# Dagster 主要指数历史分钟线接入方案

## 1. 目标与边界

新增独立数据集 `major_index_mins`，用于保存主要指数历史分钟线：

- Raw 直接从 Tushare `idx_mins` 获取；
- Silver 清洗 Raw，并生成原生五频与 `90min`、`120min` 派生频率；Silver 固定排除
  `899050.BJ`；
- Bootstrap 覆盖每个指数从 Tushare 实际首个分钟数据日到当前；
- 日常更新只探测仍有稳定源数据的 10 个指数，满足源站自审计门禁后再提交当日 Raw run；
- `899050.BJ` 北证50只作为 Raw 历史源事实保存，不进入任何 Silver 频率、Silver
  readiness 或专属 check；已知最后可用源数据日为 `2025-10-30`。

本专项不修改现有 `index_mins` 数据集，不复用现有 `ops.index_series_active`，不迁移现有文件，不覆盖既有资产、job、sensor、partition 或 check。

## 2. 源站核验结论

Tushare `index_basic` 与 `idx_mins` 已通过 MCP 只读核验。第一期代码固定为：

| ts_code | 名称 | 首个 `idx_mins` 数据日 | 日常探测 |
| --- | --- | --- | --- |
| `000001.SH` | 上证指数 | `2009-01-05` | 是 |
| `399001.SZ` | 深证成指 | `2009-01-05` | 是 |
| `399006.SZ` | 创业板指 | `2010-06-01` | 是 |
| `000688.SH` | 科创50 | `2020-07-23` | 是 |
| `000300.SH` | 沪深300 | `2009-01-05` | 是 |
| `000905.SH` | 中证500 | `2009-01-05` | 是 |
| `000852.SH` | 中证1000 | `2014-10-17` | 是 |
| `899050.BJ` | 北证50 | `2022-11-21` | 否，至 `2025-10-30` |
| `000510.SH` | 中证A500 | `2024-10-22` | 是 |
| `000016.SH` | 上证50 | `2009-01-05` | 是 |
| `000680.SH` | 科创综指 | `2025-01-20` | 是 |

`000688.SH` 是科创50，科创综指是 `000680.SH`。

源站五种频率均核验通过：`1min`、`5min`、`15min`、`30min`、`60min`。业务字段必须显式请求：

```text
ts_code,freq,trade_time,open,close,high,low,vol,amount,exchange,vwap
```

默认返回字段不含 `freq`、`exchange`、`vwap`，不能依赖默认字段。

## 3. 数据集命名与物理布局

数据集 ID：`major_index_mins`。

Raw assets：

```text
raw_major_index_mins_1m
raw_major_index_mins_5m
raw_major_index_mins_15m
raw_major_index_mins_30m
raw_major_index_mins_60m
```

Silver assets：

```text
silver_major_index_mins_1m
silver_major_index_mins_5m
silver_major_index_mins_15m
silver_major_index_mins_30m
silver_major_index_mins_60m
silver_major_index_mins_90m
silver_major_index_mins_120m
```

物理布局：

```text
raw/tushare/major_index_mins/freq=<freq>/trade_date=<YYYY-MM-DD>/part-000.parquet
silver/quote/major_index_mins/freq=<freq>/trade_date=<YYYY-MM-DD>/part-000.parquet
```

所有层使用专属动态分区：`cn_major_index_mins_trade_days`。不使用当前 `cn_a_index_mins_trade_days`。

## 4. 时间与源范围语义

分区日历从 `2009-01-05` 开始，来源为现有交易日历中的中国市场开市日。分区代表“该日允许生成主要指数分钟数据”，不代表 11 个指数在该日全部应该有行。

某日期的 Raw 请求代码集合为：

```text
source_start_date <= trade_date <= source_end_date
```

其中：

- 10 个日常指数只有 `source_start_date`；
- `899050.BJ` 的 `source_start_date=2022-11-21`、`source_end_date=2025-10-30`；
- 低于起点或高于终点的代码不进入该日期的 Raw request code set；
- Raw request code set 为空的日期不生成目标文件，并进入 Bootstrap/审计报告，不作为日常分区缺失。

Silver 输出代码集合使用同一日期 scope，但固定排除 `899050.BJ`。因此 Raw 请求范围最多
11 个指数，Silver 最多 10 个指数；北证50历史缺行、错误网格和值域异常不再进入 Silver
合同。

## 5. Raw 方案

### 5.1 请求

日常单分区、单频率请求由 bounded Tushare request policy 执行：

- API：`idx_mins`；
- `ts_code` 单代码；
- `freq` 为当前 Raw 频率；
- `start_date`/`end_date` 精确限制到一个交易日；
- 显式 `limit`、`offset`、`fields`；
- 严格校验分页 offset、返回列、跨页主键和行数；
- 失败、分页不完整或预算超限时整日 fail-closed。

日常 Raw run 对 10 个在线指数和 5 个频率请求，预计最多 50 个基础请求；sensor 不执行这 50 个请求。

### 5.2 Bootstrap

Bootstrap 不用“一个代码覆盖全历史”的无界请求。按单个 `ts_code + freq` 采用交易日窗口：

| 频率 | 最大交易日窗口 | 单窗理论最大行数（含北证安全余量） |
| --- | ---: | ---: |
| `1min` | 20 | 约 5,420 |
| `5min` | 60 | 约 3,300 |
| `15min` | 120 | 约 2,280 |
| `30min` | 180 | 约 1,080 |
| `60min` | 240 | 约 1,440 |

实际 writer 必须在每窗校验 `row_count < 8000`。达到分页上限时自动二分窗口，不允许把截断结果当作完整结果。

每次只保留一个代码、一个频率、一个窗口的有界结果；先进入 DuckDB 临时表，再按交易日输出 Raw staging 文件。所有目标日期校验通过后逐文件原子替换。

## 6. Silver 方案

- 所有日期、所有频率固定过滤 `899050.BJ`；
- 五个原生频率从对应 Raw 清洗生成；
- `90min` 从 `30min` 派生；
- `120min` 从 `60min` 派生；
- 复用现有指数分钟线的交易时段窗口聚合语义；
- 不逐代码、逐行 Python 计算；
- DuckDB 一次完成窗口聚合、字段规范化、主键检查和 staging 回读；
- 所有目标 staging 校验成功后才替换已有文件；
- 失败不得覆盖既有 Silver 文件。

### 6.1 历史缺口 fallback 边界

历史 Bootstrap 的 source staging 保留 Tushare 原始事实，Raw 不写入任何计算补造行。
已验证可修复的历史缺口只在 Silver 层处理：

- 规则必须来自版本化精确白名单，键为 `trade_date + target_freq`，值包含
  `source_freq + target_codes + reason_code`；
- 当前只允许 `1min -> 5min` 和 `5min -> 15/30/60min`；
- 只允许非北证代码，禁止日期范围扩展、自动推断或复用到日常 sensor；
- 每个 target window 的 source row count 必须完整；任一代码、窗口、时间点缺失即
  fail closed；
- fallback `vwap=NULL`，provenance 写报告/metadata，不改变 11 列 Parquet schema；
- 30min/60min fallback 完成并验收后，90min/120min 才能沿用普通派生 writer；
- 该能力是开发期 Bootstrap helper，不新增 asset、job、sensor 或长期 repair 入口。

只读验证报告 `/private/tmp/major_index_mins_non_bse_fallback_audit_20260806.json`
已证明 130/130 个非北证目标 scope 可生成完整 expected bar count，并用 260 个相邻
健康 scope 做了算法对照。这个结论不覆盖北证50，也不放行完整临时湖。

## 7. Check 设计

每个 Raw/Silver asset 保留一个 partitioned blocking core check：

- Raw 5 个；
- Silver 7 个；
- 总计 12 个 check。

每个 check 统一检查：文件存在且非空、schema、分区日期、频率、有效代码集合、主键 `(ts_code, trade_time)` 唯一、时间范围和值域。分页、请求预算、重试次数和源站空响应在 writer 门禁及 materialization metadata 中表达，不拆成额外 check event。

Raw check 只对北证50执行文件级 schema、分区、频率、允许代码和全文件主键安全校验，
不执行 BSE 代码覆盖、session、OHLC、成交量或 exchange 业务检查。Silver check 的
date-only output scope 永远不包含北证50。不存在按指数拆分的 check，也不新增 BSE check；
每交易日最多仍为 12 条 check event。

## 8. 日常 Sensor

新增专属：

- `major_index_mins_trade_day_sensor`：只注册 `cn_major_index_mins_trade_days`；
- `raw_major_index_mins_update_job_sensor`：选最早 Raw 缺口；
- `silver_major_index_mins_update_job_sensor`：Raw ready 后选最早 Silver 缺口。

Sensor 默认 `STOPPED`，启用前必须完成 Bootstrap、事件和临时湖验收。

Raw sensor 热路径：

1. 最近 10 个 expected 日期一次 DuckDB batch readiness；
2. 选择最早缺口，不扫描 Dagster event history；
3. 对候选日期只探测 10 个日常指数的 `1min` 小窗口；
4. 10 个指数全部返回目标日数据，才提交一个单分区 Raw run；
5. 北证50不参与日常探测和日常阻断；
6. sensor 每 tick 最多一个 RunRequest，cursor 只保存小型 ASCII 原因和 frontier。

Raw writer 仍会对五个频率执行完整 source contract；若某频率缺失，整日不替换文件。该失败由下一次 bounded sensor probe 或人工重试恢复，不把不完整结果落湖。

Silver sensor 只读取 Raw/Silver lake readiness，不调用 Tushare、Prod DB 或事件历史；Raw 已物化但 core check 失败时禁止自动覆盖。

## 9. 性能门禁

- Bootstrap 单请求最大 8,000 行，窗口上限和二分策略固定；
- Bootstrap 预计请求量在 5,000 次以内，dry-run 必须给出精确值，超限停止；
- 日常 Raw 最多 50 个数据请求，sensor 最多 10 个轻量探测请求；
- sensor 最近窗口 10 日、一个 DuckDB connection、最多一个 run；
- 禁止全历史 lake 扫描、Dagster event history 扫描和无界 Python 缓存；
- 单日期只创建有限 staging 文件；失败清理临时文件；
- 请求间隔、重试次数、单日期请求数和总耗时必须有预算；
- 性能异常只能调整窗口/批次设计，不得放宽完整性语义。

## 10. 实施顺序

1. P0：冻结代码集合、source scope、字段合同和专属分区；
2. P1：Tushare request builder、分页和最早日期/停止日期契约测试；
3. P2：Raw bootstrap writer、DuckDB staging、原子替换；
4. P3：Silver 原生/派生 writer 和窗口测试；
5. P4：Raw/Silver asset、core check、catalog/governance、job；
6. P5：专属分区注册、bounded readiness 和 sensors；
7. P6：Bootstrap dry-run、请求量/磁盘/耗时验证；
8. P7A：一次性 source staging 与只读源事实审计；
9. P7B：非北证 bounded Silver fallback 合同、实现、样本和性能验证；
10. P7C：Raw-only BSE、Raw/Silver scope 拆分和非北证精确清洗合同；
11. P7D：完整临时 Raw/Silver build 与全量文件对账；
12. P7E：单独批准后 promote 正式 lake；
13. P8：补 materialization、最近 20 日 check event；
14. P9：启用 sensor，观察至少 3 个交易日。

## 11. 明确不做

- 不修改现有 `index_mins`；
- 不使用 `ops.index_series_active`；
- 不把 11 个代码全局绑定到每个历史分区；
- 不为北证50源站空结果补造数据；
- 不在 sensor 中请求五频全量数据；
- 不通过增加 check 数量表达请求层诊断；
- 不在本阶段写正式湖或 Dagster event。

## 12. 新增数据集模板审计与代码事实对账

本节是对 `lake-dataset-development-template.md`、`dataset-development-template.md` 和 Dagster onboarding 模板的逐项收口。它不是泛化说明，而是本专项进入编码前的硬门禁。

| 模板要求 | 本专项落点 | 当前状态/验收 |
| --- | --- | --- |
| dataset card | 本方案第 1、3、4、5、6、9 节和开发说明第 1 节 | 文档已补齐；代码以 Catalog/asset metadata 为最终验收 |
| source behavior matrix | 本方案第 2 节与开发说明第 3 节 | 字段、五频、起止日已 MCP 核验；项目 wrapper 分页仍待 P1 |
| time/input/execution/freshness split | 开发说明第 2 节 | 已冻结；不新增生产 DatasetDefinition |
| catalog/partition/name/governance | 本方案第 13 节 | 12 条 catalog、2 个 partition model、中文名和 12 条 governance 必须在 P4 代码落地 |
| field end-to-end traceability | 开发说明第 4 节、LLD 第 11 节 | 必须有类型、NULL、主键、源字段和拒绝原因 |
| request/paging/performance | 本方案第 5、9、14 节 | 所有预算先写死，P1/P6 实测后才能放行 |
| jobs/sensors/run key/cursor | 本方案第 6、7、15 节 | 必须复用统一 builder，cursor <=8KB |
| bootstrap/recovery/event | 本方案第 8、16 节 | 文件生成、事件补录和日常启用分阶段，不能混为一次操作 |
| tests/acceptance | 本方案第 17 节 | 正反例和正式前后只读验收均需记录报告 |

本专项不把 `DatasetDefinition` 的缺失当作遗漏：当前数据集属于 `lake_console/orchestrator` 的 Dagster Lake Catalog 范围，生产 DatasetDefinition/TaskRun 如果未来需要，必须另行建立数据集事实源并做全量消费者审计。

## 13. Catalog、PartitionModel 与 governance 精确矩阵

### 13.1 PartitionModel

需要新增以下两个枚举/定义，不能复用当前 `TRADE_DATE_PARTITION_RAW_INDEX_MINS` 和 `TRADE_DATE_PARTITION_SILVER_INDEX_MINS`，因为物理事实源、代码集合、源接口和日常触发口径不同：

| 定义 | 值/分区 | physical layout | asset family |
| --- | --- | --- | --- |
| `TRADE_DATE_PARTITION_RAW_MAJOR_INDEX_MINS` | `cn_major_index_mins_trade_days` | `freq=<freq>/trade_date=<date>/part-000.parquet` | `major_index_mins_raw` |
| `TRADE_DATE_PARTITION_SILVER_MAJOR_INDEX_MINS` | `cn_major_index_mins_trade_days` | `freq=<freq>/trade_date=<date>/part-000.parquet` | `major_index_mins_silver` |

分区注册只读取 `silver_trade_calendar_path(lake_root)` 的 `trade_date/exchange/is_open`，过滤 `SSE + open + date >= 2009-01-05`。空 effective code set 不删除分区；它只代表该日期没有需要生成的有效主要指数行，并进入报告。

### 13.2 Catalog 条目

P4 必须在 `lake_assets.py` 中生成 12 个条目，且每条包含完整的 `asset_key/dataset_id/dataset_name/layer/data_domain/group_name/source_system/data_contract/data_contract_source/column_schema/path_template/partition_model/source_api/source_doc/ingestion_sources/default_daily_ingestion_source/bootstrap_sources/blocking_check_names/write_policy/event_policy/performance_contract`。

| asset family | asset keys | source system | contract | source/check |
| --- | --- | --- | --- | --- |
| Raw | `raw_major_index_mins_{1,5,15,30,60}m` | `TUSHARE` | `tushare_major_index_mins_raw_by_frequency_trade_date` | `idx_mins` / 同频 `raw_major_index_mins_*_core_check` |
| Silver | `silver_major_index_mins_{1,5,15,30,60,90,120}m` | `DERIVED` | `silver_major_index_mins_by_frequency_trade_date` | asset dependency / 同频 `silver_major_index_mins_*_core_check` |

公共 Catalog 值固定为：`dataset_id=major_index_mins`、中文名 `主要指数历史分钟线`、`group_name=index`、`data_domain=QUOTE_DATA`、Raw `ingestion_sources=(TUSHARE_API,)`、Silver `bootstrap_sources=(DERIVED_FROM_ASSETS,)`、`write_policy=PARTITION_FILE_ATOMIC_REPLACE`、`event_policy=SUPPORTS_RUNLESS_EVENT_BACKFILL`。Raw `default_daily_ingestion_source=TUSHARE_API`；Silver 无 Tushare default source。

### 13.3 Governance

`tests/test_asset_check_incremental_governance.py` 必须逐一加入 12 个 asset/check 对：

```text
raw_major_index_mins_1m    -> raw_major_index_mins_1m_core_check
raw_major_index_mins_5m    -> raw_major_index_mins_5m_core_check
raw_major_index_mins_15m   -> raw_major_index_mins_15m_core_check
raw_major_index_mins_30m   -> raw_major_index_mins_30m_core_check
raw_major_index_mins_60m   -> raw_major_index_mins_60m_core_check
silver_major_index_mins_1m   -> silver_major_index_mins_1m_core_check
silver_major_index_mins_5m   -> silver_major_index_mins_5m_core_check
silver_major_index_mins_15m  -> silver_major_index_mins_15m_core_check
silver_major_index_mins_30m  -> silver_major_index_mins_30m_core_check
silver_major_index_mins_60m  -> silver_major_index_mins_60m_core_check
silver_major_index_mins_90m  -> silver_major_index_mins_90m_core_check
silver_major_index_mins_120m -> silver_major_index_mins_120m_core_check
```

治理类别为普通 `blocking/readiness/recent-window` 规则：进入 readiness，普通历史事件只保留最近 20 个专属分区；不增加 repair/status check。Catalog check 集合与治理映射必须 exact match。

`catalog/name_mapping.py` 必须增加：

```python
"major_index_mins": "主要指数历史分钟线"
```

## 14. 字段、session grid 与 source revision

Raw/Silver 统一字段和类型如下：

| 字段 | 类型 | NULL | 约束 |
| --- | --- | --- | --- |
| `ts_code` | `VARCHAR` | 否 | Raw 属于日期有效 source scope；Silver 属于排除 BSE 后的 date-only scope |
| `freq` | `VARCHAR` | 否 | 等于目标频率 |
| `trade_time` | `TIMESTAMP` | 否 | 全层分区日期一致；非北证 Raw 和全部 Silver 执行 SH/SZ session；BSE Raw 不做 session 业务检查 |
| `open/close/high/low/vol/amount` | `DOUBLE` | 否 | BSE Raw 忠实保存源值；非北证 Raw 和全部 Silver 按各层合同校验，Silver 只允许精确白名单修正 |
| `exchange` | `VARCHAR` | Raw 允许源 NULL/`nan`，Silver 否 | Raw 保存源值；Silver 按 `.SH/.SZ` 后缀派生并校验 |
| `vwap` | `DOUBLE` | 是 | Raw 显式请求；Silver 原生保留，派生按合同可为 NULL |

业务主键固定为 `(ts_code, trade_time)`。`freq` 是身份字段，不重复塞入主键；每个频率独立物理资产和 check。

Session grid 只对非北证 Raw 和全部 Silver 生效，并复用当前 `index_mins` 的 SH/SZ
session helper。北证50只保留 Raw 源事实，不补 BSE fixture、不做 session 业务检查、
不参与 Silver 派生；Raw 仍禁止跨分区日期和全文件重复主键。

source scope hash 只证明日期有效 code set；另新增 `source_revision`：对每个 `code + freq + date/window` 的请求参数摘要、返回排序后的 `(ts_code,trade_time,fields)` 内容摘要和 scope revision 做稳定哈希。source revision 写 materialization metadata 和 Bootstrap/离线报告，不写 sensor cursor，不用完整代码列表替代它。

如果在线 10 个代码未来停止，不能静默无限等待：先输出 `source_scope_change_required`，冻结当前批次；人工修改版本化 scope、起止日、scope hash、source revision fixture 和测试后，才恢复 sensor。

## 15. Sensor、typed config 与恢复口径

### 15.1 Sensor 时间与有限探测

Raw sensor 以 `minimum_interval_seconds=600` 为基线，默认 `STOPPED`。不把一个固定收盘时间作为“源一定完成”的证明。每次 tick：

1. 从专属交易日分区的最近 10 个 expected dates 中选 first-not-ready；
2. 仅对当前候选日期的 10 个在线代码做 1min 小窗口 probe；
3. 可重试网络错误按 bounded policy 重试，不可重试错误 skip；
4. 10 个代码全部返回目标日非空样本才发一个 RunRequest；
5. DG 停止或网络失败后下一 tick 重新探测，因此不会永久丢洞；
6. 北证50不参与日常 probe，历史停止日由 source scope 处理。

sensor 不调用 Tushare 五频全量、不访问 Prod DB、Dagster event history 或 `get_event_records`。

### 15.2 typed run config

日常 update 任务的业务日期来自 Dagster `partition_key`；不把 retry 信息、完整 code set 或 request pages 放入 tags。若实现需要人工重试窗口，使用 typed config/CLI 参数，字段名和默认值必须进入配置审计表，且不得让 sensor 自由生成非合同参数。

### 15.3 cursor

必须调用 `build_sensor_cursor()`，details 至少包含：`sensor_name`、`job_name`、`asset_family`、`partition_set`、`reason_code`、`summary`、`next_action`、`frontier`、`evidence`、`performance_ms`。`reason`/`reason_code` ASCII；不写完整报告、路径列表、完整代码集合或 event storage id；总大小 <= 8192 bytes。测试覆盖 request/skip/blocked/ready 四态。

### 15.4 失败恢复

| 状态 | sensor | 人工动作 |
| --- | --- | --- |
| 文件缺失 | 可提交最早缺口 | 单日重试或等待下一 tick |
| 文件存在且 check 失败 | skip，不覆盖 | 只读审计后独立 repair |
| 某频率分页/校验失败 | 当前频率不 promote，整日 not ready | 修复后定点重跑 |
| Tushare 暂时失败 | 有界重试，失败留 skip | 下一 tick 恢复 |
| scope 发生变化 | fail closed | 更新 scope revision 后定点重跑 |

## 16. Bootstrap 与事件验收

Bootstrap 必须六阶段，请求只发生一次：

1. plan dry-run：不调用 Tushare，只计算日期、窗口、预计请求/行数/文件/磁盘和正式目标冲突；
2. source staging：经单独批准后，每个窗口请求一次并原子写入可恢复 staging，同时保存有限请求 sidecar；
3. staging audit：只读取 staging，验证 schema、分页、行数、scope、session、主键、source revision 和业务值；失败时保留 staging，不重复请求；
4. historical contract：完成非北证 bounded Silver fallback，再落实 BSE Raw-only、
   Silver 排除和非北证异常精确清洗；
5. temporary lake build：从同一 staging 生成完整 Raw/Silver 临时湖并全量对账；
6. promote/final reconciliation：仅在 staging 与临时湖全部通过后逐文件原子 promote，支持幂等续跑。

事件补录独立成 P8：

- materialization：所有通过全量文件对账的 Raw/Silver 分区；
- check：只补最近 20 个 `cn_major_index_mins_trade_days` 分区；
- 每个事件显式带 `partition`，禁止 multi-partition 一个 check event；
- 先 dry-run/小样本，再正式 runless apply，再 post-read-only 验收；
- 事件补录失败不改湖文件，也不删除历史事件。

## 17. 开发与验收步骤

| 阶段 | 工作 | 通过条件 |
| --- | --- | --- |
| P0 | 固定 scope、字段、路径、分区和治理矩阵 | 文档、合同无矛盾 |
| P1 | Tushare request builder、显式 fields、真实分页、错误分类 | 项目 wrapper 分页正反例通过 |
| P2 | Raw staging/回读/原子替换 | 临时 Lake 失败不覆盖 |
| P3 | Silver 原生/派生/session fixture | BSE、午休、派生窗口通过 |
| P4 | asset/check/catalog/governance/job | `dg check defs` 和共享门禁通过 |
| P5 | 专属分区/readiness/sensor | 单连接、10 日、0 event history |
| P6 | 无请求 Bootstrap plan dry-run + staging 工具开发 | 精确预算、目标冲突、staging/audit 本地测试通过；Tushare 请求为 0 |
| P7A | 一次性 source staging 与只读源事实审计 | 请求窗口不重复，保留完整源事实 |
| P7B | 非北证 bounded Silver fallback | 130 个 scope 全部可重建，0 次源请求，无范围扩大 |
| P7C | Raw-only BSE 和非北证精确清洗 | Raw/Silver scope 分离，北证不进入 Silver，已知异常精确修正，未知异常 fail closed |
| P7D | 完整临时 Raw/Silver lake 与全量对账 | 无未解释行数/缺失/冲突 |
| P7E | 正式 promote 与 post audit | 需单独批准，正式目标逐文件对账 |
| P8 | materialization 全量、check 最近 20 日 | partition attribution 正确 |
| P9 | 手动启用 sensor，连续观察至少 3 个交易日 | 无超时、重复、错误覆盖 |

## 18. P1/P6 预算报告字段

正式报告至少有：`scope_revision`、`scope_hash`、`date_plan_fingerprint`、`code_count`、`frequency_count`、`window_count`、`base_request_count`、`page_request_count`、`retry_count`、`source_row_count`、`written_row_count`、`file_count`、`bytes_written`、`duckdb_elapsed_ms`、`tushare_elapsed_ms`、`peak_memory_bytes`、`disk_free_bytes`、`failure_date_count`、`duplicate_key_count`、`truncated_count`。

拒绝阈值：无界分页/重试、页满却未证明完整、完整代码历史缓存、全历史 event 查询、预计磁盘不足、总请求超过 5,000、sensor 接近 60 秒 RPC deadline，任一命中都停止。

## 19. 当前审计结论

已确认：代码集合、科创综指 `000680.SH`、北证50源站停止日、五频存在性、显式字段返回、现有 index_mins 资产依赖和统一 cursor/request builder 形态。

已补充确认：orchestrator `TushareResource.call()` 会把显式字段作为独立参数传给 `idx_mins`，并透传 `limit/offset`。把 page limit 临时压到 2 的真实请求产生 3 页、5 行、0 重试，offset 分页没有重复行。MCP 同时证明默认字段不含 `freq/exchange/vwap`，显式请求后均返回；五个原生频率在同一收盘时点均有数据。

P1 还纠正了一个旧文档事实：`899050.BJ` 的最早分钟数据是 `2022-11-21 09:30:00`，不是 `2022-12-15`；`2025-10-30` 有数据、`2025-10-31` 起为空的停止边界不变。

P3 已用真实源样本冻结 session：SH/SZ 五频日行数为 `241/49/17/9/5`，BSE 为 `271/55/19/10/6`，BSE 收盘为 `15:30`。90m 对 BSE 的第三窗延伸到 `15:30`；120m 只输出两个完整窗口，不把 `15:00/15:30` 尾部伪造成 120m。完整报告见 `/private/tmp/major_index_mins_p3_session_probe_20260805.json`。

P4 已注册 Raw 5、Silver 7、每资产一个 partitioned blocking core check、Raw/Silver 两个 job、12 个 Catalog/governance 条目、两个 PartitionModel 和中文名。P5 已补齐专属分区注册、Raw/Silver 10 日 lake readiness、10 代码收盘探针和默认停止状态的 sensors。真实 `2026-08-04` 探针为 10 次请求、0 重试、约 4.09 秒；120 文件联合 readiness 经分组复用 expected tables 后由约 13.43 秒降至约 1.84 秒。

P6 首版全量请求式 dry-run 执行至第 160 个源窗口并 fail-closed。日期计划为 `2009-01-05..2026-08-04`、4,271 个交易日；精确计划为 2,662 个有界源窗口、预计 10,022,855 行、Raw 21,355 个文件、Silver 29,897 个文件，预计安全磁盘预算约 11.65 GB，当前磁盘预算通过。首个阻断是 `000001.SH` 的 `2022-02-07..2022-03-04` 1min 窗口：4,820 行和 session grid 完整，但 `2022-02-07 09:30` 返回 `open=close=3407.762, high=low=0`。补充抽样确认同日多只上证指数、五个频率均存在同形态，而深证和近期样本没有。

首版实现把已请求行只放在内存中审计并随即释放，导致重新执行时必须再次请求，现已判定为错误边界。正式方案改为：P6 plan dry-run 不请求；P7 source staging 是历史数据唯一请求入口；每个窗口的原始响应、请求身份、分页/重试统计和内容 hash 原子落盘并可断点续跑；后续 OHLC 事实统计、Raw/Silver 生成和全量对账全部复用 staging。上述哨兵在 source staging 中原样保存，既不丢弃也不被偷偷判定为正式合法；待完整 staging audit 汇总后再冻结正式 Raw/Silver 处理口径。首版报告 `/private/tmp/major_index_mins_p6_dry_run_20260805.json` 只保留为方案修正证据。

## 20. Milestone 状态

| 阶段 | 状态 | 当前证据 |
| --- | --- | --- |
| P0 | 完成 | 11 个 scope、字段、路径、专属分区、12 个 check、Catalog/governance、性能和事件口径已冻结；当前仓库无同名生产实现 |
| P1 | 完成 | 合同/分页正反例 10 项通过；MCP 字段/五频/scope 边界通过；项目 wrapper 真实 3 页/5 行/0 重试 |
| P2 | 完成 | Raw 目标复用/拒绝覆盖、source/staging 双验证、原子替换和 2,410 行完整 session 性能样本通过 |
| P3 | 完成 | Native Silver、90m/120m、SH/SZ session、BSE 历史样本审计、聚合公式、错误目标保护和临时湖联调通过；P7C 后 BSE 不再进入 Silver/session 合同 |
| P4 | 完成 | Raw 5 + Silver 7 asset/check、2 job、Catalog/PartitionModel/中文名/governance exact 注册和 definitions 装载通过 |
| P5 | 完成 | 专属分区、最近 10 日 readiness、10 代码 bounded probe、单连接/单 RunRequest/default STOPPED 和 0 event history 通过；120 文件联合 readiness 约 1.84 秒 |
| P6 | 完成 | 无请求 plan dry-run、可恢复 source staging、只读 staging audit、临时 Raw/Silver build/audit、hash + 目标目录原子 promote 已实现；fake-source 完整链路证明续跑不重复请求 |
| P7A | 完成 | 2,662/2,662 窗口已落 staging，2,662 次请求、0 重试、10,016,287 行；未写正式 lake/event |
| P7B | 完成 | retained staging 真实重建 15 个文件、1,482 行，独立 post-audit 违规为 0；耗时约 2.764 秒，整批 1 个 DuckDB connection、0 次源请求、0 次 event history 查询 |
| P7C | 完成 | Raw/Silver scope、hash、validator 已拆分；BSE Raw-only；30 行 sentinel、105 行 envelope 和 exchange 派生已通过 retained-staging 真实临时样本 |
| P7D | 完成 | retained staging 已生成 Raw 21,355、Silver 29,897 个临时文件并完成逐文件全量对账；缺失/无效均为 0，正式 lake/DB/event 写入为 0 |
| P7E | 完成 | 51,252 个临时目标已逐文件原子 promote；正式 Raw/Silver 全量 post audit 缺失/无效均为 0，Dagster 写入为 0 |
| P8 | 完成 | 注册 4,271 个专属动态分区；12 个资产全量补 51,252 条 materialization，并只对最近 20 日补 240 条 partitioned core check event；最终候选为 0 |

P0 CodeGraph 影响面：现有 `index_mins` 的 Raw/Silver writer、bounded readiness、三个 sensor、Bootstrap/event 模式；共享注册点为 `partitions.py`、`paths.py`、`asset_column_schemas.py`、`lake_assets.py`、`name_mapping.py` 和治理/definitions/static-gate 测试。没有前端/API/生产 `DatasetDefinition` 消费者。

当前分支为 `dev-interface`。P0 审计时除本专项三份未跟踪文档外，工作区还存在 `reports/a_share_power_industry_*` 等无关未跟踪文件；后续实现不得修改、删除或纳入本专项提交。

### P7 Source Staging 实际结果

经批准的历史源请求已一次性完成，staging root 为 `/Volumes/datasource/data_lake_staging/major_index_mins_p7_20260805`。执行报告 `/private/tmp/major_index_mins_p7_source_stage_20260805.json` 显示 2,662 个计划窗口全部完成、2,662 次请求、2,662 页、0 重试、10,016,287 行，耗时约 78 分钟；正式 lake 和 Dagster DB/event 写入均为 0。

修正 `exchange IS NULL` 漏计后的只读审计报告为 `/private/tmp/major_index_mins_p7_source_staging_audit_20260805_v2.json`：窗口缺失/损坏/重复主键/staging 残留均为 0；实际行数比静态 session 计划少 6,568 行，拆分为缺失 7,310、额外 742；`exchange` 为 NULL 或 `nan` 共 1,220,046 行；数值域异常 5 行；开盘 OHLC 哨兵 30 行；其它 OHLC 包络异常经 P7C 互斥复核为 105 行。详细日期、代码、频率拆分见 `/private/tmp/major_index_mins_p7_source_anomaly_breakdown_20260805.json` 和 `/private/tmp/major_index_mins_p7c_contract_audit_20260806.json`。

当前门禁已拆分：非北证 source-empty/frequency fallback 已完成 P7B 代码、真实临时重建
和独立 post-audit；P7C 已拍板 BSE Raw-only、Silver 永久排除，不再开发 BSE fallback
或业务 check。非北证 OHLC 白名单清洗和 exchange 派生按 LLD 第 29 节实现。P7D 已复用
同一 retained staging 完成完整临时湖 build 和全量对账；仍不 promote、不补事件，也不
重复请求 Tushare。

## 21. P7B-P7E 修正后的推进计划

### 21.1 P7B1 冻结非北证规则

规则共 15 个日期/频率项，展开后为 130 个代码 scope：

| trade date | target | source | target codes |
| --- | --- | --- | ---: |
| `2009-05-05`、`2009-06-05`、`2009-12-04` | `15min` | `5min` | 各 5 |
| `2010-09-02` | `5min` | `1min` | 6 |
| `2024-10-30` | `15min` | `5min` | 9 |
| `2025-07-04` | `30min`、`60min` | `5min` | 各 10 |
| `2025-07-11` | `15min`、`30min`、`60min` | `5min` | 各 10 |
| `2025-07-18` | `30min`、`60min` | `5min` | 各 10 |
| `2025-07-25` | `60min` | `5min` | 10 |
| `2025-08-01` | `30min`、`60min` | `5min` | 各 10 |

代码白名单由各日期真实 effective scope 固定；任何 `.BJ` 代码、未知日期/频率、重复
规则、target 不在 source scope 的规则都在模块 import/test 阶段拒绝。

### 21.2 P7B2 实现与样本验收

新增纯 Bootstrap helper，复用现有 source staging、DuckDB、session helper、staging
和原子替换模式。实现必须先验证 source code set、source session grid、主键和值域，
再 set-based 聚合；全部 target staging 回读通过后才允许替换临时目标。失败时保留原目标
并清理临时文件。

P7B 只输出独立临时样本和审计报告，不生成“完整正式分区”的假象，因为 P7C 的 Raw/Silver
scope 拆分和非北证清洗尚未实现。验收必须证明：130 个 scope 全部生成 expected bars、规则外 0 行、
`vwap` 全 NULL、Tushare/Prod/Dagster event history 调用均为 0。

### 21.3 P7C 剩余合同

P7C 合同已经冻结：

1. 北证50在 Raw 忠实保存；无论完整、为空、部分 grid、错误一分钟 grid 或负值，都不
   进行业务完整性检查、修复或补造；
2. Silver 原生五频及 90/120min 永久排除 `899050.BJ`，不新增 BSE availability、
   fallback、repair 或专属 check；
3. Raw/Silver validator 拆分，禁止全局放宽共享 validator；
4. 30 行非北证开盘 sentinel 和 105 行 `399001.SZ` OHLC envelope 异常只按精确
   代码/日期/频率/时间白名单清洗；
5. Silver `exchange` 统一按 `ts_code` 后缀派生，Raw 保留 NULL/`nan` 源事实；
6. Check 仍为 Raw 5 + Silver 7，每 asset 一条合并 check，不按代码或规则拆分。

具体函数、SQL、白名单、测试和性能门禁以 LLD 第 29 节为准。P7C 已完成代码迁移和
retained-staging 真实临时样本验收；P7D/P7E 正式文件发布和 P8 事件补录也已按阶段
完成，三者的报告和写入边界彼此独立。

### 21.4 P7D-P9 顺序

1. [已完成] P7D 从同一 retained staging 构建完整临时 Raw/Silver，先原生频率和
   fallback，再生成 90/120min；执行全量文件、行数、scope、session、主键和
   provenance 对账；
2. [已完成] P7E 经单独批准 promote 正式 lake，并执行正式 lake post audit；
3. [已完成] P8 全量补成功分区 materialization，只补最近 20 个专属分区的 core check event；
4. P9 最后手动启用三个 sensor，连续观察至少 3 个交易日。

P7B 已完成。真实执行报告为
`/private/tmp/major_index_mins_p7b_fallback_report_20260806.json`：15 条规则全部通过，
读取 5,072 行源数据并生成 1,482 行目标数据，耗时约 2.764 秒；独立 post-audit 违规为
0。P7C 已完成。P7D 真实执行报告为：

```text
/private/tmp/major_index_mins_p7d_temporary_lake_build_20260806.json
/private/tmp/major_index_mins_p7d_temporary_lake_build_20260806_fallback.json
/private/tmp/major_index_mins_p7d_temporary_lake_audit_20260806.json
```

临时根固定为
`/Volumes/datasource/data_lake_staging/major_index_mins_p7_20260805`。Raw 共 21,355 个
文件、10,016,287 行、472,820,318 bytes；Silver 共 29,897 个文件、9,917,572 行、
486,056,568 bytes。全量逐文件审计缺失/无效均为 0，Silver 只含 10 个非北证代码，
`899050.BJ` 为 0 行；15 条 fallback 规则生成 1,482 行。完整 build 约 8,288,856ms，
全量 target audit 约 6,360,495ms。Tushare 请求、正式 lake、Dagster DB/event 写入均为
0，staging 临时残留为 0。

source staging 的 `transport_ready=true`，历史源业务异常仍按原事实报告为
`business_contract_ready=false`；P7C 的精确清洗、Raw-only BSE 和 P7B fallback 已在
最终 Raw/Silver validator 中逐文件验收，不允许把 transport 完整误写成原始业务数据
天然无异常。P7D 已完成。P7E 已在单独批准后完成，正式报告为：

```text
/private/tmp/major_index_mins_p7e_formal_lake_promote_20260806.json
```

正式 Raw 21,355 个文件、10,016,287 行、472,820,318 bytes；正式 Silver 29,897 个
文件、9,917,572 行、486,056,568 bytes。全部文件由 staging 逐文件复制，在目标目录内
完成临时文件、size/hash 校验和原子替换；post audit 的缺失/无效均为 0。Silver 仍只含
10 个非北证代码，`899050.BJ` 为 0 行；正式目标 staging/tmp 残留为 0。Dagster
materialization/check event、专属动态分区和 run 写入均为 0。

本次执行总耗时 `11,417,256.707ms`。执行时发现 CLI 已解析 P7D 报告参数但误传给
`build-temp` 分支，导致实际 promote 报告为 `temporary_audit_mode=live_deep_audit`，重复
执行了 source/temporary 深审计；这增加耗时但没有削弱正确性。参数路由已修正并增加专门
测试；report reuse 还会验证 build/source/target fingerprint、计数、零写入以及所有 source
window/sidecar 和 target 文件自报告后未变化。后续幂等 promote 不再无条件重跑这两段
深审计，但正式 lake post audit 仍保留。P7E 和 P8 均已完成；下一步只剩 P9 手动启用
三个 sensor 并做连续交易日观察。

## 22. P8 Dagster 事件补录实际结果

P8 使用独立 runless 维护入口，不运行历史 asset job，不改写已经通过 P7E 验收的
Parquet。工具实现位于：

```text
orchestrator/defs/bootstrap/major_index_mins_bootstrap_events.py
orchestrator/defs/bootstrap/major_index_mins_bootstrap_events_cli.py
```

执行顺序固定为 dry-run、动态分区注册、最近日期 sample、sample post-audit、12 个资产
串行 apply、最终 post-audit。每次写入前同时核验冻结日期计划、P7E 正式报告、P7D
fallback 报告、文件数量和修改时间、active runs、动态分区集合及现有 latest event；工具
支持按资产幂等恢复，但不提供 job/sensor/lake 写入路径。

实际结果：

| 项目 | 结果 |
| --- | ---: |
| `cn_major_index_mins_trade_days` 注册分区 | 4,271 |
| 日期范围 | 2009-01-05 至 2026-08-04 |
| Raw materialization | 21,355 |
| Silver materialization | 29,897 |
| materialization 合计 | 51,252 |
| 最近 20 日 Raw core checks | 100 |
| 最近 20 日 Silver core checks | 140 |
| core check 合计 | 240 |
| 最终缺失 materialization / check | 0 / 0 |
| active runs | 0 |

15 个历史 Raw source-empty 日期/频率没有被伪装成非空数据。P8 只在 P7D fallback 报告
精确证明的范围内允许 0 行 Raw 文件，并在 materialization metadata 中写入
`source_empty_exempt=true`；这些日期不在最近 20 日 check 窗口内。Silver 仍由低频
fallback 生成并通过 P7D/P7E 文件验收。

主要报告：

```text
/private/tmp/major_index_mins_p8_event_dry_run_20260807_v2.json
/private/tmp/major_index_mins_p8_partition_registration_20260807_v2.json
/private/tmp/major_index_mins_p8_event_sample_20260807.json
/private/tmp/major_index_mins_p8_event_sample_post_audit_20260807.json
/private/tmp/major_index_mins_p8_apply_<asset>_20260807.json
/private/tmp/major_index_mins_p8_event_post_audit_20260807.json
```

最终 post-audit 对 12 个资产逐一确认：每个资产 4,271 个 materialized partitions、最近
20 日 20 条 ready check，check 均指向对应分区的 latest materialization；剩余计划事件
为 0，`should_stop=false`。P8 没有创建 Dagster run、没有运行 sensor、没有修改数据湖
文件。P9 仍需单独启用和观察。
