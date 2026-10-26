"""LLD 5.4.3 empty-scope/count rules; no files, source or Dagster I/O."""

from dataclasses import replace
from datetime import date

import pytest

from orchestrator.defs.run_contracts.stk_factor_pro import PublishedTarget, RecordRef

SHA = "a" * 64
EMPTY = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
P = date(2026, 10, 15)


def actual():
    return PublishedTarget(
        P,
        "raw",
        False,
        SHA,
        2,
        RecordRef("run-a", f"publication/history/{P}/raw/complete.json", SHA),
        0,
        1,
        SHA,
        1,
    )


def test_scope_counts_are_a_subset_of_the_actual_file():
    assert actual().scope_rows == 1 and actual().file_rows == 2
    with pytest.raises(ValueError, match="范围行数"):
        replace(actual(), scope_rows=3)


def test_empty_scope_has_the_standard_empty_content_digest():
    assert replace(actual(), scope_rows=0, scope_content_sha256=EMPTY).scope_rows == 0
    with pytest.raises(ValueError, match="空历史范围"):
        replace(actual(), scope_rows=0)


def test_skip_cannot_claim_existing_unrefreshed_keys_or_a_file():
    skipped = PublishedTarget(P, "raw", True, None, 0, None, 0, 0, EMPTY, 1)
    assert skipped.skip_no_file and skipped.checkpoint_ref is None
    with pytest.raises(ValueError, match="无文件目标"):
        replace(skipped, unrefreshed_count=1)


def test_day_targets_keep_all_scope_fields_absent():
    day = replace(
        actual(), scope_rows=None, scope_content_sha256=None, scope_content_version=None
    )
    assert (
        day.scope_rows is day.scope_content_sha256 is day.scope_content_version is None
    )
