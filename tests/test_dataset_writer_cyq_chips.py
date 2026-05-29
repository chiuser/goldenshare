from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.normalizer import NormalizedBatch
from src.foundation.ingestion.writer import DatasetWriter
from src.foundation.models.raw.raw_cyq_chips import RawCyqChips


class _StubRawDao:
    model = RawCyqChips

    def __init__(self) -> None:
        self.bulk_upsert_calls: list[tuple[list[dict], list[str] | None]] = []

    def bulk_upsert(self, rows: list[dict], conflict_columns=None):  # type: ignore[no-untyped-def]
        self.bulk_upsert_calls.append((rows, list(conflict_columns or []) or None))
        return len(rows)


def test_cyq_chips_writer_only_upserts_raw_table(mocker) -> None:
    raw_dao = _StubRawDao()
    mocker.patch("src.foundation.ingestion.writer.DAOFactory", return_value=SimpleNamespace(raw_cyq_chips=raw_dao))
    writer = DatasetWriter(session=mocker.Mock())
    definition = get_dataset_definition("cyq_chips")
    batch = NormalizedBatch(
        unit_id="u-cyq-chips",
        rows_normalized=[
            {
                "ts_code": "600000.SH",
                "trade_date": date(2026, 4, 24),
                "price": Decimal("10.1200"),
                "percent": Decimal("1.2300"),
            }
        ],
        rows_rejected=0,
        rejected_reasons={},
    )

    result = writer.write(definition=definition, batch=batch)

    assert len(raw_dao.bulk_upsert_calls) == 1
    rows, conflict_columns = raw_dao.bulk_upsert_calls[0]
    assert rows == batch.rows_normalized
    assert conflict_columns == ["ts_code", "trade_date", "price"]
    assert result.target_table == "raw_tushare.cyq_chips"
    assert result.rows_written == 1
