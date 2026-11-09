# Parity and regression goldens

**Since 09/nov/2026 the engine no longer matches the prototype on purpose** (math audit fixes,
`docs/audit/diferencas-prototipo.md`). `tests/engine/test_parity.py` and `test_parity_real.py` now compare against the
engine's own goldens:

- `engine_snapshot.json` (versioned): every number of `compute()` on the synthetic dataset, plus the library versions.
- `real/gol_engine.json` (confidential, not versioned): the same on `exemplo_csv/Gol`.

Regenerate both, only with approval and after reading the deltas it prints, on Linux x86-64 under the pins of
`mise.toml` (a container on Windows works):

    mise run parity-golden    # python -m tests.fixtures.parity.make_engine_goldens

The prototype's own numbers stay below as history: `snapshot.json` and `real/gol.json` are what the deltas are measured
against.

---

# Parity snapshot

`snapshot.json` holds the numbers the **frozen prototype** (`opportunity-engine`, HEAD `6146b7f`) produces on the
synthetic dataset from `tests/engine/synthetic_data.py`: per-event causal results and gate outcomes, the MMM
(contribution, R2, walk-forward CV R2, adstock/Hill parameters) and the aggregated response curve with its notable points.
`tests/engine/test_parity.py` checks `engine` against it with `rtol=1e-9`.

Regenerate **only with approval** (it defines "no number changed"). The numbers depend on the BLAS kernel and numpy's
SIMD path, so generate under the pins of `mise.toml` (`OPENBLAS_CORETYPE=Haswell`, one thread,
`NPY_DISABLE_CPU_FEATURES="X86_V4 AVX512_ICL AVX512_SPR"`), on Linux x86-64 (a container on Windows works), with the
prototype's own environment, from the prototype's checkout (read-only, `../opportunity-engine` next to this repo):

    export OPENBLAS_CORETYPE=Haswell OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NPY_DISABLE_CPU_FEATURES="X86_V4 AVX512_ICL AVX512_SPR"
    cd ../opportunity-engine
    uv run python ../opportunity-engine-v2/tests/fixtures/parity/generate_legacy_snapshot.py --legacy-repo . --out ../opportunity-engine-v2/tests/fixtures/parity/snapshot.json

Run it twice and `cmp` the files: they must be byte-identical. Docker example (Windows host):
`ghcr.io/astral-sh/uv:python3.13-bookworm` with both repos mounted and `UV_PROJECT_ENVIRONMENT` pointing outside the
mounts, so the host `.venv` is not touched.

Notes
- The prototype repo is read-only for us; the script only imports it.
- Generated on x86-64 (08/nov/2026, regenerated under the pins) with numpy 2.5.0, pandas 3.0.3, scipy 1.18.0, statsmodels 0.14.6, scikit-learn 1.9.0 (the
  `versions` key in the JSON). Parity needs the same versions; they are pinned in `pyproject.toml`.
- Two consecutive runs produce byte-identical files under the pins (~1.5 min each).
- `require_model_fit` is off in the synthetic config: the local-level model's in-sample R2 is negative on this data,
  and with the gate on no event would pass (4 of 6 events pass with it off).
- Without the pins other CPUs pick different BLAS kernels and SIMD paths and the MMM optimum moves (up to ~2e-3). With them the test passed on Zen3, Zen4 and three Intel Xeon generations. `test_parity.py` skips when the pins are absent.

## Real data (Gol)

`mise run parity-real` runs the frozen prototype on `exemplo_csv/Gol` (via `--dataset-json`, single-threaded BLAS) into
`real/gol.json`, then `tests/engine/test_parity_real.py` checks the engine against it. Both the data and `real/` are
confidential and git-ignored; the test skips where they are missing. The test pins BLAS to one thread: with all threads
the response curve drifts up to ~7e-4 (relative) on this data.

## Causal numbers since A4

The synthetic dataset has no ad metrics and its Trends passes the control screening, so `test_parity.py` still compares
every causal number with the prototype; only what the prototype does not compute is left out (`controls`, the A6
placebo, out-of-sample WMAPE and gate reasons). On the Gol, A4 changed the numbers on purpose (Clicks/Impressions/Leads
left the model): `test_parity_real.py` compares the detected events with the prototype and the numbers with the
engine's own golden, `real/gol_a4_events.json` (git-ignored), written by `mise run parity-a4-golden`. That golden
catches regressions; it is not evidence of parity. Regenerate it only with approval, after reading the printed deltas,
and again after any change that moves a gate (A6 did).
