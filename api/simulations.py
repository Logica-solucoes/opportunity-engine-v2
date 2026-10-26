import logging
import unicodedata

from sqlalchemy.orm import Session

from api.models import Simulation, User, Workspace

log = logging.getLogger(__name__)

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
