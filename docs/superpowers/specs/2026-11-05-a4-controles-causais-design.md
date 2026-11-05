# A4 · Controles causais livres de contaminação — design

Item `A4` de `docs/m2/trilha-a-motor.md`. Depende de A0 (pronto). Muda números do modelo causal de propósito; o que muda é registrado para a A10.

## Intenção

O contrafactual do modelo causal (`UnobservedComponents` com regressores) só vale se os regressores não forem **efeito do próprio investimento**. Hoje o modelo recebe `Leads`, `Clicks` e `Impressions` do arquivo de performance (`analysis.py:283-326`), que o anúncio move, e a `Generic Searches` do arquivo de tendências sem nenhuma triagem. Um regressor assim absorve o efeito que a análise quer medir e o lift sai subestimado ou sem sentido. O A4 deixa entrar só controles exógenos, rejeita explicitamente os que andam junto com o spend do canal tratado e mostra o que foi rejeitado, por evento.

## Objetivos

- Clicks, Impressions, Leads (do arquivo de performance) nunca entram no modelo causal.
- Controles do usuário (`config.controls`) são colunas do arquivo de tendências; cada um, e a `Generic Searches`, passa por uma triagem por evento contra o spend do canal tratado no pré-período.
- O LassoCV da seleção de variáveis usa folds temporais (`TimeSeriesSplit`).
- O resultado diz, por evento, quais controles foram usados e quais foram rejeitados (com a correlação).
- Controle declarado e ausente no arquivo é erro do `validate`, não surpresa no meio do run.

## Não-objetivos

- BCB (IPCA, Selic, IBC-Br): primeiro item da ordem de corte do item; fica fora. O motor não faz chamada de rede fora do LLM.
- Triagem dos controles no MMM (elasticidade) e no modelo de resposta pré-treinado (`run_opportunity_projection`): continuam como hoje (só `Generic Searches`, sem triagem). Candidato à A10.
- Placebo, WMAPE fora da amostra, suficiência (A6); thresholds finais (A10).
- Mudar o schema do `results.json` além de um campo opcional novo por evento.

## Anti-objetivo

Deixar entrar, ou tirar, um regressor em silêncio. Toda variável que o modelo causal usa ou rejeita fica registrada no resultado do evento.

## Decisões já tomadas (com o dono)

- Os controles do usuário vêm de **várias colunas do arquivo de tendências**; `config.controls` lista quais. `controls` vazio mantém só a `Generic Searches`, como hoje.
- A triagem é **por evento**, dentro da análise causal (abordagem A).

## Abordagens consideradas

- **A. Triagem por evento no causal (escolhida).** Cada controle é comparado com o spend do canal tratado no pré-período do evento. Segue o texto do item. O MMM fica como está.
- **B. Triagem global na preparação.** Um controle rejeitado sai de todo o run. Mais simples, mas rígido: descarta o controle para eventos de outros canais, e foge do texto do item.
- **C. As duas.** Fecha o MMM também, mas dobra a lógica e os testes.

## Desenho

### Arquivos

- `engine/config.py`: `GateThresholds` ganha `control_spend_corr: float = 0.5` (`gt=0, le=1`, estrito). `controls: list[str]` já existe e passa a valer (sem duplicatas e sem texto vazio).
- `engine/inputs.py`: `read_inputs` lê, além da coluna de tendência mapeada, cada coluna de `config.controls` do arquivo de tendências (mesma leitura numérica da `Generic Searches`), em `trends_df` como colunas extras com o nome do cabeçalho. Novos checks abaixo.
- `engine/analysis.py`: `run_causal_impact_analysis` deixa de ler as covariáveis do arquivo de performance (remove `found_covariates` e o bloco "New Dynamic Code"), aplica a triagem e troca o LassoCV por `TimeSeriesSplit`. A lista de regressores candidatos inclui os controles aceitos pelo nome (hoje a `Generic Searches` entra por conter "generic" no nome; isso deixa de ser a regra).
- `engine/controls.py` (novo): `screen_controls(pre_data, controls, treated_channels, threshold) -> tuple[list[str], list[dict]]`, função pura que devolve (aceitos, rejeitados com `{"name", "r"}`).
- `engine/results_schema.py`: `CausalEvent.controls: EventControls | None = None` com `used: list[str]` e `rejected: list[RejectedControl]` (`name`, `r`). Campo opcional novo, o `schema_version` continua 1.
- `engine/results.py` e `engine/pipeline.py`: repassam `controls_used`/`controls_rejected` de `results_data` para o `CausalEvent`.
- Não muda: `data_preprocessor.py`, `elasticity_analysis.py`, o modelo de resposta pré-treinado.

### Triagem (`screen_controls`)

- Candidatos: a `Generic Searches` (se houver arquivo de tendências) e as colunas de `config.controls`.
- Para cada candidato: correlação de Pearson, nas linhas do pré-período do evento, entre o controle e o spend cru do canal tratado (soma dos canais quando o evento tem mais de um, `product_group` separado por vírgula).
- Rejeitado se `abs(r) > gate_thresholds.control_spend_corr` (estrito; o sinal não importa). Correlação indefinida (controle ou spend constante) não rejeita; o filtro de variância que já existe tira a coluna constante.
- Os aceitos entram como regressores candidatos do modelo (seguem para o filtro de variância e a seleção do Lasso); os rejeitados não entram.
- Resultado por evento: `controls.used` (aceitos, em ordem alfabética) e `controls.rejected` (`name`, `r` com 4 casas, ordenado por \|r\| decrescente). Rejeitar um controle **não** reprova o evento: `reasons` continua sendo só "por que o evento não foi publicado". (Desvio de leitura do item, que fala em listar em `reasons`; decisão minha, porque `outcome.passed = not outcome.reasons` e um controle rejeitado não é falha do evento.)
- Se todos os controles forem rejeitados, o modelo roda com os canais transformados e o calendário.

### LassoCV temporal

`LassoCV(cv=TimeSeriesSplit(n_splits=k), ...)` com `k = min(5, linhas_do_pré_período − 1)`; com poucas linhas o `k` encolhe em vez de levantar. Os demais parâmetros ficam.

### Checks novos (em `validate`, via `read_inputs`, todos `error`)

| id | quando |
| --- | --- |
| `control_missing` | um nome de `controls` não existe no arquivo de tendências, ou não há arquivo de tendências |
| `control_name_clash` | um controle tem o nome de um canal de investimento ou de uma coluna reservada (`Date`, `kpi`, `Generic Searches`) |

Controle com mais de 50% de valores não numéricos usa o `value_not_numeric` existente. Nome repetido em `controls` é ignorado (uma vez só); o nome da coluna de tendência já mapeada também. O resultado da triagem por evento não aparece no `validate` (ela precisa dos eventos, que só existem no run).

### Paridade

O A4 muda números do modelo causal de propósito (folds temporais, `Generic Searches` triada, covariáveis removidas). Contrato de teste:
- Blocos que o A4 não toca (`period_days`, `mmm`, `response_curve`, `points`, `optimized_mix`) seguem **idênticos ao protótipo** (`rtol=1e-9`), no sintético e na Gol.
- No bloco `events`, os campos de identidade e de gate de entrada (`event_id`, `product_group`, `intervention_date`) seguem comparados com o protótipo. Os números do resultado causal passam a ser comparados com um **golden gerado pelo motor** no commit do A4 (`tests/fixtures/parity/snapshot_a4_events.json`; Gol: `real/gol_a4_events.json`, git-ignorado, gerado por uma tarefa do mise). O README da paridade e `docs/decisoes/engine.md` registram o que mudou, evento a evento, para a A10.
- Onde um evento não mudar, o golden coincide com o protótipo, e isso fica registrado.

## Testes e aceite

- Arquivo de performance com colunas `Clicks`, `Impressions` e `Leads` produz o **mesmo** resultado causal que o mesmo arquivo sem elas.
- Controle sintético igual a spend + ruído é rejeitado e aparece em `controls.rejected` com \|r\| acima de 0.5; um controle independente é aceito e aparece em `controls.used`.
- `Generic Searches` correlacionada com o spend do canal tratado é rejeitada; a mesma série não é rejeitada num evento de outro canal (triagem é por evento).
- Evento com mais de um canal tratado usa a soma dos spends.
- `controls.rejected` não reprova o evento (`reasons` vazio, `passed` verdadeiro).
- Todos os controles rejeitados: o modelo roda e o evento sai com `used=[]`.
- `TimeSeriesSplit`: com pré-período curto (o mínimo permitido) o Lasso não levanta; um teste confirma que os folds são temporais (a divisão usada é `TimeSeriesSplit`).
- `control_missing`, `control_name_clash`, controle não numérico (`value_not_numeric`), controle ausente sem arquivo de tendências.
- Decimal US na coluna de performance deixa de quebrar o modelo (a covariável nem é lida).
- `validate` e `run` concordam nos checks novos; `validate` segue < 10 s em 730 × 15.
- Fixtures de `results.json` regenerados (campo `controls` por evento).

## O que fica para quem constrói

- O arredondamento exato e a ordem de empate dos controles rejeitados.
- Se `performance_df` pode sair de `PreparedData` e do `RawInputs` (hoje guardado "para covariáveis"); remover só se nada mais o usa.
- Mensagens pt-BR dos checks.
- A tarefa do mise que gera o golden da Gol.

## Em aberto fora do motor

- Dev B: `api/engine_config.py` precisa de `control_spend_corr` em `gate_thresholds`; a tela do B2/B3 que lista as colunas do arquivo de tendências como controles possíveis; a tela de resultado mostra `controls.used`/`rejected` por evento (B5).
- Data Analytics: o arquivo de tendências oficial com colunas de controle (macro) e a lista de variáveis que o cliente considera exógenas.
- Limiar 0.5: chute do item; calibrar na A10.
