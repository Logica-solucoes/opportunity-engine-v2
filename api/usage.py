import csv
import io

from sqlalchemy import column, select, table
from sqlalchemy.orm import Session

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
        .order_by(usage.c.month.desc(), Workspace.name, User.name)
    )
    if month:
        query = query.where(usage.c.month == month)
    return [dict(r._mapping) for r in db.execute(query)]


def to_csv(rows: list[dict]) -> str:
    # ";" and a decimal comma, with a BOM: what Excel in pt-BR opens without the import wizard
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for r in rows:
        minutes = f"{r['run_seconds'] / 60:.1f}".replace(".", ",")
        writer.writerow(
            [r["month"], r["workspace_name"], r["user_name"], r["user_email"], *(r[c] for c in COUNTS), minutes]
        )
    return "﻿" + out.getvalue()
