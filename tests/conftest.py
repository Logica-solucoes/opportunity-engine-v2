import os

# before any `import api...`: api.db reads DATABASE_URL at import time, and tests must never touch the dev db
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://app:app@localhost:5432/app_test")

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from api import db as api_db
from api import passwords, simulations
from api.main import create_app
from api.models import Membership, User, Workspace

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "senha-de-teste-123"


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


@pytest.fixture(autouse=True)
def fast_scrypt(monkeypatch):
    monkeypatch.setattr(passwords, "SCRYPT_N", 2**14)


@pytest.fixture
def password():
    return PASSWORD


@pytest.fixture
def app(db):
    app = create_app(web_dist=ROOT / "no-dist")
    app.dependency_overrides[api_db.get_db] = lambda: db
    return app


@pytest.fixture
def make_client(app):
    # https, or the Secure cookie never comes back
    return lambda: TestClient(app, base_url="https://testserver")


@pytest.fixture
def client(make_client):
    return make_client()


@pytest.fixture
def make_user(db):
    def make(email, *, platform=False, must_change=False, active=True):
        user = User(
            email=email,
            name=email.split("@")[0],
            password_hash=passwords.hash_password(PASSWORD),
            must_change_password=must_change,
            is_platform_admin=platform,
            active=active,
        )
        db.add(user)
        db.flush()
        return user

    return make


@pytest.fixture
def make_workspace(db):
    def make(slug, members=()):
        workspace = Workspace(name=slug.upper(), slug=slug)
        db.add(workspace)
        db.flush()
        for user, role in members:
            db.add(Membership(user_id=user.id, workspace_id=workspace.id, role=role))
        db.flush()
        return workspace

    return make


@pytest.fixture
def login_as():
    def login(client, user, password=PASSWORD):
        r = client.post("/api/auth/login", json={"email": user.email, "password": password})
        assert r.status_code == 200, r.text
        return r

    return login


@pytest.fixture
def make_simulation(db):
    def make(workspace, creator, name="Simulação"):
        return simulations.create(db, workspace, name, by=creator)

    return make
