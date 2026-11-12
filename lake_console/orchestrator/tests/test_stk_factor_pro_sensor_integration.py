"""LLD 22.2: native sensors -> HTTP -> actual job, in one temporary instance.

Only the source service, upstream producer inputs and Shanghai business clock
are substituted. A's 261 fields replay the archived 2026-10-12..16 response;
adj_factor changes and B/EXTRA rows are explicit synthetic scenario inputs.
This is isolated integration evidence, not a live source or bootstrap test.
"""

import json
import os
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

import dagster as dg
import pytest
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
    AssetCheckEvaluationTargetMaterializationData,
)
from dagster._core.storage.tags import (
    PARTITION_NAME_TAG,
    PARTITION_SET_TAG,
    RUN_KEY_TAG,
    SENSOR_NAME_TAG,
)
from sqlalchemy import event
from sqlalchemy.engine import Engine

from orchestrator.defs.assets import stk_factor_pro as asset
from orchestrator.defs.checks.stk_factor_pro import audit_stk_factor_pro_file
from orchestrator.defs.io import stk_factor_pro_candidates as candidates
from orchestrator.defs.paths import (
    raw_stk_factor_pro_path,
    silver_stock_factor_pro_path,
    stk_factor_pro_run_staging_root,
)
from orchestrator.defs.run_contracts import stk_factor_pro as C
from orchestrator.defs.run_contracts.metadata import FILE_PATH_METADATA_KEY
from orchestrator.defs.sensors import (
    raw_tushare_stk_factor_pro_update_job_sensor as sensor,
)
from orchestrator.defs.sensors import stock_factor_pro_trade_day_sensor as partitions
from orchestrator.defs.sensors.readiness import (
    RAW_ADJ_FACTOR_READINESS_SPEC,
    SUSPEND_D_READINESS_SPECS,
)
from orchestrator.defs.source_readiness.stk_factor_pro import (
    probe_stk_factor_pro_source,
)
from orchestrator.tushare_download.configuration import ConfigurationSnapshot
from orchestrator.tushare_download.http_transport import (
    HttpProTransport,
    encode_request,
)
from tests import test_stk_factor_pro_jobs as job_support
from tests.stk_factor_pro_history_test_support import saved_real_rows, write_factor_file
from tests.stk_factor_pro_test_support import DAY, NAMES, connection, row
from tests.test_stk_factor_pro_batch5_job_integration import seed_upstream_events
from tests.test_stk_factor_pro_bootstrap_coverage import upstream
from tests.test_stk_factor_pro_dagster_events import _isolated_instance
from tests.test_stk_factor_pro_jobs import EXTRA, FIRST, PREVIOUS, A, B
from tests.tushare_download.test_tushare_download_http_integration import (
    Reply,
    localhost_source,
)

DAYS = tuple(date(2026, 10, n) for n in range(12, 17))
P14 = date(2026, 10, 14)
ADJ = NAMES.index("adj_factor")


def _source_row(scene, day, factor=1):
    values = list(scene.archived[day])
    values[ADJ] = factor  # Deliberate authority revision; other real values unchanged.
    return tuple(values)


def _extra_upstream_events(instance):
    """Real native bindings for T=15/P=14; existing seed covers T=16/P=15."""

    @dg.op(out={})
    def extra_inputs(context):
        inputs = [(RAW_ADJ_FACTOR_READINESS_SPEC, P14)] + [
            (spec, PREVIOUS) for spec in SUSPEND_D_READINESS_SPECS
        ]
        for spec, day in inputs:
            yield dg.AssetMaterialization(spec.asset_key, partition=str(day))
        records = context.instance.get_records_for_run(
            context.run.run_id, of_type=dg.DagsterEventType.ASSET_MATERIALIZATION
        ).records
        materialized = {(r.asset_key, r.partition_key): r for r in records}
        for spec, day in inputs:
            record = materialized[spec.asset_key, str(day)]
            for name in spec.blocking_check_names:
                yield AssetCheckEvaluation(
                    asset_key=spec.asset_key,
                    check_name=name,
                    partition=str(day),
                    passed=True,
                    blocking=True,
                    target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                        storage_id=record.storage_id,
                        run_id=context.run.run_id,
                        timestamp=record.timestamp,
                    ),
                )

    @dg.job
    def extra_inputs_job():
        extra_inputs()

    assert extra_inputs_job.execute_in_process(instance=instance).success


@pytest.fixture
def scene(tmp_path, monkeypatch, record_property):
    with job_support.isolated_update_environment(
        tmp_path, monkeypatch, substitute_upstream=False
    ) as env:
        instance, job, _, lake, staging, counts = env
        for key in instance.get_dynamic_partitions(C.STK_FACTOR_PRO_PARTITIONS):
            instance.delete_dynamic_partition(C.STK_FACTOR_PRO_PARTITIONS, key)
        state = SimpleNamespace(
            instance=instance,
            job=job,
            repository=dg.Definitions(jobs=[job]).get_repository_def(),
            lake=lake,
            staging=staging,
            base=tmp_path,
            clock=datetime.fromisoformat("2026-10-16T19:00:00+08:00"),
            cursor=None,
            archived=dict(zip(DAYS, saved_real_rows(), strict=True)),
            probes={PREVIOUS: (A, B), DAY: (A, B)},
            daily={},
            history=(),
            totals=Counter(),
            opened=Counter(),
            measurements=[],
            phase_results={},
            kind="setup",
            forbidden=[],
            counts=counts,
        )
        for day in (PREVIOUS, DAY):
            state.daily[day] = (
                _source_row(state, day),
                row(B, day.strftime("%Y%m%d"), adj_factor=1),
            )
        with connection(tmp_path) as conn:
            # Real producer schemas, explicit SSE pretrade_date, historical EXTRA
            # identity but retired lifecycle: EXTRA must be an unexpected source code.
            life = [
                (
                    code,
                    code[:6],
                    code,
                    "SZSE" if code.endswith("SZ") else "SSE",
                    None,
                    "CNY",
                    True,
                    "L" if code != EXTRA else "D",
                    date(2010, 1, 1),
                    None if code != EXTRA else date(2020, 1, 1),
                )
                for code in (A, B, EXTRA)
            ]
            upstream(
                conn,
                lake,
                DAYS,
                codes=(A, B, EXTRA),
                life=life,
                calendar=[
                    ("SSE", day, True, previous)
                    for day, previous in zip(
                        DAYS, (date(2026, 10, 9), *DAYS[:-1]), strict=True
                    )
                ],
            )
            for day in DAYS:
                write_factor_file(conn, lake, day, ((A, 1), (B, 1)))
        seed_upstream_events(instance)
        _extra_upstream_events(instance)

        class BusinessDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return state.clock.astimezone(tz)

        monkeypatch.setattr(partitions, "datetime", BusinessDateTime)
        monkeypatch.setattr(sensor, "_now", lambda: state.clock)
        monkeypatch.setattr(asset, "_now", lambda: state.clock)
        monkeypatch.setattr(sensor, "DEFAULT_LAKE_STAGING_ROOT", staging)
        monkeypatch.setattr(
            asset, "probe_stk_factor_pro_source", probe_stk_factor_pro_source
        )

        def check_paths(value):
            text = str(value)
            assert "/Volumes/datasource/" not in text
            assert all(str(path) not in text for path in state.forbidden)

        class ObservedConnection:
            def __init__(self, native):
                self.native = native

            def execute(self, sql, *args, **kwargs):
                check_paths((sql, args, kwargs))
                state.totals["duckdb_sql"] += 1
                state.totals["parquet_sql"] += "read_parquet" in sql.lower()
                state.totals["copy_sql"] += sql.lstrip().upper().startswith("COPY")
                if state.kind == "sensor":
                    assert "/stk_factor_pro/" not in str((sql, args, kwargs))
                    assert "/stock_factor_pro/" not in str((sql, args, kwargs))
                return self.native.execute(sql, *args, **kwargs)

            def __getattr__(self, name):
                return getattr(self.native, name)

        @contextmanager
        def observed_connection(_base=tmp_path):
            with connection(_base) as conn:
                try:
                    yield ObservedConnection(conn)
                finally:
                    closing = perf_counter()
            state.totals["duckdb_close_seconds"] += perf_counter() - closing

        # The existing job resource resolves this module global on each connect.
        monkeypatch.setattr(job_support, "connection", observed_connection)
        state.connect = observed_connection
        state.resources = {
            "lake_root": dg.ResourceDefinition.hardcoded_resource(
                SimpleNamespace(
                    root=lambda: lake, ensure_available_for_run=lambda: None
                )
            ),
            "duckdb": dg.ResourceDefinition.hardcoded_resource(
                SimpleNamespace(connect=observed_connection)
            ),
        }
        native_open, native_replace = Path.open, os.replace

        def observed_open(path, *args, **kwargs):
            check_paths(path)
            if path.suffix == ".parquet" and (not args or "r" in args[0]):
                state.totals["sha_file_opens"] += 1
                state.opened[path] += 1
                if state.kind == "sensor":
                    assert "/stk_factor_pro/" not in str(path)
                    assert "/stock_factor_pro/" not in str(path)
            return native_open(path, *args, **kwargs)

        def observed_replace(source, target):
            check_paths((source, target))
            target = Path(target)
            if target.is_relative_to(lake) and target.suffix == ".parquet":
                state.totals["physical_replaces"] += 1
            return native_replace(source, target)

        monkeypatch.setattr(Path, "open", observed_open)
        monkeypatch.setattr(os, "replace", observed_replace)
        for name in ("fetch_page", "close"):
            original = getattr(HttpProTransport, name)

            def timed(self, *args, _method=original, _name=name, **kwargs):
                started = perf_counter()
                try:
                    return _method(self, *args, **kwargs)
                finally:
                    state.totals["http_" + _name + "_calls"] += 1
                    state.totals["http_" + _name + "_seconds"] += (
                        perf_counter() - started
                    )

            monkeypatch.setattr(HttpProTransport, name, timed)

        def sql_executed(conn, cursor, statement, parameters, context, many):
            assert conn.dialect.name == "sqlite"
            state.totals["native_sql"] += 1

        event.listen(Engine, "before_cursor_execute", sql_executed)
        for name in (
            "fetch_materializations",
            "fetch_observations",
            "get_records_for_run",
            "get_run_by_id",
            "get_run_records",
            "get_materialized_partitions",
        ):
            original = getattr(dg.DagsterInstance, name)

            def counted(self, *args, _method=original, _name=name, **kwargs):
                state.totals["api_" + _name] += 1
                return _method(self, *args, **kwargs)

            monkeypatch.setattr(dg.DagsterInstance, name, counted)

        def respond(payload, number):
            assert payload["api_name"] == "stk_factor_pro"
            fields, params = tuple(payload["fields"].split(",")), payload["params"]
            if "trade_date" in params:
                day = date.fromisoformat(params["trade_date"])
                assert params == {
                    "trade_date": day.strftime("%Y%m%d"),
                    "limit": 10000,
                    "offset": 0,
                }
                if fields == ("ts_code", "trade_date"):
                    values = [
                        (code, day.strftime("%Y%m%d")) for code in state.probes[day]
                    ]
                else:
                    assert fields == NAMES
                    values = state.daily[day]
            else:
                assert fields == NAMES
                assert params == {
                    "ts_code": A,
                    "start_date": "20261013",
                    "end_date": "20261016",
                    "limit": 10000,
                    "offset": 0,
                }
                values = state.history
            body = {"code": 0, "data": {"fields": list(fields), "items": values}}
            return Reply(
                200, encode_request(body, state.configuration.max_response_bytes)
            )

        try:
            with localhost_source(respond) as (url, requests):
                state.configuration = ConfigurationSnapshot("isolated-token", url)
                state.requests = requests
                monkeypatch.setattr(
                    asset.ConfigurationLoader,
                    "load_configuration",
                    lambda: state.configuration,
                )
                yield state
        finally:
            event.remove(Engine, "before_cursor_execute", sql_executed)
            record_property(
                "measurements", json.dumps(state.measurements, sort_keys=True)
            )
            assert not counts["initialization"]


def measure(scene, label, kind, action):
    before, http = scene.totals.copy(), len(scene.requests)
    opened = scene.opened.copy()
    started, previous = perf_counter(), scene.kind
    scene.kind = kind
    try:
        return action()
    finally:
        scene.measurements.append(
            {
                "label": label,
                "seconds": perf_counter() - started,
                "http": len(scene.requests) - http,
                **dict(scene.totals - before),
            }
        )
        scene.kind = previous
        if kind == "sensor":
            assert all(count == 1 for count in (scene.opened - opened).values())


def tick(scene):
    def evaluate():
        with (
            dg.partition_loading_context(
                dynamic_partitions_store=scene.instance, effective_dt=scene.clock
            ),
            dg.build_sensor_context(
                instance=scene.instance,
                cursor=scene.cursor,
                resources=scene.resources,
                sensor_name=C.STK_FACTOR_PRO_UPDATE_SENSOR_NAME,
                repository_def=scene.repository,
            ) as context,
        ):
            result = sensor.raw_tushare_stk_factor_pro_update_job_sensor.evaluate_tick(
                context
            )
        scene.cursor = result.cursor
        return result

    return measure(scene, "tick:" + scene.clock.isoformat(), "sensor", evaluate)


def register(scene):
    def evaluate():
        with dg.build_sensor_context(
            instance=scene.instance, resources=scene.resources
        ) as context:
            result = partitions.stock_factor_pro_trade_day_sensor.evaluate_tick(context)
        for request in result.dynamic_partitions_requests:
            assert isinstance(request, dg.AddDynamicPartitionsRequest)
            scene.instance.add_dynamic_partitions(
                request.partitions_def_name, request.partition_keys
            )
        return result

    return measure(scene, "partition:" + scene.clock.isoformat(), "partition", evaluate)


def automatic(scene, request):
    day = scene.clock.date().isoformat()
    slot = (scene.clock.hour - 19) * 2 + scene.clock.minute // 30
    assert request.partition_key == day
    assert (
        request.run_key == f"raw_tushare_stk_factor_pro_update_job:{day}/{day}/{slot}"
    )
    assert request.tags == {
        "goldenshare/stk_factor_pro_execution_day": day,
        "goldenshare/stk_factor_pro_target_trade_date": day,
        "goldenshare/stk_factor_pro_scheduled_slot": str(slot),
        PARTITION_NAME_TAG: day,
        PARTITION_SET_TAG: "raw_tushare_stk_factor_pro_update_job_partition_set",
        SENSOR_NAME_TAG: C.STK_FACTOR_PRO_UPDATE_SENSOR_NAME,
    }
    assert request.run_config == {
        "ops": {
            "stk_factor_pro": {
                "config": {
                    "execution_day": day,
                    "target_trade_date": day,
                    "purpose": "today",
                    "scheduled_slot": slot,
                    "bootstrap_operation_id": None,
                    "expected_bootstrap_approval_digest": None,
                    "expected_bootstrap_date_result_digest": None,
                }
            }
        }
    }
    # Same extra tags as Dagster's daemon; retain the actual request unchanged.
    tags = {
        **request.tags,
        SENSOR_NAME_TAG: C.STK_FACTOR_PRO_UPDATE_SENSOR_NAME,
        RUN_KEY_TAG: request.run_key,
    }
    completed = measure(
        scene,
        "automatic:" + day + f"/{slot}",
        "job",
        lambda: scene.job.execute_in_process(
            instance=scene.instance,
            partition_key=request.partition_key,
            run_config=request.run_config,
            tags=tags,
            raise_on_error=False,
        ),
    )
    run = scene.instance.get_run_by_id(completed.run_id)
    assert run.run_config == request.run_config
    assert all(run.tags[k] == v for k, v in tags.items())
    return completed


def facts(scene, day=DAY):
    result = asset.readiness.read_stk_factor_pro_recorded_results(
        scene.instance, target_trade_date=day, known_pg={}
    )
    saved = scene.phase_results[day]
    assert result.day_result_ref.storage_id == saved["day"][0]
    assert result.history_result_ref.storage_id == saved["history"][0]
    return result


def publications(scene, completed, expected):
    result = measure(
        scene,
        "readback:" + completed.run_id,
        "readback",
        lambda: _read_publications(scene, completed, expected),
    )
    assert scene.measurements[-1].get("parquet_sql", 0) == 2 * len(expected)
    return result


def _read_publications(scene, completed, expected):
    """One final read of each published file; independent all-261 value oracle."""
    mats = scene.instance.get_records_for_run(
        completed.run_id,
        of_type=dg.DagsterEventType.ASSET_MATERIALIZATION,
        limit=2 * len(expected) + 1,
    ).records
    checks = scene.instance.get_records_for_run(
        completed.run_id,
        of_type=dg.DagsterEventType.ASSET_CHECK_EVALUATION,
        limit=2 * len(expected) + 1,
    ).records
    assert len(mats) == len(checks) == 2 * len(expected)
    by_key = {(record.asset_key, record.partition_key): record for record in mats}
    observations = scene.instance.get_records_for_run(
        completed.run_id,
        of_type=dg.DagsterEventType.ASSET_OBSERVATION,
        limit=5,  # start + day + one history batch progress + final, plus one
        ascending=True,
    ).records
    phases = {}
    run = scene.instance.get_run_by_id(completed.run_id)
    target = run.run_config["ops"]["stk_factor_pro"]["config"]["target_trade_date"]
    for record in observations:
        metadata = record.asset_observation.metadata
        values = {key: value.value for key, value in metadata.items()}
        assert record.asset_key == asset._RAW and record.partition_key == target
        assert values["producer_run_id"] == completed.run_id
        assert values["target_trade_date"] == target
        assert values["bootstrap_context"] is None
        assert values["bootstrap_coverage_refs"] == []
        assert values["bootstrap_summary_ref"] is None
        kind = values["observation_kind"]
        if kind in phases:
            # The existing publisher persists one waiting observation after the
            # single (<20 trade days) batch, before final history completion.
            assert kind == "history" and phases[kind][1]["result"] == "waiting"
        phases[kind] = (record.storage_id, values)
    assert len(observations) == (4 if len(expected) > 1 else 3 if expected else 1)
    assert set(phases) == ({"start", "day", "history"} if expected else {"start"})
    if expected:
        assert phases["day"][1]["result"] == "completed"
        assert phases["history"][1]["result"] == (
            "waiting"
            if not completed.success
            else "completed"
            if len(expected) > 1
            else "no_action"
        )
    with scene.connect() as conn:
        for day, source_rows in expected.items():
            raw_sha = None
            for layer, key, path in (
                ("raw", asset._RAW, raw_stk_factor_pro_path(scene.lake, str(day))),
                (
                    "silver",
                    asset._SILVER,
                    silver_stock_factor_pro_path(scene.lake, str(day)),
                ),
            ):
                record = by_key[key, str(day)]
                metadata = record.asset_materialization.metadata
                assert metadata[FILE_PATH_METADATA_KEY].value == str(path)
                assert (
                    metadata["goldenshare/contract_content_digest"].value
                    == C.STK_FACTOR_PRO_CONTRACT_CONTENT_DIGEST
                )
                sha = metadata["goldenshare/file_sha256"].value
                assert len(sha) == 64
                if layer == "raw":
                    raw_sha = sha
                else:
                    assert metadata["goldenshare/raw_sha256"].value == raw_sha
                result = conn.execute(
                    "SELECT * FROM read_parquet(?, hive_partitioning=false) ORDER BY ts_code,trade_date",
                    [str(path)],
                )
                assert tuple(column[0] for column in result.description) == NAMES
                assert tuple(str(column[1]) for column in result.description) == (
                    "VARCHAR",
                    "VARCHAR" if layer == "raw" else "DATE",
                    *("DOUBLE" for _ in NAMES[2:]),
                )
                expected_rows = [
                    (
                        values[0],
                        values[1] if layer == "raw" else day,
                        *(
                            None if value is None else float(value)
                            for value in values[2:]
                        ),
                    )
                    for values in sorted(source_rows)
                ]
                assert result.fetchall() == expected_rows
    for record in checks:
        check = record.event_log_entry.dagster_event.event_specific_data
        materialization = by_key[check.asset_key, check.partition]
        assert check.passed and check.blocking
        assert check.check_name == (
            C.STK_FACTOR_PRO_RAW_CHECK_NAME
            if check.asset_key == asset._RAW
            else C.STK_FACTOR_PRO_SILVER_CHECK_NAME
        )
        binding = check.target_materialization_data
        assert (binding.storage_id, binding.run_id, binding.timestamp) == (
            materialization.storage_id,
            completed.run_id,
            materialization.timestamp,
        )
    if expected:
        scene.phase_results[date.fromisoformat(target)] = phases
    return phases


def seed_history(scene):
    """Existing Raw 13/14/15; only day13 is the audited native starting fact."""
    scene.seed_rows = {}
    with scene.connect() as conn:
        for day in (FIRST, P14, PREVIOUS):
            values = (
                _source_row(scene, day),
                row(B, day.strftime("%Y%m%d"), adj_factor=1),
            )
            scene.seed_rows[day] = values
            path = raw_stk_factor_pro_path(scene.lake, str(day))
            path.parent.mkdir(parents=True, exist_ok=True)
            frame = candidates.build_stk_factor_pro_raw_batch(
                rows=values,
                source="http",
                source_fields=NAMES,
                expected_dates=(day,),
            )
            conn.register("seed_input", frame)
            conn.execute("COPY seed_input TO ? (FORMAT PARQUET)", [str(path)])
            if day == FIRST:
                audit = audit_stk_factor_pro_file(
                    conn,
                    path=path,
                    expected_relation="seed_input",
                    target_trade_date=day,
                    layer="raw",
                    known_records={},
                )
                assert audit.passed and audit.row_count == 2
            conn.unregister("seed_input")
    # Bootstrap-shaped historical partition registrations are separate from the
    # target partition, which must still come from the actual partition sensor.
    scene.instance.add_dynamic_partitions(
        C.STK_FACTOR_PRO_PARTITIONS, [str(day) for day in (FIRST, P14, PREVIOUS)]
    )
    metadata = {
        FILE_PATH_METADATA_KEY: str(audit.path),
        "goldenshare/file_sha256": audit.file_sha256,
        "goldenshare/contract_content_digest": C.STK_FACTOR_PRO_CONTRACT_CONTENT_DIGEST,
        "goldenshare/processing_version": C.STK_FACTOR_PRO_PROCESSING_VERSION,
    }
    scene.instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset._RAW,
            partition=str(FIRST),
            metadata=metadata,
        )
    )
    materialization = scene.instance.fetch_materializations(
        dg.AssetRecordsFilter(asset._RAW, asset_partitions=[str(FIRST)]),
        limit=1,
    ).records[0]
    scene.instance.report_runless_asset_event(
        AssetCheckEvaluation(
            asset_key=asset._RAW,
            check_name=C.STK_FACTOR_PRO_RAW_CHECK_NAME,
            partition=str(FIRST),
            passed=audit.passed,
            blocking=True,
            metadata=metadata,
            target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                storage_id=materialization.storage_id,
                run_id=materialization.run_id,
                timestamp=materialization.timestamp,
            ),
        )
    )


def test_partition_wait_first_publication_reopen_and_unchanged(scene):
    assert not tick(scene).run_requests
    assert scene.measurements[-1]["http"] == 0
    added = register(scene).dynamic_partitions_requests
    assert [request.partition_keys for request in added] == [[str(PREVIOUS), str(DAY)]]
    assert not register(scene).dynamic_partitions_requests
    scene.probes[DAY] = (A,)
    assert not tick(scene).run_requests
    assert scene.measurements[-1]["http"] == 1
    assert not raw_stk_factor_pro_path(scene.lake, str(DAY)).exists()
    scene.clock = scene.clock.replace(minute=1)
    assert not tick(scene).run_requests
    assert scene.measurements[-1]["http"] == 0
    scene.clock = scene.clock.replace(minute=30)
    scene.probes[DAY] = (A, B)
    (request,) = tick(scene).run_requests
    assert scene.measurements[-1]["http"] == 1
    result = automatic(scene, request)
    assert result.success
    assert scene.measurements[-1]["http"] == 1
    assert scene.measurements[-1]["physical_replaces"] == 2
    publications(scene, result, {DAY: scene.daily[DAY]})
    assert facts(scene).raw_coverage.complete
    # Force work to be necessary: a valid completed-day shortcut cannot explain
    # the skip. Reopen native storage, clear cursor, keep the submitted slot.
    with scene.connect() as conn:
        write_factor_file(conn, scene.lake, DAY, ((A, 2), (B, 1)))
    original = scene.instance
    original.dispose()
    with _isolated_instance(scene.base) as reopened:
        scene.instance, scene.cursor = reopened, None
        assert (
            reopened.get_run_by_id(result.run_id).tags[RUN_KEY_TAG] == request.run_key
        )
        assert not tick(scene).run_requests
        assert scene.measurements[-1]["http"] == 0
        with scene.connect() as conn:
            write_factor_file(conn, scene.lake, DAY, ((A, 1), (B, 1)))
        scene.clock = scene.clock.replace(hour=20, minute=0)
        assert not tick(scene).run_requests
        assert scene.measurements[-1]["http"] == 0
    scene.instance = original


def test_midnight_gap_today_then_manual_date(scene):
    scene.clock = datetime.fromisoformat("2026-10-15T23:30:00+08:00")
    register(scene)
    scene.probes[PREVIOUS] = (A,)
    assert not tick(scene).run_requests
    assert scene.measurements[-1]["http"] == 1
    scene.clock = datetime.fromisoformat("2026-10-16T00:00:00+08:00")
    assert not tick(scene).run_requests
    assert scene.measurements[-1]["http"] == 0
    assert not raw_stk_factor_pro_path(scene.lake, str(PREVIOUS)).exists()
    assert not silver_stock_factor_pro_path(scene.lake, str(PREVIOUS)).exists()
    scene.clock = scene.clock.replace(hour=19)
    assert [r.partition_keys for r in register(scene).dynamic_partitions_requests] == [
        [str(DAY)]
    ]
    (request,) = tick(scene).run_requests
    today = automatic(scene, request)
    assert today.success
    publications(scene, today, {DAY: scene.daily[DAY]})
    scene.probes[PREVIOUS] = (A, B)
    # D=16's revised authority must not be consulted when explicitly filling T=15.
    with scene.connect() as conn:
        write_factor_file(conn, scene.lake, DAY, ((A, 2), (B, 1)))
    manual = measure(
        scene,
        "manual:2026-10-15",
        "job",
        lambda: scene.job.execute_in_process(
            instance=scene.instance,
            partition_key=str(PREVIOUS),
            raise_on_error=False,
            run_config={
                "ops": {
                    "stk_factor_pro": {
                        "config": {
                            "execution_day": "2026-10-16",
                            "target_trade_date": "2026-10-15",
                            "purpose": "manual_date",
                            "scheduled_slot": None,
                            "bootstrap_operation_id": None,
                            "expected_bootstrap_approval_digest": None,
                            "expected_bootstrap_date_result_digest": None,
                        }
                    }
                }
            },
        ),
    )
    assert manual.success
    assert scene.measurements[-1]["http"] == 2
    assert scene.measurements[-1]["physical_replaces"] == 2
    publications(scene, manual, {PREVIOUS: scene.daily[PREVIOUS]})
    assert facts(scene, PREVIOUS).raw_coverage.complete
    assert not scene.counts["initialization"]


@pytest.mark.parametrize("revision", ["T", "P"])
def test_history_wait_then_complete_range_redownload(scene, revision):
    seed_history(scene)
    register(scene)
    (request,) = tick(scene).run_requests
    first = automatic(scene, request)
    assert first.success
    publications(scene, first, {DAY: scene.daily[DAY]})
    revised_day = DAY if revision == "T" else PREVIOUS
    with scene.connect() as conn:
        write_factor_file(conn, scene.lake, revised_day, ((A, 2), (B, 1)))
    scene.daily[DAY] = (
        _source_row(scene, DAY, 2 if revision == "T" else 1),
        scene.daily[DAY][1],
    )
    scene.history = tuple(
        _source_row(scene, day) for day in (FIRST, P14, PREVIOUS, DAY)
    )
    scene.clock = scene.clock.replace(minute=30)
    (request,) = tick(scene).run_requests
    waiting = automatic(scene, request)
    assert not waiting.success
    assert scene.measurements[-1]["http"] == 2, waiting.failure_data_for_node(
        "stk_factor_pro"
    )  # full T + whole historical range
    assert scene.measurements[-1].get("physical_replaces", 0) == (
        2 if revision == "T" else 0
    )
    publications(scene, waiting, {DAY: scene.daily[DAY]})
    failure = waiting.failure_data_for_node("stk_factor_pro").user_failure_data.metadata
    assert failure["goldenshare/retryable"].value is True
    pending = facts(scene)
    assert (
        pending.pending_plan_refs
        and pending.unresolved_history_failure_run_id == waiting.run_id
    )
    failed_root = stk_factor_pro_run_staging_root(
        scene.staging, waiting.run_id, str(DAY)
    )
    scene.forbidden.extend(failed_root / part for part in ("source", "candidates"))
    scene.history = tuple(
        _source_row(scene, day, 2 if day == revised_day else 1)
        for day in (FIRST, P14, PREVIOUS, DAY)
    )
    scene.clock = scene.clock.replace(hour=20, minute=0)
    (request,) = tick(scene).run_requests
    recovered = automatic(scene, request)
    assert recovered.success
    assert scene.measurements[-1]["http"] == 2
    # _publish_file compares the existing relation and uses mode=reuse when
    # identical. T is unchanged from waiting; P's Raw changes only in revision P.
    assert scene.measurements[-1]["physical_replaces"] == (3 if revision == "T" else 4)
    expected = {DAY: scene.daily[DAY]}
    for day in (FIRST, P14, PREVIOUS):
        expected[day] = (
            _source_row(scene, day, 2 if day == revised_day else 1),
            scene.seed_rows[day][1],
        )
    publications(scene, recovered, expected)
    resolved = facts(scene)
    assert (
        not resolved.pending_plan_refs
        and resolved.unresolved_history_failure_run_id is None
    )
    history_requests = [
        payload["params"]
        for _, payload, _ in scene.requests
        if "ts_code" in payload["params"]
    ]
    assert (
        history_requests
        == [
            {
                "ts_code": A,
                "start_date": "20261013",
                "end_date": "20261016",
                "limit": 10000,
                "offset": 0,
            }
        ]
        * 2
    )
    scene.clock = scene.clock.replace(minute=30)
    assert not tick(scene).run_requests
    assert scene.measurements[-1]["http"] == 0


@pytest.mark.parametrize("change", ["missing", "extra"])
def test_ready_probe_full_source_change_has_zero_publication(scene, change):
    register(scene)
    (request,) = tick(scene).run_requests
    scene.daily[DAY] = (
        scene.daily[DAY][:1]
        if change == "missing"
        else (*scene.daily[DAY], row(EXTRA, "20261016", adj_factor=1))
    )
    result = automatic(scene, request)
    assert not result.success
    assert scene.measurements[-1]["http"] == 1
    assert scene.measurements[-1].get("physical_replaces", 0) == 0
    publications(scene, result, {})
    assert not raw_stk_factor_pro_path(scene.lake, str(DAY)).exists()
    assert not silver_stock_factor_pro_path(scene.lake, str(DAY)).exists()
    failure = result.failure_data_for_node("stk_factor_pro").user_failure_data.metadata
    assert failure["goldenshare/retryable"].value is True
    assert "本次完整日源" in failure["goldenshare/summary"].value
    assert ("缺失1，额外0" if change == "missing" else "缺失0，额外1") in failure[
        "goldenshare/summary"
    ].value
