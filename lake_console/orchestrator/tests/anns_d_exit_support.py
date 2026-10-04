"""Abrupt-parent-exit recovery fixture; only writes caller-owned tmp paths."""

import os
import sys
from dataclasses import replace
from pathlib import Path

from orchestrator.defs.anns_d_checkpoint import (
    AnnouncementCheckpoint,
    AnnouncementControl,
    AnnouncementWindowBudget,
)
from orchestrator.defs.anns_d_contract import ANNOUNCEMENT_FIELDS
from orchestrator.defs.anns_d_execution import update_announcement_day
from orchestrator.defs.anns_d_io import AnnouncementStore
from orchestrator.defs.run_contracts.anns_d import AnnouncementPolicy
from tests.anns_d_test_support import source_row


def main():
    location = Path(sys.argv[1])
    mode = sys.argv[2]
    root, staging = location / "lake", location / "staging"
    root.mkdir(exist_ok=True)
    staging.mkdir(exist_ok=True)
    policy = replace(AnnouncementPolicy(), interval_seconds=0)

    def emit(event):
        if mode == "capture" and event.get("rows_captured") == 2000:
            os._exit(17)

    control = AnnouncementControl(emit=emit)
    store = AnnouncementStore(root, staging, "exit-run", policy, control)
    cp = AnnouncementCheckpoint(store.directory / "day.json", {"day": "2023-06-09"})
    if mode == "rename":
        save = cp.save

        def save_or_exit(**values):
            if values.get("phase") == "promoted":
                os._exit(17)
            save(**values)

        cp.save = save_or_exit
    budget = AnnouncementWindowBudget(store.directory / "window.json", "window", policy)
    rows = (
        [source_row(title=str(i)) for i in range(2000)]
        if mode == "capture"
        else [source_row()]
    )
    update_announcement_day(
        "2023-06-09",
        lambda *_: (rows, ANNOUNCEMENT_FIELDS),
        store,
        cp,
        control,
        budget,
        policy,
    )


if __name__ == "__main__":
    main()
