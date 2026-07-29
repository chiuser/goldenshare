import unittest

from orchestrator.defs.run_contracts.asset_column_schemas import (
    RAW_INDEX_MINS_SCHEMA,
    SILVER_INDEX_MINS_SCHEMA,
)
from orchestrator.defs.run_contracts.index_mins import (
    INDEX_MINS_ASSET_FREQS,
    INDEX_MINS_SOURCE_COLUMNS,
    INDEX_MINS_SOURCE_FREQS,
    asset_freq_for_index_mins_source_freq,
    index_mins_derived_windows,
    index_mins_code_set_hash,
    index_mins_trade_date_window,
    normalize_index_mins_asset_freq,
    normalize_index_mins_code,
    normalize_index_mins_codes,
    normalize_index_mins_source_freq,
    normalize_index_mins_silver_freq,
    source_freq_for_index_mins_derived_freq,
    source_freq_for_index_mins_asset_freq,
)


class IndexMinsContractTests(unittest.TestCase):
    def test_frequency_mapping_is_bijective(self) -> None:
        self.assertEqual(len(INDEX_MINS_ASSET_FREQS), 5)
        self.assertEqual(len(INDEX_MINS_SOURCE_FREQS), 5)
        for asset_freq, source_freq in zip(
            INDEX_MINS_ASSET_FREQS,
            INDEX_MINS_SOURCE_FREQS,
            strict=True,
        ):
            self.assertEqual(source_freq_for_index_mins_asset_freq(asset_freq), source_freq)
            self.assertEqual(asset_freq_for_index_mins_source_freq(source_freq), asset_freq)

    def test_invalid_frequency_and_code_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_index_mins_source_freq("2min")
        with self.assertRaises(ValueError):
            normalize_index_mins_asset_freq(True)
        with self.assertRaises(ValueError):
            normalize_index_mins_code("not-a-code")
        with self.assertRaises(ValueError):
            normalize_index_mins_codes(("000001.SH", "000001.SH"), reject_duplicates=True)

    def test_silver_frequency_and_derived_window_contract_is_centralized(self) -> None:
        self.assertEqual(normalize_index_mins_silver_freq(90), "90min")
        self.assertEqual(normalize_index_mins_silver_freq("120min"), "120min")
        self.assertEqual(source_freq_for_index_mins_derived_freq(90), "30min")
        self.assertEqual(source_freq_for_index_mins_derived_freq(120), "60min")
        self.assertEqual(len(index_mins_derived_windows(90)), 8)
        self.assertEqual(len(index_mins_derived_windows(120)), 4)
        with self.assertRaises(ValueError):
            source_freq_for_index_mins_derived_freq(60)

    def test_code_hash_is_sorted_and_sha256(self) -> None:
        first = index_mins_code_set_hash(("399001.SZ", "000001.SH"))
        second = index_mins_code_set_hash(("000001.SH", "399001.SZ"))
        self.assertEqual(first, second)
        self.assertEqual(len(first), 64)

    def test_date_window_is_one_day_and_half_open(self) -> None:
        start, end = index_mins_trade_date_window("2026-07-28")
        self.assertEqual(start.isoformat(sep=" "), "2026-07-28 00:00:00")
        self.assertEqual(end.isoformat(sep=" "), "2026-07-29 00:00:00")

    def test_source_and_silver_schema_have_same_eleven_columns(self) -> None:
        source_columns = tuple(contract.name for contract in RAW_INDEX_MINS_SCHEMA)
        silver_columns = tuple(contract.name for contract in SILVER_INDEX_MINS_SCHEMA)
        self.assertEqual(source_columns, INDEX_MINS_SOURCE_COLUMNS)
        self.assertEqual(silver_columns, INDEX_MINS_SOURCE_COLUMNS)
        self.assertNotIn("trade_date", source_columns)


if __name__ == "__main__":
    unittest.main()
