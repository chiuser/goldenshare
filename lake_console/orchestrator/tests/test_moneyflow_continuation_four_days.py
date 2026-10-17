"""Four tiny actual Raw/Silver jobs, SQLite parent/child and restart/replay.

Formal GraphQL/remote origin/legacy parent evidence are replaced explicitly.
The original failure validator and 5574-row candidate have independent tests.
The 45 accepted dates are references, not regenerated lake files in this test.
"""

import json
from types import SimpleNamespace as NS

import dagster as dg
import pytest
from dagster._core.definitions.job_base import InMemoryJob
from dagster._core.execution.api import execute_run

from orchestrator.moneyflow_continuation import recovery
from orchestrator.moneyflow_continuation.contract import digest, file_hash
from orchestrator.moneyflow_continuation.execution import apply
from orchestrator.moneyflow_continuation.plan import make_plan
from orchestrator.moneyflow_continuation.recovery import REEXECUTE
from orchestrator.moneyflow_continuation.state import NativeBackend, next_action
from orchestrator.moneyflow_continuation.submission import Journal, submit_once
from tests import test_moneyflow_definitions as support
from tests.moneyflow_baseline_support import seed_moneyflow_baseline
from tests.test_moneyflow_collection_recovery import DAYS, PARENT, full_parent, setup
from tests.test_moneyflow_continuation_integration import LocalJobsBackend
from tests.test_moneyflow_continuation_plan import AT

pytestmark = pytest.mark.usefixtures("isolated_moneyflow_transport")


class ReexecutionJobsBackend(LocalJobsBackend):
    def validate_run(self, run, unit, layer, body=None):
        if run.asset_selection is not None:
            return super().validate_run(run, unit, layer, body)
        values = run._asdict()
        values["remote_job_origin"] = NS(
            job_name=unit[layer]["job"],
            repository_origin=NS(
                repository_name="__repository__",
                code_location_origin=NS(location_name="orchestrator"),
            ),
        )
        return NativeBackend.validate_run(self, NS(**values), unit, layer, body)

    def guard(self, plan, at):
        super().guard(plan, at)
        # Current state.guard: 2 runtime HTTP + 2 calendar + 4 pool + 14 active-job
        # reads. Charge these too, rather than making the isolated budget free.
        for _ in range(22):
            self.meter.tick()

    def mutate(self, body):
        if body["query"] != REEXECUTE:
            return super().mutate(body)
        self.posts.append(body)
        parent = self.env.instance.get_run_by_id(body["variables"]["parentRunId"])
        job = self.env.defs.resolve_job_def(parent.job_name).with_executor_def(
            dg.in_process_executor
        )
        child = self.env.instance.create_run_for_job(
            job,
            tags=parent.tags,
            root_run_id=parent.run_id,
            parent_run_id=parent.run_id,
        )
        assert execute_run(InMemoryJob(job), child, self.env.instance).success
        if self.lose_response:
            raise OSError("isolated response lost after real child committed")
        return {
            "data": {
                "launchRun": {
                    "__typename": "LaunchRunSuccess",
                    "run": {"runId": child.run_id},
                }
            }
        }


def test_four_day_native_files_lost_response_restart_and_zero_repeat(
    tmp_path, monkeypatch, record_property
):
    case, runtime = tmp_path / "case", tmp_path / "runtime"
    case.mkdir()
    runtime.mkdir()
    child, unit, journal, *_ = setup(case, monkeypatch)
    parent = full_parent()
    full = make_plan(
        [
            {"dataset": u["dataset"], "trade_date": u["trade_date"]}
            for u in parent["units"]
        ],
        set(DAYS),
        AT,
        parent["verification"],
        {},
        [],
        parent,
        digest(parent),
        collection_recovery=child["collection_recovery"],
    )
    entries = [{"dataset": "moneyflow", "trade_date": day} for day in DAYS[3:]]
    plan = make_plan(
        entries, set(DAYS), AT, full["verification"], {}, [], full, digest(full)
    )
    generator = support.env.__wrapped__(runtime, monkeypatch)
    env = next(generator)
    try:
        backend = ReexecutionJobsBackend(env)
        backend.lose_response = True
        for day in DAYS[:3]:
            seed_moneyflow_baseline(
                instance=env.instance,
                lake=env.lake,
                staging=env.staging,
                dataset="moneyflow",
                rows=support.sample(),
                day=day,
            )
        env.instance.add_dynamic_partitions(unit["partition_set"], ["2026-10-13"])
        original = journal.read(unit, "raw")["request"]["body"]["variables"][
            "executionParams"
        ]
        tags = {t["key"]: t["value"] for t in original["executionMetadata"]["tags"]}
        old = env.instance.create_run_for_job(
            env.defs.resolve_job_def(unit["raw"]["job"]), run_id=PARENT, tags=tags
        )
        env.instance.report_run_failed(old)
        # Legacy parent audit is tested separately; this test exercises new jobs/files.
        monkeypatch.setattr(recovery, "validate_collection_failure", lambda *_: [])
        old_dir = env.staging / "moneyflow" / PARENT
        old_dir.mkdir(parents=True)
        marker = old_dir / "retained-first-round"
        marker.write_bytes(b"retained original candidate reference")
        old_hash = file_hash(marker)
        source_rows = [support.pages(support.sample(day=day)) * 2 for day in DAYS[3:]]
        env.source.responses = iter([page for pages in source_rows for page in pages])
        backend.snapshots([unit], journal)
        with pytest.raises(OSError):
            submit_once(backend, journal, unit, recovery.RAW_ACTION, AT)
        assert len(backend.posts) == 1
        backend.lose_response = False
        for _ in range(2):
            code, result = apply(
                backend,
                plan,
                root=journal.root,
                output=lambda _: None,
                clock=lambda: AT,
            )
            assert code == 0, result
            assert result["completed"] == 4
        snapshots = backend.snapshots(plan["units"], Journal(plan, journal.root))
        assert all(next_action(s) == "complete" for s in snapshots)
        assert all(
            s["raw"]["proof"]["rows"] == s["silver"]["proof"]["rows"] == 3
            for s in snapshots
        )
        assert len(env.source.calls) == 8 and len(backend.posts) == 11
        runs = env.instance.get_runs()
        assert len(runs) == 9 and sum(r.status.value == "SUCCESS" for r in runs) == 8
        assert env.instance.get_run_by_id(PARENT).status.value == "FAILURE"
        children = [r for r in runs if r.parent_run_id == PARENT]
        assert len(children) == 1 and children[0].root_run_id == PARENT
        assert file_hash(marker) == old_hash
        from pathlib import Path

        from orchestrator.defs.paths import raw_moneyflow_path, silver_moneyflow_path
        from orchestrator.moneyflow_continuation import acceptance

        original_path = Path
        mapping = {
            u[layer]["target"]: (
                raw_moneyflow_path if layer == "raw" else silver_moneyflow_path
            )(env.lake, "moneyflow", u["trade_date"])
            for u in plan["units"]
            for layer in ("raw", "silver")
        }
        monkeypatch.setattr(
            acceptance, "Path", lambda p: mapping.get(str(p), original_path(p))
        )
        events, native = {}, {}
        for u, s in zip(plan["units"], snapshots, strict=True):
            for layer in ("raw", "silver"):
                proof = s[layer]["proof"]
                key = ("moneyflow", u["trade_date"], layer)
                events[key] = {
                    "mat_id": proof["materialization_id"],
                    "run_id": proof["run_id"],
                }
                native[key] = env.instance.get_run_by_id(proof["run_id"])
        records = acceptance.accepted_records(
            backend,
            plan,
            plan["units"],
            snapshots,
            events,
            native,
            Journal(plan, journal.root),
        )
        assert (
            len(records) == 4
            and records[0]["layers"]["raw"]["submission_evidence"]
            == "native_readback_after_uncertain_response"
        )
        budgets = json.loads((journal.directory / "budgets.json").read_text())
        action_reads = [v for k, v in budgets.items() if not k.startswith("poll:")]
        assert max(action_reads) <= 40
        record_property(
            "four_day_evidence",
            json.dumps(
                {
                    "days": 4,
                    "rows_per_day_per_layer": 3,
                    "successful_native_jobs": 8,
                    "preserved_native_failures": 1,
                    "fake_source_requests": 8,
                    "mutation_posts_including_registration": 11,
                    "new_posts_on_repeat": 0,
                    "max_action_reads_with_22_guard_reads_charged": max(action_reads),
                    "total_meter_reads": backend.meter.count,
                    "legacy_parent_evidence_and_remote_origin_replaced": True,
                }
            ),
        )
    finally:
        generator.close()
