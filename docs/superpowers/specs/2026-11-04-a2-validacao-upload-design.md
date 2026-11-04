# A2 · Validação de upload e deduplicação — design

Item `A2` de `docs/m2/trilha-a-motor.md`. Depende de A0 e A1 (prontos); bloqueia B2 (swap do `validate` falso) e A3 (colinearidade, que roda dentro do mesmo `validate`).

## Intenção

O analista envia três CSV e confirma o mapeamento de colunas. Hoje a API chama um `validate` falso que só detecta `duplicate_date_channel`; o resto dos problemas aparece depois, no meio do `run`, ou nem aparece: investimento duplicado vira média, KPI com data repetida vira soma, e outliers são tratados sem aviso. O A2 entrega o `engine.validate(inputs, config) -> ValidationReport` do contrato (`docs/m2/README.md` §2) e faz o `run` obedecer ao mesmo veredito, de modo que **nenhum dado ambíguo seja corrigido em silêncio**.

## Objetivos

- `validate` síncrono, sem rodar modelo, com `id` estável por check e mensagem em pt-BR segura para a tela (sem caminhos nem dados do cliente).
- Reunir **todos** os problemas encontrados num só relatório (não parar no primeiro erro) sempre que for possível continuar lendo.
- O `run` e o `validate` concordam: um arquivo que o `validate` aprova, o `run` lê da mesma forma.
- O relatório vai no campo `validation` do `results.json` (tipo `ValidationReport` já existe em `engine/results_schema.py`, hoje `null`).

## Não-objetivos

- Colinearidade (`collinearity`) é do A3; o A2 devolve o campo vazio (`pairs=[]`, `vif={}`, `suggested_groups=[]`).
- Não muda a matemática do motor nem o adstock oculto para correlação negativa (A10).
- Não cria os templates CSV (dono: Data Analytics) nem aceita os layouts de PMAX/Tcross com canal na performance.
- Não troca a API para o motor real (swap é do Dev B).

## Anti-objetivo

Reintroduzir correção silenciosa como "aviso". Duplicata de (data, canal) e de data no KPI são **erros**, não warnings.

## Decisões já tomadas (com o dono)

- `kpi_not_single_source` é **erro**. Um arquivo de performance com coluna de canal (PMAX, Tcross: `Data;Canal;Leads`) não passa; a mensagem pede o total por data (ou por semana). Sem opção de somar.

## Abordagens consideradas

- **A. Módulo independente.** `validation.py` lê os CSV por conta própria; o preprocessor só troca exceções. Simples, mas dois leitores de CSV podem divergir.
- **B. Leitura compartilhada (escolhida).** Um passo único lê e normaliza os três arquivos e produz tabelas + checks. `validate` devolve os checks; `load_and_prepare_data` consome as mesmas tabelas e levanta `EngineError(check_id)` se houver `error`. Uma só fonte de verdade. Custo: mexe na cópia do protótipo; a paridade com Gol (1e-9) prova que dados limpos não mudam.
- **C. try/except em volta do `load_and_prepare_data`.** Só o primeiro erro e nenhum warning/info; não atende o item.

Escolha B: o dono delegou o "como", então é decisão minha.

## Desenho

### Arquivos

- `engine/inputs.py` (novo): `read_inputs(config, paths) -> RawInputs` com o que hoje está nas linhas ~766–910 de `load_and_prepare_data` (leitura, resolução de colunas, parse de data e número, remoção de rodapé de BI, remoção de linhas inválidas). Em vez de levantar `ValueError`, acumula `Check` na lista e devolve as tabelas parciais; só aborta quando não dá para seguir lendo (arquivo ilegível, coluna ausente).
- `engine/validation.py` (novo): `validate(inputs, config) -> ValidationReport` e os checks que olham as tabelas já normalizadas (cada um uma função pura `tabelas -> list[Check]`).
- `engine/errors.py`: `EngineError(message, check_id=None)`.
- `engine/data_preprocessor.py`: `load_and_prepare_data` chama `read_inputs`, levanta `EngineError` com o `check_id` do primeiro `error` (mensagem do check), depois continua como hoje (cadência, períodos parciais, outliers, adstock). Cada `raise ValueError` atual vira `EngineError` com id.
- `engine/pipeline.py`: `run()` chama `validate` antes do resto; se `ok` for falso, levanta `EngineError` (id e mensagem do primeiro erro) e **não** roda o modelo. Entrega o relatório a `build_results`.
- `engine/results.py`: preenche `ResultsV1.validation` com o relatório.
- `engine/__init__.py`: exporta `validate`, `ValidationReport`.
- `api/validation.py` não muda aqui (swap é do Dev B); a nota em `docs/decisoes/engine.md` lista o passo.

### Catálogo de checks

Ids e níveis abaixo; os dois primeiros blocos vêm do item, o resto são os erros atuais convertidos (ids são **propostas minhas**, estáveis daqui em diante).

| id | nível | quando |
| --- | --- | --- |
| `file_unreadable` | error | arquivo vazio ou ilegível (encoding/delimitador) |
| `column_missing` | error | coluna do `column_mapping` não existe e não há dica que a resolva |
| `date_unparseable` | error | nenhum formato cobre 100% das datas, ou formato ambíguo (dd/mm × mm/dd) |
| `value_not_numeric` | error | mais de 50% da coluna de investimento ou KPI não vira número |
| `no_valid_rows` | error | nada sobra após a limpeza em investimento ou performance |
| `duplicate_date_channel` | error | mais de uma linha para o mesmo (data, canal) no investimento |
| `kpi_duplicate_dates` | error | mais de uma linha por data no KPI |
| `kpi_not_single_source` | error | o arquivo de performance tem coluna de canal/plataforma (texto categórico, mais de um valor) ou o KPI repete por data com um identificador de origem |
| `cadence_mismatch` | error | cadências de investimento e KPI diferem em mais de 2 dias |
| `insufficient_after_partial` | error | nada sobra após descartar períodos parciais |
| `missing_dates` | warning | buracos na grade de datas (inclui as datas, até um teto de 50 e a contagem total) |
| `outliers` | info | pontos fora da regra IQR do `treat_outliers` (contagem e datas) |
| `partial_period_dropped` | info | períodos parciais que o `run` descarta (antes só ia para o log) |
| `dv360_cm360_overlap` | warning | duas séries de canal com correlação diária > 0.95 **e** razão de soma entre 0.9 e 1.1; por similaridade de série, nunca por nome |

`details` carrega os dados estruturados (datas, contagens, nomes de canal em `channels`) para a tela do B2; `message` é a frase pt-BR.

### Campos do relatório

`cadence` ("diária", "semanal", "mensal"), `period_days`, `date_range` e `channels` saem do que foi lido; se um erro impede o cálculo, ficam `null`/vazios e `ok=false`. `ok` é `true` se e somente se não houver check `error`.

### Efeito no `run`

Dados limpos: nenhuma mudança (a paridade com Gol e o snapshot sintético continuam idênticos). Dados sujos: investimento duplicado e KPI com data repetida deixam de virar média/soma e passam a ser erro. Avisos e infos não bloqueiam; ficam no `results.json`.

### Falhas e segurança

Mensagens não incluem caminhos nem valores do cliente além de exemplos curtos (hoje até 3 valores inválidos, mantido). `EngineError.check_id` é o único canal estruturado de erro para a API.

## Testes e aceite

- Um teste por check, com CSV mínimo (`tests/engine/test_validate_checks.py`), mais um caso "tudo limpo → `ok`, sem checks".
- `kpi_not_single_source`: o layout `Data;Canal;Leads` do exemplo Tcross reduzido falha com o id certo; o da Gol passa.
- `dv360_cm360_overlap`: duas séries quase idênticas disparam; duas correlacionadas mas com razão de soma fora de 0.9–1.1 não; renomear os canais não muda o resultado.
- `load_and_prepare_data` e `validate` concordam: para cada CSV de teste, `ok=false` ⇔ `load_and_prepare_data` levanta com o mesmo `check_id`.
- Regressão: paridade sintética e `mise run parity-real` seguem idênticos; fixtures de `results.json` regenerados com `validation` preenchido.
- Desempenho: `validate` < 10 s com 730 dias × 15 canais (teste com sintético).
- Dados reais das Core: rodar quando chegarem e registrar; até lá, a Gol e as pastas de `exemplo_csv/` servem de smoke (VW e Tcross/PMAX têm layouts diferentes e alguns devem falhar por desenho).

## O que fica para quem constrói

- Escolher os limiares exatos do `kpi_not_single_source` (heurística de coluna categórica) e testá-la contra os quatro layouts de `exemplo_csv/`.
- Teto de datas listadas em `details`.
- Se `read_inputs` precisa de cache entre `validate` e `run` no mesmo processo (hoje não; o `validate` roda na API e o `run` no worker).

## Em aberto fora do motor

- Nomes de canal DV360/CM360 e templates CSV oficiais: com Data Analytics. O design não depende deles.
- O swap da API (`api/validation.py` → `from engine import validate`) e a tela do B2 para os novos ids são do Dev B.
