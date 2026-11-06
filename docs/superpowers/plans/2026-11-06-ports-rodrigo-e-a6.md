# Ports do Rodrigo (A3–A5) e A6 · Suficiência e placebo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trazer para o `main` as peças do branch do Rodrigo (`origin/feat/a0-engine-package`) que melhoram nossos A3, A4 e A5, e reimplementar o A6 dele sobre o `main` (placebo por evento, WMAPE fora da amostra, `sufficiency` do run).

**Architecture:** As versões do `main` ficam; nada é cherry-pick. O gate do A3 passa a olhar o VIF e grava em `collinearity.unresolved` os canais que continuam colineares depois dos grupos; o A5 lê essa lista em `compute()` e esconde esses canais com o motivo `collinearity`. O A6 calcula placebo e WMAPE dentro de `run_causal_impact_analysis`, decide o gate do evento só em `_gate_reasons`, julga o run num módulo puro (`engine/sufficiency.py`) e rebaixa eventos criando outcomes novos, sem mutar os analisados. Os limiares novos vão para o `GATE_DEFAULTS` do `main` (não existe `GateThresholds` aqui).

**Tech Stack:** Python 3.13, numpy, pandas, statsmodels, scikit-learn, pydantic 2, pytest; React 19 + TypeScript na aba Causal. `uv` e `bun`.

**Leia antes:** `CODE-STYLE.md` (motor), `docs/m2/README.md` (contrato §2 e §3), `docs/m2/trilha-a-motor.md` (A3–A6), `docs/decisoes/engine.md` (A3, A4, A5). O código do Rodrigo se lê com `git show origin/feat/a0-engine-package:<caminho>`; o desenho do A6 dele está em `docs/superpowers/specs/2026-11-05-a6-suficiencia-placebo-design.md` e `docs/superpowers/plans/2026-11-05-a6-suficiencia-placebo.md` naquele branch.

---

## Decisões em aberto

O plano segue o default de cada item. Se o dono decidir diferente, o efeito está descrito na task indicada.

1. **Run com 0 canal identificável.** Hoje (nosso A5) a elasticidade sai `inconclusive` com `no_identifiable_channel`; no branch do Rodrigo sai `ok` (o run pode ser `succeeded`). Afeta o B5 parte 2 (como mostrar a curva) e o gatilho do A7 (`status == "inconclusive"` dispara o experiment designer em todo run sem canal identificável, e hoje isso é o sintético da paridade e, pela medição do Rodrigo, a Gol inteira). **Default: fica o nosso (`inconclusive`).** Nenhuma task muda isso.
2. **`control_rejected` nos `reasons` do evento.** O spec do A4 diz "rejeitado e listado em `reasons`", e o `main` faz isso; a aba Causal do B5 mostra o código cru e, num evento rejeitado, dentro da lista "Este evento não foi publicado", como se fosse motivo da rejeição. (a) tirar dos `reasons` (o sinal fica em `controls[].accepted`; contraria a letra do spec, muda o contrato) ou (b) manter e dar um rótulo pt-BR, mostrado como observação e não como motivo. **Default: (b)**, porque não muda o contrato. Task 4 tem os dois ramos.
3. **Gate de robustez `model_dependent`** (refazer o ajuste do evento sem as features de mídia e rejeitar o lift que só é significativo com elas). Não está no spec do A6. **Mas a medição do Rodrigo diz que o placebo sozinho não passa o aceite do ruído branco:** com KPI de ruído puro, 6 de 10 sementes ainda publicavam evento antes desse gate. **Default: não entra**; a Task 13 é opcional e fica por último. A Task 12 mede o aceite do ruído branco; se ele falhar, o teste fica `xfail(strict=True)` apontando para esta decisão, e o A6 não pode ser dado como feito até o dono escolher (Task 13 ou outro caminho).
4. **Risco de calibração do gate de VIF.** O spec do A3 manda bloquear com VIF > 10. O VIF pega canais que sobem juntos sem nenhum par passar de |r| 0.85 (ex.: todos crescendo com o orçamento do ano), então datasets que hoje passam no `validate` (a Gol, as Core) podem passar a ser bloqueados. **Default: segue o spec** (`vif_max` = 10 em `GATE_DEFAULTS`, ajustável por run em `gate_thresholds`; `block_per_channel` continua saindo). Medir na Gol (`tests/engine/test_validate_real.py`, local) e nas Core assim que chegarem; a A10 calibra.

**Premissas deste plano** (decisões de implementação, registradas em `docs/decisoes/engine.md` na Task 14):

- Placebo que não roda por pré-período curto (metade < `min_pre_periods` ou segunda metade < pós) **não rejeita** o evento: sai `placebo: {p_value: null, passed: null}`.
- Exceção no ajuste do placebo ou do WMAPE **não é engolida**: sobe até o `except` que já existe em `run_causal_impact_analysis` e o evento vira `analysis_failed`. É o conserto do `except Exception` do Rodrigo, que fazia um placebo que não rodou passar calado.
- `cv_in_sample` deixa a **elasticidade** `inconclusive` (status + motivo, a curva continua publicada, como no A5), em vez do `status: ok` com motivo informativo e da regra extra em `run_status` do Rodrigo. Com isso cada motivo da suficiência cai numa seção e o `run_status` não muda.
- Os limiares novos (`vif_max`, `spend_cv_min`, `oos_wmape_max`) são provisórios: a A10 calibra.

---

## File Structure

| Arquivo | Papel |
|---|---|
| `engine/config.py` | `GATE_DEFAULTS` ganha `vif_max`, `spend_cv_min`, `oos_wmape_max`; o validador aceita VIF > 1; o legacy dict leva os dois do A6 |
| `engine/results_schema.py` | `Collinearity.unresolved`; `Sufficiency.reasons` e `cv_out_of_sample`; comentários de `Placebo` e `ChannelFit.reasons` |
| `engine/validation.py` | gate por VIF, grupo sugerido para canal só de VIF, `unresolved`, `channel_group_name_taken` |
| `engine/analysis.py` | `CALENDAR_COLUMNS` exato; `cumulative_p_value`, `_fit_state_space`, `placebo_p_value`, `oos_wmape` (e, opcional, `baseline_only_test`) |
| `engine/elasticity_analysis.py` | `cv_folds` e `mmm["cv_out_of_sample"]` |
| `engine/sufficiency.py` (novo) | `spend_cv`, `assess`, `CAUSAL_REASONS` |
| `engine/identifiability.py` | motivo `collinearity`, `reallocation_suppressed`, `fold_mix` com `None` |
| `engine/pipeline.py` | `assess` em `compute()`; gate `placebo_failed`; `judge_sufficiency`; `Computed.sufficiency` |
| `engine/results.py` | placebo, `fit.wmape`, `insufficient_run` sem lift, motivos da suficiência, `reallocation_suppressed`, `sufficiency` no documento |
| `engine/outputs.py` | realocação fora do `.md` e do prompt sempre que um canal está escondido |
| `web/src/lib/results.ts`, `web/src/components/causal/EventDetail.tsx` | rótulos pt-BR dos motivos novos; `control_rejected` como observação |
| `tests/engine/synthetic_data.py` | `collinear_inputs` (movido do teste) e `seed` no `make_identifiable_dataset` |
| `tests/engine/test_parity.py`, `test_parity_real.py`, `real_data.py`, `tests/fixtures/parity/make_a4_golden.py` (novo), `tests/fixtures/parity/README.md`, `mise.toml` | paridade causal completa no sintético; golden do motor para a Gol |
| testes novos | `test_placebo.py`, `test_sufficiency.py`, `test_placebo_acceptance.py`, `test_outputs_identifiability.py`, `test_identifiability_acceptance.py` |
| docs | `CLAUDE.md`, `docs/m2/trilha-a-motor.md`, `docs/m2/README.md`, `docs/decisoes/engine.md` |

## Ordem e paralelismo

Regra: paralelo quando os arquivos não se cruzam; serial só por arquivo compartilhado ou dependência de código.

- **Lote 1 (paralelo):** Task 0 (contrato e config), Task 3 (calendário), Task 5 (paridade), Task 4 (web, ramo b), Task 8 (testes do A5).
- **Lote 2 (paralelo):** Task 1 (VIF; depois da 0 e da 8, que mexe em `synthetic_data.py`), Task 9 (placebo e WMAPE; depois da 3, mesmo `analysis.py`), Task 10 (suficiência; depois da 0).
- **Lote 3 (paralelo):** Task 2 (nome de grupo; depois da 1, mesmo `validation.py`), Task 6 (A5 colinear; depois da 1, lê `unresolved`).
- **Lote 4:** Task 7 (realocação; depois da 6, mesmo `identifiability.py`).
- **Lote 5:** Task 11 (A6 no pipeline e no `results.json`; depois de 6, 7, 9 e 10).
- **Lote 6:** Task 12 (aceite do A6; depois da 11 e da 5).
- **Lote 7:** Task 13 (opcional, só com a decisão 3), depois Task 14 (docs, por último).

Se a decisão 2 for **(a)**, a Task 4 muda `engine/results.py` e `tests/engine/test_results_build.py` e sai do Lote 1: roda depois da Task 11.

| Task | Modelo |
|---|---|
| 0, 2, 3, 4, 8 | haiku |
| 1, 5, 6, 7, 9, 10, 11, 12, 13, 14 | sonnet |

Comandos: `uv run pytest tests/engine/<arquivo> -v` (motor, sem banco); `uv run pytest tests/api/<arquivo> -v` precisa do Postgres (`docker compose up -d`); `uv run ruff format . && uv run ruff check .` antes de cada commit (o código do plano pode passar de 120 colunas; o format quebra as linhas); `cd web && bun run build && bun run lint` no front. A paridade (`tests/engine/test_parity.py`) só roda no Linux: no Windows ela é pulada, e quem verifica é o job `py` do CI ou `mise run parity` numa máquina Linux.

---

### Task 0: limiares novos e campos opcionais do contrato

**Files:**
- Modify: `engine/config.py:12-13` (`GATE_DEFAULTS`), `:60` (comentário do `block_per_channel`), `:92-102` (`_known_gates`), `:120-131` (`to_legacy_dict`)
- Modify: `engine/results_schema.py` (`Collinearity`, `Sufficiency`, `Placebo`, `ChannelFit.reasons`)
- Modify: `tests/api/test_simulations.py:213` (o dict exato de `collinearity`)
- Test: `tests/engine/test_config.py`, `tests/engine/test_results_schema.py`

- [ ] **Step 1: Write the failing tests**

No fim de `tests/engine/test_config.py`:

```python
def test_the_new_gates_have_provisional_defaults_and_reach_the_legacy_dict():
    config = EngineConfig()
    assert config.gate_threshold("vif_max") == 10.0
    legacy = config.to_legacy_dict()
    assert legacy["spend_cv_min"] == 0.10 and legacy["oos_wmape_max"] == 0.30


def test_the_vif_limit_must_be_above_one():
    assert EngineConfig(gate_thresholds={"vif_max": 5.0}).gate_threshold("vif_max") == 5.0
    for value in (1.0, 0.5):
        with pytest.raises(EngineError) as raised:
            EngineConfig.from_input({"gate_thresholds": {"vif_max": value}})
        assert str(raised.value) == "Configuração inválida: campo 'gate_thresholds': limite deve ser maior que 1: vif_max"


@pytest.mark.parametrize("name", ["spend_cv_min", "oos_wmape_max"])
def test_the_a6_limits_are_in_zero_one(name):
    with pytest.raises(EngineError) as raised:
        EngineConfig.from_input({"gate_thresholds": {name: 1.5}})
    assert str(raised.value) == f"Configuração inválida: campo 'gate_thresholds': limite fora de (0, 1): {name}"
```

No fim de `tests/engine/test_results_schema.py` (e ajuste o import da linha 5 para `from engine.results_schema import SCHEMA_VERSION, CausalEvent, Collinearity, Reports, ResultsV1, Sufficiency`):

```python
def test_the_a3_and_a6_fields_are_optional():
    assert Collinearity().unresolved == []
    sufficiency = Sufficiency(passed=False)
    assert sufficiency.reasons == [] and sufficiency.cv_out_of_sample is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_config.py tests/engine/test_results_schema.py -v`
Expected: FAIL — `KeyError: 'vif_max'`, `limite desconhecido: vif_max` e `AttributeError: 'Collinearity' object has no attribute 'unresolved'`.

- [ ] **Step 3: Implement**

`engine/config.py`, troque as linhas 12-13:

```python
# gate thresholds: A3 collinearity (|r| and VIF), A4 control screening, A6 sufficiency. Provisional: A10 calibrates
GATE_DEFAULTS = {
    "collinearity_r": 0.85,
    "vif_max": 10.0,
    "control_spend_corr": 0.5,
    "spend_cv_min": 0.10,
    "oos_wmape_max": 0.30,
}
```

Linha 60:

```python
    block_per_channel: bool = False  # the analyst accepts results only at the aggregate level: collinear channels
    # leave the per-channel results (A3 gate, A5 effect)
```

`_known_gates` (linhas 92-102):

```python
    @field_validator("gate_thresholds")
    @classmethod
    def _known_gates(cls, thresholds: dict[str, float]) -> dict[str, float]:
        unknown = sorted(set(thresholds) - set(GATE_DEFAULTS))
        if unknown:
            raise ValueError(f"limite desconhecido: {', '.join(unknown)}")
        for name in sorted(thresholds):
            if name == "vif_max":
                if not thresholds[name] > 1:  # a VIF is never below 1
                    raise ValueError(f"limite deve ser maior que 1: {name}")
            elif not 0 < thresholds[name] < 1:  # the others are correlations, a variation and an error share
                raise ValueError(f"limite fora de (0, 1): {name}")
        return thresholds
```

Em `to_legacy_dict`, depois de `legacy["control_spend_corr"] = ...`:

```python
        legacy["spend_cv_min"] = self.gate_threshold("spend_cv_min")
        legacy["oos_wmape_max"] = self.gate_threshold("oos_wmape_max")
```

`engine/results_schema.py`:

```python
class Collinearity(_Model):
    pairs: list[dict[str, Any]] = Field(default_factory=list)
    vif: dict[str, float | None] = Field(default_factory=dict)
    suggested_groups: list[list[str]] = Field(default_factory=list)
    # channels as modelled (groups summed) still over a limit: the gate blocks on them, or with block_per_channel A5
    # publishes them only in aggregate
    unresolved: list[str] = Field(default_factory=list)
```

```python
class Sufficiency(_Model):
    passed: bool
    spend_variation: dict[str, Any] | None = None  # CV of the spend of each channel with a validated event
    validated_events: int | None = None
    pre_wmape: float | None = None  # median out-of-sample WMAPE of the validated events
    reasons: list[str] = Field(default_factory=list)  # no_validated_event, low_spend_variation, high_oos_wmape, cv_in_sample
    cv_out_of_sample: bool | None = None  # False: the elasticity CV fell back to in-sample (under 40 rows)
```

```python
class Placebo(_Model):
    p_value: float | None = None
    passed: bool | None = None  # None: the pre-period is too short for a placebo (A6)
```

Em `ChannelFit`, o comentário de `reasons` passa a `# coef_ci_includes_zero, coef_ci_too_wide, collinearity (A5)`.

`tests/api/test_simulations.py:213`:

```python
        "collinearity": {"pairs": [], "vif": {}, "suggested_groups": [], "unresolved": []},
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/engine/test_config.py tests/engine/test_results_schema.py tests/engine/test_results_fixtures.py -v`
Expected: PASS. Com o Postgres no ar: `uv run pytest tests/api/test_simulations.py -v` PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/config.py engine/results_schema.py tests/engine/test_config.py tests/engine/test_results_schema.py tests/api/test_simulations.py
git commit -m "feat(engine): vif and sufficiency gate thresholds and the optional a3/a6 contract fields"
```

---

### Task 1: gate de VIF, grupo sugerido para canal só de VIF e `unresolved` (A3)

**Files:**
- Modify: `engine/validation.py:118-157` (`_connected`, `collinearity`), `:200-236` (`check_groups`), `:268-276` (`validate`)
- Modify: `tests/engine/synthetic_data.py` (recebe `collinear_inputs`)
- Test: `tests/engine/test_collinearity.py`

Contexto: hoje o VIF só reporta. O spec manda bloquear com |r| > 0.85 **ou** VIF > 10. Fica do `main`: mínimo de 30 períodos, pares de overlap (DV360/CM360) fora do gate e das sugestões, VIF ≤ 0 ou > 1e6 vira `None`. Novo: VIF `None` conta como acima do limite; no gate, o VIF é calculado sem o segundo canal de cada par de overlap (senão os gêmeos se bloqueariam pelo VIF); canal sinalizado só pelo VIF entra na sugestão junto com o canal com que mais correlaciona. `unresolved` são os canais (com os grupos somados) acima de algum limite, preenchido mesmo com `block_per_channel`: a Task 6 usa.

- [ ] **Step 1: Move `collinear_inputs` to `synthetic_data.py`**

Apague `collinear_inputs` de `tests/engine/test_collinearity.py` (linhas 14-25) e acrescente no fim de `tests/engine/synthetic_data.py`:

```python
def collinear_inputs(out_dir: Path, *, n_days: int = 364, cadence_days: int = 1) -> dict[str, Path | None]:
    """make_dataset with PMAX spend = 0.8 × SEARCH (r ≈ 0.99): one pair over the 0.85 gate.

    0.8 keeps the totals apart, so dv360_cm360_overlap (same total) does not fire.
    """
    paths = make_dataset(out_dir, n_days=n_days, cadence_days=cadence_days)
    inv = pd.read_csv(paths["investment_file"])
    search = inv.loc[inv["product_group"] == "SEARCH", "total_revenue"].to_numpy()
    noise = np.random.default_rng(3).lognormal(0.0, 0.005, len(search))
    inv.loc[inv["product_group"] == "PMAX", "total_revenue"] = 0.8 * search * noise
    inv.to_csv(paths["investment_file"], index=False)
    return paths
```

No topo de `test_collinearity.py`: `from engine.validation import MIN_COLLINEARITY_PERIODS, channel_vif, collinearity, high_vif, spend_matrix, validate` e `from tests.engine.synthetic_data import collinear_inputs, dataset_config, make_dataset`.

- [ ] **Step 2: Write the failing tests**

Acrescente a `tests/engine/test_collinearity.py`:

```python
def _vif_only_inputs(tmp_path, n=60):
    """C = A + B: no pair is over 0.85 (r(A, C) ≈ 0.7), but C is almost an exact mix of the others (VIF in the thousands)."""
    rng = np.random.default_rng(6)
    a, b = rng.normal(1000, 200, n), rng.normal(1000, 200, n)
    c = a + b + rng.normal(0, 5, n)
    ds = days(n)
    investment = [
        (d, name, round(float(v), 2)) for name, series in (("A", a), ("B", b), ("C", c)) for d, v in zip(ds, series)
    ]
    return write_inputs(tmp_path, investment, [(d, 1000 + i) for i, d in enumerate(ds)])


def test_a_vif_over_the_limit_blocks_even_without_a_pair(tmp_path):
    report = validate(_vif_only_inputs(tmp_path), dataset_config())

    check = next(c for c in report.checks if c.id == "collinearity_unresolved")
    assert report.collinearity.pairs == [] and check.details["pairs"] == []
    assert check.details["vif_channels"] == ["A", "B", "C"]
    assert check.details["suggested_groups"] == [["A", "B", "C"]]
    assert report.collinearity.suggested_groups == [["A", "B", "C"]]
    assert "VIF acima de 10" in check.message


@pytest.mark.parametrize("resolution", [{"channel_groups": [["A", "B", "C"]]}, {"block_per_channel": True}])
def test_a_group_or_the_block_flag_resolves_the_vif_gate(tmp_path, resolution):
    report = validate(_vif_only_inputs(tmp_path), {**dataset_config(), **resolution})

    assert report.ok, [c.id for c in report.checks if c.level == "error"]


def test_the_vif_limit_comes_from_gate_thresholds(tmp_path):
    report = validate(_vif_only_inputs(tmp_path), {**dataset_config(), "gate_thresholds": {"vif_max": 1e9}})

    assert report.ok, [c.id for c in report.checks if c.level == "error"]


def test_an_undefined_vif_counts_as_over_the_limit():
    a = np.arange(40, dtype=float) % 7 + 1
    b = np.random.default_rng(1).normal(10, 1, 40)

    assert high_vif(spend_matrix(_frame({"A": a, "B": b, "C": a + b})), EngineConfig()) == ["A", "B", "C"]


def test_a_vif_only_channel_is_suggested_with_its_most_correlated_channel():
    rng = np.random.default_rng(1)
    a, b = rng.normal(100, 20, 300), rng.normal(100, 20, 300)
    frame = _frame({"A": a, "B": b, "C": a + b + rng.normal(0, 0.5, 300)})

    found = collinearity(spend_matrix(frame), EngineConfig(gate_thresholds={"collinearity_r": 0.95}))

    assert found.pairs == [] and any("C" in group for group in found.suggested_groups)


def test_an_overlap_pair_does_not_block_through_its_vif(tmp_path):
    rng = np.random.default_rng(8)
    x = rng.normal(1000, 200, 60)
    series = {"X": x, "Y": x * (1 + rng.normal(0, 0.01, 60)), "Z": rng.normal(500, 80, 60)}
    ds = days(60)
    investment = [(d, name, round(float(v), 2)) for name, s in series.items() for d, v in zip(ds, s)]

    report = validate(write_inputs(tmp_path, investment, [(d, 1000 + i) for i, d in enumerate(ds)]), dataset_config())

    ids = {c.id for c in report.checks}
    assert "dv360_cm360_overlap" in ids and "collinearity_unresolved" not in ids


def test_unresolved_lists_the_channels_still_collinear_as_modelled(tmp_path):
    blocked = validate(collinear_inputs(tmp_path / "a"), {**dataset_config(), "block_per_channel": True})
    grouped = validate(collinear_inputs(tmp_path / "b"), {**dataset_config(), "channel_groups": [["SEARCH", "PMAX"]]})

    assert blocked.ok and blocked.collinearity.unresolved == ["PMAX", "SEARCH"]
    assert grouped.ok and grouped.collinearity.unresolved == []


def test_the_gate_works_on_weekly_data(tmp_path):
    paths = collinear_inputs(tmp_path, n_days=728, cadence_days=7)

    report = validate(paths, dataset_config())

    assert report.period_days == 7 and "collinearity_unresolved" in {c.id for c in report.checks}
    assert validate(paths, {**dataset_config(), "channel_groups": [["SEARCH", "PMAX"]]}).ok
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_collinearity.py -v`
Expected: FAIL — `ImportError: cannot import name 'high_vif'`.

- [ ] **Step 4: Implement**

`engine/validation.py`, troque `_connected` (linhas 118-123):

```python
def _connected(edges: list[tuple[str, str]]) -> list[list[str]]:
    groups: list[set[str]] = []
    for a, b in edges:
        linked = [g for g in groups if a in g or b in g]
        groups = [g for g in groups if g not in linked] + [{a, b}.union(*linked)]
    return sorted(sorted(g) for g in groups)
```

Depois de `_not_overlap` (linha 143), acrescente:

```python
def _without_twins(wide: pd.DataFrame, overlapping: set[frozenset]) -> pd.DataFrame:
    """One channel of each overlap pair: the twin's VIF only says it duplicates the other, as the overlap check does."""
    twins = {max(pair) for pair in overlapping}
    return wide.drop(columns=[c for c in wide.columns if c in twins])


def high_vif(wide: pd.DataFrame, config: EngineConfig, overlapping: set[frozenset] = frozenset()) -> list[str]:
    """Channels whose VIF is over `vif_max`, or undefined (an exact mix of the others); empty on a short series."""
    if not _assessable(wide):
        return []
    limit = config.gate_threshold("vif_max")
    vif = channel_vif(_without_twins(wide, overlapping))
    return sorted(name for name, value in vif.items() if value is None or value > limit)


def _suggested(wide: pd.DataFrame, pairs: list[dict], vif_channels: list[str]) -> list[list[str]]:
    """Connected components of the pairs; a channel flagged only by its VIF joins the one it correlates with most."""
    edges = [(p["a"], p["b"]) for p in pairs]
    paired = {name for edge in edges for name in edge}
    corr = wide.corr().abs()
    edges += [(name, str(corr[name].drop(name).idxmax())) for name in vif_channels if name not in paired]
    return _connected(edges)
```

`collinearity` (linhas 146-156):

```python
def collinearity(wide: pd.DataFrame, config: EngineConfig, overlapping: set[frozenset] = frozenset()) -> Collinearity:
    """Pairs over the |r| gate, every channel's VIF and the groups the pairs and the VIFs suggest; empty on a short
    series. An overlap pair stays in `pairs` but is not suggested for grouping: summing one source reported twice
    doubles it. `unresolved` is filled by `validate`, on the grouped spend."""
    if not _assessable(wide):
        return Collinearity()
    pairs = _pairs_over(wide, config)
    vif_channels = high_vif(wide, config, overlapping)
    return Collinearity(
        pairs=pairs,
        vif=channel_vif(wide),
        suggested_groups=_suggested(wide, _not_overlap(pairs, overlapping), vif_channels),
    )
```

`check_groups` (linhas 200-236) inteiro:

```python
def check_groups(
    kept_inv: pd.DataFrame, channels: set[str], config: EngineConfig, overlapping: set[frozenset]
) -> tuple[list[Check], list[str]]:
    """The analyst's answer to the gate, judged on the spend as modelled (groups summed): no pair over the |r| limit
    and no VIF over vif_max, or block_per_channel. Also returns the channels still over a limit (A5 hides them)."""
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
    grouped = spend_matrix(apply_channel_groups(kept_inv, config.channel_groups))
    open_pairs = _not_overlap(_pairs_over(grouped, config), overlapping)
    vif_channels = high_vif(grouped, config, overlapping)
    unresolved = sorted({name for p in open_pairs for name in (p["a"], p["b"])} | set(vif_channels))
    if config.block_per_channel or not unresolved:
        return checks, unresolved
    members = {" + ".join(group): group for group in config.channel_groups}
    suggested_groups = sorted(
        sorted({m for name in group for m in members.get(name, [name])})
        for group in _suggested(grouped, open_pairs, vif_channels)
    )
    suggested = "; ".join(" + ".join(group) for group in suggested_groups)
    vif_note = f" VIF acima de {config.gate_threshold('vif_max'):g}: {', '.join(vif_channels)}." if vif_channels else ""
    checks.append(
        Check(
            id="collinearity_unresolved",
            level="error",
            message=(
                "Há canais que gastam juntos, e o modelo não consegue separar o efeito de cada um "
                f"(sugestão: {suggested}).{vif_note} Agrupe-os ou aceite resultados só no nível agregado."
            ),
            details={"pairs": open_pairs, "vif_channels": vif_channels, "suggested_groups": suggested_groups},
        )
    )
    return checks, unresolved
```

Em `validate` (linha 276):

```python
        group_checks, found.unresolved = check_groups(
            kept_inv, set(investment["Product Group"]), engine_config, overlapping
        )
        checks += group_checks
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/engine/test_collinearity.py tests/engine/test_validate_checks.py tests/engine/test_run.py -v`
Expected: PASS (os testes antigos de colinearidade continuam: pares com VIF alto já estão nos pares, então não mudam sugestão nem mensagem).

- [ ] **Step 6: Commit**

```bash
git add engine/validation.py tests/engine/test_collinearity.py tests/engine/synthetic_data.py
git commit -m "feat(engine): vif over vif_max also blocks the collinearity gate and lists the unresolved channels"
```

---

### Task 2: `channel_group_name_taken` (A3)

**Files:**
- Modify: `engine/validation.py` (`check_groups`, logo depois do `channel_group_unknown`)
- Test: `tests/engine/test_collinearity.py`

Contexto: o grupo `["A", "B"]` vira o canal `"A + B"`; se o arquivo já tem um canal com esse nome, `apply_channel_groups` soma os dois em silêncio. Do Rodrigo só vem este check: `group_overlap` e `group_too_small` já são config inválida no `main` (`EngineConfig._groups_are_disjoint`), que é mais cedo (a API devolve 422 ao salvar). Como o `channel_group_unknown`, o check vive só no `validate` (o `run` valida antes de ler).

- [ ] **Step 1: Write the failing test**

```python
def test_a_group_named_like_a_channel_already_in_the_file_is_an_error(tmp_path):
    ds = days(10)
    investment = [(d, name, 100 + i) for name in ("A", "B", "A + B") for i, d in enumerate(ds)]
    paths = write_inputs(tmp_path, investment, [(d, 1000 + i) for i, d in enumerate(ds)])

    report = validate(paths, {**dataset_config(), "channel_groups": [["A", "B"]]})

    check = next(c for c in report.checks if c.id == "channel_group_name_taken")
    assert not report.ok and check.level == "error" and check.details == {"channels": ["A + B"]}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_collinearity.py::test_a_group_named_like_a_channel_already_in_the_file_is_an_error -v`
Expected: FAIL — `StopIteration`.

- [ ] **Step 3: Implement**

Em `check_groups`, depois do bloco `if unknown:`:

```python
    grouped_members = {m for group in config.channel_groups for m in group}
    taken = sorted({" + ".join(group) for group in config.channel_groups} & (channels - grouped_members))
    if taken:
        checks.append(
            Check(
                id="channel_group_name_taken",
                level="error",
                message=(
                    f"O nome do grupo coincide com um canal que já está no arquivo de investimento: {', '.join(taken)}. "
                    "Renomeie esse canal no arquivo."
                ),
                details={"channels": taken},
            )
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/engine/test_collinearity.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/validation.py tests/engine/test_collinearity.py
git commit -m "feat(engine): a channel group named like an existing channel is a validation error"
```

---

### Task 3: colunas de calendário por nome exato (A4)

**Files:**
- Modify: `engine/analysis.py:255-256` (constantes), `:384-389` (`potential_exog_vars`)
- Test: `tests/engine/test_controls.py`

Contexto: hoje entra no Lasso toda coluna do `model_data` que **contém** `"day_"`. No `main` isso não vaza na prática (canais são caixa-alta, o trends vira só `Generic Searches`, os controles são `bcb_*`), mas uma coluna de controle tipo `weekday_spend` entraria sem triagem. A lista exata do Rodrigo fecha isso sem mudar nada no sintético: o conjunto e a ordem (a do `model_data`) são os mesmos.

- [ ] **Step 1: Write the failing test**

No fim de `tests/engine/test_controls.py`:

```python
def test_only_the_calendar_columns_enter_by_name_and_in_the_model_order(monkeypatch):
    from engine import analysis

    seen = []
    real = analysis._select_variance_threshold_features

    def spy(pre, columns, *args, **kwargs):
        seen.append(list(columns))
        return real(pre, columns, *args, **kwargs)

    monkeypatch.setattr(analysis, "_select_variance_threshold_features", spy)
    leaky = pd.DataFrame({"Date": DAYS, "weekday_spend": np.arange(len(DAYS), dtype=float)})

    _event(lambda spend, rng: 50 + rng.normal(0, 5, len(spend)), leaky)

    columns = seen[-1]  # the causal model's call; the response model may call it before
    assert "weekday_spend" not in columns
    calendar = [c for c in columns if c.startswith(("day_", "is_"))]
    assert calendar == ["is_weekend", "is_payday_period", "is_holiday", *(f"day_{i}" for i in range(7))]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_controls.py::test_only_the_calendar_columns_enter_by_name_and_in_the_model_order -v`
Expected: FAIL — `assert 'weekday_spend' not in [...]`.

- [ ] **Step 3: Implement**

Linhas 255-256:

```python
TRENDS_COLUMN = "Generic Searches"
# exact names: a substring match ("day_" in col) would also take any other column that happens to contain it
CALENDAR_COLUMNS = frozenset({"is_weekend", "is_payday_period", "is_holiday", *(f"day_{i}" for i in range(7))})
```

Linhas 384-389:

```python
        # controls before the calendar, where the "generic" match used to put the trends column
        potential_exog_vars = (
            list(transformed_features.keys())
            + accepted
            + [col for col in model_data.columns if col in CALENDAR_COLUMNS]  # model_data's own order, as before
        )
```

Se `CALENDAR_FEATURES` não tiver outro uso (`grep -rn CALENDAR_FEATURES engine tests`), apague-o.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/engine/test_controls.py tests/engine/test_analysis.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/analysis.py tests/engine/test_controls.py
git commit -m "fix(engine): the causal model takes the calendar columns by exact name"
```

---

### Task 4: rótulos pt-BR na aba Causal e `control_rejected` (A4/A6 → B5)

**Files (ramo b, default):**
- Modify: `web/src/lib/results.ts:43-55`
- Modify: `web/src/components/causal/EventDetail.tsx`

Contexto: o `reasonLabel` mostra o código cru para motivo sem rótulo. Os motivos novos deste plano (ids fixos aqui, então a task roda no Lote 1): `control_rejected` (A4), `placebo_failed`, `insufficient_run`, `low_spend_variation`, `high_oos_wmape`, `no_validated_event`, `cv_in_sample` (A6) e `model_dependent` (Task 13, opcional; o rótulo não atrapalha se ela não entrar). O front não tem teste unitário (sem vitest); a verificação é build, lint e o E2E da aba.

- [ ] **Step 1: Labels and the note reasons**

`web/src/lib/results.ts`, troque as linhas 43-55:

```ts
const REASON_LABELS: Record<string, string> = {
  not_significant: 'Não significativo',
  illogical_direction: 'Direção ilógica (KPI contra o investimento)',
  poor_fit: 'Ajuste ruim no pré-período',
  analysis_failed: 'A análise do evento falhou',
  not_selected: 'Superado por outro evento do mesmo período',
  placebo_failed: 'Reprovado no placebo: o modelo acha efeito numa data sem intervenção',
  insufficient_run: 'Os dados desta execução não sustentam publicar lift',
  model_dependent: 'O efeito só aparece com as variáveis de mídia do modelo',
  control_rejected: 'Um controle foi descartado por acompanhar o investimento do canal',
  no_events_detected: 'Nenhum evento de investimento detectado',
  no_eligible_events: 'Nenhum evento com dados suficientes para análise',
  no_event_passed_gates: 'Nenhum evento passou nos critérios de publicação',
  no_validated_event: 'Nenhum evento validado',
  low_spend_variation: 'O investimento varia pouco para medir efeito',
  high_oos_wmape: 'O contrafactual erra demais fora da amostra',
  cv_in_sample: 'Histórico curto: o modelo de elasticidade não foi validado fora da amostra',
}

// a reason the engine adds later shows as its code instead of breaking the screen
export const reasonLabel = (reason: string) => REASON_LABELS[reason] ?? reason

// reasons that annotate an event without being why it was rejected
const NOTE_REASONS = new Set(['control_rejected'])
export const rejectionReasons = (e: CausalEvent) => e.reasons.filter((r) => !NOTE_REASONS.has(r))
export const eventNotes = (e: CausalEvent) => e.reasons.filter((r) => NOTE_REASONS.has(r))
```

- [ ] **Step 2: Show notes apart from the rejection reasons**

`web/src/components/causal/EventDetail.tsx`: no import de `@/lib/results`, acrescente `eventNotes` e `rejectionReasons`. Em `EventDetail`, logo depois de `<p className="text-sm text-muted-foreground">{eventPeriod(event)}</p>`:

```tsx
        {eventNotes(event).map((r) => (
          <p key={r} className="text-sm text-muted-foreground">
            {reasonLabel(r)}.
          </p>
        ))}
```

Em `Rejected`, troque `{event.reasons.map((r) => (` por `{rejectionReasons(event).map((r) => (`.

- [ ] **Step 3: Build and lint**

Run: `cd web && bun run build && bun run lint`
Expected: sem erro.

- [ ] **Step 4: E2E da aba**

Com `docker compose up -d`: `mise run e2e -- results.spec.ts` (ou `cd web && bun run e2e results.spec.ts`).
Expected: PASS (o fixture da Gol não tem os motivos novos; o teste prova que a aba não quebrou). Com `mise run web` no ar, abra a aba Causal de um run e tire um screenshot pelo MCP `playwright` antes de reportar (CLAUDE.md, "Verificar mudanças no frontend").

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/results.ts web/src/components/causal/EventDetail.tsx
git commit -m "feat(web): pt-br labels for the a4/a6 reasons and control_rejected as a note"
```

**Ramo (a), só se o dono escolher tirar `control_rejected` dos `reasons`** (roda depois da Task 11, que também mexe em `results.py`):

- Em `engine/results.py`, `_event`, apague as duas linhas `if any(not control.accepted ...): event.reasons.append("control_rejected")`.
- Em `tests/engine/test_results_build.py`, renomeie `test_screened_controls_are_published_and_a_rejection_is_a_reason` para `test_screened_controls_are_published_and_a_rejection_is_not_a_reason` e troque a última linha por `assert event.status == "published" and event.reasons == []`.
- No front, apague `NOTE_REASONS`, `rejectionReasons`, `eventNotes` e o bloco do Step 2 (o rótulo pode ficar).
- Na Task 14, o A4 de `docs/m2/trilha-a-motor.md` registra o desvio da letra do spec ("listado em `reasons`" → listado em `controls[]`) e o contrato do README perde a menção.
- Commit: `fix(engine): a rejected control is reported in controls, not as an event reason`.

---

### Task 5: paridade causal completa no sintético e golden do motor para a Gol (A4)

**Files:**
- Modify: `tests/engine/test_parity.py:24-46` (`MODEL_FREE`), `:94-107` (`test_events_and_gates_match`)
- Modify: `tests/engine/test_parity_real.py`, `tests/engine/real_data.py`
- Create: `tests/fixtures/parity/make_a4_golden.py`
- Modify: `tests/fixtures/parity/README.md`, `mise.toml`

Contexto: o A4 relaxou a paridade dos eventos para `MODEL_FREE` (só detecção e investimento), dizendo que os números do modelo causal mudaram. No sintético não mudaram: o dataset não tem Clicks/Impressions/Leads e o Trends passa na triagem em todos os eventos. Medido no Windows em 06/nov/2026 (onde a paridade não vale a 1e-9 por causa do BLAS): mesmos eventos, mesmos `passed` e `reasons`, maior diferença relativa 5e-5, todos os controles aceitos. A comparação completa volta, tirando só o que o protótipo não tem (`controls` do A4; `placebo_p_value`, `oos_wmape` e os gates do A6, já previstos aqui para a Task 9 e a 11 não precisarem tocar neste arquivo). `passed` e `selected` saem da comparação: são derivados dos `reasons` e da seleção, e o A6 os muda de propósito. A Gol tem métricas de anúncio no arquivo de performance, então lá os números mudaram mesmo: compara a detecção com o protótipo e os números com um golden **do motor** (detecta regressão, não é prova de paridade), como o Rodrigo fez.

- [ ] **Step 1: Restore the full synthetic comparison**

`tests/engine/test_parity.py`, troque as linhas 24-46:

```python
# results_data keys and gate reasons the prototype does not have: A4's control screening and A6's placebo,
# out-of-sample WMAPE and run-level demotion. `passed` and `selected` follow from the reasons and the selection.
ENGINE_KEYS = {"controls", "placebo_p_value", "oos_wmape"}
ENGINE_REASONS = {"placebo_failed", "insufficient_run"}


def prototype_view(events: list[dict]) -> list[dict]:
    """What the prototype also computed: the event, every number of its results_data and its own gate reasons."""
    return [
        {
            "event_id": e["event_id"],
            "product_group": e["product_group"],
            "intervention_date": e["intervention_date"],
            "results_data": {k: v for k, v in e["results_data"].items() if k not in ENGINE_KEYS}
            if e["results_data"]
            else None,
            "reasons": [r for r in e["reasons"] if r not in ENGINE_REASONS],
        }
        for e in events
    ]
```

Em `test_events_and_gates_match`, a última linha vira:

```python
    assert_close(prototype_view(actual), prototype_view(snapshot["events"]), "events")
```

- [ ] **Step 2: Gol: detection against the prototype, numbers against the engine's golden**

`tests/engine/real_data.py`, depois de `GOL_SNAPSHOT`:

```python
GOL_ENGINE_EVENTS = REPO_ROOT / "tests" / "fixtures" / "parity" / "real" / "gol_a4_events.json"
```

`tests/engine/test_parity_real.py`, troque o import de `real_data` e de `test_parity` e o que vem depois de `actual()`:

```python
from tests.engine.real_data import GOL_CONFIG, GOL_ENGINE_EVENTS, GOL_SNAPSHOT, engine_snapshot, gol_files
from tests.engine.test_parity import assert_close
```

```python
BLOCKS = ("period_days", "mmm", "response_curve", "points", "optimized_mix")  # events: see the two tests below
IDENTITY = ("event_id", "product_group", "intervention_date")


@pytest.mark.parametrize("block", BLOCKS)
def test_gol_block_matches_the_prototype(block, actual, legacy):
    assert_close(actual[block], legacy[block], block)


def test_gol_detected_events_match_the_prototype(actual, legacy):
    """Detection is untouched since A0; the causal numbers changed on purpose in A4 (ad metrics out of the model)."""
    assert [{k: e[k] for k in IDENTITY} for e in actual["events"]] == [
        {k: e[k] for k in IDENTITY} for e in legacy["events"]
    ]


@pytest.mark.skipif(not GOL_ENGINE_EVENTS.exists(), reason="needs mise run parity-a4-golden")
def test_gol_causal_numbers_match_the_engine_golden(actual):
    """Pinned to the engine's own output (make_a4_golden.py): catches regressions, it is not parity."""
    assert_close(actual["events"], json.loads(GOL_ENGINE_EVENTS.read_text(encoding="utf-8")), "events")
```

`tests/fixtures/parity/make_a4_golden.py`:

```python
"""Pins the engine's per-event causal numbers on the Gol (python -m tests.fixtures.parity.make_a4_golden).

Since A4 the Gol's causal numbers differ from the frozen prototype on purpose (Clicks/Impressions/Leads left the
model), and A6 adds its gates. This golden is the ENGINE's output: it catches regressions from here on, it is not
evidence of parity. The script prints how far each event moved from the prototype (real/gol.json), which is where the
A10 starts. Regenerate only with approval, after reading the deltas. Needs exemplo_csv/ and real/gol.json.
"""

import json

from threadpoolctl import threadpool_limits

from engine.config import EngineConfig
from engine.pipeline import compute
from tests.engine.real_data import GOL_CONFIG, GOL_ENGINE_EVENTS, GOL_SNAPSHOT, engine_snapshot, gol_files


def _numbers(node, prefix=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _numbers(value, f"{prefix}.{key}")
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        yield prefix, float(node)


def describe_deltas(new_events: list[dict], legacy_events: list[dict]) -> list[str]:
    legacy = {e["event_id"]: e for e in legacy_events}
    lines = []
    for event in new_events:
        old = legacy.get(event["event_id"])
        if old is None:
            lines.append(f"{event['event_id']}: not in the prototype snapshot")
            continue
        flags = [f"{k} {old[k]} -> {event[k]}" for k in ("passed", "reasons", "selected") if old[k] != event[k]]
        old_numbers = dict(_numbers(old["results_data"] or {}))
        worst = max(
            (
                abs(value - old_numbers[key]) / abs(old_numbers[key])
                for key, value in _numbers(event["results_data"] or {})
                if old_numbers.get(key)
            ),
            default=0.0,
        )
        lines.append(f"{event['event_id']}: max relative change {worst:.3g}" + (f"; {'; '.join(flags)}" if flags else ""))
    return lines


def main() -> None:
    with threadpool_limits(limits=1):
        events = engine_snapshot(compute(gol_files(), EngineConfig.from_input(GOL_CONFIG)))["events"]
    GOL_ENGINE_EVENTS.parent.mkdir(parents=True, exist_ok=True)
    GOL_ENGINE_EVENTS.write_text(json.dumps(events, indent=1), encoding="utf-8")
    print(f"wrote {GOL_ENGINE_EVENTS}")
    legacy = json.loads(GOL_SNAPSHOT.read_text(encoding="utf-8"))["events"]
    print("\n".join(describe_deltas(events, legacy)))


if __name__ == "__main__":
    main()
```

`mise.toml`, depois de `[tasks.parity-real]`:

```toml
[tasks.parity-a4-golden]
description = "Pin the engine's own causal numbers on the Gol (real/gol_a4_events.json) and print how far each event moved from the prototype. Only with approval; needs exemplo_csv/ and real/gol.json"
env = { OMP_NUM_THREADS = "1", OPENBLAS_NUM_THREADS = "1", MKL_NUM_THREADS = "1" }
run = "uv run python -m tests.fixtures.parity.make_a4_golden"
```

No fim de `tests/fixtures/parity/README.md`:

```markdown
## Causal numbers since A4

The synthetic dataset has no ad metrics and its Trends passes the control screening, so `test_parity.py` still compares
every causal number with the prototype; only what the prototype does not compute is left out (`controls`, the A6
placebo, out-of-sample WMAPE and gate reasons). On the Gol, A4 changed the numbers on purpose (Clicks/Impressions/Leads
left the model): `test_parity_real.py` compares the detected events with the prototype and the numbers with the
engine's own golden, `real/gol_a4_events.json` (git-ignored), written by `mise run parity-a4-golden`. That golden
catches regressions; it is not evidence of parity. Regenerate it only with approval, after reading the printed deltas,
and again after any change that moves a gate (A6 did).
```

- [ ] **Step 3: Run what runs here**

Run: `uv run pytest tests/engine/test_parity.py tests/engine/test_parity_real.py -v && uv run python -c "import tests.fixtures.parity.make_a4_golden"`
Expected: no Windows, tudo `skipped` e o import sem erro. No Linux: `mise run parity` PASS. **Se no Linux `test_events_and_gates_match` falhar num número do modelo**, volte o `MODEL_FREE` do `main` nesse teste, mantenha o resto da task e registre a diferença medida para a Task 14.

- [ ] **Step 4: Commit**

```bash
git add tests/engine/test_parity.py tests/engine/test_parity_real.py tests/engine/real_data.py tests/fixtures/parity/make_a4_golden.py tests/fixtures/parity/README.md mise.toml
git commit -m "test(engine): full causal parity on the synthetic and an engine golden for the gol"
```

---

### Task 6: canal colinear fica não identificável (A5)

**Files:**
- Modify: `engine/identifiability.py:8-25` (`assess`)
- Modify: `engine/pipeline.py:197-248` (`run_elasticity`, `compute`)
- Modify: `engine/results.py:247-250` (mensagem do `ValueError`)
- Test: `tests/engine/test_identifiability.py`

Contexto: `block_per_channel` passa o gate (A3) prometendo que o resultado por canal sai `identifiable=false` (A5), e o `main` nunca cumpriu (`docs/decisoes/engine.md` ~98 e ~100, comentário do `config.py`). O `assess` sai de `run_elasticity` e vai para `compute()`, onde o `ValidationReport` existe; marca os canais de `validation.collinearity.unresolved` (Task 1: já sem pares de overlap e com o VIF), com os nomes como modelados. `collinearity.pairs` não serve: é do spend cru, antes dos grupos. Sem `validation` (testes que chamam `compute` direto), nada é marcado.

- [ ] **Step 1: Write the failing tests**

Em `tests/engine/test_identifiability.py`, acrescente aos imports `import engine`, `from threadpoolctl import threadpool_limits` e `from tests.engine.synthetic_data import collinear_inputs, dataset_config`, e no fim:

```python
def test_a_collinear_channel_is_never_identifiable():
    tight = list(np.linspace(0.9, 1.1, 200))
    verdicts = assess(_mmm({"A": tight, "B": tight}, {"A": 100.0, "B": 100.0}), {"B"})

    assert verdicts["A"]["identifiable"] is True
    assert verdicts["B"]["identifiable"] is False and verdicts["B"]["reasons"] == ["collinearity"]


def test_block_per_channel_publishes_the_collinear_pair_only_in_aggregate(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "none")
    config = {**dataset_config(), "block_per_channel": True}

    with threadpool_limits(limits=1):
        result = engine.run(collinear_inputs(tmp_path / "data"), config, tmp_path / "out", lambda level, msg: None)

    assert result["validation"]["collinearity"]["unresolved"] == ["PMAX", "SEARCH"]
    channels = {c["name"]: c for c in result["elasticity"]["channels"]}
    for name in ("PMAX", "SEARCH"):
        assert channels[name]["identifiable"] is False and "collinearity" in channels[name]["reasons"]
        assert channels[name]["curve"] == [] and channels[name]["contribution_pct"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_identifiability.py -v`
Expected: FAIL — `TypeError: assess() takes 1 positional argument but 2 were given`.

- [ ] **Step 3: Implement**

`engine/identifiability.py`, `assess`:

```python
def assess(mmm: dict, collinear: set[str] = frozenset()) -> dict[str, dict]:
    """{channel: {"ci": (p2.5, p97.5), "identifiable": bool, "reasons": [...]}}, the CI in KPI units over the period.

    The Ridge is positive, so a contribution is never negative: "the CI crosses zero" is p2.5 == 0. A channel the
    collinearity gate left open (block_per_channel) is never identifiable, whatever its CI.
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
        if name in collinear:
            reasons.append("collinearity")
        verdicts[name] = {"ci": (float(lo[i]), float(hi[i])), "identifiable": not reasons, "reasons": reasons}
    return verdicts
```

`engine/pipeline.py`: em `run_elasticity`, apague as linhas 205-206 (`result["identifiability"] = ...` e `_log_contribution_split(...)`). Em `compute`:

```python
    elasticity = run_elasticity(prepared, cfg, global_dir=global_dir)
    verdicts = {}
    if elasticity["mmm"]:
        collinearity = validation.collinearity if validation else None
        verdicts = identifiability.assess(elasticity["mmm"], set(collinearity.unresolved) if collinearity else set())
        _log_contribution_split(elasticity["mmm"], verdicts)
    return Computed(
        prepared=prepared,
        effective_config=cfg,
        events=events,
        candidates=candidates,
        validation=validation,
        identifiability=verdicts,
        **elasticity,
    )
```

`engine/results.py:249`: a mensagem vira `"Computed has an MMM but no identifiability verdicts: compute() runs identifiability.assess"`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/engine/test_identifiability.py tests/engine/test_results_build.py tests/engine/test_pipeline_stages.py tests/engine/test_collinearity.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/identifiability.py engine/pipeline.py engine/results.py tests/engine/test_identifiability.py
git commit -m "feat(engine): channels left collinear under block_per_channel are not identifiable"
```

---

### Task 7: realocação fora sempre que um canal está escondido; `fold_mix` com `None` (A5)

**Files:**
- Modify: `engine/identifiability.py:32-42`
- Modify: `engine/results.py:207-218` (`_scenarios`), `:283-305` (`_elasticity`)
- Modify: `engine/outputs.py:113-115` (`_write_global`)
- Test: `tests/engine/test_identifiability.py`, `tests/engine/test_results_build.py`, `tests/engine/test_outputs_identifiability.py` (criado na Task 8)

Contexto: o ganho de realocar o mesmo orçamento depende do efeito de **cada** canal; hoje o `main` só tira o cenário quando **nenhum** canal é identificável. Passa a sair quando qualquer canal está escondido, e `metrics.reallocation_suppressed` (campo do contrato, README ~116, nunca preenchido) diz isso. O prompt do Gemini já tira a entrada de realocação quando `kpi_projections["reallocation"]` é `None` (`reports.py`, `REALLOCATION_ENTRY`), então basta a condição do `_write_global`. `metrics.low_confidence` continua `null` (fora do escopo). O `fold_mix` somava um valor ausente como 0; passa a propagar `None`.

- [ ] **Step 1: Write the failing tests**

`tests/engine/test_identifiability.py`: apague `test_fold_mix_treats_a_missing_value_as_zero` e acrescente:

```python
def test_fold_mix_is_none_when_a_hidden_value_is_missing():
    assert fold_mix({"A": 1.0, "B": None, "C": 2.0}, {"B", "C"}) == {"A": 1.0, UNIDENTIFIED: None}


def test_reallocation_is_suppressed_while_any_channel_is_hidden():
    assert identifiability.reallocation_suppressed({"A": {"identifiable": True}, "B": {"identifiable": False}})
    assert not identifiability.reallocation_suppressed({"A": {"identifiable": True}})
    assert not identifiability.reallocation_suppressed({})
```

`tests/engine/test_results_build.py`, no fim da seção de elasticidade:

```python
def test_one_hidden_channel_drops_the_reallocation_scenario_and_says_so(synthetic_computed):
    point = {"Daily_Investment": 10.0, "Projected_Total_KPIs": 5.0, "Incremental_Investment": 0, "Incremental_KPI": 0}
    plain = dataclasses.replace(_with_verdicts(synthetic_computed), strategic_reallocation_point=point)
    hidden = dataclasses.replace(
        _with_verdicts(synthetic_computed, hidden={"DISPLAY"}), strategic_reallocation_point=point
    )

    shown, suppressed = (results.build_results(c, "v").elasticity for c in (plain, hidden))

    assert "strategic_reallocation" in [s.name for s in shown.scenarios]
    assert shown.metrics.reallocation_suppressed is False
    assert "strategic_reallocation" not in [s.name for s in suppressed.scenarios]
    assert suppressed.metrics.reallocation_suppressed is True
```

`tests/engine/test_outputs_identifiability.py` (o arquivo e os helpers `_hide` e `_global_prompt` vêm da Task 8):

```python
def test_the_reallocation_is_not_offered_to_the_llm_while_a_channel_is_hidden(synthetic_computed, tmp_path):
    last = synthetic_computed.mmm["spend_cols"][-1]

    plain, plain_prompt = _global_prompt(_hide(synthetic_computed, set()), tmp_path / "plain")
    hidden, hidden_prompt = _global_prompt(_hide(synthetic_computed, {last}), tmp_path / "hidden")

    assert plain.kpi_projections["reallocation"] is not None and "Realocação Estratégica" in plain_prompt
    assert hidden.kpi_projections["reallocation"] is None and "Realocação" not in hidden_prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_identifiability.py tests/engine/test_results_build.py tests/engine/test_outputs_identifiability.py -v`
Expected: FAIL — `AttributeError: module 'engine.identifiability' has no attribute 'reallocation_suppressed'` e o `fold_mix` dando `0.0`.

- [ ] **Step 3: Implement**

`engine/identifiability.py`, depois de `none_identifiable`:

```python
def reallocation_suppressed(verdicts: dict[str, dict]) -> bool:
    """Moving the same budget between channels rests on every channel's own effect: no reallocation while any is hidden."""
    return bool(unidentified(verdicts))


def fold_mix(mix: dict[str, float | None], hidden: set[str]) -> dict[str, float | None]:
    """The mix without the hidden channels, their spend summed under UNIDENTIFIED (None when one of them is missing)."""
    if not hidden & mix.keys():
        return mix
    kept = {name: value for name, value in mix.items() if name not in hidden}
    pooled = [value for name, value in mix.items() if name in hidden]
    kept[UNIDENTIFIED] = None if any(value is None for value in pooled) else sum(pooled)
    return kept
```

`engine/results.py`, em `_scenarios`:

```python
        if not point or (
            name == "strategic_reallocation" and identifiability.reallocation_suppressed(computed.identifiability)
        ):
            continue
```

Em `_elasticity`, no `ElasticityMetrics(...)`:

```python
            reallocation_suppressed=identifiability.reallocation_suppressed(computed.identifiability),
```

`engine/outputs.py:113-115`:

```python
    reallocation = (
        None if identifiability.reallocation_suppressed(computed.identifiability) else computed.strategic_reallocation_point
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/engine/test_identifiability.py tests/engine/test_results_build.py tests/engine/test_outputs.py tests/engine/test_outputs_identifiability.py tests/engine/test_guardrails.py tests/engine/test_scenario.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/identifiability.py engine/results.py engine/outputs.py tests/engine/test_identifiability.py tests/engine/test_results_build.py tests/engine/test_outputs_identifiability.py
git commit -m "feat(engine): withhold the reallocation scenario while any channel is hidden and report it"
```

---

### Task 8: testes do A5 trazidos do Rodrigo

**Files:**
- Modify: `tests/engine/test_elasticity_analysis.py` (classe `TestBootstrapCoefficients`)
- Modify: `tests/engine/synthetic_data.py:120-126` (`make_identifiable_dataset` com `seed`)
- Create: `tests/engine/test_outputs_identifiability.py`, `tests/engine/test_identifiability_acceptance.py`

Contexto: só testes, sobre código que já existe; espera-se PASS de primeira. Se algum falhar, é bug real do A5: pare e reporte em vez de mudar o teste. O "aceite em três sementes" do branch do Rodrigo é do A6 (ruído branco, Task 12); aqui o equivalente do A5 roda o aceite `STRONG`/`NOEFFECT` em três sementes.

- [ ] **Step 1: Bootstrap mean bit-identical to the original averaging loop**

Em `TestBootstrapCoefficients`:

```python
    def test_the_mean_is_bit_identical_to_the_original_averaging_loop(self):
        rng = np.random.default_rng(1)
        X = rng.uniform(1, 10, (40, 3))
        y = X @ np.array([1.0, 0.5, 0.0]) + rng.normal(0, 1.0, 40)
        loop_rng = np.random.default_rng(5)
        coefs = np.zeros((30, 3))
        for b in range(30):
            idx = loop_rng.integers(0, 40, 40)
            coefs[b] = Ridge(alpha=1.0, positive=True, fit_intercept=False).fit(X[idx], y[idx]).coef_

        np.testing.assert_array_equal(bootstrap_coefficients(X, y, n_bootstrap=30, seed=5).mean(axis=0), coefs.mean(axis=0))
```

- [ ] **Step 2: The global prompt never names a hidden channel**

`tests/engine/test_outputs_identifiability.py`:

```python
"""A5: SATURATION_CURVE.md and the global LLM prompt speak only of the published channels."""

import dataclasses
import json

from engine import outputs
from tests.fakes.llm import GLOBAL_NARRATIVE, FakeLLM


def _hide(computed, hidden: set[str]):
    verdicts = {
        name: {
            "ci": (1.0, 2.0),
            "identifiable": name not in hidden,
            "reasons": ["coef_ci_includes_zero"] if name in hidden else [],
        }
        for name in computed.mmm["spend_cols"]
    }
    return dataclasses.replace(computed, identifiability=verdicts)


def _global_prompt(computed, out_dir):
    written = outputs.write_legacy_outputs(computed, out_dir)
    llm = FakeLLM([json.dumps(GLOBAL_NARRATIVE)])
    outputs.generate_reports(computed, dataclasses.replace(written, event_dirs={}), llm)  # only the global narrative
    assert len(llm.calls) == 1
    return written, llm.calls[0]


def test_the_saturation_markdown_and_the_global_prompt_never_name_a_hidden_channel(synthetic_computed, tmp_path):
    spend_cols = list(synthetic_computed.mmm["spend_cols"])

    written, prompt = _global_prompt(_hide(synthetic_computed, set(spend_cols[1:])), tmp_path)

    markdown = (written.global_dir / "SATURATION_CURVE.md").read_text(encoding="utf-8")
    assert spend_cols[0] in markdown
    for name in spend_cols[1:]:
        assert name not in markdown and name not in prompt
```

- [ ] **Step 3: STRONG/NOEFFECT acceptance over three seeds**

`tests/engine/synthetic_data.py`, a assinatura e a primeira linha de `make_identifiable_dataset`:

```python
def make_identifiable_dataset(out_dir: Path, n_days: int = 364, seed: int = 7) -> dict[str, Path | None]:
    """Two channels with widely varying spend: STRONG drives the KPI, NOEFFECT does not (A5 acceptance).

    Not "NULL" as a name: pandas reads it as a missing value.
    """
    rng = np.random.default_rng(seed)
```

`tests/engine/test_identifiability_acceptance.py`:

```python
"""A5 acceptance on more than one draw: the rule must not hold only for the seed it was written against."""

import pytest
from threadpoolctl import threadpool_limits

from engine.config import EngineConfig
from engine.pipeline import compute
from tests.engine.synthetic_data import identifiable_config, make_identifiable_dataset


@pytest.mark.parametrize("seed", [7, 11, 23])
def test_a_strong_channel_is_identifiable_and_a_no_effect_one_is_not(tmp_path, seed):
    inputs = make_identifiable_dataset(tmp_path, seed=seed)

    with threadpool_limits(limits=1):
        verdicts = compute(inputs, EngineConfig.from_input(identifiable_config())).identifiability

    assert verdicts["STRONG"]["identifiable"] is True
    assert verdicts["NOEFFECT"]["identifiable"] is False
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/engine/test_elasticity_analysis.py tests/engine/test_outputs_identifiability.py tests/engine/test_identifiability_acceptance.py tests/engine/test_identifiability.py -v`
Expected: PASS. Uma semente que falhe é achado para a A10: anote qual e o veredito, não troque a semente.

- [ ] **Step 5: Commit**

```bash
git add tests/engine/test_elasticity_analysis.py tests/engine/synthetic_data.py tests/engine/test_outputs_identifiability.py tests/engine/test_identifiability_acceptance.py
git commit -m "test(engine): a5 guards from the parallel branch: bootstrap loop, prompt and three seeds"
```

---

### Task 9: placebo e WMAPE fora da amostra por evento (A6)

**Files:**
- Modify: `engine/analysis.py` (helpers novos antes de `run_causal_impact_analysis`; dentro dela, o ajuste, o p-valor e o `results_dict`)
- Create: `tests/engine/test_placebo.py`

Contexto: o placebo é uma intervenção falsa no meio do pré-período, com o mesmo modelo (mesmas features, `UnobservedComponents` igual) e o mesmo teste do evento (impacto acumulado contra o erro-padrão acumulado da previsão). O WMAPE segura os 20% finais do pré. Os dois entram no `results_data` (`placebo_p_value`, `oos_wmape`); o gate fica para a Task 11. Sem `try/except` nos helpers: exceção sobe e o evento vira `analysis_failed` (o `except` de `run_causal_impact_analysis` já existe). O ajuste e os números do evento real não mudam: o p-valor só vai para uma função comum.

- [ ] **Step 1: Write the failing tests**

`tests/engine/test_placebo.py`:

```python
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm
from scipy import stats

from engine.analysis import cumulative_p_value, oos_wmape, placebo_p_value
from tests.engine.test_controls import _event


def _pre(n=120, seed=0, step_at=None, step=0.0, noise=1.0):
    """kpi = level + weekly seasonality + noise (+ an optional step); one exogenous column."""
    rng = np.random.default_rng(seed)
    kpi = 100 + 5 * np.sin(2 * np.pi * np.arange(n) / 7) + rng.normal(0, noise, n)
    if step_at is not None:
        kpi[step_at:] += step
    return pd.DataFrame({"kpi": kpi, "x": rng.normal(0, 1, n)}, index=pd.date_range("2024-01-01", periods=n, freq="D"))


def test_cumulative_p_value_tests_the_lift_against_the_accumulated_forecast_error():
    p, cum_se = cumulative_p_value(10.0, SimpleNamespace(se_mean=np.array([3.0, 4.0])))

    assert cum_se == 5.0 and p == pytest.approx(2 * stats.norm.sf(2.0))
    assert cumulative_p_value(10.0, SimpleNamespace(se_mean=np.array([]))) == (1.0, 0.0)


def test_the_placebo_rejects_a_step_in_the_pre_period():
    assert placebo_p_value(_pre(step_at=60, step=40.0), ["x"], 14, 8) < 0.05


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_the_placebo_finds_nothing_in_a_clean_pre_period(seed):
    assert placebo_p_value(_pre(seed=seed), ["x"], 14, 8) > 0.01


def test_the_placebo_does_not_run_on_a_short_pre_period():
    assert placebo_p_value(_pre(n=14), ["x"], 7, 8) is None  # half (7) < min_pre_periods (8)
    assert placebo_p_value(_pre(n=40), ["x"], 25, 8) is None  # window 25 > second half 20


def test_oos_wmape_is_small_for_a_predictable_series_and_none_when_it_cannot_be_computed():
    assert oos_wmape(_pre(noise=0.1), ["x"], 8) < 0.05
    assert oos_wmape(_pre(n=20), ["x"], 8) is None  # holdout of 4 rows < 7
    zeros = _pre()
    zeros["kpi"] = 0.0
    assert oos_wmape(zeros, ["x"], 8) is None  # nothing to weigh the error by


def test_a_fit_that_raises_is_not_swallowed(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("fit failed")

    monkeypatch.setattr(sm.tsa, "UnobservedComponents", boom)
    with pytest.raises(RuntimeError):
        placebo_p_value(_pre(), ["x"], 14, 8)
    with pytest.raises(RuntimeError):
        oos_wmape(_pre(), ["x"], 8)


def test_the_event_reports_its_placebo_and_out_of_sample_wmape():
    results = _event(lambda spend, rng: 50 + rng.normal(0, 5, len(spend)))

    assert 0 <= results["placebo_p_value"] <= 1
    assert results["oos_wmape"] is not None and results["oos_wmape"] >= 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_placebo.py -v`
Expected: FAIL — `ImportError: cannot import name 'cumulative_p_value'`.

- [ ] **Step 3: Implement**

`engine/analysis.py`, depois de `lasso_folds`:

```python
HOLDOUT_FRACTION = 0.2  # the last 20% of the pre-period, out of the fit (A6)
MIN_HOLDOUT_ROWS = 7


def cumulative_p_value(abs_lift: float, forecast) -> tuple[float, float]:
    """(p-value, cumulative standard error) of a cumulative impact against the forecast's own uncertainty.

    Shared by the event and its placebo, so both are judged by the same rule. Without a usable standard error the
    effect cannot be told from noise: p is 1 and the error 0.
    """
    se = np.asarray(forecast.se_mean, dtype=float)
    se = se[np.isfinite(se)]
    cum_se = float(np.sqrt(np.sum(se**2))) if se.size else 0.0
    if cum_se > 0:
        return float(2 * stats.norm.sf(abs(abs_lift / cum_se))), cum_se
    return 1.0, 0.0


def _fit_state_space(data: pd.DataFrame, features: list[str]):
    return sm.tsa.UnobservedComponents(
        data["kpi"], "llevel", trend=True, seasonal=7, exog=data[features] if features else None
    ).fit(disp=False)


def placebo_p_value(pre: pd.DataFrame, features: list[str], post_len: int, min_pre_periods: int) -> float | None:
    """p-value of a fake intervention halfway through the pre-period; None when the pre-period is too short for it.

    The event's model fitted on the first half and read over the next `post_len` rows: a sound counterfactual finds
    nothing there. The features were chosen on the whole pre-period, a slight leak (for the A10). A fit that raises is
    not caught here: the event fails as analysis_failed instead of passing a placebo that never ran.
    """
    half = len(pre) // 2
    if half < min_pre_periods or len(pre) - half < post_len:
        return None
    fit_part, window = pre.iloc[:half], pre.iloc[half : half + post_len]
    forecast = _fit_state_space(fit_part, features).get_forecast(steps=len(window), exog=window[features])
    impact = float((window["kpi"].to_numpy() - np.asarray(forecast.predicted_mean)).sum())
    return cumulative_p_value(impact, forecast)[0]


def oos_wmape(pre: pd.DataFrame, features: list[str], min_pre_periods: int) -> float | None:
    """Σ|y − ŷ| / Σ|y| of the event's model on the last HOLDOUT_FRACTION of the pre-period, left out of the fit."""
    held = int(round(len(pre) * HOLDOUT_FRACTION))
    train = len(pre) - held
    if train < min_pre_periods or held < MIN_HOLDOUT_ROWS:
        return None
    fit_part, holdout = pre.iloc[:train], pre.iloc[train:]
    forecast = _fit_state_space(fit_part, features).get_forecast(steps=held, exog=holdout[features])
    actual = holdout["kpi"].to_numpy()
    total = float(np.abs(actual).sum())
    return float(np.abs(actual - np.asarray(forecast.predicted_mean)).sum() / total) if total else None
```

Dentro de `run_causal_impact_analysis`, o ajuste do evento (o bloco `model = sm.tsa.UnobservedComponents(...)`) vira:

```python
        model = _fit_state_space(pre_data_for_model, selected_features)
```

e, logo depois do `log.info(f"   - Causal model R-squared (in-sample): ...")`:

```python
        placebo_p = placebo_p_value(pre_data_for_model, selected_features, len(post_data), min_pre_periods)
        if placebo_p is None:
            log.warning("   - Placebo não rodou: o pré-período é curto demais para a intervenção falsa.")
        wmape = oos_wmape(pre_data_for_model, selected_features, min_pre_periods)
```

O bloco do p-valor (de `se = np.asarray(forecast.se_mean, dtype=float)` até `impact_ci_lower = impact_ci_upper = abs_lift`) vira:

```python
        p_value, cum_se = cumulative_p_value(abs_lift, forecast)
        impact_ci_lower = abs_lift - 1.96 * cum_se
        impact_ci_upper = abs_lift + 1.96 * cum_se
```

(com `cum_se` 0 os dois limites são `abs_lift`, como antes; mantenha o comentário longo sobre a incerteza acumulada acima dessas linhas). No `results_dict`, depois de `"controls": controls,`:

```python
            "placebo_p_value": placebo_p,  # None: the pre-period is too short for a placebo
            "oos_wmape": wmape,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/engine/test_placebo.py tests/engine/test_controls.py tests/engine/test_analysis.py tests/engine/test_pipeline_stages.py -v`
Expected: PASS (o gate ainda não existe; nenhum evento muda de status).

- [ ] **Step 5: Commit**

```bash
git add engine/analysis.py tests/engine/test_placebo.py
git commit -m "feat(engine): placebo p-value and out-of-sample wmape per causal event (a6)"
```

---

### Task 10: CV fora da amostra registrado e `engine/sufficiency.py` (A6)

**Files:**
- Modify: `engine/elasticity_analysis.py:174-198` (`walk_forward_cv_score`), `:484-498` (dict do `run_mmm_engine`)
- Create: `engine/sufficiency.py`
- Create: `tests/engine/test_sufficiency.py`

Contexto: o CV walk-forward da elasticidade cai para in-sample com menos de 40 linhas sem avisar; passa a registrar `mmm["cv_out_of_sample"]` (a matemática não muda). `sufficiency.assess` é pura: recebe os eventos que passaram em todos os gates do evento (antes do corte `max_events_to_analyze`) e devolve a `Sufficiency`, sem mexer em nada. Variação de spend = desvio-padrão (ddof 0) sobre a média do spend por período nativo, no intervalo todo, de cada canal com evento validado.

- [ ] **Step 1: Write the failing tests**

`tests/engine/test_sufficiency.py`:

```python
import numpy as np
import pandas as pd
import pytest

from engine import pipeline
from engine.config import EngineConfig
from engine.elasticity_analysis import cv_folds
from engine.sufficiency import assess, spend_cv
from tests.engine.synthetic_data import dataset_config, make_dataset

DATES = pd.date_range("2024-01-01", periods=100, freq="D")
INVESTMENT = pd.concat(
    [
        pd.DataFrame({"Date": DATES, "Product Group": "A", "investment": np.tile([50.0, 150.0], 50)}),  # CV 0.5
        pd.DataFrame({"Date": DATES, "Product Group": "B", "investment": 100.0}),  # CV 0
    ]
)


def _assess(validated, cv_out_of_sample=True, spend_cv_min=0.10, oos_wmape_max=0.30):
    return assess(validated, INVESTMENT, cv_out_of_sample, spend_cv_min, oos_wmape_max)


def test_spend_cv_is_std_over_mean_and_zero_without_spend():
    cv = spend_cv(INVESTMENT, ["A", "B", "Z"])

    assert cv["A"] == pytest.approx(0.5) and cv["B"] == 0.0 and cv["Z"] == 0.0


def test_a_validated_event_on_a_varied_channel_passes():
    verdict = _assess([{"channels": ["A"], "oos_wmape": 0.1}])

    assert verdict.passed and verdict.reasons == []
    assert verdict.validated_events == 1 and verdict.spend_variation == {"A": pytest.approx(0.5)}
    assert verdict.pre_wmape == 0.1 and verdict.cv_out_of_sample is True


def test_each_reason_on_its_own():
    assert _assess([]).reasons == ["no_validated_event"]
    assert _assess([{"channels": ["B"], "oos_wmape": 0.1}]).reasons == ["low_spend_variation"]
    assert _assess([{"channels": ["A"], "oos_wmape": 0.5}]).reasons == ["high_oos_wmape"]
    assert _assess([{"channels": ["A"], "oos_wmape": 0.1}], cv_out_of_sample=False).reasons == ["cv_in_sample"]


def test_the_run_wmape_is_the_median_of_the_validated_events():
    events = [{"channels": ["A"], "oos_wmape": w} for w in (0.1, 0.5, 0.2, None)]

    assert _assess(events).pre_wmape == 0.2


def test_without_a_computable_wmape_that_check_does_not_fail():
    verdict = _assess([{"channels": ["A"], "oos_wmape": None}])

    assert verdict.passed and verdict.pre_wmape is None


def test_the_thresholds_are_arguments():
    assert _assess([{"channels": ["A"], "oos_wmape": 0.5}], oos_wmape_max=0.6).passed
    assert _assess([{"channels": ["A"], "oos_wmape": 0.1}], spend_cv_min=0.6).reasons == ["low_spend_variation"]


def test_without_a_model_the_cv_is_not_judged():
    assert _assess([{"channels": ["A"], "oos_wmape": 0.1}], cv_out_of_sample=None).passed


def test_the_cv_is_out_of_sample_from_forty_rows():
    assert (cv_folds(39), cv_folds(40), cv_folds(728)) == (1, 2, 3)


def test_the_mmm_records_whether_its_cv_was_out_of_sample(synthetic_computed, tmp_path):
    assert synthetic_computed.mmm["cv_out_of_sample"] is True
    config = EngineConfig.from_input(dataset_config())
    prepared = pipeline.load_inputs(make_dataset(tmp_path, n_days=35), config)

    mmm = pipeline.run_elasticity(prepared, {**config.to_legacy_dict(), "period_days": prepared.period_days})["mmm"]

    assert mmm["cv_out_of_sample"] is False and np.isfinite(mmm["cv_r_squared"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_sufficiency.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.sufficiency'`.

- [ ] **Step 3: Implement**

`engine/elasticity_analysis.py`, antes de `walk_forward_cv_score`:

```python
CV_SPLITS = 3


def cv_folds(n_rows: int, n_splits: int = CV_SPLITS) -> int:
    """Folds walk_forward_cv_score uses: one per 20 rows, at most n_splits. Under 2 it scores in-sample (A6 says so)."""
    return min(n_splits, max(1, n_rows // 20))
```

Em `walk_forward_cv_score`: a assinatura vira `def walk_forward_cv_score(transformed_df, kpi_lift, n_splits=CV_SPLITS):` e `usable_splits = min(n_splits, max(1, n // 20))` vira `usable_splits = cv_folds(n, n_splits)`. No dict que `run_mmm_engine` devolve, depois de `"cv_r_squared": cv_r2,`:

```python
        "cv_out_of_sample": cv_folds(len(y_lift)) >= 2,  # False: the CV above fell back to in-sample (A6)
```

`engine/sufficiency.py`:

```python
"""Run-level sufficiency (A6): do the data support publishing a lift at all? Pure over what compute() already has."""

import statistics

import pandas as pd

from engine.results_schema import Sufficiency

# the reasons that are about the causal analysis: they demote the run's events (pipeline.judge_sufficiency)
CAUSAL_REASONS = frozenset({"no_validated_event", "low_spend_variation", "high_oos_wmape"})


def spend_cv(investment_df: pd.DataFrame, channels: list[str]) -> dict[str, float]:
    """std/mean of each channel's spend per period over the whole range; 0 for a channel that never spent."""
    pivot = investment_df.pivot_table(index="Date", columns="Product Group", values="investment").fillna(0)
    out = {}
    for name in channels:
        series = pivot[name] if name in pivot.columns else pd.Series(dtype=float)
        mean = float(series.mean()) if len(series) else 0.0
        out[name] = float(series.std(ddof=0)) / mean if mean > 0 else 0.0
    return out


def assess(
    validated: list[dict],
    investment_df: pd.DataFrame,
    cv_out_of_sample: bool | None,
    spend_cv_min: float,
    oos_wmape_max: float,
) -> Sufficiency:
    """`validated`: {"channels", "oos_wmape"} of each event that passed every event gate. A WMAPE that could not be
    computed for any event, or a run without a model (cv_out_of_sample None), does not fail its check."""
    channels = list(dict.fromkeys(c for event in validated for c in event["channels"]))
    variation = spend_cv(investment_df, channels)
    wmapes = [event["oos_wmape"] for event in validated if event["oos_wmape"] is not None]
    pre_wmape = statistics.median(wmapes) if wmapes else None
    reasons = []
    if not validated:
        reasons.append("no_validated_event")
    if any(cv < spend_cv_min for cv in variation.values()):
        reasons.append("low_spend_variation")
    if pre_wmape is not None and pre_wmape > oos_wmape_max:
        reasons.append("high_oos_wmape")
    if cv_out_of_sample is False:
        reasons.append("cv_in_sample")
    return Sufficiency(
        passed=not reasons,
        spend_variation=variation,
        validated_events=len(validated),
        pre_wmape=pre_wmape,
        reasons=reasons,
        cv_out_of_sample=cv_out_of_sample,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/engine/test_sufficiency.py tests/engine/test_elasticity_analysis.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add engine/elasticity_analysis.py engine/sufficiency.py tests/engine/test_sufficiency.py
git commit -m "feat(engine): record an in-sample elasticity cv and judge run sufficiency (a6)"
```

---

### Task 11: gates do A6 no pipeline e no `results.json`

**Files:**
- Modify: `engine/pipeline.py` (imports, `EventOutcome`, `Computed`, `_gate_reasons`, `judge_sufficiency` novo, `compute`)
- Modify: `engine/results.py` (imports, `_event`, `_causal`, `_elasticity`, `build_results`)
- Test: `tests/engine/test_pipeline_stages.py`, `tests/engine/test_results_build.py`
- Modify (ajustes): `tests/engine/test_results_build.py:343-348`, `tests/engine/test_results_run.py:56-75`, `tests/engine/test_run.py:60-66`

Contexto: um lugar por decisão. O gate do evento (inclusive `placebo_failed`) fica só em `_gate_reasons`; o `Placebo.passed` publicado é lido dos `reasons`, não recalculado. O julgamento do run fica em `judge_sufficiency`, que devolve **novos** `EventOutcome` (`dataclasses.replace`) para os rebaixados a `insufficient_run`; os analisados não mudam. Evento `insufficient_run` sai sem lift, p-valor, investimento incremental, CPA e séries. Motivos causais da suficiência vão para `causal.reasons` (`no_validated_event` não, porque `no_event_passed_gates` já diz isso); `cv_in_sample` deixa a elasticidade `inconclusive`. `run_status` não muda: cada motivo cai numa seção, e seção `inconclusive` já tira o `succeeded`.

- [ ] **Step 1: Write the failing tests**

`tests/engine/test_pipeline_stages.py`, no fim:

```python
GATES = {
    "require_statistical_significance": True,
    "p_value_threshold": 0.05,
    "require_logical_direction": True,
    "require_model_fit": False,
    "r_squared_threshold": 0.3,
}
SIGNIFICANT = {"p_value": 0.01, "investment_change_pct": 50.0, "absolute_lift": 10.0, "model_r_squared": 0.5}


def test_a_failed_placebo_is_a_gate_reason_and_a_skipped_one_is_not():
    assert pipeline._gate_reasons({**SIGNIFICANT, "placebo_p_value": 0.01}, GATES) == ["placebo_failed"]
    assert pipeline._gate_reasons({**SIGNIFICANT, "placebo_p_value": 0.5}, GATES) == []
    assert pipeline._gate_reasons({**SIGNIFICANT, "placebo_p_value": None}, GATES) == []


def _passing(event_id, group="YOUTUBE"):
    return pipeline.EventOutcome(event_id, group, "2024-10-28", {"oos_wmape": 0.1}, passed=True, selected=True)


def test_an_insufficient_run_demotes_the_passing_events_as_new_outcomes(synthetic_prepared):
    good = _passing("e1")
    bad = pipeline.EventOutcome("e2", "YOUTUBE", "2024-10-28", {"oos_wmape": 0.1}, reasons=["not_significant"])
    limits = {"spend_cv_min": 0.99, "oos_wmape_max": 0.3}  # YOUTUBE varies ~0.3 on the short synthetic

    events, verdict = pipeline.judge_sufficiency(synthetic_prepared, [good, bad], {"cv_out_of_sample": True}, limits)

    assert verdict.passed is False and verdict.reasons == ["low_spend_variation"]
    assert events[0].reasons == ["insufficient_run"] and not events[0].passed and not events[0].selected
    assert events[1] is bad
    assert good.passed and good.selected and good.reasons == []  # the analysed outcome is untouched


def test_an_in_sample_cv_fails_the_run_but_keeps_the_events(synthetic_prepared):
    good = _passing("e1")
    limits = {"spend_cv_min": 0.1, "oos_wmape_max": 0.3}

    events, verdict = pipeline.judge_sufficiency(synthetic_prepared, [good], {"cv_out_of_sample": False}, limits)

    assert verdict.reasons == ["cv_in_sample"] and events == [good]


def test_compute_judges_the_sufficiency(synthetic_computed):
    verdict = synthetic_computed.sufficiency
    assert verdict is not None and verdict.validated_events == sum(e.passed for e in synthetic_computed.events)
```

`tests/engine/test_results_build.py`: o import do meio do arquivo (linha ~197) vira `from engine.results_schema import Causal, Elasticity, ResultsV1, Sufficiency` (as funções resolvem o nome na chamada) e, no fim da seção causal (antes do comentário `# --- elasticity, baseline and status ---`):

```python
def _sufficiency(*reasons):
    return Sufficiency(passed=not reasons, validated_events=1, reasons=list(reasons))


def test_an_insufficient_run_publishes_its_events_without_their_numbers(synthetic_computed):
    data = _result_data(oos_wmape=0.4, placebo_p_value=0.5)
    demoted = outcome(passed=False, selected=False, reasons=["insufficient_run"], data=data)
    computed = dataclasses.replace(with_events(synthetic_computed, [demoted]), sufficiency=_sufficiency("high_oos_wmape"))

    causal = results._causal(computed)

    event = causal.events[0]
    assert event.status == "rejected" and event.reasons == ["insufficient_run"]
    assert event.lift is None and event.p_value is None and event.cpa_incremental is None and event.series is None
    assert event.fit.wmape == 0.4 and event.placebo.passed is True and event.investment_change_pct == 80.0
    assert causal.status == "inconclusive" and causal.reasons == ["high_oos_wmape", "no_event_passed_gates"]


def test_the_placebo_is_published_from_the_gate(synthetic_computed):
    failed = outcome(passed=False, selected=False, reasons=["placebo_failed"], data=_result_data(placebo_p_value=0.01))
    skipped = outcome("YOUTUBE_2024-06-10", data=_result_data(placebo_p_value=None))

    events = results._causal(with_events(synthetic_computed, [failed, skipped])).events

    assert (events[0].placebo.p_value, events[0].placebo.passed) == (0.01, False)
    assert (events[1].placebo.p_value, events[1].placebo.passed) == (None, None)


def test_an_in_sample_cv_makes_the_elasticity_inconclusive(synthetic_computed):
    computed = dataclasses.replace(_with_verdicts(synthetic_computed), sufficiency=_sufficiency("cv_in_sample"))

    built = results.build_results(computed, "v")

    assert built.elasticity.status == "inconclusive" and built.elasticity.reasons == ["cv_in_sample"]
    assert built.elasticity.response_curve and built.sufficiency.reasons == ["cv_in_sample"]
    assert built.status == "inconclusive"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_pipeline_stages.py tests/engine/test_results_build.py -v`
Expected: FAIL — `AttributeError: module 'engine.pipeline' has no attribute 'judge_sufficiency'` e `placebo_failed` ausente dos `reasons`.

- [ ] **Step 3: Implement the pipeline**

`engine/pipeline.py`: `from dataclasses import dataclass, field, replace`; `from engine import analysis, elasticity_analysis, identifiability, outputs, results, sufficiency`; `from engine.results_schema import Sufficiency, ValidationReport`.

`EventOutcome.reasons`, o comentário vira `# not_significant, illogical_direction, poor_fit, placebo_failed, analysis_failed; insufficient_run (A6, judge_sufficiency)`.

Em `Computed`, depois de `identifiability`:

```python
    sufficiency: Sufficiency | None = None  # A6: do the data support publishing a lift (set by compute)
```

No fim de `_gate_reasons`, antes do `return`:

```python
    placebo = results.get("placebo_p_value")
    if placebo is not None and placebo < cfg["p_value_threshold"]:
        reasons.append("placebo_failed")  # the model finds an "effect" where nothing happened
```

Depois de `_log_contribution_split`:

```python
def judge_sufficiency(
    prepared: PreparedData, events: list[EventOutcome], mmm: dict | None, cfg: dict
) -> tuple[list[EventOutcome], Sufficiency]:
    """The run-level verdict (A6). A causal reason demotes every passing event to insufficient_run, as new outcomes:
    the analysed ones stay as they were."""
    validated = [
        {"channels": [c for c in e.product_group.split(", ") if c], "oos_wmape": e.results_data.get("oos_wmape")}
        for e in events
        if e.passed
    ]
    cv_out_of_sample = mmm["cv_out_of_sample"] if mmm else None
    verdict = sufficiency.assess(
        validated, prepared.investment_df, cv_out_of_sample, cfg["spend_cv_min"], cfg["oos_wmape_max"]
    )
    if verdict.passed:
        log.info(f"Dados suficientes: {verdict.validated_events} evento(s) validado(s).")
        return events, verdict
    log.warning("Dados insuficientes para publicar o resultado: " + ", ".join(verdict.reasons))
    if not sufficiency.CAUSAL_REASONS & set(verdict.reasons):
        return events, verdict
    demoted = [
        replace(e, passed=False, selected=False, reasons=[*e.reasons, "insufficient_run"]) if e.passed else e
        for e in events
    ]
    return demoted, verdict
```

Em `compute`, logo depois de `elasticity = run_elasticity(...)`:

```python
    events, verdict = judge_sufficiency(prepared, events, elasticity["mmm"], cfg)
```

e no `Computed(...)`, `sufficiency=verdict,`.

- [ ] **Step 4: Implement the document**

`engine/results.py`: acrescente `Placebo` ao import de `engine.results_schema` e `from engine.sufficiency import CAUSAL_REASONS`.

`_event` inteiro:

```python
def _event(outcome: "EventOutcome") -> CausalEvent:
    published = outcome.passed and outcome.selected
    reasons = list(outcome.reasons) + (["not_selected"] if outcome.passed and not outcome.selected else [])
    event = CausalEvent(
        id=outcome.event_id,
        channels=_channels(outcome.product_group),
        status="published" if published else "rejected",
        reasons=reasons,
        selected=outcome.selected,
    )
    data = outcome.results_data
    if not data:
        return event
    event.start, event.end = data["start_date"], data["end_date"]
    event.investment_change_pct = _num(data["investment_change_pct"])
    event.fit = Fit(
        r2=_num(data["model_r_squared"]), mae=_num(data["mae"]), mape=_num(data["mape"]), wmape=_num(data.get("oos_wmape"))
    )
    if "placebo_p_value" in data:  # None: the pre-period was too short to run it
        p = data["placebo_p_value"]
        event.placebo = Placebo(p_value=_num(p), passed=None if p is None else "placebo_failed" not in outcome.reasons)
    event.controls = [CausalControl(**control) for control in data.get("controls", [])]
    if any(not control.accepted for control in event.controls):
        event.reasons.append("control_rejected")  # the control left the model; the event still stands
    if "insufficient_run" in outcome.reasons:
        return event  # the run's data do not support a lift: its numbers stay out of the document
    lift = data["absolute_lift"]
    event.lift = Lift(
        abs=_num(lift),
        ci=(_num(data["absolute_lift_ci_lower"]), _num(data["absolute_lift_ci_upper"])),
        rel_pct=_num(data["relative_lift_pct"]),
    )
    event.p_value = _num(data["p_value"])
    event.incremental_investment = _num(data["total_investment_post_period"])
    event.cpa_incremental = None if lift == 0 else _num(data["cpa_incremental"])  # 0 was the "no lift" sentinel
    event.series = _series(outcome)
    return event
```

Em `_causal`, antes do `return`:

```python
    if status != "ok" and computed.sufficiency:
        # why the data fall short comes first; no_validated_event says what the reason below already says
        causes = CAUSAL_REASONS - {"no_validated_event"}
        reasons = [r for r in computed.sufficiency.reasons if r in causes] + reasons
```

Em `_elasticity`, troque as linhas do `none_identifiable` e do `status`/`reasons`:

```python
    none_identifiable = identifiability.none_identifiable(computed.identifiability)
    reasons = ["no_identifiable_channel"] if none_identifiable else []
    if computed.sufficiency and "cv_in_sample" in computed.sufficiency.reasons:
        reasons.append("cv_in_sample")  # under 40 rows the CV scored in-sample: the fit is not validated (A6)
    rows = _response_rows(computed)
    return Elasticity(
        status="inconclusive" if reasons else "ok",
        reasons=reasons,
```

Em `build_results`, `sufficiency=computed.sufficiency,` no `ResultsV1(...)`.

- [ ] **Step 5: Run the new tests**

Run: `uv run pytest tests/engine/test_pipeline_stages.py tests/engine/test_results_build.py -v`
Expected: os testes novos PASS; `test_build_results_validates_and_leaves_the_future_sections_null` FAIL (a suficiência deixou de ser `None`), e talvez `test_selected_is_capped_by_max_events_to_analyze` (ver Step 6).

- [ ] **Step 6: Adjust the tests the gate moves**

- `tests/engine/test_results_build.py`, em `test_build_results_validates_and_leaves_the_future_sections_null`: `assert built.validation is built.experiment_design is built.reports is None and built.sufficiency is not None`.
- `tests/engine/test_results_run.py`, em `test_run_result_validates_against_the_schema`: `assert results.experiment_design is results.reports is None and results.sufficiency is not None`. Em `test_numbers_in_results_match_compute`, a condição vira `if outcome.results_data and event["lift"]:` (evento `insufficient_run` não tem lift).
- `tests/engine/test_run.py`, em `test_run_returns_the_contract_dict`: o laço vira `for section in ("experiment_design", "reports"):` com o comentário `# owned by A7-A9`, mais `assert r["sufficiency"] is not None`.

Rode `uv run pytest tests/engine -q` e trate o que depender de **quantos** eventos passam (o placebo rejeita alguns no ano sintético; o Rodrigo mediu que sobra um):

- Se `test_selected_is_capped_by_max_events_to_analyze` cair em `len(passed) >= 2`: em `tests/engine/test_pipeline_stages.py`, `_prepared` ganha `n_days: int = SHORT` (`files = make_dataset(tmp_path, n_days=n_days, **dataset)`) e esse teste chama `_prepared(tmp_path, config={"max_events_to_analyze": 1}, n_days=728)`.
- Se o `ran` de `tests/engine/test_run.py` ou de `tests/engine/test_results_run.py` ficar com `causal.status == "inconclusive"`: troque `make_dataset(work / "data", n_days=SHORT)` por `make_dataset(work / "data")` nesse fixture (dois anos, como o Rodrigo fez).

Qualquer outra falha: pare e reporte; não afrouxe limiar.

- [ ] **Step 7: Run the engine suite**

Run: `uv run pytest tests/engine tests/llm -q`
Expected: PASS (a paridade é pulada fora do Linux).

- [ ] **Step 8: Commit**

```bash
git add engine/pipeline.py engine/results.py tests/engine/test_pipeline_stages.py tests/engine/test_results_build.py tests/engine/test_results_run.py tests/engine/test_run.py
git commit -m "feat(engine): placebo gate, run sufficiency and insufficient_run events in results.json (a6)"
```

---

### Task 12: aceite do A6 (ruído branco, placebo injetado, efeito real)

**Files:**
- Create: `tests/engine/test_placebo_acceptance.py`

Contexto: o aceite do spec. Cinco runs completos (dois anos, BLAS em 1 thread), ~4–5 min. O ruído branco é medição: o Rodrigo mediu que só o placebo deixa 6 de 10 sementes publicando (decisão 3).

- [ ] **Step 1: Write the acceptance tests**

```python
"""A6 acceptance (docs/m2/trilha-a-motor.md): white noise publishes nothing; a placebo with an effect fails."""

import numpy as np
import pandas as pd
import pytest
from threadpoolctl import threadpool_limits

import engine
from tests.engine.synthetic_data import DAYS, START, dataset_config, make_dataset

NOISE_SEEDS = (1, 2, 3)
YOUTUBE_EVENT = "synthetic_YOUTUBE_2024-10-28"  # pre-period of 300 days: its placebo reads days 150-163


def _run(work, config, inputs):
    with threadpool_limits(limits=1):
        return engine.run(inputs, config, work / "out", lambda level, message: None)


def _module_run(tmp_path_factory, name, config, build):
    mp = pytest.MonkeyPatch()
    mp.setenv("LLM_PROVIDER", "none")
    work = tmp_path_factory.mktemp(name)
    try:
        return _run(work, config, build(work / "data"))
    finally:
        mp.undo()


def make_noise_dataset(out_dir, seed):
    """The default dataset's spend (spikes included) with a KPI of pure noise: no channel moves it."""
    paths = make_dataset(out_dir)
    kpi = 5000.0 * np.random.default_rng(seed).lognormal(0.0, 0.03, DAYS)
    frame = pd.DataFrame({"date": pd.date_range(START, periods=DAYS, freq="D"), "Sessions": kpi})
    frame.to_csv(paths["performance_file"], index=False, date_format="%Y-%m-%d")
    return paths


def with_a_pulse_in_the_pre_period(out_dir):
    paths = make_dataset(out_dir)
    kpi = pd.read_csv(paths["performance_file"])
    kpi.loc[150:163, "Sessions"] *= 1.5
    kpi.to_csv(paths["performance_file"], index=False)
    return paths


@pytest.fixture(scope="module", params=NOISE_SEEDS)
def noise_run(request, tmp_path_factory):
    config = {**dataset_config(), "p_value_threshold": 0.05}  # the engine's default threshold
    return _module_run(tmp_path_factory, f"noise{request.param}", config, lambda d: make_noise_dataset(d, request.param))


@pytest.fixture(scope="module")
def injected_run(tmp_path_factory):
    return _module_run(tmp_path_factory, "injected", dataset_config(), with_a_pulse_in_the_pre_period)


@pytest.fixture(scope="module")
def clean_run(tmp_path_factory):
    return _module_run(tmp_path_factory, "clean", dataset_config(), make_dataset)


def test_white_noise_publishes_no_event_and_the_run_is_inconclusive(noise_run):
    assert [e["id"] for e in noise_run["causal"]["events"] if e["status"] == "published"] == []
    assert noise_run["status"] == "inconclusive" and noise_run["causal"]["status"] == "inconclusive"
    assert noise_run["sufficiency"]["passed"] is False


def test_an_effect_injected_in_the_pre_period_fails_the_placebo(injected_run):
    event = next(e for e in injected_run["causal"]["events"] if e["id"] == YOUTUBE_EVENT)

    assert event["status"] == "rejected" and "placebo_failed" in event["reasons"]
    assert event["placebo"]["passed"] is False and event["placebo"]["p_value"] < 0.1


def test_a_real_effect_with_a_clean_pre_period_is_still_published(clean_run):
    published = [e for e in clean_run["causal"]["events"] if e["status"] == "published"]

    assert published and clean_run["sufficiency"]["passed"] is True
    for event in published:
        assert event["placebo"]["passed"] is True and event["fit"]["wmape"] is not None
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/engine/test_placebo_acceptance.py -v`
Expected: `test_an_effect_injected...` e `test_a_real_effect...` PASS.

- O ruído branco é medição. Se alguma semente publicar evento, **não** mexa em limiar: anote quantas sementes publicam e marque o teste com `@pytest.mark.xfail(strict=True, reason="placebo alone lets white noise publish; robustness gate pending (plan, open decision 3)")`. O A6 fica sem aceite até a decisão 3; isso vai na Task 14.
- Se `test_a_real_effect...` falhar por `low_spend_variation`, imprima `clean_run["sufficiency"]["spend_variation"]` e pare: é dado para a decisão de calibração (o PMAX do sintético tem CV ≈ 0.11, perto do 0.10).

- [ ] **Step 3: Commit**

```bash
git add tests/engine/test_placebo_acceptance.py
git commit -m "test(engine): a6 acceptance: white noise, injected placebo and a clean real effect"
```

---

### Task 13 (opcional, só com a decisão 3): gate de robustez `model_dependent`

**Files:**
- Modify: `engine/analysis.py` (`baseline_only_test`; `results_dict`)
- Modify: `engine/pipeline.py` (`_gate_reasons`)
- Modify: `engine/results_schema.py` (`Robustness`, `CausalEvent.robustness`)
- Modify: `engine/results.py` (`_event`)
- Modify: `tests/engine/test_parity.py` (`ENGINE_KEYS`, `ENGINE_REASONS`)
- Test: `tests/engine/test_placebo.py`, `tests/engine/test_pipeline_stages.py`, `tests/engine/test_placebo_acceptance.py`

Contexto: emenda do Rodrigo (06/nov/2026). Refaz o ajuste do evento sem as features de mídia (`*_transformed`), só com o que o Lasso escolheu de tendência, controles e calendário, e o mesmo teste acumulado sobre o pós. Rejeita o evento quando o lift é significativo com a mídia e não sem ela (ou troca de sinal). Custa um ajuste por evento e rejeita também efeito pequeno que só o modelo com mídia vê (conservador, A10 calibra). Sem `baseline_only_p_value` (era código morto) e sem `try/except` (falha vira `analysis_failed`).

- [ ] **Step 1: Write the failing tests**

`tests/engine/test_placebo.py`, no fim (com `baseline_only_test` no import de `engine.analysis`):

```python
def _split(frame, n_post=14):
    return frame.iloc[:-n_post], frame.iloc[-n_post:]


def test_the_baseline_only_test_sees_a_real_step_and_ignores_noise():
    pre, post = _split(_pre(n=134, step_at=120, step=40.0))
    p, impact = baseline_only_test(pre, post, [])
    assert p < 0.05 and impact > 0
    for seed in (0, 1, 2):
        pre, post = _split(_pre(n=134, seed=seed))
        assert baseline_only_test(pre, post, [])[0] > 0.01
        assert baseline_only_test(pre, post, ["x"])[0] > 0.01


def test_the_event_reports_its_robustness():
    results = _event(lambda spend, rng: 50 + rng.normal(0, 5, len(spend)))
    assert 0 <= results["robust_p_value"] <= 1 and results["robust_lift"] is not None
```

`tests/engine/test_pipeline_stages.py`, no fim:

```python
def test_a_lift_significant_only_with_the_media_features_is_model_dependent():
    robust = {"robust_p_value": 0.01, "robust_lift": 8.0}
    assert pipeline._gate_reasons({**SIGNIFICANT, **robust}, GATES) == []
    assert pipeline._gate_reasons({**SIGNIFICANT, **robust, "robust_p_value": 0.4}, GATES) == ["model_dependent"]
    assert pipeline._gate_reasons({**SIGNIFICANT, **robust, "robust_lift": -8.0}, GATES) == ["model_dependent"]
    not_significant = {**SIGNIFICANT, "p_value": 0.4, "robust_p_value": 0.4, "robust_lift": 1.0}
    assert "model_dependent" not in pipeline._gate_reasons(not_significant, GATES)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_placebo.py tests/engine/test_pipeline_stages.py -v`
Expected: FAIL — `ImportError: cannot import name 'baseline_only_test'`.

- [ ] **Step 3: Implement**

`engine/analysis.py`, depois de `oos_wmape`:

```python
def baseline_only_test(pre: pd.DataFrame, post: pd.DataFrame, baseline_features: list[str]) -> tuple[float, float]:
    """(p-value, signed cumulative impact) of the event under the same model without the media features.

    A lift that is significant only with them is the model extrapolating its own coefficients onto a spend spike
    (they can be pure noise), not a response seen in the KPI.
    """
    exog = post[baseline_features] if baseline_features else None
    forecast = _fit_state_space(pre, baseline_features).get_forecast(steps=len(post), exog=exog)
    impact = float((post["kpi"].to_numpy() - np.asarray(forecast.predicted_mean)).sum())
    return cumulative_p_value(impact, forecast)[0], impact
```

Em `run_causal_impact_analysis`, depois do `wmape = ...`:

```python
        baseline_features = [f for f in selected_features if f not in transformed_features]
        robust_p, robust_lift = baseline_only_test(pre_data_for_model, post_data, baseline_features)
```

e no `results_dict`: `"robust_p_value": robust_p,` e `"robust_lift": robust_lift,`.

`engine/pipeline.py`, no fim de `_gate_reasons` (antes do `return`):

```python
    robust_p, threshold = results.get("robust_p_value"), cfg["p_value_threshold"]
    holds = robust_p is not None and robust_p < threshold and (results["absolute_lift"] > 0) == (results["robust_lift"] > 0)
    if robust_p is not None and results["p_value"] < threshold and not holds:
        reasons.append("model_dependent")  # significant only through the media features' extrapolation
```

`engine/results_schema.py`, depois de `Placebo`:

```python
class Robustness(_Model):
    p_value: float | None = None  # the lift's p-value under the model without the media features
    passed: bool | None = None  # False: significant only with them (model_dependent)
```

e em `CausalEvent`, depois de `placebo`: `robustness: Robustness | None = None`.

`engine/results.py` (import `Robustness`), em `_event`, depois do bloco do placebo:

```python
    if "robust_p_value" in data:
        event.robustness = Robustness(
            p_value=_num(data["robust_p_value"]), passed="model_dependent" not in outcome.reasons
        )
```

`tests/engine/test_parity.py`: `ENGINE_KEYS` ganha `"robust_p_value", "robust_lift"` e `ENGINE_REASONS` ganha `"model_dependent"`.

Em `tests/engine/test_placebo_acceptance.py`, tire o `xfail` do ruído branco, se a Task 12 o pôs.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/engine/test_placebo.py tests/engine/test_pipeline_stages.py tests/engine/test_placebo_acceptance.py tests/engine/test_results_build.py -v`
Expected: PASS. Se o ruído branco ainda publicar, pare e reporte quantas sementes: o gate não fecha o aceite e a decisão volta ao dono.

- [ ] **Step 5: Commit**

```bash
git add engine/analysis.py engine/pipeline.py engine/results_schema.py engine/results.py tests/engine/test_parity.py tests/engine/test_placebo.py tests/engine/test_pipeline_stages.py tests/engine/test_placebo_acceptance.py
git commit -m "feat(engine): robustness gate rejects a lift that only the media features explain (a6)"
```

---

### Task 14: documentação

**Files:**
- Modify: `CLAUDE.md` ("Estado atual")
- Modify: `docs/m2/trilha-a-motor.md` (Status de A3, A4, A5; Status novo no A6)
- Modify: `docs/m2/README.md` (contrato §2 e §3)
- Modify: `docs/decisoes/engine.md` (catálogo, A3, A4, A5, seção nova do A6)

Nenhuma rota, tabela ou coluna muda: `API-GUIDE.md` e `DATABASE.md` ficam. Use as medições reais das Tasks 5, 8 e 12 (e 13, se rodou) nos textos abaixo; onde o texto diz "medido", ponha o número.

- [ ] **Step 1: `docs/decisoes/engine.md`**

- Catálogo (linha ~85): acrescente `channel_group_name_taken` aos erros do A3.
- A3, o bullet "**VIF só reporta.** ..." vira: "**VIF também bloqueia** (06/nov/2026). `collinearity_unresolved` sai com par acima de `collinearity_r` **ou** canal com VIF acima de `gate_thresholds.vif_max` (default 10, provisório; VIF `None` conta como acima), calculado sobre o spend agrupado sem o segundo canal de cada par de `dv360_cm360_overlap` (os gêmeos se bloqueariam só pelo VIF). `details.vif_channels` lista esses canais; um canal sinalizado só pelo VIF entra em `suggested_groups` junto com o canal com que mais correlaciona. `collinearity.unresolved` grava os canais (nomes como modelados) ainda acima de algum limite depois dos grupos, também com `block_per_channel`: é o que o A5 esconde. Risco: o VIF pega canais que sobem juntos sem par acima de 0.85; medir na Gol e nas Core, A10 calibra. O nome `collinearity_vif` citado antes não existe: é `vif_max`." No bullet do gate sobre o spend agrupado, "o efeito deste último no resultado é do A5" vira "com ele, os canais de `unresolved` saem não identificáveis (A5)". Acrescente: "`channel_group_name_taken` (erro): o nome do grupo (`"A + B"`) já é um canal do arquivo. Repetição e grupo de um canal só continuam config inválida (`EngineConfig`), não check."
- A4, o bullet da paridade vira: "Paridade (06/nov/2026): no sintético a comparação causal com o protótipo voltou a ser completa (`test_events_and_gates_match`), menos o que o protótipo não calcula (`controls`, placebo, WMAPE e os motivos do A6); `passed` e `selected` saem porque derivam dos motivos. Na Gol os números mudaram de propósito (métricas de anúncio fora do modelo): `test_parity_real.py` compara a detecção com o protótipo e os números com o golden do motor, `real/gol_a4_events.json`, de `mise run parity-a4-golden` (só com aprovação; regenerar depois do A6)." Registre a decisão 2 tomada (ramo a ou b).
- A5: "Nenhum identificável → ... **E sem comparação de mix**" passa a separar os dois casos: o cenário `strategic_reallocation` sai do `results.json`, do `.md`, do HTML, do PNG combinado e do prompt sempre que **qualquer** canal está escondido, com `metrics.reallocation_suppressed = true` (antes: só sem canal identificável); as linhas "Pico de Eficiência"/"Modelo de Elasticidade" com `—` continuam só no caso sem nenhum identificável. Acrescente: "**Canal colinear** (`collinearity.unresolved`, ou seja, `block_per_channel` com par aberto ou VIF alto) sai `identifiable=false` com o motivo `collinearity`, qualquer que seja o IC. Por isso o `assess` roda em `compute()`, onde o `ValidationReport` está." e "`fold_mix` com um valor ausente entre os escondidos dá `None`, não soma 0." Registre a decisão 1 (`inconclusive` mantido).
- Seção nova `## A6 · Suficiência e placebo (06/nov/2026)`, com: placebo no meio do pré (mesmo modelo e teste do evento; p < `p_value_threshold` → `placebo_failed`; pré curto → `placebo.passed = null`, sem rejeitar; vazamento leve: features escolhidas no pré inteiro); WMAPE fora da amostra nos 20% finais do pré (`fit.wmape`; `mape` segue in-sample); exceção nesses ajustes vira `analysis_failed` (o branch paralelo engolia e passava o placebo); `sufficiency` do run (`spend_variation` = CV do spend dos canais com evento validado, `validated_events`, `pre_wmape` = mediana do WMAPE desses eventos, `reasons`, `cv_out_of_sample`); limiares `spend_cv_min` 0.10 e `oos_wmape_max` 0.30, provisórios (A10); motivo causal → eventos aprovados viram `insufficient_run` sem lift, p, CPA e séries, e `causal.reasons` ganha o motivo; `cv_in_sample` → elasticidade `inconclusive` com a curva publicada; `run_status` igual. Medições da Task 12 (quantas sementes de ruído publicam; tempo dos runs). Decisão 3 e, se a Task 13 rodou, o gate `model_dependent` e seu custo.

- [ ] **Step 2: `docs/m2/README.md`**

- §2, o fim do parágrafo "**Entregue pelo A3**" ganha: "Desde 06/nov/2026 o VIF também bloqueia (`vif_max`, default 10), `details.vif_channels` lista os canais de VIF alto e `collinearity.unresolved` lista os canais ainda colineares depois dos grupos."
- §3, lista de diferenças: o bullet do canal não identificável troca "Nenhum identificável → ... e sem o cenário `strategic_reallocation` (A5)" por "Nenhum identificável → `elasticity.status="inconclusive"` com `no_identifiable_channel`. Qualquer canal escondido → sem o cenário `strategic_reallocation` e `metrics.reallocation_suppressed=true`. Canal de `collinearity.unresolved` sai com o motivo `collinearity` (A5)." Acrescente o bullet do A6: "`sufficiency` preenchida (A6), com `reasons` (`no_validated_event`, `low_spend_variation`, `high_oos_wmape`, `cv_in_sample`) e `cv_out_of_sample`; `placebo.passed=null` quer dizer que não rodou; `fit.wmape` é fora da amostra. Evento `insufficient_run` sai `rejected` e sem lift; `cv_in_sample` deixa a elasticidade `inconclusive`. Motivos novos do evento: `placebo_failed`, `insufficient_run`." Se a Task 13 rodou: `robustness: {p_value, passed}` e `model_dependent`.

- [ ] **Step 3: `docs/m2/trilha-a-motor.md`**

- A3, acrescente ao Status: "Atualizado em 06/nov/2026: o VIF > `vif_max` (10) também bloqueia, canal só de VIF entra na sugestão, `collinearity.unresolved` e `channel_group_name_taken`. Verificado: `tests/engine/test_collinearity.py` (VIF sem par, semanal, overlap não bloqueia pelo VIF). Falta medir o VIF na Gol e nas Core."
- A4, troque a frase da paridade do Status por: "Paridade causal completa no sintético de novo (06/nov/2026); a Gol compara com o golden do motor (`mise run parity-a4-golden`, pendente de rodar com os dados). Colunas de calendário por nome exato." e registre a decisão 2.
- A5, acrescente ao Status: "Atualizado em 06/nov/2026: canal colinear com `block_per_channel` sai `identifiable=false` (`collinearity`); a realocação sai com qualquer canal escondido (`reallocation_suppressed`); aceite `STRONG`/`NOEFFECT` em três sementes."
- A6, linha nova logo abaixo do título: "- **Status:** ✅ feito em 06/nov/2026 ..." com o que foi entregue e verificado (`test_placebo.py`, `test_sufficiency.py`, `test_placebo_acceptance.py` e a medição do ruído branco). **Se o ruído branco ficou `xfail`**, o Status é "🟡 parcial: o aceite do ruído branco depende da decisão do gate de robustez", não ✅. Falta: calibrar os limiares (A10), rodar na Gol e regenerar os fixtures do A1 (precisa da Gol), `mise run parity-a4-golden` com os dados.

- [ ] **Step 4: `CLAUDE.md`, "Estado atual"**

Depois da frase do A5, acrescente: "**Ports do branch paralelo e A6 (06/nov/2026)**: o gate do A3 também bloqueia por VIF (`vif_max` 10) e grava `collinearity.unresolved`; `block_per_channel` deixa esses canais não identificáveis (`collinearity`); a realocação sai com qualquer canal escondido (`reallocation_suppressed`); paridade causal completa de volta no sintético e golden do motor para a Gol. **A6**: placebo no meio do pré (`placebo_failed`), WMAPE fora da amostra, `sufficiency` do run (`spend_cv_min` 0.10, `oos_wmape_max` 0.30, provisórios), eventos `insufficient_run` sem lift e `cv_in_sample` deixando a elasticidade `inconclusive`." No "Faltam:", tire o A6 (ou deixe "A6 aceite do ruído branco", se ficou `xfail`) e acrescente "regenerar os fixtures do A1 e o golden da Gol (precisam da Gol)".

- [ ] **Step 5: Check and commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest tests/engine tests/llm -q`
Expected: limpo e PASS.

```bash
git add CLAUDE.md docs/m2/trilha-a-motor.md docs/m2/README.md docs/decisoes/engine.md
git commit -m "docs: a3-a5 ports from the parallel branch and a6 sufficiency and placebo"
```
