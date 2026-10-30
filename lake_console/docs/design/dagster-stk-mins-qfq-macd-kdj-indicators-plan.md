# M12: Gold stk_mins qfq MACD/KDJ 指标资产设计方案

> 2026-10-30最新状态：方案及实现分别以`4a4a689e`、`5a0b13401`提交，315项测试及23项子测试通过，独立实现审计未发现阻断。之后获准通过原job只恢复29日1m，run`63c25bed-bdc8-4fee-9af8-0321b5b13ac7`已SUCCESS，两项物化及四项检查通过，耗时154.728秒；其他六频未重跑。开发验收见[LLD第19.12节](dagster-stk-mins-qfq-staging-write-plan-and-low-level-design.md#1912-开发隔离测试与实现对账2026-10-30)，正式结果见[第19.14节](dagster-stk-mins-qfq-staging-write-plan-and-low-level-design.md#1914-29日1分钟恢复执行记录)。原4GB报错的日更准备阶段本次真实通过；历史repair计算组织仍留待后续处理，2股历史repair未执行，其sensor按批准暂缓并保留原cursor。

> 2026-10-24 写入安全修正已获授权，细节见[方案和LLD](dagster-stk-mins-qfq-staging-write-plan-and-low-level-design.md)。本次包括年度指标和state候选的staging、逐文件提升与继续执行，保持本文公式、上一交易日state、repair范围及正式checks不变。历史执行结果仍是当时事实，不代表旧的目标旁临时文件写法满足现行规则。

状态：M12 代码口径已落地到 Dagster definitions、Catalog、checks、job/sensor、repair op/job、历史直写与 baseline event CLI。正式历史文件已完成全量直写并通过 full file audit；`2026-06-05` baseline cutoff 已写入 `56` 条 runless materialization/check events，scoped quick final audit 已确认 14 个 indicator/state asset-partition 全部 ready。M12J 自动 repair 链路已落地为代码口径：当 `stock_mins_qfq_daily_update_job` 与 `stock_mins_qfq_factor_repair_job` 同日都成功后，run-status sensor 先触发 M12 daily；M12 daily 成功后，repair run-status sensor 再按 qfq factor repair affected codes 自动触发 scoped M12 repair，自动 repair 上限固定为 `repair_required_code_count <= 500`。M12K/M8 安全口径已收敛：repair 只支持真实 qfq factor repair upstream batch；自动提交和 Dagster UI 人工重放都必须显式提供 `qfq_factor_repair_trade_date`、`start_trade_date`、`stock_codes`、`repair_required_codes_hash`、`upstream_batch_id`，并与上游 metadata/status 完全一致。repair op 不支持无上游 batch 的散装手工修复，也不提供空列表全市场重写入口。R5-P0 已进一步收紧 scoped repair：repair source discovery 只读取 affected code 的现存 year 文件，默认 daily/check/history 调用仍保持全市场；repair 在写任何文件前必须确认完整 target range 的 state 文件存在，并且只接受固定全七频度，以免 completion check 误报全量完成。M12L 的旧普通 qfq materialization/check event reconciliation 方案已撤销：qfq factor repair 继续只负责重写 qfq 文件并写 repair check；repair check metadata 是历史 qfq 文件改写账本；不再按历史 qfq asset partitions 补普通 materialization/check events。M12 daily 不等待全历史普通 qfq event 补齐，而是认同日 qfq daily 成功 + qfq factor repair 成功作为当前日可继续门禁。股票分钟线连续性专项 M7/M9/M10 已把 M12 daily run-status sensor、daily asset write 和 repair op 全部收敛到 `silver_trade_calendar` 的 previous expected / expected range 口径：daily writer 与 repair op 都要求 exact previous expected state，不再自动回退到任意更早 state；只有目标或 repair start 是 expected calendar 第一个交易日时，才允许无 previous state 初始化，`STK_MINS_MACD_KDJ_BASELINE_START_DATE` 只作为日历读取下限。2026-07-15 已确认：QFQ 计算正确性由受保护测试金样本保障，production check/readiness 不二次计算 QFQ 公式；已提交但未启用的 as-of basis 实现必须在后续专项中删除，不执行 Lake 初始化。`gold_stk_mins_qfq_macd_kdj_check_refresh_job` 是 checks-only 维护入口，用于补正确 partition 归属的 check events，不 materialize 或重写 Parquet。daily/repair sensors 代码默认 `STOPPED`；实际是否启用必须读取正式 Dagster instance 或 UI，不以本文档推断。

> 2026-08-13 当前修正：Gold QFQ 5m/15m/30m/60m 不应输出独立 09:30，现有四频
> indicator 与递推 state 必须在 QFQ 重建后从历史基线顺序重建。1m 保持 09:30；
> 90m/120m 当前输出合同正确，但后续必须直接从 Silver 30m/60m 构造 QFQ source，
> 不再依赖已修正 Gold 30m/60m。完整范围和执行顺序以
> [A 股分钟线 Gold 标准 K 线合同与历史重建 LLD](./dagster-cn-a-minute-gold-canonical-bars-rebuild-low-level-design.md)
> 为准。

更新时间：2026-10-30（日更读取修正方案；历史执行记录保留原日期）

## 1. Summary

M12 新增基于七频度 `gold_stk_mins_qfq_*` 的分钟技术指标资产，第一版只做：

- `MACD(12,26,9)`
- `KDJ(9,3,3)`

输入只读当前 gold qfq 分钟线：

```text
gold_stk_mins_qfq_1m/5m/15m/30m/60m/90m/120m
```

计算实现不读取raw/silver/Tushare/prod DB，不生成EMA正式指标集，也不负责前端serving实现。现有股票详情分钟指标接口可通过本地Lake reader读取本资产，真实消费者见17.4；不能把“不负责serving”理解为没有API/前端消费者。M12已新增daily sensor，代码默认`STOPPED`；正式启用状态必须读取Dagster instance或UI后确认。

M12 必须持久化递推 state。日常计算最新一天时，参与计算的输入应为上一应有交易日state、当日qfq行和KDJ所需的有限历史；不能先装载近两年全市场历史再排序截取。年度Parquet文件的实际物理读取可能大于最后保留的记录，年度指标合并及原checks仍需读取原文件，不能承诺硬盘只读当天及8行。当前代码尚不满足前述日更输入约束，修正按第17节实施，不允许从历史起点重算当日指标。

## 2. 已确认口径

1. 任务 ID 为 `M12`。
2. 第一版只做 MACD/KDJ；EMA 只作为 MACD 内部 state，不作为 M12 输出字段。
3. 支持七频度：`1/5/15/30/60/90/120`。
4. 输入为前复权 qfq 口径，只读 `gold/quote/stk_mins_qfq`。
5. 历史初始化使用 `Direct Lake Bootstrap + Baseline/Future Event Tracking`，不是 Dagster backfill。
6. 日常增量走正式 Dagster asset job / sensor，不用直写补录模式替代日常链路。
7. qfq factor repair 后，MACD/KDJ 必须从受影响起点向后重算；不能只重算 repair 当天。
8. M12 daily 触发必须等待同一 `trade_date` 的 qfq factor repair check event 成功。当前 qfq repair op 的事实事件为七个 `gold_stk_mins_qfq_*` asset 上的 `gold_stk_mins_qfq_factor_repair_plan_evaluated`，partition 为目标 `trade_date`。
9. M12J 已拍板调整 repair 时序：如果 qfq factor repair metadata 显示历史 qfq 被改写，M12 daily 仍先在 qfq daily 与 qfq factor repair 都成功后运行当日增量；随后由 `gold_stk_mins_qfq_macd_kdj_repair_job_sensor` 触发 scoped M12 repair，重算 qfq repair affected codes 的全历史指标。最终指标收口仍以 M12 repair completion event 为准。
10. MACD 柱固定为 `macd_qfq = 2 * (macd_dif_qfq - macd_dea_qfq)`；禁止实现成 `DIF - DEA`。
11. 正式 M12 主计算禁止使用 recursive CTE。`WITH RECURSIVE` 只能出现在明确隔离的 benchmark/test 中，不得进入正式 helper、asset、repair 或 bootstrap 路径。
12. 历史文件必须全量生成；Dagster event 不做历史逐日全量补齐，只从 baseline cutoff 日期开始让 Dagster 认为当前状态可追踪，之后按日常链路持续记录。
13. 递推状态资产统一使用 `state` 命名，不改成 `checkpoint`。
14. M12J 自动 repair 上限固定为 `repair_required_code_count <= 500`。超过 500 个 affected codes 时，sensor 不自动提交 M12 repair，必须人工评估后手动执行。
15. M12K/M8 安全口径：`gold_stk_mins_qfq_macd_kdj_repair_job` 只支持真实 qfq factor repair upstream batch。自动提交和 Dagster UI 人工重放都必须提供完整 config，并通过上游 metadata/status 一致性校验；仅传 `start_trade_date + stock_codes` 的散装手工 repair 必须 fail closed，不进入 DuckDB、不写任何文件、不补 completion event。
16. M12L 已落地：qfq factor repair 后不再通过重跑 qfq daily、内联补全或普通 qfq event/check reconciliation 来解除 M12 daily 阻塞。旧 reconciliation 入口已撤销、不保留。

## 3. 非目标

本轮不做：

1. EMA5/10/20/30/60/90/250 正式指标集。
2. BOLL、MA、BIAS、WR、ATR、DMI、CCI 等其它 `stk_factor_pro` 指标。
3. 任何 Tushare `stk_factor_pro` 拉取或对账请求。
4. raw/silver schema/path/check/job/sensor 变更。
5. qfq 主表公式、路径、repair 语义变更。
6. by-symbol-month research 重排。
7. ClickHouse/serving/API/frontend 接入。
8. 正式 sensor 启用状态变更。正式历史文件直写与 `2026-06-05` baseline event 写入已完成；如需追加 event 修正、重写或启用 sensor，仍必须单独列命令审批。

## 4. 当前实现依据

M12 必须继承当前新湖 qfq 事实：

| 项 | 当前口径 |
|---|---|
| qfq assets | `gold_stk_mins_qfq_1m/5m/15m/30m/60m/90m/120m` |
| qfq dataset_id | `stk_mins_qfq` |
| qfq 分区 | `cn_a_stock_mins_silver_trade_days` |
| qfq 路径 | `data_lake/gold/quote/stk_mins_qfq/freq={freq}/ts_code={ts_code}/year={year}/part-000.parquet` |
| qfq 物理布局 | `freq + ts_code + year` stock-year 文件 |
| qfq 字段 | `ts_code, freq, trade_date, trade_time, open, high, low, close, vol, amount, exchange` |
| qfq writer pool | `gold_stk_mins_qfq_writer`，正式 instance limit 为 `1` |
| qfq daily job | `stock_mins_qfq_daily_update_job`，只选七个 qfq assets + checks |
| qfq repair job | `stock_mins_qfq_factor_repair_job`，维护型 op job，repair check event 挂七个 qfq assets |

M12 不复用旧湖 `manifest/derived/research` 路径。当前 Dagster 新湖路径只允许 `raw/silver/gold` 三层，且禁止新路径包含 legacy path parts。

## 5. Asset 与路径模型

### 5.1 指标结果资产

新增七个正式 gold 指标资产：

```text
gold_stk_mins_qfq_macd_kdj_1m
gold_stk_mins_qfq_macd_kdj_5m
gold_stk_mins_qfq_macd_kdj_15m
gold_stk_mins_qfq_macd_kdj_30m
gold_stk_mins_qfq_macd_kdj_60m
gold_stk_mins_qfq_macd_kdj_90m
gold_stk_mins_qfq_macd_kdj_120m
```

dataset_id：

```text
stk_mins_qfq_macd_kdj
```

物理路径：

```text
data_lake/gold/indicator/stk_mins_qfq_macd_kdj/freq={freq}/ts_code={ts_code}/year={year}/part-000.parquet
```

说明：

1. 指标结果和 qfq 主表一样使用 stock-year 文件，便于 qfq repair 后只重写受影响股票年份。
2. Dagster 逻辑分区仍使用交易日：`cn_a_stock_mins_silver_trade_days`。
3. `partition_key=2026-06-05` 的含义是当日指标行已写入相关股票的 `year=2026` 指标文件。

### 5.2 State 资产

新增七个正式 state 资产：

```text
gold_stk_mins_qfq_macd_kdj_state_1m
gold_stk_mins_qfq_macd_kdj_state_5m
gold_stk_mins_qfq_macd_kdj_state_15m
gold_stk_mins_qfq_macd_kdj_state_30m
gold_stk_mins_qfq_macd_kdj_state_60m
gold_stk_mins_qfq_macd_kdj_state_90m
gold_stk_mins_qfq_macd_kdj_state_120m
```

dataset_id：

```text
stk_mins_qfq_macd_kdj_state
```

物理路径：

```text
data_lake/gold/indicator/stk_mins_qfq_macd_kdj_state/freq={freq}/trade_date={trade_date}/part-000.parquet
```

说明：

1. State 是递推计算必需的正式持久资产，不是 summary/readiness asset。
2. State 不对外承载行情指标查询，只服务 MACD/KDJ 增量、repair 和审计。
3. State 分区文件保存截至该 `trade_date` 的每个 `ts_code + freq` 最新递推状态；当某只股票当日没有分钟线时，state 允许从前一状态 carry-forward，不要求 state 行数等于当日有指标行的股票数。
3. 每个 state 文件保存该频度该交易日收盘后每只股票的最后递推状态。
4. 日常最新日计算必须依赖上一交易日 state；老股票缺 state 时失败，不得中途初始化。

### 5.3 Dagster 定义形态

每个频度建议用一个不可 subset 的 `multi_asset` 同时产出：

```text
gold_stk_mins_qfq_macd_kdj_{freq}m
gold_stk_mins_qfq_macd_kdj_state_{freq}m
```

原因：

1. 指标结果和 state 必须原子推进：指标写成功但 state 未推进，会导致下一天递推不可信。
2. 同一批 DuckDB 计算可以同时得到结果行和日终 state，避免重复扫描 qfq。
3. Dagster UI 仍能分别展示指标资产与 state 资产。

### 5.4 Catalog partition model

新增 catalog partition model 必须按 “分区维度 + layer + 资产名” 命名：

| 对象 | PartitionModel value | physical layout |
|---|---|---|
| 指标结果 assets | `trade_date_partition_gold_stock_mins_qfq_macd_kdj_stock_year_file` | `stock_year_file` |
| state assets | `trade_date_partition_gold_stock_mins_qfq_macd_kdj_state` | `partition_file` |

## 6. 字段契约

### 6.1 指标结果字段

建议 `GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `ts_code` | `VARCHAR` | 标准股票代码 |
| `freq` | `INTEGER` | 分钟频度，允许 `1/5/15/30/60/90/120` |
| `trade_date` | `DATE` | 交易日 |
| `trade_time` | `TIMESTAMP` | 分钟 bar 时间 |
| `macd_dif_qfq` | `DOUBLE` | MACD DIF，基于 qfq close，参数 `12/26/9` |
| `macd_dea_qfq` | `DOUBLE` | MACD DEA，基于 qfq close，参数 `12/26/9` |
| `macd_qfq` | `DOUBLE` | MACD 柱，`2 * (DIF - DEA)` |
| `kdj_k_qfq` | `DOUBLE` | KDJ K，基于 qfq close/high/low，参数 `9/3/3` |
| `kdj_d_qfq` | `DOUBLE` | KDJ D，基于 qfq close/high/low，参数 `9/3/3` |
| `kdj_qfq` | `DOUBLE` | KDJ J，`3 * K - 2 * D`；字段名对齐 Tushare `kdj_qfq` 语义 |
| `params_key` | `VARCHAR` | 固定为 `macd_12_26_9__kdj_9_3_3` |
| `indicator_version` | `INTEGER` | 算法版本，第一版为 `1` |

不输出：

1. `ema_fast/ema_slow/dea` 这类 MACD 内部递推 state。
2. 上游 qfq 的 `open/high/low/close/vol/amount/exchange` 复制列。
3. 任意 legacy `indicator`、`research`、`manifest` 路径字段。

### 6.2 State 字段

建议 `GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `ts_code` | `VARCHAR` | 标准股票代码 |
| `freq` | `INTEGER` | 分钟频度，允许 `1/5/15/30/60/90/120` |
| `trade_date` | `DATE` | state 所属交易日 |
| `last_trade_time` | `TIMESTAMP` | 截至state所属交易日最后一根已处理K线的时间；无当日行情时可以早于该日 |
| `macd_ema_fast` | `DOUBLE` | MACD 内部 fast EMA state，N=12 |
| `macd_ema_slow` | `DOUBLE` | MACD 内部 slow EMA state，N=26 |
| `macd_dea` | `DOUBLE` | MACD 内部 DEA state，N=9 |
| `kdj_k` | `DOUBLE` | KDJ 下一日递推所需 K state |
| `kdj_d` | `DOUBLE` | KDJ 下一日递推所需 D state |
| `params_key` | `VARCHAR` | 固定为 `macd_12_26_9__kdj_9_3_3` |
| `indicator_version` | `INTEGER` | 算法版本，第一版为 `1` |

KDJ的`HHV/LLV(9)`不写入state。日常计算时，从原来源发现函数提供的目标年及上一年现存qfq文件中，选取每只股票**目标日之前最近至多8根实际K线**，包含上一交易日的行情，再与当日K线构造窗口。“上一交易日之前”的旧表述有歧义，不能理解为排除上一交易日。8根只参与目标日RSV的高低窗口，不重新推进EMA、DEA、K或D。原候选集合不足8根时沿用现行部分窗口，不新增失败条件、不扩读更早年份；跨两年以上停牌的更早来源不因本轮获得额外修正。state仍保持现行扁平字段，不新增正式JSON或LIST字段；第19节LLD中的临时SQL聚合结果不属于持久化schema变更。

## 7. 公式口径

### 7.1 MACD(12,26,9)

输入：qfq `close`。

参数：

```text
fast = 12
slow = 26
signal = 9
alpha_fast = 2 / (fast + 1)
alpha_slow = 2 / (slow + 1)
alpha_dea = 2 / (signal + 1)
```

初始化：

```text
ema_fast = close
ema_slow = close
dif = 0
dea = 0
macd = 0
```

递推：

```text
ema_fast = close * alpha_fast + prev_ema_fast * (1 - alpha_fast)
ema_slow = close * alpha_slow + prev_ema_slow * (1 - alpha_slow)
dif = ema_fast - ema_slow
dea = dif * alpha_dea + prev_dea * (1 - alpha_dea)
macd = 2 * (dif - dea)
```

`macd = 2 * (dif - dea)` 是 M12 的字段契约硬口径。字段 check、样本核验和测试必须覆盖该倍率，避免落成部分行情库里常见的未放大柱值。

### 7.2 KDJ(9,3,3)

输入：qfq `close/high/low`。

窗口：

```text
HHV = max(high) over last 9 bars of the same ts_code/freq
LLV = min(low) over last 9 bars of the same ts_code/freq
```

RSV：

```text
if HHV = LLV:
  RSV = 50
else:
  RSV = (close - LLV) / (HHV - LLV) * 100
```

初始化：

```text
K = 50
D = 50
J = 50
```

递推：

```text
K = (2 / 3) * prev_K + (1 / 3) * RSV
D = (2 / 3) * prev_D + (1 / 3) * K
J = 3 * K - 2 * D
```

## 8. 历史 Bootstrap

历史初始化采用：

```text
Direct Lake Bootstrap + Baseline/Future Event Tracking
```

不是 Dagster backfill。

### 8.1 只读规模审计

进入任何正式写入前，必须只读统计：

1. qfq 七频度源文件数、源行数、涉及股票数、年份数、日期数。
2. 目标指标 stock-year 文件预计数量。
3. 目标 state 文件预计数量。
4. baseline cutoff event 数量、未来每日 event 数量，以及“如果误做历史逐日 event backfill”的上界。
5. 目标路径冲突数量。
6. `1m` 最坏频度的 source rows、max stock sequence length 和正式实现 benchmark。

如果无法给出文件、行数、event 数上界，停止，不进入写入。

### 8.2 历史计算批次

历史计算禁止使用正式 recursive CTE。当前代码第一版批次为：

```text
freq -> year
```

要求：

1. 每个批次覆盖一个 `freq/year` 的 selected partitions。
2. 同一个 `freq` 内按年份顺序计算，year-to-year state 通过上一交易日 state 文件连续传递。
3. 每个 `freq/year` 批次写该年涉及股票的 stock-year 指标文件，并写该批次内每日 state 文件。
4. state 从已计算结果中按 `ts_code/trade_date` 取最后一根 bar 生成。
5. Python 只做参数校验、路径发现、批次规划、DuckDB SQL 调度和异常报告；不得做明细公式递推。
6. MACD 必须走非递归、可批量执行的实现；KDJ 的 HHV/LLV 使用 DuckDB window function。
7. 如后续全历史正式执行发现 `freq/year` 批次内存或 spill 压力不可接受，再单独设计 security bucket；不得在本轮代码里预埋未启用分桶口径。

### 8.3 写入顺序

历史直写步骤：

1. `plan`：只读规模审计，输出批次、行数、文件数、冲突和 benchmark 结果。
2. `sample`：写临时 lake 样本，验证公式、state、schema、row count、key uniqueness。
3. `generate`：按 `freq/year` 写正式指标和 state 文件。
4. `audit-files`：聚合审计文件事实，不做逐分区深扫。
5. `report-baseline-events`：只对 baseline cutoff partition 写当前状态 materialization/check events。
6. `final-audit`：聚合文件集合差异、baseline event count、少量 readiness sample。
7. baseline 之后的 partition 由正式 daily job/sensor 正常产生 materialization/check events。

### 8.4 2026-06-08 正式历史直写与 baseline event 结果

M12 历史初始化已按 `Direct Lake Bootstrap + Baseline/Future Event Tracking` 执行完成。执行口径：

1. 历史文件全量生成，覆盖已注册 `cn_a_stock_mins_silver_trade_days` 分区。
2. Dagster event 只写 baseline cutoff partition，不做历史逐日 event backfill。
3. baseline cutoff 选择最新已注册分区 `2026-06-05`。

全量文件审计结果：

| 项 | 结果 |
|---|---:|
| `passed` | `True` |
| selected partition count | `3019` |
| selected freqs | `1/5/15/30/60/90/120` |
| selected years | `2014`-`2026` |
| planned indicator files | `369918` |
| existing indicator files | `369918` |
| planned state files | `21133` |
| existing state files | `21133` |
| source rows | `3706759744` |
| indicator rows | `3706759744` |
| state rows | `81494182` |
| missing input count | `0` |
| row count mismatch count | `0` |

baseline event scoped dry-run 结果：

```text
baseline cutoff: 2026-06-05
selected_partition_count: 1
selected_freqs: [1, 5, 15, 30, 60, 90, 120]
audited_asset_partition_count: 14
failed_asset_partition_count: 0
reported_event_count: 0
```

baseline event 正式写入结果：

```text
baseline cutoff: 2026-06-05
reported_asset_partition_count: 14
reported_event_count: 56
failed_asset_partition_count: 0
```

写入后 scoped quick final audit 结果：

```text
audit_mode: quick
selected_partition_count: 1
file_audit_passed: True
planned_target_file_count: 38598
existing_target_file_count: 38598
materialized_partition_counts: 14 个 asset 全部为 1
sample_readiness: 14 个 asset-partition 全部 True
check_success_counts_skipped: True
```

当前已完成：历史文件事实、baseline materialization/check events 和 baseline readiness sample。后续每日分区由正式 daily job/sensor 正常产生 materialization/check events。

### 8.5 2026-06-07 只读 benchmark 结论

本节保留当时的性能测量及结论，不证明2026年10月日更满足有限读取约束，也不作为本轮实际设备I/O、内存或恢复耗时的保证。该次测试确实覆盖全市场，不能说此前未做全市场测试；但未有同节证据证明当前规模的日更输入范围与中间结果上界。最新问题与本轮预算见第17节及写入LLD第19节。

本次 benchmark 只读正式 qfq 源，临时输出只写 `/private/tmp/goldenshare_m12_benchmark_20260607/`，未写正式 lake，未读取或写入正式 Dagster instance。

正式 qfq 根目录 `/Volumes/datasource/data_lake/gold/quote/stk_mins_qfq` 当前约 `78G`。

2026-05 样本规模：

| freq | qfq rows |
|---:|---:|
| 1m | 23,846,709 |
| 5m | 4,848,697 |
| 15m | 1,682,133 |
| 30m | 890,559 |
| 60m | 494,745 |
| 90m | 296,853 |
| 120m | 197,898 |
| 合计 | 31,358,285 |

样本覆盖 `18` 个交易日、约 `5510` 只股票。

实测结论：

| 测项 | 结果 |
|---|---:|
| 1m count scan | `23,846,709` rows / `0.86s` |
| 120m recursive CTE 精确原型 | `197,898` rows / `1.05s` |
| 1m 全月 recursive CTE 精确原型 | 超过 `120s`，终止 |
| 1m / 100 股票 recursive CTE 精确原型 | 超过 `60s`，终止 |
| 1m window-only benchmark | `23,846,709` rows / `7.78s` |
| 1m single Parquet COPY | `23,846,709` rows / `14.34s`，输出约 `234M` |
| 1m stock-year partitioned COPY | `23,846,709` rows / `14.28s`，`5655` 个文件，输出约 `322M` |
| 1m state COPY | `18` 个交易日，约 `99k` rows / `2.92s` |
| 七频度 stock-year partitioned COPY | `31,358,285` rows / `33.17s`，`38,774` 个文件，输出约 `644M` |

全历史 qfq 行数：

| freq | qfq rows |
|---:|---:|
| 1m | 2,739,347,833 |
| 5m | 557,710,049 |
| 15m | 193,465,798 |
| 30m | 102,390,791 |
| 60m | 57,031,570 |
| 90m | 34,075,845 |
| 120m | 22,737,858 |
| 合计 | 3,706,759,744 |

按七频度 partitioned COPY 的保守吞吐估算：

| 范围 | 估算耗时 |
|---|---:|
| 2025 七频度，约 `428,910,201` rows | 约 `7.6 min` |
| 全历史七频度，约 `3,706,759,744` rows | 约 `65.3 min` |
| 全历史 1m，约 `2,739,347,833` rows | 约 `48.3 min` |

M12 helper 落地后的临时湖 benchmark：

| freq | 2026-05 rows | source files | output files | elapsed |
|---:|---:|---:|---:|---:|
| 1m | `23,846,709` | `10,988` | `5,510` | `152.166s` |
| 5m | `4,848,697` | `10,987` | `5,510` | `25.531s` |
| 15m | `1,682,133` | `10,988` | `5,510` | `17.964s` |
| 30m | `890,559` | `10,985` | `5,510` | `15.838s` |
| 60m | `494,745` | `10,986` | `5,510` | `15.099s` |
| 90m | `296,853` | `10,985` | `5,510` | `14.263s` |
| 120m | `197,898` | `10,986` | `5,510` | `14.301s` |
| 合计 | `32,257,594` | - | - | `286.825s` |

测量口径：只读正式 `gold_stk_mins_qfq` parquet，输出到 `/private/tmp` 临时湖并清理；不写正式 lake，不写 Dagster instance。benchmark 执行当时正式 M12 state 尚未历史生成，因此使用临时 previous state seed 让 helper 跑完整计算与 stock-year 写出路径；该测量用于性能门禁，不作为正式数值验收。

结论：

1. DuckDB 读、窗口、Parquet COPY 不是主要风险；recursive CTE 是主要风险。
2. 如果正式 MACD 递推误走 recursive CTE，`1m` 会从小时级变成不可接受。
3. M12 helper 已通过 `1m 2026-05` 性能门禁：`152.166s`，低于 `30 min` 拒绝阈值。
4. 在非递归、批量/vectorized 实现成立的前提下，全历史文件生成按 `65 min` 量级规划；加 state、baseline events、聚合 audit 后，总体按 `1.5-2h` 保守规划。

## 9. 日常 Job / Sensor

### 9.1 Job

新增 job：

```text
gold_stk_mins_qfq_macd_kdj_daily_update_job
```

selection：

```text
七个 gold_stk_mins_qfq_macd_kdj_* assets
+ 七个 gold_stk_mins_qfq_macd_kdj_state_* assets
+ 对应 blocking checks
```

job 文件只允许定义 asset selection、checks selection、executor 和 description；禁止写 DuckDB SQL、路径拼接或业务计算逻辑。

建议仍使用 `in_process_executor`，保证单 run 内七频度按 Dagster 依赖顺序执行。跨 run 互斥仍依赖 pool。

### 9.2 Sensor

新增 sensor：

```text
gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor
```

默认状态：

```text
STOPPED
```

触发方式：

```text
run-status coordination
```

触发条件：

1. 监听 `stock_mins_qfq_daily_update_job` 与 `stock_mins_qfq_factor_repair_job` 的 `SUCCESS`。
2. 任一上游成功后，按同一 `trade_date` 检查另一个上游是否也成功。
3. 同日 `stock_mins_qfq_daily_update_job` 已成功，表达目标交易日 qfq 日常生产已完成。
4. 同分区 qfq factor repair check event 必须成功：七个 qfq asset 上的 `gold_stk_mins_qfq_factor_repair_plan_evaluated` 都必须是 `passed=true`，且 event partition 等于目标 `trade_date`。
5. M12L 口径下，若 qfq factor repair 改写了历史 qfq 文件，M12 daily 不等待、也不补齐全历史普通 qfq materialization/check event；旧 reconciliation 入口已撤销、不保留。
6. 非 expected calendar 首个交易日时，上一 expected trade date 的七个 state assets 必须 ready；该上一日来自 `silver_trade_calendar`，不得用 previous registered partition 代替。expected calendar 首个交易日允许无 previous state 初始化。
7. 目标指标和 state 未 ready。
8. 如果目标已 materialized 但 blocking checks 未全绿，不自动重跑，返回人工修复提示。
9. 如果 qfq factor repair metadata 显示历史 qfq 文件发生改写，M12 daily 仍先作为受控 pending-repair run 执行；该状态只表示“当天增量已先跑、后续还需要 scoped MACD/KDJ repair 收口”，不得写入项目自定义 run tags。

run key：

```text
gold_stk_mins_qfq_macd_kdj_daily_update:{trade_date}
```

run tags：

不新增项目自定义 run tags。RunRequest 只使用稳定 `run_key` 与 Dagster 分区语义；qfq factor repair 的 `upstream_batch_id`、affected code hash、repair scope 等运行事实只保存在 qfq factor repair check metadata 和 MACD/KDJ repair completion check metadata 中。Dagster event storage id 只作为 event log 观测字段，不作为 run key、run config 或 completion identity。

不得在稳定态逐 partition / 逐 check 深扫 event history。日常只看目标日期 qfq readiness、上一交易日 state readiness、目标日期 M12 readiness 和 bounded run-status coordination。

### 9.3 M12I/M12J：qfq factor repair 时序门禁（当前代码口径）

M12I 先落地了 qfq factor repair 前置门禁；M12J 将“历史重写时 daily 等 M12 repair completion”的顺序修正为当前正式口径：daily 先跑、repair 后跑、最终指标收口仍等 repair completion。M12L 进一步明确：旧普通 qfq materialization/check event reconciliation 入口已撤销、不保留，因此不再作为 M12 daily 的前置条件。

当前已实现口径：

1. `gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor` 是 run-status sensor，监听 `stock_mins_qfq_daily_update_job` 与 `stock_mins_qfq_factor_repair_job` 成功。
2. 同日 qfq daily 和 qfq factor repair 任一未成功时，M12 daily sensor 只 skip，不提交 run。
3. 同日 qfq factor repair 缺失、失败、partition 不匹配、metadata 不可解析，一律 fail closed。
4. qfq factor repair 成功且没有历史重写时，M12 daily 可以继续使用上一交易日 state 做日常增量。
5. qfq factor repair 成功且 metadata 显示历史 qfq 被重写时，M12 daily 作为受控 pending-repair run 先执行，随后由 M12 repair sensor 自动触发 scoped repair。
6. M12 daily 的当前日门禁认同日 qfq daily 成功和同日 qfq factor repair 成功；不等待 repair 涉及的全历史普通 qfq materialization/check event 全部补齐。
7. M12 daily asset 写前必须复用同一 guard：人工直接运行 daily job 时也必须先看到同日 qfq factor repair check 全绿；guard 不读取、不要求、不校验项目自定义 run tags。
8. 最终指标 ready/收口仍以 14 个 `gold_stk_mins_qfq_macd_kdj_repair_completed_check` event 覆盖本次 qfq repair scope 为准。
9. 不新增 summary asset、readiness asset、数据库表、配置项或项目自定义 run tags；状态事实通过现有 qfq repair check event、M12 repair completion check event 和 asset failure metadata 表达。

实现接口：

1. `orchestrator.defs.asset_guards.stk_mins_qfq_macd_kdj` 提供 qfq-only status、M12 completion status、daily final gate 和 asset 写前 guard。
2. helper 按 check key 读取七个 qfq asset 上最新 `gold_stk_mins_qfq_factor_repair_plan_evaluated`，不调用 `get_asset_check_execution_history`；同时校验 event partition、`passed=true`、`blocking=true` 和 metadata。
3. `stock_mins_qfq_factor_repair_op` 的 repair check metadata 已补充 `repair_start_trade_date`、`repair_end_trade_date`、`selected_partition_count`、`repair_required_codes`、`repair_required_codes_hash`、`repair_required_codes_truncated`，供 M12 判断修复范围和自动上限。
4. `gold_stk_mins_qfq_macd_kdj_repair_op` repair 成功后 emit 14 个 `gold_stk_mins_qfq_macd_kdj_repair_completed_check` events，metadata 包含覆盖范围、freqs、stock scope、文件数、行数、affected code hash/count 和 `source_upstream_batch_id`。
5. sensor 和 asset 写前 guard 复用同一 qfq repair status 与 completion status，避免 sensor 和人工 run 口径漂移。

性能门禁：

| 项 | 口径 |
|---|---|
| qfq repair gate | 按 7 个 qfq asset check key 做有界 status 读取；hot path 不回填 event storage id，不按 partition/check history 深扫 |
| M12 repair gate | 按 14 个 M12 asset check key 批量读取 latest check execution；不扫历史全量 event |
| 日常 tick 额外查询量 | target date qfq lake readiness（只复刻生产输入/文件契约）+ bounded run-status 查询；不按历史 partition 扩张 |
| 普通 qfq event reconciliation | 已撤销、不保留；不进入 M12 daily tick 路径 |
| 禁止 | `get_asset_check_execution_history(limit=...)`、逐历史 partition readiness、扫描全量 run event log、查询正式 lake 文件来判断 repair 是否完成 |
| fail closed | 缺 event、失败 event、metadata 缺字段、event 日期不匹配均不触发或不写入 |

### 9.4 M12J：qfq repair 后自动触发 M12 daily 与 scoped repair（代码口径已落地）

目标：`gold_stk_mins_qfq_macd_kdj_repair_job` 专用于修复 qfq factor repair 改写的股票代码。自动链路不做全市场重算，只重算 `stock_mins_qfq_factor_repair_job` 中 `repair_required_codes` 对应股票的全历史 MACD/KDJ。

最终时序：

```text
stock_mins_qfq_daily_update_job SUCCESS
        +
stock_mins_qfq_factor_repair_job SUCCESS
        ↓
gold_stk_mins_qfq_macd_kdj_daily_update_job
        ↓
gold_stk_mins_qfq_macd_kdj_repair_job
```

其中 `stock_mins_qfq_daily_update_job` 与 `stock_mins_qfq_factor_repair_job` 先后顺序不固定；M12 daily sensor 必须等二者同一 `trade_date` 都成功后才提交 M12 daily。

需要新增或调整的 sensor：

| sensor | 口径 |
|---|---|
| `gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor` | run-status coordination，监听 qfq daily 与 qfq factor repair 成功；同日两个上游都成功后触发 M12 daily |
| `gold_stk_mins_qfq_macd_kdj_repair_job_sensor` | run-status coordination，监听 M12 daily 成功；若同日 qfq repair metadata 显示历史重写，则触发 M12 scoped repair |

qfq repair metadata 必须补充：

| 字段 | 口径 |
|---|---|
| `repair_required_codes` | 完整 affected code list；仅当 `repair_required_code_count <= 500` 时写入并允许自动 repair |
| `repair_required_codes_hash` | affected code list 的稳定 hash，供 run_key 去重、completion 对账和审计 |
| `repair_required_code_count` | affected code 数量 |
| `repair_required_codes_truncated` | 超过 500 时为 true，sensor 必须 skip 自动 repair |
| `repair_start_trade_date` | scoped repair 起点；当前 qfq repair 为已注册分钟线最早分区，即全历史起点 |
| `repair_end_trade_date` | qfq repair 目标 trade_date |

自动 repair 上限：

| 项 | 口径 |
|---|---|
| 上限 | `repair_required_code_count <= 500` |
| `0` | qfq repair 未改写历史，M12 repair sensor skip |
| `1..500` | 自动提交 M12 repair |
| `>500` | 不自动提交；返回 skip reason，要求人工评估后手动执行 |

M12K/M8 补充安全口径：自动 sensor 只会在 `repair_required_code_count > 0` 且完整 code list/hash/upstream batch 可用时提交 repair；Dagster UI 人工执行同一个 repair job 时，只允许重放真实 qfq factor repair upstream batch，必须提供完整 config，并由 op 重新读取 qfq repair metadata/status 校验完全一致。repair job 不接受无上游 batch 的散装 `start_trade_date + stock_codes` 修复，也不接受空列表代表全市场重写。

M12 repair run config：

```python
{
  "ops": {
    "gold_stk_mins_qfq_macd_kdj_repair_op": {
      "config": {
        "qfq_factor_repair_trade_date": trade_date,
        "start_trade_date": repair_start_trade_date,
        "freqs": [1, 5, 15, 30, 60, 90, 120],
        "stock_codes": repair_required_codes,
        "reason": "qfq_factor_repair:{trade_date}",
        "repair_required_codes_hash": repair_required_codes_hash,
        "upstream_batch_id": upstream_batch_id
      }
    }
  }
}
```

Dagster UI 人工重放配置示例：

```yaml
ops:
  gold_stk_mins_qfq_macd_kdj_repair_op:
    config:
      qfq_factor_repair_trade_date: '2026-06-08'
      start_trade_date: '2014-01-02'
      freqs:
        - 1
        - 5
        - 15
        - 30
        - 60
        - 90
        - 120
      stock_codes:
        - '000001.SZ'
        - '600000.SH'
      repair_required_codes_hash: '<qfq factor repair metadata 中的 hash>'
      upstream_batch_id: '<qfq factor repair metadata 中的 upstream_batch_id>'
resources:
  lake_root:
    config:
      root_path: '/Volumes/datasource/data_lake'
```

该模式不是新的手工业务来源，只是重放真实上游批次。op 会按 `qfq_factor_repair_trade_date` 重新读取 qfq repair check metadata/status，并校验 `start_trade_date`、`stock_codes`、`repair_required_codes_hash`、`upstream_batch_id` 与上游事实完全一致。若 metadata 缺失、失败、不完整、affected codes 超过 500 或任一显式字段与 metadata 不一致，op 必须 fail closed。

M12 daily 写前 guard 调整：

1. daily asset 写前必须确认同日 qfq factor repair 成功。
2. 如果 qfq repair 改写历史，daily 允许作为受控 pending-repair run 先执行，但后续 scoped repair 必须消费当前 qfq repair 的 `upstream_batch_id` 和 code hash。
3. 人工直接运行 daily job 时仍必须通过同日 qfq factor repair guard；不得通过项目自定义 run tags 或 event storage id 绕过门禁。
4. 最终 readiness/收口必须等待 `gold_stk_mins_qfq_macd_kdj_repair_completed_check` 覆盖本次 qfq repair scope。

性能门禁：

| 项 | M12J 口径 |
|---|---|
| M12 repair 计算范围 | 只重算 qfq repair affected codes，不做全市场重算 |
| 批次 | 七频度 × affected code stock-year；核心 SQL 仍走 DuckDB 向量化 |
| Python 职责 | 只做 metadata/status 解析、run config、去重、批次日志 |
| 自动触发拒绝条件 | `repair_required_code_count > 500`、缺完整 code list、code hash 不匹配、qfq daily 未成功、M12 daily 未成功 |
| 禁止 | recursive CTE、Python 行循环、全市场默认 repair、逐历史 partition event 深扫 |

### 9.5 M12L：撤销 qfq 普通 event reconciliation，repair check 作为历史改写账本

背景：

1. `stock_mins_qfq_factor_repair_job` 是维护型 op job，正确职责是重写 qfq 文件并写 `gold_stk_mins_qfq_factor_repair_plan_evaluated` repair check。
2. factor repair 不应在同一个 run 内补全 affected date range 的普通 qfq materialization/check events；这个动作 event 数可能很大，会把 repair run 变成长时间 event 写入任务。
3. 以一次 `selected_partition_count=3021` 的 repair metadata 估算，七频度普通 qfq events 约为 `3021 * 7 * 9 = 190323` 条；其中 `9` 表示每个 asset-partition 的 1 条 materialization + 8 条普通 blocking checks。该量级不能内联到 factor repair，也不能阻塞 M12 daily。
4. 已验证的旧 reconciliation 方案虽然能复用普通 qfq runless event 模型，但事件量、历史检查语义和退市股票 as-of factor 口径都不适合作为自动链路继续保留。

已确认方案：

1. factor repair 继续只负责重写文件和写 repair check，不改成普通 qfq asset materialization job。
2. 不新增、不保留 qfq repair event reconciliation job/sensor/op/helper；旧入口从 active definitions 中删除。
3. repair check metadata 正式承担“历史 qfq 文件被改写”的审计账本职责；普通 qfq asset partition 的 materialization 时间只表示 daily/bootstrap 生成时间，不再被强制追平到 repair 时间。
4. M12 daily sensor 不等待、也不恢复已撤销的全历史普通 qfq check reconciliation；同日 `stock_mins_qfq_daily_update_job` 成功 + 同日 `stock_mins_qfq_factor_repair_job` 成功，就是当前日 MACD/KDJ 可继续的 qfq 门禁。
5. 若 repair 改写历史，真正必须同步的是 MACD/KDJ repair；该链路继续通过 qfq factor repair status 和 M12 repair completion check 保证顺序。
6. 禁止用“factor repair 后重跑 `stock_mins_qfq_daily_update_job`”来补历史 event 或绕过门禁；qfq daily 只服务当天正常生产。
7. 后续如需要更强 UI 可观测性，应增强 `gold_stk_mins_qfq_factor_repair_plan_evaluated` metadata，而不是恢复逐历史分区普通 materialization/check 补账。

性能门禁：

| 项 | M12L 撤销后口径 |
|---|---|
| factor repair run | 不内联普通 qfq event 补齐 |
| M12 daily tick | 不扫描 affected history；不等待、不恢复已撤销的普通 qfq reconciliation |
| event 写入 | 不按历史 qfq asset partitions 补普通 materialization/check events |
| 幂等判断 | 下游以 qfq factor repair `upstream_batch_id` 判断本次 repair scope；code hash 只参与 config/metadata 对账 |
| 禁止 | 恢复旧 reconciliation job/sensor/op/helper、重跑 qfq daily 代替历史修复、逐 partition 深扫 event history |

代码状态：

1. 旧 reconciliation op/job/sensor/helper 已从 active definitions 删除。
2. 静态门禁禁止旧 reconciliation 文件和 source method 回流。
3. 不得再用“普通 qfq reconciliation 未完成”解释 M12 daily 当前日必须阻塞；该旧入口已撤销、不保留。

## 10. Repair 联动

qfq factor repair 会改写受影响股票的历史 qfq stock-year 文件。MACD/KDJ 是递推指标，一旦源 qfq 从某个历史 bar 开始变化，下游从该 bar 开始直到最新日期都可能变化。

M12 必须新增维护入口：

```text
gold_stk_mins_qfq_macd_kdj_repair_job
```

维护 op 名称：

```text
gold_stk_mins_qfq_macd_kdj_repair_op
```

config：

| 字段 | 说明 |
|---|---|
| `start_trade_date` | 指标重算起始交易日，必须是受 qfq repair 影响的最早交易日 |
| `qfq_factor_repair_trade_date` | 真实 qfq factor repair upstream batch 的目标交易日；自动路径和 Dagster UI 人工重放都必填 |
| `stock_codes` | 受影响股票代码集合；必须与 qfq factor repair metadata/status 完全一致，空列表禁止作为全市场 repair 入口 |
| `freqs` | 默认七频度；允许显式缩小但不得扩大到非 qfq 频度 |
| `reason` | repair 原因，例如 `qfq_factor_repair` |
| `repair_required_codes_hash` | 受影响股票集合 hash；必须与 qfq factor repair metadata/status 完全一致 |
| `upstream_batch_id` | 真实 qfq factor repair upstream batch id；必须与 qfq factor repair metadata/status 完全一致 |

repair 规则：

1. 非 expected calendar 首个交易日时，目标口径要求读取 `start_trade_date` 的 previous expected trade date state 作为递推起点。
2. 如果 `start_trade_date` 不是 expected calendar 首个交易日且 previous expected state 缺失，当前代码必须 fail closed；不得自动回退到任意更早 state，也不得从 `start_trade_date` 中途初始化老股票。若 `start_trade_date` 是 expected calendar 首个交易日，则允许无 previous state 初始化。
3. 只重算 `stock_codes` 的受影响 stock-year 指标文件和 state 文件。
4. 目标口径要求重算范围覆盖 `start_trade_date` 到 qfq factor repair metadata/status 的 repair end date 之间的 expected trade date range。当前代码已按 expected range 执行，不能把“latest registered partition”作为正式口径恢复。
5. qfq repair 完成但指标 repair 未完成时，M12 指标的最终收口不能被视为完成；但 M12 daily 当前日生产不等待、也不恢复已撤销的全历史普通 qfq event reconciliation，只要求同日 qfq daily 成功和同日 qfq factor repair 成功。
6. repair completion check event 必须挂到七个指标 assets 和七个 state assets，partition 使用 repair 目标起点或实际触发的 `start_trade_date`。
7. 新增 repair completion check 名称：`gold_stk_mins_qfq_macd_kdj_repair_completed_check`。它是维护事件门禁，不替代指标/state 的常规 blocking checks。
8. scoped repair 写 state 文件时必须 merge：读取已有 `freq/trade_date` state，删除本次 `stock_codes` 的旧 state，union 新 state 后原子替换。禁止因为只修少量股票而整文件覆盖导致未受影响股票 state 丢失。
9. repair job 不提供无上游 batch 的散装手工入口，也不提供全市场默认入口；缺少 `qfq_factor_repair_trade_date` 或 `upstream_batch_id` 必须失败，防止 Launchpad/CLI 漏填后整市场重写。未来如确需全市场指标 repair，必须单独设计、审批和执行，不得复用空列表语义。
10. `qfq_factor_repair_trade_date` 模式必须读取同日七个 qfq repair check metadata；metadata 缺失、失败、日期不匹配、字段不完整、code list 被截断或超过自动上限时都必须 fail closed。
11. `start_trade_date`、`stock_codes`、`repair_required_codes_hash`、`upstream_batch_id` 都必须与 qfq factor repair metadata/status 完全一致，否则 fail closed。

M12J 自动触发规则：

1. qfq repair metadata 中 `repair_required_code_count=0` 时，`gold_stk_mins_qfq_macd_kdj_repair_job_sensor` skip。
2. `1 <= repair_required_code_count <= 500` 且 `repair_required_codes` 完整时，自动触发 M12 repair。
3. `repair_required_code_count > 500` 时，不自动触发；sensor 必须 skip 并写明超过自动 repair 上限。
4. M12 repair run key 必须使用 `gold_stk_mins_qfq_macd_kdj_repair:{upstream_batch_id}`；`repair_required_codes_hash` 只进入 run config 和 completion metadata，用于业务 scope 对账。
5. M12 repair completion metadata 必须回写 `source_upstream_batch_id`、`repair_required_codes_hash`、`repair_required_code_count`、`covered_start_trade_date`、`covered_end_trade_date`、`freqs`、`stock_code_scope`、`stock_code_count`。

并发保护：

1. M12 daily assets 和 repair op 第一版使用 `GOLD_STK_MINS_QFQ_WRITER_POOL`。
2. 这样可避免指标读取 qfq 时，另一个 qfq daily/repair run 正在改写同一 qfq source 文件。
3. 如果未来要拆更细 pool，必须先单独设计 qfq source read/write 一致性保护。

## 11. Checks

### 11.1 指标结果 checks

下表前三个细粒度名称只记录 M12 的历史 rule 语义；当前 production check 已收敛为
`contract_check` 与 `source_coverage_check`。公式类 production check 已退出，公式断言由受保护金样本测试承担。

| check | 口径 |
|---|---|
| `gold_stk_mins_qfq_macd_kdj_file_exists_and_schema_check` | 当日涉及的 stock-year 指标文件存在，schema 等于 definition metadata 契约 |
| `gold_stk_mins_qfq_macd_kdj_source_ready_check` | 同分区 qfq source 存在且有行 |
| `gold_stk_mins_qfq_macd_kdj_row_count_matches_qfq_check` | 指标行数等于同分区 qfq source 行数 |
| 历史 `gold_stk_mins_qfq_macd_kdj_formula_sample_check` | 已退出正式 Dagster check；MACD/KDJ 公式自洽由受保护金样本测试验证，不在 production check 中二次计算。 |

### 11.2 State checks

每个 state asset 至少需要 blocking checks：

| check | 口径 |
|---|---|
| `gold_stk_mins_qfq_macd_kdj_state_file_exists_and_schema_check` | state 分区文件存在，schema 等于 definition metadata 契约 |
| `gold_stk_mins_qfq_macd_kdj_state_latest_coverage_check` | 对当日有指标行的股票，state 的 `last_trade_time` 必须等于当日指标尾行时间；对当日无分钟线但已有历史 state 的股票，state 允许 carry-forward |

checks 可以用同一 DuckDB 连接批量聚合，不允许全绿场景无条件执行高成本 sample 查询；sample 查询只能在失败时取。

## 12. 性能门禁

| 项 | M12 口径 |
|---|---|
| 输入资产 | 七个 `gold_stk_mins_qfq_*` |
| Tushare/prod DB 请求 | `0` |
| raw/silver 读取 | `0`，只通过 qfq readiness 间接依赖 |
| 指标输出行数 | 等于 qfq source row_count |
| state 行数 | 上一完整state与当日有行情代码的并集；无当日行情的旧股票继续保留，因此可以大于当日有行情股票数 |
| 指标文件数 | 约等于 qfq source stock-year 文件数；正式数必须由只读 plan 给出 |
| state 文件数 | `freq_count * partition_count`，当前 7 频度、约 3019 个交易日时约 21133 个文件 |
| 历史核心批次 | `freq -> year`，不按股票主循环，不按日期切断递推，不使用 recursive CTE |
| 日常计算输入（待第17节落实） | 目标日期qfq行＋原目标年/上一年集合中每股最近至多8根历史K线＋上一应有交易日完整state；物理扫描、年度合并及原checks成本另外计入LLD第19.7节 |
| Repair 核心扫描 | 当前代码扫描受影响股票从 `start_trade_date` 到 qfq factor repair `repair_end_trade_date` 的 expected trade date range，并使用 previous expected state 作为递推起点 |
| DuckDB 配置 | 统一 `connect_configured_duckdb`：temp `/Volumes/datasource/.goldenshare_duckdb_tmp`，max temp `512GB`，memory `16GB`，threads `4`，`preserve_insertion_order=false` |
| 排序 | 所有正式输出必须 SQL `ORDER BY ts_code, trade_time` 或等价稳定排序 |
| 写入 | 正式Lake外的staging候选 → 现行校验 → 逐文件`os.replace`；指标stock-year和state partition均沿原publication，不恢复目标旁临时文件 |
| Python 职责 | 参数校验、路径发现、批次规划、DuckDB SQL 调度、样本汇总 |
| Dagster event | 历史只写 baseline cutoff events，未来按 daily job/sensor 记录；禁止历史逐日全量 event backfill |
| 禁止 | Python 明细递推、Python 明细写 Parquet、正式 recursive CTE、按日期切断递推、老股票中途初始化、历史逐日 event 深扫 |

不可接受阈值：

1. 只读 plan 不能给出 source row/file/event 上界。
2. 正式 helper 或 bootstrap/repair SQL 出现 `WITH RECURSIVE`、`recursive` 或等价逐行递归实现。
3. 历史主计算退化为`stock_code -> freq -> year`循环。本轮日更允许按固定股票小批次准备有限输入并执行列式计算，不能逐股重复调用完整writer、冻结输入或提升文件；详见第17节。
4. 日常最新日需要从历史起点重算。
5. repair 无法证明从受影响起点向后覆盖全部下游 state。
6. checks 在上千分区历史审计中退回逐 partition 深扫 event history。
7. `1m 2026-05` exact benchmark 超过 `30 min`；出现该结果必须停止全量历史执行并重做计算方案。
8. 七频度 2026-05 exact benchmark 不能给出 rows/files/耗时，或明显劣化到无法把全历史控制在 `1.5-2h` 规划内。

开发门禁：

1. 正式计算 helper 的 SQL/static source 必须有门禁，禁止 `WITH RECURSIVE`。
2. MACD 样本测试必须断言 `macd_qfq = 2 * (macd_dif_qfq - macd_dea_qfq)`。
3. 历史 bootstrap 工具必须在 `plan` 输出 source rows、target files、state files、baseline event count、如果误做全量历史 event 的上界。
4. `generate` 前必须先跑只读 benchmark 和 `/private/tmp` 样本写入；样本不得写正式 lake。
5. event/report 执行口径只允许 baseline cutoff 与 future tracking，不得补齐全部历史 partition events。2026-09-05 清退 M2B 已补单分区硬门禁：CLI 必须显式传入同一天的 `--start-date` / `--end-date`，显式 keys 不得越出当天，report 在任何文件审计/事件写入前确认实际 plan 只有该分区；dry-run 同样执行门禁。
6. audit 必须用聚合 count 和 sample readiness，禁止把 readiness 逐 partition 作为主流程。

## 13. 历史 event 追踪口径

M12 历史初始化不做历史逐日 runless event 全量补录。原因是物理文件全历史生成后，Dagster 只需要从当前 baseline cutoff 开始承担日常可观测和调度事实；为每个历史交易日补 materialization/check event 会放大 event log，且对后续日常生产没有必要。

### 13.1 Baseline cutoff

文件审计全绿后，选择一个 baseline cutoff partition，通常是历史生成完成时最新已注册交易日。只对该 partition 写当前状态 events：

| 对象 | 每频度 event |
|---|---:|
| 指标 asset materialization | `1` |
| state asset materialization | `1` |
| 指标 blocking checks | `4` |
| state blocking checks | `2` |
| 合计 | `8` |

以上是原 M12 执行时的 check 集合，七频度 baseline event 共 `56` 条，保留用于解释下方历史结果。2026-09-05 当前 baseline 代码已是指标 checks `2`、state checks `2`，每频 `6` 条、七频 `42` 条，资产分区仍为 `14`；以当前 check 常量为准。M2B 不修改 check 集合、daily job/sensor 或历史事件。

当前执行事实：

```text
baseline cutoff = 2026-06-05
reported_event_count = 56
reported_asset_partition_count = 14
quick audit sample_readiness = 14/14 True
```

如果误做历史逐日全量 events，按原执行时约 `3019` 个交易日和每频 `8` 条的旧集合估算：

```text
3019 * 7 freq * 8 events = 169064 events
```

该做法禁止作为 M12 默认执行口径。

该代码硬化缺口已在 2026-09-05 清退 M2B 修复：`report-gold-stk-mins-qfq-macd-kdj-baseline-events` 不再默认选择全历史。CLI 在实例访问前校验日期/显式 keys；公开 Python report 的日期也必填并复用校验。report 内只执行一次 baseline event planner，实际 keys 恰好为请求当天后，才进行文件审计和原有补事件流程；零/多/错日期结果失败，不能等报告返回再检查。原文件审计内部仍会再次调用 history planner，底层 history 规划共两次，本轮不新增预规划。只读 planner/final audit 仍支持多日。测试及执行证据见 [清退 LLD M2B](legacy-lake-console-kopia-old-lake-bootstrap-retirement-low-level-design-v1.md#m2b当前-cli-安全加固)。本轮仅做隔离验证，未再次操作正式 baseline。

### 13.2 复核方式

baseline/future tracking 复核使用：

1. 历史文件 fact set：指标 stock-year 文件、state partition 文件、row count、key uniqueness。
2. baseline materialization/check event count。
3. baseline readiness sample。
4. future daily partition 的正常 materialization/check events。

禁止把上千分区逐个调用 readiness 作为主审计。

## 14. 开发落地步骤

### M12A 设计与契约

1. 新增字段契约：`GOLD_STK_MINS_QFQ_MACD_KDJ_SCHEMA`、`GOLD_STK_MINS_QFQ_MACD_KDJ_STATE_SCHEMA`。
2. 新增 path helper：指标 stock-year path 与 state daily path。
3. 新增 freq/params/version 契约常量。
4. 静态门禁：M12 不得改 raw/silver freq，不得出现 Tushare/prod DB request。

### M12B DuckDB 计算 helper

1. 实现 MACD/KDJ DuckDB SQL helper，正式路径禁止 recursive CTE。
2. 支持从 state seed 递推最新日。
3. 支持历史 `freq/year` 批次计算。
4. 单测覆盖 MACD、KDJ、首 bar 初始化、HHV=LLV、跨日 state 延续。
5. benchmark 已覆盖真实 `1m 2026-05` 临时写出路径，耗时 `152.166s`，低于 `30 min` 拒绝门槛。

### M12C Assets 与 checks

1. 新增七组 `multi_asset`：指标结果 + state。
2. 注册 definition metadata、path_template、deps、pool。
3. 新增指标 checks 和 state checks。
4. static gate 确认 job 文件无 SQL/路径拼接。

### M12D Daily job/sensor

1. 新增 daily update job，只选 M12 assets + checks。
2. 新增默认 STOPPED run-status sensor，监听 qfq daily 与 qfq factor repair 成功。
3. sensor 等待同日两个 qfq 上游都成功后，检查 qfq 七频度 ready、上一交易日 state ready、目标指标状态。
4. sensor 不做历史深扫，不调用 `get_asset_check_execution_history`。
5. qfq repair 历史重写不阻塞 M12 daily；sensor 不传递项目自定义 run tags，asset 写前 guard 只校验同日 qfq factor repair check event 是否全绿。

### M12E Repair

1. 新增指标 repair job/op。
2. qfq repair 后必须能提交或提示 M12 repair 范围。
3. 当前代码从 previous expected state 递推到 expected repair range，禁止自动跳到任意更早 state。
4. repair completion check event 覆盖指标 assets 和 state assets。
5. repair op 成功后 emit 14 条 `gold_stk_mins_qfq_macd_kdj_repair_completed_check`，供最终 readiness/收口判断。
6. `gold_stk_mins_qfq_macd_kdj_repair_job_sensor` 在 M12 daily 成功后按 qfq repair metadata 自动触发 scoped repair。
7. repair op scoped state 写入必须 merge affected codes，禁止覆盖整日 state 导致未受影响股票 state 丢失。
8. 自动 repair 上限固定 500 个 affected codes，超过上限只提示人工处理。

### M12F History bootstrap

1. 新增 plan/generate/audit/report-baseline/final-audit CLI。
2. dry-run 先测算七频度全量规模。
3. 临时 lake 样本验证后再申请正式写入。
4. 正式补录已按 `Direct Lake Bootstrap + Baseline/Future Event Tracking` 执行完成。
5. 禁止历史逐日 event backfill；全历史文件完成后只写 baseline cutoff events，当前 baseline cutoff 为 `2026-06-05`。
6. 2026-09-05 已补代码硬门禁与正反例：baseline event CLI/Python report 强制单日且实际单分区，禁止默认全历史 dry-run/backfill；其它历史生成/规划/审计的范围能力不变。

## 15. 测试计划

单元测试：

1. MACD 递推：首 bar、连续 bars、跨日 seed。
2. KDJ 递推：9 窗口、HHV=LLV、跨日 lookback、J 超出 0-100 不失败。
3. 老股票缺 state 失败，新股首日允许初始化。
4. 指标 path 接受七频度；raw/silver path 仍拒绝 90/120。
5. state 与指标尾行一致。
6. qfq repair 触发后，M12 repair 范围从受影响起点向后覆盖。
7. MACD 柱固定为 `2 * (DIF - DEA)`。
8. qfq factor repair 未成功时，M12 daily sensor 不提交 run；人工 daily asset run 写入前失败。
9. qfq factor repair 成功但 metadata 显示历史重写、且 daily run 缺少受控 qfq repair tags 时，人工 daily asset run 写入前失败。
10. qfq factor repair 成功且没有历史重写时，M12 daily 可以继续日常增量。
11. qfq factor repair 历史重写且 M12 repair completion 覆盖目标日期后，最终 gate 可以通过。
12. M12J 新增测试：qfq daily 与 qfq factor repair 任一未成功时，不触发 M12 daily。
13. M12J 新增测试：二者同日成功后，M12 daily run-status sensor 提交同日 daily run。
14. M12J 新增测试：M12 daily 成功后，qfq repair `repair_required_code_count=0` 时 repair sensor skip。
15. M12J 新增测试：`1..500` 个 affected codes 且 code list/hash 完整时，repair sensor 提交 scoped M12 repair run config。
16. M12J 新增测试：`repair_required_code_count>500`、缺完整 code list 或 hash 不匹配时，不自动提交 repair。
17. M12J 新增测试：scoped state repair 只替换 affected codes，保留同一 `freq/trade_date` state 文件中的未受影响股票。
18. M12J 新增测试：completion event 覆盖 code hash、code count、freqs 和日期范围；缺字段或范围不足 fail closed。
19. M12K 新增测试：repair op 缺少 `qfq_factor_repair_trade_date` 且缺少显式 `start_trade_date + stock_codes` scope 时 fail closed。
20. M12K 新增测试：repair op 收到空列表或空白代码且未提供 `qfq_factor_repair_trade_date` 时 fail closed，且不调用写入 helper。
21. M12K 新增测试：只填写 `qfq_factor_repair_trade_date` 时，op 可从 qfq repair metadata 派生 start date、stock codes、hash 和 event ids。
22. M12K 新增测试：`qfq_factor_repair_trade_date` 模式下手填股票列表与 metadata 不一致时 fail closed。

静态/契约测试：

1. M12 assets 使用 qfq deps，不依赖 raw/silver/Tushare/prod DB。
2. M12 assets/op 使用 `GOLD_STK_MINS_QFQ_WRITER_POOL`。
3. daily job selection 只含 M12 assets + checks。
4. sensor 默认 STOPPED，run key 固定。
5. M12 sensor 必须引用 qfq factor repair readiness helper，且禁止调用 `get_asset_check_execution_history`。
6. M12 asset 写入前必须调用同一 qfq/M12 repair guard，且调用点在 DuckDB 写 Parquet 前。
7. M12 repair op 必须 emit `gold_stk_mins_qfq_macd_kdj_repair_completed_check`。
8. 历史 bootstrap 工具不逐 partition 深扫 readiness，不做历史逐日 event backfill。
9. `defs/jobs/**` 不出现 DuckDB SQL、Parquet 写入、路径拼接。
10. M12 正式 helper/bootstrap/repair 源码不出现 `WITH RECURSIVE` 或 recursive CTE。
11. M12J sensor 必须使用 run-status coordination 或等价 event-driven 触发，不得新增第二套并行 daily polling sensor。
12. M12J 自动 repair 不得默认全市场；必须从 qfq repair metadata 读取 `repair_required_codes`，并执行 500 code 上限门禁。
13. M12K 静态门禁：repair op 必须支持 `qfq_factor_repair_trade_date` metadata 模式，必须调用 qfq factor repair status helper；`stock_codes` 不允许“为空表示全市场”文案，空列表 guard 必须在写入 helper 前，completion metadata 不允许 `stock_code_scope=all`。

验证命令：

```text
python3 -m py_compile <touched python files>
python3 -m unittest <M12 related tests>
.venv/bin/ruff check <touched python files>
git diff --check
python3 scripts/check_docs_integrity.py
```

后续正式 Dagster job/sensor/backfill/materialization/check、正式 lake 追加写入、正式 `DAGSTER_HOME` event 修正或重写，均需单独列命令审批。M12 历史文件直写和 `2026-06-05` baseline event 写入已完成，不再列为待执行项。

## 16. 参考依据

1. 当前 qfq Dagster 代码：`gold_stk_mins_qfq_*` assets、`stock_mins_qfq_daily_update_job`、`stock_mins_qfq_daily_sensor`、`stock_mins_qfq_factor_repair_job`。
2. 当前 qfq 设计文档：`lake_console/docs/design/dagster-stk-mins-asset-design.html`。
3. M11 90/120 主口径已并入当前 qfq 设计文档：`lake_console/docs/design/dagster-stk-mins-asset-design.html`。
4. 旧分钟指标执行体系已退出；必要历史结果见[初始化与修复总账](dagster-bootstrap-legacy-links.md)。业务公式和state以本文为准，现行候选、摘要与续跑以[写入方案和LLD](dagster-stk-mins-qfq-staging-write-plan-and-low-level-design.md)及其后续修正为准；[R5 LLD](dagster-stk-mins-qfq-macd-kdj-reconciliation-recovery-r5-low-level-design.md)保留repair范围硬化及7月恢复的历史依据，不是本次日更开发或正式执行卡，其旧备份/quarantine操作不得用于本轮。不复用旧CLI/队列/锁。
5. Tushare `stk_factor_pro` 本地文档：`docs/sources/tushare/股票数据/特色数据/0328_股票技术面因子(专业版).md`。
6. DuckDB 文档：window function、`COPY ... TO` Parquet；M12 把 recursive CTE 仅作为 benchmark 中已证明不可接受的反例，不作为正式实现能力。

## 17. MACD/KDJ日更读取修正方案（2026-10-30）

### 17.1 目标、现状与本轮授权

目标是让七频MACD/KDJ正常日更先选出必要行情，再调用现有递推公式，消除近两年全市场历史临时表和完整历史排名。用户已确定先处理技术指标日更，再处理历史repair。文档阶段先审计并落回原文档，以`4a4a689e`提交；随后管理员明确批准按LLD开发、隔离测试和实现对账，完成记录见LLD第19.12节。本轮未获正式补数授权，不读取正式行情、不触发job、不改sensor。

2026-10-29的失败run为`98f3d25c-1380-47da-b079-b15701bdbbce`，目标日2026-10-29。已有日志定位到1分钟`_create_macd_kdj_source_tables`中创建计算表的SQL；同run其他六频的indicator/state已物化且24项检查通过。1分钟失败发生在`publication.bind`及候选写出前。上述是29日已取得的证据，不代表30日实时缺口已经重新核验。

当前代码先由`discover_gold_stk_mins_qfq_source_year_paths`枚举目标年和上一年，再将截至目标日的全市场七列行情放入`macd_kdj_source_all_rows`，对全部历史做`row_number`，之后才截取目标日及前8根。此路径自2026-06-07提交`4ba74ece7dd3`已存在，不是近期staging改造或版本回退引入。保留上一state与少量行情有计算依据，但未找到先处理整两年全市场的必要性说明。

DuckDB的4GB异常是单个字符串/二进制值的长度检查，不是已经生成4GB磁盘文件。当前SQL无全量字符串拼接，现有Python栈不足以确定具体内部调用方；本轮修正已证实的计算范围问题，不能预先宣称已经定位或保证消除该内部异常。

### 17.2 必须保持的业务口径

1. 仍使用原七频、原目标日及原qfq来源，不读Raw、Silver、Prod或Tushare行情，不改前复权公式。
2. 保持原发现集合`Y/Y-1`。按每股目标日前实际K线时间选最近至多8根，不以固定8天、昨日或固定日期下界替代；不新增`Y-2`读取或不足8根的guard。不把“本次集合无更早行情”升级为已经证明真实上市首日。
3. 上一state必须来自上一**应有交易日**。原允许无前日文件初始化的日历首日规则、老股票缺自身state时的错误、无前序行情股票的现行seed均保持。原候选集合中存在目标日前行情时，不能因输入裁剪丢掉这一证据，让缺state老股票被重新初始化。
4. 前序K线仅构造RSV窗口；只有目标日K线进入EMA/DEA/K/D递推。保留参数、公式、算法版本和1024根分段，MACD柱仍为`2×(DIF−DEA)`。
5. 保留完整前日state并统一生成今日state，无当日行情的股票承接旧值及旧`last_trade_time`。整体`initialized_without_previous_state`仍由完整前日state是否为空决定，不按某只新股判断。
6. 全部目标日结果准备完成后，只冻结一次完整indicator/state输入及目标清单；继续使用原年度合并、候选校验、一次摘要、逐文件提升和冲突拒绝。禁止逐股调用整个writer或对共享state分股直接覆盖。MACD的文件锁不锁QFQ来源，必须保留原共享writer pool并在未来执行前核对其串行配置；日更仅增加实际来源/前日state的文件身份核对，发现变化在bind或提升前停止。它是输入文件一致性保护，不新增价格、条数或股票业务guard。
7. 不改历史repair/history的日期、代码、公式、输入准备SQL或完成事件；只对其共用的写出部分做等价提取并回归。repair仍有大历史表及state关联的性能风险，留待下一轮审计和修正，本轮不宣称已解决。
8. 保留asset、multi_asset、job、sensor、pool、run key、checks、paths、schema、公开函数现有签名及返回值。除必要分批进度日志，不增加产品功能、运营参数或新入口。
9. 本次优化必须与原计算结果等价：不改公式、上一state及逐股时间顺序，不重新初始化已有股票，不提高数值容差。不得因本次优化重刷已完成历史、重建历史state、迁移下游、清理DG历史事件或追加历史补账。若实现不能在此条件下继续原数据，停止正式使用，修正代码/方案并重新验收，不能以重刷历史作为补救。原上游因子变化确需的repair及其去重保持，不新增优化引起的repair名单或范围。

### 17.3 日更处理顺序

1. 原资产wrapper完成目标日、前日state及qfq/factor-repair门禁。来源路径仍由原发现函数规划，Python只保存路径和小型计数。
2. 每频在同一个publication锁和同一DuckDB连接中，读取完整前日state一次；按股票代码稳定排序，每64只为一批。原共享writer pool继续隔离受管的QFQ日更、因子repair与MACD写入；读取前后及bind/提升前只核对实际来源文件身份，不增加来源SHA或冻结行情副本。这是内部工作组织，不是股票数量上限；超过64只自动进入后续批次，不截断、不报超限。
3. 批内直接筛当日行情；对有当日行情的代码，从当年文件聚合最近至多8根前序K线。当年不足8根时，只读取这些代码原集合中的上一年文件，再从至多16根候选中取最近8根。没有当日行情的代码不回读历史。
4. 只对“当日行情＋少量前序K线”计算窗口，调用原递推函数，并将当日结果留在统一工作表。每批结束释放其来源选择/计算临时表，不在内存或staging保存全市场历史。
5. 全部批次完成后用原SQL生成仅含目标日的指标替换表和完整state替换表；原完整写入流程仅调用一次。若全频率没有目标日结果，仍按原空结果规则失败。

临时SQL可使用`arg_max(struct_pack(...), trade_time, 8)`取得每股最近8条，再按时间升序计算；这是有界临时结果，不是新增正式LIST字段。不能先`list`全部历史后切片，也不能先对全市场两年历史排名再过滤。

### 17.4 代码、调用方及影响面

本轮已用CodeGraph `explore/impact`查看来源准备、公共writer和资产wrapper；其结果没有完整识别decorated repair入口，另按当前源码核对了`ops/gold_stk_mins_qfq_macd_kdj_repair.py`、`bootstrap/stk_mins_qfq_macd_kdj_history.py`和直接测试调用，不能把索引漏报当无消费者。

| 代码/消费者 | 拟处理 | 不得改变 |
| --- | --- | --- |
| `defs/stk_mins_qfq_macd_kdj.py`日更wrapper及输入准备 | 新增私有日更准备函数；提取原工作表创建、结果/state生成及prepared结果写出职责 | 原公共writer仍供repair/history使用，原历史准备路径不切换 |
| `_insert_macd_kdj_segment_rows`、`_populate_macd_kdj_indicator_work_rows` | 复用；每批代码互不重叠，统一工作表只累计目标日 | 公式、seed、分段和数值容差 |
| `io/stk_mins_qfq_publication.py`与两个年度/state writer | 调用现有实现，不修改其状态机、摘要或路径规则 | 完整目标绑定、失败现场、逐文件完成记录、冲突拒绝 |
| MACD/KDJ assets/checks/sensors/catalog | 入口、检查、字段和时序均保持 | 14个资产和28项原checks、daily后再repair |
| QFQ、九转、历史repair/history | 不新增计算逻辑或改读取依赖 | 九转从QFQ行情而非MACD/KDJ读取；原repair名单/范围及已完成批次去重不变 |
| `src/foundation/clients/local_lake/stock_mins_reader.py` → `StockMinuteQueryService.read_indicators` → 股票详情`minute-indicators`接口 | 现有真实文件消费者，只核对兼容，不修改实现 | 原年度路径、12列schema、代码/频率/日期时间键、条数、六项指标、params/version和分页语义不变 |
| `wealth/src/pages/stock-detail/StockDetailPage.tsx`及分钟图适配器 | 页面请求上述指标接口，按日期时间对应K线 | 不要求前端/API改版或历史数据迁移；这是代码链存在性，不宣称当前环境已启用本地能力 |

内部股票批量、DuckDB设置和全部读写边界见LLD第19.5—19.7节；本轮无正式配置或合同变更。

### 17.5 读写与性能口径

缩小的是参与排序和递推的中间数据，不保证年度文件只物理读取8行。日更当日筛选与历史尾部聚合可能各扫描一次当年文件；原checks仍独立发现/读取来源，年度指标仍需保留其他日期并合并重写。本轮不通过修改checks或新增state缓存隐藏这些成本。

正常、一次必要续跑和最后验收的逐项公式、历史metadata依据及条件预算统一在LLD第19.7节，不再复制另一组数字。该预算是未来正式执行前核定的估算，非实际I/O测量、非配置限制、非正式读取或重跑授权。本轮开发只使用人工临时文件，正式行情读取和正式写入均为0；开发与隔离成本见19.12。

### 17.6 验收与负面影响防范

验收须同时证明数值正确与读取路径正确。七频独立字面金样本覆盖MACD/KDJ及state；另外覆盖跨年、长停牌、原集合不足8根、集合外更早年份、新股、缺state老股、无当日行情、全空结果、跨64只批次边界、年度其他日期保留、候选失败和中断续跑。具体代码点、正反例与复用测试见LLD第19.8节。

本次只允许目标日指标/state更新；年度文件因存储布局需要重新写出时，非目标日期业务记录必须保持。文件字节或mtime改变不等于历史指标重算；旧候选摘要不同只影响该次临时结果能否接续，不得据此扩大到历史重刷。现有分钟指标reader/API的字段、行键及历史查询兼容也纳入隔离验收。

只比较新旧函数结果不构成独立数值依据；旧结果可作补充对账，不能生成全部expected。小样本通过不证明4GB异常已消除，也不证明当前正式29日/30日数据完整。

### 17.7 失败、恢复及后续顺序

批内计算失败或来源身份变化时停止，尚未bind则不生成年度候选、不替换正式文件；bind后、提升前发现来源变化则保留候选并停止，不用新输入覆盖本次结果。内部批次不是新的持久化恢复单元，不承诺从中间计算批次继续；必要续跑仍须重新生成当日替换输入并核对摘要。不能把冻结replacement结果称为已经冻结QFQ来源；无法排除不受原pool约束的来源writer时，不进入正式执行。

新旧实现即使数值在容差内，浮点尾数或Parquet编码仍可能改变输入摘要，不能自动接管旧operation、跳过摘要校验或把修复后的新代码强行用于旧候选。后续正式恢复须先有界核对真实未完成频率、旧operation及当前来源身份，单列执行卡；29日同run六频历史成功记录不应被整job重跑覆盖。

顺序为：完成方案/LLD及独立审文 → 获准后仅开发日更和等价共用代码提取 → 隔离正确性/读取路径/恢复回归及实现对账 → 另按当时缺口和具体读写范围审批正式恢复 → 日更稳定后再处理repair性能问题。本轮前三项已完成，停在正式恢复之前；本次隔离测试不替代正式执行批准。

### 17.8 方案与LLD对应

| 本文条款 | 原写入LLD | 验收内容 |
| --- | --- | --- |
| 17.1、17.2 | 19.1、19.2 | 状态、代码依据、来源/日期/合同不变 |
| 17.3、17.4 | 19.3—19.5 | 私有函数分工、每股至多8根、批量与消费者 |
| 17.2第6项、17.7 | 19.6 | 一次完整冻结、候选、摘要及恢复 |
| 17.5 | 19.7 | 正常、续跑、原检查及清理成本 |
| 17.6 | 19.8 | 独立预期、正反例、其他消费者回归 |
| 17.7 | 19.9、19.10 | 开发/正式执行分界、审文结果与未完成项 |
| 17.9 | 19.11 | 本轮讨论的最终口径、不重刷历史的交付门槛、逐项证据 |

2026-10-30文档对账已完成：两轮独立代码/文档复核修正了输入合同测试层次、停牌state时间解释及分批来源一致性三处遗漏，复审未发现本轮设计的阻断矛盾。文档完整性、改动空白及新增跨文档链接检查通过，详见LLD第19.10节；这不是开发、运行或正式数据验收。

### 17.9 讨论收口：计算等价与不重刷历史是交付条件

本节将管理员随后确认的要求归并为后续开发必须遵守的说明，与17.2第9项及LLD第19.11节共同验收，不新增计算口径。

**一、只改变取数和分批组织，不改变指标算法。** 原来先装载近两年全市场历史再截取必要行；改后先选出相同必要行再调用原计算函数。新旧对账必须使用同一有效来源集合、同一目标日、同一正确前日state、同一逐股时间顺序和原数值容差。MACD/KDJ公式、参数、算法版本、每股时间顺序、原1024根分段及前日seed不变。必要的私有函数提取与来源身份核对只改变组织和安全检查，不允许成为改变数值、字段或业务范围的理由。新旧结果一致是必须验证的交付要求，不是当前尚未开发即可宣称已证明的结果。

**二、前8根行情不代替历史递推。** KDJ每根RSV取当前这根及此前8根的高低价。以当日1分钟K线为例：第一根使用历史8根＋当日1根，第二根使用历史7根＋当日2根，第九根开始窗口全部来自当日；当日不足9根的较长频率仍需用跨日实际行情补窗口。K/D继续从上一应有交易日state保存的K/D递推，J仍为`3K−2D`；MACD继续从原state的EMA/DEA递推。更早历史的递推影响由state承接，不能取8根后从50或首价重新启动，不能把prefix再算入state一次。本轮仍保持原两年来源；不足8根时沿用原部分窗口，不能宣称跨两年以上停牌的完整窗口问题已修复，也不得为此擅自扩读或重刷历史。

**三、不重刷已完成历史是硬性验收条件。** 本次改动完成并正式使用的前提，是原state能够直接承接、目标日结果与原计算等价、原数据和下游合同兼容。不能以重算历史指标、重建历史state、迁移下游或清理DG历史事件来适配新实现。任一条件未满足就视为本轮开发未完成，继续修正代码/方案，不进入部署或正式补数，不通过放宽容差、跳过检查或重刷历史补救。

**四、年度文件重新写出与历史重算分开验收。** 合入目标日可能重新写出该股票当年的Parquet文件，这是原日更写入方式；非目标日记录必须原值保留，目标日之外的state文件不改写。文件字节、inode或mtime变化不等于旧指标被重新计算，但“文件格式允许变化”也不允许改变旧记录的值、键、类型、数量或日期范围。保持原年度合并行为不代表本轮获准重跑已完成日期。

**五、旧候选恢复只处理该次未完成范围。** 新旧临时结果的摘要不同会导致原publication拒绝接续；该拒绝不表示历史业务数据无效，不要求DG重建，也不使API消费者失效。保留既有正式结果和旧记录，按实际未完成日期/频率核定恢复办法，不混交新旧候选，不借此重跑整个job或已经成功的频率。新代码不保证自动接管旧候选，但必须能直接继续使用原正式历史及前日state。

**六、不新增历史repair范围，不改变真实下游。** 已有因子变化要求的repair仍由原上游名单、日期、身份和完成去重决定；读取优化本身不能生成新名单、扩大范围或重跑已完成批次。后续日更使用原state；股票分钟指标reader/API/前端继续使用原年度文件合同；九转读取QFQ及自己的前日结果，不以MACD/KDJ作为计算输入。这是在说明计算来源，不改变既定执行顺序、门禁或调度。本轮不开发repair性能改造。

**七、分批和只保留8根不等于只读取8行文件。** 批次按64只股票组织，不按时间截成若干段后再遍历两年历史计算；当年足够8根就不打开该股上一年文件，不足时才从原上一年集合补选。年度Parquet可能仍需扫描较多数据，当日选择与历史尾部选择也可能各读一次当年文件；原年度合并和checks读写保留，沿LLD第19.7节计费，不宣称年度I/O全部消失，不新增全局审计或正式性能试跑。

本节为已确认开发约束；本轮已按LLD第19.11节逐项取得开发及隔离证据，结果见第19.12节。代码及验收记录随本次实现提交归档，正式数据、job/sensor和补数未操作，不能以审文或隔离通过替代正式执行验收。

### 17.10 提交后独立审计与29日剩余恢复范围（2026-10-30）

实现已提交`5a0b13401`。本轮三条独立审查分别检查计算、发布/repair/下游、测试真实性，未发现阻断或必须重刷历史的问题；不重复运行已经通过的315项测试及23项子测试。报告见[提交后审计](../../reports/macd_kdj_daily_read_20261030/post_commit_audit_20261030.md)。65股用例的活跃股票前日状态相同，不能单靠该例证明两个已有股票互换状态时必然失败，这是测试可增强项；当前公式按`ts_code/freq`关联，相关原函数AST未变，未发现串用错误，不以此推定需要改计算或重刷历史。

本轮有界运行核验确认：29日原run`98f3d25c-1380-47da-b079-b15701bdbbce`仍仅1m失败，其余六频及24项检查成功；1m目标state不存在、原operation目录为空，前日28日state存在；当前无活动run，writer pool限制为1且空闲。只恢复29日1m的indicator/state及原四项检查，不重跑六频、28日或其他日期。

正式恢复按[原写入LLD第19.13节](dagster-stk-mins-qfq-staging-write-plan-and-low-level-design.md#1913-29日1分钟正式恢复执行方案已获专项批准)办理：刷新代码位置，使用原job的原生FROM_FAILURE续跑，保留原root身份；不手工计算或直写补录。该步预计读160GiB、写26GiB、额外空间32GiB，包含原检查和收尾，不自动重跑。管理员已明确回复“确认，批准”；执行事实继续记入LLD19.14。

MACD repair sensor在批准前为RUNNING；29日原因子repair产物已有2股、2014-01-02至2026-10-29的待修历史。日更成功可能自动触发该历史repair，不能假装它没有额外读取。因此此次1m恢复的专项申请同时列明暂缓该sensor自动触发；先保存并保留原cursor/lastRunKey。历史repair仍按原job实际名单和顺序推进，未获该历史范围批准前不执行、也不提前恢复可能启动它的开关。管理员已批准本次1m及暂缓该sensor的精确范围，实际操作结果以LLD19.14为准，不把批准当作已经执行成功。

本次1m正式恢复已成功：09:06:14—09:08:48，5,570份指标文件合入29日1,342,370行，当日state为5,595行；5,571个文件均完成原校验和发布，四项原检查均通过。结合原六频成功记录，29日MACD/KDJ七频日更现已齐备；这不代表2股历史repair或其他数据集已完成。未做额外全局/年度审计，没有自动重跑。receipt及必要冻结输入保留、候选文件已为空；MACD repair sensor保持STOPPED，原身份/cursor/lastRunKey不变，后续范围和预算批准后再按原job衔接并恢复。

### 17.11 29日原因子产物对应的2股MACD/KDJ repair

管理员要求继续repair、完成修补并提交。本步复用现成`gold_stk_mins_qfq_macd_kdj_repair_job`，不修改计算或再开发repair优化。实际上游名单是`000878.SZ`、`688563.SH`，起点2014-01-02、终点2026-10-29，固定七频；名单、起点、代码hash和上游batch都由原因子repair产物决定，不能手工增删。本次历史重算是原复权因子变化本来要求的repair，与日更读取优化不得新增历史重刷的要求不冲突；其他股票指标不重算，完整共享state保留其他股票。

实现及预算已只读核清，细节见[原写入LLD19.15](dagster-stk-mins-qfq-staging-write-plan-and-low-level-design.md#1915-29日2股历史repair执行方案与lld)。实际读取2股119份QFQ共28,812,168B，合并2股119份既有指标共65,863,089B、3,116日七频21,812份共享state共3,847,741,455B；这里只做metadata/stat，没有读行情。正常一次含原候选校验/单次摘要、原14项completion和收尾，预算读20GiB、写10GiB、额外空间12GiB，不是新增运行限制。该历史范围仍需根AGENTS规定的具体读取批准；29日1m的160/26/32GiB批准明确不覆盖此repair。

批准后保持repair sensor暂停，通过原job仅启动一次；原op从最新产物复核完整scope，七频全部完成后写14项completion。本次不补普通日更物化、不重跑日更和原因子任务，不追加历史行情审计。成功后恢复原sensor为RUNNING、保留原cursor/lastRunKey；原sensor用同batch完成检查去重，不会因为手工job没有sensor run key而重复修复。失败停止，保留完成频率及现场；现成repair每频独立operation，不能照搬日更root的自动续跑承诺。执行事实和提交结果随后按真实结果记录，不预填成功。
