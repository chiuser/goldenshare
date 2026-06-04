from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_hook_module():
    module_path = Path(__file__).resolve().parents[1] / ".codex/hooks/pre_tool_use_policy.py"
    spec = importlib.util.spec_from_file_location("pre_tool_use_policy", module_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_lake_run_guard_does_not_treat_fullmatch_as_full_range() -> None:
    hook = _load_hook_module()

    findings = hook._detect_unbounded_lake_run(
        "apply_patch re.fullmatch " + "stk_" + "mins helper validation"
    )

    assert findings == []


def test_lake_run_guard_still_blocks_real_full_minutes_run() -> None:
    hook = _load_hook_module()

    findings = hook._detect_unbounded_lake_run(
        "lake-console "
        + "sync-"
        + "stk-"
        + "mins "
        + "full --start-date 2026-01-01 --end-date 2026-06-01"
    )

    assert any("分钟线/全市场/跨日期任务" in finding for finding in findings)
