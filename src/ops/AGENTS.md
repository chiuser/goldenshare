# AGENTS.md — `src/ops` 子系统规则

## 适用范围

本文件适用于 `src/ops/` 及其子目录。

---

## 目录定位

`src/ops` 是运维治理与运行编排主目录，承接：

1. runtime（scheduler/worker/dispatcher）
2. TaskRun 任务运行、任务详情与问题诊断
3. specs（job/workflow/freshness，历史 spec 只可作为内部配置语境）
4. ops API / query / schema / service
5. ops 侧模型与治理能力

当前任务主线：

1. 任务记录、任务详情、重试、停止统一以 `ops.task_run / task_run_node / task_run_issue` 为事实源。
2. 旧 `JobExecution*`、`sync_run_log`、`/api/v1/ops/executions*` 不再作为当前主链。
3. 手动维护入口使用 Dataset Maintain 语义，Ops 不应把 `sync_daily / backfill_* / sync_history` 暴露给用户。

---

## 边界

允许依赖：

- `src.foundation`
- `src.ops`

禁止依赖：

- `src.biz`（直接依赖）
- legacy `src.platform` / `src.operations` 主实现

---

## 工作约束

1. 新运维能力直接写入 `src/ops/**`，不回流 legacy 目录。
2. facade 文件保持薄，复杂逻辑放主实现文件。
3. 变更 runtime/specs 时优先保证 TaskRun 队列与节点进度语义稳定。
4. 不得恢复旧 execution API 或旧执行观测表作为页面事实源。
5. 不得让前端或 API 调用方理解底层 spec 分支才能发起维护任务。
6. Ops 状态写入不得影响业务数据表读写与提交；TaskRun、issue、node、freshness、snapshot、schedule 等写入失败，只能让对应状态进入失败/待对账，不得回滚或阻断业务数据事务。

---

## 改动后说明

每次改动需说明：

1. 属于 runtime/specs/api/query/schema/service 哪一类
2. 是否影响任务调度与执行链路
3. 是否触及跨子系统依赖边界
