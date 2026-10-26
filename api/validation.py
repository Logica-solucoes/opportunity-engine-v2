from collections import Counter
from pathlib import Path

from api import csvfile

MAX_DETAIL_ROWS = 20


def validate(inputs: dict[str, Path | None], config: dict) -> dict:
    # ponytail: stand-in for engine.validate (A2, docs/m2/README.md contract §2) with one check;
    # when engine/ exists this module becomes `from engine import validate`
    mapping = config["column_mapping"]["investment_file"]
    rows = csvfile.rows(inputs["investment_file"])
    header = [c.strip() for c in next(rows)]
    date_i, channel_i = header.index(mapping["date_col"]), header.index(mapping["channel_col"])
    pairs = Counter((r[date_i].strip(), r[channel_i].strip()) for r in rows if len(r) > max(date_i, channel_i))

    checks = []
    repeated = [(date, channel, n) for (date, channel), n in pairs.items() if n > 1]
    if repeated:
        extra = sum(n - 1 for _, _, n in repeated)
        noun = "linha repetida" if extra == 1 else "linhas repetidas"
        checks.append(
            {
                "id": "duplicate_date_channel",
                "level": "error",
                "message": f"{extra} {noun} de (data, canal) no investimento",
                "details": {"rows": [{"date": d, "channel": c, "count": n} for d, c, n in repeated[:MAX_DETAIL_ROWS]]},
            }
        )
    return {
        "ok": not any(c["level"] == "error" for c in checks),
        "cadence": None,
        "period_days": None,
        "date_range": None,
        "channels": sorted({channel for _, channel in pairs}),
        "checks": checks,
        "collinearity": None,
    }
