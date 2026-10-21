# AI Agent Rules & Guidelines - Marketing GEM (opportunity-engine-v2)

This document defines project-specific rules and development guidelines for AI agents working on the **Marketing GEM** platform (M2), the successor of the Streamlit-based Max Impact Engine.

---

## 1. Project Overview & Scope
Marketing GEM runs two analytical stages (the "engine", Track A) behind a multi-brand web platform (Track B):
1. **Stage 1 (Event-Level Causal Analysis):** detects significant investment changes and uses time-series modeling (`statsmodels`) to calculate incremental lift.
2. **Stage 2 (Global Saturation/Elasticity Analysis):** models long-term channel contributions and diminishing returns subject to business financial guardrails.

**Before writing a spec, plan or code for any `A*`/`B*` item, read `docs/m2/README.md`** — it holds the decisions, the A↔B contract and the target architecture. Then read your track file (`docs/m2/trilha-a-motor.md` or `docs/m2/trilha-b-plataforma.md`). Implementation plans live in `docs/superpowers/plans/`.

---

## 2. Technology Stack & Environment
- **Runtime:** Python 3.13+ via `mise` (`mise.toml`) and `uv` (`pyproject.toml` + `uv.lock`). Run tests with `mise run test` (`uv run pytest`).
- **API:** FastAPI + SQLAlchemy 2 + Alembic (`api/alembic.ini`) + psycopg 3, Postgres 16 (`docker compose up -d`). Worker stub: `python -m api.worker`.
- **Web:** Vite + React + TypeScript, TanStack Router (file-based, `routeTree.gen.ts` is versioned) + Query, managed with `bun`.
- **Deploy:** one Docker image serves the API, the SPA (`web/dist`) and the worker (`CMD` overridable). CI in `.github/workflows/ci.yml`.
- **Dev tasks:** `mise run api` (:8000), `mise run web` (:5173, proxies `/api`), `mise run db-migrate`, `mise run worker`.

---

## 3. Directory Structure
- `api/`: FastAPI app (`main.py`), DB setup (`db.py`), worker stub (`worker.py`), Alembic (`migrations/`).
- `web/`: SPA (`src/routes/` file-based routes).
- `engine/`: analytical core (Track A) — created by A0. When it lands, add `COPY engine/ ./engine/` to the `Dockerfile` runtime stage and its deps to `pyproject.toml`.
- `tests/`: pytest suite (`tests/api/` for the platform).
- `docs/m2/`: M2 plan; `docs/superpowers/`: specs and implementation plans.

---

> The rules below were inherited from the Streamlit-era engine. They apply to `engine/` (Track A) once it lands; `scripts/`, `logger.py` and Streamlit are not part of this repo.

## 4. Key Coding Rules & Guidelines

### Configuration-Driven Design
- **Never hardcode column names.** Always resolve columns using `column_mapping` parameters in the configuration:
  - `column_mapping.investment_file`: `date_col`, `channel_col`, `investment_col`
  - `column_mapping.performance_file`: `date_col`, `kpi_col`
  - `column_mapping.generic_trends_file`: `date_col`, `trends_col`
- Date columns must be dynamically standardized to a single column named `Date` during pre-processing.

### Optimization & Financial Guardrails
- Respect the `optimization_target` configuration: `"REVENUE"` (requires `average_ticket`) or `"CONVERSIONS"`.
- Support the following dynamic guardrails under `financial_targets` to prune saturation curves:
  - `target_cpa` (Average Cost Per Acquisition)
  - `target_icpa` (Incremental CPA)
  - `target_roas` (Return on Ad Spend)
  - `target_iroas` (Incremental ROAS)
- Support configurable outlier treatment with `treat_outliers` (Boolean or list of target columns).

### Execution Fallbacks
- Maintain strict compatibility between online (`local_main.py`) and offline (`local_main-without-gemini.py`) modes.
- If Gemini API is unavailable or offline mode is chosen, fall back cleanly to Markdown-based reporting (`RECOMMENDATIONS.md`).

### Logging & Error Handling
- **Never use `print()`.** Every module does `log = logging.getLogger(__name__)` and logs through it.
- `logger.py` owns the setup (`setup_logging`), wiring three handlers:
  - console (INFO+): the pt-BR line the end user reads in the Streamlit panel. `_RULES` translate the technical message and suppress noise.
  - `data/log/<namespace>.log` (DEBUG+, rotating): full record with timestamp, level, `module:line`, traceback.
  - `data/log/<namespace>.errors.log` (WARNING+, rotating): triage without scanning the full log.
- Pick the level by impact, not verbosity:
  - `DEBUG` internal parameters, per-iteration detail, resolved paths
  - `INFO` pipeline milestones the user should see
  - `WARNING` degraded but continuing: fallback used, event skipped, bad input tolerated
  - `ERROR` one unit of work failed (an event, a report) -- the pipeline goes on
  - `CRITICAL` the run cannot continue
- Log exceptions with `exc_info=True` instead of `traceback.print_exc()` -- the traceback lands in the file log, never in the user's panel.
- New user-facing message: add a `(regex, template)` row to `_RULES` in `logger.py`. Without a rule the raw English message reaches the panel.
- CLI entrypoints wrap `main()` in `LogContext(namespace)`, which calls `setup_logging` and routes any residual `print()` through logging.
- Handle individual event errors gracefully so they do not crash the entire pipeline run when processing multiple channels or events.
