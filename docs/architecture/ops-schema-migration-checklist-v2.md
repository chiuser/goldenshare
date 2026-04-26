# Ops 数据表改造清单（配套 V2 落地节奏）

- 版本：v1.0（执行清单）
- 日期：2026-04-21
- 状态：历史执行清单（归档）
- 关联主方案：[数据同步 V2 重设计方案](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-redesign-plan.md)

> 说明：本文保留 V2 切换期的表改造执行语境与检查项，作为历史审计依据。当前请优先以 `src/ops/models/ops/*.py` 与现行 runbook/契约文档作为唯一运行口径。

---

## 1. 目标与约束

本清单用于把 `ops` 现有表结构平稳收敛到 V2 模型，核心目标：

1. 支撑 V2 的 `execution/step/unit` 三层执行语义。  
2. 支撑工作流统一语义（`workflow_profile`、失败策略、续跑）。  
3. 支撑结构化事件（可幂等消费、可重放）。  
4. 支撑状态投影一致性（current/history 可校验）。  
5. 在不中断现网的前提下完成迁移（双写、读切换、可回滚）。  

强约束：

1. 不做一次性硬切。  
2. 先增量扩展（新增列/新表），后读切换，最后停写旧表。  
3. 每阶段必须有明确门禁与回滚点。  

---

## 2. 当前 ops 表现状分组

按当前模型文件（`src/ops/models/ops/*.py`）分组如下。

### 2.1 执行编排域

1. `ops.job_execution`
2. `ops.job_execution_step`
3. `ops.job_execution_event`
4. `ops.job_schedule`

### 2.2 状态与观测域

1. `ops.dataset_layer_snapshot_current`
2. `ops.dataset_layer_snapshot_history`
3. `ops.dataset_status_snapshot`

### 2.3 策略与发布域

1. `ops.std_mapping_rule`
2. `ops.std_cleansing_rule`
3. `ops.resolution_release`
4. `ops.resolution_release_stage_status`
5. `ops.config_revision`

### 2.4 Probe 域

1. `ops.probe_rule`
2. `ops.probe_run_log`

### 2.5 历史兼容域（待退场）

1. `ops.sync_run_log`
2. `ops.sync_job_state`

### 2.6 其他治理支持

1. `ops.index_series_active`

---

## 3. 目标模型映射（表级改造决策）

| 当前表 | 决策 | 目标 |
|---|---|---|
| `job_execution` | 扩展 | 承接 run/workflow 语义与失败策略元数据 |
| `job_execution_step` | 扩展 | 回归 step 语义，明确依赖与阻塞 |
| `job_execution_event` | 扩展 | 升级为事件 envelope（可重放） |
| `job_execution_unit` | 新增 | 承接 unit 粒度状态与重试 |
| `job_schedule` | 扩展 | 增加 workflow/probe 触发策略字段 |
| `dataset_layer_snapshot_current` | 保留+增强校验 | 与 history 最新记录一致 |
| `dataset_layer_snapshot_history` | 扩展 | 引入 `snapshot_at`（datetime） |
| `dataset_status_snapshot` | 保留 | 保持“可重建投影”定位 |
| `dataset_pipeline_mode` | 下线 | 已由 DatasetDefinition 派生投影替代 |
| `std_mapping_rule` | 扩展约束 | 防重复、防脏版本 |
| `std_cleansing_rule` | 扩展约束 | 防重复、防脏版本 |
| `resolution_release` | 保留 | 发布主记录 |
| `resolution_release_stage_status` | 保留 | 发布分层状态 |
| `probe_rule` | 保留+小扩展 | 与 workflow dataset 绑定更清晰 |
| `probe_run_log` | 保留+小扩展 | 强化 execution 关联追踪 |
| `sync_run_log` | 兼容停写 | 迁移期只读，最终删除 |
| `sync_job_state` | 兼容停写 | 迁移期只读，最终删除 |
| `index_series_active` | 保留 | 与本次执行语义改造弱耦合 |

---

## 4. 逐表改造项（DDL 级别清单）

## 4.1 `ops.job_execution`（P0）

新增字段建议：

1. `run_profile`（`point_incremental/range_rebuild/snapshot_refresh`）  
2. `workflow_profile`（workflow 运行语义镜像）  
3. `failure_policy_default`（`fail_fast/continue_on_error/skip_downstream`）  
4. `correlation_id`（跨 execution/workflow 跟踪）  
5. `rerun_id`（续跑批次标识）  
6. `resume_from_step_key`（可选）  
7. `status_reason_code`（失败/取消/阻塞原因）  

索引建议：

1. `(correlation_id, requested_at)`  
2. `(run_profile, requested_at)`  

## 4.2 `ops.job_execution_step`（P0）

新增字段建议：

1. `failure_policy_effective`（step 最终生效策略）  
2. `depends_on_step_keys_json`（依赖关系）  
3. `blocked_by_step_key`（阻塞来源）  
4. `skip_reason_code`  
5. `unit_total/unit_done/unit_failed`（step 下 unit 聚合）  

约束建议：

1. 同 `execution_id` 内 `step_key` 唯一。  
2. `sequence_no` 唯一（同 `execution_id`）。  

## 4.3 `ops.job_execution_unit`（新增，P0）

建议字段：

1. 主键：`id`  
2. 外键语义字段：`execution_id`, `step_id`, `unit_id`  
3. `status`, `attempt`, `retryable`, `error_code`, `error_message`  
4. `rows_fetched`, `rows_written`  
5. `started_at`, `ended_at`, `duration_ms`  
6. `unit_payload_json`（参数快照）  

约束/索引：

1. 唯一：`(execution_id, unit_id)`  
2. 索引：`(execution_id, step_id, status)`  
3. 索引：`(status, started_at)`  

## 4.4 `ops.job_execution_event`（P0）

新增字段建议：

1. `event_id`（UUID/ULID）  
2. `event_version`（默认 1）  
3. `correlation_id`  
4. `unit_id`（可空）  
5. `producer`（runtime/engine/probe）  
6. `dedupe_key`（可选）  

约束/索引：

1. 唯一：`event_id`  
2. 索引：`(correlation_id, occurred_at)`  
3. 索引：`(execution_id, step_id, unit_id, occurred_at)`  

## 4.5 `ops.job_schedule`（P1）

新增字段建议：

1. `workflow_profile`（若 spec_type=workflow）  
2. `failure_policy_default`  
3. `max_parallel_steps`  

说明：现有 JSON 字段可保留，先不做拆表。

## 4.6 `ops.dataset_layer_snapshot_history`（P0）

新增字段建议：

1. `snapshot_at`（`timestamp with time zone`）  
2. 保留 `snapshot_date` 作为查询加速维度（非主时间轴）  

索引建议：

1. `(dataset_key, stage, snapshot_at desc)`  
2. `(source_key, stage, snapshot_at desc)`  

## 4.7 `ops.dataset_layer_snapshot_current`（P1）

增强约束建议：

1. 增加 `snapshot_ref_id`（指向 history 可选 ID）或 `snapshot_at` 对齐字段。  
2. 增加一致性巡检 SQL：current 必须等于 history 最新记录。  

## 4.8 `ops.std_mapping_rule` / `ops.std_cleansing_rule`（P1）

新增约束建议：

1. `std_mapping_rule` 唯一键：`(dataset_key, source_key, rule_set_version, src_field, std_field)`  
2. `std_cleansing_rule` 唯一键：`(dataset_key, source_key, rule_set_version, rule_type, action, condition_expr_hash)`  

## 4.9 `ops.sync_run_log` / `ops.sync_job_state`（P1/P2）

阶段策略：

1. P1：保留读，停止新增写入（由 execution/unit + snapshot 承接）。  
2. P2：只保留兼容视图或彻底下线（需引用审计通过）。  

---

## 5. 与 V2 落地节奏对齐（A/B/C/D）

## 5.1 阶段 A（基座建设）

目标：先加能力，不改主读链。

动作：

1. 新增 `job_execution_unit`。  
2. 扩展 `job_execution`、`job_execution_step`、`job_execution_event`。  
3. 扩展 `dataset_layer_snapshot_history(snapshot_at)`。  
4. 迁移脚本 + 回滚脚本 + 空跑校验脚本就位。  

门禁：

1. DDL 全量可回滚。  
2. 旧 API 行为 0 变化。  

## 5.2 阶段 B（双写期）

目标：runtime 同时写旧结构和新结构。

动作：

1. Dispatcher/Worker 双写 step 与 unit。  
2. 事件双写旧 payload + 新 envelope 字段。  
3. snapshot history 同写 `snapshot_date` 与 `snapshot_at`。  

门禁：

1. 双写一致性巡检通过（执行总数、step 总数、unit 聚合一致）。  
2. 无明显写放大瓶颈。  

## 5.3 阶段 C（读切换）

目标：查询链路切到新语义。

动作：

1. 执行详情优先读取 unit 粒度。  
2. 工作流进度改为 step+unit 双层。  
3. 状态页 freshness 以 `snapshot_at` 为主。  

门禁：

1. ops 页面关键路径回归通过。  
2. 旧读链保底开关可回切。  

## 5.4 阶段 D（兼容收口）

目标：停写并清理历史兼容。

动作：

1. 停写 `sync_run_log`、`sync_job_state`。  
2. 做最终引用审计。  
3. 删除/视图化兼容层（按风险批次）。  

门禁：

1. 连续 2 个发布窗口无回滚。  
2. 无核心查询依赖旧表。  

---

## 6. 数据集试点与表改造耦合顺序

按 V2 主方案试点顺序：

1. `daily`
2. `block_trade`
3. `moneyflow_ind_dc`
4. `stk_period_bar_month`
5. `trade_cal`

建议耦合关系：

1. 前两个试点用于验证 `execution/unit/event` 新链路。  
2. 第三个试点验证扇开+分页下 unit 规模与重试语义。  
3. 第四个试点验证周/月锚点与 `snapshot_at` freshness。  
4. 第五个试点验证低复杂度基线与回滚路径。  

---

## 7. 回归与审计清单（每阶段必做）

1. 执行链回归：job/workflow/probe 三入口。  
2. 进度回归：execution-level 与 step/unit-level 一致性。  
3. 事件回归：event_id 唯一、版本正确、可幂等消费。  
4. 状态回归：current 与 history 最新记录一致。  
5. 性能回归：双写期开销、查询延迟。  
6. 引用审计：旧表/旧字段是否仍被 runtime/query/api/tests 使用。  

---

## 8. 风险评估与回滚策略

主要风险：

1. 双写期间一致性偏差。  
2. unit 粒度导致写放大。  
3. 查询切换后页面口径抖动。  

回滚策略：

1. 读链回滚开关：新读失败可立即回退旧读。  
2. 写链回滚开关：双写可降级为旧写。  
3. 迁移脚本可逆：每次 DDL 带 downgrade 路径。  

---

## 9. 建议执行顺序（本周级）

1. 完成阶段 A 的 DDL 设计评审（不立即上线）。  
2. 先做 `job_execution_unit` + `job_execution_event` envelope 改造。  
3. 再做 `snapshot_at` 扩展与 freshness 读链兼容。  
4. 最后进入双写验证与首批数据集试点。  
