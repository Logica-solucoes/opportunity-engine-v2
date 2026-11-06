# A4 · Controles causais livres de contaminação — design

Item `A4` de `docs/m2/trilha-a-motor.md`. Depende de A0 (pronto). Não bloqueia ninguém; a A10 audita a mudança da paridade.

## Intenção

O contrafactual do causal (`run_causal_impact_analysis`) aceita como controle qualquer coluna `Leads`, `Clicks` ou `Impressions` do arquivo de performance. Essas métricas são geradas pela própria mídia: com elas no modelo, o contrafactual absorve parte do efeito que queremos medir. O A4 tira as covariáveis da mídia, faz uma triagem por evento de todo controle exógeno (Trends e, se o analista marcar, IPCA, Selic e IBC-Br do Banco Central) e passa a seleção do Lasso para folds temporais.

## Objetivos

- Coluna `Clicks`/`Leads`/`Impressions` no arquivo de performance não muda o resultado.
- Controles candidatos: a coluna de Trends (sempre que o arquivo existir, como hoje) e as séries do BCB marcadas em `config.controls`.
- Triagem por evento: |r| entre o controle e o spend dos canais tratados no pré-período > `gate_thresholds.control_spend_corr` (default 0.5) → controle rejeitado, listado no evento.
- `LassoCV` com `TimeSeriesSplit`.
- A plataforma busca as séries do BCB na API SGS ao criar o run e grava o CSV no snapshot de entradas; o motor só lê arquivo.

## Não-objetivos

- O MMM da elasticidade (`run_opportunity_projection`) não muda: o BCB não entra nele, e o Trends continua como está.
- Mais de uma coluna no arquivo de Trends. A leitura segue com uma coluna (`Generic Searches`).
- Cache local da SGS ou fallback. SGS fora do ar bloqueia o run.
- Calibrar o limite 0.5; é da A10.
- O `placebo`, a suficiência e o WMAPE fora da amostra são do A6.

## Decisões

| Pergunta | Decisão | Por quê |
|---|---|---|
| Fonte dos controles | Trends (uma coluna) + BCB (IPCA, Selic, IBC-Br) | Decidido com o dono em 06/nov/2026. O BCB é o primeiro da ordem de corte, mas entra. |
| yfinance no lugar da SGS | Não | O Yahoo não tem IPCA, Selic nem IBC-Br; não é API oficial (scraping, quebra sem aviso, uso comercial nebuloso). A SGS é oficial, gratuita e sem chave. |
| Quem busca o BCB | A API, ao criar o run; o motor recebe `inputs["bcb_file"]` | O run fica reprodutível (o IBC-Br é revisado; o snapshot guarda o que foi usado) e o motor fica sem rede. Decidido com o dono. |
| Quem liga o BCB | O analista, por simulação: `config.controls` com ids fixos, vazio por padrão | Sem controle marcado não há chamada de rede e a paridade não sente o BCB. Decidido com o dono. |
| Séries | IPCA variação mensal `433`; Selic meta `432` (diária); IBC-Br dessazonalizado `24364` (mensal) | Dessazonalizado porque o modelo só tem sazonalidade semanal (`seasonal=7`); a mensal do IBC-Br bruto entraria como sinal falso. |
| Mensal → cadência do run | Forward-fill: o valor do mês vale em todos os dias dele | Interpolação linear usaria no meio do mês o valor do mês seguinte. Forward-fill é mais simples e não olha para a frente. |
| Janela da busca | Últimos 10 anos até hoje, uma chamada por série | A SGS limita série diária a 10 anos por consulta. `ponytail:` dado com mais de 10 anos quebra; aí busca em pedaços. |
| SGS falhou | 502 em pt-BR, run não é criado | O run nunca sai diferente do que o analista pediu. Decidido com o dono. |
| Onde a triagem roda | Dentro de `run_causal_impact_analysis`, por evento | O pré-período e os canais tratados são do evento; o `validate` não os conhece. |
| Spend do evento | `event_investment_series` (soma dos canais do evento, cru) no pré-período | É a série que define o evento; adstock/Hill não mudam a correlação de interesse (controle que anda junto com o gasto). |
| Correlação indefinida (série constante) | `corr = null`, controle aceito | Controle constante já cai no `VarianceThreshold`; spend constante não tem o que contaminar. |
| Folds do Lasso | `TimeSeriesSplit(n_splits=min(5, len(pre) // 4))`, mínimo 2 | O pré-período pode ter só 8 linhas (semanal); 5 folds não cabem. |
| Nome do controle no `results.json` | Ids estáveis: `trends`, `bcb_ipca`, `bcb_selic`, `bcb_ibc_br` | O front e a A9 usam o id; o nome de exibição fica no front. |

## Motor

### `engine/analysis.py`

- Apagar o bloco `possible_covariates` e o merge do `performance_df`. O parâmetro `performance_df` sai de `run_causal_impact_analysis` (e dos chamadores em `engine/pipeline.py`).
- A lista `potential_exog_vars` deixa de casar `"generic" in col.lower()`: vira canais transformados + calendário (`day_*`, `is_weekend`, `is_payday_period`, `is_holiday`) + os controles aceitos pela triagem.
- Triagem: para cada controle candidato presente em `model_data`, `r = pre[controle].corr(event_investment_series[pre])`. `|r| > limite` → rejeitado.
- O evento devolve a lista `[{name, corr, accepted}]`; `results.py` publica.
- `LassoCV(cv=TimeSeriesSplit(...), random_state=0, max_iter=10000)`.

### `engine/config.py`

- `controls: list[Literal["bcb_ipca", "bcb_selic", "bcb_ibc_br"]]`, sem repetição, default `[]`.
- `GATE_DEFAULTS = {"collinearity_r": 0.85, "control_spend_corr": 0.5}`.

### `engine/inputs.py`

- Entrada opcional `bcb_file`: CSV `Date,<id>…` em formato fixo (gerado pela plataforma, fora do `column_mapping`: não é arquivo do usuário). Lido, ordenado por data e reamostrado com forward-fill para os dias do run; fica junto das tendências no `model_data`.
- `controls` não vazio sem `bcb_file`, ou sem a coluna de um controle pedido → `EngineError`: "Controle do Banco Central pedido sem a série: <id>."
- `python -m engine` aceita `bcb_file` no JSON de entrada.

### `engine/results_schema.py`

- `CausalControl(name: str, corr: float | None, accepted: bool)`.
- `CausalEvent.controls: list[CausalControl] = []` (aditivo; o B5 ignora).
- Evento com controle rejeitado: `reasons` ganha `control_rejected`. Não muda o `status` do evento: o controle sai, o evento segue.

## Plataforma

### `api/bcb.py` (novo)

- `SERIES = {"bcb_ipca": 433, "bcb_selic": 432, "bcb_ibc_br": 24364}`.
- `fetch(controls: list[str]) -> bytes`: um GET com `httpx` por série (`https://api.bcb.gov.br/dados/serie/bcdata.sgs.{código}/dados?formato=json&dataInicial=…&dataFinal=…`), timeout de 10 s, e junta tudo num CSV com data ISO.
- Timeout, HTTP de erro, JSON inválido ou série vazia → `BcbUnavailable`.
- Trocado por fake nos testes, como `api/gemini.py` e `api/bigquery.py`.

### `api/runs.create`

- Com `simulation.config["controls"]` não vazio, chama `bcb.fetch` **antes** do `simulations.lock` (sem segurar o lock na rede), grava com `storage.put` no esquema de `simulations.input_key` e põe `inputs["bcb_file"] = {"sha256": …, "filename": "bcb.csv"}`.
- `BcbUnavailable` → a rota devolve 502: "Não foi possível buscar as séries do Banco Central. Tente de novo ou desmarque os controles." Nenhum run é criado.
- O worker não muda: ele já monta as entradas de qualquer chave do `run.inputs`.
- "Rodar de novo" busca de novo.
- Download das entradas do snapshot (B6): `InputKey` em `api/routes/runs.py` é uma `Literal` fixa e ganha `bcb_file`; a lista de entradas na página do run ganha o rótulo "Séries do Banco Central".

### Formulário

- `controls` entra em `api/engine_config.py › ANALYST_FIELDS`.
- `web/src/lib/params.ts`: grupo de checkboxes "Controles macro (Banco Central)" com IPCA, Selic e IBC-Br. O formulário hoje só conhece enum de valor único; o widget de lista de enum é novo.

## Conflitos conhecidos

- `api/runs.py`: o A8 também mexe; o trecho do A4 fica no começo do `create`, longe do dele.
- `ANALYST_FIELDS` e `params.ts`: a tela de agrupamento por colinearidade adiciona `channel_groups`/`block_per_channel` nas mesmas listas. Conflito de linha vizinha.
- Parágrafo "Estado atual" do `CLAUDE.md`: todo item mexe.

## Testes

Motor (`tests/engine/test_controls.py`, novo):
- performance com `Clicks`/`Leads`/`Impressions` → mesmo `results.json` que sem elas;
- controle = spend do canal tratado + ruído → `accepted=false`, `control_rejected` no evento;
- controle independente do spend → aceito;
- `bcb_file` mensal → diário por forward-fill (o valor de 15/mar é o de março);
- `controls=["bcb_ipca"]` sem `bcb_file` → `EngineError`;
- `TimeSeriesSplit` com pré-período curto não quebra (8 linhas).

Paridade: regenerar `tests/fixtures/parity/snapshot.json` só depois de medir o que mudou (o sintético não tem covariáveis de mídia nem BCB; mudam o `TimeSeriesSplit` e, se rejeitado, o Trends). Registrar a diferença em `docs/decisoes/engine.md` para a A10.

API (`tests/api/test_runs.py`):
- com controles e SGS falsa → `inputs["bcb_file"]` no run e o arquivo no storage;
- SGS falsa com erro → 502, nenhum run criado;
- sem controles → SGS não é chamada.
- `tests/api/test_bcb.py`: o CSV montado a partir de respostas da SGS gravadas (sem rede).

E2E (`web/e2e/simulations.spec.ts`): marcar IPCA, salvar, recarregar e ver marcado.

## Docs no mesmo commit

- `docs/decisoes/engine.md`: por que a plataforma busca, forward-fill, ids das séries, diferença da paridade.
- `docs/m2/trilha-a-motor.md`: linha `Status` do A4.
- `CLAUDE.md`: "Estado atual"; `api/bcb.py` no mapa da estrutura.
- `API-GUIDE.md`: o 502 do `POST …/runs`.

## Em aberto

- Limite 0.5 da triagem: chute da trilha; calibrar na A10.
- Câmbio (SGS `1`) como quarto controle: fora por ora; entra trocando a `Literal` e o `SERIES`.
