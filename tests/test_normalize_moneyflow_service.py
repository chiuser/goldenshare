from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.foundation.services.transform.normalize_moneyflow_service import NormalizeMoneyflowService


def test_normalize_moneyflow_service_maps_tushare_to_std() -> None:
    service = NormalizeMoneyflowService()
    row = {
        "ts_code": "000001.SZ",
        "trade_date": date(2026, 4, 16),
        "buy_sm_vol": Decimal("1"),
        "buy_sm_amount": Decimal("2"),
        "sell_sm_vol": Decimal("3"),
        "sell_sm_amount": Decimal("4"),
        "buy_md_vol": Decimal("5"),
        "buy_md_amount": Decimal("6"),
        "sell_md_vol": Decimal("7"),
        "sell_md_amount": Decimal("8"),
        "buy_lg_vol": Decimal("9"),
        "buy_lg_amount": Decimal("10"),
        "sell_lg_vol": Decimal("11"),
        "sell_lg_amount": Decimal("12"),
        "buy_elg_vol": Decimal("13"),
        "buy_elg_amount": Decimal("14"),
        "sell_elg_vol": Decimal("15"),
        "sell_elg_amount": Decimal("16"),
        "net_mf_vol": Decimal("17"),
        "net_mf_amount": Decimal("18"),
    }

    std_row = service.to_std_from_tushare(row)

    assert std_row["source_key"] == "tushare"
    assert std_row["ts_code"] == "000001.SZ"
    assert std_row["trade_date"] == date(2026, 4, 16)
    assert std_row["net_mf_amount"] == Decimal("18")


def test_normalize_moneyflow_service_maps_biying_to_std_and_computes_net() -> None:
    service = NormalizeMoneyflowService()
    row = {
        "dm": "000001",
        "trade_date": date(2026, 4, 16),
        "zmbxdcjl": 10,
        "zmbzdcjl": 20,
        "zmbddcjl": 30,
        "zmbtdcjl": 40,
        "zmsxdcjl": 2,
        "zmszdcjl": 3,
        "zmsddcjl": 4,
        "zmstdcjl": 5,
        "zmbxdcje": Decimal("100"),
        "zmbzdcje": Decimal("200"),
        "zmbddcje": Decimal("300"),
        "zmbtdcje": Decimal("400"),
        "zmsxdcje": Decimal("10"),
        "zmszdcje": Decimal("20"),
        "zmsddcje": Decimal("30"),
        "zmstdcje": Decimal("40"),
    }

    std_row = service.to_std_from_biying_raw(row)

    assert std_row["source_key"] == "biying"
    assert std_row["ts_code"] == "000001.SZ"
    assert std_row["trade_date"] == date(2026, 4, 16)
    assert std_row["buy_elg_amount"] == Decimal("400")
    assert std_row["sell_elg_amount"] == Decimal("40")
    assert std_row["net_mf_vol"] == Decimal("86")
    assert std_row["net_mf_amount"] == Decimal("900")
