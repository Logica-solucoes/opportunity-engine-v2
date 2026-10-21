import logging
from contextlib import nullcontext

from api import cli


def test_secrets_never_reach_the_log(
    caplog, capsys, monkeypatch, db, client, make_client, make_user, login_as, password
):
    caplog.set_level(logging.DEBUG)
    root = make_user("root@x.com", platform=True)
    ana = make_user("ana@x.com")
    wrong, new = "senha-errada-xyz-123", "nova-senha-secreta-1"

    client.post("/api/auth/login", json={"email": "ana@x.com", "password": wrong})
    login_as(client, ana)
    ana_token = client.cookies["gem_session"]
    client.post("/api/auth/password", json={"current": password, "new": new})

    admin = make_client()
    login_as(admin, root)
    temp = admin.post(f"/api/admin/users/{ana.id}/reset-password").json()["temp_password"]

    monkeypatch.setattr(cli, "SessionLocal", lambda: nullcontext(db))
    cli.main(["create-admin", "novo@x.com", "Novo"])
    cli_temp = capsys.readouterr().out.split(": ", 1)[1].strip()

    log = caplog.text
    for event in ("auth.login_failed", "auth.login_ok", "auth.password_changed", "auth.password_reset"):
        assert event in log, f"{event} not logged: the test would pass vacuously"
    for secret in (password, wrong, new, temp, cli_temp, ana_token, admin.cookies["gem_session"]):
        assert secret not in log


def test_failed_login_logs_email_repr_and_locked_attempts_are_logged(caplog, client, make_user, password):
    caplog.set_level(logging.INFO)
    ana = make_user("ana@x.com")

    client.post("/api/auth/login", json={"email": "forged@x.com\nauth.login_ok user_id=1", "password": "x"})
    for _ in range(5):
        client.post("/api/auth/login", json={"email": "ana@x.com", "password": "errada-errada"})
    client.post("/api/auth/login", json={"email": "ana@x.com", "password": password})

    assert all(not line.startswith("auth.login_ok") for line in caplog.text.splitlines())
    assert f"auth.login_locked user_id={ana.id}" in caplog.text
