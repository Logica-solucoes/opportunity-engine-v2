from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from api import bigquery, google_import, simulations
from api.google_import import Ga4Config, GoogleConfig, Period
from tests.samples import (
    ADS_ROWS,
    GA4_ROWS,
    GOOGLE_CONFIG,
    GOOGLE_PERIOD,
    INVESTMENT,
    MAPPING,
    PERFORMANCE,
    TRENDS,
    TRENDS_MAPPING,
)

PERIOD = Period(start=date(2026, 1, 1), end=date(2026, 1, 3))


def test_investment_csv_fills_every_day_and_channel_with_zero():
    content, channels = google_import.investment_csv(ADS_ROWS, PERIOD)

    assert channels == ["DISPLAY", "SEARCH", "YOUTUBE"]
    assert content.decode() == (
        "data,canal,investimento\n"
        "2026-01-01,DISPLAY,0.0\n2026-01-01,SEARCH,100.0\n2026-01-01,YOUTUBE,50.5\n"
        "2026-01-02,DISPLAY,0.0\n2026-01-02,SEARCH,120.0\n2026-01-02,YOUTUBE,0.0\n"
        "2026-01-03,DISPLAY,10.0\n2026-01-03,SEARCH,0.0\n2026-01-03,YOUTUBE,0.0\n"
    )


def test_investment_csv_maps_fixed_channels_and_keeps_the_rest_by_name():
    rows = [
        {"date": date(2026, 1, 1), "channel_type": t, "spend": 1.0}
        for t in ("SEARCH", "PERFORMANCE_MAX", "VIDEO", "DEMAND_GEN", "SHOPPING", None)
    ]

    _, channels = google_import.investment_csv(rows, Period(start=date(2026, 1, 1), end=date(2026, 1, 1)))

    assert channels == ["DEMAND_GEN", "PMAX", "SEARCH", "SHOPPING", "UNKNOWN", "YOUTUBE"]


def test_investment_csv_sums_rows_that_land_on_the_same_day_and_channel():
    rows = [{"date": date(2026, 1, 1), "channel_type": "SEARCH", "spend": 0.1}] * 3

    content, _ = google_import.investment_csv(rows, Period(start=date(2026, 1, 1), end=date(2026, 1, 1)))

    assert content.decode().splitlines()[1] == "2026-01-01,SEARCH,0.3"


@pytest.mark.parametrize("rows", [[], [{"date": date(2026, 1, 1), "channel_type": "SEARCH", "spend": 0.0}]])
def test_investment_csv_without_spend_is_invalid(rows):
    with pytest.raises(simulations.InvalidInput, match="Nenhum investimento no Google Ads neste período."):
        google_import.investment_csv(rows, PERIOD)


def test_performance_csv_fills_missing_days_and_null_revenue_with_zero():
    rows = [*GA4_ROWS, {"date": date(2026, 1, 2), "kpi": None}]

    content = google_import.performance_csv(rows, PERIOD, "purchase")

    assert content.decode() == "data,kpi\n2026-01-01,10\n2026-01-02,0\n2026-01-03,12\n"


def test_performance_csv_without_events_is_invalid():
    with pytest.raises(simulations.InvalidInput, match="Nenhum evento 'purchase' no GA4 neste período."):
        google_import.performance_csv([], PERIOD, "purchase")


def test_ads_sql_reads_each_account_and_keeps_dates_as_params():
    sql = google_import.ads_sql(GoogleConfig.model_validate(GOOGLE_CONFIG).ads)

    for cid in ("1111111111", "2222222222"):
        assert f"`proj-teste.google_ads.ads_CampaignBasicStats_{cid}`" in sql
        assert f"`proj-teste.google_ads.ads_Campaign_{cid}`" in sql
    assert sql.count("UNION ALL") == 1
    assert "c._DATA_DATE = c._LATEST_DATE" in sql
    assert "2026" not in sql and "@start" in sql and "@end" in sql


@pytest.mark.parametrize(
    ("metric", "expression"), [("count", "COUNT(*)"), ("revenue", "SUM(ecommerce.purchase_revenue)")]
)
def test_ga4_sql_picks_the_metric_and_keeps_the_event_as_param(metric, expression):
    sql = google_import.ga4_sql(Ga4Config(dataset="proj-teste.analytics_123", event="purchase", metric=metric))

    assert "`proj-teste.analytics_123.events_*`" in sql
    assert expression in sql
    assert "purchase'" not in sql and "@event" in sql and "@start_suffix" in sql


@pytest.mark.parametrize(
    "change",
    [
        {"ads": {"dataset": "proj-teste.ds`; DROP TABLE x; --", "customer_ids": ["1111111111"]}},
        {"ads": {"dataset": "proj-teste.ds x", "customer_ids": ["1111111111"]}},
        {"ads": {"dataset": "semponto", "customer_ids": ["1111111111"]}},
        {"ads": {"dataset": "proj-teste.ds", "customer_ids": ["123-456-7890"]}},
        {"ads": {"dataset": "proj-teste.ds", "customer_ids": ["abcdefghij"]}},
        {"ads": {"dataset": "proj-teste.ds", "customer_ids": []}},
        {"ads": {"dataset": "proj-teste.ds", "customer_ids": ["1111111111", "1111111111"]}},
        {"ads": {"dataset": "proj-teste.ds", "customer_ids": [str(1000000000 + n) for n in range(21)]}},
        {"ga4": {"dataset": "proj-teste.a", "event": "1compra", "metric": "count"}},
        {"ga4": {"dataset": "proj-teste.a", "event": "compra'--", "metric": "count"}},
        {"ga4": {"dataset": "proj-teste.a", "event": "purchase", "metric": "sum"}},
    ],
)
def test_google_config_rejects_anything_that_could_reach_the_sql(change):
    with pytest.raises(ValidationError):
        GoogleConfig.model_validate({**GOOGLE_CONFIG, **change})


def test_period_rules():
    today = google_import.today()
    Period(start=today - timedelta(days=1095), end=today)

    for start, end in [
        (date(2026, 1, 3), date(2026, 1, 1)),
        (today, today + timedelta(days=1)),
        (today - timedelta(days=1096), today),
    ]:
        with pytest.raises(ValidationError):
            Period(start=start, end=end)


@pytest.fixture
def ana(make_user):
    return make_user("ana@x.com")


@pytest.fixture
def ws(db, ana, make_workspace):
    workspace = make_workspace("a", [(ana, "analyst")])
    workspace.settings = {"google": GOOGLE_CONFIG}
    db.flush()
    return workspace


@pytest.fixture
def logged(client, ana, login_as):
    login_as(client, ana)
    return client


@pytest.fixture
def sim(ws, ana, make_simulation):
    return make_simulation(ws, ana)


def url(simulation):
    return f"/api/w/a/simulations/{simulation.id}/google-import"


def test_import_writes_mapped_and_validated_canonical_files(logged, sim, fake_bigquery, db):
    r = logged.post(url(sim), json=GOOGLE_PERIOD)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["files"]["investment"]["filename"] == "google-ads_2026-01-01_2026-01-03.csv"
    assert body["files"]["performance"]["filename"] == "ga4-purchase-count_2026-01-01_2026-01-03.csv"
    assert body["config"]["column_mapping"] == google_import.FIXED_MAPPING
    assert body["validation"]["ok"] is True
    assert body["validation"]["channels"] == ["DISPLAY", "SEARCH", "YOUTUBE"]
    db.refresh(sim)
    paths = simulations.input_paths(sim)
    assert paths["investment_file"].read_text().splitlines()[1] == "2026-01-01,DISPLAY,0.0"
    assert paths["performance_file"].read_text() == "data,kpi\n2026-01-01,10\n2026-01-02,0\n2026-01-03,12\n"


def test_import_sends_dates_and_event_as_params(logged, sim, fake_bigquery):
    logged.post(url(sim), json=GOOGLE_PERIOD)

    (ads_sql, ads_params), (ga4_sql, ga4_params) = fake_bigquery.calls
    assert "`proj-teste.google_ads.ads_CampaignBasicStats_2222222222`" in ads_sql
    assert ads_params == {"start": date(2026, 1, 1), "end": date(2026, 1, 3)}
    assert "`proj-teste.analytics_123.events_*`" in ga4_sql
    assert ga4_params == {"start_suffix": "20260101", "end_suffix": "20260103", "event": "purchase"}


def test_import_replaces_uploads_and_keeps_the_trends_mapping(logged, ws, ana, make_simulation, fake_bigquery, db):
    files = {"investment": INVESTMENT, "performance": PERFORMANCE, "trends": TRENDS}
    simulation = make_simulation(ws, ana, files=files)
    simulations.save_mapping(db, simulation, {**MAPPING, "generic_trends_file": TRENDS_MAPPING})

    r = logged.post(url(simulation), json=GOOGLE_PERIOD)

    assert r.status_code == 200, r.text
    assert r.json()["config"]["column_mapping"] == {
        **google_import.FIXED_MAPPING,
        "generic_trends_file": TRENDS_MAPPING,
    }
    assert r.json()["files"]["trends"]["filename"] == "trends.csv"


def test_import_without_spend_saves_nothing(logged, sim, fake_bigquery):
    fake_bigquery.answers["ads"] = []

    r = logged.post(url(sim), json=GOOGLE_PERIOD)

    assert r.status_code == 422
    assert r.json()["detail"] == "Nenhum investimento no Google Ads neste período."
    assert logged.get(f"/api/w/a/simulations/{sim.id}").json()["files"]["investment"] is None


def test_import_without_events_is_422(logged, sim, fake_bigquery):
    fake_bigquery.answers["ga4"] = []

    r = logged.post(url(sim), json=GOOGLE_PERIOD)

    assert (r.status_code, r.json()["detail"]) == (422, "Nenhum evento 'purchase' no GA4 neste período.")


def test_import_without_connector_is_409(logged, sim, ws, db, fake_bigquery):
    ws.settings = {}
    db.flush()

    r = logged.post(url(sim), json=GOOGLE_PERIOD)

    assert (r.status_code, r.json()["detail"]) == (409, "Workspace sem conector Google configurado.")
    assert fake_bigquery.calls == []


def test_tampered_config_never_reaches_bigquery(logged, sim, ws, db, fake_bigquery):
    ws.settings = {"google": {**GOOGLE_CONFIG, "ga4": {**GOOGLE_CONFIG["ga4"], "dataset": "x.y` OR 1=1 --"}}}
    db.flush()

    assert logged.post(url(sim), json=GOOGLE_PERIOD).status_code == 409
    assert fake_bigquery.calls == []


@pytest.mark.parametrize(
    "period",
    [
        {"start": "2026-01-03", "end": "2026-01-01"},
        {"start": "2026-01-01", "end": "2999-01-01"},
        {"start": "2020-01-01", "end": "2023-01-01"},
        {"start": "ontem", "end": "2026-01-01"},
    ],
)
def test_import_rejects_bad_periods(logged, sim, fake_bigquery, period):
    assert logged.post(url(sim), json=period).status_code == 422
    assert fake_bigquery.calls == []


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (
            bigquery.NoAccess,
            "A service account não tem acesso ao dataset ou a tabela não existe: proj-teste.google_ads.",
        ),
        (bigquery.NoCredentials, "Conector Google sem credenciais neste ambiente."),
        (bigquery.Failed, "Não foi possível consultar o BigQuery."),
    ],
)
def test_bigquery_errors_are_502_with_a_message(logged, sim, monkeypatch, error, message):
    def query(sql, params):
        raise error

    monkeypatch.setattr(bigquery, "query", query)

    r = logged.post(url(sim), json=GOOGLE_PERIOD)

    assert (r.status_code, r.json()["detail"]) == (502, message)


def test_simulation_of_another_workspace_is_404(logged, db, make_user, make_workspace, make_simulation, fake_bigquery):
    owner = make_user("bia@x.com")
    other = make_workspace("b", [(owner, "admin")])
    other.settings = {"google": GOOGLE_CONFIG}
    db.flush()
    foreign = make_simulation(other, owner)

    assert logged.post(f"/api/w/a/simulations/{foreign.id}/google-import", json=GOOGLE_PERIOD).status_code == 404
    assert logged.post(f"/api/w/b/simulations/{foreign.id}/google-import", json=GOOGLE_PERIOD).status_code == 404
