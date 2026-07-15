# `dc_daily` 技术指标 Gold 数据集技术方案

> 状态：P8A Gold Bootstrap/lake 只读对账、P8C 临时样本 Bootstrap、P8D 正式 Gold 全量 Bootstrap 和 P9 事件验收均已完成。P10A 已启用 normal sensor；repair sensor 仍保持 `STOPPED`，尚未完成 3 个交易日观察。
>
> 本文是正式技术方案。代码级文件、SQL、测试和执行顺序见
> [`dagster-dc-daily-technical-indicators-low-level-design.md`](dagster-dc-daily-technical-indicators-low-level-design.md)。

## 1. 目标与边界

新增一个基于 `silver_dc_daily` 的 Gold 技术指标数据集，为每个板块分类序列生成：

- MA：5、10、15、20、30、60、120、250 日均线；
- KDJ：沿用股票分钟线已经验证的 `9,3,3` 口径；
- MACD：沿用股票分钟线已经验证的 `12,26,9` 口径；
- BOLL：固定 `N=20`、`P=2`，标准差冻结为总体标准差 `ddof=0`，使用 DuckDB `stddev_pop` 等价实现。

本专项只新增一个 Gold asset，不新增独立 state asset，不把指标拆成多个 Dagster asset。原因是当前 `silver_dc_daily` 只有约 596,200 行、1,065 个 `(ts_code, category)` 序列、611 个交易日；全历史批量计算可以在一个有界 DuckDB 查询内完成，额外 state asset 会增加 materialization、check、依赖和事件历史，而不能解决当前规模的性能问题。

本轮不包含：

- 修改 `dc_index`、`dc_member`、`dc_daily` Raw/Silver 语义；
- 把指标公式正确性重新交给 Dagster blocking check；
- 通过前端把空值转换为 0；
- 为了补历史而创建每个日期一个 Dagster run；
- 运行正式 Bootstrap、写正式数据湖或写 Dagster event。

## 2. 审计基线

### 2.1 当前输入数据

只读审计的 `silver_dc_daily` 当前事实：

| 项目 | 结果 |
| --- | ---: |
| 起始交易日 | `2024-01-02` |
| 最新交易日 | `2026-07-14` |
| 交易日数 | 611 |
| 总行数 | 596,200 |
| `ts_code` 数量 | 1,051 |
| `category` 数量 | 3 |
| `(ts_code, category)` 序列数 | 1,065 |
| 有至少 250 条观测的序列 | 976 |
| 覆盖全部 611 日的序列 | 902 |
| 业务主键重复 `(ts_code, trade_date, category)` | 0 |

当前三类 category 的行数为：地域板块 18,940、概念板块 267,006、行业板块 310,254；三类均覆盖 611 个交易日。最新日 `2026-07-14` 有 1,022 行。

这些数字只描述当前 lake 事实，不代表新 Gold 已经存在，也不替代开发后的真实联调。

### 2.2 初步性能基线

在只读环境中用 DuckDB 对当前 596,200 行做滚动 MA、BOLL 窗口和聚合试算，`DuckDB :memory:` 查询墙钟耗时约 0.14 秒。该样本没有包含完整 MACD 序列计算、Parquet staging、回读校验和原子替换，因此只能作为“全历史 set-based 计算可行”的初筛，不能作为上线性能承诺。

编码前必须重新测量完整 writer：读取、指标计算、写 staging、schema/行数/主键回读、原子替换和内存峰值都要单独记录。

## 3. 冻结的数据集契约

### 3.1 资产与分区

| 项目 | 冻结口径 |
| --- | --- |
| asset key | `gold_dc_daily_technical` |
| 数据层 | Gold |
| 业务域 / group | `board` |
| 来源 | `silver_dc_daily` |
| 物理路径 | `gold/board/dc_daily_technical/trade_date=YYYY-MM-DD/part-000.parquet` |
| 分区 | `cn_a_index_trade_days`，单 run 单 partition |
| 输出粒度 | 输入目标交易日存在的每个 `(ts_code, category)` 一行 |
| 排序语义 | 每个序列按 `trade_date` 升序，计算后只输出目标分区 |
| 空结果 | 目标日 Silver 无合法行时 fail closed，不生成空的“成功”文件 |
| 写入方式 | staging -> set-based 校验 -> 原子替换 |

`category` 是业务序列身份的一部分，不能丢弃、压缩或用 `ts_code` 单独分组。所有窗口、EMA、KDJ 状态均按 `(ts_code, category)` 独立计算。

### 3.2 输出字段

| 字段 | 类型 | 语义 |
| --- | --- | --- |
| `ts_code` | `VARCHAR` | 板块代码 |
| `trade_date` | `DATE` | 目标交易日 |
| `category` | `VARCHAR` | 行业 / 概念 / 地域，保留输入值 |
| `close` | `DOUBLE` | 输入 `silver_dc_daily.close` |
| `ma_5` | `DOUBLE` | 5 个有效观测的简单均值，不足时 `NULL` |
| `ma_10` | `DOUBLE` | 10 个有效观测的简单均值，不足时 `NULL` |
| `ma_15` | `DOUBLE` | 15 个有效观测的简单均值，不足时 `NULL` |
| `ma_20` | `DOUBLE` | 20 个有效观测的简单均值，不足时 `NULL` |
| `ma_30` | `DOUBLE` | 30 个有效观测的简单均值，不足时 `NULL` |
| `ma_60` | `DOUBLE` | 60 个有效观测的简单均值，不足时 `NULL` |
| `ma_120` | `DOUBLE` | 120 个有效观测的简单均值，不足时 `NULL` |
| `ma_250` | `DOUBLE` | 250 个有效观测的简单均值，不足时 `NULL` |
| `kdj_k` | `DOUBLE` | KDJ K 值 |
| `kdj_d` | `DOUBLE` | KDJ D 值 |
| `kdj_j` | `DOUBLE` | KDJ J 值 |
| `macd_dif` | `DOUBLE` | MACD DIF |
| `macd_dea` | `DOUBLE` | MACD DEA |
| `macd` | `DOUBLE` | `2 * (DIF - DEA)` |
| `boll_mid` | `DOUBLE` | BOLL 中轨，20 个有效观测不足时 `NULL` |
| `boll_upper` | `DOUBLE` | BOLL 上轨，20 个有效观测不足时 `NULL` |
| `boll_lower` | `DOUBLE` | BOLL 下轨，20 个有效观测不足时 `NULL` |
| `observation_count` | `INTEGER` | 当前序列截至本行的有效观测数 |
| `params_key` | `VARCHAR` | 参数合同标识 |
| `indicator_version` | `VARCHAR` | 指标实现版本 |

业务主键是 `(ts_code, trade_date, category)`。不增加 `id` 作为替代主键，不删除输入的 `close` 和 `category`。

### 3.3 预热期口径

- MA_N：当前序列有效观测数小于 N 时写 `NULL`；达到 N 后才写数值。
- BOLL 三条线：当前序列有效观测数小于 20 时全部写 `NULL`。
- KDJ、MACD：沿用分钟线的状态初始化口径，不用 `NULL` 替代算法定义的种子值。
- 不补交易日、不前向填充、不把空值改成 0。`observation_count` 让下游可以区分“指标尚未预热”和“实际计算结果”。
- 窗口按该 `(ts_code, category)` 的有效观测行计算，而不是按自然日制造缺失行。目标日没有输入行时不输出该序列。
- 前端和 API 必须按 nullable 数值处理指标预热期；本 Gold 不通过 0 掩盖“尚未可计算”。

## 4. 指标公式

### 4.1 MA

对每个 `(ts_code, category)`，按交易日升序取最近 N 个有效 `close`：

```text
MA_N = SUM(close over last N observations) / N
```

只有窗口有效观测数达到 N 才输出。N 集合固定为 `5, 10, 15, 20, 30, 60, 120, 250`。

### 4.2 MACD

固定参数 `fast=12, slow=26, signal=9`，公式和股票分钟线实现保持一致：

```text
EMA_fast[t] = alpha_fast * close[t] + (1-alpha_fast) * EMA_fast[t-1]
EMA_slow[t] = alpha_slow * close[t] + (1-alpha_slow) * EMA_slow[t-1]
DIF[t]      = EMA_fast[t] - EMA_slow[t]
DEA[t]      = EMA_signal(DIF[t], 9)
MACD[t]     = 2 * (DIF[t] - DEA[t])
```

首个观测的 EMA 以 `close` 初始化，DEA 以 0 初始化；同一序列的计算不能串到另一个 category。生产 SQL 必须采用有界 set-based 实现，不允许 Python 逐行计算。

### 4.3 KDJ

固定参数 `period=9, alpha=1/3, seed=50`：

```text
LLV[t] = 9 个有效观测的 low 最小值
HHV[t] = 9 个有效观测的 high 最大值
RSV[t] = (close[t] - LLV[t]) / (HHV[t] - LLV[t]) * 100
```

当 `HHV[t] == LLV[t]` 时 `RSV=50`。K、D 使用分钟线相同的平滑与种子：

```text
K[t] = (2*K[t-1] + RSV[t]) / 3
D[t] = (2*D[t-1] + K[t]) / 3
J[t] = 3*K[t] - 2*D[t]
```

首行 K/D 使用 50。KDJ 不创建额外 state asset，状态只在本次有界全历史/repair 计算中由 SQL 产生。

### 4.4 BOLL

固定 `N=20, P=2`：

```text
MID[t]   = MA(close, 20)
UPPER[t] = MID[t] + 2 * STD(close, 20)
LOWER[t] = MID[t] - 2 * STD(close, 20)
```

主流实现调研后的冻结结论是使用总体标准差：

```text
STD_POP(close, 20) = sqrt(sum((close - mean(close))^2) / 20)
```

DuckDB 实现使用 `stddev_pop(close)`，不得使用默认语义不明确的 `stddev`。同花顺公开公式只说明 `STD(X,N)`，没有在公式页公开分母；同花顺量化文章中的 Pandas `.rolling().std()` 是示例代码，不能直接当作同花顺客户端内核口径。TA-Lib 的 BBANDS 实现采用 population standard deviation，`pandas-ta` 的 BOLL 默认 `ddof=0`，这两者作为主流技术分析实现的对照基线。[TA-Lib 函数列表](https://ta-lib.org/functions/)、[TA-Lib 对照实现](https://docs.rs/nanobook/latest/nanobook/indicators/fn.bbands.html)、[pandas-ta BBANDS 源码](https://tradingstrategy.ai/docs/_modules/pandas_ta/volatility/bbands.html)、[同花顺 BOLL 公式](https://poi.10jqka.com.cn/store/formula/detail/indexid/97412)。

因此，不再把“必须拿到同花顺客户端样本”作为进入开发的阻塞条件。测试固定 `ddof=0` 的人工 fixture，并与 TA-Lib 或等价独立实现逐值对照；如果未来拿到可靠的同花顺高精度样本且出现差异，必须停止生产 Bootstrap，先重新审计公式口径。

## 5. 依赖与拓扑

```text
silver_dc_daily[trade_date]
        |
        v
gold_dc_daily_technical[trade_date]
        |
        +--> normal update sensor/job
        +--> historical repair sensor/job
```

正常链路只依赖同日 Silver；指标计算为了得到窗口，会读取冻结日期计划中目标日以前的 Silver 文件，但只输出目标日。历史修复链路依赖一个明确的 Silver repair batch 身份，不从 Dagster event history 猜测 repair 范围。

拟新增正式入口：

| 类型 | 名称 |
| --- | --- |
| asset | `gold_dc_daily_technical` |
| blocking check | `gold_dc_daily_technical_core_check` |
| normal job | `gold_dc_daily_technical_update_job` |
| normal sensor | `gold_dc_daily_technical_update_job_sensor`，默认 `STOPPED`，验收后再启用 |
| Silver repair producer job | `silver_dc_daily_repair_job`（P7，默认不自动运行） |
| repair job | `gold_dc_daily_technical_repair_job`（P7，op-based，默认不运行） |
| repair sensor | `gold_dc_daily_technical_repair_job_sensor`（P7，`STOPPED`，未启用） |

所有 check 必须显式绑定 `cn_a_index_trade_days`，每个 run 只处理一个 partition。run key、cursor、RunRequest 都必须走现有统一 builder，不手写 run key，不解析历史 run key。

## 6. Check 与状态治理

只保留一个合并的 partitioned blocking check：`gold_dc_daily_technical_core_check`。它检查当前分区文件和源输出的结构性事实：

1. 文件存在且行数大于 0；
2. schema、字段类型和 `indicator_version/params_key` 一致；
3. `trade_date` 与物理分区一致；
4. `(ts_code, trade_date, category)` 非空且唯一；
5. 输出键集合与同日 Silver 输入一致；
6. 输入 `close` 与输出 `close` 对齐；
7. `observation_count` 在每个序列内严格递增且从 1 开始；
8. 预热期字段允许 `NULL`，达到窗口后指标不得是 NaN/Inf；
9. BOLL 参数、MACD/KDJ 参数标识与合同一致。

不新增“MA 公式 check”“MACD 公式 check”“BOLL 公式 check”。公式正确性通过独立固定 fixture、分钟线公式对照和 `ddof=0` 主流实现对照测试完成；生产 blocking check 不能每次重算整段历史来证明自己刚刚算对。

文件存在但核心 check 失败时，sensor 不自动覆盖；文件缺失时才允许成为自动生成目标。sensor readiness 与正式 check 必须共享 predicates，避免“sensor 认为 ready、正式 check 变红”的语义漂移。

## 7. 正常更新与 repair

### 7.1 正常更新

正常 sensor 每 tick：

- 只看最近 10 个 `cn_a_index_trade_days` expected dates；
- 用一次 DuckDB connection 批量读取 Silver/Gold readiness；
- 不读取 Dagster event history、Prod DB 或 Tushare；
- Raw/Silver 未 ready 时不提交 Gold；
- 找到最早 Gold 文件缺口时最多提交一个 RunRequest；
- 已 materialize 但 blocking check 失败时 skip；
- cursor 只写 ASCII reason code、frontier、扫描文件数、elapsed_ms 和有限样本。

正常 asset 运行时读取目标日期之前所需的 Silver 历史窗口，在一个有界 DuckDB 计算中生成目标分区，再 staging 校验并原子替换。不能用逐日 Dagster run 递推，也不能在 sensor 中执行指标计算。

### 7.2 历史 repair

repair sensor 不能通过全历史 event 扫描猜测“哪些日期被修过”。它只接受一个明确的上游 Silver repair batch：

- `upstream_batch_id`；
- `source_revision` 或等价源版本；
- `source_repair_start_trade_date`；
- `source_repair_end_trade_date`；
- `indicator_recompute_start_trade_date`；
- `indicator_recompute_end_trade_date`；
- `context_start_trade_date`；
- `status.ready=true`；
- 受影响日期数、代码/category 范围和未截断标记。

这里必须区分“源数据修复范围”和“指标有效重算范围”。MA250 至少需要历史窗口；MACD EMA 具有递推影响，源数据修正后后续结果可能持续变化。若没有可验证的 EMA baseline，`context_start_trade_date` 必须回到指标历史起点，不能为了性能擅自截短。

`silver_dc_daily` repair producer 接收显式 source repair 范围和 indicator frontier，不从 event history 或文件 mtime 猜范围。它在一个 DuckDB connection 中先对所有 source 日期 staging，做旧/新 Silver 的 set-based 差异和 source revision 计算，只有确认存在真实变化且 batch 校验通过后才逐文件原子 promote。没有合法 batch 时 fail closed；相同内容重试返回 no-op，不产生 ready batch。

repair job 接收显式范围和 `upstream_batch_id`，一次有界扫描受影响范围及所需历史上下文，逐日期生成 staging 并原子替换。范围超过性能上限、源 batch 不 ready、日期未注册或输出对账不一致时整批停止，不拆成无界的一日一 run。

## 8. Bootstrap 与事件策略

### 8.1 Gold 文件 Bootstrap

Bootstrap 使用冻结的 `silver_dc_daily` 日期计划和一份有界 DuckDB 全历史输入：

- 读取 611 个 Silver 日期、约 596,200 行；
- 按 `(ts_code, category)` 排序计算全历史指标；
- 按日期输出 Gold 文件；
- 每批最多 20 个交易日，批内串行；
- staging 校验通过后原子替换；
- 失败日期可从报告续跑，禁止覆盖已存在但不合约的文件。

Bootstrap 不运行 Dagster job/sensor，不在正式 DB 中写 event。文件对账通过后，再单独设计全量 materialization 与最近 20 日核心 check event 的事件验收，不能把事件补录混入指标计算写入事务。

### 8.2 事件保留

- materialization 事实按全量文件保留策略处理；
- blocking check event 默认只要求最近 20 个 `cn_a_index_trade_days`，与当前事件治理口径一致；
- repair/status 账本若后续引入，必须单独保护，不进入普通历史清理白名单。

## 9. 性能门禁

| 路径 | 读取/写入模型 | 初始硬门禁 |
| --- | --- | --- |
| sensor | 最近 10 日，最多 10 个 Silver + 10 个 Gold 文件，一个 DuckDB connection | 稳态目标 < 10 秒；不得读 event history |
| 正常 asset | 一次 set-based DuckDB 读取目标日前所需 Silver 文件，输出 1 个目标日文件 | 当前规模目标 < 15 秒；超限先优化，不调大 RPC timeout 掩盖 |
| Bootstrap | 一次全历史批量计算，按最多 20 日写 staging，Python 只做编排 | 必须有完整读/算/写/回读基准；禁止全历史 Python 行循环 |
| repair | 一个显式 bounded range，单次扫描、分日期 promote | 范围或耗时超过预设上限必须 fail closed，不拆成无界 runs |
| check | 只扫描当前 Gold 分区和同日 Silver 输入 | 不读取全历史，不重复重算完整指标 |

必须记录：文件数、行数、DuckDB 查询耗时、Parquet 写入耗时、回读校验耗时、峰值内存、临时文件大小、输出文件数、sensor cursor 大小、Dagster API 调用次数。任何全历史 event 查询、逐行 Python 计算、无界文件 glob、重复扫描同一全量文件或目标文件覆盖都不可接受。

## 10. 分阶段推进

### P0：方案与合同冻结（本轮）

- 完成源数据审计、分组粒度、字段、路径、参数、空值和 repair 边界冻结；
- 形成正式方案和 LLD；
- 不写生产代码，不写 lake，不写 Dagster DB。

### P1：标准公式与性能验证

- 固定 `ddof=0` BOLL fixture，并与 TA-Lib/等价主流实现对照；
- 对当前 611 日输入完成单目标日、10 日、全历史、repair 范围性能测试；
- 只有样本和性能均通过，才进入代码。

#### P1 验证结果（2026-07-15，只读）

P1 已完成，测试只读 `/Volumes/datasource/data_lake/silver/board/dc_daily`，临时输出均位于 `/private/tmp`，没有写正式 lake、Dagster DB、event 或运行任务。完整原始报告：
`/private/tmp/dc_daily_technical_p1_report_20260715.json`；隔离进程和写出策略报告：
`/private/tmp/dc_daily_technical_p1_memory_report_20260715.json`。

- 输入事实：611 个 Silver 分区文件，`2024-01-02` 至 `2026-07-14`，约 596,200 行、1,065 个 `(ts_code, category)` 序列。
- BOLL fixture：20 点总体标准差 `5.766281297335398`，DuckDB `stddev_pop` 完全一致；样本标准差 `5.916079783099616`，证明 `ddof=0` 不是误用 `ddof=1`。
- MACD/KDJ fixture：40 行，独立 Python 递推与 DuckDB set-based 结果最大误差 `1.14e-13`。
- 10 日 readiness：10 个 Silver + 10 个临时 Gold 文件，单 DuckDB connection，`8.13ms`，Dagster event history/Tushare/Prod DB 调用均为 `0`。
- 隔离进程基线：单目标日 `0.664s / 526MB`；20 日 `0.675s / 553MB`；250 日 `1.013s / 992MB`；全历史 `1.585s / 1.56GiB`。并行 `COPY ... PARTITION_BY(trade_date)` 产生了多于日期数的文件，不能作为正式写出方式。
- 采用“单次全历史 DuckDB 临时关系 + 按日期逐个 `COPY` 到 `part-000.parquet`”后：20 日 `2.52s / 490MiB / 20 文件`；全历史 `9.57s / 511MiB / 611 文件`。输入文件只扫描一次，正式 lake 写入和 Dagster API 调用均为 `0`。

P1 结论：公式口径和性能均通过。P2 可以开始，但 writer 必须采用有界临时关系和逐交易日单文件写出；禁止直接使用并行 `PARTITION_BY`，禁止退回 Python 大表逐行计算。repair 的有效范围仍必须由显式 upstream batch 提供，不能因为本次 benchmark 通过就放宽 repair 范围。

### P2：合同与基础设施

- 增加常量、schema、path、catalog entry；
- 先写指标 fixture、schema 和静态门禁；
- 验证新资产没有把 check 拆成高基数多项。

#### P2 实现结果（2026-07-15）

P2 已完成，改动严格停留在合同和 catalog 基础设施边界：

- 新增 `orchestrator/defs/run_contracts/dc_daily_technical.py`，冻结历史起点、MA/MACD/KDJ/BOLL 参数、`ddof=0`、10 日 sensor 窗口、`params_key` 和 `indicator_version`。
- 新增 `GOLD_DC_DAILY_TECHNICAL_SCHEMA`，冻结字段顺序、类型、MA/BOLL 预热期 `NULL` 语义，并明确 `high/low` 只属于输入合同、不进入 Gold 输出。
- 新增 `gold_dc_daily_technical_path(...)`，物理布局固定为 `trade_date=.../part-000.parquet`。
- 在 `lake_assets.py` 注册 contract-only catalog entry 和 `trade_date` Gold partition model；在 `name_mapping.py` 补齐展示名称。
- 在治理矩阵中登记唯一 blocking check `gold_dc_daily_technical_core_check`，并将该资产显式标记为 planned catalog asset。P4 创建 active check 前，治理测试不会把它错误地当成已加载的 active definition。
- 新增 `tests/test_dc_daily_technical_contracts.py`，覆盖常量、schema、path、catalog、治理策略、事件策略、性能约束以及阶段边界。

本阶段没有新增 active asset、check、job、sensor，没有写正式 lake、Dagster DB 或 Dagster event。P2 聚焦测试为 `103 passed`；P3 回归测试为 `113 passed`，仅有现有 Pydantic/Dagster deprecation warnings。P3 的临时 lake 性能报告为 `/private/tmp/dc_daily_technical_p3_report_20260715.json`。

### P3：Gold writer 与公式测试

P3 已完成，新增 `orchestrator/defs/assets/dc_daily_technical.py`，但该文件只提供 writer，不包含 Dagster decorator。实现固定采用：

- 从 `silver_dc_daily` 的显式历史交易日文件列表读取输入；不做无界 glob，不访问 Dagster event history；
- 一个 DuckDB 临时 source relation 完成 schema、日期、代码、category、数值域和业务主键校验；
- 使用 DuckDB set-based 窗口、闭式 EMA、KDJ 递推、`stddev_pop` BOLL 计算；不做 Python 大表逐行计算；
- 目标日只输出同日 Silver 中存在的 `(ts_code, category)`，MA/BOLL 预热期写 `NULL`；
- staging Parquet 回读 schema、行数、日期、主键、metadata、有限值和 warmup 规则，通过后才 `os.replace`；
- 已有且合同通过的目标幂等跳过，已有但错误或并发出现的目标拒绝覆盖；任何源校验、COPY、回读异常都会清理 staging。

新增 `tests/test_dc_daily_technical.py` 覆盖 BOLL 总体标准差、MACD/KDJ 独立递推对照、category 隔离、预热期 `NULL`、schema 回读、幂等跳过、重复源键、日期错误和失败不覆盖。

2026-07-15 只读使用正式 Silver 输入、临时 symlink lake 和临时 Gold 输出完成性能验证：10 日上下文 `45.4ms`、250 日上下文 `419.6ms`、611 日全历史上下文 `981.3ms`；分别扫描 10/250/611 个 Silver 文件，输出均为单个 `part-000.parquet`，staging 残留为 0。正式 lake、Dagster DB 和 event 均未写入。

### P4：Asset、核心 check、normal job/sensor

P4 已完成，新增正式定义但没有启用 sensor、运行 Dagster job 或写正式 lake/event：

- `assets/dc_daily_technical_asset.py`：单资产、单分区 Gold wrapper，依赖 `silver_dc_daily`，调用 P3 writer；
- `checks/dc_daily_technical_checks.py`：唯一 `gold_dc_daily_technical_core_check`，显式绑定 `cn_a_index_trade_days`，`blocking=True`，多分区执行 fail closed；
- `asset_guards/dc_daily_technical_quality.py`：check/readiness 共用 schema、日期、主键、Silver key/close 对账、warmup、有限值和参数版本 predicates；
- `asset_guards/dc_daily_technical_lake_readiness.py`：最近 10 个 expected trade dates 的一次 DuckDB batch scan，文件缺失与已 materialize check failure 分离；
- `jobs/dc_daily_technical.py`：`gold_dc_daily_technical_update_job` 只选择 Gold asset 与其核心 check；
- `sensors/dc_daily_technical_sensor.py`：`gold_dc_daily_technical_update_job_sensor` 默认 `STOPPED`，每 tick 最多一条 RunRequest，使用统一 run key/cursor builder；
- `sensors/readiness.py`：登记 `gold_dc_daily_technical` readiness spec，与治理矩阵保持一致。

P4 测试与验证结果：

- P4 定义、readiness、sensor、静态门禁专项 `92 passed`；P2/P3 writer、contract、治理和资产门禁回归 `37 passed`；
- definitions 本地加载成功，`gold_dc_daily_technical` 已进入 asset graph；
- readiness 已验证：Gold 文件缺失返回 `materialized=False` 可触发；文件存在但 schema/core check 失败返回 `materialized=True`，sensor 不自动覆盖；
- sensor 已验证：最近 10 日、有界 DuckDB、单 tick 最多一个 RunRequest、registered gap 先行、无 Dagster event history API 调用、cursor 小于 8KB 且 ASCII；
- 本轮没有运行 `dg`、没有启动 daemon/webserver、没有启用 sensor、没有写正式 lake、Dagster DB 或 event。

### P5：Repair 协议与 repair job/sensor

P5 本轮只完成 repair prerequisite，不开发或启用 Gold repair job/sensor：

- 已审计当前代码：`silver_dc_daily` 只有 normal writer/asset，没有现成 Silver repair producer；股票 QFQ repair metadata 不属于板块日线 Silver 上游事实，不能直接复用；
- 新增通用 `SilverRepairBatch` 协议，要求 `producer_run_id`、`upstream_batch_id`、`status=ready`、`source_revision`、源修复范围、指标重算范围、context 起点、目标 frontier、受影响日期/序列统计、哈希、`truncated=false`、协议版本和 selected partition count；
- 新增 `silver_dc_daily` 窄适配器，未来 Silver repair writer 必须通过该适配器生产/解析 batch，不允许由 Gold sensor 扫描 event history 或自行猜范围；
- 明确定义：`affected_date_count` 是 source repair 范围的 expected 交易日数量，`selected_partition_count` 是 indicator recompute 范围的 expected 交易日数量；
- 校验已覆盖：日期格式与 expected calendar、注册分区、source/indicator 范围包含关系、context 起点、frontier、计数一致性、source revision、series hash、截断标记和重算预算；
- 测试已覆盖 plain/namespaced metadata 往返、缺字段、非 ready、截断、范围越界、注册缺口、计数不一致和预算超限；
- 在实际 `silver_dc_daily` repair producer 能稳定产生真实 source revision 和 ready batch 前，Gold repair sensor 必须保持 `STOPPED`；该前置已在 P6 完成，P7 sensor 仍保持 `STOPPED`，未经正式观察不得启用。

P5 验证结果（2026-07-15）：新增协议测试与 P2-P4 定向回归共 `106 passed`；新模块通过 `py_compile`，definitions 加载成功，asset graph 保持 67 个资产且没有新增 repair asset/sensor。本阶段没有运行 `dg`、job、sensor，没有写正式 lake、Dagster DB 或 event。

### P6：Silver repair producer（已完成）

- 新增 `asset_guards/dc_daily_silver_repair_producer.py`，从 Raw `dc_daily` 重建显式 source repair 日期；不定义 Dagster asset/job/sensor，不读取 event history，不写 Dagster DB/event。
- `dc_board_silver.py` 新增不 promote 的 staging 边界；producer 一次只建立一个 DuckDB connection，先 staging 全部 source 日期，再比较旧 Silver 与 staging 的 `(ts_code, trade_date, category, close, high, low)` 集合。
- `source_revision` 是规范化 Silver 指标输入列的稳定 SHA-256 内容版本，不使用 mtime、run history 或 event storage id；只将受影响序列的 hash 写入 batch，不写完整序列列表。
- 固定 source repair 上限为 20 个 expected 交易日，indicator recompute 上限为 60 个 expected 交易日；超限、注册缺口、上下文文件缺失、旧目标 schema 损坏或输入校验失败均在 promote 前 fail closed。
- 只有真实内容变化的 source 分区才 promote；无变化重试清理 staging 并返回 `no_op=true`、`batch=None`。
- P6 临时湖测试覆盖真实变化返回 `status=ready`、稳定 source revision、no-op、预算拒绝、非法 Raw、损坏旧目标、staging 清理和单连接约束；本阶段未写正式 lake、Dagster DB 或 event。

P6 验证结果（2026-07-15）：producer、Silver writer 和 repair protocol 定向测试共 `26 passed`；新模块通过 `py_compile`。P7 在此基础上实现 Gold repair 交接和有界重算。

### P7：Gold repair definition（已完成本地开发）

- 新增 `silver_dc_daily_repair_job`：调用 P6 producer，ready batch 只通过低基数 scalar run tags 交接；no-op 不发布 ready batch。tag 写入失败不会触发 Gold repair。
- 新增 `SilverRepairBatch.to_run_tags()` 和 source-specific tag parser；解析继续校验 `status=ready`、source asset、source revision、日期范围、注册分区、`truncated=false` 和 60 日上限。
- 新增 `assets/dc_daily_technical_repair.py`：一个 DuckDB connection 读取 context 到 indicator end，source revision 与 batch 对账，一次 set-based 计算后逐目标日期 staging、回读校验，全部通过后才原子替换；repair 明确允许替换已有目标，不复用 normal writer 的 skip 语义。
- 新增 `gold_dc_daily_technical_repair_job`：op-based，不使用多分区 asset job；每个实际重算日期写一条带 `partition` 的 Gold materialization 和现有核心 check event，不新增 repair check。
- 新增 `gold_dc_daily_technical_repair_job_sensor`：`SUCCESS` run-status sensor，只读取触发 producer run 的 tags、交易日历、dynamic partitions 和当前 Silver 文件；不读 event history/Tushare/Prod DB，验证 producer run id 和 source revision 后最多提交一个 upstream-triggered RunRequest，默认 `STOPPED`。
- P7 定向测试覆盖 tags round-trip、source revision mismatch、60 日预算、staging 清理、单连接、partitioned repair events、sensor run key/config、无 event history 和默认停止状态。未执行正式 job/sensor、未写正式 lake、Dagster DB 或 event。

### P8：Bootstrap/lake 对账与事件验收设计

#### P8A：Bootstrap/lake 只读对账（已完成）

正式历史 Bootstrap 的 expected end 不能直接取交易日历文件的最大日期。当前 SSE 日历已预置到 `2026-12-31`，其中未来日期不是本次历史数据缺口。P8A 冻结口径为：

```text
historical_expected_dates = SSE open dates >= 2024-01-02
                             and <= latest existing silver_dc_daily date
```

2026-07-15 只读报告：`/private/tmp/dc_daily_technical_p8_lake_reconciliation_20260715_v2.json`。

- source frontier：`2026-07-14`；历史 expected 日期：611 个，`2024-01-02..2026-07-14`；
- `silver_dc_daily`：611 个文件、596,200 行、1,065 个 `(ts_code, category)` 序列；
- schema 与合同一致，分区日期错位 0，身份字段异常 0，业务主键重复 0；
- Silver 临时文件 0，异常路径 0；
- `gold_dc_daily_technical` 目标文件当前为 0，历史目标冲突 0，Gold 临时文件 0；
- DuckDB 只读聚合耗时约 `735ms`，Dagster event history 调用 0，lake/DB 写入 0；
- `should_stop=false`，允许进入 Gold 临时样本 Bootstrap；这是 P8A 对账时的状态，正式 Gold 文件随后由 P8D 生成。

第一次报告 `/private/tmp/dc_daily_technical_p8_lake_reconciliation_20260715.json` 因把日历未来的 116 个日期误计入缺口而停止，已确认是审计范围错误，不是 Silver 数据缺失；v2 已按 source frontier 修正并作为有效报告。

#### P8B：事件验收计划（已完成）

Gold 文件生成并通过全量聚合对账后，事件验收分为：

1. 只读 dry-run：确认 611 个 Gold materialization 目标事实、最近 20 个 check 目标事实、已有 event 状态、缺文件和计划事件数；不得调用写入 API。
2. 小样本：选择起始日、中间日、最新日各 1 个，先写 materialization，再写对应 partitioned core check，确认 UI/readiness 的 partition 归属和 target materialization 关系。
3. 正式批量：materialization 全历史 611 个分区；check 仅最近 20 个交易日（`2026-06-16..2026-07-14`），计划总量 `611 + 20 = 631` 个 event。每批失败立即停止，不把事件补录当作 Dagster daily backfill。
4. 最终验收：聚合核对 event 数量、分区归属、latest materialization/check、最近 20 日 readiness，以及不影响 normal/repair sensor 的后续判断。

正式事件写入必须复用 Gold 的共享 core predicates；只对文件已通过同一语义的分区写绿事件。该设计已由 P8D/P9 的正式执行验证，P8A/P8C 阶段仍未调用 `report_runless_asset_event(...)`。

#### P8C：Gold 临时样本 Bootstrap（已完成）

2026-07-15 在隔离临时 lake 中复用正式 Gold normal writer，使用正式 Silver 文件的只读符号链接作为输入，未写正式 lake、Dagster DB 或事件。报告：
`/private/tmp/dc_daily_technical_p8_sample_bootstrap_20260715_174919.json`；临时 lake：
`/private/tmp/dc_daily_technical_p8_sample_lake_20260715_174919`。

- 样本日期为起始日 `2024-01-02`、中间日 `2025-04-10`、最新日 `2026-07-14`；输入链接 611 个 Silver 分区文件；
- 三个 Gold 分区均成功生成并通过共享 `gold_dc_daily_technical_core_check` 语义审计，输出行数分别为 `940`、`975`、`1022`，schema、日期、主键、close 对账和指标 warmup 均通过；
- 每个样本均为单文件 staging -> schema/质量回读 -> 原子 promote，staging 残留为 0；
- 最新日 611 日上下文 DuckDB 计算约 `607ms`，端到端约 `1049ms`；中间日 306 日上下文端到端约 `589ms`；
- 临时 Gold 文件和正式 Gold 文件相互隔离；样本阶段 Dagster event history/Tushare/Prod DB 调用均为 0，正式 lake/DB/event 写入均为 0；
- 样本通过后进入 P8D 正式全量 Bootstrap，不能由样本结果自动触发正式写入。

#### P8D：正式 Gold 全量 Bootstrap 与文件对账（已完成）

2026-07-15 在正式执行确认后，按 P8A 冻结的 `2024-01-02..2026-07-14` 交易日范围，串行生成 611 个 Gold 分区。执行期间不运行 Dagster job/sensor，不调用 Tushare/Prod DB，不写 Dagster event；只有 Gold Parquet 正式写湖。

报告：

- preflight：`/private/tmp/dc_daily_technical_p8_full_bootstrap_preflight_20260715_175436.json`；
- Bootstrap：`/private/tmp/dc_daily_technical_p8_full_bootstrap_20260715_175530.json`；
- 全量文件对账：`/private/tmp/dc_daily_technical_p8_full_bootstrap_audit_20260715_180211.json`。

验收结果：611/611 文件生成，596,200 行，611/611 日期通过共享质量语义，失败日期 0，意外文件 0，staging 残留 0；Bootstrap 约 369.7 秒，全量 DuckDB 对账约 3.22 秒，单连接完成。正式 Gold 文件只在 staging 回读校验通过后原子替换。

#### P9：正式事件验收（已完成）

P9 使用独立的有界事件工具执行，不运行 Gold daily job，不启用 normal/repair sensor，不补 611 个历史 check：

- dry-run：`/private/tmp/dc_daily_technical_p8_events_dry_run_20260715.json`，计划 611 个 materialization、最近 20 日 20 个 partitioned core check，共 631 个 event；
- 小样本：`/private/tmp/dc_daily_technical_p8_events_sample_20260715.json`，写入起始/中间/最新 3 个 materialization 和最新日 1 个 check；
- 正式 apply：`/private/tmp/dc_daily_technical_p8_events_apply_20260715.json`，新增 608 个 materialization、19 个 check，连同样本结果形成 611/611 materialization 和最近 20/20 check；
- 最终对账：`/private/tmp/dc_daily_technical_p8_events_final_20260715_180652.json`。

最终结果：materialization 分区 611、记录 611；最近 20 个 check 全部成功且带正确 partition；每个 check 的 target materialization 与对应最新 materialization 一致；readiness 失败 0，异常 check partition 0。事件写入没有触碰数据湖文件，也没有运行 job/sensor。

### P10：启用与观察

- 只读 definitions/partition/readiness 预检；
- 手动启用 normal sensor，再观察至少 3 个交易日；
- repair sensor 单独观察；
- 回写实际耗时、请求、cursor 和 UI 状态。

2026-07-15 已完成 P10A：`gold_dc_daily_technical_update_job_sensor` 已注册并启用为 `RUNNING`，`gold_dc_daily_technical_repair_job_sensor` 未启用。启用后的只读 preview 正常返回 `Silver dc_daily 尚未覆盖 Gold 技术指标目标日期`，没有提交 run；正式 instance active run 数为 0。本机当前未运行 daemon/`dg dev`，因此尚未开始交易日 tick 观察。

## 11. 验收标准与风险

进入正式开发前必须满足：

- BOLL `ddof=0` 有可复现 fixture，并通过主流实现对照；
- 611 日输入的完整 writer 性能在门禁内；
- 每个 `(ts_code, category, trade_date)` 只输出一行；
- MA/BOLL warmup 为 NULL，未被序列化或前端改成 0；
- 正常 sensor 不读 event history；
- repair 没有合法 upstream batch 时不自动猜测、不自动运行；
- check 只有一个核心事件，公式测试与运行时结构检查分离；
- 文件失败不会覆盖已有数据；
- 未来所有新增配置都有配置审计和测试门禁。

主要风险：

1. BOLL 的公开公式没有明确分母；本方案已按主流实现冻结 `ddof=0`。如果未来可靠同花顺高精度样本冲突，必须先停止 Bootstrap 并重新确认，不得悄悄改数值。
2. MACD/KDJ 采用全历史 set-based SQL，但实现若退回 Python 递推，会破坏性能门禁；必须通过性能测试保护。
3. P7 repair sensor 虽已定义，但默认 `STOPPED`；正式启用前仍必须完成 Silver/Gold lake 对账、RunRequest 只读验收和独立性能观察，不能用 sensor 替代 P8 的历史事件验收。
4. 输入存在稀疏序列；窗口按有效观测而不是补齐自然日，必须让 API/前端理解 `NULL` 预热语义。

## 12. 参考资料

- 新增数据集模板：`docs/templates/dagster-dataset-onboarding-template.html`
- 数据管道性能规范：`docs/design/dagster-data-pipeline-performance-governance.md`
- 板块数据集方案：`docs/design/dagster-dc-board-data-onboarding-plan.md`
- 板块数据集 LLD：`docs/design/dagster-dc-board-data-onboarding-low-level-design.md`
- 分钟线 QFQ 指标方案：`docs/design/dagster-stk-mins-qfq-macd-kdj-indicators-plan.md`
- 同花顺 BOLL 公式：[BOLL 公式](https://poi.10jqka.com.cn/store/formula/detail/indexid/97412)
- 同花顺公式函数资料：[STD 函数说明](https://www.renrendoc.com/paper/140441942.html)
- 公式函数列表：[STD/STDP 区分](https://help.tdx.com.cn/gspt/docs/markdown/redword/functionlist.html)
- TA-Lib：[函数列表](https://ta-lib.org/functions/)
- `pandas-ta`：[BBANDS 源码](https://tradingstrategy.ai/docs/_modules/pandas_ta/volatility/bbands.html)
