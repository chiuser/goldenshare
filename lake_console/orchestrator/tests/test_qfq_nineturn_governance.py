from __future__ import annotations

import unittest
from pathlib import Path

from orchestrator.defs.qfq_nineturn_integrity import (
    QFQ_NINETURN_DAILY_INTEGRITY_RULE_NAMES,
    QFQ_NINETURN_MINUTE_INTEGRITY_RULE_NAMES,
)
from orchestrator.defs.run_contracts.asset_column_schemas import (
    GOLD_STK_MINS_QFQ_NINETURN_SCHEMA,
    GOLD_STOCK_DAILY_QFQ_NINETURN_SCHEMA,
)

ORCHESTRATOR_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ORCHESTRATOR_ROOT.parents[1]
SOURCE_ROOT = ORCHESTRATOR_ROOT / "src" / "orchestrator" / "defs"


class QfqNineturnGovernanceTests(unittest.TestCase):
    def test_active_definitions_do_not_import_offline_bootstrap(self) -> None:
        active_roots = (
            SOURCE_ROOT / "assets",
            SOURCE_ROOT / "checks",
            SOURCE_ROOT / "jobs",
            SOURCE_ROOT / "sensors",
            SOURCE_ROOT / "asset_guards",
        )
        offenders = []
        for root in active_roots:
            for path in root.rglob("*.py"):
                source = path.read_text(encoding="utf-8")
                if "orchestrator.defs.bootstrap.qfq_nineturn" in source:
                    offenders.append(str(path.relative_to(ORCHESTRATOR_ROOT)))
        self.assertEqual(offenders, [])

    def test_history_tools_require_explicit_apply_and_no_migration_cutoff(self) -> None:
        history_cli = (
            SOURCE_ROOT / "bootstrap" / "qfq_nineturn_history_cli.py"
        ).read_text(encoding="utf-8")
        event_cli = (
            SOURCE_ROOT / "bootstrap" / "qfq_nineturn_events_cli.py"
        ).read_text(encoding="utf-8")
        combined = history_cli + event_cli
        self.assertIn("--apply", history_cli)
        self.assertIn("--apply", event_cli)
        self.assertIn("--plan-fingerprint", history_cli)
        self.assertIn("--plan-fingerprint", event_cli)
        self.assertNotIn("2026-08-07", combined)
        self.assertNotIn("report_runless_asset_event", history_cli)

    def test_event_tool_is_the_only_p4_dagster_state_writer(self) -> None:
        bootstrap_root = SOURCE_ROOT / "bootstrap"
        p4_sources = {
            path.name: path.read_text(encoding="utf-8")
            for path in bootstrap_root.glob("qfq_nineturn_*.py")
        }
        writers = sorted(
            name
            for name, source in p4_sources.items()
            if "report_runless_asset_event" in source
        )
        self.assertEqual(writers, ["qfq_nineturn_events.py"])
        self.assertNotIn("add_dynamic_partitions", "\n".join(p4_sources.values()))

    def test_history_batch_uses_compact_state_not_growing_history_rescans(self) -> None:
        source = (SOURCE_ROOT / "bootstrap" / "qfq_nineturn_history.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("historical_rescan_multiplier", source)
        self.assertIn("context_row_count", source)
        self.assertIn("seed_row_count", source)
        self.assertIn("PARTITION_BY (partition_trade_date)", source)
        self.assertNotIn("recursive", source.lower())

    def test_stock_daily_and_minute_formal_contracts_store_no_price(self) -> None:
        minute_columns = tuple(
            column.name for column in GOLD_STK_MINS_QFQ_NINETURN_SCHEMA
        )
        daily_columns = tuple(
            column.name for column in GOLD_STOCK_DAILY_QFQ_NINETURN_SCHEMA
        )
        self.assertEqual(
            minute_columns,
            (
                "ts_code",
                "freq",
                "trade_date",
                "trade_time",
                "up_count",
                "down_count",
                "nine_up_turn",
                "nine_down_turn",
            ),
        )
        self.assertEqual(
            daily_columns,
            (
                "ts_code",
                "trade_date",
                "up_count",
                "down_count",
                "nine_up_turn",
                "nine_down_turn",
            ),
        )
        self.assertNotIn("close_qfq", daily_columns)
        self.assertNotIn(
            "source_value_consistency",
            QFQ_NINETURN_MINUTE_INTEGRITY_RULE_NAMES,
        )
        self.assertNotIn(
            "source_value_consistency",
            QFQ_NINETURN_DAILY_INTEGRITY_RULE_NAMES,
        )

        for relative_path in (
            (
                "lake_console/orchestrator/src/orchestrator/defs/"
                "assets/stock_daily_qfq_nineturn_prod_core.py"
            ),
            (
                "lake_console/orchestrator/src/orchestrator/defs/"
                "prod_db/stock_daily_qfq_nineturn.py"
            ),
            "src/foundation/models/core_serving/equity_qfq_nineturn_daily.py",
            "src/biz/queries/wealth/market/stock_nine_turn/stock_nine_turn_query.py",
            "src/foundation/clients/local_lake/stock_nine_turn_contract.py",
            "src/foundation/clients/local_lake/stock_nine_turn_reader.py",
        ):
            source = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
            self.assertNotIn("close_qfq", source, relative_path)


if __name__ == "__main__":
    unittest.main()
