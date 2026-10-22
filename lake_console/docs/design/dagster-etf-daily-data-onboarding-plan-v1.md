# ETF 日线与复权因子 DG 数据湖接入技术方案 v1

> 状态：已结案（2026-09-04，管理员确认）；历史入湖、事件补录、四个 Sensor 启用及首个交易日日常验收已完成；不再等待剩余两个交易日观察；因子 coverage 阻断、日线 coverage 告警的规则不变
> 更新日期：2026-10-23
> 本次补充：§8.6 原依据核验和设计确认已完成；2026-10-23按管理员指令进入开发，合并检查、Basic内存复用和分阶段维护代码已接通，本步隔离验收已通过，证据在§8.6.9及LLD§11.9.14。尚未准备正式候选、改写正式文件、追加正式事件或重载；页首“已结案”只指原P1—P6建设。
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
10. 普通 writer 和原 Bootstrap 的正式文件只允许“新增、等价复用、冲突停止”，绝不自动覆盖。§8.6 的指定缺行追加及检查做法已确认，正式操作仍逐阶段批准；不能据此放宽普通 writer。

以上第2、6、7项描述正常生成和原 Bootstrap，不允许据此用最新 Basic 重算现存历史行；§8.6 只拟将最新 Basic 用于指定缺行的资格核对。

本期不建设 Gold 复权行情，不改 Prod 数据集，不接前端，不从 Prod DB 导出，也不使用旧 Lake Console、旧 Lake Root 或 Kopia。

结案依据：历史 `2025-01-02..2026-09-03` 共 406 日已完成文件与事件验收；`2026-09-04` 已通过正式 Sensor 自然完成四资产更新。管理员在首日验收通过后明确要求直接结案，原连续三个交易日观察不再作为结案条件，不能写成已完成三日验收。四个 Sensor 保持启用，后续进入日常维护；详细记录见 §13 P6。

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
- 不在 P6 逐阶段授权前写正式 Lake、补 Dagster 事件或启用 Sensor。

---

## 3. 建设前事实与 P0 结论

### 3.1 建设前 DG 事实（2026-09-02）

- P0 审计时 DG 尚无这四个正式资产和对应正式 Lake 文件；现已完成建设，结案状态以 §13 P6 为准。
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

- 开发门禁：P0 已通过，后续 LLD 与开发已完成。
- 源端非空复验：2026-09-03 22:29 的 P6 三日样本已使用相同字段和 limit，取得当日日线 2,113 行、复权因子 2,142 行（两页）。2026-09-04 21:15 启用前再次验证当日已发布：日线第一页 2,114 行，因子第一页 2,000 行；因子完整分页由正式 Raw job 执行，最终为 2,145 行。上述结果不证明每天 21:00 准点完成；日常非空发布探测继续保留。四个 Sensor 已单独获批启用，见 §13 P6。

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

日常 Silver 保持执行日 Basic 门禁。历史 Bootstrap 按 Basic 已有的每日上海时间 21:00 更新窗口判断新鲜度：21:00 前允许最新版本的观测日期为昨日或今日，21:00 起要求今日；只检查最新版本，不向前搜索旧的合格版本。先读取最新 Raw 的真实观测日期，再以该日期调用既有同日 Raw/Silver selector，完整复用 checks、文件、hash 和两层绑定校验；异常或选择期间版本变化立即停止。reference 的资格日期采用该快照的观测日期，避免仅因跨零点改变 fingerprint；`list_date <= trade_date` 仍按每个历史行情分区计算。不得改写观测时间，也不恢复不存在的历史 Basic。

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

下表适用于普通 writer 和原 Bootstrap。§8.6 提出的指定缺行追加须独立 review、生成完整校验候选并获得正式写入批准；不能用它放宽下表或对其他文件自动覆盖。

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
- `fund_adj` 已于 2026-09-04 根据全区间 profile 获批升级为 blocking/ERROR。406 日、539,536 个预期 ETF/日期组合缺码为 0；后续缺少预期代码或出现不应进入 Silver 的代码，因子分区不能认定为 ready，历史物理验收不能通过。Raw 额外代码不阻断。2026-09-04 当时的版本标记为 `fund_daily_warn__fund_adj_blocking_v2`；现行代码标记为 `fund_daily_warn__fund_adj_blocking_v3`。本次只校正文档与代码的对应，不改变管理员确认的覆盖规则、不修改代码标记、不触发重跑；不得用运行时开关切换。

该 review 已关闭；批准后的代码、Catalog、check 级别、readiness、历史验收/事件和测试必须同步完成，才能生成正式 Silver Plan。仍遵守“检查失败不回滚文件、不自动覆盖”的既有口径。

### 8.4 历史修复记录（补值实现已清理，正式重载待批准）

512390.SH 源因子从2026-09-10起缺失，当时 Basic 仍为 L。9月10、11、14日的人工修正和批准记录保留；9月15日起，原机制仅向 Silver 补入经批准的 `1.3094 / NULL`，Raw 保留源返回。2026-09-21的正式恢复使9月15日至18日各新增一条已批准人工行，四日各六项 blocking checks 和 readiness 均通过；后续累计18日沿用该机制。

这些属于已经发生的批准和验收事实，不是当前维护步骤。原登记、生成、同值/异值限制和特许覆盖代码已按 §8.5 删除；不保留恢复补值或修改登记的操作指引。历史文件、正式物化、检查和[人工批准记录](../../../DG_DATA_EXCEPTIONS.md)全部保留。

---

### 8.5 2026-10-21：停止补值，保留历史，解除检查依赖

**状态（2026-10-21 清理任务）：已按确认口径完成代码清理与隔离验收；本任务未执行正式代码重载，正式数据与旧事件未修改。** 本节替代此前“用最新 Basic 重建 18 日历史”的提案。该提案已撤回，不是待执行阶段；其计算出的 644 条其他 ETF 记录变化不属于本次目标，也不是任何补数或重建授权。

本节“本次／本轮／历史不动”均指512390清理任务。管理员随后要求单独修订其他56只ETF的缺行方案，见 §8.6；它不追认旧整份重建提案，也不改变512390原有行。§8.5 的完成记录不能作为 §8.6 开发或写入授权。

#### 8.5.1 已确认口径与禁止项

1. **2026-10-19 起停止为 `512390.SH` 补入 Silver 因子。** 按业务日期划界，不追究源状态改变的小时分秒。最新 Basic 已为 `D`，新生成的 Silver 按最新可用 Basic 正常排除它；不新增缺行补值、默认值或其他自动兜底。
2. **2026-10-19 之前的历史数据全部保留不动。** 不增删人工因子，不重拉 Raw，不改写旧 Basic，不替换历史 Silver，不重跑历史写入任务，不补发历史物化、不清理旧事件。此前经批准写入 Raw/Silver 的人工记录及其批准证据保留。
3. **历史检查不再执行或依赖被删除的补值逻辑。** 对已经批准、已经通过检查且文件未变的历史结果，核验其原有验收证据和输入/输出是否改变；不重新生成一行冻结因子来证明历史结果，也不把最新 Basic 套到旧文件上要求重新筛选。
4. **不处理其他 ETF 的历史覆盖差异。** 不纳入此前整份重建测算出的 644 条记录；不扩大到 ETF 日线、分钟线、Prod 或其他数据集。不能为了让历史检查通过而顺手补数、改名单、扩大扫描或降低检查级别。
5. 删除补值模块、登记 YAML、自动补行和特许覆盖分支，以及专属补值测试和运行说明。保留普通源对账、文件完整性、当前预期代码覆盖和拒绝冲突覆盖。历史证据不足或文件改变时仍阻断，不能只因日期早于 19 日就跳过检查。

#### 8.5.2 当前事实与改动原因

源端 `fund_adj` 当前查询最后一条为 2026-09-09。历史 Basic 抓取中，10 月 18 日仍为 `L`，10 月 19 日首次观察到 `D`。本次只需使用 10 月 19 日这个业务分界；因子停更与状态改为 `D` 没有同步，不能把 `L` 当成源接口保证当天必有因子。

清理前代码有两种不同用途：

| 用途 | 清理前代码依据 | 本次目标 |
| --- | --- | --- |
| 新 Silver 生成 | `assets/etf_daily.py:silver_etf_adj_factor` 选择最新通过检查的 Basic | 保留最新 Basic 筛选；删除补值和特许覆盖；D 正常排除，其他应有代码缺因子仍阻断 |
| 已有因子文件检查与日常 readiness | `checks/etf_daily_checks.py`、`asset_guards/etf_daily_lake_readiness.py` 读取该文件物化时保存的 Basic 引用，并调用补值解析器 | 原 Basic 引用保留作为历史依据；历史检查核对已验收结果和文件未变，不重放补值，不用最新名单重算历史 |

18 个历史因子文件的现存物化记录证明曾自动补值。这个数量只是依赖审计范围，不是文件重写清单。其内容和原物化不变；新 Basic 为 D 不会自动改变它们，也不要求改变它们。早期 9 月 10、11、14 日人工修正同样保留。

[此前只读审计报告](../../reports/etf_adj_factor_workaround_retirement_audit_20261021.json)中的“29,700→30,326、增加 644 行”仅记录已撤回提案的模拟结果，不能被当作本次执行目标、验收数量或待审批数据迁移。

#### 8.5.3 历史检查的设计边界

本次不新增补值登记、历史特例名单或保存另一份数据结果。历史检查只可复用正式 instance 中已有的物化、原先绑定的六项 blocking check 验收事实，以及正式 Raw、Basic、Silver 的既有指纹。详细条件见 LLD §11.8。

- 只有已批准并完成验收的旧补值文件，才进入这次历史检查调整范围；不是所有 19 日以前的文件自动通过。
- 必须核实原物化与六项检查绑定、原验收通过、Silver 内容未变、原 Basic 内容及引用未变、Raw 与原验收对应的版本未变；仍检查实际文件的字段、键、日期和数值合同。不得拿当前文件先算一个新指纹，再把它冒充历史验收依据。
- 对历史结果的认可，是保留当时已获批准且未改变的事实，不宣称那些人工因子是 Tushare 原始返回，也不要求它们重新满足“没有人工补值”的新生成规则。
- 若既有记录不能证明上述条件，必须报出缺少的证据或变化文件并停止；不得自动重建、补行、修改旧记录、忽略失败或重新补绿色事件。开发前须先完成原有证据可用性核验；不足时仅报告，不另造处理办法。
- 日常 sensor 最近 10 日的检查与手动重查须共用同一判断，避免历史文件未变却在删除解析器后阻断后续日期。其他文件继续遵守原有检查规则。

#### 8.5.4 实施顺序、预算与验收

1. 先按 LLD 对现有 18 个自动补值文件及有界正常对照核验原有物化、检查和指纹证据，写只读结果；不执行历史写入。证据可用性通过后，才开发统一历史检查与 readiness，随后删除补值代码和配置，最后清理旧运行说明。
2. 用隔离测试证明停止补值、保留历史、旧文件未变可核验、缺证据或文件变化会阻断；同样证明最近 10 日包含旧文件时日常更新可继续，而当前日期真正缺因子仍会阻断。所有输入和预期有独立依据。
3. 实际上线、代码重载、正式检查执行或 sensor 状态变更另列完整命令和边界，按正式操作门禁执行。清理任务在方案阶段不执行上述正式操作；之后已完成的代码与隔离验收另记于 §8.5.5。历史 Raw、Basic、Silver、旧物化和旧检查记录写入数必须始终为 0；不生成 Lake staging 候选，不安排历史重建任务。

| 项目 | 预算与边界 | 失败或中断处理 |
| --- | --- | --- |
| 开发前只读核验 | 18 个已有补值日期及不超过 3 个正常对照；分批不超过 10 日，只读已有证据和文件；目标 30 秒、1 thread / 256 MiB，不读取全部 ETF 历史 | 缺少证据、版本不明或文件变化即停止；中断只留下临时报告，续跑只重查本批范围 |
| 日常历史检查 | 仍为最近 10 个交易日；物化按资产批量查询、原六项检查按窗口批量读取，每窗口最多 60 条目标检查；原 Basic 重复引用只验证一次 | 不逐日查询或深扫全历史，不放宽原覆盖和文件合同；超预算先调整读取方式 |
| 最后验收及续查 | 同样限于上述日期，分别预算 30 秒；Tushare 请求、Prod 访问、历史 Lake 写入和历史事件写入均为 0 | 不扩展到其他 ETF 补数；禁止将只读通过写成已上线或正式检查执行通过 |

实施细节见 LLD §11.8.2：checks/readiness 共用只读核验；原验收和最新状态按10日窗口一起读取，另批量定位原 Raw，不逐日查库；复查本身不能充当原验收。

最终验收必须证明：补值模块/YAML 和写入分支已删除；历史文件与旧记录没有变化；旧文件检查不再 import 或调用补值解析器；正常缺数仍阻断；该512390清理任务不存在对644条记录的写入、候选或补跑，不把其他ETF补齐作为清理验收的剩余步骤。其他56只ETF的新提案见 §8.6，须独立 review。18 日原验收和实际内容的只读核验已完成，详见下段；代码与隔离验收结果见本节末尾，正式重载仍未执行。

**2026-10-21 只读核验补充：** 18 个历史因子文件各自原写入记录对应的六项 blocking checks 共 108 项均通过并正确绑定；18 份 Raw 与 18 份 Silver 的实际内容指纹均匹配原依据。18 日共同引用的旧 Basic Raw/Silver 两份快照，在管理员单独批准约 224 KiB 全快照读取后各读一次，其内容指纹也匹配原引用。无任何正式写入。详见[只读核验报告](../../reports/etf_adj_factor_terminal_cleanup_readonly_verification_20261021.json)。该报告用于设计审计，不作为新的运行时补值输入。

其他 ETF 的判断必须逐对象、逐日期区分源端、Raw 和 Silver，不能把旧重建测算中的 644 条都当成错误。`158011.SZ` 的旧 Basic 已为 L、但上市日期为空；当前上市日期为 2026-09-04。本次有界核验确认，上市日至 10 月 20 日共 27 个 SSE 开市日，源端因子日期无缺口/多余，Raw 也完整，因子值均为1.0；旧 Silver 未包含其中前25日，只有10月19、20日两天。源和 Raw 无须因此重刷；Silver 的历史覆盖差异单独记录，不因本次512390清理获得补数授权。贴水率与现查源值的差异在报告中另列，不与因子日期/数值结论混用，不推定原因或触发写入。


#### 8.5.5 本轮实施对账

已删除因子补值模块、YAML、特许覆盖及原专属生成测试。普通 writer 仅使用 Raw + Basic；新检查与日常 readiness 共用 `defs/asset_guards/etf_adj_factor_history.py`，只核对原验收及现存文件，不生成因子、不新增名单，不改合同版本、资产、job、sensor、分区或运行入口。

隔离验证覆盖29项512390专项场景；含真实六项检查在隔离 Dagster job 中对原目标复查、正确绑定及文件不变。ETF与调用方回归207项、受保护资产治理12项和增量治理6项，共225项通过；结果统一见 [LLD §11.8.7](dagster-etf-daily-data-onboarding-low-level-design-v1.md#1187-本轮实施与验收结果)。正式只读验收用新读取实现关联18天原验收和最新状态，36份 Raw/Silver 文件内容指纹均匹配，耗时4.22秒；两份旧 Basic 复用先前单独批准的核验，不重复完整读取。

本轮正式数据、事件、任务、sensor状态写入为0；未请求Tushare、未访问Prod、未处理644条其他记录。代码重载是剩余独立操作，按 LLD §11.8.8 的明确范围另行确认，不能把代码验收写成正式发布完成。


---

### 8.6 2026-10-22：只补指定代码和日期的缺行

#### 8.6.1 本次要做什么，以及不做什么

管理员确认的口径是：**只补指定ETF代码、指定交易日的缺行，原有行零修改、零删除。最新 Basic 仅用于判断这些新增行，不用于重筛整份历史文件。** 方案修订阶段只修改两份文档；管理员随后已要求按方案推进，前置核验和开发进度见 §8.6.6、§8.6.7。正式文件及事件仍须逐阶段批准。

例如 `158011.SZ` 上市日为9月4日，Raw 已有9月4日至10月16日的25条因子，而 Silver 缺这25条。本次拟从对应日期的 Raw 原样加入这25条；同一文件中的512390和其他ETF原有行全部保留。Parquet 保存时需要生成包含原有行和新增行的完整文件，但业务上只追加缺行，不用最新 Basic 重新计算所有旧行。

| 范围 | 只读核验事实／拟议边界 |
| --- | --- |
| 代码 | 固定56只：旧 Basic 无代码20只、上市日期为空7只、仍为P29只；代码与上市日期逐项列于 LLD §11.9.2 |
| 日期与数量 | 从各自上市日起核对至2026-10-21，应有869条；Raw869条齐备，Silver已有168条，缺701条，分布于26个日期文件；逐日期数量列于 LLD §11.9.2 |
| 644与701 | 原644条只统计9月15日至10月16日；本次从同56只ETF各自上市日起核对，多出9月3日至14日的57条，不是另增代码，也不是644只ETF |
| 拟议正式写入 | 只允许26份 `silver_etf_adj_factor` 文件合计追加701条；所有原有行保持原值，删除0条、修改0条；不承诺尚未执行的写入已成功 |
| 最后验收只读 | 上述26日，加10月19、20、21日，共29日；额外3日仅核对56代码共168条已有行及既有文件指纹，不生成候选、不追加物化、不运行检查。其他普通/未改动历史对照只在隔离测试，不另读正式日期 |
| 不改动 | Raw、Basic及其事件；ETF日线、分钟线、其他代码、Gold、Prod；已完整的10月19、20、21日；512390全部历史原有行及其批准记录 |

证据时间为2026-10-22 00:19（上海时间），当时最新 Basic 抓取于10月21日，56只均为L且有上市日期，Raw 均从各自上市日开始，无上市前记录、缺日、重复键、非法因子或现存 Raw/Silver 数值差异。这是56只的有界核验，不是全部ETF完整性结论，也不代表以后新上市ETF不会再次出现资料延迟。

已有[逐代码审计结果](/private/tmp/etf_56_listing_coverage_20261022.json)仅作本次设计证据，临时文件不是执行输入或运行时名单。固定代码、上市日期和逐日期数量已写入 LLD；正式 Plan 另从实际 Raw/Silver 和正式验收记录取得明确的701组代码、日期及内容依据，冻结后不得自动扩大范围。若准备时数量、上市日期或文件内容与本次证据不同，先说明变化，不能静默改目标后继续。

#### 8.6.2 为什么不能直接重跑现有入口

已核对当前实现：`io/etf_daily_silver_writer.py` 的普通 writer 按整份 Raw 和 Basic 生成候选，并拒绝覆盖不同内容；`bootstrap/etf_daily_bootstrap_apply.py:_write_silver_pair` 同时写ETF日线和因子。原事件入口还要求四资产并按尾部窗口检查。这些行为都不符合“只向26份因子文件追加指定行”，不能直接重跑、加通用覆盖开关或借补齐重建整份数据。

`asset_guards/etf_adj_factor_history.py:audit_factor_history` 当前要求整份 Silver 指纹匹配原验收。新增一条真实缺行也会改变整份指纹；反过来按最新 Basic 重筛又会排除已保留的512390。因此拟在原ETF维护代码中增加有独立阶段的指定缺行入口，并调整共用检查；不恢复已删除的补值代码，不另设任务调度、配置或数据集。具体改动位置与当前实现的区别见 LLD §11.9.3。

#### 8.6.3 如何证明只加了批准的行

1. **先保留原依据。** 每日记录原正式物化、绑定它的六项成功检查、原 Raw/Basic 引用及原文件内容指纹。所有原有行的预期值来自这些原验收事实，不从补完后的文件倒推。26日原验收是否全部足够仍是正式 Plan 的前置核验，不能拿此前18日的通过结论冒充26日已通过。
2. **新增行只来自现有 Raw。** 冻结准备时最新且 ready 的 Basic，只对56只指定代码和日期核对后缀、市场、L、上市日期；只选择批准缺行，不改因子或贴水率，NULL贴水率保留NULL。缺源行、同键异值、重复、异常日期或范围变化立即停止。
3. **保存前完整核对候选。** 去掉明确的新增键后，候选必须与原已验收文件的全部行完全相同；新增部分必须与对应 Raw 的指定行完全相同；整体字段、日期、主键、数值合同及行数全部通过。任何一条未批准新增、原值改变或原行消失都拒绝。
4. **补后检查使用同一判断。** 原物化和原检查保留不改；新物化记录原验收依据及本次新增范围。正式六项检查合并为一个执行步骤，共用一次完整核验，再分别产生六项结果；整体通过条件是六项全部通过，任一项失败则本次检查整体失败、该日期不ready并停止推进。分别保留各项真实结果，不把正常项目改成失败，也不把失败改成通过；与 readiness 共用文件判断，分别证明原行未变、新行有源且符合资格。不继续声称整份文件没变，不拿新检查冒充原验收，不用最新名单要求删除原行。新旧 Basic 各自负责的范围、计数及事件绑定见 LLD §11.9.4—§11.9.7。

这里的“补齐”是把已有源行送入 Silver，不是人为制造因子；512390的人工行仍只按原批准事实保留，不被说成 Tushare 返回。

#### 8.6.4 顺序、授权和失败处理

| 阶段 | 本阶段可产生的内容 | 后续门槛 |
| --- | --- | --- |
| 当前文档 review | 只改本方案与 LLD，并自查；不改代码、不生成候选、不执行补齐 | 管理员 review；文档确认不等于正式写入批准 |
| 开发与隔离验收 | 2026-10-23获准按LLD开发，合并检查、内存传递与维护分阶段代码已接通；本步验收状态以§8.6.9为准 | 复用仍有效的原核验证据；证明一次核验、六项真实结果、仅运行检查及性能；未通过不得准备正式写入 |
| 正式 Plan 和候选 | 另列具体命令、路径和预算，取得本阶段批准后冻结701键、原文件依据及最新 ready Basic，生成并完整审计26份 staging 候选 | 交管理员 review 候选差异：新增701、删除0、修改0；不接触正式文件或事件 |
| 文件提升 | 再获正式文件写入批准；逐文件重核原目标和候选，使用同文件系统 `os.replace()`；逐文件保存进度 | 文件替换不是事件登记，不宣称已 ready；失败停止，已完成文件不回滚 |
| 新物化与检查 | 文件提升并读回一致后，每日追加一个新因子物化，再触发现有任务的检查部分；26日各一次真实运行，每次一个核验步骤产生六项结果 | 合计26个新物化、156项新检查，另有26次运行及其日志；正式操作仍须独立批准，不改旧记录、不登记其他资产，失败停止；重载另审当前工作区 |
| 最后验收 | 26日核对完整文件、701键、原有行和新事件绑定，按最多10日3批复查readiness；另核对19—21日已有168行及文件指纹，合计29日 | Basic复用同一已核验内存，缺失即停；不额外运行正式检查或登记事件。输出完成量及未完成项，不能把部分成功说成全部完成 |

正式文件与 Dagster 事件不能一次提交。文件已换而新事件未齐时必须显示尚未验收并阻断，不能沿用旧成功判 ready。中断后根据冻结 Plan、实际文件指纹和逐文件进度继续；文件已等于已验收候选时只读回确认，不能再次追加；出现第三种内容立即停止。新物化已写而进度未保存时，按本资产、本日期只读最新1条物化；与本Plan、文件及原依据完全一致才复用真实target，仍为冻结原物化才允许首次追加，其他情况停止。新物化target保存成功后才准备检查运行编号；检查中断才按预存run_id查回，两者不能混用。正常每日期物化追加前最多查1次，确实追加后再查1次并保存target，26日该子步骤最多52次查询，计入事件阶段30秒；中断续查沿用同样上限，不自动轮询或重发。已经落下的失败检查不能当成未完成而自动重发，须先说明原因，另审后续处理及新增事件数量。只保留候选、报告和进度，不备份正式文件、不删除旧文件或事件、不使用 Kopia。

#### 8.6.5 性能、测试与验收

处理单位是一个日期文件，一次一个文件；候选和提升仍只限26日、701新增行，每份候选最多5000行、26份合计最多130000行，26日Raw/原Silver/候选三组文件字节合计上限16 MiB。最后验收单独限定29日Raw/Silver共最多58个不同文件，总字节同样不超过16 MiB；58不是扫描次数，实际扫描/载入次数仍须测量。1线程、256 MiB、禁止 spill。这里是停止上限，不是正式执行实测。Plan核验、候选生成、候选总审计、中断后续查、最后验收各预算30秒；文件提升阶段和事件阶段各预算30秒，逐文件/逐事件检查取消，超过预算保存进度并停止，不放宽数量或资源。最后26日readiness最多3批、每批最多4次证据查询；额外3日Raw/Silver各1次物化查询，最多6条记录，最后验收合计最多14次证据查询，复用结果核对新物化及156项检查，不另加一轮事件审计。日常读取仍限10日窗口，具体查询和事件上限见 LLD §11.9.8。

本次不请求 Tushare，不访问 Prod，不把旧644条模拟报告当作补齐依据。Plan/候选/提升及新事件只处理26个变更日期；最后验收才增加10月19—21日的上述只读核对，其他日期不得进入正式读取清单。Basic沿用§8.6.7已确认的内存复用；原4份快照各一次完整读取批准已经使用，不因方案确认而获得重复读取许可。内容丢失或另需完整核验时，必须先列确切快照、字节和用途，另获全局读取批准，不能静默重读。

测试必须证明：只新增批准键；原行含512390零改变；未批准代码不加入；同键异值、证据不足、日期/源内容漂移会停止；内容不变仅时间变化不会误拦；中断、重复执行和事件失败能够安全续做；正式六项检查与 readiness 判断一致。全量验收是“56只上市日至10月21日的869条齐备，新增恰为701条，原有行修改0、删除0，26日检查正确绑定”，不是全市场重建或其他数据集修复。详细逐项对照见 LLD §11.9.9。

六项合并执行的优化目标是：本次补后正式检查阶段每日期完整核验从六次降为一次，26日从156次降为26次，不能在合并步骤内仍调用原核验六遍；候选生成/审计和最后验收仍各按原预算执行，不计入这26次。六项名称、blocking级别和结果记录数保留；这不是减少PG记录数量的整改。先在隔离环境测固定一天的任务启动、文件/Basic读取、核验、保存结果及日志数量/字节；再评估26日、续跑及最后验收。总耗时不承诺缩短六倍，原30秒阶段预算不自行放宽，实测未满足或跨运行Basic复用未验证时不得正式执行。详见 LLD §11.9.12。

---

#### 8.6.6 2026-10-22历史推进记录：获批完整读取前的核验及随后进度

本段前四段保留当时尚待Basic读取批准的状态，随后完成的事实见本段末尾；当前检查决定见 §8.6.7，不能把历史等待状态当作当前仍未答复。

管理员已要求按本方案和LLD推进。本次先完成有界只读核验：26日各自最新Silver物化所绑定的六项检查共156项全部成功，且来自原运行；26份Silver共42,900行、对应Raw共56,349行，实际内容指纹和行数均匹配各自现存物化，52份输入文件合计802,735字节，文件核验0.517秒。没有产生候选、正式数据或事件。

9月10、11日的Raw修正于9月12日已批准并完成，9月15日才补登记Raw事件，因此其最新Raw事件编号晚于Silver。该顺序已由[原批准记录](../../../DG_DATA_EXCEPTIONS.md)说明，不能只因编号先后认定内容又被修改；两日实际文件仍匹配现存修正记录。本次不改写或补发这些事件。

26日共引用同一旧Basic物理快照，但有20个不同日期的引用。完整核验须按实际Raw/Silver快照内容去重，再逐一核对引用本身的日期与资格计数，不按20个引用重复完整读取。新增依据为10月21日最新版Basic；旧版及最新版各Raw/Silver两份，共4份、466,819字节，已单独请求完整读取批准，尚未取得本次答复。此前仅两份旧快照的一次批准不扩大使用。

本段仅记录已完成的前置读取；Basic完整内容与引用尚未全部复核，开发、冻结可执行Plan、候选、正式提升、事件和重载均未执行。不能把本次156项原检查通过写成补齐后的156项检查通过。

**随后完成：** 管理员单独批准4份Basic各读取一次；四份实际内容指纹、两版Raw/Silver投影、20个历史引用及26日旧文件源对账均通过。已读取内容只留在本次进程内复用，不导出Basic明细。按 LLD §11.9.11 的明确代码范围进入开发；原有行保留、新增范围和各阶段批准边界不变，尚未生成候选或写正式文件/事件。

#### 8.6.7 已确认：六项合并执行，补数后真实检查并追加记录

**状态：管理员已确认下述设计，并于2026-10-23要求严格按LLD完成下一步开发。** 合并检查、内存复用与维护分阶段代码已接通；当前开发验收结果以§8.6.9和LLD§11.9.14为准。尚未冻结正式可执行Plan、生成正式staging候选、改写正式文件或登记新事件，不能把开发通过写成已补齐或正式执行批准。

**原方法为何停止：** Dagster保存检查结果的表按“资产、检查名、run_id、日期”判重。9月3日已有6项直接保存的检查，run_id为空；原直接补登记接口同样使用空run_id，绑定新物化也不能消除冲突。这是检查结果保存方式的问题，不是26日全部存在同一种冲突，也不是因子文件不能更新。旧记录继续作为原验收依据，不覆盖、删除或改名，不伪造运行编号。

**管理员确认的两个决定：**

1. 采用“合并执行、保留六项结果”：ETF Silver因子六项检查进入同一个执行步骤，文件和所需依据共用一次核验，再产生各项真实结果。正常更新和本次历史追加使用同一实现；六个检查名和blocking级别不变，单项选择能力保留。完整六项中任一项失败，则整体检查失败、该日期不ready并停止；缺项或结果不可判定也不能算整体通过。不合成一个新检查，不扩展优化其他数据集。
2. 26份正式Parquet按已审核候选替换并读回一致后，先追加新文件物化记录，再使用现有 `silver_etf_adj_factor_update_job` 的检查部分按日真实运行。26日各一次，每次只运行合并检查，不执行文件writer。Dagster按真实运行生成新检查记录；保留不改的是原文件的Dagster物化记录和原检查记录，不是原Parquet内容。顺序为“正式Parquet替换并读回 → 追加新文件记录 → 真实检查 → 保存新结果”；不增加旧Parquet副本，整体检查通过前不ready。

26日是既有56代码、701新增键的26份变更文件，不是额外扫描日期。正常成功目标为26个新物化、156项检查结果，加上26次运行及其日志；182不是全部event log数量。保持原有行修改0/删除0、Raw/Basic不写入、512390历史行保留，不新增永久job、sensor、表、配置或日志清理任务。

**已确认的分项判断与整体结果：** 共同读取、核验不等于一份输入出错就把六项全部判失败。普通文件按每项实际依赖分别记录错误，例如Silver和Basic正常但Raw缺失时，字段、筛选、主键、值域仍按原规则判断，依赖Raw的源对账与覆盖失败；整体检查仍失败。不得直接复用现有完整核验遇Raw缺失就整体提前返回的方式。先保留各项真实结果，再按六项全部通过判断整体；运行本身也必须按blocking/ERROR表现为失败并停止，不能仅因函数返回就报成功。分项依赖与正反例见 LLD §11.9.12。

**开发阶段必须完成、正式执行前必须通过的验证：** 真正只核验一次；六项结果及失败规则正确；正确传递指定日期；只运行检查、不调用任何资产writer；9月3日保留旧结果后可新增并正确绑定；中断查回而不重复运行，失败不自动重发转绿；固定一天的读取、启动、计算、写结果和日志成本。共享Basic的读取仍遵守既有一次批准与批次复用要求，不能借26次运行重复全局读取。任何一项未通过不得进入正式执行，不增加辅助资产、第二套入口或范围外查询来绕过。完整条件见 LLD §11.9.12。

[集成模板§10A](../templates/dagster-dataset-onboarding-template.html#human-readable)已禁止为了机器方便拆出大量细碎check；[性能规范§3](dagster-data-pipeline-performance-governance.md#3-开发前性能设计清单)要求核算检查数量造成的读取及事件写入。本次按管理员决定保留六项结果，必须分别披露“重复计算减少”和“结果记录数量未减少”，不宣称已解决PG历史膨胀，不借此清理日志或修改模板。

**已确认：Basic在同一维护进程内复用（2026-10-23，代码已接通，正式执行未进行）。** 由维护入口保留旧版与冻结新版的已核验Silver Basic内存内容，串行调用26次真实检查；最后26日readiness的3批验收，以及续查中确实需要文件和Basic资格核验的环节，也显式接收同一份内容。每次检查和每批验收使用独立DuckDB连接，通过已有 `CompletionBasicCache.seed()` 导入所需内存内容，在各自连接内分别核对日期引用，不共享会被关闭的连接、不再完整读取Basic Parquet。维护入口先检查必需内容和引用，再调用共用核验；缺失、错快照或错内容立即停止，不能把维护输入缺失当作普通日常调用而回退读取。只查询运行编号状态、不需要Basic的步骤不额外增加Basic前置条件。日常因子任务和日常readiness保留正常读取规则；不新增永久缓存、跨进程共享、环境变量或Basic导出。现有一次读取批准已经使用：只能复用仍实际持有那些行的原进程；若已丢失，保留进度，单独说明原四份文件各一次、共466,819字节的重读需求，获批后才继续未完成日期。小样本资源传递的原实验见§8.6.8；本轮已接通维护入口，26日与恢复成本的开发验收见§8.6.9，不把隔离证据扩大为正式执行。

**Basic复用的代价与限制：** 进程退出会丢失内存内容，不能只凭逐日进度自动恢复；省去持久保存Basic的设施，代价是需要停下并在获批重读后继续。每次独立连接仍要复核内容指纹、导入临时表并核对日期资格，不是零计算；26次真实运行的初始化和日志成本也仍在，不能承诺六倍提速或已经满足30秒。内存里的行、JSON和临时表占用会大于压缩文件大小，需测峰值。26次运行使用冻结Basic，不自动追随后来的资料修正；涉及本次代码/上市日的变化仍须按原Plan规则核对。本轮已把跨运行传递与缺失守卫接入维护入口、合并检查和最后验收；原实验不是当前实现验收的替代，正式数据内容仍须复用已获批的内存，不隐式重读。该办法只针对本次有限快照，不推广成通用缓存方案。

开发时维护运行在现有run tags中复用`goldenshare/history_completion`记录本Plan hash，合并检查据此识别维护运行；即使Basic资源传递丢失，也必须停止，不能把None误认作正常日更。它是本次运行身份，不是新增配置或运营开关；不保存Basic明细。内部资源接口、受控DuckDB及测试隔离方式见LLD§11.9.12。本步开发覆盖已列的合并检查、内存传递和维护各独立阶段，所有运行验证只使用临时文件/实例；完整CLI不得自动重读Basic或把正式阶段一键串跑。

**已确认：少见中断只做最小防护。** 管理员同意按低频异常处理，不开发复杂恢复。每日期先读已有进度：已有拟用运行编号就沿用，只有没有编号时才生成一次UUID，并在调用Dagster之前连同本日身份原子保存；保存失败不启动。随后由Dagster用这个编号正常创建、执行真实检查，不是伪造编号直接补写结果。中断后按已保存编号精确查回；成功且六项及文件依据一致则复用，未开始、运行中、失败或不明就停下人工确认，不接通用恢复、不自动重试、不扫描全历史。

首次新执行与旧进度续查分开：本次刚生成且保存成功、确认未被使用的编号可以首次调用；续查已有编号却查无记录时，须确认原维护进程已退出且同日无在途运行，才可用同编号首次创建。原进程仍在或无法确认时停止；已有运行不能再传给 `execute_in_process` 试图接着跑，遇编号已存在也不得换新编号重试。现有逐日进度记录与接口即可承载，不新增表、服务、配置或自动恢复分支。完整字段、顺序、状态处理和最小测试见 LLD §11.9.12。

Basic复用及其代价、少见中断处理和前轮3处补充均已由管理员确认，不再列为待拍板方案。当前开发与隔离验收见§8.6.9；§8.6.8仍仅保留原机制实验，不把设计确认、代码开发或隔离通过当作正式补数或任务执行批准。

#### 8.6.8 2026-10-23：仅验证Basic内存传递与缺失时停止

管理员当时要求先验证跨运行传递Basic及传递失败时停止，该次授权只覆盖设计机制验证。随后已整体确认Basic复用方案，现行设计见§8.6.7；后续确认不改写本实验的范围，也不批准26日正式执行。使用两份各两行、符合现行14字段Silver合同的人工内存样本和两个固定日期引用；连续执行两次正常的临时Dagster检查，再执行一次缺少内存内容的失败检查。调用现有 `CompletionBasicCache.seed/get`，每次独立DuckDB连接；通过内存资源传递同一对象。另做一次不seed的对照，证明现有完整读取分支会被检测并阻止。

运行仅在 `/private/tmp` 的隔离实例和临时目录内；正式Lake、数据库、原Basic内存会话、正式job/sensor及Tushare访问均为0，不生成或读取任何Parquet。上限为3次临时真实检查运行、2份各2行的Basic、1线程/256MiB/无spill，完整实验预算30秒；包含关闭实例、连接和报告的时间。失败即停止，不扩大日期或样本，不安装依赖。实验脚本完成后删除，仅保留不含Basic明细的结果和临时执行日志；当前任务负责清理。

本步必须区分：SDK传递同一内存对象、现有seed/get可使用内存、实验入口缺失即拒绝三类证据，与正式维护入口已接通、原六项规则已验收及26日性能三类未完成事项。实验守卫不代表现有生产入口已具备守卫。详细合同、隔离边界和验收见 LLD §11.9.13；验证结果完成后落回原文。

**2026-10-23验证结果：** 本机Dagster 1.13.26下，两次临时真实检查均成功，分别使用2026-09-03、09-04；收到同一内存对象，独立连接均已关闭，4次`get`完整内容及日期引用核对通过，Basic完整读取尝试0次。缺失内容的第三次运行如期失败，创建连接、`get`和完整读取尝试均为0。未seed对照触发1次完整读取尝试，在实际读取前被哨兵阻止；因此现有缓存缺失时默认读取的行为仍然存在，正式入口必须在进入缓存前拒绝缺失内容。

完整实验（含实例/连接关闭及摘要写入）实测1,310.695毫秒，符合本步30秒预算；只是两份各2行样本，不代表26日或原六项检查的耗时。正式文件访问、Parquet打开、网络尝试及writer调用均为0。摘要为 `/private/tmp/etf-basic-memory-20261023-rvrqk2h4/result.json`，真实运行编号与分项耗时见LLD§11.9.13。临时脚本在核对后删除，不保留正式入口改动。

#### 8.6.9 2026-10-23本步开发完成，正式补数尚未执行

已按确认的LLD接通六项合并检查、Basic严格内存复用，以及独立Plan、候选、总审计、提升、事件、最后验收入口。原六个名称、blocking/ERROR、单项选择和正常写入政策保留；一项失败则真实运行失败。新文件仍只允许固定56只ETF、26日新增701行，原有42,900行不改不删；不以最新Basic重筛整个历史文件。新物化与新六项由真实运行追加，旧记录保留；路径、取消、后续失败和进度保存间隙均有停止/恢复用例。

去重后ETF307项、治理及静态131项，合计438项通过；Ruff、文档完整性和独立代码/方案对账通过。完整临时样本匹配Raw56,349行及Silver42,900→43,601行，26次真实检查生成156项结果；每日期只完整核验一次。阶段实测为Plan0.950秒、候选1.576秒、总审计1.103秒、提升1.846秒、新记录及检查4.283秒、整批成功后续查1.363秒、最后29日验收1.079秒，均保留30秒上限。成功续查新增运行/物化/日志0；Basic完整重读0。

最后验收实测58个不同文件、58次载入、8次证据查询（上限14），701+168=869。26次运行702条日志、1,506,927序列化字节，开发回归及正式预检预算为702条/2 MiB；26条物化另算，不把该字节数当作PG物理占用，也不因此新增正式日志扫描。单日启动/读取/核验/结果存储、所有阶段SQL/载入和内存限制的明细，见[LLD§11.9.14](dagster-etf-daily-data-onboarding-low-level-design-v1.md#11914-2026-10-23本步开发与隔离验收)及[验收汇总](/private/tmp/etf_completion_development_acceptance_20261023.json)。该样本使用临时文件和SQLite，不承诺正式PG和真实文件完全同耗时。

本轮正式读取与写入、源请求、正式任务/检查、sensor操作和重载均为0。本步代码与文档按管理员本次指令一并提交，其他任务改动不纳入。本步开发无待拍板设计。下一阶段是按原批准边界准备正式Plan与候选review；先确认已核验Basic内容可复用，丢失即停、重读另批。正式文件提升、事件及重载/最后正式验收仍各自独立，不把开发通过当成已补齐。

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
- 全区间审计使用一次或少量 DuckDB 聚合扫描，不逐日启动进程。
- 全历史 Raw 审计和 Raw manifest 重验按“数据集＋年份”批量读取；每组先统一核验各文件 schema，再只载入一次明细，复用临时表完成行数、主键、日期、hash、质量和覆盖统计。单文件 writer 与批量审计共享 hash 表达式和数值规则，禁止逐文件重跑整套审计。实现和性能回归要求见 LLD §16.5。
- 最终四资产物理验收也按“数据集＋年份”批量执行，不能恢复逐日深扫。复用 Raw 批量结构检查，再批量完成 Silver 结构、Basic 筛选、全部源字段双向对账、数值规则和 coverage；逐文件证据、checkpoint 对账及失败规则不变。每组固定 15 次 SQL，Raw 载入两次、Silver 一次（第二次 Raw 用于生成预期 Silver）；本次 406 日为 4 组、60 次 SQL，不含独立 Basic reference 验证。具体约束见 LLD §16.6。

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

开发状态：已完成（2026-09-02）；正式启用与结案记录见 P6。

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

状态：已完成（2026-09-02）。本阶段只使用固定 ETF Basic fixture 和临时目录验证，没有读取源端、写正式 Lake 或补 Dagster event。

- 复用 latest-only Basic selector/reference。
- 用 DuckDB 完成筛选、DATE cast、拒绝分类和候选写入。
- P3 初版每个 Silver 实现五个 blocking checks 与一个 coverage WARN check；2026-09-04 因子 coverage 已升级，当前日线为五个 blocking＋一个 WARN，因子为六个 blocking。
- Silver Catalog entries 与 Silver assets/checks/jobs 在同一切片原子落地。
- 明确验证 `change` 保留、`change_amount` 不存在、`discount_rate` 不被修正。

### P4：Jobs、Sensors 与 readiness

状态：已完成（2026-09-02）。

- 已复验 P2/P3 随各层落地的四个 layer-isolated jobs 的 Definitions 装载与选择范围；P4 没有重写 jobs。
- 已复用 P2 的两个单页发布探测，落地四个默认 `STOPPED` sensors 和批量 10 日 readiness。
- 已通过隔离测试验证 21:00 边界、最早缺口、已有坏文件阻断、Basic latest-only、稳定 run key、紧凑 cursor 和固定查询次数。
- 正常交易日 21:00 后的源端非空复验仍保留为正式启用前门禁；未通过不得启用。

### P5：Bootstrap 工具

状态：已完成（2026-09-03）。

- 实现 raw-plan、bounded-sample、raw-apply、包含 profile 的 raw-audit、silver-plan、silver-apply、physical-post-audit、events-plan、events-apply 和 events-post-audit 工具。
- Raw 与 Silver 分别冻结 plan/hash；每个文件完成后立即原子写 checkpoint；每批最多 20 日但不形成跨日事务。
- Raw audit 只把 latest ready Basic 用于 coverage 观察；Silver Plan 才冻结 Basic reference，并在 apply 前重新验证 latest-only fingerprint。
- 物理 post-audit 先闭合四资产文件、schema/key/date/hash/parity/domain、checkpoint 和 staging，再允许生成 event plan；materialization 覆盖全日期，blocking checks 只覆盖最近 20 日。
- 隔离 fake 验证最多 3 日，没有读取真实 Tushare、写正式 Lake、写正式 Dagster instance 或启用 Sensor；批次上限另以无数据写入的调度测试验证。
- 已覆盖停止/续跑、写文件后 checkpoint 前中断恢复、等价重放、目标与水位漂移、Basic/Raw manifest/policy/空间门禁、字段门禁、active run/事件冲突和幂等。ETF 日线定向测试与静态门禁合计 `245 passed`。

### P6：正式历史建设与启用

状态：已结案（2026-09-04）。下列记录按执行阶段保留；最终启用、首日验收及管理员结案决定见本节末尾。

2026-09-03 已完成的范围：

- operation：`etf-daily-20260903-p6-r2`；冻结 `2025-01-02..2026-09-03` 的 406 个共享 ETF 交易日。
- 三日隔离样本通过，随后正式新增 Raw 文件 812 个：`fund_daily` 724,654 行、`fund_adj` 735,975 行；合计 30,053,205 bytes。Raw apply 约 154.47 秒，无覆盖、无 staging 文件残留。
- 发现原全历史审计重复调用单文件检查后，已按批准范围改为数据集/年度批量读取，并保持单文件 hash 和数值规则不变。264 项 ETF 日线定向测试及静态门禁通过。
- 正式 Raw 审计通过：4 组、44 次批量 SQL、4 次 Raw 明细载入；核心审计 1,296.8 ms（不含 CLI 启动与报告序列化），各批结束时临时文件占用为 0。812 个文件的 schema/key/date/hash 与 checkpoint 对账通过；两个数据集均未命中已定义的数值异常规则。
- 按本次 latest ready Basic 观察，`fund_adj` 全部 406 日缺失为 0；`fund_daily` 有 166 日、共 310 个代码/日期缺口，单日最多 10 个，仍为已确认的 WARN。这里的 310 不是 310 个不同 ETF，也不能据此宣称日线全覆盖。Raw 中非当前 eligible ETF 的行继续保留。
- 证据目录：`/private/tmp/goldenshare-bootstrap/etf_daily/etf-daily-20260903-p6-r2/`，包含 `raw-plan.json`、`bounded-sample-audit.json`、`raw-apply-report.json`、`raw-apply-receipt.json`、`raw-audit.json`。Raw audit report hash：`caf22459d5514c6c43a015119186aab354683986357f44a9d099d19f771bdb2b`。
- 9 月 3 日停止于 coverage review，未写 Silver/事件、未启用 Sensor。9 月 4 日管理员确认因子缺码升级为阻断，日线仍告警；规则见 §8.3，编码与性能约束见 LLD §11.6。

2026-09-04 review 与执行边界：

- 再次核对 Raw manifest 与审计报告 hash 一致，已完成的 812 个 Raw 文件无需重拉或改写。
- 因子覆盖规则同步到 check 的 blocking/ERROR、Catalog 名单、readiness 和历史验收；事件补录必须有明确的因子 coverage 零缺口证据，不接受只有总 `passed=true` 的旧报告。
- 历史记录：06:57、07:10 和 08:28 预检被“Basic 观测日期必须等于执行自然日”的旧规则阻断，最新版本为 9 月 3 日晚间。这是新鲜度设计错误，不是已证明的 Basic 数据缺陷。管理员随后批准按实际每日 21:00 更新窗口修正，见 §5.2 和 LLD §16.2.1；不刷新 Basic，仍冻结原 Raw Plan 的 406 日，不自动扩到新增日期。
- coverage 升级验收：ETF 日线定向与静态门禁 279 项通过，Dagster Definitions 加载、Ruff、文档完整性检查通过；因子 coverage 的 2/10 日调用预算、缺码阻断、日线告警、失败不改文件及事件证据门禁均有回归。07:10 只读核验 Raw manifest 未变，Raw/Silver 字段完整继承；当时尚未生成 Silver Plan，没有写 Silver、补事件或启用 Sensor。

2026-09-04 08:50 正式 Silver Plan 已生成：

- 新鲜度修正仅修改 `etf_daily_bootstrap_cli._latest_basic`：复用现有 21:00 窗口和原 selector，不改 Basic 共用检查、日常链、分钟链或字段。CodeGraph explore/impact 确认影响限于该 CLI 的四个 Basic 消费分支；无 Prod/API/前端或子系统依赖变化。
- 隔离回归共 372 项通过（ETF 日线、ETF Basic、ETF 分钟 sensor 和静态门禁）；新增 20 个历史新鲜度测试场景。Ruff、`dg check defs`、文档完整性检查通过。
- 正式只读 Raw 复验：仍为 4 组、44 次 SQL、812 文件、1,460,629 行，核心耗时 1,327.492 ms；结构、checkpoint、已定义数值异常均为 0。因子缺码 0，日线 166 日共 310 个代码/日期缺口仍 WARN。
- 使用的最新 Basic：Raw 观测于 `2026-09-03T21:06:22.795212+08:00`，Silver 观测于 `2026-09-03T21:08:15.448445+08:00`，可请求 ETF 1,650 个；reference fingerprint 为 `5858fab6044298a6b37a9e09d6d66502b00333477d30eddb275b8f5f2faf96c1`。未手动刷新 Basic；审计和 Plan 使用同一 reference。
- Plan 保留原 `2025-01-02..2026-09-03` 的 406 日：`silver_etf_daily` 与 `silver_etf_adj_factor` 各 406 个目标，全部 missing，无目标文件冲突。按当前 Raw/Basic 预计筛选后分别为 539,226 / 539,536 行；这是预计值，不是已写入行数。
- 预计新文件空间上界 30,053,205 bytes，2.5 倍空间要求 75,133,013 bytes，实际可用 2,510,528,303,104 bytes；空间门禁通过。Raw manifest hash 仍为 `dcbae06225c2a029848b753c4bb6265ac44777ec12b4d807b3f8ebe3d0aedd8e`，未重拉或改写 Raw。
- 证据仍在原 operation 目录：`raw-audit-20260904-silver-preflight.json`（report hash `bfc53fef6694b7f6bc0755563ed6c1d40112bbb9152707175b8912d8ff10ce1d`）和 `silver-plan.json`（plan hash `2e0224254061157d86e9eb470a60a42522be9c0b45740fd4b284cecbecc69f95`）。Plan 的 `code_revision` 同时记录当前提交和本轮 CLI 工作区文件 SHA-256，不冒充已提交的代码版本。
- 该次 Plan 阶段源请求、正式 Lake 文件写入、Dagster event/分区/sensor 写入均为 0；当时全部 Silver 目标不存在。后续获批执行的结果见下段。

2026-09-04 Silver apply 与物理验收已完成：

- 管理员批准先补齐最终物理验收的批量实现，再继续已批准的 Silver apply。修正范围仅为 Bootstrap 验收读取模型及共用纯 SQL；删除逐日 `_audit_pair`，分类、hash、全字段双向 parity、数值和 coverage 规则不变，不增加配置或源请求。
- CodeGraph explore/impact 核验 Bootstrap、Silver writer、正式 check 和 readiness 的调用关系；分类和 hash 提取为同一纯 helper，未改变字段、API、前端、子系统边界或依赖矩阵。当时选定的 398 项定向/静态回归通过，新增批量测试逐项对照每文件证据，覆盖错误第二文件、同键改值、空/重复键、错位/空日期、零行 Silver；同年 2/20 日均固定 15 次 SQL。Ruff、Definitions 与文档完整性检查通过。该历史测试集合未包含两份全局资产治理测试，不能作为 Definitions、Catalog 与 Check governance 已完整对账的证据；事后修复见本节末尾和 §14.4。
- 复用原 Silver Plan `2e0224254061157d86e9eb470a60a42522be9c0b45740fd4b284cecbecc69f95`，启动时最新 Basic、Raw manifest、目标和空间门禁通过。正式新增 Silver 812 个文件，全部 `write_new`：日线 406 文件 / 539,226 行；复权因子 406 文件 / 539,536 行，范围仍为 `2025-01-02..2026-09-03`。Silver apply 126.821 秒，每文件 checkpoint 已保存，无自动覆盖。
- 最终只读物理验收通过：Raw/Silver 四资产各 406 文件，合计 1,624 文件；无缺文件、多余文件、checkpoint 差异或 staging Parquet 残留，结构/hash/筛选/parity/数值检查通过。因子缺码 0；日线仍有 166 日、310 个代码/日期缺口，按既定 WARN 保留，不能据此宣称日线全部覆盖。
- 性能实测为 4 组、60 次批量 SQL、Raw 明细载入 8 次、Silver 4 次；核心验收 2,953.390 ms（不含 CLI 启动与报告序列化），各组结束时临时文件占用为 0，不作为峰值证明。详见 LLD §16.6。
- 证据仍在原 operation 目录：`silver-apply-report.json`（hash `280467238a328eab9a1be79149dac1a9832f9da6f98791d82d7b3de22aa25657`）、`physical-post-audit.json`（hash `6866a60b107923a17897be598ee611c222b4a67a6051525c7b900c4187aba4b4`）及 `checkpoint.json`。本轮没有源请求、Raw 改写、Dagster 事件/动态分区写入或 Sensor 启用。
- 该阶段仅完成历史物理建设，当时尚未结案。之后的事件补录、Sensor 启用和结案结果见下文；不能用物理验收代替后续授权。

2026-09-04 11:10 正式事件补录 Plan 已生成（只读）：

- 复用原 operation `etf-daily-20260903-p6-r2`、原 Silver Plan 及已通过的物理报告，不重新拉取源数据、不生成 Parquet、不重新选择 Basic。按数据湖集成技能要求，事件登记与数据写入保持分阶段授权。
- 待补 materialization 共 1,624 条：四资产各 406 条，覆盖 `2025-01-02..2026-09-03`。它们表示已有文件的登记，不代表重新计算 1,624 次。
- 待补 blocking check 共 340 条，仅覆盖最近 20 个交易日 `2026-08-07..2026-09-03`：两个 Raw 各 60 条，日线 Silver 100 条，复权因子 Silver 120 条。日线 coverage WARN 不伪装为通过的 blocking check，已知缺口仍保留在物理报告中。
- 现有等价 materialization/check 均为 0，冲突均为 0；生成时全 instance 活动任务探测为 0，`should_stop=false`。这是 Plan 时点结果，后续 apply 仍按既有门禁重验，不等于已获得写入授权。
- 沿用已有批量 Plan 实现，无需改生产代码。按代码读取模型为 4 次 materialization 集合读取、17 次 check history 读取、1 次活动任务探测；各调用有上限，没有逐分区 readiness 深扫。实际 CLI 总耗时 1.51 秒（含启动、Plan 序列化和输出），未触发历史截断或冲突门禁；没有源请求、DuckDB 明细重扫、Lake/事件/动态分区/Sensor 写入。
- Plan：`/private/tmp/goldenshare-bootstrap/etf_daily/etf-daily-20260903-p6-r2/events-plan.json`；hash `fedd011810a665eec5e0c9e3be26f9fdae691251c5231c51800ad8fbe331536a`，绑定物理报告 hash `6866a60b107923a17897be598ee611c222b4a67a6051525c7b900c4187aba4b4`。读取回验 hash、范围和数量通过，事件模块隔离测试 `10 passed`；原 checkpoint 仍仅有 812 Raw + 812 Silver 条目，事件条目 0。
- 该 Plan 冻结的写入上限为 1,624 + 340 = 1,964 条事件，写入需要单独批准。事件阶段不改数据文件、不注册日期、不启用 Sensor；失败保留已有登记与 checkpoint，不做数据库级删除回滚。后续获批执行结果见下段。

2026-09-04 17:54 正式事件补录与写后验收已完成：

- 管理员明确批准上述 1,964 条记录后，复用原事件 Plan 和正式 CLI 执行，不修改生产代码、不重建 Plan、不重新同步数据。写前 Plan hash、物理报告、checkpoint 和无活动任务门禁通过；事件模块隔离测试再次 `10 passed`，包含两日期 8 条 materialization + 34 条 check 的真实临时 Dagster instance 写入、等价重放和读回验收。
- 正式新增 1,624 条 materialization，覆盖四资产各 406 个历史交易日；新增 340 条 blocking check，覆盖 `2026-08-07..2026-09-03` 最近 20 日。所有事件均为 `write_new`，没有冲突或失败。CLI 总耗时 137.15 秒，每条事件完成后保存 checkpoint；checkpoint 当前为 812 Raw + 812 Silver + 1,964 events，共 3,588 条。
- 写后聚合验收通过：1,624 条 materialization 的 metadata 与冻结文件证据一致，340 条 check 均为 blocking/passed 且绑定对应 materialization，失败数 0；CLI 总耗时 1.87 秒。未用全历史逐分区 readiness 深扫代替集合验收。
- 另按数据湖集成技能要求，只读抽查 `2026-08-07`、`2026-08-20`、`2026-09-03` 三日的四资产 readiness，共 12 个分区全部 ready；使用现有正式 helper，每资产一次 materialization 查询，共 4 次，核心耗时 1,282.948 ms。该抽样不改变日线历史 166 日、310 个代码/日期缺口的 WARN 结论，也不宣称全部历史日线无缺码。
- 本轮源请求、Lake 文件写入、动态分区注册、Sensor 启用均为 0；只新增正式 Dagster 事件及原 operation 目录中的执行/审计证据。没有影响 Prod 数据库、数据字段、路径、Definitions 或依赖边界。
- 证据仍在原 operation 目录：`events-apply-report.json`（hash `f86f577c80108d26289d39115ffc33c8e8bf3ff9c81f3287f6ffdef27d32d51a`）、`events-post-audit.json`（hash `9e83a3ab759b96432ccfb25e1328ed6fd9f02aae6addaa4a14abce55573d657a`）、`events-readiness-sample.json`（hash `549ff28c59a79b4c350f8c91e3289bf93a297201464e1fca91ef20934bf6f18b`）。只读抽样脚本保存在同目录 `audit_event_readiness_sample.py`，不进入生产定义。
- 17:54 时历史物理数据与 Dagster 记录已闭环，但当时尚未启用 Sensor，事件补录授权不包含启用。之后的独立启用与结案结果如下。

2026-09-04 日常启用、首日验收与结案：

- 21:15 只读预检通过：两个源接口当日已发布；共享分区 `cn_a_etf_mins_trade_days` 已包含 `2026-09-04`，共 407 个日期；最新 Basic Raw/Silver 分别观测于 21:01:15 / 21:10:52，可用 ETF 1,650 个，latest-only 与质量检查通过。四个 Sensor 均已加载且为 `STOPPED`；试算只选择当天，不追赶历史。
- 管理员明确批准“启动吧”后，21:18:53 开启两个 Raw Sensor；Raw 成功后，21:19:29 开启两个 Silver Sensor。四个 Sensor 均读回为 `RUNNING`，其它 Sensor 开关没有改变；未手动提交 job、重置 cursor 或补注册日期。

| 正式 Job（Sensor 名为 Job 名加 `_sensor`） | 9 月 4 日写入行数 | Run ID | 运行耗时 |
| --- | ---: | --- | ---: |
| `raw_fund_daily_update_job` | 2,114 | `5f34f959-2986-418f-8298-bb281348bc0f` | 1.208 秒 |
| `raw_fund_adj_update_job` | 2,145 | `93606563-6fa2-4618-9a05-5e9dce81df9c` | 1.165 秒 |
| `silver_etf_daily_update_job` | 1,650 | `96889564-5d74-4857-b73a-1df04a52f2d7` | 1.980 秒 |
| `silver_etf_adj_factor_update_job` | 1,650 | `554488e5-a96e-4b1e-be09-30ef9a41b9d7` | 1.739 秒 |

- 四个 run 均由对应正式 Sensor 触发且为 `SUCCESS`。仅新增当天 4 个 Parquet，共 149,983 bytes，全部为 `write_new`；日线 Raw 拉取 1 页，因子 Raw 拉取 2 页，无重试。原历史 Bootstrap 的 406 日范围、Plan 和 checkpoint 未扩展，也未重跑或覆盖历史文件。
- Silver 日线按既定规则筛除 464 行（459 行 Basic 无对应代码、4 行上市日期为空、1 行非场内后缀）；因子筛除 495 行（491 行 Basic 无对应代码、4 行上市日期为空）。这些源端行全部保留在 Raw，不是源数据丢失。
- 21:21 写后只读验收通过：4 个实际文件均 ready，18 项正式 check 全部 passed（17 项 blocking、1 项日线 coverage WARN 级检查），check 分区和 materialization 绑定正确。当天两个 Silver 的预期 ETF 缺码和多余代码均为 0；物理 readiness 合计 4 次 materialization 查询，整个验收耗时 923.840 ms。
- 证据仍在原 operation 目录：`sensor-preflight-20260904.json`（hash `19e5a2b5da366940d4914e1bb11522f04b01063aca4a7ab44e7484df1f27868d`）、`sensor-enable-20260904-raw-verified.json`、`sensor-enable-20260904-silver-verified.json`、`daily-first-run-audit-20260904.json`（hash `a63d176b42d23ed6bb8cdea3bfefd7e4c987557b87f54f3d96fdaeca57c21af7`）。
- 管理员在首日验收后明确要求“直接结案吧”：本需求及 P6 结案，不再以剩余两个交易日观察作为待办或阻断。实际只完成一个交易日的日常验收，不宣称已通过连续三个交易日验证。四个 Sensor 继续按上海时间 21:00 起的既定窗口运行，日常质量门禁不变。
- 已知边界继续保留：历史日线 166 日、310 个 ETF/日期缺口仍是已接受的 WARN，不因结案改成“历史全覆盖”。结案不授权自动修值、历史覆盖、新增 Gold 或 Prod 写入；本次不改代码、字段、路径或依赖矩阵。

2026-09-05 结案后治理修复：复查发现两个 Silver asset 已进入 Catalog 和正式 Definitions，但治理测试维护的 active Definitions 集合遗漏了 `silver_etf_daily`、`silver_etf_adj_factor`；四个 ETF 日线资产也未进入 `ASSET_CHECK_GOVERNANCE`。提交 `a5f995fa` 补齐两处登记，直接复用 `run_contracts.etf_daily` 的正式 check 常量；日线 coverage 仍为 WARN，因子 coverage 仍为 blocking。原 5 个失败全部消失，两份治理测试为 16 passed；按 §14.4 的固定扩大回归为 321 passed、609 个 subtests passed，修改文件 Ruff 通过。该修复只调整测试治理登记，没有修改 asset、check、job、sensor、数据文件或正式 Dagster 状态。

已执行的独立授权顺序与结案调整：

1. 正式 Raw Plan 与三日隔离样本；
2. Raw apply；
3. 全区间 Raw 审计和 `fund_adj` coverage review；
4. 必要时同步调整 coverage blocking 合同；
5. 正式 Silver Plan；
6. Silver apply；
7. 物理 post-audit；
8. events plan/apply/post-audit；
9. 启用四个 Sensor；
10. 首个交易日日常验收通过；管理员于 2026-09-04 取消剩余两日观察门槛，批准直接结案。

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

- 历史 Bootstrap 的四资产日期集合等于正式 Raw Plan 冻结的共享 ETF 分区集合，起点不早于 2025，终点不晚于冻结水位；Silver Plan 通过 Raw manifest 锁定同一集合。启用后的日常新增日期不回填到历史 Plan；本次新增 `2026-09-04` 由日常 run 独立记录。
- 每分区恰好一个可读 Parquet；schema、日期、主键、行数、内容 hash 和 source/Silver 对账全部通过。
- `source = normalized = Raw written`；`Silver selected + rejected = Raw`。
- 已存在文件只出现等价复用或显式冲突停止，没有静默覆盖。
- `fund_daily` coverage 差异产生 WARN；`fund_adj` 最终政策有全区间证据和明确 review 结论。

### 14.3 运行

- 四个 Sensor 初始均为 `STOPPED`，没有未经授权的自动运行。
- 21:00 前不做重检查；21:00 后每 tick 每 Sensor 最多一个 run。
- 日常只看最近 10 个交易日，不追赶 2025 历史。
- 最新 Basic 不 ready 时不回退旧版本。
- 正式启用前完成 21:00 后源端复验；启用后首个交易日的正式 Sensor 触发、Raw/Silver 文件、checks 和 metadata 验收通过。原连续三个交易日观察门槛已由管理员于 2026-09-04 明确取消，剩余两日未执行、不计为已通过；不改变日常运行门禁。

### 14.4 开发治理与固定回归

任何新增、删除或修改本资产族的 asset、Catalog entry、blocking check 或 Sensor readiness 时，都必须同时满足：四个 active asset 与 Catalog 精确对账；Catalog blocking checks 与正式 check specs 精确对账；四个资产全部进入 Check governance，且治理规则直接复用正式 run contract 常量，不复制 check 名称字符串。

固定回归必须从 `lake_console/orchestrator` 执行：

```bash
uv run python -m pytest -q \
  tests/test_etf_daily_*.py \
  tests/test_asset_governance_contracts.py \
  tests/test_asset_check_incremental_governance.py \
  tests/test_run_contract_static_gates.py
uv run ruff check --select E9,F63,F7,F82 src tests
uv run ruff check <本次新增和修改的 Python 文件>
```

只运行 `tests/test_etf_daily_*.py` 不构成治理验收完成。上述测试是隔离代码回归，不需要访问正式 Dagster instance、正式 Lake、数据库或 Tushare。

---

## 15. 已关闭的决策与日常维护边界

2026-09-04 管理员已确认：`fund_adj` 缺码检查升级为 blocking/ERROR，`fund_daily` 保持 WARN。完整证据为 406 日、539,536 个预期 ETF/日期组合、因子缺口为 0，详见 §8.3、§13 P6。

不再保留待选择的 WARN/blocking 口径。Silver Plan/apply、物理验收、事件补录及四个 Sensor 启用均已分阶段获批并完成，详情见 §13 P6。管理员已批准在首个交易日日常验收通过后结案，不再等待剩余两日观察。

后续由已启用的四个 Sensor 日常维护，继续遵守 Raw 保存源端事实、Silver 只筛场内 ETF、保留 `discount_rate`、最新 Basic 不合格不回退、坏文件不自动覆盖等规则。后续若需要历史修复或扩展范围，另行审计和授权，不复用本次结案作为写入许可。
