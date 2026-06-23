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
   - 例如 `raw_index_daily_file_contract_check`。
   - 旧 check 名称只作为历史 event 保留，不进入新 readiness。

## 3. 非目标

本专项不做以下事情：

- 不在新链路开发、历史文件转换、runless event 补录和 sensor 启用阶段清理 Dagster DB 里的旧 by-code run/materialization/check event；旧 index daily 状态/事件清理只能在 P9 作为独立治理动作执行。
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
- raw by-date 还需要覆盖运行时 Lake 期望 code set。历史转换段看 by-code input pair，日更段看 prod serving 对本次 DG code set 的覆盖；不得再引入 `effective_index_codes_for_trade_date` 这类生命周期推断口径。

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
- 但 backend 当前 `build_prod_core_trade_date_query(...)` 只按 trade date/range 查询，不带 DG code set 过滤；它能作为字段白名单和安全口径参考，不能作为 orchestrator 日更运行时直接复用的实现文件。
- 按仓库边界，orchestrator 不得跨区引用 backend sync 文件；需要在 `lake_console/orchestrator/src/orchestrator/defs/prod_db/index_daily.py` 内实现自己的只读 query builder/source gate。

### 4.9 prod DB 只读审计事实

2026-06-23 只读审计远程 prod DB：

| 项 | 观测值 |
| --- | ---: |
| 本机 Dagster `cn_a_index_ts_codes` dynamic partitions | 946 个 code |
| 本机 DG code set hash | `6f8f560f11cdce10e4cd5a096c64a4c9` |
| 当前 by-date raw 目标路径 | `/Volumes/datasource/data_lake/raw/index_daily` 不存在，`trade_date=*/part-000.parquet` 为 0 |
| `ops.index_series_active(resource='index_daily')` | 1130 个 code |
| `ops.index_series_active(resource='index_daily_raw')` | 3052 个 code |
| `ops.index_series_active(resource='index_mins')` | 530 个 code |
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

同步要求：

- `duckdb_sql.py` 中 `INDEX_DAILY_RAW_COLUMNS` 必须改为来自 `RAW_INDEX_DAILY_SCHEMA`；
- `assets/index_daily.py` 中 `INDEX_DAILY_RAW_COLUMN_TYPES` 必须改为来自 `RAW_INDEX_DAILY_SCHEMA`；
- `RAW_TUSHARE_INDEX_DAILY_BY_CODE_SCHEMA` 只能在迁移期旧 by-code 资产和 P3/P4 bootstrap 输入审计中出现；P7 后 active source 不得继续引用。

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

catalog 不能继续使用 `_tushare_raw_entry(...)` 或 `_derived_entry(...)` 生成 `raw_index_daily` entry：

- `_tushare_raw_entry(...)` 会自动写 `SourceSystem.TUSHARE`、`DataContractSource.TUSHARE_RAW_CONTRACT`、`IngestionSource.TUSHARE_API`；
- `_derived_entry(...)` 会自动写 `SourceSystem.DERIVED`、`DataContractSource.DERIVED_CONTRACT`；
- 新实现必须新增专用 `_prod_core_raw_entry(...)`，或直接调用 `_entry(...)` 并逐项写完整字段。

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

definition metadata 必须写：

- `source_system=SourceSystem.PROD_CORE_DB`；
- `data_contract="source_mirror_by_date"`；
- `column_schema=RAW_INDEX_DAILY_SCHEMA`；
- `path_template=raw_index_daily_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY)`；
- `source_api=None`，因为日更来源是 prod serving table，不是 Tushare API；
- `extra_metadata` 可以记录 `source_table="core_serving.index_daily_serving"`，但不得记录连接串、host、password。

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

新增 raw by-date blocking check 只能是两个聚合 check：

- `raw_index_daily_file_contract_check`
- `raw_index_daily_code_coverage_check`

禁止把文件存在、行数、schema、分区日期、唯一键拆成多条 blocking check。拆得太碎会给 Dagster DB 产生大量细碎 check event，不增加新语义，只增加事件写入、UI 展示和 readiness 查询负担。

`raw_index_daily_file_contract_check` 聚合以下 raw 文件契约：

1. 目标 by-date 文件存在。
2. 文件行数大于 0。
3. 字段和类型符合 `RAW_INDEX_DAILY_SCHEMA`。
4. 文件内 `trade_date` 全部等于 partition trade date 的 `YYYYMMDD`。
5. `(ts_code, trade_date)` 唯一。

metadata 必须包含：

- `trade_date`
- `file_path`
- `row_count`
- `schema_ok`
- `partition_date_ok`
- `unique_key_ok`
- `failure_reason_counts`
- `failed_contract_items`
- `sample_rows`

`raw_index_daily_code_coverage_check` 是统一覆盖检查，但必须按 partition 所属阶段选择覆盖依据：

1. 历史转换段，覆盖依据是当前 DG raw-by-code 输入文件中真实存在的 `(ts_code, trade_date)` pair；目标 by-date 文件必须与输入 pair 集合一致。
2. 日更段，覆盖依据是第 6 节运行时 Lake 期望 code set 与 source completeness gate 的同一套 code set。

该 check 不读取 `silver_index_basic list_date/exp_date`，也不得把历史日期机械要求为当前 946 个 code。

code coverage metadata 必须包含：

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

激活门禁：

- `raw_index_daily_update_job_sensor` 在 P3/P4 完成前必须保持 STOPPED，不得接管正式日更；
- sensor 启动时必须能从 `raw_index_daily` 文件事实和 runless event 事实得到最新已就绪 trade date；
- 如果 `raw/index_daily` 目标路径不存在、没有任何 ready partition，或 runless event 尚未补齐，sensor 必须 fail closed 并返回明确 skip/block reason；
- first daily target 只能是最新已就绪 trade date 之后的第一个 expected trade date；
- 生产代码不得使用 `2026-06-23`、`2026-06-22` 或任何固定日期作为日更起点。

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
| data contract source | `DataContractSource.PROD_SERVING_CONTRACT` |
| data contract | `source_mirror_by_date` |
| ingestion sources | `(IngestionSource.PROD_DB_READONLY,)` |
| default daily ingestion source | `IngestionSource.PROD_DB_READONLY` |
| bootstrap sources | `()`，历史 by-code 只作为物理转换输入，不写入该机器字段 |
| event policy | `EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL` |
| write policy | `WritePolicy.PARTITION_FILE_ATOMIC_REPLACE` |
| freshness | daily trade-date asset |
| checks | 第 10 节新 check names |

实现约束：

- `LakeAssetCatalogEntry.source_system` 是单值机器字段；本资产全量统一写 `PROD_CORE_DB`。
- `LakeAssetCatalogEntry.data_contract_source` 也必须是单值机器字段；本资产统一写 `PROD_SERVING_CONTRACT`，不得写 `TUSHARE_RAW_CONTRACT`。
- `ingestion_sources = (IngestionSource.PROD_DB_READONLY,)`。
- `default_daily_ingestion_source = IngestionSource.PROD_DB_READONLY`。
- `bootstrap_sources` 不用于表达历史 by-code 来源；如无其它正式业务 bootstrap source，可保持空 tuple。
- notes 和 materialization metadata 只能记录 `bootstrap_method=by_code_layout_conversion`、输入摘要、审计报告路径等迁移证据；不得把当前 DG `raw_tushare_index_daily_by_code`、Tushare 或 `DERIVED_FROM_ASSETS` 写成 `raw_index_daily` 的 source system。
- 不能通过 `_tushare_raw_entry(...)` 或 `_derived_entry(...)` 偷懒生成 entry；这两个 helper 会把机器字段写错。
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

生命周期：

- P3/P4 期间，bootstrap 模块是唯一允许在 active source 中出现旧 by-code path/symbol 的范围；
- 该允许范围只服务历史转换和 runless event 补录，不得被 sensor、asset、check、catalog 或 readiness 引用；
- P7 必须删除 bootstrap 模块，或移动到不参与 active production static gate 的离线工具目录；
- P7 后 `src/orchestrator/defs/**` 旧 by-code symbol 扫描必须为 0。

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
| checks | 约 6,800 × 2 = 13,600 |
| 总计 | 约 20,400 |

要求：

- 必须先 dry-run，生成待写清单。
- sample 阶段最多 5 个 trade dates。
- full 阶段按批提交，每批不超过 250 个 partitions。
- 每个 check event 必须绑定本轮 materialization target。
- 不允许写 green check event，除非本地 raw by-date check 等价逻辑已经通过。
- 历史转换段的 `raw_index_daily_code_coverage_check` event metadata 必须写 `coverage_basis=by_code_source_pairs`。
- 禁止补录旧 `raw_tushare_index_daily_by_code` 的新 event。

P4 不清理旧 Dagster event 的理由：

- Dagster event log 是历史审计账，不是当前 asset 事实源。
- 删除旧 event 风险高，必须有独立 dry-run、边界、备份和审批。
- 新 sensor/readiness/catalog 只读取 `raw_index_daily`，旧 by-code event 不参与新链路。
- 旧 asset definition 删除后，UI 中旧 event 只作为历史记录存在。
- 旧 index daily 状态/事件清理如确有需要，只能进入 P9，不能和 runless event 补录混在一起。

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

- Dagster DB 旧 event，P8 只处理 lake 物理文件。
- run history。
- 旧报告文件，除非用户明确要求。

### 18.1 旧 index daily Dagster 状态/事件清理

P9 是可选的独立治理阶段，不是新 by-date raw/silver 日更链路的启用条件。只有在 P7 active source 清零、P8 物理旧文件处理完成或明确延期、并且新 readiness/sensor/catalog 只读取 `raw_index_daily` 和 `silver_index_daily` 后，才允许评估 P9。

P9 候选清理对象只能通过精确名称和边界选出：

- 旧 `raw_tushare_index_daily_by_code` materialization event。
- 旧 raw-by-code check event。
- 旧 `index_daily_update_job` run 记录。
- 已删除旧 sensor 的 cursor/state。
- P8 已删除的 `raw/tushare/index_daily_by_code/**` 路径对应的旧观测记录。

P9 禁止删除：

- `cn_a_index_ts_codes` dynamic partitions。
- `cn_a_index_trade_days` dynamic partitions。
- 新 `raw_index_daily` materialization/check event。
- `silver_index_daily` 历史。
- prod DB 中任何 raw、core、serving、active pool 数据。
- 新 by-date lake 文件或历史转换报告。

P9 执行规则：

1. 必须先生成 dry-run 报告，列出候选对象类型、精确名称、storage id 或时间范围、预计数量、样本和保留对象。
2. 必须证明候选对象与新 readiness helper、sensor cursor、asset selection、catalog、run contract 无交集。
3. 必须有备份或回滚方案；没有安全回滚时，只允许归档/忽略旧记录。
4. 禁止宽泛清空 Dagster event history，禁止按 asset group、时间段或表级条件误删非 index daily 数据。
5. 如果 Dagster 当前能力不支持安全精确删除，则 P9 停止，不得用直接 SQL 强行清理。
6. 如果新链路必须依赖 P9 清理才能运行，说明 P1-P7 仍有旧依赖，必须回退到设计修正。

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
- 生产代码中硬编码 `2026-06-22`、`2026-06-23` 作为迁移终点、日更起点或 cutover 日期

允许范围：

- 历史 bootstrap 模块在 P3/P4 可以且只能把当前 DG 新湖 by-code 文件作为正式只读输入，转换写入新 raw by-date；禁止旧 Lake Console 路径。P7 后 bootstrap 代码必须删除或移出 active source，避免旧 by-code path 继续留在生产代码扫描范围内。
- 测试 fixture 可以包含旧字符串作为负向样本。
- 设计文档可以描述旧口径，但必须明确是历史/待删除。
- 审计报告、测试 fixture 和设计文档可以包含 `2026-06-22`、`2026-06-23` 作为样本事实；production runtime 逻辑不得依赖这些日期。

新增门禁：

- `raw_index_daily_update_job_sensor` 每 tick 最多一个 `RunRequest`。
- raw index daily run key 必须经统一 builder。
- prod DB SQL builder 单测禁止 `select *` 和 forbidden columns。
- runless event CLI dry-run 路径不得调用 `report_runless_asset_event(...)`。
- `raw_index_daily_update_job_sensor` 在 by-date baseline 缺失时必须 skip/block，不得猜测 first target。
- raw index daily blocking check 名称只能是 `raw_index_daily_file_contract_check` 和 `raw_index_daily_code_coverage_check`；禁止重新引入 `file_exists/row_count/schema/partition_date/unique_key/registered_code_coverage/expected_code_coverage` 等细碎 raw check 名称。

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
- raw file 契约收敛在 `raw_index_daily_file_contract_check`，coverage 收敛在 `raw_index_daily_code_coverage_check`。
- file contract metadata 能说明文件缺失、空文件、schema 错、日期错、重复键的具体子项和样本。
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
- 每个 partition 只补 `raw_index_daily_file_contract_check` 和 `raw_index_daily_code_coverage_check` 两个 raw check event。
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
- 新 raw sensor 保持 STOPPED，直到 P3/P4 audit 和只读 readiness 验收通过。
- 验证 by-date baseline 存在后，first target 由最新 ready trade date 后的 expected trade date 计算，不使用固定日期。

### P7：旧 by-code active code 清零

目标：

- 删除旧 asset/job/check/readiness/catalog/sensor refs。
- 静态门禁强制生产代码无 by-code 旧符号。
- 文档状态更新。

### P8：旧 by-code lake 文件删除

目标：

- 单独审批后删除旧 by-code raw files。
- 不删除 Dagster DB event。

### P9：旧 index daily Dagster 状态/事件清理

目标：

- 单独审批后执行旧 index daily 状态/事件清理 dry-run。
- 只在 dry-run 证明不影响新 readiness、sensor、catalog、run contract 后 apply。
- 若无法安全精确删除，则保留旧记录作为历史审计账，不强行清理。

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
- P9 旧状态/事件清理 dry-run 无法证明候选对象与新 raw/silver/readiness/sensor 无交集。

## 24. 验收标准

最终验收必须同时满足：

- `raw_index_daily[trade_date]` 正式运行成功。
- `silver_index_daily[trade_date]` 只依赖 by-date raw。
- `raw_index_daily_update_job_sensor` 每 tick 最多提交一个 date-level run。
- raw by-date blocking check 只有 `raw_index_daily_file_contract_check` 和 `raw_index_daily_code_coverage_check` 两个聚合 check。
- 若执行 P9，清理报告证明未删除 dynamic partitions、新 raw by-date event、新 silver 历史、prod 数据和 by-date lake 文件；若不执行 P9，旧事件不参与新 readiness 和日更状态。
- 生产代码不再引用旧 by-code raw asset/path/helper。
- catalog 与代码一致。
- P0 profiling 确认范围内的 by-code 到 by-date 历史转换与 runless event 补录 audit 通过。
- 旧 by-code 文件删除后，新 sensor、silver、major indices 不受影响。
- 全量本地测试通过。
- 未运行任何未经批准的正式 Dagster/lake 写入。

## 25. 本轮重新审计结论与推进建议

### 25.1 已核实的代码影响面

CodeGraph 与源码审计确认，本专项真实改动面至少包括：

| 改动面 | 当前事实 | 实现要求 |
| --- | --- | --- |
| `paths.py` | 只有 `raw_index_daily_by_code_path(...)` 和 by-code staging helper。 | 新增 `raw_index_daily_path(...)` 与 by-date staging helper；P7 删除旧 helper。 |
| `asset_column_schemas.py` / `duckdb_sql.py` | raw index daily schema 名称绑定 Tushare/by-code，`INDEX_DAILY_RAW_COLUMNS` 由旧 schema 生成。 | 新增 `RAW_INDEX_DAILY_SCHEMA`，并让 raw columns/types 全部切到新 schema。 |
| `assets/index_daily.py` | raw asset 是 `raw_tushare_index_daily_by_code[ts_code]`；silver 通过 `AllPartitionMapping()` 扫所有 by-code 文件。 | 新增 `raw_index_daily[trade_date]`；silver 改为同日 by-date raw 输入。 |
| `checks/index_daily_checks.py` | raw checks 全部挂旧 asset，silver coverage 仍读 by-code raw。 | 新增 by-date raw checks；silver coverage 改读同日 by-date raw。 |
| `sensors/index_daily_sensor.py` | Tushare source probe + per-code run；cursor 带 selected_codes/next_pending_offset/repair_state。 | prod source completeness gate + date-level run；删除 per-code repair cursor。 |
| `sensors/silver_index_daily_sensor.py` | 依赖 `audit_index_daily_raw_gaps(...)` 和 by-code 文件 presence。 | 依赖 `raw_index_daily[trade_date]` readiness。 |
| `asset_guards/market_major_indices_lake_readiness.py` | `silver_index_daily_lake_readiness_for_trade_date(...)` 仍读取 by-code raw。 | 改为 by-date raw/silver facts，不再导入旧 path。 |
| `catalog/lake_assets.py` | raw entry 通过 `_tushare_raw_entry(...)` 写 Tushare source。 | 新 raw entry 必须字段级写 prod-core-db，不得套旧 helper。 |
| `run_contracts/configs.py` | op key 是 `raw_tushare_index_daily_by_code`，config 里重复传 `trade_date`。 | op key 改 `raw_index_daily`；partition key 是唯一日期参数。 |
| `sensors/readiness.py` | 存在 `RAW_INDEX_DAILY_BY_CODE_*` spec 和 `raw_index_daily_by_code_ready_for_code(...)`。 | 新增 `RAW_INDEX_DAILY_*` trade-date readiness；P7 删除旧 spec。 |
| `tests/test_run_contract_static_gates.py` | 当前已有 sensor 侧旧 symbol 禁止项。 | 扩展为 by-code 旧符号清零、prod SQL 安全、硬编码日期禁止、runless dry-run 禁止写 event。 |

### 25.2 已核实的 prod 与 lake 数据事实

2026-06-23 本轮只读复核：

- 本机 DG `cn_a_index_ts_codes` 为 946 个，code set hash 为 `6f8f560f11cdce10e4cd5a096c64a4c9`。
- 本机 by-code raw 文件为 946 个、3,419,656 行、946 个 code、6,792 个 trade date，范围 `2000-01-04` 到 `2026-06-22`。
- 目标 by-date raw 路径 `/Volumes/datasource/data_lake/raw/index_daily` 当前不存在。
- prod `ops.index_series_active(resource='index_daily')` 为 1130 个 code。
- prod `ops.index_series_active(resource='index_daily_raw')` 为 3052 个 code。
- prod `core_serving.index_daily_serving` distinct code 为 1130 个，当前最大 trade date 为 `2026-06-22`。
- `dg_codes - prod_index_daily_active_pool = 86`。
- `dg_codes - prod_index_daily_serving_distinct_codes = 86`。
- `dg_codes - prod_index_daily_raw_pool = 0`，说明 86 个缺口都在旧 raw 请求池中，但未进入 prod `index_daily` active pool 和 serving。
- `prod_serving_codes - dg_codes = 270`，prod 额外 code 不阻断 DG 日更。
- 最近 10 个 prod serving 交易日均为 1126 个 code；active pool 最新日缺 4 个：`480055.CNI`、`480056.CNI`、`480057.CNI`、`931598.CSI`，且这 4 个与 DG 946 交集为空。
- 86 个缺口按各自 `core_serving.index_basic.list_date` 到 prod 当前最大 serving date `2026-06-22` 估算 expected pair 为 47,656；当前 prod raw 2,837 行，raw 缺 44,819；prod serving 0 行，serving 缺 47,656。

这些事实仍然只是开工前审计样本。P-1/P0 正式执行前必须重新生成报告；若任一数字变化，先改本文档，再继续开发。

### 25.3 新发现风险

1. catalog helper 写错字段风险：如果实现时继续用 `_tushare_raw_entry(...)`，即使 asset 名改成 `raw_index_daily`，catalog 仍会显示 Tushare source，违反用户已确认口径。
2. backend 复用风险：backend prod-core-db 已有字段口径但没有 DG code set filter，且跨区直接引用不允许。orchestrator 需要自己的 prod adapter。
3. baseline 缺失风险：当前 by-date 目标路径不存在，sensor 不能在 M3/M4 前通过“最新 ready raw_index_daily”计算日更起点。
4. bootstrap 遗留风险：P3/P4 必须临时读 by-code 文件，但 P7 后如果不删除或移出 active source，会和旧符号清零门禁冲突。
5. check 过碎风险：如果把文件存在、row count、schema、partition date、unique key、coverage 都拆成独立 blocking check，会给 Dagster DB 增加大量细碎 event。实现必须保持两个聚合 check：`raw_index_daily_file_contract_check` 和 `raw_index_daily_code_coverage_check`。
6. 固定日期风险：当前审计样本中的 `2026-06-22/2026-06-23` 不能进入 production runtime 逻辑。
7. 旧数据清理风险：P8 只删旧 by-code lake 文件，P9 才处理旧 Dagster 状态/事件。P9 不能成为新链路启用门槛；如果新链路需要清旧 event 才能跑，说明还有旧依赖没清零。

### 25.4 建议推进步骤

1. P-1 先做 prod source 基线修复，目标是 DG 946 code 全部进入 prod `index_daily` active pool，且 prod raw/serving 对 86 个待补 code 的 expected pair 缺口为 0。
2. P0 重新做只读 profiling，冻结字段、code set hash、历史转换范围、event 数量和性能预算；P0 输出是后续开发的验收基线。
3. P1/P2 只做新 schema/path/prod query/source gate/raw asset/check/job，不启用 sensor，不删除旧资产。
4. P3 单独申请 lake 写入，按 P0 范围生成 by-date raw 文件，sample/full 分开。
5. P4 单独申请 Dagster event 写入，runless materialization/check event 先 dry-run、再 sample、再 full。
6. P5/P6 切 silver、major indices、raw/silver sensors；新 raw sensor 先 STOPPED，完成 by-date baseline 验收后再启用。
7. P7 清零旧 by-code active source；P8 单独审批后删除旧物理文件；P9 如确有必要，再单独审批旧 index daily Dagster 状态/事件清理。

### 25.5 遗留拍板项

1. P-1 补数目标交易日：应以正式 P0 profiling 时当前 DG by-code 最大 trade date 为下限；若开发期间旧 by-code 继续增长，需要以执行前最新 profiling 为准。
2. 86 个 code 若出现 Tushare 源端确无数据，是否允许建立人工批准的 source gap 白名单继续推进。
3. P7 后 bootstrap 代码处理方式：删除，还是移出 `src/orchestrator/defs/**` active source。无论选择哪种，production static gate 旧 symbol 必须为 0。
4. catalog 实现方式：新增 `_prod_core_raw_entry(...)` helper，还是直接 `_entry(...)`。若直接 `_entry(...)`，测试必须覆盖全部字段，防止以后回退到 Tushare helper。
5. P9 旧 Dagster DB 状态/事件清理是否执行：若执行，必须另起 dry-run、审批和回滚方案；若不执行，旧记录保留为历史审计账。

## 26. 2026-06-23 check 收敛与 P9 清理代码级审计

本节只记录代码级审计和只读 dry-run 结果，不代表已经修改 Python 代码，也不代表允许执行清理 apply。

### 26.1 当前 active 代码事实

CodeGraph 和源码逐项审计确认，当前 active 代码仍是旧 by-code raw 链路：

| 文件 | 当前事实 | 对本方案的含义 |
| --- | --- | --- |
| `defs/assets/index_daily.py` | `raw_tushare_index_daily_by_code` 仍是 `cn_a_index_ts_codes` 分区 raw asset；`silver_index_daily` 通过 `AllPartitionMapping()` 依赖旧 raw-by-code，并扫描所有 by-code parquet。 | P1/P2 必须新增 `raw_index_daily[trade_date]`；P5 必须把 silver 输入切到同日 by-date raw。 |
| `defs/checks/index_daily_checks.py` | raw checks 是 5 个旧 by-code checks：file exists、row count、schema、partition code、unique key。 | P2 必须替换为 `raw_index_daily_file_contract_check` 与 `raw_index_daily_code_coverage_check` 两个聚合 check；不得把 5 个旧 check 平移到新 asset。 |
| `defs/jobs/index_daily_update.py` | job selection 是旧 `raw_tushare_index_daily_by_code` + checks。 | 新 job 必须选择 `raw_index_daily` + 两个聚合 checks。旧 `index_daily_update_job` 最终删除，不保留别名。 |
| `defs/sensors/index_daily_sensor.py` | sensor 仍查 Tushare readiness，按缺失 code 生成 per-code RunRequest，cursor 记录 selected codes / offset / repair state。 | 新 raw sensor 必须改为 prod source completeness gate + date-level single RunRequest，cursor 不再保存 per-code repair 状态。 |
| `defs/sensors/silver_index_daily_sensor.py` | sensor 先跑 by-code raw gap audit，再检查 by-code 文件是否包含目标交易日。 | 新 silver sensor 只读取 `raw_index_daily[trade_date]` readiness，不扫描 by-code 文件集合。 |
| `defs/sensors/index_daily_raw_file_readiness.py` | readiness helper 基于 `raw_index_daily_by_code_path(...)` 扫 946 个 by-code 文件。 | 新 helper 应基于单个 by-date raw 文件和 code coverage 元数据；旧 helper P7 删除。 |
| `defs/sensors/readiness.py` | `RAW_INDEX_DAILY_BY_CODE_CHECKS` 仍列 5 个旧 check，`raw_index_daily_by_code_ready_for_code(...)` 仍存在。 | 必须新增 date-level `RAW_INDEX_DAILY_*` readiness spec，并在 P7 清零旧 by-code readiness。 |
| `defs/catalog/lake_assets.py` | raw entry 仍是 `_tushare_raw_entry(asset_key='raw_tushare_index_daily_by_code')`，blocking checks 是旧 5 个 by-code checks；当前 partition model 命名还写成 `TRADE_DATE_PARTITION_RAW_INDEX_DAILY`。 | 新 entry 必须写 `SourceSystem.PROD_CORE_DB`、by-date path、两个聚合 checks 和正确 trade-date partition model；旧 entry P7 删除。 |
| `defs/run_contracts/configs.py` | op key 是 `raw_tushare_index_daily_by_code`，run config 里重复传 `trade_date`。 | 新 raw asset 以 partition key 作为唯一日期参数，run config 只保留非分区参数。 |
| `defs/asset_guards/market_major_indices_lake_readiness.py` | major indices readiness 仍读取 by-code raw paths，用 silver coverage 语义补判断。 | P6 必须切到 by-date raw/silver facts，不再 import 旧 path。 |

### 26.2 check 收敛的实现改动点

`raw_index_daily_file_contract_check` 必须把旧 raw-by-code 的 4 类文件契约和新 by-date date/key 语义聚合到一条 blocking check：

1. 文件存在。
2. row count 大于 0。
3. schema 与 `RAW_INDEX_DAILY_SCHEMA` 一致。
4. 文件内 `trade_date` 等于 partition key 的 `YYYYMMDD`。
5. `(ts_code, trade_date)` 唯一。

该 check 的 metadata 至少包含 `file_path`、`row_count`、`schema_ok`、`partition_date_ok`、`unique_key_ok`、`failed_contract_items`、`failure_reason_counts` 和样本；这样排障信息不丢，但 Dagster DB 只写一条 check event。

`raw_index_daily_code_coverage_check` 必须只承载 code coverage：

1. 历史转换段使用 `coverage_basis=by_code_source_pairs`，证明 by-code 输入 `(ts_code, trade_date)` pair 到 by-date 目标无损。
2. 日更段使用 `coverage_basis=prod_serving_expected_lake_codes`，证明 prod serving 覆盖运行时 Lake 期望 code set。
3. metadata 记录 `expected_code_count`、`expected_code_set_hash`、`actual_code_count`、missing/extra count 和样本。

测试和静态门禁必须覆盖：

1. active source 中 raw by-date blocking check 名称只能是这两个。
2. 禁止新增 `raw_index_daily_file_exists_check`、`raw_index_daily_row_count_positive_check`、`raw_index_daily_required_columns_and_types_check`、`raw_index_daily_partition_date_matches_check`、`raw_index_daily_unique_ts_code_trade_date_check`、`raw_index_daily_registered_code_coverage_check`、`raw_index_daily_expected_code_coverage_check`。
3. readiness 不能同时支持新旧 raw check。
4. runless event dry-run 对每个 partition 只计划 materialization + 2 个 raw check event。

### 26.3 P9 dry-run 执行口径

本轮 dry-run 只读本机正式 Dagster Postgres：

```text
DAGSTER_HOME: /Users/congming/.goldenshare/dagster_home
postgres_url: postgresql://congming@localhost:5432/goldenshare_dagster
执行方式: psql SELECT only
写入动作: 0
Dagster API/job/sensor/backfill 调用: 0
```

当前 Dagster storage 总量：

| 表 | 行数 |
| --- | ---: |
| `event_logs` | 6,381,606 |
| `runs` | 71,150 |
| `run_tags` | 522,615 |
| `asset_check_executions` | 1,217,342 |
| `asset_event_tags` | 73,264 |
| `dynamic_partitions` | 30,560 |
| `instigators` | 44 |

### 26.4 P9 dry-run 结果

新目标 `raw_index_daily` 当前没有正式 Dagster DB 记录：

| 对象 | 行数 |
| --- | ---: |
| `event_logs.asset_key='["raw_index_daily"]'` | 0 |
| `asset_check_executions.asset_key='["raw_index_daily"]'` | 0 |
| `asset_event_tags.asset_key='["raw_index_daily"]'` | 0 |
| `asset_keys.asset_key='["raw_index_daily"]'` | 0 |

旧 by-code raw 候选：

| 候选对象 | 行数 / 数量 | 范围 |
| --- | ---: | --- |
| `raw_tushare_index_daily_by_code` asset events | 48,515 | event id `1439487` 到 `6622347`，`2026-05-25 10:19:38` 到 `2026-06-22 17:14:35` |
| 其中 materialization | 23,780 | 同上 |
| 其中 planned materialization | 24,734 | 同上 |
| 其中 freshness state change | 1 | `2026-05-25 10:19:38` |
| 旧 raw-by-code check executions | 123,684 | evaluation event id `1439537` 到 `6622391` |
| 旧 raw-by-code check succeeded | 118,909 | 5 个旧 check 各约 23,782 条 |
| 旧 raw-by-code check planned | 4,775 | 5 个旧 check 各约 954 到 956 条 |
| `asset_event_tags` old by-code | 23,782 | key 为 `dagster/data_version` |

旧 job / run 候选：

| job | runs | event_logs | run_tags | 当前判断 |
| --- | ---: | ---: | ---: | --- |
| `index_daily_update_job` | 24,741 | 1,634,475 | 206,649 | 旧 per-code raw 更新 job，P9 候选，但不建议默认和 asset/check 事件一起删除。 |
| `index_daily_history_backfill_job` | 9 | 200,409 | 28 | 早期历史 backfill，P9 二级候选。 |
| `index_daily_repair_by_codes_job` | 1 | 31,553 | 5 | 早期 repair job，P9 二级候选。 |
| `index_daily_active_pool_initialize_job` | 1 | 56 | 0 | 早期 active pool 资产历史，P9 二级候选。 |
| `index_daily_active_pool_update_job` | 5 | 332 | 4 | 早期 active pool 资产历史，P9 二级候选。 |
| `silver_index_daily_update_job` | 6,531 | 570,168 | 45,559 | 默认不作为 P9 删除候选；`silver_index_daily` 历史仍是正式资产历史。 |

其它旧 index daily asset 历史：

| asset | event rows | 当前判断 |
| --- | ---: | --- |
| `raw_tushare_index_daily` | 19,792 | 更早的旧 raw 资产历史，当前 active code 未引用；可列为二级候选，但必须单独确认是否还需要保留调试链路。 |
| `silver_index_daily_active_pool` | 14 | 早期 active pool 资产历史，当前 active code 未引用；可列为二级候选。 |
| `silver_index_daily` | 保留 | 正式 silver 资产历史，P9 不删。 |

instigator / cursor dry-run：

| id | 当前状态 | 识别结果 | 当前判断 |
| ---: | --- | --- | --- |
| `1827` | `RUNNING SENSOR` | `job_name: index_daily_sensor` | 旧 raw sensor state。P7 删除旧 sensor 后才可进入 P9 候选。 |
| `2173` | `RUNNING SENSOR` | `job_name: silver_index_daily_sensor` | silver sensor 仍会保留但语义会变；不能直接删除，需决定是 cursor schema 迁移还是重置 cursor。 |

必须排除：

| 对象 | 当前数量 | 原因 |
| --- | ---: | --- |
| `dynamic_partitions.cn_a_index_ts_codes` | 946 | 运行时 Lake 期望 code set，不能清理。 |
| `dynamic_partitions.cn_a_index_trade_days` | 6,411 | index daily trade-date partitions，不能清理。 |
| `raw_index_daily` | 0 | 新目标，未来 P9 永远排除。 |
| `silver_index_daily` | 已有正式历史 | 下游继续消费，不能作为旧数据清理。 |

### 26.5 P9 dry-run 判定

当前判定：**禁止 apply**。

原因：

1. 当前 active source 仍引用旧 `raw_tushare_index_daily_by_code`、旧 raw-by-code checks、旧 by-code path、旧 by-code readiness 和旧 per-code sensor。
2. `index_daily_update_job` run history 关联 `event_logs` 超过 160 万行、`run_tags` 超过 20 万行，清理粒度必须单独拍板；不能把 run history 清理混入 asset/check 事件清理。
3. `silver_index_daily_sensor` 的 instigator state 仍是 RUNNING，且新链路仍会保留 silver sensor；该 cursor 只能迁移或重置，不能按“旧 sensor”直接删。

P9 最小可执行前置条件：

1. P7 后 active source 旧 by-code symbol 静态扫描为 0。
2. 新 `raw_index_daily` 和 `silver_index_daily` readiness 只读取新 asset/check/file facts。
3. 新 raw/silver sensors 已确认不读取旧 instigator cursor。
4. P9 dry-run 重跑，新 `raw_index_daily` 候选仍为 0。
5. 用户明确拍板清理粒度：只清旧 raw asset/check 历史，还是同时治理旧 run history。
