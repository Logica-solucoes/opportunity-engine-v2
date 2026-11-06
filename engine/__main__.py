"""python -m engine --config run.json --out DIR

run.json holds the EngineConfig fields plus an "inputs" object with investment_file, performance_file and (optional)
generic_trends_file. For development and for generating or checking the parity snapshot; the platform calls run().
"""

import argparse
import json
import sys
from pathlib import Path

from engine import EngineError, run

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2


class UsageError(Exception):
    """Bad command line or config file: exit code 2."""


def _say(level: str, message: str) -> None:
    sys.stderr.write(f"[{level}] {message}\n")


def _load(path: Path) -> tuple[dict, dict]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise UsageError(f"Não foi possível ler a configuração '{path}': {e}") from e
    if not isinstance(raw, dict) or not isinstance(raw.get("inputs"), dict):
        raise UsageError("O arquivo de configuração precisa de um objeto 'inputs' com os caminhos dos CSV.")
    inputs = {
        key: Path(raw["inputs"][key]) if raw["inputs"].get(key) else None
        for key in ("investment_file", "performance_file", "generic_trends_file", "bcb_file")
    }
    return {k: v for k, v in raw.items() if k != "inputs"}, inputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m engine", description="Run the Marketing GEM engine.")
    parser.add_argument("--config", required=True, type=Path, help="run.json: EngineConfig fields plus 'inputs'")
    parser.add_argument("--out", required=True, type=Path, help="directory that receives every output")
    args = parser.parse_args(argv)
    try:
        config, inputs = _load(args.config)
    except UsageError as e:
        _say("error", str(e))
        return EXIT_USAGE
    try:
        result = run(inputs, config, args.out, _say)
    except EngineError as e:
        _say("error", str(e))
        return EXIT_FAILED
    return EXIT_FAILED if result["status"] == "failed" else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
