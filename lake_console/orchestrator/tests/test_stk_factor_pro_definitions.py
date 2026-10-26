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
        self.assertTrue(factor_assets.isdisjoint(actual_assets))
        self.assertFalse(
            any(key.asset_key in factor_assets for key in graph.asset_check_keys)
        )
        self.assertTrue(
            {
                "raw_tushare_stk_factor_pro",
                "silver_stock_factor_pro",
            }.isdisjoint(list_lake_asset_keys())
        )

        repository = definitions.get_repository_def()
        self.assertTrue(
            {
                "raw_tushare_stk_factor_pro_update_job",
                "raw_tushare_stk_factor_pro_repair_job",
            }.isdisjoint(job.name for job in repository.get_all_jobs())
        )
        self.assertTrue(
            {
                "stock_factor_pro_trade_day_sensor",
                "raw_tushare_stk_factor_pro_update_job_sensor",
            }.isdisjoint(sensor.name for sensor in repository.sensor_defs)
        )
