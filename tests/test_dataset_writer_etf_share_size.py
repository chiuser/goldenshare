from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.normalizer import NormalizedBatch
from src.foundation.ingestion.writer import DatasetWriter
from src.foundation.models.raw.raw_etf_share_size import RawEtfShareSize


class _StubRawDao:
    model = RawEtfShareSize

    def __init__(self) -> None:
        self.bulk_upsert_calls: list[tuple[list[dict], list[str] | None]] = []

    def bulk_upsert(self, rows: list[dict], conflict_columns=None):  # type: ignore[no-untyped-def]
        self.bulk_upsert_calls.append((rows, list(conflict_columns or []) or None))
        return len(rows)


def test_etf_share_size_writer_only_upserts_raw_table(mocker) -> None:
    raw_dao = _StubRawDao()
    mocker.patch("src.foundation.ingestion.writer.DAOFactory", return_value=SimpleNamespace(raw_etf_share_size=raw_dao))
    writer = DatasetWriter(session=mocker.Mock())
    batch = NormalizedBatch(
        unit_id="u-etf-share-size",
        rows_normalized=[
            {
                "trade_date": date(2026, 8, 21),
                "ts_code": "510300.SH",
                "etf_name": "沪深300ETF",
                "total_share": Decimal("1000000.123456"),
                "total_size": Decimal("4200000.123456"),
                "nav": Decimal("4.20000001"),
                "close": Decimal("4.21000001"),
                "exchange": "SSE",
            }
        ],
        rows_rejected=0,
        rejected_reasons={},
    )

    result = writer.write(definition=get_dataset_definition("etf_share_size"), batch=batch)

    assert raw_dao.bulk_upsert_calls == [(batch.rows_normalized, ["trade_date", "ts_code"])]
    assert result.target_table == "raw_tushare.etf_share_size"
    assert result.rows_written == 1
