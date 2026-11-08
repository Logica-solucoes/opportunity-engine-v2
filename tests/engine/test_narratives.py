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
CONFIG = EngineConfig.from_input({"column_mapping": {"performance_file": {"date_col": "date", "kpi_col": "Pedidos"}}})


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
    config = EngineConfig.from_input({"column_mapping": CONFIG.column_mapping, "advertiser_name": "ClienteSecreto"})
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
