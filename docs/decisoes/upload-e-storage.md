# Upload e storage

Decisões do B2 (spec `docs/superpowers/specs/2026-10-26-b2-upload-validacao-design.md`).

## Simulação é um rascunho no banco

O analista cria a simulação e vai preenchendo: arquivos (`simulation_files`), mapeamento e, no B3, parâmetros (`simulations.config`, jsonb no formato do `EngineConfig`). Fechar a aba não perde nada, e o B3/B4 continuam o mesmo recurso. A alternativa (wizard só no front, submit no fim) perdia o progresso no reload e mandava até 90 MB numa requisição.

## Mapeamento antes da validação

O `trilha-b` listava "validar → confirmar mapeamento", mas o `validate` recebe o `column_mapping` dentro do config: sem saber qual coluna é a data e qual é o canal, não há como achar duplicata de (data, canal). A ordem é upload → mapeamento confirmado → validate. A sugestão de mapeamento sai da API (cabeçalho + apelidos em `suggest_mapping`), não do motor: é casamento de nomes, não matemática.

## 30 MB, não 200 MB

O protótipo aceitava 200 MB. O Cloud Run corta corpo de requisição HTTP/1 em 32 MiB, e o dado é agregado por dia e canal: 2 anos × 15 canais ≈ 11 mil linhas, menos de 1 MB. 30 MB é ~30× o arquivo real e cabe no Cloud Run sem signed URL. O Starlette grava o corpo inteiro em arquivo temporário antes do auth e do nosso teto rodarem; quem limita de fato é o Cloud Run (32 MiB). Fora dele (local, testes) não há teto de corpo.

## Storage local, endereçado por conteúdo

`api/storage.py` tem só `put` e `path` sobre `STORAGE_DIR`. O GCS entra no B11, quando houver bucket para testar; até lá uma implementação sem teste real seria só aparência. A chave `ws/{workspace_id}/sim/{simulation_id}/inputs/{sha256}.csv` dá rastreabilidade (o run do B4 guarda o sha256) e torna o re-upload idempotente. O blob substituído fica: quem apaga é a retenção do B9.

## Uma escrita por simulação

Upload e `PUT …/mapping` travam a linha da simulação (`FOR NO KEY UPDATE`, `simulations.lock`) antes de ler ou gravar os arquivos dela. Sem isso, um mapping que lia o arquivo antigo enquanto um re-upload entrava gravava `ok: true` para dados que nunca foram validados, e o B4 confiaria nesse report; e dois primeiros uploads do mesmo `kind` batiam na PK e viravam 500 (review de 26/out/2026). O upload trava só depois do `storage.put`, para não segurar a linha durante a escrita do arquivo. A trava do front (`useIsMutating`) evita a corrida na mesma aba; a do servidor cobre duas abas e duplo envio.

## Leitura do CSV

Encoding: o arquivo inteiro decodifica como `utf-8-sig`? senão `latin-1` (exports de BI brasileiros). Delimitador: o mais frequente de `,;\t|` na linha do cabeçalho. O `csv.Sniffer` foi descartado porque em arquivo com `;` e decimal com vírgula (`1.234,56`) a vírgula aparece em todas as linhas de dado e ele pode escolhê-la. Arquivo com byte NUL (ex.: export UTF-16 do Excel) é recusado no upload: o Postgres não aceita `\u0000` em jsonb.

## `validate` falso até o A2

O `engine/` não existe ainda. `api/validation.py` segue a assinatura e o formato do contrato §2 e implementa só `duplicate_date_channel`, o suficiente para o aceite "duplicata bloqueia o Rodar" rodar fim a fim. Quando o A2 sair, o módulo vira `from engine import validate` e o fake é apagado. O formato de `inputs` (`{"investment_file", "performance_file", "generic_trends_file"}` → caminho) foi proposto ao dev A no `docs/m2/README.md` › contrato §2.

## O gate do Rodar é do B4

O B2 só devolve o report; as confirmações de warning ficam na tela. Quem recusa um run com `error` ou warning não confirmado é a criação do run no B4, no servidor.

## Apagar simulação (B9)

Só o admin do workspace (e o platform admin, que o `require_role` trata como admin) apaga. Com run `queued`/`running` é 409: o worker gravaria o resultado numa pasta e numa linha que já não existem. A linha da simulação é travada `FOR UPDATE` antes da checagem, para um run criado ao mesmo tempo esperar e achar a simulação apagada.

A ordem é banco, depois storage. Apagar a linha leva `simulation_files`, `runs` e `run_logs` pelo `ON DELETE CASCADE`; depois sai a pasta `ws/{wid}/sim/{sid}/` inteira (entradas e `results.json`). Se o storage falhar, a resposta continua 204 e o log registra `simulation.files_orphaned` com o prefixo, para limpeza manual. O contrário (arquivos apagados e linhas de pé) deixaria runs apontando para arquivos que não existem. Retenção automática espera o prazo de LGPD do Data Tech.

Apagar a simulação também tira os runs dela do uso (a view `usage` lê `runs`). É de propósito: o hard delete é o que uma limpeza no estilo LGPD precisa, e um uso que sobrevivesse ao apagar exigiria uma tabela própria.

Limites conhecidos: um upload que ainda está gravando no storage quando o apagar confirma recria a pasta `inputs/` com um arquivo órfão (o `save_file` grava antes de travar a linha), e um worker vivo de um run já marcado como morto recria a pasta do run com um `results.json` órfão. Os dois são raros (o Job do Cloud Run expira em 15 min e o run só é morto aos 20) e ficam para o B11, junto com o GCS. Duas operações simultâneas sobre uma simulação que acabou de ser apagada dão 500, não 404.

## Telas (B2b e B9b)

- **Pré-preenchimento do mapping.** Um re-upload zera o `validation` mas mantém o `config.column_mapping`, que pode apontar para uma coluna que o arquivo novo não tem. A tela usa o salvo só se a coluna ainda existe e cai no `suggested` caso contrário (`initialColumn` em `web/src/lib/simulations.ts`). O backend não limpa o mapping: quem decide o que mostrar é a tela, e o `PUT …/mapping` recusa coluna inexistente de qualquer jeito.
- **Cache sem refetch.** Upload, mapping e criação devolvem o `SimulationOut` inteiro; a tela grava a resposta com `setQueryData` e só invalida a lista.
- **Rodar sempre desabilitado no B2.** O texto ao lado diz o motivo (não validado, erro, aviso sem confirmação) ou "Execução disponível em breve". As confirmações de aviso vivem no estado da página e zeram quando o report muda; o B4 as guarda com o run e confere o gate no servidor. Desde o B4 o Rodar funciona; o comportamento atual está em `runs-e-jobs.md` › Tela (B4b).
- **Arquivo checado antes do envio.** A tela recusa nome sem `.csv` ou acima de 30 MiB com a mesma mensagem da API, sem mandar o corpo. Acima de 32 MiB o 413 vem do próprio Cloud Run, em HTML, e sem essa checagem a tela mostraria "HTTP 413" ou "Falha de conexão". A API continua sendo quem decide.
- **Refetch que falha não apaga a página.** Só uma simulação que nunca carregou vira "Simulação não encontrada."; um 5xx no refetch de foco mantém os dados e o mapeamento não salvo.
- **Upload ao escolher o arquivo**, sem botão. A área de drag & drop é o `file-upload-04` do blocks.so sem a barra de progresso fake (o arquivo real é < 1 MB).
- **Apagar pede o nome.** A seção "Apagar simulação" fica no fim da página e só aparece para admin. O diálogo só habilita o botão com o nome exato digitado, e o botão é um `Button` comum, não o `AlertDialogAction`, para o 409 (run em andamento) aparecer no próprio diálogo. Ao apagar, a tela tira a simulação da lista em cache, navega para a lista e só então descarta a query da simulação (senão ela seria buscada de novo e daria 404) e as queries de runs inativas (o Voltar não mostra um run apagado). O Cancelar fica desabilitado enquanto o apagar está em andamento.
