"""Definitions and real partitioned events use only temporary files and instance."""

from datetime import datetime
from zoneinfo import ZoneInfo

import dagster as dg
import pytest

from orchestrator.defs.anns_d_contract import (
    ANNOUNCEMENT_ASSET,
    ANNOUNCEMENT_CHECKS,
    ANNOUNCEMENT_FIELDS,
)
from orchestrator.defs.anns_d_partitions import anns_d_natural_days
from orchestrator.defs.assets.anns_d import raw_tushare_anns_d
from orchestrator.defs.catalog.lake_assets import (
    get_lake_asset_catalog_entry,
    get_partition_model_definition,
)
from orchestrator.defs.checks.anns_d_checks import (
    evaluate_announcement_check,
    raw_tushare_anns_d_delivery_reconciliation_check,
    raw_tushare_anns_d_file_contract_check,
)
from orchestrator.defs.jobs.anns_d import raw_anns_d_update_job
from orchestrator.defs.resources import LakeRootResource, TushareResource
from orchestrator.defs.schedules.anns_d import raw_anns_d_update_schedule
from tests.anns_d_test_support import archive as _archive_fixture
from tests.anns_d_test_support import source_row

archive = _archive_fixture


@pytest.fixture(autouse=True)
def isolated_formal_root(archive, monkeypatch):
    import orchestrator.defs.assets.anns_d as asset_module
    import orchestrator.defs.checks.anns_d_checks as check_module

    monkeypatch.setattr(asset_module, "DEFAULT_LAKE_ROOT", str(archive.root))
    monkeypatch.setattr(check_module, "DEFAULT_LAKE_ROOT", str(archive.root))


def test_catalog_definition_schema_names_and_scope():
    entry = get_lake_asset_catalog_entry(ANNOUNCEMENT_ASSET)
    assert entry.dataset_name == "上市公司公告"
    assert tuple(c.name for c in entry.column_schema) == ANNOUNCEMENT_FIELDS
    assert all(c.type == "VARCHAR" for c in entry.column_schema)
    assert entry.blocking_check_names == ANNOUNCEMENT_CHECKS
    assert (
        get_partition_model_definition(
            entry.partition_model
        ).dagster_partition_dimension
        == "ann_date"
    )
    assert raw_tushare_anns_d.partitions_def == anns_d_natural_days
    assert raw_tushare_anns_d.backfill_policy is None
    assert "60min" not in entry.performance_contract.source_request_policy
    assert not raw_tushare_anns_d.asset_deps[raw_tushare_anns_d.key]
    assert {
        c.name
        for c in raw_tushare_anns_d.metadata_by_key[raw_tushare_anns_d.key][
            "dagster/column_schema"
        ].schema.columns
    } == set(ANNOUNCEMENT_FIELDS)
    for definition in (
        raw_tushare_anns_d_file_contract_check,
        raw_tushare_anns_d_delivery_reconciliation_check,
    ):
        for spec in definition.check_specs:
            assert spec.blocking and spec.partitions_def == anns_d_natural_days
    assert raw_anns_d_update_job.name == "raw_anns_d_update_job"
    assert raw_anns_d_update_schedule.default_status == dg.DefaultScheduleStatus.STOPPED
    assert (
        raw_anns_d_update_schedule.cron_schedule == "0 8 * * *"
        and raw_anns_d_update_schedule.execution_timezone == "Asia/Shanghai"
    )


def test_schedule_one_range_request_zero_io_same_tick_dedup():
    defs = dg.Definitions(
        assets=[raw_tushare_anns_d],
        asset_checks=[
            raw_tushare_anns_d_file_contract_check,
            raw_tushare_anns_d_delivery_reconciliation_check,
        ],
        jobs=[raw_anns_d_update_job],
        schedules=[raw_anns_d_update_schedule],
        resources={
            "lake_root": LakeRootResource(),
            "tushare": TushareResource(token="unused"),
        },
    )
    with dg.build_schedule_context(
        scheduled_execution_time=datetime(
            2026, 1, 3, 8, tzinfo=ZoneInfo("Asia/Shanghai")
        ),
        repository_def=defs.get_repository_def(),
    ) as context:
        first = raw_anns_d_update_schedule.evaluate_tick(context).run_requests
        second = raw_anns_d_update_schedule.evaluate_tick(context).run_requests
    assert len(first) == len(second) == 1
    assert first[0].partition_key is None
    assert first[0].partition_key_range == dg.PartitionKeyRange(
        "2025-12-27", "2026-01-04"
    )
    assert [r.run_key for r in first] == [r.run_key for r in second]
    assert len({r.tags["anns_d/window_id"] for r in first}) == 1
    assert first[0].run_key == ("anns_d:update:2:2026-01-03:2025-12-27:2026-01-04")
    assert "dagster/priority" not in first[0].tags
    assert "dagster/partition" not in first[0].tags
    assert first[0].tags["anns_d/execution_version"] == "2"
    assert all(r.tags["anns_d/automatic"] == "true" for r in first)


@pytest.mark.parametrize("future_partition", [False, True])
@pytest.mark.parametrize(
    "rows", [[], [source_row(), source_row(url="https://example.test/a.pdf")]]
)
def test_isolated_asset_and_check_events_have_same_partition(
    archive, monkeypatch, rows, future_partition
):
    store = archive
    import orchestrator.defs.assets.anns_d as asset_module
    import orchestrator.defs.checks.anns_d_checks as check_module

    monkeypatch.setattr(asset_module, "DEFAULT_LAKE_STAGING_ROOT", str(store.staging))
    monkeypatch.setattr(check_module, "DEFAULT_LAKE_STAGING_ROOT", str(store.staging))
    monkeypatch.setattr(LakeRootResource, "ensure_available_for_run", lambda self: None)
    day, tags = "2023-06-09", {}
    days = [day]
    if future_partition:
        from datetime import timedelta

        from orchestrator.defs.anns_d_window import (
            announcement_schedule_tags,
        )

        scheduled = datetime.now(ZoneInfo("Asia/Shanghai")).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        # Independent calendar expectation: seven prior days, today, tomorrow.
        days = [
            (scheduled.date() + timedelta(days=offset)).isoformat()
            for offset in range(-7, 2)
        ]
        tags = {
            **announcement_schedule_tags(scheduled),
            "dagster/asset_partition_range_start": days[0],
            "dagster/asset_partition_range_end": days[-1],
        }
        day = None
    calls = []

    def source(params, control):
        calls.append(params["ann_date"])
        return [
            dict(row, ann_date=params["ann_date"]) for row in rows
        ], ANNOUNCEMENT_FIELDS

    monkeypatch.setattr(
        asset_module,
        "AnnouncementProcessCall",
        lambda *args: source,
    )
    with dg.DagsterInstance.ephemeral() as instance:
        result = dg.materialize(
            [
                raw_tushare_anns_d,
                raw_tushare_anns_d_file_contract_check,
                raw_tushare_anns_d_delivery_reconciliation_check,
            ],
            partition_key=day,
            tags=tags,
            resources={
                "lake_root": LakeRootResource(root_path=str(store.root)),
                "tushare": TushareResource(token="unused"),
            },
            instance=instance,
            run_config={
                "ops": {ANNOUNCEMENT_ASSET: {"config": {"interval_seconds": 0}}}
            },
        )
        assert result.success
        events = result.get_asset_check_evaluations()
        assert len(events) == 2 * len(days)
        assert all(event.passed for event in events)
        assert {event.partition for event in events} == set(days)
        records = instance.all_logs(result.run_id)
        checks = [
            r.asset_check_evaluation
            for r in records
            if r.asset_check_evaluation is not None
        ]
        assert len(checks) == 2 * len(days)
        mats = result.get_asset_materialization_events()
        assert len(mats) == len(days)
        assert {m.materialization.partition for m in mats} == set(days)
        assert calls == [d.replace("-", "") for d in days]
        for check_name in ANNOUNCEMENT_CHECKS:
            persisted = instance.event_log_storage.get_asset_check_execution_history(
                dg.AssetCheckKey(dg.AssetKey(ANNOUNCEMENT_ASSET), check_name), limit=30
            )
            assert len(persisted) == len(days)
            assert {record.partition for record in persisted} == set(days)
        for target_day in days:
            mat = instance.fetch_materializations(
                dg.AssetRecordsFilter(
                    asset_key=dg.AssetKey(ANNOUNCEMENT_ASSET),
                    asset_partitions=[target_day],
                ),
                limit=1,
            ).records[0]
            metadata = mat.asset_materialization.metadata
            assert (
                metadata["goldenshare/announcement_identity"].value["day"] == target_day
            )
            assert metadata["dagster/row_count"].value == len(rows)
            for event in events:
                if event.partition == target_day:
                    assert event.target_materialization_data.run_id == result.run_id
                    assert (
                        event.target_materialization_data.storage_id == mat.storage_id
                    )


def test_missing_delivery_is_red_even_when_valid_empty_file_exists(archive):
    from types import SimpleNamespace

    archive.write_page([], archive.directory / "empty.parquet", archive.control)
    delivery = archive.build_day("2023-06-09", [archive.directory / "empty.parquet"])
    from orchestrator.defs.anns_d_checkpoint import AnnouncementCheckpoint

    archive.promote_day(
        "2023-06-09",
        delivery,
        AnnouncementCheckpoint(archive.directory / "temporary.json", {}),
    )
    with dg.DagsterInstance.ephemeral() as instance:
        context = SimpleNamespace(
            partition_key="2023-06-09",
            instance=instance,
            run=SimpleNamespace(run_id="check-only"),
        )
        root = LakeRootResource(root_path=str(archive.root))
        assert evaluate_announcement_check(
            context,
            root,
            day="2023-06-09",
            reconciliation=False,
            staging_root=archive.staging,
        ).passed
        result = evaluate_announcement_check(
            context,
            root,
            day="2023-06-09",
            reconciliation=True,
            staging_root=archive.staging,
        )
        assert not result.passed and result.metadata[
            "goldenshare/failed_rule_names"
        ].value == ["announcement_materialization_missing"]


@pytest.mark.parametrize(
    "corruption",
    ["source_page", "target", "wrong_run", "checkpoint_identity", "outside_staging"],
)
def test_reconciliation_cannot_borrow_or_accept_changed_evidence(archive, corruption):
    import json
    from types import SimpleNamespace

    from orchestrator.defs.anns_d_checkpoint import announcement_atomic_json
    from orchestrator.defs.anns_d_window import (
        announcement_day_run_id,
        announcement_window_tags,
        execute_announcement_window,
    )

    tags = announcement_window_tags("verified", "2023-06-09", "2023-06-09")
    from orchestrator.defs.anns_d_io import AnnouncementStore

    deliveries = execute_announcement_window(
        ("2023-06-09",),
        tags=tags,
        policy=archive.policy,
        control=archive.control,
        store_factory=lambda day: AnnouncementStore(
            archive.root,
            archive.staging,
            announcement_day_run_id("verified", day),
            archive.policy,
            archive.control,
        ),
        call_factory=lambda day, store: (
            lambda *a: ([source_row()], ANNOUNCEMENT_FIELDS)
        ),
    )
    result = deliveries["2023-06-09"]
    delivery = result.delivery
    identity = dict(result.identity)
    checkpoint_path = result.checkpoint_path
    selected = set()
    if corruption == "source_page":
        from pathlib import Path

        Path(delivery["source_pages"][0]["path"]).write_bytes(b"changed")
    elif corruption == "target":
        archive.target("2023-06-09").write_bytes(b"changed")
    elif corruption == "checkpoint_identity":
        identity = {**identity, "day": "2023-06-08"}
    elif corruption == "outside_staging":
        document = json.loads(checkpoint_path.read_text())
        document["delivery"]["source_pages"][0]["path"] = str(
            archive.root / "outside.parquet"
        )
        announcement_atomic_json(checkpoint_path, document)
    else:
        selected = {dg.AssetKey(ANNOUNCEMENT_ASSET)}
    with dg.DagsterInstance.ephemeral() as instance:
        instance.report_runless_asset_event(
            dg.AssetMaterialization(
                asset_key=ANNOUNCEMENT_ASSET,
                partition="2023-06-09",
                metadata={
                    "goldenshare/announcement_identity": identity,
                    "goldenshare/announcement_checkpoint": str(checkpoint_path),
                    "goldenshare/fingerprint": dict(delivery["fingerprint"]),
                },
            )
        )
        context = SimpleNamespace(
            partition_key="2023-06-09",
            instance=instance,
            run=SimpleNamespace(
                run_id="other-run", asset_selection=selected, step_keys_to_execute=None
            ),
        )

        def evaluate():
            return evaluate_announcement_check(
                context,
                LakeRootResource(root_path=str(archive.root)),
                day="2023-06-09",
                reconciliation=True,
                staging_root=archive.staging,
            )

        if corruption in {"source_page", "target", "outside_staging"}:
            with pytest.raises(
                Exception, match="changed|schema|parquet|Parquet|staging"
            ):
                evaluate()
        else:
            assert not evaluate().passed


def test_asset_rejects_resource_root_override_before_any_access(monkeypatch):
    from orchestrator.defs.run_contracts.anns_d import AnnouncementRawConfig

    monkeypatch.setattr(
        LakeRootResource,
        "ensure_available_for_run",
        lambda *a: pytest.fail("unapproved root accessed"),
    )
    from orchestrator.defs.anns_d_contract import AnnouncementError

    with pytest.raises(AnnouncementError, match="formal_root_contract"):
        raw_tushare_anns_d.op.compute_fn.decorated_fn(
            None,
            AnnouncementRawConfig(),
            LakeRootResource(root_path="/private/tmp/unapproved-lake"),
            TushareResource(token="unused"),
        )


def test_partition_availability_includes_today_and_tomorrow_only():
    keys = anns_d_natural_days.get_partition_keys(
        current_time=datetime(2026, 10, 12, 8, tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    assert keys[-3:] == ["2026-10-11", "2026-10-12", "2026-10-13"]
    assert "2026-10-14" not in keys
