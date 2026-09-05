# M12: Gold stk_mins qfq MACD/KDJ 指标资产设计方案

状态：M12 代码口径已落地到 Dagster definitions、Catalog、checks、job/sensor、repair op/job、历史直写与 baseline event CLI。正式历史文件已完成全量直写并通过 full file audit；`2026-06-05` baseline cutoff 已写入 `56` 条 runless materialization/check events，scoped quick final audit 已确认 14 个 indicator/state asset-partition 全部 ready。M12J 自动 repair 链路已落地为代码口径：当 `stock_mins_qfq_daily_update_job` 与 `stock_mins_qfq_factor_repair_job` 同日都成功后，run-status sensor 先触发 M12 daily；M12 daily 成功后，repair run-status sensor 再按 qfq factor repair affected codes 自动触发 scoped M12 repair，自动 repair 上限固定为 `repair_required_code_count <= 500`。M12K/M8 安全口径已收敛：repair 只支持真实 qfq factor repair upstream batch；自动提交和 Dagster UI 人工重放都必须显式提供 `qfq_factor_repair_trade_date`、`start_trade_date`、`stock_codes`、`repair_required_codes_hash`、`upstream_batch_id`，并与上游 metadata/status 完全一致。repair op 不支持无上游 batch 的散装手工修复，也不提供空列表全市场重写入口。R5-P0 已进一步收紧 scoped repair：repair source discovery 只读取 affected code 的现存 year 文件，默认 daily/check/history 调用仍保持全市场；repair 在写任何文件前必须确认完整 target range 的 state 文件存在，并且只接受固定全七频度，以免 completion check 误报全量完成。M12L 的旧普通 qfq materialization/check event reconciliation 方案已撤销：qfq factor repair 继续只负责重写 qfq 文件并写 repair check；repair check metadata 是历史 qfq 文件改写账本；不再按历史 qfq asset partitions 补普通 materialization/check events。M12 daily 不等待全历史普通 qfq event 补齐，而是认同日 qfq daily 成功 + qfq factor repair 成功作为当前日可继续门禁。股票分钟线连续性专项 M7/M9/M10 已把 M12 daily run-status sensor、daily asset write 和 repair op 全部收敛到 `silver_trade_calendar` 的 previous expected / expected range 口径：daily writer 与 repair op 都要求 exact previous expected state，不再自动回退到任意更早 state；只有目标或 repair start 是 expected calendar 第一个交易日时，才允许无 previous state 初始化，`STK_MINS_MACD_KDJ_BASELINE_START_DATE` 只作为日历读取下限。2026-07-15 已确认：QFQ 计算正确性由受保护测试金样本保障，production check/readiness 不二次计算 QFQ 公式；已提交但未启用的 as-of basis 实现必须在后续专项中删除，不执行 Lake 初始化。`gold_stk_mins_qfq_macd_kdj_check_refresh_job` 是 checks-only 维护入口，用于补正确 partition 归属的 check events，不 materialize 或重写 Parquet。daily/repair sensors 代码默认 `STOPPED`；实际是否启用必须读取正式 Dagster instance 或 UI，不以本文档推断。

> 2026-08-13 当前修正：Gold QFQ 5m/15m/30m/60m 不应输出独立 09:30，现有四频
> indicator 与递推 state 必须在 QFQ 重建后从历史基线顺序重建。1m 保持 09:30；
> 90m/120m 当前输出合同正确，但后续必须直接从 Silver 30m/60m 构造 QFQ source，
> 不再依赖已修正 Gold 30m/60m。完整范围和执行顺序以
> [A 股分钟线 Gold 标准 K 线合同与历史重建 LLD](./dagster-cn-a-minute-gold-canonical-bars-rebuild-low-level-design.md)
> 为准。

更新时间：2026-07-15

## 1. Summary

M12 新增基于七频度 `gold_stk_mins_qfq_*` 的分钟技术指标资产，第一版只做：

- `MACD(12,26,9)`
- `KDJ(9,3,3)`

输入只读当前 gold qfq 分钟线：

```text
gold_stk_mins_qfq_1m/5m/15m/30m/60m/90m/120m
```

不读取 raw/silver/Tushare/prod DB，不生成 EMA 正式指标集，不接前端 serving。M12 已新增 daily sensor，代码默认 `STOPPED`；正式启用状态必须读取 Dagster instance 或 UI 后确认。

M12 必须持久化递推 state。日常计算最新一天时，只允许读取上一交易日 state、当日 qfq 行和 KDJ 所需的有限历史 lookback，不允许从历史起点重算。

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
| `last_trade_time` | `TIMESTAMP` | 该股票该频度在该交易日最后一根已处理 bar |
| `macd_ema_fast` | `DOUBLE` | MACD 内部 fast EMA state，N=12 |
| `macd_ema_slow` | `DOUBLE` | MACD 内部 slow EMA state，N=26 |
| `macd_dea` | `DOUBLE` | MACD 内部 DEA state，N=9 |
| `kdj_k` | `DOUBLE` | KDJ 下一日递推所需 K state |
| `kdj_d` | `DOUBLE` | KDJ 下一日递推所需 D state |
| `params_key` | `VARCHAR` | 固定为 `macd_12_26_9__kdj_9_3_3` |
| `indicator_version` | `INTEGER` | 算法版本，第一版为 `1` |

KDJ 的 `HHV/LLV(9)` 不写入 state。日常计算时从 qfq stock-year 文件读取每只股票上一交易日之前最多 8 根历史 bar，加上当日 bar 构造窗口。这样 state 保持扁平字段，避免在正式 Parquet 契约里引入 JSON 或 LIST 嵌套字段。

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
| state 行数 | 每个 `freq/trade_date` 约等于当日该频度有 qfq 行的股票数 |
| 指标文件数 | 约等于 qfq source stock-year 文件数；正式数必须由只读 plan 给出 |
| state 文件数 | `freq_count * partition_count`，当前 7 频度、约 3019 个交易日时约 21133 个文件 |
| 历史核心批次 | `freq -> year`，不按股票主循环，不按日期切断递推，不使用 recursive CTE |
| 日常核心扫描 | 目标日期 qfq rows + 每股票最多 8 根 KDJ lookback + 上一交易日 state |
| Repair 核心扫描 | 当前代码扫描受影响股票从 `start_trade_date` 到 qfq factor repair `repair_end_trade_date` 的 expected trade date range，并使用 previous expected state 作为递推起点 |
| DuckDB 配置 | 统一 `connect_configured_duckdb`：temp `/Volumes/datasource/.goldenshare_duckdb_tmp`，max temp `512GB`，memory `16GB`，threads `4`，`preserve_insertion_order=false` |
| 排序 | 所有正式输出必须 SQL `ORDER BY ts_code, trade_time` 或等价稳定排序 |
| 写入 | `.tmp -> validate -> os.replace`，指标 stock-year 和 state partition 都必须原子替换 |
| Python 职责 | 参数校验、路径发现、批次规划、DuckDB SQL 调度、样本汇总 |
| Dagster event | 历史只写 baseline cutoff events，未来按 daily job/sensor 记录；禁止历史逐日全量 event backfill |
| 禁止 | Python 明细递推、Python 明细写 Parquet、正式 recursive CTE、按日期切断递推、老股票中途初始化、历史逐日 event 深扫 |

不可接受阈值：

1. 只读 plan 不能给出 source row/file/event 上界。
2. 正式 helper 或 bootstrap/repair SQL 出现 `WITH RECURSIVE`、`recursive` 或等价逐行递归实现。
3. 需要按 `stock_code -> freq -> year` 主循环才能完成。
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
4. 旧分钟指标执行体系已退出；必要历史结果见 [初始化与修复总账](dagster-bootstrap-legacy-links.md)。当前公式、baseline、状态与恢复约束以本文及 [R5 LLD](dagster-stk-mins-qfq-macd-kdj-reconciliation-recovery-r5-low-level-design.md) 为准，不复用旧 CLI/队列/锁。
5. Tushare `stk_factor_pro` 本地文档：`docs/sources/tushare/股票数据/特色数据/0328_股票技术面因子(专业版).md`。
6. DuckDB 文档：window function、`COPY ... TO` Parquet；M12 把 recursive CTE 仅作为 benchmark 中已证明不可接受的反例，不作为正式实现能力。
