import logging
from datetime import timedelta

from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api import launcher, simulations
from api.auth import Ctx
from api.models import ACTIVE_RUN_STATUSES, Run, Simulation, User

log = logging.getLogger(__name__)

# the Cloud Run Job times out at 15 min: a run still active after 20 is dead
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


def create(db: Session, simulation: Simulation, confirmed: set[str], by: User) -> Run:
    fail_stale(db, Run.simulation_id == simulation.id)
    simulations.lock(db, simulation)
    reason = block_reason(simulation, confirmed)
    if reason:
        raise Blocked(reason)

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
    except Exception:  # Popen's OSError locally, the Cloud Run client's own errors in the B11
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
