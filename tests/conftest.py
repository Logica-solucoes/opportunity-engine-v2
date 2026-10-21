import os

# before any `import api...`: api.db reads DATABASE_URL at import time, and tests must never touch the dev db
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://app:app@localhost:5432/app_test"
)

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from api import db as api_db  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def create_database_if_missing(url: str) -> None:
    target = make_url(url)
    server = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with server.connect() as conn:
        exists = conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target.database})
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    server.dispose()


@pytest.fixture(scope="session")
def schema():
    create_database_if_missing(api_db.DATABASE_URL)
    command.upgrade(Config(str(ROOT / "api" / "alembic.ini")), "head")


@pytest.fixture
def db(schema):
    conn = api_db.engine.connect()
    outer = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    outer.rollback()
    conn.close()
