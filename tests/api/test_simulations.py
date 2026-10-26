import hashlib

import pytest

from api import simulations
from api.simulations import suggest_mapping
from tests.samples import INVESTMENT, MAPPING, PERFORMANCE, TRENDS, TRENDS_MAPPING


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


def upload(client, simulation_id, kind, content, filename="dados.csv", slug="a"):
    return client.put(
        f"/api/w/{slug}/simulations/{simulation_id}/files/{kind}",
        files={"file": (filename, content, "text/csv")},
    )


def test_upload_stores_file_under_its_workspace(logged, analyst, ws, make_simulation, storage_dir):
    simulation = make_simulation(ws, analyst)

    r = upload(logged, simulation.id, "investment", INVESTMENT, filename="C:\\fakepath\\investimento.csv")

    assert r.status_code == 200
    sha = hashlib.sha256(INVESTMENT).hexdigest()
    assert r.json()["files"]["investment"] | {"uploaded_at": None} == {
        "filename": "investimento.csv",
        "size_bytes": len(INVESTMENT),
        "sha256": sha,
        "columns": ["data", "canal", "investimento"],
        "suggested": {"date_col": "data", "channel_col": "canal", "investment_col": "investimento"},
        "uploaded_at": None,
    }
    assert (storage_dir / f"ws/{ws.id}/sim/{simulation.id}/inputs/{sha}.csv").read_bytes() == INVESTMENT


def test_upload_to_another_workspace_simulation_is_404(logged, analyst, make_workspace, make_simulation, storage_dir):
    foreign = make_simulation(make_workspace("b", [(analyst, "analyst")]), analyst)

    assert upload(logged, foreign.id, "investment", INVESTMENT).status_code == 404
    assert not storage_dir.exists()


def test_upload_rejects_file_over_the_limit(logged, analyst, ws, make_simulation, monkeypatch):
    monkeypatch.setattr(simulations, "MAX_UPLOAD_BYTES", 10)
    simulation = make_simulation(ws, analyst)

    r = upload(logged, simulation.id, "investment", INVESTMENT)

    assert (r.status_code, r.json()["detail"]) == (413, "Arquivo maior que 30 MB.")


@pytest.mark.parametrize(
    "filename, content, message",
    [
        ("dados.txt", INVESTMENT, "Envie um arquivo .csv."),
        ("dados.csv", b"data\n2024-01-01\n", "Não foi possível ler o cabeçalho do CSV."),
        ("dados.csv", b"", "Não foi possível ler o cabeçalho do CSV."),
        ("dados.csv", b"data,,canal\n", "Não foi possível ler o cabeçalho do CSV."),
        ("dados.csv", b"data,ca\x00nal,x\n2024-01-01,A,1\n", "Não foi possível ler o cabeçalho do CSV."),
        ("dados.csv", "data,canal,investimento\n".encode("utf-16"), "Não foi possível ler o cabeçalho do CSV."),
    ],
)
def test_upload_rejects_unreadable_file(logged, analyst, ws, make_simulation, filename, content, message):
    simulation = make_simulation(ws, analyst)

    r = upload(logged, simulation.id, "investment", content, filename=filename)

    assert (r.status_code, r.json()["detail"]) == (422, message)


def test_upload_reads_latin1_semicolon_csv(logged, analyst, ws, make_simulation):
    simulation = make_simulation(ws, analyst)
    content = "Data;Mídia;Custo\n01/01/2024;Busca;1.234,56\n".encode("latin-1")

    file = upload(logged, simulation.id, "investment", content).json()["files"]["investment"]

    assert file["columns"] == ["Data", "Mídia", "Custo"]
    assert file["suggested"] == {"date_col": "Data", "channel_col": "Mídia", "investment_col": "Custo"}


def test_reupload_replaces_the_file(logged, analyst, ws, make_simulation):
    simulation = make_simulation(ws, analyst, files={"investment": INVESTMENT})
    new = b"dia,canal,valor\n2024-01-01,SEARCH,1\n"

    body = upload(logged, simulation.id, "investment", new).json()

    assert body["files"]["investment"]["sha256"] == hashlib.sha256(new).hexdigest()
    assert body["files"]["investment"]["columns"] == ["dia", "canal", "valor"]


BOTH = {"investment": INVESTMENT, "performance": PERFORMANCE}


def put_mapping(client, simulation_id, mapping, slug="a"):
    return client.put(f"/api/w/{slug}/simulations/{simulation_id}/mapping", json=mapping)


def test_mapping_runs_the_validation(logged, analyst, ws, make_simulation):
    simulation = make_simulation(ws, analyst, files=BOTH)

    r = put_mapping(logged, simulation.id, MAPPING)

    assert r.status_code == 200
    body = r.json()
    assert body["config"] == {"column_mapping": MAPPING}
    assert body["validation"] == {
        "ok": True,
        "cadence": None,
        "period_days": None,
        "date_range": None,
        "channels": ["SEARCH", "YOUTUBE"],
        "checks": [],
        "collinearity": None,
    }


def test_mapping_rejects_unreadable_data_rows(logged, analyst, ws, make_simulation):
    huge_field = b'data,canal,investimento\n2024-01-01,SEARCH,"' + b"x" * 200_000 + b'"\n'
    simulation = make_simulation(ws, analyst, files={"investment": huge_field, "performance": PERFORMANCE})

    r = put_mapping(logged, simulation.id, MAPPING)

    assert (r.status_code, r.json()["detail"]) == (422, "Não foi possível ler o arquivo de investimento.")


def test_duplicate_date_channel_blocks_the_run(logged, analyst, ws, make_simulation):
    duplicated = INVESTMENT + b"2024-01-01,SEARCH,30\n"
    simulation = make_simulation(ws, analyst, files={"investment": duplicated, "performance": PERFORMANCE})

    validation = put_mapping(logged, simulation.id, MAPPING).json()["validation"]

    assert validation["ok"] is False
    assert validation["checks"] == [
        {
            "id": "duplicate_date_channel",
            "level": "error",
            "message": "1 linha repetida de (data, canal) no investimento",
            "details": {"rows": [{"date": "2024-01-01", "channel": "SEARCH", "count": 2}]},
        }
    ]


def test_mapping_with_trends(logged, analyst, ws, make_simulation):
    simulation = make_simulation(ws, analyst, files=BOTH | {"trends": TRENDS})
    mapping = MAPPING | {"generic_trends_file": TRENDS_MAPPING}

    r = put_mapping(logged, simulation.id, mapping)

    assert r.status_code == 200
    assert r.json()["config"]["column_mapping"] == mapping


@pytest.mark.parametrize(
    "files, mapping, message",
    [
        ({"investment": INVESTMENT}, MAPPING, "Envie investimento e performance antes de validar."),
        (
            BOTH,
            MAPPING | {"generic_trends_file": TRENDS_MAPPING},
            "Envie o arquivo de trends antes de mapeá-lo.",
        ),
        (BOTH | {"trends": TRENDS}, MAPPING, "Mapeie as colunas do arquivo de trends."),
        (
            BOTH,
            MAPPING | {"investment_file": MAPPING["investment_file"] | {"date_col": "dia"}},
            "Coluna 'dia' não existe no arquivo de investimento.",
        ),
    ],
)
def test_mapping_rejects_inconsistent_input(logged, analyst, ws, make_simulation, files, mapping, message):
    simulation = make_simulation(ws, analyst, files=files)

    r = put_mapping(logged, simulation.id, mapping)

    assert (r.status_code, r.json()["detail"]) == (422, message)


def test_mapping_of_another_workspace_simulation_is_404(logged, analyst, make_workspace, make_simulation):
    foreign = make_simulation(make_workspace("b", [(analyst, "analyst")]), analyst, files=BOTH)

    assert put_mapping(logged, foreign.id, MAPPING).status_code == 404


def test_reupload_clears_the_validation(logged, analyst, ws, make_simulation):
    simulation = make_simulation(ws, analyst, files=BOTH)
    put_mapping(logged, simulation.id, MAPPING)

    body = upload(logged, simulation.id, "investment", INVESTMENT).json()

    assert body["validation"] is None
    assert body["config"] == {"column_mapping": MAPPING}
