import csv
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from orchestrator.seeds.market import major_indices as seed_module


def _current_seed_rows() -> list[dict[str, str]]:
    rows = []
    for row in seed_module.load_major_indices_seed():
        rows.append(
            {
                "rank": str(row.rank),
                "ts_code": row.ts_code,
                "display_name": row.display_name or "",
                "effective_start_date": row.effective_start_date.isoformat(),
                "effective_end_date": row.effective_end_date.isoformat()
                if row.effective_end_date
                else "",
            }
        )
    return rows


def _write_seed_file(path: Path, rows: list[dict[str, str]], fieldnames=None) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames or seed_module.MAJOR_INDICES_SEED_COLUMNS,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


class MarketMajorIndicesSeedContractTests(unittest.TestCase):
    def tearDown(self) -> None:
        seed_module.load_major_indices_seed.cache_clear()

    def test_current_seed_file_has_expected_contract(self) -> None:
        seed_rows = seed_module.load_major_indices_seed()

        self.assertEqual(len(seed_rows), seed_module.EXPECTED_MAJOR_INDICES_COUNT)
        self.assertEqual(
            [row.rank for row in seed_rows],
            list(range(1, seed_module.EXPECTED_MAJOR_INDICES_COUNT + 1)),
        )
        self.assertEqual(len({row.ts_code for row in seed_rows}), len(seed_rows))
        for row in seed_rows:
            self.assertLessEqual(row.effective_start_date, row.effective_end_date or row.effective_start_date)

    def test_active_seed_rows_follow_effective_date_boundaries(self) -> None:
        expected_codes_by_trade_date = {
            "2000-01-03": (),
            "2000-01-04": ("000001.SH", "399001.SZ"),
            "2005-01-04": (
                "000001.SH",
                "399001.SZ",
                "000300.SH",
                "000905.SH",
                "000852.SH",
                "000016.SH",
            ),
            "2010-06-01": (
                "000001.SH",
                "399001.SZ",
                "399006.SZ",
                "000300.SH",
                "000905.SH",
                "000852.SH",
                "000016.SH",
            ),
            "2019-12-31": (
                "000001.SH",
                "399001.SZ",
                "399006.SZ",
                "000688.SH",
                "000300.SH",
                "000905.SH",
                "000852.SH",
                "000016.SH",
            ),
            "2022-12-19": (
                "000001.SH",
                "399001.SZ",
                "399006.SZ",
                "000688.SH",
                "000300.SH",
                "000905.SH",
                "000852.SH",
                "899050.BJ",
                "000016.SH",
            ),
            "2024-09-23": (
                "000001.SH",
                "399001.SZ",
                "399006.SZ",
                "000688.SH",
                "000300.SH",
                "000905.SH",
                "000852.SH",
                "899050.BJ",
                "000510.SH",
                "000016.SH",
            ),
        }

        for trade_date, expected_codes in expected_codes_by_trade_date.items():
            with self.subTest(trade_date=trade_date):
                rows = seed_module.active_major_indices_seed_rows(trade_date)
                self.assertEqual(tuple(row.ts_code for row in rows), expected_codes)

    def test_seed_loader_rejects_bad_header(self) -> None:
        rows = _current_seed_rows()
        self._assert_temp_seed_rejected(
            rows,
            expected_message="must use columns",
            fieldnames=("rank", "ts_code", "display_name"),
        )

    def test_seed_loader_rejects_duplicate_codes(self) -> None:
        rows = _current_seed_rows()
        rows[1]["ts_code"] = rows[0]["ts_code"]
        self._assert_temp_seed_rejected(rows, expected_message="duplicate ts_code")

    def test_seed_loader_rejects_rank_gaps(self) -> None:
        rows = _current_seed_rows()
        rows[1]["rank"] = "3"
        self._assert_temp_seed_rejected(rows, expected_message="ranks must be continuous")

    def test_seed_loader_rejects_invalid_dates(self) -> None:
        rows = _current_seed_rows()
        rows[0]["effective_start_date"] = "not-a-date"
        self._assert_temp_seed_rejected(rows, expected_message="must use YYYY-MM-DD")

    def test_seed_loader_rejects_end_date_before_start_date(self) -> None:
        rows = _current_seed_rows()
        rows[0]["effective_end_date"] = "1999-01-01"
        self._assert_temp_seed_rejected(
            rows,
            expected_message="effective_end_date earlier",
        )

    def _assert_temp_seed_rejected(
        self,
        rows: list[dict[str, str]],
        *,
        expected_message: str,
        fieldnames=None,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            seed_path = Path(temp_dir) / "major_indices.cn_a.csv"
            _write_seed_file(seed_path, rows, fieldnames=fieldnames)
            seed_module.load_major_indices_seed.cache_clear()
            with mock.patch.object(seed_module, "MAJOR_INDICES_SEED_PATH", seed_path):
                with self.assertRaisesRegex(RuntimeError, expected_message):
                    seed_module.load_major_indices_seed()
            seed_module.load_major_indices_seed.cache_clear()


if __name__ == "__main__":
    unittest.main()
