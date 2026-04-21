from __future__ import annotations

from dataclasses import replace

from src.foundation.services.sync_v2.linter import lint_all_sync_v2_contracts, lint_contract
from src.foundation.services.sync_v2.registry import get_sync_v2_contract


def test_lint_all_sync_v2_contracts_passes_current_registry() -> None:
    report = lint_all_sync_v2_contracts()

    assert report.passed is True
    assert report.issues == []


def test_lint_contract_reports_missing_fanout_defaults() -> None:
    contract = get_sync_v2_contract("margin")
    broken_contract = replace(
        contract,
        planning_spec=replace(contract.planning_spec, enum_fanout_defaults={}),
    )

    issues = lint_contract(broken_contract)

    assert any(issue.code == "fanout_defaults_missing" for issue in issues)


def test_lint_contract_reports_invalid_universe_policy() -> None:
    contract = get_sync_v2_contract("dc_member")
    broken_contract = replace(
        contract,
        planning_spec=replace(contract.planning_spec, universe_policy="unsupported_policy"),
    )

    issues = lint_contract(broken_contract)

    assert any(issue.code == "invalid_universe_policy" for issue in issues)
