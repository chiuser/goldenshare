# ETF 日线与复权因子 DG 数据湖接入 LLD v1

> 状态：已结案（2026-09-04，管理员确认）；历史入湖、事件补录、四个 Sensor 启用及首个交易日日常验收已完成；不再等待剩余两个交易日观察；因子 coverage 阻断、日线 coverage 告警的规则不变
> 更新日期：2026-10-23
> 本次补充：本轮指定56代码/26日期补齐已完成并正式验收：26文件新增701行，原42,900行零改删，补后43,601行；26成功run、156项真实检查通过。最后29日/58文件验收通过，目标869条齐全。首次失败与一次获批人工恢复保留追溯，未重复新增首日物化；当前结案及实值见§11.9.18。页首原“已结案”指P1—P6建设，本补齐任务也已按本轮证据完成。
> 上位方案：`dagster-etf-daily-data-onboarding-plan-v1.md`
> P0 证据：`dagster-etf-daily-data-onboarding-p0-audit-2026-09-02.md`
> 开发目录：`lake_console/orchestrator`

---

## 1. 设计目标与硬口径

本LLD的原P1—P6为已完成的建设依据；§11.8记录512390清理，§11.9记录56只ETF指定缺行补齐、检查优化及正式执行。开发/隔离验收见§11.9.14，首次执行及失败见§11.9.17，获批修正、恢复与最终正式验收已完成，实值及当前结案见§11.9.18。各历史“未执行/停止”只描述对应时点，不能覆盖已完成事实，也不能把当时设计或开发通过冒充正式批准。若现实代码、源接口或数据与现行设计冲突，仍须停止回到方案review，不自行增加兼容或开关。

### 1.1 必须

1. 新增 `raw_tushare_fund_daily`、`silver_etf_daily`、`raw_tushare_fund_adj`、`silver_etf_adj_factor` 四个资产。
2. Raw 直接按 `trade_date` 请求 Tushare 并保存全部返回；Raw 与 ETF Basic 无依赖。
3. Silver 读取执行时冻结的最新 ready `silver_etf_basic`，只筛 `.SH/.SZ` 现行上市 ETF，并把 `trade_date` 转为 `DATE`。
4. `fund_daily` Raw/Silver 都使用 11 个源字段，保留 `change`，禁止出现 `change_amount`。
5. `fund_adj` Raw/Silver 都使用 4 个源字段，显式包含 `discount_rate`。
6. 四个资产复用 `cn_a_etf_mins_trade_days`，Bootstrap 起点为 2025 年第一个已注册日期。
7. staging 只写 `/Volumes/datasource/data_lake_staging`，正式文件只写 `/Volumes/datasource/data_lake`。
8. 普通writer／原Bootstrap：新文件原子提升；已有等价文件复用；内容冲突立即停止且不覆盖。§11.9的指定缺行追加及检查做法已确认，2026-10-23已授权按§11.9.17逐阶段执行原范围，不增加普通writer的覆盖开关。
9. 所有生产 DuckDB 连接来自 `DuckDBResource`，所有 Parquet schema 读取显式 `hive_partitioning=false`。
10. 四个 Sensor 默认 `STOPPED`，窗口从上海时间 21:00 开始，每 tick 每 Sensor 最多一个 run。

第3项及 §9 的最新 Basic 全文件筛选用于正常生成；§11.9 只核对新增行，不重新筛选历史原有行。该区别不改变源字段合同、资产 schema 或正常生成规则。

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

2026-09-04 结案决定：四个 Sensor 获批启用并完成当日日常验收后，管理员明确要求直接结案；原连续三个交易日观察不再作为结案条件。剩余两日未执行，不宣称三日验证已通过。该决定只调整结案门槛，不改变运行窗口、readiness、coverage 或写入规则；证据见 §19 P6 与技术方案 §13 P6。

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

普通 writer 提升规则与 Raw 相同；不能覆盖由旧 Basic 生成且内容不同的历史正式文件。§11.9 的指定追加是设计已确认、正式实现和执行仍待完成的独立维护入口，不改变此 writer 规则。

---

## 10. Asset definitions

`defs/assets/etf_daily.py` 定义四个 assets。Raw 函数参数为 context、lake_root、duckdb、tushare；Silver 为 context、lake_root、duckdb，并用 `deps=[同分区 Raw, silver_etf_basic]` 声明 lineage，不通过 IO manager 传 DataFrame。

Asset 函数只做 root preflight、调用 writer、结构化日志和 `MaterializeResult`，不复制 SQL。

Definition metadata 固定登记 dataset/source/contract/schema/path/source API/doc/partition set。Materialization metadata 通过统一 builder，Raw 记录 API、脱敏 params、fields、limit、page/request/retry、source/normalized/written、hash、size、write mode；Silver 再记录 Raw/selected/rejected、reason counts 和 Basic reference fingerprint/hash/URI。

metadata 不写 token、完整代码清单、完整行样本、未命名空间 key 或 `change_amount`。

---

## 11. Asset checks

### 11.1 共享审计结果

以下为普通文件规则；§11.8 已批准且验收过的旧补值文件按该节核对原验收和实际内容未变，checks/readiness 共用判断。不得将这一历史核验扩大到其他文件。checks 不重新实现 writer 逻辑。Raw checks 调用 `audit_etf_daily_raw_relation`；Silver checks 调用 `audit_etf_daily_silver_relation` 和 `audit_etf_daily_source_parity`。所有 check metadata 使用 `build_check_metadata(...)`，包含 scope、路径、检查行数、失败数、最多 20 个样本、结论和下一步。

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
| `*_source_parity_check` | 是 | 普通文件与 Raw + frozen Basic + DATE cast 双向等价；selected+rejected=raw。§11.8 指定旧补值结果只核对原验收与输入输出未变，不重造补值行 |
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
- 现行代码的 `ETF_DAILY_COVERAGE_POLICY_REVISION = "fund_daily_warn__fund_adj_blocking_v3"`（v2 仅为 2026-09-04 历史标记；本次不改代码标记或管理员确认的规则）；因子 coverage 加入 `SILVER_ETF_ADJ_FACTOR_BLOCKING_CHECKS`，Catalog 引用同一名单。check factory 直接使用该名单，禁止再追加 coverage 导致重复注册。
- `EtfDailyCoverageAudit.error_codes` 统一缺码/多余 Silver 代码的失败事实，日常 check、因子 readiness、Bootstrap 物理验收共用。日线仍只告警。事件补录只有通过当前因子 coverage 验收后才能记录成功。
- 不改 Raw/Silver 字段、写入原子性或 source filter，不在 writer 内补值/删行/回滚；阻断的是可用性和验收。

### 11.7 历史补值与批准记录（实现已清理）

2026-09-21按当时批准恢复9月15日至18日的因子 Silver：各新增唯一人工行 `512390.SH / 对应日期 / 1.3094 / NULL`，从1649行增至1650行，各六项 blocking checks 均通过且绑定原物化。Raw、历史失败记录和sensor状态未改变。此后累计18个日期曾有批准补值；本次全部保留原文件和旧事件。

原模块、登记YAML、自动补行、源恢复冻结值限制和特许覆盖实现已删除，旧开发与退出操作说明撤下。历史批准和内容依据保留，详见方案 §8.4、§8.5及本节之后的真实核验；本段不能用于恢复运行依赖。当前覆盖合同标记继续使用代码既有v3，本次不调整合同标记或管理员规则。

2026-09-04 coverage 升级验收记录：ETF 日线定向与静态门禁共 279 项通过；`dg check defs`、Ruff、文档完整性检查通过。2/10 日因子 readiness 分别执行 4/20 次新增 coverage SQL，每资产仍只有一次 materialization 查询；缺码时不 ready，检查前后文件内容不变。07:10 正式只读复验 812 个 Raw 文件、1,460,629 行 manifest 未变，字段继承不变；当时因错误的“执行自然日必须更新”规则停止在 Silver Plan 之前。该历史阻断不代表 Basic 数据有问题，现行新鲜度口径以 §16.2.1 为准。

---

### 11.8 2026-10-21：删除补值，历史不动，统一历史检查

对应方案 §8.5，业务口径已由管理员确认。本节设计已完成代码清理与隔离验收，正式重载尚未执行；结果见 §11.8.7。此前重建 18 日历史的提案已经撤回，644 条其他 ETF 记录变化不属于本次范围；不再保留候选生成、原子替换、历史 job 重跑或历史事件补录的执行步骤。

本节“本次／本轮／历史不动”指2026-10-21的512390清理任务。随后单独确认的56只ETF缺行追加见 §11.9，正式实现和执行仍待完成；该维护不得删除或修改任何512390原有行，不得重开补值逻辑。

#### 11.8.1 开发约束与当前依据

| 已确认约束 | 清理前代码位置及事实 | 设计落点 |
| --- | --- | --- |
| 2026-10-19 起不补 `512390.SH` | `assets/etf_daily.py:silver_etf_adj_factor` 使用最新 Basic；该代码已为 D，当前未注入 | 保留最新 Basic 分类和日期转换，删除所有自动补行；不设置未来重启补值的开关 |
| 19 日之前的历史不动 | 已有 18 日物化记录包含批准补值，旧文件冻结了当时 Basic | 只读已有验收证据；Raw、Basic、Silver、物化、旧检查记录均不改；不重新以最新 Basic 生成历史候选 |
| 历史检查不依赖补值 | `checks/etf_daily_checks.py` 与 `asset_guards/etf_daily_lake_readiness.py` 当前均调用例外解析器 | 共用一个历史检查实现，证明旧验收成立且文件未变；不重新构造冻结因子、不读取 YAML、不硬编码因子值 |
| 正常规则继续有效 | source parity、coverage、schema/key/date/domain 和文件指纹核验 | 历史证据缺失、错绑、失败或文件变化仍阻断；当前应有代码缺行仍 ERROR，不降级为 WARN |
| 不扩大到其他 ETF | 旧整份重建曾测算其他记录会变化 | 删除该重建提案；不补 644 条，不改 ETF 日线、分钟线、Prod 或其他历史文件 |

CodeGraph 已使用 `codegraph_explore`、`codegraph_impact(depth=3)`；源码核对补齐 writer、checks、readiness、asset、sensor 和 bootstrap 的动态调用。只有因子补值机制及其历史检查进入清理，不改工程依赖，不引入 Prod/API/前端消费者迁移。此前[只读报告](../../reports/etf_adj_factor_workaround_retirement_audit_20261021.json)的重建数量仅为已撤回提案的历史计算，不是本次验收目标。

#### 11.8.2 新写入与历史检查分别负责什么

**新写入继续使用最新通过检查的 Basic。** 沿用现有 `classify_etf_basic_requestability` / `etf_daily_classified_select` 与常规投影，只从 Raw 筛选并转换日期。Basic 为 D 不进入新 Silver；L 且符合日期口径的代码仍要求因子覆盖。删除补值后，不再把相同冻结值作为源端数值限制；已有目标仅允许等价复用，冲突仍拒绝覆盖。本次不调用历史写入 job，不能把一次旧日期写入请求解释为重建授权。

**历史检查认可已批准、已验收且未改变的旧结果，不重新生成它。** 此次调整仅用于 19 日之前已有的批准补值文件，不将所有旧文件改成不做源对账，也不将最新 Basic 叠加到历史检查中重新定义其覆盖范围。旧 Basic 引用仅用于核对当时依据是否改变，不调用旧补值解析器或生成值的函数。

开发时的具体关联规则如下，全部从既有正式记录读取，不增加运行时名单或补值配置：

- 先保留目标 Silver 记录的编号、run_id、日期和 metadata，扩展当前只保存 metadata 的 `_MaterializationEvidence`，不能先丢弃记录身份再按日期猜测。
- 范围识别同时要求：因子资产、日期早于2026-10-19、原物化 `approved_exception_row_count=1`、`exception_sample_codes` 恰为512390.SH；原 source_parity/coverage 检查中的补值数量、代码及登记内容 hash 须与该原物化一致。登记 hash 只作为已有记录之间的身份比较，不加载已删除 YAML、不按它生成值；缺失或不匹配即拒绝。原18日批准范围的身份必须保持，不能只凭旧日期、旧成功或任意非零数量放行。
- 六项原检查按“目标物化编号 + 原 run_id + 资产 + 检查名 + 日期”匹配并检查实际 target；不得以全资产最近六条或其他日期的成功替代。原验收与清理后重查分开；后续失败或记录不明不能自动回退到某次成功，须阻断并说明。
- Raw 原依据按同资产、同业务日期，在该 Silver 原写入之前最近一次 Raw 物化取得；核对原 Raw 路径、行数、内容 hash 和现存文件。不得把 Basic 的 raw_snapshot_hash 当成 fund_adj Raw hash，不得用当前 Raw 的新版本作为历史基准。原日期批量取得这些记录；查询截断、缺项或时间顺序不明均拒绝。
- 原 Basic 直接使用 Silver 已冻结的 Raw/Silver URI 与 hash，只核对原内容；不选择此刻最新 Basic 去重算历史。比较内容指纹而不是修改时间，内容相同的文件时间变化不应误拦。

历史检查与 readiness 共用以下条件，缺一不可：

1. 目标资产、分区、物化与实际文件对应，存在当时批准补值及正式验收的可追溯事实。只读取现有记录，不新增配置/YAML/名单、历史结果表或补值数据资产；日期早于 19 日不是单独放行条件。
2. 原六项 blocking checks 已通过，且都绑定该目标物化；不能拿其他日期、其他物化或这次复查新产生的结果替代原验收依据。仅有历史 SUCCESS、物化或一条绿色检查不足以认定通过。
3. 实际 Silver 的 schema、主键、分区日期、行数、数值合同和已有内容指纹匹配原物化/验收。不能仅检查文件存在、行数或更新时间；更不能从当前输出反向生成“历史 expected”。
4. 原 Basic 引用、内容 hash、路径与历史依据相符；Raw 能对应到原验收使用的版本且内容未变。`build_check_metadata` 现有 `input_file_paths` 只记路径，不包含内容 hash；不能据此声称输入未变。必须从已有 Raw/Basic 物化、源对账和目标验收记录中追到原内容依据，再与物理文件比较；若关联或 hash 证据缺失，先停止并报告，不能现场生成新基准来补齐。
5. 原验收中存在的人工补值仍按当时批准事实保留，检查结果必须表明核验的是既有历史文件，没有声称人工行来自 Tushare、没有重新请求源或进行补值。

这明确采用“原验收记录 + 实际输入输出未变”的历史检查依据，不把旧检查通过等同于文件事实，不继续按已删除的生成逻辑重算 parity。正式 check 与日常 readiness 必须共用这些条件，符合性能治理 §5.1 的事件和文件证据边界；不能让二者各自认定通过。开发前先核验这些历史证据是否确实可读且足够；本轮18日只读核验已验证原记录和内容依据可用，见 §11.8.6；新读取实现及隔离预算验证见 §11.8.7；正式重载尚未执行。

实现位置固定为 `defs/asset_guards/etf_adj_factor_history.py`，由正式 checks 和 readiness 共用；该模块只读取证据和文件，不提供写入或补值函数。保留原物化编号和 run_id 后，使用当前 `SqlEventLogStorage.index_connection()` 与 Dagster 表定义做两次有界集合查询：一次取窗口内每项原检查及最新检查，一次取每日期原 Silver 写入之前最近的 Raw。原检查最多60项，最新检查最多60项，原 Raw 最多10项；不按日期逐条查询。仓库 `stock_period_silver_readiness.py` 已使用相同存储入口，但其“只看最新检查”不能直接替代本次“原验收 + 最新状态”的要求，因此只借鉴读取方式，不复用其业务判断。存储不支持或证据不明则明确失败，不回退到生成补值。

当前 Dagster 的检查上下文通过 `context.run.run_id` 提供本次 run 编号（不是 `context.run_id`）；以安装版本的 `AssetCheckExecutionContext.run` 实现和真实隔离检查 job 验证该交接。正式检查正在执行时，仅排除当前检查 run 自己正在产生的记录，防止把自己尚未完成的检查误当成历史失败；当前 run 的新成功也不能作为原验收。日常 readiness 不排除任何 run，后续失败、错绑或未完成记录均不自动回退。隔离测试必须覆盖当前复查与后续失败，证明没有跳过真正失败。10日窗口中原 Basic 通过现有校验后复用；不新增配置、资产、版本迁移或运行入口。

#### 11.8.3 删除、保留与实现范围

| 位置 | 删除内容 | 保留或调整内容 |
| --- | --- | --- |
| `defs/corrections/etf_adj_factor_terminal_exceptions.py` / `.yaml` | 整个补值模块、登记、缓存、有效期和冻结值 | 不用 retired 继续保留运行依赖，不另建历史补值实现；其他 corrections 不动 |
| `defs/io/etf_daily_silver_writer.py` | 例外 import/类型/入参、`_etf_adj_factor_expected_select`、`_is_approved_terminal_exception_delta`、例外生成和特许覆盖；新结果不再输出补值 metadata | 使用普通 Raw+Basic 投影；`selected + rejected = raw`，新生成文件 `written = selected`；等价复用或新建，拒绝冲突覆盖 |
| `defs/checks/etf_daily_checks.py` | 调用补值解析器、重新构造补值候选、以生成候选验证旧人工行的逻辑 | 上述历史检查与现有正常 checks；旧 metadata 只作原验收证据，不再作为生成补值的参数；不改写旧 metadata |
| `defs/asset_guards/etf_daily_lake_readiness.py` | 例外 import、解析和生成值的传参 | 与 checks 共用历史核验；最近 10 日、最早缺口和禁止越过失败保持；按窗口批量读取证据 |
| `tests/test_etf_adj_factor_terminal_exceptions.py` 及既有 ETF 回归 | 专属补值生成、登记解析、特许覆盖的测试 | 改由正常写入和历史检查回归证明停止补值、历史不变、缺证据不放行；保留正常覆盖及冲突拒绝测试 |
| 方案 §8.4、LLD §11.7 和人工批准记录 | 开发清理完成后删除旧运行操作说明，不再作为维护入口 | 保留短历史说明、管理员批准和原始审计证据；不删除正式文件和旧事件 |

唯一删除的配置是仓库本地 YAML：原来由带缓存的 `default_etf_adj_factor_terminal_exception_registry()` 加载，消费者为因子 writer/check/readiness；代码 location 重新加载后删除生效。无替代 env、运营开关、数据库配置或新例外名单。10 月 19 日是本次明确确认的业务边界，不做可调整配置；实现时仅在现有合同处维护一份，不能散落在 writer、check、sensor 中各写一遍。

现有 bootstrap `_write_silver_pair` 会同时调用 ETF 日线和因子 writer，现有日常 writer 会拒绝不等价历史目标，均不是本次历史处理入口。本次不新增迁移脚本、CLI、job、asset 或历史重建能力。共享 writer 删除补值后的变化须回归其调用方，不能因此扩大到重新执行 bootstrap。若实现审计发现合同版本或其他消费者必须改动，先说明具体依赖与范围，不能借清理自动迁移其他数据集或使历史验收失效。

#### 11.8.4 顺序、失败、中断与性能预算

1. **先核验证据。** 仅对已知 18 日批准补值记录和最多 3 个正常对照做有界只读核验，列清原物化、六项原验收和输入/输出指纹是否能对应。不做全历史扫描，不补写证据。本轮已完成18日原六项检查、Raw/Silver及共同旧Basic内容核验；开发前只重核同一有界范围是否发生新变化，不扩成全历史。
2. **再同步改检查和清退生成逻辑。** 证据足够才进入开发；checks 与 readiness 共用同一实现，之后删除生成模块、YAML、writer 分支和专属测试。不能先删除导致窗口内历史检查失败，再用重建数据补救。
3. **隔离验证后做只读验收。** 不触发历史 Silver 写入、正式 check、runless event 或历史补录；先用隔离 instance、真实合同的小样本证明规则，再以正式已有记录和文件做只读核对。上线及正式任务执行仍按独立门禁列命令，不在本轮文档修改时执行。
4. **失败只报原因。** 缺原检查、检查错绑、原验收失败、Raw 版本无法对应、文件变化都必须阻断，并指出日期、文件或缺失证据。不重建、不补值、不补绿色事件，不因历史文件难处理而重新引入例外分支。
5. **中断与续查没有历史写入状态。** 只保留临时只读报告，续查仍限定原日期/批次；不创建 Lake staging 候选或提升 checkpoint。代码尚未重载时正式运行保持现状；后续上线若验证失败，停止该次上线处理，不通过修改历史数据来推进。

| 路径 | 数量、读取及预算 | 明确不做 |
| --- | --- | --- |
| 开发前证据核验 | 18 个日期 + 最多 3 个对照，每批最多 10 日；物化和六项检查按日期集合查询；1 thread / 256 MiB，30 秒预算 | 全局读取、按日深扫 event log、下载或补数据 |
| 日常检查 | 保持 10 日窗口；每资产至多 1 次批量物化查询；历史六项检查按窗口批量读取，最多 60 个目标检查；共享 Basic 引用只校验一次 | 逐日查询检查、重新生成补值、用最新 Basic 重算旧 Silver |
| 最后只读验收 / 中断后续查 | 日期范围同开发前核验，各 30 秒预算；复用批量记录和内容 hash 核验，输入漂移立即拒绝 | 新候选、原子替换、历史 job、历史事件登记、644 条记录处理 |
| 正式数据边界 | Tushare 新请求 0；Prod 读写 0；历史 Raw/Basic/Silver 写入 0；旧物化/检查记录写入 0 | 用补数或历史事件写入替代证据门禁 |

若现有存储 API 无法按预算批量取得证据，先调整读取方案并复核，不以“历史数量少”为由逐日查询或取消检查。预算是待测门禁，不是本轮性能实测通过结论。

#### 11.8.5 测试与口径对账

| 硬口径 | 必须验证的正向和反向情况 |
| --- | --- |
| 19 日起不补值 | Basic=D 且 Raw 无记录时，Silver 不生成512390；Raw 即使返回该代码，也按正常 D 过滤；没有上一日因子复制、固定值注入或特许覆盖 |
| 当前应有代码缺失仍阻断 | L 且符合上市日期的其他代码缺因子仍 ERROR；完整源数据正常通过；合法源因子改变不再被旧冻结值拒绝 |
| 历史数据不动 | 旧 Silver 中保留已批准人工行，Raw/Basic/Silver 文件与旧记录修改前后指纹相同；不调用写入入口或产生候选/历史事件；不要求新增其他 ETF 历史行 |
| 历史不依赖生成逻辑 | 移除模块/YAML 后，原验收齐全且文件未变的旧结果可核验；输入/输出改变、缺一项原检查、错绑、失败、仅有SUCCESS或仅有行数都不能通过；不得由本次新检查自证原验收 |
| 不扩大历史放行 | 未批准或未验收的旧额外行不能因日期早于19日就被认可；旧正常文件保持原检查，历史核验不足不触发补数 |
| 日常不被旧依赖卡住 | 最近10日同时含旧补值文件和19日之后正常文件，checks/readiness 结论一致；当前真正缺数和文件改变仍阻断最早日期 |

夹具字段、日期类型、原检查绑定与 hash 的依据来自当前真实生产者和现行合同，关键 expected 使用独立字面样本，不由待测函数生成。验证范围包括 ETF writer/checks/readiness、sensor、contract、bootstrap 的定向回归和静态护栏；不以隔离测试代替原证据可用性的真实只读核验。

本轮已完成上述代码调整与隔离验收，对账见 §11.8.7；正式重载尚未执行。后续如发现无法在“历史不动”范围内满足的条件，仍须报告，不回到整份历史重建方案。

#### 11.8.6 本轮真实只读核验结果

[核验报告](../../reports/etf_adj_factor_terminal_cleanup_readonly_verification_20261021.json)：18/18 个原 Silver 写入各有原 run 的六项成功且正确绑定的 blocking checks，共108项；各日原 Raw 物化与当前最新 Raw 物化编号相同，18份 Raw 内容 hash 及18份 Silver 内容 hash 均与原记录相同，字段/键/日期/数值合同无失败。共同旧 Basic 两份快照经管理员明确批准后各完整读取一次（Raw1829行、Silver1826行），规范化内容 hash 分别与原引用匹配。只读文件计算0.461秒不含该两份Basic复核及数据库查询；不是新生产读取实现的全程性能验收。

这证明本次保留的原数据未改变，不需要重建或改旧事件。报告不是运行时名单，开发仍从正式已有记录取依据。158011的源端、Raw和Silver覆盖差异及贴水率差异仅作单对象审计记录；不能转成本次补数任务，也不能据源日期齐全就断言旧Silver齐全。


#### 11.8.7 本轮实施与验收结果

| 已确认要求 | 实现与验收 |
| --- | --- |
| 停止补值，删除workaround | 模块/YAML/原生成测试已删除；writer 删除合并补行、冻结值限制、特许覆盖和新补值metadata。D 有/无源行均排除；L 缺因子仍由正式 coverage 阻断；合法源值变化正常接受 |
| 旧历史不动 | 历史检查仅核验原六项验收、原Raw、冻结Basic和实际Silver；新模块没有写入方法、冻结因子值或外部配置。文件内容、修改时间变化、缺检查、失败、错绑、未完成、未批准及19日之后错误声称补值均有正反测试 |
| 检查和日常判断一致 | checks/readiness 共用历史核验；旧文件与19日正常文件混合窗口通过；坏文件两端均失败。真实六项检查在隔离job运行并绑定原目标，未重新物化因子文件；测试辅助资产仅提供本版本所需的分区执行上下文，无数据I/O，不进入正式Definitions |
| 小窗口和共享Basic | 10日期隔离样本的原/最新检查与原Raw读取固定2条集合SQL，无逐日查库；共享Basic按引用只校验一次；原有最多10日窗口、最早失败不越过保持 |
| 真实只读核验 | 新证据读取实现核验18日原验收及最新检查均通过，36份Raw/Silver内容hash与原记录一致；1线程、内存上限配置256MB、无spill，合计4.22秒。两份旧Basic复用本轮此前经单独批准的完整核验，不重复完整读取；这里没有声称重新运行正式六项check |

测试按现行真实字段、日期类型和事件绑定构造字面历史样本，29项专项测试包括真实检查上下文的 `context.run.run_id`。ETF定向回归207项通过（含上述29项专项），受保护资产治理12项及增量治理6项通过，共225项、无跳过；数量和结果记入[核验报告](../../reports/etf_adj_factor_terminal_cleanup_readonly_verification_20261021.json)。资产治理/增量治理分别通过仓库既有受保护启动器运行，未过滤或弱化失败项；普通pytest的启动方式缺少该套件隔离上下文，相关单项最初失败不作为通过证据。Ruff致命基线、本次Python完整规则、隔离 `dg check defs --use-active-venv --no-check-yaml` 及文档检查通过。

CodeGraph已使用explore/impact(depth=3)及最终status，覆盖writer→checks/readiness、asset/sensor、bootstrap和对应测试；本次没有Prod/API/前端消费者、没有跨工程合同迁移。正式instance、Lake、任务和sensor均未被用作测试资源；正式读取只执行有界SELECT与文件审计，没有任何正式写入。

#### 11.8.8 清理任务当时列出的正式操作（本任务未执行，须按执行时状态另审）

正式DG只读确认 `http://127.0.0.1:3000/graphql` 的location为 `orchestrator`、状态 `LOADED`。重载会重新加载整个location；工作区另有其他任务的未提交改动，因此不能把本次512390验收扩大解释为其他改动的发布批准。执行前须确认这些改动已具备发布条件；不自行切分支、另建worktree或覆盖他人文件。

获准后的唯一变更是重载该location，工作目录为 `/Users/congming/github/goldenshare/lake_console/orchestrator`，正式instance为 `DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home`。使用已安装版本的 `reloadRepositoryLocation(repositoryLocationName: "orchestrator")`；不使用 `reloadWorkspace`，不执行job/check/sensor评价，不改cursor、分区、历史事件或Lake文件。完整待执行命令如下，仅作待批准操作清单：

```bash
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home curl --fail-with-body -sS --max-time 30 \
  -H 'Content-Type: application/json' \
  --data-binary '{"query":"mutation { reloadRepositoryLocation(repositoryLocationName: \"orchestrator\") { __typename } }"}' \
  http://127.0.0.1:3000/graphql
```

执行后仅只读确认location重新加载成功及因子定义可见；若返回错误或加载失败，立即停止并报告，不重启服务、不重跑历史、不恢复补值、不改其他任务。重载影响和失败原因须按当前工作区重新核验，不能用回写历史数据解决。未获此独立阶段批准前，本次结论仅为“代码清理、隔离验收及正式只读核验完成”，不是“已正式发布”。

### 11.9 2026-10-22：只补指定代码和日期的缺行

#### 11.9.1 目标、当前状态及授权

对应[方案 §8.6](dagster-etf-daily-data-onboarding-plan-v1.md#86-2026-10-22只补指定代码和日期的缺行)。管理员已确认业务口径：最新 Basic 只用于指定ETF的指定缺行，保留所有原有行；并已确认六项检查合并执行、保留六项结果，以及26日补数后真实运行检查并追加新记录。最初方案修订阶段仅改两份文档；随后完成前置读取并进入部分开发，见§11.9.10—§11.9.12。管理员2026-10-23要求严格按LLD推进开发，当前实现与隔离证据见§11.9.14。正式文件、事件、任务执行和重载仍按独立阶段批准，原直接补写检查的方式不再执行。原P1—P6和§11.8的已完成测试不作为本节已实现或已验收的证明。

本节范围只含 `silver_etf_adj_factor`。正式路径仍为 `/Volumes/datasource/data_lake/silver/quote/etf_adj_factor/trade_date=YYYY-MM-DD/part-000.parquet`；候选及执行进度只在 `/Volumes/datasource/data_lake_staging/etf_daily/` 的本次独立执行目录内。Raw、Basic、ETF日线、分钟线、Gold、Prod、调度配置和旧事件写入数均为0。保留全部512390原行，不恢复其补值或登记，不改当前源接口合同或合同版本、字段顺序、资产schema、六项检查名及 blocking 级别。

#### 11.9.2 固定代码、上市日期和缺行日期

证据为2026-10-22 00:19上海时间的[有界审计](/private/tmp/etf_56_listing_coverage_20261022.json)，使用当时最新10月21日Basic。该Basic快照编号为 `02670eabbf3993a91e5d3706006808565acd0e5a8d195dd57b89983a8b07c25f`；Raw/Silver Basic 分别观察于21:09和21:18。这里只核验56只的字段，没有完整读取这份快照计算新指纹。准备正式 Plan 时重新确认最新 ready 引用并冻结；不能把本次审计水位说成未来执行时仍是最新。

56只Raw均从本表上市日开始；截至10月21日共869条应有记录，Raw无缺失，Silver已有168条（10月19、20、21日每天56条）。新增仅为本表上市日起、至10月16日止的SSE开市日，并须逐键确认现有Silver缺失；合计701条、26文件。不得用自然日补齐，也不得把10月19日起的完整文件纳入候选。

| 旧 Basic 情况 | 代码数 | 应有记录 | Raw缺失 | Silver待追加 |
| --- | ---: | ---: | ---: | ---: |
| 无代码 | 20 | 220 | 0 | 160 |
| 上市日期为空 | 7 | 194 | 0 | 173 |
| 状态仍为P | 29 | 455 | 0 | 368 |
| 合计 | 56 | 869 | 0 | 701 |

下表是本次代码范围；不是新增运行时配置。未来执行 Plan 从本次 review 认可的表和正式数据生成；不允许CLI自由接受其他代码或日期，也不另维护一份可随意扩大的名单。

| 旧 Basic 情况 | ETF代码 | 上市日期 | 待追加行数 |
| --- | --- | --- | ---: |
| 无代码 | `158040.SZ` | 2026-10-14 | 3 |
| 无代码 | `158041.SZ` | 2026-09-17 | 16 |
| 无代码 | `158043.SZ` | 2026-10-15 | 2 |
| 无代码 | `158046.SZ` | 2026-10-12 | 5 |
| 无代码 | `158047.SZ` | 2026-10-15 | 2 |
| 无代码 | `158049.SZ` | 2026-09-22 | 13 |
| 无代码 | `158050.SZ` | 2026-09-18 | 15 |
| 无代码 | `158052.SZ` | 2026-10-16 | 1 |
| 无代码 | `158053.SZ` | 2026-09-23 | 12 |
| 无代码 | `158055.SZ` | 2026-10-16 | 1 |
| 无代码 | `158056.SZ` | 2026-09-24 | 11 |
| 无代码 | `158057.SZ` | 2026-09-23 | 12 |
| 无代码 | `158058.SZ` | 2026-10-14 | 3 |
| 无代码 | `158059.SZ` | 2026-09-30 | 8 |
| 无代码 | `158061.SZ` | 2026-09-16 | 17 |
| 无代码 | `158063.SZ` | 2026-09-24 | 11 |
| 无代码 | `515470.SH` | 2026-09-24 | 11 |
| 无代码 | `515540.SH` | 2026-09-30 | 8 |
| 无代码 | `562200.SH` | 2026-09-30 | 8 |
| 无代码 | `562420.SH` | 2026-10-16 | 1 |
| 上市日期为空 | `158011.SZ` | 2026-09-04 | 25 |
| 上市日期为空 | `158013.SZ` | 2026-09-07 | 24 |
| 上市日期为空 | `158023.SZ` | 2026-09-07 | 24 |
| 上市日期为空 | `526060.SH` | 2026-09-04 | 25 |
| 上市日期为空 | `561530.SH` | 2026-09-03 | 26 |
| 上市日期为空 | `561690.SH` | 2026-09-07 | 24 |
| 上市日期为空 | `589430.SH` | 2026-09-04 | 25 |
| 状态仍为P | `158022.SZ` | 2026-09-18 | 15 |
| 状态仍为P | `158025.SZ` | 2026-09-28 | 10 |
| 状态仍为P | `158026.SZ` | 2026-09-23 | 12 |
| 状态仍为P | `158028.SZ` | 2026-09-11 | 20 |
| 状态仍为P | `158030.SZ` | 2026-10-09 | 6 |
| 状态仍为P | `158031.SZ` | 2026-09-22 | 13 |
| 状态仍为P | `158032.SZ` | 2026-09-14 | 19 |
| 状态仍为P | `158037.SZ` | 2026-10-15 | 2 |
| 状态仍为P | `158038.SZ` | 2026-09-16 | 17 |
| 状态仍为P | `158039.SZ` | 2026-09-29 | 9 |
| 状态仍为P | `158042.SZ` | 2026-09-24 | 11 |
| 状态仍为P | `159025.SZ` | 2026-09-14 | 19 |
| 状态仍为P | `512470.SH` | 2026-09-24 | 11 |
| 状态仍为P | `512740.SH` | 2026-09-14 | 19 |
| 状态仍为P | `515440.SH` | 2026-09-10 | 21 |
| 状态仍为P | `515940.SH` | 2026-09-17 | 16 |
| 状态仍为P | `516040.SH` | 2026-09-18 | 15 |
| 状态仍为P | `526090.SH` | 2026-10-16 | 1 |
| 状态仍为P | `561070.SH` | 2026-10-13 | 4 |
| 状态仍为P | `561610.SH` | 2026-09-16 | 17 |
| 状态仍为P | `561650.SH` | 2026-09-30 | 8 |
| 状态仍为P | `562110.SH` | 2026-09-16 | 17 |
| 状态仍为P | `562150.SH` | 2026-09-14 | 19 |
| 状态仍为P | `562170.SH` | 2026-09-14 | 19 |
| 状态仍为P | `562400.SH` | 2026-10-14 | 3 |
| 状态仍为P | `562450.SH` | 2026-09-28 | 10 |
| 状态仍为P | `589480.SH` | 2026-09-24 | 11 |
| 状态仍为P | `589490.SH` | 2026-09-30 | 8 |
| 状态仍为P | `589510.SH` | 2026-09-17 | 16 |

逐日期文件的追加数固定如下；正式 Plan 还须保存每条明确的代码、日期，不能仅凭总数通过。

| 交易日 | 待追加行数 |
| --- | ---: |
| 2026-09-03 | 1 |
| 2026-09-04 | 4 |
| 2026-09-07 | 7 |
| 2026-09-08 | 7 |
| 2026-09-09 | 7 |
| 2026-09-10 | 8 |
| 2026-09-11 | 9 |
| 2026-09-14 | 14 |
| 2026-09-15 | 14 |
| 2026-09-16 | 18 |
| 2026-09-17 | 21 |
| 2026-09-18 | 24 |
| 2026-09-21 | 24 |
| 2026-09-22 | 26 |
| 2026-09-23 | 29 |
| 2026-09-24 | 35 |
| 2026-09-28 | 37 |
| 2026-09-29 | 38 |
| 2026-09-30 | 43 |
| 2026-10-08 | 43 |
| 2026-10-09 | 44 |
| 2026-10-12 | 45 |
| 2026-10-13 | 46 |
| 2026-10-14 | 49 |
| 2026-10-15 | 52 |
| 2026-10-16 | 56 |
| 合计（26日） | 701 |

旧644为上述同56只在9月15日至10月16日的缺行；9月3、4、7、8、9、10、11、14日合计57条属于上市日起的必要补齐。这个扩展已在前次只读核验中说明，本次不增加代码、不重建全市场。如准备时真实差异不是固定701键，先列差异并回到 review；同一次已批准 Plan 的断点续跑不重新定义原目标。

#### 11.9.3 当前代码依据、复用和拟议改动位置

以下是本节实现位置和边界；表中“已有/拟议”保留开发前代码依据，实施后的代码与测试对账统一见§11.9.14。当前合并检查与维护阶段已接通，尚未正式执行。

| 位置（均相对 `orchestrator/src/orchestrator/`） | 当前事实及拟议处理 |
| --- | --- |
| `defs/io/etf_daily_silver_writer.py` | `etf_daily_classified_select` 分类整份Raw，普通 writer 遇不同目标拒绝覆盖。保留公开API和普通写入规则；只复用经核对的日期投影、schema/键/数值审计和规范化内容指纹，不增加通用覆盖参数 |
| `defs/bootstrap/etf_daily_bootstrap_apply.py`、`etf_daily_bootstrap_events.py` | `_write_silver_pair` 写日线和因子；原事件校验要求四资产、尾部窗口，并拒绝不同旧物化。不能直接调用这些整段入口；不改它们来绕过原门禁，只复用无业务范围扩张的纯序列化、内容指纹和原子进度保存工具 |
| 拟新增 `defs/bootstrap/etf_adj_factor_history_completion.py`、同目录 `etf_adj_factor_history_completion_cli.py` | 仅承载本节批准范围的只读Plan、候选生成/审计、正式提升、事件登记及读回；各阶段独立，不提供一键连续执行。另写入口的原因是现有两入口会扩大资产或全文件筛选，无法满足原有行不变 |
| `defs/asset_guards/etf_adj_factor_history.py` | 当前 `audit_factor_history` 直接读整份文件对原指纹。拟拆开“从原正式记录取依据”和“对给定原有行核验”，保留未改动旧文件路径；新增行审计与正式checks/readiness共用，不能复制一套宽松判断 |
| `defs/checks/etf_daily_checks.py`、`defs/asset_guards/etf_daily_lake_readiness.py` | 已有完成记录识别的部分实现；因子仍是六个独立检查入口，各自核验。按 §11.9.12 合并为一个执行定义，共用一次核验、保留六项结果；普通及未改动历史文件的通过/失败语义不变，readiness仍要求六项结果全部正确绑定。缺记录或未知格式拒绝，不回退旧分支 |
| `defs/run_contracts/etf_daily.py`、`defs/catalog/lake_assets.py` | 仅在本工程维护追加证据的严格类型及因子资产说明；既有源字段合同、数据集名、路径、schema、六项检查和正常写入政策保持。不迁移Prod或其他资产 |
| 测试位于 `lake_console/orchestrator/tests/`（不相对本表源码目录） | 新增指定追加的隔离测试，定向回归现有writer、历史检查、正式六项检查、readiness/sensor及bootstrap调用方；不使用正式instance/Lake作测试资源 |

已通过CodeGraph explore/impact及当前代码核对writer、checks/readiness、asset/sensor、bootstrap和测试；直接引用搜索未发现本次因子资产的Gold、Prod、API或前端计算消费者。开发前复核索引和直接调用方；若发现会受本次事件字段影响的其他消费者，先列影响修订本节，不能借机改其他数据集。不新增配置项、表、数据资产、job或sensor；当前正常writer仍不能自动维护历史。

#### 11.9.4 Plan必须冻结的依据和读写边界

1. 固定本节56代码及上市日期、26日、701组明确键；SSE日历在所需日期完整且开市标志有效。每键只允许一次新增；上市前、非开市日和10月19日起均不在范围。
2. 每日记录原正式目标URI、行数、规范化内容指纹、物化记录身份及绑定它的六项成功检查；读取原 Raw 及 Basic 的真实引用和内容依据。不是用本次重新算出的指纹冒充原验收。带自动补值证据的18日沿用§11.8身份与验收条件；其余旧文件按原正常合同核对。9月10、11、14日人工修正已同时存在于Raw/Silver，保留其实际内容及当时验收，不强套18日自动补值身份，也不新造名单或补值。
3. 26日原验收与实际文件均匹配才冻结可执行 Plan。此前18日108项的核验仅覆盖§11.8，不代表另8日已验收；缺少任一原依据即停止并列原因，不自动重跑检查制造原成功。准备时若出现未解释的后续失败或错绑，不回退早期成功继续。
4. 每日现有Raw文件的URI、行数、内容指纹及正式引用；新增行必须已经存在于该Raw，允许的唯一业务转换是源 `YYYYMMDD` 到 Silver `DATE`。因子、贴水率不做四舍五入、默认值或填补，允许的NULL原样保留。
5. 准备时最新且ready的Basic引用，只投影56代码的 `ts_code/exchange/list_status/list_date` 核对新增资格；`L`、非空上市日期、后缀与市场一致且上市日期不晚于对应交易日。保存该快照引用和56行内容依据，不把这个Basic绑定给全部旧行。生成候选前确认仍是所冻结的最新ready引用；引用改变则停止重新核对，不静默换版本。候选审核后执行提升只使用已冻结引用，仍核对其内容/验收有效，不追随之后的新快照自动改范围。
6. 固定原文件与新增行的独立计数、指纹，候选路径、完整候选预期指纹、每文件预期新增键。完整候选预期指纹在Plan阶段从“原行+明确新增源行”的SQL结果计算，不提前写候选，也不在冻结后补改Plan。Plan内容hash只对业务范围、schema、Raw/Basic/原Silver内容依据及预期输出计数/hash做规范化计算；事件自增编号、run_id、观察时间、mtime、执行目录不参与完成身份。完整Plan另保存这些追溯证据，并逐项核对它们真实存在且绑定正确；不能因其不参与业务hash就免检。原物化编号只用于追溯，不放入业务 `run_key`、`run_config`、上游批次号或完成身份。
7. Plan未完整核验前只能保存不可执行草稿；全26日通过后原子冻结，任何后续内容变更都使旧批准失效。临时审计JSON只作来源说明，运行时不依赖 `/private/tmp`，也不读已撤回644测算报告来决定范围。

全局Basic内容读取沿用根规则：有界56代码投影不等于已验证整份快照内容。管理员2026-10-23已明确批准本任务新维护进程重新完整核验限定两对Raw/Silver Basic；确切文件、字节、30秒初始化与内存复用方式见§11.9.17。初始化后不再完整读取，运行中缺失/错引用立即停止；下次明确维护启动允许重新核验该有限范围，不追旧进程。超出两对或另增快照不在批准内，不能拆批绕过；必要合同/内容证据不足时Plan不可冻结。

#### 11.9.5 候选如何生成和核对

本节Plan、候选、报告和进度均须实际位于已确认的staging范围；读取或创建前检查根目录、中间目录和目标是否为符号链接，发现即停止，不跟随链接把读写带到其他位置。复用现有路径核对和原子写入，不增加可选路径参数。

每日期一个单位，经 `DuckDBResource` 连接用SQL处理；Parquet显式 `hive_partitioning=false`。保留4列顺序和类型：`ts_code VARCHAR / trade_date DATE / adj_factor DOUBLE / discount_rate DOUBLE（可空）`。不把每条记录长期装入Python对象，不跨历史累积DataFrame。

生成步骤：

1. 重核该日期原物化、原目标与Raw/Basic依据和Plan相符。原目标内有批准键时，若是同一Plan续跑，按§11.9.7识别已完成文件；其他情形不把它自动删出701键。相同键异值立即停止，不更新原值。
2. 仅从本日Raw取Plan中本日明确键，逐键验证恰好一行、日期和数值合同正确、Basic资格正确；实际来源键必须与批准键双向相等。Raw少行或多行均不能通过，也不能扩大到最新Basic中其他上市ETF。
3. 原目标全部行 `UNION ALL` 新增行，生成staging完整候选。原行不再经过Basic筛选，不改类型/值，不去重掩盖重复；出现重复键直接拒绝。文件编码、物理行序可以变化，四列的业务值必须完全保留。
4. 先核对所有原键仍在且逐字段相同；从候选排除**恰好批准新增的键**后，规范化行数/内容指纹必须等于原已验收文件。新增部分对Raw投影做双向比较，NULL使用空值相等的比较规则；全文件无重复、日期一致、schema/因子/贴水率合同通过。普通候选writer的部分校验不能代替这里的完整校验。
5. 候选总行数必须为原行数加本日批准追加数；26日总差异必须恰为新增701、修改0、删除0。保留候选及核验报告供管理员review；不因候选通过就直接提升。

例如含已批准512390人工行的9月15日文件，应完整保留该行及其他旧行，只加入当日批准的14条Raw行；不能按新Basic删除512390，也不能把它重新注入一次。未经批准的新ETF即使在最新Basic里是L且Raw有值，也不得加入。

#### 11.9.6 补后正式检查、Basic和计数

新完成物化除真实全文件URI、行数和指纹外，拟增加严格结构的 `goldenshare/history_completion` 证据。它不是运营开关或新源合同，而是说明这份文件保留了哪些原依据、具体加了哪些源行；仅因子资产接受，未知字段、缺项或范围不符拒绝。

| 证据内容 | 必须保留的实际依据 |
| --- | --- |
| 本次范围 | 已审Plan内容hash及完整冻结内容，含56代码上市日、26日和701明确键、本日期的新增数量/独立内容hash；不是只有hash或临时文件地址 |
| 原有行 | 原物化身份、run_id、原六项成功检查的真实target、原行数/hash、原Raw与Basic引用；原run_id为空就保留为空，使用物化target/日期/检查名核对，不补造run；带512390批准的原证据保持不变 |
| 新增行 | 原始Raw引用与内容hash；新增使用的冻结Basic引用及56代码字段依据；本日期新增Raw投影的行数/hash |
| 完整新文件 | 新行数/hash、正式URI；实际新物化身份在登记后读回，再供新检查绑定，不预造编号，不绑定旧物化或其他日期 |

正式检查/readiness从新物化metadata内嵌的冻结Plan核验范围和内容hash，不依赖staging、临时报告或本机文档作为运行时事实源。单份完成证据大小上限256 KiB，10日批量最多2.5 MiB；超限先调整设计，不删掉原依据或改成只有一个无法核验的文件地址。staging仅保存候选、执行报告和进度，不代替正式文件及事件。

正式检查与readiness共用文件核验顺序：先检查新完整文件自身合同与新物化一致；再排除批准新增键验证全部原有行与原验收一致；再校验新增键与冻结Raw、对应Basic资格双向一致。正式检查据此生成本次结果，不要求尚未生成的新六项已成功；readiness在相同文件核验后，额外核对新六项最新状态均通过且绑定当前新物化。补后文件不再与原整份hash直接相等，但其全部原有行仍必须与原hash相等。缺少完成证据时不能用文件形状猜测，更不能把变了的文件当作§11.8未变文件放行。

原六项检查名和阻断级别不变：schema/key/domain仍检查完整文件；filter/source_parity/coverage分别核对原已验收部分及明确新增部分。旧行不重新要求在最新Basic为L；新增行也不能只借原验收放行。不声称已符合“整份Raw按最新Basic重筛”的结果。只有本次完整通过，才能为新物化记录真实六项结果。

管理员已确认六项合并执行：一次读取并核验，随后根据这次核验的实际结果分别产出六项 `AssetCheckResult`；不在六项循环内重新读取文件或重新调用完整核验。整体通过条件为六项全部真实通过；任一项失败则检查整体失败、该日期不ready并停止。各项仍保存自己的真实结果，不能把正常项涂成失败或失败项涂成通过；缺项、未判定或读取异常不能视为整体成功。正常因子更新、本节追加文件及§11.8未改动历史文件共用这个执行定义，保留各自已有通过/失败规则和单项选择能力；不改ETF日线、Raw或其他数据集的检查。实现和测试门禁见 §11.9.12。

计数必须区分用途：新 `dagster/row_count`、`goldenshare/written_row_count` 及全文件内容hash反映新文件；原 `selected/rejected/raw` 计数和旧Basic引用保存在原证据中，新增计数单独保存。新记录不得照抄旧 `written` 或声称“新written=旧selected”；普通writer仍用 `selected+rejected=raw、written=selected`。新物化的 `goldenshare/basic_reference` 保持指向原行的旧依据，新增Basic仅在完成证据内单独绑定，所有读取此metadata的相关检查/readiness需在同次开发中同步，不让某个调用方误以为新Basic筛选过全部旧行。

对18日自动补值文件，原批准数量、代码、内容和原六项验收仍按§11.8核对，但该核对接收的是“新文件中剔除批准新增键后的原有行”。保留原Raw/Basic证据核验，不重新运行补值；9月10、11、14日人工修正按§11.9.4第2项保留。§11.8中尚未追加的旧文件继续原路径；已完成追加的日期必须先进入本节路径，不能再次拿新整份文件跑旧整份指纹判断。

原验收只向前取一层，原物化不得已经是其他追加Plan的结果；重复执行同一Plan则识别自己的完成记录。当前方案不设计无限追溯、滚动迁移或后续任意追加；若遇到另一Plan已经处理的目标，停止另审。各次复查的新成功不替代原成功；复查时只排除当前检查run自身未完成记录，readiness不排除后续失败，沿用§11.8已核验的语义。

原验收绑定原物化，补后最新检查状态绑定当前新物化，两个target分开查询。冻结前未解释的失败仍阻断；文件已提升而新事件未齐时，旧物化因实际整份指纹改变而不能通过，是尚未完成的真实状态。新物化与六项检查齐备后，按新target判断当前状态，旧target在这段期间的失败作为历史记录保留并说明，不能拿它代替新检查，也不能忽略新target之后的失败。

#### 11.9.7 提升、事件与中断续跑

**阶段独立。** CLI分别提供只读Plan、生成候选、审计候选、提升文件、登记新物化/检查、最后只读核对，已按2026-10-23开发授权实现。现行正式调用、固定Plan路径和读写量见§11.9.17；管理员已授权原范围在内部验收和独立候选总审计通过后依次执行，每次只调用一个阶段，不修改日常CLI入口行为。

**提升前：** 候选已全部通过且经review、所需共用检查代码已验收；确认正式代码状态和对应日期无在途写入/检查任务。沿用现有Lake root preflight核对正式挂载、目标权限、staging位置、同文件系统和可用空间；可用空间须满足本方案既有2.5倍候选空间预算，不创建错误挂载点或改用其他目录。每文件前重新确认原目标hash和最新物化仍为冻结原依据，候选hash未漂移；同文件系统才允许 `os.replace()`。不自动暂停sensor、取消任务或重载location；如存在冲突先停止并说明。

**进度：** Plan、26个文件的候选审核结果、逐文件实际指纹、已提升数量及最后更新时间，均在staging执行目录原子保存；文件提升后立即读回核对并保存本日进度。每文件前后检查取消；中断保留已完成文件和所有证据，不删除、不回滚，不靠Kopia或正式文件副本恢复。

| 续跑时实际文件 | 处理 |
| --- | --- |
| 仍等于冻结的原文件 | 原依据及候选仍有效才可执行该文件提升 |
| 已等于本Plan核验过的完整候选 | 读回核对、补记本日完成；包括replace成功但进度未保存的情形，不重复追加或再替换 |
| 与两者都不同／出现同键异值 | 停止并列差异，不覆盖、不重新取当前内容作基准 |

**管理员已确认改为真实检查运行；本段原直接补登记检查的方式禁止执行。** 六项合并执行及保存方式见 §11.9.12，数据目标及保留要求不变。

**文件与事件分开：** 原事件全部保留。文件提升成功但未登记新物化、检查未齐或失败时，readiness必须阻断，不能沿用原成功。按§11.9.17既有授权，在每日期文件已读回一致后追加一个新因子物化，再触发现有因子任务的检查部分；一次合并核验后由真实运行产生六项结果，全部绑定该新物化。失败结果如实保留并停止，不能预设全绿。26日成功目标为26物化+156检查=182条文件/检查事件；另有26次真实运行及其日志，182不是全部event log数量。不触发Raw、Basic、ETF日线、分钟线或sensor。

**已确认：新物化先找回并保存，再准备检查运行。** 实现仍在已列出的维护bootstrap模块/CLI内，复用现有物化查询与登记接口、`atomic_write_json`和逐日进度。只读Plan不得调用登记接口。正式事件阶段每日期追加前，以及新物化步骤中断后的续查，都先用`fetch_materializations(AssetRecordsFilter(asset_key=本因子资产, asset_partitions=[本日期]), limit=1)`取最新1条，不搜索更早历史、不跨日期探查；文件已读回且仍为审核候选是前提。

| 最新1条物化的情况 | 处理 |
| --- | --- |
| 本Plan的等价完成记录 | 核对本Plan完整内容/hash、正式URI、完整行数/written/hash、旧Basic引用及原验收依据均一致，复用实际storage_id/target；进度已有target时还须与其一致。补保存本日target，不重复追加 |
| 恰为冻结原物化的storage_id、run_id及metadata | 原依据、文件和全部正式执行门槛仍成立，且事件阶段获批，才通过Dagster正常接口首次追加1条新物化 |
| 查无、读取失败、另一Plan/target、文件或依据不符 | 停止并保留进度，不回退旧成功、不覆盖记录、不直接重发 |

真正追加后，再以相同资产/日期、`limit=1`读回最新记录，按上表的本Plan条件完整核对实际target；不能把不返回storage_id的登记接口返回值当作target。新target原子保存成功后，才进入§11.9.12的检查UUID准备与启动。追加抛错、读回不明或target保存失败都停止，实际检查启动数为0；续查仍按上表找回，不因本地没保存target就再追加。正常每日期本子步骤最多2次查询、每次最多1条，26日最多52次；已有等价记录时仅1次查询。仅处理未完成日期，恢复沿用同一上限；该计数不包含检查原依据查询，全部仍计入事件/续查各30秒预算，不自动轮询或重试。

事件阶段按日期保存新物化及拟用于真实检查的run_id、实际状态和已产出的结果。新物化中断按上表的资产/日期/Plan找回；检查运行中断才按预存run_id查回，不能混用。每日期只有一个拟用检查编号，先原子保存再调用Dagster正常创建；续跑读取已有编号，不重新生成。幂等识别按本Plan、资产、日期、全文件hash、实际新target及检查名核对；检查已完成而进度未保存时，按该编号有界查回再复用，不启动第二次。已开始或运行状态不明时不另起运行；未解释的状态即停止。具体检查状态分支与首次调用条件见 §11.9.12。出现另一Plan/另一target、更新的冲突物化或错误绑定就停止。文件完成但事件阶段中断，文件不重写；真实检查的结果由该运行产生，不用直接补写接口拼齐缺项。已记录失败的检查不得自动重发转绿，须先审计原因、另审后续操作与数量。正常成功目标不包含额外重试批准。后续重载的具体影响须另审当前工作区；§11.8.8历史命令不是本阶段批准。

#### 11.9.8 数量、资源和查询预算

| 项目 | 硬上限与方式 | 失败处理 |
| --- | --- | --- |
| 候选/提升的数据文件 | 固定26日期；1日1单位，单文件最多5000行，候选合计最多130000行；26日Raw/原Silver/候选合计最多16 MiB，实际大小先统计；只读对应文件完整行以证明旧行未变是必要范围，不扩成全部历史 | 超出行数或字节先报告，不能自行提高；0 Tushare请求、0 Prod访问 |
| 最后验收的数据文件 | 26变更日加10月19—21日，共29日；去重Raw/Silver最多58个文件，总字节单独限16 MiB，先统计再读。26日核对完整新文件和701新增键；另3日只核对56代码共168条已有行与既有正式物化中的文件指纹，不做完整六项复查、不触发检查运行；不再读其他正式对照日期 | 58是不同文件上限，不是扫描次数；实际扫描/载入次数仍须测量。超字节、范围或指纹不符即停，不新增候选或写入 |
| DuckDB | 现有Resource；1 thread、256 MiB、无spill；SQL读取与投影、逐文件COPY，不逐行Python、不跨日DataFrame；候选与正式目标同文件系统 | 超内存、spill、跨文件系统拒绝；保留证据 |
| 元数据预检/Basic初始化 | 两阶段各30秒；预检仅26日原引用3批、Basic Raw/Silver各latest 1及3项检查和4路径stat。初始化最多两对/4个Basic文件，以现有审计完整核验后冻结内存，允许审计内部有限重复扫描；实际文件字节见§11.9.17 | 超时、第三对、引用/内容/56业务字段不符即停；不读取因子准备文件，不把正常latest更新视为未冻结Plan失效 |
| 准备/总审计/续查/最后验收 | 各30秒；准备、候选及其审计仍只处理26变更日。最后26日readiness按最多10日3批，另3个完整日仅按上行只读核对；初始化后不同Basic引用共享同一已核验内存，最后验收及必要续查显式传入，每连接seed，不重新完整读取Basic | 计时含证据关联与文件核验；需要Basic而内容缺失即停，仅查运行状态不强加Basic条件。超时停止，不另扫全库补查；明确启动下一维护进程才重新初始化，不在运行内隐式重读 |
| 候选/提升/事件 | 三阶段各30秒；每文件/日期前后检查取消、保存进度；候选随生成的逐文件审计计入候选预算，独立候选总审计另计30秒；事件阶段含26个新物化、26次真实检查运行及156项结果；正式检查阶段每日期完整核验一次，共26次 | 启动、核验、保存结果、运行日志及状态查回均计时；182仅为物化/检查事件数。超时保存进度并停止领取下一日期；安全取消与续跑先经隔离验证，不靠无限重试或自行放宽预算 |
| 日常checks/readiness | 最近最多10日；每资产1次批量最新物化查询；原依据最多1层，父物化集合1次、原检查/最新检查集合1次、原Raw集合1次，最多4次证据集合查询，不逐日查库；原检查最多60项，最新检查最多60项，父物化/Raw各最多10项 | 查询截断、超限、错绑、缺项即失败；不深扫历史事件；10日窗口预算30秒 |
| 新物化保存/找回 | 仅固定26日，逐日追加前最多1次最新物化查询，确实追加后再1次；每次limit=1，正常最多52次/52条。本Plan等价记录只查1次、追加0条；新target保存成功后才准备检查run_id | 该数仅是本子步骤，不冒充检查任务或最后验收总查询数。全部计入原事件/续查30秒；失败停止，不轮询、不广搜 |
| 最后验收的证据查询 | 26日最多3批、每批沿用本表checks/readiness最多4次证据集合查询，共最多12次，包含26个新物化和156项新检查的读回；额外3日分别按Raw/Silver资产查询，每资产1次、合计最多2次，按日期分别取各自最新1条，合计最多6条目标记录。使用现有只读存储连接按partition选最新storage_id，不以3日期混合历史的总limit=3代替。不读取额外3日检查历史，最后合计最多14次证据查询 | 查询设返回上限并检测截断、缺项、重复或错绑；复用同批证据做新事件对账，不再额外发起一轮事件审计；超限即停 |

开发日志回归门禁按本机Dagster 1.13.26及既有单步骤、六结果成功路径核对：每次27条运行日志，26次合计702条，序列化UTF-8总量不超过2 MiB。该2 MiB是根据本轮约1.51 MB样本留余量的开发回归及正式预检预算，不是PostgreSQL表和索引物理占用。26条新物化另算，不能把702当作全阶段所有记录；失败/取消时也不为凑正常数量而补写。只在隔离测试中按26个实际run_id测量这些日志，不新增正式全历史读取或日志收集服务；正式阶段仍只按原六项读回和30秒预算执行。SDK、任务或metadata变化导致超过该预算时停止重新核对，不自行加量。

26个变更日与最后验收另加3日均已明确，正式写入仅26份Silver；其他对照只在隔离测试，不增加日期。原行读取用于零改删对账，额外3日指纹必须对照既有物化，不用现场新算指纹自证；禁止未批准完整Basic读取。上表预算含中断续查与最后验收，开发实测见§11.9.14，正式六阶段实测及结案见§11.9.18；不再标为当前待测。此前56只审计0.38秒、§11.8的4.22秒及原传递实验1.31秒仅证明各自范围，不能代替本轮实测。预检统计去重字节、原行数和所需事件；逐日进度显示日期、完成/总量及更新时间，ETA不可靠不展示。

#### 11.9.9 测试、真实核验和最后口径对账

| 硬口径 | 必须覆盖的证据与正反例 |
| --- | --- |
| 固定56代码、701键、26文件 | Plan逐代码/日期比对§11.9.2；56以外代码即使最新Basic为L也不能加入；非开市、上市前、10月19日起均拒绝；数量相同但换一组键也失败 |
| 只新增，所有旧行不变 | 小样本独立字面expected证明保留512390的18日自动补值及9月10、11、14日Raw/Silver人工修正，不混用两类原依据；其他D/P/旧Basic缺日期的已验收行也保留；任何删除、原值变化、未批准新增、同键异值均失败；不调用原全文件重筛writer |
| 新行确有源 | 真实合同Raw字段/类型依据、独立字面预期；因子和贴水率精确保留，合法NULL通过；缺源行、重复、日期/数值非法、Basic资格不符、冻结后内容漂移均失败，不造值不修改Raw |
| 原验收有效 | 原6项成功且正确绑定才通过；缺项、错绑、后续失败、Raw/Basic/原行变化都阻断；只改mtime但内容相同可通过；新检查不能自证原验收 |
| 新旧检查一致 | 带完成记录先进入新路径；普通文件和未改动旧512390文件保持原行为；对真实6项检查的隔离执行和readiness给相同结果，窗口混合文件也一致；新metadata所有消费者同步 |
| 六项合并、一次核验 | 真实合并执行的隔离测试断言完整核验入口只调用一次、所需Basic依据不被六项重复读取；六个check key/名称/blocking集合精确不变。逐项故障仍失败，正常变化仍通过；单项选择有效，不保留六套旧定义并行注册。任一项失败时整体检查和本次运行失败、日期不ready且停止，不能将正常分项涂红或只因步骤返回就算成功 |
| 真实检查追加记录 | 旧结果存在时更新文件、追加新物化、只执行合并检查，六项新结果均属于实际新run_id并绑定新target，旧事件/检查均未修改；用9月3日同类旧记录复现，不靠伪造run_id或辅助资产完成测试。写文件资产必须可被测试证明未调用 |
| 可恢复且无额外写入 | replace前中断、replace后进度前中断；新物化追加成功但target未保存时按本资产/日期最新1条找回，追加0条；target保存失败时检查UUID准备和运行均为0。首次追加、等价复用、查无/另一Plan/更新target停止均核对查询次数及limit=1；检查事件后进度前中断另按run_id查回。部分检查失败、重复执行不重发；只读命令正式写入0，候选命令事件/正式写入0 |
| 有界且可审计 | 10日批量查询数量、29日/58文件/16 MiB及14次最后证据查询上限，额外3日无候选/检查运行/事件；其他对照只用隔离样本。明确初始化之后，检查后3批readiness及需要Basic的续查复用同一内容、完整Basic读取0，缺失/错快照/错内容均停止，日常默认行为不变；仅查运行状态不要求Basic。各阶段30秒、256MiB/无spill；初始化限本次明确批准的两对，额外全局读取仍拒绝，不使用历史批准扩大权限 |
| 保留正常规则 | 普通writer仍拒绝覆盖，缺真实应有因子仍阻断；删除的512390生成模块不恢复；asset/job/sensor/分区/源合同版本不变 |

新单元和隔离集成使用独立小样本及真实生产者合同，不用待测代码生成expected；故意坏输入单独标明。至少通过一次真实生产者格式的小链路验证及正式已有文件/原证据的有界只读核对，再讨论候选。测试范围包括writer/checks/history/readiness/sensor/bootstrap必要回归、定义和静态治理，不为此跑全历史或正式job。

最后正式验收只读29日、最多58个Raw/Silver文件，沿用§11.9.8的独立16 MiB、30秒及最多14次证据查询预算。26个变更日完整新hash与新物化一致，原行逐字段和原指纹不变，新增701键逐字段等于冻结Raw；156项新检查全部正确绑定且真实通过，readiness按最多10日3批核对这26日，显式传入同一已核验Basic内容。10月19、20、21日只核对56代码已有的168行及既有正式物化记录中的文件指纹；该3日不运行检查、不读其检查历史、不生成候选、不重写、不登记事件。701+168=869，核对56只从各自上市日至固定10月21日完整、无上市前多余。普通文件与未改动历史文件的其他对照只在隔离测试，不额外读取正式日期。其他未触及文件以执行目标清单及写入记录证明没有写入，不扩大读取全湖来证明未改。

实际状态逐项记录：原26日验收和此前Basic读取见§11.9.10—11，开发/隔离见§11.9.14，正式重载见§11.9.15；新授权与首次执行见§11.9.17，最小修正、恢复及最终结案见§11.9.18。正式Plan、候选、文件/事件和最后验收现均已有对应真实证据，原56/26/701任务已完成；历史等待状态不能当作当前阻断，不以文档状态代替物理与新事件核验。

---

#### 11.9.10 2026-10-22前置核验记录（获批完整读取前的历史阶段）

本节保留当时尚未开发、尚待Basic完整读取批准的事实；随后已获批并完成的核验见 §11.9.11，最新设计确认和实际未完成项见 §11.9.12。

已按最多10日一批，只读查询26日原Silver、原运行绑定的六项成功检查及现有Raw记录。26日156项全部通过，全部来自各自原Silver运行且绑定正确。另核对26份Raw及26份Silver的实际字段、日期、主键、数值合同、行数和内容hash：无失败，Silver共42,900行、Raw共56,349行，52份文件合计802,735字节，1线程/256MB/无spill，文件核验0.517秒。此结果只覆盖旧文件，不包含任何候选或补后验收。

9月10、11日两条Raw物化晚于对应Silver，原因为9月12日获批修正物理文件、9月15日补登记Raw事件；[原批准记录](../../../DG_DATA_EXCEPTIONS.md)已明确记录这两个步骤。实际Raw行数2149/2150及hash匹配补登记的正式记录，Silver1650行及hash匹配原验收。本次核验仍须在Basic获准读取后，按§11.9.4第2项完成这两日的原正常合同对账；不能把事件编号晚于Silver本身当作内容变化，也不将此情况推广成任意新Raw版本均可替代原依据。

旧Basic仅一个Raw/Silver物理快照，但26日保存了20个不同引用。准备阶段必须按Raw内容hash、Silver内容hash及两条正式路径去重读取；缓存该次真实内容核验结果，并逐个核对20个引用各自的日期、可用代码数量/hash。不得仅缓存第一份引用然后跳过其他引用的合同，也不得把按引用指纹缓存误当成按实际快照去重，造成20遍完整读取。

本次需要完整核验的快照为旧版 `1b68a978cf1fdae5f457da0c899387b8130314256ee10e0636279335f39b8b44` 与最新版 `02670eabbf3993a91e5d3706006808565acd0e5a8d195dd57b89983a8b07c25f`，各自Raw/Silver共4份，分别116,508、113,155、120,495、116,661字节，合计466,819字节。单独完整读取批准尚待答复；不在等待时完整读取，不借先前的一次批准重复读取。独立证据保存在[元数据核验](/private/tmp/etf_56_completion_preflight_20261022.json)和[实际文件核验](/private/tmp/etf_56_completion_files_preflight_20261022.json)，这些临时报告不是可执行Plan或运行时输入。

本次尚未修改代码、冻结Plan、生成候选、正式提升、登记事件、重载或提交新修改。后续先完成本节未决核验，再进入对应阶段，不能将读取或原检查成功写成补齐完成。

#### 11.9.11 2026-10-22获批读取后的开发约束

本节保留当时一次完整读取及原验收的历史事实。后续不得把该次内存仍在作为当前前提；2026-10-23新维护进程、当前latest及重新核验许可按§11.9.17执行，其余原行保留、证据绑定和只读连接规则继续适用。

管理员已单独批准上述4份Basic各完整读取一次。实际按4个文件各一次读入临时内存表，Raw/Silver内容hash均匹配正式引用，两版Raw到Silver投影双向相等；20个旧引用各自的日期、可用代码数量/hash均核验通过。26日旧文件按原Basic的源对账也通过：普通日期完全相等，18日只保留原先批准且验收过的512390额外行。4份Basic后续在该次执行进程内复用，不重新完整读取或导出明细。

开发沿用§11.9.3清单，新增行及其证据审计放在 `defs/asset_guards/etf_adj_factor_history_completion.py`，与既有历史模块明确分工：旧模块保留未改动旧文件的核验；新模块供候选、正式checks和readiness共用指定追加的完整核验，复用原合同函数，不恢复生成补值。这样不把377行的旧核验继续堆入完整Plan、存储读取、候选和追加审计；不是第二套数据生成规则。维护执行仍放在已列出的bootstrap模块及CLI中。

明确以下实现细节，防止开发时再次扩大或误拦：

1. §11.9.2整份代码/上市日期/新增键清单的规范化hash为 `b42c991cbe1711316c48ad0782e9cb21d4b3944967013aa01c5288481400f76b`。在现有run contract只保存这一个已确认范围的hash，Plan内保存完整清单并对照；不另建可扩大的代码配置，也不允许CLI逐项传入新代码、日期。
2. Basic按实际快照内容缓存原审计结果，再逐个校验引用的日期和资格数量；checks/readiness复用同一缓存方式。不得把20个引用当成20个独立文件重复完整读取。当前执行可复用本次已经完整核验、仍留在内存的结果；不能把临时JSON报告当作未经校验的运行时放行名单。
3. 新物化第一次登记时，其六项检查尚不存在。检查执行必须先核对原验收及完整文件事实，再产生本次检查结果，不能要求“本次检查已经成功”才允许执行自己。readiness则必须额外核对最新六项均绑定当前新物化且通过；未齐或失败都不ready，不回退旧成功。两者对文件事实的判断完全共用。
4. 只读Plan/候选阶段使用现有正式存储配置，数据库连接强制只读，仅做有界SELECT，不初始化Dagster instance、不建表、不升级。正式事件登记仍单独批准后才允许通过现有Dagster写入接口进行。本次不新增环境变量、数据库配置或通用存储服务。

审计证据见[四份Basic及原源对账](/private/tmp/etf_56_basic_once_20261022.json)。原只读SQL差异查询有两次语法修正，均无写入；修正后的26日源对账复用已读取Basic内存表耗时0.624秒，这只是该段重查耗时，不冒充四份读取、新生产实现或整阶段性能验收。新代码、候选与正式执行仍须分别验收。

#### 11.9.12 已确认的检查合并、真实运行与追加记录

**开发时确认范围与状态：** 管理员确认“合并执行、保留六项结果”并同意26日文件补齐后按日真实检查、追加新记录；2026-10-23进入开发，合并检查、内存传递及独立维护阶段接通，隔离验收见§11.9.14。4份Basic获批读取、20旧引用及26日原核验历史不变；当时尚无正式候选/提升/新事件，开发本身不构成正式操作批准。随后正式授权、执行与当前结案见§11.9.17—§11.9.18。

**开发前已核实的现状（下列独立六次计算为开发前代码，当前实现见§11.9.14）：**

- `defs/checks/etf_daily_checks.py` 的因子六项均为独立 `@dg.asset_check`，且均为blocking；它们不是六个job。对带本节完成记录的文件，每项会分别调用完整审计并创建Basic缓存，尚未共用一次计算。
- `defs/jobs/etf_daily.py` 的既有因子job选择文件writer与全部检查，不能整段运行它完成本任务；仅选择检查的API已核对，正确日期传递及实际不调用writer仍待隔离验证。旧历史测试借助无I/O辅助资产取得日期上下文，不能拿它证明本次真正的仅检查运行已通过；本次不增加这类辅助资产。
- 安装版本的 `report_runless_asset_event` 保存检查时使用空run_id；正式表按 `(asset_key, check_name, run_id, partition)` 判重。9月3日已有6条空run_id旧检查，隔离真实SDK复现了直接新增同名同日检查失败。限制不在Parquet更新，也不表示其他25日存在同类冲突。
- `asset_guards/etf_adj_factor_history_completion.py` 按旧检查编号、旧target和原运行核对原验收。直接覆盖旧检查会破坏这条依据；正式Parquet按已审核候选替换，新文件的Dagster物化记录与新检查结果追加，旧物化/旧检查修改0、删除0。不保留旧Parquet副本，不把“保留旧记录”写成“原Parquet不改”。

上轮旧29项历史回归、新14项隔离测试及静态检查通过，只覆盖原有/部分实现和重复登记失败的反例，不能证明下面的新合并执行、正确日期、恢复或性能已通过。

**已选方案及实现位置：**

| 项目 | 已确认的做法 | 实现及影响边界 |
| --- | --- | --- |
| 合并执行 | 因子一次核验产生六项结果，保留现有六个check key、名称、分区及blocking/ERROR | 在 `defs/checks/etf_daily_checks.py` 用Dagster原生 `multi_asset_check` 合并，内部执行定义名为 `silver_etf_adj_factor_checks`，不是新增check key或job；旧六套独立定义退出，不保留并行注册或别名重复注册 |
| 复用计算 | 读取/核验与结果构造分开，先得到一份 `EtfDailySilverFileAudit`，再按规则生成各项结果；不能在结果循环里调用完整核验 | 复用 `audit_etf_daily_silver_partition`、现有规则及 `build_check_metadata`；普通、§11.8历史与本节完成文件保持原判断语义。配置 `can_subset=True` 保留单项选择，按选择准备必要输入；结果函数不读库/文件 |
| 实际运行 | 26日各一次真实检查运行，每次只执行合并步骤；新结果使用Dagster实际run_id | 维护流程仍在已列出的 `defs/bootstrap/etf_adj_factor_history_completion.py` 及CLI，复用现有job的检查选择，不新增永久job/sensor，不以整段job重写文件 |
| 原消费者 | catalog、历史验收、readiness继续读取原六项结果，六项均通过且正确绑定才ready | 本次合并不迁移为单一check、不改六项规则或覆盖政策；直接引用旧独立执行定义的测试/选择调用方同步到新合并定义，不改其他数据集 |

**已确认：分项判断保持原规则，任一失败则整体失败。** 普通文件按下表准备选中项所需输入的并集；分别保存Silver、Raw和Basic读取/核验错误，不能因Raw或Basic不可用而跳过仍可进行的Silver判断。现有 `audit_etf_daily_silver_partition` 在完整模式下遇Raw缺失会提前返回，不能不作调整就把该返回分发给六项。历史批准文件及本次追加文件仍核对原有完整依据，不借下面的普通分项依赖削弱原历史审计。

| 原检查 | 普通文件需要的输入 | 无关输入出错时的处理 |
| --- | --- | --- |
| contract | Silver、本日物化metadata | 不因Raw文件缺失或Basic文件不可用而跳过Silver自身判断 |
| source_filter | Silver、该文件引用的Basic | Raw文件缺失不替代本项实际判断 |
| source_parity | Raw、Silver、该文件引用的Basic | 任一必需输入不可用，本项失败并说明来源 |
| key_integrity | Silver | 不依赖Raw/Basic读取；继续核对自身主键 |
| domain | Silver | 不依赖Raw/Basic读取；继续核对自身数值 |
| coverage | Raw、Silver、该文件引用的Basic | 任一必需输入不可用，本项失败并说明来源 |

结果构造函数只消费已取得的结果和各项错误，不查询文件/数据库；每条 `AssetCheckResult` 明确原asset key和check name，保留blocking/ERROR及实际失败规则、数量和样本。整体通过条件为六项结果齐全且全部 `passed=True`；任一失败则整体失败、日期不ready且不领取下一日期。各项可判定的真实结果先全部产出，由Dagster现有blocking/ERROR失败处理结束本次失败运行；不得在首个普通分项失败时自行提前抛异常而漏掉其余可判定结果。公共输入不可读取或其他异常导致缺项时，同样不得报整体成功。单项选择只证明选中项的结果，不能冒充完整六项新验收已完成。

验收增加两类独立预期：以字面六个布尔值逐项构造“仅该项失败”共六例，证明整体均失败、六项全通过才成功；以正常Silver/Basic但Raw缺失的真实合同小样本证明四项仍按原规则通过、源对账和覆盖失败，整体运行失败。还须对Basic不可用、Silver不可读、部分选择及正常输入作对照，保证不扩大读取、不错报其他分项。仅检查 `readiness=False` 不够，还须验证真实运行失败、六项各自结果与绑定正确。

已用CodeGraph explore/impact，并直接核对检查构造、因子job、catalog、历史核验、readiness和现有测试。上述合并影响正常因子检查和本次历史检查的执行组织；ETF日线/Raw共享代码的行为须回归保持，不新增跨工程依赖、存储表、配置或缓存服务。

**执行顺序（正式阶段另行批准）：**

1. 按既有阶段生成并审核候选；仅为固定26份正式文件各加入批准缺行，读回确认完整hash/计数与候选一致。所有原有行零改动、零删除。
2. 只为已读回一致的日期按§11.9.7先查询最新1条物化；本Plan等价记录直接复用，仅仍为冻结原物化时才首次追加，内嵌冻结Plan、原验收及新增依据。追加后限定读回实际新target，原子保存成功才准备检查运行编号；仅表示文件已更新，不表示已通过检查。
3. 从现有因子job只选择六项检查、资产选择为空，按该日执行一次合并检查；不能触发任何writer、Tushare、其他资产或自动任务。一次核验得到六项真实结果；每项都对应本日新target，运行和结果由Dagster保存，不直接INSERT/UPDATE正式库，不手工补写检查或伪造run_id。
4. 六项齐全、全部通过、绑定正确且文件仍一致后，该日才完成；六项任一失败则整体检查及本次运行失败、该日不ready并停止，缺项/未判定也不得通过。各项真实结果保留，不将正常项改为失败，不将失败项改为通过。正常成功目标是26个新物化、156项检查结果，另有26次运行及其日志，182不是全部event log总数。

**中断、取消和续跑：** 沿用 §11.9.7 每日记录实际文件hash、新物化和运行编号；编号先保存后创建的低成本处理已获确认，详细顺序和状态表见本节末尾。尚未启动的日期才可领取；已成功且Plan/hash/target一致时复用；已经开始、失联或只保存部分结果时，先按已保存编号有界查回，不启动第二次、不补造缺项。运行中的安全取消和终态确认必须先隔离验证；未确认终态不推进后一天。真实失败不自动重试转绿，不回滚已提升文件、不改旧事件。续跑保留各阶段30秒预算，不把无限重试当恢复办法。

**性能、读取与日志门禁：** 正式检查阶段每日期完整核验入口最多一次，26日合计26次，不是156次；这不包含既有候选生成/审计及最后验收，不能把全流程说成只读26次。六项内、26次运行之间、最后验收和需要Basic的续查均复用同一已核验内容，不因阶段切换重复全局读取。原小样本传递和本轮维护接入已分别验证，26日生命周期与成本的本轮隔离证据见§11.9.14；现有一次完整读取批准不重复使用，不能以重新读取或导出明细绕过。

先在隔离环境测固定一天，分别报告启动、Raw/Silver/Basic读取及次数、核验、结果保存、运行日志条数/字节、完整总耗时；对照证明仅一次完整核验，而非只减少函数外层调用。再评估固定26日正常执行、状态查回、中断继续和最后验收；一天的结果仅是样本，不冒充26日实测。事件阶段30秒包括运行及日志成本，不擅自放宽，不新增并发或调度设施；额外运行日志的数量/字节上限须在测量后落回本节并核对，未形成有界成本或超预算不得正式执行，不能把182当日志预算。

**测试和真实边界验收：** 开发前先按真实Raw/Silver/metadata合同构造独立小样本。至少验证：一次核验产生原六项结果；各类坏输入仍阻断而合法变化不过度拦截；单项选择有效；普通/旧历史/新完成文件及readiness一致；在已有空run_id旧检查的同类场景，更新文件、追加物化、真正仅检查运行能追加六项正确绑定的新结果且旧记录未变；writer未调用、无辅助资产；中断后查回、重复执行复用、失败不自动重试；越界代码/日期、查询超量、超时和未批准完整Basic读取均拒绝。只检查API签名、手工填入新run_id、辅助资产或直接注入结果的测试均不能替代真实运行验收。现行完整调用、DAGSTER_HOME、Plan/候选路径与读写边界见§11.9.17，重载结果见§11.9.15；管理员已授权原范围按各阶段内部验收及独立候选总审计后推进，不重复请求原范围批准。

**已有数量约束与本次决定：** [模板§10A](../templates/dagster-dataset-onboarding-template.html#human-readable)禁止“为了机器方便拆出大量细碎check”，并要求合并后说明失败规则、数量和样本；Git记录表明该条已在2026-06-26存在。[性能规范§3](dagster-data-pipeline-performance-governance.md#3-开发前性能设计清单)自2026-06-21已有日期×资产×检查数量的读取模型和事件写入预算要求。当前两份文件没有统一规定每资产最多N个check，也未在这两份中找到“因PG膨胀限制为某个数量”的原文；不能因此忽略明确的数量和成本要求。本次按管理员选择保留六项结果，只消除重复核验，不宣称减少PG记录或解决历史膨胀，不顺手合成单一check、清理日志或修改模板。

**已确认：Basic复用的具体做法（2026-10-23，代码与隔离验收已完成，正式执行结果见§11.9.18）。**

1. 本轮按§11.9.17在新维护进程先完整核验两对限定Raw/Silver Basic，再形成`PreparedCompletionBasic`；维护入口 `defs/bootstrap/etf_adj_factor_history_completion.py` 在该进程持有旧版和冻结新版两份已核验Silver内存行及其引用，串行执行26次真实检查，并向最后26日readiness的3个窗口、续查中确实需要文件和Basic资格核验的环节显式提供同一份内容。对应Raw/Silver内容hash与已核验记录仍保留作依据，初始化之后不再次完整读取Basic。不是用只有指纹/计数的临时JSON报告恢复完整内容。
2. 每次检查、每批最后验收保留独立DuckDB连接。检查通过仅内存的resource传入已核验行，最后验收及需要Basic的续查通过内部参数传递；均显式交给共用核验函数，并使用现有 `CompletionBasicCache.seed(reference, rows)` 放入各自连接的临时表。调用`get()`前必需的内容及引用必须已seed；缺失、错内容或引用不在已核验集合时停止，不能进入其完整Parquet读取分支。运行/批次结束关闭自己的连接，不跨运行借用一条可能被关闭的连接，不新增永久缓存服务或落盘文件。普通日常任务和日常readiness没有本次维护输入，继续原有读取规则；维护入口必须先检查输入，不能把维护缺失输入降成普通调用绕过停止条件。
3. 物理内容仍按Raw/Silver正式路径及两种内容hash区分，不能只用“最新Basic”或日期作为缓存身份；同一物理快照的不同日期引用，逐个核对日期、可用代码数量/hash，不能只验证第一份引用。每次seed须核对Silver内容hash；不同引用共享内容，不共享未经核验的日期资格结论。
4. 管理员2026-10-23已明确允许新维护进程重新核验本任务两对Basic；此前“只能寻找旧持有进程、重读另批”的前提被替代，实际文件和字节见§11.9.17。退出时保留已有checkpoint；下次明确维护启动可以重新预检、完整核验限定两对后续查，不寻找旧Basic进程，不导出或新建缓存服务。运行中内存丢失、错引用/错内容仍停止，不隐式回退完整读取；Plan冻结后的引用变化仍按原失效规则核对，不顺手换版本或扩大快照数。
5. 隔离验证需证明同一批次连续真实运行确实收到同一份已核验内容，但各有独立连接，Basic Parquet读取不会按六项或26日增长；每个引用仍被核对。计入每次内容指纹复核、临时表导入及内存成本，不能把内存操作当作零开销。Raw/Silver每日输入也应在单次核验内复用，实测文件打开、扫描/载入、SQL及缓存未命中的次数，不能只断言完整核验入口调用一次。内存丢失、错快照、错日期引用和缺少传入内容均应停止，不能触发隐式全局读取。小样本机制见§11.9.13；维护代码、其他失败情况及26日生命周期和性能的隔离验收已完成，见§11.9.14。本轮新进程实际初始化及正式调用另按§11.9.17记录，不能以隔离测试代替。
6. 实现覆盖维护入口、`asset_guards/etf_adj_factor_history_completion.py`的共用完成审计、合并检查入口，以及`etf_daily_lake_readiness.py:_batch_readiness`和`batch_etf_adj_factor_silver_lake_readiness`之间的内部传递。后两者增加显式可选的已核验内容输入：提供时在当前连接建立缓存并seed，默认不传时保持日常行为。维护入口在调用前必须拒绝缺少必需内容，再传入全部所需内容；最后验收不能直接沿用现有每批空缓存路径。仅按运行编号查询状态、不读取文件或判断Basic资格的步骤，不额外要求Basic仍在内存；发现需要文件核验时才进入上述检查。
7. 增加隔离测试：真实检查结束后，最后3个readiness窗口及需要Basic的续查仍接收同一份内容，Basic完整读取总数保持0；分别在检查、最后验收、必要续查中验证缺失、错快照和错内容会停止，不能被普通日常默认分支掩盖。另用正常日常调用证明既有读取/失败规则不变，仅查询运行状态不因Basic缺失而被误拦。这些新增测试已按§11.9.14完成；§11.9.13的小样本实验仅保留原范围，不能代替这些测试或正式环境验收。

**本步开发的内部接口与资源核对（2026-10-23，沿用已确认的内存复用方案）：** `PreparedCompletionBasic.from_cache(cache)`仅提取当前进程中已核验的内存内容及逐日期引用，不读文件；`require_prepared_basic(value)`拒绝缺失/错类型；`seed_cache(connection, lake_root, references)`复核必需引用和内容后返回禁止完整读取的`CompletionBasicCache`。维护入口、合并检查和最后验收使用同一个对象，不把它序列化为运行配置或事件metadata。

| 内部传递或resource | 来源、默认值与消费者 | 生效和失败规则 | 读写与隔离验收 |
| --- | --- | --- | --- |
| `prepared_basic` | 合并因子检查内嵌`ResourceDefinition.hardcoded_resource(None)`，维护运行用同名resource传入已核验对象；只供本次检查及维护函数，来自进程内存，无env、数据库或文件配置，无凭据 | 日常默认None；维护入口必须先拒绝缺失。为识别resource传递丢失，在该次真实运行现有tags中复用`goldenshare/history_completion`保存本Plan hash；合并检查见此运行身份必须require内容，并核对新物化内Plan hash一致，缺失时不得进入日常读取分支。此tag由维护代码填写，不是运营开关，不包含Basic明细 | 资源初始化不访问外部系统、不写文件或事件，不使正常Definitions加载失败；在执行时报告错误。真实隔离运行验证覆盖传递丢失、错Plan及普通日常对照 |
| 维护阶段的DuckDB resource | 仍用现有`duckdb`资源key及`DuckDBResource`接口，仅维护入口提供受控连接；临时目录由既有staging执行目录确定，固定1线程/256MiB/无spill，不新增可调CLI、env或持久配置 | 复用`connect_configured_duckdb(..., temp_policy='existing_no_spill')`，扩展自动安装/加载关闭；目录/挂载/预算不符立即停止，不修改共享resource默认值，不影响其他资产 | 每次连接独立关闭；只在本阶段已获批准的路径中读写。测试目录全部在`/private/tmp`，分别断言实际设置与路径，运行检查阶段不调用writer |

合并执行通过现有`multi_asset_check(resource_defs=..., can_subset=True)`承载，不新增永久job、资产或配置。每个`AssetCheckSpec`显式绑定现因子资产对象及同一分区定义。检查运行的tag仅保存本Plan运行身份，不参与业务Plan hash，不放物化编号或Basic内容；查回既有run时也必须核对该身份。CLI每次只调用一个阶段；需要Basic的调用只接受本轮已初始化维护进程显式传入上述对象，不从JSON报告或CLI路径恢复内容。下次明确启动重新初始化按§11.9.17办理，运行中不偷偷重读。

**本步测试执行边界：** 使用现有orchestrator `.venv`、临时测试目录和隔离Dagster实例，不安装依赖、不使用`PYTHONPATH`、不读正式Lake/instance/凭据或原Basic会话。ETF专项没有现成保护启动器时，在`/private/tmp`使用当前任务负责的临时测试启动器：禁网络和正式路径访问，将测试的默认DuckDB临时目录绑定到本次临时目录，并保持受控连接实际设置；测试完成后删除该可执行文件、保留摘要。已有受保护资产治理测试继续使用其现有启动器，不另写一套替代。替换仅覆盖测试资源边界，不替代所声称验收的文件、schema、SQL、真实运行或事件存储链路。 完整26日隔离样本的原Silver为42,900行、新增701行；Raw容量按既有核验56,349行构造，差额12,748行使用明确不在两份Basic中的人工代码，验证这些原始额外行不会进入候选。仍为相同26日期、56个新增代码和701键，不读取正式资源；3个完整日另保留各56条目标行。合成文件压缩大小和临时SQLite不冒充正式Parquet或PostgreSQL成本。

**Basic复用的缺点与取舍（已确认，隔离成本见§11.9.14，正式成本逐步记录）。**

| 代价 | 对本任务的实际影响 | 建议保留的边界 |
| --- | --- | --- |
| 内存随本轮维护进程存在 | 进程退出后，逐日进度只说明做到哪里，不能恢复Basic行；下一次明确维护启动按§11.9.17重新预检及加载，再按checkpoint续查 | 不追旧Basic进程，不因方便恢复而增加Basic持久文件、跨进程缓存或后台服务 |
| 仍有计算和内存导入 | 每次独立连接的 `seed()` 仍会复核内容hash、JSON转换、建临时表和复制行；各日期资格仍需核对 | 节省的是重复完整文件读取，不宣称零计算；这些开销计入实测 |
| 运行初始化及日志仍在 | 26次真实Dagster运行及记录写入不会消失，且不等于额外启动26个操作系统进程 | 不承诺六倍提速或已满足30秒，不自行加并发来抵消 |
| 内存占用高于文件字节数 | Python行、JSON及DuckDB临时表可能同时存在，不能用压缩Parquet大小当作实际内存 | 本次只有两份有限Silver Basic内容，仍需测峰值；不推广到大型快照 |
| 冻结资料不自动追随新版 | 同批可保持一致，但相关上市日/状态后续又修正时，不能自动混入后半批 | 沿用原Plan引用和失效规则；不加入无关ETF，不自动换版本 |
| 隔离样本不能代替正式运行 | §11.9.13实验与§11.9.14合成样本只证明各自边界；随后真实Basic初始化及26日运行已按§11.9.17—18完成 | 正式结果单独列证据；运行中丢缓存仍不能悄悄完整读取 |

管理员已同意针对本次有限批次使用内存复用，并于2026-10-23明确允许新维护进程重新核验限定Basic；运行内严格复用，退出保留checkpoint、下一次明确启动重新初始化，不新增持久设施。代码接入及隔离验收见§11.9.14；正式初始化与成本逐步按§11.9.17记录，不用隔离数据冒充。

**已确认：少见运行中断的最小处理（设计已确认，当前实现与隔离证据见§11.9.14）。**

管理员明确同意把“创建运行后、编号尚未保存前退出”按低频异常处理，不开发复杂恢复。目前没有历史事故统计，不给数值概率；以下只复用已有逐日进度、原子保存和Dagster现成参数，不新增表、服务、配置、扫描全历史、自动重试或专门接续既存运行的入口。

**实现位置与进度内容：** 在既有 `defs/bootstrap/etf_adj_factor_history_completion.py` 的正式检查执行部分及已列出的CLI中实现；复用 `bootstrap/etf_daily_bootstrap_plan.py:atomic_write_json`。只在原staging执行目录的逐日进度增加拟用运行编号及其本日身份，不新增独立状态文件体系。

| 每日期必须保存/核对的内容 | 用途 |
| --- | --- |
| 既有Plan内容hash、因子asset key、交易日 | 拒绝误用另一Plan、其他资产或日期的进度 |
| 预期完整文件hash、新物化target | 确认本次检查针对已审核且已读回的同一份新文件 |
| 该日唯一的拟用run_id及已有更新时间 | 在创建前即可精确查回；编号不是已创建的证明，实际状态以Dagster查询为准 |

编号只用于执行进度及对应真实运行，不进入业务Plan内容hash、业务完成身份或业务run key，不把物化编号放入正式run config。编号及身份写入失败即停止，不能调用Dagster；不得用一个新UUID覆盖原进度中的编号。

**固定调用顺序：**

1. 前提是§11.9.7的新物化真实target已核对并原子保存；若尚未保存，先按该节有界查回，不准备UUID。随后读取并核对本日已有检查进度。已有编号则沿用；没有编号才生成一次UUID，与本日身份一起原子保存。任一原子保存失败或内容不匹配时，实际运行创建数必须为0。
2. 使用现有因子job的仅检查子集，六项全选、资产选择为空。首次新执行中，本次刚保存且确认未使用的编号可以首次调用；续跑读取的旧编号必须先按下表查询，不能直接当作未运行。
3. 首次调用使用 `检查子任务.execute_in_process(instance=指定正式实例, partition_key=本交易日, run_id=已保存编号, ...)`，其余资源及日期选择沿用已经核验的本任务入口。`instance`不能省略而落入临时实例；不得执行整段包含writer的job，不改用队列、后台提交或新的恢复入口。
4. Dagster通过内部 `create_run_for_job(run_id=该编号)` 正常创建同编号的真实运行并执行；不用UUID直接补写检查结果，不假称已有运行。本机1.13.26当前签名和内部调用链已只读核对，真实仅检查运行已按§11.9.14隔离验收；不代表正式运行已执行。
5. 执行成功后，核对六项齐全、全部通过、属于该真实run_id、绑定本日新target，且文件hash仍与审核依据一致，再保存该日完成进度。函数抛错、检查失败或证据不全就保留已保存编号并停止，不生成替代编号、不继续下一日期。可判定的六项结果按前述规则保存，不能吞异常伪造成功。

**检查运行中断后只按已保存编号查回：** 使用 `get_run_by_id(已保存编号)`；记录存在时先核对本日身份、任务与日期。成功检查的事件读回仍限定本资产、日期、run_id及六项，不扫描全运行历史。新物化写入中断不适用此编号表，按§11.9.7先找回并保存target。以下状态表同时适用于检查异常返回后与进程重启后的查回。

| 精确查回的结果 | 本任务处理 |
| --- | --- |
| `SUCCESS`且六项、target、hash及本日身份全部一致 | 复用结果，只补记完成进度；不创建运行、不改文件或旧事件 |
| `SUCCESS`但六项缺失、绑定错误、hash或身份不一致 | 停止，不能只看运行成功就完成 |
| `NOT_STARTED`，运行已创建但尚未开始 | 停下人工确认，不接入 `execute_run` 续执行 |
| `QUEUED`、`STARTING`、`STARTED`、`CANCELING` | 停止，不启动第二次；不自动取消或改状态 |
| `FAILURE`、`CANCELED`、部分结果或未知状态 | 停止，不自动重试、不手工补齐结果或改成成功 |
| 续跑旧编号查无；已确认原维护进程退出且同日无在途运行 | 允许用原编号首次创建，仍须满足原正式执行及文件/Plan门槛；不换编号 |
| 续跑旧编号查无；原进程仍在或不能确认已退出 | 停止人工确认，不能因查无就在旧进程可能随后创建时再次启动 |
| 旧进度没有预先保存编号，无法确认此前是否创建 | 停止人工核对固定日期，不自动生成编号、不扩展查询全部历史 |

`execute_in_process`总会尝试创建运行，不能把一个已存在的编号传回去当作“接着跑”。若出现 `DagsterRunAlreadyExists`，只按同编号查回并套用上表，不换新号、不覆盖运行、不删除重建。对原进程是否退出或旧进度归属无法确认时，保守停止即可；不为此增加进程监控、租约或自动恢复系统。正常查回、取消确认及结果核对仍计入既有30秒阶段/续查预算。

**最小隔离测试：** 先覆盖§11.9.7的新物化追加成功但target未保存、target保存失败及等价复用，证明不重发物化、不提前准备检查UUID。检查部分再验证启动前保存失败不调用Dagster；首次保存后未调用即退出时沿用编号；运行已创建但进度未再更新时能按编号查回；成功但完成进度未写时复用且创建次数不增；失败/未开始/仍运行时停止；查无但旧进程仍在或不明时不创建；重复编号异常不换新号。结合前述真实检查小链路核对六项与target/hash，不能只mock最终状态宣称真实运行通过。不为罕见情况增加自动接续或无限重试测试体系。

本节Basic内存复用及其代价、低成本中断处理、文件/记录修正、分项规则和整体失败规则，以及最后验收传递、新物化找回和29日只读边界均已由管理员确认，不再列为待拍板方案。开发及全阶段隔离验收见§11.9.14；§11.9.13仍只记录当时临时机制实验，不扩大其结论。正式重载与读回见§11.9.15，新的Basic初始化与原任务逐阶段正式结果见§11.9.17。

#### 11.9.13 2026-10-23获准的隔离验证：Basic跨运行内存传递

**目标与范围：** 当时仅验证同一维护进程的现成Python对象能否传入连续两次真实Dagster检查，以及缺失内容时能否在读取前拒绝；这不是正式实现接通或整个补数链路验收。该次实验授权不包含Basic方案整体确认、正式资源读取或写入；管理员随后已整体确认Basic方案，现行设计见§11.9.12，不能据后续确认扩大本实验结论或正式执行权限。

**合同与独立样本：** 依据 `assets/etf_basic.py` 的真实Silver生产者及 `run_contracts/etf_basic.py`，14字段保持不变，`setup_date/list_date`为Python `date`，`mgt_fee`为对应 `DECIMAL(12,6)` 的 `Decimal`，不是Raw字符串/浮点样本。两份内容各2行，两个日期固定为2026-09-03、09-04；状态和上市日均为刻意构造的实验值，不代表真实证券资料。以字面代码集合及日期资格构造独立预期，不调用被测分类函数生成expected；内容hash构造仅用于合法输入引用，不据此声称hash算法本身已独立验收。规范路径使用临时根拼出但不创建文件，Raw/Silver真实文件成对核验不在本步范围。

**最小执行方式：** 临时脚本位于 `/private/tmp`，从orchestrator现有 `.venv` 执行，不接入active Definitions。使用 `ResourceDefinition.hardcoded_resource` 传入同一内存对象；实验asset只代表被检查的目标，其writer若被调用立即失败，不增加无关辅助资产提供日期上下文。临时检查任务只选择检查、资产选择为空，使用显式临时实例和两个固定日期；不得调用正式六项检查或正式writer。本步临时检查验证Basic传递，不宣称六项正式业务规则通过。

**正反例与观测：**

1. 两次正常运行必须成功、run_id不同、日期正确，收到的内存对象与传入对象为同一对象；每次连接独立且运行后关闭，不能跨连接共用TEMP表。
2. 各连接分别创建现有 `CompletionBasicCache`，先seed所需样本再get；独立核对完整14字段内容/类型及两个日期引用的字面资格预期。get返回完整临时表，不把它误当成已过滤的资格清单。
3. 第三次真实运行传入缺失内容，由实验适配入口在创建缓存/get之前明确拒绝，运行必须失败，get和完整读取尝试均为0；不能用缺失时重新读文件兜底。
4. 同时用完整读取函数哨兵及本实验连接SQL记录核对：前两次和缺失负例不得调用Basic完整文件核验、不得出现Parquet/CSV等文件读取SQL。另用不seed的缓存直接get作为负向对照，必须触发完整读取尝试并在任何文件读取前被哨兵阻止；这证明现有缺缓存分支仍有隐式读取风险，也证明观测器能检测它。
5. 缺失拒绝属于临时实验适配器，不是对现有正式入口的修改；完整读取函数被替换为读取前哨兵，这个替换不冒充真实Basic文件集成。结果分别报告传递、seed/get、拒绝与基线对照，不以单个“通过”覆盖边界。

**隔离、预算和失败处理：** 所有Dagster实例、SQLite事件、日志和DuckDB临时目录均在 `/private/tmp`；显式禁用遥测，不读正式DAGSTER_HOME，不连接正式数据库，不读原Basic会话或正式Lake。0次Parquet生成/读取、0次Tushare、0次网络请求；仅2份×2行Basic、2日期、3次临时真实检查运行及1次缓存基线对照。复用现有受控连接helper，临时目录策略为 `existing_no_spill`、1线程/256MiB、扩展自动安装/加载关闭。完整实验及关闭/清理/写报告预算30秒，超时或断言失败即停止，不自动放大实验或安装依赖。

**产物与清理：** 只保存摘要、各例状态、计数及耗时，不导出Basic行。验证代码是当前任务负责的临时实验，结果记录后删除可执行脚本，不接正式入口；临时日志/摘要可保留供review。实验成功也只能支持方案可行性，正式资源注入、缺失守卫、原六项规则、26日成本及正式执行仍分别未验收。

**2026-10-23实测结果（本机Dagster 1.13.26）：**

| 情况 | 真实运行编号 | 结果与证据 | 本次运行耗时 |
| --- | --- | --- | --- |
| 2026-09-03正常传入 | `1e35c9fa-d461-4fcc-9531-36e13ed40050` | 成功，1项实验检查通过；收到原对象，独立连接已关闭；2份内容和本日引用核对通过 | 312.721毫秒 |
| 2026-09-04正常传入 | `8aae88e1-8e9b-40a1-9ddf-550ad54e133f` | 成功，1项实验检查通过；仍是同一对象，使用另一个连接并已关闭；另一天的引用分别核对通过 | 21.536毫秒 |
| 2026-09-04传入内容缺失 | `4a8055bf-414b-4613-b914-7c101192af88` | 按预期失败，原因`prepared_basic_missing_stop_before_cache_or_read`；连接创建0、get调用0、完整读取尝试0、成功检查结果0 | 11.165毫秒 |

前两次共4次`get`，完整14字段及DATE/DECIMAL类型、独立字面资格预期均通过；共12条被监测SQL，均为内存临时表创建和查询，无文件扫描SQL。两次检查各用1个独立连接，共2个；另1个连接仅用于未seed基线对照，合计3个且全部关闭。该对照确实触发1次`audit_etf_basic_silver_snapshot`调用，随即被读取前哨兵中止，没有实际读取Basic。正常传递及缺失负例均未进入这个完整读取函数。`get`计数来自脚本固定调用点及缺失前后计数对照，不是正式入口的全局监测实现。

整个实验从导入前开始，含连接/实例关闭及摘要首次写入，进程末尾计时为1,310.695毫秒，未超30秒；摘要中的`elapsed_before_report_write_ms=1310.513`专指写摘要前时间，两者不混用。实验资源未写Parquet；正式路径文件打开、Parquet打开、socket连接/地址解析尝试及writer调用的计数均为0。此处的“0读取”仅指Basic/正式资源，Python代码读取和临时运行资源不在此含义内。

结果摘要为 `/private/tmp/etf-basic-memory-20261023-rvrqk2h4/result.json`，脚本SHA-256为`daea83331929b00dca5f16944bf1122e9a30d2f7f094b254cf1c66eb7352e1b4`。临时实例是内存实例，未持久保存逐条事件；标准输出日志为空，不作为验收证据。三次真实运行的状态、检查结果和失败原因均在脚本中从运行返回值断言，摘要仅保存对应结果。脚本经两份独立只读复核后执行，核对结果后删除脚本及空日志，保留摘要，不新增可执行入口。

**结论边界：** 同进程传递原对象、现有seed/get使用内存、实验适配器缺失即停三点已验证。当前正式`CompletionBasicCache.get()`在未seed时仍会读取Basic，本步没有改变这个行为；后续正式接入必须先检查传入内容，不能照搬“直接get”作为缺失处理。临时检查的日期定义使用本机API，SDK提示其为preview；不据此批准迁移正式分区或检查定义，正式接入仍须核对现行正式任务的用法。本步未证明实际Basic已跨26次运行复用、正式六项判断及失败语义、峰值内存、正式文件绑定或26日性能；未接触正式Basic、原会话、Lake、数据库或补数任务。

#### 11.9.14 2026-10-23本步开发与隔离验收

**开发结束时状态：本步开发及所列隔离验收完成，当时正式补数未执行；后续正式结案见§11.9.18。** 管理员本轮授权按LLD开发，接通合并检查、内存复用、六个独立维护阶段及低成本中断处理；不新增job、sensor、源合同、env、缓存服务、通用覆盖开关或跨工程依赖。开发在`dev-interface`，未建分支/worktree；本步代码与文档按指令提交，不暂存或覆盖其他任务修改。

**实现与硬口径对账：** 下表源文件相对`lake_console/orchestrator/src/orchestrator/`，测试相对`lake_console/orchestrator/tests/`。既有部分实现不是本轮新增的全部；本表说明最终工作区代码如何承接本节口径，不把原依据核验重复算作本轮正式读取。

| 约束 | 当前实现 | 隔离证据 |
| --- | --- | --- |
| 固定56代码、26日和701新增键；原42,900行不改不删 | `run_contracts/etf_daily.py`固定已批准范围hash及Plan；`bootstrap/etf_adj_factor_history_completion.py`各完整阶段核对42,900→43,601，正式目标只按Plan日期生成 | `test_etf_adj_factor_history_completion.py`范围替换、原值变化/删除/多余、原依据/Raw/Basic变化等反例；execution完整容量样本 |
| 新行有源，512390旧批准记录保留 | `asset_guards/etf_adj_factor_history_completion.py`把完整文件排除批准新增键后核对原指纹；新增键与Raw投影双向相等，复用旧历史身份与原检查，不生成补值 | 原2行含512390加14条字面新行、非法源/重复/缺项、合法NULL及只改mtime的既有完成回归；不以全市场最新Basic重筛原行 |
| 六项只算一次，保留各自判断；任一失败整体失败 | `checks/etf_daily_checks.py:silver_etf_adj_factor_checks`为一个`multi_asset_check`，保留原六个spec、blocking/ERROR和单项选择；纯结果函数不读文件/库 | `test_etf_adj_factor_merged_checks.py`真实仅检查运行、一次入口、六个独立失败预期、Raw坏时其余四项仍按规则判断、Basic缺失/Silver坏/单项选择；writer调用0 |
| Basic不因六项、跨日或最后验收重复完整读取 | `PreparedCompletionBasic.from_cache/seed_cache`复制并冻结已核验内容和引用；严格缓存拒绝未seed引用；维护tag缺失内容时在连接/完整读取前停止 | `test_etf_adj_factor_completion_basic_reuse.py`不可变、错内容/引用/日期、两个真实运行、三窗口及需要Basic的续查、日常默认对照；完整容量样本各阶段及续查Basic完整重读0 |
| 文件→追加物化→真实检查，不改旧事件 | bootstrap只提升已审候选；物化按最新1条首次追加/等价复用/冲突停止；真实target先保存，然后UUID先保存再创建既有job的空资产集、精确六检查子集 | `test_etf_adj_factor_completion_execution.py`旧空run_id六项仍在、真实新run与新target绑定、保存失败不启动、重复执行不新增、非成功/错Plan/后来失败拒绝 |
| 少见中断不做复杂恢复 | 原子文件提升和逐日进度；文件已替换而进度未保存时重新证明同候选后只补进度；查已存UUID不换号、不接续既存运行、不自动重试 | 完整26日提升用例第一次replace后进度保存故意失败，续跑首日replace次数不增；真实检查期间取消后本日`SUCCESS`和结果保留，下一日物化不存在。该取消是完成当前单位后停止，未冒称把Dagster运行强制变成`CANCELED` |
| 实际读写位置和预算不能绕过 | CLI只暴露独立阶段、Plan/hash及阶段确认；只接受受控DuckDB resource；staging根/祖先/叶链接在读写前拒绝；外层30秒和用户取消沿现有回调传递，Plan亦逐文件检查 | 普通默认resource拒绝、路径链接、取消前不读Plan/数据、超时/范围/查询上限、候选与进度篡改等反例；1线程/256MiB/0B spill配置实际核对 |
| 最后只核对29日，不追加检查/事件 | `audit_completion_final`给26日3窗口显式传同一内存Basic；19—21日只比56键和既有物化指纹；复用有界证据结果 | 容量样本最终58个不同Raw/Silver文件、恰58次载入、8次证据查询（上限14）、701+168=869；无额外日期或写入 |

开发与独立复核中已修正：候选总审计/提升传给共用函数的SQL必须是完整`SELECT`；成功运行的续查还要拒绝同target后来失败/未完成的最新六项；CLI和阶段共用外层30秒；Plan取消、staging链接前置、候选进度复用已有日期校验。完成专用的新增行数字段只在确有本次完成记录及新增行时输出，不给正常ETF日线/普通因子日志额外写0。未通过的夹具曾因直接改日期却未重算引用指纹被真实合同拒绝，修正的是夹具构造，未放宽合同或预期。 UUID补充用例实际验证：查无且已确认旧进程退出时沿用预存编号首次创建；通过只让一次编号查询返回查无来模拟创建前的少见时隙，随后由SDK真实抛出重复编号异常，代码只查回同一成功运行、不换号；空临时instance中最新物化查无时事件/运行/编号写入均0。这是有界异常模拟，不声称执行了真实并发或进程强杀试验。

**必要回归及隔离方式：** ETF新增/直接消费者及既有必要回归去重后307项通过，资产治理12项、检查治理6项、静态门禁113项通过，合计438项，不重复累计多次执行，也不把治理子断言再计为独立测试。合并检查、Basic、执行专项和旧完成/检查消费者最终组合104项通过；随后执行专项37项补足单日分项、整批续查及UUID罕见分支再次通过。Ruff、格式、文档完整性和本节文档—代码审计通过；文档检查不是语义验收替代。

ETF专项启动器由操作系统禁止正式路径和网络；默认测试DuckDB只在资源边界重定向到临时受控连接，实际文件、SQL、SDK、事件存储及结果绑定均真实执行。已有治理测试沿原保护启动器运行，无安装/下载、无`PYTHONPATH`。已用CodeGraph explore/impact覆盖writer、checks、job、catalog、历史核验/readiness、bootstrap和测试，当前未发现Gold、Prod、API或前端消费者；结束时同步索引，不修改架构边界。未读取正式Basic、原内存会话、正式Lake/instance或凭据，未发Tushare请求。

**完整容量样本与性能：** 同26日Raw独立断言56,349行，旧Silver42,900行、新增701行、完成43,601行；Raw中12,748条人工代码不在两份Basic，全部未进入Silver。19—21日各保留56个目标键。样本Basic字段与DATE/DECIMAL类型依真实生产者合同构造，业务expected使用字面值，不用待测分类器生成。各阶段时间为`run_stage`完整调用，包含连接、内容核对、事件/真实检查保存与正常报告写入，均低于30秒；阶段间的量测统计不冒称正式动作。

| 阶段 | 秒 | 代理采集SQL条数 | SQL中的Parquet引用次数 | 文件载入临时表次数 | 连接数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 只读Plan准备 | 0.950 | 1120 | 364 | 52 | 1 |
| 生成并逐文件审核候选 | 1.576 | 2004 | 156 | 104 | 1 |
| 独立候选总审计 | 1.103 | 1018 | 52 | 52 | 1 |
| 文件提升及读回 | 1.846 | 2188 | 260 | 104 | 1 |
| 新物化及26次真实检查 | 4.283 | 2240 | 260 | 104 | 27 |
| 26日成功结果续查复用 | 1.363 | 1174 | 208 | 52 | 1 |
| 最后29日只读验收 | 1.079 | 1080 | 58 | 58 | 4 |

SQL代理统计不包含受控连接helper内部两条设置核对；这些设置核对的耗时已计入整阶段。Parquet引用包括`DESCRIBE`等引用表达式，不能称作操作系统文件打开或全部行扫描次数。候选/提升有3组共78个不同输入/候选文件，仍只修改26个日期；这不与最后58文件上限混算。检查事件阶段52次完整审计为26次维护前校核加26次真实检查，正式六项内每日期仅一次；另有运行后文件指纹核对，不能把全阶段声称只读52次。最后验收恰58次实际载入，每份一次（29 Raw+29 Silver），总输入393,502字节；8次证据查询涵盖26日及额外3日，不计隔离测量时单独按run_id读取日志的统计操作。

固定首日2026-09-03的真实SDK调用103.404毫秒；从运行开始事件到步骤开始事件5.562毫秒（不代表调用前初始化的全部耗时）；内存Basic核对及seed 36.804毫秒；完整文件/证据核验22.121毫秒，其中Raw/Silver载入分别0.366/0.553毫秒。六项结果实际存储5.474毫秒，本run全部27条日志存储11.815毫秒；子项存在包含关系，不能相加代替整次103.404毫秒。单日完整核验1次、Raw/Silver各载入1次、Basic Parquet读取0。

26次真实运行产生702条日志，序列化1,506,927字节，通过702条/2 MiB开发回归门禁；26条新物化另计。整批成功后续查1.363秒，保持同一26个run_id、target及完成记录，新增物化/运行/日志均0；本地进度更新时间可更新。原Basic内存始终复用，完整重读0。DuckDB实际1线程/256MiB/0B spill、临时目录结束时为空；这不声称观测到操作系统级spill峰值。测试进程峰值745,848,832字节（约711.3 MiB），包括SDK、夹具和同进程其他用例，不能当成DuckDB独占或生产整体≤256MiB的证明。

**证据及正式边界：** [汇总](/private/tmp/etf_completion_development_acceptance_20261023.json)保存去重测试来源、当前源文件指纹、测量及最终样本报告路径；本节采用的[完整测量](/private/tmp/etf-completion-tests-20261023-93zwaylp/allowed/pytest/test_complete_26_file_pipeline0/full-stage-measurement.json)和[执行专项结果](/private/tmp/etf-completion-tests-20261023-lczp99au/allowed/result.json)保留。测试启动器完成后删除，仅保留摘要/日志。合成文件压缩率、临时SQLite、人工Basic规模和路径不等于正式PostgreSQL及原快照成本；未把隔离实测扩大为正式执行已通过。

**开发结束时未执行项及后续变化：** 当时正式Basic输入与调用、Plan路径、范围构造及资源调用尚未填实，因此不能回答“每一步均已可执行”；本轮开发未探查原会话，也不能假定其对象可用。该缺口记录见§11.9.16。随后§11.9.15完成代码加载，管理员再明确授权新维护进程重新核验限定Basic、核对后直接完成原任务；现行输入、调用与路径已写入§11.9.17，不再寻找旧进程或重复请求本次范围批准。正式Plan、候选、提升、新事件/检查和最后验收仍逐步记录真实结果；其他任务修改保持不动。

#### 11.9.15 2026-10-23正式代码加载

**目标与授权：** 管理员已明确批准加载当前工作区。仅对现有`orchestrator`代码location调用一次加载，不执行Plan、候选、提升、检查或最后数据验收。加载不依赖Basic内存，不能把加载成功当作正式维护入口已验证。

**当前代码与影响：** 当前分支`dev-interface`，本需求提交`38c7dca47cd64cdf6c8c6162f03a1e201141c6f9`。现有托管code-server从当前工作区加载`orchestrator.definitions`；加载也使9份未提交orchestrator源码变化生效：`catalog/lake_assets.py`仅格式/注释，7份moneyflow sensor文件仅说明文字，`sensors/moneyflow_update_selection.py`在Raw窗口全ready时不再因当天尚未复核而重复提交下载。后者可能改变已运行sensor下一次判断，已向管理员说明。没有启停sensor的代码，不修改已有启停状态；不把它描述成完全无运行行为变化。

| 本次固定输入 | 实值与核对依据 |
| --- | --- |
| 正式服务 | `http://127.0.0.1:3000/graphql`；现有服务只读查询已成功 |
| location / repository | `orchestrator` / `__repository__` |
| 正式instance位置 | `DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home`，沿用现有webserver，不另起instance |
| 定义来源 | 模块`orchestrator.definitions`，工作目录`/Users/congming/github/goldenshare/lake_console/orchestrator/src`；当前workspace及进程参数已核对 |
| SDK及实际入口 | 本机Dagster 1.13.26；`dagster_graphql/schema/roots/mutation.py`的`GrapheneReloadRepositoryLocationMutation.mutate`核对location和权限后调用现有`reload_code_location`；不通过新写的服务入口加载 |
| 加载前定义 | location为`LOADED`，`updatedTimestamp=1792501122.9016478`；`silver_etf_adj_factor_update_job`为`silver_etf_adj_factor`加原6个独立检查步骤 |
| 证据路径 | `/private/tmp/etf_completion_formal_reload_20261023.json`，只记录代码状态、请求、定义、耗时和成功/失败，不保存Basic或数据明细 |

**准确调用：** 复用已批准的curl方式向上述端点发送JSON GraphQL请求，不安装工具、不重启webserver或daemon、不调用`reloadWorkspace`。本次mutation为：

```graphql
mutation {
  reloadRepositoryLocation(repositoryLocationName: "orchestrator") {
    __typename
    ... on WorkspaceLocationEntry {
      name
      loadStatus
      updatedTimestamp
      locationOrLoadError {
        __typename
        ... on RepositoryLocation { name serverId }
        ... on PythonError { message }
      }
    }
    ... on PythonError { message }
  }
}
```

**顺序、预算与验收：** mutation最多25秒，只尝试一次。成功后用同一端点做一次有界只读查询：location加载状态/时间，`silver_etf_adj_factor_update_job`的步骤名，以及`silver_etf_adj_factor`的6个check名称和blocking标记；只读定义，不查运行、事件或业务数据。查询最多5秒，且受加载与读回合计30秒剩余预算限制。期待location为`LOADED`、无PythonError、更新时间更新，job步骤精确为`silver_etf_adj_factor`和`silver_etf_adj_factor_checks`；六个名称仍为contract、key_integrity、source_filter、source_parity、basic_coverage、domain原名称，全为blocking。完整原名称和顺序无关的集合比较写入摘要。只收到“请求成功”或location存在不算验收通过，必须看实际新job与check定义。

**读写、失败与中断：** 本步只有代码location加载及运行服务自身必要状态更新，业务数据、分区、cursor、任务/检查/手工sensor评估、历史事件和Lake写入全部禁止；已有自动运行照其原状态继续，不宣称整个正式环境零后台写入。错误、超时、响应不明或读回不符时停止，记录已发请求和状态；不再次加载，不自动重启、回滚或启动任务。若请求超时不能认定完全未生效，后续应先只读确认，不能盲目重试。新建/修改配置、schema、API或数据合同均为0。

**首次调用结果及验收查询纠正：** 正式mutation一次成功，耗时4.778823秒，location返回`LOADED`、`updatedTimestamp=1792691955.313462`、serverId为`8fe759c4-5ca7-4657-908a-673301e9e5b6`。首次只读验收请求耗时0.009209秒、HTTP 400：查询错误地给`AssetNodeOrError`加入不支持的`PythonError`分支，接口在查询校验时拒绝，未取得定义数据；这是本次调用编写错误，不能写成验收通过。已停止原调用，不再发送mutation；在本节先记录修正，移除这一分支、用当前SDK schema本地验证后，只允许再做一次相同范围的只读定义查询，单独最多5秒，不读运行/事件/数据、不重试加载。原步骤未按最初清单一次完成，不以HTTP调用耗时相加冒充包含排错间隔的30秒完整验收。

**最终结果：加载及定义读回通过。** 修正后的查询经本机SDK schema验证，正式只读请求耗时0.045027秒。location为`LOADED`，读回`updatedTimestamp=1792691955.3272362`，serverId与mutation一致；因子job步骤精确为`silver_etf_adj_factor`和`silver_etf_adj_factor_checks`。检查名称集合仍为`silver_etf_adj_factor_basic_coverage_check`、`silver_etf_adj_factor_contract_check`、`silver_etf_adj_factor_domain_check`、`silver_etf_adj_factor_key_integrity_check`、`silver_etf_adj_factor_source_filter_check`、`silver_etf_adj_factor_source_parity_check`，恰6项且全部blocking。加载前17份本需求源码/依赖指纹与隔离验收汇总一致，另9份工作区源码已单独记录指纹。完整结果及请求、失败查询、纠正查询见上述证据文件。

本步mutation次数1，主动启动补数任务/检查、手工sensor评估、sensor启停修改、分区/cursor修改、Lake与历史事件写入、Basic读取均为0；不据此声称服务后台没有原有自动行为。正式Plan及真实Basic传入未执行，仍按§11.9.16保持未完成，不因定义加载成功而放行补数。

#### 11.9.16 正式执行缺口及逐步完成条件

**历史状态说明：** 本节记录代码加载时的遗漏及当时完成条件。之后管理员2026-10-23明确同意新维护进程重新核验所需Basic、直接完成原任务；本节“寻找原Basic进程”和“本轮除代码加载不推进”的前提已被§11.9.17替代，保留本节作审计追溯，不作为当前重复审批或暂停理由。各阶段自然产生hash/target/UUID及必须核验真实输入的要求仍适用。

**纠正审计结论：** §11.9.14证明代码及所列隔离测试，不证明实际Basic进程已接入正式维护入口。之前审计验证了测试代码传对象后能运行，却漏核对真实对象从哪里来、如何进入入口，并把“执行前再列命令”当作非阻断事项；这是审计遗漏，正式Plan目前仍被阻止。旧文两处“26日生命周期仍未验收/本轮未执行新增测试”已纠正为隔离验收完成、正式未执行。不撤回有效的开发测试，也不把文档完整性检查当作正式调用的证据。

| 步骤 | 本轮确认的缺口 | 本步骤可以开始/完成的具体条件 |
| --- | --- | --- |
| 代码加载 | 当前现场清单原未填实 | 已按§11.9.15补齐，管理员已批准；只加载与读回定义，结果单独记录 |
| 确认Basic可用及传入 | 没有确认实际持有行的原进程、对象结构及可用的同进程调用方法 | 仅在获准边界内确认原进程/对象；核对`PreparedCompletionBasic.from_cache`需要的实际snapshots/references能否由现有对象提供，并验证同进程传给入口的方法。不能先假定原会话使用该类。无法做到则停止、说明原因；不暗中重读、导出或新建缓存服务 |
| 正式Plan | 尚未确定固定范围映射的构造、实际Plan路径和资源调用 | 根据本方案已review的56代码/26日表构造scope并通过固定范围hash；不能将测试fixture或旧临时审计JSON直接用作正式许可名单。列出staging内Plan绝对路径、所用同进程调用、只读storage、受控DuckDB及Basic reference；各对象的实际来源必须明确。先做该调用的有界入口核验，再判断能否正式执行 |
| 候选及总审计 | 需承接正式Plan的真实产物，不能用临时测试产物 | Plan生成后填其真实路径/hash，再明确候选/审计报告路径、准确阶段调用和原预算；仅按已批准26日/701键生成和审核，review通过后才能提升 |
| 26文件提升 | 需承接已审候选及正式目标状态 | 填真实Plan、候选报告/hash、进度路径和准确调用；按原规则核对空间/挂载/同文件系统、目标未漂移及无冲突在途运行。先具备该阶段执行条件，再按阶段授权提升，不改原42,900行 |
| 新物化及真实检查 | 正式instance/job/resource/Basic/进度调用尚未填实 | 填上述同一Basic对象、正式instance、解析后的现有job、受控resource及真实Plan/进度路径；核对正式已加载合并检查。仍是26日各追加物化后执行六项真实检查，不改旧日志；UUID与target按既定顺序保存 |
| 最后29日验收 | 输入需来自前阶段真实结果 | 填真实Plan、完成进度和最终报告绝对路径，明确同Basic对象的阶段调用；遵守58文件、16MiB、30秒、最多14次证据查询，额外3日不追加运行/事件 |

**哪些是缺口，哪些正常在后面生成：** 真实Basic持有进程、对象如何传入、首次Plan放哪里及如何调用，应在正式Plan前明确，不能留给执行人员猜。Plan hash、候选hash、物化target及UUID由各自阶段自然生成，提前没有实值不是设计缺陷；产生后写回本清单供下一步使用，禁止预造。`main(argv, prepared_basic=..., **context)`只能由持有内容的进程传入对象；新开shell运行模块不会继承内存，不能把带路径的shell命令当作已解决传递。是否需要代码改动，须在确认真实对象和现有入口后判断，不预先增加入口或执行脚本。

**后续审计的具体交付：** 每一步分别列实际输入来源、准确调用、读写范围、原预算、失败停止方式和独立验收证据；必须核对现有代码确实接受这些输入。已验证、隔离验证和未验证分开写；有任何必需输入或调用尚未确定，即标未完成，不再用“没有待拍板设计”代表“可以执行”。本表只是明确未完成工作，不赋予新的读取、任务或写入授权；本轮除§11.9.15外不推进正式动作。

#### 11.9.17 2026-10-23：新维护进程初始化与原范围补齐

**本节保留当时获批的执行规则与首次过程；当前完成状态见§11.9.18。** 管理员明确同意重新读取本任务所需Basic、核对后直接完成原任务，不再寻找旧审计进程中的内存；此前旧进程/重读另批/仅重载的限制已被替代。授权只覆盖56代码、26日期、701新增及26文件修改，原42,900行不改不删、补后43,601行，512390及其他任务不变；各stage内部验收及独立候选总审计通过后顺序推进，不重复请求已给批准，冲突/失败/取消/超预算停止。本节“下一步/未完成/停止”均为对应时点记录，后续获批修正与恢复事实见§11.9.18，不能当作当前仍阻断或遗漏的动作。

**本节记录首次执行及当时停止状态；当前已按§11.9.18修正、恢复并完成最后验收。** 首次events失败时，26文件已提升，只为首日追加1个新物化并创建1次失败运行，六项仅planned、实际evaluation为0；当时其他25日与最后验收未执行，不能声称156项通过。26文件/checkpoint及失败日志保留，当时即停止并先审清接入修正，未自动重试。实际latest在Plan冻结前正常日更到2026-10-22，两对4份467,414字节、56资格及固定scope已核对；没有借错误扩大范围。下表及失败说明保持该时点原事实，成功恢复及当前完成状态以§11.9.18为准。

**本轮元数据预检实值。** 首次保守预检因仍要求旧`02670e...`而在内容读取前停止；已确认是正常latest更新，按当前规则核对路径后重做同范围预检，通过耗时0.048318秒，不宣称一次到位。固定scope hash符合上述56/26/701，26日仍引用20个旧日期reference，原Silver合计42,900行；Plan不存在。最新Raw物化storage_id为7717486、观测时间`2026-10-22T21:07:27.726548+08:00`、hash为`83e4d18a830c671b76571bf6095e82971efab4d0353bf6ce9bf16f8b17369293`；Silver为7717534、`2026-10-22T21:15:16.848412+08:00`、hash为`622bad0ca9bb0b9087b9c8f0abce8a886e659a6cfc914c58927a53eaa954a43e`。限定内容读取文件如下；完整结果见[本轮正式执行摘要](/private/tmp/etf_completion_formal_execution_20261023.json)，该时点`basic_initializations=0`、`stages={}`、无源请求、sensor状态或分区修改。

| 物理文件 | 字节 |
| --- | ---: |
| `/Volumes/datasource/data_lake/raw/tushare/etf_basic/snapshot_id=1b68a978cf1fdae5f457da0c899387b8130314256ee10e0636279335f39b8b44/part-000.parquet` | 116508 |
| `/Volumes/datasource/data_lake/silver/basic/etf_basic/snapshot_id=1b68a978cf1fdae5f457da0c899387b8130314256ee10e0636279335f39b8b44/part-000.parquet` | 113155 |
| `/Volumes/datasource/data_lake/raw/tushare/etf_basic/snapshot_id=83e4d18a830c671b76571bf6095e82971efab4d0353bf6ce9bf16f8b17369293/part-000.parquet` | 120774 |
| `/Volumes/datasource/data_lake/silver/basic/etf_basic/snapshot_id=83e4d18a830c671b76571bf6095e82971efab4d0353bf6ce9bf16f8b17369293/part-000.parquet` | 116977 |
| 合计 | 467414 |

**本轮初始化与Plan实测及下一调用。** 仍使用上述同一维护进程；摘要中的元数据`plan_exists=false`和`basic_contents_read=false`仅表示预检时点，后续阶段结果如下，不覆盖历史时点。

| 已执行步骤 | 实际结果和耗时 | 给下一阶段的真实输入及允许动作 |
| --- | --- | --- |
| `initialize_basic()` | 通过，0.697991秒；2个物理版本、4文件、467,414字节，完整审计调用2次，内部有限重复扫描按原设计允许。20个旧日期引用加1个新引用，共21个prepared引用；56个上市日/状态全部匹配。新引用资格日期2026-10-21，可请求代码1711，reference fingerprint为`65b6ba72ad26b74ef11d2ea9e7854abd12e6d87bb289a75544a48a67cec1d2bc` | 同进程保存`prepared_basic`及新reference；后续禁止完整读取，不从摘要重建Basic行。初始化摘要所列42,900/56,349是当时的因子元数据量，不将初始化说成已扫描因子文件 |
| `stage("plan")` | 通过，7.238582秒；按现有完整Plan核验实际扫描对应26日Raw/Silver，固定56/26/701及原42,900行通过，目标43,601行；正式Plan已冻结在上述绝对路径 | 真实Plan hash为`21d8bb72f606be1b26f1b1526ab37c6c795d17c988038c7ff16d1f21a2dbebdd`。下一步同进程分别调用`stage("candidates")`、`stage("candidate-audit")`，每次仅一个stage，各30秒，继续使用同一prepared内容、固定scope/reference、只读storage和受控resource |
| `stage("candidates")` | 通过，7.986150秒；26/26份候选已生成，逐日新增数与§11.9.2一致，合计701；只写staging，尚未提升正式文件或追加事件 | 下一调用为同进程`stage("candidate-audit")`一次，30秒，复用同一prepared内容与真实Plan；读回现有候选并生成`candidate-audit.json`，完成后才交独立子代理只读review |
| `stage("candidate-audit")` | 通过，6.602533秒；26文件、新增701、原行修改0/删除0；Raw/原Silver/候选输入合计1,152,223字节，低于16MiB。总审计报告已写入真实候选目录`candidate-audit.json` | 独立子代理已收到报告，按原固定范围、每日期结果及原行不变规则只读review；其结论未通过前不调用`promote`，不额外扩展正式读取 |
| 独立候选review | `review_run_gap`只读核对Plan、`candidates.json`、`candidate-audit.json`通过，无阻断；三者同Plan hash，scope hash独立复算一致；26日各为1650原行加批准新增，总42,900+701=43,601，修改/删除0；候选hash、总审计hash及Plan预计hash逐日相等，26路径严格落在指定候选目录，无多余日期 | 本次只读报告metadata，未重复扫描Parquet；符合提升前门槛，可以按下一段现有调用进入`promote`，仍逐文件核验正式目标与候选，不用报告review替代提升时读回 |
| `stage("promote")` | 通过，7.949846秒；26/26份正式Silver按原路径提升，逐份完整读回和`files.json`完成进度均保存 | 此阶段结束时仅文件更新，不能当作ready；随后events尝试失败如下。不要重复提升或启动writer |
| `stage("events")` | **失败并停止**，1.605481秒；首日新物化target为7718242，真实run为`eaa86d87-b837-4a2d-ad0b-fa6b1ffe1a71`，终态FAILURE。只产生该run的11条日志，其中6条check planned，实际check evaluation为0；其他25日事件未开始 | 保留1个新物化、1次失败运行及6条planned，不删除/覆盖旧新记录，不换UUID重试、不改progress。先完成下述instance接入修正与失败后处理方案审计；最后29日验收未执行，不能宣称ready |

本Plan对应真实候选目录为`/Volumes/datasource/data_lake_staging/etf_daily/operation_id=21d8bb72f606be1b26f1b1526ab37c6c795d17c988038c7ff16d1f21a2dbebdd/silver_etf_adj_factor/`，生成进度为该目录`candidates.json`。候选及总审计调用只生成/审计26份staging候选与现有报告/checkpoint，不提升正式文件、不追加事件或检查运行。总审计报告产生后由独立子代理按原标准只读review；新增701、旧行修改0/删除0、范围及候选/目标指纹全部通过后才进入既定`promote`，不以Plan或候选生成成功代替候选总验收。

**已完成提升的准确调用与读写。** 独立review通过后，在持有上述`prepared_basic`的当前进程调用`stage("promote")`一次。临时调用者使用`with daily_basic_event_instance(writable=False) as instance`，把该只读正式instance、现有只读storage、受控resource和同一prepared内容传给`run_stage("promote", plan_path=<上述固定Plan路径>, expected_plan_hash="21d8bb72f606be1b26f1b1526ab37c6c795d17c988038c7ff16d1f21a2dbebdd", approved=True, ...)`；这里`approved=True`仅承接本次已给出的原范围授权，不是新增用户开关。不得传job或写instance来做文件提升。

该阶段只处理Plan所列26个`/Volumes/datasource/data_lake/silver/quote/etf_adj_factor/trade_date=<Plan日期>/part-000.parquet`目标，日期严格取冻结Plan，不自行展开其他日。重核总审计内容、原目标/候选指纹、原依据、同日无在途运行、挂载/可写/空间和同文件系统；逐日期完整核验后`os.replace`，读回一致才保存该日完成进度。准确进度文件为`/Volumes/datasource/data_lake_staging/etf_daily/operation_id=21d8bb72f606be1b26f1b1526ab37c6c795d17c988038c7ff16d1f21a2dbebdd/silver_etf_adj_factor/files.json`，阶段每日期前后检查取消，总预算30秒（含instance建立、核验、读回和checkpoint），1线程/256MiB/无spill。不写物化或检查事件，不改Raw/Basic或原42,900行。失败保留已完成文件/进度并停止；已提升且与候选等价时只读回，不重复替换，第三种内容停止。正式readiness在新事件/检查完成前仍应阻断，不将26文件替换等同最终完成。

**本轮事件调用记录（已失败，禁止直接沿此调用重试）。** 本次在当前维护进程调用`stage("events")`一次，外层30秒从建立`daily_basic_event_instance(writable=True)`之前开始，包含最小job解析、26个固定日期的`has_dynamic_partition`只读预检、文件/原依据核验、新物化、真实检查、日志及进度；缺分区即停，不调用`add_dynamic_partitions`。解析只组合真实`silver_etf_adj_factor`、真实`silver_etf_adj_factor_checks`、现有因子job和其2个上游`AssetSpec`；不加载全局Definitions。将该真实job、写instance、同一prepared内容、受控`duckdb`/`lake_root`及只读storage传给现有`run_stage("events", plan_path=<上述固定Plan路径>, expected_plan_hash="21d8bb72f606be1b26f1b1526ab37c6c795d17c988038c7ff16d1f21a2dbebdd", approved=True, ...)`。该组合在真实检查启动时暴露下述错误，因此撤回“此instance可直接执行真实检查”的判断；不是全部26日事件执行通过。

**准确失败原因与证据边界。** 复用的`daily_basic_event_instance`原用于runless事件/只读访问，其`InstanceRef.run_coordinator_data=None`。本机Dagster 1.13.26真正的in-process检查入口，在`InstanceConcurrencyContext → event_log_storage.get_pool_config() → instance.get_concurrency_config() → instance.run_coordinator`取运行协调器时抛出`Run coordinator not configured in instance ref`，资源初始化已成功但检查步骤尚未执行。这是本次把runless helper用于真实check run的接入错误，不是因子数据错误。原438项隔离测试没有覆盖这个正式helper与真实check run的组合，不能再引用这些测试证明该组合可执行。

只按上述精确run_id、有界61条上限读回实际11条日志：6条`ASSET_CHECK_EVALUATION_PLANNED`、`PIPELINE_START`、`ENGINE_EVENT`、`RESOURCE_INIT_STARTED`、`RESOURCE_INIT_SUCCESS`、`PIPELINE_FAILURE`；没有`ASSET_CHECK_EVALUATION`。错误及堆栈保存在[本轮正式摘要](/private/tmp/etf_completion_formal_execution_20261023.json)的`stage_error`与`failed_run_diagnostics`中。未重试、未启动后续日期、未修改日志或progress。源代码调整、失败run之后如何产生新记录及相应测试，必须先落回原方案/LLD并审计；本段只记录阻断，不预先授权新增run或默认重试。

现有维护实现先确认26日`files.json`全部完成，逐日重新审计已提升文件，追加或等价找回新物化；新target持久保存后才保存UUID和运行。真实job仅取`asset_selection=set()`及该因子的6个check subset，核对资产选择为空、检查集合恰6项后`execute_in_process`；不执行资产writer。每日期1个合并核验步骤产生6项真实ERROR/blocking结果，全部通过且绑定新target才保存完成；任一项失败即停止，保留实际失败，不换UUID自动重试。运行Plan tag、错绑/后续失败核对、仅latest 1找回和中断规则仍按§11.9.7/12。

准确事件进度为`/Volumes/datasource/data_lake_staging/etf_daily/operation_id=21d8bb72f606be1b26f1b1526ab37c6c795d17c988038c7ff16d1f21a2dbebdd/silver_etf_adj_factor/events.json`。成功目标是26个新物化、26次真实检查运行、156项新检查结果及真实运行日志；旧物化/旧检查修改0、删除0，不登记其他资产，不触发sensor，不改已提升文件或Raw/Basic。仅本阶段使用写instance，其余前后阶段继续只读；Basic初始化后完整读取0，沿1线程/256MiB/无spill和原事件/恢复查询预算。每日期前后检查取消，文件/target/UUID各自既有checkpoint保留，失败不得领取下一日期。

事件阶段全部通过后，在同一进程单独调用`stage("final-audit")`，用`daily_basic_event_instance(writable=False)`、同一Plan/hash/prepared内容和受控资源。准确报告路径为`/Volumes/datasource/data_lake_staging/etf_daily/operation_id=21d8bb72f606be1b26f1b1526ab37c6c795d17c988038c7ff16d1f21a2dbebdd/silver_etf_adj_factor/final-audit.json`；只读29日/58个Raw/Silver文件、16MiB、最多14次证据查询，外层30秒含只读instance初始化及报告写入，额外3日仍无检查/运行/事件。不把事件成功替代最终869条、旧行0变化和正确新事件绑定验收。

**现有实现与调用方式。** 本次不改业务代码。临时调用脚本为`/private/tmp/etf_completion_operator_20261023.py`，仅编排现有`CompletionBasicCache`、`PreparedCompletionBasic`、`ReadonlyCompletionStorage`和`run_stage`，不重写选择、校验或写入业务逻辑。由`lake_console/orchestrator/.venv/bin/python -B -i /private/tmp/etf_completion_operator_20261023.py`启动一个本轮维护进程；启动只做下表元数据预检，`initialize_basic()`才读取Basic内容，之后通过`stage("plan")`等一次调用一个阶段。同一进程保留`prepared_basic`及上下文，摘要不包含Basic明细；完成后关闭storage/instance并删除临时调用脚本，保留执行摘要与现有进度文件。不是新增永久CLI、环境变量、缓存文件或后台服务。

| 步骤 | 目标、输入和现有入口 | 读取/写入、预算及通过条件 |
| --- | --- | --- |
| 元数据预检 | 从§11.9.2的56代码上市日表与26日表构造`scope`；校验`validate_etf_factor_completion_scope(scope)`。以`ReadonlyCompletionStorage(Path("/Users/congming/.goldenshare/dagster_home"))`读取现有配置，仅连接只读event storage。26日原因子物化中的完整Basic reference按每批最多10日、共3批取得；最新Basic Raw/Silver各取latest 1，取得对应3项检查元数据 | 只读固定26日与上述Basic元数据、4个物理路径stat，不读因子Parquet、不读取Basic内容、不读10月21日因子文件、不初始化写instance或执行job。30秒内结束；scope必须为56/26/701，固定hash为`b42c991cbe1711316c48ad0782e9cb21d4b3944967013aa01c5288481400f76b`。元数据身份、引用、路径、检查绑定或两对上限不符即停，记录实际4路径和字节后才初始化 |
| 本轮Basic初始化 | 使用受控`CompletionDuckDBResource`连接，`CompletionBasicCache(connection, lake_root, allow_full_read=True)`。旧版按一个代表reference调用`get()`完成该物理版本的完整核验；新版使用现有`audit_etf_basic_silver_snapshot`一次取得真实rows，以现有资格分类/hash和`build_etf_basic_silver_snapshot_reference`构造完整最新reference，再seed/get。其他日期reference逐个get核对各自日期资格，不再对同一物理版本完整核验 | 限预检确认的两对/4份Raw/Silver Basic；允许现有完整审计内部有限重复扫描，不将“一次调用完整审计”写成“文件绝对只扫描一次”，不为追求该说法修改共享审计。新版`eligibility_as_of=2026-10-21`是本次审计终点，观测时间使用latest元数据的真实时间，不能伪造成历史当日最新。初始化30秒、1线程、256MiB、无spill；所有完整合同、内容与资格校验通过后`PreparedCompletionBasic.from_cache(cache)`，再结束初始化连接 |
| 后续同进程调用 | `stage(name)`将已有`prepared_basic`、同一scope/reference、只读storage、受控resource及Plan路径显式传给现有`run_stage`；后续连接通过`prepared_basic.seed_cache(..., references)`取得`allow_full_read=False`缓存 | 初始化之后，26次检查、续查和最后验收均复用已核验内存；错引用、错内容、对象丢失立即停止，不能静默调用完整读取。不得从JSON报告、临时导出或原审计会话补造内容。每阶段仍30秒；不把初始化成本从本轮记录中隐藏，也不把各阶段加总误称单阶段成本 |

范围构造使用文档已review的字面表：`listing_dates`是56代码到上市日期的映射；`additions[day]`是该固定26日中上市日不晚于day的代码排序列表；同时逐行核对文档中的单日新增数与各代码新增数。不得从测试fixture或旧644条模拟JSON取得正式许可名单。固定hash校验失败即停，不改hash来适配现场。

**固定路径及资源。** 正式根为`/Volumes/datasource/data_lake`，staging根为`/Volumes/datasource/data_lake_staging`。本轮Plan绝对路径确定为`/Volumes/datasource/data_lake_staging/etf_daily/etf_adj_factor_history_completion_20261023/plan.json`；受控DuckDB临时目录为同目录`duckdb_tmp/`。创建前检查根、祖先及目标均无符号链接，沿用现有staging边界和禁止spill规则。候选仍由现有代码写入`staging/etf_daily/operation_id=<真实plan_hash>/silver_etf_adj_factor/`，不改为Plan目录或正式Lake。只读storage读取上述固定home中的现有PG配置，不打印连接凭据。`plan`、`candidates`及`candidate-audit`不创建正式instance/job。

本轮调用按原阶段逐步进行：`plan`冻结完整Plan后记录真实hash；`candidates`及`candidate-audit`只写和审计staging，并在独立总审计通过后进入`promote`。`promote`已通过现有`daily_basic_event_instance(writable=False)`取得只读正式instance；未来`final-audit`也仅只读。`events`本轮曾用该helper的`writable=True`，已暴露下述run coordinator缺失并失败，不能继续把它当作可执行真实检查的入口；修正及失败后处理尚待审清。禁止`DagsterInstance.get/from_config`或加载全局Definitions。检查job使用真实`silver_etf_adj_factor`、真实合并检查、现有job和2个上游`AssetSpec`做最小组合后`resolve_job_def`，资源仅传受控`duckdb`、`lake_root`以及现有检查所需`prepared_basic`；不创建永久job，不新增动态分区，已有分区有界核对缺失即停。具体Plan/候选/事件/最终报告与进度的真实hash、路径和逐步结果在各自产生后记录，不用占位值冒充已验收。

**中断、续跑和最后验收。** 进程退出保留现有逐日checkpoint和已经完成的文件/事件；下次明确启动本任务维护进程，允许重新预检并加载这两对必要Basic，再按现有Plan/目标指纹及进度续查，不追踪旧Basic持有进程，不增加导出或共享服务。运行期间内容丢失仍立即停止，不能以“下一次可初始化”为由偷偷回退读取。UUID续查中确认旧维护进程退出的防重复启动规则继续适用。最后仅26变更日加10月19—21日共29日、58个Raw/Silver日期文件，16MiB、30秒、最多14次证据查询；额外3日只读既定56代码已有行及文件指纹，不触发检查/运行/事件，不查全量检查历史。各阶段延续1线程/256MiB/无spill与原恢复预算；不请求Tushare、不访问Prod、不改Raw/Basic、不重刷其他日期或代码。

#### 11.9.18 首日执行接入错误的最小修正及已批准恢复

**授权与实施状态：当前已完成。** 管理员明确同意本节最小修正并继续原任务，包含仅首日失败的人工恢复例外。1个现有helper修正及1份新增测试已完成，真实同构SDK隔离8项、纯人工进度恢复隔离通过；正式人工恢复、恢复后26日events及最后29日验收均已完成，实值见下文。失败事实、26份已提升文件、冻结Plan及原56/26/701范围保留；未重做Plan/候选/提升，未增加stage或自动重试机制。

**首次失败时的状态与依据：** 当时26份Parquet已经按冻结Plan提升并读回，Plan为`21d8bb72f606be1b26f1b1526ab37c6c795d17c988038c7ff16d1f21a2dbebdd`；首日2026-09-03新物化7718242已保存，运行`eaa86d87-b837-4a2d-ad0b-fa6b1ffe1a71`失败，11条运行日志中有6条检查planned、实际evaluation为0，步骤未开始。仅按此run_id读取11条定位，未查其他历史。SDK1.13.26的`InstanceConcurrencyContext`即使步骤没有声明池，也会调用`get_pool_config→get_concurrency_config→instance.run_coordinator`；原helper实例及ref均没有coordinator，因此失败。这次将只适合读取/补事件的组合用于真实检查，是接入审计遗漏；后续修正不抹去该事实。

**只读核对过的正式配置：** `InstanceRef.from_dir("/Users/congming/.goldenshare/dagster_home")`只解析配置描述，不构造storage或写schema。实际coordinator为`dagster._core.run_coordinator.QueuedRunCoordinator`，自身config为`{}`；并发配置为`{"runs":{"max_concurrent_runs":1},"pools":{"granularity":"run"}}`。不得塞入默认coordinator、清空并发限制或修改dagster.yaml来绕过错误。

**具体开发位置与影响面。** 只修改`lake_console/orchestrator/src/orchestrator/defs/bootstrap/daily_basic_event_instance.py`，新增`lake_console/orchestrator/tests/test_etf_adj_factor_completion_instance.py`；不另建实例体系，不修改共享运行/检查/文件生成业务规则。当前源码调用方只有`defs/bootstrap/daily_basic_history_cli.py`的`daily_basic_event_instance(writable=writable)`和`moneyflow_continuation_cli.py`的无参数调用；两者保持原行为。本任务临时`/private/tmp/etf_completion_operator_20261023.py`只在events阶段调整调用，仍编排既有stage，不成为新永久入口。

| 内部参数或输入 | 默认值、来源、消费者及依赖 | 实现与禁止项 | 验收要求 |
| --- | --- | --- | --- |
| `for_execution` | 现有helper新增仅关键字内部参数，默认`False`，无env/配置文件/数据库/CLI输入；仅本次events调用显式传`True`，依赖`writable=True` | `for_execution=True, writable=False`在构造storage及任何正式读写之前拒绝。默认False沿用原helper，不解析/接入coordinator；两个既有源码调用方不修改 | 默认读取/runless模式行为不变；readonly与execution组合反例实际拒绝，不以mock提前返回替代 |
| 正式coordinator描述与concurrency | execution模式用`InstanceRef.from_dir(str(INSTANCE_HOME))`只读解析已有正式配置描述；`run_coordinator_data`必须存在。若正式settings含`concurrency`，完整deepcopy；若合法省略该可选section，保持省略并沿SDK默认。本轮实际有配置：QueuedRunCoordinator、空组件config，concurrency为runs上限1及pools按run | 只复制实际存在的这两部分到受控ref；settings保留本helper的`telemetry.enabled=False`，不复制run_monitoring等其他settings；不复制launcher、scheduler或自动构造storage，不改正式dagster.yaml。不填默认coordinator，不缩减原并发限制；合法省略concurrency时不塞空设置、不误拦 | ref和最终instance使用同一settings；`get_concurrency_config()`与`event_log_storage.get_pool_config()`保留原配置/合法缺省语义；仅缺coordinator描述或非法配置抛错，不静默兜底 |
| 现有受控PG storage和实例 | 正式home、localhost/正式库身份、SQL超时、只读/写模式及artifact检查继续复用原实现；显式构造event/run storage | 两者仍`should_autocreate_tables=False`；保持无launcher、无scheduler，不调用`DagsterInstance.from_ref/get/from_config`。只有解析ref，不实例化其其他storage；不生成另一套配置或服务 | spy核对两处False及构造参数；真实SDK执行检查时不得提交launcher、触发writer或DDL |

在同一helper中，先拒绝非法参数组合，完成既有正式配置/路径/库身份检查；execution模式再读取所需ref描述，构建包含正式`run_coordinator_data`和上述settings的受控ref。最终`DagsterInstance`与ref使用相同settings，并让instance按该ref获取正式coordinator组件；不把完整正式ref交给会自行构造其storage的入口。实例的显式storage、关闭顺序及临时资源清理沿用现有`ExitStack`。新增参数不是用户/运营可调配置，也不授权其他现有调用改成真实执行。

**测试位置、输入依据与真实边界。** 新测试使用真实`daily_basic_event_instance`函数和本机真实Dagster SDK；本任务临时artifact及SQLite只替代正式PG连接/存储，显式说明不证明正式PG成本。测试fixture来自上述已只读确认的正式配置描述合同：QueuedRunCoordinator组件config为空，完整concurrency为`{"runs":{"max_concurrent_runs":1},"pools":{"granularity":"run"}}`，telemetry关闭；不读正式home或凭据，不连网络，不安装依赖。关键预期用独立字面值，不从helper计算expected。PG构造替身同时spy确认生产构造明确传`should_autocreate_tables=False`；临时SQLite建立测试表不等于正式PG自动DDL，测试报告须区分两者。

新增测试逐项证明：原默认模式构造的真实SDK运行在检查step之前因缺coordinator失败，六项evaluation为0，能复现本次错误；execution模式通过同一真实helper构造后实际运行六项检查，六项均执行/通过，不换成另一种测试instance；ref与instance的现有concurrency完整deepcopy且修改输入不会串改输出，telemetry仍关闭，其他settings/launcher未复制；另用合法省略concurrency的正常样本，证明保留省略、可沿SDK默认取得并发配置，不误拒绝或人为增加空section；缺coordinator作为独立反例拒绝。`for_execution=True`配只读拒绝；原默认False的读取和runless行为仍通过必要回归。执行时监视禁止的网络/正式路径、storage构造、DDL、launcher及writer，不能仅断言API签名。测试可用独立小check样本验证真实执行边界，明确它不重复声称全26日生产检查已经通过；六项数据判断已有专项回归继续有效。原失败run和异常恢复通过现有progress/执行函数的隔离小样本核对：原失败记录不变、原target复用、仅首日当前UUID退役后真实新UUID正常保存并运行，其他25日不受影响；不将FAILED改为SUCCESS，不用`previous_process_exited=True`绕过失败。

新隔离片段预算30秒，仍用现有受保护测试启动方式、临时资源与已有解释器；不读正式config/Basic/Lake/instance。超时或任何上述边界未证明就停止，不能以新测试数量代替真实helper组合的验证。开发完成后先核对该helper、测试及本节硬口径一致，再允许临时调用者events使用`daily_basic_event_instance(writable=True, for_execution=True)`。`promote`/`final-audit`及两个原调用方继续默认False，不新增阶段、数据范围或并发开关。

**helper修正及真实同构SDK隔离结果（已通过）。** 源码已按本节实施，新增测试8项通过，pytest耗时1.51秒；保护执行整段1.767893秒，低于30秒。真实旧默认模式精确复现检查step前缺coordinator失败、evaluation为0；新execution模式由同一真实helper构造，六项真实check运行后从临时SQLite读回，全部通过且绑定同一个真实target。QueuedRunCoordinator与原有runs上限1/pools按run配置、合法省略concurrency的SDK默认行为均通过；默认两个caller仍不接入执行配置，readonly+execution拒绝，storage构造的`should_autocreate_tables=False`已spy核对，未使用launcher或writer。Ruff与差异空白检查通过。

该片段只用临时SQLite替代PG存储，不声称证明正式PG性能；未读正式config/Basic/Lake/instance或访问网络。保护器记录1次标准库`platform.architecture`试图通过`file`探查解释器，已被阻止、未启动子进程；此为标准库环境探查，不是Dagster launcher调用，不能把它隐去或说成成功启动。临时保护执行脚本已删除，结果保留在[保护执行摘要](/private/tmp/etf-instance-tests-20261023-gxe2yw5q/allowed/result.json)及同目录`pytest.log`。这组证据补齐本次真实helper与SDK的接入边界，仍不代表正式26日事件已成功。

**人工进度恢复的隔离结果（已通过，仅文件步骤）。** [独立验证摘要](/private/tmp/etf_manual_recovery_validation_20261023.json)记录耗时0.019520秒：只以AST提取4个具名纯函数及现有原子文件保存调用，不导入整个临时operator；输入及输出文件均在`/private/tmp`，禁止外部访问，未接触正式资源。真实执行两次原子保存，证明先保留失败依据，再退役首日当前UUID；原输入对象、首日target/hash及其他25个日期键均不变。9类反例均拒绝：错Plan、run、target、文件hash或日期，已通过、当前UUID缺失、授权依据缺失、已经记录恢复。第一次保存失败时原文件不变并停止；第二次保存失败时已持久保存恢复依据及旧UUID，不会留下“编号已删、依据没存”的状态。

该证据只覆盖纯进度内容构造及现有文件原子保存，不涉及真实DB、run、Parquet、helper真实SDK组合或外层正式恢复调用；不能据此开始正式恢复。仍须等待本节helper真实SDK集成通过，再执行授权范围内的正式动作。

**仅此失败的人工恢复（已获明确授权，开发/隔离通过后才执行）：** 保留原失败run状态、日志及6条planned；不删除、不改成功、不补造evaluation。只对上述真实hash目录现有`events.json`执行一次有界调整：先将旧UUID、日期2026-09-03、Plan hash、target7718242、文件hash、11日志/0结果及本次管理员明确同意的依据写入首日已有进度的恢复记录，原子保存成功后，再仅对该首日调用`pop("run_id")`并原子保存；target、content_hash及其他已有键全部保留，其他25日进度不变。不先清编号再补恢复依据；写失败立即停止，不领下一动作。此记录不是新数据表、缓存文件或自动重试功能。

准确人工恢复入口为临时调用者的`recover_startup_failure()`，仅处理日期`2026-09-03`、Plan hash `21d8bb72f606be1b26f1b1526ab37c6c795d17c988038c7ff16d1f21a2dbebdd`、target7718242和失败run `eaa86d87-b837-4a2d-ad0b-fa6b1ffe1a71`；不能由任意日期/run参数扩大恢复范围。重新加载修正helper及caller后先按冻结Plan恢复输入并核对上述实值，确认失败状态、11日志/0结果、文件hash及首日保存的target一致，实际验证execution实例`get_concurrency_config/get_pool_config`可用，再完成两次原子保存。外层仍30秒，任何核对/保存失败即停，不追加物化或运行。

该人工恢复返回成功后，当前维护调用者用`daily_basic_event_instance(writable=True, for_execution=True)`仅一次调用既有`stage("events")`继续。现有`execute_completion_checks`正常生成新UUID，先原子保存再创建真实run；首日`ensure_completion_materialization`必须复用7718242，不重复追加。已有失败编号不得传给`execute_in_process`当续跑，不误用`previous_process_exited=True`——该选项只用于编号查无，与本次已存在的FAILURE无关。除已批准这一次首日接入异常恢复，任何后续失败仍按原规则停止，不增加自动重试循环；人工恢复已完成，但26日新事件完成及最终验收仍未记录成功。

**正式人工恢复结果（已完成，尚未新增运行）。** `recover_startup_failure()`耗时0.122019秒。修正helper在正式既有PG实例实际读取`get_concurrency_config/get_pool_config`通过，runs上限1、pools按run均保留；旧run仍为FAILURE，其Plan/date正确，无同日在途运行，按latest 1取得首日target7718242及metadata与冻结Plan/保存进度一致。先保存完整失败恢复依据，再仅退役旧UUID，两次原子保存成功，target/hash及其他已有键保留，未修改旧run或其11条日志，新增正式事件0、run 0。实绩在[本轮执行摘要](/private/tmp/etf_completion_formal_execution_20261023.json)的`manual_recovery`；修正helper的SHA-256为`55986edfaba51e24eaeb7c6b84441f3fa02cfa44ac2e4bfb8acc3f552976c0e8`。

下一调用是在同一维护进程执行`stage("events")`一次，继续原固定26日，包括复用首日target后用正常流程生成新UUID，以及其余25日。外层30秒包含实例/并发预检、job解析、26分区有界核对、真实检查及进度，不重新写Parquet、不新增首日物化、不跳过原检查或最终验收。

**恢复输入与预算：** 使用已冻结Plan及其`original_metadata`恢复20个原日期引用和42,900行依据，不从当下latest物化重建“原42,900”基线；首日最新已是1651行，不能误当原1650行再报漂移。恢复冷启动首先读上述已冻结Plan并校核固定scope/hash，再取其`original_metadata`；不使用§11.9.17首次Plan前“26日当前latest作为原文件”的准备分支。新维护进程按§11.9.17的受控初始化方法，只重新加载此Plan冻结的旧版与新版两对Basic，不改绑恢复时的其他latest，不找旧进程，不重新生成Plan/候选或重写已提升文件。继续核对文件进度及实际target。额外允许的正式变化仅为首日一个新检查run，其余25日的25个物化/25run/150结果仍属原范围；成功后共26个新物化、156项通过结果，另保留1次启动失败，合计27次run。正常702条日志加已发生11条，目标为713条；2MiB预算不因本次错误自动放宽，正式日志不另做全局收集。恢复前先证明成本有界；事件/续查与最后验收各30秒不变，最后仍29日/58文件/16MiB/最多14次证据查询，任何后续失败停止说明。

**恢复后events实绩（已完成）。** 同一维护进程一次调用既有`stage("events")`通过，外层完整耗时28.080222秒，包含instance建立、最小job解析、26已有分区及并发配置预检、逐日文件/依据审计、新物化、真实检查和checkpoint，未放宽30秒预算。26/26日期均完成，156项实际evaluation由原函数逐日核对run SUCCESS、正确target及最新六项全部通过；不是只有planned。首日继续复用target7718242，没有再追加首日物化。全本次成功目标为26个新物化、26次成功run、156项通过结果，另保留原1次失败run及11日志；合计27个run，不删除或改写旧记录。

失败信息保留在执行摘要的`prior_stage_errors`，原首日失败run仍存在；`events`正式stage现为passed，`events.json`继续保存同Plan下的人工恢复依据及逐日target/hash/run_id。随后已按原清单在同进程单独执行`stage("final-audit")`：只读instance、29日/58个Raw/Silver日期文件、16MiB、最多14次证据查询，外层30秒包含instance与报告保存，不新增run/物化/检查；完成结果见下段，不用events成功替代最终869条及旧行零变化验收。

**最后正式验收与当前结案。** 同一维护进程单独执行既有`stage("final-audit")`通过，外层6.488283秒（报告内文件/证据核验6473.561毫秒），使用只读instance，无新run/物化/检查。实际29日、58个不同Raw/Silver日期文件、900,702字节、8次证据查询，分别低于16MiB和14次上限；58是不同文件数，不据此改称已测得58次扫描。26日完整文件/原行/701新增及新事件绑定通过；额外10月19—21日已有168条及文件指纹通过，额外3日未运行检查或写事件。目标范围869条齐全，补后26文件总43,601行、新增701、修改0、删除0，原42,900行及512390保留。

26日进度均`checks_passed=True`、26个唯一成功run、156项通过结果；首日target仍7718242，成功新run为`4181af4f-0587-4b98-87e1-57d2785725e0`。旧失败run `eaa86d87-b837-4a2d-ad0b-fa6b1ffe1a71`及11日志保留，总27run，不删改旧记录。713条日志为本节既定门禁目标，未为凑数全局收集正式日志；不将其写成已逐条统计的PG物理成本。

| 本轮完成阶段 | 实际外层耗时（秒） | 预算与范围结果 |
| --- | ---: | --- |
| Plan | 7.238582 | 26日固定范围及原依据核验通过 |
| candidates | 7.986150 | 26份staging、701新增通过 |
| candidate-audit | 6.602533 | 26份总审计，0修改/删除；另独立只读报告review通过 |
| promote | 7.949846 | 26/26文件原子提升、逐份读回/checkpoint |
| 恢复后events | 28.080222 | 26成功run、156结果；含instance/job/分区/并发预检，首日target复用 |
| final-audit | 6.488283 | 29日/58文件/8查询/900702字节，869目标行及原行零变化通过 |

六个完成阶段分别小于原30秒，未增加线程、内存、spill、读取日期或写入范围；首次events失败1.605481秒、开发修正/隔离及人工恢复0.122019秒另列，不冒充全流程一次成功或总计30秒。只修改26份指定Silver并追加获批事件/运行，Tushare请求、Prod访问、sensor状态/分区修改均0；未全湖复查，不重刷其他代码或日期。准确最终报告为`/Volumes/datasource/data_lake_staging/etf_daily/operation_id=21d8bb72f606be1b26f1b1526ab37c6c795d17c988038c7ff16d1f21a2dbebdd/silver_etf_adj_factor/final-audit.json`，实值与各产物指纹保存在[本轮执行摘要](/private/tmp/etf_completion_formal_execution_20261023.json)的`final_report`、`events_summary`及`artifacts`，总体`status=complete`。本任务已完成，不保留额外补齐/检查为待执行动作；首次失败及恢复历史继续保留。

**独立复核及收尾：** 完整正式报告已由独立子代理`review_run_gap`复核，各阶段、固定范围、原行0改删、26新物化/26成功run/156结果、失败保留和最终29日验收均对账通过。维护storage已关闭，进程exit code为0，临时operator已删除；摘要`maintenance_cleanup`记录`storage_closed=true`、`process_exit_code=0`、`operator_removed=true`，仅保留摘要及现有staging Plan/报告/checkpoint，不留下执行服务。两份本次源码Ruff/check/format通过；测试最后仅3行格式换行，AST一致，原8项测试证据有效，CodeGraph已同步到当前源码。该收尾不新增正式查询、补数或运行，不清理其他任务文件。

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

输入最多10个日期，一次完成。普通文件使用以下物理审计；符合§11.8的未改动补值文件另核对原验收。§11.9开发/隔离验收见§11.9.14，正式完成结果见§11.9.18；完成指定追加的文件必须先核对原有行和新增行，再判断ready，不能把整份文件套回旧指纹或调用补值解析器。本次维护最后验收及必要续查按§11.9.12显式传入已核验Basic，每批独立连接seed，缺失即停；日常默认行为不变：

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

2026-09-04 17:54 获批执行验收：原 Plan 的 1,624 条 materialization 和 340 条 blocking check 全部新增完成，CLI 耗时 137.15 秒；逐事件 checkpoint 共 1,964 条。`events-post-audit` 按资产/check 集合读回核对，失败 0，CLI 耗时 1.87 秒。再抽查 `2026-08-07/2026-08-20/2026-09-03` 三日、四资产，共 12 个分区全部 ready；正式 readiness helper 合计 4 次 materialization 查询，核心耗时 1,282.948 ms。10 项事件隔离测试再次通过，包含临时 Dagster instance 的两日写入/重放/验收；没有重新同步源数据、改湖文件、注册日期或启用 Sensor。执行报告、聚合验收、抽样验收及其 hash 统一记录在技术方案 §13 P6。该时点只完成历史补录，不替代日常验收；当晚另行获批的 Sensor 启用、首日验收及结案决定见 §19 P6。

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

开发状态：已完成（2026-09-02）；当时尚未授权启用，正式启用与结案见 P6。先通过最多 10 日的批量 readiness 性能测试，再落四个 evaluator 和四个默认 `STOPPED` 的 Definition。Raw 每个资产最多一次 materialization 查询，Silver 合计最多两次；已有坏文件或坏证据 fail-closed，P4 初版 Coverage WARN 不阻断。隔离测试覆盖 20:59:59 零访问、21:00 入窗、最近 10 日、最早缺口、已有坏文件、发布未就绪、latest-only Basic、稳定 run key、紧凑 cursor、查询预算和 Definitions 自动发现。正常交易日 21:00 后的源端只读发布复验是启用门禁；未经授权不启用。

上述为 P4 初版验收记录；当前因子 coverage 已按 §11.6 升级为阻断，只有日线 coverage 保持 WARN。9 月 3 日 22:29 与 9 月 4 日 21:15 的源端非空复验均通过（详见技术方案 §3.4）；四个 Sensor 已于 9 月 4 日晚单独获批启用。这些实测时点仍不代表每天 21:00 准点发布，日常 publication probe 继续保留。

### P5：Bootstrap 工具

状态：已完成（2026-09-03）。

已按 raw-plan -> bounded-sample -> raw-apply -> raw-audit（包含 profile）-> silver-plan -> silver-apply -> physical-post-audit -> events-plan -> events-apply -> events-post-audit 落地五个 Bootstrap 模块和独立 CLI。隔离 fake/临时目录验证最多 3 日；没有请求真实 Tushare、写正式 Lake、写正式 Dagster instance 或运行全量。

隔离验收覆盖：Raw 中途停止后从逐文件 checkpoint 续跑、文件已原子提升但 checkpoint 尚未落盘时通过公开 writer 重新证明等价后续跑、未完成目标与水位漂移 fail-closed、Raw audit 与 manifest 闭合、coverage review/policy 门禁、Silver Basic fingerprint 漂移拒绝、四资产物理对账、20 日 batch 调度上限、全日期 materialization、最近 20 日 blocking checks、已有等价事件复用、active run/内容冲突停止、事件重放与 post-audit。bounded sample 同时记录请求/行数、耗时、峰值 RSS、DuckDB spill、文件大小以及 `change`/`discount_rate` 字段门禁。

### P6：正式执行

状态：已结案（2026-09-04，管理员确认）。

历史建设已完成正式 Raw Plan、三日隔离样本、812 个 Raw 文件入湖、全区间批量审计、正式 Silver Plan、812 个 Silver 文件入湖及最终物理验收。2026-09-04 coverage 已拍板：因子阻断、日线告警；代码与验收要求见 §11.6。历史入口新鲜度与最终批量验收分别按 §16.2.1、§16.6 修正并通过回归。历史日线 Silver 为 539,226 行，因子为 539,536 行；物理验收 4 组、60 次 SQL、核心耗时 2,953.390 ms，1,624 个文件及 checkpoint 全部对账通过。因子缺码 0，日线 166 日共 310 个代码/日期缺口仍 WARN。当时选定的 398 项定向/静态测试、Ruff、Definitions 和文档完整性检查通过，但该测试集合未包含 `test_asset_governance_contracts.py` 与 `test_asset_check_incremental_governance.py`，因此不能证明资产治理登记已闭环。随后 §16.7 的事件 Plan、1,964 条正式事件补录、聚合写后验收和三日历史 readiness 抽样均完成，历史数据与登记记录已闭环。

日常启用与验收已完成：21:15 发布预检和最新 Basic 检查通过，共享分区已到 `2026-09-04`；管理员批准后，21:18:53 开启两个 Raw Sensor，Raw 成功后于 21:19:29 开启两个 Silver Sensor。四个正式 run 均由对应 Sensor 触发且成功，日线/因子 Raw 分别新增 2,114 / 2,145 行，两个 Silver 各 1,650 行。仅新增当天 4 个文件，未重跑或覆盖历史；日线 1 页、因子 2 页，无重试，各 run 耗时 1.165—1.980 秒。21:21 读回验收确认四个文件 ready、18 项 check 全部 passed（17 blocking、1 WARN 级检查）、当天两个 Silver 缺码均为 0；验收耗时 923.840 ms，四个 Sensor 均为 `RUNNING`。完整 run ID、筛除原因、报告路径和 hash 统一记录在技术方案 §13 P6。

管理员在首日验收后明确要求直接结案，取消剩余两个交易日观察门槛。本需求及 P6 无待开发、待启用或待观察的结案阻断；实际只完成一个交易日日常验收，不冒充连续三日验证。历史 310 个 ETF/日期缺口的 WARN 事实继续保留。四个 Sensor 进入日常维护，不改变默认 `STOPPED` 的代码定义、21:00 窗口、Basic/coverage 门禁或冲突不覆盖规则。

2026-09-05 事后治理回归发现并修复两项登记缺口：`ACTIVE_ASSET_DEFINITIONS` 补入两个 Silver asset，`ASSET_CHECK_GOVERNANCE` 补入四个 ETF 日线资产。修复提交为 `a5f995fa`，check 名称直接复用 `run_contracts.etf_daily`，没有复制字符串或改变 WARN/blocking 口径。原 5 个失败修复后，两份治理测试为 16 passed；按下方固定命令执行的 ETF 日线、治理和静态门禁扩大回归为 321 passed、609 个 subtests passed，修改文件 Ruff 通过。该修复没有修改生产 Definitions、Sensor、Check、Lake 文件或正式 Dagster 状态。

各阶段已按技术方案独立获批并交付执行证据。后续历史修复或范围扩展仍需另行审计和授权，本次结案不提供额外写入许可。

---

## 20. 验证命令

开发期必须从 `lake_console/orchestrator` 一次执行 ETF 日线专项、全局资产治理、Check governance 与静态门禁；只运行 `tests/test_etf_daily_*.py` 不构成完整验收：

```bash
uv run python -m pytest -q \
  tests/test_etf_daily_*.py \
  tests/test_asset_governance_contracts.py \
  tests/test_asset_check_incremental_governance.py \
  tests/test_run_contract_static_gates.py
uv run ruff check --select E9,F63,F7,F82 src tests
uv run ruff check <本次新增和修改的 Python 文件>
```

两份通用治理测试分别约束 active Definitions 与 Catalog、blocking check specs 与 Check governance 的精确集合关系，禁止再以数据集专项测试代替全局登记验收。

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
