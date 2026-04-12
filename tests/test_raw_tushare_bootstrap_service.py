from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.foundation.services.migration.raw_tushare_bootstrap_service import RawTushareBootstrapService


def test_raw_tushare_bootstrap_service_list_tables(mocker) -> None:
    session = mocker.Mock()
    session.execute.return_value.scalars.return_value = ["daily", "daily_basic"]

    tables = RawTushareBootstrapService().list_legacy_raw_tables(session)

    assert tables == ["daily", "daily_basic"]


def test_raw_tushare_bootstrap_service_rejects_unknown_table(mocker) -> None:
    session = mocker.Mock()
    session.execute.return_value.scalars.return_value = ["daily", "daily_basic"]

    service = RawTushareBootstrapService()
    with pytest.raises(ValueError, match="Unknown raw tables"):
        service.run(session, table_names=["daily", "not_exists"], migrate_data=False)


def test_raw_tushare_bootstrap_service_create_and_migrate_data(mocker) -> None:
    session = mocker.Mock()
    service = RawTushareBootstrapService()
    mocker.patch.object(service, "list_legacy_raw_tables", return_value=["daily"])
    mocker.patch.object(service, "_list_columns", side_effect=[["ts_code", "trade_date", "close"], ["ts_code", "trade_date"]])

    # For INSERT rowcount
    session.execute.side_effect = [
        SimpleNamespace(),  # create schema
        SimpleNamespace(),  # create table
        SimpleNamespace(),  # truncate
        SimpleNamespace(rowcount=123),  # insert
    ]

    result = service.run(session, table_names=["daily"], migrate_data=True)

    assert len(result.tables) == 1
    item = result.tables[0]
    assert item.table_name == "daily"
    assert item.migrated is True
    assert item.inserted_rows == 123
    assert session.commit.call_count == 1


def test_raw_tushare_bootstrap_service_migrate_by_common_columns(mocker) -> None:
    session = mocker.Mock()
    service = RawTushareBootstrapService()
    mocker.patch.object(service, "list_legacy_raw_tables", return_value=["stock_basic"])
    mocker.patch.object(
        service,
        "_list_columns",
        side_effect=[
            ["ts_code", "symbol", "name", "market"],
            ["ts_code", "symbol", "name"],
        ],
    )
    session.execute.side_effect = [
        SimpleNamespace(),  # create schema
        SimpleNamespace(),  # create table
        SimpleNamespace(),  # truncate
        SimpleNamespace(rowcount=3),  # insert
    ]

    result = service.run(session, table_names=["stock_basic"], migrate_data=True)

    assert result.tables[0].inserted_rows == 3
    executed_sql = " ".join(str(call.args[0]) for call in session.execute.call_args_list if call.args)
    assert 'INSERT INTO raw_tushare."stock_basic" ("ts_code", "symbol", "name")' in executed_sql
    assert 'SELECT "ts_code", "symbol", "name" FROM raw."stock_basic"' in executed_sql
