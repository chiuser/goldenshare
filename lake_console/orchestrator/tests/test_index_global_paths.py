"""Path contracts from recovery LLD section 5.1; never probe formal storage."""

from pathlib import Path
from tempfile import gettempdir

import pytest

from orchestrator.defs.paths import (
    DEFAULT_LAKE_ROOT,
    raw_index_global_path,
    raw_index_global_staging_path,
    silver_index_global_path,
    silver_index_global_staging_path,
)

DAY = "2026-10-04"
RUN = "c8a8b9f5-7cd7-49c2-8492-04fcc41d12df"


def test_formal_candidates_map_to_dedicated_staging_without_filesystem_probe(monkeypatch):
    def forbid_probe(*args, **kwargs):
        raise AssertionError("A formal path helper must not probe the volume")

    monkeypatch.setattr(Path, "stat", forbid_probe)
    monkeypatch.setattr(Path, "lstat", forbid_probe)
    root = Path(DEFAULT_LAKE_ROOT)
    assert raw_index_global_staging_path(root, RUN, DAY, "late_empty") == Path(
        "/Volumes/datasource/data_lake_staging/index_global/raw_index_global/"
        "trade_date=2026-10-04/operation=c8a8b9f5-7cd7-49c2-8492-04fcc41d12df/"
        "phase=late_empty/part-000.parquet"
    )
    assert silver_index_global_staging_path(root, RUN, DAY) == Path(
        "/Volumes/datasource/data_lake_staging/index_global/silver_index_global/"
        "trade_date=2026-10-04/operation=c8a8b9f5-7cd7-49c2-8492-04fcc41d12df/"
        "phase=silver/part-000.parquet"
    )


@pytest.mark.parametrize("phase", ["asia_1", "asia_2", "asia_3", "europe", "americas", "late_empty"])
def test_isolated_raw_candidates_keep_each_valid_phase_separate(tmp_path, phase):
    actual = raw_index_global_staging_path(tmp_path, "run-1", DAY, phase)
    assert actual == (
        tmp_path / "_staging/index_global/raw_index_global/trade_date=2026-10-04/"
        f"operation=run-1/phase={phase}/part-000.parquet"
    )
    assert not actual.exists()


def test_isolated_silver_candidate_and_formal_targets_remain_distinct(tmp_path):
    candidate = silver_index_global_staging_path(tmp_path, "run-2", DAY)
    assert candidate == (
        tmp_path / "_staging/index_global/silver_index_global/trade_date=2026-10-04/"
        "operation=run-2/phase=silver/part-000.parquet"
    )
    assert raw_index_global_path(tmp_path, DAY) == tmp_path / "raw/index_global/trade_date=2026-10-04/part-000.parquet"
    assert silver_index_global_path(tmp_path, DAY) == tmp_path / "silver/index_global/trade_date=2026-10-04/part-000.parquet"


@pytest.mark.parametrize("root", [
    Path("/Volumes/datasource/goldenshare-tushare-lake"),
    Path("/Volumes/datasource/goldenshare-tushare-lake/work"),
    Path(DEFAULT_LAKE_ROOT) / ".index_global_bootstrap_work",
    Path(DEFAULT_LAKE_ROOT) / "raw/index_global",
    Path("/Volumes/datasource/data_lake_staging"),
    Path("/Users/congming/other-lake"),
    Path("relative-lake"),
    Path("/private/tmp/lake/../escape"),
])
def test_unapproved_roots_are_rejected_without_probing_them(root, monkeypatch):
    def forbid_probe(*args, **kwargs):
        raise AssertionError("Rejected roots must not be probed")

    monkeypatch.setattr(Path, "stat", forbid_probe)
    monkeypatch.setattr(Path, "lstat", forbid_probe)
    with pytest.raises(ValueError, match="root"):
        raw_index_global_staging_path(root, RUN, DAY, "asia_1")
    with pytest.raises(ValueError, match="root"):
        silver_index_global_staging_path(root, RUN, DAY)


@pytest.mark.parametrize("day", ["20261004", "2026-2-01", "2026-02-30", "2026-10-04/../other", "", "{partition_key}"])
def test_staging_date_must_be_exact_valid_iso_day(tmp_path, day):
    with pytest.raises(ValueError, match="date"):
        raw_index_global_staging_path(tmp_path, RUN, day, "asia_1")
    with pytest.raises(ValueError, match="date"):
        silver_index_global_staging_path(tmp_path, RUN, day)


@pytest.mark.parametrize("run", ["", " ", ".", "..", "../escape", "a/b", "a\\b", "a\n", "x" * 241])
def test_staging_run_component_cannot_escape_or_form_invalid_filename(tmp_path, run):
    with pytest.raises(ValueError, match="run_id"):
        raw_index_global_staging_path(tmp_path, run, DAY, "asia_1")
    with pytest.raises(ValueError, match="run_id"):
        silver_index_global_staging_path(tmp_path, run, DAY)


@pytest.mark.parametrize("phase", ["unknown", "silver", "../asia_1", "asia_1/other", "", "asia_1 "])
def test_unknown_or_escaped_raw_phase_is_rejected(tmp_path, phase):
    with pytest.raises(ValueError, match="probe_phase"):
        raw_index_global_staging_path(tmp_path, RUN, DAY, phase)


def test_symlink_root_and_symlink_parent_are_rejected(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    for root in (alias, alias / "child"):
        with pytest.raises(ValueError, match="symbolic"):
            raw_index_global_staging_path(root, RUN, DAY, "asia_1")
        with pytest.raises(ValueError, match="symbolic"):
            silver_index_global_staging_path(root, RUN, DAY)


def test_system_temporary_root_is_accepted_without_creating_a_candidate():
    root = Path(gettempdir()) / "index-global-owned-test-root"
    assert raw_index_global_staging_path(root, RUN, DAY, "asia_1").is_relative_to(root / "_staging")
