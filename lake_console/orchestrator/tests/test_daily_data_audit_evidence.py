import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import dagster as dg
import duckdb
import pytest

from orchestrator.defs.catalog.lake_assets import SILVER_STOCK_DAILY_CHECKS
from orchestrator.defs.checks.daily_audit_coverage import stat_version
from orchestrator.defs.checks.stk_mins_checks import _silver_codes_exist_in_stock_daily
from orchestrator.defs.daily_data_audit import jobs
from orchestrator.defs.daily_data_audit.board_jobs import (
    daily_data_audit_board_confirm_job,
)
from orchestrator.defs.daily_data_audit.board_summary import BOARD_CHECKS, RAW_MONEYFLOW
from orchestrator.defs.daily_data_audit.dc_index_review import (
    BOARD_RECHECK_JOB,
    BOARD_RECHECK_META,
    REVIEW_VERSION_TAG,
)
from orchestrator.defs.daily_data_audit.evidence import (
    SHANGHAI,
    find_audit_changes,
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
from orchestrator.defs.sensors.dc_board_sensor import _automatic_board_standard
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
    digest=None,
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
        metadata = dict(published or {})
        if digest is not None:
            metadata["goldenshare/file_sha256"] = digest
        return dg.MaterializeResult(metadata=metadata)

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


def test_refresh_reuses_native_daily_index_input_and_rejects_another_release(tmp_path, monkeypatch):
    raw, silver = "raw_index_daily", "silver_index_daily"
    targets = _targets()
    monkeypatch.setattr(jobs, "read_calendar", lambda *_: CALENDAR)
    monkeypatch.setattr(jobs, "DEFAULT_LAKE_ROOT", str(tmp_path))

    @dg.asset(name=silver, deps=[raw], partitions_def=dg.StaticPartitionsDefinition([PARTITION]))
    def silver_output():
        return dg.MaterializeResult(metadata={"dagster/row_count": 1})

    def silver_check(name):
        @dg.asset_check(asset=silver_output, name=name)
        def check():
            return dg.AssetCheckResult(passed=True)
        return check

    with dg.DagsterInstance.local_temp(
        str(tmp_path), overrides={"telemetry": {"enabled": False}},
    ) as instance:
        def publish_raw():
            return _materialize(
                instance, key=raw, partition=PARTITION,
                checks=[(name, True) for name in targets[raw].check_names],
                published={"goldenshare/expected_code_set_hash": DIGEST, "dagster/row_count": 1},
            )

        def summary(*changed):
            assert jobs.daily_data_audit_summary_job.execute_in_process(
                instance=instance,
                run_config={"ops": {"generate_data_audit_summary": {"config": {
                    "business_date": PARTITION, "changed_asset_keys": list(changed),
                }}}},
            ).success
            return {row["scope"]["asset_key"]: row for row in read_summary(instance, DAY)["rows"]}

        assert publish_raw().success
        assert dg.materialize(
            [dg.AssetSpec(raw, partitions_def=silver_output.partitions_def), silver_output,
             *(silver_check(name) for name in targets[silver].check_names)],
            selection=[silver], partition_key=PARTITION, instance=instance,
        ).success
        before = summary()[silver]
        assert before["completeness"]["status"] == "complete"
        assert before["version"]["target_version"] is None
        assert any(item.get("asset_key") == raw for item in before["completeness"]["evidence"])

        assert publish_raw().success
        after = summary(raw)[silver]
        assert after["update"] == before["update"]
        assert after["completeness"]["reason"]["code"] == "version_mismatch"
        assert after["completeness"]["status"] == "pending"


def test_change_query_uses_actual_as_of_date_not_shared_week_partition(tmp_path):
    day = date(2026, 11, 19)
    key = "silver_index_weekly"
    target = _targets(day)[key]
    check = target.check_names[0]
    with dg.DagsterInstance.local_temp(
        str(tmp_path), overrides={"telemetry": {"enabled": False}},
    ) as instance:
        def publish(as_of, passed=True):
            return _materialize(
                instance, key=key, partition=PARTITION, checks=[(check, passed)],
                published={"goldenshare/trade_date": as_of.isoformat()},
            )

        assert publish(day).success
        observed = datetime.now(SHANGHAI)
        rows = {key: make_summary(day, observed, (target,), load_evidence(
            instance, (target,), day, observed,
        ))["rows"][0]}
        assert publish(DAY).success
        assert find_audit_changes(instance, (target,), rows, day, datetime.now(SHANGHAI)) == {}
        assert publish(day, passed=False).success
        changes = find_audit_changes(instance, (target,), rows, day, datetime.now(SHANGHAI))
        assert list(changes) == [key]
        assert changes[key] > observed.timestamp()


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


@pytest.mark.parametrize("raw_namechange_state", ["ready", "missing", "unchecked", "failed", "different_version"])
def test_namechange_snapshot_reuses_update_only_raw(
    tmp_path, raw_namechange_state,
):
    raw_basic = "raw_tushare_stock_basic"
    basic = "silver_stock_basic"
    lifecycle = "silver_stock_lifecycle"
    raw_names = "raw_tushare_namechange"
    names = "silver_namechange"
    identity = "silver_stock_identity_map"
    targets = _targets()
    assets = (raw_basic, basic, lifecycle, raw_names, names, identity)
    versions = {key: [1, number, 100, 200, 200] for number, key in enumerate(assets, 1)}
    previous_day = date(2026, 11, 19)

    with dg.DagsterInstance.local_temp(
        str(tmp_path), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        def publish(key, *, day=DAY, checks=None, version=None, inputs=None):
            file_version = versions[key] if version is None else version
            coverage = {
                "status": "complete",
                "file_version": file_version,
                "inputs": inputs,
                "expected_count": 3,
                "actual_count": 3,
                "missing_count": 0,
                "extra_count": 0,
                "samples": [],
                "rule_version": "stock_snapshot_projection_v1",
            }
            return _materialize(
                instance,
                key=key,
                partition=None,
                checks=[(name, True) for name in targets[key].check_names] if checks is None else checks,
                published={
                    "goldenshare/trade_date": day.isoformat(),
                    "goldenshare/audit_file_version": file_version,
                    "goldenshare/params": {"list_status": "L,D,P,G"},
                    "dagster/row_count": 3,
                },
                check_metadata={"goldenshare/audit_coverage": coverage} if inputs is not None else None,
            )

        publish(raw_basic, day=previous_day)
        publish(raw_basic)
        upstream = {raw_basic: json.dumps(versions[raw_basic], separators=(",", ":"))}
        publish(basic, inputs=upstream)
        publish(lifecycle, inputs=upstream)
        checks = [(name, True) for name in targets[raw_names].check_names]
        if raw_namechange_state == "unchecked":
            checks.pop()
        elif raw_namechange_state == "failed":
            checks[-1] = (checks[-1][0], False)
        if raw_namechange_state != "missing":
            publish(
                raw_names, checks=checks,
                version=[1, 99, 100, 200, 200] if raw_namechange_state == "different_version" else None,
            )
        publish(names, inputs={
            key: json.dumps(versions[key], separators=(",", ":")) for key in (raw_names, basic)
        })
        publish(identity, inputs={
            **{key: json.dumps(versions[key], separators=(",", ":")) for key in (names, lifecycle)},
            "股票身份映射规则": "stock_identity_mappings.cn_a.v1",
        })
        selected = tuple(targets[key] for key in assets)
        observed = datetime.now(SHANGHAI)
        evidence = load_evidence(instance, selected, DAY, observed)
        previous = load_evidence(
            instance, (_targets(previous_day)[raw_basic],), previous_day, observed
        )[raw_basic]
        report = make_summary(
            DAY, observed, selected, evidence,
            previous_stock_basic=previous, stock_basic_runs_succeeded=True,
        )

    rows = {row["scope"]["asset_key"]: row for row in report["rows"]}
    assert rows[raw_names]["completeness"]["status"] == "not_applicable"
    assert rows[basic]["completeness"]["status"] == "complete"
    assert rows[lifecycle]["completeness"]["status"] == "complete"
    expected = "complete" if raw_namechange_state == "ready" else "pending"
    assert rows[names]["completeness"]["status"] == expected
    assert rows[identity]["completeness"]["status"] == expected


def test_stock_basic_tolerance_uses_previous_trading_day_not_previous_run(tmp_path, monkeypatch):
    key = "raw_tushare_stock_basic"
    prior_day = date(2026, 11, 19)
    target = _targets()[key]
    monkeypatch.setattr(jobs, "read_calendar", lambda root, day: CALENDAR)
    with dg.DagsterInstance.local_temp(
        str(tmp_path), overrides={"telemetry": {"enabled": False}}
    ) as instance:

        def publish(day, count, scope="L,D,P,G", checks_pass=True):
            return _materialize(
                instance,
                key=key,
                partition=None,
                checks=[(name, checks_pass) for name in target.check_names],
                published={
                    "goldenshare/trade_date": day.isoformat(),
                    "goldenshare/params": {"list_status": scope},
                    "dagster/row_count": count,
                },
                fail_run=not checks_pass,
            )

        prior = publish(prior_day, 6000)
        for count, scope, checks_pass, status in (
            (6020, "L,D,P,G", True, "complete"),
            (6021, "L,D,P,G", True, "pending"),
            (5979, "L,D,P,G", True, "pending"),
            (6000, "L", True, "pending"),
            (6000, "L,D,P,G", False, "pending"),
        ):
            delivery = publish(DAY, count, scope, checks_pass)
            assert delivery.success is checks_pass
            result = jobs.daily_data_audit_summary_job.execute_in_process(
                instance=instance,
                run_config={"ops": {"generate_data_audit_summary": {"config": {"business_date": PARTITION}}}},
            )
            assert result.success
            row = next(row for row in read_summary(instance, DAY)["rows"] if row["scope"]["asset_key"] == key)
            assert row["update"]["status"] == "updated"
            assert row["completeness"]["status"] == status
            assert row["version"]["target_version"] is None
            if status == "complete":
                assert any(proof["run_id"] == prior.run_id for proof in row["completeness"]["evidence"])


@pytest.mark.parametrize(
    ("key", "partition", "metadata", "expected_update"),
    [
        ("gold_major_index_quantitative_structure", PARTITION, {"goldenshare/event_count": 0}, "updated"),
        ("silver_dc_member", PARTITION, {}, "updated"),
        ("silver_dc_industry_hierarchy", None, {"goldenshare/code_reference_trade_date": "2026-07-31"}, "not_required"),
        ("gold_major_index_mins_5m", PARTITION, {"goldenshare/expected_code_count": 10}, "updated"),
        ("gold_major_index_mins_technical_state_5m", PARTITION, {}, "updated"),
        ("raw_index_daily", PARTITION, {"goldenshare/expected_code_set_hash": "a" * 32}, "updated"),
    ],
)
def test_daily_summary_reuses_checks_on_the_exact_publication(
    tmp_path, key, partition, metadata, expected_update,
):
    audit_day = DAY if partition is not None else datetime.now(SHANGHAI).date()
    target = _targets(audit_day)[key]
    with dg.DagsterInstance.local_temp(
        str(tmp_path), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        original = _materialize(
            instance, key=key, partition=partition, published=metadata,
            checks=[(name, True) for name in target.check_names],
        )

        def latest_row():
            now = datetime.now(SHANGHAI)
            evidence = load_evidence(instance, (target,), audit_day, now)
            return make_summary(audit_day, now, (target,), evidence)["rows"][0]

        row = latest_row()
        assert row["update"]["status"] == expected_update
        assert row["completeness"]["status"] == "complete"
        assert row["version"]["target_version"] is None
        assert {proof["run_id"] for proof in row["completeness"]["evidence"]} == {original.run_id}

        _materialize(instance, key=key, partition=partition, published=metadata)
        assert latest_row()["completeness"]["status"] == "pending"


def test_daily_summary_keeps_raw_index_coverage_with_missing_scope_or_failed_check_pending(tmp_path):
    key = "raw_index_daily"
    target = _targets()[key]
    coverage = "raw_index_daily_code_coverage_check"
    with dg.DagsterInstance.local_temp(
        str(tmp_path), overrides={"telemetry": {"enabled": False}}
    ) as instance:
        for metadata, checks in (
            ({}, [(name, True) for name in target.check_names]),
            ({"goldenshare/expected_code_set_hash": "a" * 32}, [(name, name != coverage) for name in target.check_names]),
        ):
            _materialize(instance, key=key, published=metadata, checks=checks)
            now = datetime.now(SHANGHAI)
            evidence = load_evidence(instance, (target,), DAY, now)
            row = make_summary(DAY, now, (target,), evidence)["rows"][0]
            assert row["update"]["status"] == "updated"
            assert row["completeness"]["status"] == "pending"


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
        _materialize(instance, key="silver_dc_member", checks=[("silver_dc_member_core_check", True)])
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
        silver = next(row for row in summary["rows"] if row["scope"]["asset_key"] == "silver_dc_member")
        assert silver["completeness"]["status"] == "complete"
        assert silver["version"]["target_version"] is None
        assert get_completeness(instance, silver["scope"], silver["version"]) is None
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
    assert jobs.daily_data_audit_summary_schedule.cron_schedule == "0 0 * * *"
    assert jobs.daily_data_audit_summary_schedule.execution_timezone == "Asia/Shanghai"
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


def test_summary_refresh_sensor_uses_a_ten_minute_minimum_interval():
    assert jobs.daily_data_audit_summary_refresh_sensor.minimum_interval_seconds == 600
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


def test_board_confirmation_and_late_check_refresh_only_the_selected_day(tmp_path, monkeypatch):
    day = date(2026, 11, 19)
    partition = day.isoformat()
    raw = "raw_tushare_dc_index"
    silver = "silver_dc_index"
    boards = [
        {"category": "行业板块", "code": "BK0101.DC", "name": "行业样本"},
        {"category": "地域板块", "code": "BK0201.DC", "name": "地域样本"},
        {"category": "概念板块", "code": "BK0301.DC", "name": "概念样本"},
    ]
    target_version = [2, 3, 4, 5, 6]
    monkeypatch.setattr(jobs, "read_calendar", lambda _root, _day: CALENDAR)
    repo = dg.Definitions(
        jobs=[jobs.daily_data_audit_summary_job, daily_data_audit_board_confirm_job],
        sensors=[jobs.daily_data_audit_summary_refresh_sensor],
    ).get_repository_def()

    def audit(instance, config):
        assert jobs.daily_data_audit_summary_job.execute_in_process(
            instance=instance, run_config=config,
        ).success
        return read_summary(instance, day)

    def evaluate(instance, cursor=None):
        context = dg.build_sensor_context(instance=instance, repository_def=repo, cursor=cursor)
        return jobs.daily_data_audit_summary_refresh_sensor.evaluate_tick(context)

    def rows(report):
        return {row["scope"]["asset_key"]: row for row in report["rows"]}

    with dg.DagsterInstance.local_temp(str(tmp_path), overrides={"telemetry": {"enabled": False}}) as instance:
        run = _materialize(
            instance, digest=DIGEST, key=raw, partition=partition,
            checks=[(BOARD_CHECKS[raw], True)],
            published={"goldenshare/tushare_source_fingerprint": DIGEST},
            check_metadata={"goldenshare/board_classification_codes": boards},
        )
        _materialize(
            instance, digest=DIGEST, key=silver, partition=partition,
            checks=[(BOARD_CHECKS[silver], True)],
            published={"goldenshare/board_classification_input": {"target_version": target_version}},
            check_metadata={
                "goldenshare/board_classification_codes": boards,
                "goldenshare/board_parity": {
                    "raw_run_id": run.run_id, "status": "complete", "target_version": target_version,
                },
            },
        )
        flow = _materialize(
            instance, digest=DIGEST, key=RAW_MONEYFLOW, partition=partition,
            checks=[(BOARD_CHECKS[RAW_MONEYFLOW], True)],
        )
        before = audit(instance, {"ops": {"generate_data_audit_summary": {
            "config": {"business_date": partition}
        }}})
        idle = evaluate(instance)
        assert not idle.run_requests
        confirm = daily_data_audit_board_confirm_job.execute_in_process(
            instance=instance, run_config={"ops": {"save_dc_index_standard": {"config": {
                "business_date": partition, "requested_by": "isolated-test", "use_history": True,
            }}}},
        )
        assert confirm.success
        after_confirmation = evaluate(instance, idle.cursor)
        [request] = after_confirmation.run_requests
        assert request.run_key == (
            f"daily_data_audit_summary_job:board-confirm:{partition}:{confirm.run_id}"
        )
        assert request.tags["audit/business_date"] == partition

        def no_calendar_read(*args):
            raise AssertionError("board-only refresh must use DG records only")

        monkeypatch.setattr(jobs, "read_calendar", no_calendar_read)
        updated = audit(instance, request.run_config)
        assert updated["board_standard_version"] == confirm.run_id
        assert rows(updated)[raw]["completeness"]["status"] == "complete"
        assert rows(updated)[silver]["completeness"]["status"] == "complete"
        assert rows(updated)[RAW_MONEYFLOW]["completeness"]["status"] == "pending"
        assert all(
            row["update"] == rows(before)[key]["update"]
            and row["observed_at"] == rows(before)[key]["observed_at"]
            for key, row in rows(updated).items()
        )
        assert all(row == rows(before)[key] for key, row in rows(updated).items() if key not in BOARD_CHECKS)
        next_day = date(2026, 11, 20).isoformat()
        _materialize(
            instance, digest=DIGEST, key=raw, partition=next_day, checks=[(BOARD_CHECKS[raw], True)],
            published={"goldenshare/tushare_source_fingerprint": DIGEST},
            check_metadata={"goldenshare/board_classification_codes": boards},
        )
        request_next = _automatic_board_standard(
            instance, (partition, next_day),
            SimpleNamespace(status_for_trade_date=lambda _: SimpleNamespace(ready=True)),
        )
        assert request_next.job_name == "daily_data_audit_board_confirm_job"
        assert request_next.partition_key is None
        config_next = request_next.run_config["ops"]["save_dc_index_standard"]["config"]
        assert config_next["business_date"] == next_day
        assert request_next.run_key == (
            f"daily_data_audit_board_confirm_job:{next_day}:{config_next['review_version']}"
        )

        partitions = dg.StaticPartitionsDefinition([partition])

        @dg.asset(name=RAW_MONEYFLOW, partitions_def=partitions)
        def flow_asset():
            raise AssertionError("the production asset is outside the Check-only selection")

        @dg.asset_check(asset=flow_asset, name=BOARD_CHECKS[RAW_MONEYFLOW], partitions_def=partitions)
        def late_check():
            if fail_check:
                return dg.AssetCheckResult(passed=False)
            return dg.AssetCheckResult(passed=True, metadata={"goldenshare/board_coverage": {
                "raw_run_id": flow.run_id, "file_version": DIGEST, "standard_version": confirm.run_id,
                "status": "complete", "expected_count": 3, "actual_count": 3,
                "missing_codes": [], "extra_codes": [],
            }})

        job = dg.define_asset_job("isolated_flow", selection=dg.AssetSelection.assets(flow_asset))
        full_job = dg.Definitions(
            assets=[flow_asset], asset_checks=[late_check], jobs=[job],
        ).resolve_job_def("isolated_flow")
        only_check = full_job.get_subset(
            asset_selection=set(), asset_check_selection={
                dg.AssetCheckKey(flow_asset.key, BOARD_CHECKS[RAW_MONEYFLOW])
            },
        )
        fail_check = False
        checked = only_check.execute_in_process(instance=instance, partition_key=partition)
        assert checked.success and not checked.get_asset_materialization_events()

        # Each tick consumes at most one Check record; other business dates cannot update this report.
        current = after_confirmation
        for _ in range(4):
            current = evaluate(instance, current.cursor)
            if current.run_requests:
                break
        [refresh] = current.run_requests
        assert refresh.run_key == (
            f"daily_data_audit_summary_job:board-check:{partition}:{confirm.run_id}:"
            f"{checked.run_id}:{BOARD_CHECKS[RAW_MONEYFLOW]}"
        )
        assert refresh.run_config["ops"]["generate_data_audit_summary"]["config"]["changed_asset_keys"] == [
            RAW_MONEYFLOW
        ]
        result = audit(instance, refresh.run_config)
        assert rows(result)[RAW_MONEYFLOW]["completeness"]["status"] == "complete"
        assert result["summary"]["complete"] == updated["summary"]["complete"] + 1
        assert all(row == rows(updated)[key] for key, row in rows(result).items() if key != RAW_MONEYFLOW)

        @dg.asset(name=raw, partitions_def=partitions)
        def classification():
            raise AssertionError("the production asset is outside the Check-only selection")

        @dg.asset_check(asset=classification, name=BOARD_CHECKS[raw], partitions_def=partitions)
        def classification_check():
            return dg.AssetCheckResult(passed=raw_ok, metadata={
                "goldenshare/board_classification_codes": boards,
            } if raw_ok else {})

        raw_check_job = dg.define_asset_job("isolated_raw", selection=dg.AssetSelection.assets(classification))
        raw_check_only = dg.Definitions(
            assets=[classification], asset_checks=[classification_check], jobs=[raw_check_job],
        ).resolve_job_def("isolated_raw").get_subset(
            asset_selection=set(), asset_check_selection={dg.AssetCheckKey(classification.key, BOARD_CHECKS[raw])},
        )

        original = result
        for raw_ok, expected in ((False, "pending"), (True, "complete")):
            checked_raw = raw_check_only.execute_in_process(instance=instance, partition_key=partition)
            current = evaluate(instance, current.cursor)
            [refresh] = current.run_requests
            assert checked_raw.run_id in refresh.run_key
            assert refresh.run_config["ops"]["generate_data_audit_summary"]["config"]["changed_asset_keys"] == list(BOARD_CHECKS)
            result = audit(instance, refresh.run_config)
            assert result["board_standard_version"] == (confirm.run_id if raw_ok else None)
            assert all(rows(result)[key]["completeness"]["status"] == expected for key in BOARD_CHECKS)
            assert all(row["update"] == rows(original)[key]["update"] for key, row in rows(result).items())
            assert all(row == rows(original)[key] for key, row in rows(result).items() if key not in BOARD_CHECKS)

        idle = evaluate(instance, current.cursor)
        assert not idle.run_requests
        fail_check = True
        failed = only_check.execute_in_process(instance=instance, partition_key=partition)
        failure = evaluate(instance, idle.cursor)
        [refresh] = failure.run_requests
        assert failed.run_id in refresh.run_key
        updated_failure = audit(instance, refresh.run_config)
        rejected = rows(updated_failure)[RAW_MONEYFLOW]
        assert rejected["update"] == rows(result)[RAW_MONEYFLOW]["update"]
        assert rejected["completeness"]["status"] == "pending"
        assert rejected["completeness"]["evidence"][0]["passed"] is False
        assert all(
            row == rows(result)[key] for key, row in rows(updated_failure).items() if key != RAW_MONEYFLOW
        )


def test_board_baseline_reports_manual_confirmation(tmp_path, monkeypatch):
    raw = "raw_tushare_dc_index"
    baseline = date(2026, 11, 19)
    monkeypatch.setattr(jobs, "read_calendar", lambda _root, _day: CALENDAR)
    with dg.DagsterInstance.local_temp(str(tmp_path), overrides={"telemetry": {"enabled": False}}) as instance:
        assert _materialize(
            instance, digest=DIGEST, key=raw, partition=baseline.isoformat(),
            checks=[(BOARD_CHECKS[raw], True)],
            published={"goldenshare/tushare_source_fingerprint": DIGEST},
            check_metadata={"goldenshare/board_classification_codes": [
                {"category": "概念板块", "code": "BK0301.DC", "name": "概念样本"},
            ]},
        ).success
        assert jobs.daily_data_audit_summary_job.execute_in_process(
            instance=instance, run_config={"ops": {"generate_data_audit_summary": {"config": {
                "business_date": baseline.isoformat(), "use_board_history": True,
            }}}},
        ).success
        rows = read_summary(instance, baseline)["rows"]
        result = next(row for row in rows if row["scope"]["asset_key"] == raw)
        assert result["completeness"]["status"] == "pending"
        assert any(
            component["reason"]["code"] == "manual_review"
            for component in result["completeness"]["components"]
        )


def test_board_source_gap_and_repaired_historical_publication_refresh(tmp_path, monkeypatch):
    raw = "raw_tushare_dc_index"
    baseline = "2026-11-19"
    boards = [
        {"category": "行业板块", "code": "BK0101.DC", "name": "行业样本"},
        {"category": "概念板块", "code": "BK0301.DC", "name": "概念样本"},
    ]
    monkeypatch.setattr(jobs, "read_calendar", lambda _root, _day: CALENDAR)

    @dg.op(out=dg.Out(dg.Nothing))
    def confirm_source_gap(context):
        context.add_output_metadata({BOARD_RECHECK_META: dg.MetadataValue.json({
            "business_date": PARTITION, "review_version": review_version,
            "run_id": context.run_id, "results": [], "has_confirmed_gap": True,
        })})

    @dg.job(name=BOARD_RECHECK_JOB)
    def isolated_recheck():
        confirm_source_gap()

    repo = dg.Definitions(
        jobs=[jobs.daily_data_audit_summary_job, daily_data_audit_board_confirm_job, isolated_recheck],
        sensors=[jobs.daily_data_audit_summary_refresh_sensor],
    ).get_repository_def()

    def evaluate(instance, cursor=None):
        context = dg.build_sensor_context(instance=instance, repository_def=repo, cursor=cursor)
        return jobs.daily_data_audit_summary_refresh_sensor.evaluate_tick(context)

    def publish(instance, partition, current):
        return _materialize(
            instance, digest=DIGEST, key=raw, partition=partition, checks=[(BOARD_CHECKS[raw], True)],
            published={"goldenshare/tushare_source_fingerprint": DIGEST},
            check_metadata={"goldenshare/board_classification_codes": current},
        )

    def audit(instance, config):
        assert jobs.daily_data_audit_summary_job.execute_in_process(instance=instance, run_config=config).success
        return {row["scope"]["asset_key"]: row for row in read_summary(instance, DAY)["rows"]}

    with dg.DagsterInstance.local_temp(str(tmp_path), overrides={"telemetry": {"enabled": False}}) as instance:
        publish(instance, baseline, boards)
        assert daily_data_audit_board_confirm_job.execute_in_process(
            instance=instance, run_config={"ops": {"save_dc_index_standard": {"config": {
                "business_date": baseline, "requested_by": "isolated-test", "use_history": True,
            }}}},
        ).success
        old = publish(instance, PARTITION, boards[:1])
        rows = audit(instance, {"ops": {"generate_data_audit_summary": {"config": {"business_date": PARTITION}}}})
        assert rows[raw]["completeness"]["status"] == "pending"
        review_version = rows[raw]["board_review"]["review_version"]
        idle = evaluate(instance)
        assert not idle.run_requests
        checked = isolated_recheck.execute_in_process(instance=instance, tags={
            "audit/business_date": PARTITION, REVIEW_VERSION_TAG: review_version,
        })
        observed = evaluate(instance, idle.cursor)
        [refresh] = observed.run_requests
        assert refresh.run_key == f"daily_data_audit_summary_job:board-recheck:{PARTITION}:{review_version}:{checked.run_id}"
        gap = audit(instance, refresh.run_config)
        assert gap[raw]["completeness"]["status"] == "gap"
        assert gap[raw]["update"] == rows[raw]["update"]
        assert all(gap[key] == rows[key] for key in rows if key != raw)

        repaired = publish(instance, PARTITION, boards)
        latest = observed
        for _ in range(3):
            latest = evaluate(instance, latest.cursor)
            if latest.run_requests:
                break
        [refresh] = latest.run_requests
        assert refresh.run_key == f"daily_data_audit_summary_job:board-raw:{PARTITION}:{repaired.run_id}:{repaired.run_id}"
        corrected = audit(instance, refresh.run_config)
        assert corrected[raw]["completeness"]["status"] == "pending"
        assert corrected[raw]["board_review"]["raw_run_id"] != old.run_id
        assert corrected[raw]["board_review"]["raw_run_id"] == repaired.run_id
        assert corrected[raw]["board_review"]["removed"] == []
        assert corrected[raw]["board_review"]["recheck"] is None


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
