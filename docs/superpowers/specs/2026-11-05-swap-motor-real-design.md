# Swap da API para o motor real — design

A API ainda usa três falsos que esperavam a Trilha A: `api/engine_config.py` (`EngineConfig` provisório), `api/validation.py` (`validate` com um check) e `api/engine_run.py` (`run` que só escreve log). O A0, o A1 e o A2 estão no `main` desde 05/nov/2026. Este item troca os falsos pelo motor real seguindo os passos de `docs/decisoes/engine.md` › "Passos do swap". O dono é a Trilha B.

## Intenção

Um analista sobe os CSV, confirma o mapeamento, recebe o relatório do `engine.validate`, salva parâmetros validados pelo `EngineConfig` real, roda e recebe um `results.json` de verdade no storage. Os defaults e os limites dos parâmetros têm **uma fonte só**: o `engine/config.py` (contrato §1).

## Decisões

| Tema | Decisão |
|---|---|
| Fonte do `ParamsIn` | **Derivado do `EngineConfig` real na API** (`pydantic.create_model` sobre uma lista de campos). Copia default e limites de cada campo; não toca o código da Trilha A |
| Campos do formulário | Os de hoje (com os nomes novos dos `require_*`) mais `post_event_days`, `max_events_to_analyze` e `require_logical_direction`. `treat_outliers` fica no default (`false`): aceita lista de canais e o formulário gerado do schema não desenha isso |
| Regra entre campos | `REVENUE` exige `average_ticket` está num `model_validator` do `EngineConfig` e se perde no recorte. A rota `PUT …/params` checa a regra e devolve 422 com erro no campo (`["body", "average_ticket"]`, tipo `revenue_needs_ticket`). Fica na rota e não num `model_validator` do `ParamsIn` porque este daria `loc ["body"]`, que o formulário não consegue ligar a um campo |
| Configs salvos | Migration Alembic de dados renomeia `require_significance` → `require_statistical_significance` e `require_good_fit` → `require_model_fit` em `simulations.config` **e** `runs.config`, **mantendo os valores** (não dá para distinguir default provisório de escolha do analista). Os runs também, para a página do run e o "Rodar de novo" lerem os campos |
| `validate` | `api/validation.py` chama sempre o real: `engine.validate(inputs, config).model_dump(mode="json")`, também nos testes e no E2E (o `validate` falso some). Problema de dado é check no relatório, nunca exceção; `EngineError` (config que o motor recusa) vira `InvalidInput` → 422 com a mensagem do motor, em vez de 500. O caminho `csvfile.Unreadable` → 422 sai: valor ilegível vira o check `value_not_numeric` (e arquivo sem linha legível também ganha `no_valid_rows`) |
| `run` | `api/engine_run.py` chama `engine.run`. O worker continua guardando o dict que o `run` devolve (`json.dumps`), não envia o arquivo de `out_dir`: enviar o arquivo quebraria os testes que trocam o `run` por uma lambda, e o ganho é nulo (o dict é o mesmo documento) |
| Erro do motor no worker | `except EngineError as e`: `runs.error` e a linha de log recebem `str(e)` (pt-BR, segura para a tela). Qualquer outra exceção continua com a mensagem genérica |
| Fake | Só o `run` falso (`fake_run`, que só escreve log) fica atrás de `ENGINE_FAKE=1`, ligado pelo E2E (`web/e2e/env.ts`) e pela suíte da API (fixture autouse `fast_engine`). Ninguém liga em produção |
| Testes da API | A fixture autouse `fast_engine` liga `ENGINE_FAKE=1` (só afeta o `run`; o `validate` é sempre o real). Poucos testes de integração fazem `monkeypatch.delenv("ENGINE_FAKE")` e usam o `run` real com o dataset sintético curto do motor |

## Componentes

- **`api/engine_config.py`**: `ANALYST_FIELDS` (lista de nomes) e `ParamsIn = create_model("ParamsIn", __config__=…extra forbid…, **{campo: (anotação, FieldInfo) do EngineConfig})`. O `EngineConfig` provisório e o `FinancialTargets` locais saem; `from engine.config import EngineConfig` onde for preciso.
- **`api/validation.py`**: `validate(inputs, config) -> dict`, sempre o real com `model_dump(mode="json")`. Sem fake.
- **`api/engine_run.py`**: `run(...)`. Com `ENGINE_FAKE=1`, o fake de hoje (`STEPS`, `FAKE_ENGINE_STEP_SECONDS`, `FAKE_ENGINE_FAIL`); senão `engine.run`.
- **`api/simulations.py`**:
  - `save_mapping` captura `EngineError` → `InvalidInput(str(e))`;
  - a rota `PUT …/params` (`api/routes/simulations.py`) devolve 422 em `average_ticket` (`revenue_needs_ticket`) quando o alvo é `REVENUE` sem ticket; o comentário "the stand-in validate reads only the mapping" sai.
- **`api/worker.py`**: o ramo de `EngineError` e a checagem de `status` que já existe. O dict devolvido pelo `run` segue sendo o que se grava.
- **`api/migrations/versions/0006_rename_require_params.py`**: `UPDATE … SET config = config - 'old' || jsonb_build_object('new', config->'old') WHERE config ? 'old'`, nas duas tabelas e para as duas chaves. O `downgrade` faz o inverso.
- **`web/src/lib/params.ts`**: a seção Causal com os nomes novos e os 3 campos (labels em pt-BR). O tipo `Check` já aceita `info`, e a tela já mostra a `message` de qualquer id.
- **`web/e2e/env.ts`**: `ENGINE_FAKE: '1'`.

## Fluxo de erro

| Onde | O quê | Resultado |
|---|---|---|
| Salvar mapeamento | `EngineError` do `validate` (config inválido) | 422 com a mensagem do motor |
| Salvar mapeamento | Problema no dado | Check no relatório, como sempre (o `validate` real não levanta por dado) |
| Salvar parâmetros | Campo fora do limite | 422 do pydantic por campo (a tela já mostra) |
| Salvar parâmetros | `REVENUE` sem ticket | 422 na rota, com erro em `["body", "average_ticket"]` (`revenue_needs_ticket`, traduzido em `web/src/lib/params.ts`) |
| Run | `EngineError` (check de erro que escapou do gate, config inválido) | `failed`, `runs.error = str(e)` |
| Run | Outra exceção | `failed` com a mensagem genérica e o traceback no log |

## Testes

- **Unit da API:** a fixture autouse `fast_engine` liga `ENGINE_FAKE=1` e `FAKE_ENGINE_STEP_SECONDS=0`; só o `run` é falso, o `validate` é o real.
- **Integração, motor real** (`tests/api/test_engine_swap.py`, com `ENGINE_FAKE` removido), usando o `make_dataset` curto do motor (o `SHORT` do `tests/engine/conftest.py`):
  1. upload dos CSV sintéticos, confirmação do mapeamento: `simulation.validation` é o relatório real (`ok=True`, `cadence`, `channels`);
  2. com BLAS em 1 thread, `worker.execute` grava no storage um `results.json` com `schema_version=1` e um `status` final;
  3. `PUT …/params` com `REVENUE` sem ticket devolve 422 em `average_ticket`;
  4. um `EngineError` do run aparece em `runs.error` com a mensagem do motor.
- **Migration:** um config com as chaves velhas sai com as novas e os mesmos valores, nas duas tabelas.
- **`ParamsIn`:** para cada campo de `ANALYST_FIELDS`, default e limites iguais aos do `EngineConfig`; nome fora do `EngineConfig` quebra no import.
- **E2E:** sem mudança de fluxo, com `ENGINE_FAKE=1`.

## Fora do escopo

- Trocar `api/gemini.py` por `llm/` (tarefa separada).
- `treat_outliers` no formulário.
- Mostrar `details` dos checks na tela e qualquer dashboard (B5).
- O `incremental_investment` dos eventos (Trilha A).
- Import preguiçoso do `engine` na API: a carga de ~2 s acontece uma vez no boot. Revisitar se o reload do dev incomodar.

## Docs no mesmo commit

- `docs/decisoes/engine.md`: os passos do swap marcados como feitos.
- `docs/decisoes/upload-e-storage.md`: a seção do `validate` falso.
- `docs/decisoes/runs-e-jobs.md`: o erro do motor e o fake por env.
- `docs/decisoes/parametros-e-gemini.md`: o `ParamsIn` derivado.
- `CLAUDE.md`: árvore e "Estado atual".
- Contrato §1 em `docs/m2/README.md`: a API já usa o `EngineConfig`.
- `DATABASE.md`: a migration `0006`.
- `.env.example`: `ENGINE_FAKE`.

(Três ajustes depois do spec, já aplicados acima: `validate` sempre real, worker guarda o dict, regra do `REVENUE` na rota.)
