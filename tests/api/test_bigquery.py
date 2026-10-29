from datetime import date

import pytest
from google.api_core import exceptions
from google.auth.exceptions import DefaultCredentialsError

from api import bigquery


class Row(dict):
    pass


def client_that(raises=None, rows=(), seen=None):
    class Job:
        def result(self, timeout):
            seen["timeout"] = timeout
            return [Row(r) for r in rows]

    class Client:
        def __init__(self):
            if isinstance(raises, DefaultCredentialsError):
                raise raises

        def query(self, sql, job_config):
            if raises is not None:
                raise raises
            seen["sql"], seen["config"] = sql, job_config
            return Job()

    return Client


def test_query_sends_typed_params_with_a_byte_cap(monkeypatch):
    seen = {}
    monkeypatch.setattr(bigquery.bq, "Client", client_that(rows=[{"date": date(2026, 1, 1), "kpi": 3}], seen=seen))

    rows = bigquery.query("SELECT 1", {"start": date(2026, 1, 1), "event": "purchase"})

    assert rows == [{"date": date(2026, 1, 1), "kpi": 3}]
    params = {p.name: (p.type_, p.value) for p in seen["config"].query_parameters}
    assert params == {"start": ("DATE", date(2026, 1, 1)), "event": ("STRING", "purchase")}
    assert seen["config"].maximum_bytes_billed == bigquery.MAX_BYTES_BILLED
    assert seen["timeout"] == bigquery.TIMEOUT_S


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (exceptions.Forbidden("sem acesso"), bigquery.NoAccess),
        (exceptions.NotFound("sem tabela"), bigquery.NoAccess),
        (exceptions.Forbidden("cota", errors=[{"reason": "quotaExceeded"}]), bigquery.Failed),
        (DefaultCredentialsError("sem adc"), bigquery.NoCredentials),
        (exceptions.BadRequest("bytes billed"), bigquery.Failed),
        (TimeoutError(), bigquery.Failed),
    ],
)
def test_query_errors_become_ours(monkeypatch, error, expected):
    monkeypatch.setattr(bigquery.bq, "Client", client_that(raises=error, seen={}))

    with pytest.raises(expected):
        bigquery.query("SELECT 1", {})
