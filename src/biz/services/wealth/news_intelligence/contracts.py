from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Mapping


class NewsSourceType(StrEnum):
    NEWS = "news"
    MAJOR_NEWS = "major_news"
    CCTV_NEWS = "cctv_news"


class ClassificationStatus(StrEnum):
    CLASSIFIED = "CLASSIFIED"
    UNRESOLVED = "UNRESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_NEWS = "NOT_NEWS"
    MIXED_CONTENT = "MIXED_CONTENT"
    INVALID_CONTENT = "INVALID_CONTENT"


class EventTypeStatus(StrEnum):
    CLASSIFIED = "CLASSIFIED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNRESOLVED = "UNRESOLVED"


class CandidateStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    EXCLUDED = "EXCLUDED"


class ModelStageStatus(StrEnum):
    NOT_RUN = "NOT_RUN"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    DEGRADED = "DEGRADED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


@dataclass(frozen=True, slots=True)
class ReplayWindow:
    scheduled_at: datetime
    start_at: datetime
    end_at: datetime
    timezone: str = "Asia/Shanghai"
    window_kind: str = "HISTORICAL_BUSINESS_TIME"

    def __post_init__(self) -> None:
        if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
            raise ValueError("replay window datetimes must be timezone-aware")
        if self.start_at >= self.end_at:
            raise ValueError("replay window start_at must be earlier than end_at")
        if self.scheduled_at != self.end_at:
            raise ValueError("scheduled_at must equal end_at")


@dataclass(frozen=True, slots=True)
class FrozenNewsItem:
    sample_id: str
    source_type: NewsSourceType
    source_key: str
    title: str
    content: str
    source_name: str
    published_at: datetime | None
    content_date: date | None
    fetched_at: datetime
    input_hash: str
    replay_assignment: str

    def __post_init__(self) -> None:
        if self.sample_id != f"m1:{self.source_type.value}:{self.source_key}":
            raise ValueError("sample_id does not match the stable M1 identity contract")
        if self.source_type is NewsSourceType.CCTV_NEWS:
            if self.published_at is not None or self.content_date is None:
                raise ValueError("cctv_news must use content_date without published_at")
        elif self.published_at is None:
            raise ValueError("timed news sources require published_at")


@dataclass(frozen=True, slots=True)
class CandidateDecision:
    sample_id: str
    status: CandidateStatus
    exclusion_code: str | None
    normalized_title: str
    normalized_content: str
    representative_text: str
    content_length: int
    sentence_count: int
    summary_eligible: bool
    exact_duplicate_of: str | None = None


@dataclass(frozen=True, slots=True)
class LabelCandidates:
    primary_topics: tuple[str, ...]
    event_types: tuple[str, ...]
    matched_rules: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EventCluster:
    event_id: str
    member_sample_ids: tuple[str, ...]
    representative_sample_id: str
    merge_evidence: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class ImportanceDimension:
    bucket: str
    score: int
    reason: str
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    event_id: str
    classification_status: ClassificationStatus
    primary_topic: str | None
    primary_subtopic: str | None
    secondary_topics: tuple[str, ...]
    event_type_status: EventTypeStatus
    primary_event_type: str | None
    related_event_types: tuple[str, ...]
    importance_dimensions: Mapping[str, ImportanceDimension]
    total_score: int
    raw_rank: int | None
    final_rank: int | None
    summary: str | None
    summary_evidence: tuple[str, ...]
    embedding_status: ModelStageStatus
    nli_status: ModelStageStatus
    generator_status: ModelStageStatus
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class M1Manifest:
    experiment_id: str
    created_at: datetime
    code_commit: str
    query_contract: str
    taxonomy_version: str
    scoring_version: str
    summary_version: str
    model_policy_version: str
    windows: tuple[ReplayWindow, ...]
    model_revisions: Mapping[str, str]
    parameters: Mapping[str, Any]
    artifact_schema_version: str = "news-intelligence-m1-artifact-v1"
    notes: tuple[str, ...] = field(default_factory=tuple)


def as_jsonable(value: object) -> object:
    """Convert immutable M1 contracts into deterministic JSON-compatible values."""
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "__dataclass_fields__"):
        return {key: as_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): as_jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [as_jsonable(item) for item in value]
    return value
