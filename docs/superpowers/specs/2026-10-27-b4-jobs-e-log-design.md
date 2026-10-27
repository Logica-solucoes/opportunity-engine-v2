# B4 · Jobs assíncronos e log em tempo real — design

Data: 27/out/2026. Item: B4 em `docs/m2/trilha-b-plataforma.md`. Contrato do `engine.run` em `docs/m2/README.md` › contrato §3.

## Objetivo e recorte

Com arquivos validados e parâmetros salvos, o analista clica em Rodar. A API cria um run com snapshot do config e dos inputs e dispara o worker em outro processo. O worker roda o motor e grava cada linha de log no banco. A tela do run mostra o log ao vivo por SSE e retoma de onde parou ao reabrir. Dividido como o B2 e o B3: **B4a** (backend) e **B4b** (tela), cada um com seu plano.

| Fora | Volta quando |
|---|---|
| Launcher do Cloud Run Jobs | B11, junto com GCS e Secret Manager |
| `engine.run` real e tradução do log (`_RULES` do protótipo) | A0/A1; o fake já emite em pt-BR |
| Publicar/despublicar e viewer vendo runs | B6; as colunas `published_at/by` já entram |
| Lista de runs do workspace, comparar, "rodar de novo" | B6 |
| Dashboards do resultado | B5; a página do run mostra só status e resumo |
| Logs JSON estruturados na API | B9; o B4 faz só o worker |

## Desvios do `trilha-b-plataforma.md`

- **`engine.run` falso em `api/`.** O A0 ainda não entregou o `engine/`. `api/engine_run.py` segue a assinatura do contrato §3; quando o motor existir, vira `from engine import run`. Mesmo caminho do `validate` (B2) e do `EngineConfig` (B3).
- **Só o launcher local.** Sem projeto GCP não há como testar o Cloud Run Jobs de verdade; uma implementação só com mock seria aparência. `launcher.launch(run_id)` é o ponto único de troca no B11.
- **Rotas sob o workspace.** O trilha-b cita `GET /api/runs/{id}/logs/stream`; a regra do `API-GUIDE.md` põe dado de cliente sob `/api/w/{slug}/…`.
- **Sem coluna de heartbeat.** O Job tem timeout de 15 min, então run ativo com `created_at` há mais de 20 min está morto por definição. A API marca esses runs como `failed` de forma preguiçosa (ao ler e ao criar run), e o worker só grava o resultado se o status ainda for `running`.
- **Insert por linha de log, sem lote de 0,5 s.** O motor emite centenas de linhas, não milhares. O lote atrasaria a última linha antes de uma etapa longa, que é a que alimenta o "em andamento há N s". O teto fica marcado com `ponytail:` (lote se o motor ficar verboso).
- **Um run ativo por simulação.** Índice único parcial no banco; duplo clique não vira dois jobs pagos.

Os seis entram em `docs/decisoes/runs-e-jobs.md` (novo, com linha no índice `docs/decisoes/README.md`), e o trilha-b é corrigido no mesmo commit.

---

## B4a · Backend

### Tabelas (migration `0004`)

`runs`

| Coluna | Tipo | Nota |
|---|---|---|
| `id` | `bigint identity` PK | |
| `workspace_id` | `bigint` FK `workspaces` `ON DELETE CASCADE`, indexado | desnormalizado: escopo direto nas rotas de run e na view de uso do B9 |
| `simulation_id` | `bigint` FK `simulations` `ON DELETE CASCADE`, indexado | |
| `status` | enum `run_status`: `queued`, `running`, `succeeded`, `inconclusive`, `failed` | |
| `config` | `jsonb` | snapshot de `simulations.config` na criação |
| `inputs` | `jsonb` | `{"investment_file": {"sha256", "filename"}, "performance_file": {…}, "generic_trends_file": {…} \| null}` |
| `confirmed_warnings` | `jsonb` | lista de `check.id` que o analista confirmou |
| `engine_version` | `text` null | do `results.json` |
| `results_uri` | `text` null | chave do storage |
| `summary` | `jsonb` null | por ora `{"status"}`; B6/A1 definem as métricas |
| `error` | `text` null | mensagem pt-BR para a tela |
| `published_at` | `timestamptz` null | B6 |
| `published_by` | `bigint` FK `users` null | B6 |
| `created_by` | `bigint` FK `users` | |
| `created_at` | `timestamptz` default `now()` | |
| `started_at`, `finished_at` | `timestamptz` null | |

Índice único parcial `runs_one_active_per_simulation` em `(simulation_id) WHERE status IN ('queued', 'running')`.

`run_logs`

| Coluna | Tipo |
|---|---|
| `id` | `bigserial` PK |
| `run_id` | `bigint` FK `runs` `ON DELETE CASCADE`, indexado |
| `ts` | `timestamptz` default `now()` |
| `level` | `text` (`info`, `warning`, `error`) |
| `message` | `text` |

Os mapeamentos ficam em `api/models.py` (`Run`, `RunLog`), e as duas tabelas entram na tabela do `DATABASE.md`.

### Regra do run morto

`STALE_AFTER = 20 min` (constante em `api/runs.py`, com o porquê: timeout de 15 min do Job). `fail_stale(db, where)` faz `UPDATE runs SET status='failed', error='A execução parou de responder.', finished_at=now() WHERE status IN ('queued','running') AND created_at < now() - STALE_AFTER AND <where>`. É chamada antes de criar run (para a simulação), antes de ler um run e a lista da simulação, e a cada volta do stream.

### `engine.run` falso (`api/engine_run.py`)

```python
def run(inputs: dict[str, Path | None], config: dict, out_dir: Path, on_log: Callable[[str, str], None]) -> dict
```

- `inputs` tem as mesmas chaves do `validate` (`investment_file`, `performance_file`, `generic_trends_file`).
- Chama `on_log(level, message)` em umas 6 etapas em pt-BR (ex.: "Lendo os arquivos", "Detectando eventos de investimento", "Ajustando o modelo de elasticidade", "Montando cenários"), com `time.sleep(FAKE_ENGINE_STEP_SECONDS)` entre elas (env, default `1`, `0` nos testes).
- Com `FAKE_ENGINE_FAIL=1`, levanta `RuntimeError` em inglês no meio, para provar que a mensagem crua não chega à tela.
- Devolve `{"schema_version": 1, "engine_version": "fake", "status": "succeeded", "validation": None, "causal": None, "elasticity": None, "experiment_design": None, "reports": None}`.

A forma `on_log(level, message)` é proposta ao dev A no `docs/m2/README.md` › contrato §3, no mesmo commit.

### Launcher (`api/launcher.py`)

```python
def launch(run_id: int) -> None:
    # ponytail: local subprocess only; Cloud Run Jobs launcher comes in B11
    subprocess.Popen([sys.executable, "-m", "api.worker", str(run_id)])
```

Não espera o processo. Nos testes de rota ele é trocado por monkeypatch (registra o id); os testes do worker chamam a função do worker in-process.

### Criar run

`POST /api/w/{slug}/simulations/{simulation_id}/runs`, analyst+, corpo `{"confirmed_warnings": ["check_id", …]}` (default `[]`).

1. `simulations.lock` na simulação (escopada pelo workspace; outra → 404), depois `fail_stale` dela.
2. Gate, 409 com `detail` em pt-BR (as mesmas frases do `runBlockReason` da tela):
   - `validation` nulo → "Valide os arquivos antes de rodar."
   - `validation.ok` falso → "Corrija os erros antes de rodar."
   - algum check `warning` cujo `id` não está em `confirmed_warnings` → "Confirme os avisos antes de rodar."
   - `"optimization_target" not in config` (mesma regra do `paramsSaved` do front) → "Salve os parâmetros antes de rodar."
   - insert bate no índice parcial (`IntegrityError`) → "Já há uma execução em andamento nesta simulação."
3. Insere o run `queued` com o snapshot de `config` e de `inputs` (de `simulation_files`), commit, `launcher.launch(run.id)`.
4. `launch` levantou `OSError` → o run vira `failed` com "Não foi possível iniciar a execução." e o erro vai para o log.
5. Responde `201` + `RunOut`.

As quatro primeiras frases são as do `runBlockReason` em `web/src/lib/simulations.ts`; o último retorno dele ("Execução disponível em breve") sai no B4b.

### Worker (`api/worker.py`)

`python -m api.worker <run_id>`; sem argumento, lê `RUN_ID` do env (forma do Cloud Run Job no B11).

1. Em transação: `UPDATE runs SET status='running', started_at=now() WHERE id=:id AND status='queued' RETURNING …`. Nenhuma linha → loga e sai (worker idempotente; run já pego ou morto).
2. Caminhos dos inputs pela mesma chave do B2 (`ws/{workspace_id}/sim/{simulation_id}/inputs/{sha256}.csv`, `storage.path`).
3. `engine_run.run(inputs, config, tmpdir, on_log)`. O `on_log` insere uma linha em `run_logs` e faz commit na sessão do worker, que fica ociosa entre as linhas (uma sessão só deixa o worker testável com a transação do pytest).
4. Sucesso: `storage.put` de `results.json` em `ws/{w}/sim/{s}/runs/{r}/results.json`; grava `status = results["status"]`, `engine_version`, `results_uri`, `summary = {"status": …}`, `finished_at`.
5. Exceção: `log.exception` (traceback no stdout), linha `error` em `run_logs` e `runs.error` com "O motor falhou. Detalhes técnicos ficam no log do servidor (execução {id})."; `status = failed`. A mensagem da exceção nunca vai para o banco: pode estar em inglês ou carregar dado. Fica a pergunta ao dev A (no README › contrato §3): uma exceção do motor com mensagem pt-BR própria para a tela.
6. A gravação final (4 ou 5) é `UPDATE … WHERE id=:id AND status='running'`: um run que a API já marcou como morto não ressuscita.

Stdout em JSON: um `logging.Formatter` stdlib no worker emite `{"severity", "message", "run_id", "workspace_id"}` por linha (e `exc_info` formatado no campo `message` quando houver). O B9 leva o formato para a API.

### Leitura

Papel viewer+ nas três rotas, mas o viewer só enxerga run com `published_at` não nulo (ninguém, até o B6); analyst e admin veem todos. Run de outro workspace ou invisível para o papel → 404.

- `GET /api/w/{slug}/runs/{run_id}` → `RunOut`: `id`, `status`, `simulation: {id, name}`, `created_by_name`, `created_at`, `started_at`, `finished_at`, `error`, `summary`, `engine_version`.
- `GET /api/w/{slug}/simulations/{simulation_id}/runs` → lista de `RunOut` da simulação, mais recente primeiro, até 20.
- `GET /api/w/{slug}/runs/{run_id}/logs/stream` → `text/event-stream` (`StreamingResponse` com gerador síncrono):
  - auth e escopo checados antes de abrir o stream (401/404 normais);
  - ponto de partida: header `Last-Event-ID` → linhas com `id > last`; sem header → as 300 últimas;
  - laço: abre uma sessão curta (não segura conexão do pool por até 15 min), roda `fail_stale` do run, busca até 500 linhas novas, emite cada uma como `id: {id}\ndata: {"ts", "level", "message"}\n\n`; se o run está num status final e não há linha nova, emite `event: end\ndata: {"status"}\n\n` e fecha; senão dorme 0,5 s;
  - headers `Cache-Control: no-store` e `X-Accel-Buffering: no`.

As quatro rotas entram na tabela do `API-GUIDE.md` e na matriz do `tests/api/test_rbac.py`.

---

## B4b · Tela

### Simulação (`/w/$slug/simulacoes/$id`)

- Rodar fica habilitado quando `runBlockReason` vem vazio. O estado de confirmações continua por índice; no submit, os índices viram `check.id`. No 201, navega para o run.
- 409 mostra o `detail` ao lado do botão.
- Bloco "Execuções" abaixo do botão: status, data, autor e link para cada run da simulação.
- Com run `queued`/`running` na lista, `runBlockReason` ganha "Já há uma execução em andamento." com link para ela.

### Run (`/w/$slug/execucoes/$runId`)

- Cabeçalho: nome da simulação (link de volta), selo de status (Na fila, Rodando, Concluída, Inconclusiva, Falhou), autor, horário de criação.
- Painel monoespaçado com as últimas 300 linhas (`ts` em hora local, `message`); `error` em vermelho, `warning` em âmbar. Acompanha o fim só se o usuário já estava no fim.
- "Etapa em andamento há N s": agora menos o `ts` da última linha, atualizado a cada 1 s enquanto o run está ativo.
- No `end`: invalida a query do run. `failed` mostra um card com `runs.error`; `succeeded`/`inconclusive` mostram "Execução concluída. Os dashboards chegam em breve."
- O `EventSource` fechado sem `end` (401, 404) mostra "Não foi possível acompanhar o log."
- `useRunLog(slug, runId)` em `web/src/lib/runs.ts`, sobre o `EventSource` nativo (cookie same-origin, reconexão com `Last-Event-ID` automática). Tipos e rótulos de status no mesmo arquivo.

Componentes: só o shadcn já instalado (`Badge`, `Card`, `Button`, `Table`, `Alert`); o painel é uma `div` com `overflow-auto` e altura fixa.

---

## Testes

### Aceite do trilha-b

| Aceite | Verificação |
|---|---|
| Dois runs simultâneos em workspaces diferentes não misturam log nem arquivo | pytest: dois workspaces, um run em cada, workers rodados; o stream de cada um traz só as próprias linhas; `results_uri` de cada um começa com o `ws/{id}/` do próprio workspace; GET e stream do run de um pelo slug do outro → 404 |
| Fechar a aba e voltar retoma o log de onde estava | pytest: com `Last-Event-ID: N`, o stream devolve só `id > N`; sem header, as 300 últimas de um run com 350; `end` no fim. E2E: recarregar a página do run no meio da execução e o log segue até "Concluída" |
| Erro do motor aparece em pt-BR no painel, com traceback só no Cloud Logging | pytest: `FAKE_ENGINE_FAIL=1` → run `failed`, `runs.error` e a última linha de `run_logs` com a frase pt-BR; a mensagem crua do `RuntimeError` e o traceback estão no stdout JSON (capsys) e ausentes de `run_logs` e `runs` |

### Demais (pytest, `tests/api/test_runs.py`)

- Cada caso do gate → 409 com a frase; um run sem warnings e com params salvos → 201, `launch` chamado com o id.
- Snapshot: editar params depois de criar o run não muda `runs.config`; `inputs` traz o sha256 dos arquivos.
- `launch` levantando `OSError` → 201 com o run `failed` e a frase.
- Segundo POST com run ativo → 409; depois do run terminar, um novo POST → 201.
- Run com `created_at` há 21 min → GET devolve `failed` com "A execução parou de responder." e um novo POST passa.
- Worker com run que não está `queued` não faz nada; worker que termina depois de o run ser marcado morto não muda o status.
- Viewer → 404 no GET e no stream de um run não publicado.
- Rotas novas na matriz de `test_rbac.py`.

### E2E (`web/e2e/runs.spec.ts`, subprocess real)

O servidor do E2E sobe com `FAKE_ENGINE_STEP_SECONDS=0.3`. Fluxo: criar simulação → upload dos templates → mapeamento → salvar parâmetros → Rodar → página do run com linhas aparecendo → recarregar → "Concluída"; voltar para a simulação e ver o run na lista. O caminho de falha fica no pytest (a env do servidor E2E é global).

Screenshots da página do run (rodando e concluída) e do bloco "Execuções" nos dois temas.

## Docs no mesmo commit

- `docs/decisoes/runs-e-jobs.md` (novo) e linha no `docs/decisoes/README.md`.
- `API-GUIDE.md` (4 rotas), `DATABASE.md` (`runs`, `run_logs`).
- `docs/m2/README.md` › contrato §3: forma do `on_log` e a pergunta da exceção pt-BR.
- `docs/m2/trilha-b-plataforma.md`: linha `Status` do B4 e os desvios.
- `CLAUDE.md`: "Estado atual" e a linha `runs-e-jobs.md` na tabela de áreas.
