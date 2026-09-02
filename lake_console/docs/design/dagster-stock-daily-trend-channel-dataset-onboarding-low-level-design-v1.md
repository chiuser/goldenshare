# 股票日线趋势通道 Lake 数据集接入 LLD v1

状态：R0～R8 已完成并关闭；正式历史 result/state、物理审计、runless event、三个 Sensor 和本地 Wealth 真实消费链路已于 2026-09-02 完成对账；远程环境继续按合同不挂载本地 Lake 能力

日期：2026-09-02

上位方案：

- [股票日线趋势通道 Lake 数据集接入技术方案 v1](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-daily-trend-channel-dataset-onboarding-plan-v1.md)

M0 实测基线：

- [股票日线趋势通道 M0 只读规模与性能验证报告](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-stock-daily-trend-channel-m0-readonly-performance-validation-2026-09-01.md)

本文把已确认技术方案拆成可编码、可测试、可验收的低层合同。当前代码、Catalog、Dagster 定义、Lake 路径和现有消费者是事实源；R8 正式动作均在管理员逐命令批准后执行，本文自身不构成后续写湖、runless event、Sensor 或部署授权。

---

## 1. 冻结结论

### 1.1 已确认业务口径

以下口径不再是待选项：

1. 历史范围覆盖正式 `gold_stock_daily_qfq` 的全部已有历史，通过 `silver_stock_lifecycle` 保留后来退市股票的历史结果。
2. 指标资产只生成真实前复权行情行；停牌日不伪造 OHLC 或指标行情。
3. 对生命周期仍有效且已经初始化的股票，state 资产在停牌日精确 carry-forward。
4. 尚无首条有效前复权行情的股票不生成虚假初始 state。
5. 后续按市场状态做统计时读取 state 资产；绘图和行情结果读取指标资产。

股票生命周期统一使用当前代码已采用的半开区间：

```text
list_date <= trade_date < delist_date
```

`delist_date IS NULL` 表示右侧无界。不得由当前上市快照或曾用名数据反推历史生命周期。

### 1.2 资产和运行结论

新增两个非可子集化、同批提交的 Gold 资产：

```text
gold_stock_daily_trend_channel
gold_stock_daily_trend_channel_state
```

运行形态固定为：

```text
每日：qfq[T] + lifecycle/basic + state[T-1] -> result[T] + state[T]
repair：qfq 因子修复范围 -> 受影响股票从历史起点递推至 T-1
bootstrap：全历史 Direct Lake Bootstrap + 受控 Runless Event Backfill
```

每日计算和 repair 都使用 DuckDB 集合计算；禁止 Python 逐股票、逐行情行递推。

### 1.3 本地 Wealth 结论

股票趋势通道只在：

```text
APP_ENV in {dev, local}
AND 独立开关开启
AND Lake root 为 /Volumes/datasource/data_lake
AND 正式趋势结果目录可读
```

时挂载 API 并在 page-init 声明能力。远程不挂载、不展示、不回退 Prod DB，也不请求时现算。

---

## 2. 当前代码审计结论

### 2.1 CodeGraph 审计范围

本轮以仓库根 `/Users/congming/github/goldenshare` 的健康索引为准；R8 收口时同步状态为 3,022 个文件、54,926 个节点、137,397 条边。影响面覆盖：

1. `gold_stock_daily_qfq` 资产、普通 check、repair plan、repair op/job/run-status sensor。
2. `GoldStockDailyQfqFactorRepairStatus` 及 repair metadata 消费者。
3. `silver_stock_basic`、`silver_stock_lifecycle`、`silver_trade_calendar` readiness。
4. 动态分区注册、日常 continuity、batch Lake readiness、Dagster latest-check readiness。
5. Catalog、PartitionModel、ColumnContract、paths、Definitions 自动发现。
6. 本地 Lake capability、`src.app` router 组合、股票详情 page-init/API、Wealth 股票日线图和现有指数趋势绘图层。
7. 相关测试和文档消费者。

依赖边界保持：

```text
orchestrator 自成一体
src.foundation 不依赖 src.biz/src.app
src.biz 可依赖 src.foundation
src.app 只做组合装配
wealth 只消费 API contract
```

不引入 `foundation -> biz/app/ops`、任何模块到 `qtf` 的反向依赖，也不复活 legacy `platform/operations`。

### 2.2 现有公式事实

指数公式当前位于：

```text
src/biz/services/quote_trend_channel_calculator.py
```

冻结语义：

```text
formula_key = high-low-ema-hysteresis
short = EMA(high/low, 25)
long  = EMA(high/low, 90)
seed  = first_observation
close > upper -> UP
close < lower -> DOWN
inside/equality -> retain previous state
```

现有指数实现使用未量化 `float` 递推和判断，最后以 `Decimal(str(value))`、`ROUND_HALF_UP` 量化为 4 位小数。股票实现必须以独立 expected fixture 证明与这一语义逐行一致，不得直接调用业务 API 计算器生成 expected。

### 2.3 上游事实

| 上游 | 当前用途 | 本资产合同 |
| --- | --- | --- |
| `gold_stock_daily_qfq` | 按交易日保存全市场前复权日线 | 唯一价格输入，读取真实 OHLC |
| `silver_stock_basic` | 当前上市 CNY 股票快照 | 当日基础信息完成门禁，不作为历史池 |
| `silver_stock_lifecycle` | 历史 CNY 股票生命周期 | 日常、repair、bootstrap 的日期有效股票池 |
| `silver_trade_calendar` | SSE 开市日事实 | 分区注册、previous expected date、连续性窗口 |

当前 `gold_stock_daily_qfq` 路径为：

```text
/Volumes/datasource/data_lake/gold/quote/stock_daily_qfq/
  trade_date={YYYY-MM-DD}/part-000.parquet
```

### 2.4 qfq repair 已确认缺口

当前代码存在两个必须先修正的契约缺口：

1. `build_gold_stock_daily_qfq_factor_repair_run_status_decision()` 在没有因子变化时直接返回 `no_factor_changed`，不会提交 reconciliation job，因此没有可供下游稳定消费的 durable no-op check。
2. `build_gold_stock_daily_qfq_factor_repair_check_metadata()` 把前 20 个 sample 写入 `repair_required_codes`，但 `_code_scope_is_consistent()` 对自动范围 `<=500` 要求完整列表，二者语义冲突。

受影响消费者至少包括：

```text
defs/sensors/gold_stock_daily_qfq_factor_repair_job_sensor.py
defs/stock_daily_qfq.py
defs/asset_guards/stock_daily_qfq_factor_repair.py
defs/asset_guards/stk_mins_qfq_factor_repair.py
现有 stk_mins_qfq / MACD-KDJ repair guards
未来 stock daily trend-channel repair sensor
```

这两个缺口属于本需求 M1，不得由趋势通道代码本地猜测或兼容旧 metadata。

### 2.5 现有分区与 readiness 事实

1. `cn_a_stock_trade_days` 在现有股票链路中使用，注册窗口不是本需求要求的 06:00。
2. `cn_a_stock_current_trade_days` 在 06:00 后注册，但服务现有当前股票资产族，不能改变其职责。
3. 当前 readiness 已有“最近 10 个 expected dates”“最早 not-ready”“最新 materialization 对应 checks”的治理能力。
4. 新增 batch helper 必须真正一次规划文件、用一条或少量 SQL 聚合，不得复制内部逐日期重 SQL 的伪 batch 模式。

### 2.6 本地 Wealth 事实

1. 股票日线首屏请求 300 根 K 线，后端现有日线 `limit` 上限为 2000。
2. 股票分钟线通过 `dev/local + flag + readable Lake` capability 条件挂载本地路由。
3. 当前股票主图只支持 `MA | BOLL`；指数主图已经有趋势通道请求、geometry 和 `TrendChannelPanePrimitive`。
4. 现有 primitive 的绘图几何可共享，但指数的标的限制、API 类型、版本字面量和 controller 不可由股票直接依赖。

---

## 3. 数据集合同

### 3.1 资产一：结果资产

```text
asset_key       = gold_stock_daily_trend_channel
dataset_id      = stock_daily_trend_channel
layer           = gold
group_name      = quote
data_domain     = quote_data
partition       = cn_a_stock_daily_trend_channel_trade_days
write_policy    = partition_file_atomic_replace
event_policy    = supports_runless_event_backfill
formula_version = stock-daily-trend-channel-v1
```

正式路径：

```text
/Volumes/datasource/data_lake/gold/indicator/stock_daily_trend_channel/
  trade_date={YYYY-MM-DD}/part-000.parquet
```

字段：

| 字段 | DuckDB/Parquet 类型 | 可空 | 用途 |
| --- | --- | ---: | --- |
| `ts_code` | `VARCHAR` | 否 | 股票代码 |
| `trade_date` | `DATE` | 否 | 真实行情日、分区主键 |
| `open` | `DOUBLE` | 否 | 前复权开盘 |
| `high` | `DOUBLE` | 否 | 前复权最高 |
| `low` | `DOUBLE` | 否 | 前复权最低 |
| `close` | `DOUBLE` | 否 | 前复权收盘 |
| `short_upper` | `DOUBLE` | 否 | 量化到 4 位小数后的短上轨 |
| `short_lower` | `DOUBLE` | 否 | 量化到 4 位小数后的短下轨 |
| `short_position` | `VARCHAR` | 否 | `ABOVE/INSIDE/BELOW` |
| `short_state` | `VARCHAR` | 否 | `UNKNOWN/UP/DOWN` |
| `long_upper` | `DOUBLE` | 否 | 量化到 4 位小数后的长上轨 |
| `long_lower` | `DOUBLE` | 否 | 量化到 4 位小数后的长下轨 |
| `long_position` | `VARCHAR` | 否 | `ABOVE/INSIDE/BELOW` |
| `long_state` | `VARCHAR` | 否 | `UNKNOWN/UP/DOWN` |
| `combined_state` | `VARCHAR` | 否 | 组合状态 |
| `formula_version` | `VARCHAR` | 否 | 固定公式版本 |

主键：

```text
(trade_date, ts_code)
```

正式文件按 `ts_code ASC` 排序。该资产只包含当日 qfq 真实行情行；停牌股票不得出现。

### 3.2 资产二：state 资产

```text
asset_key       = gold_stock_daily_trend_channel_state
dataset_id      = stock_daily_trend_channel_state
layer           = gold
group_name      = quote
data_domain     = quote_data
partition       = cn_a_stock_daily_trend_channel_trade_days
write_policy    = partition_file_atomic_replace
event_policy    = supports_runless_event_backfill
formula_version = stock-daily-trend-channel-v1
```

正式路径：

```text
/Volumes/datasource/data_lake/gold/indicator/stock_daily_trend_channel_state/
  trade_date={YYYY-MM-DD}/part-000.parquet
```

字段：

| 字段 | DuckDB/Parquet 类型 | 可空 | 用途 |
| --- | --- | ---: | --- |
| `ts_code` | `VARCHAR` | 否 | 股票代码 |
| `trade_date` | `DATE` | 否 | state 快照日期 |
| `state_source_trade_date` | `DATE` | 否 | 最近一次真实行情日 |
| `observed_on_partition` | `BOOLEAN` | 否 | 本分区是否有真实 qfq 行 |
| `short_upper_raw` | `DOUBLE` | 否 | 精确递推短上轨 |
| `short_lower_raw` | `DOUBLE` | 否 | 精确递推短下轨 |
| `short_state` | `VARCHAR` | 否 | 短通道状态 |
| `long_upper_raw` | `DOUBLE` | 否 | 精确递推长上轨 |
| `long_lower_raw` | `DOUBLE` | 否 | 精确递推长下轨 |
| `long_state` | `VARCHAR` | 否 | 长通道状态 |
| `combined_state` | `VARCHAR` | 否 | 组合状态 |
| `formula_version` | `VARCHAR` | 否 | 固定公式版本 |

主键：

```text
(trade_date, ts_code)
```

正式文件按 `ts_code ASC` 排序。

state 行集合定义：

```text
observed_rows
UNION ALL
previous_initialized_state
  ANTI JOIN current_qfq
  INNER JOIN lifecycle_valid_on_T
```

对 carry 行：

```text
trade_date               = T
state_source_trade_date  = previous.state_source_trade_date
observed_on_partition    = false
raw EMA/state            = previous 值逐位保持
```

对真实行情行：

```text
trade_date               = T
state_source_trade_date  = T
observed_on_partition    = true
raw EMA/state            = 本日计算结果
```

### 3.3 不落库字段

以下内容不进入结果或 state Parquet：

1. `created_at/updated_at/fetched_at` 等系统字段。
2. 股票名称、行业、地区等可从基础资产派生的展示字段。
3. repair run id、Dagster storage id、候选文件路径。
4. 公式中间窗口序号、breakout event、pow 权重。
5. 买卖信号、预测、胜率。

### 3.4 源请求与归一化口径

这是纯派生数据集：

```text
外部 API 请求数 = 0
Tushare 分页数   = 0
Prod DB 请求数  = 0
```

日常验收计数必须记录：

```text
qfq_source_row_count
lifecycle_valid_code_count
previous_initialized_state_count
observed_state_row_count
carried_state_row_count
uninitialized_lifecycle_code_count
result_output_row_count
state_output_row_count
```

必须满足：

```text
result_output_row_count = qfq_source_row_count
state_output_row_count
  = observed_state_row_count + carried_state_row_count
lifecycle_valid_code_count
  = state_output_row_count + uninitialized_lifecycle_code_count
```

任何不等式必须给出 reason code 和样本，不能当作正常 reject 跳过。

---

## 4. Schema、路径和 Catalog 落点

### 4.1 文件修改

| 文件 | 改动 |
| --- | --- |
| `defs/run_contracts/asset_column_schemas.py` | 新增两个 `ColumnContract` tuple |
| `defs/paths.py` | 新增两个正式路径和 run-scoped staging 路径 helper |
| `defs/catalog/lake_assets.py` | 新增两个 PartitionModel、definition、check 列表和 Catalog entry |
| `defs/catalog/name_mapping.py` | 在 `DATASET_CHINESE_NAMES` 增加两个资产中文名，不建第二套 registry |
| `defs/partitions.py` | 新增独立动态分区定义 |

### 4.2 PartitionModel

新增：

```text
TRADE_DATE_PARTITION_GOLD_STOCK_DAILY_TREND_CHANNEL
TRADE_DATE_PARTITION_GOLD_STOCK_DAILY_TREND_CHANNEL_STATE
```

两者定义固定：

```text
family                      = trade_date_partition
layer                       = gold
asset_family                = stock_daily_trend_channel
dagster_partition_dimension = trade_date
physical_layout             = partition_file
```

### 4.3 Catalog entry

两个 entry 都使用：

```text
ingestion_source       = derived_from_assets
compute_engine         = duckdb_sql
python_row_loop_allowed = false
source_request_policy  = read_upstream_assets_only
event_policy           = supports_runless_event_backfill
```

结果资产的 `data_contract`：

```text
gold_stock_daily_qfq_trend_channel
```

state 资产的 `data_contract`：

```text
gold_stock_daily_qfq_trend_channel_state
```

### 4.4 Staging 路径

候选文件只允许位于：

```text
/Volumes/datasource/data_lake_staging/
  gold/indicator/{dataset}/run_id={normalized_run_id}/
    trade_date={YYYY-MM-DD}/part-000.parquet
```

路径 helper 必须拒绝：

1. 空 run id。
2. `/`、`..` 或越界路径片段。
3. 非 ISO 日期分区键。
4. 把 staging root 解析为正式 Lake root。

正式计算不得在 `/Volumes/datasource/data_lake` 下创建 `_staging`。不得读取或写入旧 `/Volumes/datasource/goldenshare-tushare-lake`，不得调用 Kopia。

---

## 5. 公式实现合同

### 5.1 新模块

新增：

```text
lake_console/orchestrator/src/orchestrator/defs/stock_daily_trend_channel.py
```

该模块只包含：

1. 公式常量和类型。
2. 日常、历史 segment、repair 的 SQL builder。
3. 纯审计 helper。
4. candidate write/promotion 结果对象。

Dagster context、instance、RunRequest、SensorResult 不得进入公式模块。

### 5.2 常量

```text
FORMULA_KEY                 = high-low-ema-hysteresis
FORMULA_VERSION             = stock-daily-trend-channel-v1
SHORT_PERIOD                = 25
LONG_PERIOD                 = 90
SHORT_ALPHA                 = 2.0 / 26.0
LONG_ALPHA                  = 2.0 / 91.0
SEGMENT_TRADE_DAY_LIMIT     = 250
DAILY_SOURCE_ROW_HARD_LIMIT = 10000
```

这些是代码常量，不新增 env、Settings、数据库配置或页面参数。M0 已证明 250 日 segment 满足资源门禁并将其冻结；未来若正式数据规模使其失效，必须先更新技术方案与 LLD，不能在代码中静默改值。

### 5.3 日常递推

对 T 的每个 qfq 行：

```text
如果 previous state 存在：
  ema_T = alpha * x_T + decay * ema_(T-1)
否则：
  ema_T = x_T
```

状态判断必须基于未量化 raw band：

```text
close > upper_raw -> ABOVE, state=UP
close < lower_raw -> BELOW, state=DOWN
otherwise         -> INSIDE, state=previous state or UNKNOWN
```

不得用 4 位小数轨道判断突破，也不得把量化值写回下一日 state。

### 5.4 历史和 repair 的集合 EMA

历史/repair 以 `ts_code, trade_date` 排序，并按最多 250 个交易日的 segment 计算。设：

```text
d = 1 - alpha
n = segment 内从 1 开始的观测序号
```

有前置 seed `E0` 时：

```text
E_n = d^n * (E0 + alpha * SUM(x_j / d^j, j=1..n))
```

没有前置 seed 时，第一条观测作为 seed：

```text
E_1 = x_1
E_n = d^(n-1) * (
        x_1 + alpha * SUM(x_j / d^(j-1), j=2..n)
      )
```

每个 segment 的最后一条 state 是下一 segment 的 seed。segment 只控制数值稳定性、内存和恢复粒度，不改变公式起点。

状态传播使用 DuckDB 窗口能力：

```sql
last_value(breakout_state IGNORE NULLS)
OVER (
  PARTITION BY ts_code
  ORDER BY trade_date
  ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
)
```

前置 state 作为 seed；无 seed 且没有 breakout 时为 `UNKNOWN`。禁止 Python 循环维护每只股票 state。

### 5.5 量化

候选 SQL 使用 Decimal 中间值实现四舍五入：

```sql
CAST(ROUND(CAST(raw_value AS DECIMAL(38, 18)), 4) AS DOUBLE)
```

它只有在 golden test 对所有边界样本与：

```python
Decimal(str(raw_value)).quantize(Decimal("0.0001"), ROUND_HALF_UP)
```

按 `Decimal(str(output_value))` 还原后逐值相等，才可进入正式实现。若存在差异，停止编码并修订数值表达式；不得用宽容差放宽已序列化的 4 位小数合同。

### 5.6 输入拒绝规则

任一输入出现以下情况时整批失败：

1. `(trade_date, ts_code)` 重复。
2. OHLC 为空、非有限数或非正数。
3. `low > min(open, close)`、`max(open, close) > high`。
4. qfq code 不在 T 的 lifecycle 有效范围。
5. previous state 公式版本不一致。
6. previous state 同 code 重复或 raw 值非法。
7. short/long upper 小于 lower。

不得删除坏行后继续生成部分结果。

---

## 6. 日常资产执行

### 6.1 Asset 定义

新增：

```text
defs/assets/stock_daily_trend_channel.py
```

使用不可子集化的 `@dg.multi_asset`，声明两个 `AssetSpec`。二者共享同一 `cn_a_stock_daily_trend_channel_trade_days` 分区；一次 run 必须同时生成 result 和 state。

静态依赖：

```text
gold_stock_daily_qfq
  partition_mapping = dg.IdentityPartitionMapping()

silver_stock_basic
silver_stock_lifecycle
silver_trade_calendar
```

previous state 是动态分区上的前一 expected date 文件依赖，当前 Dagster 动态分区不能用时间窗口 mapping 准确表达；由 planner、readiness 和 asset 执行前置检查共同约束，不伪造静态 same-partition 依赖。

### 6.2 前置计划

分区 T 执行前：

1. 从 `silver_trade_calendar` 确认 T 是 SSE 开市日。
2. 取得 T 的前一 expected trade date P。
3. 要求 qfq[T]、stock basic、lifecycle 文件存在且正式 readiness 已通过。
4. 如果 T 不是全历史首个 qfq 日期，要求 state[P] 存在且 readiness 通过。
5. 要求 qfq T 对应的 reconciliation 状态存在且属于精确 upstream batch。
6. 如果 reconciliation 表示历史重写，要求同 batch 的趋势 repair completion 通过。
7. result[T] 或 state[T] 任一正式目标已存在时，不自动覆盖；返回 blocked，交人工 repair。

### 6.3 一次计算

在一个 configured DuckDB connection 内：

1. 读取 qfq[T] 所需列。
2. 读取 lifecycle，生成 T 的有效代码集合。
3. 读取 state[P]；首个历史分区允许为空。
4. 生成 observed result/state。
5. 生成 carry state。
6. 生成未初始化 code 统计和样本。
7. 把两个完整输出分别 `COPY` 到 run-scoped staging。
8. 对两个候选执行纯审计 helper。

不得 `fetchall()` 全市场明细；只允许获取聚合计数和有界错误样本。

### 6.4 双文件提升

每日新分区目标在写前必须都不存在。提升顺序：

```text
validate both
-> os.replace(state candidate, state target)
-> os.replace(result candidate, result target)
-> yield state materialization
-> yield result materialization
```

如果第二个 `os.replace` 失败：

1. 删除本 run 刚创建且尚未发出 materialization event 的 state target。
2. 保留 staging 和错误诊断。
3. 整个 run 失败，不发出任何一个资产的成功 materialization。

清理只允许针对本 run 已验证的精确文件，不得递归删除正式目录。

### 6.5 Materialization metadata

两个资产 metadata 至少包含：

```text
partition_key
formula_key
formula_version
qfq_source_path
previous_state_path
stock_basic_path
stock_lifecycle_path
source_row_count
output_row_count
observed_state_row_count
carried_state_row_count
uninitialized_lifecycle_code_count
candidate_bytes
elapsed_ms
peak_memory_bytes（可观测时）
temp_spill_bytes
```

不得把完整股票代码列表或完整文件清单写入 metadata。

---

## 7. Blocking checks 与 Lake readiness

### 7.1 正式 checks

新增：

```text
defs/checks/stock_daily_trend_channel_checks.py
```

三个 blocking checks：

1. `gold_stock_daily_trend_channel_contract_check`
2. `gold_stock_daily_trend_channel_state_contract_check`
3. `gold_stock_daily_trend_channel_input_coverage_check`

### 7.2 Result contract check

验证：

1. 文件存在、单文件、路径分区与 `trade_date` 一致。
2. schema 名称、顺序、DuckDB 类型与 ColumnContract 一致。
3. 主键唯一、关键字段非空。
4. OHLC 合法，通道不倒挂。
5. position/state/combined_state 枚举合法且组合一致。
6. `formula_version` 唯一且正确。
7. 结果 code/date 与 qfq[T] 一一相等。

不重算 EMA。

### 7.3 State contract check

验证：

1. 文件、schema、主键、非空和公式版本。
2. raw 值有限、正数、上下轨不倒挂。
3. state/combined state 枚举一致。
4. `state_source_trade_date <= trade_date`。
5. `observed_on_partition=true` 时 `state_source_trade_date=trade_date`。
6. state code 全部属于 T 的 lifecycle 有效范围。

### 7.4 Input coverage check

同一条聚合 SQL 计算：

```text
expected_lifecycle_count
qfq_observed_count
previous_initialized_count
expected_carry_count
actual_observed_state_count
actual_carry_state_count
uninitialized_count
missing_state_count
unexpected_state_count
```

核心等式：

```text
actual observed state = qfq rows
actual carry state    = previous initialized lifecycle-valid codes anti current qfq
actual state          = observed + carry
expected lifecycle    = actual state + uninitialized
```

### 7.5 复用原则

单日文件读取入口保持为：

```text
audit_stock_daily_trend_channel_result(...)
audit_stock_daily_trend_channel_state(...)
audit_stock_daily_trend_channel_state_coverage(...)
```

它们由：

1. candidate validator；
2. 正式 asset checks；
3. bootstrap final audit

共同调用。

M4 实现审计确认：上述函数均为单日、多查询包装，若 batch Lake readiness 在 10 日窗口逐日直接调用，会与 8.5 的真正集合读取门禁冲突。经 2026-09-01 拍板，复用合同澄清为：

```text
单日读取 SQL ─┐
              ├─> shared result/state/coverage rule evaluation kernel
批量集合 SQL ─┘
```

共享规则评估内核固定为：

```text
evaluate_stock_daily_trend_channel_result_rules(...)
evaluate_stock_daily_trend_channel_state_rules(...)
evaluate_stock_daily_trend_channel_coverage_rules(...)
```

单日审计与批量 readiness 必须共同调用这些纯评估函数，由它们唯一维护规则名称、失败计数映射和 coverage 派生等式；批量路径保留集合 SQL，不得回调单日重查询包装。result/state/coverage 各有一组 parity 负向测试，保证两条读取路径对同一坏文件给出相同非零规则计数。不得在任一路径另建规则名称或通过判定。

### 7.6 Check metadata

失败 metadata 固定为：

```text
summary
next_action
checked_row_count
failed_row_count
failure_rule_counts
failure_samples（每规则最多 20）
source_row_count
output_row_count
formula_version
```

公式正确性由 golden tests 负责，production checks 不实现第二套全量公式计算器。

---

## 8. 动态分区、Job 和 Sensor

### 8.1 分区定义

`defs/partitions.py` 新增：

```python
cn_a_stock_daily_trend_channel_trade_days = dg.DynamicPartitionsDefinition(
    name="cn_a_stock_daily_trend_channel_trade_days"
)
```

### 8.2 06:00 注册 Sensor

新增：

```text
defs/sensors/stock_daily_trend_channel_trade_day_sensor.py
sensor name = stock_daily_trend_channel_trade_day_sensor
```

合同：

```text
default_status                 = STOPPED
minimum_interval_seconds       = 600
timezone                       = Asia/Shanghai
same_day_register_start        = 06:00
max_partitions_per_tick        = 2
default_expected_window        = 10
role                           = partition_registration
job                            = none
```

只返回 dynamic partition add request，不返回 RunRequest。该类分区注册 sensor 按现有仓库惯例允许没有对应 job，因此不强行追加 `_job_sensor`。

### 8.3 每日 Job

新增：

```text
defs/jobs/stock_daily_trend_channel_update.py
job name = gold_stock_daily_trend_channel_update_job
```

selection 同时包含两个 assets 和三个 blocking checks。

### 8.4 每日 readiness Sensor

新增：

```text
defs/sensors/stock_daily_trend_channel_sensor.py
sensor name = gold_stock_daily_trend_channel_update_job_sensor
```

合同：

```text
default_status           = STOPPED
minimum_interval_seconds = 600
job                      = gold_stock_daily_trend_channel_update_job
window                   = 最近 10 个 expected trade dates
selection                = 最早可行动 not-ready 日期
max RunRequest/tick      = 1
```

热路径顺序固定：

1. Lake root 可用。
2. expected dates 和分区注册轻量连续性。
3. 批量 target Lake readiness。
4. 选出最早 not-ready 日期 T。
5. 如果 target 已存在但 check 失败，fail closed，不覆盖。
6. 只对 T 查询 qfq、stock basic、lifecycle 的最新 Dagster readiness。
7. 检查 state[P]。
8. 读取 qfq[T] 最新成功 materialization 的 producer run id，复用公共 builder 和相邻因子 repair plan 构造 expected qfq reconciliation upstream batch id。
9. 用该 expected id 检查 qfq reconciliation exact upstream batch；旧 batch 的绿色 check 不能放行。
10. 如需 repair，检查 trend repair completion。
11. 防重后提交一个 RunRequest。

### 8.5 真正的 batch target readiness

新增：

```text
defs/asset_guards/stock_daily_trend_channel_lake_readiness.py
batch_gold_stock_daily_trend_channel_readiness(...)
```

要求：

1. 一次规划窗口内最多 10 个日期的 result/state 路径。
2. 最多扫描 20 个 target 文件，必要时加一个 previous state 边界文件。
3. 用一条或少量 SQL 按 `trade_date` 聚合正式 check 的等价语义。
4. 不在 Python 日期循环中逐日执行重 SQL。
5. 不读取 Dagster instance。
6. 返回每个日期的小型 `DatasetReadinessStatus` 和整体性能统计。

必须记录：

```text
sql_count
scanned_file_count
elapsed_ms
slowest_query_ms
window_date_count
```

文件存在或 row count 大于零只能粗筛，不能独立判定 ready。

### 8.6 Cursor

cursor 复用现有统一 builder，只保存：

```text
schema_version
evaluated_at
reason_code
selected_trade_date
continuity frontier
小型 upstream/repair/readiness 摘要
batch performance summary
```

正常目标 `<2 KB`，硬上限 `8 KB`。禁止保存完整代码列表、完整路径清单、SQL 或全窗口检查明细。

### 8.7 Run key

每日 run key 必须由以下事实稳定生成：

```text
gold_stock_daily_trend_channel_update:{T}:{formula_version}
```

同一分区与公式版本重复 tick 必须得到同一 run key。qfq upstream batch 进入 materialization/check metadata 和 readiness 精确校验，但不扩展日常 run key；已存在目标发生上游修订时走 repair，不由日常 job 覆盖。

---

## 9. qfq reconciliation 契约修正

### 9.1 无变化也提交 reconciliation job

修改：

```text
defs/sensors/gold_stock_daily_qfq_factor_repair_job_sensor.py
defs/stock_daily_qfq.py
```

当 `repair_required=false` 且 qfq[T] ordinary readiness 通过时：

1. 仍按空代码列表 hash 构造 `upstream_batch_id`。
2. 返回 `selected_for_repair` 等价的“selected_for_reconciliation”决策并提交现有 repair job。
3. op 不重写 qfq 文件，只发出 `gold_stock_daily_qfq_factor_repair_plan_evaluated` check。
4. check metadata 中 rewritten partition/row count 都为 0。

同时把 sensor 内私有 batch builder 收敛为纯公共函数：

```text
build_gold_stock_daily_qfq_factor_repair_upstream_batch_id(
  producer_run_id,
  target_trade_date,
  repair_required_codes_hash,
)
```

qfq repair sensor、趋势 daily sensor 和趋势 repair sensor必须复用同一函数；不得各自拼 batch id。

不能在 sensor 中伪造 check event，也不能让趋势 daily sensor 把“没有 check”解释成“无需 repair”。

### 9.2 完整代码范围和样本分离

修改：

```text
defs/stock_daily_qfq.py
defs/asset_guards/stock_daily_qfq_factor_repair.py
```

自动范围 `repair_required_code_count <= 500`：

```text
repair_required_codes            = 完整、有序、去重代码列表
repair_required_code_samples     = 前 20 个
repair_required_codes_truncated  = false
```

超过 500：

```text
repair_required_codes            = []
repair_required_code_samples     = 前 20 个
repair_required_codes_truncated  = true
```

同时保留：

```text
repair_required_code_count
repair_required_codes_hash
```

guard 对 `<=500` 必须验证 list 长度、排序、去重、count/hash 一致；对 `>500` 必须 fail closed，不得自动执行。

### 9.3 旧消费者清零

全仓检索并更新所有把 `repair_required_codes` 当 sample 的消费者。测试必须覆盖代码数：

```text
0 / 1 / 20 / 21 / 500 / 501
```

不保留“字段可能是全量也可能是 sample”的兼容分支。

---

## 10. 趋势 repair

### 10.1 触发和范围

新增：

```text
defs/ops/gold_stock_daily_trend_channel_repair.py
defs/jobs/gold_stock_daily_trend_channel_repair.py
defs/sensors/gold_stock_daily_trend_channel_repair_job_sensor.py
defs/asset_guards/stock_daily_trend_channel_repair.py
```

Job/sensor：

```text
job    = gold_stock_daily_trend_channel_repair_job
sensor = gold_stock_daily_trend_channel_repair_job_sensor
sensor default_status = STOPPED
```

输入来自 qfq reconciliation check 的完整范围：

```text
qfq_factor_repair_trade_date = T
affected_codes               = exact list
source_upstream_batch_id     = exact batch
```

Run key 必须使用公共 upstream-triggered builder：

```python
build_upstream_triggered_run_key(
    consumer=f"gold_stock_daily_trend_channel_repair:{FORMULA_VERSION}",
    upstream_batch_id=source_upstream_batch_id,
)
```

固定输出：

```text
gold_stock_daily_trend_channel_repair:{formula_version}:{source_upstream_batch_id}
```

`qfq_factor_repair_trade_date` 和 `repair_required_codes_hash` 是 run config/metadata 中的执行与审计事实，不能代替 exact upstream batch 进入 run key。测试必须证明：同一批次重复求值 key 不变；同日同 hash 但 `source_upstream_batch_id` 不同，key 必须不同；公式版本变化也必须生成新的下游执行身份。

对每只 affected code，repair 起点是 qfq repair 已声明的最早重写日期；结束日期是 T 之前最后一个 expected trade date。不能只重算 25/90 日。

### 10.2 自动范围

```text
TREND_AUTO_REPAIR_CODE_LIMIT
  = 500
```

M0 已实测 500 股票全历史计算、250 日全市场 segment 和 6158 文件提升，趋势安全上限为 500；与 qfq 上限取最小值后仍为 500。该值必须以代码常量落地，不新增配置。Sensor 是否启用仍由后续开发、部署和运营审批决定。

超过上限：

1. 不提交自动 repair。
2. cursor 标记 `repair_scope_exceeds_auto_limit`。
3. 要求离线 dry-run 和单独批准。

### 10.3 计算方式

repair 按日期 segment 读取所有 affected codes 的 qfq 行，使用第 5.4 节集合公式；Python 只编排 segment、文件和 promotion，不处理明细行。

对每个受影响日期：

1. 将重新计算的 affected result 行与正式 result 中未受影响行合并。
2. 将重新计算/carry 的 affected state 行与正式 state 中未受影响行合并。
3. 写出两个完整单文件候选，而不是 delta 文件。
4. 验证完整 partition contract 和 affected scope。

若某 changed code 在 T 前没有 qfq 历史，可以产生零分区 repair completion；当日 T 仍由正常 daily 首次初始化。

### 10.4 批量候选和单文件合同

DuckDB 的 `COPY ... PARTITION_BY` 可能按线程在一个分区目录产生多个文件，不能直接写正式 `part-000.parquet`。

实现固定为：

1. segment 结果先进入 run-scoped DuckDB 临时表。
2. 可以用 `PARTITION_BY` 写 run-scoped staging chunks 以减少重复计算。
3. 每个日期必须从本日期 chunks/临时结果归并为唯一 `part-000.parquet` candidate。
4. 只有 candidate 通过 schema/key/coverage 审计后才可提升。

任何直接把多 chunk staging 目录改名成正式分区的实现都应被静态测试拒绝。

### 10.5 多文件提升与失败语义

Lake/Parquet 没有跨日期、跨文件事务。repair 采用：

```text
全范围 staging 生成
-> 全范围候选预检
-> 按日期升序，每日 state 后 result 原子替换
-> 全范围最终审计
-> 最后写 completion checks
```

中途失败时：

1. 不写 completion checks。
2. daily sensor 因 exact batch completion 缺失而 fail closed。
3. 已提升日期保留，不做 Kopia 恢复或全目录回滚。
4. 使用同一 scope 的确定性 retry 重新生成并替换 affected rows。
5. completion 前再次对全部覆盖日期做统一审计。

### 10.6 Completion checks

通过 runless `AssetCheckEvaluation` 或 job 内正式 evaluation 为两个资产分别写：

```text
gold_stock_daily_trend_channel_factor_repair_completion_check
gold_stock_daily_trend_channel_state_factor_repair_completion_check
```

metadata 至少包含：

```text
qfq_factor_repair_trade_date
covered_start_trade_date
covered_end_trade_date
repair_required_code_count
repair_required_codes_hash
source_upstream_batch_id
formula_version
rewritten_partition_count
rewritten_result_row_count
rewritten_state_row_count
```

guard 必须同时验证两个 checks、partition、batch、日期范围、code count/hash 和公式版本完全一致。

---

## 11. 历史 Bootstrap

### 11.1 新增工具

新增独立模块和 CLI：

```text
defs/bootstrap/stock_daily_trend_channel_history.py
defs/bootstrap/stock_daily_trend_channel_history_cli.py
defs/bootstrap/stock_daily_trend_channel_runless_events.py
defs/bootstrap/stock_daily_trend_channel_runless_events_cli.py
```

物理写湖和 event backfill 必须分开命令；不能一次命令既写正式文件又写 Dagster 事件。

### 11.2 阶段

```text
plan
sample
benchmark
generate
audit-files
promote
report-events
final-audit
```

每阶段默认 dry-run。`apply` 必须要求精确计划 id、计划 hash、范围和管理员单独批准。

### 11.3 Plan 输出

至少输出：

```text
qfq_min/max_trade_date
qfq_partition_count
qfq_file_count
qfq_row_count
distinct_ts_code_count
delisted_history_code_count
lifecycle_missing_code_count
target_partition_count
target_result/state_file_count
conflicting_target_file_count
estimated_candidate_bytes
estimated_duckdb_temp_bytes
formal_free_bytes
staging_free_bytes
estimated_materialization_event_count
estimated_check_event_count
plan_hash
```

历史范围只能由全部正式 qfq 分区推导，不能由当前股票池裁剪。

### 11.4 生成和恢复

1. 按 250 个交易日 segment 计算全市场。
2. 每个 segment 先完成 result/state staging 和审计。
3. checkpoint 只记录已完成 segment、精确文件和 hash，不记录明细行。
4. 恢复时重新验证 checkpoint 对应候选；不可信候选必须重算。
5. 正式提升按日期升序进行。

不得把 checkpoint 写入正式 Lake，也不新增状态数据库或 manifest 资产。

### 11.5 Runless events

在全部正式文件物理对账通过后：

1. 先把批准范围内尚未登记的日期批量加入 `cn_a_stock_daily_trend_channel_trade_days`；sample 只登记 sample 日期，full apply 登记剩余日期。登记数量不得超过批准分区数。
2. 为两个资产的每个已提升分区报告 materialization event。
3. ordinary check event 只补最近 20 个 expected dates加最新日期，去重后最多 21 个分区。
4. check event 必须绑定对应 materialization storage id。
5. dry-run 先输出 exact partition registration、materialization 和 check event 数量及范围。
6. 不存在物理 materialization 的分区不得报告 check。
7. event checkpoint 和审阅报告必须位于正式 Lake 与候选 staging 之外；event 模块不得导入候选写入路径或修改任何正式文件。

event 上限：

```text
materialization <= 2 * approved_partition_count
ordinary checks <= 21 * 3
```

超出 plan 批准数即停止。

---

## 12. 性能门禁

### 12.1 M0 必须先完成

编码前必须以正式 Lake 只读方式给出：

```text
历史日期数、文件数、行数、股票数
平均/最大单日 qfq 行数和文件大小
lifecycle 覆盖和退市历史代码数
每日 1 日计算耗时/内存/spill
repair 1/20/100/500 股票 × 1年/5年/全历史
bootstrap segment 计算和写文件成本
本地 API 300/2000 行读取耗时
```

M0 只允许 `/private/tmp` 样本输出和只读正式 Lake；不得写正式 Lake、staging root 或 Dagster event。

M0 已于 2026-09-01 完成并通过，冻结结果为：

```text
qfq partitions / rows / codes = 3079 / 11,710,697 / 5565
max daily qfq rows            = 5547
segment trade days            = 250
trend auto repair code limit  = 500
local API limit               = default 300, max 2000
```

完整矩阵、峰值内存、spill、文件提升和磁盘证据见 M0 报告。开发不得用新的未测常量替换这些冻结值。

### 12.2 日常硬预算

| 项 | 硬门禁 |
| --- | ---: |
| qfq 行或 lifecycle pool | `<= 10,000` |
| 正式输入文件 | qfq 1 + previous state 0/1 + basic 1 + lifecycle 1 |
| 正式输出文件 | 2 |
| Python 明细循环 | 0 |
| 全历史扫描 | 0 |
| DuckDB peak memory | `<= 2 GiB` |
| temp spill | `<= 1 GiB` |
| 单日样本 elapsed | `<= 120 s` |

超过任一阈值时 fail closed，不截断、不降级、不切换 Python。

### 12.3 Sensor 热路径预算

| 项 | 门禁 |
| --- | ---: |
| expected window | 10 个交易日 |
| target files | 最多 20，另加有界 previous-state 边界文件 |
| RunRequest | 每 tick 最多 1 |
| cursor | 正常 `<2 KB`，硬上限 `8 KB` |
| 10 日 batch fixture | `<5,000 ms` 工程门禁 |

`5,000 ms` 是开发工程门禁，不冒充当前生产 P95。M0 已完成可独立验证的正式文件规模和 API 有界读取基线；趋势 Sensor 尚未实现，真实 10 日中位数/P95 必须在 R4 实现后、启用前补测。P95 超过 5 秒时先重构读取模型，不启用 Sensor。

### 12.4 Repair benchmark

每组记录：

```text
affected code count
trade date count
source file/row count
candidate file/byte count
DuckDB SQL count
elapsed
peak memory
temp spill
promotion elapsed
```

自动上限必须来自测量；不得只因为 qfq 上限是 500 就把趋势上限设为 500。

### 12.5 磁盘门禁

```text
staging_free_bytes
  >= 2 * candidate_bytes + duckdb_temp_budget
```

正式 Lake free bytes 也必须覆盖新增正式文件和安全余量。空间不足时在写候选前停止；不得删除正式数据腾空间。

### 12.6 DuckDB 连接合同

沿用 `connect_configured_duckdb` / `DuckDBResource`：

```text
memory_limit = 16GB（现有资源默认）
threads = 4（现有资源默认）
temp_directory = /Volumes/datasource/.goldenshare_duckdb_tmp
preserve_insertion_order = false
```

所有正式输出必须显式 `ORDER BY`；不得依赖线程或插入顺序。窗口函数是 blocking operator，segment 上限和 projection 是内存门禁的一部分。

---

## 13. 编码门禁

### 13.1 静态拒绝项

测试或代码审查必须拒绝：

1. Python 对 qfq 明细执行 `for row`、`for ts_code` 递推。
2. 日常 asset glob 或扫描全历史 qfq/state。
3. Sensor 在日期循环中逐日执行重 DuckDB SQL。
4. Sensor 对窗口内每日期调用一次 Dagster readiness API。
5. 正式分区产生多个 Parquet 文件或按股票写文件。
6. 直接覆盖正式文件，或 candidate 未校验就 `os.replace`。
7. 在正式 Lake 下创建 staging。
8. 使用旧 Lake root 或任何 Kopia 命令/模块。
9. 用 current `silver_stock_basic` 代替历史 lifecycle。
10. 用量化 band 递推或判断状态。
11. production check 全量重算 EMA。
12. 本地 API 请求时现算、读取 state 绘图或回退 Prod DB。
13. 把独立 trend 开关硬编码在前端或复用分钟开关。
14. 把完整代码列表、路径列表或 SQL 塞入 cursor。

### 13.2 事务和观测边界

1. candidate 写入、正式文件提升和 Dagster event 是不同边界。
2. Dagster event/check 状态写入失败不得回滚或污染已完成的正式文件写入。
3. repair completion 缺失时必须 fail closed；不能从物理文件存在推断完成。
4. 多文件 repair 没有全局事务，必须在文档、metadata 和测试中保持这一真实语义。

### 13.3 Definitions 注册

仓库当前通过 `orchestrator/definitions.py` 从 defs folder 自动加载。新增模块应位于既有 `defs/assets|checks|jobs|sensors` 目录并由 Definitions 验证发现；不得新建手工影子注册表。

开发后必须运行：

```text
dg check defs
Definitions.validate_loadable
catalog/definition 对账测试
```

---

## 14. 本地 Wealth 低层合同

### 14.1 配置审计

新增唯一配置：

```text
Settings field:
  wealth_local_lake_stock_daily_trend_channel_api_enabled: bool = false

env:
  WEALTH_LOCAL_LAKE_STOCK_DAILY_TREND_CHANNEL_API_ENABLED
```

消费者完整清单：

1. `stock_daily_trend_channel_capability.py`
2. `src/app/api/v1/router.py`
3. 股票详情 page-init query service/schema
4. capability tests 和 Settings tests
5. 本地运行说明

既有 `GOLDENSHARE_LAKE_ROOT` 和 `APP_ENV` 不变。新开关不控制分钟线，分钟线开关也不控制趋势通道。

### 14.2 Foundation

新增：

```text
src/foundation/clients/local_lake/stock_daily_trend_channel_contract.py
src/foundation/clients/local_lake/stock_daily_trend_channel_reader.py
src/foundation/config/stock_daily_trend_channel_capability.py
```

contract 固定：

```text
FORMAL_LAKE_ROOT = /Volumes/datasource/data_lake
result dataset root = gold/indicator/stock_daily_trend_channel
formula version = stock-daily-trend-channel-v1
```

reader：

1. 只发现 `trade_date=YYYY-MM-DD/part-000.parquet`。
2. 按 `endDate` 和 `limit` 先选择有界分区目录，不把全历史 Parquet 交给 DuckDB 后再过滤。
3. 只投影 API 必需字段。
4. 内部先 `trade_date DESC LIMIT :limit`，外层 `ORDER BY trade_date ASC`。
5. 校验单一代码、公式版本、日期唯一和升序。
6. 不读取 state，不计算 EMA。

### 14.3 API

新增：

```text
src/biz/schemas/wealth/market/stock_detail_trend_channel.py
src/biz/queries/wealth/market/stock_detail_trend_channel/
  stock_detail_trend_channel_query_service.py
src/biz/api/wealth/market/stock_detail_trend_channel.py
```

接口：

```http
GET /api/v1/wealth/market/stock-detail/trend-channel
```

参数：

```text
tsCode    必填，标准股票代码
endDate   可选，包含；默认 page-init trade date
limit     默认 300，范围 1..2000
```

返回顺序严格为 `tradeDate ASC`，不分页。响应结构沿用指数趋势通道可复用字段语义，但使用股票的 camelCase Wealth 规范：

```text
stockRef
period = day
adjustment = forward
sourceAdjustment = qfq
formula
bars
meta
dataStatus
```

错误语义：

| 条件 | HTTP/code |
| --- | --- |
| 股票不存在 | `404 STOCK_NOT_FOUND` |
| 日期/limit 非法 | `400 INVALID_ARGUMENT` |
| route 已挂载但数据集未 ready/缺分区/版本错 | `503 STOCK_TREND_CHANNEL_SOURCE_NOT_READY` |
| DuckDB 读取失败 | `500 STOCK_TREND_CHANNEL_READ_FAILED` |

远程环境因 route 不挂载而自然不存在该功能；不能在远程返回空数组假装支持。

### 14.4 Page-init

`StockDetailCapabilitiesDto` 增加：

```text
supportsTrendChannel: bool = false
```

`StockChartDefaultsDto.availableMainOverlays` 增加 `TREND_CHANNEL` 只在 capability 为 true 时返回。服务端是能力事实源，前端不得按 hostname 或环境变量自行推断。

### 14.5 Router composition

`src/app/api/v1/router.py` 增加独立 `_include_local_stock_daily_trend_channel_router()`，只调用 foundation capability。不得把它塞入分钟 capability 的真假分支，也不得让 foundation import business router。

### 14.6 Wealth 前端

新增 feature：

```text
wealth/src/features/stock-detail/trend-channel/
  api/stockTrendChannelApiTypes.ts
  api/stockTrendChannelApiClient.ts
  api/stockTrendChannelViewModelAdapter.ts
  controller/useStockTrendChannel.ts
```

共享绘图层调整：

1. 将 `TrendChannelPanePrimitive` 和 `trendChannelGeometry` 提取到 `wealth/src/shared/charts/trend-channel/`。
2. 指数和股票分别依赖 shared primitive；股票不得从 `features/index-detail` 反向 import。
3. 只移动通用几何/primitive，指数专属 controller、API、types 保持在 index feature。

股票页面：

1. `StockMainOverlay` 扩展为 `MA | BOLL | TREND_CHANNEL`。
2. capability=false 时不显示入口、不请求 API。
3. capability=true 时显示“趋势通道”，首次选择时懒加载 300 行。
4. 切换股票或离开页面取消旧请求，旧数据不得泄漏到新股票。
5. API 失败只降级趋势图层，不破坏 K 线、九转、MA/BOLL。
6. 图层时间与现有 candle 对齐；不重排 candle，不在前端补停牌日。
7. header 展示短上/短下/长上/长下，绘图颜色复用现有指数趋势通道设计，不在本需求调整颜色体系。

---

## 15. 测试方案

### 15.1 公式 golden tests

新增独立字面 expected fixture，覆盖：

1. 首条 seed。
2. 连续上涨、下跌、inside retain。
3. close 等于上/下轨。
4. short/long 状态分叉和四种组合。
5. 多股票交错输入但按股票独立。
6. segment 边界 249/250/251 日。
7. 有前置 seed 与从历史起点全量计算一致。
8. 4 位 `ROUND_HALF_UP` 边界。
9. 增量逐日、segment 历史、repair 三条路径逐值一致。

### 15.2 日常资产测试

1. 普通交易日 result/state 行数正确。
2. 停牌股票不进入 result，但已初始化 state carry。
3. 新上市无历史 qfq 时不生成 state；首条 qfq 时初始化。
4. 退市日期边界严格使用半开区间。
5. 目标已存在时拒绝自动覆盖。
6. 两候选均通过后才提升。
7. 第二文件提升失败时清理本 run 新建 state，不发 materialization。
8. state 版本不一致和 qfq 越生命周期均 fail closed。

### 15.3 Check/readiness 测试

1. 三个 ordinary checks 的正负样本。
2. candidate 与 formal check 调用同一单日 audit helper；单日 audit 与 batch readiness 调用同一共享规则评估内核，并由 result/state/coverage 三组 parity 测试锁定等价语义。
3. batch helper 对 10 天只执行一条或少量 SQL，并记录 SQL/file count。
4. 只文件存在、row count 非零但 schema/coverage 错误不能 ready。
5. target 已 materialized 但 check 红时 sensor 不提交 run。
6. cursor 大小和 sample 上限。

### 15.4 qfq reconciliation 测试

1. 0 个 changed code 也提交 no-op job 并产生 durable check。
2. 0/1/20/21/500 的 codes 保存完整 list 和最多 20 samples。
3. 501 fail closed、truncated=true、不能自动提交。
4. hash/count/list 排序去重一致。
5. 现有 qfq、分钟 qfq、MACD/KDJ repair guard 回归。

### 15.5 趋势 repair 测试

1. 单股票因子变化从最早受影响日期算到 T-1。
2. 多股票不同上市日。
3. repair 跨停牌期 state carry。
4. repair 后结果与修复后 qfq 全量重算逐值一致。
5. 未受影响行保持不变。
6. 中途失败无 completion；retry 幂等。
7. batch id 不一致、范围不一致、公式版本不一致均不 ready。
8. 超实测自动上限不创建 run。

### 15.6 Bootstrap 测试

1. plan 覆盖全部 qfq 历史和退市代码。
2. 空/坏 lifecycle 覆盖阻断。
3. segment checkpoint/resume。
4. 多 chunk 不可直接晋升正式分区。
5. runless dry-run event 数、materialization/check 绑定和上限。
6. event 写失败不修改正式文件。

### 15.7 Wealth 测试

后端：

1. capability 的 env/root/dataset/duckdb 组合矩阵。
2. remote 和 flag=false 不挂载 route。
3. 300 默认、2000 最大、`endDate` 截断和 ASC 顺序。
4. 版本错、缺文件、股票不存在、非法参数错误语义。
5. page-init capability 与 overlay 列表一致。

前端：

1. capability=false 零入口、零请求。
2. 首次选择趋势通道只请求一次。
3. 股票切换 AbortController 生效。
4. API 错误不影响 K 线和其他图层。
5. shared primitive 提取后指数趋势通道回归。
6. 股票和指数均保持 API 原顺序，不前端重算。

### 15.8 验证命令

开发完成后至少运行：

```text
dg check defs
orchestrator 相关单元/集成/性能测试
orchestrator 全量 pytest
根仓库后端相关测试
架构依赖矩阵测试
npm --prefix wealth run typecheck
npm --prefix wealth run test
npm --prefix wealth run build
```

具体命令以开发时当前 package scripts 为准，不在文档中伪造不存在的脚本。

---

## 16. 文件白名单

编码阶段预计只允许触碰下列范围；开工时必须根据当前工作区重新冻结精确文件列表：

```text
lake_console/orchestrator/src/orchestrator/defs/
  asset_guards/*stock_daily_trend_channel*
  assets/stock_daily_trend_channel.py
  bootstrap/*stock_daily_trend_channel*
  catalog/lake_assets.py
  checks/stock_daily_trend_channel_checks.py
  jobs/*stock_daily_trend_channel*
  ops/*stock_daily_trend_channel*
  partitions.py
  paths.py
  run_contracts/asset_column_schemas.py
  sensors/*stock_daily_trend_channel*
  sensors/gold_stock_daily_qfq_factor_repair_job_sensor.py
  stock_daily_qfq.py
  stock_daily_trend_channel.py

lake_console/orchestrator/tests/ 对应新测试及精确 qfq repair 回归测试

src/foundation/clients/local_lake/*stock_daily_trend_channel*
src/foundation/config/settings.py
src/foundation/config/stock_daily_trend_channel_capability.py
src/biz/api/wealth/market/stock_detail_trend_channel.py
src/biz/queries/wealth/market/stock_detail_trend_channel/
src/biz/schemas/wealth/market/stock_detail*.py
src/app/api/v1/router.py
对应后端测试

wealth/src/features/stock-detail/trend-channel/
wealth/src/shared/charts/trend-channel/
wealth/src/features/index-detail/chart/ 中共享 primitive 的精确迁移消费者
wealth/src/features/stock-detail/chart/StockChartWorkspace.tsx
wealth/src/features/stock-detail/model/stockDetailTypes.ts
wealth/src/features/stock-detail/api/stockDetailApiTypes.ts
wealth/src/pages/stock-detail/StockDetailPage.tsx
wealth/docs/system/exception-code-registry.md
对应前端测试

本技术方案、LLD、文档索引和本地运行说明
```

不使用 `git add .`，不修改无关 QTF、Sector、ETF、新闻、市场总览或报告文件。

---

## 17. 实施顺序和停止点

### R0：M0 只读与 benchmark

状态：已完成并通过。规模、覆盖、性能、磁盘和 API 读取证据已写入 M0 报告；趋势自动 repair 上限冻结为 500。

### R1：qfq reconciliation 缺口

状态：已完成（2026-09-01）。

先修 no-op durable check 和完整代码范围 metadata，完成全部消费者回归。趋势资产不能早于该契约进入自动链。

实现结果：

1. 无因子变化日改为提交既有 qfq factor repair job，由 op 走零写入分支并产出 durable reconciliation check。
2. 公共 batch builder 已落地，sensor 不再使用私有 batch id 拼接函数。
3. `repair_required_codes` 在 0～500 条时保存完整规范集合，`repair_required_code_samples` 固定最多前 20 条；501 条起完整列表为空且 `truncated=true`。
4. guard 要求新字段并校验规范化、排序、去重、count、hash 和 samples 一致性；旧 metadata 不做兼容读取，超过 500 条保持 fail closed。
5. 直接契约测试 19 passed、12 个边界 subtests passed；日线 qfq、分钟 qfq、MACD/KDJ repair、completion event 与 run-contract 消费者回归 207 passed、21 个 subtests passed。
6. 完整测试进程通过 2449 项后，8 项无关 major-index history 测试因进程累计 RSS 超过 1024 MiB 门禁失败；该文件在独立新进程 18/18 通过，未修改其性能门禁。
7. 未实现任何趋势资产、趋势 job/sensor、趋势 repair 或本地 API；R1 完成时 R2 为下一停止点，当前 R2 已按下节完成。

### R2：合同和公式内核

状态：已完成（2026-09-01）。

实现结果：

1. 在 `asset_column_schemas.py` 中新增结果与 state 两份精确 schema；在 `name_mapping.py` 中新增两个 Catalog 中文名称。
2. 在 `paths.py` 中新增结果/state 正式路径与 run-scoped staging 路径 helper；staging 路径固定包含 `run_id` 和 `trade_date`，并拒绝正式 Lake 根、旧 Lake 根、非法日期和不安全 run id。
3. 在 `lake_assets.py` 中新增两个合同级 Catalog 条目、独立 `PartitionModel` 和既定 check 名称；未注册尚不存在的 asset/check 定义。
4. 在 `partitions.py` 中新增 `cn_a_stock_daily_trend_channel_trade_days`，不复用 qfq 分区对象。
5. 在 `stock_daily_trend_channel.py` 中新增纯 DuckDB SQL 内核：不连接数据库、不 import Dagster、不逐行 Python 循环；daily、history segment 与 repair segment 共用同一公式构建路径。
6. 公式常量冻结为 25/90 日窗口、既定 EMA 衰减、250 日 segment 上限、单日 10000 行上限；计算先使用未量化 band 判定严格突破，再用 `ROUND_HALF_UP` 序列化 4 位小数。
7. 复用 M0 的独立字面量 fixture 完成 1599 行全量 parity，并覆盖 249/250/251 边界、daily/history/repair 一致性、多股票隔离、等号不突破和量化边界。
8. M2 直接合同与公式测试 30 passed；连同 Catalog、check 治理和静态门禁共 152 passed、589 个 subtests passed；修改文件 Ruff 检查通过。
9. orchestrator 全量测试为 2485 passed、3 failed；失败均来自既有 `test_major_index_nineturn_m4b.py` 在累计进程中 RSS 刚超过 1024 MiB 门禁，该文件在独立新进程 18/18 通过，因此未修改任何无关性能门禁。
10. 未实现 asset/check/job/sensor/bootstrap/repair/API，未写正式 Lake、staging 或 Dagster event；R3 为下一停止点。

### R3：每日 assets/checks

已完成（2026-09-01）：

1. 新增不可子集化的 `gold_stock_daily_trend_channel_assets`，一次 run 同时生成 result 和 state，静态依赖严格保持 qfq identity mapping、stock basic、lifecycle 和 trade calendar。
2. 日常 writer 在一个 configured DuckDB connection 内完成输入拒绝、observed 结果、停牌 carry、未初始化统计和两份 run-scoped candidate 写入；正式 result 只含 qfq 实际行，state 使用 `list_date <= T < delist_date` 半开生命周期。
3. 三个公共 audit helper 同时服务 candidate 和 ordinary checks；审计覆盖单文件/分区路径、精确 schema、键、值域、版本、qfq 一一对账、state 生命周期及 observed/carry/uninitialized 聚合等式，不重算 EMA。
4. 两个候选全部通过后才按 state、result 顺序原子提升；第二文件失败时删除未发事件的正式 state 并恢复 state candidate，保留本 run 诊断。
5. 新增三个显式分区、blocking checks，并从 Catalog 合同态切换为当前自动发现的正式 asset/check 定义；治理分类保持等待 R4 batch readiness 的既定口径。
6. M3 直接测试 20 passed，覆盖普通日、停牌 carry、新上市初始化、退市边界、目标冲突、候选失败、第二提升失败、qfq/previous state 全部拒绝规则和 checks 正负样本。
7. 冻结上限 5547 条 qfq、5565 条 lifecycle 的本地合成日样本完成 result/state 各 5547 行，18 个未初始化代码，完整 writer 端到端 182.202 ms、temp spill 0，低于 120 s/1 GiB 日常门禁。
8. 合同、公式、Catalog、治理和静态门禁定向回归 172 passed、593 个 subtests passed；orchestrator 全量回归 2508 passed、853 个 subtests passed；修改文件 Ruff、定义自动发现和 `git diff --check` 均通过。
9. 未实现 Job/Sensor、batch readiness、repair、bootstrap 或 API，未执行正式 Lake/staging 写入或 Dagster event；R4 为下一停止点。

### R4：分区和每日调度

状态：已完成（2026-09-01）。

1. 新增 `stock_daily_trend_channel_trade_day_sensor`，默认 `STOPPED`、最小间隔 600 秒；上海时间 06:00 后按 10 日 expected window 每 tick 最多注册两个缺失分区，只返回 dynamic partition add request。
2. 新增 `gold_stock_daily_trend_channel_update_job`，selection 精确包含 result/state 双资产和三个 blocking checks，不写业务逻辑或扩大上游 selection。
3. 新增 `gold_stock_daily_trend_channel_update_job_sensor`，默认 `STOPPED`、每 tick 最多一个 RunRequest；按 expected calendar、registered gap、批量 target readiness 和 selected T 上游门禁顺序推进最早可行动日期。
4. target readiness 最多读取 10 日、20 个目标文件和一个 previous-state 边界文件，正常路径执行一次 schema SQL 和一次集合审计 SQL；返回 `sql_count`、`scanned_file_count`、`elapsed_ms`、`slowest_query_ms`、`window_date_count`。
5. M0 冻结规模合成样本为连续 11 日、每日 5547 行，评估后 10 日加边界 state：`elapsed_ms=63`、`slowest_query_ms=60`、`sql_count=2`、`scanned_file_count=21`，低于 5000 ms 工程门禁；fixture 构造耗时不计入 readiness。
6. target 完全缺失时可行动；双文件部分存在、schema/contract/coverage 失败时 materialized fail closed，不自动覆盖。10 日以上窗口在任何 SQL 前拒绝。
7. qfq、stock basic、lifecycle 和 previous state 只针对 selected T 检查；qfq reconciliation 必须匹配最新 qfq producer run 推导的 exact upstream batch，旧绿色 batch 不放行。`repair_required=true` 在 R5 前以 `trend_repair_required` 阻断。
8. run key 固定为 `gold_stock_daily_trend_channel_update:{T}:{formula_version}`；cursor 使用统一 builder，只保存 frontier、小型 readiness/repair 摘要和批量性能统计，正常样本小于 2 KB。
9. result/state/coverage 三类单日审计和集合审计共同消费共享规则评估内核；M4 直接测试 15 passed，M3+M4 35 passed；合同、公式、qfq repair、Catalog、治理和静态门禁定向回归 213 passed、605 个 subtests passed。
10. orchestrator 全量回归按进程拆分通过：主套件排除既有 RSS 敏感文件后 2506 passed、853 个 subtests passed，`test_major_index_nineturn_m4b.py` 独立进程 18 passed，合计覆盖 2524 个测试。单进程全量的 8 个失败均因该无关文件读取整个 pytest 进程峰值 RSS（约 1.14 GiB）触发自身 1 GiB 门禁；本轮未改该文件或其门禁。
11. 未运行 `dg` 或访问正式 Dagster runtime，未写正式 Lake/staging、未启用 Sensor、未部署；R5 为下一停止点。

### R5：repair

状态：已完成（2026-09-02）。

1. 新增 `GoldStockDailyTrendChannelRepairConfig` 和统一 run-config builder；配置只接受完整有序代码集合、SHA-256、qfq T、repair 起止日期和 exact source batch，op 启动后重新读取 qfq repair status 并逐项校验。
2. 新增 `gold_stock_daily_trend_channel_repair_job` 与同名 run-status sensor；sensor 监听 qfq repair 成功、默认 `STOPPED`、每个成功上游 run 最多一个请求，0 changed codes 不提交，500 允许，501 起 fail closed。
3. repair run key 通过 `build_upstream_triggered_run_key(...)` 生成，版本化 consumer 与 opaque `source_upstream_batch_id` 共同构成身份；不同 producer batch 不会被旧日期/hash key 误去重。
4. 核心 writer 使用一个 configured DuckDB connection、最多 250 个交易日一段；affected 结果/state 集合重算，unaffected 行通过集合合并保持不变，不存在 Python 行级行情计算。
5. 每个日期生成 result/state 两个完整单文件候选；所有候选完成 contract、coverage、affected 精确相等和 unaffected `EXCEPT ALL` 审计后，才按日期升序执行 state -> result 原子替换。
6. 中断不做跨文件伪事务或 Kopia 回滚；已提升日期保留，同 scope 重试重建完整候选并幂等收敛。失败路径不写 completion checks，成功后再对全部正式分区复审。
7. 新增 result/state 两个 repair completion check 名称及 fail-closed guard；两个 checks 必须在 qfq T 分区同时为 blocking green，并精确匹配 batch、范围、partition count、代码 count/hash、公式版本、producer run 和重写行数。
8. 日常 sensor 的 qfq reconciliation 已接入该 guard；旧批次 completion、单 check、范围/公式/行数不一致均继续返回 `trend_repair_required`。
9. M2 的“整个公式文件禁止任何 `for`”静态测试已校准为只约束四个公式 SQL builder；M5 只允许日期 segment、文件生成/审计/提升编排循环，仍禁止公式或行情明细 Python 循环。
10. M5 直接测试 `12 passed`；趋势合同、公式、M3～M5、qfq 与分钟线/MACD-KDJ repair、run contract 定向回归 `284 passed`、`58` 个 subtests；治理/readiness/Definitions 回归 `157 passed`、`593` 个 subtests。
11. orchestrator 全量回归按既有 RSS 隔离策略通过：主套件 `2519 passed`、`853` 个 subtests，`test_major_index_nineturn_m4b.py` 独立进程 `18 passed`，合计 `2537 passed`。
12. 修改文件致命 Ruff 门禁通过，新文件及本轮直接测试完整 Ruff 通过；`configs.py` 的 11 项默认 Ruff 报告均为本轮前已存在的 DTZ007/TRY004 债务，本轮未越界修改。
13. 未运行 `dg`、未访问正式 Dagster runtime、未写正式 Lake/staging、未启用 Sensor、未部署；R6 为下一停止点。

### R6：bootstrap 工具

状态：已完成（2026-09-02）。

1. 新增 `stock_daily_trend_channel_history.py` 和 CLI，提供 `plan / sample / benchmark / generate / audit-files / promote / final-audit`；新增独立 runless event 模块和 CLI，提供 `dry-run / sample / apply / final-audit`。物理命令与事件命令互不调用。
2. `plan` 枚举全部正式 qfq 日期，要求每个分区只有精确 `part-000.parquet`，冻结源文件行数、大小、SHA-256、lifecycle SHA-256、13 个以内的 250 日 segment、目标冲突和磁盘预算。M0 的 `3079 partitions / 11,710,697 rows / 5565 codes` 继续作为性能基线；M6 完成日的正式只读 plan 已增长为 `3080 partitions / 11,716,243 rows / 5567 codes`，不把历史快照写成固定数据门禁。
3. `sample/benchmark` 只允许写 `/private/tmp` 子目录；`generate` 只允许把候选和物理 checkpoint 写入正式 staging 根下。每个 segment 使用一个 configured DuckDB connection，公式计算和审计均为集合 SQL；候选行数通过一次批量 filename 聚合读取，不逐文件新建连接。
4. 历史输出显式保留正式 schema 列名和类型。对外 4 位小数结果、状态、枚举和版本逐值等同每日路径；内部 raw state 按既有公式金样本合同使用 `abs <= 1e-10` 的浮点等价门限，不改变序列化结果或状态判定。
5. 新增 history segment readiness helper：一次规划最多 250 日的 result/state/qfq/previous-state 文件，以一次 schema 查询和一次集合审计查询复用 result/state/coverage 共享规则内核；不在 Python 日期循环中执行单日重审计。
6. checkpoint 只记录已完成 segment、精确候选文件身份和 audit 摘要；候选文件缺失、大小或 hash 漂移时不复用，按原 segment 重算。promotion checkpoint 只记录已完整提升日期；同日按 state -> result 提升，中断重试接受已存在且 hash 完全一致的目标，冲突目标立即停止。
7. `audit-files` 要求全部 segment 完成并再次集合审计；`promote` 要求精确 audit hash；物理 `final-audit` 要求精确 promote hash，并重新验证全部正式文件与跨 segment state 连续性。
8. runless event plan 只接受 green promote/final-audit 报告和未漂移的正式文件；先登记缺失动态分区，再补两个资产的 materialization。checks 只覆盖最近 20 日与最新日期的去重并集，绑定最新 materialization storage id；materialization 上限为 `2 * approved partitions`，ordinary check 上限为 `21 * 3`。
9. event apply 在任何 active Dagster run、数量越界、物理路径/大小/hash 漂移或缺少显式确认时 fail closed。event checkpoint 与报告被强制隔离在正式 Lake 和候选 staging 之外；event 失败测试证明正式文件 hash 不变。
10. M6 专项测试 `11 passed`，覆盖全 qfq 范围与退市股票、lifecycle 缺口、dry-run 零写入、每日路径 parity、停牌 state carry、候选损坏重算、promotion 中断续跑、动态分区登记、event 数量与 materialization 绑定、event 失败文件不变、控制文件路径隔离和错误确认参数。
11. M0～M6 趋势通道合同、公式、每日、readiness、repair 和 bootstrap 回归 `88 passed`；热路径、治理和静态门禁 `130 passed`、`593` 个 subtests，Definitions `validate_loadable` 通过，根依赖矩阵 `4 passed`，文档完整性通过。
12. orchestrator 全量回归沿用既有 RSS 隔离口径：主套件 `2530 passed`、`853` 个 subtests，`test_major_index_nineturn_m4b.py` 独立进程 `18 passed`，合计 `2548 passed`。
13. 2026-09-02 正式 Lake 只读 `plan` 结果：`2014-01-02～2026-09-01`、`3080` 个 qfq 分区、`11,716,243` 行、`5567` 个历史代码、`14` 个退市历史代码、`13` 个 segment；lifecycle 缺口 `0`、目标冲突 `0`、预计 materialization/check event `6160/63`、`should_stop=false`。随后使用精确 plan id/hash/range 执行 `generate` dry-run，候选和正式文件数均为 0，未创建 staging 目录或 checkpoint。该 `/private/tmp` 报告只用于 M6 验证，正式执行前仍须重新生成并审批新 plan。
14. 未运行 `dg`、未访问正式 Dagster runtime、未写正式 Lake/staging、未报告正式 runless event、未启用 Sensor、未部署；R7 为下一停止点。正式 bootstrap 与 event backfill 仍需管理员逐命令单独批准。

### R7：本地 Wealth

状态：已完成（2026-09-02）。

1. 新增唯一配置 `WEALTH_LOCAL_LAKE_STOCK_DAILY_TREND_CHANNEL_API_ENABLED`，默认 `false`；capability 严格要求 `APP_ENV in {dev, local}`、正式 Lake root、DuckDB 和 result/state 两个正式目录均可读。flag=false 或远程环境不探测 DuckDB 和正式目录。
2. Router 通过独立 `_include_local_stock_daily_trend_channel_router()` 组合，不复用分钟 capability，不改变分钟、九转或其他业务路由。远程或 capability=false 时 route 不存在；foundation 没有新增对 ops/biz/app 的反向依赖。
3. 新增 result-only local reader；只枚举合法日期目录，并仅校验按 `endDate` 截断后最新 `limit` 个分区的 `part-000.parquet`。DuckDB 使用单个内存连接、`256MB` memory limit、单线程和显式排序；API 在成功和异常路径都显式关闭本次请求的 Reader，不读取 state、不扫描 Prod DB、不请求时计算 EMA。
4. Reader 对每个被选文件校验精确 schema，对结果校验股票代码、公式版本、source file 与分区日期一致、日期唯一且严格升序、数值有限、上下轨顺序和全部枚举值。合同漂移统一映射 source-not-ready；非合同 DuckDB 故障统一映射 read-failed。
5. 新增股票趋势通道 schema、query service 和 API。API 严格拒绝未知/重复参数，`tsCode` 必填，`endDate` 为包含日期，缺省时使用 page-init 市场日期，`limit` 默认 300、最大 2000；响应保持 `tradeDate ASC`，不分页。
6. 错误码已先登记到 `wealth/docs/system/exception-code-registry.md`：股票不存在为 404，参数非法为 400，正式数据合同未 ready 为 503，读取故障为 500。
7. 股票详情 page-init 新增 `supportsTrendChannel`；只有 capability=true 时 `availableMainOverlays` 才包含 `TREND_CHANNEL`，服务端保持唯一能力事实源。
8. 通用 `TrendChannelPanePrimitive` 与 geometry 已从指数 feature 原位迁移到 `wealth/src/shared/charts/trend-channel/`；指数消费者改为 shared import，指数专属 API、controller 和类型未移动。股票 feature 没有反向依赖指数 feature。
9. 股票趋势 controller 首次选择才请求 300 行；loading/ready 期间重复选择不重复请求。切换股票、能力关闭或离页时 AbortController 取消旧请求，并以 request id 和 request key 双重阻止旧响应泄漏。
10. 股票主图只按现有 candle 时间连接服务端顺序结果，不排序、不补停牌日、不重算指标；header 展示短上/短下/长上/长下，绘图颜色复用既有指数 primitive。趋势请求失败只保留趋势图层空态，不进入页面级错误，也不破坏 K 线、九转和 MA/BOLL。
11. 后端 M7 核心定向测试 `18 passed`；连同分钟、股票九转、指数趋势、page-init/API 和架构边界的相关回归 `150 passed`。修改范围 Ruff、Python 编译和 diff whitespace 门禁通过。
12. Wealth 类型检查通过；全量测试 `78` 个文件、`544 passed`；生产构建通过，仅保留既有 bundle 超过 500 kB 的非阻断提示。
13. 根仓库单进程全量 pytest 在收集阶段被两个既有无关问题阻断：`tests/lake_console/test_sync_services.py` 引用已删除的冻结服务模块，且根目录与 `tests/lake_console` 存在同名 `test_tushare_client.py` 导入冲突。本轮未修改或规避这些无关测试；M7 调用链和依赖边界已由上述 150 项回归覆盖。
14. 浏览器使用独立临时 Wealth dev server 检查到登录保护页正常加载且 console 无 warning/error；因没有当前浏览器登录态，未进入股票详情。正式 result/state 目录当前均不存在，真实 API/绘图验收必须在 M8 bootstrap、event、配置和登录条件满足后执行，本轮没有创建 mock 正式目录。
15. M8 后本地启用参数固定为：

```text
APP_ENV=local
GOLDENSHARE_LAKE_ROOT=/Volumes/datasource/data_lake
WEALTH_LOCAL_LAKE_STOCK_DAILY_TREND_CHANNEL_API_ENABLED=true
```

上述配置只有在正式 bootstrap 与物理审计完成后才允许启用。本轮未修改任何运行配置、正式 Lake、staging、Dagster event、Sensor 或部署状态。

### R8：部署、正式 Bootstrap 和启用

状态：已完成（2026-09-02）。不改变“编码授权不等于运营授权”的合同；以下正式动作均在用户逐命令确认后执行。

1. 执行计划冻结为：

```text
plan_id   = cf161c2e70ec49b38c33cd1f349361cd
plan_hash = e6ed2fbd610d0964089463cc8a11aecc54493ea0a24dc6e7ab36e73931c3367c
range     = 2014-01-02..2026-09-01
segments  = 13
```

源事实为 `3080` 个 qfq 分区、`11,716,243` 行、`5567` 个历史代码和 `14` 个退市历史代码；lifecycle 缺失与冲突目标均为 0。

2. 先完成两只股票、250 日 sample，再完成首个全市场 segment，最后通过 checkpoint 生成其余 12 个 segment。全部候选为：

```text
result = 3080 files / 11,716,243 rows
state  = 3080 files / 11,986,495 rows
audit_hash = d8fcd45958ead7dc5a2a33f428aefb9e574cf56d96c7615bef1868e409fb4227
```

13 个 segment 均通过共享 result/state/coverage 和跨段 state 审计，`should_stop=false`，temp spill 为 0。

3. promotion dry-run 确认 `3080` 个分区、`6160` 个文件后执行原子提升。最终：

```text
promote_hash     = 493cf0bdcfff8da5981353d27a34a13bce3568c31517bb34a62dc98e021c9d12
formal result    = 3080 files
formal state     = 3080 files
processed/promoted partitions = 3080/3080
final_audit_hash = 483eb495a44fc81e50f46ec56c059339021307f089893515e4f2b795fa87baa7
failed segments  = 0
```

最终物理审计 `should_stop=false`，计划范围与正式范围精确相等，候选文件已清零。

4. runless event 先单日 sample，再提交余下 `3079` 个动态分区、`6158` 条 materialization 和 `57` 条 check；连同 sample，最终总量为 `3080` 个动态分区、`6160` 条 materialization 和最近 20 日的 `60` 条 blocking check。最终审计为：

```text
planned_registration_count    = 0
planned_materialization_count = 0
planned_check_count           = 0
active_run_count              = 0
should_stop                   = false
```

5. Sensor 启用前使用正式最近 10 日执行 3 次预热和 20 次计量：P50 `65 ms`、P95 `68 ms`、最大 `84 ms`、峰值 RSS `494.859 MiB`、temp spill `0`、21 个文件、2 条 SQL、最慢 SQL `60 ms`；`all_ready=true` 且通过 `5000 ms` 门禁。`dg check defs` 完整加载通过。

6. CLI 使用当前 `dg dev` 生成且 `location_name=orchestrator` 的 live workspace，避免 `-m orchestrator.definitions` 产生另一代码位置身份。以下三个 Sensor 已启用并核验为 `RUNNING`：

```text
stock_daily_trend_channel_trade_day_sensor
gold_stock_daily_trend_channel_update_job_sensor
gold_stock_daily_trend_channel_repair_job_sensor
```

注册 Sensor 当前无缺失动态分区，日更 Sensor 最近窗口全部 ready。run-status repair Sensor 首 tick 按 Dagster 合同初始化到最新成功事件，不追溯历史成功 run。

7. 本地运行配置已加入独立开关，并由用户重启服务：

```text
APP_ENV=local
GOLDENSHARE_LAKE_ROOT=/Volumes/datasource/data_lake
WEALTH_LOCAL_LAKE_STOCK_DAILY_TREND_CHANNEL_API_ENABLED=true
```

直接 API 以 `000001.SZ / endDate=2026-09-01 / limit=300` 返回 `200`、300 根严格升序日线、`dataStatus.status=READY` 和 `observedTradeDate=2026-09-01`。已登录 Wealth 页面首次选择“趋势通道”产生一次相同 API 请求并收到 `200`；四条轨道和 header 数值正常绘制，浏览器 console 无 warning/error。

8. 没有执行远程部署，也无需补做远程部署：`prod/production/staging` 不挂载股票趋势通道本地 Lake API 是冻结产品合同。R8 没有修改 Prod DB、ClickHouse、Redis、Kopia 或其他数据集。

### 必须停止并请求拍板的情况

M0 已排除 lifecycle 覆盖、公式 parity、repair 上限和当前磁盘空间四项前置阻断。后续开发仍在以下情况停止：

1. 日常或 10 日 readiness 超过硬门禁且无法在当前读取模型内解决。
2. 当前代码在开发前已改变 qfq repair metadata、Catalog 或本地 capability 主链，导致本文合同失真。
3. 需要新增数据库、配置表、状态 manifest、Kopia 或修改正式 Lake root。
4. 需要改变已确认的历史范围、停牌 carry 口径或 M0 冻结常量。

---

## 18. 当前待办与拍板状态

业务口径没有待拍板项。两个原待确认问题已经冻结为：

```text
全正式 qfq 历史 + 保留退市股票
停牌不造指标行 + 已初始化 state carry-forward
```

M0 真实只读规模、性能证据和趋势自动 repair 上限已经完成并冻结；R8 正式 bootstrap、runless event、Sensor 启用和本地 Wealth 验收也已完成。当前没有新增业务待拍板项或本需求待执行里程碑。后续日常 Sensor 运行与 qfq 触发的趋势 repair 属于既定运行合同，新的手工 repair、历史重算或 Sensor 停用仍须另行按命令审批。

---

## 19. 计划对账

| 上位方案硬口径 | LLD 落点 |
| --- | --- |
| 全历史且保留退市股票 | 1.1、3.4、11.3 |
| 停牌不造行情、state carry | 1.1、3.1、3.2、6.3 |
| 每天 06:00 注册但不触发 | 8.2 |
| 等 qfq/basic/lifecycle/previous state | 6.2、8.4 |
| qfq 历史变化必须 repair | 9、10 |
| EMA repair 不截断 25/90 日 | 5.4、10.1 |
| DuckDB 向量化、无 Python 明细循环 | 5、10.3、13.1 |
| staging + validate + atomic replace | 4.4、6.4、10.5 |
| 无 Kopia、正式 root 唯一 | 4.4、13.1 |
| Direct Lake Bootstrap + runless events | 11 |
| 真 batch readiness 和 10 日热窗口 | 8.4、8.5、12.3 |
| no-op qfq repair durable 状态 | 9.1 |
| 完整代码范围与 sample 分离 | 9.2、9.3 |
| 本地 Wealth、远程不存在 | 14 |
| 性能和编码硬门禁 | 12、13、15 |

---

## 20. 参考代码与规范

- [Dagster 数据管道性能治理规范](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-data-pipeline-performance-governance.md)
- [Dagster Asset Schema Contract 设计](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-asset-schema-contract-design.md)
- [Local Lake 数据集接入说明模板](/Users/congming/github/goldenshare/docs/templates/lake-dataset-development-template.md)
- `lake_console/orchestrator/src/orchestrator/defs/assets/stock_daily_qfq.py`
- `lake_console/orchestrator/src/orchestrator/defs/stock_daily_qfq.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/stock_daily_qfq_sensor.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/gold_stock_daily_qfq_factor_repair_job_sensor.py`
- `lake_console/orchestrator/src/orchestrator/defs/asset_guards/stock_daily_qfq_factor_repair.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/stock_current_trade_day_sensor.py`
- `lake_console/orchestrator/src/orchestrator/defs/catalog/lake_assets.py`
- `src/biz/services/quote_trend_channel_calculator.py`
- `src/foundation/config/local_minute_capability.py`
- `src/app/api/v1/router.py`
- `wealth/src/shared/charts/trend-channel/TrendChannelPanePrimitive.ts`
- `wealth/src/shared/charts/trend-channel/trendChannelGeometry.ts`
- `wealth/src/features/stock-detail/chart/StockChartWorkspace.tsx`
