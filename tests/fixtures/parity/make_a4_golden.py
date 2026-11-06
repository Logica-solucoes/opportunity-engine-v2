"""Pins the engine's per-event causal numbers on the Gol (python -m tests.fixtures.parity.make_a4_golden).

Since A4 the Gol's causal numbers differ from the frozen prototype on purpose (Clicks/Impressions/Leads left the
model), and A6 adds its gates. This golden is the ENGINE's output: it catches regressions from here on, it is not
evidence of parity. The script prints how far each event moved from the prototype (real/gol.json), which is where the
A10 starts. Regenerate only with approval, after reading the deltas. Needs exemplo_csv/ and real/gol.json.
"""

import json

from threadpoolctl import threadpool_limits

from engine.config import EngineConfig
from engine.pipeline import compute
from tests.engine.real_data import GOL_CONFIG, GOL_ENGINE_EVENTS, GOL_SNAPSHOT, engine_snapshot, gol_files


def _numbers(node, prefix=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _numbers(value, f"{prefix}.{key}")
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        yield prefix, float(node)


def describe_deltas(new_events: list[dict], legacy_events: list[dict]) -> list[str]:
    legacy = {e["event_id"]: e for e in legacy_events}
    lines = []
    for event in new_events:
        old = legacy.get(event["event_id"])
        if old is None:
            lines.append(f"{event['event_id']}: not in the prototype snapshot")
            continue
        flags = [f"{k} {old[k]} -> {event[k]}" for k in ("passed", "reasons", "selected") if old[k] != event[k]]
        old_numbers = dict(_numbers(old["results_data"] or {}))
        worst = max(
            (
                abs(value - old_numbers[key]) / abs(old_numbers[key])
                for key, value in _numbers(event["results_data"] or {})
                if old_numbers.get(key)
            ),
            default=0.0,
        )
        lines.append(
            f"{event['event_id']}: max relative change {worst:.3g}" + (f"; {'; '.join(flags)}" if flags else "")
        )
    return lines


def main() -> None:
    with threadpool_limits(limits=1):
        events = engine_snapshot(compute(gol_files(), EngineConfig.from_input(GOL_CONFIG)))["events"]
    GOL_ENGINE_EVENTS.parent.mkdir(parents=True, exist_ok=True)
    GOL_ENGINE_EVENTS.write_text(json.dumps(events, indent=1), encoding="utf-8")
    print(f"wrote {GOL_ENGINE_EVENTS}")
    legacy = json.loads(GOL_SNAPSHOT.read_text(encoding="utf-8"))["events"]
    print("\n".join(describe_deltas(events, legacy)))


if __name__ == "__main__":
    main()
