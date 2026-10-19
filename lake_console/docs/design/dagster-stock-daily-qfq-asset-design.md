# 股票日线前复权：资产设计与历史回刷修复方案

当前状态（2026-10-19）：管理员已认可“先完善回刷能力，再用它修复历史数据”的方向和顺序。
本次方案见[第10节](#qfq-history-repair-20261019)，尚未开发或正式执行；原 LLD 第19节记录方向，[第20节](dagster-stock-daily-qfq-asset-low-level-design.md#qfq-code-design-20261019)已按代码复核细化函数、参数、文件记录、SQL、恢复及测试。
本节初版不等于已获全历史读取、Lake 写入、DG 事件或 Prod 写入授权。
原章节保留资产口径和历史实施记录；涉及仅靠运行成功触发、历史补跑截止日和完成判断的改造，以第10节为本次提案依据。
2026年6月 P8 的删除文件/事件是已完成事故的历史记录，不适用于本次修复。

以下为原资产建设的历史实施说明：

状态：设计口径已确认，LLD 已补充，最新拍板口径已回写，P1 core formula/writer 已完成，P2 checks/catalog/readiness 已完成，P3 daily job/sensor 已完成，P4 repair core 已完成，P5 bootstrap dry-run / sample build 已完成，P6 historical bootstrap / runless event backfill 工具已完成并已正式执行至 `2026-06-25`，P7 documentation closeout 已完成。`2026-06-26` 上游 `silver_stock_daily` 与 `silver_adj_factor` 已补齐后，`gold_stock_daily_qfq_update_job` 可正常生成分区；随后暴露并修复了 ordinary asset check 缺少 partition attribution 的问题。2026-06-27 只读审计进一步确认：P6 历史 bootstrap 使用了错误的 self-as-of 口径，历史 `gold_stock_daily_qfq` 文件实际等同于 `silver_stock_daily`，不能作为 MA250 或报告事实源；P8 已完成：先删除旧错误 lake 文件和旧 Dagster events，再按 `bootstrap_as_of_trade_date=2026-06-26` 从零重建 `3033` 个历史分区并补录 `3033` 个 materialization events 与最近 `20` 个 retained contract check events；`gold_stock_daily_qfq_qfq_semantics_check` 已从 bootstrap / readiness / catalog / runless event 证明链路移除。本文只定义 `gold_stock_daily_qfq` 的资产边界、字段口径、物理布局、日常生成与 repair 的关系；报告逻辑不属于本资产设计，但 P8 后已用重建后的 qfq 文件重新生成 MA250 报告。

LLD：[`dagster-stock-daily-qfq-asset-low-level-design.md`](dagster-stock-daily-qfq-asset-low-level-design.md)

## 1. 背景

`silver_stock_daily` 当前是未复权日线标准事实。它保留 Tushare daily 的原始价格含义，`open/high/low/close/pre_close/change_amount/pct_chg/vol/amount` 不会乘复权因子，也不会按前复权口径重算。

因此，用 `silver_stock_daily.close` 直接计算 250 日均线会受拆股、送转、分红除权影响。长期均线、趋势、收益率和技术指标应消费前复权日线，而不是未复权日线。

新增 `gold_stock_daily_qfq` 的目标是：在 gold 层提供稳定、可复用的股票日线前复权行情事实源，供后续 MA250、日线指标、研究报告和其它日线 gold/serving 资产消费。

## 2. 当前代码依据

当前代码已提供可复用的基础事实和 qfq 公式参考：

- `silver_stock_daily`：股票日线标准层，路径为 `silver/quote/stock_daily/trade_date={partition_key}/part-000.parquet`。
- `silver_adj_factor`：复权因子标准层，路径为 `silver/quote/adj_factor/trade_date={partition_key}/part-000.parquet`。
- 股票分钟线 qfq 当前公式为：

```text
qfq_price = silver_price * adj_factor(row_trade_date) / adj_factor(as_of_trade_date)
```

日常 qfq 的 `as_of_trade_date` 等于目标分区交易日；repair qfq 的 `as_of_trade_date` 等于本次 repair 明确选择的复权因子交易日。

历史 bootstrap 是第三种独立场景：第一次全量初始化时，不得逐日使用
`as_of_trade_date=partition_key` 生成 self-as-of 文件，也不得通过“先 daily
update，再回放每个复权因子变化日 repair”来初始化。正确口径是：选择一个明确
的 bootstrap as-of 交易日，通常是本次覆盖范围内最新完整交易日，然后所有历史
分区一次性按该 as-of 生成。后续日常增量再由 daily update + scoped repair 维护。

`gold_stock_daily_qfq` 应沿用这个公式，不得把前复权简化为“价格直接乘以 adj_factor”。

## 3. 拍板口径

本节记录原资产建设已确认的口径。2026-10-19拟调整的触发、受影响范围推导与回刷完成判断见第10节；其余资产字段口径继续适用。

1. `pre_close/change_amount/pct_chg` 保留；上市首日或湖中无 previous source row 时统一写 `0`，不写 `NULL`。
2. repair 初版不开放手写 `stock_codes`，包括 repair config、正式 CLI 参数和 sensor payload；affected codes 必须由 `silver_adj_factor` 相邻 expected trade date diff 自动计算。
3. repair 初版必须增加自动 run-status sensor，触发逻辑参考股票分钟线 MACD/KDJ repair：`gold_stock_daily_qfq_update_job` 成功后自动做 bounded plan 判断并提交 scoped repair job。

截至 2026-06-27，上述三项均已关闭为正式口径，不再作为待拍板项保留。

### 3.0 拍板口径的执行解释

这三条在开发时按下面方式理解：

1. `0` 是合法“无上一可用日线”的业务占位，只能用于上市首日或湖中第一条可计算记录。只要上一条 source row 存在但 previous factor 缺失，就必须 fail closed，不能用 `0` 掩盖数据缺口。
2. repair 初版不提供运营手写股票池入口，也不提供散装修复入口。受影响股票必须由 `silver_adj_factor` 当前交易日与上一 expected trade date 的因子差异自动推导，并用 hash / upstream batch 做审计和幂等校验。
3. 自动 repair sensor 是“上游 daily qfq 成功后的 run-status 判断”，不是定时全市场扫描。它只围绕触发 run 的 `trade_date` 做 bounded repair plan，满足自动上限、hash 校验和 completion/status 门禁后才提交 scoped repair job。

这三条不是普通说明，后续代码和测试必须锁死：

1. writer 和契约测试必须覆盖合法 `0` 场景，同时覆盖 previous source row 存在但 previous factor 缺失时失败；不得把 `NULL` 或静默兜底带回正式输出。这里不新增公式正确性 check。
2. run config、正式 CLI、sensor payload、文档示例和测试样本都不得出现可由运营手写的 `stock_codes` 输入；如果需要人工处理超大 repair，只能走新的 dry-run 审批方案，不把散装股票池入口塞进初版正式链路。
3. repair 自动触发只能由 `gold_stock_daily_qfq_update_job` 的成功 run 驱动；不得新增定时全量 repair sensor，不得在 daily job 内顺手执行 repair，也不得让 repair sensor 进入全历史扫描。

2026-06-27 历史 bootstrap 事故后的 P8 五条修复口径也已拍板：

1. bootstrap as-of 交易日固定按用户确认的目标口径执行；本次 P8 使用 `2026-06-26` 作为 bootstrap as-of。若后续要变更 as-of 日期，必须单独拍板，不在 P8 执行期动态推导。
2. 先删除旧的错误 `gold_stock_daily_qfq` lake 文件，再从零重新生成；不得在旧错误文件上做局部 patch 或逐日 replay repair。
3. 旧的 `gold_stock_daily_qfq` Dagster materialization / ordinary check event 也要清掉，再按新文件事实重新补录；执行方式要像第一次从未做过 bootstrap 一样，而不是叠加覆盖旧错误状态。
4. bootstrap as-of factor 对每只股票的含义是“不晚于 bootstrap as-of 的最后可用 `silver_adj_factor`”。已退市股票在 as-of 当天没有因子是正常事实，不能因此误判为缺口；只要它在退市前有最后可用因子，就应使用该因子生成历史前复权序列。
5. `gold_stock_daily_qfq_qfq_semantics_check` 从 P8 后的 active ordinary check 口径中移除。公式自检用同一套公式重算，公式写错时仍会报绿，不能证明数据正确；P8 不再做这类公式正确性 check，也不再用固定样本、聚合差异或其它替代方式包装成公式验收。P8 必须在同一个修复阶段内闭环完成：代码修正、旧 lake 文件删除、旧 Dagster event 删除、新文件重建、新 runless event 补录、结构性验收和报告重算前置验收都要完成。结构性验收只确认文件、字段、分区、主键、事件补录等执行事实，不做公式正确性检查。

P8 正式执行结果（2026-06-28）：

1. 旧错误 lake 文件已删除，旧 `gold_stock_daily_qfq` materialization / ordinary check event 已删除。
2. 历史文件已按 `bootstrap_as_of_trade_date=2026-06-26` 重建：目标分区 `3033` 个，正式 lake 当前 `part-000.parquet` 文件数 `3033`，目录大小约 `775M`。
3. runless event 已补录：materialization events `3033`，retained contract check partitions `20`，reported events `3053`。
4. post-plan dry-run 报告显示：planned materialization events `0`、planned check events `0`、failed check partitions `0`；existing materialized partitions `3033`，existing ready check partitions `20`。
5. MA250 报告已用重建后的 qfq 数据重新生成：`lake_console/docs/reports/stock_below_ma250_2026-06-26.csv`，数据行 `3652`，已过滤 ST 与名称以“退”开头或结尾的股票。

### 3.1 字段保留

`gold_stock_daily_qfq` 必须保留以下字段：

| 字段 | 口径 |
| --- | --- |
| `ts_code` | 股票代码 |
| `trade_date` | 交易日，`DATE` |
| `open` | 前复权开盘价 |
| `high` | 前复权最高价 |
| `low` | 前复权最低价 |
| `close` | 前复权收盘价 |
| `pre_close` | 前复权昨收价 |
| `change_amount` | 前复权涨跌额 |
| `pct_chg` | 前复权涨跌幅 |
| `vol` | 成交量，沿用 silver 原始口径 |
| `amount` | 成交额，沿用 silver 原始口径 |

`open/high/low/close/pre_close/change_amount/pct_chg` 必须属于同一套前复权口径，不能出现价格已前复权但涨跌额、涨跌幅仍是未复权源字段的混合语义。

### 3.2 前复权字段计算

对目标分区 `D`，日常生成的 as-of 日期为 `D`。

```text
open_qfq  = open  * adj_factor(trade_date) / adj_factor(as_of_trade_date)
high_qfq  = high  * adj_factor(trade_date) / adj_factor(as_of_trade_date)
low_qfq   = low   * adj_factor(trade_date) / adj_factor(as_of_trade_date)
close_qfq = close * adj_factor(trade_date) / adj_factor(as_of_trade_date)
```

`pre_close` 必须按前复权口径生成。正式口径为：

```text
previous_source_close = latest silver_stock_daily.close for same ts_code before D
pre_close_qfq = previous_source_close * adj_factor(previous_trade_date_for_stock) / adj_factor(as_of_trade_date)
```

其中 `previous_trade_date_for_stock` 是该股票上一条可用日线交易日，而不是简单自然日前一日。

若上市首日或湖中第一条可用日线没有 previous source row，三字段统一写 `0`，不得写 `NULL`：

```text
pre_close = 0
change_amount = 0
pct_chg = 0
```

这只是“无上一可交易日”的业务占位，不是错误兜底。若 previous source row 存在但 previous factor 缺失，仍必须 fail closed，不得静默写 0。

`change_amount` 和 `pct_chg` 推荐从前复权价格重算：

```text
change_amount = close_qfq - pre_close_qfq
pct_chg = change_amount / pre_close_qfq * 100
```

若 `pre_close_qfq` 为 0，writer 必须只允许“合法无上一可交易日”的场景；只要上一条 source row 存在但 previous factor 缺失，就必须 fail closed。这个口径通过 writer/契约测试锁死，不新增公式正确性 check。

### 3.3 物理布局

物理布局采用 `trade_date=...`：

```text
data_lake/gold/quote/stock_daily_qfq/trade_date={YYYY-MM-DD}/part-000.parquet
```

采用日期分区的原因：

1. 日线单分区数据量小，按日期写入和读取成本可控。
2. 与 `silver_stock_daily`、`silver_adj_factor`、日常 sensor、报告扫描天然对齐。
3. 后续 repair 虽会重写历史日期分区，但日线文件远小于分钟线 stock-year 文件，按日期批量重写更清晰。
4. 下游 MA250、报告和日线指标通常按日期窗口扫描，不需要再从 stock-year 文件中筛日期。

## 4. 生成与 Repair 的关系

### 4.1 可以放在同一个专项需求中

`gold_stock_daily_qfq` 的日常生成和复权因子变化后的历史 repair 应放在同一个专项方案和 LLD 中设计。原因是前复权日线的正确性不只取决于当天文件是否生成，还取决于历史价格是否随最新复权因子变化完成修复。

如果只实现日常生成而不设计 repair，资产会出现“当前日可用，但历史 MA/指标仍可能按旧复权因子计算”的半成品状态。

### 4.2 不建议混成同一个 job/op

虽然生成和 repair 应在同一个专项中设计，但正式落地不应把日常生成和历史 repair 混成一个 job/op。

推荐拆成两个入口：

| 入口 | 职责 |
| --- | --- |
| `gold_stock_daily_qfq_update_job` | 日常生成单个 `trade_date` 分区 |
| `gold_stock_daily_qfq_factor_repair_job` | 当复权因子变化时，按 affected codes 和有效日期范围重写历史 qfq 日线 |

### 4.3 分入口的好处

1. 日常路径保持轻量，只处理一个交易日。
2. repair 路径可以独立做 dry-run、affected codes、effective start、写入批次和完成状态 metadata。
3. 失败语义清楚：日常生成失败不会夹带历史修复半成品；repair 失败也不会污染当日日常生成。
4. run key、upstream batch id、completion check 可以分别表达，避免互相覆盖。
5. 更容易控制 Dagster event 增量，避免一次普通日更写出大量历史 check event。

### 4.4 分入口的代价

1. 开发范围比单 asset 生成更大。
2. 需要额外设计 repair metadata、completion check、readiness/status helper。
3. 测试必须覆盖日常生成、factor changed repair、repair 后 downstream readiness。
4. 需要更严格的性能门禁，避免 repair 逐股票逐日期循环。

结论：同一个专项设计，分入口落地，共用公式 helper，不把日常生成和 repair 混成一个大 job。

### 4.5 Repair 自动触发口径

以下为原 run-status 触发设计和当前实现依据；它无法补齐已错过的运行，第10节提出替换方式，尚未落代码。

已拍板：repair 初版必须有自动 run-status sensor，但不是定时扫全量，也不是混进 daily job。正式口径参考股票分钟线 MACD/KDJ repair：

1. `gold_stock_daily_qfq_update_job[trade_date]` 成功后，由 `run_status_sensor` 触发判断。
2. sensor 只针对本次成功 run 的 `trade_date` 计算 repair plan。
3. sensor 用 DuckDB 比较同日与上一 expected trade date 的 `silver_adj_factor`，得到 affected codes 和 hash。
4. 若没有因子变化，skip。
5. 若 affected codes 超过自动上限、hash 缺失、已有 completion、或 plan 不完整，skip。
6. 若需要 repair 且未完成，提交 `gold_stock_daily_qfq_factor_repair_job`。
7. run key 使用 upstream-triggered 口径，避免同一 upstream batch 重复提交。

已拍板：repair job config、正式 CLI 和 sensor payload 都不开放手写 `stock_codes`。repair op 内部重新计算 affected codes，并校验 sensor 传入的 hash / upstream batch，防止散装修复。

## 5. 补数与事件口径

`gold_stock_daily_qfq` 后续会有三类“补数/事件”场景，不能混成一种处理方式。

### 5.1 日常增量

日常增量只处理单个 `trade_date` 分区：

1. `gold_stock_daily_qfq_update_job[trade_date]` 读取同日 `silver_stock_daily`、同日 `silver_adj_factor`，以及计算 `pre_close_qfq` 所需的上一可用日线/factor。
2. asset 负责写 `gold/quote/stock_daily_qfq/trade_date={trade_date}/part-000.parquet`。
3. Dagster 正常记录该分区 materialization event。
4. Dagster 正常记录该分区 blocking asset check events。
5. 日常链路不使用 runless event，不绕过正式 asset/check。

P8 后 `gold_stock_daily_qfq` 的 ordinary readiness 只保留结构性 contract check，
并且必须显式声明 `partitions_def=cn_a_stock_trade_days`。这是正式 readiness
的硬口径：check 不仅要执行成功，还必须写成带 `partition_key` 的 Dagster
check event，才能被 `gold_stock_daily_qfq_factor_repair_job_sensor` 和日常
readiness 按分区读取。公式正确性不再通过 Dagster blocking check 自我复算证明，
P8 也不再设计另一套公式级聚合对账、固定样本公式验收或其它公式正确性 check。
重建验收只确认“旧错误文件/事件已清零后，按显式 bootstrap as-of 从零重新生成并补录事件”的执行事实。
这里的结构性 contract 只证明文件可读、字段/分区/主键等结构契约正确，不证明前复权公式正确。

为避免再次出现“check 成功但 Dagster 认为目标 partition 缺 check”的问题，正式代码
保留人工维护入口 `gold_stock_daily_qfq_check_refresh_job`。该 job 只能选择
`AssetSelection.checks_for_assets(gold_stock_daily_qfq)`，不得 materialize asset，也
不得接 sensor；它只用于必要时对单个分区做 checks-only 修复。

日常 sensor 只负责判断最早缺失或 not-ready 的 `trade_date`，并提交单日 run；不得在 sensor 中执行历史补数，也不得扫描全历史。

补充现行防护：当 `silver_stock_daily` 与 `silver_adj_factor` 的 Dagster readiness
都绿、但 QFQ 分区仍待生成时，sensor 会只读核对该交易日两份 Parquet 的代码覆盖。它只读
`ts_code/trade_date`，正常一条聚合 SQL，缺覆盖时最多再取 5 个代码样本；不会读取前序日期、
不会复算 QFQ 公式、不会代替 adj factor sensor 提交补数。日线代码缺当日 factor 时，QFQ
sensor fail closed 并等待既有 `silver_adj_factor_update_job_sensor` 按当前生命周期重建因子文件。

### 5.2 历史初始化 / 大范围补数

本节的 P6/P8 说明是原初始化与事故处理记录。本次既有历史数据修复按第10节执行，不沿用删除旧文件/事件后重建的做法。

如果需要一次性生成历史 `gold_stock_daily_qfq`，默认不采用“数千个 Dagster backfill run”作为第一选择。后续 LLD 必须先测算规模，再按下面路径选择执行方式：

| 路径 | 适用情况 | 事件口径 |
| --- | --- | --- |
| 正式 Dagster backfill | 小范围历史补数，run 数和 event 增量可接受 | 每个 partition 由正式 asset/check 产生 materialization/check events |
| Direct lake bootstrap + runless event backfill | 全历史或大范围初始化，Dagster backfill 会产生过多 run/event 或耗时不可接受 | 先直接批量生成 lake 文件；文件结构验收通过后，再按 dry-run / sample / batch / final audit 补 runless events |

若选择 direct lake bootstrap，必须遵守当前性能治理规范：

1. 先只读 dry-run：统计 expected 日期数、完整输入日期数、已存在目标文件数、计划写入数、缺失输入样本和 sample partition。
2. 再小样本写入：只在显式 `--apply` 与指定 sample 范围下写临时/审批范围 lake root，验证 schema、row count、分区日期和唯一键；不得把样本公式复算作为 P8 验收项。
3. 再分批全量写：DuckDB set-based SQL，`_tmp -> validate -> atomic replace`；正式全量写入必须进入 P6 并单独审批。
4. 文件全量审计通过后，才允许进入 runless event backfill。
5. runless event backfill 只给已经通过结构性 contract 验收、旧错误文件清零确认和显式 as-of 重建流程确认的文件补 event；不得用自我复算公式 check 给文件报绿，也不得新增固定样本、公式级聚合 check 或任何替代性的公式正确性 check。
6. runless event 也必须 dry-run、sample、batch、final audit；不得无界写正式 Dagster DB。

runless event 补录拆成两层：

1. materialization event 全历史补录，用于告诉 Dagster 历史分区文件已经生成。
2. ordinary check event 只补保留的结构性 contract check，范围为最近 20 个 `cn_a_stock_trade_days` 与 latest partition，用于支撑最近窗口 UI/status/readiness；20 日以前不要求 Dagster DB 长期保存每个历史分区的 check 绿灯，历史文件存在、结构和事件补录事实以 bootstrap 执行报告为准。

当前 P6 已落地工具口径：

1. `gold_stock_daily_qfq_history_cli build-history` 默认 dry-run；只有显式 `--apply` 才写文件；正式写入必须显式传入并记录 `as_of_trade_date`。
2. `gold_stock_daily_qfq_history_events_cli plan-events` 只读规划 runless event。
3. `gold_stock_daily_qfq_history_events_cli report-events` 默认 dry-run；只有显式 `--apply` 才写 Dagster runless events。
4. P8 后 ordinary check event 写入前只执行保留的结构性 contract 验收；`gold_stock_daily_qfq_qfq_semantics_check` 不再补录、不再作为 readiness 阻断项，也不再作为 bootstrap 正确性证明。
5. 这些 CLI 的正式执行不属于代码开发阶段，必须另走正式 lake / Dagster DB 写入审批。

这个口径的前提是：后续自动触发、sensor、readiness 不依赖 20 日以前的 check event；报告和研究消费直接读取全历史 Parquet 文件。

### 5.3 QFQ Factor Repair

repair 不是普通日常生成，也不是历史初始化。repair 的触发原因是复权因子发生变化，需要用新的 as-of factor 重写受影响股票的历史 qfq 日线。

repair 口径：

1. repair job 只处理 affected codes 和有效历史日期范围，不全市场无脑重写。
2. repair 范围必须先 dry-run：输出 affected codes、effective start/end、预计重写日期数、预计行数、预计文件数。
3. repair 写入必须使用 DuckDB set-based SQL；禁止 Python 逐股票逐日期循环。
4. repair 成功后，应写 bounded repair status / completion metadata，记录 `upstream_batch_id`、affected codes hash、start/end、row count、file count。
5. repair job config 不开放手写 `stock_codes`。
6. 默认不做“每个历史 partition 普通 materialization/check event 全量 reconciliation”，避免 Dagster event history 继续膨胀。
7. 如果某个下游必须依赖 repaired partition 的 Dagster 普通 check 状态，必须单独设计 effective readiness 或经审批的有限 runless event 补录，不得在 repair job 里顺手无限补事件。

这里参考股票分钟线 qfq 的经验：历史文件被 repair 改写后，repair metadata 是修复账本；普通 qfq daily check 不应被反复当作 repair 后历史数据的唯一事实。

## 6. 数据集接入模板对账

本设计已按 `dagster-dataset-onboarding-template.html` 的思路先定“数据产品和资产边界”，但它还不是完整 LLD。当前覆盖和待补如下。

| 模板项 | 当前设计状态 | LLD 必须补齐 |
| --- | --- | --- |
| 数据集长期结果 | 已明确：`gold_stock_daily_qfq` 是日线前复权行情事实源 | 需要补中文名、dataset id、业务说明和主要消费者 |
| 层级判断 | 已明确为 `gold` | 需要补 `build_asset_tags(...)` 的 layer/domain/group 口径 |
| 分区模型 | 已明确物理布局 `trade_date=...` | 需要确认 Dagster partitions_def，预计复用股票交易日分区 |
| 字段契约 | 已列字段和 qfq 语义 | 需要在 `asset_column_schemas.py` 细化类型、描述、nullable 规则 |
| 路径 | 已明确 gold 路径模板 | 需要补正式 path helper 名称和 catalog path template |
| 上游依赖 | 已明确依赖 `silver_stock_daily` 与 `silver_adj_factor` | 需要补 asset deps、check additional_deps、readiness gate |
| checks | P8 后 ordinary blocking check 只保留结构性 contract；`qfq semantics` 公式自检退出 active check、readiness、catalog、runless event 和 bootstrap 证明链路 | repair status check 必须保持 protected/status 口径，不进入 ordinary readiness |
| metadata | 已要求 materialization/check/repair metadata 分层 | 需要列具体 metadata keys，走现有 metadata helper，不裸写 top-level key |
| job/sensor | P3 已落地 daily job 与 daily sensor；P4 已落地 repair job 与 repair run-status sensor | daily 已确认：`gold_stock_daily_qfq_update_job`、`gold_stock_daily_qfq_update_job_sensor`、默认 `STOPPED`、run key `gold_stock_daily_qfq_update:{trade_date}`、cursor 写结构化 reason code；repair 已确认：`gold_stock_daily_qfq_factor_repair_job`、`gold_stock_daily_qfq_factor_repair_job_sensor`、默认 `STOPPED`、run key 使用 upstream-triggered builder，config 不暴露 `stock_codes` |
| 历史迁移 | 已提出 direct lake bootstrap + runless event backfill 作为大范围候选方案 | 需要 dry-run 指标、sample 方案、全量批次、event 补录上限 |
| 性能门禁 | 已写基本性能表 | 需要真实只读样本测算：文件数、行数、DuckDB SQL 次数、耗时、event 数 |
| 人类可读治理 | 尚未完整展开 | 需要补 asset/job/sensor/check description，以及失败时先看哪里 |
| 验收计划 | 只列方向 | 需要单元测试、静态门禁、只读 profiling、小样本、最终对账清单 |

因此，回答“是否已经按模板完整设计”：当前这份文档是专项设计卡片，已经对齐模板的入口方向，但还没有达到完整 LLD 的细粒度。进入编码前必须补一份 LLD，把模板中要求的 catalog、schema、checks、metadata、job/sensor、历史补数、事件补录、性能测算和验收计划全部落到代码级别。

## 7. 非目标

本专项不包含：

1. MA250 报告改造。
2. 已生成 CSV 报告回填。
3. 非日线分钟线 qfq 逻辑重构。
4. 新增前端页面。
5. 清理或删除已有 `silver_stock_daily` 数据。
6. 用未复权 `silver_stock_daily` 字段冒充前复权字段。

报告相关工作应等 `gold_stock_daily_qfq` 资产、checks、日常生成和 repair 口径稳定后，再单独切换数据源。

## 8. 性能门禁

后续 LLD 和开发必须给出性能测算，不允许直接编码。

| 项 | 设计口径 |
| --- | --- |
| 日常生成 | 单个 `trade_date`，读取当日 `silver_stock_daily`、当日 `silver_adj_factor`，以及计算 `pre_close_qfq` 所需的 previous factor/source rows |
| 日常行数 | A 股日线数量级，约数千行 |
| 日常写入 | 一个 Parquet 文件，`_tmp -> validate -> atomic replace` |
| repair 范围 | 只处理复权因子变化影响的股票和有效历史日期，不全市场无脑重写 |
| repair 查询 | DuckDB set-based SQL，禁止 Python 逐股票逐日期行循环 |
| repair 写入 | 按日期或日期批次写入，必须 dry-run 后再执行 |
| Dagster event | 日常写单分区 materialization/check；历史 repair completion/status 需有界，不得制造不必要的全历史 check 膨胀 |
| 不可接受 | 文件存在/row count 冒充 ready；不测算 repair 范围直接全量重写；把报告需求混进资产开发；用 `NULL` 表示合法无 previous row；开放手写 `stock_codes`；用定时全量 sensor 做 repair |

## 9. LLD 已固定的开发边界

对应 LLD 已将以下事项细化到代码级开发阶段，后续开发按 LLD 分阶段推进：

1. `gold_stock_daily_qfq` 的正式 asset、job、sensor、check 名称。
2. `gold_stock_daily_qfq` 的 column schema、catalog entry、definition metadata。
3. 日常 update sensor 的 readiness：`silver_stock_daily`、`silver_adj_factor`、`silver_stock_lifecycle` 等上游门禁。
4. factor repair 的 affected codes 计算：从相邻 expected trade date 的 `silver_adj_factor` diff 中识别需要修复的股票。
5. repair 的 effective start：从 affected codes 在湖中已有 qfq/silver 日线覆盖范围取有效起点，不能盲目全历史。
6. repair completion metadata 与 downstream readiness 的关系。
7. 历史 `gold_stock_daily_qfq` 文件 bootstrap 与 runless event backfill 口径：先删除旧错误文件和旧事件，再按正确 as-of 重建；materialization 全历史补录，ordinary check event 只补保留的结构性 contract check 的最近 20 个交易日与 latest partition。
8. P95 耗时、DuckDB 扫描文件数、写入文件数、Dagster event 数量上限。
9. 三条拍板口径的门禁：`pre_close/change_amount/pct_chg` 合法缺 previous row 写 0、不开放手写 `stock_codes`、repair 自动 sensor 只走 run-status scoped repair。

<a id="qfq-history-repair-20261019"></a>
## 10. 历史遗漏回刷修复初版方案（2026-10-19）

### 10.1 要解决什么

已有审计确认：部分日更运行成功，但没有被历史回刷的监听器接到；除权前的价格因此一直没有更新。
当前检查只确认文件结构和单次任务结果，不能回答“历史是否全部按当前因子处理完”。
证据已保存为[审计报告](../../reports/stock_daily_qfq_audit_20261019/report.md)，后续直接引用，不再重复排查这五只股票。

本次遵守管理员确认的三条原则：

1. 原有数据尽量一次审计。保存覆盖范围、输入依据、异常清单及结论；以后复用，只补查实际变化和未覆盖部分。
2. 遗漏必须能被发现或明确报错。某次监听漏接、任务失败、进程退出，都不能使事项悄悄消失。
3. 错误历史应修尽修。不能只修5只样本或初筛234只，也不能通过排除退市股票、缺输入或难处理对象来宣告完成。

### 10.2 范围与已有成果

目标是正式 Lake 现有覆盖及其按现行合同应有的全部股票日线前复权历史，含沪深北市场、已退市股票和停牌前后的有效行情。
日期从已批准历史覆盖的实际起点到固定修复截止日，不能默认只检查今年或最近半年。
最终股票和日期清单由完整覆盖检查得出，不允许运营手写股票池代替。

直接复用[25股历史因子专项完成记录](dagster-stock-adj-factor-history-repair-plan-v1.md)。该专项已修复并登记，专用工具也已清退；
本次不重新下载、恢复工具或重跑原专项。其证据只证明原对象和范围，没有覆盖的历史仍需检查。
源因子真实错误与“因子正确、价格没回刷”要分清；发现源问题时记录具体对象、依据及待处理状态，不能用错误源数据计算后报完成。

本次能力改造涉及日线前复权、直接消费它的 DG 趋势通道/状态和日九转的接续判断。
分钟线、周月线、Raw/Silver因子整体修订、Prod/serving发布均不自动扩入。
如果日线修复影响这些范围，列出精确事项和处理阶段；DG价格完成与下游完成分开报告，未解决项不得藏在总成功状态里。

### 10.3 一次审计，怎样反复使用

先建立一次完整历史覆盖检查。开始前只利用既有报告、文件目录/大小、计数估算工作量，列明数据集、列、日期、预计扫描量和耗时，再按根规则取得全局读取批准。
已有今年188个日线文件约63MB的批准和测量，不能扩大为全历史已经获批，也不能拿它估算全部历史成本。

完整检查按有界日期批次读取，用 DuckDB 一起核对源行情、因子与 Gold，不按股票重复扫描历史。
每批完成就保存以下结果；中断后接着检查未完成批次：

- 已覆盖的股票、日期、文件和未覆盖范围；纳入范围的依据。
- 实际用过的源文件和目标文件的内容标识、计算/比较口径及代码版本。
- 无需修复的范围、错误行和受影响股票、具体原因、缺输入及无法判断项。
- 修复所需的日期、预计读写文件数、量额和其他股票应保留的范围。

结论不因隔天、进程重启或进入下一阶段而过期。输入和口径没有实际变化时，直接使用；
文件确实被改写、范围增加或比较口径改变时，只重新检查相应部分。
已有证据不能证明的字段必须写明，不能补写成“当时已验证”。

修复读取源文件、校验新候选和恢复时识别目标文件，是必要工作；
不得借这些步骤重做全部原因审计、反复查询源站或再跑一遍全历史计算。
最终验收汇总逐批覆盖和逐文件证明，只复核变化/缺失项，不重新计算整段历史。
报告保存在仓库 reports；正式执行的计划、候选证明和进度按 LLD 保存于获批 staging。
这些是审阅和恢复证据，不新增正式数据集、数据库表或供日常读取的报告资产。

### 10.4 让遗漏始终能被找出来

本初稿选择改造现有 `gold_stock_daily_qfq_factor_repair_job_sensor`：从只监听成功运行，改为定期、有界地核对待处理日期。
保留原名称和回刷 job，不并行新增第二套回刷触发逻辑。
检查依据是交易日历、已验收的历史范围、当前源文件与匹配的完成记录，不依赖运行来源是否完整。
正常日更在下一次核对时接续，手工补跑或漏接的运行也进入相同判断。

每次最多核对10个尚未完成交易日，最多提交1个任务；这只是单次工作量限制，不能把更早遗漏排除。
从最早未完成日期继续，已提交不等于已完成，失败或排队不能推进完成位置。
没有因子变化也明确记录“已核对，无需回刷”。超过自动500股、缺输入、缺日期或超出预算时，保留待处理位置并显示原因。
长停机或大量积压转受控历史任务，不能靠每天只看最近10天把旧遗漏忘掉。

已处理历史的源文件后来更正，也必须重新进入判断。优先利用既有上游发布记录，
再分批核对文件是否发生实际替换，避免上游文件已写成但事件没写成时漏掉。
没有变化时不重读历史行情内容；发现身份变化才核实该文件并推导影响范围。
来源记录丢失、完成证据无法恢复或文件被非正式入口改写时，明确阻断，不能默认历史正确。
对尚未同步到本地的源站更正不作已经发现的承诺；由源数据同步职责处理。

### 10.5 统一按哪个日期回刷

先固定源行情、因子均完整的修复截止日。每只股票使用不晚于该日的最后可用因子，退市股票无需在截止日仍有因子。
同一股票遗漏多次，合并后按这一个截止日处理，不逐个重放旧除权日任务。
对混用旧新因子的股票，重算其全部有效历史；对源历史值更正，按其真实影响范围处理，包含下一实际行情的昨收，以及有状态下游的后续范围。
所有价格从未复权行情和因子计算，量额不复权。

历史补跑也必须使用已经确认的截止日，不能重新默认按历史当天生成。
目标已使用更晚截止日时，旧任务拒绝覆盖；同一天输入更正则重新规划，不能仅因截止日相同而跳过。
无上一条有效行情才允许昨收等为0；不能把停牌超过查询窗口或因子缺失当成无前序行情。

### 10.6 写入、中断和下游

1. 写前固定计划、输入依据和目标旧文件标识，明确唯一写入者；共享同一天文件的任务不得并发覆盖。
2. 在 `/Volumes/datasource/data_lake_staging` 生成候选，按现有结构合同、修改范围和保留行完成一次校验。
3. 候选通过后保存证明，检查同文件系统，再逐文件 `os.replace()` 提升至正式 Gold，及时保存进度。
4. 重启后先识别已完成文件；输出与证明相符就复用，未完成才计算。遇到既不是原文件也不是本次输出的文件就停止，不能覆盖第三方修改。
5. 所有范围完成前不写整体成功。进度/事件写失败保留已提交文件，显示未完成，恢复时补记，不重新计算已完成部分。

多文件不能整体原子切换。正式修复必须安排维护窗口、协调日更和历史写入，并阻断受影响下游消费混合结果。
趋势通道/状态和日九转等需要按修正后的价格接续，原绿灯不能证明新价格已经算过。
已导出的报告只标明受影响及需要重算，不在本轮自动修改。

### 10.7 验收怎样才算没有遗漏

验收区分三件事：代码能正确计算、当前修复确实完成、下游使用了新结果。
公式和边界由独立字面预期及真实样本回归证明；不恢复已退出的普通公式自检 check。
完整历史检查是本次离线范围发现，不接入日常 readiness，不以同一个生产 helper 的输出反向生成预期。

历史范围必须能够对上以下数量：

> 应检查范围 = 已验证无需修改 + 已发现需修改 + 尚未完成检查；
> 已发现需修改 = 已修复并验证 + 尚未解决。

股票/日期/字段交叉范围不得重叠计数；范围外对象不混入分母。仅写“共修复多少行”不足以证明完整。
历史修复完成要求尚未完成检查和尚未解决均为0、候选/正式文件对账一致；
下游完成另要求相关DG结果及状态已接续。遇缺源、缺文件、损坏或证据不足，保留问题并报告，不能删除或过滤后通过。
若发现原本应有但不存在的分区，先记录并安排相应补数；不能让只改现有文件的回刷任务静默跳过。

### 10.8 落地顺序与本版状态

| 步骤 | 交付与通过条件 | 当前状态 |
| --- | --- | --- |
| 1. 方案与LLD | 本节、LLD第19节方向及第20节代码说明；覆盖函数、参数、SQL、逐文件恢复及测试 | 已按代码复核补充，待评审；未开发 |
| 2. 能力开发与隔离验收 | 改造现有触发/回刷/下游完成判断；复现本次来源遗漏和中断恢复 | 未开始 |
| 3. 一次完整历史检查 | 先获准精确全局读取范围；已有证据复用，形成可恢复检查和修复清单 | 未开始 |
| 4. 正式历史修复 | 从清单生成候选、必要样本、分批提升及下游接续；按范围获准后执行 | 未开始 |
| 5. 完成对账 | 汇总已有逐批证明、未解决为0，核对日常接续；不重放全历史计算 | 未开始 |

本轮代码复核已把并发、正式写入口、config、读取API和下游接续细化到LLD第20节，不再留给开发时临场选择。
正式DG已有全局并发1，方案复用它并拒绝绕过队列的正式直写；不新增锁或并发配置。
巡检无属性变化时只推进轻量cursor，不为它反复创建任务；有变化才进入核实，业务完成位置仍认持久执行证明。
执行记录的字段、目录和提交顺序已明确，价格事实仍来自绑定版本的Silver，不能用进度文件冒充价格源。
实际全历史文件数、字节和耗时须在取得对应读取授权后填入执行单；已有审计证据直接复用，不为填表重做原因排查。
