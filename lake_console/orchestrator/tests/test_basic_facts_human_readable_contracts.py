import ast
import unittest
from pathlib import Path

from orchestrator.defs.assets.calendar import (
    raw_tushare_trade_calendar,
    silver_trade_calendar,
)
from orchestrator.defs.assets.index_basic import (
    raw_tushare_index_basic,
    silver_index_basic,
)
from orchestrator.defs.assets.namechange import (
    raw_tushare_namechange,
    silver_namechange,
)
from orchestrator.defs.assets.stock_basic import (
    raw_tushare_stock_basic,
    silver_stock_basic,
)
from orchestrator.defs.assets.stock_identity_map import silver_stock_identity_map
from orchestrator.defs.assets.stock_lifecycle import silver_stock_lifecycle
from orchestrator.defs.jobs.calendar_update import calendar_update_job
from orchestrator.defs.jobs.index_basic_update import index_basic_update_job
from orchestrator.defs.jobs.namechange_update import (
    raw_namechange_update_job,
    silver_namechange_update_job,
)
from orchestrator.defs.jobs.stock_basic_update import (
    raw_stock_basic_update_job,
    silver_stock_basic_update_job,
)
from orchestrator.defs.jobs.stock_identity_map_update import (
    stock_identity_map_update_job,
)
from orchestrator.defs.sensors.stock_basic_sensor import (
    raw_stock_basic_update_job_sensor,
    silver_stock_basic_update_job_sensor,
)
from orchestrator.defs.sensors.stock_identity_map_sensor import (
    stock_identity_map_sensor,
)
from orchestrator.defs.sensors.stock_namechange_sensor import (
    raw_namechange_update_job_sensor,
    silver_namechange_update_job_sensor,
)


ASSET_FILES = (
    Path("src/orchestrator/defs/assets/calendar.py"),
    Path("src/orchestrator/defs/assets/stock_basic.py"),
    Path("src/orchestrator/defs/assets/stock_lifecycle.py"),
    Path("src/orchestrator/defs/assets/namechange.py"),
    Path("src/orchestrator/defs/assets/stock_identity_map.py"),
    Path("src/orchestrator/defs/assets/index_basic.py"),
)
CHECK_FILES = (
    Path("src/orchestrator/defs/checks/calendar_checks.py"),
    Path("src/orchestrator/defs/checks/stock_basic_checks.py"),
    Path("src/orchestrator/defs/checks/stock_lifecycle_checks.py"),
    Path("src/orchestrator/defs/checks/namechange_checks.py"),
    Path("src/orchestrator/defs/checks/stock_identity_map_checks.py"),
    Path("src/orchestrator/defs/checks/index_basic_checks.py"),
)


def _asset_description(asset_definition) -> str:  # noqa: ANN001
    descriptions = tuple(asset_definition.descriptions_by_key.values())
    return descriptions[0] if descriptions else ""


def _stdout_events(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    events: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "stdout":
            continue
        if (
            node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            events.add(node.args[0].value)
    return events


class BasicFactsHumanReadableContractTests(unittest.TestCase):
    def test_asset_job_and_sensor_descriptions_are_human_readable(self) -> None:
        descriptions = (
            _asset_description(raw_tushare_trade_calendar),
            _asset_description(silver_trade_calendar),
            _asset_description(raw_tushare_stock_basic),
            _asset_description(silver_stock_basic),
            _asset_description(silver_stock_lifecycle),
            _asset_description(raw_tushare_namechange),
            _asset_description(silver_namechange),
            _asset_description(silver_stock_identity_map),
            _asset_description(raw_tushare_index_basic),
            _asset_description(silver_index_basic),
            calendar_update_job.description or "",
            raw_stock_basic_update_job.description or "",
            silver_stock_basic_update_job.description or "",
            raw_namechange_update_job.description or "",
            silver_namechange_update_job.description or "",
            stock_identity_map_update_job.description or "",
            index_basic_update_job.description or "",
            raw_stock_basic_update_job_sensor.description or "",
            silver_stock_basic_update_job_sensor.description or "",
            raw_namechange_update_job_sensor.description or "",
            silver_namechange_update_job_sensor.description or "",
            stock_identity_map_sensor.description or "",
        )

        for description in descriptions:
            with self.subTest(description=description):
                self.assertRegex(description, r"[\u4e00-\u9fff]")
                self.assertNotIn("selection", description.lower())
                self.assertNotIn("implementation", description.lower())

        self.assertIn("源镜像", _asset_description(raw_tushare_stock_basic))
        self.assertIn("标准事实", _asset_description(silver_stock_basic))
        self.assertIn("生命周期", _asset_description(silver_stock_lifecycle))
        self.assertIn("身份映射", _asset_description(silver_stock_identity_map))

    def test_basic_facts_stdout_events_are_named_and_small(self) -> None:
        expected_by_file = {
            "calendar.py": {
                "trade_calendar_raw_started",
                "trade_calendar_raw_completed",
                "trade_calendar_silver_started",
                "trade_calendar_silver_completed",
            },
            "stock_basic.py": {
                "stock_basic_raw_started",
                "stock_basic_raw_completed",
                "stock_basic_silver_started",
                "stock_basic_silver_completed",
            },
            "stock_lifecycle.py": {
                "stock_lifecycle_started",
                "stock_lifecycle_completed",
            },
            "namechange.py": {
                "namechange_raw_started",
                "namechange_raw_completed",
                "namechange_silver_started",
                "namechange_silver_validation_failed",
                "namechange_silver_completed",
            },
            "stock_identity_map.py": {
                "stock_identity_map_started",
                "stock_identity_map_validation_failed",
                "stock_identity_map_completed",
            },
            "index_basic.py": {
                "index_basic_raw_started",
                "index_basic_raw_completed",
                "index_basic_silver_started",
                "index_basic_silver_completed",
            },
        }
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

        for path in ASSET_FILES:
            with self.subTest(path=path):
                self.assertEqual(expected_by_file[path.name] - _stdout_events(path), set())
                tree = ast.parse(path.read_text(), filename=str(path))
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    if not isinstance(node.func, ast.Attribute) or node.func.attr != "stdout":
                        continue
                    keyword_names = {keyword.arg for keyword in node.keywords if keyword.arg}
                    self.assertEqual(keyword_names & forbidden_stdout_fields, set())

    def test_materialization_metadata_contains_operator_fields(self) -> None:
        required_fragments = (
            '"summary"',
            '"next_action"',
            '"result_status"',
            '"input_summary"',
            '"filter_summary"',
            '"diagnostic_ref"',
        )
        for path in ASSET_FILES:
            source = path.read_text()
            with self.subTest(path=path):
                for fragment in required_fragments:
                    self.assertIn(fragment, source)

    def test_check_metadata_contains_human_readable_fields(self) -> None:
        required_fragments = (
            '"summary"',
            '"next_action"',
            '"rule_summary"',
            '"failed_rule_names"',
        )
        for path in CHECK_FILES:
            source = path.read_text()
            with self.subTest(path=path):
                for fragment in required_fragments:
                    self.assertIn(fragment, source)


if __name__ == "__main__":
    unittest.main()
