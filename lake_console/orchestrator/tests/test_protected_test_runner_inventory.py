"""Test resource boundaries without registering every governance source file."""

import importlib.util
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def runner():
    path = Path(__file__).with_name("stock_suspend_confirmed_test_runner.py")
    spec = importlib.util.spec_from_file_location("protected_runner_inventory", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "scope", ["isolation", "adapter", "regression", "root-guard"]
)
def test_each_explicit_source_permission_still_names_a_regular_file(runner, scope):
    paths = [runner.SOURCE / name for name in runner.source_files_for_scope(scope)]
    invalid = [str(path) for path in paths if not path.is_file() or path.is_symlink()]
    assert invalid == []


def test_consumer_no_longer_inventories_source_files(runner, monkeypatch, tmp_path):
    # The tests discover defs independently. Source access must not require a
    # duplicate list, a new-file registration or an inventory/hash pass.
    assert not hasattr(runner, "CONSUMER_SOURCE_FILES")
    assert runner.source_files_for_scope("consumer") == ()

    def forbidden(*args, **kwargs):
        pytest.fail("consumer policy must not inventory or hash source files")

    digest = runner.digest

    def no_source_digest(path):
        if path.is_relative_to(runner.SOURCE):
            forbidden()
        return digest(path)

    monkeypatch.setattr(Path, "rglob", forbidden)
    monkeypatch.setattr(runner, "digest", no_source_digest)
    policy = runner.policy_for(tmp_path, scope="consumer")
    grant = f"(allow file-read* (subpath {json.dumps(str(runner.SOURCE))}))"
    assert grant in policy
    assert f"(subpath {json.dumps(str(runner.PROJECT))})" not in policy
    assert "(deny file-read* file-write* network*)" in policy


def test_new_consumer_source_is_readable_but_external_resources_are_not(
    runner, monkeypatch, tmp_path
):
    # The actual macOS policy is the boundary under test; all resources below
    # are synthetic. No production Lake, instance, credentials or service is used.
    source = tmp_path / "source"
    source.mkdir()
    root = tmp_path / "test-run"
    allowed = root / "allowed"
    allowed.mkdir(parents=True)
    denied = tmp_path / "outside.txt"
    denied.write_text("unchanged outside source")
    (source / "outside-link.py").symlink_to(denied)
    monkeypatch.setattr(runner, "SOURCE", source)
    policy = allowed / "test.sb"
    policy.write_text(runner.policy_for(root, scope="consumer"))
    # Create this file AFTER constructing the policy: no inventory can know it.
    new_source = source / "new_sensor.py"
    new_source.write_text("answer = 42\n")

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        program = """
import errno, json, socket
from pathlib import Path
source, outside, allowed = map(Path, __import__('sys').argv[1:4])
address = ('127.0.0.1', int(__import__('sys').argv[4]))
assert (source / 'new_sensor.py').read_text() == 'answer = 42\\n'
(allowed / 'result.txt').write_text('temporary output allowed')
checks = {
    'outside_read': lambda: outside.read_text(),
    'outside_link_read': lambda: (source / 'outside-link.py').read_text(),
    'source_write': lambda: (source / 'new_sensor.py').write_text('wrong'),
    'outside_write': lambda: outside.write_text('wrong'),
}
with socket.socket() as client:
    checks['network'] = lambda: client.connect(address)
    for name, operation in checks.items():
        try:
            operation()
        except OSError as error:
            assert error.errno in (errno.EPERM, errno.EACCES), (name, error)
        else:
            raise AssertionError(name + ' unexpectedly allowed')
print(json.dumps({'source_read': True, 'denied': sorted(checks)}))
"""
        result = subprocess.run(
            [
                "/usr/bin/sandbox-exec", "-f", str(policy), sys.executable,
                "-I", "-B", "-c", program,
                str(source), str(denied), str(allowed),
                str(listener.getsockname()[1]),
            ],
            capture_output=True, text=True, check=True, timeout=10,
            env={"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8"},
        )
    assert json.loads(result.stdout) == {
        "source_read": True,
        "denied": [
            "network", "outside_link_read", "outside_read",
            "outside_write", "source_write",
        ],
    }
    assert new_source.read_text() == "answer = 42\n"
    assert denied.read_text() == "unchanged outside source"
    assert (allowed / "result.txt").read_text() == "temporary output allowed"


@pytest.mark.parametrize("kind", ["missing", "symlink"])
def test_policy_still_rejects_missing_or_symlink_source_before_runtime_access(
    runner, tmp_path, kind
):
    source = tmp_path / "source"
    source.mkdir()
    target = source / "module.py"
    if kind == "symlink":
        actual = tmp_path / "actual.py"
        actual.write_text("value = 1\n")
        target.symlink_to(actual)
    runner.SOURCE = source
    runner.RESOURCE_SOURCE_FILES = ("module.py",)

    def forbidden_runtime_access():
        pytest.fail("source rejection must precede runtime policy construction")

    runner.runtime_environment_identity = forbidden_runtime_access
    with pytest.raises(
        RuntimeError, match="Source allowlist must contain regular files"
    ):
        runner.policy_for(tmp_path, scope="isolation")
