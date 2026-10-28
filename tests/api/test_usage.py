from datetime import UTC, datetime, timedelta

import pytest

from api import usage
from api.models import Run

OCT = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def ana(make_user):
    return make_user("ana@x.com")


@pytest.fixture
def ws(make_workspace, ana):
    return make_workspace("a", [(ana, "analyst")])


@pytest.fixture
def add_run(db, make_simulation):
    # one simulation per run: the schema allows a single active run per simulation
    def add(ws, user, status, created_at=OCT, seconds=None):
        simulation = make_simulation(ws, user)
        started = created_at + timedelta(seconds=5) if seconds is not None else None
        db.add(
            Run(
                workspace_id=ws.id,
                simulation_id=simulation.id,
                created_by=user.id,
                status=status,
                config={},
                inputs={},
                confirmed_warnings=[],
                created_at=created_at,
                started_at=started,
                finished_at=started + timedelta(seconds=seconds) if started else None,
            )
        )
        db.commit()

    return add


def test_usage_counts_runs_by_status_and_sums_the_run_time(db, ws, ana, add_run):
    add_run(ws, ana, "succeeded", seconds=90)
    add_run(ws, ana, "succeeded", seconds=30)
    add_run(ws, ana, "inconclusive", seconds=60)
    add_run(ws, ana, "failed")
    add_run(ws, ana, "queued")
    add_run(ws, ana, "running")

    [row] = usage.rows(db, None)

    assert row == {
        "month": "2026-10",
        "workspace_id": ws.id,
        "workspace_name": "A",
        "user_id": ana.id,
        "user_name": "ana",
        "user_email": "ana@x.com",
        "succeeded": 2,
        "inconclusive": 1,
        "failed": 1,
        "active": 2,
        "total": 6,
        "run_seconds": 180,
    }


def test_the_month_is_the_business_month_in_sao_paulo(db, ws, ana, add_run):
    # 01:00 UTC on Oct 1 is still Sep 30 in São Paulo
    add_run(ws, ana, "succeeded", created_at=datetime(2026, 10, 1, 1, 0, tzinfo=UTC))
    add_run(ws, ana, "succeeded", created_at=datetime(2026, 10, 1, 4, 0, tzinfo=UTC))

    assert [(r["month"], r["total"]) for r in usage.rows(db, None)] == [("2026-10", 1), ("2026-09", 1)]
    assert [r["total"] for r in usage.rows(db, "2026-09")] == [1]


def test_usage_splits_by_workspace_and_user_and_orders_newest_month_first(
    db, ws, ana, add_run, make_user, make_workspace
):
    bia = make_user("bia@x.com")
    other = make_workspace("b", [(ana, "analyst")])
    add_run(ws, ana, "succeeded")
    add_run(ws, bia, "succeeded")
    add_run(other, ana, "succeeded")
    add_run(ws, ana, "succeeded", created_at=OCT + timedelta(days=31))

    got = [(r["month"], r["workspace_name"], r["user_name"]) for r in usage.rows(db, None)]

    assert got == [("2026-11", "A", "ana"), ("2026-10", "A", "ana"), ("2026-10", "A", "bia"), ("2026-10", "B", "ana")]


def test_csv_is_ready_for_a_ptbr_spreadsheet(db, ws, ana, add_run):
    add_run(ws, ana, "succeeded", seconds=90)

    text = usage.to_csv(usage.rows(db, None))

    assert text.startswith("﻿")
    header, line = text.lstrip("﻿").splitlines()
    assert header == (
        "Mês;Workspace;Usuário;E-mail;Concluídas;Inconclusivas;Falharam;Em andamento;Total;Minutos de execução"
    )
    assert line == "2026-10;A;ana;ana@x.com;1;0;0;0;1;1,5"
