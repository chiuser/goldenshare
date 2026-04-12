from __future__ import annotations

from typing import Any

from src.foundation.normalization.base import NormalizationError, normalize_rows_with_isolation
from src.utils import coerce_row


class EquityDailyBasicNormalizer:
    date_fields = ("trade_date",)
    decimal_fields = (
        "close",
        "turnover_rate",
        "turnover_rate_f",
        "volume_ratio",
        "pe",
        "pe_ttm",
        "pb",
        "ps",
        "ps_ttm",
        "dv_ratio",
        "dv_ttm",
        "total_share",
        "float_share",
        "free_share",
        "total_mv",
        "circ_mv",
    )
    required_fields = ("ts_code", "trade_date")

    def normalize_row(self, row: dict[str, Any], source_key: str) -> dict[str, Any]:
        normalized = coerce_row(dict(row), self.date_fields, self.decimal_fields)
        missing = [field for field in self.required_fields if normalized.get(field) in (None, "")]
        if missing:
            raise ValueError(f"missing required fields: {', '.join(missing)}")
        normalized["source_key"] = source_key
        return normalized

    def normalize_rows(
        self, rows: list[dict[str, Any]], source_key: str
    ) -> tuple[list[dict[str, Any]], list[NormalizationError]]:
        return normalize_rows_with_isolation(rows, self.normalize_row, source_key)
