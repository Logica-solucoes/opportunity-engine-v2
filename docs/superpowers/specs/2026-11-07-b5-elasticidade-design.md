# B5 (parte 2) · Dashboard Elasticidade — design

Data: 07/nov/2026. Item: B5 em `docs/m2/trilha-b-plataforma.md`. Depende do A8 (`engine.scenario`, banda, `extrapolated`, `ramp`, rota `GET /api/w/{slug}/runs/{run_id}/scenario`) e da parte 1 (abas do run, `resultsQuery`, `chart` do shadcn), ambos no `main`.

## Objetivo e recorte

A aba **Elasticidade** da página do run, hoje desabilitada, passa a mostrar o planner: filtros mensais à esquerda e, à direita, a tabela Atual / Recomendado / Saturação com os degraus, a curva de saturação com banda e extrapolação, as curvas de iCPA e receita/ROAS, o mix por canal e as curvas por canal. Toda conta fica em Python (`engine.scenario`); o front formata, compara status e escolhe o que mostrar. Um plano só (motor, API e telas).

| Fora | Volta quando |
|---|---|
| Card do experiment design no run inconclusivo | A7 |
| Selo de grounding e relatório do Gemini | A9 |
| Filtros na URL | Quando o B7 (export) ou alguém pedir link com filtro |
| Paridade pixel a pixel com o Streamlit | Não volta (`docs/decisoes/dashboards.md`) |

## Decisões

1. **Elasticidade não `ok` não mostra número, e o motor recusa.** Com `elasticity.status` `inconclusive` ou `failed`, o `engine.scenario` levanta `EngineError` e a rota devolve 409. A tela mostra só o alerta com os `reasons` em pt-BR. Hoje a Gol (`no_identifiable_channel`) sai com curva, recomendado e saturação de R$ 4,69 mi/mês vindos de canais que o motor não identificou; é a mesma regra do evento rejeitado e atende ao aceite "nenhum número de canal não identificável na tela".
2. **Tudo mensal, calculado no motor.** As curvas por canal e o mix estão no `results.json` na unidade do período; o `scenario` passa a devolvê-los já escalados pelo mesmo fator do agregado (`DAYS_PER_MONTH / period_days`). O front não multiplica nada.
3. **Mix com as três séries mesmo com a realocação suprimida.** Com `metrics.reallocation_suppressed`, o gráfico de mix mostra histórico, otimizado e estratégico com um aviso em cima ("O motor não confia na redistribuição entre canais desta execução"), em vez de esconder o otimizado.
4. **Layout com filtros num painel à esquerda**, como a sidebar do Streamlit e a coluna de eventos da aba Causal.

As quatro entram em `docs/decisoes/dashboards.md`.

---

## Motor (`engine/scenario.py`)

### Recusa

Logo no começo de `scenario()`: se `(results.get("elasticity") or {}).get("status") != "ok"`, `raise EngineError(NOT_CONCLUSIVE)`, com `NOT_CONCLUSIVE = "A análise de elasticidade desta execução não é conclusiva; não há cenário para simular."`. O `NO_CURVE` continua para curva vazia ou incompleta em elasticidade `ok`.

### `channels` (novo no retorno)

Uma entrada por canal de `elasticity.channels` com `identifiable` verdadeiro e `curve` não vazia, na ordem do `results.json`:

```
{
  "name": str,
  "curve": [{"investment", "kpi", "kpi_lo", "kpi_hi", "extrapolated"}],   # x, y, lo, hi × fator
  "observed_range": [lo, hi] | None,                                       # observed_spend_range × fator
  "current": float | None,                                                 # mix.historical[name] da linha da curva agregada mais próxima do atual × fator
  "saturation": float | None                                               # investimento do _saturation_index na curva do canal, a partir de 0
}
```

Canal não identificável não entra (o nome e os motivos a tela lê do `results.json`). **Primeiro passo do plano:** confirmar em `engine/results.py` e `engine/elasticity_analysis.py` que `ChannelFit.curve.x/y`, `observed_spend_range` e `response_curve[].mix` estão na mesma unidade de `response_curve[].investment`; se não estiverem, o fator do canal muda e a spec é corrigida antes do código. O `current` do canal sai do mix histórico da linha da curva agregada cujo `investment` é o mais próximo do atual (seleção, não interpolação); se o plano achar fonte melhor no `results.json` (ex.: um campo de gasto atual por canal), usa a fonte e anota aqui.

### `mix` nas linhas da tabela

`recommended` e `saturation` ganham `mix`: o `mix` da linha da curva de onde vieram (`{"historical"|"optimized"|"strategic": {canal: valor × fator}}`, `None` preservado). `current` não ganha (o mix atual é o histórico, já em `channels[].current`). Para isso `_curve_row` passa a carregar o `mix` escalado e `_table_row` o repassa; a `curve` devolvida também passa a ter `mix` por linha (custo pequeno, a tela não usa).

### Testes (`tests/engine/test_scenario.py`)

- Elasticidade `inconclusive` e `failed` → `EngineError` com `NOT_CONCLUSIVE`; `ok` com curva vazia continua `NO_CURVE`.
- `channels`: só os identificáveis; `curve`, `observed_range` e `current` escalados pelo fator (documento à mão com `period_days` conhecido); `saturation` cai num ponto da curva do canal.
- `mix` em `recommended` e `saturation`, escalado, com `None` preservado.
- O `identificavel.json` roda sem erro e devolve só `STRONG` em `channels`.

## API

Sem rota nova. `GET /api/w/{slug}/runs/{run_id}/scenario` já traduz `EngineError` em 409. Teste novo em `tests/api/`: o `scenario` de um run com o `gol_anonimizada.json` responde 409 com a mensagem `NOT_CONCLUSIVE`. O `API-GUIDE.md` ganha, na linha da rota, o 409 de elasticidade não conclusiva e os campos `channels` e `mix`.

---

## Telas

### Rota

`web/src/routes/_auth/w/$slug/execucoes/$runId/elasticidade.tsx`. A aba **Elasticidade** fica habilitada nos mesmos status da Causal (`succeeded`, `inconclusive`); o índice continua redirecionando para a Causal. Viewer vê o run publicado, como nas outras abas.

### Dados (`web/src/lib/scenario.ts`)

- Tipos do retorno do `scenario` (só o que a tela usa) e dos campos de `elasticity` lidos do `results.json` (`status`, `reasons`, `metrics`, `channels[].name/identifiable/reasons`).
- `scenarioQuery(slug, runId, filters)`, com `placeholderData: keepPreviousData` e `staleTime: Infinity` (mesmo run e mesmos filtros dão o mesmo resultado). Os filtros vão como query string; campo vazio não vai.
- Debounce de 200 ms entre o estado dos filtros e a chave da query (um `useDebouncedValue` de poucas linhas, sem lib nova).
- Rótulos pt-BR: em `REASON_LABELS` (`web/src/lib/results.ts`) entram `no_identifiable_channel` ("Nenhum canal com efeito identificável"), `cv_in_sample` ("Poucos períodos para validar o modelo fora da amostra"), `model_failed` ("O modelo de elasticidade falhou"), `coef_ci_includes_zero` ("O intervalo do efeito inclui zero"), `coef_ci_too_wide` ("O intervalo do efeito é largo demais") e `collinearity` ("Investimento colinear com outro canal"). Reason desconhecido continua aparecendo cru.

### Aba (`web/src/components/elasticity/`)

Grade `md:grid-cols-[18rem_minmax(0,1fr)]`, como a Causal.

**Painel de filtros (esquerda), valores mensais:**
- Orçamento: `slider` do shadcn com dois pontos (`bunx shadcn@latest add slider`), limites = `investment` da primeira e da última linha da curva da primeira resposta sem filtro, e os valores em R$ abaixo.
- CPA máx, iCPA máx, KPI mín, % de incrementalidade mín (`Input` numérico).
- ROAS mín e iROAS mín só com `revenue_mode`.
- "Limpar" volta tudo a vazio.
- Estado no componente. Erro 422 de filtro (ex.: mínimo acima do máximo) aparece embaixo do painel com a mensagem do pydantic, sem apagar o resultado anterior.

**Conteúdo (direita), nesta ordem:**
1. **Banner** "Baixa confiança" quando `metrics.low_confidence`, com o CV R² formatado.
2. **Tabela** Atual / Recomendado / Saturação. Linhas: investimento, KPI com "p5–p95" abaixo, CPA, iCPA, ROAS e iROAS (só em modo receita), investimento incremental, KPI incremental. Selo "extrapolado" na coluna cujo ponto tem `extrapolated`. Com `ramp`, um botão "N degraus" na coluna abre a lista (degrau, investimento, KPI com faixa). As `notes` aparecem abaixo da tabela, sem repetir. `recommended` `null` → a coluna diz "Nenhum ponto da curva atende aos filtros".
3. **Curva de saturação** (investimento × KPI): banda `kpi_lo`–`kpi_hi` como área, linha cheia no trecho observado e tracejada no extrapolado (duas séries separadas pelo `extrapolated` de cada ponto), pontos com `in_filter` falso esmaecidos, e marcadores em Atual, Recomendado e Saturação.
4. **iCPA** × investimento e, em modo receita, **receita e ROAS** × investimento, lado a lado.
5. **Mix por canal**: barras agrupadas (histórico, otimizado, estratégico) no ponto recomendado, ou no de saturação sem recomendado. Com `reallocation_suppressed`, o aviso em cima.
6. **Canais**: pequenos múltiplos com a curva de cada canal de `channels` (banda, tracejado no extrapolado, `observed_range` sombreada) e um gráfico de barras atual × saturação por canal. Abaixo, os canais não identificáveis (do `results.json`) só com o nome e os motivos traduzidos, sem número.

Campo `null` vira "—"; série vazia some com o gráfico. Cores das séries vêm de `--chart-1…5`.

**Estados da aba:**

| Situação | Tela |
|---|---|
| `elasticity` é `null` | "Sem análise de elasticidade nesta execução." (sem chamar o `scenario`) |
| `elasticity.status` não é `ok` | Alerta "Análise de elasticidade inconclusiva" com os `reasons` traduzidos; sem chamar o `scenario` e sem número |
| `scenario` responde 409 mesmo assim | O mesmo alerta, com a mensagem da API |
| Outro erro | "Não foi possível carregar o cenário." |

## Testes

- `tests/engine/test_scenario.py` e o teste de API acima.
- `web/e2e/elasticity.spec.ts`:
  1. Com a Gol (o `FAKE_ENGINE_RESULTS` de hoje): a aba Elasticidade mostra o alerta com "Nenhum canal com efeito identificável" e nenhum "R$".
  2. Caso feliz com `page.route` servindo `tests/fixtures/results/identificavel.json` em `…/results` e `tests/fixtures/results/identificavel_scenario.json` em `…/scenario` (gerado pelo `generate_fixtures.py` chamando `engine.scenario` sem filtro): tabela com as três colunas, banner de baixa confiança, curva visível, aviso no mix, curva de `STRONG` e `NOEFFECT` só com o motivo.
  3. Mexer num filtro dispara uma nova chamada ao `scenario` com o parâmetro na query string.
- Os specs do B4, B6 e da Causal continuam passando.
- Manual: screenshots nos dois temas (Gol inconclusiva e `identificavel`) e o slider respondendo em < 500 ms com a API real (DevTools, run do `identificavel`).

## Docs no mesmo commit

- `docs/decisoes/dashboards.md`: as quatro decisões acima.
- `API-GUIDE.md`: 409 e campos novos do `scenario`.
- `docs/m2/trilha-b-plataforma.md`: `Status` do B5 com o que foi verificado e o que falta (A7, A9).
- `CLAUDE.md` › Estado atual.
