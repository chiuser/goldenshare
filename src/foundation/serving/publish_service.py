from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.foundation.dao.factory import DAOFactory
from src.foundation.resolution.policy_store import ResolutionPolicyStore
from src.foundation.resolution.types import ResolutionPolicy
from src.foundation.serving.builders.base import ServingBuildResult
from src.foundation.serving.builders.registry import ServingBuilderRegistry
from src.foundation.serving.builders.security_serving_builder import SecurityServingBuilder
from src.foundation.serving.targets import get_target_dao_attr


@dataclass(frozen=True)
class ServingPublishResult:
    written: int
    policy: ResolutionPolicy
    resolved_count: int


@dataclass(frozen=True)
class ServingPublishPlan:
    dataset_key: str
    target_dao_attr: str
    rows: list[dict[str, Any]]
    policy: ResolutionPolicy
    resolved_count: int


class ServingPublishService:
    def __init__(
        self,
        dao: DAOFactory,
        *,
        policy_store: ResolutionPolicyStore | None = None,
        security_builder: SecurityServingBuilder | None = None,
        builder_registry: ServingBuilderRegistry | None = None,
    ) -> None:
        self.dao = dao
        self._policy_store = policy_store or ResolutionPolicyStore()
        self._builder_registry = builder_registry or ServingBuilderRegistry()
        if self._builder_registry.get("stock_basic") is None:
            self._builder_registry.register(security_builder or SecurityServingBuilder())

    def plan_publish(
        self,
        *,
        dataset_key: str,
        std_rows_by_source: dict[str, list[dict[str, Any]]],
        target_dao_attr: str | None = None,
    ) -> ServingPublishPlan:
        resolved_target_dao_attr = target_dao_attr or get_target_dao_attr(dataset_key)
        if not resolved_target_dao_attr:
            raise ValueError(f"No serving target DAO mapping configured for dataset: {dataset_key}")
        builder = self._builder_registry.get(dataset_key)
        if builder is None:
            raise ValueError(f"No serving builder registered for dataset: {dataset_key}")
        target_dao = getattr(self.dao, resolved_target_dao_attr, None)
        if target_dao is None:
            raise ValueError(f"DAOFactory has no target DAO attr: {resolved_target_dao_attr}")

        policy = self._policy_store.get_enabled_policy(self.dao.session, dataset_key) or ResolutionPolicy(
            dataset_key=dataset_key,
            mode="primary",
            primary_source_key="tushare",
            fallback_source_keys=("biying",),
            version=1,
            enabled=True,
        )
        active_sources = self._policy_store.get_active_sources(self.dao.session, dataset_key)
        target_columns = {
            column.name
            for column in target_dao.model.__table__.columns
            if column.name not in {"created_at", "updated_at"}
        }
        build_result: ServingBuildResult = builder.build_rows(
            std_rows_by_source=std_rows_by_source,
            policy=policy,
            active_sources=active_sources if active_sources else None,
            target_columns=target_columns,
        )
        return ServingPublishPlan(
            dataset_key=dataset_key,
            target_dao_attr=resolved_target_dao_attr,
            rows=build_result.rows,
            policy=policy,
            resolved_count=build_result.resolved_count,
        )

    def execute_publish_plan(
        self,
        plan: ServingPublishPlan,
        *,
        dry_run: bool = False,
        allow_empty_rows: bool = True,
    ) -> ServingPublishResult:
        if not allow_empty_rows and not plan.rows:
            raise ValueError(f"Refuse to publish empty serving rows for dataset: {plan.dataset_key}")
        if dry_run:
            return ServingPublishResult(
                written=0,
                policy=plan.policy,
                resolved_count=plan.resolved_count,
            )
        target_dao = getattr(self.dao, plan.target_dao_attr, None)
        if target_dao is None:
            raise ValueError(f"DAOFactory has no target DAO attr: {plan.target_dao_attr}")
        written = target_dao.upsert_many(plan.rows)
        return ServingPublishResult(
            written=written,
            policy=plan.policy,
            resolved_count=plan.resolved_count,
        )

    def publish(
        self,
        *,
        dataset_key: str,
        std_rows_by_source: dict[str, list[dict[str, Any]]],
        target_dao_attr: str | None = None,
        dry_run: bool = False,
        allow_empty_rows: bool = True,
    ) -> ServingPublishResult:
        plan = self.plan_publish(
            dataset_key=dataset_key,
            std_rows_by_source=std_rows_by_source,
            target_dao_attr=target_dao_attr,
        )
        return self.execute_publish_plan(
            plan,
            dry_run=dry_run,
            allow_empty_rows=allow_empty_rows,
        )

    def publish_dataset(
        self,
        *,
        dataset_key: str,
        std_rows_by_source: dict[str, list[dict[str, Any]]],
        dry_run: bool = False,
        allow_empty_rows: bool = True,
    ) -> ServingPublishResult:
        return self.publish(
            dataset_key=dataset_key,
            std_rows_by_source=std_rows_by_source,
            dry_run=dry_run,
            allow_empty_rows=allow_empty_rows,
        )

    def publish_stock_basic_from_std(
        self,
        *,
        std_rows_by_source: dict[str, list[dict[str, Any]]],
    ) -> ServingPublishResult:
        return self.publish_dataset(dataset_key="stock_basic", std_rows_by_source=std_rows_by_source)
