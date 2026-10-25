"""Real isolated Parquet readers, literal counts and preservation expectations.

Inputs follow SILVER_STK_MINS_SCHEMA/SILVER_ADJ_FACTOR_SCHEMA. Session times
and expected seven-frequency counts are the independently retained formula
golden table; expected values are not produced by the implementation.
Only the connection's temp-directory setting is redirected; policy validation,
SQL, COPY, candidate validation and publication all execute normally.
"""

from contextlib import contextmanager
from dataclasses import replace
from datetime import date

import duckdb
import pytest

from orchestrator.defs import stk_mins_qfq as core
from orchestrator.defs.assets import stk_mins as assets
from orchestrator.defs.duckdb_connection import (
    DEFAULT_DUCKDB_CONNECTION_SETTINGS,
    connect_configured_duckdb,
)
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.io.stk_mins_qfq_publication import StkMinsQfqPublication
from orchestrator.defs.paths import (
    gold_stk_mins_qfq_path,
    silver_adj_factor_path,
    silver_stk_mins_path,
)
from orchestrator.defs.resources import DuckDBResource

DAY = "2026-10-22"
CODE = "600000.SH"


class RecordingConnection:
    def __init__(self, connection, queries):
        self.connection = connection
        self.queries = queries

    def execute(self, sql, *args, **kwargs):
        self.queries.append(str(sql))
        return self.connection.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self.connection, name)


@pytest.fixture
def isolated_connections(tmp_path, monkeypatch):
    directory = tmp_path.resolve() / "duckdb"
    directory.mkdir()
    settings = replace(DEFAULT_DUCKDB_CONNECTION_SETTINGS, temp_directory=directory)
    queries, policies = [], []

    @contextmanager
    def connect(*, temp_policy="managed"):
        policies.append(temp_policy)
        with connect_configured_duckdb(settings, temp_policy=temp_policy) as connection:
            yield RecordingConnection(connection, queries)

    monkeypatch.setattr(core, "connect_configured_duckdb", connect)
    monkeypatch.setattr(assets, "connect_configured_duckdb", connect)
    return queries, policies, directory


def _source(root, freq):
    path = silver_stk_mins_path(root, freq, DAY)
    path.parent.mkdir(parents=True, exist_ok=True)
    if freq == 1:
        minutes = [*range(570, 691), *range(781, 901)]
    else:
        minutes = [570, *range(570 + freq, 691, freq), *range(780 + freq, 901, freq)]
    with duckdb.connect() as connection:
        connection.execute("CREATE TABLE times (minute INTEGER)")
        connection.executemany("INSERT INTO times VALUES (?)", [(m,) for m in minutes])
        connection.execute(copy_query_to_parquet(f"""
            SELECT '{CODE}'::VARCHAR AS ts_code, {freq}::INTEGER AS freq,
              DATE '{DAY}' AS trade_date,
              TIMESTAMP '{DAY} 00:00:00' + minute * INTERVAL '1 minute' AS trade_time,
              10.0::DOUBLE AS open, 11.0::DOUBLE AS high,
              9.0::DOUBLE AS low, 10.0::DOUBLE AS close,
              100.0::DOUBLE AS vol, 1000.0::DOUBLE AS amount,
              'SSE'::VARCHAR AS exchange FROM times
        """, path))
    factor = silver_adj_factor_path(root, DAY)
    factor.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as connection:
        connection.execute(copy_query_to_parquet(f"""
            SELECT '{CODE}'::VARCHAR AS ts_code, DATE '{DAY}' AS trade_date,
              2.0::DOUBLE AS adj_factor
        """, factor))
    return path, factor


def _rewrite(path, sql):
    temporary = path.with_suffix(".replacement.parquet")
    with duckdb.connect() as connection:
        connection.execute(copy_query_to_parquet(sql, temporary))
    temporary.replace(path)


def _literal_gold(*, day="2026-10-21", code=CODE, freq=5, price=8):
    return f"""SELECT '{code}'::VARCHAR AS ts_code, {freq}::INTEGER AS freq,
      DATE '{day}' AS trade_date, TIMESTAMP '{day} 09:35:00' AS trade_time,
      {price}::DOUBLE AS open, {price + 1}::DOUBLE AS high,
      {price - 1}::DOUBLE AS low, {price}::DOUBLE AS close,
      1.0::DOUBLE AS vol, 10.0::DOUBLE AS amount, 'SSE'::VARCHAR AS exchange"""


@pytest.mark.parametrize("freq,source_freq,count,first,volume", [
    (1, 1, 241, "09:30:00", 24100), (5, 1, 48, "09:35:00", 24100),
    (15, 5, 16, "09:45:00", 4900), (30, 5, 8, "10:00:00", 4900),
    (60, 30, 4, "10:30:00", 900), (90, 30, 3, "11:00:00", 900),
    (120, 60, 2, "11:30:00", 500),
])
def test_daily_one_source_one_factor_and_one_replacement(
    tmp_path, isolated_connections, freq, source_freq, count, first, volume,
):
    root = tmp_path / "lake"
    source, factor = _source(root, source_freq)
    queries, policies, directory = isolated_connections
    writer = (assets.write_gold_stk_mins_qfq_derived_asset_partition if freq >= 90
              else assets.write_gold_stk_mins_qfq_asset_partition)
    result = writer(lake_root=root, duckdb=DuckDBResource(), freq=freq, partition_key=DAY)
    readers = [q for q in queries if "read_parquet(" in q.lower()]
    assert sum(str(source) in q for q in readers) == 1
    assert sum(str(factor) in q for q in readers) == 1
    assert sum("CREATE TEMP TABLE qfq_replacement_rows AS" in q for q in queries) == 1
    assert policies == ["existing_no_spill"]
    assert not tuple(directory.iterdir())
    assert result.replacement_row_count == count
    path = gold_stk_mins_qfq_path(root, freq, CODE, 2026)
    with duckdb.connect() as connection:
        actual = connection.execute(f"""
            SELECT count(*), min(strftime(trade_time, '%H:%M:%S')),
              sum(vol), min(open), max(high), min(low), max(close)
            FROM {read_parquet(path, hive_partitioning=False)}
        """).fetchone()
    assert actual == (count, first, volume, 10, 11, 9, 10)


def test_old_year_and_actual_candidate_each_read_once(tmp_path, isolated_connections):
    root = tmp_path / "lake"
    target = gold_stk_mins_qfq_path(root, 5, CODE, 2026)
    target.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as connection:
        connection.execute(copy_query_to_parquet(_literal_gold(), target))
    queries, _, _ = isolated_connections
    result = core.write_gold_stk_mins_qfq_rows_to_year_files(
        lake_root=root, freq=5, qfq_select_sql=_literal_gold(day=DAY, price=10),
        replace_trade_dates=[DAY],
    )
    readers = [q for q in queries if "read_parquet(" in q.lower()]
    assert len(readers) == 2
    assert sum(str(target) in q for q in readers) == 1
    assert "SELECT freq, ts_code, trade_date, trade_time" in readers[1]
    assert result[0].row_count == 2
    with duckdb.connect() as connection:
        assert connection.execute(f"SELECT trade_date, close FROM {read_parquet(target, hive_partitioning=False)} ORDER BY trade_date").fetchall() == [
            (date(2026, 10, 21), 8), (date(2026, 10, 22), 10),
        ]


@pytest.mark.parametrize("field,value", [("ts_code", "'000001.SZ'"), ("freq", "30"),
                                          ("trade_date", "DATE '2025-10-22'")])
def test_replaced_old_day_path_errors_are_not_hidden(
    tmp_path, isolated_connections, field, value,
):
    root = tmp_path / "lake"
    target = gold_stk_mins_qfq_path(root, 5, CODE, 2026)
    target.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as connection:
        connection.execute(copy_query_to_parquet(
            f"SELECT * REPLACE ({value} AS {field}) FROM ({_literal_gold(day=DAY)})", target,
        ))
    before = target.read_bytes()
    with pytest.raises(ValueError, match="Existing gold qfq year file"):
        core.write_gold_stk_mins_qfq_rows_to_year_files(
            lake_root=root, freq=5, qfq_select_sql=_literal_gold(day=DAY),
            replace_trade_dates=[DAY],
        )
    assert target.read_bytes() == before


def test_candidate_duplicate_outside_replacement_day_still_rejected(
    tmp_path, isolated_connections,
):
    root = tmp_path / "lake"
    target = gold_stk_mins_qfq_path(root, 5, CODE, 2026)
    target.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as connection:
        connection.execute(copy_query_to_parquet(
            f"{_literal_gold()} UNION ALL {_literal_gold()}", target,
        ))
    before = target.read_bytes()
    with pytest.raises(ValueError, match="Written gold qfq year file contains duplicate"):
        core.write_gold_stk_mins_qfq_rows_to_year_files(
            lake_root=root, freq=5, qfq_select_sql=_literal_gold(day=DAY),
            replace_trade_dates=[DAY],
        )
    assert target.read_bytes() == before


@pytest.mark.parametrize("damage,expected", [
    ("date", "out_of_partition"), ("frequency", "invalid_frequency"),
    ("null", "invalid_value"), ("duplicate", "duplicate_key"),
    ("exchange", "mixed_exchange"), ("factor", "windows are incomplete"),
])
def test_source_and_factor_errors_are_not_filtered_away(
    tmp_path, isolated_connections, damage, expected,
):
    root = tmp_path / "lake"
    source, factor = _source(root, 1)
    relation = read_parquet(source, hive_partitioning=False)
    if damage == "date":
        # Let the original coverage-first gate pass so the whole-source date
        # diagnostic is actually exercised, rather than failing on missing factor.
        factor_source = read_parquet(factor, hive_partitioning=False)
        _rewrite(factor, f"SELECT * FROM {factor_source} UNION ALL SELECT * REPLACE (DATE '2026-10-21' AS trade_date) FROM {factor_source}")
    if damage == "factor":
        _rewrite(factor, f"SELECT * FROM {read_parquet(factor, hive_partitioning=False)} UNION ALL SELECT * FROM {read_parquet(factor, hive_partitioning=False)}")
    elif damage == "duplicate":
        _rewrite(source, f"SELECT * FROM {relation} UNION ALL SELECT * FROM {relation} LIMIT 242")
    else:
        changed = {"date": "DATE '2026-10-21' AS trade_date", "frequency": "5 AS freq",
                   "null": "NULL::DOUBLE AS open",
                   "exchange": "CASE WHEN strftime(trade_time, '%H:%M') = '09:30' THEN 'SZSE' ELSE exchange END AS exchange"}[damage]
        _rewrite(source, f"SELECT * REPLACE ({changed}) FROM {relation}")
    with pytest.raises(RuntimeError, match=expected):
        assets.write_gold_stk_mins_qfq_asset_partition(
            lake_root=root, duckdb=DuckDBResource(), freq=5, partition_key=DAY,
        )
    assert not tuple((root / "gold").rglob("*.parquet"))


def test_no_spill_memory_failure_does_not_fallback(tmp_path):
    directory = tmp_path.resolve() / "duckdb"
    directory.mkdir()
    settings = replace(DEFAULT_DUCKDB_CONNECTION_SETTINGS,
                       temp_directory=directory, memory_limit="4MB", threads=1)
    with connect_configured_duckdb(settings, temp_policy="existing_no_spill") as connection:
        assert connection.execute("SELECT current_setting('max_temp_directory_size')").fetchone() == ("0 bytes",)
        with pytest.raises(duckdb.OutOfMemoryException):
            connection.execute("CREATE TEMP TABLE too_large AS SELECT i, md5(i::VARCHAR) AS payload FROM range(200000) t(i) ORDER BY hash(i)")
    assert not tuple(directory.iterdir())


def test_source_changed_after_loading_stops_before_publication(
    tmp_path, isolated_connections, monkeypatch,
):
    root = tmp_path / "lake"
    source, _ = _source(root, 1)
    original = assets._canonical_qfq_source_audit

    def change_source(**kwargs):
        result = original(**kwargs)
        _rewrite(source, f"SELECT * REPLACE (20.0::DOUBLE AS amount) FROM {read_parquet(source, hive_partitioning=False)}")
        return result

    monkeypatch.setattr(assets, "_canonical_qfq_source_audit", change_source)
    with pytest.raises(RuntimeError, match="inputs changed"):
        assets.write_gold_stk_mins_qfq_asset_partition(
            lake_root=root, duckdb=DuckDBResource(), freq=5, partition_key=DAY,
        )
    assert not tuple((root / "gold").rglob("*.parquet"))
    assert not (tmp_path / "lake_staging").exists()


def test_shared_writer_takes_lock_before_reading_replacement(tmp_path, isolated_connections):
    root = tmp_path / "lake"
    queries, policies, _ = isolated_connections
    with (
        StkMinsQfqPublication(lake_root=root, family="qfq", freq=5, trade_dates=(DAY,)),
        pytest.raises(BlockingIOError),
    ):
        core.write_gold_stk_mins_qfq_rows_to_year_files(
            lake_root=root, freq=5, replace_trade_dates=[DAY],
            qfq_select_sql="SELECT * FROM read_parquet('/does-not-exist.parquet')",
        )
    assert not queries
    assert not policies


@pytest.mark.parametrize("freq,dates", [(7, [DAY]), (5, ["bad-date"])])
def test_invalid_scope_is_rejected_before_any_sql(tmp_path, isolated_connections, freq, dates):
    queries, policies, _ = isolated_connections
    with pytest.raises(ValueError):
        core.write_gold_stk_mins_qfq_rows_to_year_files(
            lake_root=tmp_path / "lake", freq=freq, replace_trade_dates=dates,
            qfq_select_sql="SELECT * FROM read_parquet('/does-not-exist.parquet')",
        )
    assert not queries
    assert not policies


def test_existing_path_error_precedes_missing_price_column(tmp_path, isolated_connections):
    root = tmp_path / "lake"
    target = gold_stk_mins_qfq_path(root, 5, CODE, 2026)
    target.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as connection:
        connection.execute(copy_query_to_parquet(
            f"SELECT * EXCLUDE (close) FROM ({_literal_gold(freq=30)})", target,
        ))
    # Original writer checks freq/code/year before binding the merge's prices.
    with pytest.raises(ValueError, match="Existing gold qfq year file"):
        core.write_gold_stk_mins_qfq_rows_to_year_files(
            lake_root=root, freq=5, qfq_select_sql=_literal_gold(day=DAY),
            replace_trade_dates=[DAY],
        )


@pytest.mark.parametrize("old_day", [DAY, "2026-10-21"])
def test_old_price_cast_keeps_original_replacement_filter_order(
    tmp_path, isolated_connections, old_day,
):
    root = tmp_path / "lake"
    target = gold_stk_mins_qfq_path(root, 5, CODE, 2026)
    target.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as connection:
        connection.execute(copy_query_to_parquet(
            f"SELECT * REPLACE ('bad'::VARCHAR AS close) FROM ({_literal_gold(day=old_day)})",
            target,
        ))
    # Independent original SQL, retained from the pre-optimization year writer.
    # A real run of that source also rejects the replaced day's invalid close;
    # filtering must not be assumed to prevent its conversion in DuckDB.
    original_sql = f"""
      WITH replacement_group AS ({_literal_gold(day=DAY, price=10)}),
      existing_rows AS (
        SELECT CAST(ts_code AS VARCHAR) AS ts_code, CAST(freq AS INTEGER) AS freq,
          CAST(trade_date AS DATE) AS trade_date, CAST(trade_time AS TIMESTAMP) AS trade_time,
          CAST(open AS DOUBLE) AS open, CAST(high AS DOUBLE) AS high,
          CAST(low AS DOUBLE) AS low, CAST(close AS DOUBLE) AS close,
          CAST(vol AS DOUBLE) AS vol, CAST(amount AS DOUBLE) AS amount,
          CAST(exchange AS VARCHAR) AS exchange
        FROM {read_parquet(target, hive_partitioning=False)}
      ), merged_rows AS (
        SELECT * FROM existing_rows
        WHERE trade_date NOT IN (SELECT DISTINCT trade_date FROM replacement_group)
        UNION ALL SELECT * FROM replacement_group
      ) SELECT * FROM merged_rows ORDER BY trade_date, trade_time
    """
    with duckdb.connect() as connection, pytest.raises(duckdb.ConversionException):
        connection.execute(copy_query_to_parquet(original_sql, tmp_path / "original-candidate.parquet"))
    before = target.read_bytes()
    with pytest.raises(duckdb.ConversionException):
        core.write_gold_stk_mins_qfq_rows_to_year_files(
            lake_root=root, freq=5, qfq_select_sql=_literal_gold(day=DAY, price=10),
            replace_trade_dates=[DAY],
        )
    assert target.read_bytes() == before
