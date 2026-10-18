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


def test_retired_audit_is_rejected_before_opening_instance(monkeypatch):
    from orchestrator.defs.bootstrap import daily_basic_event_instance as native
    from orchestrator.moneyflow_continuation_cli import main

    def forbidden(*args, **kwargs):
        pytest.fail("retired command opened the instance")

    monkeypatch.setattr(native, "daily_basic_event_instance", forbidden)
    with pytest.raises(SystemExit) as result:
        main(["audit", "--plan", "unused", "--expect-plan-sha256", "unused", "--output", "unused"])
    assert result.value.code == 2
    choices = next(a.choices for a in parser()._actions if a.dest == "mode")
    assert set(choices) == {"plan", "inspect", "apply"}


def test_retired_scope_is_rejected_before_backend_or_output(tmp_path):
    import json
    from types import SimpleNamespace

    from orchestrator.moneyflow_continuation_cli import run

    class UnusedBackend:
        def __getattr__(self, name):
            pytest.fail("backend reached for retired input: " + name)

    path = tmp_path / "scope.json"
    path.write_text(json.dumps({"units": [], "verification": {}, "collection_recovery": None}))
    output = tmp_path / "unused.json"
    args = SimpleNamespace(mode="plan", scope_file=str(path), output=str(output), parent_plan=None)
    with pytest.raises(ContinuationError, match="scope_fields"):
        run(args, UnusedBackend())
    assert not output.exists()


@pytest.mark.parametrize("mode", ["inspect", "apply"])
def test_old_plan_cannot_reach_backend(tmp_path, mode):
    import json
    from types import SimpleNamespace

    from orchestrator.moneyflow_continuation_cli import run

    class UnusedBackend:
        def __getattr__(self, name):
            pytest.fail("backend reached for old plan: " + name)

    path = tmp_path / "old.json"
    old = plan_for()
    old["format"] = 1
    path.write_text(json.dumps(old))
    args = SimpleNamespace(mode=mode, plan=str(path), expect_plan_sha256=file_hash(path))
    with pytest.raises(ContinuationError, match="plan_format"):
        run(args, UnusedBackend())


def test_apply_still_requires_exact_digest_argument():
    with pytest.raises(SystemExit) as result:
        parser().parse_args(["apply", "--plan", "unused"])
    assert result.value.code == 2
