# Dagster 基础事实两阶段刷新方案

状态：方案已拍板，待开发。本文是独立需求方案文档，尚未落地到 Dagster definitions。

更新时间：2026-06-17

## 1. 背景

当前基础事实资产的日常自动化口径不一致：

| 资产族 | 当前目标日期来源 | 当前触发口径 |
| --- | --- | --- |
| `stock_basic` | `cn_a_stock_trade_days` | 股票交易日分区 17:00 后注册；raw/silver sensor 以最新已注册日期判断 freshness |
| `suspend_d` | `cn_a_stock_trade_days` | 对已注册股票交易日补缺失 raw/silver 分区 |
| `namechange` | `cn_a_stock_current_trade_days` | 06:00 后注册当前交易日；09:30/17:00 两阶段触发 raw/silver |
| `silver_stock_identity_map` | `cn_a_stock_trade_days` | 17:30 后等待 `silver_stock_basic` 与 `silver_namechange` ready 后重建 |
| `adj_factor` | `cn_a_stock_current_trade_days` | 09:30 后触发 raw/silver；silver 只要求 stock basic 历史 ready，不要求目标日 freshness |

因此会出现上午 `namechange` 已经以当前交易日为目标，但 `stock_basic` 仍停留在前一交易日的问题。典型表现是 `silver_namechange_update_job_sensor` 的 cursor 中：

```text
raw_tushare_namechange ready = true
silver_namechange ready = true
stock_basic ready = false
raw_tushare_stock_basic materialized at previous trade date
silver_stock_basic materialized at previous trade date
```

根因不是 `namechange` sensor 不工作，而是基础事实链的目标日期与更新时间没有统一。

## 2. 目标

将以下基础事实资产统一纳入 `cn_a_stock_current_trade_days` 驱动的两阶段刷新链：

1. `raw_tushare_stock_basic` / `silver_stock_basic`
2. `raw_tushare_suspend_d` / `silver_stock_suspend_daily`
3. `raw_tushare_namechange` / `silver_namechange`
4. `silver_stock_identity_map`
5. `raw_tushare_adj_factor` / `silver_adj_factor`

每天两个阶段：

| 阶段 | 最早开始时间 | 依赖顺序 |
| --- | --- | --- |
| 早盘 | 09:00 开始 | `stock_basic` -> 09:05 `suspend_d` -> 09:10 `namechange` -> 09:15 `silver_stock_identity_map` -> 09:20 `adj_factor` |
| 下午 | 16:00 开始 | `stock_basic` -> 16:05 `suspend_d` -> 16:10 `namechange` -> 16:15 `silver_stock_identity_map` -> 16:20 `adj_factor` |

表中的时间只表示“本资产最早允许开始检查/提交”的时间点，不表示固定等待 5 分钟后无条件执行。真实顺序必须由上游本 stage success/readiness gate 保证。

用户已确认：

1. 下午 16:00 不需要再做源站可用性验证，按该时间口径设计。
2. 不做一个大 job，继续保留现有 asset/job 分层更新。
3. 5 分钟不是单纯错峰，而是为了表达执行顺序；正式实现必须用依赖门禁保证顺序，不能靠固定等待时间。
4. `suspend_d` 与 `adj_factor` 都允许每天两次重写同一交易日分区。
5. `silver_adj_factor` 必须依赖 stock basic 本 stage freshness。
6. sensor 最小 tick 间隔使用 300 秒。
7. sensor 代码默认继续 `STOPPED`。
8. 同一 stage 最多提交 3 次 run。
9. active run guard 是硬门禁，必须防止同一 job/trade_date/stage 重复提交正在运行的 run。
10. 按 8 个 milestone 分批落地，不一次性修改整条链路。
11. 两阶段基础事实 run key 正式采用 `build_repair_attempt_run_key(...)`。
12. 执行链采用强一致、强顺序方案：`stock_basic -> suspend_d -> namechange -> silver_stock_identity_map -> adj_factor`。
13. 本轮选择 A：只做日常两阶段链路；历史缺口补分区不混入本轮日常 sensor，后续单独设计 maintenance/backlog repair 方案。
14. cursor 只做观测展示，不作为提交次数或 active run 的事实源；提交次数和 active run 必须以 Dagster run history 为准，按统一 builder 生成的候选 run key 精确匹配。

## 3. 不做范围

本需求不做以下事情：

1. 不新增业务数据表、summary asset、readiness asset 或外部状态表。
2. 不改变 asset key、job 名称、path schema、字段 schema。
3. 不把多个基础资产塞进一个组合大 job。
4. 不让下游业务 job 顺手 selection 基础资产。
5. 不修改正式 Dagster instance 状态，不启停 sensor，不补跑 job。
6. 不把源站验证作为本轮前置条件。
7. 不把历史缺口补分区混入日常两阶段 sensor；旧的按历史 `cn_a_stock_trade_days` backlog 扫描、每 tick 补历史 pending 分区，不属于本轮日常链路。
8. 不在本轮新增历史补缺 sensor、maintenance job、backlog repair job、手动补数 CLI 或任何新补录入口；历史缺口维护后续单独立项设计。

## 4. 核心设计

### 4.1 统一目标日期

上述基础事实 sensor 全部改为读取 `cn_a_stock_current_trade_days` 的最新已注册日期。

`stock_trade_day_sensor` 和 `cn_a_stock_trade_days` 仍保留给股票日线、市场宽度等收盘后资产族使用；本需求不把它们删除或改语义。

### 4.2 两阶段定义

新增统一 stage helper，建议放在基础事实 sensor 共享模块中：

```text
morning:
  stock_basic: 09:00
  suspend_d: 09:05
  namechange: 09:10
  stock_identity_map: 09:15
  adj_factor: 09:20

afternoon:
  stock_basic: 16:00
  suspend_d: 16:05
  namechange: 16:10
  stock_identity_map: 16:15
  adj_factor: 16:20
```

每个 sensor tick 先判断：

1. 今天是否为已注册的 `cn_a_stock_current_trade_days`。
2. 当前时间属于哪个 stage。
3. 本资产在当前 stage 的最早触发时间是否已到。
4. 本资产的 stage-aware readiness 是否已满足。
5. 上游资产是否已经完成本 stage 且 blocking checks 全绿。
6. 本 stage 是否已经达到最多 3 次提交上限。
7. 是否存在同 job/trade_date/stage 的 active run。

### 4.3 Stage-aware readiness

现有 readiness 只支持按本地日期判断 freshness，例如 `materialization_date >= trade_date`。这不足以区分同一天早盘和下午两次更新。

本需求需要新增 stage-aware freshness：

```text
asset ready for stage =
  latest materialization exists
  AND latest materialization timestamp >= stage_start_datetime
  AND blocking checks attached to that materialization all passed
```

对于 partitioned asset，还要继续要求 `partition_key = trade_date`。

对于 full snapshot asset，例如 `stock_basic`、`namechange`、`silver_stock_identity_map`，不新增物理日期分区；用 materialization timestamp 判断是否完成本 stage。

### 4.4 Run key

所有参与两阶段刷新的 sensor run key 必须通过 `orchestrator.defs.run_contracts.run_keys` 的统一 builder 生成，不允许在 sensor 文件或基础事实 helper 中手写 run key 字符串模板，也不新增基础事实专属 run key 函数。

两阶段基础事实的同一 `job/trade_date/stage` 允许最多 3 次自动提交，这不是普通“一次性 asset update”语义，而是有界 attempt 语义。因此本链路统一使用：

```python
build_repair_attempt_run_key(
    subject="<stable_update_subject>",
    repair_scope_id=f"{trade_date}:{stage}",
    attempt=attempt,
)
```

输出格式固定为：

```text
{subject}:{trade_date}:{stage}:{attempt}
```

各 job 的 subject 仍沿用既有稳定身份：

| job | subject | run key 示例 |
| --- | --- | --- |
| `raw_stock_basic_update_job` | `raw_stock_basic_update` | `raw_stock_basic_update:2026-06-17:morning:1` |
| `silver_stock_basic_update_job` | `silver_stock_basic_update` | `silver_stock_basic_update:2026-06-17:morning:1` |
| `raw_suspend_d_update_job` | `raw_suspend_d_update` | `raw_suspend_d_update:2026-06-17:morning:1` |
| `silver_suspend_d_update_job` | `silver_suspend_d_update` | `silver_suspend_d_update:2026-06-17:morning:1` |
| `raw_namechange_update_job` | `raw_namechange_update` | `raw_namechange_update:2026-06-17:morning:1` |
| `silver_namechange_update_job` | `silver_namechange_update` | `silver_namechange_update:2026-06-17:morning:1` |
| `stock_identity_map_update_job` | `stock_identity_map` | `stock_identity_map:2026-06-17:morning:1` |
| `raw_adj_factor_update_job` | `raw_adj_factor_update` | `raw_adj_factor_update:2026-06-17:morning:1` |
| `silver_adj_factor_update_job` | `silver_adj_factor_update` | `silver_adj_factor_update:2026-06-17:morning:1` |

`attempt` 只能是 `1..3`。原因：

1. 同一天早盘和下午都要允许提交 run；只用 `trade_date` 的旧 run key 会把下午 run 当成重复请求挡掉。
2. 同一 stage 允许最多 3 次提交；如果 run key 只到 `{trade_date}:{stage}`，Dagster 会把第 2、3 次提交视为同一个 run key，无法表达“最多 3 次”。
3. active run guard 负责防并发重复提交，attempt run key 负责让失败后的第 2、3 次提交有可审计身份。
4. `run_key` 仍只用于 Dagster 幂等去重，不承载执行参数；执行参数只能来自 `partition_key`、显式 `run_config`、stage target 或上游 readiness/status。

提交前必须先用统一 builder 构造当前 `job/trade_date/stage` 的 3 个候选 run key，基于 Dagster run history 精确匹配候选 key 统计已有提交次数。下一次 run key 使用 `attempt = submitted_count + 1`；如果 `submitted_count >= 3`，直接 skip。

禁止：

1. 禁止 `attempt-1` 这类自定义字符串段。
2. 禁止 `basic_fact_run_key(...)`、`basic_fact_run_key_prefix(...)` 这类基础事实专属 run key helper。
3. 禁止用 `startswith(...)` 或解析 run key 来推导 `trade_date`、`stage`、`attempt` 或 `run_config`。

### 4.5 Cursor

每个 sensor cursor 必须记录：

1. `target_trade_date`
2. `stage`
3. `stage_start_datetime`
4. `asset_earliest_start_time`
5. `submitted_count_for_stage`
6. `next_attempt`
7. `active_run_id`
8. 关键 upstream readiness status
9. skip reason

cursor 只用于 sensor 决策可观测性，不作为提交次数或 active run 的事实源。提交次数和 active run 以 Dagster run history 为准，cursor 只把本次判断结果写清楚。

### 4.6 分层 job 保持不变

继续保留现有 job 分层：

| 资产族 | raw job | silver job |
| --- | --- | --- |
| stock_basic | `raw_stock_basic_update_job` | `silver_stock_basic_update_job` |
| suspend_d | `raw_suspend_d_update_job` | `silver_suspend_d_update_job` |
| namechange | `raw_namechange_update_job` | `silver_namechange_update_job` |
| identity_map | 不适用 | `stock_identity_map_update_job` |
| adj_factor | `raw_adj_factor_update_job` | `silver_adj_factor_update_job` |

job selection 不扩大。每个 job 仍只写自己的资产和 checks。

### 4.7 依赖门禁替代固定等待

正式口径是依赖编排，不是时间错峰编排。

`09:00/16:00` 打开 stage 后，后续资产只在满足以下条件时提交：

1. 本资产最早触发时间已到。
2. 直接上游本 stage materialization/checks ready。
3. 当前没有同 job/trade_date/stage 的 active run。
4. 当前 stage 提交次数未超过 3 次。

推荐的执行链：

```text
raw_stock_basic
  -> silver_stock_basic
  -> raw_suspend_d
  -> silver_suspend_d
  -> raw_namechange
  -> silver_namechange
  -> silver_stock_identity_map
  -> raw_adj_factor
  -> silver_adj_factor
```

该链路可以通过 polling sensor 的 readiness gate 实现，也可以通过 run-status sensor 做 job-to-job coordination；无论采用哪种实现，都不得让下游只因为“时间到了”就提交 run。

### 4.8 日常链路与历史补缺边界

本轮日常两阶段 sensor 只评估最新一个 `cn_a_stock_current_trade_days` 的当前 stage，不承担历史缺口补分区职责。

原因：

1. 日常链路目标是让当天当前 stage 的基础事实按强顺序完成。如果旧历史缺口进入同一个 sensor，历史 pending 分区可能抢占当天 stage 的执行机会，导致当天 `suspend_d` 未跑，进而阻断 `namechange`、`silver_stock_identity_map`、`adj_factor`。
2. 两阶段 run key 的 scope 是 `trade_date + stage + attempt`。历史补缺没有 morning/afternoon freshness 语义，硬塞进同一链路会制造假的 stage 身份。
3. 日常强顺序链路的失败应该只影响当天当前 stage；历史补缺失败不应污染当天 cursor、active run guard、attempt 计数或下游阻断原因。
4. cursor 应清楚回答“今天当前 stage 为什么跑/不跑”。混入历史 pending keys 会让日常观测口径变乱。

因此，旧 `suspend_d_sensor.py` 中按历史 `cn_a_stock_trade_days` 扫描 backlog、每 tick 提交历史 pending 分区的逻辑，在本轮两阶段日常链路中退场。历史缺口维护需要后续单独设计 maintenance/backlog repair 方案，并单独评估触发入口、run key、执行范围、性能门禁和人工运维口径。

## 5. 建议触发链

### 5.1 stock_basic

`stock_basic` 是本链路第一步。

触发条件：

1. 当前 stage 已开始。
2. `raw_tushare_stock_basic` 本 stage 未 ready，则提交 raw job。
3. `raw_tushare_stock_basic` 本 stage ready 后，`silver_stock_basic` 本 stage 未 ready，则提交 silver job。
4. 如果 materialized 但 blocking checks 失败，允许在同一 job/trade_date/stage 的 3 次提交上限内再次提交；达到上限后停止自动提交，要求人工处理。

### 5.2 suspend_d

触发条件建议：

1. 到达本 stage 的 `suspend_d` 最早触发时间。
2. `stock_basic` raw+silver 本 stage ready。
3. `raw_tushare_suspend_d[trade_date]` 本 stage 未 ready，则提交 raw job。
4. raw 本 stage ready 后，`silver_stock_suspend_daily[trade_date]` 本 stage 未 ready，则提交 silver job。

注意：`suspend_d` 是 partitioned asset。早盘和下午都可能重写同一个 `trade_date` 分区文件，这是本需求的预期行为。

### 5.3 namechange

触发条件建议：

1. 到达本 stage 的 `namechange` 最早触发时间。
2. `suspend_d` raw+silver 本 stage ready。
3. `raw_tushare_namechange` 本 stage 未 ready，则提交 raw job。
4. raw 本 stage ready 后，`silver_namechange` 本 stage 未 ready，则提交 silver job。
5. `silver_namechange` 必须确认跟上本 stage 的 raw namechange、stock basic 与 suspend_d 门禁口径。

### 5.4 silver_stock_identity_map

触发条件建议：

1. 到达本 stage 的 `silver_stock_identity_map` 最早触发时间。
2. `silver_stock_basic` 本 stage ready。
3. `silver_namechange` 本 stage ready。
4. `silver_stock_identity_map` 本 stage 未 ready 或未跟上上述 upstream storage id，则提交 `stock_identity_map_update_job`。

### 5.5 adj_factor

触发条件建议：

1. 到达本 stage 的 `adj_factor` 最早触发时间。
2. `silver_stock_identity_map` 本 stage ready。
3. `raw_tushare_adj_factor[trade_date]` 本 stage 未 ready，则提交 raw job。
4. raw 本 stage ready 且 stock basic raw+silver 本 stage ready 后，`silver_adj_factor[trade_date]` 本 stage 未 ready，则提交 silver job。

当前 `silver_adj_factor_update_job_sensor` 只要求 `stock_basic_ready_without_freshness`。本需求收敛为 stage-aware stock basic readiness。

## 6. 安全性分析

### 6.1 文件写入安全

本需求会让部分资产同一天写两次：

1. full snapshot：`stock_basic`、`namechange`、`silver_stock_identity_map`
2. partitioned：`suspend_d[trade_date]`、`adj_factor[trade_date]`

这在业务上是可接受的，因为这些资产表示“当前阶段看到的最新基础事实”。但实现必须保证：

1. 不并发写同一个 asset/path。
2. 每次写入仍走现有原子替换逻辑。
3. checks 必须绑定最新 materialization。
4. 下游 readiness 必须看本 stage 最新 materialization，不看旧 materialization。

### 6.2 失败阻断

已确认：5 分钟顺序表达的是硬依赖。上游本 stage 未 ready 时，下游不得提交 run。

这意味着上游失败会阻断后续资产。例如 `suspend_d` 下午失败会阻断 `namechange`、`identity_map`、`adj_factor`。该行为符合本需求对执行顺序的要求。

同一 stage 最多提交 3 次 run。达到 3 次后仍失败或未 ready，sensor 必须停止继续提交，并在 cursor/skip reason 中明确说明达到重试上限。

### 6.3 Sensor tick 精度

当前多个 sensor 的 `minimum_interval_seconds` 是 600 秒。已确认本需求改为 300 秒。

Dagster sensor 不是精确 cron；实际触发时间可能晚于目标时间。因此设计只能保证“不早于某时间触发”，不能保证“精确 09:05 触发”。执行顺序不依赖 tick 精度，而依赖上游 readiness。

### 6.4 并发保护

active run guard 是硬门禁。同一 asset/path 不能出现早盘未结束、下午又开始写，或同一 stage 重复提交多个 run 的情况。

sensor 提交 run 前必须检查同一 job/trade_date/stage 是否已经存在 active run。active run 至少包括：

```text
QUEUED
NOT_STARTED
STARTING
STARTED
CANCELING
```

如存在 active run，sensor 返回 skip，不提交新 run。

### 6.5 与下游资产关系

本需求只统一基础事实链。股票日线、分钟线、qfq、MACD/KDJ 等下游资产仍通过 readiness 消费这些基础事实，不把基础事实加入自己的 job selection。

## 7. 实现影响面

预计涉及代码：

| 文件 | 变更 |
| --- | --- |
| `defs/sensors/stock_basic_sensor.py` | 改用 `cn_a_stock_current_trade_days`；增加 stage；run key 带 stage/attempt；支持本日两次刷新 |
| `defs/sensors/suspend_d_sensor.py` | 改用 `cn_a_stock_current_trade_days`；允许同日同分区按 stage 重刷；增加 stock_basic stage gate；日常链路不再承担历史 backlog 补缺 |
| `defs/sensors/stock_namechange_sensor.py` | 调整 stage 时间到 09:10/16:10；raw 等待 suspend_d 本 stage ready；run key 使用 stage/attempt |
| `defs/sensors/stock_identity_map_sensor.py` | 改用 `cn_a_stock_current_trade_days`；时间改为 09:15/16:15；run key 带 stage/attempt |
| `defs/sensors/stock_adj_factor_sensor.py` | 时间改为 09:20/16:20；raw 等待 identity_map；silver 的 stock_basic gate 改为 stage-aware freshness |
| `defs/sensors/readiness.py` | 增加 materialization timestamp / stage-aware readiness helper |
| `defs/sensors/basic_fact_stage.py` | 新增两阶段时间、目标日期、stage target 解析 |
| `defs/sensors/basic_fact_run_guards.py` | 新增 active run guard、3 次提交上限和候选 attempt run key 精确匹配；run key 只能由统一 builder 生成 |
| tests | 覆盖两阶段触发、重复提交、失败阻断、stage readiness、run key 和 cursor |
| docs | 同步既有 Dagster 拓扑、namechange、adj factor、stock identity map 设计文档 |

不预计修改：

1. asset key
2. job 名称
3. asset path
4. Parquet schema
5. blocking check 名称
6. 正式 Dagster instance

## 8. 详细编码方案

### 8.1 硬口径到代码落点

| 已拍板口径 | 代码落点 | 测试门禁 |
| --- | --- | --- |
| 统一读取 `cn_a_stock_current_trade_days` | `stock_basic_sensor.py`、`suspend_d_sensor.py`、`stock_identity_map_sensor.py` 从 `cn_a_stock_trade_days` 改为 `cn_a_stock_current_trade_days`；`namechange`、`adj_factor` 保持 current trade day 口径 | 静态扫描这些基础事实 sensor 不再 import/use `cn_a_stock_trade_days` |
| 两阶段时间固定为 09:00/16:00 链式启动 | 新增 `defs/sensors/basic_fact_stage.py`，集中定义 stage、资产最早时间和目标日期选择 | stage helper 单测覆盖 08:59、09:00、09:05、09:10、09:15、09:20、15:59、16:00、16:20 |
| 依赖门禁替代固定等待 | 五个 sensor 都先解析 stage target，再检查直接上游本 stage readiness | 下游时间已到但上游本 stage 未 ready 时不提交 run |
| full snapshot 用 materialization timestamp 判断本 stage freshness | `defs/sensors/readiness.py` 支持 `min_materialization_datetime`；新增 stage readiness wrapper | 早盘 materialization 在下午 stage 不算 ready；下午 materialization 才算 ready |
| partitioned asset 同日两次重写 | `suspend_d_sensor.py`、`stock_adj_factor_sensor.py` 不再用 `materialized_partition_keys` 做“存在即跳过”，改用 stage readiness | 同一 `trade_date` 上午已 materialized，下午仍可提交同分区 run |
| 同一 job/trade_date/stage 最多提交 3 次 | 新增 `defs/sensors/basic_fact_run_guards.py`，用 `build_repair_attempt_run_key(...)` 构造 1..3 候选 key，并从 Dagster run history 精确匹配候选 key 统计提交数 | 第 1、2、3 次可提交；第 4 次 skip，cursor 写明达到上限 |
| active run guard 是硬门禁 | `basic_fact_run_guards.py` 用 `RunsFilter(job_name=..., statuses=ACTIVE_STATUSES, created_after=stage_start)` 查询窄范围 run，再按候选 run key 集合精确匹配 active run | 存在 active run 时不提交；即使当前 asset stale 也 skip |
| sensor tick 间隔 300 秒 | 五个基础事实 sensor decorator 改为 `minimum_interval_seconds=300` | 静态测试断言这些 sensor 的 `minimum_interval_seconds == 300` |
| sensor 默认 `STOPPED` | 五个基础事实 sensor 保持 `default_status=dg.DefaultSensorStatus.STOPPED` | 静态测试断言 default status 不变 |
| 不做大 job、不扩大 selection | `defs/jobs/**` 不改 selection；sensor 仍触发现有 raw/silver job | 既有 job selection contract 测试继续覆盖 raw/silver 分层 |
| 历史补缺不混入日常两阶段 sensor | `suspend_d_sensor.py` 只评估最新 current trade day 当前 stage；旧 backlog 扫描逻辑退出日常链路 | 历史缺失分区存在时，日常 sensor 仍优先评估当天 current trade day；不因历史 pending keys 抢占当天 stage |

### 8.2 新增 stage 策略模块

新增文件：

```text
lake_console/orchestrator/src/orchestrator/defs/sensors/basic_fact_stage.py
```

职责只放两阶段基础事实 sensor 的稳定策略，不放 Dagster run 查询，不放 readiness 查询。

建议结构：

```python
BASIC_FACT_SENSOR_MINIMUM_INTERVAL_SECONDS = 300
BASIC_FACT_MAX_STAGE_SUBMISSIONS = 3

BasicFactAssetName = Literal[
    "stock_basic",
    "suspend_d",
    "namechange",
    "stock_identity_map",
    "adj_factor",
]
BasicFactStageName = Literal["morning", "afternoon"]

@dataclass(frozen=True)
class BasicFactStageTarget:
    asset_name: BasicFactAssetName
    trade_date: str
    stage: BasicFactStageName
    stage_start_datetime: datetime
    asset_earliest_datetime: datetime
```

核心函数：

```python
latest_registered_current_trade_date(
    instance: dg.DagsterInstance,
    evaluated_at: datetime,
) -> str | None

resolve_basic_fact_stage_target(
    instance: dg.DagsterInstance,
    evaluated_at: datetime,
    asset_name: BasicFactAssetName,
) -> BasicFactStageTarget | None
```

stage 名称只允许：

```text
morning
afternoon
```

旧 `namechange` 里的 `evening` stage 不再继续产生。新 cursor 和 run key 统一写 `afternoon`。

### 8.3 新增 run 提交门禁模块

新增文件：

```text
lake_console/orchestrator/src/orchestrator/defs/sensors/basic_fact_run_guards.py
```

职责：

1. 使用 `build_repair_attempt_run_key(...)` 构造同一 `job/trade_date/stage` 的 1..3 候选 run key。
2. 从 Dagster run history 精确匹配候选 run key，统计同一 `job/trade_date/stage` 已提交次数。
3. 检查同一 `job/trade_date/stage` 是否存在 active run。
4. 给 sensor 返回是否允许提交、下一次 attempt、skip reason。

不新增自定义 run tag。仍使用当前 `build_run_request(...)`，依赖 Dagster 自动写入的 `dagster/run_key` 系统 tag。

本地 Dagster API introspection 已确认：

```text
RunsFilter(job_name=..., statuses=..., tags=..., created_after=...)
RUN_KEY_TAG = "dagster/run_key"
```

建议结构：

```python
from dagster._core.storage.dagster_run import RunsFilter
from dagster._core.storage.tags import RUN_KEY_TAG

BASIC_FACT_ACTIVE_RUN_STATUSES = (
    dg.DagsterRunStatus.QUEUED,
    dg.DagsterRunStatus.NOT_STARTED,
    dg.DagsterRunStatus.STARTING,
    dg.DagsterRunStatus.STARTED,
    dg.DagsterRunStatus.CANCELING,
)

@dataclass(frozen=True)
class BasicFactRunSubmissionState:
    allowed: bool
    repair_scope_id: str
    candidate_run_keys: tuple[str, ...]
    submitted_count: int
    next_attempt: int | None
    active_run_id: str | None
    reason: str
```

候选 run key 只能通过统一 builder 生成：

```python
candidate_run_keys = tuple(
    build_repair_attempt_run_key(
        subject=subject,
        repair_scope_id=f"{trade_date}:{stage}",
        attempt=attempt,
    )
    for attempt in range(1, max_attempts + 1)
)
```

`subject` 使用现有稳定身份：

```text
raw_stock_basic_update
silver_stock_basic_update
raw_suspend_d_update
silver_suspend_d_update
raw_namechange_update
silver_namechange_update
stock_identity_map
raw_adj_factor_update
silver_adj_factor_update
```

提交门禁：

```python
evaluate_basic_fact_run_submission(
    instance: dg.DagsterInstance,
    *,
    job_name: str,
    subject: str,
    trade_date: str,
    stage: BasicFactStageName,
    stage_start_datetime: datetime,
    max_attempts: int = BASIC_FACT_MAX_STAGE_SUBMISSIONS,
) -> BasicFactRunSubmissionState
```

查询策略：

1. 先用 `build_repair_attempt_run_key(...)` 构造 1..3 的 `candidate_run_keys`。
2. 用 `RunsFilter(job_name=job_name, created_after=stage_start_datetime)` 做窄范围查询。
3. 只统计 `run.tags.get(RUN_KEY_TAG) in set(candidate_run_keys)` 的 run。
4. active run 另用 `statuses=BASIC_FACT_ACTIVE_RUN_STATUSES` 过滤，并继续只按候选 run key 精确匹配。
5. 如果 Dagster 当前版本的 `RunsFilter.tags` 支持同一 tag 多值过滤，可以把 `tags={RUN_KEY_TAG: candidate_run_keys}` 作为窄化条件；否则先按 job/time/status 查询，再在 Python 中做精确集合匹配。两种方式都禁止 prefix/startswith。
6. 如果存在 active run，`allowed=False`，不计算新的 RunRequest。
7. 如果 `submitted_count >= 3`，`allowed=False`，skip reason 写明达到上限。
8. 否则 `next_attempt=submitted_count + 1`。

### 8.4 readiness.py stage freshness 改造

当前 `AssetReadinessStatus` 只有 `materialization_date`，只能表达“当天是否更新过”。本需求必须判断本地 materialization timestamp 是否晚于 stage start。

修改 `AssetReadinessStatus`，在字段末尾增加默认值字段，降低对现有测试构造器的冲击：

```python
materialization_timestamp: float | None = None
materialization_datetime: str | None = None
freshness_required_datetime: str | None = None
```

扩展内部函数：

```python
_local_materialization_datetime(record) -> datetime

asset_readiness_status(
    ...,
    min_materialization_date: str | None = None,
    min_materialization_datetime: datetime | None = None,
) -> AssetReadinessStatus

dataset_readiness_status(
    ...,
    min_materialization_date: str | None = None,
    min_materialization_datetime: datetime | None = None,
) -> DatasetReadinessStatus
```

freshness 判断口径：

```text
date freshness 通过 =
  min_materialization_date is None
  OR materialization local date >= min_materialization_date

stage freshness 通过 =
  min_materialization_datetime is None
  OR materialization local datetime >= min_materialization_datetime

freshness_passed = date freshness 通过 AND stage freshness 通过
```

新增 stage readiness wrapper：

```python
raw_tushare_stock_basic_ready_for_stage(instance, stage_start_datetime)
silver_stock_basic_ready_for_stage(instance, stage_start_datetime)
stock_basic_ready_for_stage(instance, stage_start_datetime)

raw_tushare_suspend_d_ready_for_stage(instance, trade_date, stage_start_datetime)
silver_suspend_d_ready_for_stage(instance, trade_date, stage_start_datetime)
suspend_d_ready_for_stage(instance, trade_date, stage_start_datetime)

raw_tushare_namechange_ready_for_stage(instance, stage_start_datetime)
silver_namechange_ready_for_stage(instance, stage_start_datetime)

silver_stock_identity_map_ready_for_stage(instance, stage_start_datetime)

raw_tushare_adj_factor_ready_for_stage(instance, trade_date, stage_start_datetime)
silver_adj_factor_ready_for_stage(instance, trade_date, stage_start_datetime)
adj_factor_ready_for_stage(instance, trade_date, stage_start_datetime)
```

保留现有 `*_ready_for_trade_date` 和 `stock_basic_ready_without_freshness`，因为其它链路仍在使用；本轮只是让基础事实两阶段 sensor 改用 stage wrapper。

### 8.5 各 sensor 具体改法

#### 8.5.1 stock_basic

文件：

```text
defs/sensors/stock_basic_sensor.py
```

改动：

1. import `cn_a_stock_current_trade_days`，不再使用 `cn_a_stock_trade_days`。
2. 删除本文件内 `_latest_registered_trade_date`，改用 `latest_registered_current_trade_date(...)`。
3. decorator `minimum_interval_seconds=300`，`default_status` 保持 `STOPPED`。
4. raw sensor 使用 `resolve_basic_fact_stage_target(..., "stock_basic")`。
5. raw readiness 使用 `raw_tushare_stock_basic_ready_for_stage(instance, stage_start_datetime)`。
6. silver readiness 使用 `silver_stock_basic_ready_for_stage(...)`，raw 前置使用 `raw_tushare_stock_basic_ready_for_stage(...)`。
7. 提交前调用 `evaluate_basic_fact_run_submission(...)`。
8. run key 使用 `build_repair_attempt_run_key(subject="raw_stock_basic_update", repair_scope_id=f"{trade_date}:{stage}", attempt=n)` / `build_repair_attempt_run_key(subject="silver_stock_basic_update", repair_scope_id=f"{trade_date}:{stage}", attempt=n)`。
9. checks 失败不再直接永久人工阻断；在 3 次提交上限内允许再次提交，达到上限后 skip。
10. cursor details 写入 `stage`、`stage_start_datetime`、`asset_earliest_datetime`、`submitted_count_for_stage`、`next_attempt`、`active_run_id`、readiness details。

#### 8.5.2 suspend_d

文件：

```text
defs/sensors/suspend_d_sensor.py
```

改动：

1. import `cn_a_stock_current_trade_days`，不再使用 `cn_a_stock_trade_days`。
2. 不再按旧股票交易日集合做 backlog 批量补缺；本需求只评估最新一个 current trade day 的当前 stage。
3. `MAX_RUN_REQUESTS_PER_TICK` 对本链路不再需要；日常两阶段 sensor 每次最多提交当前 target 的一个 run request。
4. raw sensor 在 `stock_basic_ready_for_stage(...)` ready 后才可提交。
5. raw readiness 使用 `raw_tushare_suspend_d_ready_for_stage(instance, trade_date, stage_start_datetime)`，不能再用 `materialized_partition_keys` 判断“已存在就跳过”。
6. silver sensor 依赖 `stock_basic_ready_for_stage(...)` 与 `raw_tushare_suspend_d_ready_for_stage(...)`。
7. silver readiness 使用 `silver_suspend_d_ready_for_stage(...)`。
8. run key 使用 `build_repair_attempt_run_key(subject="raw_suspend_d_update", repair_scope_id=f"{trade_date}:{stage}", attempt=n)` / `build_repair_attempt_run_key(subject="silver_suspend_d_update", repair_scope_id=f"{trade_date}:{stage}", attempt=n)`。
9. cursor 写明 stock_basic gate、raw gate、stage freshness 和提交次数。

#### 8.5.3 namechange

文件：

```text
defs/sensors/stock_namechange_sensor.py
```

改动：

1. 删除本文件内 `STOCK_NAMECHANGE_RUN_START`、`STOCK_NAMECHANGE_EVENING_RUN_START`、`STOCK_NAMECHANGE_MORNING_STAGE`、`STOCK_NAMECHANGE_EVENING_STAGE` 等私有 stage 常量，统一使用 `basic_fact_stage.py`。
2. stage 名从旧 `evening` 改为 `afternoon`。
3. raw sensor 最早时间改为 09:10/16:10。
4. raw sensor 直接上游改为 `suspend_d_ready_for_stage(instance, trade_date, stage_start_datetime)`。
5. raw readiness 使用 `raw_tushare_namechange_ready_for_stage(...)`。
6. silver sensor 依赖 `raw_tushare_namechange_ready_for_stage(...)`，并继续确认 `stock_basic_ready_for_stage(...)`。
7. silver readiness 使用 `silver_namechange_ready_for_stage(...)`，并继续用 upstream storage id 判断是否跟上 raw 与 stock_basic。
8. `_already_submitted_for_stage(...)` 退场，改用 `evaluate_basic_fact_run_submission(...)`；cursor 不再把“已经提交过一次”当硬事实。
9. run key 使用 `build_repair_attempt_run_key(subject="raw_namechange_update", repair_scope_id=f"{trade_date}:{stage}", attempt=n)` / `build_repair_attempt_run_key(subject="silver_namechange_update", repair_scope_id=f"{trade_date}:{stage}", attempt=n)`。

#### 8.5.4 silver_stock_identity_map

文件：

```text
defs/sensors/stock_identity_map_sensor.py
```

改动：

1. import `cn_a_stock_current_trade_days`，不再使用 `cn_a_stock_trade_days`。
2. 最早时间改为 09:15/16:15。
3. `STOCK_IDENTITY_MAP_RUN_START` 退场，统一使用 stage helper。
4. 上游保持 `silver_stock_basic` + `silver_namechange`，但都必须用 stage readiness。
5. identity map 自身 readiness 使用 `silver_stock_identity_map_ready_for_stage(...)`。
6. `_identity_map_decision(...)` 增加 stage-aware 输入，保持 “identity materialization storage id >= upstream latest storage id” 的 current 判断。
7. 提交前调用 active run / 3 次上限门禁。
8. run key 使用 `build_repair_attempt_run_key(subject="stock_identity_map", repair_scope_id=f"{trade_date}:{stage}", attempt=n)`。

#### 8.5.5 adj_factor

文件：

```text
defs/sensors/stock_adj_factor_sensor.py
```

改动：

1. 最早时间改为 09:20/16:20。
2. raw sensor 直接上游改为 `silver_stock_identity_map_ready_for_stage(...)`。
3. raw readiness 使用 `raw_tushare_adj_factor_ready_for_stage(instance, trade_date, stage_start_datetime)`，不再用 `materialized_partition_keys` 做“已存在跳过”。
4. silver sensor 依赖 `raw_tushare_adj_factor_ready_for_stage(...)` 与 `stock_basic_ready_for_stage(...)`。
5. 删除本 sensor 对 `stock_basic_ready_without_freshness` 的 import 和调用。
6. `_silver_sensor_cursor(...)` 中 `stock_basic_freshness_required` 固定为 `True`，并记录 `stage_start_datetime`。
7. silver readiness 使用 `silver_adj_factor_ready_for_stage(...)`，同日早盘已 materialized 但下午未重刷时必须判为 stale。
8. run key 使用 `build_repair_attempt_run_key(subject="raw_adj_factor_update", repair_scope_id=f"{trade_date}:{stage}", attempt=n)` / `build_repair_attempt_run_key(subject="silver_adj_factor_update", repair_scope_id=f"{trade_date}:{stage}", attempt=n)`。

### 8.6 Cursor 统一字段

五个 sensor 的 cursor details 必须至少包含：

```text
target_trade_date
stage
stage_start_datetime
asset_earliest_datetime
submitted_count_for_stage
next_attempt
active_run_id
repair_scope_id
candidate_run_keys
reason
readiness_details
```

如果因为时间未到、无 current trade day、active run 存在或 3 次上限而 skip，也必须写入对应 reason。cursor 里不再使用 `already_submitted_for_trade_date` 作为硬门禁字段。

### 8.7 测试文件落点

预计更新：

```text
tests/test_stock_basic_namechange_split_contracts.py
tests/test_suspend_d_sensor.py
tests/test_adj_factor_m4_contracts.py
tests/test_stock_identity_map_active_asset.py
tests/test_run_contract_run_keys.py
tests/test_run_contract_static_gates.py
```

建议新增：

```text
tests/test_basic_fact_two_stage_sensor_gates.py
```

新增测试文件集中覆盖：

1. stage helper 的时间解析和 current trade day 选择。
2. stage readiness 的 timestamp 判断。
3. active run guard 的 `RunsFilter` 查询和候选 run key 精确匹配。
4. 同一 stage 第 1/2/3 次提交与第 4 次 skip。
5. 同一 job/trade_date/stage 有 active run 时 skip。
6. `namechange` 不再产出 `evening` stage。
7. `build_repair_attempt_run_key(...)` 生成的基础事实两阶段 run key 输出为 `{subject}:{trade_date}:{stage}:{attempt}`，且不会出现 `attempt-`。

### 8.8 静态门禁

`test_run_contract_static_gates.py` 增加扫描：

1. 基础事实两阶段 sensor 不得 import `cn_a_stock_trade_days`。
2. 基础事实两阶段 sensor 的 `minimum_interval_seconds` 必须是 300。
3. 基础事实两阶段 sensor 的 `default_status` 必须是 `STOPPED`。
4. `stock_adj_factor_sensor.py` 不得调用 `stock_basic_ready_without_freshness`。
5. `suspend_d_sensor.py` 与 `stock_adj_factor_sensor.py` 不得用 `materialized_partition_keys` 作为日常 skip 主门禁。
6. 两阶段基础事实 sensor 的 `run_key=` 必须直接使用 `build_repair_attempt_run_key(...)`，不得手写字符串、不得调用基础事实专属 run key helper、不得使用 `attempt-` 字符串段。
7. `basic_fact_run_guards.py` 不得定义 `basic_fact_run_key(...)`、`basic_fact_run_key_prefix(...)`，不得用 `startswith(...)` 匹配 run key。
8. 不新增 job，不扩大 job selection。

### 8.9 验证命令

本轮实现完成后建议只跑静态和单元测试，不运行 Dagster job/sensor/backfill：

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator
uv run pytest \
  tests/test_basic_fact_two_stage_sensor_gates.py \
  tests/test_stock_basic_namechange_split_contracts.py \
  tests/test_suspend_d_sensor.py \
  tests/test_adj_factor_m4_contracts.py \
  tests/test_stock_identity_map_active_asset.py \
  tests/test_run_contract_run_keys.py \
  tests/test_run_contract_static_gates.py
```

禁止验证动作：

1. 不运行 Dagster job。
2. 不启动 sensor。
3. 不做 materialization、asset check、backfill。
4. 不读取或修改正式 Dagster instance 状态。
5. 不写 Parquet 或业务数据库。

## 9. 测试计划

### 9.1 Stage helper 与依赖门禁

1. 08:59 不返回可触发 stage。
2. 09:00 `stock_basic` 可触发 morning。
3. 09:04 `suspend_d` 不可触发。
4. 09:05 `suspend_d` 可触发 morning。
5. 16:00 `stock_basic` 可触发 afternoon。
6. 非交易日不触发。
7. 时间已到但上游本 stage 未 ready 时，不提交下游 run。

### 9.2 stock_basic

1. `cn_a_stock_current_trade_days` 注册今天，09:00 后 raw stale -> 提交 morning raw run。
2. morning raw ready 后 silver stale -> 提交 morning silver run。
3. 16:00 后即使今天上午已 ready，仍因 afternoon stage freshness 不满足而提交 afternoon raw/silver。
4. checks 失败时最多提交 3 次，达到上限后不再自动提交。
5. 存在同 job/trade_date/stage active run 时不重复提交。

### 9.3 suspend_d

1. 改用 `cn_a_stock_current_trade_days`。
2. 同一 trade_date 上午已 materialized，下午仍可因 stage freshness 不满足而提交同分区 run。
3. stock_basic stage 未 ready 时不提交。
4. 同一 stage 最多提交 3 次。
5. 存在同 job/trade_date/stage active run 时不重复提交。
6. 历史缺失分区不进入本轮日常两阶段 sensor 的 selected keys；不能抢占当天 current trade day 的 stage 执行。

### 9.4 namechange

1. 09:10/16:10 才允许触发。
2. suspend_d raw+silver 本 stage 未 ready 时 raw skip。
3. raw 本 stage ready 后 silver 才可触发。
4. silver 必须跟上 raw 与 stock_basic 的本 stage materialization。
5. 同一 stage 最多提交 3 次。
6. 存在同 job/trade_date/stage active run 时不重复提交。
7. 不再产出 `evening` stage，下午统一写 `afternoon`。

### 9.5 identity_map

1. 使用 `cn_a_stock_current_trade_days`。
2. 09:15/16:15 才允许触发。
3. `silver_stock_basic` 与 `silver_namechange` 本 stage ready 后才提交。
4. run key 带 stage 和 attempt。
5. 同一 stage 最多提交 3 次。
6. 存在同 job/trade_date/stage active run 时不重复提交。

### 9.6 adj_factor

1. 09:20/16:20 才允许触发。
2. raw/silver 同一 trade_date 可按 stage 重刷。
3. raw 等待 `silver_stock_identity_map` 本 stage ready。
4. silver 不再使用 `stock_basic_ready_without_freshness` 作为本链路门禁，而使用 stage-aware stock basic readiness。
5. 同一 stage 最多提交 3 次。
6. 存在同 job/trade_date/stage active run 时不重复提交。

### 9.7 静态门禁

1. 这些基础事实 sensor 不得继续读取 `cn_a_stock_trade_days` 作为目标日期。
2. 两阶段基础事实 sensor 的 run key 必须通过 `build_repair_attempt_run_key(...)` 表达 `trade_date`、`stage` 和 `attempt`。
3. 不新增组合大 job。
4. 不新增 summary asset、readiness asset、数据库表。
5. 不修改 asset key/job 名称/check 名称。
6. sensor `minimum_interval_seconds` 必须为 300。
7. sensor `default_status` 必须保持 `STOPPED`。

## 10. 已拍板口径

### 10.1 执行顺序

已确认：5 分钟间隔是为了表达执行顺序，不是单纯错峰。正式实现必须使用依赖门禁，时间只作为最早提交窗口。

```text
raw_stock_basic
  -> silver_stock_basic
  -> raw_suspend_d
  -> silver_suspend_d
  -> raw_namechange
  -> silver_namechange
  -> silver_stock_identity_map
  -> raw_adj_factor
  -> silver_adj_factor
```

下游 sensor 不能只因为时间到了就提交 run，必须看到直接上游在本 stage 已 materialized 且 blocking checks 通过。

### 10.2 suspend_d 每天两次重写同一分区

已确认允许。同一 `trade_date` 分区可以在 morning 和 afternoon 两个 stage 分别重写。

### 10.3 adj_factor 每天两次重写同一分区

已确认允许。同一 `trade_date` 分区可以在 morning 和 afternoon 两个 stage 分别重写。

### 10.4 `silver_adj_factor` 的 stock_basic 门禁

已确认：`silver_adj_factor` 必须依赖 stock basic 本 stage freshness，不能继续使用只检查历史存在性的 stock basic 门禁。

### 10.5 Sensor 最小 tick 间隔

已确认使用：

```text
minimum_interval_seconds = 300
```

### 10.6 Sensor default status

已确认：代码默认继续 `STOPPED`，由正式 Dagster instance 人工启用。

### 10.7 同 stage 失败后的提交上限

已确认：同一 job/trade_date/stage 最多提交 3 次 run。达到 3 次后仍失败或未 ready，sensor 不再自动提交，需要人工处理。

这不是无限自动重试；提交次数必须从 Dagster run history 中按统一 builder 生成的 1..3 候选 run key 精确匹配推导，cursor 只记录本次判断结果，后续 tick 不得突破 3 次上限。

### 10.8 Active run guard

已确认：active run guard 是硬门禁，必须确保不会重复提交 run。

active run guard 的含义是：提交 run 前检查同一 job/trade_date/stage 是否存在未完成 run；如果存在，则本次 tick 只 skip，不提交新的 run。

active run 至少包括：

```text
QUEUED
NOT_STARTED
STARTING
STARTED
CANCELING
```

### 10.9 历史补缺边界

已确认本轮选择 A：先做日常两阶段链路，历史缺口维护不混入本轮 sensor。

正式口径：

1. 日常两阶段 sensor 只评估最新一个 `cn_a_stock_current_trade_days` 的当前 stage。
2. 旧 `suspend_d_sensor.py` 的历史 backlog 扫描和每 tick 补历史 pending 分区逻辑，不进入本轮日常两阶段链路。
3. 历史缺口维护后续单独做 maintenance/backlog repair 方案，不在本轮新增入口、不自动化、不影响当天基础事实强顺序链路。
4. 如果正式环境存在历史缺口，本轮日常链路不能让历史 pending keys 抢占当天 current trade day 的 run request。

## 11. 建议落地顺序

按 8 个 milestone 分批落地：

1. **M1：基础 stage/freshness 能力**。实现 `basic_fact_stage.py` 和 `readiness.py` stage freshness。
2. **M2：run guard / run key / attempt 预算**。实现 `basic_fact_run_guards.py`，包含 active run guard、3 次提交上限和候选 attempt run key 精确匹配；不得新增基础事实专属 run key helper。
3. **M3：迁移 stock_basic**。迁移 `stock_basic` 到 `cn_a_stock_current_trade_days` 与两阶段 run key。
4. **M4：迁移 suspend_d**。迁移 `suspend_d` 到 current trade day、stock_basic stage gate 和同分区两阶段重刷；历史 backlog 补缺逻辑退出日常链路。
5. **M5：迁移 namechange**。迁移 `namechange` 到 09:10/16:10、`afternoon` stage 和 suspend_d 上游门禁。
6. **M6：迁移 silver_stock_identity_map**。迁移 `identity_map` 到 09:15/16:15 与 stage-aware upstream。
7. **M7：迁移 adj_factor**。迁移 `adj_factor` 到 09:20/16:20、identity_map 上游门禁与 stock_basic stage freshness。
8. **M8：静态门禁、回归、文档收口**。补静态门禁，防止这些基础事实 sensor 回到 `cn_a_stock_trade_days`、只按 `trade_date`/`stage` run key、手写 run key、prefix 匹配 run key、使用 `attempt-` 字符串段，或让历史 backlog 抢占日常 current trade day；同步既有拓扑和资产设计文档。

## 12. 验收标准

实现完成后，应满足：

1. 交易日 09:00 后基础事实链按 `cn_a_stock_current_trade_days[今日]` 进入 morning stage。
2. 交易日 16:00 后同一批资产按 `cn_a_stock_current_trade_days[今日]` 进入 afternoon stage。
3. `silver_namechange` 不再因为 `stock_basic` 仍停留前一交易日而在上午被卡住。
4. 同一天早盘和下午 run key 不冲突，同一 stage 的第 1/2/3 次提交 run key 也不冲突。
5. 当前 stage readiness 不会被同一天上一 stage 的 materialization 误判为 ready。
6. 不新增大 job，不扩大 job selection。
7. 不新增状态表或 summary asset。
8. 失败时 cursor 能明确说明是时间未到、上游未 ready、checks 失败、active run 存在，还是同 stage 已达到 3 次提交上限。
9. 同一 job/trade_date/stage 存在 active run 时，sensor 不会重复提交 run。
10. 同一 job/trade_date/stage 的提交次数由 Dagster run history 推导，不依赖 cursor 作为事实源。
11. 历史缺失分区不会进入日常两阶段 sensor 的 run request 选择；当天 current trade day 的 stage 执行不会被历史 pending keys 抢占。
