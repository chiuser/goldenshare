# 主要指数历史分钟线数据集开发说明

## 0. 文档状态与模板审计

| 项目 | 结论 |
| --- | --- |
| 数据集 ID | `major_index_mins` |
| 当前阶段 | 数据集开发完成：Raw/Silver P0–P8、Gold canonical/technical 历史建设与 P10 业务读取切换均已完成；连续交易日 sensor 观察属于独立运维验收 |
| 事实源 | 当前 Dagster assets、Lake Catalog、运行合同与对应 Gold canonical LLD；本项目不进入生产 `DatasetDefinition`/TaskRun 主链 |
| 源接口 | Tushare `idx_mins` |
| 当前源接口实测 | MCP 已验证代码、起始日、停止日、五种频率和显式字段；项目 wrapper 的显式字段与 `limit/offset` 真实分页已由 P1 实测通过 |
| 依据模板 | `docs/templates/lake-dataset-development-template.md`、`docs/templates/dataset-development-template.md`、`lake_console/docs/templates/dagster-dataset-onboarding-template.html` |
| 设计依据 | `/Users/congming/github/goldenshare/AGENTS.md`、`lake_console/orchestrator/AGENTS.md`、`lake_console/orchestrator/CODING_STANDARDS.md`、`lake_console/docs/design/dagster-data-pipeline-performance-governance.md` |

本说明已按新增数据集模板补齐：基本信息、源端行为、时间输入/执行/freshness 三层语义、字段端到端追踪、Catalog、分区模型、路径、请求模式、性能预算、资产依赖、job/sensor/cursor、Bootstrap、事件验收、测试和风险清单。

本项目是 Lake Console 的 Dagster/Lake 数据集，不进入 `src/foundation/datasets/**` 的生产 `DatasetDefinition` 和 Ops TaskRun 主链。因此：

- 不新增生产 `DatasetDefinition`、`DatasetExecutionPlan` 或运营输入字段；
- 不把 Tushare 可选参数直接暴露给运营；
- Dagster Catalog、asset definition metadata、run contract 和本文件共同构成当前事实链；
- 如果以后要求接入生产 DatasetDefinition，必须另开消费者审计，不在本专项隐式扩展。

## 1. 基本信息与范围

| 字段 | 固定口径 |
| --- | --- |
| 中文名 | 主要指数历史分钟线 |
| 数据域 | `quote_data` |
| Group | `index` |
| 层级 | 本文主体为 Raw + Silver；当前业务 K 线与技术指标统一消费 Gold canonical/technical |
| 更新源 | Raw 直接 Tushare；Silver 由同日 Raw 派生；Gold canonical/technical 从验收通过的上游生成 |
| 时间输入 | Dagster 单个 `trade_date` 分区；Bootstrap 使用冻结日期计划和窗口 |
| 执行单位 | 一个 `trade_date + freq` 一个 Raw/Silver asset partition |
| 状态判断 | 最近 10 个专属 expected 日期的 DuckDB batch lake readiness；不读取 Dagster event history |
| 自动触发 | 专属交易日分区 sensor、Raw sensor、Silver/Gold sensor；设计默认状态与当前运行态分开，实际状态需走独立只读运维审计 |
| 生产写入边界 | staging Parquet 校验通过后 `os.replace`；禁止覆盖错误的既有目标 |

第一期 Raw 固定 11 个指数。10 个在线指数用于日常探测；北证50只做历史 Raw source
fact Bootstrap，不参与日常 source gate，也不进入任何 Silver 频率。

| `ts_code` | 名称 | 首个源数据日 | 最后源数据日 | 日常探测 |
| --- | --- | --- | --- | --- |
| `000001.SH` | 上证指数 | 2009-01-05 | 当前 | 是 |
| `399001.SZ` | 深证成指 | 2009-01-05 | 当前 | 是 |
| `399006.SZ` | 创业板指 | 2010-06-01 | 当前 | 是 |
| `000688.SH` | 科创50 | 2020-07-23 | 当前 | 是 |
| `000300.SH` | 沪深300 | 2009-01-05 | 当前 | 是 |
| `000905.SH` | 中证500 | 2009-01-05 | 当前 | 是 |
| `000852.SH` | 中证1000 | 2014-10-17 | 当前 | 是 |
| `899050.BJ` | 北证50 | 2022-11-21 | 2025-10-30 | 否 |
| `000510.SH` | 中证A500 | 2024-10-22 | 当前 | 是 |
| `000016.SH` | 上证50 | 2009-01-05 | 当前 | 是 |
| `000680.SH` | 科创综指 | 2025-01-20 | 当前 | 是 |

`899050.BJ` 在 `2025-10-31` 之后的空结果是已确认的源站停止事实，不生成虚假的行，
也不把它作为日常缺失。Raw 每个日期按 source scope 请求；Silver 使用 date-only output
scope，并在所有日期固定排除 `899050.BJ`，不建立按频率变化的例外集合。

## 2. 三层时间语义

### 2.1 时间输入语义

- 手工 Dagster run 输入一个 ISO `trade_date`；不输入代码列表、不输入窗口、不输入频率集合。
- Bootstrap 输入冻结的日期计划和代码 scope，不把每个可选 Tushare 参数暴露为运营字段。
- Tushare 请求内部使用 `start_date/end_date` 组成单日请求或有界历史窗口；这些是 request builder 内部参数，不是运营语义。

### 2.2 执行/unit 语义

- Raw 五个 asset 分别对应 `1m/5m/15m/30m/60m`；每个 run 处理一个 `trade_date`。
- Silver 五个原生频率分别读取同频 Raw；`90m <- 30m`，`120m <- 60m`。
- 同一日期五个频率不是操作系统级事务。每个频率独立 staging、回读和原子替换；任何频率失败都使该日期的 Raw batch readiness 为 not ready。

### 2.3 freshness/audit 语义

- 专属分区表示“该日期允许检查/生成主要指数分钟线”，不表示所有代码必须有行。
- Raw 请求代码由 source scope 与日期交集计算；Silver 输出代码在该集合上固定排除 BJ；
  scope 为空时只记录 `source_scope_empty`，不伪造文件。
- 文件缺失是可触发状态；文件存在但核心语义失败是已物化但不健康，sensor 不自动覆盖。
- 10 日 readiness 是运行门禁，不是历史完整性证明；Bootstrap 使用独立全量审计。

## 3. 源接口与真实行为矩阵

源文档：`docs/sources/tushare/指数专题/0419_股票历史分钟行情.md`。

| 请求形态 | 必填/验证结论 | 处理口径 |
| --- | --- | --- |
| 不传业务参数 | 文档要求 `ts_code`、`freq`；禁止用无参返回推断全集语义 | P1 通过项目 wrapper 做拒绝/错误分类验证 |
| 仅传 `ts_code` | 缺 `freq`，不是合法业务请求 | request builder fail closed |
| `ts_code + freq` | 已用 MCP 验证五个频率可返回样本 | 继续显式传时间范围和分页参数 |
| 单日时间范围 | MCP 样本验证：非北证指数在 2026-08-04 返回 `1m=241、5m=49、15m=17、30m=9、60m=5` | 作为 fixture 和源行数基线，不把固定行数硬编码为全历史规则 |
| 显式字段 | 已验证 `ts_code,freq,trade_time,open,close,high,low,vol,amount,exchange,vwap` 可返回；默认返回不含 `freq/exchange/vwap` | 所有正式请求都显式传 `fields` |
| `limit/offset` 分页 | 源文档给出每次最大 8000 行；MCP 当前工具不能直接提供项目 wrapper 的分页证明 | P1 必须验证 orchestrator request wrapper 的页边界、offset 递增、空页终止、跨页去重；未通过不得进入 P2 |
| 起始/停止日期 | 11 个代码的首日和北证停止日已经通过 MCP 样本/范围探测冻结 | scope 以运行合同为准，源站新变化必须产生 scope revision |

分页验证的状态必须在 P1 报告中写明 `verified=true/false`、请求参数、页数、源行数、重复键和耗时。不能因为文档中有 `limit/offset` 就提前声称分页已验证。

## 4. 字段端到端契约

Raw 与 Silver 的字段名相同，但来源和约束不同。类型以 Parquet/DuckDB contract 为准：
时间戳为 `TIMESTAMP`，数值为 `DOUBLE`，代码/频率/交易所为 `VARCHAR`。Raw 保留源值；
Silver 固定排除北证50，并对非北证执行 trim/uppercase、exchange 派生和已审计历史
OHLC 精确白名单修正。

| 字段 | 类型 | NULL | 主键/业务作用 | Raw 规则 | Silver 规则 |
| --- | --- | --- | --- | --- | --- |
| `ts_code` | `VARCHAR` | 禁止 | 与 `trade_time` 组成主键；必须属于日期有效 scope | 显式返回、trim 后格式校验 | trim + uppercase 后校验 |
| `freq` | `VARCHAR` | 禁止 | 频率身份，必须等于 asset 频率 | 必须等于请求频率 | 必须等于目标频率 |
| `trade_time` | `TIMESTAMP` | 禁止 | 与 `ts_code` 组成主键；日期和时段身份 | 日期必须等于分区；非北证按 published source grid 校验，BSE 不做 session 业务检查 | 严格校验，不跨日期/午休派生 |
| `open` | `DOUBLE` | 禁止 | OHLC | 源事实；不做 BSE 业务质量判断 | 有限数值、非负，白名单外异常失败 |
| `close` | `DOUBLE` | 禁止 | OHLC | 源事实；不做 BSE 业务质量判断 | 有限数值、非负，白名单外异常失败 |
| `high` | `DOUBLE` | 禁止 | OHLC | 源事实 | 必须覆盖 open/close/low；仅精确历史白名单可修正 |
| `low` | `DOUBLE` | 禁止 | OHLC | 源事实 | 必须覆盖 open/close/high；仅精确历史白名单可修正 |
| `vol` | `DOUBLE` | 禁止 | 成交量 | 源事实；BSE 负值不修复 | 有限数值、非负 |
| `amount` | `DOUBLE` | 禁止 | 成交额 | 源事实；BSE 负值不修复 | 有限数值、非负 |
| `exchange` | `VARCHAR` | Raw 允许源 NULL/`nan` | session grid 与交易所身份 | 忠实保留源值 | 不信任 Raw，按 `.SH/.SZ` 后缀派生 |
| `vwap` | `DOUBLE` | 允许 | 源提供的成交量加权价 | 显式请求；NULL 只能按源结果/合同解释 | 原生频率保留；若派生规则不产生可靠 vwap，写 NULL 并在 metadata 标识 |

端到端追踪：Tushare `fields` -> Raw contract -> DuckDB staging -> Raw Parquet -> Silver SQL -> Silver Parquet -> asset definition metadata `goldenshare/observed_columns` -> core check。任何字段缺失、漂移或行数变化必须有 reason code，不能靠 check 全绿掩盖。

## 5. Catalog、分区与治理注册矩阵

下面是实现阶段必须加入 `catalog/lake_assets.py` 的 12 个明确条目。当前文档阶段不修改代码；P4 必须逐条落地并通过 catalog/governance 共享门禁。

### 5.1 PartitionModel

新增两个分区模型：

| 枚举名 | Dagster 分区 | 物理布局 | 层 |
| --- | --- | --- | --- |
| `TRADE_DATE_PARTITION_RAW_MAJOR_INDEX_MINS` | `cn_major_index_mins_trade_days` | `freq=<freq>/trade_date=<date>/part-000.parquet` | Raw |
| `TRADE_DATE_PARTITION_SILVER_MAJOR_INDEX_MINS` | `cn_major_index_mins_trade_days` | `freq=<freq>/trade_date=<date>/part-000.parquet` | Silver |

专属分区注册源固定为 `silver_trade_calendar_path(lake_root)` 的 `trade_date/exchange/is_open`；过滤 `exchange='SSE' AND is_open=true AND trade_date >= '2009-01-05'`，日期去重后生成动态分区。交易日注册不调用 Tushare/Prod/event history。

### 5.2 12 个 Catalog 条目

以下字段是最小明确值；`source_doc`、`column_schema`、`path_template` 必须由代码常量引用，不能在每个 asset 内手写另一套。

| asset key | layer | dataset name | data contract | partition model | source system | source/api | blocking check |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `raw_major_index_mins_1m` | RAW | 主要指数历史分钟线 | `tushare_major_index_mins_raw_by_frequency_trade_date` | RAW_MAJOR | TUSHARE / `idx_mins` | `TUSHARE_API` | `raw_major_index_mins_1m_core_check` |
| `raw_major_index_mins_5m` | RAW | 同上 | 同上 | RAW_MAJOR | TUSHARE / `idx_mins` | `TUSHARE_API` | `raw_major_index_mins_5m_core_check` |
| `raw_major_index_mins_15m` | RAW | 同上 | 同上 | RAW_MAJOR | TUSHARE / `idx_mins` | `TUSHARE_API` | `raw_major_index_mins_15m_core_check` |
| `raw_major_index_mins_30m` | RAW | 同上 | 同上 | RAW_MAJOR | TUSHARE / `idx_mins` | `TUSHARE_API` | `raw_major_index_mins_30m_core_check` |
| `raw_major_index_mins_60m` | RAW | 同上 | 同上 | RAW_MAJOR | TUSHARE / `idx_mins` | `TUSHARE_API` | `raw_major_index_mins_60m_core_check` |
| `silver_major_index_mins_1m` | SILVER | 主要指数历史分钟线 | `silver_major_index_mins_by_frequency_trade_date` | SILVER_MAJOR | DERIVED | asset dependency | `silver_major_index_mins_1m_core_check` |
| `silver_major_index_mins_5m` | SILVER | 同上 | 同上 | SILVER_MAJOR | DERIVED | asset dependency | `silver_major_index_mins_5m_core_check` |
| `silver_major_index_mins_15m` | SILVER | 同上 | 同上 | SILVER_MAJOR | DERIVED | asset dependency | `silver_major_index_mins_15m_core_check` |
| `silver_major_index_mins_30m` | SILVER | 同上 | 同上 | SILVER_MAJOR | DERIVED | asset dependency | `silver_major_index_mins_30m_core_check` |
| `silver_major_index_mins_60m` | SILVER | 同上 | 同上 | SILVER_MAJOR | DERIVED | asset dependency | `silver_major_index_mins_60m_core_check` |
| `silver_major_index_mins_90m` | SILVER | 同上 | 同上 | SILVER_MAJOR | DERIVED | asset dependency | `silver_major_index_mins_90m_core_check` |
| `silver_major_index_mins_120m` | SILVER | 同上 | 同上 | SILVER_MAJOR | DERIVED | asset dependency | `silver_major_index_mins_120m_core_check` |

所有条目的公共值：`group_name=index`、`data_domain=QUOTE_DATA`、`write_policy=PARTITION_FILE_ATOMIC_REPLACE`、`event_policy=SUPPORTS_RUNLESS_EVENT_BACKFILL`、compute engine 为 `DUCKDB_SQL`。Raw 的 `default_daily_ingestion_source=TUSHARE_API`；Silver 为 `DERIVED_FROM_ASSETS`。

### 5.3 Governance mapping

`tests/test_asset_check_incremental_governance.py` 中必须加入上述 12 个 asset 的精确 check 映射。治理规则统一为：`blocking=true`、进入 readiness、普通历史事件只保留最近 20 个交易日；不新增 repair/status check。规则名、check 集合和 Catalog 必须完全相等，不能添加空壳映射。

同时在 `catalog/name_mapping.py` 增加：

```text
"major_index_mins": "主要指数历史分钟线"
```

## 6. 依赖、Definition 装配与元数据

### 6.1 Asset dependencies

- Raw 五个 asset 不依赖运行时 `index_basic` 或 `ops.index_series_active`；11 个 scope 是本数据集的冻结合同，`index_basic` 只在 P0/P1 做核验，不作为日常依赖。
- Silver `1/5/15/30/60m` 只依赖同频 Raw；Silver `90m` 依赖 `silver_major_index_mins_30m`；Silver `120m` 依赖 `silver_major_index_mins_60m`。
- `defs/definitions.py` 继续由 `load_from_defs_folder(...)` 装配；新增模块必须放在 `defs/assets`、`defs/checks`、`defs/jobs`、`defs/sensors` 等已扫描目录，并由测试确认 definitions 可加载。

每个 asset definition metadata 必须使用公共 builder，至少含：dataset id/name、source system、source api/doc、data contract、column schema、path template、scope revision/hash、write boundary。Materialization metadata 只放当前分区的 uri、row/source rows、frequency、scope hash、request/page/retry/elapsed 摘要。Core check metadata 只放 scope、partition、checked/failed rows、failed rules、有限样本。

### 6.2 Run config、run key 与 cursor

| 项目 | 固定口径 |
| --- | --- |
| typed run config | 只包含 `trade_date` 隐含分区、目标 `source_freq`/asset 由 job 固定；Bootstrap 使用独立 CLI config，不写 sensor tags |
| update run key | `build_asset_update_run_key(subject="raw_major_index_mins_update", unit_id=trade_date)`；Silver 使用 `silver_major_index_mins_update` |
| cursor builder | 必须调用 `build_sensor_cursor()`，details 必须有 `summary`、`next_action`、ASCII `reason_code` |
| cursor 内容 | `sensor_name/asset_family/partition_set/reason_code/frontier/evidence/performance_ms`；只写计数、日期、scope hash、probe count/elapsed、有限样本 |
| cursor 禁止项 | 完整代码列表、完整 readiness report、路径列表、event storage id、逐页明细；总字节 <= 8192 |

新增配置必须在代码、文档和测试中审计：配置名、默认值、来源、消费者和生效方式。候选配置包括 `MAJOR_INDEX_MINS_*` 常量和 `TUSHARE` 请求预算；它们优先使用版本化 run contract 常量，不新增 env 开关，除非 P1 性能验证证明运维需要可调参数。

## 7. 请求、性能和拒绝策略

### 7.1 日常

- Raw run：10 个在线代码 × 5 频率 = 50 个基础代码频率请求，分页请求数另计；sensor 只做 10 个在线代码的 1min 轻探测。
- 每次请求显式 `limit=8000`、递增 `offset`、`fields`；单日总请求数、重试数、总耗时必须有上限。
- sensor 只扫描最近 10 日，1 个 DuckDB connection，最多 1 个 RunRequest，不触碰 event history。
- 任一频率分页不完整、代码集合不一致、字段漂移、预算超限，当前频率不 promote，日期 batch not ready；不以空数据覆盖旧文件。

### 7.2 Bootstrap

Bootstrap 先冻结日期计划 fingerprint，再按 `code + freq + window` 请求：

| freq | 最大交易日窗口 | 预估单窗行数上限 | 失败处理 |
| --- | ---: | ---: | --- |
| 1min | 20 | 5,420 | 满页或未知时段二分 |
| 5min | 60 | 3,300 | 同上 |
| 15min | 120 | 2,280 | 同上 |
| 30min | 180 | 1,080 | 同上 |
| 60min | 240 | 1,440 | 同上 |

P6 只计算日期、窗口、基础请求、预计行数、目标文件和磁盘预算，不再全量请求 Tushare。真实请求统一进入 P7 的可恢复 source staging；请求结果先持久化，再从同一份 staging 做分页、行数、主键、session 和 OHLC 审计。任一窗口返回满页但无法证明完整、总请求超过 5,000、预计磁盘不足或内存不满足时停止，不降级为截断写入，也不通过重新全量请求来重复审计。

### 7.3 历史 source-empty Silver fallback

P7 source staging 只读审计已经确认：除北证50外，130 个历史
`code + trade_date + target_freq` 缺口都有完整的更细频率源数据。该结论只放行
开发期 Silver fallback，不改变 Raw 和日常链路：

- Raw 继续忠实保存 Tushare 返回事实。源站为空或部分缺失时，不把聚合结果写成 Raw；
- Silver 只允许在精确白名单内执行 `1min -> 5min`、`5min -> 15min`、
  `5min -> 30min`、`5min -> 60min`；
- fallback 只读取已经保留的 source staging 或由其生成的临时 Raw，不再请求
  Tushare；
- Parquet 字段合同不增加 provenance 列。`source_mode=derived_fallback`、
  `source_freq`、reason code、source revision 和规则 fingerprint 写入 Bootstrap
  报告/运行 metadata；
- fallback 的 `vwap` 固定为 `NULL`；OHLCV/amount 使用完整窗口 set-based
  聚合；
- 先补齐 30min/60min，再生成 90min/120min，禁止用不完整基础频率继续派生；
- 该入口不注册 asset/job/sensor，不进入日常 readiness，也不允许按日期范围自动扩大。

已验证的 130 个目标全部可生成 expected bar count。`5min -> 15/30/60min`
在 260 个相邻健康对照 scope 中 OHLC 完全一致，成交量/成交额只有源精度级差异；
`1min -> 5min` 的源端跨频 OHLC 并非逐条一致，因此 `2010-09-02` 使用标准
1min 窗口聚合，明确标记为 derived fallback，不宣称复刻当日不存在的 native 5min。

## 8. Sensor、Bootstrap、事件与恢复

### 8.1 Sensor 时间与补洞

分区注册 sensor 只根据交易日历注册；Raw sensor 不固定“某个源站收盘时间”作为成功条件，而是在每次 tick 对候选缺口做有限 1min probe。probe 必须记录 `probe_at`、代码数、返回代码数、返回行数、耗时、错误分类。源站尚未完成时 skip；网络可重试错误在 probe policy 内有限重试；不可重试错误写 ASCII reason 并 skip。后续 tick 重新探测，因此 DG 停止或网络中断不会永久丢失日期。

如果 10 个在线代码中有一个未来永久停止：

1. probe 连续失败/空结果不能自动把它移出 scope；
2. 产生 `source_scope_change_required` 报告；
3. 人工更新版本化 source scope、source revision、起止日和测试 fixture；
4. 更新后才允许 sensor 使用新 scope。禁止静默永久等待或动态猜测代码集合。

### 8.2 Bootstrap

- P6 dry-run 只做无源请求的计划和目标冲突审计。
- P7 先把每个 `code + freq + window` 的 Tushare 原始响应和有限请求 metadata 写入可恢复 source staging。已完整落盘且 fingerprint/hash 匹配的窗口续跑时跳过，不重复请求。
- source staging 全量完成后只读审计。审计结果按“非北证可修复缺口”和“Raw-only
  BSE/非北证源异常”拆分；
- 非北证 Silver fallback 已完成；P7C 已冻结 BSE Raw-only、Silver 永久排除，以及
  非北证 OHLC/exchange 清洗合同；
- 只有上述两类合同都通过后，才从同一 staging 生成完整临时 Raw/Silver lake；完成全量对账后才逐文件原子 promote 到正式 lake。
- 目标文件不存在才写；存在且正确则 skip；存在但错误停止，禁止 overwrite。
- 事件补录独立于文件生成：全量文件通过后，materialization 对全部成功分区补录；check event 只补最近 20 个分区；每个 check event 必须带正确 `partition`。
- 事件补录采用 runless 工具，先 dry-run/小样本，再全量；失败日期停止，不删除旧 event，不通过无 partition 聚合事件冒充分区事件。

### 8.3 失败恢复

| 故障 | 自动行为 | 人工恢复 |
| --- | --- | --- |
| DG 停止/重启 | 下一 tick 重新计算最近窗口和 first-not-ready | 无需重跑已通过文件 |
| Bootstrap Tushare 暂时网络失败 | bounded retry；仍失败则当前 source window 不完成，已成功窗口保留 | 按 staging 账本只续跑失败/未完成窗口 |
| 某频率失败 | 只保留该频率旧目标，batch not ready | 修复后重跑该 `trade_date + freq` |
| 文件存在但合同失败 | sensor skip，不自动覆盖 | 审计后独立 repair/bootstrap |
| 源 scope 变化 | fail closed，不猜测新集合 | 更新 scope revision 后定点重跑 |
| 事件补录失败 | 不影响已通过湖文件 | 重跑 runless event dry-run/apply |

## 9. 测试与验收

必须新增/回归：

```text
tests/test_major_index_mins_contracts.py
tests/test_major_index_mins_tushare_probe.py
tests/test_major_index_mins_raw_writer.py
tests/test_major_index_mins_bootstrap.py
tests/test_major_index_mins_silver_writer.py
tests/test_major_index_mins_checks.py
tests/test_major_index_mins_lake_readiness.py
tests/test_major_index_mins_sensors.py
tests/test_major_index_mins_definitions.py
tests/test_run_contract_static_gates.py
```

负向测试必须覆盖：未验证分页、空 scope、scope 起止边界、北证停止日、字段漂移、offset 不递增、跨页重复、目标冲突、单频失败、日期错位、时间网格错、cursor 超限、event history 调用、缺 catalog/governance 映射。验收必须有真实最小 Tushare 请求和临时 Lake smoke；正式写入前不写正式 Lake/Dagster DB。

## 10. 开发前硬门禁清单

- [x] P1 已真实验证项目 wrapper 的显式 fields 与 `limit/offset` 分页；page limit 压到 2 时实际完成 3 页、5 行、0 重试。
- [x] 已冻结 11 个 source scope、生命周期和稳定 scope fingerprint。
- [x] 已用真实样本锁定 SH/SZ 五频 session grid，并完成 90m/120m fixture；BSE 历史样本
  只用于确认 Raw source anomaly，不再形成 Silver/session/check 合同。
- [x] 已新增 12 个 Catalog 条目、2 个 PartitionModel、中文名和 12 个 governance mapping。
- [x] 已落实 definition、materialization、check metadata 三层边界。
- [x] 已按 `build_sensor_cursor()` 完成 cursor schema/大小/ASCII 测试；三个 sensor 默认 `STOPPED`，每 tick 最多一个 RunRequest。
- [x] 已输出 P6 Bootstrap 请求/文件/磁盘预算，并确认旧“请求后丢弃”审计方式必须废弃。
- [x] P8 已按 dry-run、样本、分资产 apply、最终对账四阶段完成历史 materialization/check 事件补录。
- [x] 可恢复 source staging、只读审计、临时 Raw/Silver build/audit 和正式 promote 入口已完成代码与 fake-source 全链路测试；源请求与正式 lake 写入使用两个独立确认开关。
- [x] 完整专项回归、`dg check defs`、`git diff --check` 已通过；P7 source staging 已完成且未写正式 lake/event。
- [x] 已只读证明 130 个非北证历史缺口均有完整低级别源数据；审计 260 个健康对照 scope，结果写入 `/private/tmp/major_index_mins_non_bse_fallback_audit_20260806.json`。
- [x] 已实现并测试精确白名单的非北证 Silver fallback；15 条规则展开为 130 个 scope，整批只用一个 DuckDB connection，源请求和 Dagster event history 查询均为 0，未接入日常 sensor。
- [x] 已从 retained staging 完成 P7B 全量临时重建：15 个 Parquet、1,482 行、10 个 source revision、0 个 post-audit 违规，报告为 `/private/tmp/major_index_mins_p7b_fallback_report_20260806.json`。
- [x] P7C 合同已冻结：北证50 Raw-only、Silver 永久排除；30 行 sentinel、105 行
  envelope 和 exchange 派生按精确规则处理。
- [x] P7C 代码和 retained-staging 真实临时样本已完成；P7D 完整临时湖、P7E 正式 promote 与 P8 事件补录也已依次完成。

## 11. 开发收口与后续运维

Raw/Silver 的 P0–P8 已完成；Gold canonical bars、Gold technical/state 的正式历史建设、事件对账与 P10 业务 Reader 切换也已按 [A 股分钟线 Gold 标准 K 线合同与历史重建 LLD](../../lake_console/docs/design/dagster-cn-a-minute-gold-canonical-bars-rebuild-low-level-design.md)完成。当前业务读取只允许 Gold bars + Gold indicators，不再读取 Silver，也不保留 fallback。

尚未并入“开发完成”的只有运维观察：P9/P11 需要在单独批准下核对 sensor 启用状态，并观察连续三个实际交易日的自然触发、blocking checks、freshness 与失败恢复。它不表示数据集、Gold 业务合同或指数分钟页面仍有待开发功能，也不授权本轮读取 Dagster instance、启停 sensor、运行 job 或写 Lake。

P7 source staging、P7B fallback、P7C 分层合同、P7D 临时湖、P7E 正式 promote 和 P8 事件补录的日期化执行证据继续保留在方案与 LLD 中。各阶段“当时未写正式 Lake/未补事件”的文字只描述阶段边界，不得再解释为当前状态。

详细设计：

- [主要指数分钟线接入方案](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-major-index-mins-data-onboarding-plan.md)
- [主要指数分钟线 LLD](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-major-index-mins-data-onboarding-low-level-design.md)
