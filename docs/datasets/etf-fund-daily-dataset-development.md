# ETF 日线行情（`fund_daily`）数据集开发说明

## 1. 背景与目标

将 `fund_daily` 数据集统一到“按交易日历逐日同步”的模式，并补齐分页抓取能力，满足：

- 单日同步：按 `trade_date`。
- 区间维护：按 `start_date/end_date` 遍历交易日。
- 分页抓取：支持 `limit/offset`，直到当页不足 `limit` 为止。
- 运营交互不暴露代码输入，仅保留日期相关意图字段。

## 2. 接口来源

- 数据源：Tushare Pro
- 文档：<https://tushare.pro/document/2?doc_id=127>
- API：`fund_daily`

## 3. 字段与表设计

当前复用既有表，不新建重复表：

- Raw：`raw.fund_daily`
- Core：`core.fund_daily_bar`

字段覆盖：

- 业务字段：`ts_code`, `trade_date`, `open`, `high`, `low`, `close`, `pre_close`, `change`, `pct_chg`, `vol`, `amount`
- Raw 审计字段：`api_name`, `fetched_at`, `raw_payload`
- Core 标准字段：`created_at`, `updated_at`，并将 `change` 映射为 `change_amount`

## 4. 维护策略

## 4.1 单日维护

- 输入：`trade_date`
- 执行：调用 `fund_daily`，按分页参数 `limit=5000`（默认）+ `offset` 拉取全部结果。

## 4.2 区间维护

- 输入：`start_date`, `end_date`
- 执行：从交易日历取开市日序列，逐日执行单日同步逻辑（含分页）。

## 4.3 分页规则

- 首次请求 `offset=0`
- 每页返回 `n` 条：
  - 若 `n < limit`：结束
  - 若 `n == limit`：`offset += limit` 继续

## 5. 运维侧交互约束

- 单日任务：只展示 `trade_date`
- 回补任务：只展示 `start_date/end_date`
- 不展示：`ts_code`
- 不向用户暴露 `limit/offset` 内部控制参数

## 6. 当前支持范围

- 已支持：
  - `fund_daily.maintain`（单日或区间）

- 数据状态：
  - 分类：`ETF/Fund`
  - 观测列：`trade_date`
