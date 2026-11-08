# Infra e operação

Decisões do B0 (esqueleto), 21/out/2026, revistas em 04/nov/2026 (hospedagem).

## Hospedagem: servidor próprio, sem GCP (04/nov/2026)

O plano do M2 previa Cloud Run (service + Job), Cloud SQL, GCS, Secret Manager e Cloud Logging. O projeto GCP não saiu (dependência externa do `docs/m2/README.md`), e em 04/nov/2026 a decisão passou a ser **hospedar num servidor próprio x86-64, com Docker e sem GCP**. Tudo o que já rodava local continua igual, e as trocas que esperavam o B11 deixam de existir:

| Peça | Plano antigo (GCP) | Agora |
|---|---|---|
| API + SPA | Cloud Run service | um container da imagem única no servidor |
| Worker | Cloud Run Job | subprocess disparado pelo `api/launcher.py`, no mesmo container (o que já existe) |
| Banco | Cloud SQL | Postgres 16 em Docker no próprio servidor (o mesmo do `docker-compose.yml`) |
| Arquivos | GCS | disco local em `STORAGE_DIR` (volume do container) |
| Segredos | Secret Manager | variáveis de ambiente (`.env` no servidor, fora do git, leitura só do dono) |
| Logs | Cloud Logging | JSON no stdout, lido por `docker logs` |
| Gemini | Vertex ou API key | API key (`GEMINI_API_KEY`); Vertex descartado |
| Conector Ads/GA4 (BigQuery) | parte do M2 | **fora do escopo por ora**: o código do B8 fica, mas o dado entra só por upload de CSV |

O que muda para o B11, porque o Cloud Run fazia sozinho:

- **Limite do corpo da requisição.** O Starlette grava o corpo inteiro em arquivo temporário antes do auth e do teto de 30 MB rodarem, e quem cortava em 32 MiB era o Cloud Run. Sem ele, um POST anônimo enche o disco. **Feito em 05/nov/2026, em parte:** `api/main.py` recusa com 413 qualquer request com `Content-Length` acima de 32 MiB, antes do auth e antes de ler o corpo. Um corpo *chunked* não tem `Content-Length`, então o proxy reverso na frente da API ainda precisa limitar o corpo (ex.: `client_max_body_size 32m` no nginx). **Fechado em 08/nov/2026** pelo trecho do nginx em `docs/deploy.md`.
- **Timeout do worker.** O Job expirava em 15 min; um subprocess pendurado roda para sempre. O run é dado como morto aos 20 min (`STALE_AFTER`), mas o processo continua gastando CPU: **Feito em 05/nov/2026:** o worker liga um watchdog (`worker.watchdog`) que encerra o processo com código 1 ao passar do `STALE_AFTER`. O run já está `failed` pela regra de run morto.
- **TLS, backup do Postgres e do `STORAGE_DIR`, e restart dos containers** passam a ser nossos. Backup e restart: ver "B11 sem o servidor" abaixo; TLS é do proxy do servidor.
- **Saída HTTPS para `api.bcb.gov.br`.** Os controles do causal (A4) são buscados pela API ao criar o run; sem essa saída, todo run com controle do BCB dá 502.
- O worker roda em processo na mesma máquina da API. O `api/launcher.py` sobe o worker com `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS` e `MKL_NUM_THREADS` em 1 (um run usa ~1 núcleo, `docs/decisoes/engine.md`) e sem `LLM_PROVIDER=none` desde a A9 (08/nov/2026): com `GEMINI_API_KEY` no `.env` do servidor, o run chama o Gemini (até 2 chamadas por narrativa, `docs/decisoes/llm.md`). Mesmo assim, runs simultâneos disputam CPU com a API; uma fila entra se isso pesar.

## B11 sem o servidor (08/nov/2026)

Sem acesso ao servidor, o B11 entregou o que dá para escrever e conferir sem ele: `deploy/` (compose, `.env.example`, `backup.sh`, `restore.sh`), `docs/deploy.md` e o rate limit do login. Carga, rollback e homologação esperam o acesso.

- **O proxy é do servidor.** TLS e o limite de corpo ficam no nginx do time do servidor; o trecho está em `docs/deploy.md` (`client_max_body_size 32m`, `Host`, `X-Forwarded-*`, e `proxy_buffering off` com `proxy_read_timeout` de 1 h na rota do log por SSE). Isso fecha a pendência do corpo *chunked*.
- **Só prod.** Um compose (`deploy/compose.yml`), sem staging; o `docker-compose.yml` da raiz segue sendo o do dev.
- **`migrate` é um serviço de execução única.** Roda `alembic upgrade head` e sai; a `api` só sobe depois (`service_completed_successfully`). Atualizar é trocar o `TAG` e rodar `up -d`, que recria a api e mata runs em andamento (eles viram runs mortos aos 20 min), então se atualiza sem run ativo.
- **`FORWARDED_ALLOW_IPS=*` é seguro só porque a porta está presa a `127.0.0.1` E o nginx sobrescreve o `X-Forwarded-For` com `$remote_addr`.** Com `$proxy_add_x_forwarded_for` o cliente forjaria o IP (o uvicorn pega o primeiro item) e burlaria o rate limit.
- **Rate limit por IP no login: resolvido.** Conta só tentativas **falhas** (senha errada ou conta bloqueada), 20 por 15 min (`LOGIN_RATE_LIMIT`), na memória de um processo uvicorn; passando de 10 000 IPs o mapa é zerado (falha aberta sob enxurrada de IPs rotativos; a saída é o limite do proxy). Acerto não conta, para vários usuários atrás do mesmo NAT não se travarem. **Em aberto:** travar uma conta de propósito (5 falhas por conta, de qualquer IP). Detalhe em `docs/decisoes/auth.md`.
- **Backup local de 7 dias.** `backup.sh` grava `pg_dump -Fc` e o tar do `STORAGE_DIR` em `/var/backups/gem/AAAA-MM-DD`, no mesmo disco; copiar para fora é do time do servidor. O `restore.sh` recria o schema `public` antes do `pg_restore` (com `--clean` sobrariam tabelas de migrations mais novas que o dump e o próximo `migrate` quebraria). Sequência do restore testada num `postgres:16` descartável em 08/nov/2026 (schema recriado, dados voltam; sem o drop o `pg_restore` falha); falta testar o `restore.sh` inteiro no servidor.
- **`POSTGRES_PASSWORD` vai cru no `DATABASE_URL`**: tem de ser URL-safe (`openssl rand -hex 32`).

## Imagem única para API, SPA e worker

Um `Dockerfile` com três estágios (bun → build do `web/`, uv → venv, runtime). A API serve o `web/dist` no mesmo processo, então é um container só e **sem CORS**. O worker usa a mesma imagem com outro comando (`python -m api.worker`), e hoje roda como subprocess da API. O `Dockerfile` usa `CMD` e não `ENTRYPOINT`, para `docker run <img> <cmd>` trocar o comando sem brigar com o entrypoint. O `CMD` é shell form (`sh -c "exec uvicorn … --port ${PORT:-8080}"`) para a porta vir de `$PORT`; isso foi pensado para o Cloud Run e continua servindo.

## `COPY --chown` em vez de `chown -R`

**Sintoma:** a imagem saiu com 2.27GB. Um `RUN chown -R app:app /app` depois do `COPY` do venv criava uma segunda camada de ~820MB com os mesmos arquivos. **Decisão:** `COPY --chown=app:app` em cada cópia; nunca `chown -R` sobre o que já foi copiado. Resultado no repo antigo: 2.27GB → 1.22GB; no v2, com só as deps da API, **291MB**.

## Deps enxutas no v2

O `pyproject.toml` do v2 não tem Streamlit nem nada da UI do protótipo. **Por quê:** o Streamlit e suas dependências pesavam ~900MB e não fazem parte da plataforma. As deps analíticas (numpy, pandas, scipy, statsmodels, scikit-learn, matplotlib, holidays, google-genai) entraram com o `engine/` no A0, com versão **fixa** porque a paridade com o protótipo depende delas (`docs/decisoes/engine.md`). O `Dockerfile` copia `api/`, `engine/` e `llm/`. Falta medir o tamanho da imagem com as deps do motor (era 291MB só com a API).

## `ENGINE_VERSION` no build

O `results.json` leva `engine_version` para auditoria. A imagem não tem `.git` nem instala o projeto como pacote (`--no-install-project`), então o `git rev-parse` e o `importlib.metadata` de `engine/version.py` falham e a versão sairia `unknown`. **Decisão:** `engine_version()` lê primeiro a variável `ENGINE_VERSION`, que o `Dockerfile` recebe por `ARG`. O build de produção (B11) passa `--build-arg ENGINE_VERSION=$(git rev-parse --short HEAD)`.

## `/api/health` sempre responde 200

Reporta `db: ok|down` no corpo, mas o status HTTP não depende do banco. **Por quê:** o healthcheck do container não deve matar a API por uma queda de banco que ela pode sobreviver. `db.ping()` usa `connect_timeout=2` para não pendurar a resposta.

## SPA com fallback e 404 JSON na API

`mount_spa()` registra um catch-all depois dos routers: arquivo existente em `web/dist` é servido, qualquer outra rota devolve `index.html` (o roteamento é do TanStack Router), e `/api/*` desconhecido vira 404 JSON. O caminho é resolvido e checado com `is_relative_to(dist)` para impedir path traversal (`/..%2Fsecret`). Sem `index.html` o SPA não é montado, o que deixa a API subir em dev sem build.

## Alembic dentro de `api/`

`api/alembic.ini` e `api/migrations/`, sempre chamados com `-c api/alembic.ini`. A URL não fica no `.ini`: `env.py` importa `DATABASE_URL` de `api/db.py` e escapa `%` (o configparser interpreta como interpolação). `target_metadata = None` até o B1 criar o `Base.metadata`.

## `routeTree.gen.ts` é versionado

O CI roda `tsc -b` antes de qualquer geração do plugin do TanStack Router, então o arquivo gerado precisa estar no git. `.gitattributes` força LF nele: com `autocrlf` o checkout em CRLF deixava o arquivo sujo com diff vazio.

## CI

`.github/workflows/ci.yml` com dois jobs: `py` (`uv sync --frozen` + `uv run pytest -q`) e `web` (`bun install --frozen-lockfile`, `bunx tsc -b`, `bun run build`). `tsc -b` e não `tsc --noEmit`: o `tsconfig.json` raiz só tem `references`, então `--noEmit` não checaria nada. O teste que depende de Postgres pula no CI (não há service de banco ainda).

## Porta 5432 e o compose de dev

O `docker-compose.yml` publica `5432:5432`. **Sintoma:** com outro Postgres local na 5432 (já aconteceu), o `docker compose up` falha. Libere a porta ou troque o mapeamento no seu compose.

## Logs em JSON com os IDs da request (B9)

Uma linha JSON por evento no stdout (`severity`, `logger`, `message` e, quando existem, `user_id`, `workspace_id`, `run_id`), na API e no worker, inclusive no dev: é o formato que um coletor de log lê sem parser (era o do Cloud Logging; no servidor próprio, `docker logs`), e o dev vê o mesmo que a produção. `api/logs.py` concentra o formatter, o filtro e o `setup()`, que também troca os handlers do uvicorn (o access log incluso). O `setup()` roda no import de `api/main.py` porque o uvicorn configura os loggers dele antes de importar a app. O `cli.py` continua em texto: a saída dele é para quem está no terminal.

**Sintoma que guiou o desenho:** dependência síncrona do FastAPI roda numa cópia do contexto, então um `ContextVar.set()` feito no `require_role` não chega à rota. O middleware cria um `dict` por request no `ContextVar`, e `current_session`/`require_role`/`find_run` **mutam** esse objeto (`logs.tag`), que é o mesmo nas cópias. O worker abre o seu no `main` (`logs.scope(run_id=…)`) e completa com workspace e autor no `execute`. Nenhuma chamada `log.info` precisa passar `extra=`. O middleware não reseta o `ContextVar` ao sair: o uvicorn loga o traceback de um 500 e a linha de access log depois que o middleware retorna, e cada request roda na sua própria task, então o `dict` morre com ela.

## Uso derivado de `runs` (B9)

A view `usage` agrega `runs` por workspace × usuário × mês, com status em colunas e o tempo de execução somado: sem tabela nova, sem job de consolidação, e um BI pode ler a view direto. O mês é o de São Paulo, não o de UTC (um run às 22h do dia 31 é daquele mês). O CSV sai com `;`, vírgula decimal e BOM, o que o Excel em pt-BR abre sem assistente. Nomes e e-mails no CSV que começam com `=`, `+`, `-`, `@`, tab ou CR saem com `'` na frente (`SECURITY.md`). A cópia no BigQuery do trilha-b ficou para o B11, quando houver projeto GCP; é o 6º da ordem de corte.

Run morto conta no máximo 20 min: a view limita o fim a `created_at + 20 min` (o `STALE_AFTER` de `runs.py`), porque o `fail_stale` carimba `finished_at` só quando alguém mexe no workspace de novo, e um run que morreu na sexta e foi marcado na segunda somaria ~72 h. As rotas de uso rodam o `fail_stale` antes de ler, para o run morto não aparecer como "Em andamento".

A tela `/admin/uso` guarda o mês no search param (`month=YYYY-MM`, ou `todos`; sem o param, o mês atual do navegador). O tempo vem somado em segundos da API e a tela só formata ("1 h 05 min"). "Exportar CSV" é um link para a rota `.csv` com o mesmo filtro. O campo guarda o próprio rascunho e só navega com um mês completo ou vazio: Safari e Firefox de desktop mostram `type=month` como caixa de texto, e um valor pela metade não pode ir para a URL.
