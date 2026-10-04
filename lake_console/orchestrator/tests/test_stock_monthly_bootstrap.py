"""Independent fixtures prove exact values, bounded reads and recovery after interruption."""

import csv
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from orchestrator.defs.bootstrap import stock_monthly_promote as promotion
from orchestrator.defs.bootstrap.stock_monthly_capture import (
    MonthlyCaptureStore,
    build_month_candidates,
    monthly_target_path,
)
from orchestrator.defs.bootstrap.stock_monthly_files import (
    check_monthly_root,
    monthly_file_hash,
    monthly_file_lock,
    write_monthly_json,
)
from orchestrator.defs.io.stock_monthly_raw import load_monthly_csv
from orchestrator.defs.prod_db.stock_monthly import (
    PsqlMonthlyExporter,
    build_prod_monthly_export_sql,
    build_prod_monthly_query,
)
from orchestrator.defs.run_contracts.stock_monthly import (
    MonthlyBootstrapIOPolicy,
    MonthlyYearInventory,
    StockMonthlyPolicy,
    monthly_column_specs,
)
from orchestrator.defs.stock_monthly_planner import plan_month_bootstrap


class FixtureExporter:
    def __init__(self, rows):
        self.rows, self.calls = rows, 0

    def export(
        self, unit, policy, io_policy, attempt, cancel, progress, remaining_rows
    ):
        self.calls += 1
        fields = [n for n, _ in monthly_column_specs(unit.source)]
        rows = [r for r in self.rows if r["ts_code"] in unit.sorted_codes]
        path = attempt / "transport.csv"
        with path.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        evidence = {
            "source_rows": len(rows),
            "readonly": "on",
            "isolation": "repeatable read",
            "snapshot": "fixture:1",
            "snapshot_at": "2026-10-05T10:00:00+08:00",
        }
        write_monthly_json(
            attempt / "control.json", evidence, io_policy.control_max_bytes
        )
        (attempt / "transport.sql").write_text(build_prod_monthly_query(unit, policy))
        return path, evidence


def fixture_rows(source="primary_unadjusted"):
    rows = []
    for code in ("000001.SZ", "600000.SH"):
        for day in ("20200131", "20200228", "20200229"):
            row = {n: "12.3400" for n, _ in monthly_column_specs(source)}
            row.update(
                ts_code=code,
                trade_date=day,
                end_date="\\N",
                freq="month",
                vol="1234567890123456.1234",
                amount="0.0000",
                change="-0.0001",
                pct_chg="-12.3400",
                close="99.1234" if day == "20200229" else "12.3400",
            )
            rows.append(row)
    return rows


def create_store(tmp_path, source="primary_unadjusted", policy=None, rows=None):
    stage, lake = tmp_path / "staging", tmp_path / "lake"
    stage.mkdir(exist_ok=True)
    lake.mkdir(exist_ok=True)
    proof = tmp_path / "inventory.json"
    proof.write_text('{"fixture":"snapshot"}\n')
    inventory = MonthlyYearInventory(
        2020,
        ("000001.SZ", "600000.SH"),
        (("20200131", 2), ("20200228", 2), ("20200229", 2)),
    )
    plan = plan_month_bootstrap(
        source,
        (inventory,),
        first_month="2020-01",
        last_month="2020-02",
        inventory_ref=str(proof),
        inventory_hash=monthly_file_hash(proof),
        policy=policy,
    )
    return (
        MonthlyCaptureStore(plan, stage),
        lake,
        FixtureExporter(rows if rows is not None else fixture_rows(source)),
    )


def prepared(tmp_path, **kwargs):
    store, lake, exporter = create_store(tmp_path, **kwargs)
    for unit in store.plan.units:
        store.capture_unit(unit, exporter)
    path, digest = build_month_candidates(store, 2020, lake)
    return store, lake, exporter, path, digest


@pytest.mark.parametrize("source", ["primary_unadjusted", "primary_adjusted"])
def test_exact_source_exclusion_decimal_null_and_idempotent_delivery(tmp_path, source):
    store, lake, exporter, path, digest = prepared(tmp_path, source=source)
    audit = json.loads(path.read_text())
    assert (audit["captured_rows"], audit["excluded_rows"], audit["accepted_rows"]) == (
        6,
        2,
        4,
    )
    checkpoint = promotion.promote_month_candidates(store, path, digest)
    assert len(checkpoint["completed"]) == 2
    with store.connection() as con:
        target = monthly_target_path(lake, source, "2020-02")
        actual = con.execute(
            "SELECT ts_code,trade_date,end_date,CAST(close AS VARCHAR),CAST(vol AS VARCHAR),CAST(change AS VARCHAR) FROM read_parquet(?,hive_partitioning=false) ORDER BY ts_code",
            [str(target)],
        ).fetchall()
        assert actual == [
            (
                "000001.SZ",
                "20200228",
                None,
                "12.3400",
                "1234567890123456.1234",
                "-0.0001",
            ),
            (
                "600000.SH",
                "20200228",
                None,
                "12.3400",
                "1234567890123456.1234",
                "-0.0001",
            ),
        ]
        assert con.execute(
            "SELECT DISTINCT trade_date,CAST(close AS VARCHAR) FROM read_parquet(?,hive_partitioning=false)",
            [str(path.parent / "excluded_month_version.parquet")],
        ).fetchall() == [("20200229", "99.1234")]
    before = {m: r["sha256"] for m, r in checkpoint["completed"].items()}
    replay = promotion.promote_month_candidates(store, path, digest)
    assert {m: r["sha256"] for m, r in replay["completed"].items()} == before
    store.capture_unit(store.plan.units[0], exporter)
    assert exporter.calls == 1


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("freq", "week", "key_or_date"),
        ("trade_date", "20200227", "unexpected_month"),
        ("trade_date", "20210131", "outside_unit"),
        ("trade_date", "20201331", "key_or_date"),
        ("end_date", "bad", "key_or_date"),
        ("close", "12.12345", "decimal"),
        ("close", "NaN", "decimal"),
        ("close", "1e10", "decimal"),
        ("pct_chg", "9999999.0000", "decimal"),
        ("vol", "12345678901234567.0000", "decimal"),
    ],
)
def test_invalid_source_never_seals_receipt(tmp_path, field, value, reason):
    rows = fixture_rows()
    rows[0][field] = value
    store, lake, exporter = create_store(tmp_path, rows=rows)
    with pytest.raises(ValueError, match=reason):
        store.capture_unit(store.plan.units[0], exporter)
    assert not (store.unit_directory(store.plan.units[0]) / "receipt.json").exists()
    assert not list(lake.rglob("*.parquet"))


def test_duplicate_and_extra_fields_fail_instead_of_silent_dedup(tmp_path):
    rows = fixture_rows()
    rows[1] = rows[0].copy()
    store, _, exporter = create_store(tmp_path, rows=rows)
    with pytest.raises(ValueError, match="duplicate_key"):
        store.capture_unit(store.plan.units[0], exporter)
    path = tmp_path / "wrong.csv"
    path.write_text("ts_code,trade_date,freq,fetched_at\n")
    with store.connection() as con, pytest.raises(ValueError, match="source_schema"):
        load_monthly_csv(con, path, store.plan.units[0], store.plan.policy, 0)


def test_missing_28th_does_not_select_29th(tmp_path):
    rows = [r for r in fixture_rows() if r["trade_date"] != "20200228"]
    store, lake, exporter = create_store(tmp_path, rows=rows)
    store.capture_unit(store.plan.units[0], exporter)
    with pytest.raises(ValueError, match="inventory_count_changed"):
        build_month_candidates(store, 2020, lake)


def test_tampered_capture_inventory_and_plan_fail_closed(tmp_path):
    store, _, exporter = create_store(tmp_path)
    unit = store.plan.units[0]
    receipt = store.capture_unit(unit, exporter)
    capture = store.unit_directory(unit) / receipt["attempt"] / "capture.parquet"
    capture.write_bytes(capture.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="capture_changed"):
        store.capture_unit(unit, exporter)
    Path(store.plan.inventory_ref).write_text("changed")
    with pytest.raises(ValueError, match="inventory_changed"):
        store.capture_unit(unit, exporter)
    with pytest.raises(ValueError, match="frozen_plan"):
        MonthlyCaptureStore(
            replace(store.plan, accepted_rows=123), store.root.parents[2]
        )


def test_cancel_keeps_committed_unit_no_new_source_call(tmp_path):
    store, lake, exporter = create_store(
        tmp_path, policy=StockMonthlyPolicy(prod_code_batch=1)
    )
    store.capture_unit(store.plan.units[0], exporter)
    with pytest.raises(ValueError, match="cancelled"):
        store.capture_unit(store.plan.units[1], exporter, cancel=lambda: True)
    assert exporter.calls == 1
    store.capture_unit(store.plan.units[0], exporter)
    store.capture_unit(store.plan.units[1], exporter)
    assert exporter.calls == 2
    path, _ = build_month_candidates(store, 2020, lake)
    assert json.loads(path.read_text())["accepted_rows"] == 4


def test_os_replace_interruption_before_checkpoint_recovers(tmp_path, monkeypatch):
    store, lake, _, path, digest = prepared(tmp_path)
    original = os.replace

    def interrupted(src, dst):
        original(src, dst)
        if Path(dst).name == "data.parquet":
            raise RuntimeError("process_exit_after_replace")

    monkeypatch.setattr(promotion.os, "replace", interrupted)
    with pytest.raises(RuntimeError, match="process_exit"):
        promotion.promote_month_candidates(store, path, digest)
    assert len(list(lake.rglob("*.parquet"))) == 1
    monkeypatch.setattr(promotion.os, "replace", original)
    outcome = promotion.promote_month_candidates(store, path, digest)
    assert (
        len(outcome["completed"]) == 2
        and outcome["completed"]["2020-01"]["outcome"] == "promotion_recovered"
    )


def test_checkpoint_failure_does_not_rollback_installed_file(tmp_path, monkeypatch):
    store, lake, _, path, digest = prepared(tmp_path)
    original = promotion.write_monthly_json

    def failed(*args):
        raise OSError("disk_write_failed")

    monkeypatch.setattr(promotion, "write_monthly_json", failed)
    with pytest.raises(OSError, match="disk_write_failed"):
        promotion.promote_month_candidates(store, path, digest)
    assert len(list(lake.rglob("*.parquet"))) == 1
    monkeypatch.setattr(promotion, "write_monthly_json", original)
    assert (
        len(promotion.promote_month_candidates(store, path, digest)["completed"]) == 2
    )


def test_candidate_and_audit_tamper_stop_before_install(tmp_path):
    store, lake, _, path, digest = prepared(tmp_path)
    candidate = next((path.parent / "candidates").rglob("*.parquet"))
    candidate.write_bytes(b"changed")
    with pytest.raises(ValueError, match="candidate_changed"):
        promotion.promote_month_candidates(store, path, digest)
    path.write_text("{}")
    with pytest.raises(ValueError, match="audit_changed"):
        promotion.promote_month_candidates(store, path, digest)
    assert not list(lake.rglob("*.parquet"))


def test_target_changed_by_other_writer_is_preserved(tmp_path):
    store, lake, _, path, digest = prepared(tmp_path)
    target = monthly_target_path(lake, store.plan.source, "2020-01")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"another_writer")
    with pytest.raises(ValueError, match="fingerprint_changed"):
        promotion.promote_month_candidates(store, path, digest)
    assert target.read_bytes() == b"another_writer"


def test_existing_different_values_require_revision(tmp_path):
    store, lake, exporter = create_store(tmp_path)
    unit = store.plan.units[0]
    store.capture_unit(unit, exporter)
    target = monthly_target_path(lake, store.plan.source, "2020-01")
    target.parent.mkdir(parents=True)
    _, capture = store.read_receipt(unit)
    with store.connection() as con:
        con.execute(
            f"COPY (SELECT * REPLACE (CAST(123.0000 AS DECIMAL(18,4)) AS close) FROM read_parquet(?,hive_partitioning=false) WHERE trade_date='20200131') TO '{target}' (FORMAT PARQUET)",
            [str(capture)],
        )
    before = monthly_file_hash(target)
    path, digest = build_month_candidates(store, 2020, lake)
    with pytest.raises(ValueError, match="revision_required"):
        promotion.promote_month_candidates(store, path, digest)
    assert monthly_file_hash(target) == before


def test_identical_existing_file_is_reused(tmp_path):
    store, lake, _, path, digest = prepared(tmp_path)
    record = json.loads(path.read_text())["records"][0]
    target = monthly_target_path(lake, store.plan.source, record["month"])
    target.parent.mkdir(parents=True)
    target.write_bytes((path.parent / record["path"]).read_bytes())
    assert (
        promotion.promote_month_candidates(store, path, digest)["completed"][
            record["month"]
        ]["outcome"]
        == "identical_reused"
    )


@pytest.mark.parametrize("source", ["primary_unadjusted", "primary_adjusted"])
def test_prod_sql_projection_readonly_snapshot_and_exact_scope(tmp_path, source):
    store, _, _ = create_store(tmp_path, source=source)
    sql = build_prod_monthly_export_sql(
        store.plan.units[0],
        store.plan.policy,
        store.io_policy,
        tmp_path / "control.json",
        10000,
    )
    assert "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY" in sql
    assert (
        sql.index("BEGIN")
        < sql.index("SELECT count(*)")
        < sql.index("COPY (")
        < sql.index("ROLLBACK")
    )
    assert (
        "freq = 'month'" in sql
        and "DATE '2020-01-01'" in sql
        and "DATE '2020-03-01'" in sql
    )
    assert "20200228" not in sql and "20200229" not in sql
    assert all(
        s not in sql
        for s in (
            "SELECT *",
            "raw_payload",
            "fetched_at",
            "ops.",
            "core_serving",
            "DELETE",
            "INSERT",
        )
    )


@pytest.mark.parametrize(
    "mutation",
    [
        {"source": "weekly"},
        {"sorted_codes": ("000001.SZ';DROP TABLE x;--",)},
        {"sorted_codes": ("600000.SH", "000001.SZ")},
        {"max_rows": True},
        {"source_date_end": "2021-03-01"},
        {"source_date_start": "2020-01-02"},
        {"source_date_start": "2020-01-01'; SELECT 1"},
        {"unit_id": "bad"},
    ],
)
def test_invalid_units_never_generate_sql(tmp_path, mutation):
    store, _, _ = create_store(tmp_path)
    with pytest.raises(ValueError):
        build_prod_monthly_query(
            replace(store.plan.units[0], **mutation), store.plan.policy
        )


def test_supervisor_cancels_actual_child_and_wrapper_is_only_entry(tmp_path):
    store, _, _ = create_store(tmp_path)
    attempt = store.root / "supervisor"
    attempt.mkdir()
    children = []

    def factory(command, **kwargs):
        assert command[0] == "bash" and command[1].endswith("/scripts/psql-remote.sh")
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"], **kwargs
        )
        children.append(child)
        return child

    with pytest.raises(ValueError, match="cancelled"):
        PsqlMonthlyExporter(process_factory=factory).export(
            store.plan.units[0],
            store.plan.policy,
            store.io_policy,
            attempt,
            lambda: bool(children),
            lambda event: None,
            10000,
        )
    assert children[0].poll() is not None and not (attempt / "transport.csv").exists()


def test_forbidden_roots_symlink_and_writer_lock(tmp_path):
    for path in (Path("/Volumes/datasource/goldenshare-tushare-lake"), Path("/etc")):
        with pytest.raises(ValueError, match="root_forbidden|symlink_forbidden"):
            check_monthly_root(path, staging=False)
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        check_monthly_root(link, staging=True)
    lock = tmp_path / "writer.lock"
    with (
        monthly_file_lock(lock),
        pytest.raises(ValueError, match="writer_busy"),
        monthly_file_lock(lock),
    ):
        pass


@pytest.mark.parametrize(
    "kwargs",
    [
        {"control_max_bytes": 0},
        {"duckdb_threads": True},
        {"prod_statement_timeout_ms": 46000},
    ],
)
def test_invalid_runtime_limits(kwargs):
    with pytest.raises(ValueError):
        MonthlyBootstrapIOPolicy(**kwargs)


def test_actual_child_exit_after_receipt_resumes_without_another_export(tmp_path):
    code = (
        "import runpy,os; from pathlib import Path; namespace=runpy.run_path('tests/test_stock_monthly_bootstrap.py'); store,lake,exporter=namespace['create_store'](Path("
        + repr(str(tmp_path))
        + ")); store.capture_unit(store.plan.units[0],exporter); os._exit(17)"
    )
    child = subprocess.run(
        [sys.executable, "-B", "-c", code], capture_output=True, check=False, timeout=20
    )
    assert child.returncode == 17, child.stderr.decode()
    store, lake, exporter = create_store(tmp_path)
    store.capture_unit(store.plan.units[0], exporter)
    assert exporter.calls == 0
    path, digest = build_month_candidates(store, 2020, lake)
    assert (
        len(promotion.promote_month_candidates(store, path, digest)["completed"]) == 2
    )


def test_row_budget_count_and_control_budget_rejections(tmp_path):
    store, _, exporter = create_store(
        tmp_path, rows=fixture_rows() + [fixture_rows()[0]]
    )
    with pytest.raises(ValueError, match="row_budget"):
        store.capture_unit(store.plan.units[0], exporter)
    path = tmp_path / "control.json"
    with pytest.raises(ValueError, match="control_budget"):
        write_monthly_json(path, {"too_long": "x" * 100}, 10)
    assert not path.exists()


def test_supervisor_timeout_and_csv_budget_reap_real_children(tmp_path):
    store, _, _ = create_store(tmp_path)
    for mode in ("timeout", "bytes"):
        attempt = store.root / mode
        attempt.mkdir()
        children = []

        def factory(command, *, mode=mode, children=children, **kwargs):
            code = (
                "import time; time.sleep(30)"
                if mode == "timeout"
                else 'import sys,time;sys.stdout.write("x"*200);sys.stdout.flush();time.sleep(30)'
            )
            child = subprocess.Popen([sys.executable, "-c", code], **kwargs)
            children.append(child)
            return child

        budget = MonthlyBootstrapIOPolicy(
            prod_statement_timeout_ms=1000, prod_unit_seconds=1, prod_csv_max_bytes=100
        )
        with pytest.raises(
            ValueError, match="unit_timeout" if mode == "timeout" else "csv_budget"
        ):
            PsqlMonthlyExporter(process_factory=factory).export(
                store.plan.units[0],
                store.plan.policy,
                budget,
                attempt,
                lambda: False,
                lambda event: None,
                10000,
            )
        assert children[0].poll() is not None


def test_cancel_after_one_file_keeps_checkpoint_and_resumes_remaining_month(tmp_path):
    store, lake, _, path, digest = prepared(tmp_path)
    completed = []
    with pytest.raises(ValueError, match="cancelled"):
        promotion.promote_month_candidates(
            store,
            path,
            digest,
            cancel=lambda: bool(completed),
            progress=completed.append,
        )
    assert len(list(lake.rglob("*.parquet"))) == 1
    assert (
        len(json.loads((path.parent / "promoted.json").read_text())["completed"]) == 1
    )
    assert (
        len(promotion.promote_month_candidates(store, path, digest)["completed"]) == 2
    )


def test_common_target_lock_serializes_different_io_policy_versions(tmp_path):
    store, lake, _, path, digest = prepared(tmp_path)
    other = MonthlyCaptureStore(
        store.plan,
        store.root.parents[2],
        io_policy=MonthlyBootstrapIOPolicy(duckdb_threads=1),
    )
    assert other.root != store.root and other.root.parents[1] == store.root.parents[1]
    locks = other.root.parents[1] / "locks"
    locks.mkdir(exist_ok=True)
    with (
        monthly_file_lock(locks / "primary_unadjusted-2020-01.lock"),
        pytest.raises(ValueError, match="writer_busy"),
    ):
        promotion.promote_month_candidates(store, path, digest)
    assert not list(lake.rglob("*.parquet"))


def test_cross_device_preflight_refuses_before_any_promotion(tmp_path, monkeypatch):
    store, lake, _, path, digest = prepared(tmp_path)
    original = Path.stat

    def stat_with_other_device(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if self == lake:
            fields = list(result)
            fields[2] += 1
            return os.stat_result(fields)
        return result

    monkeypatch.setattr(Path, "stat", stat_with_other_device)
    with pytest.raises(ValueError, match="cross_filesystem"):
        promotion.promote_month_candidates(store, path, digest)
    assert not list(lake.rglob("*.parquet"))


def test_supervised_export_success_and_bad_control_are_bounded(tmp_path):
    store, _, _ = create_store(tmp_path)
    unit = store.plan.units[0]
    for readonly in ("on", "off"):
        attempt = store.root / ("child-" + readonly)
        attempt.mkdir()

        def factory(command, *, readonly=readonly, attempt=attempt, **kwargs):
            control = {
                "source_rows": 0,
                "readonly": readonly,
                "isolation": "repeatable read",
                "snapshot": "1:1:",
                "snapshot_at": "2026-10-05T10:00:00+08:00",
            }
            header = ",".join(n for n, _ in monthly_column_specs(unit.source)) + "\n"
            script = (
                "from pathlib import Path;import sys;Path("
                + repr(str(attempt / "control.json.pending"))
                + ").write_text("
                + repr(json.dumps(control))
                + ");sys.stdout.write("
                + repr(header)
                + ")"
            )
            return subprocess.Popen([sys.executable, "-c", script], **kwargs)

        exporter = PsqlMonthlyExporter(process_factory=factory)
        if readonly == "off":
            with pytest.raises(ValueError, match="prod_control_invalid"):
                exporter.export(
                    unit,
                    store.plan.policy,
                    store.io_policy,
                    attempt,
                    lambda: False,
                    lambda event: None,
                    10000,
                )
            assert not (attempt / "transport.csv").exists()
        else:
            csv_path, evidence = exporter.export(
                unit,
                store.plan.policy,
                store.io_policy,
                attempt,
                lambda: False,
                lambda event: None,
                10000,
            )
            assert (
                csv_path == attempt / "transport.csv" and evidence["source_rows"] == 0
            )
            assert (attempt / "transport.sql").exists() and not (
                attempt / "transport.csv.pending"
            ).exists()


def test_disk_budget_stops_before_new_export_or_promotion(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from orchestrator.defs.bootstrap import stock_monthly_files

    store, lake, exporter = create_store(tmp_path)
    original = stock_monthly_files.shutil.disk_usage
    monkeypatch.setattr(
        stock_monthly_files.shutil, "disk_usage", lambda path: SimpleNamespace(free=0)
    )
    with pytest.raises(ValueError, match="disk_budget"):
        store.capture_unit(store.plan.units[0], exporter)
    assert exporter.calls == 0
    monkeypatch.setattr(stock_monthly_files.shutil, "disk_usage", original)
    store.capture_unit(store.plan.units[0], exporter)
    path, digest = build_month_candidates(store, 2020, lake)
    monkeypatch.setattr(
        stock_monthly_files.shutil, "disk_usage", lambda path: SimpleNamespace(free=0)
    )
    with pytest.raises(ValueError, match="disk_budget"):
        promotion.promote_month_candidates(store, path, digest)
    assert not list(lake.rglob("*.parquet"))
