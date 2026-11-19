import json
from datetime import date, timedelta
from hashlib import sha256

import dagster as dg
import duckdb
import pytest

from orchestrator.defs import tushare_api_io
from orchestrator.defs.assets import calendar
from orchestrator.defs.checks import calendar_checks
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.jobs.calendar_update import calendar_update_job
from orchestrator.defs.paths import (
    RAW,
    SILVER,
    raw_trade_calendar_path,
    silver_trade_calendar_path,
    trade_calendar_staging_path,
)
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    TushareResource,
    TushareResult,
)

# The local trade_cal source document and LLD §2.2 fix the four field names,
# the YYYYMMDD date representation, the integer flag and the paging evidence.
SOURCE_COLUMNS = ("exchange", "cal_date", "is_open", "pretrade_date")
BASELINE = [
    ("SSE", "20261230", 1, None),
    ("SSE", "20261231", 1, "20261230"),
]
CURRENT = [
    ("SSE", "20270104", 1, "20261231"),
    ("SSE", "20270103", 0, "20261231"),
    ("SSE", "20270102", 0, "20261231"),
    ("SSE", "20270101", 0, "20261231"),
    *reversed(BASELINE),
]


def _minimum_end_date(value):
    return {
        "ops": {"raw_tushare_trade_calendar": {"config": {"minimum_end_date": value}}}
    }


_RETRY_JOBS = {}


def _isolated_retry_job(job_key):
    return _RETRY_JOBS[job_key]


def _seed_published_files(root, rows=BASELINE):
    raw, silver = raw_trade_calendar_path(root), silver_trade_calendar_path(root)
    for path in (raw, silver):
        path.parent.mkdir(parents=True)
    with duckdb.connect() as connection:
        connection.execute(
            "CREATE TABLE fixture(exchange VARCHAR, cal_date VARCHAR, is_open INTEGER, pretrade_date VARCHAR)"
        )
        connection.executemany("INSERT INTO fixture VALUES (?, ?, ?, ?)", rows)
        connection.execute("COPY fixture TO ? (FORMAT PARQUET)", [str(raw)])
        connection.execute(
            """
            COPY (SELECT exchange, strptime(cal_date, '%Y%m%d')::DATE trade_date,
                         is_open = 1 AS is_open,
                         strptime(pretrade_date, '%Y%m%d')::DATE pretrade_date
                  FROM fixture) TO ? (FORMAT PARQUET)
            """,
            [str(silver)],
        )
    return raw, silver


def _load_rows(path, order_by):
    with duckdb.connect() as connection:
        return connection.execute(
            f"SELECT * FROM read_parquet(?) ORDER BY {order_by}", [str(path)]
        ).fetchall()


@pytest.fixture
def isolated_calendar(tmp_path, monkeypatch):
    root = tmp_path / "data_lake"
    for layer in (RAW, SILVER, "gold"):
        (root / layer).mkdir(parents=True)
    (tmp_path / "data_lake_staging").mkdir()
    temp_directory = tmp_path / "duckdb"
    temp_directory.mkdir()
    settings = DuckDBConnectionSettings(temp_directory=temp_directory)

    def isolated_connection():
        return connect_configured_duckdb(settings, temp_policy="existing_no_spill")

    for module in (calendar, calendar_checks, tushare_api_io):
        monkeypatch.setattr(module, "connect_configured_duckdb", isolated_connection)

    calls = []
    source = {"rows": list(CURRENT), "columns": SOURCE_COLUMNS}

    def call(self, api_name, params, fields):
        assert self.token == "isolated-test"
        calls.append((api_name, dict(params), tuple(fields)))
        offset = params["offset"]
        rows = source["rows"][offset : offset + params["limit"]]
        return TushareResult(
            [dict(zip(SOURCE_COLUMNS, row, strict=True)) for row in rows],
            source["columns"],
            {},
        )

    monkeypatch.setattr(TushareResource, "call", call)
    defs = dg.Definitions(
        assets=[calendar.raw_tushare_trade_calendar, calendar.silver_trade_calendar],
        asset_checks=[
            calendar_checks.raw_trade_calendar_contract_check,
            calendar_checks.silver_trade_calendar_unique_exchange_trade_date,
            calendar_checks.silver_trade_calendar_required_columns_non_null,
        ],
        jobs=[calendar_update_job],
        resources={
            "lake_root": LakeRootResource(root_path=str(root)),
            "duckdb": DuckDBResource(),
            "tushare": TushareResource(token="isolated-test"),
        },
    )
    return root, defs.resolve_job_def("calendar_update_job"), calls, source


@pytest.mark.parametrize("minimum_end_date", ["2027-12-30", "2027-12-31"])
def test_calendar_job_reads_unbounded_dates_and_publishes_both_files(
    isolated_calendar, minimum_end_date
):
    root, job, calls, source = isolated_calendar
    raw, silver = _seed_published_files(root)
    start = date(1990, 12, 19)
    end = date(2027, 12, 31)
    # Synthetic full-sized request with the probed source boundaries and row count.
    # Opening every day here gives predictable flags and preceding dates.
    source["rows"] = [
        ("SSE", day.strftime("%Y%m%d"), 1, previous)
        for offset in range(13527)
        for day in (end - timedelta(days=offset),)
        for previous in (
            None if day == start else (day - timedelta(days=1)).strftime("%Y%m%d"),
        )
    ]
    result = job.execute_in_process(run_config=_minimum_end_date(minimum_end_date))
    assert result.success
    assert calls == [
        (
            "trade_cal",
            {"exchange": "SSE", "limit": 6000, "offset": offset},
            SOURCE_COLUMNS,
        )
        for offset in (0, 6000, 12000)
    ]
    assert len(result.get_asset_check_evaluations()) == 3
    assert all(check.passed for check in result.get_asset_check_evaluations())
    materializations = {
        item.asset_key.path[-1]: item
        for item in result.asset_materializations_for_node("raw_tushare_trade_calendar")
    }
    raw_event = materializations["raw_tushare_trade_calendar"]
    assert raw_event.metadata["goldenshare/page_count"].value == 3
    assert raw_event.metadata["dagster/uri"].value == str(raw)
    assert raw_event.metadata["goldenshare/historical_pretrade_date_changes"].value == 1

    raw_rows = _load_rows(raw, "cal_date")
    silver_rows = _load_rows(silver, "trade_date")
    assert len(raw_rows) == len(silver_rows) == 13527
    assert raw_rows[0] == ("SSE", "19901219", 1, None)
    assert raw_rows[-1] == ("SSE", "20271231", 1, "20271230")
    assert silver_rows[0] == ("SSE", start, True, None)
    assert silver_rows[-1] == ("SSE", end, True, date(2027, 12, 30))
    for layer, target in ((RAW, raw), (SILVER, silver)):
        candidate = trade_calendar_staging_path(root, result.run_id, layer)
        assert not candidate.exists()
        record = json.loads(candidate.with_name("publication.json").read_text())
        assert record["state"] == "published"
        assert record["row_count"] == 13527
        assert record["sha256"] == sha256(target.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    ("rows", "columns", "diagnostic"),
    [
        ([], SOURCE_COLUMNS, "returned 0 rows"),
        (CURRENT, SOURCE_COLUMNS[:-1], "returned columns"),
        ([CURRENT[0], *CURRENT], SOURCE_COLUMNS, "重复日期"),
        ([*CURRENT[:2], *CURRENT[3:]], SOURCE_COLUMNS, "日期不连续"),
        (
            [*CURRENT[:4], ("SSE", "20261231", 1, None)],
            SOURCE_COLUMNS,
            "已发布日期",
        ),
        ([("SSE", "20270230", 1, None)], SOURCE_COLUMNS, "日期格式非法"),
        ([("SZSE", "20261230", 1, None)], SOURCE_COLUMNS, "无效记录"),
        ([("SSE", "20261230", 2, None)], SOURCE_COLUMNS, "开市标记非法"),
        ([("SSE", "20261230", 1.2, None)], SOURCE_COLUMNS, "开市标记非法"),
        ([("SSE", "20261230", "0.4", None)], SOURCE_COLUMNS, "开市标记非法"),
        (
            [("SSE", "20270104", 1, "20270103"), *CURRENT[1:]],
            SOURCE_COLUMNS,
            "上一交易日不一致",
        ),
        (
            [("SSE", "20270104", 1, None), *CURRENT[1:]],
            SOURCE_COLUMNS,
            "上一交易日不一致",
        ),
    ],
)
def test_invalid_source_never_replaces_published_files(
    isolated_calendar, rows, columns, diagnostic
):
    root, job, _, source = isolated_calendar
    raw, silver = _seed_published_files(root)
    old_files = raw.read_bytes(), silver.read_bytes()
    source.update(rows=rows, columns=columns)
    result = job.execute_in_process(raise_on_error=False)
    failure = result.failure_data_for_node("raw_tushare_trade_calendar")
    assert not result.success and diagnostic in str(failure.error)
    assert (raw.read_bytes(), silver.read_bytes()) == old_files


def test_calendar_rejects_contiguous_source_that_ends_too_early(isolated_calendar):
    root, job, _, source = isolated_calendar
    raw, silver = _seed_published_files(root)
    old_files = raw.read_bytes(), silver.read_bytes()
    source["rows"] = list(reversed(BASELINE))
    result = job.execute_in_process(
        run_config=_minimum_end_date("2027-12-31"), raise_on_error=False
    )
    failure = result.failure_data_for_node("raw_tushare_trade_calendar")
    assert not result.success and "早于本次要求" in str(failure.error)
    assert (raw.read_bytes(), silver.read_bytes()) == old_files


@pytest.mark.parametrize("failure_stage", ["raw_checkpoint", "silver", "raw_modified"])
def test_calendar_job_retry_checks_the_published_raw(
    isolated_calendar, monkeypatch, tmp_path, failure_stage
):
    root, job, calls, source = isolated_calendar
    raw, silver = _seed_published_files(root)
    old_silver = silver.read_bytes()
    source["rows"] = [
        (exchange, day, str(flag), previous)
        for exchange, day, flag, previous in CURRENT
    ]
    compare = calendar._verify_silver_matches_raw
    write_record = calendar._write_publication_record

    def fail_silver(*args):
        raise RuntimeError("simulated Silver validation failure")

    def fail_raw_checkpoint(path, record):
        if path.parent.name == RAW and record["state"] == "published":
            raise RuntimeError("simulated failure writing the Raw publication record")
        write_record(path, record)

    if failure_stage == "raw_checkpoint":
        monkeypatch.setattr(calendar, "_write_publication_record", fail_raw_checkpoint)
        failed_node = "raw_tushare_trade_calendar"
    else:
        monkeypatch.setattr(calendar, "_verify_silver_matches_raw", fail_silver)
        failed_node = "silver_trade_calendar"

    job_key = str(tmp_path)
    monkeypatch.setitem(_RETRY_JOBS, job_key, job)
    reconstructable_job = dg.build_reconstructable_job(
        __name__, "_isolated_retry_job", (job_key,)
    )
    instance_root = tmp_path / "dagster"
    instance_root.mkdir()
    with dg.DagsterInstance.local_temp(str(instance_root)) as instance:
        run_config = _minimum_end_date("2027-01-04")
        run_config["execution"] = {"config": {"in_process": {}}}
        parent_result = dg.execute_job(
            reconstructable_job, instance, run_config=run_config
        )
        assert not parent_result.success
        assert parent_result.failure_data_for_node(failed_node)
        assert silver.read_bytes() == old_silver
        assert len(_load_rows(raw, "cal_date")) == 6
        assert len(calls) == 1

        candidate = trade_calendar_staging_path(root, parent_result.run_id, RAW)
        record = json.loads(candidate.with_name("publication.json").read_text())
        assert not candidate.exists()
        assert record["state"] == (
            "validated" if failure_stage == "raw_checkpoint" else "published"
        )
        assert record["sha256"] == sha256(raw.read_bytes()).hexdigest()

        monkeypatch.setattr(calendar, "_verify_silver_matches_raw", compare)
        monkeypatch.setattr(calendar, "_write_publication_record", write_record)
        if failure_stage == "raw_modified":
            with raw.open("ab") as stream:
                stream.write(b"unexpected-modification")

        retry_result = dg.execute_job(
            reconstructable_job,
            instance,
            reexecution_options=dg.ReexecutionOptions.from_failure(
                parent_result.run_id, instance
            ),
        )
        assert len(calls) == 1
        if failure_stage == "raw_modified":
            failure = retry_result.failure_data_for_node("silver_trade_calendar")
            assert not retry_result.success
            assert "Raw 交易日历与本次运行链的发布记录不一致" in str(failure.error)
            assert silver.read_bytes() == old_silver
            return

        assert retry_result.success
        assert _load_rows(silver, "trade_date")[-1] == (
            "SSE",
            date(2027, 1, 4),
            True,
            date(2026, 12, 31),
        )
