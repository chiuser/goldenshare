# 股票周/月线维护逻辑说明

状态：当前有效。

重要说明：`stk_weekly_monthly` / `stk_week_month_adj` 的源接口字段名叫 `trade_date`，但这里的业务含义不是“最后一个交易日”。源接口要求：

1. 周线使用自然周周五作为 `trade_date`。
2. 月线使用自然月最后一天作为 `trade_date`。

对应修正方案见：

1. [股票周/月线自然锚点日期模型修正方案 v1](/Users/congming/github/goldenshare/docs/architecture/stk-period-calendar-anchor-date-model-fix-plan-v1.md)

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

## 2. 时间口径（当前）

以源接口文档为准：

1. 股票周线：`date_axis=natural_day`、`bucket_rule=week_friday`，范围维护时按自然周周五扇出。
2. 股票月线：`date_axis=natural_day`、`bucket_rule=month_last_calendar_day`，范围维护时按自然月最后一天扇出。
3. 字段名仍为 `trade_date`，但它在这两个源接口内表达自然日期锚点，不表达交易日历锚点。

不能把股票周/月线继续套用为“每周/每月最后一个交易日”。

对照边界：

1. `index_weekly` / `index_monthly` 仍按指数接口当前口径使用最后一个开市交易日。
2. 股票周/月线与指数周/月线不能混用同一个 bucket rule。

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

历史独立回补服务已退场。股票周/月线的“自然周五 / 自然月末”规则必须通过标准 planner/resolver 从 `DatasetDefinition.date_model` 派生。

---

## 5. 观测与测试

关键测试覆盖：

1. [test_ops_action_catalog.py](/Users/congming/github/goldenshare/tests/test_ops_action_catalog.py)（动作目录暴露）
2. 后续执行计划覆盖应优先补到 DatasetExecutionPlan / resolver 测试。
