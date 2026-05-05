from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class StockStNamechangeRecord:
    id: int
    ts_code: str
    name: str
    start_date: date
    end_date: date | None
    ann_date: date | None
    change_reason: str | None


@dataclass(frozen=True)
class StockStEventRecord:
    ts_code: str
    name: str | None
    pub_date: date
    imp_date: date | None
    st_type: str
    st_reason: str | None
    st_explain: str | None


@dataclass(frozen=True)
class StockStMissingDateContext:
    trade_date: date
    prev_date: date
    next_date: date
    prev_names: dict[str, str | None]
    next_names: dict[str, str | None]
    same_day_st_events: dict[str, tuple[StockStEventRecord, ...]]
    candidate_codes: tuple[str, ...]

    @property
    def prev_count(self) -> int:
        return len(self.prev_names)

    @property
    def next_count(self) -> int:
        return len(self.next_names)

    @property
    def st_same_day_count(self) -> int:
        return len(self.same_day_st_events)

    @property
    def candidate_count(self) -> int:
        return len(self.candidate_codes)


@dataclass(frozen=True)
class StockStResolvedCandidate:
    trade_date: date
    ts_code: str
    include: bool
    resolved_name: str | None
    name_source: str | None
    prev_name: str | None
    next_name: str | None
    selected_namechange: StockStNamechangeRecord | None
    active_namechange_row_count: int
    same_day_st_events: tuple[StockStEventRecord, ...]
    validation_status: str
    validation_message: str


@dataclass(frozen=True)
class StockStReviewItem:
    trade_date: date
    ts_code: str
    review_code: str
    review_message: str
    prev_name: str | None
    next_name: str | None
    selected_namechange: StockStNamechangeRecord | None
    same_day_st_events: tuple[StockStEventRecord, ...]


@dataclass(frozen=True)
class StockStMissingDatePreview:
    trade_date: date
    prev_date: date
    next_date: date
    prev_count: int
    next_count: int
    st_same_day_count: int
    candidate_count: int
    selected_namechange_count: int
    unresolved_candidate_count: int
    selected_non_st_count: int
    reconstructed_count: int
    validation_ok_total: int
    validation_not_ok_total: int
    manual_review_count: int
    candidates: tuple[StockStResolvedCandidate, ...]
    review_items: tuple[StockStReviewItem, ...]

    @property
    def is_apply_eligible(self) -> bool:
        return self.manual_review_count == 0 and self.validation_not_ok_total == 0


@dataclass(frozen=True)
class StockStPreviewArtifacts:
    output_dir: Path
    summary_path: Path
    preview_rows_path: Path
    manual_review_path: Path


@dataclass(frozen=True)
class StockStMissingDateRepairResult:
    artifacts: StockStPreviewArtifacts
    date_previews: tuple[StockStMissingDatePreview, ...]
    applied: bool
    applied_date_count: int
    applied_row_count: int
    skipped_review_dates: tuple[date, ...]

