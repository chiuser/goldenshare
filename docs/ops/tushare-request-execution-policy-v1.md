# Tushare 全量数据集请求执行口径 v1（仅 Tushare）

- 编制日期：2026-04-22
- 口径范围：`Tushare` 已接入 54 个数据集（不含 Biying）
- 依据：`docs/sources/tushare/docs_index.csv` 对应接口文档输入参数、限量说明
- 目标：按“默认不扇出、只透传用户显式参数、分页闭环”统一请求行为。

## 1. 统一执行原则

1. 默认请求只带主时间参数（或快照无时间），不主动带可选过滤维度。
2. 用户显式传了哪些参数，就只透传哪些参数；未传的参数不补默认枚举。
3. 对“支持多值输入”的参数：单字段多值 => 枚举扇出请求；多字段都多值 => 做笛卡尔组合后逐组合请求。
4. 对“多值参数全选”的情况，按“全选折叠”为不传该字段处理；避免无意义笛卡尔扩散。
5. 分页统一闭环：`offset += limit`，直到“返回条数 `< limit`”停止。
6. 若文档给出单次上限，`limit` 用文档上限；若文档未给明确数值，由资源级策略显式指定默认 `limit`（在对应数据集条目中写清）。
7. `trade_date` 统一指交易日；周/月线使用周末/月末交易日锚点。
8. 暂不讨论 Biying 数据集。

## 2. 逐数据集执行规则（54）

### `adj_factor`（复权因子）

- 接口：`adj_factor`
- 源文档：`docs/sources/tushare/股票数据/行情数据/0028_复权因子.md`
- 分页：文档未写明单次上限数值；按工程统一上限 `limit=6000`，`offset` 递增分页。
- 默认请求：默认按 `start_date/end_date` 过滤交易日，逐 `trade_date` 请求；若只给 `trade_date` 则按单日请求。
- 用户传参规则：用户若显式传 `ts_code`，就原样透传；可组合；未传不补。
- 时间执行：以交易日为基准；区间任务先筛交易日，再逐日请求。

### `block_trade`（大宗交易）

- 接口：`block_trade`
- 源文档：`docs/sources/tushare/股票数据/参考数据/0161_大宗交易.md`
- 分页：`limit=1000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认按 `start_date/end_date` 过滤交易日，逐 `trade_date` 请求；若只给 `trade_date` 则按单日请求。
- 用户传参规则：用户若显式传 `ts_code`，就原样透传；可组合；未传不补。
- 时间执行：以交易日为基准；区间任务先筛交易日，再逐日请求。

### `broker_recommend`（券商每月荐股）

- 接口：`broker_recommend`
- 源文档：`docs/sources/tushare/股票数据/特色数据/0267_券商每月荐股.md`
- 分页：`limit=1000`（文档单次上限），`offset` 递增分页。
- 默认请求：按 `month=YYYYMM` 执行，不使用 `trade_date`。
- 用户传参规则：除时间参数与分页参数外，无额外可选维度；按默认策略执行。
- 时间执行：按 `month` 键逐月执行。

### `cyq_perf`（每日筹码及胜率）

- 接口：`cyq_perf`
- 源文档：`docs/sources/tushare/股票数据/特色数据/0293_每日筹码及胜率.md`
- 分页：`limit=5000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认按 `start_date/end_date` 过滤交易日，逐 `trade_date` 请求；若只给 `trade_date` 则按单日请求。
- 用户传参规则：用户若显式传 `ts_code`，就原样透传；可组合；未传不补。
- 时间执行：以交易日为基准；区间任务先筛交易日，再逐日请求。

### `daily`（股票日线）

- 接口：`daily`
- 源文档：`docs/sources/tushare/股票数据/行情数据/0027_A股日线行情.md`
- 分页：文档未写明单次上限数值；按工程统一上限 `limit=6000`，`offset` 递增分页。
- 默认请求：默认按 `start_date/end_date` 过滤交易日，逐 `trade_date` 请求；若只给 `trade_date` 则按单日请求。
- 用户传参规则：用户若显式传 `ts_code`，就原样透传；可组合；未传不补。
- 时间执行：以交易日为基准；区间任务先筛交易日，再逐日请求。

### `daily_basic`（股票日指标）

- 接口：`daily_basic`
- 源文档：`docs/sources/tushare/股票数据/行情数据/0032_每日指标.md`
- 分页：`limit=6000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认按 `start_date/end_date` 过滤交易日，逐 `trade_date` 请求；若只给 `trade_date` 则按单日请求。
- 用户传参规则：用户若显式传 `ts_code`，就原样透传；可组合；未传不补。
- 时间执行：以交易日为基准；区间任务先筛交易日，再逐日请求。

### `dc_daily`（东方财富板块行情）

- 接口：`dc_daily`
- 源文档：`docs/sources/tushare/股票数据/打板专题数据/0382_东财概念板块行情.md`
- 分页：`limit=2000`（文档单次上限），`offset` 递增分页。
- 默认请求：以时间参数为核心，不做板块代码扇出。`trade_date` 单日请求；`start_date/end_date` 先按交易日历筛交易日，再逐交易日请求。
- 用户传参规则：用户若显式传 `ts_code`、`idx_type`，单值直接透传；若 `idx_type` 传入多值则按枚举扇出请求；若 `idx_type` 为全选则折叠为不传该字段；未传不补。
- 时间执行：以交易日为基准；逐交易日均采用分页闭环（`offset += limit`，直到返回 `< limit`）。

### `dc_hot`（东方财富热榜）

- 接口：`dc_hot`
- 源文档：`docs/sources/tushare/股票数据/打板专题数据/0321_东方财富热榜.md`
- 分页：`limit=2000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认不传 `ts_code/market/hot_type/is_new`；按 `start_date/end_date` 过滤交易日，逐 `trade_date` 请求。
- 用户传参规则：用户若显式传 `ts_code`、`market`、`hot_type`、`is_new`，单值直接透传；若 `market/hot_type/is_new` 任一传多值则按枚举扇出；若多字段同时多值则按笛卡尔组合请求；若某字段为全选则折叠为不传该字段后再计算组合；未传不补。
- 组合示例：若 `trade_date` 已给，且 `market` 全选、`hot_type` 全选、`is_new` 未传，则请求参数折叠为仅 `trade_date`（再叠加分页 `limit/offset`）。
- 时间执行：按单个 `trade_date` 请求；如需区间，由上层枚举交易日逐日调用。

### `dc_index`（东方财富概念板块）

- 接口：`dc_index`
- 源文档：`docs/sources/tushare/股票数据/打板专题数据/0362_东方财富概念板块.md`
- 分页：`limit=5000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认按 `start_date/end_date` 过滤交易日，逐 `trade_date` 请求；若只给 `trade_date` 则按单日请求。
- 用户传参规则：用户若显式传 `ts_code`、`name`、`idx_type`，单值直接透传；若 `idx_type` 传入多值则按枚举扇出；若 `idx_type` 为全选则折叠为不传该字段；未传不补。
- 时间执行：以交易日为基准；区间任务先筛交易日，再逐日请求。

### `dc_member`（东方财富板块成分）

- 接口：`dc_member`
- 源文档：`docs/sources/tushare/股票数据/打板专题数据/0363_东方财富板块成分.md`
- 分页：`limit=5000`（文档单次上限），`offset` 递增分页。
- 默认请求：以时间参数为核心，不做板块代码扇出。`trade_date` 单日请求；`start_date/end_date` 先按交易日历筛交易日，再逐交易日请求。
- 用户传参规则：用户若显式传 `ts_code`、`con_code`，就原样透传；可组合；未传不补。
- 时间执行：以交易日为基准；逐交易日均采用分页闭环（`offset += limit`，直到返回 `< limit`）。

### `dividend`（分红送转）

- 接口：`dividend`
- 源文档：`docs/sources/tushare/股票数据/财务数据/0103_分红送股.md`
- 分页：文档未写明单次上限数值；按工程统一上限 `limit=6000`，`offset` 递增分页。
- 默认请求：事件类：默认不扇出 `ts_code`，按用户显式事件日期参数（`ann_date/record_date/ex_date/imp_ann_date`）过滤。
- 用户传参规则：用户若显式传 `ts_code`，就原样透传；可组合；未传不补。
- 时间执行：按事件日期参数执行（公告日/登记日/除权日等），不使用交易日语义。

### `etf_basic`（ETF 基本信息）

- 接口：`etf_basic`
- 源文档：`docs/sources/tushare/ETF专题/0385_ETF基础信息.md`
- 分页：`limit=5000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认做快照请求（不带可选过滤参数）。
- 用户传参规则：用户若显式传 `ts_code`、`index_code`、`list_date`、`list_status`、`exchange`、`mgr`，单值直接透传；若 `list_status/exchange` 任一传多值则按枚举扇出；若两者都多值则按笛卡尔组合请求；若某字段为全选则折叠为不传该字段后再计算组合；未传不补。
- 时间执行：无时间锚点，按快照执行。

### `etf_index`（ETF 基准指数列表）

- 接口：`etf_index`
- 源文档：`docs/sources/tushare/ETF专题/0386_ETF基准指数列表.md`
- 分页：`limit=5000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认做快照请求（不带可选过滤参数）。
- 用户传参规则：用户若显式传 `ts_code`、`pub_date`、`base_date`，就原样透传；可组合；未传不补。
- 时间执行：无时间锚点，按快照执行。

### `fund_adj`（基金复权因子）

- 接口：`fund_adj`
- 源文档：`docs/sources/tushare/ETF专题/0199_基金复权因子.md`
- 分页：`limit=2000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认按 `start_date/end_date` 过滤交易日，逐 `trade_date` 请求；若只给 `trade_date` 则按单日请求。
- 用户传参规则：用户若显式传 `ts_code`，就原样透传；可组合；未传不补。
- 时间执行：以交易日为基准；区间任务先筛交易日，再逐日请求。

### `fund_daily`（基金日线）

- 接口：`fund_daily`
- 源文档：`docs/sources/tushare/ETF专题/0127_ETF日线行情.md`
- 分页：`limit=5000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认按 `start_date/end_date` 过滤交易日，逐 `trade_date` 请求；若只给 `trade_date` 则按单日请求。
- 用户传参规则：用户若显式传 `ts_code`，就原样透传；可组合；未传不补。
- 时间执行：以交易日为基准；区间任务先筛交易日，再逐日请求。

### `hk_basic`（港股列表）

- 接口：`hk_basic`
- 源文档：`docs/sources/tushare/港股数据/0191_港股列表.md`
- 分页：文档未写明单次上限数值；按工程统一上限 `limit=6000`，`offset` 递增分页。
- 默认请求：默认做快照请求（不带可选过滤参数）。
- 用户传参规则：用户若显式传 `ts_code`、`list_status`，单值直接透传；若 `list_status` 传入多值则按枚举扇出请求；若 `list_status` 为全选则折叠为不传该字段；未传不补。
- 时间执行：无时间锚点，按快照执行。

### `index_basic`（指数主数据）

- 接口：`index_basic`
- 源文档：`docs/sources/tushare/指数专题/0094_指数基本信息.md`
- 分页：文档未写明单次上限数值；按工程默认 `limit=6000`，`offset` 递增分页。
- 默认请求：默认做快照请求（不带可选过滤参数）。
- 用户传参规则：用户若显式传 `ts_code`、`name`、`market`、`publisher`、`category`，单值直接透传；若 `market/category` 任一传多值则按枚举扇出；若两者都多值则按笛卡尔组合请求；若某字段为全选则折叠为不传该字段后再计算组合；未传不补。
- 时间执行：无时间锚点，按快照执行。

### `index_daily`（指数日线）

- 接口：`index_daily`
- 源文档：`docs/sources/tushare/指数专题/0095_指数日线行情.md`
- 分页：`limit=8000`（文档单次上限），`offset` 递增分页。
- 默认请求：固定走 active 指数池（你定制口径），在指数池内逐 `trade_date` 请求。
- 用户传参规则：用户若显式传 `ts_code`，就原样透传；可组合；未传不补。
- 时间执行：以交易日为基准；区间任务先筛交易日，再逐日请求。

### `index_daily_basic`（指数日指标）

- 接口：`index_dailybasic`
- 源文档：`docs/sources/tushare/指数专题/0128_大盘指数每日指标.md`
- 分页：`limit=3000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认按 `start_date/end_date` 过滤交易日，逐 `trade_date` 请求；若只给 `trade_date` 则按单日请求。
- 用户传参规则：用户若显式传 `ts_code`，就原样透传；可组合；未传不补。
- 时间执行：以交易日为基准；区间任务先筛交易日，再逐日请求。

### `index_monthly`（指数月线）

- 接口：`index_monthly`
- 源文档：`docs/sources/tushare/指数专题/0172_指数月线行情.md`
- 分页：`limit=1000`（文档单次上限），`offset` 递增分页。
- 默认请求：固定走 active 指数池（你定制口径），按月末交易日锚点逐点请求。
- 用户传参规则：用户若显式传 `ts_code`，就原样透传；可组合；未传不补。
- 时间执行：仅在月末交易日执行。

### `index_weekly`（指数周线）

- 接口：`index_weekly`
- 源文档：`docs/sources/tushare/指数专题/0171_指数周线行情.md`
- 分页：`limit=1000`（文档单次上限），`offset` 递增分页。
- 默认请求：固定走 active 指数池（你定制口径），按周末交易日锚点逐点请求。
- 用户传参规则：用户若显式传 `ts_code`，就原样透传；可组合；未传不补。
- 时间执行：仅在周末交易日执行。

### `index_weight`（指数成分权重）

- 接口：`index_weight`
- 源文档：`docs/sources/tushare/指数专题/0096_指数成分和权重.md`
- 分页：文档未写明单次上限数值；按工程默认 `limit=6000`，`offset` 递增分页。
- 默认请求：按月自然日窗口请求：每月 `start_date=当月1日`、`end_date=当月最后一日`，并按 `index_code` 执行。
- 用户传参规则：用户若显式传 `index_code`，单值直接透传；若传入多值则按枚举扇出请求；若 `index_code` 为全选则折叠为不传该字段；未传不补。
- 时间执行：按自然月窗口执行（非“周/月最后交易日”语义）。

### `kpl_concept_cons`（开盘啦题材成分）

- 接口：`kpl_concept_cons`
- 源文档：`docs/sources/tushare/股票数据/打板专题数据/0351_开盘啦题材成分.md`
- 分页：`limit=3000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认按 `trade_date` 单点请求。
- 用户传参规则：用户若显式传 `ts_code`、`con_code`，就原样透传；可组合；未传不补。
- 时间执行：按单个 `trade_date` 请求；如需区间，由上层枚举交易日逐日调用。

### `kpl_list`（开盘啦榜单）

- 接口：`kpl_list`
- 源文档：`docs/sources/tushare/股票数据/打板专题数据/0347_开盘啦榜单数据.md`
- 分页：`limit=8000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认按 `start_date/end_date` 过滤交易日，逐 `trade_date` 请求；若只给 `trade_date` 则按单日请求。
- 用户传参规则：用户若显式传 `ts_code`、`tag`，单值直接透传；若 `tag` 传入多值则按枚举扇出请求；若 `tag` 为全选则折叠为不传该字段；未传不补。
- 时间执行：以交易日为基准；区间任务先筛交易日，再逐日请求。

### `limit_cpt_list`（最强板块统计）

- 接口：`limit_cpt_list`
- 源文档：`docs/sources/tushare/股票数据/打板专题数据/0357_最强板块统计.md`
- 分页：`limit=2000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认按 `start_date/end_date` 过滤交易日，逐 `trade_date` 请求；若只给 `trade_date` 则按单日请求。
- 用户传参规则：用户若显式传 `ts_code`，就原样透传；可组合；未传不补。
- 时间执行：以交易日为基准；区间任务先筛交易日，再逐日请求。

### `limit_list_d`（涨跌停榜）

- 接口：`limit_list_d`
- 源文档：`docs/sources/tushare/股票数据/打板专题数据/0298_涨跌停列表（新）.md`
- 分页：`limit=2500`（文档单次上限），`offset` 递增分页。
- 默认请求：默认按 `start_date/end_date` 过滤交易日，逐 `trade_date` 请求；若只给 `trade_date` 则按单日请求。
- 用户传参规则：用户若显式传 `ts_code`、`limit_type`、`exchange`，单值直接透传；若 `limit_type/exchange` 任一传多值则按枚举扇出；若两者都多值则按笛卡尔组合请求；若某字段为全选则折叠为不传该字段后再计算组合；未传不补。
- 时间执行：以交易日为基准；区间任务先筛交易日，再逐日请求。

### `limit_list_ths`（同花顺涨跌停榜单）

- 接口：`limit_list_ths`
- 源文档：`docs/sources/tushare/股票数据/打板专题数据/0355_涨跌停榜单（同花顺）.md`
- 分页：`limit=4000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认按 `start_date/end_date` 过滤交易日，逐 `trade_date` 请求；若只给 `trade_date` 则按单日请求。
- 用户传参规则：用户若显式传 `ts_code`、`limit_type`、`market`，单值直接透传；若 `limit_type/market` 任一传多值则按枚举扇出；若两者都多值则按笛卡尔组合请求；若某字段为全选则折叠为不传该字段后再计算组合；未传不补。
- 时间执行：以交易日为基准；区间任务先筛交易日，再逐日请求。

### `limit_step`（涨停天梯）

- 接口：`limit_step`
- 源文档：`docs/sources/tushare/股票数据/打板专题数据/0356_连板天梯.md`
- 分页：`limit=2000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认按 `start_date/end_date` 过滤交易日，逐 `trade_date` 请求；若只给 `trade_date` 则按单日请求。
- 用户传参规则：用户若显式传 `ts_code`、`nums`，就原样透传；可组合；未传不补。
- 时间执行：以交易日为基准；区间任务先筛交易日，再逐日请求。

### `margin`（融资融券交易汇总）

- 接口：`margin`
- 源文档：`docs/sources/tushare/股票数据/两融及转融通/0058_融资融券交易汇总.md`
- 分页：`limit=4000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认按 `start_date/end_date` 过滤交易日，逐 `trade_date` 请求；若只给 `trade_date` 则按单日请求。
- 用户传参规则：用户若显式传 `exchange_id`，单值直接透传；若 `exchange_id` 传入多值则按枚举扇出请求；若 `exchange_id` 为全选则折叠为不传该字段；未传不补。
- 时间执行：以交易日为基准；区间任务先筛交易日，再逐日请求。

### `moneyflow`（资金流向（基础））

- 接口：`moneyflow`
- 源文档：`docs/sources/tushare/股票数据/资金流向数据/0170_个股资金流向.md`
- 分页：`limit=6000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认按 `start_date/end_date` 过滤交易日，逐 `trade_date` 请求；若只给 `trade_date` 则按单日请求。
- 用户传参规则：用户若显式传 `ts_code`，就原样透传；可组合；未传不补。
- 时间执行：以交易日为基准；区间任务先筛交易日，再逐日请求。

### `moneyflow_cnt_ths`（概念板块资金流向（同花顺））

- 接口：`moneyflow_cnt_ths`
- 源文档：`docs/sources/tushare/股票数据/资金流向数据/0371_同花顺概念板块资金流向（THS）.md`
- 分页：`limit=5000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认按 `start_date/end_date` 过滤交易日，逐 `trade_date` 请求；若只给 `trade_date` 则按单日请求。
- 用户传参规则：用户若显式传 `ts_code`，就原样透传；可组合；未传不补。
- 时间执行：以交易日为基准；区间任务先筛交易日，再逐日请求。

### `moneyflow_dc`（个股资金流向（东方财富））

- 接口：`moneyflow_dc`
- 源文档：`docs/sources/tushare/股票数据/资金流向数据/0349_个股资金流向（DC）.md`
- 分页：`limit=6000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认按 `start_date/end_date` 过滤交易日，逐 `trade_date` 请求；若只给 `trade_date` 则按单日请求。
- 用户传参规则：用户若显式传 `ts_code`，就原样透传；可组合；未传不补。
- 时间执行：以交易日为基准；区间任务先筛交易日，再逐日请求。

### `moneyflow_ind_dc`（板块资金流向（东方财富））

- 接口：`moneyflow_ind_dc`
- 源文档：`docs/sources/tushare/股票数据/资金流向数据/0344_东财概念及行业板块资金流向（DC）.md`
- 分页：`limit=5000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认按 `start_date/end_date` 过滤交易日，逐 `trade_date` 请求；若只给 `trade_date` 则按单日请求。
- 用户传参规则：用户若显式传 `ts_code`、`content_type`，单值直接透传；若 `content_type` 传入多值（如行业/概念/地域）则按枚举扇出请求；若 `content_type` 为全选则折叠为不传该字段；未传不补。
- 时间执行：以交易日为基准；区间任务先筛交易日，再逐日请求。

### `moneyflow_ind_ths`（行业资金流向（同花顺））

- 接口：`moneyflow_ind_ths`
- 源文档：`docs/sources/tushare/股票数据/资金流向数据/0343_同花顺行业资金流向（THS）.md`
- 分页：`limit=5000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认按 `start_date/end_date` 过滤交易日，逐 `trade_date` 请求；若只给 `trade_date` 则按单日请求。
- 用户传参规则：用户若显式传 `ts_code`，就原样透传；可组合；未传不补。
- 时间执行：以交易日为基准；区间任务先筛交易日，再逐日请求。

### `moneyflow_mkt_dc`（市场资金流向（东方财富））

- 接口：`moneyflow_mkt_dc`
- 源文档：`docs/sources/tushare/股票数据/资金流向数据/0345_大盘资金流向（DC）.md`
- 分页：`limit=3000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认按 `start_date/end_date` 过滤交易日，逐 `trade_date` 请求；若只给 `trade_date` 则按单日请求。
- 用户传参规则：除时间参数与分页参数外，无额外可选维度；按默认策略执行。
- 时间执行：以交易日为基准；区间任务先筛交易日，再逐日请求。

### `moneyflow_ths`（个股资金流向（同花顺））

- 接口：`moneyflow_ths`
- 源文档：`docs/sources/tushare/股票数据/资金流向数据/0348_个股资金流向（THS）.md`
- 分页：`limit=6000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认按 `start_date/end_date` 过滤交易日，逐 `trade_date` 请求；若只给 `trade_date` 则按单日请求。
- 用户传参规则：用户若显式传 `ts_code`，就原样透传；可组合；未传不补。
- 时间执行：以交易日为基准；区间任务先筛交易日，再逐日请求。

### `stk_factor_pro`（股票技术面因子(专业版)）

- 接口：`stk_factor_pro`
- 源文档：`docs/sources/tushare/股票数据/特色数据/0328_股票技术面因子(专业版).md`
- 分页：`limit=10000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认按 `start_date/end_date` 过滤交易日，逐 `trade_date` 请求；若只给 `trade_date` 则按单日请求。
- 用户传参规则：用户若显式传 `ts_code`，就原样透传；可组合；未传不补。
- 时间执行：以交易日为基准；区间任务先筛交易日，再逐日请求。

### `stk_holdernumber`（股东户数）

- 接口：`stk_holdernumber`
- 源文档：`docs/sources/tushare/股票数据/参考数据/0166_股东人数.md`
- 分页：`limit=3000`（文档单次上限），`offset` 递增分页。
- 默认请求：事件类：默认不扇出 `ts_code`，优先按 `start_date/end_date` 区间请求；定向补数再传 `ts_code`。
- 用户传参规则：用户若显式传 `ts_code`，就原样透传；可组合；未传不补。
- 时间执行：按事件日期区间或公告日期执行，不使用交易日语义。

### `stk_limit`（每日涨跌停价格）

- 接口：`stk_limit`
- 源文档：`docs/sources/tushare/股票数据/行情数据/0183_每日涨跌停价格.md`
- 分页：`limit=5800`（文档单次上限），`offset` 递增分页。
- 默认请求：默认按 `start_date/end_date` 过滤交易日，逐 `trade_date` 请求；若只给 `trade_date` 则按单日请求。
- 用户传参规则：用户若显式传 `ts_code`，就原样透传；可组合；未传不补。
- 时间执行：以交易日为基准；区间任务先筛交易日，再逐日请求。

### `stk_mins`（股票历史分钟行情）

- 接口：`stk_mins`
- 源文档：`docs/sources/tushare/股票数据/行情数据/0370_股票历史分钟行情.md`
- 分页：Tushare 请求分页固定 `limit=8000`，`offset` 递增分页；这是接口内部分页，不对用户暴露。
- 默认请求：按交易日执行，程序内部固定拆为上午 `09:30:00~11:30:00` 与下午 `13:00:00~15:00:00` 两个交易时段；未传 `ts_code` 时按股票池全量扇出；用户必须选择 `freq`。
- 用户传参规则：用户可显式传 `ts_code`、`freq`；`freq` 支持 `1min/5min/15min/30min/60min` 多选，按频度扇出请求；不暴露具体小时、分钟、秒输入，也不暴露股票池 offset/limit。
- 时间执行：以交易日为基准；`trade_date` 单日执行，`start_date/end_date` 先筛交易日后逐日执行；不纳入普通 `sync-history`，单独使用 `sync-minute-history` / `sync_minute_history.stk_mins`。

### `stk_nineturn`（神奇九转指标）

- 接口：`stk_nineturn`
- 源文档：`docs/sources/tushare/股票数据/特色数据/0364_神奇九转指标.md`
- 分页：`limit=10000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认按 `start_date/end_date` 过滤交易日，逐 `trade_date` 请求；若只给 `trade_date` 则按单日请求；`freq` 在实现内固定为 `daily`，不对用户暴露。
- 用户传参规则：用户只可显式传 `ts_code`；`freq` 为系统内置固定参数（`daily`），不接受用户输入。
- 时间执行：以交易日为基准；区间任务先筛交易日，再逐日请求。

### `stk_period_bar_adj_month`（股票复权月线）

- 接口：`stk_week_month_adj`
- 源文档：`docs/sources/tushare/股票数据/行情数据/0365_股票周_月线行情(复权--每日更新).md`
- 分页：`limit=6000`（文档单次上限），`offset` 递增分页。
- 默认请求：按月末交易日锚点请求（复权月线只在月末交易日触发）；`freq` 在实现内固定为“月线”，不对用户暴露。
- 用户传参规则：用户只可显式传 `ts_code`；`freq` 为系统内置固定参数，不接受用户输入。
- 时间执行：仅在月末交易日执行。

### `stk_period_bar_adj_week`（股票复权周线）

- 接口：`stk_week_month_adj`
- 源文档：`docs/sources/tushare/股票数据/行情数据/0365_股票周_月线行情(复权--每日更新).md`
- 分页：`limit=6000`（文档单次上限），`offset` 递增分页。
- 默认请求：按周末交易日锚点请求（复权周线只在周末交易日触发）；`freq` 在实现内固定为“周线”，不对用户暴露。
- 用户传参规则：用户只可显式传 `ts_code`；`freq` 为系统内置固定参数，不接受用户输入。
- 时间执行：仅在周末交易日执行。

### `stk_period_bar_month`（股票月线）

- 接口：`stk_weekly_monthly`
- 源文档：`docs/sources/tushare/股票数据/行情数据/0336_股票周_月线行情(每日更新).md`
- 分页：`limit=6000`（文档单次上限），`offset` 递增分页。
- 默认请求：按月末交易日锚点请求（月线只在月末交易日触发）；`freq` 在实现内固定为“月线”，不对用户暴露。
- 用户传参规则：用户只可显式传 `ts_code`；`freq` 为系统内置固定参数，不接受用户输入。
- 时间执行：仅在月末交易日执行。

### `stk_period_bar_week`（股票周线）

- 接口：`stk_weekly_monthly`
- 源文档：`docs/sources/tushare/股票数据/行情数据/0336_股票周_月线行情(每日更新).md`
- 分页：`limit=6000`（文档单次上限），`offset` 递增分页。
- 默认请求：按周末交易日锚点请求（周线只在周末交易日触发）；`freq` 在实现内固定为“周线”，不对用户暴露。
- 用户传参规则：用户只可显式传 `ts_code`；`freq` 为系统内置固定参数，不接受用户输入。
- 时间执行：仅在周末交易日执行。

### `stock_basic`（股票主数据）

- 接口：`stock_basic`
- 源文档：`docs/sources/tushare/股票数据/基础数据/0025_基础信息.md`
- 分页：`limit=6000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认快照请求固定 `list_status=L,D,P,G`（全口径），不传其他可选过滤。
- 用户传参规则：用户若显式传 `ts_code`、`name`、`market`、`list_status`、`exchange`、`is_hs`，单值直接透传；若 `list_status/market/exchange/is_hs` 传入多值则按枚举扇出；多字段同时多值时按笛卡尔组合请求；若某字段为全选则折叠为不传该字段后再计算组合；未传不补。
- 时间执行：无时间锚点，按快照执行。

### `stock_st`（ST股票列表）

- 接口：`stock_st`
- 源文档：`docs/sources/tushare/股票数据/基础数据/0397_ST股票列表.md`
- 分页：`limit=1000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认按 `start_date/end_date` 过滤交易日，逐 `trade_date` 请求；若只给 `trade_date` 则按单日请求。
- 用户传参规则：用户若显式传 `ts_code`，就原样透传；可组合；未传不补。
- 时间执行：以交易日为基准；区间任务先筛交易日，再逐日请求。

### `suspend_d`（每日停复牌信息）

- 接口：`suspend_d`
- 源文档：`docs/sources/tushare/股票数据/行情数据/0214_每日停复牌信息.md`
- 分页：文档未写明单次上限数值；默认不强制写死 `limit`，如需统一分页可用保守值 `limit=2000`。
- 默认请求：默认按 `start_date/end_date` 过滤交易日，逐 `trade_date` 请求；若只给 `trade_date` 则按单日请求。
- 用户传参规则：用户若显式传 `ts_code`、`suspend_type`，单值直接透传；若 `suspend_type` 传入多值则按枚举扇出请求；若 `suspend_type` 为全选则折叠为不传该字段；未传不补。
- 时间执行：以交易日为基准；区间任务先筛交易日，再逐日请求。

### `ths_daily`（同花顺板块行情）

- 接口：`ths_daily`
- 源文档：`docs/sources/tushare/股票数据/打板专题数据/0260_同花顺板块指数行情.md`
- 分页：`limit=3000`（文档单次上限），`offset` 递增分页。
- 默认请求：以时间参数为核心，不做板块代码扇出。`trade_date` 单日请求；`start_date/end_date` 先按交易日历筛交易日，再逐交易日请求。
- 用户传参规则：用户若显式传 `ts_code`，就原样透传；可组合；未传不补。
- 时间执行：以交易日为基准；逐交易日均采用分页闭环（`offset += limit`，直到返回 `< limit`）。

### `ths_hot`（同花顺热榜）

- 接口：`ths_hot`
- 源文档：`docs/sources/tushare/股票数据/打板专题数据/0320_同花顺热榜.md`
- 分页：`limit=2000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认不传 `ts_code/market/is_new`；按 `start_date/end_date` 过滤交易日，逐 `trade_date` 请求。
- 用户传参规则：用户若显式传 `ts_code`、`market`、`is_new`，单值直接透传；若 `market/is_new` 任一传多值则按枚举扇出；若两者都多值则按笛卡尔组合请求；若某字段为全选则折叠为不传该字段后再计算组合；未传不补。
- 时间执行：按单个 `trade_date` 请求；如需区间，由上层枚举交易日逐日调用。

### `ths_index`（同花顺概念和行业指数）

- 接口：`ths_index`
- 源文档：`docs/sources/tushare/股票数据/打板专题数据/0259_同花顺概念和行业指数.md`
- 分页：`limit=5000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认做快照请求（不带可选过滤参数）。
- 用户传参规则：用户若显式传 `ts_code`、`exchange`、`type`，单值直接透传；若 `exchange/type` 任一传多值则按枚举扇出；若两者都多值则按笛卡尔组合请求；若某字段为全选则折叠为不传该字段后再计算组合；未传不补。
- 时间执行：无时间锚点，按快照执行。

### `ths_member`（同花顺板块成分）

- 接口：`ths_member`
- 源文档：`docs/sources/tushare/股票数据/打板专题数据/0261_同花顺概念板块成分.md`
- 分页：`limit=6000`（文档单次上限），`offset` 递增分页。
- 默认请求：无时间参数，默认单窗分页请求（不做板块代码扇出）。
- 用户传参规则：用户若显式传 `ts_code`、`con_code`，就原样透传；可组合；未传不补。
- 时间执行：无时间锚点；执行时采用分页闭环（`offset += limit`，直到返回 `< limit`）。

### `top_list`（龙虎榜）

- 接口：`top_list`
- 源文档：`docs/sources/tushare/股票数据/打板专题数据/0106_龙虎榜每日明细.md`
- 分页：`limit=10000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认按 `trade_date` 单点请求。
- 用户传参规则：用户若显式传 `ts_code`，就原样透传；可组合；未传不补。
- 时间执行：按单个 `trade_date` 请求；如需区间，由上层枚举交易日逐日调用。

### `trade_cal`（交易日历）

- 接口：`trade_cal`
- 源文档：`docs/sources/tushare/股票数据/基础数据/0026_交易日历.md`
- 分页：文档未写明单次上限数值；默认不强制写死 `limit`，如需统一分页可用保守值 `limit=2000`。
- 默认请求：默认按 `start_date/end_date` 单窗请求。
- 用户传参规则：用户若显式传 `exchange`、`is_open`，单值直接透传；若 `exchange/is_open` 任一传多值则按枚举扇出；若两者都多值则按笛卡尔组合请求；若某字段为全选则折叠为不传该字段后再计算组合；未传不补。
- 时间执行：按自然日区间单窗执行。

### `us_basic`（美股列表）

- 接口：`us_basic`
- 源文档：`docs/sources/tushare/美股数据/0252_美股列表.md`
- 分页：`limit=6000`（文档单次上限），`offset` 递增分页。
- 默认请求：默认做快照请求（不带可选过滤参数）。
- 用户传参规则：用户若显式传 `ts_code`、`classify`，单值直接透传；若 `classify` 传入多值则按枚举扇出请求；若 `classify` 为全选则折叠为不传该字段；未传不补。
- 时间执行：无时间锚点，按快照执行。
