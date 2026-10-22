import logging

from sqlalchemy import select

from api.models import Membership, User


def test_list_members_sorted_by_email(client, make_user, make_workspace, login_as):
    admin = make_user("zeca@x.com")
    viewer = make_user("bia@x.com", active=False)
    make_workspace("a", [(admin, "admin"), (viewer, "viewer")])
    login_as(client, admin)

    assert client.get("/api/w/a/members").json() == [
        {"user_id": viewer.id, "email": "bia@x.com", "name": "bia", "role": "viewer", "active": False},
        {"user_id": admin.id, "email": "zeca@x.com", "name": "zeca", "role": "admin", "active": True},
    ]


def test_platform_admin_creates_account_with_temp_password_once(
    make_client, client, db, make_user, make_workspace, login_as
):
    root = make_user("root@x.com", platform=True)
    ws = make_workspace("a")
    login_as(client, root)

    r = client.post("/api/w/a/members", json={"email": " Nova@X.com ", "name": "Nova", "role": "analyst"})

    assert r.status_code == 201
    assert r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["email"] == "nova@x.com" and body["role"] == "analyst" and body["active"] is True
    temp = body["temp_password"]
    assert len(temp) >= 12

    user = db.scalar(select(User).where(User.email == "nova@x.com"))
    assert user.must_change_password and db.get(Membership, (user.id, ws.id)).role == "analyst"
    newcomer = make_client()
    login_as(newcomer, user, temp)
    assert newcomer.get("/api/me").json()["must_change_password"] is True


def test_add_existing_account_only_creates_membership(client, db, make_user, make_workspace, login_as):
    admin = make_user("admin@x.com")
    other = make_user("outro@x.com")
    make_workspace("b", [(other, "viewer")])
    make_workspace("a", [(admin, "admin")])
    before = other.password_hash
    login_as(client, admin)

    r = client.post("/api/w/a/members", json={"email": "outro@x.com", "name": "Nome Trocado", "role": "viewer"})

    assert r.status_code == 201
    assert r.json()["temp_password"] is None
    db.refresh(other)
    assert (other.password_hash, other.name) == (before, "outro")


def test_workspace_admin_cannot_create_accounts(client, db, make_user, make_workspace, login_as):
    # an account minted by brand A's admin would later be linked to brand B, with A's admin holding its password
    admin = make_user("admin@x.com")
    make_workspace("a", [(admin, "admin")])
    login_as(client, admin)

    r = client.post("/api/w/a/members", json={"email": "nova@x.com", "name": "Nova", "role": "viewer"})

    assert (r.status_code, r.json()) == (404, {"detail": "account_not_found"})
    assert db.scalar(select(User).where(User.email == "nova@x.com")) is None


def test_linking_needs_no_name_but_creating_does(client, make_user, make_workspace, login_as):
    root = make_user("root@x.com", platform=True)
    make_user("outro@x.com")
    make_workspace("a")
    login_as(client, root)

    linked = client.post("/api/w/a/members", json={"email": "outro@x.com", "role": "viewer"})
    unnamed = client.post("/api/w/a/members", json={"email": "nova@x.com", "role": "viewer"})
    blank = client.post("/api/w/a/members", json={"email": "nova@x.com", "name": "  ", "role": "viewer"})

    assert linked.status_code == 201
    assert (unnamed.status_code, unnamed.json()) == (422, {"detail": "name_required"})
    assert blank.status_code == 422


def test_add_existing_member_is_409(client, make_user, make_workspace, login_as):
    admin = make_user("admin@x.com")
    make_workspace("a", [(admin, "admin")])
    login_as(client, admin)

    r = client.post("/api/w/a/members", json={"email": "admin@x.com", "name": "Admin", "role": "viewer"})

    assert r.status_code == 409


def test_add_member_validates_input(client, make_user, make_workspace, login_as):
    admin = make_user("admin@x.com")
    make_workspace("a", [(admin, "admin")])
    login_as(client, admin)

    bad_role = client.post("/api/w/a/members", json={"email": "x@x.com", "name": "X", "role": "owner"})
    bad_email = client.post("/api/w/a/members", json={"email": "sem-arroba", "name": "X", "role": "viewer"})

    assert bad_role.status_code == 422 and bad_email.status_code == 422


def test_change_role_and_remove(client, db, make_user, make_workspace, login_as):
    admin = make_user("admin@x.com")
    member = make_user("m@x.com")
    ws = make_workspace("a", [(admin, "admin"), (member, "viewer")])
    login_as(client, admin)

    r = client.patch(f"/api/w/a/members/{member.id}", json={"role": "analyst"})
    assert r.status_code == 200 and r.json()["role"] == "analyst"

    assert client.delete(f"/api/w/a/members/{member.id}").status_code == 204
    assert db.get(Membership, (member.id, ws.id)) is None
    assert db.get(User, member.id) is not None


def test_last_admin_cannot_be_demoted_or_removed(client, make_user, make_workspace, login_as):
    admin = make_user("admin@x.com")
    make_workspace("a", [(admin, "admin")])
    login_as(client, admin)

    demote = client.patch(f"/api/w/a/members/{admin.id}", json={"role": "viewer"})
    remove = client.delete(f"/api/w/a/members/{admin.id}")

    assert (demote.status_code, demote.json()) == (409, {"detail": "last_admin"})
    assert (remove.status_code, remove.json()) == (409, {"detail": "last_admin"})


def test_admin_can_step_down_when_another_admin_remains(client, make_user, make_workspace, login_as):
    admin = make_user("admin@x.com")
    other = make_user("outro@x.com")
    make_workspace("a", [(admin, "admin"), (other, "admin")])
    login_as(client, admin)

    assert client.patch(f"/api/w/a/members/{other.id}", json={"role": "viewer"}).status_code == 200
    assert client.patch(f"/api/w/a/members/{other.id}", json={"role": "admin"}).status_code == 200
    assert client.delete(f"/api/w/a/members/{other.id}").status_code == 204


def test_role_change_and_removal_are_logged(caplog, client, make_user, make_workspace, login_as):
    caplog.set_level(logging.INFO)
    admin = make_user("admin@x.com")
    member = make_user("m@x.com")
    ws = make_workspace("a", [(admin, "admin"), (member, "viewer")])
    login_as(client, admin)

    client.patch(f"/api/w/a/members/{member.id}", json={"role": "analyst"})
    client.delete(f"/api/w/a/members/{member.id}")

    assert (
        f"auth.member_role_changed user_id={member.id} workspace_id={ws.id} role=analyst by={admin.id}" in caplog.text
    )
    assert f"auth.member_removed user_id={member.id} workspace_id={ws.id} by={admin.id}" in caplog.text


def test_unknown_member_is_404(client, make_user, make_workspace, login_as):
    admin = make_user("admin@x.com")
    make_workspace("a", [(admin, "admin")])
    login_as(client, admin)

    assert client.patch("/api/w/a/members/999999", json={"role": "viewer"}).status_code == 404
    assert client.delete("/api/w/a/members/999999").status_code == 404


def test_pending_password_change_blocks_workspace_routes(client, make_user, make_workspace, login_as):
    admin = make_user("admin@x.com", must_change=True)
    make_workspace("a", [(admin, "admin")])
    login_as(client, admin)

    r = client.get("/api/w/a/members")

    assert (r.status_code, r.json()) == (403, {"detail": "password_change_required"})
    assert client.get("/api/me").status_code == 200


def test_out_of_range_user_id_is_422_not_500(client, make_user, make_workspace, login_as):
    admin = make_user("admin@x.com")
    make_workspace("a", [(admin, "admin")])
    login_as(client, admin)

    for user_id in (2**63, 0):
        assert client.patch(f"/api/w/a/members/{user_id}", json={"role": "viewer"}).status_code == 422
        assert client.delete(f"/api/w/a/members/{user_id}").status_code == 422
