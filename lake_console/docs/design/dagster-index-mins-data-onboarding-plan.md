# 指数分钟线 `index_mins` Dagster 数据集接入方案

更新时间：2026-07-29
状态：P0 方案/LLD、P1、P2、P3、P4 已完成；尚未进入 P5
适用范围：`lake_console/orchestrator` 正式 Dagster 数据湖

## 1. 目标与冻结结论

本专项把生产库已经维护的指数分钟线接入 Dagster Lake：

~~~
Prod PostgreSQL raw_tushare.index_mins
        + ops.index_series_active(resource='index_mins')
        -> Raw 五个频率资产
        -> Silver 五个原生频率 + 90m/120m 两个派生频率资产
~~~

冻结结论：

1. Bootstrap 和日常 Raw 同步都从 Prod DB 只读导出；本专项不把 Tushare 直请求作为第二条隐式路径。
2. Tushare `idx_mins` 文档和 MCP 实测只用于源字段、分页和兼容性核验。未来若增加 Tushare fallback，必须另行设计 source adapter、请求预算和恢复边界。
3. Raw 建五个独立资产：`1min/5min/15min/30min/60min`。
4. Silver 建七个独立资产：五个原生频率，以及从 `30min` 派生的 `90min`、从 `60min` 派生的 `120min`。
5. 原生 Silver 保留源端 `vwap`；90m/120m 没有已确认的合法 VWAP 聚合公式，`vwap` 固定写 `NULL`，不伪造加权价格。
6. 分区使用专属 `cn_a_index_mins_trade_days`，不复用 `cn_a_index_trade_days`。历史起点按当前生产真实最早日期 `2025-01-02` 冻结；正式 Bootstrap 前必须重新做日期范围 dry-run。
7. `ops.index_series_active` 是本次源端范围合同。每个 Raw run 在只读源会话内读取 active pool，并记录排序代码集合 hash。
8. 当前默认 Dagster Lake 没有可直接使用的 `index_mins` active-pool 本地副本。本专项不假设存在本地快照，也不临时新增 manifest 数据集；active pool 与 Raw 源表同库读取，失败则 fail-closed。
9. Sensor 热路径只做最近 10 个专属 expected dates 的批量 Lake readiness 和一次有界 Prod source probe，不读取 Dagster event history，不拉取明细行，不逐代码请求。
10. 每个 asset 只保留一个合并 blocking core check；请求量、源/写入行数、active pool hash、分页和耗时写入 materialization metadata，不拆成高基数 check event。

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
| Raw 总行数 | 约 64,176,112 |
| Raw 表总大小 | 约 17.5 GB |
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

## 3. 范围与非目标

### 3.1 包含

- 五个 Raw asset、五个 Raw core check、一个 Raw job、一个 Raw sensor。
- 五个原生 Silver asset、两个派生 Silver asset、七个 Silver core check、一个 Silver job、一个 Silver sensor。
- 专属动态分区 `cn_a_index_mins_trade_days` 及日历注册 sensor。
- Prod DB read-only active pool + source range contract。
- DuckDB set-based Raw/Silver writer、staging 回读、原子替换。
- Bootstrap dry-run、正式 Bootstrap、文件对账、最近 20 日事件补录方案。
- catalog、data card、definition column schema、governance mapping、sensor tags、cursor 和性能测试。

### 3.2 不包含

- Tushare 日常 fallback。
- Sensor 访问 Tushare、读取完整 Prod 明细或读取 Dagster event history。
- active pool 持久化 manifest、summary/readiness asset、状态表或新数据库表。
- Prod 表直接注册为 Dagster asset。
- 改动 `index_daily`、`index_global`、`stk_mins` 或 `dc_board`。
- Raw 写入 `90min/120min`。
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
| `supported_commands` | `bootstrap-dry-run`、`bootstrap-apply`、Dagster 单分区 job |
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

Silver 原生保留 Raw 11 列并标准化；90m/120m 保留同一列集合，`freq` 固定为派生值，OHLC 使用窗口聚合，vol/amount 求和，exchange 要求组内唯一，vwap 固定 NULL。

有效集合：

~~~
active_pool
  ∩ 当前 trade_date 的源范围
~~~

active pool 是本次 Raw 源端范围合同；空、重复、空 code、查询失败均 fail-closed。P4 的 Raw asset 依赖 `silver_index_basic` 作为 Dagster 质量前置，但当前 writer 不用它缩小 active code set，也不在 Prod 查询中隐式做生命周期 join。materialization 只记录 count/hash/有限样本。

## 6. 读取策略、路径与分区

日常单位为一个 `trade_date`；一个 Raw job 选择五频资产及 checks，每个频率执行一次按日范围 SQL，再写对应 staging。每日 source query 合计 5 次，避免 2,650 次 Tushare code fan-out。

Bootstrap 最多 20 个交易日/批，每批每频率一次范围 query，流式分组到日期 staging，不加载全历史。当前基线约 378 日、Raw 1,890 文件、Silver 2,646 文件，正式前重算。

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
- Raw 五频未全部 ready 时阻断。
- 选择最早 Silver 缺口。
- 目标错误不覆盖。
- 90m/120m 检查同日 30m/60m 窗口。
- 每 tick 最多一个 run request。

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
- `catalog/lake_assets.py` 与治理矩阵已登记 12 个 asset/check 对；P5 sensor 尚未接入，因此治理规则的 `participates_in_sensor_readiness` 暂为 false。

P4 只完成定义和本地/临时湖验证，不启用 sensor、不执行正式 job、不写正式 Lake 或 Dagster event。

## 8. 性能、Bootstrap 与事件

性能门禁：

| 项目 | 门禁 |
|---|---|
| Raw source query | 每频率 1 次，日常 5 次 |
| source probe | 1 只读连接、5 聚合 query，不读明细 |
| readiness | 最近 10 日期 |
| Dagster event history | 0 次 |
| RunRequest | 每 tick 最多 1 个 |
| Python | 禁止逐股票/逐行计算 |
| Bootstrap | 最多 20 日/批，串行流式 |
| 写入 | staging 回读后原子替换 |

不可接受：代码×频率 Tushare fan-out、sensor 逐日 event 深扫、文件存在冒充 ready、row count 冒充派生完整性、active pool 失败后继续写、未校验覆盖目标。

Bootstrap dry-run 为独立 CLI，只生成日期计划、active hash、源 coverage、目标冲突、行数/文件数/磁盘/耗时报告。正式 apply 另设显式确认参数。Raw 全量对账通过后才生成 Silver。

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
| Silver 90m/120m | `derived_rebuild` | 只读同日 30m/60m Silver 文件 | 窗口完整才写目标 |
| Tushare P1 验证 | bounded `page_loop` | 只做最小真实样本，显式上限 | 不作为正式日常链路 |

Prod 范围 SQL 不需要 `limit/offset` 分页；流式读取由 named cursor 的 `fetchmany` 约束。若源查询量、耗时、内存或磁盘预算超限，整批 fail-closed，不退化为 530 代码循环。每个日期的请求数、行数、查询耗时、写入耗时和峰值内存必须进入报告。

### 9.3 数据量与文件数

当前只读基线为 530 个指数、五频合计约 170,130 行/最新交易日，原始表约 64,176,112 行、约 17.5 GB。以上是规划基线，不是写死的产量合同；正式 Bootstrap 前必须重新取样。

按照当前日期范围约 378 个交易日估算：Raw 为 `378 x 5 = 1,890` 个文件，Silver 为 `378 x 7 = 2,646` 个文件，合计约 4,536 个分区文件。单文件大小、压缩率、Silver 派生行数在 P6 以真实样本测量；不能用 row count 冒充完整性，也不能在未测量时承诺磁盘容量。

该规模低于当前小文件 warning 门槛，但每日继续增长。第一版不做 compact；如果未来超过 10,000 文件或单日文件过小，必须另开 compact 方案，不能在 writer 中偷偷合并历史文件。

### 9.4 命令与操作提示

新增数据集不增加前端自定义写入入口。Bootstrap 采用独立、显式、默认只读的 CLI：

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator

# 只读生成日期、源覆盖、目标冲突和预算报告
PYTHONPATH=src uv run --project . python -m orchestrator.defs.bootstrap.index_mins_bootstrap_cli dry-run \
  --lake-root /Volumes/datasource/data_lake \
  --output /private/tmp/index_mins_bootstrap_dry_run_<timestamp>.json

# 正式写入必须显式确认；P7 另行审批后才能执行
PYTHONPATH=src uv run --project . python -m orchestrator.defs.bootstrap.index_mins_bootstrap_cli apply \
  --lake-root /Volumes/datasource/data_lake \
  --confirm-lake-write \
  --batch-size 20 \
  --output /private/tmp/index_mins_bootstrap_apply_<timestamp>.json
```

`dry-run` 不写 Lake、Dagster DB、dynamic partitions 或 event；`apply` 只写正式 Parquet，不写 Dagster event。正式日常通过后续单分区 job/sensor 运行，不提供绕过 partition、active pool 或 core check 的命令。所有命令示例必须在实现阶段用真实 CLI help 和测试更新，不能让文档命令与 parser 漂移。

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
| P4 | asset/check/catalog/schema/governance/job（已完成） |
| P5 | 专属分区、readiness、Raw/Silver sensor，默认 STOPPED |
| P6 | Bootstrap dry-run 与性能回归 |
| P7 | 正式 Raw/Silver Bootstrap 与文件对账，单独批准 |
| P8 | materialization 全量补、最近 20 日 check 补，单独批准 |
| P9 | 手动启用 sensor，观察连续 3 个交易日 |

验收必须覆盖：source/written/normalized/output 行数解释、目标 schema/date/PK、staging 清零、event partition、最近 20 日 ready、连续 3 日无超时。

当前下一步为 P5：实现专属分区注册、batch readiness 和默认 STOPPED 的 Raw/Silver sensor。P5 之前仍不启用 sensor，不执行正式 Bootstrap 或事件写入。

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
- [x] P4 定义/治理/核心 check 回归已通过：132 项相关测试通过；正式 Lake、Dagster DB、event 和 sensor 均未执行。
- [ ] active pool 空/重复/非法/漂移/查询失败负例已覆盖。
- [x] 原生 vwap 保留、派生 vwap NULL fixture 已覆盖。
- [ ] 最近 10 日期 readiness 性能测试已完成，event history 调用为 0。
- [ ] Bootstrap 请求量、连接数、分页、磁盘、内存和单批耗时预算已测量。
- [ ] 命令示例已经过真实 parser/help 对账；默认 dry-run 不写入。
- [ ] 前端分组、数据集卡片、详情字段和命令提示已对齐 catalog，不由页面硬编码。
- [ ] M3-M6 既有测试和静态门禁回归已通过。
- [ ] P0 文档与代码事实再次对账，未解释冲突已清零。

任何源字段、active pool、日期起点、窗口规则或性能预算冲突，必须停止并更新方案，不得靠兼容补丁绕过。
