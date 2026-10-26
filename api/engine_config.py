from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ponytail: stand-in for engine/config.py (A0, docs/m2/README.md contract §1). Names and defaults of the causal
# fields are provisional; when engine/ exists EngineConfig comes from there and ParamsIn follows its fields


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class FinancialTargets(Strict):
    target_cpa: float | None = Field(default=None, gt=0)
    target_icpa: float | None = Field(default=None, gt=0)
    target_roas: float | None = Field(default=None, gt=0)
    target_iroas: float | None = Field(default=None, gt=0)


class ParamsIn(Strict):
    """What the analyst fills in on the parameters form."""

    optimization_target: Literal["REVENUE", "CONVERSIONS"] = "CONVERSIONS"
    kpi_is_monetary: bool = False
    average_ticket: float | None = Field(default=None, gt=0)
    conversion_rate_from_kpi_to_bo: float = Field(default=1.0, gt=0, le=1)
    financial_targets: FinancialTargets = Field(default_factory=FinancialTargets)
    investment_limit_factor: float = Field(default=1.5, gt=1, le=5)
    max_budget_step: float = Field(default=0.2, gt=0, le=1)
    p_value_threshold: float = Field(default=0.05, gt=0, lt=1)
    min_pre_period_days: int = Field(default=28, ge=7)
    r_squared_threshold: float = Field(default=0.5, ge=0, le=1)
    increase_threshold_percent: float = Field(default=20, gt=0)
    decrease_threshold_percent: float = Field(default=20, gt=0)
    require_significance: bool = True
    require_good_fit: bool = True


class EngineConfig(ParamsIn):
    # written by other screens: the mapping (B2), groups (A3) and controls (A4)
    column_mapping: dict = Field(default_factory=dict)
    channel_groups: list[list[str]] = Field(default_factory=list)
    controls: list[str] = Field(default_factory=list)
    gate_thresholds: dict = Field(default_factory=dict)
