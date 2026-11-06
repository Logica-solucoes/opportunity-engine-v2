"""Banco Central series for the causal model's controls, from the SGS (public, no key)."""

import csv
import io
import logging
from datetime import date, datetime, timedelta

import httpx

log = logging.getLogger(__name__)

# IPCA monthly change, Selic target (daily), IBC-Br seasonally adjusted (monthly): the model has only weekly seasonality
SERIES = {"bcb_ipca": 433, "bcb_selic": 432, "bcb_ibc_br": 24364}
URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"
TIMEOUT = 10
# ponytail: one call per series covers 10 years (the SGS caps a daily series there); older data needs chunked calls
WINDOW = timedelta(days=3650)
ERROR = "Não foi possível buscar as séries do Banco Central. Tente de novo ou desmarque os controles."


class Unavailable(Exception):
    pass


def get(code: int, start: date, end: date) -> list[dict]:
    params = {"formato": "json", "dataInicial": start.strftime("%d/%m/%Y"), "dataFinal": end.strftime("%d/%m/%Y")}
    response = httpx.get(URL.format(code=code), params=params, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def fetch(controls: list[str], today: date | None = None) -> bytes:
    """The engine's bcb_file: Date plus one column per control, a blank where a series has no value that day."""
    end = today or date.today()
    start = end - WINDOW
    series = {}
    for name in controls:
        try:
            rows = get(SERIES[name], start, end)
            values = {datetime.strptime(row["data"], "%d/%m/%Y").date(): float(row["valor"]) for row in rows}
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
            log.warning("bcb.unavailable series=%s reason=%r", name, e)
            raise Unavailable(name) from e
        if not values:
            log.warning("bcb.unavailable series=%s reason=empty", name)
            raise Unavailable(name)
        series[name] = values

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["Date", *controls])
    for day in sorted(set().union(*series.values())):
        writer.writerow([day.isoformat(), *(series[name].get(day, "") for name in controls)])
    return out.getvalue().encode()
