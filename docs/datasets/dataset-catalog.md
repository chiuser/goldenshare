# 数据集能力与字段说明（自动生成）

- 生成时间: `2026-04-05 09:46:25`
- 数据来源: `SYNC_SERVICE_REGISTRY`、`DAOFactory`、`JOB_SPEC_REGISTRY`
- 适用范围: 现有可同步数据集（raw/core 主链路）

## 字段语义约定（通用）

- `ts_code`: 证券代码
- `name`: 证券或板块名称
- `trade_date`: 交易日期（YYYY-MM-DD）
- `ann_date`: 公告日期
- `end_date`: 报告期或统计截止日期
- `open/high/low/close`: OHLC 价格
- `pre_close`: 前收盘价
- `change_amount`: 涨跌额
- `pct_chg`: 涨跌幅（百分比）
- `vol`: 成交量
- `amount`: 成交额
- `rank`: 榜单排名
- `source`: 数据来源标记（如 api / derived_daily）
- `query_*`: 请求上下文参数快照，用于重放与溯源
- `created_at/updated_at`: 系统写入与更新时间

## 数据集总览

| resource | api_name | raw_table | core_table | 显式fields数 | 观测日期字段 | 支持任务 |
| --- | --- | --- | --- | ---: | --- | --- |
| `adj_factor` | `adj_factor` | `raw.adj_factor` | `core.equity_adj_factor` | 3 | `trade_date` | backfill_equity_series.adj_factor, sync_daily.adj_factor, sync_history.adj_factor |
| `block_trade` | `block_trade` | `raw.block_trade` | `core.equity_block_trade` | 7 | `trade_date` | backfill_by_trade_date.block_trade, sync_daily.block_trade, sync_history.block_trade |
| `daily` | `daily` | `raw.daily` | `core.equity_daily_bar` | 11 | `trade_date` | backfill_equity_series.daily, sync_daily.daily, sync_history.daily |
| `daily_basic` | `daily_basic` | `raw.daily_basic` | `core.equity_daily_basic` | 18 | `trade_date` | backfill_by_trade_date.daily_basic, sync_daily.daily_basic, sync_history.daily_basic |
| `dc_daily` | `dc_daily` | `raw.dc_daily` | `core.dc_daily` | 12 | `trade_date` | backfill_by_date_range.dc_daily, sync_daily.dc_daily, sync_history.dc_daily |
| `dc_hot` | `dc_hot` | `raw.dc_hot` | `core.dc_hot` | 8 | `trade_date` | backfill_by_trade_date.dc_hot, sync_daily.dc_hot, sync_history.dc_hot |
| `dc_index` | `dc_index` | `raw.dc_index` | `core.dc_index` | 13 | `trade_date` | backfill_by_date_range.dc_index, sync_daily.dc_index, sync_history.dc_index |
| `dc_member` | `dc_member` | `raw.dc_member` | `core.dc_member` | 4 | `trade_date` | backfill_by_trade_date.dc_member, sync_daily.dc_member, sync_history.dc_member |
| `dividend` | `dividend` | `raw.dividend` | `core.equity_dividend` | 16 | `None` | backfill_low_frequency.dividend, sync_history.dividend |
| `etf_basic` | `etf_basic` | `raw.etf_basic` | `core.etf_basic` | 14 | `None` | sync_history.etf_basic |
| `fund_daily` | `fund_daily` | `raw.fund_daily` | `core.fund_daily_bar` | 11 | `trade_date` | backfill_fund_series.fund_daily, sync_daily.fund_daily, sync_history.fund_daily |
| `hk_basic` | `hk_basic` | `raw.hk_basic` | `core.hk_security` | 12 | `None` | sync_history.hk_basic |
| `index_basic` | `index_basic` | `raw.index_basic` | `core.index_basic` | 13 | `None` | sync_history.index_basic |
| `index_daily` | `index_daily` | `raw.index_daily` | `core.index_daily_serving` | 11 | `trade_date` | backfill_index_series.index_daily, sync_daily.index_daily, sync_history.index_daily |
| `index_daily_basic` | `index_dailybasic` | `raw.index_daily_basic` | `core.index_daily_basic` | 12 | `trade_date` | backfill_index_series.index_daily_basic, sync_history.index_daily_basic |
| `index_monthly` | `index_monthly` | `raw.index_monthly_bar` | `core.index_monthly_serving` | 11 | `trade_date` | backfill_index_series.index_monthly, sync_history.index_monthly |
| `index_weekly` | `index_weekly` | `raw.index_weekly_bar` | `core.index_weekly_serving` | 11 | `trade_date` | backfill_index_series.index_weekly, sync_history.index_weekly |
| `index_weight` | `index_weight` | `raw.index_weight` | `core.index_weight` | 4 | `trade_date` | backfill_index_series.index_weight, sync_history.index_weight |
| `kpl_concept_cons` | `kpl_concept_cons` | `raw.kpl_concept_cons` | `core.kpl_concept_cons` | 8 | `trade_date` | backfill_by_trade_date.kpl_concept_cons, sync_daily.kpl_concept_cons, sync_history.kpl_concept_cons |
| `kpl_list` | `kpl_list` | `raw.kpl_list` | `core.kpl_list` | 24 | `trade_date` | backfill_by_date_range.kpl_list, sync_daily.kpl_list, sync_history.kpl_list |
| `limit_cpt_list` | `limit_cpt_list` | `raw.limit_cpt_list` | `core.limit_cpt_list` | 9 | `trade_date` | backfill_by_trade_date.limit_cpt_list, sync_daily.limit_cpt_list, sync_history.limit_cpt_list |
| `limit_list_d` | `limit_list_d` | `raw.limit_list` | `core.equity_limit_list` | 18 | `trade_date` | backfill_by_trade_date.limit_list_d, sync_daily.limit_list_d, sync_history.limit_list_d |
| `limit_list_ths` | `limit_list_ths` | `raw.limit_list_ths` | `core.limit_list_ths` | 24 | `trade_date` | backfill_by_trade_date.limit_list_ths, sync_daily.limit_list_ths, sync_history.limit_list_ths |
| `limit_step` | `limit_step` | `raw.limit_step` | `core.limit_step` | 4 | `trade_date` | backfill_by_trade_date.limit_step, sync_daily.limit_step, sync_history.limit_step |
| `moneyflow` | `moneyflow` | `raw.moneyflow` | `core.equity_moneyflow` | 20 | `trade_date` | backfill_by_trade_date.moneyflow, sync_daily.moneyflow, sync_history.moneyflow |
| `stk_holdernumber` | `stk_holdernumber` | `raw.holdernumber` | `core.equity_holder_number` | 4 | `None` | backfill_low_frequency.stk_holdernumber, sync_history.stk_holdernumber |
| `stk_period_bar_adj_month` | `stk_week_month_adj` | `raw.stk_period_bar_adj` | `core.stk_period_bar_adj` | 21 | `trade_date` | backfill_equity_series.stk_period_bar_adj_month, sync_history.stk_period_bar_adj_month |
| `stk_period_bar_adj_week` | `stk_week_month_adj` | `raw.stk_period_bar_adj` | `core.stk_period_bar_adj` | 21 | `trade_date` | backfill_equity_series.stk_period_bar_adj_week, sync_history.stk_period_bar_adj_week |
| `stk_period_bar_month` | `stk_weekly_monthly` | `raw.stk_period_bar` | `core.stk_period_bar` | 13 | `trade_date` | backfill_equity_series.stk_period_bar_month, sync_history.stk_period_bar_month |
| `stk_period_bar_week` | `stk_weekly_monthly` | `raw.stk_period_bar` | `core.stk_period_bar` | 13 | `trade_date` | backfill_equity_series.stk_period_bar_week, sync_history.stk_period_bar_week |
| `stock_basic` | `stock_basic` | `raw.stock_basic` | `core.security` | 17 | `None` | sync_history.stock_basic |
| `ths_daily` | `ths_daily` | `raw.ths_daily` | `core.ths_daily` | 14 | `trade_date` | backfill_by_date_range.ths_daily, sync_daily.ths_daily, sync_history.ths_daily |
| `ths_hot` | `ths_hot` | `raw.ths_hot` | `core.ths_hot` | 11 | `trade_date` | backfill_by_trade_date.ths_hot, sync_daily.ths_hot, sync_history.ths_hot |
| `ths_index` | `ths_index` | `raw.ths_index` | `core.ths_index` | 6 | `None` | sync_history.ths_index |
| `ths_member` | `ths_member` | `raw.ths_member` | `core.ths_member` | 7 | `None` | sync_history.ths_member |
| `top_list` | `top_list` | `raw.top_list` | `core.equity_top_list` | 15 | `trade_date` | backfill_by_trade_date.top_list, sync_daily.top_list, sync_history.top_list |
| `trade_cal` | `trade_cal` | `raw.trade_cal` | `core.trade_calendar` | 4 | `trade_date` | backfill_trade_cal.trade_cal, sync_history.trade_cal |
| `us_basic` | `us_basic` | `raw.us_basic` | `core.us_security` | 6 | `None` | sync_history.us_basic |

## 分数据集详细说明

### `adj_factor`

- API: `adj_factor`
- Raw 表: `raw.adj_factor`（DAO: `raw_adj_factor`）
- Core 表: `core.equity_adj_factor`（DAO: `equity_adj_factor`）
- 显式请求 fields（3）: ts_code, trade_date, adj_factor
- 支持任务: backfill_equity_series.adj_factor, sync_daily.adj_factor, sync_history.adj_factor
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `adj_factor`: 复权因子
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `adj_factor`: 复权因子
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `block_trade`

- API: `block_trade`
- Raw 表: `raw.block_trade`（DAO: `raw_block_trade`）
- Core 表: `core.equity_block_trade`（DAO: `equity_block_trade`）
- 显式请求 fields（7）: ts_code, trade_date, price, vol, amount, buyer, seller
- 支持任务: backfill_by_trade_date.block_trade, sync_daily.block_trade, sync_history.block_trade
- Raw 字段释义:
- `id`: 系统代理主键
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `buyer`: 上游原始字段，语义请参照对应接口文档
- `seller`: 上游原始字段，语义请参照对应接口文档
- `price`: 上游原始字段，语义请参照对应接口文档
- `vol`: 成交量
- `amount`: 成交额
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `id`: 系统代理主键
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `buyer`: 上游原始字段，语义请参照对应接口文档
- `seller`: 上游原始字段，语义请参照对应接口文档
- `price`: 上游原始字段，语义请参照对应接口文档
- `vol`: 成交量
- `amount`: 成交额
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `daily`

- API: `daily`
- Raw 表: `raw.daily`（DAO: `raw_daily`）
- Core 表: `core.equity_daily_bar`（DAO: `equity_daily_bar`）
- 显式请求 fields（11）: ts_code, trade_date, open, high, low, close, pre_close, change, pct_chg, vol, amount
- 支持任务: backfill_equity_series.daily, sync_daily.daily, sync_history.daily
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `open`: 开盘价
- `high`: 最高价
- `low`: 最低价
- `close`: 收盘价
- `pre_close`: 昨收价
- `change`: 涨跌额（上游原始字段）
- `pct_chg`: 涨跌幅（系统标准字段）
- `vol`: 成交量
- `amount`: 成交额
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `open`: 开盘价
- `high`: 最高价
- `low`: 最低价
- `close`: 收盘价
- `pre_close`: 昨收价
- `change_amount`: 涨跌额（系统标准字段）
- `pct_chg`: 涨跌幅（系统标准字段）
- `vol`: 成交量
- `amount`: 成交额
- `source`: 数据来源标识（如 api / derived_daily）
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `daily_basic`

- API: `daily_basic`
- Raw 表: `raw.daily_basic`（DAO: `raw_daily_basic`）
- Core 表: `core.equity_daily_basic`（DAO: `equity_daily_basic`）
- 显式请求 fields（18）: ts_code, trade_date, close, turnover_rate, turnover_rate_f, volume_ratio, pe, pe_ttm, pb, ps, ps_ttm, dv_ratio, dv_ttm, total_share, float_share, free_share, total_mv, circ_mv
- 支持任务: backfill_by_trade_date.daily_basic, sync_daily.daily_basic, sync_history.daily_basic
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `close`: 收盘价
- `turnover_rate`: 换手率
- `turnover_rate_f`: 上游原始字段，语义请参照对应接口文档
- `volume_ratio`: 上游原始字段，语义请参照对应接口文档
- `pe`: 上游原始字段，语义请参照对应接口文档
- `pe_ttm`: 上游原始字段，语义请参照对应接口文档
- `pb`: 上游原始字段，语义请参照对应接口文档
- `ps`: 上游原始字段，语义请参照对应接口文档
- `ps_ttm`: 上游原始字段，语义请参照对应接口文档
- `dv_ratio`: 上游原始字段，语义请参照对应接口文档
- `dv_ttm`: 上游原始字段，语义请参照对应接口文档
- `total_share`: 上游原始字段，语义请参照对应接口文档
- `float_share`: 上游原始字段，语义请参照对应接口文档
- `free_share`: 上游原始字段，语义请参照对应接口文档
- `total_mv`: 总市值
- `circ_mv`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `close`: 收盘价
- `turnover_rate`: 换手率
- `turnover_rate_f`: 上游原始字段，语义请参照对应接口文档
- `volume_ratio`: 上游原始字段，语义请参照对应接口文档
- `pe`: 上游原始字段，语义请参照对应接口文档
- `pe_ttm`: 上游原始字段，语义请参照对应接口文档
- `pb`: 上游原始字段，语义请参照对应接口文档
- `ps`: 上游原始字段，语义请参照对应接口文档
- `ps_ttm`: 上游原始字段，语义请参照对应接口文档
- `dv_ratio`: 上游原始字段，语义请参照对应接口文档
- `dv_ttm`: 上游原始字段，语义请参照对应接口文档
- `total_share`: 上游原始字段，语义请参照对应接口文档
- `float_share`: 上游原始字段，语义请参照对应接口文档
- `free_share`: 上游原始字段，语义请参照对应接口文档
- `total_mv`: 总市值
- `circ_mv`: 上游原始字段，语义请参照对应接口文档
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `dc_daily`

- API: `dc_daily`
- Raw 表: `raw.dc_daily`（DAO: `raw_dc_daily`）
- Core 表: `core.dc_daily`（DAO: `-`）
- 显式请求 fields（12）: ts_code, trade_date, close, open, high, low, change, pct_change, vol, amount, swing, turnover_rate
- 支持任务: backfill_by_date_range.dc_daily, sync_daily.dc_daily, sync_history.dc_daily
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `close`: 收盘价
- `open`: 开盘价
- `high`: 最高价
- `low`: 最低价
- `change`: 涨跌额（上游原始字段）
- `pct_change`: 涨跌幅（上游原始字段）
- `vol`: 成交量
- `amount`: 成交额
- `swing`: 上游原始字段，语义请参照对应接口文档
- `turnover_rate`: 换手率
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- 无

### `dc_hot`

- API: `dc_hot`
- Raw 表: `raw.dc_hot`（DAO: `raw_dc_hot`）
- Core 表: `core.dc_hot`（DAO: `-`）
- 显式请求 fields（8）: trade_date, data_type, ts_code, ts_name, rank, pct_change, current_price, rank_time
- 支持任务: backfill_by_trade_date.dc_hot, sync_daily.dc_hot, sync_history.dc_hot
- Raw 字段释义:
- `trade_date`: 交易日
- `data_type`: 上游原始字段，语义请参照对应接口文档
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `rank_time`: 榜单时间戳
- `query_market`: 请求上下文：market
- `query_hot_type`: 请求上下文：hot_type
- `query_is_new`: 请求上下文：is_new
- `ts_name`: 上游原始字段，语义请参照对应接口文档
- `rank`: 排名
- `pct_change`: 涨跌幅（上游原始字段）
- `current_price`: 上游原始字段，语义请参照对应接口文档
- `hot`: 热度值
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- 无

### `dc_index`

- API: `dc_index`
- Raw 表: `raw.dc_index`（DAO: `raw_dc_index`）
- Core 表: `core.dc_index`（DAO: `dc_index`）
- 显式请求 fields（13）: ts_code, trade_date, name, leading, leading_code, pct_change, leading_pct, total_mv, turnover_rate, up_num, down_num, idx_type, level
- 支持任务: backfill_by_date_range.dc_index, sync_daily.dc_index, sync_history.dc_index
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `name`: 名称
- `leading`: 上游原始字段，语义请参照对应接口文档
- `leading_code`: 代码字段（具体语义以接口文档为准）
- `pct_change`: 涨跌幅（上游原始字段）
- `leading_pct`: 上游原始字段，语义请参照对应接口文档
- `total_mv`: 总市值
- `turnover_rate`: 换手率
- `up_num`: 上游原始字段，语义请参照对应接口文档
- `down_num`: 上游原始字段，语义请参照对应接口文档
- `idx_type`: 板块类型
- `level`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `name`: 名称
- `leading`: 上游原始字段，语义请参照对应接口文档
- `leading_code`: 代码字段（具体语义以接口文档为准）
- `pct_change`: 涨跌幅（上游原始字段）
- `leading_pct`: 上游原始字段，语义请参照对应接口文档
- `total_mv`: 总市值
- `turnover_rate`: 换手率
- `up_num`: 上游原始字段，语义请参照对应接口文档
- `down_num`: 上游原始字段，语义请参照对应接口文档
- `idx_type`: 板块类型
- `level`: 上游原始字段，语义请参照对应接口文档
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `dc_member`

- API: `dc_member`
- Raw 表: `raw.dc_member`（DAO: `raw_dc_member`）
- Core 表: `core.dc_member`（DAO: `-`）
- 显式请求 fields（4）: trade_date, ts_code, con_code, name
- 支持任务: backfill_by_trade_date.dc_member, sync_daily.dc_member, sync_history.dc_member
- Raw 字段释义:
- `trade_date`: 交易日
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `con_code`: 成分代码
- `name`: 名称
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- 无

### `dividend`

- API: `dividend`
- Raw 表: `raw.dividend`（DAO: `raw_dividend`）
- Core 表: `core.equity_dividend`（DAO: `equity_dividend`）
- 显式请求 fields（16）: ts_code, end_date, ann_date, div_proc, stk_div, stk_bo_rate, stk_co_rate, cash_div, cash_div_tax, record_date, ex_date, pay_date, div_listdate, imp_ann_date, base_date, base_share
- 支持任务: backfill_low_frequency.dividend, sync_history.dividend
- Raw 字段释义:
- `id`: 系统代理主键
- `row_key_hash`: 记录级哈希键（去重与幂等）
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `end_date`: 报告期/统计截止日期
- `ann_date`: 公告日
- `div_proc`: 上游原始字段，语义请参照对应接口文档
- `record_date`: 股权登记日
- `ex_date`: 除权除息日
- `pay_date`: 派息日
- `div_listdate`: 上游原始字段，语义请参照对应接口文档
- `imp_ann_date`: 日期字段（具体语义以接口文档为准）
- `base_date`: 日期字段（具体语义以接口文档为准）
- `base_share`: 上游原始字段，语义请参照对应接口文档
- `stk_div`: 上游原始字段，语义请参照对应接口文档
- `stk_bo_rate`: 上游原始字段，语义请参照对应接口文档
- `stk_co_rate`: 上游原始字段，语义请参照对应接口文档
- `cash_div`: 上游原始字段，语义请参照对应接口文档
- `cash_div_tax`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `id`: 系统代理主键
- `row_key_hash`: 记录级哈希键（去重与幂等）
- `event_key_hash`: 事件级哈希键（事件聚合）
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `end_date`: 报告期/统计截止日期
- `ann_date`: 公告日
- `div_proc`: 上游原始字段，语义请参照对应接口文档
- `record_date`: 股权登记日
- `ex_date`: 除权除息日
- `pay_date`: 派息日
- `div_listdate`: 上游原始字段，语义请参照对应接口文档
- `imp_ann_date`: 日期字段（具体语义以接口文档为准）
- `base_date`: 日期字段（具体语义以接口文档为准）
- `base_share`: 上游原始字段，语义请参照对应接口文档
- `stk_div`: 上游原始字段，语义请参照对应接口文档
- `stk_bo_rate`: 上游原始字段，语义请参照对应接口文档
- `stk_co_rate`: 上游原始字段，语义请参照对应接口文档
- `cash_div`: 上游原始字段，语义请参照对应接口文档
- `cash_div_tax`: 上游原始字段，语义请参照对应接口文档
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `etf_basic`

- API: `etf_basic`
- Raw 表: `raw.etf_basic`（DAO: `raw_etf_basic`）
- Core 表: `core.etf_basic`（DAO: `etf_basic`）
- 显式请求 fields（14）: ts_code, csname, extname, cname, index_code, index_name, setup_date, list_date, list_status, exchange, mgr_name, custod_name, mgt_fee, etf_type
- 支持任务: sync_history.etf_basic
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `csname`: 上游原始字段，语义请参照对应接口文档
- `extname`: 上游原始字段，语义请参照对应接口文档
- `cname`: 上游原始字段，语义请参照对应接口文档
- `index_code`: 指数代码
- `index_name`: 上游原始字段，语义请参照对应接口文档
- `setup_date`: 日期字段（具体语义以接口文档为准）
- `list_date`: 上市日期
- `list_status`: 上市状态
- `exchange`: 交易所
- `mgr_name`: 上游原始字段，语义请参照对应接口文档
- `custod_name`: 上游原始字段，语义请参照对应接口文档
- `mgt_fee`: 上游原始字段，语义请参照对应接口文档
- `etf_type`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `csname`: 上游原始字段，语义请参照对应接口文档
- `extname`: 上游原始字段，语义请参照对应接口文档
- `cname`: 上游原始字段，语义请参照对应接口文档
- `index_code`: 指数代码
- `index_name`: 上游原始字段，语义请参照对应接口文档
- `setup_date`: 日期字段（具体语义以接口文档为准）
- `list_date`: 上市日期
- `list_status`: 上市状态
- `exchange`: 交易所
- `mgr_name`: 上游原始字段，语义请参照对应接口文档
- `custod_name`: 上游原始字段，语义请参照对应接口文档
- `mgt_fee`: 上游原始字段，语义请参照对应接口文档
- `etf_type`: 上游原始字段，语义请参照对应接口文档
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `fund_daily`

- API: `fund_daily`
- Raw 表: `raw.fund_daily`（DAO: `raw_fund_daily`）
- Core 表: `core.fund_daily_bar`（DAO: `fund_daily_bar`）
- 显式请求 fields（11）: ts_code, trade_date, open, high, low, close, pre_close, change, pct_chg, vol, amount
- 支持任务: backfill_fund_series.fund_daily, sync_daily.fund_daily, sync_history.fund_daily
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `open`: 开盘价
- `high`: 最高价
- `low`: 最低价
- `close`: 收盘价
- `pre_close`: 昨收价
- `change`: 涨跌额（上游原始字段）
- `pct_chg`: 涨跌幅（系统标准字段）
- `vol`: 成交量
- `amount`: 成交额
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `open`: 开盘价
- `high`: 最高价
- `low`: 最低价
- `close`: 收盘价
- `pre_close`: 昨收价
- `change_amount`: 涨跌额（系统标准字段）
- `pct_chg`: 涨跌幅（系统标准字段）
- `vol`: 成交量
- `amount`: 成交额
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `hk_basic`

- API: `hk_basic`
- Raw 表: `raw.hk_basic`（DAO: `raw_hk_basic`）
- Core 表: `core.hk_security`（DAO: `hk_security`）
- 显式请求 fields（12）: ts_code, name, fullname, enname, cn_spell, market, list_status, list_date, delist_date, trade_unit, isin, curr_type
- 支持任务: sync_history.hk_basic
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `name`: 名称
- `fullname`: 上游原始字段，语义请参照对应接口文档
- `enname`: 上游原始字段，语义请参照对应接口文档
- `cn_spell`: 上游原始字段，语义请参照对应接口文档
- `market`: 市场类型
- `list_status`: 上市状态
- `list_date`: 上市日期
- `delist_date`: 退市日期
- `trade_unit`: 上游原始字段，语义请参照对应接口文档
- `isin`: 上游原始字段，语义请参照对应接口文档
- `curr_type`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `name`: 名称
- `fullname`: 上游原始字段，语义请参照对应接口文档
- `enname`: 上游原始字段，语义请参照对应接口文档
- `cn_spell`: 上游原始字段，语义请参照对应接口文档
- `market`: 市场类型
- `list_status`: 上市状态
- `list_date`: 上市日期
- `delist_date`: 退市日期
- `trade_unit`: 上游原始字段，语义请参照对应接口文档
- `isin`: 上游原始字段，语义请参照对应接口文档
- `curr_type`: 上游原始字段，语义请参照对应接口文档
- `source`: 数据来源标识（如 api / derived_daily）
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `index_basic`

- API: `index_basic`
- Raw 表: `raw.index_basic`（DAO: `raw_index_basic`）
- Core 表: `core.index_basic`（DAO: `index_basic`）
- 显式请求 fields（13）: ts_code, name, fullname, market, publisher, index_type, category, base_date, base_point, list_date, weight_rule, desc, exp_date
- 支持任务: sync_history.index_basic
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `name`: 名称
- `fullname`: 上游原始字段，语义请参照对应接口文档
- `market`: 市场类型
- `publisher`: 上游原始字段，语义请参照对应接口文档
- `index_type`: 上游原始字段，语义请参照对应接口文档
- `category`: 上游原始字段，语义请参照对应接口文档
- `base_date`: 日期字段（具体语义以接口文档为准）
- `base_point`: 上游原始字段，语义请参照对应接口文档
- `list_date`: 上市日期
- `weight_rule`: 上游原始字段，语义请参照对应接口文档
- `desc`: 上游原始字段，语义请参照对应接口文档
- `exp_date`: 日期字段（具体语义以接口文档为准）
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `name`: 名称
- `fullname`: 上游原始字段，语义请参照对应接口文档
- `market`: 市场类型
- `publisher`: 上游原始字段，语义请参照对应接口文档
- `index_type`: 上游原始字段，语义请参照对应接口文档
- `category`: 上游原始字段，语义请参照对应接口文档
- `base_date`: 日期字段（具体语义以接口文档为准）
- `base_point`: 上游原始字段，语义请参照对应接口文档
- `list_date`: 上市日期
- `weight_rule`: 上游原始字段，语义请参照对应接口文档
- `desc`: 上游原始字段，语义请参照对应接口文档
- `exp_date`: 日期字段（具体语义以接口文档为准）
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `index_daily`

- API: `index_daily`
- Raw 表: `raw.index_daily`（DAO: `raw_index_daily`）
- Core 表: `core.index_daily_serving`（DAO: `index_daily_serving`）
- 显式请求 fields（11）: ts_code, trade_date, open, high, low, close, pre_close, change, pct_chg, vol, amount
- 支持任务: backfill_index_series.index_daily, sync_daily.index_daily, sync_history.index_daily
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `open`: 开盘价
- `high`: 最高价
- `low`: 最低价
- `close`: 收盘价
- `pre_close`: 昨收价
- `change`: 涨跌额（上游原始字段）
- `pct_chg`: 涨跌幅（系统标准字段）
- `vol`: 成交量
- `amount`: 成交额
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `open`: 开盘价
- `high`: 最高价
- `low`: 最低价
- `close`: 收盘价
- `pre_close`: 昨收价
- `change_amount`: 涨跌额（系统标准字段）
- `pct_chg`: 涨跌幅（系统标准字段）
- `vol`: 成交量
- `amount`: 成交额
- `source`: 数据来源标识（如 api / derived_daily）
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `index_daily_basic`

- API: `index_dailybasic`
- Raw 表: `raw.index_daily_basic`（DAO: `raw_index_daily_basic`）
- Core 表: `core.index_daily_basic`（DAO: `index_daily_basic`）
- 显式请求 fields（12）: ts_code, trade_date, total_mv, float_mv, total_share, float_share, free_share, turnover_rate, turnover_rate_f, pe, pe_ttm, pb
- 支持任务: backfill_index_series.index_daily_basic, sync_history.index_daily_basic
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `total_mv`: 总市值
- `float_mv`: 流通市值
- `total_share`: 上游原始字段，语义请参照对应接口文档
- `float_share`: 上游原始字段，语义请参照对应接口文档
- `free_share`: 上游原始字段，语义请参照对应接口文档
- `turnover_rate`: 换手率
- `turnover_rate_f`: 上游原始字段，语义请参照对应接口文档
- `pe`: 上游原始字段，语义请参照对应接口文档
- `pe_ttm`: 上游原始字段，语义请参照对应接口文档
- `pb`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `total_mv`: 总市值
- `float_mv`: 流通市值
- `total_share`: 上游原始字段，语义请参照对应接口文档
- `float_share`: 上游原始字段，语义请参照对应接口文档
- `free_share`: 上游原始字段，语义请参照对应接口文档
- `turnover_rate`: 换手率
- `turnover_rate_f`: 上游原始字段，语义请参照对应接口文档
- `pe`: 上游原始字段，语义请参照对应接口文档
- `pe_ttm`: 上游原始字段，语义请参照对应接口文档
- `pb`: 上游原始字段，语义请参照对应接口文档
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `index_monthly`

- API: `index_monthly`
- Raw 表: `raw.index_monthly_bar`（DAO: `raw_index_monthly_bar`）
- Core 表: `core.index_monthly_serving`（DAO: `index_monthly_serving`）
- 显式请求 fields（11）: ts_code, trade_date, close, open, high, low, pre_close, change, pct_chg, vol, amount
- 支持任务: backfill_index_series.index_monthly, sync_history.index_monthly
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `close`: 收盘价
- `open`: 开盘价
- `high`: 最高价
- `low`: 最低价
- `pre_close`: 昨收价
- `change`: 涨跌额（上游原始字段）
- `pct_chg`: 涨跌幅（系统标准字段）
- `vol`: 成交量
- `amount`: 成交额
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `period_start_date`: 日期字段（具体语义以接口文档为准）
- `trade_date`: 交易日
- `open`: 开盘价
- `high`: 最高价
- `low`: 最低价
- `close`: 收盘价
- `pre_close`: 昨收价
- `change_amount`: 涨跌额（系统标准字段）
- `pct_chg`: 涨跌幅（系统标准字段）
- `vol`: 成交量
- `amount`: 成交额
- `source`: 数据来源标识（如 api / derived_daily）
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `index_weekly`

- API: `index_weekly`
- Raw 表: `raw.index_weekly_bar`（DAO: `raw_index_weekly_bar`）
- Core 表: `core.index_weekly_serving`（DAO: `index_weekly_serving`）
- 显式请求 fields（11）: ts_code, trade_date, close, open, high, low, pre_close, change, pct_chg, vol, amount
- 支持任务: backfill_index_series.index_weekly, sync_history.index_weekly
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `close`: 收盘价
- `open`: 开盘价
- `high`: 最高价
- `low`: 最低价
- `pre_close`: 昨收价
- `change`: 涨跌额（上游原始字段）
- `pct_chg`: 涨跌幅（系统标准字段）
- `vol`: 成交量
- `amount`: 成交额
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `period_start_date`: 日期字段（具体语义以接口文档为准）
- `trade_date`: 交易日
- `open`: 开盘价
- `high`: 最高价
- `low`: 最低价
- `close`: 收盘价
- `pre_close`: 昨收价
- `change_amount`: 涨跌额（系统标准字段）
- `pct_chg`: 涨跌幅（系统标准字段）
- `vol`: 成交量
- `amount`: 成交额
- `source`: 数据来源标识（如 api / derived_daily）
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `index_weight`

- API: `index_weight`
- Raw 表: `raw.index_weight`（DAO: `raw_index_weight`）
- Core 表: `core.index_weight`（DAO: `index_weight`）
- 显式请求 fields（4）: index_code, con_code, trade_date, weight
- 支持任务: backfill_index_series.index_weight, sync_history.index_weight
- Raw 字段释义:
- `index_code`: 指数代码
- `trade_date`: 交易日
- `con_code`: 成分代码
- `weight`: 权重
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `index_code`: 指数代码
- `trade_date`: 交易日
- `con_code`: 成分代码
- `weight`: 权重
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `kpl_concept_cons`

- API: `kpl_concept_cons`
- Raw 表: `raw.kpl_concept_cons`（DAO: `raw_kpl_concept_cons`）
- Core 表: `core.kpl_concept_cons`（DAO: `kpl_concept_cons`）
- 显式请求 fields（8）: ts_code, name, con_name, con_code, trade_date, desc, hot_num, ts_name
- 支持任务: backfill_by_trade_date.kpl_concept_cons, sync_daily.kpl_concept_cons, sync_history.kpl_concept_cons
- Raw 字段释义:
- `trade_date`: 交易日
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `con_code`: 成分代码
- `name`: 名称
- `con_name`: 上游原始字段，语义请参照对应接口文档
- `ts_name`: 上游原始字段，语义请参照对应接口文档
- `desc`: 上游原始字段，语义请参照对应接口文档
- `hot_num`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `trade_date`: 交易日
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `con_code`: 成分代码
- `name`: 名称
- `con_name`: 上游原始字段，语义请参照对应接口文档
- `ts_name`: 上游原始字段，语义请参照对应接口文档
- `desc`: 上游原始字段，语义请参照对应接口文档
- `hot_num`: 上游原始字段，语义请参照对应接口文档
- `raw_payload`: 原始响应载荷
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `kpl_list`

- API: `kpl_list`
- Raw 表: `raw.kpl_list`（DAO: `raw_kpl_list`）
- Core 表: `core.kpl_list`（DAO: `kpl_list`）
- 显式请求 fields（24）: ts_code, name, trade_date, lu_time, ld_time, open_time, last_time, lu_desc, tag, theme, net_change, bid_amount, status, bid_change, bid_turnover, lu_bid_vol, pct_chg, bid_pct_chg, rt_pct_chg, limit_order, amount, turnover_rate, free_float, lu_limit_order
- 支持任务: backfill_by_date_range.kpl_list, sync_daily.kpl_list, sync_history.kpl_list
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `tag`: 上游原始字段，语义请参照对应接口文档
- `name`: 名称
- `lu_time`: 时间字段（具体语义以接口文档为准）
- `ld_time`: 时间字段（具体语义以接口文档为准）
- `open_time`: 时间字段（具体语义以接口文档为准）
- `last_time`: 时间字段（具体语义以接口文档为准）
- `lu_desc`: 上游原始字段，语义请参照对应接口文档
- `theme`: 上游原始字段，语义请参照对应接口文档
- `net_change`: 上游原始字段，语义请参照对应接口文档
- `bid_amount`: 上游原始字段，语义请参照对应接口文档
- `status`: 上游原始字段，语义请参照对应接口文档
- `bid_change`: 上游原始字段，语义请参照对应接口文档
- `bid_turnover`: 上游原始字段，语义请参照对应接口文档
- `lu_bid_vol`: 上游原始字段，语义请参照对应接口文档
- `pct_chg`: 涨跌幅（系统标准字段）
- `bid_pct_chg`: 上游原始字段，语义请参照对应接口文档
- `rt_pct_chg`: 上游原始字段，语义请参照对应接口文档
- `limit_order`: 上游原始字段，语义请参照对应接口文档
- `amount`: 成交额
- `turnover_rate`: 换手率
- `free_float`: 上游原始字段，语义请参照对应接口文档
- `lu_limit_order`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `tag`: 上游原始字段，语义请参照对应接口文档
- `name`: 名称
- `lu_time`: 时间字段（具体语义以接口文档为准）
- `ld_time`: 时间字段（具体语义以接口文档为准）
- `open_time`: 时间字段（具体语义以接口文档为准）
- `last_time`: 时间字段（具体语义以接口文档为准）
- `lu_desc`: 上游原始字段，语义请参照对应接口文档
- `theme`: 上游原始字段，语义请参照对应接口文档
- `net_change`: 上游原始字段，语义请参照对应接口文档
- `bid_amount`: 上游原始字段，语义请参照对应接口文档
- `status`: 上游原始字段，语义请参照对应接口文档
- `bid_change`: 上游原始字段，语义请参照对应接口文档
- `bid_turnover`: 上游原始字段，语义请参照对应接口文档
- `lu_bid_vol`: 上游原始字段，语义请参照对应接口文档
- `pct_chg`: 涨跌幅（系统标准字段）
- `bid_pct_chg`: 上游原始字段，语义请参照对应接口文档
- `rt_pct_chg`: 上游原始字段，语义请参照对应接口文档
- `limit_order`: 上游原始字段，语义请参照对应接口文档
- `amount`: 成交额
- `turnover_rate`: 换手率
- `free_float`: 上游原始字段，语义请参照对应接口文档
- `lu_limit_order`: 上游原始字段，语义请参照对应接口文档
- `raw_payload`: 原始响应载荷
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `limit_cpt_list`

- API: `limit_cpt_list`
- Raw 表: `raw.limit_cpt_list`（DAO: `raw_limit_cpt_list`）
- Core 表: `core.limit_cpt_list`（DAO: `limit_cpt_list`）
- 显式请求 fields（9）: ts_code, name, trade_date, days, up_stat, cons_nums, up_nums, pct_chg, rank
- 支持任务: backfill_by_trade_date.limit_cpt_list, sync_daily.limit_cpt_list, sync_history.limit_cpt_list
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `name`: 名称
- `days`: 上游原始字段，语义请参照对应接口文档
- `up_stat`: 上游原始字段，语义请参照对应接口文档
- `cons_nums`: 上游原始字段，语义请参照对应接口文档
- `up_nums`: 上游原始字段，语义请参照对应接口文档
- `pct_chg`: 涨跌幅（系统标准字段）
- `rank`: 排名
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `name`: 名称
- `days`: 上游原始字段，语义请参照对应接口文档
- `up_stat`: 上游原始字段，语义请参照对应接口文档
- `cons_nums`: 上游原始字段，语义请参照对应接口文档
- `up_nums`: 上游原始字段，语义请参照对应接口文档
- `pct_chg`: 涨跌幅（系统标准字段）
- `rank`: 排名
- `raw_payload`: 原始响应载荷
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `limit_list_d`

- API: `limit_list_d`
- Raw 表: `raw.limit_list`（DAO: `raw_limit_list`）
- Core 表: `core.equity_limit_list`（DAO: `equity_limit_list`）
- 显式请求 fields（18）: trade_date, ts_code, industry, name, close, pct_chg, amount, limit_amount, float_mv, total_mv, turnover_ratio, fd_amount, first_time, last_time, open_times, up_stat, limit_times, limit
- 支持任务: backfill_by_trade_date.limit_list_d, sync_daily.limit_list_d, sync_history.limit_list_d
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `limit`: 上游原始字段，语义请参照对应接口文档
- `industry`: 行业分类
- `name`: 名称
- `close`: 收盘价
- `pct_chg`: 涨跌幅（系统标准字段）
- `amount`: 成交额
- `limit_amount`: 上游原始字段，语义请参照对应接口文档
- `float_mv`: 流通市值
- `total_mv`: 总市值
- `turnover_ratio`: 上游原始字段，语义请参照对应接口文档
- `fd_amount`: 上游原始字段，语义请参照对应接口文档
- `first_time`: 时间字段（具体语义以接口文档为准）
- `last_time`: 时间字段（具体语义以接口文档为准）
- `open_times`: 上游原始字段，语义请参照对应接口文档
- `up_stat`: 上游原始字段，语义请参照对应接口文档
- `limit_times`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `limit_type`: 上游原始字段，语义请参照对应接口文档
- `industry`: 行业分类
- `name`: 名称
- `close`: 收盘价
- `pct_chg`: 涨跌幅（系统标准字段）
- `amount`: 成交额
- `limit_amount`: 上游原始字段，语义请参照对应接口文档
- `float_mv`: 流通市值
- `total_mv`: 总市值
- `turnover_ratio`: 上游原始字段，语义请参照对应接口文档
- `fd_amount`: 上游原始字段，语义请参照对应接口文档
- `first_time`: 时间字段（具体语义以接口文档为准）
- `last_time`: 时间字段（具体语义以接口文档为准）
- `open_times`: 上游原始字段，语义请参照对应接口文档
- `up_stat`: 上游原始字段，语义请参照对应接口文档
- `limit_times`: 上游原始字段，语义请参照对应接口文档
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `limit_list_ths`

- API: `limit_list_ths`
- Raw 表: `raw.limit_list_ths`（DAO: `raw_limit_list_ths`）
- Core 表: `core.limit_list_ths`（DAO: `-`）
- 显式请求 fields（24）: trade_date, ts_code, name, price, pct_chg, open_num, lu_desc, limit_type, tag, status, first_lu_time, last_lu_time, first_ld_time, last_ld_time, limit_order, limit_amount, turnover_rate, free_float, lu_limit_order, limit_up_suc_rate, turnover, rise_rate, sum_float, market_type
- 支持任务: backfill_by_trade_date.limit_list_ths, sync_daily.limit_list_ths, sync_history.limit_list_ths
- Raw 字段释义:
- `trade_date`: 交易日
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `query_limit_type`: 请求上下文字段
- `query_market`: 请求上下文：market
- `name`: 名称
- `price`: 上游原始字段，语义请参照对应接口文档
- `pct_chg`: 涨跌幅（系统标准字段）
- `open_num`: 上游原始字段，语义请参照对应接口文档
- `lu_desc`: 上游原始字段，语义请参照对应接口文档
- `limit_type`: 上游原始字段，语义请参照对应接口文档
- `tag`: 上游原始字段，语义请参照对应接口文档
- `status`: 上游原始字段，语义请参照对应接口文档
- `first_lu_time`: 时间字段（具体语义以接口文档为准）
- `last_lu_time`: 时间字段（具体语义以接口文档为准）
- `first_ld_time`: 时间字段（具体语义以接口文档为准）
- `last_ld_time`: 时间字段（具体语义以接口文档为准）
- `limit_order`: 上游原始字段，语义请参照对应接口文档
- `limit_amount`: 上游原始字段，语义请参照对应接口文档
- `turnover_rate`: 换手率
- `free_float`: 上游原始字段，语义请参照对应接口文档
- `lu_limit_order`: 上游原始字段，语义请参照对应接口文档
- `limit_up_suc_rate`: 上游原始字段，语义请参照对应接口文档
- `turnover`: 上游原始字段，语义请参照对应接口文档
- `rise_rate`: 上游原始字段，语义请参照对应接口文档
- `sum_float`: 上游原始字段，语义请参照对应接口文档
- `market_type`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- 无

### `limit_step`

- API: `limit_step`
- Raw 表: `raw.limit_step`（DAO: `raw_limit_step`）
- Core 表: `core.limit_step`（DAO: `limit_step`）
- 显式请求 fields（4）: ts_code, name, trade_date, nums
- 支持任务: backfill_by_trade_date.limit_step, sync_daily.limit_step, sync_history.limit_step
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `nums`: 上游原始字段，语义请参照对应接口文档
- `name`: 名称
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `nums`: 上游原始字段，语义请参照对应接口文档
- `name`: 名称
- `raw_payload`: 原始响应载荷
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `moneyflow`

- API: `moneyflow`
- Raw 表: `raw.moneyflow`（DAO: `raw_moneyflow`）
- Core 表: `core.equity_moneyflow`（DAO: `equity_moneyflow`）
- 显式请求 fields（20）: ts_code, trade_date, buy_sm_vol, buy_sm_amount, sell_sm_vol, sell_sm_amount, buy_md_vol, buy_md_amount, sell_md_vol, sell_md_amount, buy_lg_vol, buy_lg_amount, sell_lg_vol, sell_lg_amount, buy_elg_vol, buy_elg_amount, sell_elg_vol, sell_elg_amount, net_mf_vol, net_mf_amount
- 支持任务: backfill_by_trade_date.moneyflow, sync_daily.moneyflow, sync_history.moneyflow
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `buy_sm_vol`: 上游原始字段，语义请参照对应接口文档
- `buy_sm_amount`: 上游原始字段，语义请参照对应接口文档
- `sell_sm_vol`: 上游原始字段，语义请参照对应接口文档
- `sell_sm_amount`: 上游原始字段，语义请参照对应接口文档
- `buy_md_vol`: 上游原始字段，语义请参照对应接口文档
- `buy_md_amount`: 上游原始字段，语义请参照对应接口文档
- `sell_md_vol`: 上游原始字段，语义请参照对应接口文档
- `sell_md_amount`: 上游原始字段，语义请参照对应接口文档
- `buy_lg_vol`: 上游原始字段，语义请参照对应接口文档
- `buy_lg_amount`: 上游原始字段，语义请参照对应接口文档
- `sell_lg_vol`: 上游原始字段，语义请参照对应接口文档
- `sell_lg_amount`: 上游原始字段，语义请参照对应接口文档
- `buy_elg_vol`: 上游原始字段，语义请参照对应接口文档
- `buy_elg_amount`: 上游原始字段，语义请参照对应接口文档
- `sell_elg_vol`: 上游原始字段，语义请参照对应接口文档
- `sell_elg_amount`: 上游原始字段，语义请参照对应接口文档
- `net_mf_vol`: 上游原始字段，语义请参照对应接口文档
- `net_mf_amount`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `buy_sm_vol`: 上游原始字段，语义请参照对应接口文档
- `buy_sm_amount`: 上游原始字段，语义请参照对应接口文档
- `sell_sm_vol`: 上游原始字段，语义请参照对应接口文档
- `sell_sm_amount`: 上游原始字段，语义请参照对应接口文档
- `buy_md_vol`: 上游原始字段，语义请参照对应接口文档
- `buy_md_amount`: 上游原始字段，语义请参照对应接口文档
- `sell_md_vol`: 上游原始字段，语义请参照对应接口文档
- `sell_md_amount`: 上游原始字段，语义请参照对应接口文档
- `buy_lg_vol`: 上游原始字段，语义请参照对应接口文档
- `buy_lg_amount`: 上游原始字段，语义请参照对应接口文档
- `sell_lg_vol`: 上游原始字段，语义请参照对应接口文档
- `sell_lg_amount`: 上游原始字段，语义请参照对应接口文档
- `buy_elg_vol`: 上游原始字段，语义请参照对应接口文档
- `buy_elg_amount`: 上游原始字段，语义请参照对应接口文档
- `sell_elg_vol`: 上游原始字段，语义请参照对应接口文档
- `sell_elg_amount`: 上游原始字段，语义请参照对应接口文档
- `net_mf_vol`: 上游原始字段，语义请参照对应接口文档
- `net_mf_amount`: 上游原始字段，语义请参照对应接口文档
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `stk_holdernumber`

- API: `stk_holdernumber`
- Raw 表: `raw.holdernumber`（DAO: `raw_holder_number`）
- Core 表: `core.equity_holder_number`（DAO: `equity_holder_number`）
- 显式请求 fields（4）: ts_code, ann_date, end_date, holder_num
- 支持任务: backfill_low_frequency.stk_holdernumber, sync_history.stk_holdernumber
- Raw 字段释义:
- `id`: 系统代理主键
- `row_key_hash`: 记录级哈希键（去重与幂等）
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `ann_date`: 公告日
- `end_date`: 报告期/统计截止日期
- `holder_num`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `id`: 系统代理主键
- `row_key_hash`: 记录级哈希键（去重与幂等）
- `event_key_hash`: 事件级哈希键（事件聚合）
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `ann_date`: 公告日
- `end_date`: 报告期/统计截止日期
- `holder_num`: 上游原始字段，语义请参照对应接口文档
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `stk_period_bar_adj_month`

- API: `stk_week_month_adj`
- Raw 表: `raw.stk_period_bar_adj`（DAO: `raw_stk_period_bar_adj`）
- Core 表: `core.stk_period_bar_adj`（DAO: `stk_period_bar_adj`）
- 显式请求 fields（21）: ts_code, trade_date, end_date, freq, open, high, low, close, pre_close, open_qfq, high_qfq, low_qfq, close_qfq, open_hfq, high_hfq, low_hfq, close_hfq, vol, amount, change, pct_chg
- 支持任务: backfill_equity_series.stk_period_bar_adj_month, sync_history.stk_period_bar_adj_month
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `freq`: 上游原始字段，语义请参照对应接口文档
- `end_date`: 报告期/统计截止日期
- `open`: 开盘价
- `high`: 最高价
- `low`: 最低价
- `close`: 收盘价
- `pre_close`: 昨收价
- `open_qfq`: 上游原始字段，语义请参照对应接口文档
- `high_qfq`: 上游原始字段，语义请参照对应接口文档
- `low_qfq`: 上游原始字段，语义请参照对应接口文档
- `close_qfq`: 上游原始字段，语义请参照对应接口文档
- `open_hfq`: 上游原始字段，语义请参照对应接口文档
- `high_hfq`: 上游原始字段，语义请参照对应接口文档
- `low_hfq`: 上游原始字段，语义请参照对应接口文档
- `close_hfq`: 上游原始字段，语义请参照对应接口文档
- `vol`: 成交量
- `amount`: 成交额
- `change`: 涨跌额（上游原始字段）
- `pct_chg`: 涨跌幅（系统标准字段）
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `freq`: 上游原始字段，语义请参照对应接口文档
- `end_date`: 报告期/统计截止日期
- `open`: 开盘价
- `high`: 最高价
- `low`: 最低价
- `close`: 收盘价
- `pre_close`: 昨收价
- `open_qfq`: 上游原始字段，语义请参照对应接口文档
- `high_qfq`: 上游原始字段，语义请参照对应接口文档
- `low_qfq`: 上游原始字段，语义请参照对应接口文档
- `close_qfq`: 上游原始字段，语义请参照对应接口文档
- `open_hfq`: 上游原始字段，语义请参照对应接口文档
- `high_hfq`: 上游原始字段，语义请参照对应接口文档
- `low_hfq`: 上游原始字段，语义请参照对应接口文档
- `close_hfq`: 上游原始字段，语义请参照对应接口文档
- `vol`: 成交量
- `amount`: 成交额
- `change_amount`: 涨跌额（系统标准字段）
- `pct_chg`: 涨跌幅（系统标准字段）
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `stk_period_bar_adj_week`

- API: `stk_week_month_adj`
- Raw 表: `raw.stk_period_bar_adj`（DAO: `raw_stk_period_bar_adj`）
- Core 表: `core.stk_period_bar_adj`（DAO: `stk_period_bar_adj`）
- 显式请求 fields（21）: ts_code, trade_date, end_date, freq, open, high, low, close, pre_close, open_qfq, high_qfq, low_qfq, close_qfq, open_hfq, high_hfq, low_hfq, close_hfq, vol, amount, change, pct_chg
- 支持任务: backfill_equity_series.stk_period_bar_adj_week, sync_history.stk_period_bar_adj_week
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `freq`: 上游原始字段，语义请参照对应接口文档
- `end_date`: 报告期/统计截止日期
- `open`: 开盘价
- `high`: 最高价
- `low`: 最低价
- `close`: 收盘价
- `pre_close`: 昨收价
- `open_qfq`: 上游原始字段，语义请参照对应接口文档
- `high_qfq`: 上游原始字段，语义请参照对应接口文档
- `low_qfq`: 上游原始字段，语义请参照对应接口文档
- `close_qfq`: 上游原始字段，语义请参照对应接口文档
- `open_hfq`: 上游原始字段，语义请参照对应接口文档
- `high_hfq`: 上游原始字段，语义请参照对应接口文档
- `low_hfq`: 上游原始字段，语义请参照对应接口文档
- `close_hfq`: 上游原始字段，语义请参照对应接口文档
- `vol`: 成交量
- `amount`: 成交额
- `change`: 涨跌额（上游原始字段）
- `pct_chg`: 涨跌幅（系统标准字段）
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `freq`: 上游原始字段，语义请参照对应接口文档
- `end_date`: 报告期/统计截止日期
- `open`: 开盘价
- `high`: 最高价
- `low`: 最低价
- `close`: 收盘价
- `pre_close`: 昨收价
- `open_qfq`: 上游原始字段，语义请参照对应接口文档
- `high_qfq`: 上游原始字段，语义请参照对应接口文档
- `low_qfq`: 上游原始字段，语义请参照对应接口文档
- `close_qfq`: 上游原始字段，语义请参照对应接口文档
- `open_hfq`: 上游原始字段，语义请参照对应接口文档
- `high_hfq`: 上游原始字段，语义请参照对应接口文档
- `low_hfq`: 上游原始字段，语义请参照对应接口文档
- `close_hfq`: 上游原始字段，语义请参照对应接口文档
- `vol`: 成交量
- `amount`: 成交额
- `change_amount`: 涨跌额（系统标准字段）
- `pct_chg`: 涨跌幅（系统标准字段）
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `stk_period_bar_month`

- API: `stk_weekly_monthly`
- Raw 表: `raw.stk_period_bar`（DAO: `raw_stk_period_bar`）
- Core 表: `core.stk_period_bar`（DAO: `stk_period_bar`）
- 显式请求 fields（13）: ts_code, trade_date, end_date, freq, open, high, low, close, pre_close, vol, amount, change, pct_chg
- 支持任务: backfill_equity_series.stk_period_bar_month, sync_history.stk_period_bar_month
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `freq`: 上游原始字段，语义请参照对应接口文档
- `end_date`: 报告期/统计截止日期
- `open`: 开盘价
- `high`: 最高价
- `low`: 最低价
- `close`: 收盘价
- `pre_close`: 昨收价
- `vol`: 成交量
- `amount`: 成交额
- `change`: 涨跌额（上游原始字段）
- `pct_chg`: 涨跌幅（系统标准字段）
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `freq`: 上游原始字段，语义请参照对应接口文档
- `end_date`: 报告期/统计截止日期
- `open`: 开盘价
- `high`: 最高价
- `low`: 最低价
- `close`: 收盘价
- `pre_close`: 昨收价
- `vol`: 成交量
- `amount`: 成交额
- `change_amount`: 涨跌额（系统标准字段）
- `pct_chg`: 涨跌幅（系统标准字段）
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `stk_period_bar_week`

- API: `stk_weekly_monthly`
- Raw 表: `raw.stk_period_bar`（DAO: `raw_stk_period_bar`）
- Core 表: `core.stk_period_bar`（DAO: `stk_period_bar`）
- 显式请求 fields（13）: ts_code, trade_date, end_date, freq, open, high, low, close, pre_close, vol, amount, change, pct_chg
- 支持任务: backfill_equity_series.stk_period_bar_week, sync_history.stk_period_bar_week
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `freq`: 上游原始字段，语义请参照对应接口文档
- `end_date`: 报告期/统计截止日期
- `open`: 开盘价
- `high`: 最高价
- `low`: 最低价
- `close`: 收盘价
- `pre_close`: 昨收价
- `vol`: 成交量
- `amount`: 成交额
- `change`: 涨跌额（上游原始字段）
- `pct_chg`: 涨跌幅（系统标准字段）
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `freq`: 上游原始字段，语义请参照对应接口文档
- `end_date`: 报告期/统计截止日期
- `open`: 开盘价
- `high`: 最高价
- `low`: 最低价
- `close`: 收盘价
- `pre_close`: 昨收价
- `vol`: 成交量
- `amount`: 成交额
- `change_amount`: 涨跌额（系统标准字段）
- `pct_chg`: 涨跌幅（系统标准字段）
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `stock_basic`

- API: `stock_basic`
- Raw 表: `raw.stock_basic`（DAO: `raw_stock_basic`）
- Core 表: `core.security`（DAO: `security`）
- 显式请求 fields（17）: ts_code, symbol, name, area, industry, fullname, enname, cnspell, market, exchange, curr_type, list_status, list_date, delist_date, is_hs, act_name, act_ent_type
- 支持任务: sync_history.stock_basic
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `symbol`: 交易代码短码
- `name`: 名称
- `area`: 地区
- `industry`: 行业分类
- `fullname`: 上游原始字段，语义请参照对应接口文档
- `enname`: 上游原始字段，语义请参照对应接口文档
- `cnspell`: 上游原始字段，语义请参照对应接口文档
- `market`: 市场类型
- `exchange`: 交易所
- `curr_type`: 上游原始字段，语义请参照对应接口文档
- `list_status`: 上市状态
- `list_date`: 上市日期
- `delist_date`: 退市日期
- `is_hs`: 上游原始字段，语义请参照对应接口文档
- `act_name`: 上游原始字段，语义请参照对应接口文档
- `act_ent_type`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `symbol`: 交易代码短码
- `name`: 名称
- `area`: 地区
- `industry`: 行业分类
- `fullname`: 上游原始字段，语义请参照对应接口文档
- `enname`: 上游原始字段，语义请参照对应接口文档
- `cnspell`: 上游原始字段，语义请参照对应接口文档
- `market`: 市场类型
- `exchange`: 交易所
- `curr_type`: 上游原始字段，语义请参照对应接口文档
- `list_status`: 上市状态
- `list_date`: 上市日期
- `delist_date`: 退市日期
- `is_hs`: 上游原始字段，语义请参照对应接口文档
- `act_name`: 上游原始字段，语义请参照对应接口文档
- `act_ent_type`: 上游原始字段，语义请参照对应接口文档
- `security_type`: 上游原始字段，语义请参照对应接口文档
- `source`: 数据来源标识（如 api / derived_daily）
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `ths_daily`

- API: `ths_daily`
- Raw 表: `raw.ths_daily`（DAO: `raw_ths_daily`）
- Core 表: `core.ths_daily`（DAO: `-`）
- 显式请求 fields（14）: ts_code, trade_date, close, open, high, low, pre_close, avg_price, change, pct_change, vol, turnover_rate, total_mv, float_mv
- 支持任务: backfill_by_date_range.ths_daily, sync_daily.ths_daily, sync_history.ths_daily
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `close`: 收盘价
- `open`: 开盘价
- `high`: 最高价
- `low`: 最低价
- `pre_close`: 昨收价
- `avg_price`: 上游原始字段，语义请参照对应接口文档
- `change`: 涨跌额（上游原始字段）
- `pct_change`: 涨跌幅（上游原始字段）
- `vol`: 成交量
- `turnover_rate`: 换手率
- `total_mv`: 总市值
- `float_mv`: 流通市值
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- 无

### `ths_hot`

- API: `ths_hot`
- Raw 表: `raw.ths_hot`（DAO: `raw_ths_hot`）
- Core 表: `core.ths_hot`（DAO: `-`）
- 显式请求 fields（11）: trade_date, data_type, ts_code, ts_name, rank, pct_change, current_price, concept, rank_reason, hot, rank_time
- 支持任务: backfill_by_trade_date.ths_hot, sync_daily.ths_hot, sync_history.ths_hot
- Raw 字段释义:
- `trade_date`: 交易日
- `data_type`: 上游原始字段，语义请参照对应接口文档
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `rank_time`: 榜单时间戳
- `query_market`: 请求上下文：market
- `query_is_new`: 请求上下文：is_new
- `ts_name`: 上游原始字段，语义请参照对应接口文档
- `rank`: 排名
- `pct_change`: 涨跌幅（上游原始字段）
- `current_price`: 上游原始字段，语义请参照对应接口文档
- `concept`: 所属概念
- `rank_reason`: 上榜原因
- `hot`: 热度值
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- 无

### `ths_index`

- API: `ths_index`
- Raw 表: `raw.ths_index`（DAO: `raw_ths_index`）
- Core 表: `core.ths_index`（DAO: `ths_index`）
- 显式请求 fields（6）: ts_code, name, count, exchange, list_date, type
- 支持任务: sync_history.ths_index
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `name`: 名称
- `count`: 上游原始字段，语义请参照对应接口文档
- `exchange`: 交易所
- `list_date`: 上市日期
- `type`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `name`: 名称
- `count`: 上游原始字段，语义请参照对应接口文档
- `exchange`: 交易所
- `list_date`: 上市日期
- `type`: 上游原始字段，语义请参照对应接口文档
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `ths_member`

- API: `ths_member`
- Raw 表: `raw.ths_member`（DAO: `raw_ths_member`）
- Core 表: `core.ths_member`（DAO: `-`）
- 显式请求 fields（7）: ts_code, con_code, con_name, weight, in_date, out_date, is_new
- 支持任务: sync_history.ths_member
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `con_code`: 成分代码
- `con_name`: 上游原始字段，语义请参照对应接口文档
- `weight`: 权重
- `in_date`: 日期字段（具体语义以接口文档为准）
- `out_date`: 日期字段（具体语义以接口文档为准）
- `is_new`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- 无

### `top_list`

- API: `top_list`
- Raw 表: `raw.top_list`（DAO: `raw_top_list`）
- Core 表: `core.equity_top_list`（DAO: `equity_top_list`）
- 显式请求 fields（15）: trade_date, ts_code, name, close, pct_change, turnover_rate, amount, l_sell, l_buy, l_amount, net_amount, net_rate, amount_rate, float_values, reason
- 支持任务: backfill_by_trade_date.top_list, sync_daily.top_list, sync_history.top_list
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `reason`: 上游原始字段，语义请参照对应接口文档
- `name`: 名称
- `close`: 收盘价
- `pct_change`: 涨跌幅（上游原始字段）
- `turnover_rate`: 换手率
- `amount`: 成交额
- `l_sell`: 上游原始字段，语义请参照对应接口文档
- `l_buy`: 上游原始字段，语义请参照对应接口文档
- `l_amount`: 上游原始字段，语义请参照对应接口文档
- `net_amount`: 上游原始字段，语义请参照对应接口文档
- `net_rate`: 上游原始字段，语义请参照对应接口文档
- `amount_rate`: 上游原始字段，语义请参照对应接口文档
- `float_values`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `reason`: 上游原始字段，语义请参照对应接口文档
- `reason_hash`: 上游原始字段，语义请参照对应接口文档
- `name`: 名称
- `close`: 收盘价
- `pct_chg`: 涨跌幅（系统标准字段）
- `turnover_rate`: 换手率
- `amount`: 成交额
- `l_sell`: 上游原始字段，语义请参照对应接口文档
- `l_buy`: 上游原始字段，语义请参照对应接口文档
- `l_amount`: 上游原始字段，语义请参照对应接口文档
- `net_amount`: 上游原始字段，语义请参照对应接口文档
- `net_rate`: 上游原始字段，语义请参照对应接口文档
- `amount_rate`: 上游原始字段，语义请参照对应接口文档
- `float_values`: 上游原始字段，语义请参照对应接口文档
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `trade_cal`

- API: `trade_cal`
- Raw 表: `raw.trade_cal`（DAO: `raw_trade_cal`）
- Core 表: `core.trade_calendar`（DAO: `trade_calendar`）
- 显式请求 fields（4）: exchange, cal_date, is_open, pretrade_date
- 支持任务: backfill_trade_cal.trade_cal, sync_history.trade_cal
- Raw 字段释义:
- `exchange`: 交易所
- `cal_date`: 日历日期
- `is_open`: 是否开市
- `pretrade_date`: 日期字段（具体语义以接口文档为准）
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `exchange`: 交易所
- `trade_date`: 交易日
- `is_open`: 是否开市
- `pretrade_date`: 日期字段（具体语义以接口文档为准）

### `us_basic`

- API: `us_basic`
- Raw 表: `raw.us_basic`（DAO: `raw_us_basic`）
- Core 表: `core.us_security`（DAO: `us_security`）
- 显式请求 fields（6）: ts_code, name, enname, classify, list_date, delist_date
- 支持任务: sync_history.us_basic
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `name`: 名称
- `enname`: 上游原始字段，语义请参照对应接口文档
- `classify`: 上游原始字段，语义请参照对应接口文档
- `list_date`: 上市日期
- `delist_date`: 退市日期
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `name`: 名称
- `enname`: 上游原始字段，语义请参照对应接口文档
- `classify`: 上游原始字段，语义请参照对应接口文档
- `list_date`: 上市日期
- `delist_date`: 退市日期
- `source`: 数据来源标识（如 api / derived_daily）
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

## 维护方式

每次新增或改动数据集后，执行：

```bash
python scripts/generate_dataset_catalog.py
```

然后提交更新后的 `docs/datasets/dataset-catalog.md`。
