from contextlib import nullcontext

from sqlalchemy import select

from api import cli
from api.accounts import create_platform_admin
from api.models import User


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
