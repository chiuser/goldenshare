from __future__ import annotations

from datetime import date
from pathlib import Path
import runpy

from sqlalchemy import BigInteger, DateTime, Float, String

from src.foundation.dao.factory import DAOFactory
from src.foundation.models.base import Base
from src.foundation.models.raw.raw_etf_minute_bar import RawEtfMinuteBar


MIGRATION_PATH = "alembic/versions/20260825_000151_add_etf_minute_bar.py"


def test_etf_minute_bar_model_matches_frozen_raw_contract(mocker) -> None:
    table = RawEtfMinuteBar.__table__
    assert table is Base.metadata.tables["raw_tushare.etf_minute_bar"]
    assert table.schema == "raw_tushare"
    assert tuple(column.name for column in table.primary_key.columns) == (
        "ts_code",
        "freq",
        "trade_time",
    )
    assert isinstance(table.c.ts_code.type, String) and table.c.ts_code.type.length == 16
    assert isinstance(table.c.freq.type, String) and table.c.freq.type.length == 8
    assert isinstance(table.c.trade_time.type, DateTime) and table.c.trade_time.type.timezone is False
    assert isinstance(table.c.vol.type, BigInteger)
    for field_name in ("open", "close", "high", "low", "amount", "vwap"):
        assert isinstance(table.c[field_name].type, Float)
        assert table.c[field_name].type.precision == 53

    factory = DAOFactory(mocker.Mock())
    assert factory.raw_etf_minute_bar.model is RawEtfMinuteBar


def test_etf_minute_bar_migration_uses_real_head_and_hdd_month_partitions() -> None:
    namespace = runpy.run_path(MIGRATION_PATH)
    source = Path(MIGRATION_PATH).read_text(encoding="utf-8")

    assert namespace["revision"] == "20260825_000151"
    assert namespace["down_revision"] == "20260824_000150"
    months = namespace["_partition_months"]()
    assert len(months) == 29 * 12
    assert months[0] == date(2009, 1, 1)
    assert months[-1] == date(2037, 12, 1)
    assert "PARTITION BY RANGE (trade_time)" in source
    assert "PARTITION OF {_SCHEMA}.{_TABLE} DEFAULT" in source
    assert "TABLESPACE {_TABLESPACE}" in source
    assert "PRIMARY KEY (ts_code, freq, trade_time)" in source
    assert "(freq, trade_time DESC, ts_code)" in source
    assert "SELECT 1 FROM pg_tablespace" in source
    assert "已有业务数据，禁止自动 downgrade 删除" in source
