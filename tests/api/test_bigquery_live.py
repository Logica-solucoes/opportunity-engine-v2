import os
from datetime import date
from pathlib import Path

import pytest

from api import bigquery, google_import
from api.google_import import AdsConfig, Ga4Config, Period

PROJECT = os.environ.get("BIGQUERY_TEST_PROJECT")
SEED = Path(__file__).resolve().parents[1] / "bigquery" / "seed_ads.sql"
GA4_SAMPLE = "bigquery-public-data.ga4_obfuscated_sample_ecommerce"

pytestmark = pytest.mark.skipif(not PROJECT, reason="BIGQUERY_TEST_PROJECT não definido")


@pytest.fixture(scope="module", autouse=True)
def billing_project():
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GOOGLE_CLOUD_PROJECT", PROJECT)
        yield


@pytest.fixture(scope="module")
def ads_dataset():
    bigquery.query(SEED.read_text(encoding="utf-8"), {})
    return f"{PROJECT}.b8_ads_seed"


def test_ads_sql_sums_accounts_and_uses_the_latest_campaign_type(ads_dataset):
    period = Period(start=date(2026, 1, 2), end=date(2026, 1, 4))
    config = AdsConfig(dataset=ads_dataset, customer_ids=["1111111111", "2222222222"])

    rows = google_import.fetch(ads_dataset, google_import.ads_sql(config), {"start": period.start, "end": period.end})
    content, channels = google_import.investment_csv(rows, period)

    # campaign 4 counts as DEMAND_GEN (latest snapshot) and only once (one snapshot joined), never as YOUTUBE
    assert channels == ["DEMAND_GEN", "DISPLAY", "PMAX", "SEARCH"]
    assert content.decode().splitlines()[1:5] == [
        "2026-01-02,DEMAND_GEN,3.0",
        "2026-01-02,DISPLAY,0.5",
        "2026-01-02,PMAX,2.0",
        "2026-01-02,SEARCH,5.0",
    ]
    assert len(content.decode().splitlines()) == 1 + 3 * 4


@pytest.mark.parametrize("metric", ["count", "revenue"])
def test_ga4_sql_runs_against_a_real_export(metric):
    period = Period(start=date(2020, 11, 1), end=date(2020, 11, 7))
    config = Ga4Config(dataset=GA4_SAMPLE, event="purchase", metric=metric)
    params = {"start_suffix": "20201101", "end_suffix": "20201107", "event": "purchase"}

    rows = google_import.fetch(GA4_SAMPLE, google_import.ga4_sql(config), params)

    assert sorted(r["date"] for r in rows) == period.days()
    assert all(r["kpi"] > 0 for r in rows)
