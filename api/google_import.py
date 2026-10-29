import csv
import io
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import AfterValidator, BaseModel, Field, StringConstraints, model_validator

from api import simulations

log = logging.getLogger(__name__)

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
MAX_DAYS = 1096

# advertising_channel_type -> channel; any other type keeps its own name so no spend is dropped
CHANNELS = {"SEARCH": "SEARCH", "PERFORMANCE_MAX": "PMAX", "VIDEO": "YOUTUBE", "DEMAND_GEN": "DEMAND_GEN"}
METRICS = {"count": "COUNT(*)", "revenue": "SUM(ecommerce.purchase_revenue)"}


def unique(ids: list[str]) -> list[str]:
    if len(set(ids)) != len(ids):
        raise ValueError("customer id repetido")
    return ids


# `project.dataset`. Table names can't be query parameters: this pattern is what keeps the SQL safe
Dataset = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{4,28}[a-z0-9]\.[A-Za-z0-9_]{1,1024}$")]
CustomerId = Annotated[str, StringConstraints(pattern=r"^[0-9]{10}$")]


class AdsConfig(BaseModel):
    dataset: Dataset
    customer_ids: Annotated[list[CustomerId], Field(min_length=1, max_length=20), AfterValidator(unique)]


class Ga4Config(BaseModel):
    dataset: Dataset
    event: Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,39}$")]
    metric: Literal["count", "revenue"]


class GoogleConfig(BaseModel):
    ads: AdsConfig
    ga4: Ga4Config


def today() -> date:
    return datetime.now(SAO_PAULO).date()


class Period(BaseModel):
    start: date
    end: date

    @model_validator(mode="after")
    def check(self):
        if self.start > self.end:
            raise ValueError("O início vem antes do fim.")
        if self.end > today():
            raise ValueError("O fim não pode estar no futuro.")
        if (self.end - self.start).days >= MAX_DAYS:
            raise ValueError("O período vai até 3 anos.")
        return self

    def days(self) -> list[date]:
        return [self.start + timedelta(days=n) for n in range((self.end - self.start).days + 1)]


def ads_sql(config: AdsConfig) -> str:
    # _DATA_DATE prunes the partitions; the outer date filter keeps a backfilled row of another day out
    blocks = "\nUNION ALL\n".join(
        f"""SELECT CAST(s.segments_date AS DATE) AS date, c.campaign_advertising_channel_type AS channel_type,
       s.metrics_cost_micros AS cost_micros
FROM `{config.dataset}.ads_CampaignBasicStats_{cid}` s
JOIN `{config.dataset}.ads_Campaign_{cid}` c
  ON c.campaign_id = s.campaign_id AND c._DATA_DATE = c._LATEST_DATE
WHERE s._DATA_DATE BETWEEN @start AND @end"""
        for cid in config.customer_ids
    )
    return f"""SELECT date, channel_type, SUM(cost_micros) / 1e6 AS spend FROM (
{blocks}
) WHERE date BETWEEN @start AND @end
GROUP BY 1, 2"""


def ga4_sql(config: Ga4Config) -> str:
    # events_* also matches events_intraday_*, whose suffix starts with a letter and falls outside the range
    return f"""SELECT PARSE_DATE('%Y%m%d', event_date) AS date, {METRICS[config.metric]} AS kpi
FROM `{config.dataset}.events_*`
WHERE _TABLE_SUFFIX BETWEEN @start_suffix AND @end_suffix AND event_name = @event
GROUP BY 1"""


def to_csv(header: list[str], rows: list[list]) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue().encode()


def investment_csv(rows: list[dict], period: Period) -> tuple[bytes, list[str]]:
    spend = defaultdict(float)
    for r in rows:
        channel_type = r["channel_type"] or "UNKNOWN"
        spend[(r["date"], CHANNELS.get(channel_type, channel_type))] += r["spend"] or 0
    if not any(spend.values()):
        raise simulations.InvalidInput("Nenhum investimento no Google Ads neste período.")
    channels = sorted({channel for _, channel in spend})
    # the engine needs a continuous series: a day the DTS has no row for is a day with no spend
    grid = [[day.isoformat(), c, str(round(spend[(day, c)], 2))] for day in period.days() for c in channels]
    return to_csv(["data", "canal", "investimento"], grid), channels


def performance_csv(rows: list[dict], period: Period, event: str) -> bytes:
    kpi = {r["date"]: r["kpi"] or 0 for r in rows}
    if not any(kpi.values()):
        raise simulations.InvalidInput(f"Nenhum evento '{event}' no GA4 neste período.")
    return to_csv(["data", "kpi"], [[day.isoformat(), str(round(kpi.get(day, 0), 2))] for day in period.days()])
