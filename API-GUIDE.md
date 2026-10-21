# Guia da API

REST em FastAPI, tudo sob `/api`. O `docs/m2/README.md` vence em dúvida de contrato; o porquê do comportamento de cada rota está em `docs/decisoes/`. O OpenAPI do FastAPI fica em `/docs` (a exposição em produção é decisão do B11, ver `SECURITY.md`).

## Regras

- **Rota fina**: valida entrada, chama o serviço, traduz exceção de domínio em status. Regra de negócio fica fora da rota.
- **Escopo por workspace** via dependência do FastAPI que checa a membership (B1). Recurso de outro workspace → **404, nunca 403** (`SECURITY.md`).
- **Status de erro**: 401 sem sessão ou cookie adulterado; 404 recurso inexistente ou de outro workspace; 422 entrada inválida; provedor externo fora do ar degrada, nunca vira 500.
- **`/api/health` responde sempre 200** com `{"status":"ok","db":"ok|down"}`: liveness não depende do banco.
- **Ordem de declaração**: rota literal antes da parametrizada.
- **SPA**: `mount_spa()` registra o catch-all **depois** de todos os routers; `/api/*` desconhecido devolve 404 JSON (`{"detail":"Not Found"}`), nunca o `index.html`. Sem `web/dist/index.html` não há SPA. O diretório vem de `WEB_DIST` (default `web/dist`).
- Matemática (curva, CPA, ponto ótimo) vem pronta do `engine/` pela API; o front só exibe.

## Endpoints

| Método | Path | Observação |
|---|---|---|
| GET | `/api/health` | **Público.** Sempre 200; `db` reporta `ok` ou `down` |

Os demais entram com B1 (auth, membros, workspaces), B2 (upload e validação), B3 (sugestão de parâmetros), B4 (runs e log em tempo real), B5–B9. Cada rota nova ganha uma linha aqui no mesmo commit.

## Nova rota REST

router em `api/` → schemas Pydantic → serviço → `app.include_router` em `create_app()` (`api/main.py`) → teste em `tests/api/test_<recurso>.py` → tipo e `useQuery`/`useMutation` em `web/src/` → linha na tabela acima.

No frontend, chamadas vão para `/api/…` na mesma origem (o Vite faz proxy para `:8000` em dev). O front usa TanStack Query; invalide as queries afetadas depois de cada mutation.
