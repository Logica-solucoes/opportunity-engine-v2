"""A9: the contract of the real LLM. Manual and weekly in CI (.github/workflows/llm-live.yml); skipped everywhere else."""

import json
import os
import re
from pathlib import Path

import pytest

from engine import narratives
from engine.config import EngineConfig
from engine.results_schema import ResultsV1
from llm import get_llm
from tests.fixtures.results.add_reports import CONFIGS

KEY = os.environ.get("GEMINI_API_KEY")
pytestmark = pytest.mark.skipif(
    os.environ.get("LLM_LIVE") != "1" or not KEY,
    reason="live LLM test: set LLM_LIVE=1 and GEMINI_API_KEY",
)

RESULTS = Path(__file__).resolve().parents[1] / "fixtures" / "results"
RAW_FLOAT = re.compile(r"\d[.,]\d{4,}")


@pytest.fixture(autouse=True)
def gemini_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", KEY)  # tests/conftest.py removes it for every other test


@pytest.mark.parametrize("name", ["gol_anonimizada.json", "identificavel.json"])
def test_gemini_narratives_pass_the_grounding(name):
    document = json.loads((RESULTS / name).read_text(encoding="utf-8"))
    reports = narratives.build(document, EngineConfig.from_input(CONFIGS[name]), get_llm("gemini"))
    ResultsV1.model_validate({**document, "reports": reports})
    published = [*reports["events"].values(), *([reports["global"]] if reports["global"] else [])]
    assert published
    for report in published:
        assert report["grounding"] is None or report["grounding"]["status"] != "blocked"
        if report["source"] == "llm":
            assert not RAW_FLOAT.search(narratives.text_of(report))
    assert any(r["source"] == "llm" for r in published)
