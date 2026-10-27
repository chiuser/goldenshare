"""Immutable receipt and callback boundaries, using the actual Raw producer.

The callback/ack spies isolate Dagster event confirmation, tested separately in
test_stock_period_delivery_confirmation. No formal instance or Lake is opened.
"""

import os
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path

import pytest

from orchestrator.defs.bootstrap import stock_period_history as history
from orchestrator.defs.io.stock_period_raw import atomic_json, read_json
from orchestrator.defs.run_contracts.stock_period import digest, execution_id
from tests.test_stock_period_combined import (
    bootstrap,
    combined_intent,
    combined_source,
    values,
)
from tests.test_stock_period_history import args


def captured(tmp_path):
    arguments = args(tmp_path)
    result = history.run_period(**arguments)
    run = Path(result["path"])
    saved = read_json(run / "manifest.json")
    complete = read_json(run / "complete.json")
    assert [item["freq"] for item in complete["files"]] == ["week", "month"]
    assert [item["rows"] for item in complete["files"]] == [1, 1]
    assert saved["phase"] == "files_complete"
    return arguments, run, saved, complete


def proof(saved, complete, **changes):
    # These literal decision flags are independent of the implementation under test.
    result = {
        "run_id": complete["run_id"],
        "identity_hash": saved["identity_hash"],
        "file_receipt_hash": saved["file_receipt_hash"],
        "files": complete["files"],
        "events_complete": True,
        "historical_only": True,
        "current_files": [],
        "allowed_frequencies": ["month", "week"],
    }
    result.update(changes)
    return result


def forbid(*args, **kwargs):
    pytest.fail("unexpected source, file-version scan, or business event")


def test_receipt_validation_does_not_require_old_file_to_stay_current(tmp_path):
    _, run, saved, complete = captured(tmp_path)
    Path(complete["files"][0]["target"]).write_bytes(b"later-version")
    assert history.completed_receipt(run, saved) == complete
    with pytest.raises(ValueError, match="period_committed_file_changed"):
        history.completed_files(run, saved)


def test_preloaded_receipt_still_checks_hash_without_reading_it_again(
    tmp_path, monkeypatch
):
    _, run, saved, complete = captured(tmp_path)
    monkeypatch.setattr(history, "read_json", forbid)
    assert history.completed_receipt(run, saved, complete=complete) == complete
    broken = {**complete, "unit_asofs": {"week": {"changed": "20261027"}}}
    with pytest.raises(ValueError, match="period_complete_receipt_changed"):
        history.completed_receipt(run, saved, complete=broken)


def test_new_file_phase_without_events_does_not_query_or_report_delivery(
    tmp_path, monkeypatch
):
    arguments = args(tmp_path)
    monkeypatch.setattr(history, "replay_events", forbid)
    result = history.run_period(
        **arguments,
        confirm_delivery=forbid,
        completion_events=forbid,
    )
    run = Path(result["path"])
    saved = read_json(run / "manifest.json")
    complete = read_json(run / "complete.json")
    assert saved["phase"] == "files_complete"
    assert saved["file_receipt_hash"] == digest(complete)
    assert result["events_complete"] is False
    assert result["historical_only"] is False
    assert result["current_files"] == complete["files"]
    assert [(item["freq"], item["period"], item["rows"]) for item in result["files"]] == [
        ("week", "2026-10-16", 1),
        ("month", "2026-10", 1),
    ]
    assert {freq: notice["file_count"] for freq, notice in result["completions"].items()} == {
        "week": 1,
        "month": 1,
    }
    assert not (run / "events").exists()


def test_restoring_file_complete_work_still_requires_delivery_confirmation(
    tmp_path, monkeypatch
):
    import orchestrator.defs.stock_period_update as update

    arguments = args(tmp_path)
    result = history.run_period(**arguments, confirm_delivery=forbid)
    run = Path(result["path"])
    saved = read_json(run / "manifest.json")
    complete = read_json(run / "complete.json")
    confirmations = []
    monkeypatch.setattr(history, "file_version", forbid)
    monkeypatch.setattr(history, "assemble", forbid)
    monkeypatch.setattr(update, "acknowledge_period_delivery", lambda *a, **k: None)

    def confirm(path):
        confirmations.append(path)
        return proof(saved, complete)

    restored = history.run_period(
        **{**arguments, "transport": forbid},
        confirm_delivery=confirm,
    )
    assert confirmations == [run]
    assert restored["events_complete"] is True
    assert restored["historical_only"] is True


@pytest.mark.parametrize("case", ["path", "rows", "version", "sha", "duplicate"])
def test_receipt_validation_rejects_semantic_corruption_even_with_new_digest(
    tmp_path, case
):
    _, run, saved, original = captured(tmp_path)
    complete = deepcopy(original)
    item = complete["files"][0]
    if case == "path":
        item["target"] = str(tmp_path / "outside" / "part.parquet")
    elif case == "rows":
        item["rows"] = -1
    elif case == "version":
        item["version"] = [True, 1, 2, 3, 4]
    elif case == "sha":
        item["sha256"] = "invalid"
    else:
        complete["files"].append(deepcopy(item))
    atomic_json(run / "complete.json", complete)
    saved["file_receipt_hash"] = digest(complete)
    with pytest.raises(ValueError, match="period_complete_file"):
        history.completed_receipt(run, saved)


def test_confirmed_historical_delivery_skips_current_files_and_event_callbacks(
    tmp_path, monkeypatch
):
    import orchestrator.defs.stock_period_update as update

    arguments, run, saved, complete = captured(tmp_path)
    confirmation = proof(saved, complete)
    acknowledged = []
    monkeypatch.setattr(history, "file_version", forbid)
    monkeypatch.setattr(
        update,
        "acknowledge_period_delivery",
        lambda *a, **k: acknowledged.append((a, k)),
        raising=False,
    )
    result = history.replay_events(
        run,
        root=arguments["root"],
        staging=arguments["staging"],
        events=forbid,
        completion_events=forbid,
        confirm_delivery=lambda _: confirmation,
    )
    assert result["events_complete"] is True
    assert result["historical_only"] is True
    assert result["current_files"] == []
    assert result["files"] == complete["files"]
    assert len(acknowledged) == 1
    assert acknowledged[0][0] == (run, confirmation)


def test_confirmation_unknown_reason_cannot_fall_through_to_event_repair(
    tmp_path, monkeypatch
):
    arguments, run, saved, complete = captured(tmp_path)
    monkeypatch.setattr(history, "file_version", forbid)
    with pytest.raises(ValueError, match="period_delivery_confirmation_incomplete"):
        history.replay_events(
            run,
            root=arguments["root"],
            staging=arguments["staging"],
            events=forbid,
            completion_events=forbid,
            confirm_delivery=lambda _: proof(
                saved, complete, events_complete=False, reason="unknown_replacement"
            ),
        )


def test_current_missing_events_are_reconfirmed_after_real_callback_writes(
    tmp_path, monkeypatch
):
    import orchestrator.defs.stock_period_update as update

    arguments, run, saved, complete = captured(tmp_path)
    emitted, confirmations, acknowledgements = [], [], []

    def confirm(_):
        confirmations.append(len(emitted))
        return proof(
            saved,
            complete,
            events_complete=len(emitted) == 2,
            historical_only=False,
            current_files=complete["files"],
            reason="missing_events" if len(emitted) < 2 else "complete",
        )

    monkeypatch.setattr(
        update,
        "acknowledge_period_delivery",
        lambda *a, **k: acknowledgements.append((a, k)),
        raising=False,
    )
    result = history.replay_events(
        run,
        root=arguments["root"],
        staging=arguments["staging"],
        events=lambda item, completion: emitted.append(item["freq"]) or True,
        completion_events=lambda _: 7,
        confirm_delivery=confirm,
    )
    assert emitted == ["week", "month"]
    assert confirmations == [0, 2]
    assert len(acknowledgements) == 1
    assert result["events_complete"] is True


def test_successful_callbacks_without_confirmed_results_do_not_close_batch(
    tmp_path, monkeypatch
):
    import orchestrator.defs.stock_period_update as update

    arguments, run, saved, complete = captured(tmp_path)
    monkeypatch.setattr(update, "acknowledge_period_delivery", forbid, raising=False)
    result = history.replay_events(
        run,
        root=arguments["root"],
        staging=arguments["staging"],
        events=lambda item, completion: True,
        completion_events=lambda _: 7,
        confirm_delivery=lambda _: proof(
            saved,
            complete,
            events_complete=False,
            historical_only=False,
            current_files=complete["files"],
            reason="missing_checks",
        ),
    )
    assert result["events_complete"] is False
    assert read_json(run / "manifest.json")["phase"] == "files_complete"


def test_closed_week_only_scope_does_not_stat_or_ack_other_frequency(
    tmp_path, monkeypatch
):
    import orchestrator.defs.stock_period_update as update

    arguments, run, saved, complete = captured(tmp_path)
    saved["phase"] = "events_complete"
    atomic_json(run / "manifest.json", saved)
    monkeypatch.setattr(history, "file_version", forbid)
    monkeypatch.setattr(update, "acknowledge_period_delivery", forbid, raising=False)
    result = history.replay_events(
        run,
        root=arguments["root"],
        staging=arguments["staging"],
        events=forbid,
        completion_events=forbid,
        confirm_delivery=lambda _: proof(
            saved,
            complete,
            events_complete=False,
            allowed_frequencies=["week"],
            reason="current_events_incomplete",
        ),
    )
    assert result["historical_only"] is True
    assert result["events_complete"] is False
    assert result["current_files"] == []
    assert set(result["completions"]) == {"week"}
    assert read_json(run / "manifest.json")["phase"] == "events_complete"


def test_run_period_complete_resume_confirms_before_old_target_stat(
    tmp_path, monkeypatch
):
    import orchestrator.defs.stock_period_update as update

    arguments, _, saved, complete = captured(tmp_path)
    monkeypatch.setattr(history, "file_version", forbid)
    monkeypatch.setattr(history, "assemble", forbid)
    monkeypatch.setattr(update, "acknowledge_period_delivery", lambda *a, **k: None, raising=False)
    result = history.run_period(
        **{**arguments, "transport": forbid},
        events=forbid,
        completion_events=forbid,
        confirm_delivery=lambda _: proof(saved, complete),
    )
    assert result["historical_only"] is True
    assert result["files"] == complete["files"]


def test_new_intent_cannot_write_before_earlier_pending_delivery(tmp_path):
    arguments = args(tmp_path)
    original = {
        "intent": {
            "request_id": "old-pending",
            "asof": "2026-10-20",
        }
    }
    atomic_json(
        arguments["staging"] / "stock_period/daily.json",
        {"pending_work": {execution_id("old-pending"): original}},
    )
    with pytest.raises(ValueError, match="period_original_run_required"):
        history.run_period(**{**arguments, "transport": forbid})
    assert not (
        arguments["staging"] / "stock_period/runs" / execution_id("test")
    ).exists()


def test_pending_order_uses_original_dates_instead_of_json_key_order(tmp_path):
    old = {"intent": {"request_id": "old", "asof": "2026-10-20"}}
    new = {"intent": {"request_id": "new", "asof": "2026-10-21"}}
    state = {
        "pending_work": {
            execution_id("new"): new,
            execution_id("old"): old,
        }
    }
    assert history.ordered_pending_work(tmp_path, state) == [old, new]


def test_original_earliest_file_work_can_resume_before_later_intents(tmp_path):
    old = {"intent": {"request_id": "old", "asof": "2026-10-20"}}
    new = {"intent": {"request_id": "new", "asof": "2026-10-21"}}
    atomic_json(
        tmp_path / "stock_period/daily.json",
        {"pending_work": {execution_id("new"): new, execution_id("old"): old}},
    )
    history.require_pending_delivery_before_write(
        tmp_path, execution_id("old"), root=tmp_path / "lake"
    )


@pytest.mark.parametrize("value", [None, "not-a-date", "20261020"])
def test_pending_work_without_unambiguous_original_date_is_rejected(tmp_path, value):
    state = {
        "pending_work": {
            execution_id("old"): {"intent": {"request_id": "old", "asof": value}}
        }
    }
    with pytest.raises(ValueError, match="period_pending_date"):
        history.ordered_pending_work(tmp_path, state)


def current_only_intent():
    return {
        **combined_intent("current-only"),
        "codes": [],
    }


def test_registered_missing_target_is_not_treated_as_a_new_partition(
    tmp_path, monkeypatch
):
    from orchestrator.defs.io import stock_period_raw as raw

    arguments = bootstrap(tmp_path)
    target = raw.target_path(arguments["root"], "week", "2026-10-16")
    target.unlink()
    stages = []
    real = raw.execute

    def tracked(*a, **kw):
        stages.append(kw.get("stage"))
        return real(*a, **kw)

    monkeypatch.setattr(raw, "execute", tracked)
    with pytest.raises(ValueError, match="period_registered_target_missing"):
        history.run_period(
            **arguments, intent=current_only_intent(), transport=combined_source
        )
    assert not target.exists()
    assert "read_affected_once" not in stages
    assert "partition_copy" not in stages


def test_unknown_unselected_version_does_not_block_normal_selected_update(tmp_path):
    from orchestrator.defs.io import stock_period_raw as raw

    arguments = bootstrap(tmp_path)
    untouched = raw.target_path(arguments["root"], "week", "2026-10-02")
    stamp = untouched.stat()
    os.utime(untouched, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1))
    before = raw.file_version(untouched)
    result = history.run_period(
        **arguments, intent=current_only_intent(), transport=combined_source
    )
    assert [(i["freq"], i["period"]) for i in result["files"]] == [
        ("week", "2026-10-16")
    ]
    assert raw.file_version(untouched) == before
    assert [str(r[2]) for r in values(arguments["root"], "2026-10-16")] == [
        "3.0000",
        "8.0000",
    ]


def test_same_intent_committed_file_can_resume_without_becoming_unknown(
    tmp_path, monkeypatch
):
    from orchestrator.defs.io import stock_period_raw as raw

    arguments = bootstrap(tmp_path)
    stopped = False

    def progress(event):
        nonlocal stopped
        if event["stage"] == "file_committed":
            stopped = True

    with pytest.raises(raw.PeriodCancelled):
        history.run_period(
            **arguments,
            intent=combined_intent("partial-owned"),
            transport=combined_source,
            progress=progress,
            cancel=lambda: stopped,
        )
    work = arguments["staging"] / "stock_period/runs" / execution_id("partial-owned")
    committed = next((work / "committed/week").glob("*.json"))
    item = read_json(committed)
    before = raw.file_version(item["target"])
    real = raw.publish
    moves = []

    def publish(candidate, *, checkpoint, **kw):
        if not checkpoint.exists():
            moves.append(candidate["period"])
        return real(candidate, checkpoint=checkpoint, **kw)

    monkeypatch.setattr(history, "publish", publish)
    result = history.run_period(
        **arguments,
        intent=combined_intent("partial-owned"),
        transport=forbid,
    )
    assert raw.file_version(item["target"]) == before
    assert item["period"] not in moves
    assert len(result["files"]) == 3


def test_cached_copy_checks_target_ownership_before_reusing_candidate(tmp_path):
    from orchestrator.defs.io import stock_period_raw as raw

    arguments = bootstrap(tmp_path)
    result = history.run_period(
        **arguments, intent=current_only_intent(), transport=combined_source
    )
    run = Path(result["path"])
    saved = read_json(run / "manifest.json")
    copied = read_json(run / "build/week/copy.json")
    # Use the actual source/COPY manifest, but independently inject an unknown
    # current target version. No candidate or committed receipt authorizes it.
    target = Path(result["files"][0]["target"])
    stamp = target.stat()
    os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1))

    def check(items):
        history.validate_registered_targets(
            items,
            run=run,
            saved=saved,
            baseline=arguments["staging"] / "stock_period/baseline.json",
        )

    with pytest.raises(ValueError, match="period_target_commit_ownership_invalid"):
        raw.assemble(
            [Path(item[0]) for item in copied["identity"]["sources"]],
            work=run / "build/week",
            root=arguments["root"],
            mode="upsert",
            freq="week",
            periods=["2026-10-16"],
            policy=arguments["policy"],
            validate_targets=check,
        )


def metadata_commits(tmp_path, count):
    """Metadata-only scale fixture, not a claim that fake Parquet was published.

    Field ownership and the first-four-version rename rule follow the actual
    producer's candidates/committed receipts exercised above. Snapshot values
    here are independent literal inputs; expected read counts are literal too.
    """
    run = tmp_path / "run"
    baseline = tmp_path / "baseline.json"
    atomic_json(baseline, {"files": []})
    candidates, items = [], []
    for index in range(count):
        period = (date(2010, 1, 1) + timedelta(days=7 * index)).isoformat()
        target = str(
            tmp_path / "lake/raw/tushare/stk_period_bar_adj_week"
            / f"week_end={period}" / "part-000.parquet"
        )
        before = [5, 1000 + index, 4096, 8, 9]
        candidate = {
            "freq": "week",
            "period": period,
            "target": target,
            "candidate": str(
                run / "build/week/outputs" / f"period={period}" / "data_0.parquet"
            ),
            "version": [5, 2000 + index, 4096, 10, 11],
            "target_preimage": before,
            "rows": 1,
            "sha256": "a" * 64,
        }
        committed = {**candidate, "version": [5, 2000 + index, 4096, 10, 12]}
        atomic_json(run / "committed/week" / (period + ".json"), committed)
        candidates.append(candidate)
        items.append(
            {
                key: committed[key]
                for key in ("freq", "period", "target", "version", "target_preimage")
            }
        )
    path = run / "week.candidates.json"
    atomic_json(path, candidates)
    return run, baseline, {"candidate_hashes": {"week": digest(candidates)}}, items


@pytest.mark.parametrize("count", [2, 100])
def test_target_ownership_reads_shared_candidate_receipt_once(tmp_path, monkeypatch, count):
    run, baseline, saved, items = metadata_commits(tmp_path, count)
    reads = []
    real = history.read_json

    def observed(path):
        reads.append(Path(path))
        return real(path)

    monkeypatch.setattr(history, "read_json", observed)
    history.validate_registered_targets(
        items, run=run, saved=saved, baseline=baseline
    )
    assert reads.count(run / "week.candidates.json") == 1
    assert len(reads) == count + 2  # One baseline, one candidate list, each commit.


def test_target_ownership_cache_rejects_same_call_candidate_drift(tmp_path, monkeypatch):
    run, baseline, saved, items = metadata_commits(tmp_path, 2)
    real = history.read_json
    calls = 0

    def changed(path):
        nonlocal calls
        value = real(path)
        if Path(path).parent == run / "committed/week":
            calls += 1
            if calls == 2:
                candidates = real(run / "week.candidates.json")
                candidates[0]["rows"] = 2
                atomic_json(run / "week.candidates.json", candidates)
        return value

    monkeypatch.setattr(history, "read_json", changed)
    with pytest.raises(ValueError, match="period_target_commit_ownership_invalid"):
        history.validate_registered_targets(
            items, run=run, saved=saved, baseline=baseline
        )
