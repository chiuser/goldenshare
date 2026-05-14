from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


MINUTE_BARS_BY_FREQ = {
    1: 241,
    5: 49,
    15: 17,
    30: 9,
    60: 5,
}
DEFAULT_SEVERE_RATIO = 0.05
DEFAULT_UNDERFILLED_RATIO = 0.90


@dataclass(frozen=True)
class RawPartitionAssessment:
    freq: int
    trade_date: date
    expected_rows: int
    raw_files: int
    raw_rows: int
    status: str
    active_symbols: int


@dataclass(frozen=True)
class ResearchDateCount:
    row_count: int = 0
    code_count: int = 0
    patch_rows: int = 0


class StkMinsRawRecoveryService:
    """Read-only integrity audit for stk_mins raw partitions.

    Historical raw recovery writes have been removed. This service intentionally
    keeps only read-only assessment helpers so raw repair can no longer bypass
    the current raw -> clean_next refresh lifecycle.
    """

    def __init__(self, *, lake_root: Path, progress: Callable[[str], None] | None = None) -> None:
        self.lake_root = lake_root
        self.progress = progress or print

    def audit_raw_integrity(
        self,
        *,
        freqs: list[int],
        start_date: date,
        end_date: date,
        patch_ts_code: str | None = None,
        sample_limit: int = 20,
    ) -> dict[str, Any]:
        trade_dates = self._trade_dates(start_date=start_date, end_date=end_date)
        active_by_date = self._active_symbol_counts(trade_dates)
        freq_summaries: list[dict[str, Any]] = []
        self.progress(
            f"[stk_mins_raw_audit] start freqs={freqs} start_date={start_date.isoformat()} "
            f"end_date={end_date.isoformat()} trade_dates={len(trade_dates)}"
        )
        for freq in freqs:
            self.progress(f"[stk_mins_raw_audit] assessing_raw freq={freq}")
            assessments = self._assess_raw_partitions(
                freq=freq,
                trade_dates=trade_dates,
                active_by_date=active_by_date,
            )
            issue_dates = [item.trade_date for item in assessments if item.status in {"missing", "severely_low"}]
            self.progress(f"[stk_mins_raw_audit] counting_research freq={freq} issue_dates={len(issue_dates)}")
            research_counts = self._research_counts_by_date(freq=freq, trade_dates=issue_dates, patch_ts_code=patch_ts_code)
            self.progress(f"[stk_mins_raw_audit] freq_done freq={freq} issue_dates={len(issue_dates)}")
            freq_summaries.append(
                self._summarize_assessments(
                    freq=freq,
                    assessments=assessments,
                    research_counts=research_counts,
                    sample_limit=sample_limit,
                )
            )

        return {
            "operation": "audit_stk_mins_raw_integrity",
            "mode": "read_only",
            "lake_root": str(self.lake_root),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "trade_date_count": len(trade_dates),
            "freqs": freqs,
            "patch_ts_code": patch_ts_code,
            "freq_summaries": freq_summaries,
            "write_intent": False,
        }

    def _assess_raw_partitions(
        self,
        *,
        freq: int,
        trade_dates: list[date],
        active_by_date: dict[date, int],
    ) -> list[RawPartitionAssessment]:
        bars = _bars_for_freq(freq)
        assessments: list[RawPartitionAssessment] = []
        for trade_date in trade_dates:
            expected_rows = active_by_date[trade_date] * bars
            files = _partition_files(self._raw_partition(freq=freq, trade_date=trade_date))
            raw_rows = _row_count(files)
            if not files:
                status = "missing"
            elif expected_rows > 0 and (raw_rows <= bars * 5 or raw_rows / expected_rows < DEFAULT_SEVERE_RATIO):
                status = "severely_low"
            elif expected_rows > 0 and raw_rows / expected_rows < DEFAULT_UNDERFILLED_RATIO:
                status = "underfilled"
            else:
                status = "ok"
            assessments.append(
                RawPartitionAssessment(
                    freq=freq,
                    trade_date=trade_date,
                    expected_rows=expected_rows,
                    raw_files=len(files),
                    raw_rows=raw_rows,
                    status=status,
                    active_symbols=active_by_date[trade_date],
                )
            )
        return assessments

    def _summarize_assessments(
        self,
        *,
        freq: int,
        assessments: list[RawPartitionAssessment],
        research_counts: dict[date, ResearchDateCount],
        sample_limit: int,
    ) -> dict[str, Any]:
        by_status: dict[str, list[RawPartitionAssessment]] = defaultdict(list)
        for item in assessments:
            by_status[item.status].append(item)
        total_expected = sum(item.expected_rows for item in assessments)
        total_raw = sum(item.raw_rows for item in assessments)
        issue_items = by_status["missing"] + by_status["severely_low"]
        research_has_more_rows = [
            item
            for item in issue_items
            if research_counts.get(item.trade_date, ResearchDateCount()).row_count > item.raw_rows
        ]
        return {
            "freq": freq,
            "expected_rows": total_expected,
            "raw_rows": total_raw,
            "row_gap_estimate": max(total_expected - total_raw, 0),
            "partition_count": len(assessments),
            "missing_partitions": len(by_status["missing"]),
            "severely_low_partitions": len(by_status["severely_low"]),
            "underfilled_partitions": len(by_status["underfilled"]),
            "ok_partitions": len(by_status["ok"]),
            "research_has_more_rows_issue_partitions": len(research_has_more_rows),
            "severe_ranges": _compress_trade_date_ranges([item.trade_date for item in by_status["severely_low"]], [item.trade_date for item in assessments]),
            "missing_ranges": _compress_trade_date_ranges([item.trade_date for item in by_status["missing"]], [item.trade_date for item in assessments]),
            "issue_samples": [
                {
                    "trade_date": item.trade_date.isoformat(),
                    "status": item.status,
                    "expected_rows": item.expected_rows,
                    "raw_rows": item.raw_rows,
                    "raw_files": item.raw_files,
                    "research_rows": research_counts.get(item.trade_date, ResearchDateCount()).row_count,
                    "research_distinct_ts_code": research_counts.get(item.trade_date, ResearchDateCount()).code_count,
                }
                for item in issue_items[:sample_limit]
            ],
        }

    def _research_counts_by_date(
        self,
        *,
        freq: int,
        trade_dates: Iterable[date],
        patch_ts_code: str | None,
    ) -> dict[date, ResearchDateCount]:
        dates_by_month: dict[str, list[date]] = defaultdict(list)
        for trade_date in sorted(set(trade_dates)):
            dates_by_month[trade_date.strftime("%Y-%m")].append(trade_date)
        if not dates_by_month:
            return {}

        duckdb = _require_duckdb()
        connection = duckdb.connect(database=":memory:")
        result: dict[date, ResearchDateCount] = {}
        try:
            for trade_month, month_dates in dates_by_month.items():
                files = sorted(self._research_month(freq=freq, trade_month=trade_month).glob("bucket=*/*.parquet"))
                if not files:
                    continue
                self.progress(
                    f"[stk_mins_raw_audit] research_count freq={freq} trade_month={trade_month} "
                    f"dates={len(month_dates)} files={len(files)}"
                )
                file_list = "[" + ",".join(_sql_quote(str(path)) for path in files) + "]"
                start_date = min(month_dates).isoformat()
                end_date = max(month_dates).isoformat()
                patch_expr = "0"
                if patch_ts_code:
                    patch_expr = f"sum(case when ts_code = {_sql_quote(patch_ts_code)} then 1 else 0 end)"
                rows = connection.execute(
                    f"""
                    select
                      cast(trade_time as date) as trade_date,
                      count(*) as row_count,
                      count(distinct ts_code) as code_count,
                      {patch_expr} as patch_rows
                    from read_parquet({file_list})
                    where cast(trade_time as date) between date '{start_date}' and date '{end_date}'
                    group by 1
                    """
                ).fetchall()
                for raw_trade_date, row_count, code_count, patch_rows in rows:
                    parsed_date = _parse_date(raw_trade_date)
                    if parsed_date in month_dates:
                        result[parsed_date] = ResearchDateCount(
                            row_count=int(row_count or 0),
                            code_count=int(code_count or 0),
                            patch_rows=int(patch_rows or 0),
                        )
        finally:
            connection.close()
        return result

    def _trade_dates(self, *, start_date: date, end_date: date) -> list[date]:
        if end_date < start_date:
            raise ValueError("end-date 不能早于 start-date。")
        calendar_path = self.lake_root / "manifest" / "trading_calendar" / "tushare_trade_cal.parquet"
        rows = _read_parquet_rows(calendar_path, columns=["cal_date", "is_open"])
        trade_dates = sorted(
            {
                parsed
                for row in rows
                if (parsed := _parse_date(row.get("cal_date"))) is not None
                and start_date <= parsed <= end_date
                and bool(row.get("is_open"))
            }
        )
        if not trade_dates:
            raise RuntimeError(f"本地交易日历没有覆盖区间：{start_date.isoformat()} ~ {end_date.isoformat()}")
        return trade_dates

    def _active_symbol_counts(self, trade_dates: list[date]) -> dict[date, int]:
        stock_path = self.lake_root / "manifest" / "security_universe" / "tushare_stock_basic.parquet"
        rows = _read_parquet_rows(stock_path, columns=["ts_code", "list_date", "delist_date"])
        securities: list[tuple[date | None, date | None]] = []
        for row in rows:
            if not str(row.get("ts_code") or "").strip():
                continue
            securities.append((_parse_date(row.get("list_date")), _parse_date(row.get("delist_date"))))
        return {
            trade_date: sum(
                1
                for list_date, delist_date in securities
                if (list_date is None or list_date <= trade_date)
                and (delist_date is None or delist_date >= trade_date)
            )
            for trade_date in trade_dates
        }

    def _raw_partition(self, *, freq: int, trade_date: date) -> Path:
        return self.lake_root / "raw_tushare" / "stk_mins_by_date" / f"freq={freq}" / f"trade_date={trade_date.isoformat()}"

    def _research_month(self, *, freq: int, trade_month: str) -> Path:
        return self.lake_root / "research" / "stk_mins_by_symbol_month" / f"freq={freq}" / f"trade_month={trade_month}"


def _read_parquet_rows(path: Path, *, columns: list[str]) -> list[dict[str, Any]]:
    if not path.exists():
        raise RuntimeError(f"缺少本地 Lake 文件：{path}")
    pq = _require_pyarrow_parquet()
    table = pq.ParquetFile(path).read(columns=columns)
    return table.to_pylist()


def _partition_files(partition: Path) -> list[Path]:
    if not partition.exists():
        return []
    return sorted(path for path in partition.glob("*.parquet") if path.is_file())


def _row_count(files: list[Path]) -> int:
    pq = _require_pyarrow_parquet()
    return sum(int(pq.ParquetFile(path).metadata.num_rows) for path in files)


def _bars_for_freq(freq: int) -> int:
    try:
        return MINUTE_BARS_BY_FREQ[freq]
    except KeyError as exc:
        allowed = ",".join(str(item) for item in sorted(MINUTE_BARS_BY_FREQ))
        raise ValueError(f"raw 完整性审计仅支持 freq={allowed}，不支持 {freq}") from exc


def _compress_trade_date_ranges(dates: list[date], calendar_dates: list[date]) -> list[dict[str, Any]]:
    if not dates:
        return []
    date_set = set(dates)
    ranges: list[dict[str, Any]] = []
    start: date | None = None
    previous: date | None = None
    count = 0
    for trade_date in calendar_dates:
        if trade_date not in date_set:
            if start is not None and previous is not None:
                ranges.append({"start_date": start.isoformat(), "end_date": previous.isoformat(), "trade_date_count": count})
            start = None
            previous = None
            count = 0
            continue
        if start is None:
            start = trade_date
            count = 0
        previous = trade_date
        count += 1
    if start is not None and previous is not None:
        ranges.append({"start_date": start.isoformat(), "end_date": previous.isoformat(), "trade_date_count": count})
    return ranges


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text.lower() in {"none", "nan", "nat"}:
        return None
    return date.fromisoformat(text[:10])


def _sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _require_duckdb():  # type: ignore[no-untyped-def]
    try:
        import duckdb
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "缺少 DuckDB 依赖。请先安装：lake_console/.venv/bin/pip install -r lake_console/backend/requirements.txt"
        ) from exc
    return duckdb


def _require_pyarrow_parquet():  # type: ignore[no-untyped-def]
    try:
        import pyarrow.parquet as pq
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "缺少 Parquet 依赖。请先安装：lake_console/.venv/bin/pip install -r lake_console/backend/requirements.txt"
        ) from exc
    return pq
