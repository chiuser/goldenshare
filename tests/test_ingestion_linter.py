from __future__ import annotations

from dataclasses import replace

import pytest

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion import linter as linter_module
from src.foundation.ingestion.linter import lint_all_dataset_definitions


def test_lint_all_dataset_definitions_passes_current_registry() -> None:
    report = lint_all_dataset_definitions()
    assert report.passed is True
    assert report.issues == ()


@pytest.mark.parametrize("fetch_concurrency", (0, 5))
def test_lint_rejects_invalid_fetch_concurrency(monkeypatch, fetch_concurrency: int) -> None:
    definition = get_dataset_definition("daily")
    definition = replace(definition, planning=replace(definition.planning, fetch_concurrency=fetch_concurrency))
    monkeypatch.setattr(linter_module, "list_dataset_definitions", lambda: (definition,))
    monkeypatch.setattr(linter_module, "DATASET_RUNTIME_REGISTRY", {definition.dataset_key: object()})

    report = lint_all_dataset_definitions()

    assert report.passed is False
    assert [(issue.dataset_key, issue.code) for issue in report.issues] == [
        ("daily", "invalid_fetch_concurrency")
    ]


def test_lint_rejects_invalid_source_release_policy(monkeypatch) -> None:
    definition = get_dataset_definition("daily")
    definition = replace(definition, source=replace(definition.source, release_policy="tomorrow_maybe"))
    monkeypatch.setattr(linter_module, "list_dataset_definitions", lambda: (definition,))
    monkeypatch.setattr(linter_module, "DATASET_RUNTIME_REGISTRY", {definition.dataset_key: object()})

    report = lint_all_dataset_definitions()

    assert report.passed is False
    assert [(issue.dataset_key, issue.code) for issue in report.issues] == [
        ("daily", "invalid_source_release_policy")
    ]


def test_lint_requires_fund_daily_two_phase_commit_policy(monkeypatch) -> None:
    definition = get_dataset_definition("fund_daily")
    definition = replace(
        definition,
        transaction=replace(definition.transaction, commit_policy="unit"),
    )
    monkeypatch.setattr(linter_module, "list_dataset_definitions", lambda: (definition,))
    monkeypatch.setattr(linter_module, "DATASET_RUNTIME_REGISTRY", {definition.dataset_key: object()})

    report = lint_all_dataset_definitions()

    assert [(issue.dataset_key, issue.code) for issue in report.issues] == [
        ("fund_daily", "fund_daily_two_phase_commit_policy_invalid")
    ]


def test_lint_rejects_raw_then_serving_on_other_dataset(monkeypatch) -> None:
    definition = get_dataset_definition("daily")
    definition = replace(
        definition,
        transaction=replace(definition.transaction, commit_policy="raw_then_serving"),
    )
    monkeypatch.setattr(linter_module, "list_dataset_definitions", lambda: (definition,))
    monkeypatch.setattr(linter_module, "DATASET_RUNTIME_REGISTRY", {definition.dataset_key: object()})

    report = lint_all_dataset_definitions()

    assert [(issue.dataset_key, issue.code) for issue in report.issues] == [
        ("daily", "raw_then_serving_not_allowed")
    ]


def test_lint_rejects_raw_storage_on_direct_serving_write_path(monkeypatch) -> None:
    definition = get_dataset_definition("margin_detail")
    definition = replace(definition, storage=replace(definition.storage, raw_table="raw_tushare.margin_detail"))
    monkeypatch.setattr(linter_module, "list_dataset_definitions", lambda: (definition,))
    monkeypatch.setattr(linter_module, "DATASET_RUNTIME_REGISTRY", {definition.dataset_key: object()})

    report = lint_all_dataset_definitions()

    assert report.passed is False
    assert [(issue.dataset_key, issue.code) for issue in report.issues] == [
        ("margin_detail", "direct_serving_raw_table_forbidden")
    ]
