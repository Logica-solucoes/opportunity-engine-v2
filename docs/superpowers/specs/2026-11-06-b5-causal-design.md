# B5 (parte 1) · Dashboard Causal — design

Data: 06/nov/2026. Item: B5 em `docs/m2/trilha-b-plataforma.md`. Depende do A1 (`results.json` v1 e os fixtures em `tests/fixtures/results/`), já no `main`. Não depende do A8: a aba Causal não usa `scenario`.

## Objetivo e recorte

A página do run ganha abas, e a primeira é a **Causal**: resumo dos eventos, lista de eventos e o detalhe de um evento publicado, com veredito, métricas e gráficos, tudo lido do `results.json` pela API. O front só formata e conta status, sem calcular nada. Um plano só (backend pequeno e telas juntos).

| Fora | Volta quando |
|---|---|
| Aba Elasticidade, filtros, slider, `scenario` | B5 parte 2, depois do merge do A8 (`band`, `extrapolated`, `ramp`, rota `scenario`) |
| Card do experiment design no run inconclusivo | A7; hoje `experiment_design` sai `null` |
| Selo de grounding e relatório do Gemini | A9 |
| Paridade visual pixel a pixel com o Streamlit | Não volta; ver o desvio abaixo |
| `placebo` e `wmape` no detalhe do evento | A6; hoje saem `null` |

## Desvios do `trilha-b-plataforma.md`

- **Recharts (via `chart` do shadcn), não plotly.js.** O Recharts já está no UI stack, pesa ~100 KB gz (o plotly básico, ~350 KB), e herda o tema claro/escuro pelas variáveis CSS. A paridade com o Streamlit passa a ser de **conteúdo e número** (mesmas séries, mesmos valores, mesmos rótulos), não de aparência.
- **Rotas em português, sob o run existente.** Em vez de `/w/{ws}/runs/{id}/causal`, a rota é `/w/$slug/execucoes/$runId/causal`, ao lado de `/detalhes`, seguindo o histórico do B6.
- **Evento rejeitado não mostra número nem gráfico.** Só canais, datas e o motivo em pt-BR. O BRD manda manter o reprovado fora dos dashboards, e um lift com aviso de "não publicável" acaba citado numa apresentação mesmo assim. O `series` dos rejeitados existe no JSON e é ignorado pela tela.

Os três entram em `docs/decisoes/dashboards.md` (arquivo novo, com linha no índice `docs/decisoes/README.md`).

---

## Backend

### Rota

| Método | Rota | Regra |
|---|---|---|
| GET | `/api/w/{slug}/runs/{run_id}/results` | Viewer+ (viewer só vê publicado, pelo `find_run` que já existe). Devolve o `results.json` gravado como está, `FileResponse` com `media_type="application/json"`, sem parsear. Run sem `results_uri` (rodando, falhou, morto) → 404 "Esta execução não tem resultado." |

Outro workspace ou run não publicado para o viewer → 404, como as outras rotas do run. A regra fica em `api/runs.py` (função pequena que devolve o caminho ou levanta), e a rota só traduz. O A8 adiciona `scenario` nos mesmos dois arquivos; as duas mudanças só acrescentam código.

### Motor falso

`api/engine_run.fake_run` passa a aceitar `FAKE_ENGINE_RESULTS=<caminho de um results.json>`: com a variável, devolve o conteúdo do arquivo; sem ela, o documento com seções `null` de hoje. O E2E aponta para `tests/fixtures/results/gol_anonimizada.json`.

### Testes (`tests/api/test_results.py`)

- Analyst recebe o arquivo byte a byte igual ao gravado.
- Viewer: 404 em run não publicado, 200 depois de publicar.
- Outro workspace → 404.
- Run sem resultado (`queued`, `failed`) → 404.
- `fake_run` com `FAKE_ENGINE_RESULTS` devolve o fixture.

---

## Telas

### Rotas (`web/src/routes/_auth/w/$slug/execucoes/`)

| Arquivo | O que faz |
|---|---|
| `$runId.tsx` | Vira layout: link de volta, título, badge de status, autor/data/motor, alerta de falha, as abas e o `<Outlet>`. Mantém o `key` por `runId` |
| `$runId/index.tsx` | Redireciona: `succeeded`/`inconclusive` → `causal`; qualquer outro → `detalhes`. Os links que já apontam para `/execucoes/$runId` continuam valendo |
| `$runId/detalhes.tsx` | O conteúdo de hoje, sem mudança de comportamento: `RunDetails` (parâmetros, entradas, publicar) e o log ao vivo, com a invalidação do run quando o log termina |
| `$runId/causal.tsx` | A aba nova |

Abas: **Causal** (só em `succeeded`/`inconclusive`), **Elasticidade** (desabilitada, "em breve") e **Detalhes**. Quando o run termina enquanto se está em Detalhes, a aba Causal aparece; a tela não troca de aba sozinha.

### Dados (`web/src/lib/results.ts`)

- Tipos da seção `causal` do `results.json` v1 (`engine/results_schema.py`: `Causal`, `CausalEvent`, `EventSeries`…), só o que a tela usa.
- `resultsQuery(slug, runId)`, com `staleTime: Infinity`: o resultado de um run não muda.
- `REASON_LABEL`, os `reasons` em pt-BR:

| reason | Rótulo |
|---|---|
| `not_significant` | Não significativo |
| `illogical_direction` | Direção ilógica (KPI contra o investimento) |
| `poor_fit` | Ajuste ruim no pré-período |
| `analysis_failed` | A análise do evento falhou |
| `not_selected` | Superado por outro evento do mesmo período |
| `no_events_detected` | Nenhum evento de investimento detectado |
| `no_eligible_events` | Nenhum evento com dados suficientes para análise |
| `no_event_passed_gates` | Nenhum evento passou nos critérios de publicação |

  Reason desconhecido aparece cru (o código), sem quebrar a tela.
- Formatação com `Intl` em pt-BR: inteiros com milhar, percentuais com uma casa e sinal, moeda em R$, datas `dd/mm/aaaa`, p-valor `< 0,001` abaixo de 0,001.

### Aba Causal (`web/src/components/causal/`)

- **Resumo:** três números, eventos detectados (`events_detected.length`), publicados e rejeitados (contagem por `status`).
- **Lista de eventos** (à esquerda): canais (até 2 nomes, senão "N canais"), datas de `start`–`end` (no evento de `analysis_failed`, que sai com `start` `null`, a data `AAAA-MM-DD` do fim do `id`, que o motor monta como `{anunciante}_{canais}_{data}`) e, no publicado, o `lift.rel_pct`. O filtro padrão é "Publicados"; "Todos" mostra também os rejeitados, esmaecidos e com o primeiro motivo. O primeiro publicado vem selecionado. A seleção fica no estado do componente, não na URL.
- **Detalhe do evento publicado** (à direita):
  - título com canais e período, badge "Publicado";
  - veredito: "Aumento/Queda significativo(a) de {lift.abs} no KPI ({rel_pct}), IC 95% [{ci}], p {p_value}". O sinal vem do `lift.abs`;
  - três cards: Lift (abs e %), Investimento incremental (`incremental_investment`), CPA incremental (`cpa_incremental`);
  - **linha:** `series.line`, KPI real × contrafactual (`forecasted_kpi`), investimento no segundo eixo, faixa `start`–`end` sombreada;
  - **barras:** `series.investment` (pré × evento) e `series.kpi` (previsto × real), lado a lado;
  - **Qualidade do ajuste**, recolhida: R², MAE e MAPE de `fit` e o gráfico de `series.accuracy` (KPI × previsto no pré-período).
  - Campo `null` vira "—"; série vazia some com o gráfico.
- **Detalhe do evento rejeitado:** canais, período, badge "Rejeitado" e a lista de motivos. Nenhum número.

Estados da aba:

| Situação | Tela |
|---|---|
| `causal` é `null` | "Sem análise causal nesta execução." |
| `causal.status` `inconclusive` ou `failed` | Alerta "Análise causal inconclusiva" com os `reasons` traduzidos; a lista de eventos aparece se houver eventos |
| Nenhum publicado, há rejeitados | Lista vazia com "Nenhum evento publicado. Ver todos" |
| Erro ao buscar o resultado | "Não foi possível carregar o resultado." |

Componente novo do shadcn: `chart` (`bunx shadcn@latest add chart`, traz o `recharts`). As cores das séries vêm do tema (`--chart-1…5` em `web/src/index.css`).

### Testes

- `web/e2e/results.spec.ts`, com `FAKE_ENGINE_RESULTS` apontando para a Gol no `playwright.config`:
  1. analyst roda a simulação, abre o run e cai na aba Causal com 52 detectados, 5 publicados e 47 rejeitados;
  2. o primeiro publicado está selecionado, com o veredito e o gráfico de linha;
  3. "Todos" lista os rejeitados; clicar num deles mostra o motivo e nenhum "R$" nem "%" no painel;
  4. a aba Detalhes mostra o log;
  5. viewer abre o run publicado e vê a Causal.
- Os specs do B4 e do B6 que abrem o run continuam passando (o redirect leva para a aba certa).
- Screenshots nos dois temas: Gol (publicado e rejeitado) e `gol_inconclusiva` (estado inconclusivo, rodando a API com o fixture trocado).

## Docs no mesmo commit

- `API-GUIDE.md`: a rota na tabela.
- `docs/m2/trilha-b-plataforma.md`: `Status` do B5 vira "parte 1 (Causal) feita", com o que foi verificado e o que falta.
- `CLAUDE.md` › Estado atual.
- `docs/decisoes/dashboards.md` (novo) e a linha no `docs/decisoes/README.md`.
- `.superpowers/` no `.gitignore`.
