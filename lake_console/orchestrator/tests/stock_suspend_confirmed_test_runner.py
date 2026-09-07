"""Task-local, stdlib-only launcher for I03-I08 isolation tests in fixed batches.

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
import sys
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
STARTUP_PROBES = (
    "guard_missing", "guard_late", "policy_missing", "policy_invalid", "policy_mismatch",
    "selfcheck_failed_stale", "collection_allowed", "collection_denied", "skip", "xfail",
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


def create_isolation_root() -> Path:
    root = Path(tempfile.mkdtemp(prefix="stock-suspend-isolated-", dir="/private/tmp"))
    allowed, denied = root / "allowed", root / "denied-fixture"
    allowed.mkdir()
    denied.mkdir()
    return root


def run_isolation_batch(batch: str, expected_count: int, case_names: tuple[str, ...]) -> int:
    root = create_isolation_root()
    allowed = root / "allowed"
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
                        case_names: tuple[str, ...], listeners: dict, *,
                        startup_probe: str | None = None, batch_deadline: float | None = None,
                        budget_roots: tuple[Path, ...] = ()) -> int:
    allowed, denied = root / "allowed", root / "denied-fixture"
    network_targets = {kind: listener.getsockname() for kind, listener in listeners.items()}
    network_before = verify_parent_network_endpoints(listeners)
    (denied / "sentinel.txt").write_text("synthetic denied resource fixture\n")
    policy = allowed / "capability.sb"
    policy.write_text(policy_for(root))
    bootstrap = allowed / "bootstrap.py"
    source = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('stock_suspend_confirmed_test_support', {str(SUPPORT)!r})\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "sys.modules[spec.name] = module\n"
        "spec.loader.exec_module(module)\n"
    )
    selected_policy = policy
    if startup_probe is None:
        source += (
            f"raise SystemExit(module.run({str(root)!r}, {digest(policy)!r}, {str(TEST)!r}, "
            f"batch={batch!r}, case_names={case_names!r}, expected_count={expected_count!r}, "
            f"network_targets={network_targets!r}))\n"
        )
    else:
        if startup_probe not in STARTUP_PROBES:
            raise ValueError("unknown_startup_probe")
        source = "print('I07_PAYLOAD_STARTED', flush=True)\n" + source
        fixture = prepare_startup_fixture(root, startup_probe)
        source += f"raise SystemExit(module.probe_startup_gate({startup_probe!r}, {str(root)!r}, {digest(policy)!r}, {str(fixture)!r}))\n"
        if startup_probe == "policy_missing":
            selected_policy = allowed / "missing.sb"
        elif startup_probe == "policy_invalid":
            selected_policy = allowed / "invalid.sb"
            selected_policy.write_text("(version 1)\n(I07_INVALID_PROFILE)\n")
        elif startup_probe == "selfcheck_failed_stale":
            (allowed / "pytest-result.json").write_text(json.dumps({
                "passed": True, "completed": 1, "failures": 0, "synthetic_stale": True,
            }) + "\n")
    bootstrap.write_text(source)
    argv = [
        "/opt/homebrew/bin/uv", "run", "--offline", "--no-sync", "--no-env-file",
        "--no-config", "--no-python-downloads", "--cache-dir", str(allowed / "uv-cache"),
        "/usr/bin/sandbox-exec", "-f", str(selected_policy), str(PROJECT / ".venv/bin/python"),
        "-I", "-B", str(bootstrap),
    ]
    env = {"PATH": "/opt/homebrew/bin:/usr/bin:/bin", "LANG": "en_US.UTF-8",
           "TMPDIR": str(allowed), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    before = inventory(denied)
    started = time.monotonic()
    report = {
        "scope": "isolation", "implemented_slice": batch, "all_isolation_accepted": False,
        "case_names": list(case_names), "expected_count": expected_count,
        "startup_probe": startup_probe,
        "expected_resource_gate": startup_probe in (None, "collection_allowed"),
        "network_targets": network_targets, "network_before": network_before,
        "root": str(root), "cwd": str(PROJECT), "argv": argv, "env_keys": sorted(env),
        "policy_sha256": digest(policy), "policy": policy.read_text(),
        "selected_policy": str(selected_policy),
        "selected_policy_text": selected_policy.read_text() if selected_policy.exists() else None,
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
                if batch_deadline is not None and time.monotonic() > batch_deadline:
                    stop_reason = "batch_timeout_60s"
                elif time.monotonic() - started > (30 if startup_probe else 60):
                    stop_reason = "case_timeout_30s" if startup_probe else "batch_timeout_60s"
                elif sum(p.lstat().st_size for directory in (budget_roots or (root,))
                         for p in directory.rglob("*") if p.is_file()) > 100 * 1024**2:
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
    resource_gate_passed = passed
    probe_evidence = None
    if startup_probe is not None:
        probe_evidence = evaluate_startup_probe(root, startup_probe, code, outputs, observed)
        passed = stop_reason is None and before == after and probe_evidence["passed"] \
            and resource_gate_passed == (startup_probe == "collection_allowed")
    report.update({"passed": passed, "resource_gate_passed": resource_gate_passed,
                   "startup_evidence": probe_evidence, "after": after, "denied_unchanged": before == after,
                   "network_after": network_after,
                   "exit_code": code, "stop_reason": stop_reason, "pytest": observed,
                   "elapsed_ms": round(1000 * (time.monotonic() - started)),
                   **{name: data.decode(errors="replace") for name, data in outputs.items()}})
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"batch": batch, "passed": passed, "report": str(report_path)}), flush=True)
    return 0 if passed else 1


def prepare_startup_fixture(root: Path, case: str) -> Path:
    """Create only fixed synthetic collection sources; never a business test."""
    if case not in ("collection_allowed", "collection_denied", "skip", "xfail"):
        return TEST
    allowed = root / "allowed"
    (allowed / "sentinel.txt").write_text("synthetic denied resource fixture\n")
    target = (root / "denied-fixture" if case == "collection_denied" else allowed) / "sentinel.txt"
    source = (
        "import json\nfrom pathlib import Path\nimport pytest\n"
        "from stock_suspend_confirmed_test_support import require_isolated_context\n"
        "allowed = require_isolated_context()\n"
        "(allowed / 'collection-entered.txt').write_text('synthetic')\n"
        f"target = Path({str(target)!r})\n"
        "try:\n    assert target.read_bytes() == b'synthetic denied resource fixture\\n'\n"
        "except OSError as error:\n"
        "    (allowed / 'collection-denial.json').write_text(json.dumps({'errno': error.errno, 'target': str(target)}))\n"
        "    raise\n"
        "(allowed / 'collection-finished.txt').write_text('synthetic')\n"
    )
    if case == "skip":
        source += "@pytest.mark.skip(reason='I07_synthetic_skip')\n"
    source += "def test_body():\n"
    if case == "xfail":
        source += "    pytest.xfail('I07_synthetic_xfail')\n"
    source += "    (allowed / 'test-body.txt').write_text('synthetic')\n"
    fixture = allowed / "test_startup_fixture.py"
    fixture.write_text(source)
    return fixture


def evaluate_startup_probe(root: Path, case: str, code: int, outputs: dict, observed) -> dict:
    import errno

    allowed = root / "allowed"
    stdout, stderr = (outputs[name].decode(errors="replace") for name in ("stdout", "stderr"))
    proof_path = allowed / "startup-proof.json"
    proof = json.loads(proof_path.read_text()) if proof_path.exists() else None
    if case.startswith("policy_") and case != "policy_mismatch":
        reason = (str(allowed / "missing.sb") in stderr and "No such file or directory" in stderr) \
            if case == "policy_missing" else "I07_INVALID_PROFILE" in stderr and "unbound variable" in stderr
        passed = code > 0 and reason and "I07_PAYLOAD_STARTED" not in stdout and proof is None and observed is None
    elif case in ("guard_missing", "guard_late", "policy_mismatch", "selfcheck_failed_stale"):
        reasons = {"guard_missing": "isolation_not_initialized_before_collection",
                   "guard_late": "protection_loaded_too_late", "policy_mismatch": "policy_mismatch",
                   "selfcheck_failed_stale": "synthetic_self_check_failed"}
        passed = code == 1 and proof is not None and proof.get("reason") == reasons[case] \
            and proof.get("context_initialized") is False \
            and proof.get("loaded_modules") == (["pytest"] if case == "guard_late" else [])
        passed = passed and (observed == {"passed": True, "completed": 1, "failures": 0, "synthetic_stale": True}
                             if case == "selfcheck_failed_stale" else observed is None)
    else:
        entered = (allowed / "collection-entered.txt").exists()
        finished = (allowed / "collection-finished.txt").exists()
        body = (allowed / "test-body.txt").exists()
        passed = entered and proof is not None and proof.get("business_modules") == [] and observed is not None
        if case == "collection_allowed":
            passed = passed and code == 0 and finished and body and observed.get("passed") is True \
                and observed.get("completed") == 1
        elif case == "collection_denied":
            denial_path = allowed / "collection-denial.json"
            denial = json.loads(denial_path.read_text()) if denial_path.exists() else {}
            passed = passed and code in (2, 4) and not finished and not body \
                and observed.get("passed") is False and observed.get("completed") == 0 \
                and denial.get("errno") in (errno.EPERM, errno.EACCES) \
                and denial.get("target") == str(root / "denied-fixture/sentinel.txt")
            proof = {**(proof or {}), "denial": denial}
        else:
            passed = passed and code == 0 and finished and not body and observed.get("passed") is False \
                and observed.get("completed") == 0 and observed.get("failures") == 1 \
                and ("1 skipped" if case == "skip" else "1 xfailed") in stdout
        proof = {**(proof or {}), "collection_entered": entered, "collection_finished": finished,
                 "test_body_executed": body}
    return {"passed": bool(passed), "case": case, "proof": proof}


def run_startup_gate_batch() -> int:
    import io
    from contextlib import redirect_stderr
    from unittest.mock import patch

    root = create_isolation_root()
    roots = [root]
    started = time.monotonic()
    results = []
    report_path = root / "allowed/startup-result.json"

    def save_report(passed=False):
        report_path.write_text(json.dumps({
            "slice": "I07", "passed": passed, "expected_count": 15, "completed": len(results),
            "elapsed_ms": round(1000 * (time.monotonic() - started)),
            "roots": [str(path) for path in roots], "results": results,
        }, indent=2) + "\n")

    save_report()
    for name, args, reason in (
        ("scope_missing", [], "required: --scope"),
        ("scope_value_missing", ["--scope"], "expected one argument"),
        ("scope_unknown", ["--scope", "unknown"], "invalid choice"),
        ("scope_adapter", ["--scope", "adapter"], "adapter is not accepted"),
        ("scope_extra", ["--scope", "isolation", "-k", "synthetic"], "unrecognized arguments"),
    ):
        errors = io.StringIO()
        with ExitStack() as guards:
            guards.enter_context(patch.object(sys, "argv", [str(Path(__file__)), *args]))
            guards.enter_context(redirect_stderr(errors))
            spies = [guards.enter_context(patch.object(owner, key, side_effect=AssertionError(key)))
                     for owner, key in ((tempfile, "mkdtemp"), (Path, "mkdir"), (subprocess, "Popen"))]
            try:
                main()
            except SystemExit as error:
                passed = error.code == 2 and reason in errors.getvalue() and not any(spy.called for spy in spies)
            else:
                passed = False
        results.append({"case": name, "passed": passed, "argv": args, "stderr": errors.getvalue(),
                        "mkdir_or_process_calls": sum(spy.call_count for spy in spies)})
        save_report()
        print(json.dumps(results[-1]), flush=True)
        if not passed:
            return 1
    for case in STARTUP_PROBES:
        if time.monotonic() - started > 60:
            save_report()
            return 1
        child_root = create_isolation_root()
        assert child_root not in roots
        roots.append(child_root)
        code = run_isolation_child(child_root, f"I07:{case}", 1, ("test_body",), {},
                                   startup_probe=case, batch_deadline=started + 60, budget_roots=tuple(roots))
        results.append({"case": case, "passed": code == 0,
                        "report": str(child_root / "allowed/resource-result.json")})
        save_report()
        if code:
            return 1
    save_report(passed=True)
    print(json.dumps({"batch": "I07", "passed": True, "completed": len(results), "report": str(report_path)}), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("isolation", "adapter"), required=True)
    args = parser.parse_args()
    if args.scope != "isolation":
        parser.error("adapter is not accepted: complete independent isolation review first")
    if Path.cwd() != PROJECT:
        parser.error(f"Run from {PROJECT}")
    for batch, expected_count, case_names in ISOLATION_BATCHES:
        if run_isolation_batch(batch, expected_count, case_names) != 0:
            return 1
    if run_startup_gate_batch() != 0:
        return 1
    if run_isolation_batch("I08", 3, (
        "test_i08_readonly_input_has_no_side_effects", "test_i08_health_probe_side_effects",
    )) != 0:
        return 1
    print(json.dumps({"I03_I04_I05_I06_I07_I08_passed": True,
                      "all_isolation_accepted": False, "independent_review_required": True}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
