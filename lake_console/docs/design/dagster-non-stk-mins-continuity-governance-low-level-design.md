# Dagster 非股票分钟线连续性治理 LLD

更新时间：2026-06-21

依据文档：

1. [Dagster 非股票分钟线连续性治理专项方案](dagster-non-stk-mins-continuity-governance-plan.md)
2. [Dagster Bounded Continuity Selector 基础能力 LLD](dagster-bounded-continuity-selector-foundation-low-level-design.md)
3. [Dagster Market Major Indices Sensor 热路径性能治理 LLD](dagster-market-major-indices-sensor-performance-governance-low-level-design.md)

状态：开发前 LLD，待按阶段执行。

范围：非股票分钟线日频历史连续资产的停机补洞能力、生命周期事实源收敛、主要指数 sensor 性能治理、派生 automation 资产显式补洞入口。本文档只设计，不执行代码开发，不运行 `dg`，不读取正式 Dagster runtime，不触碰正式 lake。

## 1. 总体硬口径

1. 历史连续资产不得以 latest registered partition 作为正式目标。
2. 目标选择必须来自 expected calendar、registered gap guard、batch/bounded readiness、first missing / first not-ready。
3. 默认窗口固定为最近 60 个 expected trade dates。
4. 已 materialized 但 blocking checks failed 的日期必须阻断后续推进，不自动重跑。
5. sensor 热路径禁止逐日调用单日 Dagster readiness wrapper 扫 event/check history。
6. 能用 lake 文件事实判断的 readiness，优先 DuckDB batch；不能用 row count 冒充完整 blocking check 语义。
7. `silver_stock_lifecycle` 是历史股票生命周期判断的唯一长期 silver 事实源。
8. current snapshot 资产不做历史逐日补洞。
9. P6 后默认 `AutomationCondition.eager()` 不作为历史补洞入口；显式 bounded sensor 是唯一 active 补洞入口。
10. run key、run config、job/sensor/asset/check 名称除明确新增 `silver_stock_lifecycle` 外均不改变。

## 2. 推荐执行顺序

阶段编号表达治理主题，不等同于编码顺序。推荐推进顺序：

```text
P0F -> P1 -> P2A -> P2B -> P2C -> P3 -> P5 -> P4 -> P6 -> P7
```

原因：

1. P0F 是所有 first-not-ready sensor 的基础。
2. P1 先修 `cn_a_stock_current_trade_days` 注册，复权因子后续依赖它。
3. P2A/P2B 先收敛生命周期事实源，否则 P2C 复权因子 readiness 会继续误判历史退市股票。
4. P5 先加固指数日线上游 guard，再做 P4 主要指数 gold，更符合依赖顺序。
5. P6 涉及退出 declarative automation active 入口，必须在基础能力稳定后单独推进。

## 3. P0F Bounded Continuity Selector 基础能力

详细设计见：[Dagster Bounded Continuity Selector 基础能力 LLD](dagster-bounded-continuity-selector-foundation-low-level-design.md)。

本阶段目标文件：

```text
lake_console/orchestrator/src/orchestrator/defs/asset_guards/bounded_continuity.py
lake_console/orchestrator/tests/test_bounded_continuity.py
lake_console/orchestrator/tests/test_run_contract_static_gates.py
```

本阶段验收：

1. `ContinuityExpectedDateWindow`、`ContinuityRegisteredGapStatus`、`ContinuityDateReadiness`、`ContinuityBatchReadiness`、`ContinuitySelection` 可用。
2. selector 是纯函数，不依赖 Dagster instance 或 DuckDB。
3. expected dates loader 只读 `silver_trade_calendar`。
4. cursor details 小型稳定。
5. 静态门禁禁止新接入 sensor 回流单日 readiness wrapper。

## 4. P1 Current Trade Day 注册补洞

### 4.1 当前代码

文件：

```text
lake_console/orchestrator/src/orchestrator/defs/sensors/stock_current_trade_day_sensor.py
```

当前函数：

```text
StockCurrentTradeDayRegistrationDecision
build_stock_current_trade_day_registration_decision(...)
_cursor_payload(...)
_skip_reason(...)
stock_current_trade_day_sensor(...)
```

当前问题：

`build_stock_current_trade_day_registration_decision(...)` 只判断 today 是否 open、是否到 06:00、today 是否已注册。停机错过历史交易日后不会补注册。

### 4.2 实现目标

1. 保留 sensor 名称、tags、default status、`minimum_interval_seconds=600`、resource 依赖。
2. 使用 P0F 的 expected date loader，`same_day_register_start=06:00`。
3. 只看最近 60 个 expected trade dates。
4. 每 tick 最多注册 2 个缺失 `cn_a_stock_current_trade_days`。
5. 历史已完成交易日不受当天 06:00 窗口阻挡。

### 4.3 代码改造

建议删除 today-only 决策结构，替换为通用注册结果：

```text
StockCurrentTradeDayRegistrationDecision
build_stock_current_trade_day_registration_decision(...)
```

改为：

```text
load_expected_trade_date_window(...)
build_registered_gap_status(...)
selected_keys = first 2 missing_registered_dates
```

cursor details 增加：

```text
expected_count
registered_count
first_missing_registered_date
selected_keys
same_day_register_start
window_limit
```

### 4.4 测试

更新：

```text
lake_console/orchestrator/tests/test_adj_factor_m4_contracts.py
```

覆盖：

1. expected 有 `2026-06-15/2026-06-16`，registered 缺二者，单 tick 注册两个或按上限先注册最早两个。
2. 当天 06:00 前不注册今天。
3. 历史缺口不受今天窗口影响。
4. cursor 不再写 today-only 旧字段作为正式契约。
5. 不读取 Dagster event/check history。

## 5. P2 股票生命周期 silver 化与复权因子 first-not-ready

P2 拆为 P2A / P2B / P2C，禁止合并成一个大改。

### 5.1 P2A 新增 `silver_stock_lifecycle`

#### 5.1.1 目标

新增正式 silver 事实资产：

```text
silver_stock_lifecycle
```

它表达历史股票生命周期事实，不是 current-listed snapshot。

#### 5.1.2 目标文件

新增或更新：

```text
lake_console/orchestrator/src/orchestrator/defs/paths.py
lake_console/orchestrator/src/orchestrator/defs/duckdb_sql.py
lake_console/orchestrator/src/orchestrator/defs/run_contracts/asset_column_schemas.py
lake_console/orchestrator/src/orchestrator/defs/assets/stock_lifecycle.py
lake_console/orchestrator/src/orchestrator/defs/checks/stock_lifecycle_checks.py
lake_console/orchestrator/src/orchestrator/defs/jobs/stock_basic_update.py
lake_console/orchestrator/src/orchestrator/defs/sensors/readiness.py
lake_console/orchestrator/src/orchestrator/defs/catalog/lake_assets.py
lake_console/orchestrator/tests/test_stock_lifecycle_contracts.py
lake_console/orchestrator/tests/test_run_contract_static_gates.py
```

说明：

1. `definitions.py` 使用 `load_from_defs_folder(...)`，新增 defs 文件会被加载；实现阶段仍必须用本地静态测试确认 definition 可发现。
2. 使用独立 `assets/stock_lifecycle.py`，避免继续扩大 `stock_basic.py` 的 current snapshot 语义。

#### 5.1.3 Path

新增：

```python
def silver_stock_lifecycle_path(root: Path) -> Path:
    ...
```

建议物理路径：

```text
silver/basic/stock_lifecycle.parquet
```

不得复用 `silver_stock_basic_path(...)`。

#### 5.1.4 字段契约

新增：

```python
SILVER_STOCK_LIFECYCLE_SCHEMA = (
    ColumnContract("ts_code", "VARCHAR", "..."),
    ColumnContract("symbol", "VARCHAR", "..."),
    ColumnContract("name", "VARCHAR", "..."),
    ColumnContract("exchange", "VARCHAR", "..."),
    ColumnContract("market", "VARCHAR", "..."),
    ColumnContract("curr_type", "VARCHAR", "..."),
    ColumnContract("is_cny_stock", "BOOLEAN", "..."),
    ColumnContract("list_status", "VARCHAR", "..."),
    ColumnContract("list_date", "DATE", "..."),
    ColumnContract("delist_date", "DATE", "..."),
)
```

最低必须包含：

```text
ts_code
list_date
delist_date
list_status
exchange
market
is_cny_stock
```

字段规则：

1. `list_date` 必须非空。
2. `delist_date` 可空。
3. `is_cny_stock` 来自 `curr_type='CNY'` 的派生布尔值。
4. `list_status` 保留源状态，例如 `L/D/P/G`，不得只保留当前上市。
5. 保留 `exchange/market`，方便下游 check metadata 可解释。

#### 5.1.5 SQL

新增：

```python
def silver_stock_lifecycle_select(raw_stock_basic_path: Path) -> str:
    ...
```

规则：

1. 输入只读 `raw_tushare_stock_basic`。
2. 不过滤成 current-listed-only。
3. 保留 CNY 股票。
4. `list_date/delist_date` 标准化为 `DATE`。
5. 对明显非法 lifecycle 日期 fail closed，由 check 报错，不静默吞掉。

`historical_cny_stock_lifecycle_select(...)` 后续只允许作为 `silver_stock_lifecycle_select(...)` 的内部辅助或测试辅助，不再给下游长期直接消费。

#### 5.1.6 Asset

新增 `@dg.asset(name="silver_stock_lifecycle", deps=["raw_tushare_stock_basic"])`。

metadata：

```text
dataset_id="stock_lifecycle"
source_system=DERIVED
data_contract="historical_cny_stock_lifecycle"
column_schema=SILVER_STOCK_LIFECYCLE_SCHEMA
path_template=silver_stock_lifecycle_path(...)
```

materialization metadata：

```text
uri
row_count
observed_columns
source_row_count
cny_stock_count
list_status_distribution
```

#### 5.1.7 Job

更新 `jobs/stock_basic_update.py`：

1. `silver_stock_basic_update_job` 是否扩展 selection 到 `silver_stock_lifecycle`，需要在 P2A 实现计划中明确。
2. 推荐：保留 job 名称 `silver_stock_basic_update_job`，selection 包含 `silver_stock_basic | silver_stock_lifecycle | checks_for_assets(...)`，因为两个 silver fact 都从同一个 raw stock basic 快照派生，且都是基础股票事实。
3. 不新增单独 sensor；沿用现有 stock basic silver 更新节奏。

#### 5.1.8 Checks

新增 blocking checks：

```text
silver_stock_lifecycle_file_exists_check
silver_stock_lifecycle_required_columns_and_types_check
silver_stock_lifecycle_unique_ts_code_check
silver_stock_lifecycle_required_fields_non_null_check
silver_stock_lifecycle_dates_valid_check
silver_stock_lifecycle_cny_stock_universe_check
```

命名若与现有 check 风格冲突，以 `CODING_STANDARDS.md` 新增 check 命名规则为准；不得改名已有 check。

#### 5.1.9 Readiness

在 `sensors/readiness.py` 增加：

```python
silver_stock_lifecycle_ready(...)
silver_stock_lifecycle_ready_without_freshness(...)
```

或用现有 dataset readiness 构造方式注册 specs。

用途：

1. P2B/P2C selected-date gates。
2. 后续 lifecycle consumers check additional_deps。

#### 5.1.10 Catalog

更新 `LAKE_ASSET_CATALOG`：

1. 新增 `silver_stock_lifecycle` entry。
2. 登记 path template、column schema、blocking checks、write policy、event policy、performance contract。
3. 不把它登记成 trade_date partitioned asset。

### 5.2 P2B 迁移 lifecycle consumers

P2B 必须一次性清零既有长期消费者，不能只修复权因子。

#### 5.2.1 迁移清单

| 当前消费者 | 当前口径 | 目标口径 |
| --- | --- | --- |
| `assets/stock_daily.py::silver_stock_daily_select(...)` | 直接读 `raw_stock_basic` 生命周期。 | 读 `silver_stock_lifecycle`。 |
| `checks/stock_daily_checks.py` lifecycle checks | 多处直接 `historical_cny_stock_lifecycle_select(raw_stock_basic_path)`。 | 读 `silver_stock_lifecycle_path`，additional_deps 改为 `silver_stock_lifecycle`。 |
| `checks/stk_mins_checks.py::silver_stk_mins_name_timeline_covered` | 直接读 raw lifecycle。 | 读 `silver_stock_lifecycle`。 |
| `asset_guards/stk_mins_lake_readiness.py` | 直接读 raw lifecycle。 | 读 `silver_stock_lifecycle`。 |
| `bootstrap/stk_mins_name_timeline_check_events.py` | dry-run helper 直接读 raw lifecycle。 | 读 `silver_stock_lifecycle`。 |

#### 5.2.2 保留项

以下直接使用 `raw_stock_basic_path` 不属于本迁移清零目标：

1. `raw_tushare_stock_basic` 自身 checks。
2. `silver_stock_lifecycle` 的生产 SQL / checks。
3. 测试 fixture 或负向样本。
4. `silver_stock_basic` current-listed snapshot 生产逻辑。

#### 5.2.3 静态门禁

新增门禁：

1. 生产路径中禁止下游长期消费者直接调用 `historical_cny_stock_lifecycle_select(raw_stock_basic_path)`。
2. allowlist 只允许 `duckdb_sql.py`、`assets/stock_lifecycle.py`、`checks/stock_lifecycle_checks.py`、测试。
3. `silver_stock_basic` 不得被改成包含退市历史股票。

### 5.3 P2C 复权因子 first-not-ready

#### 5.3.1 当前代码

文件：

```text
sensors/stock_adj_factor_sensor.py
assets/adj_factor.py
checks/adj_factor_checks.py
```

当前问题：

1. sensor 使用 `_latest_registered_trade_date(...)`。
2. silver asset/check 仍依赖 `silver_stock_basic` current-listed 口径。
3. 单日 Dagster readiness wrapper 已通过 profiling 证明不可进入窗口循环。

#### 5.3.2 Asset / check 语义修正

`assets/adj_factor.py`：

1. `silver_adj_factor` deps 从 `silver_stock_basic` 改为 `silver_stock_lifecycle`。
2. `silver_adj_factor_select(...)` 改为使用 `silver_stock_lifecycle_path(...)`。
3. `current_listed_stock_count` metadata 改名为历史生命周期语义字段，例如 `lifecycle_stock_count`。

`checks/adj_factor_checks.py`：

1. `silver_adj_factor_listed_stock_only` 使用 `silver_stock_lifecycle`。
2. `silver_adj_factor_coverage_complete` 使用 `silver_stock_lifecycle`。
3. 退市股票在 `trade_date <= delist_date` 时必须合法。
4. `trade_date > delist_date` 或无 lifecycle 记录必须失败。

#### 5.3.3 Sensor 改造

`stock_adj_factor_sensor.py`：

1. 删除 `_latest_registered_trade_date(...)` 正式口径。
2. 使用 P0F expected window + registered gap guard。
3. raw sensor：
   - batch 判断 raw adj factor materialized/checks。
   - 选择 first missing raw。
4. silver sensor：
   - batch 判断 silver adj factor materialized/checks。
   - selected date 上检查 raw ready、`stock_basic_ready_without_freshness`、`silver_stock_lifecycle` ready。
5. run key 不变：
   - `raw_adj_factor_update:{trade_date}`
   - `silver_adj_factor_update:{trade_date}`

#### 5.3.4 Readiness provider

新增或扩展：

```text
asset_guards/adj_factor_lake_readiness.py
```

要求：

1. 60 日窗口一次性判断 raw/silver readiness。
2. 不调用 `raw_tushare_adj_factor_ready_for_trade_date(...)` 或 `adj_factor_ready_for_trade_date(...)`。
3. 完整覆盖正式 blocking check 语义。
4. 复用 `silver_stock_lifecycle` 做历史股票全集 / listed 判断。

## 6. P3 股票日线与停复牌 registered gap guard

### 6.1 目标文件

```text
sensors/stock_daily_sensor.py
sensors/suspend_d_sensor.py
tests/test_stock_daily_sensor.py
tests/test_suspend_d_sensor.py
tests/test_run_contract_static_gates.py
```

### 6.2 实现目标

1. 在现有 `_eligible_registered_trade_dates(...)` 后增加 expected registered gap guard。
2. 存在更早 expected date 未注册时 skip。
3. 不改变现有 registered 内 pending selection。
4. 不扩大 selected-date readiness。
5. 保留每 tick 最多 2 个 run。
6. 保留 stock daily raw missing-code repair 逻辑，不扩大到全历史。

### 6.3 测试

覆盖：

1. expected 有 `2026-06-15/2026-06-16`，registered 缺 `2026-06-15`，raw/silver stock daily 不提交 `2026-06-16`。
2. suspend raw/silver 同样不提交后续日期。
3. registered 连续后，现有 pending selection 行为不变。
4. selected-date `stock_basic`、`suspend`、raw readiness 仍只对目标日期调用。

## 7. P5 指数日线 guard 加固

### 7.1 目标文件

```text
sensors/index_daily_sensor.py
sensors/silver_index_daily_sensor.py
tests/test_index_daily_sensor.py
tests/test_silver_index_daily_sensor.py
tests/test_run_contract_static_gates.py
```

### 7.2 实现目标

1. raw / silver 两个 sensor 增加 expected registered gap guard。
2. 保留 `audit_index_daily_raw_gaps(...)`。
3. 保留 `select_first_not_ready_silver_index_daily_partition(...)`。
4. 不把 `silver_index_daily_ready_for_trade_date(...)` 放入窗口循环。
5. 不改 raw-by-code repair、cursor offset、run key。

### 7.3 测试

覆盖：

1. `cn_a_index_trade_days` 注册缺口存在时，raw/silver index daily skip。
2. 注册连续后，raw gap audit 行为不变。
3. silver first-not-ready 仍使用 bounded selector。
4. 静态门禁防止单日 wrapper 回流。

## 8. P4 主要指数日线 gold

详细设计见：[Dagster Market Major Indices Sensor 热路径性能治理 LLD](dagster-market-major-indices-sensor-performance-governance-low-level-design.md)。

本总 LLD 只固定接入边界：

1. P4 在 P5 后推进更稳。
2. P4 必须复用 P0F 的通用 selector 数据结构。
3. P4 不得调用旧 Dagster readiness wrapper。
4. P4 不得新增持久化状态实体。
5. P4 的 `checks_passed` 表示 lake-derived blocking check 等价语义，不表示历史 check event 已 passed。

## 9. P6 派生 / Serving 显式 Bounded Sensor

### 9.1 当前代码

当前仍存在：

```text
assets/market_breadth.py::MARKET_BREADTH_AUTOMATION_CONDITION
assets/stock_return_distribution.py::STOCK_RETURN_DISTRIBUTION_AUTOMATION_CONDITION
assets/clickhouse_serving.py::CLICKHOUSE_MARKET_BREADTH_AUTOMATION_CONDITION
assets/clickhouse_serving.py::PROD_CLICKHOUSE_MARKET_BREADTH_AUTOMATION_CONDITION
sensors/market_breadth_automation_sensor.py
sensors/stock_return_distribution_automation_sensor.py
sensors/clickhouse_share_fact_market_breadth_automation_sensor.py
sensors/prod_clickhouse_share_fact_market_breadth_automation_sensor.py
```

### 9.2 新增显式 sensor

建议新增：

```text
sensors/market_breadth_continuity_sensor.py
sensors/stock_return_distribution_continuity_sensor.py
sensors/clickhouse_market_breadth_continuity_sensor.py
```

也可以在 P6 设计评审时决定是否合并为一个文件；但 active sensor definition 必须职责清晰、tags 完整、cursor 小型。

### 9.3 资产目标

| 资产 | 上游门禁 | 目标 |
| --- | --- | --- |
| `gold_market_breadth_daily` | selected-date `silver_stock_daily` ready。 | first missing / first-not-ready gold breadth。 |
| `gold_stock_return_distribution` | selected-date `silver_stock_daily` ready。 | first missing / first-not-ready gold distribution。 |
| `ch_share_fact_market_breadth_daily` | selected-date 两个 gold 派生资产 ready。 | first missing / first-not-ready local ClickHouse serving。 |
| `prod_ch_share_fact_market_breadth_daily` | selected-date local ClickHouse serving ready。 | first missing / first-not-ready prod ClickHouse serving。 |

### 9.4 Automation 退出

P6 显式 sensor 成为正式入口时，必须同步：

1. 移除四个 asset 上的 `automation_condition=...`。
2. 删除或退出四个 `AutomationConditionSensorDefinition`。
3. 静态门禁禁止这些 asset 重新出现 `AutomationCondition.eager()`。
4. 静态门禁禁止旧 automation sensor definition 继续 active。

不允许保留 active automation condition 作为 latest propagation 辅助路径。

### 9.5 Readiness

P6 必须先做只读性能方案，再进入代码：

1. gold 派生资产可用 lake fact readiness 判断输出文件、schema、row count、partition date、计算语义。
2. ClickHouse serving readiness 如无法从 lake 文件判断，必须用 bounded metadata 或 ClickHouse 只读查询，并写清读取次数和上限。
3. 不允许全历史逐分区调用 `asset_readiness_status(...)`。

## 10. P7 最终收口

P7 只做：

1. 更新文档状态。
2. 静态门禁收口。
3. 本地单元回归。
4. 性能报告对账。
5. 代码事实与文档口径对账。

P7 不做新功能开发。

## 11. 静态门禁总表

| 禁止项 | 门禁范围 |
| --- | --- |
| latest-only target 回流 | P1/P2C/P3/P5/P4/P6 迁移后的 sensor。 |
| 60 日窗口逐日调用单日 Dagster readiness wrapper | 所有接入 bounded selector 的 sensor。 |
| `raw_stock_basic` 生命周期事实长期下游直接消费 | P2B 迁移完成后的生产代码。 |
| `silver_stock_basic` 被用作历史退市股票全集 | P2A 后除 current snapshot / freshness guard 外的生产路径。 |
| `AutomationCondition.eager()` 继续作为 P6 四个资产 active 补洞入口 | P6 完成后的 assets/sensors。 |
| 直接 `dg.RunRequest(...)` / 手写 run key | 所有正式 sensor。 |
| cursor 写完整大数组或逐文件明细 | 新增/迁移后的 continuity sensors。 |

## 12. 最小本地测试矩阵

每阶段执行各自小回归；最终 P7 汇总：

```bash
cd lake_console/orchestrator
PYTHONPATH=src uv run --project . --with pytest python -m pytest \
  tests/test_bounded_continuity.py \
  tests/test_adj_factor_m4_contracts.py \
  tests/test_stock_lifecycle_contracts.py \
  tests/test_stock_daily_sensor.py \
  tests/test_suspend_d_sensor.py \
  tests/test_index_daily_sensor.py \
  tests/test_silver_index_daily_sensor.py \
  tests/test_market_major_indices_lake_readiness.py \
  tests/test_market_major_indices_daily_sensor.py \
  tests/test_run_contract_static_gates.py
```

说明：

1. 具体测试文件可在实现阶段按现有测试命名调整。
2. 不运行 `dg`。
3. 不读取正式 Dagster runtime。
4. 不触碰正式 lake。

## 13. 需要在实现计划中再次确认的点

以下不是方案口径分歧，而是每个阶段开工计划必须列清的实现细节：

1. P2A `silver_stock_lifecycle` 是否纳入现有 `silver_stock_basic_update_job` selection；本 LLD 推荐纳入，不新增独立 sensor。
2. P6 四个派生资产显式 sensor 是拆成三个文件还是四个文件；无论如何旧 automation active 入口必须退出。
3. P4 gold lake readiness SQL 是否复用现有 check helper 内部 SQL，还是抽成 shared SQL builder；不能复制出语义漂移的第二套逻辑。
4. P2C adj factor batch readiness helper 文件名与测试命名；必须表达资产族职责，不得使用阶段编号。
5. P2B 开工前必须逐项审计 `stock_daily_checks.py` 中 current-listed 语义和 historical lifecycle 语义的边界：仍服务 `silver_stock_basic` freshness / current pool 的检查可以保留 current-listed 口径；`silver_stock_daily` 历史生命周期过滤、覆盖和下游完整性判断必须迁到 `silver_stock_lifecycle`。禁止用全局替换方式把所有 `silver_stock_basic_path` / `raw_stock_basic_path` 调用一刀切改掉。
6. P2C 开工前必须在 P2A/P2B 已完成后重新做只读 DuckDB batch profiling。已有约 1.1 秒的 60 日复权因子 batch 数据来自旧生命周期口径，只证明读取模型可行，不证明迁移到 `silver_stock_lifecycle` 后的完整 blocking check 语义和耗时仍然成立。
7. P4 开工前必须先做只读 DuckDB SQL / 性能原型验证：覆盖 60 日 `gold_market_major_indices_daily` lake readiness、selected-date `silver_index_daily` lake readiness、`silver_index_basic` lake readiness 和 seed/input gate。已有 47 秒 / 超时数据只证明旧 wrapper 不可用，不能替代新 lake-derived readiness 的性能验收。
8. P6 开工前必须先做只读 readiness provider 审计：gold 派生资产优先 lake 文件事实，local / prod ClickHouse serving 优先 bounded ClickHouse 只读查询或明确 bounded metadata 查询；不得运行正式 automation evaluator，不得全历史逐分区调用 `asset_readiness_status(...)`。

## 14. 已确认无需额外性能测试的阶段

以下阶段已有只读 profiling 或读取模型证据支撑，进入开发前不需要再跑正式性能测试，但仍需按阶段计划列清硬口径和测试：

1. P0F：基础 selector 是纯函数，性能门禁来自本地单元测试和静态门禁，不读取正式 Dagster runtime。
2. P1：正式 calendar 读取、`cn_a_stock_current_trade_days` dynamic partitions 读取和 60 日 gap diff 已完成只读 profiling，均为亚秒级 / 毫秒级。
3. P3：股票日线 / 停复牌只加 expected registered gap guard，不扩大 selected-date readiness；正式 dynamic partition 和 materialized partition set 读取已验证为毫秒级。
4. P5：指数日线 raw/silver 保留既有 raw gap audit 和 silver bounded selector，只补 expected registered gap guard；20/60 日只读 profiling 已覆盖。

这些点应在各阶段进入开发前计划中列清并等待 review。
