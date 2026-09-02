import hashlib
import inspect
import os
from dataclasses import dataclass
from pathlib import Path

import dagster as dg
import duckdb
import pytest

from orchestrator.defs.bootstrap.stock_daily_trend_channel_history import (
    StockDailyTrendChannelHistoryError,
    audit_stock_daily_trend_channel_history_candidates,
    final_audit_stock_daily_trend_channel_history,
    generate_stock_daily_trend_channel_history,
    load_stock_daily_trend_channel_history_plan,
    plan_stock_daily_trend_channel_history,
    promote_stock_daily_trend_channel_history,
)
from orchestrator.defs.bootstrap.stock_daily_trend_channel_history_cli import (
    _parser as history_parser,
)
from orchestrator.defs.bootstrap.stock_daily_trend_channel_runless_events import (
    StockDailyTrendChannelRunlessEventError,
    final_audit_stock_daily_trend_channel_runless_events,
    plan_stock_daily_trend_channel_runless_events,
    report_stock_daily_trend_channel_runless_events,
    write_stock_daily_trend_channel_runless_event_report,
)
from orchestrator.defs.duckdb_connection import DuckDBConnectionSettings
from orchestrator.defs.paths import (
    gold_stock_daily_qfq_path,
    gold_stock_daily_trend_channel_path,
    gold_stock_daily_trend_channel_state_path,
    silver_stock_lifecycle_path,
)
from tests.test_stock_daily_trend_channel_m3 import (
    _rows,
    _write_day,
    _write_lifecycle,
    _write_qfq,
)

DATES = ("2026-08-27", "2026-08-28", "2026-08-31")
CODE_A = "000001.SZ"
CODE_B = "600000.SH"
DELISTED_CODE = "000003.SZ"
LIFECYCLE = [
    (CODE_A, "1991-01-01", None),
    (CODE_B, "1999-01-01", None),
    (DELISTED_CODE, "2000-01-01", "2026-08-28"),
]
QFQ_ROWS = {
    DATES[0]: [
        (CODE_A, 10.0, 11.0, 9.0, 10.5),
        (CODE_B, 20.0, 21.0, 19.0, 20.5),
        (DELISTED_CODE, 5.0, 5.5, 4.5, 5.2),
    ],
    DATES[1]: [(CODE_B, 20.5, 21.5, 19.5, 21.0)],
    DATES[2]: [
        (CODE_A, 11.0, 12.0, 10.0, 11.5),
        (CODE_B, 21.0, 22.0, 20.0, 21.5),
    ],
}


@dataclass(frozen=True)
class _BuiltHistory:
    root: Path
    staging: Path
    reports: Path
    settings: DuckDBConnectionSettings
    plan: object
    checkpoint: Path
    audit_path: Path
    audit_report: dict[str, object]
    promote_path: Path
    promote_report: dict[str, object]
    final_path: Path
    final_report: dict[str, object]


def _settings(tmp_path: Path) -> DuckDBConnectionSettings:
    return DuckDBConnectionSettings(temp_directory=tmp_path / "duckdb-spill")


def _write_inputs(root: Path) -> None:
    connection = duckdb.connect()
    try:
        for trade_date in DATES:
            _write_qfq(
                connection,
                gold_stock_daily_qfq_path(root, trade_date),
                trade_date,
                QFQ_ROWS[trade_date],
            )
        _write_lifecycle(
            connection,
            silver_stock_lifecycle_path(root),
            LIFECYCLE,
        )
    finally:
        connection.close()


def _plan(tmp_path: Path):
    root = tmp_path / "lake"
    staging = tmp_path / "staging"
    reports = tmp_path / "reports"
    staging.mkdir(parents=True)
    _write_inputs(root)
    settings = _settings(tmp_path)
    plan = plan_stock_daily_trend_channel_history(
        lake_root=root,
        staging_root=staging,
        output_dir=reports,
        duckdb_settings=settings,
    )
    return root, staging, reports, settings, plan


def _build_history(tmp_path: Path) -> _BuiltHistory:
    root, staging, reports, settings, plan = _plan(tmp_path)
    checkpoint = staging / "control" / "history-checkpoint.json"
    generate = generate_stock_daily_trend_channel_history(
        plan=plan,
        expected_plan_id=plan.plan_id,
        expected_plan_hash=plan.plan_hash,
        expected_start_date=DATES[0],
        expected_end_date=DATES[-1],
        checkpoint_path=checkpoint,
        dry_run=False,
        confirm_write=True,
        segment_count_limit=1,
        duckdb_settings=settings,
    )
    assert generate["completed_segment_count"] == 1
    audit_path = reports / "candidate-audit.json"
    audit_report = audit_stock_daily_trend_channel_history_candidates(
        plan=plan,
        expected_plan_id=plan.plan_id,
        expected_plan_hash=plan.plan_hash,
        expected_start_date=DATES[0],
        expected_end_date=DATES[-1],
        checkpoint_path=checkpoint,
        output_path=audit_path,
        duckdb_settings=settings,
    )
    promote_path = reports / "promote.json"
    promote_report = promote_stock_daily_trend_channel_history(
        plan=plan,
        expected_plan_id=plan.plan_id,
        expected_plan_hash=plan.plan_hash,
        expected_start_date=DATES[0],
        expected_end_date=DATES[-1],
        audit_report_path=audit_path,
        expected_audit_hash=str(audit_report["audit_hash"]),
        promotion_checkpoint_path=staging / "control" / "promotion.json",
        output_path=promote_path,
        dry_run=False,
        confirm_write=True,
    )
    final_path = reports / "final-audit.json"
    final_report = final_audit_stock_daily_trend_channel_history(
        plan=plan,
        expected_plan_id=plan.plan_id,
        expected_plan_hash=plan.plan_hash,
        expected_start_date=DATES[0],
        expected_end_date=DATES[-1],
        promote_report_path=promote_path,
        expected_promote_hash=str(promote_report["promote_hash"]),
        output_path=final_path,
        duckdb_settings=settings,
    )
    return _BuiltHistory(
        root=root,
        staging=staging,
        reports=reports,
        settings=settings,
        plan=plan,
        checkpoint=checkpoint,
        audit_path=audit_path,
        audit_report=audit_report,
        promote_path=promote_path,
        promote_report=promote_report,
        final_path=final_path,
        final_report=final_report,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_state_rows_equal(
    actual_rows: list[tuple],
    expected_rows: list[tuple],
) -> None:
    assert len(actual_rows) == len(expected_rows)
    raw_value_indexes = (4, 5, 7, 8)
    exact_value_indexes = tuple(
        index for index in range(12) if index not in raw_value_indexes
    )
    for actual, expected in zip(actual_rows, expected_rows, strict=True):
        for index in raw_value_indexes:
            assert actual[index] == pytest.approx(expected[index], abs=1e-10)
        assert tuple(actual[index] for index in exact_value_indexes) == tuple(
            expected[index] for index in exact_value_indexes
        )


def test_history_plan_covers_all_qfq_dates_and_delisted_codes(tmp_path: Path) -> None:
    root, staging, _, _, plan = _plan(tmp_path)

    assert not plan.should_stop
    assert plan.trade_dates == DATES
    assert plan.report["qfq_partition_count"] == 3
    assert plan.report["qfq_row_count"] == 6
    assert plan.report["distinct_ts_code_count"] == 3
    assert plan.report["delisted_history_code_count"] == 1
    assert plan.report["lifecycle_missing_code_count"] == 0
    assert plan.report["estimated_materialization_event_count"] == 6
    assert plan.report["estimated_check_event_count"] == 9
    assert not any(
        gold_stock_daily_trend_channel_path(root, trade_date).exists()
        for trade_date in DATES
    )
    loaded = load_stock_daily_trend_channel_history_plan(plan.report_path)
    assert loaded.plan_hash == plan.plan_hash
    assert loaded.staging_root == staging.resolve()


def test_history_plan_stops_on_missing_lifecycle_coverage(tmp_path: Path) -> None:
    root, staging, reports, settings, _ = _plan(tmp_path)
    connection = duckdb.connect()
    try:
        _write_lifecycle(
            connection,
            silver_stock_lifecycle_path(root),
            LIFECYCLE[:-1],
        )
    finally:
        connection.close()

    plan = plan_stock_daily_trend_channel_history(
        lake_root=root,
        staging_root=staging,
        output_dir=reports,
        duckdb_settings=settings,
    )

    assert plan.should_stop
    assert "qfq_code_missing_lifecycle" in plan.stop_reasons
    assert plan.report["lifecycle_missing_code_count"] == 1


def test_generate_dry_run_writes_no_checkpoint_or_candidates(tmp_path: Path) -> None:
    _, staging, _, _, plan = _plan(tmp_path)
    checkpoint = staging / "control" / "history.json"

    report = generate_stock_daily_trend_channel_history(
        plan=plan,
        expected_plan_id=plan.plan_id,
        expected_plan_hash=plan.plan_hash,
        expected_start_date=DATES[0],
        expected_end_date=DATES[-1],
        checkpoint_path=checkpoint,
    )

    assert report["mode"] == "dry-run"
    assert not checkpoint.exists()
    assert not (staging / "gold").exists()


def test_history_candidates_match_daily_recompute_and_carry_state(
    tmp_path: Path,
) -> None:
    built = _build_history(tmp_path)
    expected_root = tmp_path / "expected"
    expected_staging = tmp_path / "expected-staging"
    connection = duckdb.connect()
    try:
        for index, trade_date in enumerate(DATES):
            _write_day(
                connection=connection,
                root=expected_root,
                staging_root=expected_staging,
                run_id=f"expected-{index}",
                trade_date=trade_date,
                qfq_rows=QFQ_ROWS[trade_date],
                lifecycle_rows=LIFECYCLE,
                previous_trade_date=DATES[index - 1] if index else None,
            )
        for trade_date in DATES:
            assert _rows(
                connection,
                gold_stock_daily_trend_channel_path(built.root, trade_date),
            ) == _rows(
                connection,
                gold_stock_daily_trend_channel_path(expected_root, trade_date),
            )
            _assert_state_rows_equal(
                _rows(
                    connection,
                    gold_stock_daily_trend_channel_state_path(
                        built.root,
                        trade_date,
                    ),
                ),
                _rows(
                    connection,
                    gold_stock_daily_trend_channel_state_path(
                        expected_root,
                        trade_date,
                    ),
                ),
            )
        carried = next(
            row
            for row in _rows(
                connection,
                gold_stock_daily_trend_channel_state_path(built.root, DATES[1]),
            )
            if row[0] == CODE_A
        )
        assert carried[2].isoformat() == DATES[0]
        assert carried[3] is False
    finally:
        connection.close()
    assert built.final_report["formal_partition_count"] == 3
    assert built.final_report["should_stop"] is False


def test_untrusted_candidate_is_recomputed_from_checkpoint(tmp_path: Path) -> None:
    _, staging, _, settings, plan = _plan(tmp_path)
    checkpoint = staging / "control" / "history.json"
    kwargs = {
        "plan": plan,
        "expected_plan_id": plan.plan_id,
        "expected_plan_hash": plan.plan_hash,
        "expected_start_date": DATES[0],
        "expected_end_date": DATES[-1],
        "checkpoint_path": checkpoint,
        "dry_run": False,
        "confirm_write": True,
        "segment_count_limit": 1,
        "duckdb_settings": settings,
    }
    generate_stock_daily_trend_channel_history(**kwargs)
    payload = __import__("json").loads(checkpoint.read_text())
    candidate = Path(payload["completed_segments"]["1"]["files"][0]["candidate_path"])
    trusted_sha = payload["completed_segments"]["1"]["files"][0]["sha256"]
    candidate.write_bytes(b"corrupt")

    rerun = generate_stock_daily_trend_channel_history(**kwargs)

    assert rerun["processed_segment_count"] == 1
    assert _sha256(candidate) == trusted_sha


def test_promotion_interruption_resumes_idempotently(tmp_path: Path) -> None:
    root, staging, reports, settings, plan = _plan(tmp_path)
    checkpoint = staging / "control" / "history.json"
    generate_stock_daily_trend_channel_history(
        plan=plan,
        expected_plan_id=plan.plan_id,
        expected_plan_hash=plan.plan_hash,
        expected_start_date=DATES[0],
        expected_end_date=DATES[-1],
        checkpoint_path=checkpoint,
        dry_run=False,
        confirm_write=True,
        segment_count_limit=1,
        duckdb_settings=settings,
    )
    audit_path = reports / "audit.json"
    audit = audit_stock_daily_trend_channel_history_candidates(
        plan=plan,
        expected_plan_id=plan.plan_id,
        expected_plan_hash=plan.plan_hash,
        expected_start_date=DATES[0],
        expected_end_date=DATES[-1],
        checkpoint_path=checkpoint,
        output_path=audit_path,
        duckdb_settings=settings,
    )
    replacements = 0

    def fail_after_one_date(source: Path, target: Path) -> None:
        nonlocal replacements
        replacements += 1
        if replacements == 3:
            raise OSError("simulated interruption")
        os.replace(source, target)

    promote_kwargs = {
        "plan": plan,
        "expected_plan_id": plan.plan_id,
        "expected_plan_hash": plan.plan_hash,
        "expected_start_date": DATES[0],
        "expected_end_date": DATES[-1],
        "audit_report_path": audit_path,
        "expected_audit_hash": str(audit["audit_hash"]),
        "promotion_checkpoint_path": staging / "control" / "promote.json",
        "output_path": reports / "promote.json",
        "dry_run": False,
        "confirm_write": True,
    }
    with pytest.raises(OSError, match="simulated interruption"):
        promote_stock_daily_trend_channel_history(
            **promote_kwargs,
            replace_file=fail_after_one_date,
        )
    assert gold_stock_daily_trend_channel_path(root, DATES[0]).is_file()
    assert gold_stock_daily_trend_channel_state_path(root, DATES[0]).is_file()

    report = promote_stock_daily_trend_channel_history(**promote_kwargs)
    assert report["promoted_partition_count"] == 3
    assert report["formal_file_count"] == 6


def _event_kwargs(built: _BuiltHistory, instance: object) -> dict[str, object]:
    return {
        "instance": instance,
        "plan_report_path": built.plan.report_path,
        "expected_plan_id": built.plan.plan_id,
        "expected_plan_hash": built.plan.plan_hash,
        "promote_report_path": built.promote_path,
        "expected_promote_hash": str(built.promote_report["promote_hash"]),
        "final_audit_report_path": built.final_path,
        "expected_final_audit_hash": str(built.final_report["final_audit_hash"]),
    }


def test_runless_events_are_bounded_registered_and_bound_to_materializations(
    tmp_path: Path,
) -> None:
    built = _build_history(tmp_path)
    with dg.DagsterInstance.ephemeral() as instance:
        kwargs = _event_kwargs(built, instance)
        dry_run = plan_stock_daily_trend_channel_runless_events(**kwargs)
        assert dry_run.planned_registration_count == 3
        assert dry_run.planned_materialization_count == 6
        assert dry_run.planned_check_count == 9
        assert not dry_run.should_stop

        sample = report_stock_daily_trend_channel_runless_events(
            **kwargs,
            dry_run=False,
            confirm_event_write=True,
            sample_only=True,
            sample_trade_date=DATES[-1],
        )
        assert sample.registered_partition_count == 1
        assert sample.reported_materialization_count == 2
        assert sample.reported_check_count == 3

        applied = report_stock_daily_trend_channel_runless_events(
            **kwargs,
            dry_run=False,
            confirm_event_write=True,
            checkpoint_path=tmp_path / "event-checkpoint.json",
        )
        assert applied.registered_partition_count == 2
        assert applied.reported_materialization_count == 4
        assert applied.reported_check_count == 6
        final = final_audit_stock_daily_trend_channel_runless_events(**kwargs)
        assert final.planned_registration_count == 0
        assert final.planned_materialization_count == 0
        assert final.planned_check_count == 0


class _FailingEventInstance:
    def __init__(self, instance: object) -> None:
        self._instance = instance
        self._reported = 0

    def __getattr__(self, name: str):
        return getattr(self._instance, name)

    def report_runless_asset_event(self, event: object) -> None:
        self._reported += 1
        if self._reported == 2:
            raise RuntimeError("simulated event failure")
        self._instance.report_runless_asset_event(event)


def test_event_failure_never_modifies_formal_files(tmp_path: Path) -> None:
    built = _build_history(tmp_path)
    before = {
        path: _sha256(path)
        for trade_date in DATES
        for path in (
            gold_stock_daily_trend_channel_path(built.root, trade_date),
            gold_stock_daily_trend_channel_state_path(built.root, trade_date),
        )
    }
    with dg.DagsterInstance.ephemeral() as instance:
        failing = _FailingEventInstance(instance)
        with pytest.raises(RuntimeError, match="simulated event failure"):
            report_stock_daily_trend_channel_runless_events(
                **_event_kwargs(built, failing),
                dry_run=False,
                confirm_event_write=True,
                sample_only=True,
                sample_trade_date=DATES[-1],
            )
    assert {path: _sha256(path) for path in before} == before


def test_event_control_files_cannot_enter_lake_or_candidate_staging(
    tmp_path: Path,
) -> None:
    built = _build_history(tmp_path)
    with dg.DagsterInstance.ephemeral() as instance:
        kwargs = _event_kwargs(built, instance)
        plan = plan_stock_daily_trend_channel_runless_events(**kwargs)
        with pytest.raises(
            StockDailyTrendChannelRunlessEventError,
            match="outside formal Lake",
        ):
            write_stock_daily_trend_channel_runless_event_report(
                plan,
                built.root / "event-report.json",
            )
        with pytest.raises(
            StockDailyTrendChannelRunlessEventError,
            match="outside candidate staging",
        ):
            report_stock_daily_trend_channel_runless_events(
                **kwargs,
                dry_run=False,
                confirm_event_write=True,
                checkpoint_path=built.staging / "event-checkpoint.json",
            )


def test_cli_and_static_gates_keep_physical_and_event_writes_separate() -> None:
    commands = history_parser()._subparsers._group_actions[0].choices
    assert set(commands) == {
        "plan",
        "sample",
        "benchmark",
        "generate",
        "audit-files",
        "promote",
        "final-audit",
    }
    history_source = inspect.getsource(
        __import__(
            "orchestrator.defs.bootstrap.stock_daily_trend_channel_history",
            fromlist=["dummy"],
        )
    )
    event_source = inspect.getsource(
        __import__(
            "orchestrator.defs.bootstrap.stock_daily_trend_channel_runless_events",
            fromlist=["dummy"],
        )
    )
    assert "report_runless_asset_event" not in history_source
    assert "gold_stock_daily_trend_channel_staging_path" not in event_source
    assert "duckdb.connect(" not in history_source
    assert "kopia" not in history_source.lower()
    assert "kopia" not in event_source.lower()


def test_wrong_plan_identity_and_event_confirmation_fail_closed(
    tmp_path: Path,
) -> None:
    _, staging, _, _, plan = _plan(tmp_path)
    with pytest.raises(StockDailyTrendChannelHistoryError, match="identity"):
        generate_stock_daily_trend_channel_history(
            plan=plan,
            expected_plan_id="wrong",
            expected_plan_hash=plan.plan_hash,
            expected_start_date=DATES[0],
            expected_end_date=DATES[-1],
            checkpoint_path=staging / "control" / "history.json",
        )
    built = _build_history(tmp_path / "events")
    with (
        dg.DagsterInstance.ephemeral() as instance,
        pytest.raises(
            StockDailyTrendChannelRunlessEventError,
            match="confirm_event_write",
        ),
    ):
        report_stock_daily_trend_channel_runless_events(
            **_event_kwargs(built, instance),
            dry_run=False,
            confirm_event_write=False,
        )
