from __future__ import annotations

from datetime import date
import importlib.util
from io import StringIO
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
from sqlalchemy.dialects import postgresql

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion import (
    DatasetActionRequest,
    DatasetActionResolver,
    DatasetTimeInput,
)
from src.foundation.ingestion.errors import IngestionValidationError
from src.foundation.models.core.equity_margin import EquityMargin
from src.foundation.models.raw.raw_margin import RawMargin
from src.foundation.serving.targets import get_target_dao_attr


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = REPO_ROOT / "alembic/versions/20260826_000152_make_margin_raw_view.py"
SOURCE_FIELDS = (
    "trade_date",
    "exchange_id",
    "rzye",
    "rzmre",
    "rzche",
    "rqye",
    "rqmcl",
    "rzrqye",
    "rqyl",
)


def _load_migration():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(
        "migration_20260826_000152", MIGRATION_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _postgresql_type(column) -> str:  # type: ignore[no-untyped-def]
    return str(column.type.compile(dialect=postgresql.dialect()))


def test_margin_definition_changes_only_storage_delivery_contract(
    mocker,
) -> None:
    definition = get_dataset_definition("margin")

    assert definition.source.api_name == "margin"
    assert definition.source.source_fields == SOURCE_FIELDS
    assert definition.source.request_builder_key == "_margin_params"
    assert definition.source.base_params == {}
    assert definition.date_model.date_axis == "trade_open_day"
    assert definition.date_model.bucket_rule == "every_open_day"
    assert definition.date_model.window_mode == "point_or_range"
    assert definition.date_model.input_shape == "trade_date_or_start_end"
    assert definition.date_model.observed_field == "trade_date"
    assert definition.date_model.audit_applicable is True
    assert tuple(field.name for field in definition.input_model.time_fields) == (
        "trade_date",
        "start_date",
        "end_date",
    )
    assert tuple(field.name for field in definition.input_model.filters) == (
        "exchange_id",
    )
    assert definition.input_model.filters[0].enum_values == ("SSE", "SZSE", "BSE")
    assert definition.input_model.filters[0].multi_value is True
    assert definition.planning.universe_policy == "no_pool"
    assert definition.planning.enum_fanout_fields == ("exchange_id",)
    assert definition.planning.enum_fanout_defaults == {
        "exchange_id": ("SSE", "SZSE", "BSE")
    }
    assert definition.planning.pagination_policy == "offset_limit"
    assert definition.planning.page_limit == 4000
    assert definition.planning.max_units_per_execution is None
    assert definition.planning.unit_builder_key == "generic"
    assert definition.capabilities.actions[0].action == "maintain"
    assert definition.capabilities.actions[0].manual_enabled is True
    assert definition.capabilities.actions[0].schedule_enabled is True
    assert definition.capabilities.actions[0].retry_enabled is True
    assert definition.capabilities.actions[0].supported_time_modes == ("point", "range")

    assert definition.storage.raw_dao_name == "raw_margin"
    assert definition.storage.core_dao_name == "raw_margin"
    assert definition.storage.target_table == "raw_tushare.margin"
    assert definition.storage.raw_table == "raw_tushare.margin"
    assert definition.storage.serving_table == "core_serving.equity_margin"
    assert definition.storage.delivery_mode == "raw_with_serving_view"
    assert definition.storage.layer_plan == "raw->serving_view"
    assert definition.storage.write_path == "raw_only_upsert"
    assert definition.storage.conflict_columns is None

    plan = DatasetActionResolver(mocker.Mock()).build_plan(
        DatasetActionRequest(
            dataset_key="margin",
            action="maintain",
            time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 8, 22)),
        )
    )
    assert plan.source.fields == SOURCE_FIELDS
    assert plan.planning.unit_count == 3
    assert plan.planning.pagination_policy == "offset_limit"
    assert plan.writing.raw_dao_name == "raw_margin"
    assert plan.writing.core_dao_name == "raw_margin"
    assert plan.writing.target_table == "raw_tushare.margin"
    assert plan.writing.write_path == "raw_only_upsert"
    assert [unit.request_params for unit in plan.units] == [
        {"trade_date": "20260822", "exchange_id": "BSE"},
        {"trade_date": "20260822", "exchange_id": "SSE"},
        {"trade_date": "20260822", "exchange_id": "SZSE"},
    ]
    assert all(unit.pagination_policy == "offset_limit" for unit in plan.units)
    assert all(unit.page_limit == 4000 for unit in plan.units)


def test_margin_preserves_exchange_fanout_filter_and_rejects_new_filters(
    mocker,
) -> None:
    plan = DatasetActionResolver(mocker.Mock()).build_plan(
        DatasetActionRequest(
            dataset_key="margin",
            action="maintain",
            time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 8, 22)),
            filters={"exchange_id": ["SSE"]},
        )
    )
    assert plan.planning.unit_count == 1
    assert plan.units[0].request_params == {
        "trade_date": "20260822",
        "exchange_id": "SSE",
    }

    with pytest.raises(IngestionValidationError, match="存在未定义参数：ts_code"):
        DatasetActionResolver(mocker.Mock()).build_plan(
            DatasetActionRequest(
                dataset_key="margin",
                action="maintain",
                time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 8, 22)),
                filters={"ts_code": "000001.SZ"},
            )
        )


def test_margin_raw_model_covers_serving_business_contract_and_index() -> None:
    raw_table = RawMargin.__table__
    serving_table = EquityMargin.__table__

    assert raw_table.schema == "raw_tushare"
    assert serving_table.schema == "core_serving"
    assert tuple(raw_table.columns.keys()) == SOURCE_FIELDS + (
        "api_name",
        "fetched_at",
        "raw_payload",
    )
    assert tuple(serving_table.columns.keys()) == SOURCE_FIELDS + (
        "created_at",
        "updated_at",
    )
    assert tuple(raw_table.primary_key.columns.keys()) == ("trade_date", "exchange_id")
    assert tuple(serving_table.primary_key.columns.keys()) == (
        "trade_date",
        "exchange_id",
    )

    for field_name in SOURCE_FIELDS:
        raw_column = raw_table.columns[field_name]
        serving_column = serving_table.columns[field_name]
        assert _postgresql_type(raw_column) == _postgresql_type(serving_column)
        assert raw_column.nullable == serving_column.nullable

    assert {index.name: tuple(index.columns.keys()) for index in raw_table.indexes} == {
        "idx_raw_tushare_margin_trade_date": ("trade_date",),
        "idx_raw_tushare_margin_exchange_trade_date": ("exchange_id", "trade_date"),
    }
    assert {
        index.name: tuple(index.columns.keys()) for index in serving_table.indexes
    } == {
        "idx_equity_margin_trade_date": ("trade_date",),
        "idx_equity_margin_exchange_trade_date": ("exchange_id", "trade_date"),
    }


def test_margin_is_not_registered_for_serving_publish_bypass() -> None:
    assert get_target_dao_attr("margin") is None


def test_margin_migration_is_independent_atomic_and_fail_closed() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    uppercase = source.upper()

    assert 'revision = "20260826_000152"' in source
    assert 'down_revision = "20260825_000151"' in source
    assert "SET LOCAL lock_timeout = '15s'" in source
    assert "SET LOCAL statement_timeout = '120s'" in source
    assert "SET LOCAL work_mem = '16MB'" in source
    assert "SET LOCAL temp_file_limit" not in source
    assert "max_relation_rows constant bigint := 5000" in source
    assert "relation size exceeds migration safety cap" in source
    assert "SELECT pg_catalog.count(*) INTO raw_row_count" in source
    assert "SELECT pg_catalog.count(*) INTO serving_row_count" in source
    assert "raw_tushare.margin must remain on SSD pg_default" in source
    assert "idx_raw_tushare_margin_trade_date" in source
    assert "idx_raw_tushare_margin_exchange_trade_date" in source
    assert "idx_equity_margin_trade_date" in source
    assert "idx_equity_margin_exchange_trade_date" in source
    assert source.count("AND NOT index_row.indisunique") == 4
    assert source.count("AND index_row.indexprs IS NULL") == 4
    assert "Unexpected column-level ACL" in source
    assert "constraint_row.contype NOT IN ('p', 'n')" in source
    assert "constraint_row.contype <> 'p'" not in source
    assert "Unexpected function dependency" in source
    assert "Unexpected logical-publication contract" in source
    assert "Unexpected rewrite rule" in source
    assert "Unexpected extended statistics" in source
    assert "Unexpected security label" in source
    assert "LOCK TABLE raw_tushare.margin IN SHARE MODE" in source
    assert "LOCK TABLE core_serving.equity_margin IN SHARE MODE" in source
    assert "LOCK TABLE core_serving.equity_margin IN ACCESS EXCLUSIVE MODE" in source
    assert uppercase.count("EXCEPT ALL") == 2
    assert "DROP TABLE core_serving.equity_margin" in source
    assert "DROP TABLE core_serving.equity_margin CASCADE" not in source
    assert "DROP TABLE raw_tushare.margin" not in source
    assert "CREATE VIEW core_serving.equity_margin AS" in source
    assert "SELECT *" not in uppercase
    assert "fetched_at AS created_at" in source
    assert "fetched_at AS updated_at" in source
    assert "reject_raw_direct_serving_view_dml" in source
    assert "INSTEAD OF INSERT OR UPDATE OR DELETE" in source
    assert "_VERIFY_EXISTING_REJECT_FUNCTION" in source
    assert "Required DML rejection function contract is missing or invalid" in source
    assert (
        "CREATE FUNCTION core_serving.reject_raw_direct_serving_view_dml" not in source
    )
    assert "Failed to restore serving metadata" in source
    assert "automatic downgrade is forbidden" in source

    raw_lock_at = source.index("LOCK TABLE raw_tushare.margin IN SHARE MODE")
    serving_lock_at = source.index(
        "LOCK TABLE core_serving.equity_margin IN SHARE MODE"
    )
    equality_at = source.index("EXCEPT ALL")
    exclusive_lock_at = source.index(
        "LOCK TABLE core_serving.equity_margin IN ACCESS EXCLUSIVE MODE"
    )
    drop_at = source.index("DROP TABLE core_serving.equity_margin")
    create_view_at = source.index("CREATE VIEW core_serving.equity_margin AS")
    assert (
        raw_lock_at
        < serving_lock_at
        < equality_at
        < exclusive_lock_at
        < drop_at
        < create_view_at
    )


def test_margin_migration_renders_complete_postgresql_sql() -> None:
    migration = _load_migration()
    for sql_name in (
        "_SET_BOUNDED_SESSION_LIMITS",
        "_PREFLIGHT_RELATIONS",
        "_LOCK_SOURCE_RELATIONS",
        "_PREFLIGHT_CONTRACT",
        "_VERIFY_DATA_EQUIVALENCE",
        "_VERIFY_EXISTING_REJECT_FUNCTION",
        "_LOCK_SERVING_FOR_SWITCH",
        "_SWITCH_RELATION",
        "_VERIFY_VIEW_CONTRACT",
    ):
        sql_value = getattr(migration, sql_name)
        statements = (sql_value,) if isinstance(sql_value, str) else sql_value
        assert statements
        for sql in statements:
            assert isinstance(sql, str)
            assert sql.strip()
            assert not sql.lstrip().startswith("_")

    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    with Operations.context(context):
        migration.upgrade()

    sql = output.getvalue()
    assert "CREATE VIEW core_serving.equity_margin AS" in sql
    assert "CREATE TRIGGER trg_equity_margin_reject_dml" in sql
    assert "rzye|numeric(20,4)|NULL" in sql
    assert "api_name|character varying(32)|NOT NULL" in sql
    assert "created_at|timestamp with time zone|NOT NULL" in sql
    assert "numeric(20,4)NULL" not in sql
    assert "character varying(32)NULL NULL" not in sql
    assert "DROP TABLE core_serving.equity_margin CASCADE" not in sql
    assert "DROP TABLE raw_tushare.margin" not in sql


def test_margin_migration_forbids_automatic_downgrade() -> None:
    with pytest.raises(RuntimeError, match="automatic downgrade is forbidden"):
        _load_migration().downgrade()
