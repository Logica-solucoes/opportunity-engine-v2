# B8 · Conectores Google Ads e GA4 — design

Data: 29/out/2026. Item: B8 em `docs/m2/trilha-b-plataforma.md`. Depende do B2 (upload, `save_file`, `save_mapping`, `validate`) e de acesso ao BigQuery, que **ainda não existe**: não há projeto GCP, dataset do DTS nem export do GA4 das contas Core.

## Objetivo e recorte

Num workspace com o conector configurado, o analista puxa investimento diário por canal (Google Ads, via Data Transfer Service) e KPI diário (export nativo do GA4) do BigQuery, para um período escolhido, sem fazer upload. O resultado vira os mesmos dois CSV canônicos de um upload e passa pelo mesmo `save_mapping` → `validate`, então o mapeamento, os parâmetros e o run não mudam. Divisão como nos itens anteriores: **B8a** (backend) e **B8b** (telas), um plano para cada.

Sem acesso real, o código é escrito contra os schemas documentados do DTS e do export do GA4. A SQL roda de verdade num **BigQuery sandbox** (grátis, só precisa de conta Google): o GA4 contra o dataset público `bigquery-public-data.ga4_obfuscated_sample_ecommerce`, que é um export real, e o Ads contra tabelas semeadas no sandbox. O aceite de ±1% contra o Google Ads UI fica pendente até haver uma conta real.

| Fora | Volta quando |
|---|---|
| OAuth nativo (Ads API + GA4 Data API, refresh token no Secret Manager) | O developer token sair. É o 7º e último da ordem de corte do README |
| Import assíncrono (job) | A query passar do timeout de 60 s com dados reais |
| Reimport agendado / dados sempre frescos | Pedido explícito. O analista importa de novo quando quiser |
| Trends do Google (Search/Trends) | Fora do "Fazer"; trends continua por upload |
| Config do conector pelo admin do workspace | Uma service account por cliente (ver Segurança) |

## Respostas do "Em aberto" do trilha-b

- **DTS no projeto Omnicom ou no do cliente?** Não importa para o código: o config guarda `projeto.dataset` completo. A service account da plataforma precisa de *BigQuery Data Viewer* no dataset (onde quer que esteja) e de *BigQuery Job User* no projeto da plataforma, que paga as queries. Fica registrado em `docs/decisoes/conectores-google.md` para o B11.
- **Quem configura o export do GA4 de cada Core?** Questão organizacional, segue com o Data Tech. Não bloqueia o código: sem o dataset do GA4, o workspace não tem conector.

## Desvios do `trilha-b-plataforma.md`

- **Período escolhido no import**, não "na criação da simulação". O botão "Importar do Google" fica na página da simulação, ao lado do upload, e importar de novo substitui os arquivos, como um novo upload.
- **Canais fora do mapa fixo** viram um canal com o próprio nome do `advertising_channel_type` (ex.: `DISPLAY`, `SHOPPING`). Nenhum spend some, e o total bate com o Google Ads UI.
- **Property id do GA4** não é campo separado: está no nome do dataset (`analytics_<property_id>`).
- **Vários customer ids por workspace**, com o spend somado por dia × canal.

---

## B8a · Backend

### Config por workspace

Em `workspaces.settings["google"]` (JSONB que já existe; sem migration):

```json
{"ads": {"dataset": "proj-omnicom.google_ads_marca", "customer_ids": ["1234567890", "9876543210"]},
 "ga4": {"dataset": "proj-cliente.analytics_123456789", "event": "purchase", "metric": "count"}}
```

Modelo pydantic `GoogleConfig` em `api/google_import.py`:

| Campo | Tipo | Regra |
|---|---|---|
| `ads.dataset` | `str` | `^[a-z][a-z0-9-]{4,28}[a-z0-9]\.[A-Za-z0-9_]{1,1024}$` (`projeto.dataset`) |
| `ads.customer_ids` | `list[str]` | 1 a 20 itens, cada um `^[0-9]{10}$` (sem hífens; a tela tira os hífens antes de enviar), sem repetição |
| `ga4.dataset` | `str` | mesmo regex do `ads.dataset` |
| `ga4.event` | `str` | `^[A-Za-z][A-Za-z0-9_]{0,39}$` (regra de nome de evento do GA4) |
| `ga4.metric` | `Literal["count", "revenue"]` | `count` = `COUNT(*)`; `revenue` = `SUM(ecommerce.purchase_revenue)` |

Os dois blocos são obrigatórios: sem Ads ou sem GA4 não há os dois arquivos que o `validate` exige.

### Segurança

- **Só o platform admin** grava o config. A service account é uma só e lê os datasets de todos os clientes. Se o admin do workspace pudesse apontar o dataset, leria os dados de outra marca, o que é vazamento entre workspaces. Fica no `SECURITY.md`.
- Nome de dataset e de tabela não pode ser parâmetro de query no BigQuery, então entra na SQL por interpolação. O regex acima é a defesa: ele roda ao gravar e de novo ao montar a SQL (`GoogleConfig.model_validate(settings["google"])`), assim um valor escrito direto no banco também não passa. Datas, evento e customer ids nos filtros vão como `QueryParameter`.
- Para quem não é platform admin, a API expõe só `google: bool`, nunca os datasets nem os customer ids.

### Rotas

| Método | Rota | Regra |
|---|---|---|
| GET | `/api/admin/workspaces` | (existente) `WorkspaceOut` ganha `google: GoogleConfig \| None` |
| PUT | `/api/admin/workspaces/{workspace_id}/google` | Platform admin. Body `GoogleConfig`; formato inválido → 422; workspace inexistente → 404. Grava em `settings["google"]` → 200 com o `WorkspaceOut` |
| DELETE | `/api/admin/workspaces/{workspace_id}/google` | Platform admin. Remove `settings["google"]` → 204 (idempotente) |
| GET | `/api/me` | (existente) `MyWorkspace` ganha `google: bool` |
| POST | `/api/w/{slug}/simulations/{simulation_id}/google-import` | Analyst+. Body `{start: date, end: date}`. Outro workspace → 404. Detalhe abaixo → 200 com o `SimulationOut` |

Validação do body do import (422): `start <= end`, `end <= hoje` (São Paulo) e período de até 1.096 dias (3 anos). A regra fica em `api/google_import.py`, e a rota só traduz exceções.

### `api/bigquery.py`

Uma função, no mesmo papel do `gemini.py` (os testes trocam por fake):

```python
def query(sql: str, params: dict[str, date | str]) -> list[dict]
```

- `bigquery.Client()` com ADC: `GOOGLE_APPLICATION_CREDENTIALS` no local, a SA anexada no Cloud Run. Projeto de cobrança: o do ADC, ou `GOOGLE_CLOUD_PROJECT` (variável padrão do cliente). Nenhuma env nova nossa; as duas entram comentadas no `.env.example`.
- `QueryJobConfig(maximum_bytes_billed=20 GB)` como teto de custo por query (`ponytail:` subir se um GA4 real passar disso) e `result(timeout=60)`.
- Dependência nova: `google-cloud-bigquery`.

### Queries

**Ads**: um bloco por customer id, unidos por `UNION ALL` e somados por fora. As tabelas são as views do DTS (`ads_CampaignBasicStats_<cid>` e `ads_Campaign_<cid>`):

```sql
SELECT date, channel_type, SUM(cost_micros) / 1e6 AS spend FROM (
  SELECT CAST(s.segments_date AS DATE) AS date, c.campaign_advertising_channel_type AS channel_type,
         s.metrics_cost_micros AS cost_micros
  FROM `{dataset}.ads_CampaignBasicStats_{cid}` s
  LEFT JOIN `{dataset}.ads_Campaign_{cid}` c
    ON c.campaign_id = s.campaign_id AND c._DATA_DATE = c._LATEST_DATE
  WHERE s._DATA_DATE BETWEEN @start AND @end
  -- UNION ALL do mesmo bloco para cada customer id
) WHERE date BETWEEN @start AND @end
GROUP BY 1, 2
```

O `_DATA_DATE = _LATEST_DATE` pega o tipo atual da campanha, que é o snapshot mais recente da tabela de dimensão. Nomes conferidos em 29/out/2026 na documentação do DTS (`docs.cloud.google.com/bigquery/docs/google-ads-transfer` e `…/google-ads-transformation`, Google Ads API v25), incluindo o `_DATA_DATE = _LATEST_DATE` da query de exemplo oficial. A doc não diz o tipo de `segments_date` (só o formato `yyyy-MM-dd`), por isso a query usa `CAST(s.segments_date AS DATE)`, que serve para `DATE` e para `STRING`. O filtro em `s._DATA_DATE` poda as partições; o filtro de fora em `date` mantém fora uma linha de outro dia. O `LEFT JOIN` mantém o spend de uma campanha ausente do último snapshot, que vira canal `UNKNOWN` em vez de sumir.

Mapeamento fixo no código (`CHANNELS`): `SEARCH→SEARCH`, `PERFORMANCE_MAX→PMAX`, `VIDEO→YOUTUBE`, `DEMAND_GEN→DEMAND_GEN`. Qualquer outro tipo vira o próprio nome. O Python soma por `(data, canal)` entre as contas e entre os tipos que caem no mesmo canal.

**GA4**:

```sql
SELECT PARSE_DATE('%Y%m%d', event_date) AS date, {COUNT(*) | SUM(ecommerce.purchase_revenue)} AS kpi
FROM `{dataset}.events_*`
WHERE _TABLE_SUFFIX BETWEEN @start_suffix AND @end_suffix AND event_name = @event
GROUP BY 1
```

`events_*` não pega as tabelas `events_intraday_*`, porque o `_TABLE_SUFFIX` delas começa com `intraday_` e fica fora do `BETWEEN` de datas `YYYYMMDD`. A expressão da métrica sai do `Literal`, nunca de texto do usuário. `SUM` de evento sem receita dá `NULL`, que vira 0.

### Materialização

1. Grade completa: todo dia de `start` a `end` × todo canal que apareceu no Ads; o que faltar vira 0. O KPI também vai a 0 nos dias sem evento. Dia sem dado e dia com zero são indistinguíveis no BigQuery, e o motor precisa da série contínua.
2. Spend todo zero no período → `InvalidInput("Nenhum investimento no Google Ads neste período.")`. KPI todo zero → `InvalidInput("Nenhum evento '<event>' no GA4 neste período.")`.
3. Escreve `data,canal,investimento` e `data,kpi` (datas ISO, ponto decimal, `csv` da stdlib) e chama o `save_file` existente para cada um. Os nomes de arquivo são `google-ads_<start>_<end>.csv` e `ga4-<event>-<metric>_<start>_<end>.csv`, e `uploaded_by` é quem importou.
4. Chama o `save_mapping` existente com `investment_file = {date_col: "data", channel_col: "canal", investment_col: "investimento"}` e `performance_file = {date_col: "data", kpi_col: "kpi"}`, mais o `generic_trends_file` do mapping atual se houver arquivo de trends. Sai com o report de validação gravado.

Antes das queries, o import lê o config, fecha a transação (`db.rollback()`, mesmo padrão do `gemini_params`) para não prender conexão durante até 2 × 60 s, e só então chama `save_file`/`save_mapping`, que travam a simulação como num upload. Uma simulação apagada no meio tem o mesmo comportamento de um upload concorrente com o apagar.

Log: `simulation.google_imported simulation_id=… start=… end=… channels=…`. O log de sucesso não leva customer id nem valores.

### Erros

| Situação | Exceção em `google_import` | Status |
|---|---|---|
| Workspace sem `settings["google"]` | `NotConfigured` | 409 "Workspace sem conector Google configurado." |
| Período inválido | pydantic | 422 |
| Sem spend ou sem KPI no período | `InvalidInput` (existente) | 422 com a mensagem (convenção do `InvalidInput`) |
| `google.api_core.exceptions.Forbidden` / `NotFound` | `SourceError` | 502 "A service account não tem acesso ao dataset ou a tabela não existe: <projeto.dataset>." |
| Teto de bytes, timeout, outro `GoogleAPIError` | `SourceError` | 502 "Não foi possível consultar o BigQuery." |
| `settings["google"]` gravado direto no banco e fora do formato | `NotConfigured` (loga o erro) | 409, sem chegar ao BigQuery |
| ADC ausente (`DefaultCredentialsError`) | `SourceError` | 502 "Conector Google sem credenciais neste ambiente." |

Todo `SourceError` loga a exceção original com `log.exception`.

### Testes (`tests/api/`)

- `test_google_import.py`, com `bigquery.query` trocado por um fake que guarda `(sql, params)` e devolve linhas prontas:
  - grade com zeros (canal sem spend num dia, dia sem KPI);
  - soma entre dois customer ids e entre tipos do mesmo canal;
  - `DISPLAY` vira canal `DISPLAY`;
  - SQL com o dataset e o `cid` certos, e datas e evento como parâmetros;
  - `revenue` usa `SUM(ecommerce.purchase_revenue)`;
  - arquivos gravados com os nomes certos, mapeamento salvo e report de validação presente;
  - mapping de trends preservado;
  - sem spend → 422; sem config → 409; período invertido, futuro e > 3 anos → 422;
  - `Forbidden` → 502 com o dataset na mensagem;
  - simulação de outro workspace → 404.
- `test_admin.py`: PUT grava e aparece no GET; DELETE remove; dataset com `` ` ``, `;` ou espaço → 422; customer id com letra → 422; o `/api/me` mostra `google: true` e não os datasets.
- `test_rbac.py`: as rotas novas na matriz (config só platform admin; import analyst+, viewer 403).
- `test_bigquery_live.py`, pulado (`skipif`) sem `BIGQUERY_TEST_PROJECT`:
  - roda a query do GA4 de verdade contra `bigquery-public-data.ga4_obfuscated_sample_ecommerce` (evento `purchase`, `count` e `revenue`, uma semana de nov/2020);
  - roda a query do Ads contra `<BIGQUERY_TEST_PROJECT>.b8_ads_seed`, semeado por `tests/bigquery/seed_ads.sql`: as duas views do DTS com 2 contas, 3 campanhas (SEARCH, PERFORMANCE_MAX, DISPLAY), uma campanha que mudou de tipo e 10 dias de dados;
  - confere somas e canais contra valores conhecidos.

  O teste semeia o `b8_ads_seed` sozinho (CTAS, que o sandbox aceita). Fora do CI; roda à mão com `BIGQUERY_TEST_PROJECT=<projeto> uv run pytest tests/api/test_bigquery_live.py` depois de `gcloud auth application-default login`.

---

## B8b · Telas

### `/admin/workspaces`: conector Google

- Cada linha ganha a ação "Conector Google" (com o selo "configurado" quando existir), que abre um `Dialog`:
  - Ads: dataset (`projeto.dataset`) e customer ids (separados por vírgula; aceita `123-456-7890`, a tela tira os hífens);
  - GA4: dataset, evento e métrica (`Select`: "Contagem de eventos" / "Receita (purchase_revenue)").
- Salvar faz o PUT, e os erros 422 aparecem por campo como no formulário de parâmetros. "Remover conector" (com confirmação) faz o DELETE.

### Página da simulação: "Importar do Google"

- Só aparece se o workspace do `meQuery` tiver `google: true`. Fica ao lado do drop de investimento/performance, como alternativa ao upload.
- Dois `<input type="date">` (início e fim; o fim começa em ontem, o início 2 anos antes) e o botão "Importar". Durante a chamada, o botão trava com "Consultando o BigQuery…".
- Sucesso: atualiza a query da simulação. Os arquivos aparecem com os nomes `google-ads_…`/`ga4-…`, e o mapeamento e o report vêm preenchidos.
- Erro 400/409/502: a mensagem da API aparece embaixo do botão.

### Verificação

- E2E (`admin.spec.ts`, `simulations.spec.ts`):
  - o platform admin configura o conector, recarrega e vê o selo;
  - o analista desse workspace vê "Importar do Google", e o de outro workspace não vê.
  
  - o import roda de verdade até o cliente do BigQuery: o E2E aponta `GOOGLE_APPLICATION_CREDENTIALS` para um arquivo inexistente, e a tela mostra "Conector Google sem credenciais neste ambiente.". SQL, grade e mapeamento ficam no pytest e no teste contra o sandbox.

  O `errorMessage` do front passa a mostrar a frase de um 5xx que traga `detail` em texto (o 502 do conector); o 5xx sem `detail` continua "Erro no servidor".
- Manual com o sandbox: configurar um workspace apontando para o `b8_ads_seed` e para o dataset público do GA4, importar e conferir arquivos, mapeamento e report. Screenshots do diálogo do admin e do import nos dois temas.

## Aceite

- [ ] Com config apontando para o sandbox, criar uma simulação sem upload e importar gera arquivos que passam no `validate`: verificação manual do B8b e `test_bigquery_live.py`.
- [ ] Total do período bate com o Google Ads UI (±1%): **pendente**, até existir acesso a uma conta Core com DTS.

## Fechamento

No commit que conclui cada parte:
- `Status` do B8 no trilha-b (com o ±1% marcado como pendente) e "Estado atual" no `CLAUDE.md`;
- as rotas na tabela do `API-GUIDE.md`;
- `settings["google"]` no `DATABASE.md` (coluna JSONB existente, chave nova);
- a regra "config do conector só pelo platform admin" no `SECURITY.md`;
- `docs/decisoes/conectores-google.md` novo (o porquê do fallback, do sandbox, do mapeamento de canais e da service account única), mais a linha no índice `docs/decisoes/README.md` e na tabela de áreas do `CLAUDE.md`;
- `google-cloud-bigquery` no `pyproject.toml` e as envs comentadas no `.env.example`.
