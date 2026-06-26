# Dagster 股票日线前复权资产 Low-Level Design

## 1. Summary

本 LLD 细化 `gold_stock_daily_qfq` 的代码级落地方案。目标是在 gold 层新增一个基于 `silver_stock_daily` 与 `silver_adj_factor` 生成的股票日线前复权行情资产，供后续 MA250、日线指标、研究报告和其它下游消费。

本 LLD 只设计数据湖与 Dagster 资产能力，不纳入报告生成逻辑。报告改造后续单独推进。

已确认的用户口径：

1. `gold_stock_daily_qfq` 保留 `pre_close`、`change_amount`、`pct_chg` 字段。
2. 物理布局采用 `trade_date=...`：
   `gold/quote/stock_daily_qfq/trade_date={YYYY-MM-DD}/part-000.parquet`。
3. 日常生成和复权因子变化后的 repair 放在同一专项 / LLD 中设计，但实现上分成不同 entrypoint、job 和测试阶段。
4. 报告相关工作不进入本需求开发范围。
5. 上市首日或湖中无 previous source row 时，`pre_close/change_amount/pct_chg` 统一写 `0`，不写 `NULL`。
6. repair 初版不开放手写 `stock_codes`；affected codes 必须由 `silver_adj_factor` 相邻 expected trade date diff 自动计算。
7. repair 初版必须增加自动 run-status sensor；触发逻辑参考股票分钟线 MACD/KDJ repair：daily qfq 成功后自动做 bounded plan 判断并提交 scoped repair job。

代码实现必须按下面三条解释落地：

1. `pre_close/change_amount/pct_chg = 0` 只表示“该股票在湖中没有上一条可用 source row”。它不是数据缺失兜底；如果 previous source row 存在但 previous adj factor 缺失，writer 和 check 都必须 fail closed。
2. repair op、repair config、sensor cursor 和测试都不得出现手写 `stock_codes` 正式入口。affected codes 只能从相邻 expected trade date 的 `silver_adj_factor` diff 得到，并通过 `repair_required_codes_hash` 与 `upstream_batch_id` 校验。
3. repair 自动化只由 `gold_stock_daily_qfq_update_job` 成功 run 触发。不得新增定时全量 repair sensor，不得在 daily job 内混入 repair 写入，也不得让 sensor 扫全历史 Dagster event 或全历史 lake 文件。

## 2. Audit Scope

### 2.1 规范与设计依据

本 LLD 依据：

- 根目录 `AGENTS.md`
- `lake_console/AGENTS.md`
- `lake_console/orchestrator/AGENTS.md`
- `lake_console/orchestrator/CODING_STANDARDS.md`
- `lake_console/docs/design/dagster-data-pipeline-performance-governance.md`
- `lake_console/docs/design/dagster-asset-schema-contract-design.md`
- `lake_console/docs/templates/dagster-dataset-onboarding-template.html`
- `lake_console/docs/design/dagster-stock-daily-qfq-asset-design.md`
- `lake_console/docs/design/dagster-adj-factor-asset-design.md`

### 2.2 当前代码审计范围

已用 CodeGraph 和文本审计覆盖：

- `orchestrator/defs/assets/stock_daily.py`
  - `raw_stock_daily`
  - `silver_stock_daily`
  - `silver_stock_daily_update_job`
  - `silver_stock_daily_update_job_sensor`
- `orchestrator/defs/assets/adj_factor.py`
  - `raw_adj_factor`
  - `silver_adj_factor`
  - `silver_adj_factor_update_job`
  - `silver_adj_factor_update_job_sensor`
- `orchestrator/defs/stk_mins_qfq.py`
  - `build_daily_qfq_select_sql(...)`
  - `execute_gold_stk_mins_qfq_factor_repair(...)`
  - `build_adj_factor_changed_codes_sql(...)`
- `orchestrator/defs/asset_column_schemas.py`
  - `SILVER_STOCK_DAILY_SCHEMA`
  - `SILVER_ADJ_FACTOR_SCHEMA`
  - `GOLD_STK_MINS_QFQ_SCHEMA`
- `orchestrator/defs/catalog/lake_assets.py`
  - partition model
  - asset catalog
  - check catalog
- `orchestrator/defs/checks/stock_daily_checks.py`
  - stock daily check grouping pattern
- `orchestrator/defs/sensors/readiness.py`
  - readiness specs and payload pattern
- `orchestrator/defs/run_contracts/run_keys.py`
  - run key builder
  - upstream batch id
  - forbidden legacy payload fields
- `orchestrator/defs/run_contracts/cursors.py`
  - sensor cursor schema
  - reason code / summary / next action payload rules
- `orchestrator/defs/paths.py`
  - raw / silver / gold lake path helper pattern

### 2.3 当前代码事实

1. `silver_stock_daily` 是未复权股票日线，字段包含：
   `ts_code`、`trade_date`、`open`、`high`、`low`、`close`、`pre_close`、`change_amount`、`pct_chg`、`vol`、`amount`。
2. `silver_adj_factor` 是复权因子日线，字段至少包含：
   `ts_code`、`trade_date`、`adj_factor`。
3. 现有分钟线 qfq 公式不是简单乘以因子，而是：
   `source_price * trade_date_adj_factor / as_of_adj_factor`。
4. `stock_mins_qfq` 的物理布局是 stock-year 文件；股票日线 qfq 已拍板使用 `trade_date=...` 布局，不能复用分钟线 writer。
5. `RunRequest` 必须经统一 `build_run_request(...)` 和 run key builder；不得新增直接 `dg.RunRequest(...)`。
6. sensor cursor 必须使用结构化 payload，不得塞大样本、大 SQL 或大文件清单。

## 3. Target Dataset Contract

### 3.1 Asset Contract

新增 Dagster asset：

- Asset key: `gold_stock_daily_qfq`
- Dataset id: `stock_daily_qfq`
- 中文名: `股票日线前复权`
- Layer: `gold`
- Domain: `quote_data`
- Group: `quote`
- Partition definition: `cn_a_stock_trade_days`

使用 `cn_a_stock_trade_days` 的原因：

- `silver_stock_daily` 是该资产的直接行情输入。
- 输出是按交易日组织的历史日线资产。
- 不使用 `cn_a_stock_current_trade_days`，避免把 current snapshot 口径混入 gold 历史日线资产。

### 3.2 Lake Path

新增 path helper：

```python
def gold_stock_daily_qfq_path(root: Path, partition_key: str) -> Path:
    return (
        root
        / "gold"
        / "quote"
        / "stock_daily_qfq"
        / f"trade_date={partition_key}"
        / "part-000.parquet"
    )
```

禁止：

- 不使用 stock-year 布局。
- 不新增第二套 raw/silver 风格路径。
- 不让下游自己拼路径。

### 3.3 Column Schema

新增 `GOLD_STOCK_DAILY_QFQ_SCHEMA`：

```python
GOLD_STOCK_DAILY_QFQ_SCHEMA = {
    "ts_code": "VARCHAR",
    "trade_date": "DATE",
    "open": "DOUBLE",
    "high": "DOUBLE",
    "low": "DOUBLE",
    "close": "DOUBLE",
    "pre_close": "DOUBLE",
    "change_amount": "DOUBLE",
    "pct_chg": "DOUBLE",
    "vol": "DOUBLE",
    "amount": "DOUBLE",
}
```

字段语义：

- `open/high/low/close`: 前复权价格。
- `pre_close`: 前复权后的上一可交易日收盘价。
- `change_amount`: `close - pre_close`。
- `pct_chg`: `change_amount / pre_close * 100`。
- `vol/amount`: 成交量、成交额不复权，沿用 `silver_stock_daily`。

上市首日或湖中找不到上一可交易日 source row 时：

- `pre_close = 0`
- `change_amount = 0`
- `pct_chg = 0`

理由：

- 新上市股票首个可计算交易日本身没有上一可交易日收盘价。
- 不能 fallback 到任意更早、不属于该股票生命周期的行。
- 这类 0 是“无上一可交易日”的业务占位，不是错误兜底。
- 若 previous source row 存在但 previous factor 缺失，仍必须 fail closed，不得静默写 0。

### 3.4 Catalog Entry

在 `catalog/lake_assets.py` 新增：

- `PartitionModel.TRADE_DATE_PARTITION_GOLD_STOCK_DAILY_QFQ`
- `GOLD_STOCK_DAILY_QFQ_CHECKS`
- `LAKE_ASSET_CATALOG["gold_stock_daily_qfq"]`

catalog 口径：

- `storage_path_template = "gold/quote/stock_daily_qfq/trade_date={trade_date}/part-000.parquet"`
- `partition_model = TRADE_DATE_PARTITION_GOLD_STOCK_DAILY_QFQ`
- `source_assets = ["silver_stock_daily", "silver_adj_factor"]`
- ordinary check count = 2
- repair status check 单独列为 protected status check，不纳入 ordinary check count。

## 4. QFQ Formula

### 4.1 Daily As-Of Formula

对目标交易日 `D`，日常生成使用：

```text
as_of_trade_date = D
```

每个 source price 的前复权公式：

```text
qfq_price = source_price * adj_factor(row_trade_date) / adj_factor(as_of_trade_date)
```

日常生成中 `row_trade_date = as_of_trade_date = D`，因此 `open/high/low/close` 通常与未复权价一致；但仍必须通过统一 SQL 公式生成。

原因：

- 和 repair 公式保持一致。
- 下游永远只读 gold qfq，不需要理解 source/as-of 差异。
- 后续历史 repair 时同一套公式可以用新的 as-of factor 重算历史行。

### 4.2 Previous Close Formula

`pre_close` 不直接照抄 `silver_stock_daily.pre_close`。正式口径为：

```text
previous_source_close = latest silver_stock_daily.close for same ts_code before D
previous_adj_factor = silver_adj_factor for same ts_code at previous_source_trade_date
as_of_adj_factor = silver_adj_factor for same ts_code at D
pre_close_qfq = previous_source_close * previous_adj_factor / as_of_adj_factor
change_amount = close_qfq - pre_close_qfq
pct_chg = change_amount / pre_close_qfq * 100
```

previous source row 按股票自身在 `silver_stock_daily` 中的上一可用交易日计算，不按全市场上一交易日硬推。

没有 previous source row 时：

```text
pre_close = 0
change_amount = 0
pct_chg = 0
```

这个分支只适用于上市首日或湖中该股票第一条可用日线。存在 previous source row 但缺 previous factor 时，必须 fail closed。

这样可以覆盖：

- 新上市股票。
- 临停或长期停牌后恢复交易。
- 个股缺某日 source row 的情况。

### 4.3 Repair As-Of Formula

当复权因子在交易日 `R` 发生变化时，repair 使用：

```text
as_of_trade_date = R
historical_qfq_price = source_price_at_trade_date * adj_factor(source_trade_date) / adj_factor(R)
```

即 repair 会按 `R` 的复权因子重写受影响股票在历史日期范围内的 qfq 行。

禁止：

- 不用 `silver_stock_daily.close * adj_factor` 这种简化公式。
- 不允许下游报告临时拼复权公式。
- 不允许用缺失上一日时 fallback 到任意更早、不属于股票生命周期的行。

## 5. Code Layout

### 5.1 New Files

建议新增：

```text
lake_console/orchestrator/src/orchestrator/defs/stock_daily_qfq.py
lake_console/orchestrator/src/orchestrator/defs/assets/stock_daily_qfq.py
lake_console/orchestrator/src/orchestrator/defs/checks/stock_daily_qfq_checks.py
lake_console/orchestrator/src/orchestrator/defs/ops/gold_stock_daily_qfq_factor_repair.py
lake_console/orchestrator/src/orchestrator/defs/sensors/stock_daily_qfq_sensor.py
lake_console/orchestrator/src/orchestrator/defs/sensors/gold_stock_daily_qfq_factor_repair_job_sensor.py
```

职责：

- `defs/stock_daily_qfq.py`: SQL、writer、repair range helper、metadata helper。
- `defs/assets/stock_daily_qfq.py`: asset、daily job、repair job definition。
- `defs/checks/stock_daily_qfq_checks.py`: 2 个 ordinary blocking checks 和 1 个 protected repair status check。
- `defs/ops/gold_stock_daily_qfq_factor_repair.py`: repair op 与 config 消费。
- `defs/sensors/stock_daily_qfq_sensor.py`: daily sensor。
- `defs/sensors/gold_stock_daily_qfq_factor_repair_job_sensor.py`: repair run-status sensor。

### 5.2 Existing Files To Modify

需要修改：

```text
lake_console/orchestrator/src/orchestrator/defs/paths.py
lake_console/orchestrator/src/orchestrator/defs/asset_column_schemas.py
lake_console/orchestrator/src/orchestrator/defs/catalog/lake_assets.py
lake_console/orchestrator/src/orchestrator/defs/catalog/name_mapping.py
lake_console/orchestrator/src/orchestrator/defs/sensors/readiness.py
lake_console/orchestrator/src/orchestrator/defs/run_contracts/configs.py
```

实现前必须再次确认 current definitions loader 是否会自动发现新文件；不得凭历史印象手写注册。

## 6. Asset Write Path

### 6.1 Asset Function

建议：

```python
@dg.asset(
    key="gold_stock_daily_qfq",
    partitions_def=cn_a_stock_trade_days,
    deps=[silver_stock_daily, silver_adj_factor],
    group_name="quote",
    metadata=...,
    tags=...,
)
def gold_stock_daily_qfq(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    ...
```

执行流程：

1. 读取 `partition_key`。
2. 计算目标输入：
   - `silver_stock_daily_path(root, partition_key)`
   - `silver_adj_factor_path(root, partition_key)`
3. 计算 previous lookup：
   - 从 `silver_trade_calendar` 取 `partition_key` 前最多 20 个 expected trade dates。
   - 生成这些日期的 `silver_stock_daily_path` 与 `silver_adj_factor_path` 候选。
   - 只读取存在的文件。
4. 若目标日 `silver_stock_daily` 或目标日 `silver_adj_factor` 缺失，抛 `dg.Failure`。
5. 使用 DuckDB set-based SQL 生成 qfq rows。
6. 写临时文件，再原子替换目标 Parquet。
7. 返回 `dg.MaterializeResult`。

materialization metadata：

- `row_count`
- `observed_columns`
- `output_file_path`
- `source_silver_stock_daily_file_path`
- `source_silver_adj_factor_file_path`
- `previous_lookup_trade_date_count`
- `missing_previous_row_count`

### 6.2 SQL Helper

新增：

```python
def build_stock_daily_qfq_select_sql(
    *,
    stock_daily_path: Path,
    trade_adj_factor_path: Path,
    previous_stock_daily_paths: Sequence[Path],
    previous_adj_factor_paths: Sequence[Path],
    as_of_adj_factor_path: Path,
    trade_date: str,
    as_of_trade_date: str,
) -> str:
    ...
```

SQL 结构：

1. `source_daily`: 读取目标日 `silver_stock_daily`。
2. `trade_factor`: 读取 row trade date 对应 factor。
3. `as_of_factor`: 读取 as-of 日 factor。
4. `previous_daily`: 从 previous paths 读取，并按 `ts_code` 取最大 `trade_date`。
5. `previous_factor`: 读取 previous row 对应 factor。
6. 输出 qfq 字段。

性能约束：

- 使用 DuckDB `read_parquet([...])` 或等价批量读取。
- 禁止 Python 行循环。
- previous lookup 默认最多 20 个 expected dates。
- SQL 和 metadata 不写大样本行。

### 6.3 Writer Helper

新增：

```python
def write_gold_stock_daily_qfq_partition(
    *,
    connection: duckdb.DuckDBPyConnection,
    lake_root: Path,
    trade_date: str,
    previous_lookup_trade_dates: Sequence[str],
) -> StockDailyQfqWriteResult:
    ...
```

`StockDailyQfqWriteResult` 字段：

- `trade_date`
- `output_path`
- `row_count`
- `source_row_count`
- `missing_previous_row_count`
- `previous_lookup_start_date`
- `previous_lookup_end_date`
- `previous_lookup_file_count`

## 7. Asset Checks

### 7.1 Check Count

初版设计 2 个 ordinary blocking checks。

原因：

- 避免把每条 SQL 规则拆成独立 Dagster check，导致 Dagster DB 增量过快。
- 保留足够的 UI 可观测性和 sensor readiness 判断能力。
- 细节规则进入 check metadata 的 `failed_rule_names` 和样本，不独立成 Dagster check。
- 一个资产每天只新增 2 条 ordinary check event，避免新资产上线后继续放大 Dagster DB 压力。

### 7.2 Check Names

ordinary checks：

```text
gold_stock_daily_qfq_contract_check
gold_stock_daily_qfq_qfq_semantics_check
```

protected status check：

```text
gold_stock_daily_qfq_factor_repair_plan_evaluated
```

`gold_stock_daily_qfq_factor_repair_plan_evaluated` 不属于 daily readiness checks；它是 repair 状态账本，后续 event retention 必须保护。

### 7.3 Contract Check

`gold_stock_daily_qfq_contract_check` 覆盖：

- 文件存在。
- row count > 0。
- schema 与 `GOLD_STOCK_DAILY_QFQ_SCHEMA` 一致。
- `trade_date` 列非空。
- 文件内 `trade_date` 必须等于 partition key。
- `ts_code` 非空。
- `(ts_code, trade_date)` 唯一。

metadata：

- `checked_row_count`
- `failed_rule_names`
- `file_path`
- `partition_key`
- `duplicate_key_count`
- `null_key_count`
- `sample_rows`

### 7.4 QFQ Semantics Check

`gold_stock_daily_qfq_qfq_semantics_check` 覆盖：

- 每个 source row 都有 row trade date 对应 `silver_adj_factor`。
- 每个 source row 都有 as-of trade date 对应 `silver_adj_factor`。
- 存在 previous source row 的股票，必须能找到 previous row 的 factor。
- 没有 previous source row 的股票，允许 `pre_close/change_amount/pct_chg` 为 0，但必须能解释为首个可用交易日。
- `open/high/low/close` 与前复权公式一致。
- `pre_close` 与 previous source close 前复权公式一致。
- `change_amount = close - pre_close`。
- `pct_chg = change_amount / pre_close * 100`。
- `high >= greatest(open, close, low)` 等基本价格关系。
- 价格与成交量不能出现明显非法值。
- 如果 previous source row 存在，`pre_close/change_amount/pct_chg` 不得用 0 冒充无法计算结果。

允许误差：

- price formula tolerance: `1e-6`
- pct formula tolerance: `1e-6`

metadata：

- `checked_row_count`
- `source_row_count`
- `missing_trade_factor_count`
- `missing_as_of_factor_count`
- `missing_previous_factor_count`
- `allowed_missing_previous_row_count`
- `formula_mismatch_count`
- `price_domain_failed_count`
- `failed_rule_names`
- `sample_rows`

## 8. Daily Job

新增：

```python
gold_stock_daily_qfq_update_job = dg.define_asset_job(
    name="gold_stock_daily_qfq_update_job",
    selection=(
        dg.AssetSelection.assets(gold_stock_daily_qfq)
        | dg.AssetSelection.checks_for_assets(gold_stock_daily_qfq)
    ),
)
```

禁止：

- job 内不写 SQL。
- job 不包含 repair op。
- job 不包含报告逻辑。
- job 不直接构造 run key。

## 9. Daily Sensor

### 9.1 Sensor Definition

新增：

```python
@dg.sensor(
    name="gold_stock_daily_qfq_update_job_sensor",
    job=gold_stock_daily_qfq_update_job,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb"},
)
def gold_stock_daily_qfq_update_job_sensor(...):
    ...
```

默认 `STOPPED`，由运营确认后再开启。

### 9.2 Target Selection

target selection 口径：

1. 用 `silver_trade_calendar` 生成最近 10 个 expected trade dates。
2. partition set 使用 `cn_a_stock_trade_days`。
3. 先查 registered gap。
4. 再查 `gold_stock_daily_qfq` 自身 readiness。
5. 选择 first not-ready date。
6. selected date 上检查上游：
   - `silver_stock_daily` ready。
   - `silver_adj_factor` ready。
7. 上游 ready 后提交 selected date run。

禁止：

- 不按 latest registered 直接推进。
- 不扫描全历史 Dagster event。
- 不解析 run key 反推 config。
- 不新增直接 `dg.RunRequest(...)`。

### 9.3 Run Request

使用统一 builder：

```python
build_run_request(
    job_name="gold_stock_daily_qfq_update_job",
    partition_key=trade_date,
    run_key=build_asset_update_run_key(
        subject="gold_stock_daily_qfq_update",
        unit_id=trade_date,
    ),
    run_config=None,
    tags=...,
)
```

run key：

```text
gold_stock_daily_qfq_update:{trade_date}
```

### 9.4 Cursor

cursor 使用 `build_sensor_cursor(...)`。

cursor details：

- `continuity_status`
- `gold_stock_daily_qfq_status`
- `silver_stock_daily_status`
- `silver_adj_factor_status`
- `reason_code`

`reason_code` 必须是英文枚举，例如：

- `missing_registered_partition`
- `gold_stock_daily_qfq_not_ready`
- `upstream_silver_stock_daily_not_ready`
- `upstream_silver_adj_factor_not_ready`
- `selected_for_update`
- `all_ready`

不允许中文 reason code。

## 10. Repair Job

### 10.1 Why Separate Repair

日常生成和 repair 不合并为同一个 job。

原因：

- 日常生成只写一个 trade date partition。
- repair 会改写多个历史 trade date partition，风险和耗时明显更高。
- repair 需要 status metadata、affected code hash、effective range 等审计信息。
- 合并入口会让 sensor、run key、config、权限和回滚边界混在一起。

### 10.2 Repair Job Definition

新增：

```python
gold_stock_daily_qfq_factor_repair_job = dg.job(
    name="gold_stock_daily_qfq_factor_repair_job",
    resource_defs=...,
)(...)
```

内部只包含一个 op：

```text
gold_stock_daily_qfq_factor_repair_op
```

repair job 不由定时 sensor 直接扫描全量触发，而是由 run-status sensor 在 daily qfq 成功后做 bounded plan 判断并自动提交。

### 10.3 Repair Config

在 `run_contracts/configs.py` 新增显式 config：

```python
class GoldStockDailyQfqFactorRepairConfig(dg.Config):
    qfq_factor_trade_date: str
    repair_required_codes_hash: str
    upstream_batch_id: str
```

已拍板：初版不支持手写 `stock_codes`，config schema 中不得出现 `stock_codes` 字段。

原因：

- 受影响股票应来自 `silver_adj_factor` 与 previous expected date 的因子 diff。
- 手写 code list 容易产生散装 repair 和审计口径漂移。
- repair op 内部重新计算 affected codes，并校验 config 中的 `repair_required_codes_hash`。
- `upstream_batch_id` 来自触发本次判断的 daily qfq run 和 affected codes hash，用于 run key 幂等和 repair completion 对账。
- 如果未来需要人工限定 stock_codes，必须另开设计并要求 hash/source/audit metadata。

### 10.4 Repair Run-Status Sensor

已拍板：repair 初版必须增加自动 run-status sensor。它不是定时扫全量日期的 sensor，而是只监听 `gold_stock_daily_qfq_update_job` 成功 run，并对触发 run 的单个 `trade_date` 做 bounded repair plan 判断。

新增：

```python
@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.SUCCESS,
    request_job=gold_stock_daily_qfq_factor_repair_job,
    monitored_jobs=[gold_stock_daily_qfq_update_job],
    default_status=dg.DefaultSensorStatus.STOPPED,
    tags=...,
)
def gold_stock_daily_qfq_factor_repair_job_sensor(
    context: dg.RunStatusSensorContext,
) -> dg.RunRequest | dg.SkipReason:
    ...
```

触发口径：

1. 只监听 `gold_stock_daily_qfq_update_job` 成功。
2. 从触发 run 的 partition tag 读取 `qfq_factor_trade_date`。
3. 只对该交易日计算 repair plan。
4. 不定时扫全量日期。
5. 不扫描全历史 Dagster event。
6. 不在 sensor 中写 lake 文件或 Dagster event。

sensor 决策流程：

1. 解析 target trade date；无法解析则 skip。
2. 确认 target date 的 `gold_stock_daily_qfq` ordinary readiness ready；不 ready 则 skip。
3. 读取 target date 和上一 expected trade date 的 `silver_adj_factor`。
4. 用 DuckDB set-based SQL 计算 affected codes。
5. 若 affected codes 为空，skip。
6. 若 affected codes 数量超过自动上限，skip，要求人工 dry-run 后再处理。
7. 计算 `repair_required_codes_hash`。
8. 用触发 daily run id、target trade date、hash 构造 `upstream_batch_id`。
9. 查询同一 `upstream_batch_id` 的 repair status；已 ready 则 skip。
10. 未完成则提交 `gold_stock_daily_qfq_factor_repair_job`。

run key：

```python
build_upstream_triggered_run_key(
    consumer="gold_stock_daily_qfq_factor_repair",
    upstream_batch_id=upstream_batch_id,
)
```

run config：

```python
{
    "ops": {
        "gold_stock_daily_qfq_factor_repair_op": {
            "config": {
                "qfq_factor_trade_date": target_trade_date,
                "repair_required_codes_hash": repair_required_codes_hash,
                "upstream_batch_id": upstream_batch_id,
            }
        }
    }
}
```

自动上限：

```python
GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_AUTO_CODE_LIMIT = 500
```

超过上限不代表不能修，只代表不能自动修。后续必须通过 repair dry-run 报告单独审批。

### 10.5 Affected Code Detection

新增：

```python
def build_stock_daily_qfq_factor_changed_codes_sql(
    *,
    current_adj_factor_path: Path,
    previous_adj_factor_path: Path,
) -> str:
    ...
```

语义：

- `qfq_factor_trade_date = R`。
- 找 previous expected trade date `P`。
- 比较 `silver_adj_factor[R]` 与 `silver_adj_factor[P]`。
- `adj_factor` 变化的股票进入 affected set。
- 新上市导致 previous factor 不存在、且没有历史 qfq 行的股票不进入 repair set。

### 10.6 Effective Repair Range

repair range 不使用全局历史起点。

计算：

1. 读取 affected codes。
2. 从现有 `gold_stock_daily_qfq/trade_date=*/part-000.parquet` 中批量查询 affected codes 的最早 `trade_date`。
3. `effective_start_trade_date = min(existing qfq trade_date for affected codes)`。
4. `repair_end_trade_date = qfq_factor_trade_date`。
5. target dates = expected calendar between effective start and repair end。

如果 affected codes 非空但没有任何现有 qfq row：

- fail closed。
- 不写 success metadata。
- 提示需要先完成历史 bootstrap。

### 10.7 Repair Write Strategy

对每个 target trade date：

1. 必须存在现有 `gold_stock_daily_qfq` partition 文件。
2. 必须存在对应 `silver_stock_daily` source 文件。
3. 必须存在 target trade date 的 `silver_adj_factor`。
4. 必须存在 as-of trade date 的 `silver_adj_factor`。
5. 生成 affected codes 的 replacement rows。
6. 读取 existing gold qfq rows。
7. 删除 existing 中 affected codes 的旧 rows。
8. union unaffected rows + replacement rows。
9. 校验 `(ts_code, trade_date)` 唯一。
10. 写临时文件后原子替换目标文件。

禁止：

- 不创建原本不存在的历史 partition。
- 不跳过中间缺失 partition 后继续写。
- 不在 Python 中逐行循环计算价格。
- 不写旧 storage id 字段。

### 10.8 Repair Status Check

新增 protected check：

```text
gold_stock_daily_qfq_factor_repair_plan_evaluated
```

metadata：

- `qfq_factor_trade_date`
- `repair_start_trade_date`
- `repair_end_trade_date`
- `repair_required_codes`
- `repair_required_codes_count`
- `repair_required_codes_hash`
- `rewritten_partition_count`
- `rewritten_row_count`
- `skipped_partition_count`
- `upstream_batch_id`
- `producer_run_id`

`upstream_batch_id` 使用统一 `build_batch_id(...)`。

禁止：

- 不写 `event_storage_id`。
- 不写旧 storage id 字段。
- 不把完整大 code list 写到 cursor。
- metadata 中 code list 必须有上限；超过上限写 hash 和 truncated 标记，并 fail closed 或要求分批设计。

## 11. Historical Bootstrap And Event Backfill

### 11.1 Why Bootstrap Is Needed

`gold_stock_daily_qfq` 的主要业务价值是计算长期均线和指标。如果只从上线日起增量生成，则 MA250 等下游会缺历史基础。

因此需要历史 bootstrap。

### 11.2 Bootstrap Scope

历史 bootstrap 生成文件：

- 从 `silver_stock_daily` 已有最早日期开始。
- 到当前最新 `cn_a_stock_trade_days`。
- 只处理 `silver_stock_daily` 与 `silver_adj_factor` 都存在的日期。

历史 bootstrap 不通过 Dagster sensor 自动触发。

建议新增 bootstrap CLI：

```text
python -m orchestrator.defs.bootstrap.gold_stock_daily_qfq_bootstrap build-files
```

参数：

- `--lake-root`
- `--start-date`
- `--end-date`
- `--batch-size`
- `--dry-run`
- `--output`

### 11.3 Runless Event Backfill Policy

为兼顾历史可追溯性与 Dagster DB 增长控制，历史 bootstrap 的 materialization event 与 ordinary check event 分开补录。

默认策略：

1. 文件全历史生成。
2. Dagster runless materialization event 全历史补录。
3. Dagster runless ordinary check event 只补：
   - 最近 20 个 `cn_a_stock_trade_days`。
   - latest partition。
4. repair/status protected check event 按 repair trade date 单独写入，不参与 ordinary check event 补录窗口。
5. 如果运营明确要求 UI 可证明全部历史 partition 的 ordinary checks 都 ready，再单独审批全历史 check event backfill。

理由：

- materialization event 表达“历史分区文件存在且已生成”，全历史补录成本可控。
- 报告和计算读取 Parquet 文件，不依赖 Dagster 历史 event。
- sensor 日常推进只依赖 recent window 和 latest 的 check 状态。
- 20 日以前的历史质量证明以 bootstrap 文件审计报告为准，不要求 Dagster DB 长期保存每个历史分区的 check 绿灯。
- 避免新数据集一上线就制造数千个历史 ordinary check event。

### 11.4 Bootstrap Safety

bootstrap 必须：

- 先 dry-run 输出日期数、预计文件数、预计行数。
- 样本执行 1 个 partition。
- 再分批执行全量。
- 每批写入后有 row count / schema / formula 抽样验证。
- 不删除已有 `silver_stock_daily` 或 `silver_adj_factor`。
- 不清理 Dagster DB。

## 12. Readiness

### 12.1 New Readiness Specs

在 `sensors/readiness.py` 中新增：

```python
GOLD_STOCK_DAILY_QFQ_READINESS_SPECS = (
    AssetReadinessSpec(
        asset_key=dg.AssetKey("gold_stock_daily_qfq"),
        required_check_names=GOLD_STOCK_DAILY_QFQ_CHECK_NAMES,
    ),
)
```

ordinary readiness 只包含 2 个 ordinary checks。

不包含：

- `gold_stock_daily_qfq_factor_repair_plan_evaluated`

### 12.2 Readiness Helper

新增：

```python
def gold_stock_daily_qfq_ready_for_trade_date(
    instance: dg.DagsterInstance,
    trade_date: str,
) -> DatasetReadinessStatus:
    ...
```

使用现有 `partition_dataset_readiness_status_from_latest_checks(...)` pattern。

注意：

- 只用于 selected date。
- 不允许在 sensor hot path 对 10 天窗口逐日扫 Dagster event。
- 如未来发现性能问题，应补 DuckDB lake readiness batch helper，而不是扩大 Dagster event scan。

## 13. Performance Gate

### 13.1 Daily Update

目标规模：

- 每日 source 行数：约 A 股日线几千行。
- 输入文件：
  - 目标日 `silver_stock_daily` 1 个文件。
  - 目标日 `silver_adj_factor` 1 个文件。
  - previous lookup 最多 20 个 `silver_stock_daily` 文件。
  - previous lookup 最多 20 个 `silver_adj_factor` 文件。
- 输出文件：1 个 Parquet。
- Dagster event：1 materialization + 2 ordinary checks。

不可接受：

- 每日 job 读全历史日线。
- 每日 sensor 扫全历史 Dagster event。
- 每日 sensor 对每个股票逐个查询。

### 13.2 Repair

repair 必须先 dry-run。

dry-run 输出：

- affected code count
- effective start date
- target partition count
- expected source file count
- estimated rewrite row count
- estimated output file count
- missing source partition samples

不可接受：

- 未 dry-run 直接全量 rewrite。
- Python row loop 计算全市场历史价格。
- 写完整历史所有股票，而不是 affected codes。
- repair status metadata 写超大 code list。

### 13.3 Event Growth

ordinary check event 增量：

- 日常：每个交易日 2 条 ordinary check event。
- bootstrap materialization event 全历史补录。
- bootstrap ordinary check event 默认只补最近 20 日 + latest。
- repair：每个 repair trade date 1 条 protected status check。

这比把细粒度 SQL 规则拆成十几个 check 更可控。

## 14. Tests

### 14.1 Test Files

新增：

```text
tests/test_stock_daily_qfq_contracts.py
tests/test_stock_daily_qfq_checks.py
tests/test_stock_daily_qfq_sensor_contracts.py
tests/test_stock_daily_qfq_repair_contracts.py
```

### 14.2 Asset Write Tests

覆盖：

- 目标日 source 和 factor 都存在时写入成功。
- `open/high/low/close` 按 formula 生成。
- `pre_close/change_amount/pct_chg` 按上一可交易日生成。
- 新上市首日 previous row 缺失时 `pre_close/change_amount/pct_chg` 为 0。
- previous row 缺失时 0 是合法业务占位；previous row 存在但 previous factor 缺失时仍 fail closed。
- 目标日 `silver_stock_daily` 缺失 fail closed。
- 目标日 `silver_adj_factor` 缺失 fail closed。
- previous row 存在但 previous factor 缺失 fail closed。

### 14.3 Check Tests

覆盖：

- contract: 缺文件、空文件、schema mismatch、partition date mismatch。
- key integrity: null key、duplicate key。
- factor coverage: missing trade factor、missing as-of factor、missing previous factor。
- formula consistency: price formula mismatch、pre_close formula mismatch、change/pct mismatch、price domain failure。

### 14.4 Sensor Tests

覆盖：

Daily sensor：

- registered gap 时 skip。
- output 缺失时提交 selected date run。
- output materialized but check failed 时 skip，不自动重跑。
- selected date `silver_stock_daily` not ready 时 skip。
- selected date `silver_adj_factor` not ready 时 skip。
- all ready 时 skip。
- run key 为 `gold_stock_daily_qfq_update:{trade_date}`。
- 不出现直接 `dg.RunRequest(...)`。

Repair run-status sensor：

- 监听 `gold_stock_daily_qfq_update_job` success。
- target trade date 解析失败时 skip。
- target `gold_stock_daily_qfq` ordinary readiness 不 ready 时 skip。
- affected codes 为空时 skip。
- affected codes 超过自动上限时 skip。
- repair status 已 ready 时 skip。
- affected codes 未超过上限、completion 未 ready 时提交 repair job。
- run key 使用 `build_upstream_triggered_run_key(...)`。
- run config 不包含 `stock_codes`。

### 14.5 Repair Tests

覆盖：

- factor unchanged no-op，写 repair status。
- factor changed，effective start 来自现有 qfq rows。
- affected codes 起点不同，effective start 取最早 qfq row。
- affected code 无现有 qfq rows 时 fail closed。
- missing intermediate qfq partition fail closed。
- repair 只改 affected codes，不改 unaffected rows。
- metadata 写 `repair_required_codes_hash` 与 `upstream_batch_id`。
- repair op 重新计算 affected codes，并校验 config 里的 `repair_required_codes_hash`。
- config 不允许 `stock_codes`。

### 14.6 Static Gates

更新 `tests/test_run_contract_static_gates.py`：

- 新 sensor 禁止直接 `dg.RunRequest(...)` / `RunRequest(...)`。
- 新 sensor 禁止手写 `run_key=f`。
- repair config 禁止 `event_storage_id` / `storage_id`。
- repair config 禁止 `stock_codes`。
- repair run-status sensor 必须使用 `build_upstream_triggered_run_key(...)`。
- repair run-status sensor 必须监控 `gold_stock_daily_qfq_update_job`。
- ordinary check count 固定为 2。
- protected repair status check 不得进入 ordinary readiness spec。
- bootstrap CLI 不得有默认 apply/delete。

## 15. Development Phases

### P0: LLD Review

当前阶段。

输出：

- 本 LLD。
- 用户 review 后确认是否进入编码。

### P1: Core Formula And Writer

状态：已完成。

范围：

- path helper
- schema
- SQL helper
- writer helper
- asset materialization
- asset write unit tests

不做：

- sensor
- repair
- bootstrap

已落地文件：

- `defs/paths.py`: `gold_stock_daily_qfq_path(...)`
- `defs/run_contracts/asset_column_schemas.py`: `GOLD_STOCK_DAILY_QFQ_SCHEMA`
- `defs/catalog/name_mapping.py`: `stock_daily_qfq` 中文名。该项原列在 P2，但 P1 asset definition metadata 必须立即解析 dataset 中文名，否则 definitions 导入会失败；catalog registry 仍留到 P2。
- `defs/stock_daily_qfq.py`: qfq SQL、coverage validation、previous lookup、writer helper。
- `defs/assets/stock_daily_qfq.py`: `gold_stock_daily_qfq` asset definition。
- `tests/test_stock_daily_qfq_contracts.py`: P1 formula/writer/asset definition tests。

本地验证：

```bash
cd lake_console/orchestrator
PYTHONPATH=src uv run --project . --with pytest python -m pytest tests/test_stock_daily_qfq_contracts.py
```

结果：`6 passed`。测试只使用临时目录和本地 DuckDB，不读取正式 Dagster runtime，不触碰正式数据湖。

### P2: Checks And Catalog

范围：

- catalog entry
- name mapping
- 2 ordinary checks
- readiness specs
- check tests
- static gates

已落地文件：

- `defs/catalog/lake_assets.py`: `gold_stock_daily_qfq` catalog entry、`TRADE_DATE_PARTITION_GOLD_STOCK_DAILY_QFQ` partition model、2 条 ordinary blocking checks。
- `defs/checks/stock_daily_qfq_checks.py`: `gold_stock_daily_qfq_contract_check` 与 `gold_stock_daily_qfq_qfq_semantics_check`。
- `defs/sensors/readiness.py`: `GOLD_STOCK_DAILY_QFQ_READINESS_SPECS` 与 `gold_stock_daily_qfq_ready_for_trade_date(...)`。
- `tests/test_stock_daily_qfq_checks.py`: contract/qfq semantics check 正反例。
- `tests/test_stock_daily_qfq_contracts.py`: catalog/readiness 对账测试。
- `tests/test_asset_governance_contracts.py`: active asset / catalog 数量与 blocking check 对账。
- `tests/test_run_contract_static_gates.py`: ordinary check 数量、防 repair status 进入 ordinary readiness、DuckDB 连接门禁。

已确认口径：

- ordinary readiness 只包含：
  - `gold_stock_daily_qfq_contract_check`
  - `gold_stock_daily_qfq_qfq_semantics_check`
- `gold_stock_daily_qfq_factor_repair_plan_evaluated` 不进入 ordinary readiness。
- 两个 ordinary checks 内部用 `failed_rule_names` 表达子规则，不拆成更多 Dagster check，避免 asset check event 过快膨胀。
- check 只读临时/目标 Parquet 与上游 silver 文件，不写 lake，不写 Dagster event。

本地验证：

```bash
cd lake_console/orchestrator
PYTHONPATH=src uv run --project . --with pytest python -m pytest \
  tests/test_stock_daily_qfq_contracts.py \
  tests/test_stock_daily_qfq_checks.py \
  tests/test_asset_governance_contracts.py \
  tests/test_run_contract_static_gates.py
```

结果：`93 passed`。测试只使用临时目录、本地 DuckDB 和静态扫描，不运行 `dg`，不读取正式 Dagster instance，不触碰正式数据湖。

### P3: Daily Job And Sensor

范围：

- daily job
- daily sensor
- run key / cursor tests
- targeted local pytest

### P4: Repair Core

范围：

- repair config
- affected code detection
- effective range
- rewrite logic
- protected status check
- repair run-status sensor
- upstream-triggered run key / completion status tests
- repair tests

### P5: Bootstrap Dry-Run

范围：

- bootstrap CLI dry-run
- sample partition build
- performance report

不做正式全量写入，除非单独审批。

### P6: Historical Bootstrap And Runless Event Backfill

范围：

- full file bootstrap
- full-history runless materialization event backfill
- recent 20 + latest runless ordinary check event backfill
- post-bootstrap readiness verification

必须单独审批正式 lake 写入与 runless event 写入。

### P7: Documentation Closeout

范围：

- 更新高层设计文档状态。
- 更新 asset schema contract / onboarding index 如需要。
- 更新 performance governance 的新增数据集样例或 check count。

## 16. Stop Conditions

任一情况立即停止：

1. 发现 `silver_stock_daily` 与 `silver_adj_factor` 无法稳定表达日线前复权。
2. 发现必须改 `silver_stock_daily` schema 才能实现。
3. 发现需要报告逻辑才能验证本资产正确性。
4. 发现 daily update 必须读全历史。
5. 发现 repair 必须重写全市场全历史所有股票。
6. 发现必须新增大量细粒度 Dagster checks 才能表达 readiness。
7. 发现必须直接读取或写正式 Dagster runtime 才能完成代码阶段测试。
8. 发现必须使用旧 storage id 或解析 run key 反推 config。

## 17. Confirmed Decisions

以下口径已拍板，不再作为待确认项：

1. 上市首日或无 previous source row 时，`pre_close/change_amount/pct_chg` 统一写 0，不写 NULL。
2. repair 初版不开放手写 `stock_codes`；affected codes 必须由 `silver_adj_factor` 相邻 expected trade date diff 自动计算。
3. repair 初版增加自动 run-status sensor；触发方式参考股票分钟线 MACD/KDJ repair：`gold_stock_daily_qfq_update_job` 成功后自动判断并提交 scoped repair job。

补充约束：

1. `0` 只用于无 previous source row；previous source row 存在但 previous factor 缺失时仍失败。
2. `stock_codes` 不得作为 repair config、正式 CLI 参数或 sensor payload 暴露。
3. 自动 sensor 必须是 run-status sensor，只处理触发 run 的单个 `trade_date`，并受 affected code 上限、hash、completion/status 和性能门禁约束。
