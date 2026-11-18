"""指数周期sensor隔离门禁、真实上游及原生分区链；不访问正式资源。"""

import json
import time
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

import dagster as dg
import duckdb
import pytest
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)
from dagster._core.remote_origin import (
    RegisteredCodeLocationOrigin,
    RemoteRepositoryOrigin,
)

from orchestrator.defs.assets import index_daily, index_period
from orchestrator.defs.catalog import get_lake_asset_catalog_entry
from orchestrator.defs.checks import index_daily_checks
from orchestrator.defs.io import index_daily_writer
from orchestrator.defs.jobs.silver_index_daily_update import (
    silver_index_daily_update_job,
)
from orchestrator.defs.partitions import cn_a_index_trade_days, cn_a_index_ts_codes
from orchestrator.defs.paths import raw_index_daily_path, silver_index_daily_path
from orchestrator.defs.run_contracts.index_period import (
    INDEX_MONTHLY,
    INDEX_WEEKLY,
    IndexPeriodSilverConfig,
    build_index_period_silver_run_config,
)
from orchestrator.defs.sensors import index_period_daily_readiness as readiness
from orchestrator.defs.sensors import index_period_update_job_sensors as sensors
from tests.index_period_test_support import daily_input, seed_silver, silver_inputs
from tests.test_index_period_checks import definitions
from tests.test_index_period_contracts import EXPECTED_CODES, fake_source

TZ = ZoneInfo("Asia/Shanghai")
SENSORS = tuple(value for value in vars(sensors).values() if isinstance(value, dg.SensorDefinition))


def instant(day="2026-07-02", hour=19):
    return datetime.fromisoformat(day).replace(hour=hour, tzinfo=TZ)


def emit_delivery(instance, asset, *, day=None, metadata=None, bad=None, inspect=None):
    """原生测试run发事件；手工绿灯只用于门禁反例，真实生产者另测。"""
    names = get_lake_asset_catalog_entry(asset).blocking_check_names

    @dg.op(out={})
    def emit(context):
        context.log_event(dg.AssetMaterialization(asset_key=asset, partition=day, metadata=metadata or {}))
        mat = readiness.latest_index_period_materialization(instance, asset, day)
        for name in names[:-1] if bad == "missing" else names:
            context.log_event(dg.AssetCheckEvaluation(
                asset_key=dg.AssetKey(asset), check_name=name, partition=None,
                passed=bad != "red", blocking=bad != "nonblocking",
                target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                    storage_id=mat.storage_id + int(bad == "other_materialization"),
                    run_id="another-run" if bad == "other_run" else context.run_id,
                    timestamp=mat.timestamp,
                ),
            ))
        if inspect:
            inspect()
        if bad == "failed_run":
            raise RuntimeError("人工失败样本：事件已写而运行未成功")

    @dg.job
    def test_delivery():
        emit()

    return test_delivery.execute_in_process(instance=instance, raise_on_error=False)


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    defs = definitions(monkeypatch, tmp_path)
    silver_inputs(tmp_path / "lake")
    monkeypatch.setattr(index_daily_writer, "gettempdir", lambda: str(tmp_path / "daily_staging"))
    monkeypatch.setattr(index_period.write_index_period_raw.__globals__["TushareDownloader"], "load",
                        lambda: pytest.fail("sensor／Silver不得创建源下载器"))
    monkeypatch.setattr(dg.DagsterInstance, "get", lambda: pytest.fail("不得发现正式instance"))
    with dg.DagsterInstance.ephemeral(tempdir=str(tmp_path / "instance")) as instance:
        emit_delivery(instance, "silver_trade_calendar")
        emit_delivery(instance, "silver_index_basic")
        context = dg.build_sensor_context(instance=instance, resources=defs.resources)
        yield defs, context, instance, tmp_path / "lake"


def tick(context, *, period=INDEX_WEEKLY, layer="silver", day="2026-07-02", hour=19):
    result = sensors.evaluate_index_period_sensor(context, instant(day, hour), period=period, layer=layer)
    assert len(result.run_requests) <= 1 and len(result.dynamic_partitions_requests) <= 1
    assert len(result.cursor.encode()) < 2048
    return result


def reason(result):
    return json.loads(result.cursor)["details"]["reason_code"]


def execute_request(defs, instance, result, asset):
    request = result.run_requests[0]
    for addition in result.dynamic_partitions_requests:
        instance.add_dynamic_partitions(addition.partitions_def_name, addition.partition_keys)
    return defs.resolve_job_def(asset + "_update_job").execute_in_process(
        instance=instance, partition_key=request.partition_key,
        run_config=request.run_config, tags={"dagster/run_key": request.run_key},
        raise_on_error=False,
    )


def test_sensor_definitions_match_four_jobs_and_config_contract():
    assert {s.name for s in SENSORS} == {
        "raw_index_weekly_update_job_sensor", "raw_index_monthly_update_job_sensor",
        "silver_index_weekly_update_job_sensor", "silver_index_monthly_update_job_sensor",
    }
    for sensor in SENSORS:
        assert sensor.default_status == dg.DefaultSensorStatus.STOPPED
        assert sensor.minimum_interval_seconds == 600
        assert sensor.job_name + "_sensor" == sensor.name
        assert sensor.tags["goldenshare/sensor_domain"] == "index_topic"
    assert build_index_period_silver_run_config(INDEX_MONTHLY, IndexPeriodSilverConfig(mode="period")) == {
        "ops": {"silver_index_monthly": {"config": {"mode": "period"}}}
    }


@pytest.mark.parametrize("hour", [0, 18])
@pytest.mark.parametrize("layer", ["raw", "silver"])
def test_outside_window_has_no_resource_or_event_reads(hour, layer):
    class NeverRead:
        def __getattr__(self, name):
            pytest.fail("窗口外不应读取：" + name)
    context = dg.build_sensor_context()
    context._instance = NeverRead()
    assert reason(tick(context, layer=layer, hour=hour)) == "outside_window"


@pytest.mark.parametrize("bad", [None, "red", "missing", "other_materialization", "other_run", "nonblocking", "failed_run"])
def test_daily_checks_match_native_materialization_with_empty_partition(isolated, bad, monkeypatch):
    _, context, instance, root = isolated
    pending = []
    result = emit_delivery(instance, "silver_index_daily", day="2026-07-02", bad=bad,
        inspect=lambda: pending.append(readiness.index_period_daily_readiness(instance, context.resources.duckdb, root, "2026-07-02")[0]))
    assert pending == ["daily_run_not_success"]
    original = instance.get_records_for_run
    calls = []

    def bounded(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(instance, "get_records_for_run", bounded)
    monkeypatch.setattr(instance.event_log_storage, "get_asset_check_execution_history", lambda *a, **k: pytest.fail("不得扫描检查历史"))
    code, missing = readiness.index_period_daily_readiness(instance, context.resources.duckdb, root, "2026-07-02")
    assert (code == "ready") == (bad is None)
    if result.success:
        assert len(calls) == 1
        assert calls[0] == ((result.run_id,), {"of_type": dg.DagsterEventType.ASSET_CHECK_EVALUATION, "limit": 4, "ascending": False})
    assert missing == ()


@pytest.mark.parametrize("problem", ["missing_file", "missing_code", "wrong_day", "previous_day_only"])
def test_daily_file_and_today_code_gate(isolated, problem):
    _, context, instance, root = isolated
    emit_delivery(instance, "silver_index_daily", day="2026-07-01" if problem == "previous_day_only" else "2026-07-02")
    if problem == "missing_file":
        silver_index_daily_path(root, "2026-07-02").unlink()
    elif problem in ("missing_code", "wrong_day"):
        daily_input(root, "2026-07-02", (100, 108, 98, 106, 102, 1, 2),
                    codes=EXPECTED_CODES[:-1] if problem == "missing_code" else EXPECTED_CODES)
        if problem == "wrong_day":
            path = silver_index_daily_path(root, "2026-07-02")
            with duckdb.connect() as connection:
                connection.execute("CREATE TABLE wrong AS SELECT * FROM read_parquet(?)", [str(path)])
                connection.execute("UPDATE wrong SET trade_date=DATE '2026-07-01'")
                connection.execute(f"COPY wrong TO '{path}' (FORMAT PARQUET)")
    result = tick(context)
    assert not result.run_requests
    if problem == "missing_code":
        details = json.loads(result.cursor)["details"]
        assert details["evidence"]["missing_code_count"] == 1
        assert details["evidence"]["missing_codes"] == [EXPECTED_CODES[-1]]
    elif problem == "wrong_day":
        # 11码都在，唯一错误是文件内部日期；不能让缺代码掩盖日期过滤错误。
        assert json.loads(result.cursor)["details"]["evidence"]["missing_code_count"] == 11


def test_daily_each_day_same_partition_dedup_and_failed_attempt(isolated):
    defs, context, instance, root = isolated
    seed_silver(root, INDEX_WEEKLY)
    emit_delivery(instance, "silver_index_daily", day="2026-07-01")
    first = tick(context, day="2026-07-01")
    assert first.run_requests[0].partition_key == "2026-07-03"
    assert execute_request(defs, instance, first, INDEX_WEEKLY.silver_asset).success
    done = tick(context, day="2026-07-01")
    assert not done.run_requests
    payload = json.loads(done.cursor)
    assert payload["blocked_count"] == 0 and payload["details"]["blocked_component"] == "none"
    assert "等待新的正式Raw批次" in payload["details"]["summary"]
    emit_delivery(instance, "silver_index_daily", day="2026-07-02")
    second = tick(context)
    assert second.run_requests[0].partition_key == first.run_requests[0].partition_key
    assert second.run_requests[0].run_key != first.run_requests[0].run_key
    silver_index_daily_path(root, "2026-07-01").unlink()
    failed = execute_request(defs, instance, second, INDEX_WEEKLY.silver_asset)
    assert not failed.success
    stopped = tick(context)
    assert not stopped.run_requests and reason(stopped) == "daily_attempt_failed"
    assert json.loads(stopped.cursor)["blocked_count"] == 1
    daily_input(root, "2026-07-01", (100, 104, 98, 102, 100, 100.1256, 200.5678))
    manual = defs.resolve_job_def("silver_index_weekly_update_job").execute_in_process(
        instance=instance, partition_key="2026-07-03", run_config=second.run_requests[0].run_config,
    )
    assert manual.success
    assert not tick(context).run_requests


@pytest.mark.parametrize("period,day,key,end", [
    (INDEX_WEEKLY, "2026-07-03", "2026-07-03", "2026-07-03"),
    (INDEX_MONTHLY, "2026-07-01", "2026-06", "2026-06-30"),
    (INDEX_MONTHLY, "2027-01-04", "2026-12", "2026-12-31"),
])
def test_raw_release_targets_and_no_retry(isolated, monkeypatch, period, day, key, end):
    defs, context, instance, root = isolated
    if day == "2027-01-04":
        from orchestrator.defs.paths import silver_trade_calendar_path
        path = silver_trade_calendar_path(root)
        with duckdb.connect() as con:
            con.execute("CREATE TABLE cal AS SELECT * FROM read_parquet(?)", [str(path)])
            con.execute("UPDATE cal SET is_open=false WHERE trade_date=DATE '2027-01-01'")
            con.execute(f"COPY cal TO '{path}' (FORMAT PARQUET)")
    probes = []
    monkeypatch.setattr(sensors, "index_period_source_published", lambda p, d: probes.append((p, d.isoformat())) or False)
    assert reason(tick(context, period=period, layer="raw", day=day)) == "source_not_published"
    monkeypatch.setattr(sensors, "index_period_source_published", lambda p, d: probes.append((p, d.isoformat())) or True)
    result = tick(context, period=period, layer="raw", day=day)
    assert result.run_requests[0].partition_key == key
    assert probes == [(period, end), (period, end)]
    job = defs.resolve_job_def(period.raw_asset + "_update_job")
    instance.create_run_for_job(job, status=dg.DagsterRunStatus.FAILURE, tags={"dagster/run_key": result.run_requests[0].run_key})
    monkeypatch.setattr(sensors, "index_period_source_published", lambda *a: pytest.fail("已提交失败任务不重新探测"))
    assert reason(tick(context, period=period, layer="raw", day=day)) == "attempt_exists"


@pytest.mark.parametrize("status", [dg.DagsterRunStatus.QUEUED, dg.DagsterRunStatus.STARTED])
def test_busy_job_stops_before_foundation_and_source(isolated, status, monkeypatch):
    defs, context, instance, _ = isolated
    instance.create_run_for_job(defs.resolve_job_def("silver_index_weekly_update_job"), status=status,
        remote_job_origin=RemoteRepositoryOrigin(RegisteredCodeLocationOrigin("isolated"), "test").get_job_origin("silver_index_weekly_update_job"),
        run_config=build_index_period_silver_run_config(INDEX_WEEKLY, IndexPeriodSilverConfig(mode="daily", trade_date="2026-07-02")))
    monkeypatch.setattr(sensors, "index_period_native_delivery", lambda *a: pytest.fail("运行中不读取上游"))
    assert reason(tick(context)) == "job_active"


@pytest.mark.parametrize("layer,day", [("raw", "2026-07-02"), ("silver", "2026-07-04")])
def test_non_release_or_closed_has_no_source_calls(isolated, monkeypatch, layer, day):
    _, context, _, _ = isolated
    monkeypatch.setattr(sensors, "index_period_source_published", lambda *a: pytest.fail("不应探测源"))
    assert not tick(context, layer=layer, day=day).run_requests


def test_raw_after_daily_overrides_original_partition_and_dedups(isolated, monkeypatch):
    defs, context, instance, _ = isolated
    emit_delivery(instance, "silver_index_daily", day="2026-07-03")
    daily = tick(context, day="2026-07-03")
    # 周更中间日需接续；这里用已结束周期repair生成独立的完整北证50记录。
    instance.add_dynamic_partitions(INDEX_WEEKLY.partition_set, ["2026-07-03"])
    repair = defs.resolve_job_def("silver_index_weekly_update_job").execute_in_process(
        instance=instance, partition_key="2026-07-03",
        run_config=build_index_period_silver_run_config(INDEX_WEEKLY, IndexPeriodSilverConfig(mode="repair")),
    )
    assert repair.success
    fake_source(monkeypatch, INDEX_WEEKLY)
    raw = defs.resolve_job_def("raw_index_weekly_update_job").execute_in_process(instance=instance, partition_key="2026-07-03")
    assert raw.success
    candidate = tick(context, day="2026-07-03")
    assert reason(candidate) == "period_requested"
    assert candidate.run_requests[0].run_key != daily.run_requests[0].run_key
    assert execute_request(defs, instance, candidate, INDEX_WEEKLY.silver_asset).success
    context.update_cursor(candidate.cursor)
    assert reason(tick(context, day="2026-07-03")) == "period_attempt_exists"


def test_raw_original_month_independent_of_today_daily(isolated, monkeypatch):
    defs, context, instance, root = isolated
    seed_silver(root, INDEX_MONTHLY, start="2026-06-01", day="2026-06-30")
    fake_source(monkeypatch, INDEX_MONTHLY)
    instance.add_dynamic_partitions(INDEX_MONTHLY.partition_set, ["2026-06"])
    assert defs.resolve_job_def("raw_index_monthly_update_job").execute_in_process(instance=instance, partition_key="2026-06").success
    # 日更已经失败也不得挡住独立的上月Raw覆盖，不自动重试本月日更。
    instance.create_run_for_job(defs.resolve_job_def("silver_index_monthly_update_job"),
        status=dg.DagsterRunStatus.FAILURE,
        run_config=build_index_period_silver_run_config(INDEX_MONTHLY, IndexPeriodSilverConfig(mode="daily", trade_date="2026-07-02")),
        tags={"dagster/run_key": "silver_index_monthly_update_job:2026-07:2026-07-02"})
    result = tick(context, period=INDEX_MONTHLY)
    assert reason(result) == "period_requested"
    assert result.run_requests[0].partition_key == "2026-06"
    assert execute_request(defs, instance, result, INDEX_MONTHLY.silver_asset).success


def test_real_daily_producer_four_checks_then_both_period_jobs(isolated, monkeypatch):
    period_defs, context, instance, root = isolated
    seed_silver(root, INDEX_WEEKLY)
    path = raw_index_daily_path(root, "2026-07-01")
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as con:
        con.execute(f"COPY (SELECT ts_code,strftime(trade_date,'%Y%m%d') trade_date,open,high,low,close,pre_close,change_amount AS change,pct_chg,vol,amount FROM read_parquet(?,hive_partitioning=false)) TO '{path}' (FORMAT PARQUET)", [str(silver_index_daily_path(root, "2026-07-01"))])

    @contextmanager
    def connect():
        with duckdb.connect() as con:
            yield con

    monkeypatch.setattr(index_daily_checks, "connect_configured_duckdb", connect)
    checks = [getattr(index_daily_checks, name) for name in readiness.SILVER_INDEX_DAILY_BLOCKING_CHECKS]
    daily_defs = dg.Definitions(assets=[index_daily.silver_index_daily, dg.AssetSpec("raw_index_daily")],
        asset_checks=checks, jobs=[silver_index_daily_update_job], resources=period_defs.resources)
    instance.add_dynamic_partitions(cn_a_index_trade_days.name, ["2026-07-01"])
    instance.add_dynamic_partitions(cn_a_index_ts_codes.name, EXPECTED_CODES)
    assert not tick(context, day="2026-07-01").run_requests
    upstream = daily_defs.resolve_job_def("silver_index_daily_update_job").execute_in_process(instance=instance, partition_key="2026-07-01")
    assert upstream.success and len(upstream.get_asset_check_evaluations()) == 4
    assert all(e.partition is None for e in upstream.get_asset_check_evaluations())
    for period in (INDEX_WEEKLY, INDEX_MONTHLY):
        request = tick(context, period=period, day="2026-07-01")
        assert reason(request) == "daily_requested"
        result = execute_request(period_defs, instance, request, period.silver_asset)
        assert result.success and len(result.get_asset_check_evaluations()) == 1
        assert result.get_asset_check_evaluations()[0].partition == request.run_requests[0].partition_key


@pytest.mark.parametrize("superseded", [False, True])
def test_bootstrap_origin_then_new_raw_batches_are_not_lost(isolated, monkeypatch, superseded):
    defs, context, instance, _ = isolated
    emit_delivery(instance, INDEX_WEEKLY.raw_asset, day="2026-06-19", metadata={"goldenshare/source_method": "index_period_bootstrap"})
    origin = tick(context)
    assert reason(origin) == "bootstrap_origin" and not origin.run_requests
    context.update_cursor(origin.cursor)
    fake_source(monkeypatch, INDEX_WEEKLY)
    keys = ["2026-06-26", "2026-06-26" if superseded else "2026-07-03"]
    instance.add_dynamic_partitions(INDEX_WEEKLY.partition_set, sorted(set(keys)))
    raw_job = defs.resolve_job_def("raw_index_weekly_update_job")
    for key in keys:
        assert raw_job.execute_in_process(instance=instance, partition_key=key).success
    candidate = tick(context)
    if superseded:
        assert reason(candidate) == "raw_superseded"
    else:
        assert candidate.run_requests[0].partition_key == keys[0]
        instance.create_run_for_job(defs.resolve_job_def("silver_index_weekly_update_job"),
            run_config=candidate.run_requests[0].run_config, status=dg.DagsterRunStatus.SUCCESS,
            tags={"dagster/run_key": candidate.run_requests[0].run_key})
        candidate = tick(context)
        assert reason(candidate) == "period_attempt_exists"
    context.update_cursor(candidate.cursor)
    following = tick(context)
    assert reason(following) == "period_requested"
    assert following.run_requests[0].partition_key == keys[1]


@pytest.mark.parametrize("period,layer,day,key", [
    (INDEX_WEEKLY, "silver", "2026-07-01", "2026-07-03"),
    (INDEX_MONTHLY, "silver", "2026-07-01", "2026-07"),
    (INDEX_WEEKLY, "raw", "2026-07-03", "2026-07-03"),
    (INDEX_MONTHLY, "raw", "2026-07-01", "2026-06"),
])
def test_sensor_evaluate_tick_can_register_and_request_in_same_tick(isolated, monkeypatch, period, layer, day, key):
    defs, _, _, root = isolated
    complete = dg.Definitions.merge(defs, dg.Definitions(sensors=SENSORS))
    class FixedClock:
        @staticmethod
        def now(zone):
            return instant(day)
    monkeypatch.setattr(sensors, "datetime", FixedClock)
    monkeypatch.setattr(sensors, "index_period_source_published", lambda *args: True)
    # 按实际RPC入口提供instance_ref；build_sensor_context测试入口本身不传此引用。
    directory = root.parent / "tick_instance"
    directory.mkdir()
    with dg.DagsterInstance.local_temp(str(directory), overrides={"telemetry": {"enabled": False}}) as instance:
        for asset in ("silver_trade_calendar", "silver_index_basic", "silver_index_daily"):
            emit_delivery(instance, asset, day=day if asset == "silver_index_daily" else None)
        repository = complete.get_repository_def()
        with dg.SensorEvaluationContext(instance_ref=instance.get_ref(), instance=instance,
                repository_def=repository, resources=repository.get_top_level_resources()) as context:
            sensor = getattr(sensors, getattr(period, layer + "_asset") + "_update_job_sensor")
            result = sensor.evaluate_tick(context)
        assert result.run_requests[0].partition_key == key
        assert result.dynamic_partitions_requests[0].partition_keys == [key]
        assert instance.get_dynamic_partitions(period.partition_set) == []


@pytest.mark.parametrize("base", ["silver_trade_calendar", "silver_index_basic"])
def test_foundation_new_red_check_cannot_use_previous_green(isolated, monkeypatch, base):
    _, context, instance, _ = isolated
    emit_delivery(instance, base, bad="red")
    monkeypatch.setattr(sensors, "_calendar_targets", lambda *a: pytest.fail("基础未就绪不得读日历"))
    assert reason(tick(context)) == "foundation_not_ready"


def test_holiday_week_end_and_incomplete_calendar(isolated, monkeypatch):
    _, context, _, root = isolated
    from orchestrator.defs.paths import silver_trade_calendar_path
    path = silver_trade_calendar_path(root)
    with duckdb.connect() as con:
        con.execute("CREATE TABLE cal AS SELECT * FROM read_parquet(?)", [str(path)])
        con.execute("UPDATE cal SET is_open=false WHERE trade_date=DATE '2026-07-03'")
        con.execute(f"COPY cal TO '{path}' (FORMAT PARQUET)")
    probes = []
    monkeypatch.setattr(sensors, "index_period_source_published", lambda p, d: probes.append(d.isoformat()) or True)
    result = tick(context, day="2026-07-02", layer="raw")
    assert result.run_requests[0].partition_key == "2026-07-02" and probes == ["2026-07-02"]
    with duckdb.connect() as con:
        con.execute("CREATE TABLE cal AS SELECT * FROM read_parquet(?) WHERE trade_date != DATE '2026-06-01'", [str(path)])
        con.execute(f"COPY cal TO '{path}' (FORMAT PARQUET)")
    # 无关上月的缺口不能误挡本周更新；缺的是本周日期才阻断。
    assert tick(context, day="2026-07-02", layer="raw").run_requests
    with duckdb.connect() as con:
        con.execute("CREATE TABLE cal AS SELECT * FROM read_parquet(?) WHERE trade_date != DATE '2026-07-01'", [str(path)])
        con.execute(f"COPY cal TO '{path}' (FORMAT PARQUET)")
    assert reason(tick(context)) == "calendar_incomplete"


def test_same_raw_batch_failure_needs_manual_retry_and_new_batch_is_independent(isolated, monkeypatch):
    defs, context, instance, _ = isolated
    fake_source(monkeypatch, INDEX_WEEKLY)
    instance.add_dynamic_partitions(INDEX_WEEKLY.partition_set, ["2026-07-03"])
    raw_job = defs.resolve_job_def("raw_index_weekly_update_job")
    assert raw_job.execute_in_process(instance=instance, partition_key="2026-07-03").success
    request = tick(context)
    instance.create_run_for_job(defs.resolve_job_def("silver_index_weekly_update_job"),
        status=dg.DagsterRunStatus.FAILURE, run_config=request.run_requests[0].run_config,
        tags={"dagster/run_key": request.run_requests[0].run_key})
    failed = tick(context)
    assert not failed.run_requests and reason(failed) == "period_attempt_exists"
    context.update_cursor(failed.cursor)
    assert not tick(context).run_requests
    assert raw_job.execute_in_process(instance=instance, partition_key="2026-07-03").success
    updated = tick(context)
    assert updated.run_requests[0].run_key != request.run_requests[0].run_key


def test_silver_file_update_at_documented_history_scale(isolated, tmp_path):
    """与§2相同行数的人工历史，不把人工日期、价格或耗时称为真实源验收。"""
    defs, _, instance, root = isolated
    from orchestrator.defs.io import index_period_writer as writer
    # 每码已结束周期数来自原方案§2；此处只复现保存规模，不重复审计来源历史。
    counts = (
        ("000001.SH", 1793, 424), ("399001.SZ", 1610, 382), ("399006.SZ", 843, 197),
        ("000688.SH", 324, 76), ("000300.SH", 1102, 259), ("000905.SH", 1014, 238),
        ("000852.SH", 619, 145), ("899050.BJ", 204, 48), ("000510.SH", 111, 26),
        ("000016.SH", 1165, 274), ("000680.SH", 94, 22),
    )
    for day in range(2, 19):
        if datetime(2026, 11, day, tzinfo=TZ).weekday() < 5:
            daily_input(root, f"2026-11-{day:02}", (100, 108, 98, 106, 100, 100.1256, 200.5678))
    metrics = []
    for period, position, expected in ((INDEX_WEEKLY, 1, 8890), (INDEX_MONTHLY, 2, 2102)):
        path = writer.index_period_path(root, period, "silver")
        path.parent.mkdir(parents=True, exist_ok=True)
        values = ",".join(f"('{code}',{sizes[position-1]})" for code, *sizes in counts)
        cycle = "DATE '2026-11-16'-i*INTERVAL 7 DAY" if period == INDEX_WEEKLY else "DATE '2026-11-01'-i*INTERVAL 1 MONTH"
        start = "cycle_day" if period == INDEX_WEEKLY else "cycle_day+CASE isodow(cycle_day) WHEN 6 THEN INTERVAL 2 DAY WHEN 7 THEN INTERVAL 1 DAY ELSE INTERVAL 0 DAY END"
        end = "cycle_day+INTERVAL 4 DAY" if period == INDEX_WEEKLY else "last_day(cycle_day)-CASE isodow(last_day(cycle_day)) WHEN 6 THEN INTERVAL 1 DAY WHEN 7 THEN INTERVAL 2 DAY ELSE INTERVAL 0 DAY END"
        with duckdb.connect() as con:
            con.execute(f"""COPY (SELECT {writer.index_period_projection(writer.SILVER_INDEX_WEEKLY_SCHEMA)} FROM (
                SELECT ts_code,({start})::DATE period_start_date,
                    CASE WHEN i=0 THEN DATE '2026-11-17' ELSE ({end})::DATE END trade_date,
                    100 open,100 high,100 low,100 AS "close",100 pre_close,0 change_amount,0 pct_chg,0 vol,0 amount
                FROM (SELECT ts_code,i,({cycle})::DATE cycle_day FROM (VALUES {values})s(ts_code,n),LATERAL range(0,n+1)t(i))))
                TO '{path}' (FORMAT PARQUET)""")
        key = "2026-11-20" if period == INDEX_WEEKLY else "2026-11"
        instance.add_dynamic_partitions(period.partition_set, [key])
        began = time.perf_counter()
        result = defs.resolve_job_def(period.silver_asset + "_update_job").execute_in_process(instance=instance, partition_key=key,
            run_config=build_index_period_silver_run_config(period, IndexPeriodSilverConfig(mode="daily", trade_date="2026-11-18")))
        assert result.success
        mats = result.get_asset_materialization_events()
        assert len(mats) == len(result.get_asset_check_evaluations()) == 1
        metadata = mats[0].materialization.metadata
        assert metadata["goldenshare/file_row_count"].value == expected
        metrics.append({"asset": period.silver_asset, "rows": expected, "bytes": path.stat().st_size,
            "input_rows": metadata["goldenshare/source_row_count"].value, "asset_events": 2,
            "elapsed_seconds": time.perf_counter()-began})
    (tmp_path / "cost.json").write_text(json.dumps(metrics))
