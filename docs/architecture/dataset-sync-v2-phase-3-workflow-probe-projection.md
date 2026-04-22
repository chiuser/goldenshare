# Phase 3：工作流、Probe 与状态投影（P1）

- 版本：v1.0
- 日期：2026-04-21
- 状态：已执行（归档）
- 关联文档：
  - [V2 主方案](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-redesign-plan.md)
  - [Phase 1：执行域与事件模型](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-phase-1-execution-domain.md)
  - [Phase 2：引擎与契约层](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-phase-2-engine-contracts.md)

---

## 1. 本期目标与范围

### 1.1 本期目标

1. 统一工作流执行语义（profile、参数、失败策略、恢复策略）。  
2. 将 Probe 从“配置对象”升级为“可治理触发链路”，并与自动任务联动。  
3. 统一状态投影链：execution/probe -> layer snapshot -> dataset status。  
4. 形成前端可稳定读取的双层进度模型（step + unit）。  

### 1.2 本期范围（只做这些）

1. `ops/specs` 工作流规格扩展。  
2. `ops/runtime` 工作流执行与 probe 触发语义扩展。  
3. `ops/models/ops` 状态投影相关字段扩展。  
4. `ops/queries` 观测与任务进度查询契约补齐。  

### 1.3 本期不做

1. 不做业务 API 契约改造。  
2. 不做全量前端重设计，仅提供可用后端数据。  
3. 不做最终兼容层删除（留到 Phase 4）。  

---

## 2. 工作流域详细设计（模块级）

### 2.0 约束判定口径（本期统一）

1. **硬约束**：发布或执行前必须满足；不满足即拒绝（配置不生效或执行失败）。  
2. **软约束**：允许缺省，运行时可由默认值或上游上下文补齐。  
3. **可空策略**：
   - `不可空`：字段必须存在且非空。  
   - `可空-条件必填`：默认可空，但在特定 workflow/probe 场景必须有值。  
   - `可空-透传`：可为空，主要用于策略或上下文透传。  
   - `可空-仅回显`：可为空，仅用于观测审计展示。  

## 2.1 关键模块与职责

| 模块 | 现状文件 | 本期职责 |
|---|---|---|
| Workflow Spec | `src/ops/specs/workflow_spec.py` | 扩展 profile/失败策略/参数作用域 |
| Dispatcher | `src/ops/runtime/dispatcher.py` | 按 step + policy 执行与状态传播 |
| Execution Service | `src/ops/services/operations_execution_service.py` | 创建 workflow execution 元数据 |
| Query Service | `src/ops/queries/execution_query_service.py` | 返回 workflow 级+step 级+unit 级摘要 |

## 2.2 WorkflowSpec 字段扩展设计

`WorkflowSpec` 全量字段字典（旧字段+新增字段）：

| 字段 | 来源 | 类型 | 必填 | 默认 | 约束级别 | 可空策略 | 说明 |
|---|---|---|---|---|---|---|---|
| `key` | 旧 | `str` | 是 | 无 | 硬约束 | 不可空 | workflow 唯一键 |
| `display_name` | 旧 | `str` | 是 | 无 | 硬约束 | 不可空 | workflow 名称 |
| `description` | 旧 | `str` | 是 | 无 | 硬约束 | 不可空 | 描述 |
| `steps` | 旧 | `tuple[WorkflowStepSpec,...]` | 是 | 无 | 硬约束 | 不可空 | step 列表 |
| `supported_params` | 旧 | `tuple[ParameterSpec,...]` | 否 | `()` | 软约束 | 可空-透传 | 可支持参数 |
| `parallel_policy` | 旧 | `str` | 是 | `by_dependency` | 硬约束 | 不可空 | 并行策略 |
| `default_schedule_policy` | 旧 | `str|None` | 否 | `null` | 软约束 | 可空-透传 | 默认调度策略 |
| `supports_schedule` | 旧 | `bool` | 是 | `false` | 硬约束 | 不可空 | 是否支持自动任务 |
| `supports_manual_run` | 旧 | `bool` | 是 | `true` | 硬约束 | 不可空 | 是否支持手动触发 |
| `workflow_profile` | 新 | `str` | 是 | 无 | 硬约束 | 不可空 | `point_incremental/range_rebuild/snapshot_refresh` |
| `failure_policy_default` | 新 | `str` | 是 | `fail_fast` | 硬约束 | 不可空 | 默认失败策略 |
| `supports_probe_trigger` | 新 | `bool` | 是 | `false` | 硬约束 | 不可空 | 是否允许 probe 触发 |
| `resume_supported` | 新 | `bool` | 是 | `true` | 硬约束 | 不可空 | 是否支持从失败 step 续跑 |

`WorkflowStepSpec` 全量字段字典（旧字段+新增字段）：

| 字段 | 来源 | 类型 | 必填 | 默认 | 约束级别 | 可空策略 | 说明 |
|---|---|---|---|---|---|---|---|
| `step_key` | 旧 | `str` | 是 | 无 | 硬约束 | 不可空 | step 唯一键 |
| `job_key` | 旧 | `str` | 是 | 无 | 硬约束 | 不可空 | 绑定 job 规格键 |
| `display_name` | 旧 | `str` | 是 | 无 | 硬约束 | 不可空 | step 展示名 |
| `depends_on` | 旧 | `tuple[str,...]` | 否 | `()` | 软约束 | 可空-透传 | 依赖 step 键 |
| `default_params` | 旧 | `dict` | 否 | `{}` | 软约束 | 可空-透传 | 默认参数 |
| `dataset_key` | 新 | `str` | 是 | 无 | 硬约束 | 不可空 | 明确 step 数据集 |
| `failure_policy_override` | 新 | `str` | 否 | `null` | 软约束 | 可空-透传 | step 覆盖策略 |
| `params_override` | 新 | `dict` | 是 | `{}` | 硬约束 | 不可空 | step 参数覆盖 |
| `max_retry_per_unit` | 新 | `int` | 否 | `2` | 软约束 | 可空-透传 | 单元重试上限 |

不变量：

1. 所有 step 的 `dataset_key` 必须支持 `workflow_profile`。  
2. `depends_on` 必须是 DAG。  
3. `failure_policy_override` 只允许 `fail_fast/continue_on_error/skip_downstream`。  

## 2.3 Workflow 执行状态传播规则

传播矩阵：

| 当前 step 失败策略 | 当前 step 状态 | 后继 step | workflow 状态 |
|---|---|---|---|
| `fail_fast` | `FAILED` | `BLOCKED` | `FAILED` |
| `continue_on_error` | `FAILED` | 可继续 | `PARTIAL_FAILED` |
| `skip_downstream` | `FAILED` | 依赖链 `SKIPPED/BLOCKED`，非依赖继续 | `PARTIAL_FAILED` |

续跑规则：

1. `resume_from_step_key` 之前且已成功 step 不重复执行。  
2. 续跑 execution 必须产生新 `rerun_id`，复用 `correlation_id`。  

---

## 3. Probe 触发链路详细设计（模块级）

## 3.1 关键模块与职责

| 模块 | 现状文件 | 本期职责 |
|---|---|---|
| Schedule <-> Probe Binding | `src/ops/services/schedule_probe_binding_service.py` | 自动任务转 probe 规则模板 |
| Probe Runtime | `src/ops/services/operations_probe_runtime_service.py` | 窗口/频率/上限检查与触发 |
| Probe Command | `src/ops/services/probe_service.py` | probe 规则管理 |
| Scheduler | `src/ops/runtime/scheduler.py` | 合并 schedule + probe 触发 |

## 3.2 ProbeRule 字段扩展设计

`ops.probe_rule` 全量字段字典（旧字段+新增字段）：

| 字段 | 来源 | 类型 | 必填 | 默认 | 约束级别 | 可空策略 | 说明 |
|---|---|---|---|---|---|---|---|
| `id` | 旧 | `bigint` | 是 | 自增 | 硬约束 | 不可空 | 规则主键 |
| `schedule_id` | 旧 | `bigint` | 否 | `null` | 软约束 | 可空-仅回显 | 来源自动任务 |
| `name` | 旧 | `varchar(128)` | 是 | 无 | 硬约束 | 不可空 | 规则名称 |
| `dataset_key` | 旧 | `varchar(64)` | 是 | 无 | 硬约束 | 不可空 | 目标数据集（必须单值） |
| `source_key` | 旧 | `varchar(32)` | 否 | `null` | 软约束 | 可空-透传 | 来源数据源 |
| `status` | 旧 | `varchar(16)` | 是 | `active` | 硬约束 | 不可空 | 规则状态 |
| `window_start` | 旧 | `varchar(16)` | 否 | `null` | 软约束 | 可空-透传 | 探测窗口开始时间 |
| `window_end` | 旧 | `varchar(16)` | 否 | `null` | 软约束 | 可空-透传 | 探测窗口结束时间 |
| `probe_interval_seconds` | 旧 | `int` | 是 | `300` | 硬约束 | 不可空 | 探测间隔秒数 |
| `probe_condition_json` | 旧 | `jsonb` | 是 | `{}` | 硬约束 | 不可空 | 探测条件 |
| `on_success_action_json` | 旧 | `jsonb` | 是 | `{}` | 硬约束 | 不可空 | 命中动作（必须含 `spec_type/spec_key/params_json`） |
| `max_triggers_per_day` | 旧 | `int` | 是 | `1` | 硬约束 | 不可空 | 每日触发上限 |
| `timezone_name` | 旧 | `varchar(64)` | 是 | `Asia/Shanghai` | 硬约束 | 不可空 | 时区 |
| `last_probed_at` | 旧 | `timestamptz` | 否 | `null` | 软约束 | 可空-仅回显 | 最近探测时间 |
| `last_triggered_at` | 旧 | `timestamptz` | 否 | `null` | 软约束 | 可空-仅回显 | 最近触发时间 |
| `created_by_user_id` | 旧 | `bigint` | 否 | `null` | 软约束 | 可空-仅回显 | 创建人 |
| `updated_by_user_id` | 旧 | `bigint` | 否 | `null` | 软约束 | 可空-仅回显 | 更新人 |
| `created_at` | 旧 | `timestamptz` | 是 | `now()` | 硬约束 | 不可空 | 创建时间（TimestampMixin） |
| `updated_at` | 旧 | `timestamptz` | 是 | `now()` | 硬约束 | 不可空 | 更新时间（TimestampMixin） |
| `trigger_mode` | 新 | `varchar(32)` | 是 | `dataset_execution` | 硬约束 | 不可空 | `dataset_execution/workflow_step` |
| `workflow_key` | 新 | `varchar(128)` | 否 | `null` | 软约束 | 可空-条件必填 | 若来自工作流绑定，记录 workflow |
| `step_key` | 新 | `varchar(128)` | 否 | `null` | 软约束 | 可空-条件必填 | 若绑定到 workflow step |
| `rule_version` | 新 | `int` | 是 | `1` | 硬约束 | 不可空 | 规则版本 |

## 3.3 ProbeRunLog 字段扩展设计

`ops.probe_run_log` 全量字段字典（旧字段+新增字段）：

| 字段 | 来源 | 类型 | 必填 | 默认 | 约束级别 | 可空策略 | 说明 |
|---|---|---|---|---|---|---|---|
| `id` | 旧 | `bigint` | 是 | 自增 | 硬约束 | 不可空 | 日志主键 |
| `probe_rule_id` | 旧 | `bigint` | 是 | 无 | 硬约束 | 不可空 | 所属规则 |
| `status` | 旧 | `varchar(16)` | 是 | 无 | 硬约束 | 不可空 | 执行状态 |
| `condition_matched` | 旧 | `bool` | 是 | `false` | 硬约束 | 不可空 | 是否命中条件 |
| `message` | 旧 | `text` | 否 | `null` | 软约束 | 可空-仅回显 | 文本说明 |
| `payload_json` | 旧 | `jsonb` | 是 | `{}` | 硬约束 | 不可空 | 探测载荷 |
| `probed_at` | 旧 | `timestamptz` | 是 | 无 | 硬约束 | 不可空 | 探测时间 |
| `triggered_execution_id` | 旧 | `bigint` | 否 | `null` | 软约束 | 可空-仅回显 | 命中后创建的 execution |
| `duration_ms` | 旧 | `int` | 否 | `null` | 软约束 | 可空-仅回显 | 探测耗时 |
| `rule_version` | 新 | `int` | 是 | `1` | 硬约束 | 不可空 | 对应规则版本 |
| `result_code` | 新 | `varchar(32)` | 是 | 无 | 硬约束 | 不可空 | `hit/miss/error/skipped` |
| `result_reason` | 新 | `varchar(64)` | 否 | `null` | 软约束 | 可空-仅回显 | 机器可读原因码 |
| `correlation_id` | 新 | `varchar(64)` | 否 | `null` | 软约束 | 可空-透传 | 与 execution 链接 |

## 3.4 工作流 Probe 语义（采用“按数据集拆 rule”）

1. 工作流配置 probe 目标数据集集合后，系统为每个 `dataset_key` 生成独立 probe_rule。  
2. 任一 rule 命中，只触发该数据集 execution，不强制触发整条 workflow。  
3. “整条 workflow 一次性触发”继续走定时/手动，不走 probe 分拆。  

---

## 4. 状态投影域详细设计（模块级）

## 4.1 关键模块与职责

| 模块 | 现状文件 | 本期职责 |
|---|---|---|
| Snapshot Service | `src/ops/services/operations_dataset_status_snapshot_service.py` | status 投影与 current/history 维护 |
| Freshness Query | `src/ops/queries/freshness_query_service.py` | overview 查询输入聚合 |
| Projection Mapper | `src/ops/dataset_status_projection.py` | snapshot -> UI 模型映射 |

## 4.2 `dataset_layer_snapshot_current` 字段语义增强

现有主键：`(dataset_key, source_key, stage)` 保持不变。  

全量字段字典（旧字段+新增字段）：

| 字段 | 来源 | 类型 | 必填 | 默认 | 约束级别 | 可空策略 | 说明 |
|---|---|---|---|---|---|---|---|
| `dataset_key` | 旧 | `varchar(64)` | 是 | 无 | 硬约束 | 不可空 | 数据集键（主键一部分） |
| `source_key` | 旧 | `varchar(32)` | 是 | `__all__` | 硬约束 | 不可空 | 数据源键（主键一部分） |
| `stage` | 旧 | `varchar(16)` | 是 | 无 | 硬约束 | 不可空 | 层级（主键一部分） |
| `status` | 旧 | `varchar(16)` | 是 | 无 | 硬约束 | 不可空 | 层级状态 |
| `rows_in` | 旧 | `bigint` | 否 | `null` | 软约束 | 可空-仅回显 | 输入行数 |
| `rows_out` | 旧 | `bigint` | 否 | `null` | 软约束 | 可空-仅回显 | 输出行数 |
| `error_count` | 旧 | `int` | 否 | `null` | 软约束 | 可空-仅回显 | 错误数 |
| `last_success_at` | 旧 | `timestamptz` | 否 | `null` | 软约束 | 可空-仅回显 | 最近成功时间 |
| `last_failure_at` | 旧 | `timestamptz` | 否 | `null` | 软约束 | 可空-仅回显 | 最近失败时间 |
| `lag_seconds` | 旧 | `int` | 否 | `null` | 软约束 | 可空-仅回显 | 滞后秒数 |
| `message` | 旧 | `text` | 否 | `null` | 软约束 | 可空-仅回显 | 状态说明 |
| `calculated_at` | 旧 | `timestamptz` | 是 | 无 | 硬约束 | 不可空 | 当前快照计算时间 |
| `state_updated_at` | 新 | `timestamptz` | 是 | `now()` | 硬约束 | 不可空 | 该层状态最近刷新时间 |
| `status_reason_code` | 新 | `varchar(64)` | 否 | `null` | 软约束 | 可空-仅回显 | 状态原因码 |
| `execution_id` | 新 | `bigint` | 否 | `null` | 软约束 | 可空-透传 | 最近影响该层的 execution |
| `run_profile` | 新 | `varchar(32)` | 否 | `null` | 软约束 | 可空-透传 | 最近执行语义 |

## 4.3 `dataset_layer_snapshot_history` 字段语义增强

现有 `snapshot_date` 继续保留，新增建议：

| 字段 | 来源 | 类型 | 必填 | 默认 | 约束级别 | 可空策略 | 说明 |
|---|---|---|---|---|---|---|---|
| `id` | 旧 | `bigint` | 是 | 自增 | 硬约束 | 不可空 | 历史快照主键 |
| `snapshot_date` | 旧 | `date` | 是 | 无 | 硬约束 | 不可空 | 按日查询维度 |
| `dataset_key` | 旧 | `varchar(64)` | 是 | 无 | 硬约束 | 不可空 | 数据集键 |
| `source_key` | 旧 | `varchar(32)` | 否 | `null` | 软约束 | 可空-透传 | 数据源键 |
| `stage` | 旧 | `varchar(16)` | 是 | 无 | 硬约束 | 不可空 | 层级 |
| `status` | 旧 | `varchar(16)` | 是 | 无 | 硬约束 | 不可空 | 层级状态 |
| `rows_in` | 旧 | `bigint` | 否 | `null` | 软约束 | 可空-仅回显 | 输入行数 |
| `rows_out` | 旧 | `bigint` | 否 | `null` | 软约束 | 可空-仅回显 | 输出行数 |
| `error_count` | 旧 | `int` | 否 | `null` | 软约束 | 可空-仅回显 | 错误数 |
| `last_success_at` | 旧 | `timestamptz` | 否 | `null` | 软约束 | 可空-仅回显 | 最近成功时间 |
| `last_failure_at` | 旧 | `timestamptz` | 否 | `null` | 软约束 | 可空-仅回显 | 最近失败时间 |
| `lag_seconds` | 旧 | `int` | 否 | `null` | 软约束 | 可空-仅回显 | 滞后秒数 |
| `message` | 旧 | `text` | 否 | `null` | 软约束 | 可空-仅回显 | 状态说明 |
| `calculated_at` | 旧 | `timestamptz` | 是 | 无 | 硬约束 | 不可空 | 快照计算时间 |
| `snapshot_at` | 新 | `timestamptz` | 是 | `now()` | 硬约束 | 不可空 | 精确快照时间（主时间轴） |
| `execution_id` | 新 | `bigint` | 否 | `null` | 软约束 | 可空-透传 | 来源 execution |
| `status_reason_code` | 新 | `varchar(64)` | 否 | `null` | 软约束 | 可空-仅回显 | 原因码 |

说明：

1. `snapshot_date` 保留用于按日聚合。  
2. `snapshot_at` 用于精确回放。  

## 4.4 `dataset_status_snapshot` 字段语义增强

全量字段字典（旧字段+新增字段）：

| 字段 | 来源 | 类型 | 必填 | 默认 | 约束级别 | 可空策略 | 说明 |
|---|---|---|---|---|---|---|---|
| `dataset_key` | 旧 | `varchar(64)` | 是 | 无 | 硬约束 | 不可空 | 数据集键（主键） |
| `resource_key` | 旧 | `varchar(64)` | 是 | 无 | 硬约束 | 不可空 | 资源键 |
| `display_name` | 旧 | `varchar(128)` | 是 | 无 | 硬约束 | 不可空 | 数据集名称 |
| `domain_key` | 旧 | `varchar(64)` | 是 | 无 | 硬约束 | 不可空 | 分组键 |
| `domain_display_name` | 旧 | `varchar(64)` | 是 | 无 | 硬约束 | 不可空 | 分组名称 |
| `job_name` | 旧 | `varchar(64)` | 是 | 无 | 硬约束 | 不可空 | 对应任务名 |
| `target_table` | 旧 | `varchar(128)` | 是 | 无 | 硬约束 | 不可空 | 目标表 |
| `cadence` | 旧 | `varchar(16)` | 是 | 无 | 硬约束 | 不可空 | 更新频率 |
| `state_business_date` | 旧 | `date` | 否 | `null` | 软约束 | 可空-仅回显 | 状态口径业务日 |
| `earliest_business_date` | 旧 | `date` | 否 | `null` | 软约束 | 可空-仅回显 | 最早业务日 |
| `observed_business_date` | 旧 | `date` | 否 | `null` | 软约束 | 可空-仅回显 | 观测业务日 |
| `latest_business_date` | 旧 | `date` | 否 | `null` | 软约束 | 可空-仅回显 | 最新业务日 |
| `business_date_source` | 旧 | `varchar(32)` | 是 | `none` | 硬约束 | 不可空 | 业务日来源 |
| `freshness_note` | 旧 | `text` | 否 | `null` | 软约束 | 可空-仅回显 | 新鲜度说明 |
| `latest_success_at` | 旧 | `timestamptz` | 否 | `null` | 软约束 | 可空-仅回显 | 最近成功时间 |
| `last_sync_date` | 旧 | `date` | 否 | `null` | 软约束 | 可空-仅回显 | 最近同步业务日 |
| `expected_business_date` | 旧 | `date` | 否 | `null` | 软约束 | 可空-仅回显 | 期望业务日 |
| `lag_days` | 旧 | `int` | 否 | `null` | 软约束 | 可空-仅回显 | 滞后天数 |
| `freshness_status` | 旧 | `varchar(16)` | 是 | 无 | 硬约束 | 不可空 | 新鲜度状态 |
| `recent_failure_message` | 旧 | `text` | 否 | `null` | 软约束 | 可空-仅回显 | 最近失败详情 |
| `recent_failure_summary` | 旧 | `varchar(255)` | 否 | `null` | 软约束 | 可空-仅回显 | 最近失败摘要 |
| `recent_failure_at` | 旧 | `timestamptz` | 否 | `null` | 软约束 | 可空-仅回显 | 最近失败时间 |
| `primary_execution_spec_key` | 旧 | `varchar(128)` | 否 | `null` | 软约束 | 可空-透传 | 主执行规格键 |
| `full_sync_done` | 旧 | `bool` | 是 | `false` | 硬约束 | 不可空 | 是否全量完成 |
| `snapshot_date` | 旧 | `date` | 是 | 无 | 硬约束 | 不可空 | 快照日期 |
| `last_calculated_at` | 旧 | `timestamptz` | 是 | 无 | 硬约束 | 不可空 | 最近计算时间 |
| `pipeline_mode` | 新 | `varchar(32)` | 是 | 无 | 硬约束 | 不可空 | 当前管线模式 |
| `raw_stage_status` | 新 | `varchar(16)` | 否 | `null` | 软约束 | 可空-仅回显 | 原始层状态 |
| `std_stage_status` | 新 | `varchar(16)` | 否 | `null` | 软约束 | 可空-仅回显 | 标准层状态 |
| `resolution_stage_status` | 新 | `varchar(16)` | 否 | `null` | 软约束 | 可空-仅回显 | 融合层状态 |
| `serving_stage_status` | 新 | `varchar(16)` | 否 | `null` | 软约束 | 可空-仅回显 | 服务层状态 |
| `state_updated_at` | 新 | `timestamptz` | 是 | `now()` | 硬约束 | 不可空 | 状态更新时间 |

---

## 5. 查询契约（前后端统一语义）

## 5.1 Execution 详情查询（新增字段）

响应建议包含：

1. `execution`：基础字段 + `run_profile/workflow_profile/correlation_id/rerun_id`  
2. `steps`：每 step 的 `failure_policy_effective/unit_total/unit_done/unit_failed`  
3. `units_summary`：`total/done/failed/running`  
4. `errors`：结构化错误统计（按 `error_code` 聚合）  

## 5.2 数据状态查询（总览卡片）

必须提供：

1. `latest_business_date`
2. `state_updated_at`
3. `pipeline_mode`
4. 四层状态（raw/std/resolution/serving）
5. `freshness_status + lag_days`

---

## 6. 代码改造点（精确到文件）

1. `src/ops/specs/workflow_spec.py`（字段扩展）  
2. `src/ops/runtime/dispatcher.py`（策略传播 + 续跑）  
3. `src/ops/services/schedule_probe_binding_service.py`（rule 拆分与模板字段）  
4. `src/ops/services/operations_probe_runtime_service.py`（result_code/reason/correlation）  
5. `src/ops/models/ops/probe_rule.py`（字段扩展）  
6. `src/ops/models/ops/probe_run_log.py`（字段扩展）  
7. `src/ops/models/ops/dataset_layer_snapshot_current.py`（字段扩展）  
8. `src/ops/models/ops/dataset_layer_snapshot_history.py`（字段扩展）  
9. `src/ops/models/ops/dataset_status_snapshot.py`（字段扩展）  
10. `src/ops/services/operations_dataset_status_snapshot_service.py`（投影逻辑增强）  
11. `src/ops/queries/execution_query_service.py`（返回结构增强）  
12. `src/ops/queries/freshness_query_service.py`（新字段透出）  

---

## 7. 测试门禁与验收标准

## 7.1 工作流门禁

1. profile 不匹配的数据集不得发布。  
2. DAG 有环必须发布失败。  
3. 三种失败策略行为与矩阵一致。  

## 7.2 Probe 门禁

1. 同规则同日触发不超过上限。  
2. 命中与未命中都必须有 run_log。  
3. 命中触发 execution 后可追溯 `execution_id`。  

## 7.3 状态投影门禁

1. history 与 current 一致性可校验。  
2. status snapshot 可由 current 重建。  
3. `state_updated_at` 与 execution 时间线一致。  

---

## 8. 风险与回滚

主要风险：

1. 工作流状态传播变更导致历史任务展示差异。  
2. Probe 拆分后执行量增加，需要频控保护。  
3. 投影字段新增导致旧查询遗漏赋值。  

回滚策略：

1. 工作流新字段默认可空，旧逻辑可继续运行。  
2. Probe 新增字段不影响旧触发，必要时退回旧模板。  
3. snapshot 扩展字段可回退为派生计算，不阻断主流程。  
