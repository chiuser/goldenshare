from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any


class NormalizeMoneyflowService:
    _BUY_VOL_FIELDS = ("zmbxdcjl", "zmbzdcjl", "zmbddcjl", "zmbtdcjl")
    _SELL_VOL_FIELDS = ("zmsxdcjl", "zmszdcjl", "zmsddcjl", "zmstdcjl")
    _BUY_AMOUNT_FIELDS = ("zmbxdcje", "zmbzdcje", "zmbddcje", "zmbtdcje")
    _SELL_AMOUNT_FIELDS = ("zmsxdcje", "zmszdcje", "zmsddcje", "zmstdcje")

    @classmethod
    def normalize_dm_to_ts_code(cls, dm: str | None) -> str:
        raw = (dm or "").strip().upper()
        if not raw:
            raise ValueError("missing dm")
        if "." in raw:
            return raw
        if len(raw) == 6:
            if raw.startswith(("6", "9")):
                return f"{raw}.SH"
            if raw.startswith(("4", "8")):
                return f"{raw}.BJ"
            return f"{raw}.SZ"
        return raw

    def to_std_from_tushare(self, row: dict[str, Any]) -> dict[str, Any]:
        ts_code = (row.get("ts_code") or "").strip().upper()
        if not ts_code:
            raise ValueError("missing ts_code")
        trade_date = row.get("trade_date")
        if not isinstance(trade_date, date):
            raise ValueError("missing trade_date")
        return {
            "source_key": "tushare",
            "ts_code": ts_code,
            "trade_date": trade_date,
            "buy_sm_vol": self._to_int(row.get("buy_sm_vol")),
            "buy_sm_amount": self._to_decimal(row.get("buy_sm_amount")),
            "sell_sm_vol": self._to_int(row.get("sell_sm_vol")),
            "sell_sm_amount": self._to_decimal(row.get("sell_sm_amount")),
            "buy_md_vol": self._to_int(row.get("buy_md_vol")),
            "buy_md_amount": self._to_decimal(row.get("buy_md_amount")),
            "sell_md_vol": self._to_int(row.get("sell_md_vol")),
            "sell_md_amount": self._to_decimal(row.get("sell_md_amount")),
            "buy_lg_vol": self._to_int(row.get("buy_lg_vol")),
            "buy_lg_amount": self._to_decimal(row.get("buy_lg_amount")),
            "sell_lg_vol": self._to_int(row.get("sell_lg_vol")),
            "sell_lg_amount": self._to_decimal(row.get("sell_lg_amount")),
            "buy_elg_vol": self._to_int(row.get("buy_elg_vol")),
            "buy_elg_amount": self._to_decimal(row.get("buy_elg_amount")),
            "sell_elg_vol": self._to_int(row.get("sell_elg_vol")),
            "sell_elg_amount": self._to_decimal(row.get("sell_elg_amount")),
            "net_mf_vol": self._to_int(row.get("net_mf_vol")),
            "net_mf_amount": self._to_decimal(row.get("net_mf_amount")),
        }

    def to_std_from_biying_raw(self, row: dict[str, Any]) -> dict[str, Any]:
        ts_code = self.normalize_dm_to_ts_code(row.get("dm"))
        trade_date = row.get("trade_date")
        if not isinstance(trade_date, date):
            raise ValueError("missing trade_date")

        buy_sm_vol = self._to_int(row.get("zmbxdcjl"))
        buy_sm_amount = self._to_decimal(row.get("zmbxdcje"))
        sell_sm_vol = self._to_int(row.get("zmsxdcjl"))
        sell_sm_amount = self._to_decimal(row.get("zmsxdcje"))
        buy_md_vol = self._to_int(row.get("zmbzdcjl"))
        buy_md_amount = self._to_decimal(row.get("zmbzdcje"))
        sell_md_vol = self._to_int(row.get("zmszdcjl"))
        sell_md_amount = self._to_decimal(row.get("zmszdcje"))
        buy_lg_vol = self._to_int(row.get("zmbddcjl"))
        buy_lg_amount = self._to_decimal(row.get("zmbddcje"))
        sell_lg_vol = self._to_int(row.get("zmsddcjl"))
        sell_lg_amount = self._to_decimal(row.get("zmsddcje"))
        buy_elg_vol = self._to_int(row.get("zmbtdcjl"))
        buy_elg_amount = self._to_decimal(row.get("zmbtdcje"))
        sell_elg_vol = self._to_int(row.get("zmstdcjl"))
        sell_elg_amount = self._to_decimal(row.get("zmstdcje"))

        net_mf_vol = self._subtract_int(
            self._sum_int(self._to_int(row.get(field)) for field in self._BUY_VOL_FIELDS),
            self._sum_int(self._to_int(row.get(field)) for field in self._SELL_VOL_FIELDS),
        )
        net_mf_amount = self._subtract(
            self._sum(self._to_decimal(row.get(field)) for field in self._BUY_AMOUNT_FIELDS),
            self._sum(self._to_decimal(row.get(field)) for field in self._SELL_AMOUNT_FIELDS),
        )

        return {
            "source_key": "biying",
            "ts_code": ts_code,
            "trade_date": trade_date,
            "buy_sm_vol": buy_sm_vol,
            "buy_sm_amount": buy_sm_amount,
            "sell_sm_vol": sell_sm_vol,
            "sell_sm_amount": sell_sm_amount,
            "buy_md_vol": buy_md_vol,
            "buy_md_amount": buy_md_amount,
            "sell_md_vol": sell_md_vol,
            "sell_md_amount": sell_md_amount,
            "buy_lg_vol": buy_lg_vol,
            "buy_lg_amount": buy_lg_amount,
            "sell_lg_vol": sell_lg_vol,
            "sell_lg_amount": sell_lg_amount,
            "buy_elg_vol": buy_elg_vol,
            "buy_elg_amount": buy_elg_amount,
            "sell_elg_vol": sell_elg_vol,
            "sell_elg_amount": sell_elg_amount,
            "net_mf_vol": net_mf_vol,
            "net_mf_amount": net_mf_amount,
        }

    @staticmethod
    def _to_decimal(value: Any) -> Decimal | None:
        if value is None or value == "":
            return None
        return Decimal(str(value))

    @staticmethod
    def _to_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        decimal_value = Decimal(str(value))
        if decimal_value != decimal_value.to_integral_value():
            raise ValueError(f"值必须是整数格式，实际值：{value}")
        return int(decimal_value)

    @staticmethod
    def _sum(values: Any) -> Decimal | None:
        total = Decimal("0")
        seen = False
        for value in values:
            if value is None:
                continue
            total += value
            seen = True
        return total if seen else None

    @staticmethod
    def _subtract(left: Decimal | None, right: Decimal | None) -> Decimal | None:
        if left is None and right is None:
            return None
        return (left or Decimal("0")) - (right or Decimal("0"))

    @staticmethod
    def _sum_int(values: Any) -> int | None:
        total = 0
        seen = False
        for value in values:
            if value is None:
                continue
            total += int(value)
            seen = True
        return total if seen else None

    @staticmethod
    def _subtract_int(left: int | None, right: int | None) -> int | None:
        if left is None and right is None:
            return None
        return (left or 0) - (right or 0)
