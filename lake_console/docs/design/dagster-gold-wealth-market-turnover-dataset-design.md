# Dagster Gold Wealth Market Turnover Dataset Design

状态：代码开发闭环已落地。WMT-1/WMT-2/WMT-3/WMT-4/WMT-5 已完成，包含 schema/path/catalog、正式 asset/writer、单一 blocking check、lake readiness helper、专用 job、默认停止的 sensor、历史 direct lake bootstrap 工具和最近 20 日 runless event 工具。已审批执行 `dg check defs` 并通过。尚未执行正式历史 lake 写入、正式 runless event apply 或 sensor 启用。

## 1. 目标

新增 Dagster 数据湖资产 `gold_wealth_market_turnover`，按交易日分区，从新湖 `silver_stk_mins` 计算财富行情市场总览使用的成交额分钟快照。

本轮设计口径：

1. 资产名：`gold_wealth_market_turnover`。
2. 数据层级：`gold`。这是服务型结果数据，但在 lake 内属于从 silver 派生的 gold 资产。
3. 分区：按交易日分区，复用 `cn_a_stock_mins_silver_trade_days`。
4. 数据源：只读 `silver/quote/stk_mins/freq=<freq>/trade_date=<YYYY-MM-DD>/part-000.parquet`。
5. 频度：首期固定 `1/5/15/30/60`，与现有 `TURNOVER_SNAPSHOT_ALLOWED_FREQS` 和 `STK_MINS_FREQS` 对齐。
6. 输出路径：`gold/wealth/market_turnover/trade_date=<YYYY-MM-DD>/part-000.parquet`。
7. 输出字段：对齐当前 `core_serving.wealth_market_turnover_snapshot` 的业务 schema。
8. 计算方式：按 `trade_date + freq` 聚合全市场分钟成交额、成交量和证券数，`amount` 从元转换为千元。
9. 调度：新增专用 job 和 sensor；sensor 默认 `STOPPED`，只在上游 silver 五个频度全 ready 后触发单日分区。

不做：

1. 不修改现有 Wealth API 查询逻辑。
2. 不写 prod DB / core_serving。
3. 不从 Tushare 或旧 raw 表计算。
4. 不把 `src/biz/services/.../TurnoverSnapshotMaterializeService` 直接复用到 orchestrator。
5. 不新增 resource。
6. 不新增配置项。
7. 不在资产代码实现阶段直接执行历史 backfill 或 runless event 补录；历史 backfill 必做，但作为上线前单独执行步骤审批和验收。

已拍板结论：

1. `points_json` 在 Parquet 里必须使用 `JSON` 逻辑类型。
2. 历史 backfill 必做，历史范围对齐 `silver_stk_mins` 的历史范围。
3. 暂不把 gold lake 结果同步回 `core_serving.wealth_market_turnover_snapshot`，后续另议。
4. 日更启动时间为 `silver_stk_mins` 日更时间 + 10 分钟；当前代码中 `STOCK_MINS_SILVER_RUN_START = 19:50`，因此本资产日更窗口为 `20:00`。
5. 即使到了 `20:00`，也必须等当日五个 silver 频度全部 ready 才触发。
6. 如果某天只有部分 silver 频度 ready，则本资产全失败，不允许写入部分频度结果，由上游先处理错误。

## 2. 审计依据

### 2.1 已读规范和方案

| 文件 | 结论 |
| --- | --- |
| `/Users/congming/github/goldenshare/AGENTS.md` | 新增数据集必须审计当前代码、明确时间输入语义、执行 unit 语义和 freshness/audit 语义；不得猜测式编码。 |
| `/Users/congming/github/goldenshare/lake_console/AGENTS.md` | `lake_console` 新增资产必须走数据湖/Dagster 现有约束，不绕开 catalog、checks、job/sensor 约定。 |
| `/Users/congming/github/goldenshare/lake_console/orchestrator/AGENTS.md` | orchestrator 变更必须遵守 asset/check/job/sensor 和 run contract 本地规范。 |
| `/Users/congming/github/goldenshare/lake_console/orchestrator/CODING_STANDARDS.md` | 资产、job、sensor、run request、cursor、metadata、path helper 需要使用统一 helper 和命名。 |
| `/Users/congming/github/goldenshare/lake_console/docs/design/dagster-asset-schema-contract-design.md` | 新资产 schema 必须进入 `asset_column_schemas.py`，definition metadata、catalog、checks 使用同一份契约。 |
| `/Users/congming/github/goldenshare/lake_console/docs/design/dagster-data-pipeline-performance-governance.md` | 传感器热路径要有读取上限，计算用 DuckDB set-based SQL，禁止 Python 逐行写。 |
| `/Users/congming/github/goldenshare/lake_console/docs/templates/dagster-dataset-onboarding-template.html` | 新数据集必须先登记路径、schema、catalog、checks、job、sensor、性能门禁。 |
| `/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/turnover-minute-snapshot-plan-v1.html` | `core_serving.wealth_market_turnover_snapshot` 是财富行情成交额总览服务表；`points_json` 存完整分钟点数组，`amount` 单位为千元。 |

### 2.2 CodeGraph 和代码审计

| 审计点 | 当前代码事实 | 对本方案的影响 |
| --- | --- | --- |
| `WealthMarketTurnoverSnapshot` | `/Users/congming/github/goldenshare/src/foundation/models/core_serving/wealth_market_turnover_snapshot.py` 定义 `core_serving.wealth_market_turnover_snapshot`，主键为 `type, market, trade_date, freq`，`total_vol` 是 `BigInteger`。 | gold lake schema 必须包含同一组业务字段和主键语义。 |
| 旧构建服务 | `/Users/congming/github/goldenshare/src/biz/services/wealth/market/turnover/turnover_snapshot_materialize_service.py` 使用 `RawStkMins`，频度为 `1/5/15/30/60`，`amount / 1000` 后写入 snapshot。 | 新 DG 不能复用旧 raw DB 服务，但计算口径要继承。 |
| 单位测试 | `/Users/congming/github/goldenshare/tests/test_turnover_snapshot_materialize_service.py` 明确 raw minute amount 是元，snapshot 存千元。 | 资产和 checks 必须测试金额单位转换。 |
| 页面查询 | `/Users/congming/github/goldenshare/src/biz/queries/wealth/market/turnover/turnover_query.py` 当前只读取 `freq=30` 且 `build_status=READY` 的 serving 快照，累计值由查询层计算。 | DG 资产仍生成五个频度；不能把输出缩成页面固定 5 个展示点。 |
| 状态查询 | `/Users/congming/github/goldenshare/src/biz/queries/wealth/market/turnover/turnover_state_query.py` 以 `freq=30` 的 READY snapshot 判断 intraday source date。 | 后续若切 API source，要另起 serving/API 方案；本轮不改。 |
| silver 源 schema | `/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/run_contracts/asset_column_schemas.py` 中 `SILVER_STK_MINS_SCHEMA` 包含 `ts_code, freq, trade_date, trade_time, vol, amount`。 | gold 计算只投影必要列，不读 OHLC。 |
| silver 路径 | `/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/paths.py` 的 `silver_stk_mins_path(root, freq, partition_key)` 固定到 `silver/quote/stk_mins/freq=<freq>/trade_date=<date>/part-000.parquet`。 | 新资产必须复用该 helper，禁止手写路径字符串。 |
| silver 分区 | `/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/partitions.py` 已有 `cn_a_stock_mins_silver_trade_days`。 | 新 gold 分区复用该 partition set，不新增分区集。 |
| 现有 gold 模式 | `gold_market_breadth_daily`、`stock_mins_qfq_daily_update_job`、相关 checks/sensors 已形成 gold derived asset 模式。 | 新资产按同类模式新增 asset/check/job/sensor，不修改旧链路。 |
| catalog | `LAKE_ASSET_CATALOG` 已登记现有 active assets；`DATASET_CHINESE_NAMES` 尚无 wealth turnover。 | 实现时必须新增 catalog entry、partition model、中文名和治理测试。 |

CodeGraph 搜索结果确认：当前 orchestrator active source 中没有 `wealth_market_turnover` 或 `gold_wealth_market_turnover`，本方案是新增资产，不是改造既有 DG 资产。

## 3. 数据集卡片

| 项 | 设计 |
| --- | --- |
| dataset_id | `wealth_market_turnover` |
| 中文名 | `财富市场成交额快照` |
| asset key | `gold_wealth_market_turnover` |
| layer | `AssetLayer.GOLD` |
| data_domain | `DataDomain.DERIVED_METRIC` |
| group_name | `wealth` |
| source_system | `SourceSystem.DERIVED` |
| data_contract | `wealth_market_turnover_snapshot` |
| data_contract_source | `DataContractSource.DERIVED_CONTRACT` |
| ingestion_sources | `(IngestionSource.DERIVED_FROM_ASSETS,)` |
| default_daily_ingestion_source | `IngestionSource.DERIVED_FROM_ASSETS` |
| bootstrap_sources | `()` |
| partition definition | `cn_a_stock_mins_silver_trade_days` |
| partition model | `trade_date_partition_gold_wealth_market_turnover` |
| path template | `gold/wealth/market_turnover/trade_date=<partition_key>/part-000.parquet` |
| write policy | `WritePolicy.PARTITION_FILE_ATOMIC_REPLACE` |
| event policy | `EventPolicy.DAGSTER_RUN_ONLY` |
| compute engine | `ComputeEngine.DUCKDB_SQL` |
| source request policy | `no external source request; read five local silver stk_mins parquet files` |

## 4. 时间语义

### 4.1 时间输入语义

`gold_wealth_market_turnover` 支持一个交易日分区输入，分区 key 格式为 `YYYY-MM-DD`。这个日期表示需要计算哪一个 A 股交易日的成交额快照。

### 4.2 执行 unit 语义

一次 Dagster run 只计算一个 `trade_date` 分区，读取该日五个 silver 分钟线文件：

1. `freq=1`
2. `freq=5`
3. `freq=15`
4. `freq=30`
5. `freq=60`

输出一个 partition parquet，文件内恰好五行，每行对应一个 `freq`。

### 4.3 Freshness / audit 语义

该资产不要求所有历史交易日都必须存在，也不自行定义“连续日期完整性”。它的 readiness 只判断最近窗口内：上游 `silver_stk_mins` 五个频度是否 ready、目标 gold 文件是否 ready、blocking checks 是否通过。

历史 backfill 是上线前必须完成的前置步骤。范围对齐 `silver_stk_mins` 的历史范围，当前代码常量为 `STK_MINS_SILVER_HISTORY_START_DATE = "2014-01-01"`，实际执行时还必须以 `cn_a_stock_mins_silver_trade_days` 已注册分区和五频度 silver 文件事实为准。历史 backfill 不改变资产的日常 freshness 语义：日常 readiness 仍只看最近窗口和当日上游状态。

## 5. 文件契约

### 5.1 输出路径

新增 path helper：

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

实现时 catalog metadata 必须通过 `lake_path_template(gold_wealth_market_turnover_path(PATH_TEMPLATE_LAKE_ROOT, PATH_TEMPLATE_PARTITION_KEY))` 生成，禁止在 catalog 里手写另一套模板。

### 5.2 输出 schema

新增 `GOLD_WEALTH_MARKET_TURNOVER_SCHEMA`。字段顺序固定如下：

| 字段 | Lake contract 类型 | 来源/规则 | 是否允许空 |
| --- | --- | --- | --- |
| `type` | `VARCHAR` | 固定 `stock` | 否 |
| `market` | `VARCHAR` | 固定 `CN_A` | 否 |
| `trade_date` | `DATE` | 分区交易日 | 否 |
| `freq` | `SMALLINT` | `1/5/15/30/60` | 否 |
| `build_status` | `VARCHAR` | 固定 `READY` | 否 |
| `latest_trade_time` | `TIMESTAMP` | 当前 `trade_date + freq` 内 `max(trade_time)` | 否 |
| `total_amount` | `DECIMAL(20,2)` | `sum(amount) / 1000`，单位千元 | 否 |
| `total_vol` | `BIGINT` | `sum(vol)` | 否 |
| `security_count` | `INTEGER` | `count(distinct ts_code)` | 否 |
| `source_row_count` | `BIGINT` | 参与汇总的 silver 行数 | 否 |
| `points_json` | `JSON` | 完整分钟点数组，按 `trade_time` 升序 | 否 |
| `build_version` | `VARCHAR` | 固定 `v1` | 否 |
| `built_at` | `TIMESTAMP WITH TIME ZONE` | 本次 asset 生成时间 | 否 |
| `build_note` | `VARCHAR` | 正常构建为 `NULL` | 是 |

说明：

1. `points_json` 在 Postgres serving 表是 `json/jsonb`。Lake 侧已拍板必须使用 DuckDB 可校验的 `JSON` 逻辑类型；如果实现时发现 DuckDB/Parquet 无法稳定写出和校验 `JSON`，必须停止并回报，不允许降级成 `VARCHAR` 继续实现。
2. Lake 文件只保存 `READY` 行。若任一频度缺数据或不满足契约，asset 失败且不替换目标文件；不要在 lake 文件中写 `FAILED` 行。
3. `points_json` 存完整分钟点数组，不是前端固定 `09:30/10:30/11:30/14:00/15:00` 五个累计点。

### 5.3 `points_json` 元素契约

每个元素包含：

| 字段 | 含义 |
| --- | --- |
| `tradeTime` | `HH:MM`，例如 `09:30` |
| `tradeTimeTs` | `YYYY-MM-DD HH:MM:SS` |
| `amount` | 当前分钟点成交额，单位千元 |
| `vol` | 当前分钟点成交量 |
| `securityCount` | 当前分钟点参与统计证券数 |

数组必须按 `trade_time` 升序。

## 6. 计算设计

### 6.1 输入读取

对每个 `partition_key`，输入路径由以下 helper 生成：

```python
silver_stk_mins_path(lake_root.root(), freq, partition_key)
```

读取要求：

1. 必须显式投影 `ts_code, freq, trade_date, trade_time, vol, amount`。
2. 必须使用 `hive_partitioning=False`。
3. 五个输入文件缺任意一个，asset 直接失败。
4. 任一输入文件行数为 0，asset 直接失败。
5. 任一输入文件内 `trade_date` 或 `freq` 与路径不一致，asset 直接失败。
6. 任一输入文件存在 `(ts_code, trade_time)` 重复，asset 直接失败。

### 6.2 聚合规则

对每个 `freq`：

```sql
source_row_count = count(*)
security_count = count(distinct ts_code)
total_amount = round(sum(amount) / 1000, 2)
total_vol = sum(vol)
latest_trade_time = max(trade_time)
```

`points_json` 先按 `trade_time` 聚合：

```sql
point_amount = round(sum(amount) / 1000, 2)
point_vol = sum(vol)
point_security_count = count(distinct ts_code)
```

再按 `trade_time` 升序组装 JSON 数组。

### 6.3 写入方式

1. 使用 DuckDB set-based SQL 计算并写出 parquet。
2. 禁止 Python 按行循环写 parquet。
3. 先写临时文件，再 `os.replace` 原子替换正式 `part-000.parquet`。
4. 替换前必须完成 schema、行数、主键、freq set、日期对齐校验。
5. 如果校验失败，删除临时文件，保留旧正式文件。

### 6.4 行数和主键

目标文件必须满足：

1. 行数恰好为 5。
2. 主键 `(type, market, trade_date, freq)` 唯一。
3. `type='stock'`。
4. `market='CN_A'`。
5. `trade_date` 全部等于分区日期。
6. `freq` 集合恰好为 `{1, 5, 15, 30, 60}`。
7. `build_status='READY'`。

## 7. Asset 设计

新增文件：

```text
lake_console/orchestrator/src/orchestrator/defs/assets/wealth_market_turnover.py
```

资产定义：

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
    tags=build_asset_tags(layer=AssetLayer.GOLD, data_domain=DataDomain.DERIVED_METRIC),
    metadata=build_asset_definition_metadata(
        dataset_id="wealth_market_turnover",
        source_system=SourceSystem.DERIVED,
        data_contract="wealth_market_turnover_snapshot",
        path_template=lake_path_template(...),
        column_schema=GOLD_WEALTH_MARKET_TURNOVER_SCHEMA,
        extra_metadata={
            "calculation_contract": "...",
        },
    ),
)
def gold_wealth_market_turnover(...):
    ...
```

实现注意：

1. 不 import `src.biz.services.wealth...TurnoverSnapshotMaterializeService`。
2. 不 import SQLAlchemy model。
3. 不使用 prod/local Postgres。
4. 不读取 raw stk mins。
5. Materialization metadata 至少记录：
   - `dagster/uri`
   - `dagster/row_count`
   - `goldenshare/observed_columns`
   - `goldenshare/partition_key`
   - `goldenshare/input_file_paths`
   - `goldenshare/freqs`
   - `goldenshare/build_version`
   - `goldenshare/source_row_count`

## 8. Check 设计

新增文件：

```text
lake_console/orchestrator/src/orchestrator/defs/checks/wealth_market_turnover_checks.py
```

只新增一个 blocking check，避免历史 backfill 和日更产生过多 Dagster DB 状态数据：

| check name | 语义 |
| --- | --- |
| `gold_wealth_market_turnover_integrity_check` | 先校验目标文件契约，再从五个 silver 文件重算对账；任一阶段失败则 check failed。 |

内部 helper 分两阶段，但只暴露一个 Dagster asset check：

1. `file_contract` 阶段只看目标 gold 文件：文件存在、schema、行数 5、主键唯一、freq set、日期对齐、固定字段、非空字段、`points_json` 是 JSON、非空且时间升序。
2. `recomputed_from_silver` 阶段读取五个 silver 文件并重新聚合，对比目标文件 summary 和 `points_json` 明细，确认金额单位转换、证券数、成交量、最新时间一致。

`recomputed_from_silver` 阶段必须显式投影，不允许宽表 `select *`。它是防止“文件长得对但里面算错了”的核心门禁。

失败样本 metadata 要使用 `build_check_metadata(...)` 的标准 key，不新增未治理的裸 metadata key。

metadata 必须记录失败阶段：

1. `failure_stage=file_contract`
2. `failure_stage=recomputed_from_silver`

这样 Dagster DB 只保留一个 check event，同时仍能定位错误属于文件契约还是计算对账。

## 9. Readiness 和 Sensor 设计

### 9.1 Readiness helper

新增文件：

```text
lake_console/orchestrator/src/orchestrator/defs/asset_guards/wealth_market_turnover_lake_readiness.py
```

职责：

1. 批量检查最近窗口内 `gold_wealth_market_turnover` 文件状态。
2. 热路径最多检查 `STK_MINS_CONTINUITY_WINDOW_LIMIT` 个交易日。
3. 每个交易日只检查一个 gold 文件，不深扫全历史。
4. 返回结构应能放入 sensor cursor，包含 `trade_date, ready, materialized, checks_passed, reason, failed_check_names, missing_file_paths, checked_row_count, failed_row_count`。

上游 source readiness 复用现有：

```python
batch_silver_stk_mins_lake_readiness(
    connection=...,
    lake_root=...,
    expected_trade_dates=...,
    registered_trade_days=...,
    freqs=STK_MINS_FREQS,
    full_semantics=True,
)
```

### 9.2 Job

新增文件：

```text
lake_console/orchestrator/src/orchestrator/defs/jobs/gold_wealth_market_turnover_update.py
```

job：

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

job 只选择本资产和一个 blocking check，不把 silver 上游资产纳入同一个 job。

### 9.3 Sensor

新增文件：

```text
lake_console/orchestrator/src/orchestrator/defs/sensors/gold_wealth_market_turnover_sensor.py
```

sensor：

| 项 | 设计 |
| --- | --- |
| name | `gold_wealth_market_turnover_update_job_sensor` |
| job target | `gold_wealth_market_turnover_update_job` |
| default_status | `STOPPED` |
| minimum_interval_seconds | `600` |
| required resources | `lake_root`, `duckdb` |
| tags | `SensorDomain.DERIVED_METRIC`, `SensorTargetLayer.GOLD`, `SensorRole.ASSET_UPDATE` |
| run key | `gold_wealth_market_turnover:<trade_date>` |
| each tick | 最多 1 个 `RunRequest` |

触发逻辑：

1. 使用交易日历加载最近 expected trade date window。
2. expected window 不超过 `STK_MINS_CONTINUITY_WINDOW_LIMIT`。
3. 读取 `cn_a_stock_mins_silver_trade_days` 已注册分区。
4. 若注册分区有缺口，skip。
5. 调用 `batch_silver_stk_mins_lake_readiness(..., full_semantics=True)`；若目标日任一 freq silver 不 ready，skip，且不继续扫描 gold readiness。
6. 调用新 gold readiness helper；若目标 gold 已 ready，skip。
7. 若目标 gold 有失败 check 或 materialization/check 状态不一致，fail closed，skip 并写 cursor reason，不自动覆盖。
8. 选择最早一个 gold not ready 且 silver ready 的交易日发起 run。
9. 使用 `build_run_request(...)` 和 `build_asset_update_run_key(...)`。
10. 使用 `build_sensor_cursor(...)`，不要手写裸 JSON cursor。

运行时间门槛：

1. 日更窗口固定为 `silver_stk_mins` 日更时间 + 10 分钟。
2. 当前代码中 `STOCK_MINS_SILVER_RUN_START = time(19, 50)`，因此本 sensor 的运行窗口为 `20:00`。
3. `20:00` 只是允许检查的时间门槛，不代表一定触发；只有当日五个 `silver_stk_mins` 频度全部 ready，才允许发起 gold run。
4. 实现时优先从 `STOCK_MINS_SILVER_RUN_START` 推导 `GOLD_WEALTH_MARKET_TURNOVER_RUN_START`，不要另设散落配置。

## 10. 历史 Backfill 设计

历史 backfill 必做，作为日更启用前的上线前置步骤。

范围：

1. 起点对齐 `silver_stk_mins` 历史范围。当前代码常量为 `STK_MINS_SILVER_HISTORY_START_DATE = "2014-01-01"`。
2. 终点为执行 backfill 时 `silver_stk_mins` 已完成的最新交易日。
3. 每个历史交易日必须同时存在五个 silver 频度文件；缺任一频度则该交易日不写 gold，并在 backfill 报告中列出。
4. 不按全市场日历强行补没有 silver 输入的日期。

执行口径：

1. 历史文件生成优先使用 direct lake bootstrap，不通过 Dagster backfill 为每个历史分区创建 run。
2. bootstrap 必须复用正式 asset 的计算 SQL/helper 和正式 check 的内部校验 helper。
3. 不允许为了历史加一套绕过 checks 的写文件脚本。
4. 历史状态补录采用 runless event，且只补最近窗口，不为全历史每个分区补 materialization/check event。
5. 历史 runless 状态窗口统一保留最近 20 个交易日；这是本类历史补状态的统一口径，不跟随 sensor 热路径窗口变化。
6. 历史 backfill 完成后，必须输出报告：输入交易日数、成功分区数、跳过分区数、失败原因样本、目标文件数、总行数、校验结果、runless event 计划数量。

验收：

1. 成功分区每个文件恰好 5 行。
2. 成功分区的 `freq` 集合都是 `{1, 5, 15, 30, 60}`。
3. 所有成功分区通过 `gold_wealth_market_turnover_integrity_check` 的内部两阶段校验。
4. 历史输出范围与 silver 可用范围一致；差异必须有明确原因。
5. Dagster DB 只为最近 20 个交易日补 runless materialization/check event，不补全历史状态。
6. 日更 sensor 启用前，最近窗口必须 ready。

只读 profile 结果：

1. 报告：`/private/tmp/wealth_market_turnover_history_profile-history_20260624_200131.json`。
2. `selected_partition_count=3030`，范围为 `2014-01-02` 到 `2026-06-23`。
3. 五个 silver 频度各有 `3030` 个分区，`complete_silver_partition_count=3030`。
4. 当前 gold 目标文件数为 `0`，`planned_write_count=3030`。
5. `missing_input_count=0`。
6. 最近 20 日 runless event 计划数按统一口径封顶为 `40`，不按全历史 `3030 * 2` 计算。
7. sample 分区为 `2014-01-02`、`2020-03-23`、`2026-06-23`。

sample 写入已执行并通过：

1. 写入报告：`/private/tmp/wealth_market_turnover_history_write-sample_20260624_200432.json`。
2. 审计报告：`/private/tmp/wealth_market_turnover_history_audit-sample_20260624_200439.json`。
3. 写入分区为 `2014-01-02`、`2020-03-23`、`2026-06-23`，未跳过已有文件。
4. 目标文件数为 `3`，目标总行数为 `15`，每个分区各 `5` 行。
5. `failed_partition_count=0`，文件契约和从 silver 重算一致性均通过。
6. 本阶段未写 Dagster DB，未补 runless event，未启用 sensor。

full 写入已执行并通过：

1. 写入报告：`/private/tmp/wealth_market_turnover_history_write-full_20260624_204837.json`。
2. 审计报告：`/private/tmp/wealth_market_turnover_history_audit-full_20260624_205241.json`。
3. full 阶段跳过已存在的 `257` 个分区，新增写入 `2773` 个分区，最终覆盖 `3030` 个交易日。
4. 最终范围为 `2014-01-02` 到 `2026-06-23`。
5. 目标文件数为 `3030`，目标总行数为 `15150`。
6. `failed_partition_count=0`，全量文件契约和从 silver 重算一致性均通过。
7. 本阶段未写 Dagster DB，未补 runless event，未启用 sensor。

实现中已固化的确定性口径：

1. `amount` 从 silver 读取后先转为 `DECIMAL(38,4)` 再聚合，避免 DOUBLE 并行求和导致同日重算出现 `0.01` 漂移。
2. writer 的写入、审计、摘要使用独立 DuckDB connection，并在写入/审计 connection 中关闭 `enable_external_file_cache`，避免同进程刚写再读的 parquet 缓存误判。
3. writer 临时文件后缀保留 `.parquet`，并兼容清理旧 `part-000.parquet.tmp` 临时文件。

## 11. Catalog 和 Governance 改动点

实现时必须同步以下位置：

| 文件 | 改动 |
| --- | --- |
| `lake_console/orchestrator/src/orchestrator/defs/run_contracts/asset_column_schemas.py` | 新增 `GOLD_WEALTH_MARKET_TURNOVER_SCHEMA`。 |
| `lake_console/orchestrator/src/orchestrator/defs/paths.py` | 新增 `gold_wealth_market_turnover_path(...)`。 |
| `lake_console/orchestrator/src/orchestrator/defs/catalog/name_mapping.py` | 新增 `wealth_market_turnover` 中文名。 |
| `lake_console/orchestrator/src/orchestrator/defs/catalog/lake_assets.py` | 新增 check tuple、partition model、catalog entry，并导入 path/schema。 |
| `lake_console/orchestrator/src/orchestrator/defs/assets/wealth_market_turnover.py` | 新增 asset 和写入 helper。 |
| `lake_console/orchestrator/src/orchestrator/defs/checks/wealth_market_turnover_checks.py` | 新增一个 blocking check。 |
| `lake_console/orchestrator/src/orchestrator/defs/jobs/gold_wealth_market_turnover_update.py` | 新增 job。 |
| `lake_console/orchestrator/src/orchestrator/defs/sensors/gold_wealth_market_turnover_sensor.py` | 新增 sensor。 |
| `lake_console/orchestrator/src/orchestrator/defs/asset_guards/wealth_market_turnover_lake_readiness.py` | 新增 gold readiness helper。 |
| `lake_console/orchestrator/src/orchestrator/defs/bootstrap/wealth_market_turnover_history.py` | 新增历史 direct lake bootstrap 计划、写入和审计 helper。 |
| `lake_console/orchestrator/src/orchestrator/defs/bootstrap/wealth_market_turnover_history_cli.py` | 新增历史 bootstrap CLI，默认 dry-run，`--apply` 才写 lake。 |
| `lake_console/orchestrator/src/orchestrator/defs/bootstrap/wealth_market_turnover_runless_events.py` | 新增最近 20 日 runless event 计划和报告 helper。 |
| `lake_console/orchestrator/src/orchestrator/defs/bootstrap/wealth_market_turnover_runless_events_cli.py` | 新增 runless event CLI，默认 dry-run，`--apply` 才写 Dagster event。 |
| `lake_console/orchestrator/tests/**` | 新增资产、checks、readiness、sensor、job、bootstrap、runless、catalog、static gates 测试。 |

Catalog entry 必须包含：

```python
LakeAssetCatalogEntry(
    asset_key="gold_wealth_market_turnover",
    dataset_id="wealth_market_turnover",
    dataset_name=get_dataset_chinese_name("wealth_market_turnover"),
    layer=AssetLayer.GOLD,
    data_domain=DataDomain.DERIVED_METRIC,
    group_name="wealth",
    source_system=SourceSystem.DERIVED,
    data_contract="wealth_market_turnover_snapshot",
    data_contract_source=DataContractSource.DERIVED_CONTRACT,
    column_schema=GOLD_WEALTH_MARKET_TURNOVER_SCHEMA,
    path_template=lake_path_template(gold_wealth_market_turnover_path(...)),
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
        python_row_loop_allowed=False,
        source_request_policy="read local silver stk_mins parquet files only",
    ),
)
```

## 12. 测试计划

### 12.1 Asset 测试

新增 `tests/test_gold_wealth_market_turnover_asset.py`：

1. 使用临时 lake root 构造五个 silver stk mins parquet。
2. 正常样本生成一份 gold 文件，行数为 5。
3. 验证 `amount / 1000` 单位转换：源为元，gold 为千元。
4. 验证 `total_vol`、`source_row_count`、`security_count`、`latest_trade_time`。
5. 验证 `points_json` 包含完整分钟点数组，按时间升序。
6. 验证任一 source 文件缺失时失败。
7. 验证任一 source 文件为空时失败。
8. 验证 source `freq/trade_date` 与路径不一致时失败。
9. 验证重复 `(ts_code, trade_time)` 时失败。
10. 验证 atomic replace：失败时不污染旧正式文件。

### 12.2 Check 测试

新增 `tests/test_gold_wealth_market_turnover_checks.py`：

1. `gold_wealth_market_turnover_integrity_check` 正常样本通过。
2. 缺文件失败。
3. schema 缺列/错序/错类型失败。
4. 行数不是 5 失败。
5. freq set 缺失或多余失败。
6. 主键重复失败。
7. `type/market/build_status` 非固定值失败。
8. `points_json` 空数组、不可解析、非升序失败。
9. summary 金额、成交量、证券数、最新时间任一不一致失败。
10. point 明细任一不一致失败。
11. 文件契约失败时 metadata 包含 `failure_stage=file_contract`。
12. silver 重算对账失败时 metadata 包含 `failure_stage=recomputed_from_silver`。

### 12.3 Job / Sensor 测试

新增 `tests/test_gold_wealth_market_turnover_sensor.py` 和 `tests/test_gold_wealth_market_turnover_job.py`：

1. sensor 默认 `STOPPED`。
2. sensor target job 是 `gold_wealth_market_turnover_update_job`。
3. 每 tick 最多发起一个 run。
4. 上游 silver 任一 freq 未 ready 时 skip。
5. 目标 gold 已 ready 时 skip。
6. 目标 gold 有 failed check 时 skip，不自动重跑覆盖。
7. run key 为 `gold_wealth_market_turnover:<trade_date>`。
8. run request 使用 `build_run_request(...)`。
9. cursor 使用 `build_sensor_cursor(...)`。
10. job selection 只包含 `gold_wealth_market_turnover` 和一个 check，不包含 silver 上游。
11. `20:00` 前 skip；`20:00` 后但 silver 五频度未全部 ready 仍 skip。
12. 只有部分 silver 频度 ready 时，全失败，不写部分结果。

### 12.4 Governance / Static Gates

需要更新或新增：

1. active asset catalog 数量 +1。
2. catalog entry 与 asset definition metadata 一致。
3. catalog blocking checks 与实际 check 名称一致。
4. `DATASET_CHINESE_NAMES` 包含 `wealth_market_turnover`。
5. 静态门禁确认新资产不 import `src.biz`、SQLAlchemy model、Tushare resource、prod DB resource。
6. 静态门禁确认 sensor 不手写 run key/cursor，不一次提交多个分区。
7. 静态门禁确认生产代码不硬编码某个迁移日期或历史起点。
8. 静态门禁确认 `points_json` schema 是 `JSON`，不是 `VARCHAR`。

建议验证命令：

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
  tests.test_run_contract_static_gates
git diff --check
```

`dg check defs` 只在单独审批后运行。

## 13. 性能门禁

| 入口 | 最大读取 | 写入 | 拒绝策略 |
| --- | ---: | ---: | --- |
| asset 单分区 | 5 个 silver parquet | 1 个 gold parquet | 任一 source 缺失、为空、schema/key/date/freq 错误即失败 |
| check | 先读 1 个 gold；文件契约通过后再读 5 个 silver 重算 | 0 | 任一阶段不一致即 failed check |
| sensor hot path | 最近最多 10 个交易日，每日最多 5 个 silver readiness + 1 个 gold readiness | 0 或 1 run request | 上游未 ready、目标 failed、不一致状态均 skip |
| catalog/static gates | 只读 Python 定义 | 0 | catalog 与定义不一致则测试失败 |

拒绝策略：

1. 不允许 Python 逐行扫描全市场分钟线。
2. 不允许 sensor 深扫全历史。
3. 不允许 sensor 每 tick 发起多个交易日 run。
4. 不允许读 raw/prod DB 来补齐该 gold 资产。

## 14. 实施顺序

建议按以下顺序落地：

1. 新增 schema/path/catalog/name mapping。
2. 新增 asset 写入 helper 和 `gold_wealth_market_turnover`。
3. 新增一个 blocking check，内部包含文件契约和 silver 重算两阶段。
4. 新增 job。
5. 新增 lake readiness helper。
6. 新增 sensor，默认 `STOPPED`。
7. 补齐 asset/check/job/sensor/catalog/static tests。
8. 运行单元测试和 `git diff --check`。
9. 单独审批后运行 `dg check defs`。已执行并通过：`All definitions loaded successfully.`
10. 单独审批并执行 direct lake bootstrap 历史 backfill，范围对齐 `silver_stk_mins` 历史范围。
11. 单独审批并执行最近 20 个交易日 runless event apply。
12. backfill 与 runless event 验收通过后，再决定是否启用 sensor。

## 15. 风险和后续项

| 风险/问题 | 结论/建议 |
| --- | --- |
| `points_json` 的 DuckDB/Parquet 稳定类型需要实现时验证 | 已拍板使用 `JSON`。如果实现时无法稳定写出和校验 `JSON`，停止回报，不降级为 `VARCHAR`。 |
| 旧 serving 表目前由 `src/biz` 服务从 raw DB 生成 | 已拍板暂不把 gold lake 结果同步回 `core_serving.wealth_market_turnover_snapshot`；API/serving 切换后续另起方案。 |
| 当前 Wealth API 只消费 `freq=30` | 资产仍生成五个频度，保持原服务表完整契约；不要为了当前页面裁掉其他频度。 |
| 历史数据是否需要 backfill | 已拍板必须 backfill，范围对齐 `silver_stk_mins` 历史范围；执行前另列 backfill 计划。 |
| backfill 状态数据量 | 已拍板使用 direct lake bootstrap + 最近 20 个交易日 runless event，不为全历史生成 Dagster runs/check events。 |
| sensor 启用时间 | 已拍板日更窗口为 silver 日更时间 + 10 分钟，即当前 `20:00`；但仍必须等当日五频度 silver ready。 |
| 部分频度 ready | 已拍板全失败，不写部分结果。 |

## 16. 开发完成验收口径

代码完成后，至少满足：

1. `gold_wealth_market_turnover` 在 Dagster definitions 中可加载。
2. Catalog、metadata、schema、path template、checks 完全一致。
3. 单分区样本 materialize 产生 5 行 parquet。
4. `gold_wealth_market_turnover_integrity_check` 全绿。
5. sensor 默认停止，且只会在 silver 全 ready 后为一个 trade date 提交 run。
6. 新代码不读取 raw/prod DB/Tushare，不 import `src.biz` 旧服务。
7. 不影响现有 Wealth API、旧 `core_serving.wealth_market_turnover_snapshot` 表和现有 maintenance CLI。
8. 历史 bootstrap/runless 工具默认 dry-run；正式 lake 写入和 Dagster event 写入必须单独审批并显式 `--apply`。
