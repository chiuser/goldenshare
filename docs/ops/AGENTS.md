# AGENTS.md — `docs/ops/` 运维文档规则

## 适用范围

本文件适用于 `docs/ops/` 目录及其子目录。

---

## 当前运维事实

1. 任务记录、任务详情、重试、停止、问题诊断以 TaskRun 为当前主线。
2. 当前任务表为 `ops.task_run`、`ops.task_run_node`、`ops.task_run_issue`。
3. 当前任务 API 为 `/api/v1/ops/task-runs*` 与 `/api/v1/ops/manual-actions/{action_key}/task-runs`。
4. 旧 `/api/v1/ops/executions*`、`JobExecution*`、`sync_run_log` 已退场，不再作为页面或 API 当前事实源。
5. `ops.job_schedule` 默认配置已重置，自动任务配置待后续专项重建。

---

## 编写约束

1. 当前文档不得继续以 `execution` 作为任务中心主对象；如必须提及，只能作为历史背景。
2. 当前文档不得把 `run-now`、`立即执行`、`retry-now` 写成有效交互或 API 口径。
3. 当前任务详情页描述必须遵守：失败原因主页面只展示一处，完整技术诊断按需读取 issue detail。
4. 手动维护动作只表达维护对象、处理范围、筛选项和发起方式，不暴露底层 `sync_daily / backfill_* / sync_history`。
5. 若文档描述自动任务，必须注明当前默认配置待重建，不能误写成已经完整恢复。

---

## 必读基线

1. [Ops 当前契约](/Users/congming/github/goldenshare/docs/ops/ops-contract-current.md)
2. [Ops API 全量说明](/Users/congming/github/goldenshare/docs/ops/ops-api-reference-v1.md)
3. [Ops TaskRun 执行观测模型重设计方案](/Users/congming/github/goldenshare/docs/ops/ops-task-run-observability-redesign-plan-v1.md)
4. [手动维护动作模型收敛方案 v2](/Users/congming/github/goldenshare/docs/ops/ops-manual-action-model-alignment-plan-v2.md)
