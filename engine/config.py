"""EngineConfig: the single source of the engine's parameters and defaults.

The analytical modules still read a plain dict with `config.get(...)`; `to_legacy_dict()` builds it from this model.
"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from engine.errors import EngineError

# gate thresholds (A3); A4 adds control_spend_corr and A5 collinearity_vif when they use them
GATE_DEFAULTS = {"collinearity_r": 0.85}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class FinancialTargets(Strict):
    target_cpa: float | None = Field(default=None, gt=0)
    target_icpa: float | None = Field(default=None, gt=0)
    target_roas: float | None = Field(default=None, gt=0)
    target_iroas: float | None = Field(default=None, gt=0)


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
    gate_thresholds: dict[str, float] = Field(default_factory=dict)
    block_per_channel: bool = False  # the analyst accepts results only at the aggregate level (A3 gate; effect in A5)
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

    @field_validator("channel_groups")
    @classmethod
    def _groups_are_disjoint(cls, groups: list[list[str]]) -> list[list[str]]:
        groups = [
            list(dict.fromkeys(name.strip().upper() for name in group)) for group in groups
        ]  # as the reader normalizes channels
        seen: set[str] = set()
        for group in groups:
            if len(set(group)) < 2:
                raise ValueError("cada grupo precisa de pelo menos dois canais diferentes")
            repeated = seen & set(group)
            if repeated:
                raise ValueError(f"o canal {min(repeated)} está em mais de um grupo")
            seen |= set(group)
        return groups

    @field_validator("gate_thresholds")
    @classmethod
    def _known_gates(cls, thresholds: dict[str, float]) -> dict[str, float]:
        unknown = sorted(set(thresholds) - set(GATE_DEFAULTS))
        if unknown:
            raise ValueError(f"limite desconhecido: {', '.join(unknown)}")
        return thresholds

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

    def gate_threshold(self, name: str) -> float:
        return {**GATE_DEFAULTS, **self.gate_thresholds}[name]


def _describe(err: dict) -> str:
    where = ".".join(str(part) for part in err["loc"])
    if err["type"] == "extra_forbidden":
        return f"campo '{where}' não é reconhecido pelo motor"
    message = err["msg"].removeprefix("Value error, ")
    return f"campo '{where}': {message}" if where else message
