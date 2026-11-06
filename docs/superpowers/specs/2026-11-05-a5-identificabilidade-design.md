# A5 · Identificabilidade por canal — design

Item `A5` de `docs/m2/trilha-a-motor.md`. Depende de A3 (pronto); bloqueia A8 (bandas e `engine.scenario`) e A9 (grounding).

## Intenção

O MMM reparte o efeito de mídia entre os canais, mas nem toda divisão tem sustentação: um canal pode receber crédito num ajuste e zero no seguinte. Hoje o bootstrap (n=200, seed 42) calcula os coeficientes de cada reamostragem e só a média sobrevive, sem nenhum intervalo. O A5 expõe o intervalo por canal, marca como não identificável o canal cujo efeito não se separa de zero (ou é largo demais) e tira esse canal de tudo que é publicado por canal: curva, mix, cenários e payload do Gemini.

## Objetivos

- `channels[].coef_ci` com p2.5/p97.5 da contribuição do canal, em unidade do KPI.
- `channels[].identifiable` e `channels[].reasons` em todo canal do modelo.
- Canal não identificável: sem `contribution_pct`, `hill`, `adstock` e `curve` no `results.json`; o spend dele no mix entra somado numa chave `"Não identificados"`.
- Nenhum canal identificável: `elasticity.status = "inconclusive"` com `no_identifiable_channel`; o mix fica só com `"Não identificados"`.
- A matriz do bootstrap fica guardada para o A8.

## Não-objetivos

- O modelo e a otimização não mudam. O canal não identificável continua no ajuste e no otimizador; só a **publicação** muda. A média do bootstrap é a mesma de hoje, então a paridade fica idêntica.
- Bandas `lo`/`hi` nas curvas e cenários são do A8.
- Reescrever o payload do Gemini é do A9. O A5 só garante que o canal não chega nele.
- Arquivos legados de curva individual (PNG/CSV em `global_saturation_analysis/`) não mudam: a API não os expõe.
- `block_per_channel` do A3 continua só liberando o gate. Não força `identifiable=false` (ver Em aberto).

## Decisões

| Pergunta | Decisão | Por quê |
|---|---|---|
| O que "sai de curva, mix e cenários" significa | Só publicação: modelo e otimizador iguais, o canal some do JSON e do Gemini, o spend dele vai para `"Não identificados"` | Mantém a paridade e os totais da curva agregada; congelar ou tirar do modelo muda números que a A10 ainda vai auditar. Decidido com o dono em 05/nov/2026. |
| Unidade do `coef_ci` | Contribuição total no período, em unidade do KPI: `coef_b × Σ X_scaled[:, i]` por reamostragem | O coeficiente da Ridge vive no espaço MinMax e não significa nada fora do modelo; a contribuição o analista lê. Decidido com o dono. |
| "IC cruza zero" | `p2.5 <= 0` | A Ridge tem `positive=True`: coeficiente nunca é negativo. Cruzar zero é ≥ 2,5% das reamostragens zerarem o canal. |
| "Largura maior que o ponto" | `p97.5 − p2.5 > ponto`, com ponto = contribuição com o coeficiente médio (a de hoje) | O ponto é o que já é publicado. |
| Limites configuráveis | Não. Regra fixa | É a regra da trilha; nenhum valor a calibrar. A A10 revê se precisar. |
| Nenhum canal identificável | `elasticity.status = "inconclusive"`, `reasons = ["no_identifiable_channel"]`; curva agregada e cenários publicados, sem mix por canal | O total investimento × KPI continua medido; só a divisão não. Decidido com o dono. |
| `run_status` com elasticidade inconclusiva | Conta como "publicou algo": causal `inconclusive` + elasticidade `inconclusive` → run `inconclusive`, não `failed` | A curva total sai publicada; `failed` diria que nada saiu. `failed` continua sendo causal sem evento + elasticidade `failed`. |
| Regra estrita demais para os dados atuais? | Fica a regra da trilha | Medido em 05/nov/2026: no sintético da paridade (spend com ~3% de ruído fora de dois picos), nos 728 dias, no semanal e no colinear agrupado, **todo canal sai não identificável** (`p2.5 = 0`, 35–96% das reamostragens zeram o canal). Com spend que varia de verdade (σ = 0,5) o canal forte passa e o sem efeito reprova. A Gol provavelmente fica toda não identificável. Decidido com o dono: a regra é honesta; a A10 calibra com a Data Science. |
| Grupo do A3 | Avaliado como um canal | O grupo já é uma coluna só no modelo (somado na leitura). |
| Chave do bucket | `"Não identificados"` (constante em `engine/identifiability.py`) | Rótulo direto na tela pt-BR; colisão com nome real de canal é desprezível. |

## Abordagens consideradas

- **Módulo puro `engine/identifiability.py` (escolhida).** O cálculo e o `fold_mix` são funções sem I/O, testáveis com matrizes feitas à mão, e o `results.py` e o `outputs.py` usam o mesmo `fold_mix`.
- **Tudo dentro de `run_mmm_engine` e `results.py`.** Menos arquivos, mas testar exige rodar o MMM inteiro e a regra de dobrar o mix ficaria duplicada entre JSON e Gemini.

## Desenho

**Bootstrap.** `bootstrap_average_coefficients` vira `bootstrap_coefficients(X, y, n_bootstrap=200, seed=42) -> np.ndarray` e devolve a matriz `(n_bootstrap, n_canais)`. Em `run_mmm_engine`, `mkt_model.coef_ = samples.mean(axis=0)` (o número de hoje) e o dict do MMM ganha `coef_samples` (a matriz) e `channel_totals` (`X_mkt_scaled.sum(axis=0)`, para converter em contribuição sem guardar o `X`).

**`engine/identifiability.py`.**

```python
UNIDENTIFIED = "Não identificados"

def assess(mmm: dict) -> dict[str, dict]:
    # {canal: {"ci": (lo, hi), "identifiable": bool, "reasons": [...]}}
    # contribuições = coef_samples * channel_totals; ponto = coef_ médio * channel_totals

def fold_mix(mix: dict[str, float | None], unidentified: set[str]) -> dict[str, float | None]:
    # tira os canais não identificáveis e soma o spend deles em UNIDENTIFIED; sem nenhum, devolve igual
```

Motivos: `coef_ci_includes_zero` e `coef_ci_too_wide` (os dois podem vir juntos).

**Pipeline.** `compute` chama `identifiability.assess(mmm)` uma vez, quando há MMM, e guarda em `Computed.identifiability`. Sem MMM, fica `{}`.

**`results.py`.**
- `_channel_fits`: todo canal recebe `identifiable`, `coef_ci` e `reasons`. Não identificável: `contribution_pct`, `hill`, `adstock` = `None`, `curve = []`. `observed_spend_range` continua (é dado, não modelo).
- `_response_rows`: cada variante do `mix` passa por `fold_mix`.
- `_elasticity`: se nenhum canal é identificável, `status="inconclusive"` e `reasons=["no_identifiable_channel"]`. O `fold_mix` já deixa cada variante do mix só com `"Não identificados"`; nenhum caso especial.
- `ChannelFit` ganha `reasons: list[str] = []`. Campo opcional: `schema_version` não muda e os fixtures atuais continuam válidos.

**`outputs._scenario`.** Cada `splits[label]` passa por `fold_mix`. Daí saem o `SATURATION_CURVE.md`, o HTML global e o payload do Gemini, então o canal não chega ao prompt. Nenhum canal identificável: `splits` fica só com `UNIDENTIFIED`, igual ao JSON.

## Testes e aceite

`tests/engine/test_identifiability.py`:

- `assess` com matriz feita à mão: canal com todas as reamostragens > 0 e estreitas → `true`; canal com 10% de zeros → `false` com `coef_ci_includes_zero`; canal largo → `coef_ci_too_wide`.
- `fold_mix` preserva o total e não tem chave do canal removido; sem canal removido devolve o mesmo dict.
- **Sintético (aceite da trilha):** dataset novo `make_identifiable_dataset` (dois canais com spend lognormal σ = 0,5: `STRONG` move o KPI, `NOEFFECT` não); `STRONG` sai `identifiable=true` e `NOEFFECT` `false`. O sintético atual vira o caso "nenhum identificável", e os testes que esperavam elasticidade `ok` nele passam a esperar `inconclusive`.
- **JSON (aceite da trilha):** o `results.json` de um run com canal não identificável não tem curva, Hill, adstock nem chave de mix desse canal, e tem `"Não identificados"`.
- Nenhum canal identificável → `elasticity.status == "inconclusive"` e run `inconclusive` quando o causal é `ok`.
- `test_parity.py` (Linux, `mise run parity`) intacto: a média do bootstrap não muda. No Windows, `tests/engine` verde.

## Fixtures

Os fixtures de `tests/fixtures/results/` saem de `exemplo_csv/Gol`, que não está nesta máquina. Como os campos novos são opcionais, os fixtures atuais seguem válidos com `identifiable`/`coef_ci` `null`; regenerar com `generate_fixtures.py` quando a Gol estiver disponível, para o B5 ver o campo preenchido.

## Docs no mesmo commit

- `Status` do A5 em `docs/m2/trilha-a-motor.md` e o "Estado atual" do `CLAUDE.md`.
- `docs/decisoes/engine.md`: a regra de identificabilidade, o "só publicação" e o bucket `"Não identificados"`.
- `docs/m2/README.md` §3: `channels[].reasons` e a chave `"Não identificados"` no mix.

## Em aberto

- `block_per_channel` (A3) deveria forçar `identifiable=false` nos canais dos pares sinalizados? Hoje não força; o bootstrap decide. Levar à A10.
- O IC é condicional aos hiperparâmetros (adstock, Hill) do ajuste final: o bootstrap só reamostra a Ridge. É mais estreito que o verdadeiro. Registrar para a A10.
