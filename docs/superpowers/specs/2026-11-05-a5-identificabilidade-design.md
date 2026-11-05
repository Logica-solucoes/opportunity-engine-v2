# A5 · Identificabilidade por canal — design

Item `A5` de `docs/m2/trilha-a-motor.md`. Depende de A3 (pronto). Alimenta a A8 (bandas dos cenários usam a matriz de bootstrap) e a tela de resultado do B5.

## Intenção

O modelo de elasticidade devolve um coeficiente por canal, e o `results.json` publica curva, contribuição e mix de cada um. Quando os dados não separam o efeito de um canal do ruído (ou de outro canal), esse número é arbitrário, mas hoje sai com a mesma cara de um resultado firme. O A5 mede, por canal, se o coeficiente é separável de zero e estável (intervalo de bootstrap), marca `identifiable` e **não publica** o que não se sustenta: o canal sai de curva individual, mix, cenários e payload do Gemini, e só o grupo (ou o total) é publicado, com o motivo.

## Objetivos

- `coef_ci` (percentis 2.5 e 97.5 do bootstrap) e `identifiable` por canal, com o motivo quando falso.
- Canal não identificável não aparece, no `results.json`, com `hill`, `adstock`, `curve` nem `contribution_pct`, nem como chave no `mix` das linhas da curva agregada; no lugar entra um balde único `nao_identificavel`.
- O payload que vai ao Gemini e os cenários dele deixam de citar o canal.
- A matriz de bootstrap fica guardada em memória para a A8.
- A matemática do MMM não muda: `mmm`, curva, pontos e mix seguem idênticos ao protótipo (paridade intacta).

## Não-objetivos

- Recalcular o modelo com os canais não identificáveis agrupados, ou travá-los na participação atual no mix otimizado: mexe na matemática, fica para a A8 (abordagem B descartada).
- Intervalos de confiança das curvas e dos cenários (A8) e suficiência/placebo (A6).
- Esconder os arquivos legados gravados em `out_dir` (PNG/CSV/MD/HTML por canal): são artefatos de diagnóstico do protótipo, fora do contrato; a plataforma lê só o `results.json`.
- Calibrar o limiar com as Core (A10).

## Anti-objetivo

Publicar, com cara de resultado, um número por canal que os dados não sustentam; ou "consertar" o bootstrap até os canais passarem. O gate pode deixar quase tudo de fora nos dados atuais, e isso é o gate funcionando.

## Decisões já tomadas (com o dono)

- Regra **literal do item**: `identifiable` é falso quando o IC cruza zero **ou** a largura é maior que o |ponto|; o limiar da largura é configurável (`gate_thresholds`), com default 1.0.
- O filtro age na **camada de publicação** (abordagem A), sem refazer a matemática.

## O que a medição mostrou (05/nov/2026)

Com o mesmo bootstrap do modelo (Ridge positivo, 200 reamostras, seed 42): **Gol 0 de 12** canais identificáveis (10 com coeficiente 0 em quase todas as reamostras; o META tem IC [8.352, 72.913] mas largura 64.560 > ponto 40.134) e **sintético 0 de 5** (todos com limite inferior 0). Um bootstrap sem a restrição de positividade foi testado e descartado: identifica efeitos de mídia negativos e de sinal errado. Com os dados atuais o run publica só o total; é o comportamento esperado até a calibração.

## Abordagens consideradas

- **A. Filtro na publicação (escolhida).** Flags e IC no estágio do MMM; `results.py` e o payload do LLM escondem o que não passa. Matemática intacta.
- **B. Refazer o modelo com um balde agrupado.** Fecha o limite abaixo, mas muda a matemática, quebra a paridade e exige uma segunda rodada do modelo. Descartada; a A8 revisita.

**Limite conhecido da A:** a participação do balde `nao_identificavel` no mix otimizado ainda vem dos coeficientes não identificados. Fica documentado como entrada da A8.

## Desenho

### Arquivos

- `engine/config.py`: `GateThresholds.identifiability_width_ratio: float = 1.0` (`gt=0`, estrito).
- `engine/elasticity_analysis.py`: `bootstrap_coefficients(X, y, n_bootstrap=200, seed=42) -> ndarray` (a matriz); `bootstrap_average_coefficients` passa a chamar essa função e devolver `.mean(axis=0)` (resultado numericamente idêntico). `run_mmm_engine` guarda no dicionário `mmm`: `bootstrap_coefs` (matriz, só em memória), `coef_ci` (`{canal: (lo, hi)}`) e `identifiable` (`{canal: {"ok": bool, "reasons": [...]}}`).
- `engine/identifiability.py` (novo): `assess(coefs, columns, width_ratio, collinear_channels) -> dict`, função pura.
- `engine/results_schema.py`: `ChannelFit.reasons: list[str]`; `Elasticity.unidentified: Unidentified | None` com `channels: list[str]` e `contribution_pct: float | None`.
- `engine/results.py`: `_channel_fits`, `_response_rows` e `_elasticity` aplicam o filtro.
- `engine/outputs.py`: o payload do LLM (`_scenario`, a razão de contribuição) usa só os canais identificáveis mais o balde.
- `engine/pipeline.py`: `compute` passa ao MMM a lista de canais colineares marcada pelo `validate` (via `Computed.validation`).

### Regra (`identifiability.assess`)

Coeficientes no espaço do modelo (spend transformado e escalado). Para cada canal ativo: `lo, hi` = percentis 2.5 e 97.5 das reamostras; `ponto` = a média das reamostras (o mesmo coeficiente que o modelo usa). `identifiable` é verdadeiro sse `lo > 0` **e** `(hi − lo) ≤ width_ratio × |ponto|`. Motivos, na ordem de teste: `ci_crosses_zero` (`lo ≤ 0`, o que inclui o canal que vai a zero em mais de 2.5% das reamostras), `ci_too_wide`. Ponto igual a zero nunca é identificável. Um canal em `collinear_channels` ganha também `collinearity`, e fica `identifiable=false` mesmo que passe no IC (é a marca prometida ao `block_per_channel` do A3). Um grupo do A3 é um canal só. Canais inativos (fora de `spend_cols`) não são avaliados e continuam fora do resultado, como hoje.

`collinear_channels` = canais citados em `validation.collinearity.pairs` ou com VIF acima de `vif_max`, quando houver relatório de validação; sem relatório (chamadas diretas a `compute`), vazio.

### Publicação (`results.json`)

- `elasticity.channels[]`: todo canal ativo aparece com `identifiable`, `coef_ci` (no espaço do modelo; a A8 usa a matriz) e `reasons`. Se `identifiable` é falso: `hill`, `adstock`, `curve` e `contribution_pct` saem nulos/vazios. `observed_spend_range` fica (é dado, não saída do modelo).
- `elasticity.response_curve[].mix`: para cada variante, os canais identificáveis ficam com a chave própria; os demais somam numa única chave `nao_identificavel`. A soma da linha não muda.
- `elasticity.unidentified`: `channels` (nomes) e `contribution_pct` (soma). Nulo quando todos são identificáveis.
- `elasticity.scenarios[]` já não tem mix por canal (não muda); a A8 define as bandas.
- `status`: continua `ok`; se nenhum canal é identificável, `reasons` ganha `no_identifiable_channel` (informativo, o total segue publicado).
- `schema_version` continua 1 (campos novos opcionais).

### Payload do LLM

O dicionário de cenários e a razão de contribuição que vão ao Gemini usam os mesmos nomes publicados: canais identificáveis individualmente mais o balde `nao_identificavel`, nunca o canal oculto. Os prompts não mudam.

### Falhas e segurança

Nada novo: o IC vem de dados já agregados; `coef_ci` não revela linhas do cliente.

## Testes e aceite

- `assess`: IC que cruza zero → falso com `ci_crosses_zero`; IC positivo largo → `ci_too_wide`; positivo e estreito → verdadeiro; `lo == 0` exato → falso; ponto zero → falso; canal colinear → falso com `collinearity`; `width_ratio` muda o resultado; invariante a ordem/nome dos canais.
- `bootstrap_average_coefficients` devolve exatamente o mesmo vetor de antes (comparação `==` com a implementação anterior).
- **Aceite do item:** sintético dedicado com um canal de efeito real forte e um sem efeito: o primeiro sai `identifiable=true`, o segundo `false`.
- O JSON de um run com canal não identificável **não contém**, para ele, `hill`, `adstock`, `curve` nem `contribution_pct`, nem o nome dele como chave de `mix`; o balde `nao_identificavel` aparece e a soma de cada linha do mix não muda.
- Nenhum canal identificável: `unidentified` lista todos, `reasons` tem `no_identifiable_channel`, o total e a curva agregada seguem publicados.
- O prompt/payload recebido por um LLM falso não contém o nome do canal oculto (`tests/fakes/llm`).
- `block_per_channel` + par colinear (A3): os canais sinalizados saem `identifiable=false` com `collinearity`.
- Paridade: `mmm`, curva, pontos e mix idênticos ao protótipo (sintético e Gol); `test_defaults`/hygiene continuam verdes.
- Gol e sintético: registrar quantos canais passam (hoje 0 de 12 e 0 de 5) e o que o run publica.
- Fixtures de `results.json` regenerados.

## O que fica para quem constrói

- Construir o sintético de efeito forte (tamanho da série, ganho do canal) até o aceite ser estável; sem afrouxar a regra.
- Onde exatamente o payload do Gemini monta os nomes de canal (`outputs.py`/`reports.py`) e se há mais de um ponto.
- Textos de motivo no log em pt-BR.
- Se `coef_ci` fica em `ChannelFit` como tupla de duas floats (contrato já existente).

## Em aberto fora do motor

- Dev B: a tela do B5 mostra `identifiable`, `reasons` e o balde `nao_identificavel`; `identifiability_width_ratio` em `api/engine_config.py`.
- A8: travar o balde na participação atual (ou re-estimá-lo) e usar a matriz de bootstrap para as bandas.
- A10: calibrar o limiar de largura (1.0) e rever se o bootstrap com Ridge positivo é a medida certa; com os dados de hoje quase nada passa.
