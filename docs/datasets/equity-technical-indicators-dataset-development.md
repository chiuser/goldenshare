# 股票技术指标数据集开发说明（派生计算）

## 1. 背景

为支持“全市场机会扫描”和低延迟查询，新增技术指标落库能力。  
指标按族拆表，避免宽表膨胀，同时保证查询简单。

## 2. 数据来源与计算口径

本数据集不直接调用外部 API，输入来自：

1. `core.equity_daily_bar`（原始日线）
2. 复权因子表（由配置决定）：
  - 默认：`core.equity_adj_factor`
  - 可切换：`core.equity_price_restore_factor`
  - 配置项：`EQUITY_ADJUSTMENT_FACTOR_SOURCE=adj_factor|price_restore_factor`

支持两种复权口径：

1. `adjustment=forward`（前复权）
2. `adjustment=backward`（后复权）

为同时保存两种口径，指标表主键包含 `adjustment`。

## 3. 表设计

## 3.1 指标表

1. `core.ind_macd`
  - 主键：`(ts_code, trade_date, adjustment, version)`
  - 字段：`dif`, `dea`, `macd_bar`

2. `core.ind_kdj`
  - 主键：`(ts_code, trade_date, adjustment, version)`
  - 字段：`k`, `d`, `j`

3. `core.ind_rsi`
  - 主键：`(ts_code, trade_date, adjustment, version)`
  - 字段：`rsi_6`, `rsi_12`, `rsi_24`

## 3.2 元数据与状态

1. `core.indicator_meta`
  - 主键：`(indicator_name, version)`
  - 字段：`params_json`, `updated_at`
  - 用途：记录指标参数与版本。

2. `core.indicator_state`
  - 主键：`(ts_code, adjustment, indicator_name, version)`
  - 字段：`last_trade_date`, `state_json`, `updated_at`
  - 用途：记录递推状态，支持后续增量优化。

## 4. 同步任务

资源 key：`equity_indicators`

1. `sync_daily.equity_indicators`
  - 参数：`ts_code`（可选）
  - 用途：按股票全历史重算（可指定单股）。

2. `sync_history.equity_indicators`
  - 参数：`ts_code`（可选）
  - 用途：按股票全历史重算（可指定单股）。

## 5. 当前实现策略

第一版以正确性优先：

1. 单股计算时会读取该股到 `end_date` 的历史日线与因子。
2. 在指定区间内写入三张指标表，并更新 `indicator_state`。
3. 通过 `version` 管理指标逻辑迭代。

## 6. 重算触发规则（已确认）

1. 除权新增/修订触发：
  - 后复权指标：单股从第一个 `trade_date >= T` 重算到最新。
  - 前复权指标：单股全历史重算到最新。

2. 日常盘后新增交易日：
  - 前/后复权指标都可按增量更新。

> 注：当前代码已落地统一计算框架与版本管理；后续可在此基础上进一步强化“状态递推”性能优化。
