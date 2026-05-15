# Ops Date Model 与 Freshness 对齐方案 v1

状态：历史归档

## 归档说明

本文档原本用于记录一次早期 freshness 口径修正。当前主线已经升级为：

1. 数据集健康度只由 `DatasetDefinition.date_model + 真实业务表观测 + TaskRun` 计算。
2. `ops.dataset_status_snapshot` 只作为 freshness 缓存，不再保存分层健康状态。
3. 数据源页、数据状态总览、数据集详情页统一读取 freshness 与 dataset card 当前契约。

当前执行口径请以以下文档为准：

1. [Ops 当前契约](/Users/congming/github/goldenshare/docs/ops/ops-contract-current.md)
2. [Ops API 全量说明](/Users/congming/github/goldenshare/docs/ops/ops-api-reference-v1.md)
3. [Ops Freshness 单一事实源与分层观测退场计划](/Users/congming/github/goldenshare/docs/ops/ops-freshness-single-source-layer-snapshot-retirement-plan-v1.md)
