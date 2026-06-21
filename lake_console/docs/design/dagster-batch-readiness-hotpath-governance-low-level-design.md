# Dagster Batch Readiness Hot Path 性能治理 LLD

更新时间：2026-06-21

依据文档：[Dagster Batch Readiness Hot Path 性能治理专项方案](dagster-batch-readiness-hotpath-governance-plan.md)

状态：P0 已完成。P0A、P0B、P0C、P0D、P0E、P0F、P0G 均已完成。本文档是编码级设计和阶段验收依据。

## 0. 当前进度与阶段边界

| 阶段 | 状态 | 开发边界 |
| --- | --- | --- |
| P0A 窗口前轻量 skip | 已完成 | 只调整 qfq daily / qfq factor repair sensor 窗口前执行顺序；不改变 run key / run config。 |
| P0B qfq gold profiling | 已完成 | 只读 profiling，不改生产代码；输出写 `/private/tmp`。 |
| P0C qfq gold true batch | 已完成 | 只重写 `batch_gold_stk_mins_qfq_lake_readiness(...)` 的读取模型；不降低 check 语义。 |
| P0D sensor 分层短路 | 已完成 | qfq daily sensor 已按 silver -> adj factor -> gold lazy load；silver 阻断时不加载 adj/gold，adj 阻断时不加载 gold。提交：`7c7eb0e6`。 |
| P0E 全部 helper 门禁与性能回归 | 已完成 | 统一测试所有 sensor hot path batch helper；其它 helper 性能测试固定放在本阶段并已执行。提交：`b70c51c0`。 |
| P0F 本地回归与性能结果落档 | 已完成 | 已跑本地目标测试和必要静态门禁；不运行 `dg`。本轮文档提交记录最终结果。 |
| P0G 文档与长期规范收口 | 已完成 | 长期规范和关联方案文档状态已同步；P0 收口完成。 |

### 0.1 其它 helper 性能测试位置

其它 helper 的性能测试固定在 P0E，不在 P0B。

原因：

1. P0B 是 qfq gold 单点根因定位，目的是证明旧 qfq gold 实现的耗时构成。
2. P0C 会重写 qfq gold batch，P0D 会改变 sensor 调用顺序；在这两步之前测全 helper，不能代表最终 hot path。
3. P0E 是统一验收阶段，必须把 qfq gold、raw/silver 分钟线、adj factor、major indices、market breadth、ClickHouse readiness helper 一起跑完。
4. P0E 如果发现其它 helper 也有同等级超时风险，必须新增修复阶段，不能只写成“已知风险”。

### 0.2 P0E / P0F 当前验收事实

P0E 已完成，落点如下：

```text
tests/test_stk_mins_continuity_performance.py
tests/test_batch_readiness_hotpath_performance.py
tests/test_run_contract_static_gates.py
```

P0E 没有修改生产运行逻辑；它只补充门禁和本地性能样本，用于证明其它 helper 没有同等级 hot path timeout 风险。其它 helper 的性能测试已经在 P0E 完成，不再后移。

P0E 本地临时性能样本结果：

| Helper | 范围 | elapsed_ms / 调用次数 | 验收 |
| --- | --- | ---: | --- |
| `batch_raw_stk_mins_lake_readiness` | 10 天 × 5 频度 | `27.43 ms` | 通过 |
| `batch_silver_stk_mins_lake_readiness` | 10 天 × 5 频度 | `47.74 ms` | 通过 |
| `batch_gold_stk_mins_qfq_lake_readiness` | 10 天 × 7 频度 | `119.37 ms` | 通过 |
| `batch_raw_adj_factor_lake_readiness` | 10 天 | `19 ms` | 通过 |
| `batch_silver_adj_factor_lake_readiness` | 10 天 | `16 ms` | 通过 |
| `batch_adj_factor_lake_readiness` | 10 天 | `17 ms` | 通过 |
| `batch_market_major_indices_lake_readiness` | 10 天 | `9 ms` | 通过 |
| `batch_gold_market_breadth_lake_readiness` | 10 天 | `15 ms` | 通过 |
| `batch_gold_stock_return_distribution_lake_readiness` | 10 天 | `20 ms` | 通过 |
| `batch_clickhouse_market_breadth_readiness` | 10 天 fake client | `6 ms`，`execute_count=1` | 通过 |
| `batch_prod_clickhouse_market_breadth_readiness` | 10 天 fake client | `0 ms`，local/prod 各 `1` 次 | 通过 |

P0F 本地目标回归已完成：

```text
119 passed, 5 warnings in 5.12s
```

执行命令：

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator
PYTHONPATH=src uv run --project . --with pytest python -m pytest \
  tests/test_stk_mins_lake_readiness.py \
  tests/test_stk_mins_continuity_performance.py \
  tests/test_batch_readiness_hotpath_performance.py \
  tests/test_stock_mins_daily_continuity_sensors.py \
  tests/test_stk_mins_qfq_m9a_sensor_contracts.py \
  tests/test_stk_mins_qfq_m9c_sensor_contracts.py \
  tests/test_run_contract_static_gates.py
```

补充静态检查：

1. `git diff --check` 通过。
2. 单日 qfq helper symbol 允许继续存在于旧单日 helper 定义中；禁止的是 `batch_gold_stk_mins_qfq_lake_readiness(...)` body 回调这些 helper，该约束已经落入 `test_run_contract_static_gates.py`。

## 1. 目标

本 LLD 只解决 sensor hot path 中 batch readiness 名实不符和 qfq gold readiness 超时风险。

必须达成：

1. `stock_mins_qfq_daily_sensor`、`stock_mins_qfq_factor_repair_sensor` 在运行窗口前直接轻量 skip，不执行任何重 DuckDB readiness。
2. `batch_gold_stk_mins_qfq_lake_readiness(...)` 从日期乘频度重复重扫，改成窗口级 batch 读取模型。
3. qfq gold readiness 保留 native 1/5/15/30/60 与 derived 90/120 全部正式 blocking check 语义。
4. qfq daily sensor 按 silver -> adj factor -> gold qfq 顺序短路；上游已阻断时不跑 gold qfq 重查。
5. qfq factor repair sensor 只在 gold qfq selected target ready 后读取 factor repair status。
6. 所有 sensor hot path batch helper 都必须完成一次性能回归和门禁测试；其它 helper 不全量重写，但不能无测试放过。

## 2. 不做事项

1. 不改 run key。
2. 不改 run config。
3. 不新增 asset、job、sensor、check、resource、database table、summary asset、readiness asset、status manifest 或配置项。
4. 不降低 blocking check 语义。
5. 不把文件存在、row count 当作 ready。
6. 不把 bootstrap runless event 写入逻辑接入日常 sensor。
7. 不运行 `dg`，不读写正式 Dagster runtime，不写正式 lake。
8. 不全量重写其它 batch helper；只做性能回归、门禁与必要的后续风险升级。

## 3. 当前代码事实

### 3.1 高危调用链

当前 `batch_gold_stk_mins_qfq_lake_readiness(...)` 位于：

```text
lake_console/orchestrator/src/orchestrator/defs/asset_guards/stk_mins_lake_readiness.py
```

当前结构：

```text
batch_gold_stk_mins_qfq_lake_readiness
  -> for trade_date in expected_trade_dates
       -> _gold_qfq_status_for_trade_date
            -> for freq in STK_MINS_QFQ_NATIVE_FREQS
                 -> _gold_qfq_native_counts_for_trade_date
            -> for freq in STK_MINS_QFQ_DERIVED_FREQS
                 -> _gold_qfq_derived_counts_for_trade_date
```

问题：

1. `batch` 外观只体现在返回 `StkMinsBatchReadiness`。
2. 内部仍按日期重复执行 native / derived 重 SQL。
3. derived 90/120 每个日期都会重复发现 source year paths、构造 diagnostics SQL、计算 expected paths 和 formula comparison。
4. sensor 10 天窗口仍可能接近或超过 60 秒 gRPC timeout。

### 3.2 直接消费者

直接正式消费者：

```text
stock_mins_qfq_daily_sensor.py
stock_mins_qfq_factor_repair_sensor.py
```

文本审计补充说明：CodeGraph 对嵌套闭包里的 sensor 调用识别不完整，因此调用方影响面以 CodeGraph + `rg` 文本审计共同确认。

### 3.3 可复用参考

可参考但不能直接照搬：

```text
bootstrap/stk_mins_qfq_bootstrap_events.py
  audit_stk_mins_qfq_bootstrap_batch(...)
  _batch_silver_counts(...)
  _batch_gold_counts(...)
  _batch_factor_coverage_counts(...)
  _batch_formula_counts(...)

bootstrap/stk_mins_qfq_derived_bootstrap_events.py
  audit_stk_mins_qfq_derived_bootstrap_batch(...)
  _batch_derived_diagnostics_counts(...)
  _batch_derived_formula_counts(...)
```

约束：

1. 只能复用或抽取纯只读 SQL / 聚合统计能力。
2. 不得把 runless event report、instance 写入、bootstrap dry-run/apply 语义带进 sensor helper。

## 4. 目标文件

生产代码目标文件：

```text
lake_console/orchestrator/src/orchestrator/defs/asset_guards/stk_mins_lake_readiness.py
lake_console/orchestrator/src/orchestrator/defs/sensors/stock_mins_qfq_daily_sensor.py
lake_console/orchestrator/src/orchestrator/defs/sensors/stock_mins_qfq_factor_repair_sensor.py
```

测试目标文件：

```text
lake_console/orchestrator/tests/test_stk_mins_lake_readiness.py
lake_console/orchestrator/tests/test_stk_mins_continuity_performance.py
lake_console/orchestrator/tests/test_stock_mins_daily_continuity_sensors.py
lake_console/orchestrator/tests/test_stk_mins_qfq_m9a_sensor_contracts.py
lake_console/orchestrator/tests/test_stk_mins_qfq_m9c_sensor_contracts.py
lake_console/orchestrator/tests/test_run_contract_static_gates.py
```

文档目标文件：

```text
lake_console/docs/design/dagster-batch-readiness-hotpath-governance-plan.md
lake_console/docs/design/dagster-batch-readiness-hotpath-governance-low-level-design.md
lake_console/docs/design/dagster-stk-mins-qfq-sensor-hotpath-performance-fix-plan.md
lake_console/docs/design/dagster-stk-mins-continuity-performance-optimization-plan.html
lake_console/docs/design/dagster-stk-mins-continuity-performance-optimization-low-level-design.html
```

## 5. P0A 窗口前轻量 Skip

### 5.1 `stock_mins_qfq_daily_sensor`

当前问题：`run_window_started` 计算后，代码先加载 expected dates、partitions，并可能进入 batch readiness，之后才判断窗口。

目标顺序：

```python
evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)
run_window_started = evaluated_at.time() >= STOCK_MINS_QFQ_DAILY_RUN_START
if not run_window_started:
    decision = StockMinsQfqDailyUpdateDecision(
        target_trade_date=None,
        run_window_started=False,
        selected_trade_date=None,
        reason="股票分钟线 gold qfq 日常更新窗口尚未到 20:10，暂不触发。",
    )
    return dg.SensorResult(
        skip_reason=decision.reason,
        cursor=_cursor_payload(... lightweight fields only ...),
    )
```

窗口前禁止调用：

1. `_load_stock_mins_qfq_expected_trade_dates(...)`
2. `context.instance.get_dynamic_partitions(...)`
3. `batch_silver_stk_mins_lake_readiness(...)`
4. `batch_adj_factor_lake_readiness(...)`
5. `batch_gold_stk_mins_qfq_lake_readiness(...)`

窗口前 cursor 允许字段：

```text
job_name
run_window_started=false
reason
schema_version
evaluated_at
```

窗口前 cursor 禁止字段携带重扫描结果：

```text
continuity_status
silver_batch_status
adj_factor_batch_status
gold_batch_status
silver_status
adj_factor_status
gold_status
```

### 5.2 `stock_mins_qfq_factor_repair_sensor`

目标顺序同上，窗口为 `STOCK_MINS_QFQ_FACTOR_REPAIR_RUN_START = 20:40`。

窗口前禁止调用：

1. `_load_stock_mins_qfq_expected_trade_dates(...)`
2. `context.instance.get_dynamic_partitions(...)`
3. `batch_gold_stk_mins_qfq_lake_readiness(...)`
4. `gold_stk_mins_qfq_factor_repair_status(...)`

## 6. P0B qfq gold 只读 Profiling

P0B 是开发前或开发中诊断步骤，不改生产代码。若读取正式 lake，必须单独列命令等待批准。

### 6.1 profiling 输出

输出到：

```text
/private/tmp/qfq_gold_batch_readiness_profile_YYYYMMDD_HHMMSS.json
```

JSON 必须包含：

```json
{
  "expected_start_date": "...",
  "expected_end_date": "...",
  "expected_count": 10,
  "native": {
    "freqs": [1, 5, 15, 30, 60],
    "path_planning_ms": 0,
    "schema_ms": 0,
    "counts_ms": 0,
    "coverage_ms": 0,
    "formula_ms": 0,
    "file_count": 0,
    "sql_count": 0
  },
  "derived": {
    "freqs": [90, 120],
    "source_path_discovery_ms": 0,
    "diagnostics_ms": 0,
    "expected_paths_ms": 0,
    "target_counts_ms": 0,
    "formula_ms": 0,
    "source_file_count": 0,
    "target_file_count": 0,
    "sql_count": 0
  },
  "total_elapsed_ms": 0,
  "slowest_steps": []
}
```

### 6.2 profiling 禁止事项

1. 不运行 `dg`。
2. 不写 Dagster event。
3. 不写 lake。
4. 不修改 cursor。
5. 不以 row count 粗筛结果替代完整语义结论。

## 7. P0C qfq gold True Batch 设计

### 7.1 保持公开函数签名

保留现有签名，避免扩大调用方影响：

```python
def batch_gold_stk_mins_qfq_lake_readiness(
    *,
    connection,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
    registered_trade_days: Sequence[str],
    full_semantics: bool = True,
) -> StkMinsBatchReadiness:
    ...
```

### 7.2 新增内部数据结构

P0C 实现后，当前代码已保留 `_GoldQfqNativePathPlan`，并把 derived 侧收敛为按窗口日期直接返回 `derived_counts_by_key` 与 `derived_missing_paths_by_key`，没有长期保留单独的 `_GoldQfqDerivedPathPlan` dataclass。后续维护以当前代码事实为准：derived 侧不要求为了贴合旧草案而补一个无实际用途的 dataclass。

P0C 当前核心调用链：

```text
batch_gold_stk_mins_qfq_lake_readiness
  -> _gold_qfq_native_path_plans
  -> _gold_qfq_native_batch_counts
  -> _gold_qfq_derived_batch_counts
  -> _gold_qfq_statuses_from_batch_counts
```

以下原始设计片段保留为实现背景：native 侧需要明确 path plan；derived 侧只要保持窗口级 batch 统计和 `(trade_date, freq)` fan-out 即可。

```python
@dataclass(frozen=True)
class _GoldQfqNativePathPlan:
    trade_date: str
    freq: int
    silver_path: Path
    trade_adj_factor_path: Path
    expected_gold_paths: tuple[Path, ...]
    existing_gold_paths: tuple[Path, ...]
    missing_gold_paths: tuple[Path, ...]
```

概念上的 batch metrics 必须至少包含：

```text
native_counts_by_key: Mapping[(trade_date, freq), GoldStkMinsQfqCheckCounts]
derived_counts_by_key: Mapping[(trade_date, freq), GoldStkMinsQfqDerivedCheckCounts]
derived_missing_paths_by_key: Mapping[(trade_date, freq), tuple[Path, ...]]
```

当前代码直接用多个 mapping 传递，不要求为了形式统一新增 `_GoldQfqBatchMetrics` 类型。

Key 统一使用：

```text
(trade_date, freq)
```

### 7.3 新增内部 helper

建议新增：

```python
def _gold_qfq_native_path_plans(
    connection,
    *,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
) -> tuple[_GoldQfqNativePathPlan, ...]:
    ...
```

职责：

1. 对窗口日期与 native freqs 一次性生成 silver path、adj factor path、expected gold paths。
2. 不执行重公式 SQL。
3. 允许调用 `_gold_qfq_expected_paths(...)`，但必须在窗口 path planning 阶段集中完成。

Derived 侧当前不单独暴露 path plan helper，而是由 `_gold_qfq_derived_batch_counts(...)` 内部按 `target_freq + source_freq + year` 集中发现 source paths、计算 expected target paths、执行 diagnostics / target counts / formula comparison。

```python
def _gold_qfq_native_batch_counts(
    connection,
    *,
    native_plans: Sequence[_GoldQfqNativePathPlan],
    full_semantics: bool,
) -> Mapping[tuple[str, int], GoldStkMinsQfqCheckCounts]:
    ...
```

职责：

1. 聚合 existing gold paths 后批量执行 row count / path / duplicate / price SQL。
2. 聚合 silver paths 与 adj factor paths 后批量执行 coverage SQL。
3. 聚合 formula comparison，输出按 `(trade_date, freq)` 分组的 counts。

```python
def _gold_qfq_derived_batch_counts(
    connection,
    *,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
) -> tuple[
    Mapping[tuple[str, int], GoldStkMinsQfqDerivedCheckCounts],
    Mapping[tuple[str, int], tuple[Path, ...]],
]:
    ...
```

职责：

1. 按 `target_freq + source_freq + year` 合并 derived diagnostics。
2. 按 `target_freq + year` 合并 target gold counts。
3. 按 `target_freq + source_freq + year` 合并 derived formula comparison。
4. 每条 SQL 必须输出 `trade_date`，以便 fan-out。
5. 返回 `derived_counts_by_key` 和 `derived_missing_paths_by_key`，key 均为 `(trade_date, target_freq)`。

```python
def _gold_qfq_statuses_from_batch_counts(
    *,
    expected_trade_dates: Sequence[str],
    registered_trade_day_set: set[str],
    native_counts_by_key: Mapping[tuple[str, int], GoldStkMinsQfqCheckCounts],
    derived_counts_by_key: Mapping[tuple[str, int], GoldStkMinsQfqDerivedCheckCounts],
    missing_paths_by_trade_date: Mapping[str, tuple[Path, ...]],
    full_semantics: bool,
) -> dict[str, StkMinsDateReadiness]:
    ...
```

职责：

1. 按现有 `_gold_qfq_native_failed_check_names(...)` 和 `_gold_qfq_derived_failed_check_names(...)` 生成 failed checks。
2. 保持现有 missing file -> `materialized=False` 语义。
3. 保持现有 materialized + failed checks -> `materialized=True, checks_passed=False` 语义。
4. 保持 `dataset="gold_stk_mins_qfq"` 和 `freq_count=len(STK_MINS_QFQ_FREQS)`。

### 7.4 禁止继续使用的结构

`batch_gold_stk_mins_qfq_lake_readiness(...)` 正式 body 中禁止：

```python
{
    trade_date: _gold_qfq_status_for_trade_date(...)
    for trade_date in expected_trade_dates
}
```

也禁止：

```python
for trade_date in expected_trade_dates:
    _gold_qfq_native_counts_for_trade_date(...)
    _gold_qfq_derived_counts_for_trade_date(...)
```

兼容保留：

1. `_gold_qfq_native_counts_for_trade_date(...)` 可暂时保留给单日测试或后续清理，不再由 batch helper 调用。
2. `_gold_qfq_derived_counts_for_trade_date(...)` 可暂时保留给单日测试或后续清理，不再由 batch helper 调用。

若 P0C 实现后这两个单日 helper 没有正式调用方，应在同阶段删除，避免长期留下回流入口。

### 7.5 Native 批量 SQL 口径

Native freqs：

```text
1, 5, 15, 30, 60
```

必须覆盖现有 checks：

1. `GOLD_STK_MINS_QFQ_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK`
2. `GOLD_STK_MINS_QFQ_SCHEMA_MATCHES_CONTRACT_CHECK`
3. `GOLD_STK_MINS_QFQ_FREQ_DATE_PATH_MATCH_CHECK`
4. `GOLD_STK_MINS_QFQ_UNIQUE_TS_CODE_TRADE_TIME_CHECK`
5. `GOLD_STK_MINS_QFQ_PRICE_SANITY_CHECK`
6. `GOLD_STK_MINS_QFQ_ROW_COUNT_MATCHES_SILVER_CHECK`
7. `GOLD_STK_MINS_QFQ_FACTOR_COVERAGE_COMPLETE_CHECK`
8. `GOLD_STK_MINS_QFQ_FORMULA_MATCHES_SILVER_ADJ_FACTOR_CHECK`

SQL 输出必须至少能分组：

```text
trade_date
freq
```

Native batch 可以按 freq 分批执行，不能按 trade_date 分批执行。

### 7.6 Derived 批量 SQL 口径

Derived freqs：

```text
90, 120
```

必须覆盖现有 checks：

1. `GOLD_STK_MINS_QFQ_FILE_EXISTS_AND_ROW_COUNT_POSITIVE_CHECK`
2. `GOLD_STK_MINS_QFQ_SCHEMA_MATCHES_CONTRACT_CHECK`
3. `GOLD_STK_MINS_QFQ_FREQ_DATE_PATH_MATCH_CHECK`
4. `GOLD_STK_MINS_QFQ_UNIQUE_TS_CODE_TRADE_TIME_CHECK`
5. `GOLD_STK_MINS_QFQ_PRICE_SANITY_CHECK`
6. `GOLD_STK_MINS_QFQ_DERIVED_SOURCE_READY_CHECK`
7. `GOLD_STK_MINS_QFQ_DERIVED_ROW_COUNT_MATCHES_SOURCE_WINDOWS_CHECK`
8. `GOLD_STK_MINS_QFQ_DERIVED_FORMULA_MATCHES_SOURCE_CHECK`

Derived batch 必须按下面维度合并：

```text
target_freq
source_freq
year
partition_keys in window for that year
```

禁止每个 `trade_date` 单独调用：

```python
build_gold_stk_mins_qfq_derived_diagnostics_sql(... partition_keys=[trade_date])
build_gold_stk_mins_qfq_derived_select_sql(... partition_keys=[trade_date])
```

允许按 year 分批的原因：

1. qfq gold 物理文件按 `freq/ts_code/year` 组织。
2. 10 天窗口可能跨年。
3. 跨年时按 year 分批可以避免读取无关 year files。

## 8. P0D Sensor 分层短路

### 8.1 qfq daily

目标执行顺序：

```text
1. run window guard
2. expected calendar + silver registered gap
3. silver batch readiness
4. select first silver not-ready
5. if selected silver status not ready:
     skip，不调用 adj factor / gold qfq batch
6. adj factor batch readiness
7. if selected adj factor status not ready:
     skip，不调用 gold qfq batch
8. gold qfq batch readiness
9. selected target run decision
```

这会改变当前实现中的一个性能点：当前 `_batch_readiness_for_trade_date(...)` 第一次被调用时会一次性算 silver、adj factor、gold 三个 batch。P0D 后必须拆成按阶段 lazy load，避免银层或复权因子已阻断时还跑 qfq gold。

建议拆分：

```python
silver_batch_status = None
adj_factor_batch_status = None
gold_batch_status = None

def _silver_status_for_trade_date(trade_date: str) -> StkMinsDateReadiness: ...
def _adj_factor_status_for_trade_date(trade_date: str) -> ContinuityDateReadiness: ...
def _gold_status_for_trade_date(trade_date: str) -> StkMinsDateReadiness: ...
```

Selection 可以分三段执行，而不是一个 snapshot callback 一次性加载全部上游。

### 8.2 qfq factor repair

目标执行顺序：

```text
1. run window guard
2. expected calendar + silver registered gap
3. gold qfq batch readiness
4. if selected gold status not ready:
     skip，不读取 qfq factor repair status
5. only selected trade_date:
     gold_stk_mins_qfq_factor_repair_status(... include_event_storage_ids=False)
6. if repair status ready:
     advance / skip
7. if repair status not ready:
     submit factor repair run
```

禁止：

1. 对 10 天窗口里每个 gold-ready 日期都读取 repair status。
2. 在 gold qfq 未 ready 时读取 repair status。
3. 恢复 `include_event_storage_ids=True` 参与 sensor hot path。

## 9. P0E 全部 Batch Helper 门禁与性能回归

其它 helper 的性能测试固定放在 P0E。

原因：

1. P0B 是 qfq gold 的问题定位 profiling，不是全 helper 验收。
2. P0C/P0D 会改变 qfq gold 与 sensor 调用模型。
3. 所有 helper 的统一性能回归应在 qfq gold 重写后执行，才能比较最终 hot path 风险。
4. 其它 helper 不全量重写，但必须实际跑一遍，不能只靠审计结论放行。

### 9.1 性能回归测试文件

优先扩展：

```text
lake_console/orchestrator/tests/test_stk_mins_continuity_performance.py
```

如现有测试文件不适合容纳非股票分钟线 helper，可新增：

```text
lake_console/orchestrator/tests/test_batch_readiness_hotpath_performance.py
```

新增测试必须只使用临时目录、临时 Parquet、fake ClickHouse client 或 in-memory DuckDB，不读写正式 lake / Dagster runtime。

P0E 不修改生产运行逻辑。若现有 helper 暴露出同等级 timeout 风险，P0E 只记录失败和风险，停止进入后续修复设计；不得在性能测试阶段顺手重写生产 helper。

### 9.2 必测 helper

| Helper | 测试位置 | 必测内容 |
| --- | --- | --- |
| `batch_raw_stk_mins_lake_readiness` | `test_stk_mins_continuity_performance.py` | 10 天五频度 full semantics，记录 elapsed_ms。 |
| `batch_silver_stk_mins_lake_readiness` | 同上 | 10 天五频度 full semantics，包含 stock daily / suspend / lifecycle。 |
| `batch_gold_stk_mins_qfq_lake_readiness` | 同上 | 10 天七频度 full semantics，验证 true batch 后预算。 |
| `batch_raw_adj_factor_lake_readiness` | 可新建或扩展 adj factor tests | 10 天 raw full semantics。 |
| `batch_silver_adj_factor_lake_readiness` | 同上 | 10 天 silver full semantics。 |
| `batch_adj_factor_lake_readiness` | 同上 | combined 一次调用，确认不重复执行 raw/silver 两套扫描。 |
| `batch_market_major_indices_lake_readiness` | 可扩展 major indices tests | 10 天 readiness，记录 file count 和 elapsed_ms。 |
| `batch_gold_market_breadth_lake_readiness` | 可扩展 market breadth tests | 10 天 readiness，确认小对象 wrapper 仍在预算。 |
| `batch_gold_stock_return_distribution_lake_readiness` | 同上 | 10 天 readiness。 |
| `batch_clickhouse_market_breadth_readiness` | fake client test | 断言 ClickHouse fetch 是 partition set 级别一次调用。 |
| `batch_prod_clickhouse_market_breadth_readiness` | fake client test | 断言 local/prod 各一次 partition set fetch。 |

### 9.2.1 测试夹具口径

P0E 测试夹具按 helper 类型分三类，不共享正式 lake：

| 类型 | 夹具来源 | 必须覆盖 |
| --- | --- | --- |
| DuckDB / Parquet helper | `TemporaryDirectory` + 临时 Parquet + in-memory DuckDB | ready、缺文件、文件存在但 blocking check 失败；至少一个样本必须证明不是只测 row count。 |
| ClickHouse readiness helper | fake client / fake readiness source | 断言查询粒度是 partition set 级别；10 天窗口不得产生 10 次逐日查询。 |
| sensor hot path 静态门禁 | 读取生产源文件文本 / AST | 禁止 Dagster event history 深扫、禁止 qfq gold 回流 per-date 重扫、禁止窗口前重 batch。 |

临时性能样本不要求模拟正式湖全量数据规模，但必须覆盖完整 blocking check 语义路径。不能为了跑得快只构造“文件存在 + row count”的绿色样本。

### 9.2.2 P0E 测试落点

P0E 推荐落点如下：

```text
tests/test_stk_mins_continuity_performance.py
  - raw / silver stk mins 10-day readiness elapsed_ms
  - qfq gold 10-day native + derived readiness elapsed_ms

tests/test_batch_readiness_hotpath_performance.py  # 新增时使用
  - adj factor raw / silver / combined 10-day readiness elapsed_ms
  - major indices 10-day readiness elapsed_ms
  - market breadth / stock return distribution 10-day readiness elapsed_ms
  - ClickHouse local/prod fake-client partition-set call count

tests/test_run_contract_static_gates.py
  - qfq sensors window-before-batch ordering
  - qfq gold batch helper no per-date heavy helper call
  - sensor hot path no Dagster event/check history deep scan
  - batch readiness helpers no Dagster instance dependency
```

如果不新增 `test_batch_readiness_hotpath_performance.py`，必须把同等覆盖补到既有 helper contract tests 中，并在 P0E 对账里逐项说明每个 helper 对应的测试文件。

### 9.3 性能预算

本地临时样本预算：

| Helper 类型 | 预算 |
| --- | --- |
| raw/silver stk mins 临时 10 天样本 | 不得退化到秒级逐日 Dagster 深扫；目标 < 5s，硬上限 < 10s。 |
| qfq gold 临时 10 天样本 | 必须显著低于旧 20/60 天模型；目标 < 8s，硬上限 < 15s。 |
| adj factor 临时 10 天样本 | 目标 < 5s，硬上限 < 10s。 |
| major indices / market breadth 小对象 | 目标 < 1s，硬上限 < 3s。 |
| ClickHouse fake client | 调用次数门禁优先于耗时，必须是 partition set 级别；local/prod 对账最多各一次 fetch。 |

预算失败处理：

1. qfq gold 超硬上限：P0E 停止，回到 qfq gold helper 继续修复。
2. 非 qfq helper 接近或超过 30s sensor hot path 风险：P0E 停止，新增同级修复阶段，不进入 P0F。
3. 临时样本失败但原因是测试夹具不完整：先修测试夹具，不降低正式 blocking check 语义。
4. fake ClickHouse client 调用次数失败：说明读取模型退回逐日查询，必须阻断。

真实 lake profiling 预算：

1. 若需要读取正式 lake，必须单独审批。
2. 输出只写 `/private/tmp`。
3. 不进入 repo，不写 Dagster，不写 lake。

### 9.4 静态门禁

在 `test_run_contract_static_gates.py` 增加或强化：

1. `stock_mins_qfq_daily_sensor.py` 窗口前分支必须出现在 batch helper 调用之前。
2. `stock_mins_qfq_factor_repair_sensor.py` 同上。
3. `stk_mins_lake_readiness.py` 中 `batch_gold_stk_mins_qfq_lake_readiness` body 不得调用 `_gold_qfq_status_for_trade_date`。
4. `batch_gold_stk_mins_qfq_lake_readiness` body 不得出现 `for trade_date in expected_trade_dates` 后调用 `_gold_qfq_native_counts_for_trade_date` 或 `_gold_qfq_derived_counts_for_trade_date`。
5. sensor hot path 禁止 `get_event_records`、`get_asset_check_execution_history`、`partition_dataset_readiness_status_from_latest_checks`。
6. 所有 batch readiness helper 禁止依赖 Dagster instance。

### 9.5 P0E 输出对账格式

P0E 完成后必须在交付说明中列出：

| 项 | 必填内容 |
| --- | --- |
| helper | helper 函数名。 |
| test_file | 覆盖它的测试文件。 |
| window | 起止日期和 expected date 数。 |
| scope | 文件数、频度数或外部查询次数。 |
| elapsed_ms | 本地样本耗时。 |
| semantics | 覆盖了哪些 blocking check 语义，是否包含失败样本。 |
| verdict | 通过、阻断、或需要新增修复阶段。 |

这张表不要求写入 repo；P0F/P0G 文档收口时再把最终验收结果落档。

## 10. P0F 本地验证命令

纯本地测试，不运行 `dg`：

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator
PYTHONPATH=src uv run --project . --with pytest python -m pytest \
  tests/test_stk_mins_lake_readiness.py \
  tests/test_stk_mins_continuity_performance.py \
  tests/test_batch_readiness_hotpath_performance.py \
  tests/test_stock_mins_daily_continuity_sensors.py \
  tests/test_stk_mins_qfq_m9a_sensor_contracts.py \
  tests/test_stk_mins_qfq_m9c_sensor_contracts.py \
  tests/test_run_contract_static_gates.py
```

如果 P0E 最终选择不新增 `tests/test_batch_readiness_hotpath_performance.py`，P0F 命令中应删除该文件，并在对账中说明非股票分钟线 helper 的实际覆盖落点。

静态检查：

```bash
cd /Users/congming/github/goldenshare
rg -n "_gold_qfq_status_for_trade_date|_gold_qfq_native_counts_for_trade_date|_gold_qfq_derived_counts_for_trade_date" \
  lake_console/orchestrator/src/orchestrator/defs/asset_guards/stk_mins_lake_readiness.py
git diff --check
git status --short
```

注意：`_gold_qfq_native_counts_for_trade_date` 和 `_gold_qfq_derived_counts_for_trade_date` 如果保留为非正式路径，静态检查必须进一步限定“不得由 batch helper body 调用”，不能简单全文件零命中。

## 11. 开发阶段拆分

### P0A：窗口前 early skip

改动文件：

```text
stock_mins_qfq_daily_sensor.py
stock_mins_qfq_factor_repair_sensor.py
tests/test_stk_mins_qfq_m9a_sensor_contracts.py
tests/test_stk_mins_qfq_m9c_sensor_contracts.py
tests/test_stock_mins_daily_continuity_sensors.py
tests/test_run_contract_static_gates.py
```

验收：

1. 窗口前 batch helpers mock 成抛错，sensor 仍 skip。
2. 窗口前 cursor 不包含 batch status。

### P0B：只读 profiling

改动文件：

```text
可选新增 tests / local helper，但不得进入生产 Definitions。
```

验收：

1. 输出 profiling JSON。
2. 明确 native / derived / formula 最慢阶段。
3. 如果 profiling 需要正式 lake，先等用户审批。

### P0C：qfq gold true batch

改动文件：

```text
stk_mins_lake_readiness.py
tests/test_stk_mins_lake_readiness.py
tests/test_stk_mins_continuity_performance.py
tests/test_run_contract_static_gates.py
```

验收：

1. 既有 qfq gold readiness 正反测试通过。
2. 新增多日期窗口测试证明不是 per-date 重扫。
3. 静态门禁禁止 batch helper 调用 `_gold_qfq_status_for_trade_date`。

### P0D：sensor 分层短路

改动文件：

```text
stock_mins_qfq_daily_sensor.py
stock_mins_qfq_factor_repair_sensor.py
tests/test_stock_mins_daily_continuity_sensors.py
tests/test_stk_mins_qfq_m9a_sensor_contracts.py
tests/test_stk_mins_qfq_m9c_sensor_contracts.py
```

验收：

1. qfq daily silver not ready 时不调用 adj factor / gold。
2. qfq daily adj factor not ready 时不调用 gold。
3. qfq factor repair gold not ready 时不调用 repair status。
4. gold ready 后只读取 selected target repair status。

当前状态：已完成并提交 `7c7eb0e6`。本次落地范围实际覆盖 qfq daily 分层短路；qfq factor repair 的“gold not ready 不读取 repair status”仍由 P0A/P6 既有测试和 P0E 静态/性能回归继续守住，不在 P0D 追加业务语义变更。

### P0E：全部 helper 门禁与性能回归

改动文件：

```text
tests/test_stk_mins_continuity_performance.py
tests/test_batch_readiness_hotpath_performance.py  # 如需要
tests/test_run_contract_static_gates.py
```

验收：

1. 所有 helper 实际跑一遍。
2. 记录 helper 名称、窗口、文件数/调用次数、elapsed_ms、完整语义覆盖。
3. 如果非 qfq helper 接近 30 秒风险，停止并把该 helper 升级为同级别修复项。

当前状态：已完成并提交 `b70c51c0`。P0E 新增 `tests/test_batch_readiness_hotpath_performance.py`，并扩展分钟线性能测试和静态门禁；所有当前 sensor hot path batch helper 均已跑过本地性能样本或 fake-client 调用次数测试，未发现需要追加同级修复阶段的 helper。

### P0F：本地回归

执行 P0F 测试命令。不得运行 `dg`。

当前状态：已完成。本地目标回归结果为 `119 passed, 5 warnings in 5.12s`；补充静态检查 `git diff --check` 通过。单日 qfq helper symbol 仍保留在旧单日 helper 定义中，但 batch helper body 不调用这些单日 helper，该口径由静态门禁覆盖。

### P0G：文档收口

更新：

```text
dagster-batch-readiness-hotpath-governance-plan.md
dagster-batch-readiness-hotpath-governance-low-level-design.md
dagster-stk-mins-qfq-sensor-hotpath-performance-fix-plan.md
dagster-stk-mins-continuity-performance-optimization-plan.html
dagster-stk-mins-continuity-performance-optimization-low-level-design.html
```

当前状态：已完成。`CODING_STANDARDS.md` 已新增 Sensor Hot Path Batch Readiness 长期规则；qfq hotpath fix 文档和股票分钟线连续性性能优化两份文档已同步 P0 完成事实；本 LLD 与主方案状态均已更新为 P0 完成。

## 12. 停止条件

开发中遇到以下任一情况必须停止汇报：

1. qfq gold 完整语义无法在不新增持久化实体的前提下进入预算。
2. 需要降低公式、coverage、derived source window 等 blocking check 语义。
3. 需要运行 `dg` 或读取正式 Dagster runtime 才能判断。
4. 需要写正式 lake。
5. 需要修改 run key、run config、asset/check/job/sensor 名称。
6. 非 qfq helper 性能回归发现同等级超时风险。
7. bootstrap event 写入逻辑必须被引入 sensor 才能复用。

## 13. P0E 位置说明

其它 helper 的性能测试固定在 P0E，而不是 P0B。

理由：

1. P0B 是 qfq gold 的问题定位 profiling，目的是指导重写。
2. P0E 是验收阶段，必须在 qfq gold 重写和 sensor 分层短路后执行。
3. 其它 helper 当前不是高危修复对象，但必须通过 P0E 证明没有同类风险。
4. 若 P0E 发现其它 helper 有同等级风险，必须追加修复阶段，不能把结果只写成“已知风险”。
