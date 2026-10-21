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

Ainda nenhuma: o B0 deixou o Alembic sem revisões. O B1 cria as quatro primeiras.

| Tabela | Colunas-chave | Migration |
|---|---|---|
| `users` | email único, nome, hash, `is_platform_admin`, `active` | B1 (planejada) |
| `workspaces` | nome, slug único, `settings jsonb` | B1 (planejada) |
| `memberships` | `(user_id, workspace_id)` único, `role` admin\|analyst\|viewer | B1 (planejada) |
| `sessions` | hash do token, `user_id`, `expires_at` | B1 (planejada) |

Atualize esta tabela no mesmo commit da migration (linha deixa de ser "planejada" e ganha o id da revisão).

## Migrations

- Uma migration por mudança, com `downgrade` que funciona.
- Rodar sempre com `-c api/alembic.ini`: `mise run db-migrate` aplica; `uv run alembic -c api/alembic.ini revision -m "…"` cria.
- `api/migrations/env.py` lê `DATABASE_URL` de `api/db.py` (a URL não vai no `.ini`). `target_metadata` é `None` hoje; o B1 troca para o `Base.metadata`.
- Valor novo de enum do Postgres não pode ser usado na transação em que foi adicionado.

### Nova coluna ou tabela

model (`api/…`) → `uv run alembic -c api/alembic.ini revision -m "…"` → teste → schema Pydantic → tipo em `web/src/` → linha na tabela acima.

## Sessão e testes

- `engine` com `pool_pre_ping` e `connect_timeout=2` (`api/db.py`): banco fora do ar falha rápido em vez de pendurar o health.
- Teste que escreve no banco roda dentro de rollback; `alembic upgrade head` sobe o schema uma vez por sessão de testes. Duas rodadas de `pytest` simultâneas contra o mesmo banco podem se atrapalhar.
