import logging
from contextlib import nullcontext
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from api import cli, storage
from api.accounts import create_platform_admin
from api.models import Run, Simulation, User, Workspace


def test_create_admin_makes_a_platform_admin_that_can_log_in(client, db, login_as):
    temp = create_platform_admin(db, " Root@X.com ", "Root")

    user = db.scalar(select(User).where(User.email == "root@x.com"))
    me = login_as(client, user, temp).json()
    assert me["is_platform_admin"] is True and me["must_change_password"] is True


def test_create_admin_promotes_existing_user_and_resets_password(client, db, make_user, password):
    ana = make_user("ana@x.com")

    temp = create_platform_admin(db, "ana@x.com", "Ana")

    assert ana.is_platform_admin is True
    assert client.post("/api/auth/login", json={"email": "ana@x.com", "password": password}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "ana@x.com", "password": temp}).status_code == 200


def test_main_prints_the_temp_password(client, db, monkeypatch, capsys):
    monkeypatch.setattr(cli, "SessionLocal", lambda: nullcontext(db))

    cli.main(["create-admin", "root@x.com", "Root"])

    out = capsys.readouterr().out
    assert out.startswith("senha temporária: ")
    temp = out.split(": ", 1)[1].strip()
    assert client.post("/api/auth/login", json={"email": "root@x.com", "password": temp}).status_code == 200


@pytest.fixture
def cli_db(db, monkeypatch):
    monkeypatch.setattr(cli, "SessionLocal", lambda: nullcontext(db))
    return db


def trashed(db, make_workspace, slug, age):
    workspace = make_workspace(slug)
    workspace.deleted_at = func.now() - age
    db.commit()
    storage.path(f"ws/{workspace.id}/sim/1").mkdir(parents=True)
    return workspace


def exists(db, workspace_id):
    return db.get(Workspace, workspace_id) is not None


def test_purge_deletes_only_what_is_in_the_trash_for_more_than_7_days(cli_db, make_workspace, capsys):
    old = trashed(cli_db, make_workspace, "velho", timedelta(days=7, seconds=1))
    recent = trashed(cli_db, make_workspace, "recente", timedelta(days=7) - timedelta(minutes=1))
    active = make_workspace("ativo")
    old_id = old.id

    cli.main(["purge-workspaces"])

    cli_db.expire_all()
    assert not exists(cli_db, old_id) and not storage.path(f"ws/{old_id}").exists()
    assert exists(cli_db, recent.id) and storage.path(f"ws/{recent.id}").exists()
    assert exists(cli_db, active.id)
    assert capsys.readouterr().out == "1 workspace(s) apagado(s) de vez\n"


def test_purge_with_nothing_to_delete_says_zero(cli_db, capsys):
    cli.main(["purge-workspaces"])

    assert capsys.readouterr().out == "0 workspace(s) apagado(s) de vez\n"


def test_a_storage_failure_still_purges_the_rows_and_logs_the_orphans(cli_db, make_workspace, monkeypatch, caplog):
    old = trashed(cli_db, make_workspace, "velho", timedelta(days=8))
    old_id = old.id

    def broken(prefix):
        raise OSError("disk")

    monkeypatch.setattr(storage, "delete_prefix", broken)
    caplog.set_level(logging.INFO)

    cli.main(["purge-workspaces"])

    cli_db.expire_all()
    assert not exists(cli_db, old_id)
    orphan = next(rec for rec in caplog.records if rec.getMessage().startswith("workspace.files_orphaned"))
    assert orphan.levelno == logging.ERROR and f"prefix=ws/{old_id}" in orphan.getMessage()


def test_delete_workspace_with_yes_deletes_an_active_one_now(cli_db, make_workspace, capsys):
    workspace = make_workspace("a")
    wid = workspace.id

    cli.main(["delete-workspace", "a", "--yes"])

    cli_db.expire_all()
    assert not exists(cli_db, wid)
    assert capsys.readouterr().out == "a apagado de vez\n"


def test_delete_workspace_deletes_one_in_the_trash(cli_db, make_workspace):
    workspace = trashed(cli_db, make_workspace, "a", timedelta(hours=1))
    wid = workspace.id

    cli.main(["delete-workspace", "a", "--yes"])

    cli_db.expire_all()
    assert not exists(cli_db, wid) and not storage.path(f"ws/{wid}").exists()


def test_delete_workspace_asks_for_the_slug_again(cli_db, make_workspace, monkeypatch):
    workspace = make_workspace("a")
    wid = workspace.id
    monkeypatch.setattr("builtins.input", lambda prompt: "a")

    cli.main(["delete-workspace", "a"])

    cli_db.expire_all()
    assert not exists(cli_db, wid)


def test_a_wrong_confirmation_deletes_nothing(cli_db, make_workspace, monkeypatch):
    workspace = make_workspace("a")
    monkeypatch.setattr("builtins.input", lambda prompt: "b")

    with pytest.raises(SystemExit) as exit_:
        cli.main(["delete-workspace", "a"])

    assert exit_.value.code == 1 and exists(cli_db, workspace.id)


def test_an_unknown_slug_exits_1(cli_db):
    with pytest.raises(SystemExit) as exit_:
        cli.main(["delete-workspace", "nao-existe", "--yes"])

    assert exit_.value.code == 1


def test_an_active_run_blocks_delete_workspace(cli_db, make_user, make_workspace, make_simulation):
    user = make_user("ana@x.com")
    workspace = make_workspace("a", [(user, "analyst")])
    simulation = make_simulation(workspace, user)
    cli_db.add(
        Run(
            workspace_id=workspace.id,
            simulation_id=simulation.id,
            created_by=user.id,
            status="running",
            config={},
            inputs={},
            confirmed_warnings=[],
        )
    )
    cli_db.commit()

    with pytest.raises(SystemExit) as exit_:
        cli.main(["delete-workspace", "a", "--yes"])

    assert exit_.value.code == 1 and exists(cli_db, workspace.id)
    assert cli_db.get(Simulation, simulation.id) is not None
