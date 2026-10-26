"""Historical fixtures use native range units and independent source contracts.

Fields/values come from doc328 and the first-batch saved source response.  The
factor file schema follows assets/adj_factor.py and RAW_TUSHARE_ADJ_FACTOR_SCHEMA;
the fixture supplies inputs, never expected values derived from the code tested.
No helper opens a connection or accesses formal resources or the network.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from orchestrator.defs.checks.stk_factor_pro import factor_file_sha
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.paths import raw_adj_factor_path
from orchestrator.defs.run_contracts.stk_factor_pro import (
    FactorFileRef,
    HistoryEligibilityRecord,
    HistoryPlanRecord,
    RunIdentity,
    StkFactorProRawCoverage,
    StkFactorProTargetSilver,
)
from orchestrator.tushare_download import (
    DownloadMode,
    DownloadStatus,
    DownloadTask,
    ObjectTimeRange,
    TimeRange,
)
from orchestrator.tushare_download.contracts.stk_factor_pro import (
    STK_FACTOR_PRO_CONTRACT,
)
from orchestrator.tushare_download.download_models import (
    DownloadSummary,
    DownloadUnit,
    OrderingFacts,
    SourceRecord,
    TerminationSummary,
    UnitResult,
    UnitStatistics,
)
from orchestrator.tushare_download.task_input import validate_task
from orchestrator.tushare_download.unit_planner import UnitPlanner
from tests.stk_factor_pro_test_support import NAMES, connection, contract, identity, row

__all__ = [
    "NAMES",
    "HistoryDownloader",
    "connection",
    "contract",
    "eligibility",
    "history_result",
    "history_task",
    "identity",
    "planned_units",
    "roots",
    "row",
    "saved_real_rows",
    "write_factor_file",
]


def history_task(
    ranges: tuple[tuple[str, date, date], ...],
) -> DownloadTask:
    """Build the actual public mode-5 task, including per-object closed ranges."""
    return DownloadTask(
        "stk_factor_pro",
        DownloadMode.BY_OBJECT_RANGE,
        object_ranges=tuple(
            ObjectTimeRange(code, TimeRange(start.isoformat(), end.isoformat()))
            for code, start, end in ranges
        ),
    )


def planned_units(task: DownloadTask) -> tuple[DownloadUnit, ...]:
    """Use the real validator/planner instead of manufacturing a daily unit."""
    assert task.mode is DownloadMode.BY_OBJECT_RANGE
    planner = UnitPlanner(
        validate_task(task, STK_FACTOR_PRO_CONTRACT, 1024 * 1024),
        STK_FACTOR_PRO_CONTRACT,
    )
    try:
        units = []
        while (unit := planner.next_unit()) is not None:
            units.append(unit)
        assert len(units) == planner.total_units
        return tuple(units)
    finally:
        planner.close()


def history_result(
    unit: DownloadUnit,
    rows: tuple[tuple[object, ...], ...],
) -> UnitResult:
    """Full unit carrier; callers may deliberately supply wrong rows as negatives."""
    assert unit.mode is DownloadMode.BY_OBJECT_RANGE and unit.time_range is not None
    records = tuple(SourceRecord(NAMES, values, 0) for values in rows)
    return UnitResult(
        unit,
        records,
        (NAMES,),
        (
            (
                ("ts_code", unit.object_code),
                ("start_date", unit.time_range.start.replace("-", "")),
                ("end_date", unit.time_range.end.replace("-", "")),
            ),
        ),
        UnitStatistics(1, 0, 1, 1, int(not rows), len(rows), 0, 0.1, 0, 0.1, 0),
        OrderingFacts("trade_date", "1", len(rows), 0),
        TerminationSummary(2, True, 1, None),
    )


class HistorySession:
    """Independent session with final facts available only after normal close."""

    def __init__(self, owner: HistoryDownloader, task: DownloadTask, kwargs: dict):
        self.owner, self.task, self.kwargs = owner, task, kwargs
        self.units = planned_units(task)
        self.task_id = f"history-test-session-{len(owner.calls)}"
        self.closed = self.exhausted = False
        self.delivered = self.rows = 0
        self.summary = None

    def __enter__(self):
        return self

    def __iter__(self):
        for unit in self.units:
            value = history_result(
                unit, self.owner.rows_by_code.get(unit.object_code, ())
            )
            if self.owner.result_transform is not None:
                value = self.owner.result_transform(value)
            self.delivered += 1
            self.rows += len(value.records)
            yield value
        self.exhausted = True

    def __exit__(self, exc_type, exc, traceback):
        self.closed = True
        if self.owner.close_error is not None:
            raise self.owner.close_error
        succeeded = exc_type is None and self.exhausted
        self.summary = DownloadSummary(
            self.task_id,
            DownloadStatus.SUCCEEDED if succeeded else DownloadStatus.FAILED,
            len(self.units),
            self.delivered,
            self.delivered,
            self.rows,
            self.rows,
            self.delivered,
            0,
            self.delivered,
            succeeded,
            0.1,
            None,
            (),
            0,
            None,
            0,
        )
        if self.owner.summary_transform is not None:
            self.summary = self.owner.summary_transform(self.summary)


class HistoryDownloader:
    """No-network downloader substitute; validates every received public task."""

    def __init__(
        self,
        rows_by_code: Mapping[str, tuple[tuple[object, ...], ...]],
        *,
        result_transform: Callable[[UnitResult], UnitResult] | None = None,
        summary_transform: Callable[[DownloadSummary], DownloadSummary] | None = None,
        close_error: BaseException | None = None,
    ):
        self.rows_by_code = rows_by_code
        self.result_transform, self.summary_transform = (
            result_transform,
            summary_transform,
        )
        self.close_error = close_error
        self.calls: list[tuple[DownloadTask, dict]] = []
        self.sessions: list[HistorySession] = []

    def download(self, task: DownloadTask, **kwargs):
        self.calls.append((task, kwargs))
        session = HistorySession(self, task, kwargs)
        self.sessions.append(session)
        return session


def roots(tmp_path: Path) -> tuple[Path, Path]:
    lake, staging = tmp_path / "lake", tmp_path / "staging"
    lake.mkdir(parents=True, exist_ok=True)
    staging.mkdir(parents=True, exist_ok=True)
    return lake, staging


def write_factor_file(
    conn,
    lake: Path,
    day: date,
    values: tuple[tuple[str, float], ...],
) -> FactorFileRef:
    """Write the real three-column Raw factor input using the supplied connection."""
    path = raw_adj_factor_path(lake, day.isoformat())
    path.parent.mkdir(parents=True, exist_ok=True)
    data = pd.DataFrame(
        {
            "ts_code": pd.Series([code for code, _ in values], dtype="string"),
            "trade_date": pd.Series(
                [day.strftime("%Y%m%d")] * len(values), dtype="string"
            ),
            "adj_factor": pd.Series([value for _, value in values], dtype="Float64"),
        }
    )
    conn.register("history_test_factor_input", data)
    try:
        conn.execute(
            copy_query_to_parquet(
                "SELECT CAST(ts_code AS VARCHAR) AS ts_code, "
                "CAST(trade_date AS VARCHAR) AS trade_date, "
                "CAST(adj_factor AS DOUBLE) AS adj_factor "
                "FROM history_test_factor_input ORDER BY ts_code",
                path,
            )
        )
    finally:
        conn.unregister("history_test_factor_input")
    return FactorFileRef(
        day, "raw_tushare_adj_factor", factor_file_sha(path), len(values)
    )


def eligibility(
    run: RunIdentity,
    plan: HistoryPlanRecord,
    raw_sha: str = "a" * 64,
    silver_sha: str = "b" * 64,
    *,
    stock_count: int = 1,
) -> HistoryEligibilityRecord:
    """Already-verified upstream facts; no fake Dagster storage is queried or written."""
    coverage = StkFactorProRawCoverage(
        run.target_trade_date,
        True,
        True,
        raw_sha,
        "c" * 64,
        "d" * 64,
        "e" * 64,
        stock_count,
        stock_count,
        0,
        (),
        "隔离夹具：上游已核原T股票齐备",
        1,
        2,
        None,
    )
    silver = StkFactorProTargetSilver(
        run.target_trade_date,
        True,
        silver_sha,
        raw_sha,
        raw_sha,
        3,
        4,
        "隔离夹具：上游已核Silver对应当前Raw",
    )
    return HistoryEligibilityRecord(
        1,
        run,
        plan.history_plan_digest,
        plan.history_ranges_digest,
        coverage,
        silver,
        datetime(2026, 10, 16, 19, tzinfo=ZoneInfo("Asia/Shanghai")),
    )


def saved_real_rows() -> tuple[tuple[object, ...], ...]:
    """Decode only the existing, bounded one-stock/five-day source evidence."""
    evidence = (
        Path(__file__).resolve().parents[2]
        / "reports/stock_factor_pro_batch1_20261026/source/component-rows.canonical.json"
    )

    def decode(value):
        if value[0] == 0:
            return None
        if value[0] == 1:
            return value[1]
        if value[0] == 2:
            return int(value[1])
        assert value[0] == 3
        return Decimal((value[1], tuple(value[2]), value[3]))

    rows = tuple(
        tuple(decode(value) for value in values)
        for values in json.loads(evidence.read_text())
    )
    assert len(rows) == 5 and all(len(values) == 261 for values in rows)
    assert tuple((values[0], values[1]) for values in rows) == (
        ("000001.SZ", "20261012"),
        ("000001.SZ", "20261013"),
        ("000001.SZ", "20261014"),
        ("000001.SZ", "20261015"),
        ("000001.SZ", "20261016"),
    )
    return rows
