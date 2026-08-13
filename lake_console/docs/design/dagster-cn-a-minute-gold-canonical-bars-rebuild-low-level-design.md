# A 股分钟线 Gold 标准 K 线合同与历史重建 LLD

更新时间：2026-08-13

状态：**P0 轻量只读审计、P1 共享合同/金样本、P2 指数 Gold/消费链代码、P3 股票 QFQ/指标重建代码和 P4 临时 Lake/真实性能门禁均已完成。P0-P4 没有修改正式 Lake、Dagster event 或 sensor 状态；两个新增指数 Gold sensor 均保持 `STOPPED`。下一步是单独审批 P5 正式运行冻结，不能直接写正式 Lake。**

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
8. bars 与 indicators 的业务匹配键固定为 `ts_code + freq + trade_date + trade_time`，任何读取端都必须严格按该键对齐。
9. `15:01-15:30` source 时段只允许保留在 Raw/Silver；不得进入任何 Gold bar、任何其它
   行情 bar 聚合、任何技术指标或递推 state。
10. Gold 1m/5m/15m/30m/60m/90m/120m 的最后一根 bar 均固定为 15:00。

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

90m/120m 先做 candidate 与现有正式文件的批量统计等值审计：

1. 按稳定批次对账 row count、key hash、规范化 value hash，并抽样核对边界日期、SH/SZ/BJ
   和首尾窗口；键、OHLC、vol、exchange 精确一致且 amount 绝对误差不超过 `1e-6` 时，
   不重写历史文件，只切换代码 source 合同。
2. 任一计数、键、非 amount 业务值或超容差 amount 存在差异时停止；单独输出差异报告并
   回到合同 Review，禁止扩大容差绕过真实数据问题。

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
7. 90m/120m 只有在第 7.2 节发现 QFQ 内容差异时才进入重建；否则保留现有内容并做全量 key/hash 对账。

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
2. `stk_mins_qfq_history.py` 新增
   `rebuild_stk_mins_qfq_canonical_history(...)`。默认只重建 5/15/30/60，按
   `freq + stock-year` 有界处理，完整生成 candidate 后再执行既有原子替换；checkpoint 使用
   plan fingerprint 和原子 JSON 替换，计划变化或已完成目标文件缺失时 fail closed。1m 后续
   只允许通过 P7 精确计算出的 affected date/code 范围调用，禁止全市场无差别重建。
3. `stk_mins_qfq_derived_history.py` 新增
   `audit_stk_mins_qfq_derived_canonical_equivalence(...)`。90m/120m 按 `freq + year`
   使用 DuckDB set-based SQL 对比现有 Gold 与 Silver-direct canonical candidate 的 row count、
   key hash、规范化 value hash、missing/extra key 和值差异。键、OHLC、成交量和交易所必须
   精确一致；`amount` 仅允许 DuckDB 并行浮点求和造成的绝对误差 `1e-6`，超过即停止，
   不能自动重写。
4. `stk_mins_qfq_macd_kdj_history.py` 新增
   `rebuild_stk_mins_qfq_macd_kdj_history(...)`。5/15/30/60 默认按 `freq + year`
   严格日期顺序重建 indicator/state；跨年批次必须读取上一 expected trade date 的精确 state，
   不再使用“任意更早 state”。1m affected codes 可按共同最早受影响日期分组后通过显式
   `stock_codes` 范围执行，未受影响代码不进入重建范围。checkpoint 与计划、频率、日期和代码
   scope 绑定，断点续跑时缺少 indicator/state 目标会 fail closed。
5. `stk_mins_migration_cli.py` 新增两个仅供显式维护的入口：
   `rebuild-gold-qfq-canonical-history` 和
   `rebuild-gold-stk-mins-qfq-macd-kdj-history`。两者都强制提供 checkpoint 和
   `--confirm-rebuild`；指标入口可显式传受影响 `stock_codes`。本阶段仅完成代码和临时测试，
   没有运行这些正式重建命令。
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
   `1.862645149230957e-09` 尾差，原精确 DOUBLE 比较在 12 次重复查询中误报 2 次。门禁现
   固定为键/OHLC/vol/exchange 精确一致、amount 绝对误差不超过 `1e-6`；`1e-9` 正例和
   `1e-3` 负例测试均通过，业务公式没有改变。
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

### P7 股票 QFQ 正式重建

顺序固定：

1. 先按 P0 affected code/date scope 生成 1m candidate，删除 `15:01-15:30`，审计后替换。
2. 完成所有 5m candidate stock-year 文件并审计，再逐文件原子替换。
3. 依次处理 15m、30m、60m；前一频率全量通过后才进入下一频率。
4. 每个 stock-year 替换均为完整文件，进程中断后按 checkpoint 幂等续跑。
5. 90m/120m 运行批量 row/key/规范化 value hash、amount 容差对账和代表性抽样，不默认重写。
6. 所有受影响 QFQ 范围通过后，才允许进入指标重建。

不使用 Kopia。恢复事实来自未修改的 Silver + adj factor + 已冻结代码版本；任何失败都停止
Web 和 sensors，修正后从 checkpoint 重新生成，不让业务读取半完成版本。

### P8 股票指标与 state 正式重建

1. 先对 1m affected codes 从各自最早受影响日期顺序重建。
2. 再按 5m、15m、30m、60m 逐频执行全历史重建。
3. 每个频率按 expected trade date 严格升序生成 indicator 和 state。
4. 每日完成后校验 exact previous state、bars/indicator keys 和 output rows。
5. 一个频率从 baseline 到 frontier 全部通过后，才进入下一频率。
6. 不允许 daily sensor 与 rebuild CLI 同时写同一频率。

### P9 事件补录

物理文件全量对账通过后才补 event：

1. 新增指数 Gold bars 全历史补 materialization event。
2. 重建的主要指数 technical/state 和股票 QFQ/indicator/state 全历史补 materialization event。
3. blocking check event 只补各自专属分区最近 20 个 expected trade dates。
4. 每条 event 必须带正确 partition，不写 multi-partition 聚合 check。
5. 不伪造未执行过的历史公式 check，不删除旧 run/event。
6. event 补录完成后重新验证 latest materialization 与 latest-bound check。

### P10 业务读取切换

1. 指数 reader 从 Silver bars 切到 Gold bars，无 fallback。
2. 股票 reader 路径不变，但必须等 QFQ 和 indicators/state 全部完成。
3. 启动本地 Web 前运行全量业务合同审计。
4. API 分别抽查七频，验证非 1m 无 09:30、首根时间正确、bars/indicators 时间键一致。
5. 浏览器检查 K 线和 tooltip 时间、OHLC、指标严格同轴。

### P11 Sensor 恢复与观察

按依赖顺序逐个启用：

1. 现有 Raw/Silver 链。
2. 指数 Gold bars sensors。
3. 主要指数 technical sensor。
4. 股票 QFQ daily/factor repair sensors。
5. 股票 MACD/KDJ daily/repair sensors。

至少观察连续 3 个实际交易日，记录 first-not-ready、run key、耗时、文件数、cursor 大小和
partitioned event。任一环节错误立即停止对应 sensor，不靠自动覆盖修复已 materialized 文件。

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
5. candidate 只能写 `/Volumes/datasource/data_lake_staging`，验证后同文件系统 `os.replace()`。
6. 任何磁盘不足、重复扫描、单批超预算、源文件变化或 fingerprint 漂移立即停止。
7. 报告写 `/private/tmp`，不把逐行结果写 Dagster metadata/cursor。

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
6. 股票 90/120 candidate 与现有文件按批次 row/key/规范化 value hash 和 amount 容差等价，
   且代表样本相等。
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
11. bars/indicators 时间键全量一致，API 和前端不补、不猜、不错位。
12. materialization 全量、check 最近 20 日、partition 归属和 latest binding 正确。
13. 日常 sensors 连续至少 3 个实际交易日稳定，无 RPC timeout、重复 run 或错误覆盖。

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
