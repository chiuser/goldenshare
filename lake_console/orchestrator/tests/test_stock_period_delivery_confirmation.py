"""LLD12 historical confirmation: actual Raw producer + actual SDK/SQLite events.

Only the HTTP response is replaced. run_period creates real tiny candidates,
committed/complete receipts and baseline. A tiny real Dagster run writes the
normal SDK materialization/check/observation payloads. The deliberately stale
daily pending is installed after the two producer versions to reproduce the
already-observed pre-fix state, without bypassing the new write admission guard.
No formal instance, credentials, mounted lake or remote source is accessed.
"""

import json
import tempfile
from contextlib import contextmanager
from pathlib import Path

import dagster as dg
import pytest
import sqlalchemy as sa
from dagster._core.definitions.asset_checks.asset_check_evaluation import (
    AssetCheckEvaluation,
    AssetCheckEvaluationTargetMaterializationData,
)
from dagster._core.events import DagsterEvent
from dagster._core.storage.event_log.schema import SqlEventLogStorageTable as Events

from orchestrator.defs import stock_period_update as update
from orchestrator.defs.asset_guards.stock_period_silver_readiness import raw_check_names
from orchestrator.defs.bootstrap.stock_period_history import run_period, writer
from orchestrator.defs.io import stock_period_raw as raw
from orchestrator.defs.run_contracts.stock_period import (
    VERSION,
    StockPeriodPolicy,
    completion_notice,
    completion_reference,
)

SOURCE_FIELDS = (
    "ts_code", "trade_date", "end_date", "freq", "open", "high", "low", "close",
    "pre_close", "open_qfq", "high_qfq", "low_qfq", "close_qfq", "open_hfq",
    "high_hfq", "low_hfq", "close_hfq", "vol", "amount", "change", "pct_chg",
)
POLICY = StockPeriodPolicy(
    duckdb_memory="256MiB", workspace_bytes=1024**3, spill_bytes=128 * 1024**2,
)


def _metadata(item, notice):
    return {
        "dagster/uri": item["target"], "dagster/row_count": item["rows"],
        "goldenshare/period_file_version": dg.MetadataValue.json(item["version"]),
        "goldenshare/period_completion": dg.MetadataValue.json(notice),
    }


def _notice(result, frequency):
    saved = raw.read_json(Path(result["path"]) / "manifest.json")
    return completion_notice(
        completion_reference(result["run_id"], saved["file_receipt_hash"], frequency),
        frequency, sum(item["freq"] == frequency for item in result["files"]),
    )


def _check_event(context, item, materialization, *, passed=True):
    asset = dg.AssetKey(f"raw_tushare_stk_period_bar_adj_{item['freq']}")
    for name in raw_check_names(item["freq"]):
        context.instance.report_dagster_event(
            DagsterEvent(
                event_type_value="ASSET_CHECK_EVALUATION", job_name=context.job_name,
                step_key=context.get_step_execution_context().step.key,
                event_specific_data=AssetCheckEvaluation(
                    asset_key=asset, check_name=name, partition=item["period"],
                    passed=passed, blocking=True,
                    target_materialization_data=AssetCheckEvaluationTargetMaterializationData(
                        storage_id=materialization.storage_id,
                        run_id=materialization.event_log_entry.run_id,
                        timestamp=materialization.event_log_entry.timestamp,
                    ),
                ),
            ), run_id=context.run_id,
        )


def _emit(instance, result, *, checks="all", notice=True, materializations=True):
    produced = {}

    @dg.op
    def report(context):
        for item in result["files"]:
            if not materializations:
                continue
            asset = dg.AssetKey(f"raw_tushare_stk_period_bar_adj_{item['freq']}")
            context.log_event(dg.AssetMaterialization(
                asset_key=asset, partition=item["period"],
                metadata=_metadata(item, _notice(result, item["freq"])),
            ))
            mat = context.instance.fetch_materializations(
                dg.AssetRecordsFilter(asset, asset_partitions=[item["period"]]), limit=1,
            ).records[0]
            produced[(item["freq"], item["period"])] = mat
            file_checks = checks.get(item["freq"], "all") if isinstance(checks, dict) else checks
            if file_checks != "none":
                _check_event(context, item, mat, passed=file_checks != "failed")
        if notice:
            for frequency in {item["freq"] for item in result["files"]}:
                context.log_event(dg.AssetObservation(
                    asset_key=f"raw_tushare_stk_period_bar_adj_{frequency}",
                    metadata={"goldenshare/period_completion": dg.MetadataValue.json(_notice(result, frequency))},
                ))

    @dg.job
    def delivery_event_fixture():
        report()

    assert delivery_event_fixture.execute_in_process(instance=instance).success
    return produced


def _emit_checks(instance, item, target, *, passed):
    @dg.op
    def report(context):
        _check_event(context, item, target, passed=passed)

    @dg.job
    def changed_check_fixture():
        report()

    assert changed_check_fixture.execute_in_process(instance=instance).success


@contextmanager
def _scenario(*, frequencies=("week",), successor=True, old_checks="all", old_notice=True,
              late_old_failure=False, seed_events=False, old_materialization=True,
              successor_frequencies=("week",)):
    with tempfile.TemporaryDirectory(prefix="period-delivery-", dir="/private/tmp") as directory:
        base = Path(directory)
        root, staging = base / "lake", base / "staging"
        requests = []

        def source(asof, value):
            def transport(params):
                requests.append(dict(params))
                day = "20261023" if params["freq"] == "week" else "20261031"
                # Independent literal wire contract: one stock, one period, 21 columns.
                row = ["000001.SZ", day, asof, params["freq"]] + [value] * 17
                return json.dumps({"code": 0, "data": {"fields": SOURCE_FIELDS, "items": [row]}}).encode()
            return transport

        common = {"root": root, "staging": staging, "listed": {"000001.SZ"},
                  "aliases": {}, "policy": POLICY}
        seed = run_period(**common, intent={
            "version": VERSION, "mode": "bootstrap", "frequencies": ["week", "month"],
            "codes": ["000001.SZ"], "request_id": "seed",
        }, transport=source("20261019", "1.0000"))
        baseline = staging / "stock_period/baseline.json"
        raw.atomic_json(baseline, {**raw.read_json(baseline), "status": "ready"})
        instance_directory = base / "instance"
        instance_directory.mkdir()
        (instance_directory / "dagster.yaml").write_text("telemetry:\n  enabled: false\n")
        with dg.DagsterInstance.local_temp(str(instance_directory)) as instance:
            seed_mats = _emit(instance, seed) if seed_events else {}
            periods = {frequency: ["2026-10-23" if frequency == "week" else "2026-10"]
                       for frequency in frequencies}
            old_intent = {"version": VERSION, "mode": "upsert", "frequencies": list(frequencies),
                          "codes": [], "periods": periods, "request_id": "old-20", "asof": "2026-10-20"}
            old = run_period(**common, intent=old_intent, transport=source("20261020", "2.0000"))
            assert len(old["files"]) == len(frequencies)
            assert all(item["rows"] == 1 for item in old["files"])
            old_mats = _emit(instance, old, checks=old_checks, notice=old_notice,
                             materializations=old_materialization)
            if late_old_failure:
                _emit_checks(instance, old["files"][0], old_mats[("week", "2026-10-23")], passed=False)
            new = None
            if successor:
                new = run_period(**common, intent={
                    "version": VERSION, "mode": "upsert", "frequencies": list(successor_frequencies),
                    "codes": [], "periods": {frequency: periods[frequency] for frequency in successor_frequencies},
                    "request_id": "new-21", "asof": "2026-10-21",
                }, transport=source("20261021", "3.0000"))
                _emit(instance, new)
                assert new["files"][0]["target_preimage"] == old["files"][0]["version"]
            daily = {
                "completed_through": {"week": "2026-10-16", "month": "2026-09"},
                "last_refresh": {"week": "2026-10-21", "month": "2026-10-20"},
                "factor_through": "2026-10-21", "unrelated": {"keep": 7},
                "pending_work": {old["run_id"]: {
                    "intent": old_intent, "frequency": "week", "consumed": True,
                    "policy": POLICY.payload(), "listed": ["000001.SZ"], "aliases": {},
                    "confirmed_retired": [], "pending": periods["week"], "holidays": [],
                }},
            }
            raw.atomic_json(staging / "stock_period/daily.json", daily)
            yield {
                **common, "instance": instance, "old": old, "new": new,
                "requests": requests, "daily": daily, "old_mats": old_mats, "seed_mats": seed_mats,
            }


def _confirm(case, **kwargs):
    return update.confirm_period_delivery(
        case["instance"], Path(case["old"]["path"]), root=case["root"], staging=case["staging"],
        cancel=lambda: False, **kwargs,
    )


def _ack(case, confirmation):
    return update.acknowledge_period_delivery(
        Path(case["old"]["path"]), confirmation, root=case["root"], staging=case["staging"], cancel=lambda: False,
    )


def _event_count(instance):
    with instance.event_log_storage.index_connection() as connection:
        return connection.execute(sa.select(sa.func.count()).select_from(Events)).scalar_one()


def test_old_real_delivery_closes_without_rewriting_new_file_or_business_events(monkeypatch):
    with _scenario() as case:
        old_run = Path(case["old"]["path"])
        immutable = {name: (old_run / name).read_bytes() for name in ("complete.json", "committed/week/2026-10-23.json")}
        identity = raw.read_json(old_run / "manifest.json")["identity_hash"]
        version = raw.file_version(case["old"]["files"][0]["target"])
        request_count, event_count = len(case["requests"]), _event_count(case["instance"])
        monkeypatch.setattr(raw, "connection", lambda *a, **k: pytest.fail("confirmation did business SQL"))
        monkeypatch.setattr(raw, "file_digest", lambda *a, **k: pytest.fail("confirmation hashed Parquet"))
        with writer(case["staging"]):
            confirmed = _confirm(case)
            assert confirmed["events_complete"] is True and confirmed["historical_only"] is True
            evidence = confirmed["file_evidence"][("week", "2026-10-23")]
            assert evidence["materialization_id"] == case["old_mats"][("week", "2026-10-23")].storage_id
            assert len(evidence["checks"]) == 3
            assert evidence["before_event_id"] == evidence["successors"][0]["first_materialization_id"]
            assert _ack(case, confirmed)["pending_removed"] is True
        assert raw.read_json(old_run / "manifest.json")["phase"] == "events_complete"
        assert raw.read_json(old_run / "manifest.json")["identity_hash"] == identity
        assert immutable == {name: (old_run / name).read_bytes() for name in immutable}
        assert raw.file_version(case["old"]["files"][0]["target"]) == version
        assert len(case["requests"]) == request_count and _event_count(case["instance"]) == event_count
        actual_daily = raw.read_json(case["staging"] / "stock_period/daily.json")
        assert actual_daily == {**case["daily"], "pending_work": {}}
        real_stat = update._period_delivery_stat

        def no_old_parquet(path):
            assert Path(path).suffix != ".parquet", "closed history statted an old target"
            return real_stat(path)

        monkeypatch.setattr(update, "_period_delivery_stat", no_old_parquet)
        repeated = _confirm(case)
        assert repeated["events_complete"] and repeated["historical_only"]
        assert repeated["current_files"] == []
        assert _ack(case, repeated)["pending_removed"] is False


@pytest.mark.parametrize("problem", ["missing_checks", "missing_notice", "late_failure", "unknown_target"])
def test_replaced_old_file_cannot_close_without_its_exact_history(problem):
    with _scenario(old_checks="none" if problem == "missing_checks" else "all",
                   old_notice=problem != "missing_notice", late_old_failure=problem == "late_failure") as case:
        if problem == "unknown_target":
            target = Path(case["old"]["files"][0]["target"])
            target.write_bytes(target.read_bytes())  # Intentional unknown replacement in this owned fixture.
        before = raw.read_json(Path(case["old"]["path"]) / "manifest.json")
        with pytest.raises(ValueError, match="period_delivery_(history_missing|checks_invalid|current_file_unknown)"):
            _confirm(case)
        assert raw.read_json(Path(case["old"]["path"]) / "manifest.json") == before
        assert raw.read_json(case["staging"] / "stock_period/daily.json") == case["daily"]


def test_earlier_true_preimage_checks_are_missing_but_late_wrong_binding_is_invalid():
    with _scenario(successor=False, old_checks="none", seed_events=True) as case:
        confirmation = _confirm(case)
        assert confirmation["events_complete"] is False and confirmation["reason"] == "missing_checks"
        assert confirmation["historical_only"] is False
        assert confirmation["current_files"] == case["old"]["files"]
        _emit_checks(case["instance"], case["old"]["files"][0],
                     case["seed_mats"][("week", "2026-10-23")], passed=True)
        with pytest.raises(ValueError, match="period_delivery_checks_invalid"):
            _confirm(case)


def test_missing_original_materialization_does_not_hide_latest_failed_check():
    with _scenario(successor=False, old_checks="none", old_materialization=False,
                   seed_events=True) as case:
        missing = _confirm(case)
        assert missing["events_complete"] is False and missing["reason"] == "missing_events"
        _emit_checks(case["instance"], case["old"]["files"][0],
                     case["seed_mats"][("week", "2026-10-23")], passed=False)
        with pytest.raises(ValueError, match="period_delivery_checks_invalid"):
            _confirm(case)


def test_closed_phase_without_original_checkpoint_is_not_success():
    with _scenario() as case:
        _ack(case, _confirm(case))
        run = Path(case["old"]["path"])
        (run / "events/week/2026-10-23.json").unlink()  # Deliberate isolated evidence corruption.
        with pytest.raises(ValueError, match="period_delivery_checkpoint_changed"):
            _confirm(case)


def test_new_current_file_ack_waits_for_original_file_consumption():
    with _scenario(successor=False) as case:
        daily_path = case["staging"] / "stock_period/daily.json"
        daily = raw.read_json(daily_path)
        daily["pending_work"][case["old"]["run_id"]]["consumed"] = False
        raw.atomic_json(daily_path, daily)
        ready = _confirm(case)
        assert ready["events_complete"] is True and ready["historical_only"] is False
        assert _ack(case, ready)["pending_removed"] is False
        assert raw.read_json(Path(case["old"]["path"]) / "manifest.json")["phase"] == "events_complete"
        assert raw.read_json(daily_path) == daily
        # A resumed closed record cannot consume the daily business watermarks itself.
        with pytest.raises(ValueError, match="period_delivery_consumption_missing"):
            _ack(case, _confirm(case))


def test_week_only_confirmation_does_not_touch_month_or_close_whole_batch(monkeypatch):
    with _scenario(frequencies=("week", "month")) as case:
        real_stat = update._period_delivery_stat

        def no_month(path):
            assert "/month/" not in str(path) and "/month_end=" not in str(path)
            return real_stat(path)

        monkeypatch.setattr(update, "_period_delivery_stat", no_month)
        confirmation = _confirm(case, allowed_frequencies={"week"})
        assert confirmation["events_complete"] is False
        assert confirmation["allowed_events_complete"] is True
        assert confirmation["reason"] == "ok"
        assert set(confirmation["file_evidence"]) == {("week", "2026-10-23")}
        outcome = _ack(case, confirmation)
        assert outcome["allowed_events_complete"] is True
        assert not outcome["events_complete"] and not outcome["pending_removed"]
        run = Path(case["old"]["path"])
        assert raw.read_json(run / "events/week/2026-10-23.json") == {
            key: case["old"]["files"][0][key] for key in ("version", "sha256")
        }
        assert raw.read_json(run / "manifest.json")["phase"] == "files_complete"
        assert raw.read_json(case["staging"] / "stock_period/daily.json") == case["daily"]


def test_ack_refuses_control_drift_and_unconsumed_historical_work():
    with _scenario() as case:
        confirmation = _confirm(case)
        daily_path = case["staging"] / "stock_period/daily.json"
        changed = raw.read_json(daily_path)
        changed["unrelated"]["keep"] = 8
        raw.atomic_json(daily_path, changed)
        with pytest.raises(ValueError, match="control_changed"):
            _ack(case, confirmation)
        changed["pending_work"][case["old"]["run_id"]]["consumed"] = False
        raw.atomic_json(daily_path, changed)
        with pytest.raises(ValueError, match="consumption_missing"):
            _ack(case, _confirm(case))
        assert not (Path(case["old"]["path"]) / "events/week/2026-10-23.json").exists()


@pytest.mark.parametrize("stage", ["file", "completion", "phase", "daily"])
def test_ack_after_each_atomic_write_can_resume_without_new_events_or_source(stage, monkeypatch):
    with _scenario() as case:
        confirmation = _confirm(case)
        real_write = update.atomic_json
        run = Path(case["old"]["path"])
        paths = {
            "file": run / "events/week/2026-10-23.json",
            "completion": run / "events/completion/week.json",
            "phase": run / "manifest.json",
            "daily": case["staging"] / "stock_period/daily.json",
        }
        events, requests = _event_count(case["instance"]), len(case["requests"])

        def failed_after_write(path, value):
            real_write(path, value)
            if Path(path) == paths[stage]:
                raise OSError("interrupted_after_atomic_write")

        monkeypatch.setattr(update, "atomic_json", failed_after_write)
        with pytest.raises(OSError, match="interrupted_after_atomic_write"):
            _ack(case, confirmation)
        monkeypatch.setattr(update, "atomic_json", real_write)
        resumed = _confirm(case)
        assert resumed["events_complete"] is True
        _ack(case, resumed)
        assert raw.read_json(run / "manifest.json")["phase"] == "events_complete"
        assert raw.read_json(case["staging"] / "stock_period/daily.json") == {**case["daily"], "pending_work": {}}
        assert len(case["requests"]) == requests and _event_count(case["instance"]) == events
