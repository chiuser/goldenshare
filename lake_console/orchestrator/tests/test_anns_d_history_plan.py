"""Frozen planning is bounded, read-only and rejects drifting identities."""

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestrator.defs.anns_d_contract import AnnouncementError
from orchestrator.defs.bootstrap.anns_d_history_plan import (
    announcement_bootstrap_volume_gate,
    load_announcement_history_document,
    make_announcement_history_plan,
    save_announcement_history_report,
    seal_history_document,
    validate_announcement_history_plan,
)
from orchestrator.defs.prod_db.anns_d import AnnouncementHistorySource
from tests.anns_d_test_support import archive as _archive_fixture
from tests.test_anns_d_history import FakeResource

archive = _archive_fixture


def month_plan(store, *, inventory=None):
    inventory = (
        inventory
        if inventory is not None
        else [{"day": "2023-06-09", "rows": 3, "upper_id": 3}]
    )
    return make_announcement_history_plan(
        "2023-06-01",
        "2023-06-30",
        "history",
        inventory,
        store.policy,
        root=store.root,
        staging=store.staging,
    )


def test_plan_freezes_30_dates_no_staging_or_lake_creation(archive):
    before = list(archive.root.rglob("*")), list(archive.staging.rglob("*"))
    plan = month_plan(archive)
    assert len(plan["months"]) == 1 and len(plan["months"][0]["days"]) == 30
    assert plan["months"][0]["upper_id"] == 3 and plan["cost"]["source_rows"] == 3
    assert (list(archive.root.rglob("*")), list(archive.staging.rglob("*"))) == before
    assert (
        validate_announcement_history_plan(plan, roots=(archive.root, archive.staging))
        == plan
    )
    with pytest.raises(AnnouncementError, match="formal_roots"):
        validate_announcement_history_plan(plan)


@pytest.mark.parametrize(
    "start,end",
    [
        ("2023-06-02", "2023-06-30"),
        ("2023-06-01", "2023-06-29"),
        ("2019-12-01", "2019-12-31"),
        ("2026-10-01", "2026-10-31"),
    ],
)
def test_plan_scope_cannot_expand_or_be_partial(archive, start, end):
    with pytest.raises(AnnouncementError):
        make_announcement_history_plan(
            start,
            end,
            "history",
            [],
            archive.policy,
            root=archive.root,
            staging=archive.staging,
        )


def test_plan_inventory_and_space_rejections(archive, monkeypatch):
    with pytest.raises(AnnouncementError, match="inventory_dates"):
        month_plan(archive, inventory=[{"day": "2023-07-01", "rows": 1, "upper_id": 1}])
    with pytest.raises(AnnouncementError, match="month_budget"):
        month_plan(
            archive, inventory=[{"day": "2023-06-09", "rows": 2000001, "upper_id": 3}]
        )
    import orchestrator.defs.bootstrap.anns_d_history_plan as module

    monkeypatch.setattr(module.shutil, "disk_usage", lambda _: SimpleNamespace(free=1))
    with pytest.raises(AnnouncementError, match="space"):
        announcement_bootstrap_volume_gate(archive.root, archive.staging)


def test_reports_preserve_identity_and_never_overwrite(archive):
    plan = month_plan(archive)
    with tempfile.TemporaryDirectory(
        dir="/private/tmp", prefix="anns-plan-test-"
    ) as directory:
        path = Path(directory) / "plan.json"
        save_announcement_history_report(path, plan)
        assert (
            load_announcement_history_document(
                path, kind="anns_d_history_plan", fingerprint=plan["fingerprint"]
            )
            == plan
        )
        with pytest.raises(AnnouncementError, match="exists"):
            save_announcement_history_report(path, plan)
        payload = json.loads(path.read_text())
        payload["months"][0]["source_rows"] = 4
        path.write_text(json.dumps(payload))
        with pytest.raises(AnnouncementError, match="fingerprint"):
            load_announcement_history_document(path, kind="anns_d_history_plan")
    with pytest.raises(AnnouncementError, match="private_tmp"):
        save_announcement_history_report(archive.directory / "plan.json", plan)


def test_frozen_plan_rejects_date_and_target_changes_even_when_resealed(archive):
    plan = month_plan(archive)
    plan["months"][0]["days"][0]["target"] = "/private/tmp/elsewhere.parquet"
    with pytest.raises(AnnouncementError, match="plan_target"):
        validate_announcement_history_plan(
            seal_history_document(plan), roots=(archive.root, archive.staging)
        )


def test_inventory_readonly_ordering_and_bounded_fetch(archive):
    from datetime import date

    resource = FakeResource([])
    resource.cursor.fetchmany.side_effect = [[(date(2023, 6, 9), 3, 3)], []]
    result = AnnouncementHistorySource(resource, archive.policy).inventory(
        "2023-06-01", "2023-06-30", archive.control
    )
    assert result == [{"day": "2023-06-09", "rows": 3, "upper_id": 3}]
    statements = [c.args[0] for c in resource.cursor.execute.call_args_list]
    assert statements[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    assert (
        "GROUP BY ann_date ORDER BY ann_date" in statements[-1]
        and "raw_payload" not in statements[-1]
    )
    assert resource.cursor.fetchmany.call_args.args == (256,) and resource.closed


@pytest.mark.parametrize("upper", [-1, "3", True, 0])
def test_resealed_plan_rejects_invalid_upper_id(archive, upper):
    plan = month_plan(archive)
    plan["months"][0]["upper_id"] = upper
    with pytest.raises(AnnouncementError, match="upper_id"):
        validate_announcement_history_plan(
            seal_history_document(plan), roots=(archive.root, archive.staging)
        )


def test_sample_plan_does_not_claim_full_history_runtime(archive):
    assert month_plan(archive)["cost"]["estimated_seconds_range"] is None
