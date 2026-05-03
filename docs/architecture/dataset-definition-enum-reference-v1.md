# DatasetDefinition 枚举语义参考 v1

- 状态：当前事实参考
- 事实来源：`src/foundation/datasets/models.py` 与 `src/foundation/datasets/definitions/**`
- 生成口径：截至 2026-05-03，当前 registry 共 59 个 `DatasetDefinition`
- 目标：统一说明 `DatasetDefinition` 内所有枚举/准枚举字段的实际取值、含义与使用数据集，避免重复定义、语义交叉或隐藏特例。

---

## 1. 使用规则

1. 新增或修改 `DatasetDefinition` 字段取值前，必须先检查本文是否已有对应语义。
2. 如果新增枚举值，必须同步更新本文、相关测试和消费方审计。
3. 不允许把同一语义拆成两个名字，也不允许把两个不同语义塞进同一个名字。
4. 如果实际行为与 Definition 字段不一致，必须视为待收口问题，不能让隐藏逻辑长期存在。

---

## 2. 当前待收口项

### E1：`index_weight` 的对象池扇出没有写进 `universe_policy`

| 数据集 | 当前 Definition 字段 | 实际运行行为 | 问题 | 建议 |
| --- | --- | --- | --- | --- |
| `index_weight` | `planning.universe_policy=none`；`planning.unit_builder_key=build_index_weight_units`；筛选字段为 `index_code` | 未传 `filters.index_code` 时，`build_index_weight_units` 会先查 `ops.index_series_active(resource='index_weight')`；为空时再查 `core_serving.index_basic` 中 `exp_date is null or exp_date >= today` 的未终止指数；然后按每个指数生成 unit | Definition 表面表达“不使用对象池”，真实行为却使用指数对象池；对象池来源优先级藏在 custom builder 中 | 已确定收口方向：`universe_policy` 目标有效值为 `no_pool/pool`；`none` 只表示未定义或历史未迁移；具体对象池规则沉到 `planning.universe` |

### E2：`date_model.input_shape=none` 的时间字段已清零

当前已确认：所有 `date_model.input_shape=none` 的数据集，`input_model.time_fields` 均为空，且 `capabilities.supported_time_modes` 不再暴露虚假的单日/区间维护入口。

| 数据集 | 当前 `date_model.date_axis` | 当前 `date_model.window_mode` | 当前 `date_model.input_shape` | 当前 `input_model.time_fields` | 当前 `supported_time_modes` | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| `etf_basic` | `none` | `none` | `none` | 空 | `none` | `list_date` 保留为业务筛选字段，不作为维护时间轴 |
| `etf_index` | `none` | `none` | `none` | 空 | `none` | `pub_date/base_date` 保留为业务筛选字段，不作为维护时间轴 |
| `hk_basic` | `none` | `none` | `none` | 空 | `none` | 源站输入无日期参数 |
| `index_basic` | `none` | `none` | `none` | 空 | `none` | 源站无维护时间轴 |
| `stock_basic` | `none` | `none` | `none` | 空 | `none` | 多来源基础主数据，无维护时间轴 |
| `ths_index` | `none` | `none` | `none` | 空 | `none` | 源站输入无日期参数 |
| `ths_member` | `none` | `none` | `none` | 空 | `none` | 源站输入无日期参数；对象池仍由 `ths_index_board_codes` 生成 |
| `us_basic` | `none` | `none` | `none` | 空 | `none` | 源站输入无日期参数 |

### E3：非通用 selector 的具体命中范围

这里的问题不是“这些数据集一定错误”，而是这些字段目前都是字符串 selector。新增或修改时必须查本文和实现注册表，不能随手新造名字。当前非通用命中范围如下。

#### E3.1 `planning.unit_builder_key != generic`

| 数据集 | 当前 `unit_builder_key` | 需要关注的隐藏语义 |
| --- | --- | --- |
| `biying_equity_daily` | `build_biying_equity_daily_units` | Biying 股票日线 unit 生成 |
| `biying_moneyflow` | `build_biying_moneyflow_units` | Biying 资金流 unit 生成 |
| `cctv_news` | `build_cctv_news_units` | 新闻联播按日期 unit 生成 |
| `dividend` | `build_dividend_units` | 分红送股按公告日/区间 unit 生成 |
| `index_daily` | `build_index_daily_units` | 指数日线按指数对象池 unit 生成 |
| `index_weight` | `build_index_weight_units` | 指数权重按自然月窗口与指数对象池 unit 生成；另见 E1 |
| `major_news` | `build_major_news_units` | 新闻通讯按日期与来源 unit 生成 |
| `stk_holdernumber` | `build_stk_holdernumber_units` | 股东户数按公告日/区间 unit 生成 |
| `stk_mins` | `build_stk_mins_units` | 分钟行情按股票、频率、时间窗口 unit 生成 |
| `stock_basic` | `build_stock_basic_units` | 股票基础信息按来源 unit 生成 |

#### E3.2 `normalization.row_transform_name != None`

| 数据集 | 当前 `row_transform_name` |
| --- | --- |
| `biying_equity_daily` | `_biying_equity_daily_row_transform` |
| `biying_moneyflow` | `_biying_moneyflow_row_transform` |
| `cctv_news` | `_cctv_news_row_transform` |
| `daily` | `_daily_row_transform` |
| `dc_hot` | `_dc_hot_row_transform` |
| `dividend` | `_dividend_row_transform` |
| `fund_daily` | `_fund_daily_row_transform` |
| `hk_basic` | `_hk_security_row_transform` |
| `index_daily` | `_index_daily_row_transform` |
| `index_monthly` | `_index_daily_row_transform` |
| `index_weekly` | `_index_daily_row_transform` |
| `kpl_concept_cons` | `_kpl_concept_cons_row_transform` |
| `limit_list_d` | `_limit_list_row_transform` |
| `limit_list_ths` | `_limit_list_ths_row_transform` |
| `major_news` | `_major_news_row_transform` |
| `moneyflow` | `_moneyflow_row_transform` |
| `stk_holdernumber` | `_holdernumber_row_transform` |
| `stk_mins` | `_stk_mins_row_transform` |
| `stk_period_bar_adj_month` | `_stk_period_bar_adj_row_transform` |
| `stk_period_bar_adj_week` | `_stk_period_bar_adj_row_transform` |
| `stk_period_bar_month` | `_stk_period_bar_row_transform` |
| `stk_period_bar_week` | `_stk_period_bar_row_transform` |
| `stock_basic` | `_stock_basic_row_transform` |
| `suspend_d` | `_suspend_d_row_transform` |
| `ths_hot` | `_ths_hot_row_transform` |
| `top_list` | `_top_list_row_transform` |
| `trade_cal` | `_trade_cal_row_transform` |
| `us_basic` | `_us_security_row_transform` |

#### E3.3 `source.request_builder_key`

当前 59 个数据集均有各自的 `request_builder_key`，完整清单见第 3.6 节。新增数据集时，必须优先复用已有 request builder；确实需要新增时，必须同步新增实现、注册表、测试和本文条目。

---

## 3. 领域与来源枚举

### 3.1 `domain.domain_key`

| 值 | 含义 | 使用数据集 |
| --- | --- | --- |
| `board_theme` | 板块、主题、热榜类数据 | `dc_daily`, `dc_hot`, `dc_index`, `dc_member`, `kpl_concept_cons`, `kpl_list`, `ths_daily`, `ths_hot`, `ths_index`, `ths_member` |
| `equity_market` | A 股行情、指标、事件类数据 | `adj_factor`, `biying_equity_daily`, `block_trade`, `broker_recommend`, `cyq_perf`, `daily`, `daily_basic`, `limit_cpt_list`, `limit_list_d`, `limit_list_ths`, `limit_step`, `margin`, `stk_factor_pro`, `stk_limit`, `stk_mins`, `stk_nineturn`, `stk_period_bar_adj_month`, `stk_period_bar_adj_week`, `stk_period_bar_month`, `stk_period_bar_week`, `stock_st`, `suspend_d`, `top_list` |
| `index_fund` | 指数、ETF、基金行情和主数据 | `etf_index`, `fund_adj`, `fund_daily`, `index_basic`, `index_daily`, `index_daily_basic`, `index_monthly`, `index_weekly`, `index_weight` |
| `low_frequency` | 低频事件型数据 | `dividend`, `stk_holdernumber` |
| `moneyflow` | 资金流相关数据 | `biying_moneyflow`, `moneyflow`, `moneyflow_cnt_ths`, `moneyflow_dc`, `moneyflow_ind_dc`, `moneyflow_ind_ths`, `moneyflow_mkt_dc`, `moneyflow_ths` |
| `news` | 新闻、语料类数据 | `cctv_news`, `major_news` |
| `reference_data` | 基础主数据、证券主数据、日历等参考数据 | `etf_basic`, `hk_basic`, `stock_basic`, `trade_cal`, `us_basic` |

### 3.2 `domain.cadence`

| 值 | 含义 | 使用数据集 |
| --- | --- | --- |
| `daily` | 每日维护或每日观察的数据 | 50 个数据集：除 `dividend`, `etf_basic`, `etf_index`, `hk_basic`, `major_news`, `stk_holdernumber`, `stock_basic`, `trade_cal`, `us_basic` 外的大多数 Tushare/Biying 数据集 |
| `intraday` | 盘中或高频发布的数据 | `major_news` |
| `low_frequency` | 非每日固定频率的低频数据 | `dividend`, `stk_holdernumber` |
| `snapshot` | 快照/主数据类数据 | `etf_basic`, `etf_index`, `hk_basic`, `stock_basic`, `trade_cal`, `us_basic` |

### 3.3 `source.source_key_default`

| 值 | 含义 | 使用数据集 |
| --- | --- | --- |
| `tushare` | 默认从 Tushare 获取 | 57 个数据集 |
| `biying` | 默认从 Biying 获取 | `biying_equity_daily`, `biying_moneyflow` |

### 3.4 `source.source_keys`

| 值 | 含义 | 使用数据集 |
| --- | --- | --- |
| `tushare` | 只支持 Tushare | 56 个数据集 |
| `biying` | 只支持 Biying | `biying_equity_daily`, `biying_moneyflow` |
| `biying,tushare` | 多来源数据集 | `stock_basic` |

### 3.5 `source.adapter_key`

| 值 | 含义 | 使用数据集 |
| --- | --- | --- |
| `tushare` | 使用 Tushare source client | 57 个数据集 |
| `biying` | 使用 Biying source client | `biying_equity_daily`, `biying_moneyflow` |

### 3.6 `source.request_builder_key`

`request_builder_key` 是源接口请求参数构造器 selector。每个值必须能在 `src/foundation/ingestion/request_builders.py` 中找到对应实现。

| 值 | 使用数据集 |
| --- | --- |
| `_adj_factor_params` | `adj_factor` |
| `_biying_equity_daily_params` | `biying_equity_daily` |
| `_biying_moneyflow_params` | `biying_moneyflow` |
| `_block_trade_params` | `block_trade` |
| `_broker_recommend_params` | `broker_recommend` |
| `_cctv_news_params` | `cctv_news` |
| `_cyq_perf_params` | `cyq_perf` |
| `_daily_basic_params` | `daily_basic` |
| `_daily_params` | `daily` |
| `_dc_daily_params` | `dc_daily` |
| `_dc_hot_params` | `dc_hot` |
| `_dc_index_params` | `dc_index` |
| `_dc_member_params` | `dc_member` |
| `_dividend_params` | `dividend` |
| `_etf_basic_params` | `etf_basic` |
| `_etf_index_params` | `etf_index` |
| `_fund_adj_params` | `fund_adj` |
| `_fund_daily_params` | `fund_daily` |
| `_hk_basic_params` | `hk_basic` |
| `_index_basic_params` | `index_basic` |
| `_index_daily_basic_params` | `index_daily_basic` |
| `_index_daily_params` | `index_daily` |
| `_index_monthly_params` | `index_monthly` |
| `_index_weekly_params` | `index_weekly` |
| `_index_weight_params` | `index_weight` |
| `_kpl_concept_cons_params` | `kpl_concept_cons` |
| `_kpl_list_params` | `kpl_list` |
| `_limit_cpt_list_params` | `limit_cpt_list` |
| `_limit_list_params` | `limit_list_d` |
| `_limit_list_ths_params` | `limit_list_ths` |
| `_limit_step_params` | `limit_step` |
| `_major_news_params` | `major_news` |
| `_margin_params` | `margin` |
| `_moneyflow_cnt_ths_params` | `moneyflow_cnt_ths` |
| `_moneyflow_dc_params` | `moneyflow_dc` |
| `_moneyflow_ind_dc_params` | `moneyflow_ind_dc` |
| `_moneyflow_ind_ths_params` | `moneyflow_ind_ths` |
| `_moneyflow_mkt_dc_params` | `moneyflow_mkt_dc` |
| `_moneyflow_params` | `moneyflow` |
| `_moneyflow_ths_params` | `moneyflow_ths` |
| `_stk_factor_pro_params` | `stk_factor_pro` |
| `_stk_holdernumber_params` | `stk_holdernumber` |
| `_stk_limit_params` | `stk_limit` |
| `_stk_mins_params` | `stk_mins` |
| `_stk_nineturn_params` | `stk_nineturn` |
| `_stk_period_bar_adj_month_params` | `stk_period_bar_adj_month` |
| `_stk_period_bar_adj_week_params` | `stk_period_bar_adj_week` |
| `_stk_period_bar_month_params` | `stk_period_bar_month` |
| `_stk_period_bar_week_params` | `stk_period_bar_week` |
| `_stock_basic_params` | `stock_basic` |
| `_stock_st_params` | `stock_st` |
| `_suspend_d_params` | `suspend_d` |
| `_ths_daily_params` | `ths_daily` |
| `_ths_hot_params` | `ths_hot` |
| `_ths_index_params` | `ths_index` |
| `_ths_member_params` | `ths_member` |
| `_top_list_params` | `top_list` |
| `_trade_cal_params` | `trade_cal` |
| `_us_basic_params` | `us_basic` |

### 3.7 `source.base_params`

当前所有 DatasetDefinition 的 `base_params` 均为空。新增默认源参数前必须明确：它是源接口固定事实，而不是用户输入、调度策略或执行器临时补参。

---

## 4. 日期模型枚举

### 4.1 `date_model.date_axis`

| 值 | 含义 | 使用数据集 |
| --- | --- | --- |
| `trade_open_day` | 以交易日为日期轴 | `adj_factor`, `biying_equity_daily`, `biying_moneyflow`, `block_trade`, `cyq_perf`, `daily`, `daily_basic`, `dc_daily`, `dc_hot`, `dc_index`, `dc_member`, `fund_adj`, `fund_daily`, `index_daily`, `index_daily_basic`, `index_monthly`, `index_weekly`, `kpl_concept_cons`, `kpl_list`, `limit_cpt_list`, `limit_list_d`, `limit_list_ths`, `limit_step`, `margin`, `moneyflow`, `moneyflow_cnt_ths`, `moneyflow_dc`, `moneyflow_ind_dc`, `moneyflow_ind_ths`, `moneyflow_mkt_dc`, `moneyflow_ths`, `stk_factor_pro`, `stk_limit`, `stk_mins`, `stk_nineturn`, `stock_st`, `suspend_d`, `ths_daily`, `ths_hot`, `top_list` |
| `natural_day` | 以自然日为日期轴 | `cctv_news`, `dividend`, `major_news`, `stk_holdernumber`, `stk_period_bar_adj_month`, `stk_period_bar_adj_week`, `stk_period_bar_month`, `stk_period_bar_week`, `trade_cal` |
| `month_key` | 以 `YYYYMM` 月份键为日期轴 | `broker_recommend` |
| `month_window` | 以自然月起止窗口为日期轴 | `index_weight` |
| `none` | 无业务日期轴 | `etf_basic`, `etf_index`, `hk_basic`, `index_basic`, `stock_basic`, `ths_index`, `ths_member`, `us_basic` |

### 4.2 `date_model.bucket_rule`

| 值 | 含义 | 使用数据集 |
| --- | --- | --- |
| `every_open_day` | 每个交易日都应有观察桶 | 38 个交易日数据集 |
| `every_natural_day` | 每个自然日都应有观察桶 | `cctv_news`, `dividend`, `stk_holdernumber`, `trade_cal` |
| `every_natural_month` | 每个自然月键都应有观察桶 | `broker_recommend` |
| `week_friday` | 自然周周五作为周频锚点 | `stk_period_bar_adj_week`, `stk_period_bar_week` |
| `month_last_calendar_day` | 自然月最后一天作为月频锚点 | `stk_period_bar_adj_month`, `stk_period_bar_month` |
| `week_last_open_day` | 每周最后一个交易日作为锚点 | `index_weekly` |
| `month_last_open_day` | 每月最后一个交易日作为锚点 | `index_monthly` |
| `month_window_has_data` | 自然月窗口内至少有数据 | `index_weight` |
| `not_applicable` | 不适用日期完整性 | `etf_basic`, `etf_index`, `hk_basic`, `index_basic`, `major_news`, `stock_basic`, `ths_index`, `ths_member`, `us_basic` |

### 4.3 `date_model.window_mode`

| 值 | 含义 | 使用数据集 |
| --- | --- | --- |
| `none` | 不需要用户选择时间 | `etf_basic`, `etf_index`, `hk_basic`, `index_basic`, `stock_basic`, `ths_index`, `ths_member`, `us_basic` |
| `point_or_range` | 支持单点或区间 | 48 个数据集 |
| `range` | 只支持区间或窗口 | `dividend`, `index_weight`, `stk_holdernumber` |

### 4.4 `date_model.input_shape`

| 值 | 含义 | 使用数据集 |
| --- | --- | --- |
| `none` | 无时间输入 | `etf_basic`, `etf_index`, `hk_basic`, `index_basic`, `stock_basic`, `ths_index`, `ths_member`, `us_basic` |
| `trade_date_or_start_end` | 单日 `trade_date` 或区间 `start_date/end_date` | 47 个数据集 |
| `ann_date_or_start_end` | 公告日 `ann_date` 或区间 `start_date/end_date` | `dividend`, `stk_holdernumber` |
| `month_or_range` | 月份键或月份区间 | `broker_recommend` |
| `start_end_month_window` | 自然月窗口，输入月份键，resolver 展开为自然月起止日期 | `index_weight` |

### 4.5 `date_model.observed_field`

| 值 | 含义 | 使用数据集 |
| --- | --- | --- |
| `trade_date` | 用 `trade_date` 作为观测日期 | 45 个数据集 |
| `ann_date` | 用公告日作为观测日期 | `dividend`, `stk_holdernumber` |
| `date` | 用自然日期字段作为观测日期 | `cctv_news` |
| `month` | 用月份键作为观测桶 | `broker_recommend` |
| `pub_time` | 用发布时间作为观测时间 | `major_news` |
| `trade_time` | 用交易时间作为观测时间 | `stk_mins` |
| `None` | 无观测日期字段 | `etf_basic`, `etf_index`, `hk_basic`, `index_basic`, `stock_basic`, `ths_index`, `ths_member`, `us_basic` |

### 4.6 `date_model.audit_applicable`

| 值 | 含义 | 使用数据集 |
| --- | --- | --- |
| `True` | 适用日期完整性审计 | 49 个数据集 |
| `False` | 不适用日期完整性审计 | `etf_basic`, `etf_index`, `hk_basic`, `index_basic`, `major_news`, `stk_mins`, `stock_basic`, `ths_index`, `ths_member`, `us_basic` |

### 4.7 `date_model.not_applicable_reason`

| 值 | 含义 | 使用数据集 |
| --- | --- | --- |
| `snapshot/master dataset` | 主数据或快照数据，不按日期完整性审计 | `etf_basic`, `etf_index`, `hk_basic`, `index_basic`, `stock_basic`, `ths_index`, `ths_member`, `us_basic` |
| `minute completeness audit requires trading-session calendar` | 分钟级完整性需要交易时段日历，本模型暂不直接审计 | `stk_mins` |
| `新闻通讯按来源与发布时间采集，不保证每个自然日或每个来源都有数据。` | 新闻来源不保证每日覆盖 | `major_news` |
| `None` | 可审计或未声明不适用原因 | 49 个数据集 |

### 4.8 `DatasetDateModel.selection_rule()` 派生值

| `bucket_rule` | 派生 `selection_rule` | 含义 |
| --- | --- | --- |
| `week_friday` | `week_friday` | 自然周五 |
| `month_last_calendar_day` | `month_end` | 自然月最后一天 |
| `week_last_open_day` | `week_last_trading_day` | 每周最后一个交易日 |
| `month_last_open_day` | `month_last_trading_day` | 每月最后一个交易日 |
| `every_natural_day` | `calendar_day` | 自然日 |
| `every_natural_month` | `month_key` | 月份键 |
| `month_window_has_data` | `month_window` | 自然月窗口 |
| `not_applicable` | `none` | 无日期选择 |
| 其他值 | `trading_day_only` | 默认交易日 |

---

## 5. 输入字段枚举

### 5.1 `DatasetInputField.field_type`

| 值 | 含义 | 使用字段 |
| --- | --- | --- |
| `date` | 日期输入字段 | `trade_date`, `start_date`, `end_date`, `ann_date`, `base_date`, `enddate`, `ex_date`, `imp_ann_date`, `list_date`, `pub_date`, `record_date` |
| `string` | 普通字符串输入 | `ts_code`, `index_code`, `con_code`, `exchange`, `month`, `name`, `publisher`, `category`, `mgr`, `type`, `nums`, `adj_type` |
| `enum` | 单选枚举 | `index_basic.market`, `stock_basic.source_key` |
| `list` | 枚举列表或多选参数 | `classify`, `content_type`, `exchange`, `exchange_id`, `freq`, `hot_type`, `idx_type`, `is_hs`, `is_new`, `limit_type`, `list_status`, `market`, `src`, `suspend_type`, `symbol`, `tag` |

### 5.2 `input_model.filters.enum_values`

| 数据集 | 字段 | 类型 | 多选 | 默认值 | 枚举值 | 含义 |
| --- | --- | --- | --- | --- | --- | --- |
| `dc_daily` | `idx_type` | `list` | 是 | - | `行业板块`, `概念板块`, `地域板块` | 东财板块类型 |
| `dc_hot` | `market` | `list` | 是 | - | `A股市场`, `ETF基金`, `港股市场`, `美股市场` | 东财热榜市场 |
| `dc_hot` | `hot_type` | `list` | 是 | - | `人气榜`, `飙升榜` | 东财热榜类型 |
| `dc_hot` | `is_new` | `list` | 否 | - | `Y` | 日终/最新标记，当前默认扇出使用 `Y` |
| `dc_index` | `idx_type` | `list` | 是 | - | `行业板块`, `概念板块`, `地域板块` | 东财板块类型 |
| `dc_member` | `idx_type` | `list` | 是 | - | `行业板块`, `概念板块`, `地域板块` | 东财成分接口板块类型 |
| `index_basic` | `market` | `enum` | 否 | - | `MSCI`, `CSI`, `SSE`, `SZSE`, `CICC`, `SW`, `OTH` | 指数市场；不填表示全量 |
| `kpl_list` | `tag` | `list` | 是 | - | `涨停`, `炸板`, `跌停`, `自然涨停`, `竞价` | 开盘啦榜单标签 |
| `limit_list_d` | `limit_type` | `list` | 是 | - | `U`, `D`, `Z` | 每日涨跌停榜单类型 |
| `limit_list_d` | `exchange` | `list` | 是 | - | `SH`, `SZ`, `BJ` | 交易所 |
| `limit_list_ths` | `limit_type` | `list` | 是 | - | `涨停池`, `连板池`, `冲刺涨停`, `炸板池`, `跌停池` | 同花顺涨跌停榜单类型 |
| `limit_list_ths` | `market` | `list` | 是 | - | `HS`, `GEM`, `STAR` | 同花顺市场 |
| `major_news` | `src` | `list` | 是 | - | `新华网`, `凤凰财经`, `同花顺`, `新浪财经`, `华尔街见闻`, `中证网`, `财新网`, `第一财经`, `财联社` | 新闻来源 |
| `margin` | `exchange_id` | `list` | 是 | - | `SSE`, `SZSE`, `BSE` | 交易所 |
| `moneyflow_ind_dc` | `content_type` | `list` | 是 | - | `行业`, `概念`, `地域` | 东财板块资金类型 |
| `stk_mins` | `freq` | `list` | 是 | - | `1min`, `5min`, `15min`, `30min`, `60min` | 分钟频度 |
| `stock_basic` | `source_key` | `enum` | 否 | `tushare` | `tushare`, `biying`, `all` | 股票基础信息来源 |
| `suspend_d` | `suspend_type` | `list` | 是 | - | `S`, `R` | 停牌/复牌 |
| `ths_hot` | `market` | `list` | 是 | - | `热股`, `ETF`, `可转债`, `行业板块`, `概念板块`, `期货`, `港股`, `热基`, `美股` | 同花顺热榜市场 |
| `ths_hot` | `is_new` | `list` | 否 | - | `Y` | 日终/最新标记，当前默认扇出使用 `Y` |

---

## 6. 存储与写入枚举

### 6.1 `storage.delivery_mode`

| 值 | 含义 | 使用数据集 |
| --- | --- | --- |
| `single_source_serving` | 单来源 raw 直接发布到 serving/core_serving | 50 个数据集 |
| `core_direct` | 直接写 core 表 | `adj_factor`, `fund_adj` |
| `raw_collection` | 只采集 raw，不立即发布 serving | `biying_equity_daily`, `stk_mins` |
| `raw_with_serving_light_view` | raw 采集，并有轻量查询视图 | `cctv_news`, `major_news` |
| `multi_source_fusion` | 多来源进入标准化/融合后发布 | `biying_moneyflow`, `moneyflow`, `stock_basic` |

### 6.2 `storage.layer_plan`

| 值 | 含义 | 使用数据集 |
| --- | --- | --- |
| `raw->serving` | raw 写入后发布到 serving/core_serving | 50 个数据集 |
| `raw->core` | raw 写入后发布到 core | `adj_factor`, `fund_adj` |
| `raw-only` | 只落 raw | `biying_equity_daily`, `stk_mins` |
| `raw->serving_light_view` | raw 加轻量服务视图 | `cctv_news`, `major_news` |
| `raw->std->resolution->serving` | 多源标准化、决议、发布链路 | `biying_moneyflow`, `moneyflow`, `stock_basic` |

### 6.3 `storage.write_path`

| 值 | 含义 | 使用数据集 |
| --- | --- | --- |
| `raw_core_upsert` | raw 与 core/serving upsert 主路径 | 49 个数据集 |
| `raw_only_upsert` | 只写 raw | `biying_equity_daily`, `cctv_news`, `major_news`, `stk_mins` |
| `raw_index_period_serving_upsert` | 指数周/月线周期服务表写入 | `index_monthly`, `index_weekly` |
| `raw_core_snapshot_insert_by_trade_date` | 按交易日快照插入 | `block_trade` |
| `raw_std_publish_moneyflow` | Tushare 资金流多源发布 | `moneyflow` |
| `raw_std_publish_moneyflow_biying` | Biying 资金流多源发布 | `biying_moneyflow` |
| `raw_std_publish_stock_basic` | 股票基础信息多源发布 | `stock_basic` |

---

## 7. 规划枚举

### 7.1 `planning.universe_policy`

| 值 | 含义 | 使用数据集 |
| --- | --- | --- |
| `none` | 当前历史未收口值；目标语义只能表示未定义或未迁移，不能表示“没有对象池展开” | 56 个数据集，包括 `index_weight` |
| `index_active_codes` | 指数 code 池展开；优先 `ops.index_series_active`，为空则用 `index_basic` 未终止指数 | `index_daily` |
| `dc_index_board_codes` | 从东财板块代码池展开 | `dc_member` |
| `ths_index_board_codes` | 从同花顺板块代码池展开 | `ths_member` |

说明：

1. 上表是 2026-05-03 当前代码事实，不代表长期目标模型。
2. 已拍板的收口方向是：`universe_policy` 目标有效值只保留 `no_pool/pool`。
3. `none` 只允许表达未定义或历史未迁移状态，不允许表达“没有对象池展开”。
4. `index_active_codes`、`dc_index_board_codes`、`ths_index_board_codes` 这类实现型 selector，后续应下沉到 `planning.universe.sources`。
5. 详细方案见 [Dataset Universe 模型收口方案 v1](/Users/congming/github/goldenshare/docs/architecture/dataset-universe-model-refactor-plan-v1.md)。

### 7.2 `planning.pagination_policy`

| 值 | 含义 | 使用数据集 |
| --- | --- | --- |
| `offset_limit` | 使用 `offset/limit` 分页 | 57 个数据集 |
| `none` | 不使用通用分页 | `biying_equity_daily`, `biying_moneyflow` |

### 7.3 `planning.enum_fanout_fields`

| 值 | 含义 | 使用数据集 |
| --- | --- | --- |
| `()` | 不按枚举字段自动扇出 | 49 个数据集 |
| `idx_type` | 按板块类型扇出 | `dc_daily`, `dc_index` |
| `market,hot_type,is_new` | 按东财热榜市场、榜单类型、最新标记组合扇出 | `dc_hot` |
| `tag` | 按开盘啦榜单标签扇出 | `kpl_list` |
| `limit_type,exchange` | 按涨跌停类型和交易所组合扇出 | `limit_list_d` |
| `limit_type,market` | 按同花顺涨跌停类型和市场组合扇出 | `limit_list_ths` |
| `src` | 按新闻来源扇出 | `major_news` |
| `exchange_id` | 按交易所扇出 | `margin` |
| `content_type` | 按板块类型扇出 | `moneyflow_ind_dc` |
| `market,is_new` | 按同花顺热榜市场和最新标记扇出 | `ths_hot` |

### 7.4 `planning.enum_fanout_defaults`

| 数据集 | 默认值 | 含义 |
| --- | --- | --- |
| `dc_hot` | `market=A股市场/ETF基金/港股市场/美股市场`; `hot_type=人气榜/飙升榜`; `is_new=Y` | 默认按东财热榜维度完整扇出 |
| `kpl_list` | `tag=涨停/炸板/跌停/自然涨停/竞价` | 默认按开盘啦标签扇出 |
| `limit_list_d` | `limit_type=U/D/Z`; `exchange=SH/SZ/BJ` | 默认按涨跌停类型和交易所扇出 |
| `limit_list_ths` | `limit_type=涨停池/连板池/冲刺涨停/炸板池/跌停池`; `market=HS/GEM/STAR` | 默认按同花顺涨跌停市场维度扇出 |
| `major_news` | `src=新华网/凤凰财经/同花顺/新浪财经/华尔街见闻/中证网/财新网/第一财经/财联社` | 默认按来源扇出 |
| `margin` | `exchange_id=SSE/SZSE/BSE` | 默认按交易所扇出 |
| `moneyflow_ind_dc` | `content_type=行业/概念/地域` | 默认按东财板块资金类型扇出 |
| `ths_hot` | `market=热股/ETF/可转债/行业板块/概念板块/期货/港股/热基/美股`; `is_new=Y` | 默认按同花顺热榜市场扇出 |
| 其他 51 个数据集 | `{}` | 无枚举默认扇出 |

### 7.5 `planning.unit_builder_key`

| 值 | 含义 | 使用数据集 |
| --- | --- | --- |
| `generic` | 通用 unit builder | 49 个数据集 |
| `build_index_daily_units` | 指数日线专用 builder | `index_daily` |
| `build_index_weight_units` | 指数权重专用 builder | `index_weight` |
| `build_stk_mins_units` | 分钟行情专用 builder | `stk_mins` |
| `build_stock_basic_units` | 股票基础信息多来源 builder | `stock_basic` |
| `build_dividend_units` | 分红送股专用 builder | `dividend` |
| `build_stk_holdernumber_units` | 股东户数专用 builder | `stk_holdernumber` |
| `build_cctv_news_units` | 新闻联播专用 builder | `cctv_news` |
| `build_major_news_units` | 新闻通讯专用 builder | `major_news` |
| `build_biying_equity_daily_units` | Biying 股票日线专用 builder | `biying_equity_daily` |
| `build_biying_moneyflow_units` | Biying 资金流专用 builder | `biying_moneyflow` |

---

## 8. 归一化枚举

### 8.1 `normalization.row_transform_name`

`row_transform_name` 是行转换函数 selector。`None` 表示不使用额外行转换。

| 值 | 使用数据集 |
| --- | --- |
| `None` | 31 个数据集 |
| `_biying_equity_daily_row_transform` | `biying_equity_daily` |
| `_biying_moneyflow_row_transform` | `biying_moneyflow` |
| `_cctv_news_row_transform` | `cctv_news` |
| `_daily_row_transform` | `daily` |
| `_dc_hot_row_transform` | `dc_hot` |
| `_dividend_row_transform` | `dividend` |
| `_fund_daily_row_transform` | `fund_daily` |
| `_hk_security_row_transform` | `hk_basic` |
| `_holdernumber_row_transform` | `stk_holdernumber` |
| `_index_daily_row_transform` | `index_daily`, `index_monthly`, `index_weekly` |
| `_kpl_concept_cons_row_transform` | `kpl_concept_cons` |
| `_limit_list_row_transform` | `limit_list_d` |
| `_limit_list_ths_row_transform` | `limit_list_ths` |
| `_major_news_row_transform` | `major_news` |
| `_moneyflow_row_transform` | `moneyflow` |
| `_stk_mins_row_transform` | `stk_mins` |
| `_stk_period_bar_adj_row_transform` | `stk_period_bar_adj_month`, `stk_period_bar_adj_week` |
| `_stk_period_bar_row_transform` | `stk_period_bar_month`, `stk_period_bar_week` |
| `_stock_basic_row_transform` | `stock_basic` |
| `_suspend_d_row_transform` | `suspend_d` |
| `_ths_hot_row_transform` | `ths_hot` |
| `_top_list_row_transform` | `top_list` |
| `_trade_cal_row_transform` | `trade_cal` |
| `_us_security_row_transform` | `us_basic` |

---

## 9. 能力枚举

### 9.1 `capabilities.action`

| 值 | 含义 | 使用数据集 |
| --- | --- | --- |
| `maintain` | 数据维护动作 | 当前全部 59 个数据集 |

### 9.2 `capabilities.supported_time_modes`

| 值 | 含义 | 使用数据集 |
| --- | --- | --- |
| `none` | 不需要选择时间 | `etf_basic`, `etf_index`, `hk_basic`, `index_basic`, `stock_basic`, `ths_index`, `ths_member`, `us_basic` |
| `range` | 只支持区间/窗口 | `dividend`, `index_weight`, `stk_holdernumber` |
| `point,range` | 支持单点与区间 | 47 个数据集 |
| `none,point,range` | 同时支持无时间、单点、区间 | `trade_cal` |

### 9.3 开关字段

| 字段 | 当前值 | 含义 |
| --- | --- | --- |
| `manual_enabled` | 全部为 `True` | 全部数据集允许手动维护 |
| `schedule_enabled` | 全部为 `True` | 全部数据集允许自动任务配置 |
| `retry_enabled` | 全部为 `True` | 全部数据集允许重试 |

---

## 10. 质量与事务枚举

### 10.1 `quality.reject_policy`

| 值 | 含义 | 使用数据集 |
| --- | --- | --- |
| `record_rejections` | 记录拒绝行，不静默吞掉质量问题 | 当前全部 59 个数据集 |

### 10.2 `transaction.commit_policy`

| 值 | 含义 | 使用数据集 |
| --- | --- | --- |
| `unit` | 每个 planned unit 独立提交业务数据事务 | 当前全部 59 个数据集 |

### 10.3 `transaction.idempotent_write_required`

| 值 | 含义 | 使用数据集 |
| --- | --- | --- |
| `True` | 写入路径必须满足幂等要求 | `cctv_news`, `dc_member`, `index_daily`, `index_weight`, `major_news`, `stk_factor_pro`, `stk_mins` |
| `False` | 当前 Definition 未显式要求幂等 | 52 个数据集 |

---

## 11. 维护检查清单

新增数据集或修改 DatasetDefinition 时，必须逐项确认：

1. `domain_key/cadence` 是否已有同义值，不能新造近义词。
2. `date_axis/bucket_rule/window_mode/input_shape` 是否与日期模型消费指南一致。
3. 所有业务枚举是否写入 `input_model.filters.enum_values`，不能让 Ops 或前端猜。
4. 自动扇出字段是否同时声明在 `enum_fanout_fields` 与 `enum_fanout_defaults`。
5. 对象池扇出是否明确表达在 `universe_policy=pool` 与 `planning.universe`，不能藏在 custom builder。
6. `request_builder_key/unit_builder_key/row_transform_name/write_path` 是否已有可复用值。
7. 如果新增 selector 字符串，必须同步实现注册表和测试。
8. 如果状态字段或 Ops 页面需要消费新字段，必须做全量消费者审计，旧口径清零。
