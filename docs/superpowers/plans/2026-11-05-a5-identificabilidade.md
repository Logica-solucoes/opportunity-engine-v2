# A5 · Identificabilidade por canal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expor o IC de contribuição por canal do bootstrap do MMM, marcar `identifiable`, e tirar canal não identificável de curva, mix, cenários e payload do Gemini.

**Architecture:** O bootstrap devolve a matriz (a média continua sendo o coeficiente do modelo, então a paridade não muda). Um módulo puro `engine/identifiability.py` (`assess`, `unidentified`, `fold_mix`) decide por canal; o `pipeline` guarda o veredito no `Computed`; `results.py` (JSON) e `outputs._scenario` (Markdown, HTML global, Gemini) consomem o mesmo `fold_mix`.

**Tech Stack:** Python 3.13, numpy, scikit-learn (Ridge), pydantic, pytest. Rodar tudo com `uv run`.

**Spec:** `docs/superpowers/specs/2026-11-05-a5-identificabilidade-design.md`. Leia antes, junto com `CODE-STYLE.md` (regras do motor).

**Fato medido que guia os testes (05/nov/2026):** no dataset sintético atual (`tests/engine/synthetic_data.py`), em 364 e 728 dias, semanal e colinear agrupado, **todo canal sai não identificável**. Logo, todo run sobre ele passa a ter `elasticity.status == "inconclusive"` com `reasons == ["no_identifiable_channel"]`, e o run `inconclusive`. O caso "canal identificável" usa o dataset novo da Task 3.

**Tempo:** os fixtures `synthetic_computed` e os runs de `test_run.py`/`test_results_run.py` levam minutos. Rode só o arquivo da task; a suíte inteira só na Task 7.

**Dependências entre tasks:** 1 e 2 são independentes (podem rodar em paralelo). 3 depende de 1 e 2. 4 e 5 dependem de 3 e podem rodar em paralelo (arquivos diferentes). 6 depende de 4. 7 é a última.

---

### Task 1: Bootstrap devolve a matriz

**Files:**
- Modify: `engine/elasticity_analysis.py:248-270` (função do bootstrap) e `:417-419`, `:478-490` (`run_mmm_engine`)
- Test: `tests/engine/test_elasticity_analysis.py:8-17` (import) e `:126-153` (classe `TestBootstrapAverageCoefficients`)

- [ ] **Step 1: Atualizar os testes para a nova API**

Em `tests/engine/test_elasticity_analysis.py`, troque o import `bootstrap_average_coefficients,` por `bootstrap_coefficients,` e substitua a classe `TestBootstrapAverageCoefficients` inteira por:

```python
class TestBootstrapCoefficients(unittest.TestCase):
    def test_recovers_a_zeroed_channels_true_contribution(self):
        # Two highly correlated columns (corr ~0.99) that BOTH truly drive y
        # (70/30 split). A single positive-constrained Ridge fit on the full
        # data hands 100% of the credit to column A and zeroes column B -- a
        # stable corner solution caused by the collinearity, not a fluke.
        rng = np.random.default_rng(5)
        n = 60
        a = rng.uniform(1, 10, n)
        b = np.clip(a + rng.normal(0, 0.5, n), 0.1, None)
        X = np.column_stack([a, b])
        y = 0.7 * a + 0.3 * b + rng.normal(0, 2.0, n)

        single_fit = Ridge(alpha=1.0, positive=True, fit_intercept=False).fit(X, y)
        self.assertEqual(single_fit.coef_[1], 0.0)

        boot_coef = bootstrap_coefficients(X, y, n_bootstrap=300, seed=42).mean(axis=0)
        self.assertGreater(boot_coef[1], 0.0)

    def test_reproducible_with_a_fixed_seed(self):
        rng = np.random.default_rng(1)
        X = rng.uniform(1, 10, (40, 2))
        y = X[:, 0] + X[:, 1] + rng.normal(0, 1.0, 40)

        result_a = bootstrap_coefficients(X, y, n_bootstrap=50, seed=7)
        result_b = bootstrap_coefficients(X, y, n_bootstrap=50, seed=7)
        np.testing.assert_array_equal(result_a, result_b)

    def test_returns_one_row_per_resample(self):
        rng = np.random.default_rng(2)
        X = rng.uniform(1, 10, (30, 3))
        y = X.sum(axis=1)

        samples = bootstrap_coefficients(X, y, n_bootstrap=20, seed=1)

        self.assertEqual(samples.shape, (20, 3))
        self.assertTrue((samples >= 0).all())  # positive Ridge
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/engine/test_elasticity_analysis.py -k Bootstrap -q`
Expected: FAIL / ERROR com `ImportError: cannot import name 'bootstrap_coefficients'`.

- [ ] **Step 3: Implementar**

Em `engine/elasticity_analysis.py`, renomeie a função e devolva a matriz (o corpo do loop não muda):

```python
def bootstrap_coefficients(X, y, n_bootstrap=200, seed=42):
    """
    Refits Ridge(alpha=1.0, positive=True, fit_intercept=False) on n_bootstrap
    resamples of the rows (with replacement) and returns the (n_bootstrap, n_columns)
    matrix of coefficients. The model uses its mean; A5 uses its percentiles.

    A single fit of a positive-constrained Ridge on correlated columns tends to
    hand all the credit to one column and zero the other (a stable but fragile
    corner solution -- see docs/superpowers/specs/2026-07-06-dashboard-inconsistencies-fix-design.md
    for the original diagnosis and the 2026-07-08 follow-up confirming it happens
    even when the zeroed channel has real, substantial spend). Averaging over
    resamples smooths this out: a channel that only wins the corner solution by
    chance on the full dataset won't win it in every resample.
    """
    rng = np.random.default_rng(seed)
    n_rows = X.shape[0]
    y_arr = np.asarray(y)
    coefs = np.zeros((n_bootstrap, X.shape[1]))
    for b in range(n_bootstrap):
        idx = rng.integers(0, n_rows, n_rows)
        model = Ridge(alpha=1.0, positive=True, fit_intercept=False).fit(X[idx], y_arr[idx])
        coefs[b] = model.coef_
    return coefs
```

Em `run_mmm_engine`, troque a linha `mkt_model.coef_ = bootstrap_average_coefficients(X_mkt_scaled, y_lift)` por:

```python
    coef_samples = bootstrap_coefficients(X_mkt_scaled, y_lift)
    mkt_model.coef_ = coef_samples.mean(axis=0)
```

E no `return {...}` do fim de `run_mmm_engine`, logo depois de `"model": mkt_model,`, acrescente:

```python
        "coef_samples": coef_samples,  # (n_bootstrap, channels), scaled space: A5 CIs, A8 bands
        "channel_totals": X_mkt_scaled.sum(axis=0),  # coef × total = the channel's contribution over the period
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/engine/test_elasticity_analysis.py -q`
Expected: PASS.

Run: `grep -rn "bootstrap_average_coefficients" engine tests --include=*.py`
Expected: nenhuma linha.

- [ ] **Step 5: Commit**

```bash
uv run ruff format engine tests && uv run ruff check engine tests
git add engine/elasticity_analysis.py tests/engine/test_elasticity_analysis.py
git commit -m "refactor(engine): keep the bootstrap coefficient matrix, the model still uses its mean"
```

---

### Task 2: Módulo `engine/identifiability.py`

**Files:**
- Create: `engine/identifiability.py`
- Test: `tests/engine/test_identifiability.py`

- [ ] **Step 1: Escrever os testes**

Crie `tests/engine/test_identifiability.py`:

```python
from types import SimpleNamespace

import numpy as np
import pytest

from engine import identifiability
from engine.identifiability import UNIDENTIFIED, assess, fold_mix, unidentified


def _mmm(samples: dict[str, list[float]], totals: dict[str, float]) -> dict:
    names = list(samples)
    matrix = np.column_stack([samples[n] for n in names])
    return {
        "spend_cols": names,
        "coef_samples": matrix,
        "channel_totals": np.array([totals[n] for n in names]),
        "model": SimpleNamespace(coef_=matrix.mean(axis=0)),
    }


def test_a_tight_positive_channel_is_identifiable():
    verdict = assess(_mmm({"A": list(np.linspace(0.9, 1.1, 200))}, {"A": 100.0}))["A"]

    assert verdict["identifiable"] is True and verdict["reasons"] == []
    lo, hi = verdict["ci"]
    assert lo == pytest.approx(np.percentile(np.linspace(90, 110, 200), 2.5))
    assert hi == pytest.approx(np.percentile(np.linspace(90, 110, 200), 97.5))


def test_a_channel_zeroed_in_some_resamples_includes_zero():
    samples = [0.0] * 20 + [1.0] * 180  # 10% of resamples zero the channel

    verdict = assess(_mmm({"A": samples}, {"A": 50.0}))["A"]

    assert verdict["identifiable"] is False and "coef_ci_includes_zero" in verdict["reasons"]


def test_a_wide_interval_is_too_wide():
    samples = list(np.linspace(0.2, 3.0, 200))  # all positive, width ≈ 2.7 > mean 1.6

    verdict = assess(_mmm({"A": samples}, {"A": 1.0}))["A"]

    assert verdict["reasons"] == ["coef_ci_too_wide"] and verdict["identifiable"] is False


def test_unidentified_lists_the_failing_channels():
    verdicts = {"A": {"identifiable": True}, "B": {"identifiable": False}}

    assert unidentified(verdicts) == {"B"}
    assert unidentified({}) == set()


def test_fold_mix_sums_the_hidden_channels_and_keeps_the_total():
    mix = {"A": 10.0, "B": 5.0, "C": 2.0}

    folded = fold_mix(mix, {"B", "C"})

    assert folded == {"A": 10.0, UNIDENTIFIED: 7.0}
    assert sum(folded.values()) == sum(mix.values())


def test_fold_mix_without_hidden_channels_is_the_same_mix():
    mix = {"A": 10.0, "B": None}

    assert fold_mix(mix, set()) == mix
    assert fold_mix(mix, {"Z"}) == mix


def test_fold_mix_treats_a_missing_value_as_zero():
    assert fold_mix({"A": 1.0, "B": None}, {"B"}) == {"A": 1.0, UNIDENTIFIED: 0.0}


def test_the_bucket_name_is_shown_as_is():
    assert identifiability.UNIDENTIFIED == "Não identificados"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/engine/test_identifiability.py -q`
Expected: ERROR com `ImportError` / `ModuleNotFoundError: engine.identifiability`.

- [ ] **Step 3: Implementar**

Crie `engine/identifiability.py`:

```python
"""Per-channel identifiability (A5): the bootstrap spread of a channel's contribution decides whether it is published."""

import numpy as np

UNIDENTIFIED = "Não identificados"


def assess(mmm: dict) -> dict[str, dict]:
    """{channel: {"ci": (p2.5, p97.5), "identifiable": bool, "reasons": [...]}}, the CI in KPI units over the period.

    The Ridge is positive, so a contribution is never negative: "the CI crosses zero" is p2.5 == 0.
    """
    totals = np.asarray(mmm["channel_totals"])
    contributions = np.asarray(mmm["coef_samples"]) * totals
    points = np.asarray(mmm["model"].coef_) * totals
    lo, hi = np.percentile(contributions, [2.5, 97.5], axis=0)
    verdicts = {}
    for i, name in enumerate(mmm["spend_cols"]):
        reasons = []
        if lo[i] <= 0:
            reasons.append("coef_ci_includes_zero")
        if hi[i] - lo[i] > points[i]:
            reasons.append("coef_ci_too_wide")
        verdicts[name] = {"ci": (float(lo[i]), float(hi[i])), "identifiable": not reasons, "reasons": reasons}
    return verdicts


def unidentified(verdicts: dict[str, dict]) -> set[str]:
    return {name for name, verdict in verdicts.items() if not verdict["identifiable"]}


def fold_mix(mix: dict[str, float | None], hidden: set[str]) -> dict[str, float | None]:
    """The mix without the hidden channels, their spend summed under UNIDENTIFIED (a missing value counts as 0)."""
    if not hidden & mix.keys():
        return mix
    kept = {name: value for name, value in mix.items() if name not in hidden}
    kept[UNIDENTIFIED] = sum(value or 0.0 for name, value in mix.items() if name in hidden)
    return kept
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/engine/test_identifiability.py -q`
Expected: PASS (8 testes).

- [ ] **Step 5: Commit**

```bash
uv run ruff format engine tests && uv run ruff check engine tests
git add engine/identifiability.py tests/engine/test_identifiability.py
git commit -m "feat(engine): decide per-channel identifiability from the bootstrap contribution interval"
```

---

### Task 3: Veredito no `Computed` e dataset identificável

**Files:**
- Modify: `engine/pipeline.py:12` (import), `:41-57` (`Computed`), `:185-211` (`run_elasticity`)
- Modify: `tests/engine/synthetic_data.py` (gerador novo no fim)
- Modify: `tests/engine/conftest.py` (fixture nova)
- Test: `tests/engine/test_identifiability.py` (acrescentar)

- [ ] **Step 1: Gerador e fixture**

No fim de `tests/engine/synthetic_data.py`:

```python
def make_identifiable_dataset(out_dir: Path, n_days: int = 364) -> dict[str, Path | None]:
    """Two channels with widely varying spend: STRONG drives the KPI, NOEFFECT does not (A5 acceptance).

    Not "NULL" as a name: pandas reads it as a missing value.
    """
    rng = np.random.default_rng(7)
    out_dir.mkdir(parents=True, exist_ok=True)
    days = pd.date_range(START, periods=n_days, freq="D")
    strong = 1000 * rng.lognormal(0, 0.5, n_days)
    noeffect = 800 * rng.lognormal(0, 0.5, n_days)
    carried = np.zeros(n_days)
    for t in range(n_days):
        carried[t] = strong[t] + (0.5 * carried[t - 1] if t else 0.0)
    kpi = (5000 + 3000 * carried / (carried + 2000)) * rng.lognormal(0, 0.03, n_days)

    paths: dict[str, Path | None] = {
        "investment_file": out_dir / "investment.csv",
        "performance_file": out_dir / "performance.csv",
        "generic_trends_file": None,
    }
    investment = pd.DataFrame(
        {
            "dates": np.tile(days, 2),
            "product_group": np.repeat(["STRONG", "NOEFFECT"], n_days),
            "total_revenue": np.concatenate([strong, noeffect]),
        }
    )
    investment.to_csv(paths["investment_file"], index=False, date_format="%Y-%m-%d")
    pd.DataFrame({"date": days, "Sessions": kpi}).to_csv(paths["performance_file"], index=False, date_format="%Y-%m-%d")
    return paths


def identifiable_config() -> dict:
    """dataset_config without the trends file, which make_identifiable_dataset does not write."""
    config = dataset_config()
    config["column_mapping"] = {k: v for k, v in config["column_mapping"].items() if k != "generic_trends_file"}
    return config
```

Em `tests/engine/conftest.py`, troque o import por `from tests.engine.synthetic_data import dataset_config, identifiable_config, make_dataset, make_identifiable_dataset` e acrescente no fim:

```python
@pytest.fixture(scope="session")
def identifiable_computed(tmp_path_factory):
    inputs = make_identifiable_dataset(tmp_path_factory.mktemp("identifiable"))
    with threadpool_limits(limits=1):
        return compute(inputs, EngineConfig.from_input(identifiable_config()))
```

- [ ] **Step 2: Testes do pipeline**

No fim de `tests/engine/test_identifiability.py`:

```python
def test_compute_keeps_the_bootstrap_matrix_and_the_verdicts(synthetic_computed):
    mmm = synthetic_computed.mmm
    assert mmm["coef_samples"].shape == (200, len(mmm["spend_cols"]))
    np.testing.assert_allclose(mmm["coef_samples"].mean(axis=0), mmm["model"].coef_)
    assert set(synthetic_computed.identifiability) == set(mmm["spend_cols"])


def test_the_flat_spend_synthetic_has_no_identifiable_channel(synthetic_computed):
    # spend varies ~3% outside two spikes: the split between channels is not separable (measured 05/nov/2026)
    assert unidentified(synthetic_computed.identifiability) == set(synthetic_computed.mmm["spend_cols"])


def test_a_strong_channel_is_identifiable_and_a_no_effect_one_is_not(identifiable_computed):
    verdicts = identifiable_computed.identifiability
    assert verdicts["STRONG"]["identifiable"] is True
    assert verdicts["NOEFFECT"]["identifiable"] is False
    assert "coef_ci_includes_zero" in verdicts["NOEFFECT"]["reasons"]
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `uv run pytest tests/engine/test_identifiability.py -q`
Expected: os 3 novos falham com `AttributeError: 'Computed' object has no attribute 'identifiability'`.

- [ ] **Step 4: Implementar**

Em `engine/pipeline.py`, import: `from engine import analysis, elasticity_analysis, identifiability, outputs, results`.

No `Computed`, depois de `validation: ...`:

```python
    identifiability: dict = field(default_factory=dict)  # channel -> identifiability.assess verdict; {} without a model
```

Em `run_elasticity`, logo depois de `if not mmm: return result`:

```python
    result["identifiability"] = identifiability.assess(mmm)
```

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest tests/engine/test_identifiability.py -q`
Expected: PASS (11 testes). Se `test_a_strong_channel...` falhar, imprima `verdicts` e pare: a medição de 05/nov/2026 deu STRONG `ci=(11786, 25810)` com ponto 19304, e NOEFFECT `ci=(0, 0)`.

- [ ] **Step 6: Commit**

```bash
uv run ruff format engine tests && uv run ruff check engine tests
git add engine/pipeline.py tests/engine/synthetic_data.py tests/engine/conftest.py tests/engine/test_identifiability.py
git commit -m "feat(engine): compute keeps the identifiability verdict of each modeled channel"
```

---

### Task 4: `results.json` publica só o que é identificável

**Files:**
- Modify: `engine/results_schema.py` (`ChannelFit`)
- Modify: `engine/results.py` (import, `_response_rows`, `_channel_fits`, `_elasticity`, `run_status`)
- Test: `tests/engine/test_results_build.py`

- [ ] **Step 1: Atualizar e escrever os testes**

Em `tests/engine/test_results_build.py`, acrescente `from engine import identifiability` aos imports e este helper logo antes de `def test_elasticity_metrics_and_channels`:

```python
def _with_verdicts(computed, hidden=frozenset()):
    """The computed with every channel identifiable except `hidden` (the synthetic itself has none identifiable)."""
    verdicts = {
        ch: {
            "ci": (1.0, 2.0),
            "identifiable": ch not in hidden,
            "reasons": ["coef_ci_includes_zero"] if ch in hidden else [],
        }
        for ch in computed.mmm["spend_cols"]
    }
    return dataclasses.replace(computed, identifiability=verdicts)
```

Substitua `test_elasticity_metrics_and_channels` por:

```python
def test_elasticity_metrics_and_channels(synthetic_computed):
    elasticity = results.build_results(_with_verdicts(synthetic_computed), "v").elasticity
    mmm = synthetic_computed.mmm
    assert elasticity.status == "ok" and elasticity.reasons == []
    assert elasticity.metrics.cv_r2 == mmm["cv_r_squared"] and elasticity.metrics.r2 == mmm["r_squared"]
    assert elasticity.metrics.media_contribution_pct == mmm["marketing_contribution_of_kpi_pct"]
    assert [c.name for c in elasticity.channels] == list(mmm["spend_cols"])
    for i, channel in enumerate(elasticity.channels):
        assert channel.hill.K == mmm["optimal_params"]["ks"][i] and channel.hill.n == mmm["optimal_params"]["ss"][i]
        assert channel.adstock == mmm["optimal_params"]["alphas"][i]
        assert channel.observed_spend_range[0] <= channel.observed_spend_range[1]
        assert len(channel.curve) == 100 and channel.identifiable is True
        assert channel.coef_ci == (1.0, 2.0) and channel.reasons == []
```

Em `test_response_curve_rows_map_the_columns`, troque a primeira linha por `curve = results.build_results(_with_verdicts(synthetic_computed), "v").elasticity.response_curve`.

Em `test_run_status_matrix`, acrescente no fim:

```python
    assert results.run_status(causal("ok"), elasticity("inconclusive")) == "inconclusive"
    assert results.run_status(causal("inconclusive"), elasticity("inconclusive")) == "inconclusive"
```

E acrescente estes testes depois de `test_response_curve_rows_map_the_columns`:

```python
def test_an_unidentified_channel_loses_its_fit_and_its_mix_key(synthetic_computed):
    built = results.build_results(_with_verdicts(synthetic_computed, hidden={"DISPLAY"}), "v")
    dumped = _dump(built)["elasticity"]
    display = next(c for c in dumped["channels"] if c["name"] == "DISPLAY")
    assert display["identifiable"] is False and display["reasons"] == ["coef_ci_includes_zero"]
    assert display["coef_ci"] == [1.0, 2.0] and display["observed_spend_range"] is not None
    assert display["curve"] == [] and display["hill"] is None and display["adstock"] is None
    assert display["contribution_pct"] is None
    for row in dumped["response_curve"]:
        for mix in row["mix"].values():
            assert "DISPLAY" not in mix and identifiability.UNIDENTIFIED in mix
    assert dumped["status"] == "ok"


def test_mix_totals_survive_the_fold(synthetic_computed):
    plain = results.build_results(_with_verdicts(synthetic_computed), "v").elasticity.response_curve
    hidden = {"DISPLAY", "SOCIAL"}
    folded = results.build_results(_with_verdicts(synthetic_computed, hidden=hidden), "v").elasticity.response_curve
    for a, b in zip(plain, folded, strict=True):
        for variant in a.mix:
            total_a = sum(v or 0 for v in a.mix[variant].values())
            assert sum(v or 0 for v in b.mix[variant].values()) == pytest.approx(total_a)


def test_no_identifiable_channel_makes_elasticity_inconclusive(synthetic_computed):
    elasticity = results.build_results(synthetic_computed, "v").elasticity  # flat-spend synthetic: none identifiable
    assert elasticity.status == "inconclusive" and elasticity.reasons == ["no_identifiable_channel"]
    assert elasticity.response_curve and elasticity.scenarios
    assert all(set(m) == {identifiability.UNIDENTIFIED} for row in elasticity.response_curve for m in row.mix.values())
    assert all(c.identifiable is False and c.curve == [] and c.coef_ci is not None for c in elasticity.channels)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/engine/test_results_build.py -q`
Expected: falham `test_elasticity_metrics_and_channels` (`reasons` não existe em `ChannelFit`), os três novos e o `test_run_status_matrix`.

- [ ] **Step 3: Implementar**

Em `engine/results_schema.py`, no `ChannelFit`, depois de `coef_ci`:

```python
    reasons: list[str] = Field(default_factory=list)  # coef_ci_includes_zero, coef_ci_too_wide (A5)
```

Em `engine/results.py`, acrescente `from engine import identifiability` aos imports (o módulo só importa numpy; não há ciclo).

Em `_response_rows`, depois de `spend_cols = computed.mmm["spend_cols"]`:

```python
    hidden = identifiability.unidentified(computed.identifiability)
```

e troque o `mix={...}` por:

```python
                mix={
                    variant: identifiability.fold_mix(
                        {ch: _num(record.get(f"Spend_{ch}_{suffix}")) for ch in spend_cols}, hidden
                    )
                    for variant, suffix in MIX_VARIANTS.items()
                },
```

Substitua `_channel_fits` por:

```python
def _channel_fits(computed: "Computed") -> list[ChannelFit]:
    """A channel that is not identifiable keeps only its verdict and observed spend: no share, Hill, adstock or curve."""
    mmm = computed.mmm
    params, frame = mmm["optimal_params"], mmm["dataframe"]
    curves = computed.individual_curves_df
    fits = []
    for i, name in enumerate(mmm["spend_cols"]):
        verdict = computed.identifiability[name]
        fit = ChannelFit(
            name=name,
            identifiable=verdict["identifiable"],
            coef_ci=tuple(_num(v) for v in verdict["ci"]),
            reasons=verdict["reasons"],
            observed_spend_range=(_num(frame[name].min()), _num(frame[name].max())),
        )
        if verdict["identifiable"]:
            fit.contribution_pct = _num(mmm["contribution_pct"].get(name))
            fit.hill = Hill(K=_num(params["ks"][i]), n=_num(params["ss"][i]))
            fit.adstock = _num(params["alphas"][i])
            if curves is not None and not curves.empty:
                own = curves[curves["Channel"] == name]
                fit.curve = [CurvePoint(x=_num(r.Channel_Spend), y=_num(r.Projected_Total_KPIs)) for r in own.itertuples()]
        fits.append(fit)
    return fits
```

(Atribuição em model pydantic depois de criado funciona porque o `_Model` não é `frozen`. Se `validate_assignment` estiver ligado em algum momento, continua válido.)

Em `_elasticity`, substitua o `return Elasticity(...)` por:

```python
    none_identifiable = identifiability.unidentified(computed.identifiability) >= set(mmm["spend_cols"])
    return Elasticity(
        status="inconclusive" if none_identifiable else "ok",
        reasons=["no_identifiable_channel"] if none_identifiable else [],
        metrics=ElasticityMetrics(
            cv_r2=_num(mmm["cv_r_squared"]),
            r2=_num(mmm["r_squared"]),
            media_contribution_pct=_num(mmm["marketing_contribution_of_kpi_pct"]),
        ),
        channels=_channel_fits(computed),
        groups=groups,
        response_curve=_response_rows(computed),
        scenarios=_scenarios(computed),
    )
```

Substitua `run_status` por:

```python
def run_status(causal: Causal, elasticity: Elasticity | None) -> str:
    """succeeded when both analyses are ok, failed when neither published anything, inconclusive otherwise.

    An inconclusive elasticity still publishes the total curve and the scenarios (A5), so it counts as something.
    """
    ok = [causal.status == "ok", elasticity is not None and elasticity.status == "ok"]
    if all(ok):
        return "succeeded"
    if any(ok) or (elasticity is not None and elasticity.status == "inconclusive"):
        return "inconclusive"
    return "failed"
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/engine/test_results_build.py tests/engine/test_results_schema.py tests/engine/test_results_fixtures.py -q`
Expected: PASS. Os fixtures em `tests/fixtures/results/` continuam válidos (campo novo é opcional).

- [ ] **Step 5: Commit**

```bash
uv run ruff format engine tests && uv run ruff check engine tests
git add engine/results_schema.py engine/results.py tests/engine/test_results_build.py
git commit -m "feat(engine): results.json drops the fit and mix of channels that are not identifiable"
```

---

### Task 5: Cenários do Markdown, HTML global e Gemini sem o canal

**Files:**
- Modify: `engine/outputs.py:15` (import) e `_scenario` (`:83-92`)
- Test: `tests/engine/test_outputs.py`

- [ ] **Step 1: Escrever o teste**

No fim de `tests/engine/test_outputs.py` (acrescente `import pytest` e `from engine import identifiability` aos imports):

```python
def test_scenario_splits_fold_the_unidentified_channels():
    computed = SimpleNamespace(
        current_split={"A": 0.5, "B": 0.3, "C": 0.2},
        optimized_mix={"A": 0.6, "B": 0.2, "C": 0.2},
        identifiability={"A": {"identifiable": True}, "B": {"identifiable": False}, "C": {"identifiable": False}},
    )

    scenario = outputs._scenario("t", "d", {"Daily_Investment": 10.0}, 3.0, computed, {"A": 0.7, "B": 0.1, "C": 0.2})

    for split in scenario["splits"].values():
        assert set(split) == {"A", identifiability.UNIDENTIFIED}
        assert sum(split.values()) == pytest.approx(30.0)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/engine/test_outputs.py -q`
Expected: FAIL (`set(split)` tem `B` e `C`).

- [ ] **Step 3: Implementar**

Em `engine/outputs.py`, import: `from engine import identifiability, presentation, recommendations, reports`. Em `_scenario`, troque a linha `"splits": ...` por:

```python
        "splits": {
            label: identifiability.fold_mix({k: v * total for k, v in mix.items()}, hidden)
            for label, mix in zip(MIX_LABELS, mixes, strict=True)
        },
```

e acrescente, logo depois de `mixes = (...)`:

```python
    hidden = identifiability.unidentified(computed.identifiability)  # keeps them out of the .md, HTML and Gemini
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/engine/test_outputs.py tests/engine/test_reports.py tests/engine/test_presentation.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff format engine tests && uv run ruff check engine tests
git add engine/outputs.py tests/engine/test_outputs.py
git commit -m "feat(engine): the global report and the gemini payload fold unidentified channels"
```

---

### Task 6: Testes de run refletem o sintético sem canal identificável

**Files:**
- Modify: `tests/engine/test_results_run.py:58`, `:89`
- Modify: `tests/engine/test_run.py:61`, `:66`, `:109`, `:133`
- Modify: `tests/engine/test_collinearity.py:147`

Pelo fato medido no topo, todo run sobre o sintético dá `elasticity.status == "inconclusive"` e o run `inconclusive`.

- [ ] **Step 1: Rodar e ver falhar**

Run: `uv run pytest tests/engine/test_results_run.py tests/engine/test_run.py tests/engine/test_collinearity.py -q`
Expected: falham exatamente os asserts das linhas listadas acima (status `succeeded`/`ok` esperado, `inconclusive` obtido). Se falhar outro teste, pare e investigue.

- [ ] **Step 2: Atualizar os asserts**

`tests/engine/test_results_run.py:58`:

```python
    assert results.status == "inconclusive" and results.causal.status == "ok"
    assert results.elasticity.status == "inconclusive" and results.elasticity.reasons == ["no_identifiable_channel"]
```

`tests/engine/test_results_run.py:89`: `assert result["elasticity"]["status"] == "inconclusive"` (o `result["status"] == "inconclusive"` da linha 87 continua certo pelo novo `run_status`).

`tests/engine/test_run.py:61`: `assert r["schema_version"] == 1 and r["status"] == "inconclusive"`.

`tests/engine/test_run.py:66`: `assert r["causal"]["status"] == "ok" and r["elasticity"]["reasons"] == ["no_identifiable_channel"]`.

`tests/engine/test_run.py:109` e `:133`: `assert run.result["status"] == "inconclusive"`.

`tests/engine/test_collinearity.py:147`:

```python
    assert elasticity["status"] == "inconclusive" and elasticity["reasons"] == ["no_identifiable_channel"]
```

- [ ] **Step 3: Rodar e ver passar**

Run: `uv run pytest tests/engine/test_results_run.py tests/engine/test_run.py tests/engine/test_collinearity.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
uv run ruff format tests && uv run ruff check tests
git add tests/engine/test_results_run.py tests/engine/test_run.py tests/engine/test_collinearity.py
git commit -m "test(engine): runs on the flat-spend synthetic have no identifiable channel"
```

---

### Task 7: Docs e verificação final

**Files:**
- Modify: `docs/m2/trilha-a-motor.md` (seção A5: linha `Status` nova, logo depois do título)
- Modify: `CLAUDE.md` (parágrafo "Estado atual")
- Modify: `docs/decisoes/engine.md` (seção nova antes de `## Passos do swap (Dev B)`)
- Modify: `docs/m2/README.md` (§3, linha de `channels`)

- [ ] **Step 1: Suíte inteira**

Run: `uv run pytest -q` (com o Postgres do `docker compose up -d` no ar, para `tests/api`).
Expected: tudo verde, exceto os testes que já pulam no Windows (paridade). Anote a contagem para o Status.

Run: `uv run ruff format --check . && uv run ruff check .`
Expected: limpo.

- [ ] **Step 2: Docs**

`docs/m2/trilha-a-motor.md`, logo abaixo de `## A5 · Identificabilidade por canal — semana 3`:

```markdown
- **Status:** ✅ feito em 05/nov/2026. `channels[].coef_ci` é o p2.5/p97.5 da contribuição do canal no período (unidade do KPI) sobre as 200 reamostragens; `identifiable=false` quando p2.5 ≤ 0 (a Ridge é positiva) ou a largura passa do ponto; o canal sai sem contribuição, Hill, adstock e curva, e o spend dele entra em `"Não identificados"` no mix da curva, dos cenários e do payload do Gemini. Só publicação: modelo e otimizador iguais, paridade intacta. Nenhum canal identificável → `elasticity` `inconclusive` (`no_identifiable_channel`), com a curva total publicada. Verificado: `tests/engine/test_identifiability.py` (sintético com `STRONG` identificável e `NOEFFECT` não), `test_results_build.py`, `test_outputs.py`; a matriz fica em `mmm["coef_samples"]` para o A8. **Medido:** no sintético da paridade todo canal sai não identificável (spend quase constante), então os runs dele ficam `inconclusive`. Falta: rodar na Gol e nas Core, regenerar os fixtures do A1 (precisa da Gol) e a paridade no Linux. Spec: `docs/superpowers/specs/2026-11-05-a5-identificabilidade-design.md`.
```

`CLAUDE.md`, no "Estado atual", logo depois da frase do A3 (termina em "abaixo de 30 períodos completos não avalia."):

```markdown
**A5 (identificabilidade) concluído em 05/nov/2026**: `coef_ci` da contribuição por canal do bootstrap, `identifiable=false` com p2.5 ≤ 0 ou IC mais largo que o ponto; o canal sai de curva, Hill, mix (vira `"Não identificados"`), cenários e Gemini, sem mudar o modelo; nenhum canal identificável deixa a elasticidade `inconclusive`. No sintético da paridade nenhum canal é identificável.
```

e, na frase "Faltam: A4–A10 (Trilha A)", troque por "Faltam: A4 e A6–A10 (Trilha A)".

`docs/decisoes/engine.md`, seção nova antes de `## Passos do swap (Dev B)`:

```markdown
## Identificabilidade (A5, 05/nov/2026)

- **Só publicação.** O canal não identificável continua no ajuste e no otimizador; o `results.json` e o payload do Gemini é que o escondem. **Por quê:** congelar ou tirar do modelo muda números que a A10 ainda audita, e a paridade fica intacta.
- **IC em unidade do KPI.** `coef_b × Σ X_scaled` por reamostragem, p2.5/p97.5. O coeficiente da Ridge vive no espaço MinMax e não significa nada fora do modelo.
- **"Cruza zero" é p2.5 ≤ 0.** A Ridge tem `positive=True`; zero exato é o canal zerado em ≥ 2,5% das reamostragens. Largura > ponto também reprova. Regra fixa, sem `gate_thresholds`.
- **Bucket `"Não identificados"`.** O spend dos canais escondidos é somado nessa chave no mix da curva, dos cenários e do `.md`/HTML global; os totais não mudam.
- **Nenhum identificável → `inconclusive`, não `failed`.** A curva total e os cenários saem; o `run_status` conta elasticidade `inconclusive` como "publicou algo".
- **Estrito nos dados atuais.** No sintético da paridade (spend com ~3% de ruído) todo canal reprova; com spend lognormal σ = 0,5 o canal forte passa. A Gol deve reprovar toda. Calibrar com a Data Science na A10.
- **O IC é condicional aos hiperparâmetros** (adstock, Hill) do ajuste final: o bootstrap só reamostra a Ridge, então é mais estreito que o verdadeiro. Para a A10.
```

`docs/m2/README.md` §3, na linha de `"channels"`, troque `"identifiable":true,"coef_ci":[…,…],` por `"identifiable":true,"coef_ci":[…,…],"reasons":[],`, e logo depois do bloco JSON (antes da lista que começa com `- \`scenarios[].name\``), acrescente o item:

```markdown
- Canal com `identifiable=false` sai sem `contribution_pct`, `hill`, `adstock` e `curve`, com `reasons` (`coef_ci_includes_zero`, `coef_ci_too_wide`); no `mix`, o spend dele entra somado na chave `"Não identificados"`. Nenhum identificável → `elasticity.status="inconclusive"` com `no_identifiable_channel` (A5).
```

- [ ] **Step 3: Commit**

```bash
git add docs/m2/trilha-a-motor.md CLAUDE.md docs/decisoes/engine.md docs/m2/README.md docs/superpowers/specs/2026-11-05-a5-identificabilidade-design.md
git commit -m "docs(a5): record the identifiability gate"
```
