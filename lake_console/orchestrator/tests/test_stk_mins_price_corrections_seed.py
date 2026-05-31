import csv
import tempfile
import unittest
from datetime import date, time
from pathlib import Path
from unittest import mock

from orchestrator.seeds.quote import stk_mins_price_corrections as seed_module


def _current_seed_rows() -> list[dict[str, str]]:
    return [
        {
            "freq": str(row.freq),
            "trade_date": row.trade_date.isoformat(),
            "ts_code": row.ts_code,
            "trade_time": row.trade_time.isoformat(),
            "open": f"{row.open:.2f}",
            "high": f"{row.high:.2f}",
            "low": f"{row.low:.2f}",
            "close": f"{row.close:.2f}",
            "reason": row.reason,
        }
        for row in seed_module.load_stk_mins_price_correction_catalog().rows
    ]


def _write_seed_file(
    path: Path,
    rows: list[dict[str, str]],
    *,
    fieldnames=None,
) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames or seed_module.STK_MINS_PRICE_CORRECTIONS_SEED_COLUMNS,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


class StkMinsPriceCorrectionSeedTests(unittest.TestCase):
    def tearDown(self) -> None:
        seed_module.load_stk_mins_price_correction_catalog.cache_clear()

    def test_current_seed_loads_expected_rows(self) -> None:
        catalog = seed_module.load_stk_mins_price_correction_catalog()

        self.assertEqual(len(catalog.rows), 5)
        self.assertEqual(
            frozenset(row.trade_date.isoformat() for row in catalog.rows),
            seed_module.STK_MINS_PRICE_CORRECTION_DATES,
        )
        self.assertEqual(
            catalog.corrections_for_partition(freq=1, trade_date="2014-06-03"),
            tuple(row for row in catalog.rows if row.trade_date == date(2014, 6, 3)),
        )
        self.assertEqual(
            catalog.corrections_for_partition(freq=5, trade_date="2014-06-03"),
            (),
        )

    def test_daily_guard_does_not_load_catalog(self) -> None:
        with mock.patch.object(
            seed_module,
            "load_stk_mins_price_correction_catalog",
            side_effect=AssertionError("catalog should not be loaded"),
        ):
            self.assertFalse(seed_module.has_stk_mins_price_corrections("2026-05-29"))
            self.assertTrue(seed_module.has_stk_mins_price_corrections(date(2014, 6, 3)))

    def test_catalog_is_cached(self) -> None:
        seed_module.load_stk_mins_price_correction_catalog.cache_clear()
        catalog_one = seed_module.load_stk_mins_price_correction_catalog()
        catalog_two = seed_module.load_stk_mins_price_correction_catalog()

        self.assertIs(catalog_one, catalog_two)

    def test_loader_rejects_bad_header(self) -> None:
        rows = _current_seed_rows()
        self._assert_temp_seed_rejected(
            rows,
            expected_message="columns must be exactly",
            fieldnames=("freq", "trade_date", "ts_code"),
        )

    def test_loader_rejects_non_1m_frequency(self) -> None:
        rows = _current_seed_rows()
        rows[0]["freq"] = "5"
        self._assert_temp_seed_rejected(rows, expected_message="only supports freq=1")

    def test_loader_rejects_duplicate_business_key(self) -> None:
        rows = _current_seed_rows()
        rows[1]["trade_date"] = rows[0]["trade_date"]
        rows[1]["ts_code"] = rows[0]["ts_code"]
        rows[1]["trade_time"] = rows[0]["trade_time"]
        self._assert_temp_seed_rejected(rows, expected_message="business keys must be unique")

    def test_loader_rejects_invalid_date_or_time(self) -> None:
        rows = _current_seed_rows()
        rows[0]["trade_date"] = "not-a-date"
        self._assert_temp_seed_rejected(rows, expected_message="invalid trade_date")

        rows = _current_seed_rows()
        rows[0]["trade_time"] = "not-a-time"
        self._assert_temp_seed_rejected(rows, expected_message="invalid trade_time")

    def test_loader_rejects_non_positive_prices(self) -> None:
        rows = _current_seed_rows()
        rows[0]["low"] = "0"
        self._assert_temp_seed_rejected(rows, expected_message="non-positive low")

    def test_loader_rejects_bad_price_relation(self) -> None:
        rows = _current_seed_rows()
        rows[0]["high"] = "7.40"
        self._assert_temp_seed_rejected(rows, expected_message="high below low")

        rows = _current_seed_rows()
        rows[0]["open"] = "7.60"
        self._assert_temp_seed_rejected(rows, expected_message="open outside")

        rows = _current_seed_rows()
        rows[0]["close"] = "7.60"
        self._assert_temp_seed_rejected(rows, expected_message="close outside")

    def test_loader_rejects_date_constant_drift(self) -> None:
        rows = _current_seed_rows()
        rows[0]["trade_date"] = "2014-06-04"
        self._assert_temp_seed_rejected(rows, expected_message="must match seed trade_date")

    def test_catalog_returns_current_partition_only(self) -> None:
        catalog = seed_module.load_stk_mins_price_correction_catalog()

        correction = catalog.corrections_for_partition(
            freq=1,
            trade_date=date(2014, 12, 22),
        )

        self.assertEqual(len(correction), 1)
        self.assertEqual(correction[0].ts_code, "600062.SH")
        self.assertEqual(correction[0].trade_time, time(9, 34))
        self.assertEqual(correction[0].low, 20.77)

    def _assert_temp_seed_rejected(
        self,
        rows: list[dict[str, str]],
        *,
        expected_message: str,
        fieldnames=None,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            seed_path = Path(temp_dir) / "stk_mins_price_corrections.cn_a.csv"
            _write_seed_file(seed_path, rows, fieldnames=fieldnames)
            seed_module.load_stk_mins_price_correction_catalog.cache_clear()
            with self.assertRaisesRegex(ValueError, expected_message):
                seed_module.load_stk_mins_price_correction_catalog(seed_path)


if __name__ == "__main__":
    unittest.main()
