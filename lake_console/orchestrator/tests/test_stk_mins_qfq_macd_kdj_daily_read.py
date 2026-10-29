"""Bounded daily inputs, literal formula results, and old-state compatibility.

Files follow the real QFQ/state schemas and stock-year producer layout. Literal
expectations below are independently derived from MACD(12,26,9)/KDJ(9,3,3).
The connection seam changes only test resource settings; SQL, formulas and
publication remain real. No production Lake, instance, credentials or network.
"""

from contextlib import contextmanager
from datetime import date, datetime, timedelta

import dagster as dg
import duckdb
import pytest

from orchestrator.defs import stk_mins_qfq as qfq_module
from orchestrator.defs import stk_mins_qfq_macd_kdj as module
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.paths import (
    gold_stk_mins_qfq_macd_kdj_path,
    gold_stk_mins_qfq_macd_kdj_state_path,
    gold_stk_mins_qfq_path,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA,
    GOLD_STK_MINS_QFQ_SCHEMA,
)

CODE = "600000.SH"
OTHER = "000001.SZ"
DAY = "2026-10-29"
PRIOR = "2026-10-28"
NEXT = "2026-10-30"
FREQUENCIES = (1, 5, 15, 30, 60, 90, 120)
TIMES = {
    1: ("09:30:00", "09:31:00"),
    5: ("09:35:00", "09:40:00"),
    15: ("09:45:00", "10:00:00"),
    30: ("10:00:00", "10:30:00"),
    60: ("10:30:00", "11:30:00"),
    90: ("11:00:00", "14:00:00"),
    120: ("11:30:00", "15:00:00"),
}
VALUE_FIELDS = (
    "macd_dif_qfq",
    "macd_dea_qfq",
    "macd_qfq",
    "kdj_k_qfq",
    "kdj_d_qfq",
    "kdj_qfq",
)


class RecordingConnection:
    def __init__(self, connection, queries):
        self.connection = connection
        self.queries = queries

    def execute(self, query, *args, **kwargs):
        self.queries.append(str(query))
        return self.connection.execute(query, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.connection, name)


@pytest.fixture
def isolated_connections(tmp_path, monkeypatch):
    queries = []
    settings = DuckDBConnectionSettings(
        temp_directory=tmp_path / "duckdb",
        memory_limit="128MiB",
        max_temp_directory_size="64MiB",
        threads=1,
    )

    @contextmanager
    def connect(*_args, **_kwargs):
        with connect_configured_duckdb(settings) as connection:
            yield RecordingConnection(connection, queries)

    monkeypatch.setattr(module, "connect_configured_duckdb", connect)
    return queries


def write_rows(path, schema, rows):
    """Synthetic producer-contract fixture, never a consumer-inferred schema."""
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = tuple(column.name for column in schema)
    declarations = ", ".join(f'"{c.name}" {c.type}' for c in schema)
    with duckdb.connect(
        ":memory:",
        config={
            "temp_directory": str(path.parent / "fixture_duckdb"),
            "memory_limit": "128MiB",
            "threads": 1,
        },
    ) as connection:
        connection.execute(f"CREATE TEMP TABLE fixture ({declarations})")
        if rows:
            placeholders = ", ".join("?" for _ in columns)
            connection.executemany(
                f"INSERT INTO fixture VALUES ({placeholders})",
                [[row[column] for column in columns] for row in rows],
            )
        connection.execute(copy_query_to_parquet("SELECT * FROM fixture", path))


def qfq(day, *, freq=1, code=CODE, time=None, close=10.0, high=11.0, low=9.0):
    return {
        "ts_code": code,
        "freq": freq,
        "trade_date": day,
        "trade_time": f"{day} {time or TIMES[freq][0]}",
        "open": close,
        "high": high,
        "low": low,
        "close": close,
        "vol": 100.0,
        "amount": 1000.0,
        "exchange": "SSE" if code.endswith(".SH") else "SZSE",
    }


def state(day=PRIOR, *, freq=1, code=CODE):
    return {
        "ts_code": code,
        "freq": freq,
        "trade_date": day,
        "last_trade_time": f"{day} {TIMES[freq][-1]}",
        "macd_ema_fast": 10.0,
        "macd_ema_slow": 10.0,
        "macd_dea": 0.0,
        "kdj_k": 60.0,
        "kdj_d": 40.0,
        "params_key": "macd_12_26_9__kdj_9_3_3",
        "indicator_version": 1,
    }


def seed(root, *, freq=1, day=PRIOR, rows=None):
    path = gold_stk_mins_qfq_macd_kdj_state_path(root, freq, day)
    write_rows(
        path,
        GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA,
        rows if rows is not None else [state(day, freq=freq)],
    )
    return path


def source(root, rows, *, freq=1, code=CODE, year=2026):
    path = gold_stk_mins_qfq_path(root, freq, code, str(year))
    write_rows(path, GOLD_STK_MINS_QFQ_SCHEMA, rows)
    return path


def records(path, order="ts_code, trade_date"):
    with duckdb.connect(":memory:") as connection:
        result = connection.execute(
            f"SELECT * FROM {read_parquet(path, hive_partitioning=False)} ORDER BY {order}"
        )
        columns = [item[0] for item in result.description]
        return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]


def daily(root, *, freq=1, day=DAY, previous=PRIOR, initial=False, operation="daily"):
    return module.write_gold_stk_mins_qfq_macd_kdj_asset_partition(
        lake_root=root,
        freq=freq,
        partition_key=day,
        previous_expected_trade_date=previous,
        allow_without_previous_state=initial,
        publication_id=operation,
    )


def assert_values(row, expected):
    for field, value in zip(VALUE_FIELDS, expected, strict=True):
        assert row[field] == pytest.approx(value, rel=1e-12, abs=1e-10), field


def historical_rows(*, freq=1, count=8, end=PRIOR, code=CODE):
    end_day = date.fromisoformat(end)
    return [
        qfq((end_day - timedelta(days=count - i - 1)).isoformat(), freq=freq, code=code)
        for i in range(count)
    ]


@pytest.mark.parametrize("freq", FREQUENCIES)
def test_daily_keeps_literal_noninitial_state_and_original_formula(
    tmp_path,
    isolated_connections,
    freq,
):
    root = tmp_path / "lake"
    previous = seed(root, freq=freq)
    previous_identity = (
        previous.stat().st_ino,
        previous.stat().st_mtime_ns,
        previous.read_bytes(),
    )
    source(
        root,
        [
            *historical_rows(freq=freq),
            qfq(DAY, freq=freq, close=13, high=14, low=12),
            qfq(DAY, freq=freq, time=TIMES[freq][1], close=13, high=14, low=12),
        ],
        freq=freq,
    )

    result = daily(root, freq=freq)
    indicator = records(
        gold_stk_mins_qfq_macd_kdj_path(root, freq, CODE, "2026"), "trade_time"
    )
    assert result.indicator_row_count == 2
    assert result.initialized_without_previous_state is False
    # First EMA=136/13 and 92/9; DIF=28/117, DEA=28/585.
    # RSV=80; K=(2*60+80)/3; D=(2*40+K)/3.
    assert_values(
        indicator[0], (28 / 117, 28 / 585, 224 / 585, 200 / 3, 440 / 9, 920 / 9)
    )
    assert_values(
        indicator[1],
        (
            1834 / 169 - 2534 / 243,
            (4 / 5) * (28 / 585) + (1 / 5) * (1834 / 169 - 2534 / 243),
            (8 / 5) * (1834 / 169 - 2534 / 243 - 28 / 585),
            640 / 9,
            1520 / 27,
            2720 / 27,
        ),
    )
    final_state = records(gold_stk_mins_qfq_macd_kdj_state_path(root, freq, DAY))[0]
    assert final_state["macd_ema_fast"] == pytest.approx(1834 / 169, abs=1e-10)
    assert final_state["macd_ema_slow"] == pytest.approx(2534 / 243, abs=1e-10)
    assert final_state["kdj_k"] == pytest.approx(640 / 9, abs=1e-10)
    assert final_state["kdj_d"] == pytest.approx(1520 / 27, abs=1e-10)
    assert previous_identity == (
        previous.stat().st_ino,
        previous.stat().st_mtime_ns,
        previous.read_bytes(),
    )
    assert not any("macd_kdj_source_all_rows" in sql for sql in isolated_connections)


@pytest.mark.parametrize(
    "current_count,previous_count", [(0, 8), (3, 10), (1, 1), (1, 0), (0, 0)]
)
def test_cross_year_and_partial_windows_match_original_without_extra_years(
    tmp_path,
    isolated_connections,
    current_count,
    previous_count,
):
    root, reference = tmp_path / "lake", tmp_path / "reference"
    day, prior = "2026-01-08", "2026-01-07"
    current = historical_rows(count=current_count, end=prior) if current_count else []
    previous_rows = historical_rows(count=previous_count, end="2025-12-31")
    source(root, [*current, qfq(day, close=13, high=14, low=12)])
    if previous_rows:
        source(root, previous_rows, year=2025)
    # A valid but out-of-scope year with extreme prices must never be selected.
    excluded = source(root, [qfq("2024-12-31", high=1000, low=0.5)], year=2024)
    previous = seed(root, day=prior)
    paths = module.discover_gold_stk_mins_qfq_source_year_paths(
        root,
        freq=1,
        trade_dates=[day],
    )
    module.write_gold_stk_mins_qfq_macd_kdj_rows(
        lake_root=reference,
        freq=1,
        source_qfq_paths=paths,
        target_trade_dates=[day],
        previous_state_paths=[previous],
        publication_id="original",
    )
    isolated_connections.clear()
    daily(root, day=day, previous=prior)
    actual = records(gold_stk_mins_qfq_macd_kdj_path(root, 1, CODE, "2026"))[0]
    old = records(gold_stk_mins_qfq_macd_kdj_path(reference, 1, CODE, "2026"))[0]
    kdj = (
        (200 / 3, 440 / 9, 920 / 9)
        if current_count + previous_count
        else (170 / 3, 410 / 9, 710 / 9)
    )
    assert_values(actual, (28 / 117, 28 / 585, 224 / 585, *kdj))
    assert actual.keys() == old.keys()
    for field in actual:
        if isinstance(actual[field], float):
            assert actual[field] == pytest.approx(old[field], rel=1e-12, abs=1e-10)
        else:
            assert actual[field] == old[field]
    assert not any(str(excluded) in sql for sql in isolated_connections)


def test_current_year_eight_bars_skip_previous_year_and_ninth_extreme(
    tmp_path,
    isolated_connections,
):
    root = tmp_path / "lake"
    seed(root)
    ninth = qfq("2026-01-02", high=1000, low=0.5)
    source(root, [ninth, *historical_rows(), qfq(DAY, close=13, high=14, low=12)])
    unused = source(root, [qfq("2025-12-31", high=2000, low=0.25)], year=2025)
    daily(root)
    actual = records(gold_stk_mins_qfq_macd_kdj_path(root, 1, CODE, "2026"))[0]
    assert_values(actual, (28 / 117, 28 / 585, 224 / 585, 200 / 3, 440 / 9, 920 / 9))
    assert not any(str(unused) in sql for sql in isolated_connections)


def test_suspension_uses_actual_bars_not_a_fixed_date_window(
    tmp_path, isolated_connections
):
    root = tmp_path / "lake"
    previous = state()
    previous["last_trade_time"] = "2026-02-02 09:30:00"
    seed(root, rows=[previous])
    source(
        root, [*historical_rows(end="2026-02-02"), qfq(DAY, close=13, high=14, low=12)]
    )
    daily(root)
    actual = records(gold_stk_mins_qfq_macd_kdj_path(root, 1, CODE, "2026"))[0]
    assert_values(actual, (28 / 117, 28 / 585, 224 / 585, 200 / 3, 440 / 9, 920 / 9))


@pytest.mark.parametrize("count", range(1, 8))
def test_partial_history_keeps_existing_window_without_new_rejection(
    tmp_path,
    isolated_connections,
    count,
):
    root = tmp_path / "lake"
    seed(root)
    source(root, [*historical_rows(count=count), qfq(DAY, close=13, high=14, low=12)])
    daily(root)
    actual = records(gold_stk_mins_qfq_macd_kdj_path(root, 1, CODE, "2026"))[0]
    assert_values(actual, (28 / 117, 28 / 585, 224 / 585, 200 / 3, 440 / 9, 920 / 9))


def test_window_operates_only_on_target_rows_and_top_eight_history(
    tmp_path,
    isolated_connections,
    monkeypatch,
):
    root = tmp_path / "lake"
    seed(root)
    path = source(
        root,
        [
            *historical_rows(count=20),
            qfq(DAY, close=13, high=14, low=12),
        ],
    )
    inspected = []
    original = module._populate_macd_kdj_indicator_work_rows

    def populate(connection, **kwargs):
        prefix = connection.execute(
            "SELECT count(*) FROM macd_kdj_daily_prior_rows"
        ).fetchone()[0]
        target = connection.execute(
            "SELECT count(*) FROM macd_kdj_calculation_rows"
        ).fetchone()[0]
        assert (prefix, target) == (8, 1)
        assert (
            connection.execute(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_name='macd_kdj_source_all_rows'"
            ).fetchone()[0]
            == 0
        )
        plan = connection.execute(
            "EXPLAIN "
            + module._daily_macd_kdj_prior_bars_sql(
                [path],
                freq=1,
                trade_date=DAY,
            )
        ).fetchall()
        text = " ".join(str(value) for row in plan for value in row)
        assert "arg_max" in text
        assert "GROUP_BY" in text
        assert "WINDOW" not in text
        inspected.append((prefix, target))
        return original(connection, **kwargs)

    monkeypatch.setattr(module, "_populate_macd_kdj_indicator_work_rows", populate)
    daily(root)
    assert inspected == [(8, 1)]


@pytest.mark.parametrize("count", [1, 64, 65])
def test_all_stock_batches_are_kept_and_do_not_share_seeds(
    tmp_path,
    isolated_connections,
    monkeypatch,
    count,
):
    root = tmp_path / "lake"
    codes = tuple(f"{i:06d}.SZ" for i in range(1, count + 1))
    dormant = "999999.SZ"
    seed(root, rows=[*(state(code=code) for code in codes), state(code=dormant)])
    for code in codes:
        source(root, [qfq(DAY, code=code, close=13, high=14, low=12)], code=code)
    seen = []
    original = module._populate_macd_kdj_indicator_work_rows

    def populate(connection, **kwargs):
        seen.append(
            tuple(
                row[0]
                for row in connection.execute(
                    "SELECT DISTINCT ts_code FROM macd_kdj_calculation_rows ORDER BY ts_code"
                ).fetchall()
            )
        )
        return original(connection, **kwargs)

    monkeypatch.setattr(module, "_populate_macd_kdj_indicator_work_rows", populate)
    result = daily(root)
    assert tuple(code for batch in seen for code in batch) == codes
    assert all(len(batch) <= module.MACD_KDJ_DAILY_STOCK_BATCH_SIZE for batch in seen)
    assert len(seen) == (count + 63) // 64
    assert result.indicator_row_count == count
    final_state = records(gold_stk_mins_qfq_macd_kdj_state_path(root, 1, DAY))
    assert {row["ts_code"] for row in final_state} == {*codes, dormant}
    for row in final_state:
        if row["ts_code"] == dormant:
            assert row["kdj_k"] == 60
            assert row["last_trade_time"].date() == date.fromisoformat(PRIOR)
        else:
            assert row["kdj_k"] == pytest.approx(170 / 3, abs=1e-10)
            assert row["kdj_d"] == pytest.approx(410 / 9, abs=1e-10)


def test_new_stock_keeps_original_seed_and_dormant_stock_keeps_state(
    tmp_path,
    isolated_connections,
):
    root = tmp_path / "lake"
    seed(root, rows=[state(code=OTHER)])
    source(root, [qfq(DAY, close=13, high=14, low=12)])
    result = daily(root)
    assert result.initialized_without_previous_state is False
    actual = records(gold_stk_mins_qfq_macd_kdj_path(root, 1, CODE, "2026"))[0]
    assert_values(actual, (0, 0, 0, 50, 50, 50))
    states = {
        row["ts_code"]: row
        for row in records(gold_stk_mins_qfq_macd_kdj_state_path(root, 1, DAY))
    }
    assert set(states) == {CODE, OTHER}
    assert states[OTHER]["kdj_k"] == 60
    assert states[OTHER]["last_trade_time"].date() == date.fromisoformat(PRIOR)


def test_existing_stock_missing_own_state_fails_before_publication(
    tmp_path,
    isolated_connections,
):
    root = tmp_path / "lake"
    seed(root, rows=[state(code=OTHER)])
    source(root, [*historical_rows(), qfq(DAY, close=13, high=14, low=12)])
    with pytest.raises(RuntimeError, match="previous state is missing"):
        daily(root)
    assert not gold_stk_mins_qfq_macd_kdj_state_path(root, 1, DAY).exists()
    assert not gold_stk_mins_qfq_macd_kdj_path(root, 1, CODE, "2026").exists()


def test_exact_previous_state_does_not_fall_back_to_older_file(
    tmp_path,
    isolated_connections,
):
    root = tmp_path / "lake"
    seed(root, day="2026-10-27")
    source(root, [qfq(DAY, close=13, high=14, low=12)])
    # Existing assert_exact_previous_state_path rejects with Dagster Failure.
    with pytest.raises(dg.Failure, match="previous expected state is missing"):
        daily(root)
    assert not gold_stk_mins_qfq_macd_kdj_state_path(root, 1, DAY).exists()


def test_calendar_first_day_preserves_initialization(tmp_path, isolated_connections):
    root = tmp_path / "lake"
    source(root, [qfq(DAY, close=13, high=14, low=12)])
    result = daily(root, previous=None, initial=True)
    assert result.initialized_without_previous_state is True
    actual = records(gold_stk_mins_qfq_macd_kdj_path(root, 1, CODE, "2026"))[0]
    assert_values(actual, (0, 0, 0, 50, 50, 50))


def test_no_target_rows_keeps_original_empty_result_failure(
    tmp_path, isolated_connections
):
    root = tmp_path / "lake"
    seed(root)
    source(root, historical_rows())
    with pytest.raises(RuntimeError, match="no indicator"):
        daily(root)
    assert not gold_stk_mins_qfq_macd_kdj_state_path(root, 1, DAY).exists()


def test_new_state_continues_next_day_without_rebuilding_old_state(
    tmp_path,
    isolated_connections,
):
    root, reference = tmp_path / "lake", tmp_path / "reference"
    previous = seed(root)
    identity = (
        previous.stat().st_ino,
        previous.stat().st_mtime_ns,
        previous.read_bytes(),
    )
    source_path = source(
        root,
        [
            *historical_rows(),
            qfq(DAY, close=13, high=14, low=12),
            qfq(NEXT, close=13, high=14, low=12),
        ],
    )
    daily(root)
    produced = gold_stk_mins_qfq_macd_kdj_state_path(root, 1, DAY)
    snapshot = (
        produced.stat().st_ino,
        produced.stat().st_mtime_ns,
        produced.read_bytes(),
    )
    daily(root, day=NEXT, previous=DAY, operation="next")
    module.write_gold_stk_mins_qfq_macd_kdj_rows(
        lake_root=reference,
        freq=1,
        source_qfq_paths=[source_path],
        target_trade_dates=[DAY, NEXT],
        previous_state_paths=[previous],
        publication_id="original-two-days",
    )
    actual = records(
        gold_stk_mins_qfq_macd_kdj_path(root, 1, CODE, "2026"), "trade_time"
    )
    old = records(
        gold_stk_mins_qfq_macd_kdj_path(reference, 1, CODE, "2026"), "trade_time"
    )
    assert [row["trade_date"] for row in actual] == [
        date.fromisoformat(DAY),
        date.fromisoformat(NEXT),
    ]
    assert_values(
        actual[1],
        (
            1834 / 169 - 2534 / 243,
            (4 / 5) * (28 / 585) + (1 / 5) * (1834 / 169 - 2534 / 243),
            (8 / 5) * (1834 / 169 - 2534 / 243 - 28 / 585),
            640 / 9,
            1520 / 27,
            2720 / 27,
        ),
    )
    for actual_row, old_row in zip(actual, old, strict=True):
        for field in actual_row:
            if isinstance(actual_row[field], float):
                assert actual_row[field] == pytest.approx(
                    old_row[field], rel=1e-12, abs=1e-10
                )
            else:
                assert actual_row[field] == old_row[field]
    assert identity == (
        previous.stat().st_ino,
        previous.stat().st_mtime_ns,
        previous.read_bytes(),
    )
    assert snapshot == (
        produced.stat().st_ino,
        produced.stat().st_mtime_ns,
        produced.read_bytes(),
    )
    assert isinstance(actual[0]["trade_time"], datetime)


@pytest.mark.parametrize(
    "violation", ["ts_code", "trade_date", "trade_time", "duplicate"]
)
def test_existing_qfq_producer_rejects_invalid_keys_not_new_daily_guard(
    tmp_path,
    isolated_connections,
    violation,
):
    # Deliberate invalid producer inputs. This verifies the existing upstream
    # validation boundary, not a claim that MACD rejects every NULL/missing field.
    row = qfq(DAY)
    if violation != "duplicate":
        row[violation] = None
    rows = [row, row] if violation == "duplicate" else [row]
    path = source(tmp_path / "lake", rows)
    with duckdb.connect(":memory:") as connection:
        connection.execute(
            "CREATE TABLE qfq_replacement_rows AS SELECT * FROM "
            + read_parquet(path, hive_partitioning=False)
        )
        message = (
            "duplicate ts_code" if violation == "duplicate" else "null business keys"
        )
        with pytest.raises(ValueError, match=message):
            qfq_module._validate_replacement_rows(
                connection,
                normalized_freq=1,
                allowed_dates_sql=f"DATE '{DAY}'",
            )
