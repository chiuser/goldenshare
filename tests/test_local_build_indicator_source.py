"""Check which indicator package the local Web and its preflight import."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


LAUNCHER = Path(__file__).resolve().parents[1] / "scripts" / "local-build-and-run.sh"


@pytest.mark.parametrize("inherit_pythonpath", [False, True])
def test_local_launcher_uses_the_current_checkout(tmp_path, inherit_pythonpath):
    checkout = tmp_path / "current checkout"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    launcher = Path(shutil.copyfile(LAUNCHER, scripts / LAUNCHER.name))
    (checkout / ".env.web.local").touch()

    source = checkout / "packages" / "technical_indicators" / "src"
    stale = tmp_path / "old package"
    for directory in (source, stale):
        package = directory / "goldenshare_technical_indicators"
        package.mkdir(parents=True)
        (package / "__init__.py").touch()

    probe = tmp_path / "probe.py"
    probe.write_text(
        """import os
import sys

sys.path.append(os.environ["TEST_INSTALLED_PACKAGE"])
import goldenshare_technical_indicators as package

print(f"{sys.argv[1]}: {package.__file__}")
print(f"{sys.argv[1]} path: {os.environ.get('PYTHONPATH', '')}")
""",
        encoding="utf-8",
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    python = bin_dir / "python3"
    python.write_text(
        """#!/bin/bash
if [[ "$1" == "-" ]]; then
  exit 1
fi
if [[ "$1" == "-m" && "$2" == "src.app.web.run" ]]; then
  "$TEST_PYTHON" -B "$TEST_PROBE" web
  exit 7
fi
exit 8
""",
        encoding="utf-8",
    )
    python.chmod(0o755)
    (scripts / "release-preflight.sh").write_text(
        '"$TEST_PYTHON" -B "$TEST_PROBE" preflight\n', encoding="utf-8",
    )
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "ENV_FILE": ".env.web.local",
        "TEST_PYTHON": sys.executable,
        "TEST_PROBE": str(probe),
        "TEST_INSTALLED_PACKAGE": str(stale),
        "INSTALL_PY_DEPS": "0",
        "INSTALL_FE_DEPS": "0",
    }
    if inherit_pythonpath:
        env["PYTHONPATH"] = str(stale)
        expected_pythonpath = f"{source}{os.pathsep}{stale}"
    else:
        env.pop("PYTHONPATH", None)
        expected_pythonpath = str(source)

    result = subprocess.run(
        ["bash", str(launcher), "--web-only", "--skip-backend-compile", "--with-preflight"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    for step in ("preflight", "web"):
        assert f"{step}: {source / 'goldenshare_technical_indicators' / '__init__.py'}" in result.stdout
        assert f"{step} path: {expected_pythonpath}\n" in result.stdout
