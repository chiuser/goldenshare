from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class NewsColdStorageSummary:
    row_count: int
    earliest_news_time: datetime | None
    latest_news_time: datetime | None
    rows_by_year: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class NewsColdStoragePreparation:
    partition_tablespaces: tuple[tuple[str, str], ...]
    partition_indexes: tuple[tuple[str, str, str], ...]


@dataclass(frozen=True)
class NewsColdStorageVerification:
    source: NewsColdStorageSummary
    stage: NewsColdStorageSummary
    source_missing_from_stage: int
    stage_missing_from_source: int

    @property
    def is_consistent(self) -> bool:
        return (
            self.source.row_count == self.stage.row_count
            and self.source.rows_by_year == self.stage.rows_by_year
            and self.source.earliest_news_time == self.stage.earliest_news_time
            and self.source.latest_news_time == self.stage.latest_news_time
            and self.source_missing_from_stage == 0
            and self.stage_missing_from_source == 0
        )


@dataclass(frozen=True)
class NewsColdStorageCopyResult:
    applied: bool
    copy_started_at: datetime | None
    rows_affected: int | None
    source: NewsColdStorageSummary
    stage_before_copy: NewsColdStorageSummary


@dataclass(frozen=True)
class NewsColdStorageCutoverResult:
    copy_started_at: datetime
    tail_rows_affected: int
    verification: NewsColdStorageVerification
