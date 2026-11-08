# Dashboards

Por que a tela de resultado é do jeito que é. Itens do M2: B5 e B7.

## Recharts, não plotly.js (06/nov/2026)

O plano do B5 pedia portar os builders Plotly do Streamlit para plotly.js com a mesma aparência. Usamos o `chart` do shadcn (Recharts): ele já está no UI stack, pesa ~100 KB gz contra ~350 KB do plotly básico e herda o tema claro/escuro pelas variáveis `--chart-*`. O custo é a aparência: a paridade com o Streamlit passa a ser de conteúdo e número (mesmas séries, mesmos valores, mesmos rótulos), não de pixel.

## Evento rejeitado não mostra número (06/nov/2026)

O `results.json` traz `series` também dos eventos rejeitados, e a tela ignora. O BRD manda manter o que reprovou num gate fora dos dashboards, e um lift com aviso de "não publicável" acaba citado numa apresentação mesmo assim. A tela mostra canais, período e os motivos em pt-BR (`web/src/lib/results.ts`); reason novo do motor aparece como código até ganhar rótulo.

## Abas em subrotas do run (06/nov/2026)

`/execucoes/$runId` virou layout com `causal`, `detalhes` e, no futuro, `elasticidade`. O índice redireciona: run concluído ou inconclusivo abre na Causal, o resto em Detalhes (onde está o log). Quando o run termina com a pessoa em Detalhes, a aba Causal aparece, mas a tela não troca sozinha: quem está lendo o log não perde o lugar.

## Elasticidade não conclusiva não mostra número (07/nov/2026)

Com `elasticity.status` `failed` ou com `no_identifiable_channel`/`model_failed` nos motivos, o `engine.scenario` recusa (`NOT_CONCLUSIVE`, 409 na rota) e a aba mostra só o alerta com os motivos. Revisto em 08/nov/2026: `inconclusive` só por `cv_in_sample` (histórico curto, CV dentro da amostra) não recusa, porque os canais identificáveis seguem identificáveis; a aba mostra o planner sob um alerta "não validada" com o motivo. A Gol sai `inconclusive` por `no_identifiable_channel`, e a curva dela, com recomendado e saturação, vinha inteira de canais que o motor não identificou. É a regra do evento rejeitado aplicada à elasticidade, e o gate mora no motor para nenhum outro consumidor (export do B7) escapar dele.

## Tudo mensal, escalado no motor (07/nov/2026)

As curvas por canal, a faixa observada e o mix estão no `results.json` em valores diários do período. O `scenario` devolve tudo já em valores mensais, pelo mesmo `30 / period_days` do agregado; o gasto atual de cada canal é a participação histórica (constante ao longo da curva) × o investimento atual. A saturação de cada canal é procurada a partir do gasto atual dele, como a do agregado (08/nov/2026): procurada desde zero, podia cair abaixo do gasto atual e sugerir corte.

## Mix com as três séries mesmo com a realocação suprimida (07/nov/2026)

Com `metrics.reallocation_suppressed`, o gráfico de mix mostra histórico, otimizado e estratégico sob um aviso de que o motor não confia na redistribuição, em vez de esconder o otimizado. Decisão do time em 07/nov/2026: o analista prefere ver a hipótese marcada a perder a comparação.

## Filtros num painel à esquerda (07/nov/2026)

Como a sidebar do Streamlit e a lista de eventos da aba Causal: os filtros ficam sempre ao lado do que mudam. Ficam no estado do componente, não na URL, até alguém precisar de link com filtro.

## Eixo Y das curvas começa no dado (08/nov/2026)

A curva de saturação e as curvas por canal usam o domínio do dado no eixo Y, não o zero: o KPI incremental é pequeno perto do total (no sintético, +897 sobre ~197 mil) e, a partir do zero, a curva vira uma reta sem leitura. Os gráficos de barras (mix, atual × saturação) seguem a partir do zero.

## Export pela API, com os filtros da tela (08/nov/2026)

Os CSVs saem da API, não do navegador: `events.csv` do `results.json`, `scenario.csv` e `curve.csv` do `engine.scenario` com os mesmos filtros da tela, levados na query do link (`<a href download>`, sem fetch nem Blob). O arquivo bate com a tabela, o gate da elasticidade (409) vale sem código novo e o front segue sem conta. Evento rejeitado entra com veredito e motivos e os números vazios, pela mesma regra da tela. Os rótulos dos motivos de evento existem também em `api/exports.py`; como o motor não tem lista desses códigos, um teste prende a tabela ao `REASON_LABELS` de `web/src/lib/results.ts` e às fixtures reais. Números com vírgula decimal e sem separador de milhar, para o Excel pt-BR ler como número; só texto passa pelo `safe()`, porque um número negativo também começa com `-`. Um botão por arquivo, sem zip.

## PDF é a impressão da aba (08/nov/2026)

`window.print()` e `@media print`, sem biblioteca nem PDF no servidor: sai a aba aberta, em A4 com 12 mm de margem, sempre no tema claro (o `dark` só vale na tela), sem a navegação e com um cabeçalho de impressão (workspace, simulação, execução, data, status, motor). No lugar do painel de filtros da Elasticidade sai uma linha com os filtros aplicados. A aba Causal imprime a lista e o evento selecionado; imprimir o detalhe de todos exigiria renderizar gráficos escondidos, que o Recharts não mede. Na impressão o `main` tem a largura útil do A4 (186 mm): a impressão emulada (o E2E, o `page.pdf`) redesenha os gráficos nessa largura, e a do navegador, que não redesenha o Recharts, recebe os gráficos da tela, que já cabem (~664 px numa coluna do `max-w-5xl`, contra ~703 px úteis).

## Grounding no cabeçalho só quando existir (08/nov/2026)

O cabeçalho impresso mostra o grounding só quando o `results.json` traz `reports.grounding` (A9). Com `null` (nenhuma narrativa passou pelo LLM, por exemplo run sem `GEMINI_API_KEY`), a linha não aparece: o PDF não afirma um grounding que ninguém avaliou.

## Narrativa com selo de origem (08/nov/2026)

O cartão "Análise" aparece no evento publicado (aba Causal) e no topo da Elasticidade, com o texto de `reports`. Ele diz de onde veio: sem selo, o texto passou pelo LLM e pelo grounding; "Texto padrão" é o determinístico, montado pelo motor, sem nenhuma tentativa aprovada do LLM (sem chave ou LLM indisponível); "Bloqueado pelo grounding" é o determinístico depois de duas respostas do LLM citarem número ou canal fora do resultado. Ocultar o selo esconderia justamente o que o analista precisa saber antes de citar o texto. O cartão não aparece quando `reports` é `null` (erro interno do motor, ver `docs/decisoes/engine.md` › A9).

## O front não calcula

Lift, IC, `rel_pct`, CPA, investimento pré × evento e KPI previsto × real vêm prontos do motor. O front formata (`Intl` pt-BR), compara sinal (aumento × queda) e conta status. Se um número novo for preciso na tela, ele entra no `results.json`, não no TypeScript.
