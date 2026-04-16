# 股票技术指标数据集开发说明（派生计算）

## 1. 背景

为支持“全市场机会扫描”和低延迟查询，新增技术指标落库能力。  
指标按族拆表，避免宽表膨胀，同时保证查询简单。

## 2. 数据来源与计算口径

本数据集不直接调用外部 API，输入来自：

1. `core.equity_daily_bar`（原始日线）
2. 复权因子表：`core.equity_adj_factor`

支持两种复权口径：

1. `adjustment=forward`（前复权）
2. `adjustment=backward`（后复权）

为同时保存两种口径，指标表主键包含 `adjustment`。

## 3. 表设计

## 3.1 指标表

1. `core.ind_macd`
  - 主键：`(ts_code, trade_date, adjustment, version)`
  - 字段：`dif`, `dea`, `macd_bar`, `is_valid`
  - 说明：`is_valid` 采用预热窗口规则，`bar_count >= 250` 时为 `TRUE`。

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

当前版本已支持“增量优先、异常回退全量”：

1. `INCREMENTAL` 模式下，优先读取 `indicator_state` 做递推计算。  
2. 若发现状态缺失/`bar_count` 不一致/复权因子快照漂移，则自动回退该股全量重算。  
3. `FULL` 模式下按全历史重算，重建三类指标与状态。  
4. `indicator_state` 中 MACD 状态包含：`ema_fast`、`ema_slow`、`dea`、`bar_count`、`last_adj_factor`。  
5. 指标结果通过 `version` 做逻辑迭代管理。

## 6. 重算触发规则（已确认）

1. 除权新增/修订触发：
  - 后复权指标：单股从第一个 `trade_date >= T` 重算到最新。
  - 前复权指标：单股全历史重算到最新。

2. 日常盘后新增交易日：
  - 前/后复权指标都可按增量更新。

3. 异常状态保护触发：
  - `indicator_state.bar_count` 与实际历史行数不一致。
  - `last_trade_date` 对应复权因子与状态快照差异超过阈值（`1e-8`）。
  - 任一指标递推关键状态缺失。

> 注：当前代码已落地统一计算框架与版本管理；后续可在此基础上进一步强化“状态递推”性能优化。

## 7. P2 巡检能力（已落地）

新增 CLI：

1. `goldenshare reconcile-indicator-state`
  - 默认巡检 `source_key=tushare`、`version=1`
  - 输出总览：
    - `missing_state`
    - `stale_state`
    - `bar_count_mismatch`
    - `adj_factor_mismatch`
  - 支持阈值门禁，任一超阈值返回非 0（可接发版/定时巡检）。

2. 常用示例
  - 仅查看：
    - `goldenshare reconcile-indicator-state --sample-limit 20`
  - 作为门禁：
    - `goldenshare reconcile-indicator-state --threshold-missing-state 0 --threshold-stale-state 0 --threshold-bar-count-mismatch 0 --threshold-adj-factor-mismatch 0`

## 8. P3 性能优化（已落地）

1. 同一股票全量重算时，共享加载 `daily` 与 `adj_factor` 输入，避免前/后复权重复查询。  
2. 进度上报改为按总量步长提交（约最多 100 次），减少高频 `commit` 带来的吞吐抖动。  
3. 对外语义不变：结果口径、状态回退规则、任务进度字段保持兼容。
