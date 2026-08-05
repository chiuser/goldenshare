from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.foundation.dao.factory import DAOFactory
from src.foundation.dao.observed_snapshot_dao import ObservedSnapshotDAO
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion import DatasetActionRequest, DatasetActionResolver, DatasetTimeInput
from src.foundation.ingestion.errors import IngestionWriteError
from src.foundation.ingestion.normalizer import DatasetNormalizer
from src.foundation.ingestion.source_client import DatasetSourceClient, SourceFetchResult
import src.foundation.ingestion.source_client as source_client_module
from src.foundation.ingestion.writer import DatasetWriter
from src.foundation.models.base import Base
from src.foundation.models.core_serving.fund_company_current import FundCompanyCurrent
from src.foundation.models.core_serving.fund_company_observation import FundCompanyObservation
from src.foundation.models.core_serving.mkt_idx_bmk_current import MktIdxBmkCurrent
from src.foundation.models.core_serving.mkt_idx_bmk_observation import MktIdxBmkObservation
from src.foundation.models.table_model_registry import table_model_registry


def _company_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "name": "示例基金管理有限公司",
        "shortname": "示例基金",
        "short_enname": None,
        "province": "北京市",
        "city": "北京市",
        "address": "示例地址",
        "phone": "010-00000000",
        "office": "示例办公地址",
        "website": "https://example.invalid",
        "chairman": "甲",
        "manager": "乙",
        "reg_capital": 1000.0,
        "setup_date": "20200101",
        "end_date": None,
        "employees": 10.0,
        "main_business": "基金管理",
        "org_code": "ORG-1",
        "credit_code": "911100000000000001",
    }
    row.update(overrides)
    return row


def _benchmark_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "ts_code": "000001.SH",
        "symbol": "000001",
        "name": "上证指数",
        "fullname": "上证综合指数",
        "bmk_level": "一类库",
        "bmk_type": "宽基",
        "bmk_src": "中证指数",
        "idx_type": "综合类指数",
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    ("dataset_key", "rows", "expected_offsets"),
    (
        ("fund_company", [_company_row(name=f"公司{i}", credit_code=f"C{i}") for i in range(204)], [0, 64, 128, 192]),
        ("mkt_idx_bmk", [_benchmark_row(ts_code=f"{i:06d}.SH") for i in range(141)], [0, 64, 128]),
    ),
)
def test_public_fund_source_client_paginates_with_explicit_fields(
    monkeypatch,
    dataset_key: str,
    rows: list[dict[str, object]],
    expected_offsets: list[int],
) -> None:
    definition = get_dataset_definition(dataset_key)
    calls: list[tuple[dict, tuple[str, ...]]] = []

    class Connector:
        def call(self, *, api_name: str, params: dict, fields: tuple[str, ...]) -> list[dict]:
            assert api_name == definition.source.api_name
            calls.append((dict(params), fields))
            offset = int(params["offset"])
            limit = int(params["limit"])
            return [dict(row) for row in rows[offset : offset + limit]]

    monkeypatch.setattr(source_client_module, "create_source_connector", lambda source_key: Connector())
    plan = DatasetActionResolver(SimpleNamespace()).build_plan(
        DatasetActionRequest(dataset_key=dataset_key, action="maintain", time_input=DatasetTimeInput(mode="none"))
    )

    result = DatasetSourceClient().fetch(definition=definition, unit=plan.units[0])

    assert [params["offset"] for params, _ in calls] == expected_offsets
    assert {params["limit"] for params, _ in calls} == {64}
    assert all(fields == definition.source.source_fields for _, fields in calls)
    assert result.request_count == len(expected_offsets)
    assert result.rows_raw == rows


def test_public_fund_identity_transforms_preserve_source_variants_and_fallbacks() -> None:
    definition = get_dataset_definition("fund_company")
    result = DatasetNormalizer().normalize(
        definition=definition,
        fetch_result=SourceFetchResult(
            unit_id="fund-company",
            request_count=1,
            retry_count=0,
            latency_ms=0,
            rows_raw=[
                _company_row(name="同码甲", credit_code=" credit-1 "),
                _company_row(name="同码乙", credit_code="CREDIT-1"),
                _company_row(name="无信用代码", setup_date="20210101", credit_code=None),
                _company_row(name=None, setup_date=None, credit_code=None),
            ],
        ),
    )

    assert result.rows_rejected == 0
    assert [row["identity_basis"] for row in result.rows_normalized] == [
        "credit_code",
        "credit_code",
        "name_setup",
        "content_hash_fallback",
    ]
    assert result.rows_normalized[0]["source_entity_key"] == result.rows_normalized[1]["source_entity_key"] == "credit:CREDIT-1"
    assert result.rows_normalized[2]["source_entity_key"].startswith("name_setup:")
    assert result.rows_normalized[3]["source_entity_key"].startswith("content:")


def test_mkt_idx_bmk_blank_ts_code_is_rejected_and_blocks_snapshot_write(mocker) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("mkt_idx_bmk")
    batch = DatasetNormalizer().normalize(
        definition=definition,
        fetch_result=SourceFetchResult(
            unit_id="benchmark",
            request_count=1,
            retry_count=0,
            latency_ms=0,
            rows_raw=[_benchmark_row(), _benchmark_row(ts_code="   ")],
        ),
    )

    assert batch.rows_rejected == 1
    assert batch.rejected_reasons == {"normalize.empty_not_allowed:ts_code": 1}
    with pytest.raises(IngestionWriteError, match="完整观察快照存在归一化拒绝行"):
        DatasetWriter(mocker.Mock()).write(definition=definition, batch=batch)


@pytest.fixture()
def company_db_session():  # type: ignore[no-untyped-def]
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    connection = engine.connect().execution_options(schema_translate_map={"core_serving": None})
    for table in (FundCompanyCurrent.__table__, FundCompanyObservation.__table__):
        table.create(connection)
    session = Session(connection, future=True)
    try:
        yield session
    finally:
        session.close()
        connection.close()
        engine.dispose()


def test_fund_company_writer_preserves_versions_and_replaces_current(company_db_session: Session, mocker) -> None:  # type: ignore[no-untyped-def]
    definition = get_dataset_definition("fund_company")
    dao_factory = SimpleNamespace(
        fund_company_current=ObservedSnapshotDAO(company_db_session, FundCompanyCurrent),
        fund_company_observation=ObservedSnapshotDAO(company_db_session, FundCompanyObservation),
    )
    mocker.patch("src.foundation.ingestion.writer.DAOFactory", return_value=dao_factory)
    writer = DatasetWriter(company_db_session)
    normalizer = DatasetNormalizer()

    first = normalizer.normalize(
        definition=definition,
        fetch_result=SourceFetchResult(
            unit_id="first",
            request_count=1,
            retry_count=0,
            latency_ms=0,
            rows_raw=[
                _company_row(name="同码甲", credit_code="CREDIT-1"),
                _company_row(name="同码乙", credit_code="CREDIT-1"),
            ],
        ),
    )
    mocker.patch("src.foundation.ingestion.writer.utc_now", return_value=datetime(2026, 8, 5, 1, tzinfo=timezone.utc))
    assert writer.write(definition=definition, batch=first).rows_written == 2
    company_db_session.commit()

    second = normalizer.normalize(
        definition=definition,
        fetch_result=SourceFetchResult(
            unit_id="second",
            request_count=1,
            retry_count=0,
            latency_ms=0,
            rows_raw=[
                _company_row(name="同码甲（更新）", credit_code="CREDIT-1"),
                _company_row(name="同码乙", credit_code="CREDIT-1"),
            ],
        ),
    )
    mocker.patch("src.foundation.ingestion.writer.utc_now", return_value=datetime(2026, 8, 5, 2, tzinfo=timezone.utc))
    assert writer.write(definition=definition, batch=second).rows_written == 2
    company_db_session.commit()

    assert len(company_db_session.scalars(select(FundCompanyCurrent)).all()) == 2
    assert len(company_db_session.scalars(select(FundCompanyObservation)).all()) == 3
    assert {row.name for row in company_db_session.scalars(select(FundCompanyCurrent)).all()} == {"同码甲（更新）", "同码乙"}


def test_public_fund_models_are_registered() -> None:
    table_model_registry.cache_clear()
    registry = table_model_registry()
    assert registry["core_serving.fund_company_current"] is FundCompanyCurrent
    assert registry["core_serving.fund_company_observation"] is FundCompanyObservation
    assert registry["core_serving.mkt_idx_bmk_current"] is MktIdxBmkCurrent
    assert registry["core_serving.mkt_idx_bmk_observation"] is MktIdxBmkObservation


def test_dao_factory_registers_the_existing_observed_snapshot_dao_for_all_b1_tables(mocker) -> None:  # type: ignore[no-untyped-def]
    factory = DAOFactory(mocker.Mock())

    assert isinstance(factory.fund_company_current, ObservedSnapshotDAO)
    assert factory.fund_company_current.model is FundCompanyCurrent
    assert isinstance(factory.fund_company_observation, ObservedSnapshotDAO)
    assert factory.fund_company_observation.model is FundCompanyObservation
    assert isinstance(factory.mkt_idx_bmk_current, ObservedSnapshotDAO)
    assert factory.mkt_idx_bmk_current.model is MktIdxBmkCurrent
    assert isinstance(factory.mkt_idx_bmk_observation, ObservedSnapshotDAO)
    assert factory.mkt_idx_bmk_observation.model is MktIdxBmkObservation
