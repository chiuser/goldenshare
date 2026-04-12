from __future__ import annotations

from types import SimpleNamespace

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
