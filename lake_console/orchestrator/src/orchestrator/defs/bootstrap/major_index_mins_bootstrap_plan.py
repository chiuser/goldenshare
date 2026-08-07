"""Request-free Bootstrap planning for major-index minute data."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
from time import perf_counter

from orchestrator.defs.duckdb_sql import read_parquet
from orchestrator.defs.io.major_index_mins_quality import (
    prepare_major_index_mins_raw_expected_tables,
    prepare_major_index_mins_silver_expected_tables,
    validate_major_index_mins_raw_relation,
    validate_major_index_mins_silver_relation,
)
from orchestrator.defs.paths import (
    raw_major_index_mins_path,
    silver_major_index_mins_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.major_index_mins import (
    MAJOR_INDEX_MINS_BOOTSTRAP_DISK_SAFETY_MULTIPLIER,
    MAJOR_INDEX_MINS_BOOTSTRAP_MAX_REQUESTS,
    MAJOR_INDEX_MINS_BOOTSTRAP_WINDOW_TRADING_DAYS,
    MAJOR_INDEX_MINS_HISTORY_START_DATE,
    MAJOR_INDEX_MINS_SCOPE_REVISION,
    MAJOR_INDEX_MINS_SILVER_FREQS,
    MAJOR_INDEX_MINS_SOURCE_FREQS,
    MAJOR_INDEX_MINS_SOURCE_SCOPES,
    effective_raw_request_codes_for_date,
    effective_silver_codes_for_date,
    major_index_mins_exchange_for_code,
    major_index_mins_session_times,
)


_SAMPLE_LIMIT = 20
_RAW_ESTIMATED_BYTES_PER_ROW = 256
_SILVER_ESTIMATED_BYTES_PER_ROW = 320


class MajorIndexMinsBootstrapPlanError(ValueError):
    """Raised when the read-only Bootstrap plan cannot be trusted."""


def _hash_payload(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class MajorIndexMinsDatePlan:
    start_date: str
    end_date: str
    expected_trade_dates: tuple[str, ...]
    fingerprint: str

    def to_dict(self) -> dict[str, object]:
        samples = tuple(
            dict.fromkeys(
                (*self.expected_trade_dates[:3], *self.expected_trade_dates[-3:])
            )
        )
        return {
            "start_date": self.start_date,
            "end_date": self.end_date,
            "expected_date_count": len(self.expected_trade_dates),
            "expected_date_samples": list(samples),
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True, slots=True)
class MajorIndexMinsSourceWindow:
    window_id: str
    ts_code: str
    source_freq: str
    trade_dates: tuple[str, ...]
    start_datetime: str
    end_datetime: str
    expected_row_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "window_id": self.window_id,
            "ts_code": self.ts_code,
            "source_freq": self.source_freq,
            "start_date": self.trade_dates[0],
            "end_date": self.trade_dates[-1],
            "trade_date_count": len(self.trade_dates),
            "expected_row_count": self.expected_row_count,
        }


@dataclass(frozen=True, slots=True)
class MajorIndexMinsSourcePlan:
    windows: tuple[MajorIndexMinsSourceWindow, ...]
    fingerprint: str
    expected_row_count: int
    request_count_by_frequency: Mapping[str, int]

    def to_dict(self) -> dict[str, object]:
        return {
            "fingerprint": self.fingerprint,
            "scope_revision": MAJOR_INDEX_MINS_SCOPE_REVISION,
            "code_count": len(MAJOR_INDEX_MINS_SOURCE_SCOPES),
            "frequency_count": len(MAJOR_INDEX_MINS_SOURCE_FREQS),
            "window_count": len(self.windows),
            "base_request_count": len(self.windows),
            "expected_row_count": self.expected_row_count,
            "request_count_by_frequency": dict(self.request_count_by_frequency),
            "window_samples": [
                window.to_dict() for window in (*self.windows[:3], *self.windows[-3:])
            ],
        }


@dataclass(frozen=True, slots=True)
class MajorIndexMinsTargetAudit:
    layer: str
    expected_file_count: int
    missing_count: int
    valid_existing_count: int
    invalid_existing_count: int
    existing_row_count: int
    existing_bytes: int
    elapsed_ms: float
    invalid_samples: tuple[Mapping[str, object], ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self) | {
            "invalid_samples": [dict(value) for value in self.invalid_samples]
        }


@dataclass(frozen=True, slots=True)
class MajorIndexMinsDiskBudget:
    disk_free_bytes: int
    estimated_source_staging_bytes: int
    estimated_raw_bytes: int
    estimated_silver_bytes: int
    estimated_required_bytes: int
    safety_multiplier: float
    passed: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MajorIndexMinsBootstrapDryRunReport:
    generated_at: str
    lake_root: str
    date_plan: MajorIndexMinsDatePlan
    source_plan: MajorIndexMinsSourcePlan
    target_audits: tuple[MajorIndexMinsTargetAudit, ...]
    disk_budget: MajorIndexMinsDiskBudget
    expected_raw_file_count: int
    expected_silver_file_count: int
    expected_file_count: int
    should_stop: bool
    stop_reason_codes: tuple[str, ...]
    elapsed_ms: float

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "generated_at": self.generated_at,
            "lake_root": self.lake_root,
            "date_plan": self.date_plan.to_dict(),
            "source_plan": self.source_plan.to_dict(),
            "source_request_count": 0,
            "target_audits": [value.to_dict() for value in self.target_audits],
            "disk_budget": self.disk_budget.to_dict(),
            "expected_raw_file_count": self.expected_raw_file_count,
            "expected_silver_file_count": self.expected_silver_file_count,
            "expected_file_count": self.expected_file_count,
            "should_stop": self.should_stop,
            "stop_reason_codes": list(self.stop_reason_codes),
            "elapsed_ms": round(self.elapsed_ms, 3),
            "writes": {
                "formal_lake": 0,
                "dagster_db": 0,
                "dynamic_partitions": 0,
                "dagster_events": 0,
            },
        }


def build_date_plan(
    *,
    connection,
    lake_root: Path,
    end_date: str | None = None,
) -> MajorIndexMinsDatePlan:
    calendar_path = silver_trade_calendar_path(lake_root)
    if not calendar_path.exists():
        raise MajorIndexMinsBootstrapPlanError(
            f"silver trade calendar is missing: {calendar_path}"
        )
    rows = connection.execute(
        """
        SELECT CAST(trade_date AS DATE)::VARCHAR, count(*)
        FROM read_parquet(?)
        WHERE exchange = 'SSE'
          AND is_open = true
          AND CAST(trade_date AS DATE) >= CAST(? AS DATE)
        GROUP BY CAST(trade_date AS DATE)
        ORDER BY CAST(trade_date AS DATE)
        """,
        [str(calendar_path), MAJOR_INDEX_MINS_HISTORY_START_DATE],
    ).fetchall()
    if not rows:
        raise MajorIndexMinsBootstrapPlanError("no SSE open dates in Bootstrap range")
    duplicate_dates = tuple(str(row[0]) for row in rows if int(row[1]) != 1)
    if duplicate_dates:
        raise MajorIndexMinsBootstrapPlanError(
            f"duplicate SSE calendar dates: {duplicate_dates[:_SAMPLE_LIMIT]!r}"
        )
    latest_calendar_date = str(rows[-1][0])
    normalized_end = str(end_date or latest_calendar_date)
    try:
        parsed_end = date.fromisoformat(normalized_end)
    except ValueError as error:
        raise MajorIndexMinsBootstrapPlanError(
            f"invalid Bootstrap end date: {normalized_end!r}"
        ) from error
    if parsed_end > date.today():
        raise MajorIndexMinsBootstrapPlanError("Bootstrap end date is in the future")
    expected = tuple(str(row[0]) for row in rows if str(row[0]) <= normalized_end)
    if not expected:
        raise MajorIndexMinsBootstrapPlanError(
            "Bootstrap end date precedes the history start"
        )
    return MajorIndexMinsDatePlan(
        start_date=expected[0],
        end_date=expected[-1],
        expected_trade_dates=expected,
        fingerprint=_hash_payload(
            {
                "scope_revision": MAJOR_INDEX_MINS_SCOPE_REVISION,
                "trade_dates": expected,
            }
        ),
    )


def build_source_plan(
    date_plan: MajorIndexMinsDatePlan,
) -> MajorIndexMinsSourcePlan:
    windows: list[MajorIndexMinsSourceWindow] = []
    request_count_by_frequency: Counter[str] = Counter()
    for scope in MAJOR_INDEX_MINS_SOURCE_SCOPES:
        eligible_dates = tuple(
            trade_date
            for trade_date in date_plan.expected_trade_dates
            if scope.eligible_on(trade_date)
        )
        if not eligible_dates:
            continue
        exchange = major_index_mins_exchange_for_code(scope.ts_code)
        for frequency in MAJOR_INDEX_MINS_SOURCE_FREQS:
            window_size = MAJOR_INDEX_MINS_BOOTSTRAP_WINDOW_TRADING_DAYS[frequency]
            expected_per_date = len(
                major_index_mins_session_times(
                    exchange=exchange,
                    source_freq=frequency,
                )
            )
            for offset in range(0, len(eligible_dates), window_size):
                trade_dates = eligible_dates[offset : offset + window_size]
                start_datetime = f"{trade_dates[0]} 09:00:00"
                end_datetime = f"{trade_dates[-1]} 16:00:00"
                identity = {
                    "scope_revision": MAJOR_INDEX_MINS_SCOPE_REVISION,
                    "ts_code": scope.ts_code,
                    "source_freq": frequency,
                    "start_datetime": start_datetime,
                    "end_datetime": end_datetime,
                }
                windows.append(
                    MajorIndexMinsSourceWindow(
                        window_id=_hash_payload(identity),
                        ts_code=scope.ts_code,
                        source_freq=frequency,
                        trade_dates=trade_dates,
                        start_datetime=start_datetime,
                        end_datetime=end_datetime,
                        expected_row_count=len(trade_dates) * expected_per_date,
                    )
                )
                request_count_by_frequency[frequency] += 1
    if len(windows) > MAJOR_INDEX_MINS_BOOTSTRAP_MAX_REQUESTS:
        raise MajorIndexMinsBootstrapPlanError(
            "Bootstrap request budget exceeded: "
            f"count={len(windows)}, max={MAJOR_INDEX_MINS_BOOTSTRAP_MAX_REQUESTS}"
        )
    payload = [
        {
            "id": value.window_id,
            "expected_rows": value.expected_row_count,
        }
        for value in windows
    ]
    return MajorIndexMinsSourcePlan(
        windows=tuple(windows),
        fingerprint=_hash_payload(payload),
        expected_row_count=sum(value.expected_row_count for value in windows),
        request_count_by_frequency=dict(request_count_by_frequency),
    )


def audit_bootstrap_targets(
    *,
    connection,
    lake_root: Path,
    date_plan: MajorIndexMinsDatePlan,
) -> tuple[MajorIndexMinsTargetAudit, ...]:
    specs = {
        "raw": (
            MAJOR_INDEX_MINS_SOURCE_FREQS,
            raw_major_index_mins_path,
        ),
        "silver": (
            MAJOR_INDEX_MINS_SILVER_FREQS,
            silver_major_index_mins_path,
        ),
    }
    audits: list[MajorIndexMinsTargetAudit] = []
    for layer, (frequencies, path_builder) in specs.items():
        started_at = perf_counter()
        missing_count = 0
        valid_existing_count = 0
        invalid_existing_count = 0
        existing_row_count = 0
        existing_bytes = 0
        invalid_samples: list[Mapping[str, object]] = []
        for trade_date in date_plan.expected_trade_dates:
            expected_codes = (
                effective_raw_request_codes_for_date(trade_date)
                if layer == "raw"
                else effective_silver_codes_for_date(trade_date)
            )
            for frequency in frequencies:
                path = path_builder(lake_root, frequency, trade_date)
                if not path.exists():
                    missing_count += 1
                    continue
                existing_bytes += path.stat().st_size
                try:
                    relation_sql = read_parquet(path, hive_partitioning=False)
                    if layer == "raw":
                        prepare_major_index_mins_raw_expected_tables(
                            connection,
                            expected_codes=expected_codes,
                            frequency=frequency,
                            partition_key=trade_date,
                        )
                        validation = validate_major_index_mins_raw_relation(
                            connection,
                            relation_sql=relation_sql,
                            expected_codes=expected_codes,
                            frequency=frequency,
                            partition_key=trade_date,
                        )
                    else:
                        prepare_major_index_mins_silver_expected_tables(
                            connection,
                            expected_codes=expected_codes,
                            frequency=frequency,
                        )
                        validation = validate_major_index_mins_silver_relation(
                            connection,
                            relation_sql=relation_sql,
                            expected_codes=expected_codes,
                            frequency=frequency,
                            partition_key=trade_date,
                            require_null_vwap=frequency in {"90min", "120min"},
                        )
                    existing_row_count += validation.row_count
                    if validation.errors:
                        raise MajorIndexMinsBootstrapPlanError(
                            f"existing target core check failed: {validation.errors!r}"
                        )
                    valid_existing_count += 1
                except Exception as error:  # noqa: BLE001 - conflict audit fails closed.
                    invalid_existing_count += 1
                    if len(invalid_samples) < _SAMPLE_LIMIT:
                        invalid_samples.append(
                            {
                                "layer": layer,
                                "trade_date": trade_date,
                                "frequency": frequency,
                                "path": str(path),
                                "error_type": type(error).__name__,
                            }
                        )
        expected_file_count = len(date_plan.expected_trade_dates) * len(frequencies)
        audits.append(
            MajorIndexMinsTargetAudit(
                layer=layer,
                expected_file_count=expected_file_count,
                missing_count=missing_count,
                valid_existing_count=valid_existing_count,
                invalid_existing_count=invalid_existing_count,
                existing_row_count=existing_row_count,
                existing_bytes=existing_bytes,
                elapsed_ms=(perf_counter() - started_at) * 1000,
                invalid_samples=tuple(invalid_samples),
            )
        )
    return tuple(audits)


def _derived_expected_rows(date_plan: MajorIndexMinsDatePlan) -> int:
    total = 0
    for trade_date in date_plan.expected_trade_dates:
        for code in effective_silver_codes_for_date(trade_date):
            exchange = major_index_mins_exchange_for_code(code)
            total += len(
                major_index_mins_session_times(
                    exchange=exchange,
                    source_freq="90min",
                )
            )
            total += len(
                major_index_mins_session_times(
                    exchange=exchange,
                    source_freq="120min",
                )
            )
    return total


def _disk_budget(
    *,
    lake_root: Path,
    source_plan: MajorIndexMinsSourcePlan,
    date_plan: MajorIndexMinsDatePlan,
) -> MajorIndexMinsDiskBudget:
    source_staging_bytes = source_plan.expected_row_count * _RAW_ESTIMATED_BYTES_PER_ROW
    raw_bytes = source_plan.expected_row_count * _RAW_ESTIMATED_BYTES_PER_ROW
    silver_rows = source_plan.expected_row_count + _derived_expected_rows(date_plan)
    silver_bytes = silver_rows * _SILVER_ESTIMATED_BYTES_PER_ROW
    required = math.ceil(
        (source_staging_bytes + raw_bytes + silver_bytes)
        * MAJOR_INDEX_MINS_BOOTSTRAP_DISK_SAFETY_MULTIPLIER
    )
    free = shutil.disk_usage(lake_root).free
    return MajorIndexMinsDiskBudget(
        disk_free_bytes=free,
        estimated_source_staging_bytes=source_staging_bytes,
        estimated_raw_bytes=raw_bytes,
        estimated_silver_bytes=silver_bytes,
        estimated_required_bytes=required,
        safety_multiplier=MAJOR_INDEX_MINS_BOOTSTRAP_DISK_SAFETY_MULTIPLIER,
        passed=free >= required,
    )


def run_dry_run(
    *,
    lake_root: Path,
    duckdb_resource: DuckDBResource | None = None,
    end_date: str | None = None,
) -> MajorIndexMinsBootstrapDryRunReport:
    started_at = perf_counter()
    duckdb_resource = duckdb_resource or DuckDBResource()
    with duckdb_resource.connect() as connection:
        date_plan = build_date_plan(
            connection=connection,
            lake_root=lake_root,
            end_date=end_date,
        )
        source_plan = build_source_plan(date_plan)
        target_audits = audit_bootstrap_targets(
            connection=connection,
            lake_root=lake_root,
            date_plan=date_plan,
        )
    disk_budget = _disk_budget(
        lake_root=lake_root,
        source_plan=source_plan,
        date_plan=date_plan,
    )
    stop_reasons: list[str] = []
    if any(value.invalid_existing_count for value in target_audits):
        stop_reasons.append("invalid_existing_target")
    if not disk_budget.passed:
        stop_reasons.append("insufficient_disk_space")
    raw_files = len(date_plan.expected_trade_dates) * len(MAJOR_INDEX_MINS_SOURCE_FREQS)
    silver_files = len(date_plan.expected_trade_dates) * len(
        MAJOR_INDEX_MINS_SILVER_FREQS
    )
    return MajorIndexMinsBootstrapDryRunReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        lake_root=str(lake_root),
        date_plan=date_plan,
        source_plan=source_plan,
        target_audits=target_audits,
        disk_budget=disk_budget,
        expected_raw_file_count=raw_files,
        expected_silver_file_count=silver_files,
        expected_file_count=raw_files + silver_files,
        should_stop=bool(stop_reasons),
        stop_reason_codes=tuple(dict.fromkeys(stop_reasons)),
        elapsed_ms=(perf_counter() - started_at) * 1000,
    )


def write_report(
    report: MajorIndexMinsBootstrapDryRunReport,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


__all__ = [
    "MajorIndexMinsBootstrapDryRunReport",
    "MajorIndexMinsBootstrapPlanError",
    "MajorIndexMinsDatePlan",
    "MajorIndexMinsSourcePlan",
    "MajorIndexMinsSourceWindow",
    "audit_bootstrap_targets",
    "build_date_plan",
    "build_source_plan",
    "run_dry_run",
    "write_report",
]
