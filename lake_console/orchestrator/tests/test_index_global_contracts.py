import unittest

from orchestrator.defs.run_contracts.index_global import (
    INDEX_GLOBAL_EXPECTED_CODES,
    INDEX_GLOBAL_FIELDS,
    IndexGlobalRawValidationError,
    normalize_index_global_numeric_values,
    normalize_index_global_trade_date,
    validate_index_global_phase_rows,
)


def _row(code: str = "XIN9", trade_date: str = "20220104") -> dict[str, object]:
    return {
        "ts_code": code,
        "trade_date": trade_date,
        "open": 1.0,
        "close": 1.0,
        "high": 1.0,
        "low": 1.0,
        "pre_close": 1.0,
        "change": 0.0,
        "pct_chg": 0.0,
        "swing": 0.0,
        "vol": 1.0,
        "amount": None,
    }


class IndexGlobalContractTests(unittest.TestCase):
    def test_contract_has_fixed_source_fields_and_identity_bound(self) -> None:
        self.assertEqual(len(INDEX_GLOBAL_FIELDS), 12)
        self.assertEqual(INDEX_GLOBAL_FIELDS[:2], ("ts_code", "trade_date"))
        self.assertEqual(len(INDEX_GLOBAL_EXPECTED_CODES), 22)
        self.assertIn("HSHKCI", INDEX_GLOBAL_EXPECTED_CODES)

    def test_trade_date_normalizes_iso_and_raw_forms(self) -> None:
        self.assertEqual(normalize_index_global_trade_date("20220104"), "2022-01-04")
        self.assertEqual(normalize_index_global_trade_date("2022-01-04"), "2022-01-04")

    def test_phase_rows_are_normalized_without_changing_source_fields(self) -> None:
        rows = validate_index_global_phase_rows(
            [_row("HSHKCI")], trade_date="2022-01-04", probe_phase="asia_1"
        )
        self.assertEqual(rows[0]["ts_code"], "HSHKCI")
        self.assertEqual(rows[0]["trade_date"], "20220104")
        self.assertEqual(set(rows[0]), set(INDEX_GLOBAL_FIELDS))

    def test_unknown_code_duplicate_and_column_drift_fail_closed(self) -> None:
        with self.assertRaises(IndexGlobalRawValidationError):
            validate_index_global_phase_rows(
                [_row("UNKNOWN")], trade_date="2022-01-04", probe_phase="asia_1"
            )
        with self.assertRaises(IndexGlobalRawValidationError):
            validate_index_global_phase_rows(
                [_row(), _row()], trade_date="2022-01-04", probe_phase="asia_1"
            )
        drifted = _row()
        drifted.pop("amount")
        with self.assertRaises(IndexGlobalRawValidationError):
            validate_index_global_phase_rows(
                [drifted], trade_date="2022-01-04", probe_phase="asia_1"
            )

    def test_row_count_is_bounded_by_fixed_identity_set(self) -> None:
        rows = [_row(code) for code in INDEX_GLOBAL_EXPECTED_CODES]
        validate_index_global_phase_rows(
            rows, trade_date="2022-01-04", probe_phase="asia_1"
        )
        with self.assertRaises(IndexGlobalRawValidationError):
            validate_index_global_phase_rows(
                rows + [_row("XIN9")], trade_date="2022-01-04", probe_phase="asia_1"
            )

    def test_source_nan_is_normalized_to_parquet_null(self) -> None:
        row = _row()
        row["amount"] = float("nan")
        normalized = normalize_index_global_numeric_values(row)
        self.assertIsNone(normalized["amount"])
