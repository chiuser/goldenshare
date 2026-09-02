import json
import os
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import dagster as dg
import duckdb
import pytest

import orchestrator.defs.asset_guards.stock_daily_trend_channel_repair as repair_guard
import orchestrator.defs.ops.gold_stock_daily_trend_channel_repair as repair_op_module
import orchestrator.defs.sensors.gold_stock_daily_trend_channel_repair_job_sensor as repair_sensor
import orchestrator.defs.sensors.stock_daily_trend_channel_sensor as daily_sensor
from orchestrator.defs.asset_guards.stock_daily_qfq_factor_repair import (
    GoldStockDailyQfqFactorRepairStatus,
)
from orchestrator.defs.asset_guards.stock_daily_trend_channel_repair import (
    RESULT_ASSET_KEY,
    RESULT_REPAIR_COMPLETION_CHECK_NAME,
    STATE_ASSET_KEY,
    STATE_REPAIR_COMPLETION_CHECK_NAME,
    gold_stock_daily_trend_channel_repair_completion_status,
)
from orchestrator.defs.jobs.gold_stock_daily_trend_channel_repair import (
    gold_stock_daily_trend_channel_repair_job,
)
from orchestrator.defs.partitions import (
    cn_a_stock_daily_trend_channel_trade_days,
)
from orchestrator.defs.paths import (
    gold_stock_daily_qfq_path,
    gold_stock_daily_trend_channel_path,
    gold_stock_daily_trend_channel_staging_path,
    gold_stock_daily_trend_channel_state_path,
    gold_stock_daily_trend_channel_state_staging_path,
    silver_stock_lifecycle_path,
)
from orchestrator.defs.run_contracts.configs import (
    GoldStockDailyTrendChannelRepairConfig,
    build_gold_stock_daily_trend_channel_repair_run_config,
)
from orchestrator.defs.sensors.gold_stock_daily_trend_channel_repair_job_sensor import (
    _run_request,
    build_stock_daily_trend_channel_repair_run_status_decision,
    gold_stock_daily_trend_channel_repair_job_sensor,
)
from orchestrator.defs.stock_daily_qfq import (
    GoldStockDailyQfqFactorRepairPlan,
    gold_stock_daily_qfq_factor_repair_codes_hash,
)
from orchestrator.defs.stock_daily_trend_channel import (
    FORMULA_VERSION,
    TREND_AUTO_REPAIR_CODE_LIMIT,
    StockDailyTrendChannelRepairPartition,
    write_stock_daily_trend_channel_factor_repair,
)
from tests.test_stock_daily_trend_channel_m3 import (
    _rows,
    _write_day,
    _write_qfq,
)

DATES = ("2026-08-27", "2026-08-28", "2026-08-31")
AFFECTED_CODE = "000001.SZ"
UNAFFECTED_CODE = "600000.SH"


def _qfq_rows(
    *, repaired: bool
) -> dict[str, list[tuple[str, float, float, float, float]]]:
    scale = 2.0 if repaired else 1.0
    return {
        DATES[0]: [
            (AFFECTED_CODE, 10.0 * scale, 11.0 * scale, 9.0 * scale, 10.5 * scale),
            (UNAFFECTED_CODE, 20.0, 21.0, 19.0, 20.5),
        ],
        DATES[1]: [(UNAFFECTED_CODE, 20.5, 21.5, 19.5, 21.0)],
        DATES[2]: [
            (AFFECTED_CODE, 11.0 * scale, 12.0 * scale, 10.0 * scale, 11.5 * scale),
            (UNAFFECTED_CODE, 21.0, 22.0, 20.0, 21.5),
        ],
    }


def _write_history(
    *,
    connection,
    root: Path,
    staging_root: Path,
    repaired: bool,
) -> None:
    lifecycle = [
        (AFFECTED_CODE, "1991-01-01", None),
        (UNAFFECTED_CODE, "1999-01-01", None),
    ]
    rows_by_date = _qfq_rows(repaired=repaired)
    for index, trade_date in enumerate(DATES):
        _write_day(
            connection=connection,
            root=root,
            staging_root=staging_root,
            run_id=f"baseline-{repaired}-{index}",
            trade_date=trade_date,
            qfq_rows=rows_by_date[trade_date],
            lifecycle_rows=lifecycle,
            previous_trade_date=DATES[index - 1] if index > 0 else None,
        )


def _replace_qfq_with_repaired_history(connection, root: Path) -> None:
    for trade_date, rows in _qfq_rows(repaired=True).items():
        _write_qfq(
            connection,
            gold_stock_daily_qfq_path(root, trade_date),
            trade_date,
            rows,
        )


def _repair_partitions(
    *,
    root: Path,
    staging_root: Path,
    run_id: str,
) -> tuple[StockDailyTrendChannelRepairPartition, ...]:
    return tuple(
        StockDailyTrendChannelRepairPartition(
            trade_date=trade_date,
            qfq_source_path=gold_stock_daily_qfq_path(root, trade_date),
            previous_state_target_path=(
                gold_stock_daily_trend_channel_state_path(root, DATES[index - 1])
                if index > 0
                else None
            ),
            result_target_path=gold_stock_daily_trend_channel_path(root, trade_date),
            state_target_path=gold_stock_daily_trend_channel_state_path(
                root, trade_date
            ),
            result_candidate_path=gold_stock_daily_trend_channel_staging_path(
                staging_root, run_id, trade_date
            ),
            state_candidate_path=(
                gold_stock_daily_trend_channel_state_staging_path(
                    staging_root, run_id, trade_date
                )
            ),
        )
        for index, trade_date in enumerate(DATES)
    )


def _execute_repair(
    *,
    connection,
    root: Path,
    staging_root: Path,
    run_id: str,
    replace_file=os.replace,
):
    return write_stock_daily_trend_channel_factor_repair(
        connection=connection,
        repair_start_trade_date=DATES[0],
        repair_end_trade_date=DATES[-1],
        repair_required_codes=(AFFECTED_CODE,),
        stock_lifecycle_path=silver_stock_lifecycle_path(root),
        partitions=_repair_partitions(
            root=root,
            staging_root=staging_root,
            run_id=run_id,
        ),
        replace_file=replace_file,
    )


def test_scoped_repair_matches_clean_full_recompute_and_preserves_unaffected(
    tmp_path: Path,
) -> None:
    root = tmp_path / "lake"
    expected_root = tmp_path / "expected-lake"
    staging = tmp_path / "staging"
    expected_staging = tmp_path / "expected-staging"
    connection = duckdb.connect()
    try:
        _write_history(
            connection=connection,
            root=root,
            staging_root=staging,
            repaired=False,
        )
        unaffected_before = {
            trade_date: tuple(
                row
                for row in _rows(
                    connection,
                    gold_stock_daily_trend_channel_path(root, trade_date),
                )
                if row[0] == UNAFFECTED_CODE
            )
            for trade_date in DATES
        }
        _replace_qfq_with_repaired_history(connection, root)
        _write_history(
            connection=connection,
            root=expected_root,
            staging_root=expected_staging,
            repaired=True,
        )

        result = _execute_repair(
            connection=connection,
            root=root,
            staging_root=staging,
            run_id="repair",
        )

        assert result.selected_partition_count == 3
        assert result.rewritten_result_partition_count == 3
        assert result.rewritten_state_partition_count == 3
        carried_state = next(
            row
            for row in _rows(
                connection,
                gold_stock_daily_trend_channel_state_path(root, DATES[1]),
            )
            if row[0] == AFFECTED_CODE
        )
        assert carried_state[2].isoformat() == DATES[0]
        assert carried_state[3] is False
        for trade_date in DATES:
            assert _rows(
                connection,
                gold_stock_daily_trend_channel_path(root, trade_date),
            ) == _rows(
                connection,
                gold_stock_daily_trend_channel_path(expected_root, trade_date),
            )
            assert _rows(
                connection,
                gold_stock_daily_trend_channel_state_path(root, trade_date),
            ) == _rows(
                connection,
                gold_stock_daily_trend_channel_state_path(expected_root, trade_date),
            )
            assert unaffected_before[trade_date] == tuple(
                row
                for row in _rows(
                    connection,
                    gold_stock_daily_trend_channel_path(root, trade_date),
                )
                if row[0] == UNAFFECTED_CODE
            )
    finally:
        connection.close()


def test_all_candidates_exist_before_promotion(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    staging = tmp_path / "staging"
    connection = duckdb.connect()
    checked = False

    def _assert_candidates_then_replace(source: Path, target: Path) -> None:
        nonlocal checked
        if not checked:
            partitions = _repair_partitions(
                root=root,
                staging_root=staging,
                run_id="all-candidates",
            )
            assert all(
                item.result_candidate_path.is_file()
                and item.state_candidate_path.is_file()
                for item in partitions
            )
            checked = True
        os.replace(source, target)

    try:
        _write_history(
            connection=connection,
            root=root,
            staging_root=staging,
            repaired=False,
        )
        _replace_qfq_with_repaired_history(connection, root)
        _execute_repair(
            connection=connection,
            root=root,
            staging_root=staging,
            run_id="all-candidates",
            replace_file=_assert_candidates_then_replace,
        )
        assert checked
    finally:
        connection.close()


def test_partial_promotion_is_retryable_and_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "lake"
    expected_root = tmp_path / "expected-lake"
    staging = tmp_path / "staging"
    connection = duckdb.connect()
    replace_count = 0

    def _fail_third_replace(source: Path, target: Path) -> None:
        nonlocal replace_count
        replace_count += 1
        if replace_count == 3:
            raise OSError("forced repair interruption")
        os.replace(source, target)

    try:
        _write_history(
            connection=connection,
            root=root,
            staging_root=staging,
            repaired=False,
        )
        _replace_qfq_with_repaired_history(connection, root)
        _write_history(
            connection=connection,
            root=expected_root,
            staging_root=tmp_path / "expected-staging",
            repaired=True,
        )
        with pytest.raises(OSError, match="forced repair interruption"):
            _execute_repair(
                connection=connection,
                root=root,
                staging_root=staging,
                run_id="interrupted",
                replace_file=_fail_third_replace,
            )
        assert _rows(
            connection,
            gold_stock_daily_trend_channel_path(root, DATES[0]),
        ) == _rows(
            connection,
            gold_stock_daily_trend_channel_path(expected_root, DATES[0]),
        )

        first_retry = _execute_repair(
            connection=connection,
            root=root,
            staging_root=staging,
            run_id="retry-1",
        )
        second_retry = _execute_repair(
            connection=connection,
            root=root,
            staging_root=staging,
            run_id="retry-2",
        )
        assert first_retry.rewritten_result_row_count == (
            second_retry.rewritten_result_row_count
        )
        for trade_date in DATES:
            assert _rows(
                connection,
                gold_stock_daily_trend_channel_path(root, trade_date),
            ) == _rows(
                connection,
                gold_stock_daily_trend_channel_path(expected_root, trade_date),
            )
    finally:
        connection.close()


def test_empty_historical_scope_and_code_limit_are_explicit(tmp_path: Path) -> None:
    lifecycle = tmp_path / "lifecycle.parquet"
    connection = duckdb.connect()
    try:
        lifecycle.parent.mkdir(parents=True, exist_ok=True)
        connection.execute(
            f"COPY (SELECT '000001.SZ' AS ts_code, true AS is_cny_stock, "
            f"DATE '2026-08-31' AS list_date, NULL::DATE AS delist_date) "
            f"TO '{lifecycle}' (FORMAT PARQUET)"
        )
        result = write_stock_daily_trend_channel_factor_repair(
            connection=connection,
            repair_start_trade_date="2026-08-31",
            repair_end_trade_date="2026-08-28",
            repair_required_codes=(AFFECTED_CODE,),
            stock_lifecycle_path=lifecycle,
            partitions=(),
        )
        assert result.selected_partition_count == 0
        with pytest.raises(ValueError, match="exceeds automatic limit"):
            write_stock_daily_trend_channel_factor_repair(
                connection=connection,
                repair_start_trade_date="2026-08-31",
                repair_end_trade_date="2026-08-28",
                repair_required_codes=tuple(
                    f"{index:06d}.SZ"
                    for index in range(TREND_AUTO_REPAIR_CODE_LIMIT + 1)
                ),
                stock_lifecycle_path=lifecycle,
                partitions=(),
            )
    finally:
        connection.close()


def _status(*, code_count: int = 1, repair_required: bool = True):
    codes = tuple(f"{index:06d}.SZ" for index in range(code_count))
    return GoldStockDailyQfqFactorRepairStatus(
        ready=True,
        trade_date="2026-08-31",
        reason="ready",
        repair_required=repair_required,
        upstream_batch_id="qfq-batch",
        repair_start_trade_date="2026-08-27" if repair_required else None,
        repair_end_trade_date="2026-08-31",
        selected_partition_count=3 if repair_required else 0,
        repair_required_code_count=code_count if repair_required else 0,
        repair_required_codes=codes if repair_required else (),
        repair_required_codes_hash=(
            gold_stock_daily_qfq_factor_repair_codes_hash(codes)
        ),
        repair_required_codes_truncated=code_count > TREND_AUTO_REPAIR_CODE_LIMIT,
        rewritten_partition_count=3 if repair_required else 0,
        rewritten_row_count=3 if repair_required else 0,
    )


def test_repair_sensor_contract_and_run_key_are_exact() -> None:
    decision = build_stock_daily_trend_channel_repair_run_status_decision(
        qfq_factor_repair_trade_date="2026-08-31",
        repair_end_trade_date="2026-08-28",
        qfq_factor_repair_status=_status(),
    )
    assert decision.selected
    request = _run_request(decision)
    assert request.run_key == (
        f"gold_stock_daily_trend_channel_repair:{FORMULA_VERSION}:qfq-batch"
    )
    config = request.run_config["ops"]["gold_stock_daily_trend_channel_repair_op"][
        "config"
    ]
    assert config["stock_codes"] == ["000000.SZ"]
    assert config["repair_end_trade_date"] == "2026-08-28"
    assert gold_stock_daily_trend_channel_repair_job.name == (
        "gold_stock_daily_trend_channel_repair_job"
    )
    assert gold_stock_daily_trend_channel_repair_job_sensor.default_status == (
        dg.DefaultSensorStatus.STOPPED
    )


def test_repair_sensor_cursor_uses_trend_partition_set() -> None:
    selected = build_stock_daily_trend_channel_repair_run_status_decision(
        qfq_factor_repair_trade_date="2026-08-31",
        repair_end_trade_date="2026-08-28",
        qfq_factor_repair_status=_status(),
    )
    no_op = build_stock_daily_trend_channel_repair_run_status_decision(
        qfq_factor_repair_trade_date="2026-08-31",
        repair_end_trade_date="2026-08-28",
        qfq_factor_repair_status=_status(code_count=0, repair_required=False),
    )

    for decision in (selected, no_op):
        payload = json.loads(repair_sensor._cursor(decision))
        assert payload["details"]["partition_set"] == (
            cn_a_stock_daily_trend_channel_trade_days.name
        )


def test_repair_sensor_evaluation_returns_run_and_cursor(monkeypatch) -> None:
    status = _status()
    monkeypatch.setattr(
        repair_sensor,
        "_qfq_config_from_run",
        lambda _run: ("2026-08-31", "qfq-batch"),
    )
    monkeypatch.setattr(
        repair_sensor,
        "_previous_expected_trade_date",
        lambda _trade_date: "2026-08-28",
    )
    monkeypatch.setattr(
        repair_sensor,
        "gold_stock_daily_qfq_factor_repair_status",
        lambda _instance, _trade_date, *, upstream_batch_id: status,
    )
    monkeypatch.setattr(
        repair_sensor,
        "gold_stock_daily_trend_channel_repair_completion_status",
        lambda _instance, **_kwargs: SimpleNamespace(ready=False),
    )

    result = repair_sensor._evaluate_sensor(
        SimpleNamespace(dagster_run=object(), instance=object())
    )

    assert len(result.run_requests) == 1
    assert result.run_requests[0].run_key == (
        f"gold_stock_daily_trend_channel_repair:{FORMULA_VERSION}:qfq-batch"
    )
    payload = json.loads(result.cursor)
    assert payload["details"]["partition_set"] == (
        cn_a_stock_daily_trend_channel_trade_days.name
    )


def test_repair_run_key_is_stable_per_exact_upstream_batch() -> None:
    decision = build_stock_daily_trend_channel_repair_run_status_decision(
        qfq_factor_repair_trade_date="2026-08-31",
        repair_end_trade_date="2026-08-28",
        qfq_factor_repair_status=_status(),
    )
    assert decision.selected

    original_key = _run_request(decision).run_key
    assert _run_request(decision).run_key == original_key
    assert (
        _run_request(
            replace(decision, source_upstream_batch_id="qfq-batch-rerun")
        ).run_key
        != original_key
    )


def test_repair_sensor_noop_and_501_scope_fail_closed() -> None:
    no_op = build_stock_daily_trend_channel_repair_run_status_decision(
        qfq_factor_repair_trade_date="2026-08-31",
        repair_end_trade_date="2026-08-28",
        qfq_factor_repair_status=_status(code_count=0, repair_required=False),
    )
    assert not no_op.selected
    assert no_op.reason_code == "trend_repair_not_required"

    at_limit = build_stock_daily_trend_channel_repair_run_status_decision(
        qfq_factor_repair_trade_date="2026-08-31",
        repair_end_trade_date="2026-08-28",
        qfq_factor_repair_status=_status(code_count=TREND_AUTO_REPAIR_CODE_LIMIT),
    )
    assert at_limit.selected
    assert len(at_limit.stock_codes) == TREND_AUTO_REPAIR_CODE_LIMIT

    too_large = build_stock_daily_trend_channel_repair_run_status_decision(
        qfq_factor_repair_trade_date="2026-08-31",
        repair_end_trade_date="2026-08-28",
        qfq_factor_repair_status=_status(code_count=TREND_AUTO_REPAIR_CODE_LIMIT + 1),
    )
    assert not too_large.selected
    assert too_large.reason_code == "repair_scope_exceeds_auto_limit"


def test_typed_repair_config_rejects_non_exact_code_order() -> None:
    with pytest.raises(ValueError, match="sorted and unique"):
        build_gold_stock_daily_trend_channel_repair_run_config(
            qfq_factor_repair_trade_date="2026-08-31",
            repair_start_trade_date="2026-08-27",
            repair_end_trade_date="2026-08-28",
            stock_codes=("600000.SH", "000001.SZ"),
            repair_required_codes_hash="a" * 64,
            source_upstream_batch_id="batch",
        )


def test_repair_op_failure_does_not_emit_completion_checks(monkeypatch) -> None:
    emitted_events: list[object] = []
    context = SimpleNamespace(
        instance=object(),
        run_id="repair-run",
        resources=SimpleNamespace(
            lake_root=SimpleNamespace(
                ensure_available_for_run=lambda: None,
                root=lambda: Path("/private/tmp/unused-lake-root"),
            ),
            duckdb=SimpleNamespace(connect=lambda: nullcontext(object())),
        ),
        log_event=emitted_events.append,
        log=SimpleNamespace(info=lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(
        repair_op_module,
        "_validated_qfq_repair_status",
        lambda **kwargs: SimpleNamespace(selected_partition_count=3),
    )
    monkeypatch.setattr(
        repair_op_module,
        "_load_expected_trade_dates",
        lambda **kwargs: DATES,
    )
    monkeypatch.setattr(
        repair_op_module,
        "_trend_repair_trade_dates",
        lambda **kwargs: (DATES[1], DATES[:2]),
    )
    monkeypatch.setattr(
        repair_op_module,
        "write_stock_daily_trend_channel_factor_repair",
        lambda **kwargs: (_ for _ in ()).throw(OSError("forced repair failure")),
    )
    config = GoldStockDailyTrendChannelRepairConfig(
        qfq_factor_repair_trade_date=DATES[2],
        repair_start_trade_date=DATES[0],
        repair_end_trade_date=DATES[1],
        stock_codes=[AFFECTED_CODE],
        repair_required_codes_hash="a" * 64,
        source_upstream_batch_id="qfq-batch",
    )

    with pytest.raises(OSError, match="forced repair failure"):
        repair_op_module.gold_stock_daily_trend_channel_repair_op.compute_fn.decorated_fn(
            context,
            config,
        )

    assert emitted_events == []


def test_daily_gate_requires_exact_trend_completion(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "lake"
    for trade_date in DATES[-2:]:
        path = daily_sensor.silver_adj_factor_path(root, trade_date)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    codes = (AFFECTED_CODE,)
    codes_hash = gold_stock_daily_qfq_factor_repair_codes_hash(codes)
    plan = GoldStockDailyQfqFactorRepairPlan(
        qfq_factor_trade_date=DATES[-1],
        previous_trade_date=DATES[-2],
        reason="factor_changed",
        can_execute_repair=True,
        repair_required=True,
        repair_required_codes=codes,
        repair_required_codes_hash=codes_hash,
    )
    status = GoldStockDailyQfqFactorRepairStatus(
        ready=True,
        trade_date=DATES[-1],
        reason="ready",
        repair_required=True,
        upstream_batch_id="exact-batch",
        repair_start_trade_date=DATES[0],
        repair_end_trade_date=DATES[-1],
        selected_partition_count=3,
        repair_required_code_count=1,
        repair_required_codes=codes,
        repair_required_codes_hash=codes_hash,
        rewritten_partition_count=3,
        rewritten_row_count=3,
    )
    monkeypatch.setattr(
        daily_sensor,
        "_latest_qfq_materialization_run_id",
        lambda *args, **kwargs: "qfq-run",
    )
    monkeypatch.setattr(
        daily_sensor,
        "build_gold_stock_daily_qfq_factor_repair_plan",
        lambda **kwargs: plan,
    )
    monkeypatch.setattr(
        daily_sensor,
        "gold_stock_daily_qfq_factor_repair_status",
        lambda *args, **kwargs: status,
    )
    context = SimpleNamespace(
        instance=object(),
        resources=SimpleNamespace(
            lake_root=SimpleNamespace(root=lambda: root),
            duckdb=SimpleNamespace(connect=lambda: nullcontext(object())),
        ),
    )
    monkeypatch.setattr(
        daily_sensor,
        "gold_stock_daily_trend_channel_repair_completion_status",
        lambda *args, **kwargs: SimpleNamespace(ready=False),
    )
    _, _, blocked_reason = daily_sensor._qfq_reconciliation(
        context,
        target_trade_date=DATES[-1],
        previous_trade_date=DATES[-2],
    )
    assert blocked_reason == "trend_repair_required"

    monkeypatch.setattr(
        daily_sensor,
        "gold_stock_daily_trend_channel_repair_completion_status",
        lambda *args, **kwargs: SimpleNamespace(ready=True),
    )
    _, _, ready_reason = daily_sensor._qfq_reconciliation(
        context,
        target_trade_date=DATES[-1],
        previous_trade_date=DATES[-2],
    )
    assert ready_reason is None


def _completion_metadata(**overrides) -> dict[str, object]:
    metadata = {
        "qfq_factor_repair_trade_date": "2026-08-31",
        "repair_start_trade_date": "2026-08-27",
        "repair_end_trade_date": "2026-08-28",
        "covered_start_trade_date": "2026-08-27",
        "covered_end_trade_date": "2026-08-28",
        "selected_partition_count": 2,
        "repair_required_code_count": 1,
        "repair_required_codes_hash": "a" * 64,
        "source_upstream_batch_id": "batch",
        "formula_version": FORMULA_VERSION,
        "rewritten_partition_count": 2,
        "rewritten_indicator_partition_count": 2,
        "rewritten_result_partition_count": 2,
        "rewritten_state_partition_count": 2,
        "rewritten_indicator_row_count": 10,
        "rewritten_result_row_count": 10,
        "rewritten_state_row_count": 12,
        "producer_run_id": "repair-run",
    }
    metadata.update(overrides)
    return metadata


def test_completion_guard_requires_both_exact_green_checks(monkeypatch) -> None:
    records = {
        RESULT_REPAIR_COMPLETION_CHECK_NAME: SimpleNamespace(
            evaluation=SimpleNamespace(
                passed=True,
                blocking=True,
                metadata=_completion_metadata(),
            )
        ),
        STATE_REPAIR_COMPLETION_CHECK_NAME: SimpleNamespace(
            evaluation=SimpleNamespace(
                passed=True,
                blocking=True,
                metadata=_completion_metadata(),
            )
        ),
    }

    def _latest(instance, asset_keys, check_name, *, partition_key):
        del instance, partition_key
        asset_key = next(iter(asset_keys))
        record = records.get(check_name)
        return (
            {dg.AssetCheckKey(asset_key, check_name): record}
            if record is not None
            else {}
        )

    monkeypatch.setattr(repair_guard, "latest_partition_check_records", _latest)
    monkeypatch.setattr(
        repair_guard,
        "asset_check_record_evaluation",
        lambda record: record.evaluation,
    )
    monkeypatch.setattr(
        repair_guard,
        "asset_check_record_metadata",
        lambda evaluation: evaluation.metadata,
    )
    monkeypatch.setattr(
        repair_guard, "asset_check_record_succeeded", lambda record: True
    )
    monkeypatch.setattr(
        repair_guard,
        "asset_check_record_partition",
        lambda record, evaluation: "2026-08-31",
    )
    monkeypatch.setattr(
        repair_guard,
        "asset_check_record_event_storage_id",
        lambda *args, **kwargs: 1,
    )

    ready = gold_stock_daily_trend_channel_repair_completion_status(
        object(),
        qfq_factor_repair_trade_date="2026-08-31",
        repair_start_trade_date="2026-08-27",
        repair_end_trade_date="2026-08-28",
        selected_partition_count=2,
        repair_required_code_count=1,
        repair_required_codes_hash="a" * 64,
        source_upstream_batch_id="batch",
    )
    assert ready.ready

    records[
        STATE_REPAIR_COMPLETION_CHECK_NAME
    ].evaluation.metadata = _completion_metadata(source_upstream_batch_id="old-batch")
    mismatch = gold_stock_daily_trend_channel_repair_completion_status(
        object(),
        qfq_factor_repair_trade_date="2026-08-31",
        repair_start_trade_date="2026-08-27",
        repair_end_trade_date="2026-08-28",
        selected_partition_count=2,
        repair_required_code_count=1,
        repair_required_codes_hash="a" * 64,
        source_upstream_batch_id="batch",
    )
    assert not mismatch.ready

    mismatch_overrides = (
        {"repair_start_trade_date": "2026-08-26"},
        {"formula_version": "stock-daily-trend-channel-v2"},
        {"rewritten_indicator_row_count": 9},
        {"rewritten_state_row_count": -1},
    )
    for overrides in mismatch_overrides:
        records[
            RESULT_REPAIR_COMPLETION_CHECK_NAME
        ].evaluation.metadata = _completion_metadata()
        records[
            STATE_REPAIR_COMPLETION_CHECK_NAME
        ].evaluation.metadata = _completion_metadata(**overrides)
        rejected = gold_stock_daily_trend_channel_repair_completion_status(
            object(),
            qfq_factor_repair_trade_date="2026-08-31",
            repair_start_trade_date="2026-08-27",
            repair_end_trade_date="2026-08-28",
            selected_partition_count=2,
            repair_required_code_count=1,
            repair_required_codes_hash="a" * 64,
            source_upstream_batch_id="batch",
        )
        assert not rejected.ready

    records.pop(STATE_REPAIR_COMPLETION_CHECK_NAME)
    missing = gold_stock_daily_trend_channel_repair_completion_status(
        object(),
        qfq_factor_repair_trade_date="2026-08-31",
        repair_start_trade_date="2026-08-27",
        repair_end_trade_date="2026-08-28",
        selected_partition_count=2,
        repair_required_code_count=1,
        repair_required_codes_hash="a" * 64,
        source_upstream_batch_id="batch",
    )
    assert not missing.ready


def test_guard_asset_and_check_names_are_frozen() -> None:
    assert RESULT_ASSET_KEY.to_user_string() == "gold_stock_daily_trend_channel"
    assert STATE_ASSET_KEY.to_user_string() == "gold_stock_daily_trend_channel_state"
    assert RESULT_REPAIR_COMPLETION_CHECK_NAME.endswith(
        "factor_repair_completion_check"
    )
    assert STATE_REPAIR_COMPLETION_CHECK_NAME.endswith(
        "state_factor_repair_completion_check"
    )
