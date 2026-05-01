from __future__ import annotations

from pathlib import Path

from src.foundation.datasets.registry import list_dataset_definitions
from src.ops.catalog.dataset_catalog_view_resolver import validate_default_dataset_catalog


def test_ops_dataset_catalog_view_covers_registered_datasets() -> None:
    errors = validate_default_dataset_catalog(list_dataset_definitions())

    assert errors == []


def test_frontend_does_not_keep_dataset_group_mapping() -> None:
    forbidden_tokens = ("GROUP_CONFIG", "domain_display_name || \"分类配置异常\"")
    checked_files = [
        Path("frontend/src/pages/ops-v21-source-page.tsx"),
        Path("frontend/src/pages/ops-v21-task-auto-tab.tsx"),
        Path("frontend/src/pages/ops-v21-dataset-audit-page.tsx"),
    ]

    for path in checked_files:
        content = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            assert token not in content
