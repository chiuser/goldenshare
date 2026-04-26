# 股票周/月线维护逻辑说明（当前锚点口径）

状态：当前业务口径说明，执行入口已收敛到 `Dataset Maintain + DatasetExecutionPlan + TaskRun`。

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

内部实现要求：

1. 不得把历史执行入口重新暴露为前端任务名称或 API 主语义。
2. 周/月线锚点必须由 `DatasetDefinition.date_model` 与 `DatasetExecutionPlan` 派生。

---

## 4. 实现落位（当前代码）

### 4.1 当前执行计划投影

当前执行计划投影位于：

1. [execution_plan.py](/Users/congming/github/goldenshare/src/foundation/ingestion/execution_plan.py)
2. [resolver.py](/Users/congming/github/goldenshare/src/foundation/ingestion/resolver.py)

历史独立回补服务已退场，其中“开市日 -> 周末/月末交易日锚点”的有效规则必须通过标准 planner/resolver 表达。

---

## 5. 观测与测试

关键测试覆盖：

1. [test_ops_action_catalog.py](/Users/congming/github/goldenshare/tests/test_ops_action_catalog.py)（动作目录暴露）
2. 后续执行计划覆盖应优先补到 DatasetExecutionPlan / resolver 测试。
