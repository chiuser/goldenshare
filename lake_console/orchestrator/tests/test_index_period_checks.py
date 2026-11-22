"""隔离执行两个真实 Raw job，验证原生分区、检查关联和失败行为。"""

from contextlib import contextmanager
from datetime import date, datetime, timedelta
from json import loads

import dagster as dg
import duckdb
import pytest

from orchestrator.defs.assets import index_period as assets
from orchestrator.defs.daily_data_audit import jobs as audit_jobs
from orchestrator.defs.daily_data_audit.evidence import (
    SHANGHAI,
    get_completeness,
    load_evidence,
    read_summary,
)
from orchestrator.defs.daily_data_audit.registry import targets_for_day
from orchestrator.defs.io import index_period_writer as writer
from orchestrator.defs.jobs.index_period_update import (
    raw_index_monthly_update_job,
    raw_index_weekly_update_job,
    silver_index_monthly_update_job,
    silver_index_weekly_update_job,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.index_period import INDEX_MONTHLY, INDEX_WEEKLY
from tests.index_period_test_support import seed_silver, silver_inputs
from tests.test_index_period_contracts import calendar, fake_source


def definitions(monkeypatch, tmp_path):
    root = tmp_path / "lake"
    with duckdb.connect() as connection:
        calendar(connection, root)

    @contextmanager
    def connect(self):
        with duckdb.connect() as connection:
            yield connection

    monkeypatch.setattr(DuckDBResource, "connect", connect)
    monkeypatch.setattr(LakeRootResource, "ensure_available_for_run", lambda _: None)
    monkeypatch.setattr(assets, "DEFAULT_LAKE_STAGING_ROOT", str(tmp_path / "staging"))
    return dg.Definitions(
        assets=[
            assets.raw_index_weekly,
            assets.raw_index_monthly,
            assets.silver_index_weekly,
            assets.silver_index_monthly,
            dg.AssetSpec("silver_trade_calendar"),
            dg.AssetSpec("silver_index_basic"),
            dg.AssetSpec("silver_index_daily"),
        ],
        jobs=[
            raw_index_weekly_update_job,
            raw_index_monthly_update_job,
            silver_index_weekly_update_job,
            silver_index_monthly_update_job,
        ],
        resources={
            "lake_root": LakeRootResource(root_path=str(root)),
            "duckdb": DuckDBResource(),
        },
    )


@pytest.mark.parametrize(
    "period,key", [(INDEX_WEEKLY, "2026-07-03"), (INDEX_MONTHLY, "2026-07")]
)
def test_real_job_check_and_execution_partition(monkeypatch, tmp_path, period, key):
    defs = definitions(monkeypatch, tmp_path)
    fake_source(monkeypatch, period)
    with duckdb.connect() as connection:
        writer.write_index_period_raw(
            connection,
            lake_root=tmp_path / "lake",
            staging_root=tmp_path / "staging",
            period=period,
            partition_key="2026-06-26" if period == INDEX_WEEKLY else "2026-06",
            run_id="prior-period",
        )
    fake_source(monkeypatch, period)
    with dg.DagsterInstance.ephemeral(tempdir=str(tmp_path / "instance")) as instance:
        instance.add_dynamic_partitions(period.partition_set, [key])
        job = defs.resolve_job_def(f"{period.raw_asset}_update_job")
        result = job.execute_in_process(instance=instance, partition_key=key)
        assert result.success
        evaluations = result.get_asset_check_evaluations()
        assert len(evaluations) == 1
        evaluation = evaluations[0]
        assert evaluation.passed and evaluation.partition == key
        assert evaluation.check_name == period.raw_check
        materializations = result.get_asset_materialization_events()
        assert len(materializations) == 1
        assert materializations[0].asset_key == dg.AssetKey(period.raw_asset)
        assert materializations[0].materialization.partition == key
        mat = instance.fetch_materializations(
            dg.AssetRecordsFilter(
                asset_key=dg.AssetKey(period.raw_asset), asset_partitions=[key]
            ),
            limit=1,
        ).records[0]
        assert evaluation.target_materialization_data.storage_id == mat.storage_id
        assert evaluation.target_materialization_data.run_id == result.run_id
        records = instance.event_log_storage.get_asset_check_execution_history(
            dg.AssetCheckKey(dg.AssetKey(period.raw_asset), period.raw_check), limit=1
        )
        assert len(records) == 1 and records[0].partition == key
        assert records[0].evaluation.passed
        metadata = mat.asset_materialization.metadata
        assert metadata["dagster/row_count"].value == 10
        assert metadata["goldenshare/file_row_count"].value == 20
        assert metadata["goldenshare/changed_row_count"].value == 10
        assert metadata["goldenshare/upstream_batch_id"].value.startswith(
            f"{period.raw_asset}:{key}:"
        )
        assert "dagster/column_schema" not in metadata
        assert {
            record.asset_key.to_user_string()
            for record in instance.fetch_materializations(
                dg.AssetRecordsFilter(asset_key=dg.AssetKey(period.raw_asset)), limit=5
            ).records
        } == {period.raw_asset}


def test_candidate_failure_emits_red_check_without_success_materialization(
    monkeypatch, tmp_path
):
    defs = definitions(monkeypatch, tmp_path)
    fake_source(monkeypatch, INDEX_WEEKLY)
    original_copy = writer.copy_query_to_parquet
    monkeypatch.setattr(
        writer,
        "copy_query_to_parquet",
        lambda sql, path: original_copy(f"SELECT *, 1 extra FROM ({sql})", path),
    )
    with dg.DagsterInstance.ephemeral(tempdir=str(tmp_path / "instance")) as instance:
        instance.add_dynamic_partitions(INDEX_WEEKLY.partition_set, ["2026-07-03"])
        result = defs.resolve_job_def("raw_index_weekly_update_job").execute_in_process(
            instance=instance, partition_key="2026-07-03", raise_on_error=False
        )
        assert not result.success
        checks = result.get_asset_check_evaluations()
        assert len(checks) == 1 and not checks[0].passed
        assert checks[0].partition == "2026-07-03"
        assert checks[0].metadata["goldenshare/failure_counts"].value["schema"] == 1
        assert result.get_asset_materialization_events() == []
        assert not list((tmp_path / "lake" / "raw").rglob("*.parquet"))


def test_raw_job_has_no_extra_time_or_source_configuration(monkeypatch, tmp_path):
    defs = definitions(monkeypatch, tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("错误配置必须在取源前被拒绝")

    monkeypatch.setattr(writer, "download_index_period_rows", forbidden)
    with dg.DagsterInstance.ephemeral(tempdir=str(tmp_path / "instance")) as instance:
        instance.add_dynamic_partitions(INDEX_WEEKLY.partition_set, ["2026-07-03"])
        with pytest.raises(dg.DagsterInvalidConfigError):
            defs.resolve_job_def("raw_index_weekly_update_job").execute_in_process(
                instance=instance,
                partition_key="2026-07-03",
                run_config={
                    "ops": {
                        "raw_index_weekly": {
                            "config": {
                                "period_end_date": "2026-07-03",
                                "source": "old_lake",
                            }
                        }
                    }
                },
            )


@pytest.mark.parametrize(
    "period,key", [(INDEX_WEEKLY, "2026-07-03"), (INDEX_MONTHLY, "2026-07")]
)
def test_silver_job_native_checks_and_daily_input_metadata(
    monkeypatch, tmp_path, period, key
):
    defs = definitions(monkeypatch, tmp_path)
    silver_inputs(tmp_path / "lake")
    if period == INDEX_WEEKLY:
        seed_silver(tmp_path / "lake", period)

    def forbidden(*args, **kwargs):
        pytest.fail("Silver job不得访问下载器")

    monkeypatch.setattr(writer.TushareDownloader, "load", forbidden)
    calendar_by_day = {
        date(2026, 6, 1) + timedelta(days=index): index % 7 < 5 for index in range(61)
    }
    monkeypatch.setattr(audit_jobs, "read_calendar", lambda root, day: calendar_by_day)
    instance_path = tmp_path / "audit-instance"
    instance_path.mkdir()
    with dg.DagsterInstance.local_temp(
        str(instance_path), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        instance.add_dynamic_partitions(period.partition_set, [key])
        job = defs.resolve_job_def(period.silver_asset + "_update_job")
        config = {
            "ops": {
                period.silver_asset: {
                    "config": {"mode": "daily", "trade_date": "2026-07-01"}
                }
            }
        }
        result = job.execute_in_process(
            instance=instance,
            partition_key=key,
            run_config=config,
        )
        assert result.success
        checks = result.get_asset_check_evaluations()
        assert len(checks) == 1 and checks[0].partition == key and checks[0].passed
        mats = result.get_asset_materialization_events()
        assert len(mats) == 1 and mats[0].asset_key == dg.AssetKey(period.silver_asset)
        record = instance.fetch_materializations(
            dg.AssetKey(period.silver_asset), limit=1
        ).records[0]
        assert checks[0].target_materialization_data.storage_id == record.storage_id
        meta = record.asset_materialization.metadata
        assert meta["dagster/row_count"].value == 11
        assert meta["goldenshare/source_row_count"].value == (
            33 if period == INDEX_WEEKLY else 11
        )
        assert meta["goldenshare/changed_row_count"].value == 11
        assert meta["goldenshare/daily_input"].value["file_count"] == (
            3 if period == INDEX_WEEKLY else 1
        )
        assert meta["goldenshare/source_assets"].value == ["silver_index_daily"]
        coverage = checks[0].metadata["goldenshare/index_period_coverage"].value
        assert coverage["scope"] == {
            "asset_key": period.silver_asset,
            "business_date": "2026-07-01",
            "as_of_date": "2026-07-01",
            "partition_key": key,
            "frequency": "周线" if period == INDEX_WEEKLY else "月线",
            "coverage_scope": "dataset",
        }
        assert (
            coverage["version"]
            == meta["goldenshare/index_period_coverage"].value["version"]
        )
        published = writer.index_period_path(tmp_path / "lake", period, "silver").stat()
        assert (
            meta["goldenshare/period_file_version"].value
            == loads(coverage["version"]["target_version"])
            == [
                published.st_dev,
                published.st_ino,
                published.st_size,
                published.st_mtime_ns,
                published.st_ctime_ns,
            ]
        )
        assert coverage["expected_count"] == coverage["actual_count"] == 11
        assert coverage["wrong_date_count"] == 0
        inputs = coverage["version"]["inputs"]
        daily = [i for i in inputs if i["asset_key"] == "silver_index_daily"]
        assert [i["scope"]["partition_key"] for i in daily] == (
            ["2026-06-29", "2026-06-30", "2026-07-01"]
            if period == INDEX_WEEKLY
            else ["2026-07-01"]
        )
        assert {item["asset_key"] for item in inputs if item not in daily} == (
            {"major_indices.cn_a.csv", "silver_index_basic", "silver_trade_calendar"}
            | ({period.silver_asset} if period == INDEX_WEEKLY else set())
        )
        assert all(item["target_version"] for item in inputs)
        assert (
            instance.event_log_storage.get_asset_check_execution_history(
                dg.AssetCheckKey(dg.AssetKey(period.silver_asset), period.silver_check),
                limit=1,
            )[0].partition
            == key
        )

        day = date(2026, 7, 1)
        targets = tuple(
            t
            for t in targets_for_day(day, calendar_by_day)
            if t.asset_key == period.silver_asset
        )
        evidence = load_evidence(instance, targets, day, datetime.now(SHANGHAI))
        assert (
            evidence[period.silver_asset].checks[period.silver_check].run_id
            == result.run_id
        )

        def audit_row():
            summary_result = audit_jobs.daily_data_audit_summary_job.execute_in_process(
                instance=instance,
                run_config={
                    "ops": {
                        "generate_data_audit_summary": {
                            "config": {"business_date": day.isoformat()}
                        }
                    }
                },
            )
            assert summary_result.success
            return next(
                row
                for row in read_summary(instance, day)["rows"]
                if row["scope"]["asset_key"] == period.silver_asset
            )

        row = audit_row()
        assert row["update"]["status"] == "updated"
        assert row["completeness"]["status"] == "complete"
        assert row["completeness"]["expected_count"] == 11
        assert (
            get_completeness(instance, row["scope"], coverage["version"])
            == row["completeness"]
        )
        assert (
            get_completeness(
                instance, row["scope"], {**coverage["version"], "target_version": "old"}
            )
            is None
        )

        synthesize = writer.synthesize_index_period

        def wrong_date(connection, **kwargs):
            inputs = synthesize(connection, **kwargs)
            connection.execute(
                "UPDATE index_period_synthesized SET trade_date=DATE '2026-07-02' WHERE ts_code='000300.SH'"
            )
            return inputs

        with monkeypatch.context() as patch:
            patch.setattr(writer, "synthesize_index_period", wrong_date)
            failed = job.execute_in_process(
                instance=instance,
                partition_key=key,
                run_config=config,
                raise_on_error=False,
            )
        assert not failed.success and not failed.get_asset_materialization_events()
        (failed_check,) = failed.get_asset_check_evaluations()
        failed_coverage = failed_check.metadata[
            "goldenshare/index_period_coverage"
        ].value
        assert failed_coverage["wrong_date_count"] == 1
        assert failed_coverage["version"]["target_version"] is None
        assert audit_row()["completeness"]["evidence"][-1]["run_id"] == result.run_id

        live_version = writer.file_version

        def no_daily_version(path):
            if (
                path.parent.name == "trade_date=2026-07-01"
                and path.parent.parent.name == "index_daily"
            ):
                raise OSError("隔离样本模拟无法查询文件身份")
            return live_version(path)

        with monkeypatch.context() as patch:
            patch.setattr(writer, "file_version", no_daily_version)
            newer = job.execute_in_process(
                instance=instance, partition_key=key, run_config=config
            )
        assert newer.success and newer.get_asset_check_evaluations()[0].passed
        pending = audit_row()
        assert pending["update"]["status"] == "updated"
        assert pending["completeness"]["status"] == "pending"
        assert pending["completeness"]["evidence"][-1]["run_id"] == newer.run_id
        assert (
            pending["version"]["target_version"]
            != coverage["version"]["target_version"]
        )
        assert get_completeness(instance, row["scope"], coverage["version"]) is None


def test_period_job_requires_raw_native_delivery_before_reading_files(
    monkeypatch, tmp_path
):
    defs = definitions(monkeypatch, tmp_path)

    def forbidden(*args, **kwargs):
        pytest.fail("Raw本次物化和check未成功，不得读取行情或提升候选")

    monkeypatch.setattr(assets, "write_index_period_silver", forbidden)
    with dg.DagsterInstance.ephemeral(tempdir=str(tmp_path / "instance")) as instance:
        instance.add_dynamic_partitions(INDEX_WEEKLY.partition_set, ["2026-07-03"])
        result = defs.resolve_job_def(
            "silver_index_weekly_update_job"
        ).execute_in_process(
            instance=instance,
            partition_key="2026-07-03",
            run_config={"ops": {"silver_index_weekly": {"config": {"mode": "period"}}}},
            raise_on_error=False,
        )
        assert not result.success
        assert result.get_asset_materialization_events() == []


def test_real_raw_success_then_silver_override_same_partition(monkeypatch, tmp_path):
    defs = definitions(monkeypatch, tmp_path)
    silver_inputs(tmp_path / "lake")
    config = {"ops": {"silver_index_weekly": {"config": {"mode": "repair"}}}}
    with dg.DagsterInstance.ephemeral(tempdir=str(tmp_path / "instance")) as instance:
        instance.add_dynamic_partitions(INDEX_WEEKLY.partition_set, ["2026-07-03"])
        silver_job = defs.resolve_job_def("silver_index_weekly_update_job")
        before = silver_job.execute_in_process(
            instance=instance, partition_key="2026-07-03", run_config=config
        )
        assert before.success
        fake_source(monkeypatch, INDEX_WEEKLY)
        raw = defs.resolve_job_def("raw_index_weekly_update_job").execute_in_process(
            instance=instance, partition_key="2026-07-03"
        )
        assert raw.success

        def forbidden(*args, **kwargs):
            pytest.fail("正式覆盖不得下载源或重读日线")

        monkeypatch.setattr(writer.TushareDownloader, "load", forbidden)
        monkeypatch.setattr(writer, "synthesize_index_period", forbidden)
        after = silver_job.execute_in_process(
            instance=instance,
            partition_key="2026-07-03",
            run_config={"ops": {"silver_index_weekly": {"config": {"mode": "period"}}}},
        )
        assert after.success
        checks = after.get_asset_check_evaluations()
        assert (
            len(checks) == 1
            and checks[0].partition == "2026-07-03"
            and checks[0].passed
        )
        mats = after.get_asset_materialization_events()
        assert len(mats) == 1 and mats[0].asset_key == dg.AssetKey(
            "silver_index_weekly"
        )
        record = instance.fetch_materializations(
            dg.AssetKey("silver_index_weekly"), limit=1
        ).records[0]
        assert record.asset_materialization.metadata[
            "goldenshare/source_assets"
        ].value == ["raw_index_weekly", "silver_index_weekly"]
