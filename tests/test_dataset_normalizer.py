from __future__ import annotations

from datetime import date

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
