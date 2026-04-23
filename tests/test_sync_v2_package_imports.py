from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_isolated_import(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_sync_v2_package_keeps_model_imports_cycle_free() -> None:
    result = _run_isolated_import(
        "import importlib; "
        "importlib.import_module('src.foundation.models.core.equity_factor_pro'); "
        "importlib.import_module('src.foundation.dao.factory'); "
        "print('ok')"
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_sync_v2_package_still_exports_service_lazily() -> None:
    result = _run_isolated_import(
        "from src.foundation.services.sync_v2 import SyncV2Service; "
        "print(SyncV2Service.__name__)"
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "SyncV2Service"
