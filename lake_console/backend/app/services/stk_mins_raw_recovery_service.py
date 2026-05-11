from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from lake_console.backend.app.catalog.tushare_stk_mins import STK_MINS_FIELDS
from lake_console.backend.app.services.lake_root_service import LakeRootService


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
    """Read-only audit and dry-run recovery planning for stk_mins raw partitions."""

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

    def plan_recover_from_research(
        self,
        *,
        freqs: list[int],
        start_date: date,
        end_date: date,
        patch_ts_code: str,
        sample_limit: int = 20,
    ) -> dict[str, Any]:
        trade_dates = self._trade_dates(start_date=start_date, end_date=end_date)
        active_by_date = self._active_symbol_counts(trade_dates)
        freq_plans: list[dict[str, Any]] = []
        total_planned = 0
        total_blocked = 0
        self.progress(
            f"[stk_mins_raw_recovery] dry_run start freqs={freqs} start_date={start_date.isoformat()} "
            f"end_date={end_date.isoformat()} trade_dates={len(trade_dates)} patch_ts_code={patch_ts_code}"
        )
        for freq in freqs:
            self.progress(f"[stk_mins_raw_recovery] assessing_raw freq={freq}")
            assessments = self._assess_raw_partitions(
                freq=freq,
                trade_dates=trade_dates,
                active_by_date=active_by_date,
            )
            candidates = [item for item in assessments if item.status in {"missing", "severely_low"}]
            self.progress(f"[stk_mins_raw_recovery] counting_research freq={freq} candidates={len(candidates)}")
            research_counts = self._research_counts_by_date(
                freq=freq,
                trade_dates=[item.trade_date for item in candidates],
                patch_ts_code=patch_ts_code,
            )
            planned: list[dict[str, Any]] = []
            blocked: list[dict[str, Any]] = []
            for item in candidates:
                research = research_counts.get(item.trade_date, ResearchDateCount())
                if research.row_count <= 0:
                    blocked.append(
                        {
                            "freq": freq,
                            "trade_date": item.trade_date.isoformat(),
                            "reason": "missing_research_source",
                            "raw_rows": item.raw_rows,
                            "expected_rows": item.expected_rows,
                        }
                    )
                    continue
                estimated_final_rows = research.row_count - research.patch_rows + self._raw_patch_rows(
                    freq=freq,
                    trade_date=item.trade_date,
                    patch_ts_code=patch_ts_code,
                )
                planned.append(
                    {
                        "freq": freq,
                        "trade_date": item.trade_date.isoformat(),
                        "raw_rows": item.raw_rows,
                        "raw_files": item.raw_files,
                        "expected_rows": item.expected_rows,
                        "research_rows": research.row_count,
                        "research_distinct_ts_code": research.code_count,
                        "research_patch_rows": research.patch_rows,
                        "raw_patch_rows": self._raw_patch_rows(
                            freq=freq,
                            trade_date=item.trade_date,
                            patch_ts_code=patch_ts_code,
                        ),
                        "estimated_final_rows": estimated_final_rows,
                        "action": "would_restore_from_research_and_merge_raw_patch",
                    }
                )

            total_planned += len(planned)
            total_blocked += len(blocked)
            self.progress(
                f"[stk_mins_raw_recovery] freq_done freq={freq} planned={len(planned)} blocked={len(blocked)}"
            )
            freq_plans.append(
                {
                    "freq": freq,
                    "candidate_partitions": len(candidates),
                    "planned_restore_partitions": len(planned),
                    "blocked_partitions": len(blocked),
                    "planned_ranges": _compress_trade_date_ranges(
                        [date.fromisoformat(str(item["trade_date"])) for item in planned],
                        trade_dates,
                    ),
                    "planned_samples": planned[:sample_limit],
                    "blocked_samples": blocked[:sample_limit],
                }
            )

        return {
            "operation": "recover_stk_mins_raw_from_research",
            "mode": "dry_run",
            "lake_root": str(self.lake_root),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "freqs": freqs,
            "patch_ts_code": patch_ts_code,
            "planned_restore_partitions": total_planned,
            "blocked_partitions": total_blocked,
            "freq_plans": freq_plans,
            "write_intent": False,
            "notes": [
                "本命令只生成恢复计划，不写 _tmp、manifest 或正式 Parquet 分区。",
                "预计恢复流程为 research 当日全市场数据 + 当前 raw 中 patch_ts_code 行，按 (ts_code, freq, trade_time) 去重。",
            ],
        }

    def apply_recover_from_research(
        self,
        *,
        freqs: list[int],
        start_date: date,
        end_date: date,
        patch_ts_code: str,
        sample_limit: int = 20,
    ) -> dict[str, Any]:
        LakeRootService(self.lake_root).require_ready_for_write()
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-stk-mins-raw-recovery")
        trade_dates = self._trade_dates(start_date=start_date, end_date=end_date)
        active_by_date = self._active_symbol_counts(trade_dates)
        total_restored = 0
        total_blocked = 0
        total_written_rows = 0
        freq_results: list[dict[str, Any]] = []
        self.progress(
            f"[stk_mins_raw_recovery] apply start run_id={run_id} freqs={freqs} "
            f"start_date={start_date.isoformat()} end_date={end_date.isoformat()} "
            f"trade_dates={len(trade_dates)} patch_ts_code={patch_ts_code}"
        )
        for freq in freqs:
            self.progress(f"[stk_mins_raw_recovery] assessing_raw freq={freq}")
            assessments = self._assess_raw_partitions(
                freq=freq,
                trade_dates=trade_dates,
                active_by_date=active_by_date,
            )
            candidates = [item for item in assessments if item.status in {"missing", "severely_low"}]
            research_counts = self._research_counts_by_date(
                freq=freq,
                trade_dates=[item.trade_date for item in candidates],
                patch_ts_code=patch_ts_code,
            )
            restored_samples: list[dict[str, Any]] = []
            blocked_samples: list[dict[str, Any]] = []
            restored_dates: list[date] = []
            freq_written_rows = 0
            for index, item in enumerate(candidates, start=1):
                research = research_counts.get(item.trade_date, ResearchDateCount())
                if research.row_count <= 0:
                    total_blocked += 1
                    if len(blocked_samples) < sample_limit:
                        blocked_samples.append(
                            {
                                "freq": freq,
                                "trade_date": item.trade_date.isoformat(),
                                "reason": "missing_research_source",
                                "raw_rows": item.raw_rows,
                                "expected_rows": item.expected_rows,
                            }
                        )
                    continue
                self.progress(
                    f"[stk_mins_raw_recovery] restore freq={freq} unit={index}/{len(candidates)} "
                    f"trade_date={item.trade_date.isoformat()} raw_rows={item.raw_rows} research_rows={research.row_count}"
                )
                result = self._restore_one_partition_from_research(
                    run_id=run_id,
                    freq=freq,
                    trade_date=item.trade_date,
                    patch_ts_code=patch_ts_code,
                    raw_rows_before=item.raw_rows,
                    research_rows=research.row_count,
                )
                total_restored += 1
                freq_written_rows += int(result["written_rows"])
                total_written_rows += int(result["written_rows"])
                restored_dates.append(item.trade_date)
                if len(restored_samples) < sample_limit:
                    restored_samples.append(result)
            freq_results.append(
                {
                    "freq": freq,
                    "candidate_partitions": len(candidates),
                    "restored_partitions": len(restored_dates),
                    "blocked_partitions": len(blocked_samples),
                    "written_rows": freq_written_rows,
                    "restored_ranges": _compress_trade_date_ranges(restored_dates, trade_dates),
                    "restored_samples": restored_samples,
                    "blocked_samples": blocked_samples,
                }
            )
            self.progress(
                f"[stk_mins_raw_recovery] freq_done freq={freq} restored={len(restored_dates)} "
                f"blocked={len(blocked_samples)} written_rows={freq_written_rows}"
            )

        return {
            "operation": "recover_stk_mins_raw_from_research",
            "mode": "apply",
            "run_id": run_id,
            "lake_root": str(self.lake_root),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "freqs": freqs,
            "patch_ts_code": patch_ts_code,
            "restored_partitions": total_restored,
            "blocked_partitions": total_blocked,
            "written_rows": total_written_rows,
            "freq_results": freq_results,
            "write_intent": True,
            "backup_root": str(self.lake_root / "_recovery" / run_id / "raw_partition_backup"),
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
        recoverable = [
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
            "recoverable_issue_partitions": len(recoverable),
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
                    f"[stk_mins_raw_recovery] research_count freq={freq} trade_month={trade_month} "
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

    def _raw_patch_rows(self, *, freq: int, trade_date: date, patch_ts_code: str) -> int:
        files = _partition_files(self._raw_partition(freq=freq, trade_date=trade_date))
        if not files:
            return 0
        total = 0
        pq = _require_pyarrow_parquet()
        for path in files:
            table = pq.ParquetFile(path).read(columns=["ts_code"])
            total += sum(1 for value in table.column("ts_code").to_pylist() if str(value) == patch_ts_code)
        return total

    def _restore_one_partition_from_research(
        self,
        *,
        run_id: str,
        freq: int,
        trade_date: date,
        patch_ts_code: str,
        raw_rows_before: int,
        research_rows: int,
    ) -> dict[str, Any]:
        research_frame = self._read_research_day_frame(freq=freq, trade_date=trade_date)
        raw_patch_frame = self._read_raw_patch_frame(freq=freq, trade_date=trade_date, patch_ts_code=patch_ts_code)
        output_frame = _merge_research_and_patch_frames(
            research_frame=research_frame,
            raw_patch_frame=raw_patch_frame,
            patch_ts_code=patch_ts_code,
        )
        if output_frame.empty:
            raise RuntimeError(f"恢复结果为空：freq={freq} trade_date={trade_date.isoformat()}")
        final_partition = self._raw_partition(freq=freq, trade_date=trade_date)
        tmp_partition = (
            self.lake_root
            / "_tmp"
            / run_id
            / "raw_tushare"
            / "stk_mins_by_date"
            / f"freq={freq}"
            / f"trade_date={trade_date.isoformat()}"
        )
        backup_partition = (
            self.lake_root
            / "_recovery"
            / run_id
            / "raw_partition_backup"
            / f"freq={freq}"
            / f"trade_date={trade_date.isoformat()}"
        )
        patch_backup_file = (
            self.lake_root
            / "_recovery"
            / run_id
            / "patch_rows"
            / f"freq={freq}"
            / f"trade_date={trade_date.isoformat()}"
            / "part-000.parquet"
        )
        _write_frame_to_parquet(raw_patch_frame, patch_backup_file)
        output_file = tmp_partition / "part-00000.parquet"
        written_rows = _write_frame_to_parquet(output_frame, output_file)
        validated_rows = _row_count([output_file])
        if validated_rows != written_rows:
            raise RuntimeError(
                f"恢复 Parquet 校验失败：freq={freq} trade_date={trade_date.isoformat()} "
                f"written={written_rows} validated={validated_rows}"
            )
        _replace_partition_keep_backup(tmp_partition=tmp_partition, final_partition=final_partition, backup_partition=backup_partition)
        return {
            "freq": freq,
            "trade_date": trade_date.isoformat(),
            "raw_rows_before": raw_rows_before,
            "research_rows": research_rows,
            "raw_patch_rows": len(raw_patch_frame),
            "written_rows": written_rows,
            "final_partition": str(final_partition),
            "backup_partition": str(backup_partition),
            "patch_backup_file": str(patch_backup_file),
        }

    def _read_research_day_frame(self, *, freq: int, trade_date: date):  # type: ignore[no-untyped-def]
        files = sorted(self._research_month(freq=freq, trade_month=trade_date.strftime("%Y-%m")).glob("bucket=*/*.parquet"))
        if not files:
            raise RuntimeError(f"缺少 research 源：freq={freq} trade_month={trade_date.strftime('%Y-%m')}")
        duckdb = _require_duckdb()
        connection = duckdb.connect(database=":memory:")
        try:
            file_list = "[" + ",".join(_sql_quote(str(path)) for path in files) + "]"
            columns = ", ".join(STK_MINS_FIELDS)
            return connection.execute(
                f"""
                select {columns}
                from read_parquet({file_list})
                where cast(trade_time as date) = date '{trade_date.isoformat()}'
                order by ts_code, trade_time
                """
            ).fetchdf()
        finally:
            connection.close()

    def _read_raw_patch_frame(self, *, freq: int, trade_date: date, patch_ts_code: str):  # type: ignore[no-untyped-def]
        pd = _require_pandas()
        frames = []
        for path in _partition_files(self._raw_partition(freq=freq, trade_date=trade_date)):
            frame = pd.read_parquet(path, columns=list(STK_MINS_FIELDS), engine="pyarrow")
            frames.append(frame[frame["ts_code"].astype(str) == patch_ts_code])
        if not frames:
            return pd.DataFrame(columns=list(STK_MINS_FIELDS))
        return pd.concat(frames, ignore_index=True)

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


def _merge_research_and_patch_frames(*, research_frame: Any, raw_patch_frame: Any, patch_ts_code: str):  # type: ignore[no-untyped-def]
    pd = _require_pandas()
    if raw_patch_frame.empty:
        merged = research_frame.copy()
    else:
        retained_research = research_frame[research_frame["ts_code"].astype(str) != patch_ts_code]
        merged = pd.concat([retained_research, raw_patch_frame], ignore_index=True)
    if merged.empty:
        return merged
    merged = merged.loc[:, list(STK_MINS_FIELDS)]
    merged = merged.drop_duplicates(subset=["ts_code", "freq", "trade_time"], keep="last")
    merged = merged.sort_values(["ts_code", "trade_time"], kind="mergesort").reset_index(drop=True)
    return merged


def _write_frame_to_parquet(frame: Any, output_path: Path) -> int:  # type: ignore[no-untyped-def]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if frame.empty:
        frame = frame.loc[:, list(STK_MINS_FIELDS)] if set(STK_MINS_FIELDS).issubset(set(frame.columns)) else frame
    else:
        frame = frame.loc[:, list(STK_MINS_FIELDS)]
    frame.to_parquet(output_path, index=False, engine="pyarrow", compression="zstd")
    return int(len(frame))


def _replace_partition_keep_backup(*, tmp_partition: Path, final_partition: Path, backup_partition: Path) -> None:
    if backup_partition.exists():
        raise RuntimeError(f"恢复备份目录已存在，拒绝覆盖：{backup_partition}")
    final_partition.parent.mkdir(parents=True, exist_ok=True)
    backup_partition.parent.mkdir(parents=True, exist_ok=True)
    moved_final = False
    try:
        if final_partition.exists():
            final_partition.replace(backup_partition)
            moved_final = True
        tmp_partition.replace(final_partition)
    except Exception:
        if moved_final and backup_partition.exists() and not final_partition.exists():
            backup_partition.replace(final_partition)
        raise


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
    if not text or text.lower() in {"nan", "nat", "none", "null"}:
        return None
    if len(text) == 8 and text.isdigit():
        return date.fromisoformat(f"{text[:4]}-{text[4:6]}-{text[6:8]}")
    return date.fromisoformat(text[:10])


def _sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _require_pyarrow_parquet():  # type: ignore[no-untyped-def]
    try:
        import pyarrow.parquet as pq
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 pyarrow，无法读取 Parquet。请先安装 lake_console/backend/requirements.txt。") from exc
    return pq


def _require_duckdb():  # type: ignore[no-untyped-def]
    try:
        import duckdb
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 duckdb，无法生成 research 恢复预案。请先安装 lake_console/backend/requirements.txt。") from exc
    return duckdb


def _require_pandas():  # type: ignore[no-untyped-def]
    try:
        import pandas as pd
    except ModuleNotFoundError as exc:
        raise RuntimeError("缺少 pandas，无法恢复 Parquet。请先安装 lake_console/backend/requirements.txt。") from exc
    return pd
