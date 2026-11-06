from copy import copy

from pydantic import ConfigDict, create_model

from engine.config import EngineConfig

# what the analyst edits on the parameters form; default and limits come from the engine (contract §1).
# treat_outliers stays at the engine's default: it takes a list of channels the generated form can't draw
ANALYST_FIELDS = (
    "optimization_target",
    "kpi_is_monetary",
    "average_ticket",
    "conversion_rate_from_kpi_to_bo",
    "financial_targets",
    "investment_limit_factor",
    "max_budget_step",
    "p_value_threshold",
    "min_pre_period_days",
    "post_event_days",
    "r_squared_threshold",
    "increase_threshold_percent",
    "decrease_threshold_percent",
    "max_events_to_analyze",
    "require_statistical_significance",
    "require_logical_direction",
    "require_model_fit",
    "controls",
)

ParamsIn = create_model(
    "ParamsIn",
    __config__=ConfigDict(extra="forbid", allow_inf_nan=False),
    **{
        name: (EngineConfig.model_fields[name].annotation, copy(EngineConfig.model_fields[name]))
        for name in ANALYST_FIELDS
    },
)
