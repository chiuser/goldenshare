# Dagster Gold Stock Daily QFQ Asset Design

状态：设计口径已确认，LLD 已补充，最新拍板口径已回写，P1 core formula/writer 已完成，P2 checks/catalog/readiness 已完成，P3 daily job/sensor 已完成，待推进 P4 repair core。本文只定义 `gold_stock_daily_qfq` 的资产边界、字段口径、物理布局、日常生成与 repair 的关系；不包含报告改造。

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

`gold_stock_daily_qfq` 应沿用这个公式，不得把前复权简化为“价格直接乘以 adj_factor”。

## 3. 拍板口径

本节为已拍板口径，后续 LLD 与开发不得再回到待确认状态：

1. `pre_close/change_amount/pct_chg` 保留；上市首日或湖中无 previous source row 时统一写 `0`，不写 `NULL`。
2. repair 初版不开放手写 `stock_codes`，affected codes 必须由 `silver_adj_factor` 相邻 expected trade date diff 自动计算。
3. repair 初版必须增加自动 run-status sensor，触发逻辑参考股票分钟线 MACD/KDJ repair：daily qfq 成功后自动做 bounded plan 判断并提交 scoped repair job。

### 3.0 拍板口径的执行解释

这三条在开发时按下面方式理解：

1. `0` 是合法“无上一可用日线”的业务占位，只能用于上市首日或湖中第一条可计算记录。只要上一条 source row 存在但 previous factor 缺失，就必须 fail closed，不能用 `0` 掩盖数据缺口。
2. repair 初版不提供运营手写股票池入口。受影响股票必须由 `silver_adj_factor` 当前交易日与上一 expected trade date 的因子差异自动推导，并用 hash / upstream batch 做审计和幂等校验。
3. 自动 repair sensor 是“上游 daily qfq 成功后的 run-status 判断”，不是定时全市场扫描。它只围绕触发 run 的 `trade_date` 做 bounded repair plan，满足自动上限和 completion/status 门禁后才提交 scoped repair job。

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

若 `pre_close_qfq` 为 0，必须在 check 中显式区分“合法无上一可交易日”和“应有上一可交易日却写 0”的数据问题。

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

已拍板：repair 初版必须有自动 run-status sensor，但不是定时扫全量，也不是混进 daily job。正式口径参考股票分钟线 MACD/KDJ repair：

1. `gold_stock_daily_qfq_update_job[trade_date]` 成功后，由 `run_status_sensor` 触发判断。
2. sensor 只针对本次成功 run 的 `trade_date` 计算 repair plan。
3. sensor 用 DuckDB 比较同日与上一 expected trade date 的 `silver_adj_factor`，得到 affected codes 和 hash。
4. 若没有因子变化，skip。
5. 若 affected codes 超过自动上限、hash 缺失、已有 completion、或 plan 不完整，skip。
6. 若需要 repair 且未完成，提交 `gold_stock_daily_qfq_factor_repair_job`。
7. run key 使用 upstream-triggered 口径，避免同一 upstream batch 重复提交。

已拍板：repair job config 不开放手写 `stock_codes`。repair op 内部重新计算 affected codes，并校验 sensor 传入的 hash / upstream batch，防止散装修复。

## 5. 补数与事件口径

`gold_stock_daily_qfq` 后续会有三类“补数/事件”场景，不能混成一种处理方式。

### 5.1 日常增量

日常增量只处理单个 `trade_date` 分区：

1. `gold_stock_daily_qfq_update_job[trade_date]` 读取同日 `silver_stock_daily`、同日 `silver_adj_factor`，以及计算 `pre_close_qfq` 所需的上一可用日线/factor。
2. asset 负责写 `gold/quote/stock_daily_qfq/trade_date={trade_date}/part-000.parquet`。
3. Dagster 正常记录该分区 materialization event。
4. Dagster 正常记录该分区 blocking asset check events。
5. 日常链路不使用 runless event，不绕过正式 asset/check。

日常 sensor 只负责判断最早缺失或 not-ready 的 `trade_date`，并提交单日 run；不得在 sensor 中执行历史补数，也不得扫描全历史。

### 5.2 历史初始化 / 大范围补数

如果需要一次性生成历史 `gold_stock_daily_qfq`，默认不采用“数千个 Dagster backfill run”作为第一选择。后续 LLD 必须先测算规模，再按下面路径选择执行方式：

| 路径 | 适用情况 | 事件口径 |
| --- | --- | --- |
| 正式 Dagster backfill | 小范围历史补数，run 数和 event 增量可接受 | 每个 partition 由正式 asset/check 产生 materialization/check events |
| Direct lake bootstrap + runless event backfill | 全历史或大范围初始化，Dagster backfill 会产生过多 run/event 或耗时不可接受 | 先直接批量生成 lake 文件；文件审计通过后，再按 dry-run / sample / batch / final audit 补 runless events |

若选择 direct lake bootstrap，必须遵守当前性能治理规范：

1. 先只读 dry-run：统计目标日期数、预期行数、预期文件数、已存在文件、覆盖风险。
2. 再小样本写入：验证 schema、row count、分区日期、唯一键、qfq 公式、`pre_close/change_amount/pct_chg`。
3. 再分批全量写：DuckDB set-based SQL，`_tmp -> validate -> atomic replace`。
4. 文件全量审计通过后，才允许进入 runless event backfill。
5. runless event backfill 只给已经通过正式 blocking check 语义的文件补 event；不得给未通过检查的文件报绿。
6. runless event 也必须 dry-run、sample、batch、final audit；不得无界写正式 Dagster DB。

runless event 补录拆成两层：

1. materialization event 全历史补录，用于告诉 Dagster 历史分区文件已经生成。
2. ordinary check event 只补最近 20 个 `cn_a_stock_trade_days` 与 latest partition，用于支撑最近窗口 UI/status/readiness；20 日以前的历史质量证明以 bootstrap 文件审计报告为准，不要求 Dagster DB 长期保存每个历史分区的 check 绿灯。

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
| checks | 已落地 2 条 ordinary blocking checks：contract 与 qfq semantics，子规则写入 metadata | 后续 repair status check 必须保持 protected/status 口径，不进入 ordinary readiness |
| metadata | 已要求 materialization/check/repair metadata 分层 | 需要列具体 metadata keys，走现有 metadata helper，不裸写 top-level key |
| job/sensor | P3 已落地 daily job 与 daily sensor；repair job / run-status sensor 留到 P4 | daily 已确认：`gold_stock_daily_qfq_update_job`、`gold_stock_daily_qfq_update_job_sensor`、默认 `STOPPED`、run key `gold_stock_daily_qfq_update:{trade_date}`、cursor 写结构化 reason code；P4 需补 repair job / run-status sensor |
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
| 不可接受 | 文件存在/row count 冒充 ready；不测算 repair 范围直接全量重写；把报告需求混进资产开发 |

## 9. LLD 已固定的开发边界

对应 LLD 已将以下事项细化到代码级开发阶段，后续开发按 LLD 分阶段推进：

1. `gold_stock_daily_qfq` 的正式 asset、job、sensor、check 名称。
2. `gold_stock_daily_qfq` 的 column schema、catalog entry、definition metadata。
3. 日常 update sensor 的 readiness：`silver_stock_daily`、`silver_adj_factor`、`silver_stock_lifecycle` 等上游门禁。
4. factor repair 的 affected codes 计算：从相邻 expected trade date 的 `silver_adj_factor` diff 中识别需要修复的股票。
5. repair 的 effective start：从 affected codes 在湖中已有 qfq/silver 日线覆盖范围取有效起点，不能盲目全历史。
6. repair completion metadata 与 downstream readiness 的关系。
7. 历史 `gold_stock_daily_qfq` 文件 bootstrap 与 runless event backfill 口径：materialization 全历史，ordinary check event 只补最近 20 个交易日与 latest partition。
8. P95 耗时、DuckDB 扫描文件数、写入文件数、Dagster event 数量上限。
