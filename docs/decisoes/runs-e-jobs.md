# Runs e jobs

Decisões do B4, 27/out/2026. Spec: `docs/superpowers/specs/2026-10-27-b4-jobs-e-log-design.md`.

## `engine.run` falso em `api/`

O A0 ainda não entregou o `engine/`. `api/engine_run.py` segue a assinatura do contrato §3 (`run(inputs, config, out_dir, on_log) -> dict`, `on_log(level, message)`), emite seis etapas em pt-BR com pausa de `FAKE_ENGINE_STEP_SECONDS` e falha com `FAKE_ENGINE_FAIL=1`. Quando o motor existir, o módulo vira `from engine import run`. Mesmo caminho do `validate` (B2) e do `EngineConfig` (B3).

## Só o launcher local

`api/launcher.py` dispara `python -m api.worker <run_id>` por subprocess e não espera. O launcher do Cloud Run Jobs (override de env `RUN_ID`, que o worker já lê) entra no B11: sem projeto GCP, uma implementação só com mock seria aparência. Os testes trocam o `launch` por uma lista (fixture `launched`, autouse) e rodam `worker.execute` no processo.

## Gate no servidor

O `POST …/runs` refaz a conta do `runBlockReason` da tela, com as mesmas frases: sem validação, erro, aviso não confirmado (por `check.id`, guardado no run), parâmetros não salvos (`optimization_target` no `config`). Quem passa o gate ganha snapshot de `config` e do sha256 dos inputs: editar a simulação depois não muda o run, e o storage por conteúdo garante que o arquivo ainda existe.

## Um run ativo por simulação

Índice único parcial em `runs(simulation_id)` com status `queued`/`running`. O `IntegrityError` vira 409. Duplo clique ou duas abas não viram dois jobs pagos; editar arquivos ou parâmetros durante o run continua livre.

## Run morto sem heartbeat

O trilha-b pedia heartbeat. O Job tem timeout de 15 min, então run ativo com `created_at` há mais de 20 min está morto por definição, sem coluna nova. A API marca esses runs como `failed` ("A execução parou de responder.") ao criar run, ao ler run e lista, e a cada volta do stream. O worker grava o resultado com `WHERE status = 'running'`: um run já dado como morto não ressuscita. Localmente nada mata um worker pendurado; ele só deixa de importar depois dos 20 min.

## Uma linha de log por insert

O trilha-b pedia lote de 0,5 s. O motor emite centenas de linhas por run, não milhares, e o lote atrasaria a última linha antes de uma etapa longa, que é a que a tela usa para o "em andamento há N s". O worker faz insert e commit por linha na própria sessão. Se o motor ficar verboso, agrupar (marcado com `ponytail:` no `on_log`).

## Erro do motor nunca chega cru à tela

Exceção do motor vira `failed` com "O motor falhou. Detalhes técnicos ficam no log do servidor (execução N)." em `runs.error` e numa linha `error` do log. O traceback e a mensagem crua vão só para o stdout JSON (`severity`, `message`, `run_id`, `workspace_id`), que o Cloud Logging lê. A mensagem crua pode estar em inglês ou carregar dado do cliente. Pergunta ao dev A no contrato §3: uma exceção do motor com mensagem pt-BR própria para a tela.

## SSE com sessões curtas

`GET …/logs/stream` é um gerador assíncrono no `StreamingResponse`. A rota checa auth e escopo com a sessão da requisição e a devolve ao pool antes de abrir o stream; cada volta do laço (0,5 s) roda `poll` no threadpool (`run_in_threadpool`), que abre uma sessão curta, lê o status e depois as linhas novas (nessa ordem: o worker grava todas as linhas antes do status final); a espera entre voltas é `asyncio.sleep`. Sem `Last-Event-ID` vão as 300 últimas linhas; com ele, as de id maior, e o `EventSource` reconecta sozinho mandando o último id. Uma aba parada não segura thread (só as queries de cada volta passam pelo threadpool), e uma aba fechada é notada no próximo `await`. O front (B4b) deve chamar `close()` no `EventSource` ao receber `end`: o servidor encerrar a conexão faz o `EventSource` reconectar.

## Viewer e publicação

As rotas de leitura aceitam viewer, mas ele só enxerga run com `published_at`, que só o B6 preenche. Até lá, run não publicado é 404 para o viewer, como recurso de outro workspace.

## Tela (B4b)

- **Página própria do run** (`/w/$slug/execucoes/$runId`), onde os dashboards do B5 vão entrar. A simulação lista os runs dela (até 20); a lista do workspace é do B6.
- **`EventSource` nativo**, sem lib. Ele reconecta sozinho mandando `Last-Event-ID`; um fechamento sem `end` (401, 404) vira "Não foi possível acompanhar o log." O hook descarta linha com id menor ou igual à última, porque o segundo efeito do StrictMode reabre o stream e recebe o backlog de novo.
- **Status por polling curto** enquanto o run está ativo (2 s na página, 3 s na lista): `queued → running` não tem evento próprio. O `end` do stream invalida a query na hora.
- **"Etapa em andamento há N s"** é o relógio do navegador menos o `ts` da última linha, nunca negativo (relógios diferentes). É exibição, não conta do motor.
- **Confirmações de aviso** continuam por índice na tela e viram `check.id` no `POST`.
- **Rodar com run ativo** fica desabilitado com "Já há uma execução em andamento." e o link para ela; o 409 do servidor cobre duas abas e recarrega a lista, que passa a mostrar o run e o link. Rodar também fica desabilitado enquanto um upload ou um salvamento está em voo, para o run não sair dos dados anteriores.
