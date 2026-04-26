# 数据集能力与字段说明（自动生成）

- 生成时间: `2026-04-19 23:56:14`
- 状态: 历史自动生成快照，已过期
- 数据来源: `SYNC_SERVICE_REGISTRY`、`DAOFactory`、`JOB_SPEC_REGISTRY`
- 适用范围: 现有可同步数据集（raw/core 主链路）

> 当前口径：本文只保留为 2026-04-19 的历史快照，不再作为数据集事实源。
> 当前数据集身份、中文名、日期模型、输入能力、表映射等事实应以 `src/foundation/datasets/**` 的 `DatasetDefinition` 投影为准；执行入口应以 `DatasetExecutionPlan + action=maintain + TaskRun` 为准。
> 本文中 `sync_daily / backfill_* / sync_history` 等“支持任务”列是旧执行模型快照，不应用于新增 UI、API 或调度设计。

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
| `adj_factor` | `adj_factor` | `raw_tushare.adj_factor` | `core.equity_adj_factor` | 3 | `trade_date` | backfill_equity_series.adj_factor, sync_daily.adj_factor, sync_history.adj_factor |
| `biying_equity_daily` | `equity_daily_bar` | `-` | `raw_biying.equity_daily_bar` | 0 | `trade_date` | sync_daily.biying_equity_daily, sync_history.biying_equity_daily |
| `biying_moneyflow` | `moneyflow` | `raw_biying.moneyflow` | `raw_biying.moneyflow` | 0 | `trade_date` | sync_daily.biying_moneyflow, sync_history.biying_moneyflow |
| `block_trade` | `block_trade` | `raw_tushare.block_trade` | `core_serving.equity_block_trade` | 7 | `trade_date` | backfill_by_trade_date.block_trade, sync_daily.block_trade, sync_history.block_trade |
| `broker_recommend` | `broker_recommend` | `raw_tushare.broker_recommend` | `core_serving.broker_recommend` | 14 | `None` | backfill_by_month.broker_recommend, sync_daily.broker_recommend, sync_history.broker_recommend |
| `cyq_perf` | `cyq_perf` | `raw_tushare.cyq_perf` | `core_serving.equity_cyq_perf` | 11 | `trade_date` | sync_daily.cyq_perf, sync_history.cyq_perf |
| `daily` | `daily` | `raw_tushare.daily` | `core_serving.equity_daily_bar` | 11 | `trade_date` | backfill_equity_series.daily, sync_daily.daily, sync_history.daily |
| `daily_basic` | `daily_basic` | `raw_tushare.daily_basic` | `core_serving.equity_daily_basic` | 18 | `trade_date` | backfill_by_trade_date.daily_basic, sync_daily.daily_basic, sync_history.daily_basic |
| `dc_daily` | `dc_daily` | `raw_tushare.dc_daily` | `core_serving.dc_daily` | 12 | `trade_date` | backfill_by_date_range.dc_daily, sync_daily.dc_daily, sync_history.dc_daily |
| `dc_hot` | `dc_hot` | `raw_tushare.dc_hot` | `core_serving.dc_hot` | 8 | `trade_date` | backfill_by_trade_date.dc_hot, sync_daily.dc_hot, sync_history.dc_hot |
| `dc_index` | `dc_index` | `raw_tushare.dc_index` | `core_serving.dc_index` | 13 | `trade_date` | backfill_by_date_range.dc_index, sync_daily.dc_index, sync_history.dc_index |
| `dc_member` | `dc_member` | `raw_tushare.dc_member` | `core_serving.dc_member` | 4 | `trade_date` | backfill_by_trade_date.dc_member, sync_daily.dc_member, sync_history.dc_member |
| `dividend` | `dividend` | `raw_tushare.dividend` | `core_serving.equity_dividend` | 16 | `None` | backfill_low_frequency.dividend, sync_history.dividend |
| `etf_basic` | `etf_basic` | `raw_tushare.etf_basic` | `core_serving.etf_basic` | 14 | `None` | sync_history.etf_basic |
| `etf_index` | `etf_index` | `raw_tushare.etf_index` | `core_serving.etf_index` | 8 | `None` | sync_history.etf_index |
| `fund_adj` | `fund_adj` | `raw_tushare.fund_adj` | `core.fund_adj_factor` | 3 | `trade_date` | backfill_fund_series.fund_adj, sync_daily.fund_adj, sync_history.fund_adj |
| `fund_daily` | `fund_daily` | `raw_tushare.fund_daily` | `core_serving.fund_daily_bar` | 11 | `trade_date` | backfill_fund_series.fund_daily, sync_daily.fund_daily, sync_history.fund_daily |
| `hk_basic` | `hk_basic` | `raw_tushare.hk_basic` | `core_serving.hk_security` | 12 | `None` | sync_history.hk_basic |
| `index_basic` | `index_basic` | `raw_tushare.index_basic` | `core_serving.index_basic` | 13 | `None` | sync_history.index_basic |
| `index_daily` | `index_daily` | `raw_tushare.index_daily` | `core_serving.index_daily_serving` | 11 | `trade_date` | backfill_index_series.index_daily, sync_daily.index_daily, sync_history.index_daily |
| `index_daily_basic` | `index_dailybasic` | `raw_tushare.index_daily_basic` | `core_serving.index_daily_basic` | 12 | `trade_date` | backfill_index_series.index_daily_basic, sync_history.index_daily_basic |
| `index_monthly` | `index_monthly` | `raw_tushare.index_monthly_bar` | `core_serving.index_monthly_serving` | 11 | `trade_date` | backfill_index_series.index_monthly, sync_history.index_monthly |
| `index_weekly` | `index_weekly` | `raw_tushare.index_weekly_bar` | `core_serving.index_weekly_serving` | 11 | `trade_date` | backfill_index_series.index_weekly, sync_history.index_weekly |
| `index_weight` | `index_weight` | `raw_tushare.index_weight` | `core_serving.index_weight` | 4 | `trade_date` | backfill_index_series.index_weight, sync_history.index_weight |
| `kpl_concept_cons` | `kpl_concept_cons` | `raw_tushare.kpl_concept_cons` | `core_serving.kpl_concept_cons` | 8 | `trade_date` | backfill_by_trade_date.kpl_concept_cons, sync_daily.kpl_concept_cons, sync_history.kpl_concept_cons |
| `kpl_list` | `kpl_list` | `raw_tushare.kpl_list` | `core_serving.kpl_list` | 24 | `trade_date` | backfill_by_date_range.kpl_list, sync_daily.kpl_list, sync_history.kpl_list |
| `limit_cpt_list` | `limit_cpt_list` | `raw_tushare.limit_cpt_list` | `core_serving.limit_cpt_list` | 9 | `trade_date` | backfill_by_trade_date.limit_cpt_list, sync_daily.limit_cpt_list, sync_history.limit_cpt_list |
| `limit_list_d` | `limit_list_d` | `raw_tushare.limit_list` | `core_serving.equity_limit_list` | 18 | `trade_date` | backfill_by_trade_date.limit_list_d, sync_daily.limit_list_d, sync_history.limit_list_d |
| `limit_list_ths` | `limit_list_ths` | `raw_tushare.limit_list_ths` | `core_serving.limit_list_ths` | 24 | `trade_date` | backfill_by_trade_date.limit_list_ths, sync_daily.limit_list_ths, sync_history.limit_list_ths |
| `limit_step` | `limit_step` | `raw_tushare.limit_step` | `core_serving.limit_step` | 4 | `trade_date` | backfill_by_trade_date.limit_step, sync_daily.limit_step, sync_history.limit_step |
| `margin` | `margin` | `raw_tushare.margin` | `core_serving.equity_margin` | 9 | `trade_date` | backfill_by_trade_date.margin, sync_daily.margin, sync_history.margin |
| `moneyflow` | `moneyflow` | `raw_tushare.moneyflow` | `core_serving.equity_moneyflow` | 20 | `trade_date` | backfill_by_trade_date.moneyflow, sync_daily.moneyflow, sync_history.moneyflow |
| `moneyflow_cnt_ths` | `moneyflow_cnt_ths` | `raw_tushare.moneyflow_cnt_ths` | `core_serving.concept_moneyflow_ths` | 12 | `trade_date` | backfill_by_trade_date.moneyflow_cnt_ths, sync_daily.moneyflow_cnt_ths, sync_history.moneyflow_cnt_ths |
| `moneyflow_dc` | `moneyflow_dc` | `raw_tushare.moneyflow_dc` | `core_serving.equity_moneyflow_dc` | 15 | `trade_date` | backfill_by_trade_date.moneyflow_dc, sync_daily.moneyflow_dc, sync_history.moneyflow_dc |
| `moneyflow_ind_dc` | `moneyflow_ind_dc` | `raw_tushare.moneyflow_ind_dc` | `core_serving.board_moneyflow_dc` | 18 | `trade_date` | backfill_by_trade_date.moneyflow_ind_dc, sync_daily.moneyflow_ind_dc, sync_history.moneyflow_ind_dc |
| `moneyflow_ind_ths` | `moneyflow_ind_ths` | `raw_tushare.moneyflow_ind_ths` | `core_serving.industry_moneyflow_ths` | 12 | `trade_date` | backfill_by_trade_date.moneyflow_ind_ths, sync_daily.moneyflow_ind_ths, sync_history.moneyflow_ind_ths |
| `moneyflow_mkt_dc` | `moneyflow_mkt_dc` | `raw_tushare.moneyflow_mkt_dc` | `core_serving.market_moneyflow_dc` | 15 | `trade_date` | backfill_by_trade_date.moneyflow_mkt_dc, sync_daily.moneyflow_mkt_dc, sync_history.moneyflow_mkt_dc |
| `moneyflow_ths` | `moneyflow_ths` | `raw_tushare.moneyflow_ths` | `core_serving.equity_moneyflow_ths` | 13 | `trade_date` | backfill_by_trade_date.moneyflow_ths, sync_daily.moneyflow_ths, sync_history.moneyflow_ths |
| `stk_factor_pro` | `stk_factor_pro` | `raw_tushare.stk_factor_pro` | `core_serving.equity_factor_pro` | 227 | `trade_date` | backfill_by_trade_date.stk_factor_pro, sync_daily.stk_factor_pro, sync_history.stk_factor_pro |
| `stk_holdernumber` | `stk_holdernumber` | `raw_tushare.holdernumber` | `core_serving.equity_holder_number` | 4 | `None` | backfill_low_frequency.stk_holdernumber, sync_history.stk_holdernumber |
| `stk_limit` | `stk_limit` | `raw_tushare.stk_limit` | `core_serving.equity_stk_limit` | 5 | `trade_date` | sync_daily.stk_limit, sync_history.stk_limit |
| `stk_nineturn` | `stk_nineturn` | `raw_tushare.stk_nineturn` | `core_serving.equity_nineturn` | 13 | `trade_date` | backfill_by_trade_date.stk_nineturn, sync_daily.stk_nineturn, sync_history.stk_nineturn |
| `stk_period_bar_adj_month` | `stk_week_month_adj` | `raw_tushare.stk_period_bar_adj` | `core_serving.stk_period_bar_adj` | 21 | `trade_date` | backfill_equity_series.stk_period_bar_adj_month, sync_daily.stk_period_bar_adj_month, sync_history.stk_period_bar_adj_month |
| `stk_period_bar_adj_week` | `stk_week_month_adj` | `raw_tushare.stk_period_bar_adj` | `core_serving.stk_period_bar_adj` | 21 | `trade_date` | backfill_equity_series.stk_period_bar_adj_week, sync_history.stk_period_bar_adj_week |
| `stk_period_bar_month` | `stk_weekly_monthly` | `raw_tushare.stk_period_bar` | `core_serving.stk_period_bar` | 13 | `trade_date` | backfill_equity_series.stk_period_bar_month, sync_daily.stk_period_bar_month, sync_history.stk_period_bar_month |
| `stk_period_bar_week` | `stk_weekly_monthly` | `raw_tushare.stk_period_bar` | `core_serving.stk_period_bar` | 13 | `trade_date` | backfill_equity_series.stk_period_bar_week, sync_history.stk_period_bar_week |
| `stock_basic` | `stock_basic` | `raw_tushare.stock_basic` | `core_serving.security_serving` | 17 | `None` | sync_history.stock_basic |
| `stock_st` | `stock_st` | `raw_tushare.stock_st` | `core_serving.equity_stock_st` | 5 | `trade_date` | sync_daily.stock_st, sync_history.stock_st |
| `suspend_d` | `suspend_d` | `raw_tushare.suspend_d` | `core_serving.equity_suspend_d` | 4 | `trade_date` | backfill_by_trade_date.suspend_d, sync_daily.suspend_d, sync_history.suspend_d |
| `ths_daily` | `ths_daily` | `raw_tushare.ths_daily` | `core_serving.ths_daily` | 14 | `trade_date` | backfill_by_date_range.ths_daily, sync_daily.ths_daily, sync_history.ths_daily |
| `ths_hot` | `ths_hot` | `raw_tushare.ths_hot` | `core_serving.ths_hot` | 11 | `trade_date` | backfill_by_trade_date.ths_hot, sync_daily.ths_hot, sync_history.ths_hot |
| `ths_index` | `ths_index` | `raw_tushare.ths_index` | `core_serving.ths_index` | 6 | `None` | sync_history.ths_index |
| `ths_member` | `ths_member` | `raw_tushare.ths_member` | `core_serving.ths_member` | 7 | `None` | sync_history.ths_member |
| `top_list` | `top_list` | `raw_tushare.top_list` | `core_serving.equity_top_list` | 15 | `trade_date` | backfill_by_trade_date.top_list, sync_daily.top_list, sync_history.top_list |
| `trade_cal` | `trade_cal` | `raw_tushare.trade_cal` | `core_serving.trade_calendar` | 4 | `trade_date` | backfill_trade_cal.trade_cal, sync_history.trade_cal |
| `us_basic` | `us_basic` | `raw_tushare.us_basic` | `core_serving.us_security` | 6 | `None` | sync_history.us_basic |

## 分数据集详细说明

### `adj_factor`

- API: `adj_factor`
- Raw 表: `raw_tushare.adj_factor`（DAO: `raw_adj_factor`）
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

### `biying_equity_daily`

- API: `equity_daily_bar`
- Raw 表: `-`（DAO: `raw_biying_equity_daily`）
- Core 表: `raw_biying.equity_daily_bar`（DAO: `-`）
- 显式请求 fields（0）: -
- 支持任务: sync_daily.biying_equity_daily, sync_history.biying_equity_daily
- Raw 字段释义:
- 无
- Core 字段释义:
- 无

### `biying_moneyflow`

- API: `moneyflow`
- Raw 表: `raw_biying.moneyflow`（DAO: `raw_biying_moneyflow`）
- Core 表: `raw_biying.moneyflow`（DAO: `-`）
- 显式请求 fields（0）: -
- 支持任务: sync_daily.biying_moneyflow, sync_history.biying_moneyflow
- Raw 字段释义:
- `dm`: 上游原始字段，语义请参照对应接口文档
- `trade_date`: 交易日
- `mc`: 上游原始字段，语义请参照对应接口文档
- `quote_time`: 时间字段（具体语义以接口文档为准）
- `zmbzds`: 上游原始字段，语义请参照对应接口文档
- `zmszds`: 上游原始字段，语义请参照对应接口文档
- `dddx`: 上游原始字段，语义请参照对应接口文档
- `zddy`: 上游原始字段，语义请参照对应接口文档
- `ddcf`: 上游原始字段，语义请参照对应接口文档
- `zmbzdszl`: 上游原始字段，语义请参照对应接口文档
- `zmszdszl`: 上游原始字段，语义请参照对应接口文档
- `cjbszl`: 上游原始字段，语义请参照对应接口文档
- `zmbtdcje`: 上游原始字段，语义请参照对应接口文档
- `zmbddcje`: 上游原始字段，语义请参照对应接口文档
- `zmbzdcje`: 上游原始字段，语义请参照对应接口文档
- `zmbxdcje`: 上游原始字段，语义请参照对应接口文档
- `zmstdcje`: 上游原始字段，语义请参照对应接口文档
- `zmsddcje`: 上游原始字段，语义请参照对应接口文档
- `zmszdcje`: 上游原始字段，语义请参照对应接口文档
- `zmsxdcje`: 上游原始字段，语义请参照对应接口文档
- `bdmbtdcje`: 上游原始字段，语义请参照对应接口文档
- `bdmbddcje`: 上游原始字段，语义请参照对应接口文档
- `bdmbzdcje`: 上游原始字段，语义请参照对应接口文档
- `bdmbxdcje`: 上游原始字段，语义请参照对应接口文档
- `bdmstdcje`: 上游原始字段，语义请参照对应接口文档
- `bdmsddcje`: 上游原始字段，语义请参照对应接口文档
- `bdmszdcje`: 上游原始字段，语义请参照对应接口文档
- `bdmsxdcje`: 上游原始字段，语义请参照对应接口文档
- `zmbtdcjl`: 上游原始字段，语义请参照对应接口文档
- `zmbddcjl`: 上游原始字段，语义请参照对应接口文档
- `zmbzdcjl`: 上游原始字段，语义请参照对应接口文档
- `zmbxdcjl`: 上游原始字段，语义请参照对应接口文档
- `zmstdcjl`: 上游原始字段，语义请参照对应接口文档
- `zmsddcjl`: 上游原始字段，语义请参照对应接口文档
- `zmszdcjl`: 上游原始字段，语义请参照对应接口文档
- `zmsxdcjl`: 上游原始字段，语义请参照对应接口文档
- `bdmbtdcjl`: 上游原始字段，语义请参照对应接口文档
- `bdmbddcjl`: 上游原始字段，语义请参照对应接口文档
- `bdmbzdcjl`: 上游原始字段，语义请参照对应接口文档
- `bdmbxdcjl`: 上游原始字段，语义请参照对应接口文档
- `bdmstdcjl`: 上游原始字段，语义请参照对应接口文档
- `bdmsddcjl`: 上游原始字段，语义请参照对应接口文档
- `bdmszdcjl`: 上游原始字段，语义请参照对应接口文档
- `bdmsxdcjl`: 上游原始字段，语义请参照对应接口文档
- `zmbtdcjzl`: 上游原始字段，语义请参照对应接口文档
- `zmbddcjzl`: 上游原始字段，语义请参照对应接口文档
- `zmbzdcjzl`: 上游原始字段，语义请参照对应接口文档
- `zmbxdcjzl`: 上游原始字段，语义请参照对应接口文档
- `zmstdcjzl`: 上游原始字段，语义请参照对应接口文档
- `zmsddcjzl`: 上游原始字段，语义请参照对应接口文档
- `zmszdcjzl`: 上游原始字段，语义请参照对应接口文档
- `zmsxdcjzl`: 上游原始字段，语义请参照对应接口文档
- `bdmbtdcjzl`: 上游原始字段，语义请参照对应接口文档
- `bdmbddcjzl`: 上游原始字段，语义请参照对应接口文档
- `bdmbzdcjzl`: 上游原始字段，语义请参照对应接口文档
- `bdmbxdcjzl`: 上游原始字段，语义请参照对应接口文档
- `bdmstdcjzl`: 上游原始字段，语义请参照对应接口文档
- `bdmsddcjzl`: 上游原始字段，语义请参照对应接口文档
- `bdmszdcjzl`: 上游原始字段，语义请参照对应接口文档
- `bdmsxdcjzl`: 上游原始字段，语义请参照对应接口文档
- `zmbtdcjzlv`: 上游原始字段，语义请参照对应接口文档
- `zmbddcjzlv`: 上游原始字段，语义请参照对应接口文档
- `zmbzdcjzlv`: 上游原始字段，语义请参照对应接口文档
- `zmbxdcjzlv`: 上游原始字段，语义请参照对应接口文档
- `zmstdcjzlv`: 上游原始字段，语义请参照对应接口文档
- `zmsddcjzlv`: 上游原始字段，语义请参照对应接口文档
- `zmszdcjzlv`: 上游原始字段，语义请参照对应接口文档
- `zmsxdcjzlv`: 上游原始字段，语义请参照对应接口文档
- `bdmbtdcjzlv`: 上游原始字段，语义请参照对应接口文档
- `bdmbddcjzlv`: 上游原始字段，语义请参照对应接口文档
- `bdmbzdcjzlv`: 上游原始字段，语义请参照对应接口文档
- `bdmbxdcjzlv`: 上游原始字段，语义请参照对应接口文档
- `bdmstdcjzlv`: 上游原始字段，语义请参照对应接口文档
- `bdmsddcjzlv`: 上游原始字段，语义请参照对应接口文档
- `bdmszdcjzlv`: 上游原始字段，语义请参照对应接口文档
- `bdmsxdcjzlv`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- 无

### `block_trade`

- API: `block_trade`
- Raw 表: `raw_tushare.block_trade`（DAO: `raw_block_trade`）
- Core 表: `core_serving.equity_block_trade`（DAO: `equity_block_trade`）
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

### `broker_recommend`

- API: `broker_recommend`
- Raw 表: `raw_tushare.broker_recommend`（DAO: `raw_broker_recommend`）
- Core 表: `core_serving.broker_recommend`（DAO: `broker_recommend`）
- 显式请求 fields（14）: month, currency, name, ts_code, trade_date, close, pct_change, target_price, industry, broker, broker_mkt, author, recom_type, reason
- 支持任务: backfill_by_month.broker_recommend, sync_daily.broker_recommend, sync_history.broker_recommend
- Raw 字段释义:
- `month`: 上游原始字段，语义请参照对应接口文档
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `broker`: 上游原始字段，语义请参照对应接口文档
- `currency`: 上游原始字段，语义请参照对应接口文档
- `name`: 名称
- `trade_date`: 交易日
- `close`: 收盘价
- `pct_change`: 涨跌幅（上游原始字段）
- `target_price`: 上游原始字段，语义请参照对应接口文档
- `industry`: 行业分类
- `broker_mkt`: 上游原始字段，语义请参照对应接口文档
- `author`: 上游原始字段，语义请参照对应接口文档
- `recom_type`: 上游原始字段，语义请参照对应接口文档
- `reason`: 上游原始字段，语义请参照对应接口文档
- `offset`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `month`: 上游原始字段，语义请参照对应接口文档
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `broker`: 上游原始字段，语义请参照对应接口文档
- `currency`: 上游原始字段，语义请参照对应接口文档
- `name`: 名称
- `trade_date`: 交易日
- `close`: 收盘价
- `pct_change`: 涨跌幅（上游原始字段）
- `target_price`: 上游原始字段，语义请参照对应接口文档
- `industry`: 行业分类
- `broker_mkt`: 上游原始字段，语义请参照对应接口文档
- `author`: 上游原始字段，语义请参照对应接口文档
- `recom_type`: 上游原始字段，语义请参照对应接口文档
- `reason`: 上游原始字段，语义请参照对应接口文档
- `offset`: 上游原始字段，语义请参照对应接口文档
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `cyq_perf`

- API: `cyq_perf`
- Raw 表: `raw_tushare.cyq_perf`（DAO: `raw_cyq_perf`）
- Core 表: `core_serving.equity_cyq_perf`（DAO: `-`）
- 显式请求 fields（11）: ts_code, trade_date, his_low, his_high, cost_5pct, cost_15pct, cost_50pct, cost_85pct, cost_95pct, weight_avg, winner_rate
- 支持任务: sync_daily.cyq_perf, sync_history.cyq_perf
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `his_low`: 上游原始字段，语义请参照对应接口文档
- `his_high`: 上游原始字段，语义请参照对应接口文档
- `cost_5pct`: 上游原始字段，语义请参照对应接口文档
- `cost_15pct`: 上游原始字段，语义请参照对应接口文档
- `cost_50pct`: 上游原始字段，语义请参照对应接口文档
- `cost_85pct`: 上游原始字段，语义请参照对应接口文档
- `cost_95pct`: 上游原始字段，语义请参照对应接口文档
- `weight_avg`: 上游原始字段，语义请参照对应接口文档
- `winner_rate`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- 无

### `daily`

- API: `daily`
- Raw 表: `raw_tushare.daily`（DAO: `raw_daily`）
- Core 表: `core_serving.equity_daily_bar`（DAO: `equity_daily_bar`）
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
- Raw 表: `raw_tushare.daily_basic`（DAO: `raw_daily_basic`）
- Core 表: `core_serving.equity_daily_basic`（DAO: `equity_daily_basic`）
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
- Raw 表: `raw_tushare.dc_daily`（DAO: `raw_dc_daily`）
- Core 表: `core_serving.dc_daily`（DAO: `-`）
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
- Raw 表: `raw_tushare.dc_hot`（DAO: `raw_dc_hot`）
- Core 表: `core_serving.dc_hot`（DAO: `-`）
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
- Raw 表: `raw_tushare.dc_index`（DAO: `raw_dc_index`）
- Core 表: `core_serving.dc_index`（DAO: `dc_index`）
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
- Raw 表: `raw_tushare.dc_member`（DAO: `raw_dc_member`）
- Core 表: `core_serving.dc_member`（DAO: `-`）
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
- Raw 表: `raw_tushare.dividend`（DAO: `raw_dividend`）
- Core 表: `core_serving.equity_dividend`（DAO: `equity_dividend`）
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
- Raw 表: `raw_tushare.etf_basic`（DAO: `raw_etf_basic`）
- Core 表: `core_serving.etf_basic`（DAO: `etf_basic`）
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

### `etf_index`

- API: `etf_index`
- Raw 表: `raw_tushare.etf_index`（DAO: `raw_etf_index`）
- Core 表: `core_serving.etf_index`（DAO: `etf_index`）
- 显式请求 fields（8）: ts_code, indx_name, indx_csname, pub_party_name, pub_date, base_date, bp, adj_circle
- 支持任务: sync_history.etf_index
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `indx_name`: 上游原始字段，语义请参照对应接口文档
- `indx_csname`: 上游原始字段，语义请参照对应接口文档
- `pub_party_name`: 上游原始字段，语义请参照对应接口文档
- `pub_date`: 日期字段（具体语义以接口文档为准）
- `base_date`: 日期字段（具体语义以接口文档为准）
- `bp`: 上游原始字段，语义请参照对应接口文档
- `adj_circle`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `indx_name`: 上游原始字段，语义请参照对应接口文档
- `indx_csname`: 上游原始字段，语义请参照对应接口文档
- `pub_party_name`: 上游原始字段，语义请参照对应接口文档
- `pub_date`: 日期字段（具体语义以接口文档为准）
- `base_date`: 日期字段（具体语义以接口文档为准）
- `bp`: 上游原始字段，语义请参照对应接口文档
- `adj_circle`: 上游原始字段，语义请参照对应接口文档
- `created_at`: 创建时间（系统写入）
- `updated_at`: 更新时间（系统写入）

### `fund_adj`

- API: `fund_adj`
- Raw 表: `raw_tushare.fund_adj`（DAO: `raw_fund_adj`）
- Core 表: `core.fund_adj_factor`（DAO: `fund_adj_factor`）
- 显式请求 fields（3）: ts_code, trade_date, adj_factor
- 支持任务: backfill_fund_series.fund_adj, sync_daily.fund_adj, sync_history.fund_adj
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

### `fund_daily`

- API: `fund_daily`
- Raw 表: `raw_tushare.fund_daily`（DAO: `raw_fund_daily`）
- Core 表: `core_serving.fund_daily_bar`（DAO: `fund_daily_bar`）
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
- Raw 表: `raw_tushare.hk_basic`（DAO: `raw_hk_basic`）
- Core 表: `core_serving.hk_security`（DAO: `hk_security`）
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
- Raw 表: `raw_tushare.index_basic`（DAO: `raw_index_basic`）
- Core 表: `core_serving.index_basic`（DAO: `index_basic`）
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
- Raw 表: `raw_tushare.index_daily`（DAO: `raw_index_daily`）
- Core 表: `core_serving.index_daily_serving`（DAO: `index_daily_serving`）
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
- Raw 表: `raw_tushare.index_daily_basic`（DAO: `raw_index_daily_basic`）
- Core 表: `core_serving.index_daily_basic`（DAO: `index_daily_basic`）
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
- Raw 表: `raw_tushare.index_monthly_bar`（DAO: `raw_index_monthly_bar`）
- Core 表: `core_serving.index_monthly_serving`（DAO: `index_monthly_serving`）
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
- Raw 表: `raw_tushare.index_weekly_bar`（DAO: `raw_index_weekly_bar`）
- Core 表: `core_serving.index_weekly_serving`（DAO: `index_weekly_serving`）
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
- Raw 表: `raw_tushare.index_weight`（DAO: `raw_index_weight`）
- Core 表: `core_serving.index_weight`（DAO: `index_weight`）
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
- Raw 表: `raw_tushare.kpl_concept_cons`（DAO: `raw_kpl_concept_cons`）
- Core 表: `core_serving.kpl_concept_cons`（DAO: `kpl_concept_cons`）
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
- Raw 表: `raw_tushare.kpl_list`（DAO: `raw_kpl_list`）
- Core 表: `core_serving.kpl_list`（DAO: `kpl_list`）
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
- Raw 表: `raw_tushare.limit_cpt_list`（DAO: `raw_limit_cpt_list`）
- Core 表: `core_serving.limit_cpt_list`（DAO: `limit_cpt_list`）
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
- Raw 表: `raw_tushare.limit_list`（DAO: `raw_limit_list`）
- Core 表: `core_serving.equity_limit_list`（DAO: `equity_limit_list`）
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
- Raw 表: `raw_tushare.limit_list_ths`（DAO: `raw_limit_list_ths`）
- Core 表: `core_serving.limit_list_ths`（DAO: `-`）
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
- Raw 表: `raw_tushare.limit_step`（DAO: `raw_limit_step`）
- Core 表: `core_serving.limit_step`（DAO: `limit_step`）
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

### `margin`

- API: `margin`
- Raw 表: `raw_tushare.margin`（DAO: `raw_margin`）
- Core 表: `core_serving.equity_margin`（DAO: `-`）
- 显式请求 fields（9）: trade_date, exchange_id, rzye, rzmre, rzche, rqye, rqmcl, rzrqye, rqyl
- 支持任务: backfill_by_trade_date.margin, sync_daily.margin, sync_history.margin
- Raw 字段释义:
- `trade_date`: 交易日
- `exchange_id`: 上游原始字段，语义请参照对应接口文档
- `rzye`: 上游原始字段，语义请参照对应接口文档
- `rzmre`: 上游原始字段，语义请参照对应接口文档
- `rzche`: 上游原始字段，语义请参照对应接口文档
- `rqye`: 上游原始字段，语义请参照对应接口文档
- `rqmcl`: 上游原始字段，语义请参照对应接口文档
- `rzrqye`: 上游原始字段，语义请参照对应接口文档
- `rqyl`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- 无

### `moneyflow`

- API: `moneyflow`
- Raw 表: `raw_tushare.moneyflow`（DAO: `raw_moneyflow`）
- Core 表: `core_serving.equity_moneyflow`（DAO: `-`）
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
- 无

### `moneyflow_cnt_ths`

- API: `moneyflow_cnt_ths`
- Raw 表: `raw_tushare.moneyflow_cnt_ths`（DAO: `raw_moneyflow_cnt_ths`）
- Core 表: `core_serving.concept_moneyflow_ths`（DAO: `-`）
- 显式请求 fields（12）: trade_date, ts_code, name, lead_stock, close_price, pct_change, industry_index, company_num, pct_change_stock, net_buy_amount, net_sell_amount, net_amount
- 支持任务: backfill_by_trade_date.moneyflow_cnt_ths, sync_daily.moneyflow_cnt_ths, sync_history.moneyflow_cnt_ths
- Raw 字段释义:
- `trade_date`: 交易日
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `name`: 名称
- `lead_stock`: 上游原始字段，语义请参照对应接口文档
- `close_price`: 上游原始字段，语义请参照对应接口文档
- `pct_change`: 涨跌幅（上游原始字段）
- `industry_index`: 上游原始字段，语义请参照对应接口文档
- `company_num`: 上游原始字段，语义请参照对应接口文档
- `pct_change_stock`: 上游原始字段，语义请参照对应接口文档
- `net_buy_amount`: 上游原始字段，语义请参照对应接口文档
- `net_sell_amount`: 上游原始字段，语义请参照对应接口文档
- `net_amount`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- 无

### `moneyflow_dc`

- API: `moneyflow_dc`
- Raw 表: `raw_tushare.moneyflow_dc`（DAO: `raw_moneyflow_dc`）
- Core 表: `core_serving.equity_moneyflow_dc`（DAO: `-`）
- 显式请求 fields（15）: trade_date, ts_code, name, pct_change, close, net_amount, net_amount_rate, buy_elg_amount, buy_elg_amount_rate, buy_lg_amount, buy_lg_amount_rate, buy_md_amount, buy_md_amount_rate, buy_sm_amount, buy_sm_amount_rate
- 支持任务: backfill_by_trade_date.moneyflow_dc, sync_daily.moneyflow_dc, sync_history.moneyflow_dc
- Raw 字段释义:
- `trade_date`: 交易日
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `name`: 名称
- `pct_change`: 涨跌幅（上游原始字段）
- `close`: 收盘价
- `net_amount`: 上游原始字段，语义请参照对应接口文档
- `net_amount_rate`: 上游原始字段，语义请参照对应接口文档
- `buy_elg_amount`: 上游原始字段，语义请参照对应接口文档
- `buy_elg_amount_rate`: 上游原始字段，语义请参照对应接口文档
- `buy_lg_amount`: 上游原始字段，语义请参照对应接口文档
- `buy_lg_amount_rate`: 上游原始字段，语义请参照对应接口文档
- `buy_md_amount`: 上游原始字段，语义请参照对应接口文档
- `buy_md_amount_rate`: 上游原始字段，语义请参照对应接口文档
- `buy_sm_amount`: 上游原始字段，语义请参照对应接口文档
- `buy_sm_amount_rate`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- 无

### `moneyflow_ind_dc`

- API: `moneyflow_ind_dc`
- Raw 表: `raw_tushare.moneyflow_ind_dc`（DAO: `raw_moneyflow_ind_dc`）
- Core 表: `core_serving.board_moneyflow_dc`（DAO: `-`）
- 显式请求 fields（18）: trade_date, content_type, ts_code, name, pct_change, close, net_amount, net_amount_rate, buy_elg_amount, buy_elg_amount_rate, buy_lg_amount, buy_lg_amount_rate, buy_md_amount, buy_md_amount_rate, buy_sm_amount, buy_sm_amount_rate, buy_sm_amount_stock, rank
- 支持任务: backfill_by_trade_date.moneyflow_ind_dc, sync_daily.moneyflow_ind_dc, sync_history.moneyflow_ind_dc
- Raw 字段释义:
- `trade_date`: 交易日
- `content_type`: 上游原始字段，语义请参照对应接口文档
- `name`: 名称
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `pct_change`: 涨跌幅（上游原始字段）
- `close`: 收盘价
- `net_amount`: 上游原始字段，语义请参照对应接口文档
- `net_amount_rate`: 上游原始字段，语义请参照对应接口文档
- `buy_elg_amount`: 上游原始字段，语义请参照对应接口文档
- `buy_elg_amount_rate`: 上游原始字段，语义请参照对应接口文档
- `buy_lg_amount`: 上游原始字段，语义请参照对应接口文档
- `buy_lg_amount_rate`: 上游原始字段，语义请参照对应接口文档
- `buy_md_amount`: 上游原始字段，语义请参照对应接口文档
- `buy_md_amount_rate`: 上游原始字段，语义请参照对应接口文档
- `buy_sm_amount`: 上游原始字段，语义请参照对应接口文档
- `buy_sm_amount_rate`: 上游原始字段，语义请参照对应接口文档
- `buy_sm_amount_stock`: 上游原始字段，语义请参照对应接口文档
- `rank`: 排名
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- 无

### `moneyflow_ind_ths`

- API: `moneyflow_ind_ths`
- Raw 表: `raw_tushare.moneyflow_ind_ths`（DAO: `raw_moneyflow_ind_ths`）
- Core 表: `core_serving.industry_moneyflow_ths`（DAO: `-`）
- 显式请求 fields（12）: trade_date, ts_code, industry, lead_stock, close, pct_change, company_num, pct_change_stock, close_price, net_buy_amount, net_sell_amount, net_amount
- 支持任务: backfill_by_trade_date.moneyflow_ind_ths, sync_daily.moneyflow_ind_ths, sync_history.moneyflow_ind_ths
- Raw 字段释义:
- `trade_date`: 交易日
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `industry`: 行业分类
- `lead_stock`: 上游原始字段，语义请参照对应接口文档
- `close`: 收盘价
- `pct_change`: 涨跌幅（上游原始字段）
- `company_num`: 上游原始字段，语义请参照对应接口文档
- `pct_change_stock`: 上游原始字段，语义请参照对应接口文档
- `close_price`: 上游原始字段，语义请参照对应接口文档
- `net_buy_amount`: 上游原始字段，语义请参照对应接口文档
- `net_sell_amount`: 上游原始字段，语义请参照对应接口文档
- `net_amount`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- 无

### `moneyflow_mkt_dc`

- API: `moneyflow_mkt_dc`
- Raw 表: `raw_tushare.moneyflow_mkt_dc`（DAO: `raw_moneyflow_mkt_dc`）
- Core 表: `core_serving.market_moneyflow_dc`（DAO: `-`）
- 显式请求 fields（15）: trade_date, close_sh, pct_change_sh, close_sz, pct_change_sz, net_amount, net_amount_rate, buy_elg_amount, buy_elg_amount_rate, buy_lg_amount, buy_lg_amount_rate, buy_md_amount, buy_md_amount_rate, buy_sm_amount, buy_sm_amount_rate
- 支持任务: backfill_by_trade_date.moneyflow_mkt_dc, sync_daily.moneyflow_mkt_dc, sync_history.moneyflow_mkt_dc
- Raw 字段释义:
- `trade_date`: 交易日
- `close_sh`: 上游原始字段，语义请参照对应接口文档
- `pct_change_sh`: 上游原始字段，语义请参照对应接口文档
- `close_sz`: 上游原始字段，语义请参照对应接口文档
- `pct_change_sz`: 上游原始字段，语义请参照对应接口文档
- `net_amount`: 上游原始字段，语义请参照对应接口文档
- `net_amount_rate`: 上游原始字段，语义请参照对应接口文档
- `buy_elg_amount`: 上游原始字段，语义请参照对应接口文档
- `buy_elg_amount_rate`: 上游原始字段，语义请参照对应接口文档
- `buy_lg_amount`: 上游原始字段，语义请参照对应接口文档
- `buy_lg_amount_rate`: 上游原始字段，语义请参照对应接口文档
- `buy_md_amount`: 上游原始字段，语义请参照对应接口文档
- `buy_md_amount_rate`: 上游原始字段，语义请参照对应接口文档
- `buy_sm_amount`: 上游原始字段，语义请参照对应接口文档
- `buy_sm_amount_rate`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- 无

### `moneyflow_ths`

- API: `moneyflow_ths`
- Raw 表: `raw_tushare.moneyflow_ths`（DAO: `raw_moneyflow_ths`）
- Core 表: `core_serving.equity_moneyflow_ths`（DAO: `-`）
- 显式请求 fields（13）: trade_date, ts_code, name, pct_change, latest, net_amount, net_d5_amount, buy_lg_amount, buy_lg_amount_rate, buy_md_amount, buy_md_amount_rate, buy_sm_amount, buy_sm_amount_rate
- 支持任务: backfill_by_trade_date.moneyflow_ths, sync_daily.moneyflow_ths, sync_history.moneyflow_ths
- Raw 字段释义:
- `trade_date`: 交易日
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `name`: 名称
- `pct_change`: 涨跌幅（上游原始字段）
- `latest`: 上游原始字段，语义请参照对应接口文档
- `net_amount`: 上游原始字段，语义请参照对应接口文档
- `net_d5_amount`: 上游原始字段，语义请参照对应接口文档
- `buy_lg_amount`: 上游原始字段，语义请参照对应接口文档
- `buy_lg_amount_rate`: 上游原始字段，语义请参照对应接口文档
- `buy_md_amount`: 上游原始字段，语义请参照对应接口文档
- `buy_md_amount_rate`: 上游原始字段，语义请参照对应接口文档
- `buy_sm_amount`: 上游原始字段，语义请参照对应接口文档
- `buy_sm_amount_rate`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- 无

### `stk_factor_pro`

- API: `stk_factor_pro`
- Raw 表: `raw_tushare.stk_factor_pro`（DAO: `raw_stk_factor_pro`）
- Core 表: `core_serving.equity_factor_pro`（DAO: `-`）
- 显式请求 fields（227）: ts_code, trade_date, close_bfq, open_bfq, high_bfq, low_bfq, pre_close_bfq, change_bfq, pct_change_bfq, vol_bfq, amount_bfq, close_hfq, open_hfq, high_hfq, low_hfq, pre_close_hfq, change_hfq, pct_change_hfq, vol_hfq, amount_hfq, close_qfq, open_qfq, high_qfq, low_qfq, pre_close_qfq, change_qfq, pct_change_qfq, vol_qfq, amount_qfq, adj_factor, tor, vr, ma_bfq_5, ma_hfq_5, ma_qfq_5, ma_bfq_10, ma_hfq_10, ma_qfq_10, ma_bfq_20, ma_hfq_20, ma_qfq_20, ma_bfq_30, ma_hfq_30, ma_qfq_30, ma_bfq_60, ma_hfq_60, ma_qfq_60, ma_bfq_90, ma_hfq_90, ma_qfq_90, ma_bfq_250, ma_hfq_250, ma_qfq_250, ma_bfq_500, ma_hfq_500, ma_qfq_500, ema_bfq_5, ema_hfq_5, ema_qfq_5, ema_bfq_10, ema_hfq_10, ema_qfq_10, ema_bfq_20, ema_hfq_20, ema_qfq_20, ema_bfq_30, ema_hfq_30, ema_qfq_30, ema_bfq_60, ema_hfq_60, ema_qfq_60, ema_bfq_90, ema_hfq_90, ema_qfq_90, ema_bfq_250, ema_hfq_250, ema_qfq_250, ema_bfq_500, ema_hfq_500, ema_qfq_500, macd_dif_bfq, macd_dea_bfq, macd_bfq, macd_dif_hfq, macd_dea_hfq, macd_hfq, macd_dif_qfq, macd_dea_qfq, macd_qfq, kdj_k_bfq, kdj_d_bfq, kdj_j_bfq, kdj_k_hfq, kdj_d_hfq, kdj_j_hfq, kdj_k_qfq, kdj_d_qfq, kdj_j_qfq, rsi_bfq_6, rsi_hfq_6, rsi_qfq_6, rsi_bfq_12, rsi_hfq_12, rsi_qfq_12, rsi_bfq_24, rsi_hfq_24, rsi_qfq_24, boll_upper_bfq, boll_mid_bfq, boll_lower_bfq, boll_upper_hfq, boll_mid_hfq, boll_lower_hfq, boll_upper_qfq, boll_mid_qfq, boll_lower_qfq, cci_bfq, cci_hfq, cci_qfq, obv_bfq, obv_hfq, obv_qfq, roc_bfq, roc_hfq, roc_qfq, ma_roc_bfq, ma_roc_hfq, ma_roc_qfq, bbi_bfq, bbi_hfq, bbi_qfq, expma_12_bfq, expma_12_hfq, expma_12_qfq, expma_50_bfq, expma_50_hfq, expma_50_qfq, ar_bfq, ar_hfq, ar_qfq, br_bfq, br_hfq, br_qfq, atr_bfq, atr_hfq, atr_qfq, dmi_pdi_bfq, dmi_mdi_bfq, dmi_adx_bfq, dmi_adxr_bfq, dmi_pdi_hfq, dmi_mdi_hfq, dmi_adx_hfq, dmi_adxr_hfq, dmi_pdi_qfq, dmi_mdi_qfq, dmi_adx_qfq, dmi_adxr_qfq, mtm_bfq, mtm_hfq, mtm_qfq, mtmma_bfq, mtmma_hfq, mtmma_qfq, ktn_down_bfq, ktn_mid_bfq, ktn_up_bfq, ktn_down_hfq, ktn_mid_hfq, ktn_up_hfq, ktn_down_qfq, ktn_mid_qfq, ktn_up_qfq, trix_bfq, trix_hfq, trix_qfq, trma_bfq, trma_hfq, trma_qfq, dfma_dif_bfq, dfma_dif_hfq, dfma_dif_qfq, dfma_difma_bfq, dfma_difma_hfq, dfma_difma_qfq, emv_bfq, emv_hfq, emv_qfq, maemv_bfq, maemv_hfq, maemv_qfq, psy_bfq, psy_hfq, psy_qfq, psyma_bfq, psyma_hfq, psyma_qfq, mass_bfq, mass_hfq, mass_qfq, mamass_bfq, mamass_hfq, mamass_qfq, obos_bfq, obos_hfq, obos_qfq, mfi_bfq, mfi_hfq, mfi_qfq, asi_bfq, asi_hfq, asi_qfq, asit_bfq, asit_hfq, asit_qfq, xsii_td1_bfq, xsii_td1_hfq, xsii_td1_qfq, xsii_td2_bfq, xsii_td2_hfq, xsii_td2_qfq, xsii_td3_bfq, xsii_td3_hfq, xsii_td3_qfq, xsii_td4_bfq, xsii_td4_hfq, xsii_td4_qfq
- 支持任务: backfill_by_trade_date.stk_factor_pro, sync_daily.stk_factor_pro, sync_history.stk_factor_pro
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `close_bfq`: 上游原始字段，语义请参照对应接口文档
- `open_bfq`: 上游原始字段，语义请参照对应接口文档
- `high_bfq`: 上游原始字段，语义请参照对应接口文档
- `low_bfq`: 上游原始字段，语义请参照对应接口文档
- `pre_close_bfq`: 上游原始字段，语义请参照对应接口文档
- `change_bfq`: 上游原始字段，语义请参照对应接口文档
- `pct_change_bfq`: 上游原始字段，语义请参照对应接口文档
- `vol_bfq`: 上游原始字段，语义请参照对应接口文档
- `amount_bfq`: 上游原始字段，语义请参照对应接口文档
- `close_hfq`: 上游原始字段，语义请参照对应接口文档
- `open_hfq`: 上游原始字段，语义请参照对应接口文档
- `high_hfq`: 上游原始字段，语义请参照对应接口文档
- `low_hfq`: 上游原始字段，语义请参照对应接口文档
- `pre_close_hfq`: 上游原始字段，语义请参照对应接口文档
- `change_hfq`: 上游原始字段，语义请参照对应接口文档
- `pct_change_hfq`: 上游原始字段，语义请参照对应接口文档
- `vol_hfq`: 上游原始字段，语义请参照对应接口文档
- `amount_hfq`: 上游原始字段，语义请参照对应接口文档
- `close_qfq`: 上游原始字段，语义请参照对应接口文档
- `open_qfq`: 上游原始字段，语义请参照对应接口文档
- `high_qfq`: 上游原始字段，语义请参照对应接口文档
- `low_qfq`: 上游原始字段，语义请参照对应接口文档
- `pre_close_qfq`: 上游原始字段，语义请参照对应接口文档
- `change_qfq`: 上游原始字段，语义请参照对应接口文档
- `pct_change_qfq`: 上游原始字段，语义请参照对应接口文档
- `vol_qfq`: 上游原始字段，语义请参照对应接口文档
- `amount_qfq`: 上游原始字段，语义请参照对应接口文档
- `adj_factor`: 复权因子
- `tor`: 上游原始字段，语义请参照对应接口文档
- `vr`: 上游原始字段，语义请参照对应接口文档
- `ma_bfq_5`: 上游原始字段，语义请参照对应接口文档
- `ma_hfq_5`: 上游原始字段，语义请参照对应接口文档
- `ma_qfq_5`: 上游原始字段，语义请参照对应接口文档
- `ma_bfq_10`: 上游原始字段，语义请参照对应接口文档
- `ma_hfq_10`: 上游原始字段，语义请参照对应接口文档
- `ma_qfq_10`: 上游原始字段，语义请参照对应接口文档
- `ma_bfq_20`: 上游原始字段，语义请参照对应接口文档
- `ma_hfq_20`: 上游原始字段，语义请参照对应接口文档
- `ma_qfq_20`: 上游原始字段，语义请参照对应接口文档
- `ma_bfq_30`: 上游原始字段，语义请参照对应接口文档
- `ma_hfq_30`: 上游原始字段，语义请参照对应接口文档
- `ma_qfq_30`: 上游原始字段，语义请参照对应接口文档
- `ma_bfq_60`: 上游原始字段，语义请参照对应接口文档
- `ma_hfq_60`: 上游原始字段，语义请参照对应接口文档
- `ma_qfq_60`: 上游原始字段，语义请参照对应接口文档
- `ma_bfq_90`: 上游原始字段，语义请参照对应接口文档
- `ma_hfq_90`: 上游原始字段，语义请参照对应接口文档
- `ma_qfq_90`: 上游原始字段，语义请参照对应接口文档
- `ma_bfq_250`: 上游原始字段，语义请参照对应接口文档
- `ma_hfq_250`: 上游原始字段，语义请参照对应接口文档
- `ma_qfq_250`: 上游原始字段，语义请参照对应接口文档
- `ma_bfq_500`: 上游原始字段，语义请参照对应接口文档
- `ma_hfq_500`: 上游原始字段，语义请参照对应接口文档
- `ma_qfq_500`: 上游原始字段，语义请参照对应接口文档
- `ema_bfq_5`: 上游原始字段，语义请参照对应接口文档
- `ema_hfq_5`: 上游原始字段，语义请参照对应接口文档
- `ema_qfq_5`: 上游原始字段，语义请参照对应接口文档
- `ema_bfq_10`: 上游原始字段，语义请参照对应接口文档
- `ema_hfq_10`: 上游原始字段，语义请参照对应接口文档
- `ema_qfq_10`: 上游原始字段，语义请参照对应接口文档
- `ema_bfq_20`: 上游原始字段，语义请参照对应接口文档
- `ema_hfq_20`: 上游原始字段，语义请参照对应接口文档
- `ema_qfq_20`: 上游原始字段，语义请参照对应接口文档
- `ema_bfq_30`: 上游原始字段，语义请参照对应接口文档
- `ema_hfq_30`: 上游原始字段，语义请参照对应接口文档
- `ema_qfq_30`: 上游原始字段，语义请参照对应接口文档
- `ema_bfq_60`: 上游原始字段，语义请参照对应接口文档
- `ema_hfq_60`: 上游原始字段，语义请参照对应接口文档
- `ema_qfq_60`: 上游原始字段，语义请参照对应接口文档
- `ema_bfq_90`: 上游原始字段，语义请参照对应接口文档
- `ema_hfq_90`: 上游原始字段，语义请参照对应接口文档
- `ema_qfq_90`: 上游原始字段，语义请参照对应接口文档
- `ema_bfq_250`: 上游原始字段，语义请参照对应接口文档
- `ema_hfq_250`: 上游原始字段，语义请参照对应接口文档
- `ema_qfq_250`: 上游原始字段，语义请参照对应接口文档
- `ema_bfq_500`: 上游原始字段，语义请参照对应接口文档
- `ema_hfq_500`: 上游原始字段，语义请参照对应接口文档
- `ema_qfq_500`: 上游原始字段，语义请参照对应接口文档
- `macd_dif_bfq`: 上游原始字段，语义请参照对应接口文档
- `macd_dea_bfq`: 上游原始字段，语义请参照对应接口文档
- `macd_bfq`: 上游原始字段，语义请参照对应接口文档
- `macd_dif_hfq`: 上游原始字段，语义请参照对应接口文档
- `macd_dea_hfq`: 上游原始字段，语义请参照对应接口文档
- `macd_hfq`: 上游原始字段，语义请参照对应接口文档
- `macd_dif_qfq`: 上游原始字段，语义请参照对应接口文档
- `macd_dea_qfq`: 上游原始字段，语义请参照对应接口文档
- `macd_qfq`: 上游原始字段，语义请参照对应接口文档
- `kdj_k_bfq`: 上游原始字段，语义请参照对应接口文档
- `kdj_d_bfq`: 上游原始字段，语义请参照对应接口文档
- `kdj_j_bfq`: 上游原始字段，语义请参照对应接口文档
- `kdj_k_hfq`: 上游原始字段，语义请参照对应接口文档
- `kdj_d_hfq`: 上游原始字段，语义请参照对应接口文档
- `kdj_j_hfq`: 上游原始字段，语义请参照对应接口文档
- `kdj_k_qfq`: 上游原始字段，语义请参照对应接口文档
- `kdj_d_qfq`: 上游原始字段，语义请参照对应接口文档
- `kdj_j_qfq`: 上游原始字段，语义请参照对应接口文档
- `rsi_bfq_6`: 上游原始字段，语义请参照对应接口文档
- `rsi_hfq_6`: 上游原始字段，语义请参照对应接口文档
- `rsi_qfq_6`: 上游原始字段，语义请参照对应接口文档
- `rsi_bfq_12`: 上游原始字段，语义请参照对应接口文档
- `rsi_hfq_12`: 上游原始字段，语义请参照对应接口文档
- `rsi_qfq_12`: 上游原始字段，语义请参照对应接口文档
- `rsi_bfq_24`: 上游原始字段，语义请参照对应接口文档
- `rsi_hfq_24`: 上游原始字段，语义请参照对应接口文档
- `rsi_qfq_24`: 上游原始字段，语义请参照对应接口文档
- `boll_upper_bfq`: 上游原始字段，语义请参照对应接口文档
- `boll_mid_bfq`: 上游原始字段，语义请参照对应接口文档
- `boll_lower_bfq`: 上游原始字段，语义请参照对应接口文档
- `boll_upper_hfq`: 上游原始字段，语义请参照对应接口文档
- `boll_mid_hfq`: 上游原始字段，语义请参照对应接口文档
- `boll_lower_hfq`: 上游原始字段，语义请参照对应接口文档
- `boll_upper_qfq`: 上游原始字段，语义请参照对应接口文档
- `boll_mid_qfq`: 上游原始字段，语义请参照对应接口文档
- `boll_lower_qfq`: 上游原始字段，语义请参照对应接口文档
- `cci_bfq`: 上游原始字段，语义请参照对应接口文档
- `cci_hfq`: 上游原始字段，语义请参照对应接口文档
- `cci_qfq`: 上游原始字段，语义请参照对应接口文档
- `obv_bfq`: 上游原始字段，语义请参照对应接口文档
- `obv_hfq`: 上游原始字段，语义请参照对应接口文档
- `obv_qfq`: 上游原始字段，语义请参照对应接口文档
- `roc_bfq`: 上游原始字段，语义请参照对应接口文档
- `roc_hfq`: 上游原始字段，语义请参照对应接口文档
- `roc_qfq`: 上游原始字段，语义请参照对应接口文档
- `ma_roc_bfq`: 上游原始字段，语义请参照对应接口文档
- `ma_roc_hfq`: 上游原始字段，语义请参照对应接口文档
- `ma_roc_qfq`: 上游原始字段，语义请参照对应接口文档
- `bbi_bfq`: 上游原始字段，语义请参照对应接口文档
- `bbi_hfq`: 上游原始字段，语义请参照对应接口文档
- `bbi_qfq`: 上游原始字段，语义请参照对应接口文档
- `expma_12_bfq`: 上游原始字段，语义请参照对应接口文档
- `expma_12_hfq`: 上游原始字段，语义请参照对应接口文档
- `expma_12_qfq`: 上游原始字段，语义请参照对应接口文档
- `expma_50_bfq`: 上游原始字段，语义请参照对应接口文档
- `expma_50_hfq`: 上游原始字段，语义请参照对应接口文档
- `expma_50_qfq`: 上游原始字段，语义请参照对应接口文档
- `ar_bfq`: 上游原始字段，语义请参照对应接口文档
- `ar_hfq`: 上游原始字段，语义请参照对应接口文档
- `ar_qfq`: 上游原始字段，语义请参照对应接口文档
- `br_bfq`: 上游原始字段，语义请参照对应接口文档
- `br_hfq`: 上游原始字段，语义请参照对应接口文档
- `br_qfq`: 上游原始字段，语义请参照对应接口文档
- `atr_bfq`: 上游原始字段，语义请参照对应接口文档
- `atr_hfq`: 上游原始字段，语义请参照对应接口文档
- `atr_qfq`: 上游原始字段，语义请参照对应接口文档
- `dmi_pdi_bfq`: 上游原始字段，语义请参照对应接口文档
- `dmi_mdi_bfq`: 上游原始字段，语义请参照对应接口文档
- `dmi_adx_bfq`: 上游原始字段，语义请参照对应接口文档
- `dmi_adxr_bfq`: 上游原始字段，语义请参照对应接口文档
- `dmi_pdi_hfq`: 上游原始字段，语义请参照对应接口文档
- `dmi_mdi_hfq`: 上游原始字段，语义请参照对应接口文档
- `dmi_adx_hfq`: 上游原始字段，语义请参照对应接口文档
- `dmi_adxr_hfq`: 上游原始字段，语义请参照对应接口文档
- `dmi_pdi_qfq`: 上游原始字段，语义请参照对应接口文档
- `dmi_mdi_qfq`: 上游原始字段，语义请参照对应接口文档
- `dmi_adx_qfq`: 上游原始字段，语义请参照对应接口文档
- `dmi_adxr_qfq`: 上游原始字段，语义请参照对应接口文档
- `mtm_bfq`: 上游原始字段，语义请参照对应接口文档
- `mtm_hfq`: 上游原始字段，语义请参照对应接口文档
- `mtm_qfq`: 上游原始字段，语义请参照对应接口文档
- `mtmma_bfq`: 上游原始字段，语义请参照对应接口文档
- `mtmma_hfq`: 上游原始字段，语义请参照对应接口文档
- `mtmma_qfq`: 上游原始字段，语义请参照对应接口文档
- `ktn_down_bfq`: 上游原始字段，语义请参照对应接口文档
- `ktn_mid_bfq`: 上游原始字段，语义请参照对应接口文档
- `ktn_up_bfq`: 上游原始字段，语义请参照对应接口文档
- `ktn_down_hfq`: 上游原始字段，语义请参照对应接口文档
- `ktn_mid_hfq`: 上游原始字段，语义请参照对应接口文档
- `ktn_up_hfq`: 上游原始字段，语义请参照对应接口文档
- `ktn_down_qfq`: 上游原始字段，语义请参照对应接口文档
- `ktn_mid_qfq`: 上游原始字段，语义请参照对应接口文档
- `ktn_up_qfq`: 上游原始字段，语义请参照对应接口文档
- `trix_bfq`: 上游原始字段，语义请参照对应接口文档
- `trix_hfq`: 上游原始字段，语义请参照对应接口文档
- `trix_qfq`: 上游原始字段，语义请参照对应接口文档
- `trma_bfq`: 上游原始字段，语义请参照对应接口文档
- `trma_hfq`: 上游原始字段，语义请参照对应接口文档
- `trma_qfq`: 上游原始字段，语义请参照对应接口文档
- `dfma_dif_bfq`: 上游原始字段，语义请参照对应接口文档
- `dfma_dif_hfq`: 上游原始字段，语义请参照对应接口文档
- `dfma_dif_qfq`: 上游原始字段，语义请参照对应接口文档
- `dfma_difma_bfq`: 上游原始字段，语义请参照对应接口文档
- `dfma_difma_hfq`: 上游原始字段，语义请参照对应接口文档
- `dfma_difma_qfq`: 上游原始字段，语义请参照对应接口文档
- `emv_bfq`: 上游原始字段，语义请参照对应接口文档
- `emv_hfq`: 上游原始字段，语义请参照对应接口文档
- `emv_qfq`: 上游原始字段，语义请参照对应接口文档
- `maemv_bfq`: 上游原始字段，语义请参照对应接口文档
- `maemv_hfq`: 上游原始字段，语义请参照对应接口文档
- `maemv_qfq`: 上游原始字段，语义请参照对应接口文档
- `psy_bfq`: 上游原始字段，语义请参照对应接口文档
- `psy_hfq`: 上游原始字段，语义请参照对应接口文档
- `psy_qfq`: 上游原始字段，语义请参照对应接口文档
- `psyma_bfq`: 上游原始字段，语义请参照对应接口文档
- `psyma_hfq`: 上游原始字段，语义请参照对应接口文档
- `psyma_qfq`: 上游原始字段，语义请参照对应接口文档
- `mass_bfq`: 上游原始字段，语义请参照对应接口文档
- `mass_hfq`: 上游原始字段，语义请参照对应接口文档
- `mass_qfq`: 上游原始字段，语义请参照对应接口文档
- `mamass_bfq`: 上游原始字段，语义请参照对应接口文档
- `mamass_hfq`: 上游原始字段，语义请参照对应接口文档
- `mamass_qfq`: 上游原始字段，语义请参照对应接口文档
- `obos_bfq`: 上游原始字段，语义请参照对应接口文档
- `obos_hfq`: 上游原始字段，语义请参照对应接口文档
- `obos_qfq`: 上游原始字段，语义请参照对应接口文档
- `mfi_bfq`: 上游原始字段，语义请参照对应接口文档
- `mfi_hfq`: 上游原始字段，语义请参照对应接口文档
- `mfi_qfq`: 上游原始字段，语义请参照对应接口文档
- `asi_bfq`: 上游原始字段，语义请参照对应接口文档
- `asi_hfq`: 上游原始字段，语义请参照对应接口文档
- `asi_qfq`: 上游原始字段，语义请参照对应接口文档
- `asit_bfq`: 上游原始字段，语义请参照对应接口文档
- `asit_hfq`: 上游原始字段，语义请参照对应接口文档
- `asit_qfq`: 上游原始字段，语义请参照对应接口文档
- `xsii_td1_bfq`: 上游原始字段，语义请参照对应接口文档
- `xsii_td1_hfq`: 上游原始字段，语义请参照对应接口文档
- `xsii_td1_qfq`: 上游原始字段，语义请参照对应接口文档
- `xsii_td2_bfq`: 上游原始字段，语义请参照对应接口文档
- `xsii_td2_hfq`: 上游原始字段，语义请参照对应接口文档
- `xsii_td2_qfq`: 上游原始字段，语义请参照对应接口文档
- `xsii_td3_bfq`: 上游原始字段，语义请参照对应接口文档
- `xsii_td3_hfq`: 上游原始字段，语义请参照对应接口文档
- `xsii_td3_qfq`: 上游原始字段，语义请参照对应接口文档
- `xsii_td4_bfq`: 上游原始字段，语义请参照对应接口文档
- `xsii_td4_hfq`: 上游原始字段，语义请参照对应接口文档
- `xsii_td4_qfq`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- 无

### `stk_holdernumber`

- API: `stk_holdernumber`
- Raw 表: `raw_tushare.holdernumber`（DAO: `raw_holder_number`）
- Core 表: `core_serving.equity_holder_number`（DAO: `equity_holder_number`）
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

### `stk_limit`

- API: `stk_limit`
- Raw 表: `raw_tushare.stk_limit`（DAO: `raw_stk_limit`）
- Core 表: `core_serving.equity_stk_limit`（DAO: `-`）
- 显式请求 fields（5）: trade_date, ts_code, pre_close, up_limit, down_limit
- 支持任务: sync_daily.stk_limit, sync_history.stk_limit
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `pre_close`: 昨收价
- `up_limit`: 上游原始字段，语义请参照对应接口文档
- `down_limit`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- 无

### `stk_nineturn`

- API: `stk_nineturn`
- Raw 表: `raw_tushare.stk_nineturn`（DAO: `raw_stk_nineturn`）
- Core 表: `core_serving.equity_nineturn`（DAO: `-`）
- 显式请求 fields（13）: ts_code, trade_date, freq, open, high, low, close, vol, amount, up_count, down_count, nine_up_turn, nine_down_turn
- 支持任务: backfill_by_trade_date.stk_nineturn, sync_daily.stk_nineturn, sync_history.stk_nineturn
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `freq`: 上游原始字段，语义请参照对应接口文档
- `open`: 开盘价
- `high`: 最高价
- `low`: 最低价
- `close`: 收盘价
- `vol`: 成交量
- `amount`: 成交额
- `up_count`: 上游原始字段，语义请参照对应接口文档
- `down_count`: 上游原始字段，语义请参照对应接口文档
- `nine_up_turn`: 上游原始字段，语义请参照对应接口文档
- `nine_down_turn`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- 无

### `stk_period_bar_adj_month`

- API: `stk_week_month_adj`
- Raw 表: `raw_tushare.stk_period_bar_adj`（DAO: `raw_stk_period_bar_adj`）
- Core 表: `core_serving.stk_period_bar_adj`（DAO: `stk_period_bar_adj`）
- 显式请求 fields（21）: ts_code, trade_date, end_date, freq, open, high, low, close, pre_close, open_qfq, high_qfq, low_qfq, close_qfq, open_hfq, high_hfq, low_hfq, close_hfq, vol, amount, change, pct_chg
- 支持任务: backfill_equity_series.stk_period_bar_adj_month, sync_daily.stk_period_bar_adj_month, sync_history.stk_period_bar_adj_month
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
- Raw 表: `raw_tushare.stk_period_bar_adj`（DAO: `raw_stk_period_bar_adj`）
- Core 表: `core_serving.stk_period_bar_adj`（DAO: `stk_period_bar_adj`）
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
- Raw 表: `raw_tushare.stk_period_bar`（DAO: `raw_stk_period_bar`）
- Core 表: `core_serving.stk_period_bar`（DAO: `stk_period_bar`）
- 显式请求 fields（13）: ts_code, trade_date, end_date, freq, open, high, low, close, pre_close, vol, amount, change, pct_chg
- 支持任务: backfill_equity_series.stk_period_bar_month, sync_daily.stk_period_bar_month, sync_history.stk_period_bar_month
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
- Raw 表: `raw_tushare.stk_period_bar`（DAO: `raw_stk_period_bar`）
- Core 表: `core_serving.stk_period_bar`（DAO: `stk_period_bar`）
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
- Raw 表: `raw_tushare.stock_basic`（DAO: `raw_stock_basic`）
- Core 表: `core_serving.security_serving`（DAO: `-`）
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
- 无

### `stock_st`

- API: `stock_st`
- Raw 表: `raw_tushare.stock_st`（DAO: `raw_stock_st`）
- Core 表: `core_serving.equity_stock_st`（DAO: `-`）
- 显式请求 fields（5）: ts_code, name, trade_date, type, type_name
- 支持任务: sync_daily.stock_st, sync_history.stock_st
- Raw 字段释义:
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `type`: 上游原始字段，语义请参照对应接口文档
- `name`: 名称
- `type_name`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- 无

### `suspend_d`

- API: `suspend_d`
- Raw 表: `raw_tushare.suspend_d`（DAO: `raw_suspend_d`）
- Core 表: `core_serving.equity_suspend_d`（DAO: `-`）
- 显式请求 fields（4）: ts_code, trade_date, suspend_timing, suspend_type
- 支持任务: backfill_by_trade_date.suspend_d, sync_daily.suspend_d, sync_history.suspend_d
- Raw 字段释义:
- `id`: 系统代理主键
- `row_key_hash`: 记录级哈希键（去重与幂等）
- `ts_code`: 证券代码（含股票/指数/板块等代码）
- `trade_date`: 交易日
- `suspend_timing`: 上游原始字段，语义请参照对应接口文档
- `suspend_type`: 上游原始字段，语义请参照对应接口文档
- `api_name`: 上游原始字段，语义请参照对应接口文档
- `fetched_at`: 抓取时间
- `raw_payload`: 原始响应载荷
- Core 字段释义:
- 无

### `ths_daily`

- API: `ths_daily`
- Raw 表: `raw_tushare.ths_daily`（DAO: `raw_ths_daily`）
- Core 表: `core_serving.ths_daily`（DAO: `-`）
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
- Raw 表: `raw_tushare.ths_hot`（DAO: `raw_ths_hot`）
- Core 表: `core_serving.ths_hot`（DAO: `-`）
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
- Raw 表: `raw_tushare.ths_index`（DAO: `raw_ths_index`）
- Core 表: `core_serving.ths_index`（DAO: `ths_index`）
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
- Raw 表: `raw_tushare.ths_member`（DAO: `raw_ths_member`）
- Core 表: `core_serving.ths_member`（DAO: `-`）
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
- Raw 表: `raw_tushare.top_list`（DAO: `raw_top_list`）
- Core 表: `core_serving.equity_top_list`（DAO: `equity_top_list`）
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
- Raw 表: `raw_tushare.trade_cal`（DAO: `raw_trade_cal`）
- Core 表: `core_serving.trade_calendar`（DAO: `trade_calendar`）
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
- Raw 表: `raw_tushare.us_basic`（DAO: `raw_us_basic`）
- Core 表: `core_serving.us_security`（DAO: `us_security`）
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
