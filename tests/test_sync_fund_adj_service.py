from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.foundation.services.sync.sync_fund_adj_service import SyncFundAdjService


def test_sync_fund_adj_incremental_paginates_with_default_limit(mocker) -> None:
    session = mocker.Mock()
    service = SyncFundAdjService(session)
    service.page_limit = 2
    mocker.patch.object(
        service.client,
        "call",
        side_effect=[
            [
                {"ts_code": "510300.SH", "trade_date": "20260331", "adj_factor": "1.001"},
                {"ts_code": "159915.SZ", "trade_date": "20260331", "adj_factor": "1.002"},
            ],
            [
                {"ts_code": "512880.SH", "trade_date": "20260331", "adj_factor": "1.003"},
            ],
        ],
    )
    raw_upsert = mocker.patch.object(service.dao.raw_fund_adj, "bulk_upsert", side_effect=[2, 1])
    core_upsert = mocker.patch.object(service.dao.fund_adj_factor, "bulk_upsert", side_effect=[2, 1])

    fetched, written, result_date, message = service.execute("INCREMENTAL", trade_date=date(2026, 3, 31))

    assert fetched == 3
    assert written == 3
    assert result_date == date(2026, 3, 31)
    assert message is None
    assert service.client.call.call_args_list[0].kwargs["params"] == {"trade_date": "20260331", "limit": 2, "offset": 0}
    assert service.client.call.call_args_list[1].kwargs["params"] == {"trade_date": "20260331", "limit": 2, "offset": 2}
    rows = raw_upsert.call_args_list[0].args[0]
    assert rows[0]["adj_factor"] == Decimal("1.001")
    assert raw_upsert.call_count == 2
    assert core_upsert.call_count == 2
