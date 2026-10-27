"""One caller-owned native Dagster/SIGINT probe; never signals another process."""

import hashlib
import json
import os
import signal
import sys
from pathlib import Path
from unittest.mock import patch

import dagster as dg
from dagster._core.errors import DagsterExecutionInterruptedError

from orchestrator.defs.anns_d_checkpoint import AnnouncementControl
from orchestrator.defs.anns_d_contract import ANNOUNCEMENT_ASSET, ANNOUNCEMENT_FIELDS
from orchestrator.defs.anns_d_window import announcement_manual_window_id
from orchestrator.defs.assets import anns_d as asset_module
from orchestrator.defs.checks import anns_d_checks as checks_module
from orchestrator.defs.resources import LakeRootResource, TushareResource

DAY = "2023-06-09"


def main():
    location = Path(sys.argv[1]).resolve()
    root, staging, instance_path = (
        location / "lake",
        location / "staging",
        location / "instance",
    )
    for directory in (root, staging, instance_path):
        directory.mkdir(parents=True)
    row = {
        "ann_date": "20230609",
        "ts_code": "155162.SH",
        "name": "19津投04",
        "title": "literal native SIGINT probe",
        "url": None,
        "rec_time": None,
    }
    calls, sent, stage = [], [], ["source"]
    progress = AnnouncementControl.progress
    with dg.DagsterInstance.ephemeral(tempdir=str(instance_path)) as instance:

        def source(params, control):
            calls.append(params.copy())
            if stage[0] == "source":
                run = instance.get_run_by_id(control.view["active_run_id"])
                instance.report_run_canceling(run)
                raise DagsterExecutionInterruptedError()
            return [row], ANNOUNCEMENT_FIELDS

        def observe(control, **event):
            progress(control, **event)
            if stage[0] == "promoted" and event.get("phase") == "promoted" and not sent:
                sent.append(os.getpid())
                run = instance.get_run_by_id(control.view["active_run_id"])
                instance.report_run_canceling(run)
                # Only this dedicated test subprocess receives this signal.
                os.kill(os.getpid(), signal.SIGINT)

        with (
            patch.object(asset_module, "DEFAULT_LAKE_ROOT", str(root)),
            patch.object(asset_module, "DEFAULT_LAKE_STAGING_ROOT", str(staging)),
            patch.object(checks_module, "DEFAULT_LAKE_ROOT", str(root)),
            patch.object(checks_module, "DEFAULT_LAKE_STAGING_ROOT", str(staging)),
            patch.object(LakeRootResource, "ensure_available_for_run", lambda *_: None),
            patch.object(asset_module, "AnnouncementProcessCall", lambda *_: source),
            patch.object(AnnouncementControl, "progress", observe),
        ):
            definitions = dg.Definitions(
                assets=[asset_module.raw_tushare_anns_d],
                asset_checks=[
                    checks_module.raw_tushare_anns_d_file_contract_check,
                    checks_module.raw_tushare_anns_d_delivery_reconciliation_check,
                ],
                jobs=[
                    dg.define_asset_job(
                        "native_sigint", executor_def=dg.in_process_executor
                    )
                ],
                resources={
                    "lake_root": LakeRootResource(root_path=str(root)),
                    "tushare": TushareResource(token="unused-isolated-placeholder"),
                },
            )
            job = definitions.resolve_job_def("native_sigint")
            config = {"ops": {ANNOUNCEMENT_ASSET: {"config": {"interval_seconds": 0}}}}
            first = job.execute_in_process(
                partition_key=DAY,
                instance=instance,
                raise_on_error=False,
                run_config=config,
            )
            first_run = instance.get_run_by_id(first.run_id)
            first_window = announcement_manual_window_id(first.run_id, DAY, DAY)
            first_state = json.loads(
                (
                    staging / "anns_d/windows" / first_window / "execution.json"
                ).read_text()
            )
            first_checkpoint = json.loads(
                Path(first_state["days"][DAY]["checkpoint"]).read_text()
            )
            first_events = instance.all_logs(first.run_id)
            source_report = {
                "run_status": first_run.status.value,
                "phase": first_state["phase"],
                "day_phase": first_checkpoint["phase"],
                "files_completed": first_state["files_completed"],
                "requests": first_state["requests"],
                "source_calls": list(calls),
                "materializations": sum(
                    bool(event.asset_materialization) for event in first_events
                ),
                "checks": sum(
                    bool(event.asset_check_evaluation) for event in first_events
                ),
                "error_sources": [
                    event.dagster_event.event_specific_data.error_source.value
                    for event in first_events
                    if event.dagster_event and event.dagster_event.is_step_failure
                ],
            }
            calls.clear()
            stage[0] = "promoted"
            result = job.execute_in_process(
                partition_key=DAY,
                instance=instance,
                raise_on_error=False,
                run_config={
                    "ops": {ANNOUNCEMENT_ASSET: {"config": {"interval_seconds": 0}}}
                },
            )
        run = instance.get_run_by_id(result.run_id)
        window_id = announcement_manual_window_id(run.run_id, DAY, DAY)
        state = json.loads(
            (staging / "anns_d/windows" / window_id / "execution.json").read_text()
        )
        events = instance.all_logs(run.run_id)
        failures = [
            event.dagster_event.event_specific_data
            for event in events
            if event.dagster_event and event.dagster_event.is_step_failure
        ]
        target = next(root.rglob("*.parquet"))
        checkpoint = json.loads(Path(state["days"][DAY]["checkpoint"]).read_text())
        report = {
            "run_id": run.run_id,
            "source_interrupt": source_report,
            "window_id": window_id,
            "run_status": run.status.value,
            "success": result.success,
            "signal_self_pid": sent,
            "pid": os.getpid(),
            "error_sources": [failure.error_source.value for failure in failures],
            "native_interrupt": any(
                "DagsterExecutionInterruptedError" in failure.error.to_string()
                for failure in failures
            ),
            "materializations": sum(
                bool(event.asset_materialization) for event in events
            ),
            "checks": sum(bool(event.asset_check_evaluation) for event in events),
            "source_calls": calls,
            "state": state,
            "day_checkpoint": checkpoint,
            "target": str(target),
            "fingerprint": {
                "size": target.stat().st_size,
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            },
        }
    (location / "report.json").write_text(json.dumps(report))


if __name__ == "__main__":
    main()
