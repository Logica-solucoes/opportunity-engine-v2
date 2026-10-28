# B9 · Uso, logs e retenção — design

Data: 28/out/2026. Item: B9 em `docs/m2/trilha-b-plataforma.md`. Depende só do B4 (tabela `runs`, worker, storage por simulação).

## Objetivo e recorte

O platform admin passa a ver quantos runs cada usuário de cada workspace fez por mês, com o tempo de execução, e a exportar isso em CSV. O admin do workspace pode apagar uma simulação inteira (linhas e arquivos). Todos os logs da API e do worker saem em JSON, uma linha por evento, com `user_id`, `workspace_id` e `run_id` quando existem. A divisão segue a do B4 e do B6: **B9a** (backend, inclui os logs) e **B9b** (telas), um plano para cada.

| Fora | Volta quando |
|---|---|
| Cópia analítica no BigQuery (append do worker em 3 tabelas) | B11, quando o projeto GCP existir. É o 6º da ordem de corte do README: o Postgres basta para o M2 |
| Retenção automática (apagar dados de cliente depois de N dias) | O prazo de retenção (LGPD) sair do Data Tech. Até lá só existe o apagar manual |
| Apagar workspace ou usuário | Pedido explícito; não está no "Fazer" do trilha-b. Usuário já tem "desativar" desde o B1 |
| Uso visto pelo admin do workspace | Pedido explícito; o trilha-b fala só do platform admin |

## Desvios do `trilha-b-plataforma.md`

- **Minutos de execução no uso.** Além da contagem por status, a view soma `finished_at − started_at` dos runs terminados. É a noção de custo de Cloud Run que o platform admin vai querer, e sai da mesma tabela.
- **Status como colunas.** A view tem uma linha por workspace × usuário × mês, com uma coluna por status, em vez de uma linha por status. O CSV sai pronto para planilha.
- **Quem apaga é o admin do workspace.** O trilha-b diz "ação de admin"; o papel `admin` do workspace (e o platform admin, que o `require_role` já trata como admin) apaga as simulações daquele workspace.
- **BigQuery fora**, como na tabela acima.

Os desvios entram em `docs/decisoes/` (logs e uso em `infra-e-operacao.md`, apagar em `upload-e-storage.md`), e o trilha-b recebe o `Status` no mesmo commit.

---

## B9a · Backend

### View `usage` (migration `0005`)

`CREATE VIEW usage` sobre `runs`, uma linha por `(workspace_id, user_id, month)`:

| Coluna | Definição |
|---|---|
| `workspace_id` | `runs.workspace_id` |
| `user_id` | `runs.created_by` |
| `month` | `date_trunc('month', created_at AT TIME ZONE 'America/Sao_Paulo')::date` — o mês do negócio, não o de UTC |
| `succeeded`, `inconclusive`, `failed` | `count(*) FILTER (WHERE status = …)` |
| `active` | `count(*) FILTER (WHERE status IN ('queued', 'running'))` |
| `total` | `count(*)` |
| `run_seconds` | `coalesce(sum(extract(epoch FROM finished_at - started_at)) FILTER (WHERE finished_at IS NOT NULL AND started_at IS NOT NULL), 0)` |

Sem tabela nova: um BI pode ler a view direto. No Python ela é lida com `sqlalchemy.table("usage", column(...))`, sem model; o downgrade da migration faz `DROP VIEW`. Um run morto (`fail_stale`) conta como `failed` e, sem `started_at` ou `finished_at`, não soma tempo.

### Rotas

| Método | Rota | Regra |
|---|---|---|
| GET | `/api/admin/usage?month=YYYY-MM` | Platform admin (`require_platform_admin`; outro → 403, como as rotas de admin). Linhas da view com `workspace_name`, `user_name`, `user_email`, ordenadas por mês desc, workspace e usuário. Sem `month`, todos os meses; `month` fora do formato → 422 |
| GET | `/api/admin/usage.csv?month=YYYY-MM` | Mesma regra e mesmo filtro. `text/csv` como anexo (`uso-YYYY-MM.csv`, ou `uso.csv` sem filtro), cabeçalho em pt-BR, `run_seconds` em minutos com uma casa decimal |
| DELETE | `/api/w/{slug}/simulations/{simulation_id}` | Admin do workspace (`require_role("admin")`). Simulação de outro workspace → 404. Roda `fail_stale` da simulação; com run `queued` ou `running` → 409 "Há uma execução em andamento.". → 204 |

A regra de apagar fica em `api/simulations.py` (`delete`), e a rota só traduz o bloqueio em 409.

### Apagar: ordem e storage

1. Apaga a linha de `simulations`; `simulation_files`, `runs` e `run_logs` caem pelo `ON DELETE CASCADE` que já existe. Commit.
2. Apaga o prefixo `ws/{workspace_id}/sim/{simulation_id}/` com `storage.delete_prefix(key)` novo (`shutil.rmtree`, sem erro se não existir), que leva as entradas e os `results.json` dos runs.
3. Se o passo 2 falhar, loga `simulation.files_orphaned` como erro com o prefixo e devolve 204 assim mesmo.

O banco vai primeiro porque o contrário (arquivos apagados e linhas de pé) deixaria runs apontando para arquivos que não existem. Os arquivos órfãos de um passo 2 com falha ficam no log para limpeza manual. `delete_prefix` leva o `ponytail:` de que o B11 troca para GCS. Log `simulation.deleted` com `simulation_id` e `by`.

### Logs JSON

- **`api/logs.py`** (novo): o `JsonFormatter` sai de `api/worker.py` para cá e passa a emitir `severity`, `message`, `logger` e, quando existem, `user_id`, `workspace_id` e `run_id`. Um `logging.Filter` copia os IDs do contexto da request para o record. `setup()` põe o handler JSON no stdout para o root e para os loggers do uvicorn (`uvicorn`, `uvicorn.error`, `uvicorn.access`, que não propagam). JSON sempre, inclusive no dev, igual ao worker hoje.
- **Contexto:** um `ContextVar` guarda um `dict` de IDs. Dependência síncrona do FastAPI roda numa cópia do contexto, então um `.set()` dentro dela não chegaria à rota. Por isso um middleware cria o `dict` no começo de cada request, e quem conhece os IDs **muta** esse mesmo objeto: `active_user` (`user_id`), `require_role` (`workspace_id`) e `find_run` (`run_id`). O worker cria o seu `dict` no `execute` com `run_id`, `workspace_id` e `user_id` (o `created_by` do run), e deixa de passar `extra=ids` em cada chamada.
- **Onde liga:** `create_app()` chama `logs.setup()`; o `__main__` do worker também. O `cli.py` continua com `basicConfig` (saída de terminal para humano; a senha temporária nunca passa por log). As chamadas `log.info(...)` existentes não mudam.
- O que nunca vai para o log continua igual (`SECURITY.md`): senha, token de sessão, conteúdo de CSV.

### Testes (`tests/api/`)

- `test_usage.py`: contagens por status e `active`; mês no fuso de São Paulo (run criado às 01:00 UTC do dia 1 conta no mês anterior); `run_seconds` ignora run sem `finished_at`; filtro `month`; `month` inválido → 422; CSV com cabeçalho, minutos e nome do arquivo.
- `test_simulations.py`: DELETE apaga as linhas (simulação, arquivos, runs, logs) e a pasta no storage; run ativo → 409 e nada apagado; outro workspace → 404; falha no storage → 204 com o erro no log.
- `test_logs.py`: uma request autenticada que loga sai como uma linha JSON com `user_id` e `workspace_id`; uma rota de run inclui `run_id`; o worker loga com `run_id` sem `extra=`.
- `test_rbac.py`: as três rotas novas na matriz (DELETE só admin; uso só platform admin).

---

## B9b · Telas

### `/admin/uso` (rota nova)

- Entra no menu do admin ao lado de Workspaces e Usuários.
- `<input type="month">` no topo, começando no mês atual; vazio = todos os meses. O valor fica no search param `month`.
- Tabela: Mês, Workspace, Usuário (nome, e-mail no `title`), Concluídas, Inconclusivas, Falharam, Em andamento, Total e Tempo de execução (`run_seconds` formatado como "1 h 05 min"/"12 min" — exibição, não conta do motor).
- "Exportar CSV": `<a href download>` para `/api/admin/usage.csv` com o mesmo `month`.
- Vazio → "Nenhuma execução neste período.".

### Apagar simulação (página da simulação)

- Só para admin do workspace: uma seção "Apagar simulação" no fim da página, com o aviso de que execuções e arquivos somem junto.
- O `AlertDialog` pede para digitar o nome da simulação; o botão de confirmar só habilita com o nome exato. Confirmar é um `Button` comum (como no "Rodar de novo"), para o 409 aparecer no próprio diálogo.
- Sucesso: remove a query da simulação, invalida a lista de simulações e as de runs do workspace, e navega para `/w/$slug`.

### Verificação

- E2E: o admin do workspace apaga uma simulação com um run terminado, ela some da lista e o run some de `/execucoes`; o analista não vê a seção. O platform admin abre `/admin/uso`, vê a linha do run e baixa o CSV.
- Screenshots de `/admin/uso` e do diálogo de apagar nos dois temas.

## Fechamento

No commit que conclui cada parte: `Status` do B9 no trilha-b, "Estado atual" no `CLAUDE.md`, as rotas na tabela do `API-GUIDE.md`, a view na tabela do `DATABASE.md`, e as seções de `docs/decisoes/infra-e-operacao.md` (logs, uso) e `docs/decisoes/upload-e-storage.md` (apagar).
