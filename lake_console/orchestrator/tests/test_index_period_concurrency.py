"""真实multiprocess执行器与四个原生pool；资源和时序文件均在隔离目录。"""

import os
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import dagster as dg
import duckdb
import pytest

from orchestrator.defs.assets import index_period as assets
from orchestrator.defs.io import index_period_writer as writer
from orchestrator.defs.jobs import index_period_update as jobs
from orchestrator.defs.run_contracts.index_period import (
    INDEX_MONTHLY,
    INDEX_WEEKLY,
    IndexPeriodSilverConfig,
    build_index_period_silver_run_config,
)
from tests.index_period_test_support import silver_inputs
from tests.test_index_period_contracts import row


class TemporaryLake(dg.ConfigurableResource):
    root_path: str

    def root(self):
        return Path(self.root_path)

    def ensure_available_for_run(self):
        assert self.root().is_relative_to(Path("/private/tmp"))


class TemporaryDuckDB(dg.ConfigurableResource):
    @contextmanager
    def connect(self):
        with duckdb.connect() as connection:
            yield connection


def _source_rows(period, period_end, *, codes, required_codes):
    # 人工源替身：仅替换HTTP，行字段顺序来自已核对的完整11字段源合同。
    return [row(code, period_end.strftime("%Y%m%d")) for code in codes if code != "899050.BJ"]


def _native_job(period, layer):
    """可重建工厂，仅供此测试；子进程同样明确注入临时资源和HTTP替身。"""
    root = Path(os.environ["DG_INDEX_PERIOD_TEST_ROOT"])
    assert root.is_relative_to(Path("/private/tmp"))
    assets.DEFAULT_LAKE_STAGING_ROOT = str(root.parent / "staging")
    writer.download_index_period_rows = _source_rows
    original = writer.write_index_period_raw if layer == "raw" else writer.write_index_period_silver

    def measured(connection, **kwargs):
        identity = layer + "-" + period.frequency + "-" + kwargs["partition_key"]
        control = root.parent / "control"
        (control / (identity + ".enter")).write_text(str(time.monotonic_ns()))
        if (control / "hold").read_text() == identity:
            # 仅为测试时序协调；正式生产没有该文件、等待或锁。
            deadline = time.monotonic() + 30
            while not (control / "release").exists():
                if time.monotonic() >= deadline:
                    raise TimeoutError("隔离并发测试未释放首个writer")
                time.sleep(0.05)
        result = original(connection, **kwargs)
        (control / (identity + ".exit")).write_text(str(time.monotonic_ns()))
        return result

    if layer == "raw":
        assets.write_index_period_raw = measured
    else:
        assets.write_index_period_silver = measured
    asset = getattr(assets, period.raw_asset if layer == "raw" else period.silver_asset)
    job = getattr(jobs, (period.raw_asset if layer == "raw" else period.silver_asset) + "_update_job")
    return dg.Definitions(
        assets=[asset, dg.AssetSpec("silver_trade_calendar"), dg.AssetSpec("silver_index_basic"),
                dg.AssetSpec("silver_index_daily")] + ([dg.AssetSpec(period.raw_asset)] if layer == "silver" else []),
        jobs=[job], executor=dg.multiprocess_executor,
        resources={"lake_root": TemporaryLake(root_path=str(root)), "duckdb": TemporaryDuckDB()},
    ).resolve_job_def(job.name)


def native_raw_weekly_job():
    return _native_job(INDEX_WEEKLY, "raw")


def native_raw_monthly_job():
    return _native_job(INDEX_MONTHLY, "raw")


def native_silver_weekly_job():
    return _native_job(INDEX_WEEKLY, "silver")


def native_silver_monthly_job():
    return _native_job(INDEX_MONTHLY, "silver")


FACTORIES = {
    ("week", "raw"): native_raw_weekly_job, ("month", "raw"): native_raw_monthly_job,
    ("week", "silver"): native_silver_weekly_job, ("month", "silver"): native_silver_monthly_job,
}


def _wait_for(predicate):
    # 测试进程协调的30秒超时，不是生产性能预算或源等待策略。
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("隔离原生执行没有到达预期步骤")


def _execute(instance, period, layer, key):
    return dg.execute_job(
        dg.reconstructable(FACTORIES[period.frequency, layer]), instance=instance,
        tags={"dagster/partition": key},
        run_config=build_index_period_silver_run_config(period, IndexPeriodSilverConfig(mode="repair")) if layer == "silver" else {},
    )


@pytest.fixture
def isolated_pool(tmp_path, monkeypatch):
    root = tmp_path / "lake"
    silver_inputs(root)
    control = tmp_path / "control"
    control.mkdir()
    monkeypatch.setenv("DG_INDEX_PERIOD_TEST_ROOT", str(root))
    # execute_job在父进程重建时也会注入；恢复这些修改以免污染别的测试。
    monkeypatch.setattr(assets, "DEFAULT_LAKE_STAGING_ROOT", str(tmp_path / "staging"))
    monkeypatch.setattr(writer, "download_index_period_rows", _source_rows)
    monkeypatch.setattr(assets, "write_index_period_raw", writer.write_index_period_raw)
    monkeypatch.setattr(assets, "write_index_period_silver", writer.write_index_period_silver)
    (tmp_path / "instance").mkdir()
    with dg.DagsterInstance.local_temp(str(tmp_path / "instance"), overrides={"telemetry": {"enabled": False}}) as instance:
        assert instance.event_log_storage.supports_global_concurrency_limits
        for period in (INDEX_WEEKLY, INDEX_MONTHLY):
            for layer in ("raw", "silver"):
                pool = getattr(period, layer + "_pool")
                instance.event_log_storage.set_concurrency_slots(pool, 1)
                assert instance.event_log_storage.get_concurrency_info(pool).slot_count == 1
            instance.add_dynamic_partitions(period.partition_set,
                ["2026-06-26", "2026-07-03"] if period == INDEX_WEEKLY else ["2026-06", "2026-07"])
        yield root, control, instance


def _seed_silver_sources(root, period):
    # 两个完整北证50合成记录；另外十码由对应Raw补入，验证两个周期更新都保留。
    keys = ["2026-06-26", "2026-07-03"] if period == INDEX_WEEKLY else ["2026-06", "2026-07"]
    ends = ["2026-06-26", "2026-07-03"] if period == INDEX_WEEKLY else ["2026-06-30", "2026-07-31"]
    starts = ["2026-06-22", "2026-06-29"] if period == INDEX_WEEKLY else ["2026-06-01", "2026-07-01"]
    for key in keys:
        with duckdb.connect() as con:
            writer.write_index_period_raw(con, lake_root=root, period=period, partition_key=key,
                run_id="seed-"+key, staging_root=root.parent / "staging")
    with duckdb.connect() as con:
        selection = " UNION ALL ".join(
            f"SELECT '899050.BJ' ts_code,DATE '{start}' period_start_date,DATE '{end}' trade_date,100 open,100 high,100 low,100 AS \"close\",100 pre_close,0 change_amount,0 pct_chg,0 vol,0 amount"
            for start, end in zip(starts, ends, strict=True)
        )
        path = writer.index_period_path(root, period, "silver")
        path.parent.mkdir(parents=True, exist_ok=True)
        con.execute(f"COPY (SELECT {writer.index_period_projection(writer.SILVER_INDEX_WEEKLY_SCHEMA)} FROM ({selection})) TO '{path}' (FORMAT PARQUET)")


@pytest.mark.parametrize("period", [INDEX_WEEKLY, INDEX_MONTHLY])
@pytest.mark.parametrize("layer", ["raw", "silver"])
def test_native_pool_serializes_two_periods_without_losing_updates(isolated_pool, period, layer):
    root, control, instance = isolated_pool
    keys = ["2026-06-26", "2026-07-03"] if period == INDEX_WEEKLY else ["2026-06", "2026-07"]
    if layer == "silver":
        _seed_silver_sources(root, period)
    first_id, second_id = (layer + "-" + period.frequency + "-" + key for key in keys)
    (control / "hold").write_text(first_id)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(_execute, instance, period, layer, keys[0])
        _wait_for(lambda: (control / (first_id + ".enter")).exists())
        second = executor.submit(_execute, instance, period, layer, keys[1])

        def native_blocked():
            runs = instance.get_runs(filters=dg.RunsFilter(job_name=getattr(period, layer + "_asset") + "_update_job", tags={"dagster/partition": keys[1]}), limit=1)
            return runs and any(
                "blocked by limit for pool" in record.event_log_entry.message
                for record in instance.get_records_for_run(runs[0].run_id, of_type=dg.DagsterEventType.ENGINE_EVENT).records
            )

        try:
            _wait_for(native_blocked)
            assert not (control / (second_id + ".enter")).exists()
            assert instance.event_log_storage.get_concurrency_info(getattr(period, layer + "_pool")).active_slot_count == 1
        finally:
            (control / "release").touch()
        assert first.result().success and second.result().success
    assert int((control / (second_id + ".enter")).read_text()) >= int((control / (first_id + ".exit")).read_text())
    with duckdb.connect() as con:
        rows, periods = con.execute("SELECT count(*),count(DISTINCT trade_date) FROM read_parquet(?)", [str(writer.index_period_path(root, period, layer))]).fetchone()
    assert rows == (20 if layer == "raw" else 22) and periods == 2


def test_different_file_pools_can_enter_while_another_writer_is_held(isolated_pool):
    _, control, instance = isolated_pool
    (control / "hold").write_text("raw-week-2026-06-26")
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(_execute, instance, INDEX_WEEKLY, "raw", "2026-06-26")
        _wait_for(lambda: (control / "raw-week-2026-06-26.enter").exists())
        second = executor.submit(_execute, instance, INDEX_MONTHLY, "raw", "2026-06")
        try:
            _wait_for(lambda: (control / "raw-month-2026-06.enter").exists())
            assert not first.done()
        finally:
            (control / "release").touch()
        assert first.result().success and second.result().success
