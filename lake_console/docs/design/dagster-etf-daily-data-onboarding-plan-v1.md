# ETF 日线与复权因子 DG 数据湖接入技术方案 v1

> 状态：P0、P1、P2 已完成；P2 最小真实样本已通过，待推进 P3；尚未进入 Bootstrap 或 Sensor 启用
> 更新日期：2026-09-02
> 适用范围：`lake_console/orchestrator` 当前 Dagster 数据湖主链
> 正式 Lake：`/Volumes/datasource/data_lake`
> 数据集：Tushare `fund_daily`、`fund_adj`

---

## 1. 结论

本需求建设四个按交易日分区的正式资产：

```text
Tushare fund_daily -> raw_tushare_fund_daily -> silver_etf_daily
Tushare fund_adj   -> raw_tushare_fund_adj   -> silver_etf_adj_factor
```

已经拍板并在本文冻结的口径如下：

1. Raw 直接按日请求 Tushare，保存接口当天返回的全部源端事实；Raw 不读取 ETF Basic，也不先筛 `.SH/.SZ`。
2. Silver 只做两件事：按本次执行冻结的最新 ready `silver_etf_basic` 筛选场内 ETF，并把 `trade_date` 从 `VARCHAR` 标准化为 `DATE`。不改字段名、不补值、不修值、不增加派生字段。
3. `silver_etf_daily` 完整继承 Raw 的 11 个字段，必须保留源字段 `change`，禁止改成或新增 `change_amount`。
4. `fund_adj` Raw/Silver 都保留 `discount_rate`；允许为空，非空只要求能表示为有限 `DOUBLE`，不按正负号或绝对值裁剪。
5. 日期直接复用 ETF 分钟线的动态分区 `cn_a_etf_mins_trade_days`；首次 Bootstrap 只覆盖该集合中 2025 年以来、且不晚于正式 Raw Plan 冻结水位的日期。
6. Silver 只认执行时最新且 ready 的 ETF Basic materialization。最新版本失败、不新鲜或文件漂移时立即 fail-closed，不回退旧版本。
7. 历史 Silver 不恢复不存在的 Basic 历史快照；Raw 全量完成并通过审计后，由 Silver Plan 冻结当时最新 Basic，自洽筛选全部历史分区。日后 ETF 退市不触发历史文件删除或重写。
8. 日常运行窗口为上海时间 `21:00（含）—24:00（不含）`；所有新 Sensor 默认 `STOPPED`，启用仍需单独授权。
9. 历史建设走一次性的 Direct Lake Bootstrap；日常增量走四个独立资产 Job。两条链复用同一组 request builder、候选校验、内容对账和原子提升函数。
10. 正式文件只允许“新增、等价复用、冲突停止”，绝不自动覆盖。

本期不建设 Gold 复权行情，不改 Prod 数据集，不接前端，不从 Prod DB 导出，也不使用旧 Lake Console、旧 Lake Root 或 Kopia。

---

## 2. 目标与边界

### 2.1 目标

1. 在 DG Lake 建立可追溯的 ETF 日线 Raw/Silver。
2. 在 DG Lake 建立包含 `discount_rate` 的 ETF 复权因子 Raw/Silver。
3. 让两类日频数据与 ETF 分钟线共享同一批交易日，不再维护第二套 ETF 行情日期集合。
4. 一次性补齐 2025 年以来的历史分区，之后按交易日日常增量维护。
5. 每个分区都能回答：源端请求了什么、返回多少、Raw 写了什么、Silver 筛掉多少及绑定哪版 Basic、文件是否可读、合同是否通过。

### 2.2 明确不做

- 不从 Prod DB 读取 `fund_daily` 或 `fund_adj`。
- 不用 ETF Basic 限制 Raw 请求或 Raw 入湖范围。
- 不要求 `fund_daily` 与 `fund_adj` 的 Raw 代码集合相等。
- 不把 Basic 范围外的源端记录认定为 Raw 污染。
- 不构造历史 Basic，不对历史日期做穿越式 ETF 身份还原。
- 不把价格、复权因子或折溢价率修正后再写入 Silver。
- 不生成前复权/后复权日线，不建设 Gold。
- 不通过日常 Sensor 追赶 2025 年以来的全历史。
- 不新增数据库表、状态表、缓存层、Tushare 客户端或环境配置。
- 不修改现有股票日线通用分页 helper 的行为。
- 不在本文或 LLD 评审完成前写正式 Lake、补 Dagster 事件或启用 Sensor。

---

## 3. 当前事实与 P0 结论

### 3.1 当前 DG 事实

- DG 目前没有这四个正式资产和对应正式 Lake 文件。
- ETF Basic 已具备 content-addressed Raw/Silver 快照、latest-only selector 和 blocking checks，可直接复用。
- ETF 分钟线已使用 `cn_a_etf_mins_trade_days`。2026-09-02 的只读证据为 404 个分区：2025 年 243 个、2026 年 161 个，范围 `2025-01-02..2026-09-01`。
- 上述数量只是审计时事实。正式 Bootstrap 仍要动态读取分区集合并冻结水位，不能把 404 或 `2026-09-01` 写成运行常量。

### 3.2 P0 真实源端证据

P0 使用项目正式 `TushareResource`，只写 `/private/tmp` 隔离样本，没有访问正式 Dagster instance 或正式 Lake。

| 项目 | `fund_daily` | `fund_adj` |
| --- | --- | --- |
| 正式 unit | 单个 `trade_date` | 单个 `trade_date` |
| 显式字段 | 11 个 | 4 个，含 `discount_rate` |
| limit | `5000` | `2000` |
| 三日行数 | `1452 / 1848 / 2105` | `1501 / 1862 / 2138` |
| 最大真实页数 | 1 | 2（`2000 + 138`） |
| 主键重复/日期错位 | 0 / 0 | 0 / 0 |

补充结论：

- `fund_daily@2026-09-01` 真实返回过 `158008.OF`，证明 Raw 不能硬编码 `.SH/.SZ` 过滤。
- `fund_daily` 用诊断 limit `1000` 得到 `1000 + 1000 + 105`，与正式 limit 文件双向 `EXCEPT ALL` 差异为 0。
- `fund_adj` 默认字段不含 `discount_rate`；只有显式写入 fields 才返回。
- 三日 `fund_adj` 有 8 个 `discount_rate` 空值，非空范围为 `-72.4787..9940.7`，因此不做范围清洗。
- 六个样本 Parquet 共 326,003 bytes；DuckDB 扫描 6 文件、10,906 行并做聚合检查耗时 206 ms、无 spill。
- 稳定单分区额外 Python 分配峰值不超过 2.4 MB；当前数据量不需要跨日内存缓存或并发拉取。

### 3.3 P0 冻结的质量阈值

`fund_daily` 三日样本中：

- `change - (close - pre_close)` 最大绝对误差约 `1.48e-14`；冻结容差为 `1e-6` 元。
- `pct_chg - (close - pre_close) / pre_close * 100` 最大绝对误差约 `0.005497` 个百分点；冻结容差为 `0.01` 个百分点。

检查只判断是否 ready，不修改源值。

### 3.4 21:00 的边界

P0 在 2026-09-02 盘中验证当日两个接口均为零行，只能证明盘中尚未发布。管理员已经确认：以 Prod 通常在 20:50 左右完成同步为依据，`21:00` 可以作为开发口径，不阻断后续设计和编码。

因此状态分为两层：

- 开发门禁：已通过；可以写 LLD 和进入后续开发评审。
- 启用门禁：尚未通过；正式启用 Sensor 前，必须在一个正常交易日 21:00 后用同一字段和 limit 做一次当日非空复验。失败时只调整发布窗口方案并重新 review，不在代码里猜时间。

---

## 4. 源接口合同

### 4.1 `fund_daily`

```text
api_name = fund_daily
params   = {trade_date: YYYYMMDD, limit: 5000, offset: 0/5000/...}
fields   = ts_code,trade_date,pre_close,open,high,low,close,change,pct_chg,vol,amount
```

| 顺序 | 字段 | Raw 类型 | Silver 类型 | 处理 |
| ---: | --- | --- | --- | --- |
| 1 | `ts_code` | `VARCHAR` | `VARCHAR` | 原样保留 |
| 2 | `trade_date` | `VARCHAR` | `DATE` | 仅 Silver 转换 |
| 3 | `pre_close` | `DOUBLE` | `DOUBLE` | 原样保留 |
| 4 | `open` | `DOUBLE` | `DOUBLE` | 原样保留 |
| 5 | `high` | `DOUBLE` | `DOUBLE` | 原样保留 |
| 6 | `low` | `DOUBLE` | `DOUBLE` | 原样保留 |
| 7 | `close` | `DOUBLE` | `DOUBLE` | 原样保留 |
| 8 | `change` | `DOUBLE` | `DOUBLE` | 原字段名原样保留 |
| 9 | `pct_chg` | `DOUBLE` | `DOUBLE` | 原样保留 |
| 10 | `vol` | `DOUBLE` | `DOUBLE` | 原样保留源端单位 |
| 11 | `amount` | `DOUBLE` | `DOUBLE` | 原样保留源端单位 |

Raw 数值列允许保存源端空值；任何业务质量问题通过正式 check 表达，不通过删行或改值让文件通过。

### 4.2 `fund_adj`

```text
api_name = fund_adj
params   = {trade_date: YYYYMMDD, limit: 2000, offset: 0/2000/...}
fields   = ts_code,trade_date,adj_factor,discount_rate
```

| 顺序 | 字段 | Raw 类型 | Silver 类型 | 处理 |
| ---: | --- | --- | --- | --- |
| 1 | `ts_code` | `VARCHAR` | `VARCHAR` | 原样保留 |
| 2 | `trade_date` | `VARCHAR` | `DATE` | 仅 Silver 转换 |
| 3 | `adj_factor` | `DOUBLE` | `DOUBLE` | 原样保留 |
| 4 | `discount_rate` | `DOUBLE NULL` | `DOUBLE NULL` | 原样保留空值和极端值 |

本地源文档已经补充 `discount_rate` 的显式字段事实；实现不得退回默认 fields。

### 4.3 有界分页

新资产复用当前 `execute_bounded_pages(...)` 和 `TushareRequestPolicy`，不修改旧 `_fetch_all_pages`，也不增加另一套分页框架。

冻结的单分区物理请求预算：

| 接口 | limit | `max_retries` | `max_requests` | `max_elapsed_seconds` | 依据 |
| --- | ---: | ---: | ---: | ---: | --- |
| `fund_daily` | 5000 | 1 | 2 | 30 | 真实 1 页；允许一次重试或第二页 |
| `fund_adj` | 2000 | 1 | 4 | 30 | 真实 2 页；允许两页各一次重试 |

继续使用现有最小请求间隔 `0.13` 秒和退避逻辑。`max_requests` 统计真实网络尝试次数，重试也占预算；达到请求或时间预算仍未取得短页时 fail-closed。

这里不新增“第 N 个 5000 行假页面”的大体量 fake 测试。已有通用分页测试证明短页、重复键和预算停止；本数据集只测试冻结策略、请求参数及 `budget_exceeded` 会阻断候选提升。

---

## 5. 日期、分区与 Basic 合同

### 5.1 共享日期

四个新资产直接复用：

```text
cn_a_etf_mins_trade_days
```

保留这个历史名称是为了不迁移正式 Dagster 动态分区状态。它的长期语义扩展为“ETF 行情共享交易日集合”，由现有 `etf_mins_trade_day_sensor` 继续注册；P1 只修正该 Sensor 的说明文字，不改 Definition 名称和 partition key。

时间语义拆开如下：

| 层次 | 口径 |
| --- | --- |
| 输入时间 | 已注册 ETF 行情交易日 `YYYY-MM-DD` |
| 执行 unit | 一个资产的一个交易日分区 |
| freshness/audit | 只检查已注册交易日，不要求自然日每天有数据 |

### 5.2 latest-only Basic

Silver 复用当前：

```text
select_latest_etf_basic_snapshot_reference(...)
EtfBasicSilverSnapshotReference
classify_etf_basic_requestability(...)
```

日常 Silver asset 在运行开始时冻结一次最新 reference。历史链先完成 Raw Plan、Raw apply 和 Raw 全区间审计；只有随后生成 Silver Plan 时才冻结一次最新 reference，并让全部 Silver 批次复用。Raw Plan 和 Raw apply 都不选择、不冻结、不验证 Basic。reference 至少包含 Raw/Silver 内容 hash、两层 URI、观测时间、资格日期、requestable code 数量/hash 和 reference fingerprint。

Silver 筛选条件为：

```text
ts_code 后缀为 .SH 或 .SZ
exchange 与代码后缀一致
list_status = 'L'
list_date 非空
list_date <= 行情分区 trade_date
```

Basic reference 的“新鲜日期”是执行日；`list_date <= trade_date` 才是历史行情分区的资格判断。两者不能混成“为每个历史日期恢复一版 Basic”。

---

## 6. 资产、路径与依赖

### 6.1 资产拓扑

| 资产 | 直接依赖 | 说明 |
| --- | --- | --- |
| `raw_tushare_fund_daily` | Tushare resource | 全源端当日日线 |
| `raw_tushare_fund_adj` | Tushare resource | 全源端当日复权因子 |
| `silver_etf_daily` | 同分区 Raw + 最新 ready `silver_etf_basic` | 场内 ETF 日线 |
| `silver_etf_adj_factor` | 同分区 Raw + 最新 ready `silver_etf_basic` | 场内 ETF 复权因子 |

Raw 绝不依赖 Basic。Silver 在 Dagster 中用 `deps=` 声明 lineage，不通过 IO manager 传 DataFrame。

### 6.2 正式路径

```text
/Volumes/datasource/data_lake/
  raw/tushare/fund_daily/trade_date=YYYY-MM-DD/part-000.parquet
  raw/tushare/fund_adj/trade_date=YYYY-MM-DD/part-000.parquet
  silver/quote/etf_daily/trade_date=YYYY-MM-DD/part-000.parquet
  silver/quote/etf_adj_factor/trade_date=YYYY-MM-DD/part-000.parquet
```

候选文件只允许位于：

```text
/Volumes/datasource/data_lake_staging/etf_daily/
  operation_id=<run_id-or-bootstrap-id>/<asset_key>/trade_date=YYYY-MM-DD/part-000.parquet
```

正式 Lake 与 staging 必须是同一文件系统。候选完整校验后用 `os.replace()` 原子提升；不得把候选写入正式 Lake 再改名，也不得使用 Kopia。

### 6.3 Catalog

四个资产必须先登记到 `LAKE_ASSET_CATALOG`，同步补充：

- `fund_daily`、`etf_daily`、`fund_adj`、`etf_adj_factor` 中文名；
- 四个 `PartitionModel` 与 `PartitionModelDefinition`；
- schema、path、source、blocking checks、write policy、event policy 和 performance contract；
- `DataDomain.QUOTE_DATA`、`group_name="quote"`；
- Raw `SourceSystem.TUSHARE`，Silver `SourceSystem.DERIVED`；
- `EventPolicy.SUPPORTS_RUNLESS_EVENT_BACKFILL`；
- 不新增“readiness=false”的临时 Catalog 状态或 contract-only 例外。Raw/Silver 的 Catalog entry 必须分别与对应 active asset、checks 和 job 在同一开发切片一起落地，避免 Registry 与 Definitions 中途失配。

---

## 7. 写入与幂等

### 7.1 候选写入

每次只处理一个 `asset + trade_date`：

```text
build request
  -> execute_bounded_pages
  -> 每页按冻结 schema 写入 DuckDB 临时 relation
  -> 生成 staging Parquet
  -> 结构/日期/主键/行数校验
  -> staging read-back
  -> 与正式目标判定
  -> 原子新增或等价复用
```

Raw 的候选完整性校验只覆盖文件传输合同：文件可读、字段/类型正确、非空、日期匹配、主键非空唯一、源端/归一化/候选行数一致、跨页无重复。不在 writer 内判断价格公式或复权因子业务质量。

Silver 候选由一条 DuckDB SQL 从 Raw 与冻结 Basic 生成，保留 Raw 字段顺序，只转换 `trade_date`。候选 validator 检查字段、主键、日期、Basic 身份和 `selected + rejected = raw`；正式业务质量仍由 asset checks 表达。

### 7.2 已存在目标

| 状态 | 行为 |
| --- | --- |
| 目标不存在 | `os.replace()` 原子新增 |
| 目标存在且 schema、行数和完整内容双向等价 | 删除候选，复用目标，不重写 |
| 目标不可读或内容不等价 | 报冲突并停止，绝不覆盖 |

语义等价以冻结字段顺序、类型、主键排序后的完整 relation 为准，使用行数、规范化内容 hash 和双向 `EXCEPT ALL` 对账；不比较 Parquet 文件字节 hash，也不要求与 Prod hash 一致。

### 7.3 行级拒绝原因

Silver 只为诊断记录有界样本，不把 reason 写入行情 Parquet。固定分类顺序为：

```text
NON_EXCHANGE_SUFFIX
BASIC_CODE_ABSENT
EXCHANGE_MISMATCH
STATUS_NOT_LISTED
LIST_DATE_NULL
LIST_DATE_AFTER_TRADE_DATE
```

完整计数写 materialization/check metadata 或 Bootstrap report；大清单写 operation report。

---

## 8. Checks 与准入

### 8.1 Raw blocking checks

两个 Raw 各有三个单一职责 check：

1. `source_contract_check`：字段顺序、物理类型、source/normalized/written 行数守恒。
2. `partition_scope_check`：文件日期全部等于分区且文件非空。
3. `key_integrity_check`：`(ts_code, trade_date)` 非空且唯一。

Raw 额外代码、数值空值或 ETF Basic 缺失不在 Raw 层删行。

### 8.2 Silver blocking checks

两个 Silver 都检查：

- `contract_check`：文件可读、字段/物理类型/顺序精确，日期全部等于分区；
- `source_filter_check`：每个输出代码满足冻结 Basic 条件，reference 与 materialization metadata 一致；
- `key_integrity_check`：主键非空唯一、日期等于分区；
- `source_parity_check`：Silver 与“Raw + frozen Basic + DATE cast”的期望 relation 双向等价，`selected + rejected = raw`；
- 数据集自身数值域 check。

`silver_etf_daily_bar_domain_check`：

- `pre_close/open/high/low/close` 非空、有限且大于 0；
- `high >= max(open, close, low)`；
- `low <= min(open, close, high)`；
- `vol/amount` 非空、有限且不小于 0；
- `change` 公式误差不超过 `1e-6` 元；
- `pct_chg` 公式误差不超过 `0.01` 个百分点。

`silver_etf_adj_factor_domain_check`：

- `adj_factor` 非空、有限且大于 0；
- `discount_rate` 允许为空，非空只要求有限；
- 不做范围裁剪。

Asset check 失败只把分区标成不 ready，不回滚已经原子写入的文件，也不触发自动覆盖修复。

### 8.3 覆盖检查

以同一 frozen Basic 中、且 `list_date <= trade_date` 的代码为期望集合，统计：

```text
expected_codes
raw_matching_codes
missing_expected_codes
raw_extra_codes
silver_codes
```

P0 三日样本：

| 日期 | Basic 期望 | `fund_daily` | `fund_adj` |
| --- | ---: | ---: | ---: |
| 2025-01-02 | 1,022 | 1,019，缺 3 | 1,022，缺 0 |
| 2025-12-31 | 1,377 | 1,376，缺 1 | 1,377，缺 0 |
| 2026-09-01 | 1,648 | 1,645，缺 3 | 1,648，缺 0 |

因此：

- `fund_daily` Basic 覆盖差异固定为 WARN，不阻断 Silver。
- `fund_adj` 在开发阶段也以 WARN 形式实现，保证可以形成全区间 profile；但正式历史 Silver apply 之前必须 review 2025 年以来的完整 profile。若证据要求升级为 blocking，必须同步修改本文、LLD、Catalog、check spec 和测试后再执行，禁止用运行时开关临时切换。

这项后置 review 不阻断 P1—P5 开发，只阻断正式 `silver_etf_adj_factor` 全历史提升。

---

## 9. 日常 Dagster 运行

### 9.1 Jobs

Definition 名称冻结为：

```text
raw_fund_daily_update_job
silver_etf_daily_update_job
raw_fund_adj_update_job
silver_etf_adj_factor_update_job
```

每个 Job 只选择本层单个 asset 与其 checks，使用 `in_process_executor`。Job 文件不放请求、SQL、质量判断或路径逻辑。

### 9.2 Sensors

Definition 名称冻结为：

```text
raw_fund_daily_update_job_sensor
silver_etf_daily_update_job_sensor
raw_fund_adj_update_job_sensor
silver_etf_adj_factor_update_job_sensor
```

统一行为：

- 上海时间 21:00 前直接 skip，不打开 DuckDB、不请求 Tushare。
- 每次只检查共享分区集合最近 10 个交易日，并选择最早不 ready 日期。
- 每 tick 最多提交一个 run，run key 使用稳定 job + partition + contract revision。
- Raw Sensor 在本地目标缺失后，只做一次 `offset=0` 的非空发布探测；它不翻页、不写文件、不把第一页当完整性证据。真正的完整分页仍只在 Raw asset 中执行。这样可以避免把“尚未发布的零行结果”提交成一个永久去重的失败 run。
- Silver Sensor 要求同分区 Raw ready，并先确认最新 Basic 可冻结；不回退旧 Basic。
- 已有文件但 checks 失败时停止并提示人工处理，不自动覆盖。
- cursor 使用统一 v1 builder，只记录当前决策、目标日期、阻断组件、有界计数和耗时。
- 四个 Sensor 均 `default_status=STOPPED`、`minimum_interval_seconds=600`。

一次发布探测每天每接口最多增加 1 个请求；`fund_adj` 即使第一页恰好 2,000 行，也只代表“已经开始发布”，不能替代 Raw asset 的第二页和短页门禁。

现有 `etf_mins_trade_day_sensor` 继续唯一负责共享日期注册。新需求不再增加第五个分区 Sensor。

### 9.3 日常空结果

已注册交易日返回零行时，Raw asset 失败且不创建空文件。ETF 分钟历史链的显式零行文件合同不适用于本次日频 Tushare 数据。

---

## 10. 一次性 Direct Lake Bootstrap

### 10.1 范围与规模

正式 Raw Plan 动态冻结：

```text
cn_a_etf_mins_trade_days 中
trade_date >= 2025-01-01
且 trade_date <= raw_plan_watermark
的有序日期集合
```

按 P0 的 404 日证据估算：

| 项目 | 估算 |
| --- | ---: |
| Raw 文件 | 808 |
| Silver 文件 | 808 |
| 合计文件 | 1,616 |
| `fund_daily` 请求 | 约 404 次 |
| `fund_adj` 请求 | 约 404—808 次 |
| Raw 总请求 | 约 808—1,212 次 |
| 四层空间 | 保守低于 0.5 GB |

这只是选型依据，不是正式执行清单。正式数量、字节和水位由 Raw Plan 重新计算。

### 10.2 执行阶段

```text
raw-plan
  -> bounded-sample
  -> raw-apply
  -> raw-audit
  -> fund_adj coverage review
  -> silver-plan
  -> silver-apply
  -> physical-post-audit
  -> events-plan
  -> events-apply
  -> events-post-audit
```

Raw Plan、Raw apply、Silver Plan、Silver apply、事件 apply 分别需要独立授权。批准任一 Plan 都不代表批准写 Lake；批准写 Lake 不代表批准补 Dagster 事件或启用 Sensor。

### 10.3 Raw Plan 与 Silver Plan 冻结内容

Raw Plan 冻结：

- `operation_id`、生成时间、代码版本、schema/contract revision；
- 有序日期列表、起止日期、数量和 SHA-256；
- 动态水位；
- 两个接口的 API、fields、limit 和 request policy；
- 两类 Raw 正式目标路径清单；
- 目标文件的缺失、结构有效、结构无效状态；
- P0 文件大小基线、预计新增字节、可用空间和 `2.5` 倍安全系数；
- Raw Plan payload hash。

Raw Plan 不请求全历史 Tushare，因此不能提前声称已存在文件与源端返回“内容等价”。精确等价只在 Raw apply 为该日期拉到候选后判断。

Raw apply 执行前只重验：Raw Plan hash、冻结日期集合未漂移、Raw 目标状态没有恶化、磁盘空间仍足够。Basic 的更新、失败或缺失都不能阻断 Raw apply。不同批次不重复做全市场源 coverage 查询。

Raw 全量完成并通过审计、`fund_adj` coverage review 关闭后，才允许生成 Silver Plan。Silver Plan 冻结：

- 父 Raw Plan hash；
- 两类 Raw 的路径、行数和内容 hash manifest，以及 manifest hash；
- 已确认的 `fund_adj` coverage policy revision；
- 生成时最新且 ready 的 Basic reference 及 fingerprint；
- 两类 Silver 正式目标路径及当前状态；
- 预计新增字节、可用空间和 `2.5` 倍安全系数；
- Silver Plan payload hash。

Silver apply 执行前重验 Silver Plan hash、父 Raw manifest、coverage policy、Basic 仍为最新 ready reference、Silver 目标状态和磁盘空间。Basic 漂移只会作废 Silver Plan；不得作废、删除或重写已经完成的 Raw 文件。

### 10.4 批次、checkpoint 与恢复

- 每批最多 20 个交易日。这个数字是 checkpoint 调度上限，不是 20 日大事务；由于每个文件完成后立即释放单日内存并落 checkpoint，批次上限不扩大单分区内存边界。
- 每个 `asset + trade_date` 独立请求、校验、提升并原子写 checkpoint；Raw checkpoint 绑定 Raw Plan hash，Silver checkpoint 绑定 Silver Plan hash。
- 常驻内存只保留单接口单日页；不跨日积累 DataFrame 或 Python 行列表。
- 源请求串行执行，不新增并发。
- 当前文件完成后才领取下一个 unit；失败时保留已完成正式文件和 checkpoint。
- 续跑先核验 checkpoint 与正式文件；等价则跳过，冲突则停止。
- 全区间审计使用一次或少量 DuckDB 聚合扫描，不按 404 日启动 404 个进程。

### 10.5 事件补齐

只有物理文件和最终审计通过后才生成 runless event 计划：

- 四个资产的历史 materialization 全量补齐；
- blocking check 事件只补最近 20 个交易日；
- 更早日期由 frozen manifest、全区间报告和 physical post-audit 保存质量证据；
- 等价事件复用，非等价事件停止；
- 事件写入失败不回滚 Lake，但结案保持未完成并可续跑。

---

## 11. 性能与容量门禁

1. 单日 Raw 用 `execute_bounded_pages(..., retain_rows=False)` 分页消费；每页只在一个 page-bounded DataFrame 中转，再由 DuckDB `INSERT ... SELECT` 写入临时 relation。
2. Silver 用一次 DuckDB SQL 完成 Basic 连接、日期转换、排序和 Parquet 写出。
3. 正式输出显式 `ORDER BY ts_code, trade_date`，不依赖 insertion order。
4. DuckDB 连接统一来自 `DuckDBResource`；生产代码不得直接 `duckdb.connect()`。
5. 查询 Parquet 固定 `hive_partitioning=false`，避免目录分区列混入文件 schema。
6. 不使用逐行 Python `executemany`、跨日全量 DataFrame、并发 Tushare 或每行日志。
7. readiness 对最近 10 日做批量读取；禁止逐日重复查询 Dagster event history。
8. Bootstrap 的磁盘 preflight 至少满足预计新增字节的 `2.5` 倍。
9. P0 已证明单分区和全样本扫描无 spill；开发后仍需做隔离单日与 20 日性能回归，但不允许借性能测试同步全量历史。

---

## 12. 观测与排障

### 12.1 Definition metadata

稳定事实只放 definition metadata：dataset id、source、data contract、schema、path template、source API/doc、partition set。

### 12.2 Materialization metadata

每次运行至少记录：

- URI、row count、observed columns；
- API、脱敏 params、fields、limit、page/request/retry count、elapsed；
- source/normalized/candidate/written/selected/rejected count；
- 文件字节、规范化内容 hash、write mode；
- Silver 的 Basic reference fingerprint、Raw/Silver Basic hash 与 URI；
- missing/extra code count 和有界 reason samples；
- 简短中文结论与下一步动作。

metadata 必须通过项目统一 builder 生成，不裸写无命名空间字段。完整代码清单、全量 profile 和文件 manifest 写 operation report，不塞进 Dagster event metadata。

### 12.3 失败路径

| 失败 | 操作人员下一步 |
| --- | --- |
| 源端零行/请求失败 | 等待发布或重试同一分区，不创建空文件 |
| 分页/字段/日期/主键失败 | 查看 Raw check 和 source request 摘要 |
| 正式目标冲突 | 停止自动化，人工比较候选与正式文件 |
| Basic 不 ready | 先修复最新 ETF Basic，不回退旧版本 |
| Silver 数值域失败 | 保留源事实和失败文件，不自动修值/覆盖 |
| Raw Plan 范围/目标漂移 | 作废旧 Raw Plan，重新生成并审批；不选择 Basic |
| Silver Plan 的 Raw manifest/Basic/policy 漂移 | 作废旧 Silver Plan，重新生成并审批；不回滚 Raw |

---

## 13. 开发顺序

### P0：源端与性能证据

已完成。真实字段、分页、质量阈值、批次上限和容量证据已回填本文；21:00 当日可用性转为启用前验收，不再阻断开发。

### P1：纯合同与共享结构

状态：已完成（2026-09-02）。

- 新增 ETF 日线 run contract、四套 schema、四个 path helper、PartitionModel 和中文名。
- 更新共享分区 Sensor 的人类可读说明，不改 partition definition 名称。
- 本阶段不增加 active Catalog entry，不创建 contract-only 临时例外。

### P2：Raw

状态：已完成（2026-09-02）。隔离 fake/临时目录测试和 `2026-09-01` 两接口最小真实样本均通过；真实样本仅写 `/private/tmp`，未写正式 Lake 或 Dagster event。验收证据见 `dagster-etf-daily-data-onboarding-p2-real-sample-2026-09-02.md`。

- 实现两个 request builder、两套小预算 `TushareRequestPolicy`。
- 基于现有 `execute_bounded_pages` 实现 page-bounded 候选写入。
- 实现 Raw 结构审计、三个 blocking checks、等价复用/冲突停止。
- Raw Catalog entries 与 Raw assets/checks/jobs 在同一切片原子落地。
- 完成隔离 fake、临时目录单测和经批准的最小真实样本验收。

### P3：Silver

- 复用 latest-only Basic selector/reference。
- 用 DuckDB 完成筛选、DATE cast、拒绝分类和候选写入。
- 实现五个 blocking checks 与一个 coverage WARN check。
- Silver Catalog entries 与 Silver assets/checks/jobs 在同一切片原子落地。
- 明确验证 `change` 保留、`change_amount` 不存在、`discount_rate` 不被修正。

### P4：Jobs、Sensors 与 readiness

- 复验 P2/P3 已随各层落地的四个 layer-isolated jobs 的 Definitions 装载与选择范围；P4 不重新实现 jobs。
- 复用 P2 已落地的两个单页发布探测，实现四个默认 `STOPPED` sensors 和批量 10 日 readiness。
- 测试 21:00 边界、最早缺口、已有坏文件阻断、Basic latest-only、run key 和调用次数。
- 在一个正常交易日 21:00 后完成源端非空复验；未通过不得启用。

### P5：Bootstrap 工具

- 实现 raw-plan、bounded-sample、raw-apply、包含 profile 的 raw-audit、silver-plan、silver-apply、physical-post-audit、events-plan、events-apply 和 events-post-audit 工具。
- 只做极小隔离样本，不同步全量。
- 测试停止/续跑、等价重放、目标冲突、Raw Plan 漂移、Silver Plan/Basic/Raw manifest 漂移、空间漂移和事件幂等。

### P6：正式历史建设与启用

按独立授权顺序执行：

1. 正式 Raw Plan；
2. Raw apply；
3. 全区间 Raw 审计和 `fund_adj` coverage review；
4. 必要时同步调整 coverage blocking 合同；
5. 正式 Silver Plan；
6. Silver apply；
7. 物理 post-audit；
8. events plan/apply/post-audit；
9. 启用四个 Sensor；
10. 连续三个交易日验收。

任何阶段发现当前代码、源端或正式数据与本文冲突，都停下来说明，不靠兼容或临时开关绕过。

---

## 14. 验收标准

### 14.1 合同

- 四个资产进入 Definitions 和 Catalog，Catalog 与代码的 key、schema、path、checks、partition、source、write/event policy 完全一致。
- Raw `fund_daily` 恰好 11 字段；Silver 仍恰好这 11 字段，只把 `trade_date` 改为 `DATE`。
- `change` 在 Raw/Silver 中都存在，`change_amount` 在新资产合同、SQL、metadata 和测试中都不存在。
- Raw/Silver `fund_adj` 恰好 4 字段且包含 `discount_rate`；空值和极端值原样保留。
- Raw 不读取 Basic；Silver 每次明确记录使用的 Basic reference。

### 14.2 物理与数据

- 四个资产的日期集合等于正式 Raw Plan 冻结的共享 ETF 分区集合，起点不早于 2025，终点不晚于冻结水位；Silver Plan 通过 Raw manifest 锁定同一集合。
- 每分区恰好一个可读 Parquet；schema、日期、主键、行数、内容 hash 和 source/Silver 对账全部通过。
- `source = normalized = Raw written`；`Silver selected + rejected = Raw`。
- 已存在文件只出现等价复用或显式冲突停止，没有静默覆盖。
- `fund_daily` coverage 差异产生 WARN；`fund_adj` 最终政策有全区间证据和明确 review 结论。

### 14.3 运行

- 四个 Sensor 初始均为 `STOPPED`，没有未经授权的自动运行。
- 21:00 前不做重检查；21:00 后每 tick 每 Sensor 最多一个 run。
- 日常只看最近 10 个交易日，不追赶 2025 历史。
- 最新 Basic 不 ready 时不回退旧版本。
- 正式启用前完成 21:00 源端复验；启用后连续三个交易日 Raw、Silver、checks、cursor 和 metadata 验收通过。

---

## 15. 待后置 review 的唯一事项

当前没有阻断 LLD 或开发的待拍板项。

唯一后置 review 是：Raw 全历史完成后，根据 2025 年以来 `fund_adj` 对最新 Basic 的完整 coverage profile，确认 coverage 最终保持 WARN，还是升级为 blocking。这个决定只影响正式 `silver_etf_adj_factor` 全历史提升和日常 readiness，不改变 Raw 保存源端事实、Silver 只筛场内 ETF、保留 `discount_rate` 等已拍板口径。
