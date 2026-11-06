# Parity snapshot

`snapshot.json` holds the numbers the **frozen prototype** (`opportunity-engine`, HEAD `6146b7f`) produces on the
synthetic dataset from `tests/engine/synthetic_data.py`: per-event causal results and gate outcomes, the MMM
(contribution, R2, walk-forward CV R2, adstock/Hill parameters) and the aggregated response curve with its notable points.
`tests/engine/test_parity.py` checks `engine` against it with `rtol=1e-9`.

Regenerate **only with approval** (it defines "no number changed"). With the prototype's own environment:

    cd /home/rodrigo/Sistemas/Dash/opportunity-engine
    uv run python <this repo>/tests/fixtures/parity/generate_legacy_snapshot.py --legacy-repo . --out <this dir>/snapshot.json

Notes
- The prototype repo is read-only for us; the script only imports it.
- Generated on x86-64 with numpy 2.5.0, pandas 3.0.3, scipy 1.18.0, statsmodels 0.14.6, scikit-learn 1.9.0 (the
  `versions` key in the JSON). Parity needs the same versions; they are pinned in `pyproject.toml`.
- Two consecutive runs produced byte-identical files on the generating machine (~1.5 min each, multi-threaded BLAS).
- `require_model_fit` is off in the synthetic config: the local-level model's in-sample R2 is negative on this data,
  and with the gate on no event would pass (4 of 6 events pass with it off).
- Other CPUs may pick different BLAS kernels. Run the parity test once on the server and record any tolerance change.

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
