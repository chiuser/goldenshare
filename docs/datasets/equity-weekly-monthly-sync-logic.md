# 股票周/月线同步逻辑说明（现行 V2 口径）

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

### 3.1 `sync-daily`

1. 输入：`trade_date`
2. 行为：按对应 contract 的锚点语义校验该日期并执行单点同步。

### 3.2 `sync-history`

1. 输入：`start_date` + `end_date`（支持 `ts_code` 可选筛选）
2. 行为：区间内按锚点展开交易日序列后执行。

### 3.3 `backfill_equity_series`

1. 输入：`start_date` + `end_date`（支持 `offset/limit`）
2. 行为：由回补服务先筛出区间开市日，再压缩为周末/月末交易锚点执行。

---

## 4. 实现落位（当前代码）

### 4.1 V2 contract

文件：

1. [market_equity.py](/Users/congming/github/goldenshare/src/foundation/services/sync_v2/registry_parts/contracts/market_equity.py)

关键字段：

1. `stk_period_bar_week` / `stk_period_bar_adj_week`：`anchor_type=week_end_trade_date`
2. `stk_period_bar_month` / `stk_period_bar_adj_month`：`anchor_type=month_end_trade_date`
3. 四个数据集都为 `window_policy=point_or_range`

### 4.2 策略函数

文件：

1. [stk_period_bar_week.py](/Users/congming/github/goldenshare/src/foundation/services/sync_v2/dataset_strategies/stk_period_bar_week.py)
2. [stk_period_bar_month.py](/Users/congming/github/goldenshare/src/foundation/services/sync_v2/dataset_strategies/stk_period_bar_month.py)
3. [stk_period_bar_adj_week.py](/Users/congming/github/goldenshare/src/foundation/services/sync_v2/dataset_strategies/stk_period_bar_adj_week.py)
4. [stk_period_bar_adj_month.py](/Users/congming/github/goldenshare/src/foundation/services/sync_v2/dataset_strategies/stk_period_bar_adj_month.py)

共用锚点展开与分页能力：

1. [common.py](/Users/congming/github/goldenshare/src/foundation/services/sync_v2/dataset_strategies/common.py)
2. [trade_date_expand.py](/Users/congming/github/goldenshare/src/foundation/services/sync_v2/strategy_helpers/trade_date_expand.py)

### 4.3 历史回补服务

文件：

1. `src/ops/services/operations_history_backfill_service.py`（历史实现，已退场）

其中 `backfill_equity_series` 曾对周/月线采用“开市日 -> 周末/月末交易日锚点”压缩执行。

---

## 5. 观测与测试

关键测试覆盖：

1. `tests/test_history_backfill_service.py`（历史测试，已随旧回补服务退场）
2. [test_extended_sync_services.py](/Users/congming/github/goldenshare/tests/test_extended_sync_services.py)（周/月线策略参数）
3. [test_ops_specs.py](/Users/congming/github/goldenshare/tests/test_ops_specs.py)（任务规格暴露）

---

## 6. 历史说明

旧实现曾位于 `src/foundation/services/sync/sync_stk_period_bar*_service.py`，该路径已在 V1 清理阶段移除。本文不再以旧路径作为现行依据。
