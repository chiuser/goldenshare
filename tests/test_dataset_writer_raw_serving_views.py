from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from src.foundation.datasets.registry import get_dataset_definition
from src.foundation.ingestion.normalizer import NormalizedBatch
from src.foundation.ingestion.writer import DatasetWriter
from src.foundation.models.raw.raw_cyq_perf import RawCyqPerf
from src.foundation.models.raw.raw_dc_daily import RawDcDaily
from src.foundation.models.raw.raw_moneyflow_cnt_ths import RawMoneyflowCntThs
from src.foundation.models.raw.raw_moneyflow_ind_dc import RawMoneyflowIndDc
from src.foundation.models.raw.raw_moneyflow_ind_ths import RawMoneyflowIndThs
from src.foundation.models.raw.raw_moneyflow_mkt_dc import RawMoneyflowMktDc
from src.foundation.models.raw.raw_margin import RawMargin
from src.foundation.models.raw.raw_st import RawSt
from src.foundation.models.raw.raw_stk_nineturn import RawStkNineTurn
from src.foundation.models.raw.raw_suspend_d import RawSuspendD


class _RecordingRawDao:
    def __init__(self, model: type) -> None:
        self.model = model
        self.calls: list[tuple[list[dict], list[str] | None]] = []

    def bulk_upsert(self, rows: list[dict], conflict_columns=None):  # type: ignore[no-untyped-def]
        self.calls.append((rows, list(conflict_columns or []) or None))
        return len(rows)


@pytest.mark.parametrize(
    ("dataset_key", "raw_dao_name", "raw_model", "row", "target_table", "expected_conflict_columns"),
    (
        (
            "cyq_perf",
            "raw_cyq_perf",
            RawCyqPerf,
            {"ts_code": "000001.SZ", "trade_date": date(2026, 8, 3), "winner_rate": 0.5},
            "raw_tushare.cyq_perf",
            None,
        ),
        (
            "stk_nineturn",
            "raw_stk_nineturn",
            RawStkNineTurn,
            {"ts_code": "000001.SZ", "trade_date": date(2026, 8, 3), "freq": "daily"},
            "raw_tushare.stk_nineturn",
            None,
        ),
        (
            "dc_daily",
            "raw_dc_daily",
            RawDcDaily,
            {
                "ts_code": "BK1234.DC",
                "trade_date": date(2026, 8, 27),
                "category": "概念板块",
                "close": 100,
            },
            "raw_tushare.dc_daily",
            ["ts_code", "trade_date", "category"],
        ),
        (
            "moneyflow_cnt_ths",
            "raw_moneyflow_cnt_ths",
            RawMoneyflowCntThs,
            {
                "trade_date": date(2026, 8, 22),
                "ts_code": "885001.TI",
                "net_amount": 0,
            },
            "raw_tushare.moneyflow_cnt_ths",
            None,
        ),
        (
            "moneyflow_ind_dc",
            "raw_moneyflow_ind_dc",
            RawMoneyflowIndDc,
            {
                "trade_date": date(2026, 8, 22),
                "content_type": "概念",
                "name": "示例板块",
                "ts_code": "BK001.DC",
                "net_amount": 0,
            },
            "raw_tushare.moneyflow_ind_dc",
            None,
        ),
        (
            "moneyflow_ind_ths",
            "raw_moneyflow_ind_ths",
            RawMoneyflowIndThs,
            {
                "trade_date": date(2026, 8, 22),
                "ts_code": "881101.TI",
                "net_amount": 0,
            },
            "raw_tushare.moneyflow_ind_ths",
            None,
        ),
        (
            "moneyflow_mkt_dc",
            "raw_moneyflow_mkt_dc",
            RawMoneyflowMktDc,
            {
                "trade_date": date(2026, 8, 22),
                "net_amount": 0,
            },
            "raw_tushare.moneyflow_mkt_dc",
            None,
        ),
        (
            "margin",
            "raw_margin",
            RawMargin,
            {
                "trade_date": date(2026, 8, 22),
                "exchange_id": "SSE",
                "rzye": 0,
            },
            "raw_tushare.margin",
            None,
        ),
        (
            "suspend_d",
            "raw_suspend_d",
            RawSuspendD,
            {
                "id": 642264,
                "row_key_hash": "b" * 64,
                "ts_code": "000001.SZ",
                "trade_date": date(2026, 8, 27),
                "suspend_type": "S",
            },
            "raw_tushare.suspend_d",
            ["row_key_hash"],
        ),
        (
            "st",
            "raw_st",
            RawSt,
            {
                "ts_code": "300125.SZ",
                "pub_date": date(2026, 8, 12),
                "st_type": "风险警示",
                "row_key_hash": "a" * 64,
            },
            "core_serving_light.st",
            ["row_key_hash"],
        ),
    ),
)
def test_raw_serving_view_datasets_only_upsert_raw_table(
    mocker,
    dataset_key: str,
    raw_dao_name: str,
    raw_model: type,
    row: dict,
    target_table: str,
    expected_conflict_columns: list[str] | None,
) -> None:
    raw_dao = _RecordingRawDao(raw_model)
    mocker.patch(
        "src.foundation.ingestion.writer.DAOFactory",
        return_value=SimpleNamespace(**{raw_dao_name: raw_dao}),
    )
    definition = get_dataset_definition(dataset_key)
    batch = NormalizedBatch(
        unit_id=f"{dataset_key}-u1",
        rows_normalized=[row],
        rows_rejected=0,
        rejected_reasons={},
    )

    result = DatasetWriter(session=mocker.Mock()).write(definition=definition, batch=batch)

    assert definition.storage.core_dao_name == raw_dao_name
    assert raw_dao.calls == [(batch.rows_normalized, expected_conflict_columns)]
    assert result.target_table == target_table
    assert result.rows_written == 1
