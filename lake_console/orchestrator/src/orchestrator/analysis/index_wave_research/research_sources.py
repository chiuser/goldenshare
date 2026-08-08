"""Bounded DuckDB readers for the index-wave read-only research harness."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Final

import duckdb

from ..index_wave.bars import SHANGHAI_TIMEZONE, CanonicalBar, InputContractError
from .source_adapters import (
    INDEX_DAILY_FREQ,
    INDEX_DAILY_SOURCE_CONTRACT_VERSION,
    MAJOR_INDEX_120M_FREQ,
    MAJOR_INDEX_120M_SOURCE_CONTRACT_VERSION,
    adapt_index_daily_rows,
    adapt_major_index_120m_rows,
)


DEFAULT_LAKE_ROOT: Final = Path("/Volumes/datasource/data_lake")
MAJOR_INDEX_RESEARCH_CODES: Final = (
    "000001.SH",
    "399001.SZ",
    "399006.SZ",
    "000688.SH",
    "000300.SH",
    "000905.SH",
    "000852.SH",
    "000510.SH",
    "000016.SH",
    "000680.SH",
)
SUPPORTED_RESEARCH_FREQUENCIES: Final = (INDEX_DAILY_FREQ, MAJOR_INDEX_120M_FREQ)
PARQUET_SCAN_BATCH_SIZE: Final = 256


@dataclass(frozen=True, slots=True)
class SourceManifest:
    source_contract_version: str
    data_snapshot_id: str
    file_count: int
    total_bytes: int
    visible_through: date


@dataclass(frozen=True, slots=True)
class SourceExclusion:
    trade_date: date
    reason_code: str
    missing_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LoadedSeries:
    ts_code: str
    freq: str
    bars: tuple[CanonicalBar, ...]
    expected_trade_date_count: int
    observed_trade_date_count: int
    first_bar_at: datetime
    last_bar_at: datetime
    data_snapshot_id: str
    source_exclusions: tuple[SourceExclusion, ...]


def classify_daily_reference_observations(
    rows: list[dict[str, object]],
) -> tuple[list[dict[str, object]], tuple[SourceExclusion, ...]]:
    """Separate leading close-only base points; never drop malformed K-lines."""

    required_prices = ("open", "high", "low", "close")
    first_complete = next(
        (
            index
            for index, row in enumerate(rows)
            if all(row.get(field) is not None for field in required_prices)
        ),
        None,
    )
    if first_complete is None:
        raise InputContractError(
            "SOURCE_DAILY_NO_COMPLETE_BAR", "daily source has no complete OHLC row"
        )
    exclusions: list[SourceExclusion] = []
    for row in rows[:first_complete]:
        missing = tuple(field for field in required_prices if row.get(field) is None)
        if missing != ("open", "high", "low") or row.get("close") is None:
            raise InputContractError(
                "SOURCE_DAILY_LEADING_ROW_INVALID",
                "only a leading close-only reference observation may be excluded",
            )
        raw_trade_date = row.get("trade_date")
        if not isinstance(raw_trade_date, date):
            raise InputContractError(
                "SOURCE_TRADE_DATE_INVALID",
                "reference observation has invalid trade_date",
            )
        exclusions.append(
            SourceExclusion(
                trade_date=raw_trade_date,
                reason_code="LEADING_CLOSE_ONLY_REFERENCE_OBSERVATION",
                missing_fields=missing,
            )
        )
    return rows[first_complete:], tuple(exclusions)


def _local_as_of(as_of: datetime) -> datetime:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return as_of.astimezone(SHANGHAI_TIMEZONE)


def _partition_date(path: Path) -> date | None:
    for parent in path.parents:
        if parent.name.startswith("trade_date="):
            try:
                return date.fromisoformat(parent.name.removeprefix("trade_date="))
            except ValueError:
                return None
    return None


def build_source_manifest(
    *,
    lake_root: Path,
    freq: str,
    visible_through: date,
) -> SourceManifest:
    if freq == INDEX_DAILY_FREQ:
        source_root = lake_root / "silver/index_daily"
        contract = INDEX_DAILY_SOURCE_CONTRACT_VERSION
    elif freq == MAJOR_INDEX_120M_FREQ:
        source_root = lake_root / "silver/quote/major_index_mins/freq=120min"
        contract = MAJOR_INDEX_120M_SOURCE_CONTRACT_VERSION
    else:
        raise ValueError(f"unsupported research frequency: {freq}")
    files = tuple(
        path
        for path in sorted(source_root.glob("trade_date=*/part-*.parquet"))
        if (_partition_date(path) or date.max) <= visible_through
    )
    calendar_file = lake_root / "silver/calendar/trade_calendar/full/part-000.parquet"
    if not files:
        raise FileNotFoundError(f"no visible source files under {source_root}")
    if not calendar_file.is_file():
        raise FileNotFoundError(f"trade calendar is missing: {calendar_file}")
    hasher = sha256()
    hasher.update(contract.encode())
    hasher.update(visible_through.isoformat().encode())
    total_bytes = 0
    for path in files + (calendar_file,):
        stat = path.stat()
        total_bytes += stat.st_size
        hasher.update(str(path.relative_to(lake_root)).encode())
        hasher.update(str(stat.st_size).encode())
        hasher.update(str(stat.st_mtime_ns).encode())
    return SourceManifest(
        source_contract_version=contract,
        data_snapshot_id=f"sha256:{hasher.hexdigest()}",
        file_count=len(files) + 1,
        total_bytes=total_bytes,
        visible_through=visible_through,
    )


class IndexWaveLakeReader:
    """Read only the selected code/frequency columns from Silver Parquet."""

    def __init__(self, lake_root: Path = DEFAULT_LAKE_ROOT) -> None:
        self.lake_root = lake_root
        self._connection = duckdb.connect(database=":memory:")
        self._connection.execute("SET threads=1")

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "IndexWaveLakeReader":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _rows(self, sql: str, parameters: list[object]) -> list[dict[str, object]]:
        cursor = self._connection.execute(sql, parameters)
        names = tuple(item[0] for item in cursor.description)
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    def _source_files(self, freq: str, visible_through: date) -> tuple[str, ...]:
        if freq == INDEX_DAILY_FREQ:
            source_root = self.lake_root / "silver/index_daily"
        elif freq == MAJOR_INDEX_120M_FREQ:
            source_root = self.lake_root / "silver/quote/major_index_mins/freq=120min"
        else:
            raise ValueError(f"unsupported research frequency: {freq}")
        return tuple(
            str(path)
            for path in sorted(source_root.glob("trade_date=*/part-*.parquet"))
            if (_partition_date(path) or date.max) <= visible_through
        )

    def _batched_source_rows(
        self,
        *,
        sql: str,
        files: tuple[str, ...],
        parameters: list[object],
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for start in range(0, len(files), PARQUET_SCAN_BATCH_SIZE):
            batch = list(files[start : start + PARQUET_SCAN_BATCH_SIZE])
            rows.extend(self._rows(sql, [batch, *parameters]))
        return rows

    def _open_dates(self, start: date, end: date) -> tuple[date, ...]:
        calendar_path = (
            self.lake_root / "silver/calendar/trade_calendar/full/part-000.parquet"
        )
        rows = self._connection.execute(
            """
            SELECT trade_date
            FROM read_parquet(?, hive_partitioning = false)
            WHERE exchange = 'SSE'
              AND is_open = true
              AND trade_date BETWEEN ? AND ?
            ORDER BY trade_date
            """,
            [str(calendar_path), start, end],
        ).fetchall()
        return tuple(row[0] for row in rows)

    def load_series(
        self,
        *,
        ts_code: str,
        freq: str,
        as_of: datetime,
        manifest: SourceManifest,
    ) -> LoadedSeries:
        if ts_code not in MAJOR_INDEX_RESEARCH_CODES:
            raise ValueError(
                f"ts_code is outside the frozen research universe: {ts_code}"
            )
        local_as_of = _local_as_of(as_of)
        if freq == INDEX_DAILY_FREQ:
            bars, source_exclusions = self._load_daily(
                ts_code,
                local_as_of,
                manifest.data_snapshot_id,
                manifest.visible_through,
            )
        elif freq == MAJOR_INDEX_120M_FREQ:
            bars = self._load_120m(
                ts_code,
                local_as_of,
                manifest.data_snapshot_id,
                manifest.visible_through,
            )
            source_exclusions = ()
        else:
            raise ValueError(f"unsupported research frequency: {freq}")
        observed_dates = tuple(dict.fromkeys(bar.trade_date for bar in bars))
        return LoadedSeries(
            ts_code=ts_code,
            freq=freq,
            bars=bars,
            expected_trade_date_count=len(observed_dates),
            observed_trade_date_count=len(observed_dates),
            first_bar_at=bars[0].bar_end_at,
            last_bar_at=bars[-1].bar_end_at,
            data_snapshot_id=manifest.data_snapshot_id,
            source_exclusions=source_exclusions,
        )

    def _load_daily(
        self,
        ts_code: str,
        as_of: datetime,
        data_snapshot_id: str,
        visible_through: date,
    ) -> tuple[tuple[CanonicalBar, ...], tuple[SourceExclusion, ...]]:
        rows = self._batched_source_rows(
            sql="""
            SELECT ts_code, trade_date, open, high, low, close, vol, amount
            FROM read_parquet(?, hive_partitioning = false, union_by_name = true)
            WHERE ts_code = ?
              AND CAST(trade_date AS TIMESTAMP) + INTERVAL 15 HOUR <= ?
            ORDER BY trade_date
            """,
            files=self._source_files(INDEX_DAILY_FREQ, visible_through),
            parameters=[ts_code, as_of.replace(tzinfo=None)],
        )
        if not rows:
            raise InputContractError(
                "SOURCE_SERIES_EMPTY", f"no daily rows for {ts_code}"
            )
        rows, exclusions = classify_daily_reference_observations(rows)
        observed_dates = tuple(row["trade_date"] for row in rows)
        expected_dates = self._open_dates(observed_dates[0], observed_dates[-1])
        bars = adapt_index_daily_rows(
            rows,
            ts_code=ts_code,
            data_snapshot_id=data_snapshot_id,
            as_of=as_of,
            expected_trade_dates=expected_dates,
        )
        if tuple(bar.trade_date for bar in bars) != expected_dates:
            raise InputContractError(
                "SOURCE_DAILY_COVERAGE_MISMATCH",
                "daily bars do not cover every open date",
            )
        return bars, exclusions

    def _load_120m(
        self,
        ts_code: str,
        as_of: datetime,
        data_snapshot_id: str,
        visible_through: date,
    ) -> tuple[CanonicalBar, ...]:
        rows = self._batched_source_rows(
            sql="""
            SELECT ts_code, freq, trade_time, open, high, low, close, vol, amount
            FROM read_parquet(?, hive_partitioning = false, union_by_name = true)
            WHERE ts_code = ?
              AND freq = '120min'
              AND trade_time <= ?
            ORDER BY trade_time
            """,
            files=self._source_files(MAJOR_INDEX_120M_FREQ, visible_through),
            parameters=[ts_code, as_of.replace(tzinfo=None)],
        )
        if not rows:
            raise InputContractError(
                "SOURCE_SERIES_EMPTY", f"no 120m rows for {ts_code}"
            )
        observed_dates = tuple(dict.fromkeys(row["trade_time"].date() for row in rows))
        expected_dates = self._open_dates(observed_dates[0], observed_dates[-1])
        return adapt_major_index_120m_rows(
            rows,
            ts_code=ts_code,
            data_snapshot_id=data_snapshot_id,
            as_of=as_of,
            expected_trade_dates=expected_dates,
        )
