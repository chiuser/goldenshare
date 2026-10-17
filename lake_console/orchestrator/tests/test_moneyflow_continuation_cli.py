"""No arbitrary destinations, force switches, source override or partial selectors."""

import ast
from pathlib import Path

import pytest
from dagster_graphql.schema import create_schema
from graphql import parse, validate

from orchestrator.moneyflow_continuation.contract import ContinuationError, file_hash
from orchestrator.moneyflow_continuation.plan import LAUNCH, REGISTER
from orchestrator.moneyflow_continuation.submission import (
    new_plan_output,
    verify_plan_file,
)
from orchestrator.moneyflow_continuation_cli import parser
from tests.test_moneyflow_continuation_plan import plan_for


@pytest.mark.parametrize(
    "option",
    ["--force", "--retry-failed", "--url", "--lake-root", "--job", "--enable-sensor"],
)
def test_dangerous_options_do_not_exist(option):
    with pytest.raises(SystemExit) as result:
        parser().parse_args(
            ["apply", "--plan", "p", "--expect-plan-sha256", "h", option, "x"]
        )
    assert result.value.code == 2


def test_input_matches_installed_graphql_schema():
    schema = create_schema().graphql_schema
    for query in (REGISTER, LAUNCH):
        assert validate(schema, parse(query)) == []


def test_plan_output_new_file_only_and_digest(tmp_path):
    import tempfile

    with tempfile.TemporaryDirectory(dir="/private/tmp") as directory:
        path = Path(directory) / "plan.json"
        new_plan_output(path, plan_for())
        assert verify_plan_file(path, file_hash(path))["mode"] == "plan"
        with pytest.raises(ContinuationError, match="output_exists"):
            new_plan_output(path, plan_for())
        with pytest.raises(ContinuationError, match="plan_sha256"):
            verify_plan_file(path, "wrong")
    with pytest.raises(ContinuationError, match="output_location"):
        new_plan_output(tmp_path / "forbidden.json", plan_for())


def test_source_contains_no_alternate_native_write_paths():
    from orchestrator.moneyflow_continuation import execution

    directory = Path(execution.__file__).parent
    forbidden = {
        "terminate_run",
        "report_runless_asset_event",
        "add_dynamic_partitions",
        "set_concurrency_slots",
        "start_sensor",
        "stop_sensor",
        "reload_repository_location",
    }
    for path in directory.glob("*.py"):
        tree = ast.parse(path.read_text())
        calls = {
            n.func.attr
            for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        }
        assert not calls & forbidden
