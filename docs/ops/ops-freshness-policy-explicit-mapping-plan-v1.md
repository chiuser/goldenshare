# Ops Freshness Policy 显式映射方案 v1

状态：已实施，已吸收 2026-05-16 评审意见
创建时间：2026-05-16
适用范围：`DatasetDefinition`、Ops freshness、dataset cards、overview、probe、前端数据源页与数据状态总览。

## 1. 背景

当前 freshness 的核心事实已经收敛到 `DatasetDefinition.date_model + 真实业务表观测 + TaskRun`，但仍存在一个语义问题：

`date_model` 能说明一个数据集如何接收时间输入、如何展开执行 unit、从哪个字段观察日期；它不能单独说明这个数据集是否应该按连续日期判断新鲜度。

典型问题：

1. `dividend` 分红送股有 `ann_date`，但不是每天都有公司分红。
2. `stk_holdernumber` 股东户数有 `ann_date/end_date`，源文档明确写明“数据不定期公布”。
3. 新闻、公告、研报等数据有发布时间或公告日期，但不保证每天都有事件。
4. 主数据、快照数据没有连续业务日期概念，不应展示为“未知”来误导运营。

因此，freshness 需要从“按 `date_model.bucket_rule` 推断”升级为“由 `DatasetDefinition` 显式声明 freshness policy，再由 Ops 查询层执行固定策略”。

## 2. 目标

1. 在 `src/foundation/datasets` 下集中定义每个数据集的 freshness policy，`DatasetDefinition` 只引用该集中定义，不在各定义文件里分散维护。
2. Ops freshness 不再仅凭 `date_model.bucket_rule` 推断健康度。
3. 事件型与快照型数据不再因为不适合连续日期判断而显示“未知”。
4. 页面文案不再使用模糊替代表述，只使用明确字段：
   - 最近维护成功时间
   - 最近刷新成功时间
   - 最新事件日期
   - 最新业务日期
5. 新增 `unconfirmed` 状态表达“需要运营确认是否已维护过”，不再用 `unknown` 承担事件型/快照型数据的正常待确认状态。
6. `unknown` 只保留给真正的技术异常或事实缺失，例如定义缺失、观测失败且无可用缓存。

## 3. 非目标

1. 不新增业务数据表。
2. 不触碰、清空、重建任何 `raw_*`、`core_*`、`core_serving*` 业务表。
3. 不改变数据维护执行链路和源接口请求参数生成位置。
4. 不把 freshness policy 放到前端或 Ops 临时映射表里。
5. 不恢复旧分层观测链路。

## 4. 当前代码核验结果

### 4.1 当前 freshness 事实来源

已核验代码：

1. `src/foundation/datasets/models.py`
   - `DatasetDateModel` 当前包含 `date_axis/bucket_rule/window_mode/input_shape/observed_field/audit_applicable/not_applicable_reason`。
   - `DatasetObservability` 当前包含 `progress_label/observed_field/audit_applicable/freshness_policy`。
2. `src/ops/dataset_definition_projection.py`
   - `build_dataset_freshness_projection()` 从 `DatasetDefinition` 投影出 `target_table/raw_table/observed_date_column/freshness_policy`。
3. `src/ops/queries/freshness_query_service.py`
   - `_expected_business_date_for_projection()` 当前按 `date_model.date_axis + bucket_rule` 推导应完成日期。
   - `_freshness_status_for_date_model()` 当前按 `date_model.bucket_rule` 推导 `fresh/lagging/stale/unknown`。
4. `src/ops/services/operations_dataset_status_snapshot_service.py`
   - `dataset_status_snapshot` 只是 freshness 缓存，真实业务表观测由 `build_live_items()` 生产。
5. `src/ops/queries/dataset_card_query_service.py`
   - 数据源卡片消费 freshness item，并把 status 聚合到卡片。
6. `src/ops/queries/overview_query_service.py`
   - 今日运行和数据状态总览消费同一套 freshness summary 与关注列表。

### 4.2 当前误判点

已核验代码与源文档：

1. `dividend`
   - 当前定义：`natural_day/every_natural_day/ann_date/audit_applicable=True`
   - 代码位置：`src/foundation/datasets/definitions/low_frequency.py`
   - 源文档：`docs/sources/tushare/股票数据/财务数据/0103_分红送股.md`
   - 事实：这是公司分红事件，不保证每个自然日都有数据。
2. `stk_holdernumber`
   - 当前定义：`natural_day/every_natural_day/ann_date/audit_applicable=True`
   - 代码位置：`src/foundation/datasets/definitions/low_frequency.py`
   - 源文档：`docs/sources/tushare/股票数据/参考数据/0166_股东人数.md`
   - 源文档明确写明：获取上市公司股东户数数据，数据不定期公布。
3. 现有 `bucket_rule=not_applicable` 且带 `observed_field` 的事件/资讯类数据，当前 freshness 状态通常落为 `unknown`，页面容易误解为系统无法同步。
4. `block_trade` 当前定义为连续交易日 freshness，但大宗交易并不一定每天发生，更适合事件型判断。

## 5. Policy 定义

### 5.1 `continuous_open_day`

适用：交易日连续数据。

判断：

1. 用交易日历计算最新应完成交易日。
2. 用目标表观测字段计算最新业务日期。
3. 最新业务日期达到应完成交易日：正常。
4. 未达到时按固定阈值区分滞后和严重滞后。

页面主文案：

1. 最新业务日期
2. 最近维护成功时间
3. 滞后天数

### 5.2 `continuous_natural_day`

适用：自然日连续数据。

判断：

1. 用北京时间自然日计算应完成日期。
2. 用目标表观测字段计算最新自然日。
3. 最新自然日达到应完成日期：正常。
4. 未达到时按固定阈值区分滞后和严重滞后。

页面主文案：

1. 最新自然日
2. 最近维护成功时间
3. 滞后天数

### 5.3 `period_bucket`

适用：周线、月线、月份键、月窗口数据。

判断：

1. 仍由 `date_model.date_axis + bucket_rule` 计算当前应完成周期桶。
2. 目标表只观测同类周期桶。
3. 达到应完成周期桶：正常。
4. 未达到时按周期桶阈值区分滞后和严重滞后。

页面主文案：

1. 最新周期
2. 应完成周期
3. 最近维护成功时间

### 5.4 `event_run_trace`

适用：有事件日期，但事件不要求连续发生的数据。

典型例子：

1. 分红送股
2. 股东户数
3. 上市公司公告
4. 新闻快讯
5. 新闻通讯
6. 研报
7. 互动问答

判断：

1. 不计算 `expected_business_date`。
2. 不计算 `lag_days`。
3. 不按 `max(事件日期)` 与今天比较。
4. 有最近维护成功时间，且没有更新的失败：显示正常。
5. 没有最近维护成功时间，但目标表有事件日期：显示 `unconfirmed`，页面文案为“未确认”，需要运营检查维护记录。
6. 有更新的失败：进入关注列表，展示失败摘要。

页面主文案：

1. 最近维护成功时间
2. 最新事件日期
3. 最近失败时间与失败摘要

禁止文案：

1. 模糊的最近刷新类表述
2. 最新事件日期滞后几天

### 5.5 `snapshot_run_trace`

适用：快照、主数据、基础信息。

判断：

1. 不计算 `expected_business_date`。
2. 不计算 `lag_days`。
3. 不展示最新业务日期。
4. 有最近刷新成功时间，且没有更新的失败：显示正常。
5. 没有最近刷新成功时间：显示 `unconfirmed`，页面文案为“未确认”。
6. 有更新的失败：进入关注列表，展示失败摘要。

页面主文案：

1. 最近刷新成功时间
2. 最近失败时间与失败摘要

禁止文案：

1. 模糊的最近刷新类表述
2. 最新业务日期
3. 滞后天数

## 6. 逐数据集 policy 建议表

说明：

1. “当前 date_model 摘要”来自当前 `DatasetDefinition` 实际导出结果。
2. “拟定 policy”是本方案建议，待 review 后再进入实现。
3. `dividend`、`stk_holdernumber` 当前 date_model 与业务语义不一致，本方案建议同时修正 date_model 和 freshness policy。

| dataset_key | 名称 | 当前领域 | 当前 date_model 摘要 | 拟定 policy | 判断依据 / 备注 |
| --- | --- | --- | --- | --- | --- |
| dc_daily | 东方财富板块日线行情 | 板块 / 题材 | trade_open_day/every_open_day/trade_date | continuous_open_day | 连续交易日数据，按最新应完成交易日判断。 |
| dc_hot | 东方财富热榜 | 板块 / 题材 | trade_open_day/every_open_day/trade_date | continuous_open_day | 连续交易日榜单，按最新应完成交易日判断。 |
| dc_index | 东方财富板块列表 | 板块 / 题材 | trade_open_day/every_open_day/trade_date | continuous_open_day | 当前定义为按交易日维护的板块列表。 |
| dc_member | 东方财富板块成分 | 板块 / 题材 | trade_open_day/every_open_day/trade_date | continuous_open_day | 当前定义为按交易日维护的板块成分。 |
| kpl_concept_cons | 开盘啦板块成分 | 板块 / 题材 | trade_open_day/every_open_day/trade_date | continuous_open_day | 当前定义为按交易日维护的板块成分。 |
| kpl_list | 开盘啦榜单 | 板块 / 题材 | trade_open_day/every_open_day/trade_date | continuous_open_day | 连续交易日榜单，按最新应完成交易日判断。 |
| ths_daily | 同花顺板块日线行情 | 板块 / 题材 | trade_open_day/every_open_day/trade_date | continuous_open_day | 连续交易日行情，按最新应完成交易日判断。 |
| ths_hot | 同花顺热榜 | 板块 / 题材 | trade_open_day/every_open_day/trade_date | continuous_open_day | 连续交易日榜单，按最新应完成交易日判断。 |
| ths_index | 同花顺板块列表 | 板块 / 题材 | none/not_applicable/- | snapshot_run_trace | 快照型板块列表，不按业务日期连续性判断。 |
| ths_member | 同花顺板块成分 | 板块 / 题材 | none/not_applicable/- | snapshot_run_trace | 快照型板块成分，不按业务日期连续性判断。 |
| adj_factor | 复权因子 | 股票行情 | trade_open_day/every_open_day/trade_date | continuous_open_day | 连续交易日数据，按最新应完成交易日判断。 |
| biying_equity_daily | BIYING 股票日线 | 股票行情 | trade_open_day/every_open_day/trade_date | continuous_open_day | 连续交易日行情，按最新应完成交易日判断。 |
| block_trade | 大宗交易 | 股票行情 | trade_open_day/every_open_day/trade_date | event_run_trace | 大宗交易有交易日期，但并不一定每天发生，不应按连续交易日判断滞后。 |
| broker_recommend | 券商月度金股推荐 | 股票行情 | month_key/every_natural_month/month | period_bucket | 月份键数据，按自然月周期桶判断。 |
| cyq_perf | 每日筹码及胜率 | 股票行情 | trade_open_day/every_open_day/trade_date | continuous_open_day | 连续交易日数据，按最新应完成交易日判断。 |
| daily | 股票日线 | 股票行情 | trade_open_day/every_open_day/trade_date | continuous_open_day | 连续交易日行情，按最新应完成交易日判断。 |
| daily_basic | 每日指标 | 股票行情 | trade_open_day/every_open_day/trade_date | continuous_open_day | 连续交易日指标，按最新应完成交易日判断。 |
| limit_cpt_list | 涨停概念列表 | 股票行情 | trade_open_day/every_open_day/trade_date | continuous_open_day | 当前定义为按交易日维护。 |
| limit_list_d | 每日涨跌停名单 | 股票行情 | trade_open_day/every_open_day/trade_date | continuous_open_day | 连续交易日名单，按最新应完成交易日判断。 |
| limit_list_ths | 同花顺涨停名单 | 股票行情 | trade_open_day/every_open_day/trade_date | continuous_open_day | 连续交易日名单，按最新应完成交易日判断。 |
| limit_step | 连板梯队 | 股票行情 | trade_open_day/every_open_day/trade_date | continuous_open_day | 连续交易日数据，按最新应完成交易日判断。 |
| margin | 融资融券汇总 | 股票行情 | trade_open_day/every_open_day/trade_date | continuous_open_day | 连续交易日数据，按最新应完成交易日判断。 |
| research_report | 券商研究报告 | 股票行情 | natural_day/not_applicable/trade_date | event_run_trace | 研报是事件型发布，不要求连续自然日每天有数据。 |
| stk_factor_pro | 股票技术面因子(专业版) | 股票行情 | trade_open_day/every_open_day/trade_date | continuous_open_day | 连续交易日数据，按最新应完成交易日判断。 |
| stk_limit | 每日涨跌停价格 | 股票行情 | trade_open_day/every_open_day/trade_date | continuous_open_day | 连续交易日价格，按最新应完成交易日判断。 |
| stk_mins | 股票历史分钟行情 | 股票行情 | trade_open_day/every_open_day/trade_time | continuous_open_day | 按最新交易日判断数据是否追到应完成日期；分钟完整性审计仍不在本 policy 解决。 |
| stk_nineturn | 神奇九转指标 | 股票行情 | trade_open_day/every_open_day/trade_date | continuous_open_day | 连续交易日指标，按最新应完成交易日判断。 |
| stk_period_bar_adj_month | 股票月线行情（复权） | 股票行情 | natural_day/month_last_calendar_day/trade_date | period_bucket | 股票复权月线，按自然月最后一天周期桶判断。 |
| stk_period_bar_adj_week | 股票周线行情（复权） | 股票行情 | natural_day/week_friday/trade_date | period_bucket | 股票复权周线，按自然周五周期桶判断。 |
| stk_period_bar_month | 股票月线行情 | 股票行情 | natural_day/month_last_calendar_day/trade_date | period_bucket | 股票月线，按自然月最后一天周期桶判断。 |
| stk_period_bar_week | 股票周线行情 | 股票行情 | natural_day/week_friday/trade_date | period_bucket | 股票周线，按自然周五周期桶判断。 |
| stock_st | ST股票列表 | 股票行情 | trade_open_day/every_open_day/trade_date | continuous_open_day | 当前定义为按交易日维护的 ST 列表。 |
| suspend_d | 每日停复牌信息 | 股票行情 | trade_open_day/every_open_day/trade_date | continuous_open_day | 连续交易日停复牌信息，按最新应完成交易日判断。 |
| top_list | 龙虎榜 | 股票行情 | trade_open_day/every_open_day/trade_date | continuous_open_day | 交易日事件集合，但源数据按交易日维护，仍按交易日完整性判断。 |
| etf_index | ETF 跟踪指数 | 指数 / ETF | none/not_applicable/- | snapshot_run_trace | ETF 跟踪指数主数据，不按业务日期连续性判断。 |
| fund_adj | 基金复权因子 | 指数 / ETF | trade_open_day/every_open_day/trade_date | continuous_open_day | 连续交易日数据，按最新应完成交易日判断。 |
| fund_daily | 基金日线行情 | 指数 / ETF | trade_open_day/every_open_day/trade_date | continuous_open_day | 连续交易日行情，按最新应完成交易日判断。 |
| index_basic | 指数基础信息 | 指数 / ETF | none/not_applicable/- | snapshot_run_trace | 指数基础主数据，不按业务日期连续性判断。 |
| index_daily | 指数日线行情 | 指数 / ETF | trade_open_day/every_open_day/trade_date | continuous_open_day | 连续交易日行情，按最新应完成交易日判断。 |
| index_daily_basic | 指数每日指标 | 指数 / ETF | trade_open_day/every_open_day/trade_date | continuous_open_day | 连续交易日指标，按最新应完成交易日判断。 |
| index_mins | 指数历史分钟行情 | 指数 / ETF | trade_open_day/every_open_day/trade_time | continuous_open_day | 按最新交易日判断数据是否追到应完成日期；分钟完整性审计仍不在本 policy 解决。 |
| index_monthly | 指数月线 | 指数 / ETF | trade_open_day/month_last_open_day/trade_date | period_bucket | 指数月线，按每月最后一个交易日周期桶判断。 |
| index_weekly | 指数周线 | 指数 / ETF | trade_open_day/week_last_open_day/trade_date | period_bucket | 指数周线，按每周最后一个交易日周期桶判断。 |
| index_weight | 指数成分权重 | 指数 / ETF | month_window/month_window_has_data/trade_date | period_bucket | 月窗口数据，按有数据的月窗口判断。 |
| dividend | 分红送股 | 低频数据 | natural_day/every_natural_day/ann_date | event_run_trace | 事件型低频披露，不保证连续自然日有数据；建议同步改为 `bucket_rule=not_applicable`、`audit_applicable=False`。 |
| stk_holdernumber | 股东户数 | 低频数据 | natural_day/every_natural_day/ann_date | event_run_trace | 源文档明确“不定期公布”；建议同步改为 `bucket_rule=not_applicable`、`audit_applicable=False`。 |
| biying_moneyflow | BIYING 资金流向 | 资金流向 | trade_open_day/every_open_day/trade_date | continuous_open_day | 连续交易日资金流，按最新应完成交易日判断。 |
| moneyflow | 个股资金流向 | 资金流向 | trade_open_day/every_open_day/trade_date | continuous_open_day | 连续交易日资金流，按最新应完成交易日判断。 |
| moneyflow_cnt_ths | 概念板块资金流向(THS) | 资金流向 | trade_open_day/every_open_day/trade_date | continuous_open_day | 连续交易日资金流，按最新应完成交易日判断。 |
| moneyflow_dc | 个股资金流向(DC) | 资金流向 | trade_open_day/every_open_day/trade_date | continuous_open_day | 连续交易日资金流，按最新应完成交易日判断。 |
| moneyflow_ind_dc | 板块资金流向(DC) | 资金流向 | trade_open_day/every_open_day/trade_date | continuous_open_day | 连续交易日资金流，按最新应完成交易日判断。 |
| moneyflow_ind_ths | 行业资金流向(THS) | 资金流向 | trade_open_day/every_open_day/trade_date | continuous_open_day | 连续交易日资金流，按最新应完成交易日判断。 |
| moneyflow_mkt_dc | 市场资金流向(DC) | 资金流向 | trade_open_day/every_open_day/trade_date | continuous_open_day | 连续交易日资金流，按最新应完成交易日判断。 |
| moneyflow_ths | 个股资金流向(THS) | 资金流向 | trade_open_day/every_open_day/trade_date | continuous_open_day | 连续交易日资金流，按最新应完成交易日判断。 |
| anns_d | 上市公司公告 | 新闻资讯 | natural_day/not_applicable/ann_date | event_run_trace | 公告是事件型数据，不要求连续自然日每天有数据。 |
| cctv_news | 新闻联播文字稿 | 新闻资讯 | natural_day/every_natural_day/date | continuous_natural_day | 新闻联播文字稿按自然日连续维护。 |
| irm_qa_sh | 上证E互动问答 | 新闻资讯 | natural_day/not_applicable/pub_time | event_run_trace | 互动问答是事件型发布，不要求连续自然日每天有数据。 |
| irm_qa_sz | 深证互动易问答 | 新闻资讯 | natural_day/not_applicable/pub_time | event_run_trace | 互动问答是事件型发布，不要求连续自然日每天有数据。 |
| major_news | 新闻通讯 | 新闻资讯 | natural_day/not_applicable/pub_time | event_run_trace | 新闻通讯是事件型资讯，不保证每个来源每天都有新闻。 |
| news | 新闻快讯 | 新闻资讯 | natural_day/not_applicable/news_time | event_run_trace | 新闻快讯是事件型资讯，不保证每个来源每天都有新闻。 |
| bak_basic | 股票历史基础列表 | 基础主数据 | trade_open_day/every_open_day/trade_date | continuous_open_day | 当前定义为按交易日维护的历史基础列表。 |
| bse_mapping | 北交所新旧代码对照 | 基础主数据 | none/not_applicable/- | snapshot_run_trace | 快照型主数据，不按业务日期连续性判断。 |
| etf_basic | ETF 基础信息 | 基础主数据 | none/not_applicable/- | snapshot_run_trace | 快照型主数据，不按业务日期连续性判断。 |
| hk_basic | 港股基础信息 | 基础主数据 | none/not_applicable/- | snapshot_run_trace | 快照型主数据，不按业务日期连续性判断。 |
| namechange | 股票曾用名 | 基础主数据 | none/not_applicable/- | snapshot_run_trace | 当前定义为默认全集分页刷新，不按公告日或自然日扇出。 |
| st | ST 风险警示事件 | 基础主数据 | none/not_applicable/- | snapshot_run_trace | 当前定义为默认全集分页刷新，不按发布日期或实施日期扇出。 |
| stock_basic | 股票主数据 | 基础主数据 | none/not_applicable/- | snapshot_run_trace | 快照型主数据，不按业务日期连续性判断。 |
| stock_company | 上市公司基本信息 | 基础主数据 | none/not_applicable/- | snapshot_run_trace | 快照型主数据，不按业务日期连续性判断。 |
| trade_cal | 交易日历 | 基础主数据 | natural_day/every_natural_day/trade_date | continuous_natural_day | 交易日历本身按自然日连续覆盖。 |
| us_basic | 美股基础信息 | 基础主数据 | none/not_applicable/- | snapshot_run_trace | 快照型主数据，不按业务日期连续性判断。 |

## 7. 改动点重新核验

### 7.1 Definition 层

目标文件：

1. `src/foundation/datasets/models.py`
2. `src/foundation/datasets/freshness_policies.py`，新增
3. `src/foundation/datasets/definitions/_builder.py`
4. `src/foundation/datasets/definitions/**`

改动：

1. 新增集中 policy 映射文件，逐个列出 70 个数据集的 policy。
2. `DatasetObservability` 增加只读 `freshness_policy` 字段，由 builder 根据集中映射填入。
3. 各数据集定义文件不分散填写 policy，避免同一事实在多个文件里重复维护。
4. 所有 70 个数据集必须在集中映射文件中显式登记，不允许默认推断。
5. `dividend`、`stk_holdernumber` 同步修正 `date_model`：
   - `bucket_rule=not_applicable`
   - `audit_applicable=False`
   - `not_applicable_reason` 写明事件型低频披露，不保证连续自然日有数据
6. 不修改维护执行链路，不修改 request builder 的源接口参数生成规则。

集中映射文件建议形态：

```python
FRESHNESS_POLICY_BY_DATASET = {
    "daily": "continuous_open_day",
    "block_trade": "event_run_trace",
    "dividend": "event_run_trace",
    "stock_basic": "snapshot_run_trace",
}
```

约束：

1. 缺少映射的数据集必须让 registry 测试失败。
2. 映射文件属于 `foundation/datasets`，不得依赖 Ops。
3. Ops 使用时只能通过 `DatasetDefinition.observability.freshness_policy` 读取，不能另建一份 Ops 侧 policy map。

### 7.2 Projection 与查询层

目标文件：

1. `src/ops/dataset_definition_projection.py`
2. `src/ops/queries/freshness_query_service.py`

改动：

1. `DatasetFreshnessProjection` 增加 `freshness_policy`。
2. `OpsFreshnessQueryService` 增加固定 policy evaluator。
3. `expected_business_date / lag_days` 只允许连续型与周期型 policy 生成。
4. `event_run_trace / snapshot_run_trace` 不生成滞后天数。
5. `event_run_trace / snapshot_run_trace` 缺少成功任务记录时返回 `unconfirmed`，不返回 `unknown`。
6. `unknown` 只在技术异常或事实源缺失时出现。
7. freshness note 禁止出现模糊的最近刷新类表述。

### 7.3 Snapshot 缓存

目标文件：

1. `src/ops/services/operations_dataset_status_snapshot_service.py`
2. `src/ops/models/ops/dataset_status_snapshot.py`
3. `src/ops/dataset_status_projection.py`

初步判断：

1. 不需要新增表。
2. `freshness_policy` 是 Definition 静态事实，只从 `DatasetDefinition` 当前映射读取，不作为新的缓存事实落库。
3. API 返回 policy 时，由 query/projection 每次读取 Definition 后附加；不得保存到 `ops.dataset_status_snapshot`。
4. `ops.dataset_status_snapshot` 仍只保存观测结果、最近成功/失败、状态缓存等运行结果，不保存 policy 副本。
5. 若决定把 `latest_business_date` 改名为 `latest_observed_date`，则需要单独评估是否重命名 snapshot 内部字段。本方案建议优先改 API/页面语义，避免为了命名做不必要的数据迁移。

人话流程：

```text
页面请求 freshness / dataset cards
  -> 后端读取 ops.dataset_status_snapshot 里的运行结果
     例如：这个数据集目标表最新观测日期、最近成功时间、最近失败摘要
  -> 后端拿 snapshot.resource_key 回到 DatasetDefinition registry
  -> 由 DatasetDefinition 生成当前 DatasetFreshnessProjection
     projection 里带上当前 freshness_policy
  -> freshness evaluator 用“snapshot 运行结果 + 当前 projection policy”重新解释状态
  -> 返回给 API 和页面
```

这样设计的原因：

1. `freshness_policy` 是定义事实，不是运行结果。
2. snapshot 是缓存，只适合保存“上次观测到了什么”，不适合保存“这个数据集应该按什么规则解释”。
3. 如果 policy 后续调整，只要改集中映射和 Definition，页面下一次请求就用新 policy 解释现有观测结果。
4. 如果把 policy 也写进 snapshot，就会出现 Definition 里是新规则、snapshot 里还是旧规则的双事实源问题。

### 7.4 API Schema

目标文件：

1. `src/ops/schemas/freshness.py`
2. `src/ops/schemas/dataset_card.py`
3. `src/ops/schemas/overview.py`

改动：

1. freshness item 增加 `freshness_policy`。
2. dataset card 增加 `freshness_policy`。
3. freshness summary 增加 `unconfirmed_datasets`，避免把未确认和未知混在一起。
4. 面向前端增加语义明确的展示字段，建议：
   - `latest_observed_date`
   - `latest_observed_date_label`
   - `expected_observed_date`
   - `expected_observed_date_label`
   - `last_success_label`
5. 页面不得再自行把 `latest_business_date` 统一叫“最新业务日”。

### 7.5 页面消费

目标文件：

1. `frontend/src/pages/ops-v21-source-page.tsx`
2. `frontend/src/pages/ops-v21-overview-page.tsx`
3. `frontend/src/pages/ops-today-page.tsx`
4. `frontend/src/pages/ops-v21-dataset-detail-page.tsx`
5. `frontend/src/shared/ops-display.ts`
6. `frontend/src/shared/api/types.ts`

改动：

1. 连续型数据展示“最新业务日期/最新自然日 + 滞后天数”。
2. 周期型数据展示“最新周期/应完成周期”。
3. 事件型数据展示“最近维护成功时间 + 最新事件日期”。
4. 快照型数据展示“最近刷新成功时间”。
5. 页面不得把事件型和快照型数据显示成“未知”或“滞后几天”。
6. 事件型和快照型没有最近成功记录时，页面显示“未确认”。

### 7.6 Probe 与自动任务

目标文件：

1. `src/ops/services/schedule_probe_binding_service.py`
2. `src/ops/services/operations_probe_runtime_service.py`
3. `frontend/src/pages/ops-v21-task-auto-tab.tsx`

当前事实：

1. 探测条件当前只有 `freshness_latest_open`。
2. 这个条件语义是“最新业务日命中最新交易日”，只适合 `continuous_open_day`。

改动：

1. `freshness_latest_open` 只允许绑定 `continuous_open_day` 数据集。
2. 本轮不为事件型和快照型新增探测条件，避免扩大范围。
3. 如果后续需要事件型探测，应另立 `last_success_after_trigger` 或类似明确条件，但不在本方案第一期实现。

### 7.7 Date Completeness Audit

目标文件：

1. `src/ops/queries/date_completeness_query_service.py`
2. `src/ops/services/date_completeness_*`
3. `frontend/src/pages/ops-v21-dataset-audit-page.tsx`

改动：

1. date completeness audit 继续只认 `date_model.audit_applicable` 与 `bucket_rule`。
2. `freshness_policy` 不参与完整性审计。
3. `dividend`、`stk_holdernumber` 改成事件型后，应退出连续自然日完整性审计。

## 8. 需要你 review 的决策点

### D1：事件型/快照型状态显示

结论：新增 `unconfirmed` 状态，不用 `unknown` 表达这类待确认状态。

1. 有最近成功时间，且没有更新的失败：显示“正常”。
2. 没有最近成功时间，但目标表有数据：状态为 `unconfirmed`，页面显示“未确认”。
3. 有更新的失败：进入关注列表，展示失败摘要。

### D2：`dividend`、`stk_holdernumber` 是否同步退出日期完整性审计

结论：退出。

理由：

1. 它们支持日期范围维护，不代表要求连续自然日每天都有数据。
2. 源文档与业务语义都不支持“每天必须有数据”的判断。

### D3：API 是否新增语义展示字段

结论：新增。

理由：

1. 如果只返回 `latest_business_date`，前端仍然容易把事件日期叫成业务日期。
2. 新增服务端生成的 label 可以避免页面自行拼装事实字段。

### D4：是否在本轮处理 cadence 退场

结论：处理，最终彻底清理干净。

人话解释：

退场前，`cadence` 是 `DatasetDefinition.domain.cadence` 里的“更新节奏标签”，例如 `daily`、`monthly`、`intraday`、`snapshot`、`low_frequency`。它当时还会出现在 dataset card、freshness item、snapshot 表和前端“更新频率”展示里。

“cadence 退场”的意思是：删除这个抽象节奏标签，不再让页面或 freshness 判断依赖它。真正的判断由 `date_model` 和本方案新增的 `freshness_policy` 承担。

执行要求：

1. 本轮把 cadence 退场纳入同一主线实施，不再作为后续 P1 悬挂事项。
2. 删除用户可见的“更新频率”展示。
3. 删除 freshness / dataset card / overview API 中的 cadence 字段。
4. 删除 `ops.dataset_status_snapshot.cadence` 列。
5. 删除 `DatasetDomain.cadence` 与 `cadence_display_name`。
6. 所有原本依赖 cadence 的判断改为依赖 `date_model` 或 `freshness_policy`。
7. 清理后，代码中不应再有业务逻辑依赖 `cadence`。

## 9. 实施里程碑

执行结果（2026-05-16）：

1. M1~M5 已完成，`DatasetDefinition`、Ops API、snapshot cache、dataset cards、overview、probe 与前端页面已切到 `freshness_policy`。
2. `cadence` 已从当前生产代码、前端类型和测试 fixture 中清理；`ops.dataset_status_snapshot.cadence` 通过迁移 `20260516_000108` 退场。
3. `dividend`、`stk_holdernumber` 已退出连续日期完整性审计；`block_trade` 已改为事件型 freshness。
4. `freshness_latest_open` 探测条件已限制为 `continuous_open_day` 数据集。
5. 文档中后续如需引用本方案，应按“当前事实”而不是“待评审方案”理解。

### M1：模型与定义

1. `DatasetObservability` 增加必填 `freshness_policy`。
2. 新增集中 policy 映射文件，70 个 DatasetDefinition 全量登记。
3. builder 从集中映射读取并写入 `DatasetDefinition.observability.freshness_policy`。
4. 删除 `DatasetDomain.cadence` 与 `cadence_display_name`。
5. 全量移除 DatasetDefinition 定义里的 `domain.cadence`。
6. 修正 `dividend`、`stk_holdernumber` date_model。
7. 补 registry 测试，确保无数据集缺 policy，且无新增 cadence 依赖。

### M2：Freshness evaluator

1. `DatasetFreshnessProjection` 透出 policy。
2. `OpsFreshnessQueryService` 改为 policy evaluator。
3. 删除 `bucket_rule` 直接推断 freshness status 的主路径。
4. 保留 `date_model` 只用于连续型与周期型 policy 的 expected date 计算。
5. `unconfirmed` 加入状态排序、汇总和关注列表规则。

### M3：API 与页面展示

1. freshness / dataset card API 返回 policy 与服务端展示字段。
2. 数据源页、今日运行、数据状态总览、数据集详情页改为按 policy 展示。
3. 页面删除模糊的最近刷新类文案。
4. 页面删除“更新频率”展示。
5. 前端类型移除 cadence / cadence_display_name。

### M4：Snapshot 与 cadence 字段退场

1. `DatasetFreshnessItem` 删除 `cadence`。
2. `DatasetCardItem` 删除 `cadence` / `cadence_display_name`。
3. `ops.dataset_status_snapshot` 删除 `cadence` 列。
4. 新增 Alembic 迁移前先检查当前真实 head。
5. snapshot rebuild 后不再写 cadence。

### M5：Probe 守卫

1. `freshness_latest_open` 只允许 `continuous_open_day`。
2. 自动任务页面说明同步调整。
3. 非连续型数据集不得创建该探测规则。

### M6：Snapshot 重建与回归

1. 本地测试通过后，运行 snapshot rebuild。
2. 验证事件型、快照型不再大面积显示“未知”。
3. 验证连续型、周期型滞后判断不变。
4. 验证 API、前端、测试和文档中无现行业务 cadence 依赖。

## 10. 验证清单

验证时至少执行：

1. `pytest -q tests/test_dataset_definition_registry.py`
2. `pytest -q tests/web/test_ops_freshness_api.py`
3. `pytest -q tests/test_ops_freshness_snapshot_query_service.py`
4. `pytest -q tests/test_dataset_status_snapshot_service.py`
5. `pytest -q tests/web/test_ops_dataset_cards_api.py`
6. `pytest -q tests/web/test_ops_overview_api.py`
7. `pytest -q tests/web/test_ops_date_completeness_api.py`
8. `pytest -q tests/web/test_ops_schedule_api.py`
9. `cd frontend && npm run typecheck`
10. `cd frontend && npm run test:smoke`
11. `python3 scripts/check_docs_integrity.py`
12. `rg "\\bcadence\\b" src frontend tests docs`

`rg "\\bcadence\\b"` 允许命中：

1. 历史归档文档。
2. 本方案或 cadence 退场记录中对已删除字段的说明。

不允许命中：

1. 当前生产代码。
2. 当前 API schema。
3. 当前前端展示。
4. 当前测试 fixture 作为有效字段。

## 11. 本方案对现有架构的影响

1. 不改变 `foundation -> ops` 依赖方向；policy 定义仍在 `DatasetDefinition`，执行在 Ops。
2. 不新增第二套数据集事实源。
3. 不改变业务数据事务。
4. 不影响 ingestion request builder 的职责边界。
5. 会影响 freshness API、dataset cards API、overview、probe 和前端展示，必须一次性做消费者审计。
