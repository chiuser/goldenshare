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
    if (
        path.name == "index_daily_sensor.py"
        and isinstance(node, ast.Attribute)
        and node.attr == "run_key"
        and isinstance(node.value, ast.Name)
        and node.value.id == "run"
    ):
        return True
    return (
        isinstance(node, ast.Call)
        and _call_name(node.func) in RUN_KEY_BUILDER_CALL_NAMES
    )


class RunContractStaticGateTests(unittest.TestCase):
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

        sensor_source = sensor_path.read_text()
        required_sensor_fragments = (
            "run_status_sensor",
            "request_job=gold_stk_mins_qfq_macd_kdj_daily_update_job",
            "monitored_jobs=[stock_mins_qfq_daily_update_job, stock_mins_qfq_factor_repair_job]",
            "DEFAULT_LAKE_ROOT",
            "connect_configured_duckdb",
            "load_stock_mins_expected_trade_dates",
            "previous_expected_trade_date",
            "partition_dataset_readiness_status_from_latest_checks",
            "gold_stk_mins_qfq_factor_repair_status",
            "GOLD_STK_MINS_QFQ_READINESS_SPECS",
            "build_sensor_tags",
        )
        forbidden_sensor_fragments = (
            "get_asset_check_execution_history",
            "duckdb.connect",
            "read_parquet",
            "cn_a_stock_mins_silver_trade_days",
            "_previous_registered_trade_date",
            "gold_stk_mins_qfq_macd_kdj_path",
            "PENDING_QFQ_FACTOR_REPAIR_TAG",
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
            "STK_MINS_MACD_KDJ_BASELINE_START_DATE",
            "silver_trade_calendar_path",
        )
        issues.extend(
            f"{asset_path} misses MACD/KDJ daily continuity fragment: {fragment}"
            for fragment in required_asset_fragments
            if fragment not in asset_source
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
            "assert_exact_previous_state_path",
            "source_paths_by_freq",
            "previous_state_path_by_freq",
            "qfq_factor_repair_trade_date",
            "upstream_batch_id",
            "gold_stk_mins_qfq_factor_repair_status",
            "_repair_scope_from_qfq_factor_repair_status",
            "dg.AssetCheckEvaluation",
            "blocking=True",
            "partition=start_trade_date",
            "repair_required_codes_hash",
            "source_upstream_batch_id",
            '"stock_code_scope": "explicit"',
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
        )
        issues.extend(
            f"{repair_op_path} contains forbidden MACD/KDJ repair op fragment: {fragment}"
            for fragment in forbidden_repair_op_fragments
            if fragment in repair_op_source
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
        )
        forbidden_fragments = (
            "raw_stk_mins_ready_for_trade_date",
            "dg.RunRequest(",
            "RunRequest(",
            "run_key=f",
            "run_key=(",
            ".split(",
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
        job_path = JOBS_DIR / "lake_root_health_check.py"
        schedule_path = SCHEDULES_DIR / "lake_root_health.py"
        resource_path = DEFS_DIR / "resources.py"
        job_source = job_path.read_text()
        schedule_source = schedule_path.read_text()
        resource_source = resource_path.read_text()
        issues = []

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
                                == "gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor.py"
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

        self.assertEqual(sensor_definition_count, 33)
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
            ),
            SENSORS_DIR / "stock_mins_qfq_factor_repair_sensor.py": (
                "gold_stk_mins_qfq_ready_for_trade_date",
                "get_asset_check_execution_history",
                "partition_dataset_readiness_status_from_latest_checks",
                "GOLD_STK_MINS_QFQ_READINESS_SPECS",
                "get_event_records",
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
            SENSORS_DIR / "index_daily_sensor.py",
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


if __name__ == "__main__":
    unittest.main()
