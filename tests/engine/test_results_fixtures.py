import json
import re
from pathlib import Path

import pandas as pd
import pytest

from engine.identifiability import UNIDENTIFIED
from engine.results_schema import ResultsV1
from tests.engine.real_data import GOL_CONFIG, GOL_DIR
from tests.engine.synthetic_data import dataset_config, make_dataset
from tests.fixtures.results.anonymize_gol import anonymize, load_factors

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "results"
NAMES = ("gol_anonimizada.json", "gol_inconclusiva.json", "falha.json", "identificavel.json")
ANONYMOUS = re.compile(r"^CANAL_\d{2}$")


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)


def test_anonymize_renames_and_scales_but_keeps_dates(tmp_path):
    files = make_dataset(tmp_path / "src", n_days=60)
    mapping = dataset_config()["column_mapping"]
    factors = {"investment": 2.0, "kpi": 0.5}
    new_files, renamed = anonymize(files, mapping, tmp_path / "out", factors)

    before = pd.read_csv(files["investment_file"], dtype=str)
    after = pd.read_csv(new_files["investment_file"], dtype=str)
    assert sorted(renamed.values()) == [f"CANAL_{i:02d}" for i in range(1, len(renamed) + 1)]
    assert set(after["product_group"]) == set(renamed.values())
    assert list(after["dates"]) == list(before["dates"])
    ratio = after["total_revenue"].astype(float) / before["total_revenue"].astype(float)
    assert ratio.round(3).eq(2.0).all()
    kpi_before = pd.read_csv(files["performance_file"])["Sessions"]
    kpi_after = pd.read_csv(new_files["performance_file"])["Sessions"]
    assert (kpi_after - kpi_before * 0.5).abs().max() < 0.01
    assert new_files["generic_trends_file"].read_bytes() == files["generic_trends_file"].read_bytes()


def test_anonymize_is_deterministic_for_the_same_factors_file(tmp_path):
    files = make_dataset(tmp_path / "src", n_days=60)
    mapping = dataset_config()["column_mapping"]
    factors = load_factors(tmp_path / ".private" / "factors.json")
    assert factors == load_factors(tmp_path / ".private" / "factors.json")
    first, _ = anonymize(files, mapping, tmp_path / "a", factors)
    second, _ = anonymize(files, mapping, tmp_path / "b", factors)
    assert first["investment_file"].read_bytes() == second["investment_file"].read_bytes()


@pytest.mark.parametrize("name", NAMES)
def test_fixtures_validate_and_have_no_non_finite_numbers(name):
    text = (FIXTURES / name).read_text(encoding="utf-8")
    ResultsV1.model_validate(json.loads(text))
    json.loads(text, parse_constant=lambda token: pytest.fail(f"{token} in {name}"))


def test_fixtures_cover_what_the_screens_must_show():
    # no dataset reaches succeeded since A5/A6: the Gol has no identifiable channel, the synthetic one no event
    assert [_load(n)["status"] for n in NAMES] == ["inconclusive", "inconclusive", "failed", "inconclusive"]
    gol = _load("gol_anonimizada.json")
    events = gol["causal"]["events"]
    # since the audit fixes (09/nov/2026) the skill gate demotes every Gol event (high_oos_wmape): no fixture has a
    # published event; the E2E serves e2e_gol_publicado.json, the Gol as written before the fixes
    assert events and all(e["status"] == "rejected" for e in events)
    assert gol["sufficiency"]["reasons"] == ["high_oos_wmape"]
    assert gol["elasticity"]["reasons"] == ["no_identifiable_channel"]
    assert any("collinearity" in c["reasons"] for c in gol["elasticity"]["channels"])  # block_per_channel
    assert any("hill_at_bound" in c["reasons"] for c in gol["elasticity"]["channels"])
    assert _load("gol_inconclusiva.json")["causal"]["reasons"] == ["no_eligible_events"]
    assert _load("falha.json")["elasticity"]["reasons"] == ["model_failed"]
    channels = {c["name"]: c for c in _load("identificavel.json")["elasticity"]["channels"]}
    assert channels["STRONG"]["identifiable"] and channels["STRONG"]["curve"]
    assert not channels["NOEFFECT"]["identifiable"]


@pytest.mark.parametrize("name", NAMES[:2])
def test_fixtures_only_use_anonymous_channel_names(name):
    data = _load(name)
    channels = {c["name"] for c in data["elasticity"]["channels"]}
    channels |= {ch for d in data["causal"]["events_detected"] for ch in d["channels"]}
    channels |= {ch for e in data["causal"]["events"] for ch in e["channels"]}
    channels |= {ch for row in data["elasticity"]["response_curve"][:1] for mix in row["mix"].values() for ch in mix}
    channels |= {ch for m in data["baseline"]["monthly"] for ch in m["by_channel"]}
    assert channels and all(ANONYMOUS.match(c) or c == UNIDENTIFIED for c in channels)  # A5 pools hidden channels
    for text in _strings({k: v for k, v in data.items() if k != "reports"}):
        assert "exemplo_csv" not in text and "/" not in text
    assert all("exemplo_csv" not in text for text in _strings(data["reports"]))  # narratives quote dd/mm/yyyy dates


def _gol_available():
    return (GOL_DIR / "investment.csv").exists()


@pytest.mark.skipif(not _gol_available(), reason="needs exemplo_csv/Gol")
@pytest.mark.parametrize("name", NAMES[:2])
def test_fixtures_hide_the_original_data(name):
    text = (FIXTURES / name).read_text(encoding="utf-8")
    source = pd.read_csv(GOL_DIR / "investment.csv", encoding="utf-8-sig")
    for real in source[GOL_CONFIG["column_mapping"]["investment_file"]["channel_col"]].str.strip().unique():
        assert real not in text, f"real channel name {real!r} leaked into {name}"
    tokens = set(re.findall(r"(?<![\d.])\d{4,}(?![\d.])", text))
    originals = {str(v) for v in source["investment"] if v >= 1000}
    assert not tokens & originals, "an original investment value appears verbatim"


@pytest.mark.parametrize("name", NAMES)
def test_fixtures_carry_the_validation_report(name):
    report = ResultsV1.model_validate(_load(name)).validation
    assert report is not None and report.ok
    assert report.channels and report.date_range


@pytest.mark.parametrize("name", ["gol_anonimizada.json", "gol_inconclusiva.json", "identificavel.json", "falha.json"])
def test_fixtures_carry_the_deterministic_reports(name):
    document = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    reports = document["reports"]
    published = {e["id"] for e in (document["causal"] or {}).get("events", []) if e["status"] == "published"}
    assert set(reports["events"]) == published
    assert all(r["source"] == "deterministic" and r["grounding"] is None for r in reports["events"].values())
    assert reports["global"]["source"] == "deterministic"
    assert reports["grounding"] is None
