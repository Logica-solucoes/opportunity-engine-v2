import pytest

from api.engine_config import EngineConfig, ParamsIn


@pytest.fixture
def analyst(make_user):
    return make_user("ana@x.com")


@pytest.fixture
def ws(make_workspace, analyst):
    return make_workspace("a", [(analyst, "analyst")])


@pytest.fixture
def logged(client, analyst, ws, login_as):
    login_as(client, analyst)
    return client


def test_config_schema_lists_only_the_form_fields(logged):
    schema = logged.get("/api/engine/config-schema").json()

    props = schema["properties"]
    assert props["investment_limit_factor"]["default"] == 1.5
    assert props["optimization_target"]["enum"] == ["REVENUE", "CONVERSIONS"]
    assert {"column_mapping", "channel_groups", "controls", "gate_thresholds"}.isdisjoint(props)


def test_engine_config_is_the_form_fields_plus_the_rest():
    config = EngineConfig()

    assert config.max_budget_step == 0.2 and config.column_mapping == {}
    assert set(ParamsIn.model_fields) < set(EngineConfig.model_fields)
