from __future__ import annotations

from datetime import date

from src.foundation.services.sync.sync_holdernumber_service import SyncHolderNumberService
from src.foundation.services.transform.holdernumber_hash import build_holdernumber_event_key_hash, build_holdernumber_row_key_hash


def _build_service(mocker) -> SyncHolderNumberService:
    session = mocker.Mock()
    service = SyncHolderNumberService(session)
    service.dao = mocker.Mock()
    service.dao.raw_holder_number = mocker.Mock()
    service.dao.equity_holder_number = mocker.Mock()
    service.client = mocker.Mock()
    service.logger = mocker.Mock()
    return service


def test_holdernumber_execute_writes_raw_and_core_when_ann_date_missing(mocker) -> None:
    service = _build_service(mocker)
    service.client.call.return_value = [
        {"ts_code": "000001.SZ", "ann_date": None, "end_date": "19961231", "holder_num": 330500}
    ]
    service.dao.raw_holder_number.bulk_upsert.return_value = 1
    service.dao.equity_holder_number.bulk_upsert.return_value = 1

    fetched, written, _, message = service.execute("FULL", ts_code="000001.SZ")

    assert fetched == 1
    assert written == 1
    assert message is None
    raw_rows = service.dao.raw_holder_number.bulk_upsert.call_args.args[0]
    assert raw_rows[0]["row_key_hash"] == build_holdernumber_row_key_hash(raw_rows[0])
    assert service.dao.raw_holder_number.bulk_upsert.call_args.kwargs["conflict_columns"] == ["row_key_hash"]
    core_rows = service.dao.equity_holder_number.bulk_upsert.call_args.args[0]
    assert core_rows[0]["end_date"] == date(1996, 12, 31)
    assert core_rows[0]["ann_date"] is None
    assert core_rows[0]["row_key_hash"] == build_holdernumber_row_key_hash(core_rows[0])
    assert core_rows[0]["event_key_hash"] == build_holdernumber_event_key_hash(core_rows[0])


def test_holdernumber_execute_skips_core_when_ts_code_or_end_date_missing(mocker) -> None:
    service = _build_service(mocker)
    service.client.call.return_value = [{"ts_code": "000001.SZ", "ann_date": None, "end_date": None, "holder_num": 330500}]
    service.dao.equity_holder_number.bulk_upsert.return_value = 0

    fetched, written, _, message = service.execute("FULL", ts_code="000001.SZ")

    assert fetched == 1
    assert written == 0
    assert message == "skipped 1 core holdernumber rows missing required business keys"
    service.dao.equity_holder_number.bulk_upsert.assert_called_once_with([], conflict_columns=["row_key_hash"])
