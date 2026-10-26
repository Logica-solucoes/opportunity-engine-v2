import hashlib
import logging
import tempfile
import unicodedata
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import func
from sqlalchemy.orm import Session

from api import csvfile, storage
from api.models import Simulation, SimulationFile, User, Workspace

log = logging.getLogger(__name__)

# Cloud Run caps HTTP/1 request bodies at 32 MiB; aggregated daily data is well under 1 MB
MAX_UPLOAD_BYTES = 30 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024

FIELDS = {
    "investment": ("date_col", "channel_col", "investment_col"),
    "performance": ("date_col", "kpi_col"),
    "trends": ("date_col", "trends_col"),
}
ALIASES = {
    "date_col": ("data", "date", "dia", "day"),
    "channel_col": ("canal", "channel", "midia", "media"),
    "investment_col": ("investimento", "invest", "spend", "custo", "cost", "valor"),
}


class TooLarge(Exception):
    pass


class InvalidInput(Exception):
    pass


def create(db: Session, workspace: Workspace, name: str, by: User) -> Simulation:
    simulation = Simulation(workspace_id=workspace.id, name=name, config={}, created_by=by.id)
    db.add(simulation)
    db.commit()
    log.info("simulation.created simulation_id=%s workspace_id=%s by=%s", simulation.id, workspace.id, by.id)
    return simulation


def normalize(column: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", column.lower()) if c.isalnum())


def suggest_mapping(kind: str, columns: list[str]) -> dict[str, str | None]:
    normalized = [normalize(c) for c in columns]
    suggestion = {}
    for field in FIELDS[kind]:
        if field in ALIASES:
            suggestion[field] = next((c for c, n in zip(columns, normalized) if n.startswith(ALIASES[field])), None)
        else:
            # the KPI / trends file has one value column besides the date
            suggestion[field] = next((c for c in columns if c != suggestion["date_col"]), None)
    return suggestion


def input_key(simulation: Simulation, sha256: str) -> str:
    return f"ws/{simulation.workspace_id}/sim/{simulation.id}/inputs/{sha256}.csv"


def save_file(db: Session, simulation: Simulation, kind: str, src: BinaryIO, filename: str, by: User) -> None:
    if not filename.lower().endswith(".csv"):
        raise InvalidInput("Envie um arquivo .csv.")
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "upload.csv"
        digest, size = hashlib.sha256(), 0
        with local.open("wb") as out:
            while chunk := src.read(CHUNK_BYTES):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise TooLarge
                digest.update(chunk)
                out.write(chunk)
        try:
            columns = csvfile.header(local)
        except csvfile.Unreadable:
            raise InvalidInput("Não foi possível ler o cabeçalho do CSV.")
        sha256 = digest.hexdigest()
        storage.put(input_key(simulation, sha256), local)

    row = db.get(SimulationFile, (simulation.id, kind)) or SimulationFile(simulation_id=simulation.id, kind=kind)
    row.sha256 = sha256
    # display only, never a path; browsers on Windows may send "C:\fakepath\name.csv"
    row.filename = filename.replace("\\", "/").rsplit("/", 1)[-1][:200]
    row.size_bytes = size
    row.columns = columns
    row.uploaded_by = by.id
    row.uploaded_at = func.now()
    db.add(row)
    simulation.validation = None
    simulation.updated_at = func.now()
    db.commit()
    log.info(
        "simulation.file_uploaded simulation_id=%s kind=%s sha256=%s size_bytes=%s", simulation.id, kind, sha256, size
    )
