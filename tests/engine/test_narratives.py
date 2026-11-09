"""A9: narratives built from the published results.json, checked, regenerated once, or replaced."""

import itertools
import json
from pathlib import Path

from engine import grounding, narratives
from engine.config import EngineConfig
from llm.base import LLMBadOutput, LLMError, LLMUnavailable
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
FIXTURES = Path(__file__).parents[1] / "fixtures" / "results"
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
    assert '"channels_without_identifiable_effect": 2' in global_prompt
    assert "nenhum canal tem efeito identificável" in global_prompt  # the reason arrives translated


def test_a_failed_elasticity_gets_no_llm_call():
    failed = {"status": "failed", "reasons": ["model_failed"], "channels": [], "groups": []}
    llm = FakeLLM([json.dumps(EVENT_NARRATIVE)])
    reports = _build(_document(failed), llm)
    assert len(llm.calls) == 1
    assert reports["global"]["source"] == "deterministic"
    assert "o modelo de elasticidade falhou" in reports["global"]["summary"]


def test_no_elasticity_section_means_no_global_report():
    assert _build(_document(None), None)["global"] is None


def test_a_published_group_lets_its_members_be_cited():
    elasticity = {
        "status": "ok",
        "reasons": [],
        "channels": [{"name": "A + B", "identifiable": True, "contribution_pct": 12.0}],
        "groups": [{"name": "A + B", "members": ["A", "B"]}],
    }
    document = _document(elasticity, events=())
    document["validation"]["channels"] = ["A", "B"]
    answer = {**GLOBAL_NARRATIVE, "summary": "O grupo A + B responde, com A e B juntos."}
    reports = _build(document, FakeLLM([json.dumps(answer)]))
    assert reports["global"]["source"] == "llm"
    assert reports["global"]["grounding"] == {"status": "passed", "issues": []}


def test_an_llm_error_that_is_not_about_the_output_stops_the_calls():
    llm = FakeLLM([LLMError("http_400")])
    reports = _build(_document(INCONCLUSIVE), llm)
    assert len(llm.calls) == 1
    assert reports["events"][EVENT["id"]]["grounding"] is None
    assert reports["global"]["source"] == "deterministic" and reports["global"]["grounding"] is None


def test_once_the_time_budget_is_spent_the_rest_skips_the_llm(monkeypatch):
    clock = itertools.chain([0, 0], itertools.repeat(narratives.LLM_BUDGET_S + 1))
    monkeypatch.setattr(narratives.time, "monotonic", lambda: next(clock))
    llm = FakeLLM([json.dumps(EVENT_NARRATIVE)])
    reports = _build(_document(INCONCLUSIVE), llm)
    assert len(llm.calls) == 1
    assert reports["events"][EVENT["id"]]["source"] == "llm"
    assert reports["global"]["source"] == "deterministic" and reports["global"]["grounding"] is None


def test_payload_floats_are_rounded_to_four_significant_digits():
    event = {**EVENT, "lift": {"abs": -1234.5678, "ci": [-2010.123456, -458.7], "rel_pct": 238.99107106472343}}
    payload = narratives.event_payload(event, "Pedidos", 0.05, [])
    assert payload["lift"] == {"abs": -1235.0, "ci": [-2010.0, -458.7], "rel_pct": 239.0}
    assert payload["incremental_investment"] == 3_412_000.0
    assert "post_period_investment" not in payload


def test_the_event_duration_is_in_the_payload_so_it_can_be_cited():
    payload = narratives.event_payload(EVENT, "Pedidos", 0.05, [])
    assert payload["post_period_days"] == 29  # 06/01 to 03/02, both days in the window
    assert grounding.check("Em 29 dias o KPI caiu.", payload, {"CANAL_01"}, {"CANAL_01"}) == []
    assert narratives.event_payload(EVENT, "Pedidos", 0.05, [], period_days=7)["post_period_days"] == 35


def test_a_tiny_p_value_is_written_as_a_bound_that_passes_the_grounding():
    payload = narratives.event_payload({**EVENT, "p_value": 0.00001}, "Pedidos", 0.05, [])
    text = narratives.text_of(narratives.deterministic_event(payload))
    assert "p-valor < 0,0001" in text and "0,0000" not in text
    assert grounding.check(text, payload, {"CANAL_01"}, {"CANAL_01"}) == []


def _short_history():
    document = json.loads((FIXTURES / "identificavel.json").read_text(encoding="utf-8"))
    document["elasticity"] = {**document["elasticity"], "status": "inconclusive", "reasons": ["cv_in_sample"]}
    return document


def test_a_short_history_still_narrates_the_planner_with_a_caveat():
    document = _short_history()
    payload = narratives.global_payload(document, CONFIG, "Pedidos", False)
    assert payload["scenarios_monthly"] and payload["channels"]
    text = narratives.text_of(narratives.deterministic_global(payload))
    assert "não é conclusiva" not in text and "não foi validado fora da amostra" in text
    assert grounding.check(text, payload, {"STRONG"}, narratives.universe(document)) == []

    llm = FakeLLM([json.dumps(GLOBAL_NARRATIVE)])
    _build({**document, "causal": None}, llm)
    assert narratives.NOT_OK_RULE not in llm.calls[0] and narratives.CAVEAT_RULE in llm.calls[0]


def test_the_deterministic_text_calls_the_spend_incremental():
    payload = narratives.event_payload(EVENT, "Pedidos", 0.05, [])
    assert "investimento incremental de r$ 3.412.000,00" in narratives.deterministic_event(payload)["analysis"].lower()
