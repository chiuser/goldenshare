from __future__ import annotations

from src.foundation.ingestion.linter import lint_all_dataset_definitions


def test_lint_all_dataset_definitions_passes_current_registry() -> None:
    report = lint_all_dataset_definitions()
    assert report.passed is True
    assert report.issues == ()
