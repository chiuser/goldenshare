# Dagster Gold Wealth Market Turnover Dataset Low-Level Design

状态：开发中。WMT-1/WMT-2/WMT-3 已按当前治理测试事实合并为第一个可验证闭环并完成；WMT-4 job/sensor 已完成；WMT-5 历史 bootstrap/runless event 未实现。本文档是 [Dagster Gold Wealth Market Turnover Dataset Design](dagster-gold-wealth-market-turnover-dataset-design.md) 的编码级落地方案和执行对账记录。

## 0. 依据和硬口径

已重新阅读：

1. `/Users/congming/github/goldenshare/AGENTS.md`
2. `/Users/congming/github/goldenshare/lake_console/AGENTS.md`
3. `/Users/congming/github/goldenshare/lake_console/orchestrator/AGENTS.md`
4. `/Users/congming/github/goldenshare/lake_console/orchestrator/CODING_STANDARDS.md`
5. `/Users/congming/github/goldenshare/lake_console/docs/design/dagster-data-pipeline-performance-governance.md`
6. `/Users/congming/github/goldenshare/lake_console/docs/design/dagster-asset-schema-contract-design.md`
7. `/Users/congming/github/goldenshare/lake_console/docs/design/dagster-gold-wealth-market-turnover-dataset-design.md`
8. `/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/turnover-minute-snapshot-plan-v1.html`

CodeGraph 审计范围：

1. `gold_market_breadth_daily`：确认 gold derived asset、path、schema、catalog、checks、job 的现有模式。
2. `batch_silver_stk_mins_lake_readiness`：确认股票分钟线 silver readiness helper 的位置、签名和正式消费者。
3. `STOCK_MINS_SILVER_RUN_START`：确认当前 silver 日更时间为 `time(19, 50)`。
4. `lake_console/orchestrator/src/orchestrator/defs` 文件树：确认新增落点在现有 `assets/checks/jobs/sensors/asset_guards/bootstrap/run_contracts/catalog` 结构内。

本 LLD 硬口径：

1. 只新增 `gold_wealth_market_turnover` 资产族，不改现有 Wealth API、旧 serving 表、旧 CLI。
2. 数据源只读 `silver_stk_mins` 五个频度文件。
3. 输出 `points_json` 必须是 DuckDB/Parquet 可校验的 `JSON` 逻辑类型，不允许降级为 `VARCHAR`。
4. 每个交易日输出一个 parquet，文件内恰好五行，对应 `1/5/15/30/60`。
5. 只暴露一个 blocking check：`gold_wealth_market_turnover_integrity_check`。
6. check 内部两阶段：`file_contract` 和 `recomputed_from_silver`。
7. 历史 backfill 必做，范围对齐 `silver_stk_mins` 历史范围。
8. 历史文件生成走 `Direct Lake Bootstrap + Runless Event Backfill`，不走 Dagster backfill 为全历史创建 run。
9. 历史 runless 状态只补最近 20 个交易日，不补全历史 materialization/check event。
10. 日更 sensor 默认 `STOPPED`，窗口为 `STOCK_MINS_SILVER_RUN_START + 10min = 20:00`，且必须等五个 silver 频度全 ready。
11. 部分频度 ready 时，全失败，不写部分结果。
12. 不新增 resource、数据库表、summary asset、readiness asset、status manifest 或配置项。
13. 不运行 `dg`、job、sensor、materialize、backfill 或正式 instance 命令，除非单独审批。

## 1. 目标文件清单

### 1.1 生产代码

| 文件 | 变更 |
| --- | --- |
| `lake_console/orchestrator/src/orchestrator/defs/run_contracts/asset_column_schemas.py` | 新增 `GOLD_WEALTH_MARKET_TURNOVER_SCHEMA` 和列名 tuple 派生使用点。 |
| `lake_console/orchestrator/src/orchestrator/defs/paths.py` | 新增 `gold_wealth_market_turnover_path(root, partition_key)`。 |
| `lake_console/orchestrator/src/orchestrator/defs/catalog/name_mapping.py` | 新增 `wealth_market_turnover -> 财富市场成交额快照`。 |
| `lake_console/orchestrator/src/orchestrator/defs/catalog/lake_assets.py` | 新增 check tuple、partition model、catalog entry。 |
| `lake_console/orchestrator/src/orchestrator/defs/wealth_market_turnover_contract.py` | 新增共享 SQL、写入 helper、文件契约 audit、silver 重算 audit；供 asset/check/readiness 复用，避免 active asset 与 check 互相 import。 |
| `lake_console/orchestrator/src/orchestrator/defs/assets/wealth_market_turnover.py` | 新增正式 asset，调用共享 SQL/writer/helper。 |
| `lake_console/orchestrator/src/orchestrator/defs/checks/wealth_market_turnover_checks.py` | 新增一个 blocking asset check，调用共享两阶段校验 helper。 |
| `lake_console/orchestrator/src/orchestrator/defs/asset_guards/wealth_market_turnover_lake_readiness.py` | 新增 sensor 热路径 gold readiness helper。 |
| `lake_console/orchestrator/src/orchestrator/defs/jobs/gold_wealth_market_turnover_update.py` | 新增 asset job。 |
| `lake_console/orchestrator/src/orchestrator/defs/sensors/gold_wealth_market_turnover_sensor.py` | 新增日更 sensor，默认停止。 |
| `lake_console/orchestrator/src/orchestrator/defs/bootstrap/wealth_market_turnover_history.py` | 新增 direct lake bootstrap 文件生成和聚合审计 helper。 |
| `lake_console/orchestrator/src/orchestrator/defs/bootstrap/wealth_market_turnover_history_cli.py` | 新增离线 CLI，默认 dry-run，apply 需显式参数。 |
| `lake_console/orchestrator/src/orchestrator/defs/bootstrap/wealth_market_turnover_runless_events.py` | 新增最近 20 日 runless event planning/report/audit helper。 |
| `lake_console/orchestrator/src/orchestrator/defs/bootstrap/wealth_market_turnover_runless_events_cli.py` | 新增 runless event CLI，默认 dry-run，apply 需显式参数。 |

说明：bootstrap/runless 文件可先进入 `defs/bootstrap/**`，但不得注册为 active asset/check/job/sensor。若后续项目要求历史工具退出 active source，需要按已有 static gates 口径删除或移出。

### 1.2 测试代码

| 文件 | 覆盖点 |
| --- | --- |
| `lake_console/orchestrator/tests/test_gold_wealth_market_turnover_asset.py` | asset 计算、JSON、单位转换、原子替换、缺源失败。 |
| `lake_console/orchestrator/tests/test_gold_wealth_market_turnover_checks.py` | 单 check 两阶段语义、metadata failure_stage。 |
| `lake_console/orchestrator/tests/test_gold_wealth_market_turnover_lake_readiness.py` | gold readiness helper 最近窗口、完整 integrity 语义、失败样本。 |
| `lake_console/orchestrator/tests/test_gold_wealth_market_turnover_sensor.py` | 默认停止、20:00 窗口、silver 全 ready、单 tick 1 run、cursor/run key。 |
| `lake_console/orchestrator/tests/test_gold_wealth_market_turnover_job.py` | job selection 只含本 asset 和一个 check。 |
| `lake_console/orchestrator/tests/test_wealth_market_turnover_history_bootstrap.py` | direct lake bootstrap dry-run/sample/full helper，不走 Python 行循环。 |
| `lake_console/orchestrator/tests/test_wealth_market_turnover_runless_events.py` | 最近 20 日 runless event plan、dry-run 不写、apply 绑定 materialization。 |
| `lake_console/orchestrator/tests/test_asset_governance_contracts.py` | catalog、metadata、schema、path、blocking check 对账。 |
| `lake_console/orchestrator/tests/test_run_contract_static_gates.py` | 禁止 `src.biz`/raw/prod/Tushare；禁止多个 check；禁止 Dagster backfill 全历史；禁止 `points_json VARCHAR`。 |
| `lake_console/orchestrator/tests/test_batch_readiness_hotpath_performance.py` | 新 gold readiness helper hot path 读取模型和调用次数。 |

## 2. 命名对账

| 类型 | 名称 | 规则依据 |
| --- | --- | --- |
| asset | `gold_wealth_market_turnover` | `layer + asset name`。 |
| check | `gold_wealth_market_turnover_integrity_check` | `asset name + function + check`，function 为 `integrity`，承载单一正式质量门禁。 |
| job | `gold_wealth_market_turnover_update_job` | `layer + asset name + mode + job`。 |
| sensor | `gold_wealth_market_turnover_update_job_sensor` | `job name + sensor`。 |
| readiness helper | `batch_gold_wealth_market_turnover_lake_readiness` | 真 batch，窗口级读取模型。 |
| path helper | `gold_wealth_market_turnover_path` | 稳定资产路径职责。 |
| schema | `GOLD_WEALTH_MARKET_TURNOVER_SCHEMA` | 稳定字段契约。 |
| bootstrap CLI | `wealth_market_turnover_history_cli` | 历史文件生成，不进入 daily path。 |
| runless CLI | `wealth_market_turnover_runless_events_cli` | 最近 20 日状态补录，不进入 daily path。 |

## 3. Schema 和字段契约

### 3.1 `GOLD_WEALTH_MARKET_TURNOVER_SCHEMA`

`GOLD_WEALTH_MARKET_TURNOVER_SCHEMA` 新增到 `asset_column_schemas.py`：

```python
GOLD_WEALTH_MARKET_TURNOVER_SCHEMA = (
    ColumnContract("type", "VARCHAR", "主体类型，首期固定 stock"),
    ColumnContract("market", "VARCHAR", "市场标识，首期固定 CN_A"),
    ColumnContract("trade_date", "DATE", "交易日"),
    ColumnContract("freq", "SMALLINT", "分钟周期，支持 1/5/15/30/60"),
    ColumnContract("build_status", "VARCHAR", "构建状态，Lake 文件只保存 READY"),
    ColumnContract("latest_trade_time", "TIMESTAMP", "该交易日该频度内最新分钟点"),
    ColumnContract("total_amount", "DECIMAL(20,2)", "全市场成交额，单位千元"),
    ColumnContract("total_vol", "BIGINT", "全市场成交量"),
    ColumnContract("security_count", "INTEGER", "参与统计证券数"),
    ColumnContract("source_row_count", "BIGINT", "参与汇总的 silver 行数"),
    ColumnContract("points_json", "JSON", "完整分钟点数组，按 trade_time 升序"),
    ColumnContract("build_version", "VARCHAR", "构建版本，首期固定 v1"),
    ColumnContract("built_at", "TIMESTAMP WITH TIME ZONE", "本次生成时间"),
    ColumnContract("build_note", "VARCHAR", "构建说明，正常为空"),
)
```

派生常量放在 `wealth_market_turnover_contract.py`，避免 `asset_column_schemas.py` 变成运行逻辑承载文件：

```python
GOLD_WEALTH_MARKET_TURNOVER_COLUMNS = tuple(
    column.name for column in GOLD_WEALTH_MARKET_TURNOVER_SCHEMA
)
GOLD_WEALTH_MARKET_TURNOVER_COLUMN_TYPES = {
    column.name: column.type.upper()
    for column in GOLD_WEALTH_MARKET_TURNOVER_SCHEMA
}
```

约束：

1. `points_json` 必须是 `JSON`。
2. 若 DuckDB `DESCRIBE` 无法稳定显示 `JSON`，实现必须停止并汇报，不得把 schema 改成 `VARCHAR`。
3. materialization metadata 只写 observed columns，不写 definition schema。

### 3.2 Path

新增到 `paths.py`：

```python
def gold_wealth_market_turnover_path(root: Path, partition_key: str) -> Path:
    return lake_path(
        root,
        GOLD,
        "wealth",
        "market_turnover",
        f"trade_date={partition_key}",
        "part-000.parquet",
    )
```

path template：

```python
lake_path_template(
    gold_wealth_market_turnover_path(
        PATH_TEMPLATE_LAKE_ROOT,
        PATH_TEMPLATE_PARTITION_KEY,
    )
)
```

禁止：

1. asset、check、catalog、bootstrap 中手写另一套正式路径。
2. 输出到 repo、home、`/tmp` 或 lake root 外。

## 4. Asset 低层设计

### 4.1 Asset definition

文件：`defs/assets/wealth_market_turnover.py`

签名：

```python
@dg.asset(
    name="gold_wealth_market_turnover",
    deps=[
        "silver_stk_mins_1m",
        "silver_stk_mins_5m",
        "silver_stk_mins_15m",
        "silver_stk_mins_30m",
        "silver_stk_mins_60m",
    ],
    partitions_def=cn_a_stock_mins_silver_trade_days,
    group_name="wealth",
    tags=build_asset_tags(
        layer=AssetLayer.GOLD,
        data_domain=DataDomain.DERIVED_METRIC,
    ),
    metadata=build_asset_definition_metadata(
        dataset_id="wealth_market_turnover",
        source_system=SourceSystem.DERIVED,
        data_contract="wealth_market_turnover_snapshot",
        path_template=...,
        column_schema=GOLD_WEALTH_MARKET_TURNOVER_SCHEMA,
        extra_metadata={
            "calculation_contract": (
                "source=silver_stk_mins; freqs=1/5/15/30/60; "
                "amount is converted from yuan to thousand_yuan; "
                "points_json stores full minute point array."
            ),
        },
    ),
    description="财富行情市场总览成交额分钟快照。",
)
def gold_wealth_market_turnover(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    ...
```

资源：

1. `LakeRootResource`
2. `DuckDBResource`

实现必须调用 `lake_root.ensure_available_for_run()`。

### 4.2 输入路径计划

新增 dataclass：

```python
@dataclass(frozen=True, slots=True)
class WealthMarketTurnoverInputPath:
    freq: int
    path: Path
```

函数：

```python
def wealth_market_turnover_input_paths(
    lake_root: Path,
    partition_key: str,
    freqs: Sequence[int] = STK_MINS_FREQS,
) -> tuple[WealthMarketTurnoverInputPath, ...]:
    ...
```

校验：

1. `freqs` 必须等于 `STK_MINS_FREQS`，默认 `(1, 5, 15, 30, 60)`。
2. 缺任一输入文件，抛 `FileNotFoundError`，不写目标。
3. 输入文件存在但行数为 0，抛 `ValueError`，不写目标。
4. 输入文件 `freq/trade_date` 不匹配，抛 `ValueError`，不写目标。
5. 输入文件有 `(ts_code, trade_time)` 重复，抛 `ValueError`，不写目标。

### 4.3 SQL 构造

新增：

```python
def wealth_market_turnover_select_sql(
    *,
    input_paths: Sequence[WealthMarketTurnoverInputPath],
    partition_key: str,
    built_at_sql: str = "current_timestamp",
) -> str:
    ...
```

SQL 结构：

```sql
WITH source_rows AS (
  SELECT
    CAST(ts_code AS VARCHAR) AS ts_code,
    CAST(freq AS SMALLINT) AS freq,
    CAST(trade_date AS DATE) AS trade_date,
    CAST(trade_time AS TIMESTAMP) AS trade_time,
    CAST(vol AS DOUBLE) AS vol,
    CAST(amount AS DOUBLE) AS amount
  FROM read_parquet('<silver-1m>', hive_partitioning=false)
  UNION ALL
  ...
),
point_rows AS (
  SELECT
    freq,
    trade_date,
    trade_time,
    round(sum(amount) / 1000, 2) AS amount,
    CAST(sum(vol) AS BIGINT) AS vol,
    CAST(count(DISTINCT ts_code) AS INTEGER) AS security_count
  FROM source_rows
  GROUP BY freq, trade_date, trade_time
),
point_json AS (
  SELECT
    freq,
    trade_date,
    to_json(
      list(
        struct_pack(
          tradeTime := strftime(trade_time, '%H:%M'),
          tradeTimeTs := strftime(trade_time, '%Y-%m-%d %H:%M:%S'),
          amount := amount,
          vol := vol,
          securityCount := security_count
        )
        ORDER BY trade_time
      )
    )::JSON AS points_json
  FROM point_rows
  GROUP BY freq, trade_date
),
summary AS (
  SELECT
    CAST('stock' AS VARCHAR) AS type,
    CAST('CN_A' AS VARCHAR) AS market,
    trade_date,
    CAST(freq AS SMALLINT) AS freq,
    CAST('READY' AS VARCHAR) AS build_status,
    max(trade_time) AS latest_trade_time,
    CAST(round(sum(amount) / 1000, 2) AS DECIMAL(20,2)) AS total_amount,
    CAST(sum(vol) AS BIGINT) AS total_vol,
    CAST(count(DISTINCT ts_code) AS INTEGER) AS security_count,
    CAST(count(*) AS BIGINT) AS source_row_count,
    CAST('v1' AS VARCHAR) AS build_version,
    CAST({built_at_sql} AS TIMESTAMP WITH TIME ZONE) AS built_at,
    CAST(NULL AS VARCHAR) AS build_note
  FROM source_rows
  GROUP BY trade_date, freq
)
SELECT
  summary.type,
  summary.market,
  summary.trade_date,
  summary.freq,
  summary.build_status,
  summary.latest_trade_time,
  summary.total_amount,
  summary.total_vol,
  summary.security_count,
  summary.source_row_count,
  point_json.points_json,
  summary.build_version,
  summary.built_at,
  summary.build_note
FROM summary
JOIN point_json USING (trade_date, freq)
WHERE summary.trade_date = DATE '<partition_key>'
ORDER BY summary.freq
```

注意：

1. `read_parquet(...)` 必须用 `hive_partitioning=false`。
2. SQL 必须显式字段投影。
3. 输出顺序必须与 `GOLD_WEALTH_MARKET_TURNOVER_SCHEMA` 一致。
4. `ORDER BY freq` 固定输出顺序。
5. `built_at_sql` 只用于测试注入稳定时间；生产默认 `current_timestamp`。

### 4.4 写入 helper

新增：

```python
def write_gold_wealth_market_turnover_partition(
    *,
    connection,
    input_paths: Sequence[WealthMarketTurnoverInputPath],
    partition_key: str,
    target_path: Path,
) -> WealthMarketTurnoverWriteAudit:
    ...
```

流程：

1. 生成 select SQL。
2. 写到 `target_path.with_name("part-000.parquet.tmp")`。
3. 对 tmp 文件运行 `audit_gold_wealth_market_turnover_file(...)`。
4. 对 tmp 文件运行 `audit_gold_wealth_market_turnover_recomputed_from_silver(...)`。
5. 两阶段 audit 全部通过后 `os.replace(tmp_path, target_path)`。
6. 替换后读取正式文件 columns、row count、summary metadata。
7. 返回 `WealthMarketTurnoverWriteAudit`。

失败处理：

1. tmp 写入失败，删除 tmp。
2. audit 失败，删除 tmp，保留正式文件。
3. 不写部分频度结果。

### 4.5 Materialization metadata

`MaterializeResult` metadata：

```python
build_materialization_metadata(
    uri=target_path,
    row_count=5,
    observed_columns=observed_columns,
    extra_metadata={
        "partition_key": partition_key,
        "input_file_paths": [str(path.path) for path in input_paths],
        "freqs": [1, 5, 15, 30, 60],
        "build_version": "v1",
        "source_row_count": audit.source_row_count,
        "total_amount": str(audit.total_amount),
        "total_vol": audit.total_vol,
        "security_count_by_freq": audit.security_count_by_freq,
        "latest_trade_time_by_freq": audit.latest_trade_time_by_freq,
    },
)
```

禁止：

1. metadata 里写完整 `points_json`。
2. metadata 里写全量失败行。
3. metadata 使用未命名空间裸 key，除非已有 helper 会统一加 `goldenshare/` 前缀。

## 5. Check 低层设计

### 5.1 公共 audit dataclass

文件：`defs/checks/wealth_market_turnover_checks.py`

新增：

```python
@dataclass(frozen=True, slots=True)
class WealthMarketTurnoverIntegrityAudit:
    passed: bool
    failure_stage: str | None
    reason_code: str | None
    checked_row_count: int
    failed_row_count: int
    missing_file_paths: tuple[str, ...]
    sample_rows: tuple[dict[str, object], ...]
    metadata: dict[str, object]
```

`failure_stage` 只允许：

1. `file_contract`
2. `recomputed_from_silver`
3. `None`

### 5.2 文件契约阶段

函数：

```python
def audit_gold_wealth_market_turnover_file_contract(
    *,
    connection,
    target_path: Path,
    partition_key: str,
) -> WealthMarketTurnoverIntegrityAudit:
    ...
```

检查项：

1. 文件存在。
2. `DESCRIBE` schema 等于 `GOLD_WEALTH_MARKET_TURNOVER_SCHEMA`。
3. 行数恰好 5。
4. `(type, market, trade_date, freq)` 唯一。
5. `type='stock'`。
6. `market='CN_A'`。
7. `trade_date=partition_key`。
8. `freq` 集合恰好 `{1,5,15,30,60}`。
9. `build_status='READY'`。
10. 非空字段不为空。
11. `points_json` 类型为 `JSON`，能解析为数组。
12. 每个 `points_json` 数组非空。
13. `points_json` 内 `tradeTimeTs` 按升序排列。

失败时 metadata：

```python
{
    "failure_stage": "file_contract",
    "reason_code": "...",
    "file_path": str(target_path),
    "partition_key": partition_key,
    "failed_row_count": ...,
    "sample_rows": [...],
}
```

### 5.3 Silver 重算阶段

函数：

```python
def audit_gold_wealth_market_turnover_recomputed_from_silver(
    *,
    connection,
    target_path: Path,
    input_paths: Sequence[WealthMarketTurnoverInputPath],
    partition_key: str,
) -> WealthMarketTurnoverIntegrityAudit:
    ...
```

重算 SQL：

1. 使用同一份 `wealth_market_turnover_select_sql(...)`，但 `built_at` 和 `build_note` 不参与比较。
2. summary 比较字段：
   - `type`
   - `market`
   - `trade_date`
   - `freq`
   - `build_status`
   - `latest_trade_time`
   - `total_amount`
   - `total_vol`
   - `security_count`
   - `source_row_count`
   - `build_version`
3. `points_json` 比较字段：
   - 数组长度。
   - 每个 point 的 `tradeTime`。
   - 每个 point 的 `tradeTimeTs`。
   - 每个 point 的 `amount`。
   - 每个 point 的 `vol`。
   - 每个 point 的 `securityCount`。

失败时 metadata：

```python
{
    "failure_stage": "recomputed_from_silver",
    "reason_code": "...",
    "gold_file_path": str(target_path),
    "input_file_paths": [...],
    "partition_key": partition_key,
    "mismatch_count": ...,
    "sample_rows": [...],
}
```

### 5.4 暴露一个 asset check

```python
@dg.asset_check(
    asset=gold_wealth_market_turnover,
    blocking=True,
)
def gold_wealth_market_turnover_integrity_check(
    context: dg.AssetCheckExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.AssetCheckResult:
    ...
```

执行顺序：

1. 构造 target path 和五个 silver input paths。
2. 文件契约阶段失败则直接返回 failed。
3. 文件契约阶段通过后执行 silver 重算阶段。
4. 两阶段都通过才返回 passed。

`AssetCheckResult.metadata` 使用 `build_check_metadata(...)`，并通过 `extra_metadata` 附加 `failure_stage`、`reason_code`、样本和统计。

## 6. Readiness 低层设计

文件：`defs/asset_guards/wealth_market_turnover_lake_readiness.py`

### 6.1 数据结构

```python
@dataclass(frozen=True)
class WealthMarketTurnoverDateReadiness:
    trade_date: str
    ready: bool
    materialized: bool
    checks_passed: bool
    reason: str
    failed_check_names: tuple[str, ...]
    missing_file_paths: tuple[str, ...]
    checked_row_count: int = 0
    failed_row_count: int = 0
    sample_rows: tuple[dict[str, object], ...] = ()

    def to_cursor_details(self) -> dict[str, object]:
        ...
```

```python
@dataclass(frozen=True)
class WealthMarketTurnoverBatchReadiness:
    dataset: str
    expected_start_date: str | None
    expected_end_date: str | None
    expected_count: int
    elapsed_ms: float
    statuses_by_trade_date: Mapping[str, WealthMarketTurnoverDateReadiness]

    def status_for_trade_date(self, trade_date: str) -> WealthMarketTurnoverDateReadiness:
        ...
```

### 6.2 Batch helper

```python
def batch_gold_wealth_market_turnover_lake_readiness(
    *,
    connection,
    lake_root: Path,
    expected_trade_dates: Sequence[str],
) -> WealthMarketTurnoverBatchReadiness:
    ...
```

读取模型：

1. 输入最多 `STK_MINS_CONTINUITY_WINDOW_LIMIT` 个 expected dates，由 sensor 限制。
2. 一次性规划目标 gold paths 和五频度 silver paths。
3. 对存在的 gold path 先做 schema/row/key/date/freq 粗筛。
4. 对通过粗筛的 gold path 执行完整 integrity 语义：`file_contract` + `recomputed_from_silver`。
5. 不读 Dagster instance。
6. 不允许逐日期、逐频度重复执行重 SQL；必须把窗口内 gold/silver paths 聚合规划后批量执行。

说明：

1. 日常 sensor 的上游正确性来自 `batch_silver_stk_mins_lake_readiness(... full_semantics=True)`。
2. gold readiness 必须复刻 `gold_wealth_market_turnover_integrity_check` 的完整语义，不能只看文件存在、row count 或 file contract。
3. helper 不读 Dagster event history；`checks_passed` 表示 lake 文件事实按正式 check 语义重新计算后通过。
4. 性能测试必须证明 10 日窗口读取模型可接受；如果 10 日窗口完整重算超预算，停止重新设计，不能降级 ready 语义。

## 7. Job 低层设计

文件：`defs/jobs/gold_wealth_market_turnover_update.py`

```python
gold_wealth_market_turnover_update_job = dg.define_asset_job(
    name="gold_wealth_market_turnover_update_job",
    selection=(
        dg.AssetSelection.assets(gold_wealth_market_turnover)
        | dg.AssetSelection.checks_for_assets(gold_wealth_market_turnover)
    ),
    executor_def=dg.in_process_executor,
    description="按单日分区生成财富市场成交额 gold 快照。",
)
```

禁止：

1. job 文件里写 SQL。
2. job 文件里写路径拼接。
3. job selection 纳入 silver 上游。
4. job selection 纳入 bootstrap/runless 工具。

## 8. Sensor 低层设计

文件：`defs/sensors/gold_wealth_market_turnover_sensor.py`

### 8.1 常量

```python
GOLD_WEALTH_MARKET_TURNOVER_SENSOR_JOB_NAME = "gold_wealth_market_turnover_update_job"
GOLD_WEALTH_MARKET_TURNOVER_RUN_START = (
    datetime.combine(date.today(), STOCK_MINS_SILVER_RUN_START)
    + timedelta(minutes=10)
).time()
```

当前推导值为 `20:00`。

### 8.2 Sensor definition

```python
@dg.sensor(
    job_name=GOLD_WEALTH_MARKET_TURNOVER_SENSOR_JOB_NAME,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb"},
    tags=build_sensor_tags(
        sensor_domain=SensorDomain.DERIVED_METRIC,
        target_layer=SensorTargetLayer.GOLD,
        role=SensorRole.ASSET_UPDATE,
    ),
    description="股票分钟线 silver 五频度 ready 后，触发财富市场成交额 gold 快照。",
)
def gold_wealth_market_turnover_update_job_sensor(
    context: dg.SensorEvaluationContext,
) -> dg.SensorResult:
    ...
```

### 8.3 执行顺序

1. `evaluated_at = datetime.now(CN_A_SENSOR_TIMEZONE)`。
2. 判断 `evaluated_at.time() >= GOLD_WEALTH_MARKET_TURNOVER_RUN_START`。
3. 窗口未到，轻量 skip，不执行 DuckDB readiness。
4. 窗口已到，读取 expected trade date window。
5. expected window 最多 `STK_MINS_CONTINUITY_WINDOW_LIMIT` 个交易日。
6. 读取 `cn_a_stock_mins_silver_trade_days` dynamic partitions。
7. 若 expected window 与 registered partitions 有缺口，skip。
8. 调用 `batch_silver_stk_mins_lake_readiness(..., freqs=STK_MINS_FREQS, full_semantics=True)`。
9. 若目标日任一 silver freq 未 ready，skip，且不继续扫描 gold readiness。
10. 调用 `batch_gold_wealth_market_turnover_lake_readiness(...)`。
11. 选择最早一个 gold not ready 且 silver ready 的 trade date。
12. 若目标 gold 有 failed check 或状态不一致，skip，等待人工处理。
13. 生成一个 RunRequest。

### 8.4 RunRequest

```python
run_request = build_run_request(
    run_key=build_asset_update_run_key(
        subject="gold_wealth_market_turnover",
        unit_id=selected_trade_date,
    ),
    partition_key=selected_trade_date,
)
```

禁止：

1. 手写 `run_key=f"..."`。
2. 解析 run key 生成参数。
3. 每 tick 多个 `RunRequest`。
4. cursor 中存全窗口文件路径或全量状态。

### 8.5 Cursor

cursor 通过 `build_sensor_cursor(...)`：

```python
build_sensor_cursor(
    evaluated_at=evaluated_at,
    decision=SensorCursorDecision.REQUEST_RUNS or SensorCursorDecision.SKIP,
    target_date=target_trade_date,
    selected_count=1 if selected_trade_date else 0,
    blocked_count=...,
    sample_keys=[selected_trade_date] if selected_trade_date else [],
    details={
        "partition_set": cn_a_stock_mins_silver_trade_days.name,
        "run_window_started": run_window_started,
        "selected_trade_date": selected_trade_date,
        "reason_code": reason_code,
        "silver_status": silver_status.to_cursor_details(),
        "gold_status": gold_status.to_cursor_details(),
    },
)
```

`reason_code` 必须是 ASCII。

## 9. Catalog 低层设计

### 9.1 Partition model

新增 enum：

```python
TRADE_DATE_PARTITION_GOLD_WEALTH_MARKET_TURNOVER = (
    "trade_date_partition_gold_wealth_market_turnover"
)
```

新增 model：

```python
_model(
    PartitionModel.TRADE_DATE_PARTITION_GOLD_WEALTH_MARKET_TURNOVER,
    PartitionModelFamily.TRADE_DATE_PARTITION,
    AssetLayer.GOLD,
    "wealth_market_turnover",
    "trade_date",
    PartitionPhysicalLayout.PARTITION_FILE,
)
```

### 9.2 Check tuple

```python
GOLD_WEALTH_MARKET_TURNOVER_CHECKS = (
    "gold_wealth_market_turnover_integrity_check",
)
```

### 9.3 Catalog entry

```python
_entry(
    asset_key="gold_wealth_market_turnover",
    dataset_id="wealth_market_turnover",
    layer=AssetLayer.GOLD,
    data_domain=DataDomain.DERIVED_METRIC,
    group_name="wealth",
    source_system=SourceSystem.DERIVED,
    data_contract="wealth_market_turnover_snapshot",
    data_contract_source=DataContractSource.DERIVED_CONTRACT,
    column_schema=GOLD_WEALTH_MARKET_TURNOVER_SCHEMA,
    path_template=lake_path_template(
        gold_wealth_market_turnover_path(
            PATH_TEMPLATE_LAKE_ROOT,
            PATH_TEMPLATE_PARTITION_KEY,
        )
    ),
    partition_model=PartitionModel.TRADE_DATE_PARTITION_GOLD_WEALTH_MARKET_TURNOVER,
    source_api=None,
    source_doc="wealth/docs/pages/market-overview/turnover-minute-snapshot-plan-v1.html",
    ingestion_sources=(IngestionSource.DERIVED_FROM_ASSETS,),
    default_daily_ingestion_source=IngestionSource.DERIVED_FROM_ASSETS,
    bootstrap_sources=(),
    blocking_check_names=GOLD_WEALTH_MARKET_TURNOVER_CHECKS,
    write_policy=WritePolicy.PARTITION_FILE_ATOMIC_REPLACE,
    event_policy=EventPolicy.DAGSTER_RUN_ONLY,
    performance_contract=_perf(
        batch_grain="one trade_date partition, five stk_mins frequencies",
        compute_engine=ComputeEngine.DUCKDB_SQL,
        source_request_policy="read local silver stk_mins parquet files only",
    ),
)
```

## 10. 历史 Direct Lake Bootstrap LLD

### 10.1 文件生成 CLI

文件：`defs/bootstrap/wealth_market_turnover_history_cli.py`

命令阶段：

1. `profile-history`
2. `write-sample`
3. `audit-sample`
4. `write-full`
5. `audit-full`

默认只读；写 lake 必须显式 `--apply`。

输出报告路径：

```text
/private/tmp/wealth_market_turnover_history_<stage>_<timestamp>.json
```

### 10.2 Source selection

历史范围：

1. 起点：`STK_MINS_SILVER_HISTORY_START_DATE`，当前 `2014-01-01`。
2. 终点：执行时 `silver_stk_mins` 五频度均存在且通过输入契约的最新交易日。
3. 候选日期来自 `cn_a_stock_mins_silver_trade_days` 和 silver 文件事实交集。

缺任一频度的交易日：

1. 不写 gold。
2. 报告中记录 `missing_freqs` 和 path。
3. 不报绿色 runless event。

### 10.3 批量写入模型

推荐批次：

1. 按年批处理。
2. 年内按交易日输出 `trade_date=<YYYY-MM-DD>/part-000.parquet`。
3. Python 只负责发现路径、分批、调用 SQL、汇总报告。
4. 每个交易日仍使用正式 `write_gold_wealth_market_turnover_partition(...)` 或等价 set-based batch SQL。

性能预算：

| 项 | 上限/口径 |
| --- | --- |
| 输入文件 | 每个交易日 5 个 silver parquet |
| 输出文件 | 每个成功交易日 1 个 gold parquet |
| 输出行数 | 每个成功交易日 5 行 |
| Python 行循环 | 禁止处理分钟线行；允许循环日期/批次 |
| 写入粒度 | 分区文件原子替换 |
| 失败策略 | 任一分区失败，记录并按阶段策略停止或跳过；不得写部分频度 |

### 10.4 Full audit

最终报告必须包含：

1. selected_trade_date_count
2. written_partition_count
3. skipped_partition_count
4. skipped reason counts
5. target_file_count
6. target_row_count
7. target_date_min/max
8. duplicate key count
9. null key count
10. schema mismatch count
11. integrity check failure count
12. sample rows

`audit-full` 不读 Dagster DB，只审计 lake 文件事实。

## 11. 最近 20 日 Runless Event LLD

### 11.1 CLI 阶段

文件：`defs/bootstrap/wealth_market_turnover_runless_events_cli.py`

阶段：

1. `plan-events`
2. `report-sample-events`
3. `audit-sample-events`
4. `report-recent-window-events`
5. `audit-recent-window-events`

默认 dry-run；正式写入必须显式 `--apply`。

### 11.2 窗口

1. 从已通过 full audit 的 gold 文件集合中取最新 20 个交易日。
2. 不使用 sensor 10 日窗口。
3. 少于 20 个成功分区时停止，等待人工确认。
4. 若窗口内任一文件未通过 `gold_wealth_market_turnover_integrity_check` 内部两阶段校验，不写事件。

### 11.3 写入事件

每个分区最多 2 条 event：

1. `AssetMaterialization(asset_key="gold_wealth_market_turnover", partition=trade_date)`
2. `AssetCheckEvaluation(check_name="gold_wealth_market_turnover_integrity_check", passed=True, partition=trade_date)`

materialization 后必须读取最新 materialization storage id，并用 `AssetCheckEvaluationTargetMaterializationData` 绑定 check event。

20 个交易日上限：

```text
20 materialization + 20 check = 40 events
```

metadata：

```python
{
    "source_method": "wealth_market_turnover_history_bootstrap",
    "bootstrap_event_backfill": True,
    "event_backfill_scope": "recent_20_trade_days",
    "history_audit_report_path": "...",
    "partition_key": trade_date,
    "freqs": [1, 5, 15, 30, 60],
}
```

禁止：

1. 为全历史补 event。
2. 报告 failed check 作为绿色状态。
3. 写旧 serving、旧 raw 或其它 asset。
4. 直接 SQL 改 Dagster DB。

### 11.4 性能预算和拒绝策略

| 入口 | 读取模型 | 写入模型 | 必须测量 | 拒绝策略 |
| --- | --- | --- | --- | --- |
| 日常 asset | 1 个交易日 × 5 个 silver parquet；显式投影 `ts_code/freq/trade_date/trade_time/vol/amount` | 1 个 gold parquet，5 行 | 输入总行数、输出行数、DuckDB 耗时、tmp 文件大小 | 任一频度缺失、为空、key/date/freq 错、JSON 不稳定、写后 audit 失败则不替换正式文件 |
| 日常 check | 1 个 gold parquet + 5 个 silver parquet；两阶段完整 integrity | 0 | check 耗时、mismatch_count、failure_stage | 任一阶段失败即 failed check |
| 日常 sensor | 最近 10 个 expected dates；最多 10 个 gold + 50 个 silver 文件事实；不读 Dagster event history | 0 或 1 个 RunRequest | tick 耗时、文件数、SQL 次数、cursor 大小 | 超预算、窗口未到、silver 未全 ready、gold failed 时 skip |
| 历史 bootstrap dry-run | `2014-01-01` 起，注册分区与五频度 silver 文件事实交集 | 0 | 候选日期数、缺频度日期数、预估输出文件数、预估行数、目标冲突、磁盘空间 | 候选集合不清、目标冲突不可解释、缺频度比例异常、磁盘不足则停止 |
| 历史 bootstrap full | 按年或更小批次读 silver；每个成功交易日 5 个输入文件 | 每个成功交易日 1 个 gold parquet | 每批输入文件数、输出文件数、总行数、失败原因样本、耗时 | 任一批次 audit 不通过时停止，不进入 runless event |
| 最近 20 日 runless | 只读最近 20 个已通过 full audit 的 gold 文件和必要 Dagster materialization/check 事实 | 最多 40 条 event | 计划分区数、已有 ready 数、待写 event 数、sample audit | 窗口不是 20 个交易日、任一文件未通过 integrity、event 数超过 40 则停止 |

性能门槛：

1. 日常 sensor hot path 目标 p95 小于 10 秒；若完整 integrity readiness 超过预算，必须优化 batch SQL，不得降级 ready 语义。
2. 历史 bootstrap 必须先 dry-run，再 sample，再 full/batched，再 final audit。
3. 历史 runless event 必须先 dry-run，再 sample apply，再 recent-window apply。
4. 任何 full 阶段前都必须输出 `/private/tmp/wealth_market_turnover_*` 报告。

## 12. 测试和静态门禁

### 12.1 单元测试命令

建议：

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator
uv run python -m unittest \
  tests.test_gold_wealth_market_turnover_asset \
  tests.test_gold_wealth_market_turnover_checks \
  tests.test_gold_wealth_market_turnover_lake_readiness \
  tests.test_gold_wealth_market_turnover_sensor \
  tests.test_gold_wealth_market_turnover_job \
  tests.test_wealth_market_turnover_history_bootstrap \
  tests.test_wealth_market_turnover_runless_events \
  tests.test_asset_governance_contracts \
  tests.test_run_contract_static_gates \
  tests.test_batch_readiness_hotpath_performance
git diff --check
```

`dg check defs` 只在单独审批后运行。

### 12.2 静态门禁

`test_run_contract_static_gates.py` 新增：

1. `gold_wealth_market_turnover` 生产代码不得 import `src.biz`。
2. 生产代码不得 import `WealthMarketTurnoverSnapshot` 或 SQLAlchemy model。
3. 生产代码不得 import Tushare resource、prod DB resource、raw stk mins path。
4. check 名称只能有 `gold_wealth_market_turnover_integrity_check` 一个。
5. `points_json` schema 必须是 `JSON`。
6. sensor 必须默认 `STOPPED`。
7. sensor run key 必须使用 `build_asset_update_run_key(...)`。
8. sensor cursor 必须使用 `build_sensor_cursor(...)`。
9. job selection 不得包含 silver 上游。
10. 历史 bootstrap 代码不得调用 Dagster backfill。
11. runless event 只允许最近 20 个交易日。
12. bootstrap/runless CLI 默认 dry-run，apply 必须显式参数。

### 12.3 性能测试

`test_batch_readiness_hotpath_performance.py` 新增：

1. 10 日窗口内 `batch_gold_wealth_market_turnover_lake_readiness(...)` 不访问 Dagster instance。
2. helper 不对每日期重复扫描 silver 五频度文件，必须使用窗口级路径规划和批量 SQL。
3. helper 文件读取上限为窗口目标 gold 文件数 + 窗口日期数 × 5 个 silver 文件，不读全历史。
4. cursor sample keys 不超过 `MAX_CURSOR_SAMPLE_KEYS`。

## 13. 开发分片

当前代码事实：`tests/test_asset_governance_contracts.py` 要求 active catalog、active asset definition、blocking check specs 三者同步对账。如果只落 WMT-1 catalog entry 而不落 active asset/check，治理测试会必然失败。因此实际执行时将 WMT-1/WMT-2/WMT-3 合并为第一个可验证闭环；这不是扩大需求，而是为了遵守 registry-first 治理门禁。

### WMT-1 Contract / Path / Catalog

状态：已完成。

改动：

1. `asset_column_schemas.py`
2. `paths.py`
3. `name_mapping.py`
4. `lake_assets.py`
5. governance tests

验收：

1. catalog entry 存在。
2. path template 与 path helper 一致。
3. schema 列名/类型/描述完整。
4. active catalog 数量 +1。

### WMT-2 Asset / SQL / Writer

状态：已完成。

改动：

1. `assets/wealth_market_turnover.py`
2. `wealth_market_turnover_contract.py`
3. asset tests

验收：

1. 正常样本输出 5 行。
2. `amount / 1000` 正确。
3. `points_json` 是 JSON，完整、升序。
4. 缺频度、空文件、重复 key、日期/freq 不匹配失败。
5. 失败不污染正式文件。

### WMT-3 Check / Readiness

状态：已完成。

改动：

1. `checks/wealth_market_turnover_checks.py`
2. `asset_guards/wealth_market_turnover_lake_readiness.py`
3. check/readiness tests

验收：

1. 只暴露一个 blocking check。
2. `failure_stage` 正确。
3. 文件契约和 silver 重算对账均覆盖。
4. readiness helper 保持 hot path 有界。

### WMT-4 Job / Sensor

状态：已完成。

改动：

1. `jobs/gold_wealth_market_turnover_update.py`
2. `sensors/gold_wealth_market_turnover_sensor.py`
3. job/sensor tests

验收：

1. job selection 正确。
2. sensor 默认 STOPPED。
3. 20:00 前轻量 skip。
4. silver 五频度未全 ready 时 skip，且不扫描 gold readiness。
5. 每 tick 最多一个 run。

### WMT-5 History Bootstrap / Runless Events

状态：未实现。

改动：

1. `bootstrap/wealth_market_turnover_history.py`
2. `bootstrap/wealth_market_turnover_history_cli.py`
3. `bootstrap/wealth_market_turnover_runless_events.py`
4. `bootstrap/wealth_market_turnover_runless_events_cli.py`
5. bootstrap/runless tests

验收：

1. 历史文件生成 dry-run/sample/full/audit 分阶段。
2. 不通过 Dagster backfill 创建全历史 runs。
3. runless event 只补最近 20 个交易日。
4. 最大事件数 40。
5. check event 绑定对应 materialization。

## 14. 停止条件

开发中遇到以下情况必须停止，不继续编码：

1. DuckDB/Parquet 无法稳定写出或校验 `points_json JSON`。
2. `silver_stk_mins` 五频度历史范围不一致，无法定义 backfill 终点。
3. 正式 asset/check helper 无法同时被 daily path 和 bootstrap path 复用。
4. 需要新增配置项、resource、数据库表、summary asset 或 status manifest。
5. 需要修改 Wealth API 或 `core_serving.wealth_market_turnover_snapshot`。
6. 需要读取 prod DB、Tushare 或 raw DB 才能完成 gold 计算。
7. sensor hot path 需要深扫 Dagster event history 或全历史 lake 文件。
8. 历史 runless event 计划超过最近 20 个交易日或 40 条 event。

## 15. 完成定义

代码完成后，必须满足：

1. `gold_wealth_market_turnover` active definition 可加载。
2. `gold_wealth_market_turnover_update_job` 和 `gold_wealth_market_turnover_update_job_sensor` 可加载，sensor 默认停止。
3. asset、catalog、schema、path、metadata、check 名称一致。
4. 单分区样本 materialize 输出 5 行 JSON parquet。
5. 一个 blocking check 全绿。
6. 历史 direct lake bootstrap dry-run 和 sample audit 可执行。
7. 最近 20 日 runless event dry-run 可输出 40 条以内计划。
8. 单元测试和静态门禁通过。
9. 未运行正式 Dagster instance 命令，除非有单独审批记录。
