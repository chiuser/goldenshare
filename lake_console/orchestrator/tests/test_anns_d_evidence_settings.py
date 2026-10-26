"""Saved producer contracts remain readable without today's execution Policy.

The legacy policy literal below is the policy recorded by the 2026-10-04
history producer in reports/anns_d_dg_p3_frozen_plan_20261004.json.  Only its
execution metadata is used; no formal Lake paths or announcement rows are read.
"""

import copy
import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from orchestrator.defs.anns_d_checkpoint import (
    AnnouncementCheckpoint,
    announcement_file_fingerprint,
)
from orchestrator.defs.anns_d_contract import (
    AnnouncementError,
    AnnouncementFileSettings,
    AnnouncementHistorySettings,
    announcement_file_settings_from_evidence,
    announcement_history_settings_from_plan,
)
from orchestrator.defs.bootstrap import anns_d_event_files as event_files
from orchestrator.defs.bootstrap.anns_d_history_execution import (
    announcement_history_store,
)
from orchestrator.defs.bootstrap.anns_d_history_plan import (
    seal_history_document,
    validate_announcement_history_plan,
)
from orchestrator.defs.run_contracts.anns_d import (
    ANNOUNCEMENT_EXECUTION_VERSION,
    AnnouncementPolicy,
)
from tests.anns_d_test_support import archive as _archive_fixture
from tests.anns_d_test_support import source_row
from tests.test_anns_d_history_plan import month_plan

archive = _archive_fixture

LEGACY_POLICY = {
    "page_size": 2000,
    "prod_fetch_rows": 10000,
    "interval_seconds": 5,
    "max_attempts": 3,
    "call_timeout": 30,
    "cancel_grace": 5,
    "max_day_requests": 100,
    "max_window_requests": 350,
    "max_window_seconds": 3600,
    "max_month_rows": 2000000,
    "month_deadline": 1800,
    "sql_timeout_ms": 60000,
    "duckdb_memory": "2GB",
    "duckdb_threads": 2,
    "spill_limit": "20GB",
    "min_free_reserve": 5368709120,
}
FILE_FIELDS = (
    "page_size",
    "duckdb_memory",
    "duckdb_threads",
    "spill_limit",
    "min_free_reserve",
)
HISTORY_FIELDS = (
    *FILE_FIELDS,
    "prod_fetch_rows",
    "max_month_rows",
    "month_deadline",
    "sql_timeout_ms",
)


def saved_identity():
    return {
        "window_id": "recorded-window",
        "day": "2023-06-09",
        "policy": copy.deepcopy(LEGACY_POLICY),
    }


def test_old_and_current_saved_policies_use_one_purpose_specific_reader():
    original = saved_identity()
    before = copy.deepcopy(original)
    current = copy.deepcopy(original)
    current["policy"].pop("max_window_seconds")
    expected_file = AnnouncementFileSettings(2000, "2GB", 2, "20GB", 5368709120)
    expected_history = AnnouncementHistorySettings(
        2000, "2GB", 2, "20GB", 5368709120, 10000, 2000000, 1800, 60000
    )
    for record in (original, current):
        assert announcement_file_settings_from_evidence(record) == expected_file
        assert announcement_history_settings_from_plan(record) == expected_history
    assert original == before and original["policy"]["max_window_seconds"] == 3600
    settings = announcement_file_settings_from_evidence(original)
    assert not hasattr(settings, "interval_seconds")
    assert not hasattr(settings, "max_window_seconds")
    assert not hasattr(settings, "max_window_requests")
    with pytest.raises(FrozenInstanceError):
        settings.page_size = 6000


@pytest.mark.parametrize("field", FILE_FIELDS)
def test_required_file_fields_cannot_be_missing(field):
    identity = saved_identity()
    del identity["policy"][field]
    with pytest.raises(AnnouncementError, match="evidence_policy"):
        announcement_file_settings_from_evidence(identity)


@pytest.mark.parametrize("field", HISTORY_FIELDS)
def test_required_history_fields_cannot_be_missing(field):
    identity = saved_identity()
    del identity["policy"][field]
    with pytest.raises(AnnouncementError, match="plan_policy"):
        announcement_history_settings_from_plan(identity)


@pytest.mark.parametrize("bad", [None, [], {"policy": []}, {"policy": None}])
def test_malformed_saved_policy_is_rejected(bad):
    with pytest.raises(AnnouncementError, match="evidence_policy"):
        announcement_file_settings_from_evidence(bad)
    with pytest.raises(AnnouncementError, match="plan_policy"):
        announcement_history_settings_from_plan(bad)


@pytest.mark.parametrize(
    "field,value",
    [
        ("page_size", 2000.0),
        ("page_size", 6000),
        ("page_size", True),
        ("duckdb_threads", True),
        ("duckdb_threads", 0),
        ("min_free_reserve", -1),
        ("min_free_reserve", 1.5),
        ("duckdb_memory", 2),
        ("duckdb_memory", " "),
        ("spill_limit", ""),
        ("spill_limit", None),
    ],
)
def test_wrong_file_types_or_values_are_not_coerced(field, value):
    identity = saved_identity()
    identity["policy"][field] = value
    with pytest.raises(AnnouncementError, match="evidence_policy"):
        announcement_file_settings_from_evidence(identity)


@pytest.mark.parametrize(
    "value", [True, 0, -1, "1800", float("nan"), float("inf"), 10**400]
)
def test_history_timeout_is_finite_positive_numeric(value):
    identity = saved_identity()
    identity["policy"]["month_deadline"] = value
    with pytest.raises(AnnouncementError, match="plan_policy"):
        announcement_history_settings_from_plan(identity)


@pytest.mark.parametrize(
    "field", ["prod_fetch_rows", "max_month_rows", "sql_timeout_ms"]
)
@pytest.mark.parametrize("value", [True, 0, -1, 1.5, "10000"])
def test_history_count_controls_require_positive_integers(field, value):
    identity = saved_identity()
    identity["policy"][field] = value
    with pytest.raises(AnnouncementError, match="plan_policy"):
        announcement_history_settings_from_plan(identity)


def test_saved_capacity_strings_are_preserved_including_disabled_spill():
    identity = saved_identity()
    identity["policy"].update(duckdb_memory="2 GB", spill_limit="0B")
    settings = announcement_file_settings_from_evidence(identity)
    assert settings.duckdb_memory == "2 GB" and settings.spill_limit == "0B"


def test_removed_budget_is_only_archival_metadata_not_a_new_execution_option():
    assert ANNOUNCEMENT_EXECUTION_VERSION == 2
    with pytest.raises(TypeError, match="max_window_seconds"):
        AnnouncementPolicy(max_window_seconds=3600)
    assert announcement_file_settings_from_evidence(saved_identity()).page_size == 2000


def test_saved_history_plan_and_store_keep_original_identity(archive):
    plan = month_plan(archive)
    plan["policy"] = copy.deepcopy(LEGACY_POLICY)
    plan = seal_history_document(plan)
    before = copy.deepcopy(plan)
    assert (
        validate_announcement_history_plan(plan, roots=(archive.root, archive.staging))
        is plan
    )
    store = announcement_history_store(plan, plan["months"][0], archive.control)
    assert isinstance(store.policy, AnnouncementHistorySettings)
    assert store.policy.prod_fetch_rows == 10000
    assert plan == before
    assert plan["policy"]["max_window_seconds"] == 3600


@pytest.mark.parametrize("mutation", ["fingerprint", "day", "target", "policy"])
def test_legacy_plan_does_not_lose_existing_validation(archive, mutation):
    plan = month_plan(archive)
    plan["policy"] = copy.deepcopy(LEGACY_POLICY)
    if mutation == "day":
        plan["months"][0]["days"][0]["day"] = "2023-05-31"
    elif mutation == "target":
        plan["months"][0]["days"][0]["target"] = str(archive.root / "wrong.parquet")
    elif mutation == "policy":
        plan["policy"]["prod_fetch_rows"] = True
    plan = seal_history_document(plan)
    if mutation == "fingerprint":
        plan["fingerprint"] = "changed"
    with pytest.raises(AnnouncementError):
        validate_announcement_history_plan(plan, roots=(archive.root, archive.staging))


def test_legacy_daily_delivery_uses_real_file_contract_and_never_rewrites(
    archive, monkeypatch
):
    day = "2023-06-09"
    page = archive.write_page(
        [source_row()], archive.directory / "page.parquet", archive.control
    )
    delivery = archive.build_day(day, [page])
    delivery.update(
        capture_complete=True,
        last_page_rows=1,
        source_pages=[
            {"path": str(page), "fingerprint": announcement_file_fingerprint(page)}
        ],
    )
    checkpoint = AnnouncementCheckpoint(
        archive.directory / "delivery.json", saved_identity()
    )
    archive.promote_day(day, delivery, checkpoint)
    manifest = archive.directory / "manifest.json"
    manifest.write_text(json.dumps([str(checkpoint.path)]))
    monkeypatch.setattr(event_files, "DEFAULT_LAKE_STAGING_ROOT", str(archive.staging))
    reader = event_files.AnnouncementEvidenceReader
    monkeypatch.setattr(
        event_files,
        "AnnouncementEvidenceReader",
        lambda directory, policy, control: reader(
            directory, policy, control, root=archive.root, staging=archive.staging
        ),
    )
    before = {str(p): p.read_bytes() for p in archive.staging.rglob("*") if p.is_file()}
    target_before = archive.target(day).read_bytes()
    entries = event_files.read_announcement_event_files(
        {"mode": "daily", "delivery_manifest": str(manifest)}, archive.control
    )
    assert len(entries) == 1 and entries[0]["rows"] == 1
    assert entries[0]["identity"] == saved_identity()
    assert entries[0]["identity"]["policy"]["max_window_seconds"] == 3600
    assert before == {
        str(p): p.read_bytes() for p in archive.staging.rglob("*") if p.is_file()
    }
    assert archive.target(day).read_bytes() == target_before
    event_files.verify_announcement_event_evidence(entries)
    Path(entries[0]["path"]).write_bytes(b"wrong-file")
    with pytest.raises(AnnouncementError, match="file_changed"):
        event_files.read_announcement_event_files(
            {"mode": "daily", "delivery_manifest": str(manifest)}, archive.control
        )
