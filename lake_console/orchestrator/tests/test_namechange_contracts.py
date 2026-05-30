from datetime import date
from pathlib import Path
import tempfile
import unittest

import duckdb

from orchestrator.defs.assets.namechange import NAMECHANGE_RAW_COLUMN_TYPES
from orchestrator.defs.duckdb_sql import NAMECHANGE_RAW_COLUMNS
from orchestrator.defs.namechange_timeline import (
    build_latest_announcement_namechange_timeline,
)
from orchestrator.defs.resources import DuckDBResource, TushareResult
from orchestrator.defs.tushare_api_io import fetch_tushare_full_file_distinct_to_raw


class FakeTushareResource:
    def __init__(self, rows):
        self._rows = rows

    def call(self, api_name, params, fields):
        self.last_api_name = api_name
        self.last_params = dict(params)
        return TushareResult(
            rows=list(self._rows),
            columns=tuple(fields),
            metadata={},
        )


class NamechangeContractTests(unittest.TestCase):
    def test_raw_full_snapshot_helper_removes_exact_duplicates(self) -> None:
        rows = [
            {
                "ts_code": "000001.SZ",
                "name": "平安银行",
                "start_date": "19910403",
                "end_date": None,
                "ann_date": None,
                "change_reason": "其他",
            },
            {
                "ts_code": "000001.SZ",
                "name": "平安银行",
                "start_date": "19910403",
                "end_date": None,
                "ann_date": None,
                "change_reason": "其他",
            },
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            target_path = Path(tmpdir) / "part-000.parquet"
            metadata = fetch_tushare_full_file_distinct_to_raw(
                tushare=FakeTushareResource(rows),
                duckdb=DuckDBResource(),
                api_name="namechange",
                api_params={},
                fields=NAMECHANGE_RAW_COLUMNS,
                column_types=NAMECHANGE_RAW_COLUMN_TYPES,
                target_path=target_path,
                allow_empty=False,
            )
            with duckdb.connect(database=":memory:") as connection:
                row_count = connection.execute(
                    f"SELECT count(*) FROM read_parquet('{target_path.as_posix()}')"
                ).fetchone()[0]

        self.assertEqual(row_count, 1)
        self.assertEqual(metadata["dagster/row_count"], 1)
        self.assertEqual(metadata["goldenshare/source_row_count"], 2)
        self.assertEqual(metadata["goldenshare/duplicate_removed_count"], 1)

    def test_latest_announcement_timeline_handles_huangtai(self) -> None:
        result = build_latest_announcement_namechange_timeline(
            [
                _row("000995.SZ", "*ST皇台", "20180503", "20201215", "20180428"),
                _row("000995.SZ", "皇台酒业", "20201216", None, "20201215"),
                _row("000995.SZ", "皇台酒业", "20201216", "20220428", "20220428"),
                _row("000995.SZ", "*ST皇台", "20220429", None, "20220428"),
                _row("000995.SZ", "*ST皇台", "20220429", "20230817", "20230817"),
                _row("000995.SZ", "皇台酒业", "20230818", None, "20230817"),
            ]
        )

        self.assertEqual(result.blocking_conflict_count, 0)
        self.assertEqual(
            [
                (row["name"], row["start_date"], row["end_date"])
                for row in result.rows
            ],
            [
                ("*ST皇台", date(2018, 5, 3), date(2020, 12, 15)),
                ("皇台酒业", date(2020, 12, 16), date(2022, 4, 28)),
                ("*ST皇台", date(2022, 4, 29), date(2023, 8, 17)),
                ("皇台酒业", date(2023, 8, 18), None),
            ],
        )

    def test_same_start_same_announcement_unresolved_conflict_is_reported(self) -> None:
        result = build_latest_announcement_namechange_timeline(
            [
                _row("000001.SZ", "名称A", "20200101", "20200131", "20200101"),
                _row("000001.SZ", "名称B", "20200101", "20200131", "20200101"),
            ]
        )

        self.assertEqual(result.unresolved_conflict_count, 1)
        self.assertGreater(result.blocking_conflict_count, 0)

    def test_open_interval_is_closed_by_next_start_to_avoid_overlap(self) -> None:
        result = build_latest_announcement_namechange_timeline(
            [
                _row("000001.SZ", "名称A", "20200101", None, "20200101"),
                _row("000001.SZ", "名称B", "20200110", None, "20200109"),
            ]
        )

        self.assertEqual(result.blocking_conflict_count, 0)
        self.assertEqual(result.rows[0]["end_date"], date(2020, 1, 9))
        self.assertEqual(result.overlap_count, 0)

    def test_known_adjacent_gap_is_observed_but_not_unknown(self) -> None:
        result = build_latest_announcement_namechange_timeline(
            [
                _row("000022.SZ", "深赤湾A", "20061009", "20181224", None),
                _row("000022.SZ", "招商港口", "20181226", None, "20181214"),
            ]
        )

        self.assertEqual(result.blocking_conflict_count, 0)
        self.assertEqual(result.adjacent_gap_count, 1)
        self.assertEqual(result.known_adjacent_gap_count, 1)
        self.assertEqual(result.unknown_adjacent_gap_count, 0)

    def test_unknown_adjacent_gap_is_reported(self) -> None:
        result = build_latest_announcement_namechange_timeline(
            [
                _row("000001.SZ", "名称A", "20200101", "20200105", "20200101"),
                _row("000001.SZ", "名称B", "20200107", None, "20200106"),
            ]
        )

        self.assertEqual(result.blocking_conflict_count, 0)
        self.assertEqual(result.adjacent_gap_count, 1)
        self.assertEqual(result.unknown_adjacent_gap_count, 1)


def _row(ts_code, name, start_date, end_date, ann_date):
    return {
        "ts_code": ts_code,
        "name": name,
        "start_date": start_date,
        "end_date": end_date,
        "ann_date": ann_date,
        "change_reason": "其他",
    }


if __name__ == "__main__":
    unittest.main()
