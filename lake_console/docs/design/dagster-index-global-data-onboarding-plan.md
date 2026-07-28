# `index_global` 国际指数数据集接入方案

## 1. 文档状态

- 状态：方案口径已冻结，已完成代码级前置审计；进入代码前还必须完成 P1 真实请求验证。
- 数据集：`index_global`，中文展示名为“国际指数日线”。
- 数据源：Tushare `index_global`。
- 本文不执行代码、不写正式湖、不写 Dagster 数据库、不启用 sensor。
- 当前仓库尚未实现 `index_global` 的 asset、check、job、sensor、catalog 或 schema；本文件和 LLD 是实现前约束，不代表功能已上线。
- 代码实现前必须继续通过本地 fake/临时湖测试和 Tushare 最小真实请求验证。

## 1.1 数据集说明卡

| 项目 | 冻结内容 |
| --- | --- |
| 中文名称 | 国际指数日线 |
| 稳定 dataset id | `index_global` |
| Raw asset | `raw_index_global`，保存 Tushare 原始字段和自然日分区结果 |
| Silver asset | `silver_index_global`，把日期和字段名标准化为内部事实口径 |
| 数据域/group | `index_topic` / `index` |
| 主要消费者 | 当前无已登记下游消费者；后续国际市场概览、研究查询和跨市场分析只能消费 Silver，不直接消费 Raw |
| 数据层职责 | Raw 只镜像源站；Silver 只做类型、字段名、日期和键标准化，不承担 21 个指数覆盖判断 |
| 初始化来源 | Tushare 按五阶段读取；不从 Prod DB 或旧湖初始化 |
| 更新单位 | 一个自然日、一个 `probe_phase`，最终 Silver 每日只消费 `americas` 完成后的 Raw |

## 1.2 Catalog、分区和治理登记清单

正式代码进入 Definitions 前必须一次性完成以下登记，不能只写 asset 文件：

| 登记位置 | 必须新增内容 |
| --- | --- |
| `orchestrator/defs/catalog/name_mapping.py` | `index_global: 国际指数日线` |
| `orchestrator/defs/catalog/lake_assets.py` | `raw_index_global`、`silver_index_global` 两条 `LakeAssetCatalogEntry` |
| `orchestrator/defs/catalog/lake_assets.py` | `TRADE_DATE_PARTITION_RAW_INDEX_GLOBAL`、`TRADE_DATE_PARTITION_SILVER_INDEX_GLOBAL` 两个 `PartitionModel` 和对应 `PARTITION_MODEL_DEFINITIONS` |
| `orchestrator/defs/partitions.py` | 唯一的 `cn_global_index_trade_days` dynamic partition 定义 |
| `orchestrator/defs/paths.py` | Raw/Silver 路径 helper 和模板 |
| `orchestrator/defs/run_contracts/asset_column_schemas.py` | Raw/Silver schema contract |
| `orchestrator/defs/run_contracts/index_global.py` | 代码集合、phase、配置、请求策略、metadata key 和 contract 常量 |
| `tests/test_asset_check_incremental_governance.py` | 两个 core check 的治理映射，规则集合必须与 catalog 完全一致 |

Catalog 固定字段：

- `dataset_id=index_global`，`dataset_name=国际指数日线`；
- `layer=raw/silver`，`data_domain=INDEX_TOPIC`，`group_name=index`；
- Raw `source_system=TUSHARE`、`source_api=index_global`、`source_doc=docs/sources/tushare/指数专题/0211_国际指数.md`；
- Raw/Silver `partition_model`、schema、path template、blocking check、write policy、event policy 和 performance contract 必须与实现一致；
- Raw `write_policy=PARTITION_FILE_ATOMIC_REPLACE`，Silver 同样使用分区文件原子替换；
- 两个资产的 blocking check 各只有一个合并 core check，但 check metadata 必须列出每条失败规则、失败数量和有限样本；
- 事件策略明确为普通日常事件保留最近 20 个自然日；Bootstrap 不按五个 phase 逐个补录历史 Dagster event。

治理映射在代码中必须按下表落地，不能用空壳规则通过门禁：

| Asset | Blocking check | category | participates_in_sensor_readiness | retention_allowed | implementation_phase |
| --- | --- | --- | --- | --- | --- |
| `raw_index_global` | `raw_index_global_core_check` | `MOVE_TO_SENSOR_LAKE_READINESS` | `false` | `true` | `INDEX_GLOBAL_P5` |
| `silver_index_global` | `silver_index_global_core_check` | `MOVE_TO_SENSOR_LAKE_READINESS` | `false` | `true` | `INDEX_GLOBAL_P5` |

这里的 `false` 是有意的：sensor 的实际门禁是 DuckDB lake readiness，不读取 Dagster check history；Dagster core check 负责分区事实审计和 UI 展示，不能再被实现成 sensor 热路径的隐式深扫。`retention_allowed=true` 只表示普通历史 check 可以按统一最近 20 个自然日策略治理，不表示可以删除 latest check 或绕过 lake readiness。

### 1.3 七项已拍板事项闭环

| 拍板事项 | 冻结结论 | 方案落点 |
| --- | --- | --- |
| 1. retry 信息来源 | 从 typed run config 读取，不依赖 run tags | 第 4 节、7.2 节、9 节；统一 `index_global.py` 配置和 builder |
| 2. 数据集登记 | 中文名为“国际指数日线”，补齐 data card、catalog、partition model、governance mapping | 1.1、1.2、实现顺序 P5/P6 |
| 3. cursor | 只使用现有 `build_sensor_cursor()`，不得手写 JSON | 7.2、7.3、9 测试门禁 |
| 4. Silver 最终触发 | 只由 `americas` 成功 run-status 触发 | 7.3，独立 Silver retry sensor |
| 5. phase merge rank | 旧文件 `0`、当前 phase `1`，rank 只存在 DuckDB 临时语句 | 第 5 节 |
| 6. late-empty 形态 | 独立 `index_global_late_empty_sensor`，默认 `STOPPED`，最近 3 日、每日期最多 2 次 | 7.2、9.1 |
| 7. 配置与预算 | 集中配置审计，固定 5 阶段请求、10 日 replay、50 slot、20 日 Bootstrap batch 和预算报告 | 8.1、8.2、9、10 |

## 2. 已冻结口径

### 2.1 历史起点

历史初始化下限固定为 `2022-01-01`，但这只是统一的查询下限，不表示 21 个指数都从当天开始有数据。

Tushare MCP 实测：

- `2022-01-01` 返回空结果；
- `2022-01-03` 返回 16 个指数；
- `2022-01-04` 返回 21 个指数。

因此 Bootstrap 必须允许起点日期、周末、节假日和单个指数的自然缺失。不得通过“首个非空日期”反推统一起点，也不得要求每个指数从 `2022-01-01` 开始存在。

### 2.2 分区语义

`cn_global_index_trade_days` 的实际语义为“国际指数自然日分区集合”，不是全球统一交易日历。

- 每个自然日都可以注册分区；
- 注册不依赖 A 股 `index_trade_day_sensor`；
- 注册不读取 Tushare 数据；
- 注册不判断当天是否有 21 个指数；
- 周末、节假日允许存在空分区；
- 分区注册和源数据同步完全解耦。

当前名称保留为 `cn_global_index_trade_days`，但文档和代码注释必须明确它不是“全市场共同交易日”。

### 2.3 当天分阶段同步

不能等到第二天才统一请求。当天同步分为五个阶段，每个阶段按日期请求一次全部已发布的国际指数数据：

| 阶段 | 北京时间 | 目标自然日 | 主要市场/代码 |
| --- | --- | --- | --- |
| `asia_1` | 14:40 | 当天 | `N225`、`KS11`、`TWII`、`AS51` |
| `asia_2` | 16:20 | 当天 | `HSI`、`HKTECH`、`HKAH` |
| `asia_3` | 18:30 | 当天 | `XIN9`、`CKLSE`、`SENSEX` |
| `europe` | 00:45 | 前一天 | `FTSE`、`FCHI`、`GDAXI`、`CSX5P`、`RTS` |
| `americas` | 05:30 | 前一天 | `DJI`、`SPX`、`IXIC`、`RUT`、`SPTSX`、`IBOVESPA` |

请求不按代码循环。每个阶段调用一次：

```text
index_global(
    trade_date=target_trade_date,
    fields=INDEX_GLOBAL_FIELDS,
    limit=4000,
    offset=0,
)
```

Tushare 返回的是该日期当前已经发布的全部指数。后续阶段重新请求同一日期，合并并原子替换该日期文件。

### 2.4 空结果和 21 个指数覆盖

本阶段不定义“21 个指数自然缺失”的业务口径，因此禁止以下 blocking check：

- 每天必须返回 21 个指数；
- 每个代码每天都必须存在；
- 行数必须大于 0；
- 任何缺失代码都判定为失败。

空结果建议写成 schema 正确的空 Parquet 分区，并在 materialization metadata 记录：

```text
source_observation=empty
source_row_count=0
probe_phase=<phase>
```

这样可以保证每天的同步任务有明确结果，又不把周末、节假日和暂未定义的自然缺失误判成错误。后续如需识别“工作日源站异常空结果”，另做离线审计，不回流当前 blocking check。

### 2.5 Raw/Silver 字段分层

Raw 保留 Tushare 原始字段名，Silver 使用项目内部标准字段：

| 语义 | Raw | Silver |
| --- | --- | --- |
| 指数代码 | `ts_code` | `ts_code` |
| 日期 | `trade_date`，`YYYYMMDD` 字符串 | `trade_date`，`DATE` |
| 涨跌点位 | `change` | `change_amount` |
| 成交额 | `amount` | `amount` |

`change_amount` 是涨跌点位，不是成交金额。成交金额仍使用 `amount`。

该口径与现有 `raw_index_daily -> silver_index_daily` 一致：Raw 不改动源字段，Silver 在 DuckDB 标准化时执行 `change -> change_amount`。

## 3. 源接口与 21 个代码

源接口文档为：[`0211_国际指数.md`](/Users/congming/github/goldenshare/docs/sources/tushare/指数专题/0211_国际指数.md)。接口支持 `ts_code`、`trade_date`、`start_date`、`end_date`、`limit`、`offset`，单次最多 4000 行。

进入 P1 前必须重新保存真实请求证据，不能只引用一次历史请求：

| 请求类别 | 必须验证 |
| --- | --- |
| 默认返回 | 不传 `fields`，记录字段集合、样本行和行数 |
| 官方字段 | 按本地源文档显式请求全部输出字段，记录 `amount` 是否出现及 NULL 口径 |
| 业务关键字段 | 显式请求 `ts_code/trade_date/open/close/high/low/pre_close/change/pct_chg/swing/vol/amount` |
| 对象过滤 | 不传时间、只传 `ts_code`、只传 `trade_date`，确认是否返回全集或单日结果 |
| 时间范围 | `start_date/end_date` 区间请求与按日请求的行数和边界一致性 |
| 分页 | `limit=4000`、`offset=0` 和后续 offset 的字段集合、重复行、空页终止行为 |

每组请求必须记录请求参数（脱敏）、返回行数、字段集合、第一页和最后一页样本、耗时和错误；任何字段或日期语义差异都必须先回写本方案。

固定代码集合：

```text
XIN9 HSI HKTECH HKAH DJI SPX IXIC FTSE FCHI GDAXI N225 KS11
AS51 SENSEX IBOVESPA RTS TWII CKLSE SPTSX CSX5P RUT
```

代码集合只用于身份字段校验、统计和有限样本，不用于覆盖完整性 blocking check。

### 3.1 收盘时间依据

市场收盘时间用于设计请求窗口，不等同于 Tushare 的实际发布时间：

- 日本、韩国、台湾、澳大利亚：分别参考 JPX、KRX、TWSE、ASX；
- 香港、新加坡、马来西亚、印度：分别参考 HKEX、SGX、交易所公开时间；
- 英国、法国、德国和 STOXX：参考 LSE、Xetra、STOXX；
- 美国、加拿大、巴西、俄罗斯：参考 Nasdaq、TSX、B3、MOEX。

夏令时会改变北京时间映射，因此阶段时间必须留有缓冲，不能写死为“某交易所收盘后立即成功”。

时间窗口设计参考的官方页面：

- [JPX Trading Hours](https://www.jpx.co.jp/english/systems/equities-trading/)
- [KRX Trading Hours](https://global.krx.co.kr/contents/GLB/06/0605/0605030100/GLB0605030100.jsp)
- [TWSE Trading Hours](https://www.twse.com.tw/en/products/system/trading.html)
- [ASX Cash Market Trading Hours](https://www.asx.com.au/markets/market-resources/trading-hours-calendar/cash-market-trading-hours)
- [HKEX Securities Market Trading Hours](https://www.hkex.com.hk/Services/Trading-hours-and-Severe-Weather-Arrangements/Trading-Hours/Securities-Market?sc_lang=zh-HK)
- [LSE Trading Hours FAQ](https://www.londonstockexchange.com/personal-investing/faqs?accordionId=0-92bc05a5-ceb5-40ec-939b-8ed45a8a197d&accordionid=0-da27fc36-9d55-4c52-8482-972337465857)
- [Deutsche Börse Xetra Trading Calendar and Hours](https://www.cashmarket.deutsche-boerse.com/cash-en/trading/trading-calendar-and-trading-hours)
- [Nasdaq Global Trading Hours FAQ](https://www.nasdaq.com/docs/nasdaq-global-trading-hours-faqs)
- [TSX Trading Hours](https://www.tsx.com/en/trading/calendars-and-trading-hours/trading-hours)
- [B3 Trading Hours Notice](https://www.b3.com.br/pt_br/noticias/operacoes-8AA8D0CD9C709633019CC38376552862.htm)
- [MOEX Trading Schedule](https://www.moex.com/a7211)

这些是触发窗口依据，不是源站发布时间保证。P1/P11 必须用实际连续观察记录校准“收盘后多久可稳定拿到 Tushare 数据”；夏令时、交易所临时休市和 Tushare 延迟只能通过 bounded retry 与 late-empty 策略处理，不能把固定时刻当作数据已发布事实。

## 3.2 字段、空值和数值域口径

- Raw 只检查源字段类型、日期、主键和身份代码；不在 Raw 中做业务修正。
- `ts_code`、`trade_date`、`open/close/high/low/pre_close/change/pct_chg/swing` 的字段是否允许 NULL，必须以 P1 实测和源合同分别冻结，不能用一次样本推断全局。
- `vol`、`amount` 按源文档允许 NULL；NULL 不因本身失败，但若源返回非 NULL，必须保持数值类型和有限值。
- Silver 只做 trim、日期转换和 `change -> change_amount`；不把 NULL 擅自填 0。
- `close/high/low/open/pre_close` 的非负、`pct_chg`/`swing` 的 finite 规则必须在 P1 后形成明确 SQL predicate，并写入 core check 的 `failed_rule_names`；未确认前不写猜测式范围检查。

## 4. 目标数据集边界

### 4.1 本专项包含

- `raw_index_global`：Tushare 原始镜像，按自然日物理分区；
- `silver_index_global`：Raw 标准化 Silver，按自然日物理分区；
- 专属自然日分区注册逻辑；
- Raw 单分区 asset、核心 check、job、sensor；
- Silver 单分区 asset、核心 check、job、sensor；
- 五阶段 Raw refresh 的合并、幂等、原子替换和性能门禁；
- Bootstrap、每日增量和有限失败恢复。

### 4.2 本专项不包含

- 不复用 A 股 `cn_a_index_trade_days`；
- 不复用 A 股 `index_trade_day_sensor`；
- 不从 Prod DB 初始化；
- 不按 21 个代码逐个请求；
- 不定义每个指数的自然缺失业务规则；
- 不新增数据库表、summary asset、manifest asset 或 readiness asset；
- 不在 sensor 中调用 Tushare；
- 不扫描 Dagster event history；
- 不在本阶段写正式湖或正式 Dagster event。

## 5. Raw 多阶段文件语义

物理路径固定为：

```text
raw/index_global/trade_date=YYYY-MM-DD/part-000.parquet
```

同一日期可以被五个阶段重复写入，但禁止 Parquet 追加写入。每次阶段更新必须：

```text
读取既有日期文件
    -> 合并本阶段 Tushare 返回
    -> 按 (ts_code, trade_date) 去重
    -> 后阶段结果覆盖前阶段同主键结果
    -> DuckDB set-based 校验
    -> staging parquet
    -> staging 回读校验
    -> 原子替换目标文件
```

同主键内容冲突时，以后阶段的源结果为准，并记录 `replaced_row_count`；不得静默丢弃冲突事实。

merge 的 rank 只存在于本次 DuckDB 临时查询，不写入 Raw schema：

- 已有目标文件中的行 `merge_rank=0`；
- 当前阶段已验证返回的行 `merge_rank=1`；
- 当前阶段相同主键优先于已有行；同一阶段重复键先 fail-closed，不进入 merge；
- 当前阶段空结果不删除已有行；目标不存在时才生成固定 schema 的空文件；
- rank 相同且字段相同只保留一行，字段不同以当前阶段行覆盖并计入 `replaced_row_count`；
- retry 和 late-empty 仍视为当前阶段的新输入，不依赖未持久化的 `probe_sequence`。

## 6. 核心检查设计

每个 Raw/Silver 资产只保留一个合并 blocking check，避免 5 个阶段每天重复写大量细粒度 check event。

### Raw core check

`raw_index_global_core_check`：

- 文件存在；
- schema 完全符合 Raw 合同；
- 分区日期和行内 `trade_date` 一致；
- 非空行的 `ts_code` 非空且属于固定身份集合；
- `(ts_code, trade_date)` 唯一；
- 空文件允许通过；
- 不检查代码覆盖数和正行数。

合并 check 必须使用 `build_check_metadata(...)`，写入 `CheckScope`、分区、文件路径、检查行数、失败行数、`failed_rule_names`、规则结果和最多 3 个失败样本。check 不重新执行 Tushare 请求，也不重新计算 merge。

### Silver core check

`silver_index_global_core_check`：

- 文件存在；
- schema 完全符合 Silver 合同；
- 日期类型和分区日期一致；
- `(ts_code, trade_date)` 唯一；
- 数值字段类型正确；
- `amount`、`vol` 等源站允许为空的字段不因 NULL 失败；
- 空文件允许通过。

Silver check 同样只验证当前分区文件事实，必须使用 `build_check_metadata(...)`；不得把源站发布时间、21 个代码覆盖或历史完整性混入 blocking check。

## 7. Sensor 与 Job

### 7.1 专属自然日注册 sensor

新增专属注册逻辑，职责仅为幂等注册自然日：

- 不调用 Tushare；
- 不读取 Prod DB；
- 不判断 21 个代码；
- 不依赖 A 股交易日历；
- 在现有 `orchestrator/defs/partitions.py` 新增
  `cn_global_index_trade_days = dg.DynamicPartitionsDefinition(...)`；
- 在独立的 `orchestrator/defs/sensors/global_index_partition_sensor.py` 实现注册 sensor；
- 每次读取已注册集合一次，在内存中计算缺失日期；
- 每次最多提交一个 dynamic partition add request；
- `GLOBAL_INDEX_PARTITION_REGISTRATION_BATCH_SIZE` 固定为 `2000`，单次最多补注册 2000 个日期，剩余日期由后续 tick 继续补齐；
- 需要时补齐从 `2022-01-01` 到当前日期的自然日分区。

### 7.2 Raw update sensor

Raw sensor 根据北京时间阶段窗口选择目标日期和 `probe_phase`：

- 每次 tick 最多一个 RunRequest；
- 同一日期、同一阶段使用独立 run key；
- 使用 phase slot replay，不只判断当前阶段；
- 自动回放最近 10 个自然日内错过的阶段，最多 50 个 slot；
- 按最早缺口顺序逐个补发，每 tick 只提交一个；
- 超过 10 个自然日的积压 fail-closed，转人工 Bootstrap/repair；
- 只做时间窗口、分区注册和幂等判断；
- 不调用 Tushare；
- 不访问 Dagster event history；
- 不做 21 代码 coverage readiness。

原始 phase run 使用：

```python
build_asset_update_run_key(
    subject="index_global_update",
    unit_id=f"{trade_date}:{probe_phase}",
)
```

phase、slot 和 retry 信息全部放在 typed run config 中，不依赖 run tags，也不从 run key 反解析业务字段：

```text
trade_date
probe_phase
slot_key
attempt=0                 # 原始 run
late_empty_attempt=0      # 普通 phase 固定为 0
```

对最终失败的 phase run，增加默认 `STOPPED` 的 run-status retry sensor：

- 只消费 `raw_index_global_update_job` 的直接失败事件；
- 不扫描 event history；
- 在同一日期/阶段范围内最多提交 2 个 retry run；
- retry 超限后输出 `retry_exhausted`，不无限创建新 run。

对最终阶段后仍为零行的最近 3 个日期，允许每个日期最多 2 次 late-empty reprobe。该机制只处理源站延迟观测，不把“必须返回指数”升级成 blocking check。

late-empty 固定实现为独立的 `index_global_late_empty_sensor`，默认 `STOPPED`，不并入失败 retry sensor：

- 只读取最近 3 个自然日的 Raw 文件，一次 DuckDB 查询完成行数探测；
- 每日期 attempt 只允许 `late_empty_1`、`late_empty_2`；
- attempt 状态放在该 sensor 自己的 cursor `details.runtime_state`；
- run config 使用 `probe_phase=late_empty`、`late_empty_attempt` 和目标日期；
- run key 使用 `build_repair_attempt_run_key(subject="index_global_update", repair_scope_id=trade_date, attempt=late_empty_attempt, attempt_scope="late_empty")`；
- 每 tick 最多一个 RunRequest，超过次数输出 `late_empty_exhausted` 并转离线审计；
- 不读取 event history、不访问 Tushare、不删除已有行，仍通过同一 Raw phase merge writer 处理有效返回。

retry run 必须使用 `build_repair_attempt_run_key(...)`，固定 `attempt_scope="retry"`；不能在 sensor 中拼接 `retry-1` 字符串。原始 run 与 retry run 的 config 由同一个 typed config builder 生成，只有 `attempt` 递增。

### 7.3 Silver 最终阶段触发

Silver 不通过“文件存在”猜测 `americas` 是否完成，固定采用独立的 run-status sensor：

- `silver_index_global_update_job_sensor` 监听 `raw_index_global_update_job` 成功 run；
- 只有触发 run 的 typed config 中 `probe_phase == "americas"` 才提交 Silver run；
- 直接读取触发 run 的 `run_config`，不调用 `instance.get_event_records(...)`；
- Silver run 继续使用 `build_asset_update_run_key(subject="silver_index_global_update", unit_id=trade_date)`；
- Silver 只读取同日最终 Raw，不请求 Tushare，不访问 Prod DB；
- Silver 文件已存在但核心 check 失败时不自动覆盖；
- Silver run 失败由独立的 bounded run-status retry sensor 最多重试 2 次，超过后输出 `silver_retry_exhausted`，不无限重试。

Silver retry sensor 固定文件为 `orchestrator/defs/sensors/silver_index_global_retry_sensor.py`，只读取失败 run 的 typed `run_config`，使用 `build_repair_attempt_run_key(...)`，不访问 event history。

Raw 的 `americas` run 成功是 Silver 的唯一日常触发信号。它保证 Raw 最终阶段和 Silver 触发之间有明确因果关系，同时不增加 event history 扫描。

如果以后要求亚洲数据在当天下午进入 Silver，再另行设计 Silver phase policy，不在本专项隐式扩展。

## 8. 性能门禁

- 正常日期最多 5 次 Tushare 请求；
- 不得退化成 21 代码循环；
- 每次请求 `limit=4000`、`offset=0`，分页仍受 bounded policy 约束；
- 每个阶段只保留当前日期的有限内存数据；
- DuckDB 使用 set-based merge 和校验；
- 不逐行 Python 计算；
- 不扫描全历史湖文件；
- sensor 的 Tushare 调用次数为 0；
- sensor 的 Dagster event history 调用次数为 0；
- 单 tick 只产生一个 RunRequest；
- cursor 只保存日期、阶段、行数、请求数、耗时和有限错误样本；
- 目标文件只能由 staging 校验通过后原子替换；
- 请求、分页、重试、耗时超过预算时整阶段 fail-closed。

### 分区注册性能

- 每次注册 tick 只调用一次 `get_dynamic_partitions`；
- 只在内存中生成自然日候选并计算 set difference，不逐日调用 Dagster API；
- 每次最多提交一个 dynamic partition add request，单次新增日期受固定上限约束；
- 初始历史补注册超过上限时分批完成，不阻塞 Raw 同步，也不触发 Tushare 请求；
- 注册 sensor 的 Dagster DB 写入仅限 dynamic partition keys，不写 materialization/check event；
- 分区注册耗时、待注册数量和本次新增数量写入小型 cursor，cursor 不保存全量日期列表。
- phase replay 只回看最近 10 个自然日，最多 50 个 slot；
- retry sensor 只消费直接失败事件，event history API 调用为 0；
- late-empty reprobe 最多批量读取 3 个目标文件，不做全历史扫描；
- 任何自动补偿超过上限都 fail-closed，不扩大日期范围、不无限重试。

## 8.1 配置审计

本数据集不新增环境变量或运营可调配置。所有固定口径集中在
`orchestrator/defs/run_contracts/index_global.py`，由 typed config 和不可变常量统一消费：

| 配置/常量 | 默认值 | 消费者 | 说明 |
| --- | --- | --- | --- |
| `GLOBAL_INDEX_START_DATE` | `2022-01-01` | Bootstrap、分区注册、日期计划 | 历史下限，不代表每个指数有数据 |
| `GLOBAL_INDEX_PARTITION_REGISTRATION_BATCH_SIZE` | `2000` | 专属分区注册 sensor | 每 tick 最大新增动态分区数 |
| `GLOBAL_INDEX_REPLAY_LOOKBACK_DAYS` | `10` | Raw phase sensor | 自动回放自然日范围 |
| `GLOBAL_INDEX_REPLAY_SLOT_LIMIT` | `50` | Raw phase sensor | 每 tick/窗口最大 phase slot 数 |
| `GLOBAL_INDEX_FAILED_RUN_RETRY_LIMIT` | `2` | Raw failed-run retry sensor | 不含 job 内网络重试 |
| `GLOBAL_INDEX_LATE_EMPTY_DATE_LIMIT` | `3` | late-empty sensor | 只探测最近自然日 |
| `GLOBAL_INDEX_LATE_EMPTY_RETRY_LIMIT` | `2` | late-empty sensor | 每日期最大补探次数 |
| `GLOBAL_INDEX_REQUEST_LIMIT` | `4000` | Tushare request policy | 源接口单页上限 |
| `GLOBAL_INDEX_PHASE_TIMES` | 五阶段固定时间 | phase planner | 北京时间窗口，非源站完成保证 |
| `GLOBAL_INDEX_REQUEST_BUDGET` | 复用 bounded policy | Raw asset | 请求数、重试数、总耗时上限 |

这些值不从 sensor、job、asset 文件各自读取；改变任一值必须同步更新本方案、LLD、测试基线和性能报告。

## 8.2 Bootstrap 量级预算

按 `2022-01-01` 到 `2026-07-28` 的自然日计划估算：

- 约 `1,670` 个自然日；
- 五阶段基础请求约 `8,350` 次；每次通常一页，但失败重试和分页必须单独计数；
- Raw 最终文件约 `1,670` 个，Silver 最终文件约 `1,670` 个，合计约 `3,340` 个；
- 不能通过 Dagster 逐 phase 启动历史 run；Bootstrap 使用独立 runner，日期串行、批次最多 20 日，可中断续跑；
- 五阶段 source observation 只进入 Bootstrap 报告，不逐阶段补 Dagster event；历史 Dagster 只补最终 Raw/Silver 状态事件，避免事件量膨胀；
- 正式 Bootstrap 前必须做代表日期样本和小批量 benchmark，记录请求、页数、重试、source rows、written rows、DuckDB、Parquet、磁盘和峰值内存；
- 任何未解释的源行数变化、schema/主键冲突、磁盘不足或预算超限都停止，不覆盖目标文件。

## 9. 测试门禁

### 源请求

- 2022-01-01 空结果可接受；
- 2022-01-03 部分指数可接受；
- 2022-01-04 21 个指数可接受；
- 显式字段、`limit`、`offset`、空页、重复页、跨页重复和字段漂移均有测试。

### Raw/Silver

- 空分区可通过核心合同；
- 非法代码、日期错位、重复主键、schema 漂移失败；
- 五阶段重复写入最终只保留唯一主键；
- 后阶段同主键内容变化能够覆盖并记录；
- staging 失败不覆盖既有文件；
- 正常重跑不产生追加重复。

### Sensor

- 自然日注册不调用 A 股分区注册逻辑；
- 五阶段目标日期映射正确；
- 同日期不同阶段 run key 不冲突；
- DG 停止后 phase slot 能按时间顺序回放；
- 超过 10 个自然日积压时 fail-closed；
- failed run 最多生成 2 个 retry run；
- late-empty reprobe 每个日期最多 2 次；
- 每 tick 最多一个 RunRequest；
- sensor 不调用 Tushare 和 event history；
- cursor 使用 ASCII、大小受限。

## 10. 实施顺序

1. P1：Tushare `index_global` 请求和分页真实验证；
2. P2：Raw contract、phase merge writer、staging 和原子替换；
3. P3：临时湖 Raw 五阶段联调；
4. P4：Silver writer 和 Silver contract；
5. P5：正式 Raw/Silver asset、core check、job；
6. P6：自然日注册和五阶段 Raw sensor；
7. P7：phase replay、failed run retry 和 late-empty reprobe；
8. P8：Silver final-phase sensor；
9. P9：Bootstrap dry-run、正式湖生成和 Raw/Silver 对账；
10. P10：Dagster event 验收；
11. P11：手动启用 sensor，观察至少三个实际运行日。

任何阶段不得在前一阶段失败时跳过门禁进入下一阶段。

## 11. 参考实现

- Tushare 源文档：[`0211_国际指数.md`](/Users/congming/github/goldenshare/docs/sources/tushare/指数专题/0211_国际指数.md)
- 现有 A 股指数 Raw/Silver：[`index_daily.py`](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/assets/index_daily.py)
- Raw/Silver 字段合同：[`asset_column_schemas.py`](/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/run_contracts/asset_column_schemas.py)
- 低延迟/有限请求规范：[`tushare-contract-validation`](/Users/congming/github/goldenshare/.agents/skills/tushare-contract-validation/SKILL.md)
- Dagster 性能治理：[`dagster-data-pipeline-performance-governance.md`](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-data-pipeline-performance-governance.md)
