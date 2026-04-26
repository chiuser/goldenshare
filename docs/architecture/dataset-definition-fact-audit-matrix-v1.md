# DatasetDefinition 事实审计矩阵 v1

- 状态：M1 已落档；配合 M2，当前 `DatasetDefinition` 静态事实已收口到 `src/foundation/datasets/definitions/**`
- 日期：2026-04-26
- 范围：当前 57 个数据集定义
- 关联方案：[DatasetDefinition 单一事实源重构方案 v1](/Users/congming/github/goldenshare/docs/architecture/dataset-definition-single-source-refactor-plan-v1.md)

## 1. 审计结论

1. 数据集身份、领域、来源 API、日期模型、输入字段、枚举、多选、写入目标、观测字段，已经形成 `DatasetDefinition` 形态的静态事实。
2. `DatasetDefinition` registry 不再运行时遍历 Sync V2 contract 生成定义；Sync V2 contract 仍作为后续 M3 的执行运行投影改造对象。
3. `dc_index`、`dc_daily`、`dc_member` 的 `idx_type` 已明确为东方财富板块类型枚举：`行业板块 / 概念板块 / 地域板块`。
4. 本矩阵只记录数据集事实，不记录任务状态、freshness 状态、TaskRun 状态，也不引入 checkpoint/acquire/replay 语义。

## 2. 字段说明

| 字段 | 含义 |
|---|---|
| 数据集 | `dataset_key` 与用户可见维护对象名称 |
| 领域 | `DatasetDomain`，用于分组和目录展示 |
| 来源 | 来源适配器与 API 名称 |
| 日期模型 | `date_axis / bucket_rule / input_shape` |
| 输入字段 | 时间字段以外的筛选字段；枚举字段写明可选值和是否多选 |
| 写入目标 | 当前维护后的主要目标表 |
| 规划事实 | universe、enum fanout、pagination、unit 上限 |

## 3. 审计矩阵

| 数据集 | 领域 | 来源 | 日期模型 | 输入字段 | 写入目标 | 规划事实 |
|---|---|---|---|---|---|---|
| `adj_factor`<br/>复权因子 | equity_market<br/>股票行情 | `tushare.adj_factor` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string)<br/>exchange(string) | `core.equity_adj_factor` | universe=none; enum=-; pagination=none; max_units=- |
| `biying_equity_daily`<br/>BIYING 股票日线 | equity_market<br/>股票行情 | `biying.equity_daily_bar` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string)<br/>adj_type(string) | `raw_biying.equity_daily_bar` | universe=none; enum=-; pagination=none; max_units=- |
| `biying_moneyflow`<br/>BIYING 资金流向 | moneyflow<br/>资金流向 | `biying.moneyflow` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string) | `core_serving.equity_moneyflow` | universe=none; enum=-; pagination=none; max_units=- |
| `block_trade`<br/>大宗交易 | equity_market<br/>股票行情 | `tushare.block_trade` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string) | `core_serving.equity_block_trade` | universe=none; enum=-; pagination=offset_limit; max_units=- |
| `broker_recommend`<br/>券商月度金股推荐 | equity_market<br/>股票行情 | `tushare.broker_recommend` | month_key/every_natural_month/month_or_range | - | `core_serving.broker_recommend` | universe=none; enum=-; pagination=offset_limit; max_units=- |
| `cyq_perf`<br/>每日筹码及胜率 | equity_market<br/>股票行情 | `tushare.cyq_perf` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string)<br/>exchange(string) | `core_serving.equity_cyq_perf` | universe=none; enum=-; pagination=offset_limit; max_units=- |
| `daily`<br/>股票日线 | equity_market<br/>股票行情 | `tushare.daily` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string)<br/>exchange(string) | `core_serving.equity_daily_bar` | universe=none; enum=-; pagination=none; max_units=- |
| `daily_basic`<br/>每日指标 | equity_market<br/>股票行情 | `tushare.daily_basic` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string) | `core_serving.equity_daily_basic` | universe=none; enum=-; pagination=none; max_units=- |
| `dc_daily`<br/>东方财富板块日线行情 | board_theme<br/>板块 / 题材 | `tushare.dc_daily` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string)<br/>idx_type(多选枚举:行业板块/概念板块/地域板块) | `core_serving.dc_daily` | universe=none; enum=idx_type; pagination=offset_limit; max_units=5000 |
| `dc_hot`<br/>东方财富热榜 | board_theme<br/>板块 / 题材 | `tushare.dc_hot` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string)<br/>market(多选枚举:A股市场/ETF基金/港股市场/美股市场)<br/>hot_type(多选枚举:人气榜/飙升榜)<br/>is_new(单选枚举:Y) | `core_serving.dc_hot` | universe=none; enum=market, hot_type, is_new; pagination=none; max_units=- |
| `dc_index`<br/>东方财富板块列表 | board_theme<br/>板块 / 题材 | `tushare.dc_index` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string)<br/>idx_type(多选枚举:行业板块/概念板块/地域板块) | `core_serving.dc_index` | universe=none; enum=idx_type; pagination=none; max_units=- |
| `dc_member`<br/>东方财富板块成分 | board_theme<br/>板块 / 题材 | `tushare.dc_member` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string)<br/>con_code(string)<br/>idx_type(多选枚举:行业板块/概念板块/地域板块) | `core_serving.dc_member` | universe=dc_index_board_codes; enum=-; pagination=none; max_units=5000 |
| `dividend`<br/>分红送股 | low_frequency<br/>低频数据 | `tushare.dividend` | natural_day/every_natural_day/ann_date_or_start_end | ts_code(string)<br/>record_date(date)<br/>ex_date(date)<br/>imp_ann_date(date) | `core_serving.equity_dividend` | universe=none; enum=-; pagination=offset_limit; max_units=- |
| `etf_basic`<br/>ETF 基础信息 | reference_data<br/>基础主数据 | `tushare.etf_basic` | none/not_applicable/none | ts_code(string)<br/>index_code(string)<br/>exchange(string)<br/>mgr(string)<br/>list_status(list)<br/>list_date(date) | `core_serving.etf_basic` | universe=none; enum=-; pagination=none; max_units=- |
| `etf_index`<br/>ETF 跟踪指数 | index_fund<br/>指数 / ETF | `tushare.etf_index` | none/not_applicable/none | ts_code(string)<br/>pub_date(date)<br/>base_date(date) | `core_serving.etf_index` | universe=none; enum=-; pagination=none; max_units=- |
| `fund_adj`<br/>基金复权因子 | index_fund<br/>指数 / ETF | `tushare.fund_adj` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string) | `core.fund_adj_factor` | universe=none; enum=-; pagination=offset_limit; max_units=- |
| `fund_daily`<br/>基金日线行情 | index_fund<br/>指数 / ETF | `tushare.fund_daily` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string)<br/>exchange(string) | `core_serving.fund_daily_bar` | universe=none; enum=-; pagination=offset_limit; max_units=- |
| `hk_basic`<br/>港股基础信息 | reference_data<br/>基础主数据 | `tushare.hk_basic` | none/not_applicable/none | list_status(list) | `core_serving.hk_security` | universe=none; enum=-; pagination=none; max_units=- |
| `index_basic`<br/>指数基础信息 | index_fund<br/>指数 / ETF | `tushare.index_basic` | none/not_applicable/none | ts_code(string) | `core_serving.index_basic` | universe=none; enum=-; pagination=none; max_units=- |
| `index_daily`<br/>指数日线行情 | index_fund<br/>指数 / ETF | `tushare.index_daily` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string)<br/>exchange(string) | `core_serving.index_daily_serving` | universe=index_active_codes; enum=-; pagination=offset_limit; max_units=- |
| `index_daily_basic`<br/>指数每日指标 | index_fund<br/>指数 / ETF | `tushare.index_dailybasic` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string)<br/>exchange(string) | `core_serving.index_daily_basic` | universe=none; enum=-; pagination=offset_limit; max_units=- |
| `index_monthly`<br/>指数月线 | index_fund<br/>指数 / ETF | `tushare.index_monthly` | trade_open_day/month_last_open_day/trade_date_or_start_end | ts_code(string) | `core_serving.index_monthly_serving` | universe=none; enum=-; pagination=offset_limit; max_units=- |
| `index_weekly`<br/>指数周线 | index_fund<br/>指数 / ETF | `tushare.index_weekly` | trade_open_day/week_last_open_day/trade_date_or_start_end | ts_code(string) | `core_serving.index_weekly_serving` | universe=none; enum=-; pagination=offset_limit; max_units=- |
| `index_weight`<br/>指数成分权重 | index_fund<br/>指数 / ETF | `tushare.index_weight` | month_window/month_window_has_data/start_end_month_window | index_code(string) | `core_serving.index_weight` | universe=none; enum=-; pagination=offset_limit; max_units=- |
| `kpl_concept_cons`<br/>开盘啦板块成分 | board_theme<br/>板块 / 题材 | `tushare.kpl_concept_cons` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string)<br/>con_code(string) | `core_serving.kpl_concept_cons` | universe=none; enum=-; pagination=none; max_units=- |
| `kpl_list`<br/>开盘啦榜单 | board_theme<br/>板块 / 题材 | `tushare.kpl_list` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string)<br/>tag(多选枚举:涨停/炸板/跌停/自然涨停/竞价) | `core_serving.kpl_list` | universe=none; enum=tag; pagination=none; max_units=- |
| `limit_cpt_list`<br/>涨停概念列表 | equity_market<br/>股票行情 | `tushare.limit_cpt_list` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string) | `core_serving.limit_cpt_list` | universe=none; enum=-; pagination=none; max_units=- |
| `limit_list_d`<br/>每日涨跌停名单 | equity_market<br/>股票行情 | `tushare.limit_list_d` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string)<br/>limit_type(多选枚举:U/D/Z)<br/>exchange(多选枚举:SH/SZ/BJ) | `core_serving.equity_limit_list` | universe=none; enum=limit_type, exchange; pagination=none; max_units=- |
| `limit_list_ths`<br/>同花顺涨停名单 | equity_market<br/>股票行情 | `tushare.limit_list_ths` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string)<br/>limit_type(多选枚举:涨停池/连板池/冲刺涨停/炸板池/跌停池)<br/>market(多选枚举:HS/GEM/STAR) | `core_serving.limit_list_ths` | universe=none; enum=limit_type, market; pagination=none; max_units=- |
| `limit_step`<br/>连板梯队 | equity_market<br/>股票行情 | `tushare.limit_step` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string)<br/>nums(string) | `core_serving.limit_step` | universe=none; enum=-; pagination=none; max_units=- |
| `margin`<br/>融资融券汇总 | equity_market<br/>股票行情 | `tushare.margin` | trade_open_day/every_open_day/trade_date_or_start_end | exchange_id(多选枚举:SSE/SZSE/BSE) | `core_serving.equity_margin` | universe=none; enum=exchange_id; pagination=none; max_units=- |
| `moneyflow`<br/>个股资金流向 | moneyflow<br/>资金流向 | `tushare.moneyflow` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string) | `core_serving.equity_moneyflow` | universe=none; enum=-; pagination=none; max_units=- |
| `moneyflow_cnt_ths`<br/>概念板块资金流向(THS) | moneyflow<br/>资金流向 | `tushare.moneyflow_cnt_ths` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string) | `core_serving.concept_moneyflow_ths` | universe=none; enum=-; pagination=none; max_units=- |
| `moneyflow_dc`<br/>个股资金流向(DC) | moneyflow<br/>资金流向 | `tushare.moneyflow_dc` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string) | `core_serving.equity_moneyflow_dc` | universe=none; enum=-; pagination=offset_limit; max_units=- |
| `moneyflow_ind_dc`<br/>板块资金流向(DC) | moneyflow<br/>资金流向 | `tushare.moneyflow_ind_dc` | trade_open_day/every_open_day/trade_date_or_start_end | content_type(多选枚举:行业/概念/地域)<br/>ts_code(string) | `core_serving.board_moneyflow_dc` | universe=none; enum=content_type; pagination=offset_limit; max_units=- |
| `moneyflow_ind_ths`<br/>行业资金流向(THS) | moneyflow<br/>资金流向 | `tushare.moneyflow_ind_ths` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string) | `core_serving.industry_moneyflow_ths` | universe=none; enum=-; pagination=offset_limit; max_units=- |
| `moneyflow_mkt_dc`<br/>市场资金流向(DC) | moneyflow<br/>资金流向 | `tushare.moneyflow_mkt_dc` | trade_open_day/every_open_day/trade_date_or_start_end | - | `core_serving.market_moneyflow_dc` | universe=none; enum=-; pagination=offset_limit; max_units=- |
| `moneyflow_ths`<br/>个股资金流向(THS) | moneyflow<br/>资金流向 | `tushare.moneyflow_ths` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string) | `core_serving.equity_moneyflow_ths` | universe=none; enum=-; pagination=offset_limit; max_units=- |
| `stk_factor_pro`<br/>股票技术面因子(专业版) | equity_market<br/>股票行情 | `tushare.stk_factor_pro` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string) | `core_serving.equity_factor_pro` | universe=none; enum=-; pagination=offset_limit; max_units=- |
| `stk_holdernumber`<br/>股东户数 | low_frequency<br/>低频数据 | `tushare.stk_holdernumber` | natural_day/every_natural_day/ann_date_or_start_end | ts_code(string)<br/>enddate(date) | `core_serving.equity_holder_number` | universe=none; enum=-; pagination=offset_limit; max_units=- |
| `stk_limit`<br/>每日涨跌停价格 | equity_market<br/>股票行情 | `tushare.stk_limit` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string) | `core_serving.equity_stk_limit` | universe=none; enum=-; pagination=offset_limit; max_units=- |
| `stk_mins`<br/>股票历史分钟行情 | equity_market<br/>股票行情 | `tushare.stk_mins` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string)<br/>freq(多选枚举:1min/5min/15min/30min/60min) | `raw_tushare.stk_mins` | universe=none; enum=-; pagination=offset_limit; max_units=- |
| `stk_nineturn`<br/>神奇九转指标 | equity_market<br/>股票行情 | `tushare.stk_nineturn` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string) | `core_serving.equity_nineturn` | universe=none; enum=-; pagination=offset_limit; max_units=- |
| `stk_period_bar_adj_month`<br/>股票月线行情（复权） | equity_market<br/>股票行情 | `tushare.stk_week_month_adj` | trade_open_day/month_last_open_day/trade_date_or_start_end | ts_code(string) | `core_serving.stk_period_bar_adj` | universe=none; enum=-; pagination=none; max_units=- |
| `stk_period_bar_adj_week`<br/>股票周线行情（复权） | equity_market<br/>股票行情 | `tushare.stk_week_month_adj` | trade_open_day/week_last_open_day/trade_date_or_start_end | ts_code(string) | `core_serving.stk_period_bar_adj` | universe=none; enum=-; pagination=none; max_units=- |
| `stk_period_bar_month`<br/>股票月线行情 | equity_market<br/>股票行情 | `tushare.stk_weekly_monthly` | trade_open_day/month_last_open_day/trade_date_or_start_end | ts_code(string) | `core_serving.stk_period_bar` | universe=none; enum=-; pagination=none; max_units=- |
| `stk_period_bar_week`<br/>股票周线行情 | equity_market<br/>股票行情 | `tushare.stk_weekly_monthly` | trade_open_day/week_last_open_day/trade_date_or_start_end | ts_code(string) | `core_serving.stk_period_bar` | universe=none; enum=-; pagination=none; max_units=- |
| `stock_basic`<br/>股票主数据 | reference_data<br/>基础主数据 | `tushare.stock_basic` | none/not_applicable/none | source_key(单选枚举:tushare/biying/all)<br/>ts_code(string)<br/>name(string)<br/>market(list)<br/>exchange(list)<br/>list_status(list)<br/>is_hs(list) | `core_serving.security_serving` | universe=none; enum=-; pagination=offset_limit; max_units=- |
| `stock_st`<br/>ST股票列表 | equity_market<br/>股票行情 | `tushare.stock_st` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string) | `core_serving.equity_stock_st` | universe=none; enum=-; pagination=offset_limit; max_units=- |
| `suspend_d`<br/>每日停复牌信息 | equity_market<br/>股票行情 | `tushare.suspend_d` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string)<br/>suspend_type(多选枚举:S/R) | `core_serving.equity_suspend_d` | universe=none; enum=-; pagination=offset_limit; max_units=- |
| `ths_daily`<br/>同花顺板块日线行情 | board_theme<br/>板块 / 题材 | `tushare.ths_daily` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string) | `core_serving.ths_daily` | universe=none; enum=-; pagination=offset_limit; max_units=5000 |
| `ths_hot`<br/>同花顺热榜 | board_theme<br/>板块 / 题材 | `tushare.ths_hot` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string)<br/>market(多选枚举:热股/ETF/可转债/行业板块/概念板块/期货/港股/热基/美股)<br/>is_new(单选枚举:Y) | `core_serving.ths_hot` | universe=none; enum=market, is_new; pagination=none; max_units=- |
| `ths_index`<br/>同花顺板块列表 | board_theme<br/>板块 / 题材 | `tushare.ths_index` | none/not_applicable/none | ts_code(string)<br/>exchange(string)<br/>type(string) | `core_serving.ths_index` | universe=none; enum=-; pagination=none; max_units=- |
| `ths_member`<br/>同花顺板块成分 | board_theme<br/>板块 / 题材 | `tushare.ths_member` | none/not_applicable/none | ts_code(string)<br/>con_code(string) | `core_serving.ths_member` | universe=ths_index_board_codes; enum=-; pagination=none; max_units=5000 |
| `top_list`<br/>龙虎榜 | equity_market<br/>股票行情 | `tushare.top_list` | trade_open_day/every_open_day/trade_date_or_start_end | ts_code(string) | `core_serving.equity_top_list` | universe=none; enum=-; pagination=offset_limit; max_units=- |
| `trade_cal`<br/>交易日历 | reference_data<br/>基础主数据 | `tushare.trade_cal` | natural_day/every_natural_day/trade_date_or_start_end | exchange(string) | `core_serving.trade_calendar` | universe=none; enum=-; pagination=none; max_units=- |
| `us_basic`<br/>美股基础信息 | reference_data<br/>基础主数据 | `tushare.us_basic` | none/not_applicable/none | classify(list)<br/>ts_code(string) | `core_serving.us_security` | universe=none; enum=-; pagination=none; max_units=- |

## 4. 后续进入 M3 前的检查点

1. 新增或修改数据集时，必须先改 `src/foundation/datasets/definitions/**`，再派生执行投影。
2. M3 要把执行运行投影从 Sync V2 contract 迁到 `DatasetDefinition -> DatasetRuntimeContract`，不能继续手写两套事实。
3. 若某个字段是业务枚举，必须在 `DatasetDefinition.input_model.filters` 中声明 `enum_values` 与 `multi_value`，不能让 Ops 或前端猜。
4. 若源接口参数值与用户可读标签不同，需要先扩展输入字段模型表达 value/label，再接入 UI；不能用错误字符串凑展示。
