"""Window evidence and cancellation regressions against temporary real producers.

The dates, counts and intentionally damaged records below follow LLD §15.4.
Source calls are replaced; capture/build/promote and the asset wrapper remain real.
"""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import dagster as dg
import pytest

from orchestrator.defs.anns_d_checkpoint import AnnouncementWindowBudget
from orchestrator.defs.anns_d_contract import (
    ANNOUNCEMENT_FIELDS,
    AnnouncementCancelled,
    AnnouncementError,
)
from orchestrator.defs.anns_d_window import (
    announcement_restore_window_tags,
    announcement_window_tags,
)
from orchestrator.defs.resources import LakeRootResource, TushareResource
from orchestrator.defs.run_contracts.anns_d import AnnouncementRawConfig
from tests.anns_d_test_support import archive as _archive_fixture
from tests.test_anns_d_window import run_window, state_for

archive = _archive_fixture
DAYS = ("2023-06-08", "2023-06-09", "2023-06-10")


def _execution_paths(archive, window_id):
    directory = archive.staging / "anns_d" / "windows" / window_id
    return directory / "execution.json", directory / "budget.json"


def _write_test_record(path, document):
    """Deliberate mutation of this test's small temporary evidence only."""
    path.write_text(json.dumps(document))


def _empty_source(calls):
    def call(params, control):
        calls.append(params["ann_date"])
        return [], ANNOUNCEMENT_FIELDS

    return call


def test_conflicting_day_fingerprint_never_replaces_original_window_proof(
    archive, monkeypatch
):
    import orchestrator.defs.anns_d_window as window

    day, calls = DAYS[0], []
    tags = announcement_window_tags("conflicting-proof", day, day)
    run_window(archive, (day,), tags, _empty_source(calls))
    original = state_for(archive, "conflicting-proof")["days"][day]
    # Independent file fingerprint, not an expected value from the window helper.
    target = archive.target(day)
    expected = {
        "size": target.stat().st_size,
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    }
    assert original["fingerprint"] == expected
    checkpoint_path = Path(original["checkpoint"])
    checkpoint = json.loads(checkpoint_path.read_text())
    # A valid JSON shape with a conflicting digest is intentionally corrupt evidence.
    checkpoint["delivery"]["fingerprint"] = {"size": 13, "sha256": "0" * 64}
    _write_test_record(checkpoint_path, checkpoint)
    damaged_bytes = checkpoint_path.read_bytes()
    monkeypatch.setattr(
        window, "announcement_file_fingerprint",
        lambda *_: pytest.fail("existing window proof was unnecessarily rehashed"),
    )

    for _ in range(2):
        with pytest.raises(AnnouncementError, match="delivery_missing"):
            run_window(
                archive, (day,), tags, None,
                factory=lambda *_: pytest.fail("conflicting evidence requested source"),
            )
        record = state_for(archive, "conflicting-proof")["days"][day]
        assert record["phase"] == "promoted"
        assert record["fingerprint"] == expected
        assert record["checkpoint"] == original["checkpoint"]
        assert checkpoint_path.read_bytes() == damaged_bytes
    assert calls == ["20230608"]


@pytest.mark.parametrize("damage", ["identity", "pages", "fingerprint", "target"])
def test_new_window_fact_cannot_be_recovered_from_invalid_promoted_evidence(
    archive, damage
):
    tags = announcement_window_tags("invalid-new-proof", DAYS[0], DAYS[1])
    calls = []

    def emit(event):
        if event.get("phase") != "promoted":
            return
        # This is the real producer's checkpoint, before the window records promotion.
        paths = list((archive.staging / "anns_d").glob("run_id=*/delivery.json"))
        assert len(paths) == 1
        checkpoint_path = paths[0]
        checkpoint = json.loads(checkpoint_path.read_text())
        if damage == "identity":
            checkpoint["identity"]["window_id"] = "another-window"
        elif damage == "pages":
            del checkpoint["delivery"]["source_pages"]
        elif damage == "fingerprint":
            checkpoint["delivery"]["fingerprint"]["sha256"] = "not-a-sha256"
        else:
            archive.target(DAYS[0]).write_bytes(b"changed after the real commit")
        _write_test_record(checkpoint_path, checkpoint)
        # Its source-shaped reason must not make damaged shared evidence skippable.
        raise AnnouncementError("announcement_source_timeout")

    archive.control.emit = emit
    with pytest.raises(AnnouncementError, match="identity|incomplete|file_changed"):
        run_window(archive, DAYS[:2], tags, _empty_source(calls))
    state = state_for(archive, "invalid-new-proof")
    assert state["phase"] == "failed" and state["files_completed"] == []
    assert "fingerprint" not in state["days"][DAYS[0]]
    assert state["unattempted_days"] == ["2023-06-09"]
    assert calls == ["20230608"]
    assert not archive.target(DAYS[1]).exists()


def test_new_promoted_fact_uses_one_target_sha_and_then_resumes_without_source(
    archive, monkeypatch
):
    import orchestrator.defs.anns_d_window as window

    day, calls, hashes = DAYS[0], [], []
    tags = announcement_window_tags("valid-new-proof", day, day)
    original = window.announcement_file_fingerprint

    def fingerprint(path):
        hashes.append(path)
        return original(path)

    def emit(event):
        if event.get("phase") == "promoted":
            raise RuntimeError("the day committed before window progress")

    monkeypatch.setattr(window, "announcement_file_fingerprint", fingerprint)
    archive.control.emit = emit
    with pytest.raises(RuntimeError, match="day committed"):
        run_window(archive, (day,), tags, _empty_source(calls))
    state = state_for(archive, "valid-new-proof")
    assert state["files_completed"] == [day]
    assert hashes == [archive.target(day)]
    archive.control.emit = lambda _: None
    run_window(
        archive, (day,), tags, None,
        factory=lambda *_: pytest.fail("recovered committed file requested source"),
    )
    assert hashes == [archive.target(day)]
    assert calls == ["20230608"]
    assert "failure_phase" not in state_for(archive, "valid-new-proof")["days"][day]


@pytest.mark.parametrize("regression", ["total", "per_day"])
def test_budget_regression_fails_before_either_evidence_file_is_written(
    archive, monkeypatch, regression
):
    tags = announcement_window_tags("budget-regression", DAYS[0], DAYS[-1])
    calls = []
    run_window(archive, DAYS, tags, _empty_source(calls))
    execution_path, budget_path = _execution_paths(archive, "budget-regression")
    document = json.loads(budget_path.read_text())
    assert document["requests"] == 3
    assert document["day_requests"] == {day: 1 for day in DAYS}
    if regression == "total":
        document.update(requests=0, day_requests={})
    else:
        # The total is still 3 and all values are legal, but June 8 lost one claim.
        document["day_requests"] = {
            "2023-06-08": 0, "2023-06-09": 2, "2023-06-10": 1,
        }
    _write_test_record(budget_path, document)
    before = (execution_path.read_bytes(), budget_path.read_bytes())
    monkeypatch.setattr(
        AnnouncementWindowBudget, "recover_interrupted",
        lambda *_: pytest.fail("regressed budget reached request recovery"),
    )

    with pytest.raises(AnnouncementError, match="budget"):
        announcement_restore_window_tags(
            "budget-regression", DAYS[0], DAYS[-1], archive.staging, archive.policy
        )
    assert (execution_path.read_bytes(), budget_path.read_bytes()) == before
    with pytest.raises(AnnouncementError, match="budget"):
        run_window(
            archive, DAYS, tags, None,
            factory=lambda *_: pytest.fail("regressed budget requested source"),
        )
    assert (execution_path.read_bytes(), budget_path.read_bytes()) == before
    assert calls == ["20230608", "20230609", "20230610"]


@pytest.mark.parametrize("damage", ["bool", "unknown_day", "sum", "missing", "partial"])
def test_invalid_execution_counts_cannot_be_overwritten_from_budget(archive, damage):
    day = DAYS[0]
    tags = announcement_window_tags("invalid-execution-counts", day, day)
    run_window(archive, (day,), tags, _empty_source([]))
    execution_path, budget_path = _execution_paths(archive, "invalid-execution-counts")
    document = json.loads(execution_path.read_text())
    if damage == "bool":
        document["requests"] = True
    elif damage == "unknown_day":
        document["day_requests"] = {"2023-06-09": 1}
    elif damage == "sum":
        document["requests"] = 0
    elif damage == "missing":
        del document["requests"], document["day_requests"]
    else:
        del document["requests"]
    _write_test_record(execution_path, document)
    before = (execution_path.read_bytes(), budget_path.read_bytes())
    with pytest.raises(AnnouncementError, match="budget|checkpoint"):
        announcement_restore_window_tags(
            "invalid-execution-counts", day, day, archive.staging, archive.policy
        )
    assert (execution_path.read_bytes(), budget_path.read_bytes()) == before
    with pytest.raises(AnnouncementError, match="budget|checkpoint"):
        run_window(
            archive, (day,), tags, None,
            factory=lambda *_: pytest.fail("invalid execution counts requested source"),
        )
    assert (execution_path.read_bytes(), budget_path.read_bytes()) == before


def _stop_after_initialization(archive, monkeypatch, tags):
    import orchestrator.defs.anns_d_window as window

    original = window._save_execution

    def stop(*_):
        raise RuntimeError("initialized before progress")

    monkeypatch.setattr(window, "_save_execution", stop)
    with pytest.raises(RuntimeError, match="initialized before progress"):
        run_window(
            archive, (DAYS[0],), tags, None,
            factory=lambda *_: pytest.fail("initialization requested source"),
        )
    monkeypatch.setattr(window, "_save_execution", original)


def test_budget_may_lead_execution_and_in_flight_claim_is_not_refunded(
    archive, monkeypatch
):
    day, calls = DAYS[0], []
    tags = announcement_window_tags("budget-ahead", day, day)
    _stop_after_initialization(archive, monkeypatch, tags)
    execution_path, budget_path = _execution_paths(archive, "budget-ahead")
    document = json.loads(execution_path.read_text())
    # Literal zero summary models a persisted claim before the next outer summary.
    document.update(requests=0, day_requests={})
    _write_test_record(execution_path, document)
    budget = AnnouncementWindowBudget(
        budget_path, "budget-ahead", archive.policy,
        identity=document["identity"], require_existing=True,
    )
    assert budget.claim(archive.control, day) == 1
    assert json.loads(budget_path.read_text())["in_flight"] is True
    before = (execution_path.read_bytes(), budget_path.read_bytes())
    assert announcement_restore_window_tags(
        "budget-ahead", day, day, archive.staging, archive.policy
    ) == tags
    assert (execution_path.read_bytes(), budget_path.read_bytes()) == before

    run_window(archive, (day,), tags, _empty_source(calls))
    state = state_for(archive, "budget-ahead")
    assert calls == ["20230608"]
    assert state["requests"] == 2 and state["day_requests"] == {day: 2}
    assert json.loads(budget_path.read_text())["in_flight"] is False


def test_zero_initialization_with_both_legacy_summary_fields_absent_can_resume(
    archive, monkeypatch
):
    day = DAYS[0]
    tags = announcement_window_tags("zero-initialization", day, day)
    _stop_after_initialization(archive, monkeypatch, tags)
    execution_path, budget_path = _execution_paths(archive, "zero-initialization")
    document = json.loads(execution_path.read_text())
    assert document["phase"] == "planned"
    assert document["days"] == {day: {"phase": "planned"}}
    # The original version-2 initializer omitted both fields at this exact boundary.
    document.pop("requests", None)
    document.pop("day_requests", None)
    _write_test_record(execution_path, document)
    assert json.loads(budget_path.read_text())["requests"] == 0
    before = (execution_path.read_bytes(), budget_path.read_bytes())
    assert announcement_restore_window_tags(
        "zero-initialization", day, day, archive.staging, archive.policy
    ) == tags
    assert (execution_path.read_bytes(), budget_path.read_bytes()) == before
    run_window(archive, (day,), tags, _empty_source([]))
    assert state_for(archive, "zero-initialization")["requests"] == 1


def test_absent_initial_counts_cannot_hide_an_already_consumed_claim(
    archive, monkeypatch
):
    day = DAYS[0]
    tags = announcement_window_tags("consumed-initialization", day, day)
    _stop_after_initialization(archive, monkeypatch, tags)
    execution_path, budget_path = _execution_paths(archive, "consumed-initialization")
    document = json.loads(execution_path.read_text())
    document.pop("requests", None)
    document.pop("day_requests", None)
    _write_test_record(execution_path, document)
    budget = AnnouncementWindowBudget(
        budget_path, "consumed-initialization", archive.policy,
        identity=document["identity"], require_existing=True,
    )
    budget.claim(archive.control, day)
    before = (execution_path.read_bytes(), budget_path.read_bytes())
    with pytest.raises(AnnouncementError, match="checkpoint"):
        announcement_restore_window_tags(
            "consumed-initialization", day, day, archive.staging, archive.policy
        )
    with pytest.raises(AnnouncementError, match="checkpoint"):
        run_window(
            archive, (day,), tags, None,
            factory=lambda *_: pytest.fail("missing counters requested source"),
        )
    assert (execution_path.read_bytes(), budget_path.read_bytes()) == before


@pytest.mark.parametrize(
    "phase,completed,expected_attempted,expected_unattempted",
    [
        ("files_running", 0, [], list(DAYS)),
        ("file_promoted", 1, ["2023-06-08"], ["2023-06-09", "2023-06-10"]),
        ("file_promoted", 3, list(DAYS), []),
        ("files_completed", 3, list(DAYS), []),
    ],
)
def test_visible_cancellation_preserves_commits_and_does_not_claim_another_day(
    archive, phase, completed, expected_attempted, expected_unattempted
):
    tags = announcement_window_tags("visible-cancel", DAYS[0], DAYS[-1])
    calls, cancelled = [], [False]
    archive.control.cancelled = lambda: cancelled[0]

    def emit(event):
        if event.get("phase") == phase and event.get("files_completed") == completed:
            cancelled[0] = True

    archive.control.emit = emit
    with pytest.raises(AnnouncementCancelled, match="announcement_cancelled"):
        run_window(archive, DAYS, tags, _empty_source(calls))
    state = state_for(archive, "visible-cancel")
    assert state["phase"] == "cancelled"
    assert state["attempted_days"] == expected_attempted
    assert state["unattempted_days"] == expected_unattempted
    assert state["files_completed"] == list(DAYS[:completed])
    before = {
        day: hashlib.sha256(archive.target(day).read_bytes()).hexdigest()
        for day in DAYS[:completed]
    }
    cancelled[0] = False
    archive.control.emit = lambda _: None
    run_window(archive, DAYS, tags, _empty_source(calls))
    assert calls == ["20230608", "20230609", "20230610"]
    assert state_for(archive, "visible-cancel")["phase"] == "files_completed"
    assert all(
        hashlib.sha256(archive.target(day).read_bytes()).hexdigest() == fingerprint
        for day, fingerprint in before.items()
    )


@pytest.mark.parametrize("boundary", ["helper_return", "first_metadata", "last_metadata"])
def test_asset_observes_cancellation_before_materialization(
    archive, monkeypatch, boundary
):
    import orchestrator.defs.assets.anns_d as asset_module

    tags = announcement_window_tags("asset-cancel", DAYS[0], DAYS[-1])
    status, metadata, calls = [dg.DagsterRunStatus.STARTED], [], []
    monkeypatch.setattr(asset_module, "DEFAULT_LAKE_ROOT", str(archive.root))
    monkeypatch.setattr(asset_module, "DEFAULT_LAKE_STAGING_ROOT", str(archive.staging))
    monkeypatch.setattr(LakeRootResource, "ensure_available_for_run", lambda *_: None)
    monkeypatch.setattr(
        asset_module, "AnnouncementProcessCall", lambda *_: _empty_source(calls)
    )
    original = asset_module.execute_announcement_window

    def execute(*args, **kwargs):
        result = original(*args, **kwargs)
        if boundary == "helper_return":
            status[0] = dg.DagsterRunStatus.CANCELING
        return result

    monkeypatch.setattr(asset_module, "execute_announcement_window", execute)

    def add_metadata(values, *, partition_key):
        metadata.append(partition_key)
        if (boundary == "first_metadata" and partition_key == DAYS[0]) or (
            boundary == "last_metadata" and partition_key == DAYS[-1]
        ):
            status[0] = dg.DagsterRunStatus.CANCELING

    # Run-state lookup is a substitute. The actual asset/control/window and file IO run.
    context = SimpleNamespace(
        partition_keys=list(DAYS),
        run=SimpleNamespace(run_id="asset-cancel-run", root_run_id=None, tags=tags),
        instance=SimpleNamespace(
            get_run_by_id=lambda _: SimpleNamespace(status=status[0])
        ),
        log=SimpleNamespace(info=lambda _: None),
        add_asset_metadata=add_metadata,
    )
    with pytest.raises(AnnouncementCancelled, match="announcement_cancelled"):
        asset_module.raw_tushare_anns_d.op.compute_fn.decorated_fn(
            context,
            AnnouncementRawConfig(interval_seconds=0),
            LakeRootResource(root_path=str(archive.root)),
            TushareResource(token="isolated-unused-token"),
        )
    assert metadata == {
        "helper_return": [], "first_metadata": [DAYS[0]], "last_metadata": list(DAYS),
    }[boundary]
    state = state_for(archive, "asset-cancel")
    assert state["phase"] == "files_completed"
    assert state["files_completed"] == list(DAYS)
    assert calls == ["20230608", "20230609", "20230610"]
