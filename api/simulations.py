import hashlib
import logging
import tempfile
import unicodedata
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import func
from sqlalchemy.orm import Session

from api import csvfile, storage, validation
from api.models import Simulation, SimulationFile, User, Workspace

log = logging.getLogger(__name__)

# Cloud Run caps HTTP/1 request bodies at 32 MiB; aggregated daily data is well under 1 MB
MAX_UPLOAD_BYTES = 30 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024

# EngineConfig.column_mapping key -> uploaded file kind
MAPPING_FILES = {"investment_file": "investment", "performance_file": "performance", "generic_trends_file": "trends"}
FILE_LABELS = {"investment": "investimento", "performance": "performance", "trends": "trends"}

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


def save_mapping(db: Session, simulation: Simulation, mapping: dict) -> None:
    files = {f.kind: f for f in simulation.files}
    if "investment" not in files or "performance" not in files:
        raise InvalidInput("Envie investimento e performance antes de validar.")
    if "trends" in files and "generic_trends_file" not in mapping:
        raise InvalidInput("Mapeie as colunas do arquivo de trends.")
    if "trends" not in files and "generic_trends_file" in mapping:
        raise InvalidInput("Envie o arquivo de trends antes de mapeá-lo.")
    for key, columns in mapping.items():
        file = files[MAPPING_FILES[key]]
        for column in columns.values():
            if column not in file.columns:
                raise InvalidInput(f"Coluna '{column}' não existe no arquivo de {FILE_LABELS[file.kind]}.")

    inputs = {
        key: storage.path(input_key(simulation, files[kind].sha256)) if kind in files else None
        for key, kind in MAPPING_FILES.items()
    }
    simulation.config = {**simulation.config, "column_mapping": mapping}
    try:
        report = validation.validate(inputs, simulation.config)
    except csvfile.Unreadable:
        raise InvalidInput("Não foi possível ler o arquivo de investimento.")
    simulation.validation = report
    simulation.updated_at = func.now()
    db.commit()
    log.info("simulation.validated simulation_id=%s ok=%s", simulation.id, report["ok"])
