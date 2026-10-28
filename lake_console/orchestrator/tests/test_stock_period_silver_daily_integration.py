"""Actual Raw producer -> observations -> sensors -> Silver jobs/checks -> ack.

The HTTP response is replaced with the existing source-contract literal fixture;
files, checkpoints, SQL selection, event storage, jobs and checks are real and temporary.
"""

import json
import time

import dagster as dg
import pytest

from orchestrator.defs import paths
from orchestrator.defs import stock_period_silver as silver
from orchestrator.defs.checks import stock_period_silver_checks as checks
from orchestrator.defs.io.stock_period_raw import file_version
from orchestrator.defs.io.stock_period_silver import read_json, run_directory
from orchestrator.defs.run_contracts.stock_period import COMPLETION_METADATA_KEY
from orchestrator.defs.run_contracts.stock_period_silver import target_path
from tests.test_stock_period_silver_contracts import A
from tests.test_stock_period_silver_contracts import (
    period_fixture as period_fixture,  # noqa: PLC0414
)
from tests.test_stock_period_silver_contracts import (
    update_fixture as update_fixture,  # noqa: PLC0414
)
from tests.test_stock_period_silver_jobs import definitions
from tests.test_stock_period_silver_sensors import context


def tick(f, ctx, freq):
    return silver.evaluate_update_sensor(ctx, freq=freq, staging_root=f["staging"])


def run_request(f, request, monkeypatch):
    monkeypatch.setattr(paths, "DEFAULT_LAKE_STAGING_ROOT", str(f["staging"]))
    monkeypatch.setattr(checks, "DEFAULT_LAKE_STAGING_ROOT", str(f["staging"]))
    return (
        definitions(f["lake"])
        .resolve_job_def(request.job_name)
        .execute_in_process(
            instance=f["instance"],
            partition_key=request.partition_key,
            run_config=request.run_config,
            tags={"dagster/run_key": request.run_key},
        )
    )


def changed_two_frequencies(f):
    # Independent intended values: revise A's adjusted close, remove A's oldest
    # week. All other stocks and all unselected fields must be preserved.
    rows = []
    for original in f["state"]["rows"]:
        row = list(original)
        if row[0] == A:
            if row[3] == "week" and row[1] == "20140103":
                continue
            row[12] = "25.1250"
        rows.append(row)
    f["state"]["rows"] = rows
    return f["capture"](frequencies=["week", "month"])


def test_two_frequency_history_chain_and_native_anchor_completion(
    update_fixture, monkeypatch, record_property
):
    f = update_fixture
    contexts = {freq: context(f) for freq in ("week", "month")}
    before = {
        freq: f["instance"]
        .fetch_observations(
            dg.AssetKey(f"raw_tushare_stk_period_bar_adj_{freq}"), limit=100
        )
        .records
        for freq in contexts
    }
    changed_two_frequencies(f)
    selected, calls = [], []
    original = silver.select_period
    import resource
    from contextlib import contextmanager

    connect = silver.connect_configured_duckdb
    statements = []

    @contextmanager
    def counted_connection(*args, **kwargs):
        with connect(*args, **kwargs) as connection:

            class Proxy:
                def execute(self, statement, *args, **kwargs):
                    statements.append(statement)
                    return connection.execute(statement, *args, **kwargs)

                def __getattr__(self, name):
                    return getattr(connection, name)

            yield Proxy()

    monkeypatch.setattr(silver, "connect_configured_duckdb", counted_connection)

    def tracked(*args, **kwargs):
        selected.append((args[2], args[3]))
        return original(*args, **kwargs)

    monkeypatch.setattr(silver, "select_period", tracked)
    began = time.perf_counter()
    for freq, ctx in contexts.items():
        observations = (
            f["instance"]
            .fetch_observations(
                dg.AssetKey(f"raw_tushare_stk_period_bar_adj_{freq}"), limit=100
            )
            .records
        )
        assert len(observations) == len(before[freq]) + 1
        notice = (
            observations[0].asset_observation.metadata[COMPLETION_METADATA_KEY].value
        )
        assert notice["freq"] == freq and notice["file_count"] == 3
        with monkeypatch.context() as guard:
            guard.setattr(
                silver,
                "connect_configured_duckdb",
                lambda *a, **k: pytest.fail("sensor computed market data"),
            )
            requested = tick(f, ctx, freq)
        assert len(requested.run_requests) == 1
        request = requested.run_requests[0]
        assert request.partition_key == ("2026-10-16" if freq == "week" else "2026-10")
        assert run_request(f, request, monkeypatch).success
        run_id = request.run_config["ops"][
            request.job_name.removesuffix("_update_job")
        ]["config"]["execution_id"]
        work = run_directory(f["staging"], run_id)
        assert not (work / "events_complete.json").exists()
        versions = {
            u["period"]: file_version(u["target"])
            for u in read_json(work / "execution.json")["identity"]["units"]
        }
        calls.append((freq, len(versions)))
        with monkeypatch.context() as guard:
            guard.setattr(
                silver,
                "connect_configured_duckdb",
                lambda *a, **k: pytest.fail("completion recomputed market data"),
            )
            assert (
                tick(f, ctx, freq).skip_reason.skip_message == "silver_batch_complete"
            )
        assert read_json(work / "events_complete.json")["files"] == 3
        assert "pending" not in json.loads(ctx.cursor)
        for period, version in versions.items():
            assert file_version(target_path(f["lake"], freq, period)) == version
    assert len(selected) == len(set(selected)) == 6
    assert (
        sum(statement.lstrip().upper().startswith("COPY ") for statement in statements)
        == 6
    )
    assert calls == [("week", 3), ("month", 3)]
    # Independent literal result, including removal of the only listed first-week
    # row. No selector or normalizer generates these expected values.
    from orchestrator.defs.duckdb_connection import (
        DuckDBConnectionSettings,
        connect_configured_duckdb,
    )

    with connect_configured_duckdb(
        settings=DuckDBConnectionSettings(
            temp_directory=f["staging"] / "readback",
            memory_limit="256MiB",
            threads=1,
        )
    ) as con:
        assert (
            con.execute(
                "SELECT count(*) FROM read_parquet(?,hive_partitioning=false)",
                [str(target_path(f["lake"], "week", "2014-01-03"))],
            ).fetchone()[0]
            == 0
        )
        for freq, period in [("week", "2026-10-16"), ("month", "2026-10")]:
            assert con.execute(
                "SELECT ts_code,close_qfq::VARCHAR FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code",
                [str(target_path(f["lake"], freq, period))],
            ).fetchall() == [
                ("000001.SZ", "25.1250"),
                ("301569.SZ", "11.1400"),
                ("920000.BJ", "11.1400"),
            ]
    record_property("two_frequency_chain_seconds", time.perf_counter() - began)
    record_property(
        "process_peak_rss_bytes", resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    )


@pytest.mark.parametrize("fault", ["failed", "wrong_binding"])
def test_native_completion_refuses_latest_real_failure_or_binding(
    update_fixture, monkeypatch, fault
):
    from orchestrator.defs.run_contracts.stock_period_silver import check_names
    from tests.test_stock_period_silver_events import emit_test_check

    f = update_fixture
    ctx = context(f)
    f["capture"]()
    request = tick(f, ctx, "week").run_requests[0]
    assert run_request(f, request, monkeypatch).success
    period = "2014-01-03" if fault == "wrong_binding" else "2026-10-16"
    mat = (
        f["instance"]
        .fetch_materializations(
            dg.AssetRecordsFilter(
                asset_key=dg.AssetKey("silver_stock_weekly"), asset_partitions=[period]
            ),
            limit=1,
        )
        .records[0]
    )
    emit_test_check(
        f["instance"],
        "silver_stock_weekly",
        "2026-10-16",
        check_names("week")[0],
        mat,
        passed=fault == "wrong_binding",
    )
    result = tick(f, ctx, "week")
    assert not result.run_requests
    assert "checks_not_ready" in result.skip_reason.skip_message
    work = run_directory(
        f["staging"], json.loads(ctx.cursor)["pending"]["execution_id"]
    )
    assert not (work / "events_complete.json").exists()


@pytest.mark.parametrize("freq", ["week", "month"])
def test_actual_sensor_definition_evaluates_real_receipt(
    update_fixture, monkeypatch, freq
):
    from orchestrator.defs.sensors.silver_stock_monthly_update_job_sensor import (
        silver_stock_monthly_update_job_sensor,
    )
    from orchestrator.defs.sensors.silver_stock_weekly_update_job_sensor import (
        silver_stock_weekly_update_job_sensor,
    )

    f = update_fixture
    initial = context(f).cursor
    f["capture"](freq=freq)
    # Same actual helper, but evaluate the Dagster definition rather than directly
    # invoking it. Temporary roots replace the resource/staging boundary only.
    import orchestrator.defs.paths as path_module

    monkeypatch.setattr(path_module, "DEFAULT_LAKE_STAGING_ROOT", str(f["staging"]))
    definition = (
        silver_stock_weekly_update_job_sensor
        if freq == "week"
        else silver_stock_monthly_update_job_sensor
    )
    with (
        dg.build_sensor_context(
            instance=f["instance"],
            cursor=initial,
            definitions=definitions(f["lake"]),
            resources={"lake_root": definitions(f["lake"]).resources["lake_root"]},
        ) as ctx,
        dg.partition_loading_context(dynamic_partitions_store=f["instance"]),
    ):
        result = definition.evaluate_tick(ctx)
    assert len(result.run_requests) == 1
    assert (
        result.run_requests[0].job_name
        == f"silver_stock_{'weekly' if freq == 'week' else 'monthly'}_update_job"
    )


def test_completion_record_failure_resumes_without_recomputing(
    update_fixture, monkeypatch
):
    f = update_fixture
    ctx = context(f)
    f["capture"]()
    request = tick(f, ctx, "week").run_requests[0]
    assert run_request(f, request, monkeypatch).success
    pending = json.loads(ctx.cursor)["pending"]
    work = run_directory(f["staging"], pending["execution_id"])
    original = silver.atomic_json

    def failed(path, value):
        if path == work / "events_complete.json":
            raise OSError("injected completion save failure")
        return original(path, value)

    with monkeypatch.context() as fault:
        fault.setattr(silver, "atomic_json", failed)
        assert "save failure" in tick(f, ctx, "week").skip_reason.skip_message
    assert "pending" in json.loads(ctx.cursor)
    monkeypatch.setattr(
        silver,
        "connect_configured_duckdb",
        lambda *a, **k: pytest.fail("completion resumed compute"),
    )
    assert tick(f, ctx, "week").skip_reason.skip_message == "silver_batch_complete"
    assert tick(f, ctx, "week").skip_reason.skip_message == "silver_no_completion"


def test_duplicate_closed_notification_after_later_update_does_not_reopen_old_files(
    update_fixture, monkeypatch
):
    from orchestrator.defs.run_contracts.stock_period import completion_notice
    from orchestrator.defs.stock_period_update import report_completion_events

    f = update_fixture
    ctx = context(f)
    first = f["capture"]()
    request = tick(f, ctx, "week").run_requests[0]
    assert run_request(f, request, monkeypatch).success
    assert tick(f, ctx, "week").skip_reason.skip_message == "silver_batch_complete"
    changed_two_frequencies(f)
    request = tick(f, ctx, "week").run_requests[0]
    assert run_request(f, request, monkeypatch).success
    assert tick(f, ctx, "week").skip_reason.skip_message == "silver_batch_complete"
    report_completion_events(f["instance"], completion_notice(first, "week", 3))
    monkeypatch.setattr(
        silver,
        "connect_configured_duckdb",
        lambda *a, **k: pytest.fail("old batch replay computed data"),
    )
    assert (
        tick(f, ctx, "week").skip_reason.skip_message == "silver_batch_already_complete"
    )


def test_raw_notification_receipt_failure_replays_only_notification(
    update_fixture, monkeypatch
):
    from pathlib import Path

    from orchestrator.defs.bootstrap import stock_period_history as raw
    from orchestrator.defs.stock_period_update import report_completion_events

    f = update_fixture
    ref = f["capture"]()
    run = f["staging"] / "stock_period/runs" / ref["raw_execution_id"]
    # Simulate a crash after observation persistence and before its local receipt.
    cp = run / "events/completion/week.json"
    cp.unlink()
    source_calls = len(f["source_calls"])
    versions = {
        i["target"]: file_version(i["target"])
        for i in read_json(run / "complete.json")["files"]
    }
    save = raw.atomic_json

    def failed(path, value):
        if path == cp:
            raise OSError("injected notification receipt failure")
        return save(path, value)

    def replay():
        return raw.replay_events(
            run,
            root=f["lake"],
            staging=f["staging"],
            events=lambda *a, **k: pytest.fail("completed file events replayed"),
            completion_events=lambda notice: report_completion_events(
                f["instance"], notice
            ),
        )

    with monkeypatch.context() as fault:
        fault.setattr(raw, "atomic_json", failed)
        with pytest.raises(OSError, match="receipt failure"):
            replay()
    assert replay()["events_complete"]
    assert read_json(cp)["completion"]["upstream_batch_id"] == ref["upstream_batch_id"]
    assert len(f["source_calls"]) == source_calls
    assert all(
        file_version(Path(path)) == version for path, version in versions.items()
    )


def test_completion_source_drift_does_not_save_success(update_fixture, monkeypatch):
    from pathlib import Path

    f = update_fixture
    ctx = context(f)
    f["capture"]()
    request = tick(f, ctx, "week").run_requests[0]
    assert run_request(f, request, monkeypatch).success
    work = run_directory(
        f["staging"], json.loads(ctx.cursor)["pending"]["execution_id"]
    )
    execution = read_json(work / "execution.json")
    source = Path(execution["identity"]["units"][0]["source"])
    save = silver.atomic_json
    changed = False

    def drift(path, value):
        nonlocal changed
        save(path, value)
        if path.parent.parent == work / "events" and not changed:
            changed = True
            with source.open("ab") as stream:
                stream.write(b"unpublished-change")

    monkeypatch.setattr(silver, "atomic_json", drift)
    message = tick(f, ctx, "week").skip_reason.skip_message
    assert message.split(";", 1)[0] == "silver_event_file_changed"
    assert "files_complete=true" in message
    recovery_config = json.loads(message.split(";run_config=", 1)[1])
    assert recovery_config == request.run_config
    assert not (work / "events_complete.json").exists()
    assert "pending" in json.loads(ctx.cursor)
