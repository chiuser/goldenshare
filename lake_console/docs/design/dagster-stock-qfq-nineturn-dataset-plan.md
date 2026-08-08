# 股票前复权九转资产族接入方案

状态：设计口径已冻结，尚未进入代码开发、历史写入或正式 Dagster 操作

代码级设计见：
[`dagster-stock-qfq-nineturn-dataset-low-level-design.md`](./dagster-stock-qfq-nineturn-dataset-low-level-design.md)

## 1. 目标

新增一组基于现有前复权行情计算的 Gold 九转资产，供每天全市场扫描、信号筛选和后续多频度研究使用：

1. `gold_stock_daily_qfq_nineturn`
2. `gold_stk_mins_qfq_nineturn_30m`
3. `gold_stk_mins_qfq_nineturn_60m`
4. `gold_stk_mins_qfq_nineturn_90m`
5. `gold_stk_mins_qfq_nineturn_120m`

本专项只生产可复用的九转事实，不定义“机会”“买点”“卖点”或多频度共振规则。机会筛选属于这些资产的下游业务，必须在信号条件单独拍板后再设计。

## 2. 已确认口径

### 2.1 计算规则

对每个股票、每个频度，按实际 bar 顺序比较当前前复权收盘价与前第 4 根 bar 的前复权收盘价：

```text
close[t] > close[t-4]  -> up_count 递增，down_count 归零
close[t] < close[t-4]  -> down_count 递增，up_count 归零
close[t] = close[t-4]  -> 两个计数都归零
不足 4 根历史 bar      -> 两个计数都为 0
```

信号字段口径：

```text
up_count >= 9   -> nine_up_turn = "+9"
down_count >= 9 -> nine_down_turn = "-9"
其它情况        -> 对应信号为空
```

计数不会在 9 截断。`10`、`11` 表示同一方向条件继续成立，并不代表新一轮九转。

设计前已用当前 DG 的 Tushare 日线九转事实做独立转移审计：4,610,961 个可比较的相邻状态转移中，按上述规则重建的下一状态差异为 0。这个结果只用于确认公式口径，不会让新资产依赖 Tushare 九转。

### 2.2 不重绘语义

本方案采用固定公式、只使用当前及以前 bar 的因果计算。未来行情不会把已经形成的历史计数重新排成另一套序列。

以下两类情况不叫“未来行情导致重绘”：

1. 上游历史前复权行情被正式修正，旧输出需要受控重建。
2. 公式版本经业务批准发生变化，需要按新版本重建。

### 2.3 数据来源

| 新资产 | 唯一业务来源 |
| --- | --- |
| `gold_stock_daily_qfq_nineturn` | `gold_stock_daily_qfq` |
| `gold_stk_mins_qfq_nineturn_30m` | `gold_stk_mins_qfq_30m` |
| `gold_stk_mins_qfq_nineturn_60m` | `gold_stk_mins_qfq_60m` |
| `gold_stk_mins_qfq_nineturn_90m` | `gold_stk_mins_qfq_90m` |
| `gold_stk_mins_qfq_nineturn_120m` | `gold_stk_mins_qfq_120m` |

现有 `raw_tushare_stk_nineturn` 和 `silver_stock_nineturn_daily` 保持不变，只能作为源站事实和离线对照样本，不是新资产的生产输入。

### 2.4 不新增独立 state 资产

九转方向由有限滞后公式决定，连续计数可以由相同方向的连续段直接推导，不需要像 MACD EMA、DEA 或 KDJ 平滑值那样保存递推数值状态。

日常增量允许读取上一交易日九转输出的末行作为计算加速种子，但它仍是主资产自己的上一分区，不是新的 state 数据集。新股、停牌后恢复或种子缺失时，计算器从现有 QFQ 历史精确回算；不能用 0 静默初始化老股票。

### 2.5 不新增运行配置

本资产族不新增环境变量、`Settings`、数据库配置、配置文件、Dagster resource 或可由运营临时修改的公式开关。

比较滞后 4 根、信号阈值 9、正式频度 daily/30/60/90/120 和公式版本都属于数据契约，不属于运行参数。它们集中定义在稳定 contract 中，由资产、测试、metadata 和历史工具共同引用。禁止在 sensor、asset、bootstrap 脚本或文档中各自维护另一份数值。

如果以后要改变滞后、阈值、频度集合或公式语义，必须先形成新的设计决策，升级公式版本，并评估历史数据重建；不能通过修改环境变量或一次 run config 静默改变同一资产的含义。

## 3. 资产与文件布局

五个资产都按交易日分区。日线复用 `cn_a_stock_trade_days`，四个分钟频度复用 `cn_a_stock_mins_silver_trade_days`，不新增 dynamic partition set。

```text
gold/indicator/stock_daily_qfq_nineturn/
  trade_date=<YYYY-MM-DD>/part-000.parquet

gold/indicator/stk_mins_qfq_nineturn/
  freq=<30|60|90|120>/trade_date=<YYYY-MM-DD>/part-000.parquet
```

选择全市场按日文件，而不是复制上游“股票 + 年份”布局，原因是本资产的主要消费方式是每天做一次全市场扫描。正常查询只需读取 5 个文件，不需要打开数万份股票年份文件。

### 3.1 日线字段

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `ts_code` | `VARCHAR` | 标准股票代码 |
| `trade_date` | `DATE` | 交易日 |
| `close_qfq` | `DOUBLE` | 本次九转计算使用的前复权收盘价 |
| `up_count` | `INTEGER` | 连续上九转计数 |
| `down_count` | `INTEGER` | 连续下九转计数 |
| `nine_up_turn` | `VARCHAR` | `+9` 或空 |
| `nine_down_turn` | `VARCHAR` | `-9` 或空 |

### 3.2 分钟字段

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `ts_code` | `VARCHAR` | 标准股票代码 |
| `freq` | `INTEGER` | 30、60、90 或 120 |
| `trade_date` | `DATE` | 交易日 |
| `trade_time` | `TIMESTAMP` | bar 时间 |
| `close_qfq` | `DOUBLE` | 本次九转计算使用的前复权收盘价 |
| `up_count` | `INTEGER` | 连续上九转计数 |
| `down_count` | `INTEGER` | 连续下九转计数 |
| `nine_up_turn` | `VARCHAR` | `+9` 或空 |
| `nine_down_turn` | `VARCHAR` | `-9` 或空 |

不复制完整 OHLC、成交量和成交额。九转公式只使用 `close`，保留 `close_qfq` 足以解释信号价格；需要完整 K 线时按相同业务键连接现有 QFQ 资产，避免再复制一套行情事实。

## 4. 日常生产链路

日线和分钟线使用两个 job，因为它们属于不同的正式动态分区集合，不能为了一个入口伪造统一分区口径。

```text
gold_stock_daily_qfq ready
  + 同日 qfq factor repair plan 已判定“无需修复”或 repair 已完成
    -> gold_stock_daily_qfq_nineturn_update_job

30/60/90/120m gold_stk_mins_qfq ready
  + 同日分钟 qfq factor repair job 已完成检测和必要回刷
    -> gold_stk_mins_qfq_nineturn_update_job
```

正式入口：

| 类型 | 名称 |
| --- | --- |
| 日线 job | `gold_stock_daily_qfq_nineturn_update_job` |
| 日线 sensor | `gold_stock_daily_qfq_nineturn_update_job_sensor` |
| 分钟 job | `gold_stk_mins_qfq_nineturn_update_job` |
| 分钟 sensor | `gold_stk_mins_qfq_nineturn_update_job_sensor` |

两个 sensor 均遵循：

1. 默认 `STOPPED`，发布验收后单独批准启用。
2. 每个 tick 最多提交一个交易日。
3. 先判断注册分区和运行窗口，再批量读取最近窗口 readiness。
4. 上游 materialization、blocking checks、factor repair 状态缺一不可。
5. 目标已 materialized 但 check 失败时 fail closed，不自动覆盖。
6. cursor 使用标准 v1 模板，只说明本次是否触发、目标日期、阻断组件、摘要和下一步动作。

### 4.1 人的排障顺序

这组资产在 Dagster 中出现问题时，固定按下面的顺序看，不要求运营人员先读代码或拼接多份机器报告：

| 看到的现象 | 第一入口 | 一眼要回答的问题 | 继续排查的位置 |
| --- | --- | --- | --- |
| sensor 没触发 | sensor cursor | 目标日期是什么、卡在哪个组件、下一步该等还是该修 | 对应上游 asset/check readiness |
| run 失败 | Run stdout/stderr | 失败发生在读源、fallback、校验还是正式文件替换前 | 本次 materialization metadata 或异常栈 |
| check 失败 | 聚合 check metadata | 哪条规则失败、失败多少、少量样本是什么 | `diagnostic_ref` 指向的只读审计结果 |
| 历史 bootstrap 失败 | `/private/tmp` 中的 plan/progress/final audit | 哪个批次停止、fingerprint 是否变化、是否写过正式文件/event | 本方案的历史与回滚章节 |

cursor 只做本 tick 的调度路标；stdout 记录运行阶段；materialization metadata 说明本次写出了什么；check metadata 说明产物哪里不合格；历史审计报告承载大规模明细。禁止让四个入口重复保存完整 readiness、路径清单或全量样本。

## 5. Check 与公式测试分工

每个资产只注册一个聚合 blocking check，总共 5 个，不拆成大量细碎 Dagster 状态。

| 资产 | Check |
| --- | --- |
| 日线 | `gold_stock_daily_qfq_nineturn_integrity_check` |
| 30m | `gold_stk_mins_qfq_nineturn_30m_integrity_check` |
| 60m | `gold_stk_mins_qfq_nineturn_60m_integrity_check` |
| 90m | `gold_stk_mins_qfq_nineturn_90m_integrity_check` |
| 120m | `gold_stk_mins_qfq_nineturn_120m_integrity_check` |

聚合 check 只验证生产事实：

1. 文件存在、可读、schema 与分区日期正确。
2. 业务 key 唯一且非空，`close_qfq` 为正数。
3. 计数为非负整数，同一行不能同时出现正的上、下计数。
4. 信号与计数域一致，例如 `+9` 只能出现在 `up_count >= 9`。
5. 输出 key 集合与同日上游 QFQ key 集合完全一致。
6. 文件写入完整，没有 staging 残留或半文件。

production check 禁止重新执行九转公式。公式正确性由受保护金样本测试负责，至少覆盖：

- 大于、小于、等于和不足 4 根 bar。
- 连续段重置、计数到 9 后继续到 10/11。
- 跨交易日、跨年份、新股首批 bar、停牌后恢复。
- 30/60/90/120m 四个频度。
- 前复权价格统一正比例缩放后九转结果不变。
- 上游重复 key、空 key、错日期和种子缺失必须失败。

测试 expected 值必须是人工确认的字面量，禁止调用被测 helper 反向生成。

## 6. 历史与修复

### 6.1 历史 bootstrap

历史范围不硬编码截止日，也不按当前股票池补笛卡尔积。每个资产以对应 QFQ 源文件中的实际业务键和实际日期范围为准。

历史生成使用 DuckDB set-based SQL，按频度、年份分批计算，再按交易日写目标文件。禁止 Python 逐行计算或逐行写 Parquet。

正式写入前必须先做只读 profiling，冻结：

1. 每个频度的 source row count、日期范围和股票数。
2. 预计输出行数、文件数、字节数和年度最大批次。
3. 查询耗时、峰值临时空间和 staging 空间。
4. 源输出 key 差异、重复和空 key。

历史事件口径：

1. 每个实际生成分区补 1 条 runless materialization，保证 Dagster UI 能真实显示历史物理覆盖。
2. blocking check event 只补最近 20 个交易日，保持统一轻量口径。
3. 不创建历史 run，不启动 sensor，不为全历史补 check。

### 6.2 上游历史修正

正常 QFQ factor repair 只改变同一股票历史价格的共同正比例分母时，`>`、`<` 比较结果不变，不触发九转历史重算。

若发生以下任一情况，必须走单独批准的离线 rebuild，不允许日常 sensor 自动扩大范围：

1. 上游历史 bar key、日期或排序发生变化。
2. 历史复权因子被非等比例修正，导致相对大小可能变化。
3. QFQ 历史文件被人工修复或公式版本变化。

rebuild 只按明确代码和日期范围执行，使用 staging、manifest 和原子替换；完成后按实际改写分区补 materialization，不补全历史 checks。

## 7. 性能预算

2026-08-06 当前 Lake 只读样本：

| 频度 | 当日行数 | 股票数 |
| --- | ---: | ---: |
| daily | 5,533 | 5,533 |
| 30m | 49,797 | 5,533 |
| 60m | 27,665 | 5,533 |
| 90m | 16,599 | 5,533 |
| 120m | 11,066 | 5,533 |
| 合计 | 110,660 | 5,533 |

当前四个分钟 QFQ 最新日只读投影共打开相应股票年份文件并统计，实测约 2.3 秒。该结果只作为静态设计基线，不等于新计算性能验收。

正式性能门禁：

| 路径 | 最大读取 | 最大写入 | 预算 |
| --- | --- | --- | --- |
| 日线 sensor | 最近 10 个日期的批量状态 | 0 或 1 run | 稳态小于 3 秒 |
| 分钟 sensor | 最近 5 个日期的批量状态 | 0 或 1 run | 稳态小于 10 秒 |
| 日线 asset | 当日源、必要滞后上下文、上一输出种子 | 1 parquet | 小于 15 秒 |
| 四分钟 asset job | 4 个频度的当日源和必要上下文 | 4 parquet | 合计小于 30 秒 |
| Check | 5 个目标文件和源 key 投影 | 5 check events | 合计小于 10 秒 |

超过预算时 fail closed 并进入只读 profiling，不通过增加 state 资产、调大 gRPC timeout 或弱化 check 绕过。

日常每个交易日固定新增：

- 5 个 Parquet 文件。
- 5 条 materialization event。
- 5 条 blocking check event。
- 合计 10 条 Dagster event。

## 8. 不做事项

本专项不做：

1. 不修改现有 QFQ、Tushare 九转、MACD/KDJ 资产。
2. 不新增九转 state 资产、数据库表、readiness manifest 或 summary asset。
3. 不新增 1m、5m、15m 九转。
4. 不定义交易机会、多周期共振或自动交易结论。
5. 不把 Tushare 九转当作生产 source 或线上 blocking gate。
6. 不在 production check 中二次计算公式。
7. 不默认执行历史 bootstrap、Dagster run、sensor、runless event 或 Lake 写入。

## 9. 治理文档同步

正式 Definitions 落地时必须同步以下现行治理文档：

1. `dagster-asset-job-topology.html`：登记五个资产、两个 job、两个 sensor 及日线/分钟两套分区入口。
2. `dagster-run-contract-governance.html`：登记两个 sensor 的分类、run key、run request、标准 cursor 和默认 `STOPPED` 边界。

这两份治理文档只登记当前拓扑与运行入口，并链接回本方案和 LLD；不复制九转公式、SQL、历史 bootstrap 细节，避免同一业务口径维护多份。

## 10. 分阶段推进

| 阶段 | 内容 | 写入边界 |
| --- | --- | --- |
| P0 | 只读 profiling，冻结历史规模、增量读取模型和性能 | 零正式写入 |
| P1 | schema、path、contract、calculator 和金样本测试 | 只改代码/测试 |
| P2 | 五个 asset、五个聚合 check、catalog | 只改代码/测试 |
| P3 | 两个 job、两个 sensor、readiness、cursor 和治理文档同步 | sensor 默认 STOPPED |
| P4 | 历史 bootstrap/rebuild 工具与 dry-run | 默认只读 |
| P5 | `dg check defs` 和正式只读 preflight | 需单独批准 |
| P6 | 历史 Lake 写入、runless event、sensor 启用 | 每类写入单独批准 |

## 11. 开发前停止条件

出现以下任一情况，停止开发并修订本文：

1. 90m/120m 上游正式 bar 契约在开发前发生变化，且现有 QFQ asset/check 未完成收口。
2. 精确日常计算需要全历史扫描，无法满足已冻结性能预算。
3. 需要新增独立 state 才能保证正确性，说明当前无 state 方案不成立。
4. 历史预计空间、文件数或耗时超过 P0 批准上限。
5. 现有 factor repair metadata 无法区分日常等比例修复与非日常历史事实修正。
