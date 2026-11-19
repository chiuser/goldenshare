"""Exercise the local launcher without installing dependencies or opening ports."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "local-build-and-run.sh"


@pytest.fixture
def launcher(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = Path(shutil.copyfile(SCRIPT, scripts / SCRIPT.name))
    (tmp_path / "frontend" / "node_modules").mkdir(parents=True)
    env_file = tmp_path / "web.env"
    env_file.touch()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    listener = tmp_path / "listener"
    stub = bin_dir / "python3"
    stub.write_text(
        """#!/bin/bash
if [[ "$1" == "-" ]]; then
  [[ -e "$TEST_LISTENER" ]]
  exit $?
fi
echo 'test child spawned'
if [[ "$TEST_MODE" == "ready" ]]; then
  sleep 2.5
  echo 'test listener ready'
  touch "$TEST_LISTENER"
  sleep 2
fi
if [[ "$TEST_MODE" == "early-zero" ]]; then
  exit 0
fi
exit 7
""",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    (bin_dir / "npm").symlink_to(stub)

    def run(mode, service):
        if mode == "occupied":
            listener.touch()
        return subprocess.run(
            ["bash", str(script), f"--{service}-only", "--env-file", str(env_file),
             "--skip-backend-compile", "--skip-frontend-build"],
            env={**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                 "TEST_LISTENER": str(listener), "TEST_MODE": mode, "RUN_PREFLIGHT": "0",
                 "INSTALL_PY_DEPS": "0", "INSTALL_FE_DEPS": "0"},
            capture_output=True, text=True, timeout=12,
        )

    return run


@pytest.mark.parametrize("service,name", [("web", "Web"), ("frontend", "Frontend")])
def test_waits_for_listener_then_propagates_child_exit(launcher, service, name):
    result = launcher("ready", service)
    assert result.returncode == 7
    assert result.stdout.index("test listener ready") < result.stdout.index("已启动服务")
    assert f"{name} 进程已退出，状态码=7" in result.stdout


@pytest.mark.parametrize("mode,child_status,launcher_status", [("failed", 7, 7), ("early-zero", 0, 1)])
def test_startup_failure_is_not_reported_as_ready(launcher, mode, child_status, launcher_status):
    result = launcher(mode, "web")
    assert result.returncode == launcher_status
    assert f"Web 进程已退出，状态码={child_status}" in result.stdout
    assert "已启动服务" not in result.stdout


def test_occupied_port_does_not_start_a_child(launcher):
    result = launcher("occupied", "web")
    assert result.returncode == 1
    assert "Web 端口已在监听" in result.stdout
    assert "test child spawned" not in result.stdout
