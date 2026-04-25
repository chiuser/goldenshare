from __future__ import annotations

from pathlib import Path

from src.foundation.datasets.registry import list_dataset_definitions
from src.ops.specs.registry import JOB_SPEC_REGISTRY, WORKFLOW_SPEC_REGISTRY


REPO_ROOT = Path(__file__).resolve().parents[2]
ACTIVE_CODE_ROOTS = (
    REPO_ROOT / "src/foundation",
    REPO_ROOT / "src/ops",
    REPO_ROOT / "src/app",
    REPO_ROOT / "src/cli.py",
    REPO_ROOT / "src/cli_parts",
    REPO_ROOT / "frontend/src",
    REPO_ROOT / "frontend/e2e/support",
)


def _python_and_frontend_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    suffixes = {".py", ".ts", ".tsx", ".js"}
    return [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and path.suffix in suffixes
        and "__pycache__" not in path.parts
    ]


def test_active_code_does_not_reference_legacy_dataset_execution_names() -> None:
    forbidden_tokens = (
        "sync" + "_daily",
        "sync" + "_history",
        "sync" + "_minute_history",
        "backfill" + "_",
        "History" + "BackfillService",
        "history" + "_backfill_service",
    )
    violations: list[str] = []
    for root in ACTIVE_CODE_ROOTS:
        for path in _python_and_frontend_files(root):
            text = path.read_text(encoding="utf-8")
            for token in forbidden_tokens:
                if token in text:
                    rel_path = path.relative_to(REPO_ROOT).as_posix()
                    violations.append(f"{rel_path}: {token}")

    assert not violations, "旧数据集执行模型不得回到活跃代码:\n" + "\n".join(violations)


def test_workflows_and_job_specs_only_use_dataset_actions_or_maintenance_jobs() -> None:
    dataset_keys = {definition.dataset_key for definition in list_dataset_definitions()}
    assert set(JOB_SPEC_REGISTRY) == {
        "maintenance.rebuild_dm",
        "maintenance.rebuild_index_kline_serving",
    }

    for workflow in WORKFLOW_SPEC_REGISTRY.values():
        for step in workflow.steps:
            if step.job_key.startswith("maintenance."):
                assert step.job_key in JOB_SPEC_REGISTRY
                continue
            assert step.job_key.endswith(".maintain")
            assert step.job_key.removesuffix(".maintain") in dataset_keys


def test_ingestion_layer_has_no_checkpoint_or_acquire_semantics() -> None:
    root = REPO_ROOT / "src/foundation/ingestion"
    forbidden_tokens = ("checkpoint", "acquire(")
    violations: list[str] = []
    for path in _python_and_frontend_files(root):
        text = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            if token in text:
                rel_path = path.relative_to(REPO_ROOT).as_posix()
                violations.append(f"{rel_path}: {token}")

    assert not violations, "本轮未规划 checkpoint/acquire 续跑语义，不得引入:\n" + "\n".join(violations)
