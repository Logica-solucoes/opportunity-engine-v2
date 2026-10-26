# B3 · Parâmetros com sugestão do Gemini — design

Data: 26/out/2026. Item: B3 em `docs/m2/trilha-b-plataforma.md`. Contrato do `EngineConfig` em `docs/m2/README.md` › contrato §1.

## Objetivo e recorte

Depois de confirmar o mapeamento, o analista preenche os parâmetros da simulação. O formulário já abre com sugestões tiradas dos arquivos; um botão pede sugestões ao Gemini, cada uma com a explicação. O analista aceita ou edita e salva. Dividido como o B2: **B3a** (backend) e **B3b** (tela), cada um com seu plano.

| Fora | Volta quando |
|---|---|
| `channel_groups` no formulário | A3 (colinearidade e `suggested_groups`) |
| `controls` no formulário | A4 (controles causais) |
| `gate_thresholds` no formulário | quando o A0 fixar os gates; até lá vale o default |
| Chave do Gemini no Secret Manager | B11; até lá, variável de ambiente |
| Config que zera a validação | A2, se o `validate` real passar a depender de outro campo além do `column_mapping` |

## Desvios do `trilha-b-plataforma.md`

- **`EngineConfig` provisório em `api/`.** O A0 ainda não entregou o `engine/`. `api/engine_config.py` define o modelo com os campos do contrato §1. Quando o `engine/config.py` existir, o arquivo vira `from engine.config import EngineConfig` e o resto não muda. Mesmo caminho do `validate` falso do B2.
- **Rotas sob o workspace.** O trilha-b cita `POST /api/simulations/{id}/suggest`. A regra do projeto põe dado de cliente sob `/api/w/{slug}/…`, então as rotas ficam lá. O schema não é dado de cliente e fica em `/api/engine/config-schema`.
- **Sugestão dos dados escrita do zero.** O time não tem acesso ao `suggest_causal_config` do protótipo. O B3 cobre só o que sai dos arquivos com regra simples (tabela abaixo); o resto fica no default, sem selo.
- **O Gemini não vê linhas.** O prompt leva só o resumo agregado dos arquivos.

Os quatro entram em `docs/decisoes/parametros-e-gemini.md` e o trilha-b é corrigido no mesmo commit.

---

## B3a · Backend

### `EngineConfig` provisório (`api/engine_config.py`)

Pydantic v2. Nomes e defaults abaixo são provisórios: o A0 decide, e a troca é avisada às duas trilhas.

| Campo | Tipo | Default | Restrição |
|---|---|---|---|
| `optimization_target` | `Literal["REVENUE", "CONVERSIONS"]` | `"CONVERSIONS"` | |
| `kpi_is_monetary` | `bool` | `False` | |
| `average_ticket` | `float \| None` | `None` | `> 0` |
| `conversion_rate_from_kpi_to_bo` | `float` | `1.0` | `> 0`, `≤ 1` |
| `financial_targets` | `FinancialTargets` | todos `None` | cada um `> 0` |
| `financial_targets.target_cpa`, `target_icpa`, `target_roas`, `target_iroas` | `float \| None` | `None` | `> 0` |
| `investment_limit_factor` | `float` | `1.5` (BRD) | `> 1`, `≤ 5` |
| `max_budget_step` | `float` | `0.20` | `> 0`, `≤ 1` |
| `p_value_threshold` | `float` | `0.05` | `> 0`, `< 1` |
| `min_pre_period_days` | `int` | `28` | `≥ 7` |
| `r_squared_threshold` | `float` | `0.5` | `≥ 0`, `≤ 1` |
| `increase_threshold_percent` | `float` | `20` | `> 0` |
| `decrease_threshold_percent` | `float` | `20` | `> 0` |
| `require_significance` | `bool` | `True` | |
| `require_good_fit` | `bool` | `True` | |
| `column_mapping` | `dict` | `{}` | escrito só pelo `PUT …/mapping` (B2) |
| `channel_groups` | `list[list[str]]` | `[]` | fora do formulário |
| `controls` | `list[str]` | `[]` | fora do formulário |
| `gate_thresholds` | `dict` | `{}` | fora do formulário |

`ParamsIn` é o mesmo modelo sem `column_mapping`, `channel_groups`, `controls` e `gate_thresholds`: os campos do formulário. `extra="forbid"` nos dois.

### Rotas

| Método | Rota | Acesso | Resposta |
|---|---|---|---|
| GET | `/api/engine/config-schema` | `active_user` | `ParamsIn.model_json_schema()` |
| GET | `/api/w/{slug}/simulations/{id}/suggestions` | analyst+ | `{campo: {value, reason, source: "dados"}}`; 422 sem mapeamento salvo |
| POST | `/api/w/{slug}/simulations/{id}/suggestions/gemini` | analyst+ | `{available: bool, suggestions: {campo: {value, reason, source: "gemini"}}}`; 422 sem mapeamento salvo |
| PUT | `/api/w/{slug}/simulations/{id}/params` | analyst+ | `ParamsIn` → `SimulationOut`; 422 do pydantic com `loc` por campo; 422 sem mapeamento salvo |

O campo de sugestão é o caminho com ponto (`financial_targets.target_cpa`), o mesmo que o front usa no layout e que o `loc` do pydantic dá.

O `PUT …/params` trava a simulação com `simulations.lock` (como upload e mapping), grava `{**ParamsIn.model_dump(mode="json"), "column_mapping": <salvo>}` em `simulations.config` e não mexe no `validation`.

### Sugestões dos dados (`api/suggestions.py`)

Funções puras sobre os CSVs já enviados e o `column_mapping` salvo. Cada sugestão traz `reason` em pt-BR.

| Campo | Regra | Exemplo de `reason` |
|---|---|---|
| `min_pre_period_days` | um quarto do período do arquivo de performance, entre 28 e 90 dias (diário) ou entre 56 e 182 dias (semanal) | "Um quarto dos 420 dias de histórico." |
| `optimization_target`, `kpi_is_monetary` | nome normalizado da coluna de KPI: `receita`, `revenue`, `faturamento`, `gmv`, `valor` → `REVENUE` e `true`; `conversao`, `conversion`, `vendas`, `pedidos`, `leads` → `CONVERSIONS` e `false`; nenhum dos dois → sem sugestão | "A coluna de KPI se chama 'receita'." |

A cadência sai da mediana do intervalo entre datas distintas do arquivo de performance: 1 dia → diário, 7 dias → semanal; outro valor → sem sugestão de `min_pre_period_days`. As datas são lidas em ISO (`AAAA-MM-DD`); linha com data ilegível é ignorada.

### Gemini (`api/gemini.py`)

- SDK `google-genai`, chave em `GEMINI_API_KEY`. Modelo fixo numa constante (`GEMINI_MODEL`), sem escolha por usuário; conferir o nome atual do modelo no context7 ao implementar.
- O prompt leva: o JSON Schema do `ParamsIn`, os nomes das colunas mapeadas, a cadência, o período, a lista de canais, o investimento total e a participação de cada canal, e mínimo, média e máximo do KPI. Nenhuma linha dos arquivos.
- Saída estruturada (`response_schema`): lista de `{field, value, reason}`, com `field` restrito aos caminhos do `ParamsIn`.
- Cada sugestão é validada aplicando o valor sobre o config atual e montando `ParamsIn`; a que falhar é descartada e logada (`simulation.gemini_dropped field=… `), sem o valor.
- Sem chave, erro do SDK ou timeout de 20 s → `{available: false, suggestions: {}}` com status 200, e um log `simulation.gemini_unavailable reason=…`. O prompt e a resposta nunca vão para o log.
- Nos testes, o cliente do Gemini é trocado por um fake via `monkeypatch` na função `ask` do módulo. Nenhum teste chama a rede.

### Testes (pytest)

Seams: as quatro rotas acima, e `suggestions.from_data(files, mapping)` como função pura.

- Sugestão dos dados: cadência diária e semanal, KPI monetário, KPI de conversão, KPI sem nome conhecido, data ilegível.
- Gemini com sucesso (fake): sugestões chegam com `source: "gemini"`; valor fora da restrição é descartado; campo fora do `ParamsIn` é descartado.
- Gemini indisponível (sem chave e fake que levanta): 200 com `available: false`.
- `PUT …/params`: grava e preserva o `column_mapping`; valor inválido dá 422 com o `loc` do campo; campo extra dá 422.
- Sem mapeamento salvo: as três rotas de simulação dão 422.
- Matriz RBAC (`test_rbac.py`) ganha as quatro rotas; 404 entre workspaces; viewer recebe 403.

---

## B3b · Tela

### Onde

Seção "Parâmetros" na página da simulação, entre Validação e Rodar. Aparece quando o mapeamento já foi salvo (`sim.validation` existe). Erro na validação não esconde o formulário; quem barra o run é o B4.

### Layout (`web/src/lib/params.ts`)

`FORM_LAYOUT` lista os grupos e, em cada um, os caminhos dos campos com rótulo e ajuda em pt-BR. Campo do schema que não está no layout não aparece. Campo do layout que sumiu do schema é ignorado (o A0 pode renomear).

| Grupo | Campos |
|---|---|
| Objetivo | `optimization_target`, `kpi_is_monetary`, `average_ticket`, `conversion_rate_from_kpi_to_bo` |
| Metas financeiras | `financial_targets.target_cpa`, `.target_icpa`, `.target_roas`, `.target_iroas` |
| Orçamento | `investment_limit_factor`, `max_budget_step` |
| Causal | `p_value_threshold`, `min_pre_period_days`, `r_squared_threshold`, `increase_threshold_percent`, `decrease_threshold_percent`, `require_significance`, `require_good_fit` |

O controle sai do schema (`GET /api/engine/config-schema`, `staleTime: Infinity`): `number`/`integer` → `<input type="number">` com `min`/`max`/`step` do schema; `enum` → `NativeSelect`; `boolean` → `Checkbox`; tipo que aceita `null` → vazio vira `null`. Os rótulos dos valores de enum (`REVENUE` → "Receita") ficam no layout.

### Valor inicial e selos

Cada campo começa com, em ordem: o valor salvo em `sim.config`; a sugestão dos dados; o default do schema. Campo cujo valor veio de sugestão mostra um selo ("Sugerido pelos dados" ou "Sugerido pelo Gemini") e o `reason` em texto pequeno embaixo. Editar o campo tira o selo e a explicação.

Quando o salvo existe, a sugestão dos dados não sobrescreve: o salvo é decisão do analista.

### Botões

- **Sugerir com Gemini**: chama o POST; aplica as sugestões só nos campos que o analista não editou nesta tela, inclusive os que vieram salvos. Nada é gravado até "Salvar parâmetros". Com `available: false`, toast "Sugestão do Gemini indisponível. Os demais campos seguem valendo." e nada muda.
- **Salvar parâmetros**: `PUT …/params` com os valores do formulário; grava a resposta no cache como upload e mapping. 422 do pydantic vira erro inline no campo pelo `loc`, com mensagem pt-BR pelo `type` do erro (`greater_than` → "Deve ser maior que {gt}.", `less_than_equal` → "Deve ser no máximo {le}.", `int_parsing`/`float_parsing` → "Informe um número.", `literal_error` → "Escolha uma das opções."); `type` sem tradução cai em "Valor inválido."
- Os dois ficam desabilitados com a mesma trava `busy` da página (uma escrita por vez).
- **Rodar** continua sempre desabilitado. Sem parâmetros salvos, o motivo passa a ser "Salve os parâmetros antes de rodar." Parâmetros salvos = `sim.config` tem `optimization_target`.

### Testes (Playwright)

O E2E roda sem `GEMINI_API_KEY`; o caminho de sucesso do Gemini fica no pytest.

- Depois de validar, o formulário abre com o selo "Sugerido pelos dados" em `min_pre_period_days` e o `reason` visível.
- "Sugerir com Gemini" sem chave mostra o toast e não muda campos.
- Valor inválido (ex.: `investment_limit_factor` = 0) mostra o erro no campo depois de salvar.
- Valores salvos persistem depois de recarregar; o selo não volta em campo salvo.

---

## Docs no mesmo commit

- `API-GUIDE.md`: as quatro rotas.
- `docs/decisoes/parametros-e-gemini.md` (novo, e no índice `docs/decisoes/README.md`): os quatro desvios, o resumo enviado ao Gemini e por quê.
- `docs/m2/README.md` › contrato §1: os nomes provisórios de `require_*` e os defaults, marcados como provisórios até o A0.
- `.env.example`: `GEMINI_API_KEY`.
- Ao fechar: `Status` do B3 no trilha-b e "Estado atual" do `CLAUDE.md`.
