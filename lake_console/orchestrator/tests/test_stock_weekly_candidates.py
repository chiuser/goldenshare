import json
from dataclasses import replace
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from orchestrator.defs.bootstrap.stock_weekly_candidates import (
    build_weekly_partition_candidates,
    partition_path,
)
from orchestrator.defs.bootstrap.stock_weekly_capture import (
    WeeklyCaptureError,
    WeeklyCaptureStore,
)
from orchestrator.defs.bootstrap.stock_weekly_promote import promote_weekly_candidates
from orchestrator.defs.run_contracts.stock_weekly import (
    StockWeeklySource,
    weekly_column_specs,
    weekly_schema_hash,
)

from .stock_weekly_capture_test_support import bind_plan_evidence, prod_frame, prod_plan


def captured(tmp_path, frames=None, source=StockWeeklySource.PRIMARY_UNADJUSTED):
    root = tmp_path / "capture"
    root.mkdir()
    plan = prod_plan()
    if source == StockWeeklySource.PRIMARY_ADJUSTED:
        plan = replace(
            plan,
            source=source,
            units=tuple(
                replace(u, source=source, schema_hash=weekly_schema_hash(source))
                for u in plan.units
            ),
        )
    plan = bind_plan_evidence(plan, root)
    frames = frames or [prod_frame()]
    store = WeeklyCaptureStore(root, plan)
    with store.locked(), duckdb.connect() as connection:
        for unit in plan.units:
            attempt = store.begin_attempt(unit)
            chunks = [
                store.write_chunk(connection, f, unit, attempt, i)
                for i, f in enumerate(frames)
            ]
            store.seal(connection, unit, chunks, sum(len(f) for f in frames), {})
    return plan, root


def build(tmp_path, frames=None):
    plan, root = captured(tmp_path, frames)
    target = tmp_path / "formal"
    audit = build_weekly_partition_candidates(
        plan, capture_root=root, target_root=target, year=2020, partial_scope=True
    )
    return audit, target, plan, root


def test_roundtrip_and_replay_preserve_null_and_nonfriday(tmp_path):
    audit, target, _, _ = build(tmp_path, [prod_frame(trade_date="20200227")])
    assert json.loads(audit.read_text())["stats"]["non_friday_rows"] == 1
    assert promote_weekly_candidates(audit)["status"] == "preflight"
    assert not target.exists()
    assert promote_weekly_candidates(audit, apply=True)["status"] == "verified"
    path = partition_path(target, StockWeeklySource.PRIMARY_UNADJUSTED, "2020-02-28")
    with duckdb.connect() as con:
        assert con.execute(
            "SELECT trade_date,close FROM read_parquet(?,hive_partitioning=false)",
            [str(path)],
        ).fetchone() == ("20200227", None)
        assert (
            len(
                con.execute(
                    "DESCRIBE SELECT * FROM read_parquet(?,hive_partitioning=false)",
                    [str(path)],
                ).fetchall()
            )
            == 13
        )
    assert promote_weekly_candidates(audit, apply=True)["status"] == "verified"


@pytest.mark.parametrize("stage", ["before_replace", "after_replace"])
def test_interrupted_promotion_recovers(tmp_path, stage):
    audit, _, _, _ = build(tmp_path)

    def crash(current, week):
        if current == stage:
            raise RuntimeError("exit seam")

    with pytest.raises(RuntimeError, match="exit seam"):
        promote_weekly_candidates(audit, apply=True, fault_probe=crash)
    assert promote_weekly_candidates(audit, apply=True)["status"] == "verified"


def test_existing_only_and_same_value_overlap(tmp_path):
    audit, target, plan, root = build(tmp_path)
    promote_weekly_candidates(audit, apply=True)
    path = partition_path(target, plan.source, "2020-02-28")
    with duckdb.connect() as con:
        con.execute(
            "CREATE TABLE previous AS SELECT * FROM read_parquet(?,hive_partitioning=false)",
            [str(path)],
        )
        con.execute(
            "INSERT INTO previous SELECT '000001.SZ', * EXCLUDE(ts_code) FROM previous"
        )
        con.execute("COPY previous TO ? (FORMAT PARQUET)", [str(path)])
    second = build_weekly_partition_candidates(
        plan, capture_root=root, target_root=target, year=2020, partial_scope=True
    )
    stats = json.loads(second.read_text())["stats"]
    assert stats["existing_rows"] == stats["candidate_rows"] == 2
    assert stats["new_keys"] == 0
    promote_weekly_candidates(second, apply=True)


def test_source_duplicate_merge_rules(tmp_path):
    from orchestrator.defs.io.stock_weekly_raw import assemble_relation, load_relation

    audit, _, plan, _ = build(tmp_path)
    path = Path(json.loads(audit.read_text())["files"][0]["candidate"])
    with duckdb.connect() as con:
        load_relation(con, "weekly_input", [path], plan.source)
        load_relation(con, "weekly_existing", [], plan.source)
        con.execute("INSERT INTO weekly_input SELECT * FROM weekly_input")
        stats = assemble_relation(con, plan.source, 2020, plan.budget, ())
        assert stats["duplicate_rows"] == 1 and stats["candidate_rows"] == 1
        con.execute("UPDATE weekly_input SET close=2 WHERE rowid=1")
        with pytest.raises(WeeklyCaptureError, match="raw_duplicate_key"):
            assemble_relation(con, plan.source, 2020, plan.budget, ())


@pytest.mark.parametrize("kind", ["source", "candidate", "target", "audit"])
def test_changed_evidence_rejected(tmp_path, kind):
    audit, _, _, _ = build(tmp_path)
    payload = json.loads(audit.read_text())
    if kind == "source":
        path = Path(payload["source_evidence"][-1]["path"])
    elif kind == "candidate":
        path = Path(payload["files"][0]["candidate"])
    elif kind == "target":
        path = Path(payload["files"][0]["target"])
        path.parent.mkdir(parents=True)
    else:
        payload["stats"]["candidate_rows"] += 1
        audit.write_text(json.dumps(payload))
        path = None
    if path:
        path.write_bytes(b"changed")
    with pytest.raises(WeeklyCaptureError):
        promote_weekly_candidates(audit, apply=True)


def test_missing_inventory_or_receipt(tmp_path):
    plan, root = captured(tmp_path)
    with pytest.raises(WeeklyCaptureError, match="year_boundary_inventory_missing"):
        build_weekly_partition_candidates(
            plan, capture_root=root, target_root=tmp_path / "formal", year=2020
        )
    for path in root.glob("stock_weekly_raw/*/units/*/receipt.json"):
        path.unlink()
    with pytest.raises(WeeklyCaptureError, match="capture_incomplete"):
        build_weekly_partition_candidates(
            plan,
            capture_root=root,
            target_root=tmp_path / "formal",
            year=2020,
            partial_scope=True,
        )


def test_adjusted_values(tmp_path):
    frame = prod_frame()
    source = StockWeeklySource.PRIMARY_ADJUSTED
    for name, _, _ in weekly_column_specs(source):
        if name not in frame:
            frame[name] = "123.0001"
    frame = frame[[n for n, _, _ in weekly_column_specs(source)]]
    plan, root = captured(tmp_path, [frame], source)
    audit = build_weekly_partition_candidates(
        plan,
        capture_root=root,
        target_root=tmp_path / "formal",
        year=2020,
        partial_scope=True,
    )
    promote_weekly_candidates(audit, apply=True)
    with duckdb.connect() as con:
        path = partition_path(tmp_path / "formal", source, "2020-02-28")
        assert (
            str(
                con.execute(
                    "SELECT close_qfq FROM read_parquet(?,hive_partitioning=false)",
                    [str(path)],
                ).fetchone()[0]
            )
            == "123.0001"
        )


def test_cancel_after_one_partition_then_resume(tmp_path):
    audit, _, _, _ = build(
        tmp_path,
        [
            pd.concat(
                [prod_frame(), prod_frame(trade_date="20200306")], ignore_index=True
            )
        ],
    )
    completed = []
    with pytest.raises(WeeklyCaptureError, match="canceled"):
        promote_weekly_candidates(
            audit,
            apply=True,
            cancel=lambda: bool(completed),
            progress=lambda p: completed.append(p),
        )
    assert completed[0]["completed_files"] == 1
    assert promote_weekly_candidates(audit, apply=True)["files"] == 2


def test_cross_calendar_year_routing(tmp_path):
    from orchestrator.defs.run_contracts.stock_weekly import (
        ProdWeeklyScope,
        ProdYearInventory,
    )
    from orchestrator.defs.stock_weekly_planner import freeze_prod_weekly_plan

    root = tmp_path / "capture"
    root.mkdir()
    plan = freeze_prod_weekly_plan(
        ProdWeeklyScope(
            StockWeeklySource.PRIMARY_UNADJUSTED,
            tuple(ProdYearInventory(y, ("000005.SZ",), 52) for y in (2020, 2021, 2022)),
            "reports/fake.csv",
            "a" * 64,
        )
    )
    plan = bind_plan_evidence(plan, root)
    store = WeeklyCaptureStore(root, plan)
    with store.locked(), duckdb.connect() as con:
        for unit in plan.units:
            year = unit.source_date_start.year
            frame = prod_frame(trade_date="20201231" if year == 2020 else "20210101")
            if year == 2022:
                frame = frame.iloc[:0]
            attempt = store.begin_attempt(unit)
            chunk = store.write_chunk(con, frame, unit, attempt, 0)
            store.seal(con, unit, [chunk], len(frame), {})
    audit = build_weekly_partition_candidates(
        plan, capture_root=root, target_root=tmp_path / "formal", year=2021
    )
    payload = json.loads(audit.read_text())
    assert payload["stats"]["candidate_rows"] == 2
    assert payload["files"][0]["week"] == "2021-01-01"
    assert payload["partial_scope"] is False


def test_target_conflict_schema_and_wrong_week(tmp_path):
    audit, target, plan, root = build(tmp_path)
    promote_weekly_candidates(audit, apply=True)
    path = partition_path(target, plan.source, "2020-02-28")
    with duckdb.connect() as con:
        con.execute(
            "CREATE TABLE bad AS SELECT * FROM read_parquet(?,hive_partitioning=false)",
            [str(path)],
        )
        con.execute("UPDATE bad SET close=2")
        con.execute("COPY bad TO ? (FORMAT PARQUET)", [str(path)])
    with pytest.raises(WeeklyCaptureError, match="raw_duplicate_key"):
        build_weekly_partition_candidates(
            plan, capture_root=root, target_root=target, year=2020, partial_scope=True
        )
    with duckdb.connect() as con:
        con.execute("COPY (SELECT 'wrong' ts_code) TO ? (FORMAT PARQUET)", [str(path)])
    with pytest.raises((WeeklyCaptureError, duckdb.BinderException)):
        build_weekly_partition_candidates(
            plan, capture_root=root, target_root=target, year=2020, partial_scope=True
        )


def test_symlink_and_primary_exclusion(tmp_path):
    plan, root = captured(tmp_path)
    link = tmp_path / "link"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(WeeklyCaptureError, match="symlink"):
        build_weekly_partition_candidates(
            plan,
            capture_root=link,
            target_root=tmp_path / "formal",
            year=2020,
            partial_scope=True,
        )
    with pytest.raises(WeeklyCaptureError, match="primary_exclusion_forbidden"):
        build_weekly_partition_candidates(
            plan,
            capture_root=root,
            target_root=tmp_path / "formal",
            year=2020,
            partial_scope=True,
            excluded_week_keys=("2020-02-28",),
        )


def test_week_lock_and_extra_target_file(tmp_path):
    import fcntl

    audit, target, plan, root = build(tmp_path)
    from orchestrator.defs.run_contracts.stock_weekly import weekly_dataset_id

    lock = (
        root
        / "stock_weekly_raw"
        / "writer_locks"
        / weekly_dataset_id(plan.source)
        / "2020-02-28.lock"
    )
    lock.parent.mkdir(parents=True)
    with lock.open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(WeeklyCaptureError, match="weekly_writer_active"):
            promote_weekly_candidates(audit, apply=True)
    assert not target.exists()
    target_path = partition_path(target, plan.source, "2020-02-28")
    target_path.parent.mkdir(parents=True)
    target_path.with_name("unexpected.parquet").write_bytes(b"other")
    with pytest.raises(WeeklyCaptureError, match="target_layout_changed"):
        promote_weekly_candidates(audit, apply=True)


def test_fallback_negative_volume_and_double_null(tmp_path):
    from orchestrator.defs.io.stock_weekly_raw import assemble_relation, load_relation

    from .stock_weekly_capture_test_support import alternate_frame, weekly_plan

    plan = weekly_plan()
    root = tmp_path / "capture"
    root.mkdir()
    evidence = root / "source.json"
    evidence.write_text("source sample")
    import hashlib

    unit = replace(
        plan.units[0],
        source_evidence=(
            (str(evidence), hashlib.sha256(evidence.read_bytes()).hexdigest()),
        ),
    )
    plan = bind_plan_evidence(replace(plan, units=(unit,)), root)
    keys = Path(plan.evidence_ref)
    keys.write_text("ts_code,week_key\n000005.SZ,2020-02-28\n")
    plan = replace(plan, evidence_hash=hashlib.sha256(keys.read_bytes()).hexdigest())
    unit = replace(plan.units[0], expected_key_ref=plan.evidence_ref)
    plan = replace(plan, units=(unit,))
    store = WeeklyCaptureStore(root, plan)
    with store.locked(), duckdb.connect() as con:
        attempt = store.begin_attempt(unit)
        chunk = store.write_chunk(con, alternate_frame(), unit, attempt, 0)
        store.seal(con, unit, [chunk], 1, {})
    audit = build_weekly_partition_candidates(
        plan, capture_root=root, target_root=tmp_path / "formal", year=2020
    )
    path = Path(json.loads(audit.read_text())["files"][0]["candidate"])
    with duckdb.connect() as con:
        load_relation(con, "weekly_input", [path], plan.source)
        load_relation(con, "weekly_existing", [], plan.source)
        assert (
            assemble_relation(con, plan.source, 2020, plan.budget, ())["candidate_rows"]
            == 1
        )
        con.execute("UPDATE weekly_input SET vol=-1")
        with pytest.raises(WeeklyCaptureError, match="raw_key_or_value_invalid"):
            assemble_relation(con, plan.source, 2020, plan.budget, ())
    promote_weekly_candidates(audit, apply=True)


def promote_then_exit(audit, stage):
    import os

    def terminate(current, week):
        if current == stage:
            os._exit(23)

    promote_weekly_candidates(Path(audit), apply=True, fault_probe=terminate)


@pytest.mark.parametrize("stage", ["before_replace", "after_replace"])
def test_process_exit_releases_locks_and_recovers(tmp_path, stage):
    import multiprocessing

    audit, _, _, _ = build(tmp_path)
    process = multiprocessing.get_context("spawn").Process(
        target=promote_then_exit, args=(str(audit), stage)
    )
    process.start()
    process.join(10)
    if process.is_alive():
        process.kill()
        process.join()
        pytest.fail("child did not exit")
    assert process.exitcode == 23
    assert promote_weekly_candidates(audit, apply=True)["status"] == "verified"


def test_budget_rejects_and_wrong_partition(tmp_path):
    audit, target, plan, root = build(tmp_path)
    promote_weekly_candidates(audit, apply=True)
    changed = replace(plan, budget=replace(plan.budget, max_phase_rows=1))
    # Same plan hash with changed budget cannot reopen the frozen capture plan.
    with pytest.raises(WeeklyCaptureError, match="plan_changed"):
        build_weekly_partition_candidates(
            changed,
            capture_root=root,
            target_root=target,
            year=2020,
            partial_scope=True,
        )
    path = partition_path(target, plan.source, "2020-02-28")
    wrong = partition_path(target, plan.source, "2020-03-06")
    wrong.parent.mkdir(parents=True)
    path.rename(wrong)
    with pytest.raises(WeeklyCaptureError, match="target_partition_mismatch"):
        build_weekly_partition_candidates(
            plan, capture_root=root, target_root=target, year=2020, partial_scope=True
        )


def test_cross_device_preflight_writes_no_target(tmp_path, monkeypatch):
    import os

    audit, target, _, _ = build(tmp_path)
    candidate = Path(json.loads(audit.read_text())["files"][0]["candidate"])
    original = Path.stat

    def different_device(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if path == candidate:
            fields = list(result)
            fields[2] += 1
            return os.stat_result(fields)
        return result

    monkeypatch.setattr(Path, "stat", different_device)
    with pytest.raises(WeeklyCaptureError, match="cross_device_promotion_forbidden"):
        promote_weekly_candidates(audit, apply=True)
    assert not target.exists()
    assert candidate.exists()


def test_row_budget_checked_before_merge(tmp_path):
    from orchestrator.defs.io.stock_weekly_raw import assemble_relation, load_relation

    audit, _, plan, _ = build(tmp_path)
    path = Path(json.loads(audit.read_text())["files"][0]["candidate"])
    with duckdb.connect() as con:
        load_relation(con, "weekly_input", [path], plan.source)
        load_relation(con, "weekly_existing", [path], plan.source)
        with pytest.raises(WeeklyCaptureError, match="raw_row_budget_exceeded"):
            assemble_relation(
                con, plan.source, 2020, replace(plan.budget, max_phase_rows=1), ()
            )


def test_validated_receipt_does_not_update_checkpoint(tmp_path):
    from orchestrator.defs.bootstrap.stock_weekly_capture import capture_file_hash

    plan, root = captured(tmp_path)
    checkpoint = next(root.glob("stock_weekly_raw/*/units/*/checkpoint.json"))
    before = capture_file_hash(checkpoint)
    store = WeeklyCaptureStore(root, plan)
    with store.locked(), duckdb.connect() as con:
        path, receipt = store.validated_receipt(con, plan.units[0])
        assert path.exists() and receipt["source_rows"] == 1
    assert capture_file_hash(checkpoint) == before


def test_expected_keys_present_absent_and_mismatched_inventory(tmp_path):
    import hashlib
    from datetime import date

    from orchestrator.defs.run_contracts.stock_weekly import stable_weekly_hash

    from .stock_weekly_capture_test_support import alternate_frame, weekly_plan

    root = tmp_path / "capture"
    root.mkdir()
    inventory = root / "expected.csv"
    inventory.write_text(
        "ts_code,week_key\n000005.SZ,2020-02-28\n000005.SZ,2020-03-06\n"
    )
    proof = root / "proof.json"
    proof.write_text("complete request evidence")
    original = weekly_plan()
    unit = replace(
        original.units[0],
        unit_id="f" * 64,
        anchor_end="2020-03-06",
        request_end=date(2020, 3, 8),
        max_rows=2,
        expected_key_ref=str(inventory),
        expected_key_hash=stable_weekly_hash(["2020-02-28", "2020-03-06"]),
        expected_key_count=2,
        source_evidence=((str(proof), hashlib.sha256(proof.read_bytes()).hexdigest()),),
    )
    plan = replace(
        original,
        units=(unit,),
        evidence_ref=str(inventory),
        evidence_hash=hashlib.sha256(inventory.read_bytes()).hexdigest(),
    )
    store = WeeklyCaptureStore(root, plan)
    with store.locked(), duckdb.connect() as con:
        attempt = store.begin_attempt(unit)
        chunk = store.write_chunk(con, alternate_frame(), unit, attempt, 0)
        store.seal(con, unit, [chunk], 1, {})
    audit = build_weekly_partition_candidates(
        plan, capture_root=root, target_root=tmp_path / "formal", year=2020
    )
    payload = json.loads(audit.read_text())
    assert payload["source_key_outcomes"]["counts"] == {
        "source_key_present": 1,
        "source_key_absent_confirmed": 1,
    }
    with duckdb.connect() as con:
        from orchestrator.defs.bootstrap.stock_weekly_candidates import (
            audit_expected_source_keys,
        )

        con.execute(
            "CREATE TABLE weekly_unique AS SELECT * FROM read_parquet(?,hive_partitioning=false)",
            [payload["files"][0]["candidate"]],
        )
        bad = replace(unit, expected_key_hash="a" * 64)
        with pytest.raises(WeeklyCaptureError, match="expected_key_identity_mismatch"):
            audit_expected_source_keys(con, plan, [bad], audit.parent, 2020)
