# Dagster 主要指数历史分钟线接入 LLD

> 2026-08-13 当前口径：本文继续约束 Raw/Silver 接入，但不再定义最终业务 K 线层。
> 主要指数必须新增七频 Gold bars；Gold 非 1m 不输出 09:30，技术指标和业务 reader
> 都只消费 Gold。代码级变更和安全重建顺序见
> [A 股分钟线 Gold 标准 K 线合同与历史重建 LLD](./dagster-cn-a-minute-gold-canonical-bars-rebuild-low-level-design.md)。
> P2 代码已完成 7 个 Gold asset/check、单分区 job、默认停止 sensor，并已将 technical 和
> 本地 reader 改为 Gold-only；正式 Gold/technical 历史重建、事件补录与运行启用尚未执行。

> 2026-08-07 修正：90m/120m 第一上午 bar 必须使用 `09:30.close` 作为 open/高低价锚点并包含竞价 `vol/amount`；90m 输出 `11:00/14:00/15:00`，120m 输出 `11:30/15:00`。旧窗口与历史文件必须按[统一修复与重建 LLD](./dagster-derived-minute-bars-90-120-contract-rebuild-low-level-design.md)替换。

## 1. LLD 范围

本文将 `major_index_mins` 方案细化到模块、常量、函数、SQL、事务、sensor 和测试级别。本文只设计新链路，不改当前 `index_mins` 代码。

依据：

- `/Users/congming/github/goldenshare/AGENTS.md`；
- `/Users/congming/github/goldenshare/lake_console/orchestrator/AGENTS.md`；
- `/Users/congming/github/goldenshare/lake_console/orchestrator/CODING_STANDARDS.md`；
- `docs/sources/tushare/指数专题/0419_股票历史分钟行情.md`；
- `docs/datasets/index-mins-dataset-development.md`；
- 当前 `index_mins` 的 Raw/Silver writer、bounded readiness、专属分区和 sensor 实现。

## 2. 文件边界

### 2.1 运行合同

新增：

```text
lake_console/orchestrator/src/orchestrator/defs/run_contracts/major_index_mins.py
```

负责固定：

- `MAJOR_INDEX_MINS_CODES`；
- `MAJOR_INDEX_MINS_DAILY_CODES`；
- `MAJOR_INDEX_MINS_SOURCE_FREQS`；
- `MAJOR_INDEX_MINS_SILVER_FREQS`；
- 每个代码的 `source_start_date`；
- `899050.BJ` 的 `source_start_date=2022-11-21`、`source_end_date=2025-10-30`；
- Raw source scope、Silver output scope 计算和 hash；
- 字段合同、窗口预算、请求预算；
- Raw/Silver asset/check 名称。

建议数据结构：

```python
@dataclass(frozen=True, slots=True)
class MajorIndexMinsSourceScope:
    ts_code: str
    source_start_date: str
    source_end_date: str | None

    def eligible_on(self, trade_date: str) -> bool: ...

MAJOR_INDEX_MINS_SOURCE_SCOPES: tuple[MajorIndexMinsSourceScope, ...]
```

P7C 后必须把“请求范围”和“Silver 输出范围”拆开：

```python
def effective_raw_request_codes_for_date(trade_date: str) -> tuple[str, ...]: ...

def effective_silver_codes_for_date(trade_date: str) -> tuple[str, ...]: ...
```

`effective_raw_request_codes_for_date()` 继续按 11 个 source scope 返回排序后的 tuple，
在 `2022-11-21..2025-10-30` 包含 `899050.BJ`；
`effective_silver_codes_for_date()` 从同日 source scope 中固定排除 `899050.BJ`，Silver
所有七个频率只包含其余 10 个指数及其各自起始日期后的有效行。两者都必须拒绝未知代码、
重复 scope、日期格式错误和空 scope 误进入 writer。

不得再设计 Silver 的 BSE“日期 + 频率 availability”例外。北证50不是 Silver 输出成员，
因此其历史缺行、错误时间网格和负值不进入 Silver date-only output scope。

Raw/Silver scope hash 必须分别对各自排序后的代码集合做 SHA-256；不把完整代码列表写
cursor。旧 `effective_codes_for_date()` 在所有消费者迁移完成后删除，不保留兼容分支。

### 2.2 分区与路径

修改：

```text
lake_console/orchestrator/src/orchestrator/defs/partitions.py
lake_console/orchestrator/src/orchestrator/defs/paths.py
```

新增：

```python
cn_major_index_mins_trade_days = dg.DynamicPartitionsDefinition(
    name="cn_major_index_mins_trade_days"
)
```

新增路径函数：

```python
raw_major_index_mins_path(root, source_freq, partition_key) -> Path
silver_major_index_mins_path(root, frequency, partition_key) -> Path
```

路径函数只接受白名单频率和 ISO 日期，不接受任意路径片段。

### 2.3 Raw writer

新增：

```text
lake_console/orchestrator/src/orchestrator/defs/assets/major_index_mins_raw.py
```

纯 writer 建议拆到：

```text
lake_console/orchestrator/src/orchestrator/defs/io/major_index_mins_raw_writer.py
```

核心接口：

```python
fetch_major_index_mins_window(
    *, ts_code, source_freq, start_datetime, end_datetime,
    tushare, request_policy,
) -> BoundedPageResult

write_major_index_mins_raw_partition(
    *, lake_root, partition_key, source_freq, effective_codes,
    tushare, duckdb, mode,
) -> MajorIndexMinsRawWriteResult

bootstrap_major_index_mins_raw_batch(
    *, lake_root, date_plan, code_scopes, tushare, duckdb,
    batch_size=20,
) -> MajorIndexMinsBootstrapBatchResult
```

Raw writer 不能直接调用裸 `TushareResource.call()`；只能调用项目统一 bounded request helper。

### 2.4 Silver writer

新增：

```text
lake_console/orchestrator/src/orchestrator/defs/assets/major_index_mins_silver.py
```

核心接口：

```python
write_major_index_mins_silver_partition(
    *, lake_root, partition_key, frequency, duckdb,
) -> MajorIndexMinsSilverWriteResult
```

原生频率读取同频 Raw；派生频率读取：

```text
90min  <- 30min
120min <- 60min
```

### 2.5 Assets/checks/jobs

新增：

```text
assets/major_index_mins_raw.py
assets/major_index_mins_silver.py
checks/major_index_mins_checks.py
jobs/major_index_mins.py
```

Raw asset 五个，Silver asset 七个，均为单分区 asset。

每个 asset 的 check 通过 `@asset_check(..., partitions_def=cn_major_index_mins_trade_days, blocking=True)` 定义。Job 只能选择对应 asset 和对应 check，不允许多分区聚合 check。

### 2.6 Readiness/sensors

新增：

```text
asset_guards/major_index_mins_lake_readiness.py
sensors/major_index_mins_partition_sensor.py
sensors/major_index_mins_sensor.py
```

Sensor 默认 `STOPPED`。传感器只用统一 `build_sensor_cursor()`、`build_run_request()` 和 `build_asset_update_run_key()`。

## 3. Raw 详细算法

### 3.1 单日运行

对 `partition_key` 和每个原生频率：

1. 调用 `effective_raw_request_codes_for_date(partition_key)`；
2. 目标文件存在时，使用 DuckDB contract 检查，正确则返回 `reuse_existing`，错误则 fail closed；
3. 对每个 effective code 请求该日数据；
4. 显式字段为 `MAJOR_INDEX_MINS_SOURCE_COLUMNS`；
5. 分页结束后将结果放入 DuckDB 临时表；
6. 校验列集合、`freq`、日期、允许代码集合、主键和时间范围；Raw 对北证50不执行
   代码覆盖、session grid、OHLC envelope、vol/amount 非负或 exchange 身份业务判断；
7. `COPY` 到唯一 staging Parquet；
8. 对 staging 再执行同一组 SQL；
9. 仅在 staging 与 source 行数对账通过后 `os.replace`；
10. 任一频率失败时，该频率不得替换正式目标文件；其它频率即使成功，也不能被 batch readiness 视为“五频全部 ready”。

日常 Dagster asset 是按频率独立执行的，因此不伪造跨五个 asset 的操作系统级事务。每个频率都必须独立 staging、回读校验和原子替换；Raw batch readiness 只有在当日所有适用频率都通过后才为 ready，Silver sensor 不会消费部分五频结果。Bootstrap coordinator 可以在批次层先完成全部频率 staging，再按批次验收结果 promote。

### 3.2 Raw source fact 校验

Raw 文件保存 Tushare 返回事实，不把 fallback 或 Silver 清洗结果写回 Raw。每个日期建立
非北证 expected source grid；P7B 已发布的非北证 source-empty scope 从对应日期/频率的
Raw expected grid 中精确排除，但不允许按日期范围扩展。北证50不进入 Raw 业务完整性
expected grid，它的返回行只接受结构安全校验。

DuckDB 临时表：

```sql
CREATE TEMP TABLE expected_non_bse_source_rows(
  ts_code VARCHAR,
  source_time TIME,
  PRIMARY KEY(ts_code, source_time)
);
```

Raw 全体行必须满足：

- 文件 schema 可解析且列顺序/类型符合 Raw 合同；
- `ts_code/freq/trade_time` 非空，代码属于 11 个 source scope；
- `freq` 与资产一致，`trade_time` 日期等于 partition；
- `(ts_code, freq, trade_time)` 全文件唯一；
- 非北证行与 `expected_non_bse_source_rows` exact match；
- BSE 行不参与 expected code/session/domain 比较，也不产生独立 check event。

这不是“完全不读 BSE 行”：Parquet schema、分区串线和全文件主键冲突属于文件级安全
事实，无法按代码拆除；但北证50没有任何业务完整性、session 或数值质量门禁。

主键检查：

```sql
SELECT COUNT(*) - COUNT(DISTINCT (ts_code, trade_time))
FROM source;
```

时间边界使用当日 `09:00:00 <= trade_time < next_date 00:00:00`；非北证行再校验交易时段
不能出现非允许时间。BSE Raw 只做分区日期边界，不做 session grid 业务判断。

### 3.3 Bootstrap 窗口

Bootstrap date plan 先固定每个指数的有效日期集合，再按频率切分窗口：

```python
BOOTSTRAP_WINDOW_TRADING_DAYS = {
    "1min": 20,
    "5min": 60,
    "15min": 120,
    "30min": 180,
    "60min": 240,
}
```

每个窗口请求必须：

- `start_date` 与 `end_date` 为 datetime 字符串；
- `limit=8000`、`offset=0...`；
- offset 严格递增；
- 返回空页结束；
- 返回满页时切分窗口或继续分页，但不得把满页视为窗口完整；
- 跨页 `(ts_code, trade_time)` 重复立即失败；
- 列漂移立即失败；
- 总请求数、重试数和耗时超过预算立即停止。

Bootstrap 不通过逐日 Python append 写 Parquet；所有窗口进入 DuckDB，再批量按日期生成 staging 文件。

## 4. Silver 详细算法

Silver 首先调用 `effective_silver_codes_for_date(partition_key)`，并在任何 domain/session
校验前过滤 `ts_code <> '899050.BJ'`。原生五频、90min 和 120min 都不得输出北证50。

原生 Silver：

```sql
SELECT
  upper(trim(ts_code)) AS ts_code,
  CAST(trade_time AS TIMESTAMP) AS trade_time,
  CAST(open AS DOUBLE) AS open,
  CAST(close AS DOUBLE) AS close,
  CAST(normalized_high AS DOUBLE) AS high,
  CAST(normalized_low AS DOUBLE) AS low,
  CAST(vol AS DOUBLE) AS vol,
  CAST(amount AS DOUBLE) AS amount,
  CASE
    WHEN upper(trim(ts_code)) LIKE '%.SH' THEN 'XSHG'
    WHEN upper(trim(ts_code)) LIKE '%.SZ' THEN 'XSHE'
  END AS exchange,
  CAST(vwap AS DOUBLE) AS vwap,
  CAST(freq AS VARCHAR) AS freq
FROM normalized_non_bse_source;
```

Silver 必须再次执行日期、频率、Silver scope、主键和严格 domain 校验，不信任 Raw
metadata。历史 OHLC 修正只允许命中 P7C 冻结的精确白名单；未知日期、代码、频率或
时间点的 OHLC 异常继续 fail closed。

派生 90/120 分钟使用统一交易 bar 窗口合同，不跨日期聚合。第一上午 bar 单独使用 `09:30.close` 作为 open/高低价锚点并包含竞价 `vol/amount`；后续窗口按明确 source 时间集合聚合。90m 第二窗口可包含午休前后的三根有序交易 bar，但午休期间没有虚构 source 行。完整规则以统一修复 LLD 为准。

## 5. Sensor 详细算法

### 5.1 分区注册

`major_index_mins_trade_day_sensor`：

- 读取 `silver_trade_calendar`；
- 从 `2009-01-05` 到当前日期生成自然交易日；
- 每 tick 最多注册固定数量；
- 不调用 Tushare、不访问 Prod DB、不读取 event history；
- 只负责 dynamic partition registration，不提交 run。

### 5.2 Raw sensor

`raw_major_index_mins_update_job_sensor`：

1. 以专属分区和最近 10 个 expected dates 建立 batch window；
2. 一次 DuckDB 查询读取五个 Raw 频率文件的 ready 状态；
3. 选择最早缺口；
4. 若已 materialize 但 core check 失败，skip，不覆盖；
5. 对候选日期只对 `MAJOR_INDEX_MINS_DAILY_CODES` 发 1min 小窗口探测；
6. 10 个代码全部有目标日期行，提交一个 Raw run；
7. 代码探测为空、请求异常、当前日期尚未出数时 skip；
8. cursor 保存 `reason_code`、target date、expected/registered 数、source probe count/elapsed 和小型 frontier。

探测不扫描历史 event；探测只针对当前选中的第一个缺口，不对 10 日窗口逐日请求 Tushare。

### 5.3 Silver sensor

`silver_major_index_mins_update_job_sensor`：

- 同一 DuckDB connection 批量读取 Raw/Silver 10 日 readiness；
- Raw 目标日未 ready 时 skip；
- Silver 目标已存在但 check 失败时 skip；
- 只提交最早 Silver 缺口；
- 每 tick 最多一个 RunRequest；
- 不调用 Tushare、Prod DB、event history。

## 6. Check 详细规则

每个 check 产出一个小型 metadata：

```text
failed_rules
reason_code
partition_key
expected_code_count
checked_row_count
duplicate_key_count
finite_domain_error_count
sample_rows <= 5
```

禁止把完整代码列表、完整失败行或分页明细写进 check metadata/cursor。

Raw 核心规则：

1. 目标文件存在且行数大于 0；
2. schema 与字段合同完全一致；
3. `freq` 与资产频率一致；
4. `trade_time` 日期等于 partition；
5. 所有代码属于 Raw source scope，非北证 source grid 按正式规则 exact match；
6. `(ts_code, trade_time)` 唯一；
7. 不对 `899050.BJ` 执行代码覆盖、session、OHLC、volume/amount 或 exchange 业务检查。

Silver 核心规则固定使用排除北证50后的 Silver date-only output scope，严格检查文件、schema、
日期、频率、代码 exact match、主键、session、OHLC、volume/amount、exchange 和派生窗口。
每个资产仍只有一条合并 blocking core check：Raw 5 条、Silver 7 条、合计 12 条；禁止
按指数、字段或规则拆 check。北证50没有专属 check，也不新增任何 check event。

## 7. Governance/catalog

需要同步：

- `catalog/lake_assets.py`：12 个资产和 12 个 blocking check；
- catalog name mapping：主要指数分钟线中文名；
- `PartitionModelDefinition`：`cn_major_index_mins_trade_days`；
- `ASSET_CHECK_GOVERNANCE`：12 个 check 一一映射；
- asset definition metadata：source doc、source scope、path template、schema、start/end 语义；
- run contracts 和 static gates。

治理类别：普通 Raw/Silver core check 进入 readiness 和最近窗口事件保留；不新增
repair/status check。12 条 check 每个交易日最多写 12 条 event，约每年 3,000 条，
并继续服从最近窗口 retention。`899050.BJ` 只属于 Raw source fact，不进入 Silver、
Silver readiness 或任何专属 check。

## 8. 测试清单

新增测试：

```text
tests/test_major_index_mins_contracts.py
tests/test_major_index_mins_tushare_probe.py
tests/test_major_index_mins_raw_writer.py
tests/test_major_index_mins_bootstrap.py
tests/test_major_index_mins_silver_writer.py
tests/test_major_index_mins_checks.py
tests/test_major_index_mins_lake_readiness.py
tests/test_major_index_mins_sensors.py
tests/test_major_index_mins_definitions.py
```

必须覆盖：

- 11 个 code contract、科创综指代码和北证 stop date；
- 代码起止日期前后 scope 变化；
- 五种字段显式请求；
- 单页、多页、空页、满页二分、跨页重复、offset 错误和列漂移；
- 目标文件缺失/正确/错误三种冲突；
- Raw 五频全量成功时各频率分别原子 promote；任一频率失败时失败频率零目标替换且 batch readiness 保持未 ready；
- Silver 原生与 90/120 派生窗口；
- 899050 在 2025-10-31 后不阻断；
- sensor 只探测 10 个代码、最多一个 run、不调用 event history；
- cursor ASCII、体积受限；
- Bootstrap 请求、内存、文件数和耗时预算。

## 9. 阶段验收

进入正式 Bootstrap 前必须满足：

- Tushare 真实字段与分页验证通过；
- 11 个代码和 source scope fingerprint 冻结；
- Raw/Silver 临时湖联调通过；
- Bootstrap dry-run 给出精确请求数、日期数、预计文件数和磁盘预算；
- 所有失败日期、空响应和北证 source stop 都可解释；
- 不写 Dagster DB/event，不启用 sensor；
- 全量 Raw 对账通过后才生成 Silver；
- 事件补录与日常 sensor 启用另设阶段。

## 10. 未决边界

本次核验已冻结主要业务口径，无需用户再次拍板。实现时如果 Tushare 对 `limit/offset` 的真实返回与文档不一致，必须停止实现，以 MCP/项目真实 request wrapper 结果重新校准，不允许静默降级为截断数据。

## 11. 模板合规后的代码级实现合同

本节是对模板审计后新增的实现合同。实现时不能只创建“能运行”的 writer；必须同时落地 Catalog、metadata、governance、配置审计和测试门禁。

### 11.1 文件与职责矩阵

| 文件 | 只负责 | 禁止负责 |
| --- | --- | --- |
| `defs/run_contracts/major_index_mins.py` | 11 个代码 scope、起止日、频率、字段、预算、asset/check/job 名称、hash | 读 Lake、读 Dagster instance、请求 Tushare |
| `defs/run_contracts/asset_column_schemas.py` | `RAW_MAJOR_INDEX_MINS_SCHEMA`、`SILVER_MAJOR_INDEX_MINS_SCHEMA` | 运行时推断 schema |
| `defs/partitions.py` | `cn_major_index_mins_trade_days` | 访问源站 |
| `defs/paths.py` | Raw/Silver 专属路径和频率/日期白名单 | 接收任意路径片段 |
| `defs/io/major_index_mins_raw_writer.py` | bounded Tushare page、DuckDB staging、原子 promote | 直接写 Dagster event |
| `defs/assets/major_index_mins_raw.py` | 5 个 Raw asset wrapper | 业务 SQL、裸 Tushare call |
| `defs/assets/major_index_mins_silver.py` | 7 个 Silver asset wrapper | 读取 event history、隐式补洞 |
| `defs/checks/major_index_mins_checks.py` | 12 个 partitioned blocking core checks | Tushare 请求、历史事件扫描 |
| `defs/asset_guards/major_index_mins_lake_readiness.py` | 最近 10 日 DuckDB batch readiness | Tushare、Prod、Dagster event |
| `defs/jobs/major_index_mins.py` | asset + check selection | 业务请求逻辑、multi-partition check |
| `defs/sensors/major_index_mins_partition_sensor.py` | 专属动态分区注册 | 请求源数据、事件补录 |
| `defs/sensors/major_index_mins_sensor.py` | bounded probe、first-not-ready、RunRequest/cursor | 五频抓取、全历史扫描 |
| `defs/bootstrap/major_index_mins_bootstrap_*` | dry-run/apply/event backfill 三阶段入口 | 隐式覆盖、sensor tick |
| `defs/catalog/lake_assets.py` | 12 个 Catalog 条目和 2 个 PartitionModel | 运行时请求 |
| `tests/test_asset_check_incremental_governance.py` | 12 个 governance mapping | 业务实现 |

### 11.2 运行合同常量和数据结构

`major_index_mins.py` 至少包含：

```python
MAJOR_INDEX_MINS_CODES = (...11 codes...)
MAJOR_INDEX_MINS_DAILY_CODES = (...10 online codes...)
MAJOR_INDEX_MINS_SOURCE_FREQS = ("1min", "5min", "15min", "30min", "60min")
MAJOR_INDEX_MINS_SILVER_FREQS = ("1min", "5min", "15min", "30min", "60min", "90min", "120min")
MAJOR_INDEX_MINS_SOURCE_COLUMNS = (...11 columns in contract order...)
MAJOR_INDEX_MINS_HISTORY_START_DATE = "2009-01-05"
MAJOR_INDEX_MINS_BOOTSTRAP_MAX_REQUESTS = 5000
MAJOR_INDEX_MINS_DAILY_PROBE_WINDOW_LIMIT = 10
```

并定义：

```python
@dataclass(frozen=True, slots=True)
class MajorIndexMinsSourceScope:
    ts_code: str
    source_start_date: str
    source_end_date: str | None

    def eligible_on(self, trade_date: str) -> bool: ...

@dataclass(frozen=True, slots=True)
class MajorIndexMinsSourceRevision:
    scope_revision: str
    scope_hash: str
    request_hash: str
    result_hash: str
    revision: str
```

`effective_raw_request_codes_for_date()`、`effective_silver_codes_for_date()` 和各层 scope
hash 必须先规范化日期、校验 scope 不重复，再排序计算。Raw scope hash 表示请求范围，
Silver scope hash 表示最终输出范围；`source_revision` 还必须包含请求参数和结果内容摘要。
任何 hash 不写完整代码列表到 cursor。

### 11.3 字段 contract 的实现形态

`asset_column_schemas.py` 中每个 `ColumnContract` 必须显式写：字段名、类型、nullable、说明。顺序固定为：

```text
ts_code, freq, trade_time, open, close, high, low, vol, amount, exchange, vwap
```

Raw 通过 `build_asset_definition_metadata(..., column_schema=RAW_MAJOR_INDEX_MINS_SCHEMA, source_api="idx_mins", source_doc=...)` 写定义 metadata；Silver 使用 `SILVER_MAJOR_INDEX_MINS_SCHEMA`。writer 不从第一批响应动态生成 schema。

### 11.4 分区与路径实现

`partitions.py` 新增：

```python
cn_major_index_mins_trade_days = dg.DynamicPartitionsDefinition(
    name="cn_major_index_mins_trade_days"
)
```

`paths.py` 新增 `raw_major_index_mins_path()` 和 `silver_major_index_mins_path()`，统一经过 `normalize_*_frequency()`、`normalize_partition_key()`。函数必须拒绝未知频率、非 ISO 日期、包含 `/` 的片段。

`major_index_mins_partition_sensor.py` 读取 `silver_trade_calendar_path(root)`，只投影 `trade_date, exchange, is_open`，使用 `exchange='SSE' AND is_open=true AND trade_date >= '2009-01-05'`，去重排序后调用现有 partition registration helper。它不能把 `source_scope_empty` 当作删除 dynamic partition 的理由。

## 12. Raw writer 的 SQL、分页和事务边界

### 12.1 请求 wrapper

Raw writer 只能通过项目统一 Tushare resource/policy。每页请求必须按项目 wrapper 的真实签名传入：

```python
tushare.call(
    "idx_mins",
    {
        "ts_code": code,
        "freq": source_freq,
        "start_date": start_datetime,
        "end_date": end_datetime,
        "limit": 8000,
        "offset": offset,
    },
    MAJOR_INDEX_MINS_SOURCE_COLUMNS,
)
```

P1 必须用真实项目 wrapper 验证：第一请求 offset=0；后续 offset 严格增加；空页只在上一页未满或已确认窗口完整时结束；满页继续分页/二分；跨页 `(ts_code,trade_time)` 重复 fail closed；返回列集合严格等于 contract。不能把 MCP 工具不暴露 `limit/offset` 当作分页已经通过。

错误分类固定为：`retryable_network`、`retryable_rate_limit`、`invalid_request`、`source_empty`、`schema_drift`、`duplicate_key`、`budget_exceeded`、`unknown_source_error`。重试只允许 retryable 类别；`source_empty` 必须结合有效 scope 和日常 probe 语义判断，不能直接写成功文件。

### 12.2 单日频率写入

单日单频按以下事务边界执行：

```text
validate input/scope/path
 -> read existing target contract (if exists)
 -> bounded Tushare pages
 -> DuckDB TEMP expected_raw_codes/source_rows
 -> set-based validation
 -> COPY unique staging parquet
 -> re-read staging with same validation
 -> re-check target does not appear/change
 -> os.replace(staging, target)
```

没有 Python 逐行 Parquet append，没有目标文件覆盖。五频不是同一数据库事务；如果某一频率失败，其它频率可以有自己的成功文件，但 batch readiness 只在五频适用范围全部 ready 后通过。Bootstrap runner 可以先把所有 staging 留在临时目录，统一验收后逐文件 promote。

### 12.3 核心 DuckDB 验证

```sql
CREATE TEMP TABLE expected_raw_codes(ts_code VARCHAR PRIMARY KEY);

SELECT COUNT(*) AS unexpected_code_rows
FROM (
  SELECT DISTINCT ts_code FROM source_rows
  EXCEPT SELECT ts_code FROM expected_raw_codes
  UNION ALL
  SELECT ts_code FROM expected_raw_codes
  EXCEPT SELECT DISTINCT ts_code FROM source_rows
);

SELECT COUNT(*) AS duplicate_key_rows
FROM (
  SELECT ts_code, trade_time
  FROM source_rows
  GROUP BY ts_code, trade_time
  HAVING COUNT(*) > 1
);
```

另执行：字段集合、`CAST(trade_time AS DATE)=partition`、`freq=expected`、source
rows=staging rows。非北证行继续执行 session grid、OHLC 和 finite/non-negative domain；
北证50只执行结构安全规则，不执行这些业务质量规则。失败 metadata 只保留 reason code、
计数和最多 5 个样本。

## 13. Session grid 与 Silver 派生

### 13.1 Session grid

非北证 source row 的 `trade_time` 必须属于 SH/SZ 允许时间集合，实现复用当前
`index_mins` session helper。北证50 Raw 只保存源事实，不建立 BSE session fixture，
不以 session 完整性阻断 Raw，也不进入 Silver。所有代码仍必须满足分区日期一致和
`(ts_code, trade_time)` 全文件唯一，禁止跨日和重复键污染 Parquet。

### 13.2 Native Silver

原生频率 SQL 必须先过滤 `899050.BJ`，再做 trim/uppercase、exchange 后缀派生、
类型标准化、日期/freq/date-only Silver scope/key/domain/session 检查，并在 DuckDB staging
中输出。Silver 不能相信 Raw 的 metadata；必须重新验证 source rows、output rows 和拒绝原因。

### 13.3 90m/120m

`90m` 只从 Silver 30m，`120m` 只从 Silver 60m，并复用唯一共享窗口合同。90m 输出 `11:00/14:00/15:00`；120m 输出 `11:30/15:00`。第一上午 bar 的 open 使用 `09:30.close`，high/low 包含该价格锚点，vol/amount 包含 09:30 竞价行一次；其它窗口为 first open、last close、max/min、sum。每个 anchor 和常规 source 时间集合必须完整；缺任何一项时不写该窗口，不把部分窗口标 ready。派生 vwap 继续为 NULL。

## 14. Asset、check、job 与 Definition 细节

### 14.1 Assets

Raw 五个 asset：`raw_major_index_mins_{1,5,15,30,60}m`，均使用 `partitions_def=cn_major_index_mins_trade_days`、`group_name="index"`、`AssetLayer.RAW`、`DataDomain.QUOTE_DATA`。每个 asset 只传固定频率给 writer，不从 context 接受自由频率。

Silver 七个 asset：原生五个分别依赖同频 Raw；90m 依赖 30m Silver；120m 依赖 60m Silver。每个 asset 使用同一专属分区和 `AssetLayer.SILVER`。

### 14.2 Checks

每个 asset 一个 `@dg.asset_check(..., partitions_def=cn_major_index_mins_trade_days, blocking=True)`。check function 只读取当前 asset/partition 的目标文件，不读取其它日期的 event history。metadata 必须由 `build_check_metadata()` 生成，并补充：`reason_code`、`failed_rules`、`expected_code_count`、`duplicate_key_count`、`scope_hash`、最多 5 个样本。

核心 check 规则：文件、schema、row count、date/freq、effective code set、`(ts_code,trade_time)` 唯一、数值域、session/window。失败返回 `passed=False` 并以 ERROR blocking；不把请求耗时、分页明细拆成 check。

### 14.3 Jobs 与 Definitions

Raw job 只选择 Raw 五个 asset 及对应 checks；Silver job 只选择 Silver 七个 asset 及对应 checks。job 的 `partitions_def` 为专属分区，不允许一次多日期执行聚合 check。`definitions.py` 仍使用 `load_from_defs_folder(path_within_project=Path(__file__).parent)`，新模块放进该目录扫描范围。

## 15. Sensor 代码级伪流程

```python
@dg.sensor(
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb", "tushare"},
)
def raw_major_index_mins_update_job_sensor(context):
    evaluated_at = now_in_configured_timezone()
    with context.resources.duckdb.connect() as connection:
        window = load_expected_trade_date_window(..., window_limit=10)
        registered = context.instance.get_dynamic_partitions(
            cn_major_index_mins_trade_days.name
        )
        gap = build_registered_gap_status(...)
        lake = batch_raw_major_index_mins_lake_readiness(connection, ...)
    target = select_first_not_ready_trade_date(lake, ...)
    probe = probe_online_codes_once(target, context.resources.tushare)
    if not probe.ready:
        return dg.SensorResult(skip_reason=probe.reason_code, cursor=build_cursor(...))
    return dg.SensorResult(
        run_requests=[build_run_request(
            run_key=build_asset_update_run_key(
                subject="raw_major_index_mins_update", unit_id=target
            ),
            partition_key=target,
        )],
        cursor=build_cursor(...),
    )
```

上面是结构合同，不是允许直接复制的实现。实际 sensor 还必须：注册分区缺口优先阻断、目标已物化但 check 失败时 skip、probe 不逐日扩展、只保留小型 frontier/performance 摘要。Silver sensor 无 Tushare/Prod resource，只做 Raw/Silver readiness。

## 16. Metadata、事件和报告分层

### 16.1 三类 metadata

| 层 | 必须包含 | 禁止包含 |
| --- | --- | --- |
| definition | dataset id/name、source system/api/doc、contract、schema、path、scope revision | 当前运行逐页明细 |
| materialization | uri、source/written rows、freq/date、scope hash、source revision、request/page/retry/elapsed | 完整代码列表、完整返回行 |
| check | check scope、partition、checked/failed rows、failed rules、reason、有限样本 | event history、完整异常行、全量路径列表 |

### 16.2 Event backfill

事件补录工具必须单独读取已审计文件，不从普通 sensor 猜历史。Materialization 全量补；check 只最近 20 个专属分区。每个事件单分区、单资产、可通过 `asset_check_executions.partition` 查到。正式前输出：计划报告、样本报告、全量报告、最终只读对账报告；任一 partition 归属缺失停止。

## 17. 配置审计表

当前设计不新增 env 配置；以下版本化常量必须作为配置事实在 run contract 中登记：

| 配置/常量 | 默认值 | 来源 | 消费者 | 生效方式 |
| --- | --- | --- | --- | --- |
| `MAJOR_INDEX_MINS_SOURCE_FREQS` | 5 个源频率 | 代码合同 | Raw asset/writer/check/job | 代码发布 |
| `MAJOR_INDEX_MINS_DAILY_CODES` | 10 个在线代码 | 代码合同 | probe/sensor | scope revision 发布 |
| `MAJOR_INDEX_MINS_BOOTSTRAP_MAX_REQUESTS` | 5000 | 代码合同 | Bootstrap planner/apply | 代码发布 |
| `MAJOR_INDEX_MINS_BOOTSTRAP_WINDOW_TRADING_DAYS` | 20/60/120/180/240 | 代码合同 | Bootstrap planner/source staging | 代码发布 |
| `MAJOR_INDEX_MINS_SENSOR_WINDOW_LIMIT` | 10 | 代码合同 | readiness/sensor | 代码发布 |
| `TUSHARE_FIELDS` | 11 个字段固定顺序 | 源字段合同 | request builder/schema | 代码发布 |

实现阶段如需 env 覆盖，必须重新做配置审计和测试；不能把窗口/预算散落在 sensor、writer、CLI 三处。

## 18. 测试与实现门禁矩阵

| 类别 | 正向 | 负向 |
| --- | --- | --- |
| contract | 11 code scope、五频、字段、路径、起止日 | 重复 scope、未知 code、scope empty 误写 |
| Tushare | 显式 fields、单页、多页、空页 | offset 不增、满页截断、跨页重复、列漂移、错误分类 |
| Raw | source/staging 回读相等，五频独立 promote | 任一频率失败覆盖目标、目标冲突、预算超限 |
| Silver | native、90m/120m 固定 source 时间集合 | 错误 source 时间集合、跨日期、缺竞价锚点、非法 partial window、vwap 误填 |
| check | partitioned core check 通过/失败 | 无 partition、multi-partition 聚合、超大 metadata |
| sensor | request/skip/blocked/ready，最多一个 run | event history/Tushare 五频/Prod 调用、cursor >8KB |
| catalog | 12 条 exact entry、12 条 governance mapping | 少映射、多映射、中文名缺失、旧 partition 误复用 |
| Bootstrap/event | plan/source staging/staging audit/temp lake/promote/post audit | dry-run 重复请求、隐式 apply、覆盖坏文件、无 partition event |

### 18.1 验证命令

代码阶段使用：

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator
uv run python -m pytest -q \
  tests/test_major_index_mins_contracts.py \
  tests/test_major_index_mins_tushare_probe.py \
  tests/test_major_index_mins_raw_writer.py \
  tests/test_major_index_mins_bootstrap.py \
  tests/test_major_index_mins_silver_writer.py \
  tests/test_major_index_mins_checks.py \
  tests/test_major_index_mins_lake_readiness.py \
  tests/test_major_index_mins_sensors.py \
  tests/test_major_index_mins_definitions.py \
  tests/test_run_contract_static_gates.py
uv run ruff check src tests
```

只读定义检查为 `dg check defs`。P6 plan dry-run 禁止请求 Tushare；P7 source staging 的真实请求必须单独批准并记录报告。开发阶段禁止正式 lake、Dagster DB/event、sensor tick 和正式 Bootstrap。

## 19. LLD 收口状态

已冻结：代码集合、科创综指、北证停止语义、Raw/Silver 频率和依赖、字段、专属分区、单 check、统一 cursor、事件保留口径和性能红线。

已由实现验证：项目 wrapper 的真实分页、SH/SZ session fixture、BSE source anomaly
只读审计、Raw/Silver 临时湖
联调、12 个 Catalog/governance/definitions 注册和 P5 sensor/readiness。P6 无请求
planner、可恢复 source staging、只读 staging audit、临时 Raw/Silver build/audit 和跨
文件系统安全 promote 已完成本地 fake-source 全链路测试；P7 source staging 也已一次性
完成。P7B 非北证 bounded Silver fallback 的代码、真实 retained-staging 临时重建和
独立 post-audit 均已通过；P7C 合同、P7D 完整临时湖、P7E 正式 promote 与 P8 runless
event 补录也已依次完成。当前只剩 P9 sensor 启用与连续交易日观察。若源站/项目 wrapper
与本文冲突，必须保留 staging 事实、更新本文与方案后再继续，不得在代码中静默放宽语义。

## 20. P0 开工审计记录

P0 已完成，执行日期为 `2026-08-05`。本阶段只读代码和文档，没有运行 Dagster、写 Lake、写 Dagster DB 或请求生产数据库。

### 20.1 硬口径到实现映射

| 硬口径 | 实现位置 | 必须测试的反例 |
| --- | --- | --- |
| 只允许 11 个 source scope | `run_contracts/major_index_mins.py` | 未知代码、重复代码、起止日逆序 |
| 北证只到 2025-10-30 | scope helper/Raw check/readiness | 2025-10-31 后把北证当缺失 |
| Raw 仅五频、Silver 七频 | contracts/assets/jobs/catalog | 未知频率、资产数量漂移 |
| 专属动态分区 | `partitions.py`/partition sensor | 误用 `cn_a_index_mins_trade_days` |
| 单 asset 单 blocking check | checks/governance/catalog | 无 partition check、多 check 膨胀 |
| writer 失败不覆盖 | Raw/Silver writer | staging/分页/回读失败仍 replace |
| sensor 最近 10 日、最多一个 run | readiness/sensors | 全历史扫描、多个 RunRequest |
| sensor 不读 event history | sensors/static gate | 调用 `get_event_records` |
| materialization 全量、check 最近 20 日 | Bootstrap event helper | 无 partition check event、全历史 check 膨胀 |
| P9 不在本目标执行 | milestone gate | 自动启用 sensor |

### 20.2 CodeGraph 影响面

CodeGraph 项目根使用 `/Users/congming/github/goldenshare`。审计覆盖：

- `write_raw_index_mins_partition_from_prod_db`、`write_silver_index_mins_partition`；
- Raw/Silver batch lake readiness；
- `raw_index_mins_update_job_sensor`、`silver_index_mins_update_job_sensor`、专属 partition sensor；
- `plan_index_mins_bootstrap_events`、runless materialization/check 模式；
- `LakeAssetCatalogEntry` 构造 helper、PartitionModel、中文名和 governance 测试。

结论：新增数据集不改变现有 `index_mins` contract；共享文件只做新增枚举/常量/条目，不修改旧资产语义。Definitions 由 `load_from_defs_folder()` 自动装配，测试是主要消费者。没有生产 `DatasetDefinition`、Ops TaskRun、前端或业务 API 消费者。

### 20.3 P0 性能基线

| 维度 | 冻结值/状态 |
| --- | --- |
| object count | 11 个代码，日常 probe 10 个 |
| enum expansion | Raw 5，Silver 7，check 12，Catalog 12，PartitionModel 2 |
| daily base requests | Raw 50；probe 10；分页另计 |
| sensor lake scan | 最近 10 日，Raw 最多 50 文件；Silver 联合最多 120 文件，单 DuckDB connection |
| Bootstrap request budget | <= 5000；P6 给出精确量 |
| write grain | `freq + trade_date` 单文件 staging/readback/atomic replace |
| unacceptable | 无界分页/重试、全历史 Python 缓存、event history 扫描、错误目标覆盖 |

### 20.4 P0 验收

- 三份设计文档无尾随空白，源文档和模板路径存在；
- 11 个代码、北证停止日、五频/七频、10/20 日窗口在三份文档一致；
- 当前仓库中 `major_index_mins` 仅存在于本专项文档，无同名生产实现或兼容代码；
- 工作区其它 `reports/**` 未跟踪文件属于无关任务，后续不触碰；
- P1 未验证事项仍明确标记为未完成，没有被 P0 冒充通过。

P0 结论：通过，可以进入 P1。

## 21. P1 源合同与真实请求验收

P1 已完成，执行日期为 `2026-08-05`。新增范围只有纯 source contract、bounded fetcher 和测试；没有 Dagster decorator、Lake 写入、Dagster DB/event、sensor tick 或 Bootstrap。

### 21.1 实测事实

- MCP 默认字段：`ts_code,trade_time,open,close,high,low,vol,amount`；显式字段后 `freq,exchange,vwap` 均返回。
- `000001.SH` 在 `2026-08-04 15:00:00` 的 `1/5/15/30/60min` 五频均返回，字段合同一致。
- 10 个 scope 的文档起点与 MCP 一致；北证50旧起点被纠正为 `2022-11-21`。
- `899050.BJ` 在 `2025-10-30` 返回 5 条 60m 行，`2025-10-31` 和 `2026-08-04` 返回空，停止边界成立。
- 项目 `TushareResource.call()` 真实分页：page limit=2、`000001.SH/60min/2026-08-04` 得到 3 页、5 行、0 重试，时间点为 09:30、10:30、11:30、14:00、15:00。

详细报告：`/private/tmp/major_index_mins_p1_source_probe_20260805.json`。

### 21.2 代码与门禁

- `run_contracts/major_index_mins.py` 固定 11 个 scope、五频/七频、11 字段、起止日、有效代码集合和 source revision。
- `io/major_index_mins_raw_writer.py` 只实现有界 fetch，不写文件；显式传 fields，参数中传 `limit/offset`。
- `execute_bounded_code_pages()` 负责严格 offset、预算、重试和跨页 key 去重；fetcher 额外拒绝 empty expected code、schema/freq/code/time 漂移。
- 10 个专项测试覆盖 scope、字段、生命周期、稳定 hash、单/多页、空结果、schema 漂移、跨页重复和非法输入。

### 21.3 P1 结论

P1 通过，可以进入 P2。P1 当时把 BSE session 留给 P3；该历史安排已被 P7C 最终口径
取代：BSE 只保留 Raw 源事实，不再建立 session 质量合同，也不进入 Silver。

## 22. P2 Raw staging 与原子替换验收

P2 已完成，执行日期为 `2026-08-05`。实现只写临时测试 Lake；没有 Dagster asset/check/job/sensor，也没有正式 Lake、Dagster DB/event 写入。

### 22.1 实现事实

- `paths.py` 新增独立 Raw target/staging 路径，严格拒绝未知频率、非 ISO 日期和不安全 run id。
- `write_major_index_mins_raw_partition()` 每次只处理一个 `trade_date + source_freq`，Raw
  request code set 来自版本化日期 scope。
- 目标已存在且合同正确时直接复用，不请求 Tushare；目标已存在但 schema/日期/主键/代码集/数值域错误时拒绝覆盖。
- 目标缺失时先执行 P1 bounded fetch，再进入 DuckDB 固定 schema temp table；source 和 staging 使用同一套 set-based validation。
- staging 通过回读和行数对账、再次确认目标未出现后才 `os.replace()`；异常路径删除 staging 文件。
- validator 对缺列文件先做 schema fail-closed，不再引用不存在的列产生 BinderException。

### 22.2 测试与性能

7 个 P2 测试覆盖：专属路径、正常 promote、正确目标复用、错误目标拒绝、source 质量失败、staging 回读失败和日常 1min 量级。

性能 fixture 已在 P3 exact-session 门禁中加严为：10 个在线代码、每代码 241 行、总计 2,410 行、10 次请求/10 页；本机 source -> DuckDB -> Parquet -> 回读 -> promote 约 `1.01s`，低于 10 秒测试门禁。没有逐行 Parquet append、无 Dagster event history、无全历史内存缓存。

### 22.3 P2 结论

P2 通过，可以进入 P3。P2 当时要求 P3 冻结 SH/SZ/BSE session/window fixture；P7C
最终口径已取消 BSE Silver/session 合同，只保留 SH/SZ session/window fixture。不得把
Raw 仅校验 BSE 结构安全误写成 BSE 业务质量已经通过。

## 23. P3 Silver writer 与 session 口径验收

P3 已完成，执行日期为 `2026-08-05`。实现和测试仅使用临时 Lake；没有 Dagster asset/check/job/sensor，也没有正式 Lake、Dagster DB/event 写入。

### 23.1 真实 session 与派生口径

- SH/SZ 五频日行数固定为 `241/49/17/9/5`，首行 `09:30`、末行 `15:00`。
- BSE 五频日行数固定为 `271/55/19/10/6`，首行 `09:30`、末行 `15:30`。
- 三个交易所都拒绝午休时段行；原生 Silver 必须 exact code set + exact session grid，不接受只看行数。
- 90m 以 30m 为源。正式 Silver 只覆盖 SH/SZ，输出 `11:00/14:00/15:00`；第一根使用 09:30 竞价锚点加 `10:00/10:30/11:00`。
- 120m 以 60m 为源。正式 Silver 只覆盖 SH/SZ，输出 `11:30/15:00`；第一根使用 09:30 竞价锚点加 `10:30/11:30`，第二根使用 `14:00/15:00`。旧 `10:30/14:00` 输出已废止。
- 派生窗口 `open/close/high/low/vol/amount` 使用 DuckDB set-based 聚合，派生 `vwap` 固定为 `NULL`。

### 23.2 写入和共用质量门禁

- `major_index_mins_quality.py` 提供 Raw/Silver 共用的 schema、类型、代码集合、session、主键、价格/成交量和 exchange/vwap 规则。
- Raw P2 validator 已迁移到共用门禁，避免 Raw、Silver、后续 check/readiness 语义漂移。
- `major_index_mins_silver_writer.py` 对原生频率读取同日 Raw，对 90m/120m 读取同日 30m/60m Silver。
- source、计算结果、staging 回读全部通过同一合同后才 `os.replace()`；正确已有目标复用，错误/损坏目标 fail-closed 且不覆盖。
- 派生 expected/generated window 数必须完全一致，任一缺窗不写目标。

### 23.3 测试与性能

P1-P3 及共享请求策略共 `37` 项测试通过。核心性能样本：Raw 1min 2,410 行约 `1.01s`，Silver 90m fixture 约 `0.19s`，Silver 120m fixture 约 `0.16s`。测试覆盖 Native 规范化/vwap、缺 session、BSE 15:30、90m/120m OHLCV 聚合公式、派生源错误和损坏已有目标保护。

详细只读源与性能报告：`/private/tmp/major_index_mins_p3_session_probe_20260805.json`。

### 23.4 P3 结论

P3 审计通过，可以进入 P4。P4 只接入 asset、单 blocking check、job、Catalog/governance 和 definitions；不得提前创建 sensor、运行 Dagster 或写正式 Lake/event。

## 24. P4 Asset、check、job 与治理接入验收

P4 已完成，执行日期为 `2026-08-05`。本阶段只加载 definitions 和运行本地测试；没有执行 job/sensor、写正式 Lake 或写 Dagster event。

### 24.1 Definition 事实

- `major_index_mins_raw.py` 注册 5 个固定频率 Raw asset；每个 run 只把固定频率、partition 和 run id 传给 P2 writer。
- `major_index_mins_silver.py` 注册 7 个 Silver asset；五个原生频率依赖同频 Raw，90m 依赖 30m Silver，120m 依赖 60m Silver。
- 12 个 asset 全部绑定 `cn_major_index_mins_trade_days`，没有复用现有 `cn_a_index_mins_trade_days`。
- `major_index_mins_checks.py` 每资产只注册一个显式 partitioned blocking core check，复用 P3 exact code/session/schema/key/domain 门禁；check 不访问 Tushare 或 event history。
- Raw/Silver 两个 job 分层选择对应 assets + checks，保持单分区执行。

### 24.2 Catalog 与治理

- `asset_column_schemas.py` 新增独立 Raw/Silver 字段合同，不复用别的数据集 id 冒充。
- Catalog 新增 12 条 exact entry、Raw/Silver 两个 PartitionModel，并登记 Tushare/Derived 来源、原子替换、runless event 能力和性能合同。
- 中文名固定为“主要指数分钟线”。
- `ASSET_CHECK_GOVERNANCE` 对 12 个 check 做 exact mapping，类别为 `MOVE_TO_SENSOR_LAKE_READINESS`、阶段为 `MAJOR_INDEX_MINS_P5`、允许历史 retention。
- 初次共享治理测试暴露 check tuple 未展开为模块级定义的问题；已将 12 个 check 显式导出，active definition 扫描与 governance/catalog 完全一致。没有通过修改测试绕过。

### 24.3 验证与结论

P1-P4 专项、全量 governance 和 static gate 共 `127` 项测试通过；Ruff 通过；`dg check defs` 输出 `All definitions loaded successfully`；`git diff --check` 无错误。

P4 审计通过，可以进入 P5。P5 只实现专属分区注册、10 日 bounded Raw/Silver lake readiness 和默认 STOPPED sensors；不得执行 sensor tick、正式 Bootstrap 或正式写入。

## 25. P5 实施记录（2026-08-05）

### 25.1 已完成实现

- 新增 `major_index_mins_trade_day_sensor`，仅按 SSE 开市日历注册 `cn_major_index_mins_trade_days`，历史下限为 `2009-01-05`，默认 `STOPPED`。
- 新增 Raw/Silver 最近 10 日 batch lake readiness。两层 readiness 复用 P3 的 exact schema、code scope、exchange、session grid、业务主键和数值域门禁；缺文件为可执行缺口，已有文件但 core 语义失败则阻断自动覆盖。
- 新增 Raw/Silver 两个默认 `STOPPED` sensor，统一使用 `build_sensor_cursor()`、`build_run_request()` 和 `build_asset_update_run_key()`；每 tick 最多一个 RunRequest，不读取 Dagster event history。
- Raw sensor 只在 first-not-ready Raw 缺文件时执行 15:00 的 1min bounded source probe。探针固定请求 `MAJOR_INDEX_MINS_DAILY_CODES` 的 10 个持续在线指数；`899050.BJ` 已在 source scope 于 `2025-10-30` 停止，不进入日常探针。
- Silver sensor 在同一个 DuckDB connection 内读取 Raw/Silver frontier；Raw 未覆盖目标日期或已有 Silver 文件不健康时 fail closed。

### 25.2 性能红线与修正

初版 readiness 虽然语义正确，但对每个日期、每个频率重复创建 expected code/session 临时表。10 日完整临时湖基准扫描 Raw 50 文件和 Silver 70 文件时，联合耗时 `13,427.827ms`，超过稳定态 10 秒目标，因此没有直接放行。

实现改为按“频率 + effective code scope”分组复用 expected tables，不减少任何 blocking 语义。相同 10 日、120 文件、单 DuckDB connection 基准结果：

- Raw：`868ms`；
- Silver：`972ms`；
- 联合 wall time：`1,839.981ms`；
- event history API：`0` 次；
- 正式 lake / Dagster DB 写入：`0`。

自动回归测试同时固定：相同有效 scope 的两个日期，Raw expected tables 只按五个频率创建 5 次，不允许退回每日期重复创建。性能报告为 `/private/tmp/major_index_mins_p5_readiness_performance_20260805.json`。

### 25.3 真实源探针与阶段结论

对 `2026-08-04` 执行真实只读 Tushare 探针：10 个在线代码全部返回，10 次请求、0 次重试、`4,087.938ms`，结果 `ready=true`。报告为 `/private/tmp/major_index_mins_p5_source_probe_20260805.json`。

P5 专项行为、共享静态门禁和性能回归通过后，方可进入 P6。P6 只做无源请求的 Bootstrap plan dry-run、staging/audit 工具开发、磁盘预算与正式写入前冲突审计；仍不得执行 Tushare 全量请求、正式 Bootstrap、sensor tick 或 Dagster event 写入。

## 26. P6 首版审计结果与 staging 重构

首版 P6 把 plan 和全量源审计绑定在同一个 `dry-run` 中。完整历史计划为：

- 日期：`2009-01-05..2026-08-04`，4,271 个 SSE open dates；
- 源窗口：2,662 个，低于 5,000 次预算；
- 预计源行：10,022,855；
- 目标文件：Raw 21,355、Silver 29,897，共 51,252；
- 预计安全磁盘预算：约 11.65 GB；当前可用空间约 2.54 TB，磁盘门禁通过；
- 已存在正式目标文件：0；因此没有覆盖冲突。

首次全量只读执行在第 160 个窗口 fail-closed。`000001.SH` 的 `2022-02-07..2022-03-04` 1min 请求返回完整 4,820 行，但 `2022-02-07 09:30` 的源值为 `open=close=3407.762, high=low=0`。额外 100 次有界抽样证明：同日多只上证指数、五个原生频率均存在严格相同的 `09:30 + open=close>0 + high=low=0` 形态；深证和 `2026-08-04` 样本没有该异常。

这是源站历史哨兵值与当前合同冲突，不是缺行、分页截断、重复主键、session grid 错误或性能超限。首版已验证 766,380 行随进程释放，重新审计将重复消耗请求，因此首版执行模型废弃。

### 26.1 新 P6 边界

`major_index_mins_bootstrap_plan.py` 只负责：日期计划、source window 计划、预计行数、请求上限、目标冲突和磁盘预算。`major_index_mins_bootstrap_cli.py dry-run` 不构造 `TushareResource`，不读取 token，不调用 source fetcher，报告中的实际请求数固定为 0。

### 26.2 P7 source staging 物理合同

staging root 必须由 CLI 显式传入，并采用唯一日期计划 fingerprint：

```text
<staging_root>/
  _major_index_mins_source/
    scope_revision=<revision>/
      plan_fingerprint=<fingerprint>/
        freq=<freq>/
          ts_code=<code>/
            window_id=<window_id>/
              part-000.parquet
              request.json
  raw/tushare/major_index_mins/freq=<freq>/trade_date=<date>/part-000.parquet
  silver/quote/major_index_mins/freq=<freq>/trade_date=<date>/part-000.parquet
```

`request.json` 只保存有限标量：window id、请求参数 hash、result hash、行数、request/page/retry 数、耗时、字段合同、计划 fingerprint、完成状态和错误分类；不得保存完整行或完整异常列表。Parquet 和 sidecar 都先写唯一 `.tmp`，回读/hash 验证后原子替换。两者完整且与当前计划匹配才算窗口完成；断点续跑必须跳过完成窗口。

source staging 先忠实保存 Tushare 响应，不在写入前按正式 Silver OHLC 规则丢弃已成功请求的数据。transport gate 仍必须在落盘前保证显式 schema 可解析、请求身份一致、无分页截断/重复；业务审计随后只读 staging，统计 exact code/freq/date/session、主键、数值域和 OHLC 异常。审计失败保留 staging 并阻止 Raw/Silver build，不重新全量请求。

### 26.3 临时 Raw/Silver lake 与 promote

source staging 全量审计通过后，DuckDB 按 `freq + trade_date` 从窗口 Parquet set-based 生成临时 Raw；再复用正式 Silver writer 在同一 staging root 生成 Native/90m/120m。完整 Raw 21,355 和 Silver 29,897 文件全部通过 schema、scope、session、主键、行数、staging 残留和 source revision 对账后，才允许 `--confirm-lake-write` promote 到正式 lake。

promote 不重新请求 Tushare。考虑 staging root 与正式 lake 可能位于不同文件系统，不能直接跨盘 `os.replace()`：实现先复制到正式目标目录内的唯一临时文件，校验文件大小和 SHA-256，再在目标目录内执行 `os.replace()`。已存在且合同/hash 相同则 skip，已存在但不同或损坏则停止；全部文件完成后再跑正式 lake 全量 post audit。进程中断后根据报告幂等续跑。P7 请求入口必须有独立 `--confirm-source-request`，promote 必须有独立 `--confirm-lake-write`，二者不能合并成一个隐式 apply。

### 26.4 实际模块与命令边界

| 模块 | 唯一职责 | 是否请求 Tushare | 是否写正式 lake |
| --- | --- | --- | --- |
| `major_index_mins_bootstrap_plan.py` / `_cli.py dry-run` | 日期/窗口/磁盘/正式目标冲突计划 | 否 | 否 |
| `major_index_mins_bootstrap_stage.py` / `_stage_cli.py stage-source` | 缺失窗口请求一次、窗口 Parquet + sidecar 原子落 source staging | 是，必须 `--confirm-source-request` | 否 |
| `_stage_cli.py audit-staging` | 全量审计同一份 source staging | 否 | 否 |
| `major_index_mins_bootstrap_apply.py` / `_apply_cli.py build-temp` | 从 source staging 构建临时 Raw/Silver lake | 否 | 否，必须 `--confirm-staging-write` 才写临时 lake |
| `_apply_cli.py audit-temp` | 对临时 Raw/Silver 做全量文件审计 | 否 | 否 |
| `_apply_cli.py promote` | hash 对账、目标目录原子 promote、正式 post audit | 否 | 是，必须 `--confirm-lake-write` |

`stage-source` 是整个历史 Bootstrap 唯一允许读取 `TUSHARE_TOKEN`、构造 `TushareResource` 的入口。其它命令有静态门禁禁止引入 Tushare 依赖。窗口完成标准为 Parquet 和 sidecar 同时存在，且 scope/date/source plan fingerprint、字段、内容 hash 全部匹配；续跑只请求缺失窗口。

首版报告 `/private/tmp/major_index_mins_p6_dry_run_20260805.json` 只作为旧边界和 OHLC 源事实证据，不得作为 P7 放行报告。

## 27. P7 Source Staging 执行与阻断结果

经批准执行 `stage-source --confirm-source-request` 后，`/Volumes/datasource/data_lake_staging/major_index_mins_p7_20260805` 已完整保留 2,662 个 source windows。报告 `/private/tmp/major_index_mins_p7_source_stage_20260805.json` 记录：2,662 次请求、2,662 页、0 重试、10,016,287 行、约 432 MB、约 78 分钟；窗口 Parquet/sidecar/hash 均完整，正式 lake 和 Dagster event 写入均为 0。后续禁止重新执行全量 source request，所有审计和构建必须复用该 staging。

审计 SQL 已将 `exchange IS NULL` 和字符串 `nan` 都计为身份异常，并增加回归测试。修正后的 `/private/tmp/major_index_mins_p7_source_staging_audit_20260805_v2.json` 结论如下：

| 项 | 结果 |
| --- | ---: |
| complete / missing / invalid windows | 2,662 / 0 / 0 |
| actual / static expected rows | 10,016,287 / 10,022,855 |
| row-count mismatch windows | 71 |
| duplicate keys | 0 |
| exchange NULL 或 `nan` | 1,220,046 |
| negative volume/amount rows | 5 |
| missing / extra session timestamps | 7,310 / 742 |
| `09:30 high=low=0` sentinels | 30 |
| 其它 OHLC envelope 异常 | 105 |
| staging residuals | 0 |

详细只读拆分 `/private/tmp/major_index_mins_p7_source_anomaly_breakdown_20260805.json`
和 P7C 复核报告 `/private/tmp/major_index_mins_p7c_contract_audit_20260806.json`
已确认：5 个负值均为 `899050.BJ / 2023-07-11 15:30` 的五频同源异常；30 个
哨兵均为 `2022-02-07` 六只上证指数的五频开盘行；其它 OHLC 异常实际为 105 行，
全部集中于 `399001.SZ / 2016-12-16..2017-01-25 / 09:30`。旧文档中的 75 是把
30 行 sentinel 从已互斥的 other-OHLC 统计中再次扣除，现已纠正。`899050.BJ` 的 1min
实际起点为 `2022-12-15`，而其它频率从 `2022-11-21` 开始；`2024-10-30` 的 BSE
5/30/60min 是与 1min 逐字段完全一致的错误一分钟网格。

P7B 的 130 个非北证缺口已经完成 bounded Silver fallback。P7C 已完成：北证50只在
Raw 保存源事实，Silver 所有频率固定排除；因此 BSE availability、错误网格和负值不再
需要 Silver repair。非北证 OHLC 与 exchange 清洗已按第 29 节实现并通过真实样本。
该段审计完成时只放行了 P7D `build-temp`；后续 P7E promote 和 P8 事件补录已分别获得
批准并完成，实际结果见第 31、32 节。

## 28. P7B 非北证历史 Silver fallback 代码级设计

### 28.1 当前代码事实与改动边界

CodeGraph 和源码审计确认：

- `build_temporary_lake_from_staging()` 当前先调用
  `_write_temporary_raw_partition()`，再逐频调用
  `write_major_index_mins_silver_partition()`；
- `_write_temporary_raw_partition()` 和普通 Silver writer 当前都按旧
  `effective_codes_for_date()` 要求完整 code/session，因此不能表达“Raw 忠实保留源缺口、
  Silver 在白名单内补洞”；
- `validate_major_index_mins_relation()` 同时被普通 writer、asset check、readiness 和
  Bootstrap 使用。P7B 禁止全局放宽它，否则会把历史例外带入日常自动链路；
- 现有 `assets/index_mins_silver_repair.py` 已证明“精确 source-empty scope + DuckDB
  set-based 聚合 + staging 全验收 + 原子替换 + `vwap=NULL`”可行。P7B 参考其事务和
  完整窗口语义，但使用 `major_index_mins` 自己的合同、session 和路径，不直接耦合旧
  `index_mins` 数据集；
- P7B 不修改 Raw/Silver asset、job、sensor、check、lake readiness、run key 或 cursor。

### 28.2 版本化 fallback 规则

修改：

```text
src/orchestrator/defs/run_contracts/major_index_mins.py
```

新增不可变合同：

```python
@dataclass(frozen=True, slots=True)
class MajorIndexMinsHistoricalFallbackRule:
    trade_date: str
    target_freq: str
    source_freq: str
    target_codes: tuple[str, ...]
    reason_code: str

MAJOR_INDEX_MINS_NON_BSE_FALLBACK_REVISION = (
    "major_index_mins_non_bse_fallback_v1"
)
MAJOR_INDEX_MINS_NON_BSE_FALLBACK_RULES: tuple[
    MajorIndexMinsHistoricalFallbackRule, ...
]

def major_index_mins_historical_fallback_rule(
    *, trade_date: str, target_freq: str
) -> MajorIndexMinsHistoricalFallbackRule | None: ...

def major_index_mins_historical_fallback_fingerprint() -> str: ...
```

代码集合固定为：

```python
LEGACY_FIVE = (
    "000001.SH", "000016.SH", "000300.SH", "000905.SH", "399001.SZ",
)
SEPTEMBER_2010_SIX = LEGACY_FIVE + ("399006.SZ",)
OCTOBER_2024_NINE = (
    "000001.SH", "000016.SH", "000300.SH", "000510.SH", "000688.SH",
    "000852.SH", "000905.SH", "399001.SZ", "399006.SZ",
)
CURRENT_NON_BSE_TEN = (
    "000001.SH", "000016.SH", "000300.SH", "000510.SH", "000680.SH",
    "000688.SH", "000852.SH", "000905.SH", "399001.SZ", "399006.SZ",
)
```

精确 15 条规则：

| trade date | target/source | codes |
| --- | --- | --- |
| `2009-05-05` | `15min <- 5min` | `LEGACY_FIVE` |
| `2009-06-05` | `15min <- 5min` | `LEGACY_FIVE` |
| `2009-12-04` | `15min <- 5min` | `LEGACY_FIVE` |
| `2010-09-02` | `5min <- 1min` | `SEPTEMBER_2010_SIX` |
| `2024-10-30` | `15min <- 5min` | `OCTOBER_2024_NINE` |
| `2025-07-04` | `30min <- 5min`、`60min <- 5min` | `CURRENT_NON_BSE_TEN` |
| `2025-07-11` | `15min <- 5min`、`30min <- 5min`、`60min <- 5min` | `CURRENT_NON_BSE_TEN` |
| `2025-07-18` | `30min <- 5min`、`60min <- 5min` | `CURRENT_NON_BSE_TEN` |
| `2025-07-25` | `60min <- 5min` | `CURRENT_NON_BSE_TEN` |
| `2025-08-01` | `30min <- 5min`、`60min <- 5min` | `CURRENT_NON_BSE_TEN` |

模块加载/单测必须拒绝：重复 `date+target_freq`、`.BJ` 代码、target/source 非允许映射、
代码不在当日 `effective_raw_request_codes_for_date()`、空代码集合和非 ISO 日期。规则只能修改代码并
更新 revision/fingerprint，不能由 env、CLI 或报告动态扩大。

### 28.3 新 Bootstrap helper

新增纯模块：

```text
src/orchestrator/defs/bootstrap/major_index_mins_silver_fallback.py
```

禁止 Dagster decorator、Tushare/Prod resource 和 instance/event API。接口固定为：

```python
@dataclass(frozen=True, slots=True)
class MajorIndexMinsFallbackWriteResult:
    trade_date: str
    target_freq: str
    source_freq: str
    target_codes: tuple[str, ...]
    source_row_count: int
    output_row_count: int
    expected_output_row_count: int
    source_revision: str
    rule_fingerprint: str
    target_path: str
    elapsed_ms: float

def validate_major_index_mins_fallback_source(
    *, connection, source_relation_sql: str,
    rule: MajorIndexMinsHistoricalFallbackRule,
) -> MajorIndexMinsFallbackSourceValidation: ...

def build_major_index_mins_fallback_relation(
    *, connection, source_relation_sql: str,
    rule: MajorIndexMinsHistoricalFallbackRule,
) -> str: ...

def write_major_index_mins_fallback_sample(
    *, staging_root: Path, output_root: Path,
    date_plan: MajorIndexMinsDatePlan,
    source_plan: MajorIndexMinsSourcePlan,
    duckdb_resource: DuckDBResource,
    rule: MajorIndexMinsHistoricalFallbackRule,
    run_id: str,
) -> MajorIndexMinsFallbackWriteResult: ...
```

P7B 样本输出不得写入正式 Silver 路径，固定写到：

```text
<output_root>/_major_index_mins_fallback/
  revision=<fallback_revision>/
    target_freq=<freq>/trade_date=<date>/part-000.parquet
```

source path 由 `MajorIndexMinsDatePlan + MajorIndexMinsSourcePlan +
source_window_parquet_path()` 计算，只读取已有窗口 Parquet。禁止扫描 staging 目录猜路径，
禁止重新调用 source fetcher。

### 28.4 Source validation 和聚合 SQL

每条规则只校验其 `target_codes`，不把 BSE 或同日其它未决代码带入 P7B：

1. 读取目标日期和 `source_freq` 对应的 retained source windows；
2. 只投影 11 个合同字段，并过滤 `trade_date + target_codes + source_freq`；
3. `exchange` 不信任源端 NULL/`nan`，仅在 Silver relation 中按 `ts_code` 后缀派生
   `XSHG/XSHE`；Raw/source staging 不改；
4. 校验 `(ts_code, trade_time)` 唯一、代码集合 exact、source session grid exact、数值
   可计算、OHLC 合法；
5. 对排序后的 source 内容计算稳定 `source_revision`；
6. 任一 source 时间点缺失、额外、重复或非法，在写 staging 前失败。

target window 由 `major_index_mins_session_times()` 生成。SQL 先建立
`fallback_target_windows(target_time, window_start, expected_source_count)`：

- `09:30` 只消费同一代码的 `09:30` 一行；
- 其余窗口使用 `(window_start, target_time]`；
- `1min -> 5min` 每个普通窗口必须 5 行；
- `5min -> 15/30/60min` 每个普通窗口分别必须 3/6/12 行；
- 午休前后分窗，禁止跨午休或跨日期聚合。

聚合 SQL 固定为：

```sql
SELECT
  ts_code,
  '<target_freq>'::VARCHAR AS freq,
  target_trade_time AS trade_time,
  arg_min(open, trade_time)::DOUBLE AS open,
  arg_max(close, trade_time)::DOUBLE AS close,
  max(high)::DOUBLE AS high,
  min(low)::DOUBLE AS low,
  sum(vol)::DOUBLE AS vol,
  sum(amount)::DOUBLE AS amount,
  max(derived_exchange)::VARCHAR AS exchange,
  NULL::DOUBLE AS vwap
FROM windowed
GROUP BY ts_code, target_trade_time
HAVING count(*) = max(expected_source_count)
```

结果必须满足：

```text
expected_output_rows = len(target_codes) * len(target_session_times)
```

同时检查 exact key set、target session、OHLC envelope、非负 vol/amount 和 `vwap IS
NULL`。P7B 不对成交量/成交额做近似相等放宽；健康对照中的微小跨频差异只是说明
fallback 与源站 native 的精度可能不同，不影响由细频求和的确定性输出。

`2010-09-02` 的 `1min -> 5min` 必须在 metadata 中写
`source_mode=derived_fallback` 和 `reason_code=native_5min_source_empty`。对照中存在 26
个 OHLC mismatch，因此不得把 fallback 标记为 native-equivalent。

### 28.5 Staging、回读与失败原子性

每条规则使用唯一 staging 文件：

```text
.<part-000.parquet>.<run_id>.<uuid>.tmp
```

执行顺序固定：source validation -> aggregate -> output validation -> `COPY` -> Parquet
回读 -> schema/row/key/session/domain 再验证 -> 目标冲突复查 -> `os.replace()`。任何异常
删除本次临时文件，不删除/覆盖已有目标。P7B 样本目标已存在且 hash/合同相同可 skip；
已存在但不同则 fail closed。

一批 15 条规则执行时，先把全部结果写到独立 run root；任一规则失败，整批报告
`should_stop=true`，不得把该目录解释为完整临时 Silver lake。报告至少包含：

```text
fallback_revision
rule_fingerprint
rule_count
expanded_scope_count
source_partition_count
source_row_count
output_row_count
source_revision_by_rule
elapsed_ms
duckdb_connection_count
source_request_count
dagster_event_query_count
failure_samples
```

### 28.6 P7D full builder 的后续接入点

P7B 不直接修改 `build_temporary_lake_from_staging()` 的正式执行路径。P7C 合同完成后，
P7D 才按以下顺序改造：

1. source staging audit 分开报告 `transport_ready` 和 `business_contract_ready`；不能把
   transport 完整误写成业务完整；
2. Raw 临时文件只保存 source fact，不把 fallback 行 union 到 Raw；非北证使用 P7B
   source-empty 规则校验 expected grid，北证50只做结构安全校验；
3. 对 Silver 原生频率先过滤全部 BSE 行，再取非北证 native rows，排除 fallback rule
   的 target codes，最后 `UNION ALL` 对应 fallback rows；
4. union 后使用 Silver 专用严格 validator 和 `effective_silver_codes_for_date()` 校验
   完整日期分区；不得继续用 Raw/Silver 共用的旧 validator 语义；
5. 15/30/60min 完成后再生成 90/120min；
6. 完整 expected file set（当前静态计划仍为 51,252 个，排除 BSE 行不减少分区文件）及 provenance
   对账通过后，才允许进入 P7E promote。

不得在普通 `write_major_index_mins_silver_partition()` 中加入“发现缺口便自动 fallback”
逻辑，也不得让 check/readiness 从报告猜测历史例外。

### 28.7 测试和静态门禁

新增：

```text
tests/test_major_index_mins_historical_fallback.py
```

并扩展：

```text
tests/test_major_index_mins_bootstrap.py
tests/test_run_contract_static_gates.py
```

测试必须覆盖：

- 15 条规则 fingerprint 稳定，展开恰好 130 个非北证 scope；
- 未知日期/频率、`.BJ`、规则外 code、日期范围扩大全部拒绝；
- 完整 1min 生成每代码 49 条 5min；
- 完整 5min 生成每代码 17/9/5 条 15/30/60min；
- 09:30 单行窗口、午休边界、open/close/high/low/vol/amount literal fixture；
- source 缺行、额外时间、重复 key、错误 code/freq/date、非法 OHLC/负值全部在写前失败；
- 输出 `vwap` 全 NULL，exchange 由 code 派生；
- 全部 staging 通过前不替换目标，失败后无残留；
- 规则外目标不产生任何行；
- 模块不得导入/调用 `TushareResource`、Dagster instance/event API，不得出现
  asset/job/sensor decorator；
- 普通 writer/check/readiness 的 exact contract 回归测试保持不变。

### 28.8 性能门禁

P7B 处理 15 个日期/频率规则、130 个 code scope，但只有 10 个唯一 finer-source
`date + freq` 分区：`2010-09-02/1min` 和 9 个 `date/5min`。实现应在同一 DuckDB
connection 中把每个唯一 source partition 物化为一次临时 relation，并由同日多条规则
复用；禁止为每个代码或每个 target frequency 重复读取 source window 文件。

| 指标 | 门禁 |
| --- | --- |
| Tushare / Prod 请求 | 0 |
| Dagster event history | 0 |
| DuckDB connection | 整批 1 个 |
| source 深扫 | 每个唯一 `date+freq` 最多 1 次业务扫描 |
| Python 行循环 | 0；只做规则/路径/报告汇总 |
| 目标规则 | 15 |
| 展开 code scope | 130 |
| 本机临时样本总耗时 | 目标 <= 30 秒；超限停止并优化 SQL/复用，不放宽语义 |
| 内存 | 只保留 DuckDB relation 和有限报告，不加载全历史 DataFrame |

### 28.9 修正后的下一步

1. [已完成] 实现 28.2-28.7 的合同、helper、测试和静态门禁；未写正式 lake；
2. [已完成] 从 retained staging 执行 P7B 全量临时重建，生成专项报告；
3. [已完成] P7C 只读审计并冻结“BSE Raw-only、Silver 排除、非北证异常精确清洗”；
4. [已完成] 实现 P7C 合同并通过 retained-staging 真实临时样本；
5. [已完成] 执行 P7D 完整临时湖构建与全量对账；
6. [已完成] P7E 正式 promote 与正式 lake post audit；
7. [已完成] P8 全量 materialization、最近 20 日 check event 和分区归属验收；
8. [下一步] P9 手动启用 sensor 并观察连续交易日。

P7B 实现结果：版本化合同固定 15 条规则、130 个非北证 scope 和 10 个唯一低频源分区；
纯 Bootstrap helper 只读取 `MajorIndexMinsSourcePlan` 指定的 retained source path，使用
DuckDB set-based 完整窗口聚合、staging 回读、目标冲突保护和原子替换。17 项专项测试及
165 项完整 `major_index_mins`/static-gate 回归通过；本地完整 15 规则 synthetic fixture
在 30 秒门禁内通过，整批只建立 1 个 DuckDB connection，源请求和 Dagster event history
查询均为 0。retained-staging 真实执行进一步读取 5,072 行源数据、生成 15 个 Parquet
共 1,482 行，耗时 `2763.991ms`；10 个 source revision 与 10 个逻辑源分区一致。独立
post-audit 确认 schema、主键、日期/频率、代码集合、值域、`vwap` 和临时残留违规均为
0。报告为 `/private/tmp/major_index_mins_p7b_fallback_report_20260806.json`，输出根为
`/private/tmp/major_index_mins_p7b_fallback_20260806`。当前没有授权完整临时湖、正式
lake、Dagster event 或 sensor 动作。

## 29. P7C Raw-only BSE 与非北证 Silver 清洗代码级合同

### 29.1 只读事实和最终拍板

P7C 只读扫描复用 2,662 个 retained source windows，共 10,016,287 行，耗时约
44.6 秒，Tushare 请求、Dagster event query、正式 lake/DB 写入均为 0。报告固定为：

```text
/private/tmp/major_index_mins_p7c_contract_audit_20260806.json
```

事实如下：

- BSE 有 72 个 source session 异常 scope，其中 48 个可由低频重建、24 个无足够源；
- 另有 `2023-07-11 15:30` 五频负 vol/amount，共 5 行；
- `2024-10-30` BSE 5/30/60min 均返回 271 行，时间和全部字段与 1min 逐行一致；
- 非北证有 30 行开盘 `high=low=0` sentinel；
- 非北证还有 105 行 OHLC envelope 异常，不是旧文档写的 75 行；
- `exchange` 为 NULL/`nan` 共 1,220,046 行。

管理员最终拍板：BSE 不值得继续承担 Silver 修复、完整性检查和事件成本。北证50只作为
Raw source fact 保存；Silver 所有七频固定排除 `899050.BJ`。不实现 BSE fallback、
availability table、repair helper、repair job、repair sensor 或专属 check。

### 29.2 Scope 函数与消费者清零

在 `defs/run_contracts/major_index_mins.py` 中实现并全量迁移：

```python
MAJOR_INDEX_MINS_RAW_SOURCE_CODES = MAJOR_INDEX_MINS_CODES
MAJOR_INDEX_MINS_SILVER_EXCLUDED_CODES = ("899050.BJ",)

def effective_raw_request_codes_for_date(trade_date: str) -> tuple[str, ...]: ...

def effective_silver_codes_for_date(trade_date: str) -> tuple[str, ...]: ...

def raw_scope_hash_for_partition(trade_date: str, freq: str) -> str: ...

def silver_scope_hash_for_date(trade_date: str) -> str: ...
```

消费者必须覆盖：Raw writer、Silver writer、Raw/Silver check、batch readiness、Bootstrap
plan/build/audit、asset metadata、测试和文档。旧 `effective_codes_for_date()` 和
`source_scope_hash_for_date()` 的生产消费者必须清零，不保留 fallback alias。

CodeGraph 当前影响面进一步锁定为：旧 scope 直接影响 run contract、fallback rule/hash
和 fallback contract tests；共享 `validate_major_index_mins_relation()` 影响
`major_index_mins_silver_writer.py`、Silver asset、`major_index_mins_checks.py`、
`major_index_mins_lake_readiness.py`、Bootstrap plan/apply、Silver fallback 及其专项测试。
P7C 必须一次迁移这组消费者，不允许只改 writer 后让 check/readiness 继续使用旧的
Raw/Silver 共用语义。

`effective_silver_codes_for_date()` 只按各指数 source start/end 计算后固定排除 BJ，
不接收 frequency 参数。P7B 已保证非北证历史缺口在 Silver 被补齐，因此 Silver 不再
需要“日期 + 频率 expected code set”。

### 29.3 Raw validator 和 check

拆分当前共享 validator：

```python
validate_major_index_mins_raw_relation(...)
validate_major_index_mins_silver_relation(...)
```

Raw validator 分两层：

1. 全文件结构安全：schema、允许代码、freq、partition date、非空 identity、唯一主键；
2. 非北证 source completeness：按标准 session grid，并精确减去 P7B 已发布的
   non-BSE source-empty target scope。

Raw validator 对 `899050.BJ` 明确不执行：

- expected code coverage；
- missing/extra session grid；
- OHLC envelope；
- vol/amount 非负；
- exchange 与代码后缀一致。

BSE 原始行不删除、不修改、不补造；无返回时 Raw 文件只含其它指数。Raw core check 仍是
每个 Raw asset 一条，北证50没有单独 check。schema、分区和全文件 duplicate key 属于
Parquet 级安全规则，不能按 BSE 行移除。

### 29.4 Silver writer 和异常白名单

Silver relation 第一步固定过滤：

```sql
WHERE upper(trim(ts_code)) <> '899050.BJ'
```

随后完成：

1. `exchange` 不读取源值，按 `.SH -> XSHG`、`.SZ -> XSHE` 派生；
2. P7B 非北证 fallback 与 native rows 做 exact-scope union；
3. 只在以下精确历史白名单修正 OHLC；
4. 未命中白名单的任何 OHLC/domain 异常继续 fail closed；
5. 90/120min 只从已排除 BSE 且已通过严格校验的 30/60min Silver 派生。

开盘 sentinel 规则：

```text
trade_date = 2022-02-07
codes = 000001.SH, 000016.SH, 000300.SH, 000688.SH, 000852.SH, 000905.SH
freqs = 1min, 5min, 15min, 30min, 60min
trade_time = 09:30:00
predicate = high = 0 AND low = 0 AND open > 0 AND close > 0
rewrite = high greatest(open, close); low least(open, close)
```

深证成指 envelope 规则：

```text
code = 399001.SZ
trade_time = 09:30:00
5min dates = 2016-12-16..2017-01-25 的 27 个已审计交易日
15/30/60min dates = 同集合排除 2017-01-04，共各 26 个日期
predicate = high < greatest(open, close, low)
         OR low > least(open, close, high)
rewrite = high greatest(high, open, close); low least(low, open, close)
```

开盘四价全零替换规则（cleanup revision v2）：

| 交易日 | 代码 | 频率 | 09:30 替换价 |
| --- | --- | --- | ---: |
| 2016-10-10 | `000016.SH` | 15min | 2187.652 |
| 2017-11-29 | `000001.SH` | 5/15/30/60min | 3335.567 |
| 2017-11-29 | `000016.SH` | 5/15/30/60min | 2905.331 |
| 2017-11-29 | `000300.SH` | 5/15/30/60min | 4061.355 |
| 2017-11-29 | `000852.SH` | 5/15/30/60min | 7176.156 |
| 2017-11-29 | `000905.SH` | 5/15/30/60min | 6293.246 |

这 21 行必须同时满足 `open = close = high = low = 0` 才允许命中；命中后四价都写为表中
已经由 Tushare 当前 1min、同日其它频率和本地 Raw 1min 交叉验证的 09:30 集合竞价价。
Raw 保留 Tushare 原始返回，Silver 的 `vol/amount/vwap` 也保持原值。代码、日期、频率、
时间或零值形态任一不匹配时不得替换。Silver post-validation 要求四价严格 `> 0`，未知
零值继续 fail closed。

实现中的日期集合必须以显式 tuple 和 revision/fingerprint 固定，不得把范围内未来新增
日期自动视为合法。修正后的输出仍执行未放宽的 Silver schema、exact code/session、
主键、OHLC、非负数值和 exchange 校验。

### 29.5 Check、readiness 和性能门禁

Check 数量保持不变：

| 层 | asset 数 | 每 asset check | 每交易日 check event 上限 |
| --- | ---: | ---: | ---: |
| Raw | 5 | 1 个合并 core check | 5 |
| Silver | 7 | 1 个合并 core check | 7 |
| 合计 | 12 | 禁止按代码/字段/规则拆分 | 12 |

每年约 3,000 条 event，且只保留治理策略规定的最近窗口，不构成高基数风险。每条 check
只扫描一个当日 Parquet；禁止为了排除 BSE 增加额外 query、check 或 event。

Readiness 必须分别复用 Raw/Silver validator 语义：Raw 的 BSE 源异常不阻断，Silver
date-only output scope 永不包含 BSE。日常最近 10 日热路径仍使用一次 DuckDB connection、
批量扫描，event history/Tushare/Prod DB 调用为 0。

### 29.6 测试与 P7D 进入条件

新增或修改测试必须覆盖：

- Raw 在 BSE 完整、空结果、部分 grid、错误一分钟 grid、负成交值时都原样保存；
- Raw 对同样异常的非北证未知 scope 继续失败；
- Silver 所有七频、所有日期均不输出 `899050.BJ`；
- Silver check/readiness 的 expected code count 不包含 BSE；
- P7B 130 个非北证 fallback scope 不回退；
- 30 行 sentinel 和 105 行 envelope 精确命中并通过严格 post-validation；
- 21 行开盘四价全零替换精确命中，四价使用冻结值且 `vol/amount/vwap` 不变；
- 白名单外相同形态异常不允许被自动修正；
- `exchange` 全部由代码后缀派生；
- definitions 仍只有 12 条 core check，不出现 BSE 专属 check；
- 单日 check 扫描 12 个文件、最多 12 条 event，不增加逐代码 DuckDB 查询；
- 完整 retained-staging 临时构建保持 0 次 Tushare、0 次 Dagster event history。

P7C 代码与真实临时样本全部通过后，才允许执行 P7D 完整临时湖。P7D 仍不等于正式
promote；P7E 的正式 lake 写入需要单独批准。

### 29.7 实现与真实样本验收

P7C 已完成以下实现：

- 删除旧 `effective_codes_for_date()` / `source_scope_hash_for_date()`，所有生产消费者迁移
  到 Raw/Silver 分层 scope 和 hash；
- 拆分 `validate_major_index_mins_raw_relation()` 与
  `validate_major_index_mins_silver_relation()`；
- Raw validator 对 BSE 只执行文件结构安全规则，对非北证继续执行严格 session/domain
  规则，并精确放行 P7B source-empty scope；
- Silver writer 固定先排除 `899050.BJ`，再按 135 行既有 OHLC 白名单和 21 行开盘价
  替换白名单修正 OHLC，并按代码后缀派生 exchange；
- check、10 日 batch readiness、Bootstrap plan/build/audit 和 fallback validator 已迁移到
  同一套分层语义；check 数仍为 Raw 5 + Silver 7，没有新增事件类型。

本地回归共 `169 passed`。真实样本复用 retained staging，报告为：

```text
/private/tmp/major_index_mins_p7c_retained_staging_sample_20260806_v2.json
```

验收结果：

| 项目 | 结果 |
| --- | ---: |
| retained source 集合扫描 | 5 次，每个原生频率 1 次 |
| 临时 Raw / Silver 分区 | 119 / 121 |
| 总耗时 | 22,466.261 ms |
| Raw BSE 事实行 | 1,445 |
| Raw BSE 负 vol/amount | 5，全部保留 |
| Raw BSE 错误 1min 网格事实 | 813，全部保留 |
| Silver BSE 行 | 0 |
| Raw sentinel / envelope | 30 / 105，精确命中 |
| Silver 未清理 sentinel / envelope | 0 / 0 |
| Silver exchange 错误 | 0 |
| Silver code scope 差异 | 0 |
| Tushare / Dagster event query | 0 / 0 |
| 正式 lake / Dagster DB/event 写入 | 0 / 0 |

首次 v1 样本按门禁停止于 `2024-10-30 / 15min`：该 scope 本来就是 P7B 已发布的
source-empty 目标，不能冒充 P7C 原生样本。v2 保留该日 1/5/30/60min 的 BSE 原始事实
验证；15min 继续由 P7B fallback 专项覆盖。该停止证明边界按设计 fail closed，不是新的
数据缺口。

P7C 验收完成，P7D 已按第 30 节执行并通过；P7E 已按第 31 节执行并通过。

## 30. P7D 完整临时 Raw/Silver 构建与全量对账

### 30.1 实现收口

P7D 对 `major_index_mins_bootstrap_apply.py` 的临时构建路径做了以下收口：

1. source staging audit 显式拆分 `transport_ready` 与 `business_contract_ready`。只有窗口
   缺失、损坏、sidecar 行数/hash 不一致或 staging 残留属于 transport 阻断；历史源业务
   异常继续保留 reason code，由 P7B/P7C 的精确合同处理，不能伪装成源数据天然健康；
2. Raw 逐日期、逐原生频率保存源事实。精确 source-empty scope 允许合法 0 行 Raw，
   未发布的 0 行分区继续 fail closed；
3. 15 条发布 fallback 规则先生成独立、带 revision 的临时样本。Silver 原生频率只在
   显式 Bootstrap 入口合并对应 fallback，普通日常 writer 不具备自动 fallback 能力；
4. Silver 原生五频完成后再生成 90m/120m，全部输出排除 `899050.BJ`；
5. 串行构建复用一个 DuckDB connection，但每个目标文件仍使用独立 staging、回读验证
   和原子替换；
6. build report 是原子 checkpoint。中断后只允许按冻结 date/source fingerprint 的
   确定性前缀续跑，并检查 checkpoint 对应文件存在；最终完整 `audit-temp` 仍是硬门禁，
   checkpoint 不能替代内容验收。

这些改动不创建 asset/job/sensor/check，不访问 Dagster instance，不增加 Tushare 请求，
也不允许 `build-temp` 接收正式 lake root 作为 promote 入口。

### 30.2 正式执行命令与边界

P7D 使用：

```bash
uv run python -m \
  orchestrator.defs.bootstrap.major_index_mins_bootstrap_apply_cli build-temp \
  --calendar-lake-root /Volumes/datasource/data_lake \
  --staging-root /Volumes/datasource/data_lake_staging/major_index_mins_p7_20260805 \
  --end-date 2026-08-04 \
  --confirm-staging-write \
  --output /private/tmp/major_index_mins_p7d_temporary_lake_build_20260806.json

uv run python -m \
  orchestrator.defs.bootstrap.major_index_mins_bootstrap_apply_cli audit-temp \
  --calendar-lake-root /Volumes/datasource/data_lake \
  --staging-root /Volumes/datasource/data_lake_staging/major_index_mins_p7_20260805 \
  --end-date 2026-08-04 \
  --output /private/tmp/major_index_mins_p7d_temporary_lake_audit_20260806.json
```

日期计划仍为 4,271 个交易日，fingerprint 为
`c77aabafa4943a1efc03e3829732c0ef4d5c38ed277bcffcf39867e5ee5c4a67`；source plan
fingerprint 为 `c587ad88725aa4f188e4604294c12f3a03febf2cb82fe877db923a7a23914688`。
本轮未执行 Tushare 请求、`dg launch`、sensor tick、runless event、dynamic partition 或
正式 lake promote。

### 30.3 构建与全量审计结果

| 项目 | 结果 |
| --- | ---: |
| Raw files | 21,355 / 21,355 |
| Raw rows | 10,016,287 |
| Raw bytes | 472,820,318 |
| Silver files | 29,897 / 29,897 |
| Silver rows | 9,917,572 |
| Silver bytes | 486,056,568 |
| fallback rules / rows | 15 / 1,482 |
| Raw missing / invalid | 0 / 0 |
| Silver missing / invalid | 0 / 0 |
| Silver distinct codes | 10 |
| Silver `899050.BJ` rows | 0 |
| staging residual | 0 |
| Tushare / Dagster event query | 0 / 0 |
| 正式 lake / Dagster DB/event 写入 | 0 / 0 |

完整 build 报告耗时 `8,288,855.894ms`。其中已有 19,212 个 Raw 文件通过 checkpoint
复用，本次补写 2,143 个 Raw 文件；Silver 29,897 个文件全部在本轮生成。完整 target
audit 对 Raw 和 Silver 分别耗时 `3,125,247.198ms` 与 `3,235,248.205ms`，合计约
106 分钟。它是开发期一次性深审计，禁止进入 sensor/readiness 日常热路径，也不应在
P7E 无条件重复；P7E 应复用本报告并在 promote 后执行针对正式目标的必要 post audit。

source staging 最终为 `transport_ready=true`、`business_contract_ready=false`。后者保留
`source_expected_row_count_mismatch`、identity/numeric/session/OHLC 等历史源事实，不是
P7D 失败：这些异常已经由 Raw-only BSE、精确 OHLC 清洗和发布 fallback 合同处理，并由
51,252 个目标文件的严格 validator 逐一验收。未知范围异常仍会 fail closed。

### 30.4 阶段结论

P7D 已完成。临时湖在冻结计划下文件、行数、schema、分区、主键、代码范围、session、
值域和 fallback provenance 全部通过。P7E 已按第 31 节完成，P8 已按第 32 节完成；
P9 sensor 启用仍未执行，必须单独批准。

## 31. P7E 正式 lake promote 与 post audit

### 31.1 Preflight 与写入边界

正式执行前确认：

- P7D build/audit 报告的 date/source fingerprint、51,252 个目标计数和零正式写入一致；
- P7D audit 后 Raw/Silver 临时文件变化数为 0；
- 正式 Raw/Silver 目标文件数均为 0；
- Dagster active runs 为 0，三个主要指数分钟线 sensor 没有运行态记录；
- `/Volumes/datasource` 可用空间约 2.3 TiB；
- 没有其它 major-index-mins Bootstrap/promote 进程。

P7E 只允许 `_copy_atomic()`：源文件复制到目标目录内唯一 `.tmp`，校验 source/target
size 和 SHA-256 后 `os.replace()`。中途失败不删除已成功目标；重跑时仅允许 hash 完全
相同的目标复用，任何差异都 fail closed。P7E 不调用 Dagster instance，不写 event、run
或动态分区。

### 31.2 执行结果

正式报告：

```text
/private/tmp/major_index_mins_p7e_formal_lake_promote_20260806.json
```

| 项目 | 结果 |
| --- | ---: |
| Raw promoted / reused | 21,355 / 0 |
| Raw post-audit files / rows / bytes | 21,355 / 10,016,287 / 472,820,318 |
| Silver promoted / reused | 29,897 / 0 |
| Silver post-audit files / rows / bytes | 29,897 / 9,917,572 / 486,056,568 |
| post-audit missing / invalid | 0 / 0 |
| Raw / Silver distinct codes | 11 / 10 |
| Silver `899050.BJ` rows | 0 |
| 正式 target tmp/staging residual | 0 |
| Dagster event/check/partition writes | 0 / 0 / 0 |
| active runs after promote | 0 |
| elapsed | 11,417,256.707ms |

`should_stop=false`，failure samples 为空。正式湖与 P7D 临时湖的文件数、行数和 bytes
逐层完全一致。P7E 完成不代表 Dagster 已识别历史分区；Assets 页面在 P8 前显示 0 个
materialized partitions 属于阶段设计，不得通过手工 job 重跑替代事件补录。

### 31.3 报告复用性能修复

首次 P7E 实际报告显示 `temporary_audit_mode=live_deep_audit`。根因是 CLI 虽然解析了
`--validated-build-report` 和 `--validated-temp-audit-report`，却误把参数传入
`build-temp` 分支，没有传入 `promote_temporary_lake()`。因此本次重复执行了 source 和
temporary target 深审计，总耗时约 190 分钟；这是性能浪费，不是数据正确性失败。

修复后 promote 的 report reuse 门禁同时验证：

1. build report 的 staging root、date/source fingerprint、fallback fingerprint、目标
   计数、`source_transport_ready` 和零正式写入；
2. source plan 的 2,662 个 window parquet 与 sidecar 均存在，且修改时间不晚于 build
   report；
3. target audit 为 ready，Raw/Silver expected/valid 数完全一致，missing/invalid 为 0；
4. 51,252 个临时目标都存在，且修改时间不晚于 target audit report；
5. 两份报告必须同时提供，任何单边参数或报告后变更均 fail closed；
6. 正式目标冲突检查、逐文件 size/hash 和正式 lake 完整 post audit 不得跳过。

新增 CLI 参数转发测试，防止再次出现“命令行参数存在但未进入执行函数”。P7E 已完成，
该修复只服务幂等恢复和后续维护，不触发第二次正式 promote。

### 31.4 阶段结论

P7E 已完成，正式数据湖文件事实已由 P8 采用直写补录模式完成事件登记：全量补
materialization，只对最近 20 个 `cn_major_index_mins_trade_days` 补 core check event，
并验证 event partition 归属；全过程没有运行历史 asset jobs，也没有重新生成已验收的
Parquet。实际实现和验收见第 32 节。

## 32. P8 动态分区与 runless event 补录

### 32.1 实现边界

P8 新增两个非 active definition 模块：

```text
defs/bootstrap/major_index_mins_bootstrap_events.py
defs/bootstrap/major_index_mins_bootstrap_events_cli.py
```

CLI 仅提供以下显式阶段：

```text
dry-run
register-partitions
sample
apply
post-audit
```

`register-partitions` 必须传 `--confirm-partition-write`；`sample/apply` 必须传
`--confirm-event-write`；只读命令拒绝写入确认参数。工具不导入或执行 asset job/sensor，
不写 Parquet，不删除 event，不创建 run。

### 32.2 Preflight 与文件事实门禁

每次计划生成都执行以下有界验证：

1. 从 `/private/tmp/major_index_mins_p6_dry_run_20260805.json` 重建 4,271 日冻结计划，
   fingerprint 必须为
   `c77aabafa4943a1efc03e3829732c0ef4d5c38ed277bcffcf39867e5ee5c4a67`；
2. P7E 报告的正式 lake root、文件数、行数、fingerprint、失败样本必须与当前计划一致；
3. P7D fallback 报告必须精确证明 15 个 Raw source-empty 日期/频率，未知 0 行文件一律
   fail closed；
4. 12 个资产共 51,252 个 expected 文件必须完整，且不得晚于 P7E 报告发生修改；
5. 使用一个 DuckDB connection、12 次 `parquet_file_metadata` 批量查询取得行数，不逐行
   扫描分钟数据；
6. active runs 必须为 0；动态分区必须为冻结日期集合的精确子集，禁止 unexpected key；
7. 已有 materialization 按 asset/date 有界查询；最近 20 日 check 只有在 passed、blocking
   且 target storage id 等于 latest materialization 时才算 ready。

事件 metadata 只保存有限聚合。15 个合法 source-empty Raw 文件写
`source_empty_exempt=true`，不得将其报告成正行数或创建虚假 core check；这 15 个历史
日期不在本次最近 20 日 check 窗口。

### 32.3 写入与归属合同

- 先注册全部 4,271 个 `cn_major_index_mins_trade_days`；
- 每个文件写一条显式 `partition` 的 materialization；
- 只对最近 20 日、12 个资产写 240 条 core check evaluation；
- 每条 check 的 `target_materialization_data.storage_id` 必须指向同一资产、同一分区的
  latest materialization；
- sample 固定从最近 20 日选择一个日期，先验证 12 条 materialization 和 12 条 check；
- full apply 按资产串行，每个资产独立报告，允许幂等续跑；
- 最终 post-audit 必须得到 planned materialization/check 均为 0。

### 32.4 正式执行结果

实际报告：

```text
/private/tmp/major_index_mins_p8_event_dry_run_20260807_v2.json
/private/tmp/major_index_mins_p8_partition_registration_20260807_v2.json
/private/tmp/major_index_mins_p8_event_sample_20260807.json
/private/tmp/major_index_mins_p8_event_sample_post_audit_20260807.json
/private/tmp/major_index_mins_p8_apply_raw_1m_20260807.json
/private/tmp/major_index_mins_p8_apply_raw_5m_20260807.json
/private/tmp/major_index_mins_p8_apply_raw_15m_20260807.json
/private/tmp/major_index_mins_p8_apply_raw_30m_20260807.json
/private/tmp/major_index_mins_p8_apply_raw_60m_20260807.json
/private/tmp/major_index_mins_p8_apply_silver_1m_20260807.json
/private/tmp/major_index_mins_p8_apply_silver_5m_20260807.json
/private/tmp/major_index_mins_p8_apply_silver_15m_20260807.json
/private/tmp/major_index_mins_p8_apply_silver_30m_20260807.json
/private/tmp/major_index_mins_p8_apply_silver_60m_20260807.json
/private/tmp/major_index_mins_p8_apply_silver_90m_20260807.json
/private/tmp/major_index_mins_p8_apply_silver_120m_20260807.json
/private/tmp/major_index_mins_p8_event_post_audit_20260807.json
```

| 项目 | 结果 |
| --- | ---: |
| registered partitions | 4,271 |
| Raw / Silver materializations | 21,355 / 29,897 |
| materializations total | 51,252 |
| Raw / Silver recent checks | 100 / 140 |
| checks total | 240 |
| planned events after post-audit | 0 |
| active runs | 0 |
| formal lake writes | 0 |

最终 post-audit 对每个资产确认 4,271 个 materialization 和最近 20 日 20 条 ready check；
所有 check 均绑定对应 latest materialization，`precondition_errors=[]`、
`should_stop=false`。P8 已完成。下一阶段只剩 P9：手动启用三个 sensor，并观察至少
3 个实际交易日；P8 完成不会自动改变 sensor 默认 STOPPED 状态。

## 33. Raw 缺频率有界自动重试

### 33.1 问题事实与职责边界

2026-08-12 首次 Raw run 的 5m step 因 `399001.SZ` 空响应失败，另外四个频率已经成功。
旧实现存在两个互相叠加的问题：

1. `probe_major_index_mins_source()` 固定只查 `1min 15:00`，无法证明 5m/15m/30m/60m
   已发布；
2. Raw sensor 固定使用 `raw_major_index_mins_update:<trade_date>`，失败 run 已占用该 key，
   后续 tick 虽然继续选择同一 Lake 缺口，却无法创建新的 run。

本节只修复“目标仍缺文件且已有自动 run 失败”的恢复能力。已有正式文件但 core check
失败仍执行原有 `materialized_check_failed` 门禁，禁止自动覆盖。Writer 的 schema、分页、
完整 session、代码覆盖、staging 和 no-overwrite 原子提升合同不变。

### 33.2 代码改动

`defs/run_contracts/major_index_mins.py` 新增：

```text
MAJOR_INDEX_MINS_RAW_AUTO_RETRY_LIMIT = 3
MAJOR_INDEX_MINS_RAW_RETRY_ATTEMPT_SCOPE = "retry"
```

`defs/asset_guards/major_index_mins_source_probe.py`：

1. `probe_major_index_mins_source(..., source_freq="1min")` 接受一个显式原生频率；
2. 仍只探测目标频率 15:00 bar 和 10 个日常指数；
3. result/cursor 增加 `source_freq`，不保存完整代码或行；
4. 每次调用仍使用一个共享 bounded request budget，最多 20 次请求、30 秒，正常路径 10 次；
5. 不允许一次调用扩展为五个频率。

`defs/sensors/major_index_mins_sensor.py`：

1. 对 selected Raw date 只执行一次按 `job_name + dagster/partition` 精确过滤的 runs 查询，
   limit 固定为首次 key 加 3 个 attempt key；不读取 event/check history；同分区若出现不属于
   这 4 个规范身份的人工 run，则按身份冲突 fail closed，禁止自动重试绕过并发 run；
2. 首次 run 仍使用 `build_asset_update_run_key(...)`，source probe 仍为 `1min`；
3. 首次或前次 attempt 处于 `QUEUED/STARTING/STARTED/CANCELING` 时 skip，不重复提交；
4. 前序候选 run 为 `FAILURE/CANCELED`、Lake 仍缺文件且恰好一个原生频率缺失时，探测
   该缺失频率；ready 后使用：

```python
build_repair_attempt_run_key(
    subject="raw_major_index_mins_update",
    repair_scope_id=trade_date,
    attempt_scope="retry",
    attempt=attempt,
)
```

5. 最多自动重试 3 次；耗尽后 `reason_code=raw_retry_exhausted`；
6. 多于一个频率缺失、attempt 身份不连续、已有候选 SUCCESS 但文件仍缺失时 fail closed；
7. cursor 只增加 `run_attempt`、`source_freq` 和有限计数，不写 run 列表、路径或错误报告；
8. 每 tick 仍最多 1 个 RunRequest，Silver/Gold sensor 不变。

### 33.3 性能预算

| 项目 | 正常首次触发 | 单频率恢复 | 拒绝上限 |
| --- | ---: | ---: | ---: |
| DuckDB readiness | 最近 10 日、Raw 50 文件 | 相同 | 不扩大窗口 |
| Lake stat | 0 个额外频率判断 | 5 个目标路径 | 固定 5 |
| Dagster runs 查询 | 1 次精确查询 | 1 次精确查询 | 最多 4 个候选身份 |
| Tushare probe | 10 个 1m 请求 | 10 个缺失频率请求 | 单 tick 最多 20 次含重试 |
| RunRequest | 最多 1 | 最多 1 | 自动 retry 最多 3 次 |
| event/check history | 0 | 0 | 禁止 |

2026-08-13 对 2026-08-12 的真实 5m 只读探针为 10 请求、0 重试、490 行、
`18,855.569ms`。若一次热路径需要探测多个缺失频率，线性放大可能越过 gRPC 预算，因此
多频率缺失明确拒绝自动重试，不允许靠提高 timeout 或 50 请求探针绕过。

### 33.4 测试与静态门禁

1. source probe：默认 1min、显式 5min、错误频率、单代码空响应；每次仍为 10 个代码；
2. Raw sensor：首次 key 不变；一次失败后生成 retry attempt 1；连续失败最多 attempt 3；
3. active run、非规范同分区 run、retry exhausted、多频率缺失、成功 run 与缺文件冲突均不提交；
4. retry 只探测唯一缺失频率；首次仍只探测 1min；
5. run query 固定 job/date/limit，不允许 event/check history；
6. cursor 小于 8KB，不包含完整 runs、代码、路径或 readiness 报告；
7. Silver sensor、job selection、asset/check 数量、默认 sensor 状态保持不变。

2026-08-13 代码与本地验证已完成。Ruff 通过；主要指数分钟线全族、bounded readiness
热路径、cursor、run key、静态门禁和 asset governance 合并回归为 `306 passed`，另有
`384` 个子测试通过。开发过程未执行正式 sensor tick、未创建 run、未写 Lake/Dagster DB；
`dg check defs` 与部署后真实失败重试观察仍属于独立正式验证。

### 33.5 2026-08-12 补数验收

受控补数已按 Raw -> Silver -> Gold 完成。三个成功 run 分别为
`57b24ce4-3924-43e2-9c9b-92f7dd5b1f3c`、
`ba026401-e59d-4d0d-85c5-3df8e124090f`、
`75d75d69-f728-4117-90d0-34466e62aedc`。Raw 五频率、Silver 七频率、Gold 七频率指标和
七个 state 均覆盖 10 个指数，无重复业务键；最终主要指数分钟线资产族缺失数为 0。
