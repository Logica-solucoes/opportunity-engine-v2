import threading
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select

from api import auth, passwords
from api.db import SessionLocal
from api.models import User, UserSession

NEW_PASSWORD = "uma-senha-nova-longa"


def freeze(monkeypatch, at):
    monkeypatch.setattr(auth, "now", lambda: at)


def session_count(db):
    return db.scalar(select(func.count()).select_from(UserSession))


def test_login_sets_hardened_cookie_and_returns_me(client, make_user, password):
    user = make_user("ana@x.com")

    r = client.post("/api/auth/login", json={"email": "  ANA@x.com ", "password": password})

    assert r.status_code == 200
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("gem_session=")
    for flag in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"):
        assert flag in cookie
    assert "Max-Age" not in cookie and "expires" not in cookie.lower()
    assert r.json() == {
        "id": user.id,
        "email": "ana@x.com",
        "name": "ana",
        "is_platform_admin": False,
        "must_change_password": False,
        "workspaces": [],
    }


def test_session_stores_only_the_token_hash(client, db, make_user, login_as):
    login_as(client, make_user("ana@x.com"))
    token = client.cookies["gem_session"]

    row = db.scalars(select(UserSession)).one()

    assert row.token_hash == auth.hash_token(token)


def test_me_lists_memberships(client, make_user, make_workspace, login_as):
    user = make_user("ana@x.com")
    make_workspace("beta", [(user, "viewer")])
    make_workspace("alfa", [(user, "analyst")])
    make_workspace("outro")
    login_as(client, user)

    assert client.get("/api/me").json()["workspaces"] == [
        {"slug": "alfa", "name": "ALFA", "role": "analyst"},
        {"slug": "beta", "name": "BETA", "role": "viewer"},
    ]


def test_no_cookie_is_401(client):
    r = client.get("/api/me")
    assert (r.status_code, r.json()) == (401, {"detail": "not_authenticated"})


def test_random_or_truncated_cookie_is_401(client, make_client, make_user, login_as):
    login_as(client, make_user("ana@x.com"))
    token = client.cookies["gem_session"]

    # fresh client + explicit header: the jar stores the cookie under "testserver.local", so cookies.set would duplicate it
    for forged in ("abc", token[:-1], token + "x"):
        r = make_client().get("/api/me", headers={"Cookie": f"gem_session={forged}"})
        assert (r.status_code, r.json()) == (401, {"detail": "not_authenticated"}), forged


def test_idle_session_expires_after_8h(client, db, make_user, login_as, monkeypatch):
    t0 = datetime.now(UTC)
    login_as(client, make_user("ana@x.com"))

    freeze(monkeypatch, t0 + timedelta(hours=8, minutes=1))

    assert client.get("/api/me").status_code == 401
    assert session_count(db) == 0


def test_session_dies_after_7d_even_if_active(client, db, make_user, login_as, monkeypatch):
    t0 = datetime.now(UTC)
    login_as(client, make_user("ana@x.com"))
    later = t0 + timedelta(days=7, minutes=1)
    db.scalars(select(UserSession)).one().last_seen_at = later - timedelta(minutes=1)
    db.flush()

    freeze(monkeypatch, later)

    assert client.get("/api/me").status_code == 401


def test_activity_slides_the_idle_window(client, db, make_user, login_as, monkeypatch):
    t0 = datetime.now(UTC)
    login_as(client, make_user("ana@x.com"))

    freeze(monkeypatch, t0 + timedelta(hours=7))
    assert client.get("/api/me").status_code == 200
    freeze(monkeypatch, t0 + timedelta(hours=14))
    assert client.get("/api/me").status_code == 200


def test_wrong_password_unknown_email_and_inactive_look_the_same(client, make_user, password):
    make_user("ana@x.com")
    make_user("off@x.com", active=False)

    bodies = [
        {"email": "ana@x.com", "password": "errada-errada"},
        {"email": "ninguem@x.com", "password": password},
        {"email": "off@x.com", "password": password},
    ]
    for body in bodies:
        r = client.post("/api/auth/login", json=body)
        assert (r.status_code, r.json()) == (401, {"detail": "invalid_credentials"}), body


def test_fifth_failure_locks_for_15_min(client, make_user, password, monkeypatch):
    make_user("ana@x.com")
    t0 = datetime.now(UTC)
    freeze(monkeypatch, t0)
    wrong = {"email": "ana@x.com", "password": "errada-errada"}

    for _ in range(5):
        assert client.post("/api/auth/login", json=wrong).status_code == 401

    r = client.post("/api/auth/login", json={"email": "ana@x.com", "password": password})
    assert r.status_code == 429
    assert r.json() == {"detail": "locked", "retry_after_s": 900}

    freeze(monkeypatch, t0 + timedelta(minutes=15, seconds=1))
    assert client.post("/api/auth/login", json={"email": "ana@x.com", "password": password}).status_code == 200


def test_parallel_wrong_guesses_still_lock(schema, password):
    attempts = 10
    with SessionLocal() as setup:
        setup.add(User(email="race@x.com", name="race", password_hash=passwords.hash_password(password)))
        setup.commit()
    barrier = threading.Barrier(attempts)
    results = []

    def guess(i):
        with SessionLocal() as session:
            barrier.wait()
            try:
                auth.authenticate(session, "race@x.com", f"errada-{i}")
            except auth.InvalidCredentials:
                results.append("invalid")
            except auth.AccountLocked:
                results.append("locked")

    try:
        threads = [threading.Thread(target=guess, args=(i,)) for i in range(attempts)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        with SessionLocal() as check:
            locked_until = check.scalar(select(User.locked_until).where(User.email == "race@x.com"))
    finally:
        with SessionLocal() as cleanup:
            cleanup.execute(delete(User).where(User.email == "race@x.com"))
            cleanup.commit()

    assert len(results) == attempts
    assert locked_until is not None
    assert results.count("invalid") <= auth.MAX_FAILED_LOGINS


def test_success_resets_the_failure_counter(client, make_user, password):
    make_user("ana@x.com")
    wrong = {"email": "ana@x.com", "password": "errada-errada"}
    right = {"email": "ana@x.com", "password": password}

    for _ in range(4):
        client.post("/api/auth/login", json=wrong)
    assert client.post("/api/auth/login", json=right).status_code == 200
    for _ in range(4):
        client.post("/api/auth/login", json=wrong)

    assert client.post("/api/auth/login", json=right).status_code == 200


def test_logout_kills_the_session(client, make_client, db, make_user, login_as):
    login_as(client, make_user("ana@x.com"))
    token = client.cookies["gem_session"]

    r = client.post("/api/auth/logout")

    assert r.status_code == 204
    assert 'gem_session=""' in r.headers["set-cookie"] or "Max-Age=0" in r.headers["set-cookie"]
    assert session_count(db) == 0
    assert make_client().get("/api/me", headers={"Cookie": f"gem_session={token}"}).status_code == 401


def test_change_password_keeps_current_session_and_kills_others(
    make_client, make_user, login_as, password
):
    user = make_user("ana@x.com", must_change=True)
    here, elsewhere = make_client(), make_client()
    login_as(here, user)
    login_as(elsewhere, user)

    r = here.post("/api/auth/password", json={"current": password, "new": NEW_PASSWORD})

    assert r.status_code == 204
    assert here.get("/api/me").json()["must_change_password"] is False
    assert elsewhere.get("/api/me").status_code == 401
    fresh = make_client()
    login_as(fresh, user, NEW_PASSWORD)


def test_change_password_rejects_bad_input(client, make_user, login_as, password):
    login_as(client, make_user("ana@x.com"))

    wrong_current = client.post("/api/auth/password", json={"current": "nao-e-essa", "new": NEW_PASSWORD})
    same = client.post("/api/auth/password", json={"current": password, "new": password})
    short = client.post("/api/auth/password", json={"current": password, "new": "curta"})

    assert (wrong_current.status_code, wrong_current.json()) == (400, {"detail": "invalid_current_password"})
    assert (same.status_code, same.json()) == (422, {"detail": "password_unchanged"})
    assert short.status_code == 422


def test_wrong_current_password_counts_toward_lockout(client, make_user, login_as, password, monkeypatch):
    login_as(client, make_user("ana@x.com"))
    t0 = datetime.now(UTC)
    freeze(monkeypatch, t0)
    wrong = {"current": "nao-e-essa", "new": NEW_PASSWORD}
    right = {"current": password, "new": NEW_PASSWORD}

    for _ in range(5):
        assert client.post("/api/auth/password", json=wrong).status_code == 400

    r = client.post("/api/auth/password", json=right)
    assert (r.status_code, r.json()) == (429, {"detail": "locked", "retry_after_s": 900})
    assert client.get("/api/me").status_code == 200

    freeze(monkeypatch, t0 + timedelta(minutes=15, seconds=1))
    assert client.post("/api/auth/password", json=right).status_code == 204


def test_successful_password_change_resets_the_failure_counter(client, db, make_user, login_as, password):
    user = make_user("ana@x.com")
    login_as(client, user)

    for _ in range(4):
        client.post("/api/auth/password", json={"current": "nao-e-essa", "new": NEW_PASSWORD})
    assert client.post("/api/auth/password", json={"current": password, "new": NEW_PASSWORD}).status_code == 204

    db.refresh(user)
    assert (user.failed_logins, user.locked_until) == (0, None)


def test_foreign_origin_on_mutation_is_403(client, make_user, password):
    make_user("ana@x.com")
    body = {"email": "ana@x.com", "password": password}

    evil = client.post("/api/auth/login", json=body, headers={"Origin": "https://evil.example"})
    same = client.post("/api/auth/login", json=body, headers={"Origin": "https://testserver"})
    get = client.get("/api/me", headers={"Origin": "https://evil.example"})

    assert (evil.status_code, evil.json()) == (403, {"detail": "bad_origin"})
    assert same.status_code == 200
    assert get.status_code == 200
