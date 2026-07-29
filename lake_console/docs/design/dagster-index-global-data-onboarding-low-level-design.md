# `index_global` 国际指数数据集低层设计（LLD）

## 1. 目标与边界

本文是 [`dagster-index-global-data-onboarding-plan.md`](./dagster-index-global-data-onboarding-plan.md) 的代码级设计。目标是把 Tushare `index_global` 接入 Dagster Lake，形成 Raw/Silver 两层、自然日分区、同日五阶段刷新和低开销自动触发链路。

当前进度：P1 真实请求验证、P2 Raw contract/路径/phase merge/staging、P3 真实 bounded fetch 临时湖五阶段联调、P4 Silver writer/contract/临时 Raw -> Silver 联调、P5 active Raw/Silver definitions 接入、P6 专属自然日注册/五阶段 Raw sensor/Silver final-phase 触发、P7A Bootstrap 只读目标审计、P7B 全量源请求审计、正式 Raw/Silver 生成和全量文件对账、P8 Dagster 分区注册和事件验收均已完成；P9 已完成实例启用和首个实际运行日验证，多交易日观察尚未完成。

本 LLD 不实现 Gold 指标；正式 Raw/Silver Bootstrap 已由独立 apply CLI 按本 LLD 门禁完成，P8 已由独立事件 CLI 完成动态分区和 runless event 补录；P6 的代码定义和 P9 的运行时实例状态均保留可区分的安全边界：代码默认值仍为 `STOPPED`，P9 已在正式实例中显式启用，当前负责运行观察。

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

### 2.2.1 P2 已落地实现

P2 的稳定 writer 核心位于 `orchestrator/defs/assets/index_global_raw.py`，P5 在同一模块外层增加了 active Dagster asset wrapper。`merge_index_global_phase(...)` 接收已经验证的单阶段行，不负责调用 Tushare；它通过 `DuckDBResource` 建立当前日期的 `existing_rows`/`phase_rows` 临时表，用 `merge_rank=0/1` 的 set-based 查询选择最终行，再把固定列集合写入唯一 staging 路径。staging 通过 schema、分区日期、身份集合、业务主键、有限数值和行数回读校验后才 `os.replace`。

P2 的本地验证覆盖 11 项 Raw contract/临时湖测试；另运行 99 项静态与既有 dc_board 相关回归测试。P2 没有调用 `dg`、Tushare、正式 lake 或 Dagster instance。P3 已在此 writer 之上接入 bounded fetcher，并完成临时 lake 五阶段顺序、分页结果和真实字段映射验证。

### 2.2.2 P3 已落地实现

P3 在同一稳定 Raw writer 模块中增加 `fetch_index_global_phase(...)` 和
`run_index_global_phase_sequence(...)`。fetcher 显式构造 `trade_date`、`limit`、`offset`、`fields`，复用 `execute_bounded_pages(...)`；分页结果先检查列集合，再检查日期、固定身份代码和业务主键，只有 ready 结果才进入 `merge_index_global_phase(...)`。五阶段入口按 `asia_1 -> asia_2 -> asia_3 -> europe -> americas` 串行执行，不并发放大 Tushare 请求。

真实临时湖样本使用 `2022-01-04`：五个 phase 各 21 行、各 1 页，总请求 5 次、重试 0 次，最终 Raw 21 行，全部 staging 原子 promote。真实报告为 `/private/tmp/index_global_p3_real_validation_p3-real-20260728204238.json`。验证还确认 Tushare/Pandas 空数值会以 `NaN` 进入 Python，P3 将其转换为 Parquet `NULL`；非数值和无穷值仍拒绝。P3 总计通过 105 项定向/静态测试，未调用 `dg`，未写正式 lake、Dagster DB 或 event。

P3/P4 只完成 writer 和临时湖联调；P5 已接入 active Raw/Silver asset、core check 和 job，但尚未启用 sensor 或正式湖写入。P4 的 Silver writer 核心仍由 P5 的 active Silver asset wrapper 调用。P7A 已新增只读 Bootstrap planner/CLI；P7B 又新增只读 Tushare source probe 和独立 apply CLI，当前正式 apply 不访问 Dagster instance、不写 Dagster event、不启用 sensor。

### 2.3 数据卡和代码登记落点

本 LLD 的正式名称固定为“国际指数日线”，稳定 `dataset_id=index_global`。P2 已完成 Raw schema、统一 contract、路径 helper 和 writer 核心；P5 已补齐以下 active definition、catalog 和治理登记：

| 目标 | 代码落点 |
| --- | --- |
| 中文名称 | `orchestrator/defs/catalog/name_mapping.py` 增加 `index_global` |
| 路径 | P2 已增加 `raw_index_global_path`、Raw staging helper；P4 已增加 `silver_index_global_path`、Silver staging helper |
| schema | P2 已增加 `RAW_INDEX_GLOBAL_SCHEMA`；P4 已增加 `SILVER_INDEX_GLOBAL_SCHEMA` |
| 统一合同 | P2 已增加 `orchestrator/defs/run_contracts/index_global.py` 的字段、代码集合、phase 和校验合同；P5 已补齐 typed config、请求预算和 materialization metadata 摘要，P6-P7 继续补齐 sensor/repair 侧合同 |
| partition | `orchestrator/defs/partitions.py` 增加唯一 `cn_global_index_trade_days` |
| Catalog | `orchestrator/defs/catalog/lake_assets.py` 增加两个 `PartitionModel`、两个 `PartitionModelDefinition` 和两个 `LakeAssetCatalogEntry` |
| governance | `tests/test_asset_check_incremental_governance.py` 增加两个 core check 的治理映射 |
| asset/check/job/sensor | P5 已分别落在 `orchestrator/defs/assets/`、`checks/`、`jobs/`；P6-P7 再增加 `sensors/`，均由 `orchestrator/definitions.py` 的 `load_from_defs_folder` 自动装配 |

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

### 2.5 P5 正式 Definitions 接入记录

P5 的实现边界是把已经通过 P2/P3/P4 验证的 Raw/Silver writer 接入可加载的 Dagster definitions，不改变 writer 的数据语义：

1. `raw_index_global` 和 `silver_index_global` 均使用 `cn_global_index_trade_days`，同一自然日是两层的唯一 partition unit。Raw asset 通过 `IndexGlobalRawConfig` 接收 `trade_date`、`probe_phase`、`slot_key`、`attempt` 和 `late_empty_attempt`，并在进入 writer 前校验 partition/config 一致性。
2. `raw_index_global` 每次只运行一个自然日的一个探测阶段；`silver_index_global` 声明同日 Raw 依赖并调用现有 DuckDB Silver writer。两个 asset 只返回小型 materialization metadata，不写完整代码列表、逐行结果或 event history。
3. `raw_index_global_core_check`、`silver_index_global_core_check` 都显式绑定 `cn_global_index_trade_days` 且 `blocking=True`。它们执行文件存在、schema、分区日期、身份字段、业务键唯一和有限数值规则；自然日空文件只要上述规则通过就可以通过，不把 21 指数覆盖或 row count positive 误设为核心硬门禁。
4. `raw_index_global_update_job`、`silver_index_global_update_job` 均为单分区 job，只选择对应 asset 与 core check，禁止多分区聚合 check，未新增 sensor。
5. P5 同步完成 `PartitionModel`、catalog、中文名、schema、路径、统一 contract 和治理映射。定向回归结果为 `123 passed`、`72 subtests passed`；没有运行 `dg`，没有写正式 lake、Dagster DB 或 Dagster event。

P6 仍必须单独完成自然日分区注册、五阶段 Raw sensor、late-empty sensor、Silver final-phase sensor 和默认 STOPPED 状态验收；不能因为 P5 definitions 已加载就自动启用日常同步。

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

### 5.0 P1 实测基线

P1 已完成真实只读验证，报告为：
`/private/tmp/index_global_p1_tushare_validation_20260728.json`。

实测固定为以下事实：

- `20220101` 返回空结果，`20220103` 返回 16 行，`20220104` 返回 21 行；2022-01-04 的返回代码集合与 21 个固定代码完全一致；
- 默认字段没有 `amount`，显式请求业务字段集合后可以返回 `amount`，但不同指数的 `amount` 允许 NULL；
- 点查按日期返回当前已发布结果，日期区间为闭区间；
- 不传日期或只传 `ts_code` 会返回最多 4000 行宽历史结果，正式每日同步不能采用这种请求形态；
- MCP wrapper 没有 `limit/offset` 参数，因此分页用同一 Tushare HTTP API 进行了最小只读验证：offset 递增得到不重叠页，空页可作为终止条件。

因此 P2 的实现门禁已经明确：日常请求必须显式传 `trade_date`、12 个业务字段、`limit` 和递增 `offset`，并通过现有 bounded request policy 统一处理空页、重复页、字段漂移、重试和请求预算。P1 只记录请求样本和耗时，不代表 P2 writer 的生产 SLO 已通过。

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
  upper(trim(CAST(ts_code AS VARCHAR))) AS ts_code,
  CAST(try_strptime(NULLIF(trim(CAST(trade_date AS VARCHAR)), ''), '%Y%m%d') AS DATE) AS trade_date,
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
```

实现文件为 `orchestrator/defs/assets/index_global_silver.py`，P4 提供 writer 核心，P5 在同一模块外层增加 active Dagster asset wrapper。writer 在 DuckDB 中先检查 Raw 合同，再执行上面的 set-based normalization；不会用 `WHERE` 静默丢弃日期错误，而是把非法日期和分区外日期归类为拒绝并 fail-closed。业务键 `(ts_code, trade_date)` 的完全相同重复行可去重，值冲突直接失败。

Silver 允许空 Raw 生成空 Silver，但必须保留固定 schema 和分区文件。staging 回读仍需通过 Silver schema、日期/身份、唯一键、有限数值和行数检查，全部通过后才原子替换目标文件；失败路径不会覆盖已有目标。

P4 新增：

- `SILVER_INDEX_GLOBAL_SCHEMA`：固定 Silver 12 列，`trade_date` 为 `DATE`，`change` 标准化为 `change_amount`；
- `silver_index_global_path(...)`：`silver/index_global/trade_date={trade_date}/part-000.parquet`；
- `silver_index_global_staging_path(...)`：按 `run_id/trade_date` 隔离 staging；
- `IndexGlobalSilverWriteResult`：记录源行数、输出行数、去重数、拒绝原因、耗时和 promote 结果。

P4 定向测试和 P2/P3 Raw 回归共 28 项通过；真实临时 Raw -> Silver 联调报告为 `/private/tmp/index_global_p4_real_validation_20260728204238.json`，21 行 Raw 转换为 21 行 Silver，schema、回读行数和 staging 清理均通过。P5 的 active Silver asset 只调用此 writer，不改变其清洗和原子替换语义。

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

### 8.4 P6 实现对账

P6 已按本节口径落地，代码边界如下：

| 能力 | 实现文件 | 关键门禁 |
| --- | --- | --- |
| typed Raw/Silver config、阶段时间、slot replay 上限 | `orchestrator/defs/run_contracts/index_global.py` | retry 只读 `run_config`；10 日、50 slot、2 次 retry、3 日/2 次 late-empty 上限 |
| 自然日分区注册 | `orchestrator/defs/sensors/global_index_partition_sensor.py` | 只生成 `2022-01-01` 至今日自然日；每 tick 最多注册 2000 个；不读 SSE 日历、Tushare、Prod DB 或 event history |
| 五阶段 Raw sensor | `orchestrator/defs/sensors/index_global_sensor.py` | 北京时间 due slot，按最早缺口每 tick 一个 RunRequest；未注册和超过回放边界 fail-closed |
| Raw failed-run retry | `orchestrator/defs/sensors/index_global_retry_sensor.py` | 只解析失败 run 的 typed config；`build_repair_attempt_run_key(..., attempt_scope="retry")` |
| late-empty 探测 | `orchestrator/defs/sensors/index_global_late_empty_sensor.py` | 最近 3 个已存在 Raw 文件一次 DuckDB 批量计数；每日期最多 2 次；不删除已有行 |
| Silver final-phase gate | `orchestrator/defs/sensors/silver_index_global_sensor.py` | 只接受 Raw `americas` 成功；既有 Silver core contract 失败时 skip，不自动覆盖 |
| Silver failed-run retry | `orchestrator/defs/sensors/silver_index_global_retry_sensor.py` | 只解析失败 Silver run 的 typed config；最多 2 次 retry |
| Silver 文件门禁 | `orchestrator/defs/asset_guards/index_global_lake_readiness.py` | schema、日期、身份、唯一键、有限数值 set-based 校验；合法空自然日通过 |

P6 本地验收覆盖 `tests/test_index_global_p6_sensors.py`、`tests/test_index_global_p6_static.py`、P5 回归和全局静态门禁，共 `135 passed`、`72 subtests passed`。定义加载、Python 编译和 lint 通过；仅存在既有 Dagster/Pydantic deprecation/preview warnings。P6 阶段未运行 `dg`、未启用 sensor、未写正式 lake、Dagster DB 或 event。

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
- 历史 phase 只写 Bootstrap source observation 报告，不逐 phase 补 Dagster materialization/check event；最终 Raw/Silver 状态事件另按 P8 口径处理；
- 目标存在且 contract 正确则跳过，目标存在但错误则停止，禁止静默覆盖。

### 10.1 P7A 只读 Bootstrap planner 实现

P7A 的入口固定为：

```text
orchestrator.defs.bootstrap.index_global_bootstrap_cli dry-run
```

实现落点：

- `orchestrator/defs/bootstrap/index_global_bootstrap_plan.py`：生成自然日计划、fingerprint、Raw/Silver 目标状态和五阶段基础请求预算；
- `orchestrator/defs/bootstrap/index_global_bootstrap_cli.py`：只暴露 `dry-run` 子命令，没有 `apply` 或隐式写入路径；
- `tests/test_index_global_bootstrap_plan.py`：覆盖自然日计划、未来日期/历史下限拒绝、缺失目标、合法空文件、坏 schema、CLI 无 apply 和无 Dagster event API。

P7A 的目标审计使用一个配置化 DuckDB connection：先批量读取已有目标的 schema，再对同层已有合法 schema 文件做批量 set-based contract 扫描。不存在的文件只记为 `file_missing`，允许进入后续正式生成；已有文件若 schema、分区日期、代码身份、业务主键唯一性或数值有限性失败，则以 `should_stop=true` 阻断后续写入。空 Raw/Silver 文件符合自然日允许空分区口径，不因行数为 0 被误判为坏文件。

P7A 明确不做以下动作：不调用 Tushare，不访问 Prod DB，不读取 Dagster event history，不执行 `dg`，不写 Raw/Silver Parquet，不写 Dagster DB/event。报告中的 `estimated_source_request_count` 只是五阶段基础请求预算，不是源站已成功返回的行数证明；P7B 必须另做源请求审计和性能/配额验收。

本次正式 lake 只读报告：

```text
/private/tmp/index_global_p7_bootstrap_dry_run_20260728.json
```

结果为 1,670 个自然日、估算 8,350 次基础请求、Raw/Silver 各 1,670 个目标文件；正式 lake 两层均无既有目标文件，冲突数为 0。未经正式 Raw/Silver 写入批准和全量文件对账，不得把本报告当作 Bootstrap 已完成。

### 10.2 P7B 全量 Tushare 源请求 dry-run 实现与结果

P7B 的只读入口固定为：

```text
orchestrator.defs.bootstrap.index_global_bootstrap_source_probe_cli
```

实现落点：

- `orchestrator/defs/bootstrap/index_global_bootstrap_source_probe.py`：使用冻结日期计划，按 `date -> asia_1 -> asia_2 -> asia_3 -> europe -> americas` 调用已经通过 P3 验证的 `fetch_index_global_phase(...)`；只保留聚合计数和有限失败/空结果样本；不写 Lake、不访问 Dagster instance。
- `orchestrator/defs/bootstrap/index_global_bootstrap_source_probe_cli.py`：只接收日期范围和 JSON 输出路径，不提供 apply/write/event 参数；token 只从 `TUSHARE_TOKEN` 环境读取。
- `tests/test_index_global_bootstrap_source_probe.py`：覆盖五阶段请求、空结果、首错停止、显式字段、全局节流记录和不写入边界。

P7B 的配额门禁不是“每个 phase 自己限流”而是整轮共享节流：每个 phase 内继续使用 `build_index_global_request_policy()` 的 bounded pagination/retry 规则，phase 之间额外保证至少 `0.13s` 的间隔。这样可以避免五个独立 phase runner 在切换时连续打穿 Tushare 分钟配额。报告中的 `throttle_wait_ms` 记录这部分等待。

Tushare 空 DataFrame 可能返回 `rows=()` 且 `columns=()`。`_extract_index_global_rows(...)` 将这个组合视为合法空 phase；只要有数据行，返回列集合仍必须严格等于 `INDEX_GLOBAL_FIELDS`，因此不会放松非空数据的字段漂移门禁。

2026-07-28 全量 dry-run 结果：

```text
report: /private/tmp/index_global_p7b_source_probe_20260728_retry3.json
date plan: 2022-01-01..2026-07-28
attempted/successful phases: 8350/8350
empty phases: 2349
failed phases: 0
source observation rows: 119162
requests/pages/retries: 8350/8350/0
throttle wait: 1085354 ms
elapsed: 1637916 ms (约 27.3 分钟)
should_stop: false
```

`source observation rows` 是五个 phase 返回结果的加总，不能直接当作最终 Raw 行数；同一日期的多个 phase 必须在正式 writer 中按 `merge_rank=0/1` 做 set-based 合并，最终 Raw 行数、Silver 行数和拒绝原因由正式文件对账产生。2,349 个空 phase 只说明该阶段当时没有返回行，不自动判定为全局指数缺失。

P7B 前三次失败报告没有删除：首次是一次瞬时 source request failure，第二次是 retry budget exhausted，第三次定位为空响应列误判；修正全局节流与空列空结果语义后，第四次全量报告通过。正式 apply 又重新检查了目标冲突、磁盘空间和 P7B fingerprint，随后完成 Raw/Silver 写入与对账。

### 10.3 正式 Raw/Silver apply 实现

正式写入入口固定为：

```text
orchestrator.defs.bootstrap.index_global_bootstrap_apply_cli
```

必须显式传入 `--confirm-lake-write` 和 P7B 成功报告。apply 在写入前校验：日期计划 fingerprint、8,350 个 phase 全部成功、目标文件没有 invalid existing、Lake 目录可写以及最低可用磁盘空间。它不接受 overwrite 开关，不访问 Dagster instance，不写 Dagster DB/event，不启用 sensor。

Raw 写入按最多 20 个自然日一批、批内串行执行。每个缺失日期先在正式 Lake 同一文件系统下的隐藏临时目录完成五个 phase fetch/merge；五个 phase 全部成功后才把临时 Raw 文件原子 promote 到正式日期路径。这样单个 phase 或进程失败不会把不完整 Raw 文件留在正式目标。已有目标只允许跳过；目标冲突或异常立即停止。

Raw 全量完成后，apply 先运行同一只读 DuckDB target audit；Raw 缺失或 invalid 数量必须为 0，才进入 Silver。Silver 逐日读取同日 Raw，复用现有 DuckDB set-based writer、staging 回读和原子替换。最终再次运行 Raw/Silver audit，并输出：

```text
/private/tmp/index_global_m7_raw_batch_<apply_id>.json
/private/tmp/index_global_m7_raw_audit_<apply_id>.json
/private/tmp/index_global_m7_silver_batch_<apply_id>.json
/private/tmp/index_global_m7_silver_audit_<apply_id>.json
/private/tmp/index_global_m7_final_reconciliation_<apply_id>.json
```

每个阶段失败即停止，不继续后续日期或 Silver；已完成日期及阶段、请求/分页/重试、源观测行数、最终输出行数和耗时写入批次报告，便于人工审计和后续受控续跑。正式 apply 的请求节流必须与 P7B source probe 相同，不能恢复为每个 phase 独立限流。

本次正式 apply 已完成，使用 `apply_id=20260728_233746`。Raw 与 Silver 各生成 1,670 个自然日文件；两层官方审计均为 `missing_count=0`、`invalid_existing_count=0`、`valid_existing_count=1670`。独立 DuckDB 对账确认两层各有 23,849 行、1,201 个非空日期、469 个合法空自然日分区，schema、路径日期、主键唯一性、代码/收盘价基础规则均通过，Raw/Silver 行级字段差异为 0。正式 Lake 隐藏 staging 目录残留为 0。

正式 apply 报告：

```text
/private/tmp/index_global_m7_raw_batch_20260728_233746.json
/private/tmp/index_global_m7_raw_audit_20260728_233746.json
/private/tmp/index_global_m7_silver_batch_20260728_233746.json
/private/tmp/index_global_m7_silver_audit_20260728_233746.json
/private/tmp/index_global_m7_final_reconciliation_20260728_233746.json
```

apply 期间共执行 8,350 次请求、8,350 页、0 次重试；请求阶段节流等待约 879,848 ms。该轮没有访问 Dagster instance、没有写 Dagster DB/event、没有注册 dynamic partition，也没有启用 sensor。

### 10.4 Event 和 latest-state 口径

- 日常 Raw 五个 phase 可以对同一 partition 产生多次 materialization，但每次只保留一个合并后的最终文件；后续阶段的事件不代表“新增另一份 partition 数据”；
- Raw/Silver 各自只保留一个 core check，不按字段拆分 check；同一分区的最新 check 只描述当前文件事实；
- Sensor 不从 event history 判断 phase 是否完成；Raw phase 完成由触发 run 的 typed config 和 run-status sensor直接传递；
- Bootstrap 的 phase 过程只写离线报告，避免历史阶段事件乘以五倍；最终 Raw/Silver materialization/check 事件另按 P8 验收和最近 20 个自然日保留策略处理；
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
- 全量 Bootstrap source probe 的 phase 间全局最小间隔、节流等待计时和失败分类；空响应列集合为空时作为合法空 phase。

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

## 13. P8 Dagster 事件补录实现与验收

### 13.1 入口与硬边界

P8 的实现位于：

- `orchestrator/defs/bootstrap/index_global_bootstrap_events.py`：冻结计划、分区注册、runless materialization/check 写入和幂等报告；
- `orchestrator/defs/bootstrap/index_global_bootstrap_events_cli.py`：`dry-run`、`register-partitions`、`apply` 三个显式命令；
- `tests/test_index_global_bootstrap_events.py`：分区注册、事件计划、最近 20 日范围和确认门禁测试。

命令边界固定如下：

| 命令 | 允许写入 | 禁止动作 |
| --- | --- | --- |
| `dry-run` | `/private/tmp` JSON 报告 | Dagster DB、lake、event、dynamic partition |
| `register-partitions --confirm-partition-write` | 指定 dynamic partition set | materialization、check、job、sensor、lake |
| `apply --confirm-event-write` | runless materialization/check event | dynamic partition、job、sensor、lake |

CLI 不提供隐式 apply；两个确认参数互斥。事件入口不调用 `dg`，不访问 Tushare、Prod DB 或 sensor 热路径。

### 13.2 冻结日期与事件范围

P8 只接受 P7 final reconciliation 报告中的完整 date plan，并校验：

- fingerprint=`1e4868df643ab6b35f0b76405a823bda240386dab78c7f8d274dacb7a5579492`；
- expected natural dates 数量为 1,670，范围为 `2022-01-01..2026-07-28`；
- Raw/Silver audit 各自 `expected_file_count=1670`、`missing_count=0`、`invalid_existing_count=0`、`valid_existing_count=1670`；
- 目标 Parquet 通过一次 DuckDB 批量行数读取，Python 只构造有限 metadata 摘要，不逐文件调用 Dagster API。

事件数量按以下固定矩阵计算：

| 事件 | 范围 | 数量 |
| --- | --- | ---: |
| `raw_index_global` materialization | 全部 1,670 个自然日 | 1,670 |
| `silver_index_global` materialization | 全部 1,670 个自然日 | 1,670 |
| `raw_index_global_core_check` | 最近 20 个自然日 `2026-07-09..2026-07-28` | 20 |
| `silver_index_global_core_check` | 最近 20 个自然日 `2026-07-09..2026-07-28` | 20 |

空自然日仍生成 materialization；由于 `index_global` 允许自然日合法空文件，最近 20 日 check 对空文件也按 core contract 通过处理。历史日期不补 check event，避免把事件数量扩大到无必要的全历史检查矩阵。

### 13.3 写入顺序与 partition 归属

materialization 使用 `instance.report_runless_asset_event(dg.AssetMaterialization(...))`，每条事件显式设置 `asset_key` 和 `partition=trade_date`。所有 3,340 条 materialization 完成后，check writer 才执行。

每个最近日期的 check 写入前，通过有界 `fetch_materializations(asset_key, asset_partitions=[trade_date], limit=1)` 读取刚写入的 materialization，构造 `AssetCheckEvaluationTargetMaterializationData`，再写入：

- `check_name` 保持现有 core check 名称；
- `partition=trade_date`；
- `blocking=True`、`passed=True`；
- `target_materialization_data` 指向同资产、同分区的 materialization storage id；
- metadata 使用 `build_check_metadata(CheckScope.RECONCILIATION, ...)`，保留报告路径、分区、行数和 fingerprint。

因此不会产生“check 成功但 partition 为空”或“check 指向其它日期 materialization”的历史归属错误。P8 不新增 check，不拆分字段级 check，不写 phase 级历史 event。

### 13.4 实际验收

实际报告：

- `/private/tmp/index_global_p8_partition_registration_20260729.json`；
- `/private/tmp/index_global_p8_pre_event_dry_run_20260729.json`；
- `/private/tmp/index_global_p8_event_apply_20260729.json`；
- `/private/tmp/index_global_p8_post_event_dry_run_20260729.json`。

结果：分区注册 1,670；事件写入 `3,340 + 40 = 3,380`，跳过 0；串行写入及扫描约 35.1 秒。SQL 只读验收确认 Raw/Silver materialization 各 1,670 条、分区非空；两类 core check 各 20 条，全部有 partition、target materialization 存在且 target partition 一致；20 日窗口外没有本轮 check event。post dry-run 的四类 planned count 全部为 0。

### 13.5 中断恢复

P8 event apply 不依赖事务回滚。中断后只能重新执行 P8 dry-run：

1. 已存在且可读的 materialization 按分区跳过；
2. 最近 20 日已通过且有 target 的 check 跳过；
3. 只继续补剩余缺口；
4. 任意湖文件、日期计划或分区注册校验失败时 fail-closed。

不允许直接 SQL 插入 `event_logs` / `asset_check_executions`，也不允许通过运行 normal asset/job 代替事件补录。P9 sensor 启用必须在 P8 对账通过后单独执行，并继续保留运行观察记录。

### 13.6 P9 实例启用与首个运行日收尾（2026-07-29）

P9 的开发和正式链路收尾已完成，当前只剩连续运行观察，不再新增 index_global 代码或 Dagster definition。

2026-07-29 的正式实例只读审计确认：

- `global_index_trade_day_partition_sensor`、`raw_index_global_update_job_sensor`、`raw_index_global_retry_sensor`、`raw_index_global_late_empty_sensor`、`silver_index_global_retry_sensor`、`silver_index_global_update_job_sensor` 均为 `RUNNING`；
- 代码中的 `default_status=STOPPED` 仍然保留，表示新环境默认不自动启用，不代表当前实例状态；
- `cn_global_index_trade_days` 已注册到 `2026-07-29`，共 1,671 个自然日分区；
- 当次审计时 Raw/Silver 各有 1,670 个正式文件，最新文件为 `2026-07-28`。这是正常的阶段边界：`2026-07-29` 的 `asia_1` 窗口尚未到达，不能把“尚未到触发时间”判为缺数。

`2026-07-28` 的首个完整运行日事实如下：

| 链路 | 结果 | 分区/范围 |
| --- | --- | --- |
| Raw `asia_1`、`asia_2`、`asia_3`、`europe`、`americas` | 5 个 phase run 全部成功 | `2026-07-28` |
| Raw core check | 全部通过 | `partition=2026-07-28` |
| Silver final-phase run | 自动触发并成功 | `partition=2026-07-28` |
| Silver core check | 通过 | `partition=2026-07-28` |
| Raw/Silver 文件行数 | 各 21 行 | `2026-07-28` |

四个美国指数 `DJI`、`SPX`、`IXIC`、`RUT` 均在 Raw 和 Silver 中存在，字段值对账一致。`amount` 或 `vol` 的 NULL 属于当前源合同允许值，不构成失败。该次审计没有发现活跃运行、重复 run key、错误 partition check 或未解释失败。

P9 当前结论：

1. 数据集开发、Bootstrap、Raw/Silver 文件对账、专属自然日分区注册、materialization/check event 补录和 sensor 启用均已完成；
2. normal Raw/Silver 日常链路已经有首个实际成功运行日证据；
3. 仍需继续记录至少 3 个实际交易日的运行结果，重点观察 phase replay、失败重试、late-empty、Silver final-phase gate、请求耗时、cursor 大小和 Dagster UI 状态；
4. 观察期间不应通过提高 RPC timeout 掩盖 sensor 热路径超时，也不应重新引入 Dagster event history 深扫。

## 14. 实施顺序与验收

1. 请求字段、分页和 bounded policy 真实验证（已完成，证据见 5.0）；
2. Raw schema 和 phase merge writer；
3. Raw 临时湖五阶段联调；
4. Silver writer 和空分区处理（已完成，P4）；
5. Raw/Silver definitions、core checks、jobs（已完成，P5）；
6. 专属自然日注册、Raw 五阶段 replay、failed-run retry、late-empty reprobe、Silver final-phase/retry sensor（已完成，P6）；
7. Bootstrap dry-run（已完成）；
8. P7B 全量 Tushare 源请求 dry-run 和性能/配额对账（已完成，报告见 10.2）；
9. 经单独批准后正式 Raw/Silver 生成和对账（已完成，报告见 10.3）；
10. Dagster event 验收（已完成：P8）；
11. 手动启用 sensors 并完成首个实际运行日验证（已完成）；继续观察至少三个实际运行日后完成 P9 运维收口。

进入正式写入前必须同时满足：

- 请求分页测试通过；
- 临时湖五阶段 merge 测试通过；
- 空分区测试通过；
- schema/date/key 检查通过；
- sensor 热路径无网络和 event history 调用；
- 性能数据在预算内；
- 无未解释的字段、行数或覆盖冲突；
- Dagster event 补录已由 P8 完成；P9 已按单独批准口径启用 sensor 并完成首个实际运行日验证，后续只需完成多交易日运行观察。

## 15. 实现前置验收命令

代码实现阶段至少补充并执行：

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator

PYTHONPATH=src uv run --project . --with pytest python -m pytest \
  tests/test_index_global_bootstrap_source_probe.py \
  tests/test_index_global_contracts.py \
  tests/test_index_global_partition_sensor.py \
  tests/test_index_global_raw_io.py \
  tests/test_index_global_checks.py \
  tests/test_index_global_sensors.py \
  tests/test_index_global_bootstrap_plan.py \
  tests/test_index_global_bootstrap_apply.py \
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
