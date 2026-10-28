# B6 · Histórico de simulações — design

Data: 28/out/2026. Item: B6 em `docs/m2/trilha-b-plataforma.md`. Depende só do B4 (tabela `runs`, página do run, `runs.visible`).

## Objetivo e recorte

O workspace ganha uma página com todos os seus runs, com busca e filtros. A página do run passa a mostrar com o que ele rodou: parâmetros, entradas com sha256 e download, e versão do motor. O analista publica e despublica um run, e o viewer só vê o que foi publicado. "Rodar de novo" devolve os parâmetros de um run antigo à simulação. A divisão segue a do B4: **B6a** (backend) e **B6b** (telas), um plano para cada.

| Fora | Volta quando |
|---|---|
| Comparar dois runs lado a lado | A1 entrega um `summary` com métricas; hoje ele só tem `{status}`. É o 4º da ordem de corte do README |
| Modo demo (workspace "Demo" + seed) | Houver dataset anonimizado e motor real; um run do motor falso não demonstra nada |
| Colunas de métricas do `summary` na lista | A1 |
| Resultados na página do run | B5 |
| Renomear e apagar simulação (o Streamlit tem) | Pedido explícito; não está no "Fazer" do trilha-b |

## Desvios do `trilha-b-plataforma.md`

- **Filtros no front, sobre os últimos 500 runs.** A API devolve a lista, e a tela filtra por nome da simulação, status, autor e período. A busca responde na hora, as opções de autor saem da própria lista, e não há endpoint de autores nem paginação. O teto fica marcado com `ponytail:` na rota: passando de 500 runs por workspace, os mais antigos somem da busca, e a saída é mover os filtros para query params.
- **"Rodar de novo" restaura na simulação, não cria run.** O front faz `PUT …/params` com o `config` do run e leva o analista à simulação, onde ele revisa e clica Rodar. O gate da B4 continua sendo o único caminho para criar run. Os arquivos usados são os atuais da simulação, não os do run antigo.
- **Download das entradas só para analyst+.** O viewer vê o resultado publicado, não o CSV bruto do cliente. Ele vê o nome do arquivo e o sha256, mas sem link.
- **Sem colunas do `summary`.** Enquanto o motor é falso, o `summary` só repete o status.

Os quatro entram em `docs/decisoes/runs-e-jobs.md` (seção nova "Histórico e publicação (B6)", que substitui a "Viewer e publicação"), e o trilha-b recebe o `Status` no mesmo commit.

---

## B6a · Backend

Sem migration: `published_at` e `published_by` existem desde a `0004`.

### `RunOut`

O mesmo shape serve para a lista e para o detalhe. Ele ganha:

| Campo | Origem |
|---|---|
| `config` | `runs.config` (snapshot, inclui `column_mapping`) |
| `inputs` | `runs.inputs`: `{investment_file\|performance_file\|generic_trends_file: {filename, sha256} \| null}` |
| `published_at` | `runs.published_at` |
| `published_by_name` | nome de `runs.published_by`, ou `null` |

O `Run` ganha a relationship `publisher` (`foreign_keys=[published_by]`), e a lista carrega `creator`, `publisher` e `simulation` por `joinedload` para não fazer N+1.

### Rotas

| Método | Rota | Regra |
|---|---|---|
| GET | `/api/w/{slug}/runs` | Viewer+ (viewer só vê publicados, via `runs.visible`). Até 500 `RunOut`, mais recente primeiro. Roda `fail_stale` do workspace antes, como as outras leituras |
| POST | `/api/w/{slug}/runs/{run_id}/publish` | Analyst+. Só `succeeded` ou `inconclusive`; outro status → 409 "Só execuções concluídas podem ser publicadas.". Grava `published_at = now()` e `published_by`; publicar de novo atualiza os dois. → `RunOut` |
| POST | `/api/w/{slug}/runs/{run_id}/unpublish` | Analyst+. Zera `published_at` e `published_by`; idempotente. → `RunOut` |
| GET | `/api/w/{slug}/runs/{run_id}/inputs/{key}` | Analyst+. `key` ∈ `investment_file`, `performance_file`, `generic_trends_file` (outro valor → 422 pelo `Literal`). Entrada `null` no run → 404. `FileResponse` de `storage.path(simulations.input_key(workspace_id, simulation_id, sha256))` com `filename` do upload e `media_type="text/csv"` |

Run de outro workspace, ou não publicado para o viewer, é 404 em todas, pelo `find_run` que já existe. A regra de negócio (pode publicar? marca e desmarca) fica em `api/runs.py`, e a rota só traduz `runs.Blocked` em 409, como no `POST …/runs`.

### Testes (`tests/api/test_runs.py`, `tests/api/test_rbac.py`)

- Lista: ordem, escopo por workspace e viewer vendo só os publicados (antes e depois de publicar e de despublicar).
- Publish com `queued`, `running` e `failed` → 409; com `succeeded` e `inconclusive` → 200 com `published_by_name`.
- Download devolve os bytes do arquivo do snapshot mesmo depois de a simulação trocar o arquivo; `null` → 404; viewer → 403.
- Matriz papel × rota para as quatro rotas novas.

---

## B6b · Telas

### `/w/$slug/execucoes` (rota nova)

- Tabela com Simulação (texto: o viewer não abre simulações, e a página do run linka a simulação para o analista), Status (o selo que a B4b já usa), Autor, Criada em, Versão do motor e Publicada (selo). A linha leva à página do run.
- Filtros acima da tabela: busca pelo nome da simulação, status (select), autor (select com os autores da lista) e período (dois `<input type="date">` sobre `created_at`, no fuso do navegador). Todos ficam nos search params da rota (`validateSearch`), para o link manter os filtros e o voltar do navegador funcionar.
- Lista vazia → "Nenhuma execução ainda."; filtros sem resultado → "Nenhuma execução com esses filtros." com o botão "Limpar filtros".
- Os tipos e a query (`workspaceRunsQuery`) entram em `web/src/lib/runs.ts`, e os filtros em uma função pura no mesmo arquivo. É exibição, não conta do motor.

### Home do workspace (`/w/$slug/`)

- Analyst+ ganha o link "Execuções" ao lado de "Nova simulação".
- O viewer é redirecionado para `/w/$slug/execucoes` no `beforeLoad`: o histórico é a única coisa que ele vê. Isso substitui o "Nenhuma simulação ainda." que ele vê hoje.

### Página do run (`/w/$slug/execucoes/$runId`)

Abaixo do que já existe (status, log), entram três seções:

- **Parâmetros:** leitura, agrupada e rotulada com o layout de `web/src/lib/params.ts`; o `column_mapping` aparece por arquivo, como "papel → coluna".
- **Entradas:** nome do arquivo, sha256 abreviado (completo no `title`) e, para analyst+, link de download (`<a href download>` para a rota da API).
- **Publicação:** selo "Publicada por X em D" ou "Não publicada". Analyst+ vê Publicar/Despublicar; Publicar só aparece habilitado para `succeeded`/`inconclusive`, com o motivo ao lado nos outros casos. A versão do motor fica no cabeçalho do run.

**Rodar de novo** (analyst+, run terminado): um diálogo confirma "Substituir os parâmetros de *simulação* pelos desta execução?". No OK, faz `PUT …/simulations/{id}/params` com o `config` do run sem `column_mapping` (o `ParamsIn` é `extra="forbid"` e o `PUT` preserva o mapeamento salvo), invalida a query da simulação e navega até ela. Um 422 (o schema do motor mudou desde o run) aparece no diálogo com a mensagem do servidor, sem navegar.

### Verificação

- E2E (`web/e2e/`): o analista roda duas vezes, filtra a lista por status e por nome, publica um run, e o viewer vê só esse run em `/execucoes`. "Rodar de novo" restaura um parâmetro alterado na simulação.
- Screenshots da lista (com e sem filtro) e da página do run (publicada e não publicada) nos dois temas.

## Fechamento

No commit que conclui cada parte: `Status` do B6 no trilha-b, "Estado atual" no `CLAUDE.md`, as rotas novas na tabela do `API-GUIDE.md` (e a linha do `RunOut` com os campos novos) e a seção do `docs/decisoes/runs-e-jobs.md`.
