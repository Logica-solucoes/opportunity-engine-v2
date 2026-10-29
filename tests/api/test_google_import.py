from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from api import google_import, simulations
from api.google_import import Ga4Config, GoogleConfig, Period
from tests.samples import ADS_ROWS, GA4_ROWS, GOOGLE_CONFIG

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
