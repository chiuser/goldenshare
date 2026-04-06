# 基金复权因子（`fund_adj`）数据集开发说明

## 1. 背景与目标

新增 `fund_adj` 数据集并打通到运营系统，满足：

- 单日同步（`trade_date`）
- 历史回补（`start_date/end_date`）
- 单日分页抓取（`limit/offset` 循环）

## 2. 接口来源

- 数据源：Tushare Pro
- 文档：<https://tushare.pro/document/2?doc_id=199>
- API：`fund_adj`
- 限制：单次最多 2000 行，支持分页循环，数据总量不限

## 3. 输入输出参数

### 输入参数（上游）

- `ts_code`
- `trade_date`
- `start_date`
- `end_date`
- `limit`
- `offset`

### 输出字段（全量落库）

- `ts_code`
- `trade_date`
- `adj_factor`

## 4. 表设计

## 4.1 `raw.fund_adj`

- 主键：`(ts_code, trade_date)`
- 业务字段：`ts_code`, `trade_date`, `adj_factor`
- 审计字段：`api_name`, `fetched_at`, `raw_payload`

## 4.2 `core.fund_adj_factor`

- 主键：`(ts_code, trade_date)`
- 业务字段：`ts_code`, `trade_date`, `adj_factor`
- 系统字段：`created_at`, `updated_at`
- 索引：`idx_fund_adj_factor_trade_date`

## 5. 同步策略

## 5.1 单日同步

- 以 `trade_date` 请求接口。
- 默认 `limit=2000`，`offset` 从 0 开始递增。
- 当返回行数 `< limit` 时停止分页。

## 5.2 历史回补

- 从交易日历读取开市日序列（`start_date`~`end_date`）。
- 逐个交易日调用单日同步逻辑（含分页）。
- 不使用 `ts_code` 逐基金遍历模式。

## 6. 运维接入

- 任务规格：
  - `sync_daily.fund_adj`
  - `sync_history.fund_adj`
  - `backfill_fund_series.fund_adj`
- 手动配置：
  - 单日模式：`trade_date`
  - 区间模式：`start_date/end_date`
- 不向运营用户暴露 `ts_code`、`limit`、`offset`。
- 数据状态归类：`ETF/Fund`，观测列：`trade_date`。
