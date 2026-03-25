from __future__ import annotations

from datetime import date

from src.scripts.backfill_top_list_reason_hash import find_top_list_reason_hash_conflicts
from src.services.sync.sync_top_list_service import SyncTopListService
from src.services.transform.top_list_reason import hash_top_list_reason, normalize_top_list_reason


def _build_service(mocker) -> SyncTopListService:
    session = mocker.Mock()
    service = SyncTopListService(session)
    service.dao = mocker.Mock()
    service.dao.raw_top_list = mocker.Mock()
    service.dao.equity_top_list = mocker.Mock()
    service.client = mocker.Mock()
    service.logger = mocker.Mock()
    return service


def test_top_list_reason_hash_normalizes_before_hashing() -> None:
    assert normalize_top_list_reason("  异常\t波动  ") == "异常 波动"
    assert normalize_top_list_reason("ＡＢＣ　123") == "ABC 123"
    assert hash_top_list_reason("  异常\t波动  ") == hash_top_list_reason("异常 波动")


def test_top_list_execute_writes_reason_hash_and_keeps_legacy_conflict_semantics_until_backfill(mocker) -> None:
    service = _build_service(mocker)
    service.client.call.return_value = [
        {
            "ts_code": "000001.SZ",
            "trade_date": "20260324",
            "reason": "  异常\t波动  ",
            "pct_change": 1.23,
        }
    ]
    service.dao.raw_top_list.bulk_upsert.return_value = 1
    service.dao.equity_top_list.bulk_upsert.return_value = 1

    fetched, written, result_date, message = service.execute("INCREMENTAL", trade_date=date(2026, 3, 24))

    assert fetched == 1
    assert written == 1
    assert result_date == date(2026, 3, 24)
    assert message is None
    core_rows = service.dao.equity_top_list.bulk_upsert.call_args.args[0]
    assert core_rows[0]["reason_hash"] == hash_top_list_reason("异常 波动")
    assert core_rows[0]["pct_chg"] is not None
    assert service.dao.equity_top_list.bulk_upsert.call_args.kwargs == {}


def test_top_list_execute_preserves_raw_rows_and_skips_core_when_reason_missing(mocker) -> None:
    service = _build_service(mocker)
    service.client.call.return_value = [
        {
            "ts_code": "000001.SZ",
            "trade_date": "20260324",
            "reason": "   ",
        }
    ]
    service.dao.raw_top_list.bulk_upsert.return_value = 1
    service.dao.equity_top_list.bulk_upsert.return_value = 0

    fetched, written, _, message = service.execute("INCREMENTAL", trade_date=date(2026, 3, 24))

    assert fetched == 1
    assert written == 0
    assert message == "skipped 1 top_list rows missing required core reason"
    raw_rows = service.dao.raw_top_list.bulk_upsert.call_args.args[0]
    assert raw_rows[0]["ts_code"] == "000001.SZ"
    service.dao.equity_top_list.bulk_upsert.assert_called_once_with([])
    service.logger.warning.assert_called_once()


def test_top_list_current_deploy_order_avoids_reason_hash_conflict_switch_before_backfill(mocker) -> None:
    service = _build_service(mocker)
    service.client.call.return_value = [
        {
            "ts_code": "000001.SZ",
            "trade_date": "20260324",
            "reason": "异常 波动",
        }
    ]
    service.dao.raw_top_list.bulk_upsert.return_value = 1
    service.dao.equity_top_list.bulk_upsert.return_value = 1

    service.execute("INCREMENTAL", trade_date=date(2026, 3, 24))

    # Deployment safety: current sync still upserts by the legacy primary key
    # while reason_hash is only populated as a staged field.
    assert service.dao.equity_top_list.bulk_upsert.call_args.kwargs == {}


def test_find_top_list_reason_hash_conflicts_detects_normalized_duplicates(mocker) -> None:
    session = mocker.Mock()
    session.execute.return_value = [
        ("000001.SZ", date(2026, 3, 24), "异常  波动"),
        ("000001.SZ", date(2026, 3, 24), "异常\t波动"),
    ]

    conflicts = find_top_list_reason_hash_conflicts(session)

    assert len(conflicts) == 1
    ts_code, trade_date, reason_hash, count = conflicts[0]
    assert ts_code == "000001.SZ"
    assert trade_date == date(2026, 3, 24)
    assert reason_hash == hash_top_list_reason("异常 波动")
    assert count == 2
