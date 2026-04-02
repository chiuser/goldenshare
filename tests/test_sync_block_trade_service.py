from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from src.services.sync.sync_block_trade_service import SyncBlockTradeService


def _build_fake_dao(raw_dao: SimpleNamespace, core_dao: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        sync_run_log=SimpleNamespace(
            start_log=lambda *args, **kwargs: object(),
            finish_log=lambda *args, **kwargs: None,
        ),
        sync_job_state=SimpleNamespace(
            mark_success=lambda *args, **kwargs: None,
            mark_full_sync_done=lambda *args, **kwargs: None,
        ),
        raw_block_trade=raw_dao,
        equity_block_trade=core_dao,
    )


def test_block_trade_keeps_source_duplicates_and_rebuilds_trade_date_snapshot(mocker) -> None:
    session = mocker.Mock()
    raw_dao = mocker.Mock()
    core_dao = mocker.Mock()
    core_dao.bulk_insert.return_value = 3
    mocker.patch(
        "src.services.sync.base_sync_service.DAOFactory",
        return_value=_build_fake_dao(raw_dao, core_dao),
    )
    snapshot_service_cls = mocker.patch("src.operations.services.dataset_status_snapshot_service.DatasetStatusSnapshotService")
    snapshot_service = snapshot_service_cls.return_value

    service = SyncBlockTradeService(session)
    service.client = mocker.Mock()
    service.client.call.return_value = [
        {
            "ts_code": "000001.SZ",
            "trade_date": "20260401",
            "buyer": "A",
            "seller": "B",
            "price": "10.01",
            "vol": "1000",
            "amount": "10010",
        },
        {
            "ts_code": "000001.SZ",
            "trade_date": "20260401",
            "buyer": "A",
            "seller": "B",
            "price": "10.01",
            "vol": "1000",
            "amount": "10010",
        },
        {
            "ts_code": "000002.SZ",
            "trade_date": "20260401",
            "buyer": "C",
            "seller": "D",
            "price": "8.88",
            "vol": "2000",
            "amount": "17760",
        },
    ]

    result = service.run_incremental(trade_date=date(2026, 4, 1))

    raw_dao.delete_by_date_range.assert_called_once_with(date(2026, 4, 1), date(2026, 4, 1))
    core_dao.delete_by_date_range.assert_called_once_with(date(2026, 4, 1), date(2026, 4, 1))
    assert raw_dao.bulk_insert.call_count == 1
    assert core_dao.bulk_insert.call_count == 1
    inserted_rows = core_dao.bulk_insert.call_args.args[0]
    assert len(inserted_rows) == 3
    assert result.rows_fetched == 3
    assert result.rows_written == 3
    snapshot_service.refresh_resources.assert_called_once_with(session, ["block_trade", "equity_block_trade"])
