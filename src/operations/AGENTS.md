# AGENTS.md — `src/operations` legacy 冻结规则

## 适用范围

本文件适用于 `src/operations/` 及其子目录。

---

## 当前状态

`src/operations` 已完成迁移收口，目录仅保留 legacy 说明文件，不承接任何 Python 主实现。

---

## 允许与禁止

允许：

1. 更新收尾文档
2. 更新架构护栏测试

禁止：

1. 在 `src/operations` 新增 Python 实现或兼容壳
2. 将 `src/ops` 主逻辑写回 `src/operations`
3. 引入新的跨域依赖

---

## 护栏

由 `tests/architecture/test_operations_legacy_guardrails.py` 约束：

1. `operations/services` 仅允许 `AGENTS.md`
2. 禁止 legacy `src.operations.*` 路径在运行代码中回流

---

## 改动后说明

每次改动本目录需说明：

1. 是否只触碰说明/护栏
2. 是否新增 Python 文件（必须为否）
3. 是否需要同步更新架构文档
