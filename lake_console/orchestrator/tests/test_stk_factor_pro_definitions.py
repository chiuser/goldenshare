"""Load current project definitions under the existing protected consumer runner.

This checks source-definition loading only. It does not reload a running code
location or evaluate assets, checks, sensors, resources or a formal instance.
"""

import unittest

import dagster as dg


class StkFactorProDefinitionsTests(unittest.TestCase):
    def test_current_definitions_load_without_stock_factor_execution(self) -> None:
        from stock_suspend_confirmed_test_support import require_isolated_context

        from orchestrator.definitions import defs as project_defs
        from orchestrator.defs.catalog.lake_assets import list_lake_asset_keys

        allowed = require_isolated_context()
        self.assertTrue(allowed.is_absolute())
        definitions = project_defs()
        dg.Definitions.validate_loadable(definitions)
        graph = definitions.resolve_asset_graph()
        actual_assets = graph.get_all_asset_keys()
        self.assertIn(dg.AssetKey("raw_tushare_stock_daily"), actual_assets)

        factor_assets = {
            dg.AssetKey("raw_tushare_stk_factor_pro"),
            dg.AssetKey("silver_stock_factor_pro"),
        }
        self.assertTrue(factor_assets.issubset(actual_assets))
        self.assertEqual(
            {
                key.name
                for key in graph.asset_check_keys
                if key.asset_key in factor_assets
            },
            {
                "raw_tushare_stk_factor_pro_file_contract_check",
                "silver_stock_factor_pro_file_contract_check",
            },
        )
        self.assertTrue(
            {key.to_user_string() for key in factor_assets}.issubset(
                list_lake_asset_keys()
            )
        )

        repository = definitions.get_repository_def()
        jobs = {job.name for job in repository.get_all_jobs()}
        self.assertIn("raw_tushare_stk_factor_pro_update_job", jobs)
        self.assertIn("raw_tushare_stk_factor_pro_repair_job", jobs)
        sensors = {sensor.name: sensor for sensor in repository.sensor_defs}
        partition_sensor = sensors["stock_factor_pro_trade_day_sensor"]
        self.assertEqual(
            partition_sensor.default_status, dg.DefaultSensorStatus.STOPPED
        )
        self.assertEqual(partition_sensor.minimum_interval_seconds, 600)
        update_sensor = sensors["raw_tushare_stk_factor_pro_update_job_sensor"]
        self.assertEqual(update_sensor.default_status, dg.DefaultSensorStatus.STOPPED)
        self.assertEqual(update_sensor.minimum_interval_seconds, 60)
        self.assertEqual(
            update_sensor.tags,
            {
                "goldenshare/sensor_domain": "quote_data",
                "goldenshare/sensor_target_layer": "raw_silver",
                "goldenshare/sensor_role": "asset_update",
            },
        )
