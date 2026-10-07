"""Isolated streaming, CSV contracts and durable source-unit recovery acceptance."""

import csv
import io
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestrator.defs.bootstrap import moneyflow_history_export as engine
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
    return engine.export_moneyflow_history_unit(
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
        / "history_export"
        / f"unit-{unit:06d}/checkpoint.json"
    )


@pytest.mark.parametrize("dataset", DATASETS)
def test_seven_independent_exports_verified_and_idempotent(tmp_path, dataset):
    payload = data(dataset, [row(dataset)])
    source = Source(payload, payload)
    receipt = run(tmp_path, source, plan(dataset))
    assert receipt["stage"] == "verified"
    assert receipt["export"] == receipt["verification"]
    assert receipt["export"]["rows"] == 1
    assert len(source.requests) == 2
    assert receipt["export_attempt"] != receipt["verification_attempt"]
    assert run(tmp_path, Source(), plan(dataset)) == receipt
    assert len(list(tmp_path.rglob("source.csv"))) == 2
    progress = json.loads(next(tmp_path.rglob("progress.json")).read_text())
    assert progress["completed_units"] == 1 and progress["reservation_seconds"] == 0
    assert progress["charged_seconds"] > 0


@pytest.mark.parametrize("dataset", ("moneyflow_ths", "moneyflow_ind_dc"))
def test_source_changed_same_keys_same_rows_blocks_and_preserves_both(
    tmp_path, dataset
):
    a, b = row(dataset), row(dataset)
    b[next(c.name for c in history_schema(dataset) if c.type.startswith("DECIMAL"))] = (
        "1.25"
    )
    with pytest.raises(MoneyflowContractError, match="history_source_changed"):
        run(tmp_path, Source(data(dataset, [a]), data(dataset, [b])), plan(dataset))
    receipt = json.loads(checkpoint(tmp_path, dataset).read_text())
    assert receipt["stage"] == "blocked"
    assert receipt["export"]["sha256"] != receipt["verification"]["sha256"]
    assert len(list(tmp_path.rglob("source.csv"))) == 2
    with pytest.raises(MoneyflowContractError, match="history_unit_blocked"):
        run(tmp_path, Source(), plan(dataset))


def test_cancelled_partial_preserved_and_new_attempt_resumes(tmp_path):
    payload = data("moneyflow_ths", [row("moneyflow_ths")])

    class Cancelled:
        def copy(self, request, sink, check):
            sink.write(payload[:40])
            raise InterruptedError("history_cancelled")

    with pytest.raises(InterruptedError):
        run(tmp_path, Cancelled())
    partial = next(tmp_path.rglob("source.partial"))
    original = partial.read_bytes()
    receipt = run(tmp_path, Source(payload, payload))
    assert receipt["stage"] == "verified" and partial.read_bytes() == original
    assert len(list(tmp_path.rglob("source.partial"))) == 1


def test_cancel_after_export_keeps_export_and_only_repeats_verification(tmp_path):
    payload = data("moneyflow_ths", [row("moneyflow_ths")])
    with pytest.raises(InterruptedError):
        run(tmp_path, Source(payload, InterruptedError("history_cancelled")))
    before = json.loads(checkpoint(tmp_path).read_text())
    source = Source(payload)
    after = run(tmp_path, source)
    assert before["export"] == after["export"]
    assert before["export_attempt"] == after["export_attempt"]
    assert len(source.requests) == 1


@pytest.mark.parametrize("phase", ("exported", "verified"))
def test_exit_between_csv_rename_and_checkpoint_is_adopted(
    tmp_path, monkeypatch, phase
):
    payload = data("moneyflow_ths", [row("moneyflow_ths")])
    real_json = engine._Store.json

    class Exit(BaseException):
        pass

    def fail_after_rename(store, path, value):
        if path.name == "checkpoint.json" and value.get("stage") == phase:
            raise Exit()
        return real_json(store, path, value)

    monkeypatch.setattr(engine._Store, "json", fail_after_rename)
    with pytest.raises(Exit):
        run(tmp_path, Source(payload, payload))
    monkeypatch.setattr(engine._Store, "json", real_json)
    source = Source(payload) if phase == "exported" else Source()
    result = run(tmp_path, source)
    assert result["stage"] == "verified"
    assert len(source.requests) == (phase == "exported")
    assert len(list(tmp_path.rglob("source.csv"))) == 2


def test_unclean_exit_keeps_time_reservation(tmp_path):
    payload = data("moneyflow_ths", [row("moneyflow_ths")])

    class Exit(BaseException):
        pass

    with pytest.raises(Exit):
        run(tmp_path, Source(Exit()))
    progress = next(tmp_path.rglob("progress.json"))
    assert json.loads(progress.read_text())["charged_seconds"] == 120
    run(tmp_path, Source(payload, payload))
    assert json.loads(progress.read_text())["charged_seconds"] >= 120


@pytest.mark.parametrize(
    "change,reason",
    (
        ({"trade_date": "20260930"}, "history_csv_date"),
        ({"trade_date": "2026-09-31"}, "history_csv_date"),
        ({"trade_date": "2026-09-29"}, "history_csv_date_counts"),
        ({"ts_code": None}, "history_csv_identity"),
        ({"ts_code": ""}, "history_csv_identity"),
        ({"net_amount": "0.00001"}, "history_csv_numeric:net_amount"),
        ({"net_amount": "NaN"}, "history_csv_numeric:net_amount"),
        ({"net_amount": "True"}, "history_csv_numeric:net_amount"),
        ({"net_amount": "1e99"}, "history_csv_numeric:net_amount"),
    ),
)
def test_invalid_csv_rejected_with_reason(tmp_path, change, reason):
    item = row("moneyflow_ths")
    item.update(change)
    with pytest.raises(MoneyflowContractError, match=reason):
        run(tmp_path, Source(data("moneyflow_ths", [item])))
    assert not list(tmp_path.rglob("source.csv"))
    assert json.loads(checkpoint(tmp_path).read_text())["stage"] == "blocked"


@pytest.mark.parametrize(
    "kind", ("header", "rows", "duplicate", "malformed", "key_order", "integer")
)
def test_schema_counts_keys_and_integer_precision(tmp_path, kind):
    dataset = "moneyflow"
    a, b = row(dataset, "000001.SZ"), row(dataset, "000002.SZ")
    rows = [a, b]
    fields = None
    reason = "history_csv_"
    if kind == "header":
        fields = list(reversed([c.name for c in history_schema(dataset)]))
    elif kind == "rows":
        rows = [a]
    elif kind == "duplicate":
        rows = [a, a]
    elif kind == "key_order":
        rows = [b, a]
    elif kind == "integer":
        a["buy_sm_vol"] = "1.1"
    payload = data(dataset, rows, fields)
    if kind == "malformed":
        payload += b'"broken\n'
    with pytest.raises(MoneyflowContractError, match=reason):
        run(tmp_path, Source(payload), plan(dataset, 2))


def test_low_coverage_and_early_industry_no_daily_scope_requirement(tmp_path):
    rows = [row("moneyflow_ind_dc"), row("moneyflow_ind_dc")]
    rows[1]["name"] = "另一行业"
    payload = data("moneyflow_ind_dc", rows)
    assert (
        run(tmp_path, Source(payload, payload), plan("moneyflow_ind_dc", 2))["export"][
            "rows"
        ]
        == 2
    )
    assert rows[0]["ts_code"] is None


def test_daily_source_does_not_crop_null_or_negative_values(tmp_path):
    item = row("moneyflow_ths", code="920000.BJ")
    item.update(
        name=None, net_amount="-10.1250", latest=None, net_d5_amount="-999.0000"
    )
    payload = data("moneyflow_ths", [item])
    run(tmp_path, Source(payload, payload))
    assert next(tmp_path.rglob("source.csv")).read_bytes() == payload


def test_quoted_null_marker_is_a_real_dc_board_name(tmp_path):
    item = row("moneyflow_ind_dc")
    item["name"] = r"\N"
    payload = data("moneyflow_ind_dc", [item])
    # COPY quotes a real string equal to its null marker; NULL itself is unquoted.
    fields = [c.name for c in history_schema("moneyflow_ind_dc")]
    values = [item[name] for name in fields]
    handle = io.StringIO(newline="")
    writer = csv.writer(handle, lineterminator="\n", quoting=csv.QUOTE_ALL)
    writer.writerow(fields)
    writer.writerow([r"\N" if value is None else value for value in values])
    payload = handle.getvalue().encode().replace(b',"\\N",', b',\\N,', 1)
    assert (
        run(tmp_path, Source(payload, payload), plan("moneyflow_ind_dc"))["stage"]
        == "verified"
    )


def test_initial_space_admission_is_not_reapplied_to_completed_operation(
    tmp_path, monkeypatch
):
    payload = data("moneyflow_ths", [row("moneyflow_ths")])
    run(tmp_path, Source(payload, payload))
    monkeypatch.setattr(
        engine.shutil, "disk_usage", lambda _: SimpleNamespace(free=40 * 1024**3)
    )
    assert run(tmp_path, Source())["stage"] == "verified"


def test_keyset_continuation_comes_from_verified_predecessor_csv(tmp_path, monkeypatch):
    import orchestrator.defs.bootstrap.moneyflow_history_plan as planner

    # Tighten the unit size in an isolated planner; never relax the real limit.
    monkeypatch.setattr(planner, "MONEYFLOW_HISTORY_MAX_ROWS_PER_UNIT", 2)
    p = build(
        "moneyflow",
        (Count("2026-09-28", 1, 1), Count("2026-09-29", 1, 1), Count(DAY, 1, 1)),
        cutoff=DAY,
    )
    first = data(
        "moneyflow",
        [
            row("moneyflow", "000001.SZ", "2026-09-28"),
            row("moneyflow", "000002.SZ", "2026-09-29"),
        ],
    )
    second = data("moneyflow", [row("moneyflow", "000003.SZ")])
    source = Source(first, first, second, second)
    run(tmp_path, source, p)
    receipt = run(tmp_path, source, p, unit=1)
    assert receipt["after_key"] == ["000002.SZ", "2026-09-29"]
    assert source.requests[1].through_key == ("000002.SZ", "2026-09-29")
    assert source.requests[2].after_key == ("000002.SZ", "2026-09-29")
    assert source.requests[3].through_key == ("000003.SZ", DAY)
    assert receipt["stage"] == "verified"


@pytest.mark.parametrize("stage", ("partial", "rename"))
def test_real_process_exit_and_fresh_process_resume(tmp_path, stage):
    payload = data("moneyflow_ths", [row("moneyflow_ths")])
    fixture = tmp_path / "copy-fixture.csv"
    fixture.write_bytes(payload)
    script = """
import json, os, sys
from pathlib import Path
from types import SimpleNamespace
from orchestrator.defs.bootstrap import moneyflow_history_export as engine
from orchestrator.defs.bootstrap.moneyflow_history_plan import MoneyflowHistoryDateCount, build_moneyflow_history_plan
root=Path(sys.argv[1]);mode=sys.argv[2]
engine.shutil.disk_usage=lambda _:SimpleNamespace(free=128*1024**3)
plan=build_moneyflow_history_plan('moneyflow_ths',(MoneyflowHistoryDateCount('2026-09-30',1,1),),cutoff='2026-09-30')
calls=[]
class Source:
 def copy(self,request,sink,check):
  calls.append(request.unit_id)
  with (root/'copy-fixture.csv').open('rb') as handle:
   for block in iter(lambda:handle.read(64*1024),b''):
    sink.write(block)
    if mode=='partial':os._exit(37)
real=engine._Store.json
def journal(self,path,value):
 if mode=='rename' and path.name=='checkpoint.json' and value.get('stage')=='exported':os._exit(38)
 return real(self,path,value)
engine._Store.json=journal
result=engine.export_moneyflow_history_unit(plan,0,staging_root=root,operation_id='isolated',source=Source())
print(json.dumps({'stage':result['stage'],'copies':len(calls)}))
"""
    crashed = subprocess.run(
        [sys.executable, "-B", "-c", script, str(tmp_path), stage],
        capture_output=True,
        text=True,
        check=False,
    )
    assert crashed.returncode == (37 if stage == "partial" else 38), crashed.stderr
    resumed = subprocess.run(
        [sys.executable, "-B", "-c", script, str(tmp_path), "resume"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert resumed.returncode == 0, resumed.stderr
    assert json.loads(resumed.stdout) == {
        "stage": "verified",
        "copies": 2 if stage == "partial" else 1,
    }
    assert len(list(tmp_path.rglob("source.csv"))) == 2


@pytest.mark.parametrize(
    "kind", ("csv", "proof", "scope", "attempt", "schema", "symlink")
)
def test_resume_detects_modified_files_proof_or_scope(tmp_path, kind):
    payload = data("moneyflow", [row("moneyflow")])
    p = plan("moneyflow")
    run(tmp_path, Source(payload, payload), p)
    path = checkpoint(tmp_path, "moneyflow")
    receipt = json.loads(path.read_text())
    if kind == "csv":
        target = path.parent / receipt["export_attempt"] / "source.csv"
        target.write_bytes(target.read_bytes().replace(b"000001", b"000002"))
    elif kind == "proof":
        receipt["export"]["last_key"][0] = "999999.SZ"
    elif kind == "scope":
        receipt["dates"] = ["2026-09-29"]
    elif kind == "attempt":
        receipt["export_attempt"] = "../../elsewhere"
    elif kind == "schema":
        receipt["schema_hash"] = "0" * 64
    elif kind == "symlink":
        extra = path.parent / "poison"
        extra.symlink_to(tmp_path)
    path.write_text(json.dumps(receipt))
    with pytest.raises(MoneyflowContractError):
        run(tmp_path, Source(), p)


def test_changed_plan_blocks_before_source_call(tmp_path):
    payload = data("moneyflow_ths", [row("moneyflow_ths")])
    run(tmp_path, Source(payload, payload))
    source = Source()
    with pytest.raises(MoneyflowContractError):
        run(tmp_path, source, plan(rows=2))
    assert source.requests == []


@pytest.mark.parametrize("kind", ("csv", "source", "time", "free", "rss", "chunk"))
def test_all_resource_budgets_fail_closed(tmp_path, monkeypatch, kind):
    payload = data("moneyflow_ths", [row("moneyflow_ths")])
    source = Source(payload, payload)
    if kind == "csv":
        monkeypatch.setattr(engine, "MONEYFLOW_HISTORY_MAX_CSV_BYTES", 100)
    elif kind == "source":
        monkeypatch.setattr(engine, "MONEYFLOW_HISTORY_MAX_SOURCE_BYTES", 20)
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
    elif kind == "chunk":
        monkeypatch.setattr(engine, "MONEYFLOW_HISTORY_STREAM_BYTES", 10)
    with pytest.raises(MoneyflowContractError):
        run(tmp_path, source)
    assert not list(tmp_path.rglob("source.csv"))


def test_unit_deadline_and_timeout_can_retry(tmp_path):
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


def test_no_later_unit_claimed_and_before_start_cancel_has_no_output(tmp_path):
    p = build("moneyflow_dc", (Count("2025-12-31", 1, 1), Count(DAY, 1, 1)), cutoff=DAY)
    with pytest.raises(MoneyflowContractError, match="history_checkpoint_file"):
        run(tmp_path, Source(), p, unit=1)
    assert not list(tmp_path.rglob("source.partial"))
    other = tmp_path / "cancelled"
    with pytest.raises(InterruptedError):
        run(other, Source(), cancel=lambda: True)
    assert not other.exists()


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
