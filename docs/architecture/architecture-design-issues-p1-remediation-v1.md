# 架构问题 P1 修复方案 V1（2026-04-18）

关联总览：  
[architecture-design-issues-v1.md](/Users/congming/github/goldenshare/docs/architecture/architecture-design-issues-v1.md)

## 1. P1-1 observed-date 注册表单一事实源

## 问题现状

`freshness_query_service` 与 `sync_job_state_reconciliation_service` 各自维护一套 `OBSERVED_DATE_MODEL_REGISTRY`，映射重复且存在差异风险。

## 修复方案

1. 抽取共享模块，集中维护：
- `OBSERVED_DATE_MODEL_REGISTRY`
- `OBSERVED_DATE_FILTERS`
- `OBSERVED_DATE_AUTHORITATIVE_KEYS`
2. freshness 与 reconciliation 统一引用共享模块，移除本地重复定义。
3. 后续新增数据集仅允许在共享模块维护一次映射。

## 验收标准

1. 代码中不再存在两份独立的 observed-date 模型映射。
2. freshness 和 reconciliation 对同一数据集使用同一模型来源。

## 2. P1-2 快照刷新失败可见性

## 问题现状

execution finalize 后会触发 `DatasetStatusSnapshotService.refresh_for_execution`，但异常可见性不足，容易形成“执行已结束但状态未刷新”的静默失败。

## 修复方案

1. 在 worker finalize 路径对刷新调用增加显式异常捕获。
2. 刷新失败时写入 `job_execution_event`（`WARNING`），包含错误摘要，便于前端与运维定位。
3. 不让快照刷新失败反向污染 execution 最终状态，保障主任务状态稳定。

## 验收标准

1. 快照刷新异常时，execution 事件流中可直接看到告警信息。
2. 主任务状态仍按 dispatch 结果收敛，不被快照子流程覆写。

## 3. P1-3 freshness 元数据守门

## 问题现状

当前构建 `DATASET_FRESHNESS_SPEC_REGISTRY` 时，对 `SYNC_SERVICE_REGISTRY` 中缺失 metadata 的资源采用静默跳过。新增数据集时易引入“显示名未配置”等线上问题。

## 修复方案

1. 在 registry 初始化阶段增加强校验：
- 若 sync 资源缺失 freshness metadata，直接抛出启动错误。
2. 错误信息中列出缺失资源清单，便于开发阶段一次性补齐。
3. 在新增数据集开发文档模板中加入 checklist（本轮另行落地过，继续沿用）。

## 验收标准

1. 新增 sync 资源遗漏 freshness metadata 时，应用启动/导入阶段即失败。
2. 不再出现“新增后运行阶段才发现未配置显示名”的迟滞暴露问题。

## 4. 风险与回滚

1. 元数据守门会提升启动时严格性，短期可能暴露历史漏配项；这是预期行为，应补齐后再运行。
2. 若事件告警文本过长，按既有截断规则处理，避免写入失败。
