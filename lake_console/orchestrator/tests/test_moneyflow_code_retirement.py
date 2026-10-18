"""Retired operation code cannot reenter maintained imports or mutation actions."""

import ast
import builtins
import os
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestrator.moneyflow_continuation import recovery
from orchestrator.moneyflow_continuation.contract import ContinuationError
from orchestrator.moneyflow_continuation.submission import Journal, submit_once
from tests.test_moneyflow_continuation_plan import AT, plan_for

PROJECT = Path(__file__).resolve().parents[1]
BOOTSTRAP = "orchestrator.defs.bootstrap."
RETIRED_MODULES = {
    BOOTSTRAP + name for name in (
        "moneyflow_history_supplement", "moneyflow_history_supplement_code",
        "moneyflow_history_supplement_control", "moneyflow_history_supplement_events",
        "moneyflow_history_supplement_files", "moneyflow_history_supplement_sensors",
    )
} | {"orchestrator.moneyflow_continuation.acceptance"}
RETIRED_TESTS = {
    "tests.test_moneyflow_history_supplement", "tests.test_moneyflow_history_supplement_code",
    "tests.test_moneyflow_collection_recovery", "tests.test_moneyflow_continuation_acceptance",
}
RETIRED_SYMBOLS = {
    "RAW_ACTION", "validate_collection_descriptor", "collection_evidence_path",
    "collection_evidence", "validate_collection_failure", "validate_collection_candidate",
}


def forbidden_references(source, *, recovery_source=False):
    found = set()
    for node in ast.walk(ast.parse(source)):
        modules = set()
        if isinstance(node, ast.Import):
            modules.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
            modules.update((node.module or "") + "." + a.name for a in node.names)
        elif isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if (
                name in {"__import__", "import_module"}
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                modules.add(node.args[0].value)
        found.update(modules & (RETIRED_MODULES | RETIRED_TESTS))
        if recovery_source:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in RETIRED_SYMBOLS:
                found.add(node.name)
            if isinstance(node, ast.Name) and node.id in RETIRED_SYMBOLS:
                found.add(node.id)
            if isinstance(node, ast.Attribute) and node.attr in RETIRED_SYMBOLS:
                found.add(node.attr)
    return found


def test_deleted_files_and_all_current_imports():
    for name in RETIRED_MODULES:
        assert not (PROJECT / "src" / (name.replace(".", "/") + ".py")).exists()
    for name in RETIRED_TESTS:
        assert not (PROJECT / (name.replace(".", "/") + ".py")).exists()
    for base in (PROJECT / "src", PROJECT / "tests"):
        for path in base.rglob("*.py"):
            assert not forbidden_references(
                path.read_text(), recovery_source="moneyflow_continuation" in path.parts
            ), path
    assert recovery.RECOVERY_ACTIONS == frozenset({"silver_reexecution"})


@pytest.mark.parametrize("source", [
    "from orchestrator.defs.bootstrap import moneyflow_history_supplement",
    "import orchestrator.moneyflow_continuation.acceptance",
    "from tests.test_moneyflow_collection_recovery import setup",
    "__import__('orchestrator.moneyflow_continuation.acceptance')",
    "importlib.import_module('orchestrator.moneyflow_continuation.acceptance')",
    "RAW_ACTION = 'raw_reexecution'",
    "def validate_collection_candidate(): pass",
])
def test_static_check_detects_reintroduction(source):
    assert forbidden_references(source, recovery_source=True)


@pytest.mark.parametrize("operation", ["read", "prepare", "submit"])
def test_retired_raw_action_rejected_without_backend_or_journal_writes(tmp_path, operation):
    plan = plan_for()
    unit = plan["units"][0]
    journal = Journal(plan, tmp_path / "control")

    class ForbiddenBackend:
        def __getattr__(self, name):
            pytest.fail("retired action reached backend: " + name)

    with pytest.raises(ContinuationError, match="journal_scope"):
        if operation == "read":
            journal.read(unit, "raw_reexecution")
        elif operation == "prepare":
            journal.prepare(unit, "raw_reexecution", AT, None, {})
        else:
            submit_once(ForbiddenBackend(), journal, unit, "raw_reexecution", AT)
    assert not journal.root.exists()


def test_raw_recovery_cannot_be_called_below_cli(tmp_path):
    plan = plan_for()
    unit = plan["units"][0]
    value = {"dataset": unit["dataset"], "trade_date": unit["trade_date"], "layer": "raw"}
    with pytest.raises(ContinuationError, match="recovery_scope"):
        recovery.request(value, unit, None)
    with pytest.raises(ContinuationError, match="recovery_scope"):
        recovery.effective_runs(SimpleNamespace(), Journal(plan, tmp_path), unit, [], "raw")
    with pytest.raises(ContinuationError, match="recovery_scope"):
        recovery.action_layer("raw_reexecution")
    assert recovery.descriptor(plan, unit, "raw") is None


def test_project_definitions_load_with_moneyflow_identities_unchanged(tmp_path, monkeypatch):
    # Only declarations load. Any request or formal-path open is an actual test failure.
    for key in list(os.environ):
        if key.startswith(("PROD_", "PG", "TUSHARE_", "CLICKHOUSE_", "FEISHU_")) or any(
            token in key for token in ("TOKEN", "PASSWORD", "DATABASE_URL", "DSN")
        ):
            monkeypatch.delenv(key)
    monkeypatch.setenv("DAGSTER_HOME", str(tmp_path / "instance"))
    original_open, original_os_open, original_path_open = builtins.open, os.open, Path.open

    def path_allowed(path):
        if isinstance(path, (str, bytes, os.PathLike)):
            name = os.fsdecode(path)
            assert not name.startswith(("/Volumes/", "/Users/congming/.goldenshare/")), name
            assert not Path(name).name.startswith(".env"), name

    def safe_open(path, *args, **kwargs):
        path_allowed(path)
        return original_open(path, *args, **kwargs)

    def safe_os_open(path, *args, **kwargs):
        path_allowed(path)
        return original_os_open(path, *args, **kwargs)

    def safe_path_open(path, *args, **kwargs):
        path_allowed(path)
        return original_path_open(path, *args, **kwargs)

    def no_network(*args, **kwargs):
        pytest.fail("Definitions loading attempted network access")

    monkeypatch.setattr(builtins, "open", safe_open)
    monkeypatch.setattr(os, "open", safe_os_open)
    monkeypatch.setattr(Path, "open", safe_path_open)
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket.socket, "connect_ex", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    from orchestrator.definitions import defs

    definitions = defs()
    graph = definitions.resolve_asset_graph()
    datasets = ("moneyflow_mkt_dc", "moneyflow_ind_ths", "moneyflow_cnt_ths", "moneyflow_ind_dc", "moneyflow_dc", "moneyflow_ths", "moneyflow")
    assets = {prefix + name for name in datasets for prefix in ("raw_tushare_", "silver_")}
    actual = {key.to_user_string() for key in graph.get_all_asset_keys() if key.to_user_string().startswith(("raw_tushare_moneyflow", "silver_moneyflow"))}
    assert actual == assets and len(actual) == 14
    jobs = {job.name for job in definitions.resolve_all_job_defs()}
    assert {name + "_update_job" for name in assets} <= jobs
    sensors = {sensor.name for sensor in definitions.sensors}
    expected_sensors = {name + "_update_job_sensor" for name in assets} | {"cn_a_" + name + "_trade_day_sensor" for name in datasets}
    assert len(expected_sensors) == 21 and expected_sensors <= sensors
    checks = [spec for definition in definitions.asset_checks for spec in definition.check_specs if spec.asset_key.to_user_string() in assets]
    assert len(checks) == 14 and all(spec.blocking for spec in checks)
