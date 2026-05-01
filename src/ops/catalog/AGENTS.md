# AGENTS.md — `src/ops/catalog` 展示目录规则

## 适用范围

本文件适用于 `src/ops/catalog/` 目录及其子目录。

## 目录职责

`src/ops/catalog` 承接运营后台用户可见目录配置，例如数据集展示分组、排序与默认视图。

## 硬约束

1. 这里属于 Ops 用户视图层，不得把展示分组写回 `src/foundation/datasets`。
2. `DatasetDefinition.domain` 只作为底层领域事实，不能被这里反向修改。
3. 展示目录必须显式配置；不允许静默落入“其他”或临时兼容分组。
4. 修改目录契约时，必须审计所有前端和 API 消费方，不允许页面自行拼装分组事实。
