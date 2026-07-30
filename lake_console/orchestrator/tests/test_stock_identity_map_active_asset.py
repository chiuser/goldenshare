import csv
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from orchestrator.defs.assets.stock_identity_map import (
    STOCK_LIFECYCLE_IDENTITY_CONFIDENCE,
    STOCK_LIFECYCLE_IDENTITY_SOURCE,
    build_stock_identity_map_rows,
    write_stock_identity_map_snapshot,
)
from orchestrator.defs.resources import DuckDBResource
from orchestrator.defs.run_contracts.cursors import load_sensor_cursor
from orchestrator.defs.sensors.readiness import AssetReadinessStatus
from orchestrator.defs.sensors.stock_identity_map_sensor import (
    _identity_map_decision,
    _latest_registered_trade_date,
    _source_window_started,
    stock_identity_map_sensor,
)
from orchestrator.seeds.basic.stock_identity_mappings import (
    STOCK_IDENTITY_MAPPINGS_SEED_COLUMNS,
    STOCK_IDENTITY_MAPPINGS_SEED_PATH,
    StockIdentityMappingSeedRow,
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

    def test_versioned_seed_covers_nineturn_historical_bse_code(self) -> None:
        seed_rows = load_stock_identity_mapping_seed(STOCK_IDENTITY_MAPPINGS_SEED_PATH)
        mapping = {
            row.source_ts_code: row.latest_ts_code
            for row in seed_rows
            if row.identity_source == "bse_mapping"
        }
        self.assertEqual(mapping["839680.BJ"], "920680.BJ")

    def test_build_rows_generates_self_and_seed_mappings(self) -> None:
        seed_rows = load_stock_identity_mapping_seed(_write_seed_fixture())
        result = build_stock_identity_map_rows(
            lifecycle_rows=(
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
            {"value": STOCK_LIFECYCLE_IDENTITY_SOURCE, "row_count": 2},
            result.source_distribution,
        )
        self.assertIn(
            {"value": STOCK_LIFECYCLE_IDENTITY_CONFIDENCE, "row_count": 3},
            result.confidence_distribution,
        )

    def test_build_rows_fails_when_seed_latest_code_missing(self) -> None:
        seed_rows = load_stock_identity_mapping_seed(_write_seed_fixture())
        with self.assertRaisesRegex(RuntimeError, "latest_ts_code not found"):
            build_stock_identity_map_rows(
                lifecycle_rows=(
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
            lifecycle_rows=(
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

    def test_build_rows_self_maps_delisted_historical_code(self) -> None:
        result = build_stock_identity_map_rows(
            lifecycle_rows=(
                {
                    "ts_code": "000638.SZ",
                    "list_date": date(1996, 11, 26),
                    "delist_date": date(2026, 6, 3),
                },
            ),
            seed_rows=(),
            namechange_codes=set(),
            created_at=datetime(2026, 7, 10, tzinfo=ZoneInfo("Asia/Shanghai")),
        )

        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["source_ts_code"], "000638.SZ")
        self.assertEqual(result.rows[0]["latest_ts_code"], "000638.SZ")
        self.assertEqual(result.rows[0]["valid_from"], date(1996, 11, 26))
        self.assertEqual(result.rows[0]["valid_to"], date(2026, 6, 3))
        self.assertEqual(
            result.rows[0]["identity_source"],
            STOCK_LIFECYCLE_IDENTITY_SOURCE,
        )

    def test_namechange_seed_can_target_delisted_lifecycle_code(self) -> None:
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
        )

        result = build_stock_identity_map_rows(
            lifecycle_rows=(
                {
                    "ts_code": "920305.BJ",
                    "list_date": date(2021, 8, 26),
                    "delist_date": date(2026, 7, 30),
                },
            ),
            seed_rows=seed_rows,
            namechange_codes={"920305.BJ"},
            created_at=datetime(2026, 7, 30, tzinfo=ZoneInfo("Asia/Shanghai")),
        )

        seed_row = next(
            row for row in result.rows if row["source_ts_code"] == "835305.BJ"
        )
        self.assertEqual(seed_row["latest_ts_code"], "920305.BJ")
        self.assertEqual(seed_row["effective_delist_date"], date(2026, 7, 30))


class StockIdentityMapSensorDecisionTests(unittest.TestCase):
    def test_window_starts_at_1730(self) -> None:
        timezone = ZoneInfo("Asia/Shanghai")
        self.assertFalse(
            _source_window_started(datetime(2026, 5, 31, 17, 29, tzinfo=timezone))
        )
        self.assertTrue(
            _source_window_started(datetime(2026, 5, 31, 17, 30, tzinfo=timezone))
        )

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
            stock_lifecycle_status=_status(ready=False, reason="stock lifecycle stale"),
            namechange_status=_status(ready=True, storage_id=2),
            identity_map_status=_status(ready=False, storage_id=1),
        )

        self.assertFalse(decision.request_run)
        self.assertIn("股票生命周期事实未 ready", decision.reason)

    def test_decision_requests_when_identity_map_is_stale(self) -> None:
        decision = _identity_map_decision(
            target_trade_date="2026-05-29",
            stock_lifecycle_status=_status(ready=True, storage_id=10),
            namechange_status=_status(ready=True, storage_id=11),
            identity_map_status=_status(ready=True, storage_id=9),
        )

        self.assertTrue(decision.request_run)
        self.assertFalse(decision.identity_map_current)

    def test_decision_skips_when_identity_map_is_current(self) -> None:
        decision = _identity_map_decision(
            target_trade_date="2026-05-29",
            stock_lifecycle_status=_status(ready=True, storage_id=10),
            namechange_status=_status(ready=True, storage_id=11),
            identity_map_status=_status(ready=True, storage_id=12),
        )

        self.assertFalse(decision.request_run)
        self.assertTrue(decision.identity_map_current)

    def test_sensor_request_cursor_is_human_readable_and_not_blocked(self) -> None:
        with patch(
            "orchestrator.defs.sensors.stock_identity_map_sensor.datetime",
            _FixedDateTime,
        ), patch(
            "orchestrator.defs.sensors.stock_identity_map_sensor.silver_stock_lifecycle_ready_without_freshness",
            return_value=_status(ready=True, storage_id=10),
        ), patch(
            "orchestrator.defs.sensors.stock_identity_map_sensor.silver_namechange_ready_for_trade_date",
            return_value=_status(ready=True, storage_id=11),
        ), patch(
            "orchestrator.defs.sensors.stock_identity_map_sensor.silver_stock_identity_map_ready_for_trade_date",
            return_value=_status(ready=True, storage_id=9),
        ):
            result = stock_identity_map_sensor._raw_fn(_FakeContext())

        self.assertEqual(len(result.run_requests), 1)
        cursor = load_sensor_cursor(result.cursor)
        self.assertLess(len(result.cursor or ""), 2000)
        self.assertEqual(cursor["details"]["reason_code"], "request_run")
        self.assertEqual(cursor["details"]["blocked_component"], "none")
        self.assertIn("summary", cursor["details"])
        self.assertIn("next_action", cursor["details"])
        self.assertEqual(
            cursor["details"]["evidence"]["target_trade_date"],
            "2026-05-29",
        )


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


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 5, 31, 17, 30, tzinfo=tz)


class _FakeInstance:
    def get_dynamic_partitions(self, _name: str) -> list[str]:
        return ["2026-05-29", "2026-06-01"]


class _FakeContext:
    instance = _FakeInstance()


_TEMP_DIRS: list[tempfile.TemporaryDirectory] = []


if __name__ == "__main__":
    unittest.main()
