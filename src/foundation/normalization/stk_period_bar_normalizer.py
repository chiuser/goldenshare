from __future__ import annotations

from typing import Any

from src.foundation.normalization.base import NormalizationError, normalize_rows_with_isolation
from src.utils import coerce_row


class StkPeriodBarNormalizer:
    date_fields = ("trade_date", "end_date")
    decimal_fields = ("open", "high", "low", "close", "pre_close", "vol", "amount", "change_amount", "pct_chg")
    required_fields = ("ts_code", "trade_date", "freq")

    def normalize_row(self, row: dict[str, Any], source_key: str) -> dict[str, Any]:
        normalized = dict(row)
        if "change_amount" not in normalized and "change" in normalized:
            normalized["change_amount"] = normalized.pop("change")
        normalized = coerce_row(normalized, self.date_fields, self.decimal_fields)
        missing = [field for field in self.required_fields if normalized.get(field) in (None, "")]
        if missing:
            raise ValueError(f"missing required fields: {', '.join(missing)}")
        normalized["source_key"] = source_key
        return normalized

    def normalize_rows(
        self, rows: list[dict[str, Any]], source_key: str
    ) -> tuple[list[dict[str, Any]], list[NormalizationError]]:
        return normalize_rows_with_isolation(rows, self.normalize_row, source_key)


class StkPeriodBarAdjNormalizer:
    date_fields = ("trade_date", "end_date")
    decimal_fields = (
        "open",
        "high",
        "low",
        "close",
        "pre_close",
        "open_qfq",
        "high_qfq",
        "low_qfq",
        "close_qfq",
        "open_hfq",
        "high_hfq",
        "low_hfq",
        "close_hfq",
        "vol",
        "amount",
        "change_amount",
        "pct_chg",
    )
    required_fields = ("ts_code", "trade_date", "freq")

    def normalize_row(self, row: dict[str, Any], source_key: str) -> dict[str, Any]:
        normalized = dict(row)
        if "change_amount" not in normalized and "change" in normalized:
            normalized["change_amount"] = normalized.pop("change")
        normalized = coerce_row(normalized, self.date_fields, self.decimal_fields)
        missing = [field for field in self.required_fields if normalized.get(field) in (None, "")]
        if missing:
            raise ValueError(f"missing required fields: {', '.join(missing)}")
        normalized["source_key"] = source_key
        return normalized

    def normalize_rows(
        self, rows: list[dict[str, Any]], source_key: str
    ) -> tuple[list[dict[str, Any]], list[NormalizationError]]:
        return normalize_rows_with_isolation(rows, self.normalize_row, source_key)
