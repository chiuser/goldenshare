# Index Daily Raw By-Date Prod DB Migration Low-Level Design

## 1. 目标

本 LLD 用于把指数日线 raw 层从当前 `raw_tushare_index_daily_by_code[ts_code]` 迁移为 `raw_index_daily[trade_date]`。

核心口径：

- 历史数据先在当前 Dagster 新湖内做物理布局转换：P0 profiling 扫描到的现有 by-code raw 全部历史文件转换为 by-date raw 文件；当前审计样本范围是 `2000-01-04` 到 `2026-06-22`，实现不得写死该范围。
- raw 日更默认数据源切到 prod core DB 后，从当前 Lake `raw_index_daily` 最新已就绪交易日之后的第一个 expected trade date 开始，只读同步 `core_serving.index_daily_serving`；起点由文件事实和交易日历计算，不硬编码具体日期。
- raw 层按交易日分区，路径按 `trade_date` 组织。
- raw 层代码池与 silver 层一致，必须使用运行时 Lake 期望 code set；当前实现的 DG 管理集合是 `cn_a_index_ts_codes` dynamic partitions。
- prod `ops.index_series_active(resource='index_daily')` 必须覆盖运行时 Lake 期望 code set，但不能反向定义 Lake/DG 的同步集合。
- 日更目标交易日的 prod serving 数据没有完整覆盖运行时 Lake 期望 code set 时，不允许发起 Lake 更新；prod 多出来的 code 不阻断，DG 只读取并校验自己本次要的 code。
- raw 只做源镜像和最小归一化，不提前承担 silver 的 `change_amount` 等语义转换。
- 历史 by-date raw 文件正式从当前 DG raw-by-code 文件转换生成；这是同一 Dagster 新湖内的布局重排，不是读取旧 Lake Console 路径，也不是从 prod DB 重拉历史。
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
- 不读取旧 Lake Console 路径生成正式 by-date raw 文件；历史转换只允许使用当前 Dagster 新湖内的 active by-code raw 资产。

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

2026-06-23 只读扫描当前 Dagster 新湖得到的 raw-by-code 文件事实：

| 项 | 观测值 |
| --- | ---: |
| 文件数 | 946 个 `part-000.parquet` |
| 行数 | 3,419,656 行 |
| distinct `ts_code` | 946 个 |
| distinct `trade_date` | 6,792 个 |
| 日期范围 | `2000-01-04` 到 `2026-06-22` |

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
| 上述 86 个在 `ops.index_series_active(resource='index_daily')` 中 | 0 个 |
| 上述 86 个在 `ops.index_series_active(resource='index_daily_raw')` 中 | 86 个 |
| 上述 86 个当前 prod raw 行数 | 2,837 行 |
| 上述 86 个当前 prod serving 行数 | 0 行 |
| 上述 86 个 `core_serving.index_basic.list_date` 范围 | `2023-03-13` 到 `2025-07-21` |
| 上述 86 个按 `list_date` 到 `2026-06-22` 开市日估算应有 serving 行数 | 47,656 行 |
| 上述 86 个估算 raw 缺口 | 44,819 行 |
| 上述 86 个估算 serving 缺口 | 47,656 行 |

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
- `index_daily` raw by-date 更新的 code universe 不能凭设计假设为 prod `index_daily` active pool，也不能凭旧 by-code 文件推断；P0 必须记录迁移审计基线，并确认日更运行时 code set 来源。
- serving 当日不齐备时必须阻断 Lake 更新；阻断口径以运行时 Lake 期望 code set 为准。

### 4.10 开发前强制前置步骤：prod active pool 与 86 个 DG 代码历史补齐

本节是本 LLD 的硬门禁。P0 之前必须先完成本节，且最终验收必须全绿。否则禁止进入任何 Dagster/Lake 代码开发。

#### 4.10.1 前置目标

1. prod `ops.index_series_active(resource='index_daily')` 必须包含当前 DG 管理的全部指数日线代码。
2. DG/Lake 日更同步集合仍以运行时 Lake 期望 code set 为准；当前迁移审计基线是本机 Dagster `cn_a_index_ts_codes` 的 946 个 code。
3. prod active pool 只作为 prod source 与 serving 写入门禁，不作为 Lake code universe 的来源。
4. 新增进 prod `index_daily` active pool 的 DG 缺口代码，必须把 prod `raw_tushare.index_daily` 和 `core_serving.index_daily_serving` 的历史数据补齐后，才能作为本迁移的 prod source。

#### 4.10.2 只读 dry-run

dry-run 必须生成 `/private/tmp/index_daily_prod_source_baseline_*.json` 或等价报告，报告不得进入 repo。

只读输入：

| 来源 | 读取内容 | 用途 |
| --- | --- | --- |
| 本机 Dagster DB | `public.dynamic_partitions where partitions_def_name='cn_a_index_ts_codes'` | 生成迁移审计基线 |
| prod `ops.index_series_active` | `resource, ts_code, first_seen_date, last_seen_date, last_checked_at` | 审计 `index_daily` 与 `index_daily_raw` resource 差异 |
| prod `core_serving.index_daily_serving` | `distinct ts_code`, bounded row counts | 审计 serving 是否覆盖 DG 集合 |
| prod `core_serving.index_basic` | `ts_code, list_date, exp_date` | 计算每个待补 code 的历史起止范围 |
| prod `core_serving.trade_calendar` | `trade_date where is_open=true` | 计算 expected code/date pair |
| prod `raw_tushare.index_daily` | `ts_code, trade_date` bounded counts | 审计 raw 缺口 |

集合对账要求：

1. `dg_codes = cn_a_index_ts_codes`，当前样本为 946 个。
2. `active_missing = dg_codes - prod_index_daily_active_pool`。
3. `serving_missing_codes = dg_codes - prod_index_daily_serving_distinct_codes`。
4. set diff 必须使用 SQL set operation，或将两侧输出统一 `LC_ALL=C sort` 后再比较；禁止直接把不同数据库的 `ORDER BY` 输出交给 `comm`。
5. 当前审计中 `active_missing` 与 `serving_missing_codes` 的核心交集是 86 个；若重新审计数量变化，必须先更新本 LLD，再继续。

历史范围计算：

1. `start_date = core_serving.index_basic.list_date`。
2. `end_date = approved_target_trade_date`。
3. 如果未来 code 有 `exp_date`，则 `end_date = min(exp_date, approved_target_trade_date)`。
4. expected rows 使用 `core_serving.trade_calendar where is_open = true` 计算。
5. 禁止把 prod raw 当前已有的 `2026-05-06` 到 `2026-06-22` 这 33 个交易日当作历史补齐范围；这只是当前缓存窗口。

当前只读样本结论：

- 86 个 code 的 `list_date` 范围是 `2023-03-13` 到 `2025-07-21`。
- 按各自 `list_date` 到 `2026-06-22` 估算应有 serving 47,656 行。
- prod raw 当前已有 2,837 行，估算缺 44,819 行。
- prod serving 当前 0 行，估算缺 47,656 行。
- `970051.CNI` 在 `2026-05-20` 的 Tushare `index_daily` 源端有数据，但 prod raw 缺失；此类缺口必须按源端事实补齐。

#### 4.10.3 生产修复执行顺序

所有写 prod 的动作都必须单独审批。本 LLD 只记录必须执行的顺序，不授权直接执行。

1. 写入 prod active pool：
   - 向 `ops.index_series_active` 写入缺失 code 的 `resource='index_daily'` 行。
   - `first_seen_date/last_seen_date/last_checked_at` 是审计字段，不参与 Lake 期望集合定义。
   - 审计字段必须来自本次补齐计划的实际 source 覆盖范围和执行时间。
   - 不得把已有 `resource='index_daily_raw'` 行改名或复用为 `resource='index_daily'`。
2. 补齐 prod raw：
   - 使用当前生产 `index_daily` 维护链路。
   - 每个待补 code 显式传 `ts_code`，范围为 `[list_date, approved_target_trade_date]`。
   - 写入目标是 `raw_tushare.index_daily`，幂等键是 `(ts_code, trade_date)`。
   - Tushare 返回空、字段缺失、分页异常、请求失败必须记录到报告，不得静默跳过。
   - 当前代码依据：`src/foundation/ingestion/request_builders.py::_index_daily_params(...)` 支持 explicit `ts_code` + `start_date/end_date`；`src/foundation/ingestion/unit_planner.py::_resolve_index_codes(...)` 在请求传入 explicit `ts_code` 时优先使用该 code，不依赖 `index_daily_raw` 请求池展开。
3. 补齐 prod serving：
   - serving 写入必须使用当前 `index_daily` active gate 语义。
   - 字段映射必须保持当前实现口径：raw `change` -> serving `change_amount`。
   - 写入目标是 `core_serving.index_daily_serving`，幂等键是 `(ts_code, trade_date)`。
   - 禁止直接绕过现有字段转换、active gate 或唯一键语义写 serving。
   - 当前代码依据：`src/foundation/ingestion/writer.py::_write_index_daily_serving(...)` 先 upsert `raw_tushare.index_daily`，再通过 `ops.index_series_active(resource='index_daily')` 过滤后写 serving。因此必须先完成第 1 步 active pool 写入，再执行 raw/serving 历史补齐。
4. 执行后只读审计：
   - 对比 expected code/date pair 与 prod raw/serving 实际 pair。
   - 对比 DG code set 与 prod `index_daily` active pool。
   - 对比 DG code set 与 prod serving distinct code。

#### 4.10.4 最终验收

必须全部满足：

1. `dg_codes - prod_index_daily_active_pool = empty`。
2. `dg_codes - prod_index_daily_serving_distinct_codes = empty`。
3. 对本次待补 code，`expected_code_trade_dates - raw_tushare.index_daily_pairs = empty`。
4. 对本次待补 code，`expected_code_trade_dates - core_serving.index_daily_serving_pairs = empty`。
5. 目标交易日 `core_serving.index_daily_serving` 完整覆盖运行时 Lake 期望 code set。
6. 所有缺口、重复 key、源端空返回都有报告；若源端确无数据，必须有逐 code/date 的 Tushare 实测证据和人工批准。

停止条件：

1. prod active pool 仍缺任何 DG code。
2. 历史补齐后 prod raw 或 serving 仍缺任何应有 code/date。
3. 补齐计划试图用 prod active pool 反向改写 Lake 期望 code set。
4. 补齐计划需要删除、清空或重建任何业务表。
5. row count、字段映射、重复键或源端空数据无法解释。

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
raw/index_daily/_staging/run_id=<RUN_ID>/trade_date=<YYYY-MM-DD>/part-000.parquet
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
- 每次日更运行前实时读取，不使用迁移时的静态文件替代 dynamic partitions。
- 返回值用于本次 run/check 的 expected code set；materialization/check metadata 必须记录 `expected_code_count` 与按排序 code 计算的 `expected_code_set_hash`，方便事后解释本次运行使用的 DG code 集合。hash 只做审计，不作为新的事实源。

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

- 检查 `core_serving.index_daily_serving[trade_date]` 是否完整覆盖本次运行的 Lake 期望 code set。
- 只对本次期望 code 检查 `(ts_code, trade_date)` 是否唯一。
- 返回 row count、expected code count、actual expected-code count、missing sample、prod extra code count/sample。
- 本次期望 code 缺失、重复 key、超时或查询异常时 fail closed；prod source 存在额外 code 不阻断，只记录为观测信息。若本地查询结果已经按期望 code 过滤后仍出现非期望 code，则视为 SQL/filter bug 并 fail closed。
- 输出排序稳定。

该门禁是日更路径的唯一 prod source 完整性门禁：

- raw by-date coverage check。
- silver index daily coverage check。
- raw/silver readiness。
- prod DB source readiness。

历史转换路径不使用 prod source completeness helper 判定每个历史日期是否应有当前 946 个 code；历史转换的覆盖依据是当前 DG raw-by-code 输入文件中真实存在的 `(ts_code, trade_date)` pair。

## 7. prod DB 日更读取设计

本节只服务日更 raw 写入，不服务历史 by-code 到 by-date 转换。

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
- `trade_date` 必须来自日更 selector 选中的目标交易日；历史转换不得调用该 builder。
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

- 只用于日更 sensor 选中目标日期后的一次有界 probe。
- 只做运行时 Lake 期望 code set 对账、`count(distinct ts_code)`、缺失代码样本、prod extra code 样本、source row count、重复 key 计数。
- 当日 serving code 集合必须完整覆盖运行时 Lake 期望 code set；prod 额外 code 不阻断。
- 不拉全量明细，除非 asset run 真正执行。
- 超时或异常时 fail closed，sensor skip，不提交 run。

性能预算：

- sensor source probe p95 必须小于 10 秒。
- 超过 10 秒时停止开发，改方案，不得把重查询塞进 sensor。

## 8. 日更 raw 写入设计

本节 writer 只负责日更从 prod-core-db 写入 `raw_index_daily[trade_date]`。历史 by-code 到 by-date 转换由第 16 节 bootstrap 模块负责。

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
2. 校验 `trade_date` 是日更 selector 选中的 expected trade date，不使用固定日期下界。
3. 校验 `index_codes` 非空且全部来自运行时 Lake 期望 code set。
4. attach prod DB readonly。
5. 执行 source completeness gate；若 prod serving 未完整覆盖运行时 Lake 期望 code set，则拒绝写 Lake。
6. 用 remote query 拉取目标日、目标代码池数据。
7. 写入 staging parquet。
8. 在 staging 上执行 raw checks 等价的 preflight：
   - schema。
   - row count > 0。
   - 所有行 `trade_date` 等于 partition date。
   - `(ts_code, trade_date)` 唯一。
   - 覆盖运行时 expected code set，且本地写出行不得包含非 expected code。
9. `os.replace` 原子替换正式 target。
10. 删除 staging。

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

coverage check 是一个统一 check，但必须按 partition 所属阶段选择覆盖依据：

1. 历史转换段，覆盖依据是当前 DG raw-by-code 输入文件中真实存在的 `(ts_code, trade_date)` pair；目标 by-date 文件必须与输入 pair 集合一致。
2. 日更段，覆盖依据是第 6 节运行时 Lake 期望 code set 与 source completeness gate 的同一套 code set。

该 check 不读取 `silver_index_basic list_date/exp_date`，也不得把历史日期机械要求为当前 946 个 code。

metadata 必须包含：

- `trade_date`
- `coverage_basis`
- `expected_code_count`
- `expected_code_set_hash`
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

`silver_index_daily_registered_code_coverage` 改为对齐同日 `raw_index_daily` 文件中的 code set；日更 raw 文件本身已由 prod source completeness gate 保证覆盖运行时 Lake 期望 code set。不得用 `silver_index_basic list_date/exp_date` 重新推导本日应有 code。

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

该 helper 服务日常 sensor 热路径，默认只评估从当前 Lake 最新已就绪 `raw_index_daily` 之后开始的最近窗口。历史转换验收由第 16 节 bootstrap audit 承担，不进入日常 sensor。

覆盖 raw check 等价语义：

- file exists。
- row count。
- schema。
- partition date。
- unique key。
- 日更 code coverage，即运行时 Lake 期望 code set。

性能：

- sensor 默认最多 10 个 trade dates。
- 不读取 Dagster instance。
- 不读取 by-code raw；历史转换审计例外在第 16 节 bootstrap 模块中单独约束。
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

1. 读取 expected trade dates，候选日期从当前 Lake `raw_index_daily` 最新已就绪交易日之后开始；历史转换缺口不由 sensor 自动补。
2. 窗口使用 `STK_MINS_CONTINUITY_WINDOW_LIMIT` 同类默认，即当前 10 个交易日；若新增非分钟线常量，则统一命名为 `NON_STK_DAILY_CONTINUITY_WINDOW_LIMIT = 10`。
3. 检查 `cn_a_index_trade_days` registered gap。
4. 无 registered gap 后，调用 raw by-date lake readiness batch helper。
5. 选择 first not-ready date。
6. 如果 not-ready 且 `materialized=False`，做 prod DB source readiness probe。
7. source ready 必须表示 prod serving 当日 code 集合完整覆盖运行时 Lake 期望 code set；只有 source ready 后才提交一个 date-level `RunRequest`。
8. 如果 not-ready 且 `materialized=True, checks_passed=False`，skip，要求人工处理，不自动覆盖。

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
- silver readiness 覆盖使用运行时 Lake 期望 code set、同日 raw by-date code set，或 silver check 等价逻辑。
- major indices 只关心 silver 是否可消费，不反向依赖旧 raw 布局。

## 15. catalog 改造

更新 `catalog/lake_assets.py`：

raw index daily entry：

| 字段 | 新口径 |
| --- | --- |
| asset key | `raw_index_daily` |
| partition set | `cn_a_index_trade_days` |
| path | `raw/index_daily/trade_date=<date>/part-000.parquet` |
| source system | `SourceSystem.PROD_CORE_DB`，覆盖全量 `raw_index_daily`，包括历史转换段和日更段 |
| data contract | `source_mirror_by_date` |
| freshness | daily trade-date asset |
| checks | 第 10 节新 check names |

实现约束：

- `LakeAssetCatalogEntry.source_system` 是单值机器字段；本资产全量统一写 `PROD_CORE_DB`。
- `default_daily_ingestion_source = IngestionSource.PROD_DB_READONLY`。
- `bootstrap_sources` 不用于表达历史 by-code 来源；如无其它正式业务 bootstrap source，可保持空 tuple。
- notes 和 materialization metadata 只能记录 `bootstrap_method=by_code_layout_conversion`、输入摘要、审计报告路径等迁移证据；不得把当前 DG `raw_tushare_index_daily_by_code`、Tushare 或 `DERIVED_FROM_ASSETS` 写成 `raw_index_daily` 的 source system。
- 旧 `raw_tushare_index_daily_by_code` entry 删除。

## 16. 历史 by-code 到 by-date 文件转换

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

转换输入：

1. 正式输入只能是当前 Dagster 新湖内的 active `raw_tushare_index_daily_by_code[ts_code]` 文件。
2. 输入路径是 `raw/tushare/index_daily_by_code/ts_code=<TS_CODE>/part-000.parquet`，位于同一个 `DEFAULT_LAKE_ROOT=/Volumes/datasource/data_lake` 下。
3. 转换范围由 P0 profiling 扫描当前 DG raw-by-code 文件得到；当前审计样本是 `2000-01-04` 到 `2026-06-22`，实现不得写死该范围。
4. code universe 是当前 DG `cn_a_index_ts_codes` 的 946 个 code；历史每个 trade date 的实际 code set 以 by-code 输入文件中存在的 `(ts_code, trade_date)` pair 为准。
5. prod DB 不参与历史转换；prod `ops.index_series_active(resource='index_daily')` 和 `core_serving.index_daily_serving` 只约束日更 source。

禁止：

- 不允许读取旧 Lake Console 路径，例如 `/Volumes/datasource/goldenshare-tushare-lake/raw_tushare/index_daily/**`。
- 不允许从 prod DB 重拉历史来生成 by-date 文件。
- 不允许在新 bootstrap 中复用旧 by-code writer/check 作为正式写入逻辑；可以复用字段契约、path helper 和只读 SQL 片段。
- 不允许把 by-code input file list 全量写入 Dagster materialization metadata；只记录 input summary、`bootstrap_method=by_code_layout_conversion` 和报告路径。metadata 中的 source system 仍为 `PROD_CORE_DB`。

生成 SQL：

- 用 DuckDB `read_parquet(..., hive_partitioning=false, union_by_name=true)` 批量读取当前 by-code parquet 文件。
- 按批次构造 input facts：`ts_code`、`trade_date`、行情字段。
- 每个目标日期的 expected code set 来自该日期在 input facts 中出现的 `ts_code` 集合。
- 按 `trade_date` 写 by-date parquet。
- 禁止 Python row loop。

批次建议：

- 按年份或月份切批。
- 单批输出文件数不超过 250。
- 单批内存峰值必须记录。

验收：

- by-date 总 row count 等于 by-code input 总 row count。
- by-date `(ts_code, trade_date)` pair 集合等于 by-code input pair 集合。
- `(ts_code, trade_date)` 唯一。
- 每个输出日期满足 raw by-date checks。
- 每个输出日期 code set 等于 by-code input 中该日期的 code set；不能要求历史日期都有当前 946 个 code。
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
- 历史转换段的 coverage check event metadata 必须写 `coverage_basis=by_code_source_pairs`。
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
| 单日 rows | 约运行时 Lake 期望 code count |

如果 prod DB 单日读取超过 60s：

- 先 profile SQL 和索引条件。
- 不允许退回每 code 多 run。
- 不允许在 sensor 热路径拉明细。

### 19.3 历史转换

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

- 历史 bootstrap 模块在 P3/P4 可以且只能把当前 DG 新湖 by-code 文件作为正式只读输入，转换写入新 raw by-date；禁止旧 Lake Console 路径。P7 后 bootstrap 代码必须删除或移出 active source，避免旧 by-code path 继续留在生产代码扫描范围内。
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
- 运行时 Lake 期望 code coverage。
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
- coverage 使用运行时 Lake 期望 code set 或同日 raw by-date code set。
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
- 当前 DG by-code path 只允许在历史转换 bootstrap 的只读输入路径中出现；旧 Lake Console 路径禁止出现。

## 22. 开发阶段

### P-1：prod active pool 与 DG 缺口代码历史补齐

目标：

- 完成第 4.10 节的 prod source 基线修复。
- 确认 prod `ops.index_series_active(resource='index_daily')` 覆盖 DG 当前 946 个指数日线代码。
- 将当前 DG 缺口代码从各自 `core_serving.index_basic.list_date` 到批准目标交易日的 prod raw 与 serving 历史补齐。
- 形成最终只读验收报告。

禁止：

- 不改 Dagster/Lake 代码。
- 不写 lake。
- 不写 Dagster event。
- 不把 prod active pool 作为 Lake code universe。
- 不把当前 33 个 prod raw 缓存交易日当作历史补齐范围。

输出：

- `/private/tmp/index_daily_prod_source_baseline_*.json`
- `/private/tmp/index_daily_prod_source_repair_audit_*.json`
- 如果该阶段任一验收项不通过，停止本迁移，不进入 P0。

### P0：只读 profiling 与契约基线

目标：

- 验证 prod DB `core_serving.index_daily_serving` 字段。
- 验证 `change` 字段映射。
- 验证本机 Dagster `cn_a_index_ts_codes`、prod `ops.index_series_active(resource='index_daily')`、prod `core_serving.index_daily_serving` 三个 code set 的覆盖关系。
- 记录本迁移 Lake code set 审计基线，并确认日更运行时读取 `cn_a_index_ts_codes` dynamic partitions。
- 验证 source completeness gate 对本次期望 code 缺失、重复 key、source 异常均 fail closed；prod 额外 code 不阻断。
- 测单日 prod source probe 和 full read 耗时。
- 只读扫描当前 DG raw-by-code 文件，估算历史转换 trade dates、row count、event count。

禁止：

- 不写代码。
- 不写 Dagster。
- 不写 lake。

输出：

- `/private/tmp/index_daily_prod_db_profile_*.json`
- `/private/tmp/index_daily_by_code_to_by_date_profile_*.json`
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

### P3：历史 by-code 到 by-date 文件转换

目标：

- 从当前 Dagster 新湖 `raw_tushare_index_daily_by_code` dry-run/sample/full 写 by-date raw 历史文件。
- 转换范围来自 P0 profiling 的当前 DG raw-by-code min/max；当前审计样本为 `2000-01-04` 到 `2026-06-22`。
- source/target `(ts_code, trade_date)` pair 必须一致。
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
- prod source completeness gate 发现目标日期 serving 未完整覆盖运行时 Lake 期望 code set。
- by-date 历史转换发现当前 DG by-code input 与目标行数、pair 集合、唯一键、schema 无法对齐。
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
- P0 profiling 确认范围内的 by-code 到 by-date 历史转换与 runless event 补录 audit 通过。
- 旧 by-code 文件删除后，新 sensor、silver、major indices 不受影响。
- 全量本地测试通过。
- 未运行任何未经批准的正式 Dagster/lake 写入。
