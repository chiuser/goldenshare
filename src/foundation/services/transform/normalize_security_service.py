from __future__ import annotations

from typing import Any

from src.utils import coerce_row


class NormalizeSecurityService:
    def _normalize_tushare(self, row: dict[str, Any]) -> dict[str, Any]:
        normalized = coerce_row(dict(row), ["list_date", "delist_date"], [])
        normalized["security_type"] = "EQUITY"
        normalized["source"] = "tushare"
        return normalized

    def _normalize_biying(self, row: dict[str, Any]) -> dict[str, Any]:
        ts_code = (row.get("dm") or "").strip()
        if not ts_code:
            raise ValueError("missing dm")
        symbol = ts_code.split(".", 1)[0] if "." in ts_code else ts_code
        normalized: dict[str, Any] = {
            "ts_code": ts_code,
            "symbol": symbol,
            "name": (row.get("mc") or "").strip() or ts_code,
            "exchange": (row.get("jys") or "").strip() or None,
            "list_status": "L",
        }
        normalized["security_type"] = "EQUITY"
        normalized["source"] = "biying"
        return normalized

    def to_core(self, row: dict[str, Any], source_key: str = "tushare") -> dict[str, Any]:
        if source_key == "biying":
            return self._normalize_biying(row)
        return self._normalize_tushare(row)

    def to_std(self, row: dict[str, Any], source_key: str = "tushare") -> dict[str, Any]:
        normalized = self.to_core(row, source_key=source_key)
        normalized["source_key"] = source_key
        normalized["security_type"] = "EQUITY"
        return normalized
