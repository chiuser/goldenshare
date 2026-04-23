from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.foundation.services.sync_v2.contracts import FetchResult, RunRequest
from src.foundation.services.sync_v2.dataset_strategies.biying_moneyflow import build_biying_moneyflow_units
from src.foundation.services.sync_v2.errors import SyncV2ValidationError
from src.foundation.services.sync_v2.normalizer import SyncV2Normalizer
from src.foundation.services.sync_v2.registry import get_sync_v2_contract
from src.foundation.services.sync_v2.validator import ContractValidator


def _fake_session(stocks: list[tuple[str, str]]) -> SimpleNamespace:
    rows = [SimpleNamespace(dm=dm, mc=mc) for dm, mc in stocks]
    return SimpleNamespace(execute=lambda stmt: SimpleNamespace(all=lambda: rows))


def test_biying_moneyflow_point_incremental_requires_trade_date() -> None:
    contract = get_sync_v2_contract("biying_moneyflow")
    request = RunRequest(
        request_id="req-biying-moneyflow-missing-trade-date",
        dataset_key="biying_moneyflow",
        run_profile="point_incremental",
        trigger_source="test",
        params={},
    )

    with pytest.raises(SyncV2ValidationError) as exc_info:
        ContractValidator().validate(request, contract)
    assert exc_info.value.structured_error.error_code == "missing_anchor_fields"


def test_biying_moneyflow_range_rebuild_builds_units() -> None:
    contract = get_sync_v2_contract("biying_moneyflow")
    request = RunRequest(
        request_id="req-biying-moneyflow-range",
        dataset_key="biying_moneyflow",
        run_profile="range_rebuild",
        trigger_source="test",
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 10),
        params={"ts_code": "000001.SZ"},
    )
    validated = ContractValidator().validate(request, contract)
    units = build_biying_moneyflow_units(
        validated,
        contract,
        dao=None,
        settings=None,
        session=_fake_session([("000001", "平安银行")]),
    )

    assert len(units) == 1
    assert units[0].request_params == {
        "dm": "000001",
        "mc": "平安银行",
        "st": "20260401",
        "et": "20260410",
    }
    assert units[0].source_key == "biying"


def test_biying_moneyflow_normalizer_maps_fields_and_types() -> None:
    contract = get_sync_v2_contract("biying_moneyflow")
    batch = SyncV2Normalizer().normalize(
        contract=contract,
        fetch_result=FetchResult(
            unit_id="u-biying-moneyflow",
            request_count=1,
            retry_count=0,
            latency_ms=1,
            rows_raw=[
                {
                    "dm": "000001.SZ",
                    "mc": "平安银行",
                    "t": "2026-04-10 00:00:00",
                    "zmbzds": 2567,
                    "zmszds": 2113,
                    "dddx": "-5.3",
                    "zmbtdcje": "643556632.0",
                    "zmbtdcjl": 534893,
                    "zmbtdcjzlv": 534893,
                }
            ],
        ),
    )
    row = batch.rows_normalized[0]
    assert row["dm"] == "000001.SZ"
    assert row["trade_date"] == date(2026, 4, 10)
    assert row["mc"] == "平安银行"
    assert row["zmbzds"] == 2567
    assert row["dddx"] == Decimal("-5.3")
    assert row["zmbtdcje"] == Decimal("643556632.0")
    assert row["zmbtdcjl"] == 534893
    assert row["zmbtdcjzlv"] == 534893
