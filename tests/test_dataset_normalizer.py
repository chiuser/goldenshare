from __future__ import annotations

from datetime import date
from datetime import datetime

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.normalizer import DatasetNormalizer
from src.foundation.ingestion.source_client import SourceFetchResult


def test_dc_daily_normalizer_keeps_required_fields() -> None:
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("dc_daily"),
        fetch_result=SourceFetchResult(
            unit_id="u-dc-daily",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[{"trade_date": "20260401", "ts_code": "BK001", "close": "1"}],
        ),
    )

    assert batch.rows_rejected == 0
    assert batch.rows_normalized[0]["trade_date"] == date(2026, 4, 1)
    assert batch.rows_normalized[0]["ts_code"] == "BK001"


def test_stk_mins_normalizer_writes_slim_storage_fields_only() -> None:
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("stk_mins"),
        fetch_result=SourceFetchResult(
            unit_id="u-stk-mins",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "ts_code": "600000.sh",
                    "freq": "5min",
                    "trade_time": "2026-04-24 09:35:00",
                    "open": "10.234",
                    "close": "10.236",
                    "high": "10.246",
                    "low": "10.221",
                    "vol": "3000000000",
                    "amount": "5678.9",
                    "trade_date": "20260424",
                    "session_tag": "morning",
                    "api_name": "stk_mins",
                    "fetched_at": "2026-04-24T09:36:00+08:00",
                    "raw_payload": "{}",
                }
            ],
        ),
    )

    assert batch.rows_rejected == 0
    normalized = batch.rows_normalized[0]
    assert normalized == {
        "ts_code": "600000.SH",
        "freq": 5,
        "trade_time": datetime(2026, 4, 24, 9, 35),
        "open": 10.23,
        "close": 10.24,
        "high": 10.25,
        "low": 10.22,
        "vol": 3000000000,
        "amount": 5678.9,
    }


def test_stk_mins_normalizer_rejects_outside_trading_session() -> None:
    batch = DatasetNormalizer().normalize(
        definition=get_dataset_definition("stk_mins"),
        fetch_result=SourceFetchResult(
            unit_id="u-stk-mins",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "ts_code": "600000.SH",
                    "freq": "1min",
                    "trade_time": "2026-04-24 12:00:00",
                    "open": "10.23",
                    "close": "10.23",
                    "high": "10.23",
                    "low": "10.23",
                    "vol": "1",
                    "amount": "1",
                }
            ],
        ),
    )

    assert batch.rows_normalized == []
    assert batch.rows_rejected == 1
    assert batch.rejected_reasons == {"normalize.row_transform_failed": 1}
