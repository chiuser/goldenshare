from datetime import date
from pathlib import Path
import tempfile
import unittest

import duckdb

from orchestrator.defs.assets import namechange as namechange_assets
from orchestrator.defs.assets.namechange import (
    NAMECHANGE_RAW_COLUMN_TYPES,
    build_silver_namechange_supported_codes,
)
from orchestrator.defs.checks.namechange_checks import (
    raw_namechange_overlap_interval_observed,
)
from orchestrator.defs.duckdb_sql import NAMECHANGE_RAW_COLUMNS
from orchestrator.defs.namechange_timeline import (
    build_latest_announcement_namechange_timeline,
)
from orchestrator.defs.paths import raw_namechange_path
from orchestrator.defs.resources import DuckDBResource, LakeRootResource, TushareResult
from orchestrator.defs.tushare_api_io import (
    fetch_tushare_full_file_distinct_to_raw,
    fetch_tushare_namechange_announcement_windows_to_raw,
)
from orchestrator.seeds.basic.stock_identity_mappings import StockIdentityMappingSeedRow


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


class WindowedFakeTushareResource:
    def __init__(self, rows_by_window):
        self._rows_by_window = rows_by_window
        self.calls = []

    def call(self, api_name, params, fields):
        requested_params = dict(params)
        self.calls.append((api_name, requested_params, tuple(fields)))
        window = (requested_params["start_date"], requested_params["end_date"])
        return TushareResult(
            rows=list(self._rows_by_window[window]),
            columns=tuple(fields),
            metadata={},
        )


class NamechangeContractTests(unittest.TestCase):
    def test_silver_scope_keeps_only_namechange_seeded_historical_targets(self) -> None:
        seed_rows = (
            StockIdentityMappingSeedRow(
                latest_ts_code="920305.BJ",
                source_ts_code="835305.BJ",
                valid_from=date(2021, 8, 26),
                valid_to=None,
                identity_source="namechange",
                confidence="inferred",
                reason="manually confirmed historical identity",
            ),
            StockIdentityMappingSeedRow(
                latest_ts_code="920001.BJ",
                source_ts_code="830001.BJ",
                valid_from=date(2021, 8, 26),
                valid_to=None,
                identity_source="bse_mapping",
                confidence="confirmed",
                reason="unrelated BSE mapping",
            ),
        )
        supported_codes = build_silver_namechange_supported_codes(
            current_listed_stock_names={"000001.SZ": "平安银行"},
            seed_rows=seed_rows,
        )
        raw_rows = [
            _row("000001.SZ", "平安银行", "19910403", None, None),
            _row("920305.BJ", "云创退", "20260709", None, "20260701"),
            _row("920001.BJ", "无关北交所代码", "20210101", None, None),
            _row("600000.SH", "未引用退市代码", "20000101", None, None),
        ]
        timeline = build_latest_announcement_namechange_timeline(
            [row for row in raw_rows if row["ts_code"] in supported_codes],
            stock_basic_names={"000001.SZ": "平安银行"},
        )

        self.assertEqual(supported_codes, frozenset({"000001.SZ", "920305.BJ"}))
        self.assertEqual(timeline.blocking_conflict_count, 0)
        self.assertEqual(
            {row["ts_code"] for row in timeline.rows},
            {"000001.SZ", "920305.BJ"},
        )

    def test_raw_asset_uses_namechange_announcement_window_reader(self) -> None:
        source = Path(namechange_assets.__file__).read_text()

        self.assertIn(
            "fetch_tushare_namechange_announcement_windows_to_raw(", source
        )
        self.assertNotIn("fetch_tushare_full_file_distinct_to_raw", source)

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

    def test_announcement_window_reader_splits_full_page_and_deduplicates(self) -> None:
        first = _row("000001.SZ", "名称A", "20200101", None, "20200101")
        second = _row("000002.SZ", "名称B", "20200102", None, "20200102")
        tushare = WindowedFakeTushareResource(
            {
                ("20200101", "20200104"): [first, second, first],
                ("20200101", "20200102"): [first],
                ("20200103", "20200104"): [first, second],
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            target_path = Path(tmpdir) / "part-000.parquet"
            metadata = fetch_tushare_namechange_announcement_windows_to_raw(
                tushare=tushare,
                duckdb=DuckDBResource(),
                fields=NAMECHANGE_RAW_COLUMNS,
                column_types=NAMECHANGE_RAW_COLUMN_TYPES,
                target_path=target_path,
                allow_empty=False,
                announcement_start_date=date(2020, 1, 1),
                announcement_end_date=date(2020, 1, 4),
                limit=3,
            )
            with duckdb.connect(database=":memory:") as connection:
                row_count = connection.execute(
                    f"SELECT count(*) FROM read_parquet('{target_path.as_posix()}')"
                ).fetchone()[0]

        self.assertEqual(row_count, 2)
        self.assertEqual(metadata["dagster/row_count"], 2)
        self.assertEqual(metadata["goldenshare/api_name"], "namechange")
        self.assertEqual(metadata["goldenshare/source_query_strategy"], "announcement_date_adaptive_bisection")
        self.assertEqual(metadata["goldenshare/source_query_count"], 3)
        self.assertEqual(metadata["goldenshare/accepted_window_count"], 2)
        self.assertEqual(metadata["goldenshare/split_window_count"], 1)
        self.assertEqual(metadata["goldenshare/max_accepted_window_row_count"], 2)
        self.assertEqual(metadata["goldenshare/source_row_count"], 3)
        self.assertEqual(metadata["goldenshare/duplicate_removed_count"], 1)
        self.assertEqual(
            [(params["start_date"], params["end_date"]) for _, params, _ in tushare.calls],
            [
                ("20200101", "20200104"),
                ("20200101", "20200102"),
                ("20200103", "20200104"),
            ],
        )
        self.assertTrue(
            all(
                api_name == "namechange" and params["offset"] == 0
                for api_name, params, _ in tushare.calls
            )
        )

    def test_announcement_window_reader_preserves_source_anchors(self) -> None:
        anchors = [
            _row_with_reason(
                "000040.SZ",
                "ST鸿基",
                "20040510",
                "20050525",
                "20040430",
                "撤消*ST并实行ST",
            ),
            _row_with_reason(
                "000761.SZ",
                "本钢板材",
                "20040510",
                "20060314",
                "20040430",
                "撤销ST",
            ),
            _row_with_reason(
                "600381.SH",
                "青海春天",
                "20150612",
                "20160628",
                "20150424",
                "其他",
            ),
        ]
        tushare = WindowedFakeTushareResource(
            {
                ("20200101", "20200104"): anchors,
                ("20200101", "20200102"): anchors[:2],
                ("20200103", "20200104"): anchors[2:],
            }
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            target_path = Path(tmpdir) / "part-000.parquet"
            fetch_tushare_namechange_announcement_windows_to_raw(
                tushare=tushare,
                duckdb=DuckDBResource(),
                fields=NAMECHANGE_RAW_COLUMNS,
                column_types=NAMECHANGE_RAW_COLUMN_TYPES,
                target_path=target_path,
                allow_empty=False,
                announcement_start_date=date(2020, 1, 1),
                announcement_end_date=date(2020, 1, 4),
                limit=3,
            )
            with duckdb.connect(database=":memory:") as connection:
                actual = connection.execute(
                    f"""
                    SELECT ts_code, name, start_date, end_date, ann_date, change_reason
                    FROM read_parquet('{target_path.as_posix()}')
                    ORDER BY ts_code
                    """
                ).fetchall()

        self.assertEqual(
            actual,
            [
                (
                    row["ts_code"],
                    row["name"],
                    row["start_date"],
                    row["end_date"],
                    row["ann_date"],
                    row["change_reason"],
                )
                for row in anchors
            ],
        )

    def test_announcement_window_reader_fails_without_replacing_target_for_full_day(
        self,
    ) -> None:
        full_day_rows = [
            _row("000001.SZ", "名称A", "20200101", None, "20200101"),
            _row("000002.SZ", "名称B", "20200101", None, "20200101"),
        ]
        tushare = WindowedFakeTushareResource(
            {("20200101", "20200101"): full_day_rows}
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            target_path = Path(tmpdir) / "part-000.parquet"
            target_path.write_bytes(b"unchanged-target")
            with self.assertRaisesRegex(RuntimeError, "single day"):
                fetch_tushare_namechange_announcement_windows_to_raw(
                    tushare=tushare,
                    duckdb=DuckDBResource(),
                    fields=NAMECHANGE_RAW_COLUMNS,
                    column_types=NAMECHANGE_RAW_COLUMN_TYPES,
                    target_path=target_path,
                    allow_empty=False,
                    announcement_start_date=date(2020, 1, 1),
                    announcement_end_date=date(2020, 1, 1),
                    limit=2,
                )

            self.assertEqual(target_path.read_bytes(), b"unchanged-target")
        self.assertEqual(tushare.calls[0][1]["offset"], 0)

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
