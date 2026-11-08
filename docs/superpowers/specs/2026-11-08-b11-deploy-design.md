# B11 · Deploy no servidor próprio (parte sem acesso ao servidor) — design

Data: 08/nov/2026. Item: `docs/m2/trilha-b-plataforma.md` › B11. Branch: `feat/a7-b11`.

## Objetivo

Deixar pronto tudo do B11 que não precisa do servidor: o compose de produção, os scripts de backup e restauração, o rate limit do login e o passo a passo. No dia do acesso sobra rodar e medir.

## Decisões (aprovadas em 08/nov/2026)

1. **O servidor já tem proxy reverso.** O compose não leva proxy. O `docs/deploy.md` traz o trecho de nginx que o time do servidor aplica (TLS é deles).
2. **Só prod por ora.** Staging fica para quando houver um segundo servidor. O compose não muda: um `.env` por máquina.
3. **Rate limit por IP no login fica em memória**, porque há um processo uvicorn só.

## `deploy/`

- `deploy/compose.yml` (nome de projeto `gem`):
  - `postgres`: `postgres:16`, volume `pgdata`, `restart: unless-stopped`, healthcheck `pg_isready`. Sem porta publicada.
  - `migrate`: imagem `gem:${TAG}`, `command: alembic -c api/alembic.ini upgrade head`, `depends_on: postgres (service_healthy)`, `restart: "no"`.
  - `api`: imagem `gem:${TAG}`, `depends_on: migrate (service_completed_successfully)`, `restart: unless-stopped`, `env_file: .env`, volume `storage` em `STORAGE_DIR`, porta `127.0.0.1:${API_PORT:-8080}:8080`, `FORWARDED_ALLOW_IPS=*`.
  - O worker é subprocess da API e não tem serviço.
  - O `*` é seguro porque a porta só escuta em localhost: só o proxy do servidor chega nela.
- `deploy/.env.example`: `TAG`, `API_PORT`, `POSTGRES_PASSWORD`, `DATABASE_URL`, `STORAGE_DIR`, `GEMINI_API_KEY` e o que mais o `.env.example` da raiz exigir em produção (cookie `Secure`, Origin permitido). O `.env` real fica fora do git, com `chmod 600`.
- `deploy/backup.sh`: `pg_dump -Fc` pelo `docker compose exec` e tar do volume `storage`, em `${BACKUP_DIR:-/var/backups/gem}/AAAA-MM-DD/`. Apaga as pastas com mais de 7 dias. Roda com `set -euo pipefail` e sai com código ≠ 0 se algo falhar, para o cron avisar.
- `deploy/restore.sh <pasta>`: para a `api`, faz `pg_restore --clean --if-exists`, restaura o tar no volume e sobe a `api`. Pede confirmação, porque sobrescreve tudo.

## Rate limit do login (`api/auth.py` + `api/routes/auth.py`)

- Janela deslizante em memória: `dict[ip, deque[timestamps]]`, com até `LOGIN_RATE_LIMIT = 20` tentativas por `LOGIN_RATE_WINDOW = 15 min` por IP. Toda tentativa conta, com sucesso ou falha.
- Acima disso a resposta é **429** com `Retry-After` (em segundos) e a mensagem pt-BR "Muitas tentativas de login. Tente de novo em N minutos." A checagem vem antes do scrypt e antes do banco.
- O IP vem de `request.client.host`. Com `FORWARDED_ALLOW_IPS`, o uvicorn já troca esse IP pelo do `X-Forwarded-For` (o `proxy_headers` é padrão).
- O comentário `ponytail:` registra o teto: memória de um processo só. Com mais de um worker, isso vira tabela no Postgres ou limite no proxy.
- O bloqueio por conta (5 falhas → 15 min) continua igual. O rate limit só tira o ataque de bloquear o admin a partir de um IP só. Contra muitos IPs, o `create-admin` do CLI continua sendo a saída.
- O front mostra a mensagem do 429 como qualquer erro do login (`auth.ts`), se o mapeamento atual já não cobrir.
- Testes em `tests/api/test_auth.py`: a 21ª tentativa do mesmo IP leva 429 com `Retry-After`, outro IP passa, e a janela expira (relógio injetável, sem `sleep`).

## `docs/deploy.md`

1. **Pré-requisitos:** Docker com compose v2, DNS e TLS no proxy do servidor, memória de pelo menos 2 GB (até `passwords.SLOTS` = 4 scrypts de ~128 MB ao mesmo tempo, mais o motor no worker).
2. **Primeiro deploy:** clonar, copiar o `.env`, `docker build --build-arg ENGINE_VERSION=$(git rev-parse --short HEAD) -t gem:$(git rev-parse --short HEAD) .`, `TAG=… docker compose -f deploy/compose.yml up -d` e `create-admin` pelo `docker compose run --rm api python -m api.cli create-admin …`.
3. **Atualizar:** build da nova tag e `up -d` com ela. As migrations rodam sozinhas no `migrate`.
4. **Rollback:** subir a tag anterior. Se a migration nova não for reversível, restaurar o backup anterior ao deploy.
5. **Trecho do nginx:** `client_max_body_size 32m`, `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for`, `X-Forwarded-Proto`, `Host` e, na rota do log, **`proxy_buffering off` e `proxy_read_timeout` ≥ 1h**. Sem o buffering desligado, o SSE do log fica parado até o run acabar.
6. **Backup:** a linha do cron (`0 3 * * * …/deploy/backup.sh`) e como testar a restauração.
7. **Logs:** `docker compose logs -f api`, que sai em JSON por linha.

## Fica para quando houver o servidor

Teste de carga (10 runs e 30 usuários), restauração e rollback testados uma vez, homologação das 4 jornadas, guia do usuário v1. A remoção do Streamlit não se aplica, porque ele não existe neste repo.

## Docs no mesmo commit

`docs/decisoes/infra-e-operacao.md` (proxy do servidor, rate limit, backup), a tabela do `API-GUIDE.md` (429 no login), o `SECURITY.md` (rate limit), a linha `Status` do B11 em `trilha-b-plataforma.md` e o "Estado atual" do `CLAUDE.md` (só a frase do B11). O `infra-e-operacao.md` também é mexido pelo A9 (`LLM_PROVIDER=none`), então esse arquivo vai depois do rebase.
