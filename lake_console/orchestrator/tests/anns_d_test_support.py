from dataclasses import replace

import pytest

from orchestrator.defs.anns_d_checkpoint import (
    AnnouncementCheckpoint,
    AnnouncementControl,
)
from orchestrator.defs.anns_d_contract import ANNOUNCEMENT_FIELDS
from orchestrator.defs.anns_d_io import AnnouncementStore
from orchestrator.defs.run_contracts.anns_d import AnnouncementPolicy


def source_row(**values):
    return (
        dict(
            zip(
                ANNOUNCEMENT_FIELDS,
                ("20230609", "155162.SH", "19津投04", "同标题", None, None),
                strict=True,
            )
        )
        | values
    )


@pytest.fixture
def archive(tmp_path):
    root, staging = tmp_path / "lake", tmp_path / "staging"
    root.mkdir()
    staging.mkdir()
    policy = replace(AnnouncementPolicy(), interval_seconds=0)
    return AnnouncementStore(root, staging, "test-run", policy, AnnouncementControl())


def checkpoint(store, day="2023-06-09"):
    return AnnouncementCheckpoint(store.directory / f"{day}.json", {"day": day})
