from __future__ import annotations

import json

from lake_console.backend.app.services.lake_root_service import LakeRootService, REQUIRED_DIRECTORIES


def test_initialize_creates_layout(tmp_path):
    lake_root = tmp_path / "lake"

    LakeRootService(lake_root).initialize()

    for relative in REQUIRED_DIRECTORIES:
        assert (lake_root / relative).is_dir()
    payload = json.loads((lake_root / "manifest" / "lake.json").read_text(encoding="utf-8"))
    assert payload["layout_version"] == 1


def test_status_reports_missing_root(tmp_path):
    lake_root = tmp_path / "missing"

    status = LakeRootService(lake_root).get_status()

    assert status.path.exists is False
    assert any(risk.code == "lake_root_missing" for risk in status.risks)
