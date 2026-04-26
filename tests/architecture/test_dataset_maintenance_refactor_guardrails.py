from __future__ import annotations

from pathlib import Path

from src.ops.action_catalog import MAINTENANCE_ACTION_REGISTRY, WORKFLOW_DEFINITION_REGISTRY
from src.foundation.datasets.registry import get_dataset_definition_by_action_key
from src.foundation.datasets.registry import list_dataset_definitions


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


def test_active_code_does_not_reference_legacy_schedule_contract_names() -> None:
    forbidden_tokens = (
        "spec_" + "type",
        "spec_" + "key",
        "spec_" + "display_name",
        "Job" + "Schedule",
        "job_" + "schedule",
        "create_from_" + "spec",
        "system_" + "job",
    )
    violations: list[str] = []
    for root in ACTIVE_CODE_ROOTS:
        for path in _python_and_frontend_files(root):
            text = path.read_text(encoding="utf-8")
            for token in forbidden_tokens:
                if token in text:
                    rel_path = path.relative_to(REPO_ROOT).as_posix()
                    violations.append(f"{rel_path}: {token}")

    assert not violations, "自动任务调度不得恢复旧调度契约:\n" + "\n".join(violations)


def test_workflows_only_use_dataset_actions_or_maintenance_actions() -> None:
    dataset_keys = {definition.dataset_key for definition in list_dataset_definitions()}
    assert set(MAINTENANCE_ACTION_REGISTRY) == {
        "maintenance.rebuild_dm",
        "maintenance.rebuild_index_kline_serving",
    }

    for workflow in WORKFLOW_DEFINITION_REGISTRY.values():
        for step in workflow.steps:
            if step.action_key.startswith("maintenance."):
                assert step.action_key in MAINTENANCE_ACTION_REGISTRY
                continue
            definition, action = get_dataset_definition_by_action_key(step.action_key)
            assert action == "maintain"
            assert definition.dataset_key in dataset_keys


def test_frontend_does_not_assemble_dataset_display_facts_from_keys() -> None:
    forbidden_tokens = (
        "formatSpecDisplayLabel",
        "formatResourceLabel",
        "formatProgressMessageLabel",
        "primary_execution_" + "spec_" + "key",
        "route_" + "spec_" + "keys",
    )
    forbidden_snippets = (
        "display_name || item." + "detail_dataset_key",
        "display_name || item." + "dataset_key",
        "display_name || item." + "resource_key",
        "display_name ?? item." + "detail_dataset_key",
        "display_name ?? item." + "dataset_key",
        "display_name ?? item." + "resource_key",
        "target_display_name || item." + "key",
        "resource_display_name || item." + "resource_key",
    )
    violations: list[str] = []
    for root in (REPO_ROOT / "frontend/src",):
        for path in _python_and_frontend_files(root):
            text = path.read_text(encoding="utf-8")
            for token in forbidden_tokens:
                if token in text:
                    rel_path = path.relative_to(REPO_ROOT).as_posix()
                    violations.append(f"{rel_path}: {token}")
            for snippet in forbidden_snippets:
                if snippet in text:
                    rel_path = path.relative_to(REPO_ROOT).as_posix()
                    violations.append(f"{rel_path}: {snippet}")

    assert not violations, "前端不得通过旧字段或本地 key 映射拼装事实字段:\n" + "\n".join(violations)


def test_ops_does_not_parse_dataset_identity_from_route_key_text() -> None:
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

    assert not violations, "Ops 不得从路由 key 文本拆出 dataset identity，必须走 DatasetDefinition registry:\n" + "\n".join(violations)


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


def test_active_code_does_not_reference_dataset_pipeline_mode_fact_table() -> None:
    forbidden_tokens = (
        "dataset_" + "pipeline_mode",
        "Dataset" + "PipelineMode",
        "pipeline-" + "modes",
    )
    violations: list[str] = []
    for root in ACTIVE_CODE_ROOTS:
        for path in _python_and_frontend_files(root):
            text = path.read_text(encoding="utf-8")
            for token in forbidden_tokens:
                if token in text:
                    rel_path = path.relative_to(REPO_ROOT).as_posix()
                    violations.append(f"{rel_path}: {token}")

    assert not violations, "旧 dataset_pipeline_mode / pipeline-modes 事实链不得留在活跃代码:\n" + "\n".join(violations)


def test_active_code_does_not_reference_old_freshness_fact_chain() -> None:
    forbidden_tokens = (
        "Dataset" + "Freshness" + "Spec",
        "DATASET" + "_FRESHNESS" + "_SPEC" + "_REGISTRY",
        "get_" + "dataset" + "_freshness" + "_spec",
        "list_" + "dataset" + "_freshness" + "_specs",
        "dataset" + "_freshness" + "_spec",
    )
    violations: list[str] = []
    for root in ACTIVE_CODE_ROOTS:
        for path in _python_and_frontend_files(root):
            text = path.read_text(encoding="utf-8")
            for token in forbidden_tokens:
                if token in text:
                    rel_path = path.relative_to(REPO_ROOT).as_posix()
                    violations.append(f"{rel_path}: {token}")

    assert not violations, (
        "freshness 页面/查询/服务不得再消费 ops.specs 静态事实链，"
        "必须从 DatasetDefinition 派生 projection:\n" + "\n".join(violations)
    )


def test_active_code_does_not_reference_ops_specs_package() -> None:
    forbidden_tokens = (
        "src." + "ops." + "specs",
        "Job" + "Spec",
        "Workflow" + "Spec",
        "Parameter" + "Spec",
        "JOB" + "_SPEC" + "_REGISTRY",
        "WORKFLOW" + "_SPEC" + "_REGISTRY",
        "job_" + "specs",
        "workflow_" + "specs",
        "supported_" + "params",
        "job_" + "key",
    )
    violations: list[str] = []
    for root in ACTIVE_CODE_ROOTS:
        for path in _python_and_frontend_files(root):
            text = path.read_text(encoding="utf-8")
            for token in forbidden_tokens:
                if token in text:
                    rel_path = path.relative_to(REPO_ROOT).as_posix()
                    violations.append(f"{rel_path}: {token}")

    assert not violations, "活跃代码不得恢复旧 ops specs/catalog 事实链:\n" + "\n".join(violations)


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
