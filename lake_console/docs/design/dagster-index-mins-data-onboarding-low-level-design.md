# `index_mins` 指数分钟线 Dagster 低层设计（LLD）

更新时间：2026-07-29
状态：P0 设计完成；P1/P2/P3/P4 已编码并通过本地/临时湖验证；P5 尚未开始
对应方案：[dagster-index-mins-data-onboarding-plan.md](./dagster-index-mins-data-onboarding-plan.md)

## 1. LLD 约束

本 LLD 把方案硬口径落到模块、函数、SQL、测试和阶段验收。P1/P2/P3 已完成合同、Prod 只读验证、Raw/Silver writer 和临时 fixture；仍不新增 active Dagster definition，不写正式 Lake，不读写正式 Dagster instance。

硬约束：

1. Raw 日常和 Bootstrap 只读 Prod DB；不在 Dagster 生产路径中调用裸 Tushare。
2. Raw 五频、Silver 七频，均为独立单分区 asset。
3. 每个 asset 一个单分区合并 blocking core check。
4. 所有目标文件都走 `_tmp -> validate -> atomic replace`。
5. Sensor 只做最近 10 日期 batch lake readiness + 有界 source probe，不读 event history。
6. 90m/120m 只由本地原生 Silver 派生，`vwap=NULL`。
7. 不新增 status manifest、summary/readiness asset、数据库表或持久化 active-pool entity。

## 2. 当前代码影响面审计

### 2.1 可复用但不能直接复制

| 当前模块 | 可复用部分 | 不可直接复制部分 |
|---|---|---|
| `defs/assets/stk_mins.py` | Prod DB read-only attach、DuckDB COPY、单日原子替换、metadata | 股票代码池、停牌、stock lifecycle、数字频率规则 |
| `defs/prod_db/index_daily.py` | allowlisted source columns、Prod SQL builder、source readiness dataclass | 日线字段、index daily 动态分区、日线覆盖语义 |
| `backend/app/services/prod_raw_index_mins_export_service.py` | 五频范围读取、流式 batch、源字段顺序 | backend manifest 依赖、旧 CLI、Python 分组语义 |
| `backend/app/services/tushare_index_mins_sync_service.py` | 显式 fields、频率标准化、源 API 参数 | 530 code x 5 Tushare fan-out |
| `defs/catalog/lake_assets.py` | catalog entry、schema、partition model、performance contract | 现有 index daily/stk mins 条目不能代替新 12 条资产 |
| `defs/partitions.py` | dynamic partition 定义方式 | 不复用宽泛 `cn_a_index_trade_days` |

### 2.2 预期文件和职责

~~~
orchestrator/defs/partitions.py
orchestrator/defs/paths.py
orchestrator/defs/run_contracts/index_mins.py
orchestrator/defs/prod_db/index_mins.py
orchestrator/defs/assets/index_mins.py       # P2 pure Raw writer
orchestrator/defs/assets/index_mins_raw.py
orchestrator/defs/assets/index_mins_silver.py
orchestrator/defs/assets/index_mins_silver_defs.py
orchestrator/defs/checks/index_mins_checks.py
orchestrator/defs/asset_guards/index_mins_lake_readiness.py
orchestrator/defs/jobs/index_mins.py
orchestrator/defs/sensors/index_mins_partition_sensor.py
orchestrator/defs/sensors/index_mins_sensor.py
orchestrator/defs/run_contracts/asset_column_schemas.py
tests/test_index_mins_*.py
~~~

Definitions 装配文件必须同步更新；不能只让模块可 import 而不进入正式 Definitions。jobs 只定义 selection，业务请求/SQL/写文件全部放 asset/helper/resource。

### 2.3 不受影响边界

- `index_daily` 的 `cn_a_index_trade_days` 和现有 sensor 不改。
- `index_global` 的自然日分区不改。
- `stk_mins` 的 `cn_a_stock_mins_trade_days` 不改。
- Prod DB 只读；不添加 migration、不添加写权限。
- 本专项只新增 `index_mins` catalog/schema/governance 条目。

## 3. 固定合同与配置审计

### 3.1 合同常量

新增 `defs/run_contracts/index_mins.py`，集中定义：

~~~
INDEX_MINS_HISTORY_START_DATE = "2025-01-02"
INDEX_MINS_SOURCE_FREQS = ("1min", "5min", "15min", "30min", "60min")
INDEX_MINS_RAW_ASSET_FREQS = (1, 5, 15, 30, 60)
INDEX_MINS_DERIVED_FREQS = (90, 120)
INDEX_MINS_SENSOR_WINDOW_LIMIT = 10
INDEX_MINS_BOOTSTRAP_BATCH_SIZE = 20
INDEX_MINS_SOURCE_PAGE_LIMIT = 8000
~~~

`1/5/...` 是 asset/内部 alias，`1min/5min/...` 是源字段/路径值，只允许通过一个双向 mapping 转换。硬编码任何第二份 mapping 都是静态门禁错误。

### 3.2 已有配置

| 配置 | 来源 | 消费者 | 结论 |
|---|---|---|---|
| `GOLDENSHARE_LAKE_ROOT` | LakeRootResource | asset/check/readiness | 复用 |
| `PROD_POSTGRES_*` | ProdPostgresResource | Raw writer/source probe | 只读复用 |
| `DAGSTER_HOME` | Dagster runtime | definitions/正式运行 | 业务代码不读取 |
| Tushare token | TushareResource | 本专项不消费 | 不作为 Prod Raw 前置依赖 |

本专项不新增 env、数据库配置、Dagster Config 或前端输入项。若后续把 query timeout、page limit、active-pool path 做成配置，必须单独完成配置审计并增加测试。

### 3.3 输入语义与源接口矩阵

时间语义拆成三层：

| 层 | 实现 | 约束 |
|---|---|---|
| 时间输入 | Dagster 单分区 `trade_date` | 由专属 dynamic partition 提供，不能直接输入任意日期绕过分区 |
| 执行单位 | 单日 Raw/Silver run；Bootstrap 最多 20 日源读取批次 | Raw 目标仍按日期/frequency 独立 staging 和 promote |
| freshness/audit | 最近 10 个 expected dates 的 Lake readiness + source probe | 不把“分区已注册”当成“源已更新”，不查 event history |

Tushare `idx_mins` 的必填参数为 `ts_code`、`freq`；`start_date/end_date` 是可选时间范围，`limit/offset` 是可选分页参数。P1 必须分别验证不传时间、最小时间窗口、跨页和空结果；验证用例只用于确认源行为，不进入正式 Prod writer。任何将 Tushare fallback 接入正式路径的变更，都必须重新完成 source adapter、配额、重试和失败恢复设计。

Prod 正式 Raw writer 不向用户暴露上述参数，而是从 `trade_date`、集中频率映射和 active pool 合同生成参数。生产路径固定使用 5 个频率范围 SQL 和 `fetchmany`，因此不会把 Tushare 的 `ts_code x freq` 请求量带入 Dagster。

### 3.4 P1 实现映射与验收证据

P1 已将本节的合同落到以下代码：

| 设计点 | 实现位置 | 关键约束 |
|---|---|---|
| 频率双向映射 | `defs/run_contracts/index_mins.py` | 只保留一份 `1/5/15/30/60` 与 `1min/5min/15min/30min/60min` 映射 |
| 字段合同 | `defs/run_contracts/index_mins.py`、`defs/run_contracts/asset_column_schemas.py` | 固定 11 列，包含 `freq/exchange/vwap` |
| 日期窗口 | `index_mins_trade_date_window(...)` | 使用目标日 `[00:00, 次日 00:00)` 的无时区窗口 |
| active pool | `defs/prod_db/index_mins.py` | `resource='index_mins'`、排序、`fetchmany(500)`、2,000 code 上限、重复/非法/空值 fail-closed |
| Prod range SQL | `build_prod_index_mins_range_query(...)` | 显式列、参数化频率/时间/code、禁止 `SELECT *` |
| source probe | `probe_prod_index_mins_source(...)` | 每频一次聚合查询，共五次；检查行数、code 数、重复 key、时间范围 |

P1 本地测试文件：

- `tests/test_index_mins_contracts.py`
- `tests/test_index_mins_prod_db.py`

验证结果：P1 专项 `13 passed`；加上既有 index daily Prod contract 和 static gates 后 `105 passed`；新模块和 schema 的 `py_compile` 通过。测试中的 fake connection 明确禁止 `fetchall()`，确保 active pool 路径保持有界读取。

2026-07-29 的正式 Prod 只读 source probe 以 `2026-07-27` 为目标日，active pool 为 530 个 code，五个源频率均覆盖 530 个 code，行数分别为 `127730/25970/9010/4770/2650`，各频率重复 key 为 0，所有时间戳位于目标日窗口内，五次聚合查询总耗时 2,229 ms。该 probe 没有写 Prod、Lake、Dagster DB 或事件，也没有调用 Dagster event history。

source probe 的 code 覆盖是聚合计数，不等于 exact code-set 相等。P2 Raw writer 已对实际 fetched rows 做集合差异校验（missing/extra code），并在 staging 回读后再次校验；只有 exact-set、schema、日期、主键和行数合同同时通过，才允许 promote。P1 不提前把明细集合装入 source probe，避免把 sensor/探测路径变成高内存或高延迟流程。

### 3.5 P2 Raw writer 实现映射与验收证据

P2 已将 Raw 写入硬口径落到：

| 设计点 | 实现位置 | 验收方式 |
|---|---|---|
| 专属 Raw 路径 | `defs/paths.py:raw_index_mins_path` | 频率和日期路径测试 |
| attached read-only Prod source | `defs/prod_db/index_mins.py`、`defs/assets/index_mins.py` | attach options 为 `TYPE POSTGRES, READ_ONLY`，无写 resource |
| 五频单查询 | `build_prod_index_mins_duckdb_source_sql(...)` | 每次单频一个 set-based range query，显式 11 列，无 `SELECT *` |
| exact active code-set | `defs/assets/index_mins.py:_code_set_diff` | missing/extra code 均 fail-closed，有限样本进入错误信息 |
| 主键与范围 | `defs/assets/index_mins.py:_validate_relation` | `(ts_code, freq, trade_time)` 重复、日期/频率越界均拒绝 |
| DuckDB staging | `write_raw_index_mins_partition_from_prod_db(...)` | 先 source relation，再 `COPY` 临时 Parquet |
| 回读与原子替换 | 同一 writer | schema、行数、集合合同复核后 `os.replace`；异常清理 staging |
| 已有文件语义 | 同一 writer | 合同通过才复用；错误文件不覆盖；目标出现竞争时停止 |

P2 测试文件：

- `tests/test_index_mins_raw_writer.py`
- `tests/test_index_mins_prod_db.py`

P2 专项回归共 `23 passed`。真实临时湖 smoke 读取 Prod 的 `2026-07-27`：`5min` 为 25,970 source/written rows、`1min` 为 127,730 source/written rows，两次均为 530 expected/returned codes，缺失/额外/重复/越界均为 0、单次 query，耗时约 8.369 秒和 15.948 秒；输出仅位于 `/private/tmp/index_mins_p2_smoke_20260729` 与 `/private/tmp/index_mins_p2_smoke_20260729_1min`。

P2 明确没有把 exact code-set 明细下沉到 source probe 或 cursor。writer 只在单日/单频 staging 内做集合差异，性能边界为单频一个源查询、一个 DuckDB connection、一个 staging 文件；五频和 20 日 Bootstrap 总预算留到 P6 真实回归。

### 3.6 P3 Silver writer 实现映射与验收证据

P3 将 Silver 设计落到纯 writer 模块，不提前把业务逻辑放进 asset 或 sensor：

| 设计点 | 实现位置 | 关键约束 |
|---|---|---|
| 七频合同 | `defs/run_contracts/index_mins.py` | 原生 `1/5/15/30/60min`，派生 `90/120min`；派生源分别固定为 `30min/60min` |
| Silver 路径 | `defs/paths.py:silver_index_mins_path` | `silver/quote/index_mins/freq=<freq>/trade_date=<date>/part-000.parquet` |
| 原生标准化 | `defs/assets/index_mins_silver.py:_native_normalized_sql` | trim/uppercase、类型固定、日期/freq/PK/OHLC/数值校验，native vwap 保留 |
| 90m 窗口 | `defs/assets/index_mins_silver.py:_derived_diagnostics`、`_derived_output_sql` | 固定 3 个窗口，最后窗口 2 根；按 anchor 判断，不以总行数冒充完整 |
| 120m 窗口 | 同上 | 固定 2 个窗口，每个 2 根；额外源 bar 不进入目标 |
| 聚合 | `_derived_output_sql` | first open、last close、max high、min low、sum vol/amount、exchange 单值、vwap NULL |
| staging/回读 | `write_silver_index_mins_partition` | staging schema/row/PK/domain 回读后才 `os.replace`；目标错误或竞争出现时停止 |
| 派生失败 | `_derived_diagnostics` | 缺 bar、混合 exchange、无完整窗口均 fail-closed，旧目标不动 |

P3 测试文件：`tests/test_index_mins_silver_writer.py`。本地 fixture 共 `7 passed`，覆盖 native vwap、90m/120m 锚点和聚合、非窗口源 bar、缺窗口、混合 exchange、staging 清理、错误目标不覆盖和无 active Dagster definition。测试只使用临时 lake/DuckDB，不调用 Prod、Tushare、Dagster instance 或 event API。

530 个代码的临时性能样本中，原生五频 writer 各耗时约 `11.211-15.432 ms`，90m/120m 派生 writer 分别约 `21.159/20.926 ms`；含临时 fixture 物理文件生成的整轮耗时约 `3.155 s`。该样本不替代 P6 正式湖性能验收，P6 仍需测量五频连续运行、文件大小、磁盘增量、20 日批次和峰值内存。

## 4. Schema 与路径

### 4.1 Column contract

定义 `INDEX_MINS_RAW_SCHEMA` 和 `INDEX_MINS_SILVER_SCHEMA` 两个稳定 schema tuple：

~~~
ts_code      VARCHAR   指数代码
freq         VARCHAR   源/派生频率
trade_time   TIMESTAMP 分钟 bar 时间
open         DOUBLE    开盘点位
close        DOUBLE    收盘点位
high         DOUBLE    最高点位
low          DOUBLE    最低点位
vol          DOUBLE    成交量
amount       DOUBLE    成交金额
exchange     VARCHAR   交易所
vwap         DOUBLE    源端成交均价；derived 固定 NULL
~~~

Raw/Silver 都不增加 `trade_date`、`source`、`fetched_at` 等系统列。稳定 schema 放 definition metadata 的 `dagster/column_schema`；materialization 只放 observed columns 和本次事实。

### 4.2 Path helper

新增纯函数：

~~~
raw_index_mins_path(lake_root, source_freq, trade_date)
silver_index_mins_path(lake_root, silver_freq, trade_date)
~~~

约束：只接受 allowlist 频率；日期必须是 ISO；文件固定 `part-000.parquet`；不扫描历史、不隐式 fallback。

路径：

~~~
raw/tushare/index_mins/freq=<source_freq>/trade_date=<date>/part-000.parquet
silver/index_mins/freq=<silver_freq>/trade_date=<date>/part-000.parquet
~~~

路径中的 `tushare` 是源数据域命名；definition source system 仍为 `prod_core_db`。

## 5. Prod DB source contract

### 5.1 Allowlist

~~~
PROD_INDEX_MINS_SOURCE_TABLE = "raw_tushare.index_mins"
PROD_INDEX_MINS_ACTIVE_TABLE = "ops.index_series_active"
PROD_INDEX_MINS_ACTIVE_RESOURCE = "index_mins"
PROD_INDEX_MINS_SOURCE_COLUMNS = (
    "ts_code", "freq", "trade_time", "open", "close", "high", "low",
    "vol", "amount", "exchange", "vwap",
)
~~~

禁止 `SELECT *`、write resource、sensor 明细读取、从 run key 解析源范围。

### 5.2 Active pool

允许 SQL：

~~~sql
SELECT ts_code
FROM ops.index_series_active
WHERE resource = 'index_mins'
ORDER BY ts_code
~~~

校验：resource、空 code、重复 code、code 格式。对排序集合计算 SHA-256 hash。完整 code 列表只能在内存中短暂存在，不写 cursor/event。

### 5.3 Dagster 质量依赖

Raw asset 声明 `silver_index_basic` 依赖，用于在 Dagster 图中表达指数基础事实的质量前置；当前 P2 writer 不读取该文件来缩小源端代码集合，也不在 Prod 查询中隐式执行生命周期 join。源端范围固定由 `ops.index_series_active(resource='index_mins')` 提供，active pool 的 exact code-set 校验在 DuckDB staging 内完成。

因此，`silver_index_basic` 缺失或未 ready 时由 Dagster 依赖关系阻断 Raw asset；writer 本身不会通过猜测或无界补查改变源范围。

### 5.4 Raw query

每个频率只允许一个范围查询：

~~~sql
SELECT
  ts_code, freq, trade_time, open, close, high, low,
  vol, amount, exchange, vwap
FROM raw_tushare.index_mins
WHERE freq = %(freq)s
  AND trade_time >= %(start_ts)s
  AND trade_time < %(end_ts)s
  AND ts_code = ANY(%(effective_codes)s)
ORDER BY ts_code, trade_time
~~~

实现可使用现有 DuckDB PostgreSQL read-only attach，但必须经统一 SQL builder 生成。单日范围为当天 00:00 到次日 00:00，目录日期由 planner 传入。

### 5.5 Sensor source probe

Sensor 不读取明细，只做五个聚合查询：

~~~sql
SELECT
  COUNT(*) AS row_count,
  COUNT(DISTINCT ts_code) AS code_count,
  COUNT(DISTINCT (ts_code, trade_time)) AS key_count,
  MIN(trade_time) AS min_trade_time,
  MAX(trade_time) AS max_trade_time
FROM raw_tushare.index_mins
WHERE freq = %(freq)s
  AND trade_time >= %(start_ts)s
  AND trade_time < %(end_ts)s
  AND ts_code = ANY(%(effective_codes)s)
~~~

ready 条件：

- active/effective code count > 0。
- 五频都有正行数。
- code_count 等于 effective_code_count。
- key_count 等于 row_count。
- min/max 在目标日期内。
- 查询未超时，连接为只读。

需要展示缺失 code 时，最多执行一次有界 `SELECT DISTINCT ts_code`，不能循环 530 个 code。

## 6. Raw Asset、Writer、Metadata

### 6.1 Asset 定义

每个 Raw asset 只绑定一个 source frequency：

~~~python
@dg.asset(
    name="raw_index_mins_1m",
    partitions_def=cn_a_index_mins_trade_days,
    group_name="index",
    deps=["silver_index_basic"],
    metadata=build_asset_definition_metadata(...),
)
def raw_index_mins_1m(...):
    return _materialize_raw_index_mins_partition(..., source_freq="1min")
~~~

建议用 `RAW_INDEX_MINS_ASSETS` tuple 复用五份 selection。`silver_index_basic` 只能作为只读 quality dependency，不能加入 Raw job selection。

### 6.2 Writer 顺序

~~~text
ensure lake root
 -> normalize partition/frequency
 -> verify dedicated partition membership
 -> open read-only Prod session
 -> read active pool + hash
 -> execute one source range query
 -> DuckDB staging table
 -> set-based schema/date/freq/key/value/coverage validation
 -> COPY staging to _tmp/<run_id>/raw/...
 -> re-read staging parquet
 -> atomic replace
 -> MaterializeResult metadata
~~~

目标存在且正确：`skip_existing`。目标存在但错误：raise，禁止覆盖。目标不存在才进入 staging。

### 6.3 Result fields

内存态 result 至少包含：

~~~text
partition_key
source_freq
target_path
active_pool_count
effective_code_count
active_pool_hash
source_row_count
written_row_count
duplicate_key_count
null_key_count
date_mismatch_count
invalid_value_count
query_count
elapsed_ms
staging_path
write_status
~~~

source/written 不一致、任何核心计数非零或 staging 回读失败，都不 promote。

## 7. Silver Asset、Writer、指标语义

### 7.1 Native Silver

五个原生 asset 读取同日对应 Raw，通过一次 DuckDB set-based SQL 标准化：

~~~sql
SELECT
  upper(trim(ts_code)) AS ts_code,
  trim(freq) AS freq,
  CAST(trade_time AS TIMESTAMP) AS trade_time,
  CAST(open AS DOUBLE) AS open,
  CAST(close AS DOUBLE) AS close,
  CAST(high AS DOUBLE) AS high,
  CAST(low AS DOUBLE) AS low,
  CAST(vol AS DOUBLE) AS vol,
  CAST(amount AS DOUBLE) AS amount,
  NULLIF(trim(exchange), '') AS exchange,
  CAST(vwap AS DOUBLE) AS vwap
FROM read_parquet(?)
~~~

检查日期、频率、主键、数值有限性、OHLC 关系。主键冲突按 reason code 拒绝，不静默 `DISTINCT`。

### 7.2 90m

源 `30min`，沿用股票分钟线已批准窗口：

| source bars | target anchor | required rows |
|---|---|---:|
| 10:00,10:30,11:00 | 11:00 | 3 |
| 11:30,13:30,14:00 | 14:00 | 3 |
| 14:30,15:00 | 15:00 | 2 |

每个 code 独立判断，窗口不完整则不写目标。

### 7.3 120m

源 `60min`：

| source bars | target anchor | required rows |
|---|---|---:|
| 09:30,10:30 | 10:30 | 2 |
| 11:30,14:00 | 14:00 | 2 |

### 7.4 OHLC/VWAP

DuckDB 聚合必须等窗口完整后执行：

~~~sql
first(open ORDER BY trade_time) AS open,
last(close ORDER BY trade_time) AS close,
max(high) AS high,
min(low) AS low,
sum(vol) AS vol,
sum(amount) AS amount,
CASE WHEN COUNT(DISTINCT exchange) = 1 THEN min(exchange) ELSE NULL END AS exchange,
CAST(NULL AS DOUBLE) AS vwap
~~~

exchange 多值失败，不静默取第一值；vwap NULL 是固定合同而非计算失败。

## 8. Checks、Jobs、Sensors

### 8.1 Checks

`checks/index_mins_checks.py` 用通用 builder 生成 12 个显式分区 check：

~~~
raw_index_mins_{1m,5m,15m,30m,60m}_core_check
silver_index_mins_{1m,5m,15m,30m,60m,90m,120m}_core_check
~~~

每个 check：

- 绑定 `cn_a_index_mins_trade_days`。
- blocking=True。
- 只读当前 Lake 文件，必要时读取同日 Raw。
- 一次 set-based 汇总 file/schema/freq/date/PK/identity/value。
- 派生频率再检查窗口/anchor/vwap NULL。
- failure metadata 含 reason code、计数、有限样本。

禁止 multi-partition 聚合 check、Prod DB 查询、event history 扫描、字段级高基数 check。

### 8.2 Jobs

~~~
raw_index_mins_update_job
  = assets(RAW_INDEX_MINS_ASSETS)
    + checks_for_assets(RAW_INDEX_MINS_ASSETS)

silver_index_mins_update_job
  = assets(SILVER_INDEX_MINS_ASSETS)
    + checks_for_assets(SILVER_INDEX_MINS_ASSETS)
~~~

jobs 只做 selection、description、executor；不能调用 SQL、Prod、Tushare 或 writer。

### 8.2.1 P4 实现映射与验收

P4 已完成，实际定义边界为：

| 交付 | 实现位置 | 关键约束 |
|---|---|---|
| 五个 Raw asset | `defs/assets/index_mins_raw.py` | 逐频固定 source frequency，专属动态分区，依赖 `silver_index_basic`；调用 P2 writer |
| 七个 Silver asset | `defs/assets/index_mins_silver_defs.py` | 原生依赖对应 Raw；90m/120m 分别依赖 30m/60m Silver；调用 P3 writer |
| 12 个 core check | `defs/checks/index_mins_checks.py` | 每 asset 一个 `blocking=True`、显式 `cn_a_index_mins_trade_days` 的 check |
| Raw/Silver job | `defs/jobs/index_mins.py` | 只做 asset + `checks_for_assets` selection，不调用业务 writer |
| catalog/governance | `defs/catalog/lake_assets.py`、`tests/test_asset_check_incremental_governance.py` | 12 个 asset/check 一一对应；P5 前 readiness participation 保持 false |

核心 check 只读当前分区 Parquet，并复用 P3 的 schema、日期、主键、值域和派生窗口语义；不访问 Prod、不扫描 event history、不拆成高基数 check event。P4 定义/治理/核心 check 回归通过；没有正式 Lake、Dagster DB 或 event 写入。

### 8.3 Partition sensor

`index_mins_trade_day_sensor`：

- 从 `silver_trade_calendar` 读取 SSE open dates。
- 从历史起点起补齐专属 dynamic partitions。
- 支持停机后 catch-up。
- 不读取 event history、不请求 Prod 明细。
- 不复用 `cn_a_index_trade_days`。

### 8.4 Raw/Silver sensors

Raw/Silver sensor 默认 STOPPED，分别使用现有：

- `build_sensor_tags`
- `build_sensor_cursor`
- `build_run_request`
- `build_asset_update_run_key`

Raw：最近 10 日期的 batch lake readiness + 单次 Prod aggregate source probe；source ready 才提交五资产 run。Silver：Raw 五频 ready 后，提交最早 Silver 缺口；90m/120m 由本地窗口规则决定。

cursor 只保留 decision、target、reason_code、blocked_component、expected/registered、frontier、query count、elapsed 和有限样本；小于 8 KB，reason 为 ASCII。每 tick 最多一个 RunRequest。

## 9. Bootstrap、事件与测试

### 9.1 Bootstrap

新增非 active Dagster 的 dry-run planner/CLI：

~~~text
defs/bootstrap/index_mins_bootstrap_plan.py
defs/bootstrap/index_mins_bootstrap_cli.py
~~~

dry-run 输出日期计划、active hash、源 coverage、目标冲突、预计行数/文件数/磁盘/查询/耗时；不写 Lake、Dagster DB、dynamic partitions 或 event。apply 必须有独立 `--confirm-lake-write`。

正式顺序：

1. Raw 按最多 20 日/批串行生成。
2. Raw 全量对账通过后生成 Silver。
3. Silver native 完成后生成 90m/120m。
4. 失败日期停止当前批次，成功日期报告可续跑。
5. 错误目标不覆盖。

### 9.2 Event backfill

P8 单独执行：

- 所有成功 Raw/Silver 分区补 materialization。
- blocking check 只补最近 20 个专属交易日。
- 每条 event 显式带正确 partition。
- 事件补录前必须通过 Lake 文件对账。
- 不从 check history 推导业务事实。

### 9.3 测试矩阵

Contract/static：

- 资产 5/7 数量、名称、分区。
- 12 个 check 显式 partitioned/blocking。
- jobs 不含业务逻辑。
- catalog/governance 集合完全一致。
- source SQL 无 `SELECT *`。
- writer 无裸 `TushareResource.call()`。
- sensor 无 `instance.get_event_records`。
- cursor 使用 `build_sensor_cursor` 且小于 8 KB。

Source/Raw：

- active pool 空/重复/非法/漂移/查询失败。
- source 字段/freq/date/PK/coverage。
- source/written 行数不一致。
- staging 失败不覆盖旧文件。
- 正确目标 skip、错误目标停止。
- 五频每次只发一个范围 query。
- connection 只读。

Silver：

- native pass-through。
- 90m/120m 完整和缺窗口。
- OHLC/vol/amount 聚合。
- native vwap 保留、derived vwap 全 NULL。
- exchange 多值失败。
- 输出主键和日期。

Sensor/performance：

- 专属分区缺口只影响注册。
- source not ready 不提交 Raw。
- Raw failure 不覆盖。
- Raw ready 才允许 Silver。
- 每 tick 一个 DuckDB connection，最多一个 RunRequest。
- 最近 10 日不读 event history。
- 20 日 Bootstrap 流式内存/耗时在预算内。

建议测试文件：

~~~text
tests/test_index_mins_contracts.py
tests/test_index_mins_prod_db.py
tests/test_index_mins_raw_writer.py
tests/test_index_mins_silver_writer.py
tests/test_index_mins_definitions.py
tests/test_index_mins_checks.py
tests/test_index_mins_lake_readiness.py
tests/test_index_mins_sensors.py
tests/test_index_mins_bootstrap.py
tests/test_run_contract_static_gates.py
~~~

## 10. 开发顺序与验收

1. P1：频率/字段/Prod SQL/source probe contract（已完成）。
2. P2：Raw writer、staging、原子替换、临时 parquet smoke（已完成）。
3. P3：Silver native/90m/120m writer 与 fixture（已完成）。
4. P4：asset/check/catalog/schema/governance/job（已完成）。
5. P5：专属分区、batch readiness、Raw/Silver sensors，默认 STOPPED。
6. P6：Bootstrap dry-run 与性能回归。
7. P7：正式 Raw/Silver Bootstrap 与文件对账，单独批准。
8. P8：materialization 全量补、最近 20 日 checks 补，单独批准。
9. P9：手动启用 sensor，观察连续 3 个交易日。

任一阶段发现源字段、active pool、日期起点、窗口规则或性能预算冲突，停止当前阶段并回写方案。

P4 已完成：五个 Raw asset、七个 Silver asset、12 个单分区 blocking check、两份 job、catalog 和 governance 映射已落地，并通过定义、治理、核心 check 和临时湖回归。P5 才实现 readiness 和 sensor；在 P5 完成前不启用 sensor、不做正式 Bootstrap 或事件写入。

## 11. 回滚与边界

风险处理：

- active pool 查询失败：本次 fail-closed。
- active pool 漂移：记录 hash/差异，停止当前范围。
- Prod 源缺失：source probe not ready，等待。
- 派生窗口不完整：不写目标。
- schema 漂移：staging 校验停止，旧文件不动。
- sensor 过慢：停止启用，重做 batch readiness，不提高 RPC timeout。

回滚只清理当前 run 临时 staging；不删除既有 Parquet、Dagster event 或 Prod 数据。
