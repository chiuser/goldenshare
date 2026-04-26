# 股票周/月线同步逻辑说明（当前锚点口径）

状态：当前业务口径说明，执行入口已从旧 `sync_daily / sync_history / backfill_equity_series` 心智收敛到 `Dataset Maintain + DatasetExecutionPlan + TaskRun`。

---

## 1. 适用数据集

1. `stk_period_bar_week`（股票周线）
2. `stk_period_bar_month`（股票月线）
3. `stk_period_bar_adj_week`（股票复权周线）
4. `stk_period_bar_adj_month`（股票复权月线）

对应接口：

1. `stk_weekly_monthly`
2. `stk_week_month_adj`

---

## 2. 统一时间口径（当前）

以交易日历开市日为基准：

1. 周线：`week_end_trade_date`（每周最后一个交易日）
2. 月线：`month_end_trade_date`（每月最后一个交易日）

不再使用“自然周五 / 自然月末”作为执行锚点。

关联基线：

1. [周/月锚点交易日口径确认 v1](/Users/congming/github/goldenshare/docs/architecture/weekly-monthly-trade-date-anchor-confirmation-v1.md)

---

## 3. 入口语义（当前）

当前用户/API 口径：

1. 手动维护或自动任务只表达 `action=maintain`。
2. 单点处理输入一个日期；区间处理输入 `start_date + end_date`。
3. resolver/planner 根据数据集 `date_model` 与锚点规则生成执行计划。
4. TaskRun 负责记录任务主状态、节点进度与问题诊断。

历史内部入口说明：

1. `sync_daily`、`sync_history`、`backfill_equity_series` 仅作为历史实现/迁移语境保留，不再作为用户可见或文档主口径。
2. 若代码内部仍需投影旧 contract 能力，只能作为 `DatasetExecutionPlan` 的输入来源，不得重新暴露为前端任务名称或 API 主语义。

---

## 4. 实现落位（当前代码）

### 4.1 V2 contract

文件：

1. `market_equity.py`（历史路径，已删除）

关键字段：

1. `stk_period_bar_week` / `stk_period_bar_adj_week`：`anchor_type=week_end_trade_date`
2. `stk_period_bar_month` / `stk_period_bar_adj_month`：`anchor_type=month_end_trade_date`
3. 四个数据集都为 `window_policy=point_or_range`

### 4.2 策略函数

文件：

1. `stk_period_bar_week.py`（历史路径，已删除）
2. `stk_period_bar_month.py`（历史路径，已删除）
3. `stk_period_bar_adj_week.py`（历史路径，已删除）
4. `stk_period_bar_adj_month.py`（历史路径，已删除）

共用锚点展开与分页能力：

1. `common.py`（历史路径，已删除）
2. `trade_date_expand.py`（历史路径，已删除）

### 4.3 当前执行计划投影

当前执行计划投影位于：

1. [execution_plan.py](/Users/congming/github/goldenshare/src/foundation/ingestion/execution_plan.py)
2. [resolver.py](/Users/congming/github/goldenshare/src/foundation/ingestion/resolver.py)

历史 `src/ops/services/operations_history_backfill_service.py` 已退场，其中“开市日 -> 周末/月末交易日锚点”的有效规则必须通过标准 planner/resolver 表达。

---

## 5. 观测与测试

关键测试覆盖：

1. `test_extended_sync_services.py`（历史路径，已删除）（周/月线策略参数）
2. [test_ops_action_catalog.py](/Users/congming/github/goldenshare/tests/test_ops_action_catalog.py)（动作目录暴露）
3. 后续执行计划覆盖应优先补到 DatasetExecutionPlan / resolver 测试，而不是恢复旧回补服务测试。

---

## 6. 历史说明

旧实现曾位于 `src/foundation/services/sync/sync_stk_period_bar*_service.py`，该路径已在 V1 清理阶段移除。本文不再以旧路径作为现行依据。
