# A9 · Grounding do Gemini — design

Data: 08/nov/2026. Item: `docs/m2/trilha-a-motor.md` § A9. Depende de A5 e A6 (prontos). Inclui a parte de tela (B5) e o worker.

## Objetivo

Toda narrativa do Gemini que chega à tela só cita números e canais que o motor publicou. Texto que não passa na checagem, mesmo depois de uma regeneração, é trocado pelo texto determinístico. Sem chave de API, o run termina com o texto determinístico.

## Decisões

| Pergunta | Decisão |
|---|---|
| De onde sai a narrativa? | De um módulo novo, `engine/narratives.py`, que roda depois do `build_results` e lê o `ResultsV1`. Os números do payload são os mesmos da tela. |
| Os prompts do protótipo ficam? | Não. O payload deles (tabela de apresentação, matriz de correlação, `SATURATION_CURVE.md`) tem centenas de números e deixaria o checador permissivo. |
| HTML legado por LLM (`report_*.html`, `global_report.html`)? | Sai do run. A plataforma nunca leu esses arquivos, e manter as duas gerações dobraria as chamadas. O `RECOMMENDATIONS.md` por evento continua, agora com o texto determinístico novo. |
| Quem ganha narrativa? | Cada evento `published` e o global (quando há seção `elasticity`). Evento rejeitado não ganha: a tela já não mostra número dele. |
| Elasticidade não conclusiva? | O global recebe só `status` e `reasons` e só pode explicar o porquê. `elasticity.status == "failed"`: sem narrativa global por LLM, só a determinística. |
| Granularidade do bloqueio? | Por relatório. Um evento bloqueado não derruba os outros. `reports.grounding` resume o run. |
| Tolerância numérica? | Arredondamento da forma escrita: o número do texto passa se algum valor do payload, arredondado às casas e à escala usadas, der o mesmo número. |
| Temperatura? | `temperature=0` dentro do `GeminiLLM.generate_json`, como manda o `llm.md` (amostragem é do adaptador). |
| Worker? | O `launcher` deixa de forçar `LLM_PROVIDER=none`. Com `GEMINI_API_KEY`, o run da plataforma gera narrativa. |
| Nome do cliente no prompt? | Sai. O prompt leva o nome do KPI e o modo (receita/conversões), mais nada de identificação. |

## Payload

Montado a partir do `ResultsV1` e de `engine.scenario(results, ScenarioFilters())` (valores mensais, os mesmos da aba Elasticidade sem filtro).

- **Comum:** `kpi_name`, `revenue_mode`, `period_days`, `sufficiency.reasons`.
- **Evento publicado:** `channels`, `start`, `end`, `investment_change_pct`, `lift.abs`, `lift.ci`, `lift.rel_pct`, `p_value`, `incremental_investment`, `cpa_incremental`, `fit.r2`, `fit.wmape`, `placebo.p_value`, `robustness.p_value`.
- **Global:**
  - `elasticity.status` e `elasticity.reasons`.
  - `metrics`: `cv_r2`, `r2`, `media_contribution_pct`, `low_confidence`, `reallocation_suppressed`.
  - Canais identificáveis com `contribution_pct` e `hill.K`.
  - `unidentified_count`: só a contagem, sem nomes.
  - Cenários mensais do `scenario`: `current`, `recommended` e `saturation`, cada um com `investment`, `kpi`, `kpi_lo`, `kpi_hi`, `icpa`, e `roas`/`iroas` em modo receita.
  - Com status não `ok`, só `status`, `reasons` e `unidentified_count`.

O prompt instrui: pt-BR, usar só números do payload, não citar canal fora da lista, e, com status não `ok`, só explicar os motivos.

## Saída do LLM (`response_schema`)

- **Evento:** `{title: str, verdict: str, analysis: str, next_steps: [str] (1–3)}`.
- **Global:** `{title: str, summary: str, scenarios: [{name: str, analysis: str}], recommendations: [str] (1–3)}`.

O texto checado é a concatenação de todos os campos `str`.

## Checador (`engine/grounding.py`, funções puras)

`check(text, payload, published_channels, all_channels) -> list[Issue]`. Uma lista vazia significa que passou. Uma `Issue` é `{kind: "number"|"channel", value: str}`.

### Números

Extração por regex de: prefixo `R$` opcional, sinal, dígitos com `.` de milhar e `,` decimal, e um sufixo opcional entre `%`, `x`, `mil`, `k`, `M`, `mi`, `milhão`/`milhões`, `bi` e `bilhão`/`bilhões`.

Um número escrito `n`, com `d` casas e escala `s` (1, 1e3, 1e6 ou 1e9), passa se, para algum valor `v` folha do payload, valer `round(v / s, d) == n` com qualquer destas variantes:

- `v`;
- `|v|`;
- `v × 100` e `|v × 100|`, para frações escritas com `%` (`r2`, `wmape`).

Não são checados:

- datas no formato `dd/mm/aaaa` ou `aaaa-mm-dd`, desde que estejam no payload (`start` ou `end`);
- inteiros de 1 a 12 sem unidade e sem casa decimal, porque são contagens e ordinais. É um teto deliberado, marcado com `ponytail:`: um número inventado pequeno passa.

### Canais

O universo vem de `validation.channels` mais os nomes dos grupos. O conjunto publicado é formado pelos canais identificáveis (para o global) ou pelos canais do próprio evento. Todo canal do universo que esteja fora do conjunto publicado e apareça no texto (palavra inteira, sem diferenciar maiúsculas) gera uma issue.

Limite conhecido: canal que não existe nos dados (ex.: "Meta") não é detectado.

### Regeneração

Em caso de reprovação, uma segunda chamada vai com o mesmo prompt mais a lista de problemas ("estes números não estão nos dados: …; estes canais não podem ser citados: …"). Se reprovar de novo, o status fica `blocked`.

## Resultado no `results.json`

`reports` deixa de ser `null` quando o run chega ao `build_results`:

```text
reports.events[<event id>] = {source: "llm"|"deterministic", title, verdict, analysis, next_steps,
                              grounding: {status: "passed"|"regenerated"|"blocked", issues: [...]} | null}
reports.global             = {source, title, summary, scenarios, recommendations, grounding} | null
reports.grounding          = {status: <pior status entre os relatórios>, issues: [{report: <chave>, kind, value}]} | null
```

- `source: "deterministic"` com `grounding: null`: sem LLM, ou com o LLM indisponível naquele relatório.
- `source: "deterministic"` com `grounding.status = "blocked"`: o texto do LLM foi trocado. Os campos têm o texto determinístico, e as issues guardam o que reprovou.
- `reports.grounding` é `null` quando nenhum relatório passou pelo LLM. É ele que alimenta a linha "Grounding" do PDF.
- A ordem de gravidade dos status é `passed` < `regenerated` < `blocked`.
- O schema (`Reports`) fica como está, porque `events` e `global_` já são `dict[str, Any]` e `Grounding` já existe. Mudam só o comentário e o tipo `issues`.

### Texto determinístico

Vem de `narratives.deterministic_event(event, payload)` e `deterministic_global(payload)`, com os mesmos campos do LLM. Os números são formatados em pt-BR a partir do payload, então passam no checador por construção (um teste garante). Ele substitui o cálculo próprio de ROAS e iCPA do `recommendations.py`, que hoje diverge do `cpa_incremental` da tela. O `RECOMMENDATIONS.md` passa a ser escrito a partir dele.

### Falhas

- `LLMUnavailable` em qualquer chamada: as próximas param, e os relatórios restantes saem determinísticos com `grounding: null` (o mesmo comportamento de hoje).
- Outro `LLMError`, ou JSON fora do schema: a chamada conta como reprovada, sem issue de número, com `{kind: "output", value: <código>}`, e segue para a regeneração.
- Exceção inesperada dentro de `narratives` (payload ou texto determinístico): log `ERROR` com `exc_info` e `reports = null`. O run não falha por causa da narrativa. Erro do LLM fica dentro do relatório e cai no determinístico.

## Código

- `engine/grounding.py` (novo): extração e checagem.
- `engine/narratives.py` (novo): payload, prompts, schema, chamada com uma regeneração e texto determinístico. `build(document: dict, config, llm) -> dict` (recebe o dict sanitizado, não o `ResultsV1`).
- `engine/pipeline.py`: `run()` chama `narratives.build` depois do `build_results` e antes do `write_results`. Sai a chamada a `outputs.generate_reports`.
- `engine/outputs.py`: sai o `generate_reports`. O `RECOMMENDATIONS.md` por evento passa a usar o texto determinístico.
- `engine/reports.py`: removido (só servia ao HTML por LLM). Do `recommendations.py` sai a função antiga, e o módulo some se ficar vazio.
- `engine/logmessages.py`: sem mudança; as linhas novas já nascem em pt-BR.
- `llm/gemini.py`: `temperature=0` no `generate_json`.
- `api/launcher.py`: sai `LLM_PROVIDER=none` do `WORKER_ENV`.
- `web/src/lib/results.ts`: tipos de `reports` (`Narrative`, `GlobalNarrative`).
- `web/src/components/causal/EventDetail.tsx`: cartão "Análise" no evento publicado.
- `web/src/components/elasticity/ElasticityTab.tsx`: cartão "Análise" no topo.
- Nos dois cartões o texto é puro (o React escapa). O selo "Texto padrão" aparece quando `source == "deterministic"`, e o selo "Bloqueado pelo grounding" quando `grounding.status == "blocked"`.
- `PrintHeader`: já mostra a linha "Grounding" com `reports.grounding`. Falta conferir os rótulos.

## Testes

- `tests/engine/test_grounding.py`: textos fabricados.
  - Número inventado reprova.
  - Canal rejeitado e canal não identificável reprovam.
  - Arredondamento legítimo passa: `3,4M` para 3.412.000, `89,7%` para 0,8968, `-0,17x`, e `1.234` para 1234.
  - Datas do payload passam.
  - Inteiros pequenos passam.
- `tests/engine/test_narratives.py`, com o `FakeLLM`.
  - Cenários de fluxo: passa de primeira; regenera e passa (`regenerated`); reprova duas vezes (`blocked` com texto determinístico).
  - Indisponível: os relatórios restantes saem determinísticos com `grounding: null`.
  - Sem LLM: todos os relatórios saem determinísticos e `reports.grounding` fica `null`.
  - Conteúdo do prompt: não contém o nome de canal não identificável nem o do cliente.
  - O texto determinístico passa no checador.
- `tests/engine/test_reports.py`, `test_outputs*.py` e `test_run.py`: atualizados para o fim do HTML por LLM.
- `tests/api/test_worker_process.py`: o worker não força mais o `LLM_PROVIDER`.
- Os fixtures de `tests/fixtures/results/` são regenerados e saem com `reports` determinístico. O `test_results_fixtures.py` passa a exigir `reports`.
- E2E `results.spec.ts`: o evento publicado mostra o cartão "Análise" com o selo "Texto padrão" (o E2E roda sem chave).

## Fora do escopo

- Detectar canal inventado que não existe nos dados.
- Limite de chamadas ao Gemini por usuário (B11).
- Migrar `api/gemini.py` para `llm/` (pendência do Dev B, independente).
