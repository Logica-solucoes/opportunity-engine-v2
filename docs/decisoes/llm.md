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

Sobre `google-genai` (importado dentro do adaptador, para o pacote carregar sem o SDK). Sem `temperature` explícito. Mapeamento: sem chave, `429` (`rate_limited`), `500/503/504` (`http_<código>`), timeout e falha de conexão → `LLMUnavailable`; prompt bloqueado → `LLMRefused`; resposta vazia ou JSON inválido → `LLMBadOutput`; qualquer outro erro do SDK → `LLMError`. `generate_json` usa `response_mime_type="application/json"` + `response_json_schema` e tolera *code fence*.

O SDK antigo (`google-generativeai`) **não** foi adicionado: ele deixava um thread gRPC que travava o processo (origem do `os._exit(0)` do protótipo), o que deixaria o worker pendurado depois de terminar.

## Como o motor usa

`reports.py` chama `llm.generate_text(prompt, timeout_s=60)` e interpreta o JSON da narrativa onde sempre interpretou (a A9 passa a `generate_json` com `response_schema`). `LLMUnavailable` **não** é embrulhado em `RuntimeError`: o `run` a captura, avisa em pt-BR e deixa de chamar o LLM no resto do run (substitui o casamento de texto de `is_gemini_outage_error`); qualquer outro `LLMError` falha só aquele relatório, que cai no `RECOMMENDATIONS.md` determinístico.

## Como adicionar um provedor

1. `llm/<nome>.py` com uma classe que tenha `provider`, `model`, `generate_text`, `generate_json` e o classmethod `from_env(model) -> instância | None` (lê a própria chave e o modelo padrão).
2. Uma linha em `PROVIDERS` (`llm/__init__.py`) e a dependência no `pyproject.toml`.
3. Um teste com um cliente falso que passe `run_provider_contract` (`tests/fakes/llm.py`), como `tests/llm/test_gemini.py`.
4. Revisar a interface: ela foi desenhada com um provedor só e pode ter vazado algum detalhe dele.

## Para o Dev B

`api/gemini.py` (`ask(prompt, response_schema) -> str`, `Unavailable`) pode virar `get_llm().generate_json(prompt, schema, timeout_s=20)`, mapeando `LLMUnavailable` para o `available: false` de hoje; `suggestions.from_gemini` já valida item a item. Depois, renomear a rota `…/suggestions/gemini`, o `source: "gemini"` e o botão da tela para algo neutro (`ia`/`llm`), com migração do que o front espera. Nada disso foi feito no A0.
