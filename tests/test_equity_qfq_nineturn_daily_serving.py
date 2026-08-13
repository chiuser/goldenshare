from __future__ import annotations

from pathlib import Path

from sqlalchemy import DateTime, Float, Integer, SmallInteger

from src.foundation.models.all_models import EquityQfqNineTurnDaily
from src.foundation.models.base import Base


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic/versions/20260813_000135_add_equity_qfq_nineturn_daily_serving.py"
)


def test_equity_qfq_nineturn_daily_model_matches_frozen_serving_contract() -> None:
    table = EquityQfqNineTurnDaily.__table__

    assert table.schema == "core_serving"
    assert table is Base.metadata.tables["core_serving.equity_qfq_nineturn_daily"]
    assert [column.name for column in table.primary_key.columns] == [
        "ts_code",
        "trade_date",
    ]
    assert isinstance(table.columns["close_qfq"].type, Float)
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
        "ck_equity_qfq_nineturn_daily_close_positive",
        "ck_equity_qfq_nineturn_daily_counts_non_negative",
        "ck_equity_qfq_nineturn_daily_single_direction",
        "ck_equity_qfq_nineturn_daily_up_signal_allowed",
        "ck_equity_qfq_nineturn_daily_down_signal_allowed",
        "ck_equity_qfq_nineturn_daily_up_signal_count",
        "ck_equity_qfq_nineturn_daily_down_signal_count",
        "ck_equity_qfq_nineturn_daily_single_signal",
        "ck_equity_qfq_nineturn_daily_formula_version",
    }


def test_equity_qfq_nineturn_daily_migration_chains_head_and_grants_only_required_dml() -> None:
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    uppercase = source.upper()

    assert 'revision = "20260813_000135"' in source
    assert 'down_revision = "20260813_000134"' in source
    assert "CORE_SERVING.EQUITY_QFQ_NINETURN_DAILY TO LAKE_RAW_WRITER" in uppercase
    assert "GRANT SELECT, INSERT, DELETE ON TABLE" in uppercase
    for forbidden in (
        "CREATE ROLE",
        "CREATE USER",
        "ALTER ROLE",
        "GRANT UPDATE",
        "TRUNCATE",
    ):
        assert forbidden not in uppercase
