from __future__ import annotations

import contextlib
import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import duckdb

from orchestrator.defs.bootstrap import (
    stk_mins_qfq_canonical_history_cli,
    stk_mins_qfq_history_cli,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_canonical_history import (
    StkMinsQfqCanonicalHistoryError,
    _code_contract_paths,
    audit_stk_mins_qfq_canonical_candidates,
    audit_stk_mins_qfq_canonical_formal,
    build_stk_mins_qfq_canonical_candidates,
    plan_stk_mins_qfq_canonical_history,
    promote_stk_mins_qfq_canonical_candidates,
)
from orchestrator.defs.bootstrap.stk_mins_qfq_history import (
    StkMinsQfqHistoryBatch,
    _finalize_qfq_history_partitioned_export,
    generate_stk_mins_qfq_history,
    plan_stk_mins_qfq_history,
)
from orchestrator.defs.duckdb_sql import copy_query_to_parquet, read_parquet
from orchestrator.defs.paths import (
    gold_stk_mins_qfq_path,
    silver_adj_factor_path,
    silver_stk_mins_path,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_SCHEMA,
    SILVER_ADJ_FACTOR_SCHEMA,
    SILVER_STK_MINS_SCHEMA,
)
from orchestrator.defs.run_contracts.cn_a_derived_minute_bars import (
    expected_canonical_gold_source_times,
)
from orchestrator.defs.stk_mins_qfq import gold_stk_mins_qfq_source_freq

DATE_1 = "2014-06-03"
DATE_2 = "2014-06-04"
DATE_3 = "2014-06-05"
STOCK_A = "600000.SH"
STOCK_B = "000001.SZ"


def _column_types(schema) -> dict[str, str]:
    return {column.name: column.type for column in schema}


def _write_rows(
    path: Path,
    *,
    column_types: dict[str, str],
    rows: list[dict[str, object]],
    order_by: str = "1",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = tuple(column_types)
    with duckdb.connect(database=":memory:") as connection:
        column_defs = ", ".join(
            f'"{column}" {column_types[column]}' for column in columns
        )
        connection.execute(f"CREATE TEMP TABLE rows_to_write ({column_defs})")
        if rows:
            placeholders = ", ".join("?" for _column in columns)
            values = [[row.get(column) for column in columns] for row in rows]
            connection.executemany(
                f"INSERT INTO rows_to_write VALUES ({placeholders})",
                values,
            )
        select_columns = ", ".join(
            f'CAST("{column}" AS {column_types[column]}) AS "{column}"'
            for column in columns
        )
        connection.execute(
            copy_query_to_parquet(
                f"""
                SELECT {select_columns}
                FROM rows_to_write
                ORDER BY {order_by}
                """,
                path,
            )
        )


def _silver_row(
    *,
    ts_code: str,
    freq: int,
    trade_date: str,
    trade_time: str,
    open_: float,
) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "freq": freq,
        "trade_date": trade_date,
        "trade_time": trade_time,
        "open": open_,
        "high": open_ + 1.0,
        "low": open_ - 1.0,
        "close": open_ + 0.5,
        "vol": 100.0,
        "amount": 1000.0,
        "exchange": "SSE" if ts_code.endswith(".SH") else "SZSE",
    }


def _adj_row(ts_code: str, trade_date: str, adj_factor: float) -> dict[str, object]:
    return {
        "ts_code": ts_code,
        "trade_date": trade_date,
        "adj_factor": adj_factor,
    }


def _write_silver_partition(
    lake_root: Path,
    *,
    target_freq: int,
    trade_date: str,
    stock_codes: tuple[str, ...] = (STOCK_A, STOCK_B),
) -> None:
    source_freq = gold_stk_mins_qfq_source_freq(target_freq)
    source_times = expected_canonical_gold_source_times(target_freq)
    _write_rows(
        silver_stk_mins_path(lake_root, source_freq, trade_date),
        column_types=_column_types(SILVER_STK_MINS_SCHEMA),
        rows=[
            _silver_row(
                ts_code=stock_code,
                freq=source_freq,
                trade_date=trade_date,
                trade_time=f"{trade_date} {trade_time}",
                open_=open_base,
            )
            for stock_code, open_base in (
                (
                    stock_code,
                    (10.0 if stock_code == STOCK_A else 20.0)
                    + (0.0 if trade_date == DATE_1 else 10.0),
                )
                for stock_code in stock_codes
            )
            for trade_time in source_times
        ],
        order_by="ts_code, trade_time",
    )


def _write_adj_factor_partition(lake_root: Path, *, trade_date: str) -> None:
    _write_rows(
        silver_adj_factor_path(lake_root, trade_date),
        column_types=_column_types(SILVER_ADJ_FACTOR_SCHEMA),
        rows=[
            _adj_row(STOCK_A, trade_date, 2.0 if trade_date == DATE_1 else 4.0),
            _adj_row(STOCK_B, trade_date, 3.0 if trade_date == DATE_1 else 6.0),
        ],
        order_by="ts_code",
    )


def _write_valid_inputs(lake_root: Path, *, freqs: tuple[int, ...] = (5,)) -> None:
    for target_freq in freqs:
        _write_silver_partition(
            lake_root,
            target_freq=target_freq,
            trade_date=DATE_1,
        )
        _write_silver_partition(
            lake_root,
            target_freq=target_freq,
            trade_date=DATE_2,
        )
    _write_adj_factor_partition(lake_root, trade_date=DATE_1)
    _write_adj_factor_partition(lake_root, trade_date=DATE_2)


def _read_gold_rows(path: Path) -> list[dict[str, object]]:
    with duckdb.connect(database=":memory:") as connection:
        columns = [
            row[0]
            for row in connection.execute(
                f"DESCRIBE SELECT * FROM {read_parquet(path, hive_partitioning=False)}"
            ).fetchall()
        ]
        rows = connection.execute(
            f"""
            SELECT *
            FROM {read_parquet(path, hive_partitioning=False)}
            ORDER BY trade_date, trade_time
            """
        ).fetchall()
    return [dict(zip(columns, row, strict=True)) for row in rows]


def _write_p7_inputs(lake_root: Path) -> None:
    _write_valid_inputs(lake_root, freqs=(5, 15, 60))
    silver_1m_path = silver_stk_mins_path(lake_root, 1, DATE_1)
    silver_rows = _read_gold_rows(silver_1m_path)
    silver_rows.extend(
        [
            _silver_row(
                ts_code=STOCK_A,
                freq=1,
                trade_date=DATE_1,
                trade_time=f"{DATE_1} {trade_time}",
                open_=100.0 + index,
            )
            for index, trade_time in enumerate(("15:01:00", "15:30:00"))
        ]
    )
    _write_rows(
        silver_1m_path,
        column_types=_column_types(SILVER_STK_MINS_SCHEMA),
        rows=silver_rows,
        order_by="ts_code, trade_time",
    )
    for stock_code in (STOCK_A, STOCK_B):
        rows = [
            {
                **_silver_row(
                    ts_code=stock_code,
                    freq=1,
                    trade_date=trade_date,
                    trade_time=f"{trade_date} {trade_time}",
                    open_=open_base,
                )
            }
            for trade_date, open_base in ((DATE_1, 10.0), (DATE_2, 20.0))
            for trade_time in ("09:30:00", "15:00:00")
        ]
        if stock_code == STOCK_A:
            rows.extend(
                [
                    {
                        **_silver_row(
                            ts_code=stock_code,
                            freq=1,
                            trade_date=DATE_1,
                            trade_time=f"{DATE_1} {trade_time}",
                            open_=30.0 + index,
                        )
                    }
                    for index, trade_time in enumerate(("15:01:00", "15:30:00"))
                ]
            )
        _write_rows(
            gold_stk_mins_qfq_path(lake_root, 1, stock_code, 2014),
            column_types=_column_types(GOLD_STK_MINS_QFQ_SCHEMA),
            rows=rows,
            order_by="trade_date, trade_time",
        )


def _p7_plan(lake_root: Path, staging_root: Path, report_root: Path) -> dict[str, object]:
    return plan_stk_mins_qfq_canonical_history(
        registered_partition_keys=[DATE_1, DATE_2],
        lake_root=lake_root,
        staging_root=staging_root,
        report_root=report_root,
        start_date=DATE_1,
        end_date=DATE_2,
        duckdb_resource=DuckDBResource(),
    )


class StkMinsQfqM8CHistoryTests(unittest.TestCase):
    def test_partitioned_history_export_merges_multiple_parts_per_stock(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            export_root = root / "export" / "__partition_ts_code=600000.SH"
            target_root = root / "target"
            for index, trade_time in enumerate(("09:35:00", "09:40:00")):
                _write_rows(
                    export_root / f"part-{index}.parquet",
                    column_types=_column_types(GOLD_STK_MINS_QFQ_SCHEMA),
                    rows=[
                        _silver_row(
                            ts_code=STOCK_A,
                            freq=5,
                            trade_date=DATE_1,
                            trade_time=f"{DATE_1} {trade_time}",
                            open_=10.0 + index,
                        )
                    ],
                    order_by="trade_time",
                )
            with duckdb.connect(database=":memory:") as connection:
                results = _finalize_qfq_history_partitioned_export(
                    connection=connection,
                    target_lake_root=target_root,
                    export_root=root / "export",
                    batch=StkMinsQfqHistoryBatch(
                        freq=5,
                        year="2014",
                        partition_keys=(DATE_1,),
                    ),
                )
            rows = _read_gold_rows(
                gold_stk_mins_qfq_path(target_root, 5, STOCK_A, 2014)
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].row_count, 2)
        self.assertEqual(len(rows), 2)

    def test_canonical_rebuild_cli_requires_stage_confirmation(self) -> None:
        with TemporaryDirectory() as temp_dir:
            exit_code = stk_mins_qfq_canonical_history_cli.main(
                [
                    "build-candidates",
                    "--plan",
                    str(Path(temp_dir) / "plan.json"),
                    "--plan-hash",
                    "frozen",
                    "--freq",
                    "5",
                ]
            )
        self.assertEqual(exit_code, 2)

    def test_derived_equivalence_cli_requires_one_sample_freq_and_year(self) -> None:
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            stk_mins_qfq_canonical_history_cli.main(
                [
                    "audit-derived-equivalence",
                    "--plan",
                    "/private/tmp/unused-plan.json",
                    "--plan-hash",
                    "frozen",
                ]
            )

    def test_canonical_plan_fingerprints_derived_equivalence_code(self) -> None:
        contract_names = {path.name for path in _code_contract_paths()}

        self.assertIn("stk_mins_qfq_derived_history.py", contract_names)

    def test_unsafe_canonical_rebuild_command_is_removed(self) -> None:
        with self.assertRaises(SystemExit):
            stk_mins_qfq_canonical_history_cli.main(["rebuild-gold-qfq-canonical-history"])

    def test_candidate_first_rebuild_preserves_formal_until_promote(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lake_root = root / "lake"
            staging_root = root / "staging"
            report_root = root / "reports"
            lake_root.mkdir()
            _write_p7_inputs(lake_root)
            formal_1m = gold_stk_mins_qfq_path(lake_root, 1, STOCK_A, 2014)
            unaffected_1m = gold_stk_mins_qfq_path(lake_root, 1, STOCK_B, 2014)
            before_bytes = formal_1m.read_bytes()
            unaffected_before_bytes = unaffected_1m.read_bytes()
            plan = _p7_plan(lake_root, staging_root, report_root)
            plan_path = Path(str(plan["phase_root"])) / "plan.json"
            plan_hash = str(plan["plan_hash"])

            build = build_stk_mins_qfq_canonical_candidates(
                plan_path=plan_path,
                expected_plan_hash=plan_hash,
                freq=1,
                duckdb_resource=DuckDBResource(),
                confirm_build=True,
            )
            self.assertEqual(formal_1m.read_bytes(), before_bytes)
            self.assertEqual(unaffected_1m.read_bytes(), unaffected_before_bytes)
            self.assertEqual(build["candidate_file_count"], 1)
            candidate_audit = audit_stk_mins_qfq_canonical_candidates(
                plan_path=plan_path,
                expected_plan_hash=plan_hash,
                freq=1,
                duckdb_resource=DuckDBResource(),
            )
            self.assertTrue(candidate_audit["ready"])
            promoted = promote_stk_mins_qfq_canonical_candidates(
                plan_path=plan_path,
                expected_plan_hash=plan_hash,
                freq=1,
                confirm_promote=True,
            )
            self.assertEqual(promoted["promoted_file_count"], 1)
            formal_audit = audit_stk_mins_qfq_canonical_formal(
                plan_path=plan_path,
                expected_plan_hash=plan_hash,
                freq=1,
                duckdb_resource=DuckDBResource(),
            )
            self.assertTrue(formal_audit["ready"])
            self.assertEqual(unaffected_1m.read_bytes(), unaffected_before_bytes)
            stock_a_rows = _read_gold_rows(formal_1m)
            stock_b_rows = _read_gold_rows(
                gold_stk_mins_qfq_path(lake_root, 1, STOCK_B, 2014)
            )

        self.assertEqual(
            [row["trade_time"].strftime("%H:%M:%S") for row in stock_a_rows],
            ["09:30:00", "15:00:00", "09:30:00", "15:00:00"],
        )
        self.assertEqual(len(stock_b_rows), 4)

    def test_replan_after_one_minute_repair_has_empty_scope(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lake_root = root / "lake"
            lake_root.mkdir()
            _write_p7_inputs(lake_root)
            first_plan = _p7_plan(lake_root, root / "staging-1", root / "reports-1")
            first_plan_path = Path(str(first_plan["phase_root"])) / "plan.json"
            first_plan_hash = str(first_plan["plan_hash"])
            build_stk_mins_qfq_canonical_candidates(
                plan_path=first_plan_path,
                expected_plan_hash=first_plan_hash,
                freq=1,
                duckdb_resource=DuckDBResource(),
                confirm_build=True,
            )
            audit_stk_mins_qfq_canonical_candidates(
                plan_path=first_plan_path,
                expected_plan_hash=first_plan_hash,
                freq=1,
                duckdb_resource=DuckDBResource(),
            )
            promote_stk_mins_qfq_canonical_candidates(
                plan_path=first_plan_path,
                expected_plan_hash=first_plan_hash,
                freq=1,
                confirm_promote=True,
            )

            second_plan = _p7_plan(
                lake_root,
                root / "staging-2",
                root / "reports-2",
            )

        self.assertTrue(second_plan["one_minute_already_canonical"])
        self.assertEqual(second_plan["one_minute_affected_pair_count"], 0)
        self.assertEqual(second_plan["one_minute_affected_file_count"], 0)
        self.assertEqual(second_plan["one_minute_tail_row_count"], 0)

    def test_candidate_change_blocks_formal_promotion(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lake_root = root / "lake"
            lake_root.mkdir()
            _write_p7_inputs(lake_root)
            plan = _p7_plan(lake_root, root / "staging", root / "reports")
            plan_path = Path(str(plan["phase_root"])) / "plan.json"
            plan_hash = str(plan["plan_hash"])
            with patch(
                "orchestrator.defs.bootstrap.stk_mins_qfq_canonical_history."
                "P7_STOCK_CHUNK_SIZE",
                1,
            ):
                build_stk_mins_qfq_canonical_candidates(
                    plan_path=plan_path,
                    expected_plan_hash=plan_hash,
                    freq=5,
                    duckdb_resource=DuckDBResource(),
                    confirm_build=True,
                )
            audit_stk_mins_qfq_canonical_candidates(
                plan_path=plan_path,
                expected_plan_hash=plan_hash,
                freq=5,
                duckdb_resource=DuckDBResource(),
            )
            candidate = next(
                Path(str(plan["candidate_lake_root"])).glob(
                    "gold/quote/stk_mins_qfq/freq=5/ts_code=*/year=*/part-000.parquet"
                )
            )
            candidate.write_bytes(candidate.read_bytes() + b"changed")

            with self.assertRaisesRegex(
                StkMinsQfqCanonicalHistoryError,
                "Candidate file is missing or changed",
            ):
                promote_stk_mins_qfq_canonical_candidates(
                    plan_path=plan_path,
                    expected_plan_hash=plan_hash,
                    freq=5,
                    confirm_promote=True,
                )

    def test_source_change_blocks_candidate_build(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lake_root = root / "lake"
            lake_root.mkdir()
            _write_p7_inputs(lake_root)
            plan = _p7_plan(lake_root, root / "staging", root / "reports")
            plan_path = Path(str(plan["phase_root"])) / "plan.json"
            source = silver_stk_mins_path(lake_root, 1, DATE_1)
            source.touch()

            with self.assertRaisesRegex(
                StkMinsQfqCanonicalHistoryError,
                "Frozen source file changed",
            ):
                build_stk_mins_qfq_canonical_candidates(
                    plan_path=plan_path,
                    expected_plan_hash=str(plan["plan_hash"]),
                    freq=5,
                    duckdb_resource=DuckDBResource(),
                    confirm_build=True,
                )

    def test_incomplete_frequency_manifest_blocks_candidate_audit(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lake_root = root / "lake"
            lake_root.mkdir()
            _write_p7_inputs(lake_root)
            plan = _p7_plan(lake_root, root / "staging", root / "reports")
            plan_path = Path(str(plan["phase_root"])) / "plan.json"
            plan_hash = str(plan["plan_hash"])
            build = build_stk_mins_qfq_canonical_candidates(
                plan_path=plan_path,
                expected_plan_hash=plan_hash,
                freq=5,
                duckdb_resource=DuckDBResource(),
                confirm_build=True,
            )
            manifest_path = Path(str(build["manifest_path"]))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["completed_batch_keys"] = []
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(
                StkMinsQfqCanonicalHistoryError,
                "candidates are incomplete",
            ):
                audit_stk_mins_qfq_canonical_candidates(
                    plan_path=plan_path,
                    expected_plan_hash=plan_hash,
                    freq=5,
                    duckdb_resource=DuckDBResource(),
                )

    def test_concurrent_formal_change_blocks_all_promotion(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            lake_root = root / "lake"
            lake_root.mkdir()
            _write_p7_inputs(lake_root)
            plan = _p7_plan(lake_root, root / "staging", root / "reports")
            plan_path = Path(str(plan["phase_root"])) / "plan.json"
            plan_hash = str(plan["plan_hash"])
            build = build_stk_mins_qfq_canonical_candidates(
                plan_path=plan_path,
                expected_plan_hash=plan_hash,
                freq=5,
                duckdb_resource=DuckDBResource(),
                confirm_build=True,
            )
            audit_stk_mins_qfq_canonical_candidates(
                plan_path=plan_path,
                expected_plan_hash=plan_hash,
                freq=5,
                duckdb_resource=DuckDBResource(),
            )
            manifest = json.loads(
                Path(str(build["manifest_path"])).read_text(encoding="utf-8")
            )
            entries = sorted(manifest["files"], key=lambda item: item["formal_path"])
            changed_target = Path(entries[-1]["formal_path"])
            changed_target.parent.mkdir(parents=True, exist_ok=True)
            changed_target.write_bytes(b"concurrent-change")

            with self.assertRaisesRegex(
                StkMinsQfqCanonicalHistoryError,
                "new formal target appeared",
            ):
                promote_stk_mins_qfq_canonical_candidates(
                    plan_path=plan_path,
                    expected_plan_hash=plan_hash,
                    freq=5,
                    confirm_promote=True,
                )
            self.assertFalse(Path(entries[0]["formal_path"]).exists())

    def test_m8c_helper_does_not_define_active_dagster_components(self) -> None:
        helper_path = Path("src/orchestrator/defs/bootstrap/stk_mins_qfq_history.py")
        text = helper_path.read_text()
        for token in ("@dg.asset", "@dg.asset_check", "@dg.sensor", "define_asset_job"):
            self.assertNotIn(token, text)

    def test_generate_writes_qfq_by_stock_year_with_contract_schema(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_inputs(lake_root)
            _write_rows(
                silver_adj_factor_path(lake_root, DATE_3),
                column_types=_column_types(SILVER_ADJ_FACTOR_SCHEMA),
                rows=[
                    _adj_row(STOCK_A, DATE_3, 8.0),
                    _adj_row(STOCK_B, DATE_3, 12.0),
                ],
                order_by="ts_code",
            )

            report = generate_stk_mins_qfq_history(
                lake_root=lake_root,
                duckdb_resource=DuckDBResource(),
                registered_partition_keys=[DATE_1, DATE_2],
                freqs=[5],
            )

            self.assertEqual(report.written_file_count, 2)
            stock_a_path = gold_stk_mins_qfq_path(lake_root, 5, STOCK_A, 2014)
            stock_b_path = gold_stk_mins_qfq_path(lake_root, 5, STOCK_B, 2014)
            self.assertTrue(stock_a_path.exists())
            self.assertTrue(stock_b_path.exists())
            rows = _read_gold_rows(stock_a_path)
            self.assertEqual([column.name for column in GOLD_STK_MINS_QFQ_SCHEMA], list(rows[0]))
            self.assertEqual(len(rows), 96)
            self.assertAlmostEqual(rows[0]["open"], 5.25)
            self.assertAlmostEqual(rows[48]["open"], 20.5)
            self.assertEqual(report.plan.planned_event_count, 2 * 1 * 5)

    def test_generate_uses_delisted_codes_last_available_factor(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_silver_partition(
                lake_root,
                target_freq=5,
                trade_date=DATE_1,
            )
            _write_silver_partition(
                lake_root,
                target_freq=5,
                trade_date=DATE_2,
                stock_codes=(STOCK_A,),
            )
            _write_adj_factor_partition(lake_root, trade_date=DATE_1)
            _write_rows(
                silver_adj_factor_path(lake_root, DATE_2),
                column_types=_column_types(SILVER_ADJ_FACTOR_SCHEMA),
                rows=[_adj_row(STOCK_A, DATE_2, 4.0)],
                order_by="ts_code",
            )

            report = generate_stk_mins_qfq_history(
                lake_root=lake_root,
                duckdb_resource=DuckDBResource(),
                registered_partition_keys=[DATE_1, DATE_2],
                freqs=[5],
            )
            stock_b_rows = _read_gold_rows(
                gold_stk_mins_qfq_path(lake_root, 5, STOCK_B, 2014)
            )

        self.assertEqual(report.written_file_count, 2)
        self.assertEqual(len(stock_b_rows), 48)
        self.assertEqual(
            {row["trade_date"].isoformat() for row in stock_b_rows},
            {DATE_1},
        )
        self.assertAlmostEqual(stock_b_rows[0]["open"], 20.5)

    def test_plan_counts_targets_and_does_not_write_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_inputs(lake_root)

            plan = plan_stk_mins_qfq_history(
                lake_root=lake_root,
                registered_partition_keys=[DATE_1, DATE_2],
                freqs=[5],
            )

            self.assertEqual(plan.selected_partition_keys, (DATE_1, DATE_2))
            self.assertEqual(plan.planned_target_file_count, 2)
            self.assertEqual(plan.existing_target_file_count, 0)
            self.assertEqual(len(plan.batches), 1)
            self.assertFalse((lake_root / "gold").exists())

    def test_generate_fails_when_target_exists(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_inputs(lake_root)
            _write_rows(
                gold_stk_mins_qfq_path(lake_root, 5, STOCK_A, 2014),
                column_types=_column_types(GOLD_STK_MINS_QFQ_SCHEMA),
                rows=[
                    {
                        **_silver_row(
                            ts_code=STOCK_A,
                            freq=5,
                            trade_date=DATE_1,
                            trade_time=f"{DATE_1} 09:35:00",
                            open_=1.0,
                        )
                    }
                ],
                order_by="trade_date, trade_time",
            )

            with self.assertRaisesRegex(FileExistsError, "already exist"):
                generate_stk_mins_qfq_history(
                    lake_root=lake_root,
                    duckdb_resource=DuckDBResource(),
                    registered_partition_keys=[DATE_1, DATE_2],
                    freqs=[5],
                )

    def test_generate_fails_for_missing_silver_or_adj_factor_inputs(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_silver_partition(lake_root, target_freq=5, trade_date=DATE_1)

            with self.assertRaisesRegex(FileNotFoundError, "inputs are missing"):
                generate_stk_mins_qfq_history(
                    lake_root=lake_root,
                    duckdb_resource=DuckDBResource(),
                    registered_partition_keys=[DATE_1],
                    freqs=[5],
                )

    def test_generate_fails_when_factor_coverage_is_incomplete(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_silver_partition(lake_root, target_freq=5, trade_date=DATE_1)
            _write_rows(
                silver_adj_factor_path(lake_root, DATE_1),
                column_types=_column_types(SILVER_ADJ_FACTOR_SCHEMA),
                rows=[_adj_row(STOCK_A, DATE_1, 2.0)],
                order_by="ts_code",
            )

            with self.assertRaisesRegex(RuntimeError, "factor coverage failed"):
                generate_stk_mins_qfq_history(
                    lake_root=lake_root,
                    duckdb_resource=DuckDBResource(),
                    registered_partition_keys=[DATE_1],
                    freqs=[5],
                )

    def test_cli_plan_reads_registered_partitions_but_does_not_write(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_inputs(lake_root)
            buffer = io.StringIO()

            with patch.object(
                stk_mins_qfq_history_cli,
                "registered_stk_mins_silver_partition_keys",
                return_value=(DATE_1, DATE_2),
            ), contextlib.redirect_stdout(buffer):
                stk_mins_qfq_history_cli.main(
                    [
                        "plan-gold-qfq-history",
                        "--lake-root",
                        str(lake_root),
                        "--freqs",
                        "5",
                    ]
                )

            self.assertIn("'planned_target_file_count': 2", buffer.getvalue())
            self.assertFalse((lake_root / "gold").exists())

    def test_cli_generate_writes_only_gold_targets_under_lake_root(self) -> None:
        with TemporaryDirectory() as temp_dir:
            lake_root = Path(temp_dir)
            _write_valid_inputs(lake_root)

            with patch.object(
                stk_mins_qfq_history_cli,
                "registered_stk_mins_silver_partition_keys",
                return_value=(DATE_1, DATE_2),
            ), contextlib.redirect_stdout(io.StringIO()):
                stk_mins_qfq_history_cli.main(
                    [
                        "generate-gold-qfq-history",
                        "--lake-root",
                        str(lake_root),
                        "--freqs",
                        "5",
                    ]
                )

            self.assertTrue(gold_stk_mins_qfq_path(lake_root, 5, STOCK_A, 2014).exists())
            self.assertTrue(gold_stk_mins_qfq_path(lake_root, 5, STOCK_B, 2014).exists())


if __name__ == "__main__":
    unittest.main()
