"""Retained source factors do not enlarge automatic repair calculations.

The inputs follow the three-column Silver factor schema and full lifecycle
schema. Retirement dates are independent literal business facts, including the
allowed D + NULL case from stock_lifecycle_checks.py.
"""

from pathlib import Path

import duckdb
import pytest

from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.paths import silver_adj_factor_path, silver_stock_lifecycle_path
from orchestrator.defs.stk_mins_qfq import (
    build_gold_stk_mins_qfq_factor_repair_check_metadata,
    build_gold_stk_mins_qfq_factor_repair_plan,
)
from orchestrator.defs.stock_daily_qfq import (
    build_gold_stock_daily_qfq_factor_repair_plan,
    execute_gold_stock_daily_qfq_factor_repair,
    gold_stock_daily_qfq_factor_repair_codes_hash,
)
from tests.factor_repair_fixtures import (
    isolated_factor_repair_connections as isolated_factor_repair_connections,
)
from tests.factor_repair_fixtures import write_repair_lifecycle

pytestmark = pytest.mark.usefixtures("isolated_factor_repair_connections")

DAY = "2026-10-28"
PREVIOUS = "2026-10-27"


def _factor(path: Path, day: str, rows: list[tuple[str, float]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(":memory:") as con:
        con.execute("CREATE TABLE factors(ts_code VARCHAR,trade_date DATE,adj_factor DOUBLE)")
        if rows:
            con.executemany("INSERT INTO factors VALUES (?,?::DATE,?)", [(code, day, value) for code, value in rows])
        con.execute(copy_query_to_parquet("SELECT * FROM factors ORDER BY ts_code", path))
    return path


def _inputs(root, *, current, previous, lifecycle, day=DAY, previous_day=PREVIOUS):
    current_path = _factor(root / "current.parquet", day, current)
    previous_path = _factor(root / "previous.parquet", previous_day, previous)
    lifecycle_path = write_repair_lifecycle(root / "lifecycle.parquet", lifecycle)
    # The historical/basic input remains frozen by the executor; lifecycle is
    # explicitly authoritative for historical listing dates and retired codes.
    basic_path = root / "basic.parquet"
    with duckdb.connect(":memory:") as con:
        con.execute(copy_query_to_parquet("SELECT '000001.SZ'::VARCHAR ts_code, DATE '2000-01-01' list_date", basic_path))
    return current_path, previous_path, basic_path, lifecycle_path


def _minute(paths, *, day=DAY, previous=PREVIOUS):
    current_path, previous_path, basic_path, lifecycle_path = paths
    return build_gold_stk_mins_qfq_factor_repair_plan(
        current_adj_factor_path=current_path,
        previous_adj_factor_path=previous_path,
        silver_stock_basic_path=basic_path,
        silver_stock_lifecycle_path=lifecycle_path,
        trade_date=day, previous_trade_date=previous,
    )


def test_retained_retired_and_unresolved_records_do_not_block_active_repair(tmp_path):
    paths = _inputs(tmp_path,
        current=[("000001.SZ", 2.0), ("600001.SH", 9.0), ("301139.SZ", 1.1319), ("600002.SH", 4.0)],
        previous=[("000001.SZ", 1.0), ("301139.SZ", 1.0079)],
        lifecycle=[
            {"ts_code": "000001.SZ"},
            {"ts_code": "600001.SH", "list_status": "D", "delist_date": "2020-01-01"},
            {"ts_code": "301139.SZ", "list_status": "D", "list_date": "2022-07-08", "delist_date": DAY},
            {"ts_code": "600002.SH", "list_status": "D", "delist_date": None},
        ])
    plan = _minute(paths)
    assert plan.can_execute_repair
    assert plan.reason == "factor_changed"
    assert plan.repair_required_codes == ("000001.SZ",)
    assert plan.missing_previous_factor_code_count == 0
    assert plan.detected_change_code_count == 1
    assert plan.unresolved_delisted_code_count == 1
    assert plan.unresolved_delisted_code_samples == ("600002.SH",)
    metadata = build_gold_stk_mins_qfq_factor_repair_check_metadata(plan, producer_run_id="isolated-scope")
    assert metadata["goldenshare/repair_required_codes"] == ["000001.SZ"]
    assert metadata["goldenshare/unresolved_delisted_code_samples"] == ["600002.SH"]


def test_active_missing_previous_factor_remains_a_blocker(tmp_path):
    paths = _inputs(tmp_path,
        current=[("000001.SZ", 2.0), ("600001.SH", 9.0)], previous=[],
        lifecycle=[{"ts_code": "000001.SZ"},
                   {"ts_code": "600001.SH", "list_status": "D", "delist_date": "2020-01-01"}])
    plan = _minute(paths)
    assert not plan.can_execute_repair
    assert plan.reason == "missing_previous_factor"
    assert plan.missing_previous_factor_code_samples == ("000001.SZ",)


def test_currently_retired_stock_participates_for_its_valid_historical_day(tmp_path):
    paths = _inputs(tmp_path,
        current=[("301139.SZ", 2.0)], previous=[("301139.SZ", 1.0)],
        lifecycle=[{"ts_code": "301139.SZ", "list_status": "D",
                    "list_date": "2022-07-08", "delist_date": DAY}],
        day="2026-10-27", previous_day="2026-10-26")
    plan = _minute(paths, day="2026-10-27", previous="2026-10-26")
    assert plan.can_execute_repair
    assert plan.repair_required_codes == ("301139.SZ",)


def test_unresolved_retirement_is_not_reported_as_no_change(tmp_path):
    paths = _inputs(tmp_path, current=[("600002.SH", 4.0)], previous=[],
                    lifecycle=[{"ts_code": "600002.SH", "list_status": "D", "delist_date": None}])
    plan = _minute(paths)
    assert plan.can_execute_repair
    assert not plan.repair_required
    assert plan.reason == "unresolved_delist_date"
    assert plan.unresolved_delisted_code_count == 1
    with duckdb.connect(":memory:") as con:
        daily = build_gold_stock_daily_qfq_factor_repair_plan(
            connection=con, current_adj_factor_path=paths[0], previous_adj_factor_path=paths[1],
            silver_stock_lifecycle_path=paths[3], qfq_factor_trade_date=DAY, previous_trade_date=PREVIOUS)
    assert daily.reason == "unresolved_delist_date"
    assert daily.repair_required_codes == ()
    assert daily.unresolved_delisted_code_samples == ("600002.SH",)


def test_daily_repair_uses_same_valid_day_scope(tmp_path):
    paths = _inputs(tmp_path,
        current=[("000001.SZ", 2.0), ("301139.SZ", 1.1319), ("600002.SH", 4.0)],
        previous=[("000001.SZ", 1.0), ("301139.SZ", 1.0079), ("600002.SH", 1.0)],
        lifecycle=[{"ts_code": "000001.SZ"},
                   {"ts_code": "301139.SZ", "list_status": "D", "delist_date": DAY},
                   {"ts_code": "600002.SH", "list_status": "D", "delist_date": None}])
    with duckdb.connect(":memory:") as con:
        plan = build_gold_stock_daily_qfq_factor_repair_plan(
            connection=con, current_adj_factor_path=paths[0], previous_adj_factor_path=paths[1],
            silver_stock_lifecycle_path=paths[3], qfq_factor_trade_date=DAY, previous_trade_date=PREVIOUS)
    assert plan.repair_required_codes == ("000001.SZ",)
    assert plan.unresolved_delisted_code_samples == ("600002.SH",)


def test_explicit_hash_cannot_force_unresolved_stock_into_daily_repair(tmp_path):
    _factor(silver_adj_factor_path(tmp_path, DAY), DAY, [("600002.SH", 4.0)])
    _factor(silver_adj_factor_path(tmp_path, PREVIOUS), PREVIOUS, [("600002.SH", 1.0)])
    write_repair_lifecycle(silver_stock_lifecycle_path(tmp_path), [
        {"ts_code": "600002.SH", "list_status": "D", "delist_date": None},
    ])
    # An operator-provided hash naming this stock cannot override the planner.
    # The actual executor must reject before it reads any historical prices.
    with duckdb.connect(":memory:") as con, pytest.raises(ValueError, match="hash does not match"):
        execute_gold_stock_daily_qfq_factor_repair(
            connection=con, lake_root=tmp_path, qfq_factor_trade_date=DAY,
            expected_trade_dates=(PREVIOUS, DAY),
            repair_required_codes_hash=gold_stock_daily_qfq_factor_repair_codes_hash(("600002.SH",)),
            upstream_batch_id="isolated-explicit-unresolved",
        )
    assert not (tmp_path / "gold").exists()


def test_minute_repair_freezes_lifecycle_before_historical_work(tmp_path, monkeypatch):
    import os

    from orchestrator.defs import stk_mins_qfq_factor_repair as repair
    from tests.test_stk_mins_qfq_factor_repair_read_reuse import _execute, _inputs

    _inputs(tmp_path)
    original = repair.build_gold_stk_mins_qfq_factor_repair_plan

    def changed_lifecycle(**kwargs):
        result = original(**kwargs)
        path = kwargs["silver_stock_lifecycle_path"]
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
        return result

    monkeypatch.setattr(repair, "build_gold_stk_mins_qfq_factor_repair_plan", changed_lifecycle)
    with pytest.raises(RuntimeError, match="inputs changed"):
        _execute(tmp_path)


def test_configured_connections_use_only_test_owned_temp(isolated_factor_repair_connections):
    from orchestrator.defs import resources, stk_mins_qfq
    from orchestrator.defs import stk_mins_qfq_factor_repair as repair

    expected = str(isolated_factor_repair_connections)
    for factory in (stk_mins_qfq.connect_configured_duckdb,
                    repair.connect_configured_duckdb,
                    resources.DuckDBResource().connect):
        with factory() as connection:
            directory = connection.execute("SELECT current_setting('temp_directory')").fetchone()[0]
            assert directory == expected
            assert not directory.startswith("/Volumes/")
