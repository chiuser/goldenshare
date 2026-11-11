"""Retained bootstrap recovery, independent of the retired daily/global index."""

import pytest

from orchestrator.defs.bootstrap import stock_period_history as history
from orchestrator.defs.io import stock_period_raw as raw
from tests.test_stock_period_history import args


@pytest.mark.parametrize("freq", ["week", "month"])
def test_coordinator_recovers_rename_before_checkpoint_without_rewriting(
    tmp_path, monkeypatch, freq
):
    kw = args(tmp_path)
    write = raw.atomic_json
    raised = False

    def fail(path, value):
        nonlocal raised
        if "committed" in path.parts and freq in path.parts and not raised:
            raised = True
            raise OSError("after rename")
        return write(path, value)

    monkeypatch.setattr(raw, "atomic_json", fail)
    with pytest.raises(OSError, match="after rename"):
        history.run_period(**kw)
    period = "2026-10-16" if freq == "week" else "2026-10"
    target = raw.target_path(kw["root"], freq, period)
    version = raw.file_version(target)
    monkeypatch.setattr(raw, "atomic_json", write)
    kw["transport"] = lambda _: pytest.fail("bootstrap re-downloaded complete source")
    result = history.run_period(**kw)
    assert raw.file_version(target) == version and len(result["files"]) == 2
    assert not (kw["staging"] / "stock_period/baseline.json").exists()
    assert not (kw["staging"] / "stock_period/daily.json").exists()


@pytest.mark.parametrize("mode", ["history", "upsert"])
def test_retired_coordinator_modes_are_rejected_without_state_or_source(tmp_path,mode):
    kw=args(tmp_path)
    kw["intent"]["mode"]=mode
    kw["transport"]=lambda _:pytest.fail("retired mode requested source")
    with pytest.raises(ValueError,match="version_or_mode_invalid"):
        history.run_period(**kw)
    assert not kw["root"].exists() and not kw["staging"].exists()


def test_old_coordinators_and_global_indexes_are_absent():
    from orchestrator.defs import stock_period_update as update
    from orchestrator.defs.run_contracts import configs
    from orchestrator.defs.run_contracts import stock_period as contract
    removed={history:("history_work_identity","ensure_history_pending","frozen_history_work","ordered_pending_work","require_pending_delivery_before_write","_record_ranges","validate_registered_targets","recover_moved_candidate"),
             raw:("_old_range_paths","range_index_valid","_source_ranges","merge_ranges"),
             update:("daily_state","daily_handoff_ready","_daily_work","_consume_daily_files","_execute_daily_locked","execute_daily","handoff_bootstrap","bootstrap_watermarks","factor_changes","confirmed_retirements","calendar_days","period_bounds","close_day","source_final","no_trading_period","confirm_period_delivery","acknowledge_period_delivery","report_file_events","report_completion_events"),
             contract:("completion_reference","validate_completion_reference","completion_notice","validate_completion_notice","STOCK_PERIOD_RUNTIME_RSS_GIB_TAG"),
             configs:("StockWeeklyBootstrapEventChecksConfig",)}
    for module,names in removed.items():
        assert all(not hasattr(module,name) for name in names)
