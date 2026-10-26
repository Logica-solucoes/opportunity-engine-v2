from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from api import simulations
from api.auth import Ctx, require_role
from api.db import get_db
from api.models import FILE_KINDS, FileKind, Simulation, SimulationFile
from api.routes import SimulationId

router = APIRouter(prefix="/api/w/{slug}/simulations")
analyst = require_role("analyst")

SimulationName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class SimulationIn(BaseModel):
    name: SimulationName


class SimulationSummary(BaseModel):
    id: int
    name: str
    created_by_name: str
    created_at: datetime
    updated_at: datetime


class FileOut(BaseModel):
    filename: str
    size_bytes: int
    sha256: str
    columns: list[str]
    suggested: dict[str, str | None]
    uploaded_at: datetime


class SimulationOut(BaseModel):
    id: int
    name: str
    config: dict
    validation: dict | None
    files: dict[str, FileOut | None]


def file_out(f: SimulationFile) -> FileOut:
    return FileOut(
        filename=f.filename,
        size_bytes=f.size_bytes,
        sha256=f.sha256,
        columns=f.columns,
        suggested=simulations.suggest_mapping(f.kind, f.columns),
        uploaded_at=f.uploaded_at,
    )


def simulation_out(s: Simulation) -> SimulationOut:
    files = {f.kind: f for f in s.files}
    return SimulationOut(
        id=s.id,
        name=s.name,
        config=s.config,
        validation=s.validation,
        files={kind: file_out(files[kind]) if kind in files else None for kind in FILE_KINDS},
    )


def find_simulation(db: Session, ctx: Ctx, simulation_id: int) -> Simulation:
    simulation = db.scalar(
        select(Simulation).where(Simulation.id == simulation_id, Simulation.workspace_id == ctx.workspace.id)
    )
    if simulation is None:
        raise HTTPException(404)
    return simulation


@router.get("", response_model=list[SimulationSummary])
def list_simulations(ctx: Ctx = Depends(analyst), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Simulation)
        .options(joinedload(Simulation.creator))
        .where(Simulation.workspace_id == ctx.workspace.id)
        .order_by(Simulation.updated_at.desc(), Simulation.id.desc())
    )
    return [
        SimulationSummary(
            id=s.id, name=s.name, created_by_name=s.creator.name, created_at=s.created_at, updated_at=s.updated_at
        )
        for s in rows
    ]


@router.post("", status_code=201, response_model=SimulationOut)
def create_simulation(body: SimulationIn, ctx: Ctx = Depends(analyst), db: Session = Depends(get_db)):
    return simulation_out(simulations.create(db, ctx.workspace, body.name, by=ctx.user))


@router.get("/{simulation_id}", response_model=SimulationOut)
def get_simulation(simulation_id: SimulationId, ctx: Ctx = Depends(analyst), db: Session = Depends(get_db)):
    return simulation_out(find_simulation(db, ctx, simulation_id))


@router.put("/{simulation_id}/files/{kind}", response_model=SimulationOut)
def upload_file(
    simulation_id: SimulationId,
    kind: FileKind,
    file: UploadFile,
    ctx: Ctx = Depends(analyst),
    db: Session = Depends(get_db),
):
    simulation = find_simulation(db, ctx, simulation_id)
    try:
        simulations.save_file(db, simulation, kind, file.file, file.filename or "", by=ctx.user)
    except simulations.TooLarge:
        raise HTTPException(413, "Arquivo maior que 30 MB.")
    except simulations.InvalidInput as e:
        raise HTTPException(422, str(e))
    return simulation_out(simulation)
