"""Delivery metadata rules use original daily/monthly producers in temporary roots."""

import copy
import json
from types import SimpleNamespace

import pytest

from orchestrator.defs.anns_d_contract import AnnouncementError
from orchestrator.defs.anns_d_execution import (
    announcement_capture_pages,
    verify_announcement_delivery,
)
from orchestrator.defs.bootstrap.anns_d_history_execution import (
    announcement_history_day_checkpoint,
    announcement_history_store,
    announcement_month_checkpoint,
)
from orchestrator.defs.checks import anns_d_checks as checks
from orchestrator.defs.resources import LakeRootResource
from tests.anns_d_test_support import archive as _archive_fixture
from tests.anns_d_test_support import source_row
from tests.test_anns_d_history_execution import stage
from tests.test_anns_d_history_plan import month_plan
from tests.test_anns_d_reused_delivery import delivery_case as _delivery_case

delivery_case = _delivery_case
archive = _archive_fixture


def _evaluate(case, monkeypatch):
    monkeypatch.setattr(checks, "DEFAULT_LAKE_ROOT", str(case.root))
    context = SimpleNamespace(
        instance=SimpleNamespace(
            fetch_materializations=lambda *args, **kwargs: SimpleNamespace(
                records=[case.record]
            )
        ),
        run=SimpleNamespace(run_id="independent-delivery-check"),
    )
    return checks.evaluate_announcement_check(
        context,
        LakeRootResource(root_path=str(case.root)),
        day="2023-06-09",
        reconciliation=True,
        staging_root=case.staging,
        target_record=case.record,
        materializing=False,
    )


@pytest.mark.parametrize("field", ["source_pages", "last_page_rows"])
def test_normal_delivery_rejects_missing_source_or_end_page(
    delivery_case, monkeypatch, field
):
    # Existing source/capture producer always emits these fields, including an
    # empty terminal page. Removing one is deliberately damaged evidence.
    case = delivery_case
    assert _evaluate(case, monkeypatch).passed
    document = json.loads(case.checkpoint_path.read_text())
    document["delivery"].pop(field)
    case.checkpoint_path.write_text(json.dumps(document))
    before = case.checkpoint_path.read_bytes()
    assert not _evaluate(case, monkeypatch).passed
    assert case.checkpoint_path.read_bytes() == before


@pytest.mark.parametrize("delivery_case", [0, 1, 2000, 2001], indirect=True)
def test_complete_daily_producer_remains_green_without_rewriting_evidence(
    delivery_case, monkeypatch
):
    case = delivery_case
    before = case.checkpoint_path.read_bytes()
    assert _evaluate(case, monkeypatch).passed
    assert case.checkpoint_path.read_bytes() == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("capture_complete", 1),
        ("capture_complete", False),
        ("source_pages", []),
        ("source_pages", None),
        ("page_count", True),
        ("page_count", 0),
        ("page_count", 2),
        ("last_offset", True),
        ("last_offset", -1),
        ("last_offset", 2000),
        ("last_page_rows", True),
        ("last_page_rows", -1),
        ("last_page_rows", 2000),
        ("source_rows", True),
        ("source_rows", -1),
        ("source_rows", 2),
        ("readback_rows", True),
        ("fingerprint", {}),
    ],
)
def test_normal_daily_delivery_rejects_invalid_paging_metadata(
    delivery_case, monkeypatch, field, value
):
    case = delivery_case
    document = json.loads(case.checkpoint_path.read_text())
    document["delivery"][field] = value
    case.checkpoint_path.write_text(json.dumps(document))
    assert not _evaluate(case, monkeypatch).passed


@pytest.mark.parametrize(
    "field,value",
    [
        ("offset", True),
        ("offset", 1),
        ("rows", True),
        ("rows", 0),
        ("path", ""),
        ("fingerprint", {}),
    ],
)
def test_normal_daily_delivery_rejects_invalid_page_reference(
    delivery_case, monkeypatch, field, value
):
    case = delivery_case
    document = json.loads(case.checkpoint_path.read_text())
    document["delivery"]["source_pages"][0][field] = value
    case.checkpoint_path.write_text(json.dumps(document))
    assert not _evaluate(case, monkeypatch).passed


@pytest.mark.parametrize("kind", ["unknown", "mixed", "bad_policy", "bad_history_id"])
def test_unknown_or_mixed_producer_cannot_downgrade_to_history(delivery_case, kind):
    case = delivery_case
    document = json.loads(case.checkpoint_path.read_text())
    identity = copy.deepcopy(document["identity"])
    if kind == "unknown":
        identity.pop("window_id")
    elif kind == "mixed":
        identity["plan_fingerprint"] = "0" * 64
    elif kind == "bad_policy":
        identity["policy"] = None
    else:
        identity.pop("window_id")
        identity["plan_fingerprint"] = "not-a-plan-hash"
    checkpoint = SimpleNamespace(identity=identity, document=document)
    with pytest.raises(AnnouncementError, match="checkpoint_identity"):
        announcement_capture_pages(checkpoint, page_size=2000)


def test_old_daily_policy_keeps_complete_capture_and_original_bytes(
    delivery_case, monkeypatch
):
    # Old P2 capture/execution emitted the same fields before execution v2.
    case = delivery_case
    document = json.loads(case.checkpoint_path.read_text())
    identity = copy.deepcopy(document["identity"])
    identity["policy"]["max_window_seconds"] = 3600
    document["identity"] = identity
    case.checkpoint_path.write_text(json.dumps(document))
    materialization = case.record.asset_materialization
    metadata = dict(materialization.metadata)
    import dagster as dg

    metadata["goldenshare/announcement_identity"] = dg.MetadataValue.json(identity)
    case.record.asset_materialization = dg.AssetMaterialization(
        asset_key=materialization.asset_key, partition="2023-06-09", metadata=metadata
    )
    before = case.checkpoint_path.read_bytes()
    assert _evaluate(case, monkeypatch).passed
    assert case.checkpoint_path.read_bytes() == before


@pytest.mark.parametrize("empty_month", [False, True])
def test_real_history_producer_keeps_shared_month_pages_and_empty_month(
    archive, empty_month
):
    # Actual history capture/build/child producer. Two dates prove that month
    # page row sums must not be compared to a single day's source_rows.
    rows = [] if empty_month else [source_row(), source_row(ann_date="20230610")]
    inventory = (
        []
        if empty_month
        else [
            {"day": "2023-06-09", "rows": 1, "upper_id": 1},
            {"day": "2023-06-10", "rows": 1, "upper_id": 2},
        ]
    )
    plan = month_plan(archive, inventory=inventory)

    class MonthSource:
        def batches(self, month, upper_id, control, on_plan):
            on_plan({"expected_rows": 0 if empty_month else 2, "month_start": month})
            if rows:
                yield rows

    stage(archive, "capture", plan, source=MonthSource())
    stage(archive, "build", plan)
    month = plan["months"][0]
    store = announcement_history_store(plan, month, archive.control)
    parent = announcement_month_checkpoint(plan, month, store)
    for day, expected in [("2023-06-09", 0 if empty_month else 1), ("2023-06-11", 0)]:
        delivery = parent.document["deliveries"][day]
        child = announcement_history_day_checkpoint(plan, day, store)
        store.promote_day(day, delivery, child)
        before = child.path.read_bytes()
        actual = verify_announcement_delivery(store, day, child)
        assert actual["source_rows"] == expected
        assert sum(page["rows"] for page in actual["source_pages"]) == (
            0 if empty_month else 2
        )
        assert not any("offset" in page for page in actual["source_pages"])
        assert child.path.read_bytes() == before
        if empty_month:
            assert actual["source_pages"] == []


@pytest.mark.parametrize("value", [True, -1, 1])
def test_history_expected_count_remains_strict(delivery_case, value):
    case = delivery_case
    document = json.loads(case.checkpoint_path.read_text())
    identity = {
        "plan_fingerprint": "0" * 64,
        "day": "2023-06-09",
        "policy": document["identity"]["policy"],
    }
    # Deliberately damaged history-shaped evidence, not an old daily fallback.
    document["delivery"]["source_plan"] = {"expected_rows": value}
    document["delivery"]["source_pages"] = []
    document["delivery"]["source_rows"] = 0
    checkpoint = SimpleNamespace(identity=identity, document=document)
    with pytest.raises(AnnouncementError):
        announcement_capture_pages(checkpoint, page_size=2000)
