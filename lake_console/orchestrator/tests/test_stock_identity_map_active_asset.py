import csv
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from orchestrator.defs.assets.stock_identity_map import (
    STOCK_BASIC_IDENTITY_CONFIDENCE,
    STOCK_BASIC_IDENTITY_SOURCE,
    build_stock_identity_map_rows,
    write_stock_identity_map_snapshot,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.sensors.readiness import AssetReadinessStatus
from orchestrator.defs.sensors.stock_identity_map_sensor import (
    _identity_map_decision,
    _latest_registered_trade_date,
    _source_window_started,
)
from orchestrator.seeds.basic.stock_identity_mappings import (
    STOCK_IDENTITY_MAPPINGS_SEED_COLUMNS,
    load_stock_identity_mapping_seed,
)


class StockIdentityMapActiveAssetTests(unittest.TestCase):
    def test_seed_loader_rejects_duplicate_source_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            seed_path = Path(temp_dir) / "stock_identity_mappings.cn_a.csv"
            with seed_path.open("w", newline="") as file:
                writer = csv.writer(file)
                writer.writerow(STOCK_IDENTITY_MAPPINGS_SEED_COLUMNS)
                writer.writerow(
                    [
                        "920001.BJ",
                        "830001.BJ",
                        "2021-11-15",
                        "",
                        "bse_mapping",
                        "confirmed",
                        "seed row",
                    ]
                )
                writer.writerow(
                    [
                        "920002.BJ",
                        "830001.BJ",
                        "2021-11-15",
                        "",
                        "bse_mapping",
                        "confirmed",
                        "duplicate source",
                    ]
                )

            with self.assertRaisesRegex(ValueError, "source_ts_code must be unique"):
                load_stock_identity_mapping_seed(seed_path)

    def test_build_rows_generates_self_and_seed_mappings(self) -> None:
        seed_rows = load_stock_identity_mapping_seed(_write_seed_fixture())
        result = build_stock_identity_map_rows(
            stock_basic_rows=(
                {
                    "ts_code": "000001.SZ",
                    "list_date": date(1991, 4, 3),
                    "delist_date": None,
                },
                {
                    "ts_code": "920001.BJ",
                    "list_date": date(2021, 11, 15),
                    "delist_date": None,
                },
            ),
            seed_rows=seed_rows,
            namechange_codes=set(),
            created_at=datetime(2026, 5, 31, 16, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        )

        self.assertEqual(len(result.rows), 3)
        source_codes = {row["source_ts_code"] for row in result.rows}
        self.assertEqual(source_codes, {"000001.SZ", "920001.BJ", "830001.BJ"})
        seed_row = next(row for row in result.rows if row["source_ts_code"] == "830001.BJ")
        self.assertEqual(seed_row["latest_ts_code"], "920001.BJ")
        self.assertEqual(seed_row["effective_list_date"], date(2021, 11, 15))
        self.assertIn(
            {"value": STOCK_BASIC_IDENTITY_SOURCE, "row_count": 2},
            result.source_distribution,
        )
        self.assertIn(
            {"value": STOCK_BASIC_IDENTITY_CONFIDENCE, "row_count": 3},
            result.confidence_distribution,
        )

    def test_build_rows_fails_when_seed_latest_code_missing(self) -> None:
        seed_rows = load_stock_identity_mapping_seed(_write_seed_fixture())
        with self.assertRaisesRegex(RuntimeError, "latest_ts_code not found"):
            build_stock_identity_map_rows(
                stock_basic_rows=(
                    {
                        "ts_code": "000001.SZ",
                        "list_date": date(1991, 4, 3),
                        "delist_date": None,
                    },
                ),
                seed_rows=seed_rows,
                namechange_codes=set(),
                created_at=datetime.now(ZoneInfo("Asia/Shanghai")),
            )

    def test_write_snapshot_is_atomic_and_keeps_contract_columns(self) -> None:
        seed_rows = load_stock_identity_mapping_seed(_write_seed_fixture())
        result = build_stock_identity_map_rows(
            stock_basic_rows=(
                {
                    "ts_code": "920001.BJ",
                    "list_date": date(2021, 11, 15),
                    "delist_date": None,
                },
            ),
            seed_rows=seed_rows,
            namechange_codes=set(),
            created_at=datetime(2026, 5, 31, 16, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            target_path = Path(temp_dir) / "silver/basic/stock_identity_map/part-000.parquet"
            row_count, columns = write_stock_identity_map_snapshot(
                duckdb=DuckDBResource(),
                rows=result.rows,
                target_path=target_path,
            )

            self.assertTrue(target_path.exists())
            self.assertEqual(row_count, len(result.rows))
            self.assertEqual(
                columns,
                (
                    "latest_ts_code",
                    "source_ts_code",
                    "valid_from",
                    "valid_to",
                    "effective_list_date",
                    "effective_delist_date",
                    "identity_source",
                    "confidence",
                    "reason",
                    "created_at",
                ),
            )


class StockIdentityMapSensorDecisionTests(unittest.TestCase):
    def test_window_starts_at_1630(self) -> None:
        timezone = ZoneInfo("Asia/Shanghai")
        self.assertFalse(_source_window_started(datetime(2026, 5, 31, 16, 29, tzinfo=timezone)))
        self.assertTrue(_source_window_started(datetime(2026, 5, 31, 16, 30, tzinfo=timezone)))

    def test_latest_registered_trade_date_uses_stock_trade_days(self) -> None:
        evaluated_at = datetime(2026, 5, 31, 17, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.assertEqual(
            _latest_registered_trade_date(
                ("2026-05-28", "2026-05-29", "2026-06-01"),
                evaluated_at,
            ),
            "2026-05-29",
        )

    def test_decision_skips_when_upstream_not_ready(self) -> None:
        decision = _identity_map_decision(
            target_trade_date="2026-05-29",
            stock_basic_status=_status(ready=False, reason="stock basic stale"),
            namechange_status=_status(ready=True, storage_id=2),
            identity_map_status=_status(ready=False, storage_id=1),
        )

        self.assertFalse(decision.request_run)
        self.assertIn("股票基础信息未 ready", decision.reason)

    def test_decision_requests_when_identity_map_is_stale(self) -> None:
        decision = _identity_map_decision(
            target_trade_date="2026-05-29",
            stock_basic_status=_status(ready=True, storage_id=10),
            namechange_status=_status(ready=True, storage_id=11),
            identity_map_status=_status(ready=True, storage_id=9),
        )

        self.assertTrue(decision.request_run)
        self.assertFalse(decision.identity_map_current)

    def test_decision_skips_when_identity_map_is_current(self) -> None:
        decision = _identity_map_decision(
            target_trade_date="2026-05-29",
            stock_basic_status=_status(ready=True, storage_id=10),
            namechange_status=_status(ready=True, storage_id=11),
            identity_map_status=_status(ready=True, storage_id=12),
        )

        self.assertFalse(decision.request_run)
        self.assertTrue(decision.identity_map_current)


def _write_seed_fixture() -> Path:
    temp_dir = tempfile.TemporaryDirectory()
    seed_path = Path(temp_dir.name) / "stock_identity_mappings.cn_a.csv"
    with seed_path.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(STOCK_IDENTITY_MAPPINGS_SEED_COLUMNS)
        writer.writerow(
            [
                "920001.BJ",
                "830001.BJ",
                "2021-11-15",
                "",
                "bse_mapping",
                "confirmed",
                "seed row",
            ]
        )
    _TEMP_DIRS.append(temp_dir)
    return seed_path


def _status(
    *,
    ready: bool,
    storage_id: int | None = None,
    reason: str = "ready",
) -> AssetReadinessStatus:
    return AssetReadinessStatus(
        asset_key="asset",
        partition_key=None,
        ready=ready,
        materialized=storage_id is not None,
        checks_passed=ready,
        freshness_passed=True,
        materialization_storage_id=storage_id,
        materialization_date="2026-05-29" if storage_id is not None else None,
        missing_check_names=(),
        failed_check_names=(),
        reason=reason,
    )


_TEMP_DIRS: list[tempfile.TemporaryDirectory] = []


if __name__ == "__main__":
    unittest.main()

