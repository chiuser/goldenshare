"""Isolated seven-plan freeze, shared budgets, lock and process recovery."""

import copy
import csv
import hashlib
import io
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestrator.defs.bootstrap import moneyflow_history_candidates as engine
from orchestrator.defs.bootstrap import moneyflow_history_cohort as cohort
from orchestrator.defs.bootstrap import moneyflow_history_metadata as metadata
from orchestrator.defs.bootstrap import moneyflow_history_source as transport
from orchestrator.defs.bootstrap.moneyflow_history_plan import (
    MoneyflowHistoryDateCount,
    build_moneyflow_history_plan,
    history_schema,
)
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_HISTORY_DATASETS as DATASETS,
)
from orchestrator.defs.run_contracts.moneyflow import MoneyflowContractError

DAY = "2026-09-30"


def row(dataset):
    value = {
        c.name: "0" if c.type != "VARCHAR" else None for c in history_schema(dataset)
    }
    value["trade_date"] = DAY
    if "ts_code" in value:
        value["ts_code"] = "000001.SZ"
    if "name" in value:
        value["name"] = '名称,"逗号\n和换行'
    if dataset == "moneyflow_ind_dc":
        value.update(content_type="行业", ts_code=None)
    return value


def data(dataset, rows):
    fields = [c.name for c in history_schema(dataset)]
    handle = io.StringIO(newline="")
    writer = csv.writer(handle, lineterminator="\n")
    writer.writerow(fields)
    for item in rows:
        writer.writerow([r"\N" if item.get(f) is None else item[f] for f in fields])
    return handle.getvalue().encode()


def plan():
    return build_moneyflow_history_plan(
        "moneyflow_ths", (MoneyflowHistoryDateCount(DAY, 1, 1),), cutoff=DAY
    )


@pytest.fixture(autouse=True)
def space(monkeypatch):
    monkeypatch.setattr(
        cohort.shutil, "disk_usage", lambda _: SimpleNamespace(free=128 * 1024**3)
    )


def snapshot(dataset, rows):
    scoped = dataset == "moneyflow_ind_dc"
    counts = {}
    for item in rows:
        key = (item["trade_date"], item["content_type"] if scoped else "")
        counts[key] = counts.get(key, 0) + 1
    return {
        "dataset": dataset,
        "cutoff": DAY,
        "relation_kind": "r",
        "columns": [
            [
                c.name,
                "date"
                if c.name == "trade_date"
                else "text"
                if c.type == "VARCHAR"
                else c.type.lower().replace("decimal", "numeric"),
            ]
            for c in history_schema(dataset)
        ],
        "facts": [
            {"trade_date": day, "scope": scope, "rows": n, "keys": n, "invalid_keys": 0}
            for (day, scope), n in sorted(counts.items())
        ],
    }


def wire(value):
    return json.dumps(value, ensure_ascii=False).encode().hex().encode() + b"\n"


class Source:
    def __init__(self, rows=None):
        self.rows = rows or {ds: [row(ds)] for ds in DATASETS}
        self.snapshots = {ds: snapshot(ds, self.rows[ds]) for ds in DATASETS}
        self.calls = []
        self.on_metadata = lambda request, number: None
        self.on_copy = lambda request, number: None

    def metadata(self, request, sink, check):
        self.calls.append(("metadata", request.dataset))
        request.sql()
        value = copy.deepcopy(self.snapshots[request.dataset])
        change = self.on_metadata(request, len(self.calls))
        if change is not None:
            value = change
        sink.write(wire(value))
        check()

    def copy(self, request, sink, check):
        self.calls.append(("copy", request.plan.dataset))
        self.on_copy(request, len(self.calls))
        request.sql()
        selected = [
            r
            for r in self.rows[request.plan.dataset]
            if r["trade_date"] in request.plan.units[request.unit_id].dates
        ]
        payload = data(request.plan.dataset, selected)
        for offset in range(0, len(payload), 65536):
            sink.write(payload[offset : offset + 65536])
            check()


def run(tmp_path, source=None, freeze=False, **kwargs):
    return (
        cohort.freeze_moneyflow_history_cohort
        if freeze
        else cohort.build_moneyflow_history_cohort_candidates
    )(
        staging_root=tmp_path,
        operation_id="cohort",
        cutoff=DAY,
        source=source or Source(),
        **kwargs,
    )


def root(tmp_path):
    return tmp_path / "moneyflow/cohort"


def progress(tmp_path):
    return json.loads((root(tmp_path) / "progress.json").read_text())


def write_progress(tmp_path, value):
    (root(tmp_path) / "progress.json").write_text(json.dumps(value))


def test_seven_plans_share_budget_and_replay_without_business_copy(tmp_path):
    source = Source()
    result = run(tmp_path, source)
    assert result["stage"] == "candidates_verified"
    assert result["completed_units"] == result["total_units"] == 7
    assert result["copy_transactions"] == result["connections"] == 28
    assert result["sql_statements"] == 112
    assert result["max_requests"] == 42
    manifest = json.loads((root(tmp_path) / "cohort.json").read_text())
    assert list(manifest["plans"]) == list(DATASETS)
    assert len(list(root(tmp_path).rglob("raw.parquet"))) == 7
    hashes = {
        p: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root(tmp_path).rglob("*.parquet")
    }
    before = list(source.calls)
    replay = run(tmp_path, source)
    assert source.calls[len(before) :] == [("metadata", ds) for ds in DATASETS]
    assert replay["copy_transactions"] == 35
    assert hashes == {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in hashes}
    assert not (tmp_path / "raw").exists()
    assert not (tmp_path / "silver").exists()


@pytest.mark.parametrize("dataset", DATASETS)
def test_metadata_sql_is_fixed_readonly_and_bounded(dataset):
    sql = metadata.moneyflow_history_metadata_sql(dataset, DAY)
    assert sql.startswith("BEGIN READ ONLY;") and sql.endswith("ROLLBACK;\n")
    assert sql.count(";") == 4 and "statement_timeout = '120s'" in sql
    assert "raw_tushare." + dataset in sql
    assert (
        "LIMIT 60001" in sql if dataset == "moneyflow_ind_dc" else "LIMIT 20001" in sql
    )
    assert (
        "SELECT *" not in sql
        and "OFFSET" not in sql
        and "net_amount" not in sql.split("cols AS")[0]
    )
    assert "count(DISTINCT" in sql and "invalid_keys" in sql
    with pytest.raises(MoneyflowContractError):
        metadata.moneyflow_history_metadata_sql(dataset + ";DROP", DAY)
    with pytest.raises(MoneyflowContractError):
        metadata.moneyflow_history_metadata_sql(dataset, "2026-09-30' OR true")


@pytest.mark.parametrize(
    "kind",
    (
        "relation",
        "columns",
        "type",
        "null_date",
        "future",
        "duplicate",
        "keys",
        "invalid",
        "empty",
        "order",
        "scope",
        "oversize",
        "junk",
    ),
)
def test_metadata_contract_rejects_bad_evidence(kind):
    value = snapshot("moneyflow_ind_dc", [row("moneyflow_ind_dc")])
    fact = value["facts"][0]
    if kind == "relation":
        value["relation_kind"] = None
    if kind == "columns":
        value["columns"].pop()
    if kind == "type":
        value["columns"][0][1] = "timestamp without time zone"
    if kind == "null_date":
        fact["trade_date"] = None
    if kind == "future":
        fact["trade_date"] = "2026-10-01"
    if kind == "duplicate":
        value["facts"].append(dict(fact))
    if kind == "keys":
        fact["keys"] = 0
    if kind == "invalid":
        fact["invalid_keys"] = 1
    if kind == "empty":
        value["facts"] = []
    if kind == "scope":
        fact["scope"] = "伪造"
    if kind == "order":
        value["facts"].insert(0, {**fact, "trade_date": "2026-09-29"})
        value["facts"].reverse()
    if kind == "oversize":
        value["facts"] = [fact] * 60001
    payload = wire(value) if kind != "junk" else b"COPY 1\n"
    with pytest.raises(MoneyflowContractError):
        metadata.parse_moneyflow_history_metadata(payload, "moneyflow_ind_dc", DAY)


@pytest.mark.parametrize("phase", ("second", "resume", "partial_resume"))
def test_source_freeze_change_blocks_without_refreshing_plan(tmp_path, phase):
    source = Source()
    if phase == "second":
        source.on_metadata = lambda req, n: (
            {**source.snapshots[req.dataset], "columns": []} if n == 2 else None
        )
    elif phase == "resume":
        run(tmp_path, source, freeze=True)
        source.snapshots["moneyflow"]["facts"][0].update(rows=2, keys=2)
    else:

        def stop(req, n):
            if n == 3:
                raise InterruptedError("history_cancelled")

        source.on_metadata = stop
        with pytest.raises(InterruptedError):
            run(tmp_path, source, freeze=True)
        source.on_metadata = lambda req, n: None
        source.snapshots["moneyflow"]["facts"][0].update(rows=2, keys=2)
    with pytest.raises(MoneyflowContractError):
        run(tmp_path, source, freeze=True)
    assert not list(root(tmp_path).rglob("*.parquet"))


def test_dc_historical_industry_only_and_scope_change_block(tmp_path):
    source = Source()
    # Industry-only history is legitimate. A same-count category replacement isn't.
    run(tmp_path, source, freeze=True)
    source.rows["moneyflow_ind_dc"][0]["content_type"] = "概念"
    with pytest.raises(MoneyflowContractError, match="history_source_scopes_changed"):
        run(tmp_path, source)


@pytest.mark.parametrize("kind", ("requests", "time", "disk"))
def test_shared_limit_blocks_before_dispatch_without_reset(tmp_path, monkeypatch, kind):
    source = Source()
    run(tmp_path, source, freeze=True)
    saved = progress(tmp_path)
    saved["dataset"] = "moneyflow_ths"
    if kind == "requests":
        saved["copy_transactions"] = saved["max_requests"]
        saved["connections"] = saved["max_requests"]
        saved["sql_statements"] = 4 * saved["max_requests"]
    if kind == "time":
        saved["charged_seconds"] = engine.MONEYFLOW_HISTORY_MAX_ELAPSED_SECONDS - 119
    write_progress(tmp_path, saved)
    if kind == "disk":
        with (root(tmp_path) / "disk-budget-sparse.bin").open("wb") as handle:
            handle.truncate(engine.MONEYFLOW_HISTORY_MAX_DISK_BYTES + 1)
    calls = len(source.calls)
    with pytest.raises(
        MoneyflowContractError, match="history_(request|time|disk_bytes)_budget"
    ):
        run(tmp_path, source)
    assert len(source.calls) == calls
    assert progress(tmp_path)["copy_transactions"] == saved["copy_transactions"]


def test_failure_charges_attempt_no_retry_and_next_dataset_preserves_prefix(tmp_path):
    source = Source()

    def stop(req, n):
        if req.plan.dataset == "moneyflow_cnt_ths":
            raise InterruptedError("history_cancelled")

    source.on_copy = stop
    with pytest.raises(InterruptedError):
        run(tmp_path, source)
    saved = progress(tmp_path)
    assert saved["completed_units"] == 1 and saved["copy_transactions"] == 17
    assert saved["closed_units"][0]["dataset"] == "moneyflow"
    source.on_copy = lambda req, n: None
    result = run(tmp_path, source)
    assert result["completed_units"] == 7 and result["copy_transactions"] == 36
    assert source.calls.count(("copy", "moneyflow")) == 2


@pytest.mark.parametrize("kind", ("raw", "checkpoint", "progress"))
def test_closed_prefix_tampering_rejected(tmp_path, kind):
    source = Source()
    run(tmp_path, source)
    if kind == "raw":
        next(root(tmp_path).rglob("raw.parquet")).write_bytes(b"tampered")
    if kind == "checkpoint":
        path = next(root(tmp_path).rglob("checkpoint.json"))
        path.write_text(path.read_text() + " ")
    if kind == "progress":
        saved = progress(tmp_path)
        saved["completed_units"] = 0
        write_progress(tmp_path, saved)
    calls = len(source.calls)
    with pytest.raises(MoneyflowContractError):
        run(tmp_path, source)
    assert all(kind == "metadata" for kind, _ in source.calls[calls:])


def test_namespace_writer_and_single_operation_boundary(tmp_path):
    (tmp_path / "moneyflow").mkdir()
    with engine._writer_lock(tmp_path / "moneyflow"):
        with pytest.raises(MoneyflowContractError, match="history_writer_active"):
            run(tmp_path)
        with pytest.raises(MoneyflowContractError, match="history_writer_active"):
            engine.build_moneyflow_history_unit_candidates(
                plan(),
                0,
                staging_root=tmp_path,
                operation_id="another",
                source=Source(),
            )
    run(tmp_path, freeze=True)
    with pytest.raises(MoneyflowContractError, match="history_cohort_operation"):
        engine.build_moneyflow_history_unit_candidates(
            plan(), 0, staging_root=tmp_path, operation_id="cohort", source=Source()
        )
    legacy = tmp_path / "moneyflow/legacy/moneyflow"
    legacy.mkdir(parents=True)
    with pytest.raises(MoneyflowContractError, match="history_legacy_operation"):
        cohort.freeze_moneyflow_history_cohort(
            staging_root=tmp_path, operation_id="legacy", cutoff=DAY, source=Source()
        )


def test_metadata_adapter_reuses_exact_entry(tmp_path, monkeypatch):
    captured = []
    monkeypatch.setattr(
        transport,
        "_copy_process",
        lambda command, cwd, sink, check: captured.append(command),
    )
    request = metadata.MoneyflowHistoryMetadataRequest(
        "moneyflow", DAY, tmp_path / "source.sql"
    )
    transport.PsqlMoneyflowHistorySource().metadata(request, None, lambda: None)
    assert captured[0][:2] == ["bash", "scripts/psql-remote.sh"]
    assert captured[0][-4:] == ["-q", "-X", "-v", "ON_ERROR_STOP=1"]
    assert request.sql_path.read_text() == request.sql()


def test_six_real_public_fixtures_and_market_null_negative_sample(tmp_path):
    rows = {}
    for dataset in DATASETS:
        if dataset == "moneyflow_mkt_dc":
            item = row(dataset)
            item.update(close_sh=None, net_amount="-123.4567")
            rows[dataset] = [item]
        else:
            rows[dataset] = json.loads(
                (
                    Path(__file__).parent / "fixtures" / (dataset + "_20260930.json")
                ).read_text(),
                parse_float=Decimal,
            )
            for item in rows[dataset]:
                item["trade_date"] = DAY
    source = Source(rows)
    result = run(tmp_path, source)
    assert result["completed_units"] == 7 and result["copy_transactions"] == 28
    for path in root(tmp_path).rglob("checkpoint.json"):
        receipt = json.loads(path.read_text())
        assert receipt["difference_count"] == 0
        assert (
            receipt["source_proof"]["rows"]
            == receipt["verification_proof"]["rows"]
            == receipt["files"][0]["rows"]
        )


def test_real_process_exit_preserves_precharge_and_new_process_resumes(tmp_path):
    script = tmp_path / "process.py"
    script.write_text("""
import json, os, sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, sys.argv[2])
from test_moneyflow_history_cohort import Source, run
from orchestrator.defs.bootstrap import moneyflow_history_cohort as cohort
cohort.shutil.disk_usage=lambda p:SimpleNamespace(free=128*1024**3)
source=Source()
if sys.argv[3]=='exit':
    def die(request, number):
        if request.plan.dataset=='moneyflow_cnt_ths': os._exit(23)
    source.on_copy=die
result=run(Path(sys.argv[1]),source)
print(json.dumps({'result':result,'calls':source.calls}))
""")
    command = [
        sys.executable,
        "-B",
        str(script),
        str(tmp_path),
        str(Path(__file__).parent),
        "exit",
    ]
    first = subprocess.run(command, capture_output=True, timeout=30, check=False)
    assert first.returncode == 23, first.stderr.decode()
    saved = progress(tmp_path)
    assert saved["completed_units"] == 1 and saved["copy_transactions"] == 17
    assert saved["reservation_seconds"] == 120 and saved["charged_seconds"] >= 120
    command[-1] = "resume"
    second = subprocess.run(command, capture_output=True, timeout=30, check=False)
    assert second.returncode == 0, second.stderr.decode()
    output = json.loads(second.stdout)
    assert output["result"]["copy_transactions"] == 36
    assert output["result"]["charged_seconds"] >= 120
    assert ["copy", "moneyflow"] not in output["calls"]
    assert output["result"]["stage"] == "candidates_verified"


def test_large_cohort_ledger_retains_receipt_size_guard(tmp_path):
    run(tmp_path, freeze=True)
    saved = progress(tmp_path)
    saved["audit_notes"] = "x" * (270 * 1024)
    write_progress(tmp_path, saved)
    with pytest.raises(MoneyflowContractError, match="history_checkpoint_file"):
        engine._read_json(root(tmp_path) / "progress.json")
    resumed = run(tmp_path, freeze=True)
    assert resumed["total_units"] == 7
    assert progress(tmp_path)["connections"] == 21
    with pytest.raises(MoneyflowContractError, match="history_cohort_bytes"):
        engine._Store(root(tmp_path), json_limit=100).json(
            root(tmp_path) / "rejected.json", saved
        )
    assert not (root(tmp_path) / "rejected.json").exists()


def test_connection_sql_counters_cannot_diverge(tmp_path):
    source = Source()
    run(tmp_path, source, freeze=True)
    saved = progress(tmp_path)
    saved["connections"] -= 1
    write_progress(tmp_path, saved)
    calls = len(source.calls)
    with pytest.raises(MoneyflowContractError, match="history_checkpoint_progress"):
        run(tmp_path, source)
    assert len(source.calls) == calls
