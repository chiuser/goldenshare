from __future__ import annotations

from datetime import date

from src.services.sync.sync_dividend_service import SyncDividendService


def _build_service(mocker) -> SyncDividendService:
    session = mocker.Mock()
    service = SyncDividendService(session)
    service.dao = mocker.Mock()
    service.dao.raw_dividend = mocker.Mock()
    service.dao.equity_dividend = mocker.Mock()
    service.client = mocker.Mock()
    service.logger = mocker.Mock()
    return service


def test_dividend_execute_writes_valid_core_rows(mocker) -> None:
    service = _build_service(mocker)
    service.client.call.return_value = [
        {
            "ts_code": "000001.SZ",
            "ann_date": "20260321",
            "record_date": "20260325",
            "ex_date": "20260326",
            "cash_div_tax": 0.36,
        }
    ]
    service.dao.raw_dividend.bulk_upsert.return_value = 1
    service.dao.equity_dividend.bulk_upsert.return_value = 1

    fetched, written, _, message = service.execute("FULL", ts_code="000001.SZ")

    assert fetched == 1
    assert written == 1
    assert message is None
    raw_rows = service.dao.raw_dividend.bulk_upsert.call_args.args[0]
    assert len(raw_rows) == 1
    assert raw_rows[0]["ts_code"] == "000001.SZ"
    core_rows = service.dao.equity_dividend.bulk_upsert.call_args.args[0]
    assert core_rows[0]["ts_code"] == "000001.SZ"
    assert core_rows[0]["ann_date"] == date(2026, 3, 21)


def test_dividend_execute_skips_rows_missing_required_core_keys(mocker) -> None:
    service = _build_service(mocker)
    service.client.call.return_value = [
        {
            "ts_code": "000001.SZ",
            "ann_date": "20260321",
            "record_date": None,
            "ex_date": None,
            "cash_div_tax": 0.36,
        }
    ]
    service.dao.raw_dividend.bulk_upsert.return_value = 1
    service.dao.equity_dividend.bulk_upsert.return_value = 0

    fetched, written, _, message = service.execute("FULL", ts_code="000001.SZ")

    assert fetched == 1
    assert written == 0
    assert message == "skipped 1 rows missing required core dividend keys"
    raw_rows = service.dao.raw_dividend.bulk_upsert.call_args.args[0]
    assert len(raw_rows) == 1
    assert raw_rows[0]["ts_code"] == "000001.SZ"
    service.dao.equity_dividend.bulk_upsert.assert_called_once_with([])
    service.logger.warning.assert_called_once()
    service.logger.debug.assert_called_once()


def test_dividend_execute_preserves_raw_rows_even_when_core_skips(mocker) -> None:
    service = _build_service(mocker)
    service.client.call.return_value = [
        {
            "ts_code": "000001.SZ",
            "ann_date": None,
            "record_date": "20260325",
            "ex_date": "20260326",
        }
    ]
    service.dao.raw_dividend.bulk_upsert.return_value = 1
    service.dao.equity_dividend.bulk_upsert.return_value = 0

    service.execute("FULL", ts_code="000001.SZ")

    raw_rows = service.dao.raw_dividend.bulk_upsert.call_args.args[0]
    assert len(raw_rows) == 1
    assert raw_rows[0]["ts_code"] == "000001.SZ"
