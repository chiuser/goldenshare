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
