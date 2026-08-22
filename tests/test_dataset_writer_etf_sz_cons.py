from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.normalizer import NormalizedBatch
from src.foundation.ingestion.writer import DatasetWriter
from src.foundation.models.raw.raw_etf_sz_cons import RawEtfSzCons


class _StubRawDao:
    model = RawEtfSzCons

    def __init__(self) -> None:
        self.bulk_upsert_calls: list[tuple[list[dict], list[str] | None]] = []

    def bulk_upsert(self, rows: list[dict], conflict_columns=None):  # type: ignore[no-untyped-def]
        self.bulk_upsert_calls.append((rows, list(conflict_columns or []) or None))
        return len(rows)


def test_etf_sz_cons_writer_only_upserts_raw_table(mocker) -> None:
    raw_dao = _StubRawDao()
    mocker.patch("src.foundation.ingestion.writer.DAOFactory", return_value=SimpleNamespace(raw_etf_sz_cons=raw_dao))
    writer = DatasetWriter(session=mocker.Mock())
    batch = NormalizedBatch(
        unit_id="u-etf-sz-cons",
        rows_normalized=[
            {
                "trade_date": date(2026, 8, 21),
                "ts_code": "159919.SZ",
                "con_code": "000001.SZ",
                "con_name": "平安银行",
                "qty": Decimal("1500.000000"),
                "sub_flag": "允许",
                "cpr": Decimal("0.10000000"),
                "rdr": Decimal("0.20000000"),
                "sub_cc": Decimal("100.00000000"),
                "red_cc": Decimal("200.00000000"),
                "exchange": "SZSE",
            }
        ],
        rows_rejected=0,
        rejected_reasons={},
    )

    result = writer.write(definition=get_dataset_definition("etf_sz_cons"), batch=batch)

    assert raw_dao.bulk_upsert_calls == [(batch.rows_normalized, ["trade_date", "ts_code", "con_code"])]
    assert result.target_table == "raw_tushare.etf_sz_cons"
    assert result.rows_written == 1
