# Dagster Market Major Indices Sensor 热路径性能治理 LLD

更新时间：2026-06-21

依据文档：

1. [Dagster Market Major Indices Sensor 热路径性能治理技术设计方案](dagster-market-major-indices-sensor-performance-governance-plan.md)
2. [Dagster Bounded Continuity Selector 基础能力 LLD](dagster-bounded-continuity-selector-foundation-low-level-design.md)
3. [Dagster 非股票分钟线连续性治理专项方案](dagster-non-stk-mins-continuity-governance-plan.md)

状态：开发前 LLD，待按 P4 阶段执行。

范围：只处理 `market_major_indices_daily_sensor` 及其热路径 readiness。P4 不处理其它非分钟线资产族，不修改 run key、run config、job/sensor/asset/check 名称，不新增持久化状态实体，不运行 `dg`，不读取正式 Dagster runtime。

## 1. 当前代码事实

当前入口：

```text
lake_console/orchestrator/src/orchestrator/defs/sensors/market_major_indices_daily_sensor.py
```

当前问题：

1. `_latest_registered_trade_date(...)` 只选择 latest registered index trade day。
2. `gold_market_major_indices_daily_ready_for_trade_date(...)` 在 sensor 热路径读取 Dagster event/check history。
3. `silver_index_daily_ready_for_trade_date(...)` 和 `silver_index_basic_ready(...)` 也读取 Dagster event/check history。
4. 已经存在的 `check_market_major_indices_inputs_for_trade_date(...)` 是 seed-driven DuckDB 小规模检查，可保留为 selected-date gate。
5. run key 已通过 `build_asset_update_run_key(subject="market_major_indices_daily", unit_id=target_trade_date)` 生成，口径正确，必须保留。

已完成只读 profiling：

| 项 | 结果 |
| --- | --- |
| 单日 `gold_market_major_indices_daily_ready_for_trade_date(...)` | 约 47s / 超时。 |
| 当前热路径最坏读取模型 | gold 10 checks + silver 7 checks + index basic 6 checks，最多 23 次 check history 查询。 |

结论：P4 不能把旧单日 readiness wrapper 放入 20/60 日循环，也不能继续在 selected-date 上调用它们。

## 2. 开发目标

1. `market_major_indices_daily_sensor` 目标从 latest registered 改为 expected calendar 中的 first not-ready gold。
2. 新增 expected registered gap guard。
3. 使用 DuckDB/lake fact readiness 等价判断 gold blocking checks。
4. selected-date upstream gate 改为 lake readiness，不调用旧 Dagster event history wrapper。
5. 保留 seed/input gate：`check_market_major_indices_inputs_for_trade_date(...)`。
6. 保留已 materialized 但 checks failed 时 skip、不自动重跑、不推进后续日期的安全口径。
7. cursor 输出 continuity summary 与 batch summary，不写逐文件明细。

## 3. 不做事项

1. 不调整 Dagster gRPC timeout。
2. 不修改 `asset_readiness_status(...)` 的全局实现。
3. 不降低 `CHECK_HISTORY_LIMIT` 作为性能修复。
4. 不新增 status manifest、summary asset、readiness asset、数据库表或配置项。
5. 不新增或改名 asset/check/job/sensor。
6. 不把 `checks_passed=True` 解释为 Dagster 历史 check event 已经存在。
7. 不处理 `index_daily_sensor.py` / `silver_index_daily_sensor.py` 的 P5 guard；P5 是上游 guard 阶段。

## 4. 目标文件

新增：

```text
lake_console/orchestrator/src/orchestrator/defs/asset_guards/market_major_indices_lake_readiness.py
lake_console/orchestrator/tests/test_market_major_indices_lake_readiness.py
```

更新：

```text
lake_console/orchestrator/src/orchestrator/defs/sensors/market_major_indices_daily_sensor.py
lake_console/orchestrator/tests/test_market_major_indices_daily_sensor.py
lake_console/orchestrator/tests/test_run_contract_static_gates.py
```

依赖基础模块：

```text
orchestrator.defs.asset_guards.bounded_continuity
```

## 5. 数据模型

P4 不新增平行长期数据模型，统一复用基础 LLD 的：

```text
ContinuityExpectedDateWindow
ContinuityRegisteredGapStatus
ContinuityDateReadiness
ContinuityBatchReadiness
ContinuitySelection
```

主要指数业务细节写入：

1. `ContinuityDateReadiness.failed_check_names`
2. `ContinuityDateReadiness.missing_check_names`
3. `ContinuityDateReadiness.missing_file_paths`
4. `ContinuityDateReadiness.summary`

`summary` 允许包含：

```text
row_count
active_seed_code_count
registered_code_count
missing_seed_code_count
rank_mismatch_count
price_sanity_failed_count
schema_error
scan_error_code
```

禁止在 summary 中写入完整 seed code 列表、完整文件列表或所有失败行。

## 6. Helper 设计

### 6.1 `batch_market_major_indices_lake_readiness(...)`

文件：

```text
asset_guards/market_major_indices_lake_readiness.py
```

签名：

```python
def batch_market_major_indices_lake_readiness(
    *,
    connection,
    lake_root_path: Path,
    expected_trade_dates: Sequence[str],
    registered_index_codes: Sequence[str],
    sample_limit: int = DEFAULT_CONTINUITY_SAMPLE_LIMIT,
) -> ContinuityBatchReadiness:
    ...
```

职责：

1. 对最近 60 个 expected index trade dates 一次性判断 `gold_market_major_indices_daily` readiness。
2. 不读取 Dagster instance。
3. 不调用 `asset_readiness_status(...)`。
4. 不调用 `gold_market_major_indices_daily_ready_for_trade_date(...)`。
5. 用 lake parquet + seed + registered index codes 复用正式 blocking check 语义。

每个日期的 `ContinuityDateReadiness` 口径：

| 场景 | materialized | checks_passed | ready | reason |
| --- | --- | --- | --- | --- |
| gold 文件缺失 | false | false | false | `missing_gold_file` |
| gold 文件存在且 checks 全部通过 | true | true | true | `ready` |
| gold 文件存在但任一 check 失败 | true | false | false | `blocking_checks_failed` |
| DuckDB scan error | 文件存在则 true，否则 false | false | false | `scan_error` |

### 6.2 Gold checks 等价语义

必须覆盖以下正式 blocking check 语义：

| check | 等价实现 |
| --- | --- |
| `gold_market_major_indices_daily_file_exists` | 目标 partition parquet 文件存在。 |
| `gold_market_major_indices_daily_required_columns_and_types` | `DESCRIBE` 结果匹配 `MARKET_MAJOR_INDICES_DAILY_COLUMNS` / schema contract。 |
| `gold_market_major_indices_daily_partition_date_matches` | 文件内 `trade_date` 全部等于 partition。 |
| `gold_market_major_indices_daily_row_count_matches_seed` | 行数等于该日 active seed 行数。 |
| `gold_market_major_indices_daily_seed_codes_present` | active seed codes 全部在 gold 文件中出现。 |
| `gold_market_major_indices_daily_unique_ts_code` | `ts_code` 不重复。 |
| `gold_market_major_indices_daily_rank_matches_active_seed_order` | rank 与 active seed order 一致。 |
| `gold_market_major_indices_daily_price_sanity` | OHLC / pre_close 非负且高低价区间合法。 |
| `gold_market_major_indices_seed_codes_exist_in_index_basic` | active seed codes 存在于 `silver_index_basic`。 |
| `gold_market_major_indices_seed_codes_exist_in_registered_index_ts_codes` | active seed codes 存在于 registered index codes。 |

实现原则：

1. DuckDB SQL 聚合统计，不做 Python 明细行循环。
2. 对 60 个 partition 文件可以按 path 规划后批量 UNION / relation scan；若文件缺失，先在 Python 层记录 missing，不把缺失路径传给 DuckDB 造成异常。
3. schema 检查可以 bounded metadata scan，最多 60 个 gold 文件。

### 6.3 `silver_index_daily_lake_readiness_for_trade_date(...)`

签名：

```python
def silver_index_daily_lake_readiness_for_trade_date(
    *,
    connection,
    lake_root_path: Path,
    trade_date: str,
    registered_index_codes: Sequence[str],
    sample_limit: int = DEFAULT_CONTINUITY_SAMPLE_LIMIT,
) -> ContinuityDateReadiness:
    ...
```

职责：

1. 只判断 selected gold target date 的 `silver_index_daily` upstream readiness。
2. 不做 60 日 silver batch。
3. 不调用 `silver_index_daily_ready_for_trade_date(...)`。

必须覆盖当前 `SILVER_INDEX_DAILY_BLOCKING_CHECKS` 的 lake 等价语义：

1. required columns/types。
2. row count positive。
3. partition date matches。
4. unique `ts_code + trade_date`。
5. conflicting duplicate absent。
6. price sanity。
7. registered code coverage。

### 6.4 `silver_index_basic_lake_readiness(...)`

签名：

```python
def silver_index_basic_lake_readiness(
    *,
    connection,
    lake_root_path: Path,
    sample_limit: int = DEFAULT_CONTINUITY_SAMPLE_LIMIT,
) -> ContinuityDateReadiness:
    ...
```

职责：

1. 每个 sensor tick 最多检查一次 unpartitioned `silver_index_basic`。
2. 不调用 `silver_index_basic_ready(...)`。

必须覆盖：

1. file exists。
2. required columns/types。
3. row count positive。
4. unique `ts_code`。
5. required fields non-null。
6. no terminated indexes。

## 7. Sensor 改造

文件：

```text
sensors/market_major_indices_daily_sensor.py
```

### 7.1 import 清理

删除：

```python
gold_market_major_indices_daily_ready_for_trade_date
silver_index_daily_ready_for_trade_date
silver_index_basic_ready
```

新增：

```python
load_expected_trade_date_window
build_registered_gap_status
select_first_not_ready_trade_date
build_continuity_cursor_details
batch_market_major_indices_lake_readiness
silver_index_daily_lake_readiness_for_trade_date
silver_index_basic_lake_readiness
```

### 7.2 目标选择流程

目标流程：

```text
evaluated_at
  -> load expected index trade date window
  -> read cn_a_index_trade_days / cn_a_index_ts_codes
  -> registered gap guard
  -> batch gold lake readiness
  -> select first not-ready gold
  -> if all ready: skip
  -> if materialized checks failed: skip, manual required
  -> selected date silver index daily lake readiness
  -> silver index basic lake readiness
  -> seed/input gate
  -> build_run_request(...)
```

### 7.3 SkipReason 口径

| 场景 | SkipReason 主语义 |
| --- | --- |
| 无 registered trade days | 没有注册指数交易日分区。 |
| 无 registered index codes | 没有注册指数代码分区。 |
| expected registered gap | 指数交易日分区存在注册缺口，等待注册 sensor 补齐。 |
| gold all ready | 最近 60 个 expected index dates 的主要指数 gold 都已 ready。 |
| gold materialized checks failed | 目标 gold 已生成但 blocking checks 未全绿，需人工处理。 |
| selected silver not ready | 等待 selected date 的 `silver_index_daily` lake readiness。 |
| index basic not ready | 等待 `silver_index_basic` lake readiness。 |
| seed/input not ready | 主要指数 seed/input 门禁未满足。 |

### 7.4 RunRequest

保持现有口径：

```python
build_run_request(
    run_key=build_asset_update_run_key(
        subject="market_major_indices_daily",
        unit_id=selected_trade_date,
    ),
    partition_key=selected_trade_date,
)
```

禁止：

1. 直接 `dg.RunRequest(...)`。
2. 手写 `run_key=f"..."`
3. 解析 run key 生成 config。

### 7.5 Cursor

现有 `_cursor_payload(...)` 扩展字段：

```text
continuity_status
gold_batch_status
selected_silver_status
index_basic_status
input_status
```

约束：

1. 保留 `registered_trade_day_count`、`registered_code_count`、`selected_trade_date`、`reason`。
2. 不写完整 60 日 status map。
3. 不写完整 seed codes。
4. `checks_passed` 字段必须说明是 lake-derived checks，不代表 Dagster event log 已有 passed check event。

## 8. 测试计划

### 8.1 Helper 测试

新增：

```text
tests/test_market_major_indices_lake_readiness.py
```

覆盖：

1. 60 日窗口全 ready。
2. 某日 gold 文件缺失，返回 `materialized=False`。
3. schema 缺列，返回 `materialized=True, checks_passed=False`。
4. `trade_date` 不匹配 partition，失败。
5. seed code 缺失，失败。
6. rank 顺序不匹配，失败。
7. price sanity 失败。
8. seed code 不在 `silver_index_basic`，失败。
9. seed code 不在 registered index codes，失败。
10. `silver_index_daily` selected-date upstream 缺文件。
11. `silver_index_basic` snapshot 缺文件。
12. unknown date fail closed。
13. cursor payload 不包含逐文件大对象。

### 8.2 Sensor 测试

更新：

```text
tests/test_market_major_indices_daily_sensor.py
```

覆盖：

1. expected 有 `2026-06-15/2026-06-16`，`2026-06-15` gold 缺失，只提交 `2026-06-15`。
2. `2026-06-15` gold 文件存在但 checks failed，skip，不提交 `2026-06-16`。
3. `2026-06-15` ready、`2026-06-16` missing，提交 `2026-06-16`。
4. registered gap 存在，skip，不调用 batch gold readiness。
5. selected date silver not ready，skip。
6. index basic not ready，skip。
7. seed/input gate not ready，skip。
8. run key 保持 `market_major_indices_daily:{trade_date}`。
9. cursor 包含 continuity summary。

### 8.3 静态门禁

更新：

```text
tests/test_run_contract_static_gates.py
```

断言 `market_major_indices_daily_sensor.py` 不得出现：

```text
gold_market_major_indices_daily_ready_for_trade_date
silver_index_daily_ready_for_trade_date
silver_index_basic_ready
asset_readiness_status
_latest_registered_trade_date
run_key=f
dg.RunRequest(
RunRequest(
```

断言 helper 不得出现：

```text
get_asset_check_execution_history
asset_readiness_status
silver_index_daily_ready_for_trade_date
silver_index_basic_ready
gold_market_major_indices_daily_ready_for_trade_date
```

## 9. 性能门禁

| 项 | P4 目标 |
| --- | --- |
| expected window | 最近 60 个 expected index trade dates。 |
| Dagster event/check history | 0 次。 |
| gold files | 最多 60 个 partition parquet。 |
| silver files | selected date 1 个 partition parquet。 |
| index basic | 1 个 snapshot parquet。 |
| seed | 仓库 seed，小规模。 |
| dynamic partitions | `cn_a_index_trade_days`、`cn_a_index_ts_codes` 各 1 次。 |
| 稳态 sensor tick | < 5s。 |
| 异常完整扫描 | < 10s。 |
| 拒绝阈值 | > 15s 停止并重新设计。 |

开发前如需正式 profiling，必须单独审批；本 LLD 不授权读取正式 Dagster instance 或运行 `dg`。

## 10. 验收清单

P4 完成时必须逐条对账：

1. `market_major_indices_daily_sensor` 不再 latest-only。
2. sensor 热路径不读取 Dagster event/check history。
3. gold readiness 覆盖所有正式 blocking check 等价语义。
4. selected-date silver/index basic gate 不调用旧 readiness wrappers。
5. `check_market_major_indices_inputs_for_trade_date(...)` 保留。
6. run key、run config、job/sensor 名称不变。
7. 已 materialized checks failed 不自动重跑、不推进后续日期。
8. 静态门禁防止旧 wrapper 回流。
9. 本地测试和性能样本记录在 P4 收口说明中。
