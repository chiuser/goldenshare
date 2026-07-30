# 指数分钟线 `index_mins` Dagster 数据集接入方案

更新时间：2026-07-30
状态：P0 方案/LLD、P1、P2、P3、P4、P5 已完成；P6A/P6B source scope 冻结与只读性能验证已完成；5 个 source-empty 日期组合的 5m Raw fallback 与 10 个 Silver fallback 已完成审计；P7 apply runner 已补齐 source-empty Raw 豁免和 Silver fallback 复用，正式 Raw/Silver Bootstrap 与文件对账仍待执行。fallback 仅用于开发期 Bootstrap/历史修复，正式日常 sensor 仍不调用。
适用范围：`lake_console/orchestrator` 正式 Dagster 数据湖

## 1. 目标与冻结结论

本专项把生产库已经维护的指数分钟线接入 Dagster Lake：

~~~
Prod PostgreSQL raw_tushare.index_mins
        + ops.index_series_active(resource='index_mins')
        -> Raw 五个频率资产
        -> Silver 五个源优先频率资产 + 15m/30m/60m 受控 5m fallback + 90m/120m 两个派生频率资产
~~~

冻结结论：

1. Bootstrap 和日常 Raw 同步都从 Prod DB 只读导出；本专项不把 Tushare 直请求作为第二条隐式路径。
2. Tushare `idx_mins` 文档和 MCP 实测只用于源字段、分页和兼容性核验。未来若增加 Tushare fallback，必须另行设计 source adapter、请求预算和恢复边界。
3. Raw 建五个独立资产：`1min/5min/15min/30min/60min`。
4. Silver 建七个独立资产：`1m/5m/15m/30m/60m` 五个频率资产、`90m` 和 `120m` 两个派生资产。对 `15m/30m/60m`，同日目标频率源数据优先；仅在源端明确返回该日期/频率全局空结果时，才允许用同日 `5min` 受控派生。
5. `15m/30m/60m` fallback 固定使用 `5min`，不级联使用其它派生频率。目标时间使用源端 interval-end label，窗口为 `(target_time - N minutes, target_time]`；每个指数应分别得到 15m=17、30m=9、60m=5 个目标 bar。
6. fallback 的 OHLC 使用首开、末收、最高、最低；`vol/amount` 求和；`exchange` 必须组内唯一；`vwap` 固定写 `NULL`。这是 Silver 的可解释派生事实，不伪造源端目标频率的成交均价。
7. Raw 永远保持 Prod 源事实，不把 5m 合成结果写回 Raw，也不把源端目标频率空结果伪造成 Raw 行。原生源目标频率出现部分数据但不完整或不合法时，必须 fail-closed，禁止静默 fallback。
8. 分区使用专属 `cn_a_index_mins_trade_days`，不复用 `cn_a_index_trade_days`。历史起点按当前生产真实最早日期 `2025-01-02` 冻结；正式 Bootstrap 前必须重新做日期范围 dry-run。
9. `ops.index_series_active` 是本次源端范围合同。每个 Raw run 在只读源会话内读取 active pool，并记录排序代码集合 hash。
10. 当前默认 Dagster Lake 没有可直接使用的 `index_mins` active-pool 本地副本。本专项不假设存在本地快照，也不临时新增 manifest 数据集；active pool 与 Raw 源表同库读取，失败则 fail-closed。
11. Sensor 热路径只做最近 10 个专属 expected dates 的批量 Lake readiness 和一次有界 Prod source probe，不读取 Dagster event history，不拉取明细行，不逐代码请求。
12. 每个 asset 只保留一个合并 blocking core check；请求量、源/写入行数、active pool hash、source mode、分页和耗时写入 materialization metadata，不拆成高基数 check event。

## 2. 依据与审计结果

### 2.1 已读取的规范和模板

本方案编写前已读取：

- 根目录 `AGENTS.md`
- `lake_console/AGENTS.md`
- `lake_console/orchestrator/AGENTS.md`
- `lake_console/orchestrator/CODING_STANDARDS.md`
- `lake_console/docs/design/dagster-data-pipeline-performance-governance.md`
- `lake_console/docs/design/dagster-asset-schema-contract-design.md`
- `docs/templates/lake-dataset-development-template.md`
- `lake_console/docs/templates/dagster-dataset-onboarding-template.html`
- `lake_console/docs/design/dagster-index-global-data-onboarding-plan.md`
- `lake_console/docs/design/dagster-index-global-data-onboarding-low-level-design.md`
- `/Users/congming/github/tushare/docs/tushare-v45/指数专题/0419_股票历史分钟行情.md`

已使用 CodeGraph 审计 `index_mins` 生产同步链路、Prod 导出、active pool、现有股票分钟线 Raw/Silver 资产、分区、资源和定义装配影响面。当前结果确认生产链路与 Dagster 新接入不能直接复用为同一执行入口。

### 2.2 当前代码事实

| 位置 | 当前行为 | 本专项处理 |
|---|---|---|
| `backend/app/services/tushare_index_mins_sync_service.py` | Tushare 代码 × 频率循环，当前约 `530 x 5 = 2,650` 个基础请求/日 | 不搬入 Dagster 日常路径 |
| `backend/app/services/prod_raw_index_mins_export_service.py` | Prod DB 每个频率一次范围查询，流式 batch 读取 | 作为性能和字段口径参考，重新落 Dagster 只读 helper |
| `backend/app/services/index_mins_active_pool_sync_service.py` | 可将 `ops.index_series_active` 写成 legacy manifest | 当前 Dagster Lake 没有该 manifest，不能假设已存在 |
| `orchestrator/defs/assets/stk_mins.py` | 股票分钟线 Prod DB Raw 采用 DuckDB + PostgreSQL read-only attach + 单日分区原子替换 | 复用架构模式，不复制股票业务规则 |
| `orchestrator/defs/partitions.py` | 有宽泛 `cn_a_index_trade_days`，没有指数分钟线专属分区 | 新增 `cn_a_index_mins_trade_days` |
| `orchestrator/defs/catalog/lake_assets.py` | 已有 catalog、schema、governance 模型 | 后续补齐 12 条新资产 entry |

### 2.3 Prod DB 只读审计基线

当前生产 `raw_tushare.index_mins` 审计事实：

| 项目 | 事实 |
|---|---:|
| `ops.index_series_active(resource='index_mins')` | 530 个唯一 `ts_code` |
| Raw 总行数 | 约 63,501,920 |
| Raw 表总大小 | 约 16 GB（表约 7.7 GB，索引约 8.9 GB） |
| 频率 | `1min/5min/15min/30min/60min` 五种 |
| 各频率最早时间 | `2025-01-02 09:30:00` |
| 审计样本最新日期 | `2026-07-27` |
| 2026-07-27 五频行数 | 1min 127,730；5min 25,970；15min 9,010；30min 4,770；60min 2,650 |
| 最新日各频率 code 数 | 均为 530 |
| 主键 | `(ts_code, freq, trade_time)` 唯一 |

最近五个有数据的交易日样本中，五个频率均覆盖 530 个 active code；最新 Raw code set 与 active pool 完全相等。数字是设计基线，不是代码硬编码；正式 Bootstrap 前必须重新审计。

当前 `ops.index_series_active` 的 `first_seen_date`、`last_seen_date`、`last_checked_at` 不是可靠的当天源更新时间指标，审计时可见其值滞后于最新 Raw 日。它只能作为本次同步的代码范围合同，不能用于推断 Prod 何时完成，也不能据此设置固定收盘触发时间；源是否 ready 必须由目标日期/频率的只读聚合 probe 判断。

### 2.4 Tushare 字段事实差异

本地源文档为 `/Users/congming/github/tushare/docs/tushare-v45/指数专题/0419_股票历史分钟行情.md`。文档默认输出列出 8 个字段：`ts_code/trade_time/open/close/high/low/vol/amount`。实际对 `idx_mins` 显式传入：

~~~
ts_code,freq,trade_time,open,close,high,low,vol,amount,exchange,vwap
~~~

MCP 实测返回 11 个字段。因此不能因文档的默认显示没有 `freq/exchange/vwap` 就丢弃它们。Raw 合同以 Prod 真实字段和显式字段实测为准；未来 Tushare fallback 必须显式传完整 fields 并保留 limit/offset。

源接口行为矩阵：

| 验证项 | 口径 | 正式设计结论 |
|---|---|---|
| 不传业务对象 | 文档要求 `ts_code`、`freq` 必填 | 不作为正式请求；失败必须 fail-closed |
| 只传对象过滤 | `ts_code + freq`，不传时间范围 | 只用于 P1 探测全量返回边界，不用于 Bootstrap，避免无界历史拉取 |
| 时间点 | `start_date` 与 `end_date` 组成最小窗口 | 只用于 P1 确认边界/空结果语义 |
| 时间区间 | 单个指数、单个频率、明确 `[start_date, end_date]` | Tushare fallback 的最小请求单元；必须配合显式 `limit/offset` |
| 分页 | `limit` 最大 8,000，`offset` 严格递增 | P1 做真实分页验证；正式 Dagster 不走此路径 |

`ts_code` 和 `freq` 是源接口必填，不对应运营侧输入字段；它们由内部 source adapter 生成。`start_date/end_date`、`limit/offset` 同样由 planner/strategy 生成，不能直接暴露为用户参数。正式方案选择 Prod DB `range_stream`，原因是同一日期/频率可用一次范围 SQL 覆盖有效代码集合，避免 530 个指数乘 5 个频率的请求扇出。

### 2.5 P1 实现与真实只读验证结果

P1 已按本方案完成，当前只落地合同、Prod 只读 SQL、active pool loader 和 source probe，没有新增 Dagster asset/job/sensor，没有写 Lake、Dagster DB、event 或 Prod 数据。

实现文件：

- `orchestrator/defs/run_contracts/index_mins.py`：集中维护五个源频率、五个 Raw 频率、两个派生频率、日期窗口、代码格式、代码集合 hash 和一一映射。
- `orchestrator/defs/prod_db/index_mins.py`：显式字段的 Prod range query、bounded active pool `fetchmany`、五频聚合 source probe、source readiness metadata。
- `orchestrator/defs/run_contracts/asset_column_schemas.py`：新增 Raw/Silver 11 列 schema 合同。
- `tests/test_index_mins_contracts.py`：频率映射、代码/日期合同、hash、schema 测试。
- `tests/test_index_mins_prod_db.py`：SQL、只读连接、bounded fetch、active pool、source probe 和 fail-closed 测试。

本地验证结果：

- P1 专项测试：`13 passed`。
- P1 + 既有 index daily Prod contract + static gates：`105 passed`。
- 新增模块和 schema `py_compile` 通过；仅有既存 Dagster/Pydantic deprecation warnings。

正式 Prod 只读 probe 结果（2026-07-29 执行）：

| 项目 | 结果 |
|---|---:|
| source probe 日期 | `2026-07-27` |
| active pool | 530 个 code |
| 五频覆盖 | 5/5，均覆盖 530 个 code |
| 1min / 5min / 15min / 30min / 60min 行数 | 127,730 / 25,970 / 9,010 / 4,770 / 2,650 |
| 五频重复 key | 0 |
| 时间范围 | 均落在目标日半开区间 |
| 单次 probe 耗时 | 2,229 ms |

这里的“覆盖 530 个 code”来自聚合计数，不能替代代码集合逐项相等校验。P2 Raw writer 必须在实际 fetched rows 上执行 exact code-set 校验，再允许 staging promote；不能把 `COUNT(DISTINCT ts_code)` 当成集合完全一致的证明。

P1 性能边界已经固定：active pool 使用单个只读连接和 `fetchmany(500)`，上限 2,000 个 code；source probe 每个频率一个聚合 SQL，共 5 次，不拉明细、不做逐代码查询。真实样本一次探测耗时 2.229 秒。P2 已验证单频明细 range query、DuckDB staging、回读和原子替换；五频连续执行与 20 日 Bootstrap 总预算留到 P6 统一回归。

### 2.6 P2 Raw writer 实现与验证结果

P2 已完成五频 Raw writer，但仍保持纯 writer 边界，没有新增 active Dagster definition、job、sensor、check，也没有写正式 Lake 或 Dagster event。

实现文件：

- `orchestrator/defs/assets/index_mins.py`：Prod DB attached read-only DuckDB source、单频/单日 writer、source exact code-set/日期/频率/主键/schema 校验、staging 回读和原子替换。
- `orchestrator/defs/paths.py`：`raw_index_mins_path(...)`，固定 `raw/tushare/index_mins/freq=<freq>/trade_date=<date>/part-000.parquet`。
- `orchestrator/defs/prod_db/index_mins.py`：增加 attached Postgres 的显式字段 source SQL 和只读 attach 合同。
- `tests/test_index_mins_raw_writer.py`：临时 Parquet smoke、缺失/额外 code、重复 key、越界行、已有文件复用/拒绝覆盖、staging 失败清理。
- `tests/test_index_mins_prod_db.py`：attached source SQL 的显式字段和只读 attach 测试。

P2 writer 的安全顺序固定为：

~~~text
目标存在性/既有文件合同
  -> read-only Prod attach
  -> 单频范围 SQL
  -> DuckDB source relation
  -> exact active code-set、schema、日期/频率、主键校验
  -> staging Parquet
  -> staging 回读及 source/written 行数对账
  -> 目标不存在二次确认
  -> os.replace 原子 promote
~~~

失败时只清理当前 staging；已有目标文件不覆盖。已有文件只有在同一 active pool、日期、频率、schema、主键和行数合同全部通过时才复用。

验证结果：P1/P2 专项测试 `23 passed`；P2 真实只读 smoke 均写入 `/private/tmp`，目标日为 `2026-07-27`：`5min` source/written 为 25,970 行、`1min` source/written 为 127,730 行，两次均为 530/530 code，重复/缺失/额外/越界均为 0，单频 query 次数为 1，耗时分别约 8.369 秒和 15.948 秒。两次 smoke 均不写正式 Lake、Prod DB、Dagster DB 或 event。

当前仍需在后续性能回归中测量五频连续执行和 20 日 Bootstrap 的总耗时、磁盘增量与临时目录峰值；P2 的单频 smoke 不能替代全量预算验收。

### 2.7 P3 Silver writer 与窗口 fixture 实现结果

P3 已完成，但仍保持纯 writer 边界：没有新增 active Dagster definition、check、job、sensor，也没有写正式 Lake、Dagster DB 或事件。

实现文件：

- `orchestrator/defs/run_contracts/index_mins.py`：集中维护七个 Silver 频率、90m/120m 的源频率映射和固定窗口锚点。
- `orchestrator/defs/paths.py`：新增 `silver_index_mins_path(...)`，固定 `silver/quote/index_mins/freq=<freq>/trade_date=<date>/part-000.parquet`。
- `orchestrator/defs/assets/index_mins_silver.py`：DuckDB set-based 原生 Silver 标准化、90m/120m 派生、窗口完整性诊断、staging 回读和原子替换。
- `tests/test_index_mins_silver_writer.py`：原生字段/vwap、90m、120m、缺窗口、混合 exchange 和无 Dagster definition fixture。

P3 的派生窗口不是按总行数整除推断，而是按集中窗口表匹配源时刻：

- 90m 使用 `30min` 的 `10:00/10:30/11:00`、`11:30/13:30/14:00`、`14:30/15:00` 三个窗口；最后一个窗口要求两根源 bar。
- 120m 使用 `60min` 的 `09:30/10:30`、`11:30/14:00` 两个窗口；未进入窗口的源 bar 不参与聚合。
- 窗口缺 bar 或窗口内 exchange 出现多个值时 fail-closed；不产生目标文件，不覆盖已有文件。
- 原生 Silver 保留源端 vwap；派生 Silver 的 vwap 固定为 NULL。

本地 P3 writer fixture：`7 passed`。测试只使用临时目录和临时 DuckDB，覆盖 staging 原子 promote、派生 OHLC/vol/amount 聚合、锚点、NULL vwap、缺窗口和混合交易所拒绝、错误已有目标不覆盖；未运行 `dg`，未写正式 Lake、Dagster DB 或 event。

临时性能样本使用 530 个指数代码、五个原生频率和两个派生频率。各 writer 的 DuckDB 处理耗时约为：原生 `1/5/15/30/60min` 分别 `11.810/11.211/12.072/15.432/15.245 ms`，派生 `90/120min` 分别 `21.159/20.926 ms`；整轮含 fixture 建文件耗时约 `3,154.819 ms`。该结果只证明 set-based 单日样本没有代码级循环放大，不能替代 P6 的正式湖磁盘、连续五频和 Bootstrap 总预算验收。

### 2.8 源端目标频率为空时的 5m fallback 审计与冻结口径

本节记录 2026-07-29 对 Prod 缺失频率的只读审计，以及本轮新增的 Silver 设计口径。审计不写 Prod、Lake、Dagster DB 或事件。

已确认目标日期/频率的源端空结果为：

| trade_date | source-empty target frequency |
|---|---|
| `2025-07-04` | `30min`, `60min` |
| `2025-07-11` | `15min`, `30min`, `60min` |
| `2025-07-18` | `30min`, `60min` |
| `2025-07-25` | `60min` |
| `2025-08-01` | `30min`, `60min` |

`2026-07-28`、`2026-07-29` 尚未进入本次结论，因为 Prod 尚未更新到这两天。对上述日期，Prod 的 `5min` 行数分别为 `25,872`、`25,872`、`25,872`、`25,970`、`25,970`，对应每个指数均为 49 个 5m bar（530 指数时为 `530 * 49`，528 指数时为 `528 * 49`）。Tushare MCP 对抽样指数的显式字段请求也确认：这些日期的 5m 均返回 49 行，而对应缺失的 15m/30m/60m 返回 0 行。

5m 的时间标签是区间结束标签，Silver fallback 使用固定左开右闭窗口：

~~~text
(target_time - N minutes, target_time]
~~~

因此每个代码的期望输出行数为：15m=17、30m=9、60m=5。源端已有的 15m/30m 样本与 5m 聚合在 OHLC 上一致；`vol/amount` 存在少量舍入/对账差异，不能把合成结果宣称为源端目标频率的逐字段复制。`vwap` 不能用 `amount/vol` 直接计算，fallback 统一写 `NULL`。

冻结规则：

1. Raw 仍只保存 Prod `raw_tushare.index_mins` 的源事实，不生成合成 Raw，不把 fallback 行伪装成 Tushare/Prod 返回。
2. Silver 先判断同日目标频率源文件/源 probe：目标频率全局 `source_row_count=0` 才进入 fallback；目标频率存在任意行但 code 不完整、窗口不完整、字段或主键不合法时，直接 fail-closed，不 fallback。
3. fallback 只覆盖 `15m/30m/60m`，统一从同日 `5min` 派生；`1m/5m` 不派生，`90m/120m` 继续沿用既有 `30m/60m` Silver 派生规则。
4. fallback 必须对 effective code set 逐代码验证 5m 的完整时间集合、无重复 key、日期/频率正确，再由一个 DuckDB set-based SQL 完成聚合；任一代码不完整，目标日期不写入或不替换。
5. `source_mode`、`source_freq`、`source_empty_reason`、`lower_source_row_count`、`derived_row_count` 等信息只进入 materialization metadata/离线报告，不新增高基数 check，不增加 schema 系统列。
6. 未来 Prod 补回同日目标频率后，native source 必须重新取得优先级。替换既有 fallback 文件必须走显式 bounded Silver repair/reconcile 路径，不能依赖普通 writer 的“已有文件直接 skip”语义静默完成。

P3 follow-up 已实现：

- `orchestrator/defs/assets/index_mins_silver_repair.py::repair_silver_index_mins_source_empty(...)` 是开发期/Bootstrap 使用的 bounded fallback writer。它只接受显式 source-empty 频率、effective code set、source revision 和 ASCII reason；不注册 Dagster asset/job/sensor，不读 event history。
- writer 只读同日 5m Raw，做一次 set-based source contract、exact code set、49 个 5m 时间点和 source revision 校验，再生成 15m/30m/60m staging；三个目标 staging 全部回读通过后才替换，替换中途失败会恢复已有目标。
- `validate_silver_index_mins_source_empty_fallback(...)` 和 `batch_silver_index_mins_fallback_lake_readiness(...)` 是只读验收入口，区分目标全缺、目标部分存在、全部 ready、源合同失败和未注册分区；不接入普通 Silver sensor。
- `reconcile_silver_index_mins_native_partition(...)` 是源端原生目标频率后来补回时的显式 bounded reconcile 入口，普通 Silver writer 仍保持已有文件 skip，不会静默覆盖 fallback。
- 这些入口只服务本轮历史缺口清理、开发期 Bootstrap 或 native source reappearance 的一次性修复；缺口关闭后不作为日常自动任务持续运行。日常链路仍按 Raw 目标频率原生数据和现有 Silver job/sensor 运行。

实现测试：`tests/test_index_mins_silver_repair.py`、`tests/test_index_mins_fallback_readiness.py`；覆盖完整 5m 正向生成、部分源 fail-closed、已有目标保护、native reconcile、目标全缺/部分存在/ready 和注册缺口。当前代码不把 fallback 结果写回 Raw，不增加 check event 或持久化状态。

## 3. 范围与非目标

### 3.1 包含

- 五个 Raw asset、五个 Raw core check、一个 Raw job、一个 Raw sensor。
- 五个原生/源优先 Silver asset、两个派生 Silver asset、七个 Silver core check、一个 Silver job、一个 Silver sensor；其中 `15m/30m/60m` 资产包含明确 source-empty 时的 5m fallback。
- source-empty fallback 不直接复用当前普通 Silver asset job：当前 Silver asset 对 `15m/30m/60m` 仍依赖对应 Raw asset，fallback 由独立 bounded Silver repair/bootstrap 入口执行。
- 专属动态分区 `cn_a_index_mins_trade_days` 及日历注册 sensor。
- Prod DB read-only active pool + source range contract。
- DuckDB set-based Raw/Silver writer、staging 回读、原子替换。
- Silver `15m/30m/60m` 的 source-empty 5m fallback：不改 Raw，严格区分 native source、derived fallback 和 partial-source failure。
- Bootstrap dry-run、正式 Bootstrap、文件对账、最近 20 日事件补录方案。
- catalog、data card、definition column schema、governance mapping、sensor tags、cursor 和性能测试。

### 3.2 不包含

- Tushare 日常 fallback。
- Sensor 访问 Tushare、读取完整 Prod 明细或读取 Dagster event history。
- active pool 持久化 manifest、summary/readiness asset、状态表或新数据库表。
- Prod 表直接注册为 Dagster asset。
- 改动 `index_daily`、`index_global`、`stk_mins` 或 `dc_board`。
- Raw 写入 `90min/120min`。
- 将 5m fallback 结果写入 Raw，或把 fallback 结果伪装成 Prod/Tushare 原生目标频率。
- 在目标频率存在部分数据但不完整时静默 fallback；部分源结果必须 fail-closed。
- Python 逐股票/逐行计算、无界分页、无界重试。

## 4. Data Card、Catalog 与治理

| 字段 | 冻结值 |
|---|---|
| `dataset_id` | `index_mins` |
| 中文名 | 指数历史分钟行情 |
| 领域 | `index_topic` / 指数行情 |
| 展示分组 | `index_market_data` / A股指数行情 |
| `date_model` | `partitioned_trade_date`；输入单位是单个交易日，源明细时间字段是 `trade_time` |
| `input_shape` | `range_stream`；不是用户可选的 `ts_code` 扇出 |
| `observed_field` | `trade_time`；用于分区日期、范围和 freshness 对账 |
| `request_strategy_key` | `prod_db_index_mins_range_stream_v1` |
| `supported_commands` | `bootstrap-dry-run`、Dagster 单分区 job |
| Raw source | Prod DB read-only，`raw_tushare.index_mins` |
| Tushare reference | `idx_mins`，仅字段/分页核验 |
| 主业务字段 | `trade_time` |
| 物理分区 | `trade_date` = CAST(trade_time AS DATE)，不进 Raw source schema |
| 历史起点 | `2025-01-02`，Bootstrap 前复核 |
| Raw 频率 | `1min/5min/15min/30min/60min` |
| Silver 频率 | Raw 五频 + `90min/120min` |
| 默认源系统 | `prod_core_db` / read-only |
| 日期完整性 | 使用专属 index mins trade-day 口径 |
| 事件保留 | materialization 全量补；blocking check 最近 20 个交易日 |

资产清单：

~~~
raw_index_mins_1m
raw_index_mins_5m
raw_index_mins_15m
raw_index_mins_30m
raw_index_mins_60m

silver_index_mins_1m
silver_index_mins_5m
silver_index_mins_15m
silver_index_mins_30m
silver_index_mins_60m
silver_index_mins_90m
silver_index_mins_120m
~~~

资产名用 `1m/5m/...` 与现有股票分钟线一致；源字段和路径用 `1min/5min/...`，映射集中维护。

Catalog entry 必须逐资产包含 asset key、dataset id、layer、domain、group、中文名、contract、column schema、path、partition model、blocking checks、write/event policy 和 performance contract。治理固定为：

| 资产族 | category | readiness | phase |
|---|---|---:|---|
| Raw 五频 | `MOVE_TO_SENSOR_LAKE_READINESS` | 是 | `INDEX_MINS_RAW` |
| Silver 原生五频 | `MOVE_TO_SENSOR_LAKE_READINESS` | 是 | `INDEX_MINS_SILVER` |
| Silver 90m/120m | `MOVE_TO_SENSOR_LAKE_READINESS` | 是 | `INDEX_MINS_SILVER_DERIVED` |

## 5. 字段与有效代码合同

Raw 11 列：

| 字段 | Lake 类型 | 可空 | 说明 |
|---|---|---:|---|
| `ts_code` | `VARCHAR` | 否 | 指数代码 |
| `freq` | `VARCHAR` | 否 | 源分钟频率 |
| `trade_time` | `TIMESTAMP` | 否 | 分钟 bar 时间 |
| `open/close/high/low` | `DOUBLE` | 是 | OHLC |
| `vol/amount` | `DOUBLE` | 是 | 成交量/金额 |
| `exchange` | `VARCHAR` | 是 | 交易所 |
| `vwap` | `DOUBLE` | 是 | 源端 VWAP |

Raw PK 为 `(ts_code, freq, trade_time)`；`trade_date` 只用于目录和日期校验。

Silver 原生保留 Raw 11 列并标准化；`15m/30m/60m` 在目标频率源端全局为空时，可从同日 5m 以固定窗口派生；90m/120m 保留同一列集合，`freq` 固定为派生值。所有派生路径的 OHLC 使用窗口聚合，vol/amount 求和，exchange 要求组内唯一，vwap 固定 NULL。native/fallback/derived 的来源模式不新增到业务 schema，写入 materialization metadata。

有效集合：

~~~
active_pool
  ∩ 当前 trade_date 的源范围
~~~

active pool 是本次 Raw 源端范围合同；空、重复、空 code、查询失败均 fail-closed。P4 的 Raw asset 依赖 `silver_index_basic` 作为 Dagster 质量前置，但当前 writer 不用它缩小 active code set，也不在 Prod 查询中隐式做生命周期 join。materialization 只记录 count/hash/有限样本。

## 6. 读取策略、路径与分区

日常单位为一个 `trade_date`；一个 Raw job 选择五频资产及 checks，每个频率执行一次按日范围 SQL，再写对应 staging。每日 source query 合计 5 次，避免 2,650 次 Tushare code fan-out。

Bootstrap 最多 20 个交易日/批，每批每频率一次范围 query，流式分组到日期 staging，不加载全历史。P6A/P6B 冻结范围截至 Prod 最新 `2026-07-27` 为 378 个日期、Raw 1,890 文件、Silver 2,646 文件；正式写入前仍必须以通过的 dry-run 报告为准。

路径：

~~~
raw/tushare/index_mins/freq=1min/trade_date=YYYY-MM-DD/part-000.parquet
...
raw/tushare/index_mins/freq=60min/trade_date=YYYY-MM-DD/part-000.parquet
silver/index_mins/freq=1min/trade_date=YYYY-MM-DD/part-000.parquet
...
silver/index_mins/freq=120min/trade_date=YYYY-MM-DD/part-000.parquet
~~~

路径中的 `tushare` 是源数据域命名；Dagster source_system 仍记录 `prod_core_db`。

专属动态分区：

~~~
cn_a_index_mins_trade_days = dg.DynamicPartitionsDefinition(
    name="cn_a_index_mins_trade_days",
)
~~~

分区只表示日期可处理，不表示源 ready。注册 sensor 从 `silver_trade_calendar` 的 SSE open dates、历史起点起补齐分区，不复用 `cn_a_index_trade_days`，不以固定几点钟判断 Prod 成功。

## 7. 触发与检查

Raw sensor `index_mins_raw_update_job_sensor` 默认 STOPPED：

1. 最近 10 个已注册 expected dates 批量读取本地 Raw readiness。
2. 对最早缺失目标执行一次有界 source probe：active pool + 五个聚合 coverage 查询。
3. source ready 且目标缺失时提交一个五资产 Raw run。
4. 文件存在但 core check 失败时 skip，不覆盖。
5. source not ready 时 skip，等待下一 tick，不使用固定收盘时间。

Silver sensor `index_mins_silver_update_job_sensor` 默认 STOPPED：

- 最近 10 日期批量读取 Raw/Silver readiness。
- 普通日常路径要求五个 Raw 频率全部 ready；source-empty fallback 不通过普通 sensor 绕过 Raw 依赖。
- 选择最早 Silver 缺口。
- 目标错误不覆盖。
- 90m/120m 检查同日 30m/60m 窗口。
- 每 tick 最多一个 run request。

Silver `15m/30m/60m` 的 source-empty fallback 选择顺序固定为：

~~~text
同日目标频率源数据存在且通过 source contract -> native Silver
同日目标频率 source_row_count == 0 且 5m 完整 -> 5m derived fallback
目标频率部分存在但不完整/不合法 -> fail-closed
~~~

fallback 不是普通 sensor 热路径里的计算任务，也不由普通 `silver_index_mins_update_job` 自动绕过 Raw 依赖。独立 bounded repair/bootstrap 入口先接收经过源端审计的“目标频率全局为空”结论，再在 Silver writer 内完成 5m 完整性验证、固定窗口聚合和 staging promote。这样正常 sensor 不增加 Prod 访问、明细扫描或新的自动触发分支。

fallback run 的 writer 约束：

- 只使用同日 `5min` Silver/Raw 合同，窗口按 interval-end label 的 `(target_time-N, target_time]` 计算。
- 每个 effective code 都必须具备完整 5m 时间集合；缺任意 code、重复 key、日期/频率错位或 exchange 混合，整日不写目标。
- 15m/30m/60m 的期望输出分别为每 code 17/9/5 行；OHLC 使用首开、末收、最高、最低，vol/amount 求和，vwap 固定 NULL。
- fallback 只生成 Silver 文件；目标源模式和 lower-source 统计写 materialization metadata，不新增 check event。
- fallback repair 的输入必须是显式的、可审计的 source-empty 日期/频率范围；不能只用“目标 Raw 文件不存在”推断源为空。
- Prod 后续补回 native 目标频率时，必须由显式 bounded repair/reconcile 重新生成 native Silver，普通 writer 不得覆盖已有 fallback 文件。

总共 12 个合并 blocking check：

~~~
raw_index_mins_{1m,5m,15m,30m,60m}_core_check
silver_index_mins_{1m,5m,15m,30m,60m,90m,120m}_core_check
~~~

每个 check 只检查当前 Lake 文件的 file/schema/freq/date/PK/identity/value 语义；派生额外检查窗口完整、anchor 和 vwap NULL。Check 不访问 Prod、不扫 event history、不拆字段级高基数 event。source rows、written rows、active hash、query/page/elapsed 进入 materialization metadata。

P4 已完成，实际定义边界为：

- `assets/index_mins.py` 和 `assets/index_mins_silver.py` 继续保持纯 writer，不包含 Dagster decorator。
- `assets/index_mins_raw.py` 提供五个 Prod-backed Raw asset；`assets/index_mins_silver_defs.py` 提供五个原生和两个派生 Silver asset。
- `checks/index_mins_checks.py` 提供 12 个显式绑定 `cn_a_index_mins_trade_days` 的 blocking check。
- `jobs/index_mins.py` 提供 Raw/Silver 两个单分区 job，只做 asset 与 check selection。
- `catalog/lake_assets.py` 与治理矩阵已登记 12 个 asset/check 对；P5 使用独立的 batch lake readiness helper，不复用 shared `AssetReadinessSpec` 注册表，因此治理规则的 `participates_in_sensor_readiness` 保持 false，避免同一语义被两套 readiness 机制重复声明。

P4 只完成定义和本地/临时湖验证，不启用 sensor、不执行正式 job、不写正式 Lake 或 Dagster event。

### P5 实现映射与验收

P5 已完成，仍未启用 sensor、未执行正式 job、未写正式 Lake、Dagster DB 或 event：

- `asset_guards/index_mins_lake_readiness.py` 提供 Raw/Silver 两个 batch readiness。输入由 sensor 复用同一个 DuckDB connection，窗口最多 10 个 expected trade dates；Raw 最多扫描 50 个频率文件，Silver 在目标和源均存在时最多扫描 140 个文件，不读取 Dagster event history。
- `sensors/index_mins_partition_sensor.py` 只从 `silver_trade_calendar` 注册 `cn_a_index_mins_trade_days`，使用 `2025-01-02` 起点，支持停机 catch-up，不探测 Prod 明细。
- `sensors/index_mins_sensor.py` 提供 Raw/Silver 两个默认 `STOPPED` sensor。Raw 只有在首个 lake 缺口确认后才读取 Prod active pool 和五个聚合 source probe；Silver 先确认 Raw frontier，不访问 Prod。
- 两个更新 sensor 每 tick 最多提交一个单分区 RunRequest，使用统一 run key、tags、`build_sensor_cursor` 和 ASCII `reason_code`；cursor 测试小于 8 KB，sensor 测试确认不调用 `get_event_records`。
- 现有 12 个 blocking check 仍只负责当前分区文件核心质量；sensor 热路径由 P5 batch readiness 负责连续性选择，不新增高基数 check。

P5 本地验证通过：readiness、sensor、definition、check、治理和静态门禁全量回归为 141 passed、84 subtests passed；未启动 `dg`，未执行正式 Lake、Dagster DB 或 event 写入。

## 8. 性能、Bootstrap 与事件

性能门禁：

| 项目 | 门禁 |
|---|---|
| Raw source query | 每频率 1 次，日常 5 次 |
| source probe | 日常单日 1 只读连接、5 聚合 query；P6 全历史 dry-run 使用 1 次全频聚合，不读明细 |
| readiness | 最近 10 日期 |
| Dagster event history | 0 次 |
| RunRequest | 每 tick 最多 1 个 |
| Python | 禁止逐股票/逐行计算 |
| Silver source-empty fallback | 仅 `15m/30m/60m`；每个目标日一次 DuckDB set-based 5m 聚合；不进入 sensor 明细扫描 |
| fallback 完整性 | 先验证 effective code set 的 5m 时间集合，再 promote；任何缺失/重复/错位整日 fail-closed |
| fallback 额外请求 | 0 次；只读已有 5m Raw/Silver，不调用 Tushare、不访问 Prod 明细 |
| Bootstrap | 最多 20 日/批，串行流式；P6 全历史 source audit 受 300 秒硬预算 |
| 写入 | staging 回读后原子替换 |

不可接受：代码×频率 Tushare fan-out、sensor 逐日 event 深扫、文件存在冒充 ready、row count 冒充派生完整性、active pool 失败后继续写、未校验覆盖目标。

Bootstrap dry-run 为独立 CLI，只生成日期计划、active hash、源 coverage、目标冲突、行数/文件数/磁盘/耗时报告。P6 CLI 只有 `dry-run`，没有 apply 写入路径。Raw 全量对账通过后才生成 Silver。

P6 实现与真实验收结果：

- 日期 scope 已冻结为 `2025-01-02` 至 Prod 当前最新 `2026-07-27`，共 `378` 个 SSE open dates；当前 active pool 为 `530` 个指数，代码集合 hash 为 `4360dbf7b0ea86d2465ba43b8e282d8c07a429dd23b4aacb2d219775210b297e`。Prod 尚未更新 `2026-07-28` 及之后日期，本轮不把它们判断为 source-empty。
- 历史 code scope 不再把当前 530 个代码强行套到所有历史日期。以 `silver_index_basic.list_date/exp_date` 与当前 active pool 的交集作为历史有效范围：`2025-01-02..2025-01-17` 为 526 个、`2025-01-20..2025-07-18` 为 528 个、`2025-07-21..2026-07-27` 为 530 个；4 个后上市指数为 `000680.SH`、`000681.SH`、`399267.SZ`、`399268.SZ`。实际非空 `freq/date` 聚合结果与该历史范围代码数无不解释偏差。
- P6B coverage-only probe 使用一个只读连接和一条 `freq + trade_date` 聚合 SQL，只统计行数、返回代码数、时间范围，不做全历史 `COUNT(DISTINCT (ts_code, trade_time))`。正式范围实际耗时 `88,383 ms`，完整报告耗时 `88,635 ms`，低于 `300,000 ms` 硬预算；查询只把 `1,880` 个聚合结果读入 Python，不读取明细行。
- P6B 目标冲突审计使用一个 DuckDB connection；正式 Lake Raw `1,890` 个目标、Silver `2,646` 个目标均缺失，未发现错误存量文件。磁盘剩余约 `2.55 TB`，保守估算本批约 `71.9 GB`，磁盘门禁通过。
- 源覆盖结果为：`1min/5min` 全部 `378` 个日期有数据；`15min` 缺 `2025-07-11`；`30min` 缺 `2025-07-04/07-11/07-18/08-01`；`60min` 缺 `2025-07-04/07-11/07-18/07-25/08-01`。这些日期进入已实现的 5m fallback 开发期入口，不把空源伪造成 Raw 原生数据。

结论：P6A/P6B 的 source scope 和 coverage 性能门禁已通过；原 dry-run 的唯一阻断项是上述 5 个 source-empty 日期组合，不是查询性能或历史代码范围误判。fallback 已按既定入口完成并通过专项审计；P7 apply runner 不再把这些原生空频率当成可写的 Raw 缺口，而是显式豁免 Raw、复用已验收的 Silver fallback。禁止用提高 timeout、全量主键 distinct 或把当前 active pool 硬套历史的方式绕过门禁。

P8 单独处理事件：materialization 全量补；blocking check 只补最近 20 日；每条 event 带正确 partition。

## 9. 请求策略、数据量、命令与前端

### 9.1 输入、输出和类型合同

本数据集的正式源是 Prod DB，不把运营用户输入直接透传到源接口。每个 Raw 日常 run 的输入由 partition planner 生成：

| 输入 | 来源 | 语义 |
|---|---|---|
| `trade_date` | `cn_a_index_mins_trade_days` | 单日 Dagster 分区；不由用户任意输入 |
| `source_freq` | 集中 frequency mapping | 五个 Raw asset 各自固定一个值 |
| `start_ts/end_ts` | `trade_date` 派生 | `[trade_date 00:00, next_date 00:00)`，不允许跨日 |
| `effective_codes` | Prod active pool 原样标准化后的代码集合 | 运行时事实，不写入 cursor |
| `source_columns` | 固定 allowlist | 禁止 `SELECT *` |

Prod 查询的输出固定为 11 列：`ts_code`、`freq`、`trade_time`、`open`、`close`、`high`、`low`、`vol`、`amount`、`exchange`、`vwap`。`trade_time` 为 `TIMESTAMP`，数值列统一为 `DOUBLE`，代码/频率/交易所为 `VARCHAR`；目标 Parquet schema 不因某天的空值或源端列顺序变化而漂移。

Tushare `idx_mins` 仅用于 P1 的真实字段/分页验证，不进入正式请求策略。验证请求必须显式传入上述业务字段和 `limit/offset`，并记录默认字段、显式字段和业务补充字段的差异；如果未来增加 fallback，必须新增 source adapter 和独立方案评审。

### 9.2 执行模式与请求预算

| 场景 | 执行模式 | 连接/请求数量 | 内存与重跑边界 |
|---|---|---:|---|
| Raw 日常 | `range_stream` | 1 个只读 Prod 连接，5 个频率范围查询 | 单日 staging；失败只重跑该日 |
| Raw Bootstrap | `range_stream` + `batch_window` | 每批最多 20 日、每频率 1 次范围查询，即最多 5 次 | server-side cursor/fetchmany；不缓存全历史 |
| Silver 原生 | `derived_rebuild` | 每日读取 5 个同日 Raw 文件 | 单日原子替换 |
| Silver 15/30/60 fallback | `derived_fallback_from_5min` | 仅目标频率 source_row_count=0 时读取同日 5m；一次 DuckDB set-based 聚合 | 单日独立 staging；5m 完整性失败不写目标 |
| Silver 90m/120m | `derived_rebuild` | 只读同日 30m/60m Silver 文件 | 窗口完整才写目标 |
| Tushare P1 验证 | bounded `page_loop` | 只做最小真实样本，显式上限 | 不作为正式日常链路 |

Prod 范围 SQL 不需要 `limit/offset` 分页；流式读取由 named cursor 的 `fetchmany` 约束。若源查询量、耗时、内存或磁盘预算超限，整批 fail-closed，不退化为 530 代码循环。每个日期的请求数、行数、查询耗时、写入耗时和峰值内存必须进入报告。

### 9.3 数据量与文件数

P6 实测基线为 530 个指数、五频合计约 170,130 行/最新交易日，原始表约 63,501,920 行、约 16 GB（表约 7.7 GB，索引约 8.9 GB）。以上是容量与性能审计事实，不是写死的产量合同；正式 Bootstrap 若重新进入，仍必须以当次 dry-run 为准。

截至 2026-07-30、以 Prod 最新 `2026-07-27` 为结束日期的真实日期计划为 378 个交易日：逻辑 Raw 网格为 `378 x 5 = 1,890`，其中 10 个已审计 source-empty 原生频率不生成 Raw 文件，因此正式 Raw 对账的有效文件数为 `1,880`；Silver 为 `378 x 7 = 2,646` 个文件，合计预期物理文件为 4,526 个。历史 Raw code scope 不是全量 `silver_index_basic`，而是冻结的 530 个 active pool 与 index basic 生命周期交集；正式日历还包含未来日期，但 Bootstrap 默认排除未来日期；历史起点、结束日期和文件数仍以冻结 date-plan 与 source report 为准。

该规模低于当前小文件 warning 门槛，但每日继续增长。第一版不做 compact；如果未来超过 10,000 文件或单日文件过小，必须另开 compact 方案，不能在 writer 中偷偷合并历史文件。

### 9.4 命令与操作提示

新增数据集不增加前端自定义写入入口。Bootstrap 采用独立、显式、默认只读的 CLI：

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator

# 只读生成日期、源覆盖、目标冲突和预算报告
PYTHONPATH=src uv run --project . python -m orchestrator.defs.bootstrap.index_mins_bootstrap_cli dry-run \
  --lake-root /Volumes/datasource/data_lake \
  --output /private/tmp/index_mins_bootstrap_dry_run_<timestamp>.json

# P6 不提供正式写入命令；P7 必须另行设计并审批
```

`dry-run` 不写 Lake、Dagster DB、dynamic partitions 或 event；当前 CLI 没有 `apply` 路径。正式日常通过后续单分区 job/sensor 运行，不提供绕过 partition、active pool 或 core check 的命令。所有命令示例必须用真实 CLI help 和测试对账，不能让文档命令与 parser 漂移。

### 9.5 前端展示

- 列表页以一个逻辑数据集卡片展示 `index_mins`，显示中文名“指数历史分钟行情”、source system、Raw/Silver 层、五个 Raw/七个 Silver 频率、历史起点、最近 ready 日期、最近更新时间、文件数和数据量。
- 详情页按 `layer -> freq` 展示资产，不把 12 个内部 asset 误显示为 12 个互不相关的数据集；显示 schema、分区范围、核心 check 状态、source/written/output 行数、active pool count/hash 摘要和风险提示。
- Assets 页面继续使用 Dagster asset/check 状态；本专项不新增 UI 自定义状态查询，也不把 active code 完整列表写入页面或 cursor。
- 命令示例页从 catalog 的 `supported_commands`/操作提示生成，前端不得硬编码命令、源字段或路径。

## 10. 里程碑、验收与风险

| 阶段 | 交付 |
|---|---|
| P0 | 方案、LLD、事实对账（当前） |
| P1 | 字段/频率/Prod SQL/source probe contract（已完成；本地 105 tests 通过，Prod 只读 probe 通过） |
| P2 | Raw writer、staging、原子替换、临时测试（已完成；P1/P2 专项 23 tests 通过，单频 Prod 只读 smoke 通过） |
| P3 | Silver 原生/90m/120m writer 与 fixture（已完成；7 tests passed） |
| P3 follow-up | `15m/30m/60m` source-empty 5m fallback writer、只读 readiness、开发期 repair 和 native reconcile 已完成；不进入普通 sensor 日常链路 |
| P4 | asset/check/catalog/schema/governance/job（已完成） |
| P5 | 专属分区、普通 readiness、Raw/Silver sensor，默认 STOPPED（已完成；fallback readiness 为独立维护入口，不接入普通 sensor） |
| P6A/P6B | source scope 冻结、coverage-only dry-run 与性能回归（已完成；全历史 coverage 88.4s 通过，source-empty 日期仍阻断 P7） |
| P7 | 正式 Raw/Silver Bootstrap 与文件对账，单独批准 |
| P8 | materialization 全量补、最近 20 日 check 补，单独批准 |
| P9 | 手动启用 sensor，观察连续 3 个交易日 |

验收必须覆盖：source/written/normalized/output 行数解释、目标 schema/date/PK、staging 清零、event partition、最近 20 日 ready、连续 3 日无超时。

当前状态为 P7 正式写入前置：P6A/P6B 工具、scope、coverage-only 查询和性能回归已完成；P3 follow-up 的 fallback writer/readiness/repair 已完成本地验证，5 个 source-empty 日期组合已完成正式 fallback 文件和专项对账。apply runner 已在本地测试中验证：不写空源 Raw、复用 10 个 Silver fallback、其余 Raw/Silver 按批串行生成，缺 fallback 文件会在 writer 前停止。fallback 不会改变普通 Silver sensor 的 Raw 依赖，也不自动触发长期 repair。P7 正式 Bootstrap 仍需单独批准；P8 才处理事件补录。

风险处理：

- active pool 查询失败：本次 fail-closed。
- active pool 漂移：记录 hash/差异，停止当前范围。
- 源缺失：source probe not ready，等待。
- 派生窗口不完整：不写派生目标。
- schema 漂移：staging 校验停止，旧文件不动。
- sensor 过慢：停用并重做 batch readiness，不增大 RPC timeout。

回滚只清理当前 run 临时 staging；不删除正式 Parquet、Dagster event 或 Prod 数据。

## 11. 开发门禁与模板 Checklist

编码前必须逐项勾选：

- [x] Data Card、catalog、partition model、中文名、governance mapping 已登记。
- [ ] `date_model`、`input_shape`、`observed_field` 三层时间语义已分别核对。
- [ ] 源文档、显式字段请求和 MCP 真实结果已对账；字段差异已记录。
- [ ] 配置项审计和 source contract 测试已完成。
- [x] 五 Raw/七 Silver asset names 与单分区 check 名称已锁定。
- [x] P4/P5 定义、治理、核心 check、readiness 和 sensor 回归已通过：141 passed、84 subtests passed；正式 Lake、Dagster DB、event 和 sensor 均未执行。
- [ ] active pool 空/重复/非法/漂移/查询失败负例已覆盖。
- [x] 原生 vwap 保留、派生 vwap NULL fixture 已覆盖。
- [x] `15m/30m/60m` source-empty 5m fallback 的 source precedence、完整性、`vwap=NULL`、partial-source fail-closed 和 native reappearance repair fixture 已覆盖。
- [x] 最近 10 日期 readiness 性能测试已完成，event history 调用为 0；Raw/Silver readiness 与 sensor 测试通过。
- [x] Bootstrap 请求量、连接数、分页、磁盘、内存和单批耗时预算已测量；P6B coverage-only 全历史 source probe 在 300 秒内完成，source-empty 日期仍 fail-closed。
- [x] 命令示例已经过真实 parser/help 对账；CLI 只有 dry-run，不写入。
- [ ] 前端分组、数据集卡片、详情字段和命令提示已对齐 catalog，不由页面硬编码。
- [x] M3-M6 既有测试和静态门禁回归已通过；P5 新增 readiness/sensor 测试通过。
- [x] P0 文档与代码事实已再次对账；未解释的历史 source scope 冲突已明确为 P7 前置阻断。

任何源字段、active pool、日期起点、窗口规则或性能预算冲突，必须停止并更新方案，不得靠兼容补丁绕过。
