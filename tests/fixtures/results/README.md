# results.json fixtures

Real-shaped `results.json` documents (schema v1, `engine/results_schema.py`) for building screens without running the engine.

| File | `status` | What it is |
|---|---|---|
| `gol_anonimizada.json` | `succeeded` | Gol example data, anonymized: 53 candidate events, 5 `published` and the rest `rejected` (with `reasons`), 12 channels |
| `gol_inconclusiva.json` | `inconclusive` | Same data with no eligible event (`causal.reasons == ["no_eligible_events"]`), elasticity still `ok` |
| `falha.json` | `failed` | Nothing worked: `elasticity.reasons == ["model_failed"]`, no events |

What a screen can assume
- Read `status` and `reasons` (run level, per section, per event); never recompute a gate.
- `null` means "not produced": `validation`, `sufficiency`, `experiment_design`, `reports` (A2, A5-A9), plus `placebo`, `identifiable`, `coef_ci`, curve intervals and `extrapolated` for now.
- No `NaN`/`Infinity` anywhere; a missing number is `null`.

Anonymization (`anonymize_gol.py`): channels become `CANAL_01..NN`; investment and KPI are multiplied by two private factors
(`.private/factors.json`, git-ignored); **dates are the real ones** (accepted risk: the shape of the series is still
recognizable to someone who knows the client) and trends are untouched.

Regenerate (needs `exemplo_csv/Gol` and the same `.private/factors.json`; ~6 min, one BLAS thread):

    uv run python tests/fixtures/results/generate_fixtures.py
