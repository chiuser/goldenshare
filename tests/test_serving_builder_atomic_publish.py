from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.foundation.dao.factory import DAOFactory
from src.foundation.resolution.types import ResolutionPolicy
from src.foundation.serving.publish_service import ServingPublishPlan, ServingPublishService


def test_serving_publish_executes_single_target_write_atomically(mocker) -> None:
    session = mocker.Mock()
    dao = DAOFactory(session)
    dao.security = mocker.Mock()
    dao.security.upsert_many.return_value = 2
    policy = ResolutionPolicy(dataset_key="stock_basic", mode="primary", primary_source_key="tushare")
    plan = ServingPublishPlan(
        dataset_key="stock_basic",
        target_dao_attr="security",
        rows=[
            {"ts_code": "000001.SZ", "source": "tushare"},
            {"ts_code": "000002.SZ", "source": "biying"},
        ],
        policy=policy,
        resolved_count=2,
    )
    service = ServingPublishService(dao, policy_store=mocker.Mock(), security_builder=mocker.Mock(dataset_key="stock_basic"))

    result = service.execute_publish_plan(plan)

    assert result.written == 2
    dao.security.upsert_many.assert_called_once_with(plan.rows)


def test_serving_publish_plan_and_execute_keep_consistent_row_count(mocker) -> None:
    session = mocker.Mock()
    dao = DAOFactory(session)
    dao.security = mocker.Mock()
    dao.security.model = SimpleNamespace(__table__=SimpleNamespace(columns=[SimpleNamespace(name="ts_code"), SimpleNamespace(name="source")]))
    dao.security.upsert_many.return_value = 1

    policy_store = mocker.Mock()
    policy_store.get_enabled_policy.return_value = ResolutionPolicy(
        dataset_key="stock_basic",
        mode="primary",
        primary_source_key="tushare",
        fallback_source_keys=("biying",),
    )
    policy_store.get_active_sources.return_value = {"tushare", "biying"}
    builder = mocker.Mock()
    builder.dataset_key = "stock_basic"
    builder.build_rows.return_value = SimpleNamespace(rows=[{"ts_code": "000001.SZ", "source": "tushare"}], resolved_count=1)

    service = ServingPublishService(dao, policy_store=policy_store, security_builder=builder)
    plan = service.plan_publish(dataset_key="stock_basic", std_rows_by_source={"tushare": []})
    result = service.execute_publish_plan(plan)

    assert len(plan.rows) == result.written
    assert result.resolved_count == 1


def test_serving_publish_plan_raises_when_target_dao_missing(mocker) -> None:
    session = mocker.Mock()
    dao = DAOFactory(session)
    policy_store = mocker.Mock()
    builder = mocker.Mock()
    builder.dataset_key = "stock_basic"
    service = ServingPublishService(dao, policy_store=policy_store, security_builder=builder)
    plan = ServingPublishPlan(
        dataset_key="stock_basic",
        target_dao_attr="unknown_target",
        rows=[],
        policy=ResolutionPolicy(dataset_key="stock_basic", mode="primary", primary_source_key="tushare"),
        resolved_count=0,
    )

    with pytest.raises(ValueError, match="DAOFactory has no target DAO attr"):
        service.execute_publish_plan(plan)
