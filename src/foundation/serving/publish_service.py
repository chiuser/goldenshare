from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.foundation.dao.factory import DAOFactory
from src.foundation.resolution.policy_store import ResolutionPolicyStore
from src.foundation.resolution.types import ResolutionPolicy
from src.foundation.serving.builders.base import ServingBuildResult
from src.foundation.serving.builders.equity_adj_factor_serving_builder import EquityAdjFactorServingBuilder
from src.foundation.serving.builders.equity_daily_bar_serving_builder import EquityDailyBarServingBuilder
from src.foundation.serving.builders.equity_daily_basic_serving_builder import EquityDailyBasicServingBuilder
from src.foundation.serving.builders.index_daily_serving_builder import IndexDailyServingBuilder
from src.foundation.serving.builders.moneyflow_serving_builder import MoneyflowServingBuilder
from src.foundation.serving.builders.registry import ServingBuilderRegistry
from src.foundation.serving.builders.stk_period_bar_adj_month_serving_builder import StkPeriodBarAdjMonthServingBuilder
from src.foundation.serving.builders.stk_period_bar_adj_week_serving_builder import StkPeriodBarAdjWeekServingBuilder
from src.foundation.serving.builders.stk_period_bar_month_serving_builder import StkPeriodBarMonthServingBuilder
from src.foundation.serving.builders.stk_period_bar_week_serving_builder import StkPeriodBarWeekServingBuilder
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
    period_groups: tuple = ()


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
        default_builders = [
            security_builder or SecurityServingBuilder(),
            EquityDailyBarServingBuilder(),
            EquityAdjFactorServingBuilder(),
            EquityDailyBasicServingBuilder(),
            MoneyflowServingBuilder(),
            IndexDailyServingBuilder(),
            StkPeriodBarWeekServingBuilder(),
            StkPeriodBarMonthServingBuilder(),
            StkPeriodBarAdjWeekServingBuilder(),
            StkPeriodBarAdjMonthServingBuilder(),
        ]
        for builder in default_builders:
            if self._builder_registry.get(builder.dataset_key) is None:
                self._builder_registry.register(builder)

    @property
    def builder_registry(self) -> ServingBuilderRegistry:
        return self._builder_registry

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
        from src.foundation.datasets.registry import get_dataset_definition
        definition = get_dataset_definition(dataset_key)
        if definition.planning.stock_period_adj_policy is not None:
            from src.foundation.datasets.stock_period_adj_contracts import frequency, period_start
            from src.foundation.ingestion.stock_period_adj_delivery import bounded_transaction, select_groups
            freq = frequency(definition)
            groups = sorted({(row['ts_code'], period_start(row['trade_date'], freq))
                for rows in std_rows_by_source.values() for row in rows})
            with bounded_transaction(self.dao.session, definition.planning.stock_period_adj_policy, lambda: None):
                rows, _ = select_groups(self.dao.session, groups, freq, definition.planning.stock_period_adj_policy, lambda: None)
            return ServingPublishPlan(dataset_key=dataset_key, target_dao_attr=resolved_target_dao_attr,
                rows=rows, policy=policy, resolved_count=len(rows), period_groups=tuple(groups))
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
        from src.foundation.datasets.registry import get_dataset_definition
        definition = get_dataset_definition(plan.dataset_key)
        if definition.planning.stock_period_adj_policy is not None:
            from sqlalchemy.orm import Session
            from src.foundation.datasets.stock_period_adj_contracts import frequency, period_start
            from src.foundation.ingestion.stock_period_adj_delivery import bounded_transaction, acquire_writer, republish_groups
            freq = frequency(definition)
            groups = list(plan.period_groups)
            policy = definition.planning.stock_period_adj_policy
            with Session(self.dao.session.get_bind()) as business:
                with bounded_transaction(business, policy, lambda: None):
                    acquire_writer(business, freq)
                    rows, _ = republish_groups(business, groups, freq, policy, lambda: None)
                    business.commit()
            return ServingPublishResult(written=len(rows), policy=plan.policy, resolved_count=len(rows))
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
