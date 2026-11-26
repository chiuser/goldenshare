"""Internal entry for preparing and queuing the agreed index minute repair."""

import argparse
from pathlib import Path

from sqlalchemy.orm import Session

from src.foundation.ingestion.index_minute_volume_repair import (
    PILOT,
    REPAIR_DAYS,
    freeze_volume_repair,
    verify_frozen_volume_repair,
)
from src.ops.models.ops.task_run import TaskRun
from src.ops.services.task_run_service import TaskRunCommandService, TaskRunCreateContext


def enqueue_volume_repair(session: Session, *, manifest: Path, sha256: str) -> TaskRun:
    path = manifest.resolve(strict=True)
    with path.open("rb") as stream:
        header = verify_frozen_volume_repair(stream, sha256)
    days = (PILOT[2],) if header["scope"] == "pilot" else REPAIR_DAYS
    return TaskRunCommandService().create_task_run(
        session,
        context=TaskRunCreateContext(
            task_type="dataset_action", resource_key="index_mins", action="maintain",
            trigger_source="system", requested_by_user_id=None,
            time_input={"mode": "range", "start_date": min(days).isoformat(), "end_date": max(days).isoformat()},
            filters={},
            request_payload={"index_minute_volume_repair": {"manifest": str(path), "sha256": sha256}},
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--preview", required=True, type=Path)
    prepare.add_argument("--output", required=True, type=Path)
    prepare.add_argument("--scope", required=True, choices=("pilot", "first-batch"))
    enqueue = commands.add_parser("enqueue")
    enqueue.add_argument("--manifest", required=True, type=Path)
    enqueue.add_argument("--sha256", required=True)
    args = parser.parse_args()

    from src.db import get_session_factory

    session_factory = get_session_factory()
    if args.command == "prepare":
        print(freeze_volume_repair(session_factory, preview=args.preview, target=args.output, scope=args.scope))
    else:
        with session_factory() as session:
            print(enqueue_volume_repair(session, manifest=args.manifest, sha256=args.sha256).id)


if __name__ == "__main__":
    main()
