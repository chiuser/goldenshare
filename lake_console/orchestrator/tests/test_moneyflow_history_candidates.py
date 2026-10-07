"""Isolated direct daily candidates, independent reread and durable recovery."""

import csv
import io
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestrator.defs.bootstrap import moneyflow_history_candidates as engine
from orchestrator.defs.bootstrap import moneyflow_history_source as transport
from orchestrator.defs.bootstrap.moneyflow_history_plan import (
    MoneyflowHistoryDateCount as Count,
)
from orchestrator.defs.bootstrap.moneyflow_history_plan import (
    build_moneyflow_history_plan as build,
)
from orchestrator.defs.bootstrap.moneyflow_history_plan import (
    history_schema,
)
from orchestrator.defs.run_contracts.moneyflow import MoneyflowContractError

DAY = "2026-09-30"
DATASETS = (
    "moneyflow",
    "moneyflow_dc",
    "moneyflow_ths",
    "moneyflow_ind_dc",
    "moneyflow_ind_ths",
    "moneyflow_cnt_ths",
    "moneyflow_mkt_dc",
)


@pytest.fixture(autouse=True)
def isolated_free_space(monkeypatch):
    # This fixture controls an admission check, never a formal volume or budget.
    monkeypatch.setattr(
        engine.shutil, "disk_usage", lambda path: SimpleNamespace(free=128 * 1024**3)
    )


def row(dataset, code="000001.SZ", day=DAY):
    result = {
        c.name: ("0" if c.type != "VARCHAR" else None) for c in history_schema(dataset)
    }
    result.update(trade_date=day)
    if "ts_code" in result:
        result["ts_code"] = code
    if "name" in result:
        result["name"] = '名称,"逗号\n和换行'
    if dataset == "moneyflow_ind_dc":
        result.update(content_type="行业", ts_code=None)
    return result


def data(dataset, rows, fields=None):
    fields = fields or [c.name for c in history_schema(dataset)]
    handle = io.StringIO(newline="")
    writer = csv.writer(handle, lineterminator="\n")
    writer.writerow(fields)
    for item in rows:
        writer.writerow(
            [r"\N" if item.get(name) is None else item[name] for name in fields]
        )
    return handle.getvalue().encode()


class Source:
    def __init__(self, *outputs):
        self.outputs = iter(outputs)
        self.requests = []

    def copy(self, request, sink, check):
        self.requests.append(request)
        request.sql()  # Exercise exactly the same whitelist builder as the adapter.
        output = next(self.outputs)
        if isinstance(output, BaseException):
            raise output
        for start in range(0, len(output), 31):
            check()
            sink.write(output[start : start + 31])


def plan(dataset="moneyflow_ths", rows=1):
    return build(dataset, (Count(DAY, rows, rows),), cutoff=DAY)


def run(tmp_path, source, p=None, unit=0, **kwargs):
    return engine.build_moneyflow_history_unit_candidates(
        p or plan(),
        unit,
        staging_root=tmp_path,
        operation_id="isolated",
        source=source,
        **kwargs,
    )


def checkpoint(tmp_path, dataset="moneyflow_ths", unit=0):
    return (
        tmp_path
        / "moneyflow/isolated"
        / dataset
        / DAY
        / "history_candidates"
        / f"unit-{unit:06d}/checkpoint.json"
    )


@pytest.mark.parametrize("dataset", DATASETS)
def test_seven_independent_candidates_verified_and_replay_keeps_files(
    tmp_path, dataset
):
    payload = data(dataset, [row(dataset)])
    source = Source(payload, payload)
    receipt = run(tmp_path, source, plan(dataset))
    assert receipt["stage"] == "verified"
    assert receipt["source_proof"]["rows"] == receipt["verification_proof"]["rows"] == 1
    assert receipt["difference_count"] == 0 and len(source.requests) == 2
    files = {p: p.read_bytes() for p in tmp_path.rglob("*.parquet")}
    assert len(files) == 2
    replay = Source(payload)
    assert run(tmp_path, replay, plan(dataset))["stage"] == "verified"
    assert len(replay.requests) == 1
    assert all(p.read_bytes() == content for p, content in files.items())
    assert not list(tmp_path.rglob("*.csv")) and not list(tmp_path.rglob("*.partial"))
    progress = json.loads(next(tmp_path.rglob("progress.json")).read_text())
    assert progress["completed_units"] == 1 and progress["reservation_seconds"] == 0
    assert progress["copy_transactions"] == 3


@pytest.mark.parametrize("dataset", ("moneyflow_ths", "moneyflow_ind_dc"))
def test_same_keys_changed_value_blocks_and_preserves_candidates(tmp_path, dataset):
    a, b = row(dataset), row(dataset)
    b[next(c.name for c in history_schema(dataset) if c.type.startswith("DECIMAL"))] = (
        "1.25"
    )
    with pytest.raises(MoneyflowContractError, match="history_source_changed"):
        run(tmp_path, Source(data(dataset, [a]), data(dataset, [b])), plan(dataset))
    receipt = json.loads(checkpoint(tmp_path, dataset).read_text())
    assert receipt["stage"] == "blocked" and receipt["difference_count"] == 2
    assert receipt["difference_samples"]
    assert len(list(tmp_path.rglob("*.parquet"))) == 2
    assert not list(tmp_path.rglob("*.csv"))
    with pytest.raises(MoneyflowContractError, match="history_unit_blocked"):
        run(tmp_path, Source(), plan(dataset))


def test_cancel_during_receive_leaves_no_business_copy_and_resumes(tmp_path):
    payload = data("moneyflow_ths", [row("moneyflow_ths")])

    class Cancelled:
        def copy(self, request, sink, check):
            sink.write(payload[:40])
            raise InterruptedError("history_cancelled")

    with pytest.raises(InterruptedError):
        run(tmp_path, Cancelled())
    assert not list(tmp_path.rglob("*.parquet"))
    assert not list(tmp_path.rglob("*.csv"))
    assert run(tmp_path, Source(payload, payload))["stage"] == "verified"


def test_cancel_after_candidates_repeats_only_verification(tmp_path):
    payload = data("moneyflow_ths", [row("moneyflow_ths")])
    with pytest.raises(InterruptedError):
        run(tmp_path, Source(payload, InterruptedError("history_cancelled")))
    before = json.loads(checkpoint(tmp_path).read_text())
    files = {p: p.read_bytes() for p in tmp_path.rglob("*.parquet")}
    source = Source(payload)
    after = run(tmp_path, source)
    assert before["attempt"] == after["attempt"] and before["files"] == after["files"]
    assert len(source.requests) == 1 and all(
        p.read_bytes() == b for p, b in files.items()
    )


@pytest.mark.parametrize("stage", ("candidates_complete", "verified"))
def test_exit_after_daily_manifest_can_resume(tmp_path, monkeypatch, stage):
    payload = data("moneyflow_ths", [row("moneyflow_ths")])
    real_json = engine._Store.json

    class Exit(BaseException):
        pass

    def crash(store, path, value):
        if path.name == "checkpoint.json" and value.get("stage") == stage:
            raise Exit()
        return real_json(store, path, value)

    monkeypatch.setattr(engine._Store, "json", crash)
    with pytest.raises(Exit):
        run(tmp_path, Source(payload, payload))
    monkeypatch.setattr(engine._Store, "json", real_json)
    source = Source(payload)
    assert run(tmp_path, source)["stage"] == "verified" and len(source.requests) == 1
    assert len(list(tmp_path.rglob("*.parquet"))) == 2


def test_handled_exit_releases_time_reservation(tmp_path):
    class Exit(BaseException):
        pass

    with pytest.raises(Exit):
        run(tmp_path, Source(Exit()))
    path = next(tmp_path.rglob("progress.json"))
    assert 0 < json.loads(path.read_text())["charged_seconds"] < 120
    payload = data("moneyflow_ths", [row("moneyflow_ths")])
    run(tmp_path, Source(payload, payload))
    assert json.loads(path.read_text())["reservation_seconds"] == 0


@pytest.mark.parametrize(
    "change,reason",
    (
        ({"trade_date": "20260930"}, "history_copy_date"),
        ({"trade_date": "2026-09-31"}, "history_copy_date"),
        ({"trade_date": "2026-09-29"}, "history_copy_date_counts"),
        ({"ts_code": None}, "history_copy_identity"),
        ({"ts_code": ""}, "history_copy_identity"),
        ({"net_amount": "0.00001"}, "history_copy_numeric:net_amount"),
        ({"net_amount": "NaN"}, "history_copy_numeric:net_amount"),
        ({"net_amount": "True"}, "history_copy_numeric:net_amount"),
        ({"net_amount": "1e99"}, "history_copy_numeric:net_amount"),
    ),
)
def test_reject_invalid_source_with_reason(tmp_path, change, reason):
    item = row("moneyflow_ths")
    item.update(change)
    with pytest.raises(MoneyflowContractError, match=reason):
        run(tmp_path, Source(data("moneyflow_ths", [item])))
    assert not list(tmp_path.rglob("*.parquet"))
    assert json.loads(checkpoint(tmp_path).read_text())["stage"] == "blocked"


@pytest.mark.parametrize(
    "kind,reason",
    (
        ("header", "history_copy_header"),
        ("rows", "history_copy_row_count"),
        ("duplicate", "history_copy_duplicate_key"),
        ("malformed", "history_copy_incomplete"),
        ("integer", "history_copy_numeric:buy_sm_vol"),
    ),
)
def test_schema_counts_duplicate_keys_and_integer_precision(tmp_path, kind, reason):
    rows = [row("moneyflow", "000001.SZ"), row("moneyflow", "000002.SZ")]
    fields = None
    if kind == "header":
        fields = list(reversed([c.name for c in history_schema("moneyflow")]))
    elif kind == "rows":
        rows = rows[:1]
    elif kind == "duplicate":
        rows = [rows[0], rows[0]]
    elif kind == "integer":
        rows[0]["buy_sm_vol"] = "1.1"
    payload = data("moneyflow", rows, fields)
    if kind == "malformed":
        payload += b'"broken\n'
    with pytest.raises(MoneyflowContractError, match=reason):
        run(tmp_path, Source(payload), plan("moneyflow", 2))


def test_wire_order_is_not_a_continuation_contract(tmp_path):
    rows = [row("moneyflow", "000002.SZ"), row("moneyflow", "000001.SZ")]
    assert (
        run(
            tmp_path,
            Source(data("moneyflow", rows), data("moneyflow", rows[::-1])),
            plan("moneyflow", 2),
        )["stage"]
        == "verified"
    )


def test_negative_null_and_quoted_null_text_preserved(tmp_path):
    import duckdb

    item = row("moneyflow_ths", code="920000.BJ")
    item.update(name=None, net_amount="-10.1250", latest=None)
    payload = data("moneyflow_ths", [item])
    run(tmp_path, Source(payload, payload))
    with duckdb.connect() as db:
        value = db.execute(
            "SELECT ts_code,name,net_amount,latest FROM read_parquet(?)",
            [str(next(tmp_path.rglob("raw.parquet")))],
        ).fetchone()
    assert (
        str(value[2]) == "-10.1250"
        and value[0:2] == ("920000.BJ", None)
        and value[3] is None
    )
    other = tmp_path / "quoted"
    item = row("moneyflow_ind_dc")
    item["name"] = r"\N"
    # The only real NULL is ts_code; COPY quotes the real name equal to NULL marker.
    payload = data("moneyflow_ind_dc", [item]).replace(b",\\N,0,", b',"\\N",0,', 1)
    run(other, Source(payload, payload), plan("moneyflow_ind_dc"))
    with duckdb.connect() as db:
        assert db.execute(
            "SELECT name,ts_code FROM read_parquet(?)",
            [str(next(other.rglob("raw.parquet")))],
        ).fetchone() == (r"\N", None)


def test_multiple_explicit_dates_generated_without_spool(tmp_path):
    dates = ("2026-09-29", DAY)
    p = build("moneyflow", tuple(Count(d, 1, 1) for d in dates), cutoff=DAY)
    payload = data("moneyflow", [row("moneyflow", day=d) for d in dates])
    result = run(tmp_path, Source(payload, payload), p)
    assert [f["trade_date"] for f in result["files"]] == list(dates)
    assert len(list(tmp_path.rglob("*.parquet"))) == 4
    assert not list(tmp_path.rglob("*.csv"))


@pytest.mark.parametrize(
    "kind", ("file", "scope", "attempt", "schema", "symlink", "legacy_key")
)
def test_resume_checks_physical_files_and_scope(tmp_path, kind):
    payload = data("moneyflow_ths", [row("moneyflow_ths")])
    run(tmp_path, Source(payload, payload))
    path = checkpoint(tmp_path)
    receipt = json.loads(path.read_text())
    if kind == "file":
        next(tmp_path.rglob("raw.parquet")).write_bytes(b"changed")
    elif kind == "scope":
        receipt["dates"] = ["2026-09-29"]
    elif kind == "attempt":
        receipt["attempt"] = "../../elsewhere"
    elif kind == "schema":
        receipt["schema_hash"] = "0" * 64
    elif kind == "legacy_key":
        receipt["after_key"] = ["code", DAY]
    else:
        (path.parent / "poison").symlink_to(tmp_path)
    path.write_text(json.dumps(receipt))
    source = Source()
    with pytest.raises(MoneyflowContractError):
        run(tmp_path, source)
    assert not source.requests


def test_legacy_operation_and_changed_plan_rejected_before_copy(tmp_path):
    legacy = checkpoint(tmp_path).parents[1].parent / "history_export"
    legacy.mkdir(parents=True)
    source = Source()
    with pytest.raises(MoneyflowContractError, match="history_legacy_operation"):
        run(tmp_path, source)
    assert not source.requests
    other = tmp_path / "new"
    payload = data("moneyflow_ths", [row("moneyflow_ths")])
    run(other, Source(payload, payload))
    with pytest.raises(MoneyflowContractError, match="history_plan_changed"):
        run(other, source, plan(rows=2))


@pytest.mark.parametrize("kind", ("buffer", "disk", "time", "free", "rss", "chunk"))
def test_resource_budgets_fail_closed(tmp_path, monkeypatch, kind):
    if kind == "buffer":
        monkeypatch.setattr(engine, "MONEYFLOW_HISTORY_MAX_BUFFER_BYTES", 100)
    elif kind == "disk":
        monkeypatch.setattr(engine, "MONEYFLOW_HISTORY_MAX_DISK_BYTES", 20)
    elif kind == "time":
        monkeypatch.setattr(engine, "MONEYFLOW_HISTORY_MAX_ELAPSED_SECONDS", 100)
    elif kind == "free":
        monkeypatch.setattr(
            engine.shutil, "disk_usage", lambda _: SimpleNamespace(free=0)
        )
    elif kind == "rss":
        monkeypatch.setattr(
            engine,
            "assert_moneyflow_memory_budget",
            lambda: (_ for _ in ()).throw(
                MoneyflowContractError("memory_budget_exceeded")
            ),
        )
    else:
        monkeypatch.setattr(engine, "MONEYFLOW_HISTORY_STREAM_BYTES", 10)
    payload = data("moneyflow_ths", [row("moneyflow_ths")])
    with pytest.raises(MoneyflowContractError):
        run(tmp_path, Source(payload, payload))
    assert not list(tmp_path.rglob("*.parquet"))


def test_timeout_retry_and_before_start_cancel(tmp_path):
    class Clock:
        now = 0

        def __call__(self):
            return self.now

    clock = Clock()

    class Slow:
        def copy(self, request, sink, check):
            clock.now = 121
            check()

    with pytest.raises(MoneyflowContractError, match="history_unit_timeout"):
        run(tmp_path, Slow(), clock=clock)
    payload = data("moneyflow_ths", [row("moneyflow_ths")])
    assert run(tmp_path, Source(payload, payload), clock=clock)["stage"] == "verified"
    other = tmp_path / "cancelled"
    with pytest.raises(InterruptedError):
        run(other, Source(), cancel=lambda: True)
    assert not other.exists()


def test_writer_lock_rejects_second_owner(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    with (
        engine._writer_lock(tmp_path),
        pytest.raises(MoneyflowContractError, match="history_writer_active"),
        engine._writer_lock(tmp_path),
    ):
        pass


def test_psql_adapter_uses_existing_entry_and_hides_stderr(tmp_path, monkeypatch):
    request = transport.MoneyflowHistoryCopyRequest(plan(), 0, tmp_path / "source.sql")
    captured = []
    monkeypatch.setattr(
        transport,
        "_copy_process",
        lambda command, cwd, sink, check: captured.append((command, cwd)),
    )
    transport.PsqlMoneyflowHistorySource().copy(request, io.BytesIO(), lambda: None)
    command, cwd = captured[0]
    assert command[:2] == ["bash", "scripts/psql-remote.sh"]
    assert command[-5:] == ["--", "-q", "-X", "-v", "ON_ERROR_STOP=1"]
    assert cwd == Path(__file__).resolve().parents[3]
    assert "BEGIN READ ONLY" in request.sql_path.read_text()
    assert command[command.index("--env-file") + 1] == str(cwd / ".env.web.local")
    assert not any("postgres://" in arg for arg in command)


def test_transport_drains_large_stderr_without_full_output_buffer():
    sink = io.BytesIO()
    command = [
        sys.executable,
        "-B",
        "-c",
        "import os;os.write(2,b'x'*2000000);os.write(1,b'csv data')",
    ]
    transport._copy_process(command, Path("/private/tmp"), sink, lambda: None)
    assert sink.getvalue() == b"csv data"


def test_transport_cancel_stops_entire_child_group(tmp_path):
    ready = tmp_path / "child.ready"
    stopped = tmp_path / "child.stopped"
    child_code = "import signal,sys,time;from pathlib import Path;signal.signal(signal.SIGTERM,lambda s,f:(Path(sys.argv[2]).write_text('terminated'),sys.exit(0)));Path(sys.argv[1]).write_text('ready');time.sleep(30)"
    parent_code = "import subprocess,sys,time;from pathlib import Path;p=subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2],sys.argv[3]]);time.sleep(30)"
    command = [
        sys.executable,
        "-B",
        "-c",
        parent_code,
        child_code,
        str(ready),
        str(stopped),
    ]
    started = time.monotonic()

    def cancel():
        if ready.exists():
            raise InterruptedError("cancelled")
        assert time.monotonic() - started < 3

    with pytest.raises(InterruptedError):
        transport._copy_process(command, Path("/private/tmp"), io.BytesIO(), cancel)
    deadline = time.monotonic() + 1
    while not stopped.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ready.exists() and stopped.read_text() == "terminated"
    assert time.monotonic() - started < 4


@pytest.mark.parametrize(
    "path",
    (
        "/Volumes/datasource/data_lake",
        "/Volumes/datasource/goldenshare-tushare-lake",
        "/Volumes/other",
        "relative",
    ),
)
def test_formal_retired_other_volume_relative_paths_rejected_without_source(path):
    source = Source()
    with pytest.raises(MoneyflowContractError):
        run(Path(path), source)
    assert not source.requests


@pytest.mark.parametrize("dataset", DATASETS[:-1])
def test_public_real_value_samples_read_back_without_reject(tmp_path, dataset):
    from decimal import Decimal

    items = json.loads(
        (Path(__file__).parent / "fixtures" / (dataset + "_20260930.json")).read_text(),
        parse_float=Decimal,
    )
    for item in items:
        item["trade_date"] = DAY
    payload = data(dataset, items)
    result = run(tmp_path, Source(payload, payload), plan(dataset, len(items)))
    assert (
        result["source_proof"]["rows"]
        == result["verification_proof"]["rows"]
        == result["files"][0]["rows"]
        == len(items)
    )
    assert result["difference_count"] == 0


@pytest.mark.parametrize("stage", ("receiving", "manifest"))
def test_actual_process_exit_and_fresh_process_resume(tmp_path, stage):
    payload = data("moneyflow_ths", [row("moneyflow_ths")])
    script = """
import io,json,os,sys
from pathlib import Path
from types import SimpleNamespace
from orchestrator.defs.bootstrap import moneyflow_history_candidates as engine
from orchestrator.defs.bootstrap.moneyflow_history_plan import MoneyflowHistoryDateCount,build_moneyflow_history_plan
root=Path(sys.argv[1]);mode=sys.argv[2];payload=bytes.fromhex(sys.argv[3]);calls=[]
engine.shutil.disk_usage=lambda _:SimpleNamespace(free=128*1024**3)
plan=build_moneyflow_history_plan('moneyflow_ths',(MoneyflowHistoryDateCount('2026-09-30',1,1),),cutoff='2026-09-30')
class Source:
 def copy(self,request,sink,check):
  calls.append(1)
  sink.write(payload[:40])
  if mode=='receiving':os._exit(37)
  sink.write(payload[40:])
real=engine._Store.json
def journal(self,path,value):
 if mode=='manifest' and path.name=='checkpoint.json' and value.get('stage')=='candidates_complete':os._exit(38)
 return real(self,path,value)
engine._Store.json=journal
result=engine.build_moneyflow_history_unit_candidates(plan,0,staging_root=root,operation_id='isolated',source=Source())
print(json.dumps({'stage':result['stage'],'copies':len(calls)}))
"""
    args = [sys.executable, "-B", "-c", script, str(tmp_path), stage, payload.hex()]
    crashed = subprocess.run(
        args, capture_output=True, text=True, check=False, timeout=20
    )
    assert crashed.returncode == (37 if stage == "receiving" else 38), crashed.stderr
    progress = json.loads(next(tmp_path.rglob("progress.json")).read_text())
    assert progress["charged_seconds"] >= (120 if stage == "receiving" else 0)
    charged = progress["charged_seconds"]
    args[-2] = "resume"
    resumed = subprocess.run(
        args, capture_output=True, text=True, check=False, timeout=20
    )
    assert resumed.returncode == 0, resumed.stderr
    assert json.loads(resumed.stdout) == {
        "stage": "verified",
        "copies": 2 if stage == "receiving" else 1,
    }
    assert len(list(tmp_path.rglob("*.parquet"))) == 2
    assert not list(tmp_path.rglob("*.csv"))
    assert (
        json.loads(next(tmp_path.rglob("progress.json")).read_text())["charged_seconds"]
        >= charged
    )


@pytest.mark.parametrize("rows", (100000, 100001))
def test_single_day_row_boundary_and_overflow_sentinel(tmp_path, rows):
    # The extra row is real, not a patched planner limit or mocked count query.
    template = row("moneyflow")
    items = [{**template, "ts_code": f"{number:06d}.SZ"} for number in range(rows)]
    payload = data("moneyflow", items)
    if rows == 100001:
        with pytest.raises(MoneyflowContractError, match="history_rows_budget"):
            run(tmp_path, Source(payload), plan("moneyflow", 100000))
        assert not list(tmp_path.rglob("*.parquet"))
    else:
        receipt = run(tmp_path, Source(payload, payload), plan("moneyflow", rows))
        assert receipt["stage"] == "verified" and receipt["files"][0]["rows"] == rows
        assert len(list(tmp_path.rglob("*.parquet"))) == 2


def test_native_columnar_work_interrupts_on_cancel(tmp_path):
    from orchestrator.defs.bootstrap.moneyflow_history_receive import (
        history_candidate_connection,
    )

    started = time.monotonic()

    def check():
        if time.monotonic() - started > 0.15:
            raise InterruptedError("cancelled")

    with (
        pytest.raises(InterruptedError),
        history_candidate_connection(tmp_path, check) as db,
    ):
        db.execute("SELECT sum(i::HUGEINT * i) FROM range(10000000000) t(i)")
    assert time.monotonic() - started < 3


def test_later_date_unit_requires_actual_verified_predecessor(tmp_path):
    p = build("moneyflow", (Count("2025-12-31", 1, 1), Count(DAY, 1, 1)), cutoff=DAY)
    source = Source()
    with pytest.raises(MoneyflowContractError, match="history_checkpoint_file"):
        run(tmp_path, source, p, unit=1)
    assert not source.requests
    first = data("moneyflow", [row("moneyflow", day="2025-12-31")])
    second = data("moneyflow", [row("moneyflow")])
    run(tmp_path, Source(first, first), p)
    assert run(tmp_path, Source(second, second), p, unit=1)["stage"] == "verified"
    assert (
        json.loads(next(tmp_path.rglob("progress.json")).read_text())["completed_units"]
        == 2
    )
