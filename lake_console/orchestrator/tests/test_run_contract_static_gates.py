import ast
import unittest
from pathlib import Path

from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
)


DEFS_DIR = Path("src/orchestrator/defs")
AUDITS_DIR = Path("src/orchestrator/audits")
ASSETS_DIR = DEFS_DIR / "assets"
CHECKS_DIR = DEFS_DIR / "checks"
CATALOG_DIR = DEFS_DIR / "catalog"
JOBS_DIR = DEFS_DIR / "jobs"
SENSORS_DIR = DEFS_DIR / "sensors"
SCHEDULES_DIR = DEFS_DIR / "schedules"
QFQ_SOURCE_FILES = (
    DEFS_DIR / "assets" / "stk_mins.py",
    DEFS_DIR / "stk_mins_qfq.py",
    DEFS_DIR / "stk_mins_qfq_factor_repair.py",
)
QFQ_AS_OF_SOURCE_FILES = (
    *QFQ_SOURCE_FILES,
    DEFS_DIR / "checks" / "stk_mins_checks.py",
    DEFS_DIR / "bootstrap" / "stk_mins_qfq_history.py",
    DEFS_DIR / "bootstrap" / "stk_mins_qfq_bootstrap_events.py",
    AUDITS_DIR / "stk_mins_qfq_performance.py",
)
GOLD_STK_MINS_QFQ_MACD_KDJ_SOURCE_FILES = (
    DEFS_DIR / "stk_mins_qfq_macd_kdj.py",
    DEFS_DIR / "assets" / "stk_mins_qfq_macd_kdj.py",
    DEFS_DIR / "checks" / "stk_mins_qfq_macd_kdj_checks.py",
    DEFS_DIR / "ops" / "gold_stk_mins_qfq_macd_kdj_repair.py",
    DEFS_DIR / "sensors" / "gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor.py",
    DEFS_DIR / "sensors" / "gold_stk_mins_qfq_macd_kdj_repair_job_sensor.py",
    DEFS_DIR / "bootstrap" / "stk_mins_qfq_macd_kdj_history.py",
    DEFS_DIR / "bootstrap" / "stk_mins_qfq_macd_kdj_baseline_events.py",
)
GOLD_WEALTH_MARKET_TURNOVER_SOURCE_FILES = (
    DEFS_DIR / "wealth_market_turnover_contract.py",
    DEFS_DIR / "assets" / "wealth_market_turnover.py",
    DEFS_DIR / "checks" / "wealth_market_turnover_checks.py",
    DEFS_DIR / "asset_guards" / "wealth_market_turnover_lake_readiness.py",
    DEFS_DIR / "jobs" / "gold_wealth_market_turnover_update.py",
    DEFS_DIR / "sensors" / "gold_wealth_market_turnover_sensor.py",
    DEFS_DIR / "bootstrap" / "wealth_market_turnover_history.py",
    DEFS_DIR / "bootstrap" / "wealth_market_turnover_history_cli.py",
    DEFS_DIR / "bootstrap" / "wealth_market_turnover_runless_events.py",
    DEFS_DIR / "bootstrap" / "wealth_market_turnover_runless_events_cli.py",
)
GOLD_WEALTH_MARKET_TURNOVER_PROD_SYNC_FILES = (
    DEFS_DIR / "resources.py",
    DEFS_DIR / "prod_db" / "wealth_market_turnover.py",
    DEFS_DIR / "assets" / "wealth_market_turnover_prod_core.py",
)
MACD_KDJ_DIRECT_RUN_REQUEST_SENSOR_FILES: set[str] = set()
DUCKDB_CONNECTION_HELPER = DEFS_DIR / "duckdb_connection.py"

FORBIDDEN_QFQ_SUMMARY_IDENTIFIERS = {
    "gold_stk_mins_qfq_daily_summary",
    "gold_stk_mins_qfq_factor_repair_summary",
}
GOLD_STK_MINS_QFQ_WRITER_POOL_LITERAL = "gold_stk_mins_qfq_writer"

SENSOR_FORBIDDEN_STRING_LITERALS = {
    "triggered_by",
    "asset_family",
    "index_ts_code",
    "merge_repair",
    "raw_tushare_index_daily_by_code",
}

LEGACY_METADATA_KEYS = {
    "path",
    "raw_path",
    "silver_path",
    "gold_path",
    "paths",
    "missing_paths",
    "row_count",
    "columns",
    "schema",
    "layer",
    "source_api",
    "data_contract",
}

SENSOR_DEFINITION_CALL_NAMES = {
    "sensor",
    "run_status_sensor",
    "run_failure_sensor",
    "AutomationConditionSensorDefinition",
}
RUN_KEY_BUILDER_CALL_NAMES = {
    "build_asset_update_run_key",
    "build_repair_attempt_run_key",
    "build_upstream_triggered_run_key",
}

ASSETS_WITHOUT_COLUMN_SCHEMA = {"lake_root_health"}


def _python_files(directory: Path) -> tuple[Path, ...]:
    return tuple(
        path for path in sorted(directory.glob("*.py")) if path.name != "__init__.py"
    )


def _sensor_definition_files() -> tuple[Path, ...]:
    return tuple(
        path for path in _python_files(SENSORS_DIR) if path.name.endswith("_sensor.py")
    )


def _parse_python_file(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_call_named(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Call) and _call_name(node.func) == name


def _is_sensor_definition_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and (
        _call_name(node.func) in SENSOR_DEFINITION_CALL_NAMES
    )


def _keyword_value(call: ast.Call, keyword_name: str) -> ast.AST | None:
    for keyword in call.keywords:
        if keyword.arg == keyword_name:
            return keyword.value
    return None


def _direct_string_keys(dict_node: ast.Dict) -> set[str]:
    return {
        key.value
        for key in dict_node.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def _dict_keys_for_keyword(call: ast.Call, keyword_name: str) -> set[str]:
    value = _keyword_value(call, keyword_name)
    return _direct_string_keys(value) if isinstance(value, ast.Dict) else set()


def _node_location(path: Path, node: ast.AST) -> str:
    return f"{path}:{getattr(node, 'lineno', '?')}"


def _function_source(path: Path, function_name: str) -> str:
    source = path.read_text()
    tree = ast.parse(source, filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"{path} does not define {function_name}")


def _enum_attribute(node: ast.AST, enum_name: str) -> str | None:
    if not isinstance(node, ast.Attribute):
        return None
    if not isinstance(node.value, ast.Name):
        return None
    if node.value.id != enum_name:
        return None
    return node.attr


def _check_metadata_builder_names(tree: ast.Module) -> set[str]:
    builder_names = {"build_check_metadata"}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Return) and _is_call_named(
                child.value,
                "build_check_metadata",
            ):
                builder_names.add(node.name)
    return builder_names


def _is_allowed_sensor_run_config_dict(path: Path, dict_node: ast.Dict) -> bool:
    return path.name in (
        "stock_mins_qfq_factor_repair_sensor.py",
        "gold_stk_mins_qfq_macd_kdj_repair_job_sensor.py",
    ) and "ops" in _direct_string_keys(dict_node)


def _is_allowed_direct_run_request(path: Path) -> bool:
    return path.name in MACD_KDJ_DIRECT_RUN_REQUEST_SENSOR_FILES


def _is_allowed_direct_run_request_tags(path: Path) -> bool:
    return False


def _is_allowed_sensor_run_key_value(path: Path, node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and _call_name(node.func) in RUN_KEY_BUILDER_CALL_NAMES
    )


class RunContractStaticGateTests(unittest.TestCase):
    def test_dc_board_m3_writers_keep_raw_only_bounded_boundary(self) -> None:
        writer_path = DEFS_DIR / "assets" / "dc_board.py"
        bootstrap_path = DEFS_DIR / "bootstrap" / "dc_board_bootstrap.py"
        resource_path = DEFS_DIR / "resources.py"
        writer_source = writer_path.read_text()
        bootstrap_source = bootstrap_path.read_text()
        resource_source = resource_path.read_text()

        for required in (
            "execute_bounded_pages",
            "execute_bounded_code_pages",
            "copy_query_to_parquet",
            "os.replace",
            "write_dc_member_rows_streaming",
            "source_method",
        ):
            self.assertIn(required, writer_source)
        for forbidden in (
            "TushareResource.call(",
            "report_runless_asset_event",
            "@dg.asset",
            "@dg.asset_check",
            "@dg.job",
            "@dg.sensor",
            "select *",
            "SELECT *",
        ):
            self.assertNotIn(forbidden, writer_source)

        self.assertIn("connect_readonly_transaction", bootstrap_source)
        self.assertIn("fetchmany", bootstrap_source)
        self.assertIn("DC_MEMBER_BOOTSTRAP_SELECT_SQL", bootstrap_source)
        self.assertNotIn("fetchall", bootstrap_source)
        self.assertNotIn("ProdPostgresWriteResource", bootstrap_source)
        self.assertNotIn("prod_postgres_write", bootstrap_source)
        self.assertNotIn("SELECT *", bootstrap_source)
        self.assertNotIn("report_runless_asset_event", bootstrap_source)

        self.assertIn("connection.set_session(readonly=True, autocommit=False)", resource_source)
        self.assertIn("connection.rollback()", resource_source)

    def test_dc_board_m4_keeps_partitioned_checks_and_hot_path_boundary(self) -> None:
        asset_path = ASSETS_DIR / "dc_board_raw.py"
        check_path = CHECKS_DIR / "dc_board_checks.py"
        readiness_path = DEFS_DIR / "asset_guards" / "dc_board_lake_readiness.py"
        jobs_path = JOBS_DIR / "dc_board.py"
        sensors_path = SENSORS_DIR / "dc_board_sensor.py"
        asset_source = asset_path.read_text()
        check_source = check_path.read_text()
        readiness_source = readiness_path.read_text()
        jobs_source = jobs_path.read_text()
        sensors_source = sensors_path.read_text()

        for check_name in (
            "raw_tushare_dc_index_core_check",
            "raw_tushare_dc_member_core_check",
            "raw_tushare_dc_daily_core_check",
        ):
            self.assertIn(check_name, check_source)
        self.assertEqual(check_source.count("partitions_def=cn_a_index_trade_days"), 3)
        self.assertIn("blocking=True", check_source)

        for source in (asset_source, readiness_source, sensors_source):
            self.assertNotIn("get_event_records", source)
        self.assertNotIn("ProdPostgresResource", sensors_source)
        self.assertNotIn("TushareResource.call(", asset_source)
        self.assertIn("plan_dc_member_candidate_codes", asset_source)
        self.assertIn("DC_BOARD_MAX_REQUESTS_PER_PARTITION", asset_source)
        self.assertIn("read_parquet", readiness_source)
        self.assertIn("DC_BOARD_SENSOR_WINDOW_LIMIT", sensors_source)
        self.assertIn("build_asset_update_run_key", sensors_source)
        self.assertNotIn("AssetSelection.assets(silver_", jobs_source)
        self.assertEqual(jobs_source.count("dg.define_asset_job("), 3)

    def test_dc_board_m5_keeps_silver_partition_boundary_and_no_automation(self) -> None:
        asset_path = ASSETS_DIR / "dc_board_silver.py"
        check_path = CHECKS_DIR / "dc_board_silver_checks.py"
        asset_source = asset_path.read_text()
        check_source = check_path.read_text()

        for asset_name in ("silver_dc_index", "silver_dc_member", "silver_dc_daily"):
            self.assertIn(f'name="{asset_name}"', asset_source)
        for check_name in (
            "silver_dc_index_core_check",
            "silver_dc_member_core_check",
            "silver_dc_daily_core_check",
        ):
            self.assertIn(f'name="{check_name}"', check_source)

        self.assertEqual(asset_source.count("@dg.asset("), 3)
        self.assertEqual(check_source.count("@dg.asset_check("), 3)
        self.assertEqual(check_source.count("partitions_def=cn_a_index_trade_days"), 3)
        self.assertEqual(check_source.count("blocking=True"), 3)
        self.assertIn("read_parquet", asset_source)
        self.assertIn("silver_trade_calendar_path", asset_source)
        self.assertIn("os.replace", asset_source)
        self.assertNotIn("get_event_records", asset_source + check_source)
        self.assertNotIn("TushareResource", asset_source + check_source)
        self.assertNotIn("ProdPostgresResource", asset_source + check_source)
        self.assertNotIn("AssetSelection", asset_source + check_source)

    def test_gold_wealth_market_turnover_keeps_source_boundary(self) -> None:
        forbidden_fragments = (
            "src.biz",
            "TurnoverSnapshotMaterializeService",
            "WealthMarketTurnoverSnapshot",
            "TushareResource",
            "ProdPostgresResource",
            "raw_stk_mins_path",
            "core_serving.wealth_market_turnover_snapshot",
        )
        issues = []
        for path in GOLD_WEALTH_MARKET_TURNOVER_SOURCE_FILES:
            source = path.read_text()
            for fragment in forbidden_fragments:
                if fragment in source:
                    issues.append(
                        f"{path} contains forbidden wealth turnover fragment: {fragment}"
                    )

        self.assertEqual(issues, [])

    def test_dc_board_silver_sensor_is_bounded_and_event_history_free(self) -> None:
        sensor_path = DEFS_DIR / "sensors" / "dc_board_silver_sensor.py"
        readiness_path = DEFS_DIR / "asset_guards" / "dc_board_silver_lake_readiness.py"
        jobs_path = DEFS_DIR / "jobs" / "dc_board_silver.py"
        sensor_source = sensor_path.read_text()
        readiness_source = readiness_path.read_text()
        jobs_source = jobs_path.read_text()

        for fragment in (
            "DC_BOARD_SENSOR_WINDOW_LIMIT",
            "batch_raw_dc_index_lake_readiness",
            "batch_silver_dc_index_lake_readiness",
            "select_first_not_ready_trade_date",
            "build_run_request",
            "build_asset_update_run_key",
            "default_status=dg.DefaultSensorStatus.STOPPED",
        ):
            self.assertIn(fragment, sensor_source)
        for forbidden in (
            "get_event_records(",
            "get_asset_check_execution_history(",
            "partition_dataset_readiness_status_from_latest_checks",
            "dg.RunRequest(",
            "run_key.split",
        ):
            self.assertNotIn(forbidden, sensor_source)
        self.assertIn("ContinuityBatchReadiness", readiness_source)
        self.assertIn("SILVER_DC_QUALITY_SPECS", readiness_source)
        self.assertNotIn("get_event_records(", readiness_source)
        self.assertNotIn("AssetSelection.assets(raw_", jobs_source)

    def test_gold_wealth_market_turnover_keeps_single_json_integrity_check(self) -> None:
        schema_source = (
            DEFS_DIR / "run_contracts" / "asset_column_schemas.py"
        ).read_text()
        catalog_source = (CATALOG_DIR / "lake_assets.py").read_text()
        check_source = (CHECKS_DIR / "wealth_market_turnover_checks.py").read_text()

        self.assertIn('ColumnContract("points_json", "JSON"', schema_source)
        self.assertNotIn('ColumnContract("points_json", "VARCHAR"', schema_source)
        self.assertIn(
            'GOLD_WEALTH_MARKET_TURNOVER_CHECKS = (\n'
            '    "gold_wealth_market_turnover_integrity_check",\n'
            ')',
            catalog_source,
        )
        self.assertEqual(check_source.count("@dg.asset_check"), 1)

    def test_gold_wealth_market_turnover_prod_sync_boundary(self) -> None:
        resource_source = (DEFS_DIR / "resources.py").read_text()
        prod_db_source = (
            DEFS_DIR / "prod_db" / "wealth_market_turnover.py"
        ).read_text()
        gold_asset_source = (
            DEFS_DIR / "assets" / "wealth_market_turnover.py"
        ).read_text()
        sensor_source = (
            DEFS_DIR / "sensors" / "gold_wealth_market_turnover_sensor.py"
        ).read_text()

        self.assertIn("class ProdPostgresResource", resource_source)
        self.assertIn(
            "connection.set_session(readonly=True, autocommit=True)",
            resource_source,
        )
        self.assertIn("class ProdPostgresWriteResource", resource_source)
        self.assertIn(
            "connection.set_session(readonly=False, autocommit=False)",
            resource_source,
        )
        self.assertIn('"prod_postgres_write": ProdPostgresWriteResource()', resource_source)
        self.assertIn("PROD_POSTGRES_WRITE_USER", resource_source)

        self.assertNotIn("select *", prod_db_source.lower())
        for required_fragment in (
            "PROD_CORE_WEALTH_MARKET_TURNOVER_FORBIDDEN_COLUMNS",
            "PROD_CORE_WEALTH_MARKET_TURNOVER_DELETE_SQL",
            "PROD_CORE_WEALTH_MARKET_TURNOVER_INSERT_SQL",
            "PROD_CORE_WEALTH_MARKET_TURNOVER_SELECT_SQL",
            "replace_prod_core_wealth_market_turnover_partition",
        ):
            self.assertIn(required_fragment, prod_db_source)

        for forbidden_fragment in (
            "ProdPostgresWriteResource",
            "prod_postgres_write",
            "replace_prod_core_wealth_market_turnover_partition",
            "core_serving.wealth_market_turnover_snapshot",
        ):
            self.assertNotIn(forbidden_fragment, gold_asset_source)

        independent_prod_jobs = [
            path.name
            for path in JOBS_DIR.glob("prod_core_wealth_market_turnover*job*.py")
        ]
        self.assertEqual(independent_prod_jobs, [])
        self.assertIn("PROD_CORE_WEALTH_MARKET_TURNOVER_ASSET_KEY", sensor_source)
        self.assertIn("prod_sync_failed_requires_manual_retry", sensor_source)
        self.assertIn('DAGSTER_RUN_KEY_TAG = "dagster/run_key"', sensor_source)
        for forbidden_fragment in (
            "ProdPostgresWriteResource",
            "prod_postgres_write",
            "replace_prod_core_wealth_market_turnover_partition",
            "core_serving.wealth_market_turnover_snapshot",
        ):
            self.assertNotIn(forbidden_fragment, sensor_source)

    def test_gold_wealth_market_turnover_prod_sync_reads_gold_only(self) -> None:
        prod_asset_source = (
            DEFS_DIR / "assets" / "wealth_market_turnover_prod_core.py"
        ).read_text()
        for required_fragment in (
            "deps=[gold_wealth_market_turnover]",
            "gold_wealth_market_turnover_path",
            "ProdPostgresWriteResource",
            "replace_prod_core_wealth_market_turnover_partition",
        ):
            self.assertIn(required_fragment, prod_asset_source)
        for forbidden_fragment in (
            "silver_stk_mins_path",
            "raw_stk_mins_path",
            "TushareResource",
            "src.biz",
            "TurnoverSnapshotMaterializeService",
            "WealthMarketTurnoverSnapshot",
        ):
            self.assertNotIn(forbidden_fragment, prod_asset_source)

    def test_gold_wealth_market_turnover_human_readable_governance_stays_compact(
        self,
    ) -> None:
        gold_asset_source = (
            DEFS_DIR / "assets" / "wealth_market_turnover.py"
        ).read_text()
        prod_asset_source = (
            DEFS_DIR / "assets" / "wealth_market_turnover_prod_core.py"
        ).read_text()
        check_source = (CHECKS_DIR / "wealth_market_turnover_checks.py").read_text()
        sensor_source = (
            SENSORS_DIR / "gold_wealth_market_turnover_sensor.py"
        ).read_text()
        issues = []

        for fragment in (
            "gold_wealth_market_turnover_started",
            "gold_wealth_market_turnover_completed",
            "metric_summary",
            "五频度",
            "points_json",
        ):
            if fragment not in gold_asset_source:
                issues.append(f"wealth gold asset misses readable fragment: {fragment}")

        for fragment in (
            "prod_core_wealth_market_turnover_started",
            "prod_core_wealth_market_turnover_completed",
            "serving_summary",
            "core_serving.wealth_market_turnover_snapshot",
        ):
            if fragment not in prod_asset_source:
                issues.append(f"wealth prod asset misses readable fragment: {fragment}")

        for fragment in ("summary", "next_action", "rule_summary"):
            if fragment not in check_source:
                issues.append(f"wealth check misses readable metadata: {fragment}")

        for fragment in (
            "_summary_and_next_action",
            "五频度还没有全部 ready",
            "prod core serving",
            "延后 10 分钟",
        ):
            if fragment not in sensor_source:
                issues.append(f"wealth sensor cursor misses readable fragment: {fragment}")

        for fragment in (
            "status_samples",
            "to_cursor_details()",
            "input_file_paths=",
            "points_json=",
            "sample_rows=",
        ):
            if fragment in sensor_source:
                issues.append(f"wealth sensor cursor contains bulky fragment: {fragment}")

        self.assertEqual(issues, [])

    def test_stock_mins_silver_job_does_not_pull_raw_or_source_config(self) -> None:
        path = JOBS_DIR / "stock_mins_silver_update.py"
        source = path.read_text()
        forbidden_fragments = (
            "RAW_STK_MINS_ASSETS",
            "Tushare",
            "ProdPostgres",
            "build_stock_mins_raw_update_job_run_config",
            "STOCK_MINS_RAW_CONFIG_SCHEMA",
            "raw_stk_mins_",
            '"ops"',
            "'ops'",
            "run_tags",
        )
        issues = [
            f"{path} contains forbidden stock_mins silver job fragment: {fragment}"
            for fragment in forbidden_fragments
            if fragment in source
        ]

        self.assertEqual(issues, [])

    def test_stock_mins_raw_silver_human_readable_governance_stays_compact(
        self,
    ) -> None:
        asset_source = (ASSETS_DIR / "stk_mins.py").read_text()
        check_source = (CHECKS_DIR / "stk_mins_checks.py").read_text()
        raw_sensor_source = (
            SENSORS_DIR / "stock_mins_raw_sensor.py"
        ).read_text()
        silver_sensor_source = (
            SENSORS_DIR / "stock_mins_silver_sensor.py"
        ).read_text()
        issues = []

        for fragment in (
            "raw_stk_mins_started",
            "raw_stk_mins_completed",
            "raw_stk_mins_repair_started",
            "raw_stk_mins_repair_completed",
            "silver_stk_mins_started",
            "silver_stk_mins_completed",
            "_raw_stk_mins_human_metadata",
            "_silver_stk_mins_human_metadata",
        ):
            if fragment not in asset_source:
                issues.append(f"stk_mins asset misses readable fragment: {fragment}")

        for fragment in ("summary", "next_action", "rule_summary", "failed_rule_names"):
            if fragment not in check_source:
                issues.append(f"stk_mins check misses readable metadata: {fragment}")

        sensor_requirements = {
            "raw": (
                raw_sensor_source,
                (
                    "_cursor_summary_and_next_action",
                    "股票分钟线 raw 五频度更新",
                    "stock_mins_raw_update_from_prod_job",
                    "raw_stk_mins checks",
                ),
            ),
            "silver": (
                silver_sensor_source,
                (
                    "_cursor_summary_and_next_action",
                    "股票分钟线 silver 五频度更新",
                    "stock_mins_silver_update_job",
                    "raw_stk_mins 五频度",
                    "silver_stk_mins checks",
                ),
            ),
        }
        for name, (source, required_fragments) in sensor_requirements.items():
            for fragment in required_fragments:
                if fragment not in source:
                    issues.append(f"{name} stock_mins sensor misses {fragment}")

        forbidden_sensor_fragments = (
            "status_samples",
            "to_cursor_details()",
            "readiness_details",
            "repair_details",
            "sample_rows",
        )
        for name, source in (
            ("raw", raw_sensor_source),
            ("silver", silver_sensor_source),
        ):
            for fragment in forbidden_sensor_fragments:
                if fragment in source:
                    issues.append(f"{name} stock_mins sensor contains {fragment}")

        self.assertEqual(issues, [])

    def test_stock_mins_qfq_human_readable_governance_stays_compact(self) -> None:
        asset_source = (ASSETS_DIR / "stk_mins.py").read_text()
        check_source = (CHECKS_DIR / "stk_mins_checks.py").read_text()
        daily_sensor_source = (
            SENSORS_DIR / "stock_mins_qfq_daily_sensor.py"
        ).read_text()
        repair_sensor_source = (
            SENSORS_DIR / "stock_mins_qfq_factor_repair_sensor.py"
        ).read_text()
        issues = []

        for fragment in (
            "gold_stk_mins_qfq_started",
            "gold_stk_mins_qfq_completed",
            "gold_stk_mins_qfq_derived_started",
            "gold_stk_mins_qfq_derived_completed",
            "_gold_stk_mins_qfq_human_metadata",
            "_gold_stk_mins_qfq_derived_human_metadata",
        ):
            if fragment not in asset_source:
                issues.append(f"qfq asset misses readable fragment: {fragment}")

        for fragment in (
            "股票 {freq} 分钟 gold qfq",
            "派生输入覆盖",
            "rule_summary",
            "failed_rule_names",
            "next_action",
        ):
            if fragment not in check_source:
                issues.append(f"qfq check misses readable fragment: {fragment}")

        sensor_requirements = {
            "daily": (
                daily_sensor_source,
                (
                    "_cursor_summary_and_next_action",
                    "gold qfq 七频度更新",
                    "silver_adj_factor",
                    "gold_stk_mins_qfq checks",
                ),
            ),
            "repair": (
                repair_sensor_source,
                (
                    "_cursor_summary_and_next_action",
                    "qfq factor repair",
                    "stock_mins_qfq_factor_repair_job",
                    "gold_stk_mins_qfq 七频度",
                ),
            ),
        }
        for name, (source, required_fragments) in sensor_requirements.items():
            for fragment in required_fragments:
                if fragment not in source:
                    issues.append(f"{name} qfq sensor misses {fragment}")

        forbidden_sensor_fragments = (
            "status_samples",
            "to_cursor_details()",
            "readiness_details",
            "repair_details",
            "sample_rows",
        )
        for name, source in (
            ("daily", daily_sensor_source),
            ("repair", repair_sensor_source),
        ):
            for fragment in forbidden_sensor_fragments:
                if fragment in source:
                    issues.append(f"{name} qfq sensor contains {fragment}")

        self.assertEqual(issues, [])

    def test_stock_mins_macd_kdj_human_readable_governance_stays_compact(
        self,
    ) -> None:
        asset_source = (ASSETS_DIR / "stk_mins_qfq_macd_kdj.py").read_text()
        check_source = (CHECKS_DIR / "stk_mins_qfq_macd_kdj_checks.py").read_text()
        daily_sensor_source = (
            SENSORS_DIR / "gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor.py"
        ).read_text()
        repair_op_source = (
            DEFS_DIR / "ops" / "gold_stk_mins_qfq_macd_kdj_repair.py"
        ).read_text()
        repair_sensor_source = (
            SENSORS_DIR / "gold_stk_mins_qfq_macd_kdj_repair_job_sensor.py"
        ).read_text()
        issues = []

        for fragment in (
            "gold_stk_mins_qfq_macd_kdj_started",
            "gold_stk_mins_qfq_macd_kdj_indicator_completed",
            "gold_stk_mins_qfq_macd_kdj_state_completed",
            "_macd_kdj_indicator_human_metadata",
            "_macd_kdj_state_human_metadata",
            "previous_state_ready",
            "initialized_without_previous_state",
        ):
            if fragment not in asset_source:
                issues.append(f"MACD/KDJ asset misses readable fragment: {fragment}")

        for fragment in (
            "_readable_check_metadata",
            "MACD/KDJ source 覆盖",
            "MACD/KDJ state 最新覆盖",
            "rule_summary",
            "failed_rule_names",
            "next_action",
        ):
            if fragment not in check_source:
                issues.append(f"MACD/KDJ check misses readable fragment: {fragment}")

        for fragment in (
            "next_action",
            "下一步：",
            "qfq factor repair",
            "上一 expected 交易日",
            "MACD/KDJ indicator/state",
        ):
            if fragment not in daily_sensor_source:
                issues.append(f"MACD/KDJ daily sensor misses readable fragment: {fragment}")

        for fragment in (
            "cursor=",
            "status_samples",
            "to_cursor_details()",
            "readiness_details",
            "sample_rows",
        ):
            if fragment in daily_sensor_source:
                issues.append(f"MACD/KDJ daily sensor contains {fragment}")

        for fragment in (
            "DgStdoutLogger",
            "gold_stk_mins_qfq_macd_kdj_repair_started",
            "gold_stk_mins_qfq_macd_kdj_repair_completed",
            "_repair_completion_human_metadata",
            "repair_completed",
            "diagnostic_ref",
            "source_upstream_batch_id",
        ):
            if fragment not in repair_op_source:
                issues.append(f"MACD/KDJ repair op misses readable fragment: {fragment}")

        for fragment in (
            "next_action",
            "下一步：",
            "completion check",
            "upstream_batch_id",
        ):
            if fragment not in repair_sensor_source:
                issues.append(
                    f"MACD/KDJ repair sensor misses readable fragment: {fragment}"
                )

        for fragment in (
            "cursor=",
            "status_samples",
            "to_cursor_details()",
            "readiness_details",
            "sample_rows",
            "source_qfq_factor_repair_event_storage_ids",
        ):
            if fragment in repair_sensor_source:
                issues.append(f"MACD/KDJ repair sensor contains {fragment}")

        self.assertEqual(issues, [])

    def test_gold_stk_mins_qfq_macd_kdj_formal_code_avoids_recursive_cte_and_row_loops(
        self,
    ) -> None:
        issues = []
        for path in GOLD_STK_MINS_QFQ_MACD_KDJ_SOURCE_FILES:
            source = path.read_text()
            lowered = source.lower()
            if "with recursive" in lowered:
                issues.append(f"{path} contains forbidden recursive CTE")
            tree = _parse_python_file(path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.For):
                    continue
                target_name = getattr(node.target, "id", "")
                if target_name == "row" and path.name.endswith("_checks.py"):
                    continue
                if target_name in {"row", "record", "stock_code", "ts_code"}:
                    issues.append(
                        f"{_node_location(path, node)} contains forbidden primary "
                        f"Python loop target: {target_name}"
                    )

        self.assertEqual(issues, [])

    def test_gold_stk_mins_qfq_macd_kdj_entrypoints_keep_contract_boundaries(
        self,
    ) -> None:
        issues = []
        job_path = JOBS_DIR / "gold_stk_mins_qfq_macd_kdj_daily_update.py"
        repair_job_path = JOBS_DIR / "gold_stk_mins_qfq_macd_kdj_repair.py"
        sensor_path = SENSORS_DIR / "gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor.py"
        repair_sensor_path = SENSORS_DIR / "gold_stk_mins_qfq_macd_kdj_repair_job_sensor.py"
        asset_path = ASSETS_DIR / "stk_mins_qfq_macd_kdj.py"
        repair_op_path = DEFS_DIR / "ops" / "gold_stk_mins_qfq_macd_kdj_repair.py"

        for path in (job_path, repair_job_path):
            source = path.read_text()
            forbidden_fragments = (
                "DuckDB",
                "duckdb",
                "read_parquet",
                "COPY",
                "gold_stk_mins_qfq_macd_kdj_path",
                "gold_stk_mins_qfq_macd_kdj_state_path",
                "sql",
                "run_tags",
            )
            issues.extend(
                f"{path} contains forbidden MACD/KDJ job fragment: {fragment}"
                for fragment in forbidden_fragments
                if fragment in source
            )

        macd_kdj_job_source = job_path.read_text()
        check_refresh_start = macd_kdj_job_source.find(
            "gold_stk_mins_qfq_macd_kdj_check_refresh_job = dg.define_asset_job("
        )
        if check_refresh_start == -1:
            issues.append("MACD/KDJ checks-only refresh job is missing")
        else:
            check_refresh_source = macd_kdj_job_source[check_refresh_start:]
            expected_check_refresh_selection = (
                "selection=dg.AssetSelection.checks_for_assets(\n"
                "        *GOLD_STK_MINS_QFQ_MACD_KDJ_ASSETS\n"
                "    )"
            )
            if expected_check_refresh_selection not in check_refresh_source:
                issues.append(
                    "MACD/KDJ checks-only refresh job must select checks_for_assets"
                )
            if (
                "partitions_def=cn_a_stock_mins_silver_trade_days"
                not in check_refresh_source
            ):
                issues.append(
                    "MACD/KDJ checks-only refresh job must declare the stock mins "
                    "silver trade-day partitions_def"
                )
            if "AssetSelection.assets" in check_refresh_source:
                issues.append(
                    "MACD/KDJ checks-only refresh job must not select materializable "
                    "assets"
                )

        macd_kdj_checks_source = (
            CHECKS_DIR / "stk_mins_qfq_macd_kdj_checks.py"
        ).read_text()
        if (
            macd_kdj_checks_source.count(
                "partitions_def=cn_a_stock_mins_silver_trade_days"
            )
            != 2
        ):
            issues.append(
                "MACD/KDJ indicator and state check builders must declare the "
                "stock mins silver trade-day partitions_def"
            )

        sensor_source = sensor_path.read_text()
        required_sensor_fragments = (
            "run_status_sensor",
            "request_job=gold_stk_mins_qfq_macd_kdj_daily_update_job",
            "monitored_jobs=[stock_mins_qfq_daily_update_job, stock_mins_qfq_factor_repair_job]",
            "DEFAULT_LAKE_ROOT",
            "connect_configured_duckdb",
            "load_stock_mins_expected_trade_dates",
            "previous_expected_trade_date",
            "is_first_expected_trade_date",
            "partition_dataset_readiness_status_from_latest_checks",
            "gold_stk_mins_qfq_factor_repair_status",
            "batch_gold_stk_mins_qfq_lake_readiness",
            "build_sensor_tags",
        )
        forbidden_sensor_fragments = (
            "get_asset_check_execution_history",
            "duckdb.connect",
            "read_parquet",
            "GOLD_STK_MINS_QFQ_READINESS_SPECS",
            "_previous_registered_trade_date",
            "gold_stk_mins_qfq_macd_kdj_path",
            "PENDING_QFQ_FACTOR_REPAIR_TAG",
            "target_trade_date == STK_MINS_MACD_KDJ_BASELINE_START_DATE",
            "target_trade_date != STK_MINS_MACD_KDJ_BASELINE_START_DATE",
        )
        issues.extend(
            f"{sensor_path} misses MACD/KDJ daily sensor fragment: {fragment}"
            for fragment in required_sensor_fragments
            if fragment not in sensor_source
        )
        issues.extend(
            f"{sensor_path} contains forbidden MACD/KDJ daily sensor fragment: {fragment}"
            for fragment in forbidden_sensor_fragments
            if fragment in sensor_source
        )
        repair_sensor_source = repair_sensor_path.read_text()
        required_repair_sensor_fragments = (
            "run_status_sensor",
            "request_job=gold_stk_mins_qfq_macd_kdj_repair_job",
            "monitored_jobs=[gold_stk_mins_qfq_macd_kdj_daily_update_job]",
            "_automatic_macd_kdj_repair_allowed",
            '"stock_codes": list(decision.stock_codes)',
            '"upstream_batch_id": decision.upstream_batch_id',
            "build_upstream_triggered_run_key",
            "build_run_request",
            "build_sensor_tags",
        )
        forbidden_repair_sensor_fragments = (
            "get_asset_check_execution_history",
            "duckdb",
            "read_parquet",
            "gold_stk_mins_qfq_macd_kdj_path",
            "source_qfq_factor_repair_event_storage_ids",
            '"stock_codes": []',
        )
        issues.extend(
            f"{repair_sensor_path} misses MACD/KDJ repair sensor fragment: {fragment}"
            for fragment in required_repair_sensor_fragments
            if fragment not in repair_sensor_source
        )
        issues.extend(
            f"{repair_sensor_path} contains forbidden MACD/KDJ repair sensor fragment: {fragment}"
            for fragment in forbidden_repair_sensor_fragments
            if fragment in repair_sensor_source
        )

        repair_op_source = repair_op_path.read_text()
        required_repair_op_fragments = (
            "stock_codes=stock_codes",
            "_assert_repair_target_state_files_exist",
            "freqs != STK_MINS_QFQ_FREQS",
            "MACD_KDJ_REPAIR_FULL_FREQUENCY_ERROR",
            "repair_required_codes_hash=repair_required_codes_hash",
            "upstream_batch_id=upstream_batch_id",
        )
        issues.extend(
            f"{repair_op_path} misses R5 MACD/KDJ repair guard: {fragment}"
            for fragment in required_repair_op_fragments
            if fragment not in repair_op_source
        )

        source_scope_callers = (
            asset_path,
            CHECKS_DIR / "stk_mins_qfq_macd_kdj_checks.py",
            DEFS_DIR / "bootstrap" / "stk_mins_qfq_macd_kdj_history.py",
            repair_op_path,
        )
        repair_scope_call_count = 0
        for path in source_scope_callers:
            source_tree = ast.parse(path.read_text())
            for node in ast.walk(source_tree):
                if not isinstance(node, ast.Call):
                    continue
                if _call_name(node.func) != "discover_gold_stk_mins_qfq_source_year_paths":
                    continue
                uses_repair_scope = any(
                    keyword.arg == "stock_codes" for keyword in node.keywords
                )
                if not uses_repair_scope:
                    continue
                if path != repair_op_path:
                    issues.append(
                        f"{path} must not pass repair-only stock_codes scope to "
                        "MACD/KDJ source discovery"
                    )
                    continue
                repair_scope_call_count += 1
        if repair_scope_call_count != 1:
            issues.append(
                "MACD/KDJ repair op must be the only source discovery caller "
                "that passes stock_codes scope"
            )

        asset_source = asset_path.read_text()
        guard_call = "assert_gold_stk_mins_qfq_macd_kdj_daily_repair_gate"
        guard_call_site = (
            "assert_gold_stk_mins_qfq_macd_kdj_daily_repair_gate(\n"
            "            context.instance"
        )
        guard_run_tags = "run_tags=context.run.tags"
        write_call = "write_result = write_gold_stk_mins_qfq_macd_kdj_asset_partition"
        if guard_call not in asset_source:
            issues.append("MACD/KDJ asset must call qfq repair gate guard")
        elif guard_call_site not in asset_source:
            issues.append("MACD/KDJ asset guard call site must use context.instance")
        elif guard_run_tags in asset_source:
            issues.append("MACD/KDJ asset guard must not depend on run tags")
        elif write_call not in asset_source:
            issues.append("MACD/KDJ asset write helper call is missing")
        elif asset_source.index(guard_call_site) > asset_source.index(write_call):
            issues.append(
                "MACD/KDJ repair gate guard must run before Parquet write helper"
            )
        required_asset_fragments = (
            "DuckDBResource",
            "load_stock_mins_expected_trade_dates",
            "previous_expected_trade_date",
            "is_first_expected_trade_date",
            "STK_MINS_MACD_KDJ_BASELINE_START_DATE",
            "silver_trade_calendar_path",
        )
        issues.extend(
            f"{asset_path} misses MACD/KDJ daily continuity fragment: {fragment}"
            for fragment in required_asset_fragments
            if fragment not in asset_source
        )
        if "partition_key == STK_MINS_MACD_KDJ_BASELINE_START_DATE" in asset_source:
            issues.append(
                "MACD/KDJ daily asset must use expected-calendar first date for "
                "baseline state initialization"
            )

        writer_path = DEFS_DIR / "stk_mins_qfq_macd_kdj.py"
        writer_source = _function_source(
            writer_path,
            "write_gold_stk_mins_qfq_macd_kdj_asset_partition",
        )
        if "assert_exact_previous_state_path" not in writer_source:
            issues.append("MACD/KDJ daily writer must use exact previous state gate")
        if "discover_latest_macd_kdj_state_path_before_trade_date" in writer_source:
            issues.append(
                "MACD/KDJ daily writer must not use latest-before-state discovery"
            )

        repair_op_source = repair_op_path.read_text()
        required_repair_op_fragments = (
            "GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_COMPLETED_CHECK_NAME",
            "MACD_KDJ_REPAIR_EMPTY_STOCK_CODES_ERROR",
            "MACD_KDJ_REPAIR_MANUAL_UNSUPPORTED_ERROR",
            'required_resource_keys={"lake_root", "duckdb"}',
            "DuckDBResource",
            "silver_trade_calendar_path",
            "load_stock_mins_expected_trade_dates",
            "STK_MINS_MACD_KDJ_BASELINE_START_DATE",
            "expected_trade_dates_between",
            "assert_expected_dates_registered",
            "previous_expected_trade_date",
            "is_first_expected_trade_date",
            "assert_exact_previous_state_path",
            "source_paths_by_freq",
            "previous_state_path_by_freq",
            "qfq_factor_repair_trade_date",
            "upstream_batch_id",
            "gold_stk_mins_qfq_factor_repair_status",
            "_repair_scope_from_qfq_factor_repair_status",
            "dg.AssetCheckEvaluation",
            "blocking=True",
            "partition=qfq_factor_repair_trade_date",
            "repair_required_codes_hash",
            "source_upstream_batch_id",
            '"stock_code_scope": "explicit"',
            "DgStdoutLogger",
            "gold_stk_mins_qfq_macd_kdj_repair_started",
            "gold_stk_mins_qfq_macd_kdj_repair_completed",
            "_repair_completion_human_metadata",
            '"summary":',
            '"next_action":',
            '"result_status": "repair_completed"',
            '"diagnostic_ref":',
        )
        issues.extend(
            f"{repair_op_path} misses MACD/KDJ repair completion fragment: {fragment}"
            for fragment in required_repair_op_fragments
            if fragment not in repair_op_source
        )
        stock_codes_schema_start = repair_op_source.find('"stock_codes": dg.Field(')
        reason_schema_start = repair_op_source.find(
            '"reason": dg.Field(',
            stock_codes_schema_start,
        )
        if stock_codes_schema_start == -1 or reason_schema_start == -1:
            issues.append(f"{repair_op_path} misses stock_codes repair config schema")
        else:
            stock_codes_schema = repair_op_source[
                stock_codes_schema_start:reason_schema_start
            ]
            if "is_required=False" not in stock_codes_schema:
                issues.append(
                    "MACD/KDJ repair stock_codes config must be optional for replay mode"
                )
            if "为空表示全市场" in stock_codes_schema:
                issues.append(
                    "MACD/KDJ repair stock_codes config must not allow empty "
                    "all-market repair"
                )
            if "qfq factor repair metadata" not in stock_codes_schema:
                issues.append(
                    "MACD/KDJ repair stock_codes config must mention metadata match"
                )
        stock_codes_guard = "if not stock_codes:"
        repair_write_call = "write_gold_stk_mins_qfq_macd_kdj_rows("
        if stock_codes_guard not in repair_op_source:
            issues.append(
                "MACD/KDJ repair op must reject empty stock_codes before writing"
            )
        elif repair_write_call not in repair_op_source:
            issues.append("MACD/KDJ repair op misses write helper call")
        elif repair_op_source.index(stock_codes_guard) > repair_op_source.index(
            repair_write_call
        ):
            issues.append(
                "MACD/KDJ repair op must reject empty stock_codes before writing"
            )
        manual_guard = "if qfq_factor_repair_trade_date is None or not upstream_batch_id:"
        qfq_status_call = "gold_stk_mins_qfq_factor_repair_status("
        if manual_guard not in repair_op_source:
            issues.append(
                "MACD/KDJ repair op must reject missing upstream batch before writing"
            )
        elif repair_op_source.index(manual_guard) > repair_op_source.index(
            repair_write_call
        ):
            issues.append("MACD/KDJ repair manual guard must run before writing")
        if qfq_status_call not in repair_op_source:
            issues.append(
                "MACD/KDJ repair op must read qfq factor repair metadata in replay mode"
            )
        elif repair_op_source.index(qfq_status_call) > repair_op_source.index(
            repair_write_call
        ):
            issues.append("MACD/KDJ repair replay mode must resolve scope before writing")
        forbidden_repair_op_fragments = (
            '"stock_code_scope": "explicit" if stock_codes else "all"',
            '"stock_code_scope": "all"',
            "MACD_KDJ_REPAIR_MISSING_SCOPE_ERROR",
            "source_qfq_factor_repair_event_storage_ids",
            "def _target_trade_dates",
            "discover_latest_macd_kdj_state_path_before_trade_date",
            "start_trade_date == STK_MINS_MACD_KDJ_BASELINE_START_DATE",
            "partition=start_trade_date",
        )
        issues.extend(
            f"{repair_op_path} contains forbidden MACD/KDJ repair op fragment: {fragment}"
            for fragment in forbidden_repair_op_fragments
            if fragment in repair_op_source
        )

        repair_gate_path = DEFS_DIR / "asset_guards" / "stk_mins_qfq_macd_kdj.py"
        repair_gate_source = repair_gate_path.read_text()
        if "partition_key=qfq_factor_repair_trade_date" not in repair_gate_source:
            issues.append(
                "MACD/KDJ repair completion gate must read the QFQ repair trigger partition"
            )
        if "partition_key=repair_start_trade_date" in repair_gate_source:
            issues.append(
                "MACD/KDJ repair completion gate must not read the repair start partition"
            )

        self.assertEqual(issues, [])

    def test_macd_kdj_repair_legacy_storage_id_field_is_absent_from_production_code(
        self,
    ) -> None:
        issues = []
        field_name = "source_qfq_factor_repair_event_storage_ids"
        forbidden_symbols = (
            field_name,
            "legacy_gold_stk_mins_qfq_macd_kdj_repair_completion_status",
            "_legacy_macd_kdj_repair_completion_status",
            "legacy_source_qfq_factor_repair_event_storage_ids",
            "_MACD_KDJ_REPAIR_LEGACY_COMPLETION_REQUIRED_METADATA_KEYS",
        )
        for path in sorted(DEFS_DIR.rglob("*.py")):
            source = path.read_text()
            for symbol in forbidden_symbols:
                if symbol in source:
                    issues.append(
                        f"{path} contains removed legacy bridge symbol: {symbol}"
                    )

        self.assertEqual(issues, [])

    def test_market_breadth_continuity_replaces_automation_condition(self) -> None:
        issues = []
        old_sensor_files = (
            SENSORS_DIR / "market_breadth_automation_sensor.py",
            SENSORS_DIR / "stock_return_distribution_automation_sensor.py",
            SENSORS_DIR / "clickhouse_share_fact_market_breadth_automation_sensor.py",
            SENSORS_DIR / "prod_clickhouse_share_fact_market_breadth_automation_sensor.py",
        )
        for path in old_sensor_files:
            if path.exists():
                issues.append(f"{path} must not remain as active automation sensor")

        asset_files = (
            ASSETS_DIR / "market_breadth.py",
            ASSETS_DIR / "stock_return_distribution.py",
            ASSETS_DIR / "clickhouse_serving.py",
        )
        forbidden_asset_fragments = (
            "AutomationCondition.eager",
            "automation_condition=",
            "AUTOMATION_CONDITION",
        )
        for path in asset_files:
            source = path.read_text()
            issues.extend(
                f"{path} contains removed P6 automation fragment: {fragment}"
                for fragment in forbidden_asset_fragments
                if fragment in source
            )

        sensor_requirements = {
            "market_breadth_continuity_sensor.py": (
                "load_expected_trade_date_window",
                "build_registered_gap_status",
                "batch_gold_market_breadth_lake_readiness",
                "select_first_not_ready_trade_date",
                "stock_daily_ready_for_trade_date",
                "build_asset_update_run_key",
                "build_run_request",
            ),
            "stock_return_distribution_continuity_sensor.py": (
                "load_expected_trade_date_window",
                "build_registered_gap_status",
                "batch_gold_stock_return_distribution_lake_readiness",
                "select_first_not_ready_trade_date",
                "stock_daily_ready_for_trade_date",
                "build_asset_update_run_key",
                "build_run_request",
            ),
            "clickhouse_market_breadth_continuity_sensor.py": (
                "batch_clickhouse_market_breadth_readiness",
                "batch_prod_clickhouse_market_breadth_readiness",
                "batch_gold_market_breadth_lake_readiness",
                "batch_gold_stock_return_distribution_lake_readiness",
                "select_first_not_ready_trade_date",
                "build_asset_update_run_key",
                "build_run_request",
            ),
        }
        forbidden_sensor_fragments = (
            "AutomationConditionSensorDefinition",
            "AutomationCondition.eager",
            "asset_readiness_status(",
            "partition_dataset_readiness_status_from_latest_checks",
            "run_key=f",
            "dg.RunRequest(",
        )
        for filename, required_fragments in sensor_requirements.items():
            path = SENSORS_DIR / filename
            source = path.read_text()
            issues.extend(
                f"{path} misses P6 bounded sensor fragment: {fragment}"
                for fragment in required_fragments
                if fragment not in source
            )
            issues.extend(
                f"{path} contains forbidden P6 sensor fragment: {fragment}"
                for fragment in forbidden_sensor_fragments
                if fragment in source
            )
            if filename == "clickhouse_market_breadth_continuity_sensor.py":
                forbidden_clickhouse_cursor_fragments = (
                    "to_cursor_details()",
                    '"serving_batch_status":',
                    '"upstream_batch_statuses":',
                    '"status_samples"',
                    "gold_market_breadth_daily_path",
                    "gold_market_breadth_row",
                    "clickhouse_row_counts_by_partition",
                )
                issues.extend(
                    f"{path} contains oversized ClickHouse cursor fragment: {fragment}"
                    for fragment in forbidden_clickhouse_cursor_fragments
                    if fragment in source
                )

        helper_path = DEFS_DIR / "asset_guards" / "market_breadth_lake_readiness.py"
        helper_source = helper_path.read_text()
        required_helper_fragments = (
            "market_breadth_daily_select",
            "stock_return_distribution_select",
            "fetch_clickhouse_market_breadth_rows_for_partitions",
            "ContinuityBatchReadiness",
            "ContinuityDateReadiness",
        )
        issues.extend(
            f"{helper_path} misses P6 readiness fragment: {fragment}"
            for fragment in required_helper_fragments
            if fragment not in helper_source
        )
        forbidden_helper_fragments = (
            "DagsterInstance",
            "get_event_records",
            "asset_readiness_status(",
            "partition_dataset_readiness_status_from_latest_checks",
        )
        issues.extend(
            f"{helper_path} contains forbidden P6 readiness fragment: {fragment}"
            for fragment in forbidden_helper_fragments
            if fragment in helper_source
        )

        self.assertEqual(issues, [])

    def test_market_breadth_gold_human_readable_governance_stays_compact(
        self,
    ) -> None:
        issues = []
        sources = {
            "market_breadth_asset": ASSETS_DIR / "market_breadth.py",
            "return_distribution_asset": ASSETS_DIR / "stock_return_distribution.py",
            "market_breadth_checks": CHECKS_DIR / "market_breadth_checks.py",
            "return_distribution_checks": CHECKS_DIR
            / "stock_return_distribution_checks.py",
            "market_breadth_sensor": SENSORS_DIR
            / "market_breadth_continuity_sensor.py",
            "return_distribution_sensor": SENSORS_DIR
            / "stock_return_distribution_continuity_sensor.py",
        }
        source_text = {name: path.read_text() for name, path in sources.items()}

        requirements = {
            "market_breadth_asset": (
                "gold_market_breadth_started",
                "gold_market_breadth_completed",
                "metric_summary",
                "市场宽度 gold",
            ),
            "return_distribution_asset": (
                "gold_stock_return_distribution_started",
                "gold_stock_return_distribution_completed",
                "metric_summary",
                "收益率分布 gold",
            ),
            "market_breadth_checks": (
                "rule_summary",
                "failed_rule_names",
                "市场宽度 gold",
                "next_action",
            ),
            "return_distribution_checks": (
                "rule_summary",
                "failed_rule_names",
                "收益率分布 gold",
                "next_action",
            ),
            "market_breadth_sensor": (
                "_summary_and_next_action",
                "silver_stock_daily 还没有 ready",
                "触发",
                "市场宽度 gold",
            ),
            "return_distribution_sensor": (
                "_summary_and_next_action",
                "silver_stock_daily 还没有 ready",
                "触发",
                "收益率分布 gold",
            ),
        }
        for name, required_fragments in requirements.items():
            source = source_text[name]
            for fragment in required_fragments:
                if fragment not in source:
                    issues.append(f"{name} misses readable fragment: {fragment}")

        forbidden_cursor_fragments = (
            "status_samples",
            "to_cursor_details(",
            "gold_market_breadth_daily_path",
            "gold_stock_return_distribution_path",
            "clickhouse_row_counts_by_partition",
        )
        for name in ("market_breadth_sensor", "return_distribution_sensor"):
            source = source_text[name]
            for fragment in forbidden_cursor_fragments:
                if fragment in source:
                    issues.append(f"{name} contains bulky cursor fragment: {fragment}")

        forbidden_stdout_fields = (
            "sql=",
            "query=",
            "dataframe=",
            "sample_rows=",
        )
        for name in ("market_breadth_asset", "return_distribution_asset"):
            source = source_text[name]
            for fragment in forbidden_stdout_fields:
                if fragment in source:
                    issues.append(f"{name} stdout contains bulky field: {fragment}")

        self.assertEqual(issues, [])

    def test_clickhouse_market_breadth_human_readable_governance_stays_compact(
        self,
    ) -> None:
        asset_source = (ASSETS_DIR / "clickhouse_serving.py").read_text()
        local_check_source = (CHECKS_DIR / "clickhouse_serving_checks.py").read_text()
        prod_check_source = (
            CHECKS_DIR / "prod_clickhouse_serving_checks.py"
        ).read_text()
        sensor_source = (
            SENSORS_DIR / "clickhouse_market_breadth_continuity_sensor.py"
        ).read_text()
        issues = []

        for fragment in (
            "ch_share_fact_market_breadth_started",
            "ch_share_fact_market_breadth_completed",
            "prod_ch_share_fact_market_breadth_started",
            "prod_ch_share_fact_market_breadth_completed",
            "serving_summary",
            "本机 ClickHouse 市场宽度 serving",
            "Prod ClickHouse 市场宽度 serving",
        ):
            if fragment not in asset_source:
                issues.append(f"ClickHouse serving asset misses fragment: {fragment}")

        for source_name, source in (
            ("local", local_check_source),
            ("prod", prod_check_source),
        ):
            for fragment in ("summary", "next_action", "rule_summary"):
                if fragment not in source:
                    issues.append(
                        f"{source_name} ClickHouse checks miss metadata: {fragment}"
                    )

        for fragment in (
            "_summary_and_next_action",
            "上游 gold 还没有 ready",
            "prod 同步等待本机 ClickHouse serving ready",
            "ClickHouse serving blocking checks",
        ):
            if fragment not in sensor_source:
                issues.append(f"ClickHouse sensor cursor misses fragment: {fragment}")

        for fragment in (
            '"serving_batch_status":',
            '"upstream_batch_statuses":',
            "status_samples",
            "gold_market_breadth_daily_path",
            "gold_market_breadth_row",
            "clickhouse_row_counts_by_partition",
        ):
            if fragment in sensor_source:
                issues.append(f"ClickHouse sensor cursor contains bulky field: {fragment}")

        self.assertEqual(issues, [])

    def test_gold_qfq_repair_event_reconciliation_chain_is_removed(self) -> None:
        issues = []
        factor_repair_op_path = DEFS_DIR / "ops" / "stock_mins_qfq_factor_repair.py"
        removed_reconciliation_paths = (
            DEFS_DIR / "ops" / "gold_stk_mins_qfq_repair_event_reconciliation.py",
            JOBS_DIR / "gold_stk_mins_qfq_repair_event_reconciliation.py",
            SENSORS_DIR / "gold_stk_mins_qfq_repair_event_reconciliation_job_sensor.py",
            DEFS_DIR / "bootstrap" / "stk_mins_qfq_repair_reconciliation_events.py",
        )
        qfq_repair_guard_path = (
            DEFS_DIR / "asset_guards" / "stk_mins_qfq_factor_repair.py"
        )
        macd_kdj_guard_path = (
            DEFS_DIR / "asset_guards" / "stk_mins_qfq_macd_kdj.py"
        )

        factor_repair_op_source = factor_repair_op_path.read_text()
        forbidden_factor_repair_fragments = (
            "report_stk_mins_qfq_partition_events",
            "report_stk_mins_qfq_derived_partition_events",
            "stk_mins_qfq_factor_repair_reconciliation",
        )
        issues.extend(
            f"{factor_repair_op_path} directly reports ordinary qfq events: {fragment}"
            for fragment in forbidden_factor_repair_fragments
            if fragment in factor_repair_op_source
        )

        issues.extend(
            f"old qfq repair event reconciliation file must be removed: {path}"
            for path in removed_reconciliation_paths
            if path.exists()
        )

        forbidden_source_fragments = (
            "gold_stk_mins_qfq_repair_event_reconciliation",
            "stk_mins_qfq_repair_reconciliation_events",
            "report_stk_mins_qfq_repair_reconciliation_events",
            "build_stk_mins_qfq_repair_reconciliation_plan",
            "STK_MINS_QFQ_REPAIR_RECONCILIATION_SOURCE_METHOD",
            "stk_mins_qfq_factor_repair_reconciliation",
            "qfq_factor_repair_event_reconciliation",
        )
        for path in DEFS_DIR.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            source = path.read_text()
            issues.extend(
                f"{path} contains removed qfq repair reconciliation fragment: {fragment}"
                for fragment in forbidden_source_fragments
                if fragment in source
            )

        qfq_repair_guard_source = qfq_repair_guard_path.read_text()
        if "class GoldStkMinsQfqFactorRepairStatus" not in qfq_repair_guard_source:
            issues.append("neutral qfq factor repair guard status class is missing")
        if "gold_stk_mins_qfq_factor_repair_status" not in qfq_repair_guard_source:
            issues.append("neutral qfq factor repair status helper is missing")

        macd_kdj_guard_source = macd_kdj_guard_path.read_text()
        if "gold_stk_mins_qfq_macd_kdj_qfq_factor_repair_status" in macd_kdj_guard_source:
            issues.append("qfq factor repair status must not be exposed from macd/kdj guard")

        self.assertEqual(issues, [])

    def test_stock_mins_qfq_daily_job_does_not_pull_raw_silver_or_source_config(
        self,
    ) -> None:
        path = JOBS_DIR / "stock_mins_qfq_daily_update.py"
        source = path.read_text()
        forbidden_fragments = (
            "RAW_STK_MINS_ASSETS",
            "SILVER_STK_MINS_ASSETS",
            "Tushare",
            "ProdPostgres",
            "build_stock_mins_raw_update_job_run_config",
            "STOCK_MINS_RAW_CONFIG_SCHEMA",
            "raw_stk_mins_",
            "silver_stk_mins_",
            "silver_adj_factor",
            "repair",
            "summary",
            '"ops"',
            "'ops'",
            "run_tags",
        )
        issues = [
            f"{path} contains forbidden stock_mins qfq job fragment: {fragment}"
            for fragment in forbidden_fragments
            if fragment in source
        ]

        self.assertEqual(issues, [])

    def test_stock_mins_qfq_factor_repair_job_only_calls_repair_op(self) -> None:
        path = JOBS_DIR / "stock_mins_qfq_factor_repair.py"
        source = path.read_text()
        required_fragments = (
            "stock_mins_qfq_factor_repair_op",
            "@dg.job",
        )
        forbidden_fragments = (
            "cn_a_stock_mins_silver_trade_days",
            "partitions_def",
            "DuckDB",
            "duckdb",
            "parquet",
            "gold_stk_mins_qfq_path",
            "silver_adj_factor",
            "silver_stk_mins_",
            "raw_stk_mins_",
            "build_daily_qfq_select_sql",
            "rewrite_qfq_year_file_for_stock_code",
            "summary",
            '"ops"',
            "'ops'",
            "run_tags",
        )
        issues = [
            f"{path} misses required qfq repair job fragment: {fragment}"
            for fragment in required_fragments
            if fragment not in source
        ]
        issues.extend(
            f"{path} contains forbidden qfq repair job fragment: {fragment}"
            for fragment in forbidden_fragments
            if fragment in source
        )

        self.assertEqual(issues, [])

    def test_stock_daily_freshness_guard_stays_on_silver_asset(self) -> None:
        asset_path = ASSETS_DIR / "stock_daily.py"
        job_path = JOBS_DIR / "stock_daily_update.py"
        raw_source = _function_source(asset_path, "raw_tushare_stock_daily")
        silver_source = _function_source(asset_path, "silver_stock_daily")
        job_source = job_path.read_text()
        guard_call = "assert_silver_stock_basic_fresh_for_stock_daily"
        issues = []

        for fragment in (
            guard_call,
            "silver_stock_basic_ready_for_trade_date",
            "stock_basic_ready_for_trade_date",
        ):
            if fragment in raw_source:
                issues.append(f"raw_tushare_stock_daily references {fragment}")

        if guard_call not in silver_source:
            issues.append("silver_stock_daily must call stock basic freshness guard")
        elif silver_source.index(guard_call) > silver_source.index(
            "with connect_configured_duckdb()"
        ):
            issues.append(
                "silver_stock_daily freshness guard must run before DuckDB writes"
            )

        forbidden_job_fragments = (
            "raw_tushare_stock_basic",
            "silver_stock_basic",
            "stock_basic_update_job",
            "stock_basic_ready_for_trade_date",
        )
        issues.extend(
            f"{job_path} contains forbidden stock basic selection fragment: {fragment}"
            for fragment in forbidden_job_fragments
            if fragment in job_source
        )

        self.assertEqual(issues, [])

    def test_stock_lifecycle_is_owned_by_stock_basic_silver_job(self) -> None:
        asset_path = ASSETS_DIR / "stock_lifecycle.py"
        check_path = CHECKS_DIR / "stock_lifecycle_checks.py"
        job_path = JOBS_DIR / "stock_basic_update.py"
        sensor_path = SENSORS_DIR / "stock_basic_sensor.py"
        asset_source = asset_path.read_text()
        check_source = check_path.read_text()
        job_source = job_path.read_text()
        sensor_source = sensor_path.read_text()
        issues = []

        for fragment in (
            "silver_stock_lifecycle",
            "silver_stock_lifecycle_ready_for_trade_date",
        ):
            if fragment not in sensor_source and fragment.endswith("_ready_for_trade_date"):
                issues.append(f"{sensor_path} does not read lifecycle readiness")
            if fragment == "silver_stock_lifecycle" and fragment not in job_source:
                issues.append(f"{job_path} does not select silver_stock_lifecycle")

        if "silver_stock_basic_path" in asset_source:
            issues.append("stock_lifecycle asset must not depend on silver_stock_basic")
        if "silver_stock_basic_path" in check_source:
            issues.append("stock_lifecycle checks must not depend on silver_stock_basic")
        if "raw_stock_basic_path" not in asset_source:
            issues.append("stock_lifecycle asset must derive from raw_stock_basic")

        self.assertEqual(issues, [])

    def test_stock_lifecycle_consumers_use_silver_lifecycle_asset(self) -> None:
        target_paths = (
            ASSETS_DIR / "stock_daily.py",
            CHECKS_DIR / "stock_daily_checks.py",
            CHECKS_DIR / "stk_mins_checks.py",
            DEFS_DIR / "asset_guards" / "stk_mins_lake_readiness.py",
            DEFS_DIR / "bootstrap" / "stk_mins_name_timeline_check_events.py",
        )
        required_fragments = (
            "silver_stock_lifecycle_path",
            "silver_cny_stock_lifecycle_select",
        )
        forbidden_fragments = (
            "raw_tushare_stock_basic",
            "raw_stock_basic_path",
            "raw_stock_basic_file_path",
            "historical_cny_stock_lifecycle_select",
        )
        issues = []

        for path in target_paths:
            source = path.read_text()
            issues.extend(
                f"{path} misses required lifecycle consumer fragment: {fragment}"
                for fragment in required_fragments
                if fragment not in source
            )
            issues.extend(
                f"{path} contains forbidden raw lifecycle consumer fragment: {fragment}"
                for fragment in forbidden_fragments
                if fragment in source
            )

        self.assertEqual(issues, [])

    def test_stock_mins_silver_direct_dependencies_exclude_namechange_and_basic(
        self,
    ) -> None:
        asset_path = ASSETS_DIR / "stk_mins.py"
        source = asset_path.read_text()
        writer_source = _function_source(asset_path, "write_silver_stk_mins_partition")
        issues = []

        for fragment in ("silver_namechange_path", "silver_stock_basic_path"):
            if fragment in writer_source:
                issues.append(
                    "write_silver_stk_mins_partition contains forbidden input "
                    f"requirement: {fragment}"
                )

        for freq in ("1", "5", "15", "30", "60"):
            marker = f'name="silver_stk_mins_{freq}m"'
            def_marker = f"def silver_stk_mins_{freq}m"
            decorator_source = source[
                source.index(marker) : source.index(def_marker, source.index(marker))
            ]
            for fragment in ("silver_namechange", "silver_stock_basic"):
                if fragment in decorator_source:
                    issues.append(
                        f"silver_stk_mins_{freq}m deps contain forbidden direct "
                        f"dependency: {fragment}"
                    )
            for fragment in (
                "silver_stock_identity_map",
                "silver_stock_daily",
                "silver_stock_suspend_daily",
            ):
                if fragment not in decorator_source:
                    issues.append(
                        f"silver_stk_mins_{freq}m deps miss required dependency: "
                        f"{fragment}"
                    )

        self.assertEqual(issues, [])

    def test_stock_mins_raw_sensor_uses_batch_lake_readiness(self) -> None:
        path = SENSORS_DIR / "stock_mins_raw_sensor.py"
        source = path.read_text()
        issues = []

        required_fragments = (
            "batch_raw_stk_mins_lake_readiness",
            "StkMinsBatchReadiness",
            "build_run_request",
            "build_asset_update_run_key",
            "build_stock_mins_raw_update_job_run_config",
            "source=STOCK_MINS_RAW_SOURCE",
        )
        forbidden_fragments = (
            "raw_stk_mins_ready_for_trade_date",
            "dg.RunRequest(",
            "RunRequest(",
            "run_key=f",
            "run_key=(",
            ".split(",
            "partition_key=trade_date,\n    )",
        )
        issues.extend(
            f"{path} misses required raw sensor batch readiness fragment: {fragment}"
            for fragment in required_fragments
            if fragment not in source
        )
        issues.extend(
            f"{path} contains forbidden raw sensor hot-path fragment: {fragment}"
            for fragment in forbidden_fragments
            if fragment in source
        )

        self.assertEqual(issues, [])

    def test_stock_mins_raw_default_source_is_prod_db(self) -> None:
        path = DEFS_DIR / "run_contracts" / "configs.py"
        source = path.read_text()
        issues = []

        required_fragments = (
            'default_value="prod_db"',
            'config.get("source", "prod_db")',
        )
        forbidden_fragments = (
            'default_value="tushare"',
            'config.get("source", "tushare")',
        )
        issues.extend(
            f"{path} misses required stock mins raw default source fragment: {fragment}"
            for fragment in required_fragments
            if fragment not in source
        )
        issues.extend(
            f"{path} contains unsafe stock mins raw default source fragment: {fragment}"
            for fragment in forbidden_fragments
            if fragment in source
        )

        self.assertEqual(issues, [])

    def test_stock_mins_silver_sensors_do_not_gate_on_namechange(self) -> None:
        issues = []
        for path in (
            SENSORS_DIR / "stock_mins_silver_trade_day_sensor.py",
            SENSORS_DIR / "stock_mins_silver_sensor.py",
        ):
            source = path.read_text()
            for fragment in (
                "silver_namechange_ready_for_trade_date",
                "namechange_ready",
                "namechange_status",
            ):
                if fragment in source:
                    issues.append(
                        f"{path} contains forbidden silver namechange gate fragment: "
                        f"{fragment}"
                    )

        self.assertEqual(issues, [])

    def test_stock_mins_silver_sensors_use_batch_lake_readiness(self) -> None:
        issues = []
        expected_by_file = {
            SENSORS_DIR / "stock_mins_silver_trade_day_sensor.py": (
                "batch_raw_stk_mins_lake_readiness",
                "StkMinsBatchReadiness",
            ),
            SENSORS_DIR / "stock_mins_silver_sensor.py": (
                "batch_raw_stk_mins_lake_readiness",
                "batch_silver_stk_mins_lake_readiness",
                "StkMinsBatchReadiness",
                "build_run_request",
                "build_asset_update_run_key",
            ),
        }
        forbidden_by_file = {
            SENSORS_DIR / "stock_mins_silver_trade_day_sensor.py": (
                "raw_stk_mins_ready_for_trade_date",
                "dg.RunRequest(",
                "RunRequest(",
                "run_key=f",
                "run_key=(",
                ".split(",
            ),
            SENSORS_DIR / "stock_mins_silver_sensor.py": (
                "raw_stk_mins_ready_for_trade_date",
                "silver_stk_mins_ready_for_trade_date",
                "dg.RunRequest(",
                "RunRequest(",
                "run_key=f",
                "run_key=(",
                ".split(",
            ),
        }

        for path, fragments in expected_by_file.items():
            source = path.read_text()
            issues.extend(
                f"{path} misses required silver sensor batch fragment: {fragment}"
                for fragment in fragments
                if fragment not in source
            )
            issues.extend(
                f"{path} contains forbidden silver sensor hot-path fragment: {fragment}"
                for fragment in forbidden_by_file[path]
                if fragment in source
            )

        self.assertEqual(issues, [])

    def test_stock_mins_silver_name_timeline_check_uses_silver_lifecycle(
        self,
    ) -> None:
        check_source = _function_source(
            CHECKS_DIR / "stk_mins_checks.py",
            "_silver_name_timeline_covered",
        )
        issues = []

        required_fragments = (
            "silver_stock_lifecycle_path",
            "silver_cny_stock_lifecycle_select",
            "lifecycle_fact_source",
            "silver_stock_lifecycle_file_path",
            "checked_code_date_count",
            "failed_code_date_count",
        )
        forbidden_fragments = (
            "raw_stock_basic_path",
            "historical_cny_stock_lifecycle_select",
            "silver_stock_basic_path",
            "silver_namechange_path",
        )
        issues.extend(
            f"_silver_name_timeline_covered misses required fragment: {fragment}"
            for fragment in required_fragments
            if fragment not in check_source
        )
        issues.extend(
            f"_silver_name_timeline_covered contains forbidden fragment: {fragment}"
            for fragment in forbidden_fragments
            if fragment in check_source
        )

        self.assertEqual(issues, [])

    def test_lake_root_health_entrypoints_stay_infra_only(self) -> None:
        asset_path = ASSETS_DIR / "lake_root_health.py"
        check_path = CHECKS_DIR / "lake_root_health_checks.py"
        health_path = DEFS_DIR / "health" / "lake_root.py"
        job_path = JOBS_DIR / "lake_root_health_check.py"
        schedule_path = SCHEDULES_DIR / "lake_root_health.py"
        resource_path = DEFS_DIR / "resources.py"
        asset_source = asset_path.read_text()
        check_source = check_path.read_text()
        health_source = health_path.read_text()
        job_source = job_path.read_text()
        schedule_source = schedule_path.read_text()
        resource_source = resource_path.read_text()
        issues = []

        required_human_fragments = (
            "summary",
            "next_action",
            "result_status",
            "component_status",
            "diagnostic_ref",
            "rule_summary",
        )
        human_source = "\n".join((asset_source, check_source, health_source))
        issues.extend(
            f"lake root health readability misses fragment: {fragment}"
            for fragment in required_human_fragments
            if fragment not in human_source
        )

        forbidden_business_fragments = (
            "source_asset",
            "downstream",
            "tushare",
            "index_daily",
            "stock_daily",
            "stk_mins",
        )
        issues.extend(
            f"lake root health readability contains business fragment: {fragment}"
            for fragment in forbidden_business_fragments
            if fragment in human_source
        )

        required_job_fragments = (
            "lake_root_health",
            "dg.AssetSelection.assets(lake_root_health)",
            "dg.AssetSelection.checks_for_assets(lake_root_health)",
        )
        issues.extend(
            f"{job_path} misses lake root health job fragment: {fragment}"
            for fragment in required_job_fragments
            if fragment not in job_source
        )

        forbidden_job_fragments = (
            "duckdb",
            "parquet",
            "disk_usage",
            "evaluate_lake_root_health",
            '"ops"',
            "'ops'",
            "run_tags",
        )
        issues.extend(
            f"{job_path} contains forbidden health job fragment: {fragment}"
            for fragment in forbidden_job_fragments
            if fragment in job_source
        )

        required_schedule_fragments = (
            "dg.ScheduleDefinition",
            'cron_schedule="0 */2 * * *"',
            'execution_timezone="Asia/Shanghai"',
            "default_status=dg.DefaultScheduleStatus.STOPPED",
            "lake_root_health_check_job",
        )
        issues.extend(
            f"{schedule_path} misses lake root health schedule fragment: {fragment}"
            for fragment in required_schedule_fragments
            if fragment not in schedule_source
        )

        if "assert_lake_root_available_for_run(self.root())" not in resource_source:
            issues.append(
                "LakeRootResource.ensure_available_for_run must call health guard"
            )

        for path in _sensor_definition_files():
            source = path.read_text()
            if "lake_root_health" in source:
                issues.append(f"{path} depends on lake_root_health")

        self.assertEqual(issues, [])

    def test_gold_qfq_summary_entities_are_not_registered(self) -> None:
        issues = []

        for path in sorted(DEFS_DIR.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            source = path.read_text()
            for identifier in FORBIDDEN_QFQ_SUMMARY_IDENTIFIERS:
                if identifier in source:
                    issues.append(
                        f"{path} registers forbidden gold qfq summary identifier: "
                        f"{identifier}"
                    )

        self.assertEqual(issues, [])

    def test_gold_qfq_formal_writes_stay_on_duckdb_helpers(self) -> None:
        issues = []

        for path in QFQ_SOURCE_FILES:
            tree = _parse_python_file(path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                call_name = _call_name(node.func)
                if call_name in {"to_parquet", "write_parquet"}:
                    issues.append(
                        f"{_node_location(path, node)} writes qfq parquet outside "
                        "DuckDB helper path"
                    )
                if call_name == "DataFrame":
                    issues.append(
                        f"{_node_location(path, node)} builds qfq rows through "
                        "Python DataFrame"
                    )

        self.assertEqual(issues, [])

    def test_gold_qfq_writer_pool_is_centralized_and_required(self) -> None:
        issues = []
        constant_source = (DEFS_DIR / "stk_mins_qfq.py").read_text()
        if GOLD_STK_MINS_QFQ_WRITER_POOL_LITERAL not in constant_source:
            issues.append("qfq writer pool literal is not defined in stk_mins_qfq.py")

        for path in sorted(DEFS_DIR.rglob("*.py")):
            if "__pycache__" in path.parts or path == DEFS_DIR / "stk_mins_qfq.py":
                continue
            source = path.read_text()
            if GOLD_STK_MINS_QFQ_WRITER_POOL_LITERAL in source:
                issues.append(f"{path} hard-codes qfq writer pool literal")

        assets_source = (ASSETS_DIR / "stk_mins.py").read_text()
        if assets_source.count("pool=GOLD_STK_MINS_QFQ_WRITER_POOL") != 7:
            issues.append("gold qfq assets must all use GOLD_STK_MINS_QFQ_WRITER_POOL")

        repair_op_source = (
            DEFS_DIR / "ops" / "stock_mins_qfq_factor_repair.py"
        ).read_text()
        if "pool=GOLD_STK_MINS_QFQ_WRITER_POOL" not in repair_op_source:
            issues.append(
                "stock_mins_qfq_factor_repair_op must use "
                "GOLD_STK_MINS_QFQ_WRITER_POOL"
            )

        self.assertEqual(issues, [])

    def test_gold_qfq_uses_explicit_as_of_adj_factor(self) -> None:
        forbidden_tokens = (
            "build_latest_adj_factor_by_code_sql",
            "latest_adj_factor_paths",
            "latest_adj_factor_path",
            "latest_adj_paths",
            "_write_latest_adj_factor_snapshot",
            "_discover_silver_adj_factor_paths",
            "missing_latest_adj_factor_row_count",
        )
        issues = []
        for path in QFQ_AS_OF_SOURCE_FILES:
            source = path.read_text()
            for token in forbidden_tokens:
                if token in source:
                    issues.append(f"{path} retains old qfq latest-factor token: {token}")

        self.assertEqual(issues, [])

    def test_qfq_factor_repair_uses_expected_calendar_for_range(self) -> None:
        issues = []
        helper_path = DEFS_DIR / "stk_mins_qfq_factor_repair.py"
        op_path = DEFS_DIR / "ops" / "stock_mins_qfq_factor_repair.py"
        helper_source = helper_path.read_text()
        op_source = op_path.read_text()

        required_helper_fragments = (
            "expected_trade_dates",
            "previous_expected_trade_date",
            "assert_expected_dates_registered",
            "cn_a_stock_mins_silver_trade_days.name",
        )
        forbidden_helper_fragments = (
            "def _previous_trade_date",
            "def _select_repair_partition_keys",
        )
        required_op_fragments = (
            "load_stock_mins_expected_trade_dates",
            "silver_trade_calendar_path",
            "STK_MINS_QFQ_HISTORY_START_DATE",
            "expected_trade_dates=expected_trade_dates",
        )
        for fragment in required_helper_fragments:
            if fragment not in helper_source:
                issues.append(
                    f"{helper_path} misses expected-calendar repair fragment: {fragment}"
                )
        for fragment in forbidden_helper_fragments:
            if fragment in helper_source:
                issues.append(
                    f"{helper_path} retains registered-only repair fragment: {fragment}"
                )
        for fragment in required_op_fragments:
            if fragment not in op_source:
                issues.append(
                    f"{op_path} misses expected-calendar op fragment: {fragment}"
                )

        self.assertEqual(issues, [])

    def test_formal_defs_use_centralized_duckdb_connection(self) -> None:
        issues = []
        for path in sorted(DEFS_DIR.rglob("*.py")):
            if "__pycache__" in path.parts or path == DUCKDB_CONNECTION_HELPER:
                continue
            source = path.read_text()
            if "duckdb.connect(" in source:
                issues.append(f"{path} uses duckdb.connect outside the central helper")

        helper_source = DUCKDB_CONNECTION_HELPER.read_text()
        if helper_source.count("duckdb.connect(") != 1:
            issues.append("duckdb_connection.py must be the only DuckDB connect owner")

        self.assertEqual(issues, [])

    def test_lake_asset_catalog_registry_stays_read_only_and_boundary_safe(
        self,
    ) -> None:
        path = CATALOG_DIR / "lake_assets.py"
        source = path.read_text()
        tree = _parse_python_file(path)
        issues = []

        forbidden_import_prefixes = (
            "src",
            "lake_console.backend",
            "orchestrator.defs.assets",
            "orchestrator.defs.bootstrap",
            "orchestrator.defs.duckdb_connection",
            "orchestrator.defs.duckdb_sql",
            "orchestrator.defs.jobs",
            "orchestrator.defs.ops",
            "orchestrator.defs.resources",
            "orchestrator.defs.sensors",
            "dagster",
            "duckdb",
            "psycopg",
            "requests",
            "clickhouse",
        )
        forbidden_fragments = (
            "DagsterInstance",
            "DAGSTER_HOME",
            "duckdb.connect",
            "event_log_storage",
            "get_asset_check_execution_history",
            "get_latest_asset_check_execution_by_key",
            "glob(",
            "listdir(",
            "rglob(",
            "scandir(",
        )
        forbidden_stage_names = (
            "old_lake_catalog",
            "new_lake_catalog",
            "phase",
            "poc",
            "temporary_catalog",
        )

        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                modules.append(node.module)

            for module in modules:
                if any(
                    module == prefix or module.startswith(f"{prefix}.")
                    for prefix in forbidden_import_prefixes
                ):
                    issues.append(
                        f"{_node_location(path, node)} imports forbidden catalog "
                        f"dependency: {module}"
                    )

        issues.extend(
            f"{path} contains forbidden read/write or instance fragment: {fragment}"
            for fragment in forbidden_fragments
            if fragment in source
        )
        issues.extend(
            f"{path} contains forbidden staged catalog name: {fragment}"
            for fragment in forbidden_stage_names
            if fragment in source
        )

        self.assertEqual(issues, [])

    def test_gold_qfq_factor_repair_does_not_loop_by_changed_code(self) -> None:
        path = DEFS_DIR / "stk_mins_qfq_factor_repair.py"
        source = path.read_text()
        forbidden_fragments = (
            "for stock_code in plan.repair_required_codes",
            "_repair_qfq_for_stock_code",
        )
        issues = [
            f"{path} contains forbidden stock-code primary repair loop: {fragment}"
            for fragment in forbidden_fragments
            if fragment in source
        ]

        self.assertEqual(issues, [])

    def test_sensor_files_use_run_contract_helpers(self) -> None:
        issues = []

        for path in _sensor_definition_files():
            tree = _parse_python_file(path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    if any(alias.name == "json" for alias in node.names):
                        issues.append(f"{_node_location(path, node)} imports json")
                elif isinstance(node, ast.ImportFrom):
                    if node.module == "json":
                        issues.append(f"{_node_location(path, node)} imports from json")
                elif isinstance(node, ast.Call):
                    call_name = _call_name(node.func)
                    if call_name == "RunRequest" and not _is_allowed_direct_run_request(path):
                        issues.append(
                            f"{_node_location(path, node)} constructs RunRequest directly"
                        )
                    for keyword in node.keywords:
                        if keyword.arg == "run_key" and not _is_allowed_sensor_run_key_value(
                            path,
                            keyword.value,
                        ):
                            issues.append(
                                f"{_node_location(path, node)} writes run_key "
                                "without run key builder"
                            )
                        elif keyword.arg == "run_tags":
                            issues.append(
                                f"{_node_location(path, node)} writes run_tags"
                            )
                        elif keyword.arg == "tags" and not (
                            (
                                _is_sensor_definition_call(node)
                                and _is_call_named(keyword.value, "build_sensor_tags")
                            )
                            or (
                                call_name == "RunRequest"
                                and _is_allowed_direct_run_request_tags(path)
                            )
                            or (
                                call_name == "RunsFilter"
                                and path.name
                                in {
                                    "gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor.py",
                                    "gold_wealth_market_turnover_sensor.py",
                                }
                            )
                        ):
                            issues.append(
                                f"{_node_location(path, node)} writes tags without "
                                "build_sensor_tags(...)"
                            )
                elif isinstance(node, ast.Attribute):
                    if (
                        isinstance(node.value, ast.Name)
                        and node.value.id == "json"
                        and node.attr in {"dumps", "loads"}
                    ):
                        issues.append(
                            f"{_node_location(path, node)} serializes cursor locally"
                        )
                elif isinstance(node, ast.Dict):
                    if "ops" in _direct_string_keys(
                        node
                    ) and not _is_allowed_sensor_run_config_dict(path, node):
                        issues.append(
                            f"{_node_location(path, node)} writes deep run_config"
                        )
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if node.value in SENSOR_FORBIDDEN_STRING_LITERALS:
                        issues.append(
                            f"{_node_location(path, node)} uses legacy run contract "
                            f"literal {node.value!r}"
                        )

        self.assertEqual(issues, [])

    def test_sensor_definitions_use_registered_definition_tags(self) -> None:
        issues = []
        sensor_definition_count = 0

        for path in _sensor_definition_files():
            tree = _parse_python_file(path)
            for node in ast.walk(tree):
                if not _is_sensor_definition_call(node):
                    continue
                sensor_definition_count += 1
                tags_value = _keyword_value(node, "tags")
                if not _is_call_named(tags_value, "build_sensor_tags"):
                    issues.append(
                        f"{_node_location(path, node)} sensor definition does not "
                        "use build_sensor_tags(...)"
                    )
                    continue

                sensor_domain = _keyword_value(tags_value, "sensor_domain")
                target_layer = _keyword_value(tags_value, "target_layer")
                role = _keyword_value(tags_value, "role")

                domain_member = _enum_attribute(sensor_domain, "SensorDomain")
                target_layer_member = _enum_attribute(
                    target_layer,
                    "SensorTargetLayer",
                )
                role_member = _enum_attribute(role, "SensorRole")

                if domain_member not in SensorDomain.__members__:
                    issues.append(
                        f"{_node_location(path, sensor_domain or node)} uses "
                        "unregistered SensorDomain"
                    )
                if target_layer_member not in SensorTargetLayer.__members__:
                    issues.append(
                        f"{_node_location(path, target_layer or node)} uses "
                        "unregistered SensorTargetLayer"
                    )
                if role_member not in SensorRole.__members__:
                    issues.append(
                        f"{_node_location(path, role or node)} uses "
                        "unregistered SensorRole"
                    )

        self.assertEqual(sensor_definition_count, 44)
        self.assertEqual(issues, [])

    def test_gold_qfq_sensors_keep_quote_gold_asset_update_tags(self) -> None:
        issues = []
        expected_fragments_by_file = {
            SENSORS_DIR / "stock_mins_qfq_daily_sensor.py": (
                "sensor_domain=SensorDomain.QUOTE_DATA",
                "target_layer=SensorTargetLayer.GOLD",
                "role=SensorRole.ASSET_UPDATE",
            ),
            SENSORS_DIR / "stock_mins_qfq_factor_repair_sensor.py": (
                "sensor_domain=SensorDomain.QUOTE_DATA",
                "target_layer=SensorTargetLayer.GOLD",
                "role=SensorRole.ASSET_UPDATE",
            ),
        }

        for path, fragments in expected_fragments_by_file.items():
            source = path.read_text()
            issues.extend(
                f"{path} misses gold qfq sensor classification fragment: {fragment}"
                for fragment in fragments
                if fragment not in source
            )

        self.assertEqual(issues, [])

    def test_gold_qfq_sensors_use_batch_readiness_without_history_scans(self) -> None:
        issues = []
        required_by_file = {
            SENSORS_DIR / "stock_mins_qfq_daily_sensor.py": (
                "batch_silver_stk_mins_lake_readiness",
                "batch_adj_factor_lake_readiness",
                "batch_gold_stk_mins_qfq_lake_readiness",
            ),
            SENSORS_DIR / "stock_mins_qfq_factor_repair_sensor.py": (
                "batch_gold_stk_mins_qfq_lake_readiness",
                "include_event_storage_ids=False",
            ),
        }
        forbidden_by_file = {
            SENSORS_DIR / "stock_mins_qfq_daily_sensor.py": (
                "silver_stk_mins_ready_for_trade_date",
                "adj_factor_ready_for_trade_date",
                "gold_stk_mins_qfq_ready_for_trade_date",
                "get_asset_check_execution_history",
                "partition_dataset_readiness_status_from_latest_checks",
                "SILVER_STK_MINS_READINESS_SPECS",
                "ADJ_FACTOR_READINESS_SPECS",
                "GOLD_STK_MINS_QFQ_READINESS_SPECS",
                "effective_gold_qfq_readiness_for_trade_date",
                "stk_mins_qfq_effective_readiness",
                "gold_qfq_formula_mismatch_codes",
            ),
            SENSORS_DIR / "stock_mins_qfq_factor_repair_sensor.py": (
                "gold_stk_mins_qfq_ready_for_trade_date",
                "get_asset_check_execution_history",
                "partition_dataset_readiness_status_from_latest_checks",
                "GOLD_STK_MINS_QFQ_READINESS_SPECS",
                "get_event_records",
                "effective_gold_qfq_readiness_for_trade_date",
                "stk_mins_qfq_effective_readiness",
                "gold_qfq_formula_mismatch_codes",
            ),
        }
        for path, required_fragments in required_by_file.items():
            source = path.read_text()
            issues.extend(
                f"{path} misses qfq batch readiness fragment: {fragment}"
                for fragment in required_fragments
                if fragment not in source
            )
        for path, forbidden_fragments in forbidden_by_file.items():
            source = path.read_text()
            issues.extend(
                f"{path} contains forbidden qfq sensor readiness fragment: {fragment}"
                for fragment in forbidden_fragments
                if fragment in source
            )

        window_order_fragments = {
            SENSORS_DIR / "stock_mins_qfq_daily_sensor.py": (
                "stock_mins_qfq_daily_sensor",
                "if not run_window_started:",
                "_load_stock_mins_qfq_expected_trade_dates(",
                "batch_silver_stk_mins_lake_readiness(",
                "batch_adj_factor_lake_readiness(",
                "batch_gold_stk_mins_qfq_lake_readiness(",
            ),
            SENSORS_DIR / "stock_mins_qfq_factor_repair_sensor.py": (
                "stock_mins_qfq_factor_repair_sensor",
                "if not run_window_started:",
                "_load_stock_mins_qfq_expected_trade_dates(",
                "batch_gold_stk_mins_qfq_lake_readiness(",
                "_qfq_factor_repair_readiness_snapshot_for_trade_date(",
            ),
        }
        for path, (
            function_name,
            window_guard,
            *heavy_fragments,
        ) in window_order_fragments.items():
            function_source = _function_source(path, function_name)
            guard_index = function_source.find(window_guard)
            if guard_index < 0:
                issues.append(f"{path} must check run window before heavy readiness")
                continue
            for fragment in heavy_fragments:
                fragment_index = function_source.find(fragment)
                if fragment_index < 0:
                    issues.append(f"{path} misses expected qfq sensor fragment: {fragment}")
                elif guard_index > fragment_index:
                    issues.append(
                        f"{path} calls {fragment} before the run-window guard"
                    )

        repair_status_source = _function_source(
            DEFS_DIR / "asset_guards" / "stk_mins_qfq_factor_repair.py",
            "gold_stk_mins_qfq_factor_repair_status",
        )
        if "include_event_storage_ids: bool = True" not in repair_status_source:
            issues.append("qfq factor repair status must expose bounded metadata mode")

        evaluate_status_source = _function_source(
            DEFS_DIR / "asset_guards" / "stk_mins_qfq_factor_repair.py",
            "_evaluate_qfq_factor_repair_records",
        )
        if "include_event_storage_ids: bool = True" not in evaluate_status_source:
            issues.append("qfq factor repair evaluator must keep default storage id mode")
        if "if include_event_storage_ids:" not in evaluate_status_source:
            issues.append("qfq factor repair evaluator must guard storage id backfill")

        retired_basis_paths = (
            DEFS_DIR / "stk_mins_qfq_as_of_basis.py",
            DEFS_DIR / "bootstrap" / "stk_mins_qfq_as_of_basis.py",
            DEFS_DIR / "bootstrap" / "stk_mins_qfq_as_of_basis_cli.py",
        )
        retired_effective_path = (
            DEFS_DIR / "asset_guards" / "stk_mins_qfq_effective_readiness.py"
        )
        if retired_effective_path.exists():
            issues.append("retired qfq effective-readiness workaround must be deleted")
        for retired_basis_path in retired_basis_paths:
            if retired_basis_path.exists():
                issues.append(
                    f"retired qfq as-of-basis module must be deleted: {retired_basis_path}"
                )

        checks_source = (CHECKS_DIR / "stk_mins_checks.py").read_text()
        readiness_source = (
            DEFS_DIR / "asset_guards" / "stk_mins_lake_readiness.py"
        ).read_text()
        catalog_source = (DEFS_DIR / "catalog" / "lake_assets.py").read_text()
        sensor_readiness_source = (SENSORS_DIR / "readiness.py").read_text()
        bootstrap_sources = (
            (DEFS_DIR / "assets" / "stk_mins.py").read_text(),
            (DEFS_DIR / "stk_mins_qfq.py").read_text(),
            (DEFS_DIR / "stk_mins_qfq_factor_repair.py").read_text(),
            (DEFS_DIR / "bootstrap" / "stk_mins_qfq_bootstrap_events.py").read_text(),
            (
                DEFS_DIR / "bootstrap" / "stk_mins_qfq_derived_bootstrap_events.py"
            ).read_text(),
            (DEFS_DIR / "bootstrap" / "stk_mins_qfq_history.py").read_text(),
            (
                DEFS_DIR / "bootstrap" / "stk_mins_qfq_macd_kdj_baseline_events.py"
            ).read_text(),
        )
        for source_name, source in (
            (
                "qfq direct checks",
                checks_source,
            ),
            (
                "qfq lake readiness",
                readiness_source,
            ),
            ("qfq catalog", catalog_source),
            ("qfq sensor readiness", sensor_readiness_source),
            *(
                (f"qfq bootstrap source {index}", source)
                for index, source in enumerate(bootstrap_sources, start=1)
            ),
        ):
            issues.extend(
                f"{source_name} contains retired qfq validation fragment: {fragment}"
                for fragment in (
                    "as_of_basis",
                    "build_daily_qfq_select_sql_from_as_of_basis",
                    "GOLD_STK_MINS_QFQ_FORMULA_MATCHES_SILVER_ADJ_FACTOR_CHECK",
                    "GOLD_STK_MINS_QFQ_DERIVED_FORMULA_MATCHES_SOURCE_CHECK",
                    "GOLD_STK_MINS_QFQ_MACD_KDJ_FORMULA_SAMPLE_CHECK",
                    "_indicator_formula_result",
                    "_gold_qfq_formula_sample_sql",
                )
                if fragment in source
            )

        if "build_gold_stk_mins_qfq_derived_select_sql" in readiness_source:
            issues.append("qfq lake readiness must not evaluate the full derived QFQ SQL")
        if "build_gold_stk_mins_qfq_derived_coverage_sql" not in readiness_source:
            issues.append("qfq lake readiness must use derived identity coverage SQL")

        for source_name, source in (
            ("qfq direct checks", checks_source),
            ("qfq lake readiness", readiness_source),
        ):
            issues.extend(
                f"{source_name} still contains retired workaround fragment: {fragment}"
                for fragment in (
                    "effective_gold_qfq_readiness_for_trade_date",
                    "gold_qfq_formula_mismatch_codes",
                    "ready_after_qfq_factor_repair",
                )
                if fragment in source
            )

        self.assertEqual(issues, [])

    def test_stock_mins_continuity_hot_paths_do_not_reintroduce_slow_readiness(
        self,
    ) -> None:
        issues = []
        sensor_paths = (
            SENSORS_DIR / "stock_mins_raw_sensor.py",
            SENSORS_DIR / "stock_mins_silver_trade_day_sensor.py",
            SENSORS_DIR / "stock_mins_silver_sensor.py",
            SENSORS_DIR / "stock_mins_qfq_daily_sensor.py",
            SENSORS_DIR / "stock_mins_qfq_factor_repair_sensor.py",
        )
        forbidden_sensor_fragments = (
            "get_asset_check_execution_history",
            "partition_dataset_readiness_status_from_latest_checks",
            "raw_stk_mins_ready_for_trade_date",
            "silver_stk_mins_ready_for_trade_date",
            "gold_stk_mins_qfq_ready_for_trade_date",
            "full_semantics=False",
            "dg.RunRequest(",
            "RunRequest(",
            "run_key=f",
            "run_key=(",
        )
        for path in sensor_paths:
            source = path.read_text()
            issues.extend(
                f"{path} contains forbidden stock mins hot-path fragment: {fragment}"
                for fragment in forbidden_sensor_fragments
                if fragment in source
            )

        lake_readiness_source = (
            DEFS_DIR / "asset_guards" / "stk_mins_lake_readiness.py"
        ).read_text()
        forbidden_helper_fragments = (
            "import dagster",
            "from dagster",
            "DagsterInstance",
            "get_asset_check_execution_history",
            "partition_dataset_readiness_status_from_latest_checks",
            "get_event_records",
            "@dg.asset",
            "@dg.asset_check",
            "Definitions(",
            "status_manifest",
            "summary_asset",
            "readiness_asset",
        )
        required_helper_fragments = (
            "def batch_raw_stk_mins_lake_readiness",
            "def batch_silver_stk_mins_lake_readiness",
            "def batch_gold_stk_mins_qfq_lake_readiness",
            "full_semantics: bool = True",
            "failed_check_names",
            "materialized=False",
            "checks_passed=False",
        )
        issues.extend(
            "stk_mins_lake_readiness.py contains forbidden runtime/state fragment: "
            f"{fragment}"
            for fragment in forbidden_helper_fragments
            if fragment in lake_readiness_source
        )
        issues.extend(
            "stk_mins_lake_readiness.py misses required batch readiness fragment: "
            f"{fragment}"
            for fragment in required_helper_fragments
            if fragment not in lake_readiness_source
        )
        gold_qfq_batch_source = _function_source(
            DEFS_DIR / "asset_guards" / "stk_mins_lake_readiness.py",
            "batch_gold_stk_mins_qfq_lake_readiness",
        )
        forbidden_gold_qfq_batch_fragments = (
            "_gold_qfq_status_for_trade_date(",
            "_gold_qfq_native_counts_for_trade_date(",
            "_gold_qfq_derived_counts_for_trade_date(",
        )
        issues.extend(
            "batch_gold_stk_mins_qfq_lake_readiness must not call "
            f"single-date helper: {fragment}"
            for fragment in forbidden_gold_qfq_batch_fragments
            if fragment in gold_qfq_batch_source
        )
        qfq_daily_sensor_source = _function_source(
            SENSORS_DIR / "stock_mins_qfq_daily_sensor.py",
            "stock_mins_qfq_daily_sensor",
        )
        qfq_daily_sensor_file_source = (
            SENSORS_DIR / "stock_mins_qfq_daily_sensor.py"
        ).read_text()
        if "STOCK_MINS_QFQ_DAILY_READINESS_WINDOW_LIMIT = 5" not in (
            qfq_daily_sensor_file_source
        ):
            issues.append("qfq daily sensor hot-path window limit must stay at 5 days")
        if "expected_trade_dates[-STK_MINS_CONTINUITY_WINDOW_LIMIT:]" in (
            qfq_daily_sensor_file_source
        ):
            issues.append(
                "qfq daily sensor must not use the global 10-day continuity window"
            )
        if "STOCK_MINS_QFQ_DAILY_READINESS_WINDOW_LIMIT" not in qfq_daily_sensor_source:
            issues.append("qfq daily sensor must use its dedicated window constant")
        adj_factor_ready_guard_index = qfq_daily_sensor_source.find(
            "if not adj_factor_status.ready:"
        )
        gold_batch_call_index = qfq_daily_sensor_source.find(
            "batch_gold_stk_mins_qfq_lake_readiness("
        )
        if adj_factor_ready_guard_index < 0:
            issues.append("qfq daily sensor must guard on adj factor ready status")
        if gold_batch_call_index < 0:
            issues.append("qfq daily sensor must call gold qfq batch readiness")
        if (
            adj_factor_ready_guard_index >= 0
            and gold_batch_call_index >= 0
            and gold_batch_call_index < adj_factor_ready_guard_index
        ):
            issues.append(
                "qfq daily sensor must not load gold qfq batch before "
                "adj factor readiness passes"
            )

        adj_factor_readiness_source = (
            DEFS_DIR / "asset_guards" / "adj_factor_lake_readiness.py"
        ).read_text()
        adj_factor_required_fragments = (
            "def batch_raw_adj_factor_lake_readiness",
            "def batch_silver_adj_factor_lake_readiness",
            "def batch_adj_factor_lake_readiness",
            "silver_stock_lifecycle_path",
            "silver_cny_stock_lifecycle_select",
            "full_semantics: bool = True",
            "failed_check_names",
            "materialized = not missing_file_paths",
            "checks_passed = not failed_check_names",
        )
        adj_factor_forbidden_fragments = (
            "import dagster",
            "from dagster",
            "DagsterInstance",
            "get_asset_check_execution_history",
            "partition_dataset_readiness_status_from_latest_checks",
            "get_event_records",
            "silver_stock_basic_path",
            "current_cny_stock_basic_select",
        )
        issues.extend(
            "adj_factor_lake_readiness.py misses required batch readiness fragment: "
            f"{fragment}"
            for fragment in adj_factor_required_fragments
            if fragment not in adj_factor_readiness_source
        )
        issues.extend(
            "adj_factor_lake_readiness.py contains forbidden runtime/state fragment: "
            f"{fragment}"
            for fragment in adj_factor_forbidden_fragments
            if fragment in adj_factor_readiness_source
        )

        self.assertEqual(issues, [])

    def test_prod_clickhouse_market_breadth_checks_are_partition_attributable(
        self,
    ) -> None:
        issues = []
        asset_source = (ASSETS_DIR / "clickhouse_serving.py").read_text()
        checks_source = (CHECKS_DIR / "prod_clickhouse_serving_checks.py").read_text()
        job_source = (
            JOBS_DIR / "prod_clickhouse_share_fact_market_breadth_sync.py"
        ).read_text()
        event_retention_doc = Path(
            "../docs/design/dagster-event-history-retention-governance-plan.md"
        ).read_text()

        if "PROD_MARKET_BREADTH_SYNC_MAX_PARTITIONS_PER_RUN = 1" not in asset_source:
            issues.append(
                "prod_ch_share_fact_market_breadth_daily must run as a "
                "single-partition Dagster asset so check events are attributable"
            )
        if "requires exactly one partition" not in checks_source:
            issues.append(
                "prod ClickHouse serving checks must fail closed for "
                "multi-partition check contexts"
            )
        if "partitions_def=cn_a_stock_trade_days" not in checks_source:
            issues.append(
                "prod ClickHouse serving checks must explicitly declare "
                "cn_a_stock_trade_days partitions_def so check event partitions "
                "are not empty"
            )
        forbidden_check_fragments = (
            "check batch is too large",
            "mismatched_partition_count",
            "older_prod_partition_count",
        )
        issues.extend(
            "prod ClickHouse serving checks contain forbidden batch-check fragment: "
            f"{fragment}"
            for fragment in forbidden_check_fragments
            if fragment in checks_source
        )

        check_refresh_start = job_source.find(
            "prod_clickhouse_share_fact_market_breadth_check_refresh_job = "
            "dg.define_asset_job("
        )
        if check_refresh_start == -1:
            issues.append("prod ClickHouse checks-only refresh job is missing")
        else:
            check_refresh_source = job_source[check_refresh_start:]
            required_fragments = (
                "selection=dg.AssetSelection.checks_for_assets(\n"
                "        prod_ch_share_fact_market_breadth_daily\n"
                "    )",
                "config=dg.PartitionedConfig(",
                "run_config_for_partition_key_fn=_empty_check_refresh_run_config",
                "partitions_def=cn_a_stock_trade_days",
            )
            issues.extend(
                "prod ClickHouse checks-only refresh job misses required "
                f"fragment: {fragment}"
                for fragment in required_fragments
                if fragment not in check_refresh_source
            )
            if "AssetSelection.assets" in check_refresh_source:
                issues.append(
                    "prod ClickHouse checks-only refresh job must not select "
                    "materializable assets"
                )

        if "P3 第一批只允许包含：" not in event_retention_doc:
            issues.append("event retention plan must keep explicit P3 allowlist")
        p3_allowed_section = event_retention_doc.split(
            "P3 第一批只允许包含：",
            maxsplit=1,
        )[-1].split("P3 第一批禁止包含：", maxsplit=1)[0]
        if "prod_ch_share_fact_market_breadth_daily" in p3_allowed_section:
            issues.append(
                "event retention P3 allowlist must not include "
                "prod_ch_share_fact_market_breadth_daily before P2R completes"
            )

        self.assertEqual(issues, [])

    def test_sensor_cursor_decision_reason_uses_machine_codes(self) -> None:
        issues = []
        forbidden_fragments = (
            '"reason": reason',
            '"reason": decision.reason',
        )
        for path in SENSORS_DIR.glob("*.py"):
            source = path.read_text()
            issues.extend(
                f"{path} writes human decision reason into cursor: {fragment}"
                for fragment in forbidden_fragments
                if fragment in source
            )

        cursor_source = (DEFS_DIR / "run_contracts" / "cursors.py").read_text()
        for required_fragment in (
            "must be ASCII. Use reason_code",
            "decision diagnostics and keep human text in SkipReason",
        ):
            if required_fragment not in cursor_source:
                issues.append(
                    "cursor builder must reject non-ASCII reason values and "
                    f"explain reason_code usage: {required_fragment}"
                )

        self.assertEqual(issues, [])

    def test_sensor_cursor_payloads_do_not_embed_readiness_reports(self) -> None:
        issues = []
        forbidden_fragments = (
            "to_cursor_details()",
            '"status_samples":',
            '"sample_rows":',
            '"missing_file_paths":',
            '"readiness_details":',
            '"raw_batch_status":',
            '"silver_batch_status":',
            '"gold_batch_status":',
            '"serving_batch_status":',
            '"upstream_batch_statuses":',
            '"batch_status":',
            '"missing_file_path_sample":',
        )
        for path in _sensor_definition_files():
            source = path.read_text()
            issues.extend(
                f"{path} embeds report-style cursor detail fragment: {fragment}"
                for fragment in forbidden_fragments
                if fragment in source
            )

        cursor_source = (DEFS_DIR / "run_contracts" / "cursors.py").read_text()
        for required_fragment in (
            "summary and next_action",
            "ensure_ascii=False",
            "MAX_SENSOR_CURSOR_BYTES",
            "_FORBIDDEN_CURSOR_DETAIL_KEYS",
        ):
            if required_fragment not in cursor_source:
                issues.append(
                    "cursor builder must enforce compact human-readable v1 contract: "
                    f"{required_fragment}"
                )

        self.assertEqual(issues, [])

    def test_stock_daily_human_readable_governance_stays_compact(self) -> None:
        asset_path = ASSETS_DIR / "stock_daily.py"
        sensor_path = SENSORS_DIR / "stock_daily_sensor.py"
        check_path = CHECKS_DIR / "stock_daily_checks.py"
        asset_tree = _parse_python_file(asset_path)
        raw_cursor_source = _function_source(sensor_path, "_raw_sensor_cursor")
        combined_check_source = _function_source(check_path, "_combined_check_result")
        issues = []

        forbidden_cursor_fragments = (
            '"repair_details":',
            '"status_samples":',
            '"readiness_details":',
            '"raw_batch_status":',
        )
        issues.extend(
            f"{sensor_path} writes oversized stock daily cursor fragment: {fragment}"
            for fragment in forbidden_cursor_fragments
            if fragment in raw_cursor_source
        )

        forbidden_stdout_fields = {
            "sql",
            "query",
            "dataframe",
            "df",
            "ts_codes",
            "missing_codes",
            "sample_rows",
            "conflict_sample_rows",
            "duplicate_sample_rows",
        }
        for node in ast.walk(asset_tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute) or node.func.attr != "stdout":
                continue
            keyword_names = {keyword.arg for keyword in node.keywords if keyword.arg}
            forbidden = sorted(keyword_names & forbidden_stdout_fields)
            if forbidden:
                issues.append(
                    f"{_node_location(asset_path, node)} stock daily stdout writes "
                    f"forbidden fields {forbidden}"
                )

        for required_fragment in (
            "failed_rule_names",
            "rule_summary",
            "summary",
            "next_action",
        ):
            if required_fragment not in combined_check_source:
                issues.append(
                    "stock daily combined check must keep human-readable metadata "
                    f"and stable failed rules: {required_fragment}"
                )

        self.assertEqual(issues, [])

    def test_suspend_d_human_readable_governance_stays_compact(self) -> None:
        asset_path = ASSETS_DIR / "suspend_d.py"
        sensor_path = SENSORS_DIR / "suspend_d_sensor.py"
        check_path = CHECKS_DIR / "suspend_d_checks.py"
        asset_tree = _parse_python_file(asset_path)
        raw_cursor_source = _function_source(sensor_path, "_raw_sensor_cursor")
        silver_cursor_source = _function_source(sensor_path, "_silver_sensor_cursor")
        combined_check_source = _function_source(check_path, "_combined_check_result")
        missing_file_source = _function_source(check_path, "_missing_file_result")
        issues = []

        forbidden_cursor_fragments = (
            "to_cursor_details()",
            '"status_samples":',
            '"readiness_details":',
            '"raw_batch_status":',
            '"silver_batch_status":',
            '"gate_statuses_by_trade_date":',
        )
        for cursor_source in (raw_cursor_source, silver_cursor_source):
            issues.extend(
                f"{sensor_path} writes oversized suspend_d cursor fragment: {fragment}"
                for fragment in forbidden_cursor_fragments
                if fragment in cursor_source
            )

        forbidden_stdout_fields = {
            "sql",
            "query",
            "dataframe",
            "df",
            "ts_codes",
            "missing_codes",
            "sample_rows",
            "conflict_sample_rows",
            "duplicate_sample_rows",
        }
        for node in ast.walk(asset_tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute) or node.func.attr != "stdout":
                continue
            keyword_names = {keyword.arg for keyword in node.keywords if keyword.arg}
            forbidden = sorted(keyword_names & forbidden_stdout_fields)
            if forbidden:
                issues.append(
                    f"{_node_location(asset_path, node)} suspend_d stdout writes "
                    f"forbidden fields {forbidden}"
                )

        for required_fragment in (
            "failed_rule_names",
            "rule_summary",
            "summary",
            "next_action",
        ):
            if required_fragment not in combined_check_source:
                issues.append(
                    "suspend_d combined check must keep human-readable metadata "
                    f"and stable failed rules: {required_fragment}"
                )

        for required_fragment in ("summary", "next_action", "missing_file"):
            if required_fragment not in missing_file_source:
                issues.append(
                    "suspend_d missing file result must keep human-readable metadata: "
                    f"{required_fragment}"
                )

        self.assertEqual(issues, [])

    def test_adj_factor_human_readable_governance_stays_compact(self) -> None:
        asset_path = ASSETS_DIR / "adj_factor.py"
        sensor_path = SENSORS_DIR / "stock_adj_factor_sensor.py"
        check_path = CHECKS_DIR / "adj_factor_checks.py"
        asset_tree = _parse_python_file(asset_path)
        raw_cursor_source = _function_source(sensor_path, "_raw_sensor_cursor")
        silver_cursor_source = _function_source(sensor_path, "_silver_sensor_cursor")
        combined_check_source = _function_source(check_path, "_combined_check_result")
        missing_file_source = _function_source(check_path, "_missing_file_result")
        missing_input_source = _function_source(
            check_path,
            "_missing_input_file_result",
        )
        partition_allowed_source = _function_source(
            check_path,
            "_stock_current_partition_key_allowed_result",
        )
        issues = []

        forbidden_cursor_fragments = (
            "to_cursor_details()",
            ".to_cursor_details(",
            '"status_samples":',
            '"readiness_details":',
            '"raw_batch_status":',
            '"silver_batch_status":',
            '"gate_statuses_by_trade_date":',
        )
        for cursor_source in (raw_cursor_source, silver_cursor_source):
            issues.extend(
                f"{sensor_path} writes oversized adj_factor cursor fragment: {fragment}"
                for fragment in forbidden_cursor_fragments
                if fragment in cursor_source
            )

        forbidden_stdout_fields = {
            "sql",
            "query",
            "dataframe",
            "df",
            "ts_codes",
            "missing_codes",
            "sample_rows",
            "conflict_sample_rows",
            "duplicate_sample_rows",
            "invalid_sample_rows",
            "missing_code_samples",
            "unexpected_code_samples",
        }
        for node in ast.walk(asset_tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute) or node.func.attr != "stdout":
                continue
            keyword_names = {keyword.arg for keyword in node.keywords if keyword.arg}
            forbidden = sorted(keyword_names & forbidden_stdout_fields)
            if forbidden:
                issues.append(
                    f"{_node_location(asset_path, node)} adj_factor stdout writes "
                    f"forbidden fields {forbidden}"
                )

        for required_fragment in (
            "failed_rule_names",
            "rule_summary",
            "summary",
            "next_action",
        ):
            if required_fragment not in combined_check_source:
                issues.append(
                    "adj_factor combined check must keep human-readable metadata "
                    f"and stable failed rules: {required_fragment}"
                )

        for source_name, source in (
            ("missing file", missing_file_source),
            ("missing input file", missing_input_source),
            ("partition allowed", partition_allowed_source),
        ):
            for required_fragment in ("summary", "next_action"):
                if required_fragment not in source:
                    issues.append(
                        f"adj_factor {source_name} metadata must stay readable: "
                        f"{required_fragment}"
                    )

        self.assertEqual(issues, [])

    def test_basic_facts_human_readable_governance_stays_compact(self) -> None:
        asset_paths = (
            ASSETS_DIR / "calendar.py",
            ASSETS_DIR / "stock_basic.py",
            ASSETS_DIR / "stock_lifecycle.py",
            ASSETS_DIR / "namechange.py",
            ASSETS_DIR / "stock_identity_map.py",
            ASSETS_DIR / "index_basic.py",
        )
        sensor_paths = (
            SENSORS_DIR / "stock_basic_sensor.py",
            SENSORS_DIR / "stock_namechange_sensor.py",
            SENSORS_DIR / "stock_identity_map_sensor.py",
        )
        check_paths = (
            CHECKS_DIR / "calendar_checks.py",
            CHECKS_DIR / "stock_basic_checks.py",
            CHECKS_DIR / "stock_lifecycle_checks.py",
            CHECKS_DIR / "namechange_checks.py",
            CHECKS_DIR / "stock_identity_map_checks.py",
            CHECKS_DIR / "index_basic_checks.py",
        )
        issues = []

        forbidden_cursor_fragments = (
            "to_cursor_details()",
            '"status_samples":',
            '"readiness_details":',
            '"raw_batch_status":',
            '"silver_batch_status":',
            '"repair_details":',
        )
        for sensor_path in sensor_paths:
            source = sensor_path.read_text()
            issues.extend(
                f"{sensor_path} writes oversized basic facts cursor fragment: {fragment}"
                for fragment in forbidden_cursor_fragments
                if fragment in source
            )

        forbidden_stdout_fields = {
            "sql",
            "query",
            "dataframe",
            "df",
            "ts_codes",
            "sample_rows",
            "duplicate_sample_rows",
            "conflict_sample_rows",
        }
        for asset_path in asset_paths:
            asset_tree = _parse_python_file(asset_path)
            for node in ast.walk(asset_tree):
                if not isinstance(node, ast.Call):
                    continue
                if not isinstance(node.func, ast.Attribute) or node.func.attr != "stdout":
                    continue
                keyword_names = {keyword.arg for keyword in node.keywords if keyword.arg}
                forbidden = sorted(keyword_names & forbidden_stdout_fields)
                if forbidden:
                    issues.append(
                        f"{_node_location(asset_path, node)} basic facts stdout writes "
                        f"forbidden fields {forbidden}"
                    )

        for check_path in check_paths:
            combined_check_source = _function_source(check_path, "_combined_check_result")
            for required_fragment in (
                "failed_rule_names",
                "rule_summary",
                "summary",
                "next_action",
            ):
                if required_fragment not in combined_check_source:
                    issues.append(
                        "basic facts combined checks must keep human-readable metadata "
                        f"and stable failed rules: {check_path} missing {required_fragment}"
                    )

        self.assertEqual(issues, [])

    def test_sensor_hot_path_batch_readiness_helpers_stay_runtime_free(self) -> None:
        helper_requirements = {
            DEFS_DIR / "asset_guards" / "stk_mins_lake_readiness.py": (
                "def batch_raw_stk_mins_lake_readiness",
                "def batch_silver_stk_mins_lake_readiness",
                "def batch_gold_stk_mins_qfq_lake_readiness",
            ),
            DEFS_DIR / "asset_guards" / "adj_factor_lake_readiness.py": (
                "def batch_raw_adj_factor_lake_readiness",
                "def batch_silver_adj_factor_lake_readiness",
                "def batch_adj_factor_lake_readiness",
            ),
            DEFS_DIR / "asset_guards" / "market_major_indices_lake_readiness.py": (
                "def batch_market_major_indices_lake_readiness",
                "def batch_silver_index_daily_lake_readiness",
            ),
            DEFS_DIR / "asset_guards" / "market_breadth_lake_readiness.py": (
                "def batch_gold_market_breadth_lake_readiness",
                "def batch_gold_stock_return_distribution_lake_readiness",
                "def batch_clickhouse_market_breadth_readiness",
                "def batch_prod_clickhouse_market_breadth_readiness",
            ),
        }
        forbidden_fragments = (
            "import dagster",
            "from dagster",
            "DagsterInstance",
            "get_event_records",
            "get_asset_check_execution_history",
            "partition_dataset_readiness_status_from_latest_checks",
            "asset_readiness_status(",
            "dataset_readiness_status(",
            "RunRequest(",
            "dg.RunRequest(",
            "@dg.asset",
            "@dg.asset_check",
            "@dg.sensor",
            "Definitions(",
            "status_manifest",
            "summary_asset",
            "readiness_asset",
        )
        issues = []

        for path, required_fragments in helper_requirements.items():
            source = path.read_text()
            issues.extend(
                f"{path} misses sensor hot-path batch helper: {fragment}"
                for fragment in required_fragments
                if fragment not in source
            )
            issues.extend(
                f"{path} contains forbidden Dagster runtime fragment: {fragment}"
                for fragment in forbidden_fragments
                if fragment in source
            )

        gold_qfq_batch_source = _function_source(
            DEFS_DIR / "asset_guards" / "stk_mins_lake_readiness.py",
            "batch_gold_stk_mins_qfq_lake_readiness",
        )
        single_date_fragments = (
            "_gold_qfq_status_for_trade_date(",
            "_gold_qfq_native_counts_for_trade_date(",
            "_gold_qfq_derived_counts_for_trade_date(",
        )
        issues.extend(
            "batch_gold_stk_mins_qfq_lake_readiness must not call "
            f"single-date helper: {fragment}"
            for fragment in single_date_fragments
            if fragment in gold_qfq_batch_source
        )

        self.assertEqual(issues, [])

    def test_bounded_continuity_foundation_stays_pure_and_bounded(self) -> None:
        path = DEFS_DIR / "asset_guards" / "bounded_continuity.py"
        source = path.read_text()
        cursor_source = _function_source(path, "build_continuity_cursor_details")
        issues = []

        required_fragments = (
            "DEFAULT_CONTINUITY_WINDOW_LIMIT = 10",
            "DEFAULT_CONTINUITY_SAMPLE_LIMIT = 20",
            "class ContinuityExpectedDateWindow",
            "class ContinuityRegisteredGapStatus",
            "class ContinuityDateReadiness",
            "class ContinuityBatchReadiness",
            "class ContinuitySelection",
            "def load_expected_trade_date_window",
            "def build_registered_gap_status",
            "def select_first_not_ready_trade_date",
            "def build_continuity_cursor_details",
        )
        forbidden_fragments = (
            "import dagster",
            "from dagster",
            "DagsterInstance",
            "asset_readiness_status(",
            "dataset_readiness_status(",
            "partition_dataset_readiness_status_from_latest_checks",
            "get_asset_check_execution_history",
            "get_event_records",
            "duckdb.connect",
            "@dg.asset",
            "@dg.asset_check",
            "@dg.sensor",
            "RunRequest",
            "Definitions(",
            "status_manifest",
            "summary_asset",
            "readiness_asset",
        )
        issues.extend(
            f"{path} misses bounded continuity fragment: {fragment}"
            for fragment in required_fragments
            if fragment not in source
        )
        issues.extend(
            f"{path} contains forbidden runtime/state fragment: {fragment}"
            for fragment in forbidden_fragments
            if fragment in source
        )
        if "statuses_by_trade_date" in cursor_source:
            issues.append(
                "build_continuity_cursor_details must not write full statuses map"
            )

        self.assertEqual(issues, [])

    def test_stock_current_trade_day_sensor_uses_bounded_catch_up(self) -> None:
        path = SENSORS_DIR / "stock_current_trade_day_sensor.py"
        source = path.read_text()
        issues = []

        required_fragments = (
            "load_expected_trade_date_window",
            "build_registered_gap_status",
            "DEFAULT_CONTINUITY_WINDOW_LIMIT",
            "STOCK_CURRENT_TRADE_DAY_REGISTER_START = time(6, 0)",
            "STOCK_CURRENT_TRADE_DAY_MAX_PARTITIONS_PER_TICK = 2",
            "same_day_register_start=STOCK_CURRENT_TRADE_DAY_REGISTER_START",
            "window_limit=DEFAULT_CONTINUITY_WINDOW_LIMIT",
            "cn_a_stock_current_trade_days.build_add_request",
        )
        forbidden_fragments = (
            "StockCurrentTradeDayRegistrationDecision",
            "build_stock_current_trade_day_registration_decision",
            "build_trade_day_partition_registration_result",
            "resolve_latest_completed_trade_date",
            "load_completed_open_day_keys",
            "asset_readiness_status(",
            "dataset_readiness_status(",
            "partition_dataset_readiness_status_from_latest_checks",
            "get_asset_check_execution_history",
            "get_event_records",
            "RunRequest(",
            "dg.RunRequest(",
        )
        issues.extend(
            f"{path} misses current trade day bounded catch-up fragment: {fragment}"
            for fragment in required_fragments
            if fragment not in source
        )
        issues.extend(
            f"{path} contains forbidden current trade day fragment: {fragment}"
            for fragment in forbidden_fragments
            if fragment in source
        )

        self.assertEqual(issues, [])

    def test_stock_daily_and_suspend_sensors_use_registered_gap_guard(self) -> None:
        sensor_paths = (
            SENSORS_DIR / "stock_daily_sensor.py",
            SENSORS_DIR / "suspend_d_sensor.py",
        )
        issues = []

        required_fragments = (
            "load_expected_trade_date_window",
            "build_registered_gap_status",
            "build_continuity_cursor_details",
            "STOCK_TRADE_DAY_MIN_DATE",
            "STOCK_TRADE_DAY_REGISTER_START",
            "DEFAULT_CONTINUITY_WINDOW_LIMIT",
            "same_day_register_start=STOCK_TRADE_DAY_REGISTER_START",
            "window_limit=DEFAULT_CONTINUITY_WINDOW_LIMIT",
            "_registered_gap_skip_reason",
        )
        for path in sensor_paths:
            source = path.read_text()
            issues.extend(
                f"{path} misses stock trade day registered gap guard fragment: "
                f"{fragment}"
                for fragment in required_fragments
                if fragment not in source
            )
            if "source_window_started" in source:
                issues.append(
                    f"{path} must not introduce source-window cursor semantics "
                    "for non-minute daily continuity gap guards"
                )

        self.assertEqual(issues, [])

    def test_index_daily_sensors_use_registered_gap_guard(self) -> None:
        sensor_paths = (
            SENSORS_DIR / "raw_index_daily_update_job_sensor.py",
            SENSORS_DIR / "silver_index_daily_sensor.py",
        )
        issues = []

        required_fragments = (
            "load_expected_trade_date_window",
            "build_registered_gap_status",
            "build_continuity_cursor_details",
            "INDEX_TRADE_DAY_MIN_DATE",
            "SAME_DAY_PARTITION_REGISTER_START",
            "DEFAULT_CONTINUITY_WINDOW_LIMIT",
            "same_day_register_start=SAME_DAY_PARTITION_REGISTER_START",
            "window_limit=DEFAULT_CONTINUITY_WINDOW_LIMIT",
            "_registered_gap_skip_reason",
        )
        forbidden_fragments = (
            "_latest_registered_trade_date",
            "_eligible_registered_trade_dates",
        )
        for path in sensor_paths:
            source = path.read_text()
            issues.extend(
                f"{path} misses index trade day registered gap guard fragment: "
                f"{fragment}"
                for fragment in required_fragments
                if fragment not in source
            )
            issues.extend(
                f"{path} contains forbidden index daily gap guard fragment: "
                f"{fragment}"
                for fragment in forbidden_fragments
                if fragment in source
            )

        self.assertEqual(issues, [])

    def test_raw_index_daily_by_date_p1_p2_contracts(self) -> None:
        asset_source = (ASSETS_DIR / "index_daily.py").read_text()
        check_source = (CHECKS_DIR / "index_daily_checks.py").read_text()
        job_source = (JOBS_DIR / "index_daily_update.py").read_text()
        prod_source = (DEFS_DIR / "prod_db" / "index_daily.py").read_text()
        prod_select_source = prod_source[
            prod_source.index("PROD_INDEX_DAILY_SELECT_TEMPLATE") : prod_source.index(
                "@dataclass",
                prod_source.index("PROD_INDEX_DAILY_SELECT_TEMPLATE"),
            )
        ]
        issues = []

        required_fragments = {
            ASSETS_DIR / "index_daily.py": (
                "def raw_index_daily(",
                "partitions_def=cn_a_index_trade_days",
                "SourceSystem.PROD_CORE_DB",
                "column_schema=RAW_INDEX_DAILY_SCHEMA",
                "write_raw_index_daily_partition_from_prod_db",
                "context.instance.get_dynamic_partitions(cn_a_index_ts_codes.name)",
                "expected_code_set_hash",
            ),
            CHECKS_DIR / "index_daily_checks.py": (
                "def raw_index_daily_file_contract_check(",
                "def raw_index_daily_code_coverage_check(",
                "asset=raw_index_daily",
            ),
            JOBS_DIR / "index_daily_update.py": (
                "raw_index_daily_update_job = dg.define_asset_job(",
                "dg.AssetSelection.assets(raw_index_daily)",
                "dg.AssetSelection.checks_for_assets(raw_index_daily)",
            ),
            DEFS_DIR / "prod_db" / "index_daily.py": (
                "change_amount AS change",
                "to_char(trade_date, 'YYYYMMDD') AS trade_date",
                "core_serving.index_daily_serving",
                "PROD_INDEX_DAILY_DUCKDB_ATTACH_OPTIONS = \"TYPE POSTGRES, READ_ONLY\"",
            ),
        }
        sources_by_path = {
            ASSETS_DIR / "index_daily.py": asset_source,
            CHECKS_DIR / "index_daily_checks.py": check_source,
            JOBS_DIR / "index_daily_update.py": job_source,
            DEFS_DIR / "prod_db" / "index_daily.py": prod_source,
        }
        for path, fragments in required_fragments.items():
            source = sources_by_path[path]
            issues.extend(
                f"{path} misses raw_index_daily P1/P2 fragment: {fragment}"
                for fragment in fragments
                if fragment not in source
            )

        if "select *" in prod_select_source.lower():
            issues.append("prod index_daily select template must not use SELECT *")
        for forbidden_column in ("source", "created_at", "updated_at"):
            if forbidden_column in prod_select_source.lower():
                issues.append(
                    "prod index_daily select template must not export "
                    f"{forbidden_column}"
                )
        for forbidden_check_fragment in (
            "def raw_index_daily_file_exists(",
            "def raw_index_daily_row_count_positive(",
            "def raw_index_daily_required_columns_and_types(",
            "def raw_index_daily_partition_date_matches(",
            "def raw_index_daily_unique_ts_code_trade_date(",
        ):
            if forbidden_check_fragment in check_source:
                issues.append(
                    "raw_index_daily by-date checks must stay aggregated, found "
                    f"{forbidden_check_fragment}"
                )
        if "2026-06-23" in asset_source + check_source + prod_source:
            issues.append("raw_index_daily production code must not hardcode migration date")

        self.assertEqual(issues, [])

    def test_raw_index_daily_runless_bootstrap_removed_from_active_defs(self) -> None:
        helper_path = (
            DEFS_DIR / "bootstrap" / "index_daily_raw_by_date_runless_events.py"
        )
        cli_path = (
            DEFS_DIR / "bootstrap" / "index_daily_raw_by_date_runless_events_cli.py"
        )
        issues = []
        for path in (helper_path, cli_path):
            if path.exists():
                issues.append(f"{path} must not remain in active defs after P7")

        active_bootstrap_source = "\n".join(
            path.read_text()
            for path in (DEFS_DIR / "bootstrap").glob("*.py")
            if path.name != "__init__.py"
        )
        if "index_daily_raw_by_date_runless_events" in active_bootstrap_source:
            issues.append(
                "index daily runless event bootstrap code must not remain in active defs"
            )

        self.assertEqual(issues, [])

    def test_index_daily_by_date_p5_p6_active_path_contracts(self) -> None:
        asset_source = (ASSETS_DIR / "index_daily.py").read_text()
        check_source = (CHECKS_DIR / "index_daily_checks.py").read_text()
        raw_sensor_path = SENSORS_DIR / "raw_index_daily_update_job_sensor.py"
        silver_sensor_path = SENSORS_DIR / "silver_index_daily_sensor.py"
        major_helper_path = (
            DEFS_DIR / "asset_guards" / "market_major_indices_lake_readiness.py"
        )
        readiness_path = SENSORS_DIR / "readiness.py"
        raw_file_readiness_path = SENSORS_DIR / "index_daily_raw_file_readiness.py"
        raw_sensor_source = raw_sensor_path.read_text()
        silver_sensor_source = silver_sensor_path.read_text()
        major_helper_source = major_helper_path.read_text()
        readiness_source = readiness_path.read_text()
        raw_file_readiness_source = raw_file_readiness_path.read_text()
        silver_asset_start = asset_source.index('@dg.asset(\n    name="silver_index_daily"')
        silver_asset_end = asset_source.index("def silver_index_daily(")
        silver_asset_slice = asset_source[silver_asset_start:silver_asset_end]
        silver_coverage_start = check_source.index(
            "def evaluate_silver_index_daily_registered_code_coverage"
        )
        silver_coverage_end = check_source.index("@dg.asset_check(", silver_coverage_start)
        silver_coverage_slice = check_source[
            silver_coverage_start:silver_coverage_end
        ]
        issues = []

        required_fragments = {
            raw_sensor_path: (
                'job_name="raw_index_daily_update_job"',
                "default_status=dg.DefaultSensorStatus.STOPPED",
                "raw_index_daily_lake_readiness_for_trade_dates",
                "check_prod_index_daily_source_readiness",
                "build_raw_index_daily_update_job_run_config",
                'subject="raw_index_daily"',
                'write_mode="replace"',
                "build_cursor_details",
                "reason_code=reason_code",
                "blocked_component=_blocked_component_for_reason",
            ),
            silver_sensor_path: (
                'job_name="silver_index_daily_update_job"',
                "default_status=dg.DefaultSensorStatus.STOPPED",
                "raw_index_daily_lake_readiness_for_trade_dates",
                "batch_silver_index_daily_lake_readiness",
                "select_first_not_ready_trade_date",
                'subject="silver_index_daily"',
                "build_cursor_details",
                "reason_code=reason_code",
            ),
            major_helper_path: (
                "raw_index_daily_path",
                "raw_file_path",
                "silver_index_daily_lake_readiness_for_trade_date",
            ),
            readiness_path: (
                'RAW_INDEX_DAILY_ASSET_KEY = dg.AssetKey("raw_index_daily")',
                "RAW_INDEX_DAILY_CHECKS",
                "RAW_INDEX_DAILY_READINESS_SPEC",
                "def raw_index_daily_ready_for_trade_date(",
            ),
            raw_file_readiness_path: (
                "RAW_INDEX_DAILY_READINESS_TRADE_DAY_LIMIT = 10",
                "def raw_index_daily_lake_readiness_for_trade_dates(",
                "raw_index_daily_file_contract_check",
                "raw_index_daily_code_coverage_check",
            ),
        }
        sources_by_path = {
            raw_sensor_path: raw_sensor_source,
            silver_sensor_path: silver_sensor_source,
            major_helper_path: major_helper_source,
            readiness_path: readiness_source,
            raw_file_readiness_path: raw_file_readiness_source,
        }
        for path, fragments in required_fragments.items():
            source = sources_by_path[path]
            issues.extend(
                f"{path} misses P5/P6 by-date fragment: {fragment}"
                for fragment in fragments
                if fragment not in source
            )

        forbidden_raw_sensor_fragments = (
            "tushare",
            "selected_codes",
            "next_pending_offset",
            "repair_state",
            "index_daily:",
            "raw_index_daily_by_code_path",
            "audit_index_daily_raw_gaps",
            "check_index_daily_raw_files_for_trade_date",
            "raw_tushare_index_daily_by_code",
            "2026-06-22",
            "2026-06-23",
            '"raw_batch_status":',
            "raw_batch_status.to_cursor_details()",
            '"status_samples"',
        )
        issues.extend(
            f"{raw_sensor_path} contains forbidden P5/P6 raw sensor fragment: {fragment}"
            for fragment in forbidden_raw_sensor_fragments
            if fragment in raw_sensor_source
        )

        forbidden_active_path_fragments = (
            "raw_index_daily_by_code_path",
            "audit_index_daily_raw_gaps",
            "check_index_daily_raw_files_for_trade_date",
            "raw_tushare_index_daily_by_code",
            "2026-06-22",
            "2026-06-23",
            "select_first_not_ready_silver_index_daily_partition",
            "silver_index_daily_ready_for_trade_date",
            "partition_dataset_readiness_status_from_latest_checks",
        )
        for path, source in (
            (silver_sensor_path, silver_sensor_source),
            (major_helper_path, major_helper_source),
        ):
            issues.extend(
                f"{path} contains forbidden P5/P6 active path fragment: {fragment}"
                for fragment in forbidden_active_path_fragments
                if fragment in source
            )

        if "dg.AssetDep(raw_index_daily)" not in silver_asset_slice:
            issues.append("silver_index_daily asset must depend on raw_index_daily")
        for fragment in ("AllPartitionMapping", "raw_tushare_index_daily_by_code"):
            if fragment in silver_asset_slice:
                issues.append(
                    "silver_index_daily asset active dependency must not contain "
                    f"{fragment}"
                )
        if '"source_asset": "raw_index_daily"' not in silver_asset_slice:
            issues.append("silver_index_daily metadata must name raw_index_daily source")
        if "raw_index_daily_path" not in silver_coverage_slice:
            issues.append("silver coverage check must compare against raw by-date path")
        if "cn_a_index_ts_codes" in silver_coverage_slice:
            issues.append("silver coverage check must not read current dynamic codes")

        self.assertEqual(issues, [])

    def test_index_daily_human_readable_governance_stays_compact(self) -> None:
        asset_path = ASSETS_DIR / "index_daily.py"
        check_path = CHECKS_DIR / "index_daily_checks.py"
        raw_sensor_path = SENSORS_DIR / "raw_index_daily_update_job_sensor.py"
        silver_sensor_path = SENSORS_DIR / "silver_index_daily_sensor.py"
        asset_tree = _parse_python_file(asset_path)
        asset_source = asset_path.read_text()
        raw_sensor_source = raw_sensor_path.read_text()
        silver_cursor_source = _function_source(silver_sensor_path, "_cursor_payload")
        silver_summary_source = _function_source(
            silver_sensor_path,
            "_cursor_summary_and_next_action",
        )
        combined_check_source = _function_source(check_path, "_combined_check_result")
        raw_file_contract_source = _function_source(
            check_path,
            "evaluate_raw_index_daily_file_contract",
        )
        raw_coverage_source = _function_source(
            check_path,
            "evaluate_raw_index_daily_code_coverage",
        )
        silver_coverage_source = _function_source(
            check_path,
            "evaluate_silver_index_daily_registered_code_coverage",
        )
        issues = []

        forbidden_cursor_fragments = (
            "to_cursor_details()",
            ".to_cursor_details(",
            '"status_samples":',
            '"readiness_details":',
            '"raw_batch_status":',
            '"silver_batch_status":',
            '"coverage_results":',
            '"results":',
        )
        for path, source in (
            (raw_sensor_path, raw_sensor_source),
            (silver_sensor_path, silver_cursor_source),
        ):
            issues.extend(
                f"{path} writes oversized index_daily cursor fragment: {fragment}"
                for fragment in forbidden_cursor_fragments
                if fragment in source
            )

        forbidden_stdout_fields = {
            "sql",
            "query",
            "dataframe",
            "df",
            "ts_codes",
            "index_codes",
            "missing_codes",
            "sample_rows",
            "duplicate_sample_rows",
            "missing_code_samples",
            "extra_code_samples",
        }
        for node in ast.walk(asset_tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute) or node.func.attr != "stdout":
                continue
            keyword_names = {keyword.arg for keyword in node.keywords if keyword.arg}
            forbidden = sorted(keyword_names & forbidden_stdout_fields)
            if forbidden:
                issues.append(
                    f"{_node_location(asset_path, node)} index_daily stdout writes "
                    f"forbidden fields {forbidden}"
                )

        for required_fragment in (
            "summary",
            "next_action",
            "result_status",
            "input_summary",
            "diagnostic_ref",
        ):
            if required_fragment not in asset_source:
                issues.append(
                    "index_daily materialization metadata must stay readable: "
                    f"{required_fragment}"
                )

        for source_name, source, required_fragments in (
            (
                "combined check",
                combined_check_source,
                ("failed_rule_names", "rule_summary", "summary", "next_action"),
            ),
            (
                "raw file contract",
                raw_file_contract_source,
                ("contract_summary", "rule_summary", "summary", "next_action"),
            ),
            (
                "raw coverage",
                raw_coverage_source,
                ("coverage_summary", "rule_summary", "summary", "next_action"),
            ),
            (
                "silver coverage",
                silver_coverage_source,
                ("coverage_summary", "rule_summary", "summary", "next_action"),
            ),
        ):
            for required_fragment in required_fragments:
                if required_fragment not in source:
                    issues.append(
                        f"index_daily {source_name} metadata must stay readable: "
                        f"{required_fragment}"
                    )

        for required_fragment in (
            "raw_index_daily 还没有 ready",
            "cn_a_index_ts_codes",
            "silver_index_daily blocking checks",
        ):
            if required_fragment not in silver_summary_source:
                issues.append(
                    "silver_index_daily sensor cursor summary must stay actionable: "
                    f"{required_fragment}"
                )

        self.assertEqual(issues, [])

    def test_index_daily_p7_removes_by_code_active_source_and_catalog(self) -> None:
        issues = []
        removed_files = (
            SENSORS_DIR / "index_daily_sensor.py",
            SENSORS_DIR / "index_daily_late_arrival_repair.py",
            DEFS_DIR / "bootstrap" / "index_daily_raw_by_date_runless_events.py",
            DEFS_DIR / "bootstrap" / "index_daily_raw_by_date_runless_events_cli.py",
        )
        for path in removed_files:
            if path.exists():
                issues.append(f"{path} must not exist after P7")

        forbidden_fragments = (
            "raw_tushare_index_daily_by_code",
            "raw_index_daily_by_code",
            "index_daily_by_code",
            "IndexDailyRawByCode",
            "RAW_TUSHARE_INDEX_DAILY_BY_CODE",
            "RAW_INDEX_DAILY_BY_CODE",
            "build_index_daily_update_job_run_config",
            "select_index_daily_pending_code_runs",
            "audit_index_daily_raw_gaps",
            "check_index_daily_raw_files_for_trade_date",
            'name="index_daily_update_job"',
            'job_name="index_daily_update_job"',
            '"index_daily_update_job"',
            "MAX_RUN_REQUESTS_PER_TICK = 500",
        )
        for path in sorted(DEFS_DIR.rglob("*.py")):
            source = path.read_text()
            issues.extend(
                f"{path} contains removed index daily by-code fragment: {fragment}"
                for fragment in forbidden_fragments
                if fragment in source
            )

        self.assertEqual(issues, [])

    def test_market_major_indices_sensor_uses_bounded_lake_readiness(self) -> None:
        sensor_path = SENSORS_DIR / "market_major_indices_daily_sensor.py"
        helper_path = DEFS_DIR / "asset_guards" / "market_major_indices_lake_readiness.py"
        sensor_source = sensor_path.read_text()
        helper_source = helper_path.read_text()
        issues = []

        required_sensor_fragments = (
            "load_expected_trade_date_window",
            "build_registered_gap_status",
            "select_first_not_ready_trade_date",
            "build_continuity_cursor_details",
            "batch_market_major_indices_lake_readiness",
            "silver_index_daily_lake_readiness_for_trade_date",
            "silver_index_basic_lake_readiness",
            "build_run_request",
            "build_asset_update_run_key",
        )
        forbidden_sensor_fragments = (
            "gold_market_major_indices_daily_ready_for_trade_date",
            "silver_index_daily_ready_for_trade_date",
            "silver_index_basic_ready",
            "asset_readiness_status",
            "partition_dataset_readiness_status_from_latest_checks",
            "_latest_registered_trade_date",
            "get_asset_check_execution_history",
            "dg.RunRequest(",
            "RunRequest(",
            "run_key=f",
            "run_key=(",
        )
        forbidden_helper_fragments = (
            "get_asset_check_execution_history",
            "asset_readiness_status",
            "partition_dataset_readiness_status_from_latest_checks",
            "gold_market_major_indices_daily_ready_for_trade_date",
            "silver_index_daily_ready_for_trade_date",
            "silver_index_basic_ready",
            "DagsterInstance",
            "RunRequest",
        )
        issues.extend(
            f"{sensor_path} misses market major indices lake readiness fragment: "
            f"{fragment}"
            for fragment in required_sensor_fragments
            if fragment not in sensor_source
        )
        issues.extend(
            f"{sensor_path} contains forbidden market major indices hot-path "
            f"fragment: {fragment}"
            for fragment in forbidden_sensor_fragments
            if fragment in sensor_source
        )
        issues.extend(
            f"{helper_path} contains forbidden market major indices helper "
            f"fragment: {fragment}"
            for fragment in forbidden_helper_fragments
            if fragment in helper_source
        )

        self.assertEqual(issues, [])

    def test_market_major_indices_human_readable_governance_stays_compact(
        self,
    ) -> None:
        asset_path = ASSETS_DIR / "market_major_indices.py"
        check_path = CHECKS_DIR / "market_major_indices_checks.py"
        sensor_path = SENSORS_DIR / "market_major_indices_daily_sensor.py"
        asset_source = asset_path.read_text()
        check_source = check_path.read_text()
        sensor_source = sensor_path.read_text()
        issues = []

        for required_fragment in (
            "gold_market_major_indices_started",
            "gold_market_major_indices_completed",
            "metric_summary",
            "主要指数日线 gold",
        ):
            if required_fragment not in asset_source:
                issues.append(
                    "market major indices asset misses human-readable fragment: "
                    f"{required_fragment}"
                )

        for required_fragment in (
            "rule_summary",
            "failed_rule_names",
            "summary",
            "next_action",
        ):
            if required_fragment not in check_source:
                issues.append(
                    "market major indices checks miss readable metadata fragment: "
                    f"{required_fragment}"
                )

        for required_fragment in (
            "_summary_and_next_action",
            "cn_a_index_ts_codes",
            "silver_index_daily 还没有 ready",
            "silver_index_basic 还没有 ready",
        ):
            if required_fragment not in sensor_source:
                issues.append(
                    "market major indices sensor cursor must stay actionable: "
                    f"{required_fragment}"
                )

        forbidden_stdout_fragments = (
            "sql=",
            "query=",
            "dataframe=",
            "active_seed_codes=",
            "seed_codes=",
            "sample_rows=",
        )
        for fragment in forbidden_stdout_fragments:
            if fragment in asset_source:
                issues.append(
                    "market major indices stdout must not write bulky field: "
                    f"{fragment}"
                )

        forbidden_cursor_fragments = (
            "status_samples",
            "to_cursor_details(",
            "active_seed_codes",
            "partition_metadata",
        )
        for fragment in forbidden_cursor_fragments:
            if fragment in sensor_source:
                issues.append(
                    "market major indices cursor must not write report field: "
                    f"{fragment}"
                )

        self.assertEqual(issues, [])

    def test_asset_definitions_use_asset_tag_and_metadata_helpers(self) -> None:
        issues = []

        for path in _python_files(ASSETS_DIR):
            tree = _parse_python_file(path)
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for decorator in node.decorator_list:
                    if not _is_call_named(decorator, "asset"):
                        continue

                    tags_value = _keyword_value(decorator, "tags")
                    metadata_value = _keyword_value(decorator, "metadata")
                    if not _is_call_named(tags_value, "build_asset_tags"):
                        issues.append(
                            f"{_node_location(path, decorator)} asset {node.name} "
                            "does not use build_asset_tags(...)"
                        )
                    if not _is_call_named(
                        metadata_value,
                        "build_asset_definition_metadata",
                    ):
                        issues.append(
                            f"{_node_location(path, decorator)} asset {node.name} "
                            "does not use build_asset_definition_metadata(...)"
                        )
                    if _is_call_named(metadata_value, "build_asset_definition_metadata"):
                        column_schema_value = _keyword_value(
                            metadata_value,
                            "column_schema",
                        )
                        if (
                            column_schema_value is None
                            and node.name not in ASSETS_WITHOUT_COLUMN_SCHEMA
                        ):
                            issues.append(
                                f"{_node_location(path, metadata_value)} asset "
                                f"{node.name} does not register column_schema"
                            )
                        path_template_value = _keyword_value(
                            metadata_value,
                            "path_template",
                        )
                        if isinstance(path_template_value, ast.Constant) and isinstance(
                            path_template_value.value,
                            str,
                        ):
                            issues.append(
                                f"{_node_location(path, path_template_value)} asset "
                                f"{node.name} writes path_template literal"
                            )

        self.assertEqual(issues, [])

    def test_asset_check_results_use_check_metadata_builder(self) -> None:
        issues = []

        for path in _python_files(CHECKS_DIR):
            tree = _parse_python_file(path)
            check_metadata_builder_names = _check_metadata_builder_names(tree)
            for node in ast.walk(tree):
                if not _is_call_named(node, "AssetCheckResult"):
                    continue
                metadata_value = _keyword_value(node, "metadata")
                if (
                    metadata_value is not None
                    and isinstance(metadata_value, ast.Call)
                    and _call_name(metadata_value.func) in check_metadata_builder_names
                ):
                    continue
                if metadata_value is not None:
                    issues.append(
                        f"{_node_location(path, node)} AssetCheckResult metadata "
                        "does not use build_check_metadata(...)"
                    )

        self.assertEqual(issues, [])

    def test_gold_stock_daily_qfq_ordinary_checks_stay_compact(self) -> None:
        check_path = CHECKS_DIR / "stock_daily_qfq_checks.py"
        job_path = JOBS_DIR / "stock_daily_qfq_update.py"
        readiness_path = SENSORS_DIR / "readiness.py"
        check_source = check_path.read_text()
        job_source = job_path.read_text()
        readiness_source = readiness_path.read_text()
        issues = []

        required_check_names = (
            "gold_stock_daily_qfq_contract_check",
        )
        protected_repair_check_name = "gold_stock_daily_qfq_factor_repair_plan_evaluated"

        if check_source.count("@dg.asset_check") != 1:
            issues.append("stock_daily_qfq ordinary checks must stay at 1")
        if check_source.count("partitions_def=cn_a_stock_trade_days") != 1:
            issues.append(
                "stock_daily_qfq ordinary checks must explicitly declare "
                "cn_a_stock_trade_days partitions_def so check events are "
                "attributed to the target partition"
            )
        for check_name in required_check_names:
            if check_name not in check_source:
                issues.append(f"{check_path} misses ordinary check {check_name}")
            if check_name not in readiness_source:
                issues.append(f"{readiness_path} misses readiness check {check_name}")
        forbidden_formula_fragments = (
            "gold_stock_daily_qfq_qfq_semantics_check",
            "qfq_semantics",
            "formula",
            "as_of_adj_factor_path",
            "silver_adj_factor_path",
            "silver_stock_daily_path",
        )
        for fragment in forbidden_formula_fragments:
            if fragment in check_source:
                issues.append(
                    f"{check_path} must not contain formula validation fragment: "
                    f"{fragment}"
                )
        if protected_repair_check_name in readiness_source:
            issues.append(
                "gold_stock_daily_qfq repair status check must not enter ordinary "
                "readiness"
            )

        check_refresh_start = job_source.find(
            "gold_stock_daily_qfq_check_refresh_job = dg.define_asset_job("
        )
        if check_refresh_start == -1:
            issues.append("stock_daily_qfq checks-only refresh job is missing")
        else:
            check_refresh_source = job_source[check_refresh_start:]
            required_fragments = (
                "selection=dg.AssetSelection.checks_for_assets(gold_stock_daily_qfq)",
                "partitions_def=cn_a_stock_trade_days",
                "executor_def=dg.in_process_executor",
            )
            issues.extend(
                "stock_daily_qfq checks-only refresh job misses required "
                f"fragment: {fragment}"
                for fragment in required_fragments
                if fragment not in check_refresh_source
            )
            if "AssetSelection.assets" in check_refresh_source:
                issues.append(
                    "stock_daily_qfq checks-only refresh job must not select "
                    "materializable assets"
                )

        self.assertEqual(issues, [])

    def test_gold_stock_daily_qfq_p8_reset_tool_is_scoped_and_guarded(self) -> None:
        helper_path = (
            DEFS_DIR / "bootstrap" / "gold_stock_daily_qfq_history_reset.py"
        )
        cli_path = (
            DEFS_DIR / "bootstrap" / "gold_stock_daily_qfq_history_reset_cli.py"
        )
        helper_source = helper_path.read_text()
        cli_source = cli_path.read_text()
        combined = f"{helper_source}\n{cli_source}"
        issues = []

        required_fragments = (
            '"gold_stock_daily_qfq"',
            '"gold"',
            '"quote"',
            '"stock_daily_qfq"',
            '"dry-run"',
            '"apply"',
            "--confirm-reset",
            "--backup-path",
            "--delete-lake-files",
            "--delete-dagster-events",
            "running_or_queued_run_count",
            "GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME",
            "DELETE FROM asset_event_tags",
            "DELETE FROM event_logs",
            "DELETE FROM asset_check_executions",
        )
        forbidden_fragments = (
            "DELETE FROM runs",
            "DELETE FROM run_tags",
            "DELETE FROM dynamic_partitions",
            "DELETE FROM instigators",
            "TRUNCATE",
            "DROP TABLE",
            "VACUUM",
            "gold_stock_daily_qfq_qfq_semantics_check",
        )
        issues.extend(
            f"gold_stock_daily_qfq P8 reset tool misses fragment: {fragment}"
            for fragment in required_fragments
            if fragment not in combined
        )
        issues.extend(
            f"gold_stock_daily_qfq P8 reset tool contains forbidden fragment: {fragment}"
            for fragment in forbidden_fragments
            if fragment in combined
        )

        self.assertEqual(issues, [])

    def test_gold_stock_daily_qfq_daily_sensor_uses_bounded_run_contracts(self) -> None:
        sensor_path = SENSORS_DIR / "stock_daily_qfq_sensor.py"
        source = sensor_path.read_text()
        issues = []

        required_snippets = (
            "select_first_not_ready_gold_stock_daily_qfq_partition",
            "build_run_request",
            "build_asset_update_run_key",
            "build_sensor_cursor",
            "cn_a_stock_trade_days",
            "required_resource_keys={\"lake_root\", \"duckdb\"}",
            "default_status=dg.DefaultSensorStatus.STOPPED",
        )
        for snippet in required_snippets:
            if snippet not in source:
                issues.append(f"{sensor_path} misses required snippet: {snippet}")

        forbidden_snippets = (
            "dg.RunRequest(",
            "RunRequest(",
            "run_key=f",
            "gold_stock_daily_qfq_ready_for_trade_date(",
            "stock_codes",
            "get_event_records(",
        )
        for snippet in forbidden_snippets:
            if snippet in source:
                issues.append(f"{sensor_path} contains forbidden snippet: {snippet}")

        self.assertEqual(issues, [])

    def test_gold_stock_daily_qfq_factor_repair_sensor_uses_bounded_run_contracts(self) -> None:
        sensor_path = SENSORS_DIR / "gold_stock_daily_qfq_factor_repair_job_sensor.py"
        status_path = DEFS_DIR / "asset_guards" / "stock_daily_qfq_factor_repair.py"
        config_path = DEFS_DIR / "run_contracts" / "configs.py"
        source = sensor_path.read_text()
        status_source = status_path.read_text()
        config_source = config_path.read_text()
        config_builder_source = _function_source(
            config_path,
            "build_gold_stock_daily_qfq_factor_repair_run_config",
        )
        issues = []

        required_sensor_snippets = (
            "@dg.run_status_sensor",
            "request_job=gold_stock_daily_qfq_factor_repair_job",
            "monitored_jobs=[gold_stock_daily_qfq_update_job]",
            "default_status=dg.DefaultSensorStatus.STOPPED",
            "build_batch_id",
            "build_upstream_triggered_run_key",
            "build_run_request",
            "build_gold_stock_daily_qfq_factor_repair_run_config",
            "gold_stock_daily_qfq_factor_repair_status",
            "connect_configured_duckdb",
            "GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_AUTO_CODE_LIMIT",
        )
        for snippet in required_sensor_snippets:
            if snippet not in source:
                issues.append(f"{sensor_path} misses required snippet: {snippet}")

        forbidden_sensor_snippets = (
            "dg.RunRequest(",
            "RunRequest(",
            "run_key=f",
            "stock_codes",
            "get_event_records",
            "event_storage_id",
            "storage_id",
            "context.resources",
        )
        for snippet in forbidden_sensor_snippets:
            if snippet in source:
                issues.append(f"{sensor_path} contains forbidden snippet: {snippet}")

        if "class GoldStockDailyQfqFactorRepairConfig" not in config_source:
            issues.append("missing GoldStockDailyQfqFactorRepairConfig")
        if "stock_codes" in config_builder_source:
            issues.append(
                "gold stock daily qfq factor repair run config must not expose "
                "stock_codes"
            )

        forbidden_status_snippets = (
            "get_event_records",
            "event_storage_id",
            "storage_id",
        )
        for snippet in forbidden_status_snippets:
            if snippet in status_source:
                issues.append(f"{status_path} contains forbidden snippet: {snippet}")

        self.assertEqual(issues, [])

    def test_gold_stock_daily_qfq_history_bootstrap_does_not_write_dagster_events(self) -> None:
        bootstrap_paths = (
            DEFS_DIR / "bootstrap" / "gold_stock_daily_qfq_history.py",
            DEFS_DIR / "bootstrap" / "gold_stock_daily_qfq_history_cli.py",
        )
        issues = []
        forbidden_snippets = (
            "report_runless_asset_event",
            "DagsterInstance",
            "get_event_records",
            "AssetMaterialization",
            "AssetCheckEvaluation",
            "dg.",
        )
        for path in bootstrap_paths:
            source = path.read_text()
            if path.name.endswith("_cli.py") and "--as-of-trade-date" not in source:
                issues.append(f"{path} misses required --as-of-trade-date")
            for snippet in forbidden_snippets:
                if snippet in source:
                    issues.append(f"{path} contains forbidden snippet: {snippet}")

        self.assertEqual(issues, [])

    def test_gold_stock_daily_qfq_history_events_are_manual_bootstrap_only(self) -> None:
        helper_path = (
            DEFS_DIR / "bootstrap" / "gold_stock_daily_qfq_history_events.py"
        )
        cli_path = (
            DEFS_DIR / "bootstrap" / "gold_stock_daily_qfq_history_events_cli.py"
        )
        helper_source = helper_path.read_text()
        cli_source = cli_path.read_text()
        combined = f"{helper_source}\n{cli_source}"
        issues = []

        forbidden_fragments = (
            "@dg.asset",
            "@dg.asset_check",
            "@dg.sensor",
            "@dg.run_status_sensor",
            "define_asset_job",
            "get_event_records",
            "event_storage_id",
            "storage_id\"",
        )
        required_fragments = (
            "GOLD_STOCK_DAILY_QFQ_RUNLESS_CHECK_WINDOW_SIZE = 20",
            "GOLD_STOCK_DAILY_QFQ_RUNLESS_CHECK_EVENT_MAX_PARTITIONS = 21",
            "report_runless_asset_event",
            "AssetMaterialization(",
            "AssetCheckEvaluation(",
            "\"plan-events\"",
            "\"report-events\"",
            "--as-of-trade-date",
            "--apply",
        )
        p8_forbidden_fragments = (
            "gold_stock_daily_qfq_qfq_semantics_check",
            "qfq_semantics",
            "formula",
        )
        issues.extend(
            f"gold stock daily qfq history event helper contains forbidden fragment: {fragment}"
            for fragment in forbidden_fragments
            if fragment in combined
        )
        issues.extend(
            f"gold stock daily qfq history event helper contains P8 forbidden "
            f"fragment: {fragment}"
            for fragment in p8_forbidden_fragments
            if fragment in combined
        )
        issues.extend(
            f"gold stock daily qfq history event helper misses required fragment: {fragment}"
            for fragment in required_fragments
            if fragment not in combined
        )

        self.assertEqual(issues, [])

    def test_metadata_dicts_do_not_write_legacy_keys(self) -> None:
        issues = []

        for path in (*_python_files(ASSETS_DIR), *_python_files(CHECKS_DIR)):
            tree = _parse_python_file(path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue

                checked_keys = set()
                call_name = _call_name(node.func)
                if call_name == "build_materialization_metadata":
                    if _keyword_value(node, "columns") is not None:
                        issues.append(
                            f"{_node_location(path, node)} uses removed "
                            "materialization columns keyword"
                        )
                if call_name in {
                    "build_materialization_metadata",
                    "build_check_metadata",
                    "MaterializeResult",
                    "AssetCheckResult",
                }:
                    checked_keys |= _dict_keys_for_keyword(node, "metadata")
                    checked_keys |= _dict_keys_for_keyword(node, "extra_metadata")

                legacy_keys = checked_keys & LEGACY_METADATA_KEYS
                if legacy_keys:
                    issues.append(
                        f"{_node_location(path, node)} writes legacy metadata keys "
                        f"{sorted(legacy_keys)}"
                    )

        self.assertEqual(issues, [])

    def test_stk_mins_name_timeline_event_correction_dry_run_is_read_only(
        self,
    ) -> None:
        helper_path = (
            DEFS_DIR / "bootstrap" / "stk_mins_name_timeline_check_events.py"
        )
        cli_path = (
            DEFS_DIR / "bootstrap" / "stk_mins_name_timeline_check_events_cli.py"
        )
        helper_source = helper_path.read_text()
        cli_source = cli_path.read_text()
        issues = []

        forbidden_helper_fragments = (
            "report_runless_asset_event",
            "AssetMaterialization(",
            "AssetCheckEvaluation(",
            "get_event_records",
            "asset_readiness_status",
            "partition_filter=",
        )
        required_helper_fragments = (
            "TARGET_TS_CODE = \"000638.SZ\"",
            "SILVER_STK_MINS_NAME_TIMELINE_COVERED_CHECK",
            "silver_stock_lifecycle_path",
            "silver_cny_stock_lifecycle_select",
            "get_asset_check_execution_history",
            "get_materialized_partitions",
            "planned_new_event_count=len(latest_failed)",
        )
        issues.extend(
            f"{helper_path} contains forbidden dry-run fragment: {fragment}"
            for fragment in forbidden_helper_fragments
            if fragment in helper_source
        )
        issues.extend(
            f"{helper_path} misses required dry-run fragment: {fragment}"
            for fragment in required_helper_fragments
            if fragment not in helper_source
        )
        if "\"dry-run\"" not in cli_source:
            issues.append(f"{cli_path} must expose only the dry-run command")
        if "\"apply\"" in cli_source or "report_runless_asset_event" in cli_source:
            issues.append(f"{cli_path} must not expose apply/write event behavior")

        self.assertEqual(issues, [])

    def test_stk_mins_event_history_retention_dry_run_is_scoped_and_read_only(
        self,
    ) -> None:
        helper_path = (
            DEFS_DIR / "bootstrap" / "stk_mins_event_history_retention.py"
        )
        cli_path = (
            DEFS_DIR / "bootstrap" / "stk_mins_event_history_retention_cli.py"
        )
        helper_source = helper_path.read_text()
        cli_source = cli_path.read_text()
        combined = f"{helper_source}\n{cli_source}".lower()
        issues = []

        forbidden_fragments = (
            "delete from",
            "insert into",
            "update event_logs",
            "update asset_check_executions",
            "vacuum (",
            "analyze event_logs",
            "report_runless_asset_event",
            "dagsterinstance.get",
            "--apply",
            "\"apply\"",
            "asset_key::text like",
        )
        required_helper_fragments = (
            "STK_MINS_RETENTION_KEEP_PARTITION_SET_NAME = "
            '"cn_a_stock_mins_trade_days"',
            "STK_MINS_RETENTION_KEEP_TRADE_DAY_COUNT = 20",
            "STK_MINS_RETENTION_ASSET_KEYS",
            "gold_stk_mins_qfq_factor_repair_plan_evaluated",
            "gold_stk_mins_qfq_macd_kdj_repair_completed_check",
            "candidate_checks_exclude_keep_window_partitions",
            "candidate_materializations_exclude_latest_materializations",
        )
        issues.extend(
            f"{helper_path} contains forbidden retention fragment: {fragment}"
            for fragment in forbidden_fragments
            if fragment in combined
        )
        issues.extend(
            f"{helper_path} misses required retention fragment: {fragment}"
            for fragment in required_helper_fragments
            if fragment not in helper_source
        )
        if "\"dry-run\"" not in cli_source:
            issues.append(f"{cli_path} must expose the dry-run command")

        self.assertEqual(issues, [])

    def test_stk_mins_event_history_retention_sample_delete_is_tightly_scoped(
        self,
    ) -> None:
        helper_path = (
            DEFS_DIR / "bootstrap" / "stk_mins_event_history_retention_sample_delete.py"
        )
        cli_path = (
            DEFS_DIR
            / "bootstrap"
            / "stk_mins_event_history_retention_sample_delete_cli.py"
        )
        helper_source = helper_path.read_text()
        cli_source = cli_path.read_text()
        combined = f"{helper_source}\n{cli_source}".lower()
        issues = []

        required_fragments = (
            "STK_MINS_RETENTION_DEFAULT_SAMPLE_DELETE_ASSET =",
            "gold_stk_mins_qfq_macd_kdj_state_120m",
            "--confirm-sample-delete",
            "sample-delete requires --confirm-sample-delete",
            "delete_check_event_tags",
            "delete_check_events",
            "delete_check_executions",
            "delete_materialization_event_tags",
            "delete_materialization_events",
            "connection.commit()",
            "rollback()",
        )
        forbidden_fragments = (
            "asset_key::text like",
            "truncate ",
            "drop table",
            "vacuum",
            "reindex",
            "pg_repack",
            "delete from runs",
            "delete from run_tags",
            "delete from dynamic_partitions",
            "report_runless_asset_event",
            "dagsterinstance.get",
        )
        issues.extend(
            f"{helper_path} misses sample-delete fragment: {fragment}"
            for fragment in required_fragments
            if fragment not in f"{helper_source}\n{cli_source}"
        )
        issues.extend(
            f"{helper_path} contains forbidden sample-delete fragment: {fragment}"
            for fragment in forbidden_fragments
            if fragment in combined
        )
        if "\"dry-run\"" in cli_source:
            issues.append(f"{cli_path} must not masquerade as a dry-run CLI")

        self.assertEqual(issues, [])

    def test_asset_check_incremental_governance_matrix_exists(self) -> None:
        path = Path("tests/test_asset_check_incremental_governance.py")
        source = path.read_text()
        issues = []

        required_fragments = (
            "ASSET_CHECK_GOVERNANCE",
            "PROTECTED_CHECK_GOVERNANCE",
            "KEEP_BLOCKING_DAGSTER",
            "MERGE_BLOCKING_DAGSTER",
            "MOVE_TO_SENSOR_LAKE_READINESS",
            "MOVE_TO_METADATA",
            "MOVE_TO_OFFLINE_AUDIT",
            "RETENTION_ONLY",
            "STK_MINS_RETENTION_PROTECTED_CHECK_NAMES",
            "gold_wealth_market_turnover",
            "test_all_catalog_blocking_checks_have_incremental_governance_rule",
            "test_sensor_readiness_checks_are_declared_in_governance_matrix",
            "test_checks_only_jobs_never_select_materializable_assets",
        )
        forbidden_fragments = (
            "delete from",
            "insert into",
            "update event_logs",
            "DagsterInstance.get",
            "get_event_records",
            "report_runless_asset_event",
            "asset_key::text like",
            "--apply",
        )
        issues.extend(
            f"{path} misses asset check governance fragment: {fragment}"
            for fragment in required_fragments
            if fragment not in source
        )
        lowered = source.lower()
        issues.extend(
            f"{path} contains forbidden governance fragment: {fragment}"
            for fragment in forbidden_fragments
            if fragment.lower() in lowered
        )

        self.assertEqual(issues, [])

    def test_asset_check_event_retention_dry_run_has_no_write_path(self) -> None:
        helper_path = Path(
            "src/orchestrator/defs/bootstrap/asset_check_event_retention.py"
        )
        cli_path = Path(
            "src/orchestrator/defs/bootstrap/asset_check_event_retention_cli.py"
        )
        test_path = Path("tests/test_asset_check_event_retention.py")
        helper_source = helper_path.read_text()
        cli_source = cli_path.read_text()
        test_source = test_path.read_text()
        combined = f"{helper_source}\n{cli_source}".lower()
        issues = []

        required_fragments = (
            "collect_asset_check_event_retention_dry_run",
            "ASSET_CHECK_RETENTION_KEEP_TRADE_DAY_COUNT",
            "ASSET_CHECK_RETENTION_PROTECTED_CHECK_NAMES",
            "ASSET_CHECK_RETENTION_ASSET_FAMILY_BY_KEY",
            "ASSET_CHECK_RETENTION_EXCLUDED_ASSETS",
            '"dry-run"',
            "set_session(readonly=True",
            "test_sql_statements_are_read_only",
            "test_module_and_cli_do_not_expose_write_or_delete_paths",
        )
        forbidden_fragments = (
            "delete from",
            "insert into",
            "update event_logs",
            "update asset_check_executions",
            "vacuum (",
            "analyze event_logs",
            "report_runless_asset_event",
            "dagsterinstance.get",
            "--apply",
            "--confirm",
        )
        source_bundle = f"{helper_source}\n{cli_source}\n{test_source}"
        issues.extend(
            f"asset check retention misses fragment: {fragment}"
            for fragment in required_fragments
            if fragment not in source_bundle
        )
        issues.extend(
            f"asset check retention exposes write fragment: {fragment}"
            for fragment in forbidden_fragments
            if fragment in combined
        )

        self.assertEqual(issues, [])

    def test_asset_check_event_retention_sample_delete_is_tightly_scoped(
        self,
    ) -> None:
        helper_path = Path(
            "src/orchestrator/defs/bootstrap/asset_check_event_retention_sample_delete.py"
        )
        cli_path = Path(
            "src/orchestrator/defs/bootstrap/asset_check_event_retention_sample_delete_cli.py"
        )
        helper_source = helper_path.read_text()
        cli_source = cli_path.read_text()
        combined = f"{helper_source}\n{cli_source}".lower()
        issues = []

        required_fragments = (
            "execute_asset_check_event_retention_sample_delete",
            "--sample-asset",
            "required=True",
            "--confirm-sample-delete",
            "sample-delete requires --confirm-sample-delete",
            "sample-delete requires exactly one sample asset",
            "requires a partitioned retention asset",
            "ASSET_CHECK_RETENTION_ASSET_KEYS",
            "ASSET_CHECK_RETENTION_KEEP_PARTITION_SET_BY_KEY",
            "delete_check_event_tags",
            "delete_check_events",
            "delete_check_executions",
            "delete_materialization_event_tags",
            "delete_materialization_events",
            "connection.commit()",
            "rollback()",
        )
        forbidden_fragments = (
            "asset_key::text like",
            "truncate ",
            "drop table",
            "vacuum",
            "reindex",
            "pg_repack",
            "delete from runs",
            "delete from run_tags",
            "delete from dynamic_partitions",
            "delete from instigators",
            "report_runless_asset_event",
            "dagsterinstance.get",
        )
        source_bundle = f"{helper_source}\n{cli_source}"
        issues.extend(
            f"asset check sample-delete misses fragment: {fragment}"
            for fragment in required_fragments
            if fragment not in source_bundle
        )
        issues.extend(
            f"asset check sample-delete contains forbidden fragment: {fragment}"
            for fragment in forbidden_fragments
            if fragment in combined
        )
        if "\"dry-run\"" in cli_source:
            issues.append(f"{cli_path} must not masquerade as a dry-run CLI")

        self.assertEqual(issues, [])

    def test_stk_nineturn_daily_slice_keeps_definition_boundaries(self) -> None:
        asset_source = Path(
            "src/orchestrator/defs/assets/stk_nineturn.py"
        ).read_text()
        checks_source = Path(
            "src/orchestrator/defs/checks/stk_nineturn_checks.py"
        ).read_text()
        job_source = Path(
            "src/orchestrator/defs/jobs/stk_nineturn_update.py"
        ).read_text()
        sensor_source = Path(
            "src/orchestrator/defs/sensors/stk_nineturn_sensor.py"
        ).read_text()
        readiness_source = Path(
            "src/orchestrator/defs/asset_guards/stk_nineturn_lake_readiness.py"
        ).read_text()
        issues = []

        required_asset_fragments = (
            'name="raw_tushare_stk_nineturn"',
            "partitions_def=cn_a_stock_trade_days",
            "fetch_tushare_partition_to_raw",
            'api_name="stk_nineturn"',
            '"freq": "daily"',
            "RAW_STK_NINETURN_COLUMNS",
            "RAW_STK_NINETURN_COLUMN_TYPES",
        )
        required_check_fragments = (
            "asset=raw_tushare_stk_nineturn",
            "partitions_def=cn_a_stock_trade_days",
            "raw_tushare_stk_nineturn_contract_check",
            "raw_tushare_stk_nineturn_content_integrity_check",
            "load_raw_stk_nineturn_metrics",
        )
        required_job_fragments = (
            'name="raw_stk_nineturn_update_job"',
            "AssetSelection.assets(raw_tushare_stk_nineturn)",
            "AssetSelection.checks_for_assets(raw_tushare_stk_nineturn)",
            'name="silver_stock_nineturn_daily_update_job"',
            "AssetSelection.assets(silver_stock_nineturn_daily)",
            "AssetSelection.checks_for_assets(silver_stock_nineturn_daily)",
        )
        required_silver_fragments = (
            'name="silver_stock_nineturn_daily"',
            "deps=[raw_tushare_stk_nineturn, silver_stock_identity_map]",
            "write_silver_stock_nineturn_daily_partition",
            "silver_stock_nineturn_daily_contract_check",
            "silver_stock_nineturn_daily_canonical_integrity_check",
            "additional_deps=[raw_tushare_stk_nineturn, silver_stock_identity_map]",
            "load_silver_stock_nineturn_daily_metrics",
        )
        issues.extend(
            f"stk_nineturn raw asset misses fragment: {fragment}"
            for fragment in required_asset_fragments
            if fragment not in asset_source
        )
        issues.extend(
            f"stk_nineturn raw checks miss fragment: {fragment}"
            for fragment in required_check_fragments
            if fragment not in checks_source
        )
        issues.extend(
            f"stk_nineturn raw job misses fragment: {fragment}"
            for fragment in required_job_fragments
            if fragment not in job_source
        )
        issues.extend(
            f"stk_nineturn Silver slice misses fragment: {fragment}"
            for fragment in required_silver_fragments
            if fragment not in f"{asset_source}\n{checks_source}"
        )
        silver_asset_offset = asset_source.index(
            '@dg.asset(\n    name="silver_stock_nineturn_daily"'
        )
        raw_asset_offset = asset_source.index("def raw_tushare_stk_nineturn(")
        raw_asset_source = asset_source[raw_asset_offset:silver_asset_offset]
        for forbidden in (
            "dg.RunRequest(",
            "silver_stock_identity_map",
            "bse_mapping",
        ):
            if forbidden in raw_asset_source:
                issues.append(f"stk_nineturn raw asset contains forbidden {forbidden}")
        if "bse_mapping" in asset_source:
            issues.append("stk_nineturn Silver asset must not build a local BSE mapping")
        if "silver_stock_daily" in asset_source:
            issues.append("stk_nineturn Silver asset must not depend on stock daily")
        required_sensor_fragments = (
            'job_name="raw_stk_nineturn_update_job"',
            'job_name="silver_stock_nineturn_daily_update_job"',
            "default_status=dg.DefaultSensorStatus.STOPPED",
            "minimum_interval_seconds=600",
            'required_resource_keys={"lake_root", "duckdb"}',
            "load_expected_trade_date_window",
            "build_registered_gap_status",
            "select_first_not_ready_trade_date",
            "batch_raw_stk_nineturn_lake_readiness",
            "batch_silver_stock_nineturn_daily_lake_readiness",
            'subject="raw_stk_nineturn_update"',
            'subject="silver_stock_nineturn_daily_update"',
            "build_run_request",
            "build_sensor_cursor",
        )
        required_readiness_fragments = (
            "load_raw_stk_nineturn_metrics",
            "load_silver_stock_nineturn_daily_metrics",
            "ContinuityBatchReadiness",
            "ContinuityDateReadiness",
            "full_semantics: bool = True",
        )
        issues.extend(
            f"stk_nineturn sensor misses fragment: {fragment}"
            for fragment in required_sensor_fragments
            if fragment not in sensor_source
        )
        issues.extend(
            f"stk_nineturn lake readiness misses fragment: {fragment}"
            for fragment in required_readiness_fragments
            if fragment not in readiness_source
        )
        for forbidden in (
            "dg.RunRequest(",
            "get_event_records(",
            "get_asset_check_execution_history(",
            "partition_dataset_readiness_status_from_latest_checks",
            "run_key.split",
        ):
            if forbidden in sensor_source or forbidden in readiness_source:
                issues.append(
                    f"stk_nineturn readiness/sensor contains forbidden {forbidden}"
                )
        for forbidden in ("TushareResource", "DuckDBResource", "read_parquet("):
            if forbidden in job_source:
                issues.append(f"stk_nineturn job contains forbidden {forbidden}")

        self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
