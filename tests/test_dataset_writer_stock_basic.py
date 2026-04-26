from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.execution_plan import PlanUnitSnapshot
from src.foundation.ingestion.normalizer import NormalizedBatch
from src.foundation.ingestion.writer import DatasetWriter


class _StubUpsertDao:
    def __init__(self, written: int = 1) -> None:
        self.written = written
        self.calls: list[list[dict]] = []

    def bulk_upsert(self, rows: list[dict], conflict_columns=None):  # type: ignore[no-untyped-def]
        self.calls.append(rows)
        return self.written


class _StubSecurityDao:
    def __init__(self, existing: set[str] | None = None, written: int = 1) -> None:
        self.existing = existing or set()
        self.written = written
        self.upsert_calls: list[list[dict]] = []
        self.existing_calls: list[list[str]] = []

    def get_existing_ts_codes(self, ts_codes):  # type: ignore[no-untyped-def]
        self.existing_calls.append(list(ts_codes))
        return set(self.existing)

    def upsert_many(self, rows: list[dict]) -> int:
        self.upsert_calls.append(rows)
        return self.written if rows else 0


def test_writer_stock_basic_tushare_direct_publish(mocker) -> None:
    raw_tushare = _StubUpsertDao(written=2)
    raw_biying = _StubUpsertDao(written=0)
    security_std = _StubUpsertDao(written=2)
    security = _StubSecurityDao(existing=set(), written=2)
    mocker.patch(
        "src.foundation.ingestion.writer.DAOFactory",
        return_value=SimpleNamespace(
            raw_stock_basic=raw_tushare,
            raw_tushare_stock_basic=raw_tushare,
            raw_biying_stock_basic=raw_biying,
            security_std=security_std,
            security=security,
        ),
    )
    writer = DatasetWriter(session=object())  # type: ignore[arg-type]
    definition = get_dataset_definition("stock_basic")
    batch = NormalizedBatch(
        unit_id="u-stock-basic-tushare",
        rows_normalized=[
            {
                "ts_code": "000001.SZ",
                "name": "平安银行",
                "list_status": "L",
                "list_date": date(1991, 4, 3),
            }
        ],
        rows_rejected=0,
        rejected_reasons={},
    )
    plan_unit = PlanUnitSnapshot(
        unit_id="u-stock-basic-tushare",
        dataset_key="stock_basic",
        source_key="tushare",
        trade_date=None,
        request_params={},
        progress_context={},
        requested_source_key="tushare",
    )

    result = writer.write(definition=definition, batch=batch, plan_unit=plan_unit)

    assert len(raw_tushare.calls) == 1
    assert len(security_std.calls) == 1
    assert len(security.upsert_calls) == 1
    assert result.rows_written == 2
    assert result.conflict_strategy == "tushare_direct_upsert"


def test_writer_stock_basic_biying_only_inserts_missing_codes(mocker) -> None:
    raw_tushare = _StubUpsertDao(written=0)
    raw_biying = _StubUpsertDao(written=2)
    security_std = _StubUpsertDao(written=2)
    security = _StubSecurityDao(existing={"000001.SZ"}, written=1)
    mocker.patch(
        "src.foundation.ingestion.writer.DAOFactory",
        return_value=SimpleNamespace(
            raw_stock_basic=raw_tushare,
            raw_tushare_stock_basic=raw_tushare,
            raw_biying_stock_basic=raw_biying,
            security_std=security_std,
            security=security,
        ),
    )
    writer = DatasetWriter(session=object())  # type: ignore[arg-type]
    definition = get_dataset_definition("stock_basic")
    batch = NormalizedBatch(
        unit_id="u-stock-basic-biying",
        rows_normalized=[
            {"dm": "000001.SZ", "mc": "平安银行", "jys": "SZSE"},
            {"dm": "000002.SZ", "mc": "万科A", "jys": "SZSE"},
        ],
        rows_rejected=0,
        rejected_reasons={},
    )
    plan_unit = PlanUnitSnapshot(
        unit_id="u-stock-basic-biying",
        dataset_key="stock_basic",
        source_key="biying",
        trade_date=None,
        request_params={},
        progress_context={},
        requested_source_key="biying",
    )

    result = writer.write(definition=definition, batch=batch, plan_unit=plan_unit)

    assert len(raw_biying.calls) == 1
    assert len(security_std.calls) == 1
    assert security.existing_calls == [["000001.SZ", "000002.SZ"]]
    assert len(security.upsert_calls) == 1
    assert [row["ts_code"] for row in security.upsert_calls[0]] == ["000002.SZ"]
    assert result.conflict_strategy == "biying_missing_only"
