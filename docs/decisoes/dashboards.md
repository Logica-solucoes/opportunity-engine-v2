# Dashboards

Por que a tela de resultado é do jeito que é. Itens do M2: B5.

## Recharts, não plotly.js (06/nov/2026)

O plano do B5 pedia portar os builders Plotly do Streamlit para plotly.js com a mesma aparência. Usamos o `chart` do shadcn (Recharts): ele já está no UI stack, pesa ~100 KB gz contra ~350 KB do plotly básico e herda o tema claro/escuro pelas variáveis `--chart-*`. O custo é a aparência: a paridade com o Streamlit passa a ser de conteúdo e número (mesmas séries, mesmos valores, mesmos rótulos), não de pixel.

## Evento rejeitado não mostra número (06/nov/2026)

O `results.json` traz `series` também dos eventos rejeitados, e a tela ignora. O BRD manda manter o que reprovou num gate fora dos dashboards, e um lift com aviso de "não publicável" acaba citado numa apresentação mesmo assim. A tela mostra canais, período e os motivos em pt-BR (`web/src/lib/results.ts`); reason novo do motor aparece como código até ganhar rótulo.

## Abas em subrotas do run (06/nov/2026)

`/execucoes/$runId` virou layout com `causal`, `detalhes` e, no futuro, `elasticidade`. O índice redireciona: run concluído ou inconclusivo abre na Causal, o resto em Detalhes (onde está o log). Quando o run termina com a pessoa em Detalhes, a aba Causal aparece, mas a tela não troca sozinha: quem está lendo o log não perde o lugar.

## O front não calcula

Lift, IC, `rel_pct`, CPA, investimento pré × evento e KPI previsto × real vêm prontos do motor. O front formata (`Intl` pt-BR), compara sinal (aumento × queda) e conta status. Se um número novo for preciso na tela, ele entra no `results.json`, não no TypeScript.
