# Phase 1：执行域与事件模型（P0）

- 版本：v1.0
- 日期：2026-04-21
- 状态：已执行（归档）
- 关联文档：
  - [V2 主方案](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-redesign-plan.md)
  - [Ops 表改造清单](/Users/congming/github/goldenshare/docs/architecture/ops-schema-migration-checklist-v2.md)

---

## 1. 本期目标与范围

### 1.1 本期目标

1. 建立执行域统一模型：`execution -> step -> unit -> event`。  
2. 把工作流运行语义需要的关键字段落到执行模型（但不做工作流编排逻辑改造）。  
3. 建立事件 envelope，确保事件幂等消费、可重放。  

### 1.2 本期范围（只做这些）

1. `ops.job_execution`（扩展）
2. `ops.job_execution_step`（扩展）
3. `ops.job_execution_unit`（新增）
4. `ops.job_execution_event`（扩展）

### 1.3 本期不做

1. 不改 `dispatcher` 的完整 workflow 调度策略。  
2. 不改 `probe` 触发模型。  
3. 不切换前端主读链。  

---

## 2. 模块设计（代码级）

## 2.1 Runtime 模块边界

当前主模块：

1. `src/ops/runtime/dispatcher.py`
2. `src/ops/runtime/worker.py`
3. `src/ops/services/operations_execution_service.py`
4. `src/ops/queries/execution_query_service.py`

Phase 1 要求：

1. Dispatcher 继续负责执行编排，但必须同时维护 `step + unit` 两层状态。  
2. Worker 负责 execution 级状态推进（queued/running/finished），不直接写业务字段。  
3. ExecutionService 负责创建 execution 基础字段和运行上下文。  
4. ExecutionQueryService 必须能读取 unit 级进度（即便前端暂不展示）。  

## 2.2 领域对象（建议代码落位）

建议新增（仅设计约束，具体实现可分 PR）：

1. `src/ops/runtime/execution_domain.py`
   - `ExecutionStatus`（枚举）
   - `StepStatus`（枚举）
   - `UnitStatus`（枚举）
2. `src/ops/runtime/event_envelope.py`
   - `EventEnvelope` dataclass
   - `EventPayload` TypedDict

---

## 3. 数据模型详细设计（字段字典）

### 3.0 约束判定口径（本期统一）

1. **硬约束**：运行前必须满足；不满足直接失败，不允许降级。  
2. **软约束**：允许空值或默认回退；在特定上下文下可升级为条件必填。  
3. **可空策略**：
   - `不可空`：字段必须存在且非空。  
   - `可空-条件必填`：通常可空，但在特定 `spec_type`/状态下必须填写。  
   - `可空-透传`：可为空，主要作为上下文透传信息。  
   - `可空-仅回显`：可为空，仅用于审计/展示，不参与执行决策。  

## 3.1 `ops.job_execution`（扩展）

### 3.1.1 全量字段字典（旧字段+新增字段）

| 字段 | 来源 | 类型 | 必填 | 默认 | 约束级别 | 可空策略 | 含义 |
|---|---|---|---|---|---|---|---|
| `id` | 旧 | `bigint` | 是 | 自增 | 硬约束 | 不可空 | 执行主键 |
| `schedule_id` | 旧 | `bigint` | 否 | `null` | 软约束 | 可空-仅回显 | 关联自动任务 ID |
| `spec_type` | 旧 | `varchar(32)` | 是 | 无 | 硬约束 | 不可空 | 执行规格类型（`job/workflow`） |
| `spec_key` | 旧 | `varchar(128)` | 是 | 无 | 硬约束 | 不可空 | 规格主键 |
| `dataset_key` | 旧 | `varchar(64)` | 否 | `null` | 软约束 | 可空-条件必填 | 数据集键（job 场景） |
| `source_key` | 旧 | `varchar(32)` | 否 | `null` | 软约束 | 可空-透传 | 数据源键 |
| `stage` | 旧 | `varchar(16)` | 否 | `null` | 软约束 | 可空-透传 | 层级/阶段 |
| `policy_version` | 旧 | `int` | 否 | `null` | 软约束 | 可空-透传 | 策略版本 |
| `run_scope` | 旧 | `varchar(32)` | 否 | `null` | 软约束 | 可空-透传 | 运行范围标识 |
| `trigger_source` | 旧 | `varchar(16)` | 是 | 无 | 硬约束 | 不可空 | 触发来源 |
| `status` | 旧 | `varchar(20)` | 是 | `queued` | 硬约束 | 不可空 | 执行状态 |
| `priority` | 旧 | `int` | 是 | `0` | 硬约束 | 不可空 | 调度优先级 |
| `requested_by_user_id` | 旧 | `bigint` | 否 | `null` | 软约束 | 可空-仅回显 | 请求人 |
| `requested_at` | 旧 | `timestamptz` | 是 | 无 | 硬约束 | 不可空 | 请求时间 |
| `queued_at` | 旧 | `timestamptz` | 否 | `null` | 软约束 | 可空-仅回显 | 入队时间 |
| `started_at` | 旧 | `timestamptz` | 否 | `null` | 软约束 | 可空-仅回显 | 开始时间 |
| `ended_at` | 旧 | `timestamptz` | 否 | `null` | 软约束 | 可空-仅回显 | 结束时间 |
| `params_json` | 旧 | `jsonb` | 是 | `{}` | 硬约束 | 不可空 | 请求参数快照 |
| `summary_message` | 旧 | `text` | 否 | `null` | 软约束 | 可空-仅回显 | 执行摘要 |
| `rows_fetched` | 旧 | `bigint` | 是 | `0` | 硬约束 | 不可空 | 拉取行数累计 |
| `rows_written` | 旧 | `bigint` | 是 | `0` | 硬约束 | 不可空 | 写入行数累计 |
| `progress_current` | 旧 | `bigint` | 否 | `null` | 软约束 | 可空-仅回显 | 当前进度值 |
| `progress_total` | 旧 | `bigint` | 否 | `null` | 软约束 | 可空-仅回显 | 总进度值 |
| `progress_percent` | 旧 | `int` | 否 | `null` | 软约束 | 可空-仅回显 | 百分比进度 |
| `progress_message` | 旧 | `text` | 否 | `null` | 软约束 | 可空-仅回显 | 进度信息 |
| `last_progress_at` | 旧 | `timestamptz` | 否 | `null` | 软约束 | 可空-仅回显 | 最近进度更新时间 |
| `cancel_requested_at` | 旧 | `timestamptz` | 否 | `null` | 软约束 | 可空-仅回显 | 取消请求时间 |
| `canceled_at` | 旧 | `timestamptz` | 否 | `null` | 软约束 | 可空-仅回显 | 实际取消时间 |
| `error_code` | 旧 | `varchar(64)` | 否 | `null` | 软约束 | 可空-仅回显 | 错误码 |
| `error_message` | 旧 | `text` | 否 | `null` | 软约束 | 可空-仅回显 | 错误描述 |
| `created_at` | 旧 | `timestamptz` | 是 | `now()` | 硬约束 | 不可空 | 创建时间（TimestampMixin） |
| `updated_at` | 旧 | `timestamptz` | 是 | `now()` | 硬约束 | 不可空 | 更新时间（TimestampMixin） |
| `run_profile` | 新 | `varchar(32)` | 是 | 无 | 硬约束 | 不可空 | 执行主语义：`point_incremental/range_rebuild/snapshot_refresh` |
| `workflow_profile` | 新 | `varchar(32)` | 否 | `null` | 硬约束 | 可空-条件必填 | 当 `spec_type=workflow` 时记录工作流主语义 |
| `failure_policy_default` | 新 | `varchar(32)` | 否 | `fail_fast` | 软约束 | 可空-透传 | workflow 级失败策略默认值 |
| `correlation_id` | 新 | `varchar(64)` | 是 | 生成 | 硬约束 | 不可空 | 同一次业务链路的关联 ID |
| `rerun_id` | 新 | `varchar(64)` | 否 | `null` | 软约束 | 可空-仅回显 | 续跑批次标识 |
| `resume_from_step_key` | 新 | `varchar(128)` | 否 | `null` | 软约束 | 可空-透传 | 工作流续跑起点 |
| `status_reason_code` | 新 | `varchar(64)` | 否 | `null` | 软约束 | 可空-仅回显 | 状态原因（如 `workflow_step_failed`） |

### 3.1.3 不变量

1. `ended_at` 非空时，必须 `ended_at >= started_at`。  
2. `status in (success, failed, canceled, partial_failed)` 时，`ended_at` 必须非空。  
3. `run_profile` 不能为空。  
4. `spec_type=workflow` 时，`workflow_profile` 必须非空。  

### 3.1.4 索引

1. `idx_job_execution_correlation_requested_at(correlation_id, requested_at)`  
2. `idx_job_execution_run_profile_requested_at(run_profile, requested_at)`  

## 3.2 `ops.job_execution_step`（扩展）

### 3.2.1 全量字段字典（旧字段+新增字段）

| 字段 | 来源 | 类型 | 必填 | 默认 | 约束级别 | 可空策略 | 含义 |
|---|---|---|---|---|---|---|---|
| `id` | 旧 | `bigint` | 是 | 自增 | 硬约束 | 不可空 | step 主键 |
| `execution_id` | 旧 | `bigint` | 是 | 无 | 硬约束 | 不可空 | 所属 execution |
| `step_key` | 旧 | `varchar(128)` | 是 | 无 | 硬约束 | 不可空 | step 业务键 |
| `display_name` | 旧 | `varchar(128)` | 是 | 无 | 硬约束 | 不可空 | step 展示名 |
| `sequence_no` | 旧 | `int` | 是 | 无 | 硬约束 | 不可空 | 执行顺序 |
| `unit_kind` | 旧 | `varchar(32)` | 否 | `null` | 软约束 | 可空-透传 | 旧版单元类型标记 |
| `unit_value` | 旧 | `varchar(128)` | 否 | `null` | 软约束 | 可空-透传 | 旧版单元值标记 |
| `status` | 旧 | `varchar(20)` | 是 | `pending` | 硬约束 | 不可空 | step 状态 |
| `started_at` | 旧 | `timestamptz` | 否 | `null` | 软约束 | 可空-仅回显 | 开始时间 |
| `ended_at` | 旧 | `timestamptz` | 否 | `null` | 软约束 | 可空-仅回显 | 结束时间 |
| `rows_fetched` | 旧 | `bigint` | 是 | `0` | 硬约束 | 不可空 | 拉取行数累计 |
| `rows_written` | 旧 | `bigint` | 是 | `0` | 硬约束 | 不可空 | 写入行数累计 |
| `message` | 旧 | `text` | 否 | `null` | 软约束 | 可空-仅回显 | step 说明/错误摘要 |
| `created_at` | 旧 | `timestamptz` | 是 | `now()` | 硬约束 | 不可空 | 创建时间（TimestampMixin） |
| `updated_at` | 旧 | `timestamptz` | 是 | `now()` | 硬约束 | 不可空 | 更新时间（TimestampMixin） |
| `failure_policy_effective` | 新 | `varchar(32)` | 否 | `null` | 软约束 | 可空-透传 | step 最终生效策略 |
| `depends_on_step_keys_json` | 新 | `jsonb` | 是 | `[]` | 硬约束 | 不可空 | 依赖 step 列表 |
| `blocked_by_step_key` | 新 | `varchar(128)` | 否 | `null` | 软约束 | 可空-透传 | 被哪个 step 阻塞 |
| `skip_reason_code` | 新 | `varchar(64)` | 否 | `null` | 软约束 | 可空-仅回显 | 跳过原因 |
| `unit_total` | 新 | `bigint` | 是 | `0` | 硬约束 | 不可空 | unit 总数 |
| `unit_done` | 新 | `bigint` | 是 | `0` | 硬约束 | 不可空 | unit 成功数 |
| `unit_failed` | 新 | `bigint` | 是 | `0` | 硬约束 | 不可空 | unit 失败数 |

### 3.2.3 不变量

1. 同一 `execution_id` 下 `step_key` 唯一。  
2. `unit_done + unit_failed <= unit_total`。  
3. `status=success` 时 `unit_failed=0`（除非该 step 无 unit 模式）。  

## 3.3 `ops.job_execution_unit`（新增）

### 3.3.1 字段设计

| 字段 | 类型 | 必填 | 默认 | 约束级别 | 可空策略 | 含义 |
|---|---|---|---|---|---|---|
| `id` | `bigserial` | 是 | 自增 | 硬约束 | 不可空 | 记录主键 |
| `execution_id` | `bigint` | 是 | 无 | 硬约束 | 不可空 | 所属 execution |
| `step_id` | `bigint` | 是 | 无 | 硬约束 | 不可空 | 所属 step |
| `unit_id` | `varchar(128)` | 是 | 无 | 硬约束 | 不可空 | 执行单元业务键 |
| `status` | `varchar(20)` | 是 | `pending` | 硬约束 | 不可空 | unit 状态 |
| `attempt` | `int` | 是 | `0` | 硬约束 | 不可空 | 重试次数（从 0 起） |
| `retryable` | `bool` | 是 | `false` | 硬约束 | 不可空 | 是否可自动重试 |
| `error_code` | `varchar(64)` | 否 | `null` | 软约束 | 可空-仅回显 | 失败错误码 |
| `error_message` | `text` | 否 | `null` | 软约束 | 可空-仅回显 | 失败信息 |
| `rows_fetched` | `bigint` | 是 | `0` | 硬约束 | 不可空 | unit 拉取行数 |
| `rows_written` | `bigint` | 是 | `0` | 硬约束 | 不可空 | unit 写入行数 |
| `started_at` | `timestamptz` | 否 | `null` | 软约束 | 可空-仅回显 | unit 开始时间 |
| `ended_at` | `timestamptz` | 否 | `null` | 软约束 | 可空-仅回显 | unit 结束时间 |
| `duration_ms` | `int` | 否 | `null` | 软约束 | 可空-仅回显 | unit 耗时 |
| `unit_payload_json` | `jsonb` | 是 | `{}` | 硬约束 | 不可空 | unit 参数快照 |
| `created_at` | `timestamptz` | 是 | `now()` | 硬约束 | 不可空 | 创建时间 |
| `updated_at` | `timestamptz` | 是 | `now()` | 硬约束 | 不可空 | 更新时间 |

### 3.3.2 约束与索引

1. 唯一约束：`uk_job_execution_unit_execution_unit(execution_id, unit_id)`  
2. 索引：`idx_job_execution_unit_step_status(step_id, status)`  
3. 索引：`idx_job_execution_unit_execution_status(execution_id, status)`  

### 3.3.3 不变量

1. `ended_at` 非空时，`duration_ms >= 0`。  
2. `status=success` 时，`error_code/error_message` 应为空。  
3. `attempt` 单调递增。  

## 3.4 `ops.job_execution_event`（扩展）

### 3.4.1 全量字段字典（旧字段+新增字段）

| 字段 | 来源 | 类型 | 必填 | 默认 | 约束级别 | 可空策略 | 含义 |
|---|---|---|---|---|---|---|---|
| `id` | 旧 | `bigint` | 是 | 自增 | 硬约束 | 不可空 | 事件主键 |
| `execution_id` | 旧 | `bigint` | 是 | 无 | 硬约束 | 不可空 | 所属 execution |
| `step_id` | 旧 | `bigint` | 否 | `null` | 软约束 | 可空-透传 | 所属 step |
| `event_type` | 旧 | `varchar(32)` | 是 | 无 | 硬约束 | 不可空 | 事件类型 |
| `level` | 旧 | `varchar(16)` | 是 | `INFO` | 硬约束 | 不可空 | 日志级别 |
| `message` | 旧 | `text` | 否 | `null` | 软约束 | 可空-仅回显 | 事件文本 |
| `payload_json` | 旧 | `jsonb` | 是 | `{}` | 硬约束 | 不可空 | 事件载荷 |
| `occurred_at` | 旧 | `timestamptz` | 是 | 无 | 硬约束 | 不可空 | 发生时间 |
| `event_id` | 新 | `varchar(64)` | 是 | 生成 | 硬约束 | 不可空 | 全局唯一事件 ID |
| `event_version` | 新 | `int` | 是 | `1` | 硬约束 | 不可空 | 事件版本 |
| `correlation_id` | 新 | `varchar(64)` | 否 | `null` | 软约束 | 可空-透传 | 链路追踪 ID |
| `unit_id` | 新 | `varchar(128)` | 否 | `null` | 软约束 | 可空-透传 | 关联 unit |
| `producer` | 新 | `varchar(32)` | 是 | `runtime` | 硬约束 | 不可空 | 事件生产者 |
| `dedupe_key` | 新 | `varchar(128)` | 否 | `null` | 软约束 | 可空-透传 | 幂等去重键 |

### 3.4.2 约束与索引

1. 唯一约束：`uk_job_execution_event_event_id(event_id)`  
2. 索引：`idx_job_execution_event_correlation_occurred(correlation_id, occurred_at)`  
3. 索引：`idx_job_execution_event_execution_step_unit_occurred(execution_id, step_id, unit_id, occurred_at)`  

---

## 4. 状态机与错误语义（本期落库要求）

## 4.1 Execution 状态枚举（建议）

1. `queued`
2. `running`
3. `success`
4. `failed`
5. `partial_failed`
6. `canceled`

## 4.2 Step 状态枚举（建议）

1. `pending`
2. `running`
3. `success`
4. `failed`
5. `blocked`
6. `skipped`
7. `canceled`

## 4.3 Unit 状态枚举（建议）

1. `pending`
2. `running`
3. `success`
4. `failed`
5. `canceled`
6. `retrying`

## 4.4 错误码最小集（本期）

1. `validation_error`
2. `planning_error`
3. `source_call_error`
4. `normalization_error`
5. `write_error`
6. `workflow_step_failed`
7. `execution_canceled`
8. `internal_error`

---

## 5. 代码改造点（精确到文件）

1. `src/ops/models/ops/job_execution.py`：新增字段。  
2. `src/ops/models/ops/job_execution_step.py`：新增字段与约束。  
3. `src/ops/models/ops/job_execution_event.py`：新增 envelope 字段。  
4. `src/ops/models/ops/job_execution_unit.py`：新增模型文件。  
5. `src/ops/models/ops/__init__.py`：导出 `JobExecutionUnit`。  
6. `src/ops/runtime/dispatcher.py`：写 step + unit + event envelope。  
7. `src/ops/runtime/worker.py`：execution 终态与 reason_code 对齐。  
8. `src/ops/queries/execution_query_service.py`：增加 unit 查询接口（先内部可用）。  
9. `src/ops/schemas/execution.py`：扩展 schema（兼容旧字段）。  

---

## 6. 回归门禁（本期）

1. 执行链：
   - job 执行成功/失败/取消路径回归。  
   - workflow（串行）成功+中途失败路径回归。  
2. 事件链：
   - `event_id` 唯一性。  
   - `event_version` 正确落库。  
3. 一致性：
   - step 与 unit 聚合计数一致。  
4. 性能：
   - 同规模任务下写入耗时可接受（与现网基线对比）。  

---

## 7. 回滚策略（本期）

1. DDL 可逆（drop 新字段/新表可回滚）。  
2. Runtime 双开关：
   - `ENABLE_EXECUTION_UNIT_WRITE`  
   - `ENABLE_EVENT_ENVELOPE_WRITE`  
3. 关闭开关后回退到旧写路径，保持业务可用。  

---

## 8. 运行时接口契约（Phase 1 必须稳定）

## 8.1 Dispatcher -> ExecutionService

入参（逻辑）：

1. `execution_id`：执行实例 ID  
2. `spec_type/spec_key`：执行目标  
3. `run_profile`：运行语义  
4. `params_json`：请求参数快照  

出参（逻辑）：

1. `final_status`
2. `rows_fetched`
3. `rows_written`
4. `status_reason_code`
5. `summary_message`

约束：

1. Dispatcher 只编排，不直接定义业务落库逻辑。  
2. 所有终态更新必须通过 ExecutionService（避免多处散写状态）。  

## 8.2 BaseSyncService -> SyncExecutionContext

已存在 contract（`src/foundation/kernel/contracts/sync_execution_context.py`）继续沿用，但补充 Phase 1 语义：

1. `is_cancel_requested(execution_id)`：必须在 unit 边界检查。  
2. `update_progress(execution_id,current,total,message)`：必须保证单调（`current` 不回退）。  

## 8.3 Event Envelope 逻辑字段

`payload_json` 内必须包含：

1. `event_id`（字符串，全局唯一）
2. `event_version`（整数，默认 1）
3. `correlation_id`（可空）
4. `producer`（如 `dispatcher`/`worker`/`engine`）
5. `unit_id`（仅 unit 相关事件必填）

---

## 9. 数据库 DDL 草案（供评审，不直接执行）

> 说明：以下为“语义草案”，真实 DDL 在实施 PR 中按 Alembic 编写。

1. 新表：`ops.job_execution_unit`
   - 主键：`id`
   - 唯一：`(execution_id, unit_id)`
   - 索引：`(execution_id, status)`、`(step_id, status)`
2. 扩展：`ops.job_execution`
   - 新增：`run_profile/workflow_profile/failure_policy_default/correlation_id/rerun_id/resume_from_step_key/status_reason_code`
3. 扩展：`ops.job_execution_step`
   - 新增：`failure_policy_effective/depends_on_step_keys_json/blocked_by_step_key/skip_reason_code/unit_total/unit_done/unit_failed`
4. 扩展：`ops.job_execution_event`
   - 新增：`event_id/event_version/correlation_id/unit_id/producer/dedupe_key`

---

## 10. 本期实施拆解（代码任务包）

### 包 P1-1：模型层

1. `src/ops/models/ops/job_execution.py`
2. `src/ops/models/ops/job_execution_step.py`
3. `src/ops/models/ops/job_execution_event.py`
4. `src/ops/models/ops/job_execution_unit.py`（新增）
5. `src/ops/models/ops/__init__.py`

完成定义：

1. 字段、索引、约束齐全。
2. 不变量在 service/runtime 层落校验。

### 包 P1-2：运行时写链

1. `src/ops/runtime/dispatcher.py`
2. `src/ops/runtime/worker.py`
3. `src/ops/services/operations_execution_service.py`

完成定义：

1. step/unit 双层状态推进。
2. event envelope 落库。

### 包 P1-3：查询链与前端兼容

1. `src/ops/queries/execution_query_service.py`
2. `src/ops/schemas/execution.py`

完成定义：

1. 查询接口可返回 unit 汇总（先后端内部可见）。
2. 前端不改交互时保持兼容。
