# AGENTS.md — src/operations/services 过渡目录收尾规则

## 适用范围

本文件适用于 `src/operations/services/` 目录及其子目录。

---

## 当前阶段定义（收尾）

`src/operations/services` 已完成常规 service 迁移收敛，当前仅保留：

1. `history_backfill_service.py`（专项，暂缓）
2. `market_mood_walkforward_validation_service.py`（专项，暂缓）
3. `__init__.py`（过渡导出壳）

其余常规 shim 已删除，不应回流。

自动护栏：

1. `tests/architecture/test_operations_legacy_guardrails.py` 固化当前目录文件清单与允许导入边界。

---

## 允许与禁止

### 允许

1. 对上述两个专项文件做最小必要 bugfix（仅在任务明确要求时）
2. 在专项迁移窗口到来前，维护 `__init__.py` 的最小兼容导出
3. 更新与本目录相关的架构文档状态（`docs/architecture/ops-consolidation-plan.md`）

### 禁止

1. 在本目录新增任何新的常规 service 主实现
2. 将已经迁到 `src/ops/services` 的实现重新写回本目录
3. 在没有专项计划/归属判定的前提下改动两个暂缓文件
4. 借“收尾”名义顺手扩展 platform 或 biz 逻辑

---

## 专项边界（必须遵守）

当前两个剩余文件属于专项处理范围：

1. `history_backfill_service.py`
2. `market_mood_walkforward_validation_service.py`

默认策略：

1. 不主动迁移
2. 不主动重写
3. 仅在明确进入专项轮次时处理

---

## 与 src/ops/services 的关系

固定规则：

1. `src/ops/services` 是主承接目录
2. `src/operations/services` 仅保留专项遗留与最小兼容导出

若任务涉及常规 service 功能，优先检查 `src/ops/services/*`，而不是在本目录补逻辑。

---

## 完成任务时说明要求

每次改动本目录后，必须说明：

1. 是否触碰了两个专项文件
2. 是否新增了任何常规 service 文件（必须为否）
3. 是否影响 `ops-consolidation-plan.md` 的专项状态
