# Fórmulas do motor — catálogo e auditoria

Catálogo das fórmulas do motor (`engine/`) **como estão implementadas**, não como deveriam ser. Em 08/nov/2026 agentes independentes fizeram uma auditoria por área: cada agente leu o código, montou dados sintéticos com a verdade conhecida e listou achados, e um segundo agente refez cada achado por conta própria e deu o veredito. Nada aqui substitui a validação da Data Science. Este documento é o ponto de partida dela.

Como ler:

- **Status** da fórmula: `correta` (faz o que diz, com as premissas listadas), `questionável` (a conta está certa, mas depende de premissa frágil, de heurística ou de convenção não documentada), `errada` (a conta não estima o que o nome promete).
- **Achados**: só os com veredito confirmado ou incerto. A severidade é a **corrigida** pelo verificador (alta, média, baixa). "Chega ao results.json" diz se o problema muda algum número publicado.
- Os ids repetem entre áreas (há um `F1` no MMM e outro no planner). Cite sempre a área junto com o id.
- `arquivo:linha` se refere ao código em 08/nov/2026. As linhas mudam com qualquer edição.
- Vários achados são o mesmo defeito visto de áreas diferentes. As referências cruzadas estão marcadas com "ver também".
- Achado já corrigido traz a linha **Corrigido em …**. Os demais seguem abertos: vários mudam o estimando ou a paridade com o protótipo e dependem da Data Science (A10).

---

## 1. Pré-processamento

### Fórmulas

1. **Winsorização do KPI por IQR** (`iqr_bounds` / `treat_outliers`) — `engine/data_preprocessor.py:17` — questionável
   $Q_1=q_{0.25}(y),\ Q_3=q_{0.75}(y),\ \mathrm{IQR}=Q_3-Q_1;\quad y_t \leftarrow \min(\max(y_t,\ Q_1-1.5\,\mathrm{IQR}),\ Q_3+1.5\,\mathrm{IQR})$ sobre a série inteira do KPI (pré e pós de todo evento). Quantis com a interpolação linear do pandas. Só roda com `treat_outliers` ligado (padrão `False`). Na lista, qualquer nome que não seja o do KPI é ignorado sem erro.
   Premissas: KPI mais ou menos estacionário, e outlier é erro, não sinal. Roda antes do causal e do MMM, então também corta lifts reais.

2. **`geometric_decay` do pré-processamento (EWM)** — `engine/data_preprocessor.py:33` — correta
   $y_0=x_0;\quad y_t = a\,x_t + (1-a)\,y_{t-1}$ (pandas `ewm(adjust=False)`). $a$ é o peso do valor **atual** (a retenção é $1-a$). Identidade da soma: $\sum y = \sum x + \frac{1-a}{a}(x_0 - y_T)$.
   Premissas: linhas consecutivas e igualmente espaçadas de um canal. Roda sobre as linhas do formato longo, então data faltante é pulada, não vira 0.

3. **`find_best_alpha`** — `engine/data_preprocessor.py:38` — questionável
   $a^* = \arg\max_{a\in\{0.1,\dots,0.9\}} \mathrm{corr}(\mathrm{EWM}_a(x),\ y)$. A grade não tem $a=1$ (identidade), então sempre há pelo menos 10% de suavização.
   Premissas: a melhor transformação é a que maximiza a correlação contemporânea com o KPI. Escolhida olhando os dados, sem inferência. Cai nos cantos da grade (0.1 ou 0.9 em 97% das simulações nulas).

4. **Regra de adstock por correlação negativa** — `engine/data_preprocessor.py:857` — questionável
   Para cada canal $c$: se $\mathrm{corr}(x_c, y) < 0$ (merge inner com o pivot preenchido com zero), então $x_c \leftarrow \mathrm{EWM}_{a^*}(x_c)$. O resultado vira o `investment_df`, que alimenta os eventos, as features causais, o `incremental_investment`, o `baseline.monthly`, o `current_split` e o MMM (que aplica adstock de novo).
   Premissas: correlação crua negativa quer dizer efeito defasado. Na prática costuma ser confusão (gasto contracíclico) ou ruído: dispara em cerca de 50% dos canais nulos.

5. **`detect_cadence`** — `engine/data_preprocessor.py:203` — correta
   $m = \mathrm{mediana}(\Delta \text{datas únicas, em dias})$; cadência $=1$ se $m\le1.5$; $7$ se $6\le m\le8$; $30$ se $27\le m\le31$; senão $\mathrm{round}(m)$. Menos de 2 datas dá 1.
   Premissas: as datas rotulam períodos regulares. Cadência de 28 dias (4-4-5 ou 4 semanas) vira 30 e é tratada como mensal.

6. **`drop_partial_periods`** — `engine/data_preprocessor.py:336` — questionável
   $\mathrm{thr} = 0.6\cdot\text{cadência}$. Data interna $d_i$ é fragmento sse $(d_i-d_{i-1})<\mathrm{thr}$ **e** $(d_{i+1}-d_i)<\mathrm{thr}$. Data da ponta é fragmento sse seu único intervalo $<\mathrm{thr}$. Os fragmentos são apagados, não somados ao vizinho.
   Premissas: período parcial aparece como intervalo curto entre rótulos. Período rotulado pela data de início e cortado no fim do export não aparece. Semana partida em duas linhas perde um pedaço e mantém o outro.

7. **`cadence_check`** — `engine/inputs.py:308` — questionável
   Erro sse $\lvert \text{cad}_{\text{inv}} - \text{cad}_{\text{kpi}} \rvert > 2$ dias.
   Premissas: mesma cadência implica mesmos rótulos de data. O alinhamento (semana com data na segunda contra semana com data no domingo) nunca é checado, e os merges seguintes são inner/left na data exata.

8. **`suggest_causal_config`** — `engine/data_preprocessor.py:241` — questionável
   $\text{min\_pre\_period\_days} = \min(365,\ 8\cdot\text{cad})$. Por canal: buckets W-MON (terça a segunda) se cad $<7$, senão as linhas nativas; $h_t = \mathrm{média}(x_{t-12..t-1})$ com `min_periods=1`; $\mathrm{pct}_t = (x_t/h_t - 1)\cdot100$. Limiar de aumento $=\mathrm{round}(P_{90}(\mathrm{pct}>0))$, de queda $=\mathrm{round}(P_{90}(\lvert\mathrm{pct}<0\rvert))$, cada um limitado a $[1,100]$. $\text{investment\_limit\_factor} = \mathrm{round}(2\cdot\mathrm{clip}(\max/\text{média},\ 1.5,\ 5))/2$.
   Premissas: os buckets das pontas são períodos completos (não são: no diário o primeiro e o último W-MON são parciais). A plataforma não chama esta função; é código do Streamlit antigo.

9. **`robust_numeric_parsing` / `_detect_number_format`** — `engine/data_preprocessor.py:542` — errada
   Passa direto se o pandas já inferiu tipo numérico. Senão remove tudo fora de `[\d,.-]` e vota por valor: com os dois separadores, o último é o decimal; `.` repetido vota br; `,` repetido vota us; um `.` seguido de 1–2 dígitos vota us; uma `,` seguida de 1–2 dígitos vota br; o resto (por exemplo `1.500`) não vota. Ganha a maioria, empate vai para us. Valor entre parênteses vira negativo.
   Premissas: toda coluna tem pelo menos um valor sem ambiguidade. Coluna de inteiros pt-BR (`850`, `1.500`, `12.300`) não tem nenhum, e o `read_csv` já transformou `1.500` em 1.5 antes desta função rodar.

10. **`hill_transform`** — `engine/analysis.py:30` — correta
    $h(x) = \dfrac{x^k}{s^k + x^k + 10^{-9}}$
    Premissas: $x\ge0$, $s>0$, $k>0$. Gasto negativo (estorno) com $k$ não inteiro dá NaN. O $\varepsilon$ é desprezível.

11. **`geometric_decay` da análise (lfilter)** — `engine/analysis.py:36` — correta
    $y_t = x_t + a\,y_{t-1},\ y_{-1}=0$ (scipy `lfilter([1],[1,-a])`). Aqui $a$ é a **retenção** e o resultado não é normalizado (estado estacionário $x/(1-a)$). É a convenção oposta à da função de mesmo nome do pré-processamento.
    Premissas: carry-over inicial zero, então os primeiros períodos saem subestimados (burn-in).

12. **`create_calendar_features`** — `engine/analysis.py:41` — questionável
    `month` inteiro 1..12 (sempre). Se `period_days==1`: `dayofweek` inteiro 0..6; $\text{is\_weekend} = [\text{dow}\ge5]$; $\text{is\_payday\_period} = [\text{dia}\in 1..5 \cup 15..20]$; `is_holiday` do `holidays.CountryHoliday`; $\text{day}_i = [\text{dow}=i],\ i=0..6$ (os 7 dummies, então $\sum_i \text{day}_i = 1$ e $\text{is\_weekend} = \text{day}_5+\text{day}_6$: colinearidade exata com o intercepto). O modelo causal só usa `CALENDAR_COLUMNS`, então o `month` inteiro não entra nele.
    Premissas: dia da semana e feriado só no diário. O causal semanal ou mensal fica sem nenhuma sazonalidade de calendário.

13. **`periods_to_days`** — `engine/analysis.py:74` — errada
    $p = \max(\text{min\_periods},\ \lceil \text{days}/\text{period\_days} \rceil)$; devolve $(p\cdot\text{period\_days},\ p)$. Quem chama fatia o pós como `loc[d : d + p*period_days]`, inclusivo nas duas pontas, o que dá $p+1$ linhas (e 4 ou 5 no mensal, conforme o tamanho dos meses).
    Premissas: o span seria um fim exclusivo. Não é: a fatia por rótulo é inclusiva.

14. **`apply_channel_groups`** — `engine/inputs.py:337` — correta
    $x_{g,t} = \sum_{c\in g} x_{c,t}$, agrupado por (Date, nome do grupo).
    Premissas: os membros compartilham os rótulos de data.

15. **`read_controls`** — `engine/inputs.py:45` — correta
    $\text{control}_t$ = último valor publicado em data $\le t$ (ordena por Date, forward fill).
    Premissas: data de publicação = data de referência (sem defasagem de divulgação).

### Achados

**PRE-1 — Valor inteiro pt-BR com ponto de milhar é lido 1000× menor, só a partir de 1000** — alta — `engine/data_preprocessor.py:549` — confirmado — chega ao results.json
- Afirmação: o `read_csv_robust` (linha 614) chama o `pd.read_csv` com `decimal='.'`, então `1.500` vira 1.5, e o `robust_numeric_parsing` devolve colunas numéricas sem mexer. Mesmo quando a coluna fica texto (por exemplo com `R$ `), `1.500` não vota em `_digit_group_vote` (linhas 509–511), o empate vai para us e o ponto vira decimal. Abaixo de 1000 fica certo, de 1000 em diante é dividido por 1000. A corrupção não é monotônica, nenhum check dispara, e a API repassa o arquivo cru, então afeta curvas, CPA, baseline e eventos.
- Evidência: arquivo `;` pt-BR. Só inteiros: `float64 → [850.0, 1.5, 12.3, 2.0]`. Com `R$`: `str → [850.0, 1.5, 12.3, 2.0]`. Com uma linha `2.000,50` a mais: `[850.0, 1500.0, 12300.0, 2000.5]`. O verificador reproduziu com arquivos próprios: o erro depende dos dados e só gera um warning no log.
- Correção sugerida: ler o CSV com `dtype=str` (pelo menos nas colunas de valor mapeadas) para a detecção sempre rodar. Votar br quando o delimitador for `;` ou quando todo valor com separador casar com `^\d{1,3}(\.\d{3})+$`. Se continuar ambíguo, levantar um check `value_ambiguous_format` em vez de supor us.
- **Corrigido em 08/nov/2026:** os CSV são lidos com `dtype=str`, e dois ou mais valores no padrão `^[1-9]\d{0,2}(\.\d{3})+$`, sem vírgula na coluna, votam pt-BR (um valor isolado segue ambíguo, US com aviso). Testes em `tests/engine/test_data_preprocessor.py`. Ver `docs/decisoes/engine.md` › `validate`.

**PRE-2 — Investimento e KPI com a mesma cadência mas rótulos de data diferentes não têm data em comum, e nada avisa** — média — `engine/inputs.py:308` — confirmado — chega ao results.json
- Afirmação: o `cadence_check` só compara as cadências. Gasto semanal com data na segunda e KPI semanal com data no domingo (as mesmas semanas) passam no validate sem nenhum check. Os joins seguintes são por data exata: inner no pré-processamento (`data_preprocessor.py:853`) e no causal, left com `fillna(0)` no MMM (`elasticity_analysis.py:330`), o que zera o KPI. O run termina `inconclusive / no_identifiable_channel` mesmo com o KPI função linear exata do gasto. O usuário recebe um diagnóstico errado.
- Evidência: `period_days: 7 | common dates KPI x investment: 0`, `validate checks: []`. O `engine.run` com KPI $= 100 + 0.1\cdot$gasto deslocado um dia dá `status: inconclusive`, elasticidade `['no_identifiable_channel']`. O verificador reproduziu e também obteve `causal ['no_event_passed_gates']`.
- Correção sugerida: depois da poda, medir a fração das datas do KPI presentes no investimento e dar erro (`dates_not_aligned`) abaixo de uns 80%. Opcional: oferecer reancorar os rótulos semanais num mesmo dia da semana.
- **Corrigido em 08/nov/2026:** check `dates_not_aligned` (erro) quando menos de 80% das datas do KPI, dentro do período do investimento, existem no investimento. Testes em `tests/engine/test_validate_checks.py`.

**PRE-3 — Semana partida na virada do ano mantém um pedaço como período inteiro e gera um evento falso de −57%** — média — `engine/data_preprocessor.py:380` — confirmado — chega ao results.json
- Afirmação: é o caso que a docstring diz tratar: uma semana em duas linhas (29–31/dez e 1–4/jan). O `drop_partial_periods` apaga só a data do meio e mantém o outro pedaço, com 3/7 da semana, como período completo. Com gasto constante, o `find_events` marca uma queda de −57% nessa data, bem além dos 30% do padrão. Como o KPI também está parcial, o evento "menos gasto → menos KPI" parece coerente. Os 4/7 da semana apagados somem dos totais.
- Evidência: 7000/semana constante, partida em 3000 + 4000. Depois da poda fica `2025-12-29 TV 3000.0`; gasto total `336000.0 → 332000.0`; evento `2025-12-29 TV -57.14`. O verificador reproduziu (só `2026-01-01` é apagado). A frequência real disso nos exports não foi medida.
- Correção sugerida: somar o fragmento ao período vizinho (gasto e KPI no rótulo anterior) em vez de apagar, ou apagar os dois pedaços. Registrar a junção em `partial_period_dropped`.

**PRE-4 — Agrupar o diário em semanas cria semanas parciais nas pontas que nunca são podadas, e daí um evento falso de queda no fim dos dados** — média — `engine/analysis.py:139` — confirmado — chega ao results.json
- Afirmação: no diário, o `find_events` (e o `suggest_causal_config`, `data_preprocessor.py:273`) soma o gasto em buckets `to_period('W-MON')`, que vão de terça a segunda (o `start_time` é terça), não de segunda como dizem os comentários. O primeiro e o último bucket são parciais, mas a poda rodou nas linhas diárias, onde nada é parcial (limiar de 0,6 dia). Com gasto constante, o último bucket de 3 dias dá −57% contra a média móvel: vira candidato a evento com 4 dias de pós e ocupa uma das vagas de `max_events_to_analyze`. A consolidação ainda o reetiqueta com a segunda-feira da semana W-SUN, um dia antes do bucket. O mesmo artefato leva o `suggest_causal_config` a um limiar de queda de 57% em gasto constante.
- Evidência: 1000/dia constante, 01/01/2025 a 19/06/2025 (quinta). `W-MON start_time weekday of 2025-01-01: Tuesday`; evento `2025-06-16 TV -57.14`; `suggest_causal_config` devolve `increase_threshold_percent: 7`, `decrease_threshold_percent: 57`. O verificador reproduziu: bucket de 4 dias ou menos já dispara com a razão 0,7 do padrão.
- Correção sugerida: usar `to_period('W')` (segunda a domingo) nos dois lugares e descartar o primeiro e o último bucket com menos de 7 dias distintos (ou escalar por 7/dias observados) antes de calcular a média e a razão.
- Ver também: causal-6.

**PRE-5 — A janela pós tem períodos+1 linhas (fim inclusivo), e 4 ou 5 linhas no mensal** — baixa — `engine/analysis.py:101` — confirmado — chega ao results.json
- Afirmação: `periods_to_days` devolve span $= p\cdot\text{period\_days}$, `pipeline.py:123` faz fim = intervenção + span e o `loc[start:end]` é inclusivo, então o pós tem $p+1$ linhas: 15 dias para `post_event_days=14` no diário, 5 semanas quando o log diz "Mínimo de 4 período(s) (28 dias)". No mensal, um passo de 30 dias cai em 4 ou 5 rótulos de mês. O lift absoluto acumulado, o IC e o `incremental_investment` cobrem um período a mais (+7% no diário, +25% no semanal), e o `post_period_days` da narrativa (14) não bate com as 15 linhas somadas.
- Evidência: `cad=1 post_event_days=14: periods=14 span=14 -> post rows [15]`; `cad=7 post_event_days=14: periods=4 span=28 -> [5]`; `cad=30 post_event_days=90: periods=4 span=120 -> [4, 5]`.
- Veredito: severidade rebaixada para baixa. Investimento e lift somam as mesmas linhas, então `cpa_incremental` e `rel_lift` não ficam enviesados. Só o lift absoluto e o tamanho declarado da janela erram em um período.
- Correção sugerida: fim = intervenção + $(p-1)\cdot$period_days, ou melhor, fatiar o pós por contagem de linhas (as $p$ primeiras a partir da intervenção), o que também resolve o mensal.
- Ver também: causal-7.

**PRE-6 — O adstock por correlação negativa é escolhido olhando os dados, dispara em metade dos canais nulos e depois se passa por gasto real** — média — `engine/data_preprocessor.py:857` — confirmado — chega ao results.json
- Afirmação: todo canal com correlação contemporânea crua negativa com o KPI é trocado por $\mathrm{EWM}_a(x)$, com $a$ escolhido na grade 0.1..0.9 para maximizar essa mesma correlação. A grade não tem identidade, então há sempre pelo menos 10% de suavização. Não há teste por trás: num canal sem efeito a regra dispara em ~50% das vezes e quase sempre escolhe um canto da grade. A série suavizada vira o `investment_df`, que (1) o MMM passa por adstock de novo, (2) alimenta a detecção de eventos e o `investment_change_pct` e (3) aparece no results.json como `incremental_investment`, investimento do `baseline.monthly` e `current_split`. Depois de um degrau de +100%, $a=0.1$ subestima em 24% o gasto dos 15 dias do pós, e o `cpa_incremental` sai subestimado na mesma proporção. Na série inteira o total erra em $\frac{1-a}{a}(x_0-y_T)$, +6% no exemplo. O `spend_df` guarda o gasto real, mas só o A6 e o A7 usam.
- Evidência: 2000 canais nulos (gasto iid com degrau, KPI AR(1) independente): `rule fired on 1007/2000 (50%)`; $a$ escolhido `0.1: 0.252 … 0.9: 0.717`; com $a\le0.3$ a variação da primeira semana cai de +93% para +52% (mediana). Pós de 15 dias: `30000 vs ewm 22853 (-24%)`. Canal contracíclico (corr −0,638) fica mais negativo com suavização (−0,73 em $a=0.1$), a regra escolhe 0.9 e não faz quase nada, então nem trata a confusão que pretendia tratar. O verificador refez com 1000 canais nulos: disparou em 517, $a$ nos cantos (0.1: 34%, 0.9: 47%).
- Correção sugerida: remover a regra e deixar o adstock ajustado do MMM cuidar do carry-over, ou pelo menos tirá-la de todo valor em dinheiro publicado (calcular `incremental_investment`, `investment_change_pct`, baseline e `current_split` a partir do `spend_df`).
- Ver também: MMM-F4.

**PRE-7 — O corte por IQR (quando ligado) roda na série inteira do KPI e apaga cerca de metade de um lift verdadeiro** — baixa — `engine/data_preprocessor.py:817` — confirmado — chega ao results.json
- Afirmação: o `treat_outliers` corta o KPI em $Q_3+1.5\,\mathrm{IQR}$ na série inteira, inclusive no pós de cada evento, antes do causal e do MMM. Um lift curto e real é exatamente o tipo de ponto que essa cerca remove, então o lift medido e sua significância encolhem, e os picos da elasticidade ficam achatados. É opt-in (padrão `False`), mas o check informativo `outliers` da validação pode empurrar o usuário a ligar.
- Evidência: KPI N(1000, 50), 365 dias, +300 por 15 dias: o corte mantém 48% do lift de +30% (média de 500 simulações; o verificador obteve 48,5% em 300 sementes).
- Correção sugerida: estimar as cercas no pré de cada evento, ou avisar no formulário que o corte puxa o lift causal para zero. Tornar erro um nome na lista que não seja o KPI.

**PRE-8 — A escala mensal usa 30 dias, e cadência de 28 dias vira "mensal"** — baixa — `engine/data_preprocessor.py:236` — confirmado — chega ao results.json
- Afirmação: `scenario.py:11` define `DAYS_PER_MONTH=30`, então o fator mensal é $30/\text{period\_days}$: 30 no diário e 4,286 no semanal, contra 30,44 e 4,348. Todo KPI e investimento mensal do planner sai 1,4% baixo. O `detect_cadence` arredonda medianas de 27–31 dias para 30, então dado de 4 semanas (28 dias) recebe fator 1 em vez de 1,087 (−8%) e limiar de período parcial de 18 dias.
- Evidência: $365.25/12 = 30.44$; $30/30.44 - 1 = -1.4\%$; $30.44/28 = 1.087$.
- Correção sugerida: usar $365.25/12$ nos fatores diário e semanal. Arredondar para 30 só medianas de 28–31 que não sejam exatamente 28, ou manter 28 para dado de 4 semanas.
- Ver também: planner-F9.

**PRE-9 — Duas funções `geometric_decay` com significados opostos de alpha** — baixa — `engine/data_preprocessor.py:33` — confirmado — não chega ao results.json
- Afirmação: em `data_preprocessor.geometric_decay` (EWM normalizado) alpha é o peso do valor atual (retenção $1-\alpha$); em `analysis.geometric_decay` (linha 36, `lfilter` não normalizado) alpha é a retenção. O mesmo nome e o mesmo parâmetro querem dizer coisas opostas, o que esconde a interação do adstock duplo (PRE-6).
- Evidência: `ewm(alpha=a, adjust=False)` dá $y_t = a x_t + (1-a)y_{t-1}$; `lfilter([1],[1,-a])` dá $y_t = x_t + a y_{t-1}$.
- Correção sugerida: renomear a do pré-processamento (por exemplo `ewm_smooth(series, weight)`) ou removê-la junto com a regra do PRE-6.

---

## 2. Causal

### Fórmulas

1. **Baseline da detecção (média móvel dos períodos anteriores)** — `engine/analysis.py:145` — questionável
   Por canal $c$ e bucket $b$ (diário: semanas W-MON, terça a segunda, `start_time`; `period_days`$\ge7$: linhas nativas): $I_b = \sum$ gasto em $b$; $\overline{I}_b = \mathrm{média}(I_{b-12..b-1})$ com `min_periods=1` (então $\overline{I}_1 = I_0$, $\overline{I}_2 = \mathrm{média}(I_0,I_1)$, …). Linhas com $\overline{I}_b\le0$ ou NaN são descartadas.
   Premissas: buckets completos e comparáveis. 12 buckets são 12 semanas no diário/semanal, mas 12 meses no mensal. A primeira e a última semana parciais são somadas como semanas cheias.

2. **Razão e limiares da detecção** — `engine/analysis.py:153` — questionável
   $r_b = I_b/\overline{I}_b$; $\mathrm{pct}_b = (r_b-1)\cdot100$; marcado sse $r_b > 1 + \text{inc}/100$ (padrão 1,5) ou $r_b < 1 - \text{dec}/100$ (padrão 0,7) (`pipeline.py:95-96`). $\text{flagged\_share} = \#\text{marcados}/\#\text{linhas}$, só um warning quando $>0.25$.
   Premissas: uma excursão isolada contra uma média defasada. Um degrau sustentado mantém $r_b$ acima do limiar até a média de 12 buckets alcançá-lo, então é marcado em vários buckets seguidos.

3. **Consolidação dos eventos** — `engine/analysis.py:197` — questionável
   Diário: semana do evento = início da semana W-SUN (segunda) que contém o início do bucket W-MON (terça) = início do bucket − 1 dia. Canais marcados na mesma semana se fundem; o pct do evento é o de maior $\lvert\mathrm{pct}\rvert$ entre eles.
   Premissas: a data da intervenção é o primeiro dia do bucket marcado. Na verdade é um dia antes.

4. **Conversão de janela dias → períodos** — `engine/analysis.py:74` — correta
   $\text{periods} = \max(\text{min\_periods},\ \lceil \text{days}/\text{period\_days}\rceil)$; $\text{span\_days} = \text{periods}\cdot\text{period\_days}$. Pós: mínimo 4 períodos; pré: mínimo 8.
   Premissas: `period_days` correto.

5. **Janelas pré e pós** — `engine/pipeline.py:112` — questionável
   $\text{pré} = [\text{primeira data do KPI},\ \text{intervenção}-1\text{ dia}]$; $\text{pós} = [\text{intervenção},\ \text{intervenção} + \text{span\_days}]$ inclusivo via `.loc`, ou seja, periods+1 linhas (15 linhas para `post_event_days=14` no diário).
   Premissas: o fim inclusivo deixa a janela um período mais longa que o configurado.

6. **Alinhamento dos controles** — `engine/analysis.py:260` — correta
   $\text{control}(t)$ = último valor publicado com data $\le t$ (`merge_asof` backward), depois back-fill antes da primeira publicação.
   Premissas: o back-fill usa um valor futuro antes da primeira publicação (leve olhar para frente, documentado).

7. **Triagem dos controles** — `engine/analysis.py:272` — questionável
   $r = \mathrm{corr}_{\text{Pearson}}(\text{control}_t,\ \sum_{c\in\text{evento}} \text{spend}_{c,t})$ nas linhas do pré; aceito sse $r$ indefinido ou $\lvert r\rvert \le$ `control_spend_corr` (padrão 0,5).
   Premissas: correlação em nível, então tendências comuns inflam $\lvert r\rvert$. Não testa se o controle é afetado pelo tratamento no pós.

8. **Pré-filtro de variância** — `engine/analysis.py:237` — questionável
   Mantém a feature $j$ sse $\mathrm{Var}_{\text{pré}}(x_j) > 0.01$ (sem escalar).
   Premissas: limiar absoluto fixo em escalas misturadas. As features Hill ficam em $[0,1]$ e podem cair abaixo de 0,01 quando o gasto está longe de $s$.

9. **Seleção de features** — `engine/analysis.py:483` — questionável
   $X$ escalado para $[0,1]$ (MinMaxScaler no pré); `LassoCV` com `TimeSeriesSplit(n_splits = max(2, min(5, n_pre//4)))` em $y$ = KPI; selecionadas $= \{j : \beta_j \ne 0\}$; fallback: todas as features de mídia.
   Premissas: regressão i.i.d. usada só como triagem; inclui a feature de mídia do próprio canal tratado.

10. **Feature de mídia** — `engine/analysis.py:429` — errada
    $x_{c,t} = \mathrm{Hill}(\text{adstock}_t)$, $\text{adstock}_t = \text{spend}_t + \alpha\,\text{adstock}_{t-1}$, $\mathrm{Hill}(a) = \dfrac{a^k}{s^k + a^k + 10^{-9}}$. Os mesmos $\alpha, k, s$ para todo canal. A exógena do pós usa o gasto **real** do pós, inclusive o do canal tratado.
    Premissas: as covariáveis do contrafactual não podem ser afetadas pela intervenção, e o gasto do canal tratado é a própria intervenção.

11. **Modelo contrafactual** — `engine/analysis.py:307` — questionável
    `UnobservedComponents(kpi, 'llevel', trend=True, seasonal=7, exog=X)`: $y_t = \mu_t + \gamma_t + X_t b + \varepsilon_t$, $\mu_t = \mu_{t-1} + \eta_t$, sazonal estocástico de 7 períodos. O `trend=True` é anulado em silêncio pela string `'llevel'` (o statsmodels avisa; `model.trend == False`). MLE no pré.
    Premissas: `seasonal=7` independe da cadência (ciclo de 7 semanas no semanal, 7 meses no mensal). Sem tendência, apesar do argumento.

12. **Métricas de ajuste in-sample** — `engine/analysis.py:492` — errada
    $\hat y$ = `get_prediction` um passo à frente em **todas** as linhas do pré, inclusive as do burn-in difuso ($\hat y_1 = \hat y_2 = 0$). $\mathrm{MAE} = \mathrm{média}\lvert y - \hat y\rvert$; "mape" $= \mathrm{MAE}/\mathrm{média}(y)\cdot100$ (na verdade um WMAPE); $R^2 = 1 - SS_{\text{res}}/SS_{\text{tot}}$.
    Premissas: as primeiras previsões teriam significado. São artefatos da inicialização difusa (`loglikelihood_burn = 7`).

13. **Lift acumulado e lift relativo** — `engine/analysis.py:507` — correta
    $\text{impact}_t = y_t - \hat y_t$ (previsão de $h$ passos, $t$ no pós); $A = \sum_t \text{impact}_t$; $\text{rel} = A / \sum_t \hat y_t \cdot 100$.
    Premissas: contrafactual válido (ver feature de mídia).

14. **EP acumulado, p-valor e IC** — `engine/analysis.py:293` — errada
    $SE_{\text{cum}} = \sqrt{\sum_h se_h^2}$, com $se_h$ = `forecast.se_mean` (DP preditivo no horizonte $h$, com ruído de observação); $p = 2(1-\Phi(\lvert A\rvert/SE_{\text{cum}}))$; $IC = A \pm 1.96\,SE_{\text{cum}}$.
    Premissas: erros de previsão independentes entre horizontes (falso: compartilham o erro do estado no fim da amostra e os choques de nível acumulados); modelo bem especificado; parâmetros do MLE tratados como conhecidos.

15. **Placebo** — `engine/analysis.py:313` — questionável
    Ajusta em $\text{pré}[:n/2]$, prevê $\text{pré}[n/2 : n/2+H]$; $p$ por `cumulative_p_value`; `placebo_failed` sse $p <$ `p_value_threshold` (`pipeline.py:141`). `None` se $n/2 <$ `min_pre_periods` ou $n - n/2 < H$.
    Premissas: herda o p-valor anticonservador; as features são escolhidas no pré inteiro (vazamento, documentado).

16. **WMAPE fora da amostra** — `engine/analysis.py:329` — questionável
    $\text{held} = \mathrm{round}(0.2n)$; ajusta nas primeiras $n-\text{held}$ linhas; $\mathrm{WMAPE} = \sum\lvert y-\hat y\rvert/\sum\lvert y\rvert$ nas linhas guardadas (previsão de vários passos). `None` se o treino $<$ `min_pre_periods` ou held $<7$. Gate: `oos_wmape_max` 0,30 na suficiência.
    Premissas: depende da escala: com KPI de nível alto e pouca variância, até uma previsão constante tem WMAPE baixo.

17. **Robustez (só baseline)** — `engine/analysis.py:342` — questionável
    O mesmo modelo sem as features de mídia; $A_{\text{rob}} = \sum(y - \hat y_{\text{rob}})$; $p_{\text{rob}}$ por `cumulative_p_value`. `model_dependent` sse $p < \text{thr}$ e não ($p_{\text{rob}} < \text{thr}$ e $\mathrm{sinal}(A) = \mathrm{sinal}(A_{\text{rob}})$) (`pipeline.py:144-149`).
    Premissas: herda o p-valor anticonservador.

18. **Baseline de investimento pré-evento e `investment_change_pct`** — `engine/analysis.py:547` — questionável
    Somas semanais do gasto do evento até o fim do pré; $\overline{I}$ = `rolling(12).mean().shift(1).iloc[-1]` (média das 12 semanas **antes** da última semana do pré); $\text{pre\_total} = \overline{I}\cdot(\text{len(pós)}\cdot\text{period\_days}/7)$ (diário) ou $\overline{I}\cdot\text{len(pós)}$ ($\ge7$); $\text{post\_total} = \sum$ gasto nas linhas do pós; $\mathrm{pct} = (\text{post\_total} - \text{pre\_total})/\text{pre\_total}\cdot100$.
    Premissas: exclui a última semana do pré do baseline (`shift(1)`); fora isso, razoável.

19. **CPA incremental** — `engine/analysis.py:581` — errada
    $\text{cpa\_incremental} = \text{post\_total}/A$ (0 se $A=0$; `results.py:140` troca 0 por null). `results.py:139` publica $\text{incremental\_investment} = \text{post\_total}$.
    Premissas: deveria ser $(\text{post\_total} - \text{pre\_total})/A$; usa o gasto total.

### Achados

**causal-1 — O contrafactual usa o gasto real do canal tratado no pós e absorve o lift** — alta — `engine/analysis.py:504` — confirmado — chega ao results.json
- Afirmação: a previsão que serve de contrafactual usa `exog = post_data[selected_features]`, que inclui `<canal tratado>_transformed` calculado com o gasto real (aumentado) do pós. Se o modelo aprendeu o coeficiente de mídia no pré, o contrafactual já contém o efeito da mudança de gasto, e o `absolute_lift` estima só a parte da resposta que o modelo não previu (≈ 0 quando o modelo acerta), não o efeito causal da mudança. Um contrafactual válido no estilo CausalImpact precisa de covariáveis que a intervenção não afeta; o gasto tratado é a intervenção.
- Evidência: diário sintético, KPI $= 5000 + 4000\cdot\mathrm{Hill}(\mathrm{adstock}(\text{spend})) + N(0,60)$, gasto U(800, 1200) no pré e dobrado a partir de 07/07/2025, `model_params` iguais aos $\alpha, k, s$ verdadeiros. Lift verdadeiro ≈ 14091; o motor dá `absolute_lift -445, IC [-898, 7], p 0.054`. O verificador obteve $\hat\beta = 4006$ (verdade 4000), lift −42 (p 0,86) com a exógena real e 14112 (p ≈ 0) trocando pela feature do gasto contrafactual. O gate `model_dependent` não resolve: só rejeita eventos significativos com mídia e não sem, e o estimando continua errado.
- Correção sugerida: montar a exógena do pós com as features de mídia dos canais tratados no gasto contrafactual (média do pré ou último nível pré-evento, refazendo adstock e Hill), ou tirar as features dos canais tratados do modelo contrafactual (o `baseline_only_test` já faz isso com toda a mídia e está mais perto do estimando certo).

**causal-2 — O EP acumulado ignora a correlação entre os erros de previsão: p-valores e ICs muito anticonservadores** — alta — `engine/analysis.py:301` — confirmado — chega ao results.json
- Afirmação: $SE_{\text{cum}} = \sqrt{\sum_h se_h^2}$ supõe erros de $h$ passos independentes. No modelo de nível local, $e_h = (\mu_T - \hat\mu_T) + \sum_{j\le h}\eta_j + \varepsilon_h$, então $\mathrm{Cov}(e_h, e_k) = P_T + \min(h,k)\,\sigma_\eta^2 > 0$ e $\mathrm{Var}(\sum e_h) = H^2 P_T + \sigma_\eta^2 \sum_{h,k}\min(h,k) + H\sigma_\varepsilon^2$, bem maior que o $H P_T + \sigma_\eta^2\sum h + H\sigma_\varepsilon^2$ do código. Autocorrelação residual não modelada e incerteza dos parâmetros pioram. A mesma função alimenta o p-valor do evento, o IC, o placebo e a robustez.
- Evidência: 200 replicações nulas, 180 linhas de pré e 15 de pós, sem exógena. Nível local: taxa de falso positivo 0,30, cobertura do IC 0,70, DP real da soma / $SE_{\text{cum}}$ mediana 1,85. Ruído AR(1): 0,36, 0,64 e 3,14. O verificador, com 150 replicações no nível local, obteve 0,36 e razão mediana 1,89. O viés só some quando o $\sigma^2_{\text{level}}$ ajustado é ≈ 0.
- Correção sugerida: calcular a variância da soma pela covariância conjunta da previsão (simular do modelo ajustado com `anchor='end'` e tirar o DP das somas, ou propagar a covariância do estado para a soma), de preferência sorteando também os parâmetros; usar esse DP no p, no IC, no placebo e na robustez.

**causal-3 — R², MAE e MAPE in-sample incluem as previsões do burn-in difuso (0, 0, …), e o gate `poor_fit` rejeita modelos bons** — média — `engine/analysis.py:492` — confirmado — chega ao results.json
- Afirmação: `model.get_prediction()` no pré inteiro devolve previsões de um passo cujas primeiras linhas vêm da inicialização difusa ($\hat y_1 = \hat y_2 = 0$, depois valores parciais; `loglikelihood_burn = 7` com nível local + sazonal 7). Esses erros ao quadrado são da ordem de nível² e dominam o $SS_{\text{res}}$, então o $R^2$ depende mais da razão nível/variância do KPI que da qualidade do ajuste. Com `r_squared_threshold` 0,3 e `require_model_fit` ligado por padrão, eventos em KPI com coeficiente de variação abaixo de ~12% caem como `poor_fit`; `fit.r2/mae/mape` no results.json também saem errados.
- Evidência: 180 linhas diárias, nível + seno semanal + ruído. Nível 1000, ruído 20: primeiras previsões `[0, 0, 501, 688]`, R² do motor −7,70 contra 0,75 sem o burn-in; MAE 35,3 contra 16,9. Nível 5000, ruído 60: −63,27 contra 0,18. No cenário do causal-1 o motor também dá R² −15,04 para um modelo bem especificado.
- Veredito: severidade rebaixada para média. Os eventos da fixture anonimizada chegam a R² 0,39–0,53, então KPI com CV alto passa. O viés é sistemático, mas não bloqueia todo dataset real.
- Correção sugerida: descartar as primeiras `results.loglikelihood_burn` linhas (ou as linhas com variância de estado ainda difusa) antes de calcular MAE, MAPE e R², inclusive no `accuracy_df`.

**causal-4 — `cpa_incremental` divide o gasto TOTAL do pós pelo lift** — alta — `engine/analysis.py:581` — confirmado — chega ao results.json
- Afirmação: $\text{cpa\_incremental} = \text{total\_investment\_post\_period}/\text{absolute\_lift}$. CPA incremental é gasto incremental sobre KPI incremental: $(\text{post\_total} - \text{pre\_total})/\text{lift}$. Num evento de +100% o CPA sai ~2× alto (fator $(1+g)/g$ para uma mudança $g$); num evento de queda (lift $<0$, gasto total $>0$) sai negativo, embora o custo por unidade perdida, $\Delta\text{gasto}/\Delta\text{kpi}$, seja positivo. `results.py:139` também publica `incremental_investment` = gasto total do pós.
- Evidência: com $g = \text{investment\_change\_pct}/100$, $\text{post\_total} = (1+g)\,\text{pre\_total}$ e gasto incremental $= g\,\text{pre\_total}$, então código/correto $= (1+g)/g$: 2,0 para $g=1$, 3,0 para $g=0.5$. O gate de direção exige lift $<0$ quando pct $<0$, então todo evento de queda publicado sai com CPA negativo. O `total_investment_pre_period` já é um baseline do mesmo tamanho (média histórica × períodos do pós).
- Correção sugerida: $\text{cpa\_incremental} = (\text{total\_investment\_post\_period} - \text{total\_investment\_pre\_period})/\text{absolute\_lift}$, e publicar `incremental_investment` como essa mesma diferença.

**causal-5 — Um único degrau sustentado de gasto vira vários eventos seguidos, com semanas tratadas dentro dos pré-períodos dos eventos seguintes** — média — `engine/analysis.py:145` — confirmado — chega ao results.json
- Afirmação: o baseline é a média dos 12 buckets anteriores, então depois de um degrau permanente a razão fica acima de 1,5 até a média alcançar. Cada semana marcada vira um evento. Do 2º ao k-ésimo, o pré (a janela de ajuste do contrafactual) já contém o gasto e a resposta elevados do primeiro, o que contamina o contrafactual e gera eventos quase duplicados em `events_detected` e, possivelmente, na lista publicada.
- Evidência: gasto diário U(950, 1050) dobrado a partir de 02/04/2025 e mantido. O `find_events` devolve 5 eventos: 31/03 (+88%), 07/04 (+90%), 14/04 (+72%), 21/04 (+59%), 28/04 (+50%). A consolidação só funde canais da mesma semana e o `flagged_share > 0.25` só loga warning; os quase duplicados podem passar nos gates e ser publicados (os maiores $\lvert\text{lift}\rvert$, até `max_events_to_analyze`).
- Correção sugerida: marcar só o primeiro bucket de uma sequência de buckets marcados (ou exigir que o anterior não esteja marcado), e/ou tirar do baseline os buckets já marcados.

**causal-6 — A última (e a primeira) semana incompleta é somada como semana cheia: evento falso de queda** — média — `engine/analysis.py:140` — confirmado — chega ao results.json
- Afirmação: no diário, o gasto é somado por bucket W-MON sem checar se o bucket tem 7 dias. Quando os dados terminam no meio da semana, o último bucket tem uma fração de semana e é marcado como uma queda grande; o evento é então analisado com um pós de 1 a 6 dias.
- Evidência: dados terminando na quarta, 25/06/2025, sem mudança real de gasto: `2025-06-23 A -70.37` (2 dias de gasto contra uma média de 7). O `run_causal_impact_analysis` só checa `post_data.empty`. Um primeiro bucket parcial faria o segundo parecer aumento, mas o pré dele é curto demais e é pulado, então o caso prático é o último bucket.
- Correção sugerida: descartar buckets com menos dias que um bucket cheio (ou comparar médias diárias em vez de somas) e pular eventos com pós abaixo do mínimo configurado.
- Ver também: PRE-4.

**causal-7 — O pós é um período mais longo que o configurado, e a data da intervenção é um dia antes da semana marcada** — baixa — `engine/pipeline.py:123` — confirmado — chega ao results.json
- Afirmação: $\text{end\_date} = \text{intervenção} + \text{span}$ e o `.loc[start:end]` é inclusivo, então `post_event_days=14` dá 15 linhas (o mínimo de 4 períodos dá 5 linhas semanais). No diário, o bucket marcado é W-MON (terça a segunda), mas o evento é rotulado com a segunda da semana W-SUN, um dia antes do bucket: o pós começa com um dia anterior à mudança e o pré perde esse dia.
- Evidência: `W-MON period of Wed 2025-03-12: 2025-03-11/2025-03-17`; `W period of its start 2025-03-11: 2025-03-10/2025-03-16`; `post_event_days=14 -> span=14 days, rows = 15`.
- Correção sugerida: $\text{end\_date} = \text{intervenção} + \text{span} - \text{period\_days}$; usar a mesma âncora semanal nos dois agrupamentos (por exemplo `'W'`/W-SUN também no `find_events`) para a data do evento ser o primeiro dia do bucket.
- Ver também: PRE-5.

**causal-8 — `seasonal=7` fixo independente da cadência, e `trend=True` ignorado em silêncio** — baixa — `engine/analysis.py:309` — confirmado — chega ao results.json
- Afirmação: no semanal, `seasonal=7` impõe um ciclo de 7 semanas e, no mensal, de 7 meses, sem base nenhuma, e acrescenta 6 estados difusos a um pré que pode ter só 8 linhas. A string `'llevel'` anula o `trend=True` (o statsmodels avisa "Value of trend may be overridden"; o modelo ajustado tem `trend=False`), então o modelo é nível local, não tendência linear local como a chamada sugere.
- Evidência: `trend: False stoch_trend: False level True k_states 7 params [sigma2.irregular, sigma2.level, sigma2.seasonal]`. É erro de especificação, não falha; o efeito nas saídas é indireto.
- Correção sugerida: `seasonal=7` só quando `period_days == 1` (`None` nos outros casos); passar `'lltrend'` ou tirar o `trend=True`, para o código dizer o que ajusta.

---

## 3. MMM (elasticidade)

### Fórmulas

1. **Adstock geométrico (truncado, não normalizado)** — `engine/elasticity_analysis.py:89` — correta
   $a_t = \sum_{j=0}^{\min(11,t)} \alpha^j x_{t-j}$; pesos $\alpha^j$, $j=0..11$ (`max_len`=12 períodos), sem normalização e sem gasto anterior à amostra.
   Premissas: $\alpha\in[0, 0.9]$ (limite na linha 385); a defasagem é em períodos (dias ou semanas, conforme a cadência). Em $\alpha=0.9$ a cauda cortada é $0.9^{12} = 28\%$ da massa e o ganho estacionário é $(1-0.9^{12})/0.1 = 7.18\times$. As primeiras 11 linhas ficam com adstock incompleto (aquecimento).

2. **Saturação de Hill** — `engine/elasticity_analysis.py:117` — correta
   $h(a) = \dfrac{1}{1 + \left(\max(a/(s+10^{-9}),\ 10^{-9})\right)^{-k}} = \dfrac{a^k}{a^k + s^k}$ para $a > 10^{-9}$, senão 0.
   Premissas: $k\in[0.1, 1]$ força concavidade. $s\in[0.01\cdot\mathrm{média}(x),\ \max(3\max(x),\ 2\,\mathrm{média}(x))]$ é definido no gasto **cru**, enquanto $h$ se aplica ao gasto com adstock (até ~7× maior), então o comentário "$s$ perto do máximo histórico" não vale nas unidades da entrada.

3. **Estágio 1: baseline orgânico** — `engine/elasticity_analysis.py:368` — questionável
   $b_t$ = `Ridge(alpha=1)` com intercepto, sem restrição, ajustado em `MinMax(month_1..12, is_weekend, is_payday_period, is_holiday, trends)` contra $y_t$; $\text{lift}_t = y_t - b_t$ (média do lift exatamente 0, intercepto sem penalidade).
   Premissas: mídia independente de calendário/tendências; o intercepto absorve o efeito médio da mídia no baseline.

4. **Estágio 2: ajuste de marketing** — `engine/elasticity_analysis.py:440` — errada
   $z_{t,c} = \dfrac{h_c(a_{t,c}) - \min_t h_c}{\max_t h_c - \min_t h_c}$; $\beta = \arg\min \lVert \text{lift} - Z\beta\rVert^2 + 1\cdot\lVert\beta\rVert^2$, $\beta\ge0$, **sem intercepto**; $\beta$ final = média dos 200 $\beta$ do bootstrap.
   Premissas: o alvo tem média 0, $Z\ge0$ tem média $>0$ e o modelo não tem intercepto: especificação errada (ver F1).

5. **Contribuição e participação da mídia** — `engine/elasticity_analysis.py:461` — errada
   $C_c = \beta_c \sum_t z_{t,c}$; $\text{contribution\_pct}_c = 100\,C_c/\sum_c C_c$; $\text{media\_contribution\_pct} = 100\sum_c C_c/\sum_t y_t$.
   Premissas: o zero de $z$ é o menor nível observado de adstock+Hill, não gasto zero; o estágio 1 já guarda o efeito médio da mídia.

6. **Previsão do KPI para um vetor de gasto** — `engine/elasticity_analysis.py:152` — questionável
   $\mathrm{KPI}(x) = \overline{b} + \beta\cdot\max(0,\ \mathrm{MinMax}(h(x\cdot G_c)))$, com $G_c = \sum_{j<12}\alpha_c^j$ o ganho estacionário (linha 646) e $\overline{b} = \mathrm{média}_t(b_t) = \mathrm{média}_t(y_t)$.
   Premissas: gasto zero prevê o KPI médio histórico (que inclui a mídia); o gasto atual prevê KPI médio $+ \beta\cdot\bar z$.

7. **Banda do KPI** — `engine/elasticity_analysis.py:161` — questionável
   $[p_5, p_{95}]$ sobre $b$ de $\overline{b} + \beta^{(b)}\cdot\max(0,\ \mathrm{MinMax}(h))$, com $\beta^{(b)}$ do bootstrap iid por linha.
   Premissas: adstock/Hill/scaler/estágio 1 fixos (dito na docstring); linhas iid (não dito; subcobre com autocorrelação).

8. **Score da validação walk-forward** — `engine/elasticity_analysis.py:187` — questionável
   $\text{folds} = \min(3, \lfloor n/20\rfloor)$; se $<2$: MSE e $R^2$ in-sample; senão `TimeSeriesSplit(folds)`, scaler e Ridge positivo sem intercepto reajustados em cada fold de treino; devolve a média do MSE dos folds e o $R^2$ OOF agregado $= 1 - \sum(y-\hat y)^2/\sum(y - \bar y_{\text{teste agregado}})^2$ (0 se o $y$ de teste for constante).
   Premissas: o alvo lift vem de um estágio 1 ajustado em todas as linhas (vazamento); adstock/Hill escolhidos nos mesmos folds; a referência do $R^2$ é a média agregada do teste, não a do treino.

9. **Objetivo e otimizador** — `engine/elasticity_analysis.py:225` — questionável
   $\theta^* = \arg\min_\theta \text{CV-MSE}(\alpha, k, s)$, L-BFGS-B com diferenças finitas, partida $(0.5, 1.0, \mathrm{média}\ x)$ mais 3 partidas uniformes nos limites, fica o menor valor.
   Premissas: objetivo não suave (conjuntos ativos do Ridge positivo); parâmetros em escalas muito diferentes ($s$ em moeda).

10. **Bootstrap dos coeficientes** — `engine/elasticity_analysis.py:288` — questionável
    Para $b = 1..200$: $\text{idx}\sim\text{Uniforme}\{0..n-1\}^n$ iid; $\beta^{(b)}$ = Ridge positivo sem intercepto em $(Z[\text{idx}], \text{lift}[\text{idx}])$.
    Premissas: linhas permutáveis (ignora a correlação serial da mídia e dos resíduos); condiciona em $\theta^*$, no estágio 1 e no scaler.

11. **Regra de identificabilidade** — `engine/identifiability.py:15` — questionável
    $C^{(b)}_c = \beta^{(b)}_c\sum_t z_{t,c}$; $(lo, hi)$ = percentis 2,5 e 97,5 de $C^{(b)}$; ponto $= \mathrm{média}_b(\beta^{(b)})\sum_t z$; identificável sse $lo > 0$ e $hi - lo \le$ ponto e o canal fora do conjunto colinear.
    Premissas: com distribuição amostral quase normal, $hi - lo \le$ ponto equivale a ponto/EP $\ge$ ~3,92 (bem mais rígido que 1,96); $lo \le 0$ é o teste certo de "cruza o zero" com $\beta\ge0$; herda a subcobertura do bootstrap iid.

12. **Número de folds** — `engine/elasticity_analysis.py:184` — correta
    $\text{folds} = \min(3,\ \max(1,\ \lfloor n_{\text{linhas}}/20\rfloor))$.
    Premissas: $n$ em períodos.

### Achados

**F1 (MMM) — O Ridge do estágio 2 não tem intercepto num alvo de média zero: o efeito da mídia é atenuado e os canais always-on são zerados** — alta — `engine/elasticity_analysis.py:440` — confirmado — chega ao results.json
- Afirmação: o lift = $y$ − ajuste do estágio 1 tem média exatamente 0 (o estágio 1 tem intercepto sem penalidade), mas o estágio 2 o regride em $z\in[0,1]$ com média $>0$, `positive=True` e `fit_intercept=False`. Com um canal, $\hat\beta = \sum z\,\text{lift}/\sum z^2 = \mathrm{Cov}(z,\text{lift})/(\mathrm{Var}(z) + \bar z^2)$, encolhido por $\mathrm{Var}/(\mathrm{Var}+\bar z^2)$ (≈ 1/4 para um canal uniforme). Com vários canais, a restrição de positividade zera os de $\bar z^2$ grande frente a $\mathrm{Var}(z)$ (gasto always-on). O mesmo ajuste é usado na CV (linhas 207/215) e no bootstrap (linha 290), então `contribution_pct`, `media_contribution_pct`, `coef_ci`, `identifiable`/`reasons`, `cv_r2` e as curvas herdam o problema.
- Evidência: 730 dias, A always-on (1000 ± 100), B uniforme 0–2000, $y = 5000 + \text{sazonalidade} + 400h_A + 400h_B + N(0,150)$; mídia verdadeira 7,2% do KPI, divisão A/B ≈ 52/48. Em 8 sementes: `media_contribution_pct` 0,1–0,3% (verdade 7,2%), divisão A/B 0/100 em 8/8, R² 0,002–0,013, A nunca identificável (IC (0, 0)). Estágio 2 isolado com os parâmetros verdadeiros, semente 0: sem intercepto A = 0, B = 7613, R² 0,005; com intercepto A = 55865, B = 90750, R² 0,062 (verdade acima do gasto mínimo A = 38497, B = 99373). O verificador reproduziu com dados próprios: sem intercepto 0 / 18159, R² 0,025; com intercepto 33463 / 146976, R² 0,21, contra a verdade 31072 / 146768.
- Correção sugerida: estágio 2 com `fit_intercept=True` (ou $z$ centrado), ou melhor, ajustar baseline e mídia juntos num modelo só (calendário livre, mídia positiva), para o estágio 1 não remover o nível da mídia. Usar a mesma especificação em `walk_forward_cv_score` e `bootstrap_coefficients` e regenerar as fixtures.
- Ver também: planner-F2.

**F2 (MMM) — O zero da contribuição e da curva é o menor nível observado e o KPI médio histórico, não gasto zero** — média — `engine/elasticity_analysis.py:461` — confirmado — chega ao results.json
- Afirmação: como o MinMaxScaler leva o menor valor de adstock+Hill de cada canal a 0 e o intercepto do estágio 1 já guarda o efeito médio da mídia, $C_c = \beta_c\sum z_c$ mede o efeito acima do menor gasto observado, não a contribuição do canal. O `predict_clipped_kpi` em gasto zero corta $z$ em 0 e devolve `organic_baseline_mean`, que é igual a $\mathrm{média}(y)$, o KPI histórico com mídia. Um canal always-on com piso alto aparece com contribuição pequena mesmo sendo o que mais move o KPI, e a curva diz "corte toda a mídia e o KPI fica na média histórica". Isso continua depois de corrigir o F1, e nada no results.json diz que a contribuição é "acima do gasto mínimo".
- Evidência: semente 0, canal A: contribuição verdadeira relativa a gasto zero 145701 contra 38497 relativa ao mínimo (3,8×). Em toda semente `organic_baseline_mean` = KPI médio a 0,1 de diferença (5378,9 contra 5378,9). O verificador obteve 161k contra 31k (5×) e confirmou que o Ridge com intercepto dá previsão média igual a $\mathrm{média}(y)$. A definição é defensável se for rotulada, e não é.
- Correção sugerida: usar um scaler ancorado no zero (dividir pelo máximo, sem deslocar) para $z=0$ querer dizer gasto zero, e calcular o baseline sem a média da mídia (modelo conjunto, ou $\text{baseline\_mean} = \mathrm{média}(y) - \mathrm{média}(\text{previsão da mídia})$). Se a definição pelo mínimo ficar, rotular `contribution_pct`/`media_contribution_pct` como "incremental acima do menor gasto observado".

**F3 (MMM) — Bootstrap iid por linha em série temporal subcobre: `coef_ci`, identificabilidade e banda do KPI estreitos demais** — média — `engine/elasticity_analysis.py:289` — confirmado — chega ao results.json
- Afirmação: o `bootstrap_coefficients` reamostra linhas iid, mas as features com adstock e os resíduos são serialmente correlacionados. O IC por percentil subestima a dispersão amostral, então o `coef_ci` e o `kpi_band` (A8) saem estreitos e o `identifiability.assess` ($lo>0$, $hi-lo\le$ ponto) declara canais identificáveis com facilidade demais. Além disso, condiciona nos parâmetros otimizados de adstock/Hill e no estágio 1; a docstring do `kpi_band` diz isso, a do `coef_ci` não.
- Evidência: modelo bem especificado sem intercepto $y = 0.6x + e$, $x$ e $e$ AR(1), $n=300$, 300 repetições, `n_bootstrap=200`. Cobertura do IC de 95%: $\rho=0$ → 0,917; $\rho=0.5$ → 0,733; $\rho=0.8$ → 0,497. O verificador (150 repetições): 0,953 em $\rho=0$ e 0,58 em $\rho=0.8$. Hoje o F1 tende a zerar coeficientes em vez de torná-los identificáveis, o que atenua o impacto atual.
- Correção sugerida: bootstrap em blocos móveis (ou estacionário) com bloco de ~$n^{1/3}$, ou pelo menos o horizonte do decaimento do adstock, reamostrando blocos contíguos de $(Z, \text{lift})$. Idealmente refazer o estágio 1 dentro de cada réplica.
- Ver também: G2.

**F4 (MMM) — Canais com correlação negativa com o KPI passam por adstock duas vezes antes do MMM** — média — `engine/elasticity_analysis.py:306` — confirmado — chega ao results.json
- Afirmação: o `run_mmm_engine` lê `prepared.investment_df`, que o pré-processamento (`data_preprocessor.py:857-864`) já passou por `geometric_decay` nos canais com $\mathrm{corr}(\text{gasto}, \text{KPI}) < 0$. Depois aplica `geometric_adstock` de novo (linha 434), então esses canais recebem a convolução de dois decaimentos. `df[col].mean()/max()` (limites de $s$ na linha 402, `avg_daily_spend` e máximo histórico nas curvas) ficam em unidades suavizadas, e o intervalo `extrapolated` do A8 e o eixo de orçamento ficam inconsistentes para esses canais.
- Evidência: caminho no código: `data_preprocessor.py:861` sobrescreve o investimento com `geometric_decay(...)`; a docstring do `PreparedData` (linha 756) diz "the adstock already applied"; `pipeline.py:251` passa `prepared` ao `run_mmm_engine`, que pivota `prepared.investment_df` (linha 310) e aplica adstock de novo (linha 434). O `spend_df` (cru) existe e não é usado no MMM.
- Veredito: correção do verificador à afirmação: a EWM tem pesos que somam 1, então é uma suavização que preserva mais ou menos o nível médio; "não está em unidades de dinheiro" é exagero. Mas ela encolhe máximo e variância, o que mexe nos limites de $s$, no máximo histórico, no intervalo de extrapolação e no eixo da curva, e empilha um segundo carry-over no $\alpha$ ajustado. `pipeline.py:256` também calcula o `current_split` da série suavizada; os totais mudam pouco.
- Correção sugerida: montar o pivot do MMM a partir de `prepared.spend_df` e deixar o $\alpha$ ajustado como único adstock.
- Ver também: PRE-6.

**F5 (MMM) — `cv_r2` não é totalmente fora da amostra: o estágio 1 vê todas as linhas e adstock/Hill são escolhidos nos mesmos folds** — baixa — `engine/elasticity_analysis.py:450` — confirmado — chega ao results.json
- Afirmação: o alvo lift é o resíduo de um estágio 1 ajustado na série inteira, folds de teste incluídos. $\theta^*$ minimiza o mesmo CV-MSE cujo $R^2$ é publicado, e o $R^2$ OOF agregado usa a média agregada do teste como referência. Os três puxam o `cv_r2` para cima em relação a um holdout verdadeiro, e o `cv_r2` decide a realocação (`reallocation_min_cv_r2` = 0,10) e é publicado. Com o estágio 2 mal especificado de hoje (F1) o viés medido é pequeno, mas crescerá quando o estágio 2 puder ajustar de fato.
- Evidência: dados nulos (sem efeito de mídia), $n=120$, 8 sementes: `cv_r2` médio depois da seleção +0,0003 contra −0,0009 com parâmetros fixos (viés ≈ +0,001); nenhum chegou a 0,10. O vazamento é mostrado por derivação, não medido. O verificador confirmou pela leitura do código, sem medir à parte.
- Correção sugerida: reajustar o estágio 1 dentro de cada fold de treino (ou ajustar junto, ver F1), medir o $R^2$ contra a média do fold de treino e publicar o `cv_r2` num bloco final de holdout que não foi usado para escolher $\theta$.

---

## 4. Curva e planner

### Fórmulas

1. **Adstock geométrico (o mesmo do ajuste e do planner)** — `engine/elasticity_analysis.py:89` — correta
   $a_t = \sum_{j=0}^{11}\alpha^j x_{t-j}$ (truncado em 12 defasagens, convolução causal).
   Premissas: carry-over geométrico com memória finita de 12 períodos; $\alpha\in[0, 0.9]$.

2. **Multiplicador do adstock em estado estacionário** — `engine/elasticity_analysis.py:643` — correta
   $m_c = \text{adstock}(\mathbf{1}_{30}, \alpha_c)[-1] = \sum_{j=0}^{11}\alpha_c^j = \dfrac{1-\alpha_c^{12}}{1-\alpha_c}$; gasto com adstock simulado $= \text{spend}_c\cdot m_c$.
   Premissas: gasto constante mantido até o estado estacionário; o mesmo truncamento do ajuste, então consistente.

3. **Saturação de Hill** — `engine/elasticity_analysis.py:117` — correta
   $h(a) = \dfrac{1}{1+(a/(s+10^{-9}))^{-k}} = \dfrac{a^k}{a^k+s^k}$, $h(a\le10^{-9}) = 0$.
   Premissas: $k\in[0.1, 1]$, então côncava em $a$.

4. **KPI pontual do planner** (`simulate_kpi`, objetivo, curvas individuais) — `engine/elasticity_analysis.py:152` — errada
   $\mathrm{KPI}(x) = \overline{B} + \sum_c \beta_c\max\left(0,\ \dfrac{h_c(\min(x_c,\ 3\max_{\text{hist},c})\,m_c) - h^{\min}_c}{h^{\max}_c - h^{\min}_c}\right)$, com $\overline{B}$ a média da previsão orgânica do estágio 1, $\beta$ a média dos 200 coeficientes do bootstrap (Ridge positivo sem intercepto) e $h^{\min}/h^{\max}$ o intervalo do MinMaxScaler nas features Hill do treino.
   Premissas: estado estacionário com gasto constante; gasto por canal limitado a `per_channel_investment_limit_factor` × máximo histórico; o corte em 0 faz todo gasto igual ou abaixo do mínimo histórico valer o mesmo que gasto zero (ver F1).

5. **Banda do KPI p5/p95** — `engine/elasticity_analysis.py:161` — questionável
   $[lo, hi] = \text{percentil}_{5,95,b}\left(\overline{B} + \beta^{(b)}\cdot\text{clip}_0(\text{features escaladas})\right)$, $\beta^{(b)}$ dos coeficientes do bootstrap iid por linha.
   Premissas: Hill/adstock/scaler fixos (a docstring diz que é otimista); a reamostragem iid ignora a autocorrelação, então a banda é mais estreita que a de um bootstrap em blocos; é banda da resposta média, não intervalo de predição.

6. **Flag de extrapolação (agregada)** — `engine/elasticity_analysis.py:683` — correta
   $\text{extrap} = \neg(\min_t S_t \le X \le \max_t S_t)\ \lor\ \exists c: \neg(\min_t x_{c,t} \le X\cdot\text{mix}_c \le \max_t x_{c,t})$, com $S_t$ o gasto total da linha.
   Premissas: só intervalos marginais (um ponto dentro de todos os intervalos marginais pode estar fora do suporte conjunto); usa o gasto sem o teto.

7. **Flag de extrapolação (curva individual)** — `engine/elasticity_analysis.py:1048` — correta
   $\text{extrap} = \neg(\min_t x_{c,t} \le \text{spend} \le \max_t x_{c,t})$; os outros canais na média.
   Premissas: só intervalo marginal.

8. **Mix histórico** — `engine/elasticity_analysis.py:614` — correta
   $w_c = \mathrm{média}_t\,x_{c,t}\ /\ \sum_c \mathrm{média}_t\,x_{c,t}$.
   Premissas: nenhuma.

9. **Otimização do mix por orçamento** — `engine/elasticity_analysis.py:720` — errada
   $\max_x \mathrm{KPI}(x)$ s.a. $\sum x = X$, $0\le x_c\le X$ (SLSQP, partindo do mix anterior); depois $\text{mix} = \text{cap}(x/X)$ com teto por canal $\min(\text{max\_channel\_mix\_share},\ 3\max_{\text{hist},c}/X)$; mix histórico se `cv_r2` < `reallocation_min_cv_r2`.
   Premissas: supõe KPI côncavo para o ótimo local ser global, o que é falso por causa do corte em 0 (F1); os tetos podem deixar parte do orçamento sem alocar (F6).

10. **Redistribuição dos tetos de participação** — `engine/elasticity_analysis.py:526` — questionável
    Repete: $\text{over} = \{c: w_c > \text{cap}_c\}$; $\text{excesso} = \sum(w_c - \text{cap}_c)$; $w_c = \text{cap}_c$ nos de over; $w_u \mathrel{+}= \text{excesso}\cdot w_u/\sum_u w_u$ nos sem teto atingido (fallback: pesos históricos, depois uniforme); para quando não sobra canal sem teto (o excesso é descartado).
    Premissas: viável só se $\sum \text{cap}_c \ge 1$; senão $\sum w < 1$ sem aviso.

11. **Grade da curva agregada** — `engine/elasticity_analysis.py:639` — correta
    $X_i = m_i\sum_c\mathrm{média}\,x_c$, $m_i = \mathrm{linspace}(0,\ \text{investment\_limit\_factor},\ 100)$.
    Premissas: unidades por período (linha); o gasto atual só cai na grade se $99/\text{limite}$ for inteiro.

12. **KPI e investimento incrementais na curva** — `engine/elasticity_analysis.py:805` — questionável
    $\Delta K_i = \max(0,\ \mathrm{KPI}(X_i, \text{mix estratégico}_i) - \mathrm{KPI}(X_0, \text{mix histórico}))$; $\Delta X_i = \max(0,\ X_i - X_0)$.
    Premissas: mistura o efeito da mudança de orçamento com o da realocação (F4).

13. **Receita, iROAS, iCPA (motor)** — `engine/elasticity_analysis.py:826` — correta
    $\text{Rev} = \mathrm{KPI}\cdot\text{conv}\cdot\text{ticket}$ (conv = ticket = 1 se `kpi_is_monetary`); $\text{iROAS} = (\text{Rev}_i - \text{Rev}_0)/\Delta X_i$ (0/0 → 0, x/0 → ±inf); $\text{iCPA} = \Delta X_i/\Delta K_i$ (0/0 → 0, inf → NaN).
    Premissas: razões incrementais médias (de arco) a partir do gasto de hoje, não marginais.

14. **Ponto de máxima eficiência** — `engine/elasticity_analysis.py:836` — errada
    Modo receita: $\arg\max_{X_i\ge X_0}\text{iROAS}_i$; senão Kneedle: $\arg\max\ \lvert y_n - x_n\rvert/\sqrt2$ com $x, y$ normalizados min-max em $X_i \ge X_0$; KPI avaliado com o mix histórico do "Pico de Eficiência".
    Premissas: numa curva côncava o iROAS médio a partir de $X_0$ é decrescente, então a regra do modo receita sempre devolve o primeiro ponto da grade acima de $X_0$ (F5).

15. **Ponto de limite estratégico** — `engine/elasticity_analysis.py:906` — errada
    Maior $X_i > X_0$ com $\text{CPA} = X/\mathrm{KPI} \le$ target_cpa, $0 < \text{iCPA} \le$ target_icpa, $\text{ROAS} = \text{Rev}/X \ge$ target_roas, $\text{iROAS} \ge$ target_iroas; se nenhum: o $X$ mais perto de investment_limit_factor·$X_0$ (o maior orçamento).
    Premissas: o fallback contradiz os filtros (F3).

16. **Escala mensal (scenario)** — `engine/scenario.py:250` — correta
    $\text{fator} = 30/\text{period\_days}$; investimento, KPI, banda, receita e incrementais × fator; CPA, iCPA, ROAS e iROAS ficam como razões sem escala.
    Premissas: mês de 30 dias (−1,4% contra 30,44); razões não dependem da escala, então é consistente.

17. **CPA / ROAS / iCPA / iROAS / incrementalidade do scenario** — `engine/scenario.py:113` — questionável
    $\text{cpa} = X/\mathrm{KPI}$; $\text{roas} = \text{Rev}/X$; $\text{icpa} = \Delta X/\Delta K$ (`None` se $\Delta K\le0$); iroas vem do motor; $\text{pct\_incrementality} = \Delta K/\mathrm{KPI}\cdot100$; linhas da tabela: $\Delta X = X - X_{\text{atual}}$, $\Delta K = \mathrm{KPI} - \mathrm{KPI}_{\text{atual}}$, $\text{iroas} = \Delta\text{Rev}/\Delta X$ se $\Delta K > 0$.
    Premissas: o KPI inclui o baseline orgânico (CPA/ROAS misturados); $\Delta K$ carrega o ganho da realocação (F4).

18. **Rampa** — `engine/scenario.py:40` — correta
    Níveis $L_j = c\,(1\pm s)^j$ até cruzar o alvo $t$, último nível $= t$; $n = \lceil \log(t/c)/\log(1\pm s)\rceil$; KPI e banda de cada degrau por interpolação linear na curva.
    Premissas: a curva usa o mix estratégico mesmo para cenários com outro mix; o `results.py` sobrescreve só o degrau de chegada.

19. **Ponto de saturação** — `engine/scenario.py:146` — correta
    Nas linhas com $X \ge X_{\text{início}}$: $d_j = (y_j - y_{j-1})/(X_j - X_{j-1})$, $d_0 = 0$; pico $= \max d$; $j^*$ = último $j$ com $d_j > 0.1\cdot$pico; saturação = linha $j^*+1$ (`None` se passar do fim → recomendado ou última linha).
    Premissas: 10% do marginal de pico medido a partir do gasto de hoje; sensível ao ruído do SLSQP no mix reotimizado.

20. **Curva de resposta individual** — `engine/elasticity_analysis.py:1033` — questionável
    Grade de gasto $\mathrm{linspace}(0,\ \min(\max(\mathrm{média}_c\cdot L,\ 1.2\,\text{rec}_c),\ 3\max_{\text{hist},c}),\ 100)$; $\mathrm{KPI} = \overline{B} + \beta\cdot\text{clip}_0(h(\text{spend}\cdot m)\ \text{escalado})$, outros canais na média.
    Premissas: o mesmo artefato do corte em 0 do F1 (plana de 0 até o mínimo histórico).

21. **Mix do "Pico de Eficiência" (otimizado)** — `engine/analysis.py:1077` — questionável
    Somas semanais (W-MON); $\text{eff}_t = \sum_{t-3..t}\mathrm{KPI}/\sum_{t-3..t}\text{spend}$; semanas do topo $\text{eff}_t \ge q_{90}$; $\text{mix} = \sum_{\text{semanas do topo}}\text{spend}_c/\text{gasto total}$.
    Premissas: KPI total (com orgânico) sobre gasto favorece semanas de gasto baixo; a razão móvel de 4 semanas e o mix de uma semana só ficam desalinhados (F8).

22. **Projeção de oportunidade** (via `pipeline.analyze_events`; só $\alpha, k, s$ seguem adiante) — `engine/analysis.py:805` — questionável
    $\alpha = \arg\max_{0.1..0.9}\mathrm{corr}(\text{geometric\_decay}(S, \alpha),\ y - \text{baseline OLS})$; Hill $(k, s)$ por `curve_fit` de $\max(\text{resid})\cdot h(a)$; KPI da curva $= \text{base} + h(X/(1-\alpha))\cdot\max(\text{resid})$. O pipeline descarta a curva e os cenários dela (`projection[7] = {alpha, k, s, scaler}` alimenta o modelo causal).
    Premissas: estado estacionário $1/(1-\alpha)$ não truncado contra decaimento truncado; a amplitude fixa $\max(\text{resid})$ não é uma escala ajustada; nenhuma saída de planner dela chega ao results.json.

### Achados

**F1 (planner) — O corte em 0 das features min-max faz o gasto abaixo do mínimo histórico de um canal não valer nada; o otimizador é premiado por zerar canais** — alta — `engine/elasticity_analysis.py:152` — confirmado — chega ao results.json
- Afirmação: o `predict_clipped_kpi` (e o `kpi_band`, linha 160) calcula $\beta_c\max(0, (h_c - h^{\min}_c)/(h^{\max}_c - h^{\min}_c))$. Como o estágio 2 não tem intercepto, a feature escalada é exatamente 0 no gasto mínimo histórico, e todo gasto em $[0, \min]$ dá o mesmo KPI. O KPI deixa de ser côncavo ao longo da reta de orçamento: tirar um canal do mínimo para 0 não custa nada, e o SLSQP (que supõe um problema suave e côncavo) cai num ótimo interno local ou no canto conforme a partida. Resultados: (a) a curva no orçamento de hoje, feita com o mix estratégico partindo do anterior, mostra um ganho de realocação fantasma; (b) o cenário `strategic_reallocation`, resolvido a partir do histórico, discorda da linha da curva no mesmo orçamento; (c) gasto zero vale o mesmo que gasto mínimo nas curvas agregada e individual.
- Evidência: MMM de 2 canais montado à mão (como em `tests/engine/test_guardrails.py`): `B min=100.6: kpi(A=mean,B=0)=1558.93 = kpi(A=mean,B=min)=1558.93`. SLSQP no orçamento de hoje: partida histórica `x=[187.7 118.7] kpi=1953.0`, partida 90/10 `x=[306.3 0.] kpi=2428.6`, força bruta 2428.6; gradientes iguais na parada (6,943 contra 6,944), ótimo local genuíno de um objetivo não côncavo. Dois canais lineares idênticos (KPI verdadeiro $= 1000 + 3a + 3b$, nenhum mix é melhor): verdade 1919,0; motor no mix histórico 1900,2; linha da curva no orçamento de hoje (A = 31, B = 276) 2096,5 (+10% fantasma); `strategic_reallocation` no mesmo orçamento 1901,5.
- Veredito: (a) e (c) reproduzidos pelo verificador (dois canais idênticos com Hill $k=1$, $s=150$: kpi(B=0) = kpi(B=min) = 1942,57; o SLSQP leva o mix para A = 276 / B = 31 e o motor dá ganho de realocação 1975,8 contra 1951,9, com verdade 0; força bruta confirma que o corte é o que faz o canto compensar). (b) não apareceu na verificação: lá a linha da curva bateu com o ponto de realocação (1975,8) porque as partidas coincidiram.
- Correção sugerida: parar de tratar o mínimo histórico como efeito zero. Ajustar o estágio 2 nas features Hill sem escala ($h(0) = 0$ já) ou dividir só por $h^{\max}$ (sem deslocar), para gasto zero dar contribuição zero e o objetivo continuar côncavo; aí o corte fica desnecessário. Rodar a realocação com várias partidas, ou resolver no simplex em espaço de participações.
- Ver também: MMM-F1, MMM-F2.

**F2 (planner) — A divisão em dois estágios põe o nível da mídia no baseline orgânico e atenua a inclinação: o KPI com gasto zero é a média histórica, e o iCPA sai ~10× inflado** — alta — `engine/elasticity_analysis.py:381` — confirmado — chega ao results.json
- Afirmação: o estágio 1 (Ridge com intercepto, só calendário e contexto) passa pela média do KPI, então o `y_lift` tem média 0 e o efeito médio da mídia vai para o `organic_baseline_mean` (linha 511). O estágio 2 regride esse lift de média zero em features não negativas sem intercepto, o que encolhe cada inclinação por ~$\mathrm{var}(x)/(\mathrm{var}(x) + \mathrm{média}(x)^2)$. O planner soma $\beta\cdot x$ em cima de $\overline{B}$ = KPI médio. A curva diz que desligar toda a mídia ainda dá o KPI médio histórico, que o gasto de hoje dá mais do que jamais se observou em média, e toda razão incremental (iCPA, iROAS, saturação, limite estratégico) usa uma inclinação muito enviesada. O código está no `run_mmm_engine`, mas o `simulate_kpi` (linha 668) e a curva herdam direto.
- Evidência: `make_identifiable_dataset` dos testes (KPI verdadeiro com gasto zero = 5000): KPI médio observado 6507,7; `organic_baseline_mean` 6507,7; KPI do motor em gasto zero 6507,7 e no gasto atual 6561,9; participação da mídia 0,81% contra ~23,17% verdadeiros. iCPA do motor logo acima do atual = 30,1, contra marginal verdadeiro de 0,392 KPI/R$ no mix histórico, ou seja, iCPA verdadeiro ≈ 2,55. Monte Carlo só do estágio 2 (200 repetições): ajustado/verdadeiro médio 0,298 contra $\mathrm{var}/(\mathrm{var} + \mathrm{média}^2)$ previsto 0,311. O verificador, via `pipeline.compute` no mesmo dataset: marginal do motor para STRONG na média 0,060 KPI/R$ contra ~0,71 verdadeiro, iCPA ~12× inflado.
- Correção sugerida: ajustar baseline e mídia juntos (uma regressão com calendário, contexto e features Hill, coeficientes de mídia $\ge 0$, intercepto livre), ou pelo menos dar intercepto ao estágio 2 e tirar o nível da curva de intercepto + média do calendário, não da média da previsão do estágio 1.
- Ver também: MMM-F1, MMM-F2.

**F3 (planner) — O limite estratégico cai no maior orçamento simulado quando nenhum ponto atinge as metas financeiras** — alta — `engine/elasticity_analysis.py:935` — confirmado — chega ao results.json
- Afirmação: quando os filtros de CPA/iCPA/ROAS/iROAS rejeitam todo ponto acima do gasto de hoje, o `strategic_limit_point` vira a linha mais perto de `investment_limit_factor` (o maior orçamento da grade). Uma meta inatingível vira recomendação de gastar o máximo. O cenário chega ao results.json (`scenarios[strategic_limit]`, com rampa) e às narrativas. No modo CONVERSIONS os filtros de ROAS/iROAS também rodam sobre `Projected_Revenue = KPI·conv·average_ticket`, e o `to_legacy_dict` põe `average_ticket` = 0 quando não definido, então qualquer `target_roas` nesse modo rejeita todo ponto e dispara o mesmo fallback. A API de cenário (`scenario.py`) devolve `recommended=None` nesse caso, e as duas discordam.
- Evidência: CONVERSIONS com `target_icpa=0.01` (inatingível): menor iCPA acima do atual 0,144; `strategic_limit=919.0` = máximo da grade (atual 306,3). O verificador reproduziu com `target_icpa=1e-6` (918,96 = máximo da grade) e com `target_roas=0.5` em CONVERSIONS (receita 0 em todo ponto, o filtro roda por causa de `if revenue_mode or min_roas > 0`, cai no máximo da grade).
- Correção sugerida: com `valid_points_df` vazio, não publicar limite estratégico, ou publicar o gasto de hoje com um motivo (`targets_unreachable`). Aplicar os filtros de ROAS só no modo receita, como o `analysis.run_opportunity_projection` já faz.

**F4 (planner) — KPI incremental, iCPA e iROAS da curva misturam o ganho da realocação com o efeito do orçamento extra** — média — `engine/elasticity_analysis.py:805` — confirmado — chega ao results.json
- Afirmação: $\text{Incremental\_KPI}_i = \mathrm{KPI}(X_i, \text{mix estratégico}_i) - \mathrm{KPI}(X_0, \text{mix histórico})$. Quando a realocação é confiável, as primeiras linhas acima do gasto de hoje creditam todo o ganho da reorganização a um investimento extra mínimo: o iCPA vai a quase 0 e o iROAS explode. A API de cenário repassa isso (icpa/iroas do `_curve_row` e o $\Delta K$ do `_table_row` contra o atual no mix histórico). Os filtros `target_icpa`/`min_iroas` e o ponto recomendado parecem muito mais eficientes do que o aumento de orçamento é de verdade.
- Evidência: MMM de 2 canais confiável: primeiro ponto acima do atual `inc_inv=9.28 inc_kpi=438.54 iCPA=0.021` contra o mesmo ponto no mix histórico `inc_kpi=64.32 iCPA=0.144` (7× subestimado). O verificador, em modo receita: KPI incremental 27,2 contra 1,37 no mix histórico, iCPA 0,34 contra 6,77 (~20×), iROI 2,93 contra 0,15.
- Correção sugerida: medir os incrementos da curva contra $\mathrm{KPI}(X_0, \text{mesmo mix estratégico})$, o valor da própria curva no orçamento de hoje, e publicar o ganho da realocação separado (ele já tem cenário próprio).

**F5 (planner) — A "Máxima Eficiência" do modo receita é sempre o primeiro ponto da grade acima do gasto de hoje** — média — `engine/elasticity_analysis.py:837` — confirmado — chega ao results.json
- Afirmação: $\text{Incremental\_ROI}_i = (\text{Rev}(X_i) - \text{Rev}(X_0))/(X_i - X_0)$ é a inclinação média a partir de $X_0$. Numa curva côncava ($k\le1$ garante), a inclinação média não cresce em $X_i$, então o argmax é o menor $X_i > X_0$, ~$X_0(1 + L/99)$. O cenário não diz nada além de "gaste 1,5–3% a mais". O modo conversões usa a regra do joelho, então os dois modos respondem perguntas diferentes sob o mesmo rótulo.
- Evidência: $f$ côncava implica $(f(x) - f(c))/(x - c)$ não crescente em $x$. Com `trust=False`: atual 306,3, primeiro ponto acima 315,6, `max_efficiency=315.6`. O verificador achou um caso ainda mais degenerado com `trust=True`: a linha atual tem investimento incremental 0 e ganho de realocação positivo, então $\text{Incremental\_ROI} = +\infty$, o `fillna` não mexe em inf e o `idxmax` escolhe o gasto de hoje (306,3).
- Correção sugerida: usar a mesma regra de joelho/saturação nos dois modos, ou definir máxima eficiência como o maior $X$ em que o iROAS marginal ($d\text{Rev}/dX$) ainda é $\ge 1$ (ou $\ge$ target_iroas).

**F6 (planner) — Os tetos de participação podem deixar parte do orçamento sem alocar, enquanto o orçamento inteiro é publicado como investimento** — média — `engine/elasticity_analysis.py:580` — confirmado — chega ao results.json
- Afirmação: `cap_channel_share_per_channel` (e `cap_channel_mix_share`) param de redistribuir quando todo canal bateu no teto e descartam o excesso. Com 2 canais e o `max_channel_mix_share=0.4` do padrão, o mix estratégico soma 80%. Em orçamentos altos os tetos absolutos $3\max_{\text{hist},c}/X$ prendem todos os canais e a soma também fica abaixo de 1. O KPI é simulado no gasto menor, mas `Daily_Investment`, CPA, iCPA e iROAS cobram o orçamento inteiro, e o `mix.strategic` do results.json não fecha com o investimento.
- Evidência: 2 canais, padrão 0,4: gasto estratégico / investimento min = max = 0,800. 5 canais, tetos do padrão, limite 5×: min 0,785 no investimento 3813. O verificador obteve 0,800 em todo ponto positivo e, no orçamento de hoje, KPI estratégico (1933,6) abaixo do KPI no mix histórico (1951,9).
- Correção sugerida: quando a soma dos tetos for $< 1$, relaxar o teto de participação para $1/n_{\text{canais}}$ ou mais, ou cortar a curva onde os tetos absolutos por canal não absorvem o orçamento e marcar essas linhas como fora do intervalo modelado; nunca descartar o excesso em silêncio.

**F7 (planner) — A curva continua realocando quando a identificabilidade suprime a realocação** — média — `engine/pipeline.py:290` — confirmado — chega ao results.json
- Afirmação: o `compute()` monta a curva agregada em `run_elasticity` antes de rodar o `identifiability.assess`. O `generate_aggregated_response_curve` decide o mix só pelo `cv_r2` (`trust_reallocation`). O results.json então publica `metrics.reallocation_suppressed=true` e tira o cenário `strategic_reallocation`, mas `response_curve`, `strategic_limit`, `max_efficiency` e suas rampas continuam vindo de um mix do otimizador que pode mover orçamento para dentro ou para fora de canais não identificáveis (juntados em "Não identificados").
- Evidência: `pipeline.compute` chama `run_elasticity` (linha 290) e só depois `identifiability.assess` (linha ~294); `elasticity_analysis.py:700` só olha `trust_reallocation`; `Computed.reallocation_suppressed` (`pipeline.py:68`) faz OR com a identificabilidade, mas nada volta para a curva. Não foi rodado numericamente (no sintético do verificador o `cv_r2` foi 0,076 e o mix histórico foi usado); o `fold_mix` só renomeia o gasto escondido.
- Correção sugerida: rodar a identificabilidade antes da curva e passar `reallocation_suppressed` para o `generate_aggregated_response_curve`, usando o mix histórico sempre que a flag estiver ligada.

**F8 (planner) — O mix do "Pico de Eficiência" favorece semanas de gasto baixo e desalinha a janela** — baixa — `engine/analysis.py:1078` — confirmado — chega ao results.json
- Afirmação: eficiência = KPI total de 4 semanas (com orgânico) / gasto de 4 semanas. Como o nível orgânico domina o numerador, o decil do topo são só as semanas de menor gasto, não as de mix mais eficiente. O mix ainda é tirado da semana $t$ sozinha, enquanto a razão cobre $t-3..t$. Esse mix alimenta `mix.optimized` e o KPI do cenário `max_efficiency`.
- Evidência: derivação: $\mathrm{KPI} = B + g(\text{spend})$ com $B \gg g$ implica $\mathrm{KPI}/\text{spend} \approx B/\text{spend}$, decrescente no gasto. Não rodado numericamente. É heurística, então o impacto é baixo.
- Correção sugerida: ordenar as semanas por KPI incremental (KPI − previsão do baseline) por gasto e calcular o mix na mesma janela de 4 semanas da razão, ou trocar a heurística pelo ótimo do próprio modelo.

**F9 (planner) — O fator mensal usa 30 dias** — baixa — `engine/scenario.py:10` — confirmado — não chega ao results.json (só à API de cenário)
- Afirmação: $\text{fator} = 30/\text{period\_days}$ subestima investimento e KPI mensais em 1,4% contra o mês médio (30,44 dias). As razões não mudam.
- Evidência: $30/30.4375 = 0.9856$. Convenção de rótulo, cosmética.
- Correção sugerida: usar $365.25/12$, ou rotular a unidade como "30 dias".
- Ver também: PRE-8.

---

## 5. Gates

### Fórmulas

1. **Gate de par por Pearson (`collinearity_r`)** — `engine/validation.py:130` — correta
   `wide` = pivot(Date × canal, gasto).fillna(0), colunas constantes removidas; par $(a, b)$ marcado sse $\lvert\mathrm{corr}(\text{wide}_a, \text{wide}_b)\rvert > \text{collinearity\_r}$ (0,85); só com $\ge 2$ canais e $\ge 30$ períodos.
   Premissas: gasto cru na cadência do arquivo, antes de adstock/Hill; canal sem linha numa data conta como gasto 0; sob independência, $\lvert r\rvert > 0.85$ com $n \ge 30$ é praticamente impossível, então o gate mede flighting/tendência em comum.

2. **VIF por canal** — `engine/validation.py:107` — correta
   $\mathrm{VIF}_i = 1/(1 - R^2_i)$, com $R^2_i$ da OLS de $x_i$ em $[1, x_{-i}]$ (`variance_inflation_factor` do statsmodels com coluna de constante explícita); `None` quando não finito, $\le 0$ ou $> 10^6$.
   Premissas: VIF no gasto cru; o MMM regride no gasto com adstock + Hill (o MinMax é afim e não importa, mas adstock e Hill importam), então o VIF é um proxy da colinearidade da matriz do modelo.

3. **Gate de VIF (`vif_max`) sem os gêmeos de overlap** — `engine/validation.py:152` — questionável
   Marca $i$ sse $\mathrm{VIF}_i$ é `None` ou $> \text{vif\_max}$ (10), com o VIF calculado depois de tirar $\max(\text{par})$ (o nome lexicograficamente maior) de cada par de overlap.
   Premissas: o par de overlap é tratado como uma fonte reportada duas vezes.

4. **Regra de overlap DV360/CM360** — `engine/validation.py:205` — questionável
   Par sobreposto sse $\mathrm{corr}(a, b) > 0.95$ e $\min(S_a, S_b)/\max(S_a, S_b) \ge 0.9$, com $S$ o gasto total do período.
   Premissas: correlação alta + totais parecidos indicam reporte duplicado; a regra não distingue isso de dois canais distintos com o mesmo flighting e orçamentos parecidos.

5. **Gate de gasto agrupado (`collinearity_unresolved`)** — `engine/validation.py:259` — questionável
   unresolved = canais em qualquer par fora do overlap com $\lvert r\rvert > 0.85$ ou $\mathrm{VIF} > 10$ no gasto depois de somar os `channel_groups`; erro, a menos de `block_per_channel`.
   Premissas: as mesmas dos gates de par e de VIF; pares de overlap isentos.

6. **Grupos sugeridos** — `engine/validation.py:161` — correta
   Componentes conexas do grafo de $\lvert r\rvert$; canal marcado só por VIF é ligado a $\arg\max_j \lvert\mathrm{corr}(i, j)\rvert$ (sem os gêmeos).
   Premissas: heurística.

7. **Datas faltantes** — `engine/validation.py:56` — questionável
   Para datas únicas consecutivas $d_k < d_{k+1}$: $\text{steps} = \mathrm{round}((d_{k+1} - d_k).\text{days}/\text{period\_days})$; faltantes $= d_k + \text{period\_days}\cdot j$, $j = 1..\text{steps}-1$; união sobre investimento e KPI com a cadência do investimento.
   Premissas: períodos de tamanho fixo; no mensal (30) as datas listadas são $d_k$ + 30 dias, não inícios de mês; buracos por canal são preenchidos com zero em outro lugar e não contam.

8. **Outliers (cercas de IQR)** — `engine/data_preprocessor.py:17` — questionável
   $Q_1, Q_3$ = quantis 0,25/0,75 da série inteira do KPI (interpolação linear do pandas); outlier sse $\text{kpi} < Q_1 - 1.5\,\mathrm{IQR}$ ou $\text{kpi} > Q_3 + 1.5\,\mathrm{IQR}$.
   Premissas: distribuição marginal incondicional: ignora tendência e sazonalidade, então não pega anomalias em série com tendência e marca as pontas de uma tendência forte; só nível info.

9. **Coeficiente de variação do gasto (`spend_cv_min`)** — `engine/sufficiency.py:13` — questionável
   $\mathrm{CV}_c = \mathrm{std}_{\text{ddof}=0}(s_{c,t})/\mathrm{média}(s_{c,t})$ em todos os períodos de `prepared.spend_df` (pivot por média, fillna 0), 0 se a média $\le 0$; `low_spend_variation` sse **algum** canal de **algum** evento validado tem $\mathrm{CV} < 0.10$.
   Premissas: depende da cadência (agregar encolhe o CV do ruído de pacing por ~$\sqrt{\text{fator de agregação}}$); conta ruído de pacing e tendência como "variação"; um canal com CV baixo rebaixa todo evento do run.

10. **WMAPE fora da amostra (`oos_wmape_max`)** — `engine/analysis.py:329` — questionável
    Por evento: ajusta o espaço de estados em $\text{pré}[:n - \mathrm{round}(n\cdot\text{HOLDOUT\_FRACTION})]$, prevê o holdout em vários passos com sua exógena; $\mathrm{WMAPE} = \sum\lvert y - \hat y\rvert/\sum\lvert y\rvert$; no run, `pre_wmape` = mediana entre os eventos validados com valor; `high_oos_wmape` sse `pre_wmape` $> 0.30$.
    Premissas: erro absoluto relativo à escala: mistura o erro do modelo com a razão ruído/nível irredutível do KPI, sem comparação com uma previsão ingênua.

11. **Coeficientes do bootstrap** — `engine/elasticity_analysis.py:270` — questionável
    $B = 200$ reamostras iid de linhas (com reposição) de $(X_{\text{escalado}}, y_{\text{lift}})$; cada uma ajusta `Ridge(alpha=1, positive=True, fit_intercept=False)`: $\min \lVert y - Xb\rVert^2 + \lVert b\rVert^2$, $b \ge 0$; estimativa pontual = média dos 200 vetores.
    Premissas: linhas permutáveis (sem autocorrelação); hiperparâmetros de adstock/Hill e baseline do estágio 1 fixos nos valores da amostra inteira (bootstrap condicional).

12. **Veredito de identificabilidade** — `engine/identifiability.py:8` — questionável
    $\text{contrib}_{b,i} = \text{coef}_{b,i}\sum_t X_{\text{escalado}}[t, i]$; $\text{ponto}_i = \mathrm{média}_b(\text{coef}_{b,i})\sum_t X_{\text{escalado}}[t, i]$; $(lo, hi)$ = percentis 2,5/97,5 de $\text{contrib}_{b,i}$; não identificável sse $lo \le 0$ (`coef_ci_includes_zero`) ou $hi - lo >$ ponto (`coef_ci_too_wide`) ou $i \in$ `validation.collinearity.unresolved`.
    Premissas: bootstrap por percentil válido (ver bootstrap); com bootstrap normal, "too wide" exige $\mu/\sigma > 3.92$ e "includes zero" exige $> 1.96$, então o primeiro motivo é implicado pelo segundo no caso suave.

13. **`fold_mix`** — `engine/identifiability.py:44` — correta
    Mix sem os canais escondidos; $\text{UNIDENTIFIED} = \sum$ dos valores escondidos (`None` se algum for `None`).
    Premissas: participações somam.

### Achados

**G1 — A regra de overlap isenta do gate de colinearidade justamente os pares mais colineares, e de forma não monotônica no orçamento** — média — `engine/validation.py:214` — confirmado — chega ao results.json
- Afirmação: um par com $r > 0.95$ e razão de gasto total $\ge 0.9$ conta como duplicata DV360/CM360. Isso só dá warning. O par sai do gate de $\lvert r\rvert$ (`_not_overlap`) e do gate de VIF (`_without_twins`), então o validate devolve `ok=True` com `unresolved=[]`, e o A5 nunca acrescenta o motivo `collinearity` para eles. Dois canais distintos com o mesmo flighting e orçamentos parecidos são exatamente o caso mais difícil de identificar, e passam no gate. Corte um orçamento pela metade com o mesmo $r$ e o run é bloqueado. O veredito depende da razão dos totais, que não tem nada a ver com colinearidade, e os pares mais fortes ($r > 0.95$) são os que passam.
- Evidência: sintético, 120 dias, `engine.validate`: quase gêmeos `r=0.9597 ok=True unresolved=[]`, só `dv360_cm360_overlap` (warning), VIF A 12,90 / B 12,86; mesmo par com orçamento pela metade (razão 0,5): `ok=False unresolved=[A, B]`, `collinearity_unresolved` (erro). Em 40 datasets assim o A5 publica os dois gêmeos individualmente (A e B identificáveis em 100%). O verificador reproduziu e confirmou que `pipeline.py:294` passa só `collinearity.unresolved` ao `identifiability.assess`. A isenção é proposital para fontes duplicadas, mas nada obriga o analista a tirar um dos gêmeos.
- Correção sugerida: manter os pares de overlap em `unresolved`, ou tornar `dv360_cm360_overlap` erro até o analista tirar um gêmeo ou confirmar que são distintos. No mínimo, passar os gêmeos ao `identifiability.assess` como colineares.

**G2 — O bootstrap iid por linha do A5 ignora autocorrelação: canais com efeito zero saem "identificáveis" em 8–18% das vezes** — média — `engine/elasticity_analysis.py:288` — confirmado — chega ao results.json
- Afirmação: o IC da identificabilidade reamostra linhas de série temporal iid e condiciona nos parâmetros de adstock/Hill ajustados na amostra inteira. Com gasto e resíduos autocorrelacionados (normal em dado de mídia diário ou semanal), a dispersão do bootstrap subestima a variância amostral, e um canal sem efeito passa em $lo > 0$ e largura $<$ ponto bem mais que o nível nominal. Com dado iid a mesma regra dá 0%. O condicionamento em Hill/adstock não foi simulado e só aumentaria o otimismo.
- Evidência: Ridge positivo sem intercepto via NNLS (conferido igual ao sklearn) + o `identifiability.assess` do motor, 400 repetições, canal X2 com efeito verdadeiro 0: $n=104$, $\rho$ 0/0 → 0,000; $n=104$, $\rho$ 0,8/0,8 → 0,080; $n=365$, $\rho$ 0,9/0,8 → 0,115; $n=365$, $\rho$ 0,95/0,9 → 0,175. O verificador, com o `bootstrap_coefficients` do próprio motor ($n=200$, 150 repetições): iid 0,7%, $\rho=0.9$ 16%.
- Correção sugerida: bootstrap em blocos móveis (ou estacionário) com bloco de ~$n^{1/3}$ ou tirado da ACF dos resíduos; idealmente reajustar ou perturbar os parâmetros de Hill/adstock dentro do bootstrap. Calibrar a taxa de falsa identificação da regra em simulações nulas como parte do A10.
- Ver também: MMM-F3.

**G3 — O `high_oos_wmape` mede a razão ruído/nível do KPI, não o erro do modelo: KPI de volume baixo reprova até com modelo perfeito** — média — `engine/sufficiency.py:42` — confirmado — chega ao results.json
- Afirmação: $\mathrm{WMAPE} = \sum\lvert y - \hat y\rvert/\sum\lvert y\rvert$ com teto absoluto fixo de 0,30 e sem comparação com previsão ingênua. Para um KPI de contagem com média $\lambda$ por período, até a previsão pela média verdadeira tem $\mathrm{WMAPE} \approx \sqrt{2/(\pi\lambda)}$. Todo run com KPI médio de ~8 ou menos por período é rebaixado a `insufficient_run`, qualquer que seja a qualidade do modelo. Um KPI de nível alto e pouco ruído passa mesmo com previsão muito enviesada. O texto do motivo diz que o modelo prevê mal, mas o gate é sobretudo uma propriedade do KPI.
- Evidência: holdout de 30 períodos, previsão = média Poisson verdadeira: média 3 → WMAPE mediano 0,447, P(>0,30) 0,99; 5 → 0,350, 0,83; 8 → 0,279, 0,30; 10 → 0,249, 0,09; 20 → 0,176, 0,00. KPI normal nível 1000, DP 50, previsão +15% enviesada: mediana 0,150 (passa). O verificador reproduziu e notou que $\sqrt{2/(\pi\lambda)}$ chega a 0,30 perto de $\lambda \approx 7$.
- Correção sugerida: comparar com um baseline ingênuo: WMAPE relativo, MASE ou skill $= 1 - \mathrm{WMAPE}_{\text{modelo}}/\mathrm{WMAPE}_{\text{ingênuo}}$ (ingênuo sazonal ou média do pré). Ou escalar o teto pelo ruído do próprio KPI, por exemplo com o piso Poisson $\sqrt{2/(\pi\cdot\text{média})}$.

**G4 — O `spend_cv_min` depende da cadência e conta ruído de pacing como variação de orçamento** — baixa — `engine/sufficiency.py:20` — confirmado — chega ao results.json
- Afirmação: CV = std/média do gasto por período no intervalo inteiro, com um limiar fixo de 0,10. O mesmo orçamento plano com só ruído aleatório de pacing passa no diário e reprova no mensal. Pacing por dia da semana ou tendência também contam como "variação", então o check não mede a variação deliberada de orçamento de que um lift precisa. E um canal com CV baixo em qualquer evento validado rebaixa todo evento do run (`any()`).
- Evidência: orçamento plano de 1000/dia com 25% de ruído iid de pacing, `engine.sufficiency.spend_cv`: diário 0,246, semanal 0,107, mensal 0,072 (gate 0,10). Agregar encolhe o CV do ruído por ~$1/\sqrt{\text{dias por período}}$. Severidade baixa porque o efeito é um rebaixamento conservador, não um número errado.
- Correção sugerida: medir a variação numa cadência comum (por exemplo somas semanais) ou no gasto livre de um ajuste de dia da semana/tendência, ou escalar o limiar por `period_days`. Julgar cada evento pelos próprios canais em vez de `any()` no run.

**G5 — `coef_ci_too_wide` torna `coef_ci_includes_zero` redundante e é um teste z ≥ 3,92** — baixa — `engine/identifiability.py:23` — confirmado — chega ao results.json
- Afirmação: com bootstrap aproximadamente normal, $hi - lo >$ ponto vale sse $\mu/\sigma < 2\cdot1.96 = 3.92$, enquanto $lo \le 0$ vale sse $\mu/\sigma < 1.96$. Todo canal que reprova no teste do zero reprova também no de largura, e a régua efetiva da identificabilidade é $\lvert t\rvert > 3.9$, bem mais rígida que um IC de 95% que exclui o zero. Não está errado, mas a lista de motivos e a documentação parecem dois critérios independentes, e a rigidez real não é dita.
- Evidência: largura $= 2\cdot1.96\,\sigma > \mu$ sse $\mu/\sigma < 3.92$. Nas simulações do G2, o canal com sinal real só é identificável em 21–43% das vezes. O verificador mostrou que a redundância vale mesmo sem normalidade: ponto = média do bootstrap e o percentil 97,5 fica acima da média na prática, então $lo \le 0$ implica $hi - lo \ge hi \ge$ ponto.
- Correção sugerida: documentar o limiar z equivalente, ou definir a regra de largura por uma precisão relativa alvo (por exemplo meia-largura/ponto $\le 0.5$, que volta a $z \ge 1.96$) quando o A10 calibrar.

**G6 — O check de outliers por IQR ignora tendência e sazonalidade; datas faltantes mensais são listadas em datas erradas** — baixa — `engine/validation.py:82` — confirmado — chega ao results.json (só o texto do relatório de validação)
- Afirmação: o `check_outliers` usa cercas na distribuição incondicional do KPI, então um pico de 60% numa série com tendência não é marcado. O `_gaps` anda de `period_days` em `period_days`, então um fevereiro faltante num arquivo mensal aparece como 31/01/2025, e um maio faltante como 01/05/2025 só por coincidência. Os dois checks são info/warning, então o impacto é no que o analista lê no relatório.
- Evidência: `monthly gaps listed: [2025-01-31, 2025-05-01]` para fevereiro e maio faltantes; tendência + ruído gaussiano, sem anomalia: `[]`; a mesma série com pico de 60% no dia 200: `[]`. De 01/jan a 01/mar são 59 dias, $\mathrm{round}(59/30) = 2$.
- Correção sugerida: aplicar as cercas de IQR nos resíduos de um ajuste de tendência + dia da semana (ou de uma mediana móvel). No mensal, gerar as datas faltantes com `pd.DateOffset(months=k)` a partir da âncora observada.

---

## 6. Experiment designer

### Fórmulas

1. **Regressão de ruído com tendência (+ dia da semana)** — `engine/experiment.py:22` — correta
   Diário: $y_t = b_0 + b_1 t + \sum_{d=1}^{6} g_d\,\mathbb{1}[\text{dow}_t = d] + e_t$; outros: $y_t = b_0 + b_1 t + e_t$; $t$ = índice da linha $0..n-1$; $\beta$ por OLS via `lstsq`.
   Premissas: linhas da janela igualmente espaçadas ($t$ é o índice, não a data); tendência linear; segunda é a base do dia da semana; o efeito da mídia fica dentro de $e_t$.

2. **σ dos resíduos** — `engine/experiment.py:31` — correta
   $\sigma = \sqrt{e^\top e/(n - p)}$, $p = 2$ (não diário) ou 8 (diário).
   Premissas: DP marginal dos resíduos com correção de graus de liberdade; o KPI pode já ter passado pelo corte de IQR se `treat_outliers` estiver ligado.

3. **ρ do AR(1)** — `engine/experiment.py:32` — questionável
   $\hat\rho = \mathrm{corr}(e_{2..n}, e_{1..n-1})$ (Pearson, recentrado), depois $\rho = \mathrm{clip}(\hat\rho, 0, 0.95)$; 0 se $\sigma = 0$ ou não finito.
   Premissas: autocorrelação residual AR(1); a correlação amostral de defasagem 1 dos resíduos de OLS tem viés para baixo de cerca de $-(1+3\rho)/n$ mais um termo da remoção da tendência, sem correção.

4. **Tamanho da janela** — `engine/experiment.py:61` — correta
   $n_w = \max(30,\ \lceil 90/\text{period\_days}\rceil)$ últimas linhas: diário 90, semanal 30 (210 dias), mensal 30 (~900 dias).
   Premissas: cadência do KPI = cadência do gasto (garantido antes pelo `cadence_check`).

5. **Nível de referência** — `engine/experiment.py:62` — correta
   $\overline{y} = \frac{1}{n_w}\sum y_t$ na janela.
   Premissas: o lift alvo é relativo à média da janela, não ao nível da tendência no fim da janela.

6. **Inflação de variância do AR(1)** — `engine/experiment.py:69` — questionável
   $f = \dfrac{1+\rho}{1-\rho}$
   Premissas: fator assintótico da variância de longo prazo, $\mathrm{Var}(\sum_{1..T} e) \approx \sigma^2 f T$; o fator exato para $T$ finito é $1 + 2\sum_{k=1}^{T-1}(1 - k/T)\rho^k$, menor que $f$ para $T$ pequeno.

7. **Duração** — `engine/experiment.py:70` — questionável
   $T = \max\left(1,\ \left\lceil \left(\dfrac{Z\,\sigma\sqrt f}{\text{lift}\cdot\overline{y}}\right)^2 \right\rceil\right)$, $Z = 1.96 + 0.84 = 2.80$.
   Premissas: inverte $\text{mde\_rel}(T) = \text{lift}$; teste z de uma amostra do KPI somado contra um contrafactual tratado como conhecido sem erro; bilateral a 5% ignorando a cauda oposta, poder 80% ($Z$ exato 2,8016).

8. **Teto** — `engine/experiment.py:71` — correta
   $\text{max\_periods} = \lfloor \text{max\_days}/\text{period\_days}\rfloor$; $T = \min(T, \text{max\_periods})$; $\text{feasible} = T_{\text{sem teto}} \le \text{max\_periods}$; $\text{max\_periods} < 1$ → `insufficient_history`/`duration_capped`.
   Premissas: período mensal tomado como 30 dias.

9. **MDE absoluto** — `engine/experiment.py:76` — questionável
   $\text{mde\_abs} = Z\,\sigma\sqrt{fT}$ (KPI somado no teste).
   Premissas: as mesmas da duração: só o ruído da soma do período de teste, sem a variância de estimar o contrafactual.

10. **MDE relativo** — `engine/experiment.py:106` — correta
    $\text{mde\_rel} = \text{mde\_abs}/(\overline{y}\,T) = Z\,\sigma\sqrt{f/T}/\overline{y}$ ($\le$ lift quando viável).
    Premissas: as mesmas acima.

11. **Gasto por período** — `engine/experiment.py:79` — correta
    $s_c = (\sum \text{investimento do canal } c \text{ nas datas da janela})/n_w$; canais com $s_c \le 0$ saem; ordenados crescente.
    Premissas: datas do `spend_df` alinhadas com as do KPI (mesma cadência); gasto cru, antes do adstock.

12. **Orçamento em risco** — `engine/experiment.py:82` — correta
    on_off: $\text{risk} = s_c\,T$; step_up: $\text{risk} = \text{step}\cdot s_c\,T$ (step = `max_budget_step`).
    Premissas: o mesmo $T$ para todo canal (o lift alvo é do KPI total, não da contribuição do canal; dito no texto de premissas).

13. **Condição de cálculo** — `engine/results.py:393` — correta
    `experiment_design` só é calculado quando o status do run é `inconclusive`; qualquer exceção → `None`.
    Premissas: —

### Achados

**EXP-1 — MDE e duração ignoram a variância do contrafactual, então o teste planejado tem falso positivo inflado e menos de 80% de poder** — média — `engine/experiment.py:70` — confirmado — chega ao results.json
- Afirmação: `duration_periods` e `mde_abs` vêm só de $\mathrm{Var}(\sum \text{KPI do teste}) = \sigma^2 f T$, isto é, um teste z de uma amostra contra um baseline conhecido sem erro. Numa leitura real de on/off ou step-up o baseline é estimado (média do pré, tendência extrapolada ou um braço de controle), o que soma variância: com a média de $n_w$ períodos do pré, $\mathrm{Var}(\sum y - T\bar y) \approx \sigma^2 f (T + T^2/n_w)$, e com $T \approx n_w$ isso dá ~2×; extrapolar tendência soma ainda mais (o erro da inclinação cresce como $T^3$). O resultado é uma duração curta demais e um MDE pequeno demais, apresentados como 95% de confiança / 80% de poder. O texto de premissas chama a estimativa de "conservadora", o que a simulação contradiz.
- Evidência: 1000 repetições, ruído AR(1) com σ 100, média 1000, lift 5%, `design()` no histórico, efeito = `mde_abs` somado ao futuro, $z = \sum(y - \text{cf})/(\sigma\sqrt{fT})$. Nominal: tamanho 0,05, poder 0,80. Diário ρ 0,3: cf conhecido tamanho 0,070 / poder 0,789; cf média do pré 0,135 / 0,771; cf tendência 0,442 / 0,615. Diário ρ 0,6: conhecido 0,092 / 0,771; média do pré 0,219 / 0,707. Semanal ρ 0,5: conhecido 0,143 / 0,744; média do pré 0,267 / 0,722; tendência 0,596 / 0,578. O verificador (800 repetições, 200 períodos de histórico) obteve números do mesmo tamanho, inclusive semanal ρ 0 com $T \approx 33$ contra $n_w = 30$: tamanho 0,16, poder 0,72, consistente com o fator $1 + T/n_w \approx 2$. O "conservadora" do texto (linha 40) se refere à variância da mídia dentro de σ, não ao contrafactual. A fórmula está marcada como provisória, mas a saída é apresentada como 95%/80%.
- Correção sugerida: dizer qual é a leitura e dimensionar para ela: pré/pós contra a média da janela, $\mathrm{Var} = \sigma^2 f (T + T^2/n_w)$, resolvendo $T$ por iteração (sem forma fechada); contrafactual por tendência, somar a variância de predição da OLS da extrapolação somada; desenho com dois braços (geo/holdout), $2\sigma^2 f T$. No mínimo, tirar a palavra "conservadora" das premissas e dizer que o contrafactual é suposto conhecido.

**EXP-2 — O ρ de defasagem 1 dos resíduos de OLS tem viés para baixo na janela de 30 períodos e subestima f e a duração no semanal/mensal** — baixa — `engine/experiment.py:32` — confirmado — chega ao results.json
- Afirmação: $\hat\rho = \mathrm{corr}(e_t, e_{t-1})$ em resíduos sem tendência tem o viés clássico de amostra pequena para baixo (~$-(1+3\rho)/n$, pior depois de tirar a tendência). Com $n_w = 30$ (semanal e mensal), $\hat f$ sai 13–35% pequeno demais, e $T$ e `mde_abs` são subestimados na mesma proporção em $T$ (raiz no MDE). No diário ($n_w = 90$) o viés é pequeno ($\hat f/f$ 0,92–0,99).
- Evidência: 3000 repetições chamando `engine.experiment._noise`. $n=30$: ρ 0,3 → $\hat\rho$ médio 0,202, $\hat f/f$ mediano 0,797; ρ 0,5 → 0,358, 0,721; ρ 0,7 → 0,514, 0,579. $n=90$: ρ 0,5 → 0,469, 0,934. No Monte Carlo do EXP-1, semanal ρ 0,5 com cf conhecido: $\hat\rho$ 0,349, tamanho 0,143, poder 0,744. O verificador (2000 repetições) obteve 0,206 / 0,80 e 0,360 / 0,73 com $n=30$; em ρ 0 o piso em 0 mantém $\hat f/f$ mediano em 1,0. O efeito se sobrepõe ao EXP-1.
- Correção sugerida: corrigir o viés de ρ (por exemplo $\rho + (1+3\rho)/n$, depois clip), ou trocar o fator AR(1) por uma estimativa da variância de longo prazo dos resíduos (Newey-West / batch means), ou alongar a janela no semanal.

**EXP-3 — O fator assintótico do AR(1) superestima a variância de somas curtas (conservador no mensal e em T pequeno)** — baixa — `engine/experiment.py:69` — confirmado — chega ao results.json
- Afirmação: $f = (1+\rho)/(1-\rho)$ é o limite com $T \to \infty$. A variância exata da soma de $T$ períodos de um AR(1) estacionário é $\sigma^2 T\,[1 + 2\sum_{k<T}(1 - k/T)\rho^k]$, menor para $T$ pequeno. No mensal (no máximo 3 períodos com o teto de 90 dias do padrão) ou com ρ alto, `mde_abs` e o $T$ sem teto saem superestimados. Compensa em parte o EXP-2, mas sem controle.
- Evidência: exato/$f$ em $T=3$: 0,786 (ρ 0,3), 0,611 (ρ 0,5), 0,399 (ρ 0,7), 0,144 (ρ 0,9); em $T=10$: 0,934, 0,867, 0,733, 0,383; em $T=90$: $\ge 0.895$. O verificador recalculou os mesmos valores: no mensal `mde_abs` fica superestimado em até $1/\sqrt{0.4} \approx 1.6\times$ com ρ alto; os $T$ sem teto do diário e semanal ficaram entre 33 e 108 períodos, onde a diferença fica abaixo de ~10%.
- Correção sugerida: usar o fator exato para $T$ finito e resolver $T$ por iteração (com $T$ pequeno, um laço até `max_periods` basta).

---

## Achados refutados

Nenhum. Os 40 achados das seis áreas foram confirmados pelos verificadores, alguns com a severidade corrigida (causal-3 de alta para média, PRE-5 de média para baixa) ou com ressalvas registradas no próprio achado (MMM-F4, planner-F1 (b), planner-F7 e planner-F8 sem reprodução numérica).

## Resumo

| Área | Nº de fórmulas | Alta | Média | Baixa | Total confirmado |
| --- | ---: | ---: | ---: | ---: | ---: |
| Pré-processamento | 15 | 1 | 4 | 4 | 9 |
| Causal | 19 | 3 | 3 | 2 | 8 |
| MMM | 12 | 1 | 3 | 1 | 5 |
| Curva e planner | 22 | 3 | 4 | 2 | 9 |
| Gates | 13 | 0 | 3 | 3 | 6 |
| Experiment designer | 13 | 0 | 1 | 2 | 3 |
| **Total** | **94** | **8** | **18** | **14** | **40** |

Os achados de severidade alta, em ordem de pipeline: PRE-1 (leitura de números pt-BR), causal-1 (contrafactual absorve o lift), causal-2 (p-valor/IC anticonservadores), causal-4 (`cpa_incremental` com gasto total), MMM-F1 / planner-F2 (estágio 2 sem intercepto, mesma causa), planner-F1 (corte em 0 no mínimo histórico) e planner-F3 (limite estratégico cai no maior orçamento).
