"""Four tiny actual Raw/Silver jobs with lost response and durable reconnect.

The source, clock and HTTP adapter are replaced. SQLite events/checks and
Parquet are real. No formal queue, remote source or old recovery is executed.
"""

import json

import pytest

from orchestrator.defs.paths import raw_moneyflow_path, silver_moneyflow_path
from orchestrator.moneyflow_continuation.contract import file_hash
from orchestrator.moneyflow_continuation.execution import apply
from orchestrator.moneyflow_continuation.plan import LAUNCH
from orchestrator.moneyflow_continuation.state import next_action
from orchestrator.moneyflow_continuation.submission import Journal, submit_once
from tests import test_moneyflow_definitions as support
from tests.moneyflow_baseline_support import seed_moneyflow_baseline
from tests.test_moneyflow_continuation_integration import LocalJobsBackend
from tests.test_moneyflow_continuation_plan import AT, plan_for

pytestmark = pytest.mark.usefixtures("isolated_moneyflow_transport")
DAYS = ("2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16")


class FourDayJobsBackend(LocalJobsBackend):
    drop_raw_response = False

    def guard(self, plan, at):
        super().guard(plan, at)
        # Same formal guard accounting as the original four-day test.
        for _ in range(22):
            self.meter.tick()

    def mutate(self, body):
        result = super().mutate(body)
        if (
            self.drop_raw_response
            and body["query"] == LAUNCH
            and body["variables"]["executionParams"]["selector"]["jobName"]
            == "raw_tushare_moneyflow_update_job"
        ):
            self.drop_raw_response = False
            raise OSError("isolated response lost after actual Raw committed")
        return result


def test_four_day_native_files_lost_response_restart_and_zero_repeat(
    tmp_path, monkeypatch, record_property
):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    generator = support.env.__wrapped__(runtime, monkeypatch)
    env = next(generator)
    try:
        for day in ("2026-10-08", "2026-10-09", "2026-10-12"):
            seed_moneyflow_baseline(
                instance=env.instance, lake=env.lake, staging=env.staging,
                dataset="moneyflow", rows=support.sample(), day=day,
            )
        # Literal dates/counts and samples come from the existing source-contract fixture.
        plan = plan_for(("moneyflow",), DAYS)
        unit = plan["units"][0]
        journal = Journal(plan, tmp_path / "control")
        backend = FourDayJobsBackend(env)
        env.source.responses = iter(
            page for day in DAYS for page in support.pages(support.sample(day=day)) * 2
        )
        submit_once(backend, journal, unit, "register", AT)
        backend.drop_raw_response = True
        with pytest.raises(OSError, match="response lost"):
            submit_once(backend, journal, unit, "raw", AT)
        files = journal.read(unit, "raw")
        assert "send_intent" in files and "response" not in files
        assert len(backend.posts) == 2
        code, result = apply(
            backend, plan, root=journal.root, output=lambda _: None, clock=lambda: AT
        )
        assert code == 0 and result["completed"] == 4, result
        snapshots = backend.snapshots(plan["units"], Journal(plan, journal.root))
        assert all(next_action(s) == "complete" for s in snapshots)
        assert all(s[layer]["proof"]["rows"] == 3 for s in snapshots for layer in ("raw", "silver"))
        runs = env.instance.get_runs()
        assert len(runs) == 8 and all(r.status.value == "SUCCESS" for r in runs)
        assert all(r.parent_run_id is None and r.root_run_id is None for r in runs)
        assert set(env.instance.get_dynamic_partitions(unit["partition_set"])) == {
            "2026-09-29", "2026-09-30", "2026-10-08", "2026-10-09", "2026-10-12", *DAYS
        }
        import dagster as dg
        from dagster._core.event_api import PartitionKeyFilter

        check_ids = set()
        for u, snapshot in zip(plan["units"], snapshots, strict=True):
            for layer in ("raw", "silver"):
                checks = env.instance.event_log_storage.get_asset_check_execution_history(
                    dg.AssetCheckKey(dg.AssetKey(u[layer]["asset"]), u[layer]["check"]),
                    limit=1, partition_filter=PartitionKeyFilter(key=u["trade_date"]),
                )
                assert len(checks) == 1
                check = checks[0]
                evaluation = check.event.dagster_event.event_specific_data
                assert check.status.value == "SUCCEEDED" and evaluation.passed and evaluation.blocking
                assert evaluation.target_materialization_data.storage_id == snapshot[layer]["proof"]["materialization_id"]
                assert evaluation.target_materialization_data.run_id == snapshot[layer]["proof"]["run_id"]
                check_ids.add(check.id)
        assert len(check_ids) == 8
        assert len(env.source.calls) == 8 and len(backend.posts) == 12
        paths = [
            helper(env.lake, "moneyflow", day)
            for day in DAYS for helper in (raw_moneyflow_path, silver_moneyflow_path)
        ]
        before = {str(p): (file_hash(p), p.stat().st_mtime_ns) for p in paths}
        # A new backend reconnects to the same real instance and unchanged journal.
        old_posts = len(backend.posts)
        backend = FourDayJobsBackend(env)
        code, repeated = apply(
            backend, plan, root=journal.root, output=lambda _: None, clock=lambda: AT
        )
        assert code == 0 and repeated["completed"] == 4, repeated
        assert old_posts == 12 and backend.posts == [] and len(env.source.calls) == 8
        assert {str(p): (file_hash(p), p.stat().st_mtime_ns) for p in paths} == before
        assert len(env.instance.get_runs()) == 8
        budgets = json.loads((journal.directory / "budgets.json").read_text())
        action_reads = [v for k, v in budgets.items() if not k.startswith("poll:")]
        assert max(action_reads) <= 40
        record_property("four_day_evidence", json.dumps({
            "days": 4, "rows_per_day_per_layer": 3, "successful_native_jobs": 8,
            "fake_source_requests": 8, "mutation_posts_including_registration": 12,
            "new_posts_on_repeat": 0, "max_action_reads_with_22_guard_reads_charged": max(action_reads),
            "source_clock_http_adapter_replaced": True,
        }))
    finally:
        generator.close()
