from __future__ import annotations

import importlib.util
from io import StringIO
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import DateTime, Integer, SmallInteger

from src.foundation.models.all_models import EquityQfqNineTurnDaily
from src.foundation.models.base import Base


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic/versions/20260816_000137_drop_equity_qfq_nineturn_daily_close.py"
)


def test_equity_qfq_nineturn_daily_model_matches_frozen_serving_contract() -> None:
    table = EquityQfqNineTurnDaily.__table__

    assert table.schema == "core_serving"
    assert table is Base.metadata.tables["core_serving.equity_qfq_nineturn_daily"]
    assert [column.name for column in table.primary_key.columns] == [
        "ts_code",
        "trade_date",
    ]
    assert "close_qfq" not in table.columns
    assert isinstance(table.columns["up_count"].type, Integer)
    assert isinstance(table.columns["down_count"].type, Integer)
    assert isinstance(table.columns["formula_version"].type, SmallInteger)
    assert isinstance(table.columns["published_at"].type, DateTime)
    assert table.columns["published_at"].type.timezone is True
    assert table.columns["nine_up_turn"].nullable is True
    assert table.columns["nine_down_turn"].nullable is True
    assert {index.name for index in table.indexes} == {
        "idx_equity_qfq_nineturn_daily_trade_code"
    }
    assert {constraint.name for constraint in table.constraints} == {
        "pk_equity_qfq_nineturn_daily",
        "ck_equity_qfq_nineturn_daily_counts_non_negative",
        "ck_equity_qfq_nineturn_daily_single_direction",
        "ck_equity_qfq_nineturn_daily_up_signal_allowed",
        "ck_equity_qfq_nineturn_daily_down_signal_allowed",
        "ck_equity_qfq_nineturn_daily_up_signal_count",
        "ck_equity_qfq_nineturn_daily_down_signal_count",
        "ck_equity_qfq_nineturn_daily_single_signal",
        "ck_equity_qfq_nineturn_daily_formula_version",
    }


def test_equity_qfq_nineturn_daily_migration_chains_head_and_only_drops_price() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    uppercase = source.upper()

    assert 'revision = "20260816_000137"' in source
    assert 'down_revision = "20260814_000136"' in source
    assert "DROP_CONSTRAINT" in uppercase
    assert "DROP_COLUMN" in uppercase
    assert "CLOSE_QFQ" in uppercase
    for forbidden in (
        "CREATE_TABLE",
        "ADD_COLUMN",
        "INSERT",
        "DELETE FROM",
        "TRUNCATE",
    ):
        assert forbidden not in uppercase


def test_equity_qfq_nineturn_daily_migration_uses_frozen_constraint_name() -> None:
    spec = importlib.util.spec_from_file_location(
        "migration_20260816_000137",
        MIGRATION_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    with Operations.context(context):
        migration.upgrade()

    sql = output.getvalue()
    assert (
        "ALTER TABLE core_serving.equity_qfq_nineturn_daily "
        "DROP CONSTRAINT ck_equity_qfq_nineturn_daily_close_positive;"
    ) in sql
    assert "ck_equity_qfq_nineturn_daily_ck_equity_qfq_nineturn" not in sql
