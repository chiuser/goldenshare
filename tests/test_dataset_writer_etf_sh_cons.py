from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.normalizer import NormalizedBatch
from src.foundation.ingestion.writer import DatasetWriter
from src.foundation.models.raw.raw_etf_sh_cons import RawEtfShCons


class _StubRawDao:
    model = RawEtfShCons

    def __init__(self) -> None:
        self.bulk_upsert_calls: list[tuple[list[dict], list[str] | None]] = []

    def bulk_upsert(self, rows: list[dict], conflict_columns=None):  # type: ignore[no-untyped-def]
        self.bulk_upsert_calls.append((rows, list(conflict_columns or []) or None))
        return len(rows)


def test_etf_sh_cons_writer_only_upserts_raw_table(mocker) -> None:
    raw_dao = _StubRawDao()
    mocker.patch("src.foundation.ingestion.writer.DAOFactory", return_value=SimpleNamespace(raw_etf_sh_cons=raw_dao))
    writer = DatasetWriter(session=mocker.Mock())
    definition = get_dataset_definition("etf_sh_cons")
    batch = NormalizedBatch(
        unit_id="u-etf-sh-cons",
        rows_normalized=[
            {
                "trade_date": date(2026, 6, 18),
                "ts_code": "510300.SH",
                "con_code": "000001.SZ",
                "con_name": "平安银行",
                "qty": Decimal("1500.000000"),
                "sub_flag": "现金替代",
                "cpr": "-",
                "rdr": "1",
                "sca": None,
                "exchange": "SSE",
            }
        ],
        rows_rejected=0,
        rejected_reasons={},
    )

    result = writer.write(definition=definition, batch=batch)

    assert len(raw_dao.bulk_upsert_calls) == 1
    rows, conflict_columns = raw_dao.bulk_upsert_calls[0]
    assert rows == batch.rows_normalized
    assert conflict_columns == ["trade_date", "ts_code", "con_code"]
    assert result.target_table == "raw_tushare.etf_sh_cons"
    assert result.rows_written == 1
