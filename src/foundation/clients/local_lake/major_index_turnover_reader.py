from __future__ import annotations

import math
import time
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time as clock_time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from src.foundation.clients.local_lake.major_index_mins_contract import (
    EXPECTED_BARS_PER_SESSION,
    GOLD_BAR_COLUMN_SPECS,
    MAJOR_INDEX_MINS_GOLD_CODES,
    MAJOR_INDEX_TURNOVER_MAX_PARTITIONS,
    MAJOR_INDEX_TURNOVER_MAX_ROWS,
    major_index_minute_frequency_root,
)


class MajorIndexTurnoverReaderError(RuntimeError):
    code = "ITI_QUERY_FAILED"


class MajorIndexTurnoverRequestError(MajorIndexTurnoverReaderError):
    code = "ITI_SOURCE_CONTRACT_MISMATCH"


class MajorIndexTurnoverSourceContractError(MajorIndexTurnoverReaderError):
    code = "ITI_SOURCE_CONTRACT_MISMATCH"


class MajorIndexTurnoverCodeScopeError(MajorIndexTurnoverReaderError):
    code = "ITI_CODE_SCOPE_MISMATCH"


class MajorIndexTurnoverPointQualityError(MajorIndexTurnoverReaderError):
    code = "ITI_POINT_QUALITY_INVALID"


class MajorIndexTurnoverQueryError(MajorIndexTurnoverReaderError):
    code = "ITI_QUERY_FAILED"


@dataclass(frozen=True, slots=True)
class MajorIndexTurnoverReadRequest:
    trade_dates: tuple[date, ...]


@dataclass(frozen=True, slots=True)
class MajorIndexTurnoverMinuteRow:
    ts_code: str
    trade_date: date
    trade_time: datetime
    amount_yuan: Decimal


@dataclass(frozen=True, slots=True)
class MajorIndexTurnoverReadIssue:
    code: str
    ts_code: str | None
    trade_date: date | None
    detail: str


@dataclass(frozen=True, slots=True)
class MajorIndexTurnoverReadResult:
    rows: tuple[MajorIndexTurnoverMinuteRow, ...]
    available_trade_dates: tuple[date, ...]
    missing_trade_dates: tuple[date, ...]
    issues: tuple[MajorIndexTurnoverReadIssue, ...]
    scanned_file_count: int
    scanned_row_count: int
    elapsed_ms: int


@dataclass(frozen=True, slots=True)
class _PartitionFile:
    trade_date: date
    path: Path


class MajorIndexTurnoverLakeReader:
    def __init__(self, lake_root: Path) -> None:
        self._lake_root = lake_root.expanduser().resolve()
        if self._lake_root in {
            Path("/Volumes/datasource/data_lake_staging"),
            Path("/Volumes/datasource/goldenshare-tushare-lake"),
        }:
            raise MajorIndexTurnoverSourceContractError(
                "指数成交额只允许读取 DG 正式 Gold 根。"
            )

    def read(
        self, request: MajorIndexTurnoverReadRequest
    ) -> MajorIndexTurnoverReadResult:
        started = time.perf_counter()
        trade_dates = _normalize_trade_dates(request.trade_dates)
        partitions, missing_dates = self._resolve_partitions(trade_dates)
        if not partitions:
            return MajorIndexTurnoverReadResult(
                rows=(),
                available_trade_dates=(),
                missing_trade_dates=missing_dates,
                issues=(),
                scanned_file_count=0,
                scanned_row_count=0,
                elapsed_ms=_elapsed_ms(started),
            )

        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover - capability gate covers startup
            raise MajorIndexTurnoverQueryError("本地 DuckDB 依赖不可用。") from exc

        connection = duckdb.connect(database=":memory:", config={"threads": 4})
        try:
            paths = tuple(partition.path for partition in partitions)
            _validate_combined_schema(connection, paths)
            raw_rows, scanned_row_count = _query_rows(connection, paths)
        except MajorIndexTurnoverReaderError:
            raise
        except Exception as exc:
            raise MajorIndexTurnoverQueryError("指数成交额 Gold 批量查询失败。") from exc
        finally:
            connection.close()

        if scanned_row_count > MAJOR_INDEX_TURNOVER_MAX_ROWS:
            raise MajorIndexTurnoverSourceContractError(
                "指数成交额扫描行数超过有界合同。"
            )

        rows, issues = _validate_rows(
            raw_rows,
            partition_dates=frozenset(item.trade_date for item in partitions),
        )
        return MajorIndexTurnoverReadResult(
            rows=rows,
            available_trade_dates=tuple(item.trade_date for item in partitions),
            missing_trade_dates=missing_dates,
            issues=issues,
            scanned_file_count=len(partitions),
            scanned_row_count=scanned_row_count,
            elapsed_ms=_elapsed_ms(started),
        )

    def _resolve_partitions(
        self, trade_dates: tuple[date, ...]
    ) -> tuple[tuple[_PartitionFile, ...], tuple[date, ...]]:
        try:
            frequency_root = major_index_minute_frequency_root(
                self._lake_root, "bars", 1
            )
        except ValueError as exc:
            raise MajorIndexTurnoverSourceContractError(str(exc)) from exc

        partitions: list[_PartitionFile] = []
        missing: list[date] = []
        for trade_date in trade_dates:
            candidate = (
                frequency_root
                / f"trade_date={trade_date.isoformat()}"
                / "part-000.parquet"
            )
            if not candidate.exists():
                missing.append(trade_date)
                continue
            if _contains_symlink(candidate, stop=self._lake_root):
                raise MajorIndexTurnoverSourceContractError(
                    "指数成交额分区不得使用符号链接。"
                )
            resolved = candidate.resolve()
            if (
                not resolved.is_relative_to(self._lake_root)
                or not resolved.is_relative_to(frequency_root)
                or resolved.name != "part-000.parquet"
                or not resolved.is_file()
            ):
                raise MajorIndexTurnoverSourceContractError(
                    "指数成交额分区路径越界或不符合固定命名合同。"
                )
            partitions.append(_PartitionFile(trade_date=trade_date, path=resolved))
        return tuple(partitions), tuple(missing)


def _normalize_trade_dates(trade_dates: tuple[date, ...]) -> tuple[date, ...]:
    if not 1 <= len(trade_dates) <= MAJOR_INDEX_TURNOVER_MAX_PARTITIONS:
        raise MajorIndexTurnoverRequestError("trade_dates 数量必须在 1 到 24 之间。")
    if any(isinstance(value, datetime) or not isinstance(value, date) for value in trade_dates):
        raise MajorIndexTurnoverRequestError("trade_dates 必须只包含日期。")
    if len(set(trade_dates)) != len(trade_dates):
        raise MajorIndexTurnoverRequestError("trade_dates 不得重复。")
    if tuple(sorted(trade_dates, reverse=True)) != trade_dates:
        raise MajorIndexTurnoverRequestError("trade_dates 必须严格降序。")
    return trade_dates


def _contains_symlink(path: Path, *, stop: Path) -> bool:
    current = path
    while current != stop:
        if current.is_symlink():
            return True
        parent = current.parent
        if parent == current:
            return True
        current = parent
    return False


def _validate_combined_schema(connection: Any, paths: Sequence[Path]) -> None:
    try:
        description = connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?, hive_partitioning=false, union_by_name=false)",
            [list(map(str, paths))],
        ).fetchall()
    except Exception as exc:
        raise MajorIndexTurnoverSourceContractError(
            "指数成交额 Parquet schema 无法读取。"
        ) from exc
    actual = tuple((str(row[0]), _normalize_duckdb_type(row[1])) for row in description)
    if actual != GOLD_BAR_COLUMN_SPECS:
        raise MajorIndexTurnoverSourceContractError(
            "指数成交额 Parquet 列名、顺序或类型不符合 Gold 合同。"
        )


def _normalize_duckdb_type(value: Any) -> str:
    normalized = str(value).upper()
    if normalized.startswith("TIMESTAMP"):
        return "TIMESTAMP"
    if normalized in {"TEXT", "STRING"}:
        return "VARCHAR"
    return normalized


def _query_rows(
    connection: Any, paths: Sequence[Path]
) -> tuple[list[tuple[Any, ...]], int]:
    ordered_codes = tuple(sorted(MAJOR_INDEX_MINS_GOLD_CODES))
    code_placeholders = ", ".join("?" for _ in ordered_codes)
    sql = f"""
        WITH source AS MATERIALIZED (
          SELECT
            ts_code,
            CAST(freq AS INTEGER) AS freq,
            CAST(trade_date AS DATE) AS trade_date,
            CAST(trade_time AS TIMESTAMP) AS trade_time,
            amount,
            ts_code IN ({code_placeholders}) AS code_allowed,
            CAST(
              regexp_extract(filename, 'trade_date=([0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}})', 1)
              AS DATE
            ) AS partition_date,
            filename
          FROM read_parquet(
            ?, filename=true, hive_partitioning=false, union_by_name=false
          )
        ),
        contract AS (
          SELECT
            count(*) AS scanned_row_count,
            count(*) FILTER (WHERE freq IS NULL OR freq <> 1) AS invalid_freq_count,
            count(*) - count(DISTINCT (ts_code, trade_date, trade_time, freq)) AS duplicate_count
          FROM source
        ),
        target AS (
          SELECT * FROM source WHERE freq = 1
        )
        SELECT
          target.ts_code,
          target.freq,
          target.trade_date,
          target.trade_time,
          target.amount,
          target.code_allowed,
          target.partition_date,
          contract.scanned_row_count,
          contract.invalid_freq_count,
          contract.duplicate_count
        FROM contract LEFT JOIN target ON TRUE
        ORDER BY target.trade_date DESC, target.ts_code, target.trade_time
    """
    try:
        cursor = connection.execute(
            sql,
            [*ordered_codes, list(map(str, paths))],
        )
        fetched = cursor.fetchall()
    except Exception as exc:
        raise MajorIndexTurnoverQueryError("指数成交额 Gold 批量查询失败。") from exc
    if not fetched:
        return [], 0

    scanned_row_count = int(fetched[0][7])
    invalid_freq_count = int(fetched[0][8])
    duplicate_count = int(fetched[0][9])
    if invalid_freq_count:
        raise MajorIndexTurnoverSourceContractError(
            "指数成交额分区存在非 1 分钟频率。"
        )
    if duplicate_count:
        raise MajorIndexTurnoverPointQualityError(
            "指数成交额分区存在重复唯一键。"
        )
    rows = [row for row in fetched if row[0] is not None]
    return rows, scanned_row_count


def _validate_rows(
    raw_rows: Iterable[Sequence[Any]],
    *,
    partition_dates: frozenset[date],
) -> tuple[
    tuple[MajorIndexTurnoverMinuteRow, ...],
    tuple[MajorIndexTurnoverReadIssue, ...],
]:
    grouped: dict[tuple[str, date], list[MajorIndexTurnoverMinuteRow]] = defaultdict(list)
    invalid_groups: set[tuple[str, date]] = set()
    issues: list[MajorIndexTurnoverReadIssue] = []

    for raw in raw_rows:
        ts_code = str(raw[0])
        if not bool(raw[5]):
            raise MajorIndexTurnoverCodeScopeError(
                f"指数成交额分区出现固定十指数范围外代码：{ts_code}。"
            )
        trade_date = raw[2]
        trade_time = raw[3]
        if not isinstance(trade_date, date) or isinstance(trade_date, datetime):
            raise MajorIndexTurnoverSourceContractError(
                "指数成交额 trade_date 类型不符合合同。"
            )
        if not isinstance(trade_time, datetime):
            raise MajorIndexTurnoverSourceContractError(
                "指数成交额 trade_time 类型不符合合同。"
            )
        partition_date = raw[6]
        if not isinstance(partition_date, date) or isinstance(
            partition_date, datetime
        ):
            raise MajorIndexTurnoverSourceContractError(
                "指数成交额文件缺少有效日期分区。"
            )
        if partition_date not in partition_dates or trade_date != partition_date:
            raise MajorIndexTurnoverSourceContractError(
                "指数成交额行内日期与请求分区日期不一致。"
            )
        key = (ts_code, trade_date)
        if trade_time.date() != trade_date:
            invalid_groups.add(key)
            issues.append(
                MajorIndexTurnoverReadIssue(
                    code="ITI_POINT_QUALITY_INVALID",
                    ts_code=ts_code,
                    trade_date=trade_date,
                    detail="trade_time 日期与 trade_date 不一致。",
                )
            )
            continue
        try:
            amount = Decimal(str(raw[4]))
        except (InvalidOperation, ValueError, TypeError):
            amount = Decimal("NaN")
        if not amount.is_finite() or amount < 0:
            invalid_groups.add(key)
            issues.append(
                MajorIndexTurnoverReadIssue(
                    code="ITI_POINT_QUALITY_INVALID",
                    ts_code=ts_code,
                    trade_date=trade_date,
                    detail="amount 必须是有限且非负的元值。",
                )
            )
            continue
        grouped[key].append(
            MajorIndexTurnoverMinuteRow(
                ts_code=ts_code,
                trade_date=trade_date,
                trade_time=trade_time,
                amount_yuan=amount,
            )
        )

    expected_times = _expected_trade_times()
    for trade_date in sorted(partition_dates, reverse=True):
        for ts_code in sorted(MAJOR_INDEX_MINS_GOLD_CODES):
            key = (ts_code, trade_date)
            rows = grouped.get(key, [])
            actual_times = tuple(row.trade_time.time() for row in rows)
            if not rows:
                invalid_groups.add(key)
                issues.append(
                    MajorIndexTurnoverReadIssue(
                        code="ITI_SOURCE_NOT_READY",
                        ts_code=ts_code,
                        trade_date=trade_date,
                        detail="该日期缺少当前指数分钟数据。",
                    )
                )
            elif len(rows) != EXPECTED_BARS_PER_SESSION[1] or actual_times != expected_times:
                invalid_groups.add(key)
                issues.append(
                    MajorIndexTurnoverReadIssue(
                        code="ITI_TIME_GRID_MISMATCH",
                        ts_code=ts_code,
                        trade_date=trade_date,
                        detail=(
                            "分钟点必须精确匹配 1 分钟 241 点规范时间网格；"
                            f"实际 {len(rows)} 点。"
                        ),
                    )
                )

    valid_rows = tuple(
        row
        for key in sorted(grouped, key=lambda value: (value[1], value[0]), reverse=True)
        if key not in invalid_groups
        for row in grouped[key]
    )
    return valid_rows, tuple(_deduplicate_issues(issues))


def _expected_trade_times() -> tuple[clock_time, ...]:
    morning_start = datetime.combine(date.min, clock_time(9, 30))
    afternoon_start = datetime.combine(date.min, clock_time(13, 1))
    return tuple(
        (morning_start + timedelta(minutes=offset)).time() for offset in range(121)
    ) + tuple(
        (afternoon_start + timedelta(minutes=offset)).time() for offset in range(120)
    )


def _deduplicate_issues(
    issues: Iterable[MajorIndexTurnoverReadIssue],
) -> Iterable[MajorIndexTurnoverReadIssue]:
    seen: set[tuple[str, str | None, date | None]] = set()
    for issue in issues:
        identity = (issue.code, issue.ts_code, issue.trade_date)
        if identity in seen:
            continue
        seen.add(identity)
        yield issue


def _elapsed_ms(started: float) -> int:
    return max(0, math.ceil((time.perf_counter() - started) * 1000))
