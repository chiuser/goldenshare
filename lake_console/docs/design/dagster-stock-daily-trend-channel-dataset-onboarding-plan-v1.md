# 股票日线趋势通道 Lake 数据集接入技术方案 v1

状态：M0～M5 已完成；每日链路与 exact-batch 趋势 repair 已落地，尚未实现 bootstrap、本地 Wealth、部署、正式写湖或 Sensor 启用

日期：2026-09-02

适用范围：A 股股票日线、前复权、Gold Lake、Dagster 日常增量与历史 repair、本地 Wealth 消费

本文是股票日线趋势通道数据集的主技术方案。它不会替代或修改现有上证指数按需计算方案：

- [上证指数日线趋势通道实时计算方案 v1](/Users/congming/github/goldenshare/docs/architecture/sse-daily-trend-channel-realtime-computation-plan-v1.md)
- [上证指数日线趋势通道实时计算 LLD v1](/Users/congming/github/goldenshare/docs/architecture/sse-daily-trend-channel-realtime-computation-low-level-design-v1.md)

本方案的实施级设计见：

- [股票日线趋势通道 Lake 数据集接入 LLD v1](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-daily-trend-channel-dataset-onboarding-low-level-design-v1.md)

M0 实测基线见：

- [股票日线趋势通道 M0 只读规模与性能验证报告](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-daily-trend-channel-m0-readonly-performance-validation-2026-09-01.md)

股票方案复用指数方案的公式语义，但采用“按日预计算、持久化 state、可 repair 的 Lake 数据资产”架构。

---

## 1. 结论

股票日线趋势通道采用两个正式 Gold 资产：

1. `gold_stock_daily_trend_channel`：保存每只股票每个实际行情日的通道结果，供研究、统计和本地 Wealth 展示。
2. `gold_stock_daily_trend_channel_state`：保存每个交易日收盘后的精确递推状态；无行情但按生命周期仍在有效股票池中的已初始化股票允许 carry-forward，供下一日增量和统计使用。

数据只来自正式 Lake：

```text
gold_stock_daily_qfq
silver_stock_basic
silver_stock_lifecycle（历史初始化与历史股票池）
silver_trade_calendar
```

核心运行口径：

1. 趋势通道按交易日分区，每天 06:00 后注册当日分区；注册不等于触发计算。
2. 日常计算必须等待当日前复权日线、前复权 factor repair 结论、股票基础信息和上一交易日趋势 state 全部 ready。
3. 如果前复权因子变化并重写历史，趋势通道必须先对受影响股票从最早受影响日期向后 repair，再计算当日分区。
4. EMA 是无限递推状态，不能用 25 日或 90 日窗口截断 repair。
5. 历史初始化使用 `Direct Lake Bootstrap + Runless Event Backfill`，不使用逐日 Dagster backfill。
6. 正式计算使用 DuckDB 向量化 SQL；禁止 Python 逐股票、逐日循环处理明细行。
7. 正式文件只能写入 `/Volumes/datasource/data_lake/gold`，候选文件只能写入 `/Volumes/datasource/data_lake_staging`，校验通过后同文件系统原子替换；不使用 Kopia。
8. Wealth 只在本地 `dev/local` 且显式开关开启时挂载读取 Lake 的 API；远程部署不挂载、不回退 Prod DB、不提供该功能。

本方案同时纳入两个已确认的前复权修复契约调整：

1. 即使当日没有复权因子变化，也必须落一条可消费的“无需 repair”完成状态，不能只在 sensor 中静默跳过。
2. 自动可执行范围内必须在 check metadata 保存完整 `repair_required_codes`；前 20 个样本单独进入 `repair_required_code_samples`，不能再用样本列表冒充完整范围。

---

## 2. 目标与非目标

### 2.1 目标

1. 为 A 股股票按日生成可复现的前复权趋势通道结果。
2. 支持后续按交易日、股票、短期状态、长期状态和组合状态做统计。
3. 日常增量只读取当日前复权行情、上一交易日 state 和当日股票池，不从历史起点重算全市场。
4. 前复权历史重写后，能精确限定受影响股票并向后 repair，最终结果与基于修复后前复权历史的全量重算一致。
5. 资产、分区、文件、schema、checks、job、sensor、cursor 和 run contract 全部进入当前 Dagster 正式治理体系。
6. 本地 Wealth 能读取正式 Lake 结果；远程 Wealth 不暴露该能力。

### 2.2 非目标

本方案不做：

1. 不修改现有上证指数趋势通道 API、缓存或前端实现。
2. 不把股票趋势通道写入 Prod PostgreSQL、ClickHouse 或 Redis。
3. 不新增 Tushare 请求，不修改 `gold_stock_daily_qfq` 的计算公式。
4. 不支持周线、月线、分钟线趋势通道。
5. 不允许运营或前端传入 EMA 周期、种子或状态规则。
6. 不生成买卖建议、胜率或预测结论。
7. 不把生产 check 做成第二套趋势公式计算器。
8. 不在本方案中启用 sensor、执行历史 bootstrap、repair 或正式写湖。

---

## 3. 当前代码事实与设计影响

### 3.1 现有指数趋势通道是按需现算

当前上证指数实现读取 `core_serving.index_daily_serving`，由后端按全历史计算并使用进程内小缓存；没有趋势通道数据库表，也没有对应 Lake 资产。

股票需要长期统计、全市场计算和历史修复，因此不能复制这条请求时全历史现算链路。

### 3.2 股票前复权日线已经是正式 Gold 分区资产

当前 `gold_stock_daily_qfq`：

| 项 | 当前事实 |
| --- | --- |
| dataset_id | `stock_daily_qfq` |
| 分区 | `cn_a_stock_trade_days` |
| 路径 | `gold/quote/stock_daily_qfq/trade_date={date}/part-000.parquet` |
| 主键 | `(trade_date, ts_code)` |
| 直接依赖 | `silver_stock_daily`、`silver_adj_factor` |
| 普通 blocking check | `gold_stock_daily_qfq_contract_check` |
| repair check | `gold_stock_daily_qfq_factor_repair_plan_evaluated` |

前复权修复会根据相邻交易日 `silver_adj_factor` 的变化找出受影响股票，并重写这些股票的历史前复权数据。因此趋势通道必须消费 repair 完成事实，不能只消费当日普通 materialization。

### 3.3 股票基础信息有两个不同用途

| 资产 | 语义 | 趋势通道用途 |
| --- | --- | --- |
| `silver_stock_basic` | 当前上市、CNY 股票快照 | 日常基础信息完成门禁和当前股票信息 |
| `silver_stock_lifecycle` | 历史上市、退市生命周期 | 日常按 `T` 判断有效股票池；历史 bootstrap 还原历史股票池 |

只用当前 `silver_stock_basic` 处理历史或补跑旧日期会漏掉已经退市的历史股票，因此日常、补跑和历史初始化都以 `silver_stock_lifecycle` 的日期有效范围确定股票池；`silver_stock_basic` 仍作为用户要求的当日基础信息更新门禁。

### 3.4 当前分区注册时间不能直接复用

`cn_a_stock_trade_days` 当前由 `stock_trade_day_sensor` 在 17:00 后注册；另一个 `cn_a_stock_current_trade_days` 在 06:00 后注册，但它服务的是当前股票资产族。

本方案不修改这两个既有分区集合或 sensor。趋势通道新增独立分区集合：

```text
cn_a_stock_daily_trend_channel_trade_days
```

并通过 `dg.IdentityPartitionMapping()` 将同一个 `YYYY-MM-DD` 映射到 `gold_stock_daily_qfq`。这样既满足 06:00 注册要求，又不会改变现有股票资产族的注册语义。

---

## 4. 公式合同

### 4.1 版本

股票方案复用指数公式语义，但使用独立版本，避免把指数专属版本名写入股票资产：

```text
formula_key     = high-low-ema-hysteresis
formula_version = stock-daily-trend-channel-v1
short_period    = 25
long_period     = 90
seed            = first_observation
state_rule      = strict_close_breakout_inside_retention
```

### 4.2 四条轨道

```text
short_upper = EMA(high, 25)
short_lower = EMA(low, 25)
long_upper  = EMA(high, 90)
long_lower  = EMA(low, 90)
```

EMA 定义：

```text
alpha(N) = 2 / (N + 1)
EMA_0    = first observation
EMA_t    = alpha * x_t + (1 - alpha) * EMA_(t-1)
```

精确递推使用未量化的 `DOUBLE` state。对外轨道值按 `0.0001`、`ROUND_HALF_UP` 量化；量化值不得反向作为下一日递推输入。

### 4.3 状态规则

每组通道独立计算：

```text
close > upper  -> position=ABOVE, state=UP
close < lower  -> position=BELOW, state=DOWN
otherwise      -> position=INSIDE, state 保持上一有效行情日不变
```

等于上轨或下轨都属于 `INSIDE`，不触发状态切换。

如果股票尚未发生第一次向上或向下突破，状态为 `UNKNOWN`。

组合状态：

```text
UNKNOWN
UP_UP
UP_DOWN
DOWN_UP
DOWN_DOWN
```

### 4.4 因果约束

第 `T` 日结果只能使用：

1. 该股票 `trade_date <= T` 的前复权日线；
2. 上一有效行情日递推状态；
3. 不晚于 `T` 的股票生命周期事实。

不得使用未来 K 线回填过去状态。

---

## 5. 数据产品与资产边界

### 5.1 指标结果资产

```text
asset_key:    gold_stock_daily_trend_channel
dataset_id:   stock_daily_trend_channel
dataset_name: 股票日线前复权趋势通道
layer:        gold
group_name:   quote
data_domain:  quote_data
source_system: derived
data_contract: gold_stock_daily_qfq_trend_channel
```

物理路径：

```text
/Volumes/datasource/data_lake/gold/indicator/stock_daily_trend_channel/
  trade_date=YYYY-MM-DD/part-000.parquet
```

每个分区只保存当日实际存在 `gold_stock_daily_qfq` 行的股票，不伪造停牌 OHLC 或交易日行情。

### 5.2 递推状态资产

```text
asset_key:    gold_stock_daily_trend_channel_state
dataset_id:   stock_daily_trend_channel_state
dataset_name: 股票日线前复权趋势通道状态
layer:        gold
group_name:   quote
data_domain:  quote_data
source_system: derived
data_contract: gold_stock_daily_qfq_trend_channel_state
```

物理路径：

```text
/Volumes/datasource/data_lake/gold/indicator/stock_daily_trend_channel_state/
  trade_date=YYYY-MM-DD/part-000.parquet
```

State 文件是当日收盘后的状态快照：

1. 当日有行情的股票，用当日 OHLC 推进 state。
2. 当日无行情、但按 `silver_stock_lifecycle` 仍属于有效股票池且此前已初始化的股票，carry-forward 上一交易日 state。
3. 新上市且尚无第一根有效前复权行情的股票，不伪造 EMA；暂不进入 state，并在 materialization metadata 记录 `uninitialized_code_count`。
4. 已不属于当日有效股票池的股票不继续 carry-forward。

该设计同时满足：

- 增量计算只读上一交易日一个 state 文件；
- 停牌股票恢复交易后仍从最后有效状态继续；
- 后续市场趋势统计可以从每日 state 快照读取当日有效股票的状态，不必逐股票回看历史。

### 5.3 Definition 形态

建议使用不可 subset 的 `multi_asset` 同时产生结果与 state：

```text
gold_stock_daily_trend_channel
gold_stock_daily_trend_channel_state
```

原因：

1. 两个资产来自同一次 DuckDB 计算，不应重复扫描输入。
2. 结果与 state 必须一起成功；否则下一日递推基线不可信。
3. Dagster UI 和 Catalog 仍分别展示业务结果与递推状态。

---

## 6. 字段契约

### 6.1 `gold_stock_daily_trend_channel`

| 字段 | DuckDB/Parquet 类型 | 空值 | 说明 |
| --- | --- | --- | --- |
| `ts_code` | `VARCHAR` | 否 | 标准股票代码 |
| `trade_date` | `DATE` | 否 | 交易日 |
| `open` | `DOUBLE` | 否 | 当日前复权开盘价 |
| `high` | `DOUBLE` | 否 | 当日前复权最高价 |
| `low` | `DOUBLE` | 否 | 当日前复权最低价 |
| `close` | `DOUBLE` | 否 | 当日前复权收盘价 |
| `short_upper` | `DOUBLE` | 否 | 短期上轨，对外量化到 4 位小数 |
| `short_lower` | `DOUBLE` | 否 | 短期下轨，对外量化到 4 位小数 |
| `short_position` | `VARCHAR` | 否 | `ABOVE/INSIDE/BELOW` |
| `short_state` | `VARCHAR` | 否 | `UNKNOWN/UP/DOWN` |
| `long_upper` | `DOUBLE` | 否 | 长期上轨，对外量化到 4 位小数 |
| `long_lower` | `DOUBLE` | 否 | 长期下轨，对外量化到 4 位小数 |
| `long_position` | `VARCHAR` | 否 | `ABOVE/INSIDE/BELOW` |
| `long_state` | `VARCHAR` | 否 | `UNKNOWN/UP/DOWN` |
| `combined_state` | `VARCHAR` | 否 | 五种组合状态之一 |
| `formula_version` | `VARCHAR` | 否 | 固定 `stock-daily-trend-channel-v1` |

主键：

```text
(trade_date, ts_code)
```

结果资产不保存 `short_upper_raw` 等内部 state，避免统计或 API 误把未量化内部值作为对外合同。

### 6.2 `gold_stock_daily_trend_channel_state`

| 字段 | DuckDB/Parquet 类型 | 空值 | 说明 |
| --- | --- | --- | --- |
| `ts_code` | `VARCHAR` | 否 | 标准股票代码 |
| `trade_date` | `DATE` | 否 | state 快照所属交易日 |
| `state_source_trade_date` | `DATE` | 否 | 最近一次实际使用 OHLC 推进 state 的日期 |
| `observed_on_partition` | `BOOLEAN` | 否 | 当日是否有实际前复权行情 |
| `short_upper_raw` | `DOUBLE` | 否 | 短期上轨精确递推 state |
| `short_lower_raw` | `DOUBLE` | 否 | 短期下轨精确递推 state |
| `short_state` | `VARCHAR` | 否 | `UNKNOWN/UP/DOWN` |
| `long_upper_raw` | `DOUBLE` | 否 | 长期上轨精确递推 state |
| `long_lower_raw` | `DOUBLE` | 否 | 长期下轨精确递推 state |
| `long_state` | `VARCHAR` | 否 | `UNKNOWN/UP/DOWN` |
| `combined_state` | `VARCHAR` | 否 | 五种组合状态之一 |
| `formula_version` | `VARCHAR` | 否 | 固定 `stock-daily-trend-channel-v1` |

主键：

```text
(trade_date, ts_code)
```

`observed_on_partition=false` 时，四个 raw EMA 和状态必须与上一交易日完全一致，只允许 `trade_date` 前进。

---

## 7. Catalog、分区、路径与注册

### 7.1 Catalog 接入

实现时必须同步新增：

1. `DATASET_CHINESE_NAMES` 两个中文名。
2. `PartitionModel` 两个稳定枚举：
   - `trade_date_partition_gold_stock_daily_trend_channel`
   - `trade_date_partition_gold_stock_daily_trend_channel_state`
3. `PARTITION_MODEL_DEFINITIONS`：均为 `TRADE_DATE_PARTITION + PARTITION_FILE`。
4. `LAKE_ASSET_CATALOG` 两个 `_derived_entry`。
5. `asset_column_schemas.py` 两组 `ColumnContract`。
6. `paths.py` 正式路径与 staging 路径 helper。

建议性能合同：

```text
batch_grain: trade_date
compute_engine: duckdb_sql
python_row_loop_allowed: false
source_request_policy: no external request; bounded local parquet reads
write_policy: partition_file_atomic_replace
event_policy: supports_runless_event_backfill
bootstrap_sources: derived_from_assets
```

### 7.2 分区定义

新增：

```text
cn_a_stock_daily_trend_channel_trade_days
```

日期来源固定为 `silver_trade_calendar` 的 `exchange='SSE' AND is_open=true`。

分区 key：

```text
YYYY-MM-DD
```

### 7.3 06:00 注册 sensor

新增：

```text
stock_daily_trend_channel_trade_day_sensor
```

固定口径：

| 项 | 值 |
| --- | --- |
| default status | `STOPPED` |
| minimum interval | `600s` |
| same-day register start | `06:00 Asia/Shanghai` |
| 每 tick 最多注册 | 2 个最早缺失 expected dates |
| 是否触发 job | 否 |
| cursor | 通用小型 cursor，不保存历史日期列表 |

该 sensor 只负责注册。06:00 时日线行情通常尚未完成，不能因为分区存在就把数据标成 ready。

---

## 8. 日常增量计算

### 8.1 输入读取边界

交易日 `T` 的普通增量最多读取：

1. `gold_stock_daily_qfq[T]` 一个文件；
2. `gold_stock_daily_trend_channel_state[T-1]` 一个文件；
3. `silver_stock_basic` 一个全量快照；
4. `silver_stock_lifecycle` 一个全量快照；
5. 有界的 Dagster materialization/check 状态。

禁止每日扫描全历史 qfq 文件、全历史 state 或全量 event history。

### 8.2 当日计算步骤

1. 从 `silver_trade_calendar` 找到 `T` 的 previous expected trade date `T-1`。
2. 校验 `gold_stock_daily_qfq[T]` 普通 readiness。
3. 校验 `gold_stock_daily_qfq_factor_repair_plan_evaluated[T]` 已完成且属于本次 qfq upstream batch。
4. 校验 `silver_stock_basic` 和 `silver_stock_lifecycle` 的 materialization/check/freshness 不早于 `T`。
5. 用 `silver_stock_lifecycle` 的 `[list_date, delist_date)` 口径得到 `T` 的有效股票池。
6. 非历史首日时校验 `state[T-1]` ready。
7. 以 `state[T-1]` 为基线，对 `qfq[T]` 中有行情的股票推进四条 EMA 和状态。
8. 指标结果只写当日有 qfq 行的股票。
9. State 写入“当日有效股票池中已经初始化的股票”：有行情的写新 state，无行情的 carry-forward。
10. 候选文件写入 staging，执行 schema、主键、行数、枚举、公式版本、上下轨和 carry-forward 校验。
11. 两个候选均通过后，分别 `os.replace()` 到正式分区路径。
12. materialization metadata 记录输入/输出行数、股票数、观察数、carry 数、未初始化数、上游 batch 和公式版本。

### 8.3 Job

新增：

```text
gold_stock_daily_trend_channel_update_job
```

Job 只允许包含：

```text
两个 multi_asset outputs
+ 对应 blocking checks
+ executor / description
```

SQL、路径发现、状态转换和写入逻辑不能写在 job 文件中。

### 8.4 日常 readiness sensor

新增：

```text
gold_stock_daily_trend_channel_update_job_sensor
```

使用普通 polling sensor，而不是只依赖某一个上游 run-status 事件，原因是 `gold_stock_daily_qfq` 与 `silver_stock_basic` 的完成先后不应影响最终触发。

固定规则：

1. 默认 `STOPPED`，最小间隔 `600s`。
2. 热路径只检查最近 10 个 expected trade dates。
3. 每 tick 只选择最早一个可行动日期，不跨过旧缺口计算更晚日期。
4. 目标已 materialized 但 blocking check 不绿时不自动覆盖，返回人工修复提示。
5. 缺普通 qfq readiness、qfq repair 状态、stock basic/lifecycle freshness 或 previous state 时只 skip。
6. qfq repair 显示历史重写时，必须等待同一 upstream batch 的趋势 repair completion，才能提交当日 update。
7. 不在 cursor 保存股票代码列表、文件列表或 check history。

Run key：

```text
gold_stock_daily_trend_channel_update:{trade_date}:{formula_version}
```

---

## 9. 前复权修复契约的两项先决调整

### 9.1 缺口一：无因子变化时当前没有 durable 状态

当前 `gold_stock_daily_qfq_factor_repair_job_sensor` 在 `repair_required=false` 时直接返回 `SkipReason`。这意味着普通 qfq 已 ready，但下游无法只靠正式 check 区分：

1. 已完成比较且无需 repair；
2. repair 尚未评估；
3. sensor 没有运行；
4. 评估过程失败。

目标调整：

1. qfq daily ready 后总是生成确定性的 `upstream_batch_id`，空代码列表使用稳定空 hash。
2. `repair_required_code_count <= 500` 时都提交 qfq factor repair job；其中 0 个代码是轻量 no-op reconciliation。
3. no-op job 不重写任何 qfq 文件，但必须写通过的 `gold_stock_daily_qfq_factor_repair_plan_evaluated`。
4. metadata 明确：

```text
repair_required=false
repair_required_code_count=0
repair_required_codes=[]
repair_required_codes_hash=<empty-list-hash>
repair_required_codes_truncated=false
selected_partition_count=0
rewritten_partition_count=0
rewritten_row_count=0
upstream_batch_id=<current-qfq-batch>
```

趋势通道只消费这条 durable 结果，不在自己的 sensor 中重新计算相邻复权因子。

### 9.2 缺口二：当前完整代码列表与样本列表混用

当前 qfq repair metadata 只把前 20 个代码写入 `repair_required_codes`，但自动范围允许到 500 个。下游无法对 21～500 个代码做完整、精确的 repair。

目标调整：

| 字段 | 新口径 |
| --- | --- |
| `repair_required_codes` | 自动可执行范围内保存完整排序、去重代码列表 |
| `repair_required_code_samples` | 仅用于 UI，最多前 20 个 |
| `repair_required_codes_truncated` | 只有完整列表未保存时才为 `true` |
| `repair_required_code_count` | 完整代码数量 |
| `repair_required_codes_hash` | 完整代码列表稳定 hash |

边界：

1. `0～500`：完整代码列表必须存在，hash/count/list 必须一致。
2. `>500`：qfq 自动 repair 继续 fail closed；只保存 count/hash/sample，`truncated=true`，等待批准后的人工 repair。
3. 任何消费者发现 count、hash、list、truncated 矛盾时必须阻塞，不能降级为全市场或前 20 个代码。

这些调整是上游 repair 合同修正，不改变 qfq 计算公式或表结构。

---

## 10. 趋势通道 repair

### 10.1 为什么必须向后重算

前复权因子变化会调整受影响股票的历史 OHLC。趋势通道的 EMA 满足：

```text
EMA_t = alpha * value_t + (1 - alpha) * EMA_(t-1)
```

任意历史点变化都会影响该点之后所有 EMA state。即使影响随时间衰减，也不存在 25 日或 90 日后严格归零的边界。因此：

```text
禁止只 repair 变更日
禁止只 repair 最近 25/90 个交易日
禁止只重算当前日
```

### 10.2 Repair scope

自动趋势 repair 只接受 qfq repair check 中的正式 scope：

```text
upstream_batch_id
qfq_factor_trade_date
repair_start_trade_date
repair_end_trade_date
repair_required_codes
repair_required_code_count
repair_required_codes_hash
```

范围定义：

1. 股票范围严格等于 `repair_required_codes`。
2. 起点为上游 `repair_start_trade_date`；实现时仍需逐股票从其第一根受影响 qfq 行初始化，不能使用已失真的旧 state。
3. 终点为最新已经存在的趋势通道分区，通常是 `qfq_factor_trade_date` 的上一 expected trade date。
4. 当日 `T` 的普通 update 必须在 repair completion 后执行。
5. 空股票列表只代表 no-op，不得解释为全市场。

### 10.3 Repair Job 与 Sensor

新增：

```text
gold_stock_daily_trend_channel_repair_job
gold_stock_daily_trend_channel_repair_job_sensor
```

Repair sensor 监听 qfq factor repair job 成功：

1. `repair_required=false`：不提交趋势 repair，普通 update sensor 可继续。
2. `repair_required=true` 且范围不超过“趋势 repair 实测自动上限”：提交 scoped repair。
3. 超过趋势自动上限：skip 并给出人工 dry-run/repair 提示，普通 update 继续阻塞。
4. metadata 缺失、truncated、hash 不一致或 upstream batch 不一致：fail closed。

Run key：

```text
build_upstream_triggered_run_key(
  consumer="gold_stock_daily_trend_channel_repair:{formula_version}",
  upstream_batch_id=source_upstream_batch_id,
)

gold_stock_daily_trend_channel_repair:
  {formula_version}:{source_upstream_batch_id}
```

`source_upstream_batch_id` 是 qfq repair 提供的 opaque exact batch，不能用日期或代码 hash 替代。同一 exact batch 与公式版本重复 tick 必须得到同一 key；同一日期、同一代码 hash 但上游 producer run 不同，必须得到不同 key。正式 run key 实现为一行稳定字符串，不加入文件数、时间戳或随机值。

### 10.4 Repair 计算与写入

Repair helper 使用 DuckDB 批量完成：

1. 读取受影响股票在 `[repair_start, repair_end]` 内全部 qfq 分区。
2. 按 `ts_code, trade_date` 严格升序重算四条 EMA 和状态。
3. 读取目标范围内既有结果/state，只保留未受影响股票。
4. 将未受影响股票与新计算的受影响股票合并，生成逐日候选文件。
5. 对所有候选做完整预检后，再按交易日顺序原子替换结果和 state 文件。
6. 所有文件成功后写趋势 repair completion check；中途失败不得写 completion。
7. 重试使用同一 upstream batch 和 scope，幂等重写未完成范围。

正式 Lake 多分区文件没有跨文件事务。为保证最终正确性：

1. repair 期间该 upstream batch 的最新日不对下游标记 ready；
2. 日常 update 和本地 API 的“最新可用日”必须以 repair completion 为界；
3. 如果 repair 中断，恢复任务继续重写同一 scope，完成前不能宣称 repair 成功。

M0 已实测最坏 6158 文件的临时目录原子提升低于 0.9 秒，250 日全市场完整候选链路约 4.6 秒；本地-only 展示没有证明需要“整代文件 + 原子指针”。因此冻结为不新增 manifest 状态实体，继续使用 completion check 隔离未完成 repair。

### 10.5 Repair completion metadata

至少包含：

```text
summary
next_action
formula_version
qfq_factor_trade_date
repair_start_trade_date
repair_end_trade_date
selected_partition_count
repair_required_code_count
repair_required_codes_hash
source_upstream_batch_id
rewritten_indicator_partition_count
rewritten_state_partition_count
rewritten_indicator_row_count
rewritten_state_row_count
producer_run_id
```

完整股票代码列表留在上游 qfq repair check，不在趋势 completion metadata 重复保存。

---

## 11. Checks 与 readiness

### 11.1 生产 checks 的职责

生产 checks 只验证文件和数据合同，不对全分区重新计算 EMA：

#### `gold_stock_daily_trend_channel_contract_check`

1. 文件存在且可读。
2. schema 与列顺序精确一致。
3. `(trade_date, ts_code)` 非空且唯一。
4. 文件中 `trade_date` 全等于 partition key。
5. OHLC 有限、正数且满足高低价关系。
6. `upper >= lower`。
7. position/state/combined_state 枚举合法。
8. `formula_version` 唯一且正确。
9. 行数和代码集合与当日 qfq 输入一致。

#### `gold_stock_daily_trend_channel_state_contract_check`

1. 文件存在、schema 和主键正确。
2. raw state 全部有限且 `upper_raw >= lower_raw`。
3. 枚举和公式版本正确。
4. `state_source_trade_date <= trade_date`。
5. `observed_on_partition=true` 的代码集合等于当日指标代码集合。
6. `observed_on_partition=false` 的行与上一 expected state 精确 carry-forward。
7. State 代码不得超出当日有效股票池。

#### `gold_stock_daily_trend_channel_input_coverage_check`

记录并验证：

```text
expected_stock_count
qfq_observed_stock_count
previous_initialized_stock_count
carried_stock_count
newly_initialized_stock_count
uninitialized_stock_count
output_indicator_stock_count
output_state_stock_count
```

该 check 不要求停牌股票存在指标行，但必须解释 expected pool 与实际 qfq 之间的差异。

### 11.2 公式正确性的职责

公式正确性由受保护的测试金样本保证，不由生产 check 重算：

1. 同一固定 OHLC fixture 分别验证现有指数 Python 公式和新 DuckDB 公式输出一致。
2. 覆盖首值 seed、上下轨严格突破、等于边界、通道内状态保持、`UNKNOWN`、四种组合状态。
3. 覆盖未量化 raw state 继续递推、量化值只用于输出。
4. 覆盖历史全量计算与“上一日 state + 当日增量”逐行一致。
5. 覆盖 repair 后结果与修复后 qfq 全历史重算一致。

生产代码不允许从 `lake_console/orchestrator` 反向依赖 `src.biz`。公式一致性通过静态金样本和测试对账实现，不建立运行时跨子系统依赖。

---

## 12. 历史 Bootstrap

### 12.1 执行模式

历史初始化固定使用：

```text
Direct Lake Bootstrap + Runless Event Backfill
```

原因：

1. 历史交易日可能达到数千个；逐日 Dagster run 会产生大量 run/event 开销。
2. 趋势 state 有严格时间顺序，按连续日期批量计算更高效。
3. 正式文件事实与 Dagster 历史事件可以分阶段校验和登记。

### 12.2 历史股票池

历史 bootstrap 使用 `silver_stock_lifecycle` 按日期判断股票有效范围，不用当前 `silver_stock_basic` 反推历史。

已确认范围：

```text
所有现存 gold_stock_daily_qfq 历史分区
+ 这些分区内出现过的全部股票，包括后来退市股票
```

这样后续长期统计不会因“当前已退市”而丢失历史样本。

### 12.3 Bootstrap 阶段

1. `plan`：只读统计 qfq 日期数、文件数、行数、股票数、生命周期覆盖、目标文件数、冲突文件和空间预算。
2. `sample`：选少量股票和跨状态日期写入 `/private/tmp`，通过公式、schema、state 和 repair 金样本。
3. `benchmark`：在 `/private/tmp` 测量不同日期跨度和股票数的 DuckDB 计算、Parquet 写入、峰值内存和 temp spill。
4. `generate`：按连续日期批次计算，候选写入 `/Volumes/datasource/data_lake_staging`。
5. `audit-files`：聚合核对全部源/目标日期、行数、主键、公式版本和 state 连续性。
6. `promote`：按日期顺序将通过校验的候选原子提升到正式 Lake。
7. `report-events`：只对已经通过物理审计的 asset-partition 写 runless materialization/check events。
8. `final-audit`：核对正式文件、Catalog、事件数和最新 state readiness。

任何正式 bootstrap、runless event 或写湖命令都需要单独审批，不因本文通过而自动授权。

---

## 13. 性能与容量门禁

### 13.1 设计上界

在真实规模审计前，代码按以下硬上界设计，不把它们冒充当前实际数据量：

| 维度 | 设计上界 |
| --- | ---: |
| 单日有效股票池 | 6,500 |
| 单日 qfq 行 | 6,500 |
| 历史交易日 | 10,000 |
| 单资产历史行上界 | 65,000,000 |
| 结果 + state 每日正式文件 | 2 |
| 结果 + state 全历史文件上界 | 20,000 |

M0 已用正式 Lake 只读数据替换未知实际值：3079 个交易日、11,710,697 行、5565 个历史股票代码，最大单日 5547 行；完整证据见 M0 报告。设计上界继续作为 fail-closed 门禁，不因当前实测较低而下调，也不跳过退市股票。

### 13.2 日常热路径预算

| 项 | 预算 |
| --- | --- |
| 外部 API / DB 请求 | 0 |
| Lake 主输入文件 | qfq 1 + previous state 1 + stock basic 1 + stock lifecycle 1 |
| 输出文件 | 2 |
| 输入明细行 | 不超过 26,000 量级 |
| Python 明细循环 | 0 |
| event/check 查询 | 有界，最近 10 个 expected dates，批量读取 latest |
| cursor | 正常小于 2 KB，硬上限 8 KB |

开发拒绝阈值：

1. 单日 qfq 或股票池超过 10,000 行时停止并报告，不静默截断。
2. 日常计算需要扫描全历史 qfq/state 时拒绝实现。
3. DuckDB 峰值内存超过 2 GiB、出现超过 1 GiB temp spill，或单日样本运行超过 120 秒时，必须重新设计后再开发。
4. 每个资产每个交易日只能生成一个正式 `part-000.parquet`，不按股票制造小文件。

这些是编码门禁，不是当前实测 P95。上线前必须在正式 Lake 只读样本上给出中位数、P95、峰值内存、spill 和文件大小。

### 13.3 Repair 预算

Repair 最坏读取行数近似：

```text
affected_codes * affected_trade_dates
```

文件改写数近似：

```text
2 * affected_trade_dates
```

文件数可能比行数更先成为瓶颈。M0 已完成以下实测矩阵：

```text
股票数：1 / 20 / 100 / 500
跨度：1 年 / 5 年 / 全历史
```

每组记录：

```text
source files
source rows
candidate files
candidate bytes
elapsed
peak memory
temp spill bytes
promotion time
```

趋势自动 repair 上限由 M0 实测后取：

```text
min(qfq 自动上限, 趋势 repair 实测安全上限)
```

M0 已验证 500 股票全历史、250 日全市场 segment 和 6158 文件提升均通过门禁，因此冻结：

```text
TREND_AUTO_REPAIR_CODE_LIMIT = min(500, 500) = 500
```

超过 500 必须 fail closed。Sensor 是否启用仍属于后续开发、部署和运营审批，不因 M0 通过而自动启用。

### 13.4 磁盘门禁

Repair/Bootstrap 开始前必须计算：

```text
candidate_bytes
duckdb_temp_budget
formal_lake_free_bytes
staging_free_bytes
```

最低要求：

```text
staging_free_bytes >= 2 * candidate_bytes + duckdb_temp_budget
```

不满足时停止，不允许写一半后再清理正式文件腾空间。

---

## 14. 本地 Wealth 消费

### 14.1 能力边界

股票趋势通道沿用股票分钟线的“本地能力、远程不存在”模式，但使用独立语义开关，不能绑在分钟 API 开关上。

建议新增配置：

| 配置 | 默认 | 持久化/来源 | 作用范围 | 生效方式 |
| --- | --- | --- | --- | --- |
| `WEALTH_LOCAL_LAKE_STOCK_DAILY_TREND_CHANNEL_API_ENABLED` | `false` | env -> `Settings` | 本地股票日线趋势通道 capability、router、page-init | 服务启动时 |
| `GOLDENSHARE_LAKE_ROOT` | 现有，空 | env -> `Settings` | 正式 Lake 根目录 | 服务启动时 |
| `APP_ENV` | 现有 | env -> `Settings` | 只允许 `dev/local` | 服务启动时 |

依赖关系：

```text
APP_ENV in {dev, local}
AND trend channel flag = true
AND GOLDENSHARE_LAKE_ROOT = /Volumes/datasource/data_lake
AND DuckDB dependency available
AND trend result/state roots readable
```

任一不满足：

1. capability 为 false；
2. API router 不挂载；
3. stock detail page-init 不声明支持；
4. 前端不展示或不启用趋势通道入口；
5. 不回退读取 Prod DB 或现算全历史。

该配置必须进入 Settings、能力解析器、router composition、page-init、测试和运维说明；不得只写前端常量。

### 14.2 API 方向

建议本地 API：

```http
GET /api/v1/wealth/market/stock-detail/trend-channel
```

参数：

```text
tsCode  必填
limit   默认 300，最大 2000，与当前股票日线图窗口和既有日线 API 上限对齐
endDate 可选，按交易日因果截断
```

读取规则：

1. 只读 `gold_stock_daily_trend_channel` 正式分区文件。
2. 按 `trade_date DESC` 限定范围后，再按 `trade_date ASC` 返回绘图序列。
3. 不读取内部 state 作为图形结果。
4. 不在 API 中重新计算 EMA 或状态。
5. 遇到正在 repair、缺文件、check 未 ready 或公式版本不匹配时返回结构化 source-not-ready，不返回旧数据冒充最新。

响应字段与现有指数趋势通道尽量保持绘图层可复用，但 `formula.version` 固定为股票版本，标的范围不再限定 `000001.SH`。

### 14.3 代码边界

建议接入点：

```text
src/foundation/clients/local_lake/
  stock_daily_trend_channel_contract.py
  stock_daily_trend_channel_reader.py

src/foundation/config/
  stock_daily_trend_channel_capability.py

src/biz/api/wealth/market/
  stock_detail_trend_channel.py
```

`src.foundation` 只能提供本地 Lake 客户端和 capability，不能依赖 `src.biz`。Router 仍由 `src.app` 组合装配。

前端可以复用现有 `TrendChannelPanePrimitive` 的绘图能力，但不能复用指数专属的标的判断、版本字面量或请求控制器。

---

## 15. 运行链路

### 15.1 普通交易日，无因子变化

```text
06:00 注册趋势分区 T
        ↓
gold_stock_daily_qfq[T] ready
        ↓
qfq factor reconciliation no-op job
        ↓
qfq repair check: repair_required=false
        +
silver_stock_basic + silver_stock_lifecycle fresh for T
        +
trend state[T-1] ready
        ↓
gold_stock_daily_trend_channel_update_job[T]
        ↓
indicator/state checks green
```

### 15.2 因子变化且自动范围安全

```text
gold_stock_daily_qfq[T] ready
        ↓
qfq factor repair job rewrites affected history
        ↓
qfq repair check: repair_required=true + full codes + upstream_batch_id
        ↓
gold_stock_daily_trend_channel_repair_job[S..T-1, codes]
        ↓
trend repair completion green
        ↓
gold_stock_daily_trend_channel_update_job[T]
```

### 15.3 范围超过自动上限

```text
qfq or trend repair scope exceeds measured automatic limit
        ↓
sensor skip with actionable reason
        ↓
trend daily T remains blocked
        ↓
operator dry-run + approved manual scoped repair
        ↓
completion green 后恢复 daily
```

不得通过“先算 T、以后再说”绕过 previous state 正确性。

---

## 16. 观测与诊断

### 16.1 Materialization metadata

日常结果至少记录：

```text
summary
next_action
result_status
partition_key
formula_version
source_qfq_path
source_qfq_row_count
source_qfq_materialization_id 或等价稳定引用
source_qfq_repair_upstream_batch_id
previous_state_path
previous_state_row_count
expected_stock_count
observed_stock_count
carried_stock_count
newly_initialized_stock_count
uninitialized_stock_count
indicator_row_count
state_row_count
candidate_bytes
elapsed_ms
```

### 16.2 Sensor cursor

Cursor 只保存决策前沿：

```text
evaluated_at
decision
target_date
selected_count
blocked_count
reason_code
blocked_component
frontier
```

不得保存股票代码列表、文件路径列表、全历史分区列表或异常堆栈。

### 16.3 Fail-closed reason codes

至少区分：

```text
partition_not_registered
qfq_not_ready
qfq_repair_status_missing
qfq_repair_scope_invalid
stock_basic_not_fresh
stock_lifecycle_not_fresh
previous_state_not_ready
trend_repair_required
trend_repair_scope_exceeds_auto_limit
target_materialized_checks_failed
source_file_missing
formula_version_mismatch
```

---

## 17. 测试与验收

### 17.1 契约与公式测试

1. schema、Catalog、中文名、路径、partition model 和 definition metadata 一致。
2. 指数公式金样本与股票 DuckDB 公式逐行一致。
3. 全历史计算与 state 增量计算一致。
4. 严格突破、边界相等、内部保持和 `UNKNOWN` 全覆盖。
5. State carry-forward 不改变 raw EMA 或状态。

### 17.2 Repair 测试

1. qfq 无因子变化也生成 durable no-op check。
2. `repair_required_codes` 在 0、20、21、500 个代码时完整可用。
3. 501 个代码时自动链路 fail closed，不能只 repair 前 20 个。
4. hash/count/list/truncated 任一不一致时阻塞。
5. Repair 后结果与修复后 qfq 全历史重算一致。
6. 中途失败不写 completion；重试同 scope 幂等完成。
7. 空代码列表不会触发全市场重算。

### 17.3 Sensor 与 continuity 测试

1. 06:00 前不注册，06:00 后只补最早缺失日期，每 tick 最多 2 个。
2. 注册分区不触发计算。
3. qfq、repair、stock basic、previous state 任一未 ready 时不提交 daily。
4. 最早日期阻塞时不越过缺口提交更晚日期。
5. 目标已 materialized 但 check 失败时不自动覆盖。
6. Sensor cursor 小于硬上限且不含代码列表。

### 17.4 文件与性能验收

1. 单日 source rows、result rows、state rows 和物理文件行数对账。
2. 历史 bootstrap 源日期与目标日期无缺口。
3. 无重复主键、无非法枚举、无非有限 state。
4. 日常与 repair benchmark 满足第 13 节门禁。
5. staging 失败不会污染正式文件。

### 17.5 本地 Wealth 验收

1. `dev/local + flag=true + formal lake ready` 时 route 和 capability 可用。
2. 远程环境或 flag=false 时 route 不挂载、前端不展示能力。
3. 不存在 Prod DB fallback。
4. API 不重新计算、不改变 Lake 顺序和公式版本。
5. 股票切换、请求取消、错误降级和现有图层共存通过前端回归。
6. 现有股票分钟线和指数趋势通道能力不回归。

---

## 18. 实施里程碑

### M0：只读规模审计、公式金样本与性能基线

- 状态：已完成并通过，详见 M0 只读规模与性能验证报告。
- 正式 qfq：3079 个交易日、11,710,697 行、5565 个历史股票代码；lifecycle 缺失和越界均为 0。
- 冻结：250 日 segment、自动 repair 上限 500、本地 API 默认 300/最大 2000。
- M0 未写正式 Lake、staging root 或 Dagster event。

### M1：修正 qfq repair 两个现有契约缺口

- 状态：已完成（2026-09-01）。
- 无变化也生成 durable no-op check。
- 完整代码列表与 samples 字段分离。
- 全量消费者审计旧 metadata 口径，21～500 代码回归。
- 已公开统一的 `build_gold_stock_daily_qfq_factor_repair_upstream_batch_id()`；当前 qfq repair sensor 已复用，后续趋势 daily/repair sensor 必须继续复用，禁止自行拼接 batch id。
- `0/1/20/21/500/501` 边界、旧 metadata 拒绝、排序/去重/count/hash 一致性，以及分钟 qfq、MACD/KDJ repair 下游均已通过回归；501 仍 fail closed。
- 截至 M1 停止点，本里程碑未新增趋势资产、配置、实体、check 名称或正式 Lake 写入；M2 新增的合同级 check 名称见下一节。

### M2：数据合同、Catalog、分区和公式 helper

- 状态：已完成（2026-09-01）。
- 已新增结果与 state schema、正式/staging 路径 helper、Catalog 条目、中文名称和独立交易日分区定义；Catalog 当前仅声明合同，不注册尚未实现的资产。
- 已新增不连接数据库、不依赖 Dagster 的纯 DuckDB SQL 公式内核，统一承载 daily、history segment 和 repair segment 三种计划；窗口、衰减、分段上限和日行数上限均由代码常量冻结。
- 已复用 M0 独立字面量金样本，对 1599 行全量结果、249/250/251 分段边界、daily/history/repair 一致性、多股票隔离、等号保持区间内和 `ROUND_HALF_UP` 边界建立保护测试。
- M2 直接合同与公式测试 30 passed；连同 Catalog、check 治理和静态门禁共 152 passed、589 个 subtests passed。
- orchestrator 全量测试为 2485 passed、3 failed；3 项均是既有 major-index history 测试在累计测试进程中 RSS 刚超过 1024 MiB 门禁，该文件在独立新进程 18/18 通过。本里程碑不修改该无关性能门禁。
- 本里程碑未实现 asset/check/job/sensor/bootstrap/repair/API，未写正式 Lake、staging 或 Dagster event；M3 为下一停止点。

### M3：Assets、Checks 与每日写入

- 状态：已完成（2026-09-01）。
- 已实现不可子集化的 result/state `multi_asset`，静态依赖保持为 qfq 同分区映射及 stock basic、lifecycle、trade calendar；previous state 仍由前一 expected date 文件显式承接，不伪造同分区依赖。
- 一个 configured DuckDB connection 内完成输入拒绝、observed 计算、停牌 carry、未初始化统计和两份 run-scoped candidate 写入；单日 qfq/lifecycle 继续执行 10000 行硬门禁，无 Python 股票明细循环。
- `audit_stock_daily_trend_channel_result()`、`audit_stock_daily_trend_channel_state()`、`audit_stock_daily_trend_channel_state_coverage()` 已成为 candidate 与三个 ordinary checks 的唯一审计事实源；正式检查不重算 EMA。
- 提升顺序固定为“两个候选全部通过 -> state -> result”；第二次提升失败时移除正式 state 并恢复本 run state candidate，不发出任何 materialization。
- 已覆盖普通交易日、停牌 carry、新上市未初始化/首次 qfq 初始化、退市半开边界、目标存在、候选失败、第二文件提升失败、qfq 非法输入、previous state 重复/非法 raw/倒挂/版本不一致和三个 checks 正负样本。
- 以冻结上限 5547 条 qfq、5565 条 lifecycle 的本地合成日样本验证完整 writer，result/state 各 5547 行，18 个未初始化代码，端到端 182.202 ms、temp spill 0，低于 120 s/1 GiB 日常门禁。
- M3 直接测试 20 passed；合同、公式、Catalog、治理和静态门禁定向回归 172 passed、593 个 subtests passed；orchestrator 全量回归 2508 passed、853 个 subtests passed，修改文件 Ruff 与 `git diff --check` 通过。
- 本里程碑未实现 Job/Sensor、batch readiness、repair、bootstrap 或 API，未写正式 Lake、staging root 或 Dagster event；M4 为下一停止点。

### M4：06:00 注册与日常 readiness 链

- 状态：已完成（2026-09-01）。
- 已实现默认 `STOPPED` 的 `stock_daily_trend_channel_trade_day_sensor`：上海时间 06:00 后只注册最近 10 个 expected trade dates 中最早两个缺失分区，不提交数据 RunRequest。
- 已实现只选择 result/state 双资产和三个 blocking checks 的 `gold_stock_daily_trend_channel_update_job`。
- 已实现默认 `STOPPED` 的 `gold_stock_daily_trend_channel_update_job_sensor`：按最近 10 个 expected trade dates 选择最早可行动 not-ready 日期，每 tick 最多提交一个 run；已存在但检查失败或部分存在的目标 fail closed，不自动覆盖。
- target readiness 使用真正集合读取：最多扫描 20 个目标文件和一个 previous-state 边界文件，正常路径固定两次 DuckDB SQL，不读取 Dagster instance；M0 冻结规模的 10 日合成样本实测 `elapsed_ms=63`、`slowest_query_ms=60`、`sql_count=2`、`scanned_file_count=21`。
- 单日审计和批量审计共同消费 result/state/coverage 三个共享规则评估内核；批量路径不逐日调用单日重查询函数，并由三组正负 parity 测试锁定等价语义。
- qfq reconciliation 使用目标 qfq 最新成功 materialization 的 producer run id 构造 exact upstream batch；旧 batch 绿色状态不能放行，需要趋势 repair 时在 M5 完成前明确阻断。
- run key 固定为 `gold_stock_daily_trend_channel_update:{trade_date}:{formula_version}`；cursor 正常小于 2 KB，10 日以上窗口在执行 SQL 前拒绝。
- M4 相关合同、公式、M3/M4、qfq repair、Catalog、治理和静态门禁定向回归 `213 passed`、`605` 个 subtests passed。
- orchestrator 全量回归按进程拆分通过：主套件排除既有 RSS 敏感文件后 `2506 passed`、`853` 个 subtests passed，`test_major_index_nineturn_m4b.py` 独立进程 `18 passed`，合计覆盖当前 `2524` 个测试。单进程全量曾因该无关文件读取整个 pytest 进程峰值 RSS（约 1.14 GiB）触发其 1 GiB 门禁而出现 8 个失败；独立重跑证明不是趋势通道回归，本轮未修改无关测试或门禁。
- 本里程碑未实现 M5 repair、M6 bootstrap 或 M7 本地 Wealth，未运行 `dg`、未访问正式 Dagster instance、未写正式 Lake/staging、未启用 Sensor，也未部署。

### M5：趋势 Repair

- 状态：已完成（2026-09-02）。
- 已实现 typed repair config、专属 op/job、默认 `STOPPED` 的 run-status sensor、exact qfq batch 二次校验及 result/state 双 completion checks。
- run key 使用公共 upstream-triggered builder，固定为 `gold_stock_daily_trend_channel_repair:{formula_version}:{source_upstream_batch_id}`；同批次稳定、不同 producer batch 必然不同，不再用日期和代码 hash 代替上游批次身份。
- scoped repair 以最多 250 个交易日为 segment，通过 DuckDB 集合 SQL 重算 affected codes；逐日把 affected 重算结果与 unaffected 正式行合并成完整单文件候选。Python 只编排日期 segment、文件审计和原子提升，不处理行情明细行。
- 全范围候选全部通过 result/state/coverage 和 affected/unaffected 集合差异审计后，才按日期升序执行 state -> result 原子替换；中断保留已提升日期，重试幂等，completion checks 只在全范围最终审计成功后写入。
- 日常 sensor 只有在同一 `source_upstream_batch_id`、范围、代码 count/hash 和公式版本的两个 completion checks 同时通过后才继续 T 日更新；旧批次、缺 check、范围或公式不一致均 fail closed。
- 自动股票范围继续使用 M0 冻结上限 500；501 起不提交自动 repair。未新增配置项、状态实体、数据库或 manifest。
- M5 直接测试 `12 passed`；趋势合同、公式、M3～M5、qfq 与分钟线/MACD-KDJ repair、run contract 定向回归 `284 passed`、`58` 个 subtests；治理/readiness/Definitions 回归 `157 passed`、`593` 个 subtests。
- orchestrator 全量回归按既有 RSS 隔离策略通过：主套件 `2519 passed`、`853` 个 subtests，既有 `test_major_index_nineturn_m4b.py` 独立进程 `18 passed`，合计 `2537 passed`。
- 未运行 `dg`、未访问正式 Dagster instance、未写正式 Lake/staging、未启用 Sensor、未部署；M6 为下一停止点。

### M6：历史 Bootstrap

- 完成 plan/sample/generate/audit/promote/report-events/final-audit 工具链。
- 正式执行仍需单独命令审批。

### M7：本地 Wealth 接入

- 完成配置审计、capability、local Lake reader、API、page-init 和前端绘图接入。
- 远程 capability 缺失与现有分钟线回归验收。

### M8：部署与运营启用

- 由管理员单独批准并执行正式 bootstrap、event backfill、sensor 启用和本地 Wealth 配置。
- 本文不授权 M8 的任何生产动作。

---

## 19. 开发前硬门禁

进入编码前必须全部满足：

1. M0 真实只读规模和性能数据完成，不能只保留设计上界。
2. qfq repair 两个已确认缺口有精确消费者清单和负向测试计划。
3. 公式金样本已冻结，不以现有指数页面截图作为数值合同。
4. 每个资产的 schema、路径、分区、checks、write policy、event policy 和 performance contract 已落到 LLD 具体文件。
5. repair 自动上限有实测依据；没有依据时 sensor 只能保持停止。
6. 本地 Wealth 新配置完成全消费者审计，不能复用语义错误的分钟 API flag。
7. CodeGraph 影响面覆盖 assets、checks、jobs、sensors、catalog、definitions、local capability、router、API、page-init、前端和测试。
8. 当前工作区无关改动有文件白名单保护；不得使用 `git add .`、reset 或全仓格式化。

---

## 20. 风险与控制

| 风险 | 控制 |
| --- | --- |
| 历史 qfq 变化造成未来 state 全部漂移 | 强制从受影响起点向后 repair，不设 25/90 日截断 |
| qfq 无变化没有下游可消费状态 | no-op repair job 写 durable check |
| 21～500 个代码只修前 20 个 | 完整 list 与 sample 字段分离，hash/count/list 一致性门禁 |
| 每日扫描全历史造成性能退化 | 只读 qfq[T] + state[T-1] + stock basic |
| Python 逐股票递推过慢 | DuckDB 向量化 SQL，性能静态门禁 |
| 按股票写小文件 | 每资产每交易日一个分区文件 |
| Bootstrap 产生海量 Dagster run/event | Direct Lake Bootstrap + 聚合审计 + 受控 runless events |
| Repair 多文件无跨文件事务 | staging 全量预检、顺序原子替换、完成 check 作为最终 readiness 门禁 |
| 远程误开放本地 Lake 能力 | `dev/local + explicit flag + formal root` 三重 capability 门禁 |
| 当前股票池用于历史导致退市股票丢失 | 历史 bootstrap 使用 `silver_stock_lifecycle` |
| 停牌日伪造 K 线 | 指标资产不造行情；state 只 carry 内部状态并明确标记 |

---

## 21. 已确认业务口径

以下两个口径已于 2026-09-01 经用户确认，并已进入本技术方案与 LLD 的冻结合同：

1. **历史范围**：覆盖正式 `gold_stock_daily_qfq` 已有全部历史，并通过 `silver_stock_lifecycle` 保留后来退市股票的历史结果；不得只按当前上市股票快照裁剪历史。
2. **停牌日**：指标结果不生成伪造行情行；state 对仍在有效股票池中的已初始化股票 carry-forward，后续市场状态统计读取 state 资产。尚未出现首条有效行情的股票不生成虚假初始 state。

上述口径不再作为开发中的可选项。公式、06:00 只注册、日常 readiness、repair 传播、本地-only Wealth、两个 qfq repair 合同修正同样按本文和 LLD 执行。

---

## 22. 完成定义

只有同时满足以下条件，股票日线趋势通道数据集才可标记完成：

1. 两个 Gold 资产、schema、Catalog、路径、分区和中文名全部一致。
2. 公式金样本、历史计算、日常 state 增量和 repair 全部一致。
3. qfq 无变化和有变化都存在可消费、可追溯的 repair 结论。
4. 每日链路只在所有上游和 previous state ready 后运行。
5. 历史 bootstrap 物理文件和 Dagster 事件完成对账。
6. 性能实测通过，不存在 Python 明细循环、全历史日常扫描或逐股票小文件。
7. 本地 Wealth 可用，远程部署不存在该能力，且无 Prod fallback。
8. 相关文档、LLD、代码、测试和运营启用说明口径一致。

---

## 23. 参考依据

- [Dagster 数据管道性能治理规范](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-data-pipeline-performance-governance.md)
- [Dagster Asset Schema Contract 设计](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-asset-schema-contract-design.md)
- [股票日线趋势通道 Lake 数据集接入 LLD v1](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-daily-trend-channel-dataset-onboarding-low-level-design-v1.md)
- [Local Lake 数据集接入说明模板](/Users/congming/github/goldenshare/docs/templates/lake-dataset-development-template.md)
- [M12 Gold 股票分钟前复权 MACD/KDJ 指标资产设计](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stk-mins-qfq-macd-kdj-indicators-plan.md)
- [上证指数日线趋势通道实时计算方案 v1](/Users/congming/github/goldenshare/docs/architecture/sse-daily-trend-channel-realtime-computation-plan-v1.md)
- `lake_console/orchestrator/src/orchestrator/defs/assets/stock_daily_qfq.py`
- `lake_console/orchestrator/src/orchestrator/defs/stock_daily_qfq.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/gold_stock_daily_qfq_factor_repair_job_sensor.py`
- `lake_console/orchestrator/src/orchestrator/defs/asset_guards/stock_daily_qfq_factor_repair.py`
- `lake_console/orchestrator/src/orchestrator/defs/assets/stock_basic.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/stock_current_trade_day_sensor.py`
- `src/biz/services/quote_trend_channel_calculator.py`
- `src/foundation/config/local_minute_capability.py`
