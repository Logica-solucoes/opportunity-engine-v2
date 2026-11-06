import hashlib
import json
import logging
import tempfile
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import engine
from api import bcb, launcher, simulations, storage
from api.auth import Ctx
from api.models import ACTIVE_RUN_STATUSES, Run, Simulation, User

log = logging.getLogger(__name__)

# the worker's watchdog kills it at 20 min (api/worker.py): a run still active after that is dead
STALE_AFTER = timedelta(minutes=20)
ACTIVE = ACTIVE_RUN_STATUSES
PUBLISHABLE = ("succeeded", "inconclusive")
PUBLISH_ERROR = "Só execuções concluídas podem ser publicadas."
STALE_ERROR = "A execução parou de responder."
LAUNCH_ERROR = "Não foi possível iniciar a execução."


class Blocked(Exception):
    pass


def fail_stale(db: Session, *where) -> None:
    db.execute(
        update(Run)
        .where(Run.status.in_(ACTIVE), Run.created_at < func.now() - STALE_AFTER, *where)
        .values(status="failed", error=STALE_ERROR, finished_at=func.now())
    )
    db.commit()


def visible(ctx: Ctx) -> list:
    where = [Run.workspace_id == ctx.workspace.id]
    # viewers see only what an analyst published (B6)
    if ctx.role == "viewer":
        where.append(Run.published_at.is_not(None))
    return where


def block_reason(simulation: Simulation, confirmed: set[str]) -> str | None:
    # same sentences as runBlockReason in web/src/lib/simulations.ts
    report = simulation.validation
    if report is None:
        return "Valide os arquivos antes de rodar."
    if not report["ok"]:
        return "Corrija os erros antes de rodar."
    if any(c["level"] == "warning" and c["id"] not in confirmed for c in report["checks"]):
        return "Confirme os avisos antes de rodar."
    if "optimization_target" not in simulation.config:
        return "Salve os parâmetros antes de rodar."
    return None


def snapshot_bcb(simulation: Simulation) -> dict | None:
    """The Banco Central series the analyst asked for, stored like an upload; raises bcb.Unavailable."""
    controls = simulation.config.get("controls") or []
    if not controls:
        return None
    content = bcb.fetch(controls)
    sha256 = hashlib.sha256(content).hexdigest()
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "bcb.csv"
        local.write_bytes(content)
        storage.put(simulations.input_key(simulation.workspace_id, simulation.id, sha256), local)
    return {"sha256": sha256, "filename": "bcb.csv"}


def create(db: Session, simulation: Simulation, confirmed: set[str], by: User) -> Run:
    # checked once before the network call so a blocked run never waits on the SGS, and again under the lock
    reason = block_reason(simulation, confirmed)
    if reason:
        raise Blocked(reason)
    fetched_controls = list(simulation.config.get("controls") or [])
    bcb_file = snapshot_bcb(simulation)  # before the lock: no row lock held during the HTTP calls
    fail_stale(db, Run.simulation_id == simulation.id)
    simulations.lock(db, simulation)
    reason = block_reason(simulation, confirmed)
    if reason:
        raise Blocked(reason)
    if (simulation.config.get("controls") or []) != fetched_controls:
        raise Blocked("Os parâmetros mudaram enquanto as séries do Banco Central eram buscadas. Rode de novo.")

    files = {f.kind: f for f in simulation.files}
    warning_ids = {c["id"] for c in simulation.validation["checks"] if c["level"] == "warning"}
    run = Run(
        workspace_id=simulation.workspace_id,
        simulation_id=simulation.id,
        status="queued",
        config=simulation.config,
        inputs={
            key: {"sha256": files[kind].sha256, "filename": files[kind].filename} if kind in files else None
            for key, kind in simulations.MAPPING_FILES.items()
        },
        confirmed_warnings=sorted(confirmed & warning_ids),
        created_by=by.id,
    )
    if bcb_file:
        run.inputs = {**run.inputs, "bcb_file": bcb_file}
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Blocked("Já há uma execução em andamento nesta simulação.")
    log.info(
        "run.created run_id=%s simulation_id=%s workspace_id=%s by=%s",
        run.id,
        run.simulation_id,
        run.workspace_id,
        by.id,
    )

    try:
        launcher.launch(run.id)
    except Exception:  # Popen's OSError
        log.exception("run.launch_failed run_id=%s", run.id)
        run.status, run.error, run.finished_at = "failed", LAUNCH_ERROR, func.now()
        db.commit()
    return run


def publish(db: Session, run: Run, by: User) -> None:
    # the engine already marks what failed a gate; this is the analyst's review before viewers see it
    if run.status not in PUBLISHABLE:
        raise Blocked(PUBLISH_ERROR)
    run.published_at, run.published_by = func.now(), by.id
    db.commit()
    log.info("run.published run_id=%s workspace_id=%s by=%s", run.id, run.workspace_id, by.id)


def unpublish(db: Session, run: Run, by: User) -> None:
    run.published_at, run.published_by = None, None
    db.commit()
    log.info("run.unpublished run_id=%s workspace_id=%s by=%s", run.id, run.workspace_id, by.id)


NO_RESULTS = "Esta execução não tem resultado para simular cenários."


def scenario(run: Run, filters: engine.ScenarioFilters) -> dict:
    if run.results_uri is None:
        raise Blocked(NO_RESULTS)
    results = json.loads(storage.path(run.results_uri).read_text(encoding="utf-8"))
    # ponytail: parses results.json on every slider move (~10 ms for 1 MB); cache by run id if it shows up in latency
    step = run.config.get("max_budget_step", engine.EngineConfig().max_budget_step)
    try:
        return engine.scenario(results, filters, step)
    except engine.EngineError as e:
        raise Blocked(str(e)) from e
