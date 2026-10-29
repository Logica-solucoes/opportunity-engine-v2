# Banco de dados

Postgres 16 (Docker no dev, Cloud SQL em produção), SQLAlchemy 2 com `DATABASE_URL` em `api/db.py` (default `postgresql+psycopg://app:app@localhost:5432/app`), migrations Alembic em `api/migrations/`. O `docs/m2/README.md` vence em dúvida de schema; o Postgres é a fonte de verdade de runs (BigQuery guarda só mídia e cópia analítica).

## Regras

- **Escopo**: toda tabela de dado de cliente tem `workspace_id` e toda query filtra por ele (`SECURITY.md`).
- **Nomes** de tabela, coluna e enum em inglês, minúsculos com `_`.
- **Dinheiro**: `NUMERIC`, nunca `float`. Escala e precisão definidas no B2/B5 quando a primeira coluna monetária aparecer; registre aqui.
- **Configuração flexível** (`workspaces.settings`, `gate_thresholds`) em `jsonb`; o que se filtra ou junta vira coluna.
- **Derivado, nunca materializado** quando a leitura é barata; guarde snapshot só de propósito, e anote aqui qual e por quê.
- Senha em hash `scrypt`; sessão guarda **hash** do token, nunca o token (`SECURITY.md`).
- "Hoje" e datas de run saem do relógio do servidor em UTC; converta para fuso só na apresentação.

## Tabelas

Models em `api/models.py` (`Base` em `api/db.py`).

| Tabela | Colunas-chave | Migration |
|---|---|---|
| `users` | email único (minúsculo), nome, `password_hash` (scrypt), `must_change_password`, `is_platform_admin`, `active`, `failed_logins`, `locked_until` | `0001` |
| `workspaces` | nome, slug único e imutável, `settings jsonb` (default `{}`; chave `google` = config do conector (B8, formato `GoogleConfig` de `api/google_import.py`, gravada só pelo platform admin)) | `0001` |
| `memberships` | PK `(user_id, workspace_id)`, índice em `workspace_id`, `role` enum `membership_role` (admin\|analyst\|viewer) | `0001`, `0002` |
| `sessions` | PK `token_hash` (sha256 do token), `user_id`, `created_at`, `last_seen_at` | `0001` |
| `simulations` | `workspace_id` (index), `name`, `config jsonb` (rascunho do `EngineConfig`; o B2 grava `column_mapping`), `validation jsonb` (último `ValidationReport`: snapshot de propósito, revalidar relê o CSV inteiro; zerado a cada upload), `created_by`, `created_at`, `updated_at` | `0003` |
| `simulation_files` | PK `(simulation_id, kind)`, `kind` enum `simulation_file_kind` (investment\|performance\|trends), `sha256` (compõe a chave no storage), `filename` (só exibição), `size_bytes`, `columns jsonb` (cabeçalho), `uploaded_by`, `uploaded_at` | `0003` |
| `runs` | `workspace_id` (index, desnormalizado para escopo direto), `simulation_id` (index), `status` enum `run_status` (queued\|running\|succeeded\|inconclusive\|failed), `config jsonb` e `inputs jsonb` (snapshot: o run nunca relê a simulação), `confirmed_warnings jsonb`, `engine_version`, `results_uri`, `summary jsonb`, `error` (pt-BR para a tela), `published_at/by` (B6), `created_by`, `created_at`, `started_at`, `finished_at`. Índice único parcial `runs_one_active_per_simulation` em `simulation_id` com status ativo | `0004` |
| `run_logs` | `id` identity (ordem e cursor do SSE), `run_id` (index), `ts`, `level`, `message` (pt-BR) | `0004` |
| `usage` (view) | uma linha por `workspace_id` × `user_id` (`runs.created_by`) × `month` (`YYYY-MM` em `America/Sao_Paulo`); `succeeded`, `inconclusive`, `failed`, `active` (queued + running), `total`, `run_seconds` (soma de `finished_at − started_at`, com o fim limitado a 20 min depois de `created_at`: run morto não infla o tempo). Lida com `sqlalchemy.table()` em `api/usage.py`, sem model | `0005` |

Atualize esta tabela no mesmo commit da migration (linha deixa de ser "planejada" e ganha o id da revisão).

## Migrations

- Uma migration por mudança, com `downgrade` que funciona.
- Rodar sempre com `-c api/alembic.ini`: `mise run db-migrate` aplica; `uv run alembic -c api/alembic.ini revision -m "…"` cria.
- `api/migrations/env.py` lê `DATABASE_URL` de `api/db.py` (a URL não vai no `.ini`) e usa `Base.metadata` (`import api.models` registra as tabelas). `fileConfig(..., disable_existing_loggers=False)`: os testes rodam o Alembic no mesmo processo e o default calaria os loggers da API.
- `tests/api/test_migrations.py` compara migrations e models (`compare_metadata`); model novo sem migration quebra o teste.
- Valor novo de enum do Postgres não pode ser usado na transação em que foi adicionado.

### Nova coluna ou tabela

model (`api/…`) → `uv run alembic -c api/alembic.ini revision -m "…"` → teste → schema Pydantic → tipo em `web/src/` → linha na tabela acima.

## Sessão e testes

- `engine` com `pool_pre_ping` e `connect_timeout=2` (`api/db.py`): banco fora do ar falha rápido em vez de pendurar o health.
- Testes usam o banco `app_test` (`TEST_DATABASE_URL`), que o `tests/conftest.py` cria se faltar; o conftest força `DATABASE_URL` para ele antes de importar `api`, então pytest nunca toca o banco de dev. `alembic upgrade head` roda uma vez por sessão (fixture `schema`).
- Cada teste roda numa transação externa com `Session(join_transaction_mode="create_savepoint")` e rollback no fim; o `get_db` da app é sobrescrito por essa sessão. Duas rodadas de `pytest` simultâneas funcionam, mas podem esperar lock.
