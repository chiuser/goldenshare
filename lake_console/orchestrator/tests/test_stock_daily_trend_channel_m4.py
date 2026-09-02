import inspect
import os
from contextlib import nullcontext
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import dagster as dg
import duckdb
import pytest

from orchestrator.definitions import defs as project_defs
from orchestrator.defs import stock_daily_trend_channel as trend_channel
from orchestrator.defs.asset_guards import (
    stock_daily_trend_channel_lake_readiness as readiness_module,
)
from orchestrator.defs.asset_guards.bounded_continuity import (
    ContinuityDateReadiness,
    ContinuityExpectedDateWindow,
)
from orchestrator.defs.asset_guards.stock_daily_qfq_factor_repair import (
    GoldStockDailyQfqFactorRepairStatus,
)
from orchestrator.defs.asset_guards.stock_daily_trend_channel_lake_readiness import (
    StockDailyTrendChannelBatchReadiness,
    batch_gold_stock_daily_trend_channel_readiness,
)
from orchestrator.defs.assets import stock_daily_trend_channel as asset_module
from orchestrator.defs.jobs.stock_daily_trend_channel_update import (
    gold_stock_daily_trend_channel_update_job,
)
from orchestrator.defs.partitions import (
    cn_a_stock_daily_trend_channel_trade_days,
)
from orchestrator.defs.paths import (
    gold_stock_daily_qfq_path,
    gold_stock_daily_trend_channel_path,
    gold_stock_daily_trend_channel_state_path,
    silver_adj_factor_path,
    silver_stock_lifecycle_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.cursors import load_sensor_cursor
from orchestrator.defs.run_contracts.sensor_tags import (
    SENSOR_DOMAIN_TAG,
    SENSOR_ROLE_TAG,
    SENSOR_TARGET_LAYER_TAG,
)
from orchestrator.defs.sensors import stock_daily_trend_channel_sensor as sensor_module
from orchestrator.defs.sensors import (
    stock_daily_trend_channel_trade_day_sensor as registration_module,
)
from orchestrator.defs.sensors.readiness import (
    AssetReadinessStatus,
    DatasetReadinessStatus,
)
from orchestrator.defs.sensors.stock_daily_trend_channel_sensor import (
    _qfq_reconciliation,
    gold_stock_daily_trend_channel_update_job_sensor,
)
from orchestrator.defs.sensors.stock_daily_trend_channel_trade_day_sensor import (
    STOCK_DAILY_TREND_CHANNEL_MAX_PARTITIONS_PER_TICK,
    STOCK_DAILY_TREND_CHANNEL_REGISTER_START,
    stock_daily_trend_channel_trade_day_sensor,
)
from orchestrator.defs.stock_daily_qfq import GoldStockDailyQfqFactorRepairPlan
from orchestrator.defs.stock_daily_trend_channel import (
    FORMULA_VERSION,
    audit_stock_daily_trend_channel_result,
    audit_stock_daily_trend_channel_state,
    audit_stock_daily_trend_channel_state_coverage,
)
from tests.test_stock_daily_trend_channel_m3 import (
    _write_calendar,
    _write_day,
    _write_parquet,
)

DAY_1 = "2026-08-27"
DAY_2 = "2026-08-28"


def test_daily_materialization_metadata_uses_registered_stock_basic_key() -> None:
    write_result = SimpleNamespace(
        state_path=Path("/lake/state.parquet"),
        result_path=Path("/lake/result.parquet"),
        qfq_source_path=Path("/lake/qfq.parquet"),
        previous_state_path=None,
        stock_basic_path=Path("/lake/stock_basic.parquet"),
        stock_lifecycle_path=Path("/lake/stock_lifecycle.parquet"),
        source_row_count=1,
        output_row_count=1,
        observed_state_row_count=1,
        carried_state_row_count=0,
        uninitialized_lifecycle_code_count=0,
        candidate_bytes=128,
        elapsed_ms=1.5,
        peak_memory_bytes=None,
        temp_spill_bytes=0,
        observed_state_columns=("ts_code",),
        observed_result_columns=("ts_code",),
    )

    state_metadata = asset_module._state_materialization_metadata(
        write_result=write_result,
        partition_key=DAY_1,
    )
    result_metadata = asset_module._result_materialization_metadata(
        write_result=write_result,
        partition_key=DAY_1,
    )

    for metadata in (state_metadata, result_metadata):
        assert metadata["goldenshare/stock_basic_file_path"] == (
            "/lake/stock_basic.parquet"
        )
        assert "stock_basic_path" not in metadata
        assert "goldenshare/stock_basic_path" not in metadata


def _write_ready_days(
    connection,
    *,
    root: Path,
    staging: Path,
    trade_dates: tuple[str, ...],
) -> None:
    previous_trade_date = None
    for index, trade_date in enumerate(trade_dates):
        _write_day(
            connection=connection,
            root=root,
            staging_root=staging,
            run_id=f"day-{index}",
            trade_date=trade_date,
            qfq_rows=[("000001.SZ", 10.0 + index, 11.0 + index, 9.0 + index, 10.5 + index)],
            lifecycle_rows=[("000001.SZ", "1991-01-01", None)],
            previous_trade_date=previous_trade_date,
        )
        previous_trade_date = trade_date


def _batch_status(
    *,
    trade_dates: tuple[str, ...],
    statuses: dict[str, ContinuityDateReadiness],
) -> StockDailyTrendChannelBatchReadiness:
    return StockDailyTrendChannelBatchReadiness(
        expected_trade_dates=trade_dates,
        statuses_by_trade_date=statuses,
        elapsed_ms=3,
        scanned_file_count=0,
        sql_count=0,
        slowest_query_ms=0,
        window_date_count=len(trade_dates),
    )


def _missing_target(trade_date: str) -> ContinuityDateReadiness:
    return ContinuityDateReadiness(
        trade_date=trade_date,
        ready=False,
        materialized=False,
        checks_passed=False,
        reason="target_not_materialized",
    )


def _ready_dataset(asset_key: str, trade_date: str) -> DatasetReadinessStatus:
    return DatasetReadinessStatus(
        ready=True,
        statuses=(
            AssetReadinessStatus(
                asset_key=asset_key,
                partition_key=trade_date,
                ready=True,
                materialized=True,
                checks_passed=True,
                freshness_passed=True,
                materialization_storage_id=1,
                materialization_date=trade_date,
                missing_check_names=(),
                failed_check_names=(),
                reason="ready",
            ),
        ),
    )


def _ready_lifecycle(trade_date: str) -> AssetReadinessStatus:
    return _ready_dataset("silver_stock_lifecycle", trade_date).statuses[0]


def _expected_window() -> ContinuityExpectedDateWindow:
    return ContinuityExpectedDateWindow(
        expected_trade_dates=(DAY_1, DAY_2),
        min_trade_date=DAY_1,
        max_trade_date=DAY_2,
        evaluated_at=datetime.fromisoformat("2026-08-28T18:00:00+08:00"),
        window_limit=10,
    )


class _FakeInstance:
    def __init__(self, partitions: tuple[str, ...]) -> None:
        self.partitions = partitions

    def get_dynamic_partitions(self, name: str) -> list[str]:
        assert name == cn_a_stock_daily_trend_channel_trade_days.name
        return list(self.partitions)


def _fake_context(partitions: tuple[str, ...]) -> SimpleNamespace:
    return SimpleNamespace(
        instance=_FakeInstance(partitions),
        resources=SimpleNamespace(lake_root=object(), duckdb=object()),
    )


def _no_repair_reconciliation():
    plan = GoldStockDailyQfqFactorRepairPlan(
        qfq_factor_trade_date=DAY_2,
        previous_trade_date=DAY_1,
        reason="no_factor_changed",
        can_execute_repair=True,
        repair_required=False,
        repair_required_codes=(),
        repair_required_codes_hash="empty-hash",
    )
    status = GoldStockDailyQfqFactorRepairStatus(
        ready=True,
        trade_date=DAY_2,
        reason="ready",
        repair_required=False,
        upstream_batch_id="batch",
    )
    return plan, status, None


def test_batch_readiness_matches_three_ordinary_contracts(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    connection = duckdb.connect()
    try:
        _write_ready_days(
            connection,
            root=root,
            staging=tmp_path / "staging",
            trade_dates=(DAY_1, DAY_2),
        )
        status = batch_gold_stock_daily_trend_channel_readiness(
            connection=connection,
            lake_root=root,
            expected_trade_dates=(DAY_1, DAY_2),
            previous_trade_date=None,
        )
    finally:
        connection.close()

    assert all(value.ready for value in status.statuses_by_trade_date.values())
    assert status.sql_count == 2
    assert status.scanned_file_count == 4
    assert status.window_date_count == 2


def test_batch_and_scalar_audits_use_shared_rule_evaluation_kernel() -> None:
    batch_source = inspect.getsource(readiness_module._status_from_audit_row)
    scalar_sources = "\n".join(
        inspect.getsource(function)
        for function in (
            trend_channel.audit_stock_daily_trend_channel_result,
            trend_channel.audit_stock_daily_trend_channel_state,
            trend_channel.audit_stock_daily_trend_channel_state_coverage,
        )
    )
    for evaluator_name in (
        "evaluate_stock_daily_trend_channel_result_rules",
        "evaluate_stock_daily_trend_channel_state_rules",
        "evaluate_stock_daily_trend_channel_coverage_rules",
    ):
        assert evaluator_name in batch_source
        assert evaluator_name in scalar_sources


def test_batch_readiness_rejects_more_than_ten_dates_before_sql() -> None:
    class _SqlMustNotRun:
        def execute(self, *args, **kwargs):
            raise AssertionError("SQL must not run for an oversized window")

    trade_dates = tuple(
        (date(2026, 8, 1) + timedelta(days=offset)).isoformat()
        for offset in range(11)
    )
    with pytest.raises(ValueError, match="at most 10 trade dates"):
        batch_gold_stock_daily_trend_channel_readiness(
            connection=_SqlMustNotRun(),
            lake_root=Path("/must-not-be-read"),
            expected_trade_dates=trade_dates,
            previous_trade_date=None,
        )


def test_batch_readiness_rejects_bad_existing_target_without_overwrite(
    tmp_path: Path,
) -> None:
    root = tmp_path / "lake"
    connection = duckdb.connect()
    try:
        _write_ready_days(
            connection,
            root=root,
            staging=tmp_path / "staging",
            trade_dates=(DAY_1,),
        )
        result_path = gold_stock_daily_trend_channel_path(root, DAY_1)
        bad_path = result_path.with_name("bad.parquet")
        _write_parquet(
            connection,
            bad_path,
            f"""
            SELECT * REPLACE ('bad-version' AS formula_version)
            FROM read_parquet('{result_path}')
            """,
        )
        os.replace(bad_path, result_path)
        scalar_audit = audit_stock_daily_trend_channel_result(
            connection=connection,
            result_path=result_path,
            qfq_source_path=(
                root
                / "gold"
                / "quote"
                / "stock_daily_qfq"
                / f"trade_date={DAY_1}"
                / "part-000.parquet"
            ),
            trade_date=DAY_1,
        )
        batch = batch_gold_stock_daily_trend_channel_readiness(
            connection=connection,
            lake_root=root,
            expected_trade_dates=(DAY_1,),
            previous_trade_date=None,
        )
    finally:
        connection.close()

    target = batch.status_for_trade_date(DAY_1)
    assert not target.ready
    assert target.materialized
    assert target.reason == "target_lake_checks_failed"
    assert target.summary["result_failure_rule_counts"] == {
        key: value
        for key, value in scalar_audit.failure_rule_counts.items()
        if value
    }


def test_batch_readiness_state_contract_matches_scalar_audit(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    connection = duckdb.connect()
    try:
        _write_ready_days(
            connection,
            root=root,
            staging=tmp_path / "staging",
            trade_dates=(DAY_1,),
        )
        state_path = gold_stock_daily_trend_channel_state_path(root, DAY_1)
        bad_path = state_path.with_name("bad.parquet")
        _write_parquet(
            connection,
            bad_path,
            f"""
            SELECT * REPLACE ('bad-version' AS formula_version)
            FROM read_parquet('{state_path}')
            """,
        )
        os.replace(bad_path, state_path)
        scalar_audit = audit_stock_daily_trend_channel_state(
            connection=connection,
            state_path=state_path,
            stock_lifecycle_path=silver_stock_lifecycle_path(root),
            trade_date=DAY_1,
        )
        batch = batch_gold_stock_daily_trend_channel_readiness(
            connection=connection,
            lake_root=root,
            expected_trade_dates=(DAY_1,),
            previous_trade_date=None,
        )
    finally:
        connection.close()

    target = batch.status_for_trade_date(DAY_1)
    assert not target.ready
    assert target.materialized
    assert target.reason == "target_lake_checks_failed"
    assert target.summary["state_failure_rule_counts"] == {
        key: value
        for key, value in scalar_audit.failure_rule_counts.items()
        if value
    }


def test_batch_readiness_state_coverage_matches_scalar_audit(
    tmp_path: Path,
) -> None:
    root = tmp_path / "lake"
    connection = duckdb.connect()
    try:
        _write_ready_days(
            connection,
            root=root,
            staging=tmp_path / "staging",
            trade_dates=(DAY_1,),
        )
        state_path = gold_stock_daily_trend_channel_state_path(root, DAY_1)
        empty_path = state_path.with_name("empty.parquet")
        _write_parquet(
            connection,
            empty_path,
            f"SELECT * FROM read_parquet('{state_path}') WHERE false",
        )
        os.replace(empty_path, state_path)
        scalar_audit = audit_stock_daily_trend_channel_state_coverage(
            connection=connection,
            state_path=state_path,
            qfq_source_path=gold_stock_daily_qfq_path(root, DAY_1),
            stock_lifecycle_path=silver_stock_lifecycle_path(root),
            previous_state_path=None,
            trade_date=DAY_1,
        )
        batch = batch_gold_stock_daily_trend_channel_readiness(
            connection=connection,
            lake_root=root,
            expected_trade_dates=(DAY_1,),
            previous_trade_date=None,
        )
    finally:
        connection.close()

    target = batch.status_for_trade_date(DAY_1)
    assert not target.ready
    assert target.materialized
    assert target.reason == "target_lake_checks_failed"
    assert target.summary["coverage_failure_rule_counts"] == {
        key: value
        for key, value in scalar_audit.failure_rule_counts.items()
        if value
    }


def test_batch_readiness_distinguishes_missing_and_partial_target(
    tmp_path: Path,
) -> None:
    root = tmp_path / "lake"
    result_path = gold_stock_daily_trend_channel_path(root, DAY_1)
    connection = duckdb.connect()
    try:
        _write_parquet(connection, result_path, "SELECT 1 AS bad")
        batch = batch_gold_stock_daily_trend_channel_readiness(
            connection=connection,
            lake_root=root,
            expected_trade_dates=(DAY_1, DAY_2),
            previous_trade_date=None,
        )
    finally:
        connection.close()

    partial = batch.status_for_trade_date(DAY_1)
    missing = batch.status_for_trade_date(DAY_2)
    assert partial.materialized and not partial.ready
    assert partial.reason == "target_pair_partially_materialized"
    assert not missing.materialized and not missing.ready
    assert missing.reason == "target_not_materialized"


def test_ten_day_batch_readiness_stays_inside_frozen_budget(tmp_path: Path) -> None:
    start = date(2026, 8, 10)
    all_trade_dates = tuple(
        (start + timedelta(days=offset)).isoformat() for offset in range(11)
    )
    trade_dates = all_trade_dates[1:]
    root = tmp_path / "lake"
    connection = duckdb.connect()
    try:
        _write_ready_days(
            connection,
            root=root,
            staging=tmp_path / "staging",
            trade_dates=all_trade_dates,
        )
        batch = batch_gold_stock_daily_trend_channel_readiness(
            connection=connection,
            lake_root=root,
            expected_trade_dates=trade_dates,
            previous_trade_date=all_trade_dates[0],
        )
    finally:
        connection.close()

    assert all(value.ready for value in batch.statuses_by_trade_date.values())
    assert batch.sql_count == 2
    assert batch.scanned_file_count == 21
    assert batch.elapsed_ms < 5_000
    assert batch.slowest_query_ms < 5_000


def test_m4_sensor_and_job_definitions_are_stopped_tagged_and_bounded() -> None:
    assert gold_stock_daily_trend_channel_update_job.name == (
        "gold_stock_daily_trend_channel_update_job"
    )
    assert stock_daily_trend_channel_trade_day_sensor.default_status == (
        dg.DefaultSensorStatus.STOPPED
    )
    assert gold_stock_daily_trend_channel_update_job_sensor.default_status == (
        dg.DefaultSensorStatus.STOPPED
    )
    assert stock_daily_trend_channel_trade_day_sensor.minimum_interval_seconds == 600
    assert gold_stock_daily_trend_channel_update_job_sensor.minimum_interval_seconds == 600
    assert STOCK_DAILY_TREND_CHANNEL_REGISTER_START.hour == 6
    assert STOCK_DAILY_TREND_CHANNEL_MAX_PARTITIONS_PER_TICK == 2
    assert stock_daily_trend_channel_trade_day_sensor.tags == {
        SENSOR_DOMAIN_TAG: "quote_data",
        SENSOR_TARGET_LAYER_TAG: "partition",
        SENSOR_ROLE_TAG: "partition_registration",
    }
    assert gold_stock_daily_trend_channel_update_job_sensor.tags == {
        SENSOR_DOMAIN_TAG: "quote_data",
        SENSOR_TARGET_LAYER_TAG: "gold",
        SENSOR_ROLE_TAG: "asset_update",
    }
    definitions = project_defs()
    asset_graph = definitions.resolve_asset_graph()
    selected_assets = gold_stock_daily_trend_channel_update_job.selection.resolve(
        asset_graph
    )
    selected_checks = (
        gold_stock_daily_trend_channel_update_job.selection.resolve_checks(
            asset_graph
        )
    )
    assert selected_assets == {
        dg.AssetKey("gold_stock_daily_trend_channel"),
        dg.AssetKey("gold_stock_daily_trend_channel_state"),
    }
    assert selected_checks == {
        dg.AssetCheckKey(
            dg.AssetKey("gold_stock_daily_trend_channel"),
            "gold_stock_daily_trend_channel_contract_check",
        ),
        dg.AssetCheckKey(
            dg.AssetKey("gold_stock_daily_trend_channel"),
            "gold_stock_daily_trend_channel_input_coverage_check",
        ),
        dg.AssetCheckKey(
            dg.AssetKey("gold_stock_daily_trend_channel_state"),
            "gold_stock_daily_trend_channel_state_contract_check",
        ),
    }


def test_registration_sensor_excludes_today_before_0600_and_registers_after(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "lake"
    for part in ("raw", "silver", "gold", "_tmp"):
        (root / part).mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as connection:
        _write_calendar(connection, root, [DAY_1, DAY_2])
    context = SimpleNamespace(
        instance=_FakeInstance((DAY_1,)),
        resources=SimpleNamespace(
            lake_root=LakeRootResource(root_path=str(root)),
            duckdb=DuckDBResource(),
        ),
    )

    class _BeforeSix:
        @classmethod
        def now(cls, timezone):
            return datetime.fromisoformat("2026-08-28T05:59:00+08:00")

    monkeypatch.setattr(registration_module, "datetime", _BeforeSix)
    before = stock_daily_trend_channel_trade_day_sensor._raw_fn(context)
    assert before.dynamic_partitions_requests == []

    class _AfterSix:
        @classmethod
        def now(cls, timezone):
            return datetime.fromisoformat("2026-08-28T06:00:00+08:00")

    monkeypatch.setattr(registration_module, "datetime", _AfterSix)
    after = stock_daily_trend_channel_trade_day_sensor._raw_fn(context)
    assert len(after.dynamic_partitions_requests) == 1
    assert after.dynamic_partitions_requests[0].partition_keys == [DAY_2]


def test_daily_sensor_selects_one_earliest_missing_target(monkeypatch) -> None:
    context = _fake_context((DAY_1, DAY_2))
    batch = _batch_status(
        trade_dates=(DAY_1, DAY_2),
        statuses={
            DAY_1: ContinuityDateReadiness(
                trade_date=DAY_1,
                ready=True,
                materialized=True,
                checks_passed=True,
                reason="ready",
            ),
            DAY_2: _missing_target(DAY_2),
        },
    )
    monkeypatch.setattr(sensor_module, "_load_expected_window", lambda *args, **kwargs: _expected_window())
    monkeypatch.setattr(sensor_module, "_load_target_readiness", lambda *args, **kwargs: (DAY_1, batch))
    monkeypatch.setattr(
        sensor_module,
        "partition_dataset_readiness_status_from_latest_checks",
        lambda *args, **kwargs: _ready_dataset("gold_stock_daily_qfq", DAY_2),
    )
    monkeypatch.setattr(
        sensor_module,
        "stock_basic_ready_for_trade_date",
        lambda *args, **kwargs: _ready_dataset("silver_stock_basic", DAY_2),
    )
    monkeypatch.setattr(
        sensor_module,
        "silver_stock_lifecycle_ready_for_trade_date",
        lambda *args, **kwargs: _ready_lifecycle(DAY_2),
    )
    monkeypatch.setattr(
        sensor_module,
        "_previous_state_status",
        lambda *args, **kwargs: ContinuityDateReadiness(
            trade_date=DAY_2,
            ready=True,
            materialized=True,
            checks_passed=True,
            reason="ready",
        ),
    )
    monkeypatch.setattr(
        sensor_module,
        "_qfq_reconciliation",
        lambda *args, **kwargs: _no_repair_reconciliation(),
    )

    result = gold_stock_daily_trend_channel_update_job_sensor._raw_fn(context)

    assert len(result.run_requests) == 1
    request = result.run_requests[0]
    assert request.partition_key == DAY_2
    assert request.run_key == (
        f"gold_stock_daily_trend_channel_update:{DAY_2}:{FORMULA_VERSION}"
    )
    cursor = result.cursor
    assert len(cursor.encode("utf-8")) < 2_048
    assert load_sensor_cursor(cursor)["details"]["reason_code"] == (
        "selected_for_update"
    )


def test_daily_sensor_blocks_existing_bad_target_before_upstream_checks(
    monkeypatch,
) -> None:
    context = _fake_context((DAY_1, DAY_2))
    upstream = SimpleNamespace(called=False)
    bad_status = ContinuityDateReadiness(
        trade_date=DAY_1,
        ready=False,
        materialized=True,
        checks_passed=False,
        reason="target_lake_checks_failed",
        failed_check_names=("gold_stock_daily_trend_channel_contract_check",),
    )
    batch = _batch_status(
        trade_dates=(DAY_1, DAY_2),
        statuses={DAY_1: bad_status, DAY_2: _missing_target(DAY_2)},
    )
    monkeypatch.setattr(sensor_module, "_load_expected_window", lambda *args, **kwargs: _expected_window())
    monkeypatch.setattr(sensor_module, "_load_target_readiness", lambda *args, **kwargs: (None, batch))

    def _unexpected(*args, **kwargs):
        upstream.called = True
        raise AssertionError("upstream readiness must not run")

    monkeypatch.setattr(
        sensor_module,
        "partition_dataset_readiness_status_from_latest_checks",
        _unexpected,
    )

    result = gold_stock_daily_trend_channel_update_job_sensor._raw_fn(context)

    assert result.run_requests == []
    assert not upstream.called
    assert load_sensor_cursor(result.cursor)["details"]["reason_code"] == (
        "target_checks_failed"
    )


def test_daily_sensor_blocks_factor_change_until_m5_repair_completion(
    monkeypatch,
) -> None:
    context = _fake_context((DAY_1, DAY_2))
    batch = _batch_status(
        trade_dates=(DAY_1, DAY_2),
        statuses={DAY_1: _missing_target(DAY_1), DAY_2: _missing_target(DAY_2)},
    )
    repair_plan = GoldStockDailyQfqFactorRepairPlan(
        qfq_factor_trade_date=DAY_1,
        previous_trade_date=None,
        reason="factor_changed",
        can_execute_repair=True,
        repair_required=True,
        repair_required_codes=("000001.SZ",),
        repair_required_codes_hash="hash",
    )
    repair_status = GoldStockDailyQfqFactorRepairStatus(
        ready=True,
        trade_date=DAY_1,
        reason="ready",
        repair_required=True,
        repair_required_code_count=1,
        upstream_batch_id="batch",
    )
    monkeypatch.setattr(sensor_module, "_load_expected_window", lambda *args, **kwargs: _expected_window())
    monkeypatch.setattr(sensor_module, "_load_target_readiness", lambda *args, **kwargs: (None, batch))
    monkeypatch.setattr(
        sensor_module,
        "partition_dataset_readiness_status_from_latest_checks",
        lambda *args, **kwargs: _ready_dataset("gold_stock_daily_qfq", DAY_1),
    )
    monkeypatch.setattr(
        sensor_module,
        "stock_basic_ready_for_trade_date",
        lambda *args, **kwargs: _ready_dataset("silver_stock_basic", DAY_1),
    )
    monkeypatch.setattr(
        sensor_module,
        "silver_stock_lifecycle_ready_for_trade_date",
        lambda *args, **kwargs: _ready_lifecycle(DAY_1),
    )
    monkeypatch.setattr(sensor_module, "_previous_state_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        sensor_module,
        "_qfq_reconciliation",
        lambda *args, **kwargs: (
            repair_plan,
            repair_status,
            "trend_repair_required",
        ),
    )

    result = gold_stock_daily_trend_channel_update_job_sensor._raw_fn(context)

    assert result.run_requests == []
    assert load_sensor_cursor(result.cursor)["details"]["reason_code"] == (
        "trend_repair_required"
    )


def test_qfq_reconciliation_uses_latest_materialization_exact_batch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "lake"
    for trade_date in (DAY_1, DAY_2):
        path = silver_adj_factor_path(root, trade_date)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    plan = GoldStockDailyQfqFactorRepairPlan(
        qfq_factor_trade_date=DAY_2,
        previous_trade_date=DAY_1,
        reason="no_factor_changed",
        can_execute_repair=True,
        repair_required=False,
        repair_required_codes=(),
        repair_required_codes_hash="empty-hash",
    )
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        sensor_module,
        "_latest_qfq_materialization_run_id",
        lambda *args, **kwargs: "qfq-run-1",
    )
    monkeypatch.setattr(
        sensor_module,
        "build_gold_stock_daily_qfq_factor_repair_plan",
        lambda **kwargs: plan,
    )

    def _status(instance, trade_date, *, upstream_batch_id=None):
        captured["upstream_batch_id"] = upstream_batch_id
        return GoldStockDailyQfqFactorRepairStatus(
            ready=True,
            trade_date=trade_date,
            reason="ready",
            repair_required=False,
            producer_run_id="qfq-run-1",
            upstream_batch_id=upstream_batch_id,
        )

    monkeypatch.setattr(
        sensor_module,
        "gold_stock_daily_qfq_factor_repair_status",
        _status,
    )
    context = SimpleNamespace(
        instance=object(),
        resources=SimpleNamespace(
            lake_root=SimpleNamespace(root=lambda: root),
            duckdb=SimpleNamespace(connect=lambda: nullcontext(object())),
        ),
    )

    resolved_plan, status, reason = _qfq_reconciliation(
        context,
        target_trade_date=DAY_2,
        previous_trade_date=DAY_1,
    )

    assert resolved_plan is plan
    assert status is not None and status.ready
    assert reason is None
    assert captured["upstream_batch_id"].startswith(
        f"gold_stock_daily_qfq_update:{DAY_2}:"
    )


def test_qfq_reconciliation_rejects_old_green_batch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "lake"
    for trade_date in (DAY_1, DAY_2):
        path = silver_adj_factor_path(root, trade_date)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    plan, _, _ = _no_repair_reconciliation()
    monkeypatch.setattr(
        sensor_module,
        "_latest_qfq_materialization_run_id",
        lambda *args, **kwargs: "new-qfq-run",
    )
    monkeypatch.setattr(
        sensor_module,
        "build_gold_stock_daily_qfq_factor_repair_plan",
        lambda **kwargs: plan,
    )
    monkeypatch.setattr(
        sensor_module,
        "gold_stock_daily_qfq_factor_repair_status",
        lambda *args, **kwargs: GoldStockDailyQfqFactorRepairStatus(
            ready=False,
            trade_date=DAY_2,
            reason="status belongs to a different upstream batch",
            upstream_batch_id="old-batch",
        ),
    )
    context = SimpleNamespace(
        instance=object(),
        resources=SimpleNamespace(
            lake_root=SimpleNamespace(root=lambda: root),
            duckdb=SimpleNamespace(connect=lambda: nullcontext(object())),
        ),
    )

    _, status, reason = _qfq_reconciliation(
        context,
        target_trade_date=DAY_2,
        previous_trade_date=DAY_1,
    )

    assert status is not None and not status.ready
    assert reason == "qfq_reconciliation_not_ready"
