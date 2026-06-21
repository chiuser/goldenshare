# Dagster 非股票分钟线连续性治理专项方案

更新时间：2026-06-21

## 1. 背景

股票分钟线连续性专项已经解决了 `stk_mins` raw / silver / qfq / MACD-KDJ 链路中的停机补洞问题：目标日期不再来自 latest registered partition，而是来自交易日历 expected dates、注册缺口、first not-ready frontier 和精确 previous expected state。

但本次停机暴露出另一个问题：非分钟线资产族仍存在不同程度的补洞能力差异。典型现象是 Dagster 停机期间漏注册或漏更新某些日频资产，恢复后部分 sensor 只看 latest partition，可能跳过更早缺口，导致后续资产基于不完整上游继续生产。

本专项目标不是重做股票分钟线逻辑，而是把同一类“停机后不能跳过空洞”的原则推广到非分钟线日频资产族，并明确哪些资产应该做历史连续补洞，哪些资产本质上是 current snapshot，不应该按历史日期逐日补。

本专项后续代码推进前，必须先完成通用显式补洞基础能力：

[Dagster Bounded Continuity Selector 基础能力专项方案](dagster-bounded-continuity-selector-foundation-plan.md)

该基础能力用于统一 expected calendar、registered gap guard、batch readiness、first-not-ready、cursor 和性能门禁。非分钟线历史连续资产后续不得各自临时实现一套近似但不一致的补洞选择逻辑。

对应 LLD：

1. [Dagster Bounded Continuity Selector 基础能力 LLD](dagster-bounded-continuity-selector-foundation-low-level-design.md)
2. [Dagster Market Major Indices Sensor 热路径性能治理 LLD](dagster-market-major-indices-sensor-performance-governance-low-level-design.md)
3. [Dagster 非股票分钟线连续性治理 LLD](dagster-non-stk-mins-continuity-governance-low-level-design.md)

## 2. 当前审计结论

本轮只读审计覆盖以下代码入口：

| 资产族 | 关键入口 | 当前结论 |
| --- | --- | --- |
| 股票普通交易日注册 | `stock_trade_day_sensor.py` -> `build_trade_day_partition_registration_result(...)` | 已具备 calendar-backed catch-up，每 tick 最多注册 2 个缺失交易日。 |
| 指数交易日注册 | `index_trade_day_sensor.py` -> `build_trade_day_partition_registration_result(...)` | 已具备 calendar-backed catch-up。 |
| 股票当前交易日注册 | `stock_current_trade_day_sensor.py` | today-only，只注册当天；停机错过当天后不会自动补该 current partition。 |
| 股票日线 raw / silver | `stock_daily_sensor.py` | 已接入最近 60 个 expected stock trade dates 的 registered gap guard；在注册缺口存在时先 skip，不读取 materialized partition set，不提交后续日期；注册连续后保留原有每 tick 最多 2 个 run、selected-date readiness 和 missing-code repair 逻辑。 |
| 停复牌 raw / silver | `suspend_d_sensor.py` | 已接入最近 60 个 expected stock trade dates 的 registered gap guard；在注册缺口存在时先 skip，不读取 materialized partition set / raw readiness，不提交后续日期；注册连续后保留原有 raw/silver registered 内补洞逻辑。 |
| 复权因子 raw / silver | `stock_adj_factor_sensor.py` | 已接入 bounded expected current trade day window、registered gap guard 和 batch lake readiness；不再以 latest registered current trade day 作为正式目标。 |
| 指数日线 raw | `index_daily_sensor.py` | 已对最近 60 个 expected index trade dates 增加 registered gap guard；注册缺口存在时不进入 raw gap audit / source readiness；注册连续后保留 raw gap audit、latest presence 与 late-arrival repair。 |
| 指数日线 silver | `silver_index_daily_sensor.py` | 已对最近 60 个 expected index trade dates 增加 registered gap guard；注册缺口存在时不进入 raw gap audit / silver selector；注册连续后保留 raw gap audit 与 first not-ready silver selector。 |
| 主要指数日线 gold | `market_major_indices_daily_sensor.py` | 已改为最近 60 个 expected index trade dates 的 registered gap guard + first not-ready gold；gold / selected-date silver / selected-date index basic readiness 已从旧 Dagster event-history wrapper 切到 DuckDB/lake readiness。 |
| 股票基础、曾用名、身份映射 | `stock_basic_sensor.py`、`stock_namechange_sensor.py`、`stock_identity_map_sensor.py` | 属于 full snapshot / current fact 类资产，不应按历史日期逐日补。 |
| 市场宽度、涨跌分布、ClickHouse serving | `market_breadth_continuity_sensor.py`、`stock_return_distribution_continuity_sensor.py`、`clickhouse_market_breadth_continuity_sensor.py` | P6 已退出默认 eager active 入口，改为显式 bounded continuity sensor；旧 `AutomationConditionSensorDefinition` 文件已删除，四个 asset 上的 `automation_condition` 已移除。 |

### 2.1 2026-06-21 代码现状对账

本节是进入 LLD 前的代码事实收口，不代表已实现。

| 代码事实 | 结论 | LLD 约束 |
| --- | --- | --- |
| `stock_current_trade_day_sensor.py` 中 `build_stock_current_trade_day_registration_decision(...)` 仍只围绕 today 判断。 | P1 仍需把 today-only 改成 bounded catch-up。 | P1 必须删除 today-only 正式口径，改用最近 60 个 expected current trade days。 |
| `stock_adj_factor_sensor.py` 已移除 `_latest_registered_trade_date(...)` 和单日 adj factor readiness wrapper。 | P2C 已迁移为 first missing / first not-ready。 | 后续静态门禁必须防止 latest registered 和逐日 Dagster readiness 回流。 |
| 已存在 `silver_stock_lifecycle` 正式 asset / path / catalog / checks / readiness。 | P2A 已完成。 | 后续历史生命周期判断以该 silver 事实为准。 |
| `silver_stock_daily`、股票分钟线 lifecycle/name timeline、lake readiness、runless dry-run helper 已迁移到 `silver_stock_lifecycle`。 | P2B 已完成。 | 长期生命周期消费者不得再直接调用 `historical_cny_stock_lifecycle_select(raw_stock_basic_path)`。 |
| `silver_adj_factor_listed_stock_only` / `silver_adj_factor_coverage_complete` 已改用 `silver_stock_lifecycle`。 | P2C 已完成。 | 复权因子历史分区不得回到 current-listed-only `silver_stock_basic` 股票全集。 |
| `stock_daily_sensor.py`、`suspend_d_sensor.py` 已在 registered partitions 内补缺，并已接入 expected registered gap guard。 | P3 已完成。 | 现有 selected-date readiness 和 raw missing-code repair 调用范围不扩大；静态门禁防止 guard 口径回流。 |
| `index_daily_sensor.py`、`silver_index_daily_sensor.py` 已有 raw gap audit / silver bounded selector，并已接入 expected registered gap guard。 | P5 已完成。 | 现有 raw gap audit、silver selector、late-arrival repair、cursor offset 和 run key 语义保持不变；静态门禁防止 latest registered helper 和单日 readiness wrapper 回流。 |
| `market_major_indices_daily_sensor.py` 已移除 `_latest_registered_trade_date(...)`，不再调用 `gold_market_major_indices_daily_ready_for_trade_date(...)`、`silver_index_daily_ready_for_trade_date(...)`、`silver_index_basic_ready(...)`。 | P4 已完成。 | 静态门禁必须防止 latest-only 目标选择和旧 Dagster event-history readiness wrapper 回流。 |
| `gold_market_breadth_daily`、`gold_stock_return_distribution`、`ch_share_fact_market_breadth_daily`、`prod_ch_share_fact_market_breadth_daily` 已不再带 `automation_condition`；旧四个 `AutomationConditionSensorDefinition` 文件已删除。 | P6 已完成。 | 静态门禁必须防止 automation condition、旧 automation sensor、latest-only 目标和无界 Dagster event/check 深扫回流。 |

### 2.2 LLD 推荐执行顺序

阶段编号表达治理主题，编码推进必须按依赖关系执行。推荐顺序如下：

| 执行顺序 | 阶段 | 核心任务 | 原因 |
| --- | --- | --- | --- |
| 1 | P0F | 先落 bounded continuity selector 基础能力。 | 后续所有历史连续 sensor 复用同一 expected dates、registered gap、readiness model、selector 和 cursor。 |
| 2 | P1 | `stock_current_trade_day_sensor` 改成 bounded catch-up。 | 复权因子仍绑定 `cn_a_stock_current_trade_days`，必须先修注册能力。 |
| 3 | P2A | 新增 `silver_stock_lifecycle` 正式 silver 资产。 | 生命周期事实源是 P2 的前置，不先做会继续混用 raw/basic/current-listed。 |
| 4 | P2B | 一次性迁移既有生命周期消费者。 | 避免两个生命周期事实源长期并存。 |
| 5 | P2C | 修复复权因子生命周期 checks，并迁移 adj factor sensor 到 first-not-ready。 | P2A/P2B 完成后，复权因子 batch readiness 才不会误判退市历史股票。 |
| 6 | P3 | 股票日线和停复牌加 expected registered gap guard。 | 低风险、已通过性能准入，只修注册缺口层。 |
| 7 | P5 | 指数日线 raw/silver 加 expected registered gap guard。 | 先加固主要指数 gold 的直接上游，避免 P4 上游注册缺口被掩盖。 |
| 8 | P4 | 主要指数日线 gold 改为 batch lake readiness + first-not-ready。 | 已完成；当前单日 readiness wrapper 47s/超时的问题已通过 lake-derived readiness 热路径规避。 |
| 9 | P6 | 派生 / serving 资产改为显式 bounded sensor，并退出旧 automation active 入口。 | 默认 eager 不能承担历史补洞，且不能和新 sensor 双触发。 |
| 10 | P7 | 静态门禁、文档对账、本地回归、性能报告收口。 | 防止 latest-only、单日 wrapper、旧 lifecycle 事实源回流。 |

## 3. 资产分类口径

### 3.1 历史连续资产

历史连续资产指：每个交易日 partition 都代表一个稳定历史事实，下游可以按日期回看或递推。停机恢复后，不能因为更晚日期已注册或已生成，就跳过更早缺口。

判断标准：

1. 资产有 `trade_date` partition。
2. 某一天缺失会造成历史数据洞，而不是只影响“当前最新状态”。
3. 下游可能按日期消费该分区，或依赖其连续性。
4. 该资产的 daily sensor 应当使用 first missing / first not-ready，而不是 latest-only。

本专项下的历史连续资产包括：

| 资产 | 分区集 | 目标口径 |
| --- | --- | --- |
| `raw_tushare_stock_daily` | `cn_a_stock_trade_days` | expected registered gap guard + registered 内 first missing。 |
| `silver_stock_daily` | `cn_a_stock_trade_days` | expected registered gap guard + registered 内 first missing，前置 raw / stock basic / suspend ready。 |
| `raw_tushare_suspend_d` | `cn_a_stock_trade_days` | expected registered gap guard + registered 内 first missing。 |
| `silver_stock_suspend_daily` | `cn_a_stock_trade_days` | expected registered gap guard + registered 内 first missing，前置 raw ready。 |
| `raw_tushare_adj_factor` | `cn_a_stock_current_trade_days` | bounded expected current trade days + first missing，不得只看 latest。 |
| `silver_adj_factor` | `cn_a_stock_current_trade_days` | bounded expected current trade days + first missing，前置 raw / stock basic ready。 |
| `raw_index_daily_by_code` | `cn_a_index_trade_days` + `cn_a_index_ts_codes` | expected registered gap guard + existing raw gap audit。 |
| `silver_index_daily` | `cn_a_index_trade_days` | expected registered gap guard + raw gap audit + first not-ready silver。 |
| `gold_market_major_indices_daily` | `cn_a_index_trade_days` | first not-ready gold，前置 silver index daily / index basic / seed inputs ready。 |

### 3.2 Current snapshot 资产

Current snapshot 资产指：资产事实表达当前最新全量快照，历史某天是否生成过一份 snapshot 不是业务主事实。停机恢复后，只需要最新快照满足 freshness 和 blocking checks，不应该为了历史日期逐日补所有 snapshot。

判断标准：

1. 资产虽然可能用交易日作为 run key 或 freshness anchor，但物理事实是全量快照。
2. 下游只需要“当前最新事实”，不需要按历史日期读取旧 snapshot。
3. 漏一天 snapshot 不应触发历史回填；下一次最新 snapshot 覆盖即可。
4. readiness 必须判断 materialization、blocking checks 和 freshness，而不是只看曾经 materialized。

本专项下 current snapshot 资产包括：

| 资产 | 当前口径 | 专项处理 |
| --- | --- | --- |
| `raw_tushare_stock_basic` | raw full snapshot | 不做历史逐日补洞；保持 latest/freshness 口径。 |
| `silver_stock_basic` | current-listed full snapshot | 不做历史逐日补洞；继续服务 current-listed 快照和 freshness guard。 |
| `raw_tushare_namechange` | 曾用名全量事实 | 不做历史逐日补洞；保持当前快照/阶段窗口语义。 |
| `silver_namechange` | 曾用名标准化事实 | 不做历史逐日补洞；保留 namechange 自身和 identity map 上游角色。 |
| `silver_stock_identity_map` | 身份映射全量事实 | 不做历史逐日补洞；只在基础事实更新后重建最新映射。 |

### 3.3 共享历史维表

共享历史维表指：资产本身不是按交易日分区的日频事实，也不是只表达“当前仍上市”的 current snapshot，而是提供历史日期判断所需的稳定维度事实。

本专项新增的共享历史维表：

| 资产 | 上游 | 专项处理 |
| --- | --- | --- |
| `silver_stock_lifecycle` | `raw_tushare_stock_basic` | 新增正式 silver 资产，表达 `ts_code + list_date + delist_date/null` 的历史生命周期事实，供 stock daily、stock mins、adj factor 等下游统一判断历史股票是否合法。 |

执行口径：

1. `silver_stock_lifecycle` 不按历史交易日逐日补洞；它随 `raw_tushare_stock_basic` 更新而重建。
2. 它不是 current-listed snapshot，不得复用 `silver_stock_basic` 的语义。
3. 下游历史连续资产只能用它判断历史生命周期，不再各自直接从 `raw_stock_basic` 派生。

### 3.4 派生 automation 资产

派生 automation 资产当前使用 Dagster declarative automation，而不是自定义 sensor 中手写日期选择逻辑。官方文档已确认默认 `eager()` 和默认 `on_missing()` 对 time-partitioned asset 都受 latest time window 限制，不应作为历史补洞机制。

当前固定归入 P6 显式 bounded sensor 设计：

| 资产 | 触发方式 | 本专项口径 |
| --- | --- | --- |
| `gold_market_breadth_daily` | `AutomationCondition.eager() & all_deps_blocking_checks_passed()` | 使用显式 bounded continuity sensor 补最近 60 个 expected trade dates 的 first missing / first not-ready。 |
| `gold_stock_return_distribution` | `AutomationCondition.eager() & all_deps_blocking_checks_passed()` | 同上。 |
| `ch_share_fact_market_breadth_daily` | direct deps automation | 使用显式 bounded continuity sensor，在两个 gold 派生资产 ready 后补 serving first missing / first not-ready。 |
| `prod_ch_share_fact_market_breadth_daily` | direct deps automation | 使用显式 bounded continuity sensor，在本机 ClickHouse serving asset ready 后补 prod serving first missing / first not-ready。 |

## 4. 通用连续性规则

### 4.1 交易日历是权威日期来源

非分钟线历史连续资产的 expected dates 必须来自 `silver_trade_calendar` 中 `exchange='SSE' AND is_open=true` 的交易日。

Dynamic partitions 只表示 Dagster 已注册状态，不得替代权威交易日历。

### 4.2 先补注册缺口，再提交数据 run

历史连续资产 sensor 在提交数据 run 前，应先确认 expected calendar 对应的 partition 已注册。

如果存在更早 expected date 未注册：

1. 数据 sensor 必须 skip，不提交更晚日期。
2. cursor / SkipReason 必须指出最早未注册日期。
3. 对应 partition registration sensor 负责补注册。

### 4.3 目标日期必须是 first missing / first not-ready

正式数据 sensor 不得以 latest registered date 作为唯一目标。

正确顺序：

```text
expected dates
  -> registered gap guard
  -> first missing physical/materialized partition
  -> first materialized but blocking checks failed
  -> first not-ready target
```

已 materialized 但 blocking checks 未绿时，仍沿用现有安全口径：不自动重跑，不推进后续日期，等待人工处理。

### 4.4 Current snapshot 不做历史逐日补洞

Current snapshot 资产不使用 first missing historical partition 口径。

它们的 sensor 可以继续围绕 latest eligible trade date 判断 freshness，但必须满足：

1. materialization 存在。
2. blocking checks 全绿。
3. freshness 满足当前生产日期。
4. 如果 checks 失败，不自动循环重跑。

### 4.5 性能口径

非分钟线资产的日常 sensor 规模小于股票分钟线，但仍必须避免无界 Dagster event history 深扫。

已拍板默认窗口：

| 项 | 已拍板口径 |
| --- | --- |
| expected window | 最近 60 个 expected trade dates。 |
| partition registration 每 tick | 最多 2 个，沿用通用注册 helper。 |
| stock daily / suspend 每 tick | 保持每 tick 最多 2 个 run。 |
| index daily raw | 保留现有 60 日 raw gap audit。 |
| market major indices | 每 tick 只提交一个 first not-ready gold partition。 |
| readiness 判断 | 能从 lake 文件事实判断的，优先 DuckDB 批量读取；需要 Dagster metadata 的，必须 bounded。 |

### 4.6 Sensor 热路径性能红线

性能问题是本专项硬红线。任何进入实现的 sensor 改造，都必须在开发前先完成只读方案测试或本地性能验证，不能等实现完成后再补性能优化。

硬规则：

1. 禁止在 60 天窗口内逐日调用 `asset_readiness_status(...)`、`dataset_readiness_status(...)` 或面向单日的 readiness wrapper 来扫描 Dagster event/check history。
2. 遇到 `日期 * asset * check` 级别判断时，必须先设计 batch 读取模型：按 asset 一次读取 materialized partition 集合，按 check key 一次读取 bounded check records，或优先用 DuckDB 读取 lake 文件事实。
3. 能用交易日历和 dynamic partition set 差集判断的 registered gap，不得读取 asset materialization 或 check history。
4. 能用 lake 文件事实判断的完整 blocking check 语义，优先抽取或复用 DuckDB SQL；不得用“文件存在 + row count”冒充 ready。
5. 所有 Dagster 相关验证都只能只读；禁止 `dg launch`、materialize、backfill、asset check 执行、report runless event、写 Dagster event、写正式 lake 或写正式数据库。
6. 如果确实需要读取正式 Dagster instance 做只读 profiling，必须单独列出命令、`DAGSTER_HOME`、读取范围、预期耗时和风险，等待明确审批。
7. 任何阶段只读 profiling 发现方案会回到秒级/十秒级热路径，必须停下重设读取模型，不得继续编码。

当前已识别的风险点和验证要求：

| 阶段 | 性能风险 | 禁止实现 | 开发前只读验证 |
| --- | --- | --- | --- |
| P1 current trade day 注册 | 误用全历史交易日注册 helper，导致从历史起点补几千个 current partitions。 | 禁止从 `STK` 历史起点或 `FULL_TRADE_DAY_MIN_DATE` 加载全量 expected dates。 | 已完成只读验证：正式 calendar 读取约 21ms，current dynamic partitions 读取约 182ms，60 日 gap diff 约 0.01ms。P1 可按 60 日 bounded catch-up 推进。 |
| P2 复权因子 raw/silver | 治理前 60 天窗口逐日读 Dagster readiness，重复扫 materialization/check history；同时生命周期判断分散在多个消费者里，容易误用 current-listed-only 股票池。 | 禁止在 selector 循环里调用 `raw_tushare_adj_factor_ready_for_trade_date(...)`、`adj_factor_ready_for_trade_date(...)`、`asset_readiness_status(...)`；禁止让复权因子、股票日线、股票分钟线继续各自直接从 `raw_stock_basic` 现算生命周期事实。 | 已完成 P2A/P2B/P2C：新增 `silver_stock_lifecycle`，迁移既有生命周期消费者，复权因子 sensor 改为 DuckDB batch lake readiness。P2C 开发前只读 prototype 显示 20 日约 10.119ms、60 日约 13.323ms；`000638.SZ` 在退市日 `2026-04-13` 用 lifecycle 通过，用 current-listed 会失败，退市后日期会失败。 |
| P3 股票日线 / 停复牌 | 误把 expected registered gap guard 做成逐日 readiness 深扫，或扩大现有 selected-date 门禁。 | 禁止新增 60 日逐日 `asset_readiness_status(...)` / `dataset_readiness_status(...)`；禁止扩大 raw repair 全历史扫描。 | 已完成只读验证：stock dynamic partitions 约 31ms，60 日 registered gap diff 约 0.003ms；raw/silver stock daily、raw/silver suspend materialized partition set 读取约 11-29ms。P3 只加 gap guard，可推进。 |
| P4 主要指数日线 gold | 60 天窗口逐日调用 `gold_market_major_indices_daily_ready_for_trade_date(...)`。 | 禁止 first-not-ready selector 逐日调用单日 gold readiness wrapper；也不得把该 wrapper 包在 20/60 日循环里。 | 已完成：正式只读 profiling 证明旧单日 wrapper 约 47s/超时；P4 已改为 DuckDB/lake batch readiness。只读 `/private/tmp` 原型显示 60 日 gold + selected silver/basic 约 24ms，selected silver coverage 2000 个 raw 文件约 77ms。 |
| P5 指数日线 raw/silver | 已有 raw gap audit 和 silver bounded selector，如果改造时回退到逐日单日 readiness wrapper，会造成 event history 深扫。 | 禁止把 `silver_index_daily_ready_for_trade_date(...)` 或其它单日 readiness wrapper 放进 20/60 日循环；禁止替换掉现有 raw gap audit 的 DuckDB batch 口径。 | 已完成只读验证：index dynamic partitions 约 37ms，index code partitions 约 10ms；raw gap audit 20/60 日约 299ms/207ms；silver first-not-ready selector 20/60 日约 4.2s/3.5s。P5 可按现有 bounded selector + gap guard 推进，但必须加静态门禁防回流。 |
| P6 派生 automation 资产 | 继续依赖默认 `eager()` 可能只能覆盖 latest propagation，不能保证历史补洞；如果改成全历史 automation / readiness 扫描，又会形成大批量 event history 深扫。 | 禁止把默认 `eager()` 当作历史补洞机制；禁止全历史逐分区调用 `asset_readiness_status(...)`；禁止运行正式 automation evaluator。 | 官方文档已确认默认 `eager()` / `on_missing()` 对 time-partitioned asset 默认只看 latest time window。P6 不再卡在验证默认 automation，而是基于 bounded continuity selector 前置能力设计显式 sensor。 |

后续任何新增或调整 sensor 的阶段，都必须先补入上表或同等性能准入矩阵。没有读模型、真实耗时、20/60 窗口对比或明确跳过理由的 sensor 改造，不允许进入编码。

### 4.7 2026-06-20 / 2026-06-21 只读性能验证结论

两轮性能验证均只读正式 Dagster event/partition 状态和正式 lake Parquet 文件事实；未运行 `dg`，未触发 job/sensor/asset/check/backfill，未写 Dagster event，也未写正式数据湖文件。临时合成样本和汇总报告只写入 `/private/tmp`。

报告文件：

| 文件 | 用途 |
| --- | --- |
| `/private/tmp/non_stk_continuity_perf_local.json` | 本地小样本 P1/P2 性能基线。 |
| `/private/tmp/non_stk_continuity_perf_local_large.json` | 本地 60 日、5000 只股票、121 个 parquet 的 P2 大样本。 |
| `/private/tmp/non_stk_continuity_perf_formal_bounded.json` | 正式 Dagster / 正式 lake 只读分段 profiling。 |
| `/private/tmp/non_stk_continuity_perf_summary.json` | 汇总数字与结论。 |
| `/private/tmp/non_stk_continuity_perf_sensor_matrix.json` | 补充覆盖 P3/P5 sensor 改动资产族的只读性能准入矩阵。 |

关键数字：

| 项 | 结果 | 结论 |
| --- | --- | --- |
| P1 正式 calendar 读取 | 约 21ms，8664 个 SSE open dates。 | 交易日历读取不是瓶颈。 |
| P1 `cn_a_stock_current_trade_days` 读取 | 约 182ms，4239 个 partitions。 | current trade day 60 日补洞可推进。 |
| P1 60 日 gap diff | 约 0.01ms。 | 60 日窗口不需要缩小到 20 日。 |
| P2 本地 60 日大样本 batch | 约 0.8s，5000 只股票、60.5 万行、121 个 parquet。 | DuckDB batch 模型可行。 |
| P2 正式 lake 60 日 batch | 约 1.1s。 | 可作为 P2 正式 sensor 热路径候选。 |
| P2 正式 Dagster 单日 raw readiness | 约 28.5s 后 timeout。 | 禁止进入 20/60 日循环。 |
| P2 正式 Dagster 单日 raw+silver dataset readiness | 约 26.9s。 | 禁止用 `adj_factor_ready_for_trade_date(...)` 做窗口扫描。 |
| P3 `cn_a_stock_trade_days` 动态分区读取 | 约 31ms，3028 个 partitions。 | 股票日线 / 停复牌 registered gap guard 成本可接受。 |
| P3 60 日 stock registered gap diff | 约 0.003ms，当前无缺口。 | gap guard 本身不是瓶颈。 |
| P3 stock daily / suspend materialized partition sets | raw stock daily 约 29ms，silver stock daily 约 11ms，raw suspend 约 26ms，silver suspend 约 25ms。 | 现有 registered 内补洞模型可保留，不需要新增状态实体。 |
| P4 正式 Dagster 单日 gold readiness | 约 47s 后 timeout。 | 已重设 P4 读取模型：sensor 热路径不再读取 Dagster event/check history。 |
| P5 `cn_a_index_trade_days` / index code 动态分区读取 | 约 37ms / 10ms。 | 指数注册状态读取成本可接受。 |
| P5 index raw gap audit | 20 日约 299ms，60 日约 207ms，946 个指数代码，60 日 56760 个 code-date pair。 | 现有 DuckDB raw gap audit 可保留。 |
| P5 silver index first-not-ready selector | 20 日约 4.2s，60 日约 3.5s。 | 现有 bounded metadata selector 可接受，但必须禁止回退为逐日单日 readiness wrapper。 |
| P6 automation 资产 partition set 读取 | 每个约 1.3s-1.9s。 | 聚合集合读取可接受，但不能证明 automation catch-up 行为。 |

已确认的阶段准入结论：

1. P1 可以进入实现；60 日窗口保留。
2. P2 已按 P2A/P2B/P2C 顺序落地；该顺序证明是必要的：先新增 `silver_stock_lifecycle`，再迁移既有直接依赖 `raw_stock_basic` 生命周期事实的消费者，最后处理复权因子历史生命周期 checks 和 sensor batch readiness。
3. P3 可以进入实现；只新增 expected registered gap guard，不扩大现有 selected-date readiness 和 repair 扫描范围。
4. P4 已完成：不复用现有 `gold_market_major_indices_daily_ready_for_trade_date(...)`，已设计、验证并落地新的 lake-derived batch selector。
5. P5 可以进入实现；保留现有 raw gap audit 与 silver bounded selector，只补 expected registered gap guard 和静态门禁。
6. P6 不再把默认 declarative automation 作为历史补洞候选；官方语义已说明默认 latest window 限制。P6 后续基于 bounded continuity selector 基础能力推进显式 sensor 方案。

## 5. 分资产修复方案

### 5.1 股票 current trade day 注册

当前问题：

`stock_current_trade_day_sensor` 只判断今天是否开市、是否到 06:00、今天是否已注册。若 Dagster 停机错过某个交易日，后续不会自动补 `cn_a_stock_current_trade_days` 中的历史 current partition。

修复方案：

1. 保留 `cn_a_stock_current_trade_days` partition set，不改名、不迁移历史 event。
2. 将注册逻辑改为 bounded calendar-backed catch-up。
3. expected dates 仍来自 `silver_trade_calendar`。
4. 同日窗口保留 06:00；历史已完成交易日不受同日窗口阻挡。
5. 每 tick 最多补 2 个缺失 current trade day。
6. cursor 写入 `first_missing_registered_date`、`selected_keys`、`eligible_open_day_count`。
7. 2026-06-20 已完成只读性能验证：正式 calendar 读取约 21ms，current dynamic partitions 读取约 182ms，60 日 gap diff 约 0.01ms；实现阶段必须保持只扫描最近 60 个 expected dates，不得加载全历史交易日。

注意：

虽然名字叫 current trade day，但它已经被 `adj_factor` 这类日频历史资产用作 partition set。为了避免 definition churn，本方案固定不改 partition set 名称，只修注册语义。

### 5.2 股票生命周期 silver 事实资产

治理前问题：

股票生命周期事实已经被多个数据资产复用，但治理前代码里有消费者直接从 `raw_stock_basic` 派生 `list_date` / `delist_date` 区间。P2A/P2B/P2C 已把这些长期生命周期消费者收敛到 `silver_stock_lifecycle`。已处理的同类消费者包括：

1. `silver_stock_daily`：写入过滤和 `silver_stock_daily_stock_lifecycle_covered` check 已迁到 `silver_stock_lifecycle`。
2. 股票分钟线 silver：`silver_stk_mins_name_timeline_covered` check、lake readiness、旧 runless check event dry-run helper 已迁到 `silver_stock_lifecycle`，主要用于解决 `000638.SZ` 这类退市历史股票。
3. 复权因子 silver：`silver_adj_factor_listed_stock_only` / `silver_adj_factor_coverage_complete` 已基于 `silver_stock_lifecycle`，不再使用 current-listed-only `silver_stock_basic` 作为历史股票全集。

这些事实表达的是同一个稳定业务概念：某只股票在哪个日期区间内是 A 股 CNY 股票，历史数据在这个区间内是否合法。因此不应让每个下游各自从 raw 层现算，也不应继续把 current-listed `silver_stock_basic` 当作历史股票全集。

修复方案：

1. 新增正式 silver 数据集 `silver_stock_lifecycle`，从 `raw_tushare_stock_basic` 派生。
2. `silver_stock_lifecycle` 表达稳定历史生命周期事实，至少包含：
   - `ts_code`
   - `list_date`
   - `delist_date`
   - `list_status`
   - `exchange`
   - `market`
   - `is_cny_stock`
3. 生命周期判断统一为：
   - `trade_date >= list_date`
   - `delist_date IS NULL OR trade_date <= delist_date`
   - 保留现有 CNY、上市日期、北交所开市日等正式过滤规则。
4. `silver_stock_lifecycle` 必须有正式 asset definition metadata、catalog entry、blocking checks、readiness spec 和唯一正式更新入口。
5. `silver_stock_lifecycle` 是下游历史生命周期判断的正式事实源；`raw_stock_basic` 继续是源层输入，`silver_stock_basic` 继续保留 current-listed snapshot / freshness guard 职责。
6. 禁止把退市股票塞回 `silver_stock_basic` 来解决历史资产问题。
7. 禁止让下游新增长期逻辑继续直接调用 `historical_cny_stock_lifecycle_select(raw_stock_basic_path)`；迁移后该 helper 只能作为 `silver_stock_lifecycle` 生产逻辑或测试辅助存在。
8. 字段契约在 P2A LLD 中必须进一步细化列类型、空值规则、过滤来源和 check metadata；实现阶段不得少于上述字段。

迁移范围：

1. `silver_stock_daily_select(...)` 改为消费 `silver_stock_lifecycle`，不再直接读 `raw_stock_basic` 生命周期。
2. `silver_stock_daily_stock_lifecycle_covered` 及相关 stock daily lifecycle checks 改为消费 `silver_stock_lifecycle`。
3. `silver_stk_mins_name_timeline_covered`、`batch_silver_stk_mins_lake_readiness(...)`、`stk_mins_name_timeline_check_events` dry-run helper 改为消费 `silver_stock_lifecycle`。
4. `silver_adj_factor_listed_stock_only` / `silver_adj_factor_coverage_complete` 改为消费 `silver_stock_lifecycle`。
5. 相关 readiness、asset deps、catalog blocking checks 和静态门禁同步迁移；旧的直接 raw lifecycle 口径必须清零。
6. 依赖迁移必须一次清零，不能只修复权因子；P2B 验收前，上述既有消费者不得继续各自直接读取 `raw_stock_basic` 作为长期生命周期事实源。

验收口径：

1. `000638.SZ` 在 `2026-04-13` 及以前生命周期内的数据被判为合法；`2026-04-13` 之后的数据被判为非法。
2. 已退市但历史日期合法的股票，不得因为不在 current-listed `silver_stock_basic` 中而导致 stock daily、stock mins、adj factor check 失败。
3. 下游生命周期消费者统一依赖 `silver_stock_lifecycle`，不再各自直接读取 `raw_stock_basic` 做长期判断。
4. `silver_stock_basic` 的 current-listed snapshot 语义不变。
5. 不新增临时兼容路径，不保留两套生命周期事实源并行。

### 5.3 复权因子 raw / silver

当前问题：

`raw_adj_factor_update_job_sensor` 和 `silver_adj_factor_update_job_sensor` 只取 latest registered current trade day。若 `2026-06-15` 漏跑而 `2026-06-16` 已注册，sensor 会围绕 `2026-06-16` 判断，可能永久跳过 `2026-06-15`。

修复方案：

1. 两个 sensor 改为基于最近 60 个 expected current trade days 选择 first not-ready。
2. 如果 `cn_a_stock_current_trade_days` 存在注册缺口，先 skip，等待 current trade day sensor 补注册。
3. raw 侧选择 first missing raw adj factor partition。
4. silver 侧选择 first missing silver adj factor partition。
5. silver 侧保留前置门禁：raw ready、`stock_basic_ready_without_freshness` ready。
6. run key 和 run config 不变：
   - `raw_adj_factor_update:{trade_date}`
   - `silver_adj_factor_update:{trade_date}`
7. 已 materialized 但 checks 未绿时，不自动重跑，不推进后续日期。
8. 正式实现不得逐日读取 Dagster check history；必须走 DuckDB/lake batch readiness。
9. P2 sensor 改造已在 `silver_stock_lifecycle` 开发与既有生命周期消费者迁移完成后推进。2026-06-21 P2C 只读 prototype 显示，迁移到 lifecycle 后 60 日 DuckDB batch 约 13.323ms，未回到逐日 Dagster event/check history 深扫模型。
10. 生命周期语义修正要求已经落地：复权因子历史分区的股票全集 / listed 判断使用 `silver_stock_lifecycle`，不能用 current-listed-only `silver_stock_basic` 把历史退市股票误判为失败。

### 5.4 股票日线 raw / silver

当前问题：

`stock_daily_sensor.py` 已经能在 registered partitions 内按最早 missing 补洞。但如果 `cn_a_stock_trade_days` 本身存在缺口，sensor 不会主动发现 expected-vs-registered 差异。

已落地口径：

1. 保留现有 registered 内补洞逻辑和每 tick 最多 2 个 run。
2. 在计算 pending raw / silver 前增加 expected registered gap guard。
3. 如果最近 60 个 expected stock trade dates 中存在未注册日期，skip，不提交更晚日期；此时不读取 materialized partition set，也不查 selected-date readiness。
4. raw 侧保留现有门禁：stock basic、suspend、Tushare source readiness。
5. raw missing-code repair 保持现有 recent repair 口径，不扩大到全历史。
6. silver 侧保留现有门禁：stock basic、suspend、raw daily ready。
7. 2026-06-21 补充只读 profiling 已确认：本阶段新增 guard 只需要读取 calendar、`cn_a_stock_trade_days` dynamic partitions 和既有 materialized partition sets；正式数据下动态分区读取约 31ms，相关 materialized partition set 读取约 11-29ms。P3 不允许把 selected-date 门禁扩大成 60 日逐日 readiness 扫描。
8. 2026-06-21 P3 本地验收已通过：`tests/test_stock_daily_sensor.py` 覆盖 `2026-06-15` 注册缺口挡住 `2026-06-16` raw/silver run，`tests/test_run_contract_static_gates.py` 锁定 bounded gap guard 片段。

### 5.5 停复牌 raw / silver

当前问题：

`suspend_d_sensor.py` 与股票日线类似，已能在 registered partitions 内补最早 missing，但不会主动识别交易日注册缺口。

已落地口径：

1. 保留每 tick 最多 2 个 run。
2. 在 raw / silver sensor 开始处增加 expected registered gap guard。
3. 如果存在更早 expected date 未注册，skip，不提交后续日期；此时不读取 materialized partition set，也不查 raw readiness。
4. silver 侧保留 raw readiness 门禁。
5. 2026-06-21 补充只读 profiling 已确认：raw / silver suspend materialized partition set 读取分别约 26ms / 25ms；本阶段不需要新增 summary asset、manifest 或数据库状态实体。
6. 2026-06-21 P3 本地验收已通过：`tests/test_suspend_d_sensor.py` 覆盖 `2026-06-15` 注册缺口挡住 `2026-06-16` raw/silver run，静态门禁禁止缺口 guard 片段丢失。

### 5.6 指数日线 raw / silver

当前问题：

指数日线 raw 已有最近 60 日 raw gap audit，silver 已先检查 raw gap 再选择 first not-ready silver。当前主要缺口是 expected calendar 与 `cn_a_index_trade_days` 的注册一致性没有在两个数据 sensor 内独立兜住。

已落地口径：

1. 保留 `index_trade_day_sensor` 的通用 catch-up 注册。
2. raw / silver 两个 sensor 增加 expected registered gap guard。
3. raw 侧保留现有 `audit_index_daily_raw_gaps(...)` 和 late-arrival repair。
4. silver 侧保留现有 raw gap audit + first not-ready silver 逻辑。
5. 不改 raw-by-code repair、cursor offset 和 run key。
6. 2026-06-21 补充只读 profiling 已确认：`cn_a_index_trade_days` / `cn_a_index_ts_codes` dynamic partition 读取约 37ms / 10ms；`audit_index_daily_raw_gaps(...)` 20 日约 299ms、60 日约 207ms；`select_first_not_ready_silver_index_daily_partition(...)` 20 日约 4.2s、60 日约 3.5s。本阶段可以保留现有 bounded selector，但必须禁止改成逐日调用 `silver_index_daily_ready_for_trade_date(...)`。
7. 2026-06-21 P5 本地验收已通过：注册缺口存在时 raw sensor 不进入 raw gap audit / source readiness，silver sensor 不进入 raw gap audit / silver selector；注册连续后原有 late-arrival repair 与 silver first-not-ready 测试保持通过。

### 5.7 主要指数日线 gold

治理前问题：

`market_major_indices_daily_sensor` 使用 `_latest_registered_trade_date(...)`，只围绕最新指数交易日判断 gold 是否 ready。如果更早日期缺失，而最新日期已经 ready，就会跳过历史缺口。

P4 专项方案：

[Dagster Market Major Indices Sensor 热路径性能治理技术设计方案](dagster-market-major-indices-sensor-performance-governance-plan.md)

该文档是本专项 P4“先设计并验证新的 batch selector”的正式设计方案。P4 已按该专项文档落地；若该专项文档与本节摘要冲突，以 P4 专项文档中更细的性能、calendar、readiness 语义约束为准。

修复方案：

1. 改为最近 60 个 expected index trade dates 的 first not-ready gold。
2. 增加 expected registered gap guard。
3. first-not-ready gold 的判断不得调用 `gold_market_major_indices_daily_ready_for_trade_date(...)` 单日 wrapper。2026-06-20 正式 profiling 证明该 wrapper 单日约 47s/超时，若放入 20/60 日 selector 会直接违反 sensor 热路径性能红线。
4. P4 已实现新的 DuckDB/lake batch selector：批量等价判断 gold blocking checks，在内存里映射最近 60 个 expected index dates，得到 first missing / first failed / ready frontier。
5. selected date 上保留现有上游门禁语义，但实现不得回到 Dagster event history wrapper：
   - `silver_index_daily` 必须使用 selected-date lake readiness，不调用 `silver_index_daily_ready_for_trade_date(...)`。
   - `silver_index_basic` 必须使用 lake readiness，不调用 `silver_index_basic_ready(...)`。
   - `check_market_major_indices_inputs_for_trade_date(...)` 第一阶段继续保留为独立 seed/input DuckDB gate。
6. 如果 selected date 已 materialized 但 checks 未绿，skip，不自动重跑，不推进后续日期。
7. run key 不变：`market_major_indices_daily:{trade_date}`。
8. P4 开发前已完成专项文档中的只读 profiling 和 calendar 对账：expected dates 与 `index_trade_day_sensor` 的注册 helper 口径保持一致。
9. 正式实现不得在 60 天窗口逐日调用 `gold_market_major_indices_daily_ready_for_trade_date(...)`，也不得调用 `silver_index_daily_ready_for_trade_date(...)` / `silver_index_basic_ready(...)` 作为 selected-date hot path。
10. P4 sensor 热路径中的 `checks_passed` 必须表示 lake-derived blocking check 等价语义，不表示 Dagster 历史 check event 已 passed；缺历史 check event 的问题属于冷路径审计，不进入 P4 sensor 热路径。

### 5.8 派生 automation 资产

当前问题：

市场宽度、涨跌分布、ClickHouse serving 资产由 Dagster declarative automation 触发，不是手写 latest-only sensor。当前 automation condition 为：

```text
AutomationCondition.eager()
  & AutomationCondition.all_deps_blocking_checks_passed()
```

官方文档已确认：

1. 默认 `eager()` 对 time-partitioned asset 只更新 latest time partition；历史分区更新要触发下游，需要移除 `in_latest_time_window()`。
2. 默认 `on_missing()` 同样只更新 latest time partition；延迟补洞场景不会自动 catch up。
3. AutomationCondition 必须由 sensor evaluate；sensor 未开启时不会提交 run。

因此本专项不再把默认 `eager()` 视作历史补洞机制。

已拍板方案：

1. P6 采用显式 bounded continuity sensor，不再依赖默认 `eager()` 做历史补洞。
2. 显式 sensor 必须复用前置基础能力：expected calendar、registered gap guard、batch / bounded readiness、first-not-ready、cursor 和性能门禁。
3. `gold_market_breadth_daily` 和 `gold_stock_return_distribution` 以 `silver_stock_daily` 为上游 ready 事实，按最近 60 个 `cn_a_stock_trade_days` 补 first missing / first not-ready。
4. `ch_share_fact_market_breadth_daily` 以上游两个 gold 派生资产 ready 为门禁，按最近 60 个 expected trade dates 补 first missing / first not-ready。
5. `prod_ch_share_fact_market_breadth_daily` 以上游本机 ClickHouse serving asset ready 为门禁，按最近 60 个 expected trade dates 补 first missing / first not-ready。
6. P6 显式 sensor 成为正式补洞入口后，必须移除这四个派生资产上的 `automation_condition`，避免它们继续被默认 automation condition sensor 识别。
7. P6 必须删除或退出对应 `AutomationConditionSensorDefinition`，不保留 active automation sensor 作为辅助触发路径。
8. 如果未来确实需要 latest propagation 辅助能力，必须单独立项设计；不得和 P6 显式 bounded sensor 同时作为 active 入口。
9. P6 不运行正式 automation evaluator，不写 Dagster event，不写正式 lake；如需正式只读 profiling，必须单独审批。

## 6. 已拍板推进阶段

### P0 设计收口

产物：

1. 本专项方案文档。
2. 后续 LLD 文档。
3. 历史连续资产与 current snapshot 资产分类按本文第 3 节固定执行。

### P0F Bounded continuity selector 基础能力

目标：

1. 按 [Dagster Bounded Continuity Selector 基础能力专项方案](dagster-bounded-continuity-selector-foundation-plan.md) 先落通用基础能力。
2. 基础能力必须覆盖 expected dates loader、registered gap guard、标准 readiness model、selector algorithm、cursor contract 和性能门禁。
3. 不接入任何正式 sensor 前，先完成纯函数测试和静态门禁。
4. 后续 P1-P6 的历史连续 sensor 改造默认复用该基础能力，不允许每个资产族各写一套临时 selector。

验收：

1. 单元测试覆盖 registered gap、all ready、first missing、materialized failed、upstream blocked。
2. 静态门禁禁止 60 日 selector 中逐日调用单日 Dagster readiness wrapper。
3. 基础能力不新增持久化状态实体。

### P1 Current trade day 注册补洞

目标：

1. 只读性能/方案测试已完成，证明最近 60 个 expected dates 的注册缺口选择逻辑不会扫描全历史，且正式数据下成本可接受。
2. `stock_current_trade_day_sensor` 从 today-only 改为 bounded calendar-backed catch-up。
3. 保留 06:00 同日窗口。
4. 保留 partition set 名称。

验收：

1. 停机漏 `2026-06-15`、`2026-06-16` 时，单 tick 先补最早缺失，最多 2 个。
2. 当天 06:00 前不注册今天。
3. 静态门禁或单元测试证明 P1 实现没有使用全历史 expected date loader。

### P2 股票生命周期 silver 化与复权因子 first-not-ready

目标：

1. 只读性能测试已证明 DuckDB/lake batch 读取模型可行，正式 lake 60 日约 1.1s；同时证明 Dagster 单日 readiness 约 27s/超时，不允许用于窗口扫描。
2. P2 必须拆成三个顺序小阶段：
   - P2A：新增 `silver_stock_lifecycle` 正式 silver 数据集，作为历史股票生命周期统一事实源。
   - P2B：迁移既有直接依赖 `raw_stock_basic` 生命周期事实的消费者，包括 `silver_stock_daily`、股票分钟线 lifecycle/name timeline checks、lake readiness、旧 check event dry-run helper。
   - P2C：在 P2A/P2B 完成后，修正 `silver_adj_factor` 生命周期 checks，并将 `raw_adj_factor_update_job_sensor` / `silver_adj_factor_update_job_sensor` 接入 first missing / first not-ready。
3. P2C 改造后不得跳过更早 current trade day 缺口。
4. 复权因子 run key、run config、partition set 均保持不变。

验收：

1. P2A 后，`silver_stock_lifecycle` 能从 `raw_stock_basic` 派生包含 `ts_code`、`list_date`、`delist_date`、`list_status`、`exchange`、`market`、`is_cny_stock` 的历史生命周期事实，且有正式 catalog、checks、readiness 和测试。
2. P2B 后，`silver_stock_daily`、股票分钟线相关 lifecycle/name timeline 路径、lake readiness、runless check event dry-run helper 不再直接读取 `raw_stock_basic` 做长期生命周期判断；依赖迁移必须一次清零。
3. P2C 后，正式或临时样本中退市历史股票不应被 `silver_adj_factor_listed_stock_only` / coverage 误判为失败；完整 blocking check 语义不能被 row count 代替。
4. P2C 后，`2026-06-15` raw/silver 缺失、`2026-06-16` 已注册时，只提交 `2026-06-15`。
5. 已 materialized 但 checks 未绿时 skip，不推进后续日期。
6. 静态门禁证明 P2 sensor 不在 60 天 selector 中逐日调用单日 adj factor Dagster readiness，并证明长期生命周期消费者不再直接依赖 `raw_stock_basic`。
7. 只读性能回归必须继续记录 20 日 / 60 日 batch 耗时；若 60 日 batch 回到秒级以上异常增长，停止并重新评估读取模型。

### P3 股票日线与停复牌 registered gap guard

状态：已完成。

已落地：

1. 2026-06-21 补充只读 profiling 已完成，确认 P3 新增 guard 的读取模型是 calendar + dynamic partitions + materialized partition set，不是 60 日逐日 readiness 深扫。
2. `stock_daily_sensor.py` 增加 expected registered gap guard，注册缺口存在时在 materialized partition set / selected-date readiness 之前 skip。
3. `suspend_d_sensor.py` 增加 expected registered gap guard，注册缺口存在时在 materialized partition set / raw readiness 之前 skip。
4. 保留现有 registered 内补洞和 repair 逻辑。
5. 不扩大 selected-date `stock_basic` / `suspend` / raw readiness / Tushare source readiness 的调用范围。

验收：

1. expected 有 `2026-06-15/2026-06-16`，registered 缺 `2026-06-15` 时，不提交 `2026-06-16`。
2. registered 连续后，继续按现有 first missing 补 run。
3. 本地验证：`PYTHONPATH=src uv run --project . --with pytest python -m pytest tests/test_stock_daily_sensor.py tests/test_suspend_d_sensor.py tests/test_run_contract_static_gates.py`，结果 `57 passed`。
3. 性能回归记录 `cn_a_stock_trade_days` dynamic partition 读取、四个相关 materialized partition set 读取耗时；不得新增状态实体。

### P4 主要指数日线 first-not-ready

目标与落地结果：

1. 已完成正式只读 profiling，确认现有单日 `gold_market_major_indices_daily_ready_for_trade_date(...)` 约 47s/超时，不能作为 P4 selector 基础。
2. 已按 `dagster-market-major-indices-sensor-performance-governance-plan.md` 设计并验证新的 batch selector，60 天窗口可以 bounded 找到 first missing / failed / ready frontier。
3. `market_major_indices_daily_sensor` 已从 latest-only 改为 first not-ready gold。
4. 已增加 expected registered gap guard。
5. selected-date upstream / input readiness 门禁语义保留，但已从旧 Dagster event history wrapper 改为 lake readiness。
6. 已对账 expected dates 与 `index_trade_day_sensor` 注册口径，避免 sensor 选择尚未注册或不应注册的目标日期。

验收：

1. `2026-06-15` gold 缺失、`2026-06-16` 已注册时，只提交 `2026-06-15`。
2. `2026-06-15` 已 materialized 但 checks failed 时 skip，不推进 `2026-06-16`。
3. 静态门禁证明 P4 sensor 不在 60 天 selector 中逐日调用单日 gold readiness，也不在 selected-date 上游门禁中调用 `silver_index_daily_ready_for_trade_date(...)` / `silver_index_basic_ready(...)`。
4. 性能回归证明 P4 batch selector 不复用 `gold_market_major_indices_daily_ready_for_trade_date(...)`，且不做 `日期 * check` 级别 event history 深扫；本地只读原型 60 日 gold + selected silver/basic 约 24ms。
5. 单元测试覆盖 lake fact readiness 与 Dagster event readiness 的边界：`checks_passed=True` 表示 lake-derived checks passed，不依赖历史 check event。

### P5 指数日线 guard 加固

状态：已完成。

已落地：

1. 2026-06-21 补充只读 profiling 已完成，确认 P5 现有 raw gap audit 与 silver bounded selector 在 60 日窗口内可接受。
2. `index_daily_sensor` 和 `silver_index_daily_sensor` 增加 expected registered gap guard。
3. 保留现有 raw gap audit、late-arrival repair 和 first not-ready silver。
4. 不把 `silver_index_daily_ready_for_trade_date(...)` 或其它单日 readiness wrapper 放入 20/60 日循环。

验收：

1. `cn_a_index_trade_days` 存在注册缺口时，raw/silver index daily 不提交更晚日期。
2. 注册连续后，现有 60 日 raw gap audit 行为不变。
3. `silver_index_daily` first-not-ready 继续使用 bounded selector；静态门禁防止回流逐日单日 readiness wrapper。
4. 本地验证：`PYTHONPATH=src uv run --project . --with pytest python -m pytest tests/test_index_daily_sensor.py tests/test_silver_index_daily_sensor.py tests/test_index_daily_late_arrival_repair.py tests/test_run_contract_static_gates.py`，结果 `55 passed`。

### P6 派生资产显式 bounded sensor

状态：已完成。

目标：

1. 基于 P0F 基础能力，为 `gold_market_breadth_daily`、`gold_stock_return_distribution`、`ch_share_fact_market_breadth_daily`、`prod_ch_share_fact_market_breadth_daily` 落地显式 bounded continuity sensor。
2. 不再验证默认 `eager()` 是否能补历史洞；官方语义已确认默认 latest time window 限制。
3. 最近 60 个 expected trade dates 内按 first missing / first not-ready 补洞。
4. 上游 checks failed 时 skip，不推进后续日期。
5. P6 已移除这四个派生资产上的 `automation_condition`，并删除对应 `AutomationConditionSensorDefinition`，避免双触发。
6. 2026-06-21 已完成只读本地性能原型：60 日 `gold_market_breadth_daily` 完整 lake-derived 语义约 88ms，`gold_stock_return_distribution` 完整 lake-derived 语义约 114ms，ClickHouse bounded 查询模型 1 次查询、0ms 级；报告写入 `/private/tmp/non_stk_continuity_p6_perf_prototype.json`。

已落地代码：

| 文件 | 职责 |
| --- | --- |
| `asset_guards/market_breadth_lake_readiness.py` | 以内存态 `ContinuityBatchReadiness` 表达 gold breadth、gold distribution、本机 ClickHouse、prod ClickHouse readiness；不读 Dagster event history，不新增持久化状态实体。 |
| `sensors/market_breadth_continuity_sensor.py` | 对 `gold_market_breadth_daily` 执行 expected calendar + registered gap + first-not-ready；selected date 只查 `stock_daily_ready_for_trade_date(...)`。 |
| `sensors/stock_return_distribution_continuity_sensor.py` | 对 `gold_stock_return_distribution` 执行同样 bounded 补洞逻辑。 |
| `sensors/clickhouse_market_breadth_continuity_sensor.py` | 同时承载本机 ClickHouse serving 与 prod ClickHouse serving 两个显式 sensor；使用 bounded ClickHouse 查询和上游 frontier 检查。 |

验收：

1. `2026-06-15` 上游 ready、下游缺失、`2026-06-16` 已存在时，只提交 `2026-06-15`。
2. 下游已 materialized 但 checks failed 时 skip，不推进后续日期。
3. 静态门禁证明 P6 sensor 不使用 latest-only 目标选择，不在 60 日窗口逐日深扫 Dagster event history。
4. 性能报告记录读取次数模型、样本日期、60 日窗口耗时和未写入证明。
5. 静态门禁证明四个派生资产不再带 `automation_condition`，对应 `AutomationConditionSensorDefinition` 不再作为 active definition 存在。
6. 本地验证：`PYTHONPATH=src uv run --project . --with pytest python -m pytest tests/test_market_breadth_lake_readiness.py tests/test_market_breadth_continuity_sensors.py tests/test_prod_clickhouse_market_breadth_batch_sync.py tests/test_run_contract_static_gates.py`，结果 `66 passed`。

### P7 文档、静态门禁与回归收口

目标：

1. 更新编码规范和相关设计文档。
2. 增加静态门禁，防止历史连续资产 sensor 回流 latest-only。
3. 跑本地单元回归，不运行正式 `dg`。

## 7. 性能与安全边界

| 项 | 方案口径 |
| --- | --- |
| 正式 Dagster runtime | 未经单独批准不读取、不执行；已批准的 2026-06-20 / 2026-06-21 profiling 仅只读 event/partition 状态，不执行 runtime 动作。 |
| `dg` / job / sensor / backfill | 本专项方案阶段不运行。 |
| expected window | 默认最近 60 个 expected trade dates。 |
| 单 tick run request | 沿用各资产现有上限；不扩大写入量。 |
| Dagster event history | 禁止无界深扫；需要 metadata 时必须 bounded。 |
| lake 文件事实 | 优先 DuckDB 批量读取，不用 Python 行循环。 |
| 新状态实体 | 默认不新增 status manifest、summary asset、readiness asset、数据库表或配置项。 |
| run key | 不改 run key builder，不新增数据集专属 run key helper。 |
| failed checks | 已 materialized 但 blocking checks failed 时不自动重跑，不推进后续日期。 |
| 风险阶段准入 | P0F 是后续历史连续 sensor 改造前置；P1、P2、P3、P4、P5 已通过性能准入并落地；P2 已完成 `silver_stock_lifecycle` 开发、既有生命周期消费者迁移和复权因子 first-not-ready；P6 不再验证默认 automation，改为基于 P0F 设计显式 bounded sensor。 |
| Dagster 验证 | 只允许只读验证；禁止写入 run、event、asset、check、backfill 或正式 lake。 |

## 8. 已拍板口径

### 8.1 `cn_a_stock_current_trade_days` 保留原 partition set 名称

决策：保留。

原因：`raw_tushare_adj_factor` 和 `silver_adj_factor` 已经绑定该 partition set。改名或迁移 partition set 会影响历史 event、asset partitions、测试和 UI 状态，成本远高于收益。当前真正要修的是注册语义：从 today-only 改成 bounded catch-up。

执行口径：

1. 不新增替代 partition set。
2. 不迁移 `raw_tushare_adj_factor` / `silver_adj_factor` 的 partition definition。
3. 只把 `stock_current_trade_day_sensor` 的注册选择从 today-only 改成 bounded calendar-backed catch-up。

### 8.2 current trade day catch-up 窗口固定为 60 个 expected trade dates

决策：使用最近 60 个 expected trade dates。

原因：与股票分钟线 continuity 口径一致，足够覆盖常见停机和假期后的缺口；非分钟线每日对象规模远小于分钟线，性能压力可控。若后续 profiling 发现 60 天有明显成本，再用真实数据调整。

2026-06-20 只读 profiling 已确认：P1 60 日 gap diff 成本约 0.01ms；P2 正式 lake 60 日 batch 约 1.1s，显著快于 Dagster 单日 readiness 约 27s/超时。因此窗口大小不是当前主要瓶颈，读取模型才是关键。60 日窗口继续作为第一版默认口径。

2026-06-21 补充 profiling 又覆盖了所有方案内会改 sensor 的资产族：P3 的 stock daily / suspend guard 只涉及毫秒级集合读取；P5 的 index raw gap audit 和 silver bounded selector 在 60 日窗口内分别约 0.2s 和 3.5s。结论不变：保留 60 日窗口，重点防止错误读取模型回流。

执行口径：

1. 本专项所有非分钟线连续性 guard 默认使用最近 60 个 expected trade dates。
2. 不以 20 天窗口作为第一版默认值。
3. 若后续真实性能数据证明 60 天不可接受，必须单独提交 profiling 证据和变更方案，不得在实现中临时缩小窗口。

### 8.3 股票生命周期事实源收敛到 `silver_stock_lifecycle`

决策：先开发 `silver_stock_lifecycle`，再迁移既有生命周期消费者，最后推进复权因子 P2。

原因：`raw_stock_basic` 是源层事实，不应被多个下游长期直接读取并各自派生生命周期区间；`silver_stock_basic` 是 current-listed snapshot，也不适合作为历史股票全集。历史连续资产需要的是同一个稳定 silver 事实：股票在历史日期上是否处于合法上市生命周期内。

执行口径：

1. `silver_stock_lifecycle` 是历史生命周期判断的正式 silver 事实源。
2. `raw_stock_basic` 只作为 `silver_stock_lifecycle` 的上游输入，不作为下游长期生命周期判断入口。
3. `silver_stock_basic` 保持 current-listed snapshot 和 freshness guard 职责，不承接退市历史股票补全。
4. 已有 `silver_stock_daily`、股票分钟线 lifecycle/name timeline、runless check event dry-run helper 等直接读取 raw lifecycle 的消费者必须迁移到 `silver_stock_lifecycle`。
5. 复权因子 `silver_adj_factor_listed_stock_only` / `silver_adj_factor_coverage_complete` 必须在该迁移完成后再修正并接入 sensor first-not-ready。

### 8.4 复权因子第一阶段不迁移 partition set

决策：第一阶段不把复权因子从 `cn_a_stock_current_trade_days` 迁移到 `cn_a_stock_trade_days`。

原因：复权因子确实是日频历史 partition，但当前资产、测试、bootstrap event 都围绕 `cn_a_stock_current_trade_days`。先修补洞能力即可解决停机风险；迁移 partition set 是更大范围的 definition 变更，应单独立项。

执行口径：

1. P1/P2 只修 current trade day 注册、`silver_stock_lifecycle` 生命周期事实源、既有生命周期消费者迁移与复权因子 first-not-ready。
2. 不改复权因子 asset key、job、sensor 名称、run key、run config 或历史 bootstrap event 口径。
3. P2 sensor 改造前必须先完成 `silver_stock_lifecycle` 开发、旧生命周期消费者迁移和复权因子历史生命周期 check 语义修正；这不等同于迁移 partition set。
4. 若未来要迁移 partition set，必须单独评估 Dagster 历史 event、partition 状态、asset catalog、tests 和下游 qfq 依赖。

### 8.5 股票日线和停复牌不做完整重写，只加 registered gap guard

决策：不重写，只加 expected registered gap guard。

原因：它们当前已经在 registered partitions 内按最早 missing 补洞。问题只在“registered 自身可能漏日期”这一层，做 guard 更小、更稳。

执行口径：

1. `stock_daily_sensor.py` 保留现有 raw/silver registered 内补缺、source readiness、missing-code repair 和每 tick 上限。
2. `suspend_d_sensor.py` 保留现有 raw/silver registered 内补缺和每 tick 上限。
3. 两者只新增 expected calendar vs registered partition 的缺口门禁；存在更早未注册日期时 skip，不提交后续日期。

### 8.6 AutomationCondition 资产不作为历史补洞机制

决策：默认 `AutomationCondition.eager()` 不作为历史补洞机制；P6 改为显式 bounded continuity sensor。

原因：Dagster 官方文档明确默认 `eager()` 和默认 `on_missing()` 对 time-partitioned asset 都受 latest time window 限制。它们适合 latest propagation，不适合承担“停机后补最早历史缺口”的正式口径。继续把 P6 卡在验证默认 eager 是否补洞，会把风险留到运行期。

执行口径：

1. P1-P5 不修改 `gold_market_breadth_daily`、`gold_stock_return_distribution`、`ch_share_fact_market_breadth_daily`、`prod_ch_share_fact_market_breadth_daily` 的 automation condition。
2. P6 在 P0F 基础能力完成后，单独设计显式 bounded continuity sensor。
3. P6 显式 sensor 是唯一 active 补洞入口；必须移除四个派生资产上的 `automation_condition`，并删除或退出对应 `AutomationConditionSensorDefinition`。
4. P6 不运行正式 Dagster runtime；如必须读取正式 Dagster instance，必须单独列命令、读写范围和风险，等明确审批。
5. 不保留 active automation condition 或 active automation sensor 作为 latest propagation 辅助路径；未来如需恢复 latest propagation，必须单独立项。

## 9. 本方案不做的事

1. 本轮文档修改不修改任何生产 Python 代码。
2. 不运行 `dg`、job、sensor、backfill、asset check；正式 Dagster instance 只允许经审批的只读 profiling，不允许写入或执行 runtime 动作。
3. 除 P2A 明确新增 `silver_stock_lifecycle` 及其必要 checks / catalog / readiness / 更新入口外，不新增其它 Dagster asset、check、job、sensor、resource、partition set、数据库表或配置项。
4. 不重做股票分钟线连续性专项已完成的链路；只迁移其中生命周期判断对 `raw_stock_basic` 的直接依赖。
5. 不把 current snapshot 资产改成历史逐日补洞资产。
6. 不改变 run key 规范。
7. 不允许绕过对应阶段准入进入正式代码开发：P0F 是历史连续 sensor 改造前置；P1、P3、P4、P5 性能准入已通过；P2 必须先完成 `silver_stock_lifecycle` 开发、既有生命周期消费者迁移和复权因子生命周期语义修正；P6 必须基于 P0F 先完成显式 bounded sensor LLD 与只读性能方案。
