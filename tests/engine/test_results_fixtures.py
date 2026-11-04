import json
import re
from pathlib import Path

import pandas as pd
import pytest

from engine.results_schema import ResultsV1
from tests.engine.real_data import GOL_CONFIG, GOL_DIR
from tests.engine.synthetic_data import dataset_config, make_dataset
from tests.fixtures.results.anonymize_gol import anonymize, load_factors

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "results"
NAMES = ("gol_anonimizada.json", "gol_inconclusiva.json", "falha.json")
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


def test_fixtures_cover_the_three_statuses():
    assert [_load(n)["status"] for n in NAMES] == ["succeeded", "inconclusive", "failed"]
    events = _load("gol_anonimizada.json")["causal"]["events"]
    assert any(e["status"] == "published" for e in events) and any(e["status"] == "rejected" for e in events)
    assert _load("gol_inconclusiva.json")["causal"]["reasons"] == ["no_eligible_events"]
    assert _load("falha.json")["elasticity"]["reasons"] == ["model_failed"]


@pytest.mark.parametrize("name", NAMES[:2])
def test_fixtures_only_use_anonymous_channel_names(name):
    data = _load(name)
    channels = {c["name"] for c in data["elasticity"]["channels"]}
    channels |= {ch for d in data["causal"]["events_detected"] for ch in d["channels"]}
    channels |= {ch for e in data["causal"]["events"] for ch in e["channels"]}
    channels |= {ch for row in data["elasticity"]["response_curve"][:1] for mix in row["mix"].values() for ch in mix}
    channels |= {ch for m in data["baseline"]["monthly"] for ch in m["by_channel"]}
    assert channels and all(ANONYMOUS.match(c) for c in channels)
    for text in _strings(data):
        assert "exemplo_csv" not in text and "/" not in text


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
