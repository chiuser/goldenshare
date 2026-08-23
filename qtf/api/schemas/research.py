from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import Field, model_validator

from qtf.api.schemas.common import QtfApiModel


class CreateResearchRequest(QtfApiModel):
    request_key: str = Field(min_length=1, max_length=96)
    template_key: str = Field(min_length=1, max_length=96)
    title: str = Field(min_length=1, max_length=160)


class RankingRuleRequest(QtfApiModel):
    kind: Literal["PERCENTILE_GTE"]
    threshold: float = Field(ge=0, le=100)


class ParameterSelectionsRequest(QtfApiModel):
    baseline_days: list[Literal[60, 120]] = Field(min_length=1, max_length=2)
    trend_days: list[Literal[5, 10, 20, 30]] = Field(min_length=1, max_length=4)
    amount_lookback_days: Literal[20]
    ewma_lambda: float = Field(gt=0, le=1)
    price_weight: float = Field(ge=0, le=1)
    amount_weight: float = Field(ge=0, le=1)
    z_clip: float = Field(gt=0)
    signal_threshold: float = Field(ge=0, le=100)
    reset_threshold: float = Field(ge=0, le=100)
    up_move_share_min: float = Field(ge=0, le=1)
    future_horizons: tuple[Literal[1], Literal[3], Literal[5]]
    comparison_scope: Literal["SIBLINGS"]
    minimum_group_size: int = Field(ge=2)
    ranking_rule: RankingRuleRequest
    event_cluster_rule: Literal["RESET_ONLY"]

    @model_validator(mode="after")
    def validate_dependencies(self) -> "ParameterSelectionsRequest":
        if len(set(self.baseline_days)) != len(self.baseline_days):
            raise ValueError("baselineDays must contain unique values")
        if len(set(self.trend_days)) != len(self.trend_days):
            raise ValueError("trendDays must contain unique values")
        if abs((self.price_weight + self.amount_weight) - 1.0) > 1e-12:
            raise ValueError("priceWeight and amountWeight must sum to 1")
        if self.reset_threshold >= self.signal_threshold:
            raise ValueError("resetThreshold must be lower than signalThreshold")
        return self


class SaveDraftRequest(QtfApiModel):
    draft_version: int = Field(ge=1)
    problem_statement: str = Field(max_length=4_000)
    success_definition_keys: list[Literal["FUTURE_SIBLING_RANK_CONTINUATION"]] = Field(max_length=1)
    non_goal_keys: list[Literal["PER_SECTOR_TUNING", "PRODUCTION_RELEASE"]] = Field(max_length=2)
    parameter_selections: ParameterSelectionsRequest | None = None


class InputPreflightRequest(QtfApiModel):
    request_key: str = Field(min_length=1, max_length=96)
    draft_version: int = Field(ge=1)
    requested_start_date: date
    requested_end_date: date


class FreezeResearchRequest(QtfApiModel):
    request_key: str = Field(min_length=1, max_length=96)
    draft_version: int = Field(ge=1)
    input_preflight_key: str = Field(min_length=1, max_length=96)
    approved_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    acknowledged_exclusions: bool


class TemplateSummary(QtfApiModel):
    template_key: str
    title: str
    description: str
    capability_key: str
    formula_key: str
    formula_version: str
    parameter_schema_key: str
    parameter_schema_version: str


class TemplateListResponse(QtfApiModel):
    templates: list[TemplateSummary]


class ResearchTemplateView(QtfApiModel):
    template_key: str
    title: str
    description: str
    formula_key: str
    parameter_schema_key: str


class ScopeView(QtfApiModel):
    source_kind: str
    object_type: str
    object_count: int | None = None
    hierarchy_version: str | None = None
    comparison_scope: str
    candidate_trend_days: list[int]
    candidate_baseline_days: list[int]
    future_horizons: list[int]
    shared_parameter_scope: str
    run_policy: str
    data_responsibility: str


class ResearchEditorResponse(QtfApiModel):
    research_key: str
    revision_key: str
    revision_no: int
    draft_version: int
    revision_status: str
    research_status: str
    title: str
    template: ResearchTemplateView
    problem_statement: str
    success_definition_keys: list[str]
    non_goal_keys: list[str]
    parameter_selections: ParameterSelectionsRequest | None
    scope: ScopeView
    revision_hash: str | None
    can_edit: bool
    can_preflight: bool
    blocking_reasons: list[str]
    updated_at: datetime


class DatasetEvidenceView(QtfApiModel):
    dataset_key: str
    fields: list[str]
    start_date: date | None
    end_date: date | None
    row_count: int
    unique_key_status: str
    missing_count: int
    duplicate_count: int
    content_hash: str


class InputIssueView(QtfApiModel):
    code: str
    severity: str
    dataset_key: str
    trade_date: date | None
    field_name: str | None
    object_key: str | None
    message: str
    remediation_owner: str
    evidence: dict[str, object]


class PreflightView(QtfApiModel):
    preflight_key: str
    preflight_status: str
    source_kind: str
    as_of: datetime
    requested_start_date: date
    requested_end_date: date
    effective_start_date: date | None
    effective_end_date: date | None
    universe_count: int
    group_count: int
    valid_group_day_count: int
    excluded_group_day_count: int
    dataset_evidence: list[DatasetEvidenceView]
    issues: list[InputIssueView]
    content_hash: str


class SampleSplitView(QtfApiModel):
    kind: str
    in_sample_pct: int
    calibration_pct: int
    out_of_sample_pct: int


class PlanBudgetView(QtfApiModel):
    estimated_source_rows: int
    estimated_group_days: int
    parameter_combination_count: int
    execution_pass_count: int
    estimated_signal_event_rows: int
    estimated_runtime_seconds: int
    peak_memory_mb: int
    result_storage_mb: int
    source_statement_timeout_ms: int


class PlanView(QtfApiModel):
    parameter_matrix: list[dict[str, object]]
    fixed_parameters: dict[str, object]
    future_horizons: list[int]
    comparison_scope: str
    sample_split: SampleSplitView
    primary_objective: str
    success_definition: dict[str, object]
    hard_gates: list[str]
    stop_conditions: list[str]
    budget: PlanBudgetView
    estimator_version: str
    plan_hash: str


class FreezePlanResponse(QtfApiModel):
    research_key: str
    revision_key: str
    draft_version: int
    draft_hash: str
    preflight: PreflightView
    plan: PlanView | None
    can_freeze: bool
    blocking_reasons: list[str]
