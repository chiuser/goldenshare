"""THS source contract and actual loopback HTTP/worker/Raw boundary checks."""

import http.client
import json
import logging
import os
import re
import select
import signal
import socket
import ssl
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError

from orchestrator.defs.io.moneyflow_candidates import moneyflow_candidate_connection
from orchestrator.defs.io.moneyflow_daily_raw_writer import insert_daily_moneyflow_page
from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_TUSHARE_MONEYFLOW_THS_SCHEMA,
)
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_MKT_DC_FIELDS,
    MoneyflowContractError,
)
from orchestrator.defs.run_contracts.moneyflow_daily import daily_fields
from orchestrator.defs.source_readiness import moneyflow_request_worker as worker
from orchestrator.defs.source_readiness import moneyflow_transport as parent
from orchestrator.defs.tushare_request_policy import classify_tushare_error
from orchestrator.tushare_download.configuration import ConfigurationSnapshot
from orchestrator.tushare_download.contract_registry import ContractRegistry
from orchestrator.tushare_download.contracts import CONTRACTS
from orchestrator.tushare_download.contracts.moneyflow_ths import MONEYFLOW_THS_CONTRACT
from orchestrator.tushare_download.dataset_transport_mapping import (
    BINDINGS,
    DatasetTransportMapping,
    TransportBinding,
)
from orchestrator.tushare_download.download_errors import DownloadErrorCode as Code
from orchestrator.tushare_download.download_models import (
    AttemptFailure,
    CleanupIssue,
    DownloadMode,
    PagePosition,
    PageRequest,
    RequestCounters,
    SessionCounters,
    UnitCounters,
)
from orchestrator.tushare_download.download_session import SessionControl
from orchestrator.tushare_download.http_transport import HttpProTransport
from orchestrator.tushare_download.source_transport import SystemClock
from orchestrator.tushare_download.unit_memory import UnitMemory
from tests.test_moneyflow_transport import local_sdk_server
from tests.tushare_download.test_tushare_download_http_integration import (
    Reply,
    localhost_source,
)

TOKEN = "ths-isolated-resource-token"
PARAMS = {"trade_date": "20261110", "limit": 2000, "offset": 0}
FIXTURE = Path(__file__).parent / "fixtures/moneyflow_ths_worker_stage05.json"
DATA = json.loads(FIXTURE.read_text(), parse_float=Decimal)
FIELDS = tuple(DATA["fields"])
PROJECTION = ("ts_code", "trade_date")


def source_body(fields, records):
    """Independent scalar JSON fixture; production encoder is not used."""
    def cell(value):
        if type(value) is Decimal:
            assert value.is_finite()
            return format(value, "f")
        return json.dumps(value, ensure_ascii=False, allow_nan=False)

    rows = ["[" + ",".join(cell(record[name]) for name in fields) + "]" for record in records]
    return (
        '{"code":0,"data":{"fields":' + json.dumps(fields)
        + ',"items":[' + ",".join(rows) + "]}}"
    ).encode()


def call_ths(url, *, fields=FIELDS, offset=0, deadline=None, command=None, check_cancel=lambda: None):
    os.environ["TUSHARE_BASE_URL"] = url
    return parent.call_moneyflow_source(
        SimpleNamespace(token=TOKEN), "moneyflow_ths", {**PARAMS, "offset": offset}, fields,
        deadline=time.perf_counter() + 300 if deadline is None else deadline,
        check_cancel=check_cancel, _command=command,
    )


@pytest.fixture
def ths_probe(tmp_path, monkeypatch):
    # The SDK is forbidden and HTTP is constrained to the owned loopback server.
    # These guards observe the real worker; neither replaces its HTTP result.
    script = tmp_path / "ths_worker_probe.py"
    script.write_text('''from time import perf_counter
t1=perf_counter()
import json,runpy,sys
from pathlib import Path
from urllib.parse import urlsplit
from orchestrator.defs.resources import TushareResource
from orchestrator.tushare_download.http_transport import HttpProTransport
def deny_sdk(*args,**kwargs):
    raise AssertionError("SDK must not be called for THS")
TushareResource.call=deny_sdk
original=HttpProTransport.fetch_page
def observed(self,request,config,*args,**kwargs):
    assert urlsplit(config.base_url).hostname=="127.0.0.1"
    t2=perf_counter()
    try:
        return original(self,request,config,*args,**kwargs)
    finally:
        t3=perf_counter()
        if timing_path:
            Path(timing_path).write_text(json.dumps({"t1":t1,"t2":t2,"t3":t3}))
HttpProTransport.fetch_page=observed
timing_path=sys.argv[2]
deadline=sys.argv[1]
sys.argv=["worker",deadline]
runpy.run_module("orchestrator.defs.source_readiness.moneyflow_request_worker",run_name="__main__")
''')
    owned = []
    original_popen = subprocess.Popen

    def launch(*args, **kwargs):
        started = time.perf_counter()
        process = original_popen(*args, **kwargs)
        if args[0][0] == sys.executable and str(script) in args[0]:
            owned.append((process, started))
            assert TOKEN not in repr(args)
            assert not {"DAGSTER_HOME", "TUSHARE_TOKEN", "PGPASSWORD"} & set(kwargs["env"])
        return process

    monkeypatch.setattr(parent.subprocess, "Popen", launch)
    monkeypatch.setenv("TUSHARE_BASE_URL", "http://127.0.0.1:1/unused")
    monkeypatch.setenv("TUSHARE_TOKEN", "different-environment-token")

    def command(deadline, timing_path=None):
        return [sys.executable, "-B", str(script), str(deadline), str(timing_path or "")]

    yield SimpleNamespace(command=command, owned=owned, script=script)
    assert all(process.poll() is not None for process, _ in owned)
    assert all(process.stdin.closed and process.stdout.closed for process, _ in owned)


def test_ths_contract_matches_independent_source_document_and_raw():
    root = Path(__file__).resolve().parents[3]
    doc = (root / DATA["source_document"]).read_text().split("## 输出参数", 1)[1].split("## 接口用法", 1)[0]
    source = re.findall(r"^\| ([a-z_0-9]+) \| (str|float) \| Y \| (.+?) \|$", doc, re.MULTILINE)
    contract = ContractRegistry(CONTRACTS).resolve("moneyflow_ths")
    assert contract is MONEYFLOW_THS_CONTRACT
    assert contract.field_names == tuple(name for name, _, _ in source) == FIELDS
    assert contract.field_names == tuple(c.name for c in RAW_TUSHARE_MONEYFLOW_THS_SCHEMA)
    assert tuple(f.description for f in contract.fields) == tuple(d for _, _, d in source)
    assert tuple(f.nullable for f in contract.fields) == (False, False) + (True,) * 11
    assert tuple(f.source_kind.name for f in contract.fields) == ("STRING",) * 3 + ("NUMBER",) * 10
    assert tuple(m.mode for m in contract.modes) == (DownloadMode.BY_POINT,)
    assert contract.pagination.effective_limit == 2000
    assert contract.pagination.offset_step == 2000
    assert DatasetTransportMapping(BINDINGS).resolve(contract) == TransportBinding("moneyflow_ths", "moneyflow_ths", http_path_rule="base")


@pytest.mark.parametrize("fields", [(), ("trade_date", "ts_code"), ("ts_code",), ("name",), FIELDS + ("extra",)])
def test_ths_worker_rejects_other_field_shapes_before_creation(fields):
    with pytest.raises(MoneyflowContractError, match="source_worker_input"):
        parent.call_moneyflow_source(SimpleNamespace(token=TOKEN), "moneyflow_ths", PARAMS, fields, deadline=time.perf_counter() + 300)


def test_ths_http_null_and_exact_numbers_reach_raw(ths_probe, tmp_path, caplog):
    with (
        localhost_source(lambda *_: Reply(200, source_body(FIELDS, DATA["golden_records"]))) as (url, received),
        caplog.at_level(logging.INFO, logger=parent.__name__),
    ):
        result = call_ths(url, command=ths_probe.command)
    assert len(received) == 1
    assert received[0][1]["token"] == TOKEN
    assert received[0][1]["params"] == PARAMS
    assert received[0][1]["fields"] == ",".join(FIELDS)
    assert result.columns == FIELDS and len(result.rows) == 2
    assert all(result.rows[0][name] is None for name in FIELDS[2:])
    assert result.rows[1]["net_d5_amount"] == "9007199254740993.0001"
    assert result.rows[1]["buy_lg_amount"] == 0
    assert set(result.metadata) == {"api_name", "params", "fields", "row_count", "fetched_at"}
    assert TOKEN not in json.dumps(result.metadata) and TOKEN not in caplog.text
    assert os.environ["TUSHARE_TOKEN"] == "different-environment-token"
    page = tmp_path / "page.json"
    page.write_text(json.dumps(result.rows))
    parquet = tmp_path / "raw.parquet"
    with moneyflow_candidate_connection(tmp_path) as connection:
        insert_daily_moneyflow_page(connection, page, 1, "2026-11-10", dataset="moneyflow_ths", content_type=None)
        connection.execute("COPY daily_round_1 TO ? (FORMAT PARQUET)", [str(parquet)])
        rows = connection.execute("SELECT * FROM read_parquet(?) ORDER BY ts_code", [str(parquet)]).fetchall()
    assert rows[0] == ("20261110", "000001.SZ") + (None,) * 11
    assert rows[1] == (
        "20261110", "000002.SZ", "人工样本", Decimal("-1.2345"), Decimal("10.2301"),
        Decimal("-1234.5678"), Decimal("9007199254740993.0001"), Decimal("0.0000"),
        Decimal("0.0000"), Decimal("12.3456"), Decimal("1.2501"),
        Decimal("-12.3456"), Decimal("-1.2501"),
    )


@pytest.mark.parametrize("cell", DATA["negative_cells"], ids=lambda v: v["raw_json_cell"])
def test_ths_http_and_raw_reject_illegal_numeric_cells(ths_probe, tmp_path, cell):
    body = source_body(FIELDS, DATA["golden_records"]).replace(b"-1234.5678", cell["raw_json_cell"].encode(), 1)
    with localhost_source(lambda *_: Reply(200, body)) as (url, received):
        if cell["expected"] == "reject_nonfinite_json":
            with pytest.raises(ValueError, match="source_or_data_contract"):
                call_ths(url, command=ths_probe.command)
        else:
            result = call_ths(url, command=ths_probe.command)
            path = tmp_path / "bad_page.json"
            path.write_text(json.dumps(result.rows))
            with (
                moneyflow_candidate_connection(tmp_path) as connection,
                pytest.raises(MoneyflowContractError, match="source_numeric_contract"),
            ):
                insert_daily_moneyflow_page(connection, path, 1, "2026-11-10", dataset="moneyflow_ths", content_type=None)
    assert len(received) == 1


@pytest.mark.parametrize("fields,records,reason", [
    (FIELDS[:-1], DATA["golden_records"], "source_row_schema"),
    (FIELDS, [{**DATA["golden_records"][1], "trade_date": "20261111"}], "source_partition_or_key"),
])
def test_http_does_not_fill_missing_fields_or_correct_source_date(ths_probe, tmp_path, fields, records, reason):
    with localhost_source(lambda *_: Reply(200, source_body(fields, records))) as (url, _):
        result = call_ths(url, command=ths_probe.command)
    assert result.columns == fields
    path = tmp_path / "bad_shape.json"
    path.write_text(json.dumps(result.rows))
    with (
        moneyflow_candidate_connection(tmp_path) as connection,
        pytest.raises(MoneyflowContractError, match=reason),
    ):
        insert_daily_moneyflow_page(connection, path, 1, "2026-11-10", dataset="moneyflow_ths", content_type=None)


@pytest.mark.parametrize("code,cause,expected", [
    (Code.CONFIGURATION, None, ("source_or_data_contract", False)),
    (Code.CONTRACT, None, ("source_or_data_contract", False)),
    (Code.INPUT, None, ("source_or_data_contract", False)),
    (Code.PERMISSION_OR_PARAMETER, None, ("source_permission_or_parameter", False)),
    (Code.RATE_LIMIT, None, ("rate_limit", True)),
    (Code.TRANSIENT_SOURCE, None, ("transient", True)),
    (Code.NO_VALID_RESPONSE, None, ("source_response_unclassified", True)),
    (Code.SOURCE_PROTOCOL, "JSONDecodeError", ("source_or_data_contract", False)),
    (Code.UNCLASSIFIED_SOURCE, None, ("non_retryable", False)),
])
def test_ths_error_literal_mapping(code, cause, expected):
    assert classify_tushare_error(worker._ths_source_error(AttemptFailure(code, cause_type=cause))) == expected


@pytest.mark.parametrize("source_error", [
    socket.gaierror(socket.EAI_NONAME, "isolated DNS"), ssl.SSLError("isolated TLS"),
    ssl.SSLCertVerificationError("isolated certificate"), http.client.BadStatusLine("bad"),
    http.client.LineTooLong("header"), TimeoutError("isolated"), ConnectionResetError("isolated"),
])
def test_actual_http_io_errors_keep_legacy_transient_policy(monkeypatch, source_error):
    class BrokenConnection(http.client.HTTPConnection):
        def request(self, *args, **kwargs):
            raise source_error

    monkeypatch.setattr(http.client, "HTTPConnection", BrokenConnection)
    config = ConfigurationSnapshot(token=TOKEN, base_url="http://127.0.0.1:1")
    transport = HttpProTransport(SystemClock())
    transport.prepare(TransportBinding("moneyflow_ths", "moneyflow_ths"), config, MONEYFLOW_THS_CONTRACT)
    request = PageRequest("moneyflow_ths", FIELDS, tuple(PARAMS.items()), PagePosition(0, offset=0), 2000)
    outcome = transport.fetch_page(request, config, UnitMemory(config), SessionControl(None, "test"), RequestCounters(SessionCounters(), UnitCounters()), 1)
    assert outcome.failure is not None
    actual = classify_tushare_error(worker._ths_source_error(outcome.failure))
    assert actual == ("transient", True)
    assert actual == classify_tushare_error(RequestsConnectionError("isolated legacy wrapper"))


@pytest.mark.parametrize("failure,exit_code", [
    (AttemptFailure(Code.CAPACITY), 126), (AttemptFailure(Code.CLEANUP), 126),
    (AttemptFailure(Code.RATE_LIMIT, cleanup_errors=(CleanupIssue("response", "OSError"),)), 126),
    (AttemptFailure(Code.CANCELLED), 125),
])
def test_local_fatal_and_cancel_are_never_source_success(monkeypatch, failure, exit_code):
    def exit_now(code):
        raise SystemExit(code)
    monkeypatch.setattr(worker.os, "_exit", exit_now)
    with pytest.raises(SystemExit) as caught:
        worker._ths_source_error(failure)
    assert caught.value.code == exit_code


@pytest.mark.parametrize("status,body,expected", [
    (403, b"", ("source_permission_or_parameter", False)),
    (429, b"", ("rate_limit", True)),
    (503, b"", ("transient", True)),
    (200, b'{"code":0,"data":null}', ("source_response_unclassified", True)),
    (200, b'{"code":9,"msg":"unknown business","data":null}', ("non_retryable", False)),
    (200, b'not-json', ("source_or_data_contract", False)),
])
def test_real_http_failure_preserves_category_without_internal_retry(ths_probe, status, body, expected):
    with (
        localhost_source(lambda *_: Reply(status, body)) as (url, received),
        pytest.raises(Exception) as caught,
    ):
        call_ths(url, command=ths_probe.command)
    assert classify_tushare_error(caught.value) == expected
    assert len(received) == 1


def test_two_fields_can_use_remaining_budget_but_full_raw_cannot(ths_probe):
    with localhost_source(lambda *_: Reply(200, source_body(PROJECTION, DATA["golden_records"]))) as (url, received):
        result = call_ths(url, fields=PROJECTION, deadline=time.perf_counter() + 8, command=ths_probe.command)
        assert result.columns == PROJECTION
        assert len(received) == 1
    with pytest.raises(MoneyflowContractError, match="request_budget_exceeded"):
        call_ths(url, deadline=time.perf_counter() + 29, command=ths_probe.command)
    with pytest.raises(MoneyflowContractError, match="request_budget_exceeded"):
        call_ths(url, fields=PROJECTION, deadline=time.perf_counter() + 2, command=ths_probe.command)


def test_actual_ths_http_request_is_bounded(ths_probe, record_property):
    with local_sdk_server(slow=True) as (url, received, disconnected):
        started = time.perf_counter()
        with pytest.raises(MoneyflowContractError, match="source_total_deadline|source_worker_failed"):
            call_ths(url, command=ths_probe.command)
        elapsed = time.perf_counter() - started
        assert 27 <= elapsed < 30
        assert len(received) == 1 and disconnected.wait(1)
        record_property("ths_hard_stop_seconds", elapsed)


def test_actual_ths_http_request_is_cancelled(ths_probe):
    with local_sdk_server(slow=True) as (url, received, disconnected):
        def canceled():
            if received:
                raise KeyboardInterrupt("isolated cancellation")
        with pytest.raises(KeyboardInterrupt, match="isolated cancellation"):
            call_ths(url, command=ths_probe.command, check_cancel=canceled)
        assert len(received) == 1 and disconnected.wait(1)


def test_ths_parent_death_closes_inflight_http(ths_probe):
    with local_sdk_server(slow=True) as (url, received, disconnected):
        script = f'''import subprocess,sys
from tests.test_moneyflow_ths_http_worker import call_ths
from orchestrator.defs.source_readiness import moneyflow_transport
original=subprocess.Popen
def launch(*args,**kwargs):
    process=original(*args,**kwargs)
    if args[0][0]==sys.executable: print(process.pid,flush=True)
    return process
moneyflow_transport.subprocess.Popen=launch
call_ths({url!r},command=lambda deadline:[sys.executable,"-B",{str(ths_probe.script)!r},str(deadline),""])
'''
        process = subprocess.Popen(
            [sys.executable, "-B", "-c", script], stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=parent._environment(), start_new_session=True,
        )
        child_pid = None
        try:
            assert select.select([process.stdout], [], [], 10)[0]
            child_pid = int(process.stdout.readline())
            deadline = time.monotonic() + 10
            while not received and time.monotonic() < deadline:
                time.sleep(0.02)
            assert len(received) == 1
            process.kill()
            process.wait(timeout=2)
            assert disconnected.wait(2)
            state = subprocess.run(
                ["/bin/ps", "-o", "stat=", "-p", str(child_pid)],
                capture_output=True, timeout=1, check=False,
            ).stdout.strip()
            assert not state or state.startswith(b"Z"), state
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=2)
            process.stdout.close()
            if child_pid is not None:
                try:
                    if os.getpgid(child_pid) == process.pid:
                        os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


@pytest.mark.parametrize("dataset", [
    "moneyflow", "moneyflow_mkt_dc", "moneyflow_ths", "moneyflow_dc",
    "moneyflow_ind_ths", "moneyflow_cnt_ths", "moneyflow_ind_dc",
])
def test_parent_connection_input_and_full_raw_admission_remain_scoped(monkeypatch, dataset):
    # This isolated echo verifies stdin only, without claiming source integration.
    echo = '''import json,resource,struct,sys
value=json.loads(sys.stdin.buffer.readline())
response={"ok":True,"columns":[],"rows":[],"metadata":value}
body=json.dumps(response).encode()
peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
sys.stdout.buffer.write(struct.pack("!Q",len(body))+body+struct.pack("!Q",peak if sys.platform=="darwin" else peak*1024))
sys.stdout.buffer.flush()
'''
    fields = MONEYFLOW_MKT_DC_FIELDS if dataset == "moneyflow_mkt_dc" else daily_fields(dataset)
    params = {**PARAMS, **({"content_type": "行业"} if dataset == "moneyflow_ind_dc" else {})}
    monkeypatch.delenv("TUSHARE_BASE_URL", raising=False)
    monkeypatch.setenv("TUSHARE_TOKEN", "environment-token-must-not-win")
    result = parent.call_moneyflow_source(
        SimpleNamespace(token=TOKEN), dataset, params, fields,
        deadline=time.perf_counter() + 300, _command=[sys.executable, "-B", "-c", echo],
    )
    expected = {"token", "api_name", "params", "fields", "deadline"}
    if dataset == "moneyflow_ths":
        expected.add("base_url")
        assert result.metadata["base_url"] == "https://api.tushare.pro"
    assert set(result.metadata) == expected
    assert result.metadata["token"] == TOKEN
    assert result.metadata["params"] == params
    assert result.metadata["fields"] == list(fields)
    with pytest.raises(MoneyflowContractError, match="request_budget_exceeded"):
        parent.call_moneyflow_source(
            SimpleNamespace(token=TOKEN), dataset, params, fields,
            deadline=time.perf_counter() + 29,
        )
    if dataset != "moneyflow_ths":
        with pytest.raises(MoneyflowContractError, match="source_worker_input"):
            parent.validate_source_input(dataset, params, PROJECTION)


def test_valid_empty_ths_page_is_distinct_from_no_valid_response(ths_probe):
    with localhost_source(lambda *_: Reply(200, source_body(FIELDS, []))) as (url, received):
        result = call_ths(url, command=ths_probe.command)
    assert result.rows == [] and result.columns == FIELDS
    assert result.metadata["row_count"] == 0 and len(received) == 1


def test_local_memory_error_uses_fatal_exit(monkeypatch):
    def exhausted(*args, **kwargs):
        raise MemoryError
    def exit_now(code):
        raise SystemExit(code)
    monkeypatch.setattr(HttpProTransport, "fetch_page", exhausted)
    monkeypatch.setattr(worker.os, "_exit", exit_now)
    with pytest.raises(SystemExit) as caught:
        worker._call_ths_http({
            "api_name": "moneyflow_ths", "params": PARAMS, "fields": FIELDS,
            "deadline": time.perf_counter() + 28, "token": TOKEN,
            "base_url": "http://127.0.0.1:1",
        })
    assert caught.value.code == 126
