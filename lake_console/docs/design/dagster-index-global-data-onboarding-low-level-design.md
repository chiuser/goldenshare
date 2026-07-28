# `index_global` 国际指数数据集低层设计（LLD）

## 1. 目标与边界

本文是 [`dagster-index-global-data-onboarding-plan.md`](./dagster-index-global-data-onboarding-plan.md) 的代码级设计。目标是把 Tushare `index_global` 接入 Dagster Lake，形成 Raw/Silver 两层、自然日分区、同日五阶段刷新和低开销自动触发链路。

本 LLD 不实现 Gold 指标，也不在本阶段执行正式 Bootstrap、Dagster event 补录或 sensor 启用。

硬边界：

- 不复用 `cn_a_index_trade_days`；
- 不复用 `index_trade_day_sensor`；
- 不复用 A 股指数 Prod DB source readiness；
- 不按 21 个指数代码逐个请求；
- 不以 21 个指数全覆盖作为 blocking check；
- 不在 sensor 热路径调用 Tushare、Prod DB 或 Dagster event history；
- 不新增 summary asset、manifest asset、readiness asset 或状态表；
- 不通过追加写入已有 Parquet；
- 不在 staging 未通过时覆盖正式目标文件。

## 2. 当前代码事实与影响面

### 2.1 不能直接复制的实现

现有 [`index_daily.py`](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/assets/index_daily.py) 的 `raw_index_daily`：

- 依赖 `ProdPostgresResource`；
- 使用 A 股 `cn_a_index_trade_days`；
- 使用注册的 A 股指数代码集合；
- 对代码集合做覆盖检查；
- Silver 通过 `change -> change_amount` 标准化。

这条链路服务 A 股指数日线，不能作为 `index_global` 的 source、calendar 或 coverage 模型。

### 2.2 可复用的基础能力

可以复用，但必须逐项确认语义：

- `TushareResource.call()` 的请求入口；
- bounded request policy 的限流、重试、分页和预算对象；
- `LakeRootResource` 和 DuckDB 连接；
- `cn_*` dynamic partition 的注册 API 形态；
- `build_asset_update_run_key(subject, unit_id)`；
- `build_run_request(...)`、`build_sensor_cursor(...)`；
- Parquet staging 和原子替换的既有工具。

不复用：A 股指数 source readiness、A 股指数 code coverage readiness、Prod DB 读取、A 股连续性 selector。

### 2.3 数据卡和代码登记落点

本 LLD 的正式名称固定为“国际指数日线”，稳定 `dataset_id=index_global`。当前代码尚无以下任何实现，必须按顺序补齐：

| 目标 | 代码落点 |
| --- | --- |
| 中文名称 | `orchestrator/defs/catalog/name_mapping.py` 增加 `index_global` |
| 路径 | `orchestrator/defs/paths.py` 增加 `raw_index_global_path`、`silver_index_global_path` |
| schema | `orchestrator/defs/run_contracts/asset_column_schemas.py` 增加 Raw/Silver schema |
| 统一合同 | `orchestrator/defs/run_contracts/index_global.py` 集中定义代码集合、phase、typed config、预算和 metadata 口径 |
| partition | `orchestrator/defs/partitions.py` 增加唯一 `cn_global_index_trade_days` |
| Catalog | `orchestrator/defs/catalog/lake_assets.py` 增加两个 `PartitionModel`、两个 `PartitionModelDefinition` 和两个 `LakeAssetCatalogEntry` |
| governance | `tests/test_asset_check_incremental_governance.py` 增加两个 core check 的治理映射 |
| asset/check/job/sensor | 分别放在 `orchestrator/defs/assets/`、`checks/`、`jobs/`、`sensors/`，由 `orchestrator/definitions.py` 的 `load_from_defs_folder` 自动装配 |

Catalog 事实必须与 definition metadata、tags、schema、path、partition model、blocking checks、write/event/performance policy 一致。不存在“先写 asset，后补 catalog”的阶段。

两个 asset 的 decorator 必须使用：

- `build_asset_tags(layer=AssetLayer.RAW/SILVER, data_domain=DataDomain.INDEX_TOPIC)`；
- `build_asset_definition_metadata(dataset_id="index_global", source_system=SourceSystem.TUSHARE, data_contract=..., column_schema=..., path_template=...)`；
- Raw 额外登记 `source_api="index_global"`、`source_category_path="指数专题"`、`source_doc="docs/sources/tushare/指数专题/0211_国际指数.md"`；
- materialization 只使用 `build_materialization_metadata(...)`，记录 URI、行数、观测列和有限的请求/merge摘要，不把完整返回行写入 metadata。

治理映射必须与 catalog 同步写入，并固定为：`raw_index_global.raw_index_global_core_check` 和
`silver_index_global.silver_index_global_core_check` 均使用
`MOVE_TO_SENSOR_LAKE_READINESS`，`participates_in_sensor_readiness=False`，
`retention_allowed=True`，`implementation_phase="INDEX_GLOBAL_P5"`。
`False` 的含义是实际 sensor 只使用 DuckDB lake readiness，不从 Dagster check history 读取状态；core check 仍是 blocking check，负责当前分区文件事实和 UI 状态。`retention_allowed=True` 只表示普通历史 check 遵循最近 20 个自然日的保留治理，latest check、latest materialization 和运行元数据仍受 retention 安全规则保护。

### 2.4 七项已拍板事项的实现闭环

1. retry 信息只存在 typed run config，使用统一 builder；run tags 不承载业务 retry 信息。
2. 数据集中文名固定为“国际指数日线”，`dataset_id` 固定为 `index_global`；data card、catalog、partition model、schema、governance mapping 必须在 definitions 可加载前完成。
3. 所有 sensor cursor 只能经 `build_sensor_cursor()` 生成，顶层字段和 decision 只能服从现有 cursor contract。
4. Silver 只由 `americas` 成功的 Raw run-status sensor 触发；不通过文件存在或 check history 猜阶段完成。
5. phase merge 临时 rank 固定为既有行 `0`、当前阶段行 `1`，不写入 Parquet，不引入 `probe_sequence`。
6. late-empty 使用独立、默认 `STOPPED` 的 sensor，最近 3 日、每日期最多 2 次，超限转离线审计。
7. 配置集中在 `run_contracts/index_global.py`，Bootstrap 采用最多 20 日串行批次，并在执行前后记录请求、页数、重试、行数、耗时、磁盘和内存预算。

## 3. 数据合同

### 3.1 Raw 合同

Asset：`raw_index_global`

分区：`cn_global_index_trade_days`

物理路径：

```text
raw/index_global/trade_date={trade_date}/part-000.parquet
```

列顺序固定：

| 列 | 类型 | 语义 | NULL |
| --- | --- | --- | --- |
| `ts_code` | `VARCHAR` | Tushare 国际指数代码 | 否 |
| `trade_date` | `VARCHAR` | `YYYYMMDD` 源日期 | 否；空文件无行 |
| `open` | `DOUBLE` | 开盘点位 | 允许 |
| `close` | `DOUBLE` | 收盘点位 | 允许 |
| `high` | `DOUBLE` | 最高点位 | 允许 |
| `low` | `DOUBLE` | 最低点位 | 允许 |
| `pre_close` | `DOUBLE` | 前收盘点位 | 允许 |
| `change` | `DOUBLE` | 源站涨跌点位 | 允许 |
| `pct_chg` | `DOUBLE` | 源站涨跌幅 | 允许 |
| `swing` | `DOUBLE` | 振幅 | 允许 |
| `vol` | `DOUBLE` | 成交量 | 允许 |
| `amount` | `DOUBLE` | 成交额 | 允许 |

Raw 必须保留源字段名，不把 `change` 在 Raw 层改成 `change_amount`。

### 3.2 Silver 合同

Asset：`silver_index_global`

分区和物理路径：

```text
silver/index_global/trade_date={trade_date}/part-000.parquet
```

列顺序固定：

| 列 | 类型 | 处理 |
| --- | --- | --- |
| `ts_code` | `VARCHAR` | trim、规范化、保留源代码 |
| `trade_date` | `DATE` | `YYYYMMDD -> DATE` |
| `open` | `DOUBLE` | 保留 |
| `high` | `DOUBLE` | 保留 |
| `low` | `DOUBLE` | 保留 |
| `close` | `DOUBLE` | 保留 |
| `pre_close` | `DOUBLE` | 保留 |
| `change_amount` | `DOUBLE` | `change` 重命名 |
| `pct_chg` | `DOUBLE` | 保留 |
| `swing` | `DOUBLE` | 保留 |
| `vol` | `DOUBLE` | 保留 |
| `amount` | `DOUBLE` | 保留 |

`change_amount` 表示涨跌点位，不表示成交金额；`amount` 继续表示成交额。

### 3.3 业务主键

Raw 和 Silver 主键都是：

```text
(ts_code, trade_date)
```

空分区没有业务行，但仍必须有固定 schema 和固定物理分区路径。

## 4. 日期和阶段模型

### 4.1 自然日分区

定义：

```python
GLOBAL_INDEX_PARTITION_SET_NAME = "cn_global_index_trade_days"
GLOBAL_INDEX_START_DATE = "2022-01-01"
GLOBAL_INDEX_PARTITION_REGISTRATION_BATCH_SIZE = 2000
```

代码落点固定为现有集中定义文件：

```text
orchestrator/defs/partitions.py
```

在该文件中新增唯一的定义：

```python
cn_global_index_trade_days = dg.DynamicPartitionsDefinition(
    name=GLOBAL_INDEX_PARTITION_SET_NAME,
)
```

不得另建第二个同名 `DynamicPartitionsDefinition`，不得把分区定义放到资产模块中，避免不同 definition 引用同名分区时出现边界不一致。

注册逻辑：

1. 读取系统当前北京时间日期；
2. 将 `2022-01-01..today` 规范化为 ISO 日期；
3. 在内存中生成候选日期，并与一次读取的已注册集合做 set difference；
4. 按日期排序，截取不超过 `GLOBAL_INDEX_PARTITION_REGISTRATION_BATCH_SIZE` 的缺失日期；
5. 通过一次 dynamic partition add request 幂等注册这一批日期；
6. 剩余缺失日期由后续 tick 继续注册；
7. 不查询 Tushare，不判断指数返回行数；
8. 不调用 A 股分区注册逻辑。

注册性能门禁：

- 每个 tick 最多一次 `get_dynamic_partitions`；
- 每个 tick 最多一个 dynamic partition add request；
- 不逐日调用 Dagster API；
- 不扫描 lake、event history 或 source 数据；
- 初始补注册必须受批量上限约束，不能把无限历史日期一次性提交给 Dagster DB；
- cursor 只记录 `registered_count`、`candidate_count`、`missing_count`、`added_count`、`elapsed_ms` 和 ASCII reason code，不写完整日期列表。

分区注册 sensor 在独立模块中实现：

```text
orchestrator/defs/sensors/global_index_partition_sensor.py
```

分区注册 sensor 不负责提交 Raw materialization run。

### 4.2 阶段到目标日期映射

阶段配置必须是不可变常量，而不是散落在 sensor 的 if/else 中：

```python
GLOBAL_INDEX_PROBE_PHASES = (
    ProbePhase("asia_1", "14:40", 0),
    ProbePhase("asia_2", "16:20", 0),
    ProbePhase("asia_3", "18:30", 0),
    ProbePhase("europe", "00:45", -1),
    ProbePhase("americas", "05:30", -1),
)
```

其中 offset 是相对于北京时间当前自然日的目标日期偏移：

- `asia_1/asia_2/asia_3` 查询当天 `trade_date`；
- `europe/americas` 在次日凌晨运行，查询前一天 `trade_date`。

例如：

```text
2026-07-28 14:40 -> trade_date=20260728, phase=asia_1
2026-07-28 18:30 -> trade_date=20260728, phase=asia_3
2026-07-29 00:45 -> trade_date=20260728, phase=europe
2026-07-29 05:30 -> trade_date=20260728, phase=americas
```

阶段时间是最早触发窗口，不是对 Tushare 发布时刻的硬保证。每个阶段必须在结束后留出缓冲，并允许 API bounded retry。

### 4.3 Typed Run Config 与配置审计

统一配置放在 `orchestrator/defs/run_contracts/index_global.py`，由 Raw job、Raw phase sensor、failed-run retry sensor、late-empty sensor 和 Bootstrap planner 复用。不得在这些模块分别定义同名常量。

```text
trade_date: str
probe_phase: Literal["asia_1", "asia_2", "asia_3", "europe", "americas", "late_empty"]
slot_key: str
attempt: int                 # 原始 phase 为 0，failed-run retry 为 1/2
late_empty_attempt: int     # 普通 phase 为 0，late-empty 为 1/2
```

固定配置：

| 配置 | 默认值 | 作用 |
| --- | --- | --- |
| `GLOBAL_INDEX_START_DATE` | `2022-01-01` | 日期计划和分区注册下限 |
| `GLOBAL_INDEX_PARTITION_REGISTRATION_BATCH_SIZE` | `2000` | 每 tick 最大新增分区数 |
| `GLOBAL_INDEX_REPLAY_LOOKBACK_DAYS` | `10` | phase replay 自然日范围 |
| `GLOBAL_INDEX_REPLAY_SLOT_LIMIT` | `50` | replay 最大 slot 数 |
| `GLOBAL_INDEX_FAILED_RUN_RETRY_LIMIT` | `2` | Raw failed-run 自动重试上限 |
| `GLOBAL_INDEX_LATE_EMPTY_DATE_LIMIT` | `3` | late-empty 最近日期数 |
| `GLOBAL_INDEX_LATE_EMPTY_RETRY_LIMIT` | `2` | 每日期 late-empty 次数 |
| `GLOBAL_INDEX_REQUEST_LIMIT` | `4000` | Tushare 单页上限 |
| `GLOBAL_INDEX_PHASE_TIMES` | 五阶段固定时间 | 北京时间最早触发窗口 |
| `GLOBAL_INDEX_REQUEST_BUDGET` | 复用 bounded policy | 请求、重试、耗时门禁 |

本轮不新增环境变量和运营输入项。修改这些常量必须同时更新方案、测试基线和性能报告；token 仍由 `TushareResource` 的 `dg.EnvVar("TUSHARE_TOKEN")` 提供。

## 5. Tushare 请求封装

### 5.1 字段合同

```python
INDEX_GLOBAL_FIELDS = (
    "ts_code",
    "trade_date",
    "open",
    "close",
    "high",
    "low",
    "pre_close",
    "change",
    "pct_chg",
    "swing",
    "vol",
    "amount",
)
```

`amount` 必须显式请求，即使大部分指数为空。不能因一次默认返回没有 `amount` 就删除该字段。

P1 必须保存三组真实请求证据：

1. 不传 `fields` 的默认字段返回；
2. 按 `docs/sources/tushare/指数专题/0211_国际指数.md` 显式请求完整字段；
3. 显式请求本项目业务关键字段 `INDEX_GLOBAL_FIELDS`。

每组还要验证不传过滤条件、只传 `ts_code`、只传 `trade_date`、`start_date/end_date` 区间以及 `limit/offset` 分页。报告记录脱敏参数、字段集合、行数、样本、耗时、错误和配额观察。若实测与本地文档不一致，先修正合同，不能带着差异进入 writer。

### 5.2 单阶段请求

```python
fetch_index_global_phase(
    tushare=tushare,
    trade_date="20260728",
    probe_phase="asia_1",
    request_policy=bounded_policy,
) -> IndexGlobalPhaseResult
```

请求参数固定：

```python
{
    "trade_date": "20260728",
    "limit": 4000,
    "offset": 0,
}
```

禁止传入一个代码列表并假设接口支持逗号拼接。通过不传 `ts_code` 获取当日已发布的全部指数，避免 21 次代码请求。

Tushare token 只通过现有 `TushareResource` 和 `dg.EnvVar("TUSHARE_TOKEN")` 注入；不得在 config、metadata、cursor、日志或报告中写入 token。

### 5.3 结果验证

单阶段结果必须先验证再交给 merge：

- 返回列集合等于 `INDEX_GLOBAL_FIELDS`；
- 所有返回行 `trade_date` 等于请求日期；
- `ts_code` 非空且属于 21 个固定身份代码；
- `(ts_code, trade_date)` 在单次返回内唯一；
- `offset` 只允许从 0 开始并严格递增；
- 满页必须继续请求，空页结束；
- 空结果是合法源观测；
- API 错误、限流错误、字段漂移、重复主键或预算超限 fail-closed。

当前每日基础请求通常只有 1 页。分页逻辑仍必须完整实现和测试，不能因为当前结果少于 4000 行就写死单页。

## 6. Raw phase merge writer

### 6.1 输入和输出

```python
merge_index_global_phase(
    lake_root_path: Path,
    trade_date: str,
    phase: str,
    phase_rows: Sequence[Mapping[str, object]],
    run_id: str,
) -> IndexGlobalMergeResult
```

输入只允许当前日期和当前阶段的已验证结果。writer 不负责调用 Tushare。

### 6.2 合并规则

1. 读取已有目标文件；不存在时使用空的固定 schema 表；
2. 将既有行和本阶段行放入 DuckDB 临时表；
3. 按 `(ts_code, trade_date)` 做窗口排序；
4. 已有目标行临时标记 `merge_rank=0`，当前阶段行临时标记 `merge_rank=1`；
5. 同一阶段的重复业务主键在 merge 前 fail-closed，不让 `ROW_NUMBER()` 随机选行；
6. 以 `(ts_code, trade_date) ORDER BY merge_rank DESC` 选择最终行；
7. 相同值重复行只保留一行；当前阶段值变化覆盖已有值并统计 `replaced_row_count`；
8. 空阶段结果不删除既有行；目标不存在时写固定 schema 空文件；
9. 所有校验通过后写 staging parquet；
10. staging 回读通过后 `os.replace`。

`merge_rank` 只存在于 DuckDB 临时 CTE，不写入 Raw schema，也不依赖不存在的 `probe_sequence`。retry 和 late-empty 都作为当前阶段的新输入；同一日期同一阶段重跑时，当前返回行仍可以替换已有行。

后阶段必须能够看到前阶段已写入的数据，不能每次从 Tushare 单次返回结果重建文件，否则会丢失早先市场的数据。

### 6.3 原子替换保护

目标文件存在时：

- 不允许直接覆盖；
- 不允许 append parquet；
- 只有 merge 后 staging 的 schema、日期、主键和行数检查通过才允许替换；
- DuckDB 错误、Tushare 错误、进程异常时保留既有目标；
- staging 文件使用 `run_id + trade_date + phase` 唯一命名；
- 成功 promote 后删除 staging；
- 失败时清理当前 run 的 staging，不删除既有目标。

## 7. Raw Asset、Check、Job、Sensor

### 7.1 Raw Asset

正式文件：

```text
orchestrator/defs/assets/index_global_raw.py
```

asset：`raw_index_global`

要求：

- `partitions_def=cn_global_index_trade_days`；
- 每次只处理一个 `trade_date`；
- 通过 typed config builder 读取 `trade_date`、`probe_phase`、`attempt`、`slot_key` 和 `late_empty_attempt`；
- 调用 bounded fetcher 和 phase merge writer；
- 返回 `MaterializeResult`，写入请求和 merge 摘要；
- 不新增项目自定义 run tags；失败 retry sensor 直接读取触发 run 的 typed `run_config`；
- 不读取 Dagster event history；
- 不在 asset 中手写 SQL 之外的逐行指标逻辑；
- 同一日期可被不同阶段重复 materialize。

metadata 最少包含：

```text
trade_date
probe_phase
source_method=tushare_index_global
source_row_count
merged_row_count
replaced_row_count
request_count
page_count
retry_count
elapsed_ms
target_path
```

禁止写入完整返回行、完整代码列表或逐页明细。

### 7.2 Raw Core Check

正式文件：

```text
orchestrator/defs/checks/index_global_checks.py
```

check：`raw_index_global_core_check`

显式绑定：

```python
partitions_def=cn_global_index_trade_days
blocking=True
```

DuckDB set-based 规则：

```text
file_exists
schema_exact
partition_trade_date_match
ts_code_non_null_and_known
unique(ts_code, trade_date)
```

不检查：

```text
row_count > 0
observed_code_count == 21
every_code_exists
```

空文件通过前提是文件存在且 schema 正确。

check 实现必须通过 `build_check_metadata(...)`，至少写入：

```text
goldenshare/check_scope
goldenshare/file_path
goldenshare/checked_row_count
goldenshare/failed_row_count
goldenshare/failed_rule_names
goldenshare/rule_results
goldenshare/failure_samples
```

失败时 `failed_rule_names` 必须能够直接解释是文件、schema、分区日期、身份字段还是主键规则失败。失败样本最多 3 条，不写完整行集。

### 7.3 Raw Job

正式文件：

```text
orchestrator/defs/jobs/index_global.py
```

job：`raw_index_global_update_job`

只选择 `raw_index_global` 及其 core check，保持单分区执行。job 只定义 selection；typed config builder 负责业务配置，config 至少包含：

```text
trade_date
probe_phase
attempt
slot_key
late_empty_attempt
```

原始 phase run 的 run key：

```python
build_asset_update_run_key(
    subject="index_global_update",
    unit_id=f"{trade_date}:{probe_phase}",
)
```

retry 不在 job 中拼接字符串，由 retry sensor 调用：

```python
build_repair_attempt_run_key(
    subject="index_global_update",
    repair_scope_id=f"{trade_date}:{probe_phase}",
    attempt=attempt,
    attempt_scope="retry",
)
```

### 7.4 Raw Sensor

正式文件：

```text
orchestrator/defs/sensors/index_global_sensor.py
```

sensor 默认 `STOPPED`，启用前必须完成本地和临时湖验证。

Raw sensor 使用确定性的 `PhaseSlot(target_trade_date, probe_phase)` 模型，不只判断“当前是否正好处于某个阶段”。

sensor 热路径只做：

- 读取当前北京时间；
- 生成最近 `GLOBAL_INDEX_REPLAY_LOOKBACK_DAYS=10` 个自然日内已经到期的 phase slot；
- 从 cursor 的 `last_dispatched_slot` 之后选择最早缺口；
- 确认目标自然日已注册；
- 构造 run key；
- 最多返回一个 RunRequest。

回放规则：

- 每个自然日最多 5 个 phase slot，最近 10 个自然日最多 50 个 slot；
- DG 停止期间错过的 slot，在恢复后的 tick 中按时间顺序逐个补发；
- 每个 tick 只推进一个 slot，避免一次恢复向 Dagster 或 Tushare 打入突发请求；
- cursor 只在 RunRequest 被接受时推进 `last_dispatched_slot`；
- 如果 cursor 与当前回放窗口相差超过 10 个自然日，返回
  `replay_backlog_exceeded`，停止自动扩大范围，转人工 Bootstrap/repair；
- 后续阶段仍会读取该日期当前已发布的全部指数，phase merge 可以间接补齐早期错过阶段的数据，但不替代 slot replay。

同一个 slot 在提交后视为 in-flight，下一 tick 不重复提交同一 slot；sensor 必须使用统一 run key 幂等保护，并在提交前对当前 slot 的运行状态做有界检查。不能为了确认 slot 状态读取完整 event history。前一 phase 未完成时，后续 phase 可以继续按时提交，因为它们的目标是同一日期的独立源观测；Silver 仍只等待 `americas` 成功。

sensor 不做：

- Tushare 请求；
- 代码覆盖判断；
- Dagster event history 查询；
- 全历史日期扫描；
- 逐文件深度检查。

sensor cursor 必须通过 `build_sensor_cursor(...)` 生成，不能在 sensor 文件中自己 `json.dumps`。顶层只使用现有 cursor contract：

```json
{
  "schema_version": 1,
  "evaluated_at": "...",
  "decision": "request_runs",
  "target_date": "2026-07-28",
  "selected_count": 1,
  "blocked_count": 0,
  "sample_keys": [],
  "details": {
    "sensor_name": "index_global_update_job_sensor",
    "job_name": "raw_index_global_update_job",
    "asset_family": "index_global",
    "partition_set": "cn_global_index_trade_days",
    "reason_code": "slot_dispatched",
    "blocked_component": "none",
    "summary": "已提交一个到期的国际指数 phase slot。",
    "next_action": "等待该 phase run 完成后继续处理下一个 slot。",
    "runtime_state": {
      "last_dispatched_slot": "2026-07-28:asia_1",
      "replay_backlog_count": 0
    }
  }
}
```

只允许使用 `request_runs`、`skip`、`register_partitions`、`notify` 四种 decision。cursor 不保存完整 slot 列表，不读取 Dagster event history，也不伪造 source readiness。run key 负责幂等，失败重试由下面的受控 retry sensor 和 job retry 规则处理。

### 7.5 Failed Run Retry Sensor

正式文件：

```text
orchestrator/defs/sensors/index_global_retry_sensor.py
```

新增一个默认 `STOPPED` 的 `@dg.run_status_sensor`，只监听
`raw_index_global_update_job` 的失败 run。它直接读取触发失败 run 的 typed `run_config`，不读取 run tags，不调用
`instance.get_event_records(...)`，也不从 run key 反解析日期或 phase。

失败重试使用：

```python
build_repair_attempt_run_key(
    subject="index_global_update",
    repair_scope_id=f"{trade_date}:{probe_phase}",
    attempt=attempt,
    attempt_scope="retry",
)
```

约束：

- job 内 bounded request policy 最多 3 次网络/限流重试；
- run-status retry sensor 最多再提交 2 个 retry run；
- retry attempt 超限后输出 `retry_exhausted`，不继续创建新 run；
- retry run 使用同一日期、阶段和 config，不扩大日期范围；
- retry sensor 每次最多一个 RunRequest，不读取湖文件、不访问 Tushare；
- schema、主键、日期等确定性错误即使重试也不会改变事实，达到上限后必须人工处理。

这样可以区分“短暂网络问题自动恢复”和“数据合同错误停止并告警”，避免无限重试。

### 7.6 Late Empty Reprobe

空结果不作为 blocking check，但需要防止“源站暂时未发布”永久固化为空文件。

新增受控的 late-empty 探测策略：

- 只检查最终 `americas` 阶段之后仍为零行的最近 3 个自然日；
- 只在目标 Raw 文件存在且行数为 0 时生成候选；
- 每个日期最多补探 2 次，分别作为 `late_empty_1`、`late_empty_2`；
- 每次 tick 最多提交一个 RunRequest；
- 通过一次 DuckDB 批量查询读取最多 3 个文件的行数，不读取 event history；
- 空结果仍是合法 source observation，不转化为“必须有指数”的 blocking check；
- 若补探仍为空，保留空文件和 source observation metadata，后续进入离线审计。

late-empty 固定实现为独立的默认 `STOPPED` sensor：

```text
orchestrator/defs/sensors/index_global_late_empty_sensor.py
```

- 该 sensor 自己维护最近 3 日、每日期最多 2 次的 `details.runtime_state`；
- run config 使用 `probe_phase="late_empty"`、`late_empty_attempt` 和目标日期；
- run key 使用 `build_repair_attempt_run_key(subject="index_global_update", repair_scope_id=trade_date, attempt=late_empty_attempt, attempt_scope="late_empty")`；
- 每 tick 最多一个 RunRequest；
- 超过次数输出 ASCII `late_empty_exhausted`，转离线审计；
- 不读取 event history、不访问 Tushare、不删除已有行，仍复用同一个 phase merge writer。

## 8. Silver 实现

### 8.1 Silver Writer

正式文件：

```text
orchestrator/defs/assets/index_global_silver.py
```

Silver 只读取同日期 Raw：

```sql
SELECT
  CAST(trim(ts_code) AS VARCHAR) AS ts_code,
  CAST(strptime(trade_date, '%Y%m%d') AS DATE) AS trade_date,
  CAST(open AS DOUBLE) AS open,
  CAST(high AS DOUBLE) AS high,
  CAST(low AS DOUBLE) AS low,
  CAST(close AS DOUBLE) AS close,
  CAST(pre_close AS DOUBLE) AS pre_close,
  CAST(change AS DOUBLE) AS change_amount,
  CAST(pct_chg AS DOUBLE) AS pct_chg,
  CAST(swing AS DOUBLE) AS swing,
  CAST(vol AS DOUBLE) AS vol,
  CAST(amount AS DOUBLE) AS amount
FROM read_parquet(...)
WHERE trade_date = :partition_trade_date
```

Silver 允许空 Raw 生成空 Silver，但必须保留固定 schema 和分区文件。

### 8.2 Silver Core Check

check：`silver_index_global_core_check`

显式绑定：

```python
partitions_def=cn_global_index_trade_days
blocking=True
```

DuckDB set-based 规则：

```text
file_exists
schema_exact
partition_trade_date_match
ts_code_non_null_and_known
unique(ts_code, trade_date)
numeric_columns_have_contract_types
```

以下情况不导致该 check 失败：

- `amount`、`vol` 等源站允许为空的字段为 NULL；
- 当前自然日没有任何源站返回，生成了固定 schema 的空 Silver 文件；
- 21 个指数没有全部出现。

该 check 不承担 Tushare 请求完整性、阶段发布时间判断或 21 个指数覆盖率判断。请求失败、字段漂移、分页重复等问题必须在 Raw writer 的 fail-closed 门禁中阻止文件替换；阶段覆盖情况进入 materialization metadata 和离线审计。

### 8.3 Silver Trigger Policy

默认只在 `americas` 阶段完成后触发 Silver，触发机制固定为 run-status sensor：

- 正式文件：`orchestrator/defs/sensors/silver_index_global_sensor.py`；
- 监听 `raw_index_global_update_job` 的成功 run；
- 只接受触发 run `run_config` 中 `probe_phase == "americas"`；
- 直接读取 `context.dagster_run.run_config`，不读取 event history，不从 run key 解析 phase；
- 提交 `silver_index_global_update_job`，run key 由 `build_asset_update_run_key(subject="silver_index_global_update", unit_id=trade_date)` 生成；
- Silver 只读取同日 Raw，Raw 缺失、schema/key/date 不合格时 fail-closed；
- Silver 已存在但核心 check 失败时不自动覆盖；
- Silver 失败由独立 bounded run-status retry sensor 最多重试 2 次，超过后输出 `silver_retry_exhausted`；
- Asia/Europe 阶段只更新 Raw，Silver 每个自然日最多执行一次。

这样不会用文件存在状态冒充“Americas 已完成”，也不会因为 Dagster event history 膨胀而在 sensor 热路径深扫。

## 9. 失败和重试

失败分类：

| 类型 | 行为 |
| --- | --- |
| 网络临时错误/限流 | bounded retry，预算内重试 |
| 返回空 | 合法 source observation；目标不存在时生成固定 schema 的空文件，已有前序阶段数据时保留已有行 |
| 字段漂移 | 当前阶段 fail-closed，不替换文件 |
| 日期错位 | 当前阶段 fail-closed，不替换文件 |
| 主键重复 | 当前阶段 fail-closed，不替换文件 |
| schema/Parquet 写失败 | 保留已有文件，清理 staging |
| 预算超限 | fail-closed，需人工分析 |

空返回的阶段不能删除之前阶段已经写入的数据。只有 Tushare 返回的有效行才参与 merge。

### 9.1 自动恢复边界

| 故障 | 自动处理 | 上限/结果 |
| --- | --- | --- |
| DG 停止导致阶段 tick 错过 | phase slot replay | 最近 10 个自然日、最多 50 个 slot |
| 单次网络抖动 | job 内 bounded retry | 最多 3 次，指数退避 |
| job 最终失败 | failed run retry sensor | 最多 2 个 retry run |
| `americas` 成功后 Silver run 失败 | Silver bounded retry sensor | 最多 2 个 retry run |
| Tushare 阶段暂时返回空 | late-empty reprobe | 最近 3 日，每日最多 2 次 |
| 回放积压超过 10 日 | 不自动扩大范围 | `replay_backlog_exceeded`，转人工 Bootstrap/repair |
| retry 超限 | 不再自动重试 | `retry_exhausted`，保留失败事实 |

自动恢复不删除事件、不删除 Parquet、不覆盖未通过校验的目标文件。所有补偿仍经过同一 staging、DuckDB 校验和原子替换路径。

## 10. Bootstrap

Bootstrap 从 `2022-01-01` 到指定结束日生成自然日计划。每个日期按阶段顺序运行：

```text
asia_1 -> asia_2 -> asia_3 -> europe -> americas
```

Bootstrap 允许读取已有目标并跳过 contract 正确的文件，但不允许静默覆盖错误文件。历史初始化需要明确区分：

- 目标不存在：允许生成；
- 目标存在且正确：跳过；
- 目标存在但错误：停止并输出冲突报告；
- 阶段重跑：按同一 merge 规则原子替换。

Bootstrap 不使用 Dagster event history，不运行 `dg launch`，不写正式 event。Raw 完成全量对账后才生成 Silver。

量级预算（以 `2022-01-01` 到 `2026-07-28` 为例）：

- 自然日约 `1,670` 个；
- 五阶段基础请求约 `8,350` 次；单阶段常态预计一页，但必须记录分页和 retry；
- Raw/Silver 最终文件约 `3,340` 个；
- 每批最多 20 个自然日，日期串行，不把历史 phase 变成 Dagster run 批量提交；
- 每个日期只保留当前阶段返回、DuckDB 临时表和当前 staging 文件，不能把全历史行装入 Python；
- Bootstrap 报告必须按日期记录 source rows、merged/written rows、replaced rows、request/page/retry、DuckDB、Parquet、磁盘和耗时；
- 历史 phase 只写 Bootstrap source observation 报告，不逐 phase 补 Dagster materialization/check event；最终 Raw/Silver 状态事件另按 P10 口径处理；
- 目标存在且 contract 正确则跳过，目标存在但错误则停止，禁止静默覆盖。

### 10.1 Event 和 latest-state 口径

- 日常 Raw 五个 phase 可以对同一 partition 产生多次 materialization，但每次只保留一个合并后的最终文件；后续阶段的事件不代表“新增另一份 partition 数据”；
- Raw/Silver 各自只保留一个 core check，不按字段拆分 check；同一分区的最新 check 只描述当前文件事实；
- Sensor 不从 event history 判断 phase 是否完成；Raw phase 完成由触发 run 的 typed config 和 run-status sensor直接传递；
- Bootstrap 的 phase 过程只写离线报告，避免历史阶段事件乘以五倍；最终 Raw/Silver materialization/check 事件另按 P10 验收和最近 20 个自然日保留策略处理；
- 不删除 runs、run tags、dynamic partitions 或未经过 retention 安全审计的事件。

## 11. 测试设计

### 11.1 Request policy

- 默认字段、显式完整字段、显式业务关键字段三组请求；
- 2022-01-01 空结果；
- 2022-01-03 部分结果；
- 2022-01-04 21 行结果；
- 单页、多页、空页、重复页、字段漂移；
- `limit=4000` 和 `offset` 递增；
- API 错误分类、重试和总预算。

### 11.2 Phase merge

- 五阶段逐步新增代码；
- 空阶段不删除旧数据；
- 相同主键相同值去重；
- 相同主键不同值以后阶段覆盖；
- staging 失败时目标保持原样；
- 重跑不产生重复行；
- 空分区 schema 正确。

### 11.3 Definitions and sensors

- Catalog entry、PartitionModelDefinition、中文名和 asset governance mapping 完整且与代码一致；
- Raw/Silver asset 使用正确 partition set；
- asset definition metadata 使用 `build_asset_definition_metadata(...)`，materialization 使用 `build_materialization_metadata(...)`；
- core check 显式 partitioned；
- core check 使用 `build_check_metadata(...)`、`CheckScope`、失败规则、失败数量和有限样本；
- 空文件通过 core check；
- 21 代码缺失不触发失败；
- 五个阶段目标日期映射正确；
- 同日期不同阶段 run key 不冲突；
- retry 和 late-empty 只从 typed run config 读取状态，不读取 run tags、不解析 run key；
- Silver 只消费 `americas` 成功 run；Silver 失败最多重试 2 次；
- sensor 不调用 Tushare、Prod DB 或 event history；
- 每 tick 最多一个 RunRequest；
- cursor ASCII 且小于 8KB；
- sensor 默认 `STOPPED`。

### 11.4 Recovery and replay

- DG 停止一个或多个阶段后，sensor 能按 slot 顺序补发；
- 单 tick 只返回一个 replay RunRequest；
- 超过 10 个自然日积压时 fail-closed；
- failed run retry sensor 只消费直接失败事件，不调用 event history；
- retry attempt 超限后不产生无限新 run；
- 空文件只触发有限 late-empty reprobe，不引入 21 代码 coverage check；
- late-empty reprobe 不删除前序阶段数据，仍使用 phase merge。

### 11.5 配置与预算

- 所有 `GLOBAL_INDEX_*` 配置只在 `run_contracts/index_global.py` 定义一次；
- 默认值、消费者、预算和修改门禁有测试；
- Bootstrap 1,670 日、8,350 基础请求、3,340 文件的预算报告可生成；
- 不允许把 Bootstrap 转成 Dagster phase run 或全历史 event 扫描。

## 12. 性能基线

需要记录：

- 每阶段请求次数、页数、重试次数；
- 每阶段源行数、合并行数、替换行数；
- DuckDB merge、校验、Parquet 写入、回读、promote 耗时；
- 每阶段文件大小；
- sensor tick elapsed；
- DuckDB connection 数；
- event history API 调用次数；
- Tushare/Prod DB sensor 调用次数。

验收：

- 正常日期最多 5 次基础请求；
- 单阶段不超过 1 个日期文件扫描；
- sensor Tushare 调用为 0；
- sensor event history 调用为 0；
- replay planner 只扫描最近 10 个自然日，不扫描全历史；
- retry sensor 的 event history API 调用为 0；
- late-empty 检查最多批量读取 3 个目标文件；
- 无全历史扫描；
- 无逐代码请求循环；
- 无无界重试和分页；
- 单阶段异常不覆盖已有目标；
- 后阶段 merge 不丢前阶段数据。

## 13. 实施顺序与验收

1. 请求字段、分页和 bounded policy 真实验证；
2. Raw schema 和 phase merge writer；
3. Raw 临时湖五阶段联调；
4. Silver writer 和空分区处理；
5. Raw/Silver definitions、core checks、jobs；
6. 自然日注册 sensor；
7. Raw 五阶段 sensor；
8. failed run retry sensor 和 late-empty reprobe；
9. Silver final-phase sensor；
10. Bootstrap dry-run；
11. 正式 Raw/Silver 生成和对账；
12. Dagster event 验收；
13. 手动启用 sensors 并观察三个实际运行日。

进入正式写入前必须同时满足：

- 请求分页测试通过；
- 临时湖五阶段 merge 测试通过；
- 空分区测试通过；
- schema/date/key 检查通过；
- sensor 热路径无网络和 event history 调用；
- 性能数据在预算内；
- 无未解释的字段、行数或覆盖冲突；
- 正式写入和 Dagster event 仍需单独批准。

## 14. 实现前置验收命令

代码实现阶段至少补充并执行：

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator

PYTHONPATH=src uv run --project . --with pytest python -m pytest \
  tests/test_index_global_source_probe.py \
  tests/test_index_global_contracts.py \
  tests/test_index_global_partition_sensor.py \
  tests/test_index_global_raw_io.py \
  tests/test_index_global_checks.py \
  tests/test_index_global_sensors.py \
  tests/test_index_global_bootstrap.py \
  tests/test_asset_check_incremental_governance.py \
  tests/test_run_contract_static_gates.py

python3 -m py_compile \
  src/orchestrator/defs/assets/index_global_raw.py \
  src/orchestrator/defs/assets/index_global_silver.py \
  src/orchestrator/defs/checks/index_global_checks.py \
  src/orchestrator/defs/sensors/index_global_sensor.py \
  src/orchestrator/defs/sensors/index_global_retry_sensor.py \
  src/orchestrator/defs/sensors/index_global_late_empty_sensor.py

python3 scripts/check_docs_integrity.py
git diff --check
```

正式 `dg check defs`、sensor tick、job、Bootstrap 和 event 写入仍需按 orchestrator AGENTS 单独批准；本 LLD 不把这些本地验证命令当作正式运行授权。
