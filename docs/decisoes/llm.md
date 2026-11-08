# LLM (`llm/`)

Decisões do A0, 04/nov/2026. Spec: `docs/superpowers/specs/2026-11-04-a0-pacote-engine-design.md` › Módulo LLM.

## Por que plugável, e só Gemini

O acesso ao modelo de linguagem estava acoplado ao SDK do Google em três pontos (`gemini_report.py`, duas chamadas, e `api/gemini.py`). A decisão do time é **implementar só o Gemini**, mas de modo que trocar de provedor no futuro seja escrever um arquivo, sem tocar no motor nem na API. O módulo é um pacote de topo (`llm/`), usado por `engine/` e `api/`; `llm/` não importa nenhum dos dois.

## Interface (`llm/base.py`)

```python
class LLM(Protocol):
    provider: str
    model: str
    def generate_text(self, prompt, *, timeout_s=None) -> str: ...
    def generate_json(self, prompt, schema, *, timeout_s=None) -> Any: ...   # já parseado; quem chama valida (pydantic)
```

Erros: `LLMError` (base), `LLMUnavailable(reason)` (sem chave, rede, timeout, cota, 5xx: tentar depois ou cair no texto determinístico), `LLMRefused` (recusa por política), `LLMBadOutput` (vazio ou JSON inválido).

**O que a interface não expõe, de propósito:** temperatura, esforço de raciocínio, seed, penalidades. São detalhes de cada provedor e ficam **dentro** do adaptador (alguns modelos nem aceitam esses parâmetros). Determinismo e segurança vêm do grounding da A9 e da validação pydantic de quem chama, que valem para qualquer provedor. `timeout_s` é geral e as chamadas têm limites diferentes (60 s nos relatórios, 20 s nas sugestões do B3).

## Seleção

`get_llm(provider=None, model=None) -> LLM | None`:

- `LLM_PROVIDER` (default `gemini`; `none` desliga) e `LLM_MODEL` (default do provedor: `gemini-flash-latest`). Cada provedor lê a própria chave (`GEMINI_API_KEY`).
- Devolve `None` quando o provedor é `none` ou falta a chave: o chamador cai no texto determinístico. Provedor desconhecido levanta `ValueError` (erro de configuração, não de run).
- Os testes do motor definem `LLM_PROVIDER=none` para a presença de uma chave no `.env` não afetar a paridade.

## `GeminiLLM` (`llm/gemini.py`)

Sobre `google-genai` (importado dentro do adaptador, para o pacote carregar sem o SDK). `generate_text` sem `temperature`; `generate_json` com `temperature=0` (A9, 08/nov/2026: a narrativa precisa ser a mesma a cada run). Mapeamento: sem chave, `429` (`rate_limited`), `500/503/504` (`http_<código>`), timeout e falha de conexão → `LLMUnavailable`; prompt bloqueado → `LLMRefused`; resposta vazia ou JSON inválido → `LLMBadOutput`; qualquer outro erro do SDK → `LLMError`. `generate_json` usa `response_mime_type="application/json"` + `response_json_schema` e tolera *code fence*.

O SDK antigo (`google-generativeai`) **não** foi adicionado: ele deixava um thread gRPC que travava o processo (origem do `os._exit(0)` do protótipo), o que deixaria o worker pendurado depois de terminar.

## Como o motor usa

`engine/narratives.py` chama `llm.generate_json(prompt, schema, timeout_s=60)`, com o `response_schema` vindo do pydantic (`EventNarrative`, `GlobalNarrative`), e valida a resposta com o mesmo modelo. `LLMUnavailable` **não** é embrulhado: o `narratives` a captura, avisa em pt-BR e deixa de chamar o LLM no resto do run (substitui o casamento de texto de `is_gemini_outage_error`). Outro `LLMError`, ou resposta fora do schema, reprova a tentativa como `output` e segue para a regeneração; a falha fica dentro do relatório e nunca derruba o run.

## Grounding (A9, 08/nov/2026)

Toda narrativa que chega à tela passa por `engine/grounding.py` antes de ser publicada:

- **Payload restrito.** O prompt recebe só o que o motor já publicou: lift, IC, p-valores, R², WMAPE, placebo e robustez do evento; status, motivos e curva mensal (`engine.scenario`, sem filtros) da elasticidade; a lista de canais que podem ser citados. Nada de CSV bruto nem dado de linha.
- **Números.** Todo número do texto (formato pt-BR: `R$ 3,4M`, `89,7%`, `-0,17x`, `1.234`, `3,41 milhões`) tem que casar com um valor do payload, arredondado com a mesma quantidade de casas escrita. Percentual casa também com a fração (`0,897` ↔ `89,7%`).
- **Datas.** `DD/MM/AAAA` (o prompt pede esse formato) ou por extenso (`20 de janeiro de 2025`): com ano, tem que ser um dia publicado; sem ano, qualquer dia publicado com o mesmo dia e mês. Data ISO no payload conta como publicada.
- **Canais.** Só canais publicados. Membro de grupo publicado conta como publicado. Um canal conhecido pelo run mas não publicado (não identificado, evento rejeitado) é reprovado.
- **Limites aceitos:** inteiro até 12 sem unidade nem casa decimal passa sem conferência (contagens como "3 canais"); um número derivado que não está no payload, como "28 dias" (duração do período, que o payload não traz), é reprovado; e um canal inventado que o run não conhece (ex.: "Meta" quando o run só tem "META") não é pego.
- **Regeneração.** Reprovado → uma nova chamada com a lista dos problemas no prompt. Reprovado de novo → `grounding.status = "blocked"` e o texto determinístico (`narratives.deterministic_event` / `deterministic_global`, montado só com números do payload, então passa no checador por construção).
- **Erro do LLM que não é resposta ruim nem recusa** (ex.: `http_400`) para as chamadas como indisponível: não vira `blocked`.
- **`temperature=0`** no `generate_json` (ver adaptador acima).
- **Sem chave** (`LLM_PROVIDER=none` ou sem `GEMINI_API_KEY`): `get_llm()` devolve `None`, nenhuma chamada, `grounding: null` e texto determinístico.
- **Worker liga o LLM.** O `api/launcher.py` não força mais `LLM_PROVIDER=none`. Com a chave no `.env` do servidor, o run chama o Gemini: até 2 chamadas por narrativa (uma por evento publicado e uma global), de até 60 s cada, e um orçamento total de `LLM_BUDGET_S` = 300 s, checado entre relatórios (pior caso ~420 s, dentro do watchdog de 20 min). Passado o orçamento, os relatórios restantes saem determinísticos.
- **Payload.** Floats arredondados a 4 algarismos significativos (sem `238.99107106472343%`), e o prompt traz a regra de formato pt-BR.

**Ceilings abertos (não corrigidos):**
- `abs()` deixa passar sinal invertido: "aumento de 31,1%" numa queda de mesmo módulo passa.
- Um percentual pode vir de uma razão não relacionada no payload e passar.
- Com `cv_in_sample`, o texto diz "não conclusiva" mesmo com a aba mostrando o planner (texto, não número).
- P-valor "0,0000" é cosmético, não reprovado.

**Verificado com chave real** (08/nov/2026, fixtures `gol_anonimizada` e `identificavel`, `narratives.build` com Gemini): antes das correções, 159 s, os 5 eventos inventaram números na primeira tentativa (ex.: "1,44") e só passaram na regeneração, com floats crus, e a global leu "12" como "12 registros não mapeados". Depois, 63 s, os 7 relatórios passaram na primeira tentativa, sem float cru e com "12 canais sem efeito identificável" correto.

Ainda pendente: `api/gemini.py` → `llm/` (abaixo). Qualidade do texto em outros datasets não foi medida.

## Como adicionar um provedor

1. `llm/<nome>.py` com uma classe que tenha `provider`, `model`, `generate_text`, `generate_json` e o classmethod `from_env(model) -> instância | None` (lê a própria chave e o modelo padrão).
2. Uma linha em `PROVIDERS` (`llm/__init__.py`) e a dependência no `pyproject.toml`.
3. Um teste com um cliente falso que passe `run_provider_contract` (`tests/fakes/llm.py`), como `tests/llm/test_gemini.py`.
4. Revisar a interface: ela foi desenhada com um provedor só e pode ter vazado algum detalhe dele.

## Para o Dev B

`api/gemini.py` (`ask(prompt, response_schema) -> str`, `Unavailable`) pode virar `get_llm().generate_json(prompt, schema, timeout_s=20)`, mapeando `LLMUnavailable` para o `available: false` de hoje; `suggestions.from_gemini` já valida item a item. Depois, renomear a rota `…/suggestions/gemini`, o `source: "gemini"` e o botão da tela para algo neutro (`ia`/`llm`), com migração do que o front espera. Nada disso foi feito no A0.
