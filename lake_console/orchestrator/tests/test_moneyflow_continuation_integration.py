"""Real seven jobs/checks, native SQLite events and Parquet; fake source/clock/HTTP adapter only.

Input fixtures come from each existing source-contract definition test. Those fixtures
include independently literal fields, NULLs, stock keys and DC's three classifications.
This does not validate the formal queue, remote origin, Tushare network or PG instance.
"""

import importlib
import json
from types import SimpleNamespace

import pytest

from orchestrator.moneyflow_continuation.execution import apply
from orchestrator.moneyflow_continuation.state import NativeBackend
from tests.test_moneyflow_continuation_plan import AT, DAY, plan_for

pytestmark = pytest.mark.usefixtures("isolated_moneyflow_transport")


class LocalJobsBackend(NativeBackend):
    def __init__(self, env):
        super().__init__(env.instance)
        self.env, self.lake, self.staging = env, env.lake, env.staging
        self.posts = []

    def guard(self, plan, at):
        # Only isolated tests bypass formal mount/PG/config/loaded-code gates.
        assert "/Volumes" not in str(self.lake)
        assert self.env.instance.telemetry_enabled is False

    def validate_run(self, run, unit, layer, body=None):
        # execute_in_process has no RemoteJobOrigin. Origin rejection is tested independently.
        assert run.remote_job_origin is None
        values = run._asdict()
        # execute_in_process stores an empty asset-selection set for these complete jobs;
        # GraphQL stores None, verified independently on the accepted 10-08 runs.
        assert run.asset_selection == frozenset()
        values["asset_selection"] = None
        values["remote_job_origin"] = SimpleNamespace(
            job_name=unit[layer]["job"],
            repository_origin=SimpleNamespace(
                repository_name="__repository__",
                code_location_origin=SimpleNamespace(location_name="orchestrator"),
            ),
        )
        return super().validate_run(SimpleNamespace(**values), unit, layer, body)

    def mutate(self, body):
        self.posts.append(body)
        variables = body["variables"]
        if "partitionKey" in variables:
            self.env.instance.add_dynamic_partitions(
                variables["partitionsDefName"], [variables["partitionKey"]]
            )
            return {
                "data": {
                    "addDynamicPartition": {
                        "__typename": "AddDynamicPartitionSuccess",
                        "partitionKey": variables["partitionKey"],
                    }
                }
            }
        params = variables["executionParams"]
        tags = {t["key"]: t["value"] for t in params["executionMetadata"]["tags"]}
        result = self.env.defs.resolve_job_def(
            params["selector"]["jobName"]
        ).execute_in_process(
            instance=self.env.instance,
            partition_key=tags["dagster/partition"],
            tags=tags,
        )
        assert result.success
        return {
            "data": {
                "launchRun": {
                    "__typename": "LaunchRunSuccess",
                    "run": {"runId": result.run_id, "status": "SUCCESS"},
                }
            }
        }


@pytest.mark.parametrize(
    "dataset,rows,requests",
    [
        ("moneyflow_mkt_dc", 1, 2),
        ("moneyflow_ind_ths", 1, 2),
        ("moneyflow_cnt_ths", 1, 2),
        ("moneyflow_ind_dc", 3, 6),
        ("moneyflow_dc", 3, 2),
        ("moneyflow_ths", 3, 2),
        ("moneyflow", 3, 2),
    ],
)
def test_controller_real_jobs_files_checks_and_zero_write_repeat(
    dataset, rows, requests, tmp_path, monkeypatch
):
    suffix = "" if dataset == "moneyflow" else dataset.removeprefix("moneyflow")
    fixture = importlib.import_module(f"tests.test_moneyflow{suffix}_definitions")
    generator = fixture.env.__wrapped__(tmp_path, monkeypatch)
    env = next(generator)
    try:
        if dataset == "moneyflow_mkt_dc":
            env.source.responses = iter(
                [[fixture.row(day=DAY)], [fixture.row(day=DAY)]]
            )
        backend, plan = LocalJobsBackend(env), plan_for((dataset,))
        code, report = apply(
            backend,
            plan,
            root=tmp_path / "controller",
            output=lambda _: None,
            clock=lambda: AT,
        )
        assert code == 0, json.dumps(report)
        assert report["complete"] and report["completed"] == 1
        facts = backend.snapshots(plan["units"])[0]
        assert facts["raw"]["proof"]["rows"] == facts["silver"]["proof"]["rows"] == rows
        assert len(env.source.calls) == requests
        posts = len(backend.posts)
        code, repeated = apply(
            backend,
            plan,
            root=tmp_path / "controller",
            output=lambda _: None,
            clock=lambda: AT,
        )
        assert code == 0 and repeated["complete"]
        assert len(backend.posts) == posts and len(env.source.calls) == requests
        # Physical corruption must invalidate green events rather than trigger repair or a new run.
        from orchestrator.defs.paths import raw_moneyflow_path

        raw = raw_moneyflow_path(env.lake, dataset, DAY)
        raw.write_bytes(b"broken isolated fixture")
        code, failed = apply(
            backend,
            plan,
            root=tmp_path / "controller",
            output=lambda _: None,
            clock=lambda: AT,
        )
        assert code == 3 and not failed["complete"] and len(backend.posts) == posts
    finally:
        generator.close()


def test_readiness_batches_ten_dates_not_full_history(monkeypatch):
    from orchestrator.moneyflow_continuation import state
    from tests.test_moneyflow_continuation_state import snapshot

    days = tuple(f"2026-10-{i:02d}" for i in range(1, 17))
    plan = plan_for(days=days)
    backend = NativeBackend(
        SimpleNamespace(
            has_dynamic_partition=lambda *_: False, get_runs=lambda *_a, **_k: []
        )
    )
    calls = []

    def batch(instance, lake, dates, **kw):
        calls.append(dates)
        return {
            layer: {
                day: SimpleNamespace(
                    ready=False,
                    materialized=False,
                    reason="missing_materialization",
                    metadata={},
                )
                for day in dates
            }
            for layer in ("raw", "silver")
        }

    monkeypatch.setattr(state, "batch_moneyflow_readiness", batch)
    assert len(backend.snapshots(plan["units"])) == 16
    assert [len(c) for c in calls] == [10, 6]
    assert snapshot()["raw"]["ready"] is False


def test_source_dependencies_include_shared_symbols_and_tool_but_not_period_jobs():
    from orchestrator.moneyflow_continuation.state import dependency_files

    paths = dependency_files()
    assert "src/orchestrator/defs/paths.py" in paths
    assert "src/orchestrator/defs/run_contracts/asset_column_schemas.py" in paths
    assert "src/orchestrator/moneyflow_continuation/submission.py" in paths
    assert "src/orchestrator/defs/jobs/stock_monthly.py" not in paths
    assert "src/orchestrator/defs/jobs/stock_weekly.py" not in paths


def test_actual_http_response_loss_has_one_post_and_no_automatic_retry(monkeypatch):
    import http.server
    import threading

    from orchestrator.moneyflow_continuation import state
    from orchestrator.moneyflow_continuation.plan import request_for

    received = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(
                json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            )
            self.connection.close()  # Server consumed request, then loses response.

        def log_message(self, *_):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        monkeypatch.setattr(state, "ENDPOINT", f"http://127.0.0.1:{server.server_port}")
        request = request_for(plan_for()["units"][0], "raw", "2026-10-17")
        import http.client

        with pytest.raises(http.client.RemoteDisconnected):
            NativeBackend(None).mutate(request)
        assert received == [request]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(2)


def test_real_calendar_sql_uses_sse_open_days_only(tmp_path):
    # Literal columns/types from assets/calendar.py's Silver producer and
    # SILVER_TRADE_CALENDAR_SCHEMA, not inferred from this controller's SELECT.
    from orchestrator.defs.paths import silver_trade_calendar_path

    backend = NativeBackend(None)
    backend.lake, backend.staging = tmp_path / "lake", tmp_path / "staging"
    backend.lake.mkdir()
    backend.staging.mkdir()
    calendar = silver_trade_calendar_path(backend.lake)
    calendar.parent.mkdir(parents=True)
    with backend.connection() as connection:
        connection.execute(
            "CREATE TABLE calendar(exchange VARCHAR,trade_date DATE,is_open BOOLEAN,pretrade_date DATE)"
        )
        connection.execute(
            "INSERT INTO calendar VALUES ('SSE','2026-10-08',true,'2026-09-30'),"
            "('SSE','2026-10-09',false,'2026-10-08'),"
            "('SZSE','2026-10-12',true,'2026-10-08'),"
            "('SSE','2026-10-13',true,'2026-10-08')"
        )
        connection.execute(
            "COPY calendar TO $target (FORMAT PARQUET)", {"target": str(calendar)}
        )
    assert backend.calendar(
        ["2026-10-08", "2026-10-09", "2026-10-12", "2026-10-13"]
    ) == {"2026-10-08", "2026-10-13"}


@pytest.mark.parametrize("problem", ["count", "depth", "symlink"])
def test_run_scoped_disk_walk_refuses_unbounded_or_unsafe_inputs(tmp_path, problem):
    from orchestrator.moneyflow_continuation.contract import ContinuationError

    backend = NativeBackend(None)
    directory = tmp_path / "run"
    directory.mkdir()
    if problem == "count":
        for index in range(513):
            (directory / str(index)).touch()
    elif problem == "depth":
        parent = directory
        for index in range(10):
            parent = parent / str(index)
            parent.mkdir()
    else:
        (directory / "link").symlink_to(tmp_path)
    with pytest.raises(ContinuationError):
        backend.run_disk_size(directory)
