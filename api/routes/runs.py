from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from api import runs
from api.auth import Ctx, require_role
from api.db import get_db
from api.models import Run
from api.routes import RunId, SimulationId
from api.routes.simulations import find_simulation

router = APIRouter(prefix="/api/w/{slug}")
analyst = require_role("analyst")
viewer = require_role("viewer")


class RunIn(BaseModel):
    confirmed_warnings: list[str] = Field(default=[], max_length=100)


class SimulationRef(BaseModel):
    id: int
    name: str


class RunOut(BaseModel):
    id: int
    status: str
    simulation: SimulationRef
    created_by_name: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    summary: dict | None
    engine_version: str | None


def run_out(r: Run) -> RunOut:
    return RunOut(
        id=r.id,
        status=r.status,
        simulation=SimulationRef(id=r.simulation.id, name=r.simulation.name),
        created_by_name=r.creator.name,
        created_at=r.created_at,
        started_at=r.started_at,
        finished_at=r.finished_at,
        error=r.error,
        summary=r.summary,
        engine_version=r.engine_version,
    )


def find_run(db: Session, ctx: Ctx, run_id: int) -> Run:
    runs.fail_stale(db, Run.id == run_id, Run.workspace_id == ctx.workspace.id)
    run = db.scalar(select(Run).where(Run.id == run_id, *runs.visible(ctx)))
    if run is None:
        raise HTTPException(404)
    return run


@router.post("/simulations/{simulation_id}/runs", status_code=201, response_model=RunOut)
def create_run(simulation_id: SimulationId, body: RunIn, ctx: Ctx = Depends(analyst), db: Session = Depends(get_db)):
    simulation = find_simulation(db, ctx, simulation_id)
    try:
        run = runs.create(db, simulation, set(body.confirmed_warnings), by=ctx.user)
    except runs.Blocked as e:
        raise HTTPException(409, str(e))
    return run_out(run)


@router.get("/simulations/{simulation_id}/runs", response_model=list[RunOut])
def list_runs(simulation_id: SimulationId, ctx: Ctx = Depends(viewer), db: Session = Depends(get_db)):
    find_simulation(db, ctx, simulation_id)
    runs.fail_stale(db, Run.simulation_id == simulation_id)
    rows = db.scalars(
        select(Run)
        .options(joinedload(Run.creator), joinedload(Run.simulation))
        .where(Run.simulation_id == simulation_id, *runs.visible(ctx))
        .order_by(Run.id.desc())
        .limit(20)
    )
    return [run_out(r) for r in rows]


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: RunId, ctx: Ctx = Depends(viewer), db: Session = Depends(get_db)):
    return run_out(find_run(db, ctx, run_id))
