# A7 · Experiment designer — design

Data: 08/nov/2026. Item: `docs/m2/trilha-a-motor.md` › A7. Depende do A6 (feito). Branch: `feat/a7-b11`.

## Objetivo

Quando o run termina `inconclusive`, o `results.json` diz ao analista como tirar a dúvida com um experimento: quanto tempo rodar, qual o menor efeito detectável e quanto orçamento fica em risco, por canal.

## Decisões (aprovadas em 08/nov/2026)

1. **Um desenho por canal com spend**, cada um com dois tipos de teste: `on_off` e `step_up` (de `max_budget_step`). O analista escolhe. A lista vem ordenada pelo `budget_at_risk` do `on_off`, do menor para o maior.
2. **σ do baseline calendário + trend**: OLS do KPI em tendência linear mais dummies de dia da semana (estas só com cadência diária). Existe sempre, mesmo sem MMM e sem evento. É conservador, porque o ruído da mídia fica no σ.
3. **Fora do escopo:** o upload do resultado do experimento para calibração. É o item 3 da ordem de corte do `docs/m2/README.md` e fica para a Trilha B guardar depois. Também fica fora o geo split, porque não há dimensão geográfica.

## Matemática

Entrada: `prepared.kpi_df` (`Date`, `kpi`), `prepared.spend_df` (spend real, antes do adstock) e `prepared.period_days`.

- **Janela:** os últimos `max(90 dias, 30 períodos)` do KPI. Com menos de 30 períodos no histórico, sai `status: "insufficient_history"` e os números ficam `null`.
- **Baseline:** `kpi ~ 1 + t (+ dia da semana)` por mínimos quadrados (`numpy.linalg.lstsq`). Resíduos `e`.
- `σ = std(e, ddof=k)`, com `k` igual ao número de coeficientes. `ρ = corr(e[1:], e[:-1])`, cortado em `[0, 0,95]`, porque um ρ negativo encolheria o MDE e não é conservador. `f = (1+ρ)/(1−ρ)`.
- `ȳ` é a média do KPI na janela, por período.
- **MDE do efeito somado em T períodos**, a 95% de confiança e 80% de poder: `MDE_abs(T) = (1,96 + 0,84) · σ · √(f·T)`.
- **Duração:** é o menor T com `MDE_abs(T) ≤ alvo · ȳ · T`, onde `alvo = experiment_target_lift`. Em forma fechada: `T = ⌈(2,8 · σ · √f / (alvo · ȳ))²⌉`, com no mínimo 1.
- **Teto:** `T_max = ⌊experiment_max_days / period_days⌋`. Com `T > T_max`, sai `feasible: false` e `T = T_max`.
- `mde_abs = MDE_abs(T)` e `mde_rel = mde_abs / (ȳ · T)`. Com `feasible: true`, `mde_rel ≤ alvo`.
- `duration_days = T · period_days`.
- **Por canal:** `spend_per_period` é a média do spend do canal na janela. O `budget_at_risk` vale `spend_per_period · T` no `on_off` e `max_budget_step · spend_per_period · T` no `step_up`. Canal com spend zero na janela fica fora da lista.
- Com `ȳ ≤ 0` ou `σ = 0`, sai `status: "insufficient_history"` com o motivo `degenerate_kpi`, sem divisão por zero.

**Limitação, que vai em `assumptions`:** o T é o mesmo para todos os canais, porque o alvo é relativo ao KPI total. Desligar um canal pequeno dificilmente move `alvo` do KPI. A fórmula é provisória até a validação da Data Science (o "Em aberto" do item).

## Config

São dois campos novos no `EngineConfig` (`engine/config.py`). Não entram no `ANALYST_FIELDS` por ora:

- `experiment_target_lift: float = Field(default=0.05, gt=0, lt=1)`
- `experiment_max_days: int = Field(default=90, ge=7)`

## Schema (`engine/results_schema.py`)

O `ExperimentDesign` deixa de ser `dict[str, Any]` e vira modelo `extra=forbid`:

```python
class ExperimentCell(_Model):
    channel: str
    test_type: Literal["on_off", "step_up"]
    step: float | None          # max_budget_step no step_up; None no on_off
    spend_per_period: float
    budget_at_risk: float

class ExperimentDesign(_Model):
    status: Literal["ok", "insufficient_history"]
    reasons: list[str] = []
    period_days: int
    target_lift: float
    sigma: float | None = None
    rho: float | None = None
    kpi_per_period: float | None = None
    duration_periods: int | None = None
    duration_days: int | None = None
    feasible: bool | None = None
    mde_abs: float | None = None
    mde_rel: float | None = None
    designs: list[ExperimentCell] = []
    assumptions: list[str] = []   # pt-BR, prontas para a tela
```

## Fluxo

- `engine/experiment.py`: `design(prepared: PreparedData, cfg: dict) -> ExperimentDesign`. É uma função pura, sem I/O, e não loga número.
- `engine/results.py` › `build_results`: depois de decidir o `status` do run, se ele for `"inconclusive"`, preenche `experiment_design = experiment.design(computed.prepared, computed.effective_config)`. Nos outros status fica `None`. O pipeline do A9 (narrativas sobre o documento) não muda.
- `api/engine_run.py`: o fake continua devolvendo `experiment_design: None`. O E2E usa os fixtures.
- Os fixtures do A1 (`tests/fixtures/results/`) são regenerados, e os `inconclusive` ganham `experiment_design`. Na regeneração os números do MMM mudam com a CPU, mas os do A7 não dependem do MMM.

## Testes (`tests/engine/test_experiment.py`)

- **Conta manual:** com uma série sintética de σ e ρ conhecidos (ruído branco, ρ≈0), o `T` e o `mde_abs` conferem com a fórmula calculada no teste.
- **Monte Carlo:** 2.000 réplicas com ruído AR(1) (σ e ρ fixos) e o efeito somado igual ao `mde_abs` no T devolvido. O z-teste da soma, com variância `σ²·f·T`, rejeita H0 em 80% ± 5 p.p. A semente é fixa.
- **Semanal:** com `period_days = 7`, o dia da semana fica fora e a janela é de 30 períodos.
- Histórico curto (< 30 períodos) → `insufficient_history`. KPI constante → `degenerate_kpi`.
- `T` acima do teto → `feasible: false`, `duration_days ≤ experiment_max_days` e `mde_rel > alvo`.
- Ordenação, `step_up = max_budget_step × on_off`, canal sem spend fora.
- `build_results`: `succeeded`/`failed` → `None`; `inconclusive` → preenchido.

## Front (depois do merge do A9 e do rebase)

- `web/src/lib/results.ts`: tipos `ExperimentDesign`/`ExperimentCell` ao lado dos `Reports` do A9.
- Card "Desenho de experimento" no topo da aba Causal, só quando `experiment_design` não é `null`. Mostra duração, MDE relativo, `feasible` (alerta quando falso), a tabela por canal (tipo, spend/período, orçamento em risco) e as `assumptions`. Os números já vêm do Python, então o front só formata. Com `insufficient_history`, mostra só o motivo.
- E2E: o fixture da Gol (inconclusiva) mostra o card. A impressão do B7 sai sem ajuste.

## Docs no mesmo commit

`docs/decisoes/engine.md` (seção A7), a linha `Status` do A7 em `trilha-a-motor.md`, o parágrafo "Estado atual" do `CLAUDE.md` (só a frase do A7) e o mapa do `engine/` no `CLAUDE.md`.
