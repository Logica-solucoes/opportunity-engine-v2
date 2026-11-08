# A9 · Grounding do Gemini — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Toda narrativa do Gemini que chega à tela só cita números e canais que o motor publicou; texto reprovado duas vezes é trocado pelo determinístico, e sem chave de API o run termina com o texto determinístico.

**Architecture:** Dois módulos novos e puros no motor. `engine/grounding.py` extrai números (formato pt-BR) e nomes de canal de um texto e os confere contra o payload. `engine/narratives.py` monta o payload a partir do `results.json` já publicado (mais o `engine.scenario` mensal), chama `llm.generate_json` com schema pydantic, checa, regenera uma vez e cai no texto determinístico. O `run()` grava o resultado em `results.json.reports`, e o HTML do protótipo por LLM sai. A plataforma liga o LLM no worker e a tela mostra a narrativa num cartão.

**Tech Stack:** Python 3.13, pydantic 2, pytest (uv); React 19, TanStack Query, shadcn, Playwright (bun). Nenhuma dependência nova.

**Spec:** `docs/superpowers/specs/2026-11-08-a9-grounding-design.md`. Leia também `CODE-STYLE.md`, `docs/decisoes/llm.md`, `docs/decisoes/engine.md` e `docs/decisoes/dashboards.md`.

**Decisões de leitura (verificadas ao escrever o plano):**
- **O documento, não o `ResultsV1`.** `engine.scenario` recebe o dict do `results.json`. Por isso `narratives.build(document: dict, config: EngineConfig, llm)` lê o dict já sanitizado (`dump_results`) e devolve o dict de `reports`. O `run()` revalida o documento com `ResultsV1.model_validate` depois de pôr o `reports`.
- **Schema por pydantic.** `EventNarrative` e `GlobalNarrative` (pydantic) dão o `response_schema` (`model_json_schema()`) e validam a forma da resposta. Uma resposta fora da forma conta como reprovação `{kind: "output", value: "bad_shape"}`.
- **Evento publicado = selecionado.** `selected` só é marcado em evento aprovado (`pipeline.analyze_events`), então os eventos `published` do documento são os mesmos que têm pasta em `Written.event_dirs`. O `RECOMMENDATIONS.md` sai para eles a partir do `reports`.
- **Fixtures sem rodar o motor.** `exemplo_csv/Gol` não existe nesta máquina, e o `generate_fixtures.py` precisa dele. Como `narratives.build` só lê o documento, um script novo (`tests/fixtures/results/add_reports.py`) preenche o `reports` nos JSON versionados com `llm=None`, que é exatamente o que o `generate_fixtures.py` gravaria. Na próxima regeneração completa o `engine.run` já inclui o `reports`.
- **`logmessages.py` fica como está.** As linhas novas já nascem em pt-BR (passam direto). As regras velhas dos HTMLs viram letra morta inofensiva. A spec dizia para tirá-las, mas isso é cosmético e mexe em `test_logmessages.py` sem ganho. Ajuste na Task 8.
- **Bug no próprio `narratives`.** Um erro de payload ou no texto determinístico (não do LLM) é pego no `run()`: log `ERROR` e `reports = null`, e o run não falha por narrativa. A spec dizia "relatórios determinísticos", mas se o determinístico quebrou não há o que mostrar. Ajuste na Task 8.

## Ordem e paralelismo

| Lote | Tarefas | Modelo sugerido |
|---|---|---|
| 1 | Task 1 (grounding), Task 3 (temperatura), Task 5 (launcher) | sonnet, haiku, haiku |
| 2 | Task 2 (narratives) | sonnet |
| 3 | Task 4 (pipeline e outputs), Task 6 (fixtures), Task 7 (tela) | sonnet, haiku, sonnet |
| 4 | Task 8 (docs e verificação final) | sonnet |

As Tasks 4, 6 e 7 tocam arquivos disjuntos. A Task 7 só precisa das fixtures da Task 6 no E2E (Step 7.6). Se rodar em paralelo, deixe o E2E para depois da Task 6.

---

### Task 1: Checador de grounding (`engine/grounding.py`)

**Files:**
- Create: `engine/grounding.py`
- Test: `tests/engine/test_grounding.py`

- [ ] **Step 1.1: Escrever os testes que falham**

```python
"""A9: the post-generation check. Fabricated texts against a payload the engine published."""

import pytest

from engine.grounding import check

PAYLOAD = {
    "lift": {"abs": -1234.4, "ci": [-2010.0, -458.7], "rel_pct": -31.08},
    "incremental_investment": 3_412_000.0,
    "fit": {"r2": 0.4567, "wmape": 0.8968},
    "iroas": -0.1712,
    "p_value": 0.0123,
    "ci_level_pct": 95,
    "start": "2025-01-20",
    "end": "2025-02-03",
}
UNIVERSE = {"CANAL_01", "CANAL_02", "CANAL_03"}


def _issues(text, published=frozenset({"CANAL_01"})):
    return check(text, PAYLOAD, set(published), UNIVERSE)


@pytest.mark.parametrize(
    "text",
    [
        "Investimento incremental de R$ 3,4M.",
        "Investimento incremental de R$ 3.412.000,00.",
        "Investimento incremental de 3,41 milhões.",
        "Queda de 1.234 no KPI.",
        "Queda de -1.234 no KPI.",
        "Variação de -31,1%.",
        "Variação de 31%.",
        "WMAPE de 89,7%.",
        "R² de 0,46.",
        "iROAS de -0,17x.",
        "p-valor 0,012.",
        "IC 95% [-2.010; -459].",
        "Entre 20/01/2025 e 2025-02-03, no ano de 2025.",
        "Três canais, 2 semanas e 12 meses.",
        "O CANAL_01 respondeu.",
    ],
)
def test_legitimate_rounding_passes(text):
    assert _issues(text) == []


@pytest.mark.parametrize(
    "text, value",
    [
        ("Investimento de R$ 5.000.", "R$ 5.000"),
        ("Investimento incremental de R$ 3,5M.", "R$ 3,5M"),
        ("Lift de 1.300 no KPI.", "1.300"),
        ("Alta de 40,2%.", "40,2%"),
        ("Em 21/01/2025 o investimento subiu.", "21/01/2025"),
        ("R² de 0,7.", "0,7"),
    ],
)
def test_an_invented_number_fails(text, value):
    assert _issues(text) == [{"kind": "number", "value": value}]


def test_a_channel_outside_the_published_set_fails_case_insensitively():
    assert _issues("O canal_02 e o CANAL_03 também.") == [
        {"kind": "channel", "value": "CANAL_02"},
        {"kind": "channel", "value": "CANAL_03"},
    ]


def test_a_channel_name_inside_another_word_is_not_a_mention():
    assert _issues("XCANAL_02 e CANAL_02X") == []


def test_numbers_inside_channel_names_are_not_numbers():
    assert check("O CANAL_06 subiu.", {}, {"CANAL_06"}, {"CANAL_06"}) == []
```

- [ ] **Step 1.2: Rodar e ver falhar**

Run: `uv run pytest tests/engine/test_grounding.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'engine.grounding'`)

- [ ] **Step 1.3: Implementar**

```python
"""Post-generation check of an LLM narrative (A9): every number it writes and every channel it names must come from
the payload the engine published. Pure functions over text."""

import re
from typing import Any

SCALES = {
    "mil": 1e3,
    "k": 1e3,
    "m": 1e6,
    "mi": 1e6,
    "milhão": 1e6,
    "milhões": 1e6,
    "milhao": 1e6,
    "milhoes": 1e6,
    "bi": 1e9,
    "bilhão": 1e9,
    "bilhões": 1e9,
    "bilhao": 1e9,
    "bilhoes": 1e9,
}
# pt-BR numbers: "R$ 3,4M", "-31,1%", "-0,17x", "1.234", "3,41 milhões". A dot followed by groups of 3 digits is a
# thousands separator; any other dot or comma is the decimal one.
NUMBER = re.compile(
    r"(?<![\w.,])(?P<sign>[-−+]?)\s?(?P<currency>R\$\s?)?(?P<sign2>[-−]?)"
    r"(?P<int>\d{1,3}(?:\.\d{3})+(?!\d)|\d+)(?:[,.](?P<dec>\d+))?"
    r"(?:\s?(?P<unit>%|x\b|(?i:milh(?:ões|ão|oes|ao)|bilh(?:ões|ão|oes|ao)|mil|mi|bi|k|m)\b))?"
)
DATE = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b|\b\d{4}-\d{2}-\d{2}\b")
ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
SMALL_COUNT = 12


def _leaves(obj: Any, numbers: list[float], days: set[str]) -> None:
    if isinstance(obj, dict):
        for value in obj.values():
            _leaves(value, numbers, days)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            _leaves(value, numbers, days)
    elif isinstance(obj, bool):
        return
    elif isinstance(obj, (int, float)):
        numbers.append(float(obj))
    elif isinstance(obj, str) and ISO_DAY.match(obj):
        days.add(obj[:10])
        numbers.append(float(obj[:4]))  # the year of a published date may be written on its own


def _matches(written: float, decimals: int, scale: float, percent: bool, numbers: list[float]) -> bool:
    tolerance = 0.5 * 10**-decimals + 1e-9  # the written number is the payload value rounded to the digits shown
    for value in numbers:
        candidates = [value, abs(value)] + ([value * 100, abs(value * 100)] if percent else [])
        if any(abs(c / scale - written) <= tolerance for c in candidates):
            return True
    return False


def check(text: str, payload: Any, published: set[str], universe: set[str]) -> list[dict]:
    """Issues found in `text`: numbers not in `payload` and channels of `universe` outside `published`. Empty = passed."""
    numbers: list[float] = []
    days: set[str] = set()
    _leaves(payload, numbers, days)
    issues: list[dict] = []

    def drop_date(m: re.Match) -> str:
        day = f"{m[3]}-{m[2]}-{m[1]}" if m[1] else m[0]
        if day not in days:
            issues.append({"kind": "number", "value": m[0]})
        return " "

    rest = DATE.sub(drop_date, text)
    for m in NUMBER.finditer(rest):
        decimals = len(m["dec"] or "")
        digits = m["int"].replace(".", "")
        written = float(f"{digits}.{m['dec']}" if m["dec"] else digits)
        unit = (m["unit"] or "").lower()
        # ponytail: small bare integers are counts and ordinals ("3 canais", "2 semanas"); an invented one passes
        if not unit and not m["currency"] and not decimals and written <= SMALL_COUNT:
            continue
        if any(s in "-−" for s in (m["sign"] + m["sign2"])):
            written = -written
        if not _matches(written, decimals, SCALES.get(unit, 1), unit == "%", numbers):
            issues.append({"kind": "number", "value": m[0].strip()})

    for name in sorted(universe - published):
        # ponytail: only channels the run knows; an invented one ("Meta") is not caught
        if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.IGNORECASE):
            issues.append({"kind": "channel", "value": name})
    return issues
```

- [ ] **Step 1.4: Rodar e ver passar**

Run: `uv run pytest tests/engine/test_grounding.py -q`
Expected: PASS. Um teste que falhe aqui indica erro no regex ou na tolerância. **Não** afrouxe a regra para fazê-lo passar. O `abs(value)` existe para "queda de 1.234" contra um lift de -1234,4; por isso um sinal positivo inventado sobre um valor negativo passa, e isso é aceito.

- [ ] **Step 1.5: Lint**

Run: `uv run ruff format engine/grounding.py tests/engine/test_grounding.py && uv run ruff check engine/grounding.py tests/engine/test_grounding.py`
Expected: sem erros

- [ ] **Step 1.6: Commit**

```bash
git add engine/grounding.py tests/engine/test_grounding.py
git commit -m "feat(engine): grounding check of llm narratives against the published numbers and channels"
```

---

### Task 2: Narrativas (`engine/narratives.py`)

**Files:**
- Create: `engine/narratives.py`
- Modify: `tests/fakes/llm.py:11-24` (narrativas no formato novo)
- Test: `tests/engine/test_narratives.py`

- [ ] **Step 2.1: Atualizar as narrativas do fake**

Em `tests/fakes/llm.py`, troque o bloco `EVENT_NARRATIVE`/`GLOBAL_NARRATIVE` por:

```python
# narratives in the A9 shape, with no number or channel, so they pass any grounding check
EVENT_NARRATIVE = {
    "title": "Relatório do evento",
    "verdict": "O investimento teve efeito no KPI.",
    "analysis": "O efeito passou nos critérios de publicação.",
    "next_steps": ["Acompanhar o próximo período."],
}
GLOBAL_NARRATIVE = {
    "title": "Elasticidade",
    "summary": "A análise de elasticidade não é conclusiva.",
    "scenarios": [],
    "recommendations": ["Coletar mais histórico."],
}
```

- [ ] **Step 2.2: Escrever os testes que falham**

```python
"""A9: narratives built from the published results.json, checked, regenerated once, or replaced."""

import json

from engine import grounding, narratives
from engine.config import EngineConfig
from llm.base import LLMBadOutput, LLMUnavailable
from tests.fakes.llm import EVENT_NARRATIVE, GLOBAL_NARRATIVE, FakeLLM

EVENT = {
    "id": "Adv_CANAL_01_2025-01-20",
    "channels": ["CANAL_01"],
    "status": "published",
    "reasons": [],
    "start": "2025-01-06",
    "end": "2025-02-03",
    "investment_change_pct": 62.5,
    "lift": {"abs": -1234.4, "ci": [-2010.0, -458.7], "rel_pct": -31.08},
    "p_value": 0.0123,
    "incremental_investment": 3_412_000.0,
    "cpa_incremental": 27.64,
    "fit": {"r2": 0.4567, "mae": 10.0, "mape": 5.0, "wmape": 0.123},
    "placebo": {"p_value": 0.62, "passed": True},
    "robustness": {"p_value": 0.01, "passed": True},
}
REJECTED = {**EVENT, "id": "Adv_CANAL_02_2025-03-01", "channels": ["CANAL_02"], "status": "rejected"}


def _document(elasticity=None, events=(EVENT, REJECTED)):
    return {
        "validation": {"ok": True, "period_days": 1, "channels": ["CANAL_01", "CANAL_02", "CANAL_03"]},
        "sufficiency": {"passed": True, "reasons": []},
        "causal": {"status": "ok", "reasons": [], "events": list(events)},
        "elasticity": elasticity,
    }


INCONCLUSIVE = {
    "status": "inconclusive",
    "reasons": ["no_identifiable_channel"],
    "channels": [
        {"name": "CANAL_01", "identifiable": False, "reasons": ["coef_ci_includes_zero"]},
        {"name": "CANAL_03", "identifiable": False, "reasons": ["coef_ci_includes_zero"]},
    ],
    "groups": [],
}
CONFIG = EngineConfig.from_input(
    {"column_mapping": {"performance_file": {"date_col": "date", "kpi_col": "Pedidos"}}}
)


def _build(document, llm):
    return narratives.build(document, CONFIG, llm)


def test_without_an_llm_every_report_is_deterministic_and_nothing_claims_a_grounding():
    reports = _build(_document(INCONCLUSIVE), None)
    assert set(reports["events"]) == {EVENT["id"]}  # a rejected event gets no narrative
    event = reports["events"][EVENT["id"]]
    assert event["source"] == "deterministic" and event["grounding"] is None
    assert "Queda de 1.234 em Pedidos" in event["verdict"]
    assert reports["global"]["source"] == "deterministic"
    assert "nenhum canal tem efeito identificável" in reports["global"]["summary"]
    assert reports["grounding"] is None


def test_the_deterministic_texts_pass_their_own_grounding():
    document = _document(INCONCLUSIVE)
    universe = narratives.universe(document)
    payload = narratives.event_payload(EVENT, "Pedidos", 0.05, [])
    text = narratives.text_of(narratives.deterministic_event(payload))
    assert grounding.check(text, payload, {"CANAL_01"}, universe) == []
    payload = narratives.global_payload(document, CONFIG, "Pedidos", False)
    text = narratives.text_of(narratives.deterministic_global(payload))
    assert grounding.check(text, payload, set(), universe) == []


def test_a_grounded_answer_passes_at_the_first_try():
    llm = FakeLLM([json.dumps(EVENT_NARRATIVE), json.dumps(GLOBAL_NARRATIVE)])
    reports = _build(_document(INCONCLUSIVE), llm)
    event = reports["events"][EVENT["id"]]
    assert event == {"source": "llm", **EVENT_NARRATIVE, "grounding": {"status": "passed", "issues": []}}
    assert reports["grounding"] == {"status": "passed", "issues": []}
    assert len(llm.calls) == 2 and llm.timeouts == [narratives.TIMEOUT_S] * 2


def test_an_invented_number_is_regenerated_with_the_issues_in_the_prompt():
    invented = {**EVENT_NARRATIVE, "analysis": "Ganho de R$ 9.999."}
    llm = FakeLLM([json.dumps(invented), json.dumps(EVENT_NARRATIVE), json.dumps(GLOBAL_NARRATIVE)])
    reports = _build(_document(INCONCLUSIVE), llm)
    event = reports["events"][EVENT["id"]]
    assert event["source"] == "llm"
    assert event["grounding"] == {"status": "regenerated", "issues": [{"kind": "number", "value": "R$ 9.999"}]}
    assert "R$ 9.999" in llm.calls[1] and "R$ 9.999" not in llm.calls[0]
    assert reports["grounding"]["status"] == "regenerated"
    assert reports["grounding"]["issues"] == [{"report": EVENT["id"], "kind": "number", "value": "R$ 9.999"}]


def test_failing_twice_blocks_the_report_and_keeps_the_deterministic_text():
    hidden = {**EVENT_NARRATIVE, "analysis": "O CANAL_02 também ajudou."}
    llm = FakeLLM([json.dumps(hidden), json.dumps(hidden), json.dumps(GLOBAL_NARRATIVE)])
    reports = _build(_document(INCONCLUSIVE), llm)
    event = reports["events"][EVENT["id"]]
    assert event["source"] == "deterministic" and "Queda de 1.234" in event["verdict"]
    assert event["grounding"] == {"status": "blocked", "issues": [{"kind": "channel", "value": "CANAL_02"}]}
    assert reports["grounding"]["status"] == "blocked"
    assert reports["global"]["grounding"]["status"] == "passed"  # one blocked report does not take the others


def test_an_answer_out_of_shape_counts_as_a_failed_try():
    llm = FakeLLM([json.dumps({"title": "só o título"}), LLMBadOutput("invalid_json"), json.dumps(GLOBAL_NARRATIVE)])
    event = _build(_document(INCONCLUSIVE), llm)["events"][EVENT["id"]]
    assert event["grounding"] == {"status": "blocked", "issues": [{"kind": "output", "value": "invalid_json"}]}


def test_an_unavailable_llm_stops_the_calls_and_the_rest_is_deterministic():
    llm = FakeLLM([LLMUnavailable("timeout")])
    reports = _build(_document(INCONCLUSIVE), llm)
    assert len(llm.calls) == 1
    assert reports["events"][EVENT["id"]]["grounding"] is None
    assert reports["global"]["source"] == "deterministic" and reports["global"]["grounding"] is None
    assert reports["grounding"] is None


def test_the_prompts_never_name_a_hidden_channel_nor_the_client():
    config = EngineConfig.from_input(
        {"column_mapping": CONFIG.column_mapping, "advertiser_name": "ClienteSecreto"}
    )
    llm = FakeLLM([json.dumps(EVENT_NARRATIVE), json.dumps(GLOBAL_NARRATIVE)])
    narratives.build(_document(INCONCLUSIVE), config, llm)
    event_prompt, global_prompt = llm.calls
    assert "ClienteSecreto" not in event_prompt + global_prompt
    assert "CANAL_02" not in event_prompt  # rejected event
    assert "CANAL_01" not in global_prompt and "CANAL_03" not in global_prompt  # not identifiable
    assert '"unidentified_count": 2' in global_prompt


def test_a_failed_elasticity_gets_no_llm_call():
    failed = {"status": "failed", "reasons": ["model_failed"], "channels": [], "groups": []}
    llm = FakeLLM([json.dumps(EVENT_NARRATIVE)])
    reports = _build(_document(failed), llm)
    assert len(llm.calls) == 1
    assert reports["global"]["source"] == "deterministic"
    assert "o modelo de elasticidade falhou" in reports["global"]["summary"]


def test_no_elasticity_section_means_no_global_report():
    assert _build(_document(None), None)["global"] is None
```

- [ ] **Step 2.3: Rodar e ver falhar**

Run: `uv run pytest tests/engine/test_narratives.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'engine.narratives'`)

- [ ] **Step 2.4: Implementar**

```python
"""LLM narratives of a run (A9): one per published event and one global, built only from the results.json the engine
already published, checked by `grounding`, regenerated once, and replaced by a deterministic text when they fail."""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from engine import grounding
from engine.config import EngineConfig
from engine.errors import EngineError
from engine.scenario import ScenarioFilters, scenario
from llm.base import LLM, LLMError, LLMUnavailable

log = logging.getLogger(__name__)

# per call: a provider retrying a 503 for minutes would freeze the log; the first call of a run pays it in full before
# LLMUnavailable stops the others
TIMEOUT_S = 60
CI_LEVEL_PCT = 95
SEVERITY = {"passed": 0, "regenerated": 1, "blocked": 2}
ELASTICITY_REASONS = {
    "no_identifiable_channel": "nenhum canal tem efeito identificável",
    "model_failed": "o modelo de elasticidade falhou",
    "cv_in_sample": "o histórico é curto e o modelo não foi validado fora da amostra",
}
SCENARIO_LABELS = {"current": "Atual", "recommended": "Recomendado", "saturation": "Saturação"}
FEEDBACK = {
    "number": "número que não está nos dados",
    "channel": "canal que não pode ser citado",
    "output": "resposta fora do formato pedido",
}


class EventNarrative(BaseModel):
    title: str
    verdict: str
    analysis: str
    next_steps: list[str] = Field(max_length=3)


class ScenarioNote(BaseModel):
    name: str
    analysis: str


class GlobalNarrative(BaseModel):
    title: str
    summary: str
    scenarios: list[ScenarioNote] = Field(max_length=4)
    recommendations: list[str] = Field(max_length=3)


RULES = """Regras:
- Escreva em português do Brasil, em tom executivo e direto.
- Use só números que estão nos dados abaixo. Pode arredondar, mas não calcule nenhum número novo.
- Cite só estes canais: {channels}. Não cite nenhum outro.
- O KPI se chama "{kpi}".
"""
EVENT_PROMPT = (
    "Escreva um relatório curto sobre um evento de investimento em mídia. O efeito no KPI foi estimado por um modelo "
    "causal e passou nos critérios de publicação.\n\n" + RULES + "\nDados (JSON):\n{data}\n"
)
GLOBAL_PROMPT = (
    "Escreva um resumo da análise de elasticidade do investimento em mídia (curva de resposta e cenários mensais)."
    "\n{status_rule}\n\n" + RULES + "\nDados (JSON):\n{data}\n"
)
NOT_OK_RULE = (
    "A análise não é conclusiva (veja status e reasons). Explique só por que ela não é conclusiva e não sugira "
    "valores de investimento."
)


# --- formatting (pt-BR, from the payload only, so the deterministic text passes the check by construction) ---


def _br(value: float, decimals: int) -> str:
    return f"{value:,.{decimals}f}".translate(str.maketrans(",.", ".,"))


def _money(value: float) -> str:
    return f"R$ {_br(value, 2)}"


def _day(iso: str) -> str:
    year, month, day = iso[:10].split("-")
    return f"{day}/{month}/{year}"


def text_of(obj: Any) -> str:
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        return " ".join(text_of(v) for v in obj.values())
    if isinstance(obj, list):
        return " ".join(text_of(v) for v in obj)
    return ""


# --- payloads ---


def event_payload(event: dict, kpi: str, p_value_threshold: float, sufficiency_reasons: list[str]) -> dict:
    fit = event.get("fit") or {}
    return {
        "kpi_name": kpi,
        "p_value_threshold": p_value_threshold,
        "ci_level_pct": CI_LEVEL_PCT,
        "channels": event["channels"],
        "start": event.get("start"),
        "end": event.get("end"),
        "investment_change_pct": event.get("investment_change_pct"),
        "lift": event.get("lift"),
        "p_value": event.get("p_value"),
        "incremental_investment": event.get("incremental_investment"),
        "cpa_incremental": event.get("cpa_incremental"),
        "fit": {"r2": fit.get("r2"), "wmape": fit.get("wmape")},
        "placebo_p_value": (event.get("placebo") or {}).get("p_value"),
        "robustness_p_value": (event.get("robustness") or {}).get("p_value"),
        "sufficiency_reasons": sufficiency_reasons,
    }


def global_payload(document: dict, config: EngineConfig, kpi: str, revenue: bool) -> dict | None:
    elasticity = document.get("elasticity")
    if not elasticity:
        return None
    channels = elasticity.get("channels") or []
    payload = {
        "kpi_name": kpi,
        "revenue_mode": revenue,
        "status": elasticity["status"],
        "reasons": elasticity.get("reasons") or [],
        "unidentified_count": sum(1 for c in channels if not c.get("identifiable")),
    }
    if elasticity["status"] != "ok":
        return payload
    metrics = elasticity.get("metrics") or {}
    keys = ("cv_r2", "r2", "media_contribution_pct", "low_confidence", "reallocation_suppressed")
    payload["metrics"] = {k: metrics.get(k) for k in keys}
    payload["channels"] = [
        {"name": c["name"], "contribution_pct": c.get("contribution_pct"), "K": (c.get("hill") or {}).get("K")}
        for c in channels
        if c.get("identifiable")
    ]
    try:
        answer = scenario(document, ScenarioFilters(), config.max_budget_step)
    except EngineError:
        return payload
    fields = ("investment", "kpi", "kpi_lo", "kpi_hi", "icpa") + (("roas", "iroas") if revenue else ())
    payload["scenarios_monthly"] = {
        name: {k: answer[name].get(k) for k in fields} for name in SCENARIO_LABELS if answer.get(name)
    }
    return payload


def universe(document: dict) -> set[str]:
    """Every channel name the run knows: the check rejects any of them outside the published set."""
    names = set((document.get("validation") or {}).get("channels") or [])
    elasticity = document.get("elasticity") or {}
    names |= {c["name"] for c in elasticity.get("channels") or []}
    names |= {g["name"] for g in elasticity.get("groups") or []}
    for event in (document.get("causal") or {}).get("events") or []:
        names |= set(event["channels"])
    return names


# --- deterministic texts ---


def deterministic_event(p: dict) -> dict:
    lift = p.get("lift") or {}
    period = f"{_day(p['start'])} a {_day(p['end'])}" if p.get("start") and p.get("end") else ""
    title = " · ".join(part for part in (", ".join(p["channels"]), period) if part)
    if lift.get("abs") is None:
        verdict = "Evento publicado sem estimativa de lift."
    else:
        verdict = f"{'Aumento' if lift['abs'] >= 0 else 'Queda'} de {_br(abs(lift['abs']), 0)} em {p['kpi_name']}"
        if lift.get("rel_pct") is not None:
            verdict += f" ({_br(abs(lift['rel_pct']), 1)}%)"
        ci = lift.get("ci") or [None, None]
        if None not in ci:
            verdict += f", IC {CI_LEVEL_PCT}% [{_br(ci[0], 0)}; {_br(ci[1], 0)}]"
        if p.get("p_value") is not None:
            verdict += f", p-valor {_br(p['p_value'], 4)}"
        verdict += "."
    fit = p.get("fit") or {}
    facts = []
    if p.get("incremental_investment") is not None:
        facts.append(f"investimento incremental de {_money(p['incremental_investment'])}")
    if p.get("cpa_incremental") is not None:
        facts.append(f"CPA incremental de {_money(p['cpa_incremental'])}")
    if fit.get("r2") is not None:
        facts.append(f"R² de {_br(fit['r2'], 2)} no pré-período")
    if fit.get("wmape") is not None:
        facts.append(f"WMAPE fora da amostra de {_br(fit['wmape'] * 100, 1)}%")
    analysis = "; ".join(facts)
    analysis = analysis[:1].upper() + analysis[1:] + "." if analysis else ""
    return {"title": title, "verdict": verdict, "analysis": analysis, "next_steps": []}


def deterministic_global(p: dict) -> dict:
    scenarios = p.get("scenarios_monthly") or {}
    if p["status"] != "ok" or not scenarios:
        reasons = [ELASTICITY_REASONS.get(r, r) for r in p["reasons"]] or ["não há curva de resposta para simular"]
        summary = "A análise de elasticidade não é conclusiva: " + "; ".join(reasons) + "."
        if p["unidentified_count"]:
            summary += f" Canais sem efeito identificável: {p['unidentified_count']}."
        return {"title": "Elasticidade não conclusiva", "summary": summary, "scenarios": [], "recommendations": []}
    rows = []
    for name, s in scenarios.items():
        if s.get("investment") is None:
            continue
        text = f"Investimento mensal de {_money(s['investment'])}"
        if s.get("kpi") is not None:
            text += f" e {p['kpi_name']} de {_br(s['kpi'], 0)}"
        if s.get("kpi_lo") is not None and s.get("kpi_hi") is not None:
            text += f" (faixa de {_br(s['kpi_lo'], 0)} a {_br(s['kpi_hi'], 0)})"
        rows.append({"name": SCENARIO_LABELS[name], "analysis": text + "."})
    return {
        "title": "Elasticidade do investimento",
        "summary": "Valores mensais da curva de resposta, sem filtros de meta.",
        "scenarios": rows,
        "recommendations": [],
    }


# --- the LLM call, checked and regenerated once ---


@dataclass(frozen=True)
class Kind:
    prompt: str
    model: type[BaseModel]
    fallback: Callable[[dict], dict]


EVENT = Kind(EVENT_PROMPT, EventNarrative, deterministic_event)
GLOBAL = Kind(GLOBAL_PROMPT, GlobalNarrative, deterministic_global)


def _feedback(issues: list[dict]) -> str:
    lines = "\n".join(f"- {FEEDBACK[i['kind']]}: {i['value']}" for i in issues)
    return f"\n\nSua resposta anterior foi recusada. Corrija:\n{lines}"


def _ask(llm: LLM, kind: Kind, payload: dict, published: set[str], names: set[str]) -> tuple[dict | None, dict]:
    prompt = kind.prompt.format(
        channels=", ".join(sorted(published)) or "nenhum",
        kpi=payload["kpi_name"],
        status_rule="" if payload.get("status", "ok") == "ok" else NOT_OK_RULE,
        data=json.dumps(payload, ensure_ascii=False, indent=2),
    )
    first: list[dict] = []
    issues: list[dict] = []
    for _ in range(2):
        try:
            answer = llm.generate_json(
                prompt + (_feedback(issues) if issues else ""), kind.model.model_json_schema(), timeout_s=TIMEOUT_S
            )
            narrative = kind.model.model_validate(answer).model_dump()
            issues = grounding.check(text_of(narrative), payload, published, names)
        except LLMUnavailable:
            raise
        except LLMError as e:
            issues = [{"kind": "output", "value": str(e) or type(e).__name__}]
        except ValidationError:
            issues = [{"kind": "output", "value": "bad_shape"}]
        if not issues:
            return narrative, {"status": "regenerated" if first else "passed", "issues": first}
        first = first or issues
    return None, {"status": "blocked", "issues": issues}


def _summary(reports: dict) -> dict | None:
    judged = [
        (key, report["grounding"])
        for key, report in [*reports["events"].items(), ("global", reports["global"])]
        if report and report["grounding"]
    ]
    if not judged:
        return None
    return {
        "status": max((g["status"] for _, g in judged), key=SEVERITY.__getitem__),
        "issues": [{"report": key, **issue} for key, g in judged for issue in g["issues"]],
    }


def build(document: dict, config: EngineConfig, llm: LLM | None) -> dict:
    """The `reports` section: a narrative per published event and a global one, each from the LLM when it passes the
    grounding check (at most two tries) or the deterministic text otherwise."""
    kpi = config.column_mapping.get("performance_file", {}).get("kpi_col") or "KPI"
    revenue = config.kpi_is_monetary or config.optimization_target == "REVENUE"
    sufficiency = (document.get("sufficiency") or {}).get("reasons") or []
    names = universe(document)
    jobs = [
        (event["id"], EVENT, event_payload(event, kpi, config.p_value_threshold, sufficiency), set(event["channels"]))
        for event in (document.get("causal") or {}).get("events") or []
        if event["status"] == "published"
    ]
    payload = global_payload(document, config, kpi, revenue)
    if payload is not None:
        jobs.append(("global", GLOBAL, payload, {c["name"] for c in payload.get("channels", [])}))
    if llm is not None and jobs:
        log.info("Gerando as narrativas com a IA e conferindo os números (grounding)...")

    reports: dict = {"events": {}, "global": None, "grounding": None}
    for key, kind, payload, published in jobs:
        narrative, judged = None, None
        if llm is not None and payload.get("status") != "failed":
            try:
                narrative, judged = _ask(llm, kind, payload, published, names)
            except LLMUnavailable as e:
                log.warning(
                    f"AVISO: o serviço de IA está indisponível ({e.reason}); os próximos relatórios usarão o texto padrão."
                )
                llm = None
            except Exception:
                log.error(f"Não foi possível gerar a narrativa {key}", exc_info=True)
        if judged and judged["status"] == "blocked":
            log.warning(f"   - A narrativa {key} citou números ou canais fora do resultado; vale o texto padrão.")
        report = {"source": "llm", **narrative} if narrative else {"source": "deterministic", **kind.fallback(payload)}
        report["grounding"] = judged
        if key == "global":
            reports["global"] = report
        else:
            reports["events"][key] = report
    reports["grounding"] = _summary(reports)
    return reports
```

- [ ] **Step 2.5: Rodar e ver passar**

Run: `uv run pytest tests/engine/test_narratives.py tests/engine/test_grounding.py -q`
Expected: PASS. Se `test_the_deterministic_texts_pass_their_own_grounding` reprovar, imprima as issues: o texto determinístico tem que ser corrigido (formatação), nunca o checador afrouxado.

- [ ] **Step 2.6: Lint e commit**

```bash
uv run ruff format engine/narratives.py tests/engine/test_narratives.py tests/fakes/llm.py
uv run ruff check engine/narratives.py tests/engine/test_narratives.py tests/fakes/llm.py
git add engine/narratives.py tests/engine/test_narratives.py tests/fakes/llm.py
git commit -m "feat(engine): grounded llm narratives from the published results, with the deterministic fallback"
```

---

### Task 3: `temperature=0` no `generate_json`

**Files:**
- Modify: `llm/gemini.py:55`
- Test: `tests/llm/test_gemini.py:50-55`

- [ ] **Step 3.1: Teste que falha**

Em `test_generate_json_parses_and_strips_code_fence`, depois de `assert config.response_json_schema == {"type": "object"}`, acrescente:

```python
    assert config.temperature == 0  # structured output is meant to be reproducible (A9)
```

- [ ] **Step 3.2: Rodar e ver falhar**

Run: `uv run pytest tests/llm/test_gemini.py -q`
Expected: FAIL (`assert None == 0`)

- [ ] **Step 3.3: Implementar**

Em `llm/gemini.py`, troque a linha do `config`:

```python
        config = types.GenerateContentConfig(
            response_mime_type="application/json", response_json_schema=schema, temperature=0
        )
```

- [ ] **Step 3.4: Rodar, lint e commit**

```bash
uv run pytest tests/llm -q
uv run ruff format llm/gemini.py tests/llm/test_gemini.py && uv run ruff check llm tests/llm
git add llm/gemini.py tests/llm/test_gemini.py
git commit -m "feat(llm): temperature 0 for gemini json output"
```

---

### Task 4: `run()` grava o `reports` e o HTML por LLM sai

**Files:**
- Modify: `engine/pipeline.py:346-349` (e import)
- Modify: `engine/outputs.py` (sai `generate_reports`, entra `write_recommendations`)
- Delete: `engine/reports.py`, `engine/recommendations.py`, `tests/engine/test_reports.py`
- Modify: `tests/engine/test_run.py`, `tests/engine/test_outputs_identifiability.py`

- [ ] **Step 4.1: Atualizar os testes do run (falham)**

Em `tests/engine/test_run.py`:

a) Troque o laço de `test_run_returns_the_contract_dict`:

```python
    assert r["experiment_design"] is None  # A7
    reports = r["reports"]
    published = [e["id"] for e in r["causal"]["events"] if e["status"] == "published"]
    assert published and set(reports["events"]) == set(published)
    assert all(rep["source"] == "deterministic" and rep["grounding"] is None for rep in reports["events"].values())
    assert reports["global"]["source"] == "deterministic" and reports["grounding"] is None
```

b) Em `test_llm_unavailable_stops_further_calls`, no lugar de `assert not list(run.out_dir.rglob("global_report.html"))`:

```python
    assert not list(run.out_dir.rglob("*.html"))
    assert run.result["reports"]["grounding"] is None
```

c) Substitua `test_other_llm_error_only_fails_that_report` inteiro por:

```python
def test_a_report_that_fails_twice_is_blocked_and_the_others_pass(monkeypatch, ran, tmp_path):
    selected = sum(e.selected for e in ran.computed.events)
    assert selected >= 2
    fake = FakeLLM(
        [LLMBadOutput("invalid_json")] * 2
        + [json.dumps(EVENT_NARRATIVE)] * (selected - 1)
        + [json.dumps(GLOBAL_NARRATIVE)]
    )
    run = _with_llm(monkeypatch, ran, tmp_path, fake)
    assert len(fake.calls) == selected + 2
    reports = run.result["reports"]
    statuses = [rep["grounding"]["status"] for rep in reports["events"].values()]
    assert statuses.count("blocked") == 1 and statuses.count("passed") == selected - 1
    assert reports["global"]["source"] == "llm" and reports["grounding"]["status"] == "blocked"
    assert len(list(run.out_dir.rglob("RECOMMENDATIONS.md"))) == selected
    assert not list(run.out_dir.rglob("*.html"))
```

d) Acrescente no fim do arquivo:

```python
def test_a_bug_in_the_narratives_never_fails_the_run(monkeypatch, ran, tmp_path):
    def explode(*args, **kwargs):
        raise KeyError("lift")

    monkeypatch.setattr(pipeline.narratives, "build", explode)
    run = _with_llm(monkeypatch, ran, tmp_path, None)
    assert run.result["status"] == "inconclusive" and run.result["reports"] is None
    assert any(level == "error" for level, _ in run.calls)
```

Em `tests/engine/test_outputs_identifiability.py`, substitua tudo depois de `_hide` por:

```python
def test_the_saturation_markdown_never_names_a_hidden_channel(synthetic_computed, tmp_path):
    spend_cols = list(synthetic_computed.mmm["spend_cols"])

    written = outputs.write_legacy_outputs(_hide(synthetic_computed, set(spend_cols[1:])), tmp_path)

    markdown = (written.global_dir / "SATURATION_CURVE.md").read_text(encoding="utf-8")
    assert spend_cols[0] in markdown
    for name in spend_cols[1:]:
        assert name not in markdown


def test_the_reallocation_is_left_out_while_a_channel_is_hidden(synthetic_computed, tmp_path):
    last = synthetic_computed.mmm["spend_cols"][-1]

    plain = outputs.write_legacy_outputs(_hide(synthetic_computed, set()), tmp_path / "plain")
    hidden = outputs.write_legacy_outputs(_hide(synthetic_computed, {last}), tmp_path / "hidden")

    assert plain.kpi_projections["reallocation"] is not None
    assert hidden.kpi_projections["reallocation"] is None
```

e remova os imports que sobrarem (`json`, `FakeLLM`, `GLOBAL_NARRATIVE`). Atualize a docstring do módulo para `"""A5: SATURATION_CURVE.md and the scenarios speak only of the published channels."""`.

- [ ] **Step 4.2: Rodar e ver falhar**

Run: `uv run pytest tests/engine/test_run.py tests/engine/test_outputs_identifiability.py -q`
Expected: FAIL (`r["reports"]` é `None`, `pipeline.narratives` não existe)

- [ ] **Step 4.3: Implementar no `pipeline.py`**

Nos imports de `engine/pipeline.py`, acrescente `narratives` ao `from engine import …` (ou `from engine import narratives` se não houver essa linha) e `from engine.results_schema import ResultsV1`.

Troque as linhas 346-349 (`written = …` até `results.write_results(…)`) por:

```python
        written = outputs.write_legacy_outputs(computed, out_dir)
        document = results.dump_results(results.build_results(computed, engine_version()))
        try:
            document["reports"] = narratives.build(document, engine_config, llm)
        except Exception:  # a narrative never fails the run: the screen just shows no text
            log.error("Não foi possível montar os relatórios da execução", exc_info=True)
        document = results.dump_results(ResultsV1.model_validate(document))
        outputs.write_recommendations(written, document["reports"])
    results.write_results(document, out_dir / "results.json")
```

E atualize a docstring do `run`: `"""The contract entry point: compute, write the legacy outputs and results.json (with the grounded reports) under `out_dir`.`

- [ ] **Step 4.4: Implementar no `outputs.py`**

Em `engine/outputs.py`:
- Apague a função `generate_reports` inteira (do `def generate_reports` até o fim do arquivo).
- Troque `from engine import identifiability, presentation, recommendations, reports` por `from engine import identifiability, presentation` e apague `from llm.base import LLM, LLMUnavailable`.
- Docstring do módulo: `"""Files the prototype always wrote (PNG, CSV, Markdown), now rooted at `out_dir`. The narratives live in results.json (engine/narratives.py)."""`
- Acrescente no fim:

```python
def write_recommendations(written: Written, reports: dict | None) -> None:
    """RECOMMENDATIONS.md of each published event, with the same text the screen shows."""
    for event_id, report in ((reports or {}).get("events") or {}).items():
        event_dir = written.event_dirs.get(event_id)
        if event_dir is None:
            continue
        lines = [f"# {report['title']}", "", report["verdict"], "", report["analysis"]]
        lines += [f"- {step}" for step in report["next_steps"]]
        (event_dir / "RECOMMENDATIONS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
```

Depois rode `uv run ruff check --fix engine/outputs.py` para tirar `os` e `pd` se tiverem ficado sem uso.

- [ ] **Step 4.5: Apagar o que só servia ao HTML por LLM**

```bash
git rm engine/reports.py engine/recommendations.py tests/engine/test_reports.py
```

Confira que nada mais importa: `grep -rn "engine.reports\|engine import.*reports\|recommendations" engine tests api --include=*.py`. O único resultado esperado é o `write_recommendations` e textos que só contêm a palavra.

- [ ] **Step 4.6: Rodar os testes do motor**

Run: `uv run pytest tests/engine -q -x`
Expected: PASS (a paridade é pulada no Windows). Se um teste de `test_logmessages.py` quebrar por regra que citava os HTMLs, não mexa nas regras: o teste testa a tradução, que continua igual.

- [ ] **Step 4.7: Lint e commit**

```bash
uv run ruff format engine tests/engine && uv run ruff check engine tests/engine
git add engine/pipeline.py engine/outputs.py tests/engine/test_run.py tests/engine/test_outputs_identifiability.py
git commit -m "feat(engine): run writes the grounded reports into results.json; the llm html reports are gone"
```

---

### Task 5: worker com LLM ligado

**Files:**
- Modify: `api/launcher.py:5-12`
- Test: `tests/api/test_worker_process.py:7-20`

- [ ] **Step 5.1: Teste que falha**

Renomeie o teste e troque a asserção do LLM:

```python
def test_launch_pins_blas_to_one_thread_and_keeps_the_llm_setting(monkeypatch):
```

e

```python
    assert env["LLM_PROVIDER"] == "gemini"  # A9: the narratives are grounded, so the worker may call the LLM
```

- [ ] **Step 5.2: Rodar e ver falhar**

Run: `uv run pytest tests/api/test_worker_process.py -q`
Expected: FAIL (`'none' == 'gemini'`)

- [ ] **Step 5.3: Implementar**

Em `api/launcher.py`, apague do `WORKER_ENV` as duas linhas:

```python
    # until A9 the engine's LLM reports are written to a temp dir and thrown away: no cost, no client data out
    "LLM_PROVIDER": "none",
```

- [ ] **Step 5.4: Rodar, lint e commit**

```bash
uv run pytest tests/api/test_worker_process.py -q
uv run ruff format api/launcher.py tests/api/test_worker_process.py && uv run ruff check api tests/api
git add api/launcher.py tests/api/test_worker_process.py
git commit -m "feat(api): worker no longer forces the llm off"
```

---

### Task 6: fixtures com `reports`

**Files:**
- Create: `tests/fixtures/results/add_reports.py`
- Modify: `tests/fixtures/results/*.json` (4 arquivos regravados pelo script)
- Modify: `tests/fixtures/results/README.md`
- Test: `tests/engine/test_results_fixtures.py`

- [ ] **Step 6.1: Teste que falha**

No fim de `tests/engine/test_results_fixtures.py`:

```python
@pytest.mark.parametrize("name", ["gol_anonimizada.json", "gol_inconclusiva.json", "identificavel.json", "falha.json"])
def test_fixtures_carry_the_deterministic_reports(name):
    document = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    reports = document["reports"]
    published = {e["id"] for e in (document["causal"] or {}).get("events", []) if e["status"] == "published"}
    assert set(reports["events"]) == published
    assert all(r["source"] == "deterministic" and r["grounding"] is None for r in reports["events"].values())
    assert reports["global"]["source"] == "deterministic"
    assert reports["grounding"] is None
```

(Se `pytest` ou `json` ainda não estiverem importados no arquivo, importe.)

- [ ] **Step 6.2: Rodar e ver falhar**

Run: `uv run pytest tests/engine/test_results_fixtures.py -q -k reports`
Expected: FAIL (`TypeError: 'NoneType' object is not subscriptable`)

- [ ] **Step 6.3: Script**

`tests/fixtures/results/add_reports.py`:

```python
"""Fill `reports` (A9) into the committed fixtures without rerunning the engine:

    uv run python tests/fixtures/results/add_reports.py

The narratives only read the document, so with no LLM this writes exactly what generate_fixtures.py would.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from engine import narratives, results
from engine.config import EngineConfig
from engine.results_schema import ResultsV1
from tests.engine.real_data import GOL_RUN_CONFIG
from tests.engine.synthetic_data import dataset_config, identifiable_config

CONFIGS = {
    "gol_anonimizada.json": GOL_RUN_CONFIG,
    "gol_inconclusiva.json": GOL_RUN_CONFIG,
    "identificavel.json": identifiable_config(),
    "falha.json": dataset_config(),
}


def main() -> None:
    for name, config in CONFIGS.items():
        path = HERE / name
        document = json.loads(path.read_text(encoding="utf-8"))
        document["reports"] = narratives.build(document, EngineConfig.from_input(config), None)
        results.write_results(results.dump_results(ResultsV1.model_validate(document)), path)
        print(f"wrote {name}", file=sys.stderr)


if __name__ == "__main__":
    main()
```

- [ ] **Step 6.4: Rodar o script e os testes das fixtures**

```bash
uv run python tests/fixtures/results/add_reports.py
uv run pytest tests/engine/test_results_fixtures.py tests/api -q
```

Expected: `wrote …` 4 vezes e os testes passam. `test_the_e2e_scenario_fixture_is_up_to_date` não muda, porque o `scenario` não lê `reports`. Confira com `git diff --stat tests/fixtures/results` que só os 4 JSON mudaram.

- [ ] **Step 6.5: README das fixtures**

Em `tests/fixtures/results/README.md`:
- Em "What a screen can assume", troque `` `experiment_design` and `reports` (A7, A9)`` por `` `experiment_design` (A7)``. Acrescente um item: `` - `reports` (A9) is always filled: one deterministic narrative per published event and a global one, `grounding: null` (the fixtures run with no LLM).``
- Depois do bloco "Regenerate", acrescente:

```markdown
`reports` alone can be refilled without the Gol data (the narratives only read the document):

    uv run python tests/fixtures/results/add_reports.py
```

- [ ] **Step 6.6: Lint e commit**

```bash
uv run ruff format tests/fixtures/results/add_reports.py tests/engine/test_results_fixtures.py
uv run ruff check tests/fixtures/results/add_reports.py tests/engine/test_results_fixtures.py
git add tests/fixtures/results tests/engine/test_results_fixtures.py
git commit -m "test(fixtures): results fixtures carry the deterministic reports"
```

---

### Task 7: narrativa na tela

**Files:**
- Modify: `web/src/lib/results.ts:40-47`
- Create: `web/src/components/NarrativeCard.tsx`
- Modify: `web/src/components/causal/EventDetail.tsx`, `web/src/components/causal/CausalTab.tsx:28-38`, `web/src/components/elasticity/ElasticityTab.tsx:31-50`
- Test: `web/e2e/results.spec.ts`

- [ ] **Step 7.1: Tipos**

Em `web/src/lib/results.ts`, troque as linhas de `export type Grounding` até o fim do tipo `Results` por:

```ts
export type Grounding = { status: 'passed' | 'regenerated' | 'blocked'; issues: unknown[] }
export type ReportBase = { source: 'llm' | 'deterministic'; title: string; grounding: Grounding | null }
export type EventReport = ReportBase & { verdict: string; analysis: string; next_steps: string[] }
export type GlobalReport = ReportBase & {
  summary: string
  scenarios: { name: string; analysis: string }[]
  recommendations: string[]
}
export type Reports = { events: Record<string, EventReport>; global: GlobalReport | null; grounding: Grounding | null }
export type Results = {
  status: 'succeeded' | 'inconclusive' | 'failed'
  causal: Causal | null
  elasticity: Elasticity | null
  // null only when the engine could not build them (A9); grounding is null when no report went through the LLM
  reports: Reports | null
}
```

- [ ] **Step 7.2: Cartão**

`web/src/components/NarrativeCard.tsx`:

```tsx
import { Badge } from '@/components/ui/badge'
import type { ReportBase } from '@/lib/results'

// plain text only: React escapes it, so an LLM answer never becomes markup
export function NarrativeCard({
  report,
  paragraphs,
  items,
}: {
  report: ReportBase
  paragraphs: string[]
  items: string[]
}) {
  return (
    <section aria-label="Análise" className="break-inside-avoid space-y-2 rounded-md border p-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-medium">{report.title}</h3>
        {report.source === 'deterministic' && <Badge variant="outline">Texto padrão</Badge>}
        {report.grounding?.status === 'blocked' && <Badge variant="outline">Bloqueado pelo grounding</Badge>}
      </div>
      {paragraphs.filter(Boolean).map((p) => (
        <p key={p}>{p}</p>
      ))}
      {items.length > 0 && (
        <ul className="list-disc space-y-1 pl-5">
          {items.map((i) => (
            <li key={i}>{i}</li>
          ))}
        </ul>
      )}
    </section>
  )
}
```

- [ ] **Step 7.3: Aba Causal**

Em `web/src/components/causal/CausalTab.tsx`:
- Adicione `type Reports,` ao import de `@/lib/results`.
- Troque `return <CausalView causal={causal} csvHref={eventsCsvHref(slug, runId)} />` por `return <CausalView causal={causal} reports={query.data.reports} csvHref={eventsCsvHref(slug, runId)} />`.
- Troque a assinatura `function CausalView({ causal, csvHref }: { causal: Causal; csvHref: string })` por `function CausalView({ causal, reports, csvHref }: { causal: Causal; reports: Reports | null; csvHref: string })`.
- Troque `<EventDetail event={selected} />` por `<EventDetail event={selected} report={reports?.events[selected.id]} />`.

Em `web/src/components/causal/EventDetail.tsx`:
- Adicione `type EventReport,` ao import de `@/lib/results` e `import { NarrativeCard } from '@/components/NarrativeCard'`.
- Troque `export function EventDetail({ event }: { event: CausalEvent }) {` por `export function EventDetail({ event, report }: { event: CausalEvent; report?: EventReport }) {`.
- Antes de `{published ? <Published event={event} /> : <Rejected event={event} />}`, acrescente:

```tsx
      {published && report && (
        <NarrativeCard report={report} paragraphs={[report.verdict, report.analysis]} items={report.next_steps} />
      )}
```

- [ ] **Step 7.4: Aba Elasticidade**

Em `web/src/components/elasticity/ElasticityTab.tsx`:
- Adicione `import { NarrativeCard } from '@/components/NarrativeCard'`.
- Logo depois de `const elasticity = query.data.elasticity`, acrescente `const report = query.data.reports?.global`.
- Dentro de `<section aria-label="Elasticidade">`, antes do `{!elasticity ? (`, acrescente:

```tsx
      {report && (
        <div className="mb-6">
          <NarrativeCard
            report={report}
            paragraphs={[report.summary, ...report.scenarios.map((s) => `${s.name}: ${s.analysis}`)]}
            items={report.recommendations}
          />
        </div>
      )}
```

- [ ] **Step 7.5: Build e lint**

Run: `cd web && bun run build && bun run lint`
Expected: sem erros

- [ ] **Step 7.6: E2E (precisa das fixtures da Task 6)**

Em `web/e2e/results.spec.ts`, depois de `await expect(detail.locator('.recharts-surface').first()).toBeVisible()`, acrescente:

```ts
  // A9: the published event carries its narrative; the E2E runs with no API key, so it is the deterministic text
  const analysis = detail.getByRole('region', { name: 'Análise' })
  await expect(analysis).toContainText('Texto padrão')
  await expect(analysis).toContainText('Queda de')
```

e depois de `await expect(detail).not.toContainText('R$')` (evento rejeitado):

```ts
  await expect(detail.getByRole('region', { name: 'Análise' })).toHaveCount(0)
```

Run: `mise run e2e`
Expected: PASS. O `export.spec.ts` imprime a aba e pode depender do layout: se ele quebrar por posição, confira o screenshot do trace antes de mexer.

- [ ] **Step 7.7: Screenshot**

Com `mise run api` e `mise run web` no ar, rode um run (o fake devolve a Gol) e abra `/w/<slug>/execucoes/<id>/causal` e `/elasticidade` pelo MCP `playwright`. Tire um screenshot de cada e confira que o cartão "Análise" aparece com o selo "Texto padrão" e não quebra o layout. Confira também a impressão (`browser_emulate_media` com `print`).

- [ ] **Step 7.8: Commit**

```bash
git add web/src/lib/results.ts web/src/components/NarrativeCard.tsx web/src/components/causal web/src/components/elasticity/ElasticityTab.tsx web/e2e/results.spec.ts
git commit -m "feat(web): grounded narrative card on the causal event and the elasticity tab"
```

---

### Task 8: docs, estado e verificação final

**Files:**
- Modify: `docs/decisoes/llm.md`, `docs/decisoes/engine.md`, `docs/decisoes/dashboards.md`, `docs/decisoes/runs-e-jobs.md` (só se citar o `LLM_PROVIDER=none` do launcher), `docs/decisoes/infra-e-operacao.md` (idem)
- Modify: `docs/m2/trilha-a-motor.md` (linha `Status` do A9)
- Modify: `docs/superpowers/specs/2026-11-08-a9-grounding-design.md` (os dois ajustes das "Decisões de leitura")
- Modify: `CLAUDE.md` (Estrutura do `engine/` e Estado atual), `docs/CODEBASE_MAP.md` (tabela do `engine/`)

- [ ] **Step 8.1: Verificação completa**

```bash
uv run ruff format --check . && uv run ruff check .
uv run pytest -q
cd web && bun run build && bun run lint && cd ..
mise run e2e
```

Expected: tudo verde. Anote as contagens (passed/skipped) para o status.

- [ ] **Step 8.2: Decisões**

- `docs/decisoes/llm.md`:
  - Uma seção "Grounding (A9, 08/nov/2026)" com o payload restrito, o checador (tolerância de arredondamento da forma escrita, inteiros até 12 ignorados, canal inventado não detectado), a regeneração única, o `blocked` com o texto determinístico, o `temperature=0` no `generate_json` e o fim do `LLM_PROVIDER=none` no worker.
  - Na pendência do Dev B, deixe claro que ela continua: `api/gemini.py` → `llm/`.
- `docs/decisoes/engine.md`:
  - O HTML do protótipo por LLM saiu do run. `reports.py` e `recommendations.py` foram apagados.
  - `reports` fica no `results.json`, e o `RECOMMENDATIONS.md` sai do mesmo texto.
  - Um erro em `narratives` deixa `reports = null` sem falhar o run.
  - As fixtures ganham `reports` pelo `add_reports.py`.
- `docs/decisoes/dashboards.md`:
  - O cartão "Análise" (texto puro, selos "Texto padrão" e "Bloqueado pelo grounding") no evento publicado e no topo da Elasticidade.
  - A linha "Grounding" do PDF agora aparece quando algum relatório passou pelo LLM.
- `runs-e-jobs.md` e `infra-e-operacao.md`: se citam o `LLM_PROVIDER=none` do launcher, atualize. Com `GEMINI_API_KEY` no `.env` do servidor, o run chama o Gemini (até 12 chamadas de até 60 s no pior caso).

- [ ] **Step 8.3: Spec**

Em `docs/superpowers/specs/2026-11-08-a9-grounding-design.md`:
- Em "Falhas", troque o item da exceção inesperada por: "Exceção inesperada dentro de `narratives` (payload ou texto determinístico): log `ERROR` com `exc_info` e `reports = null`. O run não falha por causa da narrativa. Erro do LLM fica dentro do relatório e cai no determinístico."
- Em "Código", troque o item do `logmessages.py` por: "`engine/logmessages.py`: sem mudança; as linhas novas já nascem em pt-BR."

- [ ] **Step 8.4: Status e CLAUDE.md**

- `docs/m2/trilha-a-motor.md`, seção A9: acrescente `- **Status:** feito em 08/nov/2026.` com o que foi verificado. Inclua as contagens do pytest e do E2E, o checador testado com textos fabricados, a ausência de chave com relatório determinístico, e "falta rodar com chave real".
- `CLAUDE.md`:
  - Na estrutura do `engine/`, troque `outputs.py      escritores legados (PNG/CSV/MD/HTML) e relatórios por LLM, a partir do Computed` por `outputs.py      escritores legados (PNG/CSV/MD) a partir do Computed`.
  - Acrescente as linhas `grounding.py    checagem pós-geração (A9): números pt-BR e canais do texto contra o payload` e `narratives.py   narrativas por LLM (A9) a partir do results.json, com uma regeneração e texto determinístico`.
  - Na linha das cópias do protótipo, tire `recommendations.py, reports.py`.
  - No "Estado atual", acrescente o parágrafo **A9 (grounding do Gemini) concluído em 08/nov/2026**, com o resumo do que existe. Em "Faltam", tire o A9.
- `docs/CODEBASE_MAP.md`: na tabela do `engine/`, troque a linha `outputs.py, presentation.py, reports.py, recommendations.py` por `outputs.py, presentation.py` e acrescente `grounding.py` e `narratives.py`. Na seção Gotchas, a linha do Gemini passa a dizer: "`api/gemini.py` ainda é usado pela API para as sugestões; o worker chama o Gemini pelo `llm/` (A9)".

- [ ] **Step 8.5: Commit**

```bash
git add docs CLAUDE.md
git commit -m "docs: a9 grounding, decisions and status"
```
