# Marketing GEM — guia de onboarding para o Dev A (Trilha A, motor)

> **Atualização de 04/nov/2026:** o A0 foi implementado (branch `feat/a0-engine-package`): `engine/`, `llm/` e o snapshot de paridade existem. O que este guia descreve como "a fazer" no A0 e como "o falso da API" continua valendo para a API até o swap do Dev B. Decisões atuais: `docs/decisoes/engine.md` e `llm.md`.

Escrito em 03/nov/2026 para quem entra agora no projeto e vai assumir o **motor estatístico** (`engine/`). Este documento **não substitui** a spec: ele explica o projeto, os conceitos e o código, e aponta para a spec quando você precisar do texto canônico. Em qualquer divergência, vale a ordem: `docs/m2/README.md` > `docs/m2/trilha-a-motor.md` > este guia.

## Como ler este guia (e quanto confiar em cada parte)

Algumas afirmações vêm direto da spec e do código do repo; outras são conhecimento geral de estatística ou sugestão minha. Marquei assim:

- **[spec]** está escrito em `docs/m2/` ou nos arquivos de convenção.
- **[código]** eu conferi no código deste repo (`api/`, `tests/`).
- **[protótipo]** eu li no código do protótipo (`/home/rodrigo/Sistemas/Dash/opportunity-engine/scripts/`, 03/nov/2026). Os números de linha são desse commit.
- **[inferido]** ainda deduzido, não verificado. Depois da leitura do protótipo, quase nada ficou assim; se aparecer, está marcado no ponto.
- **[sugestão]** é proposta minha, não decisão do time.

> **Onde está o código do motor.** Ele **não está neste repo** (`opportunity-engine-v2` tem só `api/`, `web/`, `tests/` da plataforma; não há `engine/`, `scripts/`, `exemplo_csv/` nem `tests/fixtures/`). Ele está no repo do protótipo **Max Impact Engine**, em `/home/rodrigo/Sistemas/Dash/opportunity-engine/` (HEAD `6146b7f`; o `bbad5af` citado pela spec é o pai dos dois últimos commits, só de docs e `.gitignore`). **Li esse código em 03/nov** e confirmei os pontos que estavam como `[inferido]`; as referências `arquivo:linha` da spec batem. O original upstream é `rafahm-google/opportunity-engine`. Estado do protótipo: `uv run --with pytest pytest` → **209 testes passam** em ~16 s.
>
> **O que continua faltando:** a pasta `exemplo_csv/` (dados de exemplo que o snapshot de paridade do A0 e os fixtures do A1 usam) está no `.gitignore` do protótipo e **não existe no disco**. Os testes do protótipo usam dados sintéticos próprios e passam sem ela, mas a spec pressupõe esse dataset. Ver seção 9, pergunta 1.

Sumário:

1. O projeto em cinco minutos
2. Conceitos de marketing e estatística (o que o motor faz, em português claro)
3. Arquitetura e o caminho de um run, do clique ao resultado
4. Trilha B (plataforma): o que já existe e o que você precisa saber dela
5. Trilha A (motor): visão geral, estado real e princípios
6. O contrato A ↔ B em detalhe (a parte mais importante)
7. Os itens A0 a A10, um a um, com a parte técnica
8. Ordem de ataque sugerida, testes e convenções de código
9. Perguntas em aberto, riscos e primeiros passos
10. Glossário

---

## 1. O projeto em cinco minutos

**O que é.** O *Marketing GEM* é uma plataforma web multi-marca para analisar **quanto o investimento em mídia paga realmente gera de resultado**. É um projeto da Omnicom / AlmapBBDO, com entrega ao Google (o "M2", demo em **18/nov/2026**). O requisito do cliente está num documento chamado **BRD** (`[Omnicom - AlmapBBDO] BRD - Marketing GEM - 2026 v2.docx`), confidencial e **fora do git**. Peça uma cópia ao time: a spec cita seções do BRD ("BRD › Technical Details §3") e você vai querer lê-las.

**De onde veio.** Existe um protótipo em Streamlit (o *Max Impact Engine*, ~5 mil linhas de Python). O M2 transforma isso em produto:

- o **motor** estatístico do protótipo é reaproveitado, virando o pacote `engine/` (decisão do time: reescrever seria risco sem ganho, o código já foi auditado em julho);
- a interface Streamlit é **substituída** por React, porque o BRD exige o visual do *Almap Metrics* (produto React da Almap), controle de acesso por papel e execução assíncrona na nuvem.

**As duas análises que o motor faz** (explicadas na seção 2):

1. **Causal por evento**: "quando o investimento em um canal mudou bruscamente, quanto o resultado (KPI) mudou *por causa disso*?"
2. **Saturação / elasticidade**: "se eu aumentar o investimento num canal, quanto o resultado cresce, e a partir de que ponto deixa de compensar?" Com guardrails de CPA/ROAS (limites de custo e retorno).

**Quem faz o quê.**

| Quem | Faz | Pasta |
|---|---|---|
| **Dev A (você)** | motor, gates estatísticos, auditoria matemática | `engine/` (a criar) |
| **Dev B** | plataforma: auth, upload, jobs, telas, deploy | `api/`, `web/` |
| Claude | specs + implementação via subagentes, revisadas pelos devs | — |

**Princípio da Trilha A, em uma frase:** *o motor decide o que é publicável.* Se um resultado não passa num teste de qualidade (um "gate"), ele sai marcado como rejeitado, com o motivo. A camada de cima (API e telas) só esconde ou rotula; **nunca refaz o julgamento nem recalcula nada**. Um número sem rótulo nunca sai do motor.

**Princípio da Trilha B:** *multi-marca primeiro*. Todo dado é isolado por **workspace** (um workspace por marca/cliente). Isso importa para você só indiretamente: o motor é cego a workspaces, ele recebe arquivos e uma config e devolve um JSON.

**Calendário (da spec) e onde estamos hoje (03/nov, terça da semana 3):**

| Semana | Trilha A (previsto) |
|---|---|
| 1 · 19–23/out | A0 pacote `engine` · A1 `results.json` + fixtures |
| 2 · 26–30/out | A2 validação · A3 colinearidade · A4 controles causais |
| **3 · 2–6/nov (agora)** | A5 identificabilidade · A6 suficiência + placebo · A7 experiment designer · A8 guardrails/cenários · A9 grounding |
| 4 · 9–13/nov | A10 auditoria matemática |
| buffer · 16–18/nov | correções · **demo ao Google em 18/nov** |

O estado real, **[código]**: nada de A0 a A10 foi entregue (não existe `engine/`). A Trilha B foi adiantada e está quase toda pronta, e **o B5 (dashboards) está bloqueado esperando você**: ele precisa dos fixtures do A1 (previstos para 23/out) e do `engine.scenario` do A8. Ou seja, **você começa com a semana 1 e 2 em atraso**. Isso não é uma crítica a você: é o ponto de partida honesto, e a seção 8 propõe uma ordem de ataque que destrava o Dev B o quanto antes. Combine o escopo realista com o Dev B e a gestão logo no início; a spec já traz uma **ordem de corte** (seção 8.2) para quando o prazo aperta.

---

## 2. Conceitos de marketing e estatística

Esta seção existe para você não precisar ser especialista em mídia para trabalhar no motor. Se você é de estatística, passe pelos termos de marketing; se é de marketing, pelos estatísticos.

### 2.1 Vocabulário de mídia

- **Canal**: onde o dinheiro é investido. Nos exemplos da spec: `SEARCH`, `PMAX` (Performance Max, campanhas automatizadas do Google), `YOUTUBE`, `Demand Gen`, `DV360`/`CM360` (plataformas de mídia programática/medição do Google).
- **Investimento / spend**: quanto se gastou, por dia (ou semana) e canal.
- **KPI**: o resultado que a marca quer maximizar: conversões (compras, leads) ou receita.
- **Alvo de otimização (`optimization_target`)**: `CONVERSIONS` (maximizar contagem) ou `REVENUE` (maximizar receita; exige `average_ticket`, o ticket médio, para converter conversões em dinheiro).
- **CPA** (custo por aquisição) = investimento ÷ conversões. **ROAS** (retorno sobre gasto) = receita ÷ investimento. As versões **incrementais** (**iCPA**, **iROAS**) usam só o resultado *adicional causado* pelo investimento adicional, e por isso são bem mais honestas que as médias. O motor trabalha com metas (`target_cpa`, `target_icpa`, `target_roas`, `target_iroas`) que funcionam como **guardrails**: recomendações que violam a meta são podadas.
- **Cadência**: granularidade dos dados, diária ou semanal (`period_days` = 1 ou 7).
- **Workspace**: o espaço isolado de uma marca na plataforma.

### 2.2 A pergunta central: correlação não é causa

Marcas gastam mais em campanhas quando já esperam vender mais (Black Friday). Olhar "mais gasto, mais vendas" não prova que o gasto causou as vendas. O motor tenta responder "quanto vendeu *a mais do que venderia sem a mudança de investimento*" com dois métodos.

### 2.3 Análise causal por evento (o "Causal Impact")

1. **Detecção de evento** **[protótipo, `analysis.find_events`]**. Por canal, agrega o investimento por semana (`W-MON`; se os dados já são semanais, usa a data nativa), compara cada semana com a **média móvel das 12 semanas anteriores** (`rolling(12).mean().shift(1)`) e chama de evento quando `razão > 1 + increase%` ou `razão < 1 − decrease%`. Se mais de 25% dos períodos de um canal viram "evento", só avisa no log (o limiar está pegando oscilação normal). Eventos de canais diferentes **na mesma semana são fundidos** num evento só, cujo "canal" é a lista `"A, B"` e cuja variação é a de maior módulo. Canal com menos de 14 linhas ou 3 semanas é ignorado.
2. **Contrafactual** **[protótipo, `analysis.run_causal_impact_analysis`]**. O pré-período vai **do primeiro dia do histórico até o dia anterior ao evento**; o pós-período é `post_event_days` (default 14) a partir da data do evento. O modelo é `statsmodels.tsa.statespace.UnobservedComponents` com nível local + tendência + **sazonalidade 7** (`"llevel", trend=True, seasonal=7`) e regressores externos (`exog`). Ele é treinado no pré-período e prevê o pós-período; a projeção é o *contrafactual*. **Lift** = Σ(KPI real − previsto) no pós-período; o **erro-padrão acumulado** é `√Σ se_t²` (assume erros independentes), o IC é `lift ± 1,96·cum_se` e o p-valor vem de `z = lift/cum_se` normal. (O protótipo anterior usava teste-t sobre resíduos autocorrelacionados, o que superestimava a significância: achado F4, corrigido.)
3. **Regressores e controles** **[protótipo]**. A lista candidata é: o investimento de cada canal depois de **adstock + Hill** (os parâmetros α, k, s vêm de um modelo de resposta pré-treinado sobre o histórico inteiro, ver 2.4), calendário (`day_*`, fim de semana, período de pagamento, feriado BR), colunas de trends ("generic") e, se existirem no arquivo de performance, **`Leads`, `Clicks` e `Impressions`** (nomes fixos no código). Um filtro de variância e um **`LassoCV(cv=5)`** sobre os dados padronizados (MinMax) escolhem quais ficam. A regra de ouro do A4: *nunca* usar como controle algo que o próprio anúncio influencia (cliques, impressões, conversões da plataforma), senão o modelo "explica" o efeito e o lift desaparece (contaminação). O protótipo **faz exatamente isso hoje**.
4. **Qualidade do ajuste**: R² e erro (`mae`, `mape` = MAE/média×100, ou seja WMAPE) calculados **dentro da amostra** no pré-período.
5. **Gates no protótipo** **[protótipo, `local_main.py:229-275`]**: o evento passa se `p < p_value_threshold` (se `require_statistical_significance`), **e** a direção é lógica — investimento subiu e lift > 0, ou desceu e lift < 0 (`require_logical_direction`), **e** `R² ≥ r_squared_threshold` (`require_model_fit`). Os aprovados são ordenados por |lift| e só os `max_events_to_analyze` (default 5) primeiros viram relatório. Hoje os reprovados **somem** (só uma linha de log); no contrato novo eles ficam no `results.json` com `status: "rejected"` e `reasons`.

> **Duas observações minhas sobre esse modelo [sugestão, verificar na A10]:** (a) o `exog` do *forecast* usa o investimento **real** do pós-período, inclusive o do canal tratado; se o Lasso mantiver esse regressor, o modelo já "explica" parte do efeito do evento e o lift medido (a diferença para a previsão) fica subestimado. Não é obrigatório que isso aconteça (o Lasso pode descartá-lo), mas vale um teste sintético com efeito conhecido. O contrafactual correto seria prever o pós-período **mantendo o investimento do canal tratado no nível do pré-período**. (b) Os parâmetros α/k/s do modelo de resposta são ajustados com o **histórico inteiro, inclusive o pós-evento** que se quer avaliar, o que é um vazamento (*look-ahead*) leve para dentro do contrafactual. A auditoria de julho tratou o F8 (um α/k/s global aplicado a todos os canais) como "diferido" justamente porque esses canais entram "só como controle"; as duas observações acima não estão na auditoria.

### 2.4 Análise de saturação / elasticidade

Ideia: o retorno de cada real adicional **diminui**. O primeiro R$ 1 mil em um canal rende muito; o milionésimo, quase nada. O motor modela isso com duas transformações padrão em *Marketing Mix Modeling* (MMM), explicadas abaixo:

- **Adstock** (efeito residual): o efeito da propaganda de hoje se espalha pelos dias seguintes. A forma geométrica mais comum: `adstock_t = gasto_t + λ · adstock_{t-1}`, com 0 ≤ λ < 1 (λ alto = efeito longo).
- **Curva de Hill** (saturação): `resposta(x) = x^n / (K^n + x^n)`. `K` é o ponto de meia-saturação; `n` controla o quão abrupta é a curva. A resposta nunca passa de 1 (vezes o coeficiente do canal).

O **coeficiente** de cada canal, depois da transformação, diz quanto ele "pesa". A **elasticidade** é a sensibilidade do KPI a variações de investimento. As curvas resultantes (investimento → KPI esperado) permitem encontrar:

- o **ponto ótimo**: onde o iCPA/iROAS ainda cumpre a meta;
- o **ponto de saturação**: onde investir mais praticamente não traz KPI.

**Como o protótipo faz** **[protótipo, `elasticity_analysis.run_mmm_engine`]** — um modelo de **dois estágios**:

1. **Estágio 1 (baseline orgânico):** `Ridge(alpha=1)` do KPI contra calendário (`month_*`, fim de semana, pagamento, feriado) e trends. O baseline é o que se venderia "sem mídia".
2. **Estágio 2 (resposta de mídia):** o *lift* é o **resíduo assinado** `KPI − baseline` (antes se cortava em zero, o que fabricava ~16% de "efeito" mesmo em ruído branco: achado F1). Para cada canal ativo aplica-se **adstock** (convolução com pesos `α^i`, janela de 12 períodos; α é o *carryover*: maior α = efeito mais longo) e **Hill** `1/(1+(x/s)^−k)` (o mesmo que `x^k/(s^k+x^k)`). Um `Ridge(alpha=1, positive=True, fit_intercept=False)` sobre as features padronizadas dá os coeficientes (positivos: mídia não "tira" vendas).
3. **Parâmetros α, k, s por canal** são escolhidos com `scipy.optimize.minimize` (L-BFGS-B, 3 reinícios, seed 42) minimizando o **MSE de validação cruzada walk-forward** (`TimeSeriesSplit`, até 3 folds). Limites: α∈[0; 0,9], **k∈[0,1; 1,0]** (curva sempre côncava, sem retorno crescente), s entre 1% da média e o maior entre 3×máx e 2×média do gasto.
4. **Coeficientes finais por bootstrap:** 200 reamostragens **iid de linhas** (seed 42) e a **média** dos coeficientes. Só essa média é guardada; as 200 versões são descartadas (ver A5).
5. **Contribuição por canal** = Σ(coef × feature); `contribution_pct` normaliza para 100%. Métricas: `r_squared` (in-sample), `cv_r_squared` (walk-forward), `marketing_contribution_of_kpi_pct`. Se `cv_r² ≤ 0` ou a contribuição é < 5% do KPI, só **avisa** no log (`low_confidence`); a realocação de mix é suprimida quando `cv_r² < 0,1` (F15).

Depois disso, `generate_aggregated_response_curve` varre o investimento total e produz a curva de resposta e os pontos notáveis (atual, máxima eficiência, limite estratégico, derivado do `investment_limit_factor`, retorno decrescente, saturação, realocação estratégica), aplicando os guardrails de `financial_targets` e tetos de participação por canal (`max_channel_mix_share`, default 0,4). `generate_individual_response_curves` faz o mesmo por canal.

Há **um segundo modelo de resposta**, mais simples, em `analysis._train_response_model` / `run_opportunity_projection`: baseline OLS (`day_*`, pagamento, feriado, trends), α escolhido por correlação numa grade 0,1–0,9 (adstock `lfilter`, que é *outra* convenção) e Hill ajustado por `curve_fit` sobre a **soma** dos canais do evento. É dele que o modelo causal herda α/k/s (ver 2.3). São, portanto, **dois modelos de resposta com convenções diferentes** no mesmo motor (achado F10, diferido).

Os números `cv_r2`, `r2`, `media_contribution_pct`, `low_confidence` do contrato descrevem a qualidade do modelo de dois estágios.

**Bootstrap** (item A5/A8): para saber a *incerteza* dos coeficientes, o protótipo reamostra os dados 200 vezes (seed 42) e reajusta o modelo, obtendo 200 versões dos coeficientes. Os percentis dessa distribuição dão **intervalos de confiança** e **bandas** nas curvas. Hoje o protótipo calcula tudo isso e **joga fora tudo exceto a média** **[spec]**; boa parte do seu trabalho é *parar de jogar fora*.

### 2.5 Identificabilidade e colinearidade

Se dois canais sobem e descem sempre juntos (ex.: `PMAX` e `SEARCH`, r = 0,91), o modelo não consegue separar o efeito de um do outro: é como tentar descobrir o peso de duas pessoas sabendo só o peso de ambas juntas. Dizemos que os efeitos individuais não são **identificáveis**.

- **Correlação par a par** (r de Pearson) é a checagem óbvia.
- **VIF** (*Variance Inflation Factor*) generaliza: para cada canal, regride o gasto dele nos demais gastos; `VIF_j = 1 / (1 − R²_j)`. VIF > 10 é a regra prática de colinearidade severa.
- **Saídas** possíveis para o analista: *agrupar* os canais (somar o gasto, modelar o grupo como um canal) ou *seguir sem agrupar* (`block_per_channel`), aceitando que o resultado por canal sai `identifiable=false` e **não é publicado**.

### 2.6 Métricas de erro

- **WMAPE** = Σ|real − previsto| / Σ|real|. É o erro "em % do total", robusto a dias pequenos. O campo `mape` do protótipo é MAE/média × 100, o que equivale a WMAPE para valores positivos **[spec]**. O problema apontado: é medido **dentro da amostra** (in-sample), ou seja, o modelo foi ajustado nos mesmos dados em que é avaliado, o que o faz parecer melhor do que é. O A6 exige WMAPE **fora da amostra** (segurar os últimos 20% do pré-período).
- **R²**: fração da variância explicada. **CV R²**: R² em validação cruzada (por tempo, ver a seguir).
- **Validação cruzada temporal** (*walk-forward*, `TimeSeriesSplit`): em séries temporais nunca se embaralham as observações; treina-se no passado e testa-se no futuro, deslizando a janela.

### 2.7 Gates (portões de publicação)

Um **gate** é um teste de qualidade que um resultado precisa passar para ser publicado. A lista, **[spec]**:

| Gate | Pergunta | Item |
|---|---|---|
| Validação de dados | Os dados têm duplicatas, buracos, KPI de fonte única? | A2 |
| Colinearidade | Canais separáveis? | A3 |
| Controles limpos | Algum controle é contaminado pelo investimento? | A4 |
| Identificabilidade | O coeficiente do canal é distinguível de zero? | A5 |
| Suficiência | Há variação de gasto, eventos e ajuste fora da amostra suficientes? | A6 |
| Placebo | Uma "intervenção falsa" também gera efeito? Então o efeito real é suspeito | A6 |
| Guardrails financeiros | A recomendação respeita CPA/ROAS-alvo, extrapolação e passo máximo? | A8 |
| Grounding | O texto do Gemini só cita números e canais que existem? | A9 |

Efeitos do gate: `status` (`published|rejected`, `succeeded|inconclusive|failed`) e `reasons` (lista de motivos). A UI mostra os motivos.

### 2.8 Placebo, MDE e experimento

- **Teste placebo**: aplica o mesmo método a um momento em que *nada* aconteceu (meio do pré-período). Se o método "encontrar" um efeito significativo ali, ele está vendo ruído, e o efeito do evento real não é confiável.
- **Run inconclusivo**: quando os dados não sustentam nenhuma conclusão (pouca variação, ruído, ajuste ruim). É um **resultado válido**, não um erro. Nesse caso o motor propõe um **experimento** (A7): "para saber, faça um teste on/off de X dias com orçamento Y".
- **MDE** (*minimum detectable effect*): o menor efeito que um experimento consegue detectar com 95% de confiança e 80% de poder estatístico, dada a volatilidade dos dados.
- **Poder estatístico**: probabilidade de detectar um efeito que realmente existe.

### 2.9 Gemini, relatório e *grounding*

O motor gera relatórios em texto (narrativa por evento e um global). O **Gemini** (modelo de linguagem do Google) escreve a narrativa a partir de um resumo de números. Risco: LLMs inventam números. **Grounding** é a checagem *pós-geração*: todo número e todo nome de canal citado no texto tem que existir no payload enviado. Se falhar, regenera uma vez; se falhar de novo, bloqueia e a UI mostra um texto determinístico de `recommendations.py`. O Gemini é **opcional**: sem chave, o run termina com o relatório determinístico.

---

## 3. Arquitetura e o caminho de um run

```
web/ (React SPA) ──HTTP/SSE──▶ api/ (FastAPI; hospedagem: servidor próprio x86-64)
                                 │  auth, RBAC, upload, validação síncrona,
                                 │  sugestão Gemini, runs, histórico, cenários
                                 ├──▶ Postgres: users, workspaces, simulations, runs, run_logs
                                 ├──▶ Storage (disco local): inputs/, results.json
                                 └──dispara──▶ worker (processo separado, mesma imagem; no desenho original era um Cloud Run Job)
                                                  └─ engine.run(...) → results.json
(Conector BigQuery/Ads/GA4: existe no código da API, mas está FORA do escopo por ora; só entra dado por upload de CSV)
```

Tecnologias **[spec/código]**: Python 3.13 com `uv` (nunca pip/poetry), FastAPI, SQLAlchemy 2 + Alembic + psycopg 3, Postgres 16; front em Vite + React 19 + TypeScript + TanStack Router/Query com `bun`; testes `pytest` e Playwright; a spec original previa Cloud Run; **a decisão atual (04/nov) é hospedar num servidor próprio x86-64, sem GCP**, ainda com API e worker na **mesma imagem Docker**, comandos diferentes. O texto de `docs/m2/` e do `CLAUDE.md` sobre Cloud Run, GCS, Secret Manager e B11 ainda não reflete isso.

### O caminho de um run, passo a passo

Quem faz cada passo é fundamental para saber *onde seu código entra* (passos 4 e 6):

1. **Cadastro e upload** (API). O analista cria uma *simulação* (um rascunho no banco), sobe até 3 CSVs (`investimento`, `performance` e, opcional, `trends`; ≤ 30 MB) (a importação do Google/BigQuery existe na API mas está fora do escopo por ora). Os arquivos vão para o storage com o nome `ws/{workspace_id}/sim/{simulation_id}/inputs/{sha256}.csv` (endereçados por conteúdo).
2. **Mapeamento de colunas** (API + tela). O analista confirma qual coluna do CSV é a data, o canal, o investimento, o KPI. Isso fica em `config.column_mapping`.
3. **Validação síncrona** (API). Na confirmação do mapeamento, a API chama `validate(inputs, config)` e guarda o `ValidationReport` em `simulation.validation`. **← Seu código (A2/A3) vai aqui.** Hoje é um falso que só detecta `duplicate_date_channel`.
4. **Parâmetros** (API + tela). O analista edita o formulário gerado do JSON Schema do `EngineConfig` (com sugestões determinísticas dos dados e do Gemini). Salva no `config` da simulação.
5. **Rodar** (API). `POST …/runs` confere o *gate do servidor* (validação ok, avisos confirmados, parâmetros salvos, nenhum run ativo na simulação) e cria o `Run` com um **snapshot** de `config` e do sha256 dos inputs. Dispara o worker.
6. **Worker** (`api/worker.py`, **[código]**). Muda o run para `running`, resolve os caminhos dos inputs no storage, chama `engine_run.run(inputs, config, out_dir, on_log)` e, ao fim: escreve `results.json` no storage, grava `status`, `engine_version`, `results_uri` no run. **← Seu código (A0/A1) vai aqui.** Hoje é um motor falso.
7. **Log ao vivo** (SSE). Cada chamada de `on_log(level, message)` vira uma linha em `run_logs`; a tela acompanha em tempo real. Em caso de erro, a tela vê uma mensagem genérica e o traceback vai só para o log do servidor.
8. **Dashboards** (B5, bloqueado). Leem `results.json` pela API; filtros e sliders chamam `engine.scenario` (A8) via `GET /runs/{id}/scenario`.
9. **Histórico e publicação** (B6, pronto). Um analista revisa e *publica* o run; só então o viewer o enxerga.

---

## 4. Trilha B (plataforma): o que existe e o que importa para você

Estado resumido **[CLAUDE.md]**: concluídos B0 (esqueleto), B1 (auth/RBAC/telas), B2 (upload), B3 (parâmetros + Gemini), B4 (jobs, log, SSE), B6 (histórico), B8 (conectores Google, **fora do escopo por ora**), B9 (uso, logs, apagar). **Faltam**: B5 (dashboards, bloqueado por você), B7 (export, depende do B5), B10 (visual contínuo), B11 (deploy, **agora num servidor próprio x86-64, não no GCP**).

O que você precisa saber sem ser dono disso:

- **Papéis**: `viewer` (vê runs publicados, mexe em cenários), `analyst` (cria simulação, sobe arquivo, roda, publica), `admin` do workspace, `platform admin`. Recurso de outro workspace devolve **404, nunca 403**.
- **Tabelas relevantes** **[código, `api/models.py`]**: `simulations` (config jsonb, validation jsonb), `simulation_files`, `runs` (`status`, `config`, `inputs`, `engine_version`, `results_uri`, `summary`, `error`, `confirmed_warnings`, `published_at`…), `run_logs` (`run_id`, `ts`, `level`, `message`). O `Run.status` vai `queued → running → succeeded | inconclusive | failed`. Um índice único garante **um run ativo por simulação**.
- **O Gemini já é chamado pela API** (sugestão de parâmetros, `api/gemini.py`, SDK `google-genai`, modelo `gemini-flash-latest`) e **só vê agregados**, nunca linhas de dados. O seu A9 (relatórios) é outra chamada ao Gemini, dentro do motor, com as mesmas preocupações de confidencialidade.
- **Gemini no motor**: chave única da plataforma (`GEMINI_API_KEY` por variável de ambiente, sem Secret Manager). **O acesso ao LLM passa a ser um módulo plugável `llm/`** (criado no A0, só com o adaptador Gemini): o motor e a API chamam `get_llm()` e não o SDK do Google; trocar de provedor no futuro é escrever um adaptador. Ver o spec do A0, seção "Módulo LLM", nunca por usuário.
- **Como a API enxerga o motor hoje**: três módulos-ponte que o seu trabalho substitui:

| Arquivo da API | O que é hoje | Vira |
|---|---|---|
| `api/engine_config.py` | `ParamsIn`/`EngineConfig` provisórios (pydantic) | `from engine.config import EngineConfig` (A0) |
| `api/validation.py` | `validate` falso, só `duplicate_date_channel` | `from engine import validate` (A2) |
| `api/engine_run.py` | `run` falso: emite 6 linhas de log e devolve todas as seções `null` | `from engine import run` (A0/A1) |

- **Variáveis de motor falso** para testes **[código]**: `FAKE_ENGINE_STEP_SECONDS` (pausa entre etapas) e `FAKE_ENGINE_FAIL=1` (simula falha). O `tests/conftest.py` e o `tests/api/test_runs.py` dependem delas; quando trocar o motor, esses testes precisam de um substituto (ex.: um fake injetado no lugar do `engine.run`).
- Documentação do porquê de cada decisão da plataforma: `docs/decisoes/` (leia `runs-e-jobs.md` e `parametros-e-gemini.md` primeiro; são os que tocam você). Regras: `CODE-STYLE.md`, `API-GUIDE.md`, `DATABASE.md`, `SECURITY.md`.

---

## 5. Trilha A (motor): visão geral

### 5.1 Missão

Entregar o pacote `engine/` com: (a) o pipeline único e executável como worker (`run`), (b) a validação rápida de upload (`validate`), (c) o recálculo interativo (`scenario`), (d) todos os gates estatísticos descritos na seção 2.7, e (e) a **auditoria matemática** que comprova que os números estão certos (A10). A auditoria é parte do que o Google homologa no M2; a spec lista "gates de publicação, RBAC, jobs na nuvem, grounding do Gemini e auditoria" como **nunca cortar**.

### 5.2 Estado real

- `engine/` não existe. A API usa três stand-ins (seção 4).
- O protótipo tem duas entradas (`local_main.py` e `local_main-without-gemini.py`) com ~90% de código repetido que já divergiram, e muitos hábitos incompatíveis com rodar como serviço: `sys.exit`, `os._exit`, `os.getcwd()`, `sys.path`, `warnings.filterwarnings("ignore")` global, config mutada, dados carregados duas vezes, defaults inconsistentes (`investment_limit_factor` vale 2.0, 3.0 e 1.5 em lugares diferentes). Tudo isso é o A0. (Lista com arquivo e linha no item A0 de `trilha-a-motor.md`.)
- Existe uma auditoria interna de julho, **disponível no repo do protótipo**: `/home/rodrigo/Sistemas/Dash/opportunity-engine/docs/superpowers/plans/2026-07-08-statistical-audit-findings.md` (achados F1–F17; **leia inteira antes do A0**, ela explica *por que* o código tem tantas guardas e comentários longos). Status: F1–F7, F11–F13 e F15 corrigidos; F9 parcial; F8 e F10 adiados; F14 é escolha de config; F16 e F17 anotados. O experimento de controle dela (KPI = ruído branco ainda gerava ~16% de "lift") é o caso de aceite do A6.
- O protótipo traz **209 testes** (`tests/test_analysis.py`, `test_elasticity_analysis.py`, `test_data_preprocessor.py`, `test_dashboard_charts.py`, `test_gemini_report.py`…). Eles viram a rede de segurança do A0: mova-os junto com o código.

### 5.3 Regras do motor **[CODE-STYLE.md]**

- **Nunca hardcode nome de coluna.** Resolva por `column_mapping`. Chaves: `investment_file` (`date_col`, `channel_col`, `investment_col`), `performance_file` (`date_col`, `kpi_col`), `generic_trends_file` (`date_col`, `trends_col`). Datas viram uma coluna `Date` no pré-processamento. (O `Leads`/`Clicks`/`Impressions` hardcoded do protótipo é exatamente o que se quer eliminar.)
- Respeite `optimization_target` (`REVENUE` exige `average_ticket`).
- `financial_targets` podam as curvas de saturação (guardrails).
- `treat_outliers` configurável (booleano ou lista de colunas).
- O motor **não imprime** (`print` proibido; use `logging.getLogger(__name__)`), **não encerra o processo**, **só escreve dentro de `out_dir`**, **não toca em filtros globais de warnings**, **não muta a config recebida**.
- Sem Gemini → cai limpo para relatório determinístico.
- Mensagens para o usuário (checks, reasons, `on_log`) em **pt-BR**, prontas para a tela. Identificadores (`id`, campos JSON, nomes de coluna) em inglês e **estáveis**.
- Nome de função/variável segue o código ao redor (o `engine/` herdou português do protótipo).
- Commits: conventional, minúsculos, em inglês (`feat(engine): …`). Nova dependência Python: `uv add` e commite o `uv.lock`.

### 5.4 Mapa do protótipo (o que existe hoje em `scripts/`) **[protótipo]**

Tamanho: ~11 mil linhas, das quais ~3 mil são o `streamlit_app.py` (que **não** vira parte do motor).

| Módulo | Linhas | Papel | Destino |
|---|---|---|---|
| `data_preprocessor.py` | 1080 | Leitura robusta de CSV (encoding, delimitador, datas e números BR/US, rodapé de BI), `resolve_column`, `detect_cadence`, `drop_partial_periods`, `load_and_prepare_data` (devolve `kpi_df`, `daily_investment_df`, `trends_df`, matriz de correlação), `suggest_causal_config` | base do A2 (`validate`) e do leitor único |
| `analysis.py` | 1190 | `find_events`, `run_causal_impact_analysis` (modelo causal), `_train_response_model` / `run_opportunity_projection` (2º modelo de resposta), `find_optimal_historical_mix`, `periods_to_days`, features de calendário | A4, A6 |
| `elasticity_analysis.py` | 1196 | `run_mmm_engine` (MMM de 2 estágios), bootstrap, curvas agregada e por canal, tetos de mix, guardrails financeiros | A5, A8 |
| `gemini_report.py` | 996 | Prompt, chamada, relatório HTML/Markdown por evento e global, detecção de *outage* | A9 |
| `presentation.py` | 718 | PNG (matplotlib), CSV de apresentação, `save_causal_chart_data`, markdown comparativo de saturação | só o que alimenta o `results.json`; PNG/HTML saem do worker (A1 › em aberto) |
| `recommendations.py` | 135 | Texto determinístico (fallback sem Gemini) e cenários de orçamento | A9 (fallback) |
| `dashboard_charts.py` | 528 | Builders Plotly + `find_saturation_point`, `compute_incremental_cpa` | lógica numérica → `engine.scenario` (A8); gráficos → front (B5) |
| `saturation_curve.py` | 494 | **Código morto** (`generate_event_saturation_curves`, `run_global_saturation_analysis`) | apagar no A0 |
| `google_api.py` | 152 | Cliente Gemini + `suggest_form_fields` (a plataforma v2 reimplementou isso em `api/`) | fora do motor |
| `local_main.py`, `local_main-without-gemini.py` | 743 / 658 | Orquestração; ~107 linhas diferem entre os dois | unificar em `pipeline.run` (A0) |
| `streamlit_app.py`, `db.py`, `logger.py` | 2979 / 212 / — | UI, SQLite, tradução de log | fica até o B11 remover o Streamlit |

**Fluxo do `local_main.main(config, args)`** (o que `pipeline.run` precisa reproduzir):

1. autentica o Gemini; `load_and_prepare_data(config)` → `kpi_df`, `daily_investment_df`, `trends_df`, `correlation_matrix` (e **muta** `config["period_days"]`);
2. relê o arquivo de performance só para as covariáveis (`Leads`/`Clicks`/`Impressions`): **segunda leitura** dos mesmos dados;
3. `find_events` → `candidate_events_df` (pré-período: todo o histórico até o dia anterior; pós-período: `post_event_days`);
4. **pré-treina** o 2º modelo de resposta (`run_opportunity_projection`) sobre todo o histórico e todos os canais com evento → `projection_model_params` (α, k, s);
5. para cada candidato: `run_causal_impact_analysis` → aplica os 3 gates (seção 2.3) → guarda os aprovados;
6. ordena por |lift|, pega os `max_events_to_analyze` melhores; para cada um gera PNGs, CSV de apresentação e relatório Gemini (se houver outage, pula os demais);
7. `run_mmm_engine(config)` → **recarrega os dados pela segunda vez**, ajusta o MMM; curva agregada, curvas individuais, cenários (atual / otimizado / estratégico × 3 mixes: média histórica, pico de eficiência, modelo de elasticidade), `SATURATION_CURVE.md` e relatório global do Gemini;
8. erros: `exit(1)` em qualquer exceção; no fim `os._exit(0)` (contorno de um thread gRPC do SDK antigo do Gemini que travava o processo).

**Config do protótipo.** O `config` é um dict lido de JSON (`config.example.json`), com **caminhos de arquivo** (`investment_file_path`, `performance_file_path`, `generic_trends_file_path`, `output_directory`) em vez do dict `inputs`/`out_dir` do contrato novo. Chaves lidas no código (grep em `scripts/`): `advertiser_name`, `client_industry`, `client_business_goal`, `primary_business_metric_name`, `performance_kpi_column`, `product_group_filter`, `average_ticket` (ou o alias `average_ticket_value`), `conversion_rate_from_kpi_to_bo`, `kpi_is_monetary`, `optimization_target`, `financial_targets`, `investment_limit_factor`, `per_channel_investment_limit_factor`, `max_channel_mix_share`, `minimum_acceptable_iroi`, `min_marketing_contribution`, `p_value_threshold`, `r_squared_threshold`, `min_pre_period_days`, `require_statistical_significance`, `require_logical_direction`, `require_model_fit`, `increase_threshold_percent`, `decrease_threshold_percent`, `post_event_days`, `max_events_to_analyze`, `treat_outliers`, `date_formats`, `column_mapping`, `country_code`, `gemini_model` e `period_days` (escrita pelo motor). Outras ainda lidas por módulos que não varri.

**Isto cria um descompasso real com a API**, que você precisa resolver no A0 junto com o Dev B:

| | Protótipo (`config.example.json` / defaults no código) | `EngineConfig` provisório da API |
|---|---|---|
| gates | `require_statistical_significance`, **`require_logical_direction`**, `require_model_fit` | `require_significance`, `require_good_fit` (**sem** `require_logical_direction`) |
| `p_value_threshold` | 0,05 no código (0,1 no exemplo) | 0,05 |
| `r_squared_threshold` | 0,3 | 0,5 |
| `min_pre_period_days` | 14 (e há um piso interno de 8 períodos) | 28 |
| `increase/decrease_threshold_percent` | 50 / 30 no exemplo | 20 / 20 |
| `post_event_days`, `max_events_to_analyze` | existem (14, 5) | **não existem** na API |
| `investment_limit_factor` | 2.0, 3.0 e 1.5 espalhados no código | 1.5 (BRD) |

Ou seja, a API grava e valida uma config que **omite campos que o motor usa** (`post_event_days`, `max_events_to_analyze`, `require_logical_direction`, `country_code`, `date_formats`...) e usa defaults diferentes. Ao definir o `EngineConfig` definitivo, decida campo a campo: entra no formulário, entra como "avançado" ou fica fixo; e **os defaults têm que ser os que a Data Science aprovar**, não os que já estão na API por acaso. Note também que o `suggest_causal_config` do protótipo (sugere `min_pre_period_days`, limiares de evento pelo percentil 90 das variações reais e `investment_limit_factor`) **existe** e o B3 reescreveu uma versão mais simples sem tê-lo visto (`docs/decisoes/parametros-e-gemini.md`): vale alinhar.

---

## 6. O contrato A ↔ B em detalhe

A Trilha B **nunca** lê CSV, PNG ou HTML do motor. Só conhece quatro superfícies. Qualquer mudança nelas exige avisar a outra trilha e atualizar `docs/m2/README.md` (seção "O contrato"). Os exemplos JSON abaixo são o *ponto de partida* **[spec]**: o formato exato de cada seção é fechado no spec do item dono.

### 6.1 `EngineConfig` (dono: A0)

Modelo pydantic em `engine/config.py`, a **única fonte** de parâmetros e defaults. A API valida o formulário com ele e o front gera o formulário do `EngineConfig.model_json_schema()`; nada de defaults duplicados em TypeScript. Campos mínimos **[spec]**: `optimization_target`, coluna de KPI, `kpi_is_monetary`, `average_ticket`, `conversion_rate_from_kpi_to_bo`, `financial_targets` (`target_cpa`, `target_icpa`, `target_roas`, `target_iroas`), `investment_limit_factor` (**1.5**), `p_value_threshold`, `min_pre_period_days`, `r_squared_threshold`, `increase/decrease_threshold_percent`, `require_*`, `column_mapping`, `channel_groups`, `controls`, `gate_thresholds`, `max_budget_step` (0,20).

O **provisório** que a API usa hoje **[código, `api/engine_config.py`]** é um bom rascunho e mostra o formato esperado:

```python
class ParamsIn(Strict):          # extra="forbid", allow_inf_nan=False
    optimization_target: Literal["REVENUE", "CONVERSIONS"] = "CONVERSIONS"
    kpi_is_monetary: bool = False
    average_ticket: float | None = Field(default=None, gt=0)
    conversion_rate_from_kpi_to_bo: float = Field(default=1.0, gt=0, le=1)
    financial_targets: FinancialTargets = ...        # 4 metas opcionais, gt=0
    investment_limit_factor: float = Field(default=1.5, gt=1, le=5)
    max_budget_step: float = Field(default=0.2, gt=0, le=1)
    p_value_threshold: float = Field(default=0.05, gt=0, lt=1)
    min_pre_period_days: int = Field(default=28, ge=7)
    r_squared_threshold: float = Field(default=0.5, ge=0, le=1)
    increase_threshold_percent: float = Field(default=20, gt=0)
    decrease_threshold_percent: float = Field(default=20, gt=0)
    require_significance: bool = True
    require_good_fit: bool = True

class EngineConfig(ParamsIn):    # + preenchidos por outras telas
    column_mapping: dict; channel_groups: list[list[str]]
    controls: list[str]; gate_thresholds: dict
```

Pontos de atenção:

- **Compare com o protótipo antes de fechar o modelo** (tabela na seção 5.4): a API omite `post_event_days`, `max_events_to_analyze` e `require_logical_direction`, que o motor usa, e tem defaults diferentes.
- `require_significance` e `require_good_fit` **são nomes provisórios**; o A0 decide os definitivos e avisa o Dev B. Mudar o nome de um campo quebra configs já salvas em `simulations.config` e `runs.config`: pergunte ao Dev B como migrar.
- Os campos do formulário ficam em `ParamsIn`. A API usa `ParamsIn` para validar o `PUT …/params`; o `column_mapping` e o que A3/A4 gravarem são escritos por outras telas.
- A API **valida com pydantic estrito** (`extra="forbid"`). Se o seu `EngineConfig` aceitar campos extras, o front não os verá, mas configs antigas com campos removidos darão 422 no "Rodar de novo" (a tela já trata, ver `runs-e-jobs.md`).
- **[sugestão]** Mantenha o `EngineConfig` separado entre "o que o analista edita" (`ParamsIn`) e "o que o sistema preenche", como hoje: a tela depende dessa divisão.
- Um valor de config `None`/ausente deve significar "sem meta" (não `999999` nem `inf`, que o protótipo usa como sentinela).

### 6.2 `validate(inputs, config) -> ValidationReport` (dono: A2, com A3 dentro)

Síncrona e **rápida** (< 10 s para 2 anos diários × 15 canais): roda na requisição HTTP quando o analista confirma o mapeamento. Não roda modelo estatístico.

```json
{"ok": false,
 "cadence": "daily", "period_days": 1, "date_range": ["2024-10-01","2026-09-30"],
 "channels": ["SEARCH","PMAX","YOUTUBE"],
 "checks": [{"id": "duplicate_date_channel", "level": "error",
             "message": "12 linhas repetidas de (data, canal) no investimento",
             "details": {"rows": [...]}}],
 "collinearity": {"pairs": [{"a":"PMAX","b":"SEARCH","r":0.91}], "vif": {"PMAX": 14.2},
                  "suggested_groups": [["PMAX","SEARCH"]]}}
```

- `level`: `error` bloqueia o run; `warning` exige confirmação do analista (a API guarda quais `id`s foram confirmados no run); `info` só informa.
- `id` é **estável** (o front e a API usam, por exemplo, para o gate de avisos confirmados); `message` em pt-BR pronta para a tela.
- `ok` = não há nenhum check `error`.
- **Entrada real, hoje** **[código]**: `inputs` é `{"investment_file": Path, "performance_file": Path, "generic_trends_file": Path | None}` e `config` é um **dict** (a config salva da simulação), com `config["column_mapping"]` como nas amostras de teste (`tests/samples.py`):

```python
MAPPING = {
  "investment_file":  {"date_col": "data", "channel_col": "canal", "investment_col": "investimento"},
  "performance_file": {"date_col": "data", "kpi_col": "conversoes"},
  # opcional: "generic_trends_file": {"date_col": "data", "trends_col": "trends"}
}
```

  Note que a API chama `validate` **antes** de o analista salvar os parâmetros, então a `config` pode ter só `column_mapping` (sem `optimization_target` etc.). O seu `validate` precisa funcionar com essa config parcial (use os defaults do `EngineConfig` para o que faltar), ou a API terá de mudar a ordem do fluxo. Combine com o Dev B (ver a nota "Parâmetros não zeram a validação" em `parametros-e-gemini.md`).
- A API traduz `csvfile.Unreadable` em "Não foi possível ler o arquivo de investimento". A API já lê CSV com detecção de encoding (`utf-8-sig` senão `latin-1`) e delimitador (o mais frequente de `,;\t|` no cabeçalho). O seu `validate` precisa tolerar os mesmos formatos (o protótipo também tem essa lógica em `data_preprocessor.py`).
- Datas e números **BR e US** (`1.234,56` vs `1,234.56`) circulam nos CSVs reais. O protótipo trata isso, mas a spec aponta um bug: `.replace(".", "")` em string quebra decimal US.

### 6.3 `run(inputs, config, out_dir, on_log) -> dict` (dono: A0/A1)

Retorna o `results.json` como dict (e o grava em `out_dir/results.json`). Assinatura **[código, o worker já a chama assim]**:

```python
results = engine_run.run(inputs, config, Path(tmp), on_log)
# inputs: {"investment_file": Path, "performance_file": Path, "generic_trends_file": Path | None}
# config: dict (snapshot da config da simulação), out_dir: pasta temporária
# on_log(level, message): level em "info" | "warning" | "error", message em pt-BR
```

O que o **worker exige do retorno** **[código, `api/worker.py`]**:

- `results["status"]` ∈ `{"succeeded", "inconclusive", "failed"}`, senão o worker levanta `ValueError` e o run falha.
- `results["engine_version"]` é lido e gravado em `runs.engine_version` (use o git sha).
- Uma exceção qualquer ou `status == "failed"` vira, na tela, **"O motor falhou. Detalhes técnicos ficam no log do servidor (execução N)."** O traceback e a mensagem crua só vão para o stdout JSON (Cloud Logging). Pergunta em aberto do contrato: o motor deve levantar uma exceção própria com mensagem pt-BR para a tela? (Item A0, "Em aberto".)
- O worker faz `json.dumps(results, ensure_ascii=False)` **sem** `allow_nan=False`. Python escreve `NaN`/`Infinity` literais, que **não são JSON válido** e quebram o front. O A1 exige que o motor converta para `null` antes de devolver (critério de aceite do A1); trate isso com um passo de sanitização no fim do `run` (e um teste), em vez de confiar no worker.
- O `summary` do `Run` hoje só repete o status (`{"status": ...}`); quando o A1 existir, combine com o Dev B quais métricas-chave entram ali (para listar e comparar runs).

Formato do `results.json` **[spec, ponto de partida]**:

```json
{"schema_version": 1, "engine_version": "<git sha>", "status": "succeeded|inconclusive|failed",
 "validation": { ...ValidationReport... },
 "sufficiency": {"passed": true, "spend_variation": {...}, "validated_events": 3, "pre_wmape": 0.08},
 "causal": {
   "events_detected": [{"date":"2025-08-18","channels":["YOUTUBE"],"investment_change_pct":89.7}],
   "events": [{"id":"YOUTUBE_2025-08-18","channels":["YOUTUBE"],"start":"…","end":"…",
               "status":"published|rejected","reasons":["placebo_failed"],
               "lift":{"abs":4640000,"ci":[…,…],"rel_pct":12.1},"p_value":0.01,
               "incremental_investment":3400000,"cpa_incremental":…,"fit":{"r2":…,"wmape":…},
               "placebo":{"p_value":0.62,"passed":true},
               "series":{"line":[…],"accuracy":[…],"investment":[…],"kpi":[…]}}]},
 "elasticity": {
   "metrics": {"cv_r2":…, "r2":…, "media_contribution_pct":…, "low_confidence":false, "reallocation_suppressed":false},
   "channels": [{"name":"YOUTUBE","identifiable":true,"coef_ci":[…,…],"hill":{"K":…,"n":…},"adstock":…,
                 "observed_spend_range":[…,…],"curve":[{"x":…,"y":…,"lo":…,"hi":…,"extrapolated":false}]}],
   "groups": [{"name":"PMAX + SEARCH","members":["PMAX","SEARCH"]}],
   "response_curve": [{"investment":…,"kpi":…,"kpi_lo":…,"kpi_hi":…,"revenue":…,"icpa":…,"iroas":…,
                       "extrapolated":false,"mix":{"YOUTUBE":…}}],
   "scenarios": [{"name":"current|recommended|saturation","investment":…,"kpi":…,"kpi_lo":…,"kpi_hi":…,
                  "cpa":…,"roas":…,"extrapolated":false,"ramp":[{"step":1,"investment":…}]}]},
 "experiment_design": null,
 "reports": {"events": {"<event id>": {…narrativa…}}, "global": {…},
             "grounding": {"status":"passed|regenerated|blocked","issues":[…]}}}
```

Observações para ler esse JSON sem se perder:

- **Todo bloco carrega seu julgamento.** `status`/`reasons` por evento; `identifiable` por canal; `sufficiency.passed`; `extrapolated` por ponto de curva; `grounding.status`. A UI só renderiza esses rótulos.
- Seções cujo item ainda não existe saem **neutras e com `status` correto** (ex.: `experiment_design: null`, `placebo: null`). Assim o A1 pode sair antes do A5–A9 sem quebrar o front.
- `series` guarda dados prontos para gráfico (listas de registros), para a API/front não recarregarem os dados brutos. O A1 pede também um `baseline` mensal de investimento e KPI dentro do JSON.
- Um **schema versionado** com pydantic (`engine/results_schema.py`, `model_json_schema()`) é o critério de aceite do A1: modele o `results.json` em pydantic desde o primeiro dia, gere o JSON a partir do modelo e valide os fixtures contra ele. Isso dá ao Dev B tipos confiáveis.
- **[sugestão]** Rejeite `NaN` no próprio modelo (`allow_inf_nan=False` na `ConfigDict`), em vez de varrer o dict depois: o erro aparece onde nasce.

### 6.4 `scenario(results, filters) -> dict` (dono: A8)

Recalcula ponto ótimo, ponto de saturação e tabela de cenários quando o usuário mexe em slider ou filtro (target CPA/ROAS/iCPA/iROAS, faixa de orçamento). A API expõe como `GET /runs/{id}/scenario?...`, chamado com *debounce* de 200 ms; precisa responder em **< 300 ms** (aceite do A8; o B5 exige < 500 ms ponta a ponta). Portanto `scenario` opera sobre o `results.json` já calculado (curvas e matriz de bootstrap), **não** reajusta modelo. Hoje essa lógica mora no Streamlit (`streamlit_app.py:2208-2366`) e em `dashboard_charts.py:15-78`. `scenario` ainda não tem formato definido; defina-o no spec do A8 junto com o Dev B.

> **Consequência de projeto**: se `scenario` recebe só o `results.json`, ele precisa de tudo para recalcular bandas. Então o `results.json` (ou um artefato ao lado dele) precisa guardar a **matriz de bootstrap** (A5 diz "guardar a matriz de bootstrap: a A8 usa para as bandas"). Decida cedo onde ela mora (no JSON infla o arquivo; um `.npz` ao lado exige storage e API que o sirvam). Este é o tipo de decisão que você deve fechar com o Dev B no spec do A5/A8.

---

## 7. Os itens A0 a A10

Formato: objetivo e por quê → o que fazer → ideias técnicas → como testar → armadilhas. As seções **[spec]** repetem o essencial de `trilha-a-motor.md`; o conteúdo **[sugestão]** é novo.

### A0 · Pacote `engine` e pipeline único (semana 1, bloqueia tudo)

**Objetivo.** Transformar scripts em uma biblioteca chamável por um worker. Sem o A0, nada do resto existe.

**Fazer [spec].** (O código está em `/home/rodrigo/Sistemas/Dash/opportunity-engine/scripts/`. Para preservar histórico, faça o `git mv` num clone/branch do protótipo e traga o resultado, ou use `git subtree`/`filter-repo`; copiar arquivos perde o `git blame`. Combine com o time o que importa preservar.)
1. `git mv` dos módulos do motor de `scripts/` para `engine/`, mantendo os nomes (reduz o diff e preserva o histórico), e trocar para imports de pacote. `streamlit_app.py` fica em `scripts/` até o Streamlit ser removido (B11).
2. `engine/pipeline.py` com `run(inputs, config, out_dir, on_log) -> dict`, unindo os dois `local_main`. Gemini opcional (sem chave → texto determinístico de `recommendations.py`).
3. `engine/config.py` com o `EngineConfig` (pydantic), único lugar dos defaults, `investment_limit_factor=1.5`.
4. CLI `python -m engine --config x.json --out dir`, que o Streamlit passa a chamar no lugar dos dois scripts (preserva o plano B de demo).
5. Limpeza: `sys.exit`, `os._exit`, `os.getcwd()`, `sys.path`, `filterwarnings("ignore")` global, config mutada, dados carregados duas vezes.
6. Pergunta aberta: remover já o código morto (`saturation_curve.py`, funções mortas de `recommendations.py`)? A sugestão da spec é sim.

**Ideias técnicas [sugestão].**
- Faça o refactor em **duas fases**, com o snapshot de paridade (abaixo) como rede de segurança: primeiro mover e fazer funcionar sem mudar números; só depois limpar defaults e a duplicação. Misturar as duas dificulta saber quem mudou um número.
- `on_log` substitui `print`/stdout. Mantenha um adaptador de `logging.Handler` que encaminha para `on_log`, se o código antigo usa `logger`. A tradução pt-BR do protótipo ficava em `logger.py` (`_RULES`, ~87 regras e `TranslationFilter`) **[spec/Trilha B]**: decida se as mensagens já nascem em pt-BR no código (melhor) ou se a tradução continua como filtro.
- Para trocar `os.getcwd()`: tudo que é caminho vem de `inputs` (entrada) ou `out_dir` (saída). Nunca derive caminho de variável global.
- Para `warnings`: use `with warnings.catch_warnings():` no ponto exato, ou capture e redirecione para `on_log("warning", …)`.
- Config imutável: copie (`config.model_copy(deep=True)`) antes de qualquer ajuste interno (o protótipo grava `period_days` na config; esse valor agora é um resultado, vai para o `ValidationReport`/`results`).
- `grep -rn "os.getcwd\|sys.exit\|os._exit\|sys.path" engine/` deve voltar vazio (aceite).
- **O que o código faz hoje e precisa mudar [protótipo]:** `local_main.py` importa `elasticity_analysis as mmm_analysis` e também `saturation_curve` (morto); `data_preprocessor.py:983` faz `config["period_days"] = inv_cadence`; `local_main.py:68` e `elasticity_analysis.py:293` (dentro de `run_mmm_engine`) leem e preparam os dados **duas vezes**, e `:73` relê o arquivo de performance uma terceira vez para as covariáveis; `local_main.py:684-697` e `:743` têm os `exit(1)` e o `os._exit(0)`; `presentation.py:16-24` e `local_main.py:704` mexem em `sys.path`; `analysis.py:28` e `elasticity_analysis.py:98` definem **duas versões de `hill_transform`** (uma com `+ epsilon` no denominador, outra com `1/(1+r^-k)`) e três de adstock; `create_calendar_features` também está duplicada em `analysis.py` e `elasticity_analysis.py`.
- **Pipeline a unificar:** os passos 1–8 da seção 5.4. As diferenças entre os dois `local_main` (107 linhas) são o Gemini; confira o diff linha a linha antes de apagar um deles (a spec já avisa que o sem-Gemini lê covariáveis com `pd.read_csv` cru).

**Aceite [spec].** `mise run test` verde; **snapshot de paridade** (rodar `exemplo_csv/` antes e depois dá os mesmos números, tolerância 1e-9, guardado em `tests/fixtures/parity/`); o `grep` acima vazio; Streamlit ainda roda fim a fim.

**Como fazer o snapshot [sugestão].** A pasta `exemplo_csv/` **não existe no disco** (seção 9). Se não aparecer, gere um dataset sintético com seed fixa (2 anos diários, ~5 canais, uma subida de investimento, sazonalidade semanal, ruído) e use-o como base de paridade; ele também vira o germe do `tests/synthetic.py` da A10. Com os dados em mãos, rode o protótipo e salve as saídas numéricas (lift, p-value, curvas) em JSON. Depois do refactor, um teste `pytest` carrega o snapshot e compara com `numpy.testing.assert_allclose(rtol=1e-9)`. Atenção à reprodutibilidade: o protótipo já usa RNG local com seed 42 no bootstrap e nos reinícios do otimizador (`np.random.default_rng(42)`) e `random_state=0` no `LassoCV`; mantenha isso e a ordem das chamadas, senão a sequência muda. O ajuste do `UnobservedComponents` e o L-BFGS-B são numéricos: confirme que o snapshot reproduz na **mesma máquina e versões** (`uv.lock`) antes de exigir 1e-9; se oscilar na 8ª–10ª casa, relaxe a tolerância e documente.

**Ao concluir (integração com B).**
- `pyproject.toml`: adicionar as deps analíticas (pandas, scipy, statsmodels, scikit-learn, numpy…; o plotly só se o Streamlit continuar na mesma imagem). Hoje a imagem pesa ~291 MB só com a API; no repo antigo, o Streamlit com as deps analíticas somava ~900 MB (a imagem chegou a 1,22 GB) **[infra-e-operacao.md]**. Decida com o Dev B o que entra na imagem (plotly e o resto do Streamlit não precisam).
- `Dockerfile`: `COPY engine/ ./engine/`.
- Trocar os três módulos-ponte da API (seção 4) por imports de `engine`.
- Atualizar o parágrafo "Estado atual" do `CLAUDE.md`, a linha `Status` do item e `docs/decisoes/` (regra do projeto: no mesmo commit).

**Armadilhas.** Rodar `uv run pytest` na CI do repo exige que dados ignorados pelo git (`exemplo_csv/`, `inputs/`, `outputs/`) existam; o CI pode falhar onde o local passa (nota no plano B0). **Reporte, não pule teste.**

### A1 · `results.json` v1 + fixtures (semana 1, bloqueia B5, B6, B7)

**Objetivo.** Dar ao front um único artefato bem tipado em vez de uma pilha de CSV/PNG/HTML/MD.

**Fazer [spec].** `run()` devolve e grava o dict do contrato; seções de itens futuros saem neutras; séries dos gráficos como listas de registros (a partir de `presentation.save_causal_chart_data`); `baseline` mensal dentro do JSON; **fixtures** de `exemplo_csv/` em `tests/fixtures/results/` (um run bom, um com evento rejeitado). NaN/Infinity → `null` (o protótipo usa `target_cpa=999999` e `inf` como sentinela).

**De onde sai cada campo [protótipo].** `run_causal_impact_analysis` devolve `results_dict` com: `start_date`, `end_date`, `product_group` (string `"A, B"`), `absolute_lift`, `absolute_lift_ci_lower/upper`, `relative_lift_pct`, `p_value`, `investment_change_pct`, `cpa_incremental`, `total_investment_post_period`, `total_investment_pre_period`, `mae`, `mape`, `model_r_squared`, `event_period_avg_investment`; mais quatro DataFrames de gráfico (`line_chart_df`, `investment_bar_df`, `sessions_bar_df`, `accuracy_df`). O mapeamento natural para o contrato:

| Contrato (`causal.events[]`) | Protótipo |
|---|---|
| `lift.abs`, `lift.ci`, `lift.rel_pct` | `absolute_lift`, `absolute_lift_ci_lower/upper`, `relative_lift_pct` |
| `p_value` | `p_value` |
| `fit.r2`, `fit.wmape` | `model_r_squared`; `mape` (é WMAPE em %, in-sample) |
| `incremental_investment` | `total_investment_post_period − total_investment_pre_period` (o pré é a média móvel de 12 semanas × nº de semanas do pós) |
| `cpa_incremental` | `cpa_incremental` (= investimento do pós ÷ lift; **não** é o investimento incremental ÷ lift) |
| `series.line/accuracy/investment/kpi` | os 4 DataFrames (o de acurácia guarda só as últimas 90 linhas) |
| `channels` | `product_group.split(",")` |
| `id` | `event_id` = `{advertiser}_{canais}_{data}` |
| `status`/`reasons` | resultado dos 3 gates em `local_main.py:229-275` (hoje só log) |

Para `elasticity`, a origem é `run_mmm_engine` (`contribution_pct`, `r_squared`, `cv_r_squared`, `optimal_params` por canal, `marketing_contribution_of_kpi_pct`) e as curvas/pontos de `generate_aggregated_response_curve` e `generate_individual_response_curves`; o relatório vem de `gemini_report`. Atenção ao `cpa_incremental`: a definição do protótipo (investimento total do pós ÷ lift) difere da do contrato (`incremental_investment` na base do iCPA); decida qual é a oficial com a Data Science.

**Prioridade.** É o item que mais destrava o Dev B. **[sugestão]** Entregue primeiro os **fixtures + o schema pydantic**, mesmo que o motor ainda gere valores simples nos blocos futuros; o Dev B só precisa do formato para construir as telas (B5).

**Armadilhas.** (1) Os fixtures não podem conter dado de cliente: use o `exemplo_csv/` do protótipo (dado de exemplo) e confirme com o time que ele é público/anonimizado (`SECURITY.md`: dados de cliente não vão para o git). (2) Série de gráficos pode ficar grande: o front lê o JSON inteiro; combine um limite razoável de pontos. (3) Decida o tratamento de datas (ISO `YYYY-MM-DD` como string) e de arredondamento (guarde precisão cheia; formatação é do front).

### A2 · Validação de upload e deduplicação (semana 2, bloqueia B2 real)

**Objetivo.** Barrar problemas dos dados antes de gastar um run, com mensagens que o analista entenda.

**Fazer [spec].** Implementar `validate` com estes checks e ids:

| id | nível | o que detecta |
|---|---|---|
| `duplicate_date_channel` | error | repetição de (data, canal) no investimento (hoje o `pivot_table` tira a média em silêncio) |
| `kpi_duplicate_dates` | error | datas repetidas no KPI (hoje são **somadas** com warning) |
| `kpi_not_single_source` | error | performance com coluna de canal, ou KPI repetido por data: conversão reportada por plataforma, e não de fonte única |
| `missing_dates` | warning | datas faltantes (com a lista) |
| `outliers` | info | contagem e datas (hoje IQR só aplica, não reporta) |
| `dv360_cm360_overlap` | warning | duas séries de canal com correlação diária > 0,95 **e** razão de somas entre 0,9 e 1,1: provável dupla contagem, o analista escolhe uma |
| + os checks atuais do `data_preprocessor.py` | variados | encoding, rodapé de BI, datas BR/US, >50% NaN, cadência divergente, períodos parciais |

Além disso: `load_and_prepare_data` levanta exceções com o `id` do check (hoje re-embrulha tudo em `Exception` genérica e perde a mensagem).

**O que reaproveitar [protótipo, `data_preprocessor.py`]:** `read_csv_robust`, `robust_date_parsing`, `robust_numeric_parsing` (detecta BR/US pelos separadores), `drop_bi_export_footer_rows`, `resolve_column`, `detect_cadence`, `drop_partial_periods`, `treat_outliers`. Pontos que o A2 precisa mudar: `pivot_table` sem `aggfunc` explícito **tira a média** de linhas repetidas (data, canal) (`:1036`); datas repetidas no KPI são somadas com `groupby.sum` (`:948-955`); `drop_partial_periods` descarta períodos parciais e só loga (o `validate` deve reportá-los); o `except Exception` final (`:1079`) perde a mensagem; `ValueError`s já têm texto pt-BR útil (limiar de 50% de NaN, cadências divergentes) e podem virar checks com `id`. `detect_cadence` usa a **mediana** das diferenças entre datas únicas e "encaixa" em 1 (≤ 1,5 d), 7 (6–8 d) ou 30 (27–31 d); fora disso devolve a mediana bruta (ex.: 14). O `validate` deve decidir o que fazer com cadência não canônica; o `drop_partial_periods` descarta datas "espremidas" (< 0,6× a cadência de distância dos dois vizinhos).

**Já existe [código, `api/validation.py`] o falso** com `duplicate_date_channel`: use o formato dele como referência (`details.rows` limitado a 20 linhas, mensagem com singular/plural: "1 linha repetida" × "N linhas repetidas"). Seu `validate` deve produzir o mesmo formato para esse check, para a tela e os testes do Dev B continuarem passando. O teste do Dev B para este check está em `tests/api/test_simulations.py`.

**Ideias técnicas [sugestão].**
- Separe **leitura/normalização** (CSV → DataFrame canônico: `Date`, `Channel`, `Investment`, `KPI`) de **checagem**. O mesmo leitor serve ao `validate` e ao `run`, evitando duas leituras que divergem (o problema do protótipo).
- Para *performance* (< 10 s), vetorize com pandas: `df.duplicated(subset=[date, channel], keep=False)`, `pd.date_range` + `difference` para datas faltantes, `groupby` para somas.
- DV360/CM360: o check é por **similaridade de série**, não por nome: pivote para canal × dia, calcule `corr` entre pares (só entre canais cuja soma pareada seja comparável) e `abs(sum_a/sum_b − 1) < 0,1`. Atenção ao custo O(c²) com 15 canais: irrelevante.
- Outliers: o IQR pode ficar como está; apenas **reporte** (info) com contagem e datas.
- Cadência: infira da moda das diferenças entre datas ordenadas (1 → diária, 7 → semanal) e preencha `cadence` e `period_days` no relatório.

**Aceite [spec].** Um teste por check, com CSV mínimo em `tests/`; `validate` < 10 s em 730 dias × 15 canais; rodar sobre os dados reais das marcas Core quando chegarem e registrar o resultado (é o melhor teste dos gates).

**Em aberto.** Nome dos canais DV360/CM360 vem do arquivo do cliente; confirmar com Data Analytics. Os templates CSV padrão existem?

### A3 · Gate de colinearidade (semana 2)

**Fazer [spec].** Dentro do `validate`: correlação par a par e **VIF** (`statsmodels.stats.outliers_influence.variance_inflation_factor`) sobre o spend por canal. Thresholds em `config.gate_thresholds` (default |r| > 0,85, VIF > 10). `suggested_groups` = **componentes conexos** dos pares sinalizados. O analista escolhe entre `config.channel_groups = {"PMAX + SEARCH": ["PMAX","SEARCH"]}` (soma o spend antes de modelar) e `config.block_per_channel = true` (modelo roda, resultado por canal sai `identifiable=false`, A5). Colinearidade não resolvida → erro de validação.

**Ideias técnicas [sugestão].**
- Componentes conexos: monte um grafo cujas arestas são os pares com |r| acima do limiar (ou cujos nós têm VIF alto) e use busca em profundidade/`scipy.sparse.csgraph.connected_components`. Se A–B e B–C correlacionam, o grupo sugerido é {A, B, C}.
- VIF com `statsmodels`: adicione uma constante (`sm.add_constant`) à matriz de spends antes de chamar a função, senão o VIF sai deformado. Canal com variância zero (gasto constante) vira divisão por zero: trate antes e reporte como outro check.
- Aceite pede conferir o VIF contra um **cálculo manual** em caso pequeno: faça a regressão de um canal nos outros com `numpy.linalg.lstsq` e compare `1/(1−R²)`.
- Pergunta aberta da spec: VIF sobre spend cru ou após adstock? O BRD diz "channel spend": comece com cru.
- **Atenção à fronteira A3 ↔ B2**: a tela de agrupamento (analista escolhe agrupar ou bloquear) é do B2 e espera `collinearity` no relatório e `channel_groups`/`block_per_channel` na config. `channel_groups` já existe no `EngineConfig` provisório, mas `block_per_channel` não: o A3 precisa acrescentá-lo e avisar o Dev B, que ajusta a tela.

**Aceite.** Sintético: dois canais com r = 0,95 são sinalizados; agrupados viram um canal; resultado só em nível de grupo.

### A4 · Controles causais livres de contaminação (semana 2)

**Fazer [spec].** Remover as covariáveis ad-driven hardcoded (`Leads`, `Clicks`, `Impressions` em `analysis.py:307-320`, com case exato e fora do `column_mapping`). **Clicks, impressions, branded search e conversões de plataforma nunca entram como controle.** Controles vêm de `config.controls` (colunas do arquivo de trends ou séries pré-empacotadas); cada um é triado: correlação com o spend do canal tratado no pré-período > `gate_thresholds.control_spend_corr` (default 0,5) → **rejeitado**, listado em `reasons`. `LassoCV` passa a usar `TimeSeriesSplit`. Séries do Banco Central (SGS: IPCA, Selic, IBC-Br) são o **1º item da ordem de corte**.

**Onde mexer [protótipo].** `analysis.py:307-346` define `possible_covariates = ["Leads", "Clicks", "Impressions"]` e as junta ao `model_data`; `:421-431` as coloca na lista candidata do Lasso (junto com as transformadas de investimento, dummies de calendário e colunas cujo nome contém `generic`); `:433-453` aplica `VarianceThreshold` e `LassoCV(cv=5)` com `MinMaxScaler`. Para o `TimeSeriesSplit`, troque `cv=5` por um splitter temporal e padronize dentro do fold. Note que o fallback `selected_features = list(transformed_features.keys())` (Lasso zerou tudo) coloca **todo** o investimento transformado como regressor: relevante para a observação (a) da seção 2.3.

**Por quê.** Se um controle é, em parte, consequência do investimento, ele absorve o efeito que se queria medir. Exemplo: mais gasto → mais cliques → o modelo "explica" a alta de conversões pelos cliques e deixa o lift perto de zero.

**Ideias técnicas [sugestão].**
- Triagem: para cada controle `c` e cada canal tratado `ch`, calcule `corr(c[pre], spend_ch[pre])` na janela pré-evento; se o módulo passar do limiar, rejeita e registra o `reason` (ex.: `control_correlated_with_spend`).
- `TimeSeriesSplit` no `LassoCV(cv=TimeSeriesSplit(n_splits=5))`. Padronize as covariáveis **dentro** de cada fold para não vazar informação do futuro.
- Corrigir `.replace(".", "")` em string: o parse numérico BR/US deve vir do leitor único (A2), não de `replace` espalhado.

**Aceite.** Um arquivo de performance com coluna `Clicks` **não muda** o resultado; um controle sintético igual a spend + ruído é rejeitado; o snapshot de paridade muda só no que foi intencional, **registrado para a A10**.

**Armadilha.** Esta é a primeira mudança que altera números de propósito. Anote cada mudança intencional (qual achado, quanto mudou) num arquivo vivo; a A10 precisa mapear "toda diferença para uma correção documentada".

### A5 · Identificabilidade por canal (semana 3)

**Fazer [spec].** Hoje o bootstrap (n = 200, seed 42, `elasticity_analysis.py:256-280`) calcula a matriz de coeficientes e só a média sobrevive. Expor percentis 2,5/97,5 por canal em `channels[].coef_ci`; `identifiable=false` quando o IC cruza zero **ou** a largura é maior que o |ponto|; canal não identificável sai de curva individual, mix, cenários e do payload do Gemini (só o grupo ou o total é publicado, com o motivo). **Guardar a matriz de bootstrap para o A8.**

**Ideias técnicas [sugestão].**
- Com `B` amostras e `C` canais, a matriz tem forma `(B, C)`. `coef_ci = np.percentile(M, [2.5, 97.5], axis=0)`. A regra: `identifiable = not (lo <= 0 <= hi) and (hi − lo) <= abs(point)`.
- Defina o "ponto" (média ou mediana do bootstrap, ou o ajuste original?). A spec diz "|ponto|": registre a escolha e use a mesma em todo o motor.
- Bootstrap de série temporal: reamostrar linhas iid destrói a autocorrelação. O protótipo faz o que faz; se for iid, comente na A10 (**revisar e decidir**: *block bootstrap* seria mais correto, mas muda números).
- Garanta que um canal `identifiable=false` **não vaza** em nenhum lugar do JSON (teste: percorra o JSON e procure o nome do canal fora de `groups`/`channels[].identifiable`/`reasons`).

**Aceite.** Sintético: canal sem efeito real → `false`; canal com efeito forte → `true`; JSON de um run com canal não identificável não contém curva nem mix dele.

### A6 · Suficiência de dados e placebo (semana 3)

**Fazer [spec].**
- **Suficiência** (`results.sufficiency`): variação de spend por canal analisado (coeficiente de variação ≥ threshold); nº de eventos validados ≥ 1; **WMAPE fora da amostra** do contrafactual segurando os últimos 20% do pré-período. Falhou → `status: "inconclusive"`, sem lift publicado, e o A7 entra. CV com poucas linhas (< 40, hoje cai calado para in-sample em `elasticity_analysis.py:169-206`) também reprova.
- **Placebo por evento**: intervenção falsa no meio do pré-período, mesmo modelo; `p < p_value_threshold` → evento `rejected` com `reasons: ["placebo_failed"]`.

**Ideias técnicas [sugestão].**
- *Coeficiente de variação* = desvio-padrão / média do spend do canal. O threshold é "em aberto": proponha um valor (ex.: 0,10) e calibre na A10.
- *Hold-out do pré-período*: ajuste o contrafactual nos primeiros 80% do pré-período e calcule WMAPE nos últimos 20%. **Não** use o pós-período (contaminado pelo evento).
- *Placebo*: dentro do pré-período, escolha uma data falsa (ex.: ponto médio), trate-a como se fosse um evento, ajuste o modelo só com dados anteriores a ela e estime o "lift" no trecho seguinte (antes do evento real). O p-value do placebo é lido como o do evento real. Cuidado: o pré-período precisa ser longo o bastante para caber o placebo; `min_pre_period_days` (28) pode não ser suficiente, e nesse caso o gate deve reprovar por falta de dados, não passar.
- *Caso de aceite do BRD*: KPI = ruído puro → nenhum evento publicado e run `inconclusive` ("16% de efeito no ruído" citado no BRD). Use `numpy.random.default_rng(seed)` e **muitas seeds** (a A10 pede 50): com α = 0,05 espera-se ~5% de falso positivo por teste; o placebo e a suficiência existem para derrubar isso.

**Aceite.** White noise → zero eventos publicados e `inconclusive`; placebo com efeito injetado no pré-período reprova.

### A7 · Experiment designer (semana 3)

**Fazer [spec].** Quando `status == "inconclusive"`, preencher `experiment_design` com: `test_type` (on/off, step-up de orçamento; geo split fica de fora, não há dimensão geográfica), `mde` (95% de confiança, 80% de poder, a partir da volatilidade residual do pré-período), `duration_days`, `budget_at_risk` (spend da célula de teste × T) e `assumptions` em texto. Calibração: upload do resultado do experimento (a plataforma guarda; no M2 o motor só **exibe** a referência no run seguinte). Fórmula validada pela Data Science.

**A matemática, em detalhe [sugestão, parte da spec].**

Seja σ o desvio-padrão residual por período do pré-período, T o número de períodos do teste, e queremos detectar o **efeito cumulativo** D (soma do lift em T períodos). Sem autocorrelação, o erro-padrão da soma é `σ·√T`, então com z₁₋α/₂ = 1,96 e z_poder = 0,84:

```
MDE_abs(T) ≈ (1,96 + 0,84) · σ · √T = 2,8 · σ · √T
```

Com resíduos autocorrelacionados AR(1) de coeficiente φ, a variância da soma cresce por `(1+φ)/(1−φ)`:

```
MDE_abs(T) ≈ 2,8 · σ · √T · √((1+φ)/(1−φ))
```

Para a duração: o efeito plausível é `lift_rel_alvo · μ · T` (μ = média do KPI por período; default de 5% para o lift relativo). Procure o menor T tal que `MDE_abs(T) < lift_rel_alvo · μ · T`. Isso tem solução fechada, `T > (2,8 · σ · k / (lift_rel_alvo · μ))²` com `k = √((1+φ)/(1−φ))`, mas implemente uma busca em T inteiro (também respeita um máximo razoável de dias).

**Aceite [spec].** Com σ e T conhecidos, o MDE confere com o cálculo manual; uma simulação **Monte Carlo** com efeito = MDE detecta ≈ 80% das vezes (tolerância ± 5 p.p.). Escreva o Monte Carlo: gere ruído AR(1), injete D, aplique o teste, repita ≥ 1000 vezes e meça a taxa de detecção.

**Armadilha.** φ é estimado dos resíduos; com poucos pontos é instável e pode chegar perto de 1 (k explode). Limite φ (ex.: máx. 0,9) e registre em `assumptions`.

### A8 · Guardrails do planner e `engine.scenario` (semana 3)

**Fazer [spec].**
- **Bandas**: propagar a matriz de bootstrap (A5) pela curva → `kpi_lo`/`kpi_hi` (percentis 5/95) em todo ponto e cenário.
- **Extrapolação**: `extrapolated=true` em ponto/cenário fora da faixa histórica de spend (por canal e total); as curvas individuais passam a respeitar o cap (hoje pulam: `elasticity_analysis.py:1070-1072`).
- **Passo máximo**: `config.max_budget_step` (0,20). Mudança maior vira `ramp`, uma lista de degraus de até 20%. Cenário +50% com passo 20% → **3 degraus** (1,2 → 1,44 → 1,5; ver abaixo).
- Notas de tCPA/tROAS em texto fixo nos cenários.
- Learning/budget-limited do Google Ads: **cortável** (depende de OAuth).
- `engine.scenario(results, filters)` reúne filtro, ponto ótimo e saturação que hoje estão no Streamlit/`dashboard_charts`. Portar com os testes de `test_dashboard_charts.py`.

**Detalhe do `ramp` [sugestão].** Degraus compostos: de I₀ a alvo I_f em passos de no máximo 20% sobre o valor atual: I₁ = 1,2·I₀, I₂ = 1,2·I₁ = 1,44·I₀, I₃ = min(1,2·I₂, I_f) = 1,5·I₀. Três degraus. Defina se o passo é composto (sobre o anterior) ou linear (sobre o original): a spec não diz; o exemplo "+50% com 20% → 3 degraus" funciona nos dois (linear: 1,2; 1,4; 1,5), então **decida com Data Science e documente**.

**Bandas.** Para cada amostra de bootstrap `b`, calcule a curva `y_b(x)` com os parâmetros dessa amostra; `kpi_lo, kpi_hi = percentis 5 e 95 de y_b(x)` em cada `x`. Vetorize sobre (B, nº de pontos) com numpy para ficar em < 300 ms.

**Aceite.** Mesmos filtros dão o mesmo ponto ótimo que o Streamlit (**teste de paridade**); nenhum ponto sem banda; `scenario` < 300 ms.

**Nota.** Os testes de `test_dashboard_charts.py` estão em `/home/rodrigo/Sistemas/Dash/opportunity-engine/tests/`; a lógica numérica a portar é `find_saturation_point` e `compute_incremental_cpa` (`dashboard_charts.py:15-80`), mais o filtro/ponto ótimo de `streamlit_app.py:2208-2366`. Os `build_*` de gráficos Plotly **não** entram no motor (são do B5).

### A9 · Grounding do Gemini (semana 3)

**Fazer [spec].**
- Migrar para `google-genai` (a API da plataforma já usa; ver `api/gemini.py` para o jeito de chamar), com `temperature=0`, `response_mime_type="application/json"` e `response_schema`. O protótipo usa `google-generativeai` (descontinuado).
- Payload restrito ao que o BRD permite: lift, p-values, R², WMAPE, K, ótimo, status de guardrails e gates. **Sem linhas de dado.**
- Canal não identificável ou run inconclusivo → o prompt recebe o status e só pode explicar *por quê*. Corrigir o achado F17 (`low_confidence` não chega ao prompt).
- **Checagem pós-geração**: extrair todo número do texto (formatos pt-BR: `R$ 3,4M`, `89,7%`, `-0,17x`, `4,64M`) e casar com algum valor do payload com tolerância de arredondamento; todo nome de canal citado tem que estar no conjunto publicado. Falhou → regenera 1×; falhou de novo → `grounding.status="blocked"` e a UI mostra o texto determinístico de `recommendations.py`.
- Remover a menção a imagem inexistente (o prompt global diz que há imagem, mas não envia).
- A narrativa entra **sem escape** no HTML no protótipo (só o título é escapado). No React o risco é outro (nunca use `dangerouslySetInnerHTML` com esse texto); combine com o Dev B que a narrativa é texto puro.

**Ideias técnicas [sugestão].**
- *Extrator de números*: uma regex para número pt-BR (`\d{1,3}(?:\.\d{3})*(?:,\d+)?` com sufixos `%`, `x`, `K|M|mi|mil|bi`) que normaliza para `float`. Defina o sufixo: `3,4M` → 3.400.000. Cuidado com datas (`18/08/2025`) e anos, que não são números do payload: use uma lista de exceções (datas, anos 20xx, numerais de lista).
- *Tolerância*: se o texto mostra `89,7%`, aceite o valor do payload `89.71` (mesma casa decimal do texto: compare `round(valor, casas_do_texto)`). Para sufixo `M`, `3,4M` aceita 3.35M–3.45M. Derive a tolerância das casas decimais exibidas, não de um número fixo.
- *Nomes de canal*: confira por nome exato (ignorando caixa) contra o conjunto publicado; e rejeite canais `identifiable=false` ou eventos `rejected`.
- Teste com **textos fabricados** (aceite): número inventado reprova, canal rejeitado reprova, arredondamento legítimo passa.
- **Estado atual do payload [protótipo, `gemini_report.py:67-229`]:** o prompt leva `causal_impact_results`, `model_validation_metrics` (r², mae, mape), **a tabela CSV de apresentação inteira** (`presentation_data_csv`) e **a matriz de correlação** investimento×KPI (com nomes de canal). Isso é mais largo que o "payload restrito" que o BRD pede e deve ser enxugado. Usa `gemini_client.generate_content` do SDK antigo, tira o *code fence* na mão (`replace("```json\n", ...)`) e falha com `RuntimeError` se o JSON não parsear. O schema pedido tem `report_title`, `executive_verdict`, `detailed_analysis`, `value_delivered{narrative, methodology_narrative}`, `next_steps[3]`; a `methodology_narrative` cita `UnobservedComponents` (verifique que o texto bate com o modelo real depois do A4/A6).
- O motor já tem tratamento de outage do Gemini (`gemini_report.py:43`, `local_main.py:414-441`): preserve.

**Aceite.** Testes do checador (acima); sem chave, o run termina com relatório determinístico.

**Em aberto.** Sem projeto GCP, Vertex AI sai de cogitação: o caminho é API key por variável de ambiente. Na A9, use o módulo `llm/` (`generate_json` com o schema) e não o SDK direto. Não conte com `temperature=0` na interface: ela não expõe amostragem (alguns modelos nem aceitam); o determinismo vem do grounding.

### A10 · Auditoria matemática (semana 4, 9–13/nov)

**Objetivo.** Provar, com números, que o motor acerta o que deve acertar e não "acha" efeito onde não há. É o que o Google audita.

**Fazer [spec].**
- **Gerador sintético** (`tests/synthetic.py`): `KPI = baseline (calendário + tendência) + Σ Hill(adstock(spend)) + ruído`, com lift e K **conhecidos**. Rode o motor e meça a recuperação.
- **Controle white noise**: nenhum efeito publicado.
- **Paridade com `upstream/main`** no `exemplo_csv` onde for intencional: toda diferença mapeia para uma correção documentada (F1… e as novas de A2–A9).
- **Revisar e decidir**, documentando: `seasonal=7` fixo mesmo com cadência semanal (`analysis.py:456`); `cum_se` assumindo independência (`:508-518`); adstock oculto em canal com correlação negativa com o KPI (`data_preprocessor.py:1043-1058`); três convenções de adstock (F10); fallback in-sample do CV.
- Calibrar os thresholds dos gates e o **histórico mínimo** de dados (o BRD pede para confirmar na semana 4).
- Relatório em `docs/audit/2026-11-auditoria-matematica-m2.md`: método, datasets, critérios, resultado e lista de correções com evidência.

**Aceite.** **Critérios numéricos definidos *antes* de rodar**, por exemplo "lift recuperado dentro do IC 95% em ≥ 90% dos cenários sintéticos" e "0 eventos publicados no white noise em 50 seeds". **Os critérios oficiais são da Data Science e estão em aberto: cobre antes de 9/nov.**

**Dica [sugestão].** O gerador sintético é útil **antes** da semana 4: ele é o seu laboratório para A5, A6 e A7 (white noise, canal sem efeito, efeito injetado). Escreva uma versão enxuta cedo e reuse. Fixe seeds e guarde-as nos testes.

---

## 8. Ordem de ataque, testes e ferramentas

### 8.1 Grafo de dependências **[spec]**

```
A0 ──▶ A1 ──▶ (B5, B6 métricas, B7)
A0 ──▶ A2 ──▶ A3 ──▶ A5 ──▶ A8 (com A1) ──▶ B5 scenario
A0 ──▶ A4
A0 ──▶ A6 ──▶ A7
A5, A6 ──▶ A9
A2…A9 ──▶ A10
```

### 8.2 Ordem recomendada **[sugestão]**

Pensada para destravar o Dev B o mais cedo possível e tornar o risco visível:

1. **Dias 1–2: leitura e baseline.** Conseguir o `exemplo_csv/` e o BRD; rodar a suíte do protótipo; ler a auditoria de julho e o código nas seções 5.4 e 2.3/2.4; ler `docs/m2/` inteiro e `api/engine_run.py`, `api/validation.py`, `api/worker.py`.
2. **A0 em duas fases**, com snapshot de paridade primeiro. Entregue `EngineConfig` cedo (o Dev B depende dos nomes dos campos).
3. **A1: schema pydantic + fixtures primeiro**, depois o resto do JSON. Entregue ao Dev B assim que houver o formato, mesmo com blocos neutros. Isso destrava o B5.
4. **A2** (substitui o `validate` falso e destrava dados reais das Core), **A3** em seguida (mesma função).
5. **A5 → A8** (bandas dependem da matriz de bootstrap) em paralelo ao **A6 → A7**.
6. **A4**: toca no modelo causal e muda números; faça junto ou antes do A6 para a calibração partir de um modelo estável.
7. **A9** por último entre os gates (depende dos status dos demais).
8. **Gerador sintético** (`tests/synthetic.py`) desde cedo; **A10** com critérios acordados antes de rodar.

Para o que não couber até 18/nov, use a **ordem de corte** da spec: (1) séries do BCB (A4); (2) learning/budget-limited do Google Ads (A8); (3) uso do experimento como calibração (A7, só guardar); (4) comparação lado a lado no histórico (B6); (5) overlap DV360/CM360 vira warning manual (A2); (6) cópia do histórico no BigQuery; (7) OAuth nativo (os itens 2, 6 e 7 já saíram do escopo com a decisão de não integrar com o Google). **Nunca cortar**: gates de publicação, RBAC, jobs na nuvem, grounding do Gemini, auditoria.

### 8.3 Fluxo de trabalho do projeto **[CLAUDE.md]**

Para cada item A*: ler `docs/m2/README.md` + o item → ler no BRD as seções citadas → ler o código em "Hoje" e confirmar → levar as "Em aberto" ao usuário → escrever o spec em `docs/superpowers/specs/AAAA-MM-DD-<id>-<slug>-design.md` (fluxo `superpowers:brainstorming`) → plano → implementar com TDD. Cada linha de **Aceite** vira pelo menos um teste. Ao concluir, atualizar no mesmo commit o parágrafo "Estado atual" do `CLAUDE.md` e a linha `Status` do item em `trilha-a-motor.md` (com data e o que foi verificado) e o arquivo da área em `docs/decisoes/`.

### 8.4 Setup local

```bash
docker compose up -d                  # Postgres 16 em :5432 (usuário/senha/banco: app)
mise run db-migrate                   # migrations
mise run create-admin voce@exemplo.com "Seu Nome"   # imprime a senha temporária
mise run api                          # API em :8000
mise run web                          # SPA em :5173
mise run test                         # uv run pytest
mise run worker <run_id>              # executa um run (python -m api.worker)
```

Use `uv` e `bun` (não pip/poetry/npm). Para trabalhar **só no motor** você não precisa de Postgres nem de web: o `engine/` deve ser testável com `pytest` puro (arquivos de entrada em `tmp_path`, sem rede). Teste que depende do Postgres pede o fixture `db` e **falha**, não pula, se o banco estiver fora.

### 8.5 Testes e qualidade **[CODE-STYLE.md]**

- TDD: ver o teste falhar, implementar, ver passar. Teste novo nasce com o código.
- `ruff format` (linha 120) e `ruff check`, ambos no CI; rode antes de dar algo por pronto.
- **Testes determinísticos**: seeds fixas; tolerâncias numéricas explícitas (`assert_allclose`); nada de depender de ordem.
- Mensagens ao usuário em pt-BR; erro de um evento/canal **não derruba o run inteiro**: registre `warning`/`reasons` e siga.
- Logging por nível: `DEBUG` detalhe, `INFO` marco visível ao usuário (o `on_log` vira o log da tela), `WARNING` degradou mas segue, `ERROR` unidade falhou, `CRITICAL` run não continua. Senha, token, chave **nunca** em log. Exceção com `exc_info=True`.
- **Segurança de dados**: dados de cliente (CSV, resultados) e o BRD nunca vão para o repositório (`.gitignore`). Fixtures devem ser sintéticos ou o `exemplo_csv/` público.
- O que o BRD/plano cortam **não se implementa, nem "para preparar terreno"**. Se algo parecer exigir um corte, pare e pergunte.

### 8.6 Onde cada decisão está escrita

| Se você quer saber… | Leia |
|---|---|
| O plano, decisões e contrato | `docs/m2/README.md` |
| Detalhe de cada item A* | `docs/m2/trilha-a-motor.md` |
| O que a plataforma espera do motor | `docs/decisoes/runs-e-jobs.md`, `parametros-e-gemini.md`, `upload-e-storage.md` |
| Estilo, testes, regras do motor | `CODE-STYLE.md` |
| Rotas e tabelas | `API-GUIDE.md`, `DATABASE.md` |
| Segredos, dados de cliente | `SECURITY.md` |
| Como cada B* foi desenhado | `docs/superpowers/specs/` e `plans/` |

---

## 9. Perguntas em aberto, riscos e primeiros passos

### 9.1 Perguntas para fazer logo (ordem de importância)

1. **Onde estão o `exemplo_csv/` e dados reais?** O código do protótipo já está acessível (`/home/rodrigo/Sistemas/Dash/opportunity-engine/`), mas a pasta `exemplo_csv/` (gitignored) não existe no disco. Sem ela, o snapshot de paridade (A0) e os fixtures (A1) precisam de um dataset sintético, que não é o que a spec descreve. Pergunte quem tem o `exemplo_csv/` e se pode ser versionado.
2. **Escopo realista:** A0–A4 deveriam estar prontos. Quanto do calendário é negociável? Qual é o mínimo para a demo de 18/nov (provavelmente A0, A1, A2, A6 e A9, com A10 reduzida)?
3. **Quem é a Data Science** dona de metodologia (A7, thresholds do A6, critérios da A10) e quando entregam os critérios numéricos (antes de 9/nov)?
4. **Nomes definitivos do `EngineConfig`** (`require_*`) e política de migração de configs já salvas.
5. **`summary` do run:** quais métricas-chave o motor devolve para a lista/histórico?
6. **Exceção própria do motor** com mensagem pt-BR para a tela?
7. **Onde mora a matriz de bootstrap** (no `results.json` ou em artefato ao lado) e o formato de `scenario`?
8. **Gemini:** continua como único provedor de LLM (decisão de 04/nov), via módulo plugável. A integração com o Google para *métricas* saiu do escopo.
9. **Dados reais das marcas Core:** quando chegam (previsto a partir de 26/out)? Rode o `validate` neles assim que possível.
10. **Dependências na imagem Docker:** o que entra (pandas/scipy/statsmodels/scikit-learn) e o impacto no tamanho da imagem e no tempo de partida, medidos no servidor próprio (x86-64; os pacotes numéricos fixados têm wheels binários).

### 9.2 Riscos que você deve ter no radar

- **Cronograma**: dois itens críticos (A0, A1) fora do prazo e bloqueando a Trilha B.
- **Reprodutibilidade numérica**: refatorar um motor estatístico sem snapshot de paridade é voar cego. Um bootstrap com RNG global ou ordem de operações diferente muda números na 10ª casa.
- **Falsos positivos**: o BRD cita "16% de efeito em ruído puro". Se os gates falharem, o Google vê o motor "descobrindo" efeito onde não há. Priorize white noise e placebo.
- **Custo e confidencialidade do Gemini**: payload só com agregados; sem log de prompt/resposta.
- **Sentinelas**: `999999`, `inf`, `NaN` circulando como "sem meta" quebram JSON e telas. Use `null`.
- **Defaults duplicados**: manter um só lugar (`EngineConfig`).
- **Tempo de execução**: a API marca como morto um run ativo há mais de 20 min (`STALE_AFTER`); o motor, com bootstrap e placebo por evento, precisa caber nisso ou o Dev B ajusta o limite. Meça no servidor próprio cedo. A paridade numérica entre máquinas x86 pode oscilar além de 1e-9 se as CPUs usarem kernels de BLAS diferentes; veja o spec do A0.

### 9.3 Seus primeiros passos (checklist)

- [ ] Ler `docs/m2/README.md` e `docs/m2/trilha-a-motor.md` (30 min).
- [ ] Conseguir o BRD e o `exemplo_csv/` (pergunta 1).
- [ ] Rodar o protótipo: `cd /home/rodrigo/Sistemas/Dash/opportunity-engine && uv run --with pytest pytest -q` (209 testes, ~16 s) e ler a auditoria de julho inteira (`docs/superpowers/plans/2026-07-08-statistical-audit-findings.md`).
- [ ] Ler, nesta ordem, no protótipo: `scripts/local_main.py` (orquestração), `analysis.py:105-680` (eventos e causal), `elasticity_analysis.py:283-520` (MMM), `data_preprocessor.py:775-1080` (preparação).
- [ ] Subir o ambiente local (seção 8.4) e abrir a plataforma em `http://localhost:5173`; criar uma simulação com CSVs de teste (veja `tests/samples.py`) e disparar um run para ver o log do motor **falso** na tela. É o jeito mais rápido de entender onde o seu código entra.
- [ ] Ler `api/worker.py`, `api/engine_run.py`, `api/validation.py`, `api/engine_config.py` (15 min).
- [ ] Salvar o snapshot de paridade (com `exemplo_csv/` ou dataset sintético com seed fixa) **antes** de mexer no código.
- [ ] Conversar com o Dev B: nomes do `EngineConfig`, formato do `results.json`, `summary`, onde moram os artefatos grandes.
- [ ] Escrever o spec do A0 (`docs/superpowers/specs/2026-11-0X-a0-...-design.md`) e começar.

---

## 10. Glossário

| Termo | Significado |
|---|---|
| **A\*/B\*** | Itens de trabalho do M2: A = motor, B = plataforma |
| **Adstock** | Efeito residual da propaganda ao longo dos dias seguintes |
| **BRD** | Documento de requisitos do cliente (confidencial) |
| **Cadência** | Granularidade temporal dos dados (diária/semanal) |
| **Canal** | Fonte de mídia onde se investe (SEARCH, PMAX, YOUTUBE…) |
| **Contrafactual** | O que o KPI teria sido sem a mudança de investimento |
| **CPA / iCPA** | Custo por aquisição / incremental |
| **Worker** | Processo que executa um run (`python -m api.worker`); no desenho original, um Cloud Run Job |
| **Colinearidade** | Variáveis que se movem juntas, impedindo separar seus efeitos |
| **Contaminação** | Controle que o próprio investimento influencia |
| **DTS** | BigQuery Data Transfer Service (carga diária do Google Ads) |
| **Elasticidade** | Sensibilidade do KPI a variações de investimento |
| **Evento** | Mudança brusca de investimento em um canal |
| **Extrapolação** | Estimativa fora da faixa de investimento já observada |
| **Gate** | Teste de qualidade que um resultado precisa passar para ser publicado |
| **Grounding** | Checagem de que o texto gerado só usa números/canais reais |
| **Guardrail** | Limite (CPA/ROAS-alvo, passo máximo) que poda recomendações |
| **Hill** | Curva de saturação `x^n/(K^n + x^n)` |
| **Identificável** | Efeito do canal distinguível de zero e separável dos outros |
| **Inconclusivo** | Dados não sustentam conclusão; vira proposta de experimento |
| **KPI** | Resultado a otimizar (conversões ou receita) |
| **Lift** | Efeito incremental causado pelo investimento |
| **MDE** | Menor efeito detectável por um experimento |
| **MMM** | Marketing Mix Modeling (modelagem do mix de mídia) |
| **Placebo** | Teste com intervenção falsa para detectar falso positivo |
| **Pré-período** | Dias anteriores ao evento, usados para treinar o contrafactual |
| **ROAS / iROAS** | Retorno sobre gasto / incremental |
| **SSE** | *Server-Sent Events*: o canal do log ao vivo no navegador |
| **VIF** | Fator de inflação da variância; mede colinearidade |
| **WMAPE** | Erro percentual absoluto ponderado |
| **Workspace** | Espaço isolado de uma marca/cliente na plataforma |
