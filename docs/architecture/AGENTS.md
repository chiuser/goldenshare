# AGENTS.md — `docs/architecture/` 架构文档规则

## 适用范围

本文件适用于 `docs/architecture/` 目录及其子目录。

---

## 当前架构事实

1. 子系统边界以 `foundation / ops / biz / app` 为主，`platform / operations` 为 legacy 冻结目录。
2. 数据集事实源收敛到 `src/foundation/datasets/**` 的 `DatasetDefinition`。
3. 数据维护执行计划收敛到 `src/foundation/ingestion/**` 的 `DatasetExecutionPlan`。
4. 旧同步实现目录已物理删除，不再是当前实现或迁移兜底。
5. 运维任务观测收敛到 `ops.task_run / task_run_node / task_run_issue` 与 TaskRun API。

---

## 编写约束

1. 历史归档文档不得把旧执行路由、旧任务表、旧运行日志或旧 execution API 写成当前事实。
2. 当前口径文档不得把旧三件套写成用户、API、UI 或长期代码主语。
3. 待评审方案若已有部分代码落地，文首必须写清“已部分落地/待继续收口”，避免误判为纯计划。
4. 禁止用临时拼装的 checkpoint/acquire/replay 机制恢复旧执行模型或另建第二套任务状态机，不是禁止断点续跑本身。Prod 长任务仍须遵守根 `AGENTS.md` 的持久化单元与续跑门禁；ingestion 的具体约束见 `src/foundation/ingestion/AGENTS.md`。专用 checkpoint 存储须按需求评审；DG/Lake 继续遵守其目录规则，不套用 Prod 门禁。
5. 所有架构方案必须遵守：Ops/TaskRun/freshness/snapshot/schedule 等状态写入不得影响业务数据表读写与事务提交；状态失败不允许成为业务数据回滚条件。

---

## 必读基线

1. [子系统架构基线（含依赖矩阵与护栏）](/Users/congming/github/goldenshare/docs/architecture/subsystem-boundary-plan.md)
2. [DatasetDefinition 数据集定义与职责](/Users/congming/github/goldenshare/docs/architecture/dataset-definition-single-source-refactor-plan-v1.md)
3. [DatasetExecutionPlan 执行计划与可靠执行](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)
4. [Ops TaskRun 执行观测模型重设计方案](/Users/congming/github/goldenshare/docs/ops/ops-task-run-observability-redesign-plan-v1.md)
