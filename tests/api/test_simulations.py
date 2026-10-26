import pytest

from api.simulations import suggest_mapping


@pytest.fixture
def analyst(make_user):
    return make_user("ana@x.com")


@pytest.fixture
def ws(make_workspace, analyst):
    return make_workspace("a", [(analyst, "analyst")])


@pytest.fixture
def logged(client, analyst, ws, login_as):
    login_as(client, analyst)
    return client


def test_create_simulation_starts_empty(logged):
    r = logged.post("/api/w/a/simulations", json={"name": "  Black Friday  "})

    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Black Friday"
    assert body["config"] == {} and body["validation"] is None
    assert body["files"] == {"investment": None, "performance": None, "trends": None}
    assert logged.get(f"/api/w/a/simulations/{body['id']}").json() == body


def test_create_rejects_blank_name(logged):
    assert logged.post("/api/w/a/simulations", json={"name": "   "}).status_code == 422


def test_list_is_scoped_and_newest_first(logged, analyst, ws, make_workspace, make_simulation):
    other = make_workspace("b", [(analyst, "analyst")])
    make_simulation(ws, analyst, "Primeira")
    newest = make_simulation(ws, analyst, "Segunda")
    make_simulation(other, analyst, "De outro workspace")

    body = logged.get("/api/w/a/simulations").json()

    assert [s["name"] for s in body] == ["Segunda", "Primeira"]
    assert body[0]["id"] == newest.id and body[0]["created_by_name"] == "ana"


def test_simulation_of_another_workspace_is_404(logged, analyst, make_workspace, make_simulation):
    foreign = make_simulation(make_workspace("b", [(analyst, "analyst")]), analyst)

    assert logged.get(f"/api/w/a/simulations/{foreign.id}").status_code == 404
    assert logged.get(f"/api/w/b/simulations/{foreign.id}").status_code == 200


@pytest.mark.parametrize(
    "kind, columns, expected",
    [
        (
            "investment",
            ["data", "canal", "investimento"],
            {"date_col": "data", "channel_col": "canal", "investment_col": "investimento"},
        ),
        (
            "investment",
            ["Date", "Channel", "Spend"],
            {"date_col": "Date", "channel_col": "Channel", "investment_col": "Spend"},
        ),
        (
            "investment",
            ["Data", "Mídia", "Custo Total"],
            {"date_col": "Data", "channel_col": "Mídia", "investment_col": "Custo Total"},
        ),
        ("investment", ["x", "y"], {"date_col": None, "channel_col": None, "investment_col": None}),
        ("performance", ["data", "conversoes"], {"date_col": "data", "kpi_col": "conversoes"}),
        ("performance", ["receita", "Dia"], {"date_col": "Dia", "kpi_col": "receita"}),
        ("trends", ["data", "trends"], {"date_col": "data", "trends_col": "trends"}),
    ],
)
def test_suggest_mapping(kind, columns, expected):
    assert suggest_mapping(kind, columns) == expected
