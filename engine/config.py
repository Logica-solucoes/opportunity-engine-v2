"""EngineConfig: the single source of the engine's parameters and defaults.

The analytical modules still read a plain dict with `config.get(...)`; `to_legacy_dict()` builds it from this model.
"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from engine.errors import EngineError


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class FinancialTargets(Strict):
    target_cpa: float | None = Field(default=None, gt=0)
    target_icpa: float | None = Field(default=None, gt=0)
    target_roas: float | None = Field(default=None, gt=0)
    target_iroas: float | None = Field(default=None, gt=0)


class GateThresholds(BaseModel):
    """Limits of the publication gates. Keys other than the known ones are kept (the Admin screen and later items add more)."""

    model_config = ConfigDict(extra="allow", allow_inf_nan=False)

    collinearity_r: float = Field(default=0.85, gt=0, le=1, strict=True)  # a pair is flagged when |r| is above this
    vif_max: float = Field(default=10.0, ge=1, strict=True)  # a channel is flagged when its VIF is above this
    control_spend_corr: float = Field(
        default=0.5, gt=0, le=1, strict=True
    )  # a control above this |r| with the spend is out


class EngineConfig(Strict):
    # --- parameters the analyst edits (form) ---
    # CONVERSIONS, not the prototype's REVENUE: REVENUE needs average_ticket, so it cannot be a default
    optimization_target: Literal["REVENUE", "CONVERSIONS"] = "CONVERSIONS"
    kpi_is_monetary: bool = False
    average_ticket: float | None = Field(default=None, gt=0)
    conversion_rate_from_kpi_to_bo: float = Field(default=1.0, gt=0, le=1)
    financial_targets: FinancialTargets = Field(default_factory=FinancialTargets)
    investment_limit_factor: float = Field(default=1.5, gt=1, le=5)
    max_budget_step: float = Field(default=0.2, gt=0, le=1)
    p_value_threshold: float = Field(default=0.05, gt=0, lt=1)
    min_pre_period_days: int = Field(default=14, ge=7)
    r_squared_threshold: float = Field(default=0.3, ge=0, le=1)
    increase_threshold_percent: float = Field(default=50, gt=0)
    decrease_threshold_percent: float = Field(default=30, gt=0, le=100)
    post_event_days: int = Field(default=14, ge=1)
    max_events_to_analyze: int = Field(default=5, ge=1)
    treat_outliers: bool | list[str] = False
    require_statistical_significance: bool = True
    require_logical_direction: bool = True
    require_model_fit: bool = True

    # --- filled by the system ---
    column_mapping: dict = Field(default_factory=dict)
    date_formats: dict = Field(default_factory=dict)
    channel_groups: list[list[str]] = Field(default_factory=list)
    controls: list[str] = Field(default_factory=list)
    gate_thresholds: GateThresholds = Field(default_factory=lambda: GateThresholds())
    block_per_channel: bool = False
    product_group_filter: list[str] | None = None
    min_intervention_date: str | None = None
    country_code: str = "BR"
    per_channel_investment_limit_factor: float = Field(default=3.0, gt=1)
    max_channel_mix_share: float = Field(default=0.4, gt=0, le=1)
    minimum_acceptable_iroi: float = Field(default=0, ge=0)
    min_marketing_contribution: float = Field(default=0.05, ge=0, lt=1)
    reallocation_min_cv_r2: float = 0.1

    # --- report metadata (optional) ---
    advertiser_name: str = "default_advertiser"
    client_industry: str | None = None
    client_business_goal: str | None = None
    primary_business_metric_name: str = "KPIs"

    @field_validator("controls", mode="before")
    @classmethod
    def _normalize_controls(cls, value):
        if not isinstance(value, list):
            return value
        names: list[str] = []
        for name in value:
            if not isinstance(name, str) or not name.strip():
                raise ValueError("cada controle deve ser o nome de uma coluna do arquivo de tendências")
            if name.strip() not in names:
                names.append(name.strip())
        return names

    @model_validator(mode="after")
    def _revenue_needs_a_ticket(self) -> Self:
        if self.optimization_target == "REVENUE" and not self.average_ticket:
            raise ValueError("average_ticket é obrigatório quando optimization_target é REVENUE")
        return self

    @classmethod
    def from_input(cls, config: "dict | EngineConfig") -> "EngineConfig":
        """Validate without touching the input; a bad config becomes an EngineError that names the fields."""
        if isinstance(config, EngineConfig):
            return config.model_copy(deep=True)
        try:
            return cls.model_validate(config)
        except ValidationError as e:
            raise EngineError("Configuração inválida: " + "; ".join(_describe(err) for err in e.errors())) from e

    def to_legacy_dict(self) -> dict:
        """Every key the analytical modules read. An unset target is an absent key (the modules default it to
        'no target'); None never reaches arithmetic."""
        legacy = self.model_dump(exclude={"financial_targets"})
        legacy["financial_targets"] = self.financial_targets.model_dump(exclude_none=True)
        legacy["average_ticket"] = self.average_ticket or 0
        legacy["client_industry"] = self.client_industry or "their industry"
        legacy["client_business_goal"] = self.client_business_goal or ""
        kpi_col = self.column_mapping.get("performance_file", {}).get("kpi_col")
        legacy["performance_kpi_column"] = kpi_col or "Sessions"
        return legacy


def _describe(err: dict) -> str:
    where = ".".join(str(part) for part in err["loc"])
    if err["type"] == "extra_forbidden":
        return f"campo '{where}' não é reconhecido pelo motor"
    message = err["msg"].removeprefix("Value error, ")
    return f"campo '{where}': {message}" if where else message
