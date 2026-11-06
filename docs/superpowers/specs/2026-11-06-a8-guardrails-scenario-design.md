# A8 · Guardrails do planner e `engine.scenario` — design

Item `A8` de `docs/m2/trilha-a-motor.md`, junto com a rota da Trilha B que o expõe (`GET …/runs/{id}/scenario`, contrato §4 do `docs/m2/README.md`). Depende de A1 e A5 (prontos); destrava o slider e os filtros do B5.

## Intenção

O planner de hoje projeta um número seco por ponto, deixa a curva individual passar do cap de extrapolação, não avisa quando a projeção sai da faixa histórica e manda subir 50% de verba de uma vez, o que zera o aprendizado do Smart Bidding. E a filtragem interativa (orçamento, CPA, iCPA, ROAS, iROAS, KPI mínimo, % incrementalidade) mora no Streamlit, fora do motor. A A8 põe banda de confiança e flag de extrapolação em todo ponto, transforma mudança grande em degraus (`ramp`), acrescenta a nota de tCPA/tROAS e move a filtragem para `engine.scenario`, que a API expõe ao slider.

## Objetivos

- `kpi_lo`/`kpi_hi` (p5/p95 do bootstrap) em toda linha da `response_curve`, em todo cenário e em todo ponto das curvas individuais (`lo`/`hi`).
- `extrapolated` em toda linha da curva, cenário e ponto de curva individual.
- Curvas individuais respeitando o cap por canal (`per_channel_investment_limit_factor`).
- `ramp` em todo cenário cujo investimento difere do atual por mais de `max_budget_step`.
- `notes` com o texto fixo de tCPA/tROAS em todo cenário que muda o investimento.
- `engine.scenario(results, filters) -> dict`, puro sobre o `results.json`, com a semântica de filtro do Streamlit e saída mensal.
- Rota `GET /api/w/{slug}/runs/{run_id}/scenario`.

## Não-objetivos

- Status de learning/budget-limited do Google Ads: depende do conector, que está fora do escopo (2º da ordem de corte).
- Re-otimizar o mix por filtro. O Streamlit também não faz: o filtro só escolhe pontos da curva já simulada.
- Unificar a escolha dos 6 cenários do `run` (`strategic_limit` com `financial_targets` da config) com o filtro do `scenario`. As regras diferem (o `run` exige investimento acima do atual e cai no `investment_limit_factor`), e mudar isso mexe na paridade que a A10 audita.
- Telas (B5) e o endpoint que serve o `results.json` inteiro (B5).
- Regenerar os fixtures do A1: precisa da Gol. O `scenario` aceita banda nula.

## Decisões

| Pergunta | Decisão | Por quê |
|---|---|---|
| Onde a banda é calculada | No `run`, gravada no `results.json`; a matriz do bootstrap não é persistida | A curva é fixa (100 pontos de 0 a `investment_limit_factor` × o atual) e o filtro só escolhe pontos dela; nada no `scenario` precisa do modelo. |
| Que incerteza a banda carrega | p5/p95 das 200 reamostragens dos coeficientes da Ridge, com Hill, adstock e scaler fixos (o modelo não tem intercepto) | É o que o bootstrap do A5 já guarda (`coef_samples`). Sai otimista (não propaga a incerteza de K, n e α); registrado para a A10. |
| Mix de cada banda | O mix que o ponto usa: estratégico na curva agregada, histórico no `current`, `optimized_mix` no `max_efficiency`, realocado no `strategic_reallocation`, demais canais na média nas curvas individuais | A banda é do mesmo número que o ponto publica. |
| O que é `extrapolated` | Total por período fora do `[min, max]` histórico do total, ou spend de algum canal (no mix daquele ponto) fora do `[min, max]` histórico do canal | "Fora da faixa histórica de spend (por canal e total)" da trilha; abaixo do mínimo também é extrapolação. |
| Curva individual com o cap | Sai o bypass do `rec_spend * 1.2` (`elasticity_analysis.py:976-981`); a curva vai até `min(média × investment_limit_factor, máx histórico × per_channel_investment_limit_factor)` | A trilha pede que as curvas individuais respeitem o cap. |
| Forma do `ramp` | Degraus compostos de no máximo `max_budget_step` a partir do `current`: +50% com 20% → 1,2 → 1,44 → 1,5 (3 degraus); vale para baixo (−50% → 0,8 → 0,64 → 0,5) | "Uma lista de degraus de no máximo 20%" medida contra o degrau anterior, que é o que o Smart Bidding vê. |
| Conteúdo do degrau | `{step, investment, kpi, kpi_lo, kpi_hi}`, com KPI e banda interpolados (linear) na `response_curve` | O B5 mostra os degraus na tabela de cenários; a curva já tem os números. |
| Texto das notas | Fixo em pt-BR, um por modo: tCPA (conversões) ou tROAS (receita), dizendo que a mudança de verba pode pedir ajuste do alvo e que é preciso esperar o período de aprendizado antes de ler o resultado ou dar o próximo degrau | BRD › Technical Review §5 ("bid-strategy notes"). Sem número de dias: o período depende da campanha. |
| Unidade do `scenario` | Filtros e saída mensais (× 30 / `validation.period_days`); o `results.json` continua por período | Decidido com o dono em 06/nov/2026: o Streamlit e os filtros são mensais, os fixtures do A1 não mudam e o front não faz conta. |
| Ponto recomendado | O de maior investimento entre os que passam em todos os filtros; nenhum passa → `recommended: null` | Semântica do Streamlit (`streamlit_app.py:2208-2235`); aceite de paridade. |
| Ponto de saturação | Regra do `find_saturation_point` (`dashboard_charts.py:15-62`) sobre a curva inteira, a partir do investimento atual, com fallback no recomendado (ou no último ponto, se não houver recomendado) | Mesma regra do Streamlit. O fallback do Streamlit é o recomendado; sem recomendado ele nem mostra a tabela. |
| Base dos incrementais no `scenario` | O cenário `current` do `results.json` | É a média histórica simulada com o mix histórico, o mesmo baseline da curva. O Streamlit usa um baseline recalculado dos CSV; a diferença é registrada no teste de paridade. |
| Paridade do motor com o protótipo | O teste compara só as colunas e chaves do protótipo; as novas da A8 (`KPI_Lo`, `KPI_Hi`, `Extrapolated`) saem antes do `assert_close` | Os números do protótipo não mudam; só ganham colunas. Mudança intencional, registrada para a A10. |
| Cache do `results.json` na rota | Nenhum: lê do storage a cada request | O fixture da Gol tem 870 KB; o parse cabe nos 500 ms do slider. Cache entra se o tempo medido pedir. |

## Abordagens consideradas

- **`run` grava banda e flags; `scenario` puro sobre o `results.json` (escolhida).** Sem modelo nem matriz em disco, testável com o fixture, rápido.
- **Persistir a matriz e o modelo, re-simular por request.** Permitiria re-otimizar o mix por filtro, coisa que o Streamlit não faz; exige guardar modelo e scaler e é ordens de grandeza mais lento.
- **Pré-calcular combinações de filtro.** Inviável com filtros contínuos.

## Desenho

### Motor: banda, extrapolação, cap (`engine/elasticity_analysis.py`)

Ao lado do `simulate_kpi`, dentro de `generate_aggregated_response_curve`:

```python
def kpi_band(total_spend, mix) -> tuple[float, float]:
    # features do ponto (cap, adstock, Hill, scaler, clip em 0) uma vez;
    # kpi_b = organic_baseline_mean + coef_samples[b] · features; devolve p5, p95

def is_extrapolated(total_spend, mix) -> bool:
    # total fora do [min, max] histórico do total por período,
    # ou total * mix[ch] fora do [min, max] histórico de algum canal
```

- `res_df` ganha `KPI_Lo`, `KPI_Hi` e `Extrapolated` (mix estratégico de cada linha).
- `baseline_point`, `max_efficiency_point`, `strategic_reallocation_point` e `strategic_limit_point` ganham as mesmas chaves, com o mix que cada um usa. `diminishing_return_point` e `saturation_point` (de `analysis.py`) são linhas da curva e herdam as colunas.
- `generate_individual_response_curves`: sem o bypass; cada ponto ganha `KPI_Lo`, `KPI_Hi` e `Extrapolated` (spend do canal fora do `[min, max]` dele), com os demais canais na média.

O `coef_samples` está no espaço escalado, o mesmo do `mkt_model.coef_`: o produto com as features escaladas dá a contribuição direto.

### Motor: `ramp` e notas (`engine/scenario.py`)

```python
def ramp(current: float, target: float, max_step: float, curve: list[dict]) -> list[dict] | None:
    # None se |target/current − 1| <= max_step (ou current <= 0);
    # senão degraus current·(1±max_step)^k, o último cortado no target;
    # cada um {step, investment, kpi, kpi_lo, kpi_hi}, com np.interp na curva (kpi_lo/hi nulos ficam nulos)

def bid_note(revenue_mode: bool) -> str
```

O `results.py` usa as duas para preencher `Scenario.ramp` e `Scenario.notes` dos 6 cenários (em unidade por período), e o `scenario` usa as mesmas na saída mensal. `Scenario` ganha `notes: list[str] = []`. `Scenario.kpi_lo/kpi_hi/extrapolated`, `ResponseRow.kpi_lo/kpi_hi/extrapolated` e `CurvePoint.lo/hi/extrapolated` já existem no schema: o `results.py` passa a preenchê-los. Campo opcional novo não muda `schema_version`.

### Motor: `engine.scenario(results, filters) -> dict`

Exportado em `engine/__init__.py`. Entrada: o dict do `results.json` e um `ScenarioFilters` (pydantic, `extra=forbid`, todos opcionais e mensais):

| Filtro | Mantém o ponto se |
|---|---|
| `min_budget`, `max_budget` | `min_budget ≤ investimento ≤ max_budget` |
| `target_cpa` | `cpa ≤ target_cpa` |
| `target_icpa` | `icpa ≤ target_icpa` (icpa nulo sai) |
| `min_roas` | `roas ≥ min_roas` |
| `min_iroas` | `iroas ≥ min_iroas` |
| `min_kpi` | `kpi ≥ min_kpi` |
| `min_incrementality_pct` | `incremental_kpi / kpi × 100 ≥ min_incrementality_pct` |

Cálculo, em Python:

1. Fator mensal `f = 30 / results["validation"]["period_days"]`. Sem `elasticity`, sem `response_curve` ou sem `period_days` → `EngineError` (a API traduz em 409).
2. Linhas mensais da curva: `investment`, `kpi`, `kpi_lo`, `kpi_hi`, `incremental_investment`, `incremental_kpi`, `revenue` × f; `cpa = investment / kpi`; `roas = revenue / investment` (modo receita); `icpa` e `iroas` como no `results.json` (razões não mudam com f); `pct_incrementality`; `extrapolated`; `in_filter`.
3. `recommended` = linha `in_filter` de maior investimento, ou `None`.
4. `saturation` = regra do `find_saturation_point` com `min_investment` = investimento do `current`.
5. `current`, `recommended` e `saturation` saem como linhas de tabela: investimento, KPI, banda, `cpa`/`roas`, incrementais contra o `current` (sem clip, como o Streamlit), `icpa`/`iroas` contra o `current` (nulo se o KPI incremental ≤ 0), `extrapolated`, `ramp` (mensal) e `notes`. No `current`, incrementais e iCPA são 0.

Saída:

```json
{"unit": "month", "revenue_mode": false,
 "current": {…}, "recommended": {…} | null, "saturation": {…},
 "curve": [{"investment": …, "kpi": …, "kpi_lo": …, "kpi_hi": …, "cpa": …, "icpa": …, "roas": …, "iroas": …,
            "pct_incrementality": …, "extrapolated": false, "in_filter": true}, …]}
```

Sem `NaN`/`Infinity`: o que não tem valor sai `null`, como no `results.json`.

### Trilha B: rota

`GET /api/w/{slug}/runs/{run_id}/scenario?min_budget=…&target_cpa=…` em `api/routes/runs.py`; a leitura do `results.json` em `api/runs.py`.

- Viewer+; o viewer só vê run publicado (o `find_run` de `api/routes/runs.py`, que usa `runs.visible`). Run de outro workspace ou invisível → 404.
- Lê `results_uri` pelo `storage`, chama `engine.scenario`. Run sem `results_uri`, ou `EngineError` do `scenario` → 409 com a mensagem pt-BR.
- Query inválida (negativo, `min_budget > max_budget`) → 422 do pydantic.
- Linha nova na tabela do `API-GUIDE.md`.

## Testes e aceite

`tests/engine/test_scenario.py`:

- **Paridade com o Streamlit (aceite da trilha):** o filtro e o `find_saturation_point` do Streamlit copiados no teste como oráculo (pandas, como lá), rodados sobre a `response_curve` do `gol_anonimizada.json` em 6–8 combinações de filtro (nenhum, só orçamento, CPA, iCPA, ROAS/iROAS num fixture em modo receita se houver, KPI mínimo, % incrementalidade, combinação que esvazia). Mesmo investimento recomendado e de saturação.
- Testes do `find_saturation_point` portados de `opportunity-engine/tests/test_dashboard_charts.py`.
- `ramp`: +50% com 20% → 3 degraus, o último no alvo; −50% → 3 degraus para baixo; +15% → `None`; KPI do degrau interpolado.
- Filtro que esvazia → `recommended` nulo, `saturation` com fallback.
- Banda nula no fixture → `kpi_lo`/`kpi_hi` nulos, sem erro.
- `scenario` < 300 ms no `gol_anonimizada.json` (tempo medido no teste, com folga para CI).

`tests/engine/test_guardrails.py` (sintético do `make_identifiable_dataset`, rodando o motor):

- Toda linha da `response_curve`, todo cenário e todo ponto de curva individual com banda, e `kpi_lo ≤ kpi ≤ kpi_hi` (o ponto usa o coeficiente médio, que fica dentro do p5–p95 por construção na prática; o teste confere).
- Linha em 0 de investimento e linhas acima do máximo histórico com `extrapolated=true`; linha no investimento atual com `false`.
- Curva individual não passa de `max histórico × per_channel_investment_limit_factor`.
- Cenário `strategic_limit` com mudança > 20% tem `ramp` e `notes`; `strategic_reallocation` (mesmo investimento) não.

`tests/engine/test_parity.py`: tira `KPI_Lo`, `KPI_Hi` e `Extrapolated` antes de comparar; o resto continua idêntico a 1e-9 (só Linux).

`tests/api/test_scenario.py`: analyst lê o scenario de um run concluído (motor fake gravando o `gol_anonimizada.json`); viewer recebe 404 em run não publicado e 200 em publicado; outro workspace → 404; run sem resultado → 409; `min_budget` negativo → 422.

## Documentação no mesmo commit

- `docs/m2/trilha-a-motor.md` (status da A8), `docs/m2/trilha-b-plataforma.md` (status do B5: fixtures do A1 e `scenario` entregues, B5 desbloqueado), `CLAUDE.md` › Estado atual.
- `docs/decisoes/engine.md`: banda só da Ridge, learning/budget-limited cortado, paridade sem as colunas da A8, base dos incrementais.
- `API-GUIDE.md`: linha da rota.
- `docs/m2/README.md` §3/§4: `notes` no cenário e a forma da saída do `scenario`.

## Em aberto

- A banda ignora a incerteza de K, n e α. Se a A10 achar a cobertura baixa, propagar exige re-ajustar o Hill por reamostragem (custo alto); decidir lá.
- O `incremental_investment` dos eventos (pendência do A1) não é tocado aqui.
