# A6 · Suficiência de dados e placebo — design

Item `A6` de `docs/m2/trilha-a-motor.md`. Depende de A0 (pronto). Alimenta o A7 (experiment designer entra quando o run é `inconclusive`) e a tela de resultado do B5.

## Intenção

Hoje o motor publica lift de um evento sempre que o p-valor, a direção e o R² passam, mesmo quando o contrafactual é ruim fora da amostra ou quando o "efeito" aparece igual numa data em que nada aconteceu. É o caso do "16% de efeito no ruído" do BRD. O A6 adiciona dois gates: um **placebo por evento** (uma intervenção falsa no pré-período, com o mesmo modelo) e uma **suficiência do run** (os dados sustentam publicar lift?). Falhou, o run sai `inconclusive`, sem lift publicado, e o A7 desenha o experimento.

## Objetivos

- Placebo por evento: p < `p_value_threshold` → evento `rejected` com `placebo_failed`.
- WMAPE fora da amostra do contrafactual por evento (segura o último 20% do pré), registrado em `fit.wmape`.
- `results.sufficiency` preenchida: variação de spend dos canais analisados, nº de eventos validados, WMAPE fora da amostra do run, `passed` e `reasons`.
- Falha de suficiência → `status: "inconclusive"` no run, sem evento publicado.
- CV da elasticidade com poucas linhas deixa de cair calado para in-sample: o fato é registrado e reprova a suficiência.

## Não-objetivos

- Experiment designer (A7): `experiment_design` continua `null`.
- Calibrar limiares com as Core (A10).
- Vários placebos por evento, placebo por canal no MMM, ou mudar o modelo causal. O ajuste do evento real fica idêntico.
- Mudar a matemática da elasticidade: só se registra se o CV foi in-sample.

## Anti-objetivo

Afrouxar limiar ou gate até a Gol "passar". Se a Gol sair `inconclusive`, é o gate funcionando; o que importa é o aceite sintético (ruído puro reprova, efeito real passa) e a medição registrada.

## Decisões já tomadas (com o dono)

- **WMAPE fora da amostra só no nível do run.** Por evento ele é métrica (`fit.wmape`), sem gate próprio. O gate do run usa a mediana dos eventos que passaram nos demais gates.
- **Placebo A:** um placebo no ponto médio do pré, um ajuste extra por evento.
- Limiares propostos (calibração no A10): variação de spend (CV) ≥ 0.10; WMAPE fora da amostra ≤ 0.30.

## Abordagens consideradas

- **A. Um placebo no ponto médio (escolhida).** Barato (um ajuste extra); ~5% dos eventos bons caem por acaso.
- **B. Vários placebos (~5 pontos).** Mais robusto, custa 5 ajustes por evento e o pré curto não comporta janelas sem sobreposição. Descartada.

## Desenho

### Placebo (`engine/analysis.py`, dentro de `run_causal_impact_analysis`)

- Com `n` linhas de pré: ajusta o mesmo `UnobservedComponents` (mesmas `selected_features`, mesma sazonalidade) nas primeiras `n // 2` linhas. Prevê as `len(post_data)` linhas seguintes, com os exógenos reais. O p-valor sai do mesmo cálculo do evento real (impacto acumulado sobre o erro-padrão acumulado da previsão), extraído para uma função comum para não duplicar a regra.
- **Não roda** quando `n // 2 < min_pre_periods` ou quando `n - n // 2 < len(post_data)`: `placebo = {p_value: null, passed: null}`, um aviso no log e o evento **não** é rejeitado por isso. Não entra em `reasons` (que são só rejeições), igual ao `controls`.
- `_gate_reasons` ganha `placebo_failed` quando o placebo rodou e `p_value < p_value_threshold`. Sem flag `require_*`: o item torna o placebo obrigatório (minha decisão).
- Limite conhecido: as features vêm do Lasso no pré inteiro, então o placebo tem um vazamento leve de seleção. Documentado.

### WMAPE fora da amostra

- Ajusta nas primeiras 80% das linhas do pré, prevê os 20% finais com os exógenos reais, `wmape = Σ|y − ŷ| / Σ|y|`. Só calcula se o treino tem ≥ `min_pre_periods` linhas e o holdout ≥ 7; senão `null`. Vai em `fit.wmape` (campo já existente) e em `results_data["oos_wmape"]`. O `mape` in-sample continua como está.

### Suficiência (`engine/sufficiency.py`, novo)

`assess(outcomes, effective_spend, cv_out_of_sample, thresholds) -> Sufficiency`, função pura sobre o que o pipeline já tem.

- `validated_events` = eventos que passaram em **todos** os gates (inclui o placebo), antes do corte `max_events_to_analyze`. Falha com `no_validated_event` se for 0.
- `spend_variation` = `{canal: CV}` (desvio-padrão sobre a média do spend cru por período nativo, em todo o intervalo) para os canais dos eventos validados. Falha com `low_spend_variation` se algum ficar abaixo de `spend_cv_min`.
- `pre_wmape` = mediana de `oos_wmape` dos eventos validados que o têm. Falha com `high_oos_wmape` se maior que `oos_wmape_max`. Sem nenhum valor calculável: `null` e esse check não reprova (fica no log).
- `cv_out_of_sample`: o MMM guarda se o CV foi walk-forward (`min(3, n // 20) ≥ 2`) ou in-sample; in-sample reprova com `cv_in_sample`.
- `passed` = nenhuma razão. `reasons` lista todas, em ids estáveis.

### Efeito no resultado

- Falha por `no_validated_event`, `low_spend_variation` ou `high_oos_wmape`: `causal.status = "inconclusive"`, `causal.reasons` ganha o motivo, e os eventos que seriam `published` viram `rejected` com `insufficient_run` (sem lift). `run_status` já devolve `inconclusive` com a análise causal inconclusiva.
- `cv_in_sample`: o run vira `inconclusive` (nova regra em `run_status`: `sufficiency.passed == false` nunca dá `succeeded`), `elasticity.reasons` ganha `cv_in_sample` (informativo) e a curva segue publicada.
- Sem elasticidade (MMM falhou): a suficiência só avalia as partes causais.

### Config

`GateThresholds`: `spend_cv_min` 0.10 (`gt=0`, estrito) e `oos_wmape_max` 0.30 (`gt=0`, estrito). A fração do holdout (0.2) é constante do código. Defaults só em `config.py`.

### Contrato (`docs/m2/README.md`)

`sufficiency` ganha `reasons` e `cv_out_of_sample`; `placebo.passed = null` significa "não rodou"; `fit.wmape` passa a ser fora da amostra (o `mape` segue in-sample); novos ids: `placebo_failed`, `insufficient_run`, `no_validated_event`, `low_spend_variation`, `high_oos_wmape`, `cv_in_sample`. `schema_version` continua 1 (campos opcionais).

### Falhas e segurança

Nada novo: tudo calculado sobre agregados já em memória. Falha no ajuste do placebo ou do holdout (exceção do statsmodels) vira `null` + aviso, nunca derruba o evento.

## Testes e aceite

- **Ruído puro:** KPI = ruído, mesmos spends → nenhum evento publicado e run `inconclusive` (o caso do BRD).
- **Placebo:** efeito injetado no pré-período reprova (`placebo_failed`); efeito real no pós, com pré limpo, passa.
- Placebo não roda com pré curto: evento não rejeitado, `passed = null`.
- `assess`: cada razão isolada, mediana do WMAPE, limiares configuráveis, sem WMAPE calculável.
- CV com < 40 linhas: `cv_out_of_sample = false` e `cv_in_sample` na suficiência; o vetor de coeficientes e o `cv_r2` seguem idênticos (paridade da elasticidade intacta).
- O ajuste do evento real (lift, p, R², features) idêntico ao golden do A4; muda só quem passa nos gates. Golden regenerado e a mudança registrada.
- Gol: registrar quantos eventos passam (hoje 12), quantos reprovam no placebo, o WMAPE mediano e o `status` do run. Fixtures de `results.json` regenerados.

## O que fica para quem constrói

- O ponto exato de montar a `Sufficiency` (`pipeline.compute`) e o que `_event` já esconde em evento `rejected` (o lift tem que sumir também de `insufficient_run`).
- Textos de log em pt-BR e o custo de tempo medido nos 52 eventos da Gol.
- Se o corte `max_events_to_analyze` interage com o placebo (o placebo roda em todos os candidatos elegíveis, não só nos selecionados).

## Em aberto fora do motor

- Dev B: `spend_cv_min` e `oos_wmape_max` em `api/engine_config.py`; a tela do B5 mostra `sufficiency.reasons` e `placebo`.
- A7: consome `sufficiency` e `status == "inconclusive"`.
- A10: calibrar 0.10 e 0.30 com as Core.
