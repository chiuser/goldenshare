from __future__ import annotations

from typing import Any

from src.utils import coerce_row


class NormalizeSecurityService:
    def to_core(self, row: dict[str, Any]) -> dict[str, Any]:
        normalized = coerce_row(row, ["list_date", "delist_date"], [])
        normalized["security_type"] = "EQUITY"
        normalized["source"] = "tushare"
        return normalized
