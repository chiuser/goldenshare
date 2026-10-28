"""LLD12.16.10: frozen receipt paths are metadata; real IO stays guarded.

Actual fixtures use two tiny producer files. The 2/100-entry capacity receipts
are explicitly synthetic metadata with independent literal paths/versions;
they do not claim 100 published files or read any formal Lake/instance.
"""

from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path

import pytest

from orchestrator.defs import stock_period_update as update
from orchestrator.defs.bootstrap import stock_period_history as history
from orchestrator.defs.io import stock_period_raw as raw
from orchestrator.defs.run_contracts.stock_period import digest
from tests.test_stock_period_delivery_confirmation import (
    _ack,
    _confirm,
    _event_count,
    _scenario,
)
from tests.test_stock_period_history import args


def forbid_paths(monkeypatch, blocked, calls):
    """Protect entire target subtrees, including dataset/partition parents."""
    for name in ("lstat", "stat", "resolve", "open", "glob", "rglob"):
        original = getattr(Path, name)

        def guarded(path, *arguments, _name=name, _original=original, **kwargs):
            path = Path(path)
            if blocked is None or any(path == parent or path.is_relative_to(parent) for parent in blocked):
                calls.append((_name, str(path)))
                raise AssertionError(f"unexpected_lake_path_access:{_name}:{path}")
            return _original(path, *arguments, **kwargs)

        monkeypatch.setattr(Path, name, guarded)


def produced(tmp_path):
    arguments = args(tmp_path)
    result = history.run_period(**arguments)
    run = Path(result["path"])
    return arguments, run, raw.read_json(run / "manifest.json"), raw.read_json(run / "complete.json")


@pytest.mark.parametrize("count", [2, 100])
def test_receipt_metadata_never_accesses_targets_or_parent_components(tmp_path, monkeypatch, count):
    arguments, run, saved, _ = produced(tmp_path)
    files = []
    for index in range(count):
        if index % 2 == 0:
            frequency = "week"
            period = (date(2014, 1, 3) + timedelta(weeks=index // 2)).isoformat()
            relative = f"raw/tushare/stk_period_bar_adj_week/week_end={period}/part-000.parquet"
        else:
            frequency = "month"
            offset = index // 2
            period = f"{2014 + offset // 12:04d}-{offset % 12 + 1:02d}"
            relative = f"raw/tushare/stk_period_bar_adj_month/month={period}/data.parquet"
        files.append({"freq": frequency, "period": period,
                      "target": str(arguments["root"] / relative), "rows": 1,
                      "version": [17, 2000 + index, 100, 3000 + index, 4000 + index],
                      "sha256": f"{index + 1:064x}"})
    complete = {"run_id": run.name, "files": files, "unit_asofs": {}}
    saved = {**saved, "file_receipt_hash": digest(complete)}
    calls = []
    with monkeypatch.context() as guard:
        forbid_paths(guard, [arguments["root"] / "raw"], calls)
        assert history.completed_receipt(run, saved, complete=complete) == complete
    assert calls == []


@pytest.mark.parametrize("frequency,period,partition,filename", [
    ("week", "2026-10-23", "week_end=2026-10-23", "part-000.parquet"),
    ("month", "2026-10", "month=2026-10", "data.parquet"),
])
def test_pure_path_composition_has_literal_identity_and_no_filesystem_access(
    tmp_path, monkeypatch, frequency, period, partition, filename,
):
    root = tmp_path / "lake"
    base = f"{root}/raw/tushare/stk_period_bar_adj_{frequency}"
    calls = []
    with monkeypatch.context() as guard:
        forbid_paths(guard, None, calls)
        assert str(raw._dataset_root_path(root, frequency)) == base
        assert str(raw._target_path(root, frequency, period)) == f"{base}/{partition}/{filename}"
    assert calls == []


@pytest.mark.parametrize("root,frequency,period", [
    ("relative/lake", "week", "2026-10-23"),
    ("/private/tmp/lake/../other", "week", "2026-10-23"),
    ("/private/tmp/lake", "year", "2026"),
    ("/private/tmp/lake", "week", "2026-10-22"),
    ("/private/tmp/lake", "month", "2026-13"),
])
def test_pure_path_composition_rejects_invalid_syntax_without_io(monkeypatch, root, frequency, period):
    calls = []
    with monkeypatch.context() as guard:
        forbid_paths(guard, None, calls)
        with pytest.raises(ValueError):
            raw._target_path(root, frequency, period)
    assert calls == []


@pytest.mark.parametrize("fault", ["target", "traversal", "relative_root", "root_traversal", "hash", "identity"])
def test_receipt_paths_root_and_hash_corruption_still_reject(tmp_path, monkeypatch, fault):
    arguments, run, saved, complete = produced(tmp_path)
    saved, complete = deepcopy(saved), deepcopy(complete)
    if fault == "target":
        complete["files"][0]["target"] = str(tmp_path / "other-lake/raw/tushare/stk_period_bar_adj_week/week_end=2026-10-16/part-000.parquet")
    elif fault == "traversal":
        complete["files"][0]["target"] = str(arguments["root"]) + "/raw/tushare/../other/part-000.parquet"
    elif fault in ("relative_root", "root_traversal"):
        saved["identity"]["root"] = "relative/lake" if fault == "relative_root" else str(arguments["root"]) + "/../other"
        saved["identity_hash"] = digest(saved["identity"])
    elif fault == "hash":
        complete["files"][0]["rows"] = 999
    else:
        saved["identity_hash"] = "0" * 64
    if fault != "hash":
        saved["file_receipt_hash"] = digest(complete)
    calls = []
    with monkeypatch.context() as guard:
        forbid_paths(guard, [arguments["root"] / "raw"], calls)
        with pytest.raises(ValueError):
            history.completed_receipt(run, saved, complete=complete)
    assert calls == []


@pytest.mark.parametrize("change", ["missing", "replaced"])
def test_real_receipt_remains_historical_after_its_target_changes(tmp_path, change):
    _, run, saved, complete = produced(tmp_path)
    target = Path(complete["files"][0]["target"])
    if change == "missing":
        target.unlink()
    else:
        target.write_bytes(b"a later physical version")
    assert history.completed_receipt(run, saved) == complete
    with pytest.raises((FileNotFoundError, ValueError)):
        history.completed_files(run, saved)


@pytest.mark.parametrize("symlink", ["leaf", "dataset"])
def test_historical_receipt_accepts_symlink_today_but_real_io_still_rejects(tmp_path, symlink):
    arguments, run, saved, complete = produced(tmp_path)
    item = complete["files"][0]
    target = Path(item["target"])
    if symlink == "leaf":
        moved = tmp_path / "original-week.parquet"
        target.rename(moved)
        target.symlink_to(moved)
    else:
        original = target.parent.parent
        moved = tmp_path / "original-week-dataset"
        original.rename(moved)
        original.symlink_to(moved, target_is_directory=True)
    assert history.completed_receipt(run, saved) == complete
    actions = [
        lambda: raw.target_path(arguments["root"], item["freq"], item["period"]),
        lambda: raw.file_version(target),
        lambda: raw.read_json(target),
        lambda: raw.publish(item, checkpoint=tmp_path / "must-not-write.json"),
    ]
    if symlink == "dataset":
        actions.append(lambda: raw.dataset_root(arguments["root"], item["freq"]))
    for operation in actions:
        with pytest.raises(ValueError, match="period_symlink_forbidden"):
            operation()
    assert not (tmp_path / "must-not-write.json").exists()


@pytest.mark.parametrize("closed", [False, True])
def test_actual_two_frequency_replay_avoids_unselected_lstat_and_closed_targets(monkeypatch, closed):
    with _scenario(frequencies=("week", "month"), successor_frequencies=("week", "month")) as case:
        run = Path(case["old"]["path"])
        if closed:
            _ack(case, _confirm(case))
        month = case["root"] / "raw/tushare/stk_period_bar_adj_month"
        moved = case["root"].parent / "original-month-dataset"
        month.rename(moved)
        month.symlink_to(moved, target_is_directory=True)
        events, requests = _event_count(case["instance"]), len(case["requests"])
        daily = (case["staging"] / "stock_period/daily.json").read_bytes()
        manifest = (run / "manifest.json").read_bytes()
        successor = Path(case["new"]["path"])
        reads = {successor / "manifest.json": 0, successor / "complete.json": 0}
        original_read = update.read_json

        def observed(path):
            if Path(path) in reads:
                reads[Path(path)] += 1
            return original_read(path)

        calls = []
        with monkeypatch.context() as guard:
            guard.setattr(update, "read_json", observed)
            forbid_paths(guard, [case["root"] / "raw"] if closed else [month], calls)
            result = history.replay_events(run, root=case["root"], staging=case["staging"],
                allowed_frequencies={"week"},
                confirm_delivery=lambda _: _confirm(case, allowed_frequencies={"week"}))
        assert result["allowed_events_complete"] and not result["events_complete"]
        assert calls == []
        # One read in confirm and one cached proof read in ack; complete is
        # decoded only by confirm. Closed history never opens successor JSON.
        assert reads == {successor / "manifest.json": 0 if closed else 2,
                         successor / "complete.json": 0 if closed else 1}
        assert (run / "manifest.json").read_bytes() == manifest
        assert (case["staging"] / "stock_period/daily.json").read_bytes() == daily
        assert _event_count(case["instance"]) == events and len(case["requests"]) == requests
