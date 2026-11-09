"""A9: real Gemini answers (tests/fixtures/llm) against the payloads they were written from, offline.

The payloads are frozen next to the answers: a fix that moves a published number (say, the monthly scale) must not
turn real prose into a checker failure; the live contract is test_narratives_live.py."""

import json
from pathlib import Path

import pytest

from engine import grounding, narratives
from engine.config import EngineConfig
from tests.fixtures.results.add_reports import CONFIGS

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ANSWERS = json.loads((FIXTURES / "llm" / "gemini_answers.json").read_text(encoding="utf-8"))
PAYLOADS = json.loads((FIXTURES / "llm" / "gemini_payloads.json").read_text(encoding="utf-8"))

CASES = [
    pytest.param(answer, job["payload"], set(job["published"]), set(job["names"]), id=f"{name}:{key}")
    for name, answers in ANSWERS.items()
    for key, answer in answers.items()
    for job in [PAYLOADS[name][key]]
]


def _issues(answer, payload, published, names, extra=""):
    return grounding.check(narratives.text_of(answer) + " " + extra, payload, published, names)


@pytest.mark.parametrize("name", ANSWERS)
def test_every_answer_still_has_a_job(name):
    document = json.loads((FIXTURES / "results" / name).read_text(encoding="utf-8"))
    keys = {key for key, *_ in narratives.jobs(document, EngineConfig.from_input(CONFIGS[name]))}
    assert keys == set(ANSWERS[name])


@pytest.mark.parametrize("answer, payload, published, names", CASES)
def test_a_real_answer_passes_the_check(answer, payload, published, names):
    assert _issues(answer, payload, published, names) == []


@pytest.mark.parametrize("answer, payload, published, names", CASES)
def test_an_invented_number_in_a_real_answer_fails(answer, payload, published, names):
    issues = _issues(answer, payload, published, names, "Ganho adicional de R$ 9.876.")
    assert {"kind": "number", "value": "R$ 9.876"} in issues


@pytest.mark.parametrize("answer, payload, published, names", CASES)
def test_a_wrong_date_in_a_real_answer_fails(answer, payload, published, names):
    issues = _issues(answer, payload, published, names, "Em 21/01/2025 o investimento subiu.")
    assert {"kind": "number", "value": "21/01/2025"} in issues


def test_a_hidden_channel_in_a_real_event_answer_fails():
    checked = 0
    for case in CASES:
        answer, payload, published, names = case.values
        hidden = sorted(names - published)
        if "channels" in payload and hidden:
            issues = _issues(answer, payload, published, names, f"O {hidden[0]} também ajudou.")
            assert {"kind": "channel", "value": hidden[0]} in issues
            checked += 1
    assert checked
