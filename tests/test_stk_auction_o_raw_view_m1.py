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
from src.foundation.models.core_serving.equity_auction_open import EquityAuctionOpen
from src.foundation.models.raw.raw_stk_auction_o import RawStkAuctionO
from src.foundation.serving.targets import get_target_dao_attr


REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    REPO_ROOT / "alembic/versions/20260828_000156_make_stk_auction_o_raw_view.py"
)
SOURCE_FIELDS = (
    "ts_code",
    "trade_date",
    "close",
    "open",
    "high",
    "low",
    "vol",
    "amount",
    "vwap",
)


def _load_migration():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location(
        "migration_20260828_000156", MIGRATION_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _postgresql_type(column) -> str:  # type: ignore[no-untyped-def]
    return str(column.type.compile(dialect=postgresql.dialect()))


def test_stk_auction_o_definition_changes_only_storage_delivery_contract(
    mocker,
) -> None:
    definition = get_dataset_definition("stk_auction_o")

    assert definition.source.api_name == "stk_auction_o"
    assert definition.source.source_fields == SOURCE_FIELDS
    assert definition.source.request_builder_key == "_stk_auction_o_params"
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
    assert tuple(field.name for field in definition.input_model.filters) == ("ts_code",)
    assert definition.planning.universe_policy == "no_pool"
    assert definition.planning.enum_fanout_fields == ()
    assert definition.planning.pagination_policy == "offset_limit"
    assert definition.planning.page_limit == 10000
    assert definition.planning.max_units_per_execution is None
    assert definition.planning.unit_builder_key == "generic"
    assert definition.capabilities.actions[0].action == "maintain"
    assert definition.capabilities.actions[0].manual_enabled is True
    assert definition.capabilities.actions[0].schedule_enabled is True
    assert definition.capabilities.actions[0].retry_enabled is True
    assert definition.capabilities.actions[0].supported_time_modes == (
        "point",
        "range",
    )

    assert definition.storage.raw_dao_name == "raw_stk_auction_o"
    assert definition.storage.core_dao_name == "raw_stk_auction_o"
    assert definition.storage.target_table == "raw_tushare.stk_auction_o"
    assert definition.storage.raw_table == "raw_tushare.stk_auction_o"
    assert definition.storage.serving_table == "core_serving.equity_auction_open"
    assert definition.storage.delivery_mode == "raw_with_serving_view"
    assert definition.storage.layer_plan == "raw->serving_view"
    assert definition.storage.write_path == "raw_only_upsert"
    assert definition.storage.conflict_columns is None

    plan = DatasetActionResolver(mocker.Mock()).build_plan(
        DatasetActionRequest(
            dataset_key="stk_auction_o",
            action="maintain",
            time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 8, 27)),
        )
    )
    assert plan.source.fields == SOURCE_FIELDS
    assert plan.planning.unit_count == 1
    assert plan.planning.pagination_policy == "offset_limit"
    assert plan.writing.raw_dao_name == "raw_stk_auction_o"
    assert plan.writing.core_dao_name == "raw_stk_auction_o"
    assert plan.writing.target_table == "raw_tushare.stk_auction_o"
    assert plan.writing.write_path == "raw_only_upsert"
    assert plan.units[0].request_params == {"trade_date": "20260827"}
    assert plan.units[0].pagination_policy == "offset_limit"
    assert plan.units[0].page_limit == 10000


def test_stk_auction_o_preserves_ts_code_filter_and_rejects_unknown_filter(
    mocker,
) -> None:
    plan = DatasetActionResolver(mocker.Mock()).build_plan(
        DatasetActionRequest(
            dataset_key="stk_auction_o",
            action="maintain",
            time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 8, 27)),
            filters={"ts_code": " 000001.sz "},
        )
    )
    assert plan.planning.unit_count == 1
    assert plan.units[0].request_params == {
        "trade_date": "20260827",
        "ts_code": "000001.SZ",
    }

    with pytest.raises(IngestionValidationError, match="存在未定义参数：category"):
        DatasetActionResolver(mocker.Mock()).build_plan(
            DatasetActionRequest(
                dataset_key="stk_auction_o",
                action="maintain",
                time_input=DatasetTimeInput(mode="point", trade_date=date(2026, 8, 27)),
                filters={"category": "概念板块"},
            )
        )


def test_stk_auction_o_models_have_identical_business_contract_and_one_date_index() -> (
    None
):
    raw_table = RawStkAuctionO.__table__
    serving_table = EquityAuctionOpen.__table__

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
    assert tuple(raw_table.primary_key.columns.keys()) == ("ts_code", "trade_date")
    assert tuple(serving_table.primary_key.columns.keys()) == (
        "ts_code",
        "trade_date",
    )

    for field_name in SOURCE_FIELDS:
        raw_column = raw_table.columns[field_name]
        serving_column = serving_table.columns[field_name]
        assert _postgresql_type(raw_column) == _postgresql_type(serving_column)
        assert raw_column.nullable == serving_column.nullable

    assert {index.name: tuple(index.columns.keys()) for index in raw_table.indexes} == {
        "idx_raw_tushare_stk_auction_o_trade_date": ("trade_date",),
    }
    assert {
        index.name: tuple(index.columns.keys()) for index in serving_table.indexes
    } == {
        "idx_equity_auction_open_trade_date": ("trade_date",),
    }


def test_stk_auction_o_is_not_registered_for_serving_publish_bypass() -> None:
    assert get_target_dao_attr("stk_auction_o") is None


def test_stk_auction_o_migration_is_independent_atomic_and_fail_closed() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    uppercase = source.upper()

    assert 'revision = "20260828_000156"' in source
    assert 'down_revision = "20260828_000155"' in source
    assert "SET LOCAL lock_timeout = '15s'" in source
    assert "SET LOCAL statement_timeout = '120s'" in source
    assert "SET LOCAL work_mem = '16MB'" in source
    assert "SET LOCAL temp_file_limit" not in source
    assert "max_rows_per_month constant bigint := 160000" in source
    assert "monthly reconciliation exceeds safety cap" in source
    assert "date_trunc('month', raw_min_date)" in source
    assert "WHILE window_start <= raw_max_date LOOP" in source
    assert "count(DISTINCT (ts_code, trade_date))" in source
    assert source.count("pg_catalog.unnest(constraint_row.conkey)") == 2
    assert "raw_tushare.stk_auction_o must remain on SSD pg_default" in source
    assert "idx_raw_tushare_stk_auction_o_trade_date" in source
    assert "idx_equity_auction_open_trade_date" in source
    assert source.count("AND NOT index_row.indisunique") == 2
    assert source.count("AND index_row.indexprs IS NULL") == 2
    assert "Unexpected column-level ACL" in source
    assert (
        "Unexpected non-primary-key constraint on raw_tushare.stk_auction_o" in source
    )
    assert "constraint_row.contype NOT IN ('p', 'n')" in source
    assert "Unexpected function dependency" in source
    assert "Unexpected logical-publication contract" in source
    assert "Unexpected rewrite rule" in source
    assert "Unexpected extended statistics" in source
    assert "Unexpected security label" in source
    assert "LOCK TABLE raw_tushare.stk_auction_o IN SHARE MODE" in source
    assert "LOCK TABLE core_serving.equity_auction_open IN SHARE MODE" in source
    assert (
        "LOCK TABLE core_serving.equity_auction_open IN ACCESS EXCLUSIVE MODE" in source
    )
    assert uppercase.count("EXCEPT ALL") == 2
    assert "DROP TABLE core_serving.equity_auction_open" in source
    assert "DROP TABLE core_serving.equity_auction_open CASCADE" not in source
    assert "DROP TABLE raw_tushare.stk_auction_o" not in source
    assert "CREATE VIEW core_serving.equity_auction_open AS" in source
    assert "SELECT *" not in uppercase
    assert "fetched_at AS created_at" in source
    assert "fetched_at AS updated_at" in source
    assert "reject_raw_direct_serving_view_dml" in source
    assert "Required DML rejection function contract is missing or invalid" in source
    assert (
        "CREATE FUNCTION core_serving.reject_raw_direct_serving_view_dml" not in source
    )
    assert "INSTEAD OF INSERT OR UPDATE OR DELETE" in source
    assert "Failed to restore serving metadata" in source
    assert "automatic downgrade is forbidden" in source
    assert "dc_daily" not in source
    assert "category" not in source
    assert "CREATE INDEX" not in uppercase
    assert "ALTER TABLE raw_tushare.stk_auction_o" not in source
    assert "INSERT INTO raw_tushare.stk_auction_o" not in source
    assert "UPDATE raw_tushare.stk_auction_o" not in source
    assert "DELETE FROM raw_tushare.stk_auction_o" not in source

    raw_lock_at = source.index("LOCK TABLE raw_tushare.stk_auction_o IN SHARE MODE")
    serving_lock_at = source.index(
        "LOCK TABLE core_serving.equity_auction_open IN SHARE MODE"
    )
    equality_at = source.index("EXCEPT ALL")
    exclusive_lock_at = source.index(
        "LOCK TABLE core_serving.equity_auction_open IN ACCESS EXCLUSIVE MODE"
    )
    drop_at = source.index("DROP TABLE core_serving.equity_auction_open")
    create_view_at = source.index("CREATE VIEW core_serving.equity_auction_open AS")
    assert (
        raw_lock_at
        < serving_lock_at
        < equality_at
        < exclusive_lock_at
        < drop_at
        < create_view_at
    )


def test_stk_auction_o_migration_renders_complete_postgresql_sql() -> None:
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
    assert "CREATE VIEW core_serving.equity_auction_open AS" in sql
    assert "CREATE TRIGGER trg_equity_auction_open_reject_dml" in sql
    assert "ts_code|character varying(16)|NOT NULL" in sql
    assert "trade_date|date|NOT NULL" in sql
    assert "close|numeric(18,4)|NULL" in sql
    assert "vol|numeric(20,4)|NULL" in sql
    assert "vwap|numeric(18,4)|NULL" in sql
    assert "api_name|character varying(32)|NOT NULL" in sql
    assert "created_at|timestamp with time zone|NOT NULL" in sql
    assert "numeric(18,4)NULL" not in sql
    assert "DROP TABLE core_serving.equity_auction_open CASCADE" not in sql
    assert "DROP TABLE raw_tushare.stk_auction_o" not in sql


def test_stk_auction_o_migration_forbids_automatic_downgrade() -> None:
    with pytest.raises(RuntimeError, match="automatic downgrade is forbidden"):
        _load_migration().downgrade()
