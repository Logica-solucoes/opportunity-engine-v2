"""The results.json contract (docs/m2/README.md §3), version 1.

Sections owned by later items (A2, A5-A9) are typed here and stay None until those items fill them. Adding an optional
field does not change `schema_version`; removing or renaming one does.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1

RunStatus = Literal["succeeded", "inconclusive", "failed"]
SectionStatus = Literal["ok", "inconclusive", "failed"]
EventStatus = Literal["published", "rejected"]
ScenarioName = Literal[
    "current", "max_efficiency", "strategic_limit", "diminishing_return", "saturation", "strategic_reallocation"
]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- owned by later items (shape from the README; the owner tightens the free-form parts) ---


class Check(_Model):
    id: str
    level: Literal["error", "warning", "info"]
    message: str
    details: dict[str, Any] | None = None


class Collinearity(_Model):
    pairs: list[dict[str, Any]] = Field(default_factory=list)
    vif: dict[str, float | None] = Field(default_factory=dict)
    suggested_groups: list[list[str]] = Field(default_factory=list)


class ValidationReport(_Model):
    ok: bool
    cadence: str | None = None
    period_days: int | None = None
    date_range: list[str] | None = None
    channels: list[str] = Field(default_factory=list)
    checks: list[Check] = Field(default_factory=list)
    collinearity: Collinearity | None = None


class Sufficiency(_Model):
    passed: bool
    spend_variation: dict[str, Any] | None = None
    validated_events: int | None = None
    pre_wmape: float | None = None
    reasons: list[str] = Field(default_factory=list)
    cv_out_of_sample: bool | None = None


ExperimentDesign = dict[str, Any]


class Grounding(_Model):
    status: Literal["passed", "regenerated", "blocked"]
    issues: list[Any] = Field(default_factory=list)


class Reports(_Model):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    events: dict[str, dict[str, Any]] = Field(default_factory=dict)
    global_: dict[str, Any] | None = Field(default=None, alias="global")
    grounding: Grounding | None = None


# --- causal ---


class EventDetected(_Model):
    date: str
    channels: list[str]
    investment_change_pct: float | None = None
    eligible: bool


class Lift(_Model):
    abs: float | None = None
    ci: tuple[float | None, float | None] | None = None
    rel_pct: float | None = None


class Fit(_Model):
    r2: float | None = None
    mae: float | None = None
    mape: float | None = None
    wmape: float | None = None


class Placebo(_Model):
    p_value: float | None = None
    passed: bool | None = None


class Robustness(_Model):
    p_value: float | None = None  # p-value of the lift under a model without the media features
    passed: bool | None = None  # False: significant only with them (`model_dependent`); None: did not run


class LinePoint(_Model):
    date: str
    actual_kpi: float | None = None
    investment: float | None = None
    forecasted_kpi: float | None = None


class AccuracyPoint(_Model):
    date: str
    kpi: float | None = None
    predicted: float | None = None
    mae: float | None = None


class InvestmentPoint(_Model):
    period: str
    investment: float | None = None


class KpiPoint(_Model):
    category: str
    kpi: float | None = None


class EventSeries(_Model):
    line: list[LinePoint] = Field(default_factory=list)
    accuracy: list[AccuracyPoint] = Field(default_factory=list)
    investment: list[InvestmentPoint] = Field(default_factory=list)
    kpi: list[KpiPoint] = Field(default_factory=list)


class RejectedControl(_Model):
    name: str
    r: float  # signed correlation with the treated channel's spend in the pre-period


class EventControls(_Model):
    used: list[str] = Field(default_factory=list)
    rejected: list[RejectedControl] = Field(default_factory=list)


class CausalEvent(_Model):
    id: str
    channels: list[str]
    status: EventStatus
    reasons: list[str] = Field(default_factory=list)
    selected: bool = False
    start: str | None = None
    end: str | None = None
    lift: Lift | None = None
    p_value: float | None = None
    investment_change_pct: float | None = None
    incremental_investment: float | None = None
    cpa_incremental: float | None = None
    fit: Fit | None = None
    placebo: Placebo | None = None
    robustness: Robustness | None = None
    controls: EventControls | None = None
    series: EventSeries | None = None


class Causal(_Model):
    status: SectionStatus
    reasons: list[str] = Field(default_factory=list)
    events_detected: list[EventDetected] = Field(default_factory=list)
    events: list[CausalEvent] = Field(default_factory=list)


# --- elasticity ---


class ElasticityMetrics(_Model):
    cv_r2: float | None = None
    r2: float | None = None
    media_contribution_pct: float | None = None
    low_confidence: bool | None = None
    reallocation_suppressed: bool | None = None


class Hill(_Model):
    K: float | None = None
    n: float | None = None


class CurvePoint(_Model):
    x: float | None = None
    y: float | None = None
    lo: float | None = None
    hi: float | None = None
    extrapolated: bool | None = None


class ChannelFit(_Model):
    name: str
    contribution_pct: float | None = None
    identifiable: bool | None = None
    coef_ci: tuple[float | None, float | None] | None = None
    hill: Hill | None = None
    adstock: float | None = None
    observed_spend_range: tuple[float | None, float | None] | None = None
    curve: list[CurvePoint] = Field(default_factory=list)
    reasons: list[str] = Field(
        default_factory=list
    )  # why identifiable is false: ci_crosses_zero, ci_too_wide, collinearity


class Group(_Model):
    name: str
    members: list[str]


class ResponseRow(_Model):
    investment: float | None = None
    kpi: float | None = None
    kpi_lo: float | None = None
    kpi_hi: float | None = None
    revenue: float | None = None
    icpa: float | None = None
    iroas: float | None = None
    incremental_investment: float | None = None
    incremental_kpi: float | None = None
    extrapolated: bool | None = None
    mix: dict[str, dict[str, float | None]] = Field(default_factory=dict)  # historical | optimized | strategic


class Scenario(_Model):
    name: ScenarioName
    investment: float | None = None
    kpi: float | None = None
    kpi_lo: float | None = None
    kpi_hi: float | None = None
    icpa: float | None = None
    cpa: float | None = None
    roas: float | None = None
    incremental_investment: float | None = None
    incremental_kpi: float | None = None
    extrapolated: bool | None = None
    ramp: list[dict[str, Any]] | None = None


class Unidentified(_Model):
    """The channels the data cannot tell apart from zero (or from each other): only their total is published."""

    channels: list[str] = Field(default_factory=list)
    contribution_pct: float | None = None


class Elasticity(_Model):
    status: SectionStatus
    reasons: list[str] = Field(default_factory=list)
    metrics: ElasticityMetrics | None = None
    channels: list[ChannelFit] = Field(default_factory=list)
    groups: list[Group] = Field(default_factory=list)
    unidentified: Unidentified | None = None
    response_curve: list[ResponseRow] = Field(default_factory=list)
    scenarios: list[Scenario] = Field(default_factory=list)


# --- baseline and root ---


class MonthlyBaseline(_Model):
    month: str
    kpi: float | None = None
    investment: float | None = None
    by_channel: dict[str, float | None] = Field(default_factory=dict)


class Baseline(_Model):
    monthly: list[MonthlyBaseline] = Field(default_factory=list)


class ResultsV1(_Model):
    schema_version: Literal[1] = SCHEMA_VERSION
    engine_version: str
    status: RunStatus
    validation: ValidationReport | None = None
    sufficiency: Sufficiency | None = None
    causal: Causal | None = None
    elasticity: Elasticity | None = None
    experiment_design: ExperimentDesign | None = None
    reports: Reports | None = None
    baseline: Baseline | None = None
