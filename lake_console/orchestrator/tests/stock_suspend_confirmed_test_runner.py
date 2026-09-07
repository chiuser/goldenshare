"""Task-local, stdlib-only launcher for I03-I06 isolation tests in fixed batches.

No Dagster imports, environment discovery, dependency installation or cleanup.
The adapter gate remains closed until the complete I group is accepted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import select
import selectors
import signal
import socket
import subprocess
import tempfile
import time
from contextlib import ExitStack
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
SUPPORT = PROJECT / "tests/stock_suspend_confirmed_test_support.py"
TEST = PROJECT / "tests/test_stock_suspend_confirmed_isolation.py"
SOURCE = PROJECT / "src/orchestrator"
ISOLATION_BATCHES = (
    ("I03-I04", 16, (
        "test_i03_actual_resource_root", "test_i03_factory_rejects_before_path_io",
        "test_i03_detects_real_resource_default_without_io", "test_i04_input_path_preflight",
    )),
    ("I05", 14, (
        "test_i05_real_duckdb_resource", "test_i05_rejects_wrong_effective_setting",
        "test_i05_rejects_bad_connection_arguments", "test_i05_rejects_formal_connection_entry",
    )),
    ("I06", 16, (
        "test_i06_real_instance_persistence", "test_i06_rejects_local_instance_arguments",
        "test_i06_rejects_instance_discovery", "test_i06_python_network_guard",
        "test_i06_native_network_denial",
    )),
)
# Actual import closure of resources.py, not permission for all defs or CSV data.
RESOURCE_SOURCE_FILES = (
    "__init__.py", "defs/__init__.py", "defs/resources.py",
    "defs/duckdb_connection.py", "defs/paths.py", "defs/tushare_request_policy.py",
    "defs/health/__init__.py", "defs/health/lake_root.py",
    "defs/notifications/__init__.py", "defs/notifications/feishu.py",
    "defs/run_contracts/__init__.py", "defs/run_contracts/etf_basic.py",
    "defs/run_contracts/etf_daily.py", "defs/run_contracts/etf_mins.py",
    "defs/run_contracts/idx_factor_pro.py", "defs/run_contracts/index_mins.py",
    "defs/run_contracts/major_index_mins.py",
    "defs/run_contracts/major_index_mins_technical.py",
    "defs/run_contracts/major_index_nineturn.py", "defs/run_contracts/qfq_nineturn.py",
    "defs/run_contracts/stk_mins.py", "defs/run_contracts/configs.py",
    "defs/run_contracts/cn_a_derived_minute_bars.py",
    "seeds/__init__.py", "seeds/market/__init__.py", "seeds/market/major_indices.py",
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def policy_for(root: Path) -> str:
    """Allow exact source files and import directory objects, never repo subtrees."""
    package_init = PROJECT / "tests/__init__.py"
    if package_init.is_symlink() or package_init.read_bytes() != b"\n":
        raise RuntimeError("tests_package_init_changed: re-audit before importing")
    try:
        (PROJECT / "__init__.py").lstat()
    except FileNotFoundError:
        pass
    else:
        raise RuntimeError("project_package_marker_present: re-audit before importing")
    source_files = [SOURCE / name for name in RESOURCE_SOURCE_FILES]
    files = [*source_files, SUPPORT, TEST, Path(__file__).resolve(), package_init]
    directories = {PROJECT, PROJECT / "src", PROJECT / "tests"}
    for path in source_files:
        directories.update(p for p in path.parents if p == SOURCE or SOURCE in p.parents)
    for path in files:
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"Source allowlist must contain regular files: {path}")
    literals = "\n".join(f"  (literal {json.dumps(str(p))})" for p in sorted(files + list(directories)))
    # The first block preserves the approved I01/I02 runtime/device permissions.
    return f'''(version 1)
(allow default)
(deny file-read* file-write* network*)
(allow file-read*
  (subpath "/System/Library") (subpath "/usr/lib") (subpath "/usr/share")
  (subpath "/Users/congming/miniconda3/bin")
  (subpath "/Users/congming/miniconda3/lib")
  (subpath "{PROJECT}/.venv")
  (literal "/dev/null") (literal "/dev/urandom") (literal "/"))
(allow file-write-data (literal "/dev/null"))
(allow file-read* file-write* (subpath "{root}/allowed"))
(allow file-read-metadata
  (literal "/private") (literal "/private/tmp") (literal "/tmp")
  (literal "{root}"))
(allow file-read*
{literals})
(allow file-read-metadata (literal "{PROJECT}/__init__.py"))
'''


def inventory(directory: Path) -> list[dict]:
    result = []
    for path in sorted(directory.rglob("*")):
        st = path.lstat()
        result.append({
            "path": str(path.relative_to(directory)), "dev": st.st_dev,
            "inode": st.st_ino, "mode": st.st_mode, "size": st.st_size,
            "mtime_ns": st.st_mtime_ns,
            "sha256": digest(path) if path.is_file() and not path.is_symlink() else None,
        })
    return result


def run_isolation_batch(batch: str, expected_count: int, case_names: tuple[str, ...]) -> int:
    root = Path(tempfile.mkdtemp(prefix="stock-suspend-isolated-", dir="/private/tmp"))
    allowed, denied = root / "allowed", root / "denied-fixture"
    allowed.mkdir()
    denied.mkdir()
    with ExitStack() as endpoints:
        listeners = {}
        if batch == "I06":
            for kind, family in (("tcp", socket.AF_INET), ("unix", socket.AF_UNIX)):
                listener = endpoints.enter_context(socket.socket(family, socket.SOCK_STREAM))
                listener.settimeout(1)
                listener.bind(("127.0.0.1", 0) if kind == "tcp" else str(allowed / "network.sock"))
                listener.listen(1)
                listeners[kind] = listener
        return run_isolation_child(root, batch, expected_count, case_names, listeners)


def verify_parent_network_endpoints(listeners: dict) -> dict:
    """A live synthetic endpoint control, not a service or a database probe."""
    observed = {}
    for kind, listener in listeners.items():
        if select.select([listener], [], [], 0)[0]:
            raise RuntimeError(f"unexpected_child_network_connection:{kind}")
        with socket.socket(listener.family, socket.SOCK_STREAM) as client:
            client.settimeout(1)
            client.connect(listener.getsockname())
            with listener.accept()[0] as accepted:
                accepted.settimeout(1)
                client.sendall(b"x")
                assert accepted.recv(1) == b"x"
                accepted.sendall(b"y")
                assert client.recv(1) == b"y"
        observed[kind] = {"reachable": True, "request_bytes": 1, "response_bytes": 1}
    return observed


def run_isolation_child(root: Path, batch: str, expected_count: int,
                        case_names: tuple[str, ...], listeners: dict) -> int:
    allowed, denied = root / "allowed", root / "denied-fixture"
    network_targets = {kind: listener.getsockname() for kind, listener in listeners.items()}
    network_before = verify_parent_network_endpoints(listeners)
    (denied / "sentinel.txt").write_text("synthetic denied resource fixture\n")
    policy = allowed / "capability.sb"
    policy.write_text(policy_for(root))
    bootstrap = allowed / "bootstrap.py"
    bootstrap.write_text(
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('stock_suspend_confirmed_test_support', {str(SUPPORT)!r})\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "sys.modules[spec.name] = module\n"
        "spec.loader.exec_module(module)\n"
        f"raise SystemExit(module.run({str(root)!r}, {digest(policy)!r}, {str(TEST)!r}, "
        f"batch={batch!r}, case_names={case_names!r}, expected_count={expected_count!r}, "
        f"network_targets={network_targets!r}))\n"
    )
    argv = [
        "/opt/homebrew/bin/uv", "run", "--offline", "--no-sync", "--no-env-file",
        "--no-config", "--no-python-downloads", "--cache-dir", str(allowed / "uv-cache"),
        "/usr/bin/sandbox-exec", "-f", str(policy), str(PROJECT / ".venv/bin/python"),
        "-I", "-B", str(bootstrap),
    ]
    env = {"PATH": "/opt/homebrew/bin:/usr/bin:/bin", "LANG": "en_US.UTF-8",
           "TMPDIR": str(allowed), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    before = inventory(denied)
    started = time.monotonic()
    report = {
        "scope": "isolation", "implemented_slice": batch, "all_isolation_accepted": False,
        "case_names": list(case_names), "expected_count": expected_count,
        "network_targets": network_targets, "network_before": network_before,
        "root": str(root), "cwd": str(PROJECT), "argv": argv, "env_keys": sorted(env),
        "policy_sha256": digest(policy), "policy": policy.read_text(),
        "test_source_sha256": {str(p): digest(p) for p in (Path(__file__), SUPPORT, TEST)},
        "source_files": list(RESOURCE_SOURCE_FILES),
        "before": before, "passed": False,
    }
    report_path = allowed / "resource-result.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"starting": True, **report}), flush=True)
    process = subprocess.Popen(argv, cwd=PROJECT, env=env, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               close_fds=True, start_new_session=True)
    outputs = {"stdout": bytearray(), "stderr": bytearray()}
    stop_reason = None
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        while selector.get_map():
            if stop_reason is None:
                if time.monotonic() - started > 60:
                    stop_reason = "batch_timeout_60s"
                elif sum(p.lstat().st_size for p in root.rglob("*") if p.is_file()) > 100 * 1024**2:
                    stop_reason = "workspace_budget_100MiB"
                if stop_reason and process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
            for key, _ in selector.select(0.1):
                data = os.read(key.fileobj.fileno(), 8192)
                if not data:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                if len(outputs[key.data]) + len(data) > 65536:
                    if stop_reason is None:
                        stop_reason = f"{key.data}_budget_64KiB"
                        if process.poll() is None:
                            os.killpg(process.pid, signal.SIGKILL)
                else:
                    outputs[key.data].extend(data)
                    print(data.decode(errors="replace"), end="", flush=True)
    code = process.wait(timeout=5)
    network_after = verify_parent_network_endpoints(listeners)
    after = inventory(denied)
    result = allowed / "pytest-result.json"
    observed = json.loads(result.read_text()) if result.is_file() else None
    passed = code == 0 and stop_reason is None and before == after and observed is not None
    passed = passed and observed.get("passed") is True and observed.get("completed") == expected_count
    report.update({"passed": passed, "after": after, "denied_unchanged": before == after,
                   "network_after": network_after,
                   "exit_code": code, "stop_reason": stop_reason, "pytest": observed,
                   "elapsed_ms": round(1000 * (time.monotonic() - started)),
                   **{name: data.decode(errors="replace") for name, data in outputs.items()}})
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"batch": batch, "passed": passed, "report": str(report_path)}), flush=True)
    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("isolation", "adapter"), required=True)
    args = parser.parse_args()
    if args.scope != "isolation":
        parser.error("adapter is not accepted: complete I07-I08 and independent review first")
    if Path.cwd() != PROJECT:
        parser.error(f"Run from {PROJECT}")
    for batch, expected_count, case_names in ISOLATION_BATCHES:
        if run_isolation_batch(batch, expected_count, case_names) != 0:
            return 1
    print(json.dumps({"I03_I04_I05_I06_passed": True, "all_isolation_accepted": False}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
