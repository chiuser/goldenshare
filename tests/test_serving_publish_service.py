from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.foundation.dao.factory import DAOFactory
from src.foundation.resolution.types import ResolutionPolicy
from src.foundation.serving.publish_service import ServingPublishService


def test_serving_publish_service_uses_policy_store_and_writes_rows(mocker) -> None:
    session = mocker.Mock()
    dao = DAOFactory(session)
    dao.security = mocker.Mock()
    dao.security.model = SimpleNamespace(__table__=SimpleNamespace(columns=[SimpleNamespace(name="ts_code"), SimpleNamespace(name="source"), SimpleNamespace(name="created_at"), SimpleNamespace(name="updated_at")]))
    dao.security.upsert_many.return_value = 1

    policy_store = mocker.Mock()
    policy_store.get_enabled_policy.return_value = ResolutionPolicy(
        dataset_key="stock_basic",
        mode="primary",
        primary_source_key="tushare",
        fallback_source_keys=("biying",),
        version=7,
    )
    policy_store.get_active_sources.return_value = {"tushare", "biying"}

    builder = mocker.Mock()
    builder.dataset_key = "stock_basic"
    builder.build_rows.return_value = SimpleNamespace(rows=[{"ts_code": "000001.SZ", "source": "tushare"}], resolved_count=1)

    service = ServingPublishService(dao, policy_store=policy_store, security_builder=builder)
    result = service.publish_stock_basic_from_std(std_rows_by_source={"tushare": [], "biying": []})

    assert result.written == 1
    assert result.resolved_count == 1
    assert result.policy.version == 7
    dao.security.upsert_many.assert_called_once_with([{"ts_code": "000001.SZ", "source": "tushare"}])


def test_serving_publish_service_publish_dataset_uses_target_mapping(mocker) -> None:
    session = mocker.Mock()
    dao = DAOFactory(session)
    dao.security = mocker.Mock()
    dao.security.model = SimpleNamespace(__table__=SimpleNamespace(columns=[SimpleNamespace(name="ts_code"), SimpleNamespace(name="source")]))
    dao.security.upsert_many.return_value = 1

    policy_store = mocker.Mock()
    policy_store.get_enabled_policy.return_value = None
    policy_store.get_active_sources.return_value = {"tushare", "biying"}

    builder = mocker.Mock()
    builder.dataset_key = "stock_basic"
    builder.build_rows.return_value = SimpleNamespace(rows=[{"ts_code": "000001.SZ", "source": "tushare"}], resolved_count=1)

    service = ServingPublishService(dao, policy_store=policy_store, security_builder=builder)
    result = service.publish_dataset(dataset_key="stock_basic", std_rows_by_source={"tushare": [], "biying": []})

    assert result.written == 1
    assert result.policy.dataset_key == "stock_basic"


def test_serving_publish_service_fails_when_target_mapping_missing(mocker) -> None:
    session = mocker.Mock()
    dao = DAOFactory(session)
    policy_store = mocker.Mock()
    builder = mocker.Mock()
    builder.dataset_key = "stock_basic"
    service = ServingPublishService(dao, policy_store=policy_store, security_builder=builder)

    with pytest.raises(ValueError, match="No serving target DAO mapping configured"):
        service.publish_dataset(dataset_key="unknown_dataset", std_rows_by_source={})


def test_serving_publish_service_plan_publish_returns_structured_plan(mocker) -> None:
    session = mocker.Mock()
    dao = DAOFactory(session)
    dao.security = mocker.Mock()
    dao.security.model = SimpleNamespace(__table__=SimpleNamespace(columns=[SimpleNamespace(name="ts_code"), SimpleNamespace(name="source")]))
    policy_store = mocker.Mock()
    policy_store.get_enabled_policy.return_value = ResolutionPolicy(
        dataset_key="stock_basic",
        mode="primary",
        primary_source_key="tushare",
        fallback_source_keys=("biying",),
        version=5,
    )
    policy_store.get_active_sources.return_value = {"tushare"}
    builder = mocker.Mock()
    builder.dataset_key = "stock_basic"
    builder.build_rows.return_value = SimpleNamespace(rows=[{"ts_code": "000001.SZ", "source": "tushare"}], resolved_count=1)

    service = ServingPublishService(dao, policy_store=policy_store, security_builder=builder)
    plan = service.plan_publish(dataset_key="stock_basic", std_rows_by_source={"tushare": []})

    assert plan.dataset_key == "stock_basic"
    assert plan.target_dao_attr == "security"
    assert plan.resolved_count == 1
    assert plan.policy.version == 5


def test_serving_publish_service_execute_publish_plan_supports_dry_run(mocker) -> None:
    session = mocker.Mock()
    dao = DAOFactory(session)
    dao.security = mocker.Mock()
    dao.security.upsert_many.return_value = 9
    policy = ResolutionPolicy(dataset_key="stock_basic", mode="primary", primary_source_key="tushare")
    plan = SimpleNamespace(
        dataset_key="stock_basic",
        target_dao_attr="security",
        rows=[{"ts_code": "000001.SZ", "source": "tushare"}],
        policy=policy,
        resolved_count=1,
    )
    service = ServingPublishService(dao, policy_store=mocker.Mock(), security_builder=mocker.Mock(dataset_key="stock_basic"))

    result = service.execute_publish_plan(plan, dry_run=True)

    assert result.written == 0
    assert result.resolved_count == 1
    dao.security.upsert_many.assert_not_called()


def test_serving_publish_service_execute_publish_plan_rejects_empty_when_guard_enabled(mocker) -> None:
    session = mocker.Mock()
    dao = DAOFactory(session)
    dao.security = mocker.Mock()
    policy = ResolutionPolicy(dataset_key="stock_basic", mode="primary", primary_source_key="tushare")
    plan = SimpleNamespace(
        dataset_key="stock_basic",
        target_dao_attr="security",
        rows=[],
        policy=policy,
        resolved_count=0,
    )
    service = ServingPublishService(dao, policy_store=mocker.Mock(), security_builder=mocker.Mock(dataset_key="stock_basic"))

    with pytest.raises(ValueError, match="Refuse to publish empty serving rows"):
        service.execute_publish_plan(plan, allow_empty_rows=False)
