# B7 · Export CSV e PDF — design

Data: 08/nov/2026. Item: `docs/m2/trilha-b-plataforma.md` § B7. Depende do B5 (pronto).

## Objetivo

O analista leva os números de um run para fora da plataforma: CSV dos eventos, dos cenários e da curva, e PDF das abas Causal e Elasticidade. Aceite da trilha: o PDF de um run publicado sai legível em A4, sem cortar gráfico.

## Decisões

| Pergunta | Decisão |
|---|---|
| O CSV da Elasticidade segue os filtros da tela? | Sim. A rota recebe os mesmos filtros do `scenario` e gera o CSV a partir do `engine.scenario`; o arquivo bate com a tabela e o gate de elasticidade (409) vale sem código novo. |
| Como entregar os CSVs? | Um botão por aba, uma rota GET por arquivo, como o `usage.csv`. Sem zip. |
| O que o PDF imprime? | A aba aberta, por `window.print()` e CSS `@media print`. No lugar do painel de filtros, um resumo dos filtros aplicados. |
| Grounding no cabeçalho? | Só quando o `results.json` tiver a seção (A9). Com `null`, a linha não aparece: o PDF não afirma um grounding que ninguém avaliou. |
| Quem exporta? | O mesmo acesso do `results`: viewer+, e viewer só em run publicado. |
| Evento rejeitado no CSV? | Entra com veredito e motivo; as colunas de número ficam vazias (regra do `dashboards.md`). |

## API

```text
GET /api/w/{slug}/runs/{run_id}/events.csv
GET /api/w/{slug}/runs/{run_id}/scenario.csv?<filtros do scenario>
GET /api/w/{slug}/runs/{run_id}/curve.csv?<filtros do scenario>
```

- **Acesso:** `viewer` + `find_run`, como `GET …/results` (escopo por workspace e visibilidade de publicado). Outro workspace ou run invisível → 404.
- **Erros:** run sem `results.json` → 404, como o `results`. Sem seção `causal` → 404 no `events.csv`. Os dois da Elasticidade chamam `engine.scenario` com os mesmos `ScenarioFilters` da rota `scenario` (mesma dependência de query): elasticidade recusada ou sem curva → 409 com a mensagem do motor, filtro inválido → 422.
- **Resposta:** `text/csv; charset=utf-8`, `Content-Disposition: attachment; filename="execucao-{run_id}-{eventos|cenarios|curva}.csv"`.
- **Código:** `api/exports.py` com funções puras de documento → texto CSV (`events_csv(results)`, `scenario_csv(answer)`, `curve_csv(answer)`); as rotas em `api/routes/runs.py` só buscam o run, leem o documento e devolvem o anexo. O escritor pt-BR do `usage.py` (`;`, vírgula decimal, BOM, `safe()` contra fórmula no Excel) sobe para `api/csvfile.py` e serve aos dois.

### Colunas

Cabeçalhos em pt-BR, com os mesmos rótulos da tela. Valores mensais na Elasticidade, como a tela. Número vazio quando o campo é `null`. Booleano como `sim`/`não`.

- **`eventos.csv`**, uma linha por evento de `causal.events`: Evento, Canais (separados por ` + `), Início, Fim, Veredito (`publicado`/`rejeitado`), Motivos (rótulos pt-BR separados por ` · `), Lift, Lift IC inferior, Lift IC superior, Lift %, p-valor, Variação do investimento %, Investimento incremental, CPA incremental, R², WMAPE, Placebo p-valor, Robustez p-valor. Evento rejeitado: só Evento, Canais, Início, Fim, Veredito e Motivos.
- **`cenarios.csv`**, uma linha por cenário (Atual, Recomendado, Saturação; Recomendado ausente quando nenhum ponto passa no filtro): Cenário, Investimento, KPI, KPI p5, KPI p95, Receita, CPA, ROAS, Investimento incremental, KPI incremental, iCPA, iROAS, Extrapolado, Notas. ROAS, iROAS e Receita só em modo receita. Depois de uma linha em branco, a rampa: Cenário, Degrau, Investimento, KPI, KPI p5, KPI p95, para cada cenário com `ramp`.
- **`curva.csv`**, um ponto por linha: Investimento, KPI, KPI p5, KPI p95, Receita, CPA, iCPA, ROAS, iROAS, Investimento incremental, KPI incremental, % incrementalidade, Extrapolado, No filtro. Receita, ROAS e iROAS só em modo receita.

Os rótulos de motivo (`REASON_LABELS` do front) precisam existir também em Python para o `eventos.csv`; o módulo do export guarda a tabela dos motivos causais, e um teste confere que ela cobre todo motivo que o motor emite.

## Tela

```text
<RunPage> ($runId.tsx)
  <PrintHeader>  hidden print:block — workspace, simulação, Execução #N, data, status, motor vX,
                 grounding só quando existir
  navegação do app e abas: print:hidden
  <CausalTab>
    barra: [Baixar CSV] [Imprimir / PDF]                 print:hidden
  <ElasticityTab>
    barra: [Cenários CSV] [Curva CSV] [Imprimir / PDF]   print:hidden
    <FiltersPanel>     print:hidden
    <FiltersSummary>   hidden print:block — "Orçamento R$ x – R$ y · CPA máximo R$ z…" ou "Sem filtros"
```

- **Download:** `<a href download>` para a rota, com os filtros na query (o estado atual, sem debounce). Sem fetch nem Blob. Elasticidade recusada não tem planner, logo não tem botões; Causal sem eventos não mostra o CSV.
- **Impressão:** `window.print()` e as variantes `print:` do Tailwind; nada novo no `package.json`.
  - `@page { size: A4; margin: 12mm }` em `index.css`.
  - Na impressão o grid do planner vira uma coluna e cada gráfico, tabela e card leva `break-inside: avoid`.
  - Tema claro forçado na impressão (fundo branco, texto escuro), mesmo com o app no escuro.
  - A aba Causal é mestre-detalhe: imprime a lista de eventos e o evento selecionado. Para outro evento, o analista o seleciona e imprime de novo. Imprimir todos os detalhes exigiria renderizar gráficos escondidos na tela, que o Recharts não mede.
  - Risco: o `ResponsiveContainer` do Recharts pode não redimensionar entre o layout da tela e o da impressão. O E2E com `page.pdf` confere; se cortar, o contêiner dos gráficos ganha uma largura máxima que cabe em A4 também na tela.

## Testes

- **pytest (`tests/api/test_exports.py`):** os três CSV com BOM, `;`, vírgula decimal e cabeçalho; evento rejeitado sem números; filtros chegam ao `scenario.csv`/`curve.csv` (Recomendado muda com `target_cpa`); 404 sem results e de outro workspace; viewer em run não publicado → 404; a Gol → 409 nos dois da Elasticidade; filtro inválido → 422; `safe()` num nome de canal começando com `=`. Funções de `api/exports.py` testadas sem banco.
- **E2E (`web/e2e/export.spec.ts`):** o download de cada CSV (nome do arquivo e cabeçalho); `page.emulateMedia({ media: 'print' })` com o cabeçalho visível, painel de filtros escondido e resumo visível; `page.pdf({ format: 'A4' })` gravado em `test-results/` para conferir a olho que nenhum gráfico corta.

## Fora do escopo

Página de relatório com todas as abas num PDF só; zip; export para Slides/PowerPoint (fora do M2, `docs/m2/README.md`); o selo de grounding (A9).

## Docs no mesmo commit da conclusão

Três rotas na tabela do `API-GUIDE.md`; `docs/decisoes/dashboards.md` (export pela API com os filtros da tela, PDF por impressão da aba, grounding só quando existir); Status do B7 na trilha B; "Estado atual" do `CLAUDE.md`.
