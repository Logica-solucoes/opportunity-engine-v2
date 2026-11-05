import copy
import re
from pathlib import Path

import pytest

from engine.config import EngineConfig
from engine.errors import EngineError
from tests.engine.synthetic_data import dataset_config

ENGINE_DIR = Path(__file__).resolve().parents[2] / "engine"
KEY_READ = re.compile(r"""\b(?:config|cfg)(?:\.get\(\s*|\[\s*)["'](\w+)["']""")
RUNTIME_KEYS = {
    "period_days",  # detected from the data, never an input
    "average_ticket_value",  # old alias read as a fallback inside .get("average_ticket", ...); removed in phase 2
}


def test_defaults_match_the_spec():
    c = EngineConfig()
    assert c.optimization_target == "CONVERSIONS" and c.kpi_is_monetary is False
    assert c.average_ticket is None and c.conversion_rate_from_kpi_to_bo == 1.0
    assert c.investment_limit_factor == 1.5 and c.max_budget_step == 0.2
    assert c.p_value_threshold == 0.05 and c.r_squared_threshold == 0.3 and c.min_pre_period_days == 14
    assert (c.increase_threshold_percent, c.decrease_threshold_percent) == (50, 30)
    assert (c.post_event_days, c.max_events_to_analyze) == (14, 5)
    assert c.require_statistical_significance and c.require_logical_direction and c.require_model_fit
    assert c.country_code == "BR" and c.per_channel_investment_limit_factor == 3.0
    assert c.max_channel_mix_share == 0.4 and c.min_marketing_contribution == 0.05
    assert c.reallocation_min_cv_r2 == 0.1 and c.minimum_acceptable_iroi == 0
    assert c.treat_outliers is False and c.channel_groups == [] and c.controls == []


def test_extra_key_is_an_engine_error_naming_the_field():
    with pytest.raises(EngineError) as raised:
        EngineConfig.from_input({"require_significance": True})
    assert "require_significance" in str(raised.value)
    assert "Configuração inválida" in str(raised.value)


def test_revenue_requires_average_ticket():
    with pytest.raises(EngineError) as raised:
        EngineConfig.from_input({"optimization_target": "REVENUE"})
    assert "average_ticket" in str(raised.value)
    assert EngineConfig.from_input({"optimization_target": "REVENUE", "average_ticket": 90}).average_ticket == 90


def test_out_of_range_value_names_the_field():
    with pytest.raises(EngineError) as raised:
        EngineConfig.from_input({"p_value_threshold": 2})
    assert "p_value_threshold" in str(raised.value)


def test_inf_is_rejected():
    with pytest.raises(EngineError):
        EngineConfig.from_input({"average_ticket": float("inf")})


def test_from_input_does_not_mutate_the_input():
    raw = dataset_config()
    before = copy.deepcopy(raw)
    EngineConfig.from_input(raw).to_legacy_dict()
    assert raw == before


def test_from_input_accepts_an_engine_config():
    c = EngineConfig(post_event_days=21)
    copied = EngineConfig.from_input(c)
    assert copied == c and copied is not c


def test_legacy_dict_omits_unset_targets():
    assert EngineConfig().to_legacy_dict()["financial_targets"] == {}
    c = EngineConfig.from_input({"financial_targets": {"target_cpa": 25}})
    assert c.to_legacy_dict()["financial_targets"] == {"target_cpa": 25.0}


def test_legacy_dict_derives_kpi_column_and_drops_paths():
    legacy = EngineConfig.from_input(dataset_config()).to_legacy_dict()
    assert legacy["performance_kpi_column"] == "Sessions"
    assert EngineConfig().to_legacy_dict()["performance_kpi_column"] == "Sessions"
    for gone in ("investment_file_path", "performance_file_path", "generic_trends_file_path", "output_directory"):
        assert gone not in legacy


def test_legacy_dict_never_holds_none_where_the_modules_do_arithmetic():
    legacy = EngineConfig().to_legacy_dict()
    assert legacy["average_ticket"] == 0
    assert legacy["client_industry"] == "their industry" and legacy["client_business_goal"] == ""


def test_dataset_config_round_trips_through_the_model():
    legacy = EngineConfig.from_input(dataset_config()).to_legacy_dict()
    assert legacy["investment_limit_factor"] == 1.5 and legacy["require_model_fit"] is False
    assert legacy["financial_targets"] == dataset_config()["financial_targets"]


def test_legacy_dict_covers_every_key_the_modules_read():
    keys = set()
    for path in ENGINE_DIR.glob("*.py"):
        keys |= set(KEY_READ.findall(path.read_text(encoding="utf-8")))
    missing = keys - set(EngineConfig().to_legacy_dict()) - RUNTIME_KEYS
    assert not missing, f"to_legacy_dict() lacks keys the engine reads: {sorted(missing)}"


def test_block_per_channel_defaults_to_false():
    assert EngineConfig().block_per_channel is False


@pytest.mark.parametrize("bad", [{"collinearity_r": 1.5}, {"collinearity_r": 0}, {"vif_max": 0.5}, {"vif_max": "x"}])
def test_invalid_gate_threshold_is_an_engine_error(bad):
    with pytest.raises(EngineError, match="gate_thresholds"):
        EngineConfig.from_input({"gate_thresholds": bad})


def test_unknown_gate_threshold_key_is_accepted():
    assert (
        EngineConfig.from_input({"gate_thresholds": {"outra_chave": 1}}).to_legacy_dict()["gate_thresholds"][
            "outra_chave"
        ]
        == 1
    )


def test_gate_threshold_defaults_live_in_the_config_schema():
    """The front reads defaults from the JSON Schema, so they must be in EngineConfig and not only in the loader."""
    schema = EngineConfig.model_json_schema()
    gate = schema["$defs"]["GateThresholds"]["properties"]
    assert gate["collinearity_r"]["default"] == 0.85 and gate["vif_max"]["default"] == 10
    assert EngineConfig().gate_thresholds.collinearity_r == 0.85


@pytest.mark.parametrize("bad", [{"vif_max": float("inf")}, {"collinearity_r": True}, {"vif_max": True}])
def test_gate_threshold_rejects_inf_and_bool(bad):
    with pytest.raises(EngineError, match="gate_thresholds"):
        EngineConfig.from_input({"gate_thresholds": bad})


def test_control_spend_corr_default_is_in_the_schema():
    gate = EngineConfig.model_json_schema()["$defs"]["GateThresholds"]["properties"]
    assert gate["control_spend_corr"]["default"] == 0.5
    assert EngineConfig().gate_thresholds.control_spend_corr == 0.5


@pytest.mark.parametrize("bad", [0, 1.5, True, "x"])
def test_invalid_control_spend_corr(bad):
    with pytest.raises(EngineError, match="gate_thresholds"):
        EngineConfig.from_input({"gate_thresholds": {"control_spend_corr": bad}})


def test_controls_are_normalized():
    assert EngineConfig.from_input({"controls": [" Selic ", "Selic", "IPCA"]}).controls == ["Selic", "IPCA"]


@pytest.mark.parametrize("bad", [[""], [3], ["  "]])
def test_invalid_controls(bad):
    with pytest.raises(EngineError, match="controls"):
        EngineConfig.from_input({"controls": bad})


def test_identifiability_width_ratio_default_is_in_the_schema():
    gate = EngineConfig.model_json_schema()["$defs"]["GateThresholds"]["properties"]
    assert gate["identifiability_width_ratio"]["default"] == 1.0


@pytest.mark.parametrize("bad", [0, -1, True, "x"])
def test_invalid_identifiability_width_ratio(bad):
    with pytest.raises(EngineError, match="gate_thresholds"):
        EngineConfig.from_input({"gate_thresholds": {"identifiability_width_ratio": bad}})
