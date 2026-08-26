from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orchestrator.defs.bootstrap.stk_mins_bse_history_recovery_cli import main
from orchestrator.defs.bootstrap.stk_mins_bse_recursive_recovery import (
    BseRecursiveRecoveryError,
    _build_nineturn_dates,
    _candidate_path,
    _macd_batches,
    _scope_rows,
    _target_specs,
    promote_bse_recursive_recovery_candidates,
)
from orchestrator.defs.resources import DuckDBResource


class BseRecursiveRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_scope_uses_each_code_earliest_change_and_registered_frontier(self) -> None:
        manifest = {
            "changed_qfq_rows": [
                {
                    "freq": 60,
                    "ts_code": "920001.BJ",
                    "earliest_changed_trade_date": "2025-07-04",
                },
                {
                    "freq": 60,
                    "ts_code": "920002.BJ",
                    "earliest_changed_trade_date": "2025-08-01",
                },
            ]
        }
        observed = _scope_rows(
            manifest,
            frontier="2025-08-04",
            registered_dates=("2025-07-04", "2025-08-01", "2025-08-04"),
        )
        self.assertEqual(
            [(row["ts_code"], row["start_trade_date"], row["end_trade_date"]) for row in observed],
            [
                ("920001.BJ", "2025-07-04", "2025-08-04"),
                ("920002.BJ", "2025-08-01", "2025-08-04"),
            ],
        )

    def test_scope_rejects_unregistered_start_and_duplicate_code_frequency(self) -> None:
        with self.assertRaisesRegex(BseRecursiveRecoveryError, "outside registered"):
            _scope_rows(
                {
                    "changed_qfq_rows": [
                        {
                            "freq": 30,
                            "ts_code": "920001.BJ",
                            "earliest_changed_trade_date": "2025-07-03",
                        }
                    ]
                },
                frontier="2025-07-04",
                registered_dates=("2025-07-04",),
            )
        with self.assertRaisesRegex(BseRecursiveRecoveryError, "duplicate"):
            _scope_rows(
                {
                    "changed_qfq_rows": [
                        {
                            "freq": 30,
                            "ts_code": "920001.BJ",
                            "earliest_changed_trade_date": "2025-07-04",
                        },
                        {
                            "freq": 30,
                            "ts_code": "920001.BJ",
                            "earliest_changed_trade_date": "2025-07-04",
                        },
                    ]
                },
                frontier="2025-07-04",
                registered_dates=("2025-07-04",),
            )

    def test_macd_batches_keep_exact_start_groups_and_year_state_chain(self) -> None:
        lake = self.root / "lake"
        for code in ("920001.BJ", "920002.BJ"):
            for year in (2024, 2025, 2026):
                path = (
                    lake
                    / f"gold/quote/stk_mins_qfq/freq=60/ts_code={code}/year={year}/part-000.parquet"
                )
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
        scopes = [
            {
                "freq": 60,
                "ts_code": "920001.BJ",
                "start_trade_date": "2025-12-31",
                "end_trade_date": "2026-01-05",
            },
            {
                "freq": 60,
                "ts_code": "920002.BJ",
                "start_trade_date": "2026-01-05",
                "end_trade_date": "2026-01-05",
            },
        ]
        batches = _macd_batches(
            scopes=scopes,
            registered_dates=("2025-12-30", "2025-12-31", "2026-01-05"),
            lake_root=lake,
        )
        self.assertEqual(
            [batch["batch_key"] for batch in batches],
            [
                "macd:60:2025-12-31:2025",
                "macd:60:2025-12-31:2026",
                "macd:60:2026-01-05:2026",
            ],
        )
        self.assertEqual(batches[0]["previous_state_kind"], "formal")
        self.assertEqual(batches[1]["previous_state_kind"], "candidate")
        self.assertEqual(batches[2]["previous_state_kind"], "formal")
        self.assertEqual(batches[2]["stock_codes"], ["920002.BJ"])

    def test_target_specs_deduplicate_shared_state_partitions(self) -> None:
        specs = _target_specs(
            macd_batches=[
                {
                    "freq": 60,
                    "indicator_target_paths": [
                        str(self.root / "freq=60/ts_code=920001.BJ/year=2025/part-000.parquet")
                    ],
                    "state_target_paths": [
                        str(self.root / "state/freq=60/trade_date=2025-07-04/part-000.parquet")
                    ],
                },
                {
                    "freq": 60,
                    "indicator_target_paths": [],
                    "state_target_paths": [
                        str(self.root / "state/freq=60/trade_date=2025-07-04/part-000.parquet")
                    ],
                },
            ],
            nineturn_batches=[],
        )
        self.assertEqual(len(specs), 2)

    def test_candidate_path_mirrors_formal_lake_only_under_staging(self) -> None:
        lake = self.root / "lake"
        plan_root = self.root / "staging"
        target = lake / "gold/indicator/example/part-000.parquet"
        observed = _candidate_path(
            {"lake_root": str(lake), "plan_root": str(plan_root)}, target
        )
        self.assertEqual(
            observed,
            plan_root / "recursive-candidates/gold/indicator/example/part-000.parquet",
        )

    def test_write_stages_require_explicit_confirmation(self) -> None:
        with self.assertRaisesRegex(BseRecursiveRecoveryError, "confirmation"):
            promote_bse_recursive_recovery_candidates(
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
                    "build-recursive-candidates",
                    "--plan",
                    str(self.root / "missing-plan.json"),
                    "--output",
                    str(self.root / "candidates.json"),
                ]
            ),
            2,
        )

    def test_nineturn_candidate_uses_typed_code_start_scope(self) -> None:
        lake = self.root / "lake"
        plan_root = self.root / "staging"
        source = (
            lake
            / "gold/quote/stk_mins_qfq/freq=30/ts_code=920001.BJ/"
            "year=2025/part-000.parquet"
        )
        target = (
            lake
            / "gold/indicator/stk_mins_qfq_nineturn/freq=30/"
            "trade_date=2025-07-04/part-000.parquet"
        )
        source.parent.mkdir(parents=True, exist_ok=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        resource = DuckDBResource()
        with resource.connect() as connection:
            connection.execute(
                """
                COPY (
                  SELECT
                    '920001.BJ'::VARCHAR AS ts_code,
                    30::INTEGER AS freq,
                    DATE '2025-07-04' AS trade_date,
                    TIMESTAMP '2025-07-04 09:30:00' + value * INTERVAL 30 MINUTE AS trade_time,
                    (10.0 + value)::DOUBLE AS close
                  FROM range(40) rows(value)
                ) TO ? (FORMAT PARQUET)
                """,
                [str(source)],
            )
            connection.execute(
                """
                COPY (
                  SELECT
                    '920001.BJ'::VARCHAR AS ts_code,
                    30::INTEGER AS freq,
                    DATE '2025-07-04' AS trade_date,
                    TIMESTAMP '2025-07-04 09:30:00' AS trade_time,
                    0::INTEGER AS up_count,
                    0::INTEGER AS down_count,
                    ''::VARCHAR AS nine_up_turn,
                    ''::VARCHAR AS nine_down_turn
                ) TO ? (FORMAT PARQUET)
                """,
                [str(target)],
            )
        plan = {"lake_root": str(lake), "plan_root": str(plan_root)}
        _build_nineturn_dates(
            plan=plan,
            batch={
                "freq": 30,
                "source_paths": [str(source)],
                "stock_code_starts": [
                    {"ts_code": "920001.BJ", "start_trade_date": "2025-07-04"}
                ],
            },
            target_trade_dates=("2025-07-04",),
            duckdb_resource=resource,
        )
        candidate = _candidate_path(plan, target)
        with resource.connect() as connection:
            row_count = connection.execute(
                "SELECT count(*) FROM read_parquet(?)", [str(candidate)]
            ).fetchone()[0]
        self.assertEqual(row_count, 40)
        self.assertEqual(
            main(
                [
                    "promote-recursive",
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
