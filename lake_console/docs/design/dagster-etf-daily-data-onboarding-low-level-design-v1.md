# ETF 日线与复权因子 DG 数据湖接入 LLD v1

> 状态：设计已确认，P1—P5 开发已完成；P6 Raw/Silver 历史入湖、物理验收、事件补录及写后验收已完成；fund_adj coverage 为阻断、日线 coverage 为告警；Sensor 启用和日常运行验收尚未执行
> 更新日期：2026-09-04
> 上位方案：`dagster-etf-daily-data-onboarding-plan-v1.md`
> P0 证据：`dagster-etf-daily-data-onboarding-p0-audit-2026-09-02.md`
> 开发目录：`lake_console/orchestrator`

---

## 1. 设计目标与硬口径

本 LLD 是后续 P1—P6 的直接编码依据。若现实代码、源接口或正式数据与本文冲突，必须先停止并回到技术方案 review，不能自行加兼容或临时开关。

### 1.1 必须

1. 新增 `raw_tushare_fund_daily`、`silver_etf_daily`、`raw_tushare_fund_adj`、`silver_etf_adj_factor` 四个资产。
2. Raw 直接按 `trade_date` 请求 Tushare 并保存全部返回；Raw 与 ETF Basic 无依赖。
3. Silver 读取执行时冻结的最新 ready `silver_etf_basic`，只筛 `.SH/.SZ` 现行上市 ETF，并把 `trade_date` 转为 `DATE`。
4. `fund_daily` Raw/Silver 都使用 11 个源字段，保留 `change`，禁止出现 `change_amount`。
5. `fund_adj` Raw/Silver 都使用 4 个源字段，显式包含 `discount_rate`。
6. 四个资产复用 `cn_a_etf_mins_trade_days`，Bootstrap 起点为 2025 年第一个已注册日期。
7. staging 只写 `/Volumes/datasource/data_lake_staging`，正式文件只写 `/Volumes/datasource/data_lake`。
8. 新文件原子提升；已有等价文件复用；内容冲突立即停止且不覆盖。
9. 所有生产 DuckDB 连接来自 `DuckDBResource`，所有 Parquet schema 读取显式 `hive_partitioning=false`。
10. 四个 Sensor 默认 `STOPPED`，窗口从上海时间 21:00 开始，每 tick 每 Sensor 最多一个 run。

### 1.2 禁止

- 禁止从 Prod DB、旧 Lake Root 或 `lake_console/backend` 读取这两个数据集。
- 禁止修改 `_fetch_all_pages` 或用它实现新资产。
- 禁止新增分页框架、Tushare client、数据库表、状态表或配置项。
- 禁止在 Raw 请求或写入前按 Basic、后缀或代码池删行。
- 禁止在 Silver 中改字段名、补值、修值、裁剪 `discount_rate` 或生成派生行情。
- 禁止把 `fund_daily` 与 `fund_adj` 的 Raw 代码集合强制对齐。
- 禁止让 Sensor 追赶 2025 年以来全历史。
- 禁止使用 Kopia、跨历史大事务、跨日全量 DataFrame 或并发 Tushare 请求。
- 禁止在隔离性能测试中同步全量历史，或构造无意义的超大满页 fake 数据。

### 1.3 决策状态

字段、日期、路径、资产名、Job/Sensor 名、21:00 窗口、Raw/Silver 边界、Basic latest-only、分页 limit、请求预算、价格容差、20 日批次和 2.5 倍空间系数都已冻结。

2026-09-04 后置 review 已关闭：`fund_adj` coverage 升级 blocking/ERROR，`fund_daily` 保持 WARN。当前固定合同与编码要求见 §11.6，不再保留运行时可选策略。

---

## 2. 当前代码复用与明确不复用

### 2.1 直接复用

| 当前能力 | 位置 | 本需求用途 |
| --- | --- | --- |
| `TushareResource` / `DuckDBResource` | `defs/resources.py` | 显式 fields 与统一 DuckDB 连接 |
| `execute_bounded_pages` / `TushareRequestPolicy` | `defs/tushare_request_policy.py` | 有界 offset 分页、重试、限速、跨页去重 |
| ETF Basic latest selector | `defs/asset_guards/etf_basic_readiness.py` | Silver 冻结最新 ready Basic |
| `EtfBasicSilverSnapshotReference` | `defs/run_contracts/etf_basic.py` | Basic 精确身份 |
| `classify_etf_basic_requestability` | 同上 | 复用现行 ETF serving 筛选语义 |
| `cn_a_etf_mins_trade_days` | `defs/partitions.py` | 四资产共享交易日 |
| metadata/tags/cursor/run-key builders | `defs/run_contracts/**` | 现有治理合同 |
| idx factor Raw/Silver writer 结构 | `defs/io/idx_factor_pro_*_writer.py` | page-bounded staging、候选校验、原子提升参考 |
| ETF mins batch readiness 结构 | `defs/asset_guards/etf_mins_lake_readiness.py` | 最近 10 日批量 readiness 参考 |
| idx factor Bootstrap 结构 | `defs/bootstrap/idx_factor_pro_bootstrap_*` | Plan/checkpoint/promotion/events 参考 |

### 2.2 不复用

1. 不复用 `fetch_tushare_partition_to_raw(...)`：它内部使用无请求次数/时间预算的 `_fetch_all_pages`，并把整日全部行累积在 Python 列表。
2. 不修改 `execute_bounded_pages(...)`：CodeGraph 显示改动会影响至少 24 个符号；新资产只传入自己的小预算策略。
3. 不复用股票 `daily/adj_factor` 的对象池与日期集合。
4. 不复用 ETF mins 的 Prod coverage reference；本需求 Raw 来源是 Tushare，且 Raw 不绑定 Basic。
5. 不复制 ETF mins 五频 N3A/N3B、零行文件和历史网格审计。

---

## 3. 最终 Definition 与 Catalog 名称

### 3.1 Asset、Job、Sensor

| Asset key | dataset_id | 中文名 | Job | Sensor |
| --- | --- | --- | --- | --- |
| `raw_tushare_fund_daily` | `fund_daily` | 基金日线行情 | `raw_fund_daily_update_job` | `raw_fund_daily_update_job_sensor` |
| `silver_etf_daily` | `etf_daily` | ETF 日线行情 | `silver_etf_daily_update_job` | `silver_etf_daily_update_job_sensor` |
| `raw_tushare_fund_adj` | `fund_adj` | 基金复权因子 | `raw_fund_adj_update_job` | `raw_fund_adj_update_job_sensor` |
| `silver_etf_adj_factor` | `etf_adj_factor` | ETF 复权因子 | `silver_etf_adj_factor_update_job` | `silver_etf_adj_factor_update_job_sensor` |

四个资产都使用 `group_name="quote"` 和 `DataDomain.QUOTE_DATA`。Job 名遵守“layer + asset family + mode + job”，不重复 Raw asset 的源系统限定词。

### 3.2 Check

```text
raw_tushare_fund_daily_source_contract_check
raw_tushare_fund_daily_partition_scope_check
raw_tushare_fund_daily_key_integrity_check
raw_tushare_fund_adj_source_contract_check
raw_tushare_fund_adj_partition_scope_check
raw_tushare_fund_adj_key_integrity_check

silver_etf_daily_contract_check
silver_etf_daily_source_filter_check
silver_etf_daily_source_parity_check
silver_etf_daily_key_integrity_check
silver_etf_daily_bar_domain_check
silver_etf_daily_basic_coverage_check          # blocking=False

silver_etf_adj_factor_contract_check
silver_etf_adj_factor_source_filter_check
silver_etf_adj_factor_source_parity_check
silver_etf_adj_factor_key_integrity_check
silver_etf_adj_factor_domain_check
silver_etf_adj_factor_basic_coverage_check     # blocking=True, severity=ERROR
```

Catalog 的 `blocking_check_names` 包含因子 coverage，不包含日线 coverage WARN。

---

## 4. 文件级改动清单

### 4.1 新增生产文件

| 文件 | 责任 |
| --- | --- |
| `defs/run_contracts/etf_daily.py` | 字段、类型、名称、请求、策略、阈值、拒绝码和纯合同 |
| `defs/io/etf_daily_raw_writer.py` | 两个 Raw 的分页、候选、审计、等价复用和原子提升 |
| `defs/io/etf_daily_silver_writer.py` | 两个 Silver 的 Basic 筛选、DATE cast、候选与原子提升 |
| `defs/assets/etf_daily.py` | 四个 asset definitions 和 materialization metadata |
| `defs/checks/etf_daily_checks.py` | 17 个 blocking checks 与 1 个日线 coverage WARN check |
| `defs/asset_guards/etf_daily_lake_readiness.py` | 最近 10 日 Raw/Silver 批量 readiness |
| `defs/asset_guards/etf_daily_source_probe.py` | 两接口 offset=0 非空发布探测 |
| `defs/jobs/etf_daily.py` | 四个单层 asset jobs |
| `defs/sensors/etf_daily_sensor.py` | 四个 stopped-by-default sensors |
| `defs/bootstrap/etf_daily_bootstrap_plan.py` | 分别生成 Raw Plan 与 Silver Plan，冻结各阶段边界、路径、空间与 hash |
| `defs/bootstrap/etf_daily_bootstrap_apply.py` | bounded sample、Raw/Silver apply 与 checkpoint |
| `defs/bootstrap/etf_daily_bootstrap_audit.py` | 全区间物理/coverage/profile/post-audit |
| `defs/bootstrap/etf_daily_raw_batch_audit.py` | 数据集/年度 Raw 结构、hash、质量和 coverage 批量审计 |
| `defs/bootstrap/etf_daily_physical_batch_audit.py` | 数据集/年度 Raw/Silver 物理验收，保持逐文件证据 |
| `defs/bootstrap/etf_daily_bootstrap_events.py` | runless event plan/apply/post-audit |
| `defs/bootstrap/etf_daily_bootstrap_cli.py` | 受控命令入口和阶段确认参数 |

### 4.2 修改生产文件

| 文件 | 修改 |
| --- | --- |
| `defs/run_contracts/asset_column_schemas.py` | 增加四套 schema |
| `defs/paths.py` | 增加四个正式 path helper 和四个 staging helper |
| `defs/catalog/name_mapping.py` | 增加四个 dataset_id 中文名 |
| `defs/catalog/lake_assets.py` | 增加四个 PartitionModel、definitions 和 catalog entries |
| `defs/sensors/etf_mins_partition_sensor.py` | 只把说明改成“ETF 行情共享交易日”，不改 Definition 名称或行为 |

### 4.3 明确不修改

```text
defs/partitions.py
defs/resources.py
defs/tushare_request_policy.py
defs/tushare_api_io.py
任何 src/foundation DatasetDefinition / DatasetExecutionPlan
任何 Prod DB、ClickHouse 或前端代码
```

Definitions 使用现有 `load_from_defs_folder(...)` 自动发现，不新增手写聚合表。

---

## 5. Run contract

### 5.1 常量

`defs/run_contracts/etf_daily.py` 冻结：

```python
FUND_DAILY_API_NAME = "fund_daily"
FUND_ADJ_API_NAME = "fund_adj"
FUND_DAILY_PAGE_LIMIT = 5_000
FUND_ADJ_PAGE_LIMIT = 2_000

ETF_DAILY_SENSOR_WINDOW_LIMIT = 10
ETF_DAILY_BOOTSTRAP_START_DATE = date(2025, 1, 1)
ETF_DAILY_BOOTSTRAP_BATCH_DAYS = 20
ETF_DAILY_BOOTSTRAP_CHECK_EVENT_TAIL_DAYS = 20
ETF_DAILY_DISK_SAFETY_FACTOR = Decimal("2.5")
ETF_DAILY_AUTOMATION_CONTRACT_REVISION = "v1"
ETF_DAILY_CHANGE_TOLERANCE = 1e-6
ETF_DAILY_PCT_CHG_TOLERANCE = 0.01
ETF_DAILY_DIAGNOSTIC_SAMPLE_LIMIT = 20
```

业务常量不得通过 env、Launchpad 或 Sensor cursor 覆盖。

### 5.2 字段与类型

```python
FUND_DAILY_SOURCE_COLUMNS = (
    "ts_code", "trade_date", "pre_close", "open", "high", "low",
    "close", "change", "pct_chg", "vol", "amount",
)
FUND_ADJ_SOURCE_COLUMNS = (
    "ts_code", "trade_date", "adj_factor", "discount_rate",
)
```

Raw 的 `ts_code/trade_date` 为 `VARCHAR`，其余为可空 `DOUBLE`。Silver 字段集合和顺序完全相同，只把 `trade_date` 改为 `DATE`。类型映射使用 `MappingProxyType`。

### 5.3 日期、offset 与请求

```python
def normalize_etf_daily_trade_date(value: str | date) -> str:
    """严格返回 YYYY-MM-DD；拒绝 datetime、非补零日期和非法日期。"""

def _validated_offset(offset: int, *, page_limit: int) -> int:
    """要求非负整数且是 page_limit 的整数倍。"""

@dataclass(frozen=True, slots=True)
class EtfDailySourceRequest:
    api_name: str
    params: Mapping[str, object]
    fields: tuple[str, ...]

def build_fund_daily_request(partition_key, offset) -> EtfDailySourceRequest: ...
def build_fund_adj_request(partition_key, offset) -> EtfDailySourceRequest: ...
```

params 精确为：

```python
{
    "trade_date": normalized_date.replace("-", ""),
    "limit": PAGE_LIMIT,
    "offset": validated_offset,
}
```

不接受 `ts_code`、`start_date`、`end_date` 或额外业务参数。

### 5.4 请求策略

```python
FUND_DAILY_REQUEST_POLICY = TushareRequestPolicy(
    minimum_interval_seconds=0.13,
    max_retries=1,
    max_requests=2,
    max_elapsed_seconds=30.0,
)
FUND_ADJ_REQUEST_POLICY = TushareRequestPolicy(
    minimum_interval_seconds=0.13,
    max_retries=1,
    max_requests=4,
    max_elapsed_seconds=30.0,
)
```

其余 backoff 沿用当前默认值。`max_requests` 包含重试；结果只要 `ready=False` 就不得生成或提升候选。

### 5.5 拒绝码

```text
NON_EXCHANGE_SUFFIX
BASIC_CODE_ABSENT
EXCHANGE_MISMATCH
STATUS_NOT_LISTED
LIST_DATE_NULL
LIST_DATE_AFTER_TRADE_DATE
```

分类纯函数输入一行 Raw、一行可选 Basic 和 `trade_date`，输出一个 reason 或 `None`。它要与 `classify_etf_basic_requestability` 的现行语义做单测对账，禁止复制漂移。

---

## 6. Asset schema contract

在 `asset_column_schemas.py` 新增：

```text
RAW_TUSHARE_FUND_DAILY_SCHEMA
SILVER_ETF_DAILY_SCHEMA
RAW_TUSHARE_FUND_ADJ_SCHEMA
SILVER_ETF_ADJ_FACTOR_SCHEMA
```

`fund_daily` 逐列为 `ts_code,trade_date,pre_close,open,high,low,close,change,pct_chg,vol,amount`。`fund_adj` 逐列为 `ts_code,trade_date,adj_factor,discount_rate`。

Raw `trade_date` 为 `VARCHAR`，Silver 为 `DATE`；其余字段名、顺序和类型不变。静态测试必须断言：`change` 存在，四个新 schema、SQL 投影和 metadata 中都没有 `change_amount`；`discount_rate` 在 Raw/Silver 中都存在且 nullable。

---

## 7. Path 与 Catalog

### 7.1 Path helpers

`defs/paths.py` 新增：

```python
raw_fund_daily_path(root, partition_key)
silver_etf_daily_path(root, partition_key)
raw_fund_adj_path(root, partition_key)
silver_etf_adj_factor_path(root, partition_key)
```

分别返回：

```text
raw/tushare/fund_daily/trade_date={date}/part-000.parquet
silver/quote/etf_daily/trade_date={date}/part-000.parquet
raw/tushare/fund_adj/trade_date={date}/part-000.parquet
silver/quote/etf_adj_factor/trade_date={date}/part-000.parquet
```

再增加四个公开 staging helper，按 `staging_root/etf_daily/operation_id=<id>/<asset_key>/trade_date=<date>/part-000.parquet` 返回。内部可共享私有函数，但公开 API 不接受任意 layer/asset 字符串。所有参数严格归一化并拒绝路径穿越。

### 7.2 PartitionModel 与 entries

新增：

```text
TRADE_DATE_PARTITION_RAW_FUND_DAILY
TRADE_DATE_PARTITION_SILVER_ETF_DAILY
TRADE_DATE_PARTITION_RAW_FUND_ADJ
TRADE_DATE_PARTITION_SILVER_ETF_ADJ_FACTOR
```

四者 family 都是 `TRADE_DATE_PARTITION`、维度 `trade_date`、布局 `PARTITION_FILE`。

Raw entries：`SourceSystem.TUSHARE`、`TUSHARE_RAW_CONTRACT`、日常和 Bootstrap 都是 `TUSHARE_API`、`PARTITION_FILE_ATOMIC_REPLACE`、`SUPPORTS_RUNLESS_EVENT_BACKFILL`、`compute_engine=TUSHARE_RESOURCE`、`python_row_loop_allowed=False`。

Silver entries：`SourceSystem.DERIVED`、`DERIVED_CONTRACT`、来源 `DERIVED_FROM_ASSETS`、`compute_engine=DUCKDB_SQL`，其余写入/event/batch 口径与 Raw 对齐。

source docs 固定为：

```text
docs/sources/tushare/ETF专题/0127_ETF日线行情.md
docs/sources/tushare/ETF专题/0199_基金复权因子.md
```

---

## 8. Raw writer

### 8.1 公开 API 与结果

`defs/io/etf_daily_raw_writer.py` 只暴露：

```python
def write_fund_daily_raw_partition(
    *, lake_root_path: Path, staging_root_path: Path,
    duckdb_resource: DuckDBResource, tushare: TushareResource,
    partition_key: str, operation_id: str,
) -> EtfDailyRawWriteResult: ...

def write_fund_adj_raw_partition(...) -> EtfDailyRawWriteResult: ...
```

私有 `_write_etf_daily_raw_partition(spec=...)` 只接受模块内冻结的两个 spec，不变成任意 API/任意 schema 的通用搬运器。

结果至少含 asset/partition、target/staging、`write_new|reuse_existing`、source/normalized/written 行数、page/request/retry、elapsed、content hash 和文件字节。

### 8.2 预检

1. Lake/staging 根必须存在、同文件系统；
2. partition 与 operation id 合法；
3. 同 operation staging 残留直接停止；
4. 正式父目录可创建；
5. 不因正式目标已存在就直接返回，必须拉当前候选判定等价或冲突。

### 8.3 page-bounded 累积

在一个 `DuckDBResource.connect()` 中创建固定 schema 临时表。`execute_bounded_pages(...)` 使用：

```python
page_size=PAGE_LIMIT
policy=FUND_*_REQUEST_POLICY
scope=f"{api_name}:{partition_key}"
row_key=lambda row: (row.get("ts_code"), row.get("trade_date"))
retain_rows=False
consume_page=consume_page
```

`request_page(offset)` 只调用对应 request builder 与 `tushare.call(...)`。`extract_rows` 对非空结果要求 columns 精确；空结果最终由整分区非空门禁阻断。

`consume_page` 只创建当前页 DataFrame，注册到 DuckDB，显式 CAST，检查 key/date 后 `INSERT ... SELECT` 到 accumulator，随后注销 relation 并释放页面。禁止跨日或跨页保留 Python 行列表。

### 8.4 候选、审计与提升

分页只有 `ready=True` 且累计行数大于 0 才能：

```sql
COPY (
  SELECT <frozen columns>
  FROM accumulator
  ORDER BY ts_code, trade_date
) TO '<staging>' (FORMAT PARQUET, COMPRESSION ZSTD);
```

Raw SQL 禁止 Basic join 或后缀过滤。

纯审计函数：

```python
audit_etf_daily_raw_relation(
    connection, *, relation_sql, spec, partition_key,
    expected_source_row_count=None,
) -> EtfDailyRawAudit
```

输出字段/类型/行数、空 key、重复 key、错误日期、内容 hash、错误码和最多 20 个样本。writer 与 checks 共用它。

内容 hash 对按 key 排序、按冻结字段顺序编码的完整 relation 做 SHA-256，不使用 Parquet 字节 hash。测试证明行物理顺序不同但值相同 hash 相同，任一字段/null/行数变化 hash 改变。

提升规则：

```text
target missing -> os.replace -> write_new
target exists -> 审计 schema/row/hash + 双向 EXCEPT ALL
  等价 -> 删除 staging -> reuse_existing
  不等价或不可读 -> 删除 staging -> conflict error，正式文件不变
```

---

## 9. Silver writer

### 9.1 公开 API

```python
write_etf_daily_silver_partition(
    *, lake_root_path, staging_root_path, duckdb_resource,
    partition_key, operation_id,
    basic_reference: EtfBasicSilverSnapshotReference,
) -> EtfDailySilverWriteResult

write_etf_adj_factor_silver_partition(...) -> EtfDailySilverWriteResult
```

结果至少含 target/staging/write mode、Raw/selected/rejected/written 行数、reason counts、Basic fingerprint/hash/URI、content hash、文件字节和有界样本。

### 9.2 Basic reference

日常 Silver asset 在调用 writer 前用上海当前日期调用：

```python
select_latest_etf_basic_snapshot_reference(
    instance=context.instance,
    lake_root_path=lake_root.root(),
    duckdb_resource=duckdb,
    eligibility_as_of=now.date(),
    required_freshness_date=now.date(),
)
```

writer 要求 reference 合同有效且 URI 对应正式 path。日常不把 reference 暴露为运营输入。历史链的 Raw Plan 和 Raw apply 不选择、不冻结、不验证 Basic；Raw 全量完成并通过审计后，Silver Plan 才冻结一次 reference。Silver apply 每次启动重新选择 latest 并要求 fingerprint 与 Silver Plan 完全一致，writer 不自行换版本。

### 9.3 分类与投影

Silver 一次打开同分区 Raw 与 `basic_reference.silver_uri`。分类优先级为：非 `.SH/.SZ`、Basic absent、exchange mismatch、非 L、list_date null、list_date 晚于行情日，最后才 selected。实现要与 `classify_etf_basic_requestability` fixture 对账。

`silver_etf_daily` 投影严格为：

```sql
SELECT
  r.ts_code,
  strptime(r.trade_date, '%Y%m%d')::DATE AS trade_date,
  r.pre_close, r.open, r.high, r.low, r.close,
  r.change, r.pct_chg, r.vol, r.amount
FROM classified r
WHERE rejection_reason IS NULL
ORDER BY r.ts_code, r.trade_date
```

`silver_etf_adj_factor` 投影严格为：

```sql
SELECT
  r.ts_code,
  strptime(r.trade_date, '%Y%m%d')::DATE AS trade_date,
  r.adj_factor,
  r.discount_rate
FROM classified r
WHERE rejection_reason IS NULL
ORDER BY r.ts_code, r.trade_date
```

禁止 `COALESCE`、`ROUND`、`ABS`、clamp、去重或字段别名变化。

### 9.4 候选 validator 与提升

候选提升前只检查文件可读、schema、日期、主键、Basic 身份、`selected+rejected=raw`、与同一 selected SQL 双向等价。价格/OHLC/复权因子/coverage 留给正式 checks。

提升规则与 Raw 相同；不能覆盖由旧 Basic 生成且内容不同的历史正式文件。

---

## 10. Asset definitions

`defs/assets/etf_daily.py` 定义四个 assets。Raw 函数参数为 context、lake_root、duckdb、tushare；Silver 为 context、lake_root、duckdb，并用 `deps=[同分区 Raw, silver_etf_basic]` 声明 lineage，不通过 IO manager 传 DataFrame。

Asset 函数只做 root preflight、调用 writer、结构化日志和 `MaterializeResult`，不复制 SQL。

Definition metadata 固定登记 dataset/source/contract/schema/path/source API/doc/partition set。Materialization metadata 通过统一 builder，Raw 记录 API、脱敏 params、fields、limit、page/request/retry、source/normalized/written、hash、size、write mode；Silver 再记录 Raw/selected/rejected、reason counts 和 Basic reference fingerprint/hash/URI。

metadata 不写 token、完整代码清单、完整行样本、未命名空间 key 或 `change_amount`。

---

## 11. Asset checks

### 11.1 共享审计结果

checks 不重新实现 writer 逻辑。Raw checks 调用 `audit_etf_daily_raw_relation`；Silver checks 调用 `audit_etf_daily_silver_relation` 和 `audit_etf_daily_source_parity`。所有 check metadata 使用 `build_check_metadata(...)`，包含 scope、路径、检查行数、失败数、最多 20 个样本、结论和下一步。

### 11.2 Raw checks

| Check | blocking | 判断 |
| --- | --- | --- |
| `*_source_contract_check` | 是 | 文件可读、字段/类型顺序精确，materialization 中 source/normalized/written 行数一致 |
| `*_partition_scope_check` | 是 | 行数大于 0，文件内日期全部等于分区 |
| `*_key_integrity_check` | 是 | `ts_code/trade_date` 非空且联合主键唯一 |

Raw check 不读取 ETF Basic，不按代码后缀判污染，也不比较两个 Raw 的代码集合。

### 11.3 Silver contract/filter/parity/key checks

| Check | blocking | 判断 |
| --- | --- | --- |
| `*_contract_check` | 是 | 文件可读、字段/类型/顺序精确，日期等于分区 |
| `*_source_filter_check` | 是 | Basic reference 可复算；输出每行符合 suffix/exchange/status/list_date |
| `*_source_parity_check` | 是 | 输出与 Raw + frozen Basic + DATE cast 双向等价；selected+rejected=raw |
| `*_key_integrity_check` | 是 | `ts_code/trade_date` 非空唯一 |

check 必须读取当前 Silver materialization metadata 中的 Basic reference，不能再次选择“此刻最新”的另一版 Basic，否则 check 与产出会错绑。

### 11.4 `silver_etf_daily_bar_domain_check`

一条聚合 SQL 统计：

```text
null_or_nonfinite_price_count
non_positive_price_count
ohlc_relation_failure_count
null_or_nonfinite_volume_count
negative_volume_count
change_formula_failure_count
pct_chg_formula_failure_count
```

公式：

```text
abs(change - (close - pre_close)) <= 1e-6
abs(pct_chg - (close - pre_close) / pre_close * 100) <= 0.01
```

只在 `pre_close > 0` 且参与字段有限时判断公式；前置无效值由对应计数单独失败，避免除零或 NaN 掩盖。

### 11.5 `silver_etf_adj_factor_domain_check`

统计：

```text
adj_factor_null_count
adj_factor_nonfinite_count
adj_factor_non_positive_count
discount_rate_nonfinite_count  # null 不计失败
```

禁止新增 `discount_rate` 的最大/最小阻断阈值。

### 11.6 Coverage：日线 WARN、因子 blocking

两个 coverage checks 都输出 expected、Raw matching、Silver、missing、extra 数量和有界样本。

- `silver_etf_daily_basic_coverage_check(blocking=False)` 固定为 WARN。
- `silver_etf_adj_factor_basic_coverage_check(blocking=True)`：2026-09-04 已批准升级，失败级别为 ERROR。`missing_expected_code_count > 0` 或 `silver_extra_code_count > 0` 失败；不能计算 coverage 时也失败。`raw_extra_code_count` 不参与失败。
- `ETF_DAILY_COVERAGE_POLICY_REVISION = "fund_daily_warn__fund_adj_blocking_v2"`；因子 coverage 加入 `SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS`，Catalog 引用同一名单。check factory 直接使用该名单，禁止再追加 coverage 导致重复注册。
- `EtfDailyCoverageAudit.error_codes` 统一缺码/多余 Silver 代码的失败事实，日常 check、因子 readiness、Bootstrap 物理验收共用。日线仍只告警。事件补录只有通过当前因子 coverage 验收后才能记录成功。
- 不改 Raw/Silver 字段、写入原子性或 source filter，不在 writer 内补值/删行/回滚；阻断的是可用性和验收。

本次升级的性能与验收约束：

| 环节 | 数量与读写边界 | 验收与拒绝策略 |
| --- | --- | --- |
| 日常 readiness | 最多 10 日；因子每日期复用现有 coverage evaluator 的 2 次 SQL，最多增加 20 次；日线不增加。Basic 仍按 reference 缓存校验，沿用统一 DuckDB 内存/spill 配置 | 每资产仍最多 1 次 materialization 查询；因子缺码或不能计算立即不 ready；2/10 日调用预算回归 |
| 历史物理验收 | 已有 coverage 结果直接参与失败判断，新增扫描/源请求/文件写入为 0 | 缺码不能通过验收，不能据此补绿色事件；日线缺码仍 WARN |
| 本轮真实复验与 Plan | 原范围 406 日、812 个 Raw 文件、约 30 MB；manifest 仍按 4 组批量重验。Tushare 请求 0、正式 Lake/事件写入 0；仅允许输出 Plan/审计报告 | 已有基线批量 Raw 审计约 1.3 秒；按秒级轻量只读操作执行。Basic 按 §16.2.1 更新窗口判断，失败不回退、不手动刷新；保留原日期范围，空间与冲突继续使用既有 Plan 门禁 |

定向反例必须覆盖：因子缺一个代码失败、完整通过、Raw 额外代码不失败、缺覆盖证据 fail-closed、日线同类缺码仍仅告警，以及事件名单不重复和旧 WARN policy Plan 被拒绝。

2026-09-04 coverage 升级验收记录：ETF 日线定向与静态门禁共 279 项通过；`dg check defs`、Ruff、文档完整性检查通过。2/10 日因子 readiness 分别执行 4/20 次新增 coverage SQL，每资产仍只有一次 materialization 查询；缺码时不 ready，检查前后文件内容不变。07:10 正式只读复验 812 个 Raw 文件、1,460,629 行 manifest 未变，字段继承不变；当时因错误的“执行自然日必须更新”规则停止在 Silver Plan 之前。该历史阻断不代表 Basic 数据有问题，现行新鲜度口径以 §16.2.1 为准。

---

## 12. Readiness

### 12.1 状态模型

`defs/asset_guards/etf_daily_lake_readiness.py` 定义：

```python
@dataclass(frozen=True, slots=True)
class EtfDailyPartitionReadiness:
    asset_key: str
    trade_date: str
    ready: bool
    materialized: bool
    file_exists: bool
    checks_passed: bool
    reason_code: str
    row_count: int | None
    content_hash: str | None

@dataclass(frozen=True, slots=True)
class EtfDailyBatchReadiness:
    asset_key: str
    statuses: tuple[EtfDailyPartitionReadiness, ...]
    materialization_query_count: int
    elapsed_ms: int
```

### 12.2 批量算法

输入最多 10 个日期，一次完成：

1. 对目标 asset 一次批量读取这些 partition 的最新 materialization evidence；禁止每日期一次 event 查询。
2. 用一个 DuckDB 连接检查目标文件存在性、schema、日期、主键和数据集 blocking 规则。
3. 要求 materialization URI、row count、content hash 与物理文件一致。
4. 已有 materialization/文件但 blocking 规则失败，返回 `materialized_check_failed`，Sensor 不得自动覆盖。
5. 日线 coverage WARN 不参与 `ready`；因子复用 `audit_etf_daily_basic_coverage`，其 `error_codes` 必须计入失败，不能计算时 fail-closed。只使用 materialization 已冻结的 Basic，不在 readiness 改绑此刻最新版本。

Raw Sensor 每 tick 只加载目标 Raw；Silver Sensor 加载同分区 Raw 与目标 Silver。每个 asset 最多一次 lineage 查询，禁止加载完整历史 check event。

---

## 13. Source publication probe

`defs/asset_guards/etf_daily_source_probe.py` 只判断“当天已经开始发布”，不判断完整覆盖。

```python
@dataclass(frozen=True, slots=True)
class EtfDailySourcePublication:
    api_name: str
    trade_date: str
    ready: bool
    reason_code: str
    row_count: int
    observed_columns: tuple[str, ...]
    elapsed_ms: float

def probe_fund_daily_publication(tushare, trade_date): ...
def probe_fund_adj_publication(tushare, trade_date): ...
```

各自只调用 request builder 的 `offset=0` 一次，并验证返回非空、columns 精确、页内 key 非空唯一、所有 `trade_date` 等于目标日。

它不请求第二页、不写文件、不比较 Basic coverage，也不把 `fund_adj` 的满 2,000 行第一页当完整分区。异常转为 fail-closed status，下一次 Sensor tick 可以重新探测。

---

## 14. Jobs

四个 Job 都采用：

```python
dg.define_asset_job(
    name=...,
    selection=(
        dg.AssetSelection.assets(target_asset)
        | dg.AssetSelection.checks_for_assets(target_asset)
    ),
    partitions_def=cn_a_etf_mins_trade_days,
    executor_def=dg.in_process_executor,
)
```

每个 Job 只选一个 asset 与其 checks。Raw Job 不包含 Silver；Silver Job 不重新 materialize Raw/Basic。Job 文件禁止调用 writer、source probe、DuckDB 或 path helper。

---

## 15. Sensors

### 15.1 窗口与公共 evaluator

输入时间先归一化为 `Asia/Shanghai`；日常窗口判断为 `local_time >= 21:00`。21:00 前直接 skip，且 DuckDB/Tushare 调用数都必须是 0。

`etf_daily_sensor.py` 可以用私有 frozen spec 共享流程，但保留四个公开 evaluator 和四个 Definition，便于独立测试与 UI 识别。

Raw evaluator：

```text
21:00 前 skip
-> 从交易日历加载最近 10 个 expected ETF 行情日期
-> 校验这些日期已注册到共享 partition set
-> 批量检查目标 Raw readiness
-> all ready: skip
-> 现有文件/check 失败: fail-closed skip
-> 选最早缺失日期
-> offset=0 publication probe
-> 未发布: skip，不产生 run key
-> 已发布: 返回一个 RunRequest
```

Silver evaluator：

```text
21:00 前 skip
-> 同一最近 10 日窗口与注册状态
-> 批量检查 Raw + Silver
-> 最早日期 Raw 不 ready: stop，不越过
-> Silver 已有坏文件: stop
-> 选择最早 Silver 缺失日期
-> select_latest_etf_basic_snapshot_reference(now.date)
-> Basic 不 ready: fail-closed skip
-> 返回一个 RunRequest
```

Silver Sensor 只用 selector 预防无效 run；Silver asset 运行开始时仍再次选择最新 Basic，保护 Launchpad/CLI 手工运行。两次调用间如 Basic 更新，asset 使用执行开始时的新 latest 并记录 metadata，不能回退旧版。

### 15.2 Run key

```python
build_asset_update_run_key(
    subject=JOB_NAME,
    unit_id=f"{trade_date}:{ETF_DAILY_AUTOMATION_CONTRACT_REVISION}",
)
```

publication probe 先于 run key，避免“尚未发布”的失败 run 永久占用当日稳定 key。Job 真正失败后由运营在 Dagster Run 页面人工 retry；Sensor 不创建第二个同语义 run key。

### 15.3 Cursor 与 Definition 属性

统一 `build_sensor_cursor(...)` 和 `build_cursor_details(...)`。details 只放 sensor/job/asset family/partition set、reason、blocked component、summary、next action、最早缺口、Raw/Silver/Basic/publication 摘要、window limit、contract revision、查询次数和耗时。

四个 Sensor 均：

```text
default_status = STOPPED
minimum_interval_seconds = 600
role = ASSET_UPDATE
domain = QUOTE_DATA
target_layer = RAW / SILVER
```

Raw required resources 为 `lake_root, duckdb, tushare`；Silver 为 `lake_root, duckdb`。现有 `etf_mins_trade_day_sensor` 继续唯一注册共享日期，新需求不增加分区 Sensor。

---

## 16. Direct Lake Bootstrap

### 16.1 CLI 与阶段

唯一入口：

```bash
uv run python -m orchestrator.defs.bootstrap.etf_daily_bootstrap_cli <command> ...
```

命令固定为：

```text
raw-plan
bounded-sample
raw-apply
raw-audit
silver-plan
silver-apply
physical-post-audit
events-plan
events-apply
events-post-audit
```

正式命令显式传 plan/report/checkpoint 绝对路径与阶段确认参数。确认参数只防误操作，不改变业务合同。Raw Plan、Raw apply、Silver Plan、Silver apply、events apply 分别审批。

### 16.2 Raw Plan 与 Silver Plan payload

```python
@dataclass(frozen=True, slots=True)
class EtfDailyBootstrapSourceContract:
    api_name: Literal["fund_daily", "fund_adj"]
    fields: tuple[str, ...]
    page_limit: int
    request_policy_hash: str


@dataclass(frozen=True, slots=True)
class EtfDailyBootstrapTarget:
    asset_key: str
    trade_date: str
    target_path: str
    observed_state: Literal[
        "missing", "existing_structurally_ready", "existing_invalid"
    ]
    observed_row_count: int | None
    observed_content_hash: str | None
    observed_size_bytes: int | None


@dataclass(frozen=True, slots=True)
class EtfDailyRawManifestEntry:
    asset_key: Literal["raw_tushare_fund_daily", "raw_tushare_fund_adj"]
    trade_date: str
    target_path: str
    row_count: int
    content_hash: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class EtfDailyRawBootstrapPlan:
    schema_version: str
    operation_id: str
    created_at: str
    code_revision: str
    contract_revision: str
    watermark: str
    trade_dates: tuple[str, ...]
    trade_dates_hash: str
    source_contracts: tuple[EtfDailyBootstrapSourceContract, ...]
    raw_targets: tuple[EtfDailyBootstrapTarget, ...]
    estimated_new_bytes: int
    required_free_bytes: int
    observed_free_bytes: int
    raw_plan_hash: str


@dataclass(frozen=True, slots=True)
class EtfDailySilverBootstrapPlan:
    schema_version: str
    operation_id: str
    created_at: str
    code_revision: str
    contract_revision: str
    parent_raw_plan_hash: str
    raw_manifest: tuple[EtfDailyRawManifestEntry, ...]
    raw_manifest_hash: str
    coverage_policy_revision: str
    basic_reference: EtfBasicSilverSnapshotReference
    silver_targets: tuple[EtfDailyBootstrapTarget, ...]
    estimated_new_bytes: int
    required_free_bytes: int
    observed_free_bytes: int
    silver_plan_hash: str
```

日期只来自正式 Dagster instance 的 `cn_a_etf_mins_trade_days`，过滤 `>=2025-01-01` 且 `<=max(registered)` 后排序。空集合、重复、非法日期或水位漂移都失败。

Raw Plan 中每个 Raw `asset + trade_date` 目标只记录 `missing / existing_structurally_ready / existing_invalid`。Raw Plan 不调用全历史 Tushare，因此不能提前写“内容等价”；等价在 Raw apply 拉到候选后判断。Raw Plan payload 中不得出现 Basic reference 或 Silver 目标。

Raw 全量完成、Raw audit 通过且 `fund_adj` coverage review 关闭后才允许生成 Silver Plan。`raw_manifest` 必须逐项冻结两个 Raw asset 的日期、正式路径、行数和内容 hash；Silver Plan 同时冻结该 manifest 的 hash、已确认的 coverage policy revision、生成时 latest ready Basic reference，以及两个 Silver asset 的目标状态。Silver Plan 不重新请求 Tushare。

两个 plan hash 都对去掉自身 hash 字段后的规范化 JSON 做 SHA-256。Raw apply 只接受 Raw Plan；Silver apply 只接受 Silver Plan，并验证 `parent_raw_plan_hash` 和 `raw_manifest_hash`。Basic 漂移只作废 Silver Plan，不能作废、删除或重写已经完成的 Raw。

#### 16.2.1 历史入口 Basic 新鲜度修正（2026-09-04 已批准）

`etf_daily_bootstrap_cli._latest_basic` 不再把执行自然日直接当作必须更新日期。复用 `etf_mins.etf_sensor_window_is_open` 的既有每日上海时间 21:00 窗口：

1. 21:00 前，最新 Raw Basic 的真实观测日期必须在昨日与今日之间；21:00 起必须为今日。未来时刻、缺失/非法/无时区观测时间或过旧版本一律停止。Basic 本身每天运行，因此这里不引入交易日历或新配置项。
2. 只以 `fetch_materializations(..., limit=1)` 读取最新 Raw 的观测日期。随后以该日期同时作为 `eligibility_as_of` 和 `required_freshness_date` 调用原 selector；原 selector、日常 asset/sensor、ETF 分钟链不改。
3. 原 selector 继续验证最新 Raw/Silver 的 blocking checks、物理文件、内容 hash、URI 和两层绑定。不得遇错再尝试昨日、不得向历史搜索 ready 版本；返回 reference 的 Raw hash/观测时间必须仍与首次读取一致，否则停止。
4. reference 的资格日期与快照观测日期绑定，单纯跨零点不会改变 fingerprint；真正更新 Basic 后仍按原 fingerprint 漂移门禁停止 Silver apply。行情分区筛选继续按 `list_date <= trade_date`，不变更历史资格 SQL。
5. 适用于现有四个 Basic 消费入口：bounded sample、Raw audit、Silver Plan、Silver apply；Raw Plan/apply 仍不依赖 Basic。不给 CLI 新增手填日期、忽略新鲜度或自动刷新参数。

本轮执行与性能约束：

| 项目 | 上限、验证与读写边界 |
| --- | --- |
| Basic 读取 | 每次选择比原流程增加 1 次 `limit=1` 的 Raw materialization 读取；原 selector 的 2 次 materialization 和各 check 最新一条查询不变，无历史深扫 |
| Raw 复验 | 原 406 日、812 文件、1,460,629 行、约 30 MB，按资产/年 4 组聚合；沿用 44 次 SQL 的 Raw audit 与 20 次 SQL 的 manifest 复验模型，预计秒级；超过 60 秒停止检查读取模型 |
| 写入和配额 | 源请求 0，正式 Lake 文件写入 0，Dagster event/分区/sensor 写入 0；只生成 `/private/tmp` 下不可变审计报告和 Silver Plan，沿用 2.5 倍磁盘空间检查 |
| 正反例 | 早晨/跨零点/20:59:59 使用昨晚版本；当天提前更新使用最新版本；21:00 旧版拒绝；缺时间/无时区/未来/过旧/最新检查失败/两层不一致/选择期间变化拒绝；不回退、不改文件，旧的日常当天门禁仍有效 |

先通过隔离测试，再正式只读复验，生成原日期范围的 Silver Plan 后停止。此阶段不授权 Silver apply 或 Basic 更新。

验收结果：2026-09-04 新增的 20 个历史新鲜度场景及 ETF 日线/Basic/分钟 sensor/静态门禁合计 372 项通过；Ruff、Definitions 加载、文档检查通过。正式 Raw 复验 1,327.492 ms，Basic 仍为 9 月 3 日晚的最新合格版本，原 manifest 未变。08:50 已生成 406 日、812 个全新目标的 Silver Plan，hash 为 `2e0224254061157d86e9eb470a60a42522be9c0b45740fd4b284cecbecc69f95`；读回验证通过，未执行 Silver apply。完整证据与数量见技术方案 §13 P6。

### 16.3 空间与 bounded sample

按 P0 文件大小基线估算 Raw，Silver 不高于 Raw，并计入 manifest/report/checkpoint：

```text
required_free_bytes = ceil(estimated_new_bytes * 2.5)
```

空间不足直接拒绝，不降低系数、不换不同文件系统 staging、不引入 Kopia。

`bounded-sample` 只允许 Raw Plan 的首、中、尾最多 3 个日期；先生成两个 Raw 候选，再使用一次隔离冻结的 latest Basic 生成两个 Silver 候选，每日期最多四个候选。输出到 operation staging，不提升正式 Lake、不写 event。验证请求、行数、Basic、schema、文件大小、耗时、RSS、spill、`change` 和 `discount_rate`。样本用 Basic 只是验证 Silver 编码路径，不能写回 Raw Plan，也不能成为正式 Silver apply 的 reference。

### 16.4 Checkpoint

```python
@dataclass(frozen=True, slots=True)
class EtfDailyBootstrapCheckpointEntry:
    phase_plan_hash: str
    phase: Literal["raw", "silver", "events"]
    asset_key: str
    trade_date: str
    target_path: str
    content_hash: str
    row_count: int
    write_mode: str
    completed_at: str
```

checkpoint 使用同目录临时文件 + `os.replace()` 原子更新。每完成一个文件立即落盘；20 日 batch 不是事务。Raw entry 的 `phase_plan_hash` 必须等于 Raw Plan hash，Silver entry 必须等于 Silver Plan hash，events entry 必须等于 event plan hash。续跑逐条核验正式文件 schema/hash/row count，不能只信 checkpoint 文本。

事件阶段仍使用同一个 checkpoint 结构。materialization 的 `target_path` 写为 `dagster://materialization/<asset>`；check 的 `target_path` 写为 `dagster://asset-check/<asset>/<check>`，从而在不增加临时字段的前提下区分同一资产、同一日期的多个 blocking checks。

### 16.5 Raw apply 与 audit

- 每批最多 20 日，日期升序；同日先 `fund_daily` 后 `fund_adj`。
- 每个文件调用与日常 asset 相同的公开 Raw writer。
- 单分区失败立即停止；已完成文件/checkpoint 保留。
- Raw apply 不选择 Basic、不写 Silver、不发 event。
- Raw apply preflight 只验证 Raw Plan、冻结日期、Raw 目标状态和空间；Basic 更新、失败或缺失均不得阻断。

Raw audit 用一次或少量 DuckDB 扫描完成日期矩阵、文件/行数/schema/key/date/hash、source/write 守恒、日线/因子质量观察。随后用 review 时 latest ready Basic 计算每日 expected/present/missing/extra；这份 Basic 只服务 coverage 观察，不追溯绑定 Raw，也不改变 Raw 审计结论。报告明确两个 Raw 不要求同代码集合。

批量读取实现固定如下（2026-09-03 修正）：

1. `bootstrap/etf_daily_raw_batch_audit.py` 按 `asset + year` 组织冻结文件清单；Python 只遍历文件路径与分区级汇总，不处理业务明细。
2. 每组先用一次 `parquet_schema` 检查所有文件的字段名、顺序和类型，再用一次 `read_parquet(..., hive_partitioning=false)` 将明细装入连接内临时表；缺文件、坏 schema、空分区、空/重复主键、日期错位继续阻断，不允许批量类型合并掩盖坏文件。
3. 按文件归组计算行数、主键、日期、内容 hash；hash 与单文件 writer 共用同一 SQL 表达式，不改变既有 checkpoint/manifest identity。
4. Raw audit 复用该组扫描结果生成 manifest 和结构证据，并在同一临时表上完成质量与 Basic coverage profile。数值规则与正式单分区检查共用纯 SQL predicates；失败样本每分区最多 20 条。
5. `build_raw_manifest` 使用同一个批量入口但不读取 Basic、不计算质量/coverage；因此 Raw audit、Silver Plan 与 Silver apply 的 Raw manifest 重验不会恢复逐文件深扫。日常 writer/check/sensor 不改变读取模型。
6. 报告记录 batch 数、Raw 文件数/行数/字节、批量 SQL 次数、明细载入次数、耗时及批次结束时临时文件占用。隔离测试对照单文件结果，并证明同年日期从 2 增至 20 时查询次数不增长；跨年只按组数增长。

本次正式范围为 406 日、812 个 Raw 文件、1,460,629 行、30,053,205 bytes，形成 4 组；历史审计不调用 Tushare、不写 Lake/事件，只输出审计报告。复用统一 DuckDB 连接及其内存/spill 配置，每组结束释放临时表。先验证隔离样本与查询次数，再运行正式只读审计；出现错误即停，不降级检查、不重拉 Raw。

本次性能与验收对账：

| 项目 | 执行口径与结果 |
| --- | --- |
| 读取量 | 2 个资产 × 2 年，共 812 文件、1,460,629 行；每组一次 footer schema 检查、一次 Raw 明细载入 |
| SQL 上限模型 | 每组结构审计 5 次；带质量/coverage 为 11 次（含临时表清理），本次共 44 次，不含独立 Basic reference 验证查询 |
| 计算与内存 | 在 DuckDB 临时表上聚合、join、按文件算 hash；Python 只接收分区汇总与每分区至多 20 条样本，每组结束释放临时表 |
| 写入与配额 | Tushare 请求 0、Lake 写入 0、Dagster 事件 0；只写 `/private/tmp` 下不可变报告，无业务事务或文件提升 |
| 真实性能 | 核心审计 1,296.8 ms；4 组均在批次结束时观测到临时文件占用 0（不是过程 spill 峰值证明） |
| 拒绝策略 | 缺文件/坏 schema/key/date/空分区立即停止；checkpoint hash/行数漂移不通过；不得跳过坏文件或改变数值规则；本次未触发 |
| 隔离门禁 | 同年 2 日与 20 日查询次数相同；异常第二文件、hash 金样本、单文件语义对照、每日期样本上限、manifest 不重复扫描均有测试；ETF 定向及静态门禁共 264 passed |

2026-09-03 全区间审计结果：结构与 checkpoint 差异均为 0，两个 Raw 数据集的已定义数值异常计数均为 0；`fund_adj` 406 日 coverage 缺失为 0，`fund_daily` 166 日共 310 个代码/日期缺口，维持 WARN。2026-09-04 管理员据此确认因子 coverage 升级 blocking；执行报告和当前停止点见技术方案 §13 P6。审计通过不自动授权 Silver apply 或事件阶段。

coverage review 已关闭，Silver Plan 必须使用 `fund_daily_warn__fund_adj_blocking_v2`；旧 WARN policy Plan 拒绝。正式历史入口按 §16.2.1 要求最新 Basic 在更新窗口内合格；过期或检查失败时停止，不触发 Basic 更新、不回退、不伪造观测日期。以合格的最新 Basic 只读复验 coverage，再生成原 406 日的 Plan，不重拉 Raw。

### 16.6 Silver apply 与物理对账

- 启动时验证 Silver Plan、父 Raw Plan hash 和 Raw manifest；重新选择 latest ready Basic，要求 fingerprint 等于 Silver Plan；变化只作废旧 Silver Plan。
- 每批最多 20 日，每文件调用同一 Silver writer。
- 每份结果记录同一 Basic reference。
- conflict、Raw manifest 漂移、Basic 漂移或 coverage policy revision 不一致立即停止。

Physical post-audit 要求四资产日期集合等于 frozen list、文件数为 `4 * date_count`、无多余日期/文件、schema/keys/date/hash/Silver parity 全通过、候选目录无未解释残留。因子 coverage 的 error_codes 计入分区失败；日线同类差异只保留 coverage_warning。报告逐 Silver 文件记录 `coverage_error_codes`、`missing_expected_code_count`、`silver_extra_code_count`，并明确 `dagster_events_written=0`。

最终物理验收批量实现（2026-09-04 补齐）：

1. `run_physical_post_audit` 按现有 `etf_daily_raw_batches` 分成数据集/年度组，调用 `etf_daily_physical_batch_audit.audit_etf_daily_physical_batch`；删除逐日期 `_audit_pair` 路径。文件集合、checkpoint、staging 残留检查仍在外层，最终仍输出每个文件的证据，不把组级通过当成文件级证明。
2. 每组先复用 §16.5 的 Raw 结构/hash 批量检查（5 次 SQL），再用一次 `parquet_schema` 检查每份 Silver 的字段顺序和物理类型。禁止 `union_by_name` 或 Hive 自动补字段掩盖坏文件。
3. 将该组 Raw 与 Silver 各批量载入一份连接内临时表，保留由文件路径确定的分区日期。复用 writer 的分类 SQL、Silver hash 表达式和数值谓词；按文件分区聚合行数、主键、日期、hash、筛选失败和数值失败。Raw 仍保存全部事实，不受 Basic 筛选。
4. 批量计算 Raw 的选入数、拒绝数及各拒绝原因；以同一冻结 Basic 生成预期 Silver，针对“文件分区日期＋全部源字段”做双向 `EXCEPT ALL`，保留重复行敏感性，不能用总行数或主键集合代替逐值对账，也不能让错误日期文件相互抵消。
5. coverage 从冻结日期表展开 Basic 的预期代码，再与各文件实际 Silver 代码做差集；即使 Silver 文件为零行，也必须保留该日期的缺码判断。因子缺码/多余代码阻断，日线同类差异告警。筛选、数值、parity 等错误仍阻断；不修值、不改正式文件。
6. 每组固定 15 次 SQL（含结构、聚合、临时表清理和临时文件占用查询），其中 Raw 两次明细载入、Silver 一次：第一次 Raw 复用结构检查，第二次生成预期 Silver，不另造通用缓存框架。本次 406 日、812 个 Raw 文件约 30 MB、812 个 Silver 文件预计约 30 MB 以内，4 组共 60 次 SQL；独立 Basic reference 验证不计入此预算。无源请求、无 Lake/事件写入，只输出报告；复用统一 DuckDB 内存/spill 配置，逐组释放临时表，Python 只接收分区级摘要。
7. 报告增加批次数、SQL 次数、Raw/Silver 明细载入次数、文件数/字节、耗时、批次结束时临时文件占用（不冒充峰值）。隔离测试逐项对照单文件检查；同年 2 日和 20 日查询次数必须一致，并覆盖坏的第二文件、同键改值、重复键、错位日期、零行 Silver 和因子/日线不同的 coverage 结论。通过后再执行已批准的正式 Silver apply 和该只读验收；事件与 Sensor 仍需后续独立授权。

### 16.7 Events

`events-plan` 读取已通过且 hash 有效的物理报告，复用其中逐文件证据，不再重扫正式 Parquet；只读 Dagster instance，冻结四资产 materialization 缺口、最近 20 日 blocking check 缺口、已有事件 identity、active run 探测和 event plan hash。活动任务探测 `limit=1`，只表示有无活动任务，不是完整活动任务总量。

因子每日期包含六个 blocking check，coverage 只注册一次；最近 20 日全新事件上限为 `20 * (3 + 3 + 5 + 6) = 340` 个 check event。生成事件 Plan 必须拒绝旧 WARN policy，以及缺少明确 coverage 零缺口证据或因子 coverage 失败的物理报告，不能仅相信总 `passed=true`。

`events-apply` 要求 active run 为 0；materialization 全日期补齐，checks 只补最近 20 日，逐事件 checkpoint。已有等价事件跳过，非等价停止。事件阶段不改 Lake、不注册新分区、不启用 Sensor。

2026-09-04 11:10 正式只读验收：`events-plan.json` 已生成，hash 为 `fedd011810a665eec5e0c9e3be26f9fdae691251c5231c51800ad8fbe331536a`，沿用原 operation、Silver Plan 和物理报告。待补 1,624 条 materialization、340 条 blocking check，已有与冲突均为 0，活动任务探测为 0，`should_stop=false`。Check 日期为 `2026-08-07..2026-09-03` 共 20 日；分资产数量为 60/60/100/120。代码模型为 4 + 17 + 1 次有界批量 API 读取，实际 CLI 总耗时 1.51 秒；没有源请求、Parquet 深扫或正式写入。10 项事件模块隔离测试和 Plan hash/范围读回校验通过。该时点仅完成 Plan；正式写入结果见下段，不得把 Plan 本身当作已完成登记的证据。

2026-09-04 17:54 获批执行验收：原 Plan 的 1,624 条 materialization 和 340 条 blocking check 全部新增完成，CLI 耗时 137.15 秒；逐事件 checkpoint 共 1,964 条。`events-post-audit` 按资产/check 集合读回核对，失败 0，CLI 耗时 1.87 秒。再抽查 `2026-08-07/2026-08-20/2026-09-03` 三日、四资产，共 12 个分区全部 ready；正式 readiness helper 合计 4 次 materialization 查询，核心耗时 1,282.948 ms。10 项事件隔离测试再次通过，包含临时 Dagster instance 的两日写入/重放/验收；没有重新同步源数据、改湖文件、注册日期或启用 Sensor。执行报告、聚合验收、抽样验收及其 hash 统一记录在技术方案 §13 P6。历史补录已闭环，但这不替代后续 21:00 发布验证、Sensor 启用和连续三个交易日验收。

---

## 17. 日志与人类可读说明

每个 asset 至少输出：

```text
source_fetch_started / silver_build_started
source_pages_completed / silver_classification_completed
candidate_validated
partition_promoted_or_reused
```

禁止每行日志。异常文字先给结论，再给分区、数量、路径、差异和下一步。Asset、Job、Sensor、Check description 必须说人话，不能只拼变量名或阶段编号。

---

## 18. 测试设计

### 18.1 新增测试文件

```text
tests/test_etf_daily_contracts.py
tests/test_etf_daily_paths.py
tests/test_etf_daily_catalog.py
tests/test_etf_daily_raw_writer.py
tests/test_etf_daily_silver_writer.py
tests/test_etf_daily_raw_checks.py
tests/test_etf_daily_silver_checks.py
tests/test_etf_daily_lake_readiness.py
tests/test_etf_daily_source_probe.py
tests/test_etf_daily_jobs.py
tests/test_etf_daily_sensors.py
tests/test_etf_daily_bootstrap.py
tests/test_etf_daily_raw_batch_audit.py
tests/test_etf_daily_physical_batch_audit.py
tests/test_etf_daily_bootstrap_events.py
tests/test_etf_daily_definitions.py
```

### 18.2 合同正反例

- 合法/非法日期，offset 非整数、负数、非 limit 倍数；
- request params/fields 精确，无 `ts_code/start_date/end_date`；
- `fund_daily` 11 字段且 `change` 保留；新范围静态扫描无 `change_amount`；
- `fund_adj` 4 字段且显式 `discount_rate`；
- Raw/Silver 只有 `trade_date` 类型不同；
- 四个 path 正确，旧 Lake Root、Kopia、路径穿越被拒绝；
- Catalog/Definition/schema/path/check/job/sensor 名全量对账。

### 18.3 Raw writer

- 一页短页、新文件写入；
- `fund_adj` 两页 `2000 + short` 合并，跨页 key 唯一；
- `158008.OF` 原样进入 Raw；
- columns 漂移、错误日期、空 key、跨页重复、零行、request budget exceeded 均不提升；
- target 等价复用且 mtime 不变；冲突停止且正式内容不变；
- staging 与 Lake 不同文件系统时拒绝；异常不删其他正式文件。

分页预算测试不构造 10,000/20,000 行 fake 页面：通用满页/预算语义由现有 `test_tushare_request_policy.py` 负责；本文件模拟 `BoundedPageRequestResult(ready=False, budget_exceeded=True)`，证明 writer 不提升。

### 18.4 Silver writer

- `.SH/.SZ` + exchange + L + `list_date<=trade_date` 正向；
- `.OF`、Basic absent、exchange mismatch、D/P、null list_date、晚于分区分别得到固定 reason；
- `selected + rejected = raw`；
- 所有数值逐项等于 Raw，只转换日期；
- `change` 保留，`change_amount` 不存在；
- `discount_rate` 的 null、负数和 9940.7 原样保留；
- Basic path/hash/fingerprint 漂移失败，最新失败不回退旧版本；
- 旧 Basic 产物与新候选冲突时不覆盖。

### 18.5 Checks

每个 check 至少一组通过和一组单一失败 fixture。公式 expected 写字面量，不调用被测 helper 生成：

- 日线价格 null/NaN/inf/非正、OHLC、负 vol/amount、change/pct 边界；
- adj_factor null/NaN/inf/0/负数；
- discount_rate null/负数/极端有限值通过，NaN/inf 失败；
- 日线缺码 check 返回 `passed=False/severity=WARN`，但不阻断 readiness；因子缺码为 `passed=False/severity=ERROR`，且 readiness 和历史物理验收失败。完整因子和 Raw 额外代码为正例；覆盖不能计算必须失败。检查不改写任何数据文件。

### 18.6 Sensor/readiness

- 20:59:59 skip 且 DuckDB/Tushare 为 0；21:00:00 进入评估；
- 最近 10 日、最早缺口、all ready、分区未注册；
- existing bad file 阻断且不发 run；
- publication 未发布时无 run key，下个 tick 可再 probe；
- probe 只 1 请求，Raw job 才做完整分页；
- Silver Raw 未 ready 不越过，最新 Basic 失败 fail-closed；
- 每 tick 最多一个 RunRequest，稳定 run key 正确；
- cursor reason/blocked component/summary/next action 和长度预算；
- batch lineage 查询 Raw ≤1、Silver ≤2，不随 10 日线性增长。

### 18.7 Bootstrap 与静态门禁

- Raw Plan 只读，从共享分区过滤 2025+ 并冻结动态水位、Raw 目标路径和空间，不含 Basic/Silver 目标；
- Raw Plan/date hash、Raw 目标路径、空间 2.5 倍；
- Raw Plan 不调用全历史 Tushare、不提前标等价；
- Silver Plan 只在 Raw audit 和 coverage review 关闭后生成，冻结父 Raw Plan、Raw manifest、coverage policy、Basic fingerprint、Silver 目标和空间；
- Basic 或 Raw manifest 漂移只作废 Silver Plan，不回滚 Raw；
- bounded sample 最多 3 日且不提升、不发 event；
- 20 日 batch、按阶段 plan hash 的逐文件 checkpoint、停止/续跑、文件漂移；
- Raw/Silver/events 权限边界；fund_adj policy 未 review 时 Silver 拒绝；
- materialization 全量、checks 最近 20 日；事件失败不回滚 Lake。

扩展 static gates：新 assets 全在 Catalog；schema/path/checks 对账；无直接 `duckdb.connect()`、旧 Lake Root、Kopia、Prod DB、`_fetch_all_pages`、`change_amount`；Sensors 默认 STOPPED；Raw 不 import ETF Basic；Job 文件不含 Tushare/DuckDB/SQL/path；Definitions 加载 4 assets、18 checks、4 jobs、4 sensors且无同名冲突。

---

## 19. 开发与验证顺序

### P1：纯合同与共享结构

状态：已完成（2026-09-02）。

先写 run contract、schema、path、PartitionModel、中文名与静态测试；不增加 active Catalog entry，也不创建 contract-only 临时例外。

### P2：Raw

状态：已完成（2026-09-02）。隔离 fake/临时目录测试和 `2026-09-01` 两接口最小真实样本均通过；真实样本仅写 `/private/tmp`，未写正式 Lake 或 Dagster event。验收证据见 `dagster-etf-daily-data-onboarding-p2-real-sample-2026-09-02.md`。

先 writer/audit，再把 Raw Catalog entries、assets、checks、jobs 同一切片落地，最后 source probe。隔离 fake 通过后，另行申请最多一个日期、两个接口的真实临时目录验证，不写正式 Lake。

### P3：Silver

状态：已完成（2026-09-02）。仅以固定 ETF Basic fixture 和临时目录完成纯分类、DuckDB SQL、候选提升、资产检查与 Definitions 装载验证；未读取 Tushare、写正式 Lake 或补 Dagster event。

先纯分类和 SQL fixture，再把 Silver Catalog entries、writer、checks、assets、jobs 同一切片落地。固定 Basic fixture 下 source parity 为零，`change`/`discount_rate` 门禁通过。

### P4：Readiness 与 Sensor

开发状态：已完成（2026-09-02）；启用验收待授权。先通过最多 10 日的批量 readiness 性能测试，再落四个 evaluator 和四个默认 `STOPPED` 的 Definition。Raw 每个资产最多一次 materialization 查询，Silver 合计最多两次；已有坏文件或坏证据 fail-closed，Coverage WARN 不阻断。隔离测试覆盖 20:59:59 零访问、21:00 入窗、最近 10 日、最早缺口、已有坏文件、发布未就绪、latest-only Basic、稳定 run key、紧凑 cursor、查询预算和 Definitions 自动发现。正常交易日 21:00 后的源端只读发布复验仍是启用门禁；未经授权不启用。

上述为 P4 初版验收记录；当前因子 coverage 已按 §11.6 升级为阻断，只有日线 coverage 保持 WARN。9 月 3 日 22:29 的源端非空复验已经通过（详见技术方案 §3.4），但不代表每天 21:00 准点发布，也不代替 Sensor 启用批准。

### P5：Bootstrap 工具

状态：已完成（2026-09-03）。

已按 raw-plan -> bounded-sample -> raw-apply -> raw-audit（包含 profile）-> silver-plan -> silver-apply -> physical-post-audit -> events-plan -> events-apply -> events-post-audit 落地五个 Bootstrap 模块和独立 CLI。隔离 fake/临时目录验证最多 3 日；没有请求真实 Tushare、写正式 Lake、写正式 Dagster instance 或运行全量。

隔离验收覆盖：Raw 中途停止后从逐文件 checkpoint 续跑、文件已原子提升但 checkpoint 尚未落盘时通过公开 writer 重新证明等价后续跑、未完成目标与水位漂移 fail-closed、Raw audit 与 manifest 闭合、coverage review/policy 门禁、Silver Basic fingerprint 漂移拒绝、四资产物理对账、20 日 batch 调度上限、全日期 materialization、最近 20 日 blocking checks、已有等价事件复用、active run/内容冲突停止、事件重放与 post-audit。bounded sample 同时记录请求/行数、耗时、峰值 RSS、DuckDB spill、文件大小以及 `change`/`discount_rate` 字段门禁。

### P6：正式执行

当前已完成正式 Raw Plan、三日隔离样本、812 个 Raw 文件入湖、全区间批量审计、正式 Silver Plan、812 个 Silver 文件入湖及最终物理验收。2026-09-04 coverage 已拍板：因子阻断、日线告警；代码与验收要求见 §11.6。历史入口新鲜度与最终批量验收分别按 §16.2.1、§16.6 修正并通过回归。日线 Silver 为 539,226 行，因子为 539,536 行；物理验收 4 组、60 次 SQL、核心耗时 2,953.390 ms，1,624 个文件及 checkpoint 全部对账通过。因子缺码 0，日线 166 日共 310 个代码/日期缺口仍 WARN。398 项定向/静态测试、Ruff、Definitions 和文档完整性检查通过；完整执行记录及报告 hash 见技术方案 §13 P6。随后 §16.7 的事件 Plan、1,964 条正式事件补录、聚合写后验收和三日 readiness 抽样均完成，历史数据与登记记录已闭环。尚未启用 Sensor；下一步为启用前 21:00 发布验证、获批启用四个 Sensor 和连续三个交易日日常验收，P6 尚未结案。

严格按技术方案的独立授权链。每阶段交付 report/hash/checkpoint，用户确认后才能继续。

---

## 20. 验证命令

开发期从 `lake_console/orchestrator` 使用 `uv run python -m pytest -q tests/test_etf_daily_*.py` 运行定向测试，并执行：

```bash
uv run python -m pytest -q tests/test_run_contract_static_gates.py
uv run ruff check --select E9,F63,F7,F82 src tests
uv run ruff check <本次新增和修改的 Python 文件>
```

Definitions、正式 Dagster instance、真实 Tushare、正式 Lake、Bootstrap、event 和 Sensor 操作都受生产执行门禁约束，必须在对应阶段先列明命令和影响并取得授权。

文档阶段只运行：

```bash
python3 scripts/check_docs_integrity.py
git diff --check
```

---

## 21. 计划对账

| 技术方案硬口径 | 代码落点 | 测试落点 |
| --- | --- | --- |
| Raw 全源端，不读 Basic | Raw writer/assets | `.OF` 保留；静态 import 门禁 |
| Silver 只筛 ETF + DATE cast | Silver writer SQL | 全字段 parity、无派生字段 |
| 保留 `change` | contract/schema/SQL | `change` 存在、`change_amount` 清零 |
| 保留 `discount_rate` | fields/schema/SQL | null/负数/极端值穿透 |
| 共享 ETF 日期 | assets/jobs/sensors/bootstrap | partition identity 与 frozen dates |
| latest-only Basic | selector + Silver asset/Silver Plan preflight | 最新失败不回退、reference 漂移；Raw Plan/apply 不受 Basic 影响 |
| 历史 Basic 不在零点失效 | `etf_daily_bootstrap_cli._latest_basic` | 复用 21:00 窗口；早晨/跨零点/新版本/21:00 边界，时间异常及最新失败不回退；原 selector 和日常链保持不变 |
| 有界分页 | request builders/policies/raw writer | 参数、预算失败不提升 |
| 新增/等价复用/冲突停止 | Raw/Silver writer + Bootstrap preflight | checkpoint 续跑、等价重放、目标冲突不覆盖 |
| 21:00 + 最近 10 日 | sensor evaluator | 时间边界、最早缺口、调用次数 |
| Sensor 默认停用 | decorators | Definitions/static gate |
| 2025+ Direct Bootstrap | raw-plan/raw-apply/audit/silver-plan/silver-apply/events | 水位、范围、Raw manifest、分阶段 checkpoint 与授权 |
| 历史 Raw 审计不逐文件深扫 | `etf_daily_raw_batch_audit`、`build_raw_manifest`、`run_raw_audit` | 同年 2/20 日固定 SQL 次数；逐文件原语义对照；坏第二文件、原 hash 与只读不变门禁 |
| 最终物理验收不逐日深扫 | `etf_daily_physical_batch_audit`、`run_physical_post_audit` | 同年 2/20 日固定 15 次 SQL、3 次数据载入；逐文件全部证据与单文件检查一致；同键改值、重复/空键、错位/空日期、空 Silver、坏第二文件及只读不变门禁 |
| 因子 coverage 阻断、日线告警 | `run_contracts.etf_daily`、coverage error_codes、check/readiness/physical/events | 因子缺码/多余代码/无法计算失败，Raw 额外代码通过；日线告警仍 ready；因子 2/10 日查询预算；坏历史验收和缺证明报告不得补成功事件；旧 policy 拒绝 |
| 不使用 Prod/旧湖/Kopia | imports/paths/static gates | 全范围静态扫描 |

---

## 22. 风险与停止条件

1. 源端 fields、默认/显式字段或分页实测与 P0 不一致：停止 P2，更新源文档、技术方案和 LLD。
2. 当前 `execute_bounded_pages` 无法在不修改共享行为的情况下满足 writer：停止，不直接改共享 helper；先做 CodeGraph 影响审计并 review。
3. latest Basic selector 无法支持日常/Bootstrap 精确 reference：停止 P3，不复制一份 selector。
4. 共享动态分区不再能表达本需求：停止 P1/P5，不新建第二套日期临时绕行。
5. `fund_adj` coverage 存在缺失：按已批准的 blocking 政策停止验收或后续执行，核查源端与 Basic；不得自动退回 WARN、补值或覆盖。
6. 21:00 后当日仍未发布：停止 Sensor 启用，记录真实可用时间并修订两份文档。
7. staging/正式 Lake 非同文件系统、空间不足或 Raw Plan/目标漂移：停止 Raw apply，不降级安全门禁。
8. Silver Plan 的 Raw manifest、coverage policy、Basic 或目标漂移：停止 Silver apply，只重做 Silver Plan，不回滚 Raw。

P1—P5 的本地开发完成不授权任何正式执行动作。P6 必须按 Raw Plan、Raw apply、Raw audit/review、Silver Plan、Silver apply、物理审计、events plan/apply/post-audit 和 Sensor 启用逐阶段审批；任何现实与本文不符都必须停下来等待 review。
