import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FORBIDDEN = r"os\.getcwd|sys\.exit|os\._exit|sys\.path"


def test_forbidden_calls_are_absent_from_engine_and_llm():
    done = subprocess.run(
        ["grep", "-rnE", FORBIDDEN, "engine", "llm"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert done.returncode == 1, f"forbidden calls found:\n{done.stdout}"


def test_llm_does_not_import_engine_or_api():
    for path in (ROOT / "llm").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"^\s*(from|import)\s+(engine|api)\b", text, re.MULTILINE), path.name
