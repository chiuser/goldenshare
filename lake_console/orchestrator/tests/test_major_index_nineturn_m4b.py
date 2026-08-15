from __future__ import annotations

import inspect
import json
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import dagster as dg
import duckdb
import pytest

from orchestrator.definitions import defs as project_defs
from orchestrator.defs import major_index_nineturn_integrity
from orchestrator.defs.assets.major_index_nineturn import (
    GOLD_MAJOR_INDEX_MINS_NINETURN_ASSETS,
    GOLD_MAJOR_INDEX_NINETURN_ASSETS,
    gold_major_index_daily_nineturn,
)
from orchestrator.defs.bootstrap import major_index_daily_nineturn_serving_history
from orchestrator.defs.bootstrap.major_index_daily_nineturn_serving_history import (
    load_major_index_daily_nineturn_serving_plan,
    plan_major_index_daily_nineturn_serving_history,
    publish_major_index_daily_nineturn_serving_history,
)
from orchestrator.defs.bootstrap.major_index_nineturn_events import (
    MajorIndexNineturnEventError,
    plan_major_index_nineturn_events,
    post_audit_major_index_nineturn_events,
    report_major_index_nineturn_events,
)
from orchestrator.defs.bootstrap.major_index_nineturn_history import (
    MajorIndexNineturnHistoryError,
    build_major_index_nineturn_history,
    load_major_index_nineturn_history_plan,
    plan_major_index_nineturn_history,
)
from orchestrator.defs.bootstrap.major_index_nineturn_history_audit import (
    audit_major_index_nineturn_history,
)
from orchestrator.defs.catalog.lake_assets import get_lake_asset_catalog_entry
from orchestrator.defs.checks.major_index_nineturn_checks import (
    GOLD_MAJOR_INDEX_NINETURN_CHECKS,
)
from orchestrator.defs.jobs.major_index_nineturn_update import (
    gold_major_index_daily_nineturn_update_job,
    gold_major_index_mins_nineturn_update_job,
)
from orchestrator.defs.major_index_nineturn import (
    build_gold_major_index_daily_nineturn_select_sql,
    build_gold_major_index_mins_nineturn_select_sql,
    write_gold_major_index_daily_nineturn_partition,
    write_gold_major_index_mins_nineturn_partition,
)
from orchestrator.defs.major_index_nineturn_integrity import (
    audit_major_index_nineturn_integrity,
)
from orchestrator.defs.partitions import (
    cn_a_index_trade_days,
    cn_major_index_mins_trade_days,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.major_index_nineturn import (
    MAJOR_INDEX_NINETURN_ASSET_KEYS,
    MAJOR_INDEX_NINETURN_HISTORY_BATCH_TRADE_DAYS,
    MAJOR_INDEX_NINETURN_MINUTE_FREQS,
)
from orchestrator.defs.sensors.major_index_nineturn_sensor import (
    gold_major_index_daily_nineturn_update_job_sensor,
    gold_major_index_mins_nineturn_update_job_sensor,
)


def test_exactly_seven_gold_assets_and_checks_are_discoverable() -> None:
    assert len(GOLD_MAJOR_INDEX_NINETURN_ASSETS) == 7
    assert len(GOLD_MAJOR_INDEX_NINETURN_CHECKS) == 7
    assert (
        tuple(asset.key.to_user_string() for asset in GOLD_MAJOR_INDEX_NINETURN_ASSETS)
        == MAJOR_INDEX_NINETURN_ASSET_KEYS
    )
    assert all("_1m" not in key for key in MAJOR_INDEX_NINETURN_ASSET_KEYS)

    definitions = project_defs()
    dg.Definitions.validate_loadable(definitions)
    graph = definitions.resolve_asset_graph()
    actual_assets = {
        key.to_user_string()
        for key in graph.get_all_asset_keys()
        if key.to_user_string() in MAJOR_INDEX_NINETURN_ASSET_KEYS
    }
    actual_checks = {
        key
        for key in graph.asset_check_keys
        if key.asset_key.to_user_string() in MAJOR_INDEX_NINETURN_ASSET_KEYS
    }
    assert actual_assets == set(MAJOR_INDEX_NINETURN_ASSET_KEYS)
    assert len(actual_checks) == 7
    assert all(
        graph.get(check.asset_key).partitions_def is not None for check in actual_checks
    )


def test_assets_consume_only_frozen_gold_upstreams_and_catalog_checks() -> None:
    assert gold_major_index_daily_nineturn.partitions_def is cn_a_index_trade_days
    daily_dependencies = {
        key.to_user_string()
        for key in gold_major_index_daily_nineturn.asset_deps[
            gold_major_index_daily_nineturn.key
        ]
    }
    assert daily_dependencies == {"gold_market_major_indices_daily"}

    for freq, asset in zip(
        MAJOR_INDEX_NINETURN_MINUTE_FREQS,
        GOLD_MAJOR_INDEX_MINS_NINETURN_ASSETS,
        strict=True,
    ):
        assert asset.partitions_def is cn_major_index_mins_trade_days
        dependencies = {key.to_user_string() for key in asset.asset_deps[asset.key]}
        assert dependencies == {f"gold_major_index_mins_{freq}m"}
        assert all("silver" not in value for value in dependencies)
    for asset_key in MAJOR_INDEX_NINETURN_ASSET_KEYS:
        entry = get_lake_asset_catalog_entry(asset_key)
        assert entry.blocking_check_names == (f"{asset_key}_integrity_check",)


def test_jobs_select_exact_assets_and_sensors_stay_stopped() -> None:
    assert gold_major_index_daily_nineturn_update_job.selection.resolve(
        GOLD_MAJOR_INDEX_NINETURN_ASSETS
    ) == {gold_major_index_daily_nineturn.key}
    assert gold_major_index_mins_nineturn_update_job.selection.resolve(
        GOLD_MAJOR_INDEX_NINETURN_ASSETS
    ) == {asset.key for asset in GOLD_MAJOR_INDEX_MINS_NINETURN_ASSETS}
    assert (
        gold_major_index_daily_nineturn_update_job_sensor.default_status
        is dg.DefaultSensorStatus.STOPPED
    )
    assert (
        gold_major_index_mins_nineturn_update_job_sensor.default_status
        is dg.DefaultSensorStatus.STOPPED
    )


def test_index_adapters_use_shared_formula_for_daily_and_six_minutes(tmp_path) -> None:
    daily_path = tmp_path / "daily.parquet"
    _write_daily_history(daily_path, row_count=14)
    with duckdb.connect() as connection:
        daily_rows = connection.execute(
            build_gold_major_index_daily_nineturn_select_sql(source_paths=(daily_path,))
        ).fetchall()
    assert daily_rows[-2][3:7] == (9, 0, "+9", None)
    assert daily_rows[-1][3:7] == (10, 0, "+9", None)

    for freq in MAJOR_INDEX_NINETURN_MINUTE_FREQS:
        minute_path = tmp_path / f"minute-{freq}.parquet"
        _write_minute_history(minute_path, freq=freq, row_count=14)
        with duckdb.connect() as connection:
            minute_rows = connection.execute(
                build_gold_major_index_mins_nineturn_select_sql(
                    source_paths=(minute_path,),
                    freq=freq,
                )
            ).fetchall()
        assert minute_rows[-2][1] == freq
        assert minute_rows[-2][5:9] == (9, 0, "+9", None)
        assert minute_rows[-1][5:9] == (10, 0, "+9", None)


def test_integrity_check_is_formula_free() -> None:
    source = inspect.getsource(major_index_nineturn_integrity).lower()
    assert "lag(" not in source
    assert "build_nineturn_formula_select_sql" not in source
    assert "row_number() over" not in source


def test_daily_writer_promotes_only_validated_partition_and_integrity_passes(
    tmp_path,
) -> None:
    lake_root = tmp_path / "lake"
    staging_root = tmp_path / "staging"
    partition_key = "2026-08-14"
    source_path = (
        lake_root
        / "gold/market/major_indices_daily"
        / f"trade_date={partition_key}"
        / "part-000.parquet"
    )
    _write_daily_partition(source_path, partition_key)
    select_sql = f"""
    SELECT '000001.SH'::VARCHAR AS ts_code,
           DATE '{partition_key}' AS trade_date,
           3000.0::DOUBLE AS close,
           9::INTEGER AS up_count,
           0::INTEGER AS down_count,
           '+9'::VARCHAR AS nine_up_turn,
           NULL::VARCHAR AS nine_down_turn
    """

    result = write_gold_major_index_daily_nineturn_partition(
        duckdb_resource=DuckDBResource(),
        lake_root=lake_root,
        staging_root=staging_root,
        partition_key=partition_key,
        run_id="test-run",
        select_sql=select_sql,
        source_paths=(source_path,),
        previous_partition_path=None,
        source_row_count=1,
    )
    with duckdb.connect() as connection:
        diagnostics = audit_major_index_nineturn_integrity(
            connection,
            target_path=result.target_path,
            source_paths=(source_path,),
            partition_key=partition_key,
            freq=None,
        )

    assert result.output_row_count == 1
    assert result.index_code_count == 1
    assert diagnostics.passed is True


def test_minute_writer_promotes_exact_schema_and_integrity_passes(tmp_path) -> None:
    lake_root = tmp_path / "lake"
    staging_root = tmp_path / "staging"
    partition_key = "2026-08-14"
    source_path = (
        lake_root
        / "gold/quote/major_index_mins/freq=5"
        / f"trade_date={partition_key}"
        / "part-000.parquet"
    )
    _write_minute_partition(source_path, partition_key, freq=5)
    select_sql = f"""
    SELECT '000001.SH'::VARCHAR AS ts_code,
           5::INTEGER AS freq,
           DATE '{partition_key}' AS trade_date,
           TIMESTAMP '{partition_key} 10:00:00' AS trade_time,
           3000.0::DOUBLE AS close,
           9::INTEGER AS up_count,
           0::INTEGER AS down_count,
           '+9'::VARCHAR AS nine_up_turn,
           NULL::VARCHAR AS nine_down_turn
    """

    result = write_gold_major_index_mins_nineturn_partition(
        duckdb_resource=DuckDBResource(),
        lake_root=lake_root,
        staging_root=staging_root,
        freq=5,
        partition_key=partition_key,
        run_id="test-run",
        select_sql=select_sql,
        source_paths=(source_path,),
        previous_partition_path=None,
        source_row_count=1,
    )
    with duckdb.connect() as connection:
        diagnostics = audit_major_index_nineturn_integrity(
            connection,
            target_path=result.target_path,
            source_paths=(source_path,),
            partition_key=partition_key,
            freq=5,
        )

    assert result.observed_columns == (
        "ts_code",
        "freq",
        "trade_date",
        "trade_time",
        "close",
        "up_count",
        "down_count",
        "nine_up_turn",
        "nine_down_turn",
    )
    assert diagnostics.passed is True


def test_history_plan_is_twenty_day_bounded_and_read_only(tmp_path) -> None:
    lake_root = tmp_path / "lake"
    source_root = lake_root / "gold/market/major_indices_daily"
    start = date(2026, 7, 1)
    for offset in range(21):
        trade_date = (start + timedelta(days=offset)).isoformat()
        path = source_root / f"trade_date={trade_date}" / "part-000.parquet"
        _write_daily_partition(path, trade_date)

    plan = plan_major_index_nineturn_history(
        lake_root=lake_root,
        asset_keys=("gold_major_index_daily_nineturn",),
        output_dir=tmp_path / "reports",
    )

    assert plan.should_stop is False
    assert [len(batch.trade_dates) for batch in plan.batches] == [
        MAJOR_INDEX_NINETURN_HISTORY_BATCH_TRADE_DAYS,
        1,
    ]
    assert plan.report["duckdb"] == {
        "memory_limit": "256MB",
        "threads": 1,
        "preserve_insertion_order": False,
        "connection_scope": "one_batch",
    }
    assert not (lake_root / "gold/indicator/major_index_daily_nineturn").exists()


def test_history_builder_requires_reviewed_sources_and_validates_resume_targets(
    tmp_path,
) -> None:
    lake_root = tmp_path / "lake"
    source_root = lake_root / "gold/market/major_indices_daily"
    for trade_date in ("2026-08-13", "2026-08-14"):
        _write_daily_partition(
            source_root / f"trade_date={trade_date}" / "part-000.parquet",
            trade_date,
        )
    plan = plan_major_index_nineturn_history(
        lake_root=lake_root,
        asset_keys=("gold_major_index_daily_nineturn",),
        output_dir=tmp_path / "reports",
    )
    checkpoint = tmp_path / "staging/checkpoint.json"

    result = build_major_index_nineturn_history(
        plan=plan,
        expected_plan_fingerprint=plan.plan_fingerprint,
        confirm_write=True,
        staging_root=tmp_path / "staging",
        checkpoint_path=checkpoint,
    )
    resumed = build_major_index_nineturn_history(
        plan=plan,
        expected_plan_fingerprint=plan.plan_fingerprint,
        confirm_write=True,
        staging_root=tmp_path / "staging",
        checkpoint_path=checkpoint,
    )

    assert result["processed_batch_count"] == 1
    assert resumed["processed_batch_count"] == 0
    target = (
        lake_root
        / "gold/indicator/major_index_daily_nineturn"
        / "trade_date=2026-08-14/part-000.parquet"
    )
    target.write_bytes(b"changed")
    with pytest.raises(
        MajorIndexNineturnHistoryError, match="Completed target changed"
    ):
        build_major_index_nineturn_history(
            plan=plan,
            expected_plan_fingerprint=plan.plan_fingerprint,
            confirm_write=True,
            staging_root=tmp_path / "staging",
            checkpoint_path=checkpoint,
        )


def test_history_builder_rejects_source_changed_after_review(tmp_path) -> None:
    lake_root = tmp_path / "lake"
    source = (
        lake_root
        / "gold/market/major_indices_daily"
        / "trade_date=2026-08-14/part-000.parquet"
    )
    _write_daily_partition(source, "2026-08-14")
    plan = plan_major_index_nineturn_history(
        lake_root=lake_root,
        asset_keys=("gold_major_index_daily_nineturn",),
        output_dir=tmp_path / "reports",
    )
    source.write_bytes(source.read_bytes() + b"changed")

    with pytest.raises(MajorIndexNineturnHistoryError, match="source files changed"):
        build_major_index_nineturn_history(
            plan=plan,
            expected_plan_fingerprint=plan.plan_fingerprint,
            confirm_write=True,
            staging_root=tmp_path / "staging",
            checkpoint_path=tmp_path / "staging/checkpoint.json",
        )


def test_history_builder_continues_sequence_across_twenty_day_batches(
    tmp_path,
) -> None:
    lake_root = tmp_path / "lake"
    source_root = lake_root / "gold/market/major_indices_daily"
    start = date(2026, 7, 1)
    for offset in range(21):
        trade_date = (start + timedelta(days=offset)).isoformat()
        _write_daily_partition(
            source_root / f"trade_date={trade_date}" / "part-000.parquet",
            trade_date,
            close=3000.0 + offset,
        )
    plan = plan_major_index_nineturn_history(
        lake_root=lake_root,
        asset_keys=("gold_major_index_daily_nineturn",),
        output_dir=tmp_path / "reports",
    )

    result = build_major_index_nineturn_history(
        plan=plan,
        expected_plan_fingerprint=plan.plan_fingerprint,
        confirm_write=True,
        staging_root=tmp_path / "staging",
        checkpoint_path=tmp_path / "staging/checkpoint.json",
    )
    latest = (
        lake_root
        / "gold/indicator/major_index_daily_nineturn"
        / "trade_date=2026-07-21/part-000.parquet"
    )
    with duckdb.connect() as connection:
        up_count, signal = connection.execute(
            "SELECT up_count, nine_up_turn FROM read_parquet(?, hive_partitioning=false)",
            [str(latest)],
        ).fetchone()

    assert result["processed_batch_count"] == 2
    assert up_count == 17
    assert signal == "+9"


def test_history_plan_reload_supports_bounded_cross_process_resume(tmp_path) -> None:
    lake_root = tmp_path / "lake"
    source_root = lake_root / "gold/market/major_indices_daily"
    start = date(2026, 7, 1)
    for offset in range(21):
        trade_date = (start + timedelta(days=offset)).isoformat()
        _write_daily_partition(
            source_root / f"trade_date={trade_date}" / "part-000.parquet",
            trade_date,
            close=3000.0 + offset,
        )
    original = plan_major_index_nineturn_history(
        lake_root=lake_root,
        asset_keys=("gold_major_index_daily_nineturn",),
        output_dir=tmp_path / "reports",
    )
    checkpoint = tmp_path / "staging/checkpoint.json"

    first = build_major_index_nineturn_history(
        plan=load_major_index_nineturn_history_plan(original.report_path),
        expected_plan_fingerprint=original.plan_fingerprint,
        confirm_write=True,
        staging_root=tmp_path / "staging",
        checkpoint_path=checkpoint,
        batch_count_limit=1,
    )
    second = build_major_index_nineturn_history(
        plan=load_major_index_nineturn_history_plan(original.report_path),
        expected_plan_fingerprint=original.plan_fingerprint,
        confirm_write=True,
        staging_root=tmp_path / "staging",
        checkpoint_path=checkpoint,
        batch_count_limit=1,
    )

    assert first["processed_batch_count"] == 1
    assert first["remaining_batch_count"] == 1
    assert second["processed_batch_count"] == 1
    assert second["remaining_batch_count"] == 0


def test_history_plan_reload_rejects_modified_report(tmp_path) -> None:
    lake_root = tmp_path / "lake"
    trade_date = "2026-08-14"
    _write_daily_partition(
        lake_root
        / "gold/market/major_indices_daily"
        / f"trade_date={trade_date}"
        / "part-000.parquet",
        trade_date,
    )
    plan = plan_major_index_nineturn_history(
        lake_root=lake_root,
        asset_keys=("gold_major_index_daily_nineturn",),
        output_dir=tmp_path / "reports",
    )
    payload = json.loads(plan.report_path.read_text(encoding="utf-8"))
    payload["batches"][0]["source_row_count"] += 1
    plan.report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(MajorIndexNineturnHistoryError, match="fingerprint drifted"):
        load_major_index_nineturn_history_plan(plan.report_path)


def test_history_final_audit_reconciles_checkpoint_source_and_targets(tmp_path) -> None:
    lake_root = tmp_path / "lake"
    source_root = lake_root / "gold/market/major_indices_daily"
    for trade_date in ("2026-08-13", "2026-08-14"):
        _write_daily_partition(
            source_root / f"trade_date={trade_date}" / "part-000.parquet",
            trade_date,
        )
    plan = plan_major_index_nineturn_history(
        lake_root=lake_root,
        asset_keys=("gold_major_index_daily_nineturn",),
        output_dir=tmp_path / "reports",
    )
    checkpoint = tmp_path / "staging/checkpoint.json"
    build_major_index_nineturn_history(
        plan=plan,
        expected_plan_fingerprint=plan.plan_fingerprint,
        confirm_write=True,
        staging_root=tmp_path / "staging",
        checkpoint_path=checkpoint,
    )

    report = audit_major_index_nineturn_history(
        plan_report_path=plan.report_path,
        checkpoint_path=checkpoint,
        output_path=tmp_path / "staging/final-audit.json",
    )

    assert report["should_stop"] is False
    assert report["expected_target_file_count"] == 2
    assert report["actual_target_file_count"] == 2
    assert report["expected_row_count"] == report["actual_row_count"] == 2
    assert report["checkpoint_hash_mismatch_count"] == 0


def test_history_events_are_sampled_batched_and_bound_to_materializations(
    tmp_path,
) -> None:
    lake_root = tmp_path / "lake"
    source_root = lake_root / "gold/market/major_indices_daily"
    dates = ("2026-08-13", "2026-08-14")
    for trade_date in dates:
        _write_daily_partition(
            source_root / f"trade_date={trade_date}" / "part-000.parquet",
            trade_date,
        )
    history_plan = plan_major_index_nineturn_history(
        lake_root=lake_root,
        asset_keys=("gold_major_index_daily_nineturn",),
        output_dir=tmp_path / "reports",
    )
    history_checkpoint = tmp_path / "staging/history-checkpoint.json"
    build_major_index_nineturn_history(
        plan=history_plan,
        expected_plan_fingerprint=history_plan.plan_fingerprint,
        confirm_write=True,
        staging_root=tmp_path / "staging",
        checkpoint_path=history_checkpoint,
    )
    history_audit_path = tmp_path / "staging/final-audit.json"
    audit_major_index_nineturn_history(
        plan_report_path=history_plan.report_path,
        checkpoint_path=history_checkpoint,
        output_path=history_audit_path,
    )
    event_checkpoint = tmp_path / "staging/event-checkpoint.json"

    with dg.instance_for_test() as instance:
        instance.add_dynamic_partitions(cn_a_index_trade_days.name, list(dates))
        event_plan = plan_major_index_nineturn_events(
            instance=instance,
            history_plan_path=history_plan.report_path,
            history_audit_path=history_audit_path,
            lake_root=lake_root,
            output_dir=tmp_path / "staging/event-plan",
        )
        assert event_plan.should_stop is False
        assert event_plan.report["planned_materialization_event_count"] == 2
        assert event_plan.report["planned_check_event_count"] == 2

        first = report_major_index_nineturn_events(
            instance=instance,
            plan=event_plan,
            expected_plan_fingerprint=event_plan.plan_fingerprint,
            checkpoint_path=event_checkpoint,
            staging_root=tmp_path / "staging",
            lake_root=lake_root,
            sample_identity=event_plan.candidates[0].identity,
        )
        second = report_major_index_nineturn_events(
            instance=instance,
            plan=event_plan,
            expected_plan_fingerprint=event_plan.plan_fingerprint,
            checkpoint_path=event_checkpoint,
            staging_root=tmp_path / "staging",
            lake_root=lake_root,
            partition_limit=10,
        )
        post = post_audit_major_index_nineturn_events(
            instance=instance,
            plan=event_plan,
            checkpoint_path=event_checkpoint,
            lake_root=lake_root,
        )

        assert first["selected_partition_count"] == 1
        assert second["remaining_partition_count"] == 0
        assert post["should_stop"] is False
        assert post["missing_materialization_count"] == 0
        assert post["missing_ready_check_count"] == 0

        checkpoint_payload = json.loads(event_checkpoint.read_text(encoding="utf-8"))
        checkpoint_payload["completed"].append("unknown_asset|2026-08-14")
        event_checkpoint.write_text(
            json.dumps(checkpoint_payload),
            encoding="utf-8",
        )
        with pytest.raises(
            MajorIndexNineturnEventError,
            match="outside the reviewed plan",
        ):
            post_audit_major_index_nineturn_events(
                instance=instance,
                plan=event_plan,
                checkpoint_path=event_checkpoint,
                lake_root=lake_root,
            )


def test_daily_serving_history_plan_freezes_audited_source_identities(tmp_path) -> None:
    lake_root = tmp_path / "lake"
    source_root = lake_root / "gold/market/major_indices_daily"
    dates = ("2026-08-13", "2026-08-14")
    for trade_date in dates:
        _write_daily_partition(
            source_root / f"trade_date={trade_date}" / "part-000.parquet",
            trade_date,
        )
    history_plan = plan_major_index_nineturn_history(
        lake_root=lake_root,
        asset_keys=("gold_major_index_daily_nineturn",),
        output_dir=tmp_path / "reports",
    )
    build_major_index_nineturn_history(
        plan=history_plan,
        expected_plan_fingerprint=history_plan.plan_fingerprint,
        confirm_write=True,
        staging_root=tmp_path / "staging",
        checkpoint_path=tmp_path / "staging/history-checkpoint.json",
    )

    plan = plan_major_index_daily_nineturn_serving_history(
        lake_root=lake_root,
        staging_root=tmp_path / "staging",
        duckdb_resource=DuckDBResource(),
        output_dir=tmp_path / "staging/serving-plan",
    )
    loaded = load_major_index_daily_nineturn_serving_plan(plan.report_path)

    assert plan.should_stop is False
    assert len(plan.partitions) == 2
    assert plan.report["source_row_count"] == 2
    assert loaded.plan_fingerprint == plan.plan_fingerprint


def test_daily_serving_history_publishes_sample_then_resumes_batch(
    tmp_path,
    monkeypatch,
) -> None:
    lake_root = tmp_path / "lake"
    source_root = lake_root / "gold/market/major_indices_daily"
    dates = ("2026-08-13", "2026-08-14")
    for trade_date in dates:
        _write_daily_partition(
            source_root / f"trade_date={trade_date}" / "part-000.parquet",
            trade_date,
        )
    history_plan = plan_major_index_nineturn_history(
        lake_root=lake_root,
        asset_keys=("gold_major_index_daily_nineturn",),
        output_dir=tmp_path / "reports",
    )
    build_major_index_nineturn_history(
        plan=history_plan,
        expected_plan_fingerprint=history_plan.plan_fingerprint,
        confirm_write=True,
        staging_root=tmp_path / "staging",
        checkpoint_path=tmp_path / "staging/history-checkpoint.json",
    )
    plan = plan_major_index_daily_nineturn_serving_history(
        lake_root=lake_root,
        staging_root=tmp_path / "staging",
        duckdb_resource=DuckDBResource(),
        output_dir=tmp_path / "staging/serving-plan",
    )
    published: list[str] = []
    monkeypatch.setattr(
        major_index_daily_nineturn_serving_history,
        "replace_prod_core_index_daily_nineturn_partition",
        lambda *, connection, rows, partition_key: published.append(partition_key),
    )
    monkeypatch.setattr(
        major_index_daily_nineturn_serving_history,
        "audit_prod_core_index_daily_nineturn_partition",
        lambda *, connection, rows, partition_key: SimpleNamespace(
            passed=True,
            expected_content_hash=("a" if partition_key == dates[0] else "b") * 64,
        ),
    )
    monkeypatch.setattr(
        major_index_daily_nineturn_serving_history,
        "audit_prod_core_index_daily_nineturn_checkpoint_partitions",
        lambda *, connection, expected_content_hashes: SimpleNamespace(
            passed=True,
            failed_partition_keys=(),
        ),
    )
    resource = _FakeServingProdResource()
    checkpoint = tmp_path / "staging/serving-checkpoint.json"

    sample = publish_major_index_daily_nineturn_serving_history(
        plan=plan,
        expected_plan_fingerprint=plan.plan_fingerprint,
        duckdb_resource=DuckDBResource(),
        prod_postgres_write=resource,
        checkpoint_path=checkpoint,
        mode="sample",
        sample_partition_keys=(dates[0],),
    )
    resumed = publish_major_index_daily_nineturn_serving_history(
        plan=plan,
        expected_plan_fingerprint=plan.plan_fingerprint,
        duckdb_resource=DuckDBResource(),
        prod_postgres_write=resource,
        checkpoint_path=checkpoint,
        mode="batch",
    )

    assert sample["completed_partition_count"] == 1
    assert resumed["resumed_partition_count"] == 1
    assert resumed["completed_partition_count"] == 2
    assert resumed["remaining_partition_count"] == 0
    assert published == list(dates)


class _FakeServingConnection:
    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


class _FakeServingContext:
    def __init__(self) -> None:
        self.connection = _FakeServingConnection()

    def __enter__(self):
        return self.connection

    def __exit__(self, *_args) -> None:
        return None


class _FakeServingProdResource:
    def connect(self) -> _FakeServingContext:
        return _FakeServingContext()

    def connect_readonly(self) -> _FakeServingContext:
        return _FakeServingContext()


def _write_daily_history(path: Path, *, row_count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    values = ",".join(
        f"('000001.SH', DATE '2026-07-{index:02d}', {3000 + index}::DOUBLE)"
        for index in range(1, row_count + 1)
    )
    with duckdb.connect() as connection:
        connection.execute(
            f"""
            COPY (
              SELECT * FROM (VALUES {values}) source(ts_code, trade_date, close)
            ) TO ? (FORMAT PARQUET)
            """,
            [str(path)],
        )


def _write_minute_history(path: Path, *, freq: int, row_count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    values = ",".join(
        (
            f"('000001.SH', {freq}::INTEGER, DATE '2026-07-01', "
            f"TIMESTAMP '2026-07-01 09:{index + 30:02d}:00', "
            f"{3000 + index}::DOUBLE)"
        )
        for index in range(row_count)
    )
    with duckdb.connect() as connection:
        connection.execute(
            f"""
            COPY (
              SELECT * FROM (VALUES {values}) source(
                ts_code, freq, trade_date, trade_time, close
              )
            ) TO ? (FORMAT PARQUET)
            """,
            [str(path)],
        )


def _write_daily_partition(
    path: Path,
    trade_date: str,
    *,
    close: float = 3000.0,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as connection:
        connection.execute(
            f"""
            COPY (
              SELECT '000001.SH'::VARCHAR AS ts_code,
                     DATE '{trade_date}' AS trade_date,
                     {close}::DOUBLE AS close
            ) TO ? (FORMAT PARQUET)
            """,
            [str(path)],
        )


def _write_minute_partition(path: Path, trade_date: str, *, freq: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as connection:
        connection.execute(
            f"""
            COPY (
              SELECT '000001.SH'::VARCHAR AS ts_code,
                     {freq}::INTEGER AS freq,
                     DATE '{trade_date}' AS trade_date,
                     TIMESTAMP '{trade_date} 10:00:00' AS trade_time,
                     3000.0::DOUBLE AS close
            ) TO ? (FORMAT PARQUET)
            """,
            [str(path)],
        )
