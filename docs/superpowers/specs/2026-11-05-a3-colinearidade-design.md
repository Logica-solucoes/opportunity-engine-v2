# A3 · Gate de colinearidade — design

Item `A3` de `docs/m2/trilha-a-motor.md`. Depende de A2 (pronto); bloqueia A5 (identificabilidade por canal) e a tela de agrupamento do B2.

## Intenção

Dois canais que se movem juntos (PMAX e SEARCH, DV360 e CM360) tornam o coeficiente de cada um indeterminável: o modelo reparte o efeito entre eles de forma arbitrária, e o número por canal que o cliente lê é ruído. O A3 detecta isso no `validate` (correlação par a par e VIF do spend por canal), sugere agrupamentos e **obriga o analista a resolver** antes do run: agrupar os canais (o spend soma antes de modelar) ou aceitar o modelo com a marca de que o resultado por canal não é identificável (efeito no A5).

## Objetivos

- `ValidationReport.collinearity` preenchido: `pairs`, `vif`, `suggested_groups`.
- Colinearidade não resolvida bloqueia o run com o check `collinearity_unresolved`.
- `config.channel_groups` passa a ter efeito: o spend dos membros soma antes do adstock e do modelo, e o grupo é um canal em todo o `results.json`.
- `validate` e `run` usam o mesmo passo de agrupamento, então não discordam (princípio do A2).
- Sem `channel_groups` e sem colinearidade, nada muda: a paridade (sintética e Gol) segue idêntica.

## Não-objetivos

- Marcar `identifiable=false` por canal, tirar curva/mix/cenário do canal: é o A5. No A3, `block_per_channel` só faz o gate passar.
- Tela de agrupamento (B2) e o swap da API (Dev B).
- Adstock oculto por correlação negativa com o KPI (A10) e triagem de controles (A4).
- Calibrar os limiares com dados reais das Core (A10); os defaults vêm do item.

## Anti-objetivo

Agrupar ou bloquear em silêncio. Colinearidade sinalizada sem resolução explícita do analista é **erro**, nunca aviso.

## Decisões já tomadas (com o dono)

- `channel_groups` continua `list[list[str]]`; o nome do grupo é gerado: `" + ".join(membros)`. Não muda o formulário do B3.
- Agrupar acontece em um passo compartilhado entre `validate` e `run`, depois da leitura e antes do adstock (abordagem A).

## Abordagens consideradas

- **A. Passo compartilhado `apply_groups` (escolhida).** `validate` e `load_and_prepare_data` chamam o mesmo passo sobre o investimento lido. O gate é avaliado no conjunto efetivo de canais.
- **B. Agrupar só dentro do `run`.** O `validate` só detecta e confere se há alguma resolução no config; não sabe se o grupo escolhido resolve (o grupo pode continuar colinear com outro canal), e o `run` poderia falhar depois do "ok". Descartada.

## Desenho

### Arquivos

- `engine/config.py`: campo `block_per_channel: bool = False`; validação das chaves conhecidas de `gate_thresholds` (abaixo). `channel_groups` não muda de tipo.
- `engine/grouping.py` (novo): `group_name(members) -> str` e `apply_groups(investment_df, groups) -> tuple[DataFrame, list[Check]]`.
- `engine/collinearity.py` (novo): `analyze(wide, r_max, vif_max) -> Collinearity`, função pura sobre a tabela larga `Date × canal`.
- `engine/validation.py`: `validate` lê, agrupa, roda as checagens de série e de colinearidade sobre o conjunto efetivo, e preenche `collinearity`.
- `engine/data_preprocessor.py`: `load_and_prepare_data` chama `apply_groups` logo depois de `read_inputs`, antes de qualquer outra transformação (cadência, parciais, adstock). Erro de grupo vira `EngineError` com o `check_id`.
- `engine/results.py`: `_elasticity` usa `group_name` (hoje faz o join por conta própria) e `groups` lista os grupos aplicados.
- `engine/__init__.py`: nada novo a exportar.

### Limiares (`gate_thresholds`)

| chave | default | regra |
| --- | --- | --- |
| `collinearity_r` | 0.85 | número em (0, 1]; sinaliza par com \|r\| > valor |
| `vif_max` | 10 | número ≥ 1; sinaliza canal com VIF > valor |

Valor inválido numa chave conhecida levanta `EngineError` de config (mesmo caminho dos outros campos). Chave desconhecida é ignorada (o dict continua livre para o B1/Admin e para itens futuros).

### Passo `apply_groups`

Entrada: investimento longo (`Date`, `Product Group`, `investment`) já deduplicado e os grupos do config. Nomes de membro são comparados em maiúsculas e sem espaços nas pontas, como o loader normaliza os canais.

Checks (todos `error`; com qualquer um, os grupos não são aplicados e o gate de colinearidade não roda, para não somar ruído ao erro):

| id | quando |
| --- | --- |
| `group_unknown_channel` | um membro não existe no investimento (inclui canal já removido pelo `product_group_filter` do loader, se houver) |
| `group_overlap` | o mesmo canal em mais de um grupo |
| `group_too_small` | grupo com menos de 2 membros |

Sem erro: soma o spend dos membros por data, e o grupo vira o canal `group_name(membros)` (membros na ordem do config). Data em que só alguns membros têm linha soma o que existe (coerente com o `fillna(0)` do pivot). Os canais fora de grupo passam intactos. `product_group_filter` refere-se a nomes depois do agrupamento (hoje ele filtra eventos pelo `ad_product`, que já é o nome efetivo).

### Cálculo (`collinearity.analyze`)

Série por canal: o spend do investimento já sem os períodos parciais descartados (o mesmo conjunto que o `check_channel_overlap` usa), pivotado por data com 0 onde falta. **Spend cru**, como o BRD diz (resolve o "em aberto" do item). Canais constantes ou de soma zero ficam fora (não têm correlação definida), como no check de sobreposição.

- `pairs`: todo par com \|r\| > `collinearity_r`, em `{a, b, r}` com `r` assinado e arredondado a 4 casas; `a < b` em ordem alfabética, lista ordenada por \|r\| decrescente. Correlação negativa forte conta (colinearidade é sobre a relação linear, não o sinal).
- `vif`: um valor por canal analisado, `1 / (1 − R²)` da regressão do canal nos demais com intercepto (`statsmodels...variance_inflation_factor` sobre a matriz com constante). Com um só canal, ou menos linhas que canais + 1, o VIF não é definido e o dicionário sai vazio. Colinearidade perfeita (infinito) sai `null`, que o schema já aceita, e conta como VIF acima do limiar.
- `suggested_groups`: componentes conexos do grafo com arestas nos `pairs`. Um canal com VIF acima do limiar e sem nenhum par entra no componente do canal com maior \|r\| em relação a ele (multicolinearidade entre três ou mais canais, sem par que passe do limiar; decisão minha: sem isso o analista receberia um erro sem sugestão). Componentes de um só canal são descartados. Grupos e membros ordenados.

### Resolução e o gate

O `validate` calcula tudo sobre o **conjunto efetivo** (grupos do config já aplicados). `collinearity` e `channels` do relatório descrevem esse conjunto. Sem `channel_groups`, é o conjunto cru, que é o que o B2 mostra no upload.

| situação (no conjunto efetivo) | resultado |
| --- | --- |
| nenhum par nem VIF sinalizado | sem check |
| sinalizado e `block_per_channel` falso | `collinearity_unresolved` (**error**), `details`: pares, canais com VIF alto e `suggested_groups` |
| sinalizado e `block_per_channel` verdadeiro | `collinearity_blocked` (**warning**): o modelo roda; o resultado por canal destes canais não é identificável (marcação no A5) |

Um grupo que continua colinear com outro canal continua sinalizado (agrupar PMAX + SEARCH não resolve se o grupo ainda colide com DV360).

### Efeito no `run`

`run` já valida primeiro e aborta no primeiro `error` com `EngineError.check_id`; `collinearity_unresolved` e os `group_*` entram por esse caminho, sem código novo no pipeline. Com grupos válidos, `load_and_prepare_data` entrega o investimento agrupado e todo o resto (adstock, eventos, elasticidade, `results.json`) enxerga o grupo como um canal. O relatório gravado em `results.json` carrega `collinearity`.

### Falhas e segurança

Mensagens em pt-BR sem caminhos nem dados do cliente além de nomes de canal e números agregados. `details` carrega os dados estruturados para a tela do B2.

## Testes e aceite

- Teste por check: `collinearity_unresolved`, `collinearity_blocked`, `group_unknown_channel`, `group_overlap`, `group_too_small`, e um caso limpo sem colinearidade (relatório com listas vazias e sem checks novos).
- **Aceite do item:** sintético com dois canais de r ≈ 0.95 é sinalizado; com `channel_groups=[["A","B"]]` vira um canal, o run passa e o `results.json` só traz o grupo (nenhum canal `A` ou `B` isolado).
- VIF contra cálculo manual (R² de uma regressão de 3 canais pequena resolvida no próprio teste com `numpy.linalg.lstsq`).
- Invariância: renomear ou reordenar canais não muda pares, VIF nem grupos sugeridos (mesmo critério do A2).
- Correlação negativa forte é sinalizada; canal constante não quebra o cálculo; perfeita colinearidade gera `vif: null` e continua erro.
- Grupo que ainda colide com outro canal continua `collinearity_unresolved`.
- `validate` e `load_and_prepare_data` concordam: para cada caso de grupo inválido, `ok=false` ⇔ o loader levanta com o mesmo `check_id`.
- Regressão: paridade sintética e `mise run parity-real` idênticas sem grupos; fixtures de `results.json` regenerados só se o `validation.collinearity` mudar de conteúdo.
- Desempenho: `validate` < 10 s com 730 dias × 15 canais, agora incluindo a colinearidade.
- Smoke nos dados reais de `exemplo_csv/` (Gol consolidada, VW, PMAX); registrar o que cada um dá. Core: quando chegar.

## O que fica para quem constrói

- Se o `product_group_filter` do loader age antes ou depois do passo de grupos (conferir no código; o desenho assume que grupos olham o investimento completo).
- Textos exatos das mensagens pt-BR.
- Arredondamento de `r` e VIF nos `details`.

## Em aberto fora do motor

- Dev B: `api/engine_config.py` precisa do campo `block_per_channel`, e configs gravadas com `channel_groups` em formato dict (um teste do B3 grava assim) deixam de passar no `EngineConfig` estrito. A tela de agrupamento do B2 usa os ids novos. Passos em `docs/decisoes/engine.md`.
- Limiares 0.85 e 10: chutes do item; calibrar na A10 com as Core.
