"""A9: real Gemini answers (tests/fixtures/llm) against the payloads the engine builds from the fixtures, offline."""

import json
from pathlib import Path

import pytest

from engine import grounding, narratives
from engine.config import EngineConfig
from tests.fixtures.results.add_reports import CONFIGS

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ANSWERS = json.loads((FIXTURES / "llm" / "gemini_answers.json").read_text(encoding="utf-8"))


def _cases():
    for name, answers in ANSWERS.items():
        document = json.loads((FIXTURES / "results" / name).read_text(encoding="utf-8"))
        names = narratives.universe(document)
        for key, _, payload, published in narratives.jobs(document, EngineConfig.from_input(CONFIGS[name])):
            yield pytest.param(answers[key], payload, published, names, id=f"{name}:{key}")


CASES = list(_cases())


def _issues(answer, payload, published, names, extra=""):
    return grounding.check(narratives.text_of(answer) + " " + extra, payload, published, names)


def test_every_answer_has_a_job():
    assert len(CASES) == sum(len(a) for a in ANSWERS.values())


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
