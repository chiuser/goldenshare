# A 股分钟线 Gold 标准 K 线合同与历史重建 LLD

更新时间：2026-09-10（新增 §14 股票分钟缺口恢复方案；前文阶段状态保留历史含义）

> **2026-09-11 当前进度：**股票分钟线按 **2014 年起、Raw → Silver → Gold → 指标**恢复，完整方案见[§14](#minute-gap-recovery-2014)，硬约束见[§14.13](#minute-gap-execution-constraints)。**B0/B1完成；B2已将45,432个冻结窗口全部处理为45,422个取源流程完成、10个待排查，见[§14.27](#minute-gap-b2-until-accounted)。**2,247,629个单元来源齐备，130,878源空、121部分数据、1,230随异常窗口待处理；单位为频率×股票×日期。Raw保留来源代码、Silver起统一新身份。正式数据和事件未写入，B3及下游尚未执行。

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

<a id="minute-gap-recovery-2014"></a>

## 14. 2014 年起股票分钟缺口恢复方案

方案日期：2026-09-10，执行收口日期：2026-09-11。当前状态：**B0/B1完成，B2冻结窗口全部有交代，未取队列为0；B3及下游未执行**。最终45,422个取源流程完成、10个待排查，见§14.27及冻结目录b2-until-accounted-01/REPORT.md。源空/部分数据不等于恢复成功；下一步统一排查，不直接进入B3。正式数据、数据库、Dagster状态和事件未修改。

### 14.1 目标和执行结论

只补 **2014-01-01 至 2026-09-09** 的股票 Raw `1/5/15/30/60min` 缺口，实际首个交易日为 2014-01-02。2009—2013 年 Raw 保留原状，不补、不删；不为补数改动 Raw 全局历史起点。2014 起点来自 `run_contracts/stk_mins.py` 的 Silver/QFQ/指标合同。截止日使用本轮审计截止，不在执行中自动扩到当天。

推荐主线：**一次查源并保存返回 → 补齐 Raw → 完成受影响 Silver → 修复实际变化的 Gold → 顺序重算递推指标 → 对账与服务验收**。不用数万个逐股票逐日 Dagster run 驱动此次历史恢复。复用正式转换与检查能力，补上有界批量编排、来源缓存和候选提升能力。

直接从 Tushare 恢复 Lake Raw 是首选。现有 Tushare 修复能力已经存在，先修 Prod 再导回 Lake 会增加一轮数据库写入和全日导出，当前没有更省时的证据。Prod 路线仅作为后备，见 §14.8。

本次不实施 Gold30 多来源切换，也不修改 canonical 映射。之前“原生 30 分钟合格时 Gold30 应可生成”的方向仍保留，另行评审；此次先把上游按层修完整，不把两个任务混在一起。

### 14.2 缺口口径与冻结基线

本次业务缺口只包括：应有的分钟记录不存在，或已有记录的 `open/high/low/close/vol` 缺失。`exchange/vwap/amount` 等字段不用于扩大这份业务缺口清单。合法零成交量不算缺口；停牌、未上市、退市后的日期不强行补满。数值异常与 NULL 缺失分列，不以“有异常”冒充“缺字段”。候选仍需满足各层现有完整合同，不能因缩小审计字段而取消正式检查。

原审计一次扫描五频 Raw，后续计算均复用缓存。2014 年后的结果如下；“股票日”指一只股票在一个交易日，每频分别计数。

| Raw 频率 | 缺口日期数 | 股票数 | 缺口股票日 | 缺失常规分钟行 | 当前有更细频候选的股票日 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1m | 2,877 | 435 | 23,660 | 5,702,060 | 0 |
| 5m | 2,998 | 300 | 9,555 | 468,195 | 5,054 |
| 15m | 3,002 | 299 | 10,641 | 180,897 | 6,140 |
| 30m | 3,003 | 297 | 11,471 | 103,239 | 6,970 |
| 60m | 3,003 | 290 | 10,246 | 51,230 | 6,843 |
| 合计，含跨频重复 | — | — | **65,573** | **6,505,621** | **25,007** |

跨频去重为 **529 只股票、3,003 个日期、46,051 个股票日**。上述已确认缺口全部是该频率整股票日无行，不是局部缺几根。日期覆盖同期 3,086 个交易日中的 97.3%；每日受影响股票数中位数 9，2022 年占缺口股票日的 31.1%，另有北交所成批缺失高峰。

已有记录的缺字段结论已进一步分清：原扫描把 NULL、非有限值、负值、高低价包络异常合在基础质量计数里；本轮仅对标记价格异常的 **107 个文件读取 Parquet footer**，OHLC 与 vol 的 NULL 统计均为 0，且无未知 NULL 统计。其余文件原扫描该异常计数为 0。由此确认：2014 年后已有记录未发现 OHLC/vol 的 NULL 缺失。原价格异常计数（1m 1 行，5m 4,025 行，15m 3,859 行，30m 3,864 行，60m 3,862 行）单列，不计入 65,573。若其中非有限值等影响候选合同，在实际处理对应文件时报告具体原因，不能顺手扩大修值范围。

还有一组必须查源、不能遗忘的历史覆盖问题：**312 只股票、462,857 个股票日**，生命周期有效但本地日线和分钟缺少交易证据，五频均缺。它们是待确认范围，不是已确认漏采；若源站返回有效行情，转入同一恢复队列。不得用当前上市股票池删掉退市历史，也不得把某频率一次空返回外推成整只股票全历史无数据。盘中停牌相关疑点保留原审计分类，按准确交易时段解释后再决定是否补。

历史漏采、迁移遗漏或当时源端空返回的具体原因尚未定位。恢复不必等待根因查完，根因也不能由“现在源站有数据”倒推。

### 14.3 不重复审计：本次证据如何直接用于恢复

审计缓存根：`/private/tmp/dg_raw_mins_audit_20260910`。

| 已有材料 | 后续用途 |
| --- | --- |
| `recovery_queue.parquet` | 筛选 2014+ 后的确定缺口、精确分钟网格、来源状态和更细频候选 |
| `unresolved_stock_days.parquet` | 历史股票待确认范围、停牌疑点；不另外全湖搜一遍 |
| `observed/`、`classified/`、`reference/` | 覆盖、质量、身份有效期、生命周期、日历、日线及停牌的缓存证据 |
| `inventory.json`、`period_summary.json` | 文件集合、字节数、年代汇总；不重做全湖文件内容扫描 |
| `plan_estimates.json`、`plan_estimates.py` | 本节请求窗口、写文件与下游规模测算，可从缓存复算 |
| `ohlcv_null_footer.json` | 107 文件的 OHLC/vol NULL 元数据核对结果 |
| `plan_source_probe_1.json`、`plan_source_probe_2.json` | 本轮新增跨日源请求的完整返回，后续直接使用 |

实际开始执行时，将必要的队列、源响应和摘要一次转存至本次 run 的 `data_lake_staging`，记录清单版本及文件校验值；不能把 `/private/tmp` 当长期执行依据。只检查挂载、剩余空间、代码版本、已有批次完成状态及文件身份，不重新跑全湖缺口审计。没有并发写入的前提下，不设置重复全量 hash 或每层重查 Tushare。

允许且必要的读取只有：已有审计缺少的窄项补充、本次实际合并目标的读取、候选验收、写后读回。已经成功缓存的源窗口不再请求；只有失败、截断或明确不完整的窗口需要重试。原 12 个 5m 股票日的源可用性证据继续采用；因原会话未保存行情载荷，实际恢复仍需获取一次数据，不再另做一轮可用性探测。

### 14.4 查源批次：把 6.56 万次请求压到约 8,205 次

请求按“源代码 + 频率 + 时间窗口”组织，写入按“日期 + 频率”组织，两者不必相同。相同股票的相邻缺口合并；最多跨过 5 个已有数据的交易日，并限制窗口跨度。跨过的正常日期只用于减少请求，返回后只保留恢复清单命中的记录用于写入，不覆盖正常日期。

| 频率 | 每窗口最多交易日 | 行数预算，含盘后余量 | 已确认缺口窗口估算 |
| --- | ---: | ---: | ---: |
| 1m | 20 | 5,420 | 2,364 |
| 5m | 100 | 5,500 | 1,099 |
| 15m | 240 | 4,560 | 1,673 |
| 30m | 240 | 2,400 | 1,948 |
| 60m | 240 | 1,440 | 1,121 |
| 合计 | — | 单请求预算低于 6,000 行 | **8,205** |

相较逐股票日 65,573 次，减少约 **87.5%**。这是按最新代码归一后的计划估算，执行 planner 还须依据 identity_map 的有效期切回真实源代码，代码切换时拆窗口，不用最新代码盲查历史。窗口重叠统一去重；源端实际返回、分页和身份切分会改变最终请求数，不把估算当硬保证。

本地 Tushare 文档 `doc_id=370` 明确单次最大 8,000 行、支持起止时间和 limit/offset。现有 writer 的请求上限为 8,000，节流常量为 450 次/分钟；这不等于已经证明当前账号可长期跑满 450。生产批量请求应沿用 TushareResource，先单请求在途，样本通过后最多 2 个在途、全局最高 180 次/分钟；最终吞吐以实测和账号实际限制中较低者为准。此为本次离线批次预算，不改日常采集配置。

请求使用单一源代码，起点 `09:00:00`、终点 `19:00:00`，显式取正式 Raw 列，包括身份、freq 和 OHLCV。正常源返回的盘后记录保留来源事实，但不计常规缺口、不用于补造聚合盘后行情。8,000 行满页不得判定完整：继续正式分页；若 MCP 无分页参数则拆窗口。超时、权限错误、限流、结构错误均记录为请求失败，不能标成源无数据。

本轮新增真实样本，均已保存完整返回：

| 对象与窗口 | 返回 | 校验与用处 |
| --- | --- | --- |
| 600395.SH，1min，2020-01-02 至 01-03 | 482 行，两天各 241 行 | 两日网格完整，无重复/多余时点；OHLCV 非空、有限、非负，freq 正确 |
| 002690.SZ，5min，2015-08-05 至 08-07 | 147 行，三天各 49 行 | 三日网格完整，同上检查通过；exchange 为空不算业务缺口 |

工具调用耗时分别约 0.186/0.160 秒，仅证明这两次小窗口请求正常，**不能用来宣称全部长窗口都能在 0.2 秒完成**。早期默认 fields 与原 12 个 5m 样本的验证不重复；长窗口、最大容量和不同市场仍在执行首批校准。

历史待确认组按同样规则，五频分别约 23,822 / 5,353 / 2,705 / 2,705 / 2,705 个窗口，合计 **37,290**；与确定缺口合计约 **45,495** 个窗口，实际合并可减少。优先取粗频长窗口作历史交易线索，响应直接进入缓存；粗频空返回不能跳过其他频率。已确定缺口不被这组历史证据长期卡住，但全任务不能在这组尚未查完时宣称完成。

### 14.5 阶段、顺序和每批规模

| 阶段 | 做什么 | 批次与完成条件 |
| --- | --- | --- |
| R0：冻结执行清单 | 复用缓存，按 2014+、字段口径、身份有效期生成窗口和目标列表；保留确定/待确认/停牌疑点分类 | 不重扫全湖；先冻结确定范围，历史查源发现的有效数据追加为可追溯 revision |
| R1：查源与保存 | 已确认缺口先取 1m，再取 5/15/30/60m；同一阶段核清历史待确认组。一次返回同时承担“查到”和“待写数据”两项用途 | 首批 20 个窗口，覆盖沪深北、2014 早期、2021—2022 密集期、2025 成批缺失、2026 近期；随后每 200 窗口 checkpoint，缓存立即落盘 |
| R2：补 Raw | 先完成 1m 的源数据恢复，再按 5 → 15 → 30 → 60m 处理原生源与必要聚合。每个目标文件汇总该股票日所有结果再合并一次 | 首次 5—10 个日期频率文件；常规批为同频 20 个日期，候选合计不超过 2GiB。成功、无变化、源缺失、失败分别记录 |
| R3：完成 Silver | 只在 Raw 阶段验收后进入；同频 Raw 修复映射到 Silver，Raw1 变化还需评估全部四个粗频 Silver | 按 5—20 个日期共享 Raw1 与参考表，一次准备、五频复用；候选与现有 Silver 等价则不提升 |
| R4：完成 Gold bars | 只在 Silver 阶段验收后进入；用实际变化股票/日期集合映射到对应 Gold，不按原始缺口表盲重建 | 单频、单年、最多 128 个受影响代码；内存/耗时达上限则缩小代码或日期段 |
| R5：递推下游 | Gold bars 全部验收后，重算受影响 MACD/KDJ、state 和分钟九转 | 每频从每只股票最早变化前的可靠状态接续至截止日，跨年顺序；共享日期 state 汇总全部受影响代码后只合并一次 |
| R6：收口 | 按恢复队列和逐文件 checkpoint 汇总最终差异，验收 Reader/API；另按批准范围处理事件 | 不再进行第二次全湖缺口普查；旧范围减已补加残留必须逐项可解释 |

R1 内优先验证原 12 个样本的缓存状态、长期缺失头部股票和北交所集中缺失日期，以尽早发现源能力、身份和单位问题；大批执行按频率与日期分组，提高文件复用。Raw 尚有可恢复缺口时不启动 Silver；不能恢复的记录必须形成明确残留清单，不能静默跳过后宣布 Raw 已完整。是否对已闭合范围进入下一层，由阶段验收确认。

### 14.6 Raw 恢复规则

**源站优先。**目标频率返回有效记录就采用目标频率的源数据。原始响应逐窗口缓存；本轮只新增缺失记录，已有有效记录逐字段保留；已有但异常的记录另列，不把补缺授权解释为替换授权。当前确定缺口全部为整日无行，因此主要操作是追加该股票日，不是改写已有行情。

**本轮按2026-09-11管理员确认的第2步口径执行：目标原生源已完成查证后，对仍空、部分或不可直接采用的目标周期，使用同股票日齐备1min直接计算。**5/15/30/60min全部直接来自1min，不采用原建议的相邻周期递推顺序。1min本身不得倒推；原生目标数据已齐备的单元直接复用，不重复聚合。已退市股票的Raw也纳入，补不了的记录残留。

整股票日只采用一种齐备1min输入，不逐字段拼接、不插值、不前值填充。当前冻结恢复范围在正式Raw中均为整股票日无行：目标源整日为空时补整日；目标源仅部分缺失时，只生成缺失时间点的完整记录，已有有效原生记录保留，不用计算值覆盖。完整性判断和来源选择写入本轮执行清单，详见§14.29。精确清单与staging聚合入口已实现并完成样本验证，见§14.30；正式Raw提升尚未接入聚合。旧相邻周期顺序不能作为执行默认。

Raw 聚合遵守原生分钟含义：09:30 独立保留；连续竞价分上午、下午右闭窗口，open 取窗口首条、high/low 取极值、close 取末条，vol/amount 求和。**此处不把竞价并入第一根连续竞价 bar**；Gold 首根合并竞价沿用 §2，Gold30 首根仍标 10:00。价格不复权，数量按股、金额按元；不套用 Silver 的小成交归零，也不合成 15:00 后记录。

聚合是 Raw 来源合同的扩展，不能把生成记录声称为 Tushare 直接返回。推荐不增加行情业务列，使用随批次永久保留的逐记录来源清单，记录 `origin=source/aggregated`、源频率、父输入键/校验值、聚合规则版本、目标文件校验值；正式资产 metadata 引用该清单，catalog 的来源说明和相关检查同步更新。聚合载荷与原生响应分开保存，不伪造源响应。来源清单作为解释正式数据的证据不能随临时缓存清理；未经该合同及消费者校准，不提升聚合 Raw。

聚合后的辅助列也必须有确定合同：amount 从同单位输入求和；建议派生 vwap 在 vol > 0 时为 amount / vol，vol = 0 且 amount = 0 时按 close 作为无成交约定值，并在聚合规则版本中明确它不是源站原生 vwap。vol = 0 但 amount > 0 不生成候选。该约定须随 Raw 聚合来源合同一起批准并通过单位及零成交样本，不能仅为通过非空检查随便填 0。exchange 按正式 schema 保留/规范身份，不因空值扩大缺口。若辅助列阻断正式检查，报告为合同问题并保留候选，不顺手恢复不在本次缺口范围内的字段。

### 14.7 Silver 和下游按实际变化修复

当前 `write_silver_stk_mins_partition` 已做身份映射、最终停牌过滤、已批准价格修正、小成交单位处理，并允许粗频异常/整日缺源通过 Raw1 的标准化结果重算。因此不能把此次 Raw 原始聚合直接复制到 Silver，也不能因为 Raw 变了就断言对应 Silver 一定变了。

| 实际变化上游 | 需要生成候选的下游 |
| --- | --- |
| Raw1 | Silver1，以及使用 Raw1 修正/补源的 Silver5/15/30/60 |
| Raw5/15/30/60 | 对应频率的 Silver |
| Silver1 | Gold1、Gold5 |
| Silver5 | Gold15、Gold30 |
| Silver15 | 当前 canonical Gold 没有直接使用它；仍要把 Silver15 修完整 |
| Silver30 | Gold60、Gold90 |
| Silver60 | Gold120 |
| 实际变化的 Gold 七频 | 对应频率 MACD/KDJ 与递推 state |
| 实际变化的 Gold30/60/90/120 | 对应分钟九转；保留当前无价格字段合同 |

仅确定缺口的保守候选范围：Raw **14,883 个日期频率文件**，原文件合计 **69,874,623,956 字节（约 65.08GiB）**；Silver 最多 **14,889 个日期频率文件**；Gold 候选最多 **6,952 个股票频率年文件**。这不是最终要改写的数量，Silver 已经补过或新旧等价时，下游范围会收缩。

递推计算不能只补缺口那一天。由上述保守范围推算，MACD/KDJ 最多涉及 **16,630 个股票频率年文件**，七频 state 的日期范围最多 **21,602 个文件**；共享 state 文件必须保留未受影响代码，不能按股票批次反复全日重写。该上界未按退市日再次收缩，也不含待确认历史组新增影响；真实执行清单由实际变化 manifest 决定。

复权继续使用当前统一计算和基准：冻结本次 as-of 因子事实并核对目标股票的现有基准。若某股票现有年文件基准不一致，扩大到该股票对应频率的必要历史 bars 重算，不能把不同基准拼在一个年文件里，也不扩成全市场因子修复。

MACD/KDJ 从最早变化之前精确上一交易日的可靠 state 接续；不存在可靠 state 时回到 2014 基线，不能取一个不完整的近似 warm-up。各频率日期严格升序，状态连续传递；九转按当前递推/历史输入定义同步处理。Gold bars 的正确性验收和递推结果验收分开进行。

历史待确认股票如恢复出行情，但缺少必要身份、停牌或复权因子，必须列明依赖缺口。Raw 可以保留有效原生行情；不得为了让 Silver/Gold 通过而编造这些参考事实，也不自行扩大为日线或因子全历史恢复任务。

### 14.8 现成代码、需要补充的能力与 Prod 备选

下列路径相对 `lake_console/orchestrator/src/orchestrator/`，均经当前代码核对。

| 入口 | 已有能力 | 本次使用方式/差距 |
| --- | --- | --- |
| `defs/assets/stk_mins.py::merge_repair_raw_stk_mins_partition_from_tushare` | 现成按股票、单日、单频 Tushare 修复；要求目标日期文件存在 | 可复用归一化、合并语义；不能先查源再调用此入口重拉。其 merge helper 目前以 `executemany` 加载修复行，在正式目标旁写 `.tmp` 后提升；本次必须补列式 staging 候选接线，不能把原入口原样循环当作符合本方案的批量工具 |
| 同文件 `_fetch_raw_stk_mins_rows` | 正式字段、8,000 行分页、逐请求节流 | 单日参数和内存汇总不适合跨多年整体调用；需有界跨日 fetch/cache 和缓存消费入口 |
| 同文件 `write_silver_stk_mins_partition` | 现行完整 Silver 转换；已有候选输出路径参数 | 保持唯一业务语义；补批量共享 Raw1/参考表的编排，避免同日反复读取 Raw1 |
| `defs/bootstrap/stk_mins_silver_replace_from_raw.py` | 已有单日五频恢复及诊断接线 | 当前 apply 仍有 quarantine/backup、重复 plan 和异常清理路径，不符合本次无备份、保留现场与不重复审计要求；复用其 writer/diagnostics 调用，不直接执行该 CLI，也不在本次顺手全面清理旧工具 |
| `defs/bootstrap/stk_mins_raw_replace_from_prod.py` | 同日五频候选、校验、原子提升、checkpoint | 当前依赖 full-market TaskRun 与 current-listed 对象集合；不直接套到历史/退市股票 |
| `defs/bootstrap/stk_mins_qfq_canonical_history.py` | canonical 历史候选/审计/提升 | 既有 P7 粗频全市场、1m 特定 affected scope，不直接拿旧计划重跑；需消费本次精确变化清单 |
| `defs/bootstrap/stk_mins_bse_qfq_recovery.py`、`stk_mins_bse_recursive_recovery.py` | 有 BSE 专项 scoped 候选和递推恢复结构 | 参考其批量设计和共享底层能力；不放宽 BSE 专项白名单来承接沪深，不伪造专项 manifest |
| `defs/bootstrap/stk_mins_qfq_macd_kdj_history.py` | 支持 freqs/stock_codes/日期范围与 checkpoint 的顺序历史重算 | 保留上一 state 语义；评估并补齐本次统一 staging/逐文件恢复接线，不能误把 history plan 当纯只读 |
| `defs/bootstrap/qfq_nineturn_history.py` | 分钟九转历史与 canonical 候选能力 | 按真实 Gold 变化范围接线，保留当前公式、字段、批量读写合同 |

**2026-09-10 排期修正：已有修复工具，不应把整套批量优化和条件性能力全部列为开始恢复的前置开发。**工作拆开处理：

1. **已有的恢复能力：**Tushare 单日单频多股票 merge repair、Silver 转换、QFQ 候选和指标历史计算均有实现。它们是可复用能力，不是已适配本次范围的一键执行器。优先按本次精确范围接线、复用校验和 checkpoint，不重写行情算法或重建一套恢复平台。现成入口的执行粒度、候选路径和专项范围限制仍须遵守。
2. **为减少总耗时而补的编排：**跨日窗口、响应缓存、缓存到 Raw 候选的接线。这是把约 65,573 次请求降到约 8,205 个窗口所需的增量能力，不是现成 merge_repair 已经支持的功能。根据最小补充代码及首批实测比较“接线成本 + 优化后运行时间”与直接使用现成入口的总时间；不能为追求请求最少而做成本更大的通用改造。两种路径均禁止先查后再拉一遍相同源数据。
3. **遇到真实需要才做的能力：**只有目标频率源站确实缺失时，才落地聚合 Raw 的来源合同与相关测试；不把这一分支作为原生源获取和恢复的前置条件。Silver/Gold 的批量优化与下游范围适配到对应阶段处理，复用现有实现，不能作为 Raw 开始前的全量重构要求。

阶段编号不得进入正式代码概念，不加新 sensor、前端配置或另一套 Silver/Gold 算法。阶段验收和只修实际变化范围的要求不变。

Prod 备选仅在两个条件之一成立时启用：Prod 已经有完整目标行情且有界导出实测比源请求省时；或者必须先让生产采集链完成恢复。届时先单独冻结 Prod 股票/日期/频率白名单及单位，用现行 ingestion/TaskRun 正式执行能力恢复 Prod，再通过正式 Raw from Prod 链路生成 Lake 候选。现成全市场单日替换不支持的历史范围要先改造，不能改当前上市池来凑覆盖。此路线的生产写入、导出与耗时另报，不计为当前默认路线已具备或已获执行批准。

### 14.9 性能预算和整体耗时

**本次修正版统一报“必要接线和验证 + 源请求 + 文件修复 + 下游计算 + 验收”的总时间，不再把准备工作藏在运行时间之外。**按下方工作包估算：

| 交付范围 | 从获准开始到该范围交付的总预算 | 包含什么 |
| --- | ---: | --- |
| 先完成已确认的 65,573 个股票日频率缺口及其下游 | **12—25 小时** | 必要接线/隔离验证约 6—10 小时，加原生源请求和逐层运行约 5—15 小时；是可单独选择的首期范围 |
| 默认完整范围：再包含 312 只历史股票的查源、可恢复数据及下游 | **18—42 小时** | 上行范围，加约 3.5—10.5 小时历史请求和约 2—6 小时新增处理；按共同文件合并，不把两行时间相加 |
| 确认需要更细频聚合恢复 Raw | **在所选范围上另加 3—6 小时** | 约 2—4 小时聚合分支接线/验证，约 0.5—2 小时候选生成及对账；受影响 Gold/指标仍只最终重算一次 |

**建议完整任务按 24—36 小时安排，容量预留到 48 小时。**“18—42 小时”和“加 3—6 小时”是工作量估算，不是测得的 SLA；首批20个源窗口已完成，取源实测及当前外推见 §14.17；10个候选文件尚未执行，文件处理与整体完工时间仍保留估算。外部权限、源不存在、身份/因子阻塞和等待管理员确认的时间不计为连续作业时间，必须单列，不能承诺一定在预算内把不可恢复数据补出来。若只批准首期，则按 12—25 小时执行并明确历史待确认组尚未闭合。

此前笼统的“先开发 2—4 个工作日”，以及只报机器运行 5—12/12—30 小时的表述，均由此表替代。6—10 小时准备预算来自 §14.12 的具体工作包，仍是工程估算；不因用户质疑而声称现成工具已经具备跨日缓存和统一候选能力。

依据分三类：

- **本轮实测：**全 Raw 83.23GiB、45.88 亿行扫描约 9 分 16 秒，包含参考分类的计算约 25 分钟，峰值 RSS 约 3.16GiB。这证明重复普查没有必要，不能直接当成 Parquet 重写速度。
- **历史执行参考：**本文 P8 的全市场 5/15/30/60m 指标重建分别约 22.1/11.1/8.9/8.5 分钟，合计约 50.6 分钟，历史峰值约 15—16GiB；本次引入 1m 和 scoped state 合并、不同批次内存上限，不能照搬这些耗时。
- **规划假设：**批量源请求持续有效吞吐按 60—180 次/分钟估算；文件恢复含读取、列式计算、压缩、候选验证、提升与写后读回。首次 20 窗口和 5—10 文件样本用于把假设替换成实测，不再跑一轮缺口审计。

| 阶段 | 仅已确认缺口的规模/模型 | 机器运行及操作时间预算，不含下述接线工作 |
| --- | --- | --- |
| 队列冻结与样本 | 复用缓存，20 请求窗口与 5—10 文件 | 15—30 分钟 |
| 源获取 | 8,205 窗口，常规完整返回含余量约 760 万行；实际响应另计 | 45—140 分钟 |
| Raw 合并和必要聚合 | 最多 14,883 文件、现存约 65.08GiB；每个目标只合并一次 | 45—120 分钟 |
| Silver 候选与实际变化判定 | 最多 14,889 文件；共享 Raw1 与参考输入 | 60—150 分钟 |
| Gold bars | 最多 6,952 个股票频率年候选；只提升实际变化 | 30—90 分钟 |
| MACD/KDJ、state、九转 | 按实际受影响股票最早日期递推至截止，不按缺口日孤立计算 | 60—180 分钟 |
| 汇总、服务验收及已批准观测收口 | 增量清单对账、有界 API 样本；不全湖重审 | 30—60 分钟 |

上述各项相加约 4.75—14.5 小时，按 **5—15 小时**计入总预算，不能再把这个小计称为整体完成时间。准备工作按 §14.12 的 B0/B1/B4/B5/B6 估算，合计约 6—10 小时。计划表按串行相加；如果源下载等待期间能够完成后续接线，只把节省算进实测 ETA，不提前重复扣减。

历史待确认组另加 37,290 窗口，按 60—180 次/分钟约 **3.45—10.36 小时纯请求时间**；若全部返回完整数据，含盘后余量约 1.68 亿行，归一化、文件合并和新增递推按 **2—6 小时**另计，因此得到前表完整范围的 18—42 小时。实际来源代码拆分、超额分页可能增加请求；全部 45,495 窗口按 30 次/分钟就需约 25.3 小时纯请求，届时总预算必须上调，不能持续沿用原 ETA。

执行实时 ETA：`剩余窗口 / 最近稳定有效请求速率 + 剩余文件字节 / 本阶段实测处理速度 + 剩余递推批次耗时`。每 200 请求、每 20 文件或每个递推批次更新；只重试失败单元，已完成工作不重跑。

| 资源项 | 本次建议上限与超限处理 |
| --- | --- |
| 网络 | 最多 2 请求在途，全局最高 180 次/分钟且不超过账号限制；失败率超过 5% 或持续限流先降速并暂停派发新批次 |
| 数据缓存 | 每个响应立即落盘；每缓存批最多 200 窗口，内存只保留一个响应及小型状态，禁止把全范围返回长期放内存 |
| Raw/Silver | DuckDB 初始 2 线程、2GiB 引擎内存，批候选不超过 2GiB；进程 RSS 超 4GiB 缩批，不直接加并发 |
| Gold/递推 | 单频单年、受影响代码批量；先沿用已核清的专用连接配置，样本决定是否沿用 14GB 历史配置；进程 RSS 硬上限 20GiB，不多开大内存进程 |
| 长操作 | 单候选审计不超过 300 秒；超时拆批，不拉长 timeout。网络请求有超时、最多 3 次有退避的失败重试，最终失败留队列 |
| 磁盘 | 执行前由文件清单算候选、源缓存和递推输出，至少留“预计保留证据/缓存 + 两倍最大在途候选 + 20GiB”；初步按 200GiB 空间预留，样本估算超出则先调整批次 |
| 写放大 | Raw 完整目标文件仍需重写，不能把仅 650 万新增行误当全部 I/O；目标读取、候选写出/校验、写后读回均计入预算 |

新增批次参数仅归入本次离线恢复计划及其版本化 schema，逐项记录默认值、来源、消费者、生效和测试，不散落 env、脚本常量、页面配置，也不更改日常 DuckDB/采集参数。

### 14.10 安全、幂等与验收

正式根固定 `/Volumes/datasource/data_lake`；执行候选与来源证据固定在 `/Volumes/datasource/data_lake_staging` 的本次 run 目录。同文件系统逐文件 `os.replace()`，不宣称多文件事务。不使用旧 Lake、Kopia、备份快照或生产表清空。执行使用当前工作区，不创建分支/worktree。

幂等单位为一个请求窗口或一个正式目标文件。checkpoint 保存输入/计划版本、目标、状态、行数、候选校验结果、提升后的身份。中止不领取新单元；已提升文件保留，未完成候选保留现场；恢复只继续缺失/失败单元。内容校验在实际读取/输出时完成，不另安排重复全文件 hash 扫描。全局阶段屏障防止 Raw 未完成就触发 Silver/Gold；日常相关 writer 如可能启动，在正式执行前按批准维护窗口处理，本轮不改 sensor 状态。

必须通过的验收：

1. **范围：**2014 之前写入计数为 0；未列入计划的股票日和字段不被修值；返回窗口跨过的正常日期不进入替换集合。
2. **Raw：**请求身份/频率、交易网格、键唯一、OHLCV 缺失和原始单位核验；当前正式 schema 与 blocking checks 同源复用。整日 241/49/17/9/5 是网格预期，合法停牌须有解释；exchange 空不成为缺口。
3. **聚合：**无目标源时才启用，整日单一更细频来源；auction 独立、午休边界、首末 OHLC、volume/amount 求和、有零成交、无完整更细频、源缺部分窗口等正反例全部覆盖。先用两源均完整的有界样本比较量价，首批建议三市场各两日；差异未解释则不提升聚合结果。
4. **Silver：**正式身份/停牌/已批准修正/量纲合同保持；新旧候选按同键对比；等价文件不重写，实际变化输出精确 code/date/freq manifest。
5. **Gold：**只消费映射后的合格 Silver；同复权基准，竞价只计一次，Gold30 首根 10:00、每日 8 根，尾端 15:00；未受影响键保留。
6. **递推：**补点影响沿日期传播；精确上一 state、跨年、取消续跑、相同批次重放、未受影响代码合并保留；bars/indicator 键集合一致，九转遵守当前无价格合同。
7. **交付：**缺口起数 = 已恢复 + 有依据不应有数据 + 源与更细频均缺 + 失败待处理；待确认组逐项有源证据或保留明确未决。非零未决/失败时不得写“全部补齐”。
8. **服务与观测：**本地 Lake Reader、股票 minutes/minute-indicators API 做有界样本，确认没有因缺 bars 或指标键不齐而丢点；前端不补行情。若需要 runless materialization/check，先输出按实际变化分区去重的数量，再单独批准执行；文件通过不代表事件已补齐。

测试只围绕恢复能力和合同负例，不重做信号研究。隔离测试不得连接正式资源。正式候选验收复用现有 checks 的纯计算能力，禁止在 writer 中复制一套更宽松的业务规则。观测失败不能回滚已成功的行情文件。

### 14.11 影响面、文档与执行授权

本轮已使用 `codegraph_explore` 核对 Raw fetch/repair、历史 QFQ/MACD-KDJ 链路；使用 `codegraph_impact(write_silver_stk_mins_partition, depth=2)` 核对 Silver writer 与五个资产消费者，并补查真实 SQL、canonical 映射、九转资产和股票分钟 API/Reader。图索引不能证明完整运行时资产依赖，因此开发冻结时还需从当前 catalog/Definitions 的隔离依赖图生成最终下游清单，逐族标记 rebuild、equivalence 或有证据的 no-impact，不能遗漏动态注册消费者。

需要同步的实现与合同面：Raw asset/config/source metadata 与 catalog、来源获取和候选编排、Silver 原生转换及批量复用、Raw/Silver/QFQ readiness/check、daily/历史 rebuild/factor repair 共用 writer、MACD/KDJ/state 与九转历史恢复、Reader/API 合同回归和恢复测试。默认不改 API 响应字段、前端行为、日常调度及复权公式，不扩为所有指数或全市场重建；具体代码文件在开发前按此表收敛，不因现有历史脚本可用而扩大执行范围。

文档本轮只修改本文及 [stk_mins 资产设计](./dagster-stk-mins-asset-design.html) 的范围入口；不新增平行设计、不改母线程报告。实现阶段若涉及来源合同、指标或检查变化，再同步对应既有 schema/catalog、QFQ 检查治理、MACD/KDJ、九转设计文档。架构依赖矩阵不变，orchestrator 不导入生产 Ops/Web；Prod 备选的生产变更另行设计与批准。

依据包括 [管道性能治理](./dagster-data-pipeline-performance-governance.md)、[编码规范](../../orchestrator/CODING_STANDARDS.md)、[字段合同](./dagster-asset-schema-contract-design.md)、[Tushare 历史分钟本地源文档](../../../docs/sources/tushare/股票数据/行情数据/0370_股票历史分钟行情.md)。资产、分区及检查的通用概念核对了 [Dagster assets](https://docs.dagster.io/guides/build/assets)、[partitions/backfills](https://docs.dagster.io/guides/build/partitions-and-backfills) 和 [asset checks](https://docs.dagster.io/guides/test/asset-checks)；本项目实际行为仍以当前代码与冻结执行清单为准。

下一步先评审本节，确认默认直接修 Lake、批次和预算，再开发最小批量能力及隔离测试。正式执行按 Raw、Silver、Gold/递推、事件分别收口；本次要求写方案不视为允许立即 materialize、backfill、数据库写入、Lake 提升、runless event、部署或提交。

<a id="minute-gap-execution-work-packages"></a>

### 14.12 可执行工作包与交接清单

本节将 §14.1—14.11 收敛成执行顺序。**默认一次处理“确定缺口 + 历史待确认组”的完整范围，避免先补确定缺口、再为历史组重复重写同一日期文件及下游。**确定范围单独交付的 12—25 小时只是可选首期预算，不是默认先做一次、再做第二次的执行方式。

#### A. 固定入口、工件和工作量

工作目录固定 `/Users/congming/github/goldenshare/lake_console/orchestrator`，解释器使用已有 `.venv/bin/python3 -B`。正式 Lake 不变；执行根建议为 `/Volumes/datasource/data_lake_staging/stk_mins_gap_recovery/run_id=<本次唯一运行号>`。本轮不创建该目录。输入缓存只来自 §14.3，不重新生成原始审计。

恢复入口为 `defs/bootstrap/stk_mins_gap_recovery_cli.py`；清单/运行约束在 `stk_mins_gap_recovery.py`，源缓存、并发调度/批清单和Raw候选分别在 `stk_mins_gap_recovery_source.py`、`stk_mins_gap_recovery_fetch.py`、`stk_mins_gap_recovery_raw.py`。文件按职责分开，未注册新 Dagster 定义；已有 provider、Raw 字段和归一化直接复用，未修改 BSE 专项白名单。B4—B6 接线仍待各自阶段实施。

执行根下的交接工件固定如下；运行过程中每份清单带 plan hash，不能传错批次：

| 工件 | 必需字段与作用 |
| --- | --- |
| `plan.json` | 日期范围、频率、正式/执行根、输入缓存版本、运行参数、源字段、数量上限、当前合同版本 |
| `scope.parquet` | scope_id、latest_ts_code、source_code_candidates、响应确认后的 source_ts_code、freq、trade_date、缺失时间点、交易证据、是否待查；业务身份一次归一，请求代码不靠逆向唯一假设，见 §14.15 |
| `source-windows.parquet` | window_id、source_ts_code、freq、起止时间、命中的 scope_id、预计行数；同一请求不得分属两个重复窗口 |
| `source-index.parquet` 与 `responses/` | 请求参数、响应路径、行数、返回日期、载荷校验值、分页/错误状态、时间戳；已有完整响应直接引用 |
| `raw-resolution.parquet` | 每个 scope 的 source-ready、source-empty、source-partial、request-failed、aggregate-ready 或 unresolved，及对应载荷/父来源 |
| `file-plan.parquet`、`checkpoint.jsonl` | layer/freq/date 或 stock-year、目标路径、输入片段、候选路径、生成/校验/提升/读回状态；以文件为恢复单元 |
| `actual-changed-raw/silver/gold.parquet` | 实际新增或变化的 code/date/freq、改变的业务键、来源；未变化内容不进入下游计划 |
| `recursive-scope.parquet` | code/freq/最早变化日/精确上一 state/截止日/目标年文件及共享 state 文件 |
| `completion.json`、`residuals.parquet` | 起始数量、恢复/不适用/源缺/失败/未决数量、文件结果、耗时和残留原因 |

工件属于本次恢复证据，不是新的生产数据库或每日维护平台。每个响应/完成文件立即记录，按固定数量压实小型索引，不把全量响应放内存。来源 provenance 和已提升文件清单长期保留；它们不是可随手删除的临时载荷。

#### B. 按顺序执行的工作包

“准备时间”是编码、接线、隔离测试的工程估算；“运行时间”是数据处理估算。以下分项能相加得到 §14.9 总预算，未进行的工作不记作实测。

| 编号 | 输入 → 明确动作 → 输出 | 已有能力 / 必要增量 | 单批规模、退出条件 | 准备时间 | 运行时间 |
| --- | --- | --- | --- | ---: | ---: |
| B0 冻结清单 | 审计缓存 → 筛 2014+、归一最新业务身份并固定有效源代码候选、把确定/待确认范围统一去重 → plan/scope/windows | 已完成冻结清单；请求选择按 §14.15，实际结果见 §14.16 | 65,573 确定单元 + 462,857 待确认股票日；不再次扫 Raw；超出冻结范围报错 | 15—30 分钟，原估算 | 5—10 分钟 |
| B1 完成 Raw 最小入口 | windows → 跨日 fetch/cache、从缓存构建列式候选、checkpoint/提升 → 可验证的恢复入口 | 已完成缓存、staging候选及隔离验收；复用TushareResource和正式归一化，不调用旧merge helper写正式文件 | 隔离覆盖多日、返回空/部分/满页、错代码/频率、重复键、取消续跑、正常行保留；通过后才允许正式源与文件操作 | 2.5—4 小时 | — |
| B2 校准并取源 | windows → 首批 20 窗口后继续同一队列 → responses/source-index/raw-resolution | 使用 B1；已有完整载荷跳过网络，原 12 样本只有可用性证据的仍取一次载荷 | 1 请求在途起步，最多 2；每 200 窗口 checkpoint。所有目标源请求有明确终态才关闭该文件的来源集合 | — | 首批已完成：20窗口、25请求、19.54秒；完整结果与约12.3小时剩余取源线性外推见 §14.17。旧分组预算保留在 §14.9作比较 |
| B3 完成 Raw 文件 | raw-resolution → 先原生 1m，再 5/15/30/60；汇总同一目标全部输入、候选验收、逐文件提升读回 → actual-changed-raw | B1 列式合并 + 正式 schema/checks | 首批 10 个来源已闭合的文件；随后同频 20 日期/批，最多 2GiB；同一目标不按股票反复提升 | — | 确定组 45—120 分钟；历史新增处理在全任务额外 2—6 小时额度内 |
| B3a 条件性聚合 | source-empty/partial 的准确缺失时点 → 按 §14.6 用齐备1min仅生成缺失记录 → aggregate-ready/残留 | 复用时间网格与 OHLCV 聚合基础，补 Raw 来源追溯和辅助列约定；只有确需时进入 | 先每市场两日、跨午休/竞价/零成交正反例；无法形成完整候选的单元留残留。请求错误不能进入此分支 | 2—4 小时，仅发生时 | 0.5—2 小时，仅发生时 |
| B4 完成 Silver | actual-changed-raw → 计算受影响五频、正式转换、候选诊断、等价比较 → actual-changed-silver | `write_silver_stk_mins_partition` + `evaluate_silver_stk_mins_partition_diagnostics`；补文件队列与输出清单 | Raw 阶段先闭合；以日期为一组，Raw1 与参考表可共享；等价不提升。最多 14,889 个确定组候选 | 0.5—1 小时 | 确定组 60—150 分钟 |
| B5 完成 Gold bars | actual-changed-silver → canonical 映射、统一复权基准、精确 stock/date 关系过滤、候选合并 → actual-changed-gold | `build_canonical_gold_stk_mins_qfq_select_sql`、`write_gold_stk_mins_qfq_rows_to_year_files`；补精确范围与 staging 接线 | Silver 阶段先闭合；同频同年最多 128 代码；仅确定组最多 6,952 年文件，不调用旧 P7 全市场 plan | 1—1.5 小时 | 确定组 30—90 分钟 |
| B6 完成递推指标 | actual-changed-gold → 每股票频率最早变化至截止日、可靠前状态、递推候选及共享 state 合并 → 指标与 state 完成清单 | `write_gold_stk_mins_qfq_macd_kdj_rows` 与九转 history SQL；参考 BSE candidate 接线但不放宽其白名单 | Gold 阶段先闭合；每频按年升序，计算可分代码块，最终同一 state 日期文件统一合并一次；七频 MACD/KDJ + 四频分钟九转 | 1.5—2.5 小时 | 确定组 60—180 分钟 |
| B7 验收与交付 | scope + 各层 checkpoint → 已修/残留对账、Reader/API 固定样本 → completion/residuals | 现有检查与 Reader/API，无新增页面功能 | 所有可恢复单元闭合、未决明示；不重扫全湖。事件按单独批准清单处理 | 纳入各工作包 | 30—60 分钟 |

B0/B1/B4/B5/B6 的准备分项合计 **6.25—9.5 小时**，排期取约 6—10 小时；B3a 不发生则不花这笔工时。下载等待期间可以完成后续接线，但不运行下游数据转换，也不据此提前减少预算。

首批 20 个窗口组已固定在 §14.16 的 `first-source-batch.json`，覆盖原 12 个股票日所在窗口、001872.SZ 的 2014 年五频、北交所五频和其他早期日期。已有 600395.SH 两日 1m、002690.SZ 三日 5m 探针日期不在实际缺口 scope，核验后仅保留为离线验证载荷，不能为了满足抽样描述而扩大正式恢复范围。源代码候选来自 identity_map，按 §14.15 复用缓存、优先新码、仅对仍缺部分尝试别名；身份 MCP 的有效载荷同样复用。

实际冻结主窗口组为 45,432 个，原 45,495 是冻结前估算。实际 HTTP 请求还受缓存命中、别名追加、部分日期切分和满页分页影响，不能把窗口组数冒充最终请求数。

源获取按频率分批：确定组约 **43 个、每批最多 200 窗口**（1m/5m/15m/30m/60m 分别 12/6/9/10/6 批）；历史待确认组约 **189 批**。这些是按现有窗口估算向上取整，不是固定请求总量；身份切分、去重和满页拆分均写入计划 revision。

Raw 确定组按同频 20 日期/批，约 **747 批**，每批仍逐文件完成；这不等于创建 747 个 Dagster run。正式目标首批只选来源已经闭合的 10 文件，成功后从剩余文件队列继续，不重做首批。尚未闭合的文件最多做 staging 性能候选，不提前提升后又为同一天剩余股票反复重写。

#### C. 需要补的代码限定到具体工作

1. **窗口与缓存：**B0 输出窗口表；B1 对每个窗口调用 `TushareResource.call("stk_mins", params, STK_MINS_RAW_COLUMNS)`。单响应最多一页数据常驻内存，分页逐页保存。先校验请求起止范围，再按返回交易日分组调用既有 `_normalize_tushare_stk_mins_row` 的单日语义；不能把多日数据传入单日 partition_key，也不放宽现有身份/频率校验。日期、枚举、整数数量和 NULL 规则复用正式合同。
2. **Raw 合并：**既有 `_merge_repair_raw_stk_mins_rows` 的键为 `ts_code + trade_time`。新候选计算沿用同键排除旧行再并入修复行的语义，修复关系来自缓存 Parquet，不用 `executemany`。一次加载目标关系后同时得到替换/新增统计与合并输出；输出在 staging，验收通过才提升。不要调用旧 helper 把 `.tmp` 写到正式根，也不为复用它复制整份 Raw 到 staging 再多读一遍。
3. **Silver 接线：**直接使用正式 writer 的 `output_path_override` 生成候选、调用正式 diagnostics；补 plan/checkpoint 和新旧语义比较。第一批测出同日 Raw1 重复读取成本，若超过预算，只提取同连接共享输入的批量入口；不在开始前强制重构五频 writer。`stk_mins_silver_replace_from_raw_cli` 原样 apply 不是此次执行命令，其备份和重复 plan 行为不符合本次方案。
4. **Gold 接线：**向 canonical SQL 传明确的 `silver_paths/trade_adj_factor_paths/as_of_adj_factor_paths/target_freq/partition_keys/stock_codes`。代码×日期列表会形成矩形候选，因此最终替换关系还必须 join 精确 affected pairs；不能因股票 A 缺 D1、股票 B 缺 D2 就连 A-D2/B-D1 也替换。目标 writer 使用 staging 输出根、来源用正式文件显式路径；保留该年非目标日期。候选所需既有年文件仅在构建时读取/准备一次，不把 staging 当独立事实源。
5. **递推接线：**使用正式 MACD/KDJ writer 的显式 `source_qfq_paths/target_trade_dates/previous_state_paths/stock_codes`；上一批的新 state 优先接下一批，不能再次读旧正式 state 作为新历史结果。新旧 state 按代码合并，全部代码块完成后再提升同一日期文件。九转使用现有 `build_gold_stk_mins_qfq_nineturn_history_batch_select_sql` 的 context/seed 语义，不复制递推公式。正式 QFQ 和 prior state 的输入路径与 staging 输出路径分开。
6. **检查与回归：**新增只针对本入口的 planner/cache/candidate/checkpoint 测试；复用 `test_stk_mins_raw_m4_contracts.py`、`test_stk_mins_silver_m5b_contracts.py`、`test_stk_mins_qfq_partition_rewrite.py`、`test_stk_mins_qfq_m12_macd_kdj.py` 等相关测试。实际运行前检查隔离夹具与受保护启动器要求，不把这些文件名直接当批准运行正式测试资源的命令。未改公式不重新进行全市场指标公式审计。

预计只新增本数据集的 CLI/编排模块及针对性测试，必要时在已有 writer/helper 中补来源缓存或输出接线。若代码评估显示必须改多个正式合同或通用基础设施，超过上述工作包，就报告具体新增工作与新预算，不以“接线”名义扩成通用平台。

#### D. 来源结果怎样决定下一步

| 来源结果 | 下一动作 | 是否再次请求原窗口 |
| --- | --- | --- |
| 网格完整、OHLCV 合格 | 命中 scope 的载荷进入 Raw 候选；跨过的正常日期不写 | 否 |
| 空返回且身份/权限/窗口已确认正确 | 标 source-empty；粗频进入 B3a，1m 保留源缺残留 | 不机械重试；有新证据才重开 |
| 部分日期/分钟缺失 | 已返回完整部分保存；只把准确缺失部分送后续解析，满页先处理分页 | 不重新拉已成功部分 |
| 目标频率缺部分但更细频完整 | 采用固定整日派生候选时，先比较源端已有分钟与派生重叠点；一致且来源合同允许才替换该日，否则保留冲突，不逐字段混拼 | 否，已保存的重叠源记录用于比较 |
| 权限、限流、网络或结构错误 | 失败队列，最多 3 次带退避重试，之后停止该单元 | 仅失败单元 |
| 历史股票五频均缺且无其他可靠交易事实 | 明示“尚不能恢复/证明应有”，不按生命周期把 241 行造出来 | 不无限重试；不标完整 |

旧审计、源请求和写后验收的职责不同：旧审计生成范围；源响应决定可恢复事实；写后验收证明此次修改正确。执行过程中不增加“写前再全审一次”的步骤。若出现新增参考依赖缺口，只记录相关对象和日期，不扩成另一轮全库审计。

#### E. 开始、续跑和完成判据

- **开始：**管理员批准具体阶段后，B0 先输出精确 plan 与清单；B1 隔离测试通过才进入 B2/B3。Raw 的真实入口、冻结 plan/hash 和批次命令已交付于 §14.16；它不是 Silver/Gold/指标全链路 CLI。B2首批20窗口已完成，见 §14.17；B2剩余批次与B3未执行，后续仍按各阶段授权推进。
- **续跑：**同一 plan/run_id 只领取 checkpoint 中未完成单元；缓存命中不联网；已读回成功的文件不重写。失败候选和响应保留原因，不能清空目录重新开始。
- **阶段转移：**Raw 中所有可恢复单元完成并列明不可恢复残留后验收；随后依次 Silver、Gold、递推。残留需明确接受范围后才能对已闭合部分继续，不把它改成“已完整”。
- **耗时校准：**20 窗口后记录成功吞吐/失败率/平均与最长延迟，10 候选后记录文件字节/实际读写次数/耗时/RSS。若稳定源吞吐低于 60 次/分钟、剩余文件预计超过 15 小时，或必要接线预计超过 10 小时，立即更新总预算和原因；不是等超时后再补一句“可能更久”。
- **最终交付：**给出 2014+ 五频剩余缺口表、历史待确认组处置、各层实际改写文件数、总耗时、Reader/API 样本，以及未决原因。所有源与更细频都没有的数据只能明确留空，任务处理完毕和数据绝对无缺口分别表述。
- **事件边界：**物理数据恢复和只读服务验收在上述总预算内；正式事件 apply 仍单独批准。若需要事件收口，先按本次实际变化计数并沿用现行事件保留口径，在 B7 预算中校准；不能在没有事件数量时承诺全历史事件也已全部计时或完成。

<a id="minute-gap-execution-constraints"></a>

### 14.13 执行硬约束与开跑条件

本节把执行边界收口。**B0/B1 的入口、冻结清单、隔离验收和真实命令单已交付，见 §14.16；B2首批取源已完成，见 §14.17，B3正式写湖尚未执行。**下面各项必须落实为参数约束、范围过滤、测试或阶段状态检查。B4—B7 的约束继续作为其开发与执行门禁，不能把 Raw 入口完成当成下游也已接线。

#### A. 不允许执行者自行改变的边界

| 编号 | 固定约束 | 必须怎样验证 |
| --- | --- | --- |
| H01 日期与频率 | Raw 只处理 2014-01-01 至 2026-09-09，频率 1/5/15/30/60；不改变全局 Raw 历史起点 | 计划和候选都校验边界；2013 日期、截止日以后和其他 Raw 频率的反例必须拒绝 |
| H02 业务缺口 | 记录缺失或 OHLC/vol 缺失；exchange、vwap、amount 空、合法零成交量不扩大业务修复范围 | 正常 OHLCV 但 exchange 空的样本不得进入缺口队列；候选仍按现有完整合同验收 |
| H03 默认范围 | 确定缺口与历史待确认组统一规划；后者先获得有效源证据再入恢复集合 | 历史待确认不能自动算成应补，也不能省略；跨范围数量必须回到冻结 scope 对账 |
| H04 默认路线 | Tushare 跨日请求并缓存 → Lake Raw；不自行切 Prod、不启动旧 P7 全市场重建、不套用 BSE 专项计划到沪深 | 入口不得隐式调用 Prod、全市场 planner 或放宽 BSE 白名单；确需改路线先报告原因、差异与预算 |
| H05 复用证据 | 缓存命中不重复请求，已成功文件不重复恢复，不另做全湖写前审计 | 有缓存的单元网络调用数为 0；正常续跑已完成文件提升次数为 0 |
| H06 原生源优先 | 有合格原生源就用原生源；只有目标频率准确缺失才进入更细频聚合，1m 不可由粗频倒推 | 请求失败不能触发聚合；仅有“更细频候选”不能直接提升；聚合来源合同获准前不得写聚合 Raw |
| H07 原始事实 | 不插值、不以前值填充、不逐字段拼接；原生载荷与聚合结果明确区分，来源可追溯 | 源缺且无完整更细频时输出残留；聚合与原生来源标记及父输入一致 |
| H08 精确写入 | 写入集合来自 scope 或上层 actual-changed；禁止把代码列表×日期列表当精确范围 | A-D1、B-D2 的计划不能改变 A-D2/B-D1；候选中任何计划外业务键变化阻断提升 |
| H09 文件单位 | 同一文件汇总全部来源/受影响代码后提升；同一计划不按股票反复重写 | `file-plan` 目标路径唯一；同一共享 state 日期文件也只有一个最终提升单元 |
| H10 分层顺序 | Raw → Silver → Gold bars → 递推指标，上一阶段未闭合不领取下一阶段任务 | 缺阶段完成记录、存在失败或未接受的残留时，下一层必须拒绝；代码接线可先做，数据计算不可越层 |
| H11 既有口径 | canonical 映射、竞价、复权、Silver 清洗、指标公式不变；Gold30 仍首根 10:00、8 根/完整日 | 已有合同回归与首尾窗口样本；不得临时启用 Gold30 多来源或另一套指标算法 |
| H12 正式写入 | 所有候选在指定 staging，同文件系统逐文件提升，失败保留现场 | 候选路径越界拒绝；不用旧 merge 的正式目录 `.tmp`、备份、Kopia、整表清空或删除异常目录 |
| H13 下游范围 | Gold 只跟随实际 Silver 变化；递推只跟随实际 Gold 变化，并传播到截止日 | 等价上游不产生下游重建；新增未分类的真实消费者应报错，不能默默漏掉或全市场兜底 |
| H14 资源预算 | 保持 §14.9 的在途请求、批次、内存和超时上限 | 超限可以降速、缩批或中止；不得为赶预计工期自行加并发、增配额或放宽质量门禁 |
| H15 改动范围 | 只做本数据集必要编排、候选接线及对应测试；不改 API/页面/日常调度/生产数据库，不做信号研究 | 开发前列实际文件白名单；发现需要额外合同/基础设施改造先报告，保留其他任务脏文件 |
| H16 真实完成 | 处理成功、源缺、失败、未决、物理文件状态和事件状态分别表达 | 非零未决或失败不得写“全部补齐”；未执行的步骤不得标绿，执行日志不得替代文件验收 |

#### B. 每次正式动作所需的命令单

B0/B1 完成后，将下面内容写入同一 run 的执行清单，并在本节关联实际路径；它是实施交付物，不是另一轮全湖审计：

1. 真实存在的入口与精确命令，工作目录、解释器、plan 路径及 hash、run_id、动作名称、批次范围；命令必须与入口的参数校验测试一致，不用未实现的参数或占位命令执行。
2. 本动作显式输入文件、候选输出根、允许提升的正式目标路径、数量和预计行数；动态新发现必须更新同一范围内的 revision，不能顺带扩大日期/数据集。
3. 该动作是否访问 Tushare、Lake 或 Dagster instance，是否写候选/正式文件/事件，以及它所对应的已有阶段授权。物理恢复执行器不隐式创建 Dagster instance 或写事件。
4. 对应隔离测试结果和 H01—H16 对账；涉及哪个约束就附对应测试或静态范围检查，不以“全部测试通过”代替真实场景。
5. 首批数量、继续批次大小、预计耗时、失败后使用的同一 run_id 续跑命令，以及阶段退出条件。

正式写入前缺任一项，停止该动作并补齐已授权的准备工作，不凭经验补默认参数。已经批准的同一阶段、同一冻结范围内续批不反复询问；只有超出授权范围、改动合同或需要接受新的残留范围时，才提交具体差异供确认。

#### C. 允许调整与必须停止

允许在同一计划内做的调整：减少在途请求、缩小批次、按明确分页规则拆窗口、重试失败单元、根据样本更新 ETA；这些调整不得增加正常数据写入范围，已成功单元继续复用。

必须停止受影响动作的情况：同一源代码无法唯一归属业务身份、返回超范围、原生/聚合重叠量价冲突、候选有计划外变化、正式检查失败、必要参考事实缺失、递推前状态不可靠、内存/磁盘越界，或实际实现要求改变既有业务合同。多个源别名指向同一最新身份不等于身份冲突，按 §14.15 查源；禁止以逆向不唯一要求管理员猜请求代码。停止时报告准确对象/日期/频率和原因；其他同阶段独立单元可按既有授权继续，不重启全量审计、不切到另一来源规避问题。上一阶段未完成时，下游仍不得启动。

若 H01—H16 与前文“建议、优先、可以评估”的措辞产生歧义，以本节固定约束为本次计划的执行口径；用户后续明确指令优先，并同步修改本节与受影响工作包，不能只在会话中改变方案。

<a id="minute-gap-b0-identity-stop"></a>

### 14.14 B0 实际停点：历史请求代码存在多个候选（2026-09-10）

> 本节保留当时停点记录。后续管理员要求先实查再形成结论，MCP 结果及当前口径见 §14.15；下述“待确认”不再表示需要管理员决定请求代码。

管理员批准推进 B0/B1 后，先复用原审计缓存核验身份。发现 §14.12 “按身份有效期确定唯一源代码”的假设不成立：当前 identity_map 支持多个旧/新源代码归一到一个最新代码，自映射与别名映射的有效期可以重叠。`stock_identity_map.py` 要求 `source_ts_code` 唯一，并不要求逆向唯一；Silver 按源代码正向联接，使用 `[valid_from, valid_to)`。因此这是本方案对请求路由能力的误判，不能据此认定身份表、原审计或采集代码有 bug。

| 范围 | 唯一候选单元 | 两个候选单元 | 多候选涉及股票日 | 多候选股票 |
| --- | ---: | ---: | ---: | ---: |
| 确定缺口 | 30,325 | 35,248 | 19,335 | 249 |
| 历史待确认 | 2,238,510 | 75,775 | 15,155 | 69 |

单元为频率×股票×日期；跨组共 250 只多候选股票，没有零候选。例：001872.SZ 在 2014-01-02 同时匹配 000022.SZ 与 001872.SZ，两条有效期均从 1993-05-05 开始且无结束日。920305.BJ 同样存在 835305.BJ 与自映射两个候选。原审计先正向归一再检查缺口，故这次路由歧义不改变 65,573 个已确认缺口的结论。

**实际交付：**`/private/tmp/dg_raw_mins_b0_identity_20260910/` 下保存 `scope-draft.parquet`（全部 2,379,858 单元）、`identity-blockers.parquet`（111,023 单元）、`identity-blockers-by-stock.csv`、`summary.json` 和 `report.md`。草稿不等于可执行冻结计划；未生成 source-windows 或正式操作命令。141 个盘中停牌待复核股票日保留原分类，没有混入生命周期待确认组。审计输入版本、范围和数量已保存，继续时复用这些工件。

**验证与成本：**输入仅三个原缓存，共 589,825 字节；本次工件生成计算实测 3.181 秒，进程峰值 RSS 约 1.34GiB（DuckDB 1GiB、2 线程、禁 spill）。业务键唯一、频率/日期边界通过，草稿 2,379,858 行读回一致。未再次读取 Raw，未新增源请求，未写正式 Lake/数据库/事件。CodeGraph 已核对身份构建入口、调用链和既有测试消费者；没有改动业务代码或依赖矩阵，未运行 B1 隔离测试。

**待确认的修正建议：**scope 保存有界候选代码集合及响应确认后的实际源代码；优先复用已有有效载荷，对多候选做少量新旧代码源样本后确定请求顺序。目标日空或不完整才尝试另一候选，失败不当作源缺；已有成功载荷不重取，重叠结果冲突则停止，Raw 保留实际返回代码。不改全局 identity_map/Silver 合同，不扩大缺口范围。确认后同步改 §14.12 的 scope/window 路由与 B1 对应反例测试，再继续 B0/B1。

此次暂停依据 §14.13 C“源身份存在歧义”及管理员允许遇到预估差异停下讨论的指令。原约 45,495 个窗口尚未考虑候选路由，仍是估算，不能作为冻结数量或承诺总耗时；修正后直接从现有草稿测算增加的窗口与耗时，不重启全湖审计。B0 尚未完成、B1 尚未开始，B2 及后续阶段均未执行。

<a id="minute-gap-identity-source-verification"></a>

### 14.15 新身份与源请求代码：当前实现及 MCP 实查（2026-09-10）

管理员明确新旧行情统一到新身份、新代码，并要求技术请求代码先通过 MCP 查实，不在证据不足时让管理员拍板。当前代码的分层事实是：Raw 保留来源的 `ts_code`；Silver 将源代码经 identity_map 正向归一为 `latest_ts_code`，作为输出 `ts_code`；Gold 沿用 Silver 新身份。业务统一已在 Silver 层实施，不能据此声称 Raw 每行都只使用新代码。

正式文件定点核验：2023-02-17 的 30min，Raw 中 `430047.BJ` 为 9 行，Silver 中 `920047.BJ` 为 9 行，Gold 中 `920047.BJ` 为 8 行，旧代码 Gold 年文件不存在。复用原审计紧凑缓存，仅查询代码/日期/频率/聚合行数，发现 2014+ 共 193 个旧来源代码、3,334,608 行，分布于 1/5/15/30min；缓存计算 0.886 秒，没有重扫 Raw。这个统计是原审计快照，正式定点读回与之相符；未全扫 Silver/Gold，不宣称全湖身份质量已完整验收。

Tushare MCP 共 24 次请求，均为单代码单日 09:00—19:00，显式请求 ts_code、trade_time、OHLC、vol、amount、freq、exchange、vwap。返回至多 241 行，没有触及 8000 行分页上限。

| 新代码 / 旧代码 | 日期 | 频率 | 新代码返回行数 | 旧代码返回行数 |
| --- | --- | --- | --- | --- |
| 001872.SZ / 000022.SZ | 2014-01-02 | 1/5/15/30/60 | 0/0/0/0/0 | 241/49/17/9/5 |
| 001872.SZ / 000022.SZ | 2026-02-26 | 30 | 9 | 0 |
| 920305.BJ / 835305.BJ | 2022-01-04 | 1/5/15/30/60 | 0/55/19/10/6 | 0/55/19/10/6 |
| 920305.BJ / 835305.BJ | 2026-02-26 | 1 | 241 | 0 |

返回身份、日期、freq 吻合，无重复时间，OHLC/vol 无 NULL 或非有限值；非空样本常规网格均完整。北交所 2022 样本粗频含盘后行（5/15/30/60min 分别 6/2/1/1 行），新旧代码的时间点、OHLC、vol、amount 逐行相同；1min 两边为空，不能当作完整数据相等。exchange 空仍不算本次业务缺口。

因此不再假设“历史只请求旧码”或“统一身份就只请求新码”。B0 的 scope 以最新代码/频率/日期唯一标识，保留有效来源候选；有效缓存优先，没有载荷时新代码为确定性首选，仅对仍为空/不完整的目标日期尝试历史别名，错误不当作源缺。有完整载荷不再请求另一代码；已经获取的重叠载荷若冲突则停止，不拼混、不双计。请求用旧代码不改变该单元的新业务身份。Raw 当前来源代码合同与 Silver/Gold 新身份合同保持明确区分，本轮没有执行 Raw 换码或正式数据修改。

MCP 全载荷保存在 `/private/tmp/dg_mins_identity_mcp_20260910.json`，验证汇总为同目录 `dg_mins_identity_mcp_summary_20260910.json`，正式样本为 `dg_mins_identity_physical_20260910.json`，人话说明为 `dg_mins_identity_findings_20260910.md`。成功和空响应都复用，不另做同批源可用性重审。样本证明请求差异确实存在，不替代其余目标的真实响应验证；当次核验时 B0/B1 尚未完成，未将其写成批量入口测试或补数成功。后续 B0/B1 交付见 §14.16。


<a id="minute-gap-b0-b1-delivery"></a>

### 14.16 B0/B1 交付：冻结清单、Raw 入口和隔离验收（2026-09-10）

**业务口径已确认：Raw 可以保留真实来源代码；Silver 起，新旧历史统一使用最新身份和新代码。**本次完成 B0/B1，无需管理员再次决定请求代码。正式 Raw/Silver/Gold、数据库、Dagster instance/事件均未写入；恢复期间的物理测试全部在 `/private/tmp` 隔离目录。正式 staging 执行目录尚未创建。

#### 冻结结果与使用入口

唯一可执行冻结计划目录：`/private/tmp/dg_stk_mins_gap_recovery_20260910_frozen`。

- plan：`plan.json`；hash：`7b829c76c3bf54df5276124aa46f3033d9660492ebc8d939ca2e8a26b74ac30b`。
- 业务范围：`scope.parquet`，2,379,858 单元 = 65,573 确定缺口 + 2,314,285 历史待确认频率股票日。后者仍不是已证明应有的行情。
- 请求：`source-windows.parquet`，45,432 个窗口组，含 8,575 个带有效别名的窗口组。原生主请求估计行数上限 175,294,944；别名仅按实际仍缺范围追加，不预先把所有请求翻倍。
- 文件：`file-plan.parquet`，15,014 个唯一 Raw 目标，既有文件合计 72,620,207,858 字节（约 67.63GiB）。这是包含待确认组的范围，不能与“只确定组”的 14,883 文件混用。
- 精确首批和命令：`first-source-batch.json`、`commands.md`；结果汇总：`preparation-results.json`。每条命令均经真实 CLI 参数解析验证，状态命令已执行，输出无源请求/正式文件 checkpoint。
- 前期 `..._plan`、`..._plan_v2` 仅为开发过程工件，不是当前执行计划。继续工作只使用上述 `_frozen` 目录，不能清空后重跑全湖审计。

| 频率 | 窗口组 | Raw 目标文件 |
| --- | ---: | ---: |
| 1m | 26,123 | 3,003 |
| 5m | 6,452 | 3,003 |
| 15m | 4,378 | 3,002 |
| 30m | 4,653 | 3,003 |
| 60m | 3,826 | 3,003 |

最终冻结过程实测 **6.91 秒、峰值 RSS 约 2.31GiB**。输入来自已有草稿/参考/文件库存及保存的源响应，未读取 Raw 行情文件。该数字是 B0 规划计算耗时，不是 B1 开发工时或全量恢复耗时。

#### 已实现的边界

入口动作仅为 `freeze / status / import-cache / fetch / build-raw / promote-raw`，没有 Silver、Gold、递推、Prod 或事件执行动作。源请求复用 `TushareResource` 和 `_normalize_tushare_stk_mins_row`；业务身份一直用 latest_ts_code，返回源代码原样保存。每页保存参数、offset/limit、载荷和校验信息，满页继续分页；请求失败不转源缺、不进入别名或聚合分支。已保存成功页、已完成窗口、已导入样本不重复取源或归一化。

Raw 按目标文件一次汇总全部成员；目前只允许所有成员均为 `source-ready` 的文件进入候选，源空/部分/失败和未处理残留不会被默默跳过。条件聚合、残留接受以及后续分层关闭仍按 B3a/后续阶段处理，不冒充已实现。候选只按精确代码/日期关系读取响应，跨过的正常日期不写；该冻结范围全部是整日无行，若某个候选来源代码在目标中已经有行则停止，防止错用本计划覆盖其他数据。

候选使用 DuckDB 列式合并，读取目标一次，正式 Raw schema/空值/负值/业务键与分区合同在同一连接内核验；序列化后校验行数及关系摘要。候选在 staging 生成，提升前记录 checkpoint，同文件系统 `os.replace()` 后读回文件身份和 Parquet footer。对“replace 已完成但 checkpoint 未写完”的中断可续跑，已完成文件不再次提升；没有正式目录 `.tmp`、备份或 Kopia。`actual-changed-raw.parquet` 仅汇总实际已提升文件的变化，并保留新身份、源代码、时间和来源。

CodeGraph 已核对 Raw normalizer 的入口/调用影响及 canonical 消费链；此次只新增四个离线模块和一个测试文件，未改共享业务合同、依赖矩阵、API、页面、日常任务或 sensor。既有脏文件未纳入本次修改。

#### 配置与性能约束的实际落点

本次没有新增 env 配置体系。批次配置全部在 `plan.json.budget` 冻结，CLI 和执行器校验版本/合同/预算；当前入口拒绝未评审预算变化。只允许 `--limit` 在下述冻结上限内缩批/续批，无动态增大并发。

| 配置/规则 | 默认与持久化 | 消费者、生效方式与验证 |
| --- | --- | --- |
| 日期/五频、源字段、Raw schema、根目录 | plan.json，2014-01-01—2026-09-09；1/5/15/30/60 | freeze/RecoveryRun/target；hash 与边界反例 |
| 窗口交易日上限/桥接/每日行余量 | budget：20/100/240/240/240；桥接5日；271/55/19/10/6 | freeze；每组估计不足6000行，scope完整成员校验 |
| 页/页数/重试/速率 | 8000行、异常最多4页、最多3次、最高180次/分钟；实现单请求在途 | SourceCache；分页、中断、失败重试、缓存零调用测试；SDK现有HTTP超时30秒 |
| 源批/文件批 | 最多200窗口组；最多20文件，首批分别20组/10文件 | CLI/selected_files；越界拒绝，按文件状态续跑 |
| 内存/线程/spill/时间 | 2GB/2线程/禁止spill、RSS4GiB、单连接操作300秒 | 共享 DuckDB connector、RSS guard、interrupt timer；隔离验证与越界预算拒绝 |
| 候选字节/磁盘 | 批次候选上限2GiB；启动可用空间至少200GiB | 候选与CLI累计检查、正式执行根初始化前检查；超限保留现场并停止 |
| TUSHARE_TOKEN | 沿用既有执行环境注入，不保存到plan、缓存或日志 | 仅fetch构造既有TushareResource；缺失在执行初始化前报错，隔离反例验证 |

#### 验收与下一阶段

新增 **30 项 pytest 测试通过**，其中隔离调用了 **3 项既有 Raw 回归**；覆盖 H01—H09、H12、H14—H16 在 B0/B1 的适用部分：日期/频率越界、重复/错身份 scope、缓存命中零网络、旧码归属新身份、完整窗口成员、错代码/频率/日期、重复源键、空/部分/失败区分、满页分页、取消续跑、已知别名载荷冲突、文件成员不齐阻断、精确 A-D1/B-D2、不改正常行、候选合同失败、提升中断恢复和幂等重放。H10/H11/H13 的下游实现未进入本轮，当前以无下游命令和不改既有公式/消费者保证边界；后续工作包仍须独立验收。

另用已保存 MCP 载荷在隔离目录构造六个缺口场景，涵盖 1/5/30min、跨日、旧码取源；成功写入 **638 条修复行到隔离文件**，六个候选完成提升、footer读回与幂等重放，网络调用0、正式文件读写0。六个场景是测试夹具，不是新增正式缺口；其中早期600395/002690探针只作为验证材料。证据为 `/private/tmp/dg_stk_mins_gap_offline_acceptance_20260910_v2/result.json`，源样本索引含29个代码/频率/日期事实。不能把该隔离结果称为正式补数完成，也不能拿小文件时间外推全市场吞吐。

静态检查：orchestrator 全域致命错误 Ruff 基线与本次文件默认 Ruff 均通过；原设计文档同步，文档完整性与 diff 空白检查通过。无提交、部署或安装。

下一步是 **B2 的20窗口组真实取源校准**，使用 commands.md 的精确计划、hash 和窗口列表；源缓存命中跳过。通过样本后同一队列每批200组续跑，B3 再按来源已齐备的文件生成和提升候选。B2/B3 不在本轮执行记录中；整体剩余 ETA 要用首次真实批次的有效吞吐与别名追加量更新，不能把本轮通过隔离测试当作已测得全量源速度。


<a id="minute-gap-b2-first20"></a>

### 14.17 B2 首批20窗口：取源结果与耗时（2026-09-10）

**首批已完成，源端缺失按正常结果留存；没有启动合成、其他来源恢复或正式写湖。**本轮执行原冻结清单的 `import-cache` 和精确20窗口 `fetch --limit 20`，计划hash不变；没有领取第21个窗口。B2整体仍待剩余批次完成，不能把本节理解为全量取源结束。

#### 结果

20窗口覆盖2,755个“股票×日期×频率”单元。实际新增25次HTTP请求（5次旧码追加），返回53,175行；另复用目标范围内既有缓存321行，形成53,496行可供后续原生恢复的数据。已导入26份已有响应，后续不重取这些成功页。先前原12股票日只有会话证据、没有完整保存的载荷，本批通过3个跨日窗口取得其可复用载荷，并未再另发12个单日探针。

| 范围 | 源数据完整 | 源返回空 | 部分/请求失败 |
| --- | ---: | ---: | ---: |
| 已确认本地缺口 | 1,032 | 3 | 0 |
| 历史待确认单元 | 880 | 840 | 0 |
| 合计 | **1,912** | **843** | **0** |

这里的“源数据完整”对应当前取源阶段的业务字段和分钟网格门禁，不等于Raw候选或下游正式合同验收通过。未把exchange等辅助列缺失计入业务缺口。840个历史待确认空单元仍不代表已证明本来应有行情，更不能据此宣称缺口已经解决。

- **002228.SZ、300999.SZ、601877.SH**：本批各65个5分钟股票日全部返回完整，共195个；原12个股票日均每股票日49行。
- **001872.SZ**：2014年历史通过真实来源代码000022.SZ取得，837个单元完整，3个为空。业务身份仍为001872.SZ。
- **000005.SZ**：本批五频840个单元完整；**000018.SZ、000023.SZ**：本批1分钟各20个单元完整。
- **832317.BJ**：本批五频840个历史待确认单元为空。1分钟窗口为2020-07-27—2020-08-21，5分钟至2020-12-21，15/30/60分钟至2021-07-20；各频覆盖不同，不能说整个年度所有频率都已查过。本轮只记录，没有扩大代码候选或另寻来源。

3个确认缺口的源空结果，以及同一批已取得的较细周期：

| 最新业务代码 | 日期 | 源空频率 | 同批已有完整较细频率 |
| --- | --- | --- | --- |
| 001872.SZ | 2014-02-11 | 60m | 5m、15m、30m |
| 001872.SZ | 2014-10-08 | 60m | 15m、30m |
| 001872.SZ | 2014-09-03 | 30m | 15m |

这些是后续评估聚合的材料，**本轮未聚合，也未额外请求这些日期的1分钟**。按管理员提醒，源端不齐不属于异常事故；以后是否需要其他来源，依据后续已取到的证据处理。

#### 性能与剩余时间

- 首批进程端到端 **19.54秒**，含CLI启动、25次请求、响应缓存、归一化、分钟网格检查、窗口状态与汇总索引写入；不含此前资料核对与缓存导入。
- 有效吞吐约 **61.4窗口组/分钟、76.8实际请求/分钟**。单窗口处理耗时中位数0.77秒、最大2.56秒；这是含本地处理的窗口耗时，未单独测量纯HTTP延迟。
- 25次响应中10次为空（5次新码历史请求空、5次北交所窗口空）；错误和重试均0。最大单页4,900行，全部未满8,000行，本批未触发分页；分页中断/续跑仍只有B1隔离证据，不冒充本批真实验证。
- 峰值RSS约 **348MiB**；staging约 **24.0MiB**，启动可用磁盘约2,781.6GiB。未触发资源或持续错误停点。
- 剩余45,412窗口按本批端到端吞吐线性外推，**仅余下取源约12.3小时**。样本只有20窗口且含空返回、别名追加，尚不是长期稳定速率，不能用此承诺全量耗时。后续每200窗口使用同一缓存与完成状态更新ETA。
- §14.9完整任务18—42小时仍是原工程预算，不能凭本批19.54秒缩短为几小时完成；B3文件样本和B4—B6接线未完成，整体剩余时间尚不能用实测取代。条件聚合、外部等待仍单列，当前未发生这些工作。

#### 工件、边界与下一步

源响应、页面、请求、窗口状态和汇总Parquet位于原计划执行根 `/Volumes/datasource/data_lake_staging/stk_mins_gap_recovery/run_id=20260910-v1`。只读状态确认 `windows.complete=20`、`files={}`，下游未执行。所有843个空单元保留在resolutions中，窗口complete只表示查源处理完成，不表示其行情全部齐备。

冻结目录 `/private/tmp/dg_stk_mins_gap_recovery_20260910_frozen` 新增 `b2-first20-events.jsonl`、`b2-first20-process.json`、`b2-first20-results.json`；其中保存逐窗口结果、3个源空具体日期、原12日结果、请求量与耗时。临时启动脚本 `/private/tmp/dg_stk_mins_b2_first20_run.py` 仅从命令单提取原20窗口命令并记录进程输出，没有绕过正式CLI。该脚本是本次执行证据，不是新运行入口。

**本轮没有改Python实现、配置、身份映射或依赖边界，没有读取或修改正式Raw/Silver/Gold行情文件，没有数据库、Dagster instance或事件操作，没有提交、部署或安装。**仅同步本LLD、资产设计入口及命令单的阶段状态。后续按原计划继续B2，每批最多200窗口；本次授权仅首批20个，故未继续领取。源端缺失不重试成“齐备”，后续B3a的条件聚合仍单独按阶段处理。


<a id="minute-gap-b2-cost-explanation"></a>

### 14.18 B2耗时解释与优化建议（2026-09-10，只读核对）

**12.3小时是当前串行程序跑完全部剩余查源范围的短样本线性外推，不是Tushare的固有下限，也不是已确认缺口本身需要这么久。**计算为45,412剩余窗口 ×（19.5407秒 ÷ 20窗口）÷ 3,600。首批只有20窗口，未拆测纯HTTP与本地处理时间，因此不能称为稳定吞吐或承诺工期。

复用冻结scope按window_id聚合，本次没有重扫Raw或再取源：

| 窗口分类 | 窗口数 |
| --- | ---: |
| 只有已确认缺口 | 8,142 |
| 同时包含确认缺口与历史待确认单元 | 67 |
| 只有历史待确认单元 | 37,223 |
| 合计 | 45,432 |

含已确认缺口共8,209窗口；约82%的窗口只用于核实历史待确认记录。这些记录是生命周期有效但缺少日线/分钟交易证据的候选，不能直接算已确认漏采。若仅用于解释耗时，8,209窗口按首批平均速度约2.23小时；这不改变默认完整范围，也不是建议先写一次Raw、以后再为历史组重写一遍。

当前代码可定位的改进点：

1. `stk_mins_gap_recovery_source.py` 的请求与 `write_page/day_facts/save_resolution` 串行执行；限速下一时点从响应返回后计算，存在网络等待与本地处理重叠、按请求发起时刻统一限速的优化空间。可以评估原方案允许的最多2个请求在途，所有请求仍共用180次/分钟上限，缓存与状态由单一写入方管理；不能仅凭并发数承诺速度翻倍。
2. `stk_mins_gap_recovery_cli.py` 每个窗口新建连接并单独读取scope；可评估每批200窗口一次读取成员，仍逐窗口/逐页保存结果，不把完成状态推迟到整批结束。现有Parquet可能通过行组裁剪减少扫描，不能把这段代码直接说成每次全量扫描2,379,858行。
3. 冻结窗口按估计低于6,000行设计，而API上限8,000行；较大窗口可能减少请求，尤其当前1分钟占26,123窗口。但这需要单独评估源量余量、分页、已缓存范围和plan revision，优先级低于保持冻结范围不变的执行优化；本轮不改窗口或预算。

建议先评估并落地前两项，再用**后续尚未取过的200窗口**校准收益。已有20窗口、页面与空结果直接沿用，不重新请求、不重新全湖审计。当前未修改Python代码或冻结plan，也未执行这200窗口；优化后ETA尚无实测，不另给无证据的短工期。

**832317.BJ的840单元含义：**既有生命周期缓存名称为“观典防务(退)”，list_date=2020-07-27，delist_date=2022-04-26。原审计代码按生命周期与交易日生成候选，再分别检查本地日线、分钟及停牌证据；这些记录被标为 `lifecycle_only_unconfirmed`，不是由实际交易记录证明应有。冻结范围为2020-07-27—2021-10-20的299日期×5频率，共1,495单元。本批只检查其中840个：1m20日 + 5m100日 + 15m240日 + 30m240日 + 60m240日，合计覆盖240个不同日期；尚余655单元未查。本批实际只发出5个跨日请求，全部返回空，不是840次请求。

这些空结果只证明本次按该代码、频率、窗口未取到行情，尚不能区分原本没有交易、历史身份/市场覆盖或源接口历史数据缺失。本轮不追加取源，不修改身份映射，不把840个空单元算成确认漏采，也不据此跳过其他尚未查过的日期和频率。


<a id="minute-gap-source-execution-optimization"></a>

### 14.19 取源执行优化实施方案（2026-09-10，已实现并通过隔离验收）

管理员批准先更新方案再实现 §14.18 前两项。本节先于代码修改落盘；本轮交付代码与隔离验证，不追加Tushare请求，不运行后续200窗口，不改正式Lake或事件。日期、频率、对象、请求窗口、源字段、分页、别名选择和业务验收全部沿用冻结plan。

#### 两项改动及配置审计

1. **两个请求与本地处理重叠。**新增 `stk_mins_gap_recovery_fetch.py` 承载有界调度。最多激活两个窗口，每窗口依旧顺序请求页和候选代码；工作线程只调用既有TushareResource，不接触DuckDB、页面文件或checkpoint。主线程恢复窗口执行步骤，完成校验、缓存和状态写入。同批完成顺序可不同，业务结果与原算法相同。
2. **每批只读一次scope。**同模块选取最多200个尚未完成的窗口，用一次明确列投影的SQL读取它们全部成员并按window_id分组；每个窗口核对完整成员和身份后才派发。正常运行不再逐窗口重读scope，不把全局所有scope长期留在内存。显式窗口ID仍只处理指定集合，未知/重复ID拒绝，完成窗口跳过。

| 配置 | 来源与生效 | 消费者/边界 |
| --- | --- | --- |
| SOURCE_MAX_IN_FLIGHT=2 | fetch模块唯一代码常量，固定执行上限，无新增env、CLI开关或可编辑配置；执行进度打印该值 | 调度器最多保留两个在途或待消费响应；不是两个写入进程 |
| requests_per_minute=180 | 继续读取冻结plan.budget | 全部线程、分页和重试共享同一发起时刻限速器，最小间隔60/180秒；响应处理时间不再额外叠加到限速起点 |
| source_batch≤200 | 冻结plan与现有--limit | 批成员最多200×240=48,000条；原页面8,000行/最多4页、最多3次重试、4GiB RSS、2GB DuckDB/2线程/禁spill均不变 |

不修改已有plan/hash或run.json；SOURCE_MAX_IN_FLIGHT是本次获准的执行方式，不改变其数据身份和预算项。旧缓存键、页面/请求/窗口checkpoint结构均继续使用现行合同，不新增另一套兼容读取或复制缓存。进度记录并发上限、窗口完成量及请求/响应耗时，供下一次获准真实批次校准ETA。

#### 取消、失败与续跑

- 取消后不领取新窗口、不发后续页或别名；已经在途的最多两个请求等待现有SDK超时/返回。成功响应由主线程先落页缓存再退出，下次复用，不因取消丢掉返回值。
- 一个窗口出错则停止新增派发，排空其他已在途响应并保存成功页，保留首个错误；请求失败不改为源空，不触发别名/聚合。错误次数沿用既有记录，不能靠重启恢复重试额度。
- 每页、每窗口完成即保存；不等整批完成才写业务状态。未启动窗口不产生假失败或完成记录。
- 网络调用可重叠，SQL、Parquet和JSON/checkpoint由同一个主线程写；恢复算法只有一个实现，单窗口公开方法与批量入口共用相同执行步骤。

#### 改动范围与硬约束验收

CodeGraph explore/impact已核对SourceCache、resolve_window/request及CLI、测试调用方；TushareResource每次call构造独立客户端，无共享可变session，不修改该公共resource。影响限于分钟恢复离线入口；Raw候选、Silver/Gold、日常资产、sensor、前端/API无调用迁移。

| 硬约束 | 代码落点 | 验收 |
| --- | --- | --- |
| 恰当重叠、最多2个请求 | fetch调度器与SourceCache页面执行步骤 | 延迟替身确认峰值在途=2、无第三个；处理A响应时B仍可在途 |
| 全局发起时刻限速 | fetch共享限速器 | 两个线程和失败重试共同遵守180/min，慢响应不再额外等待一整个间隔 |
| 单一写入方 | fetch主线程推进生成器；source原写页/解析/状态方法 | 记录所有DB/写页/checkpoint线程，必须全部为主线程 |
| 每批只读一次scope | fetch批选择与成员装载；CLI接线 | 200窗口只出现一次scope读取、最多48,000成员；错ID、重复ID、缺成员拒绝 |
| 不重取、不改语义 | 原缓存/分页/别名步骤 | 原30项回归；并发旧码/空/部分/满页、完成窗口与已缓存页重放零调用 |
| 取消和失败排空 | 调度器停止派发、源页先存后退出 | 两请求在途取消/失败，成功页保留、第三窗口不启动；续跑不重取保存页 |
| 范围与业务结果相同 | 单窗口与批量共用步骤 | 同一隔离样本分别顺序/批量运行，精确参数及归一结果、身份、状态一致 |
| 性能证据不冒充源速度 | 隔离延迟替身、缓存清单只读测量 | 保存延迟场景对比与查询次数；不能用模拟加速倍数直接承诺真实ETA |

后续200窗口真实取源及其工期校准仍不属于本轮执行；没有必要重新审计源数据或重跑已完成20窗口。实施结果如下。


#### 实施结果与计划对账

本节方案先落盘，再按两项授权实施：新增 `stk_mins_gap_recovery_fetch.py`，修改 `stk_mins_gap_recovery_source.py` 和 `stk_mins_gap_recovery_cli.py`；新增 `tests/test_stk_mins_gap_recovery_fetch.py`，原测试的时钟替身改为可推进虚拟时间，业务断言不变。没有修改共享resource、Raw候选算法、数据字段或派生层。§14.16记载的串行方式是首次交付时的历史状态，后续fetch以本节的两个在途请求及单写入方实现为准。

- **42项测试通过**（原30项加本轮12项；其中保留3项既有Raw回归），总计8.87秒。覆盖两个在途上限、请求/本地处理重叠、全局发起间隔、重试限速、等待时取消、两个响应排空保存、失败阻断第三窗口、重复批次拒绝、缓存及完成状态复用、200窗口一次scope读取、成员缺失拒绝、顺序/并发参数与业务结果一致，以及真实CLI的隔离续批接线。没有用正式token或Lake作为测试夹具。
- **隔离延迟场景：**每个模拟请求固定等待0.65秒、3窗口，同一套处理算法顺序执行2.086秒、并发执行1.387秒，耗时减少约33%。这是人工延迟替身结果，不用于直接把真实12.3小时乘以0.67。
- **真实冻结清单只读测量：**选取后续200个未完成窗口、3,903个成员，scope只读取一次，选择和装载共0.470秒，进程RSS约251MiB；plan/hash核验另耗0.026秒。只读现有规划文件和完成状态，未请求源端、未读取正式行情、未写staging。该选择没有将窗口标为运行或完成，下一次fetch仍会按同一清单正常选取。
- 全域致命错误Ruff与本次文件默认Ruff通过；CodeGraph sync/status确认索引最新，影响仍限于分钟恢复离线入口。文档和命令单同步执行规则，不改冻结plan/hash及已有源缓存。

证据：`/private/tmp/dg_stk_mins_fetch_optimization_tests_20260910.log`（测试及延迟结果）、`/private/tmp/dg_stk_mins_fetch_optimization_batch_20260910.json`（真实清单读取次数/规模/耗时），以及同目录 `dg_stk_mins_fetch_optimization_results_20260910.json`。本轮网络请求、正式Lake数据读写、staging运行写入、数据库及Dagster事件操作均为0；无提交、部署、依赖安装。尚未执行后续200窗口，真实源速度及整体ETA待下一次获准取源时更新。


<a id="minute-gap-b2-next200"></a>

### 14.20 B2优化后新增200窗口：真实取源结果（2026-09-10）

**按管理员本轮授权，仅继续200个新窗口，现已完成。**执行代码为提交 `82c854ca`，命令为原 `fetch --limit 200 --apply`，plan/hash、日期范围、字段和源候选不变。已有20窗口状态保持原样，没有重新取源；本批结束即停止，未开始下一个200窗口，也未执行Raw候选或正式提升。

#### 源结果

本批覆盖200只股票的200个1分钟窗口，目标日期范围为2014-01-02—2014-02-19，共3,903个股票日频率单元。按原队列的频率/起始日/代码顺序选择，不是重新挑出的跨频性能样本。

| 本批分类 | 源数据完整 | 源返回空 | 部分/请求失败 |
| --- | ---: | ---: | ---: |
| 已确认本地缺口 | 80 | 20 | 0 |
| 历史待确认 | 3,803 | 0 | 0 |
| 合计 | **3,883** | **20** | **0** |

实际201次请求、201页响应：其中1次为旧码追加。001914.SZ的历史通过000043.SZ取得，业务身份与来源代码仍分别保存。共返回939,177行，当前目标范围内完整数据935,803行；另外3,374行属于跨日请求返回但不在本批恢复scope内的记录，只保存在响应缓存，不能扩大正式写入范围。

20个源空单元全部为 **601360.SH，2014-01-02—2014-01-29的20个交易日，1分钟**。这里只记录按冻结候选未取得数据，不推断根因；本轮没有追加其他代码/来源请求，也没有聚合处理。两份空响应分别属于新码历史空响应和该601360.SH窗口。已确认范围的空结果仍保留，不能把窗口complete说成数据已齐备。

累计完成220窗口，6,658目标单元中5,795个源数据完整、863个源返回空；正式Raw恢复尚未开始。这些是取源分类，仍不是正式文件或下游验收通过。

#### 真实性能与ETA更新

| 指标 | 本批实测 |
| --- | ---: |
| 端到端进程耗时，含缓存/校验/状态和汇总 | **79.538秒** |
| 有效窗口吞吐 | **150.9窗口/分钟** |
| 实际请求吞吐 | **151.6请求/分钟** |
| 在途请求峰值 | **2** |
| 请求失败/重试 | **0 / 0** |
| provider调用耗时中位数 / P95 / 最大 | **0.483 / 0.819 / 2.499秒** |
| 最大单页 | **4,820行**，未触发满页分页 |
| 进程峰值RSS | **约368MiB** |
| 新响应缓存文件量（原始/归一JSON及Parquet） | **约370.6MiB** |

余下45,212窗口按本批速度线性外推，**仅剩余取源约5.0小时**，替换此前12.3小时作为当前取源估计。首批混合频率、别名占比高，本批则全部为2014年1分钟窗口，不能把两个样本吞吐差全部归因于代码优化，也不能承诺后续一直保持此速度。后续仍每200窗口更新ETA，不重复成功请求。Raw/Silver/Gold和指标处理不包含在5小时内，整体完成时间继续等文件样本与实际残留规模校准。

#### 证据与边界

原冻结目录新增 `b2-next200-before.json`、`b2-next200-events.jsonl`、`b2-next200-process.json`、`b2-next200-results.json`，记录原20窗口状态、全部请求/响应与窗口进度、逐窗口结果、20个空单元日期和耗时。源响应与checkpoint继续保存在原staging执行根，没有复制到另一套事实源。临时启动和汇总脚本位于 `/private/tmp/dg_stk_mins_b2_next200_run.py`、`/private/tmp/dg_stk_mins_b2_next200_summarize.py`，前者仅调用已批准CLI，后者读取本批缓存状态汇总，不重新校验行情或请求Tushare。

本轮只执行取源及staging保存，未读取或写入正式Raw/Silver/Gold行情、未操作数据库或Dagster instance/事件、未改Python实现。旧20窗口状态完全未变，正式文件checkpoint仍为0。仅更新两份既有设计文档与命令单记录；没有部署、安装或提交。下一步仍为B2余下窗口的分批取源，本次200个授权已经完成。

<a id="minute-gap-b2-halfhour"></a>

### 14.21 B2按约半小时停点续批（2026-09-10）

管理员批准继续B2，并要求每约半小时停下汇报。本轮从220个已完成窗口继续，每批仍为原命令 `fetch --limit 200 --apply`，最多两个源请求在途；临近半小时时不再领取下一批，异常失败或整批请求吞吐低于60次/分钟提前停止。临时编排仅重复调用既有CLI并记录日志，不修改冻结plan/hash、请求和验收规则；本次不执行B3或下游。

同花顺停复牌交叉审计没有新增可剔除单元，因此保持原队列。268,415个全天停牌股票日已被现有DG证据排除；当前范围仅命中17个盘中停牌股票日、85个单元。审计与可复用清单位于 `/private/tmp/dg_ths_suspend_audit_20260910/report.md` 和 `NEXT.md`，无需重新全量审计。

本轮日志和阶段结果保存在冻结目录的 `b2-halfhour-01/`，启动及汇总脚本位于 `/private/tmp/dg_stk_mins_b2_halfhour_run.py`、`/private/tmp/dg_stk_mins_b2_halfhour_summarize.py`。

**现已在时间边界停止，未启动第23批。**本轮22批、每批200个新窗口全部成功，实际取源1,753.131秒（29分13秒）。新增4,400窗口，累计4,620/45,432窗口（约10.17%），剩余40,812窗口。旧220窗口状态完全未变，不重取已保存页。

本轮为原队列顺序选出的240只股票、4,400个1分钟窗口，目标日期2014-01-20—2015-12-31，共83,266个股票日频率单元，不代表完整覆盖这一日期区间的全市场。

| 本轮分类 | 源数据完整 | 源返回空 | 部分/请求失败 |
| --- | ---: | ---: | ---: |
| 已确认本地缺口 | 1,127 | 458 | 0 |
| 历史待确认 | 81,224 | 457 | 0 |
| 合计 | **82,351** | **915** | **0** |

915个空单元分别为601360.SH 458个、600656.SH 128个、000033.SZ 128个、000594.SZ 96个、601268.SH 90个、600385.SH 14个、600087.SH 1个。源空按正常结果保存，没有自动推断停牌、换源或聚合。逐窗口范围和结果见 `b2-halfhour-01/windows.json`，精确单元继续复用staging中的原resolution文件。

累计89,924个取源单元：**88,146个源数据完整、1,778个源返回空**。窗口complete代表已完成来源判定，不代表该窗口数据齐备或正式Raw恢复完成。

实际4,440次请求、4,440页响应，共返回19,943,714行；81页为空，最大单页4,820行。返回行数包含请求跨日桥接等非目标记录，不能作为正式恢复写入行数。没有请求失败或重试，在途峰值2，请求全部结束。单次调用耗时中位数0.307秒、P95 1.166秒、最大5.836秒；子进程峰值RSS约690MiB，未触发内存门禁。

本轮有效速度150.6窗口/分钟。按本轮吞吐外推，**剩余取源约4.5小时**；只计B2，不包含后续Raw、Silver、Gold或指标恢复。当前样本仍以早期1分钟为主，后续按相同停点更新估计。

停点核验：22批均退出成功；累计 `raw-resolution.parquet` 与窗口汇总数量一致；旧220个checkpoint未变；正式文件checkpoint为0。只汇总既有缓存和元数据，没有重复审计正式行情。未运行DG或访问Dagster instance，未写正式Lake、数据库或事件，未改业务Python代码、配置或依赖边界；仅同步两份既有设计入口及临时命令/执行记录，没有提交或部署。下一次继续仍从原计划领取未完成窗口，并保持约半小时停点。

<a id="minute-gap-b2-hour"></a>

### 14.22 B2获准连续一小时续批（2026-09-10）

管理员本轮明确允许连续运行1小时。沿用§14.21的取源入口、冻结计划和验收边界，从4,620个已完成窗口继续，每批最多200个新窗口；本轮停点调整为约1小时，临近截止时不再领取下一批，失败或整批请求吞吐低于60次/分钟则提前停止。只获取和保存源数据，不执行B3、条件合成、Silver或下游。

执行记录使用冻结目录下独立的 `b2-hour-01/`，保留原半小时记录；临时启动/汇总脚本为 `/private/tmp/dg_stk_mins_b2_hour_run.py`、`/private/tmp/dg_stk_mins_b2_hour_summarize.py`。不修改业务代码、plan/hash或已有缓存，不重复审计原始数据。

**本轮因触发性能门禁提前停止，没有执行满1小时。**六批各200窗口均正常退出，耗时737.607秒（12分18秒）。前四批约71—72秒/批，第五批132秒，第六批318秒；末批202次请求仅38.2次/分钟，低于60次/分钟停点，未领取第七批。

新增处理1,200窗口，当前checkpoint累计5,820，未处理39,612。新增范围是227只股票的1分钟窗口、2015-12-04—2016-07-04之间23,076个目标单元，不代表这些日期的全市场。已有4,620窗口状态保持原样。

| 本轮现有缓存分类 | source-ready | source-empty | partial / request-failed |
| --- | ---: | ---: | ---: |
| 已确认本地缺口 | 365 | 176 | 0 |
| 历史待确认 | 17,882 | 4,653 | 0 |
| 合计 | **18,247** | **4,829** | **0** |

累计缓存分类为106,393个source-ready、6,607个source-empty。**这些是当前缓存标记；本轮异常空返回不能当成已证明的源端真实缺数。**窗口complete也只表示现有取源流程结束，以下238窗口仍需复核，不能把5,820个窗口全部视为来源结论已验收。

#### 日志核验与停点原因

- 共1,212次请求、1,212页响应，返回4,418,494行，260页为空；最大单页4,820行，无显式错误或重试，在途峰值2，子进程峰值RSS约764MiB。返回行数仍包含非目标桥接记录，不等同正式恢复行数。
- 前四批provider调用中位数约0.23秒；第六批升至3.007秒，P95 3.820秒，202页全部为空。末窗口完成后的索引汇总仍约2秒，变慢主要发生在源调用阶段，不是本轮缓存汇总突然变慢。
- 第五批最后一条非空响应之后，连续240次空返回（第五批38次、第六批202次），影响238窗口、199只股票、4,599个单元（已确认缺口76、历史待确认4,523），目标日期2016-04-28—2016-07-04。另230个本轮空单元不在这段连续空返回范围内；未因此直接认定其根因。
- 当前 `TushareResource.call` 直接将SDK返回DataFrame转换为行；已安装SDK的 `tushare/pro/client.py` 在 `requests.post` 响应布尔值为假时返回空DataFrame，HTTP错误可能因此没有抛异常。当前缓存未保存原HTTP状态/响应封包，所以**不能从本轮日志判定这240次到底是HTTP错误还是成功响应的合法空数据**；不能声称已定位限流、网络或Tushare服务端根因。

仅在执行记录中标出异常，没有删除或改写页面、请求、窗口checkpoint，也没有擅自把source-empty改成其他业务终态。精确页参数/缓存键见 `suspect-cache-pages.json`，单元/窗口/来源路径见 `suspect-scope-units.json`，汇总见 `suspect-impact.json`；后续只针对这个有界范围复核，不重做全量审计或重取正常成功数据。

累计 `raw-resolution.parquet` 与汇总数量一致；旧4,620窗口状态未变；正式文件checkpoint为0。本轮只执行B2源缓存写入，未运行DG、未写正式Lake、数据库、事件、Silver或下游；没有修改业务Python代码、配置或依赖，没有提交、部署、安装。

#### 下一步停点

**当前暂停，先讨论源响应核验再续批。**原fetch会跳过complete窗口，盲目继续不能解决这238个异常窗口；也不能删除缓存来强制重跑。建议下一步先做两个有界对照请求（一个此前非空窗口、一个本轮异常空窗口），保留HTTP状态与响应结果，并区分现有SDK调用与Tushare MCP通道的证据。现阶段尚未发出这些探针；根据核验结果再提出这240页及其依赖状态的精确修订方案。

此前剩余取源4.5小时建立在稳定吞吐上，当前不再作为承诺。脚本机械按本轮混合均速外推约6.8小时，也不能代表当前突变后的耗时；先确认并恢复稳定响应再重新估计。

#### 管理员批准的有界验证结果

管理员随后要求立即验证。本次仅追加原SDK通道两个原参数窗口请求，并通过Tushare MCP交叉验证异常窗口中的单日；没有续跑B2或改写既有缓存分类。

| 通道及样本 | 实测结果 |
| --- | --- |
| 原SDK：此前非空的600112.SH，1min，2016-04-28 09:00:00—2016-05-26 19:00:00，limit=8000、offset=0 | HTTP 200、API code=0、4,820行；HTTP耗时1.318秒 |
| 原SDK：此前异常空的600462.SH，1min，2016-04-28 09:00:00—2016-05-18 19:00:00，limit=8000、offset=0 | **HTTP 200、API code=0、3,374行**；HTTP耗时0.196秒 |
| Tushare MCP：600462.SH，1min，2016-04-28 09:00:00—15:30:00 | 241行、241个不同时间，09:30—15:00；预期网格无缺失/多余，代码与频率一致，OHLC/vol有限非负且非空 |

两个SDK请求继续使用原Raw合同全部显式字段，MCP也显式包含freq、exchange、vwap及OHLC/成交字段。实测资料依据为本地 `0370_股票历史分钟行情.md`，没有修改请求语义、分页或频率规则。两个SDK响应原始正文和MCP数据保存在原staging执行根下 `probes/http-probe-01/`，用于后续复用，避免为写入再次请求；HTTP摘要见 `b2-hour-01/http-probe-01.json`。

另外以假凭据、替身HTTP响应做了零网络离线验证：模拟HTTP 503时，当前已安装SDK返回0行、0列，恢复入口现有列门禁接受该结果；模拟HTTP 200且API成功的合法空结果同样被接受。因此**HTTP失败被当作空数据的实现缺口已复现**，并非仅凭日志猜测。证据见 `offline-http-error-check.json`；这是隔离验证，不是声称历史240次请求已证明都是503。

当前两个SDK样本已正常返回；至少600462.SH这个异常窗口已有源数据，先前空返回不能作为永久缺数依据。历史请求没有HTTP证据，仍不能确定当时具体状态码或网络/限流/服务端根因，也不能凭一个样本宣布全部240页都有数据。

**本次验证完成，批量仍暂停。**下一步应先修复恢复取源路径的HTTP失败判定，再对240页/238窗口做精确复核与依赖状态修订；复用本次成功响应，其余正常缓存不动。现有代码修改、缓存修订和后续批量尚未执行，不得直接按complete状态跳过这批窗口继续。

<a id="minute-gap-source-error-fix"></a>

### 14.23 源错误判定修复与历史空响应排查

管理员已授权修复错误判定、防止复发，并排查此前批次。本节先记录实现约束，再修改代码；不执行新的整批B2、缓存重置、正式Raw或下游修复。

1. **共同入口阻断无结构响应。**`TushareResource.call` 检查SDK返回的列结构；0列即请求失败，不能转成合法空数据。SDK现有API非零code、JSON错误和传输异常继续抛出。合法空表仍必须带源返回的列结构。本轮不替换SDK、不修改endpoint、token来源、请求参数、超时或安装包；不能伪造SDK没有暴露的HTTP状态。
2. **恢复入口严格验列。**`SourceRequestGate.call` 对所有结果检查原Raw列合同，包括0行响应。未知结构进入现有最多3次重试，耗尽后停止新增派发，排空最多两个在途请求并保存有效响应；不落空页、不走别名或聚合伪装成功。新增失败事件仅记录异常类型及无密钥的请求参数；正常响应记录实际列结构和校验标记。
3. **保存证据，阻断旧错误复用。**新源页保存 `observed_columns` 与 `response_contract=declared_columns_v1`，它证明显式列合同已通过，不代表保存了原HTTP状态。CLI在fetch/build-raw/promote-raw之前检查既有空页；无该证据的旧空缓存必须暂停，不能因window complete就跳过问题。只查小型page JSON元数据，不扫行情。现有缓存不自动删除、改状态或补填“已验证”。
4. **不按空结果数量判错。**连续空返回可能来自合法历史缺失，不能仅凭数量、比例或迟延把合法空结果改成失败。防复发依靠源响应结构、严格列合同、受控重试和旧空缓存门禁；原吞吐停点继续作为运行层的观察阈值。
5. **历史只查空页。**先顺序读四份执行日志及已落page元数据，输出全部历史空页清单和异常段。此前非空数据复用。此前批次的空页（初估不足100个，最终清单与补查范围见下方性能预算）在修复及隔离测试通过后，用原参数有界复核一次，记录HTTP状态、API code、源列及返回载荷；单在途、最多180次/分钟，遇到新的错误即停。载荷只进入独立probe目录，便于后续定点修订复用；不改既有page/request/window checkpoint。

配置审计：没有新增可调参数、env、运营输入或服务配置；`declared_columns_v1`是恢复源页的唯一校验版本标记，由fetch模块定义、source页写入和CLI门禁消费。并发2、3次尝试、180次/分钟等继续来自既有实现/冻结budget。无需改变plan/hash。

性能预算：日志约5,900次请求事件、缓存约5,900页JSON，仅读取元数据；新增启动门禁只保留文件名列表和单页JSON，不读取Parquet明细。全部既有空页已按元数据对齐为362页：已圈定异常段240页，此前SDK批次93页、MCP导入9页、同轮异常发生前20页。正常历史候选合计122页，分别按这三份互不重叠清单有界复核，合计最多122次请求，单页最多8,000行、单次30秒SDK超时，正常预估约1分钟，超过这个已查明的范围或出现响应错误停止。每个probe完成即保存；无正式文件替换或数据库事务。

CodeGraph explore/impact核对了TushareResource、SourceCache、调度器及CLI；AST引用清单覆盖21处实际call入口，含通用daily/namechange、分钟/BSE、指数、ETF及东财板块等资产/离线调用。共同resource仅新增异常响应拒绝，正常TushareResult结构不变；这些调用方的正常rows/columns消费与原异常传播继续保留。没有生产Ops、前端/API或Gold/Silver公式迁移。具体调用清单保存在 `source-error-audit/resource-callers.json`。

验收须覆盖：HTTP503/429等经真实已安装SDK转空时被共同resource拒绝；合法HTTP200空表/非空数据保留；API非零code、坏JSON、超时不得变空；不泄露token；恢复缺列/错列重试耗尽后没有成功页或complete窗口、不启动后续窗口；在途成功页保留；正确空页可续跑；旧未验证空页禁止fetch及Raw写入口；原42项恢复测试及共享请求策略/代表性消费者回归继续通过。实测只做上述有界旧空页复核，不拿正式Lake作为测试。

#### 实施与验收结果（2026-09-10）

**错误判定修复已完成，此前空页已查清；尚未修订旧缓存或继续B2。**本轮修改4个实现文件，新增2个测试文件，并同步本LLD及分钟资产设计页。没有更改子系统边界、依赖矩阵、数据集定义或行情计算口径。

| 约束 | 实现位置 | 验证结果 |
| --- | --- | --- |
| 无结构响应不得判为空 | `defs/resources.py` | `test_tushare_resource_response.py` 通过真实已安装SDK的离线HTTP替身验证400/401/403/429/500/502/503/504；合法空表、非空表、API错误、坏JSON、超时和连接失败均按预期处理 |
| 缺列、错列进入有限重试；保留在途成功页 | `bootstrap/stk_mins_gap_recovery_fetch.py` | `test_stk_mins_gap_response_contract.py` 覆盖缺列/多列/无列3次失败、无空页或别名误用、停止新增窗口及保存在途成功页 |
| 新页记录响应列证据；旧空页禁止直接复用 | `bootstrap/stk_mins_gap_recovery_source.py`、`bootstrap/stk_mins_gap_recovery_cli.py` | 新合法空页可零请求续跑；旧空页拦截fetch/build-raw/promote-raw，发生于初始化及执行前；旧非空页不受影响 |
| 不重取正常非空数据，历史排查有界 | 独立 `source-error-audit/` 清单与probe | 只复核122个历史空页，全部HTTP 200、API code=0、字段结构完整且仍为0行；原checkpoint字节保持不变 |

隔离回归两组分别 **81项、39项通过，去除15项重复后共105项**，覆盖原恢复流程、共享请求策略及namechange/ETF代表性消费者。目标文件Ruff、全src/tests的致命错误规则均通过。CodeGraph已sync并确认索引最新；现有Pydantic/Dagster提示不影响测试通过。

历史空页的完整对账为 **362 = 240 + 93 + 9 + 20**：

- **240页**属于已圈定的连续异常段，仍影响238窗口；600462.SH先前已取回3,374行，后续复用该响应，其余异常页本轮未重新请求。
- **93页**来自此前SDK批次（首批20窗口10页、新增200窗口2页、半小时批次81页），逐页复核均正常为空。
- **9页**来自早期MCP缓存导入，逐页复核均正常为空。
- **20页**来自本轮一小时任务的异常段之前，补查后也全部正常为空。

后三组互不重叠，共122次请求，实测合计 **47.775秒**。未发现异常段之外“此前为空、当前实际有数据”的新案例；这是当前实测结论，不能追溯证明过去每次HTTP状态正常。正常非空页没有再次请求，未重复审计正式Lake行情。

实际启动门禁读取5,904个page JSON耗时 **1.437秒**，正确阻断全部362个旧空页：122页的新复核证据目前仍在独立probe中，尚未提升到原checkpoint，不能把它们描述为运行时已经放行。最终互斥清单、原始响应路径及哈希已冻结在 `source-error-audit/verified-empty-evidence.json`（122页）与 `pending-suspect-pages.json`（240页），汇总见 `results.json`；后续无需重复请求122页。

**后续入口：**`source-error-audit/NEXT.md`。先按精确清单制定并执行证据提升、240异常页及其依赖状态修订，复用已有成功响应，保留其他缓存，再恢复原B2节奏。不能直接重跑fetch或删除缓存；本轮没有修改旧page/request/window、写正式Lake/数据库/Dagster事件、部署或提交。B3及下游保持未执行。

<a id="minute-gap-cache-revision"></a>

### 14.24 异常源缓存定点修订

管理员已明确授权“修订异常缓存”。本轮只修订既有B2源缓存及其依赖状态，不领取39,612个新窗口，不执行B3、正式Raw/Silver/Gold/指标、数据库或Dagster事件写入。

执行步骤与硬约束：

1. **固定输入。**使用§14.23的122页验证证据、240页异常清单及238窗口/4,599受影响单元；不重新审计行情。冻结这些小型清单的哈希、旧page/request/window状态和索引摘要作为修订日志，不复制行情文件作备份。校验原plan/hash、挂载、空间与路径白名单。
2. **复用与定点取源。**122个正常空页只增加真实验证证据，保留原数据路径、请求及行数；复用600462.SH已保存的3,374行原响应。其余239页使用原参数及显式字段，一页一页取回并即时保存原响应、HTTP/API状态和哈希。最多180次/分钟、单在途、每页8000行；响应错误立即停，不将失败转空；返回8000行、需要新分页或新增请求范围时停下核对，不静默扩大。成功响应续跑直接复用。
3. **候选先行。**调用现有write_page在同run的`revisions/source-empty-01`生成候选页，保留原responses目录。用当前SourceCache/day_facts重算238个窗口，完整成员来自冻结scope，仅替换240个请求的page路径；禁止新网络请求或修改其他窗口。复用原seed-index；122页仍为空且路径不变，无需改写seed事实。范围外请求被需要时停止，不绕过。
4. **完整验收。**候选页必须经过现行归一化、唯一键、日期/身份/频率及逐日网格/OHLC/vol校验。分清source-ready/empty/partial，空或部分不自动变ready。候选窗口与冻结成员一一对应；合并后的raw-resolution单元总数和主键不变、范围外记录逐字段不变。source-index由原page元数据与362项修订合成，不扫描正常行情。保存原状态至修订审计记录及checkpoint追加历史。
5. **逐文件提升与恢复。**所有候选完整通过后，按清单原子更新240项request、238项resolution与window、两份汇总索引、362项page元数据；最后才提升预留的一个旧未验证空页，使已有启动门禁在修订结束前持续阻断fetch/Raw入口。不宣称多文件整体原子。每项提升有checkpoint，候选文件哈希冻结；中断后从清单继续，已提升项不重取源、不重复业务计算。最后验证空缓存门禁通过、各候选与目标哈希一致，停在缓存验收。

| 预算项 | 本轮边界 |
| --- | --- |
| 对象与日期 | 199只股票、1min、2016-04-28—2016-07-04的238个异常窗口；另122个既有空页仅提升已保存证据 |
| 网络 | 新增239请求，复用123份已保存响应；每请求8000行硬上限，本轮新增最多1,912,000行；单在途、180次/分钟、30秒超时，错误即停 |
| 文件与内存 | 最多240个新源页、238个窗口候选及两份索引；单页归一化，DuckDB 2GB/2线程/禁spill，RSS 4GiB；写入只在原staging run内 |
| 扫描与计算 | 固定scope一次取238窗口完整成员；逐窗口只查其候选源页；约5,904页元数据合并及现有约11.3万条resolution索引集合对账，不扫正式湖 |
| 提升 | page/request/window按单JSON原子替换；resolution与两份索引按单Parquet原子替换；失败保留候选与逐文件进度 |
| 预计耗时与拒绝 | 网络约2—4分钟，候选计算和验收约1—3分钟；源错误、满页需扩分页、范围外新请求、验收不符即停；不重复全湖审计 |

CodeGraph explore已追到SourceCache→_window_steps→_request_steps→write_page→RecoveryRun.checkpoint；当前代码补查覆盖day_facts、save_resolution、compact_source_index、CLI旧空页门禁与冻结成员选择。仅以独立操作脚本编排现有helper，不新增正式asset/resource/check/配置/CLI合同，不改变分层与依赖。脚本位于`/private/tmp/dg_stk_mins_cache_revision.py`，仅本次修订使用，负责人为本任务；完成后不挂入日常任务，留作审计证据，不再默认执行。

执行前用隔离fixture验证：错误载荷、非白名单写入/网络被拒绝；合法空与非空候选保持原分类语义；断点后复用响应、最后门禁释放顺序及重复提升幂等。最小真实验证先复用已有600462响应并生成候选，再处理剩余239页；不为测试重复请求已成功响应。

#### 本次实际完成与验收

**异常缓存已修订，原B2可按原计划续跑；本轮停在缓存验收。**plan/hash、来源优先级、2014+范围及当前分支均未改变。

| 项目 | 实际结果 |
| --- | --- |
| 取源 | 复用122份正常空响应及1份已有非空响应；新增239次请求，耗时129.926秒，无请求错误、额外分页或范围扩展 |
| 异常页结果 | 240页中237页返回数据、3页正常为空；合计取得1,101,852行原生分钟行情（含复用响应），只保存在staging |
| 原误判单元 | 4,599个source-empty单元中4,566个改为source-ready，33个仍source-empty；无source-partial/request-failed |
| 剩余33个 | 000033.SZ 13个、601360.SH 20个股票日；明细见revision目录`remaining-empty-units.json`，不据此推广到其整个历史 |
| 当前汇总 | source-ready由106,393增至110,959；source-empty由6,607减至2,041；总计113,000个已处理单元不变 |
| 写入范围 | 更新362个page元数据、240个request、238组resolution JSON/Parquet及window、两份汇总索引，共1,318个逐文件提升项；旧源响应保留，未删除缓存 |
| 续跑门禁 | 首项提升后实际暂停，门禁仍正确阻断362页；恢复完成后全部旧空页有有效证据、门禁通过，原checkpoint追加记录保留 |
| 范围验收 | 238窗口的4,599个冻结成员一一对应；范围外resolution逐字段相等，其他page/request/window/seed等元数据哈希不变；候选与提升目标哈希逐项一致 |

操作脚本隔离测试最终 **9项通过**，含HTTP/API/请求/哈希/列/满页拒绝、写入白名单、禁新增网络、合法空与非空、暂停续跑/幂等/最后门禁释放、Hive目录字段推断反例。最小真实样本直接复用600462.SH的3,374行，0次新请求。数据取源及窗口重算没有重复执行。

构建索引时发生一次候选阶段错误：DuckDB默认把`run_id=...`目录推断成额外列，导致9列实体数据与10列读取结果无法UNION。原缓存当时尚未替换。已将索引合并读取显式设为`hive_partitioning=false`，补充隔离反例后重做索引合并；已有源响应和238个窗口候选直接复用。合并摘要别名同时使用SQL引号，避免保留字歧义。后续索引候选构建2.441秒，提升续跑与最终验收4.849秒；这些分段耗时不包含方案梳理及脚本编写。

修订证据唯一入口：`/Volumes/datasource/data_lake_staging/stk_mins_gap_recovery/run_id=20260910-v1/revisions/source-empty-01/`，包含manifest、独立原响应、candidate、冻结promotion清单、逐项提升记录、sample、pause-validation、operator-validation和results。冻结目录`source-error-audit/cache-revision-results.json`保存小型结果与入口。脚本及隔离测试在`/private/tmp/dg_stk_mins_cache_revision.py`、`/private/tmp/test_dg_stk_mins_cache_revision.py`，当前脚本哈希记在operator-validation中，未接入日常任务。

本轮仓库仅同步本LLD与分钟资产设计页，正式实现沿用§14.23修复，没有新增或修改asset/resource/check/partition/sensor/schedule、配置、CLI合同或依赖矩阵。未运行dg、未访问正式Dagster runtime、未写正式Lake或数据库、未部署/提交。当前仍是5,820个已处理窗口、39,612个未处理窗口；下一步可继续原B2每批200窗口，约半小时汇报，B3继续等待独立阶段执行。

<a id="minute-gap-b2-fortymin"></a>

### 14.25 B2获准继续40分钟

管理员在§14.24缓存修订验收后明确授权继续B2、可执行40分钟。本轮从累计5,820个complete窗口、110,959个source-ready和2,041个source-empty单元继续；原缓存门禁已通过。执行仍使用冻结plan/hash与原fetch入口，每批最多200新窗口、最多2请求在途、最高180次/分钟，响应错误按现行最多3次重试并停止失败批次，吞吐低于60次/分钟提前停下。

执行入口为`/private/tmp/dg_stk_mins_b2_fortymin_run.py`，由已验证的一小时操作脚本仅调整本次输出目录、起始窗口数及时间上限；40分钟硬停止，预计当前批次无法在剩余时间内完成时不领取新批次，约30分钟汇报。记录存于冻结目录`b2-fortymin-01/`。只运行B2取源与staging缓存，复用全部已有成功页/窗口/修订证据，不执行B3或下游，不写正式Lake、数据库或Dagster事件，不提交或部署。依原180次/分钟上限，本轮最多约7,200次请求，预计约5,000—6,000新窗口；实际以响应速度与门禁为准，不承诺源端都有数据。

#### 本轮执行结果与停止原因

**实际运行38分18秒，因源请求错误提前停止，没有发出第26批。**前24批全部成功，第25批完成196窗口后停止；已完成数据均保存，无重复取源或扩大范围。

| 项目 | 结果 |
| --- | --- |
| 新增完成 | 4,996窗口；另1窗口failed（20单元），1个已尝试的请求窗口被中断、尚无window终态 |
| 累计窗口 | 10,816 complete、1 failed；尚未完成34,616窗口（包含失败/中断），不能称这些窗口都未尝试过 |
| 新增分类 | 96,148 source-ready、316 source-empty、20 request-failed；无source-partial |
| 当前累计分类 | 207,107 source-ready、2,357 source-empty、20 request-failed，共209,484个已落resolution单元 |
| 范围 | 本轮已落状态涉及259只股票、1min、2016-06-03—2018-07-25的缺口窗口，不代表这些日期的全市场 |
| 源调用 | 5,041次尝试，5,036次成功响应、5次失败事件；其中3次为重试。成功页共23,242,040行，56页正常空响应，单页最大4,820行 |
| 性能 | 平均约130个完成窗口/分钟；响应中位0.380秒、P95 1.512秒、最长4.119秒；峰值2请求在途，子进程峰值RSS约1.12GiB |
| 30分钟汇报 | 第19批后已完成3,800窗口，新增73,336 source-ready、284 source-empty；随后继续到本次失败停点 |

两个失败请求均为1min、2018-06-28 09:00:00—2018-07-25 19:00:00、limit=8000、offset=0：

- **300023.SZ**：page key `67cbd5cb6e47576a9a8d5cac`，失败3次；window `bdb35940030e401443f94e74` 标记failed，20个单元为request-failed。
- **300089.SZ**：page key `971cdad5fa5858ebdf91a7d7`，失败2次后随整体停止；window `2900d1f80b9d893f9fe43ad1` 尚无checkpoint，不能算complete，也不能算source-empty。

两者均记录SDK `Exception`，现有执行日志只保存异常类型，未保存具体API错误正文或HTTP状态；**不能据此认定限流、权限或网络根因**。本轮未追加探针、修改重试计数或继续请求。失败请求均没有pages成功记录或空数据页，§14.23的错误分类本次没有回退为source-empty。

CLI异常退出时跳过末尾索引汇总，但每个成功窗口已有独立checkpoint及resolution。停止后复用现有`compact_source_index`完成一次本地汇总（4.350秒、0源请求）；没有重新计算或取回成功行情。读回确认source-index共10,940页，raw-resolution共209,484行且scope_id唯一，汇总与逐窗口状态一致；旧5,820窗口内容保持不变，空响应证据门禁通过，正式files checkpoint仍为0。

所有记录位于冻结目录`b2-fortymin-01/`：before、events、progress、process、results、windows、thirty-minute-progress、verification及failed-request-windows。**后续先核验这两个失败请求的具体API原因，再受控恢复其重试状态，随后续跑B2；不要直接清空request-errors或反复运行fetch。**首个请求的3次预算已耗尽，直接fetch会再次失败。原正常成功页、此前修订证据均继续复用。

本轮只增加独立操作脚本/执行报告并同步本LLD及资产设计页，未修改正式实现、配置、CLI合同或依赖矩阵。操作脚本致命错误静态检查通过；验收使用执行日志、缓存元数据及汇总索引，不重复全湖审计。没有运行dg或访问正式Dagster instance，没有写正式Lake、数据库或事件，没有部署、提交或进入B3。

<a id="minute-gap-b2-thirtymin-02"></a>

### 14.26 记录退市说明并继续B2最多30分钟

管理员说明300023.SZ和300089.SZ均已退市，要求记录并继续B2最多30分钟。记录来源为管理员本轮说明，未重新核查退市日期；不把退市解释为历史分钟数据应当缺失，也不据此认定此前API错误原因。

只暂缓§14.25的两个失败请求窗口：`bdb35940030e401443f94e74`与`2900d1f80b9d893f9fe43ad1`。保留其failed/未完成及3次/2次尝试记录，不修改为complete或source-empty，不清空缓存、重试计数，不从冻结总范围扣除。其他窗口（包括这两代码的其他历史窗口）仍执行原规则；不是全局排除所有退市股票。

本轮从10,816 complete、1 failed继续；34,616个尚未完成窗口中，明确暂缓2个，剩余34,614个按原freq/start_date/code顺序选取，通过既有`--window-id`逐批传入原fetch，每批最多200。选择清单只读冻结window元数据一次并保存到`b2-thirtymin-02/selection.json`，不重新审计源行情；原plan/hash、范围、两请求并发、180次/分钟及有限重试均不变。

执行脚本`/private/tmp/dg_stk_mins_b2_thirtymin_run.py`由上一轮操作脚本调整30分钟上限、初始计数及上述显式选择。1800秒硬停止，预计下一批无法在1770秒内完成时不领取；错误或吞吐门禁触发提前停。最多约5400次请求，预计约3400—4400个新窗口；结束后只做一次缓存元数据/索引汇总及对账，保留成功数据。只写staging，B3及正式Raw/Silver/Gold/指标、数据库、Dagster事件不执行，不提交或部署。

#### 本轮执行与验收结果

**实际运行29分05秒，完成22批、4,400个新窗口，按时间边界正常停止，未发出第23批。**两个指定失败窗口未请求，原失败计数、page缺席状态与所有旧window记录保持不变。

| 项目 | 实际结果 |
| --- | --- |
| 新增单元 | 87,170个：85,126 source-ready、2,044 source-empty，无新增partial或request-failed |
| 当前累计 | 292,233 source-ready、4,401 source-empty、20 request-failed，共296,654个resolution单元 |
| 窗口 | 累计15,216 complete、1 failed；尚未完成30,216，其中2个暂缓，余下30,214可按原序选取 |
| 本轮范围 | 244只股票、1min、2018-06-28—2020-04-13的缺口窗口，不代表这些日期全市场 |
| 取源 | 4,424次请求全部成功、0重试、0失败；20,544,768行、123个正常空响应页，单页最大4,820行 |
| 性能 | 约151个窗口/分钟；响应中位0.315秒、P95 0.700秒、最长4.358秒；峰值2请求在途、子进程RSS约1.47GiB |
| 验收 | 两份汇总索引与逐窗口分类一致；source-index 15,364页；raw-resolution 296,654行且scope_id唯一；空响应证据门禁通过；正式files仍为0 |

关于退市说明：本轮按原范围实际请求到300023.SZ的另外20个历史窗口（2018-07-26—2020-03-25），399个股票日均为source-ready；300089.SZ的另外20窗口（2018-07-26—2020-03-19），400个股票日均为source-ready。这是本轮正常执行结果的元数据汇总，没有为此追加探针。退市情况按管理员说明记录，但原两个失败请求的具体API原因仍未验证，不能把它们改为“退市导致无历史数据”，也不能把这两个代码整体排除。

证据保存在冻结目录`b2-thirtymin-02/`，含selection、before、events、progress、process、results、windows及verification。操作脚本使用既有CLI显式window-id，未改正式实现、配置、数据合同或依赖边界；脚本致命错误静态检查及文档完整性检查通过。旧窗口状态及两个暂缓请求未变，成功缓存不重取，本轮无需异常索引补写。

当前停点见该目录`NEXT.md`。后续B2继续显式排除这两个待处理窗口后，按原freq/start_date/code顺序选取未完成窗口；不能直接使用未带选择清单的fetch命令，因为首个旧失败请求重试预算已耗尽。两个异常请求保留独立待办，不自动重置、不改为complete、不从总范围扣除。正式Raw/Silver/Gold/指标、数据库、Dagster事件均未写入，未运行dg、未部署或提交，B3未开始。

<a id="minute-gap-b2-until-accounted"></a>

### 14.27 持续推进B2并汇总待排查项

管理员授权持续推进直到完成，中途失败或待澄清事项先记录、之后统一排查。本轮完成口径是冻结45,432个窗口全部归入“取源流程完成”或“明确待排查”，不等于所有单元来源齐备，更不等于正式Raw已补齐。B3及下游仍不执行。既有15,216个complete窗口继续复用，原2个失败窗口保留待排查，不重置重试计数。

执行约束：

1. 使用既有fetch CLI及显式window-id，每批最多200，按freq/start_date/code顺序；最多2请求在途、180次/分钟、每请求最多3次尝试、原分页和内存门禁不变。只新增本次操作控制脚本，不修改正式CLI/取源/分类合同。
2. 批次遇到窗口错误时仍由既有调度器停止并排空在途请求。控制脚本根据实际fetch开始事件与checkpoint，把已开始但未完成的窗口记录为待排查，保留参数、错误事件、缓存路径及状态；成功窗口保留，未开始的窗口放回队列首部，继续下一批。不得把整批未执行对象标为失败，不重复派发同一待排查窗口。
3. source-empty、source-partial继续保留原业务分类，不能自动视作失败、完整行情或恢复成功。最终单独汇总这些单元供后续统一处置；不在本轮聚合补造或写正式数据。
4. 每批记录选择清单和开始状态，结束后原子更新进度与待排查清单；进程中断后从实际checkpoint续跑，已成功页复用。取消立即停止领取新批次，并交给原CLI保存在途结果。没有窗口开始事件的启动/环境错误不能伪装成窗口问题，须保留现场并处理基础阻塞。
5. 单个业务/源请求错误按管理员新指令记录后继续，替代此前“任一批失败即结束整轮”的操作停点。无完成窗口的失败批次或吞吐低于原门禁时先冷却60秒再继续，避免密集空转；每20秒仍输出进度，约半小时汇总一次。磁盘、身份、plan/hash、路径与响应结构等硬门禁不放宽。
6. 异常批次不立即全量重建索引；后续成功批次沿用CLI汇总，最终统一再核对必要的索引收口。最终只读取缓存元数据/小型resolution与冻结scope作集合对账，不重复扫描正常行情或重新请求空源证明。

| 剩余频率 | 窗口（含2个既有待排查） | 目标单元 | 冻结估计源行数 |
| --- | ---: | ---: | ---: |
| 1 | 10,922 | 192,538 | 52,430,912 |
| 5 | 6,446 | 471,917 | 26,092,055 |
| 15 | 4,375 | 472,778 | 9,051,277 |
| 30 | 4,650 | 473,608 | 4,793,440 |
| 60 | 3,823 | 472,383 | 2,871,570 |

合计30,216窗口，主请求约3万次；实际别名与分页仍受原冻结合同约束。按近期约130—151窗口/分钟预估3—5小时；返回行数按上表只是冻结估计，空源、日期网格与别名会改变实际量。响应逐页保存，不在内存累积全量行情；DuckDB继续2GB/2线程/禁spill、RSS上限4GiB、可用磁盘至少200GiB。只在既有staging run写入，阶段记录位于冻结目录`b2-until-accounted-01/`。

CodeGraph explore及实际代码核对覆盖CLI→SourceCache.resolve_batch→execute_source_steps→逐页/逐窗口checkpoint；正式取源逻辑不变。操作脚本`/private/tmp/dg_stk_mins_b2_until_accounted.py`上线前隔离验证成功/失败/在途受影响/未启动回队、取消与重启复用；禁止路径和队列守恒均有反例。脚本不接入日常任务，不新增配置、asset/resource/check/事件，不部署或提交；最终同步本节与资产设计页及NEXT入口。

#### 本轮执行与验收结果（2026-09-11）

**运行4小时29分57秒，155批，新增完成30,206窗口；累计45,422个取源流程完成、10个待排查，45,432个冻结窗口全部覆盖、未取队列为0。**38,616次源请求全部正常返回、0重试，保存74,863,939行。4个批次因来源时间点校验中止后按本节规则继续，成功窗口不丢失、未启动窗口回队。峰值2请求在途、子进程RSS约3.22GiB，未放宽原预算。

| 分钟 | 来源齐备 | 源空 | 部分数据 | 异常窗口待处理 | 合计 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 449,397 | 37,078 | 2 | 40 | 486,517 |
| 5 | 449,582 | 22,528 | 1 | 301 | 472,412 |
| 15 | 449,910 | 23,587 | 1 | 0 | 473,498 |
| 30 | 449,397 | 24,336 | 116 | 479 | 474,328 |
| 60 | 449,343 | 23,349 | 1 | 410 | 473,103 |
| 合计 | 2,247,629 | 130,878 | 121 | 1,230 | 2,379,858 |

“异常窗口待处理”不是确认1,230天行情缺失：601个单元有failed分类，629个尚无最终resolution。当前实现把窗口级校验错误也记为request-failed，不能据此宣称源请求失败；本轮38,616次请求均正常返回。空源与部分数据也不擅自判为可放弃或完成恢复。

取源流程完成不等于正式数据已修复。分频率窗口验收：1分钟26,121完成/2待排查，5分钟6,448/4，15分钟4,378/0，30分钟4,651/2，60分钟3,824/2。

| 类别 | 对象与频率 | 窗口/单元 | 事实与后续入口 |
| --- | --- | --- | --- |
| 旧请求失败 | 300023.SZ、300089.SZ，1分钟 | 2窗口/40单元 | 2018-06-28—2018-07-25；原3次/2次失败尝试保留。退市仅按管理员说明记录，不推断历史无数据。 |
| 时间点校验失败 | 920680.BJ，5/30/60分钟 | 3窗口/580单元 | 均在2024-10-30触发Duplicate or off-grid source rows；原响应已缓存，后续直接定位缓存，区分重复与非标准时间点。 |
| 时间点校验失败 | 920122.BJ，5分钟 | 1窗口/1单元 | 同为2024-10-30、同类门禁；不直接清洗或放宽规则。 |
| 同批连带中断 | 600070.SH、600190.SH，5分钟；000622.SZ，30分钟；002502.SZ，60分钟 | 4窗口/609单元 | 未证明这些股票行情有错；后续基于已保存页续办，不把同批错误归因于它们。 |

旧退市说明不作为API失败根因。所有时间点校验失败均指向2024-10-30，但当前只证实既有门禁触发“Duplicate or off-grid source rows”，尚未区分重复与非标准时间点；不得直接删除行或放宽规则。连带中断对象尚未证明行情有错。完整window_id、请求窗口、checkpoint及日志路径保存在`b2-until-accounted-01/deferred-windows.csv`，批次错误上下文不代表连带对象有同一错误。

最终只读取缓存元数据、resolution和冻结scope完成一次集合对账：所有窗口恰好归入完成/待排查且互斥；2,379,858单元无重复、无范围外身份/频率/日期；缺少resolution的629单元均属于待排查窗口。source-index 53,980页与页元数据数量相符；既有15,216完成窗口及旧失败window记录保持不变；空响应结构证据门禁通过；正式files checkpoint仍为0。未重复源探针、正常行情或全湖审计。

当前入口为冻结目录`b2-until-accounted-01/NEXT.md`；人读结果`REPORT.md`、机器验收`verification.json`、全部非齐备单元`nonready-units.csv`、按股票/频率/状态汇总`nonready-summary.csv`及上述10窗口清单均已保存。旧commands/NEXT已指向该收口记录。下一步统一核对10窗口，优先定位已保存响应，受控续办连带中断，旧请求失败另查API原因；源空及部分数据仍按既有恢复方案单独处置。不自动重置失败计数、不聚合补造、不进入B3。

本轮仓库只同步本LLD及分钟资产设计页，操作/验收脚本在/private/tmp；无正式实现、配置、CLI合同或依赖矩阵变更。控制脚本7项隔离测试、两脚本致命错误静态检查通过。无正式Lake、数据库或Dagster事件写入，无部署或提交，其他任务脏文件保留。

#### Review清单与后续验证顺序（2026-09-11补充）

管理员要求在结果报告内列全非齐备股票代码。已仅从既有nonready-summary.csv汇总365个去重代码、132,229单元，逐股票列出频率、分类数量及首尾日期，写入冻结目录b2-until-accounted-01/REPORT.md；365行全部列出。分类分别为361个源空代码、2个部分数据代码、8个异常窗口代码，集合有重叠。日期跨度不代表连续缺口，异常待处理不代表行情已证实缺失。汇总与已验收verification.json逐状态计数相符，没有新源请求或全湖查询。

### 后续验证步骤（待执行）

只复用当前冻结范围和已有缓存，不再重做全湖审计。按以下顺序，每一步产出明确清单后再进入下一步；本次仅补充步骤，没有执行这些验证。

1. **定位4个时间点校验失败窗口。**只读920680.BJ的5/30/60分钟及920122.BJ的5分钟缓存，先看2024-10-30，逐条区分重复时间戳、非标准时间点、OHLC/vol异常。列出原始行和规则差异，不能直接删除行或放宽网格。只有缓存不足以解释时，才针对相同股票/日期/频率做最小Tushare MCP核验，不重取整年。
2. **续验4个连带中断窗口。**600070.SH、600190.SH的5分钟，000622.SZ的30分钟，002502.SZ的60分钟：复用已保存响应，完成未完成的窗口判定；只对没有成功缓存的请求补取。不要把同批另一只股票的错误套到它们身上。产出各自逐日分类和恢复后的checkpoint。
3. **核实2个旧请求失败。**300023.SZ、300089.SZ，1分钟，2018-06-28—2018-07-25：保留原失败证据，核对原参数并做一次受控源验证，记录具体响应/异常信息；不直接清空3次/2次计数无限重试。退市不是历史分钟必然不存在的证据。
4. **逐日解释121个部分数据单元。**只查920267.BJ的1个1分钟单元和920680.BJ的120个跨频率单元，直接定位缓存中的预期时间点缺失或OHLC/vol问题。分别列出缺少的时间点、字段及可用较小分钟周期；exchange、vwap等非核心字段缺失不计入此次行情缺口。已有分类代码的核心字段检查为OHLC/vol，并另有时间点门禁。只对仍有疑问的精确日期追加源验证。
5. **归类130,878个源空单元。**按股票/日期复用已有停复牌交叉验证、上市退市和身份映射证据，区分已有事实可解释、源确无目标行情、仍待澄清；只核未解决项，不重复验证已有源空响应。跨频率可用性按同股票日一次性汇总。5/15/30/60分钟若源缺失，再评估已有更小分钟周期是否完整及可聚合；1分钟也缺时单列其他来源待办，不直接造数或宣布无需补齐。
6. **汇总review后再进入逐层恢复。**更新每个待办的结论、证据、来源及明确处置范围，不把整段日期跨度视为连续缺口。确认来源选择和异常处置后，再按原B3做Raw候选校验与提升；Raw实际变化清单验收后，才映射处理Silver，再按下游定义逐层处理Gold/指标。本次不执行正式写入。

每步只更新涉及单元的结果，最终用已有scope集合对账：来源齐备、仍源空、仍部分数据、异常待办之和必须等于2,379,858；已确认正常的缓存不重新取源、不重复全量审计。


### 14.28 按管理员四步口径收敛恢复（2026-09-11）

本节替代14.27末尾的后续六步顺序，保留历史执行证据。管理员已确认：

1. 先依据现有响应、错误及缓存，排除请求失败/中断导致的未取到；只补取没有可靠成功结果的窗口，成功空返回不重复拉取。
2. 同股票日1min齐备时，用统一聚合规则补5/15/30/60min，不逐股票日反复对比原生周期。合成来源记录清楚；此项尚未执行。
3. 真正退市股票的Raw也按前两项尽力核验补齐，无法补齐的登记。Silver及下游清理真正退市身份的历史数据；换码、转板及身份延续不属于此排除范围。管理员接受其历史研究口径影响；当前未执行清理。
4. 剩余仍存续且缺1min的数据细化到股票/日期/周期，交由其他来源补充。

本轮只获准执行第1步，不做聚合、不清理、不进入正式Raw提升及下游。
现有130,878个source-empty及121个source-partial复用既有响应判定与空返回结构验收。
10个异常窗口拆分为：4个已取到但时间点门禁阻断（581单元），4个连带中断（609单元），2个旧请求失败（40单元）。此前4个时间点窗口的诊断证据见冻结目录b2-until-accounted-01/step1-timegrid/REPORT.md，不重复验证。

第1步预算与执行：6个窗口649单元中，1个复用4900行成功缓存；其余5个窗口各一次MCP请求，单次均低于8000行，最多40000行，总量上限40000新行+4900缓存行，预计5分钟内，内存沿用冻结预算。原响应存入run-scoped staging，使用现成write_page/day_facts/resolve_window完成缓存与逐日判定；保留旧request-errors计数和历史报告，不重新发起SDK请求、不重置重试预算。若出现失败或校验阻断就登记，不自动追加请求。正常缓存不重扫；只读取所选scope、窗口及必需元数据，source index按现有入口收口。新增证据、恢复checkpoint与本节保持一致，正式Lake/DB/Dagster均不写入。

第1步已完成：5次MCP请求17,550行，复用4900行缓存，6窗口649单元全部source-ready。使用现成缓存/判定方法并更新source index；旧错误次数及4个时间点失败checkpoint未变。来源齐备累计2,248,278；源空130,878；部分121；源已返回但窗口校验阻断581，合计2,379,858。无请求失败/中断未取到窗口。最新剩余361代码131,580单元，不等同全部真实缺失。结果与证据入口为冻结目录b2-until-accounted-01/user-step1-20260911/REPORT.md，NEXT已更新；旧快照保留。第2步、正式写入及退市下游清理未开始。


### 14.29 第2步可补量审计与执行细则（2026-09-11）

#### 已有方案与当前实现

§14.6/B3a早已规定Raw竞价、窗口、OHLCV、追溯及条件聚合，但不是已实现的聚合执行入口。当前gap_recovery_cli只有原生取源和Raw build/promote；gap_recovery_raw.build_candidate要求所有成员source-ready。Silver的_create_silver_stk_mins_final_rows已有1min窗口聚合，但会先做Silver价格/小成交处理，不能直接拿其输出当Raw。此次仅审计并细化方案，没有改代码或生成行情候选。

CodeGraph已用于定位_create_silver_stk_mins_final_rows及调用区域；前两次宽查询噪声较大，已回到确切符号和真实源码。已读恢复source/raw/CLI、Silver聚合及其测试位置。影响范围是恢复入口、来源分类与逐日追溯、Raw候选合同和测试；不改变Silver/Gold窗口或复权合同。本轮不是全消费者开发验收，实施前还需把来源说明同步到当前catalog/schema消费者。

#### 已有可计算量估算（单位为股票×日期×周期，不是实际新增量）

以第1步后的131,580个剩余单元为集合，按最新身份与日期联结旧Raw1紧凑审计、最新raw-resolution和已验证的2份单日MCP证据；没有再请求源站或重扫正式Lake。Raw1汇总按完整241点、无重复、价格成交有效及身份频率时间正确筛选，exchange不参与缺口判断。旧审计成交异常计数同时包含amount，因此本轮作保守充分条件；本次未出现因该保守条件需要复核的本地候选。source-ready依据此前取源验收，并非新完成的最终候选验收。

| 分类 | 单元数 | 处理 |
|---|---:|---|
|有齐备1min支撑的历史估算|5,121|先扣除已有有效记录，不能整批直接聚合|
|窗口连带阻断但原生已齐备|576|直接复用原生缓存，不聚合|
|粗周期无齐备1min|88,803|保留其他来源/后续处置清单|
|1min本身空或部分|37,080|不能计算恢复，保留清单|
|合计|131,580|与第1步余项精确对账|

5,121由5,003源空、114源部分及4个2024-10-30时间点异常单元组成。此前581个窗口级阻断单元进一步拆为576原生齐备、4个可计算异常日、1个仍缺；最后1个为920680.BJ/2024-11-28/5min，1min也是source-empty。此前“整段581单元不是都缺”现在有了精确分类，不修改历史报告。

| 周期 | 历史估算单元 | 按整日展开的记录数上限（不是净新增） |
|---|---:|---:|
|5min|60|2,940|
|15min|1,108|18,836|
|30min|1,976|17,784|
|60min|1,977|9,885|
|合计|5,121|49,445|

上述5,121单元和49,445行是收紧为“只补缺失记录”之前的可计算量估算，保留作历史证据，不是执行数量。4个2024-10-30异常单元的目标端点已有有效源数据，不以计算值覆盖，退出聚合队列；其余最多5,117个单元还需按已有记录扣除，源部分单元尤其不能按整日新增计数。实际需补的周期、时间点和净新增行数由下面A步骤一次生成并冻结，不能沿用此表直接执行。

#### 固定计算口径

1. 只处理2014-01-01—2026-09-09冻结单元。以最新业务身份连接输入；输出Raw代码取选定1min源代码，必须属于冻结source_candidates，不擅改身份映射。Silver以后的新身份口径保持不变。
2. 1min输入选择：已验收的本轮原生缓存优先，其次旧Raw中已验收的完整股票日；此前独立MCP证据亦可复用。用于计算的1min整日选一个来源；只有同一天确实缺多个周期时才共享读取，未缺周期不计算、不输出。来源文件、代码、日期和校验值登记到清单。
3. 盘中1min固定241点：09:30、09:31—11:30、13:01—15:00。需要每点唯一、OHLC/vol有限有效、OHLC大小关系成立。零成交不是缺口；不做Silver的小于100股归零。amount异常单列输入合同阻断，不冒充OHLC/vol缺口或填假金额。
4. 09:30原样作为独立记录；不并入Raw第一根。其余上午、下午独立左开右闭窗口。例：5min首根09:35覆盖09:31—09:35；15min首根09:45；30min首根10:00；60min首根10:30。午休不跨窗，尾根15:00。不生成15:00后行情。
5. open取第一分钟open，high/low取窗口极值，close取最后一分钟close，vol/amount求和。价格不复权；vol单位股、amount单位元。连续竞价每根必须恰有freq条1min输入，竞价恰有1条。完整日的理论行数依次49/17/9/5；实际生成行数必须等于缺失时间点数量，不能拿理论整日行数作为每个单元的新增目标。
6. 辅助字段沿§14.6收口：exchange按源代码交易所规则；vwap在vol>0时amount/vol，vol=amount=0时取close；vol=0而amount>0等不一致记录为合同异常，不伪造值。辅助字段不扩增业务缺口名单。此为聚合值，永久追溯标记aggregated，不能伪称Tushare原生vwap或响应。
7. 现有正式Raw正常股票日不覆盖；当前源部分响应的有效记录保留，聚合只补目标频率缺失时间点；不逐字段拼接，不用计算值覆盖有效原生记录。来源追溯细化到新增记录键，记录该行原生或聚合来源。未来若发现冻结范围内已有正式记录，停止该单元并核清范围，不静默覆盖。

#### 执行顺序、批次及验收

A. 将execution-classification.parquet只作为初始候选清单，不能直接当作写入清单。复用已下载结果、旧Raw审计和已确认时间点证据，按“最新身份＋日期＋目标周期＋时间点”生成精确缺失键。正式Raw与已下载目标周期数据中的有效记录都算已有；新旧代码映射到同一身份后判定，防止换码造成重复补入。目标源整日空则列出全日缺失键，部分空则只列缺失键；已有异常记录另列，不自动覆盖。576个已取到完整数据的单元直接复用；4个混合时间点异常日已有有效目标端点，保留源记录并单列其多余时间点，不用计算结果替换。输出missing-records、source-reuse和residual三份有明确键的清单，保存数量；不重做源站请求、不重扫全湖。

A步骤的缺失键确定后，只将所需1min窗口分组计算：例如只有09:35缺失，只读取已选1min输入中的09:31—09:35参与该记录的聚合；整日齐备资格继续复用已有检查。必须先筛选所缺周期与窗口，再进行聚合，不能先生成全部四周期再覆盖或丢弃多余结果。
B. 补聚合候选入口及来源清单；复用现有DuckDB连接、窗口表达式、候选检查和逐文件checkpoint。不能直接调用Silver成品，也不能把aggregated-ready强改名source-ready骗过现有build_candidate。同步调整恢复入口对已验收来源类别的识别，保持原生与聚合可区分；原生产日更行为不改变。

C. 一次隔离规则验证覆盖四周期、独立竞价、午休、零成交/小成交、缺1点、重复时间、量价非法、身份越界和正常数据保护。一次代表性候选批覆盖实际原生空/部分/时间点异常来源；无需逐股票日再请求粗周期对比。另必须验证：只缺5min时15/30/60min无计算输出；只缺09:35时只新增该记录；有效源记录全部字段保持一致；已有异常行不被覆盖；新旧代码不会重复补入；重跑已完成缺失键不重复追加。验证通过后按日批量产候选。

D. 每批最多10个日期，输入文件去重后按≤512MiB拆批，内存1GiB、2线程、禁止spill；每个股票日一次读取，只供该日缺失的周期与窗口使用。候选和追溯只写正式staging根。每个目标日期/周期形成独立候选及checkpoint；失败单元登记，已完成候选复用。落盘时同时计算完整性、行数、OHLC/成交量和父输入一致性，读回候选后证明：新增键集合等于冻结缺失键集合、已有有效记录逐字段不变、非目标周期无输出、重跑无重复；不再次拉源或全湖普查。

E. 本阶段交付仅含缺失记录的聚合候选、逐记录来源清单、已下载有效数据复用清单和最终残留清单；不越层跑Silver/Gold、不清理退市数据。正式Raw提升仍按独立B3阶段确认、逐文件原子替换与实际变化清单执行。

#### 性能预算与本轮证据

预计只需读取9个正式Raw1日期文件，原清单大小225,321,190字节；复用199个1min源缓存页11,935,475字节，另2份已验收单日MCP响应。历史估算的股票日盘中输入上限585,871行，整日展开上限49,445行、205个日期频率目标组；实际输入/输出范围需按缺失键收缩，不把上限当作需要生成的记录数。原生缓存可能含同窗口其他日期，必须按输入清单过滤；文件只读一次并共享计算。此体量无需多日开发或长时间取源，候选计算初估1—5分钟，原生接线、来源清单和一次隔离验证估1—2小时；这些是待首批实测校准的预算，不包括正式Raw全分区合并、提升与下游处理。

本轮可补量统计读取319份旧Raw1紧凑汇总21,021,450字节及当前resolution。首次身份联结执行计划过慢，约90秒中止；改为先过滤源代码与日期、再物化身份映射后1.25秒完成。没有重复扫正式行情。4个既有响应页的逐日分类只补齐此前未落盘的非异常日状态。审计结果保存冻结目录b2-until-accounted-01/step2-capacity：summary.json、refined-summary.json、input-budget.json、execution-classification.parquet/csv及by-stock.csv；refined-summary及execution-classification仅作为缺失键生成的输入，不能作为最终聚合/写入授权清单；summary/by-stock为更早的中间统计。未创建行情候选、未改恢复checkpoint、未写正式数据。


#### 实现不得偏离的例子与验收（2026-09-11管理员确认）

| 已有数据与缺口 | 必须做 | 不得做 |
|---|---|---|
|只有5min整日缺失，其他周期齐备|只补5min缺失记录|计算或覆盖15/30/60min|
|5min只缺09:35，其余时间点有效|只计算09:31—09:35，新增09:35一根|重算覆盖其余5min记录|
|5min已有有效记录，但计算值与它不同|保留已有有效源记录|以计算值替换，或逐字段混合|
|源结果包含多余时间点，但目标端点有效|复用有效源记录，多余记录单列|把整天标成缺失并覆盖|
|1min不齐备|记录无法计算的准确缺口|插值、前值填充或粗周期倒推|
|同一天同时缺5min及30min|共享1min读取，只计算两者缺失窗口|顺便生成15/60min|

验收应将上表逐条转为正向/反例测试。补缺结果合并为“已有有效目标记录＋缺失键上的计算记录”，两者的业务键集合必须互斥；已有异常记录不是自动替换对象。记录来源细化到每一条新增记录，保留输入文件与规则版本。源站比较不属于此阶段执行步骤；数学规则验证一次，真实输入随生成检查，不逐股票日反复拉源对比。

实际计算样本：000979.SZ，2018-07-27，5min曾为空、1min齐备。09:30独立保留，不加入09:35。09:35由09:31—09:35合成：open=1.09、high=1.11、low=1.09、close=1.10、vol=3,190,300+824,400+750,300+696,100+517,940=5,979,040股、amount=6,580,986.50元。随后09:40使用09:36—09:40，依次至10:00使用09:56—10:00。若这些5min中只有一根缺失，就只生成那一根；示例不构成补写指令。

本次仅修订方案文字和执行边界，不开发、不计算候选、不写正式数据；后续实现必须以上述缺失键清单和保护有效源数据的测试验收，不能再沿用“整日重算替换部分源数据”的旧理解。


### 14.30 第2步开发范围与硬口径对账（2026-09-11）

管理员授权：精确补数清单、计算代码及隔离/代表性样本验证。只在staging保存计划和样本，不批量计算、不接入正式Raw提升、不处理下游。新增独立stk_mins_gap_aggregation_plan、stk_mins_gap_aggregation及显式CLI入口；复用RecoveryRun的路径、DuckDB连接、原子文件写入基础，不改变原fetch/build-raw/promote-raw行为。CodeGraph callers确认build_candidate消费者仅现有恢复CLI和测试；Silver聚合消费者为write_silver_stk_mins_partition，均不修改；无前端/API/跨子系统调用新增。正式Raw来源合同集成留到后续正式写入阶段，不能将本次样本完成冒充已集成。

硬口径映射：冻结scope与身份日期频率→清单校验及越界反例；只补缺失键→预期网格减已存在目标键及单点测试；有效源数据不覆盖→原样保存源记录、输出键与源键互斥及值不变测试；四周期直接1min→统一右闭窗口及手算四周期测试；竞价/午休→独立09:30与午休测试；不合成坏输入→241点/量价检查与缺点重复反例；可取消续跑→逐日期产物与完成标记、未完成产物重建、重放复用测试；仅staging→输出根检查及禁止正式路径反例。辅助列缺失不扩增缺口，已有异常记录单列、绝不覆盖。

预算沿14.29：正式Raw1约225MB、缓存约12MB，精确清单仅补读目标部分数据页；原始整日缺行证据复用冻结scope。每日期一个计算unit、批最多10日期/512MiB输入、1GiB/2线程、禁止spill，预计计划/样本各分钟内；单unit完成立即保存结果、来源与checkpoint，取消不领新unit。具体路径、输入清单及状态由冻结manifest与CLI显式参数提供，不新增env或数据库配置；所有消费者为本次两个模块和CLI。源接口请求0。先冻结全量缺失键，随后只选择代表日期跑样本，不进入其余日期。


<a id="minute-gap-exact-aggregation"></a>

#### 第1、2步实施结果与当前停点

本轮授权已完成：精确新增48,763条（5min 2,842；15min 18,836；30min 17,205；60min 9,880），对应5,117单元、335股票、2,429股票日、155日期。旧49,445减4异常单元已有112条、再减部分缺失单元已有570条，得到48,763。114个部分缺失单元实际只补456根30min；580个完整目标数据单元不聚合。精确missing-records.csv与验收见冻结目录b2-until-accounted-01/step2-implementation/REPORT.md。

实现：新增bootstrap/stk_mins_gap_aggregation_plan.py和stk_mins_gap_aggregation.py及tests/test_stk_mins_gap_aggregation.py。第一文件冻结精确缺失键，第二文件仅计算缺失键并保存staging additions和逐记录lineage。旧CLI、正式Raw提升、Silver/Gold不修改，正式schema/catalog没有被本轮代码更改；聚合来源接入正式Raw留到后续独立阶段，不能声称已完成正式来源合同迁移。

原始目标数据的新旧代码副本字段完全一致时，保留全部native_evidence，existing按最新代码优先选已有记录；字段冲突停止。目标键已有但异常则进blocked，不覆盖；网格外记录进extras，不等于全部非法（包含盘后记录），不删除或自动并入聚合。计划保存manifest/scope哈希、全部输入文件指纹和产物哈希。CLI plan验证原RecoveryRun冻结哈希，已有计划直接校验复用；build显式选择≤10日且去重输入≤512MiB。每个股票日只为其缺失窗口计算，不顺便计算其他周期；按日期unit复用读取，多日页使用逐日期选择，不承诺跨所有日期只打开一次源页。

23项新隔离测试与51项既有恢复回归通过，Ruff通过；首次真实staging样本发现自动hive列注入，修正为hive_partitioning=false并增加测试。样本：2018-07-27生成240条；2022-07-15只补4条30min；2024-10-30生成612条，合计856条。新键均在missing集合且与existing互斥；000979.SZ/2018-07-27/09:35实际计算与此前展示数值相同。全部计划输入指纹不变；重放样本完成记录不重新计算，文件哈希相同。取消/未完成日期可重建，last-stop记录停止原因。正式files checkpoint仍为0。

封存计划：/Volumes/datasource/data_lake_staging/stk_mins_gap_recovery/run_id=20260910-v1/aggregation/exact-plan/plan.json；hash=f5bc9bf247e224fbefad80206b271f8169d45893d2a4905887bceeaadb63266a。已执行样本命令（从orchestrator目录）：

```bash
./.venv/bin/python3 -B -m orchestrator.defs.bootstrap.stk_mins_gap_aggregation build --plan /Volumes/datasource/data_lake_staging/stk_mins_gap_recovery/run_id=20260910-v1/aggregation/exact-plan/plan.json --date 2018-07-27 --date 2022-07-15 --date 2024-10-30
```

当前不继续其他日期。后续第3步才批量生成，其次独立第4步接入正式Raw合并/提升；不越层、不处理退市下游清理、不部署、不提交。本轮无新增Tushare请求，没有重新扫描正式全湖；精确清单只补读8个已保存目标来源页，真实样本只读取选中1min输入。测试秒级、样本命令秒级完成；1—2小时是开发与验证预算，不是重复取源等待。

### 14.31 第3步批量生成授权（2026-09-11）

管理员已批准先提交本任务代码，再继续第3步。复用§14.30封存计划，不重新取源或审计全湖；155日期共48,763条中已有3日期856条完成，剩152日期47,907条。通过原build命令显式分批，每批≤10日期且输入≤512MiB，逐日完成记录；仅写既有staging additions。沿用1GiB/2线程/禁止spill，源请求0，预计分钟级，超过10分钟或出现输入/质量冲突即暂停记录。完成后汇总输出键、数量与完成记录，不重复计算行情。正式Raw合并提升、Silver及下游仍是下一阶段，当前不执行。

第3步执行结果：代码提交8a3f0285（89项测试通过）后，16批新增生成152日期47,907条，耗时21.83秒；合计155日期48,763条全部完成。完成标记/文件哈希、输出键与missing双向差集0、与existing重叠0全部通过。没有新源请求，未正式写湖。详见原step2-implementation/REPORT.md新增第3步记录及exact-plan/batch-generation-summary.json。下一阶段为正式Raw合并/提升接入，当前停止于staging生成完成。

### 14.32 第4步：本批计算记录写入Raw（2026-09-11）

管理员明确授权将本批48,763条补入Raw。范围仅封存missing及已完成additions；202个日期频率分区，原文件238,530,035字节，最大3,323,776字节，剩余磁盘约2.9TB。源请求0，逐文件读取/合并，预算沿恢复计划2GiB内存、2线程、禁止spill、单文件≤2GiB，预计分钟级；候选总空间约原文件量加新增行，不生成备份。先全部生成验收，发现身份重叠/已有行/量价或schema冲突即停；不擅自覆盖或清理。

新增aggregation Raw入口；复用现有promote_candidate原子提升，不改原生fetch及build-raw行为。输入是验收后的missing与逐行lineage，状态独立放aggregation/exact-plan/raw-promotion；来源保留aggregated、规则、输入路径与原计划，changes永久保留供后续受影响范围使用，不伪装source-ready。只插入缺失键，不顺带写入缓存原生记录。用原冻结scope.source_candidates检查旧新代码同时间点重叠；保留原文件每列与全部原有行。合并为original UNION ALL additions，逐文件序列化校验通过后记validated；复用promoting/promoted及os.replace、目录fsync和footer读回，已完成不重复写；取消不领新文件。无Dagster instance/event、Silver/Gold、prod、退市清理或部署操作。

CodeGraph callers已核对分钟promote_candidate消费者为恢复CLI及隔离测试（同名指数入口排除），当前函数源码已确认；新增入口仅复用其文件提升协议，无共享资产schema、API或分层依赖变更。测试覆盖保留已有数据、只补目标键、旧码重叠拒绝、候选篡改拒绝、取消及替换后checkpoint中断续跑，先小文件正式提升后续跑全批。执行从orchestrator目录使用现有.venv，参数固定封存计划及原scope；原文件仅在合并时读取一次，不重新审计源行情。

第4步已完成：202个Raw分区全部原子提升，净新增48,763条，保留原有9,296,248条，最终9,345,011条。所有完成checkpoint、物理文件指纹、footer行数及新增键唯一性通过。候选生成32.48秒，首文件提升成功后剩余201文件提升10.59秒。新增5项隔离测试（正常保护、身份重叠、取消/篡改、替换后中断续跑）与Ruff通过。正式目标仅raw/tushare/stk_mins的5/15/30/60周期；无新源请求、无Silver/Gold或Dagster事件变更。验收与实际新增明细分别位于aggregation/exact-plan/raw-promotion/acceptance.json及actual-changed-raw.parquet；这是后续Silver受影响范围依据，不能用全部候选数代替实际提升事实。新增入口与本轮执行记录尚未提交。

### 14.33 沪深优先恢复：三六零旧码、南油日期及转板股（2026-09-11）

管理员授权顺序：先三六零补数，再修正招商南油缺口口径，最后测试另两股旧码。三六零2018-02-28由601313.SH改为601360.SH；原冻结scope遗漏旧码。新增独立冻结子计划，只取601360现有4,239个缺口（899股票日，1min899，其他四周期各835），源候选使用已实测的601313.SH，保留原封存记录。复用freeze_plan/SourceCache/build_candidate/promote_candidate，不改原共享合同、日更或Silver；source-ready才合并，空/部分/异常保留残留，不伪造完整性。Raw保留601313，后续Silver身份统一须先落实正式映射，本轮不执行下游。

预算：4,239分区原库存约13.07GB（1min9.08GB），单文件最大约13.2MB；按既有源窗口1min20交易日、5min100日、其他240日，单页8000、两并发、180请求/分钟、2GiB内存/2线程、禁止spill。源行情预估最多约0.3百万行，约70个窗口，候选新增几十MB，单文件原子替换，约需10—30分钟（以首批校准）；空间沿冻结预算200GiB下限。输出只位于正式staging新run，报告与子计划/private/tmp/shsz-minute-recovery-20260911。源例：601313在2014-01-02已返回241点；最小新增验证为默认字段与范围请求，复用既有分页/失败合同。代码图callers与真实代码已核对，新增执行使用现有CLI，无架构变更。目标已有任何身份行即停，避免重复补写；不重复整湖审计。逐文件合并读原分区并保留全部原有行，提升后footer与指纹读回，变化清单记录tushare_native。原始源无数据不当作补数成功。

南油2014-02-07处于2013-05-14起的暂停上市阶段，应移出待补队列并保留解释证据；不能造1分钟线。泰祥/翰博缺口处于833874.BJ/833994.BJ旧码阶段，最后各做有界旧码请求，空则如实保留，不无限重试。全步骤不写Silver/Gold、事件或Prod，不部署、不自动提交。

## 本轮执行完成（2026-09-11）

1. 三六零：复用既有恢复CLI，以601313.SH为真实源代码建立独立子计划；67个请求窗口得到4,220个原生齐备单元、19个源空单元。19项均有完整1min，按既定规则仅补缺失周期355条。4,239个Raw分区全部提升，新增283,459条（原生283,104、聚合355），原有716,785,512条全部保留。文件状态/物理指纹、前后行数、实际变化键唯一性、与冻结范围双向差集0通过。原生合并提升650.44秒，聚合部分秒级。三六零本批Raw缺口清零；Silver/Gold及正式身份种子/物理映射本轮未改，后续推进下游前须把601313→601360落实到身份映射。
2. 招商南油：将600087.SH的2014-02-07 1min单元标为暂停上市无需行情，保留nanyou-correction.json和交易所依据，不造数、不改原封存清单。更新后的待补清单为remaining-units-v2.csv及股票分钟缺口清单_更新版_20260911.csv。
3. 按管理员要求重试旧代码：833874.BJ查询2021-11-01—11-05、833994.BJ查询2021-11-01—11-03，各请求1min和30min，四次均空，无工具错误，显式字段包含身份/频率/时间/OHLC/量额。并非重跑全部历史，也不以样本宣称其他源无数据。transfer-old-code-probes.json保留完整响应。

以下为当时历史统计，转板股归属和“剩余”含义已由§14.34纠正，不得据此执行：剩余93,310单元、258股票、29,766股票日；按当前市场沪深仅泰祥和翰博两只，共3,100单元（1,555+1,545）。原97,550减三六零4,239减南油误报1，得到93,310。北交所90,210单元未变。所有新报告、子计划和实际变化清单都在/private/tmp/shsz-minute-recovery-20260911。源缓存及原子提升记录在/Volumes/datasource/data_lake_staging/stk_mins_gap_recovery/run_id=20260911-360-alias；原子提升不存在整批回滚，已完成文件可幂等续跑。没有Prod写入、下游写入、Dagster事件、部署、安装或提交。

### 14.34 转板上市日期误判案例与翰博复审（2026-09-11，当前口径）

本节纠正§14.33将泰祥、翰博旧代码阶段列为当前股票缺口的结论。历史请求、恢复凭据保留；旧版CSV不再作为这两只股票的执行清单。管理员本轮授权记录案例并只读复审翰博，不授权补写或清理数据。

#### 案例：泰祥股份301192.SZ

301192.SZ自身上市日期为2022-08-11；旧代码833874.BJ已于2022-07-18退市。此前把旧代码时期311个日期、五周期共1,555项并到新代码，称为泰祥缺口，是错误的。原清单实际标记为“仅根据上市存续区间推测、尚未确认”（lifecycle_only_unconfirmed）；后续报告丢失了这个区别，又把身份延续误当成新代码必须覆盖旧上市阶段。

正确口径：本次泰祥完整性从2022-08-11起判断。此前旧代码时期不要求补入新代码，不因旧代码已退市且源返回空而判当前股票缺数据。若此日起OHLC和成交量及必要分钟记录均完整，泰祥就是完整的。此前已核对五周期最早记录为2022-08-11；本节不把最早日期核验冒充上市后全区间验收。

为避免重犯，后续缺口清单必须同时保留：实际代码及其上市/退市日期、期望起止日期、判定依据、是否仅待确认、正式Raw是否已有、源数据是否仅下载但尚未写入。先按本次确认的上市区间排除不应有行情的日期，再统计真实缺口。Silver身份统一到新代码，不等于向前延长该代码的应有历史。本案例不自动改变三六零纯更名换码等其他情况的已确认处理规则；不全局删除历史Raw。

#### 翰博高新301321.SZ复审结果

本轮Tushare MCP stock_basic实查：301321.SZ为上市状态L，上市日期2022-08-18；833994.BJ为退市状态D，退市日期2022-07-25。因此本轮检查2022-08-18至原截止日2026-09-09，共985个交易日。旧代码阶段309日期、五周期1,545项同样仅为未确认候选，移出新代码应补范围。

| 周期 | 已有数据日期 | 正式Raw记录数（复用逐日审计） | 缺失日期数 |
| --- | ---: | ---: | ---: |
| 1min | 952 | 229,432 | 33 |
| 5min | 985 | 48,265 | 0 |
| 15min | 985 | 16,745 | 0 |
| 30min | 985 | 8,865 | 0 |
| 60min | 985 | 4,925 | 0 |

已有日期的OHLC、成交字段、分钟时间网格检查未发现异常；exchange不参与缺口认定。范围统计复用2026-09-10保存的逐股票日审计结果，不重扫全湖；对33个缺失日逐文件核对当前正式Raw，301321.SZ的1min仍全部为0条。该33日集中在2025-09-18至2025-11-11。

这33日此前已经从Tushare成功下载，只是尚未补入正式Raw。本轮读取保存的两个源文件，逐日验证每次241条、时间点完整无重复、OHLC有效、成交量非负及周期为1，共7,953条通过。无需重新请求或用其他周期计算；下一步可复用这批记录补Raw，但本轮仅审计，未执行写入。

同时纠正“剩余缺口”的统计含义：§14.33的93,310项是当时尚无可用恢复来源的清单，不代表正式Raw全部未补数量，因为已下载但未写入的记录不在其中。扣除上述两只股票3,100项误报后，该旧清单剩北交所90,210项；不能据此宣称沪深正式Raw已经全部完整，翰博这33项就是反例。今后分别报告“不应补”“Raw仍缺但已下载可补”“Raw仍缺且尚无来源”，不得混用。

证据与逐日清单：`/private/tmp/hanbo-minute-reaudit-20260911/result.json`、`raw-check.json`、`翰博上市后Raw缺口.csv`。复核脚本在同目录。33个Raw文件合计约861MB，逐文件仅查询目标代码；源校验只读两个已下载文件。使用既有内存DuckDB、2GiB/2线程、禁spill和显式文件白名单；没有新增分钟源请求、全湖重扫、代码修改、Lake/Prod/Silver/Gold写入或提交。当前仅更新本既有方案，未改变资产依赖或架构边界。

#### 翰博33日Raw补入授权与执行约束（2026-09-11）

管理员已明确要求马上补齐翰博。仅执行本节已审计的301321.SZ、1min、2025-09-18至2025-11-11共33交易日7,953条。复用原冻结scope的33项和原下载两页，在独立子计划中保存原resolution来源；不调用源接口，不扩大股票/日期/周期，不处理旧代码，不写Silver/Gold或Dagster事件。

复用freeze_plan、RecoveryRun、build_candidate、promote_candidate及compact_changed_raw，不改正式代码或共享合同。子计划只含33项，源页复制到独立run并核对摘要；原计划与原下载记录保留。全部33候选先完成原有行保留、范围/身份、schema、主键、字段与序列化校验，再逐文件原子提升；单文件失败停止，可按checkpoint续跑。

预算：1股票、33日期、1周期、33正式文件，原文件合计861,332,436字节；新增7,953条，源请求/分页为0，复用2个源文件。逐文件处理原分区，候选写入约0.9GB；2GiB内存/2线程、禁spill、现有单文件2GiB和剩余空间200GiB门禁，预计1—5分钟，超过10分钟停止领新文件并说明。staging限定data_lake_staging/stk_mins_gap_recovery/run_id=20260911-hanbo-raw，计划和执行脚本位于/private/tmp/hanbo-minute-reaudit-20260911。命令从orchestrator以现有.venv/bin/python3 -B执行apply.py；不访问DAGSTER_HOME。验收检查33文件全部promoted、实际新增键与冻结范围一致且共7,953条、物理指纹及footer与校验候选一致。已有审计和源质量结果直接复用，不重复审计取源。

执行完成：33/33个Raw文件全部校验并原子提升，新增301321.SZ 1min共7,953条，原有43,348,136条保留，最终43,356,089条。候选全部校验完成后才开始正式替换；实际新增键唯一、股票/周期及33日期与批准范围一致，逐文件物理指纹和footer行数通过。全程23.35秒，源请求0，无异常。结合§14.34原有日期审计，翰博本次上市后区间内五周期Raw缺口已补齐。未处理Silver/Gold、Dagster事件或Prod，未提交代码。

子计划hash：d89f0844a421b552e14e5615f951b0b8a8b66e421a3c16784da71b17a9ccce8b。验收：/private/tmp/hanbo-minute-reaudit-20260911/raw-acceptance.json。实际变更清单：/Volumes/datasource/data_lake_staging/stk_mins_gap_recovery/run_id=20260911-hanbo-raw/actual-changed-raw.parquet，后续Silver修复以此为输入范围。上文33天CSV及raw-check.json保留为补前审计证据，不代表当前仍有缺口。

### 14.35 北交所剩余清单复审（2026-09-11）

按管理员要求沿泰祥/翰博案例复审旧清单256只北交所股票。原90,210项拆为19,250项真实缺口（全部有日线正成交量；256股票、14,954股票日、2021-11-15至2024-11-28的171日期）与70,960项精选层时期待确认（67股票、14,192股票日、2020-07-27至2021-11-12）。后者不得继续计入“已确认缺口”，但本轮也不直接判作不应有行情。

实时stock_basic与bse_mapping显示：目标256只均仍上市，无早于当前上市日期项；246只旧码映射与冻结源候选一致。北交所官方代码对照表说明平移股票的上市日期包含精选层挂牌阶段，上市时间连续计算。因此不同于泰祥明确退市旧代码后重新上市的案例；不能擅自把2021-11-15以前全部删除或把920换码日期当历史起点。官方依据：https://www.bse.cn/service/code_mapping.html 与 https://www.bse.cn/important_news/200010914.html 。

另发现旧剩余清单遗漏3项：恒拓开源920415.BJ的2026-05-06/07 15min已下载共34条、Raw未补；中纺标920122.BJ的2024-10-30 5min因保存源记录含非标准时间点而退出聚合，但Raw仍空，需单独核清，不能把271条缓存直接当合格5min。合计本范围确认Raw缺口19,253项，另有70,960项待确认。256股票的原94,671个冻结单元对账为4,458项已聚合写Raw＋90,210项旧清单＋上述3项，数量闭合。

19,250项按频率为1min14,954、5/15/30min各1,347、60min255。2024-11-28集中1,275项；2023年六个日期集中4,368项。其源结果19,249项成功空、1项部分返回，不把请求失败当作源缺失；同花顺停牌证据未产生新增全天停牌排除项。

完整报告和逐股、逐日期CSV：/private/tmp/bj-minute-reaudit-20260911/REPORT.md。仅复用缓存与写入对账，加8个正式文件有界抽核（合计88.49MB）；实时基础信息2请求，分钟源请求0，集合查询秒级。未改正式代码、Lake数据、Prod、Dagster事件、身份映射或原冻结计划；本轮只审计并同步结论，不自动补写。

管理员随后要求将漏列项补入清单：已把上述3项合并至北交所_确认缺口.csv（19,253唯一项）并更新256只逐股汇总，1/5/15/30/60min分别14,954/1,348/1,349/1,347/255项。附表仅保留补列依据，不能重复累加；新增“当前情况”区分源空、已下载未写入、源时间异常。进入北交所前的70,960项历史待确认仍单列。此操作只改审计清单和报告，未补写数据。

#### 漏列3项补Raw（2026-09-11，已获管理员授权）

管理员要求把这3项Raw也补好。范围：920415.BJ 2026-05-06/07 15min各17条，920122.BJ 2024-10-30 5min49条，共83条、3分区；不扩至其余缺口或下游。中纺标核清结果：旧缓存271条中，标准5min网格49条全部存在且OHLCV有效；与已验证1min聚合的OHLCV逐条相等，成交额存在最高0.30元差异，保留原生成交额不覆盖。仅抽取这49条标准时段原生记录，多余222条保留原缓存作异常证据，不能把整份混杂数据写入正式5min。本次不生成计算行情。

复用既有freeze_plan/RecoveryRun/build_candidate/promote_candidate，建立3项子计划。原源页不改，限定后的原生行及筛选规则保存在独立staging，记录原页摘要及筛选数量。3个候选全部校验后原子提升，保留原分区所有行，按checkpoint续跑。源请求0；输入仅两份缓存、3个原分区和小型计划，内存2GB/2线程、禁spill、单文件2GiB及剩余空间200GiB门禁；预计1分钟内，超过5分钟暂停。执行前测量确切文件量；来源逐日网格/OHLCV、既有Raw空缺证据均已完成，不重扫全湖。运行根data_lake_staging/stk_mins_gap_recovery/run_id=20260911-bj-three-raw，报告/private/tmp/bj-minute-reaudit-20260911；仅补Raw，无Dagster事件、Prod或Silver/Gold写入。

3项Raw已完成：原3分区11,162,041字节，新增83条原生行情，保留448,050条原记录，最终448,133条。3候选全部校验后提升，实际新增分别49/17/17条且键唯一、物理指纹及footer校验通过。原271条异常页中仅选49条标准5min，另外222条未写入；未计算或改写源行情值。写后汇总SQL一处别名语法错误已修正，只重跑汇总验收，没有重复写Raw。缺口清单及逐股汇总已移出这3项，当前真实缺口剩19,250项；70,960项进入北交所前历史待确认不变。验收及已补清单位于原报告目录three-raw-acceptance.json、北交所_本批已补Raw三项.csv。子计划hash=805435ca02112f680c10a383cfe0ff08d08a4a60dbd57a9bfd2e427c448a0cba；actual-changed-raw.parquet位于本批staging根。源请求0，未写Silver/Gold、Prod或Dagster事件，未修改正式代码或提交。

### 14.36 Raw→Silver启动口径与审计（2026-09-11，当前授权依据）

管理员明确：退市身份行情仅保留Raw，Silver和下游清除且不得再生成；旧代码退市而新身份存续不能误删。北交所缺口审计从2021-11-15与自身上市日较晚者开始，开市前70,960项暂不再作为缺口；但已有合格Raw无论开市前后均继续下传，不能把审计起点变成数据过滤起点。此规则替代§14.35的待讨论表述。身份等参考事实用于判断退市，不能未经具体范围审计一起删除。本次对象仍为股票分钟修复链。

阶段安排随管理员新要求调整：无需等待北交所19,250项补齐才推进其他部分，按日期批次执行Raw完成→Silver→下游；替代§14.10对全任务Raw完成的全局屏障要求，保留每个批次层级先后及验收门禁。本轮指令为审计可执行性，未执行正式同步或删除。

审计发现沪深Raw尚未全补：原scope/resolution与全部已执行变化清单对账，当前上市沪深股票仍37,098项、250股票、3,000日期已有下载但无Raw落盘凭据；五周期待写分别7,568/7,356/7,441/7,474/7,259项，共14,859日期频率文件。正式Raw抽查招商港口2014-01-02五频旧新候选均为空。此前把来源齐备等同Raw齐备的表述纠正；已执行批次验收不受影响。无需重取源，后续从精确待写范围建立子计划。

已写Raw四组变化中当前上市身份8,967单元，影响944日期、4,686Silver分区（约12.65GB既有文件）；文件级Raw/Raw1/日线/停牌依赖均存在，尚非语义验收。Silver当前仅做身份映射和停牌过滤，没有当前退市排除；历史区间check允许退市前行情，实际Silver样本确有当前退市股。因此先调整writer、check/readiness、依赖及历史/日常共用规则。三六零601313.SH在正式身份表缺失，须补已确认映射。旧Silver恢复器存在湖内_staging和_quarantine备份路径，禁止原样执行；历史入口默认跳过已有文件，也不能直接补个股缺口。复用清洗/诊断，接入现行候选校验、原子提升及checkpoint执行模式，不能冒用BSE专用入口写沪深。

建议先完成上述规则/执行层接线，再按日期合并Raw待写和既有变化，一次生成对应Silver，避免先重写Silver再补Raw造成二次写放大；退市全历史清理另列精确范围。开市前Raw下传如缺日线/身份参考，单列依赖处理，不能跳check。Silver通过后再进入Gold/指标/状态清理重建。

审计报告、37,098项明细与文件检查结果在/private/tmp/raw-to-silver-readiness-20260911/。本轮CodeGraph explore/callers并结合真实writer、checks、历史/离线入口及测试引用核验；完整下游消费者冻结仍属实施前工作。本轮无正式代码、Raw/Silver/Gold、Prod、Dagster事件写入，没有提交或部署。

### 14.37 Raw最终可补范围落盘与验收授权（2026-09-11）

管理员最新决定覆盖§14.36退市删除方案：Silver保留已有退市历史数据，不执行退市数据删除；已退市身份不再统计缺口。三六零映射方案已获批准，但本轮先完成Raw，映射作为随后Silver前置工作保留。验收状态明确为当前存续沪深股票Raw五周期无剩余已确认缺口、北交所开市后仅剩19,250项；北交所开市前与退市股票不进入本轮缺口统计，已有数据不删除。

本轮管理员明确授权执行可补Raw及验收。复用原scope/resolution和已执行变化清单对账，待补只有沪深37,098项（SH11,016/SZ26,082），全部源已下载；北交所19,249源空、1源部分，合计19,250项不擅自造数。精确执行清单/private/tmp/raw-to-silver-readiness-20260911/ready-to-write.parquet。

实测预检：14,859正式Raw分区、66,212,955,324字节，单文件最大32,789,721字节；源缓存684文件40,866,044字节；可用磁盘约2.92TB。源请求0，列式合并保留全分区原行，候选写量约66.3GB，最终仅新增目标股票日。沿用2GB/2线程/禁spill、单批最多20文件且≤2GiB、查询300秒/进程RSS4GiB、剩余磁盘200GiB门禁；先首批实测，初估30—60分钟。每批全部候选校验后逐文件原子提升；中止不领新文件，已完成checkpoint可续跑，不重复扫描源数据或重写已完成文件。

正式代码不改。使用现有freeze_plan、RecoveryRun、build_candidate、promote_candidate；为37098项建立独立子计划，复制已验证源缓存并保留原页摘要、原resolution来源，在data_lake_staging/stk_mins_gap_recovery/run_id=20260911-shsz-final-raw运行。临时编排入口/private/tmp/raw-to-silver-readiness-20260911/apply-final-raw.py，从orchestrator用.venv/bin/python3 -B执行。每批写进度，正式文件仅在合并时读取，候选验收及提升后的指纹/footer不重复重算。最终实际新增scope/键与封存清单双向对账，确认全部文件promoted，再将原未解决范围扣减实际写入，必须得到SH/SZ=0、BJ=19,250方可宣布通过。不以source-ready冒充写入完成；不执行Silver/Gold、身份资产、Dagster事件或Prod写入。

§14.37执行及最终验收完成：37,098项、250股票、14,859Raw文件全部完成，新增2,414,390条，原有3,536,018,722条完整保留，最终3,538,433,112条。耗时3,116.21秒（51.94分钟），源请求0；未发生失败或范围冲突。全部文件promoted、正式指纹/候选及footer一致；新增键唯一、范围双向差集0，37,098单元标准分钟网格完整。按原2014—2026-09-09审计范围及当前确认口径，沪深剩余0；北交所19,249成功空＋1部分返回=19,250，与已交付清单双向差集0。验收是实际Raw写入与既有审计闭合，不以源下载状态替代，不外推到审计截止日后。

最新报告/private/tmp/raw-to-silver-readiness-20260911/RAW_FINAL_REPORT.md，验收final-state-acceptance.json、本批final-raw-acceptance.json，已补明细沪深本批已补Raw.csv。原pending/ready-to-write及“已下载尚未补Raw”CSV保留为补前冻结证据，不代表当前仍待写。子计划hash=99b007e2539751871e124f774b7fbd827ded4f9281bbfdedab287d7a53454979；实际变化清单在本批staging根actual-changed-raw.parquet。后续Silver范围须合并所有实际Raw变化，不能继续使用§14.36补前944日期旧估计。退市删除不实施；已批准三六零映射仍留给Silver前置阶段。本轮无正式代码修改、Silver/Gold/Prod/事件写入、部署或提交。

### 14.38 Raw补齐后的下游审计与补数方案（2026-09-11，仅方案）

本节接续§14.37，替代§14.12与§14.36关于本轮下游范围、退市删除和耗时的旧估计。管理员本轮只授权审计和方案，不执行Silver、Gold、指标、参考资产或Dagster事件写入，不部署、不提交。

#### 口径和本次实测范围

保留退市历史，不做退市数据删除；退市身份不再统计分钟缺口。北交所2021-11-15以前不补审计缺口，但已有合格Raw继续下传；不能把缺口审计起点当成Silver过滤条件。沪深Raw剩余0、北交所19,250项沿用已完成验收，不再次扫描Raw或请求源站。这个结论限于原审计覆盖范围，不代表截止日后或所有下游已经完整。

合并五份实际写入清单：原聚合补入、三六零、翰博、北交所三项、最终沪深37,098项。去重得到46,490个股票×日期×周期单元、584个身份、3,000个日期；实际修改日期为2014-01-02至2026-07-06。保留退市历史，因此本轮传递范围不能再用只保留list_status=L的旧8967单元清单。

| 层级 | 待评估范围 | 含义 |
| --- | --- | --- |
| Silver | 67,914单元；584股票；14,868日期周期文件 | Raw1变化影响五个Silver周期；其他Raw变化影响同周期。文件均存在，既有文件合计57.745GB。尚未计算新旧差异，不等于都要重写。 |
| Gold行情 | 最多90,918单元；533股票；3,085股票周期年文件 | 按现行唯一来源映射展开的上限。2,802年文件存在，共347.9MB；283个年文件不存在，仅为候选范围内路径情况，不是283项新确认缺口。 |
| MACD/KDJ及状态 | 最多2,276股票周期组合，从各自最早变更日向后 | 年路径上界12,148个，已有10,785行情输入文件约1.878GB、相同数量指标文件约4.538GB。路径上界含停牌、退市后无数据年份，不能当作必须新建。 |
| 九转 | 仅Gold30/60/90/120的实际变化组合 | 与MACD/KDJ都须延续到封存的下游截止日；当前状态/九转目录最晚2026-09-11，不能只修到9月9日。目录存在尚非内容验收。 |

本次只读变化清单及明确日期的参考列；正式分钟文件仅查路径和文件大小，没有全湖行情扫描。3,000日Raw1、对应Raw、Silver、日线、停牌文件均存在；相关Raw文件约52.702GB（其中包含多数Raw1），补齐Raw1依赖至3,000日后不能简单把Raw和Raw1体积相加计成本。日线列查询输入约524MB、因子约108MB，参考核对约2.2秒。

#### 已找到的前置问题

1. **三六零映射尚未生效。** 601313.SH在正式身份表没有对应记录，涉及899股票日（2014-01-02至2018-02-14）。本批其他源代码在对应日期均唯一映射且与已验收的最新身份一致。按已批准方案补601313.SH→601360.SH；有效区间须依据既有三六零证据与当前身份表构建器确定。不能扩展泰祥、翰博上市前的应有历史。
2. **参考分区存在不等于股票记录存在。** 本批56股票、341股票日，在Silver日线中没有相同最新代码和日期；Gold候选范围22股票、264股票日没有正数有限复权因子，两组有重叠。按Silver实际使用的停牌条件（S且suspend_timing为空）扣除后，数量不变。920680.BJ各占117股票日。原因尚未定位：不能宣布是分钟源缺口、退市或停牌，也不能用因子1填充。下一步只查已导出的这些键，核对旧/新代码、生命周期以及对应Raw参考数据；不重新审计所有分钟源。日线问题涉及Silver现有check，因子问题影响Gold；分别按层处理。
3. **入口不能直接全量运行。** Silver旧replace-from-raw入口使用正式湖内_staging及_quarantine，不符合当前路径/无备份规则；history默认跳过已存在分区，也不能填个股缺口。BSE恢复器限定北交所，不能冒用到沪深。Gold年写入器及MACD/KDJ写入器也会直接使用目标旁.tmp，不能把这些写入调用直接当作本次候选执行器。应复用计算、校验和合并语义，统一接到湖外候选及逐文件提升；不是重新开发行情公式。

目前适合进入“前置处理与首批验证”，不适合直接发起全部下游补写。存在参考异常的股票日先记录；整文件校验受影响时保留整文件待处理，不能偷偷去掉异常股票后声称该文件完成。其他不受影响文件可先推进。

#### 顺序、输入和结束条件

**B4-0：前置处理。** 输入本次changed.parquet、silver_scope.parquet、bad_identity.parquet、no_daily-not-suspended.parquet及no_factor-not-suspended.parquet。补已批准三六零映射的实现与测试；核清341/264日参考问题并分别列出“已有Raw可同步”“仅旧代码表达”“确无参考待处理”。共享身份事实更新前，审计身份asset、sensor/check、分钟/日线/因子等真实消费者，不扩大映射规则。改变参考数据或检查合同须另获对应执行授权。对齐候选执行器：正式根只读输入，候选仅data_lake_staging，精确范围、已有数据保护、文件校验、os.replace和checkpoint。现成CLI不具备这些完整约束，故本节不提供可误执行的全量命令；实施阶段完成入口和首批验收后，将真实命令补回本节。

**B4-1：先完成Silver。** 按日期聚合所有批次，日内只处理silver_scope列出的周期；每文件只生成一次候选。沿用write_silver_stk_mins_partition及现行清洗：身份归一、停牌、成交单位与价格处理不改。使用output_path_override写湖外候选；输入读取仍指向正式Raw。首批选择10个日期，覆盖三六零旧代码、普通沪深、退市历史保留、北交所已有历史、Raw1影响多周期及只有粗周期变化；必须包含无变化反例。若样本依赖未解，先跑齐备样本，不能将未测场景标为通过。

候选生成时顺带产出新旧差异：逐股票日期周期的新增/变更/删除键、原有有效记录是否保留、被清洗原因。跑现行十项Silver诊断；检查字段异常与“OHLC/成交量缺口”分开报告，exchange等不是本轮分钟缺口统计项。规则要求过滤的行单列原因；出现范围外变化、无依据删除或有效旧值变化时不提升，先解释差异。没有变化的文件直接记为无需写入。合格候选原子提升，记录实际Silver变化清单；失败文件及原因留清单。不得用“分区有文件”宣布个股已补齐。

首批完成后按最多10日期/50文件、候选总量不超过2GiB领批，单进程、2线程、2GiB查询内存、禁spill；每个文件checkpoint，RSS超过4GiB、单查询超过300秒或空闲空间不足200GiB暂停领新文件。候选计算只执行一次，提升后用指纹/footer确认，不再重算公式。首批若每文件耗时超过预算两倍，先调小批次并报告，不同时启动多个大扫描进程。

**B5：再完成Gold行情。** 只能读取已通过B4的实际Silver变化；本次只用现行映射：Silver1→Gold1/5，Silver5→Gold15/30，Silver30→Gold60/90，Silver60→Gold120。单独Silver15变化没有这七个Gold周期的消费者，不因此重建Gold。此任务不引入Gold多来源切换。

按股票×目标周期×年合并所有变更日期，每个年文件最多提升一次。SQL的股票集合和日期集合是交叉过滤，执行器须再以精确股票日期清单限制输出，不能把矩形范围全部替换。复用canonical窗口及复权计算：非1min竞价只并入第一根；Gold30首根10:00、全天8根，保持当前规范。交易日因子及复权基准都须明确；基准与保留的旧年文件不一致时，暂停该股票并列出必须扩展的同基准重建范围，不能混写，也不能擅自跑全历史factor repair。

先10个股票周期年候选，随后最多50个年文件且≤2GiB一批。已有其他日期与股票保持；实际新增/变更范围、主键、窗口完整性、价格和成交字段通过，才提升。仅保存实际Gold变化给B6。参考因子不足的单元不生成假行情，单独挂起。北交所19,250项继续留清单，不因此阻塞所有齐备股票，也不因此伪称下游全齐。

**B6：最后修指标和递推状态。** MACD/KDJ沿用现行计算；九转仅30/60/90/120，比较前4根及已有计数状态沿用现行公式。以每股票周期最早实际Gold变化为起点，使用准确的前一交易日状态/九转上下文，顺序计算至封存截止日（当前目录上界9月11日，先确认该日已完成）。前置状态缺失时，从该股票现有合格历史起点重算，不能任取若干天暖机替代准确EMA/KDJ状态。首次只处理5个股票周期组合；常规按最多20股票、1周期、1年、≤2GiB输入切批，跨年携带已验收状态，日期必须连续推进。

共享日状态及九转文件按本批股票合并，保留其他股票；现有MACD/KDJ局部修复要求共享状态文件已存在，缺失时作为独立问题，不能新建一个只有本批股票的伪全量文件。逐文件候选验收、checkpoint；一次阶段输出清楚记录“指标文件已完成但状态未完成”等中断位置，恢复不得跳过未完成文件。计算公式以既有字面金样本测试验证；生产运行不再全量重算一遍作验证。

**结束对账。** 每层输出已完成、无变化、依规则不产出、参考不足、失败五类，输入单元须全部有去向；不能简单要求Raw新增条数=Silver或Gold新增条数。最终剩余分钟缺口仍按确认的上市/北交所口径统计，并与参考不足单独呈现。抽查行情和九转查询消费者的时间覆盖与missing_row_count，不修改API或前端合同，不继续信号研究。Dagster事件与readiness状态登记独立列明，物理写入成功不等于已登记；本轮不执行事件，后续也不得让状态失败回滚已完成数据。

#### 必要开发、测试与影响面

开发限于身份seed/构建链的已批准三六零映射，以及有界候选编排与checkpoint；优先复用stk_mins.py、stk_mins_qfq.py、stk_mins_qfq_macd_kdj.py、qfq_nineturn.py及已有历史恢复helper。未经审计不直接修改日常asset/sensor或删除旧入口。参考问题如需改清洗合同，另列实际差异，不能临时放宽检查。

必须验证：旧新代码统一且不错误延伸转板上市日期；退市旧数据保留；北交所开市前已有数据不被审计起点过滤；Raw1与粗周期正确扇出；只补实际受影响范围；无变化不写；竞价与午休边界；复权基准一致；年文件非目标日期不变；递推跨年连续与其他股票状态保留；参考不足阻断正确文件；中断/续跑与幂等。复用现有Silver replace、Gold partition rewrite、M9因子repair、MACD/KDJ golden、九转history及readiness测试，新增仅覆盖新编排行为的缺口，不重写公式测试。

本轮已用CodeGraph explore/callers查Silver、canonical Gold、年写入、MACD/KDJ history及九转history，并核对真实代码。CodeGraph调用方结果不全，已用源码引用补查bootstrap、asset/check、readiness、测试和Wealth股票分钟九转查询。后者读取Gold行情与九转，补写会影响其结果，不要求修改返回合同。无跨子系统依赖调整；身份共享事实实施前仍须完成全部直接消费者核验，不能把本轮目标链审计冒称全仓契约迁移审计。

#### 耗时估计与如何校准

本次仅给工程预留，不把未测速度当实测：前置参考核清及执行器接线/测试预留2—4小时；Silver候选与提升预留1—2小时，依据本次约14,868文件、57.7GB既有Silver和上一批Raw14,859文件51.94分钟（Silver多清洗和check，不能直接照搬）；Gold预留20—60分钟；指标与状态预留1—3小时；最终对账约15—30分钟。齐备范围合计约4.5—10.5小时，**不是承诺所有异常都能在此时间内解决**。参考来源确实不存在的等待时间不包含在内。

Silver首10日期测每文件生成/诊断/写入时间及无变化比例；Gold首10年文件测同样指标；B6首5组合测行情行数、共享状态文件次数、跨年时间，再用剩余确切文件/行数更新ETA。指标共享状态写放大目前尚未实测，1—3小时只是预留；超出即报告修订，不能不断重试或压缩验收。新增源请求预计0；若参考修复需要取源，须先给出异常键限定的请求数量，不转为重新拉全部分钟历史。

本次审计产物位于/private/tmp/minute-downstream-plan-20260911：summary.json与inventory.json保存范围和路径；changed/silver_scope/gold_scope.parquet为可复用输入；references.json与reference-classification.json保存参考核对；两份not-suspended清单保存具体股票日；recursive-starts.parquet和recursive-inventory.json用于指标范围。以上是当前方案证据，实施直接消费，不在写前再跑一轮分钟全量审计。正式代码、Lake各层、Prod、Dagster事件均未修改。

#### 14.38前置问题原因补查与优先级纠正（2026-09-11）

上一轮将所有参考异常笼统列为“前置问题”，未先区分当前存续与退市身份，容易误导为当前沪深分钟再次出现缺口，现明确纠正：341个日线参考异常股票日（56代码）及264个因子异常股票日（22代码），按正式stock_lifecycle逐一核对，全部list_status=D；本批没有当前存续代码的这两类参考异常。这些历史日期均位于各自上市至退市前区间，不能说因为日期在退市后被合理过滤。920680.BJ为广道退，退市日2026-01-05，并非当前存续北交所待补股票。

只读300个明确日期的Raw日线/因子参考文件，共37,256,261字节：日线341项中298项同代码同日期Raw已有、43项Raw也没有；因子264项中261项Raw已有有效值、3项Raw也没有。已有身份映射所列其他源代码未找到可替代的同日Raw参考记录。直接执行当前silver_stock_daily_select和silver_adj_factor_select纯SELECT，已证明298/298和261/261均能输出。故这些已有Raw的参考项不需要新算法或重新取分钟源，按现行清洗补入对应Silver参考即可。当前代码使用历史生命周期、并非只保留当前上市股票；这些日期为什么当初未进入物理Silver，尚无历史运行证据，不能断言当前清洗bug、历史删除或某个采集故障。

剩余43项日线、3项因子是本地Raw参考也缺，源站现在是否有尚未请求。本轮保留明细，不影响既有“退市不计分钟缺口”口径，不擅自填因子1或构造日线。建议将这些退市历史的未能下传项单列，保留现有Raw和Silver，不升级为全部存续股票的全局阻塞；若同一日期文件的现行校验确被该项阻断，则暂缓该文件，不跳过check。三六零映射是独立且真实的未落地前置项：seed与正式身份表仍缺601313.SH→601360.SH，按此前批准方案实施；这不是源行情缺失。

本次只读补查，无代码、参考资产、分钟Lake或事件写入。causes.json与daily-causes/factor-causes.parquet保存逐日原因；current-reference-select-verification.json保存现行SELECT的298/261恢复验证，均位于原审计目录。此处的恢复验证是内存SELECT结果，不代表已经写入Silver。

### 14.39 下游步骤1、2执行范围（2026-09-11）

管理员已批准三六零方案并要求先完成步骤1、2。本轮仅增加601313.SH→601360.SH映射（2012-01-16含至2018-02-28不含），更新正式身份表，冻结后续补数清单；不写Silver分钟、Gold、指标、日线、复权因子或Dagster事件。此前关于退市历史向下补齐的安排取消：现有各层退市数据保留，退市身份不进入本轮执行清单，341/264参考项退出处理，不再核实。

身份构建继续用现有seed与build_stock_identity_map_rows；不改schema、枚举、过滤或调用合同。已用CodeGraph explore及实际引用审计seed加载、namechange支持代码、身份构建/check、分钟清洗、源九转归一及其readiness/bootstrap/catalog消费者。namechange中601360本来即属当前上市支持范围，新增seed不扩大其支持股票集合。日线和因子当前使用stock_lifecycle，不直接读取这条映射，本轮不改这两类资产。

执行预算：只读身份/lifecycle/namechange三个小文件和已生成的Raw变化清单；外部请求0、分钟全分区扫描0；正式写入仅身份表1文件，候选在data_lake_staging/stk_mins_downstream/run_id=20260911-steps-1-2。使用现有内存DuckDB2GiB/2线程，查询300秒；不备份或Kopia。先构建完整候选，要求旧行逐字段相同（保留旧created_at），只新增目标映射1行；源代码唯一、生命周期及seed匹配、899个三六零股票日映射完整，换码边界正反例通过。检查后同文件系统os.replace，读回摘要与行数，逐阶段checkpoint。不是重新拉源或全面重建参考数据，预计数分钟内完成。

清单基于§14.38的changed.parquet及其五组实际Raw变更来源，以latest_ts_code联正式生命周期；排除真正退市最新身份，不能按source_ts_code退市标记排除身份延续。遇未识别身份/状态先停下，不能静默丢弃。保留2014起的实际已补范围以及北交所开市前已有合格Raw；不生成北交所19,250项未补Raw的下游任务。记录纳入/排除股票日周期清单、五周期Silver扇出、Gold映射上界、源摘要、身份摘要、计数和范围hash。验收包括分组去重、输入=纳入+排除、无退市身份入选、三六零旧码入选、原始股票日周期范围无扩大、Raw1扇出和Silver15无Gold消费者的负例。冻结结果仅是后续计划，不表示Silver已经写入。

步骤1、2已完成：身份候选完整构建与比对后原子提升，正式表6,152→6,153行，原6,152行全部字段（含created_at）保持不变，唯一新增601313.SH→601360.SH；正式文件摘要0bb087cbec302b2d18f1da4836143c8e104ad6c3d34533f19b0f07c489ae332a。三六零899日期映射无遗漏，2018-02-27能匹配旧码、2018-02-28不能匹配旧码，新码自身映射不变。身份测试14项通过。

冻结清单：输入46,490个Raw变更单元，纳入527存续身份46,065单元、3,000日期；排除57退市身份425单元，二者合计与输入相等。Silver扇出67,489股票日周期、14,868文件；Gold映射上界90,368单元、510股票，须待Silver实际变化后缩减。本批变化清单中北交所开市前存续身份条数为0，未执行任何开市前过滤，也不据此声称此前全量历史数据不存在。北交所19,250待补项没有新建下游任务。

正式冻结目录/private/tmp/minute-downstream-plan-20260911/steps-1-2，plan.json、included/excluded.parquet与CSV、silver_scope.parquet、gold_scope_upper_bound.parquet已只读封存，输入/输出摘要均在计划中，plan_hash=5d2dfd99f25bf31db2c424600970533807b138b15175c23a451cf981bdcb7dfb；completed.json为本轮验收。后续执行必须使用这个存续身份清单，不能沿用§14.38含退市的584股票范围。因正式Silver按全市场日期周期存文件，步骤3即使复用全分区计算，也必须按冻结股票日期周期合并候选，保留所有范围外原行，不能顺便把本轮已排除的退市Raw新记录传入Silver；若现行全文件check阻断，记录待处理，不放宽检查。

本轮修改仅身份seed、对应测试及本既有设计；正式Lake只更新身份表1文件。Silver分钟、Gold、指标、日线、因子、Prod及Dagster事件写入均为0，无部署、提交或分支切换。身份表物理完成不等于DG事件已登记，状态登记留在后续授权阶段。候选校验曾发现staging目录被DuckDB自动解释为额外分区列，已在候选读取明确hive_partitioning=false后通过，未发生错误候选提升。

### 14.40 步骤3 Silver分钟执行（2026-09-11）

管理员已授权推进步骤3。只消费§14.39封存清单，保持527存续身份、67,489股票日周期、14,868文件边界；不写Gold/指标/退市历史或DG事件。执行脚本在/private/tmp/minute-downstream-plan-20260911/step-3，候选data_lake_staging/stk_mins_downstream/run_id=20260911-silver。复用_create_silver_stk_mins_base_tables、_create_silver_stk_mins_final_rows和_write_distinct_silver_stk_mins_rows，无算法改动；先按映射与清单抽取Raw源行到候选区，避免全市场重算。1min后续按日期缓存已选范围供多个周期共享。只新增正式Silver缺少的(ts_code,trade_time)键，已有原行全部保留，不以整股票日替换已有行情；若既有无效行导致正式检查失败，记录并停该文件，不静默覆盖。

首10日期50文件候选验证完成，尚未提升；正式十项诊断在有新增的候选上全部通过，无变化文件保留原样。首日中国平安601318.SH 30min已有7条成交额与当前Raw相差1—7元，OHLC/成交量一致。差异记录保留，按“已有有效数据不覆盖”原要求只补缺失键，不改这7条；不引入新价格/金额容差规则。首个1min候选新增三六零/招商港口/招商积余各241条，共723条，旧行不变。

计算连接2GiB/2线程/禁spill、300秒上限；正式诊断复用现有函数，其内部仍使用仓库默认16GB/4线程连接上限（串行逐项、当前候选单文件小于33MB），不能声称该函数内部已支持2GiB参数。本轮不改全局连接合同；进程RSS4GiB及空闲空间200GiB门禁继续适用，正式逐文件候选/原子提升/checkpoint。首50文件候选累计约20秒，粗估全量约1.5—2小时，按后续实际新增/无变化比例更新。先保证首批通过，再继续；每文件记录新增键和状态，失败单列。无变化不重写，提升后核对已验收候选摘要，避免重算公式。源请求0，不重扫原Raw缺口清单。

步骤3于2026-09-12完成：14,868文件全部处理，13,635个合格候选已原子提升，1,233个无变化不重写，失败0。新增2,670,999条（1/5/15/30/60min分别2,048,500/400,428/140,845/40,716/40,510）；实际变化252股票、3,000日期、37,583股票日周期，其余275股票本轮无新增。正式批次耗时6,305.77秒，约105.10分钟，符合首批修订的1.5—2小时预算。

验收：所有补写候选通过正式十项诊断，原有全行保留；新增键重复0、与冻结范围差集0；只读本次生成结果确认67,489/67,489股票日周期标准分钟网格齐备，待解释0，没有重新扫描Raw。源请求0，退市历史下传0，Gold/指标/Prod/参考行情/DG事件写入0。验收文件/private/tmp/minute-downstream-plan-20260911/step-3/acceptance.json、coverage.json及REPORT.md；逐文件checkpoint在本批staging。实际Silver变化已合并至data_lake_staging/stk_mins_downstream/run_id=20260911-silver/actual-changed-silver.parquet，后续Gold只能从此变化清单展开。

本次正式代码未新增或修改；临时执行/验收脚本与报告在上述目录，本既有设计同步结果。CodeGraph及真实代码核对到Silver清洗、BSE候选保留策略和十项诊断，未调整资产/schema/跨子系统依赖合同。未提交、部署或进入步骤4。北交所19,250项仍是Raw待解决范围；Silver本次完成不应表述为全湖无缺口，也不等于DG物化与检查事件已登记。

### 14.41 下游步骤4、5执行（2026-09-12）

管理员批准继续补Gold及MACD/KDJ、九转和递推状态；不登记Dagster事件、不提交或部署。只消费步骤3实际变化清单：映射后Gold共50,494股票日频率单元，690股票频率年文件，其中584已存在、106待新建；已有目标约250.8MB。1/5/15/30/60/90/120min分别8,500/8,500/8,172/8,172/4,524/4,524/8,102单元。Silver15不扇出Gold。清单落在/private/tmp/minute-downstream-plan-20260911/steps-4-5。

逐日期/源周期读取正式Silver，多个目标周期共享本次读取；沿用canonical聚合和复权公式，在staging生成候选，按精确股票日替换Gold年文件，非目标日期保持不变。使用当前正式因子；首10个已有年文件的收盘价反推基准均与最新因子一致。候选仍核验目标范围内原有价格的基准一致性，有不一致先记录并停止，不擅自扩大至全股票复权修复。新年文件允许创建。计算2GiB/2线程、300秒单连接上限、每批检查空间、逐文件checkpoint及原子提升；不重复Raw审计或源请求。

Gold完成后按实际变化冻结指标起点和既有状态终点。MACD/KDJ按精确前态递推，九转沿用现有公式；分股票频率/年计算，再按日期合并共享状态，保留其他股票。缺前态不得用任意预热天数代替，缺状态文件不得生成部分股票状态冒充完整分区。首批Gold和首批指标通过后按实测速率更新原20—60分钟及1—3小时预算。各层物理结果与Dagster状态登记分开交付。

步骤4中途停止记录：10,636个日期源周期候选已全部生成；已提升382/690个年文件，新增或更新2,393,428行，382个正式文件摘要读回全部一致。601360.SH的2017年5min文件未提升：13个日期（2017-12-01至12-20）134条已有close与候选不一致。逐条有界核对证明，旧值全部与Silver原生5min close按当前因子调整后的值相等，候选全部与Silver1 close按相同因子调整后的值相等。复权基准相同，差异是周期源价格；仅凭数值吻合不能断言历史生成执行来源。

例如2017-12-01 10:00，Silver1 close=51.55、Silver5 close=51.56，同一倍率0.9424621707453763得到候选48.58392490192415、旧Gold48.59334952363161。当前规则仍是Gold5←Silver1。建议继续按canonical定义修正本次受影响日，并把已有价格变化明确列入结果；不放宽容差、不改Raw/Silver、不扩大范围。按异常停止约束等待确认；后续未验收文件是否还有同类差异尚未知。步骤5未开始，指标/状态/DG事件写入0。已通过文件保留，续跑复用候选/checkpoint，不重扫源缺口。

证据与暂停报告：/private/tmp/minute-downstream-plan-20260911/steps-4-5/REPORT.md、gold-interrupted.json、gold-difference-trace.json；逐条差异在原staging/merge-5-601360.SH-2017/price-differences.parquet。公式16项及9个子测试通过，分区替换和指标历史回归37项通过。本轮临时编排脚本未成为正式入口，未修改计算公式、资产/schema或依赖边界，未部署、提交。

2026-09-12管理员确认按上述建议继续：在既定股票日范围内，按现行canonical来源修正已有Gold价格，逐文件保留旧/新价格差异，不以差异本身阻断，也不放宽价格容差。复用已生成候选及382个已完成checkpoint，继续剩余Gold，再执行步骤5。Raw/Silver不改，Dagster事件仍不登记。

续跑结果：Gold690/690文件全部提升并通过摘要、实际变化键唯一及冻结范围核验，共2,699,871条新增或更新。已有close实质修正仍仅三六零2017年5min的134条；未发现其他close差异。指标按实际Gold键冻结491个股票频率组合，终点2026-09-11；交易日历3,088日期对应七频率状态文件均存在。首5组合、43年批次17.35秒完成候选计算，2,205,391条指标及9,281条状态通过范围、非空有限值、唯一键及状态末值一致性检查。全批继续复用首批候选；正式提升前统一验收，按共享日期文件合并一次，保留其他股票。

步骤4、5最终验收完成（2026-09-12）：235股票、491股票周期组合。Gold690文件已补写；MACD/KDJ年批次3093个，提升2691、无变化402、无数据0；每日状态21616个，提升21616、无变化0、无数据0；九转日期文件12352个，提升9609、无变化2743、无数据0；失败0。候选70,132,245条指标、660,778条状态、650,858条九转与处理行数对平；终点2026-09-11。所有提升文件已在写入时完成摘要读回，最终对账复用记录，不重复扫源。53项公式/回归及9个子测试通过。

指标全批计算续跑563.92秒（另首批17.35秒），正式处理1175.86秒。已按确认口径修正134条三六零已有收盘价；Raw/Silver、退市历史、Prod、DG事件均未改动。本批不修改计算公式或依赖边界，未提交/部署。结果报告与最终验收在/private/tmp/minute-downstream-plan-20260911/steps-4-5/REPORT.md、FINAL-acceptance.json。北交所19,250项仍待补；下一阶段才处理DG事件与状态登记。

### 14.42 步骤6 DG登记与状态刷新（2026-09-12）

管理员要求继续下一步，沿用上一轮明确的DG登记阶段授权。本步只追加正式Dagster事件，不启动job/sensor，不改动态分区，不重写Lake或Prod，不提交/部署。先只读dry-run，再小批登记和只读验收；既有数据验收直接复用，不重做Raw/源站审计。

从步骤3及4/5的实际提升记录得到30资产、84,749个资产日期候选。5.53秒完成首轮控制面查询；核对发现正常check记录可能没有直接partition，但能通过target materialization定位日期，已据此修正SQL并完成结果核对，不能把这类记录误报为缺失。所有候选日期已注册且已有物化记录。历史已有物化事实无需为了此次局部更新重复补录84,749条；更不能把缺失的历史检查自动扩入本次登记范围。

沿用现有递推修复最近20个交易日的登记规则：2026-08-17至2026-09-11，七周期MACD/KDJ及状态共14资产、280资产日期。Silver、Gold行情和九转实际变化最晚分别2026-07-06、2026-07-06、2026-07-09，不进入这个近期窗口；历史物化记录保留，本步不声称它们已获得重新检查或逐日刷新。本次另登记步骤1已经变更的silver_stock_identity_map快照1项。总上限281条物化+563条正式check=844事件；不增加check名称、不扩大检查合同。

近期560项现有检查均为SUCCEEDED且关联各自原物化，本次是对补数后文件刷新验收和登记，不是修复560个红灯。复用audit_stock_indicator_state_partitions按周期一次检查20日期；560项全通过，合计计算约31秒。该函数使用既有16GB/4线程配置；只投影计数、身份与时间等字段，七周期声明文件合计约32.85GB（这是文件总大小，不是实读字节），最大单周期1min约23.08GB，实测RSS峰值约1.21GB。没有重算指标公式。身份表与步骤1摘要一致，三项完整正式检查全部通过。

执行器和证据位于/private/tmp/minute-downstream-plan-20260911/step-6。冻结plan.json（资产/日期/检查结果/证据摘要）后，先登记一个30min资产日期，核对物化和两项check的分区、通过状态及target storage id，再按最多20资产日期一批续跑。每个追加事件记录checkpoint；恢复先读取本计划已有事件再续写，防止写入成功而checkpoint未完成造成重复。每批上限60事件，全计划硬上限844；检查必须关联本计划对应新物化。使用现有正式DAGSTER_HOME，不初始化、升级或清理instance；不用旧P9删除check索引的逻辑。暂停只保留已追加事件，绝不回滚已补物理数据。

最终只读核对计划内281物化、563检查、分区及目标关联；并核对正式任务未被启动。北交所19,250项Raw缺口继续保留，不因登记变成全湖齐备。CodeGraph explore及实际代码已核对现有BSE事件、P9纯检查、catalog和SDK调用链；本次临时编排复用现有检查语义，不修改正式入口、资产合同、计算公式或依赖矩阵。

步骤6完成：首个30min分区3事件读回通过，随后20项及260项续跑；总计15资产、281条物化、563条检查、844事件，与冻结上限完全一致。正式check索引563项全部SUCCEEDED，全部关联本计划对应新物化；281个目标的最新物化ID逐项核对一致，重复0。本计划run_id未创建Dagster job run。原84,749候选中，近期280项已刷新，其余84,469项保留既有历史物化，不声称历史check已补齐。身份快照为额外1项。plan_hash=57c690d1d00e5359f9d36cee32cfa9add4b9f8e9baeadde3e830c33a943d7c5f。

执行中一次在写前检测到短暂活动任务而停止，任务自然结束后续跑，未停止或调整调度。首个物化写入后发现事件序列化用metadata_entries、check事件的event_logs.asset_key可为空，临时读回器改用Dagster自带反序列化并按本批run_id定位check；已写事件直接复用，没有重复追加。5项隔离验证覆盖检查目标、失败拒绝、错误关联拒绝、不完整拒绝及冻结规模；首批真实读回和最终正式索引验证通过。后两批登记耗时2.68秒及29.74秒，最终只读对账约1秒。临时执行器不成为日常正式入口，未改全局配置、公式或资产合同。

最终报告为/private/tmp/minute-downstream-plan-20260911/step-6/REPORT.md，acceptance.json记录上述对账。当前阶段物理补数及近期DG状态刷新完成；北交所19,250项仍待外部数据源解决。Raw历史事件、历史全量check补录没有自动纳入此阶段。未提交、部署、写Prod或重写Lake数据。

### 14.43 三只退市股票仅补Raw（2026-09-12）

管理员重新明确并批准：精伦电子600355.SH、立方数科300344.SZ、长药控股300391.SZ补齐Raw，Silver维持现状，Gold及指标不联动。三只分别退市于2026-04-27、04-22、04-13，仍按既定口径不计存续股票缺口；这不等于Raw可以遗漏已取得的数据。上一批Raw按list_status=L筛选，把这三只已经下载齐备的数据留在范围外，本轮纠正这个范围遗漏，不修改股票身份或退市日期。

只消费/private/tmp/three-stocks-minute-gap-20260912/remaining.parquet的42,282单元：精伦14,614、立方14,164、长药13,504；覆盖1/5/15/30/60，2014起至各自已取得源数据的交易日，最晚2026-04-21。每只2024-10-30的15min已补17条，明确排除，保留已有全部Raw行。原完整扫描逐项0行证据、五批写入差集及30文件物理抽核已完成，本次不重复审计。638份源缓存全部存在且此前完整网格/OHLC/vol检查通过，没有新的Tushare请求。

CodeGraph explore和实际stock_mins_silver_sensor代码核对：日常Silver仅对expected_trade_dates末10日做readiness和派发；股票分钟资产没有automation_condition，注册sensor不启动Silver任务。本批2014—2026年4月历史不进入当前日常窗口。直接Raw原子提升没有DG物化事件或run-status触发，本轮也不登记任何DG事件、启动job、修改sensor或动态分区。未来如果另行人工重建这些历史日期，仍可能读取已补Raw；本轮不改变该历史重建合同。记录全部14,944个对应Silver文件的inode/size/mtime，完成后只比对文件状态，证明本批未改Silver，不读取其行情全表。

性能与执行：14,944个现有Raw文件，合计55,216,326,784字节；638缓存合计43,024,039字节；当前空闲约2.94TB。复用freeze_plan/RecoveryRun/build_candidate/promote_candidate，原逻辑完整保留旧行、全候选校验、同盘os.replace、逐文件checkpoint。临时编排位于上述报告目录，独立stage=data_lake_staging/stk_mins_gap_recovery/run_id=20260912-three-delisted-raw。2GB/2线程、禁spill、300秒查询上限、4GiB RSS门禁、至少200GiB剩余空间；每批最多20文件且输入合计≤2GiB。源请求0、Prod写入0，候选单文件提升，不建立备份或Kopia快照。仅复制43MB源下载文件到本run隔离目录以复用现有路径约束，不复制正式Raw作为备份。

先20文件真实构建/校验/提升，再根据实测速率继续；按既有同类14,859文件51.94分钟经验，本批预计40—60分钟。候选异常立即停，不覆盖已有有效数据，不自动补Silver。成功文件直接续跑，未完成候选保留；最终用实际新增键与42,282单元双向差集、分钟网格和逐文件提升指纹验收，复用写入时完整校验，不重新扫描全Raw。完成后更新本节及原三股报告。无正式算法/配置/依赖修改，不提交或部署。

本批已完成：14,944/14,944个Raw候选通过完整校验后原子提升，新增2,714,646条；原有3,674,385,646条全部保留，合计3,677,100,292条。三只分别新增：精伦938,266条（14,614单元）、立方909,376条（14,164单元）、长药867,004条（13,504单元）。42,282个股票日周期与冻结清单双向差集0，新增键唯一、标准时间网格缺失0，失败0；本次批准清单剩余0。此前各股票2024-10-30的15min原有17条未重新写入。638缓存直接复用，源请求0。

首20文件7.04秒，续跑及Raw对账3,413.22秒，合计约57分钟，符合40—60分钟预估。恢复流程30项隔离测试通过；逐文件提升指纹通过。最终仅读取本次新增键和已有验收记录，不重复全Raw审计。对应14,944个Silver历史文件的device/inode/size/mtime_ns与写前全部一致，Silver变化0；无Silver/Gold/指标执行、无DG事件或Prod写入，未修改日常sensor配置，未提交/部署。

plan_hash=947f252ab4f61148ad232a896e20a4e51950ee20a8fb3a973ecf4411943cafa5；正式写入清单为data_lake_staging/stk_mins_gap_recovery/run_id=20260912-three-delisted-raw/actual-changed-raw.parquet。最终报告和验收位于/private/tmp/three-stocks-minute-gap-20260912/REPORT.md、acceptance.json；remaining.parquet、summary.json及ready-to-write.parquet保留为补写前冻结依据，不再代表当前待补。后续统计这三只必须计入本批实际写入清单，不能再次仅减去此前五批变化而误报42,282项。Silver及下游保持原状，此完成事实不得作为自动下传三只退市历史的授权。

### 14.44 三只股票的 Silver 历史保持规则（2026-09-12）

管理员已批准：精伦电子（600355.SH）、立方数科（300344.SZ）、长药控股（300391.SZ）的 Raw 继续保留、允许补齐；Silver 1/5/15/30/60 分钟不新增、不重算，已有记录原样保留。本规则覆盖全部历史日期，不自动扩展到其他退市股票，也不改变 Gold 或指标的计算定义。

实施约束与配置审计：

- 唯一名单为版本控制内 `defs/run_contracts/stk_mins_silver_policy.py` 的 `SILVER_STK_MINS_FROZEN_CODES`，默认且固定为以上三个最新身份；不是环境变量、数据库配置或 CLI 开关，没有运行时绕过参数。名单调整须重新批准并更新本节。正式进程加载新版代码后生效。
- 在身份映射后，统一排除目标周期 Raw 与参与计算的 Raw 1 分钟输入；不能只过滤目标周期，否则 1 分钟兜底会重新生成被排除的股票。
- 公共 `write_silver_stk_mins_partition` 写入前，从该日期、周期的正式 Silver 文件读取名单内旧记录，与其他股票的新计算结果合并。正式文件不存在时不生成这些股票。候选输出路径不能改变旧记录的读取位置。重复主键的旧记录阻止写入，不允许去重后悄悄改变历史。
- 日常资产、历史导入、从 Raw 重建和北交所恢复均调用上述公共函数，无独立名单；Raw 写入、身份映射规则、传感器调度和 API/CLI 不变。引用覆盖、结构、主键与数值检查继续检查已有 Silver，不要求这三只新增 Raw 出现在 Silver，也不豁免旧记录的质量问题。
- 物化元数据展示规则版本、目标源排除行数、1 分钟源排除行数和保留旧行数；资产目录注明历史保持规则。没有新增面向行情用户的配置。

影响面通过 CodeGraph `codegraph_explore` 与真实调用引用交叉核对：公共写入函数的调用方是分钟资产、`stk_mins_silver_history`、`stk_mins_silver_replace_from_raw`、`stk_mins_bse_history_recovery`。不改变跨子系统依赖；Gold/指标仍消费既有 Silver。

验收：五个周期分别验证原生输入和 1 分钟计算不生成名单股票；已有 Silver 全字段不变；缺少旧文件时不生成；候选输出也从正式 Silver 保留旧值；其他股票（包括名单外退市身份）正常处理；旧代码映射后按最新身份过滤；重复旧主键报错且不改原文件。运行现有 Silver、历史重建相关回归。仅用一个日期的必要文件做真实只读验证，不重复全湖审计。

性能边界：每个日期/周期额外只读一份既有 Silver 的名单内记录，不扫描其他分区；不新增源站请求，不做全历史内存聚合。沿用已有 DuckDB 内存/线程治理。当前阶段只修改代码、测试及本文，不执行正式重建、写湖、事件注册、部署或提交。

本节实施结果：公共入口已落实输入过滤、旧记录保留及运行计数；资产目录和隔离测试启动器同步完成。新增 4 项测试覆盖 20 种五频率组合及身份、重复主键、精确名单；加上 Silver 合同 20 项、历史重建 8 项、从 Raw 重建 7 项、readiness 20 项、北交所恢复 26 项，共 85 项测试通过。专用隔离启动器阻断正式资源访问。文档完整性与 `git diff --check` 通过；Ruff 新文件通过，既有分钟资产文件仍有 7 条与本次无关的历史告警，未扩展清理。

真实只读验证：2024-10-30，6 个明确文件合计 44,497,812 字节，内存 DuckDB 2GB/2 线程、禁止落盘溢写、只允许所列文件访问。1 分钟排除 723 行，5 分钟排除 147 行，过滤后名单内均为 0；当天两份 Silver 原有名单记录均为 0。所有输入文件大小和修改时间不变。证据 `/private/tmp/verify-silver-freeze.json`；旧 Silver 有记录的全字段保持由上述隔离样本验证。本轮无正式数据写入、部署或提交，正式 DG 进程尚未执行新版代码重载。
