from __future__ import annotations

from datetime import date

from src.services.sync.sync_dividend_service import SyncDividendService
from src.services.transform.dividend_hash import build_dividend_event_key_hash, build_dividend_row_key_hash


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
            "end_date": "20251231",
            "ann_date": "20260321",
            "div_proc": "预案",
            "record_date": None,
            "ex_date": None,
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
    assert raw_rows[0]["row_key_hash"] == build_dividend_row_key_hash(raw_rows[0])
    assert service.dao.raw_dividend.bulk_upsert.call_args.kwargs["conflict_columns"] == ["row_key_hash"]
    core_rows = service.dao.equity_dividend.bulk_upsert.call_args.args[0]
    assert core_rows[0]["ts_code"] == "000001.SZ"
    assert core_rows[0]["end_date"] == date(2025, 12, 31)
    assert core_rows[0]["ann_date"] == date(2026, 3, 21)
    assert core_rows[0]["div_proc"] == "预案"
    assert core_rows[0]["row_key_hash"] == build_dividend_row_key_hash(core_rows[0])
    assert core_rows[0]["event_key_hash"] == build_dividend_event_key_hash(core_rows[0])
    assert service.dao.equity_dividend.bulk_upsert.call_args.kwargs["conflict_columns"] == ["row_key_hash"]


def test_dividend_execute_skips_rows_missing_required_core_keys(mocker) -> None:
    service = _build_service(mocker)
    service.client.call.return_value = [
        {
            "ts_code": "000001.SZ",
            "ann_date": "20260321",
            "div_proc": None,
            "cash_div_tax": 0.36,
        }
    ]
    service.dao.equity_dividend.bulk_upsert.return_value = 0

    fetched, written, _, message = service.execute("FULL", ts_code="000001.SZ")

    assert fetched == 1
    assert written == 0
    assert message == "skipped 1 core dividend rows missing required business keys"
    raw_rows = service.dao.raw_dividend.bulk_upsert.call_args.args[0]
    assert len(raw_rows) == 1
    assert raw_rows[0]["ts_code"] == "000001.SZ"
    service.dao.equity_dividend.bulk_upsert.assert_called_once_with([], conflict_columns=["row_key_hash"])
    service.logger.warning.assert_called_once()
    service.logger.debug.assert_called_once()


def test_dividend_execute_preserves_raw_rows_even_when_core_skips(mocker) -> None:
    service = _build_service(mocker)
    service.client.call.return_value = [
        {
            "ts_code": "000001.SZ",
            "end_date": None,
            "ann_date": None,
            "div_proc": "预案",
        }
    ]
    service.dao.equity_dividend.bulk_upsert.return_value = 0

    _, written, _, message = service.execute("FULL", ts_code="000001.SZ")

    assert written == 0
    assert message == "skipped 1 core dividend rows missing required business keys"
    raw_rows = service.dao.raw_dividend.bulk_upsert.call_args.args[0]
    assert len(raw_rows) == 1
    assert raw_rows[0]["end_date"] is None


def test_dividend_execute_same_record_uses_stable_row_key_hash(mocker) -> None:
    service = _build_service(mocker)
    record = {
        "ts_code": "000001.SZ",
        "end_date": "20251231",
        "ann_date": "20260321",
        "div_proc": "预案",
        "record_date": None,
        "ex_date": None,
        "cash_div_tax": 0.36,
    }
    service.client.call.return_value = [record]
    service.dao.raw_dividend.bulk_upsert.return_value = 1
    service.dao.equity_dividend.bulk_upsert.return_value = 1

    service.execute("FULL", ts_code="000001.SZ")
    first_raw = service.dao.raw_dividend.bulk_upsert.call_args.args[0][0]["row_key_hash"]
    first_core = service.dao.equity_dividend.bulk_upsert.call_args.args[0][0]["row_key_hash"]

    service.execute("FULL", ts_code="000001.SZ")
    second_raw = service.dao.raw_dividend.bulk_upsert.call_args.args[0][0]["row_key_hash"]
    second_core = service.dao.equity_dividend.bulk_upsert.call_args.args[0][0]["row_key_hash"]

    assert first_raw == second_raw
    assert first_core == second_core
