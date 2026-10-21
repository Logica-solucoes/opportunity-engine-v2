# B1a — Auth, papéis e workspaces (backend) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Usuários, workspaces, memberships e sessões no Postgres; login com cookie de sessão opaco, bloqueio por falhas, troca de senha obrigatória; dependências FastAPI que escopam toda rota por workspace (404 entre workspaces); rotas de membros e de platform admin; CLI de bootstrap; teste papel × rota que cobre toda rota `/api/*`.

**Architecture:** `api/passwords.py` (scrypt stdlib) e `api/models.py` (SQLAlchemy 2) são a base. `api/auth.py` responde "quem é este request" (sessão, login, bloqueio, dependências `current_user`/`active_user`/`require_role`/`require_platform_admin`, middleware de `Origin`). `api/accounts.py` guarda a regra de negócio que muda contas (troca/reset de senha, membros, workspaces, desativar, bootstrap). As rotas em `api/routes/` são finas: validam com Pydantic, chamam o serviço e traduzem exceção em status.

**Tech Stack:** Python 3.13, FastAPI 0.158, SQLAlchemy 2.1, Alembic, psycopg 3, Postgres 16, pytest + `fastapi.testclient`. Nenhuma dependência nova.

**Spec:** [`docs/superpowers/specs/2026-10-21-b1a-auth-backend-design.md`](../specs/2026-10-21-b1a-auth-backend-design.md)

**Repo:** `opportunity-engine-v2` (todos os comandos rodam na raiz dele). **Branch:** `b1a-auth`, criada a partir da `main` antes da Task 1.

**Pré-requisito local:** `docker compose up -d` (Postgres em `:5432`). Os testes de banco usam o banco `app_test`, criado sozinho pelo `tests/conftest.py`.

**Baseline:** `uv run pytest -q` → 8 testes (7 passed, 1 skipped se o banco `app_test` ainda não existe). Nenhuma task pode quebrar os existentes.

## Ordem e paralelismo

| Lote | Tasks | Por quê |
|---|---|---|
| 1 | Task 1 (senhas) · Task 2 (models, migration, conftest de banco, CI) | arquivos disjuntos. **Task 2 não importa `api.passwords`** no conftest; os fixtures que fazem hash entram na Task 3 |
| 2 | Task 3 (sessão, login, deps, rotas de auth) | precisa de 1 e 2 |
| 3 | Task 4 (membros) → Task 5 (admin) → Task 6 (CLI) | **em série**: as três editam `api/accounts.py` e `api/main.py`; a Task 6 usa `reset_password` da Task 5 |
| 4 | Task 7 (matriz RBAC + 404 entre ws) · Task 8 (segredos fora do log) · Task 9 (docs) | arquivos disjuntos; 7 e 8 só criam testes, 9 só toca docs/config |
| 5 | Task 10 (verificação final) | precisa de tudo |

Duas rodadas de `pytest` em paralelo contra o mesmo `app_test` funcionam (cada teste roda em rollback), mas podem esperar lock de linha. No Lote 4, cada subagente roda só o seu arquivo de teste; a suíte inteira roda na Task 10.

## Mapa de arquivos

| Arquivo | Responsabilidade | Task |
|---|---|---|
| `api/passwords.py` | `hash_password`, `verify_password`, `dummy_hash`, `temp_password` | 1 |
| `tests/test_passwords.py` | testes de senha | 1 |
| `api/db.py` | + `Base`, `get_db` | 2 |
| `api/models.py` | `User`, `Workspace`, `Membership`, `UserSession`, `Role`, `ROLES` | 2 |
| `api/migrations/env.py` | `target_metadata = Base.metadata`; não silencia loggers | 2 |
| `api/migrations/versions/0001_auth_tables.py` | as 4 tabelas + enum | 2 |
| `tests/conftest.py` | banco de teste, schema, rollback por teste (2); app, clients, fábricas (3) | 2, 3 |
| `tests/api/test_migrations.py` | migration == models | 2 |
| `.github/workflows/ci.yml` | service Postgres no job `py` | 2 |
| `api/auth.py` | sessão, login, bloqueio, dependências, middleware de Origin | 3 |
| `api/accounts.py` | regra de negócio de contas | 3, 4, 5, 6 |
| `api/routes/__init__.py` | vazio | 3 |
| `api/routes/auth.py` | login, logout, troca de senha, `/api/me` | 3 |
| `api/routes/members.py` | membros do workspace | 4 |
| `api/routes/admin.py` | workspaces e contas (platform admin) | 5 |
| `api/cli.py` | `create-admin` | 6 |
| `api/main.py` | middleware + `include_router` | 3, 4, 5 |
| `mise.toml` | task `create-admin` | 6 |
| `tests/api/test_auth.py` · `test_members.py` · `test_admin.py` · `test_cli.py` | testes por recurso | 3, 4, 5, 6 |
| `tests/api/test_rbac.py` | matriz papel × rota, cobertura de rotas, 404 entre ws | 7 |
| `tests/api/test_logging.py` | segredos fora do log | 8 |
| `DATABASE.md` · `API-GUIDE.md` · `SECURITY.md` · `CODE-STYLE.md` · `CLAUDE.md` · `docs/decisoes/auth.md` · `docs/decisoes/README.md` · `docs/m2/trilha-b-plataforma.md` · `.env.example` | docs | 9 |

---

### Task 0: Branch

- [ ] **Step 1:** `git switch main && git pull --ff-only && git switch -c b1a-auth`
- [ ] **Step 2:** `docker compose up -d` e `uv run pytest -q`. Expected: `7 passed, 1 skipped` (ou `8 passed`).

---

### Task 1: Hash de senha (`api/passwords.py`)

**Files:**
- Create: `api/passwords.py`
- Test: `tests/test_passwords.py`

- [ ] **Step 1: Escrever o teste que falha**

`tests/test_passwords.py`:

```python
from api import passwords
from api.passwords import hash_password, temp_password, verify_password


def test_hash_roundtrip(monkeypatch):
    monkeypatch.setattr(passwords, "SCRYPT_N", 2**14)
    stored = hash_password("uma senha qualquer")

    assert stored.startswith("scrypt$16384$8$1$")
    assert verify_password("uma senha qualquer", stored)
    assert not verify_password("outra senha", stored)


def test_same_password_gets_different_salt(monkeypatch):
    monkeypatch.setattr(passwords, "SCRYPT_N", 2**14)
    assert hash_password("x" * 12) != hash_password("x" * 12)


def test_tampered_or_garbage_hash_is_rejected(monkeypatch):
    monkeypatch.setattr(passwords, "SCRYPT_N", 2**14)
    stored = hash_password("segredo-123456")
    algo, n, r, p, salt, digest = stored.split("$")
    flipped = ("A" if digest[0] != "A" else "B") + digest[1:]

    assert not verify_password("segredo-123456", "$".join([algo, n, r, p, salt, flipped]))
    assert not verify_password("segredo-123456", "pbkdf2$1$2$3$x$y")
    assert not verify_password("segredo-123456", "lixo")
    assert not verify_password("segredo-123456", "")


def test_params_are_read_from_the_hash(monkeypatch):
    monkeypatch.setattr(passwords, "SCRYPT_N", 2**14)
    old = hash_password("senha-antiga-123")
    monkeypatch.setattr(passwords, "SCRYPT_N", 2**15)

    assert verify_password("senha-antiga-123", old)
    assert hash_password("senha-nova-1234").startswith("scrypt$32768$")


def test_temp_password_is_long_and_random():
    a, b = temp_password(), temp_password()
    assert len(a) >= 12 and a != b
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_passwords.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.passwords'`

- [ ] **Step 3: Implementar**

`api/passwords.py`:

```python
import base64
import hashlib
import hmac
import os
import secrets
from functools import cache

# OWASP minimum for scrypt; params live in each hash, so raising N later keeps old hashes valid
SCRYPT_N = 2**17
SCRYPT_R = 8
SCRYPT_P = 1
MAXMEM = 2**28


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=MAXMEM)


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    b64 = lambda b: base64.b64encode(b).decode()
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        actual = _scrypt(password, base64.b64decode(salt), int(n), int(r), int(p))
        return hmac.compare_digest(actual, base64.b64decode(digest))
    except ValueError:
        return False


@cache
def dummy_hash() -> str:
    """Hash to verify against when the email doesn't exist, so timing doesn't reveal which accounts exist."""
    return hash_password(secrets.token_urlsafe(16))


def temp_password() -> str:
    return secrets.token_urlsafe(12)
```

(`binascii.Error` do `b64decode` é subclasse de `ValueError`, assim como os erros de parâmetro do `hashlib.scrypt`.)

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/test_passwords.py -q`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add api/passwords.py tests/test_passwords.py
git commit -m "feat(api): add scrypt password hashing"
```

---

### Task 2: Models, migration 0001, banco de teste e CI

**Files:**
- Modify: `api/db.py`
- Create: `api/models.py`, `api/migrations/versions/0001_auth_tables.py`, `tests/conftest.py`, `tests/api/test_migrations.py`
- Modify: `api/migrations/env.py`, `.github/workflows/ci.yml`

- [ ] **Step 1: `Base` e `get_db` em `api/db.py`**

Arquivo inteiro:

```python
import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://app:app@localhost:5432/app")

engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args={"connect_timeout": 2})
SessionLocal = sessionmaker(engine)


class Base(DeclarativeBase):
    pass


def get_db():
    with SessionLocal() as db:
        yield db


def ping() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
```

- [ ] **Step 2: `api/models.py`**

```python
from datetime import datetime
from typing import Literal, get_args

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Identity, LargeBinary, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api.db import Base

Role = Literal["admin", "analyst", "viewer"]
ROLES = get_args(Role)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    email: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    must_change_password: Mapped[bool] = mapped_column(server_default=text("true"))
    is_platform_admin: Mapped[bool] = mapped_column(server_default=text("false"))
    active: Mapped[bool] = mapped_column(server_default=text("true"))
    failed_logins: Mapped[int] = mapped_column(server_default=text("0"))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(Text, unique=True)
    settings: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Membership(Base):
    __tablename__ = "memberships"

    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(Enum(*ROLES, name="membership_role"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship()
    workspace: Mapped[Workspace] = relationship()


class UserSession(Base):
    __tablename__ = "sessions"

    token_hash: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()
```

(`UserSession` e não `Session` para não colidir com `sqlalchemy.orm.Session`. `created_at`/`last_seen_at` da sessão não têm default no banco: vêm de `auth.now()`, que os testes controlam.)

- [ ] **Step 3: `api/migrations/env.py`**

Troque o bloco de import/`fileConfig`/`target_metadata`. Substitua:

```python
from api.db import DATABASE_URL
```

por:

```python
import api.models  # noqa: F401  registers the tables on Base.metadata
from api.db import DATABASE_URL, Base
```

Substitua:

```python
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
```

por:

```python
if config.config_file_name is not None:
    # tests run alembic in-process; the default would disable loggers created before it (api.auth...)
    fileConfig(config.config_file_name, disable_existing_loggers=False)
```

Substitua `target_metadata = None` por `target_metadata = Base.metadata` e apague as 3 linhas de comentário do template logo acima dele (`# add your model's MetaData object here` … `# target_metadata = mymodel.Base.metadata`).

- [ ] **Step 4: Migration `api/migrations/versions/0001_auth_tables.py`**

Crie o diretório `api/migrations/versions/` e o arquivo (escrito à mão, com id fixo, para o `DATABASE.md` citar):

```python
"""auth tables: users, workspaces, memberships, sessions

Revision ID: 0001
Revises:
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_platform_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("failed_logins", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "workspaces",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("settings", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "memberships",
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column(
            "workspace_id", sa.BigInteger(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("role", sa.Enum("admin", "analyst", "viewer", name="membership_role"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.LargeBinary(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("memberships")
    op.drop_table("workspaces")
    op.drop_table("users")
    sa.Enum(name="membership_role").drop(op.get_bind())
```

- [ ] **Step 5: `tests/conftest.py` (parte de banco)**

```python
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
```

`schema` não é autouse de propósito: os testes de SPA e o `test_health_reports_db_down` não precisam de banco. Quem pede `db` e o Postgres está fora do ar **falha** (spec › Testes).

- [ ] **Step 6: Teste de que migration e models batem**

`tests/api/test_migrations.py`:

```python
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

import api.models  # noqa: F401
from api.db import Base


def test_migrations_match_models(db):
    assert compare_metadata(MigrationContext.configure(db.connection()), Base.metadata) == []
```

- [ ] **Step 7: Rodar**

Run: `uv run pytest tests/api/test_migrations.py -q`
Expected: `1 passed`. Se falhar com uma lista de diferenças, ajuste a migration (não o teste) até bater com os models.

- [ ] **Step 8: Downgrade funciona (no banco de dev)**

```bash
mise run db-migrate
uv run alembic -c api/alembic.ini downgrade base
uv run alembic -c api/alembic.ini upgrade head
```

Expected: os três sem erro; o último termina com `Running upgrade  -> 0001, auth tables...`.

- [ ] **Step 9: Postgres no CI**

Em `.github/workflows/ci.yml`, no job `py`, entre `runs-on: ubuntu-latest` e `steps:`:

```yaml
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: app
          POSTGRES_PASSWORD: app
          POSTGRES_DB: app
        ports: ["5432:5432"]
        options: >-
          --health-cmd pg_isready
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10
```

(O default de `TEST_DATABASE_URL` aponta para `localhost:5432/app_test`; o conftest cria o banco.)

- [ ] **Step 10: Suíte inteira**

Run: `uv run pytest -q`
Expected: `9 passed` (o `test_health_reports_db_ok` deixa de pular porque o `app_test` agora existe; na primeira rodada da vida ele pode ainda sair `skipped`, porque roda antes de o fixture `schema` criar o banco).

- [ ] **Step 11: Commit**

```bash
git add api/db.py api/models.py api/migrations/env.py api/migrations/versions/0001_auth_tables.py tests/conftest.py tests/api/test_migrations.py .github/workflows/ci.yml
git commit -m "feat(api): add users, workspaces, memberships and sessions tables"
```

---

### Task 3: Sessão, login, dependências e rotas de auth

**Files:**
- Create: `api/auth.py`, `api/accounts.py`, `api/routes/__init__.py` (vazio), `api/routes/auth.py`, `tests/api/test_auth.py`
- Modify: `tests/conftest.py`, `api/main.py`

- [ ] **Step 1: Fixtures de app e fábricas no `tests/conftest.py`**

Acrescente aos imports (depois de `from api import db as api_db  # noqa: E402`):

```python
from fastapi.testclient import TestClient  # noqa: E402

from api import passwords  # noqa: E402
from api.main import create_app  # noqa: E402
from api.models import Membership, User, Workspace  # noqa: E402
```

Acrescente depois de `ROOT = ...`:

```python
PASSWORD = "senha-de-teste-123"
```

E no fim do arquivo:

```python
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
```

(`tests/api/test_spa.py` tem seu próprio fixture `client`, que sobrepõe este; ele continua igual.)

- [ ] **Step 2: Escrever os testes que falham**

`tests/api/test_auth.py`:

```python
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from api import auth
from api.models import UserSession

NEW_PASSWORD = "uma-senha-nova-longa"


def freeze(monkeypatch, at):
    monkeypatch.setattr(auth, "now", lambda: at)


def session_count(db):
    return db.scalar(select(func.count()).select_from(UserSession))


def test_login_sets_hardened_cookie_and_returns_me(client, make_user, password):
    user = make_user("ana@x.com")

    r = client.post("/api/auth/login", json={"email": "  ANA@x.com ", "password": password})

    assert r.status_code == 200
    cookie = r.headers["set-cookie"]
    assert cookie.startswith("gem_session=")
    for flag in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"):
        assert flag in cookie
    assert "Max-Age" not in cookie and "expires" not in cookie.lower()
    assert r.json() == {
        "id": user.id,
        "email": "ana@x.com",
        "name": "ana",
        "is_platform_admin": False,
        "must_change_password": False,
        "workspaces": [],
    }


def test_session_stores_only_the_token_hash(client, db, make_user, login_as):
    login_as(client, make_user("ana@x.com"))
    token = client.cookies["gem_session"]

    row = db.scalars(select(UserSession)).one()

    assert row.token_hash == auth.hash_token(token)


def test_me_lists_memberships(client, make_user, make_workspace, login_as):
    user = make_user("ana@x.com")
    make_workspace("beta", [(user, "viewer")])
    make_workspace("alfa", [(user, "analyst")])
    make_workspace("outro")
    login_as(client, user)

    assert client.get("/api/me").json()["workspaces"] == [
        {"slug": "alfa", "name": "ALFA", "role": "analyst"},
        {"slug": "beta", "name": "BETA", "role": "viewer"},
    ]


def test_no_cookie_is_401(client):
    r = client.get("/api/me")
    assert (r.status_code, r.json()) == (401, {"detail": "not_authenticated"})


def test_random_or_truncated_cookie_is_401(client, make_client, make_user, login_as):
    login_as(client, make_user("ana@x.com"))
    token = client.cookies["gem_session"]

    # fresh client + explicit header: the jar stores the cookie under "testserver.local", so cookies.set would duplicate it
    for forged in ("abc", token[:-1], token + "x"):
        r = make_client().get("/api/me", headers={"Cookie": f"gem_session={forged}"})
        assert (r.status_code, r.json()) == (401, {"detail": "not_authenticated"}), forged


def test_idle_session_expires_after_8h(client, db, make_user, login_as, monkeypatch):
    t0 = datetime.now(UTC)
    login_as(client, make_user("ana@x.com"))

    freeze(monkeypatch, t0 + timedelta(hours=8, minutes=1))

    assert client.get("/api/me").status_code == 401
    assert session_count(db) == 0


def test_session_dies_after_7d_even_if_active(client, db, make_user, login_as, monkeypatch):
    t0 = datetime.now(UTC)
    login_as(client, make_user("ana@x.com"))
    later = t0 + timedelta(days=7, minutes=1)
    db.scalars(select(UserSession)).one().last_seen_at = later - timedelta(minutes=1)
    db.flush()

    freeze(monkeypatch, later)

    assert client.get("/api/me").status_code == 401


def test_activity_slides_the_idle_window(client, db, make_user, login_as, monkeypatch):
    t0 = datetime.now(UTC)
    login_as(client, make_user("ana@x.com"))

    freeze(monkeypatch, t0 + timedelta(hours=7))
    assert client.get("/api/me").status_code == 200
    freeze(monkeypatch, t0 + timedelta(hours=14))
    assert client.get("/api/me").status_code == 200


def test_wrong_password_unknown_email_and_inactive_look_the_same(client, make_user, password):
    make_user("ana@x.com")
    make_user("off@x.com", active=False)

    bodies = [
        {"email": "ana@x.com", "password": "errada-errada"},
        {"email": "ninguem@x.com", "password": password},
        {"email": "off@x.com", "password": password},
    ]
    for body in bodies:
        r = client.post("/api/auth/login", json=body)
        assert (r.status_code, r.json()) == (401, {"detail": "invalid_credentials"}), body


def test_fifth_failure_locks_for_15_min(client, make_user, password, monkeypatch):
    make_user("ana@x.com")
    t0 = datetime.now(UTC)
    freeze(monkeypatch, t0)
    wrong = {"email": "ana@x.com", "password": "errada-errada"}

    for _ in range(5):
        assert client.post("/api/auth/login", json=wrong).status_code == 401

    r = client.post("/api/auth/login", json={"email": "ana@x.com", "password": password})
    assert r.status_code == 429
    assert r.json() == {"detail": "locked", "retry_after_s": 900}

    freeze(monkeypatch, t0 + timedelta(minutes=15, seconds=1))
    assert client.post("/api/auth/login", json={"email": "ana@x.com", "password": password}).status_code == 200


def test_success_resets_the_failure_counter(client, make_user, password):
    make_user("ana@x.com")
    wrong = {"email": "ana@x.com", "password": "errada-errada"}
    right = {"email": "ana@x.com", "password": password}

    for _ in range(4):
        client.post("/api/auth/login", json=wrong)
    assert client.post("/api/auth/login", json=right).status_code == 200
    for _ in range(4):
        client.post("/api/auth/login", json=wrong)

    assert client.post("/api/auth/login", json=right).status_code == 200


def test_logout_kills_the_session(client, make_client, db, make_user, login_as):
    login_as(client, make_user("ana@x.com"))
    token = client.cookies["gem_session"]

    r = client.post("/api/auth/logout")

    assert r.status_code == 204
    assert 'gem_session=""' in r.headers["set-cookie"] or "Max-Age=0" in r.headers["set-cookie"]
    assert session_count(db) == 0
    assert make_client().get("/api/me", headers={"Cookie": f"gem_session={token}"}).status_code == 401


def test_change_password_keeps_current_session_and_kills_others(
    make_client, make_user, login_as, password
):
    user = make_user("ana@x.com", must_change=True)
    here, elsewhere = make_client(), make_client()
    login_as(here, user)
    login_as(elsewhere, user)

    r = here.post("/api/auth/password", json={"current": password, "new": NEW_PASSWORD})

    assert r.status_code == 204
    assert here.get("/api/me").json()["must_change_password"] is False
    assert elsewhere.get("/api/me").status_code == 401
    fresh = make_client()
    login_as(fresh, user, NEW_PASSWORD)


def test_change_password_rejects_bad_input(client, make_user, login_as, password):
    login_as(client, make_user("ana@x.com"))

    wrong_current = client.post("/api/auth/password", json={"current": "nao-e-essa", "new": NEW_PASSWORD})
    same = client.post("/api/auth/password", json={"current": password, "new": password})
    short = client.post("/api/auth/password", json={"current": password, "new": "curta"})

    assert (wrong_current.status_code, wrong_current.json()) == (400, {"detail": "invalid_current_password"})
    assert (same.status_code, same.json()) == (422, {"detail": "password_unchanged"})
    assert short.status_code == 422


def test_foreign_origin_on_mutation_is_403(client, make_user, password):
    make_user("ana@x.com")
    body = {"email": "ana@x.com", "password": password}

    evil = client.post("/api/auth/login", json=body, headers={"Origin": "https://evil.example"})
    same = client.post("/api/auth/login", json=body, headers={"Origin": "https://testserver"})
    get = client.get("/api/me", headers={"Origin": "https://evil.example"})

    assert (evil.status_code, evil.json()) == (403, {"detail": "bad_origin"})
    assert same.status_code == 200
    assert get.status_code == 200
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `uv run pytest tests/api/test_auth.py -q`
Expected: FAIL / ERROR — `ModuleNotFoundError: No module named 'api.auth'` (ou 404 nas rotas).

- [ ] **Step 4: `api/auth.py`**

```python
import hashlib
import logging
import math
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from fastapi import Cookie, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from api.db import get_db
from api.models import Membership, User, UserSession, Workspace
from api.passwords import dummy_hash, verify_password

log = logging.getLogger(__name__)

COOKIE = "gem_session"
IDLE_TIMEOUT = timedelta(hours=8)
MAX_AGE = timedelta(days=7)
TOUCH_EVERY = timedelta(minutes=1)
MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)
RANK = {"viewer": 0, "analyst": 1, "admin": 2}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def now() -> datetime:
    return datetime.now(UTC)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


class InvalidCredentials(Exception):
    pass


class AccountLocked(Exception):
    def __init__(self, retry_after_s: int):
        self.retry_after_s = retry_after_s


def authenticate(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None:
        verify_password(password, dummy_hash())
        log.info("auth.login_failed email=%s", email)
        raise InvalidCredentials

    t = now()
    if user.locked_until is not None and user.locked_until > t:
        raise AccountLocked(math.ceil((user.locked_until - t).total_seconds()))

    if not verify_password(password, user.password_hash):
        user.failed_logins += 1
        if user.failed_logins >= MAX_FAILED_LOGINS:
            user.failed_logins = 0
            user.locked_until = t + LOCKOUT
            log.warning("auth.locked user_id=%s", user.id)
        db.commit()
        log.info("auth.login_failed email=%s", email)
        raise InvalidCredentials

    if not user.active:
        log.info("auth.login_failed email=%s", email)
        raise InvalidCredentials

    user.failed_logins = 0
    user.locked_until = None
    return user


def create_session(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    t = now()
    db.add(UserSession(token_hash=hash_token(token), user_id=user.id, created_at=t, last_seen_at=t))
    db.commit()
    log.info("auth.login_ok user_id=%s", user.id)
    return token


def drop_sessions(db: Session, user_id: int, keep: bytes | None = None) -> None:
    query = delete(UserSession).where(UserSession.user_id == user_id)
    if keep is not None:
        query = query.where(UserSession.token_hash != keep)
    db.execute(query)


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(COOKIE, token, httponly=True, secure=True, samesite="lax", path="/")


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/", httponly=True, secure=True, samesite="lax")


def current_session(
    token: str | None = Cookie(default=None, alias=COOKIE), db: Session = Depends(get_db)
) -> UserSession:
    session = db.get(UserSession, hash_token(token)) if token else None
    if session is None:
        raise HTTPException(401, "not_authenticated")

    t = now()
    if t - session.last_seen_at >= IDLE_TIMEOUT or t - session.created_at >= MAX_AGE:
        db.delete(session)
        db.commit()
        raise HTTPException(401, "not_authenticated")

    if t - session.last_seen_at > TOUCH_EVERY:
        session.last_seen_at = t
        db.commit()
    return session


def current_user(session: UserSession = Depends(current_session)) -> User:
    return session.user


def active_user(user: User = Depends(current_user)) -> User:
    if user.must_change_password:
        raise HTTPException(403, "password_change_required")
    return user


@dataclass
class Ctx:
    user: User
    workspace: Workspace
    role: str


def require_role(min_role: str):
    def dependency(slug: str, user: User = Depends(active_user), db: Session = Depends(get_db)) -> Ctx:
        workspace = db.scalar(select(Workspace).where(Workspace.slug == slug))
        if workspace is None:
            raise HTTPException(404)

        if user.is_platform_admin:
            role = "admin"
        else:
            membership = db.get(Membership, (user.id, workspace.id))
            # not a member looks exactly like "doesn't exist": 403 would confirm the workspace exists
            if membership is None:
                raise HTTPException(404)
            role = membership.role

        if RANK[role] < RANK[min_role]:
            raise HTTPException(403)
        return Ctx(user, workspace, role)

    return dependency


def require_platform_admin(user: User = Depends(active_user)) -> User:
    if not user.is_platform_admin:
        raise HTTPException(403)
    return user


async def check_origin(request: Request, call_next):
    # host only, not scheme: Cloud Run terminates TLS, so the app sees http while the browser sends https
    origin = request.headers.get("origin")
    if (
        request.method in UNSAFE_METHODS
        and request.url.path.startswith("/api/")
        and origin is not None
        and urlsplit(origin).netloc != request.headers.get("host")
    ):
        return JSONResponse({"detail": "bad_origin"}, status_code=403)
    return await call_next(request)
```

- [ ] **Step 5: `api/accounts.py` (só troca de senha por enquanto)**

```python
import logging

from sqlalchemy.orm import Session

from api.auth import drop_sessions
from api.models import UserSession
from api.passwords import hash_password, verify_password

log = logging.getLogger(__name__)


class Conflict(Exception):
    pass


class WrongPassword(Exception):
    pass


class SamePassword(Exception):
    pass


def change_password(db: Session, session: UserSession, current: str, new: str) -> None:
    user = session.user
    if not verify_password(current, user.password_hash):
        raise WrongPassword
    if new == current:
        raise SamePassword
    user.password_hash = hash_password(new)
    user.must_change_password = False
    drop_sessions(db, user.id, keep=session.token_hash)
    db.commit()
    log.info("auth.password_changed user_id=%s", user.id)
```

- [ ] **Step 6: `api/routes/__init__.py` (vazio) e `api/routes/auth.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api import accounts, auth
from api.db import get_db
from api.models import Membership, Role, User, UserSession, Workspace

router = APIRouter(prefix="/api")


class LoginIn(BaseModel):
    email: str
    password: str


class PasswordIn(BaseModel):
    current: str
    new: str = Field(min_length=12)


class MyWorkspace(BaseModel):
    slug: str
    name: str
    role: Role


class MeOut(BaseModel):
    id: int
    email: str
    name: str
    is_platform_admin: bool
    must_change_password: bool
    workspaces: list[MyWorkspace]


def me_out(db: Session, user: User) -> MeOut:
    if user.is_platform_admin:
        rows = [(w, "admin") for w in db.scalars(select(Workspace).order_by(Workspace.name))]
    else:
        rows = db.execute(
            select(Workspace, Membership.role)
            .join(Membership, Membership.workspace_id == Workspace.id)
            .where(Membership.user_id == user.id)
            .order_by(Workspace.name)
        ).all()
    return MeOut(
        id=user.id,
        email=user.email,
        name=user.name,
        is_platform_admin=user.is_platform_admin,
        must_change_password=user.must_change_password,
        workspaces=[MyWorkspace(slug=w.slug, name=w.name, role=role) for w, role in rows],
    )


@router.post("/auth/login", response_model=MeOut)
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    try:
        user = auth.authenticate(db, body.email, body.password)
    except auth.AccountLocked as e:
        return JSONResponse({"detail": "locked", "retry_after_s": e.retry_after_s}, status_code=429)
    except auth.InvalidCredentials:
        raise HTTPException(401, "invalid_credentials")
    auth.set_session_cookie(response, auth.create_session(db, user))
    return me_out(db, user)


@router.post("/auth/logout", status_code=204)
def logout(response: Response, session: UserSession = Depends(auth.current_session), db: Session = Depends(get_db)):
    db.delete(session)
    db.commit()
    auth.clear_session_cookie(response)


@router.post("/auth/password", status_code=204)
def change_password(
    body: PasswordIn, session: UserSession = Depends(auth.current_session), db: Session = Depends(get_db)
):
    try:
        accounts.change_password(db, session, body.current, body.new)
    except accounts.WrongPassword:
        raise HTTPException(400, "invalid_current_password")
    except accounts.SamePassword:
        raise HTTPException(422, "password_unchanged")


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(auth.current_user), db: Session = Depends(get_db)):
    return me_out(db, user)
```

- [ ] **Step 7: Registrar em `api/main.py`**

Imports: troque `from api import db` por:

```python
from api import auth, db
from api.routes import auth as auth_routes
```

Em `create_app`, troque:

```python
    app = FastAPI(title="Marketing GEM")
    app.include_router(router)
```

por:

```python
    app = FastAPI(title="Marketing GEM")
    app.middleware("http")(auth.check_origin)
    app.include_router(router)
    app.include_router(auth_routes.router)
```

- [ ] **Step 8: Rodar e ver passar**

Run: `uv run pytest tests/api/test_auth.py -q`
Expected: `15 passed`.

Se `test_logout_kills_the_session` falhar só na asserção do `set-cookie`, imprima o header: o Starlette escreve `gem_session=""; ... Max-Age=0`, e a asserção aceita as duas formas.

- [ ] **Step 9: Suíte inteira e commit**

Run: `uv run pytest -q` → tudo passa.

```bash
git add api/auth.py api/accounts.py api/routes/__init__.py api/routes/auth.py api/main.py tests/conftest.py tests/api/test_auth.py
git commit -m "feat(api): add session cookie auth, lockout and password change"
```

---

### Task 4: Membros do workspace

**Files:**
- Create: `api/routes/members.py`, `tests/api/test_members.py`
- Modify: `api/accounts.py`, `api/main.py`

- [ ] **Step 1: Escrever os testes que falham**

`tests/api/test_members.py`:

```python
from sqlalchemy import select

from api.models import Membership, User


def test_list_members_sorted_by_email(client, make_user, make_workspace, login_as):
    admin = make_user("zeca@x.com")
    viewer = make_user("bia@x.com", active=False)
    make_workspace("a", [(admin, "admin"), (viewer, "viewer")])
    login_as(client, admin)

    assert client.get("/api/w/a/members").json() == [
        {"user_id": viewer.id, "email": "bia@x.com", "name": "bia", "role": "viewer", "active": False},
        {"user_id": admin.id, "email": "zeca@x.com", "name": "zeca", "role": "admin", "active": True},
    ]


def test_add_new_account_returns_temp_password_once(make_client, client, db, make_user, make_workspace, login_as):
    admin = make_user("admin@x.com")
    ws = make_workspace("a", [(admin, "admin")])
    login_as(client, admin)

    r = client.post("/api/w/a/members", json={"email": " Nova@X.com ", "name": "Nova", "role": "analyst"})

    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "nova@x.com" and body["role"] == "analyst" and body["active"] is True
    temp = body["temp_password"]
    assert len(temp) >= 12

    user = db.scalar(select(User).where(User.email == "nova@x.com"))
    assert user.must_change_password and db.get(Membership, (user.id, ws.id)).role == "analyst"
    newcomer = make_client()
    login_as(newcomer, user, temp)
    assert newcomer.get("/api/me").json()["must_change_password"] is True


def test_add_existing_account_only_creates_membership(client, db, make_user, make_workspace, login_as):
    admin = make_user("admin@x.com")
    other = make_user("outro@x.com")
    make_workspace("b", [(other, "viewer")])
    make_workspace("a", [(admin, "admin")])
    before = other.password_hash
    login_as(client, admin)

    r = client.post("/api/w/a/members", json={"email": "outro@x.com", "name": "Nome Trocado", "role": "viewer"})

    assert r.status_code == 201
    assert r.json()["temp_password"] is None
    db.refresh(other)
    assert (other.password_hash, other.name) == (before, "outro")


def test_add_existing_member_is_409(client, make_user, make_workspace, login_as):
    admin = make_user("admin@x.com")
    make_workspace("a", [(admin, "admin")])
    login_as(client, admin)

    r = client.post("/api/w/a/members", json={"email": "admin@x.com", "name": "Admin", "role": "viewer"})

    assert r.status_code == 409


def test_add_member_validates_input(client, make_user, make_workspace, login_as):
    admin = make_user("admin@x.com")
    make_workspace("a", [(admin, "admin")])
    login_as(client, admin)

    bad_role = client.post("/api/w/a/members", json={"email": "x@x.com", "name": "X", "role": "owner"})
    bad_email = client.post("/api/w/a/members", json={"email": "sem-arroba", "name": "X", "role": "viewer"})

    assert bad_role.status_code == 422 and bad_email.status_code == 422


def test_change_role_and_remove(client, db, make_user, make_workspace, login_as):
    admin = make_user("admin@x.com")
    member = make_user("m@x.com")
    ws = make_workspace("a", [(admin, "admin"), (member, "viewer")])
    login_as(client, admin)

    r = client.patch(f"/api/w/a/members/{member.id}", json={"role": "analyst"})
    assert r.status_code == 200 and r.json()["role"] == "analyst"

    assert client.delete(f"/api/w/a/members/{member.id}").status_code == 204
    assert db.get(Membership, (member.id, ws.id)) is None
    assert db.get(User, member.id) is not None


def test_unknown_member_is_404(client, make_user, make_workspace, login_as):
    admin = make_user("admin@x.com")
    make_workspace("a", [(admin, "admin")])
    login_as(client, admin)

    assert client.patch("/api/w/a/members/999999", json={"role": "viewer"}).status_code == 404
    assert client.delete("/api/w/a/members/999999").status_code == 404


def test_pending_password_change_blocks_workspace_routes(client, make_user, make_workspace, login_as):
    admin = make_user("admin@x.com", must_change=True)
    make_workspace("a", [(admin, "admin")])
    login_as(client, admin)

    r = client.get("/api/w/a/members")

    assert (r.status_code, r.json()) == (403, {"detail": "password_change_required"})
    assert client.get("/api/me").status_code == 200
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/api/test_members.py -q`
Expected: FAIL — 404 em `/api/w/a/members` (rota não existe).

- [ ] **Step 3: `add_member` em `api/accounts.py`**

Imports no topo, trocando os atuais de `api.auth`, `api.models` e `api.passwords` por:

```python
from sqlalchemy import select

from api.auth import drop_sessions, normalize_email
from api.models import Membership, User, UserSession, Workspace
from api.passwords import hash_password, temp_password, verify_password
```

No fim do arquivo:

```python
def add_member(db: Session, workspace: Workspace, email: str, name: str, role: str) -> tuple[Membership, str | None]:
    email = normalize_email(email)
    user = db.scalar(select(User).where(User.email == email))
    temp = None
    if user is None:
        temp = temp_password()
        user = User(email=email, name=name, password_hash=hash_password(temp), must_change_password=True)
        db.add(user)
        db.flush()
    elif db.get(Membership, (user.id, workspace.id)) is not None:
        raise Conflict

    membership = Membership(user_id=user.id, workspace_id=workspace.id, role=role)
    db.add(membership)
    db.commit()
    log.info("auth.member_added user_id=%s workspace_id=%s role=%s", user.id, workspace.id, role)
    return membership, temp
```

- [ ] **Step 4: `api/routes/members.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api import accounts
from api.auth import Ctx, require_role
from api.db import get_db
from api.models import Membership, Role, User

router = APIRouter(prefix="/api/w/{slug}/members")
workspace_admin = require_role("admin")


class MemberIn(BaseModel):
    email: str = Field(pattern=r"^\s*[^@\s]+@[^@\s]+\.[^@\s]+\s*$")
    name: str = Field(min_length=1)
    role: Role


class RoleIn(BaseModel):
    role: Role


class MemberOut(BaseModel):
    user_id: int
    email: str
    name: str
    role: Role
    active: bool


class NewMemberOut(MemberOut):
    temp_password: str | None


def member_out(m: Membership) -> MemberOut:
    return MemberOut(user_id=m.user_id, email=m.user.email, name=m.user.name, role=m.role, active=m.user.active)


def find_member(db: Session, ctx: Ctx, user_id: int) -> Membership:
    membership = db.get(Membership, (user_id, ctx.workspace.id))
    if membership is None:
        raise HTTPException(404)
    return membership


@router.get("", response_model=list[MemberOut])
def list_members(ctx: Ctx = Depends(workspace_admin), db: Session = Depends(get_db)):
    memberships = db.scalars(
        select(Membership).join(Membership.user).where(Membership.workspace_id == ctx.workspace.id).order_by(User.email)
    )
    return [member_out(m) for m in memberships]


@router.post("", status_code=201, response_model=NewMemberOut)
def add_member(body: MemberIn, ctx: Ctx = Depends(workspace_admin), db: Session = Depends(get_db)):
    try:
        membership, temp = accounts.add_member(db, ctx.workspace, body.email, body.name, body.role)
    except accounts.Conflict:
        raise HTTPException(409, "Usuário já é membro deste workspace")
    return NewMemberOut(**member_out(membership).model_dump(), temp_password=temp)


@router.patch("/{user_id}", response_model=MemberOut)
def change_role(user_id: int, body: RoleIn, ctx: Ctx = Depends(workspace_admin), db: Session = Depends(get_db)):
    membership = find_member(db, ctx, user_id)
    membership.role = body.role
    db.commit()
    return member_out(membership)


@router.delete("/{user_id}", status_code=204)
def remove_member(user_id: int, ctx: Ctx = Depends(workspace_admin), db: Session = Depends(get_db)):
    db.delete(find_member(db, ctx, user_id))
    db.commit()
```

- [ ] **Step 5: Registrar em `api/main.py`**

Troque `from api.routes import auth as auth_routes` por `from api.routes import auth as auth_routes, members` e, depois de `app.include_router(auth_routes.router)`, acrescente `app.include_router(members.router)`.

- [ ] **Step 6: Rodar e ver passar**

Run: `uv run pytest tests/api/test_members.py -q` → `8 passed`. Depois `uv run pytest -q` → tudo passa.

- [ ] **Step 7: Commit**

```bash
git add api/accounts.py api/routes/members.py api/main.py tests/api/test_members.py
git commit -m "feat(api): add workspace member management"
```

---

### Task 5: Rotas de platform admin

**Files:**
- Create: `api/routes/admin.py`, `tests/api/test_admin.py`
- Modify: `api/accounts.py`, `api/main.py`

- [ ] **Step 1: Escrever os testes que falham**

`tests/api/test_admin.py`:

```python
from datetime import UTC, datetime, timedelta

from api.models import Workspace


def test_create_and_list_workspaces(client, db, make_user, login_as):
    login_as(client, make_user("root@x.com", platform=True))

    r = client.post("/api/admin/workspaces", json={"name": "Marca B", "slug": "marca-b"})
    client.post("/api/admin/workspaces", json={"name": "Marca A", "slug": "marca-a"})

    assert r.status_code == 201
    assert r.json()["slug"] == "marca-b" and db.get(Workspace, r.json()["id"]).settings == {}
    assert [w["name"] for w in client.get("/api/admin/workspaces").json()] == ["Marca A", "Marca B"]


def test_workspace_slug_rules(client, make_user, make_workspace, login_as):
    make_workspace("existe")
    login_as(client, make_user("root@x.com", platform=True))

    dup = client.post("/api/admin/workspaces", json={"name": "X", "slug": "existe"})
    assert dup.status_code == 409
    for bad in ("A", "com espaço", "Maiuscula", "x" * 41, "a_b"):
        assert client.post("/api/admin/workspaces", json={"name": "X", "slug": bad}).status_code == 422, bad


def test_platform_admin_sees_all_workspaces_as_admin(client, make_user, make_workspace, login_as):
    make_workspace("b")
    make_workspace("a")
    login_as(client, make_user("root@x.com", platform=True))

    assert client.get("/api/me").json()["workspaces"] == [
        {"slug": "a", "name": "A", "role": "admin"},
        {"slug": "b", "name": "B", "role": "admin"},
    ]


def test_list_users(client, db, make_user, login_as):
    root = make_user("root@x.com", platform=True)
    ana = make_user("ana@x.com")
    ana.locked_until = datetime.now(UTC) + timedelta(minutes=5)
    db.flush()
    login_as(client, root)

    users = client.get("/api/admin/users").json()

    assert [u["email"] for u in users] == ["ana@x.com", "root@x.com"]
    assert users[0]["locked_until"] is not None and users[0]["is_platform_admin"] is False
    assert set(users[0]) == {"id", "email", "name", "active", "is_platform_admin", "locked_until"}


def test_reset_password_kills_sessions_and_unlocks(make_client, db, make_user, login_as):
    root, ana = make_user("root@x.com", platform=True), make_user("ana@x.com")
    admin_client, ana_client = make_client(), make_client()
    login_as(admin_client, root)
    login_as(ana_client, ana)
    ana.locked_until = datetime.now(UTC) + timedelta(minutes=5)
    db.flush()

    r = admin_client.post(f"/api/admin/users/{ana.id}/reset-password")

    assert r.status_code == 200
    temp = r.json()["temp_password"]
    assert ana_client.get("/api/me").status_code == 401
    fresh = make_client()
    me = login_as(fresh, ana, temp).json()
    assert me["must_change_password"] is True


def test_deactivate_kills_sessions_and_blocks_login(make_client, make_user, login_as, password):
    root, ana = make_user("root@x.com", platform=True), make_user("ana@x.com")
    admin_client, ana_client = make_client(), make_client()
    login_as(admin_client, root)
    login_as(ana_client, ana)

    r = admin_client.patch(f"/api/admin/users/{ana.id}", json={"active": False})

    assert r.status_code == 200 and r.json()["active"] is False
    assert ana_client.get("/api/me").status_code == 401
    login = ana_client.post("/api/auth/login", json={"email": "ana@x.com", "password": password})
    assert login.status_code == 401

    admin_client.patch(f"/api/admin/users/{ana.id}", json={"active": True})
    login_as(ana_client, ana)


def test_unknown_user_is_404(client, make_user, login_as):
    login_as(client, make_user("root@x.com", platform=True))

    assert client.post("/api/admin/users/999999/reset-password").status_code == 404
    assert client.patch("/api/admin/users/999999", json={"active": False}).status_code == 404
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/api/test_admin.py -q`
Expected: FAIL — 404 nas rotas `/api/admin/*`.

- [ ] **Step 3: Serviços em `api/accounts.py`** (no fim do arquivo)

```python
def create_workspace(db: Session, name: str, slug: str) -> Workspace:
    if db.scalar(select(Workspace.id).where(Workspace.slug == slug)) is not None:
        raise Conflict
    workspace = Workspace(name=name, slug=slug)
    db.add(workspace)
    db.commit()
    log.info("auth.workspace_created workspace_id=%s slug=%s", workspace.id, slug)
    return workspace


def reset_password(db: Session, user: User, by: User | None) -> str:
    temp = temp_password()
    user.password_hash = hash_password(temp)
    user.must_change_password = True
    user.failed_logins = 0
    user.locked_until = None
    drop_sessions(db, user.id)
    db.commit()
    log.info("auth.password_reset user_id=%s by=%s", user.id, by.id if by else "cli")
    return temp


def set_active(db: Session, user: User, active: bool, by: User) -> None:
    user.active = active
    if not active:
        drop_sessions(db, user.id)
        log.info("auth.user_deactivated user_id=%s by=%s", user.id, by.id)
    db.commit()
```

- [ ] **Step 4: `api/routes/admin.py`**

```python
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from api import accounts
from api.auth import require_platform_admin
from api.db import get_db
from api.models import User, Workspace

router = APIRouter(prefix="/api/admin")


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1)
    slug: str = Field(pattern=r"^[a-z0-9-]{2,40}$")


class WorkspaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    created_at: datetime


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str
    active: bool
    is_platform_admin: bool
    locked_until: datetime | None


class ActiveIn(BaseModel):
    active: bool


class TempPasswordOut(BaseModel):
    temp_password: str


def find_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404)
    return user


@router.get("/workspaces", response_model=list[WorkspaceOut])
def list_workspaces(_: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    return db.scalars(select(Workspace).order_by(Workspace.name)).all()


@router.post("/workspaces", status_code=201, response_model=WorkspaceOut)
def create_workspace(body: WorkspaceIn, _: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    try:
        return accounts.create_workspace(db, body.name, body.slug)
    except accounts.Conflict:
        raise HTTPException(409, "Já existe um workspace com esse slug")


@router.get("/users", response_model=list[UserOut])
def list_users(_: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    return db.scalars(select(User).order_by(User.email)).all()


@router.post("/users/{user_id}/reset-password", response_model=TempPasswordOut)
def reset_password(user_id: int, admin: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    return TempPasswordOut(temp_password=accounts.reset_password(db, find_user(db, user_id), by=admin))


@router.patch("/users/{user_id}", response_model=UserOut)
def set_active(
    user_id: int, body: ActiveIn, admin: User = Depends(require_platform_admin), db: Session = Depends(get_db)
):
    user = find_user(db, user_id)
    accounts.set_active(db, user, body.active, by=admin)
    return user
```

- [ ] **Step 5: Registrar em `api/main.py`**

Troque `from api.routes import auth as auth_routes, members` por `from api.routes import admin, auth as auth_routes, members` e, depois de `app.include_router(members.router)`, acrescente `app.include_router(admin.router)`.

- [ ] **Step 6: Rodar e ver passar**

Run: `uv run pytest tests/api/test_admin.py -q` → `7 passed`. Depois `uv run pytest -q` → tudo passa.

- [ ] **Step 7: Commit**

```bash
git add api/accounts.py api/routes/admin.py api/main.py tests/api/test_admin.py
git commit -m "feat(api): add platform admin routes for workspaces and accounts"
```

---

### Task 6: CLI `create-admin`

**Files:**
- Create: `api/cli.py`, `tests/api/test_cli.py`
- Modify: `api/accounts.py`, `mise.toml`

- [ ] **Step 1: Escrever os testes que falham**

`tests/api/test_cli.py`:

```python
from contextlib import nullcontext

from sqlalchemy import select

from api import cli
from api.accounts import create_platform_admin
from api.models import User


def test_create_admin_makes_a_platform_admin_that_can_log_in(client, db, login_as):
    temp = create_platform_admin(db, " Root@X.com ", "Root")

    user = db.scalar(select(User).where(User.email == "root@x.com"))
    me = login_as(client, user, temp).json()
    assert me["is_platform_admin"] is True and me["must_change_password"] is True


def test_create_admin_promotes_existing_user_and_resets_password(client, db, make_user, password):
    ana = make_user("ana@x.com")

    temp = create_platform_admin(db, "ana@x.com", "Ana")

    assert ana.is_platform_admin is True
    assert client.post("/api/auth/login", json={"email": "ana@x.com", "password": password}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "ana@x.com", "password": temp}).status_code == 200


def test_main_prints_the_temp_password(client, db, monkeypatch, capsys):
    monkeypatch.setattr(cli, "SessionLocal", lambda: nullcontext(db))

    cli.main(["create-admin", "root@x.com", "Root"])

    out = capsys.readouterr().out
    assert out.startswith("senha temporária: ")
    temp = out.split(": ", 1)[1].strip()
    assert client.post("/api/auth/login", json={"email": "root@x.com", "password": temp}).status_code == 200
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/api/test_cli.py -q`
Expected: FAIL — `ImportError: cannot import name 'cli'` / `create_platform_admin`.

- [ ] **Step 3: `create_platform_admin` em `api/accounts.py`** (no fim)

```python
def create_platform_admin(db: Session, email: str, name: str) -> str:
    email = normalize_email(email)
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, name=name, password_hash="")
        db.add(user)
    user.is_platform_admin = True
    user.active = True
    db.flush()
    return reset_password(db, user, by=None)
```

- [ ] **Step 4: `api/cli.py`**

```python
import argparse
import logging
import sys

from api.accounts import create_platform_admin
from api.db import SessionLocal


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(prog="python -m api.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    create_admin = commands.add_parser("create-admin", help="cria ou promove um platform admin")
    create_admin.add_argument("email")
    create_admin.add_argument("name")
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        temp = create_platform_admin(db, args.email, args.name)
    # the temp password is the command's output, not a log line: it must never go through logging
    sys.stdout.write(f"senha temporária: {temp}\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Task no `mise.toml`** (depois de `[tasks.db-migrate]`)

```toml
[tasks.create-admin]
description = "Create or promote a platform admin: mise run create-admin <email> <name>"
run = "uv run python -m api.cli create-admin"
```

- [ ] **Step 6: Rodar e ver passar**

Run: `uv run pytest tests/api/test_cli.py -q` → `3 passed`. Depois `uv run pytest -q` → tudo passa.

- [ ] **Step 7: Commit**

```bash
git add api/accounts.py api/cli.py mise.toml tests/api/test_cli.py
git commit -m "feat(api): add create-admin cli for platform admin bootstrap"
```

---

### Task 7: Matriz papel × rota e 404 entre workspaces

**Files:**
- Create: `tests/api/test_rbac.py`

Só teste: se algo falhar, o bug está no código das Tasks 3–5. Corrija lá, nunca afrouxe a tabela.

- [ ] **Step 1: Escrever o teste**

`tests/api/test_rbac.py`:

```python
import pytest
from fastapi.routing import APIRoute

from api.auth import RANK

PUBLIC, SESSION, PLATFORM = "public", "session", "platform"
ACTORS = ["anon", "viewer", "analyst", "admin", "platform"]

# (method, path) -> (minimum, success status, body builder). Every /api route must be here.
ROUTES = {
    ("POST", "/api/auth/login"): (PUBLIC, 200, lambda e: {"email": e["target"].email, "password": e["password"]}),
    ("POST", "/api/auth/logout"): (SESSION, 204, None),
    ("POST", "/api/auth/password"): (SESSION, 204, lambda e: {"current": e["password"], "new": "outra-senha-longa"}),
    ("GET", "/api/me"): (SESSION, 200, None),
    ("GET", "/api/w/{slug}/members"): ("admin", 200, None),
    ("POST", "/api/w/{slug}/members"): ("admin", 201, lambda e: {"email": "novo@x.com", "name": "N", "role": "viewer"}),
    ("PATCH", "/api/w/{slug}/members/{user_id}"): ("admin", 200, lambda e: {"role": "analyst"}),
    ("DELETE", "/api/w/{slug}/members/{user_id}"): ("admin", 204, None),
    ("GET", "/api/admin/workspaces"): (PLATFORM, 200, None),
    ("POST", "/api/admin/workspaces"): (PLATFORM, 201, lambda e: {"name": "Nova", "slug": "nova"}),
    ("GET", "/api/admin/users"): (PLATFORM, 200, None),
    ("POST", "/api/admin/users/{user_id}/reset-password"): (PLATFORM, 200, None),
    ("PATCH", "/api/admin/users/{user_id}"): (PLATFORM, 200, lambda e: {"active": False}),
}
UNSCOPED = {("GET", "/api/health")}


def expected_status(minimum, ok, actor):
    if minimum == PUBLIC:
        return ok
    if actor == "anon":
        return 401
    if minimum == SESSION:
        return ok
    if minimum == PLATFORM:
        return ok if actor == "platform" else 403
    return ok if actor == "platform" or RANK[actor] >= RANK[minimum] else 403


@pytest.fixture
def env(make_user, make_workspace, password):
    users = {role: make_user(f"{role}@x.com") for role in ("viewer", "analyst", "admin")}
    users["platform"] = make_user("platform@x.com", platform=True)
    target = make_user("target@x.com")
    make_workspace("a", [(users[r], r) for r in ("viewer", "analyst", "admin")] + [(target, "viewer")])
    return {"users": users, "target": target, "password": password}


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("route", list(ROUTES), ids=lambda r: f"{r[0]} {r[1]}")
def test_role_matrix(route, actor, client, env, login_as):
    minimum, ok, body = ROUTES[route]
    if actor != "anon":
        login_as(client, env["users"][actor])
    method, template = route
    path = template.format(slug="a", user_id=env["target"].id)

    r = client.request(method, path, json=body(env) if body else None)

    assert r.status_code == expected_status(minimum, ok, actor), r.text


def test_matrix_covers_every_api_route(app):
    found = {
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/")
        for method in route.methods
    }
    assert found - UNSCOPED == set(ROUTES)


def test_other_workspace_looks_like_it_does_not_exist(client, make_user, make_workspace, login_as):
    admin = make_user("admin@a.com")
    stranger = make_user("membro@b.com")
    make_workspace("a", [(admin, "admin")])
    make_workspace("b", [(stranger, "viewer")])
    login_as(client, admin)
    missing = client.get("/api/w/nao-existe/members")
    assert missing.status_code == 404

    calls = [
        ("GET", "/api/w/b/members", None),
        ("POST", "/api/w/b/members", {"email": "x@b.com", "name": "X", "role": "viewer"}),
        ("PATCH", f"/api/w/b/members/{stranger.id}", {"role": "admin"}),
        ("DELETE", f"/api/w/b/members/{stranger.id}", None),
        ("PATCH", f"/api/w/a/members/{stranger.id}", {"role": "admin"}),
    ]
    for method, path, body in calls:
        r = client.request(method, path, json=body)
        assert (r.status_code, r.json()) == (404, missing.json()), (method, path)
```

- [ ] **Step 2: Rodar**

Run: `uv run pytest tests/api/test_rbac.py -q`
Expected: `67 passed` (13 rotas × 5 atores + 2).

- [ ] **Step 3: Provar que o teste de cobertura morde**

Acrescente temporariamente em `api/routes/auth.py`:

```python
@router.get("/tmp-probe")
def probe():
    return {}
```

Run: `uv run pytest tests/api/test_rbac.py::test_matrix_covers_every_api_route -q`
Expected: FAIL, com `('GET', '/api/tmp-probe')` na diferença. **Apague a rota** e rode de novo: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/api/test_rbac.py
git commit -m "test(api): cover every api route with a role matrix and cross-workspace 404s"
```

---

### Task 8: Senha e token nunca no log

**Files:**
- Create: `tests/api/test_logging.py`

- [ ] **Step 1: Escrever o teste**

`tests/api/test_logging.py`:

```python
import logging
from contextlib import nullcontext

from api import cli


def test_secrets_never_reach_the_log(caplog, capsys, monkeypatch, db, client, make_client, make_user, login_as, password):
    caplog.set_level(logging.DEBUG)
    root = make_user("root@x.com", platform=True)
    ana = make_user("ana@x.com")
    wrong, new = "senha-errada-xyz-123", "nova-senha-secreta-1"

    client.post("/api/auth/login", json={"email": "ana@x.com", "password": wrong})
    login_as(client, ana)
    ana_token = client.cookies["gem_session"]
    client.post("/api/auth/password", json={"current": password, "new": new})

    admin = make_client()
    login_as(admin, root)
    temp = admin.post(f"/api/admin/users/{ana.id}/reset-password").json()["temp_password"]

    monkeypatch.setattr(cli, "SessionLocal", lambda: nullcontext(db))
    cli.main(["create-admin", "novo@x.com", "Novo"])
    cli_temp = capsys.readouterr().out.split(": ", 1)[1].strip()

    log = caplog.text
    for event in ("auth.login_failed", "auth.login_ok", "auth.password_changed", "auth.password_reset"):
        assert event in log, f"{event} not logged: the test would pass vacuously"
    for secret in (password, wrong, new, temp, cli_temp, ana_token, admin.cookies["gem_session"]):
        assert secret not in log
```

- [ ] **Step 2: Rodar**

Run: `uv run pytest tests/api/test_logging.py -q`
Expected: `1 passed`. Se falhar em "not logged", verifique se o `api/migrations/env.py` ficou com `disable_existing_loggers=False` (Task 2, Step 3).

- [ ] **Step 3: Commit**

```bash
git add tests/api/test_logging.py
git commit -m "test(api): assert passwords and session tokens never reach the log"
```

---

### Task 9: Documentação

**Files:**
- Modify: `DATABASE.md`, `API-GUIDE.md`, `SECURITY.md`, `CODE-STYLE.md`, `CLAUDE.md`, `docs/decisoes/README.md`, `docs/m2/trilha-b-plataforma.md`, `.env.example`
- Create: `docs/decisoes/auth.md`

Edite com `Edit` (não com heredoc de shell). Mantenha o tom e a densidade dos arquivos.

- [ ] **Step 1: `DATABASE.md`**

Troque o parágrafo `Ainda nenhuma: o B0 deixou o Alembic sem revisões. O B1 cria as quatro primeiras.` e a tabela abaixo dele por:

```markdown
Models em `api/models.py` (`Base` em `api/db.py`).

| Tabela | Colunas-chave | Migration |
|---|---|---|
| `users` | email único (minúsculo), nome, `password_hash` (scrypt), `must_change_password`, `is_platform_admin`, `active`, `failed_logins`, `locked_until` | `0001` |
| `workspaces` | nome, slug único e imutável, `settings jsonb` (default `{}`) | `0001` |
| `memberships` | PK `(user_id, workspace_id)`, `role` enum `membership_role` (admin\|analyst\|viewer) | `0001` |
| `sessions` | PK `token_hash` (sha256 do token), `user_id`, `created_at`, `last_seen_at` | `0001` |
```

Troque a linha que começa com `` - `api/migrations/env.py` lê `DATABASE_URL` `` por:

```markdown
- `api/migrations/env.py` lê `DATABASE_URL` de `api/db.py` (a URL não vai no `.ini`) e usa `Base.metadata` (`import api.models` registra as tabelas). `fileConfig(..., disable_existing_loggers=False)`: os testes rodam o Alembic no mesmo processo e o default calaria os loggers da API.
- `tests/api/test_migrations.py` compara migrations e models (`compare_metadata`); model novo sem migration quebra o teste.
```

Troque a última linha da seção "Sessão e testes" (a que começa com `- Teste que escreve no banco roda dentro de rollback`) por:

```markdown
- Testes usam o banco `app_test` (`TEST_DATABASE_URL`), que o `tests/conftest.py` cria se faltar; o conftest força `DATABASE_URL` para ele antes de importar `api`, então pytest nunca toca o banco de dev. `alembic upgrade head` roda uma vez por sessão (fixture `schema`).
- Cada teste roda numa transação externa com `Session(join_transaction_mode="create_savepoint")` e rollback no fim; o `get_db` da app é sobrescrito por essa sessão. Duas rodadas de `pytest` simultâneas funcionam, mas podem esperar lock.
```

- [ ] **Step 2: `API-GUIDE.md`**

Na tabela de endpoints, depois da linha do `/api/health`:

```markdown
| POST | `/api/auth/login` | **Público.** `{email, password}` → corpo do `/api/me` + cookie `gem_session`. 401 `invalid_credentials`, 429 `{detail: "locked", retry_after_s}` |
| POST | `/api/auth/logout` | Sessão. 204, limpa o cookie |
| POST | `/api/auth/password` | Sessão (aceita troca pendente). `{current, new}` (≥ 12). 204; 400 `invalid_current_password`; 422 `password_unchanged`. Derruba as outras sessões |
| GET | `/api/me` | Sessão (aceita troca pendente). `{id, email, name, is_platform_admin, must_change_password, workspaces: [{slug, name, role}]}` |
| GET | `/api/w/{slug}/members` | Admin do ws. `[{user_id, email, name, role, active}]` |
| POST | `/api/w/{slug}/members` | Admin do ws. `{email, name, role}` → 201 + `temp_password` (só se a conta foi criada agora; senão `null`). 409 se já é membro |
| PATCH | `/api/w/{slug}/members/{user_id}` | Admin do ws. `{role}` |
| DELETE | `/api/w/{slug}/members/{user_id}` | Admin do ws. Remove só a membership; 204 |
| GET | `/api/admin/workspaces` | Platform admin |
| POST | `/api/admin/workspaces` | Platform admin. `{name, slug}` (`^[a-z0-9-]{2,40}$`); 409 slug repetido |
| GET | `/api/admin/users` | Platform admin. `[{id, email, name, active, is_platform_admin, locked_until}]` |
| POST | `/api/admin/users/{user_id}/reset-password` | Platform admin. `{temp_password}`; derruba as sessões e desbloqueia |
| PATCH | `/api/admin/users/{user_id}` | Platform admin. `{active}`; desativar derruba as sessões |
```

Troque o parágrafo `Os demais entram com B1 (auth, membros, workspaces), B2 …` por:

```markdown
Os demais entram com B2 (upload e validação), B3 (sugestão de parâmetros), B4 (runs e log em tempo real), B5–B9. Cada rota nova ganha uma linha aqui **e** uma entrada em `ROUTES` de `tests/api/test_rbac.py` no mesmo commit; o teste falha se uma rota `/api/*` ficar de fora.
```

Nas **Regras**, troque o item `- **Escopo por workspace** via dependência do FastAPI que checa a membership (B1). …` por:

```markdown
- **Escopo por workspace**: rota de dado de cliente vive sob `/api/w/{slug}/…` e recebe `ctx: Ctx = Depends(require_role("viewer"|"analyst"|"admin"))` (`api/auth.py`); queries filtram por `ctx.workspace.id`. Workspace inexistente ou sem membership → **404, nunca 403**; papel insuficiente → 403. Rotas fora de workspace usam `current_user` (aceita troca de senha pendente), `active_user` ou `require_platform_admin`.
- **`detail` dos erros de auth é código estável** (`not_authenticated`, `invalid_credentials`, `locked`, `password_change_required`, `bad_origin`, `invalid_current_password`, `password_unchanged`): o front decide o fluxo por ele e traduz para pt-BR. Os demais erros trazem a mensagem pt-BR pronta.
```

E no item **Status de erro**, troque `401 sem sessão ou cookie adulterado;` por `401 sem sessão ou cookie adulterado; 403 papel insuficiente, troca de senha pendente ou \`Origin\` de outro site;`.

- [ ] **Step 3: `SECURITY.md`**

Troque a frase `As regras de auth abaixo são o alvo do B1 (\`docs/m2/trilha-b-plataforma.md\`); marque aqui o que já está implementado ao entregar.` por `As regras de auth e escopo abaixo estão implementadas desde o B1a (21/out/2026); as telas são do B1b.`

Na seção **Auth**, acrescente ao fim:

```markdown
- Sessão deslizante: expira com 8h sem uso, teto de 7d desde o login. Troca de senha derruba as outras sessões; reset e desativação derrubam todas.
- Mutações (`POST/PUT/PATCH/DELETE` em `/api/*`) com `Origin` de outro host → 403, além do `SameSite=Lax`.
- Conta é do platform admin (reset, desativar); membership é do admin do workspace (adicionar, papel, remover). Bootstrap do primeiro platform admin: `mise run create-admin <email> <nome>`, nunca senha em env.
```

Troque a seção **Mexer em auth** inteira por:

```markdown
## Mexer em auth

- `api/passwords.py` — scrypt (params dentro do hash), `dummy_hash` contra timing, senha temporária.
- `api/auth.py` — sessão (cookie, hash, expiração), login e bloqueio, dependências `current_user` / `active_user` / `require_role` / `require_platform_admin`, middleware `check_origin`.
- `api/accounts.py` — troca e reset de senha, membros, workspaces, desativar, `create_platform_admin`.
- `api/routes/auth.py`, `members.py`, `admin.py` — rotas finas.
- `api/cli.py` — `create-admin`.
- `tests/api/test_rbac.py` — matriz papel × rota; rota nova entra na tabela `ROUTES`.

O porquê de cada escolha: `docs/decisoes/auth.md`.
```

- [ ] **Step 4: `CODE-STYLE.md`**

Na seção **Testes**, troque o item `- Teste que precisa de Postgres pula (\`pytest.skip\`) quando …` por:

```markdown
- Teste que precisa de Postgres pede o fixture `db` (`tests/conftest.py`) e **falha** se o banco estiver fora do ar: um skip esconderia o RBAC no CI. O CI tem um service `postgres:16`. Exceção: `test_health_reports_db_ok`, que testa justamente o `ping()`.
- Fixtures prontos: `client`/`make_client` (`https://testserver`, senão o cookie `Secure` não volta), `make_user`, `make_workspace`, `login_as`, `password`. O scrypt cai para N=2¹⁴ nos testes (`fast_scrypt`).
```

- [ ] **Step 5: `docs/decisoes/auth.md` (novo)**

```markdown
# Auth, sessão e workspaces

Decisões do B1a, 21/out/2026. Spec: `docs/superpowers/specs/2026-10-21-b1a-auth-backend-design.md`.

## Token opaco no banco, não cookie assinado nem JWT

**Sintoma:** o protótipo guardava `user_id` no cookie sem assinatura; trocar o número logava como outro usuário. **Decisão:** o cookie `gem_session` leva só um token aleatório de 32 bytes; o banco guarda o sha256 dele. Revogar é apagar a linha: logout, troca de senha, reset e desativação têm efeito imediato, o que um JWT não dá sem lista de revogação. Custo: uma leitura por request, irrelevante no volume do M2.

## Sessão deslizante de 8h com teto de 7d

O analista passa o dia na ferramenta; uma sessão fixa curta o desloga no meio de um run, uma fixa longa deixa um cookie roubado valer uma semana inteira sem uso. Expira após 8h ociosa, renova a cada uso (no máximo um `UPDATE` por minuto) e morre em 7d de qualquer jeito.

## `SameSite=Lax` + checagem de `Origin`

A API serve o SPA na mesma origem, então `Lax` basta para o navegador não mandar o cookie em POST de outro site. A checagem de `Origin` nas mutações é a segunda camada, e existe porque a integração com o Almap Metrics (B10) não está definida: se virar iframe cross-site, o cookie precisa de `SameSite=None` e o `Origin` passa a ser a proteção de CSRF. Compara só o host, não o esquema: o Cloud Run termina o TLS e a app vê `http` enquanto o navegador manda `https://`. Request sem `Origin` passa (CLI, curl, testes); navegador sempre manda em POST.

## 404 entre workspaces, 403 para papel insuficiente

Recurso de outro workspace responde igual a recurso inexistente; um 403 confirmaria que o slug existe. Dentro do próprio workspace o usuário já sabe que ele existe, então papel insuficiente é 403 honesto e o front pode explicar.

## Platform admin é admin em todo workspace

BRD › Journey 3: o Data Tech cria workspaces e usuários, monitora uso e logs de job e cuida da retenção. Isso exige enxergar dentro dos workspaces, então ele passa no `require_role` como `admin` sem precisar de membership.

## Conta é do platform admin, membership é do workspace

Um analista da Almap atende várias marcas. Se o admin da marca X pudesse resetar a senha ou desativar a conta, mexeria no acesso dele à marca Y. Então o admin do workspace adiciona (criando a conta se não existir), troca papel e remove; reset e desativação são do platform admin. Senha temporária aparece uma vez na resposta e o admin a passa por fora; sem e-mail no M2.

## Bloqueio por conta, não por IP

5 falhas seguidas bloqueiam a conta por 15 min; acerto zera o contador. Conta bloqueada responde 429 e com isso revela que existe, o que é aceitável porque as contas são criadas por admin. E-mail inexistente roda um scrypt mesmo assim, para o tempo de resposta não separar os casos. Rate limit por IP fica para o B11.

## scrypt da stdlib

`hashlib.scrypt` com N=2¹⁷, r=8, p=1 (mínimo da OWASP), sem dependência nova. Cada login usa ~128 MB de RAM por ~0,3 s; considere isso ao dimensionar a instância do Cloud Run. Os parâmetros ficam no hash, então subir o custo depois não invalida senhas antigas.

## Bootstrap por CLI

Sem auto-cadastro, alguém cria o primeiro platform admin: `mise run create-admin <email> <nome>` (em produção, Cloud Run Job one-off com o mesmo comando). Seed por env deixaria uma senha morando num secret para sempre.

## `detail` em código estável nos erros de auth

O front precisa decidir o fluxo (mandar para a troca de senha, mostrar o tempo de bloqueio), então esses `detail` são códigos e a tradução para pt-BR fica na apresentação. Erros sem fluxo especial, como o 409, já vêm em pt-BR.
```

- [ ] **Step 6: `docs/decisoes/README.md`**

Acrescente na tabela: `| [auth.md](auth.md) | Sessão, cookie, CSRF, 404 × 403, papéis, bloqueio, bootstrap |`

- [ ] **Step 7: `docs/m2/trilha-b-plataforma.md`**

Logo abaixo do título `## B1 · Autenticação, papéis e workspaces — semanas 1–2`, antes de `- **BRD:**`, acrescente (no formato da linha `Status` do B0):

```markdown
- **Status:** 🟡 B1a (backend) feito em 21/out/2026: tabelas, sessão, bloqueio, RBAC por workspace, rotas de membros e admin, CLI `create-admin`; aceite verificado por `tests/api/test_rbac.py`, `test_auth.py` e `test_logging.py`. B1b (telas) pendente. Em aberto respondido: reset só pelo admin; contas do protótipo não migram.
```

- [ ] **Step 8: `CLAUDE.md`**

Na árvore de **Estrutura**, troque as linhas de `api/` até `migrations/` por:

```
api/              Python 3.13 + FastAPI + SQLAlchemy 2 + Alembic + psycopg 3 (uv)
  main.py         create_app(): middleware de Origin, routers e SPA com fallback para index.html
  db.py           DATABASE_URL, engine, SessionLocal, Base, get_db, ping()
  models.py       User, Workspace, Membership, UserSession
  passwords.py    scrypt
  auth.py         sessão, login, bloqueio, dependências de escopo (require_role…)
  accounts.py     regra de negócio de contas, membros e workspaces
  routes/         routers finos (auth, members, admin)
  cli.py          python -m api.cli create-admin
  worker.py       entrypoint do Cloud Run Job (python -m api.worker)
  alembic.ini     config do Alembic (rodar sempre com -c api/alembic.ini)
  migrations/     revisões Alembic (env.py lê DATABASE_URL de api/db.py)
```

Em **Rodando o projeto**, depois do passo 2 (`mise run db-migrate`), acrescente: `3. \`mise run create-admin voce@exemplo.com "Seu Nome"\` — cria o primeiro platform admin e imprime a senha temporária (troca obrigatória no 1º login).` e renumere os seguintes.

Troque o parágrafo **Estado atual** por:

```markdown
**B0 (esqueleto) concluído em 21/out/2026**: API com `/api/health`, SPA servida com fallback, worker stub, Postgres no compose, imagem única, CI (`py` com Postgres + `web`). **B1a (auth backend) concluído em 21/out/2026**: tabelas `users`/`workspaces`/`memberships`/`sessions` (migration `0001`), sessão por cookie opaco com expiração deslizante, bloqueio por falhas, troca de senha obrigatória, RBAC por workspace (`require_role`, 404 entre workspaces), rotas de membros e de platform admin, CLI `create-admin`. Faltam, em ordem: B1b (telas de login, troca de senha, seletor de workspace, admin), B2–B4 (upload, Gemini, jobs), B5–B9, B10 (visual, contínuo), B11 (deploy). A Trilha A (`engine/`) é do outro dev.
```

Na tabela **Onde as decisões estão escritas**, acrescente: `| Auth, sessão, papéis, workspaces | \`docs/decisoes/auth.md\` |`

- [ ] **Step 9: `.env.example`**

Acrescente depois do bloco do `DATABASE_URL`:

```bash
# Banco dos testes (pytest cria se faltar e nunca usa o DATABASE_URL de dev)
# TEST_DATABASE_URL=postgresql+psycopg://app:app@localhost:5432/app_test
```

- [ ] **Step 10: Commit**

```bash
git add DATABASE.md API-GUIDE.md SECURITY.md CODE-STYLE.md CLAUDE.md docs/decisoes/auth.md docs/decisoes/README.md docs/m2/trilha-b-plataforma.md .env.example
git commit -m "docs: record b1a auth decisions, routes, tables and status"
```

---

### Task 10: Verificação final

- [ ] **Step 1: Suíte inteira**

Run: `uv run pytest -q`
Expected: `115 passed`, zero skipped. Cole a última linha no relatório.

- [ ] **Step 2: Front continua compilando**

Run: `cd web && bunx tsc -b && bun run build`
Expected: sem erro (o B1a não toca `web/`, mas o CI roda isso).

- [ ] **Step 3: Smoke com servidor real**

```bash
mise run db-migrate
mise run create-admin root@exemplo.com "Root"     # anote a senha temporária
uv run uvicorn api.main:app --port 8000           # em outro terminal / background
curl -si -X POST localhost:8000/api/auth/login -H 'content-type: application/json' \
  -d '{"email":"root@exemplo.com","password":"<temp>"}'
```

Expected: `200`, header `set-cookie: gem_session=...; HttpOnly; Path=/; SameSite=lax; Secure`. Depois, com o token:

```bash
curl -s -b 'gem_session=<token>' localhost:8000/api/me                 # must_change_password: true
curl -s -b 'gem_session=<token>' localhost:8000/api/admin/users        # {"detail":"password_change_required"}
curl -s -X POST -H 'Origin: https://evil.example' -H 'content-type: application/json' \
  -d '{}' localhost:8000/api/auth/login                                # {"detail":"bad_origin"}
```

Se `mise run create-admin root@exemplo.com "Root"` não repassar os argumentos, rode `uv run python -m api.cli create-admin root@exemplo.com "Root"` e ajuste a task no `mise.toml`.

Apague o usuário de smoke do banco de dev depois, se quiser: `docker compose exec postgres psql -U app -c "delete from users where email='root@exemplo.com'"`.

- [ ] **Step 4: Downgrade/upgrade de novo** (agora com dados)

```bash
uv run alembic -c api/alembic.ini downgrade base && uv run alembic -c api/alembic.ini upgrade head
```

Expected: sem erro.

- [ ] **Step 5: CI**

Push da branch só com autorização do usuário. Depois do push, confirme os jobs `py` (com Postgres) e `web` verdes no GitHub Actions antes de abrir o PR.
