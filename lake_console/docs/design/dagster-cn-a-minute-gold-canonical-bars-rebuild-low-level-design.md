# A 股分钟线 Gold 标准 K 线合同与历史重建 LLD

更新时间：2026-08-15

状态：**P0-P10、P12 已完成；P11 连续三个实际交易日观察仍属于后续运维验收。P7 已完成股票 QFQ canonical bars 正式重建与抽样/统计验收；P8 已按 5m、15m、30m、60m 的顺序完成 2014-01-02 至 2026-08-12 全历史 MACD/KDJ 与递推 state 重建；P9 已对实际重建范围补齐 103,677 条 materialization event，并只对各专属分区最近 20 个交易日补齐 1,720 条 latest-bound check event。P10 已将主要指数业务 bars 从 Silver 切换到 Gold canonical bars，无 fallback，并收紧股票 bars/indicators 时间键合同。P12 已补齐直接依赖股票 QFQ 的 30m/60m/90m/120m 前复权九转资产；2026-08-15 后续去价格专项又将四个分钟九转正式资产全量切换为八列无价格合同，共 12,272 个分区、197,753,897 行，并完成事件、Reader/readiness 与分钟 sensor 恢复。P12G 的 12,268 个含价格文件只代表 2026-08-14 的历史执行快照，当前合同与结果以 P12H 及股票九转 LLD 为准。**

本文是以下三类分钟线的当前唯一业务口径：

1. 主要指数分钟线 `major_index_mins`。
2. 普通指数分钟线 `index_mins`。
3. 股票前复权分钟线 `stk_mins_qfq` 及其 MACD/KDJ。

若既有文档与本文冲突，以本文为准。既有
[90m/120m 修复 LLD](./dagster-derived-minute-bars-90-120-contract-rebuild-low-level-design.md)
保留为历史实施记录，但不再决定 Gold 5m/15m/30m/60m 的业务语义，也不再允许股票
90m/120m 从已修正的 Gold 30m/60m 取 09:30 锚点。

关联文档：

- [主要指数分钟线方案](./dagster-major-index-mins-data-onboarding-plan.md)
- [主要指数分钟线 LLD](./dagster-major-index-mins-data-onboarding-low-level-design.md)
- [普通指数分钟线方案](./dagster-index-mins-data-onboarding-plan.md)
- [普通指数分钟线 LLD](./dagster-index-mins-data-onboarding-low-level-design.md)
- [股票 QFQ 检查治理 LLD](./dagster-stk-mins-qfq-validation-governance-low-level-design.md)
- [股票 QFQ MACD/KDJ 方案](./dagster-stk-mins-qfq-macd-kdj-indicators-plan.md)
- [股票前复权九转 LLD](./dagster-stock-qfq-nineturn-dataset-low-level-design.md)
- [Dagster 数据管道性能规范](./dagster-data-pipeline-performance-governance.md)
- [Asset Schema 合同](./dagster-asset-schema-contract-design.md)
- [指数详情分钟 API 合同](../../../wealth/docs/pages/index-detail/index-detail-minutes-api-contract-v1.md)
- [股票详情分钟 API LLD](../../../wealth/docs/pages/stock-detail/stock-detail-minutes-api-low-level-design-v1.md)

## 1. 修复目标与硬边界

### 1.1 目标

本专项必须一次性解决以下问题：

1. Silver 保留源端 09:30 集合竞价行，不篡改源事实。
2. Gold 1m 保留 09:30；Gold 所有非 1m 频率不输出独立 09:30 bar。
3. Gold 非 1m 第一根 bar 仍消费 09:30 集合竞价事实，不能简单删除 09:30。
4. 指数业务读取统一切换到 Gold bars，不能继续由 Silver bars 与 Gold indicators 拼接。
5. 主要指数技术指标必须从 Gold bars 计算。
6. 股票 Gold QFQ 5m/15m/30m/60m 全历史重建；1m 对实际存在 `15:01-15:30`
   source 的代码/日期做 scoped 重建；所有受影响频率的 MACD/KDJ 和递推 state 从各自最早
   受影响日期顺序重建。
7. 股票 90m/120m 继续保持当前正确输出，但实现上改为直接从 Silver 30m/60m 加复权因子生成，禁止依赖已不再输出 09:30 的 Gold 30m/60m。
8. 股票 30m/60m/90m/120m 前复权九转必须从重建后的对应 QFQ bars 全历史重算；九转是跨 bar 递推序列，不能只删除 30m/60m 的旧 09:30 行，也不能只修最新分区。
9. bars 与 indicators 的业务匹配键固定为 `ts_code + freq + trade_date + trade_time`，任何读取端都必须严格按该键对齐。
10. `15:01-15:30` source 时段只允许保留在 Raw/Silver；不得进入任何 Gold bar、任何其它
   行情 bar 聚合、任何技术指标或递推 state。
11. Gold 1m/5m/15m/30m/60m/90m/120m 的最后一根 bar 均固定为 15:00。

### 1.2 非目标

本专项不做：

1. 不删除或改写 Raw/Silver 的 09:30 源行。
2. 不修改股票复权因子公式、MACD/KDJ 公式或指标字段 schema。
3. 不新增普通指数 530 代码的技术指标资产。普通指数本轮只新增 Gold bars；未来技术指标必须依赖 Gold。
4. 不把日线读取迁移混入本专项。
5. 不新增逐指标、逐规则 asset check，不恢复高基数公式复算 check。
6. 不使用 Kopia，不写旧 Lake，不把 staging 当正式事实源。
7. 不通过调大 Dagster RPC timeout 掩盖历史重建或 sensor 性能问题。
8. 不在日常 sensor 中执行全历史扫描、Tushare 请求、Prod DB 查询或 Dagster event history 深扫。

## 2. 冻结业务合同

### 2.1 Silver 与 Gold 职责

| 层 | 09:30 语义 | 是否允许业务行情直接读取 |
| --- | --- | --- |
| Raw | 保存源端原始事实 | 否 |
| Silver native/source 1m/5m/15m/30m/60m | 允许并保留独立 09:30 集合竞价行和源端 15:00 后事实；完成清洗、标准化和源质量约束 | 否 |
| Silver 已派生 90m/120m | 继续执行现有正确窗口，不输出独立 09:30 | 否 |
| Gold 1m | 保留独立 09:30 bar | 是 |
| Gold 5m/15m/30m/60m/90m/120m | 不输出独立 09:30；将 09:30 作为首根 bar 的内部竞价锚点 | 是 |

禁止为了让 Gold 看起来正确而从 Silver native/source 删除 09:30。Silver 1m/5m/30m/60m
是后续非 1m Gold 首根 bar 重建时的正式源事实；Silver 90m/120m 的无 09:30 输出本来就是
正确派生结果，不在本专项中倒退。

### 2.2 15:01-15:30 source 行

`15:01-15:30` 不属于业务连续竞价 Gold K 线。若某个 exchange/source 在 15:00 后还返回
1m 明细或以 15:30 标记的聚合 bar，统一执行：

1. Raw/Silver 原样保留这些 source facts，不能通过上游清洗伪装成源端没有返回。
2. Gold source relation 在任何窗口映射、QFQ、指标计算之前先限制
   `CAST(trade_time AS TIME) <= TIME '15:00:00'`。
3. 共享 ignored source 合同覆盖开区间 `(15:00:00, 15:30:00]`，不能只按单个
   `15:30:00` timestamp 判断；这些时间不能成为 target time、regular source time 或
   auction anchor。
4. Gold 1m 不得输出 `15:01-15:30`；不能只修非 1m 聚合后留下 Gold 1m/指标口径分裂。
5. MA、MACD、KDJ 及其递推 state 的 source relation 只能读取已经通过该门禁的 Gold bars。
6. 禁止在指标 writer 中再临时过滤 15:30。过滤必须发生在 Gold bar 合同层，确保
   bars/indicators key set 仍然完全相等。
7. 所有 exchange、所有七频 Gold 的业务 session 最后一根必须精确等于 15:00；只要完整
   交易日最后时间不是 15:00，core check/readiness 就必须 fail closed。
8. 15:00 后数据如需研究，必须另建明确命名的数据集，不能混回本 Gold 合同。

### 2.3 竞价锚点聚合规则

对每个 `ts_code + trade_date`，09:30 行只能作为第一上午窗口的内部锚点使用一次：

1. 输出 `open = 09:30.close`。
2. 输出 `high = max(09:30.close, regular source highs)`。
3. 输出 `low = min(09:30.close, regular source lows)`。
4. 输出 `close = 最后一条 regular source close`。
5. 输出 `vol = 09:30.vol + sum(regular source vol)`。
6. 输出 `amount = 09:30.amount + sum(regular source amount)`。
7. 不使用 `09:30.open/high/low`。
8. 09:30 锚点缺失、重复、价格或成交字段非法时 fail closed，不生成该代码当日 Gold。
9. 09:30 不能作为一条 Gold 非 1m 输出行，也不能在第一根后再次计入任何窗口。

这不是“过滤 09:30”，而是“隐藏输出身份、保留聚合贡献”。

### 2.4 七频率首根合同

| Gold 频率 | Silver source | 第一根 regular source | 第一根输出时间 | 09:30 是否输出 |
| ---: | ---: | --- | --- | --- |
| 1m | 1m | 不聚合，原样标准化 | 09:30 | 是 |
| 5m | 1m | 09:31..09:35 | 09:35 | 否 |
| 15m | 5m | 09:35, 09:40, 09:45 | 09:45 | 否 |
| 30m | 5m | 09:35, 09:40, 09:45, 09:50, 09:55, 10:00 | 10:00 | 否 |
| 60m | 30m | 10:00, 10:30 | 10:30 | 否 |
| 90m | 30m | 10:00, 10:30, 11:00 | 11:00 | 否 |
| 120m | 60m | 10:30, 11:30 | 11:30 | 否 |

后续窗口继续使用当前交易所连续竞价 session 合同中的合法 interval-end 时间，不把午休期间
时间点作为 source 或 target，也不跨交易日；90m 等窗口可以按现有合同连接上午收盘和下午开盘
后的合法 source。所有频率最后一根固定为 15:00；任何 `15:01-15:30` source 行在进入窗口
映射前已经排除。

Gold 正常完整交易日的固定业务行数为：

| 频率 | 每代码每日行数 | 首根 | 末根 |
| ---: | ---: | --- | --- |
| 1m | 241 | 09:30 | 15:00 |
| 5m | 48 | 09:35 | 15:00 |
| 15m | 16 | 09:45 | 15:00 |
| 30m | 8 | 10:00 | 15:00 |
| 60m | 4 | 10:30 | 15:00 |
| 90m | 3 | 11:00 | 15:00 |
| 120m | 2 | 11:30 | 15:00 |

### 2.5 股票 QFQ 聚合顺序

股票 Gold QFQ 必须按以下顺序构造：

```text
Silver source bar
    -> 按当前 QFQ as-of/repair 合同调整 OHLC
    -> 竞价锚点 + regular source set-based 聚合
    -> Gold QFQ target bar
```

同一 `ts_code + trade_date` 的调整系数对窗口内价格为常数，因此先调价再聚合与价格聚合后乘系数
等价；实现仍固定为“先产生带 basis 的 source relation，再使用唯一窗口 SQL”，避免日常、Bootstrap
和 factor repair 各写一套逻辑。`vol/amount` 不做复权，只按窗口求和。

### 2.6 技术指标与展示对齐

1. 所有分钟技术指标的 source key set 必须来自同频 Gold bars。
2. 指标输出 key set 必须与 Gold bars 完全相等，允许指标值因预热不足为 NULL，不允许多行或少行。
3. MACD/KDJ 递推 state 的本日输入必须是本日 Gold bars，上一日输入必须是上一 expected trade date 的精确 state。
4. API 不得按数组位置模糊拼接；必须按完整时间键匹配。
5. 前端绘图以服务端 `tradeTime` 为唯一时间轴，不自行补 09:30，也不重新 bucket。
6. 非 1m 请求出现 09:30 bar、bars/indicators 时间集合不同或重复时间时，后端必须 fail closed，不返回“看起来可画”的错误数据。
7. 任意 Gold 或 indicator/state 出现 `15:01-15:30` 的 key 时必须 fail closed。
8. 完整交易日任意频率的最后一个 key 不等于 15:00 时必须 fail closed。

## 3. 当前问题与影响面

### 3.1 主要指数

P0 审计时，业务 reader 将 bars 指向 `silver/quote/major_index_mins`，而 indicators 指向
Gold；`major_index_mins_technical_writer.py` 也直接读取 Silver。因此 5m/15m/30m/60m 的
独立 09:30 同时进入 bars 和指标计算，二者共同遵循了错误合同。

P2 已完成代码迁移：reader 的 bars 路径改为 `gold/quote/major_index_mins`，technical writer、
check、readiness、bootstrap 和 run-status sensor 都改为消费同频 Gold bars，不保留 Silver
fallback。正式 Gold 历史文件和事件尚未生成，因此当前只代表代码合同已经修正，不能把它
解释为正式数据已经可供业务发布。

### 3.2 普通指数

P0 审计时只有 Raw/Silver 七频资产，没有 Gold bars。P2 已新增 530 代码七频 Gold
asset/check/readiness/job/sensor；普通指数仍没有分钟技术指标资产，本专项也不顺手新增。
正式 Gold 历史文件、事件和日常 sensor 启用留在后续阶段。

### 3.3 股票

股票业务 reader 已读取 `gold_stk_mins_qfq`，读取层方向正确。但当前 5m/15m/30m/60m Gold
仍保留独立 09:30；对应 MACD/KDJ 和 state 也把该行纳入递推。90m/120m 输出合同已经正确，
但当前实现把 Gold 30m/60m 当派生 source；30m/60m 修正后该 source 不再含 09:30，必须改为
从 Silver 30m/60m 直接构造带 QFQ 的派生 relation。

### 3.4 影响面审计

CodeGraph 与当前源码审计覆盖：

- 三套分钟线 writer、asset、check、readiness、job、sensor、bootstrap 与事件补录。
- 主要指数 technical/state writer、asset、job 和 run-status sensor。
- 股票 QFQ 日常写入、Bootstrap、factor repair、MACD/KDJ 日常与 repair。
- 本地 Lake readers、Wealth API DTO 和前端时间键 adapter。
- catalog、governance mapping、run key builder 和静态门禁。

本专项不改变 `foundation -> ops|biz|app` 依赖方向。Gold 生成仍位于 orchestrator；业务查询只通过
`foundation/clients/local_lake` 读取 Gold，不 import Dagster。

## 4. 目标数据拓扑

### 4.1 主要指数

```text
Raw 5 native freqs
    -> Silver 5 native + 90/120
    -> Gold canonical bars 1/5/15/30/60/90/120
    -> Gold technical + state 1/5/15/30/60/90/120
    -> local Wealth reader/API/frontend
```

新增 Gold assets：

```text
gold_major_index_mins_1m
gold_major_index_mins_5m
gold_major_index_mins_15m
gold_major_index_mins_30m
gold_major_index_mins_60m
gold_major_index_mins_90m
gold_major_index_mins_120m
```

物理路径：

```text
/Volumes/datasource/data_lake/gold/quote/major_index_mins/
  freq=<freq>/trade_date=<YYYY-MM-DD>/part-000.parquet
```

### 4.2 普通指数

```text
Raw 5 native freqs
    -> Silver 5 native + bounded fallback + 90/120
    -> Gold canonical bars 1/5/15/30/60/90/120
```

新增 Gold assets：

```text
gold_index_mins_1m
gold_index_mins_5m
gold_index_mins_15m
gold_index_mins_30m
gold_index_mins_60m
gold_index_mins_90m
gold_index_mins_120m
```

物理路径：

```text
/Volumes/datasource/data_lake/gold/quote/index_mins/
  freq=<freq>/trade_date=<YYYY-MM-DD>/part-000.parquet
```

### 4.3 股票

现有 asset key 和物理路径不变：

```text
gold_stk_mins_qfq_{1m,5m,15m,30m,60m,90m,120m}

/Volumes/datasource/data_lake/gold/quote/stk_mins_qfq/
  freq=<freq>/ts_code=<ts_code>/year=<YYYY>/part-000.parquet
```

5m/15m/30m/60m 改变 bar 构造合同，90m/120m 改变 source 边界。1m 的 09:30 和
QFQ 公式不变，但实际存在 `15:01-15:30` source 的代码/日期必须删除这些 Gold 行，因此
不能再把 1m 整体标记为“内容不变”。

## 5. 共享合同与 SQL 设计

### 5.1 共享窗口合同

扩展现有：

```text
orchestrator/defs/run_contracts/cn_a_derived_minute_bars.py
```

新增或收敛为以下唯一概念：

```python
CN_A_AUCTION_ANCHOR_TIME = "09:30:00"

@dataclass(frozen=True, slots=True)
class CanonicalGoldMinuteWindow:
    target_freq: int
    source_freq: int
    window_id: int
    target_time: str
    regular_source_times: tuple[str, ...]
    auction_anchor_time: str | None

def canonical_gold_minute_windows(target_freq: int) -> tuple[CanonicalGoldMinuteWindow, ...]: ...
def expected_gold_minute_times(exchange: str, target_freq: int) -> tuple[str, ...]: ...
```

硬门禁：

1. `auction_anchor_time="09:30:00"` 只能出现在每个交易日第一上午窗口。
2. `09:30:00` 不得出现在任何非 1m `target_time`。
3. 对非 1m 窗口，`09:30:00` 不得混入 `regular_source_times`；1m 自身保留原始
   `09:30:00` bar，不走 anchor 聚合语义。
4. target/source freq 映射固定为第 2.4 节，禁止级联读取 Gold。
5. Silver 90m/120m 现有派生也继续复用该窗口对象，不另建第二套 90/120 map。

### 5.2 共享 DuckDB builder

新增纯 SQL helper：

```text
orchestrator/defs/io/cn_a_gold_minute_bars.py
```

建议入口：

```python
def build_canonical_gold_minute_select_sql(
    *,
    source_relation_sql: str,
    target_freq: int,
    partition_key: str,
    price_basis_relation_sql: str | None,
) -> str: ...

def audit_canonical_gold_minute_relation(
    connection,
    *,
    relation_sql: str,
    target_freq: int,
    partition_key: str,
    expected_codes: Sequence[str],
) -> CanonicalGoldMinuteAudit: ...
```

实现约束：

1. DuckDB set-based SQL，一次 relation 聚合，不逐代码/逐行 Python。
2. 使用显式列投影，不 `SELECT *`。
3. 先将 anchor relation 和 regular relation 分开，再 UNION/聚合；禁止依赖排序后 `first(open)`。
4. 每个 window 校验 expected source times exact match；缺行、重复或多行均失败。
5. 输出主键、schema、日期、freq、exchange、价格域和有限值一次性审计。
6. 只将有限失败样本返回 metadata/report，不把全量代码写 cursor。

## 6. 指数 Gold 实现

### 6.1 模块边界

主要指数新增：

```text
defs/io/major_index_mins_gold_writer.py
defs/assets/major_index_mins_gold.py
defs/checks/major_index_mins_gold_checks.py
defs/asset_guards/major_index_mins_gold.py
defs/jobs/major_index_mins_gold.py
defs/sensors/gold_major_index_mins_daily_update_job_sensor.py
defs/bootstrap/major_index_mins_gold_bootstrap.py
defs/bootstrap/major_index_mins_gold_events.py
```

普通指数新增：

```text
defs/assets/index_mins_gold.py
defs/assets/index_mins_gold_defs.py
defs/checks/index_mins_gold_checks.py
defs/asset_guards/index_mins_gold.py
defs/jobs/index_mins_gold.py
defs/sensors/gold_index_mins_daily_update_job_sensor.py
defs/bootstrap/index_mins_gold_bootstrap.py
defs/bootstrap/index_mins_gold_events.py
```

### 6.2 Asset 与 check

1. 两个指数资产族各 7 个 Gold asset，继续复用各自专属 dynamic partition。
2. 每个 asset 只保留 1 个合并 blocking core check，共新增 14 个 check，不拆逐规则 check。
3. core check 合并验证：文件、schema、partition/freq、PK、代码范围、时间集合、首根锚点、价格/成交域、source coverage。
4. check failure metadata 写 `reason_code`、`failed_rules`、计数和有限样本。
5. 请求量、DuckDB 耗时、source/output rows、文件大小进入 materialization metadata，不拆新 check。

### 6.3 Readiness、job 与 sensor

新增：

```text
gold_major_index_mins_update_job
gold_major_index_mins_update_job_sensor

gold_index_mins_update_job
gold_index_mins_update_job_sensor
```

规则：

1. job 为单 trade-date 分区，选择该族 7 个 Gold bars 和 7 个 core checks。
2. sensor 默认 `STOPPED`。
3. sensor 最近 10 个 expected dates、一个 DuckDB connection、每 tick 最多一个 RunRequest。
4. Silver 未 ready 则阻断；Gold 文件缺失才允许自动生成。
5. Gold 已 materialized 但 core check 失败时 skip，不自动覆盖。
6. sensor 不读 event history、不访问 Tushare/Prod DB、不计算历史指标。
7. run key 使用统一 builder，不手写或解析 run key。

### 6.4 Job 代码修改清单

Job 不实现第二份 15:30 过滤 SQL；过滤只存在于共享 Gold writer。Job 代码负责选择正确资产、
保持依赖顺序并确保所有生产入口都只能到达共享 writer：

| Job | 修改要求 |
| --- | --- |
| `silver_major_index_mins_update_job` | 继续只生成 Silver source，不在 Silver 删除 `15:01-15:30` 事实 |
| `silver_index_mins_update_job` | 继续只生成 Silver source，不在 Silver 删除 `15:01-15:30` 事实 |
| 新 `gold_major_index_mins_update_job` | 选择七频 Gold bars + 合并 core checks，统一执行 `<=15:00` 和 09:30 anchor 合同 |
| 新 `gold_index_mins_update_job` | 选择七频 Gold bars + 合并 core checks，统一执行 `<=15:00` 和 09:30 anchor 合同 |
| `gold_major_index_mins_technical_daily_update_job` | 资产依赖改为同频 Gold bars；不得直接或间接读取 Silver |
| `stock_mins_qfq_daily_update_job` | 七频 QFQ 全部委托 canonical Gold writer；5/15/30/60 使用新开盘合同 |
| `stock_mins_qfq_factor_repair_job` | repair replacement 使用同一 canonical writer；禁止保留旧 derived 分支 |
| `gold_stk_mins_qfq_macd_kdj_daily_update_job` | 只消费已修正 Gold QFQ；1m 也不得出现 `15:01-15:30` 指标行 |
| `gold_stk_mins_qfq_macd_kdj_repair_job` | repair 范围与 QFQ batch 不变，但重算 source 必须是已修正 Gold QFQ |
| 历史 Bootstrap/rebuild CLI | 与 daily/repair 共用同一 writer，不允许历史入口绕过 15:00 和 09:30 合同 |

对应 sensor 触发链固定为：

```text
Silver success
    -> Gold bars job
    -> Gold bar readiness ready
    -> technical daily job
    -> bounded repair job when an approved upstream repair batch exists
```

Raw/Silver job 本身不承担 Gold 过滤；但任何会直接生成 Gold、technical 或 state 的 job 都必须
进入修改和回归清单。仅修改 writer 而不验证 job selection、asset deps 和 run-status sensor，
不得视为完成。

### 6.5 主要指数技术指标迁移

必须修改：

```text
defs/assets/major_index_mins_technical.py
defs/io/major_index_mins_technical_writer.py
defs/asset_guards/major_index_mins_technical.py
defs/sensors/gold_major_index_mins_technical_daily_update_job_sensor.py
```

修改后：

1. technical/state asset deps 从 `silver_major_index_mins_*` 改为同频 `gold_major_index_mins_*`。
2. technical writer 只读取 Gold quote 路径。
3. technical run-status sensor 监听 `gold_major_index_mins_update_job` 成功，而不是 Silver job。
4. normal chain 固定为 `Silver -> Gold bars -> Gold technical/state`。
5. technical readiness 必须先验证同日 Gold bar key set，再验证 indicator/state。
6. 不允许保留 Silver fallback；Gold 不 ready 时 technical fail closed。

## 7. 股票 QFQ 与指标修复

### 7.1 QFQ writer 收敛

修改：

```text
defs/stk_mins_qfq.py
defs/stk_mins_qfq_factor_repair.py
defs/bootstrap/stk_mins_qfq_history.py
defs/bootstrap/stk_mins_qfq_derived_history.py
```

要求：

1. 日常、Bootstrap、factor repair 必须调用同一 canonical builder。
2. 5m 从 Silver 1m，15m/30m 从 Silver 5m，60m/90m 从 Silver 30m，120m 从 Silver 60m。
3. 90m/120m 不再读取 Gold 30m/60m。
4. 1m 保持现有 QFQ 公式和 09:30 输出。
5. factor repair 继续按 approved repair batch 和股票代码范围改写，但七频 source 构造不得分叉。
6. stock-year 文件更新继续使用“保留非目标日期 + 完整替换目标日期”的原子文件语义。

### 7.2 历史 QFQ 重建范围

必须全历史重建：

```text
gold_stk_mins_qfq_5m
gold_stk_mins_qfq_15m
gold_stk_mins_qfq_30m
gold_stk_mins_qfq_60m
```

1m 采用 scoped 重建：

```text
gold_stk_mins_qfq_1m
```

P0 只通过 Parquet footer 聚合确定可能存在 `15:01-15:30` 的日期文件范围，不做全历史行级
深扫。P7 在实际 bounded rebuild planning 中，只对这些候选日期做一次列投影、set-based
`ts_code + trade_date` 精确范围计算；只对命中的代码/日期从 Gold 1m 删除晚间行。不得按
exchange 名称猜测范围，也不得全市场无差别重写 1m。

90m/120m 只做 candidate 与现有正式文件的固定抽样等值审计，不做 26 个 `freq + year` 的
全量深扫：

1. 固定抽样矩阵为 `90m/120m x 2014/2021/2026`：2014 覆盖首年，2021 覆盖北交所边界，
   2026 覆盖最新 frontier。每次命令只允许一个 `freq + year`，并对该样本对账 row count、
   key hash、规范化 value hash、SH/SZ/BJ 可用样本和首尾窗口；键、vol、exchange 精确一致，
   OHLC 各自绝对误差不超过 `1e-7`，且 amount 绝对误差不超过 `1e-6` 时，
   不重写历史文件，只切换代码 source 合同。
2. 任一计数、键、OHLC 超过 `1e-7`、vol、exchange 或超容差 amount 存在差异时停止；单独输出
   差异报告并回到合同 Review，禁止继续扩大容差绕过真实数据问题。

### 7.3 MACD/KDJ 与 state

必须从最早 affected expected trade date 顺序重建以下频率：

```text
gold_stk_mins_qfq_macd_kdj_{5m,15m,30m,60m}
gold_stk_mins_qfq_macd_kdj_state_{5m,15m,30m,60m}
```

股票 1m 只重建 P0 识别出的 affected codes：从每个 affected code 的最早受影响日期开始，
顺序重建该代码的 1m indicator/state；未出现 `15:01-15:30` Gold 输入变化的代码不重建。

重建规则：

1. 5m/15m/30m/60m 各自从历史第一 expected date 开始；1m 按 affected code 从该代码最早
   受影响 expected date 开始。两类范围都必须在各自日期序列内严格升序执行。
2. baseline 日期允许无 previous state；其它日期必须读取上一 expected date 的精确 state。
3. 前一日 indicator 成功但 state 不存在，不允许继续。
4. 每个日期的 indicator key set 必须与同日同频 Gold QFQ 完全一致。
5. 不使用“找任意更早 state”绕过缺口。
6. 不通过普通 daily sensor 补全历史；使用 bounded rebuild CLI，带 checkpoint，可幂等续跑。
7. 90m/120m 只有在第 7.2 节固定六样本发现 QFQ 内容差异时才进入重建；否则保留现有内容，
   禁止为了收口再扩大为全历史 key/hash 深审计。

### 7.4 逻辑修改量与物理重写量

| 数据 | 逻辑变化 | 物理动作 |
| --- | --- | --- |
| 指数 Gold 1m | 删除 `15:01-15:30`，其余 bar 不变 | 新 Gold 日分区完整写入 |
| 指数 Gold 5/15/30/60 | 删除独立 09:30，替换当天第一根；如有则删除 15:00 后尾部 bar | 新 Gold 日分区完整写入 |
| 指数 Gold 90/120 | 现有窗口应等值；禁止 15:00 后输出 | 新 Gold 日分区完整写入并做等值审计 |
| 股票 Gold QFQ 1m | 只影响实际存在 15:00 后行的代码/日期 | 对应 stock-year 文件完整替换 |
| 股票 Gold QFQ 5/15/30/60 | 每代码每日删除 09:30、替换第一根；部分代码还删除尾部 bar | 对应 stock-year 文件完整替换 |
| 股票 Gold QFQ 90/120 | 预期内容不变，只切换为 Silver direct source | 全量等值审计；有差异先停止 |
| MA/BOLL 等滚动指标 | 单个 bar 只影响有限后续窗口，但历史每天第一根都变化，影响区间连成全历史 | 对受影响频率全历史重算 |
| MACD/KDJ 与 state | 早期输入变化会传递到所有后续递推值 | 从最早受影响日期严格顺序重建 |

Parquet 不支持安全原地改一行。因此“逻辑上只修改第一根 bar”不等于“只写一行”：日分区文件和
stock-year 文件都必须生成完整 candidate、完整回读验证后原子替换。禁止用 DuckDB/Python
直接修改正式 Parquet 的局部行。

## 8. 历史重建与发布顺序

下面顺序是安全合同，不能并行、调换或跳步。

### P0 只读冻结审计

1. 记录 git commit、正式 Lake 根、各频率文件数、历史起止日期和最新 frontier。
2. 使用 Parquet footer 统计 1m 文件最大时间，只定位可能存在 15:00 后 source 的日期文件；
   不读取全历史分钟行。
3. 对每个资产族选取历史起点、中位日期、最新日期和已知尾盘边界日期做代表性抽样，统计
   row/code/time 数、09:30、15:00 后行及首尾时间。
4. 冻结受影响频率、候选日期文件范围、样本日期和计划 fingerprint；精确股票代码范围留到
   P7 必要的 bounded planning 一次性计算，不在 P0 重复扫描。
5. 计算候选文件数、预计写入量、staging 空间和执行时间；本阶段不读取 Dagster event history，
   不停止 sensor，不写正式 Lake。
6. active runs、sensor 状态和 source fingerprint 只在 P5 正式写入前重新核对，避免 P0 与正式
   执行间隔较长造成审计失效。
7. 输出 `/private/tmp/cn_a_minute_gold_contract_p0_<timestamp>.json`。

P0 不重新证明已验收 Silver 的全历史数据质量，只回答“影响范围和执行量级”。正式候选仍需
逐文件 staging 回读门禁，但最终验收使用批量统计与代表性抽样，不做第二次逐行公式重算。

#### P0 已完成事实（2026-08-13）

报告：`/private/tmp/cn_a_minute_gold_contract_p0_20260813T044458Z.json`

1. 审计模式为 Parquet footer 聚合 + 代表性样本，共读取 83 个样本文件、1 个 DuckDB
   connection；总耗时 `1199.062ms`，低于 `30s` 门禁。
2. 文件清单：主要指数 Silver `7 x 4,277 = 29,939`；普通指数 Silver
   `7 x 390 = 2,730`；股票 Silver `5 x 3,066 = 15,330`。
3. 主要指数和普通指数 1m footer 中 15:00 后候选文件均为 0。
4. 股票 Silver 1m 有 739 个日期文件的 footer 最大时间为 15:30，日期范围为
   `2022-07-15..2025-10-30`。代表日 `2025-10-24` 抽样确认晚间行来自 BSE；该日 278 个
   BSE 代码在 1/5/15/30/60m 都存在 15:00 后行。
5. 三类 Silver 5/15/30/60 代表样本均存在每代码一条独立 09:30；90/120 首根时间稳定为
   11:00/11:30，尾根为 15:00。
6. 同日 Gold QFQ 抽样确认 `920000.BJ` 的 1/5/15/30/60 仍保留 15:30 尾部行，而
   `600000.SH`、`000001.SZ` 无该尾部；三者 5/15/30/60 均保留独立 09:30。
7. `should_stop=false`，计划 fingerprint 为
   `1a9ef4135ea6f05e0f72f5101d8f3db56b7eab240c2376a8e2da551be1e92327`。

### P1 合同与金样本

1. 先修改共享窗口合同和纯 SQL builder。
2. 用人工字面量 fixture 覆盖 09:30 `open != close`、high/low 异常、非零 vol/amount。
3. 覆盖七频首根、午休、收盘、跨 exchange 和缺窗口反例。
4. 测试证明非 1m 不输出 09:30，且竞价成交只计一次。
5. 在任何正式 writer 修改前让金样本全绿。

#### P1 已完成事实（2026-08-13）

1. `run_contracts/cn_a_derived_minute_bars.py` 已收敛为七频唯一窗口合同；既有 Silver
   90m/120m API 继续读取同一窗口事实，不保留第二套 map。
2. `io/cn_a_gold_minute_bars.py` 已提供纯 DuckDB builder 与 relation audit；regular 与
   auction anchor 显式分流后 `UNION ALL`，每个窗口使用 exact row/time completion gate。
3. 人工字面量金样本覆盖七频首根、09:30 `open != close`、异常 high/low、非零 vol/amount、
   price basis、15:00 后过滤，以及 anchor/regular 缺失和重复的 fail-closed 反例。
4. P1 性能报告：
   `/private/tmp/cn_a_minute_gold_contract_p1_perf_20260813.json`。530 个代码、127,730 条
   1m 输入生成并审计 25,440 条 5m 输出，单线程三次最大耗时 `102.989ms`，低于 `5s`
   门禁；DuckDB connection 为 1，Dagster event history、Lake 写入和 Dagster 写入均为 0。
5. 本阶段只实现共享合同和纯 builder，尚未将主要指数、普通指数或股票正式 writer 接入该
   builder；这部分继续属于 P2/P3，不能把 P1 通过误报为正式数据已修复。

### P2 指数 Gold 和消费链代码

1. 实现两套指数 Gold writer/assets/checks/readiness/jobs/sensors。
2. 迁移主要指数 technical/state 对 Gold 的依赖。
3. 修改本地主要指数 reader 合同为 Gold bars。
4. reader 不保留 Silver fallback。
5. 此阶段不启动 Web、不启用 sensor、不写正式 Lake。

#### P2 已完成事实（2026-08-13）

1. 新增共享 DuckDB writer/audit：
   `io/cn_a_gold_minute_bars.py`、`io/cn_a_gold_minute_writer.py`。两套指数共用同一七频
   窗口合同、staging 回读、同文件系统 `os.replace()` 和 fail-closed 校验，不在 asset/job
   中复制聚合 SQL。
2. 新增普通指数与主要指数共 14 个 Gold asset、14 个单分区 blocking core check、2 个
   单分区 job、2 个默认 `STOPPED` sensor；catalog、column schema 和 asset-check governance
   映射已同步。
3. Gold readiness 固定最近 10 个 expected trade dates，每 tick 复用一个 DuckDB 连接，最多
   提交一个 RunRequest；不读取 Dagster event history，不调用 Tushare 或 Prod DB。文件缺失
   可触发，部分文件或已有文件核心语义失败时拒绝自动覆盖。
4. 主要指数 technical asset/writer/check/readiness/bootstrap 已切换到同频 Gold bars；
   technical run-status sensor 改为监听 `gold_major_index_mins_update_job` 成功事件。原有技术
   指标公式不变，但正常完整日行数已按 Gold 合同收敛为 48/16/8/4 等正确值。
5. 本地主要指数分钟 reader 与审计脚本只读取 Gold bars，不保留 Silver fallback；reader 对
   非 1m 09:30 和所有频率 15:00 后行执行最小 fail-closed 门禁，bars/indicators 继续按完整
   时间键对齐。
6. 临时性能报告：
   `/private/tmp/cn_a_minute_gold_p2_perf_20260813.json`。530 个代码、10 个交易日、七频
   70 个 Parquet、1,706,600 行的 batch readiness 使用一个 DuckDB 连接完成。主要指数已知
   code scope 模型耗时 `2,283.439ms`；普通指数从 source 文件提取 code scope 的较重模型
   执行 70 次有界 code-scope 查询并耗时 `2,316.372ms`，两者均低于 `10s` 门禁；Dagster
   event history、Tushare、Prod DB 调用均为 0。
7. P2 定向 orchestrator 回归 `98 passed`，本地 reader/API/audit 回归 `48 passed`。全量静态
   门禁中 P2 相关门禁全部通过；当前工作区另有一条不属于本专项的 Prod Postgres 字面量断言
   失败，asset-check governance 另有未映射的
   `prod_core_stock_daily_qfq_nineturn`，P2 未修改这两处无关脏改。
8. 本阶段没有执行 `dg`、没有启动 Web、没有写正式 Lake、没有补 materialization/check
   event，也没有改变任何 sensor 的运行状态。正式历史 Bootstrap、事件补录和业务发布仍按
   P5/P6/P9 顺序单独审批；在此之前，不能把 reader 代码切换误报为正式运行验收完成。

### P3 股票 QFQ 和指标代码

1. QFQ 日常、Bootstrap、factor repair 收敛到共享窗口 builder。
2. 实现 5/15/30/60 bounded history rebuild。
3. 实现 90/120 Silver direct source 的等值审计。
4. 实现 MACD/KDJ + state 顺序重建和断点续跑。
5. 此阶段不写正式 Lake。

#### P3 已完成事实（2026-08-13）

1. `stk_mins_qfq.py` 新增统一 canonical source diagnostics；日常 asset、历史 Bootstrap 和
   factor repair 在写文件前均调用同一 Silver source window 完整性门禁。门禁复用共享窗口
   SQL，能够区分完整窗口、部分窗口、非法 09:30 锚点和 exchange 不一致；不新增 Dagster
   check，也不扫描 event history。
2. `stk_mins_qfq_history.py` 保留共享的 `freq + year` 生成批次，并允许显式指定 candidate
   Lake root；该 helper 本身不再提供正式覆盖入口。P7 的冻结计划、精确 1m scope、candidate
   manifest、整频审计、promotion checkpoint 和正式 hash 对账全部由
   `stk_mins_qfq_canonical_history.py` 承载。
3. `stk_mins_qfq_derived_history.py` 新增
   `audit_stk_mins_qfq_derived_canonical_equivalence(...)`。90m/120m 按 `freq + year`
   使用 DuckDB set-based SQL 对比现有 Gold 与 Silver-direct canonical candidate 的 row count、
   key hash、规范化 value hash、missing/extra key 和值差异。键、成交量和交易所必须精确
   一致；OHLC 按绝对误差 `1e-7` 比较；`amount` 仅允许 DuckDB 并行浮点求和造成的绝对误差
   `1e-6`，超过即停止，不能自动重写。
4. `stk_mins_qfq_macd_kdj_history.py` 新增
   `rebuild_stk_mins_qfq_macd_kdj_history(...)`。5/15/30/60 默认按 `freq + year`
   严格日期顺序重建 indicator/state；跨年批次必须读取上一 expected trade date 的精确 state，
   不再使用“任意更早 state”。1m affected codes 可按共同最早受影响日期分组后通过显式
   `stock_codes` 范围执行，未受影响代码不进入重建范围。checkpoint 与计划、频率、日期和代码
   scope 绑定，断点续跑时缺少 indicator/state 目标会 fail closed。
5. 旧 `rebuild-gold-qfq-canonical-history` one-shot 已移除，当前 canonical CLI 继续拒绝此命令，
   禁止绕过 staging 直接改正式 stock-year 文件。股票 QFQ 仅允许使用独立
   `stk_mins_qfq_canonical_history_cli.py`，并分为 `plan`、`build-candidates`、
   `audit-candidates`、`promote`、`audit-formal`、`audit-derived-equivalence` 六个显式阶段；
   staging 写和正式写分别要求独立确认参数。MACD/KDJ history 入口仍归 P8，P7 不调用。
6. 防回流门禁固定：日常 asset/check 不允许把 `stock_codes` 传入 source discovery；只有正式
   factor repair op 和显式 bounded history rebuild 各允许一处 scoped discovery。生产代码
   禁止恢复 latest-before-state discovery，90m/120m 禁止恢复 Gold 30m/60m source。
7. 定向 QFQ 回归为 `263 passed, 63 subtests passed`；共享静态门禁排除一条已知无关的 Prod
   Postgres 字面量断言后为 `99 passed`。全量静态门禁仍只有该工作区既存、与 P3 无关的
   `ProdPostgresWriteResource.set_session(...)` 字面量断言失败，P3 未修改该资源实现。
8. P3 没有执行 `dg`、没有读取或写入正式 Dagster instance、没有写正式 Lake、没有补
   materialization/check event，也没有改变 sensor 状态。P3 完成只代表重建能力可进入 P4
   临时 Lake/真实性能验证；P7/P8 正式物理重建仍需后续独立审批。

### P4 临时 Lake 与性能门禁

1. 在 `/private/tmp` 或正式 staging 根做代表日期、代表代码、全频率联调。
2. 覆盖 SH/SZ/BJ、上市首日、停牌/缺行、09:30 异常值和已有目标文件。
3. 测量 DuckDB scan、聚合、staging、回读、promote 和峰值内存。
4. 用真实 stock-year 分布校准批大小，禁止一次加载全历史股票行。
5. 任何窗口、行数、内存或磁盘预算不成立时回到设计，不进入正式发布。

#### P4 已完成事实（2026-08-13）

1. 完整报告位于
   `/private/tmp/cn_a_minute_gold_p4_perf_20260813.json`，最终
   `should_stop=false`、`stop_reason_codes=[]`。临时 Lake 位于
   `/private/tmp/cn_a_minute_gold_p4_lake_20260813`；正式 Lake 写入、Dagster instance 读取、
   Dagster event 写入和 sensor 改动均为 `0`。
2. 普通指数和主要指数覆盖 3 个代表日期、7 个频率，共执行 42 个临时 Gold writer：读取
   `969,624` 行、输出 `517,776` 行，总耗时 `2.384s`，单分区/频率最大 `149.882ms`；已有
   目标文件拒绝覆盖门禁通过。
3. 最新日期股票样本覆盖 SH/SZ/BJ、北交所上市首日代码 `920138.BJ` 和停牌/无源行代码
   `300333.SZ`。七频输出只包含实际有源行的 3 只股票，未给停牌股票造行；人为删除 09:31
   后，5m source window 从 48 个降为 47 个并被 fail closed。
4. 真实 stock-year 样本固定为 200 只股票（SH 80、SZ 80、BJ 40）和连续 3 个交易日
   `2025-10-22..2025-10-24`。测试复用正式 2025 stock-year 文件作为只读 symlink，候选写入
   只发生在临时 Lake，从而覆盖“保留旧年份行 + 替换目标日期 + 完整 stock-year 原子提升”的
   真实文件成本。
5. QFQ 5m/15m/30m/60m 重建写出 800 个 stock-year 文件、目标文件总行数 `3,820,347`，
   首轮耗时 `5.127s`；checkpoint 续跑恢复 4 个批次，仅耗时 `0.077s`。90m/120m 写出
   400 个文件、3,000 个目标范围行，耗时 `1.058s`；Silver-direct 等价审计 missing/extra
   key 和业务值 mismatch 均为 0。
6. P4 暴露并修复了等价审计的非确定性：90m 的并行 `sum(amount)` 偶发产生
   `1.862645149230957e-09` 尾差，原精确 DOUBLE 比较在 12 次重复查询中误报 2 次。P7F
   最终门禁进一步冻结为键/vol/exchange 精确一致、OHLC 绝对误差不超过 `1e-7`、amount 绝对误差
   不超过 `1e-6`；正反测试必须同时覆盖可接受尾差和真实价格漂移，业务公式没有改变。
7. MACD/KDJ 对 4 个频率写出 800 个 indicator 文件、45,600 个目标范围行，并写出 12 个
   state 文件、65,136 行，耗时 `4.770s`；checkpoint 续跑恢复 4 个批次，耗时 `0.316s`。
   5m/15m/30m/60m bars 与 indicators 的 key mismatch 均为 0。
8. 所有 200 只股票在 3 日样本中满足：5m/15m/30m/60m/90m/120m 的首根分别为
   09:35/09:45/10:00/10:30/11:00/11:30，末根均为 15:00，09:30 输出行和 15:00 后输出
   行均为 0。
9. 完整 P4 用时 `15.843s`，峰值 RSS `0.748GiB`，临时输出 `2,091` 个文件、约
   `341.3MB`，staging 残留为 0。200 代码样本向 5,463 代码线性外推约 `0.083h`；正式
   历史重建批次继续冻结为 `freq + year`，不得扩大为多频/多年全历史内存批次。
10. P4 只证明代码与预算具备进入 P5 的条件，不代表正式指数 Gold、股票 QFQ 或指标已
    修复；P5 及后续任何正式 Lake/Dagster 动作仍需独立审批。

### P5 正式运行冻结

正式写入前单独审批，并按顺序：

1. 停止相关 Raw/Silver/Gold/technical sensors。
2. 停止本地分钟行情 Web 服务，避免读取混合版本。
3. 确认无 `QUEUED/STARTING/STARTED/CANCELING` 相关 run。
4. 确认 `/Volumes/datasource/data_lake_staging` 与正式 Lake 同文件系统且空间充足。
5. 再跑一次 P0 轻量边界对账，fingerprint 不一致即停止。

#### P5 已完成事实（2026-08-13）

报告：`/private/tmp/cn_a_minute_gold_p5_freeze_20260813T145128+0800.json`

1. 冻结代码版本为 `3ab3b44817b2664cc4e054c7788ddc1cc82cf009`。股票、普通指数、主要指数
   分钟线相关 Raw/Silver/Gold/technical sensors 均已是 `STOPPED`，因此 P5 没有执行 sensor
   状态写入；正式 Dagster active runs 在冻结前后均为 0。
2. 本地分钟行情 API（原 PID `3836`、端口 `8000`）已停止，端口已释放。Wealth Vite 前端仍
   运行，但在本地 API 停止后不能读取分钟 Lake，不构成混合版本读取者。`dg dev` 保持运行仅
   供只读 UI/definitions 使用；后续正式阶段仍必须在每批写入前重新确认 active runs 为 0。
3. 正式 Lake 与 staging 的 device id 均为 `16777244`，确认位于同一文件系统；staging 可写，
   文件系统使用率为 39%，可用空间为 `2,465,094,596 KiB`，满足 P4 测得的候选空间预算。
4. 首次 P5 重跑发现 P0 临时脚本把 footer 查询的 `elapsed_ms` 纳入计划 fingerprint，导致相同
   范围也会产生不同 hash。该字段只反映查询耗时，不是重建范围事实；临时审计器已将其排除，
   没有改生产代码或正式数据。
5. 排除非语义耗时后，P0 基线与 P5 重跑的 inventory、候选尾盘范围和样本日期完全一致，稳定
   fingerprint 均为
   `a05861aecb2bfd66b388af26fccc655d0f9dae1f32c55db1c655f1d91e0e49a8`。最终只读重跑报告为
   `/private/tmp/cn_a_minute_gold_contract_p0_20260813T065123Z.json`，耗时 `874.815ms`，
   `should_stop=false`。
6. P5 正式 Lake 写入、Dagster run 提交、event 写入和 dynamic partition 写入均为 0。冻结通过
   只表示具备单独审批 P6 的条件，不授权或隐含执行 P6。

### P6 指数 Gold 正式 Bootstrap

顺序固定：

1. 普通指数 7 个 Gold bars 全量生成到 staging。
2. 普通指数全量文件/key/窗口对账通过后 promote。
3. 主要指数 7 个 Gold bars 全量生成到 staging。
4. 主要指数全量对账通过后 promote。
5. 主要指数 5m/15m/30m/60m technical/state 从历史 baseline 顺序重建。
6. 主要指数 1m/90m/120m 先做新 Gold 与旧 Silver 的批量 row/key/规范化 value hash 对账
   和代表性抽样；按本文冻结的 amount 容差等值时不重写对应 technical/state，只迁移代码
   依赖。存在真实差异则停止并重新划定 affected scope。
7. technical/state 全量 key、连续性和 source hash 对账。

新 Gold bars 没有旧正式目录，仍必须先 staging 后 promote，不能边生成边让 reader 使用。

#### P6 已完成事实（2026-08-13）

汇总报告：`/private/tmp/cn_a_minute_gold_p6/p6_execution_summary_20260813.json`

1. 普通指数 canonical Gold 使用计划 hash
   `f79f609a83f2ce978745a930476496ad6176c603d804993d6ecf0d43be6781e1`。390 个交易日、
   七频共 `2,730` 个正式文件、`66,465,308` 行、约 `2.78GB`。候选与正式全量审计均
   `ready=true`，正式 fingerprint 为
   `04da4eb19975a8e61b9b8afcb2a5b26494402e358137d8cca63628737262131b`。
2. 主要指数 canonical Gold 使用计划 hash
   `8f131a9f7412c5bdd226e6709f128ba13f6a44e7be3ace2b531778e57f682159`。4,277 个交易日、
   七频共 `29,939` 个正式文件、`9,815,204` 行、约 `469.5MB`。候选与正式全量审计均
   `ready=true`，正式 fingerprint 为
   `92dd3205d5fc9bf59325d97f48f204f0ccf342afb66657792ec5874cb9510963`。
3. 两套 Gold 正式审计中 schema、分区日期、业务主键、交易时段、代码日形态和数值域异常
   全部为 0；非 1m 独立 09:30 行为 0，15:00 后行情行为 0。正式提升前均重新确认
   Dagster active runs 为 0。
4. 主要指数 1m/90m/120m 按 `frequency + year` 分成 54 个有界批次，完成 Gold 与旧
   Silver 的全历史 row/key/规范化 value hash 及 amount `1e-6` 绝对容差对账。三频行数分别为
   `7,346,162`、`91,446`、`60,964`，missing 和 value mismatch 均为 0。因此这三频
   technical/state 按冻结口径不重写。
5. 主要指数 5m/15m/30m/60m technical/state 使用计划 hash
   `d49b1f4bccb403f5057c340d76d76f003d94f2b08fef4df197274ed9e9c91c41`，只选择四个受影响
   频率。4,277 日共生成并二次读回审计 `34,216` 个候选文件、`2,438,560` 行、约
   `400.1MB`；候选全绿后显式替换同量正式文件，未复用或遗漏旧文件。
6. technical/state 正式 post-audit 证明：34,216 个正式文件 hash 全部等于绿候选；四频
   technical key hash 全部等于同频 Gold bar key hash；每频 state 行数均为 `30,482`；
   `30,472` 个 continuing code-day 的 exact previous-state continuity failure 均为 0。
7. P6 执行顺序有一项只读调整：原步骤 6 的 1m/90m/120m 等值审计在步骤 5 的正式
   technical 替换前完成，用于提前锁定“不重写三频”的范围。该调整只读、不改变正式写入
   顺序和结果；本节保留该事实，避免把实际执行误写成完全同序。
8. 主要指数 Gold 首次候选构建实测耗时约 `1,291.3s`，峰值 RSS 约 `4.15GB`。这是一次性
   P6 历史任务，但高于 P4 样本预期；历史候选工具已改为每 20 个交易日释放 DuckDB
   connection，防止后续维护性重跑让 connection 状态跨 29,939 个文件累积。日常 asset 和
   sensor 路径没有改变。
9. P6 没有写 Dagster materialization/check event，没有提交 run，没有写 dynamic partition，
   没有启用 sensor，也没有启动分钟行情 API。最终控制面复核发现 P5 冻结后
   `gold_major_index_mins_technical_daily_update_job_sensor` 和三条股票 QFQ/指标 sensors 曾恢复为
   `RUNNING`；P6 开始后的相关 job run 记录仍为 0，且每次正式提升前 active runs 均为 0，
   因此没有并发 job 改写本轮数据。收口时已将这四条 sensors 显式停止并复核。
10. P9 event 补录和 reader/sensor 恢复边界保持不变；P7 未单独审批前，相关 sensors 必须继续
    保持 `STOPPED`。

### P7 股票 QFQ 正式重建

顺序固定：

1. 先按 P0 affected code/date scope 生成 1m candidate，删除 `15:01-15:30`，审计后替换。
2. 完成所有 5m candidate stock-year 文件并审计，再逐文件原子替换。
3. 依次处理 15m、30m、60m；前一频率全量通过后才进入下一频率。
4. 每个 stock-year 替换均为完整文件，进程中断后按 checkpoint 幂等续跑。
5. 90m/120m 只运行固定代表年份的 row/key/规范化 value hash、OHLC `1e-7`、amount 容差
   抽样，不默认重写。每个审计动作只处理一个 `freq + year`，耗时硬上限 300 秒。审计只比较
   canonical SQL 实际生成的完整窗口；源股票日中的 partial window 自然不生成，不能用
   “股票日数 x 固定窗口数”冒充应生成行数并阻断等值审计。
6. 所有受影响 QFQ 范围通过后，才允许进入指标重建。

不使用 Kopia。恢复事实来自未修改的 Silver + adj factor + 已冻结代码版本；任何失败都停止
Web 和 sensors，修正后从 checkpoint 重新生成，不让业务读取半完成版本。

#### P7A/P7B 已完成事实（2026-08-13）

1. 新增 `stk_mins_qfq_canonical_history.py` 和专用 CLI。正式阶段固定为
   `plan -> build candidates -> audit candidates -> promote -> formal audit`；candidate 只允许写
   `/Volumes/datasource/data_lake_staging/cn_a_minute_gold_p7/<plan_hash>/candidate_lake`，正式
   Lake 在 promote 前保持不变。
2. plan 冻结 3,066 个 registered expected dates、Silver 1m/5m/30m 与 adj-factor 文件
   size/mtime、以 `2026-08-12` 为截止日的 per-code as-of factor 快照、目标 stock-year 数量、
   执行代码和本 LLD 的 SHA256。per-code as-of 口径固定为：每只股票取不晚于截止日的最后一个
   有效因子；退市股票不得被要求出现在 `2026-08-12` 单日因子文件中。快照只在 plan 阶段用
   DuckDB set-based `arg_max(..., trade_date)` 生成一次，写入该 plan 的 staging，并冻结文件 hash；
   后续 52 个 `freq + year` 批次复用该快照，禁止重复扫描全部因子历史。
   精确 1m `code + date` scope 不展开进 JSON/Python 全历史对象，而是写为 staging Parquet
   manifest；plan 只保存其路径、SHA256、行数、代码数、日期数、年份和 tail row 总数。
3. 1m candidate 以现有 Gold stock-year 为基线，只替换 manifest 命中的日期并删除
   `15:01-15:30`；未命中股票/日期不重算价格。5m/15m/30m/60m 按 `freq + year` 生成完整
   candidate，整频 candidate 完成并通过 schema、key、交易时段及 source/output code-date
   覆盖审计后才允许逐 stock-year 原子提升。
4. candidate SHA、source fingerprint、代码/LLD hash、正式目标 before-state 任一变化均
   fail closed。promotion 开始前先验证本频所有未完成 candidate 和正式 before-state，避免
   在发现晚序文件冲突前已经部分提升；中断后只允许按同一 plan/checkpoint 续跑。
5. 最新定向回归 `100 passed`，P7/SQL 专项测试 `22 passed`；QFQ history、derived
   equivalence、factor repair、共享 canonical bars、普通/主要指数 P6 回归均通过。
   `dg check defs` 通过。共享静态门禁中 P7 对应门禁通过；全文件仍有一条由当前工作区既有
   `ProdPostgresWriteResource` 实现触发、与 P7 无关的旧字面量断言失败，本专项未修改该资源。

#### P7C 已完成事实（2026-08-13）

1. preflight 报告：
   `/private/tmp/cn_a_minute_gold_p7/p7c_preflight_20260813.json`。`dg dev`、daemon、webserver、
   code server、本地分钟行情 API 和 Wealth Vite 均已停止；active runs 为 0。
2. 股票 QFQ daily/factor repair、MACD/KDJ daily/repair 和 QFQ 九转 sensors 均为
   `STOPPED`。其中两个旧 RUNNING 状态使用与正式 location name 一致的 Dagster workspace
   官方 `sensor stop` 命令收口，没有直接修改 Dagster DB。
3. `cn_a_stock_mins_silver_trade_days` 冻结为 `2014-01-02..2026-08-12` 共 3,066 日；正式
   Lake 与 P7 staging 同文件系统，可用空间约 2.35 TiB。MACD/KDJ 文件 370,142 个、state
   文件 21,462 个的代表性 SHA256，以及 runs/event_logs/dynamic_partitions 基线已记录。

#### P7D 已完成事实与 P7E fail-closed 收口（2026-08-13）

1. 首个 plan hash 为
   `421f5f4bf73cf2bafe0082e9d1696bba95d4af1f32de26b7e2f806613de444c2`。1m exact scope 为
   739 个日期、279 个代码、164,810 个 `code + date`、939 个 stock-year 文件和 4,944,240 条
   `15:01-15:30` 行。939 个 candidate 全部完成审计后原子提升；正式审计确认晚间行归零、
   scope 外差异为 0、主键重复为 0，共保留 42,677,485 行。该 1m 正式结果有效且不重跑。
2. 同一旧 plan 的 5m 首批 `2014` candidate 在覆盖门禁处停止：Silver 输入
   126,082,524 行，其中 455,731 行对应的历史股票不在 `2026-08-12` 单日因子文件中。
   这是退市股票的自然事实，不是源数据损坏。门禁在 candidate 写入前触发，因此 5m 正式
   Lake 和 15m/30m/60m 均未发生写入。
3. 旧实现把“as-of 截止日”错误等同于“所有代码必须出现在截止日单文件”。修正后，历史
   rebuild 使用冻结的 per-code 最后有效因子快照；普通单日生成/repair 继续传单日因子文件，
   逐交易日审计的 `match_as_of_by_trade_date=True` 模式继续保留 code+date 原始行，禁止把
   两种语义混合。
4. 因执行代码和本 LLD 已变化，旧 plan 不得继续用于 5m/15m/30m/60m。重新规划必须生成
   新 plan hash，并把已修复的 1m 识别为 `one_minute_already_canonical=true`、affected scope
   为 0；P7E-P7F 只能使用新 plan，禁止混用旧 candidate/checkpoint。

#### P7E 性能门禁触发与 writer 收口（2026-08-13）

1. 第二个 plan hash
   `1a2dab734dd5a03f283b3863230162f99616d974b7a8c1ac8af720a3d895a2db` 正确识别 1m scope
   为 0，并生成 5,557 个代码的冻结 as-of 因子快照；但 5m candidate 在 2018 年批次耗时
   317.976 秒、命令峰值 RSS 约 16.5 GiB，分别超过 300 秒和 8 GiB 门禁，因此 checkpoint
   只提交到 2017 年，正式 5m 文件仍为 0 次写入。
2. 根因是通用 stock-year writer 会先物化整年 `qfq_replacement_rows`，然后为每只股票重复
   扫描该大表写文件；同时通用 DuckDB 默认内存上限为 16GB，与 P7 的 8GiB 上限冲突。
3. P7 history candidate 路径改为单次 DuckDB `COPY ... PARTITION_BY (__partition_ts_code)`：
   每个 `freq + year` 仍是一个逻辑批次和 checkpoint，但 stock-year 文件由同一次 set-based
   分区导出生成；导出后一次批量回读 schema、代码、年份、日期、freq 和主键，再移动到 plan
   专属 candidate layout。日常 QFQ、factor repair 和通用 writer 不变。
4. 第一版 partitioned export 的真实 2018 benchmark 证明，只把内存改成 6GB 会产生约
   113GB spill，RSS 升至约 8.9GiB，仍越过门禁，且尚未输出 candidate；benchmark 已终止并
   清理，不允许继续正式执行。
5. 最终 P7 history candidate 在同一 `freq + year` 逻辑批次内按 256 个股票代码做有界
   set-based 分片。每片分别执行因子覆盖、完整窗口和 QFQ 生成，代码集合互斥；全部分片完成后
   一次性回读整年 schema/scope/key，再写唯一年度 checkpoint。该分片只控制执行内存，不拆分
   年度成功语义，也不允许部分年度 promote。
6. P7 DuckDB 最终固定 `memory_limit=4GB`、`threads=4`，临时目录固定在当前 plan 的
   `duckdb-temp/`。静态门禁锁定 256-code partitioned export 和 4GB 上限。既有 plan 均因
   代码/LLD hash 变化作废；后续必须重新 plan，并先用 2018 年实际批次证明耗时和 RSS 门禁
   通过。
7. 256-code 真实 benchmark 的计算与导出耗时 116.56 秒、峰值 RSS 约 5.08GiB、spill 为 0，
   但 DuckDB 四线程会为少量股票输出两个 part 文件，完整性门禁因此停止。最终 finalize 允许
   staging 中同一股票存在多个 `part-*`，先对全年所有 parts 做统一 schema/scope/key 审计，
   再仅对多 part 股票 set-based 合并为一个 canonical 文件；候选 layout 最终仍严格保持每个
   stock-year 一个 `part-000.parquet`。该多 part 正反路径已有单元测试。

#### P7E 正式重建完成与 P7F 阻断事实（2026-08-13）

1. 最终冻结 plan hash 为
   `c8b53c333d5a969488171b4da4eca9a444aaba54c1a69e113464773f831ea099`。plan 继续覆盖
   `2014-01-02..2026-08-12` 共 3,066 个交易日、211,507 个计划目标文件；1m affected
   scope 为 0，证明 P7D 的 1m scoped 修复无需重复执行。最终 2018 年 5m 隔离 benchmark
   写出 3,347 个 stock-year candidate、36,972,432 行，耗时 `119.584s`，峰值 RSS
   `5,409,062,912` bytes，正式 Lake 写入为 0，满足 300 秒与 8GiB 门禁。
2. P7E 已严格按 `5m -> 15m -> 30m -> 60m` 顺序完成 candidate、整频 audit、promote 和
   formal audit。正式结果如下：

   | 频率 | 文件数 | 正式行数 | candidate 构建耗时 | 峰值 RSS | candidate audit | promote | formal audit |
   | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
   | 5m | 52,822 | 557,064,528 | 2,050.182s | 5,978,079,232 bytes | 59.225s | 94.627s | 30.193s |
   | 15m | 52,900 | 185,911,408 | 520.807s | 4,054,695,936 bytes | 26.908s | 48.812s | 15.948s |
   | 30m | 52,900 | 92,955,704 | 451.151s | 4,697,505,792 bytes | 22.355s | 41.192s | 12.840s |
   | 60m | 52,885 | 46,472,212 | 215.290s | 2,370,846,720 bytes | 19.174s | 35.430s | 10.470s |

   四频 candidate/formal audit 均为 `ready=true`：schema 和主键正确、source/output
   code-date 覆盖 missing/extra 均为 0、09:30 输出行和 15:00 后输出行均为 0，首根分别为
   09:35/09:45/10:00/10:30，末根均为 15:00。提升前 active runs 均为 0，服务和 readers
   保持停止。一次 30m promote 人工输入了错误 plan hash，入口在 0.58 秒内以
   `Canonical rebuild plan identity is invalid` fail closed，正式写入为 0；随后使用正确 hash
   才完成提升，证明计划身份门禁有效。
3. P7F 官方 90m/120m 审计在进入值比较前被旧 estimate 口径阻断：90m/2014 报告
   `incomplete_window_count=5,673`。该 estimate 错误地用“出现任意 source row 的股票日数量
   x 三个 90m 窗口”作为必须生成的窗口数；生产 canonical SQL 的真实语义是每个窗口独立
   exact completion，partial window 不生成。2014 年有界 key 审计证明 Silver-direct 完整
   candidate 与现有 90m 都为 1,569,366 行，missing/extra/duplicate 均为 0，key hash 都是
   `17826769435863804144`。因此 5,673 个 partial windows 不是现有 Gold 缺数据，而是 P7F
   前置估算口径错误。
4. 官方审计还暴露原性能门禁不适配：峰值 RSS `11,384,455,168` bytes，超过当时的 8GiB
   门禁。P7F 因此停止，没有继续 26 个 `freq + year` 批次，也没有写 90m/120m。随后只对
   90m/2014 做 4GB、
   256-code 有界只读 review：key、vol、exchange 完全一致；OHLC 位级 exact mismatch 较多，
   但最大绝对差仅 `2.842170943040401e-14`，超过 `1e-12` 的行数为 0；amount 只有 46 行
   DOUBLE 尾差，最大 `2.9802322387695312e-08`，未超过既定 `1e-6`。样本 factor 与价格倍率
   证明这不是 as-of factor 基准漂移，而是聚合/乘法执行顺序产生的 DOUBLE 尾差。
5. 2026-08-13 管理员完成 P7F 复审并冻结新口径：OHLC 各自绝对误差不超过 `1e-7`，
   `amount` 继续使用 `1e-6` 绝对容差；键、vol、exchange 仍要求
   精确一致。P7F 峰值 RSS 上限从 8GiB 调整为 16GiB，DuckDB 正式连接仍使用仓库统一的
   `memory_limit=16GB`、`threads=4` 和受控临时目录，不新增散落配置。实现必须移除等值审计对
   `source_stock_day_count x fixed_windows` 的阻断，只比较 canonical SQL 实际产出的完整窗口。
   7 位以内的 DOUBLE 尾差正例必须通过，达到第 7 位差异的真实价格漂移负例必须失败。
6. 由于本文和等值审计代码均已变化，旧 plan 的代码/LLD 指纹不再有效。后续 P7F 必须重新
   生成只读 audit plan；新 plan 的代码指纹必须显式包含 `stk_mins_qfq_derived_history.py`。
   P7F 不再运行 26 个批次的全量深审计，只执行 `90m/120m x 2014/2021/2026` 六个独立
   抽样动作，每个动作超过 300 秒立即停止。已完成的 1m/5m/15m/30m/60m 正式物理结果保持
   有效，禁止重复重建。P7F 完成前 P7G/P8 仍不得进入。
7. 主要证据：
   - `/private/tmp/cn_a_minute_gold_p7/final_benchmark_2018_20260813.json`
   - `/private/tmp/cn_a_minute_gold_p7/candidate_audit_freq_{5,15,30,60}_c8b53c333d5a969488171b4da4eca9a444aaba54c1a69e113464773f831ea099.json`
   - `/private/tmp/cn_a_minute_gold_p7/formal_audit_freq_{5,15,30,60}_c8b53c333d5a969488171b4da4eca9a444aaba54c1a69e113464773f831ea099.json`
   - `/private/tmp/cn_a_minute_gold_p7/p7f_90_2014_key_review_20260813.json`
   - `/private/tmp/cn_a_minute_gold_p7/p7f_90_2014_numeric_tail_review_20260813.json`
8. 新口径第一次 90m/2014 抽样在 7.16 秒内完成、峰值 RSS 约 4.90GiB，但报告出现
   1,485,495 行 OHLC mismatch 和 150.47 的最大差异。只读定位证明这是审计输入错误：旧
   `audit_stk_mins_qfq_derived_canonical_equivalence(...)` 仍读取 `2026-08-12` 单日 adj-factor
   文件，而 P7E 正式重建使用 plan 中冻结的 per-code 最后有效因子快照；退市股票自然不在
   截止日单文件中。P7F 必须显式消费 plan 的 `as-of-adj-factor.parquet`，并把该快照继续纳入
   hash 门禁；普通日常生成、factor repair 和非 P7 history 口径保持不变。该失败是审计假阳性，
   没有触发 90m/120m 写入，也没有继续后续五个样本。
9. 改用冻结 per-code snapshot 后，90m/2014 只剩 14 行 `round(..., 7)` 边界差异，最大 OHLC
   绝对差仍仅 `2.842170943040401e-14`。直接比较七位 round 会让二进制浮点尾差落到十进制
   四舍五入边界两侧，不符合“七位精度足够”的业务意图；最终实现因此使用 `1e-7` OHLC
   绝对容差，规范化 value hash 只作诊断，逐 key 容差比较才是通过门禁。
10. 修复审计输入和容差后，plan hash
    `4b837ccfec698e10e6ee2f395bee327197cd7db2fdf6c65e65527875f9e711d5` 的固定六样本全部
    `ready=true`，且 `formal_lake_write_count=0`：

    | 频率 | 年份 | 行数 | elapsed | 峰值 RSS | missing/extra/value mismatch |
    | --- | ---: | ---: | ---: | ---: | ---: |
    | 90m | 2014 | 1,569,366 | 6.820s | 5,499,027,456 bytes | 0 / 0 / 0 |
    | 90m | 2021 | 3,054,759 | 10.950s | 10,228,842,496 bytes | 0 / 0 / 0 |
    | 90m | 2026 | 2,421,426 | 8.929s | 7,937,097,728 bytes | 0 / 0 / 0 |
    | 120m | 2014 | 1,046,352 | 4.364s | 3,472,965,632 bytes | 0 / 0 / 0 |
    | 120m | 2021 | 2,036,486 | 7.077s | 6,129,549,312 bytes | 0 / 0 / 0 |
    | 120m | 2026 | 1,614,440 | 5.919s | 4,984,455,168 bytes | 0 / 0 / 0 |

    六个动作均远低于单动作 300 秒和 16GiB 门禁；键、vol、exchange 精确一致，OHLC 最大
    绝对差不超过 `4.547473508864641e-13`，amount 最大绝对差不超过 `5.960464477539063e-08`。
    因此 90m/120m 保留正式文件，不做物理重写。
11. P7G 只执行轻量收口：复核 active runs、Dagster 三项计数、六个预冻结 indicator/state
    文件 hash 和当前 plan 的 `.tmp` 数量。禁止重新统计全量 indicator/state 文件或重扫七频
    历史。结果为 active runs 0，runs/event_logs/dynamic partitions 与 P7 基线一致，六个样本 hash
    不变，当前 plan `.tmp` 文件为 0。P7 完成，P8 尚未进入。

### P8 股票指标与 state 正式重建

1. 先对 1m affected codes 从各自最早受影响日期顺序重建。
2. 再按 5m、15m、30m、60m 逐频执行全历史重建。
3. 每个频率按 expected trade date 严格升序生成 indicator 和 state。
4. 每日完成后校验 exact previous state、bars/indicator keys 和 output rows。
5. 一个频率从 baseline 到 frontier 全部通过后，才进入下一频率。
6. 不允许 daily sensor 与 rebuild CLI 同时写同一频率。

#### P8 实际执行记录（2026-08-13）

1. 冻结范围为 `2014-01-02..2026-08-12`，共 `3,066` 个 expected trade dates；执行顺序严格为
   `5m -> 15m -> 30m -> 60m`，每个频率内部按年份和 expected trade date 升序递推。
2. 1m 在 P7 scoped 规划中没有实际 affected scope，因此 P8 未重建 1m；90m/120m 也未进入 P8
   写入范围。
3. 执行前修复了两处历史维护入口缺陷：
   - CLI 未传 `stock_codes` 时统一解释为全市场空 tuple，不再对 `None` 迭代。
   - 全历史重建以显式 target trade dates 为 authoritative replacement scope；即使修正后的 QFQ
     在某个旧股票日期为 0 行，也会移除旧指标文件中该日期的 stale rows，不再只按 replacement
     实际返回日期做合并。
4. 历史重建专用 DuckDB `memory_limit` 固定为 `14GB`，日常 writer 默认配置不变；管理员批准的
   P8 进程峰值门禁为 `20GiB`。实际最大峰值为 `16,710,352,896` bytes，未超过门禁。
5. 5m 为降低峰值按年度独立进程完成，其余频率使用单频连续进程并通过年度 checkpoint 保证顺序；
   任何 checkpoint 都不代替最终文件对账。
6. 四频正式统计验收结果：

| freq | indicator files | indicator rows | state files | state rows | rebuild seconds | audit seconds | peak RSS bytes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5m | 52,901 | 557,215,036 | 3,066 | 11,903,729 | 1,326.38 | 年度审计均小于 7 秒 | 16,304,865,280 |
| 15m | 52,901 | 185,911,612 | 3,066 | 11,904,859 | 666.95 | 38.83 | 16,710,352,896 |
| 30m | 52,901 | 92,955,812 | 3,066 | 11,904,859 | 533.05 | 38.15 | 15,926,149,120 |
| 60m | 52,901 | 46,491,162 | 3,066 | 11,904,784 | 507.41 | 37.20 | 15,319,891,968 |

7. 四频均满足：source rows 等于 indicator rows、文件数量完整、missing input 为 0、row count
   mismatch 为 0。审计采用年度或单频统计聚合，任一独立审计均小于 5 分钟，没有重复执行七频
   全历史深审计。
8. 固定 10 个保护样本 hash 全部不变，覆盖 5m/15m/30m/60m QFQ bars、1m/90m/120m
   indicator 与 1m/90m/120m state；P8 没有触碰非目标数据集。
9. 收口时 `runs=48,559`、`event_logs=4,207,484`、`dynamic_partitions=45,768`，与 P7 冻结
   基线一致；active runs 为 0，四个股票 QFQ/MACD-KDJ daily/repair sensors 均为 `STOPPED`。
10. 执行报告位于 `/private/tmp/cn_a_minute_gold_p8/`，checkpoint 位于
    `/Volumes/datasource/data_lake_staging/cn_a_minute_gold_p8/`。P8 不补 materialization/check
    event，事件补录仍属于 P9。

### P9 事件补录

物理文件全量对账通过后才补 event：

1. 新增指数 Gold bars 全历史补 materialization event。
2. 重建的主要指数 technical/state 和股票 QFQ/indicator/state 全历史补 materialization event。
3. blocking check event 只补各自专属分区最近 20 个 expected trade dates。
4. 每条 event 必须带正确 partition，不写 multi-partition 聚合 check。
5. 不伪造未执行过的历史公式 check，不删除旧 run/event。
6. event 补录完成后重新验证 latest materialization 与 latest-bound check。

P9 于 2026-08-14 按上述口径完成，执行计划 hash 为
`871a71a42ef1097fb841e7a7e5ada629ada9b9d1d01da879746cdc7d0c88a1f7`：

| family | assets | materialization events | latest-bound check events |
| --- | ---: | ---: | ---: |
| `index_gold` | 7 | 2,730 | 140 |
| `major_index_gold` | 7 | 29,939 | 140 |
| `major_index_technical_state` | 8 | 34,216 | 800 |
| `stock_qfq` | 4 | 12,264 | 320 |
| `stock_indicator_state` | 8 | 24,528 | 320 |
| **合计** | **34** | **103,677** | **1,720** |

执行和验收事实：

1. check 窗口统一为各专属 expected trade dates 的最近 20 日，即 `2026-07-16` 至
   `2026-08-12`；没有补全历史 check。
2. 五个 family 都在独立 checkpoint 下执行，先写全量 materialization，再写最近 20 日 check；
   每条 check 都重新验证其 `materialization_event_storage_id` 指向本轮对应 partition 的最新
   materialization。
3. Dagster 1.13 的 runless check 派生索引对同一 asset/check/partition 只允许一条当前记录。
   对已有旧索引行，P9 只释放 `asset_check_executions` 中的旧派生索引，再通过 Dagster 公共
   runless API 写入新 check；旧 `event_logs` 和旧 run 均保留。该处理不删除历史事件，也不改变
   check 的 partition 归属。
4. `major_index_technical_state` 第一次写 check 时，Dagster 在派生索引唯一约束报错前已写入一条
   `event_logs.id=7076620` 的无索引日志。该记录没有 asset key、partition 或
   `asset_check_executions` 行，不参与 latest state/readiness；按“不删除旧 event”规则保留。
5. 五个 family 的 post-audit 均为 `should_stop=false`，missing registered partition 和失败 check
   partition 均为 0；汇总报告为
   `/private/tmp/cn_a_minute_gold_p9/post_audit_summary_20260814.json`。
6. 收口只读统计为：`runs=48,559`、active runs `0`、`dynamic_partitions=45,768`、
   `event_logs=4,312,882`。其中带 P9 revision 的 materialization 为 103,677 条；带 P9 revision
   的 check 日志为 1,721 条，包含上文明确隔离的 1 条无索引日志，实际有效 latest-bound check
   精确为 1,720 条。
7. P9 没有写正式 Lake、没有提交 Dagster run、没有写 dynamic partition、没有启动或启用 sensor。
   P10/P11 仍需单独审批。

### P10 业务读取切换

1. 指数 reader 从 Silver bars 切到 Gold bars，无 fallback。
2. 股票 reader 路径不变，但必须等 QFQ 和 indicators/state 全部完成。
3. 启动本地 Web 前运行全量业务合同审计。
4. API 分别抽查七频，验证非 1m 无 09:30、首根时间正确、bars/indicators 时间键一致。
5. 浏览器检查 K 线和 tooltip 时间、OHLC、指标严格同轴。

P10 于 2026-08-14 完成，实际结果：

1. `MajorIndexMinsLakeReader` 的 bars 唯一路径为
   `gold/quote/major_index_mins`；capability、页面 loading 文案和现行 API 文档均已同步为 Gold，
   没有 Silver、旧 Lake 或 staging fallback。
2. `StockMinsLakeReader` 仍只读 `gold/quote/stk_mins_qfq` 与
   `gold/indicator/stk_mins_qfq_macd_kdj`，并在本次有限返回页上 fail closed 校验身份、
   `trade_time/trade_date`、重复键、非 1m 独立 09:30 以及 15:00 后行情行；没有增加全文件扫描。
3. 股票前端 adapter 现在要求 bars 与 indicators 的根级/逐行身份一致、两侧时间键各自唯一且
   完整集合严格相等。指标字段自身的预热 NULL 继续保留；指标缺行或多行不再静默补 NULL 后绘图。
4. 正式主要指数只读样本报告为
   `/private/tmp/cn_a_minute_gold_p10/index_gold_business_audit_20260814.json`：七频 bars 与
   indicators 各有 4,277 个共同分区，最新共同分区均为 `2026-08-12`，每频率抽查 1 个最新
   分区，时间键差异和合同失败均为 0；九个页面可用指数、七频率、每组 1 次 500 根查询的
   P95 为 257.008-300.783ms，低于 1.5s 目标和 5s 硬门禁。P10 没有重复执行全历史深扫。
5. 新代码临时 Web 端口的只读 API 报告为
   `/private/tmp/cn_a_minute_gold_p10/api_contract_20260814.json`：上证指数与中信证券各七频率共
   14 组全部 READY。每个完整交易日的行数依次为 `241/48/16/8/4/3/2`，首根依次为
   `09:30/09:35/09:45/10:00/10:30/11:00/11:30`，末根均为 15:00，bars 与 indicators
   完整时间键集合严格相等。
6. 浏览器真实页面完成指数和股票 5 分钟切换；K 线、MACD、成交量、KDJ 四窗格正常渲染，
   tooltip 同一时间展示真实 OHLCV 与成交额，MACD/KDJ 标题同步变化，console error 为 0。
7. 页面当前提示分钟数据尚未覆盖期望交易日，是因为 Gold 最新物理日期仍为 `2026-08-12`，
   晚于该日期的日常追平属于 P11 sensor 恢复范围。P10 保留正确 DELAYED 状态，没有启用 sensor、
   写 Lake、写 Dagster event 或提交 run。

### P11 Sensor 恢复与观察

按依赖顺序逐个启用：

1. 现有 Raw/Silver 链。
2. 指数 Gold bars sensors。
3. 主要指数 technical sensor。
4. 股票 QFQ daily/factor repair sensors。
5. 股票 MACD/KDJ daily/repair sensors。

至少观察连续 3 个实际交易日，记录 first-not-ready、run key、耗时、文件数、cursor 大小和
partitioned event。任一环节错误立即停止对应 sensor，不靠自动覆盖修复已 materialized 文件。

### P12 股票前复权九转遗漏补偿

P12 是 P7/P8 的遗漏修复，不是新增业务数据集。目标资产固定为：

```text
gold_stk_mins_qfq_nineturn_30m
gold_stk_mins_qfq_nineturn_60m
gold_stk_mins_qfq_nineturn_90m
gold_stk_mins_qfq_nineturn_120m
```

2026-08-14 只读审计确认现有九转仍来自 canonical rebuild 之前的 QFQ bars：

1. `2026-08-12` 的 30m 九转比当前 QFQ 多 `5,539` 行，全部为已被 Gold 合同禁止的独立
   `09:30` 行。
2. 同日 60m 九转同样多 `5,539` 条独立 `09:30` 行。
3. 90m key 数量与当前 QFQ 一致，但 9 只股票共 27 行 `close_qfq` 不一致。
4. 120m key 数量与当前 QFQ 一致，但 9 只股票共 18 行 `close_qfq` 不一致。
5. 九转的 `up_count/down_count` 依赖完整有序历史；任何早期 key 或价格变化都会影响后续计数，
   因此四个频率都必须从各自最早实际 QFQ 日期重建到执行时冻结的共同 frontier。

#### P12A 执行能力收口

在现有 `qfq_nineturn_history.py` 和 `qfq_nineturn_history_cli.py` 中增加专用 canonical rebuild
模式，不复制第二套公式 SQL。CLI 阶段必须显式拆开：

```text
plan-canonical-rebuild
build-canonical-candidates
audit-canonical-candidates
promote-canonical-rebuild
audit-canonical-formal
```

实现硬边界：

1. plan 固定四个分钟资产、实际 QFQ 共同日期集合、source 文件身份、schema、文件大小和 mtime，
   并生成不可变 `plan_hash`。日期 frontier 在正式执行时从物理 QFQ 和已注册 expected dates 的
   交集冻结，不在生产代码中硬编码 `2026-08-12`。
2. candidate 只能写入
   `/Volumes/datasource/data_lake_staging/cn_a_minute_gold_p12_nineturn/<plan_hash>/`；promote 前
   正式九转文件必须保持字节不变。
3. 继续复用历史 writer 的 `freq + year`、最多 4 根 source context 和 1 条计数 seed。第一年从
   空 seed 开始，后续年份只消费本次 candidate 产生的 seed，禁止读取现有 stale 九转作为递推
   起点。
4. 现有 `plan-rebuild/rebuild` 继续只服务少量代码/日期的 bounded correction。本次禁止用“全市场
   代码文件 + 全历史日期”套用 scoped rebuild，因为该路径会为整个频率建立全历史临时结果，且
   逐分区复制旧文件，不符合本轮性能和 candidate-first 原子边界。
5. candidate audit 全绿后才允许 promote。promote 前必须重新验证 source fingerprint、candidate
   hash 和正式目标 pre-image；任一变化立即失败。
6. promote 按单频率、单交易日原子替换并写 checkpoint。中断后只能使用同一 `plan_hash` 续跑，
   禁止重新规划后混用两套 candidate。
7. 不修改普通九转 asset/check/job/sensor 名称、公式版本、分区定义或日常 run key。

#### P12B 正式重建顺序

1. 停止股票 QFQ daily/factor repair、九转 update sensor，并确认相关 active runs 为 0；重建期间
   上游 QFQ 和目标九转均不得并发写入。
2. 在生成九转正式 plan 前，先执行 bounded 上游 source 门禁：对四频 QFQ source 做聚合时段
   统计和有限异常样本。若发现旧 Gold 文件不在当前 source-driven manifest 中，或仍含独立
   `09:30`，必须先修复对应 Silver/QFQ 和递推下游，禁止让九转 candidate 忽略 stale 正式文件。
3. 生成只读 plan，确认四个频率 source 缺口为 0、日期范围一致、candidate 空间充足。
4. 先用 SH/SZ/BJ、首年/中间年/最新年样本构建 candidate，验证递推跨年连续后，再进入正式
   全历史 candidate。
5. 严格按 `30m -> 60m -> 90m -> 120m` 执行。每个频率完整 build、audit、promote、formal
   audit 通过后才进入下一频率。
6. 任一频率失败时停止，不继续后续频率，不启动 sensor，不用普通 daily job 覆盖历史文件。

#### P12B-1 2026-08-14 bounded 前置修复

首轮 30m candidate 审计在 209.494 秒内 fail closed，未执行任何 P12 promote。异常被严格缩小为
`002348.SZ`、`688790.SH` 在 `2025-12-16..2025-12-31` 的 12 个交易日：Silver 1m 每日完整
241 行，但 Prod、Raw 和 Silver 5m 原生源均为 0；前者 QFQ15/30 缺行，后者旧 Silver15/30 与
QFQ15/30 stock-year 文件仍含独立 09:30。
旧 P7 formal audit 只检查 source manifest 内文件，未覆盖这种不在当前源清单中的 stale 正式文件。

本次前置修复口径冻结为：

1. Silver 粗周期 writer 只在目标粗周期的某个 `ts_code + trade_date` **整日完全缺失**，且同日
   Silver 1m 正好具备 241 个唯一合法时间点时，才用 1m set-based 聚合补齐；已有任意原生粗
   周期行时绝不覆盖。Silver 仍保留独立 09:30，Gold canonical 才消费该锚点并隐藏它。
2. 只为上述 12 日生成 Silver5 candidate，验证每只股票每日新增恰好 49 行、原有 key/value 零
   变化后原子提升。
3. 只重建受影响的 QFQ15/30 2025 stock-year candidate，并对上述两只股票做 bounded MACD/KDJ
   与递推 state 修复；不扩大到未受影响频率。
4. 任何上游正式提升都会改变 source fingerprint。首轮 P12 plan hash 和 30m candidate 全部作废，
   禁止复用；前置修复通过后必须重新 plan。
5. 前置修复的候选仍只能写 `/Volumes/datasource/data_lake_staging`，不使用普通 daily job，不写
   Dagster event；P12 event 仍统一在四频物理重建完成后补录。

#### P12C 审计口径

每个独立审计动作必须在 5 分钟内完成，只做 DuckDB set-based 统计和有界抽样，不执行四频全量
逐行深比较。每个频率必须证明：

1. source/output 文件日期集合、row count 和业务 key 集合一致。
2. `close_qfq` 与当前 QFQ source 的绝对误差不超过 `1e-7`。
3. 主键唯一、schema exact、空 key 为 0、`15:00` 后行数为 0。
4. 30m/60m 独立 `09:30` 行数为 0；90m/120m 首根分别为 `11:00/11:30`；四频最后一根
   均为 `15:00`。
5. 固定 SH/SZ/BJ、跨年边界、停牌恢复、退市边界和最新日期样本的九转计数与字面 fixture 一致。
6. 旧 30m/60m `09:30` 行和已识别的 90m/120m stale price mismatch 均归零。

#### P12D Event 补录

物理文件验收通过后才生成独立 runless event plan：

1. 四个重建资产的所有实际历史分区追加新的 materialization event；已有旧 event 保留，不删除。
2. 只对 `cn_a_stock_mins_silver_trade_days` 最近 20 个 expected dates 追加现有聚合 integrity
   check；不得补全历史 check。
3. 新 materialization/check metadata 必须带 `canonical_rebuild_plan_hash` 和本轮 revision；event
   planner 不能因“已有旧 materialization”而错误跳过本次重建后的新状态。
4. check 必须绑定本轮同分区最新 materialization，partition 不得为空，不写 multi-partition
   聚合 event。
5. Event apply 需要单独批准；P12 Lake 重建完成不等于 event 已完成。

#### P12E 防复发门禁

新增 canonical rebuild 下游覆盖合同，至少把以下家族列为显式决策项：

```text
gold_stk_mins_qfq
gold_stk_mins_qfq_macd_kdj
gold_stk_mins_qfq_macd_kdj_state
gold_stk_mins_qfq_nineturn
```

静态测试从当前 Definitions 的 asset dependency graph 取得 QFQ 直接/递推下游，要求每个资产族在
历史重建计划中被标记为 `rebuild`、`equivalence_audit` 或有代码证据的 `no_impact`。出现未分类
下游时计划和测试都必须 fail closed。普通日常 sensor 仍只负责新增日期，不把全历史依赖扫描塞入
sensor 热路径，也不新增九转自动 repair sensor；未来任何 QFQ 历史改写必须显式生成下游影响计划。

#### P12F 性能与完成门禁

1. DuckDB set-based SQL，禁止 Python 逐 bar 计算。
2. 物理计算批次固定为一个频率、一个年份；峰值 RSS 上限 `20GiB`。
3. 审计单次上限 5 分钟；超限时拆年份或日期段，禁止提高 timeout 或改成全历史 Python 扫描。
4. staging 可用空间不得低于本阶段预计 candidate 大小两倍加 `20GiB`。
5. Lake 重建阶段不访问 Tushare、Prod DB 或 Dagster event history；runless event 阶段只读取本轮
   四资产明确分区范围的当前 materialization/check 状态。
6. 四频 Lake、全量 materialization、最近 20 日 latest-bound checks 和下游覆盖静态门禁全部通过，
   才能把 P12 标记完成并恢复九转 sensor。

#### P12G 2026-08-14 正式执行结果

P12 已按本节顺序完成，上游缺口、递推指标、四频九转 Lake 和 Dagster 状态均已收口：

1. 第一处 bounded 前置修复完成。`002348.SZ`、`688790.SH` 的 12 个交易日从完整 Silver 1m
   生成 Silver 5m，共新增 1,176 行，既有行变化为 0；随后只重建两个代码的 2025 年
   QFQ15/30 和 15/30m MACD/KDJ/state。
2. 第二处 source gate 发现 QFQ60 中 3,790 个独立 09:30 code-date，范围为 7 个代码、2,177
   个交易日。对应 Silver 5m 均为完整 49 行，而 Silver 30m 整日缺失。计划
   `0b3561bb47167abbae49e960ec7aafda4a94013628c980c33c71b546747ed86a` 仅为这些 code-date
   生成 34,110 行 Silver30（每组 9 行），既有 Silver30 行变化为 0，并原子提升 2,177 个日期文件。
3. QFQ bounded 计划
   `b5380ff721690f9199ab70f6c325600baf6a0790285e8aa5251e055329cd776b` 覆盖 7 个代码、16 个
   code-year 和 60/90/120m 共 48 个候选文件。60m、90m 各有 16 个文件需要提升，差异行分别为
   11,327 和 11,370；120m 的 16 个文件逐行差异为 0，未做无意义重写。差异全部落在冻结 scope 内。
4. 只对上述 7 个代码重建 60/90m MACD/KDJ 与递推 state，共执行 26 个年度批次，计划
   fingerprint 为 `1182d7a28136f16ef5d8114e2effa5b32bbfcc5fbbe8cb096619f7dfe8b48d0a`。
   集合审计确认 QFQ/indicator key 双向缺口为 0、指标 09:30 行为 0、state 主键唯一；120m
   QFQ 未变化，因此没有重建 120m 指标/state。
5. 四频九转正式计划 hash 为
   `bc95ab53df6141894386a132fdea356c55a57156d9c77b6984623ef3c86189b8`，范围为
   `2014-01-02..2026-08-13`、3,067 个交易日、12,268 个目标分区。严格按
   `30m -> 60m -> 90m -> 120m` 完成 candidate、分年 audit、promote 和 formal audit。
6. 最终四频九转行数分别为 93,000,216、46,509,532、34,882,149、23,267,820；每个资产
   3,067 个文件。最终聚合审计 `should_stop=false`，source/output 行数一致，缺文件、schema
   错误、重复/空 key、日期/频度错位均为 0。各频率候选审计的 09:30、15:00 后、missing key、
   extra key 和 close mismatch 均为 0；单次审计均低于 5 分钟，峰值 RSS 低于 20GiB。
7. runless event 计划 fingerprint 为
   `3023e820794752306b48b3c5eb4d04b3d25f0603547fa12707e4b2987c1b790b`，revision 为
   `canonical-bars-p12-bc95ab53`。批次 `e28be5a6-64e1-4eef-8735-a0121049f3cb` 实际追加
   12,268 条 materialization 和最近 20 日共 80 条 check，`post_plan_event_count=0`；没有创建
   Dagster run，也没有修改动态分区。

P12 的数据与事件修复已经完成。恢复服务后仍需按原计划观察自然交易日运行；观察属于运行验收，
不再是本次历史数据重建缺口。

#### P12H 2026-08-15 分钟九转去价格后续收口

P12G 解决了 canonical QFQ bars 变化后的九转历史漂移，但当时分钟九转正式文件仍重复保存
`close_qfq`。后续专项已按[股票前复权九转 LLD](./dagster-stock-qfq-nineturn-dataset-low-level-design.md)
完成以下合同修正：

1. 四个分钟九转资产最终 schema 固定为
   `ts_code/freq/trade_date/trade_time/up_count/down_count/nine_up_turn/nine_down_turn`；不再保存
   `close_qfq` 或任何 OHLC、量额、涨跌字段。公式仍读取对应同频 `gold_stk_mins_qfq.close`，
   价格只在计算内部和 staging compact context 中存在。
2. 正式范围重新冻结为 2014-01-02～2026-08-14，四频各 3,068 个文件，共 12,272 个文件、
   197,753,897 行。candidate 全绿后才逐文件原子替换；最终聚合审计的缺失、schema、重复键、
   空键、分区、频度和非法值均为 0。
3. 新事件计划只选择四个分钟资产，实际追加 12,272 条 materialization 和最近 20 日共 80 条
   check；日线候选和 post-plan 候选均为 0，没有删除历史事件或创建 Dagster run。
4. canonical 去价格链路固定 DuckDB 2GB/1线程和 16GiB 进程峰值门禁；正式执行最高观测
   10.61GB。Reader 四频返回结果无价格，最近 5 日 readiness 为 20/20 文件、失败行 0；分钟
   sensor 已恢复 `RUNNING`，最近自然评估确认最近 5 日均 ready、0 run。

因此，P12G 的价格一致性检查和 12,268 文件数字只用于说明当时为何需要 canonical 重建，不能继续
作为分钟九转正式资产的当前 schema、检查或规模口径。日线九转及其 `close_qfq` 完全不受该后续专项影响。

## 9. 检查、readiness 与事件治理

### 9.1 Gold bars core check

每个 Gold bar asset 只保留一个合并 blocking check，内部规则：

1. 目标文件存在、schema exact、行数正数。
2. `trade_date/freq` 与 partition/asset 一致。
3. 主键非空且唯一。
4. 代码集合符合目标 asset scope/lifecycle。
5. 1m 允许 09:30；非 1m 禁止 09:30。
6. 所有频率禁止 `15:01-15:30` 输出，完整交易日最后一根必须等于 15:00。
7. 第一输出时间符合频率合同。
8. source window 与 anchor 完整，竞价成交只计一次。
9. OHLC、vol、amount、exchange 满足非公式 domain 合同。

不增加“逐条重算 Gold 公式”的第二套生产 check。窗口算法正确性由受保护的 literal fixtures
负责；生产 check 只验证本次输入、文件和范围没有偏离合同。

### 9.2 Lake readiness

1. 复刻仍 active 的 core check 语义。
2. 最近 10 个 expected dates，一次 DuckDB batch 查询。
3. 文件缺失：`materialized=False`，允许自动触发。
4. 文件存在但 core check 失败：`materialized=True, checks_passed=False`，禁止自动覆盖。
5. 不读取 Dagster event history，不因旧 event 颜色覆盖物理文件事实。

### 9.3 Governance mapping

新增 14 个指数 Gold check 后，必须同步：

1. `LakeAssetCatalogEntry`。
2. data card、中文名、partition model、schema contract。
3. `ASSET_CHECK_GOVERNANCE` exact mapping。
4. 最近 20 日 check retention 阶段。
5. 静态门禁要求 catalog blocking checks 与治理 mapping 完全相等。

## 10. 性能与写入安全门禁

### 10.1 日常路径

| 项目 | 硬门禁 |
| --- | --- |
| Sensor expected window | 最近 10 个交易日 |
| DuckDB connection | 每 tick 1 个 |
| RunRequest | 每 tick 最多 1 个 |
| Dagster event history | 0 次 |
| Tushare/Prod DB | Gold sensor 0 次 |
| Python 逐行聚合 | 禁止 |
| 已有坏文件自动覆盖 | 禁止 |
| Cursor | 只写 frontier、reason_code、计数、耗时，不写完整代码/文件清单 |

### 10.2 历史重建

1. 只能使用 bounded direct bootstrap/rebuild CLI，不用 Dagster backfill 发数十万 run。
2. 股票按 `freq -> stock-year` 分批；P4 已将单批冻结为一个频率、一个年份，禁止扩大为
   多频或多年全历史批次。正式运行继续记录文件数、行数、耗时与 RSS，超出 P4 预算即停止。
3. 指数按 `dataset -> freq -> trade-date batch` 分批，每批独立报告和 checkpoint。
4. 全量对账使用 DuckDB set-based 批量扫描、列投影和 partition pruning。
5. 递推下游不能只按“是否直接展示”判断影响范围。QFQ bars、MACD/KDJ/state、九转必须在 plan
   阶段逐项分类；未分类资产族直接阻断历史 promote。
6. 九转 canonical rebuild 继续按 `freq + year` 生成 candidate；每个审计动作必须小于 5 分钟，
   峰值 RSS 不超过 20GiB，不允许使用全市场 scoped rebuild 建立四频全历史临时表。
7. candidate 只能写 `/Volumes/datasource/data_lake_staging`，验证后同文件系统 `os.replace()`。
8. 任何磁盘不足、重复扫描、单批超预算、源文件变化或 fingerprint 漂移立即停止。
9. 报告写 `/private/tmp`，不把逐行结果写 Dagster metadata/cursor。
10. 历史等值和最终验收默认采用固定边界样本与聚合计数，不做逐文件全盘深审计；单个审计动作
   硬上限 300 秒，超过立即停止并缩小范围，禁止通过延长等待时间完成审计。

## 11. 测试矩阵

### 11.1 合同金样本

必须覆盖：

1. 1m 09:30 保留。
2. 5m 首根 09:35，包含 09:30 anchor + 09:31..09:35。
3. 15m 首根 09:45。
4. 30m 首根 10:00。
5. 60m 首根 10:30。
6. 90m 首根 11:00。
7. 120m 首根 11:30。
8. `09:30.open != close` 时使用 close。
9. `09:30.high/low` 异常时不使用，仅使用 close 锚点。
10. 09:30 vol/amount 非零且只计一次。
11. anchor 缺失/重复、regular 缺行/重复均失败。
12. 午休和 15:00 收盘窗口正确；`15:01-15:30` source 行保留在 Silver 但不得进入 Gold。
13. Gold 1m/5m/15m/30m/60m/90m/120m 全部不存在 `15:01-15:30` 的 key。
14. 七频完整交易日的 `max(trade_time)` 全部精确等于 15:00。

expected OHLCV 必须为人工字面量，禁止调用被测 builder 生成 expected。

### 11.2 定义与静态门禁

1. 指数 Gold 14 个 asset/check 的名称、路径、partition、依赖 exact。
2. 主要指数 technical deps 只指向 Gold，不得出现 Silver path。
3. 本地主要指数 bars reader 只指向 Gold。
4. 股票 90/120 builder 不得读取 Gold 30/60。
5. 所有 sensor 使用统一 run key/cursor builder。
6. 禁止 event history、无界 glob、逐代码 Python 聚合和多分区 check。

### 11.3 历史候选验收

1. 每个 asset/freq/date 文件数与 frozen plan 相等。
2. 通过 DuckDB 批量统计确认非 1m 的 09:30 行数为 0、所有频率 15:00 后行数为 0。
3. 第一 bar 时间做全量聚合计数；OHLCV 只对冻结的边界日期、exchange 和代码样本做字面值
   核对，不重新逐行计算全历史公式。
4. Gold/indicator 按批次对账 row count 与 key hash，并对代表日期执行双向 `EXCEPT ALL`。
5. state 按日期统计 previous-state 连接计数，并抽样验证 baseline、跨年和最新 frontier。
6. 股票 90/120 candidate 与现有文件只按 `90m/120m x 2014/2021/2026` 固定六样本对账
   row/key、逐 key OHLC/amount 容差、vol 和 exchange；不做全历史深审计。
7. staging 残留为 0，失败日期为 0。

## 12. 最终验收

只有以下条件全部满足，才算修复完成：

1. Silver 09:30 源事实未被删除或改写。
2. 三套 Gold 1m 保留 09:30；所有 Gold 非 1m 不含独立 09:30。
3. 三套 Gold 七频均不含 `15:01-15:30` bar；该时段不参与任何聚合、指标或 state。
4. 三套 Gold 七频完整交易日的最后一根 bar 均精确等于 15:00。
5. 七频第一根时间与第 2.4 节完全一致。
6. 第一根 OHLCV/amount 正确包含竞价锚点且只计一次。
7. 指数业务 bars 只读 Gold。
8. 主要指数 technical/state 只依赖 Gold。
9. 股票 1m affected codes 的 QFQ、MACD/KDJ、state scoped 重建完成；股票
   5/15/30/60 QFQ、MACD/KDJ、state 全历史重建完成。
10. 股票 90/120 已改为 Silver direct source，且历史等值审计通过。
11. 股票 30/60/90/120 前复权九转已从 canonical QFQ 完成全历史重建；九转 key 与对应 QFQ
    一致，30/60 无独立 09:30；正式分钟九转只保存业务键、计数和信号，不再持久化价格。
12. bars/indicators 时间键全量一致，API 和前端不补、不猜、不错位。
13. materialization 全量、check 最近 20 日、partition 归属和 latest binding 正确；九转重建事件
    也按相同保留口径补齐。
14. canonical rebuild 下游覆盖门禁可自动发现未分类的 QFQ 直接/递推下游。
15. 日常 sensors 连续至少 3 个实际交易日稳定，无 RPC timeout、重复 run 或错误覆盖。

## 13. Review 清单

本轮请管理员重点确认：

1. Silver 保留 09:30；Gold 1m 保留，Gold 非 1m 不输出。
2. 非 1m 第一根仍使用 09:30.close/vol/amount 作为内部 anchor。
3. `15:01-15:30` source 只留 Raw/Silver，不进入任何 Gold、聚合 bar、指标或 state；
   七频最后一根都固定为 15:00。
4. 七频首根时间和 source mapping 是否完全符合预期。
5. 主要指数与普通指数都新增 Gold bars；只有主要指数重建现有技术指标。
6. 股票 1m 只重建存在 15:00 后行的 affected codes；5/15/30/60 全历史重建；
   90/120 改 source 后先全量等值审计。
7. 所有 Gold/technical/rebuild job 都复用共享 writer，不在 job 中复制过滤 SQL。
8. 正式顺序是否接受：合同测试 -> 新代码 -> 临时 Lake -> 冻结 -> 指数 Gold -> 主要指数指标 -> 股票 QFQ -> 股票指标/state -> event -> reader -> sensors。
9. 遗漏补偿顺序固定为：九转 candidate 能力 -> 四频全历史 candidate/audit/promote -> 全量
   materialization -> 最近 20 日 check -> 恢复九转 sensor；不得用 daily job 或全市场 scoped
   rebuild 代替。
