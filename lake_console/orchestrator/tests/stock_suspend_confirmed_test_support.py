"""Early protection for the confirmed-suspension resource and input-path tests.

Only stdlib at import time. No resource or pytest import before the OS self-check.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import signal
import socket
import stat
import sys
import time
from contextlib import contextmanager
from pathlib import Path

_allowed: Path | None = None
_completed = 0
_failures = 0
_started = 0.0
_local_instance_factory = None
_network_targets: dict = {}
_native_socket_connect = socket.socket.connect

GOLDEN_BYTES = (
    b"stock_suspend_confirmed|v1\n"
    b"000001.SZ\t2020-01-02\t\\N\tS\tadd_missing\n"
    b"688005.SH\t2026-01-16\t\\N\tS\treplace_confirmed\n"
)
GOLDEN_HASH = "dc7dde4185854a5c36d1fdc7a6da7e02405272fd688488bb3904f732a9914099"
FACTS_SQL = """SELECT * FROM (VALUES
    ('000001.SZ', DATE '2020-01-02', NULL::VARCHAR, 'S', 'add_missing'),
    ('688005.SH', DATE '2026-01-16', NULL::VARCHAR, 'S', 'replace_confirmed')
) t(ts_code, trade_date, suspend_timing, suspend_type, merge_mode)"""


def require_isolated_context() -> Path:
    if _allowed is None:
        raise RuntimeError("isolation_not_initialized_before_collection")
    return _allowed


def _assert_test_path_scope(path: Path, *, allowed: Path) -> None:
    if not path.is_absolute() or ".." in path.parts or not path.is_relative_to(allowed):
        raise ValueError("outside_test_root")


def checked_test_path(path: Path, *, allowed: Path) -> Path:
    """Reject lexical escapes before any path IO; never repair a path."""
    path = Path(path)
    _assert_test_path_scope(path, allowed=allowed)
    current = allowed
    for part in ("", *path.relative_to(allowed).parts):
        current = current / part
        if current.is_symlink():
            raise ValueError("symlink_not_allowed")
    return path


def checked_test_input_file(path: Path, *, lake_root: Path) -> Path:
    """Read-only test input preflight, not the production check adapter."""
    allowed = require_isolated_context()
    path, lake_root = Path(path), Path(lake_root)
    # Validate both lexical inputs before statting either one.
    _assert_test_path_scope(lake_root, allowed=allowed)
    _assert_test_path_scope(path, allowed=allowed)
    if not path.is_relative_to(lake_root):
        raise ValueError("outside_test_lake_root")
    checked_test_path(lake_root, allowed=allowed)
    try:
        root_stat = lake_root.lstat()
    except FileNotFoundError as error:
        raise ValueError("test_lake_root_missing") from error
    if not stat.S_ISDIR(root_stat.st_mode):
        raise ValueError("test_lake_root_not_directory")
    checked_test_path(path, allowed=allowed)
    try:
        file_stat = path.lstat()
    except FileNotFoundError as error:
        raise ValueError("test_input_file_missing") from error
    if not stat.S_ISREG(file_stat.st_mode):
        raise ValueError("test_input_not_regular_file")
    return path


def verify_lake_resource(resource, *, expected_root: Path) -> None:
    allowed = require_isolated_context()
    # root() itself only constructs a Path. Verify it before any stat, mkdir or probe.
    actual = resource.root()
    if actual != expected_root or not actual.is_relative_to(allowed):
        raise ValueError("resource_root_mismatch")


def make_confirmed_test_resources(*, lake_root: Path, work_root: Path) -> dict:
    """Construct verified test resources, without directory creation or connection."""
    allowed = require_isolated_context()
    if Path(work_root) != allowed:
        raise ValueError("work_root_mismatch")
    checked = checked_test_path(lake_root, allowed=allowed)
    from orchestrator.defs.resources import DuckDBResource, LakeRootResource

    class ConfirmedTestDuckDBResource(DuckDBResource):
        directory: str

        @contextmanager
        def connect(self):
            with connect_confirmed_test_duckdb(temp_directory=Path(self.directory)) as connection:
                yield connection

    resource = LakeRootResource(root_path=str(checked))
    verify_lake_resource(resource, expected_root=checked)
    return {"lake_root": resource,
            "duckdb": ConfirmedTestDuckDBResource(directory=str(allowed / "duckdb-temp"))}


def confirmed_test_duckdb_config(*, temp_directory: Path) -> dict[str, str]:
    checked = checked_test_path(temp_directory, allowed=require_isolated_context())
    return {"temp_directory": str(checked), "memory_limit": "512MB", "threads": "2",
            "max_temp_directory_size": "0B", "autoinstall_known_extensions": "false",
            "autoload_known_extensions": "false"}


def verify_confirmed_test_duckdb_connection(connection, *, expected: dict[str, str]) -> dict:
    observed = dict(connection.execute(
        "SELECT name, value FROM duckdb_settings() WHERE name IN "
        "('temp_directory','memory_limit','threads','max_temp_directory_size',"
        "'autoinstall_known_extensions','autoload_known_extensions')"
    ).fetchall())
    # DuckDB 1.5.2 display units, already measured in I02; do not use a loose tolerance.
    displayed = {**expected, "memory_limit": "488.2 MiB", "max_temp_directory_size": "0 bytes"}
    for name, value in displayed.items():
        if observed.get(name) != value:
            raise RuntimeError(f"test_duckdb_setting_mismatch:{name}")
    return observed


@contextmanager
def connect_confirmed_test_duckdb(*, temp_directory: Path):
    config = confirmed_test_duckdb_config(temp_directory=temp_directory)
    Path(config["temp_directory"]).mkdir(parents=True, exist_ok=True)
    import duckdb

    connection = duckdb.connect(database=":memory:", config=config)
    try:
        observed = verify_confirmed_test_duckdb_connection(connection, expected=config)
        print(json.dumps({"duckdb_settings": observed}), flush=True)
        yield connection
    finally:
        connection.close()


def _reject_formal_duckdb_connection(*args, **kwargs):
    raise RuntimeError("formal_duckdb_connection_forbidden_in_test")


def verify_confirmed_test_instance(instance, *, expected_root: Path) -> dict:
    from dagster import DagsterInstance
    from dagster._core.storage.event_log import SqliteEventLogStorage
    from dagster._core.storage.runs import SqliteRunStorage
    from dagster._core.storage.schedules import SqliteScheduleStorage
    from sqlalchemy.engine import make_url

    checked_test_path(expected_root, allowed=require_isolated_context())
    if (type(instance) is not DagsterInstance or not instance.is_persistent
            or instance.root_directory != str(expected_root) or instance.telemetry_enabled is not False):
        raise RuntimeError("test_instance_identity_mismatch")
    stores = {"event": (instance.event_log_storage, SqliteEventLogStorage),
              "run": (instance.run_storage, SqliteRunStorage),
              "schedule": (instance.schedule_storage, SqliteScheduleStorage)}
    for name, (storage, expected_type) in stores.items():
        if type(storage) is not expected_type:
            raise RuntimeError(f"test_instance_storage_type_mismatch:{name}")
    expected = {"event": expected_root / "history/runs/index.db",
                "run": expected_root / "history/runs.db",
                "schedule": expected_root / "schedules/schedules.db"}
    urls = {"event": instance.event_log_storage.conn_string_for_shard("index"),
            "run": instance.run_storage._conn_string,
            "schedule": instance.schedule_storage._conn_string}
    # Verify every declared path before opening even the first storage connection.
    for name, url in urls.items():
        parsed = make_url(url)
        if parsed.drivername != "sqlite" or parsed.database != str(expected[name]):
            raise RuntimeError(f"test_instance_storage_path_mismatch:{name}")
        checked_test_path(expected[name], allowed=require_isolated_context())
    connectors = {"event": instance.event_log_storage.index_connection,
                  "run": instance.run_storage.connect, "schedule": instance.schedule_storage.connect}
    observed = {}
    for name, connect in connectors.items():
        with connect() as connection:
            rows = connection.exec_driver_sql("PRAGMA database_list").fetchall()
            main_paths = [row[2] for row in rows if row[1] == "main"]
            if main_paths != [str(expected[name])]:
                raise RuntimeError(f"test_instance_storage_readback_mismatch:{name}")
            observed[name] = main_paths[0]
    return observed


def _create_confirmed_local_instance(tempdir=None, overrides=None):
    if tempdir is None:
        raise ValueError("test_instance_root_required")
    if overrides != {"telemetry": {"enabled": False}}:
        raise ValueError("test_instance_overrides_mismatch")
    root = checked_test_path(Path(tempdir), allowed=require_isolated_context())
    if (root / "dagster.yaml").exists():
        raise ValueError("test_instance_config_file_forbidden")
    if _local_instance_factory is None:
        raise RuntimeError("test_instance_factory_not_initialized")
    root.mkdir(parents=True, exist_ok=True)
    instance = _local_instance_factory(tempdir=str(root), overrides=overrides)
    try:
        observed = verify_confirmed_test_instance(instance, expected_root=root)
        print(json.dumps({"instance_storage_paths": observed, "telemetry_enabled": False}), flush=True)
    except BaseException:
        instance.dispose()
        raise
    return instance


@contextmanager
def make_confirmed_test_instance(*, instance_root: Path):
    require_isolated_context()
    from dagster import DagsterInstance

    with DagsterInstance.local_temp(str(instance_root), overrides={"telemetry": {"enabled": False}}) as instance:
        yield instance


def _reject_instance_discovery(*args, **kwargs):
    raise RuntimeError("instance_discovery_forbidden_in_test")


def _reject_test_network(*args, **kwargs):
    raise RuntimeError("network_forbidden_in_test")


def confirmed_test_network_address(kind: str):
    allowed = require_isolated_context()
    if kind not in ("tcp", "unix"):
        raise ValueError("test_network_kind_invalid")
    if set(_network_targets) != {"tcp", "unix"}:
        raise RuntimeError("test_network_endpoints_missing")
    host, port = _network_targets["tcp"]
    if host != "127.0.0.1" or not isinstance(port, int) or not 0 < port < 65536:
        raise ValueError("test_network_endpoint_invalid")
    if _network_targets["unix"] != str(allowed / "network.sock"):
        raise ValueError("test_network_endpoint_invalid")
    return (host, port) if kind == "tcp" else _network_targets["unix"]


def verify_native_test_network_denial(kind: str) -> int:
    """Call the saved CPython C socket method, bypassing only the Python guard."""
    address = confirmed_test_network_address(kind)
    with socket.socket(socket.AF_INET if kind == "tcp" else socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(1)
        try:
            _native_socket_connect(client, address)
        except OSError as error:
            if error.errno not in (errno.EPERM, errno.EACCES):
                raise
            return error.errno
    raise RuntimeError(f"native_network_isolation_failed:{kind}")


def _os_self_check(root: Path) -> None:
    """Fresh native allow/deny proof, not a reused I01/I02 success marker."""
    allowed, denied = root / "allowed", root / "denied-fixture"
    positive = allowed / "positive.txt"
    positive.write_bytes(b"synthetic")
    assert positive.read_bytes() == b"synthetic"
    native = ctypes.CDLL(None, use_errno=True)
    native.open.argtypes = [ctypes.c_char_p, ctypes.c_int]
    native.open.restype = ctypes.c_int
    native.close.argtypes = [ctypes.c_int]
    native.close.restype = ctypes.c_int
    fd = native.open(os.fsencode(positive), os.O_RDONLY)
    assert fd >= 0
    assert native.close(fd) == 0
    for path in (denied / "sentinel.txt",):
        ctypes.set_errno(0)
        fd = native.open(os.fsencode(path), os.O_RDONLY)
        if fd >= 0:
            native.close(fd)
            raise RuntimeError("native_read_isolation_failed")
        assert ctypes.get_errno() in (errno.EPERM, errno.EACCES)
    for name, action in (
        ("create", lambda: (denied / "new.txt").write_bytes(b"forbidden")),
        ("overwrite", lambda: (denied / "sentinel.txt").write_bytes(b"forbidden")),
        ("delete", lambda: (denied / "sentinel.txt").unlink()),
        ("mkdir", lambda: (denied / "new-directory").mkdir()),
        ("replace_out", lambda: os.replace(positive, denied / "sentinel.txt")),
        ("replace_in", lambda: os.replace(denied / "sentinel.txt", positive)),
    ):
        try:
            action()
        except OSError as error:
            if error.errno not in (errno.EPERM, errno.EACCES):
                raise
        else:
            raise RuntimeError(f"OS_self_check_failed:{name}")
    print(json.dumps({"native_self_check_passed": True, "negative_completed": 7}), flush=True)


def _deadline(signum, frame):
    raise TimeoutError("case_timeout_30s")


def _confirmed_contract_fixtures():
    """Register shared synthetic fixtures only after the OS/instance guards exist."""
    require_isolated_context()
    import pytest

    from orchestrator.defs import stock_suspend_confirmed_contract as contract
    from orchestrator.defs.paths import silver_stock_suspend_confirmed_path

    class SyntheticFixtures:
        @pytest.fixture
        def connection(self, tmp_path):
            with connect_confirmed_test_duckdb(temp_directory=tmp_path / "duckdb") as connection:
                yield connection

        @pytest.fixture
        def approved_sample(self, monkeypatch):
            monkeypatch.setattr(contract, "STOCK_SUSPEND_CONFIRMED_COUNTS", (2, 2, 2, 2, 1, 1))
            monkeypatch.setattr(contract, "STOCK_SUSPEND_CONFIRMED_OVERRIDE_KEYS", (("688005.SH", "2026-01-16"),))
            monkeypatch.setattr(contract, "STOCK_SUSPEND_CONFIRMED_APPROVED_LOGICAL_SHA256", GOLDEN_HASH)

        @pytest.fixture
        def fixed_lake(self, connection, tmp_path, approved_sample):
            root = checked_test_path(tmp_path / "lake", allowed=require_isolated_context())
            path = checked_test_path(silver_stock_suspend_confirmed_path(root), allowed=require_isolated_context())
            path.parent.mkdir(parents=True)
            connection.execute(f"COPY ({FACTS_SQL}) TO ? (FORMAT PARQUET)", [str(path)])
            return root

    return SyntheticFixtures()


def pytest_runtest_logstart(nodeid, location):
    global _started
    _started = time.monotonic()
    signal.signal(signal.SIGALRM, _deadline)
    signal.alarm(30)
    print(json.dumps({"case": nodeid, "started": True}), flush=True)


def pytest_runtest_logreport(report):
    global _completed, _failures
    if report.failed or report.skipped:
        _failures += 1
    if report.when == "call" and report.passed:
        _completed += 1


def pytest_runtest_logfinish(nodeid, location):
    signal.alarm(0)
    print(json.dumps({"case": nodeid, "completed": _completed,
                      "elapsed_ms": round(1000 * (time.monotonic() - _started))}), flush=True)


def probe_startup_gate(case: str, root_name: str, policy_hash: str, test_name: str) -> int:
    """Fixed I07 probes; the parent has already applied the OS policy."""
    import importlib.util
    from unittest.mock import patch

    root = Path(root_name)
    allowed = root / "allowed"
    if case in ("collection_allowed", "collection_denied", "skip", "xfail"):
        result = run(root_name, policy_hash, test_name, batch=f"I07:{case}",
                     case_names=("test_body",), expected_count=1, network_targets={})
        forbidden = [name for name in sys.modules if name == "orchestrator.definitions"
                     or name.startswith(("orchestrator.defs.assets.", "orchestrator.defs.checks."))]
        assert not forbidden
        (allowed / "startup-proof.json").write_text(json.dumps({
            "case": case, "business_modules": forbidden, "pytest_exit": result,
        }) + "\n")
        return result

    reasons = {"guard_missing": "isolation_not_initialized_before_collection",
               "guard_late": "protection_loaded_too_late", "policy_mismatch": "policy_mismatch",
               "selfcheck_failed_stale": "synthetic_self_check_failed"}
    if case not in reasons:
        raise ValueError("unknown_startup_probe")
    self_check_calls = []

    def failed_self_check(observed_root):
        assert observed_root == root
        self_check_calls.append(str(observed_root))
        raise RuntimeError("synthetic_self_check_failed")

    try:
        if case == "guard_missing":
            spec = importlib.util.spec_from_file_location("i07_unprotected_test", test_name)
            spec.loader.exec_module(importlib.util.module_from_spec(spec))
        else:
            if case == "guard_late":
                import pytest  # noqa: F401 -- real early import is the deliberate fault.
            if case == "policy_mismatch":
                policy_hash = "0" * 64
            if case == "selfcheck_failed_stale":
                with patch.object(sys.modules[__name__], "_os_self_check", failed_self_check):
                    run(root_name, policy_hash, test_name, batch="I07", case_names=("test_body",),
                        expected_count=1, network_targets={})
            else:
                run(root_name, policy_hash, test_name, batch="I07", case_names=("test_body",),
                    expected_count=1, network_targets={})
    except RuntimeError as error:
        assert str(error) == reasons[case]
        assert _allowed is None
        loaded = [name for name in ("dagster", "duckdb", "orchestrator", "pytest") if name in sys.modules]
        assert loaded == (["pytest"] if case == "guard_late" else [])
        assert len(self_check_calls) == (1 if case == "selfcheck_failed_stale" else 0)
        proof = {"case": case, "reason": str(error), "context_initialized": False,
                 "loaded_modules": loaded, "self_check_calls": self_check_calls}
        (allowed / "startup-proof.json").write_text(json.dumps(proof) + "\n")
        print(json.dumps(proof), flush=True)
        return 1  # The attempted execution really failed; the parent checks why.
    raise AssertionError("startup_gate_did_not_reject")


def run(root_name: str, policy_hash: str, test_name: str, *, batch: str,
        case_names: tuple[str, ...], expected_count: int, network_targets: dict,
        scope: str = "isolation") -> int:
    global _allowed, _local_instance_factory, _network_targets
    root = Path(root_name)
    if root.parent != Path("/private/tmp") or not root.name.startswith("stock-suspend-isolated-"):
        raise RuntimeError("invalid_work_root")
    if any(name in sys.modules for name in ("dagster", "duckdb", "orchestrator", "pytest")):
        raise RuntimeError("protection_loaded_too_late")
    forbidden_env = {"HOME", "CODEX_HOME", "DAGSTER_HOME", "PYTHONPATH", "PYTEST_ADDOPTS"}
    if forbidden_env.intersection(os.environ):
        raise RuntimeError("inherited_runtime_environment")
    if not sys.flags.isolated or not sys.dont_write_bytecode:
        raise RuntimeError("interpreter_not_isolated")
    allowed = root / "allowed"
    if hashlib.sha256((allowed / "capability.sb").read_bytes()).hexdigest() != policy_hash:
        raise RuntimeError("policy_mismatch")
    _os_self_check(root)
    _allowed = allowed
    _network_targets = network_targets
    from contextlib import ExitStack
    from unittest.mock import patch

    import dagster
    import pytest
    from dagster._core.instance import factory

    from orchestrator.defs import duckdb_connection, resources

    test_directory = str(Path(test_name).parent)
    args = ["-c", "/dev/null", "--rootdir", test_directory, "--confcutdir", test_directory,
            "--ignore-glob", str(Path(test_directory) / "*"),
            "--noconftest", "-p", "no:cacheprovider",
            "--import-mode=importlib", "--basetemp", str(allowed / "pytest"),
            "-x", "-v", "-s", *(f"{test_name}::{name}" for name in case_names)]
    print(json.dumps({"pytest_argv": args, "implemented_slice": batch}), flush=True)
    _local_instance_factory = factory.create_local_temp_instance
    with ExitStack() as guards:
        for owner, name, replacement in (
            (resources, "connect_configured_duckdb", _reject_formal_duckdb_connection),
            (duckdb_connection, "connect_configured_duckdb", _reject_formal_duckdb_connection),
            (factory, "create_local_temp_instance", _create_confirmed_local_instance),
            (factory, "create_instance_from_dagster_home", _reject_instance_discovery),
            (factory, "create_instance_from_config", _reject_instance_discovery),
            (dagster.DagsterInstance, "from_ref", staticmethod(_reject_instance_discovery)),
            (socket.socket, "connect", _reject_test_network),
            (socket.socket, "connect_ex", _reject_test_network),
            (socket, "create_connection", _reject_test_network),
            (socket, "getaddrinfo", _reject_test_network),
        ):
            guards.enter_context(patch.object(owner, name, replacement))
        plugins = [sys.modules[__name__]]
        if scope in ("adapter", "regression"):
            plugins.append(_confirmed_contract_fixtures())
        elif scope != "isolation":
            raise ValueError("invalid_scope")
        result = int(pytest.main(args, plugins=plugins))
    (allowed / "pytest-result.json").write_text(json.dumps({
        "slice": batch, "completed": _completed, "failures": _failures,
        "passed": result == 0 and _completed == expected_count and _failures == 0,
    }) + "\n")
    return result
