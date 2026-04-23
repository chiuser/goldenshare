from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.foundation.services.sync_v2.contracts import FetchResult, RunRequest
from src.foundation.services.sync_v2.dataset_strategies.moneyflow import build_moneyflow_units
from src.foundation.services.sync_v2.errors import SyncV2NormalizeError
from src.foundation.services.sync_v2.normalizer import SyncV2Normalizer
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator


def test_moneyflow_point_incremental_builds_trade_date_unit() -> None:
    contract = get_sync_v2_contract("moneyflow")
    request = RunRequest(
        request_id="req-moneyflow-point",
        dataset_key="moneyflow",
        run_profile="point_incremental",
        trigger_source="test",
        trade_date=date(2026, 4, 16),
        params={"ts_code": "000001.SZ"},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_moneyflow_units(validated, contract, dao=None, settings=None, session=None)

    assert len(units) == 1
    assert units[0].request_params == {"trade_date": "20260416", "ts_code": "000001.SZ"}
    assert units[0].pagination_policy == "offset_limit"
    assert units[0].page_limit == 6000


def test_moneyflow_normalizer_coerces_volume_and_amount_fields() -> None:
    contract = get_sync_v2_contract("moneyflow")
    batch = SyncV2Normalizer().normalize(
        contract=contract,
        fetch_result=FetchResult(
            unit_id="u-moneyflow",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "2026-04-16",
                    "buy_sm_vol": "1",
                    "buy_sm_amount": "2",
                    "sell_sm_vol": "3",
                    "sell_sm_amount": "4",
                    "buy_md_vol": "5",
                    "buy_md_amount": "6",
                    "sell_md_vol": "7",
                    "sell_md_amount": "8",
                    "buy_lg_vol": "9",
                    "buy_lg_amount": "10",
                    "sell_lg_vol": "11",
                    "sell_lg_amount": "12",
                    "buy_elg_vol": "13",
                    "buy_elg_amount": "14",
                    "sell_elg_vol": "15",
                    "sell_elg_amount": "16",
                    "net_mf_vol": "17",
                    "net_mf_amount": "18",
                }
            ],
        ),
    )

    assert batch.rows_rejected == 0
    row = batch.rows_normalized[0]
    assert row["trade_date"] == date(2026, 4, 16)
    assert row["buy_sm_vol"] == 1
    assert row["sell_sm_vol"] == 3
    assert row["net_mf_vol"] == 17
    assert row["net_mf_amount"] == Decimal("18")


def test_moneyflow_normalizer_rejects_fractional_volume() -> None:
    contract = get_sync_v2_contract("moneyflow")
    batch = SyncV2Normalizer().normalize(
        contract=contract,
        fetch_result=FetchResult(
            unit_id="u-moneyflow-invalid",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "ts_code": "000001.SZ",
                    "trade_date": "2026-04-16",
                    "buy_sm_vol": "1.5",
                    "buy_sm_amount": "2",
                    "sell_sm_vol": "3",
                    "sell_sm_amount": "4",
                    "buy_md_vol": "5",
                    "buy_md_amount": "6",
                    "sell_md_vol": "7",
                    "sell_md_amount": "8",
                    "buy_lg_vol": "9",
                    "buy_lg_amount": "10",
                    "sell_lg_vol": "11",
                    "sell_lg_amount": "12",
                    "buy_elg_vol": "13",
                    "buy_elg_amount": "14",
                    "sell_elg_vol": "15",
                    "sell_elg_amount": "16",
                    "net_mf_vol": "17",
                    "net_mf_amount": "18",
                }
            ],
        ),
    )

    assert batch.rows_normalized == []
    assert batch.rows_rejected == 1
    assert batch.rejected_reasons == {"normalize.row_transform_failed": 1}
    try:
        SyncV2Normalizer.raise_if_all_rejected(batch)
        assert False, "expected SyncV2NormalizeError"
    except SyncV2NormalizeError as exc:
        assert exc.structured_error.error_code == "all_rows_rejected"
