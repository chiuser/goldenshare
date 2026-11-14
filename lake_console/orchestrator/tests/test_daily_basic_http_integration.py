"""Real loopback JSON -> DG candidate -> isolated asset/check execution.

Artificial source rows follow doc32 (verified 2026-11-12); no production token,
source, database, instance or Lake is used. No fake-page fixture is enabled.
"""

import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from unittest.mock import patch

import dagster as dg
import pytest

from orchestrator.defs.asset_guards.daily_basic_readiness import (
    daily_basic_materializations,
)
from orchestrator.defs.assets.daily_basic import raw_tushare_daily_basic
from orchestrator.defs.checks.daily_basic_checks import (
    raw_tushare_daily_basic_file_contract_check,
    raw_tushare_daily_basic_source_coverage_check,
)
from orchestrator.defs.daily_basic_contract import (
    DailyBasicValidationError,
)
from orchestrator.defs.daily_basic_raw_io import write_daily_basic_partition
from orchestrator.defs.jobs.daily_basic_update import raw_tushare_daily_basic_update_job
from orchestrator.defs.partitions import cn_a_daily_basic_trade_days
from orchestrator.defs.paths import raw_daily_basic_path
from orchestrator.defs.resources import (
    DuckDBResource,
    LakeRootResource,
    TushareResource,
)
from orchestrator.defs.source_readiness.daily_basic import (
    fetch_daily_basic_pages,
    probe_daily_basic_for_trade_date,
)
from tests.test_daily_basic_raw_io import DAY, DB

# Independent literal source contract, not copied from the function under test.
FIELDS = (
    "ts_code",
    "trade_date",
    "close",
    "turnover_rate",
    "turnover_rate_f",
    "volume_ratio",
    "pe",
    "pe_ttm",
    "pb",
    "ps",
    "ps_ttm",
    "dv_ratio",
    "dv_ttm",
    "total_share",
    "float_share",
    "free_share",
    "total_mv",
    "circ_mv",
    "limit_status",
)


def source_rows(status=0):
    return [
        ["000001.SZ", "20260914", *([1.2345] * 16), status],
        ["000737.SZ", "20260914", *([None] * 16), None],
        # B-share bad business values must never reach the status/decimal validator.
        ["201872.SZ", "20260914", *(["invalid"] * 16), True],
    ]


@contextmanager
def source_http(rows, *, first_error=None):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(request)
            fields = request["fields"].split(",")
            indexes = [FIELDS.index(name) for name in fields]
            reply = (
                first_error
                if first_error and len(requests) == 1
                else {
                    "code": 0,
                    "msg": "",
                    "data": {
                        "fields": fields,
                        "items": [[row[i] for i in indexes] for row in rows],
                    },
                }
            )
            body = json.dumps(reply).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_real_http_probe_and_candidate_keep_native_integer_and_null(
    tmp_path, monkeypatch
):
    with (
        source_http(source_rows()) as (url, requests),
        patch.object(
            TushareResource,
            "call",
            side_effect=AssertionError("SDK must not be called"),
        ),
    ):
        monkeypatch.setenv("TUSHARE_BASE_URL", url)
        source = TushareResource(token="isolated")
        assert probe_daily_basic_for_trade_date(
            tushare=source, trade_date=DAY, expected_codes=("000001.SZ",)
        ).ready
        evidence = write_daily_basic_partition(
            lake_root=tmp_path / "lake",
            staging_root=tmp_path / "stage",
            trade_date=DAY,
            run_id="http",
            duckdb_resource=DB(),
            tushare=source,
            load_expected_codes=lambda: ("000001.SZ",),
        )
    assert [r["fields"] for r in requests] == ["ts_code,trade_date", ",".join(FIELDS)]
    assert all(
        r["params"] == {"trade_date": "20260914", "limit": 6000, "offset": 0}
        for r in requests
    )
    assert (
        evidence["fetched_row_count"],
        evidence["source_row_count"],
        evidence["excluded_b_share_row_count"],
        evidence["null_limit_status_count"],
    ) == (3, 2, 1, 1)
    with DB().connect() as connection:
        values = connection.execute(
            "SELECT ts_code,limit_status,typeof(limit_status) FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code",
            [str(raw_daily_basic_path(tmp_path / "lake", DAY))],
        ).fetchall()
    assert values == [("000001.SZ", 0, "INTEGER"), ("000737.SZ", None, "INTEGER")]
    assert type(values[0][1]) is int


@pytest.mark.parametrize("status", [1.0, True, "1", None, 7])
def test_real_json_bad_status_never_promotes(tmp_path, monkeypatch, status):
    with source_http(source_rows(status)) as (url, _):
        monkeypatch.setenv("TUSHARE_BASE_URL", url)
        with pytest.raises(DailyBasicValidationError, match="limit_status"):
            write_daily_basic_partition(
                lake_root=tmp_path / "lake",
                staging_root=tmp_path / "stage",
                trade_date=DAY,
                run_id="invalid-http",
                duckdb_resource=DB(),
                tushare=TushareResource(token="isolated"),
                load_expected_codes=lambda: ("000001.SZ",),
            )
    assert not raw_daily_basic_path(tmp_path / "lake", DAY).exists()


def test_http_retry_is_owned_by_existing_outer_policy(monkeypatch):
    now = [0.0]
    with source_http(
        source_rows(), first_error={"code": 2002, "msg": "请求频率超限"}
    ) as (url, requests):
        monkeypatch.setenv("TUSHARE_BASE_URL", url)
        result = fetch_daily_basic_pages(
            tushare=TushareResource(token="isolated"),
            trade_date=DAY,
            fields=FIELDS[:2],
            consume_page=lambda *_: None,
            clock=lambda: now[0],
            sleep_fn=lambda seconds: now.__setitem__(0, now[0] + seconds),
        )
    assert result.completed and result.request_count == 2 and result.retry_count == 1
    assert len(requests) == 2 and all(r["params"]["offset"] == 0 for r in requests)


def test_http_asset_and_two_partitioned_checks_execute_in_isolation(
    tmp_path, monkeypatch
):
    checks = [
        raw_tushare_daily_basic_file_contract_check,
        raw_tushare_daily_basic_source_coverage_check,
    ]
    with (
        source_http(source_rows()) as (url, requests),
        dg.DagsterInstance.ephemeral() as instance,
        patch(
            "orchestrator.defs.assets.daily_basic.DEFAULT_LAKE_STAGING_ROOT",
            str(tmp_path / "stage"),
        ),
        patch.object(LakeRootResource, "ensure_available_for_run"),
        patch.object(DuckDBResource, "connect", lambda self: DB().connect()),
        patch.object(
            TushareResource, "call", side_effect=AssertionError("no SDK fallback")
        ),
        patch(
            "orchestrator.defs.assets.daily_basic.load_daily_basic_input_codes",
            return_value=("000001.SZ",),
        ),
        patch(
            "orchestrator.defs.checks.daily_basic_checks.load_daily_basic_input_codes",
            return_value=("000001.SZ",),
        ),
    ):
        monkeypatch.setenv("TUSHARE_BASE_URL", url)
        instance.add_dynamic_partitions(cn_a_daily_basic_trade_days.name, [DAY])
        definitions = dg.Definitions(
            assets=[
                dg.AssetSpec(
                    "raw_tushare_stock_daily",
                    partitions_def=dg.DynamicPartitionsDefinition(
                        name="cn_a_stock_trade_days"
                    ),
                ),
                raw_tushare_daily_basic,
            ],
            asset_checks=checks,
            jobs=[raw_tushare_daily_basic_update_job],
            resources={
                "lake_root": LakeRootResource(root_path=str(tmp_path / "lake")),
                "duckdb": DuckDBResource(),
                "tushare": TushareResource(token="isolated"),
            },
        )
        result = definitions.resolve_job_def(
            "raw_tushare_daily_basic_update_job"
        ).execute_in_process(partition_key=DAY, instance=instance)
        assert result.success
        record = daily_basic_materializations(instance, [DAY])[DAY]
        evaluations = result.get_asset_check_evaluations()
        assert len(evaluations) == 2
        for evaluation in evaluations:
            assert evaluation.passed and evaluation.partition == DAY
            assert (
                evaluation.target_materialization_data.storage_id == record.storage_id
            )
            assert (
                evaluation.target_materialization_data.run_id
                == record.event_log_entry.run_id
            )
            assert (
                evaluation.target_materialization_data.timestamp
                == record.event_log_entry.timestamp
            )
        assert len(requests) == 1 and requests[0]["fields"] == ",".join(FIELDS)
        assert (
            record.asset_materialization.metadata["goldenshare/source_row_count"].value
            == 2
        )
        assert (
            record.asset_materialization.metadata[
                "goldenshare/null_limit_status_count"
            ].value
            == 1
        )
