# Infra e operação

Decisões do B0 (esqueleto), 21/out/2026.

## Imagem única para API, SPA e worker

Um `Dockerfile` com três estágios (bun → build do `web/`, uv → venv, runtime). A API serve o `web/dist` no mesmo processo, então é um serviço Cloud Run só e **sem CORS**. O worker é a mesma imagem com outro comando (`python -m api.worker`), por isso o `Dockerfile` usa `CMD` e não `ENTRYPOINT`: `docker run <img> <cmd>` e o Cloud Run Job trocam o comando sem brigar com o entrypoint. O `CMD` é shell form (`sh -c "exec uvicorn … --port ${PORT:-8080}"`) para o `$PORT` do Cloud Run expandir.

## `COPY --chown` em vez de `chown -R`

**Sintoma:** a imagem saiu com 2.27GB. Um `RUN chown -R app:app /app` depois do `COPY` do venv criava uma segunda camada de ~820MB com os mesmos arquivos. **Decisão:** `COPY --chown=app:app` em cada cópia; nunca `chown -R` sobre o que já foi copiado. Resultado no repo antigo: 2.27GB → 1.22GB; no v2, com só as deps da API, **291MB**.

## Deps enxutas no v2

O `pyproject.toml` do v2 tem só o que a plataforma usa (fastapi, uvicorn, sqlalchemy, alembic, psycopg, pillow). As deps analíticas (pandas, scipy, statsmodels, scikit-learn, plotly…) entram junto com o `engine/` no A0, assim como o `COPY engine/ ./engine/` no `Dockerfile`. **Por quê:** o Streamlit e suas dependências pesavam ~900MB e não fazem parte da plataforma.

## `/api/health` sempre responde 200

Reporta `db: ok|down` no corpo, mas o status HTTP não depende do banco. **Por quê:** o healthcheck do container e a liveness do Cloud Run não devem matar a API por uma queda de banco que ela pode sobreviver. `db.ping()` usa `connect_timeout=2` para não pendurar a resposta.

## SPA com fallback e 404 JSON na API

`mount_spa()` registra um catch-all depois dos routers: arquivo existente em `web/dist` é servido, qualquer outra rota devolve `index.html` (o roteamento é do TanStack Router), e `/api/*` desconhecido vira 404 JSON. O caminho é resolvido e checado com `is_relative_to(dist)` para impedir path traversal (`/..%2Fsecret`). Sem `index.html` o SPA não é montado, o que deixa a API subir em dev sem build.

## Alembic dentro de `api/`

`api/alembic.ini` e `api/migrations/`, sempre chamados com `-c api/alembic.ini`. A URL não fica no `.ini`: `env.py` importa `DATABASE_URL` de `api/db.py` e escapa `%` (o configparser interpreta como interpolação). `target_metadata = None` até o B1 criar o `Base.metadata`.

## `routeTree.gen.ts` é versionado

O CI roda `tsc -b` antes de qualquer geração do plugin do TanStack Router, então o arquivo gerado precisa estar no git. `.gitattributes` força LF nele: com `autocrlf` o checkout em CRLF deixava o arquivo sujo com diff vazio.

## CI

`.github/workflows/ci.yml` com dois jobs: `py` (`uv sync --frozen` + `uv run pytest -q`) e `web` (`bun install --frozen-lockfile`, `bunx tsc -b`, `bun run build`). `tsc -b` e não `tsc --noEmit`: o `tsconfig.json` raiz só tem `references`, então `--noEmit` não checaria nada. O teste que depende de Postgres pula no CI (não há service de banco ainda).

## Porta 5432 e o compose de dev

O `docker-compose.yml` publica `5432:5432`. **Sintoma:** com outro Postgres local na 5432 (já aconteceu), o `docker compose up` falha. Libere a porta ou troque o mapeamento no seu compose.
