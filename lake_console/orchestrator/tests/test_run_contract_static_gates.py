import ast
import unittest
from pathlib import Path

from orchestrator.defs.run_contracts.sensor_tags import (
    SensorDomain,
    SensorRole,
    SensorTargetLayer,
)


DEFS_DIR = Path("src/orchestrator/defs")
ASSETS_DIR = DEFS_DIR / "assets"
CHECKS_DIR = DEFS_DIR / "checks"
JOBS_DIR = DEFS_DIR / "jobs"
SENSORS_DIR = DEFS_DIR / "sensors"

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
                    if call_name == "RunRequest":
                        issues.append(
                            f"{_node_location(path, node)} constructs RunRequest directly"
                        )
                    for keyword in node.keywords:
                        if keyword.arg == "run_tags":
                            issues.append(
                                f"{_node_location(path, node)} writes run_tags"
                            )
                        elif keyword.arg == "tags" and not (
                            _is_sensor_definition_call(node)
                            and _is_call_named(keyword.value, "build_sensor_tags")
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
                    if "ops" in _direct_string_keys(node):
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

        self.assertEqual(sensor_definition_count, 22)
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
                        if column_schema_value is None:
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


if __name__ == "__main__":
    unittest.main()
