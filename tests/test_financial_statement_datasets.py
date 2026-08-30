from __future__ import annotations

from datetime import date
from decimal import Decimal
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from sqlalchemy import Numeric

from src.foundation.dao.factory import DAOFactory
from src.foundation.dao.generic import GenericDAO
from src.foundation.datasets.balancesheet_contracts import (
    BALANCESHEET_DECIMAL_FIELDS,
    BALANCESHEET_SOURCE_FIELDS,
)
from src.foundation.datasets.cashflow_contracts import CASHFLOW_DECIMAL_FIELDS, CASHFLOW_SOURCE_FIELDS
from src.foundation.datasets.financial_statement_contracts import (
    FINANCIAL_STATEMENT_IDENTITY_FIELDS,
    FINANCIAL_STATEMENT_REPORT_TYPE_LABELS,
    FINANCIAL_STATEMENT_REPORT_TYPE_VALUES,
)
from src.foundation.datasets.freshness_policies import EVENT_RUN_TRACE, get_freshness_policy
from src.foundation.datasets.income_contracts import INCOME_DECIMAL_FIELDS, INCOME_SOURCE_FIELDS
from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion import DatasetActionRequest, DatasetActionResolver, DatasetTimeInput
from src.foundation.ingestion.errors import IngestionNormalizeError, IngestionValidationError
from src.foundation.ingestion.execution_plan import PlanUnitSnapshot
from src.foundation.ingestion.normalizer import DatasetNormalizer
from src.foundation.ingestion.source_client import DatasetSourceClient, SourceFetchResult
import src.foundation.ingestion.source_client as source_client_module
from src.foundation.ingestion.writer import DatasetWriter
from src.foundation.models.raw.raw_balancesheet import RawBalancesheet
from src.foundation.models.raw.raw_cashflow import RawCashflow
from src.foundation.models.raw.raw_income import RawIncome
from src.foundation.models.table_model_registry import get_model_by_table_name, table_model_registry
from src.ops.action_catalog import list_workflow_definitions
from src.ops.catalog.dataset_catalog_views import OPS_DATASET_DEFAULT_VIEW


ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_FINANCIAL_STATEMENT_IDENTITY_FIELDS = (
    "ts_code",
    "ann_date",
    "f_ann_date",
    "end_date",
    "report_type",
    "comp_type",
    "end_type",
    "update_flag",
)

CASES = (
    (
        "income",
        "income_vip",
        INCOME_SOURCE_FIELDS,
        INCOME_DECIMAL_FIELDS,
        RawIncome,
        "raw_income",
        "core_serving.equity_income",
        "20260830_000163",
        "20260830_000162",
        30,
    ),
    (
        "balancesheet",
        "balancesheet_vip",
        BALANCESHEET_SOURCE_FIELDS,
        BALANCESHEET_DECIMAL_FIELDS,
        RawBalancesheet,
        "raw_balancesheet",
        "core_serving.equity_balancesheet",
        "20260830_000164",
        "20260830_000163",
        40,
    ),
    (
        "cashflow",
        "cashflow_vip",
        CASHFLOW_SOURCE_FIELDS,
        CASHFLOW_DECIMAL_FIELDS,
        RawCashflow,
        "raw_cashflow",
        "core_serving.equity_cashflow",
        "20260830_000165",
        "20260830_000164",
        50,
    ),
)


def _row(source_fields: tuple[str, ...], decimal_fields: tuple[str, ...], **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "ts_code": "000001.SZ",
        "ann_date": "20260829",
        "f_ann_date": "20260830",
        "end_date": "20260630",
        "report_type": "1",
        "comp_type": "7",
        "end_type": "2",
        **{field_name: "1.25" for field_name in decimal_fields},
        "update_flag": "1",
    }
    row.update(overrides)
    assert set(row) == set(source_fields)
    return row


def _unit(dataset_key: str, unit_date: date, *, report_type: str = "1") -> PlanUnitSnapshot:
    return PlanUnitSnapshot(
        unit_id=f"{dataset_key}:{unit_date:%Y%m%d}:report_type={report_type}",
        dataset_key=dataset_key,
        source_key="tushare",
        trade_date=unit_date,
        request_params={"ann_date": unit_date.strftime("%Y%m%d"), "report_type": report_type},
        progress_context={"ann_date": unit_date.isoformat(), "report_type": report_type},
        pagination_policy="offset_limit",
        page_limit=5_000,
    )


def _resolver(dataset_key: str) -> DatasetActionResolver:
    class NoPoolSession:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"{dataset_key} planner must not read an object pool: {name}")

    return DatasetActionResolver(NoPoolSession())


@pytest.mark.parametrize(
    "dataset_key,api_name,source_fields,decimal_fields,model,dao_name,serving_table,revision,down_revision,item_order",
    CASES,
)
def test_financial_statement_definition_storage_and_ops_contract(
    dataset_key: str,
    api_name: str,
    source_fields: tuple[str, ...],
    decimal_fields: tuple[str, ...],
    model: type,
    dao_name: str,
    serving_table: str,
    revision: str,
    down_revision: str,
    item_order: int,
) -> None:
    del model, revision, down_revision
    definition = get_dataset_definition(dataset_key)
    report_type = definition.input_model.filters[0]
    capability = definition.capabilities.get_action("maintain")

    assert definition.source.api_name == api_name
    assert definition.source.source_fields == source_fields
    assert len(source_fields) == len(decimal_fields) + 8
    assert report_type.name == "report_type"
    assert report_type.required is True
    assert report_type.multi_value is True
    assert report_type.enum_values == FINANCIAL_STATEMENT_REPORT_TYPE_VALUES
    assert report_type.option_labels == FINANCIAL_STATEMENT_REPORT_TYPE_LABELS
    assert report_type.select_all_enabled is True
    assert definition.date_model.date_axis == "natural_day"
    assert definition.date_model.input_shape == "ann_date_or_start_end"
    assert definition.date_model.bucket_rule == "not_applicable"
    assert definition.date_model.audit_applicable is False
    assert definition.planning.universe_policy == "no_pool"
    assert definition.planning.enum_fanout_defaults["report_type"] == FINANCIAL_STATEMENT_REPORT_TYPE_VALUES
    assert definition.planning.pagination_policy == "offset_limit"
    assert definition.planning.page_limit == 5_000
    assert definition.storage.raw_dao_name == dao_name
    assert definition.storage.core_dao_name == dao_name
    assert definition.storage.target_table == f"raw_tushare.{dataset_key}"
    assert definition.storage.serving_table == serving_table
    assert definition.storage.write_path == "raw_only_upsert"
    assert definition.storage.conflict_columns == FINANCIAL_STATEMENT_IDENTITY_FIELDS
    assert definition.quality.batch_unique_key_fields == FINANCIAL_STATEMENT_IDENTITY_FIELDS
    assert definition.quality.empty_result_policy == "allow"
    assert definition.quality.reject_policy == "fail_unit_on_any_rejection"
    assert capability is not None and capability.schedule_time_policy is not None
    assert capability.schedule_time_policy.policy == "since_last_success_day_range"
    assert get_freshness_policy(dataset_key) == EVENT_RUN_TRACE

    item = next(item for item in OPS_DATASET_DEFAULT_VIEW.items if item.dataset_key == dataset_key)
    assert (item.group_key, item.item_order) == ("equity_financial", item_order)
    assert all(
        all(step.dataset_key != dataset_key for step in workflow.steps)
        for workflow in list_workflow_definitions()
    )


@pytest.mark.parametrize("dataset_key", ("income", "balancesheet", "cashflow"))
def test_financial_statement_planner_defaults_to_all_types_and_keeps_natural_days(dataset_key: str) -> None:
    resolver = _resolver(dataset_key)
    point = resolver.build_plan(
        DatasetActionRequest(
            dataset_key=dataset_key,
            action="maintain",
            time_input=DatasetTimeInput(mode="point", ann_date=date(2026, 8, 29)),
        )
    )
    ranged = resolver.build_plan(
        DatasetActionRequest(
            dataset_key=dataset_key,
            action="maintain",
            time_input=DatasetTimeInput(
                mode="range",
                start_date=date(2026, 8, 29),
                end_date=date(2026, 8, 31),
            ),
            filters={"report_type": ["6", "1"]},
        )
    )

    assert [unit.request_params for unit in point.units] == [
        {"ann_date": "20260829", "report_type": report_type}
        for report_type in FINANCIAL_STATEMENT_REPORT_TYPE_VALUES
    ]
    assert [unit.request_params for unit in ranged.units] == [
        {"ann_date": day, "report_type": report_type}
        for day in ("20260829", "20260830", "20260831")
        for report_type in ("1", "6")
    ]


@pytest.mark.parametrize("dataset_key", ("income", "balancesheet", "cashflow"))
@pytest.mark.parametrize("filters", ({"report_type": []}, {"report_type": ["ALL"]}, {"report_type": ["13"]}))
def test_financial_statement_rejects_empty_sentinel_and_invalid_report_types(
    dataset_key: str,
    filters: dict[str, object],
) -> None:
    with pytest.raises(IngestionValidationError):
        _resolver(dataset_key).build_plan(
            DatasetActionRequest(
                dataset_key=dataset_key,
                action="maintain",
                time_input=DatasetTimeInput(mode="point", ann_date=date(2026, 8, 29)),
                filters=filters,
            )
        )


@pytest.mark.parametrize(
    "dataset_key,api_name,source_fields,decimal_fields,model,dao_name,serving_table,revision,down_revision,item_order",
    CASES,
)
def test_financial_statement_source_pagination_and_empty_result(
    monkeypatch,
    dataset_key: str,
    api_name: str,
    source_fields: tuple[str, ...],
    decimal_fields: tuple[str, ...],
    model: type,
    dao_name: str,
    serving_table: str,
    revision: str,
    down_revision: str,
    item_order: int,
) -> None:
    del model, dao_name, serving_table, revision, down_revision, item_order
    calls: list[tuple[dict[str, object], tuple[str, ...]]] = []

    class Connector:
        def call(self, *, api_name: str, params: dict, fields: tuple[str, ...]) -> list[dict]:
            assert api_name == locals_api_name
            calls.append((dict(params), fields))
            offset = int(params["offset"])
            if offset == 0:
                return [
                    _row(source_fields, decimal_fields, ts_code=f"{index:06d}.SZ")
                    for index in range(5_000)
                ]
            return []

    locals_api_name = api_name
    monkeypatch.setattr(source_client_module, "create_source_connector", lambda _source_key: Connector())
    result = DatasetSourceClient().fetch(
        definition=get_dataset_definition(dataset_key),
        unit=_unit(dataset_key, date(2026, 8, 29)),
    )

    assert [params for params, _fields in calls] == [
        {"ann_date": "20260829", "report_type": "1", "limit": 5_000, "offset": 0},
        {"ann_date": "20260829", "report_type": "1", "limit": 5_000, "offset": 5_000},
    ]
    assert all(fields == source_fields for _params, fields in calls)
    assert len(result.rows_raw) == 5_000
    assert result.pagination_diagnostics["observed_short_page"] is True


@pytest.mark.parametrize(
    "dataset_key,api_name,source_fields,decimal_fields,model,dao_name,serving_table,revision,down_revision,item_order",
    CASES,
)
def test_financial_statement_normalizer_preserves_versions_and_rejects_identity_conflicts(
    dataset_key: str,
    api_name: str,
    source_fields: tuple[str, ...],
    decimal_fields: tuple[str, ...],
    model: type,
    dao_name: str,
    serving_table: str,
    revision: str,
    down_revision: str,
    item_order: int,
) -> None:
    del api_name, model, dao_name, serving_table, revision, down_revision, item_order
    definition = get_dataset_definition(dataset_key)

    def normalize(rows: list[dict[str, object]]):  # type: ignore[no-untyped-def]
        return DatasetNormalizer().normalize(
            definition=definition,
            fetch_result=SourceFetchResult(
                unit_id=dataset_key,
                request_count=1,
                retry_count=0,
                latency_ms=0,
                rows_raw=rows,
            ),
            expected_unit_date=date(2026, 8, 29),
        )

    batch = normalize(
        [
            _row(
                source_fields,
                decimal_fields,
                ts_code="\x00 000001.sz ",
                end_type=None,
                update_flag="0",
            ),
            _row(source_fields, decimal_fields, update_flag="1"),
        ]
    )
    assert len(batch.rows_normalized) == 2
    assert batch.rows_normalized[0]["ts_code"] == "000001.SZ"
    assert batch.rows_normalized[0]["comp_type"] == "7"
    assert batch.rows_normalized[0]["end_type"] is None
    assert all(isinstance(batch.rows_normalized[0][field], Decimal) for field in decimal_fields)
    assert {row["update_flag"] for row in batch.rows_normalized} == {"0", "1"}
    assert all(len(str(row["source_content_hash"])) == 64 for row in batch.rows_normalized)

    exact = normalize([_row(source_fields, decimal_fields), _row(source_fields, decimal_fields)])
    assert len(exact.rows_normalized) == 1
    first_decimal = decimal_fields[0]
    with pytest.raises(IngestionNormalizeError) as conflict:
        normalize(
            [
                _row(source_fields, decimal_fields),
                _row(source_fields, decimal_fields, **{first_decimal: "9.99"}),
            ]
        )
    assert conflict.value.structured_error.error_code == "normalize.batch_unique_key_conflicting"


class _StubRawDao:
    def __init__(self, model: type) -> None:
        self.model = model
        self.calls: list[tuple[list[dict], list[str]]] = []

    def bulk_upsert(self, rows: list[dict], conflict_columns=None):  # type: ignore[no-untyped-def]
        self.calls.append((rows, list(conflict_columns or [])))
        return len(rows)


@pytest.mark.parametrize(
    "dataset_key,api_name,source_fields,decimal_fields,model,dao_name,serving_table,revision,down_revision,item_order",
    CASES,
)
def test_financial_statement_writer_model_dao_and_migration_contract(
    mocker,
    monkeypatch,
    dataset_key: str,
    api_name: str,
    source_fields: tuple[str, ...],
    decimal_fields: tuple[str, ...],
    model: type,
    dao_name: str,
    serving_table: str,
    revision: str,
    down_revision: str,
    item_order: int,
) -> None:
    del serving_table, item_order
    definition = get_dataset_definition(dataset_key)
    raw_dao = _StubRawDao(model)
    mocker.patch(
        "src.foundation.ingestion.writer.DAOFactory",
        return_value=SimpleNamespace(**{dao_name: raw_dao}),
    )
    batch = DatasetNormalizer().normalize(
        definition=definition,
        fetch_result=SourceFetchResult(
            unit_id=dataset_key,
            request_count=1,
            retry_count=0,
            latency_ms=0,
            rows_raw=[_row(source_fields, decimal_fields)],
        ),
        expected_unit_date=date(2026, 8, 29),
    )
    result = DatasetWriter(session=mocker.Mock()).write(
        definition=definition,
        batch=batch,
        plan_unit=_unit(dataset_key, date(2026, 8, 29)),
    )
    assert raw_dao.calls == [(batch.rows_normalized, list(FINANCIAL_STATEMENT_IDENTITY_FIELDS))]
    assert result.target_table == f"raw_tushare.{dataset_key}"

    table_model_registry.cache_clear()
    assert get_model_by_table_name(f"raw_tushare.{dataset_key}") is model
    assert set(model.__table__.columns.keys()) == {
        *source_fields,
        "source_content_hash",
        "api_name",
        "fetched_at",
    }
    assert list(model.__table__.primary_key.columns.keys()) == list(FINANCIAL_STATEMENT_IDENTITY_FIELDS)
    assert model.__table__.columns.end_type.nullable is True
    assert all(isinstance(model.__table__.columns[field].type, Numeric) for field in decimal_fields)
    factory = DAOFactory(SimpleNamespace())
    dao = getattr(factory, dao_name)
    assert isinstance(dao, GenericDAO)
    assert dao.model is model

    migration_path = ROOT / f"alembic/versions/{revision}_add_{dataset_key}_dataset.py"
    migration = _load_migration(migration_path, dataset_key)
    assert migration.revision == revision
    assert migration.down_revision == down_revision
    assert migration._ORIGINAL_IDENTITY_FIELDS == ORIGINAL_FINANCIAL_STATEMENT_IDENTITY_FIELDS
    migration_text = migration_path.read_text(encoding="utf-8")
    assert migration_text.index("_assert_hdd_tablespace()") < migration_text.index(
        'op.execute("CREATE SCHEMA IF NOT EXISTS raw_tushare")'
    )
    assert "postgresql_tablespace=_TABLESPACE" in migration_text
    assert migration_text.count("TABLESPACE gs_raw_cold_hdd") >= 3
    assert "WHERE report_type = '1'" in migration_text
    assert "CASE update_flag WHEN '1' THEN 0 ELSE 1 END" in migration_text
    assert "SELECT *" not in migration_text
    assert "op.drop_table" not in migration_text

    class MissingTablespaceResult:
        @staticmethod
        def scalar() -> None:
            return None

    class MissingTablespaceBind:
        dialect = SimpleNamespace(name="postgresql")

        @staticmethod
        def execute(*_args, **_kwargs):  # type: ignore[no-untyped-def]
            return MissingTablespaceResult()

    relation_calls: list[str] = []
    monkeypatch.setattr(migration.op, "get_bind", lambda: MissingTablespaceBind())
    monkeypatch.setattr(migration.op, "execute", lambda *_args, **_kwargs: relation_calls.append("execute"))
    monkeypatch.setattr(migration.op, "create_table", lambda *_args, **_kwargs: relation_calls.append("table"))
    with pytest.raises(RuntimeError, match="禁止回退到默认 SSD"):
        migration.upgrade()
    assert relation_calls == []
    with pytest.raises(RuntimeError, match="不支持自动 downgrade"):
        migration.downgrade()


def test_financial_statement_nullable_end_type_migration_contract(monkeypatch) -> None:
    migration_path = (
        ROOT / "alembic/versions/20260830_000166_allow_financial_statement_end_type_null.py"
    )
    migration = _load_migration(migration_path, "financial_statement_nullable_end_type")
    migration_text = migration_path.read_text(encoding="utf-8")

    assert migration.revision == "20260830_000166"
    assert migration.down_revision == "20260830_000165"
    assert migration._IDENTITY_FIELDS == FINANCIAL_STATEMENT_IDENTITY_FIELDS
    assert migration._TABLES == ("income", "balancesheet", "cashflow")
    assert "ALTER COLUMN end_type DROP NOT NULL" in migration_text
    assert "PRIMARY KEY USING INDEX" in migration_text
    assert "TABLESPACE {_TABLESPACE}" in migration_text
    assert "op.drop_table" not in migration_text

    class ScalarResult:
        def __init__(self, value: object) -> None:
            self.value = value

        def scalar(self) -> object:
            return self.value

    class ConflictBind:
        dialect = SimpleNamespace(name="postgresql")

        @staticmethod
        def execute(statement, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            sql = str(statement)
            if "pg_tablespace" in sql or "to_regclass" in sql:
                return ScalarResult(1)
            if "HAVING count(*) > 1" in sql:
                return ScalarResult(1)
            raise AssertionError(f"unexpected migration query: {sql}")

    ddl_calls: list[str] = []
    monkeypatch.setattr(migration.op, "get_bind", lambda: ConflictBind())
    monkeypatch.setattr(migration.op, "execute", lambda statement: ddl_calls.append(str(statement)))
    with pytest.raises(RuntimeError, match="七字段身份冲突"):
        migration.upgrade()
    assert ddl_calls == []

    with pytest.raises(RuntimeError, match="不支持自动 downgrade"):
        migration.downgrade()


def _load_migration(path: Path, dataset_key: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"{dataset_key}_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
