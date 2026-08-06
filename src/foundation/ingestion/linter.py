from __future__ import annotations

from dataclasses import dataclass

from src.foundation.datasets.registry import list_dataset_definitions
from src.foundation.datasets.source_release_policies import SUPPORTED_SOURCE_RELEASE_POLICIES
from src.foundation.ingestion.runtime_registry import DATASET_RUNTIME_REGISTRY


SUPPORTED_SCOPED_REPAIR_POLICIES = {"existing_point_bucket_only"}
SUPPORTED_DUPLICATE_KEY_POLICIES = {"allow", "dedupe_identical_reject_conflicting"}


@dataclass(frozen=True, slots=True)
class IngestionLintIssue:
    dataset_key: str
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class IngestionLintReport:
    passed: bool
    issues: tuple[IngestionLintIssue, ...]


def lint_all_dataset_definitions() -> IngestionLintReport:
    issues: list[IngestionLintIssue] = []
    runtime_keys = set(DATASET_RUNTIME_REGISTRY)
    definition_keys: set[str] = set()
    for definition in list_dataset_definitions():
        dataset_key = definition.dataset_key
        definition_keys.add(dataset_key)
        if not definition.identity.display_name.strip():
            issues.append(IngestionLintIssue(dataset_key, "missing_display_name", "display_name 不能为空"))
        if not definition.source.source_fields:
            issues.append(IngestionLintIssue(dataset_key, "missing_source_fields", "source_fields 不能为空"))
        if definition.source.release_policy not in SUPPORTED_SOURCE_RELEASE_POLICIES:
            issues.append(
                IngestionLintIssue(
                    dataset_key,
                    "invalid_source_release_policy",
                    f"source.release_policy 不支持：{definition.source.release_policy}",
                )
            )
        if not definition.storage.target_table.strip():
            issues.append(IngestionLintIssue(dataset_key, "missing_target_table", "target_table 不能为空"))
        storage = definition.storage
        if storage.write_path == "serving_observed_snapshot_refresh":
            if storage.raw_dao_name is not None:
                issues.append(
                    IngestionLintIssue(
                        dataset_key,
                        "observed_snapshot_raw_dao_forbidden",
                        "serving_observed_snapshot_refresh 不得配置 raw_dao_name",
                    )
                )
            if storage.raw_table is not None or storage.std_table is not None:
                issues.append(
                    IngestionLintIssue(
                        dataset_key,
                        "observed_snapshot_raw_or_std_table_forbidden",
                        "serving_observed_snapshot_refresh 不得配置 raw_table 或 std_table",
                    )
                )
            if not storage.core_dao_name.strip() or not storage.observation_dao_name or not storage.observation_table:
                issues.append(
                    IngestionLintIssue(
                        dataset_key,
                        "observed_snapshot_dao_or_table_missing",
                        "serving_observed_snapshot_refresh 必须配置 current 与 observation DAO/表",
                    )
                )
            if storage.observation_table == storage.target_table:
                issues.append(
                    IngestionLintIssue(
                        dataset_key,
                        "observed_snapshot_table_not_distinct",
                        "observation_table 必须与 current target_table 不同",
                    )
                )
            if storage.conflict_columns != ("source_entity_key", "source_content_hash"):
                issues.append(
                    IngestionLintIssue(
                        dataset_key,
                        "observed_snapshot_conflict_columns_invalid",
                        "观察快照 conflict_columns 必须为 source_entity_key, source_content_hash",
                    )
                )
        elif storage.write_path == "serving_observed_fact_scope_refresh":
            if storage.raw_dao_name is not None or storage.raw_table is not None or storage.std_table is not None:
                issues.append(
                    IngestionLintIssue(
                        dataset_key,
                        "observed_fact_raw_or_std_forbidden",
                        "serving_observed_fact_scope_refresh 不得配置 raw DAO/raw/std 表",
                    )
                )
            if not storage.core_dao_name.strip() or not storage.observation_dao_name or not storage.observation_table:
                issues.append(
                    IngestionLintIssue(
                        dataset_key,
                        "observed_fact_dao_or_table_missing",
                        "serving_observed_fact_scope_refresh 必须配置 current 与 observation DAO/表",
                    )
                )
            if storage.observation_table == storage.target_table:
                issues.append(
                    IngestionLintIssue(
                        dataset_key,
                        "observed_fact_table_not_distinct",
                        "observation_table 必须与 current target_table 不同",
                    )
                )
            if storage.conflict_columns != ("source_entity_key", "source_content_hash"):
                issues.append(
                    IngestionLintIssue(
                        dataset_key,
                        "observed_fact_conflict_columns_invalid",
                        "按范围观察事实 conflict_columns 必须为 source_entity_key, source_content_hash",
                    )
                )
            if not definition.quality.unit_date_field or definition.quality.batch_unique_key_fields != ("source_entity_key",):
                issues.append(
                    IngestionLintIssue(
                        dataset_key,
                        "observed_fact_scope_contract_invalid",
                        "按范围观察事实必须声明 unit_date_field 与唯一 source_entity_key",
                    )
                )
        elif storage.write_path == "serving_direct_upsert":
            if storage.raw_dao_name is not None:
                issues.append(
                    IngestionLintIssue(dataset_key, "direct_serving_raw_dao_forbidden", "serving_direct_upsert 不得配置 raw_dao_name")
                )
            if storage.raw_table is not None:
                issues.append(
                    IngestionLintIssue(dataset_key, "direct_serving_raw_table_forbidden", "serving_direct_upsert 不得配置 raw_table")
                )
            if not storage.core_dao_name.strip():
                issues.append(
                    IngestionLintIssue(dataset_key, "direct_serving_core_dao_missing", "serving_direct_upsert 必须配置 core_dao_name")
                )
            if storage.layer_plan != "source->serving":
                issues.append(
                    IngestionLintIssue(dataset_key, "direct_serving_layer_plan_invalid", "serving_direct_upsert 的 layer_plan 必须为 source->serving")
                )
            if storage.serving_table != storage.target_table:
                issues.append(
                    IngestionLintIssue(dataset_key, "direct_serving_target_mismatch", "serving_direct_upsert 的 serving_table 必须等于 target_table")
                )
        elif storage.raw_dao_name is None or storage.raw_table is None:
            issues.append(
                IngestionLintIssue(dataset_key, "raw_storage_required", "非 serving_direct_upsert 写入路径必须配置 raw DAO 和 raw 表")
            )
        if definition.transaction.commit_policy != "unit":
            issues.append(
                IngestionLintIssue(
                    dataset_key,
                    "invalid_commit_policy",
                    f"transaction.commit_policy 必须为 unit，当前为 {definition.transaction.commit_policy}",
                )
            )
        if definition.planning.max_units_per_execution is not None and definition.planning.max_units_per_execution <= 0:
            issues.append(
                IngestionLintIssue(dataset_key, "invalid_max_units", "max_units_per_execution 必须大于 0")
            )
        if definition.planning.fetch_concurrency < 1 or definition.planning.fetch_concurrency > 4:
            issues.append(
                IngestionLintIssue(dataset_key, "invalid_fetch_concurrency", "fetch_concurrency 必须在 1 到 4 之间")
            )
        for fanout_field in definition.planning.enum_fanout_fields:
            field_names = {field.name for field in definition.input_model.filters}
            if fanout_field not in field_names:
                issues.append(
                    IngestionLintIssue(
                        dataset_key,
                        "fanout_field_missing",
                        f"enum_fanout_fields 引用了未定义 filter: {fanout_field}",
                )
            )
        quality = definition.quality
        batch_unique_key_fields = quality.batch_unique_key_fields
        normalized_batch_unique_fields = tuple(str(field_name).strip() for field_name in batch_unique_key_fields)
        if batch_unique_key_fields and any(not field_name for field_name in normalized_batch_unique_fields):
            issues.append(
                IngestionLintIssue(
                    dataset_key,
                    "batch_unique_key_field_invalid",
                    "quality.batch_unique_key_fields 不得包含空字段名",
                )
            )
        if len(normalized_batch_unique_fields) != len(set(normalized_batch_unique_fields)):
            issues.append(
                IngestionLintIssue(
                    dataset_key,
                    "batch_unique_key_fields_duplicate",
                    "quality.batch_unique_key_fields 不得包含重复字段",
                )
            )
        if not set(normalized_batch_unique_fields).issubset(set(definition.normalization.required_fields)):
            issues.append(
                IngestionLintIssue(
                    dataset_key,
                    "batch_unique_key_field_not_required",
                    "quality.batch_unique_key_fields 必须全部属于 normalization.required_fields",
                )
            )
        for field_name, required_values in quality.required_distinct_values.items():
            if not str(field_name).strip() or field_name not in definition.source.source_fields:
                issues.append(
                    IngestionLintIssue(
                        dataset_key,
                        "required_distinct_field_invalid",
                        f"quality.required_distinct_values 引用了无效 source field: {field_name}",
                    )
                )
            normalized_values = tuple(str(value).strip() for value in required_values)
            if not normalized_values or any(not value for value in normalized_values):
                issues.append(
                    IngestionLintIssue(
                        dataset_key,
                        "required_distinct_values_empty",
                        f"quality.required_distinct_values[{field_name}] 必须声明非空取值",
                    )
                )
            elif len(normalized_values) != len(set(normalized_values)):
                issues.append(
                    IngestionLintIssue(
                        dataset_key,
                        "required_distinct_values_duplicate",
                        f"quality.required_distinct_values[{field_name}] 不得包含重复取值",
                    )
                )
        if quality.unit_date_field is not None:
            if quality.unit_date_field not in definition.source.source_fields:
                issues.append(
                    IngestionLintIssue(
                        dataset_key,
                        "unit_date_field_not_in_source",
                        "quality.unit_date_field 必须是 source_fields 中的字段",
                    )
                )
            if quality.unit_date_field not in definition.normalization.date_fields:
                issues.append(
                    IngestionLintIssue(
                        dataset_key,
                        "unit_date_field_not_normalized",
                        "quality.unit_date_field 必须配置为 normalization.date_fields",
                    )
                )
        if quality.duplicate_key_policy not in SUPPORTED_DUPLICATE_KEY_POLICIES:
            issues.append(
                IngestionLintIssue(
                    dataset_key,
                    "invalid_duplicate_key_policy",
                    f"quality.duplicate_key_policy 不支持：{quality.duplicate_key_policy}",
                )
            )
        elif quality.duplicate_key_policy != "allow":
            conflict_columns = set(storage.conflict_columns or ())
            if not conflict_columns:
                issues.append(
                    IngestionLintIssue(
                        dataset_key,
                        "duplicate_key_policy_conflict_columns_missing",
                        "严格 duplicate_key_policy 必须配置 storage.conflict_columns",
                    )
                )
            elif not conflict_columns.issubset(set(definition.normalization.required_fields)):
                issues.append(
                    IngestionLintIssue(
                        dataset_key,
                        "duplicate_key_policy_identity_not_required",
                        "严格 duplicate_key_policy 的 conflict_columns 必须全部为 normalization.required_fields",
                    )
                )
        for field in definition.input_model.filters:
            if field.scoped_repair_policy not in (None, *SUPPORTED_SCOPED_REPAIR_POLICIES):
                issues.append(
                    IngestionLintIssue(
                        dataset_key,
                        "invalid_scoped_repair_policy",
                        f"filter {field.name} 的 scoped_repair_policy 不支持：{field.scoped_repair_policy}",
                    )
                )
    missing_runtime = sorted(definition_keys - runtime_keys)
    for dataset_key in missing_runtime:
        issues.append(
            IngestionLintIssue(dataset_key, "runtime_registry_missing", "DATASET_RUNTIME_REGISTRY 缺少该数据集")
        )
    extra_runtime = sorted(runtime_keys - definition_keys)
    for dataset_key in extra_runtime:
        issues.append(
            IngestionLintIssue(dataset_key, "runtime_registry_extra", "DATASET_RUNTIME_REGISTRY 存在多余数据集")
        )
    return IngestionLintReport(passed=not issues, issues=tuple(issues))
