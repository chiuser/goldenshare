# Index Daily Raw By-Date Prod DB Migration Low-Level Design

## 1. 目标

本 LLD 用于把指数日线 raw 层从当前 `raw_tushare_index_daily_by_code[ts_code]` 迁移为 `raw_index_daily[trade_date]`。

核心口径：

- raw 数据源改为 prod core DB 的 `core_serving.index_daily_serving` 只读同步。
- raw 层按交易日分区，路径按 `trade_date` 组织。
- raw 层代码池与 silver 层一致，必须使用冻结后的 Lake 期望 code set；当前实现的 DG 管理集合是 `cn_a_index_ts_codes` dynamic partitions。
- 目标交易日的 prod serving 数据没有完整覆盖冻结后的 Lake 期望 code set 时，不允许发起 Lake 更新。
- raw 只做源镜像和最小归一化，不提前承担 silver 的 `change_amount` 等语义转换。
- 历史 by-date raw 文件正式从远程 prod DB 生成；现有 by-code raw lake 只能作为审计参考，不允许跨区直接复用文件。
- 性能是硬门禁：sensor 热路径不得逐 code 提交 run，不得逐日深扫 Dagster event/check history。

本 LLD 只定义开发方案，不代表已实现。

## 2. 设计修正

相对高层方案，本 LLD 做三个工程级修正：

1. 新正式 job/sensor 使用规范命名：
   - `raw_index_daily_update_job`
   - `raw_index_daily_update_job_sensor`
   - 旧 `index_daily_update_job` 随 `raw_tushare_index_daily_by_code` 删除，不保留别名兼容。

2. 新 raw asset 不再把 `trade_date` 作为 run config 重复传入：
   - `partition_key` 是唯一交易日执行参数。
   - run config 只保留 `source_mode`、`write_mode` 等非分区参数。
   - 避免出现 `partition_key != config.trade_date` 的双日期口径 bug。

3. 新 asset check 名称按长期编码规范使用 `_check` 后缀：
   - 例如 `raw_index_daily_file_exists_check`。
   - 旧 check 名称只作为历史 event 保留，不进入新 readiness。

## 3. 非目标

本专项不做以下事情：

- 不清理 Dagster DB 里的旧 by-code run/materialization/check event。
- 不把 raw 层改成 silver 语义层。
- 不把 Tushare 作为默认正式路径。
- 不在本专项实现 Tushare fallback。
- 不把每个 index code 单独作为 run 单位。
- 不新增 summary asset、readiness asset、manifest、外部状态表。
- 不在 sensor 热路径读取正式 Dagster event history 做补洞判断。
- 不在未完成 runless event 补录前删除旧 by-code 文件。
- 不直接复用旧 Lake by-code 文件生成正式 by-date raw 文件；旧文件只可只读参考、抽样对账。

## 4. 当前代码审计结论

### 4.1 raw asset 与路径

当前入口：

- `lake_console/orchestrator/src/orchestrator/defs/assets/index_daily.py`
  - `raw_tushare_index_daily_by_code`
  - `RAW_TUSHARE_INDEX_DAILY_BY_CODE_SCHEMA`
  - `IndexDailyRawByCodeConfig`
  - `fetch_tushare_index_daily_by_code_to_raw(...)`
- `lake_console/orchestrator/src/orchestrator/defs/paths.py`
  - `raw_index_daily_by_code_path(...)`
  - `raw_index_daily_by_code_staging_dir(...)`

当前 raw 路径：

```text
raw/tushare/index_daily_by_code/ts_code=<TS_CODE>/part-000.parquet
```

问题：

- 物理组织是 by-code，无法高效服务 by-date sensor 与 silver 日分区。
- 每个 run 只处理一个 index code，历史或日常补洞 run 数过多。
- raw asset 名称、schema 名称、path helper 名称都绑定 Tushare 和 by-code。

### 4.2 silver 依赖

当前 `silver_index_daily`：

- 依赖 `raw_tushare_index_daily_by_code`。
- 使用 `AllPartitionMapping()` 从所有 code 分区读原始文件。
- `materialize_silver_index_daily_partitions_from_raw_by_code(...)` 会枚举所有已注册 code 的 raw by-code 文件，再按目标 trade date 聚合。

问题：

- silver 日分区为了一个日期要扫描全 code raw 文件。
- by-date raw 切换后必须改成只读目标日 raw 文件。

### 4.3 raw checks

当前 raw check 都挂在 `raw_tushare_index_daily_by_code` 上：

- `raw_index_daily_by_code_file_exists`
- `raw_index_daily_by_code_row_count_positive`
- `raw_index_daily_by_code_required_columns_and_types`
- `raw_index_daily_by_code_partition_code_matches`
- `raw_index_daily_by_code_unique_ts_code_trade_date`

问题：

- check 语义是 by-code，不适用于 by-date。
- `partition_code_matches` 需要替换为 `partition_date_matches`。
- raw by-date 还需要覆盖 `registered/effective index code coverage`。

### 4.4 raw readiness 与 sensor

当前文件：

- `lake_console/orchestrator/src/orchestrator/defs/sensors/index_daily_raw_file_readiness.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/index_daily_sensor.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/index_daily_late_arrival_repair.py`

当前逻辑：

- `index_daily_sensor` 先做日期注册缺口检查。
- 再调用 `audit_index_daily_raw_gaps(...)` 检查最近窗口内 code/date pair。
- 再用 `select_index_daily_pending_code_runs(...)` 选出多个 code 级 run。
- 单 tick 最多 `MAX_RUN_REQUESTS_PER_TICK = 500` 个 `RunRequest`。
- run key 形如 `index_daily:{trade_date}:{index_code}` 或 repair attempt 变体。

问题：

- 这是 code 级调度模型，不是 date 级 raw asset。
- sensor cursor 有 `next_pending_offset`、`repair_state` 等 by-code 状态，迁移后必须删除。
- 当前 late-arrival repair helper 是 by-code 专用，不应带入新模型。

### 4.5 silver sensor 与 major indices readiness

当前 `silver_index_daily_sensor.py`：

- 依赖 `audit_index_daily_raw_gaps(...)`。
- 依赖 `check_index_daily_raw_files_for_trade_date(...)`。

当前 `asset_guards/market_major_indices_lake_readiness.py`：

- 使用 `raw_index_daily_by_code_path(...)` 拼所有 code raw 文件，再判断 silver readiness。

问题：

- by-date raw 切换后，这两个隐藏消费者必须同步迁移。
- major indices guard 不能继续从 by-code raw 推导 silver 覆盖。

### 4.6 run config 与 readiness registry

当前文件：

- `run_contracts/configs.py`
  - `build_index_daily_raw_op_config(...)`
  - op key `raw_tushare_index_daily_by_code`
- `defs/sensors/readiness.py`
  - `RAW_INDEX_DAILY_BY_CODE_READINESS_SPEC`
  - `raw_index_daily_by_code_ready_for_code(...)`

问题：

- op key、函数名、readiness spec 均绑定 by-code。
- 新模型必须改为 `raw_index_daily` + trade-date readiness。

### 4.7 catalog

当前 `catalog/lake_assets.py` raw index daily entry：

- asset key 是 `raw_tushare_index_daily_by_code`。
- path 是 by-code。
- source system 是 Tushare。
- contract 是 `source_mirror_by_code`。

问题：

- catalog 展示与新事实源冲突。
- 迁移后 entry 必须改成 prod core DB + by-date raw。

### 4.8 prod DB 现有模式

可复用模式：

- `defs/resources.py::ProdPostgresResource`
- `defs/prod_db/stk_mins.py`
- `lake_console/backend/app/services/prod_core_db.py`
- `lake_console/backend/app/sync/strategies/prod_db_trade_date.py`

已确认要求：

- 使用 DuckDB `ATTACH ... (TYPE POSTGRES, READ_ONLY)`。
- remote SQL 禁止 `select *`。
- 禁止读取 `source/created_at/updated_at`。
- SQL 必须有明确日期过滤。
- 不把生产连接串写入日志、cursor、metadata。
- 已有 backend prod-core-db 字段口径为 `change_amount AS change`，并已覆盖 `index_daily/index_weekly/index_monthly` 三张 `core_serving` 白名单表；Dagster LLD 必须对齐该口径，不得另起一套近义字段契约。

### 4.9 prod DB 只读审计事实

2026-06-23 只读审计远程 prod DB：

| 项 | 观测值 |
| --- | ---: |
| `ops.index_series_active(resource='index_daily')` | 1130 个 code |
| `ops.index_series_active(resource='index_daily_raw')` | 3052 个 code |
| `ops.index_series_active(resource='index_mins')` | 530 个 code |
| 本机 Dagster `cn_a_index_ts_codes` dynamic partitions | 946 个 code |
| `core_serving.index_daily_serving` distinct code | 1130 个 |
| `core_serving.index_daily_serving` 日期范围 | `2020-01-02` 到 `2026-06-22` |
| 最近 10 个交易日 serving 当日 code | 每日 1126 个 |
| DG code 与当前 prod serving 4 个缺口交集 | 0 个 |
| DG code 不在 prod serving 全历史中的数量 | 86 个 |
| prod serving 全历史 code 不在 DG 中的数量 | 270 个 |

当前 prod serving 相对 `index_daily` active pool 的缺口：

| ts_code | serving 最后有数日期 | 缺口开始 | 缺口截止 | 缺失交易日数 |
| --- | --- | --- | --- | ---: |
| `480055.CNI` | `2026-05-13` | `2026-05-14` | `2026-06-22` | 27 |
| `480056.CNI` | `2026-05-13` | `2026-05-14` | `2026-06-22` | 27 |
| `480057.CNI` | `2026-05-13` | `2026-05-14` | `2026-06-22` | 27 |
| `931598.CSI` | `2026-05-08` | `2026-05-11` | `2026-06-22` | 30 |

结论：

- 当前 4 个 prod latest serving 缺口不在本机 DG `cn_a_index_ts_codes` 中；若本迁移沿用当前 DG 管理集合，这 4 个缺口本身不阻断 Lake 更新。
- 但 DG 当前有 86 个 code 不在 prod serving 全历史中；prod DB source 尚不能证明覆盖当前 DG 管理集合。
- `index_daily` raw by-date 更新的 code universe 不能凭设计假设为 prod `index_daily` active pool，也不能凭旧 by-code 文件推断；P0 必须冻结 Lake 期望 code set。
- serving 当日不齐备时必须阻断 Lake 更新；阻断口径以冻结后的 Lake 期望 code set 为准。

## 5. 新资产契约

### 5.1 asset

新增正式 raw asset：

```text
raw_index_daily
```

Partition：

```text
cn_a_index_trade_days
```

物理路径：

```text
raw/index_daily/trade_date=<YYYY-MM-DD>/part-000.parquet
```

staging 路径：

```text
_tmp/raw/index_daily/run_id=<RUN_ID>/trade_date=<YYYY-MM-DD>/part-000.parquet
```

删除旧入口后，正式代码中不得再出现：

- `raw_tushare_index_daily_by_code`
- `raw_index_daily_by_code_path`
- `index_daily_by_code`
- `select_index_daily_pending_code_runs`
- `next_pending_offset`

### 5.2 schema

新增 schema 常量：

```python
RAW_INDEX_DAILY_SCHEMA
```

字段保持 raw 源镜像口径：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ts_code` | `VARCHAR` | 指数代码 |
| `trade_date` | `VARCHAR` | `YYYYMMDD` 或规范化后的 raw 字符串日期，raw 层不转 DATE |
| `close` | `DOUBLE` | 收盘 |
| `open` | `DOUBLE` | 开盘 |
| `high` | `DOUBLE` | 最高 |
| `low` | `DOUBLE` | 最低 |
| `pre_close` | `DOUBLE` | 昨收 |
| `change` | `DOUBLE` | 涨跌额，raw 层保留源字段名 |
| `pct_chg` | `DOUBLE` | 涨跌幅 |
| `vol` | `DOUBLE` | 成交量 |
| `amount` | `DOUBLE` | 成交额 |

约束：

- raw 层不得把 `change` 提前改名为 `change_amount`。
- raw 层不得把 `trade_date` 提前转成 `DATE`。
- silver 层继续负责 `change -> change_amount` 和日期类型转换。

### 5.3 source system

新增 source system：

```python
SourceSystem.PROD_CORE_DB = "prod_core_db"
```

catalog ingestion source 不新增近义枚举，优先复用现有：

```python
IngestionSource.PROD_DB_READONLY
```

本专项不引入 Tushare fallback source mode。

## 6. 指数代码集合与源端完整性门禁

禁止新增名为 `effective_index_codes_for_trade_date(...)` 且基于 `silver_index_basic list_date/exp_date` 的统一 helper。该设计会把“prod source 是否齐备”偷换成“Lake 本地生命周期推断”，与本迁移目标不一致。

新增 DG universe helper：

```python
dg_index_daily_registered_codes(
    connection,
    *,
    instance: dg.DagsterInstance,
) -> tuple[str, ...]
```

职责：

- 只读查询 `cn_a_index_ts_codes` dynamic partitions。
- 输出排序稳定、去重、去空。
- 不读取 `index_daily_raw` 请求池。
- 不读取 `silver_index_basic`。

若用户确认要切换到 prod `index_daily` active pool，必须单独设计 DG dynamic partitions、旧 raw/silver 文件、checks 和 runless events 的迁移，不得只替换 helper。

新增 source completeness helper：

```python
prod_index_daily_source_completeness_for_trade_date(
    connection,
    *,
    prod_postgres: ProdPostgresResource,
    trade_date: str,
    expected_lake_codes: Sequence[str],
) -> SourceCompletenessStatus
```

职责：

- 检查 `core_serving.index_daily_serving[trade_date]` 的 distinct code 集合是否完整覆盖冻结后的 Lake 期望 code set。
- 检查 `(ts_code, trade_date)` 是否唯一。
- 返回 row count、expected code count、actual code count、missing/extra sample。
- source 缺 code、extra code、重复 key、超时或查询异常时均 fail closed。
- 输出排序稳定。

该门禁是以下位置的唯一代码集合事实源：

- raw by-date coverage check。
- silver index daily coverage check。
- raw/silver readiness。
- prod DB source readiness。
- historical prod DB generation candidate set。

## 7. prod DB 读取设计

新增模块：

```text
lake_console/orchestrator/src/orchestrator/defs/prod_db/index_daily.py
```

核心常量：

```python
PROD_INDEX_DAILY_ATTACHED_DATABASE = "prod_core_pg"
PROD_INDEX_DAILY_ATTACH_OPTIONS = "TYPE POSTGRES, READ_ONLY"
PROD_INDEX_DAILY_SOURCE_TABLE = "core_serving.index_daily_serving"
PROD_INDEX_DAILY_SOURCE_COLUMNS = (...)
```

禁止项：

- 禁止 `select *`。
- 禁止读取 `source`、`created_at`、`updated_at`。
- 禁止没有 `trade_date` 过滤。
- 禁止没有 index code 集合约束。
- 禁止把连接串、密码、host 写入 metadata/cursor/log。

### 7.1 remote query

新增 builder：

```python
build_prod_index_daily_remote_query(
    *,
    trade_date: str,
    index_codes: Sequence[str],
) -> str
```

要求：

- `trade_date` 必须是 `YYYY-MM-DD` 或可严格规范化的日期。
- `index_codes` 必须非空，数量不得超过当前注册池大小。
- SQL 只投影白名单字段。
- SQL 必须显式 `ORDER BY ts_code`，保证输出稳定。

字段映射在 P0 只读 profiling 后冻结。预期本地 raw 字段映射：

| 本地 raw 字段 | prod DB 字段 |
| --- | --- |
| `ts_code` | `ts_code` |
| `trade_date` | `trade_date` |
| `open` | `open` |
| `high` | `high` |
| `low` | `low` |
| `close` | `close` |
| `pre_close` | `pre_close` |
| `change` | `change_amount AS change` |
| `pct_chg` | `pct_chg` |
| `vol` | `vol` |
| `amount` | `amount` |

当前 prod DB 字段已核验为 `change_amount`，本地 select 必须显式 `change_amount AS change`，不得把 raw schema 改成 `change_amount`。

### 7.2 DuckDB attach

新增 helper：

```python
attach_prod_index_daily_readonly(
    connection,
    prod_postgres: ProdPostgresResource,
) -> None
```

要求：

- 只能通过 `ProdPostgresResource.duckdb_connection_string()` 获取连接串。
- attach options 必须包含 `READ_ONLY`。
- 单测必须断言 attach SQL 不泄漏密码。

### 7.3 source readiness probe

新增 helper：

```python
prod_index_daily_source_readiness_for_trade_date(
    connection,
    *,
    prod_postgres: ProdPostgresResource,
    trade_date: str,
    expected_index_codes: Sequence[str],
) -> SourceReadinessStatus
```

语义：

- 只用于 sensor 选中目标日期后的一次有界 probe。
- 只做冻结后的 Lake 期望 code set 对账、`count(distinct ts_code)`、缺失/多余代码样本、source row count、重复 key 计数。
- 当日 serving code 集合必须完整覆盖冻结后的 Lake 期望 code set。
- 不拉全量明细，除非 asset run 真正执行。
- 超时或异常时 fail closed，sensor skip，不提交 run。

性能预算：

- sensor source probe p95 必须小于 10 秒。
- 超过 10 秒时停止开发，改方案，不得把重查询塞进 sensor。

## 8. raw 写入设计

新增 writer：

```python
write_raw_index_daily_by_date_from_prod_db(
    context,
    *,
    lake_root: Path,
    connection,
    prod_postgres: ProdPostgresResource,
    trade_date: str,
    index_codes: Sequence[str],
    write_mode: Literal["replace"],
) -> dict[str, Any]
```

步骤：

1. 校验 `trade_date` 与 `context.partition_key` 一致。
2. 校验 `index_codes` 非空且全部来自冻结后的 Lake 期望 code set。
3. attach prod DB readonly。
4. 执行 source completeness gate；若 prod serving 未完整覆盖冻结后的 Lake 期望 code set，则拒绝写 Lake。
5. 用 remote query 拉取目标日、目标代码池数据。
6. 写入 staging parquet。
7. 在 staging 上执行 raw checks 等价的 preflight：
   - schema。
   - row count > 0。
   - 所有行 `trade_date` 等于 partition date。
   - `(ts_code, trade_date)` 唯一。
   - 覆盖 expected code set。
8. `os.replace` 原子替换正式 target。
9. 删除 staging。

禁止项：

- 不允许 append。
- 不允许 partial replace 某些 code。
- 不允许成功写出覆盖不全的 raw 文件。
- 不允许在 prod source 不齐备时生成 Lake 文件。
- 不允许 writer 内触发 Dagster event 或 runless event。

## 9. raw asset 与 job

### 9.1 asset definition

新增：

```python
@dg.asset(
    name="raw_index_daily",
    partitions_def=cn_a_index_trade_days,
    metadata={...},
    check_specs=[...],
)
def raw_index_daily(
    context,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
    prod_postgres: ProdPostgresResource,
    config: IndexDailyRawConfig,
) -> dg.MaterializeResult:
    ...
```

config：

```python
class IndexDailyRawConfig(dg.Config):
    source_mode: Literal["prod_core_db"] = "prod_core_db"
    write_mode: Literal["replace"] = "replace"
```

约束：

- sensor 只使用 `source_mode="prod_core_db"`。
- 本专项不实现 `tushare_fallback`。
- 若未来要引入 fallback，必须单独出方案，不能在本 LLD 中预留半成品配置。

### 9.2 job

新增：

```python
raw_index_daily_update_job
```

selection：

```python
AssetSelection.assets(raw_index_daily) | AssetSelection.checks_for_assets(raw_index_daily)
```

旧：

```python
index_daily_update_job
```

最终删除，不保留别名。

## 10. raw checks

新增 check 名称：

- `raw_index_daily_file_exists_check`
- `raw_index_daily_row_count_positive_check`
- `raw_index_daily_required_columns_and_types_check`
- `raw_index_daily_partition_date_matches_check`
- `raw_index_daily_unique_ts_code_trade_date_check`
- `raw_index_daily_registered_code_coverage_check`

coverage check 使用第 6 节冻结后的 Lake 期望 code set 与 source completeness gate 的同一套 code set，不读取 `silver_index_basic list_date/exp_date`。

metadata 必须包含：

- `trade_date`
- `expected_code_count`
- `actual_code_count`
- `missing_code_count`
- `missing_code_samples`
- `extra_code_count`
- `extra_code_samples`
- `file_path`

不得写：

- prod DB 连接信息。
- 全量缺失代码列表。
- 超大 sample。

## 11. silver 改造

### 11.1 asset dependency

`silver_index_daily` 从：

```python
AssetDep(raw_tushare_index_daily_by_code, AllPartitionMapping())
```

改为：

```python
AssetDep(raw_index_daily)
```

默认 partition mapping 即按同一 `trade_date` 分区。

### 11.2 materialization helper

新增：

```python
materialize_silver_index_daily_partition_from_raw_by_date(
    *,
    lake_root: Path,
    trade_date: str,
    connection,
) -> SilverIndexDailyWriteResult
```

读取：

```text
raw/index_daily/trade_date=<trade_date>/part-000.parquet
```

转换：

- `trade_date` raw string -> silver `DATE`
- `change` -> `change_amount`
- 其它字段保持现有 silver schema。

禁止：

- 枚举所有 index code raw 文件。
- 读取旧 by-code path。
- 用 `AllPartitionMapping()`。

### 11.3 silver checks

`silver_index_daily_registered_code_coverage` 改为使用同一个冻结后的 Lake 期望 code set，或直接对齐同日 `raw_index_daily` 文件中的 code set。不得用 `silver_index_basic list_date/exp_date` 重新推导本日应有 code。

不得继续从“旧 by-code raw 文件是否存在”推导 expected code set。

## 12. readiness 改造

### 12.1 raw by-date readiness

新增 helper：

```python
raw_index_daily_lake_readiness_for_trade_dates(
    connection,
    *,
    lake_root: Path,
    trade_dates: Sequence[str],
    expected_index_codes: Sequence[str],
) -> BatchDateReadiness
```

覆盖 raw check 等价语义：

- file exists。
- row count。
- schema。
- partition date。
- unique key。
- 冻结后的 Lake 期望 code coverage。

性能：

- sensor 默认最多 10 个 trade dates。
- 不读取 Dagster instance。
- 不读取旧 by-code raw。
- DuckDB set-based SQL，禁止 Python 行循环逐 row 校验。

### 12.2 silver readiness

更新：

- `silver_index_daily_ready_for_trade_date(...)` 可继续作为 Dagster check readiness。
- sensor 热路径优先使用 lake readiness batch helper。
- major indices guard 使用 by-date silver/raw facts，不读 by-code path。

### 12.3 readiness registry

删除旧：

- `RAW_INDEX_DAILY_BY_CODE_CHECKS`
- `RAW_INDEX_DAILY_BY_CODE_ASSET_KEY`
- `RAW_INDEX_DAILY_BY_CODE_READINESS_SPEC`
- `raw_index_daily_by_code_ready_for_code(...)`

新增：

- `RAW_INDEX_DAILY_CHECKS`
- `RAW_INDEX_DAILY_ASSET_KEY`
- `RAW_INDEX_DAILY_READINESS_SPEC`
- `raw_index_daily_ready_for_trade_date(...)`

## 13. sensor 改造

### 13.1 raw sensor

新增：

```python
raw_index_daily_update_job_sensor
```

逻辑：

1. 读取 expected trade dates，窗口使用 `STK_MINS_CONTINUITY_WINDOW_LIMIT` 同类默认，即当前 10 个交易日；若新增非分钟线常量，则统一命名为 `NON_STK_DAILY_CONTINUITY_WINDOW_LIMIT = 10`。
2. 检查 `cn_a_index_trade_days` registered gap。
3. 无 registered gap 后，调用 raw by-date lake readiness batch helper。
4. 选择 first not-ready date。
5. 如果 not-ready 且 `materialized=False`，做 prod DB source readiness probe。
6. source ready 必须表示 prod serving 当日 code 集合完整覆盖冻结后的 Lake 期望 code set；只有 source ready 后才提交一个 date-level `RunRequest`。
7. 如果 not-ready 且 `materialized=True, checks_passed=False`，skip，要求人工处理，不自动覆盖。

run key：

```python
build_asset_update_run_key(
    subject="raw_index_daily",
    unit_id=trade_date,
)
```

输出示例：

```text
raw_index_daily:2026-06-18
```

cursor 必须删除旧字段：

- `selected_codes`
- `next_pending_offset`
- `repair_state`
- `missing_pair_count`

cursor 新字段：

- `selected_trade_date`
- `raw_status`
- `source_status`
- `continuity_status`
- `performance_ms`
- `source_mode`

### 13.2 silver sensor

更新 `silver_index_daily_sensor.py`：

- raw gate 改为 raw by-date readiness。
- 不再调用：
  - `audit_index_daily_raw_gaps(...)`
  - `check_index_daily_raw_files_for_trade_date(...)`
  - `raw_index_daily_by_code_path(...)`
- selected target 的 raw by-date ready 后再提交 silver run。

### 13.3 删除 by-code late-arrival selector

最终删除：

- `index_daily_late_arrival_repair.py`
- 相关测试和 cursor contract。

新模型下：

- 缺 raw 文件：raw sensor 提交 date-level run。
- raw 文件存在但 check 不绿：不自动重跑，人工处理。
- prod DB late arrival 若需要覆盖已存在 raw 文件，必须由人工启动 `raw_index_daily_update_job[trade_date]`，不由 sensor 自动覆盖。

## 14. major indices readiness 改造

更新：

```text
asset_guards/market_major_indices_lake_readiness.py
```

要求：

- 不再导入 `raw_index_daily_by_code_path`。
- 不再枚举 by-code raw 文件。
- silver readiness 覆盖使用冻结后的 Lake 期望 code set、同日 raw by-date code set，或 silver check 等价逻辑。
- major indices 只关心 silver 是否可消费，不反向依赖旧 raw 布局。

## 15. catalog 改造

更新 `catalog/lake_assets.py`：

raw index daily entry：

| 字段 | 新口径 |
| --- | --- |
| asset key | `raw_index_daily` |
| partition set | `cn_a_index_trade_days` |
| path | `raw/index_daily/trade_date=<date>/part-000.parquet` |
| source system | `prod_core_db` |
| data contract | `source_mirror_by_date` |
| freshness | daily trade-date asset |
| checks | 第 10 节新 check names |

旧 `raw_tushare_index_daily_by_code` entry 删除。

## 16. 历史文件生成

新增 bootstrap 模块：

```text
defs/bootstrap/index_daily_raw_by_date_history.py
defs/bootstrap/index_daily_raw_by_date_history_cli.py
```

命令阶段：

1. `plan-files`
2. `write-sample-files`
3. `audit-sample-files`
4. `write-files`
5. `audit-files`

输入来源：

1. 正式输入只能是远程 prod `core_serving.index_daily_serving`。
2. prod `ops.index_series_active(resource='index_daily')` 是 code universe。
3. 现有 by-code raw lake 只能作为只读审计参考和抽样对账，不允许跨区引用或直接复用文件。

禁止：

- 不允许把旧 `raw/tushare/index_daily_by_code/**` 文件直接转换成正式新 raw 文件。
- 不允许在新 bootstrap 中 import 或依赖旧 by-code writer/check 作为正式路径。
- 不允许把旧 Lake 文件路径写入新 asset materialization metadata。

生成 SQL：

- 用 DuckDB `postgres_query` 或等价只读批量读取一个日期批次的 prod serving 数据。
- 每个目标日期必须先通过 source completeness gate。
- 按 `trade_date` 写 by-date parquet。
- 禁止 Python row loop。

批次建议：

- 按年份或月份切批。
- 单批输出文件数不超过 250。
- 单批内存峰值必须记录。

验收：

- by-date row count 等于 prod source 对应 date 的去重后 row count。
- `(ts_code, trade_date)` 唯一。
- 每个输出日期满足 raw by-date checks。
- 每个输出日期 code set 等于冻结后的 Lake 期望 code set。
- 异常日期输出 CSV 到 `/private/tmp`，不得进入 repo 或 lake。

## 17. runless event 补录

新增 bootstrap 模块：

```text
defs/bootstrap/index_daily_raw_by_date_runless_events.py
defs/bootstrap/index_daily_raw_by_date_runless_events_cli.py
```

命令阶段：

1. `plan-events`
2. `report-sample-events`
3. `audit-sample-events`
4. `report-events`
5. `audit-events`

补录对象：

- `raw_index_daily[trade_date]` materialization。
- 第 10 节 raw checks。

事件量级估算：

| 类型 | 数量估算 |
| --- | ---: |
| materialization | 约 6,800 |
| checks | 约 6,800 × 6 = 40,800 |
| 总计 | 约 47,600 |

要求：

- 必须先 dry-run，生成待写清单。
- sample 阶段最多 5 个 trade dates。
- full 阶段按批提交，每批不超过 250 个 partitions。
- 每个 check event 必须绑定本轮 materialization target。
- 不允许写 green check event，除非本地 raw by-date check 等价逻辑已经通过。
- 禁止补录旧 `raw_tushare_index_daily_by_code` 的新 event。

不清理旧 Dagster event 的理由：

- Dagster event log 是历史审计账，不是当前 asset 事实源。
- 删除旧 event 风险高，会破坏历史 run 调试链路。
- 新 sensor/readiness/catalog 只读取 `raw_index_daily`，旧 by-code event 不参与新链路。
- 旧 asset definition 删除后，UI 中旧 event 只作为历史记录存在。

## 18. 旧 by-code 文件删除

删除旧 lake 文件必须单独审批，不与代码迁移混在一个开发阶段。

删除前置条件：

- by-date raw 文件全量 audit 通过。
- runless materialization/check event audit 通过。
- `silver_index_daily` 已切到 by-date raw。
- `raw_index_daily_update_job_sensor` 已切到 by-date raw。
- 正式代码 `src/**` 不再引用旧 by-code path。

删除范围：

```text
raw/tushare/index_daily_by_code/**
```

不得删除：

- Dagster DB 旧 event。
- run history。
- 旧报告文件，除非用户明确要求。

## 19. 性能门禁

### 19.1 sensor

| 场景 | 预算 |
| --- | ---: |
| raw sensor 稳定态 | < 5s |
| raw sensor 缺文件 + prod source probe | < 10s |
| silver sensor 稳定态 | < 5s |
| raw/silver readiness 窗口 | 10 trade dates |
| Dagster event history 读取 | 0 |
| 每 tick RunRequest 数 | 0 或 1 |

超过预算必须停下调方案，不允许把 timeout 作为解决方式。

### 19.2 raw asset run

| 场景 | 预算 |
| --- | ---: |
| prod DB 单日读取 | < 60s |
| 单日 raw write | < 10s |
| 单日 rows | 约冻结后的 Lake 期望 code count |

如果 prod DB 单日读取超过 60s：

- 先 profile SQL 和索引条件。
- 不允许退回每 code 多 run。
- 不允许在 sensor 热路径拉明细。

### 19.3 历史生成

| 场景 | 预算 |
| --- | ---: |
| 单批输出 partitions | <= 250 |
| 单批 DuckDB SQL | set-based |
| Python row loop | 0 |
| Dagster event 写入批次 | <= 250 partitions |

## 20. 静态门禁

更新 `tests/test_run_contract_static_gates.py`：

生产代码禁止：

- `raw_tushare_index_daily_by_code`
- `raw_index_daily_by_code_path`
- `index_daily_by_code`
- `select_index_daily_pending_code_runs`
- `next_pending_offset`
- `run_key` 中拼接 `index_code`
- `MAX_RUN_REQUESTS_PER_TICK = 500` 这类 code fan-out 模型
- sensor 里调用 `get_event_records` 判断 raw/silver readiness

允许范围：

- 历史 bootstrap 模块可以只读引用旧 by-code path 做审计参考和样本对账，但不得把旧 by-code 文件作为正式输入直接转换写入新 raw。
- 测试 fixture 可以包含旧字符串作为负向样本。
- 设计文档可以描述旧口径，但必须明确是历史/待删除。

新增门禁：

- `raw_index_daily_update_job_sensor` 每 tick 最多一个 `RunRequest`。
- raw index daily run key 必须经统一 builder。
- prod DB SQL builder 单测禁止 `select *` 和 forbidden columns。
- runless event CLI dry-run 路径不得调用 `report_runless_asset_event(...)`。

## 21. 测试计划

### 21.1 prod DB SQL contract

新增：

```text
tests/test_index_daily_prod_db_contracts.py
```

覆盖：

- remote SQL 显式列。
- 必须包含 trade_date 过滤。
- 必须包含 code set 过滤。
- 禁止 forbidden columns。
- attach readonly。
- 不泄漏连接串。

### 21.2 raw by-date asset/checks

更新/新增：

```text
tests/test_index_daily_checks.py
tests/test_index_daily_raw_by_date_asset.py
```

覆盖：

- by-date path。
- schema。
- partition date。
- unique key。
- 冻结后的 Lake 期望 code coverage。
- prod DB source field mapping。
- `change` raw 字段保持不被提前改名。

### 21.3 silver

更新：

```text
tests/test_silver_index_daily_sensor.py
tests/test_silver_index_daily_asset.py
```

覆盖：

- silver 只读目标日 raw by-date。
- 不读 by-code raw。
- coverage 使用冻结后的 Lake 期望 code set 或同日 raw by-date code set。
- `change -> change_amount` 仍在 silver 层完成。

### 21.4 sensors

更新：

```text
tests/test_index_daily_sensor.py
tests/test_sensor_cursor_contracts.py
```

覆盖：

- raw sensor first-not-ready date。
- raw file missing 提交一个 date-level run。
- raw materialized but checks failed skip，不自动覆盖。
- prod source not ready skip。
- cursor 不再包含 selected_codes/next_pending_offset。
- run key 不含 index code。

### 21.5 major indices

更新：

```text
tests/test_market_major_indices_lake_readiness.py
```

覆盖：

- 不导入 by-code raw path。
- readiness 只使用 by-date raw/silver facts。
- 缺 silver 仍 fail closed。

### 21.6 bootstrap/runless

新增：

```text
tests/test_index_daily_raw_by_date_history_bootstrap.py
tests/test_index_daily_raw_by_date_runless_events.py
```

覆盖：

- dry-run 不写 event。
- sample/full audit。
- runless check event 绑定 materialization。
- 超过 batch 上限 fail closed。
- 旧 by-code path 只允许在 bootstrap 的只读审计/对账路径中出现。

## 22. 开发阶段

### P0：只读 profiling 与契约冻结

目标：

- 验证 prod DB `core_serving.index_daily_serving` 字段。
- 验证 `change` 字段映射。
- 验证本机 Dagster `cn_a_index_ts_codes`、prod `ops.index_series_active(resource='index_daily')`、prod `core_serving.index_daily_serving` 三个 code set 的覆盖关系。
- 冻结本迁移 Lake 期望 code set。
- 验证 source completeness gate 对缺 code、extra code、重复 key、source 异常均 fail closed。
- 测单日 prod source probe 和 full read 耗时。
- 估算历史 trade dates、row count、event count。

禁止：

- 不写代码。
- 不写 Dagster。
- 不写 lake。

输出：

- `/private/tmp/index_daily_prod_db_profile_*.json`
- 若字段或性能与本 LLD 冲突，先改 LLD。

### P1：基础契约与 path/schema/prod SQL

目标：

- 新 schema/path helper。
- prod DB query builder。
- DG registered code helper。
- source completeness gate helper。
- 单元测试。

不接入 active sensor。

### P2：raw by-date asset/check/job

目标：

- 新 `raw_index_daily` asset。
- 新 checks。
- 新 `raw_index_daily_update_job`。
- config builder 更新。

旧 by-code asset 暂时保留，避免未补历史 event 前切断 silver。

### P3：历史 by-date 文件生成

目标：

- 从远程 prod DB dry-run/sample/full 写 by-date raw 历史文件。
- 旧 by-code lake 只做只读抽样对账，不作为正式输入。
- audit 文件完整性。

需要正式 lake 写入审批。

### P4：runless event 补录

目标：

- dry-run/sample/full 写 `raw_index_daily` materialization/check event。
- audit event 与文件一致。

需要正式 Dagster 写入审批。

### P5：silver 与 major indices 切换

目标：

- `silver_index_daily` 改依赖 `raw_index_daily`。
- silver materializer 改读 by-date raw。
- major indices readiness 改读新 facts。

### P6：raw/silver sensors 切换

目标：

- 新 raw date-level sensor。
- silver sensor 去 by-code readiness。
- 删除 by-code late-arrival selector。

### P7：旧 by-code active code 清零

目标：

- 删除旧 asset/job/check/readiness/catalog/sensor refs。
- 静态门禁强制生产代码无 by-code 旧符号。
- 文档状态更新。

### P8：旧 by-code lake 文件删除

目标：

- 单独审批后删除旧 by-code raw files。
- 不删除 Dagster DB event。

## 23. 失败停止条件

任一条件触发，必须停止开发：

- prod DB 字段无法映射到 raw schema。
- prod DB 单日 source probe p95 超过 10s，且无索引/SQL 优化方案。
- prod DB 单日 full read 超过 60s。
- prod source completeness gate 发现目标日期 serving 未完整覆盖冻结后的 Lake 期望 code set。
- by-date 历史生成发现 prod source 与目标行数、唯一键、schema 无法对齐。
- runless event 补录需要无界 Dagster event history 扫描。
- 需要清理 Dagster DB 旧 event 才能让新链路工作。
- 需要保留旧 by-code 兼容路径才能让新链路工作。

## 24. 验收标准

最终验收必须同时满足：

- `raw_index_daily[trade_date]` 正式运行成功。
- `silver_index_daily[trade_date]` 只依赖 by-date raw。
- `raw_index_daily_update_job_sensor` 每 tick 最多提交一个 date-level run。
- 生产代码不再引用旧 by-code raw asset/path/helper。
- catalog 与代码一致。
- 新 raw by-date 历史文件与 runless event 补录 audit 通过。
- 旧 by-code 文件删除后，新 sensor、silver、major indices 不受影响。
- 全量本地测试通过。
- 未运行任何未经批准的正式 Dagster/lake 写入。
