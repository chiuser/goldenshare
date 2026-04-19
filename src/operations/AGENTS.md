# AGENTS.md — src/operations 收尾期规则（已进入 legacy compat）

## 适用范围

本文件适用于 `src/operations/` 目录及其所有子目录。

---

## 当前阶段定义

`src/operations` 已完成主要迁移，当前定位为 **legacy/compat 收尾目录**，不再承接新主实现。

当前保留内容仅包括：

1. `src/operations/services/history_backfill_service.py`（兼容壳）
2. `src/operations/services/__init__.py`（过渡导出壳）
3. `src/operations/__init__.py`（包级占位）

已完成清理（不得回流）：

1. `operations/runtime/*`
2. `operations/specs/*`
3. `operations/dataset_status_projection.py`

---

## 允许与禁止

### 允许

1. 对现存兼容壳做最小维护（仅在任务明确要求时）
2. 更新与本目录相关的收尾文档
3. 新增护栏测试以防 legacy 路径回流

### 禁止

1. 在 `src/operations` 新增任何主实现
2. 将 `src/ops` 主实现写回 `src/operations`
3. 在本目录新增跨域依赖（尤其 `operations -> biz`）
4. 以“兼容修复”为名扩展业务逻辑

---

## 依赖边界

硬性规则：

1. 运行代码与测试代码不得重新依赖已删除的 `src.operations.runtime*`、`src.operations.specs*`、`src.operations.dataset_status_projection`。
2. `src/operations/services` 仅允许保留 `history_backfill` 兼容路径，其他 service 路径不得回流。
3. 新实现必须进入 `src/ops/**`（必要时 `src/biz/**`），而不是 `src/operations/**`。

---

## 处理本目录任务时的输出要求

每次改动 `src/operations` 后，必须说明：

1. 是否只触碰兼容壳（应为是）
2. 是否引入了新主实现（必须为否）
3. 是否需要同步更新 `docs/architecture/ops-consolidation-plan.md`
4. 是否影响架构护栏测试
