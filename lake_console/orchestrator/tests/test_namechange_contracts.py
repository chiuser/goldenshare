from datetime import date
from pathlib import Path
import tempfile
import unittest

import duckdb

from orchestrator.defs.assets.namechange import NAMECHANGE_RAW_COLUMN_TYPES
from orchestrator.defs.checks.namechange_checks import (
    raw_namechange_overlap_interval_observed,
)
from orchestrator.defs.duckdb_sql import NAMECHANGE_RAW_COLUMNS
from orchestrator.defs.namechange_timeline import (
    build_latest_announcement_namechange_timeline,
)
from orchestrator.defs.paths import raw_namechange_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource, TushareResult
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

    def test_raw_overlap_observation_check_sql_runs_on_duckdb(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target_path = raw_namechange_path(Path(tmpdir))
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with duckdb.connect(database=":memory:") as connection:
                connection.execute(
                    f"""
                    COPY (
                      SELECT
                        '000001.SZ' AS ts_code,
                        '名称A' AS name,
                        '20200101' AS start_date,
                        '20200110' AS end_date,
                        '20200101' AS ann_date,
                        '其他' AS change_reason
                      UNION ALL
                      SELECT
                        '000001.SZ' AS ts_code,
                        '名称B' AS name,
                        '20200105' AS start_date,
                        NULL AS end_date,
                        '20200104' AS ann_date,
                        '其他' AS change_reason
                    ) TO '{target_path.as_posix()}' (FORMAT PARQUET)
                    """
                )

            result = raw_namechange_overlap_interval_observed(
                lake_root=LakeRootResource(root_path=tmpdir),
                duckdb=DuckDBResource(),
            )

        self.assertTrue(result.passed)

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

    def test_diff_name_same_start_chooses_stock_basic_name_when_only_name_differs(
        self,
    ) -> None:
        result = build_latest_announcement_namechange_timeline(
            [
                _row("000001.SZ", "名称A", "20200101", "20200131", "20200101"),
                _row("000001.SZ", "名称B", "20200101", "20200131", "20200101"),
            ],
            stock_basic_names={"000001.SZ": "名称B"},
        )

        self.assertEqual(result.blocking_conflict_count, 0)
        self.assertEqual(result.diff_name_same_start_stock_basic_resolved_count, 1)
        self.assertEqual(result.rows[0]["name"], "名称B")

    def test_diff_name_same_start_keeps_blocking_when_other_fields_differ(
        self,
    ) -> None:
        result = build_latest_announcement_namechange_timeline(
            [
                _row("000001.SZ", "名称A", "20200101", "20200131", "20200101"),
                _row("000001.SZ", "名称B", "20200101", "20200229", "20200101"),
            ],
            stock_basic_names={"000001.SZ": "名称B"},
        )

        self.assertEqual(result.unresolved_conflict_count, 1)
        self.assertGreater(result.blocking_conflict_count, 0)

    def test_same_name_same_end_prefers_specific_reason_over_other(self) -> None:
        result = build_latest_announcement_namechange_timeline(
            [
                _row("000711.SZ", "ST京蓝", "20250908", None, "20250905"),
                _row_with_reason(
                    "000711.SZ", "ST京蓝", "20250908", None, "20250905", "摘星"
                ),
            ]
        )

        self.assertEqual(result.blocking_conflict_count, 0)
        self.assertEqual(result.same_name_same_end_reason_resolved_count, 1)
        self.assertEqual(result.rows[0]["change_reason"], "摘星")

    def test_same_name_same_end_treats_cancel_star_st_as_star_removal(self) -> None:
        result = build_latest_announcement_namechange_timeline(
            [
                _row_with_reason(
                    "000571.SZ", "ST大洲", "20210608", "20230627", "20210605", "摘星"
                ),
                _row_with_reason(
                    "000571.SZ",
                    "ST大洲",
                    "20210608",
                    "20230627",
                    "20210605",
                    "撤销*ST",
                ),
            ]
        )

        self.assertEqual(result.blocking_conflict_count, 0)
        self.assertEqual(result.same_name_same_end_reason_resolved_count, 1)

    def test_same_name_diff_end_chooses_latest_end_without_inner_name(self) -> None:
        result = build_latest_announcement_namechange_timeline(
            [
                _row_with_reason(
                    "000980.SZ", "*ST众泰", "20200624", "20210419", "20200623", "*ST"
                ),
                _row_with_reason(
                    "000980.SZ", "*ST众泰", "20200624", "20220519", "20200623", "*ST"
                ),
                _row_with_reason(
                    "000980.SZ", "*ST众泰", "20200624", None, "20200623", "*ST"
                ),
                _row_with_reason(
                    "000980.SZ", "ST众泰", "20220520", None, "20220519", "摘星"
                ),
            ]
        )

        self.assertEqual(result.blocking_conflict_count, 0)
        self.assertEqual(result.same_name_diff_end_resolved_count, 1)
        self.assertEqual(result.rows[0]["end_date"], date(2022, 5, 19))

    def test_same_name_diff_end_chooses_latest_end_even_with_inner_name(self) -> None:
        result = build_latest_announcement_namechange_timeline(
            [
                _row("000001.SZ", "名称A", "20200101", "20200110", "20200101"),
                _row("000001.SZ", "名称A", "20200101", "20200120", "20200101"),
                _row("000001.SZ", "名称B", "20200115", None, "20200114"),
            ]
        )

        self.assertEqual(result.blocking_conflict_count, 0)
        self.assertEqual(result.same_name_diff_end_resolved_count, 1)
        self.assertEqual(result.rows[0]["end_date"], date(2020, 1, 14))

    def test_manual_selected_event_resolves_case_by_case_reason_conflict(self) -> None:
        result = build_latest_announcement_namechange_timeline(
            [
                _row_with_reason(
                    "300173.SZ", "ST福能", "20251223", None, "20251220", "*ST"
                ),
                _row_with_reason(
                    "300173.SZ", "ST福能", "20251223", None, "20251220", "ST"
                ),
            ]
        )

        self.assertEqual(result.blocking_conflict_count, 0)
        self.assertEqual(result.manual_selected_event_resolved_count, 1)
        self.assertEqual(result.rows[0]["change_reason"], "ST")

    def test_manual_selected_event_resolves_case_by_case_name_conflict(self) -> None:
        result = build_latest_announcement_namechange_timeline(
            [
                _row("301030.SZ", "仕净环保", "20210702", None, None),
                _row("301030.SZ", "仕净科技", "20210702", None, None),
            ],
            stock_basic_names={"301030.SZ": "*ST仕净"},
        )

        self.assertEqual(result.blocking_conflict_count, 0)
        self.assertEqual(result.manual_selected_event_resolved_count, 1)
        self.assertEqual(result.rows[0]["name"], "仕净科技")

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
    return _row_with_reason(ts_code, name, start_date, end_date, ann_date, "其他")


def _row_with_reason(ts_code, name, start_date, end_date, ann_date, change_reason):
    return {
        "ts_code": ts_code,
        "name": name,
        "start_date": start_date,
        "end_date": end_date,
        "ann_date": ann_date,
        "change_reason": change_reason,
    }


if __name__ == "__main__":
    unittest.main()
