from __future__ import annotations

from decimal import Decimal

from src.foundation.services.sync.sync_etf_index_service import SyncEtfIndexService


def test_sync_etf_index_service_normalizes_and_upserts_rows(mocker) -> None:
    session = mocker.Mock()
    service = SyncEtfIndexService(session)
    mocker.patch.object(
        service.client,
        "call",
        return_value=[
            {
                "ts_code": "CSI931151.CSI",
                "indx_name": "中证光伏产业指数",
                "indx_csname": "光伏产业指数",
                "pub_party_name": "中证指数有限公司",
                "pub_date": "2025-01-31",
                "base_date": "2025-01-02",
                "bp": "1000.000000",
                "adj_circle": "季度",
            }
        ],
    )
    raw_upsert = mocker.patch.object(service.dao.raw_etf_index, "bulk_upsert", return_value=1)
    core_upsert = mocker.patch.object(service.dao.etf_index, "bulk_upsert", return_value=1)

    fetched, written, result_date, message = service.execute("FULL")

    assert fetched == 1
    assert written == 1
    assert result_date is None
    assert message is None
    rows = raw_upsert.call_args.args[0]
    assert rows[0]["pub_date"].isoformat() == "2025-01-31"
    assert rows[0]["base_date"].isoformat() == "2025-01-02"
    assert rows[0]["bp"] == Decimal("1000.000000")
    core_upsert.assert_called_once_with(rows)
