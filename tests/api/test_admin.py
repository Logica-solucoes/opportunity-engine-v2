import logging
from datetime import UTC, datetime, timedelta

from api.models import Workspace


def test_create_and_list_workspaces(client, db, make_user, login_as):
    login_as(client, make_user("root@x.com", platform=True))

    r = client.post("/api/admin/workspaces", json={"name": "Marca B", "slug": "marca-b"})
    client.post("/api/admin/workspaces", json={"name": "Marca A", "slug": "marca-a"})

    assert r.status_code == 201
    assert r.json()["slug"] == "marca-b" and db.get(Workspace, r.json()["id"]).settings == {}
    assert [w["name"] for w in client.get("/api/admin/workspaces").json()] == ["Marca A", "Marca B"]


def test_workspace_slug_rules(client, make_user, make_workspace, login_as):
    make_workspace("existe")
    login_as(client, make_user("root@x.com", platform=True))

    dup = client.post("/api/admin/workspaces", json={"name": "X", "slug": "existe"})
    assert dup.status_code == 409
    for bad in ("A", "com espaço", "Maiuscula", "x" * 41, "a_b"):
        assert client.post("/api/admin/workspaces", json={"name": "X", "slug": bad}).status_code == 422, bad


def test_platform_admin_sees_all_workspaces_as_admin(client, make_user, make_workspace, login_as):
    make_workspace("b")
    make_workspace("a")
    login_as(client, make_user("root@x.com", platform=True))

    assert client.get("/api/me").json()["workspaces"] == [
        {"slug": "a", "name": "A", "role": "admin"},
        {"slug": "b", "name": "B", "role": "admin"},
    ]


def test_list_users(client, db, make_user, login_as):
    root = make_user("root@x.com", platform=True)
    ana = make_user("ana@x.com")
    ana.locked_until = datetime.now(UTC) + timedelta(minutes=5)
    db.flush()
    login_as(client, root)

    users = client.get("/api/admin/users").json()

    assert [u["email"] for u in users] == ["ana@x.com", "root@x.com"]
    assert users[0]["locked_until"] is not None and users[0]["is_platform_admin"] is False
    assert set(users[0]) == {"id", "email", "name", "active", "is_platform_admin", "locked_until"}


def test_reset_password_kills_sessions_and_unlocks(make_client, db, make_user, login_as):
    root, ana = make_user("root@x.com", platform=True), make_user("ana@x.com")
    admin_client, ana_client = make_client(), make_client()
    login_as(admin_client, root)
    login_as(ana_client, ana)
    ana.locked_until = datetime.now(UTC) + timedelta(minutes=5)
    db.flush()

    r = admin_client.post(f"/api/admin/users/{ana.id}/reset-password")

    assert r.status_code == 200
    temp = r.json()["temp_password"]
    assert ana_client.get("/api/me").status_code == 401
    fresh = make_client()
    me = login_as(fresh, ana, temp).json()
    assert me["must_change_password"] is True


def test_deactivate_kills_sessions_and_blocks_login(make_client, make_user, login_as, password):
    root, ana = make_user("root@x.com", platform=True), make_user("ana@x.com")
    admin_client, ana_client = make_client(), make_client()
    login_as(admin_client, root)
    login_as(ana_client, ana)

    r = admin_client.patch(f"/api/admin/users/{ana.id}", json={"active": False})

    assert r.status_code == 200 and r.json()["active"] is False
    assert ana_client.get("/api/me").status_code == 401
    login = ana_client.post("/api/auth/login", json={"email": "ana@x.com", "password": password})
    assert login.status_code == 401

    admin_client.patch(f"/api/admin/users/{ana.id}", json={"active": True})
    login_as(ana_client, ana)


def test_platform_admin_cannot_deactivate_self(client, db, make_user, login_as):
    root = make_user("root@x.com", platform=True)
    login_as(client, root)

    r = client.patch(f"/api/admin/users/{root.id}", json={"active": False})

    assert (r.status_code, r.json()) == (400, {"detail": "cannot_deactivate_self"})
    db.refresh(root)
    assert root.active is True
    assert client.patch(f"/api/admin/users/{root.id}", json={"active": True}).status_code == 200


def test_reactivation_clears_lockout_and_is_logged(client, make_client, caplog, db, make_user, login_as):
    caplog.set_level(logging.INFO)
    root, ana = make_user("root@x.com", platform=True), make_user("ana@x.com", active=False)
    ana.failed_logins = 3
    ana.locked_until = datetime.now(UTC) + timedelta(minutes=5)
    db.flush()
    login_as(client, root)

    assert client.patch(f"/api/admin/users/{ana.id}", json={"active": True}).status_code == 200

    db.refresh(ana)
    assert (ana.failed_logins, ana.locked_until) == (0, None)
    assert f"auth.user_reactivated user_id={ana.id} by={root.id}" in caplog.text
    login_as(make_client(), ana)


def test_unknown_user_is_404(client, make_user, login_as):
    login_as(client, make_user("root@x.com", platform=True))

    assert client.post("/api/admin/users/999999/reset-password").status_code == 404
    assert client.patch("/api/admin/users/999999", json={"active": False}).status_code == 404


def test_out_of_range_user_id_is_422_not_500(client, make_user, login_as):
    login_as(client, make_user("root@x.com", platform=True))

    for user_id in (2**63, 0):
        assert client.post(f"/api/admin/users/{user_id}/reset-password").status_code == 422
        assert client.patch(f"/api/admin/users/{user_id}", json={"active": False}).status_code == 422
