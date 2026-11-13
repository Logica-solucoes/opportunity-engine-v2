import copy
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

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
    assert c.block_per_channel is False and c.gate_thresholds == {}
    assert c.experiment_target_lift == 0.05 and c.experiment_max_days == 90


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


def test_channel_groups_are_normalized_like_the_channels():
    assert EngineConfig(channel_groups=[[" pmax", "Search "]]).channel_groups == [["PMAX", "SEARCH"]]


@pytest.mark.parametrize(
    ("groups", "message"),
    [
        ([["PMAX"]], "cada grupo precisa de pelo menos dois canais diferentes"),
        ([["PMAX", "pmax"]], "cada grupo precisa de pelo menos dois canais diferentes"),
        ([["PMAX", "SEARCH"], ["SEARCH", "YOUTUBE"]], "o canal SEARCH está em mais de um grupo"),
    ],
)
def test_bad_channel_groups_are_an_invalid_config(groups, message):
    with pytest.raises(EngineError) as raised:
        EngineConfig.from_input({"channel_groups": groups})
    assert str(raised.value) == f"Configuração inválida: campo 'channel_groups': {message}"


def test_gate_threshold_falls_back_to_the_default():
    assert EngineConfig().gate_threshold("collinearity_r") == 0.85
    assert EngineConfig(gate_thresholds={"collinearity_r": 0.9}).gate_threshold("collinearity_r") == 0.9


def test_unknown_gate_is_an_invalid_config():
    with pytest.raises(EngineError) as raised:
        EngineConfig.from_input({"gate_thresholds": {"colinearity_r": 0.9}})
    assert str(raised.value) == "Configuração inválida: campo 'gate_thresholds': limite desconhecido: colinearity_r"


@pytest.mark.parametrize("value", [85, 1.0, 0, -0.1])
def test_gate_threshold_outside_zero_one_is_an_invalid_config(value):
    with pytest.raises(EngineError) as raised:
        EngineConfig.from_input({"gate_thresholds": {"collinearity_r": value}})
    assert str(raised.value) == "Configuração inválida: campo 'gate_thresholds': limite fora de (0, 1): collinearity_r"


def test_channel_group_members_are_deduplicated_in_order():
    assert EngineConfig(channel_groups=[["a", "A", "b"]]).channel_groups == [["A", "B"]]


def test_controls_accept_only_the_bcb_series_and_drop_repeats():
    assert EngineConfig(controls=["bcb_ipca", "bcb_ipca", "bcb_selic"]).controls == ["bcb_ipca", "bcb_selic"]
    assert EngineConfig().controls == []
    with pytest.raises(ValidationError):
        EngineConfig(controls=["Clicks"])


def test_control_spend_corr_defaults_to_half_and_reaches_the_legacy_dict():
    assert EngineConfig().to_legacy_dict()["control_spend_corr"] == 0.5
    tuned = EngineConfig(gate_thresholds={"control_spend_corr": 0.7})
    assert tuned.to_legacy_dict()["control_spend_corr"] == 0.7


def test_the_new_gates_have_provisional_defaults_and_reach_the_legacy_dict():
    config = EngineConfig()
    assert config.gate_threshold("vif_max") == 10.0
    legacy = config.to_legacy_dict()
    assert legacy["spend_cv_min"] == 0.10 and legacy["oos_wmape_max"] == 0.30 and legacy["oos_skill_min"] == 0.10


def test_the_vif_limit_must_be_above_one():
    assert EngineConfig(gate_thresholds={"vif_max": 5.0}).gate_threshold("vif_max") == 5.0
    for value in (1.0, 0.5):
        with pytest.raises(EngineError) as raised:
            EngineConfig.from_input({"gate_thresholds": {"vif_max": value}})
        assert (
            str(raised.value) == "Configuração inválida: campo 'gate_thresholds': limite deve ser maior que 1: vif_max"
        )


@pytest.mark.parametrize("name", ["spend_cv_min", "oos_wmape_max", "oos_skill_min"])
def test_the_a6_limits_are_in_zero_one(name):
    with pytest.raises(EngineError) as raised:
        EngineConfig.from_input({"gate_thresholds": {name: 1.5}})
    assert str(raised.value) == f"Configuração inválida: campo 'gate_thresholds': limite fora de (0, 1): {name}"


def test_max_budget_step_has_a_floor():
    with pytest.raises(EngineError, match="max_budget_step"):
        EngineConfig.from_input({"max_budget_step": 0.001})
    assert EngineConfig.from_input({"max_budget_step": 0.01}).max_budget_step == 0.01
