# Estilo de código

Simples, legível, fácil de depurar. Código só para o que é preciso agora, estruturado para que o segundo uso seja uma refatoração e não uma reescrita. Comentário só quando o **porquê** não se lê no código (contorno não óbvio, regra de negócio, troca deliberada); o que ele faz, o nome da função diz.

## Ferramentas

| | Backend (`api/`, `engine/`) | Frontend (`web/`) |
|---|---|---|
| Runtime e deps | Python 3.13 com `uv` (`pyproject.toml` + `uv.lock` na raiz) | `bun` |
| Format / lint | `ruff format` (linha 120) e `ruff check` (regras padrão menos B008, que é o `Depends()` do FastAPI), ambos no CI | `bun run lint` (oxlint) |
| Tipos | — | `bun run build` (`tsc -b` + vite) |
| Testes | `uv run pytest` | `bun run e2e` (Playwright, ver abaixo) |

O CI (`.github/workflows/ci.yml`) roda `ruff format --check`, `ruff check` e `uv run pytest -q` e, em `web/`, `bun run build` (que já roda o `tsc -b`) + `bun run lint` em todo push e PR; o job `e2e` roda o Playwright. Rode-os antes de dar uma tarefa como pronta. Tarefas do dia a dia estão no `mise.toml`.

`src/routeTree.gen.ts` é gerado (e versionado). Dependência Python nova entra com `uv add`, sempre commitando o `uv.lock`.

## Idioma

- Texto que o usuário lê (UI, mensagem de erro em `detail`): **pt-BR**.
- Tabela, coluna, enum, path de API e campo JSON: **inglês**. A tradução acontece só na apresentação.
- Funções, variáveis, módulos e nomes de teste: seguem o código ao redor (`engine/` herdou português do protótipo; `api/` e `web/` estão em inglês).
- Commits: conventional, minúsculos, concisos, em inglês como o histórico do repo (`feat(api): …`, `fix(web): …`). Um commit por grupo lógico.

## Erros

- Serviço levanta exceção de domínio; a rota traduz em status (`API-GUIDE.md`).
- `/api/health` responde 200 sempre e reporta `db: ok|down`: liveness não depende do banco.
- Tratamento defensivo só onde a falha perde dado ou quebra fluxo crítico.
- Erro de um evento ou canal não derruba o run inteiro.

## Logging

- **Nunca `print()`.** Todo módulo faz `log = logging.getLogger(__name__)`.
- Nível por impacto: `DEBUG` detalhe interno, `INFO` marco que o usuário vê, `WARNING` degradou mas segue (fallback, evento pulado), `ERROR` uma unidade de trabalho falhou, `CRITICAL` o run não continua.
- Exceção com `exc_info=True`, nunca `traceback.print_exc()`.
- Senha, token e chave nunca aparecem em log.

## Testes

- Teste novo nasce com o código (TDD): ver falhar, implementar, ver passar.
- Teste que precisa de Postgres pede o fixture `db` (`tests/conftest.py`) e **falha** se o banco estiver fora do ar: um skip esconderia o RBAC no CI. O CI tem um service `postgres:16`. Exceção: `test_health_reports_db_ok`, que testa justamente o `ping()`.
- Fixtures prontos: `client`/`make_client` (`https://testserver`, senão o cookie `Secure` não volta), `make_user`, `make_workspace`, `login_as`, `password`. O scrypt cai para N=2¹⁴ nos testes (`fast_scrypt`).
- Cada teste que escreve no banco roda dentro de um rollback (detalhes em `DATABASE.md`).
- `TestClient(create_app(web_dist=tmp_path))` para testar o SPA sem depender do build do `web/`.
- Front: E2E com Playwright em `web/e2e/` contra a app real (`mise run e2e`, banco `app_e2e`). Cada teste cria os próprios usuários e workspaces com sufixo aleatório; nada de depender de ordem ou de limpar o banco. Sem testes de componente por ora.

## Regras do motor (`engine/`, Trilha A)

Herdadas do protótipo; valem quando o `engine/` entrar (o A0 move os módulos de `scripts/` do repo antigo).

- **Nunca hardcode nome de coluna.** Resolva por `column_mapping`: `investment_file` (`date_col`, `channel_col`, `investment_col`), `performance_file` (`date_col`, `kpi_col`), `generic_trends_file` (`date_col`, `trends_col`). Datas viram uma coluna `Date` no pré-processamento.
- Respeite `optimization_target`: `"REVENUE"` (exige `average_ticket`) ou `"CONVERSIONS"`.
- Guardrails dinâmicos em `financial_targets` podam as curvas de saturação: `target_cpa`, `target_icpa`, `target_roas`, `target_iroas`.
- `treat_outliers` configurável (booleano ou lista de colunas).
- O motor decide o que é publicável: gate reprovado vira `status` + `reasons` no `results.json`; a camada de cima nunca refaz o julgamento (`docs/m2/README.md` › contrato).
- Se o Gemini estiver indisponível, caia limpo para relatório em Markdown.

## Fora do escopo

O que o BRD e o `docs/m2/README.md` cortam (ver seção de cortes e riscos) não se implementa, nem "para preparar terreno". Se algo parecer exigir um corte, pare e pergunte.
