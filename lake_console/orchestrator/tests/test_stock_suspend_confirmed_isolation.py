"""I03-I06 and I08 isolated resource tests; I07 runs separate startup fixtures."""

from stock_suspend_confirmed_test_support import (
    checked_test_input_file,
    checked_test_path,
    confirmed_test_network_address,
    connect_confirmed_test_duckdb,
    make_confirmed_test_instance,
    make_confirmed_test_resources,
    require_isolated_context,
    verify_confirmed_test_instance,
    verify_lake_resource,
    verify_native_test_network_denial,
)

# This must precede business imports and fail under an ordinary pytest invocation.
ALLOWED = require_isolated_context()

import errno
import hashlib
import importlib.util
import io
import json
import os
import socket
import stat
from contextlib import ExitStack, contextmanager, redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

import dagster as dg
import duckdb
import pytest
from dagster._core.instance import factory

from orchestrator.defs import duckdb_connection, resources
from orchestrator.defs.resources import DuckDBResource, LakeRootResource


@pytest.mark.parametrize("variant", (
    "normal_eof", "nonzero_exit", "exit_timeout", "monitor_error",
    "budget_stopped", "termination_denied",
))
def test_runner_child_exit(variant):
    runner_path = Path(__file__).with_name("stock_suspend_confirmed_test_runner.py")
    spec = importlib.util.spec_from_file_location("confirmed_runner_exit_test", runner_path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    root = ALLOWED / f"runner-exit-{variant}"
    (root / "allowed").mkdir(parents=True)
    (root / "denied-fixture").mkdir()
    (root / "denied-fixture/sentinel.txt").write_text("synthetic unchanged input")
    # Deliberately green assertions: process failure must still fail the batch.
    (root / "allowed/pytest-result.json").write_text(json.dumps({
        "passed": True, "completed": 1, "failures": 0,
    }))
    process = MagicMock(pid=123456789, returncode=2 if variant == "nonzero_exit" else None)
    process.stdout, process.stderr = io.BytesIO(), io.BytesIO()
    process.poll.side_effect = lambda: process.returncode
    calls = []

    def wait(*, timeout):
        calls.append("wait")
        assert timeout == 5
        if variant in ("exit_timeout", "termination_denied") and len(calls) == 1:
            raise runner.subprocess.TimeoutExpired("synthetic-child", timeout)
        if process.returncode is None:
            process.returncode = 0
        return process.returncode

    def kill(pid, sig):
        calls.append("kill")
        assert (pid, sig) == (process.pid, runner.signal.SIGKILL)
        if variant == "termination_denied":
            raise PermissionError(errno.EPERM, "synthetic termination denied")
        process.returncode = -9

    process.wait.side_effect = wait
    selector = MagicMock()
    selector.get_map.return_value = {}
    if variant == "monitor_error":
        selector.get_map.side_effect = RuntimeError("synthetic monitor error")
    elif variant == "budget_stopped":
        selector.get_map.side_effect = ({1: object()}, {})
        selector.select.return_value = []
    with patch.object(runner.subprocess, "Popen", return_value=process) as popen, \
            patch.object(runner.selectors, "DefaultSelector") as selector_factory, \
            patch.object(runner.os, "killpg", side_effect=kill) as killpg, \
            patch.object(runner, "workspace_size", return_value=101 * 1024**2), \
            redirect_stdout(io.StringIO()):
        selector_factory.return_value.__enter__.return_value = selector
        if variant in ("monitor_error", "termination_denied"):
            error = RuntimeError if variant == "monitor_error" else PermissionError
            with pytest.raises(error, match="synthetic"):
                runner.run_isolation_child(root, "synthetic-exit", 1, ("synthetic",), {})
        else:
            code = runner.run_isolation_child(root, "synthetic-exit", 1, ("synthetic",), {})
            assert code == (0 if variant == "normal_eof" else 1)
        assert popen.call_args.kwargs["start_new_session"] is True
        assert killpg.call_count == (0 if variant in ("normal_eof", "nonzero_exit") else 1)
    report = json.loads((root / "allowed/resource-result.json").read_text())
    assert report["passed"] is (variant == "normal_eof")
    if variant == "exit_timeout":
        assert calls[:2] == ["wait", "kill"]
        assert report["stop_reason"] == "child_exit_timeout_5s"
        assert report["exit_code"] == -9
    elif variant == "monitor_error":
        assert calls[:2] == ["kill", "wait"]
        assert report["stop_reason"] == "parent_monitor_error"
        assert report["child_reaped"] is True
    elif variant == "budget_stopped":
        assert calls[:2] == ["kill", "wait"]
        assert report["stop_reason"] == "workspace_budget_100MiB"
    elif variant in ("normal_eof", "nonzero_exit"):
        assert calls[0] == "wait"
        assert report["exit_code"] == (0 if variant == "normal_eof" else 2)


def test_i03_actual_resource_root():
    root = ALLOWED / "lake"
    resources = make_confirmed_test_resources(lake_root=root, work_root=ALLOWED)
    resource = resources["lake_root"]
    assert type(resource) is LakeRootResource
    assert resource.root() == root
    assert resource.root_path == str(root)
    assert not root.exists()  # Resource construction did not mkdir or probe.


@pytest.mark.parametrize("variant", ["wrong_keyword", "missing_root", "formal_root", "wrong_work_root"])
def test_i03_factory_rejects_before_path_io(variant):
    kwargs = {"lake_root": ALLOWED / "lake", "work_root": ALLOWED}
    expected = ValueError
    if variant == "wrong_keyword":
        kwargs["root_path"] = kwargs.pop("lake_root")
        expected = TypeError
    elif variant == "missing_root":
        del kwargs["lake_root"]
        expected = TypeError
    elif variant == "formal_root":
        kwargs["lake_root"] = Path("/Volumes/datasource/data_lake")
    else:
        kwargs["work_root"] = ALLOWED.parent
    with patch.object(Path, "stat") as stat, patch.object(Path, "lstat") as lstat, \
            patch.object(Path, "mkdir") as mkdir, patch.object(Path, "open") as opened, \
            patch.object(LakeRootResource, "ensure_available_for_run") as probe:
        with pytest.raises(expected):
            make_confirmed_test_resources(**kwargs)
        for spy in (stat, lstat, mkdir, opened, probe):
            spy.assert_not_called()


def _input_fixture_inventory(directory):
    """Record synthetic identities/content without following links."""
    result = []
    for path in (directory, *sorted(directory.rglob("*"))):
        observed = path.lstat()
        result.append((
            str(path.relative_to(directory)), observed.st_dev, observed.st_ino,
            observed.st_mode, observed.st_size, observed.st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest() if stat.S_ISREG(observed.st_mode)
            else os.readlink(path) if stat.S_ISLNK(observed.st_mode) else None,
        ))
    return result


@pytest.mark.parametrize(("variant", "reason"), [
    ("regular_file", None),
    ("missing_root", "test_lake_root_missing"),
    ("missing_file", "test_input_file_missing"),
    ("root_is_file", "test_lake_root_not_directory"),
    ("target_is_directory", "test_input_not_regular_file"),
    ("dotdot", "outside_test_root"),
    ("file_symlink", "symlink_not_allowed"),
    ("parent_symlink", "symlink_not_allowed"),
])
def test_i04_input_path_preflight(variant, reason):
    case_root = ALLOWED / f"input-{variant}"
    case_root.mkdir()
    root = case_root / "lake"
    target = root / "facts.txt"
    link = None
    if variant == "root_is_file":
        root.write_text("synthetic wrong-type root\n")
    elif variant != "missing_root":
        root.mkdir()
        (root / "unchanged.txt").write_text("synthetic unchanged input\n")
        if variant == "regular_file":
            target.write_text("synthetic regular input\n")
        elif variant == "target_is_directory":
            target.mkdir()
        elif variant == "dotdot":
            target = ALLOWED / ".." / "denied-fixture" / "sentinel.txt"
        elif variant == "file_symlink":
            link = target
            link.symlink_to(ALLOWED.parent / "denied-fixture" / "sentinel.txt")
        elif variant == "parent_symlink":
            link = root / "linked-directory"
            link.symlink_to(ALLOWED.parent / "denied-fixture", target_is_directory=True)
            target = link / "sentinel.txt"

    before = _input_fixture_inventory(case_root)
    original_stat = os.stat
    path_calls = []

    def guarded_stat(path, *args, **kwargs):
        # CPython 3.13 Path.lstat() delegates to os.stat(follow_symlinks=False).
        assert kwargs.get("follow_symlinks") is False
        observed = Path(path)
        assert observed.is_relative_to(ALLOWED) and ".." not in observed.parts
        if link is not None:
            assert observed == link or not observed.is_relative_to(link)
        path_calls.append(str(observed))
        return original_stat(path, *args, **kwargs)

    forbidden = (
        (Path, "open"), (Path, "mkdir"), (Path, "resolve"),
        (os, "open"), (os, "mkdir"), (os, "rename"), (os, "replace"), (os, "unlink"),
        (LakeRootResource, "ensure_available_for_run"),
    )
    with ExitStack() as stack:
        spies = [stack.enter_context(patch.object(owner, name, side_effect=AssertionError(name)))
                 for owner, name in forbidden]
        stack.enter_context(patch.object(os, "stat", side_effect=guarded_stat))
        if reason is None:
            assert checked_test_input_file(target, lake_root=root) == target
        else:
            with pytest.raises(ValueError, match=f"^{reason}$"):
                checked_test_input_file(target, lake_root=root)
        for spy in spies:
            spy.assert_not_called()
    assert _input_fixture_inventory(case_root) == before
    if variant == "dotdot":
        assert path_calls == []
    else:
        assert path_calls
    if link is not None:
        assert str(link) in path_calls
    print(json.dumps({"variant": variant, "reason": reason or "accepted",
                      "path_calls": path_calls, "forbidden_calls": 0,
                      "fixture_unchanged": True}), flush=True)


@pytest.mark.parametrize("variant", ["wrong_keyword", "implicit_default", "explicit_formal"])
def test_i03_detects_real_resource_default_without_io(variant):
    kwargs = {"lake_root": str(ALLOWED / "lake")} if variant == "wrong_keyword" else {}
    if variant == "explicit_formal":
        kwargs = {"root_path": "/Volumes/datasource/data_lake"}
    with patch.object(Path, "stat") as stat, patch.object(Path, "lstat") as lstat, \
            patch.object(Path, "mkdir") as mkdir, patch.object(Path, "open") as opened, \
            patch.object(LakeRootResource, "ensure_available_for_run") as probe:
        resource = LakeRootResource(**kwargs)
        assert resource.root() == Path("/Volumes/datasource/data_lake")
        with pytest.raises(ValueError, match="resource_root_mismatch"):
            verify_lake_resource(resource, expected_root=ALLOWED / "lake")
        for spy in (stat, lstat, mkdir, opened, probe):
            spy.assert_not_called()


def test_i05_real_duckdb_resource():
    test_resources = make_confirmed_test_resources(lake_root=ALLOWED / "lake", work_root=ALLOWED)
    resource = test_resources["duckdb"]
    assert isinstance(resource, DuckDBResource)
    assert resource.directory == str(ALLOWED / "duckdb-temp")
    assert not Path(resource.directory).exists()
    with resource.connect() as connection:
        observed = dict(connection.execute(
            "SELECT name,value FROM duckdb_settings() WHERE name IN "
            "('memory_limit','threads','max_temp_directory_size','temp_directory',"
            "'autoinstall_known_extensions','autoload_known_extensions')"
        ).fetchall())
        assert observed == {
            "memory_limit": "488.2 MiB", "threads": "2", "max_temp_directory_size": "0 bytes",
            "temp_directory": str(ALLOWED / "duckdb-temp"),
            "autoinstall_known_extensions": "false", "autoload_known_extensions": "false",
        }
        assert connection.execute("SELECT n FROM (VALUES (1),(2)) t(n) ORDER BY n").fetchall() == [(1,), (2,)]
    with pytest.raises(duckdb.ConnectionException, match="closed"):
        connection.execute("SELECT 1")
    assert list(Path(resource.directory).iterdir()) == []
    print(json.dumps({"case_evidence": "I05_real_resource", "observed": observed,
                      "closed": True, "spill_files": 0}), flush=True)


@pytest.mark.parametrize(("setting", "wrong_value", "mode"), [
    ("threads", "1", "native_configuration"),
    ("memory_limit", "256MB", "native_configuration"),
    ("temp_directory", "wrong-directory", "readback_fault"),
    ("max_temp_directory_size", "1 MiB", "readback_fault"),
    ("autoinstall_known_extensions", "true", "readback_fault"),
    ("autoload_known_extensions", "true", "readback_fault"),
])
def test_i05_rejects_wrong_effective_setting(setting, wrong_value, mode):
    temp = ALLOWED / f"duckdb-wrong-{setting}"
    native_connect = duckdb.connect
    connections = []

    class ReadbackFault:
        """Deliberately corrupt a real settings read, never enable unsafe settings."""
        def __init__(self, connection):
            self.connection = connection

        def execute(self, sql):
            rows = dict(self.connection.execute(sql).fetchall())
            assert setting in rows
            rows[setting] = wrong_value
            self.rows = list(rows.items())
            return self

        def fetchall(self):
            return self.rows

        def close(self):
            self.connection.close()

    def open_faulty(*, database, config):
        assert database == ":memory:"
        assert config["max_temp_directory_size"] == "0B"
        assert config["autoinstall_known_extensions"] == "false"
        assert config["autoload_known_extensions"] == "false"
        assert config["temp_directory"] == str(temp)
        actual_config = {**config, setting: wrong_value} if mode == "native_configuration" else config
        connection = native_connect(database=database, config=actual_config)
        connections.append(connection)
        return connection if mode == "native_configuration" else ReadbackFault(connection)

    with patch.object(duckdb, "connect", side_effect=open_faulty) as connect_spy:
        with pytest.raises(RuntimeError, match=f"^test_duckdb_setting_mismatch:{setting}$"), \
                connect_confirmed_test_duckdb(temp_directory=temp):
            pytest.fail("Invalid connection reached the caller")
        connect_spy.assert_called_once()
    assert len(connections) == 1
    with pytest.raises(duckdb.ConnectionException, match="closed"):
        connections[0].execute("SELECT 1")
    assert list(temp.iterdir()) == []
    print(json.dumps({"case_evidence": "I05_setting_rejected", "setting": setting,
                      "mode": mode, "closed": True, "yielded": False, "spill_files": 0}), flush=True)


@pytest.mark.parametrize("variant", ["missing_temp", "wrong_keyword", "formal_temp"])
def test_i05_rejects_bad_connection_arguments(variant):
    kwargs = {"temp_directory": ALLOWED / "duckdb-temp"}
    expected = TypeError
    if variant == "missing_temp":
        kwargs = {}
    elif variant == "wrong_keyword":
        kwargs = {"directory": ALLOWED / "duckdb-temp"}
    else:
        kwargs["temp_directory"] = Path("/Volumes/datasource/.goldenshare_duckdb_tmp")
        expected = ValueError
    with patch.object(duckdb, "connect") as connect_spy, \
            patch.object(Path, "stat") as stat_spy, patch.object(Path, "lstat") as lstat_spy, \
            patch.object(Path, "mkdir") as mkdir_spy, patch.object(Path, "open") as open_spy:
        with pytest.raises(expected), connect_confirmed_test_duckdb(**kwargs):
            pytest.fail("Invalid arguments reached the caller")
        for spy in (connect_spy, stat_spy, lstat_spy, mkdir_spy, open_spy):
            spy.assert_not_called()
    print(json.dumps({"case_evidence": "I05_arguments_rejected", "variant": variant,
                      "path_io": 0, "native_connect": 0}), flush=True)


@pytest.mark.parametrize("entry", ["resource", "resource_wrong_keyword", "connection_helper", "resource_helper"])
def test_i05_rejects_formal_connection_entry(entry):
    with patch.object(duckdb, "connect") as connect_spy, \
            patch.object(Path, "stat") as stat_spy, patch.object(Path, "lstat") as lstat_spy, \
            patch.object(Path, "mkdir") as mkdir_spy, patch.object(Path, "open") as open_spy:
        if entry.startswith("resource") and entry != "resource_helper":
            kwargs = {"temp_directory": str(ALLOWED / "duckdb-temp")} if entry == "resource_wrong_keyword" else {}
            resource = DuckDBResource(**kwargs)
            assert type(resource) is DuckDBResource
            assert "temp_directory" not in resource.model_dump()
            connect = resource.connect
        elif entry == "connection_helper":
            connect = duckdb_connection.connect_configured_duckdb
        else:
            connect = resources.connect_configured_duckdb
        with pytest.raises(RuntimeError, match="^formal_duckdb_connection_forbidden_in_test$"), connect():
            pytest.fail("Formal connection reached the caller")
        for spy in (connect_spy, stat_spy, lstat_spy, mkdir_spy, open_spy):
            spy.assert_not_called()
    print(json.dumps({"case_evidence": "I05_formal_entry_rejected", "entry": entry,
                      "path_io": 0, "native_connect": 0}), flush=True)


def test_i06_real_instance_persistence():
    root = ALLOWED / "instance"
    key = dg.AssetKey(["synthetic", "confirmed_suspend_isolation"])
    materialization = dg.AssetMaterialization(
        asset_key=key, metadata={"synthetic": True, "fixture": "I06"},
    )
    with make_confirmed_test_instance(instance_root=root) as instance:
        observed = verify_confirmed_test_instance(instance, expected_root=root)
        assert observed == {
            "event": str(root / "history/runs/index.db"),
            "run": str(root / "history/runs.db"),
            "schedule": str(root / "schedules/schedules.db"),
        }
        # Corrupt only the declared connection path; never connect to the wrong one.
        for kind, storage, attribute in (
            ("event", instance.event_log_storage, "conn_string_for_shard"),
            ("run", instance.run_storage, "_conn_string"),
            ("schedule", instance.schedule_storage, "_conn_string"),
        ):
            wrong_url = f"sqlite:///{root / 'wrong.db'}"
            fault = patch.object(storage, attribute, return_value=wrong_url) if kind == "event" \
                else patch.object(storage, attribute, wrong_url)
            with ExitStack() as stack:
                stack.enter_context(fault)
                spies = [stack.enter_context(patch.object(owner, name, side_effect=AssertionError(name)))
                         for owner, name in (
                             (instance.event_log_storage, "index_connection"),
                             (instance.run_storage, "connect"),
                             (instance.schedule_storage, "connect"),
                         )]
                with pytest.raises(RuntimeError, match=f"^test_instance_storage_path_mismatch:{kind}$"):
                    verify_confirmed_test_instance(instance, expected_root=root)
                for spy in spies:
                    spy.assert_not_called()
            print(json.dumps({"case_evidence": "I06_storage_path_rejected", "storage": kind,
                              "storage_connections": 0}), flush=True)
        instance.report_runless_asset_event(materialization)
        first = instance.fetch_materializations(key, limit=2).records
        assert len(first) == 1
        assert first[0].asset_materialization == materialization
        storage_id = first[0].storage_id
        assert first[0].partition_key is None
        assert instance.get_run_records(limit=2) == []
    with make_confirmed_test_instance(instance_root=root) as reopened:
        second = reopened.fetch_materializations(key, limit=2).records
        assert len(second) == 1
        assert second[0].storage_id == storage_id
        assert second[0].asset_materialization == materialization
        assert second[0].partition_key is None
        assert reopened.get_run_records(limit=2) == []
    assert not (root / "wrong.db").exists()
    print(json.dumps({"case_evidence": "I06_real_instance", "storage_paths": observed,
                      "reopened": True, "event_count": 1, "storage_id": storage_id,
                      "synthetic": True, "job_runs": 0}), flush=True)


@pytest.mark.parametrize(("variant", "reason"), [
    ("missing_root", "test_instance_root_required"),
    ("wrong_keyword", None),
    ("formal_home", "outside_test_root"),
    ("unsafe_overrides", "test_instance_overrides_mismatch"),
    ("config_file", "test_instance_config_file_forbidden"),
])
def test_i06_rejects_local_instance_arguments(variant, reason):
    root = ALLOWED / f"instance-rejected-{variant}"
    kwargs = {"tempdir": str(root), "overrides": {"telemetry": {"enabled": False}}}
    if variant == "missing_root":
        del kwargs["tempdir"]
    elif variant == "wrong_keyword":
        kwargs["directory"] = kwargs.pop("tempdir")
    elif variant == "formal_home":
        kwargs["tempdir"] = "/Users/congming/.goldenshare/dagster_home"
    elif variant == "unsafe_overrides":
        kwargs["overrides"] = {"telemetry": {"enabled": True}}
    else:
        root.mkdir()
        (root / "dagster.yaml").write_text("telemetry:\n  enabled: false\n")
    forbidden = [(factory, "create_instance_from_ref"), (Path, "open"), (os, "open"), (os, "mkdir")]
    if variant != "config_file":
        forbidden.extend([(Path, "stat"), (Path, "lstat"), (os, "stat")])
    with ExitStack() as stack:
        spies = [stack.enter_context(patch.object(owner, name, side_effect=AssertionError(name)))
                 for owner, name in forbidden]
        with pytest.raises(TypeError if reason is None else ValueError,
                           match=None if reason is None else f"^{reason}$"):
            dg.DagsterInstance.local_temp(**kwargs)
        for spy in spies:
            spy.assert_not_called()
    print(json.dumps({"case_evidence": "I06_instance_arguments_rejected", "variant": variant,
                      "reason": reason or "TypeError", "content_reads": 0,
                      "instance_creations": 0, "mkdir_calls": 0}), flush=True)


@pytest.mark.parametrize("entry", ["get", "factory_home", "from_config", "from_ref"])
def test_i06_rejects_instance_discovery(entry):
    forbidden = ((os, "getenv"), (os, "stat"), (os, "open"), (os, "mkdir"),
                 (Path, "stat"), (Path, "lstat"), (Path, "open"),
                 (factory, "create_instance_from_ref"))
    with ExitStack() as stack:
        spies = [stack.enter_context(patch.object(owner, name, side_effect=AssertionError(name)))
                 for owner, name in forbidden]
        with pytest.raises(RuntimeError, match="^instance_discovery_forbidden_in_test$"):
            if entry == "get":
                dg.DagsterInstance.get()
            elif entry == "factory_home":
                factory.create_instance_from_dagster_home()
            elif entry == "from_config":
                dg.DagsterInstance.from_config("/Users/congming/.goldenshare/dagster_home")
            else:
                dg.DagsterInstance.from_ref(None)
        for spy in spies:
            spy.assert_not_called()
    print(json.dumps({"case_evidence": "I06_default_instance_rejected", "entry": entry,
                      "environment_reads": 0, "path_io": 0, "instance_creations": 0}), flush=True)


@pytest.mark.parametrize("entry", ["tcp_connect", "tcp_connect_ex", "create_connection", "unix_connect"])
def test_i06_python_network_guard(entry):
    kind = "unix" if entry == "unix_connect" else "tcp"
    address = confirmed_test_network_address(kind)
    with patch.object(socket, "getaddrinfo", side_effect=AssertionError("DNS attempted")) as dns:
        with pytest.raises(RuntimeError, match="^network_forbidden_in_test$"):
            if entry == "create_connection":
                socket.create_connection(address, timeout=1)
            else:
                with socket.socket(socket.AF_UNIX if kind == "unix" else socket.AF_INET,
                                   socket.SOCK_STREAM) as client:
                    client.settimeout(1)
                    if entry == "tcp_connect_ex":
                        client.connect_ex(address)
                    else:
                        client.connect(address)
        dns.assert_not_called()
    print(json.dumps({"case_evidence": "I06_python_network_rejected", "entry": entry,
                      "dns_calls": 0}), flush=True)


@pytest.mark.parametrize("kind", ["tcp", "unix"])
def test_i06_native_network_denial(kind):
    observed_errno = verify_native_test_network_denial(kind)
    assert observed_errno in (errno.EPERM, errno.EACCES)
    print(json.dumps({"case_evidence": "I06_native_network_rejected", "kind": kind,
                      "errno": observed_errno, "permission_denied": True}), flush=True)


@contextmanager
def _record_i08_path_io(case_root: Path):
    """Observe this helper's real Path operations, including transient files."""
    checked_test_path(case_root, allowed=ALLOWED)
    originals = {name: getattr(Path, name) for name in ("mkdir", "write_text", "read_text", "unlink")}
    events = []

    def observed_method(name):
        def call(path, *args, **kwargs):
            checked_test_path(Path(path), allowed=case_root)
            entry = {"operation": name, "path": str(path), "completed": False}
            events.append(entry)
            try:
                result = originals[name](path, *args, **kwargs)
                if name in ("write_text", "read_text"):
                    content = args[0] if name == "write_text" else result
                    encoded = content.encode("utf-8")
                    entry.update(bytes=len(encoded), sha256=hashlib.sha256(encoded).hexdigest())
                if name == "write_text":
                    entry["file_size_after"] = path.stat().st_size
                elif name == "unlink":
                    entry["exists_after"] = path.exists()
                entry["completed"] = True
                return result
            except BaseException as error:
                entry["error_type"] = type(error).__name__
                raise
        return call

    try:
        with ExitStack() as observers:
            for name in originals:
                observers.enter_context(patch.object(Path, name, observed_method(name)))
            yield events
    finally:
        assert all(getattr(Path, name) is original for name, original in originals.items())
        # Persist evidence after restoring methods, including on a test failure.
        (ALLOWED / f"{case_root.name}-io.json").write_text(json.dumps(events, indent=2) + "\n")


def test_i08_readonly_input_has_no_side_effects():
    root = ALLOWED / "i08-readonly"
    root.mkdir()
    target = root / "synthetic.txt"
    target.write_text("synthetic readonly input\n", encoding="utf-8")
    before = _input_fixture_inventory(root)
    with _record_i08_path_io(root) as events:
        checked = checked_test_input_file(target, lake_root=root)
        assert checked.read_text(encoding="utf-8") == "synthetic readonly input\n"
    assert [entry["operation"] for entry in events] == ["read_text"]
    assert events[0]["completed"] is True and events[0]["path"] == str(target)
    assert _input_fixture_inventory(root) == before
    print(json.dumps({"case_evidence": "I08_readonly_input", "events": events,
                      "mutation_calls": 0, "fixture_unchanged": True}), flush=True)


@pytest.mark.parametrize("layout", ["first_probe", "existing_probe_directory"])
def test_i08_health_probe_side_effects(layout):
    root = ALLOWED / f"i08-{layout}"
    root.mkdir()
    for layer in ("raw", "silver", "gold"):
        (root / layer).mkdir()
    (root / "silver/unchanged.txt").write_text("synthetic unchanged fact\n", encoding="utf-8")
    probe_directory = root / "_tmp/lake_root_health"
    if layout == "existing_probe_directory":
        probe_directory.mkdir(parents=True)
    resource = make_confirmed_test_resources(lake_root=root, work_root=ALLOWED)["lake_root"]
    assert type(resource) is LakeRootResource and resource.root() == root
    before = _input_fixture_inventory(root)

    # No replacement of ensure_available_for_run or any shared health function.
    with _record_i08_path_io(root) as events:
        resource.ensure_available_for_run()

    assert [entry["operation"] for entry in events] == ["mkdir", "mkdir", "write_text", "read_text", "unlink"]
    assert all(entry["completed"] for entry in events)
    assert [entry["path"] for entry in events[:2]] == [str(root / "_tmp"), str(probe_directory)]
    written, read, deleted = events[2:]
    canary = Path(written["path"])
    assert canary.parent == probe_directory and canary.name.startswith("canary-") and canary.suffix == ".txt"
    token = canary.stem.removeprefix("canary-")
    assert len(token) == 32 and all(char in "0123456789abcdef" for char in token)
    expected = f"goldenshare-lake-root-health:{token}\n".encode()
    assert written["bytes"] == read["bytes"] == written["file_size_after"] == len(expected)
    assert written["sha256"] == read["sha256"] == hashlib.sha256(expected).hexdigest()
    assert read["path"] == deleted["path"] == str(canary)
    assert deleted["exists_after"] is False and not canary.exists()

    after = _input_fixture_inventory(root)
    assert [row for row in before if stat.S_ISREG(row[3])] == [row for row in after if stat.S_ISREG(row[3])]
    before_dirs = {row[0] for row in before if stat.S_ISDIR(row[3])}
    after_dirs = {row[0] for row in after if stat.S_ISDIR(row[3])}
    added_dirs = after_dirs - before_dirs
    assert before_dirs <= after_dirs
    assert added_dirs == ({"_tmp", "_tmp/lake_root_health"} if layout == "first_probe" else set())
    print(json.dumps({"case_evidence": "I08_real_health_probe", "layout": layout,
                      "root": str(root), "events": events, "helper_calls": 1,
                      "added_directories": sorted(added_dirs), "regular_files_unchanged": True,
                      "probe_deleted": True, "readonly_contract_passed": False}), flush=True)
