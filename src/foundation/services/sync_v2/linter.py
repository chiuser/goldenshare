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
    "raw_std_publish_moneyflow_biying",
    "raw_std_publish_stock_basic",
    "raw_only_upsert",
    "raw_core_snapshot_insert_by_trade_date",
    "raw_index_period_serving_upsert",
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
ALLOWED_DATE_AXES = {"trade_open_day", "natural_day", "month_key", "month_window", "none"}
ALLOWED_BUCKET_RULES = {
    "every_open_day",
    "week_last_open_day",
    "month_last_open_day",
    "every_natural_day",
    "every_natural_month",
    "month_window_has_data",
    "not_applicable",
}
ALLOWED_INPUT_SHAPES = {
    "trade_date_or_start_end",
    "month_or_range",
    "start_end_month_window",
    "ann_date_or_start_end",
    "none",
}
ALLOWED_COMMIT_POLICIES = {"task", "unit"}
UNIT_COMMIT_REQUIRED_DATASETS = {"stk_mins", "stk_factor_pro", "dc_member", "index_daily", "index_weight"}


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
    date_model = contract.date_model
    if date_model.date_axis not in ALLOWED_DATE_AXES:
        issues.append(
            ContractLintIssue(
                contract.dataset_key,
                "invalid_date_axis",
                f"date_model.date_axis={date_model.date_axis} is not supported",
            )
        )
    if date_model.bucket_rule not in ALLOWED_BUCKET_RULES:
        issues.append(
            ContractLintIssue(
                contract.dataset_key,
                "invalid_bucket_rule",
                f"date_model.bucket_rule={date_model.bucket_rule} is not supported",
            )
        )
    if date_model.input_shape not in ALLOWED_INPUT_SHAPES:
        issues.append(
            ContractLintIssue(
                contract.dataset_key,
                "invalid_input_shape",
                f"date_model.input_shape={date_model.input_shape} is not supported",
            )
        )
    if date_model.date_axis == "none":
        if date_model.bucket_rule != "not_applicable" or date_model.input_shape != "none":
            issues.append(
                ContractLintIssue(
                    contract.dataset_key,
                    "invalid_date_model_combo",
                    "date_axis=none requires bucket_rule=not_applicable and input_shape=none",
                )
            )
        if date_model.observed_field is not None or date_model.audit_applicable:
            issues.append(
                ContractLintIssue(
                    contract.dataset_key,
                    "invalid_audit_model",
                    "date_axis=none requires observed_field=None and audit_applicable=False",
                )
            )
    elif date_model.audit_applicable and not date_model.observed_field:
        issues.append(
            ContractLintIssue(
                contract.dataset_key,
                "invalid_audit_model",
                "audit_applicable=True requires observed_field",
            )
        )
    if not date_model.audit_applicable and not date_model.not_applicable_reason:
        issues.append(
            ContractLintIssue(
                contract.dataset_key,
                "missing_not_applicable_reason",
                "audit_applicable=False requires not_applicable_reason",
            )
        )
    anchor_type = resolve_contract_anchor_type(contract)
    if anchor_type not in ALLOWED_ANCHOR_TYPES:
        issues.append(
            ContractLintIssue(
                contract.dataset_key,
                "invalid_anchor_type",
                f"date_model resolved anchor_type={anchor_type} is not supported",
            )
        )
    window_policy = resolve_contract_window_policy(contract)
    if window_policy not in ALLOWED_WINDOW_POLICIES:
        issues.append(
            ContractLintIssue(
                contract.dataset_key,
                "invalid_window_policy",
                f"date_model.window_mode={window_policy} is not supported",
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
    if contract.transaction_spec.commit_policy not in ALLOWED_COMMIT_POLICIES:
        issues.append(
            ContractLintIssue(
                contract.dataset_key,
                "invalid_commit_policy",
                f"transaction_spec.commit_policy={contract.transaction_spec.commit_policy} is not supported",
            )
        )
    if contract.transaction_spec.commit_policy == "unit":
        if not contract.transaction_spec.idempotent_write_required:
            issues.append(
                ContractLintIssue(
                    contract.dataset_key,
                    "unit_commit_requires_idempotent_write",
                    "unit commit policy requires idempotent_write_required=True",
                )
            )
        if not contract.transaction_spec.write_volume_assessment.strip():
            issues.append(
                ContractLintIssue(
                    contract.dataset_key,
                    "missing_write_volume_assessment",
                    "unit commit policy requires a real write-volume assessment note",
                )
            )
    if contract.dataset_key in UNIT_COMMIT_REQUIRED_DATASETS and contract.transaction_spec.commit_policy != "unit":
        issues.append(
            ContractLintIssue(
                contract.dataset_key,
                "p0_dataset_requires_unit_commit",
                "P0 dataset must declare unit commit policy",
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
