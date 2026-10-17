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
    # The subprocess producer returns JSON arrays, never Python tuple objects.
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
