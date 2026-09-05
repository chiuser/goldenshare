"""Frozen operator-facing CLI contracts; all external capabilities are replaced."""

import argparse
import ast
import dataclasses
import importlib
import io
import json
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import create_autospec, patch

import dagster as dg
import pytest

PREFIX = "orchestrator.defs.bootstrap."
FIXTURE = Path(__file__).with_name("fixtures") / "stk_mins_history_cli_contract_v1.json"
COMMAND_GROUPS = {
    "stk_mins_silver_history_cli": (
        ("plan-silver", "plan_stk_mins_silver_history", "READ_ONLY"),
        ("generate-silver", "generate_stk_mins_silver_history", "LAKE_WRITE"),
        (
            "register-silver-partitions",
            "register_stock_mins_silver_partitions",
            "DAGSTER_WRITE",
        ),
        (
            "report-silver-events",
            "report_stk_mins_silver_bootstrap_events",
            "DAGSTER_WRITE",
        ),
        ("audit-silver-final", "audit_stk_mins_silver_final_state", "READ_ONLY"),
    ),
    "stk_mins_qfq_history_cli": (
        ("plan-gold-qfq-history", "plan_stk_mins_qfq_history", "READ_ONLY"),
        ("generate-gold-qfq-history", "generate_stk_mins_qfq_history", "LAKE_WRITE"),
        ("plan-gold-qfq-events", "plan_stk_mins_qfq_bootstrap_events", "READ_ONLY"),
        (
            "report-gold-qfq-events",
            "report_stk_mins_qfq_bootstrap_events",
            "DAGSTER_WRITE",
        ),
        ("audit-gold-qfq-final", "audit_stk_mins_qfq_final_state", "READ_ONLY"),
    ),
    "stk_mins_qfq_derived_history_cli": (
        (
            "plan-gold-qfq-derived-history",
            "plan_stk_mins_qfq_derived_history",
            "READ_ONLY",
        ),
        (
            "generate-gold-qfq-derived-history",
            "generate_stk_mins_qfq_derived_history",
            "LAKE_WRITE",
        ),
        (
            "plan-gold-qfq-derived-events",
            "plan_stk_mins_qfq_derived_bootstrap_events",
            "READ_ONLY",
        ),
        (
            "report-gold-qfq-derived-events",
            "report_stk_mins_qfq_derived_bootstrap_events",
            "DAGSTER_WRITE",
        ),
        (
            "audit-gold-qfq-derived-final",
            "audit_stk_mins_qfq_derived_final_state",
            "READ_ONLY",
        ),
    ),
    "stk_mins_qfq_macd_kdj_history_cli": (
        (
            "plan-gold-stk-mins-qfq-macd-kdj-history",
            "plan_stk_mins_qfq_macd_kdj_history",
            "READ_ONLY",
        ),
        (
            "generate-gold-stk-mins-qfq-macd-kdj-history",
            "generate_stk_mins_qfq_macd_kdj_history",
            "LAKE_WRITE",
        ),
        (
            "rebuild-gold-stk-mins-qfq-macd-kdj-history",
            "rebuild_stk_mins_qfq_macd_kdj_history",
            "LAKE_WRITE",
        ),
        (
            "audit-gold-stk-mins-qfq-macd-kdj-files",
            "audit_stk_mins_qfq_macd_kdj_files",
            "READ_ONLY",
        ),
        (
            "report-gold-stk-mins-qfq-macd-kdj-baseline-events",
            "report_stk_mins_qfq_macd_kdj_baseline_events",
            "DAGSTER_WRITE",
        ),
        (
            "audit-gold-stk-mins-qfq-macd-kdj-final",
            "audit_stk_mins_qfq_macd_kdj_final_state",
            "READ_ONLY",
        ),
    ),
}
SPECS = {
    command: {"cli": module, "target": target, "side_effect": effect}
    for module, commands in COMMAND_GROUPS.items()
    for command, target, effect in commands
}
RETIRED_COMMANDS = (
    "dry-run",
    "migrate-raw",
    "migrate-identity-map",
    "register-partitions",
    "report-raw-events",
    "report-identity-map-events",
    "audit-final",
)
_TARGET_NAMES = {spec["target"] for spec in SPECS.values()}


@dataclasses.dataclass(frozen=True)
class Capability:
    name: str


def normalize(value):
    if isinstance(value, Path):
        return {"type": "Path", "value": str(value)}
    if isinstance(value, Capability):
        return {"type": "capability", "name": value.name}
    if dataclasses.is_dataclass(value):
        return {
            "type": type(value).__name__,
            "fields": normalize(dataclasses.asdict(value)),
        }
    if isinstance(value, tuple):
        return {"type": "tuple", "items": [normalize(item) for item in value]}
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): normalize(item) for key, item in value.items()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise AssertionError(f"Unexpected contract value: {type(value).__name__}")


class _ParserCaptured(Exception):
    def __init__(self, parser):
        self.parser = parser


def cli_parser(module):
    def capture(parser, *_args, **_kwargs):
        raise _ParserCaptured(parser)

    with patch.object(argparse.ArgumentParser, "parse_args", capture):
        try:
            module.main([])
        except _ParserCaptured as captured:
            return captured.parser
    raise AssertionError("CLI did not parse its arguments")


def command_parsers(module):
    parser = cli_parser(module)
    return next(
        action.choices
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )


def parser_contract(parser):
    return [
        {
            "options": action.option_strings,
            "dest": action.dest,
            "action": type(action).__name__,
            "type": getattr(action.type, "__name__", None),
            "default": normalize(action.default),
            "required": action.required,
            "choices": list(action.choices) if action.choices is not None else None,
            "nargs": action.nargs,
        }
        for action in parser._actions
        if action.dest != "help"
    ]


def sentinel_report(target, kwargs):
    """Distinct literal values make dropped/renamed/swapped output fields visible."""
    counts = (
        "planned_write_count",
        "planned_event_count",
        "missing_input_count",
        "failed_partition_count",
        "reported_event_count",
        "planned_target_file_count",
        "existing_target_file_count",
        "written_file_count",
        "written_row_count",
        "asset_partition_count",
        "selected_partition_count",
        "planned_source_file_count",
        "planned_source_row_count",
        "planned_source_stock_day_count",
        "planned_target_row_count",
        "planned_indicator_file_count",
        "existing_indicator_file_count",
        "planned_state_file_count",
        "existing_state_file_count",
        "source_row_count",
        "indicator_row_count",
        "state_row_count",
        "row_count_mismatch_count",
        "failed_asset_partition_count",
        "resumed_batch_count",
        "executed_batch_count",
    )
    fields = {name: index + 11 for index, name in enumerate(counts)}
    fields.update(
        selected_partition_keys=("2026-09-02", "2026-09-04"),
        selected_freqs=(5, 15),
        selected_target_freqs=(90, 120),
        selected_years=(2025, 2026),
        raw_partition_counts={1: 13, 5: 17},
        existing_silver_partition_counts={1: 3, 5: 7},
        missing_input_samples=("missing-a", "missing-b"),
        sample_partition_keys=("2026-09-04",),
        batches=("batch-a", "batch-b"),
        batch_results=("batch-result",),
        written_asset_partitions=((5, "2026-09-04"),),
        skipped_existing_asset_partitions=(),
        reported_asset_partitions=((5, "2026-09-02"), (15, "2026-09-04")),
        skipped_materialized_asset_partitions=((5, "2026-09-04"),),
        skipped_ready_asset_partitions=(),
        partition_audits=("audit-a", "audit-b"),
        asset_audits=("asset-audit",),
        requested_partition_keys=("2026-09-02", "2026-09-04"),
        existing_partition_keys=("2026-09-02",),
        registered_partition_keys=("2026-09-04",),
        target_file_counts_by_batch={(5, 2026): 29},
        estimates_by_batch={(90, 2026): SimpleNamespace(planned_target_file_count=31)},
        materialized_partition_counts={5: 37},
        check_success_counts={"check-a": 41},
        sample_readiness={"sample-a": True, "sample-b": False},
        check_success_counts_skipped=not kwargs.get(
            "include_check_success_counts", True
        ),
        passed=False,
        file_audit_passed=True,
        dry_run=kwargs.get("dry_run", False),
        plan_fingerprint="frozen-plan",
        checkpoint_path=Path("/contract/checkpoint.json"),
        stock_codes=("600000.SH", "000001.SZ"),
    )
    if target == "audit_stk_mins_silver_final_state":
        from orchestrator.defs.bootstrap.stk_mins_silver_bootstrap_events import (
            StkMinsSilverFinalAuditReport,
        )

        return StkMinsSilverFinalAuditReport(
            2, {1: 13}, 3, {1: 7}, {"check-a": 11}, {"sample-a": True}
        )
    return SimpleNamespace(**fields, plan=SimpleNamespace(**fields))


def capture_run(module, argv, *, fail_target=False):
    calls, namespace, printed = [], {}, []
    stdout, stderr = io.StringIO(), io.StringIO()
    result, failure = None, None
    instance, resource = Capability("DagsterInstance"), Capability("DuckDBResource")
    original_parse, original_print = argparse.ArgumentParser.parse_args, print

    def parse(parser, *args, **kwargs):
        parsed = original_parse(parser, *args, **kwargs)
        namespace.update(vars(parsed))
        return parsed

    def get_instance():
        calls.append({"target": "DagsterInstance.get"})
        return instance_proxy

    def get_partitions(name):
        calls.append({"target": "DagsterInstance.get_dynamic_partitions", "name": name})
        return ["2026-09-04", "2026-09-02", "2026-09-03"]

    class InstanceProxy(Capability):
        def get_dynamic_partitions(self, name):
            return get_partitions(name)

    instance_proxy = InstanceProxy(instance.name)

    def get_resource():
        calls.append({"target": "DuckDBResource"})
        return resource

    def target_fake(name, qualified_name):
        def invoke(*args, **kwargs):
            calls.append(
                {
                    "target": qualified_name,
                    "args": normalize(args),
                    "kwargs": normalize(kwargs),
                }
            )
            if fail_target and name in _TARGET_NAMES:
                raise RuntimeError("injected target failure")
            if name in (
                "all_raw_stk_mins_partition_keys",
                "all_silver_partition_keys",
            ):
                return ("2013-12-31", "2026-09-02", "2026-09-04")
            return sentinel_report(name, kwargs)

        return invoke

    def record_print(*args, **kwargs):
        printed.append({"args": normalize(args), "kwargs": normalize(kwargs)})
        return original_print(*args, **kwargs)

    with ExitStack() as stack:
        stack.enter_context(redirect_stdout(stdout))
        stack.enter_context(redirect_stderr(stderr))
        stack.enter_context(patch.object(argparse.ArgumentParser, "parse_args", parse))
        stack.enter_context(patch("builtins.print", record_print))
        stack.enter_context(patch.object(dg.DagsterInstance, "get", get_instance))
        if hasattr(module, "DuckDBResource"):
            stack.enter_context(patch.object(module, "DuckDBResource", get_resource))
        for name in (
            *_TARGET_NAMES,
            "all_raw_stk_mins_partition_keys",
            "all_silver_partition_keys",
        ):
            if not hasattr(module, name):
                continue
            function = getattr(module, name)
            qualified = f"{function.__module__}.{function.__name__}"
            stack.enter_context(
                patch.object(
                    module,
                    name,
                    create_autospec(function, side_effect=target_fake(name, qualified)),
                )
            )
        # A missed fake must fail rather than opening any Lake, database or network.
        for method in (
            "glob",
            "rglob",
            "read_text",
            "read_bytes",
            "open",
            "write_text",
            "write_bytes",
            "mkdir",
            "unlink",
            "rename",
            "replace",
        ):
            stack.enter_context(
                patch.object(
                    Path, method, side_effect=AssertionError("unexpected file access")
                )
            )
        stack.enter_context(
            patch("builtins.open", side_effect=AssertionError("unexpected file access"))
        )
        stack.enter_context(
            patch("os.replace", side_effect=AssertionError("unexpected file promotion"))
        )
        stack.enter_context(
            patch(
                "socket.socket.connect",
                side_effect=AssertionError("unexpected network"),
            )
        )
        try:
            result = module.main(argv)
        except (ValueError, RuntimeError, SystemExit) as exc:
            failure = {"type": type(exc).__name__, "message": str(exc)}
    return {
        "namespace": namespace,
        "calls": calls,
        "printed": printed,
        "stdout": stdout.getvalue(),
        "failure": failure,
        "return": normalize(result),
        # The executable name and available subcommand list intentionally change.
        "argument_error": stderr.getvalue().split("error: ")[-1].strip()
        if "error: " in stderr.getvalue()
        else "",
    }


@pytest.fixture(scope="module")
def contract():
    return json.loads(FIXTURE.read_text())


@pytest.mark.parametrize("command", tuple(SPECS))
def test_current_command_matches_frozen_contract(command, contract, subtests):
    spec = SPECS[command]
    module = importlib.import_module(PREFIX + spec["cli"])
    frozen = contract["commands"][command]
    assert frozen["identity"] == spec
    assert parser_contract(command_parsers(module)[command]) == frozen["parser"]
    assert (
        f"{getattr(module, spec['target']).__module__}.{spec['target']}"
        == frozen["target_qualified_name"]
    )
    for case in frozen["cases"]:
        with subtests.test(case=case["name"]):
            actual = capture_run(
                module, case["argv"], fail_target=case.get("fail_target", False)
            )
            assert actual == case["expected"]


def test_frozen_inventory_is_complete(contract):
    assert contract["baseline_commit"] == "3007cc0e"
    assert contract["command_count"] == len(SPECS) == 21
    assert set(contract["commands"]) == set(SPECS)
    assert tuple(contract["retired_commands"]) == RETIRED_COMMANDS
    assert (
        sum(len(command["cases"]) for command in contract["commands"].values()) == 246
    )
    for command in contract["commands"].values():
        assert any(case["expected"]["failure"] is None for case in command["cases"])
        assert command["effective_side_effect_with_dry_run"] == (
            "READ_ONLY"
            if any("--dry-run" in action["options"] for action in command["parser"])
            else None
        )


@pytest.mark.parametrize("module_name", tuple(COMMAND_GROUPS))
def test_each_cli_exposes_only_its_own_current_commands(module_name):
    module = importlib.import_module(PREFIX + module_name)
    assert tuple(command_parsers(module)) == tuple(
        command for command, *_ in COMMAND_GROUPS[module_name]
    )


def test_old_dispatcher_is_absent():
    current = importlib.import_module(PREFIX + "stk_mins_silver_history_cli")
    assert not Path(current.__file__).with_name("stk_mins_migration_cli.py").exists()


@pytest.mark.parametrize(
    "module_name", (*COMMAND_GROUPS, "stk_mins_history_cli_contract")
)
def test_current_cli_has_no_direct_legacy_dependency(module_name):
    current = importlib.import_module(PREFIX + module_name)
    tree = ast.parse(Path(current.__file__).read_text())
    imports = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    assert PREFIX + "stk_mins_migration" not in imports
    assert PREFIX + "specs.stk_mins" not in imports
    assert PREFIX + "specs.stock_identity_map" not in imports
    assert not any(module and "lake_console.backend" in module for module in imports)


@pytest.mark.parametrize("module_name", tuple(COMMAND_GROUPS))
@pytest.mark.parametrize("command", RETIRED_COMMANDS)
def test_retired_commands_are_rejected_before_capabilities(module_name, command):
    result = capture_run(importlib.import_module(PREFIX + module_name), [command])
    assert result["failure"] == {"type": "SystemExit", "message": "2"}
    assert result["calls"] == []
    assert result["printed"] == []


def test_shared_parsing_keeps_empty_duplicate_and_order_semantics():
    shared = importlib.import_module(PREFIX + "stk_mins_history_cli_contract")
    assert shared.parse_optional_partition_keys(None) is None
    assert shared.parse_optional_partition_keys("") is None
    assert shared.parse_optional_partition_keys(" , ") == ()
    assert shared.parse_optional_partition_keys(" b, a, b, ") == ("a", "b", "b")
    assert shared.parse_optional_csv_values(None) is None
    assert shared.parse_optional_csv_values("") is None
    assert shared.parse_optional_csv_values(" , ") == ()
    assert shared.parse_optional_csv_values(" 15, 5,15, ") == ("15", "5", "15")


def test_shared_instance_injection_does_not_open_another_instance():
    shared = importlib.import_module(PREFIX + "stk_mins_history_cli_contract")
    supplied = SimpleNamespace(
        get_dynamic_partitions=lambda name: ["2026-09-04", "2026-09-02"]
    )
    with patch.object(
        dg.DagsterInstance,
        "get",
        side_effect=AssertionError("must use supplied instance"),
    ):
        assert shared.registered_stk_mins_silver_partition_keys(supplied) == (
            "2026-09-02",
            "2026-09-04",
        )
