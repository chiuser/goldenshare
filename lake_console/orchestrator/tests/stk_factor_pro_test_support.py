"""Independent doc328 fields and bounded synthetic/native-source test carriers."""

from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path

from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.run_contracts.stk_factor_pro import ContractIdentity, RunIdentity
from orchestrator.tushare_download import DownloadMode, DownloadStatus, DownloadTask
from orchestrator.tushare_download.contract_registry import content_digest
from orchestrator.tushare_download.contracts.stk_factor_pro import (
    STK_FACTOR_PRO_CONTRACT,
)
from orchestrator.tushare_download.download_models import (
    DownloadSummary,
    OrderingFacts,
    SourceRecord,
    TerminationSummary,
    UnitResult,
    UnitStatistics,
)
from orchestrator.tushare_download.task_input import validate_task
from orchestrator.tushare_download.unit_planner import UnitPlanner

DOCUMENT = (
    Path(__file__).resolve().parents[3]
    / "docs/sources/tushare/股票数据/特色数据/0328_股票技术面因子(专业版).md"
)
NAMES = tuple(
    line.strip().strip("|").split("|")[0].strip()
    for line in DOCUMENT.read_text().split("## 输出参数\n", 1)[1].splitlines()
    if len(line.strip().strip("|").split("|")) == 4
    and line.strip().strip("|").split("|")[1].strip() in ("str", "float")
)
assert len(NAMES) == 261 and NAMES[:2] == ("ts_code", "trade_date")
DAY = date(2026, 10, 16)


def identity(run="run-a", day=DAY):
    return RunIdentity(run, None, day, day, date(2026, 10, 15), "today", 0, None, None)


def contract():
    return ContractIdentity(
        "stk_factor_pro", "1", content_digest(STK_FACTOR_PRO_CONTRACT), "1"
    )


def row(code="000001.SZ", day="20261016", **values):
    # Independent literal business values, not computed with the conversion/check helpers.
    value = {name: Decimal(0) for name in NAMES[2:]}
    value.update(
        ts_code=code,
        trade_date=day,
        open=Decimal("1.25"),
        close=Decimal(10),
        macd_bfq=Decimal("-1.25"),
        pe=None,
    )
    value.update(values)
    return tuple(value[name] for name in NAMES)


def result(rows=(), *, day=DAY):
    task = DownloadTask(
        "stk_factor_pro", DownloadMode.BY_POINT, points=(day.isoformat(),)
    )
    unit = UnitPlanner(
        validate_task(task, STK_FACTOR_PRO_CONTRACT, 1024 * 1024),
        STK_FACTOR_PRO_CONTRACT,
    ).next_unit()
    assert unit.point == day.isoformat() and unit.mode is DownloadMode.BY_POINT
    records = tuple(SourceRecord(NAMES, values, 0) for values in rows)
    return UnitResult(
        unit,
        records,
        (NAMES,),
        ((("trade_date", day.strftime("%Y%m%d")),),),
        UnitStatistics(1, 0, 1, 1, int(not rows), len(rows), 0, 0.1, 0, 0.1, 0),
        OrderingFacts("trade_date", "1", len(rows), 0),
        TerminationSummary(2, True, 1, None),
    )


def summary(count):
    return DownloadSummary(
        "sample-session",
        DownloadStatus.SUCCEEDED,
        1,
        1,
        1,
        count,
        count,
        1,
        0,
        1,
        True,
        0.1,
        None,
        (),
        0,
        None,
        0,
    )


class Downloader:
    def __init__(self, value, *, final=None, close_error=None, extra=None):
        self.value, self.summary = (
            value,
            summary(len(value.records)) if final is None else final,
        )
        self.close_error, self.extra = close_error, extra
        self.calls = []
        self.closed = False
        self.task_id = "sample-session"

    def download(self, task, **kwargs):
        self.calls.append((task, kwargs))
        return self

    def __enter__(self):
        return self

    def __iter__(self):
        yield self.value
        if self.extra is not None:
            yield self.extra

    def __exit__(self, *_):
        self.closed = True
        if self.close_error:
            raise self.close_error


@contextmanager
def connection(tmp_path):
    temp = tmp_path / "duckdb"
    temp.mkdir(exist_ok=True)
    settings = DuckDBConnectionSettings(
        temp_directory=temp, memory_limit="256MB", threads=1
    )
    with connect_configured_duckdb(settings, temp_policy="existing_no_spill") as conn:
        yield conn
