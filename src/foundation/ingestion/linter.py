from __future__ import annotations

from dataclasses import dataclass

from src.foundation.datasets.registry import list_dataset_definitions
from src.foundation.ingestion.runtime_registry import DATASET_RUNTIME_REGISTRY


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
        if not definition.storage.target_table.strip():
            issues.append(IngestionLintIssue(dataset_key, "missing_target_table", "target_table 不能为空"))
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
