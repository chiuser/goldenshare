"""Early protection for the confirmed-suspension tests, initially the I03 slice.

Only stdlib at import time. No resource or pytest import before the OS self-check.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import signal
import sys
import time
from pathlib import Path

_allowed: Path | None = None
_completed = 0
_failures = 0
_started = 0.0


def require_isolated_context() -> Path:
    if _allowed is None:
        raise RuntimeError("isolation_not_initialized_before_collection")
    return _allowed


def checked_test_path(path: Path, *, allowed: Path) -> Path:
    """Reject lexical escapes before any path IO; never repair a path."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts or not path.is_relative_to(allowed):
        raise ValueError("outside_test_root")
    current = allowed
    for part in ("", *path.relative_to(allowed).parts):
        current = current / part
        if current.is_symlink():
            raise ValueError("symlink_not_allowed")
    return path


def verify_lake_resource(resource, *, expected_root: Path) -> None:
    allowed = require_isolated_context()
    # root() itself only constructs a Path. Verify it before any stat, mkdir or probe.
    actual = resource.root()
    if actual != expected_root or not actual.is_relative_to(allowed):
        raise ValueError("resource_root_mismatch")


def make_confirmed_test_resources(*, lake_root: Path, work_root: Path) -> dict:
    """I03: construct and verify the real Lake resource. No **kwargs or defaults."""
    allowed = require_isolated_context()
    if Path(work_root) != allowed:
        raise ValueError("work_root_mismatch")
    checked = checked_test_path(lake_root, allowed=allowed)
    from orchestrator.defs.resources import LakeRootResource

    resource = LakeRootResource(root_path=str(checked))
    verify_lake_resource(resource, expected_root=checked)
    return {"lake_root": resource}


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


def run(root_name: str, policy_hash: str, test_name: str) -> int:
    global _allowed
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
    import pytest

    test_directory = str(Path(test_name).parent)
    args = ["-c", "/dev/null", "--rootdir", test_directory, "--confcutdir", test_directory,
            "--ignore-glob", str(Path(test_directory) / "*"),
            "--noconftest", "-p", "no:cacheprovider",
            "--import-mode=importlib", "--basetemp", str(allowed / "pytest"),
            "-x", "-v", "-s", test_name]
    print(json.dumps({"pytest_argv": args, "implemented_slice": "I03"}), flush=True)
    result = int(pytest.main(args, plugins=[sys.modules[__name__]]))
    (allowed / "pytest-result.json").write_text(json.dumps({
        "slice": "I03", "completed": _completed, "failures": _failures,
        "passed": result == 0 and _completed == 8 and _failures == 0,
    }) + "\n")
    return result
