from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.foundation.serving.builders.registry import ServingBuilderRegistry
from src.foundation.serving.targets import SERVING_TARGET_DAO_ATTR


@dataclass(frozen=True)
class ServingCoverageIssue:
    dataset_key: str
    issue_type: str
    detail: str


def validate_serving_coverage(
    *,
    dao: Any,
    builder_registry: ServingBuilderRegistry,
) -> list[ServingCoverageIssue]:
    issues: list[ServingCoverageIssue] = []
    for dataset_key, target_dao_attr in SERVING_TARGET_DAO_ATTR.items():
        builder = builder_registry.get(dataset_key)
        if builder is None:
            issues.append(
                ServingCoverageIssue(
                    dataset_key=dataset_key,
                    issue_type="missing_builder",
                    detail=f"builder not registered for dataset={dataset_key}",
                )
            )
        if getattr(dao, target_dao_attr, None) is None:
            issues.append(
                ServingCoverageIssue(
                    dataset_key=dataset_key,
                    issue_type="missing_target_dao",
                    detail=f"DAOFactory has no attr={target_dao_attr}",
                )
            )
    return issues
