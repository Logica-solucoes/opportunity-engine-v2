import pytest
from sqlalchemy import func

from api import runs, simulations
from api.auth import RANK
from api.engine_config import ParamsIn
from tests.samples import INVESTMENT, MAPPING, PERFORMANCE

PUBLIC, SESSION, PLATFORM = "public", "session", "platform"
ACTORS = ["anon", "viewer", "analyst", "admin", "platform"]

# (method, path) -> (minimum, success status, body builder). Every /api route must be here.
ROUTES = {
    ("POST", "/api/auth/login"): (PUBLIC, 200, lambda e: {"email": e["target"].email, "password": e["password"]}),
    ("POST", "/api/auth/logout"): (SESSION, 204, None),
    ("POST", "/api/auth/password"): (SESSION, 204, lambda e: {"current": e["password"], "new": "outra-senha-longa"}),
    ("GET", "/api/me"): (SESSION, 200, None),
    ("GET", "/api/w/{slug}/members"): ("admin", 200, None),
    ("POST", "/api/w/{slug}/members"): ("admin", 201, lambda e: {"email": "fora@x.com", "role": "viewer"}),
    ("PATCH", "/api/w/{slug}/members/{user_id}"): ("admin", 200, lambda e: {"role": "analyst"}),
    ("DELETE", "/api/w/{slug}/members/{user_id}"): ("admin", 204, None),
    ("GET", "/api/w/{slug}/simulations"): ("analyst", 200, None),
    ("POST", "/api/w/{slug}/simulations"): ("analyst", 201, lambda e: {"name": "Nova"}),
    ("GET", "/api/w/{slug}/simulations/{simulation_id}"): ("analyst", 200, None),
    ("PUT", "/api/w/{slug}/simulations/{simulation_id}/files/{kind}"): (
        "analyst",
        200,
        lambda e: Files(file=("investimento.csv", INVESTMENT, "text/csv")),
    ),
    ("PUT", "/api/w/{slug}/simulations/{simulation_id}/mapping"): ("analyst", 200, lambda e: MAPPING),
    ("GET", "/api/w/{slug}/simulations/{simulation_id}/suggestions"): ("analyst", 200, None),
    ("POST", "/api/w/{slug}/simulations/{simulation_id}/suggestions/gemini"): ("analyst", 200, None),
    ("PUT", "/api/w/{slug}/simulations/{simulation_id}/params"): ("analyst", 200, lambda e: {}),
    ("POST", "/api/w/{slug}/simulations/{simulation_id}/runs"): ("analyst", 201, lambda e: {"confirmed_warnings": []}),
    ("GET", "/api/w/{slug}/simulations/{simulation_id}/runs"): ("viewer", 200, None),
    ("GET", "/api/w/{slug}/runs/{run_id}"): ("viewer", 200, None),
    ("GET", "/api/w/{slug}/runs/{run_id}/logs/stream"): ("viewer", 200, None),
    ("GET", "/api/engine/config-schema"): (SESSION, 200, None),
    ("GET", "/api/admin/workspaces"): (PLATFORM, 200, None),
    ("POST", "/api/admin/workspaces"): (PLATFORM, 201, lambda e: {"name": "Nova", "slug": "nova"}),
    ("GET", "/api/admin/users"): (PLATFORM, 200, None),
    ("POST", "/api/admin/users/{user_id}/reset-password"): (PLATFORM, 200, None),
    ("PATCH", "/api/admin/users/{user_id}"): (PLATFORM, 200, lambda e: {"active": False}),
}
UNSCOPED = {("GET", "/api/health")}


class Files(dict):
    """multipart body: sent as client.request(files=...) instead of json="""


def expected_status(minimum, ok, actor):
    if minimum == PUBLIC:
        return ok
    if actor == "anon":
        return 401
    if minimum == SESSION:
        return ok
    if minimum == PLATFORM:
        return ok if actor == "platform" else 403
    return ok if actor == "platform" or RANK[actor] >= RANK[minimum] else 403


@pytest.fixture
def env(db, stream_db, make_user, make_workspace, make_simulation, password):
    users = {role: make_user(f"{role}@x.com") for role in ("viewer", "analyst", "admin")}
    users["platform"] = make_user("platform@x.com", platform=True)
    target = make_user("target@x.com")
    make_user("fora@x.com")
    ws = make_workspace("a", [(users[r], r) for r in ("viewer", "analyst", "admin")] + [(target, "viewer")])
    simulation = make_simulation(ws, users["analyst"], files={"investment": INVESTMENT, "performance": PERFORMANCE})
    simulations.save_mapping(db, simulation, MAPPING)
    simulations.save_params(db, simulation, ParamsIn().model_dump(mode="json"))
    run = runs.create(db, simulation, set(), by=users["analyst"])
    run.status, run.published_at = "succeeded", func.now()
    db.commit()
    return {"users": users, "target": target, "password": password, "simulation": simulation, "run": run}


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("route", list(ROUTES), ids=lambda r: f"{r[0]} {r[1]}")
def test_role_matrix(route, actor, client, env, login_as):
    minimum, ok, body = ROUTES[route]
    if actor != "anon":
        login_as(client, env["users"][actor])
    method, template = route
    path = template.format(
        slug="a",
        user_id=env["target"].id,
        simulation_id=env["simulation"].id,
        run_id=env["run"].id,
        kind="investment",
    )
    payload = body(env) if body else None

    if isinstance(payload, Files):
        r = client.request(method, path, files=payload)
    else:
        r = client.request(method, path, json=payload)

    assert r.status_code == expected_status(minimum, ok, actor), r.text


def test_matrix_covers_every_api_route(app):
    # a route with include_in_schema=False escapes this check.
    # app.routes only holds lazy _IncludedRouter entries on fastapi >= 0.158; the schema lists the flattened routes
    found = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api/")
        for method in operations
    }
    assert found - UNSCOPED == set(ROUTES)


def test_other_workspace_looks_like_it_does_not_exist(client, make_user, make_workspace, login_as):
    admin = make_user("admin@a.com")
    stranger = make_user("membro@b.com")
    make_workspace("a", [(admin, "admin")])
    make_workspace("b", [(stranger, "viewer")])
    login_as(client, admin)
    missing = client.get("/api/w/nao-existe/members")
    assert missing.status_code == 404

    calls = [
        ("GET", "/api/w/b/members", None),
        ("POST", "/api/w/b/members", {"email": "admin@a.com", "role": "viewer"}),
        ("PATCH", f"/api/w/b/members/{stranger.id}", {"role": "admin"}),
        ("DELETE", f"/api/w/b/members/{stranger.id}", None),
        ("PATCH", f"/api/w/a/members/{stranger.id}", {"role": "admin"}),
    ]
    for method, path, body in calls:
        r = client.request(method, path, json=body)
        assert (r.status_code, r.json()) == (404, missing.json()), (method, path)
