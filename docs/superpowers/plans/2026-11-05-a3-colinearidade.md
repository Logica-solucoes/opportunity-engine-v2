# A3 · Gate de colinearidade — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `engine.validate` mede a colinearidade do spend por canal e bloqueia o run até o analista agrupar os canais (`channel_groups`) ou aceitar `block_per_channel`; o agrupamento funciona de ponta a ponta no `run`.

**Architecture:** `engine/config.py` ganha `block_per_channel`, os limites dos gates (`GATE_DEFAULTS` + `gate_threshold()`) e a validação de `channel_groups`. `engine/inputs.py` ganha `apply_channel_groups`, chamada por `load_and_prepare_data` logo depois de `read_inputs`. `engine/validation.py` calcula pares (|r|), VIF e grupos sugeridos sobre o spend cru e emite os checks `collinearity_unresolved`, `channel_group_unknown` e `collinearity_not_assessed`.

**Tech Stack:** Python 3.13, pandas, numpy, statsmodels (`variance_inflation_factor`, já dependência), pydantic 2, pytest. O E2E é Playwright (bun).

**Spec:** `docs/superpowers/specs/2026-11-05-a3-colinearidade-design.md`.

**Antes de começar:** `docker compose up -d` (Postgres em `:5432`, só para a suíte da API), `uv sync`. Rode tudo da raiz do repo e os testes com `-p no:warnings`. A suíte do motor não usa banco. Os testes de paridade pulam fora do Linux.

## Mapa de arquivos

| Arquivo | Responsabilidade | Tasks |
|---|---|---|
| `engine/config.py` | `block_per_channel`, `GATE_DEFAULTS`, `gate_threshold()`, validação de `channel_groups` e `gate_thresholds` | 1 |
| `engine/inputs.py` | `apply_channel_groups` | 2 |
| `engine/data_preprocessor.py` | `load_and_prepare_data` soma os grupos depois de `read_inputs` | 2 |
| `engine/validation.py` | `spend_matrix`, `channel_vif`, `collinearity`, checks novos | 3, 4 |
| `tests/engine/test_config.py` | config | 1 |
| `tests/engine/test_inputs.py` | agrupamento | 2 |
| `tests/engine/test_collinearity.py` (novo) | cálculo, gate e run | 3, 4, 5 |
| `tests/api/test_simulations.py`, `web/e2e/simulations.spec.ts` | o check `info` novo no exemplo de 2 datas | 3 |
| docs | ver Task 6 | 6 |

**Ordem e paralelismo:**
- **Lote A:** 1 e 2 são independentes (arquivos diferentes).
- **Lote B:** 3 depois da 1 (usa `gate_threshold`).
- **Lote C:** 4 depois da 3 (mesmo arquivo de teste e de código).
- **Lote D:** 5 depois de 2 e 4.
- **Fim:** 6 e 7.

---

### Task 1: Config do gate

**Files:**
- Modify: `engine/config.py`
- Test: `tests/engine/test_config.py`

- [ ] **Step 1: Testes (falham hoje)**

Em `tests/engine/test_config.py`, no fim de `test_defaults_match_the_spec`, acrescente:

```python
    assert c.block_per_channel is False and c.gate_thresholds == {}
```

E acrescente ao fim do arquivo:

```python
def test_channel_groups_are_normalized_like_the_channels():
    assert EngineConfig(channel_groups=[[" pmax", "Search "]]).channel_groups == [["PMAX", "SEARCH"]]


@pytest.mark.parametrize(
    ("groups", "message"),
    [
        ([["PMAX"]], "cada grupo precisa de pelo menos dois canais diferentes"),
        ([["PMAX", "pmax"]], "cada grupo precisa de pelo menos dois canais diferentes"),
        ([["PMAX", "SEARCH"], ["SEARCH", "YOUTUBE"]], "o canal SEARCH está em mais de um grupo"),
    ],
)
def test_bad_channel_groups_are_an_invalid_config(groups, message):
    with pytest.raises(EngineError) as raised:
        EngineConfig.from_input({"channel_groups": groups})
    assert str(raised.value) == f"Configuração inválida: campo 'channel_groups': {message}"


def test_gate_threshold_falls_back_to_the_default():
    assert EngineConfig().gate_threshold("collinearity_r") == 0.85
    assert EngineConfig(gate_thresholds={"collinearity_r": 0.9}).gate_threshold("collinearity_r") == 0.9


def test_unknown_gate_is_an_invalid_config():
    with pytest.raises(EngineError) as raised:
        EngineConfig.from_input({"gate_thresholds": {"colinearity_r": 0.9}})
    assert str(raised.value) == "Configuração inválida: campo 'gate_thresholds': limite desconhecido: colinearity_r"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q -p no:warnings tests/engine/test_config.py`

Expected: FAIL nos testes novos (`block_per_channel` e `gate_threshold` não existem; grupos inválidos passam).

- [ ] **Step 3: Implementar em `engine/config.py`**

Troque o import do pydantic por:

```python
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
```

Logo depois de `from engine.errors import EngineError`, acrescente:

```python
# gate thresholds (A3); A4 adds control_spend_corr and A5 collinearity_vif when they use them
GATE_DEFAULTS = {"collinearity_r": 0.85}
```

Na seção `# --- filled by the system ---`, troque a linha `gate_thresholds: dict = Field(default_factory=dict)` por:

```python
    gate_thresholds: dict[str, float] = Field(default_factory=dict)
    block_per_channel: bool = False  # the analyst accepts results only at the aggregate level (A3 gate; effect in A5)
```

Antes de `_revenue_needs_a_ticket`, acrescente:

```python
    @field_validator("channel_groups")
    @classmethod
    def _groups_are_disjoint(cls, groups: list[list[str]]) -> list[list[str]]:
        groups = [[name.strip().upper() for name in group] for group in groups]  # as the reader normalizes channels
        seen: set[str] = set()
        for group in groups:
            if len(set(group)) < 2:
                raise ValueError("cada grupo precisa de pelo menos dois canais diferentes")
            repeated = seen & set(group)
            if repeated:
                raise ValueError(f"o canal {sorted(repeated)[0]} está em mais de um grupo")
            seen |= set(group)
        return groups

    @field_validator("gate_thresholds")
    @classmethod
    def _known_gates(cls, thresholds: dict[str, float]) -> dict[str, float]:
        unknown = sorted(set(thresholds) - set(GATE_DEFAULTS))
        if unknown:
            raise ValueError(f"limite desconhecido: {', '.join(unknown)}")
        return thresholds
```

Depois de `to_legacy_dict`, acrescente o método:

```python
    def gate_threshold(self, name: str) -> float:
        return {**GATE_DEFAULTS, **self.gate_thresholds}[name]
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest -q -p no:warnings tests/engine/test_config.py tests/engine/test_defaults.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check engine tests && uv run ruff format engine tests
git add engine/config.py tests/engine/test_config.py
git commit -m "feat(engine): collinearity gate config: block_per_channel, gate thresholds and channel group checks"
```

---

### Task 2: `channel_groups` soma o spend na leitura

**Files:**
- Modify: `engine/inputs.py`
- Modify: `engine/data_preprocessor.py` (`load_and_prepare_data`, ~linhas 769–778)
- Test: `tests/engine/test_inputs.py`

- [ ] **Step 1: Testes (falham hoje)**

Acrescente ao fim de `tests/engine/test_inputs.py` (junte os imports aos do topo do arquivo, sem duplicar):

```python
import pandas as pd

from engine.config import EngineConfig
from engine.inputs import apply_channel_groups
from engine.pipeline import load_inputs
from tests.engine.synthetic_data import dataset_config, make_dataset


def test_apply_channel_groups_sums_the_members_per_date():
    df = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2024-01-01"] * 3 + ["2024-01-02"] * 3),
            "Product Group": ["PMAX", "SEARCH", "YOUTUBE"] * 2,
            "investment": [1.0, 2.0, 4.0, 10.0, 20.0, 40.0],
        }
    )

    out = apply_channel_groups(df, [["SEARCH", "PMAX"]])

    assert sorted(out["Product Group"].unique()) == ["SEARCH + PMAX", "YOUTUBE"]
    assert out.loc[out["Product Group"] == "SEARCH + PMAX", "investment"].tolist() == [3.0, 30.0]
    assert apply_channel_groups(df, []) is df


def test_load_turns_a_group_into_one_channel_before_any_analysis(tmp_path):
    config = EngineConfig.from_input({**dataset_config(), "channel_groups": [["SEARCH", "PMAX"]]})

    prepared = load_inputs(make_dataset(tmp_path, n_days=364), config)

    channels = set(prepared.investment_df["Product Group"])
    assert "SEARCH + PMAX" in channels and not {"SEARCH", "PMAX"} & channels
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q -p no:warnings tests/engine/test_inputs.py`

Expected: FAIL com `ImportError` (`apply_channel_groups` não existe).

- [ ] **Step 3: `apply_channel_groups` em `engine/inputs.py`**

Acrescente depois de `sufficiency_check`:

```python
def apply_channel_groups(investment_df: pd.DataFrame, groups: list[list[str]]) -> pd.DataFrame:
    """Each group becomes one channel named 'A + B', its members' spend summed per date (A3)."""
    if not groups:
        return investment_df
    names = {member: " + ".join(group) for group in groups for member in group}
    renamed = investment_df.assign(**{"Product Group": investment_df["Product Group"].replace(names)})
    return renamed.groupby(["Date", "Product Group"], as_index=False)["investment"].sum()
```

O nome `" + ".join(group)` é o mesmo que `engine/results.py` usa em `elasticity.groups`; não mude um sem o outro.

- [ ] **Step 4: Chamar em `load_and_prepare_data`**

Em `engine/data_preprocessor.py`, troque o import local:

```python
    from engine.inputs import cadence_check, read_inputs, sufficiency_check  # inputs imports this module's helpers
```

por:

```python
    from engine.inputs import (  # inputs imports this module's helpers
        apply_channel_groups,
        cadence_check,
        read_inputs,
        sufficiency_check,
    )
```

E troque:

```python
        kpi_df, daily_investment_df, trends_df = raw.kpi_df, raw.investment_df, raw.trends_df
```

por:

```python
        kpi_df, trends_df = raw.kpi_df, raw.trends_df
        # before partial periods and the negative-correlation adstock: from here on a group is a plain channel
        daily_investment_df = apply_channel_groups(raw.investment_df, config["channel_groups"])
```

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest -q -p no:warnings tests/engine/test_inputs.py tests/engine/test_config.py tests/engine/test_defaults.py tests/engine/test_pipeline_stages.py`

Expected: PASS. O `test_legacy_dict_covers_every_key_the_modules_read` continua passando porque `channel_groups` já está no `to_legacy_dict()`.

- [ ] **Step 6: Commit**

```bash
uv run ruff check engine tests && uv run ruff format engine tests
git add engine/inputs.py engine/data_preprocessor.py tests/engine/test_inputs.py
git commit -m "feat(engine): sum the spend of grouped channels before any analysis"
```

---

### Task 3: Colinearidade no relatório

**Depends on:** Task 1.

**Files:**
- Modify: `engine/validation.py`
- Create: `tests/engine/test_collinearity.py`
- Modify: `tests/api/test_simulations.py` (`test_mapping_runs_the_validation`, ~linha 205)
- Modify: `web/e2e/simulations.spec.ts` (~linha 34)

- [ ] **Step 1: Testes (falham hoje)**

Crie `tests/engine/test_collinearity.py`:

```python
import numpy as np
import pandas as pd
import pytest

from engine.config import EngineConfig
from engine.validation import MIN_COLLINEARITY_PERIODS, channel_vif, collinearity, validate
from tests.engine.csv_factory import days, write_inputs
from tests.engine.synthetic_data import dataset_config, make_dataset


def collinear_inputs(tmp_path, n_days=364):
    """The synthetic dataset with PMAX spend = 0.8 × SEARCH (r ≈ 0.99): one pair over the 0.85 gate.

    0.8 keeps the totals apart, so dv360_cm360_overlap (same total) does not fire.
    """
    paths = make_dataset(tmp_path, n_days=n_days)
    inv = pd.read_csv(paths["investment_file"])
    search = inv.loc[inv["product_group"] == "SEARCH", "total_revenue"].to_numpy()
    noise = np.random.default_rng(3).lognormal(0.0, 0.005, len(search))
    inv.loc[inv["product_group"] == "PMAX", "total_revenue"] = 0.8 * search * noise
    inv.to_csv(paths["investment_file"], index=False)
    return paths


def _frame(columns: dict[str, np.ndarray]) -> pd.DataFrame:
    """Long investment frame (Date, Product Group, investment), one spend array per channel."""
    n = len(next(iter(columns.values())))
    dates = pd.date_range("2024-01-02", periods=n, freq="D")
    return pd.concat(
        [pd.DataFrame({"Date": dates, "Product Group": name, "investment": values}) for name, values in columns.items()]
    )


def test_vif_matches_the_manual_regression():
    rng = np.random.default_rng(0)
    a, b = rng.normal(100, 10, 50), rng.normal(50, 5, 50)
    c = 0.5 * a + 0.5 * b + rng.normal(0, 3, 50)
    others = np.column_stack([np.ones(50), a, b])
    fitted = others @ np.linalg.lstsq(others, c, rcond=None)[0]
    r2 = 1 - ((c - fitted) ** 2).sum() / ((c - c.mean()) ** 2).sum()

    vif = channel_vif(pd.DataFrame({"A": a, "B": b, "C": c}))

    assert vif["C"] == pytest.approx(1 / (1 - r2), abs=1e-4)


def test_perfect_collinearity_is_a_none_vif_not_an_error():
    a = np.arange(40, dtype=float) % 7 + 1

    vif = channel_vif(pd.DataFrame({"A": a, "B": 2 * a, "C": np.random.default_rng(1).normal(10, 1, 40)}))

    assert vif["A"] is None and vif["B"] is None and vif["C"] is not None


def test_pairs_and_suggested_groups_come_from_the_spend_correlation(tmp_path):
    found = validate(collinear_inputs(tmp_path), dataset_config()).collinearity

    assert [(p["a"], p["b"]) for p in found.pairs] == [("PMAX", "SEARCH")]
    assert found.pairs[0]["r"] > 0.95
    assert found.suggested_groups == [["PMAX", "SEARCH"]]
    assert set(found.vif) == {"DISPLAY", "PMAX", "SEARCH", "SOCIAL", "YOUTUBE"}


def test_suggested_groups_are_the_connected_components():
    rng = np.random.default_rng(2)
    base, other = rng.normal(100, 10, 60), rng.normal(100, 10, 60)
    frame = _frame(
        {
            "A": base,
            "B": base * 1.1 + rng.normal(0, 1, 60),
            "C": base * 0.9 + rng.normal(0, 1, 60),
            "D": other,
        }
    )

    assert collinearity(frame, EngineConfig()).suggested_groups == [["A", "B", "C"]]


def test_a_short_series_is_not_assessed(tmp_path):
    n = MIN_COLLINEARITY_PERIODS - 1
    channels = ("SEARCH", "SOCIAL")
    investment = [(d, c, 100 + i * 3 + j * 50) for j, c in enumerate(channels) for i, d in enumerate(days(n))]
    kpi = [(d, 1000 + i) for i, d in enumerate(days(n))]

    report = validate(write_inputs(tmp_path, investment, kpi), dataset_config())

    assert report.ok and report.collinearity.pairs == [] and report.collinearity.vif == {}
    check = next(c for c in report.checks if c.id == "collinearity_not_assessed")
    assert check.level == "info" and check.details == {"periods": n}
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q -p no:warnings tests/engine/test_collinearity.py`

Expected: FAIL com `ImportError` (`MIN_COLLINEARITY_PERIODS` não existe).

- [ ] **Step 3: Implementar em `engine/validation.py`**

Acrescente o import, junto aos de terceiros:

```python
from statsmodels.stats.outliers_influence import variance_inflation_factor
```

Junto às constantes do topo:

```python
MIN_COLLINEARITY_PERIODS = 30  # with fewer dates two channels correlate near ±1 by chance; A6/A10 calibrate
MAX_FINITE_VIF = 1e6  # above this R² rounded to 1: perfect collinearity, reported as None
```

Acrescente antes de `check_channel_overlap`:

```python
def spend_matrix(investment_df: pd.DataFrame) -> pd.DataFrame:
    """Date × channel spend, without constant channels (no correlation or VIF for them)."""
    wide = investment_df.pivot_table(index="Date", columns="Product Group", values="investment").fillna(0)
    return wide.loc[:, wide.std() > 0]


def channel_vif(wide: pd.DataFrame) -> dict[str, float | None]:
    """VIF of each channel's spend on the others; None when one channel is an exact mix of the others."""
    x = np.column_stack([np.ones(len(wide)), wide.to_numpy(dtype=float)])
    out = {}
    with np.errstate(divide="ignore", invalid="ignore"):
        for i, name in enumerate(wide.columns, start=1):
            value = float(variance_inflation_factor(x, i))
            out[name] = round(value, 4) if np.isfinite(value) and value <= MAX_FINITE_VIF else None
    return out


def _connected(pairs: list[dict]) -> list[list[str]]:
    groups: list[set[str]] = []
    for pair in pairs:
        linked = [g for g in groups if pair["a"] in g or pair["b"] in g]
        groups = [g for g in groups if g not in linked] + [{pair["a"], pair["b"]}.union(*linked)]
    return sorted(sorted(g) for g in groups)


def collinearity(investment_df: pd.DataFrame, config: EngineConfig) -> Collinearity:
    """Pairs over the |r| gate, every channel's VIF and the groups the pairs suggest; empty on a short series."""
    wide = spend_matrix(investment_df)
    if wide.shape[1] < 2 or len(wide) < MIN_COLLINEARITY_PERIODS:
        return Collinearity()
    limit = config.gate_threshold("collinearity_r")
    corr = wide.corr()
    pairs = [
        {"a": a, "b": b, "r": round(float(corr.loc[a, b]), 4)}
        for a, b in itertools.combinations(wide.columns, 2)
        if abs(corr.loc[a, b]) > limit
    ]
    return Collinearity(pairs=pairs, vif=channel_vif(wide), suggested_groups=_connected(pairs))


def check_short_series(investment_df: pd.DataFrame) -> list[Check]:
    periods = int(investment_df["Date"].nunique())
    if periods >= MIN_COLLINEARITY_PERIODS:
        return []
    return [
        Check(
            id="collinearity_not_assessed",
            level="info",
            message=(
                f"A colinearidade entre canais não foi avaliada: o histórico tem {periods} período(s), "
                f"e o mínimo é {MIN_COLLINEARITY_PERIODS}."
            ),
            details={"periods": periods},
        )
    ]
```

Em `check_channel_overlap`, troque as duas linhas que montam `wide`:

```python
    wide = investment_df.pivot_table(index="Date", columns="Product Group", values="investment").fillna(0)
    wide = wide.loc[:, wide.std() > 0]
```

por:

```python
    wide = spend_matrix(investment_df)
```

Em `validate`, troque:

```python
    legacy = EngineConfig.from_input(config).to_legacy_dict()
```

por:

```python
    engine_config = EngineConfig.from_input(config)
    legacy = engine_config.to_legacy_dict()
```

e troque o trecho final (de `series, period_days = _series_checks(raw)` até o `return`) por:

```python
    series, period_days = _series_checks(raw)
    investment = raw.investment_df
    checks = [*raw.checks, *series]
    if not investment.empty:
        checks += check_short_series(investment)
    return ValidationReport(
        ok=not any(c.level == "error" for c in checks),
        cadence=None if period_days is None else CADENCE_LABEL.get(period_days, f"{period_days} dias"),
        period_days=period_days,
        date_range=None if investment.empty else _iso([investment["Date"].min(), investment["Date"].max()]),
        channels=sorted(investment["Product Group"].unique()),
        checks=checks,
        collinearity=Collinearity() if investment.empty else collinearity(investment, engine_config),
    )
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest -q -p no:warnings tests/engine/test_collinearity.py tests/engine/test_validate_checks.py tests/engine/test_inputs.py`

Expected: PASS. Se um teste de `test_validate_checks.py` falhar porque passou a ver `collinearity_not_assessed` numa lista exata de checks, troque a asserção para ignorar ids `info` daquele teste. Não mude o motor por causa disso.

- [ ] **Step 5: O exemplo de 2 datas da API e do E2E**

Em `tests/api/test_simulations.py`, em `test_mapping_runs_the_validation`, troque `"checks": [],` por:

```python
        "checks": [
            {
                "id": "collinearity_not_assessed",
                "level": "info",
                "message": "A colinearidade entre canais não foi avaliada: o histórico tem 2 período(s), e o mínimo é 30.",
                "details": {"periods": 2},
            }
        ],
```

Em `web/e2e/simulations.spec.ts`, no teste `analyst uploads the templates, accepts the suggested mapping and validates`, troque:

```ts
  await expect(analystPage.getByText('Nenhum problema encontrado.')).toBeVisible()
```

por:

```ts
  await expect(analystPage.getByText('A colinearidade entre canais não foi avaliada', { exact: false })).toBeVisible()
```

Run: `uv run pytest -q -p no:warnings tests/api/test_simulations.py tests/api/test_google_import.py tests/api/test_engine_swap.py`

Expected: PASS. Se um teste de `test_google_import.py` comparar a lista exata de checks do relatório, acrescente o mesmo `collinearity_not_assessed` com o número de períodos real (está em `details.periods` da saída). Não mude `api/`.

- [ ] **Step 6: Commit**

```bash
uv run ruff check engine tests && uv run ruff format engine tests
git add engine/validation.py tests/engine/test_collinearity.py tests/api/test_simulations.py tests/api/test_google_import.py web/e2e/simulations.spec.ts
git commit -m "feat(engine): report spend correlation pairs, vif and suggested channel groups in validate"
```

---

### Task 4: O gate

**Depends on:** Task 3.

**Files:**
- Modify: `engine/validation.py`
- Test: `tests/engine/test_collinearity.py`

- [ ] **Step 1: Testes (falham hoje)**

Acrescente ao fim de `tests/engine/test_collinearity.py`:

```python
def test_a_collinear_pair_blocks_until_resolved(tmp_path):
    report = validate(collinear_inputs(tmp_path), dataset_config())

    check = next(c for c in report.checks if c.id == "collinearity_unresolved")
    assert not report.ok and check.level == "error"
    assert [(p["a"], p["b"]) for p in check.details["pairs"]] == [("PMAX", "SEARCH")]
    assert check.details["suggested_groups"] == [["PMAX", "SEARCH"]]
    assert "PMAX + SEARCH" in check.message


@pytest.mark.parametrize("resolution", [{"channel_groups": [["SEARCH", "PMAX"]]}, {"block_per_channel": True}])
def test_a_group_or_the_block_flag_resolves_the_gate(tmp_path, resolution):
    report = validate(collinear_inputs(tmp_path), {**dataset_config(), **resolution})

    assert report.ok, [c.id for c in report.checks if c.level == "error"]
    assert report.collinearity.pairs  # the report still shows the real collinearity


def test_a_group_that_misses_one_side_of_the_pair_does_not_resolve_it(tmp_path):
    config = {**dataset_config(), "channel_groups": [["SEARCH", "YOUTUBE"]]}

    assert "collinearity_unresolved" in {c.id for c in validate(collinear_inputs(tmp_path), config).checks}


def test_a_group_naming_a_channel_not_in_the_file_is_an_error(tmp_path):
    config = {**dataset_config(), "channel_groups": [["SEARCH", "TIKTOK"]]}

    report = validate(make_dataset(tmp_path, n_days=364), config)

    check = next(c for c in report.checks if c.id == "channel_group_unknown")
    assert not report.ok and check.level == "error" and check.details == {"channels": ["TIKTOK"]}
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q -p no:warnings tests/engine/test_collinearity.py`

Expected: FAIL nos quatro testes novos (`StopIteration`: o check não existe; o caso resolvido já passa).

- [ ] **Step 3: Implementar em `engine/validation.py`**

Acrescente depois de `check_short_series`:

```python
def check_groups(found: Collinearity, channels: set[str], config: EngineConfig) -> list[Check]:
    """The analyst's answer to the gate: every flagged pair inside one group, or block_per_channel."""
    checks = []
    unknown = sorted({member for group in config.channel_groups for member in group} - channels)
    if unknown:
        checks.append(
            Check(
                id="channel_group_unknown",
                level="error",
                message=f"O agrupamento cita canais que não estão no arquivo de investimento: {', '.join(unknown)}.",
                details={"channels": unknown},
            )
        )
    if config.block_per_channel:
        return checks
    open_pairs = [
        p for p in found.pairs if not any(p["a"] in group and p["b"] in group for group in config.channel_groups)
    ]
    if open_pairs:
        suggested = "; ".join(" + ".join(group) for group in found.suggested_groups)
        checks.append(
            Check(
                id="collinearity_unresolved",
                level="error",
                message=(
                    "Há canais que gastam juntos, e o modelo não consegue separar o efeito de cada um "
                    f"(sugestão: {suggested}). Agrupe-os ou aceite resultados só no nível agregado."
                ),
                details={"pairs": open_pairs, "suggested_groups": found.suggested_groups},
            )
        )
    return checks
```

Em `validate`, troque o trecho escrito na Task 3:

```python
    checks = [*raw.checks, *series]
    if not investment.empty:
        checks += check_short_series(investment)
    return ValidationReport(
```

por:

```python
    checks = [*raw.checks, *series]
    found = Collinearity()
    if not investment.empty:
        found = collinearity(investment, engine_config)
        checks += check_short_series(investment)
        checks += check_groups(found, set(investment["Product Group"]), engine_config)
    return ValidationReport(
```

e, no `ValidationReport(...)`, troque `collinearity=Collinearity() if investment.empty else collinearity(investment, engine_config),` por `collinearity=found,`.

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest -q -p no:warnings tests/engine/test_collinearity.py tests/engine/test_validate_checks.py`

Expected: PASS. Os testes de overlap (`_two_channels`, 60 datas quase idênticas) passam a ter também `collinearity_unresolved`; eles só conferem o check de overlap e continuam passando. O `test_validate_agrees_with_load_and_prepare_data` compara o **primeiro** erro: os checks novos entram por último, então o primeiro não muda.

- [ ] **Step 5: Commit**

```bash
uv run ruff check engine tests && uv run ruff format engine tests
git add engine/validation.py tests/engine/test_collinearity.py
git commit -m "feat(engine): block the run on unresolved collinearity until channels are grouped or blocked"
```

---

### Task 5: O run com e sem resolução

**Depends on:** Tasks 2 e 4.

**Files:**
- Test: `tests/engine/test_collinearity.py`

- [ ] **Step 1: Testes**

Acrescente aos imports do topo de `tests/engine/test_collinearity.py`:

```python
from threadpoolctl import threadpool_limits

import engine
from engine.errors import EngineError
```

E ao fim do arquivo:

```python
@pytest.fixture
def no_llm(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "none")


def test_run_refuses_unresolved_collinearity_before_computing(tmp_path, no_llm):
    with pytest.raises(EngineError) as raised:
        engine.run(collinear_inputs(tmp_path / "data"), dataset_config(), tmp_path / "out", lambda level, msg: None)

    assert raised.value.check_id == "collinearity_unresolved"


def test_run_with_a_group_reports_only_the_group(tmp_path, no_llm):
    config = {**dataset_config(), "channel_groups": [["SEARCH", "PMAX"]]}

    with threadpool_limits(limits=1):
        result = engine.run(collinear_inputs(tmp_path / "data"), config, tmp_path / "out", lambda level, msg: None)

    elasticity = result["elasticity"]
    assert elasticity["status"] == "ok", elasticity["reasons"]
    names = {c["name"] for c in elasticity["channels"]}
    assert "SEARCH + PMAX" in names and not {"SEARCH", "PMAX"} & names
    assert elasticity["groups"] == [{"name": "SEARCH + PMAX", "members": ["SEARCH", "PMAX"]}]
```

- [ ] **Step 2: Rodar**

Run: `uv run pytest -q -p no:warnings tests/engine/test_collinearity.py -k run`

Expected: 2 passed (o segundo leva ~30–60 s). Se o segundo falhar:
- **o nome `"SEARCH + PMAX"` quebrou a escrita de um arquivo** (as saídas legadas usam o nome do canal no caminho): confira o saneamento de nomes em `engine/outputs.py`, que já existe para nomes de canal arbitrários, e corrija lá;
- **`elasticity.status` não é `ok`**: o `reasons` diz por quê. Investigue com `mattpocock-skills:diagnosing-bugs` antes de mexer em teste.

- [ ] **Step 3: Commit**

```bash
uv run ruff check engine tests && uv run ruff format engine tests
git add tests/engine/test_collinearity.py   # mais engine/outputs.py se precisou corrigir
git commit -m "test(engine): a grouped run reports only the group, an unresolved one never computes"
```

---

### Task 6: Documentação

**Files:** os listados abaixo; nada de código.

- [ ] **Step 1: `docs/decisoes/engine.md`.** Na seção `## validate (A2, 04/nov/2026)`:
  - no **Catálogo**, acrescente os erros `collinearity_unresolved` e `channel_group_unknown` e a info `collinearity_not_assessed`;
  - troque a linha "**Fora do A2:** colinearidade (`collinearity` sai vazia, A3)…" para tirar a colinearidade da lista.

  Acrescente depois dessa seção uma seção `## Colinearidade (A3, 05/nov/2026)` com:
  - spend **cru**, Pearson par a par, limite `gate_thresholds.collinearity_r` (default 0.85, `GATE_DEFAULTS` em `engine/config.py`);
  - VIF só reportado (`None` quando infinito ou > 1e6); o limite `collinearity_vif` entra com o A5;
  - `suggested_groups` são os componentes conexos dos pares;
  - o gate passa com todo par dentro de um grupo de `channel_groups`, ou com `block_per_channel=true` (o efeito no resultado é do A5);
  - `channel_groups` soma o spend logo depois de `read_inputs`, antes dos períodos parciais e do adstock por correlação negativa; o nome do grupo é `"A + B"` na ordem do config;
  - abaixo de 30 períodos não avalia (`collinearity_not_assessed`), porque com poucas datas a correlação dá ±1 por construção; o A6 define o histórico mínimo e a A10 calibra;
  - **consequência:** a API não tem como mandar `channel_groups`/`block_per_channel` (não estão no `ParamsIn`), então um dataset colinear com 30+ períodos não roda pela plataforma até a tela do B2.
- [ ] **Step 2: `docs/m2/trilha-a-motor.md`.** No A3, acrescente a linha `- **Status:** ✅ feito em 05/nov/2026.`, com o que foi verificado (os testes de `tests/engine/test_collinearity.py`, a paridade sintética intacta, o maior |r| do sintético 0.066) e o que falta (rodar sobre a Gol e as Core; os limites ajustáveis por admin são da Trilha B). Em "Em aberto", registre a decisão: spend cru.
- [ ] **Step 3: `docs/m2/trilha-b-plataforma.md`.** No B2, acrescente que a tela de agrupamento agora é necessária para rodar dataset colinear, que o motor espera `channel_groups` (lista de listas de canal) e `block_per_channel` no config da simulação, e que o relatório traz `collinearity.suggested_groups` para pré-preencher.
- [ ] **Step 4: `docs/m2/README.md`.** No contrato §2, depois de "**Entregue pelo A2 (04/nov/2026)**…", acrescente: "**Entregue pelo A3 (05/nov/2026):** `collinearity` preenchido (`pairs` com `a`, `b`, `r`; `vif` por canal, `None` se infinito; `suggested_groups`), vazio com menos de 30 períodos."
- [ ] **Step 5: `CLAUDE.md`.** No "Estado atual", depois do parágrafo do A2/swap, acrescente: "**A3 (gate de colinearidade) concluído em 05/nov/2026**: `validate` preenche `collinearity` (|r| > 0.85 no spend cru, VIF e grupos sugeridos) e dá `collinearity_unresolved` até o config trazer `channel_groups` (somados na leitura) ou `block_per_channel`; abaixo de 30 períodos não avalia. Pela plataforma, dataset colinear só roda quando a tela do B2 existir." Em "Faltam", troque "A3–A10" por "A4–A10".
- [ ] **Step 6: Commit**

```bash
git add docs CLAUDE.md
git commit -m "docs: record the a3 collinearity gate"
```

---

### Task 7: Verificação final

- [ ] **Step 1:** `uv run ruff check . && uv run ruff format --check .`: sem erro.
- [ ] **Step 2:** `uv run pytest -q -p no:warnings`: tudo passa. A suíte do motor leva ~10 min, e a paridade pula fora do Linux.
- [ ] **Step 3:** `cd web && bun run build && bun run lint`: sem erro.
- [ ] **Step 4:** `mise run e2e`: todos passam.
- [ ] **Step 5:** `superpowers:verification-before-completion` antes de declarar pronto.
