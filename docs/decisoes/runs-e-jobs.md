# Runs e jobs

Decisões do B4, 27/out/2026. Spec: `docs/superpowers/specs/2026-10-27-b4-jobs-e-log-design.md`.

## `engine.run` real, com fake por env

`api/engine_run.py` chama o `engine.run` real (contrato §3: `run(inputs, config, out_dir, on_log) -> dict`) desde 05/nov/2026. Com `ENGINE_FAKE=1`, `fake_run` só emite seis etapas em pt-BR com pausa de `FAKE_ENGINE_STEP_SECONDS` e falha com `FAKE_ENGINE_FAIL=1` (as duas variáveis só valem com o fake). O fake é ligado só pelo E2E (`web/e2e/env.ts`) e pela suíte da API (fixture autouse `fast_engine`); nunca em produção. O worker continua guardando o dict que o `run` devolve, não o arquivo de `out_dir`.

## Só o launcher local

`api/launcher.py` dispara `python -m api.worker <run_id>` por subprocess e não espera. É o launcher de produção também: com a hospedagem em servidor próprio (`docs/decisoes/infra-e-operacao.md`, 04/nov/2026), o launcher do Cloud Run Jobs não vai existir. O worker ainda aceita `RUN_ID` por env, sobra do desenho antigo. Os testes trocam o `launch` por uma lista (fixture `launched`, autouse) e rodam `worker.execute` no processo.

## Gate no servidor

O `POST …/runs` refaz a conta do `runBlockReason` da tela, com as mesmas frases: sem validação, erro, aviso não confirmado (por `check.id`, guardado no run), parâmetros não salvos (`optimization_target` no `config`). Quem passa o gate ganha snapshot de `config` e do sha256 dos inputs: editar a simulação depois não muda o run, e o storage por conteúdo garante que o arquivo ainda existe.

## Um run ativo por simulação

Índice único parcial em `runs(simulation_id)` com status `queued`/`running`. O `IntegrityError` vira 409. Duplo clique ou duas abas não viram dois jobs pagos; editar arquivos ou parâmetros durante o run continua livre.

## Run morto sem heartbeat

O trilha-b pedia heartbeat. O desenho era um Cloud Run Job com timeout de 15 min, então run ativo com `created_at` há mais de 20 min está morto por definição, sem coluna nova. Sem o Job, quem mata o processo é o watchdog do worker (`worker.watchdog`, desde 05/nov/2026), no mesmo `STALE_AFTER`, saindo com código 124. A API marca esses runs como `failed` ("A execução parou de responder.") ao criar run, ao ler run e lista, e no stream a cada 15 s sem linha nova (junto com o ping, não a cada volta). O worker grava o resultado com `WHERE status = 'running'`: um run já dado como morto não ressuscita. Um worker pendurado se encerra sozinho aos 20 min pelo watchdog. Um worker que morre antes disso não espera os 20 min: ver "Reaper e limites" abaixo (o `STALE_AFTER` fica como rede de segurança).

## Reaper e limites (12/nov/2026)

Sintoma: o worker morria (OOM, Ctrl+C do `uvicorn --reload`, crash) e o run ficava `running` até o `fail_stale` dos 20 min.

- **Reaper.** `launcher.launch` sobe uma thread daemon `reap(proc, run_id)` que espera o subprocess. Saída 0: nada (o worker já gravou o status). Saída `TIMEOUT_EXIT = 124` (watchdog do worker; convenção do `timeout(1)`, e não o 3 do `abort()` no Windows): run `failed` com "A execução passou do limite de 20 minutos e foi interrompida. Agrupe canais ou encurte o período e rode de novo.". Outra saída diferente de 0: "A execução foi interrompida antes de terminar.". Só atualiza run ainda `queued`/`running` e grava uma linha de erro no `RunLog`. Erro de banco no reaper vira `run.reap_failed` no log JSON, e o `fail_stale` segue valendo; o mesmo se a API reiniciar (a thread morre com ela).
- **Windows.** O worker sobe com `CREATE_NEW_PROCESS_GROUP`: o Ctrl+C do `uvicorn --reload` matava o worker junto.
- **Rollback no `on_log`.** O handler de log do motor engole a exceção; sem `rollback` depois de um commit que falhou, o `UPDATE` final de status também falhava e o run ficava `running`.
- **`RUN_DEADLINE`.** O worker exporta o prazo (epoch, início + 20 min) para o motor; as narrativas usam para parar de chamar o LLM (`docs/decisoes/engine.md`).
- **Teto de runs simultâneos.** `MAX_CONCURRENT_RUNS` (padrão: núcleos − 1, mínimo 1). No teto, `POST /runs` dá 409 "Há muitas execuções em andamento no servidor. Tente de novo em alguns minutos.". Teto mole, sem lock (dois POSTs simultâneos podem passar). É a única query que conta runs de todos os workspaces, de propósito: o recurso é a CPU do servidor. O `fail_stale` roda em todos os workspaces antes da contagem, para run morto não ocupar vaga.
- **SGS fora da transação.** `POST /runs` faz `db.rollback()` antes das chamadas HTTP ao Banco Central, para não segurar transação nem conexão do pool durante a espera.

## Uma linha de log por insert

O trilha-b pedia lote de 0,5 s. O motor emite centenas de linhas por run, não milhares, e o lote atrasaria a última linha antes de uma etapa longa, que é a que a tela usa para o "em andamento há N s". O worker faz insert e commit por linha na própria sessão. Se o motor ficar verboso, agrupar (marcado com `ponytail:` no `on_log`).

## Erro do motor nunca chega cru à tela

Desde 05/nov/2026 o worker separa dois casos. `EngineError` (mensagem pt-BR segura para a tela, por contrato) vira `failed` com a mensagem do próprio motor em `runs.error` e no log, e o `check_id` vai para o log do servidor. Qualquer outra exceção do motor vira `failed` com "O motor falhou. Detalhes técnicos ficam no log do servidor (execução N)." em `runs.error` e numa linha `error` do log; o mesmo vale quando o motor devolve `status: "failed"` sem exceção (o `results.json` fica guardado). O traceback e a mensagem crua vão só para o stdout JSON (`severity`, `message`, `run_id`, `workspace_id`), que o `docker logs` do servidor mostra. A mensagem crua pode estar em inglês ou carregar dado do cliente.
## SSE com sessões curtas

`GET …/logs/stream` é um gerador assíncrono no `StreamingResponse`. A rota checa auth e escopo com a sessão da requisição e a devolve ao pool antes de abrir o stream; cada volta do laço (0,5 s) roda `poll` no threadpool (`run_in_threadpool`), que abre uma sessão curta, lê o status e depois as linhas novas (nessa ordem: o worker grava todas as linhas antes do status final); a espera entre voltas é `asyncio.sleep`. Sem `Last-Event-ID` vão as 300 últimas linhas; com ele, as de id maior, e o `EventSource` reconecta sozinho mandando o último id. Uma aba parada não segura thread (só as queries de cada volta passam pelo threadpool), e uma aba fechada é notada no próximo `await`. O front (B4b) deve chamar `close()` no `EventSource` ao receber `end`: o servidor encerrar a conexão faz o `EventSource` reconectar.

Depois de 15 s sem linha nova o stream manda um comentário (`: ping`), para proxy não derrubar a conexão parada durante uma etapa longa do motor. A auth e o escopo são checados só ao abrir o stream: quem sai, perde a sessão ou é removido do workspace continua recebendo as linhas daquele run até ele acabar (no máximo 20 min). É só leitura, de um run que a pessoa já podia ver; rechecar a sessão a cada volta não compensa.

## Histórico e publicação (B6)

Spec: `docs/superpowers/specs/2026-10-28-b6-historico-design.md`.

- **Publicar é revisão humana, não gate.** Os gates são do motor e vêm marcados no `results.json`; o analista só decide quando o viewer passa a ver o run. Só `succeeded` e `inconclusive` podem ser publicados (o inconclusivo mostra o experiment design, que interessa ao viewer). Publicar de novo atualiza quem e quando; despublicar é idempotente. Viewer só enxerga run com `published_at`, e o resto é 404, como recurso de outro workspace.
- **Filtros no front, sobre os últimos 500 runs.** `GET …/runs` devolve até 500 `RunOut`; busca, status, autor e período rodam na tela. Sem endpoint de autores e sem paginação. Passando de 500 runs por workspace, os mais antigos somem da busca: a saída é mover os filtros para query params (marcado com `ponytail:` na rota).
- **Download das entradas só para analyst+.** O viewer vê o resultado publicado, não o CSV bruto do cliente. O storage é por conteúdo, então o arquivo do snapshot continua lá depois de a simulação trocar o arquivo.
- **"Rodar de novo" restaura na simulação.** O front faz `PUT …/params` com o `config` do run e leva à simulação; o gate da B4 continua sendo o único caminho para criar run. Os arquivos são os atuais da simulação.
- **Fora até o A1:** comparar runs lado a lado e colunas de métricas do `summary` (hoje ele só repete o status). **Fora até haver dataset anonimizado e motor real:** o modo demo.

## Telas (B4b e B6b)

- **Página própria do run** (`/w/$slug/execucoes/$runId`), onde os dashboards do B5 vão entrar. A simulação lista os runs dela (até 20); a lista do workspace é do B6.
- **`EventSource` nativo**, sem lib. Ele reconecta sozinho mandando `Last-Event-ID`; um fechamento sem `end` (401, 404) vira "Não foi possível acompanhar o log." O hook descarta linha com id menor ou igual à última, porque um Fast Refresh reabre o stream mantendo as linhas e recebe o backlog de novo.
- **Status por polling curto** enquanto o run está ativo (2 s na página, 3 s na lista): `queued → running` não tem evento próprio. O `end` do stream invalida a query na hora.
- **"Etapa em andamento há N s"** é o relógio do navegador menos o `ts` da última linha, nunca negativo (relógios diferentes). É exibição, não conta do motor.
- **Confirmações de aviso** continuam por índice na tela e viram `check.id` no `POST`.
- **Rodar com run ativo** fica desabilitado com "Já há uma execução em andamento." e o link para ela; o 409 do servidor cobre duas abas e recarrega a lista, que passa a mostrar o run e o link. Rodar também fica desabilitado enquanto um upload ou um salvamento está em voo, para o run não sair dos dados anteriores, e enquanto a lista de runs carrega. O erro do último clique some quando um run começa ou termina. Quem sai da página durante o `POST` não é levado para o run.
- **Parâmetro editado e não salvo** desabilita Rodar com "Salve os parâmetros antes de rodar.": o run usa a config salva, não a da tela. A comparação é no formato do corpo do `PUT` ("0.20" na tela é igual a 0,2 salvo). O servidor não sabe da tela, então o gate dele não cobre isso.
- **Histórico em `/w/$slug/execucoes`.** Os filtros (busca, status, autor, período) ficam nos search params, com `replace` para a digitação não encher o histórico do navegador. O período compara o dia local de `created_at` com o `<input type="date">`. O autor é filtrado pelo nome, porque o `RunOut` não traz o id de quem criou.
- **Viewer cai no histórico.** A home do workspace redireciona o viewer no `beforeLoad`; para ele o histórico não tem o link "← Simulações", que voltaria em loop, e a página do run volta para "← Execuções" em vez da simulação, que ele não abre.
- **"Rodar de novo" no diálogo.** O botão de confirmar é um `Button` comum, não o `AlertDialogAction`, para o 422 (parâmetros que o motor atual não aceita mais) aparecer no próprio diálogo. O corpo do `PUT` leva só as chaves do `config` do run que estão no schema do `ParamsIn` (`/api/engine/config-schema`); `column_mapping` e o que o A3/A4 gravarem (`channel_groups`, `controls`, `gate_thresholds`) ficam como a simulação tem.
