# 股票前复权九转资产族接入方案

状态更新（2026-10-26）：第12节补充22日四个分钟九转分区的代码审计和修正方案，当前仅完成文档，未开发、未执行。现有恢复记录仍为105/109项通过、九转4项待补；两股票sensor的最近控制证据均为`STOPPED`，待23日数据补齐后再启用。具体开发与执行以第12节和原LLD第22节为准。

历史结果（2026-08-15）：P0至P7R、分钟去价格S0至S5当时均已完成；四个分钟资产全量切换为八列合同，并完成当时的Lake、event、Reader/readiness及sensor验收。当时分钟sensor为`RUNNING`；此处记录不代表10月26日状态。日线后来已有独立去价格修正，当前合同以代码为准，本轮不修改日线。

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
| `up_count` | `INTEGER` | 连续上九转计数 |
| `down_count` | `INTEGER` | 连续下九转计数 |
| `nine_up_turn` | `VARCHAR` | `+9` 或空 |
| `nine_down_turn` | `VARCHAR` | `-9` 或空 |

分钟九转最终资产只保存业务键、计数和信号，不保存 `close_qfq`、OHLC、成交量或成交额。九转公式仍从同频 `gold_stk_mins_qfq.close` 读取价格并在计算 SQL 内使用 `close_value`；跨年度bootstrap可在规定的staging中临时保留最近四根价格，但它不是正式资产，不能被业务Reader消费。日线当前也是无价格的六列合同，此处依据`asset_column_schemas.py`校准文字，不属于本轮代码修改。

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

日线与分钟继续各自只注册一个聚合 blocking check。共同检查只验证生产事实：

1. 文件存在、可读、schema 与分区日期正确。
2. 业务 key 唯一且非空，上游 QFQ source key 也必须唯一。
3. 计数为非负整数，同一行不能同时出现正的上、下计数。
4. 信号与计数域一致，例如 `+9` 只能出现在 `up_count >= 9`。
5. 输出 key 集合与同日上游 QFQ key 集合完全一致。
6. 正式文件可完整读取，没有半文件；staging的失败现场和恢复记录不是正式数据，也不因保留而判正式文件缺失。

按当前无价格合同，日线和分钟check都不比较目标价格、不在生产环境重新计算公式；旧`close_qfq`检查不再是现行要求。含该列的旧分钟文件属于schema不匹配，不能与新八列文件混存。本轮只复用现行分钟检查。

production check 禁止重新执行九转公式。公式正确性由受保护金样本测试负责，至少覆盖：

- 大于、小于、等于和不足 4 根 bar。
- 连续段重置、计数到 9 后继续到 10/11。
- 跨交易日、跨年份、新股首批 bar、停牌后恢复。
- 30/60/90/120m 四个频度。
- 前复权价格统一正比例缩放后九转结果不变。
- 上游重复key、空key、错日期及有前序日期但整份前序文件缺失必须失败；单代码缺种子按既定fallback处理，不能与整文件缺失混为一谈。

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

以下为2026-08历史专项的预算和测量，不能据此对10月22日任务新增超时/空间中断器；本轮读取模型及成本单列于第12节、LLD第22节。2026-08-08完成正式P0只读profiling，最新业务日期为`2026-08-07`：

| 频度 | 当日行数 | 股票数 |
| --- | ---: | ---: |
| daily | 5,535 | 5,535 |
| 30m | 49,815 | 5,535 |
| 60m | 27,675 | 5,535 |
| 90m | 16,605 | 5,535 |
| 120m | 11,070 | 5,535 |
| 合计 | 110,700 | 5,535 |

五个上游的历史范围均为 `2014-01-02` 至 `2026-08-07`，均有 3,063 个实际交易日、5,553 个历史股票代码且空 key 为 0：

| 频度 | Source 文件数 | Source 行数 | Source 大小 |
| --- | ---: | ---: | ---: |
| daily | 3,063 | 11,622,020 | 0.82 GB |
| 30m | 52,881 | 104,576,189 | 3.76 GB |
| 60m | 52,876 | 58,245,695 | 2.38 GB |
| 90m | 52,881 | 34,804,311 | 1.58 GB |
| 120m | 52,876 | 23,223,508 | 1.16 GB |
| 合计 | 214,577 | 232,471,723 | 9.70 GB |

目标历史预计生成 15,315 个按日文件、232,471,723 行，预计约 0.99 GB；按最新样本压缩比给出的合理区间为 0.79 至 1.18 GB。年度最大批次是 2025 年，五个资产合计约 26,255,887 行。历史状态预计为 15,315 条 materialization 加最近窗口 100 条 check，共 15,415 条 runless event。

正式性能门禁：

| 路径 | 最大读取 | 最大写入 | 预算 |
| --- | --- | --- | --- |
| 日线 sensor | 最近 10 个日期的批量状态 | 0 或 1 run | 稳态小于 3 秒 |
| 分钟 sensor | 最近 5 个日期的批量状态 | 0 或 1 run | 稳态小于 10 秒 |
| 日线 asset | 当日源、必要滞后上下文、上一输出种子 | 1 parquet | 小于 15 秒 |
| 四分钟 asset job | 4 个频度的当日源和必要上下文 | 4 parquet | 合计小于 30 秒 |
| Check | 5 个目标文件和源 key 投影 | 5 check events | 合计小于 10 秒 |

P0 实测结果：

| 路径 | 实测 | 结论 |
| --- | ---: | --- |
| 日线增量公式与临时 Parquet 写入 | 13.7 ms | 通过 |
| 四分钟增量公式与临时 Parquet 写入 | 2.459 s | 通过 |
| 最新日五个聚合 check 原型 | 1.111 s | 通过 |
| 10 日 daily 目标 readiness | 18.6 ms | 通过 |
| 5 日四分钟目标 readiness | 1.152 s | 通过 |
| 5 日四频度上游 QFQ 完整 readiness | 6.309 s | 通过 |

P6D 正式 Lake 验收发现，历史文件落地后分钟目标 readiness 的旧 lazy-view 读取模型会对同一批按股票年度保存的源文件重复打开。优化前五次独立连接耗时范围为 9.353 至 11.133 秒，三次超过 10 秒。读取模型收敛为“每频度/年度枚举一次 + 窗口身份键临时表”后，五次独立连接耗时为 3.021 至 4.747 秒，均值 3.574 秒，五次均通过 `<10s` 门禁。目标文件和 source/output 的完整 integrity 语义未改变，也没有新增持久化状态实体。

现有通用分钟 QFQ readiness 会扫描 1/5/15/30/60/90/120m 全部七个频度，5 日实测 16.267 秒，不得直接进入本专项 sensor 热路径。实现必须复用同一套正式 blocking-check 语义，但只读取本专项需要的 30/60/90/120m；不得通过弱化检查换取性能。

P0 增量公式样本使用最近 5 个交易日的有界上下文验证读取、窗口和写入形状；样本信号数量不是公式正确性证据。公式正确性仍以已有 4,610,961 次转移零差异审计和 P1 的人工字面量金样本为准。

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
| P1 | schema、path、contract、calculator、原子 writer 内核和金样本测试 | 已完成，只改代码/测试 |
| P2 | 五个 asset、五个聚合 check、catalog、目标 readiness 和四频度上游 QFQ readiness | 已完成，只改代码/测试 |
| P3 | 两个 job、两个 sensor、cursor 和治理文档同步 | 已完成；sensor 默认 STOPPED |
| P4 | 历史 bootstrap/rebuild/events 工具与 dry-run | 已完成代码与本地临时环境验证；正式写入未执行 |
| P5 | `dg check defs` 和正式只读 preflight | 已完成；零正式写入 |
| P6A | 新鲜只读 plan 与正式源年度样本 | 已完成；零正式写入 |
| P6B | 历史 Lake 写入与聚合文件审计 | 已完成 |
| P6C | runless event 补录与状态审计 | 已完成 |
| P6D | readiness 性能收口；sensor 启用与自然触发观察 | 历史性能已通过；正式实例后来已启动，但自然链路仍未验收 |

P0 已于 2026-08-08 完成并通过，正式报告为 `/private/tmp/qfq_nineturn_p0_profile_20260808_102030.json`。P1 已完成稳定 contract、schema、正式/staging path、全历史和增量 calculator、原子 writer 内核及受保护金样本。

P2 已完成五个资产、五个聚合 blocking check、五条 catalog 记录、目标文件 readiness，以及只读取 30/60/90/120m 的上游 QFQ readiness。生产 check/readiness 共享同一套不重算公式的文件、键、值域和 source key coverage 诊断；现有七频度 QFQ readiness 的公开接口和语义保持不变。P2 定向测试与全仓静态门禁共 141 个用例通过。全局 asset governance 测试仍被同一工作区中尚未收敛的指数分钟线/主要指数分钟线 catalog 与 active-definition 清单差异阻断，九转五个资产不在该差异集合中；该外部问题不在本专项 P2 范围内。

P3 已完成两个纯 asset-selection job、两个默认 `STOPPED` 的 bounded sensor、紧凑 cursor 和 topology/run-contract 治理文档同步。日线最近窗口为 10 日；分钟最近窗口为 5 日，且上游 QFQ 热路径只读取 30/60/90/120m。两个 sensor 均等待同日 QFQ、factor repair 和上一九转分区 ready，每 tick 最多提交一个日期；目标 check 已失败时不自动覆盖。方案没有冻结额外钟点，因此实现没有擅自增加固定时刻，正式运行窗口由这些数据门禁决定。

P3 与 P1/P2 合并验证共 160 个九转相关用例通过，未运行正式 Dagster、写 Lake、写 event 或修改动态分区。

P4 已实现默认只读的历史 plan、按年度集合计算的 bootstrap、带独立 plan/fingerprint 的 scoped rebuild，以及全历史 materialization + 最近 20 日 check 的 runless event 工具。跨年计算只携带每个代码 4 根尾部 bar 和 1 条计数种子，不会重置序列，也不会随年份增长重复扫描累计历史。P4 新增用例与现有九转/静态门禁合并运行 156 个用例全部通过；测试仅使用临时 Lake 和 ephemeral Dagster instance。

P5 已完成：`dg check defs` 全绿；正式只读 plan 冻结 5 个资产、65 个年度批次、214,577 个源文件、232,471,723 行和 15,315 个目标分区，源端 key/年份/频度契约全绿且无目标冲突。正式 Dagster instance 对账确认两套动态分区均完整覆盖 3,063 个源日期，五个新资产无历史 event/check，两个 job 无活动 run，两个 sensor 未启用。报告分别为 `/private/tmp/qfq_nineturn_history_plan_20260808_115819.json` 与 `/private/tmp/qfq_nineturn_p5_preflight_20260808_120003.json`。

P6A 已完成。新鲜只读计划为 `/private/tmp/qfq_nineturn_history_plan_20260808_122656.json`，规模与 fingerprint 保持不变。正式源年度样本先发现并阻断了 DuckDB 同日多 shard 问题；history helper 随后改为在 staging 内使用 DuckDB 合并同日 shards 为唯一、排序稳定的 `part-000.parquet`。修复后样本报告为 `/private/tmp/qfq_nineturn_p6_sample_20260808_123444.json`，覆盖五个资产的 2014 年批次，共 1,225 个临时文件、10,463,797 行，逐批 source/output 行数一致，`should_stop=false`。样本实测约 8.23 bytes/row，校准后的全历史输出约 1.78 GiB，staging 约同量级，磁盘空间充足。正式 Lake 仍没有九转目标文件。

下一阶段为 P6B 正式历史 Lake 写入。历史 Lake 写入、runless event 补录和 sensor 启用仍是三个不同的正式写入边界，必须分别获得明确批准；P6A 通过不能自动授权后续写入。

P6B 首次 build 已按 fail-closed 停止。真实跨年数据暴露出旧 compact state 只保留历史 context、却丢失当年未出现代码 seed 的缺陷；修复后五个资产连续两年真实样本与 158 个回归用例均通过。首次执行留下 3,552 个本轮新建文件，恢复复用时又在日线 `2016-01-11` 证明旧输出与修正结果不一致，因此这些文件不能作为正确历史继续复用。当前未写任何 Dagster event/check，job/sensor 均未运行。P6B 恢复必须先把两个新九转目标根整体移入同卷 quarantine，再从 existing target 为 0 的新鲜计划完整重建；禁止直接删除或就地覆盖冲突文件。

P6B 已完成恢复和正式历史 Lake 重建。3,552 个失败输出已连同逐文件 SHA-256 manifest 原子隔离到 `/Volumes/datasource/data_lake/_quarantine/qfq_nineturn_p6b_failed_20260808_130229`；修正后的 build 从 existing target 为 0 的新鲜计划生成 15,315 个正式文件、232,471,723 行，实际约 1.66 GiB。最终审计 `/private/tmp/qfq_nineturn_history_final_audit_20260808_131457.json` 为 `should_stop=false`，五个资产各 3,063 个分区，所有文件、行数、schema、key、日期和频度契约全绿。P6B 没有写 Dagster event/check 或启用 sensor；下一阶段为 P6C runless event 独立审批。

P6C 只读计划已完成，报告为 `/private/tmp/qfq_nineturn_events_plan_20260808_131827.json`，`should_stop=false`。计划只补全历史 15,315 条 materialization 和五个资产各最近 20 日的 100 条聚合 check，共 15,415 条 event；不补全历史 check。正式 event apply 仍待单独批准。

P6C 正式 apply 已完成：实际写入 15,315 条 materialization 和 100 条最近窗口聚合 check，post-plan `/private/tmp/qfq_nineturn_events_plan_20260808_133743.json` 的剩余候选为 0、`should_stop=false`。P6D 初步只读验收确认五个资产各 3,063 个分区完整，日线最近 10 日和分钟最近 5 日均 ready；分钟 readiness 初测 11.08 秒且重复测量三次越过 `<10s` 门禁。代码级 profiling 证明瓶颈来自同一年度源文件被逐日期重复枚举和扫描；改为每频度/年度一次枚举并物化最近窗口身份键后，正式 Lake 五次独立重测为 3.021 至 4.747 秒，全部通过，完整 integrity 语义不变。这里的“sensor 未启用”和“目标 check 未通过”都只记录 P6D/去价格迁移前的历史状态；当前分钟状态以 10.1 节为准。

### 10.1 2026-08-15 分钟九转去价格专项 S0～S5

| 阶段 | 当前状态 | 退出条件 |
| --- | --- | --- |
| S0 文档与合同冻结 | 已完成 | 八列分钟 schema、日线隔离、正式重建与事件边界写入总方案和 LLD |
| S1 代码合同改造 | 已完成 | writer、check、Reader、history 工具只输出八列；日线 `close_qfq` 与公式结果无漂移；canonical DuckDB 固定 2GB/1线程并用 16GiB 真实 RSS 自动门禁；Definitions 与专项静态门禁通过 |
| S2 正式只读计划 | 已完成 | 计划 `01d63b…d03757` 冻结 2014-01-02～2026-08-14、3,068 日、12,272 目标文件、197,753,897 行、52 年度批次；`should_stop=false` |
| S3 candidate、审计与正式替换 | 已完成 | 四频 candidate 全绿后按 30/60/90/120 顺序原子提升；正式聚合审计 schema/键/分区/值域失败均为 0 |
| S4 Dagster 事件恢复 | 已完成 | 计划 `214001…a7f5` 精确追加 12,272 materialization 与 80 check；日线候选 0，post-plan 候选 0 |
| S5 运行恢复与自然链路验收 | 已完成 | Reader/API/readiness/Definitions 回归通过；分钟 sensor 恢复 RUNNING 并自然评估最近 5 日均 ready；下一交易日新增分区留作运维观察 |

正式执行使用固定 staging 根 `/Volumes/datasource/data_lake_staging/cn_a_minute_gold_p12_nineturn`。四频行数分别为 93,044,536、46,531,692、34,898,769、23,278,900；候选审计每个年度批次最慢 14.47 秒。S2～S3 观测到的最高单进程 RSS 为 10,606,608,384 bytes，低于 16GiB 门禁。最终 5 日 readiness 检查 20/20 文件、470,832 行，失败行 0，耗时 2.11 秒；`000001.SZ` 四频各 10 次 Reader 实测 P95 分别为 150/32/29/25ms，返回结果无价格字段。

执行没有访问 Tushare、Prod DB 或旧 Lake，没有运行 migration、Dagster materialize/backfill 或 Kopia，没有删除历史事件，也没有修改日线或指数资产。旧九列事实只保留在历史执行记录中，不再代表当前正式合同。

## 11. 开发前停止条件

出现以下任一情况，停止开发并修订本文：

1. 90m/120m 上游正式 bar 契约在开发前发生变化，且现有 QFQ asset/check 未完成收口。
2. 精确日常计算需要全历史扫描，无法满足已冻结性能预算。
3. 需要新增独立 state 才能保证正确性，说明当前无 state 方案不成立。
4. 历史预计空间、文件数或耗时超过 P0 批准上限。
5. 现有 factor repair metadata 无法区分日常等比例修复与非日常历史事实修正。

## 12. 2026-10-22四个分钟分区修正方案（2026-10-26，待开发）

### 12.1 目标、依据与边界

本步先修正分钟日更的候选写入和失败续跑，再通过现有`gold_stk_mins_qfq_nineturn_update_job`补22日30/60/90/120m四项。开发细节、预算和验收见[原LLD第22节](./dagster-stock-qfq-nineturn-dataset-low-level-design.md#22-2026-10-22分钟九转写入修正与补齐lld待开发)。本次授权仅为代码审计和补全方案/LLD，不包含开发、正式读取或补数。

依据为当前代码、CodeGraph调用/影响面结果，以及[22日恢复记录](../../reports/datasets_recovery_20261022_20261024/README.md#47-分钟九转代码审计及原方案lld补全仅文档)。MACD/KDJ日更和26股repair已完成；九转没有直接MACD依赖，不应再重跑它们。因子repair已完成，但仍须确认上一九转种子可继续使用的条件，不能以“任务成功”代替公式依据。

本轮不改九转公式、频率、八列正式合同、正式路径、四条原检查、job选择和运行方式、Reader、sensor、日线writer或历史bootstrap；不做九转全历史重算，不写Prod、不补runless event、不装依赖、不新增配置。只允许22日四个正式文件进入本轮写入范围。两个sensor继续停用，保留“23日全部补齐后再启用”的TODO。

### 12.2 已核清的问题与影响

| 当前步骤 | 原本应当怎样 | 当前实现及影响 | 本轮处理 |
| --- | --- | --- | --- |
| 候选位置 | 只在`/Volumes/datasource/data_lake_staging` | `paths.py`分钟helper返回正式Gold内`_staging` | 分钟入口改用现有发布组件，删除不再使用的旧分钟helper |
| 写入失败/重启 | 保留现场，能识别已校验和已提升文件 | 共享writer开头删除旧候选，`finally`再次删除；无逐文件记录 | 接入现有逐文件记录，失败保留，不自动重跑 |
| 续跑输入 | 实际使用的QFQ、上一九转、SQL和合同都相同 | 原fingerprint只有QFQ相对路径、大小、mtime，不含上一九转 | 额外冻结实际输入身份，不改变旧metadata的含义 |
| 提升前校验 | 检查完整候选合同和来源键 | 旧validator只核自身合同/值域/行数；逐键覆盖和分钟时间所属日期在正式check才核 | 分钟候选复用现有完整性检查，先通过再提升；原四checks仍执行 |
| 共享影响 | 四分钟修正不改变其他任务 | 日线与分钟共用`_write_qfq_nineturn_partition` | 仅分钟writer接新路径；日线保留原调用，单独列明其现存路径问题，不执行日线 |

这不是公式修复，也没有证据表明此前九转数值因这些写入问题算错。修正的目的是让本次正式补齐符合当前路径、校验、原子替换和续跑规则。日线现存同类问题不因本轮绕过或被认定已解决；其后续执行必须先完成自身修正。

### 12.3 复用与实现顺序

1. 复用`io/stk_mins_qfq_publication.py`中的`StkMinsQfqPublication`，明确增加`nineturn`类型，不冒用`macd_kdj`类型；QFQ和MACD的路径、配置及算法不改。其他候选组件缺少九转合同或输入绑定/续跑记录，不另起一套实现。
2. 分钟planner在读取前保存所读文件的五字段stat身份，结束时复核；涵盖两年QFQ、上一九转、实际探查的候选历史。writer继续复核。只对文件属性取摘要，不对历史源文件做全量SHA。
3. 每个频率/日期对应一个正式文件。将稳定的输入说明交给现有`bind`保存，不把完整历史行情或计算SQL重复执行两次。之后原SQL只计算一次候选。
4. 候选完整性检查通过后，只做一遍候选SHA；提升前复核输入和候选/目标身份，使用现有同文件系统`os.replace()`和逐文件记录。正常结束只核记录/stat，不重复SHA或公式计算。
5. 失败保留候选、输入说明和记录。恢复仍使用Dagster原root run身份；有效候选可复用，已提升文件不重写。恢复需要再次核对输入，并可能重新执行planner，不承诺零历史读取。四频不是一个事务，也不承诺固定频率执行顺序。

### 12.4 读取和规模

当前分钟planner枚举目标年及前一年，22日即2025/2026。计算读取`ts_code/freq/trade_date/trade_time/close`五个源字段，先算前4根比较，再筛22日输出；不能提前裁成22日或套用日线20天窗口。前一九转分区每代码最后一根提供方向与计数。缺种子或当前两年不足4根前序时，还会先探查相关候选代码的各年历史；真正需要回算的代码才进入完整计算。原500上限作用于最终回算名单，不能改成“候选超过500就拒绝”，否则会误拦合法新股。

复用已有MACD预检文件大小、QFQ完成行数和后续来源身份未变的证据，未重新读取正式Parquet：

| 频率 | 2025文件字节 | 2026文件字节 | 22日预期输出行数 |
| --- | ---: | ---: | ---: |
| 30m | 381,691,225 | 319,739,488 | 44,560 |
| 60m | 219,228,762 | 182,933,116 | 22,280 |
| 90m | 173,667,836 | 145,197,670 | 16,710 |
| 120m | 126,842,940 | 105,395,385 | 11,140 |
| 合计 | 901,430,763 | 753,265,659 | 94,690 |

两年共44,224文件、1,654,696,422B（1.541056GiB）。这是源文件集合的大小，不是总读取量；既有planner多条键查询、一次计算、候选覆盖及四个原检查都必须单列。LLD按SQL的读取入口给出保守计算式，并包括失败续跑、最后验收和临时工作文件；不把投影/日期裁剪后的实际I/O说成整文件实测。

尚缺21日四个九转文件的身份/质量依据，以及候选代码、最终回算代码及其历史文件大小。不能预填“回算0只”或宣称总读取已经精确算完。后续先复用控制记录及文件metadata补这些证据；若需要读两年键字段确认候选，须先单独说明并取得该范围批准，再按实际名单核算更早历史。没有批准，不调用会立即探查候选全历史的完整planner来充当只读预检。

本轮不新增性能样本、超时、临时空间额度或自动中断。既有resource和发布组件自身检查保持原样，预算用于说明开销；不能再次因自行估低临时空间而中止任务。

### 12.5 推进与完成条件

| 阶段 | 动作 | 通过条件 |
| --- | --- | --- |
| 本次 | 审计代码、完善原方案和LLD | 调用影响、输入、校验、预算、失败/续跑和测试逐项写清；仅文档 |
| 开发 | 按LLD修改分钟写入，运行隔离测试 | 正反例、正常变化、日线/历史及QFQ/MACD回归通过；不接正式资源 |
| 正式前确认 | 补必要metadata/前序/因子依据，限定实际读取范围 | 无活动writer，四目标缺失或已有可核记录；精确前序为21日；历史读写获明确批准，执行入口与配置落入LLD |
| 正式补齐 | 原job一次执行22日四资产及四原checks | 每项原检查通过且绑定对应物化；失败不自动重跑，按实际逐文件记录汇报 |
| 收尾 | 记录/stat与原四checks销账 | 只减这四项，原109项清单剩0；不以此宣称23日已补齐，也不重做全局审计 |

LLD列出的执行前待核项属于正式操作条件，不表示本次文档授权已包含相应读取或写入。不得以总方案、此前MACD批准或一般性的“继续推进”代替本链具体批准。
