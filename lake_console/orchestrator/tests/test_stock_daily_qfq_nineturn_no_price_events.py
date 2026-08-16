from __future__ import annotations

import hashlib
import io
import json
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import dagster as dg
import duckdb
import pytest

from orchestrator.defs.bootstrap.stock_daily_qfq_nineturn_no_price_events import (
    EVENT_REVISION,
    MAX_CHECK_EVENTS,
    MAX_MATERIALIZATION_EVENTS,
    StockDailyQfqNineTurnNoPriceEventError,
    apply_stock_daily_qfq_nineturn_no_price_events,
    load_stock_daily_qfq_nineturn_no_price_event_plan,
    plan_stock_daily_qfq_nineturn_no_price_events,
)
from orchestrator.defs.bootstrap.stock_daily_qfq_nineturn_no_price_history import (
    audit_stock_daily_qfq_nineturn_no_price_candidates,
    audit_stock_daily_qfq_nineturn_no_price_formal,
    build_stock_daily_qfq_nineturn_no_price_candidates,
    plan_stock_daily_qfq_nineturn_no_price_history,
    promote_stock_daily_qfq_nineturn_no_price_candidates,
)
from orchestrator.defs.bootstrap import (
    stock_daily_qfq_nineturn_no_price_serving_events as serving_events,
)
from orchestrator.defs.partitions import cn_a_stock_trade_days
from orchestrator.defs.prod_db.stock_daily_qfq_nineturn import (
    PROD_CORE_STOCK_DAILY_QFQ_NINETURN_CONSTRAINTS,
    PROD_CORE_STOCK_DAILY_QFQ_NINETURN_INDEXES,
    PROD_CORE_STOCK_DAILY_QFQ_NINETURN_LEGACY_CONSTRAINTS,
    PROD_CORE_STOCK_DAILY_QFQ_NINETURN_NO_PRICE_MIGRATION,
    PROD_CORE_STOCK_DAILY_QFQ_NINETURN_PREVIOUS_MIGRATION,
    ProdCoreStockDailyQfqNineTurnCheckpointAudit,
    ProdCoreStockDailyQfqNineTurnContractSnapshot,
)
from orchestrator.defs.resources import DuckDBResource


def test_d4_plan_binds_d3_identity_and_plans_only_daily_events(
    tmp_path: Path,
) -> None:
    lake_root, lake_plan, formal_audit_path, dates = _promoted_d3_fixture(tmp_path)
    with dg.instance_for_test() as instance:
        instance.add_dynamic_partitions(cn_a_stock_trade_days.name, list(dates))

        plan = _event_plan(
            instance,
            lake_root=lake_root,
            lake_plan=lake_plan,
            formal_audit_path=formal_audit_path,
            output_dir=tmp_path / "event-reports",
        )

        assert plan.should_stop is False
        assert plan.planned_materialization_event_count == len(dates)
        assert plan.planned_check_event_count == 20
        assert {item.partition_key for item in plan.partitions} == set(dates)
        assert {item.event_type for item in plan.candidates} == {
            "materialization",
            "check",
        }
        assert instance.get_runs_count() == 0
        assert not instance.get_materialized_partitions(
            dg.AssetKey("gold_stock_daily_qfq_nineturn")
        )


def test_d4_apply_appends_exact_events_and_second_plan_is_empty(
    tmp_path: Path,
) -> None:
    lake_root, lake_plan, formal_audit_path, dates = _promoted_d3_fixture(tmp_path)
    output_dir = tmp_path / "event-reports"
    with dg.instance_for_test() as instance:
        instance.add_dynamic_partitions(cn_a_stock_trade_days.name, list(dates))
        plan = _event_plan(
            instance,
            lake_root=lake_root,
            lake_plan=lake_plan,
            formal_audit_path=formal_audit_path,
            output_dir=output_dir,
        )
        loaded = load_stock_daily_qfq_nineturn_no_price_event_plan(plan.report_path)

        report = apply_stock_daily_qfq_nineturn_no_price_events(
            instance=instance,
            plan=loaded,
            expected_plan_fingerprint=loaded.plan_fingerprint,
            confirm_apply=True,
            duckdb_resource=DuckDBResource(),
            output_dir=output_dir,
        )

        assert report.materialization_event_count == len(dates)
        assert report.check_event_count == 20
        assert report.post_plan_event_count == 0
        assert report.current_revision_materialization_count == len(dates)
        assert report.current_revision_check_count == 20
        checks = instance.event_log_storage.get_asset_check_execution_history(
            dg.AssetCheckKey(
                dg.AssetKey("gold_stock_daily_qfq_nineturn"),
                "gold_stock_daily_qfq_nineturn_integrity_check",
            ),
            limit=100,
        )
        assert len(checks) == 20
        assert {record.partition for record in checks} == set(dates[-20:])
        assert all(
            record.evaluation.metadata["goldenshare/event_revision"].value
            == EVENT_REVISION
            for record in checks
        )
        second_plan = _event_plan(
            instance,
            lake_root=lake_root,
            lake_plan=lake_plan,
            formal_audit_path=formal_audit_path,
            output_dir=output_dir,
        )
        assert second_plan.candidates == ()


def test_d4_apply_rejects_file_drift_after_review(tmp_path: Path) -> None:
    lake_root, lake_plan, formal_audit_path, dates = _promoted_d3_fixture(tmp_path)
    output_dir = tmp_path / "event-reports"
    with dg.instance_for_test() as instance:
        instance.add_dynamic_partitions(cn_a_stock_trade_days.name, list(dates))
        plan = _event_plan(
            instance,
            lake_root=lake_root,
            lake_plan=lake_plan,
            formal_audit_path=formal_audit_path,
            output_dir=output_dir,
        )
        target = lake_root / lake_plan.partitions[-1].relative_path
        target.write_bytes(target.read_bytes() + b"drift")

        with pytest.raises(
            StockDailyQfqNineTurnNoPriceEventError,
            match="stale",
        ):
            apply_stock_daily_qfq_nineturn_no_price_events(
                instance=instance,
                plan=plan,
                expected_plan_fingerprint=plan.plan_fingerprint,
                confirm_apply=True,
                duckdb_resource=DuckDBResource(),
                output_dir=output_dir,
            )


def test_d4_plan_fails_closed_for_unregistered_partition(tmp_path: Path) -> None:
    lake_root, lake_plan, formal_audit_path, dates = _promoted_d3_fixture(tmp_path)
    with dg.instance_for_test() as instance:
        instance.add_dynamic_partitions(cn_a_stock_trade_days.name, list(dates[:-1]))

        plan = _event_plan(
            instance,
            lake_root=lake_root,
            lake_plan=lake_plan,
            formal_audit_path=formal_audit_path,
            output_dir=tmp_path / "event-reports",
        )

        assert plan.should_stop is True
        assert "missing_registered_partitions" in plan.stop_reasons


def test_d4_cli_requires_explicit_apply_and_keeps_state_writer_centralized() -> None:
    source_root = (
        Path(__file__).resolve().parents[1] / "src/orchestrator/defs/bootstrap"
    )
    helper_source = (
        source_root / "stock_daily_qfq_nineturn_no_price_events.py"
    ).read_text(encoding="utf-8")
    cli_source = (
        source_root / "stock_daily_qfq_nineturn_no_price_events_cli.py"
    ).read_text(encoding="utf-8")

    assert "--apply" in cli_source
    assert "report_runless_asset_event" not in helper_source
    assert "report_runless_asset_event" not in cli_source
    assert "MAX_CHECK_HISTORY = 500" in helper_source
    assert "get_asset_check_execution_history" in helper_source
    assert MAX_MATERIALIZATION_EVENTS == 4_000
    assert MAX_CHECK_EVENTS == 20


def test_d5_serving_plan_and_apply_bind_contract_content_and_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lake_root, lake_plan, formal_audit_path, dates = _promoted_d3_fixture(tmp_path)
    output_dir = tmp_path / "event-reports"
    baseline = _serving_contract_snapshot(legacy=True, row_count=len(dates))
    post = _serving_contract_snapshot(legacy=False, row_count=len(dates))
    baseline_report = (
        serving_events.capture_stock_daily_qfq_nineturn_serving_contract_snapshot(
            audit_reader=_FakeServingAuditReader(baseline, row_count=len(dates)),
            output_dir=output_dir,
        )
    )
    monkeypatch.setattr(
        serving_events,
        "_writer_sensor_states",
        lambda _instance: {
            name: "STOPPED" for name in serving_events.WRITER_SENSOR_NAMES
        },
    )
    with dg.instance_for_test() as instance:
        instance.add_dynamic_partitions(cn_a_stock_trade_days.name, list(dates))
        d4_plan = _event_plan(
            instance,
            lake_root=lake_root,
            lake_plan=lake_plan,
            formal_audit_path=formal_audit_path,
            output_dir=output_dir,
        )
        apply_stock_daily_qfq_nineturn_no_price_events(
            instance=instance,
            plan=d4_plan,
            expected_plan_fingerprint=d4_plan.plan_fingerprint,
            confirm_apply=True,
            duckdb_resource=DuckDBResource(),
            output_dir=output_dir,
        )
        d4_post_plan = _event_plan(
            instance,
            lake_root=lake_root,
            lake_plan=lake_plan,
            formal_audit_path=formal_audit_path,
            output_dir=output_dir,
        )
        reader = _FakeServingAuditReader(post, row_count=len(dates))
        plan = serving_events.plan_stock_daily_qfq_nineturn_no_price_serving_events(
            instance=instance,
            baseline_snapshot_report_path=baseline_report,
            d4_event_plan_report_path=d4_post_plan.report_path,
            expected_d4_plan_fingerprint=d4_post_plan.plan_fingerprint,
            deployed_revision="a" * 40,
            audit_reader=reader,
            lake_root=lake_root,
            duckdb_resource=DuckDBResource(),
            output_dir=output_dir,
        )

        assert plan.should_stop is False
        assert len(plan.partitions) == len(dates)
        assert sum(
            item.event_type == "materialization" for item in plan.candidates
        ) == len(dates)
        assert sum(item.event_type == "check" for item in plan.candidates) == 20
        report = serving_events.apply_stock_daily_qfq_nineturn_no_price_serving_events(
            instance=instance,
            plan=plan,
            expected_plan_fingerprint=plan.plan_fingerprint,
            confirm_apply=True,
            audit_reader=reader,
            duckdb_resource=DuckDBResource(),
            output_dir=output_dir,
        )

        assert report.materialization_event_count == len(dates)
        assert report.check_event_count == 20
        assert report.post_plan_event_count == 0
        assert report.current_revision_materialization_count == len(dates)
        assert report.current_revision_check_count == 20
        checks = instance.event_log_storage.get_asset_check_execution_history(
            dg.AssetCheckKey(
                dg.AssetKey(serving_events.ASSET_KEY),
                serving_events.CHECK_NAME,
            ),
            limit=100,
        )
        assert len(checks) == 20
        assert all(
            record.evaluation.metadata["goldenshare/event_revision"].value
            == serving_events.EVENT_REVISION
            for record in checks
        )


def test_d5_serving_plan_fails_closed_when_privileges_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lake_root, lake_plan, formal_audit_path, dates = _promoted_d3_fixture(tmp_path)
    output_dir = tmp_path / "event-reports"
    baseline = _serving_contract_snapshot(legacy=True, row_count=len(dates))
    changed = _serving_contract_snapshot(legacy=False, row_count=len(dates))
    changed = ProdCoreStockDailyQfqNineTurnContractSnapshot(
        **{
            **changed.to_dict(),
            "privileges": (("unexpected_role", "SELECT", "NO"),),
        }
    )
    baseline_report = (
        serving_events.capture_stock_daily_qfq_nineturn_serving_contract_snapshot(
            audit_reader=_FakeServingAuditReader(baseline, row_count=len(dates)),
            output_dir=output_dir,
        )
    )
    monkeypatch.setattr(
        serving_events,
        "_writer_sensor_states",
        lambda _instance: {
            name: "STOPPED" for name in serving_events.WRITER_SENSOR_NAMES
        },
    )
    with dg.instance_for_test() as instance:
        instance.add_dynamic_partitions(cn_a_stock_trade_days.name, list(dates))
        d4_plan = _event_plan(
            instance,
            lake_root=lake_root,
            lake_plan=lake_plan,
            formal_audit_path=formal_audit_path,
            output_dir=output_dir,
        )
        apply_stock_daily_qfq_nineturn_no_price_events(
            instance=instance,
            plan=d4_plan,
            expected_plan_fingerprint=d4_plan.plan_fingerprint,
            confirm_apply=True,
            duckdb_resource=DuckDBResource(),
            output_dir=output_dir,
        )
        d4_post_plan = _event_plan(
            instance,
            lake_root=lake_root,
            lake_plan=lake_plan,
            formal_audit_path=formal_audit_path,
            output_dir=output_dir,
        )
        plan = serving_events.plan_stock_daily_qfq_nineturn_no_price_serving_events(
            instance=instance,
            baseline_snapshot_report_path=baseline_report,
            d4_event_plan_report_path=d4_post_plan.report_path,
            expected_d4_plan_fingerprint=d4_post_plan.plan_fingerprint,
            deployed_revision="b" * 40,
            audit_reader=_FakeServingAuditReader(changed, row_count=len(dates)),
            lake_root=lake_root,
            duckdb_resource=DuckDBResource(),
            output_dir=output_dir,
        )

        assert plan.should_stop is True
        assert "prod_privileges_changed" in plan.stop_reasons


def test_d5_prod_reader_uses_only_psql_remote_and_streams_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = tmp_path / "scripts/psql-remote.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    snapshot_payload = {
        "transaction_read_only": "on",
        **_serving_contract_snapshot(legacy=True, row_count=1).to_dict(),
    }
    run_commands: list[list[str]] = []

    def fake_run(command, **_kwargs):
        run_commands.append(command)
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(snapshot_payload),
            stderr="",
        )

    popen_commands: list[list[str]] = []

    class FakeProcess:
        def __init__(self) -> None:
            self.stdout = io.StringIO("000001.SZ,2026-07-01,1,0,\\N,\\N,1\n")
            self.stderr = io.StringIO("")

        def wait(self) -> int:
            return 0

        def kill(self) -> None:
            raise AssertionError("valid stream must not be killed")

    def fake_popen(command, **_kwargs):
        popen_commands.append(command)
        return FakeProcess()

    monkeypatch.setattr(serving_events.subprocess, "run", fake_run)
    monkeypatch.setattr(serving_events.subprocess, "Popen", fake_popen)
    reader = serving_events.PsqlRemoteStockDailyQfqNineTurnServingAuditReader(
        repo_root=tmp_path
    )

    snapshot = reader.snapshot()
    expected_hash = hashlib.sha256(b"000001.SZ\t2026-07-01\t1\t0\t\t\t1").hexdigest()
    checkpoint = reader.checkpoint(
        expected_content_hashes={"2026-07-01": expected_hash}
    )

    assert snapshot.migration_versions == (
        PROD_CORE_STOCK_DAILY_QFQ_NINETURN_PREVIOUS_MIGRATION,
    )
    assert checkpoint.passed is True
    assert checkpoint.read_back_row_count == 1
    assert run_commands[0][:2] == ["bash", str(script.resolve())]
    assert popen_commands[0][:2] == ["bash", str(script.resolve())]
    assert "BEGIN READ ONLY" in run_commands[0][3]
    assert "BEGIN READ ONLY" in popen_commands[0][3]


def _event_plan(
    instance: dg.DagsterInstance,
    *,
    lake_root: Path,
    lake_plan,
    formal_audit_path: Path,
    output_dir: Path,
):
    return plan_stock_daily_qfq_nineturn_no_price_events(
        instance=instance,
        lake_plan_report_path=lake_plan.report_path,
        formal_audit_report_path=formal_audit_path,
        expected_lake_plan_hash=lake_plan.plan_hash,
        expected_partition_count=len(lake_plan.partitions),
        expected_row_count=sum(item.row_count for item in lake_plan.partitions),
        lake_root=lake_root,
        duckdb_resource=DuckDBResource(),
        output_dir=output_dir,
    )


def _promoted_d3_fixture(tmp_path: Path):
    lake_root = tmp_path / "data_lake"
    staging_root = tmp_path / "data_lake_staging"
    lake_root.mkdir()
    staging_root.mkdir()
    dates = tuple(
        (date(2026, 7, 1) + timedelta(days=offset)).isoformat() for offset in range(21)
    )
    with duckdb.connect() as connection:
        for partition_key in dates:
            target = (
                lake_root
                / "gold/indicator/stock_daily_qfq_nineturn"
                / f"trade_date={partition_key}"
                / "part-000.parquet"
            )
            source = (
                lake_root
                / "gold/quote/stock_daily_qfq"
                / f"trade_date={partition_key}"
                / "part-000.parquet"
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            source.parent.mkdir(parents=True, exist_ok=True)
            connection.execute(
                f"""
                COPY (
                  SELECT '000001.SZ'::VARCHAR AS ts_code,
                    DATE '{partition_key}' AS trade_date,
                    10.0::DOUBLE AS close_qfq,
                    1::INTEGER AS up_count,
                    0::INTEGER AS down_count,
                    NULL::VARCHAR AS nine_up_turn,
                    NULL::VARCHAR AS nine_down_turn
                ) TO '{target.as_posix()}' (FORMAT PARQUET)
                """
            )
            connection.execute(
                f"""
                COPY (
                  SELECT '000001.SZ'::VARCHAR AS ts_code,
                    DATE '{partition_key}' AS trade_date
                ) TO '{source.as_posix()}' (FORMAT PARQUET)
                """
            )
    resource = DuckDBResource()
    lake_plan = plan_stock_daily_qfq_nineturn_no_price_history(
        lake_root=lake_root,
        staging_root=staging_root,
        duckdb_resource=resource,
        writer_stopped=True,
        output_dir=tmp_path / "d3-reports",
    )
    build_stock_daily_qfq_nineturn_no_price_candidates(
        plan=lake_plan,
        expected_plan_hash=lake_plan.plan_hash,
        duckdb_resource=resource,
        mode="full",
        confirm_build=True,
    )
    candidate_audit = audit_stock_daily_qfq_nineturn_no_price_candidates(
        plan=lake_plan,
        expected_plan_hash=lake_plan.plan_hash,
        duckdb_resource=resource,
        mode="full",
    )
    promote_stock_daily_qfq_nineturn_no_price_candidates(
        plan=lake_plan,
        expected_plan_hash=lake_plan.plan_hash,
        audit_report_path=Path(str(candidate_audit["report_path"])),
        writer_stopped=True,
        reader_stopped=True,
        confirm_promote=True,
    )
    formal_audit = audit_stock_daily_qfq_nineturn_no_price_formal(
        plan=lake_plan,
        expected_plan_hash=lake_plan.plan_hash,
        candidate_audit_report_path=Path(str(candidate_audit["report_path"])),
        duckdb_resource=resource,
    )
    return (
        lake_root,
        lake_plan,
        Path(str(formal_audit["report_path"])),
        dates,
    )


class _FakeServingAuditReader:
    def __init__(
        self,
        snapshot: ProdCoreStockDailyQfqNineTurnContractSnapshot,
        *,
        row_count: int,
    ) -> None:
        self._snapshot = snapshot
        self._row_count = row_count

    def snapshot(self) -> ProdCoreStockDailyQfqNineTurnContractSnapshot:
        return self._snapshot

    def checkpoint(
        self,
        *,
        expected_content_hashes,
    ) -> ProdCoreStockDailyQfqNineTurnCheckpointAudit:
        return ProdCoreStockDailyQfqNineTurnCheckpointAudit(
            passed=True,
            expected_partition_count=len(expected_content_hashes),
            observed_partition_count=len(expected_content_hashes),
            read_back_row_count=self._row_count,
            failed_partition_keys=(),
        )


def _serving_contract_snapshot(
    *,
    legacy: bool,
    row_count: int,
) -> ProdCoreStockDailyQfqNineTurnContractSnapshot:
    type_by_column = {
        "ts_code": ("character varying", "varchar", "NO", None),
        "trade_date": ("date", "date", "NO", None),
        "close_qfq": ("double precision", "float8", "NO", None),
        "up_count": ("integer", "int4", "NO", None),
        "down_count": ("integer", "int4", "NO", None),
        "nine_up_turn": ("character varying", "varchar", "YES", None),
        "nine_down_turn": ("character varying", "varchar", "YES", None),
        "formula_version": ("smallint", "int2", "NO", None),
        "published_at": ("timestamp with time zone", "timestamptz", "NO", None),
    }
    columns = (
        (
            "ts_code",
            "trade_date",
            "close_qfq",
            "up_count",
            "down_count",
            "nine_up_turn",
            "nine_down_turn",
            "formula_version",
            "published_at",
        )
        if legacy
        else (
            "ts_code",
            "trade_date",
            "up_count",
            "down_count",
            "nine_up_turn",
            "nine_down_turn",
            "formula_version",
            "published_at",
        )
    )
    return ProdCoreStockDailyQfqNineTurnContractSnapshot(
        migration_versions=(
            PROD_CORE_STOCK_DAILY_QFQ_NINETURN_PREVIOUS_MIGRATION
            if legacy
            else PROD_CORE_STOCK_DAILY_QFQ_NINETURN_NO_PRICE_MIGRATION,
        ),
        columns=tuple((name, *type_by_column[name]) for name in columns),
        constraints=(
            PROD_CORE_STOCK_DAILY_QFQ_NINETURN_LEGACY_CONSTRAINTS
            if legacy
            else PROD_CORE_STOCK_DAILY_QFQ_NINETURN_CONSTRAINTS
        ),
        indexes=PROD_CORE_STOCK_DAILY_QFQ_NINETURN_INDEXES,
        privileges=(("lake_raw_writer", "SELECT", "NO"),),
        table_owner="goldenshare_user",
        row_count=row_count,
        partition_count=row_count,
        first_trade_date="2026-07-01",
        last_trade_date="2026-07-21",
    )
