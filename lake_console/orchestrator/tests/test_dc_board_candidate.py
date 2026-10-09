from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestrator.defs.io import dc_board_candidate as candidates


def test_isolated_candidates_are_outside_lake_and_same_device(tmp_path):
    lake = tmp_path / "lake"
    target = lake / "raw/board/dc_daily/trade_date=2026-10-08/part-000.parquet"
    path = candidates.dc_board_candidate_path(lake_root=lake, target=target)
    assert not path.is_relative_to(lake)
    assert path.is_relative_to(tmp_path / "lake_staging")
    assert "run_id=" in str(path)
    candidates.assert_dc_board_candidate_can_promote(path, target)


def test_formal_mapping_uses_existing_staging_constant_without_creating_lake(monkeypatch):
    root = Path(candidates.DEFAULT_LAKE_ROOT)
    monkeypatch.setattr(Path, "is_dir", lambda _: True)
    assert candidates.dc_board_staging_root(root) == Path(candidates.DEFAULT_LAKE_STAGING_ROOT)


@pytest.mark.parametrize("root", ["/Volumes/datasource/goldenshare-tushare-lake", "/Users/other/lake"])
def test_arbitrary_or_retired_roots_are_rejected(root):
    with pytest.raises(ValueError):
        candidates.dc_board_staging_root(Path(root))


def test_cross_device_promotion_is_rejected_before_replace(tmp_path, monkeypatch):
    candidate = tmp_path / "staging/file.parquet"
    target = tmp_path / "lake/file.parquet"
    original = Path.stat
    def stat(path, *args, **kwargs):
        if path == candidate.parent:
            return SimpleNamespace(st_dev=1)
        if path == target.parent:
            return SimpleNamespace(st_dev=2)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "stat", stat)
    with pytest.raises(ValueError, match="same filesystem"):
        candidates.assert_dc_board_candidate_can_promote(candidate, target)
