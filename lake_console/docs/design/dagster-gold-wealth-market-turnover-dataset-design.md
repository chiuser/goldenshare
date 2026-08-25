# Dagster Gold Wealth Market Turnover Dataset Design

状态：WMT-1 至 WMT-6 的代码、历史 Lake、最近 20 日 runless event 和 Prod Serving 同步已按原口径闭环。WMT-7“北交所收盘集合竞价成交量/成交额校准”已完成代码开发和本地测试；正式历史 plan 在首个分区发现历史北交所分钟源代码集合缺口后，于候选生成和正式写入前安全停止。WMT-7R 负责先恢复可恢复的 Raw/Silver 及真实受影响下游，并对源站仍为空的旧日期按冻结清单跳过；截至 `2026-08-25` 仅完成只读审计和方案设计，未写正式 Lake、Prod 或 Dagster event。WMT-7 历史修复明确不补任何 Gold/Prod 历史 materialization/check event。WMT-7/WMT-7R 生效后，本文第 17、18 节是当前计算、依赖、校验和恢复口径；前文 WMT-1 至 WMT-6 与其冲突的“只读五频分钟线”描述仅保留为历史实施记录，不再作为后续开发事实。

## 1. 目标

新增 Dagster 数据湖资产 `gold_wealth_market_turnover`，按交易日分区，从新湖 `silver_stk_mins` 计算财富行情市场总览使用的成交额分钟快照。

本轮设计口径：

1. 资产名：`gold_wealth_market_turnover`。
2. 数据层级：`gold`。这是服务型结果数据，但在 lake 内属于从 silver 派生的 gold 资产。
3. 分区：按交易日分区，复用 `cn_a_stock_mins_silver_trade_days`。
4. 原 WMT-1 数据源只读 `silver_stk_mins` 五频文件；WMT-7 生效后增加同日 `silver_stock_daily`，仅用于校准北交所缺失的收盘集合竞价成交量和成交额，详细口径见第 17 节。
5. 频度：首期固定 `1/5/15/30/60`，与现有 `TURNOVER_SNAPSHOT_ALLOWED_FREQS` 和 `STK_MINS_FREQS` 对齐。
6. 输出路径：`gold/wealth/market_turnover/trade_date=<YYYY-MM-DD>/part-000.parquet`。
7. 输出字段：对齐当前 `core_serving.wealth_market_turnover_snapshot` 的业务 schema。
8. 计算方式：按 `trade_date + freq` 聚合全市场分钟成交额、成交量和证券数，`amount` 从元转换为千元。
9. 调度：新增专用 job 和 sensor；sensor 默认 `STOPPED`，只在上游 silver 五个频度全 ready 后触发单日分区。

WMT-1 到 WMT-5 原始范围不做：

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
3. WMT-1 到 WMT-5 暂不把 gold lake 结果同步回 `core_serving.wealth_market_turnover_snapshot`；WMT-6 已拍板改为同一 job 内的下游 prod sync asset 落地，不把 prod 写入塞进 gold asset 函数。
4. 日更启动时间为 `silver_stk_mins` 日更时间 + 10 分钟；当前代码中 `STOCK_MINS_SILVER_RUN_START = 19:40`，因此本资产日更窗口为 `19:50`。
5. 即使到了 `19:50`，也必须等当日五个 silver 频度全部 ready 才触发。
6. 如果某天只有部分 silver 频度 ready，则本资产全失败，不允许写入部分频度结果，由上游先处理错误。
7. WMT-6 prod sync asset 名称确认为 `prod_core_wealth_market_turnover`。
8. WMT-6 第一版不新增 prod sync check，只在 asset 内部做事务内校验和写后读回审计。
9. WMT-6 本轮不做历史 prod 回灌。
10. prod 写库账号必须最小权限，只允许 `core_serving.wealth_market_turnover_snapshot` 的 DML，不给 DDL 和其它表权限。

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
| prod Postgres resource | `/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/resources.py` 中当前 `ProdPostgresResource.connect()` 固定 `readonly=True` 且 `autocommit=True`，用于已批准的 prod-core-db 只读导出。 | WMT-6 不能复用该 resource 做写入；必须新增 `ProdPostgresWriteResource`，resource key 为 `prod_postgres_write`，并保留现有只读 resource 语义不变。 |
| prod sync 现有模式 | `prod_ch_share_fact_market_breadth_daily` 是下游 prod sync asset，负责把本机 serving 副本同步到 prod ClickHouse；prod sync 写入不塞进上游 gold asset。 | WMT-6 复用同类 Dagster asset 表达：新增下游 prod Postgres serving sync asset，并放入现有 `gold_wealth_market_turnover_update_job` selection。 |

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
| source request policy | `no external source request; read five local silver_stk_mins parquet files plus one same-date silver_stock_daily parquet file` |

## 3.1 WMT-6 Prod Serving 同步目标

新需求：`gold_wealth_market_turnover[trade_date]` 成功生产后，同一分区写入 prod PostgreSQL：

```text
core_serving.wealth_market_turnover_snapshot
```

同步目标不是替代 gold lake 事实源。长期口径是：

```text
silver_stk_mins
  -> gold_wealth_market_turnover[trade_date] lake parquet
  -> prod_core_wealth_market_turnover[trade_date]
  -> prod core_serving.wealth_market_turnover_snapshot
```

核心结论：

1. 可行，但不建议把 prod DB 写入直接写在 `gold_wealth_market_turnover` asset 函数末尾。
2. 已确认新增下游 asset：`prod_core_wealth_market_turnover[trade_date]`。
3. 不新增独立 job；把下游 prod sync asset 加入现有 `gold_wealth_market_turnover_update_job` selection。
4. 现有 `gold_wealth_market_turnover_update_job_sensor` 继续作为入口，但 WMT-6 实现时必须把“目标链路 ready”从只看 gold，升级为 gold 和 prod sync 都 ready。
5. 如果 prod DB 写入失败，整条 job 应失败；gold 文件可能已生成，但 prod sync asset 不产生 materialization。重跑同一 partition 必须幂等。
6. 现有 `ProdPostgresResource` 是只读 resource，必须保留；prod 写入需要独立的 write resource / write helper，并且只允许写白名单表 `core_serving.wealth_market_turnover_snapshot`。

不推荐的两个方案：

| 方案 | 结论 | 原因 |
| --- | --- | --- |
| 在 `gold_wealth_market_turnover` asset 内直接写 prod DB | 不推荐 | 混合 lake 事实生成和外部 serving 副作用，prod DB 故障会让 gold asset 语义变脏，也无法单独观察 prod sync 是否完成。 |
| 新增 run-status / asset sensor 再触发单独 prod job | 本轮不选 | 可以表达“gold 成功后触发”，但会新增 job/sensor/cursor 和独立 run，违背“不单独写 job”的目标。 |

已确认方案的含义：

1. “不单独写 job”是可行的；同一个 `gold_wealth_market_turnover_update_job` 可以选择两个资产。
2. “生产成功之后执行”由 Dagster asset 依赖表达：`prod_core_wealth_market_turnover` 依赖 `gold_wealth_market_turnover`，只有上游完成后才执行。
3. job 成功口径升级为：gold lake 文件生成、gold integrity check 通过、prod serving 分区写入并自校验通过。

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

WMT-1 到 WMT-5 当前 job：

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

WMT-6 确认把同一个 job 扩展为：

```python
gold_wealth_market_turnover_update_job = dg.define_asset_job(
    name="gold_wealth_market_turnover_update_job",
    selection=(
        dg.AssetSelection.assets(
            gold_wealth_market_turnover,
            prod_core_wealth_market_turnover,
        )
        | dg.AssetSelection.checks_for_assets(gold_wealth_market_turnover)
    ),
    executor_def=dg.in_process_executor,
    description="按单日分区生成财富市场成交额 gold 快照，并同步 prod core serving。",
)
```

说明：

1. 不新增 job，sensor target job 名称不变。
2. 不把 silver 上游资产纳入同一个 job；silver 仍是只读前置 ready 条件。
3. `prod_core_wealth_market_turnover` 是下游 asset，不是 check、hook 或 sensor 副作用。
4. 由于 prod sync asset 自己读取并校验 gold parquet，若 Dagster 的 blocking check 调度顺序出现实现差异，prod 写入也不会绕过 gold 文件契约。

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

WMT-6 后 sensor 决策必须扩展：

1. 当前入口仍是 `gold_wealth_market_turnover_update_job_sensor`。
2. 目标日期选择不能只看 `gold_wealth_market_turnover` 是否 ready；必须看“gold ready + prod sync ready”的链路状态。
3. 如果 gold 未 ready 且 silver ready，提交同一个 job。
4. 如果 gold 已 ready 但 prod sync 未 materialized，仍允许提交同一个 job，依靠幂等 gold 写入和 prod replace 完成补同步。
5. 如果 gold 已 materialized 但 `gold_wealth_market_turnover_integrity_check` 失败，继续 fail closed，不允许为该日写 prod。
6. 如果 prod sync asset 曾经失败但没有 materialization，默认不靠 sensor 无限重试；第一版依赖 asset retry policy 和人工按 partition 重跑，避免固定 run key 下反复提交无效 run。
7. cursor 只记录当前阻断组件：`silver_stk_mins`、`gold_wealth_market_turnover`、`prod_core_db` 或 `none`，不写 prod row 明细或完整 JSON。

运行时间门槛：

1. 日更窗口固定为 `silver_stk_mins` 日更时间 + 10 分钟。
2. 当前代码中 `STOCK_MINS_SILVER_RUN_START = time(19, 40)`，因此本 sensor 的运行窗口为 `19:50`。
3. `19:50` 只是允许检查的时间门槛，不代表一定触发；只有当日五个 `silver_stk_mins` 频度全部 ready，才允许发起 gold run。
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

最近 20 日 runless event 已补录并通过：

1. plan 报告：`/private/tmp/wealth_market_turnover_runless_events_plan-events_20260624_205404.json`。
2. sample apply 报告：`/private/tmp/wealth_market_turnover_runless_events_report-sample-events_20260624_205450.json`。
3. recent-window apply 报告：`/private/tmp/wealth_market_turnover_runless_events_report-recent-window-events_20260624_205548.json`。
4. final audit 报告：`/private/tmp/wealth_market_turnover_runless_events_audit-recent-window-events_20260624_205600.json`。
5. runless 窗口为 `2026-05-26` 到 `2026-06-23` 的最近 `20` 个交易日。
6. sample 阶段写入 `2026-05-26`、`2026-06-09`、`2026-06-23` 三个分区，共 `6` 条 event。
7. recent-window 阶段跳过 sample 三个分区，补录剩余 `17` 个分区，共 `34` 条 event。
8. final audit 显示 `existing_materialized_count=20`、`failed_partition_count=0`。
9. 本机 Dagster PostgreSQL 只读核验显示最近 20 个分区的 `gold_wealth_market_turnover_integrity_check` 为 `20` 条，全部 `SUCCEEDED`，全部绑定 materialization。
10. 本阶段未运行 job/sensor/backfill，未写 lake 文件，未写 prod DB。

最终 definitions 门禁已执行并通过：`DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home uv run dg check defs`，结果为 `All component YAML validated successfully.` 和 `All definitions loaded successfully.`。

## 10.1 WMT-6 Prod DB 写入设计

新增下游 asset：

```text
prod_core_wealth_market_turnover[trade_date]
```

职责：

1. 只读取同分区 `gold_wealth_market_turnover` parquet。
2. 只写 prod PostgreSQL 表 `core_serving.wealth_market_turnover_snapshot`。
3. 不重新读取 silver，不重新计算成交额，不复用旧 `src.biz` raw DB 构建服务。
4. 每个 partition 固定写入五行，对应 `freq in (1, 5, 15, 30, 60)`。
5. asset 成功 materialize 即表示 prod 表中该 `type='stock' AND market='CN_A' AND trade_date=<partition_key>` 分区已经替换完成并通过写后自校验。

写入事务：

1. 运行前检查 gold parquet 文件契约：schema、行数 5、主键、日期、freq set、`build_status='READY'`、`points_json` 非空。
2. 使用独立 prod Postgres write resource 开启单事务，禁止 autocommit。
3. 在事务内执行分区 replace：

```sql
DELETE FROM core_serving.wealth_market_turnover_snapshot
WHERE type = 'stock'
  AND market = 'CN_A'
  AND trade_date = %(trade_date)s;
```

4. 再显式字段插入五行：

```sql
INSERT INTO core_serving.wealth_market_turnover_snapshot (
  type,
  market,
  trade_date,
  freq,
  build_status,
  latest_trade_time,
  total_amount,
  total_vol,
  security_count,
  source_row_count,
  points_json,
  build_version,
  built_at,
  build_note
) VALUES (...)
```

5. 插入后在同一事务内按主键读回五行，比较 row count、freq set、summary 字段和 `points_json` canonical hash。
6. 自校验通过才 commit；失败 rollback，asset 失败且不写 materialization。

同步 metadata：

| key | 含义 |
| --- | --- |
| `dagster/uri` | `postgresql://prod/core_serving.wealth_market_turnover_snapshot?trade_date=<date>` |
| `dagster/row_count` | 固定为 `5` |
| `goldenshare/observed_columns` | prod serving 表业务字段 |
| `goldenshare/partition_key` | 交易日 |
| `goldenshare/source_gold_path` | 同分区 gold parquet 路径 |
| `goldenshare/prod_table` | `core_serving.wealth_market_turnover_snapshot` |
| `goldenshare/replace_mode` | `transactional_delete_then_insert` |
| `goldenshare/points_json_hash` | 五行 JSON canonical hash 摘要，不写完整 JSON |

不新增 prod sync asset check。理由：

1. 本同步每天固定 5 行，写入资产内部可以在事务提交前完成完整自校验。
2. 新增 check 会每天多写一条 Dagster check event，但对定位问题的增量价值有限。
3. 第一版不新增 prod sync check；若后续治理另行要求 serving asset 必须有 check，最多新增一个 blocking check：`prod_core_wealth_market_turnover_integrity_check`，不得拆成 row count/schema/date/json 多个细碎 check。

失败语义：

| 失败点 | 结果 |
| --- | --- |
| gold 文件缺失或契约失败 | 不连接 prod DB，asset 失败 |
| prod DB 连接失败 | asset 失败，gold 文件保留 |
| delete 成功但 insert 或读回校验失败 | 同事务 rollback，prod 仍保留旧分区 |
| commit 成功但 Dagster 进程随后异常 | prod 已更新但 asset materialization 可能缺失；同 partition 幂等重跑可恢复 Dagster 状态 |
| prod sync 最终失败 | 本次 job 失败；第一版不靠 sensor 无限自动重试，人工按 partition 重跑 |

配置和权限：

1. 不修改当前 `ProdPostgresResource`；它继续保持只读。
2. 新增 prod write resource 前必须完成配置项审计，列清 env var、默认值、权限、消费者和测试门禁。
3. write resource 的数据库用户只允许写 `core_serving.wealth_market_turnover_snapshot`，不得拥有泛化 DDL 或其它表写权限。
4. 代码中禁止手写连接串，禁止 `select *`，禁止写 `source/created_at/updated_at` 等非业务字段。

prod 写库用户执行结果：

1. 已在远程 prod PostgreSQL `goldenshare` 数据库创建 `lake_raw_writer`。
2. `lake_raw_writer` 可登录，密码已设置；不是 `SUPERUSER`、`CREATEDB`、`CREATEROLE`、`REPLICATION` 或 `BYPASSRLS`。
3. `lake_raw_writer` 只获得 `goldenshare` 数据库 `CONNECT`、`core_serving` schema `USAGE`，且没有 `core_serving` schema `CREATE` 权限。
4. `lake_raw_writer` 对 `core_serving.wealth_market_turnover_snapshot` 只具备 `SELECT, INSERT, UPDATE, DELETE`。
5. 权限审计显示 `lake_raw_writer` 对目标表以外没有显式表权限。
6. 密码不写入文档、代码、提交信息或审计报告；本地 Dagster `PROD_POSTGRES_WRITE_*` env 仍需在正式运行环境中单独配置。

当前 WMT-6 第一阶段实现状态：

1. 已新增 `ProdPostgresWriteResource` / `prod_postgres_write`。配置项为 `PROD_POSTGRES_WRITE_HOST`、`PROD_POSTGRES_WRITE_PORT`、`PROD_POSTGRES_WRITE_USER`、`PROD_POSTGRES_WRITE_PASSWORD`、`PROD_POSTGRES_WRITE_DATABASE`、`PROD_POSTGRES_WRITE_SSLMODE`，其中 `SSL_MODE` 默认 `prefer`；消费者是后续 `prod_core_wealth_market_turnover` asset。
2. 已新增 `prod_db/wealth_market_turnover.py` 的事务 replace helper，固定写表 `core_serving.wealth_market_turnover_snapshot`，固定五行，写入前和读回后都按 gold schema 进行约束校验。
3. 现有 `ProdPostgresResource` / `prod_postgres` 仍是只读资源，`gold_wealth_market_turnover` asset 仍不 import prod write helper 或 resource。
4. 已执行 prod `core_serving.wealth_market_turnover_snapshot` 只读复核，报告为 `/private/tmp/wealth_market_turnover_prod_schema_audit.csv`；字段集合、主键和最新分区行数满足 WMT-6 接入门禁。
5. 已新增 active `prod_core_wealth_market_turnover` asset。该 asset 只读同分区 gold parquet，gold 文件契约失败时不连接 prod；prod 写入通过 `prod_postgres_write` 单事务执行 exact partition delete、五行 insert、read-back audit。
6. 已扩展 `gold_wealth_market_turnover_update_job` selection：同一 job 包含 `gold_wealth_market_turnover`、`gold_wealth_market_turnover_integrity_check` 和 `prod_core_wealth_market_turnover`，不新增独立 prod sync job。
7. 已新增 catalog entry，新增 `WritePolicy.POSTGRES_TABLE_SYNC`、`ComputeEngine.POSTGRES_SQL` 和 `PartitionPhysicalLayout.POSTGRES_TABLE`，避免把 Postgres serving sync 伪装成 ClickHouse sync。
8. 已更新 `gold_wealth_market_turnover_update_job_sensor` readiness：最近窗口内 gold 与 prod sync 均 ready 才算链路 ready；gold ready 但 `prod_core_wealth_market_turnover` 未 materialized 时提交同一个 job；prod sync 已有失败 run 且无成功 materialization 时 skip，`reason_code="prod_sync_failed_requires_manual_retry"`。本阶段尚未启用 sensor。
9. 已创建并审计 prod 写库角色 `lake_raw_writer`，权限限定为 `core_serving.wealth_market_turnover_snapshot` 单表 DML。
10. 已单独审批执行 prod write rollback dry-run，报告为 `/private/tmp/wealth_market_turnover_prod_sync_rollback_dry_run_20260625_014345.json`：分区 `2026-06-24`，gold 输入 5 行，事务内写入 5 行，freq 集合 `1,5,15,30,60`，正式 `points_json` hash 为 `b278082d23e1c4e6697779511999b75c`，写后读回审计通过，`prod_transaction_committed=false`，回滚前后 prod 目标分区均为 0 行，`rollback_preserved_state=true`。
11. 已单独审批执行 `gold_wealth_market_turnover_update_job[2026-06-24]` 正式 apply，run id 为 `c43644d0-84eb-4733-a648-ba5fb2f67cbf`，状态 `SUCCESS`。post-audit 报告为 `/private/tmp/wealth_market_turnover_prod_apply_audit_20260625_015723.json`：prod 表目标分区 5 行，freq 集合 `1,5,15,30,60`，正式 `points_json` hash 为 `b278082d23e1c4e6697779511999b75c`，`gold_wealth_market_turnover[2026-06-24]` 与 `prod_core_wealth_market_turnover[2026-06-24]` 均 ready。
12. 已按审批将正式 Dagster instance 中 `gold_wealth_market_turnover_update_job_sensor` 从 `RUNNING` 停为 `STOPPED`；本轮不启用 sensor。

prod schema 只读复核结果：

1. 字段集合覆盖 WMT schema：`type, market, trade_date, freq, latest_trade_time, security_count, source_row_count, total_amount, total_vol, points_json, build_status, build_version, built_at, build_note`。表物理列顺序与 gold schema 不完全一致，后续写入必须继续使用显式列名，禁止依赖 `SELECT *` 或物理顺序。
2. 类型兼容：`trade_date=date`、`freq=smallint`、`total_amount=numeric`、`total_vol=bigint`、`points_json=jsonb`、`built_at=timestamptz`。
3. 主键为 `PRIMARY KEY (type, market, trade_date, freq)`，符合本方案的幂等 replace 粒度。
4. 最近 `stock/CN_A` 分区为 `2026-06-04`，行数 `5`，freq 集合为 `1,5,15,30,60`，`build_status` 全为 `READY`。
5. 最近分区重复业务 key 数为 `0`。

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

WMT-1 到 WMT-5 新增 `tests/test_gold_wealth_market_turnover_sensor.py` 和 `tests/test_gold_wealth_market_turnover_job.py`：

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
11. `19:50` 前 skip；`19:50` 后但 silver 五频度未全部 ready 仍 skip。
12. 只有部分 silver 频度 ready 时，全失败，不写部分结果。

WMT-6 需要补充：

1. job selection 包含 `gold_wealth_market_turnover`、`gold_wealth_market_turnover_integrity_check` 和 `prod_core_wealth_market_turnover`。
2. 不新增独立 prod sync job。
3. gold ready 但 prod sync missing 时，sensor 仍提交现有 job。
4. gold check failed 时，sensor 不允许写 prod。
5. prod sync 失败后不靠同一固定 run key 无限自动重试。

### 12.4 Governance / Static Gates

WMT-1 到 WMT-5 需要更新或新增：

1. active asset catalog 数量 +1。
2. catalog entry 与 asset definition metadata 一致。
3. catalog blocking checks 与实际 check 名称一致。
4. `DATASET_CHINESE_NAMES` 包含 `wealth_market_turnover`。
5. 静态门禁确认新资产不 import `src.biz`、SQLAlchemy model、Tushare resource、prod DB resource。
6. 静态门禁确认 sensor 不手写 run key/cursor，不一次提交多个分区。
7. 静态门禁确认生产代码不硬编码某个迁移日期或历史起点。
8. 静态门禁确认 `points_json` schema 是 `JSON`，不是 `VARCHAR`。

WMT-6 需要新增：

1. 静态门禁确认 `gold_wealth_market_turnover` asset 不 import prod write resource / prod DB helper。
2. 静态门禁确认现有 `ProdPostgresResource` 仍为只读。
3. 静态门禁确认没有新增独立 prod sync job。
4. 静态门禁确认 prod sync SQL 显式字段列表，不含 `select *`。
5. 静态门禁确认 prod sync 不写 `source/created_at/updated_at`。

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
| WMT-6 prod sync asset | 1 个 gold parquet，5 行 | prod PostgreSQL 1 个交易日分区 5 行 | gold 文件未通过契约、prod 连接失败、写后读回不一致即失败并 rollback |
| sensor hot path | 最近最多 10 个交易日，每日最多 5 个 silver readiness + 1 个 gold readiness | 0 或 1 run request | 上游未 ready、目标 failed、不一致状态均 skip |
| catalog/static gates | 只读 Python 定义 | 0 | catalog 与定义不一致则测试失败 |

拒绝策略：

1. 不允许 Python 逐行扫描全市场分钟线。
2. 不允许 sensor 深扫全历史。
3. 不允许 sensor 每 tick 发起多个交易日 run。
4. 不允许读 raw/prod DB 来补齐该 gold 资产。
5. WMT-6 prod sync 只允许读取 gold parquet 后写白名单 prod serving 表，不得反向影响 gold 计算。

## 14. 实施顺序

WMT-1 到 WMT-5 已按以下顺序落地：

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

WMT-6 建议推进顺序：

1. 只读复核 prod `core_serving.wealth_market_turnover_snapshot` 当前 schema、主键、约束和最近日期行数，确认与代码模型和 gold schema 一致。
2. 设计并落地 `ProdPostgresWriteResource` / `prod_postgres_write`，保持现有 `ProdPostgresResource` / `prod_postgres` 只读语义不变。
3. 新增 `prod_core_wealth_market_turnover` asset，依赖 `gold_wealth_market_turnover`，读取 gold parquet 并事务性 replace prod 分区。
4. 扩展 `gold_wealth_market_turnover_update_job` selection，仍不新增 job。
5. 扩展 sensor readiness：gold 和 prod sync 都 ready 才算链路 ready；gold ready 但 prod sync missing 时仍可提交同一 job。
6. 补齐单元测试、静态门禁和文档对账。
7. 单独审批后运行 `dg check defs`，已通过：`All component YAML validated successfully.` / `All definitions loaded successfully.`
8. 先对单个最近交易日做 prod write dry-run / transaction rollback 验证，再审批正式 apply。
9. 本轮不做历史 3030 个 gold 分区全量同步 prod；若未来要做，必须另起 P6B 历史 prod sync 计划，不得跟日更代码落地混在一起执行。

## 15. 风险和后续项

| 风险/问题 | 结论/建议 |
| --- | --- |
| `points_json` 的 DuckDB/Parquet 稳定类型需要实现时验证 | 已拍板使用 `JSON`。如果实现时无法稳定写出和校验 `JSON`，停止回报，不降级为 `VARCHAR`。 |
| 旧 serving 表目前由 `src/biz` 服务从 raw DB 生成 | WMT-1 到 WMT-5 曾拍板暂不同步；WMT-6 改为由 DG 下游 prod sync asset 写回同一张 `core_serving.wealth_market_turnover_snapshot`。Wealth API 查询逻辑本轮仍不改。 |
| WMT-6 是否单独写 job | 已确认不单独写 job；新增下游 `prod_core_wealth_market_turnover` asset 并纳入现有 `gold_wealth_market_turnover_update_job`，不写在 gold asset 函数里。 |
| prod sync 失败后的自动重试 | 同一 sensor 固定 run key 不适合无限重发失败 partition；第一版用 asset retry policy + 人工按 partition 重跑，若需要自动修复再单独设计 repair 入口。 |
| prod Postgres resource | 当前 `ProdPostgresResource` 是只读 resource，不能复用写库；WMT-6 新增 `ProdPostgresWriteResource` / `prod_postgres_write`，并完成配置审计。 |
| 当前 Wealth API 只消费 `freq=30` | 资产仍生成五个频度，保持原服务表完整契约；不要为了当前页面裁掉其他频度。 |
| 历史数据是否需要 backfill | 已拍板必须 backfill，范围对齐 `silver_stk_mins` 历史范围；执行前另列 backfill 计划。 |
| backfill 状态数据量 | 已拍板使用 direct lake bootstrap + 最近 20 个交易日 runless event，不为全历史生成 Dagster runs/check events。 |
| sensor 启用时间 | 已拍板日更窗口为 silver 日更时间 + 10 分钟，即当前 `19:50`；但仍必须等当日五频度 silver ready。 |
| 部分频度 ready | 已拍板全失败，不写部分结果。 |

## 16. 开发完成验收口径

WMT-1 到 WMT-5 代码完成后，至少满足：

1. `gold_wealth_market_turnover` 在 Dagster definitions 中可加载。
2. Catalog、metadata、schema、path template、checks 完全一致。
3. 单分区样本 materialize 产生 5 行 parquet。
4. `gold_wealth_market_turnover_integrity_check` 全绿。
5. sensor 默认停止，且只会在 silver 全 ready 后为一个 trade date 提交 run。
6. 新代码不读取 raw/prod DB/Tushare，不 import `src.biz` 旧服务。
7. 不影响现有 Wealth API、旧 `core_serving.wealth_market_turnover_snapshot` 表和现有 maintenance CLI。
8. 历史 bootstrap/runless 工具默认 dry-run；正式 lake 写入和 Dagster event 写入必须单独审批并显式 `--apply`。

WMT-6 完成后，新增验收：

1. `prod_core_wealth_market_turnover` active definition 可加载。
2. 同一 job 单分区运行顺序为 gold lake 生产、gold integrity check、prod serving sync。
3. prod 表目标分区写入 5 行，主键为 `(type, market, trade_date, freq)`，freq 集合为 `{1,5,15,30,60}`。
4. prod 行与 gold parquet 在业务字段上完全一致，`points_json` canonical hash 一致。
5. prod sync 失败不会破坏 gold lake 文件；prod DB 事务失败会 rollback。
6. 不新增独立 prod sync job；如新增 repair/backfill job，必须另起方案并经拍板。
7. `2026-06-24` 正式 apply 已通过，prod 表五行与 gold parquet 的 `points_json` canonical hash 一致。
8. `gold_wealth_market_turnover_update_job_sensor` 已停为 `STOPPED`；启用必须另行审批。

## 17. WMT-7 北交所收盘集合竞价校准方案

### 17.1 问题事实与根因

本节基于 `2026-08-24` 的正式 Lake 只读审计和同日 Tushare 真实请求抽样，修正原 WMT-1 的单源假设。

已确认事实：

1. 北交所当日 `1min` 分钟线存在 `15:00` 价格行，但该行 `vol=0`、`amount=0`；`14:59` 同样为零，`14:57/14:58` 仍有连续竞价成交。
2. 以同一股票、同一交易日逐代码计算：
   - `silver_stock_daily.vol * 100 - sum(silver_stk_mins.vol)`；
   - `silver_stock_daily.amount * 1000 - sum(silver_stk_mins.amount)`。
3. `2026-08-24` 共审计 `338` 只北交所股票，`334` 只存在正成交量差、`4` 只差额为零、负差额为零；缺失成交量合计 `8,753,250` 股。
4. Tushare 抽查 `920045.BJ`、`920571.BJ`、`920438.BJ`、`920087.BJ`、`920088.BJ` 时，`1/5/15/30/60` 五个频率的全日累计成交量均比日线少同一段收盘集合竞价成交。高频率的 `15:00` bar 虽然非零，但只包含此前聚合窗口，仍缺少该差额。
5. 个别北交所分钟 `15:00 close` 与日线 `close` 也可能不同，但 `gold_wealth_market_turnover` 只消费 `vol/amount`，本专项不修正 OHLC，也不修改分钟行情 Lake。

根因不是 Gold 聚合遗漏某个现有分钟点，而是源端分钟行情没有把北交所收盘集合竞价成交量和成交额放入分钟数据。原 WMT-1 仅对五频分钟文件求和，因而五个频率都会低估北交所全日成交。

### 17.2 目标、边界与生效链路

WMT-7 只修正 `gold_wealth_market_turnover` 的生成口径：

```text
silver_stk_mins[1/5/15/30/60, trade_date]
  + silver_stock_daily[trade_date]
  -> gold_wealth_market_turnover[trade_date]
  -> prod_core_wealth_market_turnover[trade_date]
  -> prod core_serving.wealth_market_turnover_snapshot
```

边界固定为：

1. 不修改 Raw/Silver 股票分钟线文件，不补写北交所 `15:00` 分钟 bar。
2. 不修改 `silver_stock_daily`。
3. 不修改 Gold/Prod 表 schema、主键、频率集合、API DTO 或 Wealth 前端。
4. 不把 Prod daily 表作为计算源；Gold 在本机直接读取同日 `silver_stock_daily`，Prod 只接收修正后的 Gold 五行结果。
5. 不修正 SH/SZ 分钟与日线之间的来源舍入差；该差异保持审计可见，但不进入北交所 closing-auction correction。
6. 不新增 asset check。继续使用现有单一 blocking check，防止 Dagster DB 增量膨胀。
7. 不新增日常 repair sensor。旧日期的 source 回刷由显式 bounded maintenance 入口处理，不让 sensor 扫描历史。
8. 历史修复不补 Gold materialization、Gold check 或 Prod materialization event；未来新日期继续由正常 job 自然写入 `v2` 事件。

### 17.3 源字段和单位合同

| 来源 | 读取字段 | 单位 | 用途 |
| --- | --- | --- | --- |
| 五频 `silver_stk_mins` | `ts_code, freq, trade_date, trade_time, vol, amount` | `vol=股`，`amount=元` | 保留原全市场分钟点，并计算每个北交所代码、每个频率的全日累计值。 |
| `silver_stock_daily` | `ts_code, trade_date, vol, amount` | `vol=手`，`amount=千元` | 只提供北交所同日成交量/成交额总量事实。 |

转换必须在 DuckDB `DECIMAL` 表达式中完成：

```text
daily_vol_shares = silver_stock_daily.vol * 100
daily_amount_yuan = silver_stock_daily.amount * 1000
```

禁止读取 `open/high/low/close/pre_close/change_amount/pct_chg`，避免把本专项扩大成行情价格修复。

### 17.4 五频独立校准公式

对每个频率 `f in {1,5,15,30,60}`、每个北交所代码 `c` 独立计算：

```text
minute_vol(c, f) = sum(minute.vol)
minute_amount(c, f) = sum(minute.amount)

residual_vol(c, f) = daily_vol_shares(c) - minute_vol(c, f)
residual_amount(c, f) = daily_amount_yuan(c) - minute_amount(c, f)

residual_vol(f) = sum(residual_vol(c, f))
residual_amount(f) = sum(residual_amount(c, f))
```

然后只修改该频率聚合后的 `15:00` 市场点：

```text
corrected_15_00_vol(f) = original_15_00_vol(f) + residual_vol(f)
corrected_15_00_amount_yuan(f) = original_15_00_amount_yuan(f) + residual_amount(f)
```

重要语义：

1. `1min` 原 `15:00` 成交为零时，校准后该点承载北交所 closing-auction residual。
2. `5/15/30/60` 原 `15:00` 点包含已有聚合窗口，必须在原值上增加 residual，不能覆盖原值。
3. 每个频率都从自身分钟总量反算 residual。禁止先算 `1min` residual 再复制给另外四个频率，即使当前抽样结果相等。
4. 不新增时间点；若源聚合没有唯一 `15:00` 点则 fail closed。
5. `securityCount`、`security_count` 和 `source_row_count` 仍描述原分钟源行与代码覆盖，不因日线校准而增加。
6. `points_json`、`total_amount`、`total_vol` 必须从同一份 corrected point rows 生成，禁止摘要与曲线使用两套公式。
7. `build_version` 从 `v1` 升级为 `v2`，`build_note` 固定为 `bse_close_auction_reconciled_from_silver_stock_daily`。

校准前必须满足：

1. 同日五频分钟文件和日线文件全部存在。
2. 日线与分钟源的 `trade_date` 等于目标分区。
3. 每个来源的业务主键唯一，数量和金额非空且非负。
4. 每个频率的北交所代码集合与日线北交所代码集合完全一致。
5. 每个北交所代码在每个频率恰好有一个 `15:00` 源行。
6. `residual_vol(c, f) >= 0`；存在负值立即失败。
7. 对 `residual_vol(c, f) > 0` 的代码，`residual_amount(c, f)` 必须大于零。
8. 每个频率的聚合 `residual_amount(f)` 必须非负。代码级微小正负舍入可以相互抵消，但必须记录数量和有限样本。

以上门禁继续适用于日常正常链路。历史源缺口不得通过放宽正常 writer/check 解决；历史维护的可恢复、低频聚合恢复和跳过规则由第 18 节单独约束。

校准后必须满足：

1. 北交所 `total_vol` 与日线换算后的成交量完全一致。
2. 北交所 `total_amount` 与日线换算后的成交额按 Gold `DECIMAL(20,2) thousand_yuan` 输出精度一致。
3. SH/SZ 的分钟聚合 hash、总量和点数组不因 WMT-7 改变。
4. 五行频率集合仍为 `{1,5,15,30,60}`，每行时间键集合不变。

### 17.5 Asset、分区和日常触发

`gold_wealth_market_turnover` 继续使用 `cn_a_stock_mins_silver_trade_days`，但新增同日 `silver_stock_daily` 依赖。由于其分区定义是 `cn_a_stock_trade_days`，依赖必须显式使用 `IdentityPartitionMapping`，不能靠不同 dynamic partition set 的隐式映射。

日常 sensor 在原五频 minute readiness 之外增加两道选定日期门禁：

1. 目标日期已注册到 `cn_a_stock_trade_days`。
2. `silver_stock_daily[trade_date]` 的 materialization 和既有 blocking checks ready。

门禁只检查已选中的 first-not-ready 日期，不对最近 10 日逐日扫描 stock daily event history。Gold lake readiness 仍在一个 DuckDB connection 内，对最近最多 10 日按新公式重算并比较；因此同日 daily source 变化会使旧 `v1` Gold 变为 not ready。

若 Gold 文件已存在但按新源口径不一致，日常 sensor 保持 fail closed，不自动覆盖旧文件；WMT-7 首次切换和旧日期恢复统一走维护入口。

现有 job 仍只选择：

```text
gold_wealth_market_turnover
gold_wealth_market_turnover_integrity_check
prod_core_wealth_market_turnover
```

不得把 `silver_stock_daily` 或五频 `silver_stk_mins` 加入 job selection。

### 17.6 单一 Check 和 readiness 语义

`gold_wealth_market_turnover_integrity_check` 名称和数量保持不变，内部仍为两个阶段：

1. `file_contract`：五行、schema、主键、JSON、日期、频率、`build_version=v2`。
2. `recomputed_from_sources`：用同日五频分钟与日线按第 17.4 节重算并逐频比较。

check metadata 只保留低基数摘要：

- daily/minute source path count；
- 北交所代码数；
- 五频 residual vol/amount；
- 负 residual 数量；
- 代码集合缺失数量与有限样本；
- mismatch 数量与有限样本；
- build version 和 correction method。

不得增加逐频 check、逐代码 check 或完整代码列表。

### 17.7 历史 Gold/Prod 恢复设计

本节原设计假设五个分钟频率均具备完整北交所源代码集合。`2026-08-25` 正式 plan 已证明该假设对部分旧日期不成立，因此原“直接全量 WMT candidate”执行路径已停止，历史分区选择与恢复顺序由第 18 节 WMT-7R 取代。正常日常链路仍保持本节的严格五频门禁。

WMT-7R 完成上游恢复后，Gold/Prod 历史恢复仍按以下安全步骤执行：

1. **只读 plan**：从 `2021-11-15` 起，在五频 minute、stock daily 和 Gold 分区交集中筛选日线含 `.BJ` 的日期；冻结日期集合、源文件 fingerprint 和 plan hash。
2. **候选生成**：每批最多 20 个交易日，串行生成到 `/Volumes/datasource/data_lake_staging/wealth_market_turnover/operation_id=<plan_hash>/`，不得在正式 Lake 目录生成 `.tmp`。
3. **候选审计**：按批做聚合对账并抽查首日、中间日、最新日及异常 residual 样本。单个审计动作最长 5 分钟，不做无收益的全盘逐行 Python 审计。
4. **原子 promote**：候选完整通过后，使用同文件系统 `os.replace()` 逐分区替换正式 Gold；中断时只允许使用同一 plan/checkpoint 续跑。
5. **正式 Gold 抽样/统计验收**：核对文件数、五行频率、`build_version=v2`、北交所总量和有限样本；不重新跑一遍全量深审计。
6. **Prod 分批回写**：复用现有事务性 `replace_prod_core_wealth_market_turnover_partition(...)`，每分区 delete/insert/read-back/commit；失败只回滚当前分区。
7. **控制面保持不变**：不调用现有 runless event 工具，不为任何历史修复分区补 Gold materialization、Gold check 或 Prod materialization event；修复前后的 Dagster run/event 数量必须保持不变。

正式恢复不得与 daemon、sensor、人工同资产 run 并发。任何源 fingerprint 变化、候选损坏、正式目标并发变化或 Prod read-back mismatch 都必须停止。

历史事件不补录的影响已经接受并固定：

1. Gold Lake 和 Prod serving 数据按 `v2` 变为正确事实，Wealth API 和页面读取修正后的数据。
2. 历史分区在 Dagster UI 中继续显示原 materialization 时间、原 `v1` metadata 和原 check event，不代表物理文件仍是 `v1`。
3. 原历史 materialization/check event 不删除，因此这些分区不会被视为从未物化，也不会因本次修复自动触发重跑。
4. 日常 sensor 的新日期选择、未来 Gold 生成和 Prod 同步不依赖补写历史事件；代码切换后的新分区由正常 job 产生完整 `v2` 事件。
5. 若未来确实需要 Dagster UI 精确证明某个历史分区已按 `v2` 重建，必须另立事件治理专项，不能在 WMT-7 中顺带补写。

### 17.8 性能门禁

| 路径 | 输入上限 | 计算口径 | 不可接受 |
| --- | --- | --- | --- |
| 日常 writer | 同日五频 minute + 1 个 stock daily 文件 | 一个 DuckDB set-based pipeline；只投影必要列 | Python 逐股票/逐分钟循环、读取全历史、调用 Tushare/Prod daily |
| Gold readiness | 最近最多 10 日，最多 50 个 minute + 10 个 daily + 10 个 Gold 文件 | 每 tick 一个 DuckDB connection，返回聚合状态 | Dagster 全历史扫描、多个 connection、完整代码列表进入 cursor |
| stock daily event gate | 只检查已选中的 1 个日期 | 一次 bounded readiness 调用 | 最近 10 日逐日读取全部 check history |
| 历史修复 | 每批最多 20 日，串行 | staging、聚合审计、原子 promote | 全历史装入 Python、直接覆盖正式文件、单个审计动作超过 5 分钟 |
| Prod 回写 | 每分区固定 5 行 | 单分区事务和 read-back | 跨分区大事务、跳过 Gold 契约校验 |
| Dagster event | 历史修复新增 0 条 | 保留原事件，未来日期由正常 job 写事件 | 调用 runless event、补 Gold/Prod materialization 或 check event |

### 17.9 WMT-7 验收标准

代码阶段必须满足：

1. `gold_wealth_market_turnover` 明确依赖同日 `silver_stock_daily`，definitions 可加载。
2. 五频均独立计算 residual，并只修改各自 `15:00` 聚合点。
3. SH/SZ 输出不变，北交所 corrected totals 与 daily source 对齐。
4. Gold schema 和 Prod schema 不变，`build_version=v2`。
5. check 数量仍为一个，job 名称、sensor 名称、run key 和 Prod asset 名称不变。
6. missing daily、不同分区、代码集合不一致、负成交量 residual、缺 15:00、输出不一致全部 fail closed。
7. sensor 在 stock daily 未注册或未 ready 时不提交 Gold run。
8. normal writer 和 history writer 都只在 staging 审计通过后原子替换。
9. 不修改 Wealth API、首页成交额总览或成交额洞察的前端计算。

正式恢复阶段必须另外满足：

1. 受影响 Gold 分区全部为 `v2`，无 staging 残留。
2. Prod 对应分区与 Gold 五行及 `points_json` hash 一致。
3. Dagster runs、materialization events 和 check events 数量未因历史修复增加。
4. 历史 UI metadata 仍可能显示 `v1` 的已知取舍已记录，不把它误判为物理数据未修复。
5. 当日成交额总览与成交额洞察在各自展示精度下不再因北交所 closing-auction 缺口产生差异。

### 17.10 代码交付与正式恢复边界

截至 `2026-08-25`：

1. WMT-7 的 `v2` source bundle、五频 set-based residual、run-scoped staging、单一 check、Gold readiness、stock daily selected-date gate 和五阶段历史维护入口均已完成。
2. 本地目标回归结果为 `169 passed`、`147 subtests passed`；语法/import 检查通过。
3. 正式 Lake 路径层面的分区覆盖完整，但行级只读审计发现多个旧日期的 Raw/Silver 北交所代码集合为空或不完整；“文件存在”不能再等同于“WMT-7 source ready”。详细事实见第 18 节和独立缺口备案。
4. 正式历史 plan `391beab59283c5594dc56884c581a98bd5187dbccb76955143dfb1276900f1c2` 在首个分区触发 `bse_code_set_mismatch`，因此没有生成 candidate、没有 promote、没有 Prod publish。
5. 本轮没有运行 `dg`、job、sensor、runless event，也没有写正式 Lake、Prod 或 Dagster DB。
6. 正式恢复必须先完成第 18 节 WMT-7R；不得重新执行原全量 plan 绕过源集合门禁。在 WMT-7R、Gold candidate/promote 和 Prod publish 全部验收前，不得把 WMT-7 标记为数据恢复完成。

## 18. WMT-7R 北交所历史分钟源缺口恢复方案

### 18.1 目标与事实来源

WMT-7R 解决的不是 WMT 计算公式，而是历史北交所分钟源覆盖不一致。事实备案固定在：

`../reports/stk-mins-bse-historical-source-gap-audit-2026-08-25.md`

恢复目标按优先级固定为：

1. 源站当前已补齐的历史数据，从 Raw 开始恢复，并按真实变化向 Silver、QFQ、MACD/KDJ state、分钟九转、WMT 和 Prod 传播。
2. 源站仍为空的旧日期，不伪造 `1min`，不把日线差额硬塞进分钟行情。
3. 若完整 `1min` 能按现有 Silver 聚合合同生成缺失的粗频率，则只恢复 Silver 粗频率，不伪造对应 Raw 粗频率。
4. 既无原生源、也无完整低频源可聚合的日期/频率，保留原事实并跳过；不因旧历史缺口阻塞其它可恢复频率。
5. 正常日常 sensor/writer/check 继续严格 fail closed，不引入历史例外。

### 18.2 四类恢复判定

每个 `trade_date + freq` 必须在写入前归入且只能归入以下一种模式：

| 模式 | 判定 | 动作 |
| --- | --- | --- |
| `SOURCE_RECOVERABLE` | Tushare 当前返回完整 expected 历史 source code set，日期、频率、schema、主键和交易时段均合法 | 从 Raw candidate 开始恢复，再生成 Silver candidate |
| `SILVER_FALLBACK_RECOVERABLE` | 原生粗频率仍为空，但同日 Raw `1min` 具备完整 expected code set，且每个 code-day 恰有 241 个合法点 | 保留 Raw 粗频率原事实，使用现有 Silver set-based fallback 生成粗频率 |
| `SOURCE_EMPTY_SKIP` | 源站仍为空，且没有完整低频源可聚合 | 不写 Raw/Silver；该频率在 WMT 历史维护中保留原结果并记录跳过原因 |
| `PARTIAL_BLOCKED` | 只返回部分 expected code set，或 identity/date/key/session 任一合同不完整 | 整个日期/频率停止，不接受部分覆盖；先恢复缺失代码或转入明确跳过清单 |

expected historical source code set 不能直接使用当前 `920xxx.BJ`。必须以同日 `silver_stock_daily` 的 latest code set 为业务集合，再按 `stock_identity_map.valid_from/valid_to` 反查历史 `source_ts_code`；Raw 保存历史源代码，Silver 才规范化为 latest code。

模式是审计结论，不是根据“粗频率缺失”自动推导。任何日期在完成模式审计前只能标记为 `UNCLASSIFIED_CANDIDATE`。其中 `SILVER_FALLBACK_RECOVERABLE` 必须同时满足：

1. 同日 Raw `1min` 北交所 latest code set 与 `silver_stock_daily` expected set 完全一致。
2. 每个 expected code-day 恰有 `241` 行、`241` 个唯一 `trade_time`。
3. 时间集合精确等于 `09:30..11:30` 与 `13:01..15:00`，不存在缺点、重复点或越界点。
4. 1m schema、主键、OHLC、`vol/amount` 和 exchange 合同全部通过。
5. 目标粗频率对该 code-day 是“整只代码完全缺失”；若只缺部分 bar，不能使用 missing-source fallback，必须标记 `PARTIAL_BLOCKED`。
6. 使用现有 Silver writer 生成的 candidate 通过窗口行数、schema、主键、日期、代码集合和回读校验。

因此，事实备案中按代码数量识别出的 2025 日期只能是 fallback 候选，不是已经确认的 `SILVER_FALLBACK_RECOVERABLE`。

### 18.3 源站探测与性能边界

源站探测只为决定恢复模式，不做无边界全历史扫描：

1. `tushareMCP` 只用于开发期、方案期的交互式抽样，证明接口当前是否可能返回某个代码/日期/频率；MCP 结果不得直接生成 Raw candidate，也不得成为正式恢复的执行依赖。
2. 正式 source probe 和 Raw 数据获取必须由仓库运行时的 `TushareResource` 调用 `stk_mins`，复用项目 token、显式 fields、有界分页、限速、重试、报告和 checkpoint。
3. 正式代码不得 import、调用或封装 `tushareMCP`；MCP 不是可部署的数据管道组件。
4. 对连续日期段，正式 probe 按 `source_ts_code + freq + bounded date range` 请求，禁止 `date × code × freq` 三重循环。
5. 使用共享 `TushareRequestPolicy`：最小请求间隔 `0.13s`、最多重试 `3` 次、`1/2/4s` 指数退避、单批最多 `1,200` 次请求、最长 `300s`；每个探测批次及其对账最长 5 分钟。
6. 只有 `TushareResource` 实际返回的规范化 `code-date` 集合与 expected 集合完全一致，才能标记 `SOURCE_RECOVERABLE`。
7. MCP 抽样命中只证明“值得进入完整有界探测”，不能直接把整段日期标记为可写。
8. 结果冻结为不可变 manifest，包含模式、expected/returned code count、有限缺口样本、source request fingerprint 和文件 fingerprint。

### 18.4 Raw 与 Silver 恢复

Raw 恢复只处理 `SOURCE_RECOVERABLE`：

1. 在 `/Volumes/datasource/data_lake_staging` 生成候选，基于现有 Raw 文件合并北交所历史 source rows。
2. SH/SZ、非目标日期和非目标代码必须逐字节或 canonical hash 不变。
3. 禁止直接调用当前会原位修改目标的 repair helper；正式恢复入口必须是 `plan -> candidate -> audit -> promote`。
4. candidate 通过 schema、主键、日期、频率、交易时段、expected source code set 和 source-row hash 后，才按单分区 `os.replace()` 原子提升。
5. 任一 source code 空结果、部分结果或目标并发变化均停止该日期/频率。

Silver 恢复按“实际受影响日期”执行：

1. Raw `1min` 或同频 Raw 被恢复后，使用现有 `write_silver_stk_mins_partition(..., output_path_override=...)` 为同日五频生成候选。
2. 在生成 fallback candidate 前，必须先输出独立的 1m eligibility audit；未同时通过代码集合、逐代码 241 点、精确时间集合和字段合同的日期不得进入 `SILVER_FALLBACK_RECOVERABLE`。
3. `SILVER_FALLBACK_RECOVERABLE` 只在上述 eligibility audit 通过后启用；由现有 DuckDB set-based writer 聚合，不新增第二套公式。
4. 每个频率比较 candidate 与正式文件 canonical hash，只 promote 真正变化的 Silver 文件。
5. `2025-09-03` 必须先恢复历史 source code `872392.BJ` 的 Raw `1min`，随后重新执行完整 eligibility audit；不能因为单代码 MCP 抽样已有数据就直接派生粗频率。
6. `SOURCE_EMPTY_SKIP` 不生成空文件、不用日线补分钟、不修改现有 Silver。

### 18.5 下游影响和恢复顺序

下游不得按“计划范围”盲目全量重建，只消费实际 changed Silver manifest。

| 实际变化源 | 必须评估/恢复的下游 |
| --- | --- |
| 任一 `silver_stk_mins` 1/5/15/30/60 | 同日 `gold_wealth_market_turnover`，随后回写 Prod serving |
| Silver 1m | QFQ 1m、5m |
| Silver 5m | QFQ 15m、30m |
| Silver 30m | QFQ 60m、90m |
| Silver 60m | QFQ 120m |
| Silver 15m | 无 QFQ consumer；仅影响 WMT 15m |
| 任一 changed QFQ 频率 | 对应频率 MACD/KDJ 与递推 state，从最早变化日期重建至当前 frontier |
| changed QFQ 30/60/90/120 | 对应分钟九转，从最早变化日期重建至当前 frontier |

恢复顺序固定为：

```text
bounded source probe
  -> Raw candidate/audit/promote
  -> Silver candidate/audit/promote
  -> freeze changed Silver manifest
  -> bounded QFQ rebuild
  -> MACD/KDJ + state forward rebuild
  -> minute nineturn forward rebuild
  -> WMT mixed-mode historical rebuild
  -> Prod transactional publish
  -> control-plane reconciliation
```

QFQ 不使用 factor repair job 猜范围，因为本次变化来源是分钟 bar 修复，不是 adj factor 变化。应复用 canonical/history maintenance 计算口径，并仅重写 manifest 命中的北交所 code/date/stock-year 文件。

### 18.6 源站仍为空时的 WMT 处理

WMT 正常日常 writer 继续要求五频完整，不接受降级。历史维护入口则逐频处理：

1. 完整恢复后的频率按 WMT-7 `v2` 公式重建。
2. `SOURCE_EMPTY_SKIP` 频率保留现有 Gold 行及原构建语义，不向 `15:00` 注入无法由分钟源解释的日线差额。
3. 同一 Gold 分区允许在历史维护报告中出现“已重建频率 + 保留频率”，但跳过频率必须来自冻结 manifest；禁止运行时临时决定。
4. `PARTIAL_BLOCKED` 不允许生成 Gold candidate，因为部分代码比完全跳过更容易造成静默误差。
5. 若某日五频全部 `SOURCE_EMPTY_SKIP`，该 Gold 分区保持不变，也不重复发布 Prod。
6. Prod 只发布 Gold 实际发生变化的日期，逐分区事务写入并 read-back。

这一历史例外不进入正常 asset check/readiness，不扩大 sensor 热路径，也不把“旧日期已知降级”伪装成完整 `v2`。

### 18.7 Dagster 事件口径

事件按数据安全而非“历史补齐好看”处理：

1. Raw、Silver、QFQ 和 WMT 的旧日期不补全历史 materialization/check event。
2. WMT/Prod 历史恢复继续新增零条 event，与第 17 节保持一致。
3. MACD/KDJ state 和分钟九转属于递推数据；若 forward rebuild 实际改写最近 20 个交易日，则只对这些实际变化的最近 20 日刷新 materialization/check，确保后续日常 previous-state/readiness 读取的是新物理事实。
4. 第 3 项必须单独审批；若 recent-window canonical hash 未变化，则事件写入为零。
5. 不删除旧事件，不补全历史事件，不触碰 dynamic partitions、runs 或 run_tags。

### 18.8 分阶段执行和停止条件

1. **R0 只读计划**：使用 `TushareResource` 生成 source mode manifest，并对所有 fallback 候选执行逐代码 241 点 eligibility audit；同时冻结文件 fingerprint、changed-downstream 预计映射和磁盘/耗时预算。MCP 抽样不计作 R0 验收。
2. **R1 Raw**：只处理 `SOURCE_RECOVERABLE`，每批 candidate 审计不超过 5 分钟。
3. **R2 Silver**：处理 Raw 变化及 `SILVER_FALLBACK_RECOVERABLE`，冻结 actual changed manifest。
4. **R3 QFQ**：按第 18.5 节映射做 bounded rebuild；没有 changed source 的频率不动。
5. **R4 指标/九转**：按 affected code/freq 从最早变化日递推至 frontier，按年份/频率分批。
6. **R5 WMT/Prod**：逐频重建可恢复行，保留 source-empty 行，Prod 只发布 changed partitions。
7. **R6 控制面**：只读对账；如需最近 20 日事件刷新，另行批准后执行。

任一阶段遇到以下情况立即停止：source 集合部分返回、identity 映射不唯一、candidate 改变非目标市场数据、正常 writer/check 被放宽、审计超过 5 分钟、正式目标并发变化、递推范围无法确定、或需要通过猜测补数据。

### 18.9 验收标准

1. 每个 gap 都有唯一 mode 和 source evidence，不存在未分类日期/频率。
2. 源站已补齐项从 Raw 开始恢复，Raw 保存历史 source code，Silver 输出 latest code。
3. 可由完整 1m 聚合的粗频率在 Silver 补齐，Raw 粗频率不伪造。
4. source-empty 旧日期没有新增 1m 行，也没有用 daily 合成分钟 bar。
5. changed Silver 到 QFQ、指标/state、九转、WMT/Prod 的传播清单可逐项对账。
6. SH/SZ 和非目标日期 canonical hash 不变。
7. WMT 可恢复频率与日线北交所总量对齐；跳过频率保留既有值并在报告中可见。
8. 正常日常链路、asset/check/job/sensor/run key 和 API contract 无回退。
9. 无 Kopia、无正式 Lake sibling temp、无无边界 Tushare 请求、无全历史 Python 扫描。
10. 未经单独批准，不执行正式 Lake、Prod 或 Dagster event 写入。
