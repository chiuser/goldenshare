from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.normalizer import NormalizedBatch
from src.foundation.ingestion.writer import DatasetWriter
from src.foundation.models.core.equity_factor_pro import EquityFactorPro
from src.foundation.models.raw.raw_stk_factor_pro import RawStkFactorPro


class _StubRawDao:
    model = RawStkFactorPro

    def __init__(self) -> None:
        self.bulk_upsert_calls: list[list[dict]] = []

    def bulk_upsert(self, rows: list[dict], conflict_columns=None):  # type: ignore[no-untyped-def]
        self.bulk_upsert_calls.append(rows)
        return len(rows)


class _ForbiddenServingDao:
    model = EquityFactorPro

    def __init__(self) -> None:
        self.bulk_upsert_calls = 0

    def bulk_upsert(self, rows: list[dict], conflict_columns=None):  # type: ignore[no-untyped-def]
        self.bulk_upsert_calls += 1
        raise AssertionError("stk_factor_pro raw_only_upsert must not write serving")


def test_stk_factor_pro_writer_only_upserts_raw_table(mocker) -> None:
    raw_dao = _StubRawDao()
    serving_dao = _ForbiddenServingDao()
    mocker.patch(
        "src.foundation.ingestion.writer.DAOFactory",
        return_value=SimpleNamespace(raw_stk_factor_pro=raw_dao, equity_factor_pro=serving_dao),
    )
    writer = DatasetWriter(session=mocker.Mock())
    definition = get_dataset_definition("stk_factor_pro")
    batch = NormalizedBatch(
        unit_id="u-stk-factor-pro",
        rows_normalized=[
            {
                "ts_code": "000001.SZ",
                "trade_date": date(2026, 4, 24),
                "open": 10.1,
                "close_qfq": 11.2,
            }
        ],
        rows_rejected=0,
        rejected_reasons={},
    )

    result = writer.write(definition=definition, batch=batch)

    assert raw_dao.bulk_upsert_calls == [batch.rows_normalized]
    assert serving_dao.bulk_upsert_calls == 0
    assert result.target_table == "core_serving.equity_factor_pro"
    assert result.rows_written == 1
