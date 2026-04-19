# AGENTS.md — `src/ops` 子系统规则

## 适用范围

本文件适用于 `src/ops/` 及其子目录。

---

## 目录定位

`src/ops` 是运维治理与运行编排主目录，承接：

1. runtime（scheduler/worker/dispatcher）
2. specs（job/workflow/freshness）
3. ops API / query / schema / service
4. ops 侧模型与治理能力

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
3. 变更 runtime/specs 时优先保证任务执行语义稳定。

---

## 改动后说明

每次改动需说明：

1. 属于 runtime/specs/api/query/schema/service 哪一类
2. 是否影响任务调度与执行链路
3. 是否触及跨子系统依赖边界
