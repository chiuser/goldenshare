"""Exact-date scope in the real bootstrap chain, using isolated source stand-ins."""

import csv
import hashlib
import io
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from orchestrator.defs.bootstrap import moneyflow_history_candidates as engine
from orchestrator.defs.bootstrap import moneyflow_history_cohort as cohort
from orchestrator.defs.bootstrap import moneyflow_history_metadata as metadata
from orchestrator.defs.bootstrap import moneyflow_history_promote as promote
from orchestrator.defs.bootstrap.moneyflow_history_plan import history_schema
from orchestrator.defs.run_contracts.moneyflow import (
    MONEYFLOW_HISTORY_DATASETS as DATASETS,
)
from orchestrator.defs.run_contracts.moneyflow import MoneyflowContractError

CUTOFF = "2026-09-30"
DATES = ("2024-12-19", CUTOFF)
OUTSIDE = "2025-06-30"
# Hashes of the seven full-scope SQL statements actually executed in §23.
FULL_SCOPE_SQL_SHA256 = {
    "moneyflow": "7f59fe4c38123efa5f660bfad17d952e9d9e1e589adba6b2ba9aff1c6df579ad",
    "moneyflow_cnt_ths": "bc55408ab36f2eb4c9c1a8e5a6dbd14eb062bfdbf075b14a7e2aad20f87f4ffa",
    "moneyflow_dc": "ff4d247fc67e1c10879e76d5cd0963ee3c885274d53ace79425058cef06e2014",
    "moneyflow_ind_dc": "6c7f6634677d1ca238083758fb511fb79256a27968ebdfa6e66ad6ff0314003a",
    "moneyflow_ind_ths": "6896aa9f968e18da4c825cfbeb7227ed5a247afebec8d4f78875b4b5d335a1a0",
    "moneyflow_mkt_dc": "eead485449f4b547ce5c0ce4ecae6e327ecba4b604cbbdc3fbe6bef32686a2b2",
    "moneyflow_ths": "66d3a2d779138ec7c59f5b1f56b6920f5e61a330b89590159bb89c776fe5fc76",
}


class Source:
    def __init__(self, rows=None):
        self.requests = []
        self.mutate = lambda value: value
        self.rows = rows or {
            ds: [
                self.row(ds, day, scope)
                for day in (*DATES, OUTSIDE)
                for scope in (
                    ("行业", "概念", "地域")
                    if ds == "moneyflow_ind_dc" and day == CUTOFF
                    else ("行业",)
                )
            ]
            for ds in DATASETS
        }

    @staticmethod
    def row(dataset, day=CUTOFF, scope="行业"):
        row = {
            c.name: None if c.type == "VARCHAR" else "0"
            for c in history_schema(dataset)
        }
        row["trade_date"] = day
        if "ts_code" in row:
            row["ts_code"] = "000001.SZ"
        if "name" in row:
            row["name"] = scope + ',"名称\n换行'
        if dataset == "moneyflow_ind_dc":
            row["content_type"] = scope
            if day == DATES[0]:
                row["ts_code"] = None
        return row

    def metadata(self, request, sink, check):
        self.requests.append(("metadata", request.dataset, request.sql()))
        counts = {}
        for row in self.rows[request.dataset]:
            if (
                request.selected_dates is not None
                and row["trade_date"] not in request.selected_dates
            ):
                continue
            key = (
                row["trade_date"],
                row["content_type"] if request.dataset == "moneyflow_ind_dc" else "",
            )
            counts[key] = counts.get(key, 0) + 1
        value = {
            "dataset": request.dataset,
            "cutoff": request.cutoff,
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
                for c in history_schema(request.dataset)
            ],
            "facts": [
                {
                    "trade_date": day,
                    "scope": scope,
                    "rows": rows,
                    "keys": rows,
                    "invalid_keys": 0,
                }
                for (day, scope), rows in sorted(counts.items())
            ],
        }
        if request.selected_dates is not None:
            value["selected_dates"] = list(request.selected_dates)
        value = self.mutate(value)
        sink.write(
            json.dumps(value, ensure_ascii=False).encode().hex().encode() + b"\n"
        )
        check()

    def copy(self, request, sink, check):
        self.requests.append(("copy", request.plan.dataset, request.sql()))
        rows = [
            row
            for row in self.rows[request.plan.dataset]
            if row["trade_date"] in request.plan.units[request.unit_id].dates
        ]
        fields = [c.name for c in history_schema(request.plan.dataset)]
        handle = io.StringIO(newline="")
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(fields)
        for row in rows:
            writer.writerow([r"\N" if row.get(f) is None else row[f] for f in fields])
        wire = handle.getvalue().encode()
        for offset in range(0, len(wire), 65536):
            sink.write(wire[offset : offset + 65536])
            check()


@pytest.fixture(autouse=True)
def space(monkeypatch):
    monkeypatch.setattr(
        engine.shutil, "disk_usage", lambda _: SimpleNamespace(free=128 * 1024**3)
    )


def build(staging, source, *, dates=DATES, freeze=False, **kwargs):
    return (
        cohort.freeze_moneyflow_history_cohort
        if freeze
        else cohort.build_moneyflow_history_cohort_candidates
    )(
        staging_root=staging,
        operation_id="sample",
        cutoff=CUTOFF,
        selected_dates=dates,
        source=source,
        **kwargs,
    )


def root(staging):
    return staging / "moneyflow/sample"


def read(staging, name="progress.json"):
    return json.loads((root(staging) / name).read_text())


def hashes(directory):
    return {
        str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in directory.rglob("*.parquet")
    }


def test_seven_exact_scopes_reuse_real_candidate_and_promotion_chain(tmp_path):
    source = Source()
    staging, lake = tmp_path / "staging", tmp_path / "lake"
    lake.mkdir()
    built = build(staging, source)
    manifest = read(staging, "cohort.json")
    assert manifest["selected_dates"] == list(DATES)
    assert manifest["total_rows"] == 16 and manifest["total_dates"] == 14
    assert manifest["total_units"] == built["completed_units"] == 14
    assert manifest["max_requests"] == 56
    assert not any(manifest["missing_dates"].values())
    assert {p.parent.name for p in root(staging).rglob("raw.parquet")} == set(DATES)
    assert len(hashes(root(staging))) == 28
    assert len(source.requests) == built["copy_transactions"] == 42
    assert all(OUTSIDE not in sql for _, _, sql in source.requests)
    assert all(
        "IN (DATE" in sql for kind, _, sql in source.requests if kind == "metadata"
    )
    expected = hashes(root(staging))
    replay = build(staging, source)
    assert hashes(root(staging)) == expected
    assert replay["copy_transactions"] == len(source.requests) == 49
    assert all(kind == "metadata" for kind, _, _ in source.requests[42:])
    with pytest.raises(MoneyflowContractError, match="history_cohort_changed"):
        promote.promote_moneyflow_history_cohort(
            staging_root=staging,
            lake_root=lake,
            operation_id="sample",
            cutoff=CUTOFF,
            apply=True,
        )
    assert not hashes(lake)
    result = promote.promote_moneyflow_history_cohort(
        staging_root=staging,
        lake_root=lake,
        operation_id="sample",
        cutoff=CUTOFF,
        selected_dates=DATES,
        apply=True,
    )
    assert result["promoted_files"] == 28 and result["promoted_dates"] == 14
    assert result["promoted_rows"] == 16 and result["copy_transactions"] == 49


@pytest.mark.parametrize("dataset", DATASETS)
def test_source_sql_filters_exact_dates_before_aggregate(dataset):
    assert (
        hashlib.sha256(
            metadata.moneyflow_history_metadata_sql(dataset, CUTOFF).encode()
        ).hexdigest()
        == FULL_SCOPE_SQL_SHA256[dataset]
    )
    sql = metadata.moneyflow_history_metadata_sql(dataset, CUTOFF, selected_dates=DATES)
    assert (
        sql.count(";") == 4
        and sql.startswith("BEGIN READ ONLY;")
        and sql.endswith("ROLLBACK;\n")
    )
    assert (
        "WHERE (\"trade_date\" IN (DATE '2024-12-19',DATE '2026-09-30') OR \"trade_date\" IS NULL)"
        in sql
    )
    assert '"trade_date" <=' not in sql and "SELECT *" not in sql
    assert ("LIMIT 7" if dataset == "moneyflow_ind_dc" else "LIMIT 3") in sql
    assert "'selected_dates',json_build_array('2024-12-19','2026-09-30')" in sql


@pytest.mark.parametrize(
    "dates",
    (
        (),
        [],
        list(DATES),
        CUTOFF,
        tuple(reversed(DATES)),
        (CUTOFF, CUTOFF),
        ("2026-09-31",),
        ("2026-10-01",),
        (CUTOFF + "' OR true",),
        tuple(f"2026-09-{d:02d}" for d in range(1, 22)),
    ),
)
def test_invalid_intent_stops_before_source_and_directory_creation(tmp_path, dates):
    source = Source()
    with pytest.raises(MoneyflowContractError):
        build(tmp_path, source, dates=dates)
    assert not source.requests and not root(tmp_path).exists()


@pytest.mark.parametrize("dates", (None, (CUTOFF,), (DATES[0],)))
def test_reusing_operation_with_other_intent_cannot_change_source_scope(
    tmp_path, dates
):
    source = Source()
    build(tmp_path, source, freeze=True)
    before = len(source.requests)
    checkpoint = (root(tmp_path) / "cohort.json").read_bytes()
    with pytest.raises(
        MoneyflowContractError, match="history_execution_contract_changed"
    ):
        build(tmp_path, source, freeze=True, dates=dates)
    assert len(source.requests) == before
    assert (root(tmp_path) / "cohort.json").read_bytes() == checkpoint


@pytest.mark.parametrize("kind", ("echo", "outside", "rows", "empty", "type", "keys"))
def test_source_scope_and_budget_fail_before_business_copy(tmp_path, kind):
    source = Source()

    def change(value):
        if kind == "echo":
            value["selected_dates"] = [CUTOFF]
        if kind == "outside":
            value["facts"][0]["trade_date"] = "2024-12-18"
        if kind == "rows":
            for f in value["facts"]:
                f.update(rows=60000, keys=60000)
        if kind == "empty":
            value["facts"] = []
        if kind == "type":
            value["columns"][0][1] = "double precision"
        if kind == "keys":
            value["facts"][0]["keys"] = 0
        return value

    source.mutate = change
    with pytest.raises(MoneyflowContractError):
        build(tmp_path, source)
    assert source.requests and all(kind == "metadata" for kind, _, _ in source.requests)
    assert not hashes(root(tmp_path))


def test_missing_selected_day_preserves_gap_without_fabrication(tmp_path):
    source = Source()
    source.rows["moneyflow_ths"] = [
        r for r in source.rows["moneyflow_ths"] if r["trade_date"] != DATES[0]
    ]
    build(tmp_path, source)
    manifest = read(tmp_path, "cohort.json")
    assert manifest["missing_dates"]["moneyflow_ths"] == [DATES[0]]
    assert manifest["plans"]["moneyflow_ths"]["rows"] == 1
    assert manifest["total_dates"] == 13 and len(hashes(root(tmp_path))) == 26


def test_fully_empty_dataset_is_refused_before_any_business_copy(tmp_path):
    source = Source()
    source.rows["moneyflow_ths"] = [
        r for r in source.rows["moneyflow_ths"] if r["trade_date"] == OUTSIDE
    ]
    with pytest.raises(MoneyflowContractError, match="history_metadata_fact_budget"):
        build(tmp_path, source)
    assert all(kind == "metadata" for kind, _, _ in source.requests)


def test_freeze_only_default_full_scope_and_source_drift(tmp_path):
    source = Source()
    frozen = build(tmp_path, source, freeze=True, dates=None)
    assert "selected_dates" not in frozen and "missing_dates" not in frozen
    assert OUTSIDE in {
        f["trade_date"] for f in frozen["snapshots"]["moneyflow"]["facts"]
    }
    assert all('"trade_date" <= DATE' in sql for _, _, sql in source.requests)
    assert not hashes(root(tmp_path))
    source.rows["moneyflow"].append(
        {**source.rows["moneyflow"][0], "ts_code": "000002.SZ"}
    )
    with pytest.raises(MoneyflowContractError, match="history_source_metadata_changed"):
        build(tmp_path, source, freeze=True, dates=None)


def test_reviewed_cohort_is_checked_without_extra_source_requests_and_pinned(tmp_path):
    reviewed = build(tmp_path / "review", Source(), freeze=True)["cohort_hash"]
    staging, source = tmp_path / "execution", Source()
    result = build(staging, source, expected_cohort_hash=reviewed)
    assert result["reviewed_cohort_hash"] == reviewed
    assert len(source.requests) == 42
    before = hashes(root(staging))
    with pytest.raises(MoneyflowContractError, match="history_reviewed_cohort_changed"):
        build(staging, source, expected_cohort_hash="0" * 64)
    assert len(source.requests) == 42 and hashes(root(staging)) == before
    replay = build(staging, source)
    assert replay["reviewed_cohort_hash"] == reviewed
    assert len(source.requests) == 49 and hashes(root(staging)) == before


def test_wrong_reviewed_cohort_never_exports_business_rows_even_on_resume(tmp_path):
    source = Source()
    with pytest.raises(MoneyflowContractError, match="history_reviewed_cohort_changed"):
        build(tmp_path, source, expected_cohort_hash="0" * 64)
    assert read(tmp_path)["reviewed_cohort_hash"] == "0" * 64
    assert len(source.requests) == 14
    with pytest.raises(MoneyflowContractError, match="history_reviewed_cohort_changed"):
        build(tmp_path, source)
    assert len(source.requests) == 21
    assert all(kind == "metadata" for kind, _, _ in source.requests)
    assert not hashes(root(tmp_path))


@pytest.mark.parametrize("reviewed", ("", "A" * 64, "a" * 63, 1, ["a" * 64]))
def test_invalid_review_hash_stops_before_source_or_directory(tmp_path, reviewed):
    source = Source()
    with pytest.raises(MoneyflowContractError, match="history_reviewed_hash"):
        build(tmp_path, source, expected_cohort_hash=reviewed)
    assert not source.requests and not root(tmp_path).exists()


def test_malformed_persisted_review_hash_cannot_bypass_gate(tmp_path):
    source = Source()
    build(tmp_path, source, freeze=True)
    progress_path = root(tmp_path) / "progress.json"
    progress = read(tmp_path)
    progress["reviewed_cohort_hash"] = "invalid"
    progress_path.write_text(json.dumps(progress))
    before = len(source.requests)
    with pytest.raises(MoneyflowContractError, match="history_reviewed_hash"):
        build(tmp_path, source)
    assert len(source.requests) == before and not hashes(root(tmp_path))


def test_real_process_exit_and_resume_preserves_selected_scope_and_closed_files(
    tmp_path,
):
    script = tmp_path / "process.py"
    script.write_text("""
import json,os,runpy,sys
from pathlib import Path
from types import SimpleNamespace
m=runpy.run_path("tests/test_moneyflow_history_selected_dates.py")
m['engine'].shutil.disk_usage=lambda _:SimpleNamespace(free=128*1024**3)
original=m['engine']._Store.json
if sys.argv[2]=='exit':
    def save(self,path,value):
        original(self,path,value)
        if path.name=='progress.json' and value.get('completed_units')==1:os._exit(23)
    m['engine']._Store.json=save
print(json.dumps(m['build'](Path(sys.argv[1]),m['Source']())))
""")
    command = [sys.executable, "-B", str(script), str(tmp_path / "staging"), "exit"]
    first = subprocess.run(command, capture_output=True, timeout=30, check=False)
    assert first.returncode == 23, first.stderr.decode()
    staging = tmp_path / "staging"
    saved = read(staging)
    assert saved["copy_transactions"] == 16 and saved["selected_dates"] == list(DATES)
    observed = hashes(root(staging))
    assert len(observed) == 2
    command[-1] = "resume"
    second = subprocess.run(command, capture_output=True, timeout=30, check=False)
    assert second.returncode == 0, second.stderr.decode()
    result = json.loads(second.stdout)
    assert result["copy_transactions"] == 49 and result["completed_units"] == 14
    assert all(hashes(root(staging))[p] == digest for p, digest in observed.items())
    assert read(staging, "cohort.json")["selected_dates"] == list(DATES)
