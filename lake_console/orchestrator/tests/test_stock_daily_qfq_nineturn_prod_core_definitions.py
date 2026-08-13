import unittest
from types import SimpleNamespace
from unittest.mock import patch

import dagster as dg

from orchestrator.defs.assets.stock_daily_qfq_nineturn_prod_core import (
    prod_core_stock_daily_qfq_nineturn,
)
from orchestrator.defs.catalog.lake_assets import get_lake_asset_catalog_entry
from orchestrator.defs.checks.stock_daily_qfq_nineturn_prod_core_checks import (
    prod_core_stock_daily_qfq_nineturn_partition_check,
)
from orchestrator.defs.jobs.stock_daily_qfq_nineturn_prod_core_sync import (
    prod_core_stock_daily_qfq_nineturn_sync_job,
)
from orchestrator.defs.sensors import (
    stock_daily_qfq_nineturn_prod_core_sensor as sensor_module,
)
from orchestrator.defs.sensors.readiness import DatasetReadinessStatus


class StockDailyQfqNineTurnProdCoreDefinitionTests(unittest.TestCase):
    def test_catalog_declares_serving_check_as_blocking(self) -> None:
        entry = get_lake_asset_catalog_entry(
            "prod_core_stock_daily_qfq_nineturn"
        )
        self.assertEqual(
            entry.blocking_check_names,
            ("prod_core_stock_daily_qfq_nineturn_partition_check",),
        )

    def test_serving_check_is_blocking_and_partitioned(self) -> None:
        spec = next(iter(prod_core_stock_daily_qfq_nineturn_partition_check.check_specs))
        self.assertTrue(spec.blocking)
        self.assertEqual(
            spec.name,
            "prod_core_stock_daily_qfq_nineturn_partition_check",
        )

    def test_daily_job_selects_serving_asset(self) -> None:
        selected = prod_core_stock_daily_qfq_nineturn_sync_job.selection.resolve(
            [prod_core_stock_daily_qfq_nineturn]
        )
        self.assertEqual(
            prod_core_stock_daily_qfq_nineturn_sync_job.name,
            "prod_core_stock_daily_qfq_nineturn_sync_job",
        )
        self.assertEqual(selected, {prod_core_stock_daily_qfq_nineturn.key})

    def test_sensor_is_stopped_and_requests_same_partition_when_gold_ready(self) -> None:
        self.assertEqual(
            sensor_module.prod_core_stock_daily_qfq_nineturn_sync_job_sensor.default_status,
            dg.DefaultSensorStatus.STOPPED,
        )
        context = SimpleNamespace(
            dagster_run=SimpleNamespace(
                run_id="gold-run-id",
                tags={"dagster/partition": "2026-08-12"},
            ),
            instance=object(),
        )
        with patch.object(
            sensor_module,
            "partition_dataset_readiness_status_from_latest_checks",
            return_value=DatasetReadinessStatus(ready=True, statuses=()),
        ):
            result = sensor_module._evaluate_sensor(context)

        self.assertIsInstance(result, dg.RunRequest)
        self.assertEqual(result.partition_key, "2026-08-12")
        self.assertIn("gold_stock_daily_qfq_nineturn_update", result.run_key)

    def test_sensor_skips_when_gold_check_is_not_ready(self) -> None:
        context = SimpleNamespace(
            dagster_run=SimpleNamespace(
                run_id="gold-run-id",
                tags={"dagster/partition": "2026-08-12"},
            ),
            instance=object(),
        )
        with patch.object(
            sensor_module,
            "partition_dataset_readiness_status_from_latest_checks",
            return_value=DatasetReadinessStatus(ready=False, statuses=()),
        ):
            result = sensor_module._evaluate_sensor(context)

        self.assertIsInstance(result, dg.SkipReason)


if __name__ == "__main__":
    unittest.main()
