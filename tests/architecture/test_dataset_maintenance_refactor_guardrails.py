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


def test_active_code_does_not_reference_legacy_dataset_run_names() -> None:
    forbidden_tokens = (
        "sync" + "_daily",
        "sync" + "_history",
        "sync" + "_minute_history",
        "back" + "fill" + "_",
        "sync" + "_v2",
        "Sync" + "V2",
        "Dataset" + "Sync" + "Contract",
        "get_" + "sync" + "_v2" + "_contract",
        "build_" + "sync" + "_service",
        "sync" + "_run" + "_log",
        "History" + "BackfillService",
        "history" + "_back" + "fill_service",
        "ingestion_" + "execution" + "_context",
        "Ingestion" + "Execution" + "Context",
        "Null" + "Execution" + "Context",
        "Null" + "Execution" + "ResultStore",
        "execution" + "_id",
        "triggered_" + "execution" + "_id",
        "created_" + "executions",
        "dataset_" + "execution",
        "execution_" + "summary",
        "record_" + "execution" + "_outcome",
        "execution" + "_failed",
        "execution" + "_canceled",
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


def test_active_code_does_not_persist_double_underscore_all_source_scope() -> None:
    forbidden_tokens = (
        '"' + "__" + "all__" + '"',
        "'" + "__" + "all__" + "'",
    )
    violations: list[str] = []
    for root in ACTIVE_CODE_ROOTS:
        for path in _python_and_frontend_files(root):
            text = path.read_text(encoding="utf-8")
            for token in forbidden_tokens:
                if token in text:
                    rel_path = path.relative_to(REPO_ROOT).as_posix()
                    violations.append(f"{rel_path}: {token}")

    assert not violations, "Ops 来源范围不得再使用双下划线 all 哨兵；持久化范围统一使用 combined:\n" + "\n".join(violations)


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


def test_task_run_dispatcher_does_not_hardcode_maintenance_action_facts() -> None:
    path = REPO_ROOT / "src/ops/runtime/task_run_dispatcher.py"
    text = path.read_text(encoding="utf-8")
    forbidden_tokens = (
        "maintenance.rebuild_dm",
        "maintenance.rebuild_index_kline_serving",
        "dm.equity_daily_snapshot",
        "core_serving.index_weekly_serving",
        "core_serving.index_monthly_serving",
    )
    violations = [token for token in forbidden_tokens if token in text]

    assert not violations, "维护动作事实必须来自 ActionCatalog，dispatcher 不得硬编码动作名或目标表:\n" + "\n".join(violations)


def test_frontend_does_not_assemble_dataset_display_facts_from_keys() -> None:
    forbidden_tokens = (
        "format" + "Spec" + "Display" + "Label",
        "format" + "Execution" + "Resource" + "Label",
        "format" + "Resource" + "Label",
        "format" + "Progress" + "Message" + "Label",
        "strip" + "Maintenance" + "Affix",
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
        "{item." + "dataset_key}</Text>",
        "{item." + "dataset_key}</Table.Td>",
        "{rule." + "dataset_key}",
        "function cadenceLabel",
        "sourceLabel(sourceKey",
        "item.raw_table_label || item.raw_table",
        "probe_config.source_key || \"全部来源\"",
        "return \"全部来源\"",
        'label: "全部来源"',
        "来源 {form.probe_source_key",
        "MetricPanel label={source}",
        "title={`${datasetKey} ·",
        "{entry." + "source_key}",
        "def _stage_label",
        "getDatasetLabelFromCatalog",
        "probe_config.workflow_dataset_keys || []).map",
        "(detailQuery.data.probe_config.workflow_dataset_keys || []).join",
        "buildFreshnessDisplayNameMap",
        "freshItem?.latest_success_at || rawLatest?.last_success_at",
        "function stageTitle",
        'const stageOrder = ["raw", "std", "resolution", "serving"]',
        "route_" + "keys",
        "active_" + "execution_" + "status",
        "active_" + "execution_" + "started_at",
        "recent_" + "executions",
        "total_" + "executions",
        "resourceKey.startsWith(\"biying_",
        "JSON.stringify(resolvedParamsJson",
        "内部规则：",
        "同步参数：",
        "未命名数据集",
        "未命名执行对象",
        "未指定来源",
        "未定义层级",
        "groupKey.split",
        "domain_key || item.domain_key",
        "domain_display_name || item.domain_display_name",
        'key: "spec"',
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


def test_ops_services_do_not_fallback_display_names_to_keys() -> None:
    forbidden_snippets = (
        "get_action_display_name(target_type, target_key) or target_key",
        "get_action_display_name(target_type=target_type, target_key=target_key) or target_key",
        "_fallback_display_name",
        "display_name or target_key",
        "display_name or resource_key",
    )
    violations: list[str] = []
    for path in _python_and_frontend_files(REPO_ROOT / "src/ops"):
        text = path.read_text(encoding="utf-8")
        for snippet in forbidden_snippets:
            if snippet in text:
                rel_path = path.relative_to(REPO_ROOT).as_posix()
                violations.append(f"{rel_path}: {snippet}")

    assert not violations, "Ops 服务不得把 key 当作展示名兜底，展示事实必须来自 Definition/ActionCatalog:\n" + "\n".join(violations)


def test_task_run_query_does_not_use_technical_unit_id_as_display_title() -> None:
    path = REPO_ROOT / "src/ops/queries/task_run_query_service.py"
    text = path.read_text(encoding="utf-8")

    assert '"unit_id"' not in text


def test_ingestion_progress_message_does_not_emit_machine_token_summary() -> None:
    path = REPO_ROOT / "src/foundation/ingestion/executor.py"
    text = path.read_text(encoding="utf-8")
    forbidden_tokens = (
        " fetched" + "=",
        " written" + "=",
        " committed" + "=",
        " rejected" + "=",
        "unit" + "_fetched" + "=",
        "unit" + "_written" + "=",
        "unit" + "_committed" + "=",
        "reason" + "_stats" + "_truncated" + "=",
    )
    violations = [token for token in forbidden_tokens if token in text]

    assert not violations, "Ingestion 进度摘要不得恢复英文机器 token:\n" + "\n".join(violations)


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


def test_schedule_dataset_task_uses_target_key_as_single_action_fact() -> None:
    path = REPO_ROOT / "src/ops/services/task_run_service.py"
    text = path.read_text(encoding="utf-8")
    forbidden_snippets = (
        'params_json.get("dataset_key")',
        'params_json.get("action") or action',
    )
    violations = [snippet for snippet in forbidden_snippets if snippet in text]

    assert not violations, "自动任务创建 TaskRun 时不得让 params_json 覆盖 target_key 解析出的数据集动作事实:\n" + "\n".join(violations)


def test_probe_rule_names_do_not_embed_dataset_keys() -> None:
    path = REPO_ROOT / "src/ops/services/schedule_probe_binding_service.py"
    text = path.read_text(encoding="utf-8")

    assert "{template.dataset_key}" not in text


def test_probe_trigger_payload_does_not_duplicate_dataset_action_facts() -> None:
    path = REPO_ROOT / "src/ops/services/schedule_probe_binding_service.py"
    text = path.read_text(encoding="utf-8")
    forbidden_snippets = (
        '"dataset_key": dataset_key',
        '"action": "maintain"',
    )
    violations = [snippet for snippet in forbidden_snippets if snippet in text]

    assert not violations, "探测触发配置已有 action_key，不得在 request 中重复固化 dataset/action 事实:\n" + "\n".join(violations)


def test_probe_runtime_does_not_infer_action_key_from_rule_dataset() -> None:
    path = REPO_ROOT / "src/ops/services/operations_probe_runtime_service.py"
    text = path.read_text(encoding="utf-8")

    assert "get_dataset_action_key(rule.dataset_key" not in text


def test_probe_runtime_messages_do_not_emit_raw_rows_machine_summary() -> None:
    path = REPO_ROOT / "src/ops/services/operations_probe_runtime_service.py"
    text = path.read_text(encoding="utf-8")

    assert "raw rows_in=" not in text
    assert "probe action_key is required" not in text


def test_manual_action_validation_messages_do_not_emit_field_token_english() -> None:
    path = REPO_ROOT / "src/ops/services/manual_action_service.py"
    text = path.read_text(encoding="utf-8")
    forbidden_snippets = (
        " is required",
        " must be YYYY",
        "start_date must",
        "start_month must",
        "Invalid integer filter",
        "Invalid option for",
        "Unsupported " + "time mode",
        "Unsupported " + "filter",
        "Manual action does not exist",
        "Manual workflow route is not configured",
        "Manual action resource route is not configured",
        "Manual action workflow route is not configured",
        "Unsupported manual action type",
    )
    violations = [snippet for snippet in forbidden_snippets if snippet in text]

    assert not violations, "手动任务参数校验不得向前端返回英文机器字段文案:\n" + "\n".join(violations)


def test_task_run_validation_messages_do_not_emit_internal_field_tokens() -> None:
    path = REPO_ROOT / "src/ops/services/task_run_service.py"
    text = path.read_text(encoding="utf-8")
    forbidden_snippets = (
        "resource_key is required",
        "Workflow is required",
        "Maintenance action is required",
        "Dataset definition does not exist",
        "Dataset action is not supported",
        "Unsupported task_type",
    )
    violations = [snippet for snippet in forbidden_snippets if snippet in text]

    assert not violations, "TaskRun API 校验不得向前端返回英文内部字段文案:\n" + "\n".join(violations)


def test_task_run_runtime_messages_do_not_emit_internal_field_tokens() -> None:
    paths = (
        REPO_ROOT / "src/ops/queries/task_run_query_service.py",
        REPO_ROOT / "src/ops/runtime/worker.py",
        REPO_ROOT / "src/ops/runtime/task_run_dispatcher.py",
    )
    forbidden_snippets = (
        "Task run does not exist",
        "Task run issue does not exist",
        "Only queued task runs can start immediately",
        "Task run status changed before",
        "Database bind is unavailable",
        "Snapshot refresh returned 0 rows",
        "Unsupported task_type",
        "Workflow does not exist",
        "Workflow step maintenance action does not exist",
        "Maintenance action does not exist",
        "resource_key is required",
        "materialized view refreshed",
        "start_date cannot be greater than end_date",
        "index serving rebuilt",
        "Unsupported maintenance executor",
        "Unsupported period granularity",
        "Invalid SQL identifier",
        "Maintenance action execution config is missing",
        "Maintenance action execution config has invalid",
        "Invalid date value",
    )
    violations: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for snippet in forbidden_snippets:
            if snippet in text:
                violations.append(f"{path.relative_to(REPO_ROOT).as_posix()}: {snippet}")

    assert not violations, "TaskRun 查询与运行时不得向前端返回英文内部字段文案:\n" + "\n".join(violations)


def test_probe_validation_messages_do_not_emit_internal_field_tokens() -> None:
    paths = (
        REPO_ROOT / "src/ops/services/probe_service.py",
        REPO_ROOT / "src/ops/queries/probe_query_service.py",
    )
    forbidden_snippets = (
        "Probe rule does not exist",
        "cannot be empty",
        "must be active/paused/disabled",
        "must be greater than 0",
        "Probe dataset display name is unavailable",
        "Probe source display name is unavailable",
    )
    violations: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for snippet in forbidden_snippets:
            if snippet in text:
                violations.append(f"{path.relative_to(REPO_ROOT).as_posix()}: {snippet}")

    assert not violations, "探测规则 API 校验不得向前端返回英文内部字段文案:\n" + "\n".join(violations)


def test_schedule_validation_messages_do_not_emit_internal_field_tokens() -> None:
    paths = (
        REPO_ROOT / "src/ops/services/operations_schedule_service.py",
        REPO_ROOT / "src/ops/services/schedule_planner.py",
        REPO_ROOT / "src/ops/queries/schedule_query_service.py",
        REPO_ROOT / "src/ops/services/schedule_probe_binding_service.py",
    )
    forbidden_snippets = (
        "Schedule does not exist",
        "display_name cannot be empty",
        "next_run_at is required",
        "cron_expr is required",
        "Unsupported schedule_type",
        "Unsupported target_type",
        "Unsupported trigger_mode",
        "Workflow does not exist",
        "Dataset action does not exist",
        "Unsupported maintenance action",
        "must include timezone information",
        "One-shot schedule requires",
        "Unable to resolve next_run_at",
        "cron_expr must contain",
        "Invalid cron",
        "Cron value out of range",
        "Probe source display name is unavailable",
        "Schedule target display name is unavailable",
        "Probe dataset display name is unavailable",
        "Probe schedules require dataset actions or workflows",
        "Unsupported schedule target_type for probe",
        "Invalid dataset action target_key",
        "Invalid workflow probe dataset_key",
    )
    violations: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for snippet in forbidden_snippets:
            if snippet in text:
                violations.append(f"{path.relative_to(REPO_ROOT).as_posix()}: {snippet}")

    assert not violations, "自动任务 API 校验不得向前端返回英文内部字段文案:\n" + "\n".join(violations)


def test_ops_dataset_card_view_static_facts_do_not_depend_on_retired_view() -> None:
    path = REPO_ROOT / "src/ops/queries/dataset_card_query_service.py"
    text = path.read_text(encoding="utf-8")
    forbidden_tokens = (
        "DatasetPipelineModeQueryService",
        "DatasetPipelineModeItem",
        "dataset_" + "pipeline_" + "mode_query_service",
    )
    violations = [token for token in forbidden_tokens if token in text]

    assert not violations, "dataset-cards 静态事实必须从 DatasetDefinition 派生:\n" + "\n".join(violations)


def test_ops_layer_stage_plan_is_not_rederived_in_consumers() -> None:
    path_tokens = {
        REPO_ROOT / "src/ops/queries/dataset_card_query_service.py": (
            "_expected_stages(delivery_mode",
            'delivery_mode == "single_source_serving"',
            'delivery_mode in {"raw_collection", "core_direct"}',
        ),
        REPO_ROOT / "src/ops/services/operations_dataset_status_snapshot_service.py": (
            "projection.raw_enabled",
            "projection.std_enabled",
            "projection.resolution_enabled",
            "projection.serving_enabled",
            "当前模式未启用 std 物化",
            "当前模式不产出 serving",
        ),
    }
    violations: list[str] = []
    for path, forbidden_tokens in path_tokens.items():
        text = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            if token in text:
                rel_path = path.relative_to(REPO_ROOT).as_posix()
                violations.append(f"{rel_path}: {token}")

    assert not violations, "layer stage 启用规则必须来自 DatasetDefinition projection，消费者不得按 delivery_mode 重推:\n" + "\n".join(violations)


def test_layer_snapshot_query_messages_do_not_emit_internal_field_tokens() -> None:
    path = REPO_ROOT / "src/ops/queries/layer_snapshot_query_service.py"
    text = path.read_text(encoding="utf-8")
    forbidden_snippets = (
        "Layer snapshot dataset display name is unavailable",
        "Layer snapshot source display name is unavailable",
        "Layer snapshot stage display name is unavailable",
    )
    violations = [snippet for snippet in forbidden_snippets if snippet in text]

    assert not violations, "层快照 API 校验不得向前端返回英文内部字段文案:\n" + "\n".join(violations)


def test_resolution_release_messages_do_not_emit_internal_field_tokens() -> None:
    paths = (
        REPO_ROOT / "src/ops/services/resolution_release_service.py",
        REPO_ROOT / "src/ops/queries/resolution_release_query_service.py",
    )
    forbidden_snippets = (
        "Resolution release does not exist",
        "items cannot be empty",
        "dataset_key cannot be empty",
        "target_policy_version must be greater than 0",
        "dataset_key is required in stage item",
        "stage is required in stage item",
        "status is required in stage item",
        "status must be previewing/running/completed/rolled_back/failed",
        "Resolution release dataset display name is unavailable",
        "Resolution release source display name is unavailable",
        "Resolution release stage display name is unavailable",
    )
    violations: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for snippet in forbidden_snippets:
            if snippet in text:
                violations.append(f"{path.relative_to(REPO_ROOT).as_posix()}: {snippet}")

    assert not violations, "数据发布 API 校验不得向前端返回英文内部字段文案:\n" + "\n".join(violations)


def test_workflow_domain_display_facts_stay_in_action_catalog() -> None:
    path_tokens = {
        REPO_ROOT / "src/ops/queries/catalog_query_service.py": (
            'domain_display_name="工作流"',
            'domain_key="workflow"',
        ),
        REPO_ROOT / "src/ops/schemas/catalog.py": (
            'domain_display_name: str = "工作流"',
            'domain_key: str = "workflow"',
        ),
        REPO_ROOT / "src/ops/queries/manual_action_query_service.py": (
            'GROUP_CONFIG["workflow"]',
            '("workflow", "工作流"',
        ),
        REPO_ROOT / "src/ops/services/task_run_service.py": (
            '"工作流维护"',
            '"系统维护"',
        ),
    }
    violations: list[str] = []
    for path, forbidden_tokens in path_tokens.items():
        text = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            if token in text:
                rel_path = path.relative_to(REPO_ROOT).as_posix()
                violations.append(f"{rel_path}: {token}")

    assert not violations, "workflow 领域与标题事实必须来自 ActionCatalog，消费者不得本地硬编码:\n" + "\n".join(violations)


def test_std_rule_queries_do_not_synthesize_default_rules() -> None:
    path = REPO_ROOT / "src/ops/queries/std_rule_query_service.py"
    text = path.read_text(encoding="utf-8")
    forbidden_tokens = (
        "_default_mapping_rules",
        "_default_cleansing_rules",
        "list_dataset_freshness_projections",
        "identity_pass_through",
        "builtin_default",
        'source_key="tushare"',
        "id=-(100000",
        "id=-(200000",
    )
    violations = [token for token in forbidden_tokens if token in text]

    assert not violations, "std rule 查询不得伪造默认规则；默认规则必须由 seed/写入链路落库后再查询:\n" + "\n".join(violations)


def test_std_rule_messages_do_not_emit_internal_field_tokens() -> None:
    paths = (
        REPO_ROOT / "src/ops/services/std_rule_service.py",
        REPO_ROOT / "src/ops/queries/std_rule_query_service.py",
    )
    forbidden_snippets = (
        "rule_set_version must be greater than 0",
        "rule_type cannot be empty",
        "action cannot be empty",
        "cannot be empty",
        "status must be active/disabled",
        "Std mapping rule does not exist",
        "Std cleansing rule does not exist",
        "Std rule dataset display name is unavailable",
        "Std rule source display name is unavailable",
    )
    violations: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for snippet in forbidden_snippets:
            if snippet in text:
                violations.append(f"{path.relative_to(REPO_ROOT).as_posix()}: {snippet}")

    assert not violations, "标准规则 API 校验不得向前端返回英文内部字段文案:\n" + "\n".join(violations)


def test_ops_dataset_card_view_does_not_infer_grouping_from_key_prefixes() -> None:
    path = REPO_ROOT / "src/ops/queries/dataset_card_query_service.py"
    text = path.read_text(encoding="utf-8")
    forbidden_tokens = (
        "_canonical_dataset_key",
        "_source_preference",
        "startswith(\"biying_\")",
        "startswith(\"tushare_\")",
        "startswith(\"raw_biying.\")",
        "startswith(\"raw_tushare.\")",
    )
    violations = [token for token in forbidden_tokens if token in text]

    assert not violations, "dataset-cards 不得再从 key/table 前缀推断卡片归并事实:\n" + "\n".join(violations)


def test_ops_dataset_card_messages_do_not_emit_internal_field_tokens() -> None:
    path = REPO_ROOT / "src/ops/queries/dataset_card_query_service.py"
    text = path.read_text(encoding="utf-8")
    forbidden_snippets = (
        "Dataset card source display name is unavailable",
        "Dataset card stage display name is unavailable",
    )
    violations = [snippet for snippet in forbidden_snippets if snippet in text]

    assert not violations, "dataset-cards API 校验不得向前端返回英文内部字段文案:\n" + "\n".join(violations)


def test_ops_services_do_not_infer_source_from_raw_table_prefix() -> None:
    forbidden_tokens = (
        "source_raw_prefix",
        ".raw_table.startswith",
        "raw_table.startswith",
    )
    violations: list[str] = []
    for path in _python_and_frontend_files(REPO_ROOT / "src/ops"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            if token in text:
                rel_path = path.relative_to(REPO_ROOT).as_posix()
                violations.append(f"{rel_path}: {token}")

    assert not violations, "Ops 服务不得从 raw table 前缀反推 source，必须使用 DatasetDefinition source facts:\n" + "\n".join(violations)


def test_ops_observation_registry_does_not_hardcode_table_model_facts() -> None:
    path = REPO_ROOT / "src/ops/dataset_observation_registry.py"
    text = path.read_text(encoding="utf-8")
    forbidden_tokens = (
        "core.",
        "core_serving.",
        "raw_biying.",
        "raw_tushare.",
    )
    violations = [token for token in forbidden_tokens if token in text]

    assert not violations, "Ops 观测模型映射不得手写表名事实，必须从 ORM metadata 派生:\n" + "\n".join(violations)


def test_ops_does_not_keep_parallel_dataset_reconcile_fact_registry() -> None:
    path = REPO_ROOT / "src/ops/services/operations_dataset_reconcile_service.py"

    assert not path.exists(), "不得保留 Ops 侧并行维护 raw/serving/date 字段的数据集对账事实源"


def test_moneyflow_multi_source_seed_uses_dataset_definition_source_facts() -> None:
    path = REPO_ROOT / "src/ops/services/operations_moneyflow_multi_source_seed_service.py"
    text = path.read_text(encoding="utf-8")
    forbidden_tokens = (
        "_primary_source",
        "_fallback_sources",
        "_all_sources",
    )
    violations = [token for token in forbidden_tokens if token in text]

    assert not violations, "moneyflow 多源 seed 不得硬编码主备来源，必须从 DatasetDefinition 派生:\n" + "\n".join(violations)


def test_ops_and_ingestion_do_not_infer_source_from_dataset_key_prefix() -> None:
    forbidden_tokens = (
        "startswith(\"biying_\")",
        "startswith(\"tushare_\")",
    )
    violations: list[str] = []
    for root in (REPO_ROOT / "src/ops", REPO_ROOT / "src/foundation/ingestion"):
        for path in _python_and_frontend_files(root):
            text = path.read_text(encoding="utf-8")
            for token in forbidden_tokens:
                if token in text:
                    rel_path = path.relative_to(REPO_ROOT).as_posix()
                    violations.append(f"{rel_path}: {token}")

    assert not violations, "Ops/Ingestion 不得从 dataset_key 前缀反推 source，必须使用 DatasetDefinition source facts:\n" + "\n".join(violations)


def test_active_code_does_not_reference_retired_dataset_fact_table() -> None:
    forbidden_tokens = (
        "dataset_" + "pipeline_" + "mode",
        "Dataset" + "PipelineMode",
        "Dataset" + "PipelineProjection",
        "build_dataset_" + "pipeline_projection",
        "multi_source_" + "pipeline",
        "single_source_" + "direct",
        "direct_" + "maintain",
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

    assert not violations, "旧数据集模式事实链不得留在活跃代码:\n" + "\n".join(violations)


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


def test_current_docs_do_not_reintroduce_retired_execution_field_names() -> None:
    forbidden_tokens = (
        "spec" + "_type",
        "spec" + "_key",
        "executor" + "_kind",
        "job" + "_name",
        "execution" + "_id",
        "current" + "_context" + "_json",
        "triggered" + "_execution" + "_id",
        "Dataset" + "Runtime" + "Contract",
        "Dataset" + "Sync" + "Contract",
        "sync" + "_v2",
        "Sync" + "V2",
        "sync" + "_run" + "_log",
        "sync" + "_job" + "_state",
        "/api/v1/ops/" + "executions",
        "sync" + "_daily",
        "sync" + "_history",
        "backfill" + "_",
    )
    violations: list[str] = []
    docs_root = REPO_ROOT / "docs"
    for path in sorted(docs_root.rglob("*")):
        if not path.is_file():
            continue
        if "archive" in path.parts or path.name == "AGENTS.md":
            continue
        if path.suffix not in {".md", ".html"}:
            continue
        text = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            if token in text:
                rel_path = path.relative_to(REPO_ROOT).as_posix()
                violations.append(f"{rel_path}: {token}")

    assert not violations, "当前基线文档不得重新写入旧执行字段或旧链路细节:\n" + "\n".join(violations)
