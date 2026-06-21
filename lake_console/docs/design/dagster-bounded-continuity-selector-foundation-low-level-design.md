# Dagster Bounded Continuity Selector 基础能力 LLD

更新时间：2026-06-21

依据文档：[Dagster Bounded Continuity Selector 基础能力专项方案](dagster-bounded-continuity-selector-foundation-plan.md)

状态：开发前 LLD，待按阶段执行。

范围：只定义非分钟线历史连续资产共用的显式补洞选择基础能力。不直接接入任何正式 sensor，不新增 Dagster asset/job/check/resource，不读取正式 Dagster runtime，不写正式 lake。

## 1. 开发目标

本 LLD 的目标是把后续 P1/P3/P5/P6/P4 等 sensor 需要重复使用的能力收敛到一个基础模块，避免每条链路临时实现一套不同的补洞判断。

基础能力必须覆盖：

1. 从 `silver_trade_calendar` 读取最近 60 个 expected trade dates。
2. 对比 expected dates 与 dynamic partitions，找最早未注册日期。
3. 表达单日 readiness 与批量 readiness。
4. 从窗口最早日期开始选择 first missing / first not-ready。
5. 已 materialized 但 checks failed 时停止推进，不自动重跑后续日期。
6. 输出小型 cursor details。
7. 提供静态门禁，禁止 60 日窗口里逐日调用单日 Dagster readiness wrapper。

## 2. 不做事项

1. 不接入 `stock_current_trade_day_sensor.py`、`stock_daily_sensor.py`、`suspend_d_sensor.py`、`index_daily_sensor.py`、`silver_index_daily_sensor.py`、`market_major_indices_daily_sensor.py` 或 automation sensors。
2. 不新增任何持久化状态实体，例如 manifest、summary asset、readiness asset、数据库表或配置项。
3. 不运行 `dg`，不读取正式 `DAGSTER_HOME`，不触碰正式 lake。
4. 不定义具体资产族的 DuckDB readiness SQL；资产族 helper 在各自阶段实现。
5. 不改变 run key、run config、job/sensor 名称。

## 3. 目标文件

新增：

```text
lake_console/orchestrator/src/orchestrator/defs/asset_guards/bounded_continuity.py
lake_console/orchestrator/tests/test_bounded_continuity.py
```

更新：

```text
lake_console/orchestrator/tests/test_run_contract_static_gates.py
```

命名说明：

`bounded_continuity.py` 表达“有窗口上限的连续性选择能力”，不是某个资产族的业务 helper。股票分钟线已有 `stk_mins_continuity.py`，本模块服务非分钟线历史连续资产。

## 4. 常量

在 `bounded_continuity.py` 中定义：

```python
DEFAULT_CONTINUITY_WINDOW_LIMIT = 60
DEFAULT_CONTINUITY_SAMPLE_LIMIT = 20
```

约束：

1. 默认窗口固定 60 个 expected trade dates。
2. 任何调用方要改窗口，必须在本资产族 LLD 里明确说明理由和性能验证结果。
3. sample limit 只用于 cursor / metadata 摘要，不得影响正式选择逻辑。

## 5. 数据结构

### 5.1 `ContinuityExpectedDateWindow`

```python
@dataclass(frozen=True)
class ContinuityExpectedDateWindow:
    expected_trade_dates: tuple[str, ...]
    min_trade_date: str | None
    max_trade_date: str | None
    evaluated_at: datetime
    window_limit: int
```

语义：

1. `expected_trade_dates` 必须按日期升序。
2. `expected_trade_dates` 是已经应用 `min_trade_date`、同日窗口、`window_limit` 后的最终窗口。
3. `max_trade_date` 是本次窗口内最后一个 expected date，不等于今天。

### 5.2 `ContinuityRegisteredGapStatus`

```python
@dataclass(frozen=True)
class ContinuityRegisteredGapStatus:
    expected_trade_dates: tuple[str, ...]
    registered_trade_dates: tuple[str, ...]
    first_missing_registered_date: str | None
    missing_registered_dates: tuple[str, ...]

    @property
    def ready(self) -> bool: ...
    def to_cursor_details(self) -> dict[str, object]: ...
```

语义：

1. `registered_trade_dates` 只保存窗口内已注册日期。
2. `first_missing_registered_date` 非空时，数据 sensor 必须 skip。
3. cursor 只输出缺口样本，不输出全量大数组。

### 5.3 `ContinuityDateReadiness`

```python
@dataclass(frozen=True)
class ContinuityDateReadiness:
    trade_date: str
    ready: bool
    materialized: bool
    checks_passed: bool
    reason: str
    failed_check_names: tuple[str, ...] = ()
    missing_check_names: tuple[str, ...] = ()
    missing_file_paths: tuple[str, ...] = ()
    summary: Mapping[str, object] = field(default_factory=dict)
```

字段硬口径：

| 字段 | 口径 |
| --- | --- |
| `materialized` | 目标物理事实存在。可以来自 lake 文件、bounded materialized partition set 或其它正式事实。 |
| `checks_passed` | 当前 readiness provider 的完整 blocking check 等价语义通过。 |
| `ready` | 必须等价于 `materialized and checks_passed`。 |
| `failed_check_names` | 文件存在但质量语义失败的 blocking check。 |
| `missing_check_names` | 文件缺失导致无法通过的 blocking check。 |
| `missing_file_paths` | 缺失文件样本，禁止放全量大列表。 |
| `summary` | 小型摘要，例如 row count、file count、elapsed_ms，不放逐文件明细。 |

禁止：

1. 用 `row_count > 0` 冒充完整 `checks_passed=True`。
2. 把 Dagster 历史 check event 是否存在作为 lake fact readiness 的必选条件。
3. 把 scan exception 静默转成 ready。

### 5.4 `ContinuityBatchReadiness`

```python
@dataclass(frozen=True)
class ContinuityBatchReadiness:
    expected_trade_dates: tuple[str, ...]
    statuses_by_trade_date: Mapping[str, ContinuityDateReadiness]
    elapsed_ms: int
    scanned_file_count: int = 0

    def status_for_trade_date(self, trade_date: str) -> ContinuityDateReadiness: ...
    def to_cursor_details(self) -> dict[str, object]: ...
```

`status_for_trade_date(...)` 对未知日期必须 fail closed，返回：

```text
ready=False
materialized=False
checks_passed=False
reason="unknown_trade_date"
```

不能抛普通异常导致 sensor tick 失败，除非调用方明确要求 fail hard。

### 5.5 `ContinuitySelection`

```python
@dataclass(frozen=True)
class ContinuitySelection:
    selected_trade_date: str | None
    selected_status: ContinuityDateReadiness | None
    ready_through_trade_date: str | None
    first_not_ready_trade_date: str | None
    blocked_reason: str | None
```

语义：

1. `selected_trade_date` 只在目标缺文件 / 未生成、可提交 run 时非空。
2. `materialized=True and checks_passed=False` 时，`selected_trade_date=None`，`blocked_reason="materialized_check_failed"`。
3. all ready 时，`selected_trade_date=None`，`blocked_reason=None`。

## 6. 函数设计

### 6.1 `load_expected_trade_date_window(...)`

签名：

```python
def load_expected_trade_date_window(
    connection,
    calendar_path: Path,
    *,
    evaluated_at: datetime,
    min_trade_date: str | None = None,
    same_day_register_start: time | None = None,
    window_limit: int = DEFAULT_CONTINUITY_WINDOW_LIMIT,
) -> ContinuityExpectedDateWindow:
    ...
```

实现口径：

1. 只读取 `silver_trade_calendar`。
2. SQL 条件固定：
   - `exchange = 'SSE'`
   - `is_open = true`
   - `trade_date >= min_trade_date`，若传入。
3. 日期上界：
   - 历史日期总是 eligible。
   - 当天只有在 `same_day_register_start is None` 或 `evaluated_at.time() >= same_day_register_start` 时 eligible。
4. 只返回最后 `window_limit` 个 expected dates。
5. `window_limit <= 0` 必须抛 `ValueError`。

性能口径：

1. 一次 DuckDB 查询。
2. 不读取 dynamic partitions。
3. 不读取 Dagster event/check history。

### 6.2 `build_registered_gap_status(...)`

签名：

```python
def build_registered_gap_status(
    *,
    expected_trade_dates: Sequence[str],
    registered_trade_dates: Iterable[str],
    sample_limit: int = DEFAULT_CONTINUITY_SAMPLE_LIMIT,
) -> ContinuityRegisteredGapStatus:
    ...
```

实现口径：

1. 只做集合差异。
2. `first_missing_registered_date` 必须按 expected order 取最早缺口。
3. `missing_registered_dates` 只保留前 `sample_limit` 个样本。

### 6.3 `select_first_not_ready_trade_date(...)`

签名：

```python
def select_first_not_ready_trade_date(
    *,
    expected_trade_dates: Sequence[str],
    readiness: ContinuityBatchReadiness,
) -> ContinuitySelection:
    ...
```

算法：

```text
ready_through = None
for trade_date in expected_trade_dates:
    status = readiness.status_for_trade_date(trade_date)

    if status.ready:
        ready_through = trade_date
        continue

    if status.materialized and not status.checks_passed:
        return blocked(materialized_check_failed)

    return selected(trade_date)

return all_ready(ready_through)
```

禁止：

1. 跳过 check failed 日期去选择后续日期。
2. 倒序扫描。
3. 在 selector 内调用 Dagster instance 或 DuckDB；selector 必须是纯函数。

### 6.4 `build_continuity_cursor_details(...)`

签名：

```python
def build_continuity_cursor_details(
    *,
    expected_window: ContinuityExpectedDateWindow,
    gap_status: ContinuityRegisteredGapStatus,
    batch_readiness: ContinuityBatchReadiness | None,
    selection: ContinuitySelection | None,
) -> dict[str, object]:
    ...
```

输出字段：

```text
expected_count
registered_count
first_missing_registered_date
first_not_ready_trade_date
ready_through_trade_date
selected_trade_date
blocked_reason
batch_elapsed_ms
status_samples
```

约束：

1. cursor summary only。
2. `status_samples` 最多 `DEFAULT_CONTINUITY_SAMPLE_LIMIT` 条。
3. 不输出逐文件列表、完整日期数组、完整 asset/check matrix。

## 7. Readiness Provider 接口约定

基础模块不定义抽象基类，避免过度工程化。各资产族 provider 只需返回 `ContinuityBatchReadiness`。

调用方约束：

1. provider 必须一次性处理窗口日期，不得在内部逐日调用单日 Dagster readiness wrapper。
2. provider 若使用 Dagster metadata，必须在该资产族 LLD 中写清 bounded limit、查询次数、记录上限和只读 profiling 结果。
3. provider 若使用 DuckDB/lake，必须复用或抽取正式 blocking check SQL 语义。
4. selected-date upstream gate 允许调用现有单日 helper，但不得放入 60 日循环；若该 helper 本身已证实慢，必须改为 lake readiness。

## 8. 静态门禁

在 `tests/test_run_contract_static_gates.py` 中新增或扩展门禁：

1. 禁止新接入的非分钟线 continuity sensor 在 60 日 selector 中调用：
   - `asset_readiness_status(...)`
   - `dataset_readiness_status(...)`
   - `partition_dataset_readiness_status_from_latest_checks(...)`
   - 已明确禁用的单日 wrapper，例如 adj factor、major indices 旧 wrapper。
2. 禁止 sensor 文件新增 `run_key=f"..."`
3. 禁止 sensor 文件新增直接 `dg.RunRequest(...)` / `RunRequest(...)`
4. 禁止解析 `run_key` 反推 config。
5. 禁止 cursor 写入大数组字段，例如完整 `statuses_by_trade_date`。

静态门禁不得误伤：

1. 测试中的负向样本。
2. 已存在但未迁移阶段的 sensor；必须按阶段逐步扩大检查范围。
3. 文档中用于描述历史问题的字符串。

## 9. 单元测试

新增 `tests/test_bounded_continuity.py`：

1. expected date loading：
   - 历史开市日进入窗口。
   - 当天在 same-day window 前不进入。
   - 当天在 same-day window 后进入。
   - `window_limit=60` 只返回最后 60 个。
2. registered gap：
   - expected 有 `2026-06-15/2026-06-16`，registered 缺 `2026-06-15`，最早缺口必须是 `2026-06-15`。
   - sample limit 生效。
3. selector：
   - all ready 返回 `ready_through_trade_date`。
   - first missing 返回 selected date。
   - materialized checks failed 返回 blocked，不选择后续日期。
   - unknown date fail closed。
4. cursor：
   - 输出字段稳定。
   - 不包含完整 statuses map。
5. 纯函数边界：
   - selector 不依赖 Dagster instance。
   - selector 不依赖 DuckDB connection。

## 10. 性能门禁

基础能力本身的性能预算：

| 项 | 预算 |
| --- | --- |
| expected calendar query | 单次 DuckDB 查询，正式湖目标 < 100ms。 |
| registered gap diff | 60 日窗口内 < 1ms。 |
| selector scan | 60 个日期内 < 1ms。 |
| cursor serialization | 小型 JSON，禁止大数组。 |

若实现中发现基础模块需要读取 Dagster event history，必须停止；这说明职责已经越界到资产族 readiness provider。

## 11. 后续接入顺序

基础能力完成后，按总专项 LLD 接入：

1. P1 `stock_current_trade_day_sensor`
2. P3 `stock_daily_sensor.py` / `suspend_d_sensor.py`
3. P5 `index_daily_sensor.py` / `silver_index_daily_sensor.py`
4. P4 `market_major_indices_daily_sensor.py`
5. P6 派生 / serving 显式 bounded sensor

P2A/P2B 的 `silver_stock_lifecycle` 是事实源建设阶段，不直接依赖 selector；P2C 的复权因子 sensor 接入依赖本基础能力。
