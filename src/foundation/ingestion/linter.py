from __future__ import annotations

from dataclasses import dataclass

from src.foundation.datasets.registry import list_dataset_definitions
from src.foundation.datasets.source_release_policies import SUPPORTED_SOURCE_RELEASE_POLICIES
from src.foundation.ingestion.runtime_registry import DATASET_RUNTIME_REGISTRY
from src.foundation.ingestion.pre_write_validators import PRE_WRITE_VALIDATORS


SUPPORTED_SCOPED_REPAIR_POLICIES = {"existing_point_bucket_only", "existing_observed_point_scope_only"}
SUPPORTED_DUPLICATE_KEY_POLICIES = {"allow", "dedupe_identical_reject_conflicting"}
SUPPORTED_SOURCE_MULTIPLICITY_POLICIES = {"reject", "deduplicate_identical"}
SUPPORTED_EMPTY_RESULT_POLICIES = {"allow", "fail_unit", "fail_unit_per_request_variant"}


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
        staged_write = storage.write_path == "serving_staged_immutable_scope_publish"
        if definition.planning.page_processing_mode not in {"buffer_all", "staged_stream"}:
            issues.append(
                IngestionLintIssue(dataset_key, "page_processing_mode_invalid", "planning.page_processing_mode 仅支持 buffer_all/staged_stream")
            )
        if staged_write:
            if definition.planning.page_processing_mode != "staged_stream":
                issues.append(IngestionLintIssue(dataset_key, "staged_page_mode_required", "staged write path 必须使用 staged_stream"))
            if definition.planning.pagination_policy != "offset_limit" or not definition.planning.page_limit:
                issues.append(IngestionLintIssue(dataset_key, "staged_pagination_invalid", "staged write path 必须配置正数 offset_limit/page_limit"))
            if definition.planning.fetch_concurrency != 1 or definition.transaction.commit_policy != "unit":
                issues.append(IngestionLintIssue(dataset_key, "staged_execution_contract_invalid", "staged write path 必须单并发且按 unit 提交"))
            if storage.raw_dao_name is not None or storage.raw_table is not None or storage.std_table is not None:
                issues.append(IngestionLintIssue(dataset_key, "staged_raw_or_std_forbidden", "staged write path 不得配置 raw DAO/raw/std 表"))
            if storage.observation_dao_name is not None or storage.observation_table is not None:
                issues.append(IngestionLintIssue(dataset_key, "staged_observation_forbidden", "staged write path 不得配置 observation DAO/表"))
            if not storage.core_dao_name or not storage.stage_dao_name or not storage.stage_table:
                issues.append(IngestionLintIssue(dataset_key, "staged_dao_or_table_missing", "staged write path 必须配置 serving/stage DAO 与表"))
            if storage.serving_table != storage.target_table or storage.layer_plan != "source->serving":
                issues.append(IngestionLintIssue(dataset_key, "staged_serving_contract_invalid", "staged write path 必须 direct-serving 且 serving_table 等于 target_table"))
            identity_fields = tuple(storage.conflict_columns or ())
            if not identity_fields or not set(identity_fields).issubset(set(definition.normalization.required_fields)):
                issues.append(IngestionLintIssue(dataset_key, "staged_identity_invalid", "staged identity 必须非空且全部属于 normalization.required_fields"))
            if definition.quality.source_multiplicity_policy != "deduplicate_identical":
                issues.append(IngestionLintIssue(dataset_key, "staged_multiplicity_invalid", "staged write path 必须启用 exact duplicate 去重"))
        elif storage.stage_dao_name is not None or storage.stage_table is not None or definition.planning.page_processing_mode == "staged_stream":
            issues.append(IngestionLintIssue(dataset_key, "staged_contract_on_buffered_path", "非 staged write path 不得配置 stage 字段或 staged_stream"))
        elif storage.write_path == "serving_observed_snapshot_refresh":
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
            if not str(storage.core_dao_name or "").strip():
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
        elif storage.write_path == "serving_direct_scope_replace":
            if storage.raw_dao_name is not None or storage.raw_table is not None or storage.std_table is not None:
                issues.append(IngestionLintIssue(dataset_key, "scope_replace_raw_or_std_forbidden", "完整范围替换不得配置 raw DAO/raw/std 表"))
            if storage.observation_dao_name is not None or storage.observation_table is not None:
                issues.append(IngestionLintIssue(dataset_key, "scope_replace_observation_forbidden", "完整范围替换不得配置 observation DAO/表"))
            if storage.stage_dao_name is not None or storage.stage_table is not None:
                issues.append(IngestionLintIssue(dataset_key, "scope_replace_stage_forbidden", "完整范围替换不得配置 stage DAO/表"))
            if storage.layer_plan != "source->serving" or storage.serving_table != storage.target_table:
                issues.append(IngestionLintIssue(dataset_key, "scope_replace_serving_contract_invalid", "完整范围替换必须 direct-serving 且 serving_table 等于 target_table"))
            if storage.raw_conflict_columns is not None or not storage.core_dao_name:
                issues.append(IngestionLintIssue(dataset_key, "scope_replace_dao_contract_invalid", "完整范围替换必须仅配置 serving DAO"))
            required_fields = set(definition.normalization.required_fields)
            if not storage.replacement_scope_fields or not set(storage.replacement_scope_fields).issubset(required_fields):
                issues.append(IngestionLintIssue(dataset_key, "scope_replace_fields_invalid", "replacement_scope_fields 必须非空且全部为必填字段"))
            if not storage.conflict_columns or not set(storage.conflict_columns).issubset(required_fields):
                issues.append(IngestionLintIssue(dataset_key, "scope_replace_identity_invalid", "conflict_columns 必须非空且全部为必填字段"))
            if definition.quality.reject_policy != "fail_unit_on_any_rejection":
                issues.append(IngestionLintIssue(dataset_key, "scope_replace_reject_policy_invalid", "完整范围替换必须拒绝任意归一化失败行"))
            if definition.quality.empty_result_policy not in SUPPORTED_EMPTY_RESULT_POLICIES:
                issues.append(IngestionLintIssue(dataset_key, "scope_replace_empty_policy_invalid", "完整范围替换的空结果策略非法"))
            if not definition.quality.pre_write_validator_key:
                issues.append(IngestionLintIssue(dataset_key, "scope_replace_validator_missing", "完整范围替换必须声明预写校验器"))
        elif storage.write_path == "serving_immutable_fact_insert":
            if storage.raw_dao_name is not None or storage.raw_table is not None or storage.std_table is not None:
                issues.append(
                    IngestionLintIssue(
                        dataset_key,
                        "immutable_fact_raw_or_std_forbidden",
                        "serving_immutable_fact_insert 不得配置 raw DAO/raw/std 表",
                    )
                )
            if storage.observation_dao_name is not None or storage.observation_table is not None:
                issues.append(
                    IngestionLintIssue(
                        dataset_key,
                        "immutable_fact_observation_forbidden",
                        "serving_immutable_fact_insert 不得配置 observation DAO/表",
                    )
                )
            if storage.conflict_columns != ("source_entity_key",):
                issues.append(
                    IngestionLintIssue(
                        dataset_key,
                        "immutable_fact_conflict_columns_invalid",
                        "不可变事实 conflict_columns 必须仅为 source_entity_key",
                    )
                )
            if not storage.core_dao_name.strip():
                issues.append(
                    IngestionLintIssue(dataset_key, "immutable_fact_core_dao_missing", "不可变事实必须配置 core_dao_name")
                )
            if storage.layer_plan != "source->serving":
                issues.append(
                    IngestionLintIssue(dataset_key, "immutable_fact_layer_plan_invalid", "不可变事实的 layer_plan 必须为 source->serving")
                )
            if storage.serving_table != storage.target_table:
                issues.append(
                    IngestionLintIssue(dataset_key, "immutable_fact_target_mismatch", "不可变事实的 serving_table 必须等于 target_table")
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
        if quality.pre_write_validator_key is not None and quality.pre_write_validator_key not in PRE_WRITE_VALIDATORS:
            issues.append(
                IngestionLintIssue(
                    dataset_key,
                    "pre_write_validator_missing",
                    f"未注册预写校验器：{quality.pre_write_validator_key}",
                )
            )
        if quality.empty_result_policy not in SUPPORTED_EMPTY_RESULT_POLICIES:
            issues.append(
                IngestionLintIssue(
                    dataset_key,
                    "empty_result_policy_invalid",
                    f"quality.empty_result_policy 不支持：{quality.empty_result_policy}",
                )
            )
        variant_fields = definition.planning.request_variant_fields
        variant_defaults = definition.planning.request_variant_defaults
        if variant_fields or variant_defaults:
            input_names = {
                field.name
                for field in (*definition.input_model.time_fields, *definition.input_model.filters)
            }
            if not variant_fields or len(variant_fields) != len(set(variant_fields)):
                issues.append(IngestionLintIssue(dataset_key, "request_variant_fields_invalid", "request_variant_fields 必须非空且无重复"))
            if set(variant_defaults) != set(variant_fields):
                issues.append(IngestionLintIssue(dataset_key, "request_variant_defaults_invalid", "request_variant_defaults 必须精确覆盖 request_variant_fields"))
            if set(variant_fields) & input_names:
                issues.append(IngestionLintIssue(dataset_key, "request_variant_exposed", "内部 request variant 不得暴露为输入字段"))
            if set(variant_fields) & set(definition.planning.enum_fanout_fields):
                issues.append(IngestionLintIssue(dataset_key, "request_variant_fanout_conflict", "request variant 不得同时作为 enum fanout"))
            combination_count = 1
            for field_name in variant_fields:
                values = tuple(str(value).strip() for value in variant_defaults.get(field_name, ()))
                if not values or any(not value for value in values) or len(values) != len(set(values)):
                    issues.append(IngestionLintIssue(dataset_key, "request_variant_values_invalid", f"request variant {field_name} 必须非空且无重复"))
                combination_count *= max(len(values), 1)
            if combination_count > 16:
                issues.append(IngestionLintIssue(dataset_key, "request_variant_combinations_exceeded", "request variant 组合数不得超过 16"))
            if definition.planning.page_processing_mode != "buffer_all" or definition.planning.fetch_concurrency != 1:
                issues.append(IngestionLintIssue(dataset_key, "request_variant_execution_invalid", "request variant 只支持单并发 buffer_all"))
            if quality.empty_result_policy != "fail_unit_per_request_variant":
                issues.append(IngestionLintIssue(dataset_key, "request_variant_empty_policy_invalid", "request variant 必须逐变体拒绝空结果"))
        if quality.source_multiplicity_policy not in SUPPORTED_SOURCE_MULTIPLICITY_POLICIES:
            issues.append(
                IngestionLintIssue(
                    dataset_key,
                    "source_multiplicity_policy_invalid",
                    f"quality.source_multiplicity_policy 不支持：{quality.source_multiplicity_policy}",
                )
            )
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
