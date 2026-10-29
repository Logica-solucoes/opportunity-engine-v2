import csv
import io
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import AfterValidator, BaseModel, Field, StringConstraints, ValidationError, model_validator
from sqlalchemy.orm import Session

from api import bigquery, simulations
from api.models import Simulation, User, Workspace

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


class NotConfigured(Exception):
    pass


def config_of(workspace: Workspace) -> GoogleConfig | None:
    raw = workspace.settings.get("google")
    if raw is None:
        return None
    try:
        # validated again: a value written straight to the db must not reach the SQL either
        return GoogleConfig.model_validate(raw)
    except ValidationError:
        log.error("google.bad_config workspace_id=%s", workspace.id)
        return None


def configure(db: Session, workspace: Workspace, config: GoogleConfig | None, by: User) -> None:
    settings = {k: v for k, v in workspace.settings.items() if k != "google"}
    if config is not None:
        settings["google"] = config.model_dump()
    # a new dict: SQLAlchemy doesn't see in-place changes to a JSONB column
    workspace.settings = settings
    db.commit()
    log.info("google.%s workspace_id=%s by=%s", "configured" if config else "removed", workspace.id, by.id)


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
LEFT JOIN `{config.dataset}.ads_Campaign_{cid}` c
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


FIXED_MAPPING = {
    "investment_file": {"date_col": "data", "channel_col": "canal", "investment_col": "investimento"},
    "performance_file": {"date_col": "data", "kpi_col": "kpi"},
}


class SourceError(Exception):
    pass


def fetch(dataset: str, sql: str, params: dict) -> list[dict]:
    try:
        return bigquery.query(sql, params)
    except bigquery.NoAccess:
        raise SourceError(f"A service account não tem acesso ao dataset ou a tabela não existe: {dataset}.")
    except bigquery.NoCredentials:
        raise SourceError("Conector Google sem credenciais neste ambiente.")
    except bigquery.Failed:
        raise SourceError("Não foi possível consultar o BigQuery.")


def trends_mapping(simulation: Simulation) -> dict:
    trends = next((f for f in simulation.files if f.kind == "trends"), None)
    if trends is None:
        return {}
    # a trends file never mapped gets the suggestion
    current = simulation.config.get("column_mapping", {}).get("generic_trends_file")
    mapping = current or simulations.suggest_mapping("trends", trends.columns)
    # checked before the queries: failing in save_mapping would leave the Google files saved behind a 422
    if any(column not in trends.columns for column in mapping.values()):
        raise simulations.InvalidInput("Mapeie as colunas do arquivo de trends antes de importar.")
    return {"generic_trends_file": mapping}


def run(db: Session, workspace: Workspace, simulation: Simulation, period: Period, by: User) -> None:
    config = config_of(workspace)
    if config is None:
        raise NotConfigured
    simulation_id = simulation.id
    mapping = {**FIXED_MAPPING, **trends_mapping(simulation)}
    # hand the connection back to the pool: each query can take 60 s
    db.rollback()
    ads = fetch(config.ads.dataset, ads_sql(config.ads), {"start": period.start, "end": period.end})
    ga4 = fetch(
        config.ga4.dataset,
        ga4_sql(config.ga4),
        {
            "start_suffix": period.start.strftime("%Y%m%d"),
            "end_suffix": period.end.strftime("%Y%m%d"),
            "event": config.ga4.event,
        },
    )
    investment, channels = investment_csv(ads, period)
    performance = performance_csv(ga4, period, config.ga4.event)

    span = f"{period.start}_{period.end}"
    performance_name = f"ga4-{config.ga4.event}-{config.ga4.metric}_{span}.csv"
    simulations.save_file(db, simulation, "investment", io.BytesIO(investment), f"google-ads_{span}.csv", by)
    simulations.save_file(db, simulation, "performance", io.BytesIO(performance), performance_name, by)
    simulations.save_mapping(db, simulation, mapping)
    log.info(
        "simulation.google_imported simulation_id=%s start=%s end=%s channels=%s",
        simulation_id,
        period.start,
        period.end,
        ",".join(channels),
    )
