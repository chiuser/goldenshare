"""Independent date, pending-intent and native-anchor recovery boundaries."""

from datetime import date, datetime
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import dagster as dg
import pytest

from orchestrator.defs import stock_period_update as update
from orchestrator.defs.io import stock_period_raw as raw
from tests.test_stock_period_delivery_confirmation import _confirm, _scenario
from tests.test_stock_period_recovery import daily_fixture, daily_source


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = datetime(2026, 10, 28, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        return value.astimezone(tz) if tz else value.replace(tzinfo=None)


def test_explicit_intent_date_never_uses_execution_clock(monkeypatch):
    monkeypatch.setattr(update, "datetime", FrozenDatetime)
    assert update._daily_intent_date(
        NS(), NS(automatic_intent_date="2026-10-27")
    ) == date(2026, 10, 27)


@pytest.mark.parametrize(
    "created, expected",
    [
        (datetime.fromisoformat("2026-10-27T15:59:00+00:00"), None),
        (datetime.fromisoformat("2026-10-27T16:01:00+00:00"), date(2026, 10, 28)),
    ],
)
def test_manual_none_reexecution_cannot_silently_change_day(
    monkeypatch, created, expected
):
    monkeypatch.setattr(update, "datetime", FrozenDatetime)
    looked_up = []
    context = NS(
        run=NS(root_run_id="original", parent_run_id="child"),
        instance=NS(
            get_run_record_by_id=lambda run_id: looked_up.append(run_id)
            or NS(create_timestamp=created)
        ),
    )
    config = NS(automatic_intent_date=None)
    if expected is None:
        with pytest.raises(ValueError, match="period_daily_intent_date_required"):
            update._daily_intent_date(context, config)
    else:
        assert update._daily_intent_date(context, config) == expected
    assert looked_up == ["original"]


def test_first_manual_none_keeps_existing_local_day_default(monkeypatch):
    monkeypatch.setattr(update, "datetime", FrozenDatetime)
    assert update._daily_intent_date(
        NS(run=NS(root_run_id=None, parent_run_id=None)),
        NS(automatic_intent_date=None),
    ) == date(2026, 10, 28)


def test_new_date_stops_before_planning_when_old_native_events_are_missing(
    tmp_path, monkeypatch
):
    kw = daily_fixture(tmp_path)
    update.execute_daily(**kw, transport=daily_source)
    state_path = kw["staging"] / "stock_period/daily.json"
    before = state_path.read_bytes()
    monkeypatch.setattr(
        update, "_daily_work", lambda *a, **k: pytest.fail("new intent planned")
    )
    with pytest.raises(ValueError, match="period_original_run_required"):
        update.execute_daily(
            **{**kw, "today": date(2026, 10, 19)},
            transport=lambda _: pytest.fail("new source requested"),
        )
    assert state_path.read_bytes() == before


def test_original_intent_returns_for_native_checks_without_replanning(
    tmp_path, monkeypatch
):
    kw = daily_fixture(tmp_path)
    update.execute_daily(**kw, transport=daily_source)
    monkeypatch.setattr(
        update, "_daily_work", lambda *a, **k: pytest.fail("frozen intent replanned")
    )
    result = update.execute_daily(
        **kw, transport=lambda _: pytest.fail("completed source requested")
    )
    assert result
    assert not result[-1]["events_complete"]
    assert raw.read_json(kw["staging"] / "stock_period/daily.json")["pending_work"]


def test_historical_ack_precedes_new_date_planning_without_business_reads(monkeypatch):
    with _scenario(successor=True) as case:
        requests = list(case["requests"])
        target = case["old"]["files"][0]["target"]
        version = raw.file_version(target)
        planned = []

        def plan(staging, **kwargs):
            state = raw.read_json(staging / "stock_period/daily.json")
            assert not state["pending_work"]
            assert state["factor_through"] == "2026-10-21"
            planned.append((kwargs["today"], kwargs["freq"]))

        monkeypatch.setattr(update, "_daily_work", plan)
        monkeypatch.setattr(
            update, "calendar_days", lambda *a, **k: ["2026-10-22"]
        )
        result = update.execute_daily(
            root=case["root"],
            staging=case["staging"],
            today=date(2026, 10, 22),
            freq="week",
            listed=case["listed"],
            aliases=case["aliases"],
            policy=case["policy"],
            confirm_delivery=lambda run: _confirm(case),
            transport=lambda _: pytest.fail("historical recovery requested source"),
        )
        assert planned == [(date(2026, 10, 22), "week")]
        assert result[0]["historical_only"] is True
        assert result[0]["current_files"] == []
        assert raw.file_version(target) == version
        assert case["requests"] == requests


def test_unknown_current_anchor_is_rejected_before_file_audit(tmp_path, monkeypatch):
    from orchestrator.defs.paths import raw_stk_period_bar_adj_week_path

    root, staging = tmp_path / "lake", tmp_path / "staging"
    # No real Parquet content is needed to prove an ownership rejection.
    target = raw_stk_period_bar_adj_week_path(root, "2026-10-23")
    target.parent.mkdir(parents=True)
    target.write_bytes(b"unknown file")
    version = raw.file_version(target)
    raw.atomic_json(staging / "stock_period/baseline.json", {"files": []})
    materialization = dg.AssetMaterialization(
        asset_key=dg.AssetKey("raw_tushare_stk_period_bar_adj_week"),
        partition="2026-10-23",
        metadata={
            "dagster/uri": str(target),
            "goldenshare/period_file_version": dg.MetadataValue.json(version),
        },
    )
    instance = NS(
        fetch_materializations=lambda *a, **k: NS(
            records=[NS(asset_materialization=materialization)]
        )
    )
    monkeypatch.setattr(
        raw, "audit_file", lambda *a, **k: pytest.fail("unknown file audited")
    )
    with pytest.raises(ValueError, match="period_anchor_current_delivery_unknown"):
        update._current_period_anchor(instance, root, staging, "week", "2026-10-23")


def test_historical_result_is_excluded_from_native_anchor(tmp_path, monkeypatch):
    from orchestrator.defs import paths
    from orchestrator.defs.bootstrap import stock_period_history as history

    root, staging = tmp_path / "lake", tmp_path / "staging"
    monkeypatch.setattr(paths, "DEFAULT_LAKE_STAGING_ROOT", str(staging))
    monkeypatch.setattr(history, "load_scope", lambda *a, **k: ({"000001.SZ"}, {}))
    old = {"freq": "week", "period": "2026-10-23", "version": [1] * 5}
    current = {
        "freq": "week",
        "period": "2026-10-23",
        "target": str(root / "current.parquet"),
        "version": [2] * 5,
        "rows": 2,
    }
    monkeypatch.setattr(
        update,
        "execute_daily",
        lambda **kwargs: [
            {"files": [old], "historical_only": True, "current_files": []}
        ],
    )
    monkeypatch.setattr(
        update, "_current_period_anchor", lambda *a, **k: (current, None)
    )
    context = NS(
        partition_key="2026-10-23",
        instance=object(),
        log=NS(info=lambda _: None),
    )
    config = NS(intent="daily", automatic_intent_date="2026-10-22")
    lake = NS(root=lambda: root, ensure_available_for_run=lambda: None)
    result = update.deliver_asset(context, config, lake, "week")
    assert result.metadata["goldenshare/period_file_version"].value == [2] * 5
    assert result.metadata["dagster/row_count"] == 2


def test_daily_partition_mismatch_stops_before_scope_or_source(tmp_path):
    context = NS(partition_key="2026-10-30")
    config = NS(intent="daily", automatic_intent_date="2026-10-20")
    lake = NS(
        root=lambda: tmp_path / "lake",
        ensure_available_for_run=lambda: pytest.fail("mismatched run touched lake"),
    )
    with pytest.raises(ValueError, match="period_daily_partition_mismatch"):
        update.deliver_asset(context, config, lake, "week")


def test_ack_rejects_wrong_execution_directory_and_root():
    from pathlib import Path

    with _scenario(successor=True) as case:
        confirmation = _confirm(case)
        run = Path(case["old"]["path"])
        state_path = case["staging"] / "stock_period/daily.json"
        before = state_path.read_bytes()
        with pytest.raises(ValueError, match="period_event_run_path_invalid"):
            update.acknowledge_period_delivery(
                run.parent.parent / "outside" / run.name,
                confirmation,
                root=case["root"],
                staging=case["staging"],
            )
        other_root = case["root"].parent / "other-lake"
        other_root.mkdir()
        with pytest.raises(ValueError, match="period_delivery_control_changed"):
            update.acknowledge_period_delivery(
                run, confirmation, root=other_root, staging=case["staging"]
            )
        assert state_path.read_bytes() == before


def test_closed_current_file_is_consumed_before_ack_without_replanning(
    tmp_path, monkeypatch
):
    from pathlib import Path

    from tests.test_stock_period_delivery_confirmation import _emit

    kw = daily_fixture(tmp_path)
    state_path = kw["staging"] / "stock_period/daily.json"
    initial = raw.read_json(state_path)
    result = update.execute_daily(**kw, transport=daily_source)[0]
    daily = raw.read_json(state_path)
    pending = daily["pending_work"][result["run_id"]]
    pending["consumed"] = False
    daily.update(
        factor_through=initial["factor_through"],
        last_refresh=initial["last_refresh"],
        completed_through=initial["completed_through"],
    )
    raw.atomic_json(state_path, daily)
    directory = tmp_path / "isolated-instance"
    directory.mkdir()
    (directory / "dagster.yaml").write_text("telemetry:\n  enabled: false\n")
    run = Path(result["path"])
    with dg.DagsterInstance.local_temp(str(directory)) as instance:
        _emit(instance, result)

        def confirmation(path):
            return update.confirm_period_delivery(
                instance, path, root=kw["root"], staging=kw["staging"]
            )

        proof = confirmation(run)
        assert proof["events_complete"] and not proof["historical_only"]
        update.acknowledge_period_delivery(
            run, proof, root=kw["root"], staging=kw["staging"]
        )
        assert raw.read_json(run / "manifest.json")["phase"] == "events_complete"
        assert not raw.read_json(state_path)["pending_work"][result["run_id"]]["consumed"]
        monkeypatch.setattr(
            update, "_daily_work", lambda *a, **k: pytest.fail("same intent replanned")
        )
        update.execute_daily(
            **kw,
            confirm_delivery=confirmation,
            transport=lambda _: pytest.fail("source repeated after file completion"),
        )
    final = raw.read_json(state_path)
    assert not final["pending_work"]
    assert final["factor_through"] == "2026-10-16"
    assert final["last_refresh"]["week"] == "2026-10-16"


@pytest.mark.parametrize("fault", ["failed", "old_binding", "nonblocking"])
def test_raw_report_does_not_replace_real_bad_checks(fault):
    from orchestrator.defs.asset_guards.stock_period_silver_readiness import (
        raw_check_names,
    )
    from orchestrator.defs.bootstrap.stock_period_history_cli import _run_reporting
    from tests.test_stock_period_check_evidence import evaluate
    from tests.test_stock_period_delivery_confirmation import _notice

    with _scenario(successor=False, seed_events=True) as case:
        item = case["old"]["files"][0]
        asset = dg.AssetKey("raw_tushare_stk_period_bar_adj_week")
        names = raw_check_names("week")
        key = ("week", "2026-10-23")
        target = case["seed_mats"][key] if fault == "old_binding" else case["old_mats"][key]
        _run_reporting(
            case["instance"],
            lambda context: evaluate(
                case["instance"],
                context,
                names,
                target,
                asset=asset,
                passed=fault != "failed",
                blocking=fault != "nonblocking",
            ),
        )
        notice = _notice(case["old"], "week")
        assert not update.report_file_events(
            case["instance"], item, completion=notice, write=False
        )
        before = case["instance"].fetch_materializations(
            dg.AssetRecordsFilter(asset, asset_partitions=[item["period"]]), limit=20
        ).records
        storage = case["instance"].event_log_storage
        from dagster._core.event_api import PartitionKeyFilter

        check_key = dg.AssetCheckKey(asset, names[0])
        checks_before = storage.get_asset_check_execution_history(
            check_key, limit=20, partition_filter=PartitionKeyFilter(key=item["period"])
        )

        @dg.op
        def attempt(context):
            return update.report_file_events(
                case["instance"], item, completion=notice, context=context
            )

        @dg.job
        def real_raw_report_attempt():
            attempt()

        result = real_raw_report_attempt.execute_in_process(
            instance=case["instance"], raise_on_error=False
        )
        assert not result.success
        failure = next(event for event in result.all_events if event.is_step_failure)
        assert "period_event_checks_invalid" in failure.step_failure_data.error.to_string()
        assert case["instance"].fetch_materializations(
            dg.AssetRecordsFilter(asset, asset_partitions=[item["period"]]), limit=20
        ).records == before
        assert storage.get_asset_check_execution_history(
            check_key, limit=20, partition_filter=PartitionKeyFilter(key=item["period"])
        ) == checks_before


@pytest.mark.parametrize("missing", ["checks", "notification"])
def test_two_frequency_delivery_cannot_close_with_one_frequency_missing(missing):
    from pathlib import Path

    from tests.test_stock_period_delivery_confirmation import _emit, _emit_checks

    with _scenario(
        frequencies=("week", "month"),
        successor=False,
        old_checks="none" if missing == "checks" else "all",
        old_notice=missing == "checks",
    ) as case:
        week = next(item for item in case["old"]["files"] if item["freq"] == "week")
        if missing == "checks":
            _emit_checks(
                case["instance"], week, case["old_mats"][("week", "2026-10-23")],
                passed=True,
            )
        else:
            _emit(case["instance"], {**case["old"], "files": [week]})
        state_path = case["staging"] / "stock_period/daily.json"
        before = state_path.read_bytes()
        proof = _confirm(case)
        assert len(proof["files"]) == 2
        assert not proof["events_complete"]
        assert proof["reason"] == ("missing_checks" if missing == "checks" else "missing_events")
        with pytest.raises(ValueError, match="period_delivery_confirmation_invalid"):
            update.acknowledge_period_delivery(
                Path(case["old"]["path"]), proof,
                root=case["root"], staging=case["staging"],
            )
        assert state_path.read_bytes() == before
        assert raw.read_json(Path(case["old"]["path"]) / "manifest.json")["phase"] == "files_complete"


def test_two_explicit_successors_preserve_original_history_and_current_file():
    import json
    from pathlib import Path

    from orchestrator.defs.bootstrap.stock_period_history import run_period
    from tests.test_stock_period_delivery_confirmation import SOURCE_FIELDS, _emit

    with _scenario(successor=True) as case:
        state_path = case["staging"] / "stock_period/daily.json"
        pending_state = raw.read_json(state_path)
        # Construct the pre-fix history, not a production bypass: each published
        # version is produced and registered for real in this isolated instance.
        raw.atomic_json(state_path, {**pending_state, "pending_work": {}})
        saved = raw.read_json(Path(case["old"]["path"]) / "manifest.json")
        intent = {
            **saved["identity"]["intent"],
            "asof": "2026-10-22",
            "request_id": "third-22",
        }

        def source(params):
            return json.dumps(
                {
                    "code": 0,
                    "data": {
                        "fields": SOURCE_FIELDS,
                        "items": [
                            ["000001.SZ", "20261023", "20261022", "week"]
                            + ["4.0000"] * 17
                        ],
                    },
                }
            ).encode()

        third = run_period(
            root=case["root"], staging=case["staging"], listed=case["listed"],
            aliases=case["aliases"], policy=case["policy"], intent=intent,
            transport=source,
        )
        _emit(case["instance"], third)
        raw.atomic_json(state_path, pending_state)
        target = third["files"][0]["target"]
        version = raw.file_version(target)
        proof = _confirm(case)
        assert proof["events_complete"] and proof["historical_only"]
        chain = proof["file_evidence"][("week", "2026-10-23")]["successors"]
        assert [link["raw_execution_id"] for link in chain] == [
            case["new"]["run_id"], third["run_id"]
        ]
        update.acknowledge_period_delivery(
            Path(case["old"]["path"]), proof,
            root=case["root"], staging=case["staging"],
        )
        assert raw.file_version(target) == version
        assert not raw.read_json(state_path)["pending_work"]
