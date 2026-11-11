"""Manual preview and real installed GraphQL client against an owned HTTP server.

The transport fixture checks the installed client's actual JSON. The schema test
below uses the installed Dagster GraphQL schema, queued isolated instance and a
small producer; it does not contact the formal code location or execute Lake IO.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import UUID

import dagster as dg
import pytest

from orchestrator.defs.bootstrap import stock_period_history_cli as cli
from orchestrator.defs.run_contracts.stock_period_history_repair import OP_NAME

BASE = [
    "--intent",
    "specified_history",
    "--business-date",
    "2026-11-10",
    "--frequency",
    "month",
    "--stock-code",
    " 000001.sz ",
]


def test_default_preview_normalizes_and_does_not_open_any_resource(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "roots", lambda *a: pytest.fail("preview entered bootstrap")
    )
    monkeypatch.setattr(
        cli, "submit_maintenance_request", lambda *a: pytest.fail("preview submitted")
    )
    assert cli.main(["maintain", *BASE, "--stock-code", "000001.SZ"]) == 0
    request = json.loads(capsys.readouterr().out)
    cfg = request["run_config"]["ops"][OP_NAME]["config"]
    assert cfg["stock_codes"] == ["000001.SZ"] and cfg["frequencies"] == ["month"]
    assert request["source_units"] == 1 and request["submitted"] is False
    assert request["file_count"] == "尚待源定位"


def test_identity_preview_preserves_physical_codes_and_labels():
    args = cli.parse_maintenance_args(
        [
            "--intent",
            "identity_maintenance",
            "--business-date",
            "2026-11-08",
            "--frequency",
            "month",
            "--remove-key",
            "832000.bj,20200229,month",
            "--remove-key",
            "832000.BJ,20200228,month",
            "--remove-key",
            "832000.BJ,20200229,month",
        ]
    )
    request = cli.build_maintenance_request(args)
    cfg = request["run_config"]["ops"][OP_NAME]["config"]
    assert (
        cfg["stock_codes"] == []
        and request["source_units"] == 0
        and request["file_count"] == 1
    )
    assert [k["trade_date"] for k in cfg["remove_keys"]] == ["20200228", "20200229"]
    assert cfg["remove_keys"][0]["ts_code"] == "832000.BJ"


@pytest.mark.parametrize(
    "extra",
    [
        ["--request-id", "x"],
        ["--rss-limit-gib", "6"],
        ["--lake-root", "/private/tmp"],
        ["--frequency", "month"],
        ["--submit"],
        ["--remove-key", "000001.SZ,20261130,month"],
        ["--upstream-completion", "{}"],
    ],
)
def test_invalid_or_mixed_options_cannot_submit(extra):
    with pytest.raises((ValueError, SystemExit)):
        args = cli.parse_maintenance_args([*BASE, *extra])
        cli.build_maintenance_request(args)


def test_factor_preview_derives_codes_but_preserves_original_upstream_contract(
    monkeypatch,
):
    from uuid import uuid4

    from orchestrator.defs import stock_period_history_repair as repair
    from orchestrator.defs.run_contracts.stock_period_delivery import delivery_ref

    refs = [
        delivery_ref(
            str(uuid4()),
            f,
            "daily",
            "2026-11-10",
            ["2026-11-13" if f == "week" else "2026-11"],
        )
        for f in ("week", "month")
    ]
    seen = []
    monkeypatch.setattr(
        repair,
        "load_factor_changed_codes",
        lambda root, day: seen.append(day) or ["000001.SZ"],
    )
    args = cli.parse_maintenance_args(
        [
            "--intent",
            "factor_changed",
            "--business-date",
            "2026-11-10",
            "--upstream-completion",
            json.dumps(refs[1]),
            "--upstream-completion",
            json.dumps(refs[0]),
        ]
    )
    request = cli.build_maintenance_request(args)
    assert request["source_units"] == 2 and seen == ["2026-11-10"]
    assert (
        request["run_config"]["ops"][OP_NAME]["config"]["upstream_completions"] == refs
    )


@pytest.fixture
def http_transport():
    seen = []
    state = {
        "status": 200,
        "data": {
            "launchPipelineExecution": {
                "__typename": "LaunchRunSuccess",
                "run": {"runId": "24d60c76-d676-4eba-9809-a1e168c345ba"},
            }
        },
    }

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(
                json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            )
            body = (json.dumps({"data": state["data"]}).encode() if state["status"] == 200 else b"service unavailable")
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield seen, state, f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join()


@pytest.mark.parametrize("mode", ["success", "rejected", "http_error"])
def test_installed_client_submits_full_job_once_without_retry(http_transport, mode):
    from dagster_graphql import DagsterGraphQLClientError

    seen, state, remote = http_transport
    if mode == "http_error":
        state["status"] = 503
    elif mode == "rejected":
        state["data"] = {
            "launchPipelineExecution": {
                "__typename": "PythonError",
                "message": "rejected",
                "stack": [],
            }
        }
    args = cli.parse_maintenance_args(
        [
            *BASE,
            "--submit",
            "--remote",
            remote,
            "--repository-location",
            "isolated",
            "--repository",
            "__repository__",
        ]
    )
    request = cli.build_maintenance_request(args)
    if mode == "success":
        result = cli.submit_maintenance_request(args, request)
        assert (
            str(UUID(result["run_id"])) == result["run_id"]
            and result["submitted"] is True
        )
    else:
        with pytest.raises(DagsterGraphQLClientError):
            cli.submit_maintenance_request(args, request)
    assert len(seen) == 1
    params = seen[0]["variables"]["executionParams"]
    assert params["selector"] == {
        "pipelineName": request["job_name"],
        "repositoryLocationName": "isolated",
        "repositoryName": "__repository__",
        "solidSelection": None,
        "assetSelection": None,
    }
    assert params["runConfigData"] == request["run_config"]


def test_installed_graphql_schema_accepts_config_and_registers_real_run(tmp_path):
    from dagster._core.definitions.reconstruct import ReconstructableJob
    from dagster._core.execution.api import execute_run
    from dagster_graphql.client.client_queries import (
        CLIENT_SUBMIT_PIPELINE_RUN_MUTATION,
    )
    from dagster_graphql.test.utils import (
        define_out_of_process_context,
        execute_dagster_graphql,
    )

    producer = tmp_path / "producer.py"
    producer.write_text("""import dagster as dg
from orchestrator.defs.run_contracts.stock_period_history_repair import StockPeriodHistoryRepairConfig
from orchestrator.defs.asset_guards.stock_period_silver_readiness import raw_check_names
from dagster._core.definitions.asset_checks.asset_check_evaluation import AssetCheckEvaluation,AssetCheckEvaluationTargetMaterializationData
@dg.op(out={})
def raw_stock_period_history_repair_op(context,config:StockPeriodHistoryRepairConfig):
    config.validate_intent()
    asset=dg.AssetKey("raw_tushare_stk_period_bar_adj_month")
    yield dg.AssetMaterialization(asset_key=asset,partition="2026-11")
    record=context.instance.get_records_for_run(context.run_id,of_type=dg.DagsterEventType.ASSET_MATERIALIZATION).records[0]
    for name in raw_check_names("month"):
        yield AssetCheckEvaluation(asset_key=asset,check_name=name,partition="2026-11",passed=True,blocking=True,target_materialization_data=AssetCheckEvaluationTargetMaterializationData(storage_id=record.storage_id,run_id=context.run_id,timestamp=record.timestamp))
@dg.job(executor_def=dg.in_process_executor)
def raw_stock_period_history_repair_job():
    raw_stock_period_history_repair_op()
def definitions():
    return dg.Definitions(jobs=[raw_stock_period_history_repair_job])
""")
    home = tmp_path / "instance"
    home.mkdir()
    with dg.DagsterInstance.local_temp(
        str(home),
        overrides={
            "telemetry": {"enabled": False},
            "run_coordinator": {
                "module": "dagster._core.run_coordinator.queued_run_coordinator",
                "class": "QueuedRunCoordinator",
            },
        },
    ) as instance, define_out_of_process_context(
        str(producer), "definitions", instance
    ) as ctx:
        request = cli.build_maintenance_request(cli.parse_maintenance_args(BASE))
        location = ctx.code_locations[0]
        repo = next(iter(location.get_repositories()))
        response = execute_dagster_graphql(
            ctx,
            CLIENT_SUBMIT_PIPELINE_RUN_MUTATION,
            variables={
                "executionParams": {
                    "selector": {
                        "repositoryLocationName": location.name,
                        "repositoryName": repo,
                        "pipelineName": request["job_name"],
                    },
                    "runConfigData": request["run_config"],
                    "mode": "default",
                }
            },
        )
        assert response.errors is None
        result = response.data["launchPipelineExecution"]
        assert result["__typename"] == "LaunchRunSuccess"
        run_id = result["run"]["runId"]
        assert str(UUID(run_id)) == run_id
        registered = instance.get_run_by_id(run_id)
        assert registered.run_config == request["run_config"]
        reconstructed = ReconstructableJob.for_file(
            str(producer), request["job_name"]
        )
        from dagster._core.events import DagsterEvent
        instance.report_dagster_event(DagsterEvent(event_type_value="PIPELINE_STARTING",job_name=registered.job_name),run_id=run_id)
        registered=instance.get_run_by_id(run_id)
        executed = execute_run(reconstructed, registered, instance, raise_on_error=True)
        assert executed.success and len(executed.get_asset_check_evaluations()) == 3
        checks = executed.get_asset_check_evaluations()
        assert all(c.target_materialization_data.run_id == run_id for c in checks)
