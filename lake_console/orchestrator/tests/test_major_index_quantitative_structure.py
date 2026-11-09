"""Isolated Parquet and Dagster coverage for the quantitative structure dataset."""

from contextlib import contextmanager
from datetime import date, datetime, time
from pathlib import Path
from unittest.mock import patch

import dagster as dg
import pytest
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.assets.major_index_quantitative_structure import (
    STRUCTURE_UPSTREAM_SPECS,
    gold_major_index_quantitative_structure,
)
from orchestrator.defs.bootstrap import (
    major_index_quantitative_structure_history_cli as history,
)
from orchestrator.defs.catalog.lake_assets import LAKE_ASSET_CATALOG, PartitionModel
from orchestrator.defs.checks.major_index_quantitative_structure_checks import (
    gold_major_index_quantitative_structure_completion_check,
    gold_major_index_quantitative_structure_result_contract_check,
)
from orchestrator.defs.duckdb_connection import (
    DuckDBConnectionSettings,
    connect_configured_duckdb,
)
from orchestrator.defs.duckdb_sql import copy_query_to_parquet
from orchestrator.defs.io import major_index_quantitative_structure as io
from orchestrator.defs.jobs.major_index_quantitative_structure_update import (
    gold_major_index_quantitative_structure_update_job,
)
from orchestrator.defs.partitions import (
    cn_major_index_factor_trade_days,
    cn_major_index_mins_trade_days,
    cn_major_index_quantitative_structure_trade_days,
)
from orchestrator.defs.paths import (
    gold_major_index_mins_path,
    gold_major_index_mins_technical_path,
    gold_major_index_quantitative_structure_path,
    silver_index_factor_pro_path,
    silver_trade_calendar_path,
)
from orchestrator.defs.resources import DuckDBResource, LakeRootResource
from orchestrator.defs.run_contracts.major_index_quantitative_structure import (
    STRUCTURE_ASSET,
    STRUCTURE_CHECKS,
    STRUCTURE_JOB,
)
from orchestrator.defs.sensors import (
    gold_major_index_quantitative_structure_update_job_sensor as update,
)
from orchestrator.defs.sensors import (
    major_index_quantitative_structure_trade_day_sensor as registration,
)

DAYS = (date(2010, 1, 4), date(2010, 1, 5))
EARLY_CODES = ("000001.SH", "399001.SZ", "000300.SH", "000905.SH", "000016.SH")
ENDPOINTS = {
    30: ("10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00"),
    60: ("10:30", "11:30", "14:00", "15:00"),
    90: ("11:00", "14:00", "15:00"),
    120: ("11:30", "15:00"),
}
ALL_CODES = (*EARLY_CODES, "399006.SZ", "000688.SH", "000852.SH", "000510.SH")


class IsolatedDuckDBResource(DuckDBResource):
    directory: str

    @contextmanager
    def connect(self):
        with connect_configured_duckdb(
            DuckDBConnectionSettings(temp_directory=Path(self.directory)),
            temp_policy="existing_no_spill",
        ) as connection:
            yield connection


def _write_source(connection, path, schema, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    connection.execute(f"CREATE TEMP TABLE source_fixture ({schema})")
    placeholders = ", ".join("?" for _ in rows[0])
    connection.executemany(f"INSERT INTO source_fixture VALUES ({placeholders})", rows)
    connection.execute(copy_query_to_parquet("SELECT * FROM source_fixture", path))
    connection.execute("DROP TABLE source_fixture")


def _write_inputs(connection, root, day, *, extra_codes=False, wrong_endpoint=False):
    # Types are projected from the DG producer contracts (LLD §2.1).
    codes = ALL_CODES if extra_codes else EARLY_CODES
    daily_codes = (*codes, "000680.SH", "899050.BJ") if extra_codes else (*codes, "000852.SH")
    minute_codes = (*codes, "000680.SH") if extra_codes else codes
    key = day.isoformat()
    _write_source(
        connection, silver_index_factor_pro_path(root, key),
        "ts_code VARCHAR, trade_date DATE, close DOUBLE, macd_dif_bfq DOUBLE, "
        "macd_dea_bfq DOUBLE, macd_bfq DOUBLE",
        [(code, day, 100, 0, 0, 0) for code in daily_codes],
    )
    for freq, endpoints in ENDPOINTS.items():
        rows = [
            (code, freq, day, datetime.combine(day, time.fromisoformat(endpoint)))
            for code in minute_codes for endpoint in endpoints
        ]
        if wrong_endpoint and freq == 90:
            rows[0] = rows[1]  # Same total rows, one key missing and one duplicate.
        _write_source(
            connection, gold_major_index_mins_path(root, freq, key),
            "ts_code VARCHAR, freq INTEGER, trade_date DATE, trade_time TIMESTAMP, close DOUBLE",
            [(*row, 100) for row in rows],
        )
        _write_source(
            connection, gold_major_index_mins_technical_path(root, freq, key),
            "ts_code VARCHAR, freq SMALLINT, trade_date DATE, trade_time TIMESTAMP, "
            "macd_dif DOUBLE, macd_dea DOUBLE, macd DOUBLE",
            [(*row, 0, 0, 0) for row in rows],
        )


@pytest.fixture
def isolated_lake(tmp_path):
    root = tmp_path / "data_lake"
    (root / "raw").mkdir(parents=True)
    resource = IsolatedDuckDBResource(directory=str(tmp_path))
    with resource.connect() as connection:
        _write_source(
            connection, silver_trade_calendar_path(root),
            "exchange VARCHAR, trade_date DATE, is_open BOOLEAN",
            [("SSE", day, True) for day in DAYS],
        )
        for day in DAYS:
            _write_inputs(connection, root, day)
    return root, resource


def test_structure_dataset_catalog_agrees_with_dagster_definition():
    asset = gold_major_index_quantitative_structure
    key = dg.AssetKey(STRUCTURE_ASSET)
    entry, = [entry for entry in LAKE_ASSET_CATALOG if entry.asset_key == STRUCTURE_ASSET]
    assert entry.partition_model is PartitionModel.TRADE_DATE_PARTITION_GOLD_MAJOR_INDEX_QUANTITATIVE_STRUCTURE
    assert entry.path_template == "data_lake/gold/indicator/major_index_quantitative_structure/trade_date={partition_key}/part-000.parquet"
    assert entry.blocking_check_names == STRUCTURE_CHECKS
    assert entry.performance_contract.python_row_loop_allowed
    assert asset.partitions_def == cn_major_index_quantitative_structure_trade_days
    assert len(asset.asset_deps[key]) == 10  # Nine partitioned inputs and the SSE calendar.
    assert sum(len(spec.blocking_check_names) for spec in STRUCTURE_UPSTREAM_SPECS) == 31


def test_structure_reads_complete_keys_and_excludes_extra_indices(isolated_lake):
    root, resource = isolated_lake
    day = date(2026, 11, 6)
    with resource.connect() as connection:
        _write_inputs(connection, root, day, extra_codes=True)
        result, = io.calculate_structure_days(connection, root, [day], first_result_date=day)
        assert result == io.StructureDay(day, True, [], 162)
        _write_inputs(connection, root, day, extra_codes=True, wrong_endpoint=True)
        with pytest.raises(io.StructureInputError, match=r"2026-11-06.*000001.SH.*90"):
            list(io.calculate_structure_days(connection, root, [day], first_result_date=day))


def test_structure_writer_preserves_typed_empty_results_and_time_values(isolated_lake):
    root, resource = isolated_lake
    target = gold_major_index_quantitative_structure_path(root, DAYS[0].isoformat())
    events = [
        {"ts_code": "000001.SH", "period": "m90", "bar_end_time": time(11),
         "event_type": "CANCEL", "direction": "BOTTOM", "display_on_chart": False},
        {"ts_code": "000001.SH", "period": "m90", "bar_end_time": time(11),
         "event_type": "DULL", "direction": "BOTTOM", "display_on_chart": True},
    ]
    with resource.connect() as connection:
        for succeeded, stored_events in [(True, events), (True, []), (False, [])]:
            io.write_structure_day(
                connection, io.StructureDay(DAYS[0], succeeded, stored_events, 90),
                staging_dir=root.parent / "staging", target=target,
            )
            assert connection.execute(
                "SELECT * FROM read_parquet(?, hive_partitioning=false)", [str(target)],
            ).fetchall() == [(DAYS[0], succeeded, stored_events)]


def _add_green_upstream(instance, day):
    for spec in STRUCTURE_UPSTREAM_SPECS:
        instance.report_runless_asset_event(dg.AssetMaterialization(asset_key=spec.asset_key, partition=day))
        record, = instance.fetch_materializations(
            dg.AssetRecordsFilter(asset_key=spec.asset_key, asset_partitions=[day]), limit=1,
        ).records
        for name in spec.blocking_check_names:
            instance.report_dagster_event(
                run_id=f"fixture-{day}-{name}",
                dagster_event=dg.DagsterEvent(
                    event_type_value=dg.DagsterEventType.ASSET_CHECK_EVALUATION.value,
                    job_name="fixture_upstream",
                    event_specific_data=dg.AssetCheckEvaluation(
                        asset_key=spec.asset_key, check_name=name, passed=True, blocking=True,
                        partition=day,
                        target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                            storage_id=record.storage_id, run_id=record.run_id, timestamp=record.timestamp,
                        ),
                    ),
                ),
            )


def test_single_day_job_waits_then_writes_failure_then_rebuilds_only_target(isolated_lake):
    root, resource = isolated_lake
    calendar = dg.AssetSpec("silver_trade_calendar")
    upstream = [
        dg.AssetSpec(
            spec.asset_key,
            partitions_def=cn_major_index_mins_trade_days if i else cn_major_index_factor_trade_days,
        )
        for i, spec in enumerate(STRUCTURE_UPSTREAM_SPECS)
    ]
    definitions = dg.Definitions(
        assets=[calendar, *upstream, gold_major_index_quantitative_structure],
        asset_checks=[gold_major_index_quantitative_structure_result_contract_check,
                      gold_major_index_quantitative_structure_completion_check],
        jobs=[gold_major_index_quantitative_structure_update_job],
        resources={"lake_root": LakeRootResource(root_path=str(root)), "duckdb": resource},
    )
    job = definitions.resolve_job_def(STRUCTURE_JOB)
    day = DAYS[1].isoformat()
    target = gold_major_index_quantitative_structure_path(root, day)
    earlier_target = gold_major_index_quantitative_structure_path(root, DAYS[0].isoformat())
    with dg.DagsterInstance.local_temp(str(root.parent)) as instance:
        instance.add_dynamic_partitions(cn_major_index_quantitative_structure_trade_days.name, [day])
        waiting = job.execute_in_process(instance=instance, partition_key=day, raise_on_error=False)
        assert waiting.success and not waiting.get_asset_materialization_events()
        assert not waiting.get_asset_check_evaluations() and not target.exists()
        _add_green_upstream(instance, day)
        earlier_input = silver_index_factor_pro_path(root, DAYS[0].isoformat())
        earlier_input.unlink()
        failed = job.execute_in_process(instance=instance, partition_key=day, raise_on_error=False)
        assert not failed.success and len(failed.get_asset_materialization_events()) == 1
        assert {check.check_name: check.passed for check in failed.get_asset_check_evaluations()} == {
            STRUCTURE_CHECKS[0]: True, STRUCTURE_CHECKS[1]: False,
        }
        with resource.connect() as connection:
            assert connection.execute("SELECT success FROM read_parquet(?)", [str(target)]).fetchone() == (False,)
            _write_inputs(connection, root, DAYS[0])
        repaired = job.execute_in_process(instance=instance, partition_key=day, raise_on_error=False)
        assert repaired.success and not earlier_target.exists()
        assert set(update._completed_structure_dates(instance, [day])) == {day}


@pytest.mark.parametrize("registered", [False, True])
def test_sensors_wait_until_18_and_use_one_current_partition(isolated_lake, monkeypatch, registered):
    root, resource = isolated_lake
    resources = {"lake_root": LakeRootResource(root_path=str(root)), "duckdb": resource}
    day = DAYS[0].isoformat()

    class Clock(datetime):
        current_time = time(17, 59, 59)

        @classmethod
        def now(cls, tz):
            return datetime.combine(DAYS[1], cls.current_time, tzinfo=tz)

    monkeypatch.setattr(update, "datetime", Clock)
    monkeypatch.setattr(registration, "datetime", Clock)
    with dg.DagsterInstance.local_temp(str(root.parent)) as instance:
        context = dg.build_sensor_context(instance=instance, resources=resources)
        assert not update.gold_major_index_quantitative_structure_update_job_sensor(context).run_requests
        assert not registration.major_index_quantitative_structure_trade_day_sensor(context).dynamic_partitions_requests
        Clock.current_time = time(18)
        requested = registration.major_index_quantitative_structure_trade_day_sensor(context)
        assert requested.dynamic_partitions_requests[0].partition_keys == [day, DAYS[1].isoformat()]
        if registered:
            for partitions in (cn_major_index_quantitative_structure_trade_days,
                               cn_major_index_factor_trade_days, cn_major_index_mins_trade_days):
                instance.add_dynamic_partitions(partitions.name, [day])
            _add_green_upstream(instance, day)
        storage = instance.event_log_storage
        with (
            patch.object(instance, "has_dynamic_partition", wraps=instance.has_dynamic_partition) as partitions,
            patch.object(instance, "get_runs", wraps=instance.get_runs) as runs,
            patch.object(instance, "fetch_materializations", wraps=instance.fetch_materializations) as materializations,
            patch.object(storage, "get_asset_check_partition_info", wraps=storage.get_asset_check_partition_info) as checks,
            patch.object(storage, "get_latest_asset_check_execution_by_key",
                         wraps=storage.get_latest_asset_check_execution_by_key) as upstream_checks,
        ):
            result = update.gold_major_index_quantitative_structure_update_job_sensor(context)
            calls = (partitions.call_count, runs.call_count, materializations.call_count,
                     checks.call_count, upstream_checks.call_count)
            assert calls == ((3, 1, 10, 1, 1) if registered else (1, 0, 0, 1, 0))
        assert [request.partition_key for request in result.run_requests] == ([day] if registered else [])
        if registered:
            instance.report_runless_asset_event(dg.AssetMaterialization(
                asset_key=dg.AssetKey(STRUCTURE_ASSET), partition=day,
            ))
            waiting = update.gold_major_index_quantitative_structure_update_job_sensor(context)
            assert not waiting.run_requests and "已有产出" in waiting.skip_reason.skip_message


def test_history_resumes_then_replaces_files_and_rebinds_checks(isolated_lake, monkeypatch):
    root, resource = isolated_lake
    with resource.connect() as connection, dg.DagsterInstance.local_temp(str(root.parent)) as instance:
        plan = history.plan_structure_history(connection, root, DAYS[-1], replace_all=False)
        assert (plan["source_file_count"], plan["input_bar_count"], plan["output_file_count"]) == (18, 182, 2)
        assert history.register_structure_history(instance, plan) == 2
        original = history._write_json

        def interrupt_after_first_file(path, payload):
            if payload.get("last_trade_date") == DAYS[0].isoformat():
                raise InterruptedError("after file replacement")
            original(path, payload)

        with monkeypatch.context() as patch:
            patch.setattr(history, "_write_json", interrupt_after_first_file)
            with pytest.raises(InterruptedError):
                history.build_structure_history(connection, root, plan)
        assert history.build_structure_history(connection, root, plan)["row_count"] == 2
        audit = history.audit_structure_history(connection, root, plan)
        first_events = history.plan_structure_events(instance, plan, audit)
        assert (first_events["materialization_count"], first_events["check_count"]) == (2, 4)
        assert history.report_structure_events(instance, root, first_events, trade_date=None) == {
            "materialization_count": 2, "check_count": 4,
        }
        assert history.report_structure_events(instance, root, first_events, trade_date=None) == {
            "materialization_count": 0, "check_count": 0,
        }
        previous_ids = update._completed_structure_dates(instance, [day.isoformat() for day in DAYS])
        with pytest.raises(ValueError, match="覆盖所有"):
            history.plan_structure_history(connection, root, DAYS[0], replace_all=True)
        monkeypatch.setattr(history, "structure_algorithm_version", lambda: "next-test-version")
        replacement = history.plan_structure_history(connection, root, DAYS[-1], replace_all=True)
        history.build_structure_history(connection, root, replacement)
        replacement_audit = history.audit_structure_history(connection, root, replacement)
        replacement_events = history.plan_structure_events(instance, replacement, replacement_audit)
        history.report_structure_events(instance, root, replacement_events, trade_date=None)
        assert history.audit_structure_events(instance, replacement_events) == {"completed_partition_count": 2}
        current_ids = update._completed_structure_dates(instance, [day.isoformat() for day in DAYS])
        assert len(current_ids) == 2 and not set(current_ids.values()) & set(previous_ids.values())


def test_existing_r41_m90_case_keeps_same_bar_event_order(monkeypatch):
    # Independent r4.1 reference timeline from test_xxm_r4_following.py.
    rows = [
        ("10-22T14:00", 3640., -34., -2.), ("10-23T11:00", 3620.7249, -35., -2.),
        ("10-23T14:00", 3630., -36.186445721572454, -2.), ("10-23T15:00", 3645., -35., -2.),
        ("10-26T11:00", 3660., -32., 2.), ("10-30T11:00", 3630., -25., -2.),
        ("10-30T15:00", 3599.0166, -26., -2.), ("11-02T11:00", 3600., -27.029098705920205, -2.),
        ("11-02T14:00", 3620., -26.9, -2.), ("11-02T15:00", 3640., -26., 0.93069),
        ("11-03T11:00", 3615., -26.7, -2.),
        ("11-03T14:00", 3584.8710, -26.883732958846394, -4.488127712248506),
        ("11-03T15:00", 3608.0977, -26.476741829203547, -2.939316362370235),
        ("11-04T11:00", 3591.8962, -27.1485722338507, -3.4263817373316314),
        ("11-04T14:00", 3660.3843, -21.902111471293665, 5.6532318302259625),
    ]
    inputs = {}
    for stamp_text, close, dif, hist in rows:
        stamp = datetime.fromisoformat(f"2026-{stamp_text}")
        day = stamp.date()
        inputs.setdefault(day, []).append((day, day, "000001.SH", 90, stamp, close, dif, dif - hist / 2, hist))
    monkeypatch.setattr(io, "_read_structure_month", lambda conn, root, days: (
        {day: inputs[day] for day in days}, None,
    ))
    monkeypatch.setattr(io, "expected_structure_keys", lambda day: {
        ("000001.SH", 90, row[4].time()) for row in inputs[day]
    })
    target = date(2026, 11, 4)
    result, = io.calculate_structure_days(None, Path("."), sorted(inputs), first_result_date=target)
    assert [(event["bar_end_time"], event["event_type"], event["display_on_chart"])
            for event in result.results] == [
        (time(11), "CANCEL", False), (time(11), "DULL", True), (time(14), "STRUCTURE", True),
    ]
