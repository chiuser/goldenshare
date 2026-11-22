"""独立字面源样本、临时 Parquet 与下载组件替身的 Raw 写入验收。"""

from datetime import date
from decimal import Decimal

import duckdb
import pytest

from orchestrator.defs.io import index_period_writer as writer
from orchestrator.defs.paths import (
    raw_index_monthly_path,
    raw_index_weekly_path,
    silver_index_daily_path,
)
from orchestrator.defs.run_contracts.index_period import (
    INDEX_MONTHLY,
    INDEX_WEEKLY,
    IndexPeriodSilverConfig,
)
from orchestrator.tushare_download.download_models import SourcePage, SourceRecord
from tests.index_period_test_support import (
    daily_input,
    seed_silver,
    silver_inputs,
    silver_update,
)
from tests.test_index_period_contracts import (
    EXPECTED_CODES,
    FIELDS,
    NUMBERS,
    calendar,
    fake_source,
    row,
)


def update(tmp_path, period, key, run_id):
    with duckdb.connect() as connection:
        return writer.write_index_period_raw(
            connection,
            lake_root=tmp_path / "lake",
            staging_root=tmp_path / "staging",
            period=period,
            partition_key=key,
            run_id=run_id,
        )


def prepare(tmp_path):
    with duckdb.connect() as connection:
        calendar(connection, tmp_path / "lake")


def read(path):
    with duckdb.connect() as connection:
        return connection.execute(
            "SELECT * FROM read_parquet(?) ORDER BY ts_code,trade_date", [str(path)]
        ).fetchall()


@pytest.mark.parametrize(
    "period,key,previous",
    [
        (INDEX_WEEKLY, "2026-07-03", "2026-06-26"),
        (INDEX_MONTHLY, "2026-07", "2026-06"),
    ],
)
def test_full_file_merge_units_and_idempotent_replay(
    monkeypatch, tmp_path, period, key, previous
):
    prepare(tmp_path)
    fake_source(monkeypatch, period)
    first = update(tmp_path, period, previous, "previous")
    history = read(first.path)
    fake_source(monkeypatch, period)
    current = update(tmp_path, period, key, "current")
    rows = read(current.path)
    assert len(rows) == 20 and current.check.file_row_count == 20
    assert current.partition_row_count == current.check.source_row_count == 10
    current_day = "20260703" if period == INDEX_WEEKLY else "20260731"
    actual = next(r for r in rows if r[:2] == ("000680.SH", current_day))
    # 原值按已核实股／元／比例保存，不能在Raw转换成Silver单位。
    assert actual[2:] == NUMBERS
    assert tuple(str(v) for v in actual[-3:]) == (
        "-0.0024",
        "37226008500.0000",
        "2922268798699.0000",
    )
    assert [r for r in rows if r[1] != current_day] == history
    fake_source(monkeypatch, period)
    repeated = update(tmp_path, period, key, "repeat")
    assert read(repeated.path) == rows
    expected_path = (
        raw_index_weekly_path if period == INDEX_WEEKLY else raw_index_monthly_path
    )
    assert repeated.path == expected_path(tmp_path / "lake")
    assert sorted(
        p.relative_to(tmp_path / "lake" / "raw").as_posix()
        for p in (tmp_path / "lake" / "raw").rglob("*.parquet")
    ) == [f"{period.dataset_id}/full/part-000.parquet"]


@pytest.mark.parametrize(
    "period,key", [(INDEX_WEEKLY, "2026-07-03"), (INDEX_MONTHLY, "2026-07")]
)
def test_same_key_revision_and_optional_bse_preserve_history(
    monkeypatch, tmp_path, period, key
):
    prepare(tmp_path)

    def all_codes(request, attempt):
        p = dict(request.params)
        return (row(p["ts_code"], p["trade_date"]),)

    fake_source(monkeypatch, period, all_codes)
    initial = update(tmp_path, period, key, "all")
    bse = next(r for r in read(initial.path) if r[0] == "899050.BJ")

    def revised(request, attempt):
        p = dict(request.params)
        if p["ts_code"] == "899050.BJ":
            return ()
        return ((p["ts_code"], p["trade_date"], Decimal("2400.0000"), *NUMBERS[1:]),)

    fake_source(monkeypatch, period, revised)
    changed = update(tmp_path, period, key, "changed")
    rows = read(changed.path)
    assert len(rows) == changed.partition_row_count == 11
    assert changed.check.source_row_count == 10
    assert next(r for r in rows if r[0] == "899050.BJ") == bse
    assert all(r[2] == Decimal("2400.0000") for r in rows if r[0] != "899050.BJ")


@pytest.mark.parametrize(
    "problem",
    [
        "missing",
        "wrong_code",
        "wrong_date",
        "missing_field",
        "duplicate",
        "interrupted",
    ],
)
def test_bad_or_interrupted_unit_never_changes_target(monkeypatch, tmp_path, problem):
    prepare(tmp_path)
    fake_source(monkeypatch, INDEX_WEEKLY)
    initial = update(tmp_path, INDEX_WEEKLY, "2026-06-26", "initial")
    before = initial.path.read_bytes()

    def broken(request, attempt):
        p = dict(request.params)
        code, day = p["ts_code"], p["trade_date"]
        if code != "399001.SZ":
            return () if code == "899050.BJ" else (row(code, day),)
        if problem == "missing":
            return ()
        if problem == "wrong_code":
            return (row("999999.SH", day),)
        if problem == "wrong_date":
            return (row(code, "20260702"),)
        if problem == "missing_field":
            return SourcePage(
                FIELDS[:-1], (SourceRecord(FIELDS[:-1], row(code, day)[:-1], 0),)
            )
        if problem == "duplicate":
            return (row(code, day), row(code, day))
        raise RuntimeError("人工模拟下载中断")

    calls, transports, _ = fake_source(monkeypatch, INDEX_WEEKLY, broken)
    with pytest.raises((ValueError, RuntimeError)):
        update(tmp_path, INDEX_WEEKLY, "2026-07-03", "broken")
    assert initial.path.read_bytes() == before
    assert len(calls) == 2 and transports[0].closed == 1
    assert not list((tmp_path / "staging" / "broken").rglob("*.parquet"))


def test_candidate_schema_failure_and_manual_retry(monkeypatch, tmp_path):
    prepare(tmp_path)
    fake_source(monkeypatch, INDEX_WEEKLY)
    initial = update(tmp_path, INDEX_WEEKLY, "2026-06-26", "initial")
    before = initial.path.read_bytes()
    original_copy = writer.copy_query_to_parquet
    with monkeypatch.context() as patch:
        patch.setattr(
            writer,
            "copy_query_to_parquet",
            lambda sql, path: original_copy(
                f"SELECT *, 1 AS unexpected FROM ({sql})", path
            ),
        )
        fake_source(patch, INDEX_WEEKLY)
        with pytest.raises(writer.IndexPeriodContractError) as error:
            update(tmp_path, INDEX_WEEKLY, "2026-07-03", "bad-candidate")
        assert error.value.result.failure_counts["schema"] == 1
    assert initial.path.read_bytes() == before
    fake_source(monkeypatch, INDEX_WEEKLY)
    result = update(tmp_path, INDEX_WEEKLY, "2026-07-03", "manual-retry")
    assert result.check.passed and len(read(result.path)) == 20


def test_promotion_interruption_keeps_original_file(monkeypatch, tmp_path):
    prepare(tmp_path)
    fake_source(monkeypatch, INDEX_WEEKLY)
    initial = update(tmp_path, INDEX_WEEKLY, "2026-06-26", "initial")
    before = initial.path.read_bytes()

    def interrupted(*args):
        raise OSError("人工模拟提升前中断")

    monkeypatch.setattr(writer.os, "replace", interrupted)
    fake_source(monkeypatch, INDEX_WEEKLY)
    with pytest.raises(OSError, match="中断"):
        update(tmp_path, INDEX_WEEKLY, "2026-07-03", "interrupted")
    assert initial.path.read_bytes() == before
    assert list((tmp_path / "staging" / "interrupted").rglob("*.parquet"))


def test_accepted_raw_history_is_preserved_without_origin_or_price_audit(
    monkeypatch, tmp_path
):
    prepare(tmp_path)
    fake_source(monkeypatch, INDEX_WEEKLY)
    initial = update(tmp_path, INDEX_WEEKLY, "2026-06-26", "initial")
    replacement = tmp_path / "with-history.parquet"
    # 方案§2明确保留A500发布前20240920 Raw。零前收盘亦不能被新价格check拒绝。
    with duckdb.connect() as connection:
        connection.execute(
            """COPY (
            SELECT * FROM read_parquet($source) UNION ALL
            SELECT '000510.SH','20240920',
                1000::DECIMAL(18,4),1000::DECIMAL(18,4),1000::DECIMAL(18,4),1000::DECIMAL(18,4),
                0::DECIMAL(18,4),0::DECIMAL(18,4),0::DECIMAL(10,4),0::DECIMAL(20,4),0::DECIMAL(20,4)
        ) TO $target (FORMAT PARQUET)""",
            {"source": str(initial.path), "target": str(replacement)},
        )
    replacement.replace(initial.path)
    accepted = next(r for r in read(initial.path) if r[1] == "20240920")
    fake_source(monkeypatch, INDEX_WEEKLY)
    result = update(tmp_path, INDEX_WEEKLY, "2026-07-03", "after-history")
    assert result.check.passed and result.check.file_row_count == 21
    assert next(r for r in read(result.path) if r[1] == "20240920") == accepted


@pytest.mark.parametrize(
    "keys,source_count,expected_file_count,rule",
    [
        (((None, "20260703"),), 1, 10, "code_or_date"),
        ((("000680.SH", "20260702"),), 1, 10, "code_or_date"),
        ((("000680.SH", "20260703"),) * 2, 2, 10, "duplicate_key"),
        ((("000680.SH", "20260703"),), 2, 10, "source_row_count"),
        ((("000680.SH", "20260703"),), 1, 11, "file_row_count"),
    ],
)
def test_shared_file_check_rejects_bad_delta_and_transfer(
    monkeypatch, tmp_path, keys, source_count, expected_file_count, rule
):
    prepare(tmp_path)
    fake_source(monkeypatch, INDEX_WEEKLY)
    result = update(tmp_path, INDEX_WEEKLY, "2026-07-03", "good")
    with duckdb.connect() as connection:
        connection.execute("CREATE TABLE delta(ts_code VARCHAR,trade_date VARCHAR)")
        connection.executemany("INSERT INTO delta VALUES (?,?)", keys)
        check = writer.check_index_period_raw_file(
            connection,
            path=result.path,
            delta_relation="delta",
            source_row_count=source_count,
            expected_file_row_count=expected_file_count,
            codes=("000680.SH",),
            period_end=result.period_end,
        )
    assert not check.passed and check.failure_counts[rule] == 1


@pytest.fixture
def no_source(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Silver必须只读DG文件，不得下载日线或周月线")

    monkeypatch.setattr(writer.TushareDownloader, "load", forbidden)


@pytest.mark.parametrize(
    "period,key", [(INDEX_WEEKLY, "2026-07-03"), (INDEX_MONTHLY, "2026-07")]
)
def test_silver_literal_daily_and_same_day_replay(tmp_path, no_source, period, key):
    root = tmp_path / "lake"
    silver_inputs(root)
    if period == INDEX_WEEKLY:
        seed_silver(root, period)
    for target in ("2026-07-01", "2026-07-02", "2026-07-03"):
        result = silver_update(
            root, period, key, {"mode": "daily", "trade_date": target}, target
        )
    rows = read(result.path)
    assert len(rows) == 11
    expected = (
        Decimal("100.0000"),
        Decimal("109.0000"),
        Decimal("98.0000"),
        Decimal("104.0000"),
        Decimal("100.0000"),
        Decimal("4.0000"),
        Decimal("4.0000"),
        Decimal("600.705700"),
        Decimal("902.0357000"),
    )
    assert all(r[3:] == expected for r in rows)
    assert all(
        r[1] == (date(2026, 6, 29) if period == INDEX_WEEKLY else date(2026, 7, 1))
        for r in rows
    )
    again = silver_update(
        root, period, key, {"mode": "daily", "trade_date": "2026-07-03"}, "again"
    )
    assert read(again.path) == rows


@pytest.mark.parametrize(
    ("statement", "failure", "sample"),
    [
        (
            "UPDATE index_period_synthesized SET trade_date=DATE '2026-06-30' WHERE ts_code='000300.SH'",
            "wrong_date_count",
            {
                "ts_code": "000300.SH",
                "reason": "wrong_date",
                "trade_date": "2026-06-30",
            },
        ),
        (
            "UPDATE index_period_synthesized SET trade_date=DATE '2026-07-02' WHERE ts_code='000300.SH'",
            "wrong_date_count",
            {
                "ts_code": "000300.SH",
                "reason": "wrong_date",
                "trade_date": "2026-07-02",
            },
        ),
        (
            "UPDATE index_period_synthesized SET ts_code='009999.SH' WHERE ts_code='000300.SH'",
            "extra_count",
            {"ts_code": "000300.SH", "reason": "missing"},
        ),
        (
            "INSERT INTO index_period_synthesized SELECT * FROM index_period_synthesized WHERE ts_code='000300.SH'",
            "duplicate_count",
            {"ts_code": "000300.SH", "reason": "duplicate"},
        ),
        (
            "DELETE FROM index_period_synthesized WHERE ts_code='899050.BJ'",
            "missing_count",
            {"ts_code": "899050.BJ", "reason": "missing"},
        ),
    ],
)
def test_silver_coverage_blocks_bad_current_period_before_promotion(
    tmp_path, no_source, monkeypatch, statement, failure, sample
):
    root = tmp_path / "lake"
    silver_inputs(root)
    if failure in {"missing_count", "extra_count"}:
        period, key = INDEX_MONTHLY, "2026-07"
        path = seed_silver(root, period, start="2026-06-01")
    else:
        period, key = INDEX_WEEKLY, "2026-07-03"
        path = seed_silver(root, period)
    previous_bytes = path.read_bytes()
    synthesize = writer.synthesize_index_period

    def bad_output(connection, **kwargs):
        inputs = synthesize(connection, **kwargs)
        connection.execute(statement)
        return inputs

    monkeypatch.setattr(writer, "synthesize_index_period", bad_output)
    config = {"mode": "daily", "trade_date": "2026-07-01"}
    with pytest.raises(writer.IndexPeriodContractError) as failure_record:
        silver_update(root, period, key, config)
    coverage = failure_record.value.result.coverage
    assert failure_record.value.as_of.isoformat() == "2026-07-01"
    assert coverage["passed"] is False and coverage[failure] == 1
    assert sample in coverage["samples"]
    assert path.read_bytes() == previous_bytes

    monkeypatch.setattr(writer, "synthesize_index_period", synthesize)
    retry = silver_update(root, period, key, config, "retry")
    assert retry.check.passed and retry.check.coverage["actual_count"] == 11


def test_silver_coverage_switches_expected_codes_on_listing_day(tmp_path, no_source):
    root = tmp_path / "lake"
    silver_inputs(root)
    path = writer.silver_index_basic_path(root)
    with duckdb.connect() as connection:
        connection.execute(
            "CREATE TABLE listings AS SELECT * FROM read_parquet(?)", [str(path)]
        )
        connection.execute(
            "UPDATE listings SET list_date=DATE '2026-07-02' WHERE ts_code='000680.SH'"
        )
        connection.execute("COPY listings TO ? (FORMAT PARQUET)", [str(path)])
    first = silver_update(
        root, INDEX_MONTHLY, "2026-07", {"mode": "daily", "trade_date": "2026-07-01"}
    )
    assert (
        first.check.coverage["expected_count"]
        == first.check.coverage["actual_count"]
        == 10
    )
    assert not any(row[0] == "000680.SH" for row in read(first.path))
    second = silver_update(
        root, INDEX_MONTHLY, "2026-07", {"mode": "daily", "trade_date": "2026-07-02"}
    )
    assert (
        second.check.coverage["expected_count"]
        == second.check.coverage["actual_count"]
        == 11
    )
    assert any(row[0] == "000680.SH" for row in read(second.path))


@pytest.mark.parametrize(
    "close,expected",
    [
        ("2000.1000", "0.0100"),
        ("1999.9000", "-0.0100"),
        ("2000.0999", "0.0000"),
        ("1999.9001", "0.0000"),
    ],
)
def test_positive_and_negative_half_up(tmp_path, no_source, close, expected):
    root = tmp_path / "lake"
    silver_inputs(root)
    daily_input(root, "2026-07-01", (2000, 2001, 1999, float(close), 2000, 0, 0))
    result = silver_update(
        root, INDEX_MONTHLY, "2026-07", {"mode": "daily", "trade_date": "2026-07-01"}
    )
    assert all(r[9] == Decimal(expected) for r in read(result.path))


@pytest.mark.parametrize(
    "problem",
    [
        "missing_file",
        "missing_code",
        "duplicate",
        "null",
        "zero_preclose",
        "no_previous",
        "backwards",
    ],
)
def test_silver_bad_input_fails_and_manual_retry(tmp_path, no_source, problem):
    root = tmp_path / "lake"
    silver_inputs(root)
    path = seed_silver(
        root, INDEX_WEEKLY, day="2026-07-03" if problem == "backwards" else "2026-06-30"
    )
    before = path.read_bytes()
    day = silver_index_daily_path(
        root, "2026-06-29" if problem == "zero_preclose" else "2026-07-01"
    )
    if problem == "missing_file":
        day.unlink()
    elif problem == "missing_code":
        daily_input(
            root,
            "2026-07-01",
            (100, 104, 98, 102, 100, 1, 2),
            codes=EXPECTED_CODES[:-1],
        )
    elif problem in ("null", "zero_preclose", "duplicate"):
        with duckdb.connect() as connection:
            connection.execute(
                "CREATE TABLE bad AS SELECT * FROM read_parquet(?)", [str(day)]
            )
            if problem == "duplicate":
                connection.execute("INSERT INTO bad SELECT * FROM bad LIMIT 1")
            else:
                connection.execute(
                    "UPDATE bad SET pre_close=" + ("NULL" if problem == "null" else "0")
                )
            connection.execute(f"COPY bad TO '{day}' (FORMAT PARQUET)")
    elif problem == "no_previous":
        path.unlink()
    with pytest.raises(ValueError):
        silver_update(
            root,
            INDEX_WEEKLY,
            "2026-07-03",
            {"mode": "daily", "trade_date": "2026-07-01"},
        )
    if problem != "no_previous":
        assert path.read_bytes() == before
    if problem == "missing_file":
        daily_input(root, "2026-07-01", (100, 104, 98, 102, 100, 100.1256, 200.5678))
        assert silver_update(
            root,
            INDEX_WEEKLY,
            "2026-07-03",
            {"mode": "daily", "trade_date": "2026-07-01"},
            "retry",
        ).check.passed


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"mode": "unknown"},
        {"mode": "daily"},
        {"mode": "period", "trade_date": "2026-07-03"},
        {"mode": "repair", "trade_date": "2026-07-03"},
        {"mode": "daily", "trade_date": "2026-07-01", "source": "tushare"},
    ],
)
def test_silver_config_rejects_unapproved_inputs(config):
    with pytest.raises(ValueError):
        IndexPeriodSilverConfig(**config)


def test_period_override_preserves_bse_and_does_not_read_daily(tmp_path, no_source):
    root = tmp_path / "lake"
    silver_inputs(root)
    old = seed_silver(root, INDEX_WEEKLY, day="2026-07-03")
    bse = next(r for r in read(old) if r[0] == "899050.BJ")
    raw = raw_index_weekly_path(root)
    raw.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as connection:
        projection = ", ".join(
            f'CAST("{c.name}" AS {c.type}) AS "{c.name}"'
            for c in writer.RAW_INDEX_WEEKLY_SCHEMA
        )
        connection.execute(
            f"""COPY (SELECT {projection} FROM (SELECT code ts_code,'20260703' trade_date,
            104 AS "close",100 open,109 high,98 low,100 pre_close,4 change,0.0123 pct_chg,12345.6789 vol,98765.4321 amount
            FROM unnest(?::VARCHAR[])t(code))) TO '{raw}' (FORMAT PARQUET)""",
            [tuple(c for c in EXPECTED_CODES if c != "899050.BJ")],
        )
    for path in (root / "silver" / "index_daily").rglob("*.parquet"):
        path.unlink()
    result = silver_update(root, INDEX_WEEKLY, "2026-07-03", {"mode": "period"})
    rows = read(result.path)
    assert next(r for r in rows if r[0] == "899050.BJ") == bse
    assert all(
        r[9:] == (Decimal("1.2300"), Decimal("123.456789"), Decimal("98.7654321"))
        for r in rows
        if r[0] != "899050.BJ"
    )
    assert silver_update(
        root, INDEX_WEEKLY, "2026-07-03", {"mode": "repair"}, "keep-complete"
    ).check.passed
    assert read(result.path) == rows


def test_repair_full_window_without_previous_and_preserves_other_history(
    tmp_path, no_source
):
    root = tmp_path / "lake"
    silver_inputs(root)
    path = seed_silver(root, INDEX_WEEKLY, start="2026-06-22", day="2026-06-26")
    history = read(path)
    result = silver_update(root, INDEX_WEEKLY, "2026-07-03", {"mode": "repair"})
    assert len(read(result.path)) == 22
    assert [r for r in read(result.path) if r[1] == date(2026, 6, 22)] == history


@pytest.mark.parametrize(
    "period,last_key,next_key",
    [(INDEX_WEEKLY, "2026-12-31", "2027-01-08"), (INDEX_MONTHLY, "2026-12", "2027-01")],
)
def test_publication_holiday_and_year_boundary(
    tmp_path, no_source, period, last_key, next_key
):
    from orchestrator.defs.paths import (
        silver_index_basic_path,
        silver_trade_calendar_path,
    )

    root = tmp_path / "lake"
    silver_inputs(root)
    # 明确的人工发布日期和休市边界，不能用作真实指数历史证据。
    with duckdb.connect() as connection:
        basic = silver_index_basic_path(root)
        connection.execute(
            "CREATE TABLE basic AS SELECT * FROM read_parquet(?)", [str(basic)]
        )
        connection.execute(
            "UPDATE basic SET list_date=CASE WHEN ts_code='000680.SH' THEN DATE '2026-12-31' ELSE DATE '2026-12-30' END"
        )
        connection.execute(f"COPY basic TO '{basic}' (FORMAT PARQUET)")
        calendar_path = silver_trade_calendar_path(root)
        connection.execute(
            "CREATE TABLE calendar AS SELECT * FROM read_parquet(?)",
            [str(calendar_path)],
        )
        connection.execute(
            "UPDATE calendar SET is_open=false WHERE trade_date=DATE '2027-01-01'"
        )
        connection.execute(f"COPY calendar TO '{calendar_path}' (FORMAT PARQUET)")
    daily_input(root, "2026-12-30", (10, 12, 9, 11, 10, 100, 200))
    first = silver_update(
        root, period, last_key, {"mode": "daily", "trade_date": "2026-12-30"}, "first"
    )
    assert len(read(first.path)) == 10
    assert all(r[0] != "000680.SH" for r in read(first.path))
    daily_input(root, "2026-12-31", (11, 14, 10, 12, 11, 300, 400))
    last = silver_update(
        root, period, last_key, {"mode": "daily", "trade_date": "2026-12-31"}, "last"
    )
    accepted = read(last.path)
    assert len(accepted) == 11
    publication = next(r for r in accepted if r[0] == "000680.SH")
    assert publication[3:] == tuple(
        map(Decimal, ("11", "14", "10", "12", "11", "1", "9.09", "300", "400"))
    )
    daily_input(root, "2027-01-04", (12, 15, 11, 13, 12, 500, 600))
    following = silver_update(
        root,
        period,
        next_key,
        {"mode": "daily", "trade_date": "2027-01-04"},
        "following",
    )
    assert len(read(following.path)) == 22
    assert [r for r in read(following.path) if r[2] == date(2026, 12, 31)] == accepted
    assert all(
        r[1] == date(2027, 1, 4)
        for r in read(following.path)
        if r[2] == date(2027, 1, 4)
    )


def test_silver_reuses_loaded_history_for_continuity_and_merge(tmp_path, no_source):
    root = tmp_path / "lake"
    silver_inputs(root)
    path = seed_silver(root, INDEX_WEEKLY)
    reads = []
    with duckdb.connect() as connection:

        class TracedConnection:
            def execute(self, sql, *args):
                if str(path) in sql and "read_parquet" in sql:
                    reads.append(sql)
                return connection.execute(sql, *args)

        result = writer.write_index_period_silver(
            TracedConnection(),
            lake_root=root,
            period=INDEX_WEEKLY,
            partition_key="2026-07-03",
            run_id="single-history-read",
            staging_root=tmp_path / "staging",
            config=IndexPeriodSilverConfig(mode="daily", trade_date="2026-07-01"),
        )
    assert result.check.passed and len(reads) == 1


@pytest.mark.parametrize(
    "period,key", [(INDEX_WEEKLY, "2026-07-03"), (INDEX_MONTHLY, "2026-07")]
)
def test_repair_rejects_unfinished_cycle(tmp_path, monkeypatch, no_source, period, key):
    from datetime import datetime

    class FixedClock:
        @classmethod
        def now(cls, tz):
            return datetime(2026, 7, 1, 19, tzinfo=tz)

    monkeypatch.setattr(writer, "datetime", FixedClock)
    root = tmp_path / "lake"
    silver_inputs(root)
    with pytest.raises(ValueError, match="已结束周期"):
        silver_update(root, period, key, {"mode": "repair"})
    assert not writer.index_period_path(root, period, "silver").exists()
