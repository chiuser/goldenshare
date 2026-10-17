"""v2 scope and draft recovery. Byte fixtures here test metadata, not business SQL."""

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from orchestrator.defs import paths
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
    FactorRepairError,
    FactorRepairScope,
    file_identity,
    repair_hash,
)
from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_planning import (
    RepairPreparation,
    _year_files,
)


def test_annual_discovery_never_expands_to_other_stocks(tmp_path, monkeypatch):
    selected = paths.gold_stk_mins_qfq_path(tmp_path, 1, "688689.SH", "2026")
    unrelated = paths.gold_stk_mins_qfq_path(tmp_path, 1, "000001.SZ", "2026")
    for p in (selected, unrelated):
        p.parent.mkdir(parents=True)
        p.write_bytes(b"fixture")
    calls = []
    original = Path.glob

    def guarded(path, pattern):
        calls.append((path, pattern))
        assert "ts_code=*" not in pattern
        assert "ts_code=000001.SZ" not in str(path)
        return original(path, pattern)

    monkeypatch.setattr(Path, "glob", guarded)
    # Exact approved range from the independently reviewed 25-stock scope table.
    scope = FactorRepairScope(
        "688689.SH",
        (("2026-06-29", "2026-07-07"),),
        "2026-10-16",
        "2026-10-16",
        "2021-01-27",
    )
    assert _year_files(
        paths.gold_stk_mins_qfq_path, tmp_path, [scope], 1, "2026-10-16"
    ) == (selected,)
    assert len(calls) == 1


def test_preparation_reuses_completed_sql_and_one_strong_identity(
    tmp_path, monkeypatch
):
    import orchestrator.defs.bootstrap.stock_adj_factor_history_repair_planning as module

    source = tmp_path / "source"
    source.write_bytes(b"independent source bytes")
    # Persisted preparation records contain JSON arrays, not Python tuples.
    st = source.stat()
    result = {
        "input_paths": [str(source)],
        "profile_input_stats": [[str(source), st.st_size, st.st_mtime_ns]],
    }
    root = tmp_path / "run_id=11111111-1111-4111-8111-111111111111"
    calls = []
    hashes = []
    original = module.file_identity
    monkeypatch.setattr(
        module, "file_identity", lambda p, **kw: hashes.append(p) or original(p, **kw)
    )
    draft = RepairPreparation(
        root, request={"stocks": ["688689.SH"]}, implementation=[]
    )
    for name in ("profile:daily", "profile:1"):
        assert (
            draft.unit(name, {}, lambda name=name: calls.append(name) or result)
            == result
        )
    assert hashes == [source]
    resumed = RepairPreparation(
        root, request={"stocks": ["688689.SH"]}, implementation=[]
    )
    for name in ("profile:daily", "profile:1"):
        assert (
            resumed.unit(name, {}, lambda: pytest.fail("completed SQL repeated"))
            == result
        )
    assert len(calls) == 2 and hashes == [source]
    sealed = resumed.seal([])
    assert sealed["identities"][str(source)] == asdict(file_identity(source))
    assert sealed["source_hash"] == repair_hash([])


@pytest.mark.parametrize(
    "fault", ["request", "implementation", "input", "unknown", "record", "cancel"]
)
def test_preparation_rejects_wrong_owner_drift_and_unknown_artifacts(tmp_path, fault):
    source = tmp_path / "source"
    source.write_bytes(b"original")
    root = tmp_path / "run_id=11111111-1111-4111-8111-111111111111"
    draft = RepairPreparation(root, request={"scope": "approved"}, implementation=[])
    st = source.stat()
    draft.unit(
        "profile:daily",
        {},
        lambda: {
            "input_paths": [str(source)],
            "profile_input_stats": [(str(source), st.st_size, st.st_mtime_ns)],
        },
    )
    with pytest.raises(FactorRepairError):
        if fault == "request":
            RepairPreparation(root, request={"scope": "other"}, implementation=[])
        elif fault == "implementation":
            RepairPreparation(
                root,
                request={"scope": "approved"},
                implementation=[{"different": True}],
            )
        elif fault == "input":
            source.write_bytes(b"changed input")
            draft.unit("profile:daily", {}, lambda: pytest.fail("must not run"))
        elif fault == "unknown":
            (root / "unknown-zero-byte").touch()
            draft.seal([])
        elif fault == "record":
            record = next(
                p for p in draft.directory.glob("*.json") if p.name != "request.json"
            )
            record.write_text("{}")
            draft.unit("profile:daily", {}, lambda: pytest.fail("must not run"))
        else:
            draft.unit(
                "new",
                {},
                lambda: pytest.fail("cancelled unit started"),
                cancel=lambda: True,
            )


@pytest.mark.parametrize("fault", ["version", "scope", "preparation", "foreign_annual"])
def test_v2_rehashed_contract_cannot_adopt_old_or_out_of_scope_inventory(
    freeze_case, fault
):
    from copy import deepcopy

    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
        freeze_stock_factor_repair,
        validate_repair_plan,
    )

    args, _ = freeze_case
    plan = deepcopy(freeze_stock_factor_repair(**args))
    if fault == "version":
        plan["version"] = 1
    elif fault == "scope":
        plan.pop("validation_scope")
    elif fault == "preparation":
        plan["preparation_binding"]["implementation_hash"] = "0" * 64
    else:
        foreign = paths.gold_stk_mins_qfq_path(
            args["lake_root"], 1, "000001.SZ", "2026"
        )
        plan["source_fingerprints"].append(
            {"path": str(foreign), "size": 1, "mtime_ns": 1, "sha256": "0" * 64}
        )
        # Even a consistently rehashed dependency declaration cannot broaden the
        # approved stocks. This is an intentionally invalid metadata-only input.
        from orchestrator.defs.bootstrap.stock_adj_factor_history_repair import (
            repair_scope_contract,
        )

        dependency, proof = repair_scope_contract(
            args["scopes"], plan["units"], plan["source_fingerprints"]
        )
        plan.update(dependency_scope=dependency, validation_scope=proof)
        plan["preparation_binding"]["dependency_hash"] = repair_hash(dependency)
    plan.pop("plan_hash")
    plan["plan_hash"] = repair_hash(plan)
    with pytest.raises(FactorRepairError):
        validate_repair_plan(plan, plan["plan_hash"])


# Shared fixture builds only temporary metadata files, never an executable
# 31-asset calculation. Real schema/price integration is tested in promotion.
from . import test_stock_adj_factor_history_repair as contracts

freeze_case = contracts.freeze_case
repair_endpoints = contracts.repair_endpoints
scope = contracts.scope


def test_existing_plan_budget_is_checked_before_json_read(freeze_case, monkeypatch):
    from orchestrator.defs.bootstrap import (
        stock_adj_factor_history_repair_planning as module,
    )
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_promotion import (
        repair_writer_lock,
    )

    args, _ = freeze_case
    root = args["run_root"]
    monkeypatch.setattr(paths, "DEFAULT_LAKE_ROOT", str(args["lake_root"]))
    root.mkdir(parents=True)
    path = root / "plan.json"
    with path.open("wb") as handle:
        handle.truncate(module.REPAIR_PLAN_MAX_BYTES + 1)  # Sparse, intentionally invalid input.
    monkeypatch.setattr(Path, "read_text", lambda *a, **kw: pytest.fail("oversized plan parsed"))
    with repair_writer_lock(root) as lock, pytest.raises(FactorRepairError, match="plan_size_exceeded"):
        module.prepare_scoped_repair_inputs(root=root, scopes=args["scopes"],
            source=None, parent_lock=lock)


@pytest.mark.parametrize("interrupted_source", [False, True])
def test_real_freeze_cli_reuses_preparation_and_holds_lock_through_plan(
    freeze_case, monkeypatch, interrupted_source, capsys
):
    """Real CLI/preparation/freeze; source and SQL metadata are explicit substitutes.

    This exercises the API boundary, not formula or actual lake-data acceptance.
    Source fields and pagination parameters follow fetch_current_factor_rows;
    the independent approved metadata fixture is validated by the real freezer.
    """
    from contextlib import contextmanager
    from types import SimpleNamespace

    from orchestrator.defs import resources
    from orchestrator.defs.bootstrap import stock_adj_factor_history_repair_cli as cli
    from orchestrator.defs.bootstrap import (
        stock_adj_factor_history_repair_planning as planning,
    )
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_promotion import (
        repair_writer_lock,
    )

    args, _ = freeze_case
    calls, failed, reads = [], [], []
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.delenv("DAGSTER_HOME", raising=False)
    root = args["run_root"]
    codes = [s.ts_code for s in args["scopes"]]
    class Source:
        def call(self, api, params, fields):
            assert api == "adj_factor" and tuple(fields) == ("ts_code", "trade_date", "adj_factor")
            assert params["limit"] == 6000 and params["offset"] == 0
            assert params["ts_code"] in codes
            calls.append(dict(params))
            if interrupted_source and params["ts_code"] == codes[1] and not failed:
                failed.append(True)
                raise ConnectionError("isolated source interruption")
            if "trade_date" in params:
                row = next(a for a in args["anchors"] if a["ts_code"] == params["ts_code"])
                rows = [{**row, "trade_date": row["trade_date"].replace("-", "")}]
            else:
                rows = [r for r in args["source_rows"] if r["ts_code"] == params["ts_code"]]
            return SimpleNamespace(columns=tuple(fields), rows=rows)

    monkeypatch.setattr(resources, "TushareResource", lambda **kwargs: Source())
    monkeypatch.setattr(paths, "DEFAULT_LAKE_ROOT", str(args["lake_root"]))
    @contextmanager
    def readonly():
        reads.append(True)
        partition = args["partition_validation"]
        yield SimpleNamespace(get_dynamic_partitions=lambda name: (
            partition["registered_keys"] if name == partition["partition_set"]
            else partition["indicator_sets"][name]))
    monkeypatch.setattr(cli, "_readonly_instance", readonly)
    observed = {
        "profiles": [asdict(e) for e in args["endpoints"]], "stop_reasons": [],
        "target_paths": args["target_paths"], "input_paths": [r[0] for r in args["input_stats"]],
        "inventory": {"files": args["input_stats"]},
    }
    def inspection(*a, **kwargs):
        with pytest.raises(FactorRepairError, match="writer_busy"), repair_writer_lock(root):
            pytest.fail("prepare released capability lock")
        return observed
    monkeypatch.setattr(planning, "run_repair_inspection", inspection)
    monkeypatch.setattr(cli, "repair_units_from_inspection", lambda *a, **kw: args["units"])
    real_freeze = cli.freeze_stock_factor_repair
    def freeze(**kwargs):
        assert "writer_guard" not in kwargs
        with pytest.raises(FactorRepairError, match="writer_busy"), repair_writer_lock(root):
            pytest.fail("lock released before plan freeze")
        return real_freeze(**kwargs)
    monkeypatch.setattr(cli, "freeze_stock_factor_repair", freeze)
    command = ["freeze", "--as-of", args["scopes"][0].as_of_trade_date,
        "--end", args["scopes"][0].repair_end_trade_date, "--daily-basis-start", "2021-01-27",
        "--run-root", str(root), "--maintenance-confirmed"]
    for sc in args["scopes"]:
        command.extend(["--scope", f"{sc.ts_code}:{sc.factor_ranges[0][0]}:{sc.factor_ranges[0][1]}"])
    if interrupted_source:
        with pytest.raises(ConnectionError, match="source interruption"):
            cli.main(command)
        assert not (root / "plan.json").exists()
    assert cli.main(command) == 0
    plan_bytes = (root / "plan.json").read_bytes()
    assert len(calls) == (51 if interrupted_source else 50)
    assert len([p for p in calls if p["ts_code"] == codes[0]]) == 2
    assert cli.main(command) == 0
    assert (root / "plan.json").read_bytes() == plan_bytes
    assert len(calls) == (51 if interrupted_source else 50) and reads == [True]
    assert "maintenance_window" not in json.loads(plan_bytes)
    capsys.readouterr()
    plan = json.loads(plan_bytes)
    (root / "checkpoint.json").write_text(json.dumps({"promotion": {
        "status": "PROMOTING", "plan_hash": plan["plan_hash"]}}))
    assert cli.main(command) == 0
    observed = json.loads(capsys.readouterr().out)
    assert observed["status"] == "PROMOTING" and observed["next_action"] == "promote"
    assert (root / "plan.json").read_bytes() == plan_bytes
    assert len(calls) == (51 if interrupted_source else 50) and reads == [True]


@pytest.fixture
def saved_source_case(tmp_path, monkeypatch):
    """Literal source rows and record shape follow the saved 2026-10-18 producer.

    Only the temporary roots are substituted; record reading and SQL are real.
    """
    import hashlib

    from orchestrator.defs.bootstrap import stock_adj_factor_history_repair as contract

    lake = tmp_path / "lake"
    staging = tmp_path / "staging"
    lake.mkdir()
    staging.mkdir()
    monkeypatch.setattr(paths, "DEFAULT_LAKE_ROOT", str(lake))
    monkeypatch.setattr(contract, "DEFAULT_LAKE_ROOT", str(lake))
    monkeypatch.setattr(contract, "DEFAULT_LAKE_STAGING_ROOT", str(staging))
    old = staging / "stock_adj_factor_history_repair/run_id=11111111-1111-4111-8111-111111111111"
    new = old.with_name("run_id=22222222-2222-4222-8222-222222222222")
    sc = FactorRepairScope("001331.SZ", (("2026-06-26", "2026-06-29"),),
                           "2026-10-16", "2026-10-16")
    rows = [{"ts_code": "001331.SZ", "trade_date": d, "adj_factor": "1.25"}
            for d in ("20260626", "20260629")]
    anchor = {"ts_code": "001331.SZ", "trade_date": "2026-10-16", "adj_factor": 1.25}
    marker = {"version": 2, "run_id": old.name.removeprefix("run_id="),
              "request_hash": repair_hash({"scopes": [asdict(sc)]}),
              "implementation_hash": "a" * 64}
    directory = old / "checkpoints/preparation"
    directory.mkdir(parents=True)
    (directory / "request.json").write_text(json.dumps(marker))
    for name, request, result in (
        ("source:001331.SZ", asdict(sc), rows),
        ("anchor:001331.SZ", {"ts_code": "001331.SZ", "trade_date": "20261016",
                              "limit": 6000, "offset": 0}, anchor),
    ):
        record = {**marker, "unit": name, "unit_request_hash": repair_hash(request),
                  "result": result, "identities": []}
        record["record_hash"] = repair_hash(record)
        (directory / (hashlib.sha256(name.encode()).hexdigest() + ".json")).write_text(json.dumps(record))
    return lake, old, new, sc, rows, anchor


def make_factor_inputs(lake, rows, anchors):
    """Real minimal Parquet producer, using current factor/lifecycle/date contracts.

    Existing Raw and Silver factors are independently set 0.125 above source;
    all supplied keys must be reported changed. No prices/formulas are tested.
    """
    import duckdb

    from orchestrator.defs.duckdb_sql import copy_query_to_parquet

    def copy(con, query, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        con.execute(copy_query_to_parquet(query, path))

    with duckdb.connect() as con:
        con.execute("CREATE TABLE factors(ts_code VARCHAR,trade_date VARCHAR,adj_factor DOUBLE)")
        con.executemany("INSERT INTO factors VALUES (?,?,?)", [
            (r["ts_code"], r["trade_date"], float(r["adj_factor"]) + 0.125) for r in rows])
        for day in sorted({r["trade_date"] for r in rows}):
            iso = f"{day[:4]}-{day[4:6]}-{day[6:]}"
            copy(con, f"SELECT * FROM factors WHERE trade_date='{day}'", paths.raw_adj_factor_path(lake, iso))
            copy(con, f"SELECT ts_code,strptime(trade_date,'%Y%m%d')::DATE trade_date,adj_factor FROM factors WHERE trade_date='{day}'",
                 paths.silver_adj_factor_path(lake, iso))
        con.execute("CREATE TABLE anchors(ts_code VARCHAR,trade_date DATE,adj_factor DOUBLE)")
        con.executemany("INSERT INTO anchors VALUES (?,?,?)", [
            (r["ts_code"], r["trade_date"], float(r["adj_factor"])) for r in anchors])
        for day in sorted({r["trade_date"] for r in anchors}):
            copy(con, f"SELECT * FROM anchors WHERE trade_date=DATE '{day}'", paths.silver_adj_factor_path(lake, day))
        copy(con, "SELECT DISTINCT ts_code,DATE '2000-01-01' list_date,NULL::DATE delist_date,TRUE is_cny_stock,'L' list_status FROM factors",
             paths.silver_stock_lifecycle_path(lake))
        copy(con, "SELECT DATE '2026-10-16' trade_date,TRUE is_open,'SSE' exchange",
             paths.silver_trade_calendar_path(lake))


def test_saved_rows_go_through_real_factor_preparation_in_same_process(saved_source_case, tmp_path, monkeypatch):
    import os

    from orchestrator.defs.bootstrap import (
        stock_adj_factor_history_repair_planning as module,
    )

    lake, old, _, sc, rows, anchor = saved_source_case
    before = {p: p.read_bytes() for p in old.rglob("*.json")}
    saved = module.read_saved_repair_sources(old, [sc])
    assert saved["source:001331.SZ"][0] == rows
    assert saved["anchor:001331.SZ"][0] == anchor
    make_factor_inputs(lake, rows, [anchor])
    monkeypatch.setattr(module, "DEFAULT_DUCKDB_TEMP_DIRECTORY", tmp_path)
    # The real dispatcher and SQL run, not a precomputed inspection result.
    seen = []
    result = module.run_repair_preparation_phase("factor", {
        "scopes": [asdict(sc)], "source_rows": rows, "anchors": [anchor]},
        progress=lambda p: seen.append((os.getpid(), p)))
    assert result["source_rows"] == result["changed_factor_keys"] == 2
    assert result["factor_days"] == ["2026-06-26", "2026-06-29"]
    assert len(result["factor_files"]) == 4 and result["completed_sql"] > 0
    assert seen and all(pid == os.getpid() for pid, _ in seen)
    assert seen[-1][1]["completed_sql"] == result["completed_sql"]
    assert "peak_rss_bytes" not in result and not hasattr(module, "subprocess")
    assert {p: p.read_bytes() for p in before} == before


@pytest.mark.parametrize("fault", ["missing", "hash", "code", "date", "fields", "request"])
def test_saved_source_error_is_rejected_without_source_request(saved_source_case, fault):
    from orchestrator.defs.bootstrap import (
        stock_adj_factor_history_repair_planning as module,
    )

    _, old, _, sc, _, _ = saved_source_case
    path = next(p for p in (old / "checkpoints/preparation").glob("*.json")
                if p.name != "request.json" and json.loads(p.read_text())["unit"].startswith("source:"))
    record = json.loads(path.read_text())
    if fault == "missing":
        path.unlink()
    else:
        if fault == "hash":
            record["result"][0]["adj_factor"] = "99"
        elif fault == "code":
            record["result"][0]["ts_code"] = "000001.SZ"
        elif fault == "date":
            record["result"][0]["trade_date"] = "20260625"
        elif fault == "fields":
            record["result"][0]["extra"] = "invalid"
        else:
            record["unit_request_hash"] = "0" * 64
        if fault != "hash":
            record["record_hash"] = repair_hash({k: v for k, v in record.items() if k != "record_hash"})
        path.write_text(json.dumps(record))
    with pytest.raises((FactorRepairError, FileNotFoundError)):
        module.read_saved_repair_sources(old, [sc])


def test_preparation_import_records_keep_origin_and_resume_without_network(saved_source_case, monkeypatch):
    from orchestrator.defs.bootstrap import (
        stock_adj_factor_history_repair_planning as module,
    )
    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_promotion import (
        repair_writer_lock,
    )

    _, old, new, sc, rows, _ = saved_source_case
    # This is a source-persistence/cancellation test, not a 31-asset SQL test.
    monkeypatch.setattr(module, "repair_implementation_files", list)
    calls = []
    def stop_at_first_profile(*args, **kwargs):
        calls.append(True)
        raise FactorRepairError("canceled")
    with repair_writer_lock(new) as lock:
        for _ in range(2):
            with pytest.raises(FactorRepairError, match="canceled"):
                module.prepare_scoped_repair_inputs(root=new, scopes=[sc], source=None,
                    source_root=old, parent_lock=lock, run_phase=stop_at_first_profile)
    records = [json.loads(p.read_text()) for p in (new / "checkpoints/preparation").glob("*.json")
               if p.name != "request.json"]
    assert len(records) == 2 and len(calls) == 2
    assert {r["unit"] for r in records} == {"source:001331.SZ", "anchor:001331.SZ"}
    for record in records:
        origin = record["source_origin"]
        original = json.loads(Path(origin["path"]).read_text())
        assert original["record_hash"] == origin["record_hash"]
        assert record["result"] == original["result"]
        assert record["implementation_hash"] != original["implementation_hash"]
    assert next(r["result"] for r in records if r["unit"].startswith("source:")) == rows
    with repair_writer_lock(new):
        pass


def test_slow_sql_does_not_have_a_point_one_second_deadline():
    import time

    import duckdb

    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_planning import (
        RepairInspectionConnection,
    )

    with duckdb.connect() as con:
        def slow_value() -> int:
            time.sleep(0.25)
            return 42
        con.create_function("slow_value", slow_value)
        progress = []
        started = time.monotonic()
        result = RepairInspectionConnection(con, "slow", progress.append).execute("SELECT slow_value()").fetchone()
        assert result == (42,) and time.monotonic() - started >= 0.25
        assert progress[-1]["completed_sql"] == 1


def test_cancel_interrupts_real_sql_and_does_not_leave_it_running():
    import threading

    import duckdb

    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_planning import (
        RepairInspectionConnection,
    )

    cancel = threading.Event()
    timer = threading.Timer(0.2, cancel.set)
    with duckdb.connect() as con:
        timer.start()
        try:
            with pytest.raises(FactorRepairError, match="canceled"):
                RepairInspectionConnection(con, "cancel", None, cancel.is_set).execute(
                    "SELECT sum(sin(i)) FROM range(1000000000) t(i)")
        finally:
            timer.cancel()
            timer.join()
        assert con.execute("SELECT 42").fetchone() == (42,)


def test_removed_preparation_worker_entry_cannot_start(monkeypatch):
    from orchestrator.defs.bootstrap import stock_adj_factor_history_repair_cli as cli
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.delenv("DAGSTER_HOME", raising=False)
    with pytest.raises(SystemExit) as error:
        cli.main(["_inspect_worker", "factor"])
    assert error.value.code == 2


def test_term_releases_lock_and_saved_sql_result_can_resume(tmp_path):
    import select
    import signal
    import subprocess
    import sys
    import textwrap

    import duckdb

    from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_promotion import (
        repair_writer_lock,
    )

    root = tmp_path / "stock_adj_factor_history_repair/run_id=33333333-3333-4333-8333-333333333333"
    script = textwrap.dedent(f"""
        import sys
        from pathlib import Path
        import duckdb
        from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_planning import RepairPreparation, RepairInspectionConnection
        from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_execution import repair_coordinator_termination_guard
        from orchestrator.defs.bootstrap.stock_adj_factor_history_repair_promotion import repair_writer_lock
        root = Path({str(root)!r})
        try:
            with repair_coordinator_termination_guard(), repair_writer_lock(root), duckdb.connect() as con:
                db = RepairInspectionConnection(con, 'term', None)
                draft = RepairPreparation(root, request={{'test': 'TERM'}}, implementation=[])
                draft.unit('profile:done', {{}}, lambda: {{'value': db.execute('SELECT 42').fetchone()[0]}})
                print('SAVED', flush=True)
                draft.unit('profile:pending', {{}}, lambda: {{'value': db.execute('SELECT sum(sin(i)) FROM range(1000000000) t(i)').fetchone()[0]}})
        except KeyboardInterrupt:
            sys.exit(130)
    """)
    child = subprocess.Popen([sys.executable, "-B", "-c", script], text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert select.select([child.stdout], [], [], 5)[0], "preparation did not save first result"
        assert child.stdout.readline().strip() == "SAVED"
        child.send_signal(signal.SIGTERM)  # Only this test's owned process.
        stdout, stderr = child.communicate(timeout=5)
        assert child.returncode == 130, (stdout, stderr)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
    with repair_writer_lock(root), duckdb.connect() as con:
        draft = RepairPreparation(root, request={"test": "TERM"}, implementation=[])
        assert draft.unit("profile:done", {}, lambda: pytest.fail("saved SQL repeated")) == {"value": 42}
        assert draft.unit("profile:pending", {}, lambda: {"value": con.execute("SELECT 43").fetchone()[0]}) == {"value": 43}
        assert len(draft.seal([])["artifacts"]) == 3


def test_inspect_progress_consumer_does_not_require_removed_memory_fields(monkeypatch, capsys):
    """Only the CLI progress consumer is isolated here, not real SQL acceptance."""
    from types import SimpleNamespace

    from orchestrator.defs import resources
    from orchestrator.defs.bootstrap import stock_adj_factor_history_repair_cli as cli

    class Source:
        def call(self, api, params, fields):
            rows = [{"ts_code": "001331.SZ", "trade_date": d, "adj_factor": 1.25}
                    for d in ([params["trade_date"]] if "trade_date" in params else ["20260626", "20260629"])]
            return SimpleNamespace(columns=fields, rows=rows)

    def inspection(payload, *, progress):
        progress("factor", {"elapsed_seconds": 0.25, "completed_sql": 1})
        return {"stop_reasons": []}

    monkeypatch.setattr(resources, "TushareResource", lambda **kwargs: Source())
    monkeypatch.setattr(cli, "run_repair_inspection", inspection)
    assert cli.main(["inspect", "--scope", "001331.SZ:2026-06-26:2026-06-29",
                     "--as-of", "2026-10-16", "--end", "2026-10-16"]) == 0
    output = capsys.readouterr()
    assert json.loads(output.err.splitlines()[-1])["completed_sql"] == 1
    assert "peak_rss" not in output.err
