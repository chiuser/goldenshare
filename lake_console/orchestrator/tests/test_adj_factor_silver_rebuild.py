"""LLD25 retires the removal-only migration; frozen historical evidence stays readable."""

import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

import pytest

from orchestrator.defs.bootstrap import adj_factor_silver_history as history
from tests.adj_factor_test_support import (
    isolated_factor_duckdb,
)

pytestmark = pytest.mark.usefixtures(isolated_factor_duckdb.__name__)


@pytest.fixture
def old_plan(tmp_path):
    identity = history.AdjFactorFileFingerprint(str(tmp_path / "old-input.parquet"), 12, 34, "a" * 64)
    plan = history.AdjFactorSilverRebuildPlan(
        lake_root=str(tmp_path / "lake"), listing_as_of_date="2026-10-13", lifecycle=identity,
        raw_inputs=(identity,), source_code=(), units=(),
    )
    # Reproduce the documented serialization contract independently of the loader.
    payload = asdict(plan)
    payload.pop("plan_hash")
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return replace(plan, plan_hash=digest)


def test_removal_only_planning_is_rejected_before_files_or_instance_access(tmp_path):
    before = set(tmp_path.iterdir())
    with patch.object(history, "discover_adj_factor_raw_partition_keys", side_effect=AssertionError("must not scan")), pytest.raises(
        history.AdjFactorSilverRebuildError, match="legacy_current_listed_rebuild_retired",
    ):
        history.plan_silver_adj_factor_rebuild(lake_root=tmp_path, temp_directory=tmp_path / "temp",
                                              instance=object(), listing_as_of_date="2026-10-28")
    assert set(tmp_path.iterdir()) == before


@pytest.mark.parametrize("entry", ["freeze", "build", "promote", "verify", "events"])
def test_all_old_formal_entries_reject_before_io_or_state_writes(old_plan, tmp_path, entry):
    run = tmp_path / "staging" / "run"
    sentinel = tmp_path / "formal.parquet"
    sentinel.write_bytes(b"existing formal bytes")
    commands = {
        "freeze": lambda: history.freeze_silver_adj_factor_rebuild(old_plan, run),
        "build": lambda: history.build_silver_adj_factor_rebuild_candidates(old_plan, run),
        "promote": lambda: history.promote_silver_adj_factor_rebuild(old_plan, run, maintenance_confirmed=True),
        "verify": lambda: history.verify_silver_adj_factor_rebuild(old_plan, run),
        "events": lambda: history.report_silver_adj_factor_rebuild_events(old_plan, run, instance=object(),
                                                                           definitions=object(), maintenance_confirmed=True),
    }
    with pytest.raises(history.AdjFactorSilverRebuildError, match="legacy_current_listed_rebuild_retired"):
        commands[entry]()
    assert sentinel.read_bytes() == b"existing formal bytes"
    assert not run.exists()


def test_old_frozen_plan_is_loadable_as_evidence_without_current_inputs(old_plan, tmp_path):
    run = tmp_path / "staging" / "run"
    run.mkdir(parents=True)
    evidence = run / "plan.json"
    evidence.write_text(json.dumps(asdict(old_plan)))
    before = evidence.read_bytes()
    loaded = history.load_silver_adj_factor_rebuild(run)
    assert loaded == old_plan
    assert evidence.read_bytes() == before
    assert not Path(old_plan.lifecycle.path).exists()
