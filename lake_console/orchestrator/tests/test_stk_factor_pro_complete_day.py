"""Step-four admission, using producer-shaped files and native temporary jobs.

Only the archived HTTP replay below claims the probe/download transport boundary.
Other job cases explicitly substitute those boundaries through actual_job.
"""

from datetime import datetime, time, timedelta
from decimal import Decimal
from time import perf_counter, sleep
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import dagster as dg
import pytest
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
    AssetCheckEvaluationTargetMaterializationData,
)

from orchestrator.defs.assets import stk_factor_pro as asset
from orchestrator.defs.io import stk_factor_pro_candidates as candidates
from orchestrator.defs.paths import (
    raw_stk_factor_pro_path,
    silver_stock_factor_pro_path,
    silver_stock_identity_map_path,
    silver_stock_suspend_daily_path,
)
from orchestrator.defs.source_readiness import stk_factor_pro as source_probe_module
from orchestrator.defs.source_readiness.stk_factor_pro import (
    probe_stk_factor_pro_source,
)
from orchestrator.tushare_download.configuration import ConfigurationSnapshot
from orchestrator.tushare_download.contract_registry import ContractRegistry
from orchestrator.tushare_download.contracts import CONTRACTS
from orchestrator.tushare_download.dataset_transport_mapping import (
    BINDINGS,
    DatasetTransportMapping,
)
from orchestrator.tushare_download.download_api import _build_downloader
from orchestrator.tushare_download.http_transport import encode_request
from orchestrator.tushare_download.source_transport import (
    SystemClock,
    transport_factory,
)
from tests.stk_factor_pro_history_test_support import saved_real_rows
from tests.stk_factor_pro_test_support import DAY, NAMES, connection, row
from tests.test_stk_factor_pro_batch5_job_integration import seed_upstream_events
from tests.test_stk_factor_pro_bootstrap_coverage import upstream
from tests.test_stk_factor_pro_jobs import (
    EXTRA,
    PREVIOUS,
    A,
    B,
    config,
    input_files,
    isolated_update_environment,
)
from tests.tushare_download.test_tushare_download_http_integration import (
    Reply,
    localhost_source,
)

REFERENCE_READY = asset._reference_inputs_ready


@pytest.fixture
def actual_job(tmp_path, monkeypatch):
    with isolated_update_environment(tmp_path, monkeypatch) as environment:
        yield environment


def execute(environment, **kwargs):
    instance, job, *_ = environment
    return job.execute_in_process(
        instance=instance,
        partition_key=str(DAY),
        run_config=config(**kwargs),
        raise_on_error=False,
    )


def raw_file(conn, lake, codes):
    """Real Raw batch producer, with literal codes/dates; no coverage helper."""
    frame = candidates.build_stk_factor_pro_raw_batch(
        rows=tuple(row(code) for code in codes),
        source="http",
        source_fields=NAMES,
        expected_dates=(DAY,),
    )
    conn.register("existing_raw", frame)
    path = raw_stk_factor_pro_path(lake, str(DAY))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn.execute("COPY existing_raw TO ? (FORMAT PARQUET)", [str(path)])
    conn.unregister("existing_raw")
    return path


def extra_identity(conn, lake):
    # EXTRA has a valid historical identity but is no longer listed on T.
    life = [
        (
            c,
            c[:6],
            c,
            "SZSE" if c == A else "SSE",
            None,
            "CNY",
            True,
            "L",
            PREVIOUS,
            None,
        )
        for c in (A, B)
    ]
    life.append(
        (
            EXTRA,
            EXTRA[:6],
            EXTRA,
            "SZSE",
            None,
            "CNY",
            True,
            "D",
            PREVIOUS.replace(year=2010),
            PREVIOUS,
        )
    )
    upstream(conn, lake, (PREVIOUS, DAY), codes=(A, B, EXTRA), life=life)


@pytest.mark.parametrize(
    "codes,missing,extra", [((A,), 1, 0), ((A, B, EXTRA), 0, 1), ((), 2, 0)]
)
def test_incomplete_current_source_cannot_use_old_raw_or_publish(
    tmp_path, actual_job, codes, missing, extra
):
    _, _, source, lake, staging, _ = actual_job
    input_files(tmp_path, lake, changed=())
    with connection(tmp_path) as conn:
        extra_identity(conn, lake)
        path = raw_file(conn, lake, (A, B))
    before = path.read_bytes()
    source(codes and tuple(row(code) for code in codes) or ())
    result = execute(actual_job)
    assert not result.success
    assert not result.get_asset_materialization_events()
    assert path.read_bytes() == before
    assert not silver_stock_factor_pro_path(lake, str(DAY)).exists()
    failure = result.failure_data_for_node("stk_factor_pro").user_failure_data.metadata
    assert failure["goldenshare/retryable"].value is True
    assert (
        failure["goldenshare/missing_count"].value,
        failure["goldenshare/extra_count"].value,
    ) == (missing, extra)
    assert not tuple(staging.rglob("*intent*"))


def test_complete_source_but_old_extra_candidate_stops_before_raw_lift(
    tmp_path, actual_job
):
    _, _, source, lake, _, _ = actual_job
    input_files(tmp_path, lake, changed=())
    with connection(tmp_path) as conn:
        extra_identity(conn, lake)
        path = raw_file(conn, lake, (A, B, EXTRA))
    before = path.read_bytes()
    source((row(A), row(B)))
    result = execute(actual_job)
    assert not result.success and not result.get_asset_materialization_events()
    failure = result.failure_data_for_node("stk_factor_pro").user_failure_data.metadata
    assert "最终Raw候选" in failure["goldenshare/summary"].value
    assert failure["goldenshare/retryable"].value is False
    assert failure["goldenshare/extra_sample_codes"].value == [EXTRA]
    assert path.read_bytes() == before
    assert not silver_stock_factor_pro_path(lake, str(DAY)).exists()


def test_failed_source_metadata_limits_samples_without_writing_diagnostics(
    tmp_path, actual_job
):
    _, _, source, lake, staging, _ = actual_job
    codes = tuple(f"{n:06d}.SZ" for n in range(1, 22))
    input_files(tmp_path, lake, changed=(), codes=codes)
    source(())
    failed = execute(actual_job)
    assert not failed.success
    metadata = failed.failure_data_for_node("stk_factor_pro").user_failure_data.metadata
    assert metadata["goldenshare/missing_count"].value == 21
    assert metadata["goldenshare/missing_sample_codes"].value == list(codes[:20])
    assert metadata["goldenshare/extra_sample_codes"].value == []
    assert not raw_stk_factor_pro_path(lake, str(DAY)).exists()
    assert not list(staging.rglob("*missing*.parquet"))


@pytest.mark.parametrize("optional_present", [False, True])
def test_first_listing_day_optional_and_distinct_inputs_checked_once(
    tmp_path, monkeypatch, actual_job, optional_present
):
    _, _, source, lake, _, _ = actual_job
    input_files(tmp_path, lake, changed=())
    with connection(tmp_path) as conn:
        life = [
            (
                c,
                c[:6],
                c,
                "SZSE" if c == A else "SSE",
                None,
                "CNY",
                True,
                "L",
                DAY if c == B else PREVIOUS,
                None,
            )
            for c in (A, B)
        ]
        upstream(conn, lake, (PREVIOUS, DAY), codes=(A, B), life=life)
    calls, expected = [], []
    calculate = asset.readiness.calculate_stk_factor_pro_coverage
    prepare = asset.readiness._prepare_stk_factor_pro_expected_keys

    def counted(conn, **kwargs):
        calls.append(kwargs["raw_relation"])
        return calculate(conn, **kwargs)

    def counted_prepare(conn, **kwargs):
        expected.append(id(conn))
        return prepare(conn, **kwargs)

    monkeypatch.setattr(asset.readiness, "calculate_stk_factor_pro_coverage", counted)
    monkeypatch.setattr(
        asset.readiness, "_prepare_stk_factor_pro_expected_keys", counted_prepare
    )
    monkeypatch.setattr(
        asset,
        "probe_stk_factor_pro_source",
        lambda *a, **k: pytest.fail("automatic job repeats probe"),
    )
    source((row(A), row(B)) if optional_present else (row(A),))
    result = execute(actual_job)
    assert result.success, result.failure_data_for_node("stk_factor_pro")
    assert calls == [candidates.DAY_SOURCE, candidates.RAW_EXPECTED]
    assert len(expected) == 1
    with connection(tmp_path) as conn:
        assert conn.execute(
            "SELECT ts_code,pe FROM read_parquet(?) ORDER BY 1",
            [str(raw_stk_factor_pro_path(lake, str(DAY)))],
        ).fetchall() == ([(A, None), (B, None)] if optional_present else [(A, None)])
    assert len(result.get_asset_materialization_events()) == 2


def test_manual_probe_waits_before_plan_start_or_full_download(
    tmp_path, monkeypatch, actual_job
):
    instance, _, source, lake, _, _ = actual_job
    input_files(tmp_path, lake, changed=())
    downloader = source((row(A), row(B)))
    probes = []

    def probe(conn, **kwargs):
        probes.append(kwargs["target_trade_date"])
        assert "coverage_keys" in kwargs["coverage_inputs"]
        return SimpleNamespace(ready=False, coverage_counts=None, reason="源端缺码")

    monkeypatch.setattr(asset, "probe_stk_factor_pro_source", probe)
    monkeypatch.setattr(
        asset, "_plan_history", lambda *a, **k: pytest.fail("planned before probe")
    )
    tomorrow = DAY + timedelta(days=1)
    monkeypatch.setattr(
        asset,
        "_now",
        lambda: datetime.combine(tomorrow, time(10), ZoneInfo("Asia/Shanghai")),
    )
    result = execute(
        actual_job, execution_day=tomorrow, purpose="manual_date", slot=None
    )
    assert result.success and probes == [DAY] and not downloader.calls
    assert not result.get_asset_materialization_events()
    records = instance.get_records_for_run(
        result.run_id, of_type=dg.DagsterEventType.ASSET_OBSERVATION
    ).records
    assert len(records) == 1
    assert (
        "PRECHECK_NO_DOWNLOAD"
        in records[0].asset_observation.metadata["goldenshare/summary"].value
    )


def test_new_automatic_job_checks_midnight_again_after_planning(
    tmp_path, monkeypatch, actual_job
):
    _, _, source, lake, _, _ = actual_job
    input_files(tmp_path, lake, changed=())
    downloader = source((row(A), row(B)))
    plan = asset._plan_history

    def crossed_midnight(*args, **kwargs):
        result = plan(*args, **kwargs)
        monkeypatch.setattr(
            asset,
            "_now",
            lambda: datetime.combine(
                DAY + timedelta(days=1), time(), ZoneInfo("Asia/Shanghai")
            ),
        )
        return result

    monkeypatch.setattr(asset, "_plan_history", crossed_midnight)
    result = execute(actual_job)
    assert result.success and not downloader.calls
    assert not result.get_asset_materialization_events()


def test_reference_checks_bind_native_latest_events_and_cache_bounded_reads(
    tmp_path, actual_job, monkeypatch
):
    instance = actual_job[0]
    seed_upstream_events(instance)
    reads, batches = [], []
    fetch = instance.fetch_materializations
    checks = instance.event_log_storage.get_latest_asset_check_execution_by_key

    def counted_fetch(*args, **kwargs):
        reads.append(kwargs["limit"])
        return fetch(*args, **kwargs)

    def counted_checks(keys):
        batches.append(len(keys))
        return checks(keys)

    monkeypatch.setattr(instance, "fetch_materializations", counted_fetch)
    monkeypatch.setattr(
        instance.event_log_storage,
        "get_latest_asset_check_execution_by_key",
        counted_checks,
    )
    known = {}
    assert REFERENCE_READY(instance, DAY, known) == (True, "")
    assert REFERENCE_READY(instance, DAY, known) == (True, "")
    assert reads == [1, 1] and batches == [5]
    # A genuinely newer producer event must invalidate the older check binding.
    instance.report_runless_asset_event(
        dg.AssetMaterialization(
            asset.upstream_readiness.RAW_STOCK_BASIC_READINESS_SPEC.asset_key
        )
    )
    assert REFERENCE_READY(instance, DAY, {})[0] is False


@pytest.mark.parametrize(
    "problem", ["failed", "missing", "binding", "partition", "older_lifecycle", "stale"]
)
def test_reference_rejects_invalid_native_check_or_reference(problem, actual_job):
    instance = actual_job[0]
    specs = (
        asset.upstream_readiness.RAW_STOCK_BASIC_READINESS_SPEC,
        asset.upstream_readiness.SILVER_STOCK_LIFECYCLE_READINESS_SPEC,
    )

    @dg.op(out={})
    def references(context):
        for spec in reversed(specs) if problem == "older_lifecycle" else specs:
            yield dg.AssetMaterialization(spec.asset_key)
        records = context.instance.get_records_for_run(
            context.run_id, of_type=dg.DagsterEventType.ASSET_MATERIALIZATION
        ).records
        materials = {r.asset_key: r for r in records}
        for spec in specs:
            material = materials[spec.asset_key]
            for index, name in enumerate(spec.blocking_check_names):
                if problem == "missing" and index == 0:
                    continue
                yield AssetCheckEvaluation(
                    asset_key=spec.asset_key,
                    check_name=name,
                    passed=problem != "failed",
                    blocking=True,
                    partition=str(DAY) if problem == "partition" else None,
                    target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                        storage_id=material.storage_id
                        + (1 if problem == "binding" else 0),
                        run_id=context.run_id,
                        timestamp=material.timestamp,
                    ),
                )

    @dg.job
    def reference_job():
        references()

    executed = reference_job.execute_in_process(instance=instance, raise_on_error=False)
    assert executed.success is (problem != "failed")
    target = DAY.replace(year=2099) if problem == "stale" else DAY
    ready, reason = REFERENCE_READY(instance, target, {})
    assert ready is False and reason


def test_job_reference_wait_stops_before_probe_plan_and_download(
    tmp_path, monkeypatch, actual_job
):
    _, _, source, lake, _, _ = actual_job
    input_files(tmp_path, lake, changed=())
    downloader = source((row(A), row(B)))
    monkeypatch.setattr(
        asset, "_reference_inputs_ready", lambda *a: (False, "最新生命周期检查未绑定")
    )
    monkeypatch.setattr(
        asset,
        "probe_stk_factor_pro_source",
        lambda *a, **k: pytest.fail("probe before prerequisites"),
    )
    monkeypatch.setattr(
        asset, "_plan_history", lambda *a, **k: pytest.fail("plan before prerequisites")
    )
    tomorrow = DAY + timedelta(days=1)
    monkeypatch.setattr(
        asset,
        "_now",
        lambda: datetime.combine(tomorrow, time(10), ZoneInfo("Asia/Shanghai")),
    )
    result = execute(
        actual_job, execution_day=tomorrow, purpose="manual_date", slot=None
    )
    assert result.success and not downloader.calls
    assert not result.get_asset_materialization_events()


@pytest.mark.parametrize(
    "missing_path", [silver_stock_identity_map_path, silver_stock_suspend_daily_path]
)
def test_job_missing_coverage_basis_waits_before_download(
    tmp_path, monkeypatch, actual_job, missing_path
):
    _, _, source, lake, _, _ = actual_job
    input_files(tmp_path, lake, changed=())
    path = (
        missing_path(lake)
        if missing_path is silver_stock_identity_map_path
        else missing_path(lake, str(DAY))
    )
    path.unlink()
    downloader = source((row(A), row(B)))
    monkeypatch.setattr(
        asset,
        "_plan_history",
        lambda *a, **k: pytest.fail("plan before coverage basis"),
    )
    result = execute(actual_job)
    assert result.success and not downloader.calls
    assert not result.get_asset_materialization_events()


@pytest.mark.parametrize("failure", ["silver", "event_save"])
def test_raw_survives_real_job_failure_then_new_run_downloads_complete_day(
    tmp_path, monkeypatch, actual_job, failure
):
    instance, _, source, lake, _, _ = actual_job
    input_files(tmp_path, lake, changed=())
    first_source = source((row(A), row(B)))
    with monkeypatch.context() as fault:
        if failure == "silver":

            def failed_silver(*args, **kwargs):
                raise OSError("injected Silver candidate failure")

            fault.setattr(
                asset.publication,
                "build_stk_factor_pro_silver_candidate",
                failed_silver,
            )
        else:
            save = instance.event_log_storage.store_event

            def missing_materialization(event):
                if (
                    event.dagster_event is not None
                    and event.dagster_event.event_type_value == "ASSET_MATERIALIZATION"
                ):
                    return
                return save(event)

            fault.setattr(
                instance.event_log_storage, "store_event", missing_materialization
            )
        failed = execute(actual_job)
    assert not failed.success
    assert len(first_source.calls) == 1
    assert raw_stk_factor_pro_path(lake, str(DAY)).is_file()
    assert not silver_stock_factor_pro_path(lake, str(DAY)).exists()
    materials = instance.get_records_for_run(
        failed.run_id, of_type=dg.DagsterEventType.ASSET_MATERIALIZATION
    ).records
    assert len(materials) == (1 if failure == "silver" else 0)
    fresh = source((row(A, close=Decimal(12)), row(B, close=Decimal(12))))
    recovered = execute(actual_job)
    assert recovered.success, recovered.failure_data_for_node("stk_factor_pro")
    assert recovered.run_id != failed.run_id and len(fresh.calls) == 1
    assert len(recovered.get_asset_materialization_events()) == 2
    with connection(tmp_path) as conn:
        assert conn.execute(
            "SELECT ts_code,close FROM read_parquet(?) ORDER BY 1",
            [str(raw_stk_factor_pro_path(lake, str(DAY)))],
        ).fetchall() == [(A, 12.0), (B, 12.0)]


def test_archived_real_source_manual_probe_then_full_261_download(
    tmp_path, monkeypatch, actual_job, record_property
):
    _, _, _, lake, _, _ = actual_job
    input_files(tmp_path, lake, changed=(), codes=(A,))
    # Saved real 000001.SZ record, 2026-10-16; contract fixes order and Decimal/NULL.
    sample = saved_real_rows()[-1]
    assert sample[:2] == (A, "20261016") and len(sample) == 261
    calculations, preparations = [], []
    calculate = asset.readiness.calculate_stk_factor_pro_coverage
    prepare = asset.readiness._prepare_stk_factor_pro_expected_keys

    def counted_calculate(conn, **kwargs):
        calculations.append(kwargs["raw_relation"])
        return calculate(conn, **kwargs)

    def counted_prepare(conn, **kwargs):
        preparations.append(id(conn))
        return prepare(conn, **kwargs)

    monkeypatch.setattr(
        asset.readiness, "calculate_stk_factor_pro_coverage", counted_calculate
    )
    monkeypatch.setattr(
        source_probe_module, "calculate_stk_factor_pro_coverage", counted_calculate
    )
    monkeypatch.setattr(
        asset.readiness, "_prepare_stk_factor_pro_expected_keys", counted_prepare
    )

    def respond(payload, attempt):
        fields = payload["fields"].split(",")
        assert payload["api_name"] == "stk_factor_pro"
        assert payload["params"]["trade_date"] == "20261016"
        indices = [NAMES.index(field) for field in fields]
        body = {
            "code": 0,
            "data": {"fields": fields, "items": [[sample[i] for i in indices]]},
        }
        return Reply(200, encode_request(body, 67108864))

    with localhost_source(respond) as (url, requests):
        configuration = ConfigurationSnapshot("isolated-token", url)
        monkeypatch.setattr(
            asset.ConfigurationLoader, "load_configuration", lambda: configuration
        )
        monkeypatch.setattr(
            asset, "probe_stk_factor_pro_source", probe_stk_factor_pro_source
        )
        downloader = _build_downloader(
            configuration,
            ContractRegistry(CONTRACTS),
            DatasetTransportMapping(BINDINGS),
            transport_factory,
            SystemClock(),
            sleep,
        )
        monkeypatch.setattr(
            asset.download.TushareDownloader, "load", lambda: downloader
        )
        tomorrow = DAY + timedelta(days=1)
        monkeypatch.setattr(
            asset,
            "_now",
            lambda: datetime.combine(tomorrow, time(10), ZoneInfo("Asia/Shanghai")),
        )
        started = perf_counter()
        result = execute(
            actual_job, execution_day=tomorrow, purpose="manual_date", slot=None
        )
        elapsed = perf_counter() - started
        assert result.success, result.failure_data_for_node("stk_factor_pro")
    assert [r[1]["fields"] for r in requests] == ["ts_code,trade_date", ",".join(NAMES)]
    assert len(result.get_asset_materialization_events()) == 2
    assert calculations == [
        "stk_factor_pro_source_probe",
        candidates.DAY_SOURCE,
        candidates.RAW_EXPECTED,
    ]
    assert len(preparations) == 1
    with connection(tmp_path) as conn:
        assert conn.execute(
            "SELECT ts_code,trade_date,pe,typeof(trade_date),typeof(pe) FROM read_parquet(?,hive_partitioning=false)",
            [str(raw_stk_factor_pro_path(lake, str(DAY)))],
        ).fetchall() == [(A, "20261016", 5.2346, "VARCHAR", "DOUBLE")]
    record_property("archived_manual_job_seconds", round(elapsed, 3))
