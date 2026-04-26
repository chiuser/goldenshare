from __future__ import annotations

from pathlib import Path

from src.foundation.datasets.registry import get_dataset_definition_by_action_key
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
        "sync" + "_v2",
        "Sync" + "V2",
        "Dataset" + "Sync" + "Contract",
        "get_" + "sync" + "_v2" + "_contract",
        "build_" + "sync" + "_service",
        "sync" + "_run" + "_log",
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
            definition, action = get_dataset_definition_by_action_key(step.job_key)
            assert action == "maintain"
            assert definition.dataset_key in dataset_keys


def test_frontend_does_not_assemble_dataset_display_facts_from_keys() -> None:
    forbidden_tokens = (
        "formatSpecDisplayLabel",
        "formatResourceLabel",
        "formatProgressMessageLabel",
        "primary_execution_spec_key",
        "route_spec_keys",
    )
    violations: list[str] = []
    for root in (REPO_ROOT / "frontend/src",):
        for path in _python_and_frontend_files(root):
            text = path.read_text(encoding="utf-8")
            for token in forbidden_tokens:
                if token in text:
                    rel_path = path.relative_to(REPO_ROOT).as_posix()
                    violations.append(f"{rel_path}: {token}")

    assert not violations, "前端不得通过旧字段或本地 key 映射拼装事实字段:\n" + "\n".join(violations)


def test_ops_does_not_parse_dataset_identity_from_spec_key_text() -> None:
    forbidden_snippets = (
        'split(".", 1)[1]',
        "partition(\".\")",
        "partition('.')",
    )
    violations: list[str] = []
    for path in _python_and_frontend_files(REPO_ROOT / "src/ops"):
        text = path.read_text(encoding="utf-8")
        for snippet in forbidden_snippets:
            if snippet in text:
                rel_path = path.relative_to(REPO_ROOT).as_posix()
                violations.append(f"{rel_path}: {snippet}")

    assert not violations, "Ops 不得从 spec_key 文本拆出 dataset identity，必须走 DatasetDefinition registry:\n" + "\n".join(violations)


def test_ops_dataset_card_view_static_facts_do_not_depend_on_pipeline_mode_view() -> None:
    path = REPO_ROOT / "src/ops/queries/dataset_card_query_service.py"
    text = path.read_text(encoding="utf-8")
    forbidden_tokens = (
        "DatasetPipelineModeQueryService",
        "DatasetPipelineModeItem",
        "dataset_pipeline_mode_query_service",
    )
    violations = [token for token in forbidden_tokens if token in text]

    assert not violations, (
        "dataset-cards 是页面卡片事实接口，静态事实必须从 DatasetDefinition 派生，"
        "不得再消费 pipeline-modes 查询视图:\n" + "\n".join(violations)
    )


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
