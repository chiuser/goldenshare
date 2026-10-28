"""LLD12.12.4 daily RSS recovery; real tiny producers, literal RSS samples.

HTTP follows the existing doc365-shaped daily_source fixture. RSS observations
replace allocation of GiBs; isolated SDK coverage never uses formal resources.
"""

import hashlib
from copy import deepcopy
from types import SimpleNamespace as NS

import dagster as dg
import pytest

from orchestrator.defs import stock_period_update as update
from orchestrator.defs.bootstrap import stock_period_history as history
from orchestrator.defs.io import stock_period_raw as raw
from orchestrator.defs.run_contracts import stock_period as contract
from tests.test_stock_period_combined import A, B, row, wire
from tests.test_stock_period_recovery import daily_fixture, daily_source

GIB = 1024**3
TAG = "goldenshare/stock_period_rss_limit_gib"


def test_explicit_original_daily_reexecution_tag_selects_eight_gib():
    context = NS(run=NS(
        tags={TAG: "8"}, parent_run_id="failed-original",
        job_name="raw_stk_period_bar_adj_week_update_job",
    ))
    config = NS(intent="daily", automatic_intent_date="2026-10-16")
    assert update._runtime_rss_bytes(context, config, "week") == 8 * GIB


def tagged_context(**changes):
    return NS(run=NS(**{
        "tags": {TAG: "8"}, "parent_run_id": "failed-original",
        "job_name": "raw_stk_period_bar_adj_week_update_job", **changes,
    }))


def source_facts(run):
    return {
        str(path): (raw.file_version(path), hashlib.sha256(path.read_bytes()).hexdigest())
        for path in (run / "source").rglob("*") if path.is_file()
    }


def freeze_daily(kw):
    days = update.calendar_days(kw["root"], kw["staging"] / "test-calendar", kw["policy"])
    work = update._daily_work(
        kw["staging"], root=kw["root"], today=kw["today"], freq=kw["freq"],
        listed=kw["listed"], aliases=kw["aliases"], days=days, policy=kw["policy"],
        cancel=lambda: False, progress=lambda _: None,
    )
    run_id = contract.execution_id(work["intent"]["request_id"])
    state = update.daily_state(kw["staging"])
    state.setdefault("pending_work", {})[run_id] = work
    raw.atomic_json(kw["staging"] / "stock_period/daily.json", state)
    return work, kw["staging"] / "stock_period/runs" / run_id


def work_arguments(kw, work):
    return {
        "root": kw["root"], "staging": kw["staging"], "intent": work["intent"],
        "listed": set(work["listed"]), "aliases": work["aliases"],
        "confirmed_retired": work["confirmed_retired"], "policy": kw["policy"],
    }


def fail_copy_at_seven_gib(monkeypatch):
    memory = {"high": False, "rss": 7 * GIB}
    original = raw.execute

    def measured(*args, **kwargs):
        if kwargs.get("stage") == "partition_copy":
            memory["high"] = True
        return original(*args, **kwargs)

    monkeypatch.setattr(raw, "execute", measured)
    monkeypatch.setattr(raw, "current_rss_bytes", lambda: memory["rss"] if memory["high"] else 1)
    return memory


def stopped_daily(tmp_path, monkeypatch):
    kw = daily_fixture(tmp_path)
    memory = fail_copy_at_seven_gib(monkeypatch)
    calls = []

    def source(params):
        calls.append(params)
        return daily_source(params)

    with pytest.raises(ValueError, match="period_process_memory_exceeded"):
        update.execute_daily(**kw, transport=source)
    work = next(iter(update.daily_state(kw["staging"])["pending_work"].values()))
    run = kw["staging"] / "stock_period/runs" / contract.execution_id(work["intent"]["request_id"])
    assert len(calls) == 2 and all(p["freq"] == "week" for p in calls)
    assert not (run / "build/week/copy.json").exists()
    return kw, work, run, calls, memory


def test_daily_copy_resumes_at_eight_without_redownloading_successful_pages(tmp_path, monkeypatch):
    kw, _, run, calls, _ = stopped_daily(tmp_path, monkeypatch)
    before = raw.read_json(run / "manifest.json")
    sources = source_facts(run)
    progress = []

    def only_missing_source(params):
        assert params["freq"] == "month", "completed week source was requested again"
        calls.append(params)
        return daily_source(params)

    results = update.execute_daily(
        **kw, transport=only_missing_source, runtime_rss_bytes=8 * GIB,
        progress=progress.append,
    )
    assert results and len(calls) == 3
    after = raw.read_json(run / "manifest.json")
    assert after["identity"] == before["identity"]
    assert after["identity_hash"] == before["identity_hash"]
    assert after["identity"]["policy"]["rss_bytes"] == 4 * GIB
    assert all(source_facts(run)[path] == facts for path, facts in sources.items())
    assert all(raw.read_json(path)["identity"]["policy"]["rss_bytes"] == 4 * GIB
               for path in (run / "source").glob("*/complete.json"))
    pending = update.daily_state(kw["staging"])["pending_work"][run.name]
    assert pending["policy"]["rss_bytes"] == 4 * GIB
    memory = [p for p in progress if p.get("stage") == "process_memory"]
    assert memory[-1]["rss_limit_bytes"] == 8 * GIB
    assert memory[-1]["frozen_rss_limit_bytes"] == 4 * GIB
    assert memory[-1]["observed_peak_rss_bytes"] == 7 * GIB
    with pytest.raises(ValueError, match="period_process_memory_exceeded"):
        raw.check_memory(kw["policy"])


def test_existing_daily_pending_can_create_first_month_manifest_with_eight_gib(tmp_path, monkeypatch):
    kw = daily_fixture(tmp_path)
    kw["freq"] = "month"
    state = update.daily_state(kw["staging"])
    state["factor_through"] = "2026-10-16"
    raw.atomic_json(kw["staging"] / "stock_period/daily.json", state)
    work, run = freeze_daily(kw)
    assert work["intent"]["codes"] == [] and not (run / "manifest.json").exists()
    monkeypatch.setattr(raw, "current_rss_bytes", lambda: 7 * GIB)
    calls = []

    def current_month(params):
        calls.append(params)
        # The real producer contract uses a month-wide request, while a
        # single-stock historical unit may contain September and October.
        assert params == {"freq": "month", "limit": 6000, "offset": 0,
                          "start_date": "20261001", "end_date": "20261031"}
        return wire([row(A, "20261031", "month", "3"), row(B, "20261031", "month", "8")])

    result = update.execute_daily(**kw, transport=current_month, runtime_rss_bytes=8 * GIB)
    assert len(calls) == 1 and len(result[-1]["files"]) == 1
    saved = raw.read_json(run / "manifest.json")
    assert saved["identity"]["intent"] == work["intent"]
    assert saved["identity"]["policy"]["rss_bytes"] == 4 * GIB


def test_daily_history_mode_with_frozen_asof_can_use_runtime_rss(tmp_path, monkeypatch):
    kw = daily_fixture(tmp_path)
    state = update.daily_state(kw["staging"])
    state["last_refresh"]["week"] = "2026-10-16"
    state["completed_through"]["week"] = "2026-10-16"
    raw.atomic_json(kw["staging"] / "stock_period/daily.json", state)
    work, run = freeze_daily(kw)
    assert work["intent"]["mode"] == "history"
    assert work["intent"]["asof"] == "2026-10-16"
    assert work["intent"]["codes"] == [A]
    monkeypatch.setattr(raw, "current_rss_bytes", lambda: 7 * GIB)
    result = history.run_period(**work_arguments(kw, work), transport=daily_source,
                                runtime_rss_bytes=8 * GIB)
    assert result["path"] == str(run)
    assert raw.read_json(run / "manifest.json")["identity"]["policy"]["rss_bytes"] == 4 * GIB


@pytest.mark.parametrize("fault", ["missing", "frequency", "date", "request", "kind", "identity"])
def test_daily_rss_override_rejects_unbound_work_before_source_or_candidates(tmp_path, monkeypatch, fault):
    kw = daily_fixture(tmp_path)
    work, run = freeze_daily(kw)
    arguments = work_arguments(kw, work)
    state = update.daily_state(kw["staging"])
    if fault == "missing":
        state["pending_work"].clear()
    elif fault == "frequency":
        state["pending_work"][run.name]["frequency"] = "month"
    elif fault == "date":
        state["pending_work"][run.name]["intent"]["asof"] = "2026-10-19"
    elif fault == "request":
        state["pending_work"][run.name]["intent"]["request_id"] = "wrong-request"
    elif fault == "kind":
        state["pending_work"][run.name]["kind"] = "history"
    else:
        arguments["aliases"] = {B: B}
    raw.atomic_json(kw["staging"] / "stock_period/daily.json", state)
    before = (kw["staging"] / "stock_period/daily.json").read_bytes()
    monkeypatch.setattr(history, "capture_unit", lambda **k: pytest.fail("invalid work reached source"))
    monkeypatch.setattr(history, "assemble", lambda *a, **k: pytest.fail("invalid work reached candidates"))
    with pytest.raises(ValueError, match="period_runtime_rss_daily_invalid"):
        history.run_period(**arguments, runtime_rss_bytes=8 * GIB)
    assert (kw["staging"] / "stock_period/daily.json").read_bytes() == before
    assert not (run / "manifest.json").exists() and not (run / "source").exists()


def test_existing_daily_manifest_identity_drift_keeps_original_frozen_record(tmp_path, monkeypatch):
    kw, work, run, _, _ = stopped_daily(tmp_path, monkeypatch)
    changed = deepcopy(raw.read_json(run / "manifest.json"))
    changed["identity"]["aliases"] = {A: B}
    changed["identity_hash"] = contract.digest(changed["identity"])
    raw.atomic_json(run / "manifest.json", changed)
    before = (run / "manifest.json").read_bytes()
    sources = source_facts(run)
    with pytest.raises(ValueError, match="period_manifest_changed"):
        history.run_period(**work_arguments(kw, work), runtime_rss_bytes=8 * GIB,
                           transport=lambda _: pytest.fail("changed manifest requested source"))
    assert (run / "manifest.json").read_bytes() == before
    assert source_facts(run) == sources


def test_explicit_history_cannot_borrow_daily_runtime_override(tmp_path, monkeypatch):
    kw = daily_fixture(tmp_path)
    intent = {"version": contract.VERSION, "mode": "history", "frequencies": ["week", "month"],
              "codes": [A], "request_id": "manual-runtime"}
    before = (kw["staging"] / "stock_period/daily.json").read_bytes()
    monkeypatch.setattr(history, "capture_unit", lambda **k: pytest.fail("manual history reached source"))
    monkeypatch.setattr(history, "assemble", lambda *a, **k: pytest.fail("manual history reached candidates"))
    with pytest.raises(ValueError, match="period_runtime_rss_resume_required"):
        history.run_period(root=kw["root"], staging=kw["staging"], listed=kw["listed"],
                           aliases=kw["aliases"], intent=intent, policy=kw["policy"],
                           runtime_rss_bytes=8 * GIB)
    assert (kw["staging"] / "stock_period/daily.json").read_bytes() == before
    assert not (kw["staging"] / "stock_period/runs" / contract.execution_id("manual-runtime")).exists()


@pytest.mark.parametrize("value", ["0", "-1", "08", "8.0", " 8", "８", ""])
def test_invalid_runtime_tag_rejects_before_reference_reads(tmp_path, value):
    context = tagged_context(tags={TAG: value})
    context.partition_key = "2026-10-16"
    lake = NS(root=lambda: tmp_path / "lake",
              ensure_available_for_run=lambda: pytest.fail("bad tag touched lake"))
    config = NS(intent="daily", automatic_intent_date="2026-10-16")
    with pytest.raises(ValueError, match="period_runtime_rss_tag_invalid"):
        update.deliver_asset(context, config, lake, "week")


@pytest.mark.parametrize("fault", ["first_run", "job", "frequency", "history", "date"])
def test_runtime_tag_requires_original_daily_job_and_explicit_date(tmp_path, fault):
    context = tagged_context()
    context.run.root_run_id = "failed-original"
    context.instance = NS(get_run_record_by_id=lambda _: pytest.fail("missing explicit date read old run"))
    context.partition_key = "2026-10-16"
    config = NS(intent="daily", automatic_intent_date="2026-10-16")
    freq = "week"
    if fault == "first_run":
        context.run.parent_run_id = None
    elif fault == "job":
        context.run.job_name = "other_job"
    elif fault == "frequency":
        context.run.job_name = "raw_stk_period_bar_adj_month_update_job"
    elif fault == "history":
        config.intent = "history"
    else:
        config.automatic_intent_date = None
    lake = NS(root=lambda: tmp_path / "lake",
              ensure_available_for_run=lambda: pytest.fail("bad runtime scope touched lake"))
    with pytest.raises(ValueError, match="period_runtime_rss_run_invalid"):
        if fault == "date":
            update._runtime_rss_bytes(context, config, freq)
        else:
            update.deliver_asset(context, config, lake, freq)


def test_no_runtime_tag_leaves_default_and_config_schema_unchanged():
    from orchestrator.defs.run_contracts.configs import StockPeriodRawConfig

    assert contract.STOCK_PERIOD_RUNTIME_RSS_GIB_TAG == TAG
    assert update._runtime_rss_bytes(NS(run=NS(tags={})), NS(), "week") is None
    assert "runtime_rss_bytes" not in StockPeriodRawConfig.model_fields
    assert contract.DEFAULT_POLICY.rss_bytes == 4 * GIB


def test_more_than_eight_gib_still_stops_without_new_source(tmp_path, monkeypatch):
    kw, _, run, _, memory = stopped_daily(tmp_path, monkeypatch)
    sources = source_facts(run)
    memory["rss"] = 8 * GIB + 1
    with pytest.raises(ValueError, match="period_process_memory_exceeded"):
        update.execute_daily(**kw, runtime_rss_bytes=8 * GIB,
                             transport=lambda _: pytest.fail("over-limit execution requested source"))
    assert source_facts(run) == sources
    with pytest.raises(ValueError, match="period_process_memory_exceeded"):
        raw.check_memory(kw["policy"])


@pytest.mark.parametrize("error", [RuntimeError("failed"), raw.PeriodCancelled("cancelled")])
def test_eight_gib_scope_resets_after_exception_and_cancel(monkeypatch, error):
    monkeypatch.setattr(raw, "current_rss_bytes", lambda: 7 * GIB)
    progress = []
    with pytest.raises(type(error), match=str(error)), raw.process_memory_budget(
        contract.DEFAULT_POLICY, 8 * GIB, progress=progress.append,
    ):
        raw.check_memory(contract.DEFAULT_POLICY)
        raise error
    assert progress[-1]["status"] == "failed"
    assert progress[-1]["frozen_rss_limit_bytes"] == 4 * GIB
    assert progress[-1]["rss_limit_bytes"] == 8 * GIB
    with pytest.raises(ValueError, match="period_process_memory_exceeded"):
        raw.check_memory(contract.DEFAULT_POLICY)


def test_original_sdk_job_reads_stored_parent_and_rss_tag_without_changing_config(tmp_path, monkeypatch):
    from dagster._core.definitions.job_base import InMemoryJob
    from dagster._core.execution.api import execute_run

    from orchestrator.defs import paths
    from orchestrator.defs.assets import stock_monthly, stock_weekly
    from orchestrator.defs.checks import stock_weekly_checks
    from orchestrator.defs.jobs import stock_weekly as weekly_jobs
    from orchestrator.defs.resources import LakeRootResource
    from orchestrator.defs.run_contracts.stock_weekly import (
        StockWeeklySource,
        weekly_check_names,
    )

    kw = daily_fixture(tmp_path)
    fail_copy_at_seven_gib(monkeypatch)
    monkeypatch.setattr(paths, "DEFAULT_LAKE_STAGING_ROOT", str(kw["staging"]))
    monkeypatch.setattr(LakeRootResource, "ensure_available_for_run", lambda self: None)
    # This isolated boundary substitutes only the already-verified reference
    # scope and HTTP. Daily planning, capture, COPY, publish and native checks
    # execute their real implementations against the fixture's small files.
    monkeypatch.setattr(history, "load_scope", lambda *a, **k: (kw["listed"], kw["aliases"]))
    calls = []

    def source(params):
        calls.append(params)
        return daily_source(params)

    monkeypatch.setattr(history, "HttpPage", lambda **k: source)
    definitions = dg.Definitions(
        assets=[stock_weekly.raw_tushare_stk_period_bar_adj_week,
                stock_monthly.raw_tushare_stk_period_bar_adj_month],
        asset_checks=[getattr(stock_weekly_checks, name)
                      for name in weekly_check_names(StockWeeklySource.PRIMARY_ADJUSTED)],
        jobs=[weekly_jobs.raw_stk_period_bar_adj_week_update_job],
        resources={"lake_root": LakeRootResource(root_path=str(kw["root"]))},
    )
    configuration = {"ops": {"raw_tushare_stk_period_bar_adj_week": {
        "config": {"automatic_intent_date": "2026-10-16"},
    }}}
    instance_path = tmp_path / "sdk-instance"
    instance_path.mkdir()
    (instance_path / "dagster.yaml").write_text("telemetry:\n  enabled: false\n")
    with dg.DagsterInstance.local_temp(str(instance_path)) as instance:
        instance.add_dynamic_partitions("cn_a_stock_week_ends", ["2026-10-16"])
        job = definitions.resolve_job_def("raw_stk_period_bar_adj_week_update_job")
        failed = job.execute_in_process(
            instance=instance, partition_key="2026-10-16", run_config=configuration,
            raise_on_error=False,
        )
        assert not failed.success
        assert any(event.is_step_failure and "period_process_memory_exceeded"
                   in event.step_failure_data.error.to_string() for event in failed.all_events)
        assert len(calls) == 2
        work = next(iter(update.daily_state(kw["staging"])["pending_work"].values()))
        run = kw["staging"] / "stock_period/runs" / contract.execution_id(work["intent"]["request_id"])
        saved, pages = raw.read_json(run / "manifest.json"), source_facts(run)
        # Create the child through the real SDK with stored parent/root fields.
        # This verifies job/tag wiring; it does not claim a GraphQL or PG test.
        child = instance.create_run_for_job(
            job_def=job, run_config=configuration,
            parent_run_id=failed.run_id, root_run_id=failed.run_id,
            tags={**failed.dagster_run.tags, TAG: "8"},
        )
        result = execute_run(InMemoryJob(job), child, instance, raise_on_error=True)
        assert result.success
        stored = instance.get_run_by_id(child.run_id)
        assert stored.parent_run_id == failed.run_id and stored.tags[TAG] == "8"
        assert stored.run_config == configuration
        checks = [event.event_specific_data for event in result.all_events
                  if event.event_type_value == "ASSET_CHECK_EVALUATION"]
        assert len(checks) == 3 and all(check.passed for check in checks)
        assert len(calls) == 3 and calls[-1]["freq"] == "month"
        assert all(source_facts(run)[path] == facts for path, facts in pages.items())
        final = raw.read_json(run / "manifest.json")
        assert final["identity"] == saved["identity"]
        assert final["identity_hash"] == saved["identity_hash"]
        assert final["identity"]["policy"]["rss_bytes"] == 4 * GIB
