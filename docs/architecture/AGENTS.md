# AGENTS.md — `docs/architecture/` 架构文档规则

## 适用范围

本文件适用于 `docs/architecture/` 目录及其子目录。

---

## 当前架构事实

1. 子系统边界以 `foundation / ops / biz / app` 为主，`platform / operations` 为 legacy 冻结目录。
2. 数据集事实源收敛到 `src/foundation/datasets/**` 的 `DatasetDefinition`。
3. 数据维护执行计划收敛到 `src/foundation/ingestion/**` 的 `DatasetExecutionPlan`。
4. 底层同步执行实现当前仍在 `src/foundation/services/sync_v2/**`，但 `sync_v2` 是阶段性实现命名，不是长期领域模型命名。
5. 运维任务观测收敛到 `ops.task_run / task_run_node / task_run_issue` 与 TaskRun API。

---

## 编写约束

1. 若文档保留旧 `sync_daily / backfill_* / sync_history`、`JobExecution*`、`sync_run_log`、`/api/v1/ops/executions*`，必须明确标注为历史审计或迁移背景。
2. 当前口径文档不得把旧三件套写成用户、API、UI 或长期代码主语。
3. 待评审方案若已有部分代码落地，文首必须写清“已部分落地/待继续收口”，避免误判为纯计划。
4. 不得重新引入 checkpoint/acquire/replay 语义，除非用户明确要求并有独立方案。

---

## 必读基线

1. [子系统边界基线](/Users/congming/github/goldenshare/docs/architecture/subsystem-boundary-plan.md)
2. [子系统依赖矩阵](/Users/congming/github/goldenshare/docs/architecture/dependency-matrix.md)
3. [DatasetDefinition 单一事实源重构方案](/Users/congming/github/goldenshare/docs/architecture/dataset-definition-single-source-refactor-plan-v1.md)
4. [DatasetExecutionPlan 执行计划模型重构方案](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)
5. [Ops TaskRun 执行观测模型重设计方案](/Users/congming/github/goldenshare/docs/ops/ops-task-run-observability-redesign-plan-v1.md)
