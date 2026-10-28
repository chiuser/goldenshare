"""LLD12.16.3 scoped receipts, using tiny real producer files and SDK/SQLite.

Only HTTP is replaced by the independent 21-column wire samples in the original
delivery fixture. Each scenario stays below eight tiny generated files. Control
corruption and absent historical registration are deliberately injected faults.
"""

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import dagster as dg
import pytest

from orchestrator.defs import stock_period_update as update
from orchestrator.defs.bootstrap import stock_period_history as history
from orchestrator.defs.io import stock_period_raw as raw
from orchestrator.defs.run_contracts.stock_period import VERSION
from tests.test_stock_period_delivery_confirmation import (
    SOURCE_FIELDS,
    _ack,
    _confirm,
    _emit,
    _emit_checks,
    _event_count,
    _scenario,
)


def forbidden(*args, **kwargs):
    pytest.fail("scoped historical proof attempted a business operation")


def replay_week(case):
    return history.replay_events(
        Path(case["old"]["path"]), root=case["root"], staging=case["staging"],
        allowed_frequencies={"week"},
        confirm_delivery=lambda _: _confirm(case, allowed_frequencies={"week"}),
        events=forbidden, completion_events=forbidden,
    )


@pytest.mark.parametrize("successor", [False, True])
def test_week_receipts_complete_without_closing_or_accessing_month(successor, monkeypatch):
    with _scenario(frequencies=("week", "month"), successor=successor) as case:
        run = Path(case["old"]["path"])
        unchanged = {name: (run / name).read_bytes() for name in ("manifest.json", "complete.json")}
        daily = (case["staging"] / "stock_period/daily.json").read_bytes()
        events, requests = _event_count(case["instance"]), len(case["requests"])
        real_stat = update._period_delivery_stat

        def only_week(path):
            text = str(path)
            assert "/events/month/" not in text and not text.endswith("/completion/month.json")
            assert "/stk_period_bar_adj_month/" not in text
            return real_stat(path)

        monkeypatch.setattr(update, "_period_delivery_stat", only_week)
        for _ in range(2):
            result = replay_week(case)
            assert result["allowed_events_complete"] is True
            assert result["events_complete"] is False
            assert set(result["completions"]) == {"week"}
            assert result["historical_only"] is successor
        assert raw.read_json(run / "events/week/2026-10-23.json") == {
            key: case["old"]["files"][0][key] for key in ("version", "sha256")
        }
        assert (run / "events/completion/week.json").exists()
        assert not (run / "events/month").exists()
        assert (case["staging"] / "stock_period/daily.json").read_bytes() == daily
        assert unchanged == {name: (run / name).read_bytes() for name in unchanged}
        assert len(case["requests"]) == requests and _event_count(case["instance"]) == events


def test_mixed_historical_week_and_current_month_repairs_only_current_checks():
    with _scenario(frequencies=("week", "month"),
                   old_checks={"week": "all", "month": "none"}) as case:
        first = _confirm(case)
        assert first["historical_only"] is True
        assert not first["allowed_events_complete"] and first["reason"] == "missing_checks"
        assert [item["freq"] for item in first["current_files"]] == ["month"]
        repaired, confirmations = [], []

        def confirm(_):
            confirmations.append(True)
            return _confirm(case)

        def events(item, *, completion):
            repaired.append(item["freq"])
            assert item["freq"] == "month"
            _emit_checks(case["instance"], item,
                         case["old_mats"][("month", "2026-10")], passed=True)
            return True

        result = history.replay_events(
            Path(case["old"]["path"]), root=case["root"], staging=case["staging"],
            confirm_delivery=confirm, events=events, completion_events=forbidden,
        )
        assert repaired == ["month"] and len(confirmations) == 2
        assert result["events_complete"] and result["allowed_events_complete"]
        assert result["historical_only"]
        assert raw.read_json(case["staging"] / "stock_period/daily.json")["pending_work"] == {}


@pytest.mark.parametrize("fault", ["file", "notice", "check", "batch_flag", "scope_flag", "cp_source"])
def test_incomplete_or_forged_scoped_proof_writes_no_receipt(fault):
    with _scenario(frequencies=("week", "month")) as case:
        proof = deepcopy(_confirm(case, allowed_frequencies={"week"}))
        if fault == "file":
            proof["file_evidence"].clear()
        elif fault == "notice":
            proof["completion_evidence"].clear()
        elif fault == "check":
            proof["file_evidence"][("week", "2026-10-23")]["checks"].popitem()
        elif fault == "batch_flag":
            proof["events_complete"] = True
        elif fault == "scope_flag":
            proof.pop("allowed_events_complete")
        else:
            proof["file_evidence"][("week", "2026-10-23")] = {
                "cp_source": str(Path(case["old"]["path"]) / "events/week/2026-10-23.json")
            }
        with pytest.raises(ValueError, match="period_delivery_confirmation_invalid"):
            _ack(case, proof)
        assert not (Path(case["old"]["path"]) / "events").exists()


@pytest.mark.parametrize("fault", ["drop_chain", "empty_chain", "cutoff_none", "cutoff_zero",
                                  "wrong_cutoff", "link_hash", "link_checks"])
def test_historical_proof_requires_its_complete_successor_chain_and_cutoff(fault):
    with _scenario(frequencies=("week", "month")) as case:
        proof = deepcopy(_confirm(case, allowed_frequencies={"week"}))
        evidence = proof["file_evidence"][("week", "2026-10-23")]
        if fault == "drop_chain":
            del evidence["successors"]
        elif fault == "empty_chain":
            evidence["successors"] = []
        elif fault == "cutoff_none":
            evidence["before_event_id"] = None
        elif fault == "cutoff_zero":
            evidence["before_event_id"] = 0
        elif fault == "wrong_cutoff":
            evidence["before_event_id"] += 1
        elif fault == "link_hash":
            evidence["successors"][0]["file_receipt_hash"] = "0" * 64
        else:
            evidence["successors"][0]["checks"].popitem()
        with pytest.raises(ValueError, match="period_delivery_confirmation_invalid"):
            _ack(case, proof)
        assert not (Path(case["old"]["path"]) / "events").exists()


@pytest.mark.parametrize("fault", ["preimage", "complete_digest"])
def test_historical_proof_is_bound_to_controlled_successor_receipt_contents(fault):
    with _scenario(frequencies=("week", "month")) as case:
        proof = _confirm(case, allowed_frequencies={"week"})
        successor = Path(case["new"]["path"])
        if fault == "complete_digest":
            proof["control_versions"][str(successor / "complete.json")]["digest"] = "f" * 64
        else:
            # Deliberately malformed input: even a supplied control snapshot
            # matching this bad JSON cannot establish the original preimage.
            path = successor / "committed/week/2026-10-23.json"
            bad = {**raw.read_json(path), "target_preimage": [7, 8, 9, 10, 11]}
            raw.atomic_json(path, bad)
            proof["control_versions"][str(path)] = {
                "kind": "json", "version": raw.file_version(path), "digest": raw.digest(bad),
            }
        with pytest.raises(ValueError, match="period_delivery_confirmation_invalid"):
            _ack(case, proof)
        assert not (Path(case["old"]["path"]) / "events").exists()


def test_empty_frequency_intersection_is_rejected():
    with (
        _scenario(successor=False) as case,
        pytest.raises(ValueError, match="period_delivery_frequency_invalid"),
    ):
        _confirm(case, allowed_frequencies={"month"})


def test_replay_rejects_empty_scope_and_missing_new_completion_field_before_writes():
    with _scenario(successor=False) as case:
        run = Path(case["old"]["path"])
        with pytest.raises(ValueError, match="period_delivery_frequency_scope_invalid"):
            history.replay_events(run, root=case["root"], staging=case["staging"],
                allowed_frequencies={"month"}, confirm_delivery=forbidden)
        proof = _confirm(case)
        del proof["allowed_events_complete"]
        with pytest.raises(ValueError, match="period_delivery_confirmation_invalid"):
            history.replay_events(run, root=case["root"], staging=case["staging"],
                confirm_delivery=lambda _: proof, events=forbidden)
        assert not (run / "events").exists()


def test_actual_week_only_op_uses_real_proof_without_new_business_events(monkeypatch):
    from orchestrator.defs.ops import stock_weekly_bootstrap_checks as operation
    from orchestrator.defs.run_contracts.configs import (
        StockWeeklyBootstrapEventChecksConfig,
    )

    with _scenario(frequencies=("week", "month")) as case:
        monkeypatch.setattr(operation, "DEFAULT_LAKE_STAGING_ROOT", str(case["staging"]))
        count = _event_count(case["instance"])
        result = operation.report_stock_weekly_bootstrap_checks.compute_fn.decorated_fn(
            SimpleNamespace(instance=case["instance"]),
            StockWeeklyBootstrapEventChecksConfig(run_id=case["old"]["run_id"]),
        )
        assert result == {"reported_files": 0}
        assert _event_count(case["instance"]) == count
        run = Path(case["old"]["path"])
        assert (run / "events/week/2026-10-23.json").exists()
        assert not (run / "events/month").exists()
        assert raw.read_json(run / "manifest.json")["phase"] == "files_complete"


@pytest.mark.parametrize("stage", ["file", "notice"])
def test_partial_atomic_interruption_retry_and_final_check_use_three_confirmations(stage, monkeypatch):
    with _scenario(frequencies=("week", "month")) as case:
        run = Path(case["old"]["path"])
        stopped = run / ("events/week/2026-10-23.json" if stage == "file"
                         else "events/completion/week.json")
        original_write = update.atomic_json
        confirmations = []
        initial_events, initial_requests = _event_count(case["instance"]), len(case["requests"])

        def confirm(_):
            confirmations.append(True)
            return _confirm(case, allowed_frequencies={"week"})

        def replay():
            return history.replay_events(run, root=case["root"], staging=case["staging"],
                allowed_frequencies={"week"}, confirm_delivery=confirm,
                events=forbidden, completion_events=forbidden)

        def interrupted(path, value):
            original_write(path, value)
            if Path(path) == stopped:
                raise OSError("interrupted_after_partial_cp")

        monkeypatch.setattr(update, "atomic_json", interrupted)
        with pytest.raises(OSError, match="interrupted_after_partial_cp"):
            replay()
        monkeypatch.setattr(update, "atomic_json", original_write)
        assert replay()["allowed_events_complete"]
        assert replay()["allowed_events_complete"]
        assert len(confirmations) == 3
        assert raw.read_json(run / "manifest.json")["phase"] == "files_complete"
        assert _event_count(case["instance"]) == initial_events
        assert len(case["requests"]) == initial_requests


def test_partial_cp_does_not_hide_a_later_failed_current_successor_check():
    with _scenario(frequencies=("week", "month")) as case:
        assert replay_week(case)["allowed_events_complete"]
        item = case["new"]["files"][0]
        mat = case["instance"].fetch_materializations(dg.AssetRecordsFilter(
            dg.AssetKey("raw_tushare_stk_period_bar_adj_week"),
            asset_partitions=["2026-10-23"],
        ), limit=1).records[0]
        _emit_checks(case["instance"], item, mat, passed=False)
        with pytest.raises(ValueError, match="period_delivery_checks_invalid"):
            replay_week(case)
        assert raw.read_json(Path(case["old"]["path"]) / "manifest.json")["phase"] == "files_complete"


def test_closed_partial_reuses_only_original_week_receipts_without_parquet_stats(monkeypatch):
    with _scenario(frequencies=("week", "month")) as case:
        _ack(case, _confirm(case))
        run = Path(case["old"]["path"])
        before = (run / "manifest.json").read_bytes()
        real_stat = update._period_delivery_stat

        def no_old_files(path):
            assert Path(path).suffix != ".parquet"
            assert "/events/month/" not in str(path)
            assert not str(path).endswith("/completion/month.json")
            return real_stat(path)

        monkeypatch.setattr(update, "_period_delivery_stat", no_old_files)
        proof = replay_week(case)
        assert proof["allowed_events_complete"] and not proof["events_complete"]
        assert proof["historical_only"] and proof["current_files"] == []
        assert (run / "manifest.json").read_bytes() == before


@pytest.mark.parametrize("stage", ["before_file", "before_notice", "final"])
def test_partial_receipt_checks_dependencies_before_writes_and_final_return(stage, monkeypatch):
    with _scenario(frequencies=("week", "month")) as case:
        run = Path(case["old"]["path"])
        file_cp = run / "events/week/2026-10-23.json"
        notice_cp = run / "events/completion/week.json"
        commit = Path(case["new"]["path"]) / "committed/week/2026-10-23.json"
        daily = case["staging"] / "stock_period/daily.json"
        proof = _confirm(case, allowed_frequencies={"week"})
        original_write, original_check = update.atomic_json, update._period_delivery_assert_controls
        changed = False

        def drift():
            nonlocal changed
            changed = True
            path = daily if stage == "final" else commit
            raw.atomic_json(path, raw.read_json(path))

        def check(controls, cancel):
            if stage == "before_file" and set(controls) == {str(file_cp)} and not changed:
                drift()
            return original_check(controls, cancel)

        def write(path, value):
            original_write(path, value)
            if not changed and ((stage == "before_notice" and Path(path) == file_cp)
                                or (stage == "final" and Path(path) == notice_cp)):
                drift()

        monkeypatch.setattr(update, "atomic_json", write)
        monkeypatch.setattr(update, "_period_delivery_assert_controls", check)
        with pytest.raises(ValueError, match="period_delivery_control_changed"):
            _ack(case, proof)
        assert changed
        assert file_cp.exists() is (stage != "before_file")
        assert notice_cp.exists() is (stage == "final")
        assert raw.read_json(run / "manifest.json")["phase"] == "files_complete"
        assert case["old"]["run_id"] in raw.read_json(daily)["pending_work"]
        monkeypatch.setattr(update, "atomic_json", original_write)
        monkeypatch.setattr(update, "_period_delivery_assert_controls", original_check)
        assert not _ack(case, _confirm(case, allowed_frequencies={"week"}))["events_complete"]


def manual_history(case, frequencies):
    """Use the actual registered history producer, not a fabricated queue item."""
    _ack(case, _confirm(case))

    def source(params):
        day = "20261023" if params["freq"] == "week" else "20261031"
        return json.dumps({"code": 0, "data": {"fields": SOURCE_FIELDS, "items": [
            ["000001.SZ", day, "20261022", params["freq"]] + ["4.0000"] * 17,
        ]}}).encode()

    result = history.run_period(
        root=case["root"], staging=case["staging"], listed=case["listed"],
        aliases=case["aliases"], policy=case["policy"], transport=source,
        intent={"version": VERSION, "mode": "history", "frequencies": list(frequencies),
                "codes": ["000001.SZ"], "request_id": "manual-history"},
    )
    _emit(case["instance"], result)
    return result


@pytest.mark.parametrize("registered", [False, True])
def test_manual_history_partial_requires_registration_and_never_consumes_daily(registered):
    with _scenario(successor=False) as case:
        result = manual_history(case, ("week", "month"))
        run = Path(result["path"])
        path = case["staging"] / "stock_period/daily.json"
        state = raw.read_json(path)
        pending = state["pending_work"][result["run_id"]]
        assert pending["kind"] == "history" and "consumed" not in pending
        if not registered:
            del state["pending_work"][result["run_id"]]
            raw.atomic_json(path, state)
        before = path.read_bytes()

        def confirm(_):
            return update.confirm_period_delivery(case["instance"], run,
                root=case["root"], staging=case["staging"], allowed_frequencies={"week"})

        if not registered:
            with pytest.raises(ValueError, match="period_history_registration_required"):
                history.replay_events(run, root=case["root"], staging=case["staging"],
                    allowed_frequencies={"week"}, confirm_delivery=forbidden)
            with pytest.raises(ValueError, match="period_history_registration_required"):
                update.acknowledge_period_delivery(run, confirm(run),
                    root=case["root"], staging=case["staging"])
            assert not (run / "events").exists()
        else:
            scoped = history.replay_events(run, root=case["root"], staging=case["staging"],
                allowed_frequencies={"week"}, confirm_delivery=confirm,
                events=forbidden, completion_events=forbidden)
            assert scoped["allowed_events_complete"] and not scoped["events_complete"]
        assert path.read_bytes() == before
        full = update.confirm_period_delivery(case["instance"], run,
            root=case["root"], staging=case["staging"])
        # The unregistered case must use the existing full-frequency events registration first.
        if not registered:
            history.ensure_history_pending(run, root=case["root"], staging=case["staging"],
                                           saved=raw.read_json(run / "manifest.json"))
            full = update.confirm_period_delivery(case["instance"], run,
                root=case["root"], staging=case["staging"])
        assert update.acknowledge_period_delivery(run, full,
            root=case["root"], staging=case["staging"])["pending_removed"]
        after = raw.read_json(path)
        assert after == {**state, "pending_work": {}}


def test_single_week_history_scope_is_the_whole_batch_and_can_register():
    with _scenario(successor=False) as case:
        result = manual_history(case, ("week",))
        run = Path(result["path"])
        path = case["staging"] / "stock_period/daily.json"
        state = raw.read_json(path)
        del state["pending_work"][result["run_id"]]
        raw.atomic_json(path, state)
        proof = history.replay_events(run, root=case["root"], staging=case["staging"],
            allowed_frequencies={"week"}, events=forbidden, completion_events=forbidden,
            confirm_delivery=lambda _: update.confirm_period_delivery(case["instance"], run,
                root=case["root"], staging=case["staging"], allowed_frequencies={"week"}))
        assert proof["events_complete"] and proof["allowed_events_complete"]
        assert raw.read_json(path) == state
