# A3 · Gate de colinearidade — design

Item `A3` de `docs/m2/trilha-a-motor.md`. Depende de A2 (pronto); bloqueia A5 (identificabilidade por canal) e a tela de agrupamento do B2.

## Intenção

Quando dois canais gastam juntos (PMAX e SEARCH sobem e descem no mesmo dia), o modelo não consegue separar o efeito de um do efeito do outro: os coeficientes por canal viram ruído e a recomendação de orçamento por canal fica sem base. Hoje o motor não mede isso. O A3 mede a colinearidade do spend no `validate`, preenche o campo `collinearity` do relatório (vazio desde o A2) e **bloqueia o run** até o analista escolher o que fazer: somar os canais num grupo ou aceitar que o resultado por canal não seja identificável.

## Objetivos

- `validate` calcula |r| de Pearson par a par e o VIF do spend por canal, e devolve `pairs`, `vif` e `suggested_groups` no formato do contrato (`docs/m2/README.md` §2).
- Check `collinearity_unresolved` (erro) enquanto houver par sinalizado sem resolução.
- `channel_groups` funciona de ponta a ponta: o spend dos membros é somado antes de qualquer análise, e causal, elasticidade e cenários veem só o grupo.
- `block_per_channel` existe no config e resolve o gate.

## Não-objetivos

- O efeito de `block_per_channel` no resultado (`identifiable=false` por canal) é do A5. No A3 a flag só libera o gate; o resultado sai como hoje.
- A tela para escolher grupos é do B2. A API não muda.
- Não muda a matemática do modelo nem o adstock oculto para correlação negativa (A10).

## Consequência aceita

A API usa o motor real desde 05/nov/2026, e o `ParamsIn` (formulário) não tem `channel_groups` nem `block_per_channel`. **Até a tela do B2 existir, um dataset com spend colinear não roda pela plataforma**: o upload mostra o erro com os grupos sugeridos e o Rodar fica bloqueado. Pelo motor direto (`python -m engine --config run.json`) a escolha já funciona. Decidido com o dono em 05/nov/2026: erro, como o BRD pede, e não warning provisório.

## Decisões

| Pergunta | Decisão | Por quê |
|---|---|---|
| VIF sobre spend cru ou após adstock? | Spend cru | O BRD fala em "channel spend"; o adstock depende de parâmetro ajustado depois, e o gate roda antes do modelo. |
| Nível do check | `error` | BRD: run com colinearidade não resolvida não roda. |
| Escopo de `block_per_channel` no A3 | Campo + gate; efeito no A5 | O efeito é identificabilidade por canal, que é o A5. |
| Onde o grupo é somado | Na leitura, antes de períodos parciais e adstock | Um ponto só; todas as análises veem o grupo sem tocar no código legado. |
| Colinearidade calculada antes ou depois do grupo? | Antes (dado cru) | O relatório mostra a colinearidade real; o grupo só decide se o par está coberto. |
| Formato de `gate_thresholds` | Dict com chaves conhecidas (`collinearity_r`); chave desconhecida é config inválida | Uma chave não pede submodelo; o A4 acrescenta `control_spend_corr` e o A5 `collinearity_vif` do mesmo jeito. |
| Limite de VIF | Fica para o A5 | No A3 o VIF só é reportado; nada o lê para decidir. Quem usa (A5, identificabilidade) cria a chave. |
| Série curta | Menos de 30 períodos: não avalia (check `info`) | Com poucas datas a correlação dá ±1 por construção: o template de exemplo (2 datas) seria bloqueado. O A6 define o histórico mínimo; a A10 calibra. Decidido com o dono em 05/nov/2026. |

## Abordagens consideradas

- **(A, escolhida) Agrupar na leitura.** Uma função renomeia cada membro para o nome do grupo e soma por data, logo depois de `read_inputs`. Causal, elasticidade e cenários herdam o grupo.
- **(B) Agrupar só na elasticidade.** O causal continuaria por canal, o que contradiz o aceite ("o resultado sai só no nível de grupo") e espalha a regra por dois lugares.

## Desenho

### Arquivos

| Arquivo | Mudança |
|---|---|
| `engine/config.py` | `block_per_channel: bool = False` (seção "filled by the system"); validação de `channel_groups`; defaults dos thresholds |
| `engine/inputs.py` | `apply_channel_groups(investment_df, groups)` |
| `engine/validation.py` | `collinearity(...)` e o check `collinearity_unresolved`; check `channel_group_unknown` |
| `engine/data_preprocessor.py` | `load_and_prepare_data` chama `apply_channel_groups` logo depois de `read_inputs` |
| `tests/engine/` | testes abaixo |

### Config

- `channel_groups: list[list[str]]` (já existe). Validação no `EngineConfig`: cada grupo tem ≥ 2 membros e nenhum canal aparece em dois grupos; violação é `Configuração inválida…` (mesmo caminho dos outros erros de config). Os nomes são comparados como o motor normaliza os canais (`strip().upper()`).
- Nome do grupo: `" + ".join(membros)`, o mesmo que `engine/results.py` já usa para `elasticity.groups`.
- `block_per_channel: bool = False`, novo, fora do `ANALYST_FIELDS` da API.
- `gate_thresholds`: chave `collinearity_r` (default 0.85). Chave ausente usa o default (`GATE_DEFAULTS` em `engine/config.py`, única fonte); chave fora de `GATE_DEFAULTS` é `Configuração inválida`.

### O cálculo, em `validate`

1. Pivot data × canal do spend **cru** (o mesmo que o `dv360_cm360_overlap` já monta), sem canais de variância zero.
2. |r| de Pearson para cada par; par com |r| > `collinearity_r` entra em `pairs` como `{"a", "b", "r"}` (r arredondado a 4 casas, com sinal).
3. VIF por canal com `statsmodels.stats.outliers_influence.variance_inflation_factor`, com constante na matriz. VIF infinito ou indefinido (colinearidade perfeita) vira `None` no JSON.
4. `suggested_groups` = componentes conexos do grafo dos pares sinalizados, cada um ordenado, a lista ordenada.
5. O VIF é só reportado: não força grupo nem gera erro. VIF alto sem par forte costuma ser combinação de três ou mais canais; o A5 trata a identificabilidade e cria o limite `collinearity_vif`. VIF acima de 1e6 também vira `None` (R² arredondado para 1).
6. Com menos de 2 canais, `collinearity` sai vazio.
7. Com menos de 30 datas no pivot (`MIN_COLLINEARITY_PERIODS`), `collinearity` sai vazio e o relatório ganha `collinearity_not_assessed` (`info`), com o número de períodos em `details.periods`. O gate não roda.

### Quando o gate passa

Um par sinalizado está **coberto** se os dois canais estão no mesmo grupo de `channel_groups`, ou se `block_per_channel=true`. Se algum par não está coberto, sai:

- `collinearity_unresolved`, `error`. Mensagem pt-BR com os grupos sugeridos, por exemplo: "Os canais PMAX e SEARCH gastam juntos (correlação 0,91) e o modelo não consegue separar o efeito de cada um. Agrupe-os ou aceite resultados só no nível agregado." `details`: `{"pairs": [...não cobertos...], "suggested_groups": [...]}`.

Membro de `channel_groups` que não existe no arquivo de investimento:

- `channel_group_unknown`, `error`, com os nomes em `details.channels`. Fica no `validate` (e não no `EngineConfig`) porque depende do arquivo.

### Efeito no `run`

O `run` já recusa um relatório com erro (`EngineError` com o id do primeiro erro), então `collinearity_unresolved` bloqueia o run sem código novo. Com grupos, `load_and_prepare_data` soma os membros logo depois de `read_inputs`; dali em diante o grupo é um canal comum. Os checks que olham o dado cru (`duplicate_date_channel`, `outliers`, `dv360_cm360_overlap`) rodam antes e continuam por canal.

## Testes e aceite

- Dois canais sintéticos com r ≈ 0.95: aparecem em `pairs` e em `suggested_groups`, `collinearity_unresolved` é erro e `ok=false`; `run` levanta `EngineError` com esse id.
- Os mesmos dados com `channel_groups=[[a, b]]`: o `validate` passa, e o `run` traz um canal só, `"A + B"`, na elasticidade, com `elasticity.groups` preenchido.
- Com `block_per_channel=true`: o `validate` passa.
- VIF bate com o cálculo manual (regressão de cada canal nos outros, `1/(1-R²)`) numa matriz pequena.
- Colinearidade perfeita (um canal = 2 × outro): VIF `None`, sem exceção.
- Série com 29 datas e canais colineares: `collinearity` vazio, `collinearity_not_assessed` (`info`), `ok=true`. Com 30: avaliada.
- `channel_groups` com canal em dois grupos ou grupo de um membro: `Configuração inválida`. Membro inexistente: `channel_group_unknown`.
- Paridade intacta: no dataset sintético o maior |r| é 0.066 e os VIF ficam em ~1.01, então nada é sinalizado.
- `validate` continua < 10 s em 730 dias × 15 canais.

## O que fica para quem constrói

- Rodar o `validate` sobre a Gol (`exemplo_csv/`, não versionado, não está nesta máquina) e registrar se algum par passa de 0.85. Se passar, a paridade real (`mise run parity-real`) passa a falhar no gate: registrar e rodar com `block_per_channel=true`.
- Registrar em `docs/decisoes/engine.md` os dois ids novos no catálogo e o porquê do spend cru.

## Em aberto fora do motor

- Threshold 0.85 (e o VIF 10, que entra no A5) e o mínimo de 30 períodos: calibrar na A10 com os dados das Core.
- A spec da Trilha A fala em thresholds "ajustáveis por Admin do workspace via B1". A API não tem onde guardar isso hoje; é da Trilha B.
