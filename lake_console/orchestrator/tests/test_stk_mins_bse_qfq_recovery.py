from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orchestrator.defs.bootstrap.stk_mins_bse_history_recovery_cli import main
from orchestrator.defs.bootstrap.stk_mins_bse_qfq_recovery import (
    BseQfqRecoveryError,
    _build_as_of_adj_factor_snapshot,
    _candidate_path,
    _create_scoped_changed_pairs,
    _hash_payload,
    _map_qfq_scope_rows,
    _resolve_exact_affected_codes,
    promote_bse_qfq_recovery_candidates,
)
from orchestrator.defs.resources import DuckDBResource


class BseQfqRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.scope_path = self.root / "scope.parquet"
        self.resource = DuckDBResource()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_scope(self) -> None:
        with self.resource.connect() as connection:
            connection.execute(
                """
                COPY (
                  SELECT *
                  FROM (VALUES
                    ('2025-09-03', 1, '920392.BJ', 'missing'),
                    ('2025-09-03', 5, '920392.BJ', 'missing'),
                    ('2025-09-03', 15, '920392.BJ', 'covered')
                  ) AS rows(trade_date, freq, latest_ts_code, coverage_status)
                ) TO ? (FORMAT PARQUET)
                """,
                [str(self.scope_path)],
            )

    def test_resolves_exact_code_hash_and_maps_only_contract_targets(self) -> None:
        self._write_scope()
        code_hash = _hash_payload(("920392.BJ",))
        manifest = {
            "changed_silver_rows": [
                {
                    "trade_date": "2025-09-03",
                    "freq": 1,
                    "affected_latest_code_count": 1,
                    "affected_latest_code_hash": code_hash,
                },
                {
                    "trade_date": "2025-09-03",
                    "freq": 15,
                    "affected_latest_code_count": 1,
                    "affected_latest_code_hash": code_hash,
                },
            ]
        }
        with self.resource.connect() as connection:
            resolved = _resolve_exact_affected_codes(
                connection,
                manifest=manifest,
                source_scope_path=self.scope_path,
            )
        self.assertEqual(resolved[("2025-09-03", 1)], ("920392.BJ",))
        mapped = _map_qfq_scope_rows(
            manifest=manifest,
            exact_codes_by_source=resolved,
        )
        self.assertEqual([row["target_freq"] for row in mapped], [1, 5])
        self.assertTrue(all(row["ts_code"] == "920392.BJ" for row in mapped))

    def test_unresolvable_code_hash_fails_closed(self) -> None:
        self._write_scope()
        manifest = {
            "changed_silver_rows": [
                {
                    "trade_date": "2025-09-03",
                    "freq": 1,
                    "affected_latest_code_count": 1,
                    "affected_latest_code_hash": _hash_payload(("920999.BJ",)),
                }
            ]
        }
        with (
            self.resource.connect() as connection,
            self.assertRaisesRegex(BseQfqRecoveryError, "resolved uniquely"),
        ):
            _resolve_exact_affected_codes(
                connection,
                manifest=manifest,
                source_scope_path=self.scope_path,
            )

    def test_candidate_path_mirrors_formal_layout_under_plan(self) -> None:
        lake_root = self.root / "lake"
        plan_root = self.root / "staging" / "plan"
        target = (
            lake_root
            / "gold/quote/stk_mins_qfq/freq=5/ts_code=920392.BJ/year=2025/part-000.parquet"
        )
        observed = _candidate_path(
            {"lake_root": str(lake_root), "plan_root": str(plan_root)}, target
        )
        self.assertTrue(observed.is_relative_to(plan_root))
        self.assertEqual(
            observed.relative_to(plan_root).as_posix(),
            "r3-qfq-candidates/gold/quote/stk_mins_qfq/freq=5/"
            "ts_code=920392.BJ/year=2025/part-000.parquet",
        )

    def test_changed_pairs_ignore_same_code_dates_outside_frozen_scope(self) -> None:
        with self.resource.connect() as connection:
            connection.execute(
                """
                COPY (
                  SELECT *
                  FROM (VALUES
                    ('920392.BJ', 1, DATE '2025-09-03', 2025)
                  ) AS rows(ts_code, target_freq, trade_date, year)
                ) TO ? (FORMAT PARQUET)
                """,
                [str(self.scope_path)],
            )
            connection.execute(
                """
                CREATE TEMP TABLE formal_qfq AS
                SELECT * FROM (VALUES
                  ('920392.BJ', 1, DATE '2025-09-03', TIMESTAMP '2025-09-03 09:31:00', 10.0, 10.0, 10.0, 10.0, 100.0, 1000.0, 'BSE'),
                  ('920392.BJ', 1, DATE '2025-09-04', TIMESTAMP '2025-09-04 09:31:00', 11.0, 11.0, 11.0, 11.0, 110.0, 1100.0, 'BSE')
                ) AS rows(ts_code, freq, trade_date, trade_time, open, high, low, close, vol, amount, exchange)
                """
            )
            connection.execute(
                """
                CREATE TEMP TABLE r3_expected AS
                SELECT * FROM formal_qfq WHERE trade_date = DATE '2025-09-03'
                """
            )

            _create_scoped_changed_pairs(
                connection,
                formal_relation="formal_qfq",
                scope_path=self.scope_path,
                target_freq=1,
                year=2025,
            )

            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM r3_changed_pairs"
                ).fetchone()[0],
                0,
            )
            connection.execute("DROP TABLE r3_changed_pairs")
            connection.execute("UPDATE r3_expected SET close = 10.5")
            _create_scoped_changed_pairs(
                connection,
                formal_relation="formal_qfq",
                scope_path=self.scope_path,
                target_freq=1,
                year=2025,
            )
            self.assertEqual(
                connection.execute(
                    """
                    SELECT ts_code, strftime(trade_date, '%Y-%m-%d')
                    FROM r3_changed_pairs
                    """
                ).fetchall(),
                [("920392.BJ", "2025-09-03")],
            )

    def test_as_of_factor_snapshot_keeps_codes_missing_from_latest_day(self) -> None:
        lake_root = self.root / "lake"
        plan_root = self.root / "staging"
        plan_root.mkdir(parents=True)
        first_path = (
            lake_root
            / "silver/quote/adj_factor/trade_date=2025-09-03/part-000.parquet"
        )
        latest_path = (
            lake_root
            / "silver/quote/adj_factor/trade_date=2025-09-04/part-000.parquet"
        )
        first_path.parent.mkdir(parents=True)
        latest_path.parent.mkdir(parents=True)
        with self.resource.connect() as connection:
            connection.execute(
                """
                COPY (
                  SELECT *
                  FROM (VALUES
                    ('920001.BJ', DATE '2025-09-03', 1.25),
                    ('920002.BJ', DATE '2025-09-03', 2.00)
                  ) AS rows(ts_code, trade_date, adj_factor)
                ) TO ? (FORMAT PARQUET)
                """,
                [str(first_path)],
            )
            connection.execute(
                """
                COPY (
                  SELECT *
                  FROM (VALUES
                    ('920002.BJ', DATE '2025-09-04', 2.50)
                  ) AS rows(ts_code, trade_date, adj_factor)
                ) TO ? (FORMAT PARQUET)
                """,
                [str(latest_path)],
            )

        manifest = _build_as_of_adj_factor_snapshot(
            lake_root=lake_root,
            plan_root=plan_root,
            duckdb_resource=self.resource,
        )

        self.assertEqual(manifest["row_count"], 2)
        self.assertEqual(manifest["as_of_trade_date"], "2025-09-04")
        with self.resource.connect() as connection:
            rows = connection.execute(
                """
                SELECT ts_code, trade_date, adj_factor
                FROM read_parquet(?)
                ORDER BY ts_code
                """,
                [manifest["path"]],
            ).fetchall()
        self.assertEqual(
            rows,
            [
                ("920001.BJ", rows[0][1], 1.25),
                ("920002.BJ", rows[1][1], 2.50),
            ],
        )
        self.assertEqual(rows[0][1].isoformat(), "2025-09-03")
        self.assertEqual(rows[1][1].isoformat(), "2025-09-04")

    def test_promote_and_cli_write_stages_require_confirmation(self) -> None:
        with self.assertRaisesRegex(BseQfqRecoveryError, "explicit confirmation"):
            promote_bse_qfq_recovery_candidates(
                plan_path=self.root / "missing-plan.json",
                candidate_report_path=self.root / "missing-candidates.json",
                audit_report_path=self.root / "missing-audit.json",
                checkpoint_path=self.root / "checkpoint.json",
                changed_manifest_path=self.root / "changed.json",
                output_path=self.root / "promote.json",
                confirm=False,
            )
        self.assertEqual(
            main(
                [
                    "build-qfq-candidates",
                    "--plan",
                    str(self.root / "missing-plan.json"),
                    "--output",
                    str(self.root / "candidates.json"),
                ]
            ),
            2,
        )
        self.assertEqual(
            main(
                [
                    "promote-qfq",
                    "--plan",
                    str(self.root / "missing-plan.json"),
                    "--candidate-report",
                    str(self.root / "missing-candidates.json"),
                    "--audit-report",
                    str(self.root / "missing-audit.json"),
                    "--checkpoint",
                    str(self.root / "checkpoint.json"),
                    "--changed-manifest",
                    str(self.root / "changed.json"),
                    "--output",
                    str(self.root / "promote.json"),
                ]
            ),
            2,
        )


if __name__ == "__main__":
    unittest.main()
