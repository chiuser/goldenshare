"""Independent THS merge expectations and isolated native Raw publication acceptance."""

import json
import shutil
import threading
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from time import perf_counter

import dagster as dg
import duckdb
import pytest

import orchestrator.defs.assets.moneyflow_ths as assets
import orchestrator.defs.io.moneyflow_daily_update as update
import orchestrator.defs.io.moneyflow_ths_raw_merge as merge
from orchestrator.defs.asset_guards.moneyflow_ths_readiness import (
    batch_stock_moneyflow_ths_readiness,
)
from orchestrator.defs.io.moneyflow_candidates import (
    candidate_file_hash,
    moneyflow_candidate_connection,
)
from orchestrator.defs.io.moneyflow_daily_raw_writer import (
    build_daily_moneyflow_raw_candidate,
)
from orchestrator.defs.paths import raw_moneyflow_path
from orchestrator.defs.run_contracts.moneyflow import MoneyflowContractError
from orchestrator.moneyflow_continuation.contract import ContinuationError
from orchestrator.moneyflow_continuation.state import NativeBackend
from tests import test_moneyflow_ths_definitions as definitions
from tests.moneyflow_ths_upstream_support import seed_market
from tests.test_moneyflow_ths_http_worker import (
    TOKEN,
    Reply,
    localhost_source,
    source_body,
)

pytest_plugins = ("tests.test_moneyflow_ths_http_worker",)
pytestmark = pytest.mark.usefixtures("isolated_moneyflow_transport")
env = definitions.env
DAY = definitions.DAY
FIELDS = definitions.MONEYFLOW_THS_FIELDS
A, B, C = "000001.SZ", "600000.SH", "000002.SZ"


def record(code, value="1", *, name="人工样本"):
    # All 13 fields and types independently checked against doc348 and Raw schema.
    return {"trade_date": DAY.replace("-", ""), "ts_code": code, "name": name,
            **{field: value for field in FIELDS[3:]}}


def raw_file(tmp_path, label, rows):
    directory = tmp_path / label
    directory.mkdir()
    source = definitions.Source(definitions.pages(rows) + definitions.pages(rows[::-1]))
    clock = definitions.Clock()
    return build_daily_moneyflow_raw_candidate(
        tushare=source, dataset="moneyflow_ths", staging_root=directory,
        operation_id="test", trade_date=DAY, clock=clock, sleep_fn=clock.sleep,
    )


def old_target(env, rows):
    source = raw_file(env.staging, "owned-old", rows)
    target = raw_moneyflow_path(env.lake, "moneyflow_ths", DAY)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return target


def read_rows(path, directory):
    with moneyflow_candidate_connection(directory) as connection:
        return connection.execute("SELECT * FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code", [str(path)]).fetchall()


@pytest.mark.parametrize("field", FIELDS[2:])
@pytest.mark.parametrize("before,after,expected", [("1", None, "1"), (None, "2", "2"), (None, None, None), ("1", "2", "2")])
def test_each_nullable_field_uses_new_non_null_and_preserves_old(tmp_path, field, before, after, expected):
    old, new = record(A), record(A)
    old[field], new[field] = before, after
    source = raw_file(tmp_path, "new", [new])
    prior = raw_file(tmp_path, "old", [old])
    final = tmp_path / "raw-merged.parquet"
    with moneyflow_candidate_connection(tmp_path) as connection:
        merge.merge_moneyflow_ths_raw_candidate(connection, source, prior, final)
        md = merge.moneyflow_ths_raw_metadata(connection, final, {A})
    value = read_rows(final, tmp_path)[0][FIELDS.index(field)]
    assert value == (expected if field == "name" or expected is None else Decimal(expected))
    assert md == {"row_count": 1, "scope_row_counts": {"all": 1}, "missing_record_codes": [], "null_value_codes": [A] if expected is None else []}


@pytest.mark.parametrize("value", ["0", "-2"])
@pytest.mark.parametrize("field", FIELDS[3:])
def test_zero_and_negative_are_revisions_not_null(tmp_path, field, value):
    old, new = record(A), record(A)
    new[field] = value
    source = raw_file(tmp_path, "new", [new])
    prior = raw_file(tmp_path, "old", [old])
    final = tmp_path / "raw-merged.parquet"
    with moneyflow_candidate_connection(tmp_path) as connection:
        merge.merge_moneyflow_ths_raw_candidate(connection, source, prior, final)
        assert merge.moneyflow_ths_raw_metadata(connection, final, {A})["null_value_codes"] == []
    assert read_rows(final, tmp_path)[0][FIELDS.index(field)] == Decimal(value)


def test_unit_merge_keeps_absent_rows_and_lists_final_missing_only(tmp_path):
    source = raw_file(tmp_path, "new", [record(B, "250"), record(C, "300")])
    prior = raw_file(tmp_path, "old", [record(A, "100", name=None), record(B, "200")])
    final = tmp_path / "raw-merged.parquet"
    with moneyflow_candidate_connection(tmp_path) as connection:
        merge.merge_moneyflow_ths_raw_candidate(connection, source, prior, final)
        md = merge.moneyflow_ths_raw_metadata(connection, final, {A, B, C, "000004.SZ"})
    assert [(r[1], r[5]) for r in read_rows(final, tmp_path)] == [(A, Decimal(100)), (C, Decimal(300)), (B, Decimal(250))]
    assert md == {"row_count": 3, "scope_row_counts": {"all": 3}, "missing_record_codes": ["000004.SZ"], "null_value_codes": [A]}


def test_no_old_raw_and_existing_unpublished_candidate_are_idempotent(tmp_path):
    source = raw_file(tmp_path, "new", [record(A)])
    prior, final = tmp_path / "absent.parquet", tmp_path / "raw-merged.parquet"
    with moneyflow_candidate_connection(tmp_path) as connection:
        merge.merge_moneyflow_ths_raw_candidate(connection, source, prior, final)
        digest = candidate_file_hash(final)
        merge.merge_moneyflow_ths_raw_candidate(connection, source, prior, final)
        assert candidate_file_hash(final) == digest
        final.write_bytes(b"owned incomplete candidate")
        with pytest.raises(duckdb.Error):
            merge.merge_moneyflow_ths_raw_candidate(connection, source, prior, final)
        assert final.read_bytes() == b"owned incomplete candidate"


@pytest.mark.parametrize("missing,allowed", [(0, True), (24, True), (25, False)])
def test_full_raw_candidate_missing_boundary_and_old_rows_cannot_mask_it(env, missing, allowed):
    codes = tuple(f"{i:06d}.SZ" for i in range(1, 31))
    seed_market(env.instance, env.lake, env.staging, (DAY,), codes=codes)
    target = old_target(env, [record(c) for c in codes])
    digest = candidate_file_hash(target)
    definitions.set_rows(env, [record(c, "2") for c in codes[missing:]])
    result = definitions.run(env, "raw_tushare_moneyflow_ths_update_job", raise_on_error=False)
    assert result.success is allowed
    if not allowed:
        assert candidate_file_hash(target) == digest
        assert not result.get_asset_materialization_events()
        failure = next(e.step_failure_data for e in result.all_events if e.event_type == dg.DagsterEventType.STEP_FAILURE)
        assert failure.user_failure_data.metadata["goldenshare/reason_code"].value == "source_missing_codes"
        assert failure.user_failure_data.metadata["goldenshare/retryable"].value is True
    else:
        md = result.get_asset_materialization_events()[0].event_specific_data.materialization.metadata
        assert md["goldenshare/missing_record_codes"].value == []
        assert md["dagster/row_count"].value == 30


@pytest.mark.parametrize("baseline", ["absent", "broken", "large"])
def test_ths_does_not_read_old_quantity_baselines(env, monkeypatch, baseline):
    from tests.moneyflow_baseline_support import seed_moneyflow_baseline

    if baseline == "broken":
        path = raw_moneyflow_path(env.lake, "moneyflow_ths", "2026-09-30")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"owned invalid irrelevant baseline")
    elif baseline == "large":
        seed_moneyflow_baseline(instance=env.instance, lake=env.lake, staging=env.staging,
                               dataset="moneyflow_ths", rows=[record(f"{i:06d}.SZ") for i in range(20)])
    monkeypatch.setattr(update, "moneyflow_row_count_baseline", lambda **kw: pytest.fail("THS must never query old baselines"))
    result = definitions.run(env, "raw_tushare_moneyflow_ths_update_job")
    assert result.success
    md = result.get_asset_materialization_events()[0].event_specific_data.materialization.metadata
    receipt = json.loads(Path(md["goldenshare/source_proof_path"].value).read_text())
    assert "row_count_guard" not in receipt and "goldenshare/row_count_guard" not in md


def publish_three_from_two(env):
    old_target(env, [record(A, "100", name=None), record(B, "200")])
    definitions.set_rows(env, [record(B, "250"), record(C, "300")])
    result = definitions.run(env, "raw_tushare_moneyflow_ths_update_job")
    assert result.success
    return result


def test_native_metadata_and_history_accept_source_two_final_three(env):
    result = publish_three_from_two(env)
    md = result.get_asset_materialization_events()[0].event_specific_data.materialization.metadata
    assert md["dagster/row_count"].value == 3
    assert isinstance(md["goldenshare/missing_record_codes"], dg.JsonMetadataValue)
    assert md["goldenshare/missing_record_codes"].value == []
    assert md["goldenshare/null_value_codes"].value == [A]
    receipt = json.loads(Path(md["goldenshare/source_proof_path"].value).read_text())
    assert receipt["row_count"] == 2 and receipt["scope_row_counts"] == {"all": 2}
    assert receipt["raw_sha256"] != md["goldenshare/file_sha256"].value
    backend = NativeBackend(env.instance)
    backend.lake, backend.staging = env.lake, env.staging
    delivery = batch_stock_moneyflow_ths_readiness(env.instance, env.lake, (DAY,), layers=("raw",))["raw"][DAY]
    assert delivery.ready
    assert backend.audit({"dataset": "moneyflow_ths", "trade_date": DAY}, "raw", delivery)["rows"] == 3


def test_native_missing_and_null_lists_are_distinct_sorted_json(env):
    codes = tuple(f"{i:06d}.SZ" for i in range(1, 31))
    seed_market(env.instance, env.lake, env.staging, (DAY,), codes=codes)
    rows = [record(f"{i:06d}.SZ") for i in range(25, 31)]
    rows[0]["name"] = None
    definitions.set_rows(env, rows)
    result = definitions.run(env, "raw_tushare_moneyflow_ths_update_job")
    md = result.get_asset_materialization_events()[0].event_specific_data.materialization.metadata
    assert md["dagster/row_count"].value == 6
    assert md["goldenshare/missing_record_codes"].value == [f"{i:06d}.SZ" for i in range(1, 25)]
    assert md["goldenshare/null_value_codes"].value == ["000025.SZ"]
    assert all(isinstance(md[key], dg.JsonMetadataValue) for key in ("goldenshare/missing_record_codes", "goldenshare/null_value_codes"))


def test_identical_raw_reuses_file_and_still_materializes_lists(env):
    first = definitions.run(env, "raw_tushare_moneyflow_ths_update_job")
    assert first.success
    target = raw_moneyflow_path(env.lake, "moneyflow_ths", DAY)
    before = (target.stat().st_ino, candidate_file_hash(target))
    definitions.set_rows(env, definitions.sample())
    second = definitions.run(env, "raw_tushare_moneyflow_ths_update_job")
    md = second.get_asset_materialization_events()[0].event_specific_data.materialization.metadata
    assert second.success and (target.stat().st_ino, candidate_file_hash(target)) == before
    assert md["goldenshare/promotion_mode"].value == "reuse"
    assert md["goldenshare/missing_record_codes"].value == []
    assert md["goldenshare/null_value_codes"].value == [A, C, B]


@pytest.mark.parametrize("bad", ["count", "source_hash", "verification", "publication"])
def test_history_still_rejects_false_source_or_publication_proofs(env, bad):
    result = publish_three_from_two(env)
    md = result.get_asset_materialization_events()[0].event_specific_data.materialization.metadata
    receipt_path = Path(md["goldenshare/source_proof_path"].value)
    receipt = json.loads(receipt_path.read_text())
    if bad == "count":
        receipt["row_count"] = 3
    elif bad == "source_hash":
        receipt["raw_sha256"] = "0" * 64
    elif bad == "verification":
        (receipt_path.parent / "verification.parquet").write_bytes(b"owned false verification")
    else:
        cp = receipt_path.parent / "promotion-raw.json"
        value = json.loads(cp.read_text()); value["published_sha256"] = "0" * 64
        cp.write_text(json.dumps(value))
    receipt_path.write_text(json.dumps(receipt))
    backend = NativeBackend(env.instance); backend.lake, backend.staging = env.lake, env.staging
    delivery = batch_stock_moneyflow_ths_readiness(env.instance, env.lake, (DAY,), layers=("raw",))["raw"][DAY]
    with pytest.raises((ContinuationError, MoneyflowContractError)):
        backend.audit({"dataset": "moneyflow_ths", "trade_date": DAY}, "raw", delivery)


def test_metadata_failure_keeps_published_file_then_new_run_recovers(env, monkeypatch):
    original = assets._result
    monkeypatch.setattr(assets, "_result", lambda *a: (_ for _ in ()).throw(RuntimeError("injected metadata failure")))
    failed = definitions.run(env, "raw_tushare_moneyflow_ths_update_job", raise_on_error=False)
    target = raw_moneyflow_path(env.lake, "moneyflow_ths", DAY)
    assert not failed.success and target.is_file() and not failed.get_asset_materialization_events()
    digest = candidate_file_hash(target)
    monkeypatch.setattr(assets, "_result", original)
    definitions.set_rows(env, [record(A)])
    recovered = definitions.run(env, "raw_tushare_moneyflow_ths_update_job")
    assert recovered.success and len(env.source.calls) == 4
    assert recovered.run_id != failed.run_id
    assert target.is_file() and candidate_file_hash(target) != digest


def test_existing_file_budget_is_not_raised(tmp_path):
    path = tmp_path / "owned-oversized.parquet"
    with path.open("wb") as stream:
        stream.truncate(4 * 1024**2 + 1)
    with pytest.raises(MoneyflowContractError, match="file_hash_budget"):
        merge.assert_moneyflow_ths_file_budget(path)


@pytest.mark.parametrize("missing", [24, 25])
def test_extra_suspended_row_does_not_reduce_missing_count(tmp_path, missing):
    expected = {f"{i:06d}.SZ" for i in range(1, 31)}
    rows = [record(f"{i:06d}.SZ") for i in range(missing + 1, 31)] + [record("000099.SZ")]
    raw = raw_file(tmp_path, "new", rows)
    with moneyflow_candidate_connection(tmp_path) as connection:
        if missing == 24:
            merge.assert_moneyflow_ths_source_coverage(connection, raw, expected, {"000099.SZ"})
        else:
            with pytest.raises(MoneyflowContractError, match="source_missing_codes") as error:
                merge.assert_moneyflow_ths_source_coverage(connection, raw, expected, {"000099.SZ"})
            assert error.value.retryable


def test_unknown_extra_code_is_not_dropped(tmp_path):
    raw = raw_file(tmp_path, "new", [record(A), record("999999.SH")])
    with (
        moneyflow_candidate_connection(tmp_path) as connection,
        pytest.raises(MoneyflowContractError, match="source_extra_codes"),
    ):
        merge.assert_moneyflow_ths_source_coverage(connection, raw, {A}, set())


def test_capacity_twenty_thousand_and_union_overflow(tmp_path, record_property):
    from dagster._serdes import serialize_value

    from orchestrator.defs.run_contracts.asset_column_schemas import (
        RAW_TUSHARE_MONEYFLOW_THS_SCHEMA,
    )

    rows = [record(f"{i:06d}.SZ", None, name=None) for i in range(20000)]
    source = raw_file(tmp_path, "new", rows)
    old = raw_file(tmp_path, "old", [record(f"{i:06d}.SZ") for i in range(20000, 40000)])
    final = tmp_path / "raw-merged.parquet"
    expected = {f"{i:06d}.SZ" for i in range(20000)}
    started = perf_counter()
    with moneyflow_candidate_connection(tmp_path) as connection:
        merge.merge_moneyflow_ths_raw_candidate(connection, source, tmp_path / "absent", final)
        md = merge.moneyflow_ths_raw_metadata(connection, final, expected)
        assert md["row_count"] == 20000 and md["missing_record_codes"] == []
        assert md["null_value_codes"] == [f"{i:06d}.SZ" for i in range(20000)]
        merged_overflow = tmp_path / "overflow.parquet"
        merge.merge_moneyflow_ths_raw_candidate(connection, source, old, merged_overflow)
        with pytest.raises(MoneyflowContractError, match="file_count_date_or_key"):
            merge.moneyflow_ths_raw_metadata(connection, merged_overflow, expected)
    materialization = assets._result({**md, "target": str(final)}, RAW_TUSHARE_MONEYFLOW_THS_SCHEMA)
    instance_path = tmp_path / "metadata-instance"
    instance_path.mkdir()
    with dg.DagsterInstance.local_temp(str(instance_path), overrides={"telemetry": {"enabled": False}}) as instance:
        instance.report_runless_asset_event(dg.AssetMaterialization(asset_key="raw_tushare_moneyflow_ths", partition=DAY, metadata=materialization.metadata))
        saved = instance.fetch_materializations(dg.AssetRecordsFilter(asset_key=dg.AssetKey("raw_tushare_moneyflow_ths"), asset_partitions=[DAY]), limit=1).records[0]
        assert saved.asset_materialization.metadata["goldenshare/null_value_codes"].value == [f"{i:06d}.SZ" for i in range(20000)]
        assert saved.asset_materialization.metadata["goldenshare/missing_record_codes"].value == []
        event_bytes = len(serialize_value(saved.event_log_entry).encode())
    record_property("ths_stage3_capacity", json.dumps({"seconds": perf_counter() - started, "source_rows": 20000, "final_rows": 20000, "overflow_rows_rejected": 40000, "null_codes": 20000, "final_bytes": final.stat().st_size, "saved_event_bytes": event_bytes}))


def test_complete_merge_without_intent_resumes_without_rewriting_or_source(env, monkeypatch):
    publication = definitions.publication
    original = publication._checkpoint
    def fail_before_intent(path, value):
        if value["stage"] == "intent":
            raise RuntimeError("injected before intent")
        original(path, value)
    monkeypatch.setattr(publication, "_checkpoint", fail_before_intent)
    kwargs = {"instance": env.instance, "dataset": "moneyflow_ths", "tushare": env.source,
              "lake_root": env.lake, "staging_root": env.staging, "operation_id": "before-intent", "trade_date": DAY}
    with pytest.raises(RuntimeError, match="injected before intent"):
        update.update_daily_moneyflow_raw(**kwargs)
    candidate = env.staging / "moneyflow/before-intent/moneyflow_ths" / DAY / "raw-merged.parquet"
    inode = candidate.stat().st_ino
    monkeypatch.setattr(publication, "_checkpoint", original)
    result = update.update_daily_moneyflow_raw(**kwargs)
    assert len(env.source.calls) == 2 and Path(result["target"]).stat().st_ino == inode


def test_failed_original_file_check_preserves_published_raw(env, monkeypatch):
    import orchestrator.defs.checks.moneyflow_ths as checks

    def reject(*args, **kwargs):
        raise MoneyflowContractError("injected_file_check_failure")
    monkeypatch.setattr(checks, "audit_file", reject)
    failed = definitions.run(env, "raw_tushare_moneyflow_ths_update_job", raise_on_error=False)
    assert not failed.success
    assert raw_moneyflow_path(env.lake, "moneyflow_ths", DAY).is_file()
    assert len(failed.get_asset_materialization_events()) == 1
    assert not failed.get_asset_check_evaluations()[0].passed


def test_expired_budget_after_intent_cannot_replace_target(env, monkeypatch):
    publication = definitions.publication
    original = publication._checkpoint
    offset = [0]
    clock = update.perf_counter
    monkeypatch.setattr(update, "perf_counter", lambda: clock() + offset[0])
    def expire(path, value):
        original(path, value)
        if value["stage"] == "intent":
            offset[0] = 301  # Inject crossing the existing 300-second budget.
    monkeypatch.setattr(publication, "_checkpoint", expire)
    with pytest.raises(MoneyflowContractError, match="request_budget_exceeded"):
        update.update_daily_moneyflow_raw(instance=env.instance, dataset="moneyflow_ths",
            tushare=env.source, lake_root=env.lake, staging_root=env.staging,
            operation_id="expired", trade_date=DAY)
    assert not raw_moneyflow_path(env.lake, "moneyflow_ths", DAY).exists()


def test_missing_actual_upstream_stops_before_any_source_request(env):
    from orchestrator.defs.paths import silver_stock_suspend_daily_path

    silver_stock_suspend_daily_path(env.lake, DAY).unlink()  # Owned fixture only.
    result = definitions.run(env, "raw_tushare_moneyflow_ths_update_job", raise_on_error=False)
    assert not result.success and not env.source.calls and not result.get_asset_materialization_events()
    assert not raw_moneyflow_path(env.lake, "moneyflow_ths", DAY).exists()


def test_raw_sql_interrupt_uses_deadline_and_reaps_timer(tmp_path, monkeypatch):
    timers = []
    real = threading.Timer
    def timer(*args):
        value = real(*args); timers.append(value); return value
    monkeypatch.setattr(merge, "Timer", timer)
    deadline = perf_counter() + 0.05  # Injected test deadline, not a production budget.
    def check():
        if perf_counter() >= deadline:
            raise MoneyflowContractError("request_budget_exceeded")
    with (
        pytest.raises(MoneyflowContractError, match="request_budget_exceeded"),
        merge.moneyflow_ths_raw_connection(tmp_path, deadline, check) as connection,
    ):
        connection.execute("SELECT sum(sin(i)) FROM range(1000000000) t(i)").fetchone()
    assert timers and all(not t.is_alive() for t in timers)


def test_real_http_worker_raw_job_merge_metadata_and_check(env, monkeypatch, ths_probe, record_property):
    from orchestrator.defs.source_readiness import moneyflow_daily, moneyflow_transport

    old_target(env, [record(A, "100", name=None), record(B, "200")])
    rows = [record(B, "250"), record(C, "300")]
    http_rows = [{k: Decimal(v) if k in FIELDS[3:] and v is not None else v for k, v in r.items()} for r in rows]
    monkeypatch.setattr(env.source, "token", TOKEN, raising=False)
    monkeypatch.setattr(update, "build_daily_moneyflow_raw_candidate", build_daily_moneyflow_raw_candidate)
    def request(*args, **kwargs):
        return moneyflow_transport.call_moneyflow_source(*args, **kwargs, _command=ths_probe.command)
    monkeypatch.setattr(moneyflow_daily, "call_moneyflow_source", request)
    import orchestrator.defs.checks.moneyflow_ths as checks
    import orchestrator.defs.io.moneyflow_candidates as candidates

    original_connection = candidates.connect_configured_duckdb
    sql, connections = [], []
    class Observed:
        def __init__(self, connection):
            self.connection = connection
        def execute(self, statement, *args, **kwargs):
            sql.append(statement)
            return self.connection.execute(statement, *args, **kwargs)
        def __getattr__(self, name):
            return getattr(self.connection, name)
    @contextmanager
    def observed(*args, **kwargs):
        with original_connection(*args, **kwargs) as connection:
            connections.append(connection)
            yield Observed(connection)
    monkeypatch.setattr(candidates, "connect_configured_duckdb", observed)
    monkeypatch.setattr(checks, "connect_configured_duckdb", observed)
    with localhost_source(lambda *_: Reply(200, source_body(FIELDS, http_rows))) as (url, received):
        monkeypatch.setenv("TUSHARE_BASE_URL", url)
        started = perf_counter()
        result = definitions.run(env, "raw_tushare_moneyflow_ths_update_job")
        elapsed = perf_counter() - started
    assert result.success and len(received) == 2 and len(ths_probe.owned) == 2
    assert all(r[1]["fields"] == ",".join(FIELDS) for r in received)
    assert all(r[1]["params"] == {"trade_date": "20261008", "limit": 2000, "offset": 0} for r in received)
    md = result.get_asset_materialization_events()[0].event_specific_data.materialization.metadata
    assert md["dagster/row_count"].value == 3
    assert md["goldenshare/missing_record_codes"].value == [] and md["goldenshare/null_value_codes"].value == [A]
    assert result.get_asset_check_evaluations()[0].passed
    receipt = json.loads(Path(md["goldenshare/source_proof_path"].value).read_text())
    assert receipt["row_count"] == 2 and receipt["stability_gap_seconds"] >= 60
    # P=2 nonempty pages, existing target changes: LLD 11P+42=64 business SQL.
    assert len(sql) == 64 and len(connections) == 4
    record_property("ths_stage3_http_raw", json.dumps({"seconds": elapsed, "requests": 2, "workers": 2, "source_rows": 2, "final_rows": 3, "business_sql": len(sql), "connections": len(connections), "loopback_only": True}))
