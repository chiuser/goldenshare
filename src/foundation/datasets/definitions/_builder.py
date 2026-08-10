from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from typing import Any

from src.foundation.config.settings import get_settings
from src.foundation.datasets.freshness_policies import get_freshness_policy
from src.foundation.datasets.models import (
    DatasetActionCapability,
    DatasetCapabilities,
    DatasetCompletenessDefinition,
    DatasetDateModel,
    DatasetDefinition,
    DatasetDomain,
    DatasetIdentity,
    DatasetInputField,
    DatasetInputModel,
    DatasetNormalizationDefinition,
    DatasetObservability,
    DatasetPlanningDefinition,
    DatasetQualityPolicy,
    DatasetScheduleTimePolicy,
    DatasetSourceDefinition,
    DatasetStorageDefinition,
    DatasetTransactionDefinition,
    DatasetUniverseDefinition,
    DatasetUniverseSourceDefinition,
)


US_HOT_MARKET_VALUES_BY_DATASET = {
    "dc_hot": "美股市场",
    "ths_hot": "美股",
}


def _remove_value(values: tuple[str, ...], forbidden_value: str) -> tuple[str, ...]:
    return tuple(value for value in values if value != forbidden_value)


def _apply_hot_market_feature_flags(row: dict[str, Any]) -> dict[str, Any]:
    dataset_key = str(row["identity"]["dataset_key"])
    forbidden_market = US_HOT_MARKET_VALUES_BY_DATASET.get(dataset_key)
    if forbidden_market is None or get_settings().tushare_enable_us_hot_markets:
        return row

    patched = deepcopy(row)
    for field in patched["input_model"]["filters"]:
        if field.get("name") == "market":
            field["enum_values"] = _remove_value(tuple(field.get("enum_values", ())), forbidden_market)

    enum_defaults = patched["planning"].get("enum_fanout_defaults", {})
    if "market" in enum_defaults:
        enum_defaults["market"] = _remove_value(tuple(enum_defaults["market"]), forbidden_market)
    return patched


def build_definition(row: dict[str, Any]) -> DatasetDefinition:
    row = _apply_hot_market_feature_flags(row)
    identity = DatasetIdentity(**row["identity"])
    source_row = dict(row["source"])
    if "source_keys" not in source_row:
        raise ValueError(f"数据集定义 {identity.dataset_key} 缺少来源清单")
    source_keys = tuple(str(item).strip().lower() for item in source_row["source_keys"] if str(item).strip())
    if not source_keys:
        raise ValueError(f"数据集定义 {identity.dataset_key} 来源清单不能为空")
    source_default = str(source_row["source_key_default"]).strip().lower()
    if source_default not in source_keys:
        raise ValueError(f"数据集定义 {identity.dataset_key} 默认来源必须属于来源清单")
    source_row["source_key_default"] = source_default
    source_row["source_keys"] = source_keys
    date_model = DatasetDateModel(**row["date_model"])
    storage_row = dict(row["storage"])
    if "raw_table" not in storage_row:
        raise ValueError(f"数据集定义 {identity.dataset_key} 缺少原始层目标表")
    if "delivery_mode" not in storage_row:
        raise ValueError(f"数据集定义 {identity.dataset_key} 缺少交付模式")
    if "layer_plan" not in storage_row:
        raise ValueError(f"数据集定义 {identity.dataset_key} 缺少层级计划")
    if "std_table" not in storage_row:
        raise ValueError(f"数据集定义 {identity.dataset_key} 缺少标准层目标表")
    if "serving_table" not in storage_row:
        raise ValueError(f"数据集定义 {identity.dataset_key} 缺少服务层目标表")
    if "transaction" not in row:
        raise ValueError(f"数据集定义 {identity.dataset_key} 缺少事务策略")
    transaction_row = dict(row["transaction"])
    if "commit_policy" not in transaction_row:
        raise ValueError(f"数据集定义 {identity.dataset_key} 缺少事务提交策略")
    planning_row = dict(row["planning"])
    universe_row = planning_row.get("universe")
    if universe_row is not None:
        planning_row["universe"] = DatasetUniverseDefinition(
            request_field=str(universe_row["request_field"]).strip(),
            override_fields=tuple(str(item).strip() for item in universe_row.get("override_fields", ()) if str(item).strip()),
            sources=tuple(DatasetUniverseSourceDefinition(**source) for source in universe_row.get("sources", ())),
        )
    observability_row = dict(row["observability"])
    observability_row["freshness_policy"] = get_freshness_policy(identity.dataset_key)
    completeness = _build_completeness_definition(
        identity.dataset_key,
        date_model=date_model,
        row=row.get("completeness"),
    )
    storage = DatasetStorageDefinition(**storage_row)
    planning = DatasetPlanningDefinition(**planning_row)
    normalization = DatasetNormalizationDefinition(**row["normalization"])
    quality = DatasetQualityPolicy(**row["quality"])
    _validate_observed_serving_storage(
        dataset_key=identity.dataset_key,
        date_model=date_model,
        input_model=row["input_model"],
        source_fields=source_row["source_fields"],
        storage=storage,
        planning=planning,
        normalization=normalization,
        quality=quality,
    )
    return DatasetDefinition(
        identity=identity,
        domain=DatasetDomain(**row["domain"]),
        source=DatasetSourceDefinition(**source_row),
        date_model=date_model,
        input_model=DatasetInputModel(
            time_fields=tuple(DatasetInputField(**field) for field in row["input_model"]["time_fields"]),
            filters=tuple(DatasetInputField(**field) for field in row["input_model"]["filters"]),
            required_groups=tuple(tuple(item) for item in row["input_model"].get("required_groups", ())),
            mutually_exclusive_groups=tuple(tuple(item) for item in row["input_model"].get("mutually_exclusive_groups", ())),
            dependencies=tuple(tuple(item) for item in row["input_model"].get("dependencies", ())),
        ),
        storage=storage,
        planning=planning,
        normalization=normalization,
        capabilities=DatasetCapabilities(
            actions=tuple(_build_action_capability(action) for action in row["capabilities"]["actions"]),
        ),
        observability=DatasetObservability(**observability_row),
        quality=quality,
        transaction=DatasetTransactionDefinition(**transaction_row),
        completeness=completeness,
    )


def _build_action_capability(row: dict[str, Any]) -> DatasetActionCapability:
    action_row = dict(row)
    schedule_time_policy = action_row.get("schedule_time_policy")
    if schedule_time_policy is not None:
        policy_row = dict(schedule_time_policy)
        policy_row.setdefault(
            "generated_time_field",
            "trade_date" if policy_row.get("generated_time_mode") == "point" else "start_date_end_date",
        )
        policy = DatasetScheduleTimePolicy(**policy_row)
        if policy.policy not in {
            "monthly_last_day",
            "monthly_last_trading_day",
            "monthly_window_current_month",
            "trigger_day_single_range",
            "trigger_day_point",
            "latest_completed_calendar_quarter",
        }:
            raise ValueError(f"未知 schedule time policy：{policy.policy}")
        if not policy.schedule_types or not set(policy.schedule_types).issubset({"cron", "once"}):
            raise ValueError("schedule time policy 的 schedule_types 非法")
        if not set(policy.cron_repeat_modes).issubset({"daily", "weekly", "monthly", "intraday_interval"}):
            raise ValueError("schedule time policy 的 cron_repeat_modes 非法")
        if ("cron" in policy.schedule_types) != bool(policy.cron_repeat_modes):
            raise ValueError("schedule time policy 的 cron 类型与 cron_repeat_modes 必须同时声明")
        if policy.explicit_time_input not in {"allowed", "forbidden"}:
            raise ValueError("schedule time policy 的 explicit_time_input 非法")
        if policy.generated_time_mode not in {"point", "range"}:
            raise ValueError("schedule time policy 的 generated_time_mode 非法")
        if policy.generated_time_field not in {"trade_date", "ann_date", "start_date_end_date"}:
            raise ValueError("schedule time policy 的 generated_time_field 非法")
        if policy.generated_time_mode == "point" and policy.generated_time_field not in {"trade_date", "ann_date"}:
            raise ValueError("point schedule time policy 必须生成 trade_date 或 ann_date")
        if policy.generated_time_mode == "range" and policy.generated_time_field != "start_date_end_date":
            raise ValueError("range schedule time policy 必须生成 start_date/end_date")
        action_row["schedule_time_policy"] = policy
    capability = DatasetActionCapability(**action_row)
    if capability.schedule_time_policy is not None and not capability.schedule_enabled:
        raise ValueError("未开放 schedule 的 action 不得声明 schedule time policy")
    if (
        capability.schedule_time_policy is not None
        and capability.schedule_time_policy.generated_time_mode not in capability.supported_time_modes
    ):
        raise ValueError("schedule time policy 生成的时间模式必须属于 action.supported_time_modes")
    return capability


def _validate_observed_serving_storage(
    *,
    dataset_key: str,
    date_model: DatasetDateModel,
    input_model: dict[str, Any],
    source_fields: Iterable[str],
    storage: DatasetStorageDefinition,
    planning: DatasetPlanningDefinition,
    normalization: DatasetNormalizationDefinition,
    quality: DatasetQualityPolicy,
) -> None:
    if storage.write_path == "serving_observed_snapshot_refresh":
        _validate_observed_snapshot_storage(
            dataset_key=dataset_key,
            date_model=date_model,
            input_model=input_model,
            source_fields=source_fields,
            storage=storage,
            planning=planning,
            normalization=normalization,
            quality=quality,
        )
    elif storage.write_path == "serving_observed_fact_scope_refresh":
        _validate_observed_fact_scope_storage(
            dataset_key=dataset_key,
            date_model=date_model,
            input_model=input_model,
            source_fields=source_fields,
            storage=storage,
            planning=planning,
            normalization=normalization,
            quality=quality,
        )
    elif storage.write_path == "serving_immutable_fact_insert":
        _validate_immutable_fact_storage(
            dataset_key=dataset_key,
            date_model=date_model,
            input_model=input_model,
            source_fields=source_fields,
            storage=storage,
            planning=planning,
            normalization=normalization,
            quality=quality,
        )


def _validate_observed_snapshot_storage(
    *,
    dataset_key: str,
    date_model: DatasetDateModel,
    input_model: dict[str, Any],
    source_fields: Iterable[str],
    storage: DatasetStorageDefinition,
    planning: DatasetPlanningDefinition,
    normalization: DatasetNormalizationDefinition,
    quality: DatasetQualityPolicy,
) -> None:
    """Reject definitions that could replace a complete snapshot with a partial one."""
    if storage.write_path != "serving_observed_snapshot_refresh":
        return

    invalid: list[str] = []
    if (
        date_model.date_axis != "none"
        or date_model.bucket_rule != "not_applicable"
        or date_model.input_shape != "none"
        or date_model.window_mode != "none"
        or date_model.observed_field is not None
        or date_model.audit_applicable
    ):
        invalid.append("必须是无时间、无日期审计的数据集")
    if input_model.get("time_fields") or input_model.get("filters"):
        invalid.append("不得暴露时间或业务筛选输入")
    if planning.universe_policy != "no_pool" or planning.enum_fanout_fields:
        invalid.append("必须是单个完整快照单元，不得对象池或枚举 fan-out")
    if storage.raw_dao_name is not None or storage.raw_table is not None or storage.std_table is not None:
        invalid.append("不得配置 raw/std 存储")
    if not storage.core_dao_name.strip() or not storage.observation_dao_name or not storage.observation_table:
        invalid.append("必须配置 current 与 observation DAO/表")
    if storage.serving_table != storage.target_table:
        invalid.append("serving_table 必须等于 current target_table")
    if storage.observation_table == storage.target_table:
        invalid.append("observation_table 必须与 current target_table 不同")
    if storage.layer_plan != "source->serving":
        invalid.append("layer_plan 必须为 source->serving")
    if storage.raw_conflict_columns is not None:
        invalid.append("不得配置 raw_conflict_columns")
    if storage.conflict_columns != ("source_entity_key", "source_content_hash"):
        invalid.append("conflict_columns 必须为 source_entity_key, source_content_hash")
    raw_source_fields = tuple(source_fields)
    normalized_source_fields = tuple(str(item).strip() for item in raw_source_fields if str(item).strip())
    if not normalized_source_fields:
        invalid.append("必须声明显式 source_fields")
    elif len(normalized_source_fields) != len(raw_source_fields):
        invalid.append("source_fields 不得包含空白字段")
    elif any(not isinstance(item, str) or item != item.strip() for item in raw_source_fields):
        invalid.append("source_fields 必须是无前后空白的字符串")
    elif len(normalized_source_fields) != len(set(normalized_source_fields)):
        invalid.append("source_fields 不得重复")
    reserved_source_fields = {
        "source_entity_key",
        "source_content_hash",
        "observed_at",
        "first_observed_at",
        "last_observed_at",
        "created_at",
        "updated_at",
    }
    conflicting_source_fields = sorted(set(normalized_source_fields) & reserved_source_fields)
    if conflicting_source_fields:
        invalid.append(f"source_fields 不得占用协议元数据列：{', '.join(conflicting_source_fields)}")
    if "source_entity_key" not in normalization.required_fields:
        invalid.append("normalization.required_fields 必须包含 source_entity_key")
    if quality.duplicate_key_policy != "allow":
        invalid.append("duplicate_key_policy 必须为 allow，由 writer 检测完全重复源记录")
    if invalid:
        raise ValueError(f"数据集定义 {dataset_key} 的观察快照写入契约非法：{'；'.join(invalid)}")


def _validate_observed_fact_scope_storage(
    *,
    dataset_key: str,
    date_model: DatasetDateModel,
    input_model: dict[str, Any],
    source_fields: Iterable[str],
    storage: DatasetStorageDefinition,
    planning: DatasetPlanningDefinition,
    normalization: DatasetNormalizationDefinition,
    quality: DatasetQualityPolicy,
) -> None:
    invalid: list[str] = []
    expected_scope_field = {
        "trade_date_or_start_end": "trade_date",
        "ann_date_or_start_end": "ann_date",
    }.get(date_model.input_shape)
    if (
        date_model.date_axis != "natural_day"
        or date_model.bucket_rule != "not_applicable"
        or date_model.window_mode != "point_or_range"
        or expected_scope_field is None
        or date_model.observed_field != expected_scope_field
        or date_model.audit_applicable
    ):
        invalid.append("必须是按自然日 point/range 输入且不做连续日期审计的数据集")
    time_field_names = tuple(str(field.get("name") or "").strip() for field in input_model.get("time_fields", ()))
    if time_field_names != (expected_scope_field, "start_date", "end_date") or input_model.get("filters"):
        invalid.append(f"只能暴露 {expected_scope_field}/start_date/end_date，不得暴露业务筛选输入")
    if planning.universe_policy != "no_pool" or planning.enum_fanout_fields:
        invalid.append("每个日期必须是一个全市场单元，不得对象池或枚举 fan-out")
    if planning.pagination_policy != "offset_limit" or not planning.page_limit:
        invalid.append("必须使用声明 page_limit 的 offset_limit 分页")
    if storage.raw_dao_name is not None or storage.raw_table is not None or storage.std_table is not None:
        invalid.append("不得配置 raw/std 存储")
    if not storage.core_dao_name.strip() or not storage.observation_dao_name or not storage.observation_table:
        invalid.append("必须配置 current 与 observation DAO/表")
    if storage.serving_table != storage.target_table or storage.observation_table == storage.target_table:
        invalid.append("serving/current/observation 表关系非法")
    if storage.layer_plan != "source->serving" or storage.raw_conflict_columns is not None:
        invalid.append("必须 direct-serving 且不得配置 raw_conflict_columns")
    if storage.conflict_columns != ("source_entity_key", "source_content_hash"):
        invalid.append("conflict_columns 必须为 source_entity_key, source_content_hash")

    raw_source_fields = tuple(source_fields)
    normalized_source_fields = tuple(str(item).strip() for item in raw_source_fields if str(item).strip())
    if not normalized_source_fields or len(normalized_source_fields) != len(raw_source_fields):
        invalid.append("必须声明非空且无空白项的显式 source_fields")
    elif len(normalized_source_fields) != len(set(normalized_source_fields)):
        invalid.append("source_fields 不得重复")
    if expected_scope_field not in normalized_source_fields:
        invalid.append(f"source_fields 必须包含 scope 字段 {expected_scope_field}")
    if "source_entity_key" not in normalization.required_fields:
        invalid.append("normalization.required_fields 必须包含 source_entity_key")
    if quality.unit_date_field != expected_scope_field:
        invalid.append(f"quality.unit_date_field 必须为 {expected_scope_field}")
    if quality.batch_unique_key_fields != ("source_entity_key",):
        invalid.append("batch_unique_key_fields 必须为 source_entity_key")
    if quality.duplicate_key_policy != "allow":
        invalid.append("duplicate_key_policy 必须为 allow，由完整批次唯一性门禁处理")
    if invalid:
        raise ValueError(f"数据集定义 {dataset_key} 的按范围观察事实写入契约非法：{'；'.join(invalid)}")


def _validate_immutable_fact_storage(
    *,
    dataset_key: str,
    date_model: DatasetDateModel,
    input_model: dict[str, Any],
    source_fields: Iterable[str],
    storage: DatasetStorageDefinition,
    planning: DatasetPlanningDefinition,
    normalization: DatasetNormalizationDefinition,
    quality: DatasetQualityPolicy,
) -> None:
    invalid: list[str] = []
    expected_scope_field = {
        "trade_date_or_start_end": "trade_date",
        "ann_date_or_start_end": "ann_date",
    }.get(date_model.input_shape)
    if (
        date_model.date_axis != "natural_day"
        or date_model.bucket_rule != "not_applicable"
        or date_model.window_mode != "point_or_range"
        or expected_scope_field is None
        or date_model.observed_field != expected_scope_field
        or date_model.audit_applicable
    ):
        invalid.append("必须是按自然日 point/range 输入且不做连续日期审计的事件事实")
    time_fields = tuple(str(field.get("name") or "").strip() for field in input_model.get("time_fields", ()))
    if time_fields != (expected_scope_field, "start_date", "end_date") or input_model.get("filters"):
        invalid.append(f"只能暴露 {expected_scope_field}/start_date/end_date，不得暴露业务筛选输入")
    if planning.universe_policy != "no_pool" or planning.enum_fanout_fields:
        invalid.append("每个日期必须是一个全市场单元，不得对象池或枚举 fan-out")
    if planning.pagination_policy != "offset_limit" or not planning.page_limit:
        invalid.append("必须使用声明 page_limit 的 offset_limit 分页")
    if storage.raw_dao_name is not None or storage.raw_table is not None or storage.std_table is not None:
        invalid.append("不得配置 raw DAO/raw/std 表")
    if storage.observation_dao_name is not None or storage.observation_table is not None:
        invalid.append("不可变事实不得配置 observation DAO/表")
    if not str(storage.core_dao_name or "").strip() or storage.serving_table != storage.target_table:
        invalid.append("必须配置唯一 serving DAO 且 serving_table 等于 target_table")
    if storage.layer_plan != "source->serving" or storage.raw_conflict_columns is not None:
        invalid.append("必须 direct-serving 且不得配置 raw_conflict_columns")
    if storage.conflict_columns != ("source_entity_key",):
        invalid.append("conflict_columns 必须仅为 source_entity_key")

    raw_source_fields = tuple(source_fields)
    normalized_source_fields = tuple(str(item).strip() for item in raw_source_fields if str(item).strip())
    if not normalized_source_fields or len(normalized_source_fields) != len(raw_source_fields):
        invalid.append("必须声明非空且无空白项的显式 source_fields")
    elif len(normalized_source_fields) != len(set(normalized_source_fields)):
        invalid.append("source_fields 不得重复")
    if expected_scope_field not in normalized_source_fields:
        invalid.append(f"source_fields 必须包含 scope 字段 {expected_scope_field}")
    if expected_scope_field not in normalization.date_fields:
        invalid.append(f"normalization.date_fields 必须包含 scope 字段 {expected_scope_field}")
    if quality.unit_date_field != expected_scope_field:
        invalid.append(f"quality.unit_date_field 必须为 {expected_scope_field}")
    if quality.batch_unique_key_fields != ("source_entity_key",):
        invalid.append("batch_unique_key_fields 必须为 source_entity_key")
    if quality.source_multiplicity_policy not in {"reject", "deduplicate_identical"}:
        invalid.append("source_multiplicity_policy 非法")
    if "source_entity_key" not in normalization.required_fields:
        invalid.append("normalization.required_fields 必须包含 source_entity_key")
    if invalid:
        raise ValueError(f"数据集定义 {dataset_key} 的不可变事实写入契约非法：{'；'.join(invalid)}")


def _build_completeness_definition(
    dataset_key: str,
    *,
    date_model: DatasetDateModel,
    row: dict[str, Any] | None,
) -> DatasetCompletenessDefinition:
    if row is None:
        scope = "date_bucket" if date_model.audit_applicable else "not_applicable"
        return DatasetCompletenessDefinition(scope=scope)

    completeness = DatasetCompletenessDefinition(
        scope=str(row["scope"]).strip(),
        subject_kind=row.get("subject_kind"),
        subject_key_fields=tuple(str(item).strip() for item in row.get("subject_key_fields", ()) if str(item).strip()),
        actual_key_fields=tuple(str(item).strip() for item in row.get("actual_key_fields", ()) if str(item).strip()),
        universe_strategy=row.get("universe_strategy"),
        universe_source_table=row.get("universe_source_table"),
        universe_key_field=row.get("universe_key_field"),
        universe_name_field=row.get("universe_name_field"),
        lifecycle_start_field=row.get("lifecycle_start_field"),
        lifecycle_end_field=row.get("lifecycle_end_field"),
        status_field=row.get("status_field"),
        active_status_values=tuple(str(item).strip() for item in row.get("active_status_values", ()) if str(item).strip()),
    )
    _validate_completeness_definition(dataset_key, date_model=date_model, completeness=completeness)
    return completeness


def _validate_completeness_definition(
    dataset_key: str,
    *,
    date_model: DatasetDateModel,
    completeness: DatasetCompletenessDefinition,
) -> None:
    if completeness.scope not in {"date_bucket", "date_subject_matrix", "not_applicable"}:
        raise ValueError(f"数据集定义 {dataset_key} 的完整性审计 scope 无效：{completeness.scope}")
    if not date_model.audit_applicable and completeness.scope != "not_applicable":
        raise ValueError(f"数据集定义 {dataset_key} 不支持日期审计时，完整性审计 scope 必须为 not_applicable")
    if completeness.scope != "date_subject_matrix":
        return

    required_fields = {
        "subject_kind": completeness.subject_kind,
        "subject_key_fields": completeness.subject_key_fields,
        "actual_key_fields": completeness.actual_key_fields,
        "universe_strategy": completeness.universe_strategy,
        "universe_source_table": completeness.universe_source_table,
        "universe_key_field": completeness.universe_key_field,
    }
    missing = [name for name, value in required_fields.items() if not value]
    if missing:
        raise ValueError(f"数据集定义 {dataset_key} 的对象矩阵审计配置缺少字段：{', '.join(missing)}")


def build_definitions(rows: Iterable[dict[str, Any]]) -> tuple[DatasetDefinition, ...]:
    return tuple(build_definition(row) for row in rows)
