from datetime import date, datetime, timedelta
from types import SimpleNamespace

import dagster as dg
import duckdb

from orchestrator.defs.catalog.lake_assets import SILVER_STOCK_DAILY_CHECKS
from orchestrator.defs.checks.daily_audit_coverage import stat_version
from orchestrator.defs.checks.stk_mins_checks import _silver_codes_exist_in_stock_daily
from orchestrator.defs.daily_data_audit import jobs
from orchestrator.defs.daily_data_audit.evidence import (
    SHANGHAI,
    get_completeness,
    load_evidence,
    read_summary,
)
from orchestrator.defs.daily_data_audit.registry import targets_for_day
from orchestrator.defs.daily_data_audit.summary import make_summary
from orchestrator.defs.paths import (
    gold_stock_daily_qfq_path,
    silver_stk_mins_path,
    silver_stock_daily_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.sensors.stock_daily_audit_coverage import (
    late_stock_daily_coverage_request,
)

DAY = date(2026, 11, 20)
PARTITION = DAY.isoformat()
CALENDAR = {
    date(2026, 10, 1) + timedelta(days=offset): (
        date(2026, 10, 1) + timedelta(days=offset)
    ).weekday()
    < 5
    for offset in range(61)
}
RAW = "raw_tushare_dc_member"
DIGEST = "a" * 64


def _materialize(
    instance,
    *,
    digest,
    checks=(),
    key=RAW,
    partition=PARTITION,
    published=None,
    check_metadata=None,
    legacy_checks=False,
    fail_run=False,
):
    partitions = dg.StaticPartitionsDefinition([partition]) if partition else None

    @dg.asset(name=key, partitions_def=partitions)
    def example():
        return dg.MaterializeResult(
            metadata={"goldenshare/file_sha256": digest, **(published or {})}
        )

    definitions = []
    for check_name, passed in checks:

        def check_fn(passed):
            def check():
                return dg.AssetCheckResult(passed=passed, metadata=check_metadata or {})

            return check

        definitions.append(
            dg.asset_check(
                asset=example,
                name=check_name,
                partitions_def=None if legacy_checks else partitions,
                blocking=fail_run,
            )(check_fn(passed))
        )
    return dg.materialize(
        [example, *definitions],
        partition_key=partition,
        instance=instance,
        raise_on_error=not fail_run,
    )


def _targets(day=DAY):
    result = targets_for_day(day, CALENDAR)
    return {target.asset_key: target for target in result}


def test_due_dates_keep_partition_and_business_date_separate():
    thursday = _targets(date(2026, 11, 19))
    assert len(thursday) == 187
    assert not thursday["raw_index_weekly"].requires_update
    assert thursday["silver_index_weekly"].requires_update
    assert thursday["silver_index_weekly"].partition == "2026-11-20"
    assert thursday["silver_index_weekly"].expected_date.isoformat() == "2026-11-19"
    first_day = _targets(date(2026, 11, 2))
    assert first_day["raw_index_monthly"].requires_update
    assert first_day["raw_index_monthly"].partition == "2026-10"
    assert first_day["raw_index_monthly"].expected_date.isoformat() == "2026-10-30"


def test_legacy_index_period_publication_has_update_but_no_coverage(tmp_path):
    key = "silver_index_weekly"
    check = "silver_index_weekly_file_contract_check"
    with dg.DagsterInstance.local_temp(
        str(tmp_path), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        result = _materialize(
            instance,
            digest=DIGEST,
            key=key,
            checks=[(check, True)],
            published={"goldenshare/trade_date": PARTITION},
        )
        assert result.success
        targets = (_targets()[key],)
        observed = datetime.now(SHANGHAI)
        evidence = load_evidence(instance, targets, DAY, observed)
        assert evidence[key].checks[check].evaluation.passed
        row = make_summary(DAY, observed, targets, evidence)["rows"][0]

    assert row["update"]["status"] == "updated"
    assert row["completeness"]["status"] == "pending"
    assert row["completeness"]["reason"]["message"] == "缺少该版本的齐备证据"


def test_stock_daily_qfq_requires_daily_checks_file_and_successful_producer(
    tmp_path, monkeypatch
):
    daily = "silver_stock_daily"
    gold = "gold_stock_daily_qfq"
    root = tmp_path / "lake"
    file = gold_stock_daily_qfq_path(root, PARTITION)
    file.parent.mkdir(parents=True)
    monkeypatch.setattr(jobs, "read_calendar", lambda root, day: CALENDAR)
    monkeypatch.setattr(jobs, "DEFAULT_LAKE_ROOT", root)

    with dg.DagsterInstance.local_temp(
        str(tmp_path), overrides={"telemetry": {"enabled": False}}
    ) as instance:

        def audit(changed=()):
            result = jobs.daily_data_audit_summary_job.execute_in_process(
                instance=instance,
                run_config={
                    "ops": {
                        "generate_data_audit_summary": {
                            "config": {
                                "business_date": PARTITION,
                                "changed_asset_keys": list(changed),
                            }
                        }
                    }
                },
            )
            assert result.success
            return {
                row["scope"]["asset_key"]: row
                for row in read_summary(instance, DAY)["rows"]
            }

        _materialize(
            instance,
            digest=None,
            key=daily,
            checks=[(name, True) for name in SILVER_STOCK_DAILY_CHECKS],
        )
        initial = audit()
        assert initial[gold]["completeness"]["status"] == "pending"
        assert (
            initial[gold]["completeness"]["reason"]["message"]
            == "未确认当日前复权文件存在"
        )

        file.touch()  # A marker suffices for the existence rule. It must not be read as Parquet.
        failed_run = _materialize(
            instance,
            digest=None,
            key=gold,
            checks=[("test_failure_after_delivery", False)],
            fail_run=True,
        )
        assert not failed_run.success
        failed = audit([gold])[gold]
        assert failed["update"]["status"] == "updated"
        assert failed["completeness"]["status"] == "pending"
        assert failed["completeness"]["reason"]["message"] == "未确认当次前复权任务成功"

        _materialize(instance, digest=None, key=gold)
        delivered = audit([gold])
        assert delivered[daily]["observed_at"] == initial[daily]["observed_at"]
        assert delivered[gold]["update"]["status"] == "updated"
        assert delivered[gold]["completeness"]["status"] == "complete"
        assert delivered[gold]["version"]["target_version"] is None
        assert {
            entry["check_name"]
            for entry in delivered[gold]["completeness"]["evidence"]
            if entry.get("asset_key") == daily
        } == set(SILVER_STOCK_DAILY_CHECKS)

        _materialize(
            instance,
            digest=None,
            key=daily,
            checks=[(name, i != 0) for i, name in enumerate(SILVER_STOCK_DAILY_CHECKS)],
        )
        upstream_failed = audit([daily])[gold]
        assert upstream_failed["update"]["status"] == "updated"
        assert upstream_failed["completeness"]["status"] == "pending"
        assert upstream_failed["completeness"]["reason"]["code"] == "upstream_pending"


def test_moneyflow_coverage_uses_the_check_for_the_published_file_version(tmp_path):
    key = "raw_tushare_moneyflow"
    target = _targets()[key]
    file_version = [5, 6, 7, 8, 9]
    proof = {
        "status": "gap",
        "expected_count": 101,
        "actual_count": 100,
        "missing_count": 1,
        "extra_count": 0,
        "samples": [{"ts_code": "920002.BJ", "change": "missing"}],
        "file_version": file_version,
        "inputs": {"silver_stock_lifecycle": "[1,2,3,4,5]"},
        "rule_version": "moneyflow_expected_codes_v1",
    }
    with dg.DagsterInstance.local_temp(
        str(tmp_path), overrides={"telemetry": {"enabled": False}}
    ) as instance:

        def row_for(version):
            _materialize(
                instance,
                digest=DIGEST,
                key=key,
                checks=[(target.check_names[0], True)],
                check_metadata={
                    "goldenshare/audit_coverage": dg.MetadataValue.json(proof)
                },
                published={
                    "goldenshare/audit_file_version": dg.MetadataValue.json(version)
                },
            )
            now = datetime.now(SHANGHAI)
            evidence = load_evidence(instance, (target,), DAY, now)
            return make_summary(DAY, now, (target,), evidence)["rows"][0]

        row = row_for(file_version)
        assert row["update"]["status"] == "updated"
        assert row["completeness"]["status"] == "gap"
        assert row["completeness"]["samples"] == [
            {"ts_code": "920002.BJ", "change": "missing"}
        ]
        assert row_for([5, 60, 7, 8, 9])["completeness"]["status"] == "pending"


def test_stock_basic_tolerance_uses_previous_trading_day_not_previous_run(tmp_path):
    key = "raw_tushare_stock_basic"
    prior_day = date(2026, 11, 19)
    target = _targets()[key]
    prior_target = _targets(prior_day)[key]
    with dg.DagsterInstance.local_temp(
        str(tmp_path), overrides={"telemetry": {"enabled": False}}
    ) as instance:

        def publish(day, count):
            _materialize(
                instance,
                digest=DIGEST,
                key=key,
                partition=None,
                checks=[(name, True) for name in target.check_names],
                published={
                    "goldenshare/trade_date": day.isoformat(),
                    "dagster/row_count": count,
                },
            )

        publish(prior_day, 6000)
        for count, status in ((6020, "complete"), (6021, "pending"), (5979, "pending")):
            publish(DAY, count)
            now = datetime.now(SHANGHAI)
            previous = load_evidence(instance, (prior_target,), prior_day, now)[key]
            evidence = load_evidence(instance, (target,), DAY, now)
            row = make_summary(
                DAY,
                now,
                (target,),
                evidence,
                previous_stock_basic=previous,
            )["rows"][0]
            assert row["update"]["status"] == "updated"
            assert row["completeness"]["status"] == status


def test_minute_qfq_follows_actual_silver_input_without_reading_annual_files(tmp_path):
    targets = _targets()
    daily = "silver_stock_daily"
    raw_one, raw_five = "raw_stk_mins_1m", "raw_stk_mins_5m"
    silver, gold = "silver_stk_mins_5m", "gold_stk_mins_qfq_15m"
    versions = {
        key: [1, 2, index, 4, 5]
        for index, key in enumerate((daily, raw_one, raw_five, silver), 1)
    }
    selected = tuple(targets[key] for key in (*versions, gold))
    with dg.DagsterInstance.local_temp(
        str(tmp_path), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        _materialize(
            instance,
            digest=None,
            key=daily,
            published={"goldenshare/audit_file_version": versions[daily]},
            checks=[(name, True) for name in SILVER_STOCK_DAILY_CHECKS],
        )
        for key, roots in ((raw_one, 482), (raw_five, 98), (silver, 98)):
            comparison = {
                "status": "complete",
                "file_version": versions[key],
                "expected_count": roots,
                "actual_count": roots,
                "missing_count": 0,
                "extra_count": 0,
                "samples": [],
                "inputs": {daily: "[1,2,1,4,5]"}
                if key == silver
                else {"本次股票分钟线取数名单": DIGEST},
                "rule_version": "stock_minute_regular_coverage_v1",
            }
            published = {"goldenshare/audit_file_version": versions[key]}
            if key == silver:
                published["goldenshare/audit_input_versions"] = {
                    daily: "[1,2,1,4,5]",
                    raw_one: "[1,2,2,4,5]",
                    raw_five: "[1,2,3,4,5]",
                }
            _materialize(
                instance,
                digest=None,
                key=key,
                published=published,
                checks=[(name, True) for name in targets[key].check_names],
                check_metadata={"goldenshare/audit_coverage": comparison},
            )
        _materialize(
            instance,
            digest=None,
            key=gold,
            published={
                "goldenshare/output_file_count": 2,
                "goldenshare/replacement_row_count": 34,
                "goldenshare/audit_source_file_version": versions[silver],
                "goldenshare/audit_delivery_version": DIGEST,
            },
        )

        def audit():
            observed = datetime.now(SHANGHAI)
            delivery = load_evidence(instance, selected, DAY, observed)
            rows = make_summary(
                DAY,
                observed,
                selected,
                delivery,
                qfq_successful_deliveries={gold},
            )["rows"]
            return {row["scope"]["asset_key"]: row for row in rows}

        complete = audit()
        assert complete[silver]["completeness"]["status"] == "complete"
        assert complete[gold]["completeness"]["status"] == "complete"
        assert complete[gold]["completeness"]["actual_count"] == 34
        assert complete[gold]["version"]["inputs"][0]["asset_key"] == silver
        _materialize(instance, digest=None, key=raw_one)
        changed = audit()
        assert changed[silver]["completeness"]["status"] == "pending"
        assert changed[gold]["completeness"]["status"] == "pending"
        assert changed[gold]["update"]["status"] == "updated"


def test_silver_minutes_reports_missing_bars_without_blocking_original_reference_check(
    tmp_path,
):
    daily = silver_stock_daily_path(tmp_path, PARTITION)
    minute = silver_stk_mins_path(tmp_path, 60, PARTITION)
    daily.parent.mkdir(parents=True)
    minute.parent.mkdir(parents=True)
    with duckdb.connect() as db:
        db.execute(
            "COPY (SELECT '600000.SH' AS ts_code, DATE '2026-11-20' AS trade_date) TO ?",
            [str(daily)],
        )
        db.execute(
            "COPY (SELECT '600000.SH' AS ts_code, TIMESTAMP '2026-11-20 09:30:00' "
            "+ offset_hours * INTERVAL '1 HOUR' AS trade_time FROM range(4) t(offset_hours)) TO ?",
            [str(minute)],
        )
    result = _silver_codes_exist_in_stock_daily(
        context=SimpleNamespace(partition_key=PARTITION),
        lake_root=LakeRootResource(root_path=str(tmp_path)),
        duckdb=DuckDBResource(),
        freq=60,
        include_coverage=True,
    )
    assert result.passed
    proof = result.metadata["goldenshare/audit_coverage"].value
    assert proof["status"] == "gap"
    assert (proof["expected_count"], proof["actual_count"]) == (5, 4)


def test_late_daily_input_refreshes_only_the_existing_nineturn_check(tmp_path):
    asset = "raw_tushare_stk_nineturn"
    check_name = "raw_tushare_stk_nineturn_content_integrity_check"
    daily = "silver_stock_daily"
    root = tmp_path / "lake"
    path = silver_stock_daily_path(root, PARTITION)
    path.parent.mkdir(parents=True)
    path.touch()
    target_version = [2, 3, 4, 5, 6]
    with (
        dg.DagsterInstance.local_temp(
            str(tmp_path), overrides={"telemetry": {"enabled": False}}
        ) as instance,
        dg.build_sensor_context(instance=instance) as context,
    ):
        producer = _materialize(
            instance,
            digest=None,
            key=asset,
            published={"goldenshare/audit_file_version": target_version},
            checks=[(check_name, True)],
        )
        assert (
            late_stock_daily_coverage_request(
                context,
                datetime.now(SHANGHAI),
                root,
                PARTITION,
                asset,
            )
            is None
        )
        daily_version = stat_version(path)
        _materialize(
            instance,
            digest=None,
            key=daily,
            published={"goldenshare/audit_file_version": daily_version},
            checks=[(name, True) for name in SILVER_STOCK_DAILY_CHECKS],
        )
        request = late_stock_daily_coverage_request(
            context,
            datetime.now(SHANGHAI),
            root,
            PARTITION,
            asset,
        )
        assert request.partition_key == PARTITION
        assert request.asset_selection == []
        assert request.asset_check_keys == [
            dg.AssetCheckKey(dg.AssetKey(asset), check_name)
        ]
        assert request.tags["audit/target_file_version"] == "[2,3,4,5,6]"

        partitions = dg.StaticPartitionsDefinition([PARTITION])
        asset_spec = dg.AssetSpec(asset, partitions_def=partitions)

        @dg.asset_check(
            asset=asset_spec.key, name=check_name, partitions_def=partitions
        )
        def check_only():
            return dg.AssetCheckResult(
                passed=True,
                metadata={
                    "goldenshare/audit_coverage": {
                        "inputs": {
                            daily: "[" + ",".join(map(str, daily_version)) + "]"
                        },
                        "file_version": target_version,
                    }
                },
            )

        @dg.asset(name=asset, partitions_def=partitions)
        def raw():
            raise AssertionError(
                "the producer must not be selected for a coverage refresh"
            )

        job = dg.define_asset_job("raw_update", selection=dg.AssetSelection.assets(raw))
        full_job = dg.Definitions(
            assets=[raw], asset_checks=[check_only], jobs=[job]
        ).resolve_job_def("raw_update")
        request = request.with_resolved_tags_and_config(
            target_definition=full_job,
            dynamic_partitions_store=instance,
            dynamic_partitions_requests=[],
        )
        run = full_job.get_subset(
            asset_selection=set(request.asset_selection),
            asset_check_selection=set(request.asset_check_keys),
        ).execute_in_process(instance=instance, tags=request.tags)
        assert run.success
        assert run.get_asset_materialization_events() == []
        evidence = load_evidence(
            instance, (_targets()[asset],), DAY, datetime.now(SHANGHAI)
        )[asset]
        assert evidence.materialization.run_id == producer.run_id
        assert evidence.checks[check_name].run_id == run.run_id
        assert (
            late_stock_daily_coverage_request(
                context,
                datetime.now(SHANGHAI),
                root,
                PARTITION,
                asset,
            )
            is None
        )


def test_native_summary_and_exact_version_consumption(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "read_calendar", lambda root, day: CALENDAR)
    with dg.DagsterInstance.local_temp(
        str(tmp_path), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        check = "raw_tushare_dc_member_core_check"
        delivery = _materialize(instance, digest=DIGEST, checks=[(check, True)])
        config = {
            "ops": {
                "generate_data_audit_summary": {"config": {"business_date": PARTITION}}
            }
        }
        result = jobs.daily_data_audit_summary_job.execute_in_process(
            instance=instance, run_config=config
        )
        assert result.success
        summary = read_summary(instance, DAY)
        assert len(summary["rows"]) == sum(summary["summary"].values()) == 187
        row = next(row for row in summary["rows"] if row["scope"]["asset_key"] == RAW)
        assert row["update"]["status"] == "updated"
        assert row["completeness"]["status"] == "complete"
        assert row["completeness"]["evidence"][-1]["run_id"] == delivery.run_id
        assert (
            get_completeness(instance, row["scope"], row["version"])
            == row["completeness"]
        )
        assert (
            get_completeness(
                instance, row["scope"], {**row["version"], "target_version": "b" * 64}
            )
            is None
        )
        assert (
            get_completeness(
                instance, {**row["scope"], "frequency": "月线"}, row["version"]
            )
            is None
        )
        assert (
            get_completeness(
                instance,
                row["scope"],
                {**row["version"], "inputs": [{"target_version": "b" * 64}]},
            )
            is None
        )
        assert (
            get_completeness(
                instance, row["scope"], {**row["version"], "rule_version": "other"}
            )
            is None
        )

        _materialize(instance, digest="b" * 64)
        refresh = dg.RunConfig(
            ops={
                "generate_data_audit_summary": jobs.SummaryConfig(
                    business_date=PARTITION, changed_asset_keys=[RAW]
                )
            }
        )
        result = jobs.daily_data_audit_summary_job.execute_in_process(
            instance=instance, run_config=refresh
        )
        assert result.success
        new = read_summary(instance, DAY)
        previous = {row["scope"]["asset_key"]: row for row in summary["rows"]}
        current = {row["scope"]["asset_key"]: row for row in new["rows"]}
        assert current[RAW]["completeness"]["status"] == "pending"
        assert current[RAW]["version"]["target_version"] == "b" * 64
        assert current[RAW]["update"]["status"] == "updated"
        assert current["silver_dc_member"] == previous["silver_dc_member"]
        assert get_completeness(instance, row["scope"], row["version"]) is None


def test_native_evidence_retains_failed_check_and_does_not_infer_gap(tmp_path):
    with dg.DagsterInstance.local_temp(
        str(tmp_path), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        _materialize(
            instance,
            digest=DIGEST,
            checks=[("raw_tushare_dc_member_core_check", False)],
        )
        now = datetime.now(SHANGHAI)
        target = (_targets()[RAW],)
        evidence = load_evidence(instance, target, DAY, now)
        row = make_summary(DAY, now, target, evidence)["rows"][0]
        assert row["update"]["status"] == "updated"
        assert row["completeness"]["status"] == "pending"
        assert row["completeness"]["evidence"][-1]["passed"] is False


def test_midnight_schedule_uses_previous_natural_day():
    evaluation = jobs.daily_data_audit_summary_schedule.evaluate_tick(
        dg.build_schedule_context(
            scheduled_execution_time=datetime(2026, 11, 21, tzinfo=SHANGHAI),
        )
    )
    assert evaluation.run_requests[0].tags["audit/business_date"] == PARTITION
    assert (
        jobs.daily_data_audit_summary_schedule.default_status
        == dg.DefaultScheduleStatus.STOPPED
    )
    assert (
        jobs.daily_data_audit_summary_refresh_sensor.default_status
        == dg.DefaultSensorStatus.STOPPED
    )


def test_historical_shared_partition_does_not_reuse_next_days_release(tmp_path):
    key = "silver_index_monthly"
    target = (_targets()[key],)
    with dg.DagsterInstance.local_temp(
        str(tmp_path), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        old = _materialize(
            instance,
            digest=DIGEST,
            key=key,
            partition="2026-11",
            published={
                "goldenshare/trade_date": PARTITION,
            },
        )
        _materialize(
            instance,
            digest="b" * 64,
            key=key,
            partition="2026-11",
            published={
                "goldenshare/trade_date": "2026-11-23",
                "goldenshare/period_end": PARTITION,
            },
        )
        now = datetime.now(SHANGHAI)
        evidence = load_evidence(instance, target, DAY, now)
        row = make_summary(DAY, now, target, evidence)["rows"][0]
        assert row["update"]["status"] == "updated"
        assert row["scope"]["as_of_date"] == PARTITION
        assert row["completeness"]["evidence"][0]["run_id"] == old.run_id


def test_index_period_missing_daily_publication_uses_midnight_deadline(tmp_path):
    target = (_targets()["silver_index_monthly"],)
    with dg.DagsterInstance.local_temp(
        str(tmp_path), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        for hour, minute, status in ((23, 59, "not_due"), (0, 0, "overdue")):
            day = 20 if hour else 21
            observed = datetime(2026, 11, day, hour, minute, tzinfo=SHANGHAI)
            evidence = load_evidence(instance, target, DAY, observed)
            row = make_summary(DAY, observed, target, evidence)["rows"][0]
            assert row["update"]["status"] == status
            assert row["completeness"]["status"] == "pending"

        unavailable = make_summary(DAY, observed, target, {})["rows"][0]
        assert unavailable["update"]["status"] == "unknown"
        assert row["completeness"]["status"] == "pending"


def test_cutoff_and_no_evidence_do_not_share_update_status():
    target = (_targets()[RAW],)
    from orchestrator.defs.daily_data_audit.evidence import DeliveryEvidence

    before = datetime(2026, 11, 20, 23, 59, tzinfo=SHANGHAI)
    after = datetime(2026, 11, 21, 0, 0, tzinfo=SHANGHAI)
    no_delivery = {RAW: DeliveryEvidence()}
    assert (
        make_summary(DAY, before, target, no_delivery)["rows"][0]["update"]["status"]
        == "not_due"
    )
    assert (
        make_summary(DAY, after, target, no_delivery)["rows"][0]["update"]["status"]
        == "overdue"
    )
    assert (
        make_summary(DAY, after, target, {})["rows"][0]["update"]["status"] == "unknown"
    )


def test_refresh_sensor_picks_up_new_evidence_for_an_existing_day(
    tmp_path, monkeypatch
):
    now = datetime.now(SHANGHAI)
    day = now.date() - timedelta(days=1)
    formatted = day.isoformat()
    monkeypatch.setattr(jobs, "read_calendar", lambda root, day: {day: True})
    with dg.DagsterInstance.local_temp(
        str(tmp_path), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        config = dg.RunConfig(
            ops={
                "generate_data_audit_summary": jobs.SummaryConfig(
                    business_date=formatted
                )
            }
        )
        assert jobs.daily_data_audit_summary_job.execute_in_process(
            instance=instance, run_config=config
        ).success
        _materialize(instance, digest=DIGEST, partition=formatted)

        @dg.asset(name=RAW)
        def member():
            pass

        @dg.asset(name="silver_dc_member", deps=[member])
        def silver():
            pass

        repository = dg.Definitions(
            assets=[member, silver],
            jobs=[jobs.daily_data_audit_summary_job],
            sensors=[jobs.daily_data_audit_summary_refresh_sensor],
        ).get_repository_def()
        context = dg.build_sensor_context(instance=instance, repository_def=repository)
        evaluation = jobs.daily_data_audit_summary_refresh_sensor.evaluate_tick(context)
        request = evaluation.run_requests[0]
        assert request.tags["audit/business_date"] == formatted
        selected = request.run_config["ops"]["generate_data_audit_summary"]["config"][
            "changed_asset_keys"
        ]
        assert selected == [RAW, "silver_dc_member"]
        assert jobs.daily_data_audit_summary_job.execute_in_process(
            instance=instance, run_config=request.run_config
        ).success
        assert not jobs.daily_data_audit_summary_refresh_sensor.evaluate_tick(
            context
        ).run_requests


def test_legacy_check_uses_its_exact_materialization_when_partition_is_omitted(
    tmp_path,
):
    target = (_targets()[RAW],)
    name = "raw_tushare_dc_member_core_check"
    with dg.DagsterInstance.local_temp(
        str(tmp_path), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        release = _materialize(
            instance, digest=DIGEST, checks=[(name, True)], legacy_checks=True
        )
        now = datetime.now(SHANGHAI)
        evidence = load_evidence(instance, target, DAY, now)
        assert evidence[RAW].checks[name].partition is None
        row = make_summary(DAY, now, target, evidence)["rows"][0]
        assert row["completeness"]["evidence"][-1]["run_id"] == release.run_id
        assert row["completeness"]["status"] == "complete"

        _materialize(instance, digest="b" * 64)
        now = datetime.now(SHANGHAI)
        evidence = load_evidence(instance, target, DAY, now)
        assert not evidence[RAW].checks
        assert (
            make_summary(DAY, now, target, evidence)["rows"][0]["completeness"][
                "status"
            ]
            == "pending"
        )


def test_etf_basic_uses_only_the_raw_snapshot_bound_by_silver(tmp_path):
    raw_key, silver_key = "raw_tushare_etf_basic", "silver_etf_basic"
    targets = tuple(
        t for t in _targets().values() if t.asset_key in {raw_key, silver_key}
    )
    with dg.DagsterInstance.local_temp(
        str(tmp_path), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        _materialize(
            instance,
            key=raw_key,
            digest=None,
            partition=None,
            published={
                "goldenshare/trade_date": PARTITION,
                "goldenshare/raw_snapshot_hash": DIGEST,
            },
            checks=[(name, True) for name in _targets()[raw_key].check_names],
        )
        _materialize(
            instance,
            key=silver_key,
            digest=None,
            partition=None,
            published={
                "goldenshare/trade_date": PARTITION,
                "goldenshare/raw_snapshot_hash": DIGEST,
                "goldenshare/silver_content_hash": "b" * 64,
            },
            checks=[(name, True) for name in _targets()[silver_key].check_names],
        )
        now = datetime.now(SHANGHAI)
        rows = {
            r["scope"]["asset_key"]: r
            for r in make_summary(
                DAY, now, targets, load_evidence(instance, targets, DAY, now)
            )["rows"]
        }
        assert rows[silver_key]["completeness"]["status"] == "complete"
        assert rows[silver_key]["version"]["inputs"][0]["target_version"] == DIGEST

        _materialize(
            instance,
            key=raw_key,
            digest=None,
            partition=None,
            published={
                "goldenshare/trade_date": PARTITION,
                "goldenshare/raw_snapshot_hash": "c" * 64,
            },
            checks=[(name, True) for name in _targets()[raw_key].check_names],
        )
        now = datetime.now(SHANGHAI)
        rows = {
            r["scope"]["asset_key"]: r
            for r in make_summary(
                DAY, now, targets, load_evidence(instance, targets, DAY, now)
            )["rows"]
        }
        assert rows[raw_key]["completeness"]["status"] == "complete"
        assert rows[silver_key]["completeness"]["status"] == "pending"


def test_major_index_raw_requires_the_produced_source_revision_and_matching_scope(
    tmp_path,
):
    key = "raw_major_index_mins_1m"
    target = (_targets()[key],)
    uri = "major-index/2026-11-20/part-000.parquet"
    published = {
        "dagster/uri": uri,
        "goldenshare/write_mode": "staged_atomic_replace",
        "goldenshare/scope_hash": "scope-2026-11-20",
        "goldenshare/source_revision": DIGEST,
        "goldenshare/source_row_count": 2410,
        "goldenshare/output_row_count": 2410,
    }
    with dg.DagsterInstance.local_temp(
        str(tmp_path), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        for scope, status in (
            ("scope-2026-11-19", "pending"),
            ("scope-2026-11-20", "complete"),
        ):
            _materialize(
                instance,
                key=key,
                digest=None,
                published=published,
                checks=[(f"{key}_core_check", True)],
                check_metadata={
                    "goldenshare/scope_hash": scope,
                    "goldenshare/file_path": uri,
                    "goldenshare/checked_row_count": 2410,
                },
            )
            now = datetime.now(SHANGHAI)
            row = make_summary(
                DAY, now, target, load_evidence(instance, target, DAY, now)
            )["rows"][0]
            assert row["completeness"]["status"] == status


def test_local_clickhouse_delivery_uses_the_trading_day_partition():
    targets = _targets()
    for key in ("ch_share_fact_market_breadth_daily", "ch_dc_daily_technical"):
        assert targets[key].partition == PARTITION
        assert not targets[key].exact_as_of


def test_moneyflow_conversion_claim_requires_the_same_raw_version(tmp_path):
    raw_key, silver_key = "raw_tushare_moneyflow", "silver_moneyflow"
    targets = tuple(
        t for t in _targets().values() if t.asset_key in {raw_key, silver_key}
    )
    with dg.DagsterInstance.local_temp(
        str(tmp_path), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        _materialize(instance, key=raw_key, digest=DIGEST)
        for raw_version, reason in (
            ("c" * 64, "not_verified"),
            (DIGEST, "upstream_parity_only"),
        ):
            _materialize(
                instance,
                key=silver_key,
                digest="b" * 64,
                published={"goldenshare/raw_sha256": raw_version},
                checks=[("silver_moneyflow_standardization_check", True)],
            )
            now = datetime.now(SHANGHAI)
            result = make_summary(
                DAY, now, targets, load_evidence(instance, targets, DAY, now)
            )
            silver = next(
                row for row in result["rows"] if row["scope"]["asset_key"] == silver_key
            )
            assert silver["completeness"]["status"] == "pending"
            assert silver["completeness"]["reason"]["code"] == reason
            assert bool(silver["version"]["inputs"]) == (raw_version == DIGEST)
