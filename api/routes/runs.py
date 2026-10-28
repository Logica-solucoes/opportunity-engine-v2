import asyncio
import json
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from api import runs
from api.auth import Ctx, require_role
from api.db import SessionLocal, get_db
from api.models import Run, RunLog
from api.routes import RunId, SimulationId
from api.routes.simulations import find_simulation

router = APIRouter(prefix="/api/w/{slug}")
analyst = require_role("analyst")
viewer = require_role("viewer")

POLL_SECONDS = 0.5
# proxies drop a quiet connection; a comment line every 15 s keeps it open through a long engine step
PING_SECONDS = 15
BACKLOG = 300
BATCH = 500


class RunIn(BaseModel):
    confirmed_warnings: list[Annotated[str, Field(max_length=100)]] = Field(default=[], max_length=100)


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
    config: dict
    inputs: dict
    published_at: datetime | None
    published_by_name: str | None


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
        config=r.config,
        inputs=r.inputs,
        published_at=r.published_at,
        published_by_name=r.publisher.name if r.publisher else None,
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
        .options(joinedload(Run.creator), joinedload(Run.publisher), joinedload(Run.simulation))
        .where(Run.simulation_id == simulation_id, *runs.visible(ctx))
        .order_by(Run.id.desc())
        .limit(20)
    )
    return [run_out(r) for r in rows]


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: RunId, ctx: Ctx = Depends(viewer), db: Session = Depends(get_db)):
    return run_out(find_run(db, ctx, run_id))


def poll(run_id: int, after: int | None, sweep: bool = False) -> tuple[str | None, str, int | None]:
    # a short session per poll: the stream lasts the whole run and must not pin a pooled connection
    with SessionLocal() as db:
        if sweep:
            runs.fail_stale(db, Run.id == run_id)
        # status before lines: the worker writes every line before the final status
        status = db.scalar(select(Run.status).where(Run.id == run_id))
        query = select(RunLog).where(RunLog.run_id == run_id)
        if after is None:
            rows = db.scalars(query.order_by(RunLog.id.desc()).limit(BACKLOG)).all()[::-1]
        else:
            rows = db.scalars(query.where(RunLog.id > after).order_by(RunLog.id).limit(BATCH)).all()
        chunk = "".join(
            f"id: {r.id}\ndata: {json.dumps({'ts': r.ts.isoformat(), 'level': r.level, 'message': r.message}, ensure_ascii=False)}\n\n"
            for r in rows
        )
        return status, chunk, rows[-1].id if rows else None


async def log_events(run_id: int, after: int | None):
    idle = 0.0
    while True:
        # the stale check rides the ping: a worker that stops logging is failed within PING_SECONDS + a poll
        sweep = idle >= PING_SECONDS
        status, chunk, last_id = await run_in_threadpool(poll, run_id, after, sweep)
        if chunk:
            yield chunk
            after, idle = last_id, 0.0
            continue
        # a deleted run (status None) ends the stream too
        if status not in runs.ACTIVE:
            yield f"event: end\ndata: {json.dumps({'status': status})}\n\n"
            return
        if sweep:
            yield ": ping\n\n"
            idle = 0.0
        after = after or 0
        await asyncio.sleep(POLL_SECONDS)
        idle += POLL_SECONDS


@router.get("/runs/{run_id}/logs/stream")
def stream_logs(
    run_id: RunId,
    ctx: Ctx = Depends(viewer),
    db: Session = Depends(get_db),
    last_event_id: Annotated[int | None, Header(ge=0)] = None,
):
    find_run(db, ctx, run_id)
    # hand the request's connection back to the pool: the stream polls with sessions of its own
    db.commit()
    return StreamingResponse(
        log_events(run_id, last_event_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
