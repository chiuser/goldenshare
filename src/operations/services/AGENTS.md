# AGENTS.md — src/operations/services 收尾冻结规则

## 适用范围

本文件适用于 `src/operations/services/` 目录及其子目录。

---

## 当前阶段定义（收尾完成）

`src/operations/services` 的 Python compat 壳已全部清理完成。

当前目录仅保留本 AGENTS 规则文件用于防回流。

自动护栏：

1. `tests/architecture/test_operations_legacy_guardrails.py` 固化当前目录文件清单与禁止导入边界。

---

## 允许与禁止

### 允许

1. 更新与本目录相关的架构文档状态（`docs/architecture/ops-consolidation-plan.md`）
2. 维护护栏测试，确保 legacy 路径不回流

### 禁止

1. 在本目录新增任何 Python 实现文件（包括 compat 壳）
2. 将已经迁到 `src/ops/services` 的实现重新写回本目录
3. 将本目录重新扩展为主实现目录
4. 借“收尾”名义顺手扩展 platform 或 biz 逻辑

---

## 与 src/ops/services 的关系

固定规则：

1. `src/ops/services` 是主承接目录
2. `src/operations/services` 不再承接任何 Python 导出

若任务涉及常规 service 功能，必须直接在 `src/ops/services/*` 处理，不允许在本目录补逻辑。

---

## 完成任务时说明要求

每次改动本目录后，必须说明：

1. 是否触碰了 `history_backfill_service.py` 兼容壳
2. 是否新增了任何 Python 文件（必须为否）
3. 是否影响 `ops-consolidation-plan.md` 的收尾状态
