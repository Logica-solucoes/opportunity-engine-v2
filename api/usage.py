from sqlalchemy import column, select, table
from sqlalchemy.orm import Session

from api import csvfile
from api.models import User, Workspace

COUNTS = ("succeeded", "inconclusive", "failed", "active", "total")

usage = table(
    "usage", column("workspace_id"), column("user_id"), column("month"), *map(column, COUNTS), column("run_seconds")
)

CSV_HEADER = [
    "Mês",
    "Workspace",
    "Usuário",
    "E-mail",
    "Concluídas",
    "Inconclusivas",
    "Falharam",
    "Em andamento",
    "Total",
    "Minutos de execução",
]


def rows(db: Session, month: str | None) -> list[dict]:
    query = (
        select(
            usage,
            Workspace.name.label("workspace_name"),
            User.name.label("user_name"),
            User.email.label("user_email"),
        )
        .join(Workspace, Workspace.id == usage.c.workspace_id)
        .join(User, User.id == usage.c.user_id)
        .order_by(usage.c.month.desc(), Workspace.name, User.name, usage.c.workspace_id, usage.c.user_id)
    )
    if month:
        query = query.where(usage.c.month == month)
    return [dict(r._mapping) for r in db.execute(query)]


def to_csv(rows: list[dict]) -> str:
    lines = [
        [
            r["month"],
            csvfile.safe(r["workspace_name"]),
            csvfile.safe(r["user_name"]),
            csvfile.safe(r["user_email"]),
            *(r[c] for c in COUNTS),
            csvfile.decimal(r["run_seconds"] / 60, 1),
        ]
        for r in rows
    ]
    return csvfile.to_csv(CSV_HEADER, lines)
