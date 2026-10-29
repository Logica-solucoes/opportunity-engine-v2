import logging
from datetime import date

from google.api_core import exceptions
from google.auth.exceptions import DefaultCredentialsError
from google.cloud import bigquery as bq

log = logging.getLogger(__name__)

# ponytail: 20 GB per query caps the bill; raise it if a real GA4 export needs more
MAX_BYTES_BILLED = 20 * 1024**3
TIMEOUT_S = 60
TYPES = {date: "DATE", str: "STRING"}
QUOTA_REASONS = {"quotaExceeded", "rateLimitExceeded"}


class Failed(Exception):
    pass


class NoAccess(Failed):
    pass


class NoCredentials(Failed):
    pass


def query(sql: str, params: dict[str, date | str]) -> list[dict]:
    config = bq.QueryJobConfig(
        query_parameters=[bq.ScalarQueryParameter(name, TYPES[type(v)], v) for name, v in params.items()],
        maximum_bytes_billed=MAX_BYTES_BILLED,
    )
    try:
        # project and credentials come from ADC: GOOGLE_APPLICATION_CREDENTIALS locally, the attached SA on Cloud Run
        rows = bq.Client().query(sql, job_config=config).result(timeout=TIMEOUT_S)
        return [dict(row.items()) for row in rows]
    except (exceptions.Forbidden, exceptions.NotFound) as e:
        # BigQuery also answers 403 for quota and rate limits, which no dataset grant fixes
        if any(err.get("reason") in QUOTA_REASONS for err in e.errors):
            log.exception("bigquery.failed")
            raise Failed from e
        log.exception("bigquery.no_access")
        raise NoAccess from e
    except DefaultCredentialsError as e:
        log.exception("bigquery.no_credentials")
        raise NoCredentials from e
    except Exception as e:  # byte cap, timeout, network: the import answers with a message, never a 500
        log.exception("bigquery.failed")
        raise Failed from e
