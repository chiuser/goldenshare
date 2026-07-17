from pathlib import Path
import unittest

from orchestrator.defs.assets.dc_daily_technical_serving import (
    ch_dc_daily_technical,
    prod_ch_dc_daily_technical,
)
from orchestrator.defs.checks.dc_daily_technical_serving_checks import (
    CH_DC_DAILY_TECHNICAL_CHECK_NAME,
    PROD_CH_DC_DAILY_TECHNICAL_CHECK_NAME,
    ch_dc_daily_technical_core_check,
    prod_ch_dc_daily_technical_core_check,
)
from orchestrator.defs.jobs.dc_daily_technical_serving import (
    ch_dc_daily_technical_update_job,
    prod_ch_dc_daily_technical_sync_job,
)
from orchestrator.defs.partitions import cn_a_dc_daily_trade_days
from orchestrator.defs.sensors.dc_daily_technical_serving_sensor import (
    ch_dc_daily_technical_update_job_sensor,
)
from orchestrator.defs.sensors.prod_dc_daily_technical_sensor import (
    prod_ch_dc_daily_technical_continuity_sensor,
)


class DcDailyTechnicalServingDefinitionTests(unittest.TestCase):
    def test_asset_and_check_are_partitioned_and_check_is_blocking(self) -> None:
        self.assertEqual(ch_dc_daily_technical.partitions_def.name, cn_a_dc_daily_trade_days.name)
        specs = tuple(ch_dc_daily_technical_core_check.check_specs)
        self.assertEqual([spec.name for spec in specs], [CH_DC_DAILY_TECHNICAL_CHECK_NAME])
        self.assertTrue(specs[0].blocking)
        self.assertEqual(specs[0].partitions_def.name, cn_a_dc_daily_trade_days.name)

    def test_job_selects_only_serving_asset_and_its_check(self) -> None:
        selected = ch_dc_daily_technical_update_job.selection.resolve([ch_dc_daily_technical])
        self.assertIn(ch_dc_daily_technical.key, selected)
        self.assertEqual(
            ch_dc_daily_technical_update_job.partitions_def.name,
            cn_a_dc_daily_trade_days.name,
        )

    def test_sensor_is_stopped_and_has_no_event_history_api(self) -> None:
        self.assertEqual(
            str(ch_dc_daily_technical_update_job_sensor.default_status),
            "DefaultSensorStatus.STOPPED",
        )
        source = Path(
            "src/orchestrator/defs/sensors/dc_daily_technical_serving_sensor.py"
        ).read_text()
        self.assertNotIn("get_event_records", source)
        self.assertIn("minimum_interval_seconds=600", source)

    def test_prod_asset_check_job_and_sensor_are_partitioned(self) -> None:
        self.assertEqual(
            prod_ch_dc_daily_technical.partitions_def.name,
            cn_a_dc_daily_trade_days.name,
        )
        specs = tuple(prod_ch_dc_daily_technical_core_check.check_specs)
        self.assertEqual(
            [spec.name for spec in specs],
            [PROD_CH_DC_DAILY_TECHNICAL_CHECK_NAME],
        )
        self.assertTrue(specs[0].blocking)
        self.assertEqual(
            specs[0].partitions_def.name,
            cn_a_dc_daily_trade_days.name,
        )
        selected = prod_ch_dc_daily_technical_sync_job.selection.resolve(
            [prod_ch_dc_daily_technical]
        )
        self.assertIn(prod_ch_dc_daily_technical.key, selected)
        self.assertEqual(
            prod_ch_dc_daily_technical_sync_job.partitions_def.name,
            cn_a_dc_daily_trade_days.name,
        )
        self.assertEqual(
            str(prod_ch_dc_daily_technical_continuity_sensor.default_status),
            "DefaultSensorStatus.STOPPED",
        )
        source = Path(
            "src/orchestrator/defs/sensors/prod_dc_daily_technical_sensor.py"
        ).read_text()
        self.assertNotIn("get_event_records", source)
        self.assertIn("clickhouse_batch_queries", source)
