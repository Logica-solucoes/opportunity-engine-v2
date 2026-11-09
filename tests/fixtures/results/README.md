# results.json fixtures

Real-shaped `results.json` documents (schema v1, `engine/results_schema.py`) for building screens without running the engine.

| File | `status` | What it is |
|---|---|---|
| `gol_anonimizada.json` | `inconclusive` | Gol example data, anonymized, run with `block_per_channel` (`GOL_RUN_CONFIG`: the A3 gate blocks the Gol on one pair, r = 0.8501): 52 candidate events, 5 `published` and the rest `rejected` (with `reasons`, `placebo_failed` among them), 12 channels, none identifiable (`elasticity.reasons == ["no_identifiable_channel"]`, two of them also `collinearity`) |
| `gol_inconclusiva.json` | `inconclusive` | Same data with no eligible event (`causal.reasons == ["no_eligible_events"]`) |
| `falha.json` | `failed` | Nothing worked: `elasticity.reasons == ["model_failed"]`, no events |
| `identificavel.json` | `inconclusive` | Synthetic (`make_identifiable_dataset`, not anonymized): `STRONG` identifiable with its curve, `NOEFFECT` not; the one event fails the placebo |
| `identificavel_scenario.json` | — | `engine.scenario` sem filtro sobre `identificavel.json` (o E2E da aba Elasticidade serve este arquivo); regenere com `uv run python tests/fixtures/results/scenario_fixture.py` sempre que o `identificavel.json` ou o `scenario` mudarem — `test_the_e2e_scenario_fixture_is_up_to_date` avisa |

No fixture is `succeeded`: since A5/A6 no dataset we have reaches it (the Gol has no identifiable channel, the
identifiable synthetic no event). Add one when a dataset gets there.

What a screen can assume
- Read `status` and `reasons` (run level, per section, per event); never recompute a gate.
- `null` means "not produced": `experiment_design` (A7; filled on the `inconclusive` fixtures since their 08/nov/2026 regeneration, `null` on `falha.json`); `placebo.passed` is `null` when the
  pre-period was too short to run it; `placebo`, `robustness` and `fit.wmape` are `null` on an event the primary
  gates (significance, direction, fit) already rejected, since those fits only run for events still in contention.
- A hidden channel's spend is pooled under `"Não identificados"` in every mix.
- `reports` (A9) is always filled: one deterministic narrative per published event and a global one, `grounding: null` (the fixtures run with no LLM).
- No `NaN`/`Infinity` anywhere; a missing number is `null`.

Anonymization (`anonymize_gol.py`): channels become `CANAL_01..NN`; investment and KPI are multiplied by two private factors
(`.private/factors.json`, git-ignored); **dates are the real ones** (accepted risk: the shape of the series is still
recognizable to someone who knows the client) and trends are untouched. The factors were drawn again on 06/nov/2026
(the first file was lost), so absolute numbers changed scale then; relative ones (lift %) do not depend on them.

Regenerate (needs `exemplo_csv/Gol` and the same `.private/factors.json`; ~6 min, one BLAS thread; run it on Linux,
where the parity holds):

    uv run python tests/fixtures/results/generate_fixtures.py

`reports` alone can be refilled without the Gol data (the narratives only read the document):

    uv run python tests/fixtures/results/add_reports.py

The E2E serves `gol_anonimizada.json` through the fake engine (`FAKE_ENGINE_RESULTS`), so `web/e2e/` checks its
numbers: update those specs when the fixture changes.
