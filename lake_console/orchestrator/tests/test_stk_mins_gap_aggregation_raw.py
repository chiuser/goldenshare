"""Isolated Raw merges and atomic promotion of computed missing keys."""

import shutil

import pytest

from orchestrator.defs.bootstrap.stk_mins_gap_aggregation_raw import (
    AggregationRawRun,
    build_raw,
)
from orchestrator.defs.bootstrap.stk_mins_gap_recovery_raw import promote_candidate
from tests.test_stk_mins_gap_aggregation import (
    DAY,
    build_date,
    query,
    row,
    setup,
    write_rows,
)
from tests.test_stk_mins_gap_aggregation import root as isolated_root


@pytest.fixture
def root():
    yield from isolated_root.__wrapped__()


def prepare(root, existing_code="600000.SH"):
    plan, _, _ = setup(root)
    build_date(plan, DAY)
    run = AggregationRawRun(plan, root / "scope.parquet", root / "lake")
    target = run.target(5, DAY)
    target.parent.mkdir(parents=True)
    shutil.copyfile(
        write_rows(root, "old", [row("09:35:00", freq=5, ts_code=existing_code)]),
        target,
    )
    return run, run.selected()[0], target


def test_merge_preserve_promote_replay(root):
    run, file, target = prepare(root)
    old = query(root, target)
    state = build_raw(run, file)
    assert state["repair_rows"] == 49 and state["existing_rows"] == 1
    assert query(root, target) == old
    promote_candidate(run, file)
    assert len(query(root, target)) == 50
    assert old[0] in query(root, target)
    assert promote_candidate(run, file)["status"] == "promoted"
    assert len(query(root, target)) == 50


@pytest.mark.parametrize("code", ["000979.SZ", "000001.SZ"])
def test_existing_and_alias_keys_block(root, code):
    run, file, target = prepare(root, code)
    old = target.read_bytes()
    with pytest.raises(ValueError, match="overlaps"):
        build_raw(run, file)
    assert target.read_bytes() == old


def test_cancel_and_tamper(root):
    run, file, target = prepare(root)
    state = build_raw(run, file)
    with pytest.raises(InterruptedError):
        promote_candidate(run, file, cancelled=lambda: True)
    from pathlib import Path

    Path(state["candidate"]).write_bytes(b"bad")
    with pytest.raises(ValueError, match="changed"):
        promote_candidate(run, file)
    assert len(query(root, target)) == 1


def test_resume_after_replace_before_checkpoint(root, monkeypatch):
    run, file, target = prepare(root)
    build_raw(run, file)
    checkpoint = run.checkpoint

    def fail(kind, key, **values):
        if values.get("status") == "promoted":
            raise RuntimeError("interrupted")
        return checkpoint(kind, key, **values)

    monkeypatch.setattr(run, "checkpoint", fail)
    with pytest.raises(RuntimeError, match="interrupted"):
        promote_candidate(run, file)
    monkeypatch.setattr(run, "checkpoint", checkpoint)
    assert promote_candidate(run, file)["status"] == "promoted"
    assert len(query(root, target)) == 50
