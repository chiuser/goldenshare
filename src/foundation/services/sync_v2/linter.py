from __future__ import annotations

from dataclasses import dataclass, field

from src.foundation.services.sync_v2.contracts import (
    DatasetSyncContract,
    resolve_contract_anchor_type,
    resolve_contract_window_policy,
)
from src.foundation.services.sync_v2.registry import list_sync_v2_contracts

ALLOWED_WRITE_PATHS = {
    "raw_core_upsert",
    "raw_std_publish_moneyflow",
    "raw_core_snapshot_insert_by_trade_date",
    "raw_index_period_serving_upsert",
    "raw_index_daily_active_pool_upsert",
}
ALLOWED_UNIVERSE_POLICIES = {"none", "dc_index_board_codes", "index_active_codes", "ths_index_board_codes"}
ALLOWED_ANCHOR_TYPES = {
    "trade_date",
    "week_end_trade_date",
    "month_end_trade_date",
    "month_range_natural",
    "month_key_yyyymm",
    "natural_date_range",
    "none",
}
ALLOWED_WINDOW_POLICIES = {"point", "range", "point_or_range", "none"}


@dataclass(slots=True, frozen=True)
class ContractLintIssue:
    dataset_key: str
    code: str
    message: str


@dataclass(slots=True, frozen=True)
class ContractLintReport:
    passed: bool
    issues: list[ContractLintIssue] = field(default_factory=list)


def lint_contract(contract: DatasetSyncContract) -> list[ContractLintIssue]:
    issues: list[ContractLintIssue] = []
    if not contract.run_profiles_supported:
        issues.append(ContractLintIssue(contract.dataset_key, "missing_run_profiles", "run_profiles_supported must not be empty"))
    if not contract.source_spec.fields:
        issues.append(ContractLintIssue(contract.dataset_key, "missing_source_fields", "source_spec.fields must not be empty"))
    if not contract.write_spec.raw_dao_name or not contract.write_spec.core_dao_name:
        issues.append(ContractLintIssue(contract.dataset_key, "missing_writer_dao", "write_spec.raw_dao_name/core_dao_name must not be empty"))
    if contract.write_spec.write_path not in ALLOWED_WRITE_PATHS:
        issues.append(
            ContractLintIssue(
                contract.dataset_key,
                "invalid_write_path",
                f"write_spec.write_path={contract.write_spec.write_path} is not supported",
            )
        )
    if contract.planning_spec.universe_policy not in ALLOWED_UNIVERSE_POLICIES:
        issues.append(
            ContractLintIssue(
                contract.dataset_key,
                "invalid_universe_policy",
                f"planning_spec.universe_policy={contract.planning_spec.universe_policy} is not supported",
            )
        )
    anchor_type = resolve_contract_anchor_type(contract)
    if anchor_type not in ALLOWED_ANCHOR_TYPES:
        issues.append(
            ContractLintIssue(
                contract.dataset_key,
                "invalid_anchor_type",
                f"planning_spec.anchor_type={anchor_type} is not supported",
            )
        )
    window_policy = resolve_contract_window_policy(contract)
    if window_policy not in ALLOWED_WINDOW_POLICIES:
        issues.append(
            ContractLintIssue(
                contract.dataset_key,
                "invalid_window_policy",
                f"planning_spec.window_policy={window_policy} is not supported",
            )
        )
    if anchor_type == "none" and window_policy == "point_or_range":
        issues.append(
            ContractLintIssue(
                contract.dataset_key,
                "invalid_anchor_window_combo",
                "anchor_type=none cannot use window_policy=point_or_range",
            )
        )
    profiles = set(contract.run_profiles_supported)
    has_point = "point_incremental" in profiles
    has_range = "range_rebuild" in profiles
    if window_policy == "point" and has_range:
        issues.append(
            ContractLintIssue(
                contract.dataset_key,
                "window_profile_mismatch",
                "window_policy=point does not match range_rebuild support",
            )
        )
    if window_policy == "range" and has_point:
        issues.append(
            ContractLintIssue(
                contract.dataset_key,
                "window_profile_mismatch",
                "window_policy=range does not match point_incremental support",
            )
        )
    if window_policy == "none" and (has_point or has_range):
        issues.append(
            ContractLintIssue(
                contract.dataset_key,
                "window_profile_mismatch",
                "window_policy=none cannot be used with point_incremental/range_rebuild",
            )
        )
    for enum_key in contract.planning_spec.enum_fanout_fields:
        defaults = contract.planning_spec.enum_fanout_defaults.get(enum_key)
        if defaults is None or len(defaults) == 0:
            issues.append(
                ContractLintIssue(
                    contract.dataset_key,
                    "fanout_defaults_missing",
                    f"enum fanout field {enum_key} must provide defaults",
                )
            )
    return issues


def lint_all_sync_v2_contracts() -> ContractLintReport:
    issues: list[ContractLintIssue] = []
    contracts = list_sync_v2_contracts()
    seen_keys: set[str] = set()
    for contract in contracts:
        if contract.dataset_key in seen_keys:
            issues.append(ContractLintIssue(contract.dataset_key, "duplicate_dataset_key", "dataset_key duplicated"))
        seen_keys.add(contract.dataset_key)
        issues.extend(lint_contract(contract))
    return ContractLintReport(passed=len(issues) == 0, issues=issues)
