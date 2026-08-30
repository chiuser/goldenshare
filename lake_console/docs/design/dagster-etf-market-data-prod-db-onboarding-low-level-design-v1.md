# ETF Basic 与历史分钟 DG 接入低层设计（LLD）v1

状态：架构口径已收敛；P0-P2 已完成；P3 及以后尚未授权；N3B 与 N6 按后续阶段评审；尚未授权 Bootstrap、事件补录或 Sensor 启用

创建日期：2026-08-29

最近更新：2026-08-30

对应技术方案：[ETF 市场数据 DG 接入技术方案 v1](./dagster-etf-market-data-prod-db-onboarding-plan-v1.md)

上游 Prod 方案：[ETF 基础信息重建与下游数据审计清理技术方案 v1](../../../docs/architecture/etf-basic-rebuild-and-downstream-data-audit-cleanup-plan-v1.md)

上游 Prod LLD：[ETF 基础信息重建与下游数据审计清理 LLD v1](../../../docs/architecture/etf-basic-rebuild-and-downstream-data-audit-cleanup-low-level-design-v1.md)

Prod 分钟方案：[ETF 历史分钟行情数据集接入方案 v1](../../../docs/datasets/etf-mins-dataset-development.md)

Prod 分钟 LLD：[ETF 历史分钟行情数据集 LLD v1](../../../docs/datasets/etf-mins-dataset-low-level-design-v1.md)

Basic 源文档：[Tushare ETF 基础信息](../../../docs/sources/tushare/ETF专题/0385_ETF基础信息.md)

分钟源文档：[Tushare ETF 历史分钟行情](../../../docs/sources/tushare/ETF专题/0387_ETF历史分钟行情.md)

---

## 1. 这份 LLD 要解决什么

这份文档把已经确认的技术方案下沉到可以直接编码的粒度。实现者不需要重新猜资产怎么拆、文件放哪里、Basic 如何冻结、Prod SQL 怎么写、候选如何校验、失败时能不能覆盖旧文件。

核心结论只有两条：

1. ETF Basic 由 DG 自己从 Tushare 拉取，Raw 保存源站完整快照，Silver 只保留 `.SH/.SZ`，两层都按内容 hash 保存不可变版本。
2. ETF 分钟从 Prod DB 按“交易日范围 + 频率”整批读取到 staging；Prod SQL 不按 Basic 删代码，候选通过导出完整性、字段/分区合同和最新 `silver_etf_basic` 身份校验后先落正式 Raw。应覆盖缺口、五频覆盖和分钟网格由 DuckDB 审计本地 Raw；N3B 冻结后统一落成 Raw 的第三项 blocking check，三项 Raw checks 共同决定日常 readiness 和 Silver 能否生成。

本 LLD 不改变以下业务口径：

- 历史补录只看执行时最新 Basic Silver，不寻找历史 Basic。
- 最新 Basic 只决定“这次应该检查谁”，不反向删除 Lake 中已经存在的退市 ETF 历史分钟。
- 2025 年及以前的专项补录不允许修改任何 `trade_date >= 2026-01-01` 的 ETF 分钟文件。
- Silver 是完整性审计后的准入层，不在 Silver 修价格、补 bar、改 VWAP 或重算成交量。

---

## 2. 开工状态与拍板门禁

本 LLD 已经把推荐实现写完整。N3 的执行顺序已经确认：Direct Lake Bootstrap 先完成批准范围的 Raw 物理文件，再做 N3，不因单个分区的质量结论回滚已经安全落地的 Raw。N3B 冻结后，日常链把 `bar_domain` 作为第三项 Raw blocking check；失败会阻断该日及后续日常连续性和 Silver。全局 N3 policy 尚未冻结时，P10 日常 Sensors 仍不得启用。当前状态如下：

| 编号 | 结论 | 状态与阻断范围 |
| --- | --- | --- |
| N1 | Basic 使用 `snapshot_id=<Raw内容hash>/part-000.parquet` 的 content-addressed 不可变版本，不建 `current` 文件；hash 是 DG Raw 自身可复算内容身份，不要求与 Prod 一致；同时检查 Dagster 最新 Raw 与最新 Silver materialization、各自 checks、内容 hash 对齐和两层当天 freshness，失败或不新鲜不回退 | 已确认；Basic path、writer、latest-only selector 可按本文合同开发 |
| N2 | ETF 不读取 `ops.task_run`、`task_run_node` 或任何其它 Prod `ops.*`；日常只在 Sensor 做一次 Prod Raw 五频代码 coverage，Raw asset 不重复 probe、不做导出前后 fingerprint | 已关闭；不修改 `lake_console/AGENTS.md` 白名单 |
| N3 | 分钟 Raw 完整性审计拆成 N3A 观察/profile 与 N3B policy/decision | 执行顺序已确认；N3A 的规则建议不生效，N3B 待管理员看过真实报告后拍板；Bootstrap 不回滚 Raw，日常三项 Raw checks fail-closed |
| N4 | 首次 Bootstrap 截止日以每次执行前动态审计水位为准，不写死日期 | 已确认；具体日期在 P6 plan 时冻结 |
| N5 | 正式分钟文件只允许新增或语义相同复用；内容冲突立即停止，绝不自动覆盖 | 已确认；约束日常 writer、Bootstrap 和 repair 边界 |
| N6 | Basic 与分钟 Sensor 的上海时间运行窗口在上线前确认；全部先以 `STOPPED` 发布 | 可延后；只阻断 P10 启用，不阻断前序代码 |

当前没有需要立即补充拍板的架构口径。P0-P2 已经获准并完成；P3 及以后仍须逐阶段另行授权。首次分钟 Raw 物理写入必须使用 P6 plan 动态冻结的 N4 水位，并执行 N5 冲突策略。N3 固定拆为 P7A observation/profile 和 P7B policy freeze/decision 两步；P7A 完成但 P7B 尚未确认期间，不得生成 `silver_eligible`、写 Silver、补 green check event 或启用分钟日常 Sensors。

---

## 3. 当前代码影响面

### 3.1 已检查的主链

本轮按仓库规则先做了 CodeGraph 和当前代码核验。需要接入或复用的主链是：

```text
TushareResource
-> tushare_api_io full-file 分页
-> ETF Basic staging / hash / immutable promote
-> raw_tushare_etf_basic
-> silver_etf_basic
-> latest-only Basic selector

ProdPostgresResource(read-only)
-> daily Sensor one etf_minute_bar five-frequency coverage probe
-> Prod etf_minute_bar set-based query
-> run-scoped staging
-> Basic request-scope + file-contract validation
-> raw_etf_mins_* atomic promote
-> DuckDB local Raw N3A observation/profile
-> administrator-reviewed N3B policy freeze
-> partition decision manifest
-> raw_etf_mins_* three blocking checks
-> silver_etf_mins_* audited exact copy
```

### 3.2 可复用与禁止照搬

| 当前实现 | 可复用 | 不能照搬 |
| --- | --- | --- |
| `defs/resources.py` | `TushareResource`、`DuckDBResource`、`ProdPostgresResource.connect_readonly_transaction()`、只读 DuckDB attach 连接串 | 不新增第二套 Tushare/Postgres client，不用 write resource |
| `defs/tushare_api_io.py` | 显式字段、`limit/offset` 短页分页、空结果阻断、小快照写 Parquet；ETF 原样复用现有分页行为 | 普通 full-file helper 不能直接覆盖一个固定正式文件；ETF Basic 要把 helper 目标指向 staging，再按回读内容 hash 定位正式版本；不得增加 ETF 专属页数/行数熔断，也不得在 ETF asset 里另写一套分页循环 |
| `defs/assets/stock_basic.py` | full snapshot asset、中文 metadata、Raw→Silver 分层 | 股票 Basic 是单 current file，ETF Basic 是不可变版本；股票 Silver 筛选也不同 |
| `defs/prod_db/stk_mins.py`、`defs/asset_guards/stk_mins_prod_readiness.py` 与 `defs/assets/stk_mins.py` | 显式列、只读 attach、`postgres_query`、Sensor 五频代码物理覆盖和单次明细导出后的本地范围校验 | 当前股票链还叠加 TaskRun，并在五个 Raw asset 内各重查本频 coverage；ETF 明确不复制这两层重复门禁。股票 writer 在 Prod SQL 带代码集合，ETF 明细 SQL 也禁止带 Basic 代码条件 |
| `defs/assets/index_mins*.py` | 单日单频 staging、DuckDB set-based validation、原子提升、目标冲突停止 | 指数 active pool、fallback、90/120 分钟派生都不进入 ETF 链 |
| `defs/sensors/readiness.py` | materialization 与 blocking check 绑定、freshness、fail-closed | 不能逐日深扫 event history，不能用“文件存在”冒充 ready |
| `defs/bootstrap/stk_mins_bse_history_recovery*.py` | 一个实现模块配一个多 subcommand CLI、分段确认、批次、checkpoint | ETF 保留七个授权阶段，但只新增一个实现模块和一个 CLI；不读取旧 Lake、不用 Kopia、不把 runless event 混进物理写入 |

### 3.3 不受影响的边界

- 不修改 Prod 的 `DatasetDefinition`、planner、dispatcher、worker、schedule 或数据库表。
- 不引入 `fund_daily`、`fund_adj`、ETF 申赎、ETF 实时行情。
- 不修改股票分钟、指数分钟或它们的分区集合。
- 不读取 `core_serving.etf_basic` 作为 DG Basic 来源。
- 不建立 ETF 激活池、requestable manifest 或 current pointer。
- 不新增本地 ClickHouse serving。
- 不新增环境变量、数据库表或业务状态表。

---

## 4. 最终 Definition 与模块清单

### 4.1 Dagster 名称

Assets：

```text
raw_tushare_etf_basic
silver_etf_basic

raw_etf_mins_1m
raw_etf_mins_5m
raw_etf_mins_15m
raw_etf_mins_30m
raw_etf_mins_60m

silver_etf_mins_1m
silver_etf_mins_5m
silver_etf_mins_15m
silver_etf_mins_30m
silver_etf_mins_60m
```

Jobs：

```text
raw_etf_basic_update_job
silver_etf_basic_update_job
raw_etf_mins_update_job
silver_etf_mins_update_job
```

Sensors：

```text
etf_mins_trade_day_sensor
raw_etf_basic_update_job_sensor
silver_etf_basic_update_job_sensor
raw_etf_mins_update_job_sensor
silver_etf_mins_update_job_sensor
```

`etf_mins_trade_day_sensor` 只负责根据 `silver_trade_calendar` 注册 `cn_a_etf_mins_trade_days`，不请求 Prod/Tushare、不写 Parquet。其余四个 Sensor 与对应 Job 同名跟随。

### 4.2 需要新增的稳定模块

```text
src/orchestrator/defs/run_contracts/etf_basic.py
src/orchestrator/defs/run_contracts/etf_mins.py
src/orchestrator/defs/assets/etf_basic.py
src/orchestrator/defs/assets/etf_mins.py
src/orchestrator/defs/checks/etf_basic_checks.py
src/orchestrator/defs/checks/etf_mins_checks.py
src/orchestrator/defs/asset_guards/etf_basic_readiness.py
src/orchestrator/defs/asset_guards/etf_mins_lake_readiness.py
src/orchestrator/defs/asset_guards/etf_mins_prod_readiness.py
src/orchestrator/defs/prod_db/etf_mins.py
src/orchestrator/defs/jobs/etf_basic_update.py
src/orchestrator/defs/jobs/etf_mins_update.py
src/orchestrator/defs/sensors/etf_basic_sensor.py
src/orchestrator/defs/sensors/etf_mins_partition_sensor.py
src/orchestrator/defs/sensors/etf_mins_sensor.py
src/orchestrator/defs/bootstrap/etf_mins_bootstrap.py
src/orchestrator/defs/bootstrap/etf_mins_bootstrap_cli.py
```

### 4.3 需要修改的公共事实文件

```text
src/orchestrator/defs/paths.py
src/orchestrator/defs/partitions.py
src/orchestrator/defs/tushare_api_io.py
src/orchestrator/defs/run_contracts/asset_column_schemas.py
src/orchestrator/defs/catalog/lake_assets.py
src/orchestrator/defs/catalog/name_mapping.py
```

Definitions 使用现有 `load_from_defs_folder` 自动发现模式。实现验收必须证明上述 assets/checks/jobs/sensors 真正进入正式 Definitions，不能只做到模块可 import。

### 4.4 Asset factory 与 config 骨架

Basic 两层不使用 Dagster partition；版本由物理路径和 materialization metadata 表达：

```python
@asset(name="raw_tushare_etf_basic", group_name="etf_basic", ...)
def raw_tushare_etf_basic(
    context: AssetExecutionContext,
    tushare: TushareResource,
) -> MaterializeResult: ...

@asset(
    name="silver_etf_basic",
    group_name="etf_basic",
    deps=["raw_tushare_etf_basic"],
    ...,
)
def silver_etf_basic(
    context: AssetExecutionContext,
    config: EtfBasicSilverConfig,
) -> MaterializeResult: ...
```

```python
class EtfBasicSilverConfig(Config):
    raw_snapshot_reference: EtfBasicRawSnapshotReference
```

Basic Raw 是 no-time snapshot，不接收 `eligibility_as_of` 或任何业务输入。`observed_at` 和上海观测日由 asset 开始时的运行时钟生成；Tushare `business_params` 固定为 `{}`。`eligibility_as_of` 只属于分钟任务启动时的 `EtfBasicSilverSnapshotReference`，不能提前塞进 Basic Raw/Silver materialization。

分钟五频必须由同一个 factory 生成，禁止复制五份 writer：

```python
def build_raw_etf_mins_asset(*, minutes: int) -> AssetsDefinition: ...
def build_silver_etf_mins_asset(*, minutes: int) -> AssetsDefinition: ...

RAW_ETF_MINS_ASSETS = tuple(
    build_raw_etf_mins_asset(minutes=minutes)
    for minutes in ETF_MINS_ASSET_FREQS
)
SILVER_ETF_MINS_ASSETS = tuple(
    build_silver_etf_mins_asset(minutes=minutes)
    for minutes in ETF_MINS_ASSET_FREQS
)
```

Raw factory 固定 `partitions_def=cn_a_etf_mins_trade_days`、`deps=["silver_etf_basic"]` 和该 asset 的分钟频率；Silver factory 使用同一 partitions definition，并只依赖对应 Raw asset。分钟分区只从 `context.partition_key` 读取，频率只由 asset definition 决定，source method 固定在定义/metadata 中。只有 Raw 需要两个可序列化的小 reference：

```python
class EtfMinsRawConfig(Config):
    basic_snapshot_reference: EtfBasicSilverSnapshotReference
    prod_coverage_reference: EtfMinsProdCoverageReference
```

Sensor 只能通过共享 builder 生成 run config：

```python
def build_etf_mins_raw_run_config(
    *,
    partition_key: str,
    basic_reference: EtfBasicSilverSnapshotReference,
    prod_coverage_reference: EtfMinsProdCoverageReference,
) -> dict[str, object]: ...

```

Raw builder 为五个 op 生成同一 Basic reference 和同一次 Sensor 五频 coverage reference。测试必须证明五份 config 的 fingerprint 和观测时间一致，且没有 `partition_key`、`source_method`、`storage_id`、`ts_codes`、SQL 或可改写频率的字段。Raw asset 只校验 reference 结构、Basic hash 和 `context.partition_key`，不重新请求 Prod coverage。Silver 不需要 run config；正式 Silver job 在同一 run 内先执行五个 Raw blocking checks，通过后才运行 Silver assets。

---

## 5. 集中合同常量

### 5.1 `run_contracts/etf_basic.py`

```python
ETF_BASIC_SOURCE_API = "etf_basic"
ETF_BASIC_PAGE_LIMIT = 5_000
ETF_BASIC_DIAGNOSTIC_SAMPLE_LIMIT = 20
ETF_BASIC_LIST_STATUSES = ("D", "L", "P")
ETF_BASIC_CODE_SUFFIXES = ("OF", "SH", "SZ")
ETF_BASIC_SILVER_SUFFIXES = ("SH", "SZ")

ETF_BASIC_SOURCE_COLUMNS = (
    "ts_code", "csname", "extname", "cname", "index_code", "index_name",
    "setup_date", "list_date", "list_status", "exchange",
    "mgr_name", "custod_name", "mgt_fee", "etf_type",
)
```

同时定义并测试：

```text
normalize_etf_basic_snapshot_rows(...)
compute_etf_basic_snapshot_hash(...)
compute_etf_basic_silver_content_hash(...)
compute_etf_requestable_target_hash(...)
classify_etf_basic_requestability(...)
```

这些 helper 定义 DG 自己的内容身份，不复刻 Prod hash，也不 import `src.foundation`。固定 fixture 必须同时覆盖“相同 Raw Parquet 回读内容得到相同 hash”和“14 字段任一业务值变化都会改变 hash”。

### 5.2 `run_contracts/etf_mins.py`

```python
ETF_MINS_SOURCE_FREQS = ("1min", "5min", "15min", "30min", "60min")
ETF_MINS_ASSET_FREQS = (1, 5, 15, 30, 60)
ETF_MINS_SENSOR_WINDOW_LIMIT = 10
ETF_MINS_BOOTSTRAP_BATCH_TRADE_DAY_LIMIT = 20
ETF_MINS_BOOTSTRAP_MAX_TARGET_FILES = 10_000
ETF_MINS_BOOTSTRAP_DISK_SAFETY_MULTIPLIER = 1.25
ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT = 20
ETF_MINS_HISTORICAL_PROTECTION_CUTOFF = date(2026, 1, 1)
ETF_MINS_SOURCE_COLUMNS = (
    "ts_code", "freq", "trade_time", "open", "close", "high", "low",
    "vol", "amount", "vwap", "exchange",
)
```

只保留一份 `1 <-> 1min` 双向映射。paths、asset factory、SQL builder、checks、jobs 和 catalog 全部消费这一份映射；出现第二份手写映射时静态门禁失败。

分钟 coverage 与明细读取直接复用 `ProdPostgresResource` 现有只读事务和 DuckDB conninfo，不新增 ETF 专属 timeout 或 conninfo helper。P0 记录真实耗时；若现有资源级超时确实不足，必须另做共享配置审计，不能在本数据集合同里临时加常量。

### 5.3 配置与引用审计

本方案不新增环境变量、数据库配置或页面开关。所有可变运行输入和代码常量必须只出现在下表位置：

| 名称 | 默认/来源与持久化 | 作用范围与消费者 | 依赖与生效方式 | 运维可见性与测试门禁 |
| --- | --- | --- | --- | --- |
| Tushare token/限流 | 复用现有 `TushareResource` 环境配置；本方案不复制、不新增 | 仅 Basic Raw | 由现有 resource 注入；不进 run config/metadata | 缺失时 Basic fail-closed；静态测试证明无第二套 client/config |
| Basic Raw 业务 config | 不存在 | `raw_tushare_etf_basic` | no-time snapshot；参数恒为 `{}`，观测日来自运行时钟 | Launchpad 无过滤项；测试拒绝 `eligibility_as_of/ts_code/list_status` 等输入 |
| `ETF_BASIC_PAGE_LIMIT=5_000` | `run_contracts/etf_basic.py` 代码常量 | Basic Raw 调用现有通用 full-file helper | 使用现有 `limit/offset`，直到短页；不增加 ETF 专属页数或源行数熔断 | 请求参数、短页结束、跨页重复、列漂移和请求失败在 P2 随实现测试 |
| `EtfBasicRawSnapshotReference` | latest-only Raw selector 从最新 Raw materialization 和 checks 生成；由手工/测试 builder 及后续 Sensor 共用，只随单次 run config 持久化 | Basic Silver | 精确绑定当前 Raw URI/hash/fingerprint | UI 可见短 fingerprint；禁止 storage id，漂移立即失败 |
| `EtfBasicSilverSnapshotReference` | latest-only selector 从最新 Raw、最新 Silver materialization、两层 checks 和文件复算生成；只随单次分钟/Bootstrap 计划持久化 | 分钟 Raw、Bootstrap plan/apply | 两层内容 hash 必须对齐；Raw/Silver 观测时间都必须与 `eligibility_as_of` 同属上海自然日；最新失败/不新鲜不回退 | metadata/报告显示两个 hash、两个观测时间、日期和 requestable count/hash；禁止完整代码集合 |
| `EtfMinsProdCoverageReference` | Raw Sensor 一次 coverage probe 生成；只随日常 Raw run config 持久化 | 五个分钟 Raw assets | 必须绑定同一 Basic reference/日期；asset 只复核不重查 | UI 显示五频计数、短 fingerprint；测试证明合计只有 1 次 coverage |
| `EtfMinsRawConfig` | Raw Sensor builder 生成 | 五个 Raw assets | 只含 Basic reference + coverage reference；分区来自 `context.partition_key`，频率来自 asset definition | 静态测试拒绝 partition/source method、SQL、代码全集和 storage id |
| Silver 分钟 config | 不存在 | 五个 Silver assets | 分区来自 `context.partition_key`；正式 job 先执行 Raw blocking checks | Launchpad 无额外准入参数；Raw check 失败时 Silver step 不执行 |
| `ETF_MINS_SENSOR_WINDOW_LIMIT=10` | `run_contracts/etf_mins.py` 代码常量 | Raw/Silver Sensors 与 batch readiness | 每 tick 只审计最近 10 个 expected trade dates | cursor/SQL/file count 性能测试；更早缺口交给 Bootstrap |
| `ETF_MINS_BOOTSTRAP_BATCH_TRADE_DAY_LIMIT=20`、`ETF_MINS_BOOTSTRAP_MAX_TARGET_FILES=10_000`、`ETF_MINS_BOOTSTRAP_DISK_SAFETY_MULTIPLIER=1.25` | `run_contracts/etf_mins.py` 代码常量 | plan/query budget/raw-apply/空间门禁 | 单频单批最多 20 日、单 plan 最多 10,000 个 Raw 目标，空间按 1.25 倍安全系数 | plan 报告显示批次/查询/文件/空间；任一超限拒绝 |
| `ETF_BASIC_DIAGNOSTIC_SAMPLE_LIMIT=20`、`ETF_MINS_DIAGNOSTIC_SAMPLE_LIMIT=20` | 各自 run contracts 代码常量 | checks、coverage、报告和 reason samples | 只限制诊断样本，不截断事实计数或 N3 明细合同 | 测试证明计数完整、样本有界 |
| `ETF_MINS_HISTORICAL_PROTECTION_CUTOFF=2026-01-01` | `run_contracts/etf_mins.py` 代码常量 | P11 plan/apply/protection audit | CLI 只能确认等于该值，不能改成更晚日期 | 边界正反测试；写前写后保护清单零变化 |
| `cn_a_etf_mins_trade_days` | 现有 Dagster instance 的专属动态分区集合 | 分钟 assets/jobs/sensors/events | 仅 partitions 入口或 trade-day sensor 新增；不代表数据 ready | UI 可见；测试证明不复用股票/指数分区、不越界注册 |

任何实现若增加表外 config、默认值或消费者，必须先更新本表并完成全量消费者和生效方式审计；不得把常量散落到 Sensor、CLI、页面和文档各写一份。

---

## 6. 字段合同

### 6.1 ETF Basic Raw

`RAW_TUSHARE_ETF_BASIC_SCHEMA`：

| 字段 | DuckDB/Parquet 类型 | 允许空 | 说明 |
| --- | --- | --- | --- |
| `ts_code` | `VARCHAR` | 否 | ETF 代码，Raw 允许 `.SH/.SZ/.OF` |
| `csname` | `VARCHAR` | 是 | 中文简称 |
| `extname` | `VARCHAR` | 是 | 扩位简称 |
| `cname` | `VARCHAR` | 是 | 中文全称 |
| `index_code` | `VARCHAR` | 是 | 跟踪指数代码 |
| `index_name` | `VARCHAR` | 是 | 跟踪指数名称 |
| `setup_date` | `VARCHAR` | 是 | 源端 `YYYYMMDD` 字符串 |
| `list_date` | `VARCHAR` | 是 | 源端 `YYYYMMDD` 字符串 |
| `list_status` | `VARCHAR` | 否 | 只允许 `L/P/D` |
| `exchange` | `VARCHAR` | 是 | 源端交易所值 |
| `mgr_name` | `VARCHAR` | 是 | 管理人简称 |
| `custod_name` | `VARCHAR` | 是 | 托管人名称 |
| `mgt_fee` | `DOUBLE` | 是 | 源端数值，不在 Raw 舍入 |
| `etf_type` | `VARCHAR` | 是 | ETF 类型 |

Raw 不增加 `api_name/fetched_at/raw_payload/observed_at/snapshot_id` 列。运行信息只进 Dagster metadata 和物理路径。

### 6.2 ETF Basic Silver

`SILVER_ETF_BASIC_SCHEMA` 保留同名 14 字段，不裁字段：

- `setup_date/list_date` 改为 `DATE`。
- `mgt_fee` 改为稳定 `DECIMAL(12,6)`。
- 其余字段仍为 `VARCHAR`。
- 只保留 Raw 中 `ts_code` 以 `.SH` 或 `.SZ` 结尾的行。
- 不增加 `list_status='L'`、`list_date IS NOT NULL` 或 `list_date <= today` 筛选。

契约测试必须断言 Silver 字段集合完整覆盖 Raw 字段集合，且两者字段顺序一致。

### 6.3 ETF 分钟 Raw/Silver

`RAW_ETF_MINS_SCHEMA` 与 `SILVER_ETF_MINS_SCHEMA` 第一版完全一致：

| 字段 | 类型 | 入库合同 |
| --- | --- | --- |
| `ts_code` | `VARCHAR` | 非空，`.SH/.SZ` |
| `freq` | `VARCHAR` | 非空，只能是当前资产固定源频率 |
| `trade_time` | `TIMESTAMP` | 非空，属于路径交易日 |
| `open` | `DOUBLE` | Raw 保留源值，允许空；空值、非有限、非正数由 N3A 观察、N3B 决定准入 |
| `close` | `DOUBLE` | Raw 保留源值，允许空；空值、非有限、非正数由 N3A/N3B 处理 |
| `high` | `DOUBLE` | Raw 保留源值，允许空；OHLC 关系由 N3A/N3B 处理 |
| `low` | `DOUBLE` | Raw 保留源值，允许空；OHLC 关系由 N3A/N3B 处理 |
| `vol` | `BIGINT` | Raw 保留源值，允许空；空值和负数由 N3A/N3B 处理 |
| `amount` | `DOUBLE` | Raw 保留源值，允许空；空值、非有限和负数由 N3A/N3B 处理 |
| `vwap` | `DOUBLE` | Raw 保留源值，允许空；非有限或关系异常由 N3A/N3B 处理 |
| `exchange` | `VARCHAR` | 原始值原样保存；必须能按 P0 冻结映射与 `ts_code` 后缀完成 Basic 身份校验 |

`trade_date` 只在路径中表达，不加入文件。Raw/Silver 不增加 `source/fetched_at/task_run_id/basic_hash` 等治理列。

这里的“Raw/Silver schema 相同”只表示列名、顺序、物理类型相同，不表示 Silver 接受所有 Raw 分区。Raw 前只阻断文件不可读、字段或物理类型错误、主键空或重复、日期/频率错位、Basic 身份污染和未知新增代码。价格空值、负成交量、OHLC 关系、分钟网格和内部空洞全部留给 N3；Silver 只整分区复制 N3B 判定可准入的 Raw，不修值、不删行。

开发前必须对 Prod Raw 做有界样本验证：分别选择 `.SH`、`.SZ` 代码和五个频率，记录 `exchange` 的实际 distinct 值，冻结“代码后缀 -> 源分钟 exchange 值”的比较映射和反例测试。这个映射只用于比较，Parquet 中的 `exchange` 永远保存源站原值，禁止改写成 Basic 的 `SH/SZ`。

---

## 7. 路径合同

### 7.1 正式 Lake

```text
/Volumes/datasource/data_lake/raw/tushare/etf_basic/
  snapshot_id=<64位小写sha256>/part-000.parquet

/Volumes/datasource/data_lake/silver/basic/etf_basic/
  snapshot_id=<同一raw_snapshot_hash>/part-000.parquet

/Volumes/datasource/data_lake/raw/tushare/etf_mins/
  freq=<1min|5min|15min|30min|60min>/
  trade_date=YYYY-MM-DD/part-000.parquet

/Volumes/datasource/data_lake/silver/quote/etf_mins/
  freq=<1min|5min|15min|30min|60min>/
  trade_date=YYYY-MM-DD/part-000.parquet
```

`defs/paths.py` 新增：

```text
PATH_TEMPLATE_SNAPSHOT_ID = "{snapshot_id}"
raw_etf_basic_snapshot_path(root, snapshot_id)
silver_etf_basic_snapshot_path(root, snapshot_id)
raw_etf_mins_path(root, freq, partition_key)
silver_etf_mins_path(root, freq, partition_key)
etf_basic_staging_path(staging_root, run_id, layer)
etf_mins_staging_path(staging_root, operation_id, layer, freq, partition_key)
```

所有 helper 必须校验 hash、run/operation id、频率和 ISO 日期，禁止 `/`、`..` 和未登记频率。

### 7.2 Staging 与报告

候选只能位于：

```text
/Volumes/datasource/data_lake_staging/etf_basic/run_id=<run_id>/...
/Volumes/datasource/data_lake_staging/etf_mins/operation_id=<operation_id>/...
```

Bootstrap 的 frozen plan、checkpoint、候选文件清单、`finalized_raw_manifest.parquet`、`raw_final_report.json`、N3 observation/decision、`silver_work_manifest.parquet`、`finalized_silver_manifest.parquet` 和 `physical_final_report.json` 都留在对应 operation 目录。它们不是正式 asset，不得被其它数据集当作 Lake 事实源。

路径用途必须分开：P0 的探索性有界样本/profile 报告可以写 `/private/tmp`，因为它不被后续写入入口消费；P6 开始的正式 frozen plan，以及任何会被 raw-apply、raw-observe、raw-decide、silver-apply、partitions 或 events 消费的报告，必须位于 `/Volumes/datasource/data_lake_staging/etf_mins/operation_id=<operation_id>/`。正式 plan CLI 的 `--report-path` 必须校验这个边界，不能默认为 `/private/tmp`。事件补录验收完成前不自动清理 operation 目录。成功日常 run 只清理自己明确创建的候选文件和空目录，失败候选保留路径并在 metadata 中给出人工处理说明。

---

## 8. Basic 内容 hash 与不可变版本

### 8.1 Raw snapshot hash

算法只服务 DG Raw 的 content-addressed 版本，必须从写入 staging 后按 Raw schema 回读的逻辑内容计算，不依赖 Prod hash：

1. 只取 14 个业务字段。
2. 按 `ts_code` 升序排列。
3. 每行编码为按字段顺序排列的 JSON array。
4. `None -> null`；所有 `VARCHAR`（包括 `setup_date/list_date`）使用 Parquet 回读原值；`mgt_fee DOUBLE` 使用回读后 IEEE-754 值的 `float.hex()` 规范字符串，避免十进制格式和 Prod `DECIMAL` 语义影响 DG hash。
5. `json.dumps(..., ensure_ascii=False, separators=(",", ":"))`。
6. 对 UTF-8 bytes 计算 SHA-256。

`snapshot_id` 就是该 64 位小写 hash。不得用 run id、日期或抓取时间冒充内容版本，也不得把 Prod 兼容 hash 当作 DG 路径身份。若专项审计需要跨系统核对，可另算兼容 hash，但不得写入 path、run key、run config 或 completion identity。

### 8.2 Silver content hash

Silver 使用同一字段顺序和排序规则，但 `DATE` 编码为 ISO `YYYY-MM-DD`，`DECIMAL` 使用规范十进制字符串。Silver 路径仍使用 Raw `snapshot_id`，另外在 metadata 中记录 `silver_content_hash`。

### 8.3 同内容复用与冲突

- 正式目标不存在：候选全部通过校验后 `os.replace()`。
- 目标已存在且可复算出相同 hash：复用，不改文件。
- 目标已存在但 schema、行数或 hash 不同：`etf_basic_snapshot_conflict`，停止。
- 不建 `current` 文件，不扫描目录名猜最新版本。

“latest-only 版本”同时读取 Dagster 最新 Raw 与最新 Silver materialization，要求各自 blocking checks 精确绑定且通过，并要求 Silver 的 `raw_snapshot_hash` 等于最新 Raw hash；Raw/Silver 各自的 `observed_at` 都必须与本次 `eligibility_as_of` 同属上海自然日。任一层失败、两层内容未对齐或任一层不新鲜时立即 fail-closed，绝不向前搜索旧成功版本。相同内容可以复用同一物理文件，但 Basic Raw 仍必须完成当天实际源请求并产生当天 materialization。分钟任务也不得通过 `max(snapshot_id)`、目录 mtime 或文件创建时间选版本。

---

## 9. ETF Basic Raw 写入

### 9.1 请求合同

正式请求：

```python
api_name = "etf_basic"
business_params = {}
fields = ETF_BASIC_SOURCE_COLUMNS
limit = 5_000
offset = 0, 5_000, ...
```

不允许暴露 `ts_code/index_code/list_date/list_status/exchange/mgr` 为 Dagster config 或运营输入。

当前只读实测（2026-08-29）：无业务参数默认字段和显式 14 字段均返回 1,829 行；状态分布 `L=1658/P=44/D=127`，后缀 `SH=1033/SZ=793/OF=3`。这些只是本次观测，不是代码阈值。

本地源文档声明单页上限 5,000 且支持 `limit/offset`；当前 `tushareMcp` 包装没有暴露这两个参数，因此 P0 已用实际 `TushareResource` 完成受控 `limit=5000, offset=0/5000` 边界验证：第一页返回 1,829 行，第二个 offset 返回 0 行，字段顺序一致且没有重复 `ts_code`。ETF Basic 原样复用现有 full-file helper，按短页结束，不修改 helper，不增加 ETF 专属页数/行数熔断，也不得在 ETF asset 中复制 `_fetch_all_pages`。正常分页、第二页请求失败、跨页重复和列漂移在 P2 随 Basic Raw 实现测试。

### 9.2 Writer 顺序

```text
validate lake/staging roots are same filesystem
-> fetch all pages to run-scoped staging
-> exact columns / non-empty / source count validation
-> key/status/suffix/exchange validation
-> re-read staging with Raw schema
-> compute and recompute raw_snapshot_hash from that same read-back contract
-> compare immutable target
-> os.replace or reuse
-> emit materialization metadata
```

Basic 每页最多 5,000 行，使用现有 helper 继续请求直到遇到短页。当前真实规模为 1,829 行，因此允许 Python 保存这份小型 API 返回和构造参数；正式 Parquet 写入仍使用现有 DuckDB helper。任一页失败、空结果、重复 `ts_code`、未知状态/后缀或行数不一致都不能发布新版本，也不能触碰既有版本。不设置没有现实依据的 ETF 专属最大页数或最大源行数。

### 9.3 Raw materialization metadata

至少包含：

```text
dagster/uri
dagster/row_count
goldenshare/observed_columns
goldenshare/source_row_count
goldenshare/raw_snapshot_hash
goldenshare/observed_at
goldenshare/api_name = etf_basic
goldenshare/business_params = {}
goldenshare/fields
goldenshare/page_limit
goldenshare/page_count
goldenshare/status_counts
goldenshare/suffix_counts
goldenshare/list_date_null_counts
goldenshare/write_mode = write_new | reuse_existing
```

新增 metadata key 必须通过现有 `build_materialization_metadata` 命名空间和静态治理门禁，禁止裸 key。

---

## 10. ETF Basic Silver 写入

### 10.1 输入引用

Silver run 必须冻结一个 `EtfBasicRawSnapshotReference`：

```text
raw_snapshot_hash
raw_uri
raw_observed_at
reference_fingerprint
```

Sensor 只检查 Dagster 最新 Raw materialization，并在内部用其 storage id 确认 checks 精确绑定；序列化到 run config 的 reference 只含上面这些稳定内容字段。Asset 开始时重新校验 uri、文件 hash 和 reference fingerprint。运行过程中即使新 Raw 版本出现，本次 Silver 仍只消费已冻结版本。

### 10.2 Silver SQL

```sql
SELECT
  ts_code,
  csname,
  extname,
  cname,
  index_code,
  index_name,
  try_strptime(setup_date, '%Y%m%d')::DATE AS setup_date,
  try_strptime(list_date, '%Y%m%d')::DATE AS list_date,
  list_status,
  exchange,
  mgr_name,
  custod_name,
  CAST(mgt_fee AS DECIMAL(12, 6)) AS mgt_fee,
  etf_type
FROM read_parquet(<frozen_raw_path>, hive_partitioning=false)
WHERE ends_with(ts_code, '.SH') OR ends_with(ts_code, '.SZ')
ORDER BY ts_code
```

若源日期非空但转换为 `NULL`，或数值无法转成 `DECIMAL(12,6)`，整个版本失败。不得把转换失败行丢掉。

### 10.3 Silver 对账

必须用 DuckDB 集合 SQL证明：

- Silver code set 精确等于 Raw `.SH/.SZ` code set。
- `filtered_out_count` 精确等于 Raw 非 `.SH/.SZ` 行数。
- 除允许的日期/数值类型标准化外，14 字段值等价。
- `EXCEPT ALL` 两个方向都为零。
- `silver_content_hash` 回读可复算。

### 10.4 Silver materialization metadata

至少包含：

```text
dagster/uri
dagster/row_count
goldenshare/observed_columns
goldenshare/raw_uri
goldenshare/raw_snapshot_hash
goldenshare/silver_content_hash
goldenshare/raw_observed_at
goldenshare/observed_at
goldenshare/filtered_out_count
goldenshare/status_counts
goldenshare/suffix_counts
goldenshare/write_mode = write_new | reuse_existing
```

metadata 不保存 Dagster storage id。check selector 可以在一次有界状态读取中临时使用 storage id 做精确绑定，但不得把它传进正式 run config、upstream batch id 或 completion identity。

---

## 11. 最新 Basic 的 fail-closed 冻结合同

新增 `select_latest_etf_basic_snapshot_reference(...)`，只检查两层各自最新 materialization，不按“ready”向前搜索旧版本；实现只做有界 Dagster 状态读取和两个单文件校验。

输入：

```text
DagsterInstance
eligibility_as_of            # Asia/Shanghai 的任务启动日期
required_freshness_date      # 等于 eligibility_as_of
```

输出 `EtfBasicSilverSnapshotReference`：

```text
raw_snapshot_hash
silver_content_hash
raw_uri
silver_uri
raw_observed_at
silver_observed_at
eligibility_as_of
requestable_code_count
requestable_code_hash
reference_fingerprint
```

算法：

1. 分别有界读取 `raw_tushare_etf_basic` 和 `silver_etf_basic` 的最新一条 materialization；不得扫描并回退到更早成功版本。
2. 要求最新 Raw 与最新 Silver 各自的上海本地 `observed_at` 都与 `eligibility_as_of` 同日。相同内容的 Raw 仍必须有当天实际源请求产生的最新 materialization，不能靠当天重做 Silver 给旧 Raw 续 freshness。
3. selector 内部使用两条最新 materialization 的 storage id，分别要求 Basic Raw 与 Silver blocking checks 精确绑定各自最新 materialization且全部通过。storage id 只在本次有界状态读取中使用，不进入输出 reference。
4. 要求最新 Silver metadata 的 `raw_snapshot_hash` 等于最新 Raw metadata 的 `raw_snapshot_hash`。若最新 Raw 内容已经变化而 Silver 尚未物化同一内容，立即 fail-closed；相同内容的再次 Raw materialization 因 hash 相等仍视为同一快照。
5. 分别回读最新 Raw 和 Silver 文件，复算 Raw/Silver hash，并要求路径绑定同一 `snapshot_id`。
6. 用第 12 节条件计算 requestable targets 和 hash。
7. 构造不可变 reference；后续 run config 只传 reference，不传完整代码数组。

完整代码集合只在 Asset/Bootstrap 内从冻结文件重新计算，不写 cursor、run key 或 Dagster metadata。metadata 只记录 count、hash 和最多 20 个异常样本。

---

## 12. 当前可请求集合与历史日期应覆盖集合

### 12.1 当前可请求集合

对冻结 Silver：

```sql
SELECT ts_code, list_date, exchange
FROM read_parquet(<frozen_silver>, hive_partitioning=false)
WHERE list_status = 'L'
  AND list_date IS NOT NULL
  AND list_date <= CAST(<eligibility_as_of> AS DATE)
  AND (
       (ends_with(ts_code, '.SH') AND exchange = 'SH')
    OR (ends_with(ts_code, '.SZ') AND exchange = 'SZ')
  )
ORDER BY ts_code
```

`requestable_code_hash` 复刻 Prod 的 target hash：按 `ts_code` 排序，每项只含 `ts_code/list_date/exchange`，使用 `sort_keys=True` 的紧凑 JSON 计算 SHA-256。

### 12.2 历史交易日 D 的 expected 集合

```text
expected(D) = requestable_at_task_start WHERE list_date <= D
```

不根据 D 查历史 Basic，也不根据今天的退市状态删除正式历史文件。

### 12.3 六类统计

每个日期/频率候选必须输出：

| 类别 | 精确定义 | 默认处理 |
| --- | --- | --- |
| `expected` | 当前 requestable 且 `list_date <= D` | 应覆盖 |
| `present` | 候选文件实际 distinct `ts_code` | 与各类做集合对账 |
| `missing` | `expected - present` | 允许原样记录到 Raw 审计；N3 关闭前不得进入 Silver |
| `known_non_required` | 代码在最新 Silver，但不属于 expected；包括 D/P、空上市日、未来上市或 D 早于上市日 | 不要求出现；若实际出现，保留并报告，不静默删除 |
| `retained_legacy` | 代码不在最新 Silver，但在本次执行前同一正式目标文件中已经存在 | 只允许随语义相同的旧文件复用；不得借新候选新增或改写 |
| `unexplained_new` | 代码不在最新 Silver，且同一正式目标文件此前不存在该代码 | 阻断提升，人工解释 |

这里把 `retained_legacy` 限定到“同一目标正式文件在执行前已经存在”的事实，避免为判断一个日常候选而全扫所有历史文件。若目标文件不存在，Basic 无法识别的候选代码一律是 `unexplained_new`。

---

## 13. Prod DB 只读合同

### 13.1 Allowlist

```text
raw_tushare.etf_minute_bar
```

禁止读取：

```text
任何 ops.* 表
core_serving.etf_basic
任何未列出的 raw/core/ops 表
```

ETF 分钟链不修改 `lake_console/AGENTS.md` 的 Prod allowlist，也不创建 `etf_mins_task_run.py`。当前股票分钟确实是“成功 TaskRun + Prod Raw 五频代码物理覆盖”双门禁；ETF 这里只复用后半段物理覆盖检查，因为 TaskRun 是执行状态，不是数据完整性证明。

### 13.2 明细 SQL

`defs/prod_db/etf_mins.py` 集中定义表、字段和两层 SQL builder。`postgres_query` 的远端 SQL 不能使用 psycopg 的 `%s` 占位符；它必须先校验频率属于白名单、起止时间是规范 ISO 时间且组成半开区间，再由专用 PostgreSQL literal helper 生成下列纯字符串：

```sql
SELECT
  ts_code, freq, trade_time, open, close, high, low,
  vol, amount, vwap, exchange
FROM raw_tushare.etf_minute_bar
WHERE freq = <validated_and_quoted_source_freq>
  AND trade_time >= TIMESTAMP <validated_and_quoted_start_datetime>
  AND trade_time < TIMESTAMP <validated_and_quoted_end_datetime>
ORDER BY ts_code, trade_time
```

第二层 `build_prod_etf_mins_duckdb_source_sql(...)` 只把上面的已验证远端 SQL 包进：

```sql
SELECT <11 explicit columns>
FROM postgres_query(<attached_database_literal>, <remote_query_literal>)
```

禁止把操作者原始字符串直接插值进 SQL。测试必须分别覆盖允许频率、非法频率、非法日期、反引号/引号注入样本和半开区间。

时间窗口为目标日 `[00:00:00, next day 00:00:00)`。SQL 中禁止出现：

- `SELECT *`
- Basic/Serving join
- `ts_code IN/ANY`
- `api_name/fetched_at/raw_payload`
- 任意写语句、DDL 或锁表语句

DuckDB 直接使用现有 `ProdPostgresResource.duckdb_connection_string()` 并以 `TYPE POSTGRES, READ_ONLY` attach，与 `stk_mins` 保持同一资源合同。conninfo 只在内存中的 attach 语句使用，不进入远端查询、日志、异常文本、run config 或 metadata；测试用脱敏 fake conninfo 验证，不快照真实凭据。ETF 不新增专用 conninfo parser 或 timeout 注入 helper。

### 13.3 Prod Raw 五频代码物理覆盖

`defs/prod_db/etf_mins.py` 只实现一套有界 batch coverage evaluator，日常用单日期模式，Bootstrap 水位用最多 10 个日期的模式。输入是冻结 Basic 的 `requestable targets(ts_code, list_date)`、1 到 10 个 SSE 开市日和五个源频率；SQL 用参数化 `unnest` 建立日期、requestable target 和频率关系，按 `list_date <= trade_date` 形成每个日期自己的 `expected(D) × freq`，再对 `raw_tushare.etf_minute_bar` 用主键前缀条件做 `EXISTS ... LIMIT 1`。单次查询按 `trade_date + freq` 返回 expected/present/missing 数量和每组最多 20 个缺失代码，不能返回分钟明细。禁止在 Python 或 SQL 调用层展开为“日期 × 频率”多次查询。

coverage/watermark 走 `ProdPostgresResource.connect_readonly_transaction()`，数组、日期和样本上限全部使用绑定参数，结束无论成功失败都 rollback。它与第 13.2 节的 DuckDB 明细 attach 是两种明确分开的执行策略，不能把 `%s` 参数合同误套到 `postgres_query` 远端字符串，也不能为了统一形式增加重复查询。P0 只测量并记录两条现有连接路径的真实耗时；若确需新增超时能力，另按共享 resource 配置评审，不在 ETF 模块内改写连接串。

这个 probe 的边界必须说清楚：

- 它只证明“当前 Basic 要求检查的每个代码，在目标日五个频率都至少存在一行”。
- 它不证明价格正确、每个频率 bar 数正确或日内没有空洞；这些属于 Raw 落湖后的 N3。
- 日常 Sensor 只有在五频全部无缺代码时才发起 Raw run，避免在 Prod 仍在写时过早固化一个残缺的不可变文件。
- 历史 Bootstrap 允许把缺代码或缺频率的物理事实原样落 Raw，再由 N3A 统一观察；不得把这条日常调度策略误写成 Raw 字段合同。

### 13.4 Sensor coverage reference 与单次导出合同

日常 Sensor 在提交 Raw Job 前只执行一次五频 probe，并冻结 `EtfMinsProdCoverageReference`：

```text
trade_date
basic_reference_fingerprint
expected_code_count / expected_code_hash
五频 expected/present/missing counts
coverage_observed_at
coverage_fingerprint
```

Raw asset 开始时只校验 reference 的日期、Basic reference fingerprint、expected code count/hash 和五频均为 `missing=0`，并重新回读 Basic 文件确认冻结 reference 未变。它不再请求 Prod coverage，也不在导出前后重复查询同一明细 scope。

随后每个日常 Raw asset 只执行一条单日单频明细查询；Bootstrap raw-apply 每个最多 20 个交易日的单频批次也只执行一条明细查询。实际导出 relation 在同一个 DuckDB connection 内完成 source row count、字段、日期/频率、主键、代码集合、exchange 和 staging 回读对账，不再增加第二遍 Prod fingerprint。该策略与当前 `stk_mins` writer 的“一次明细导出后本地校验”一致，同时去掉股票链在每个 Raw asset 内重复 coverage 的额外查询。

---

## 14. 分钟 Raw writer

### 14.1 Run config

日常五个 Raw assets 都接收同一形状的 `EtfMinsRawConfig`：

```text
basic_snapshot_reference
prod_coverage_reference
```

`prod_coverage_reference` 只证明 Sensor 当时为何允许启动，不代表分钟网格或字段值已经验收。

分区由 `context.partition_key` 提供，频率由 asset definition 固定，source method 也是定义常量，三者都不进入 config。完整 Basic 代码列表和 Prod SQL 也不进入 config。

### 14.2 单日单频写入顺序

```text
validate partition/frequency/config fingerprints
-> assert lake and staging roots available and same filesystem
-> revalidate frozen Basic reference; validate the carried Sensor coverage reference without querying Prod
-> build explicit-column Prod SQL
-> one DuckDB read-only postgres_query
-> COPY ordered rows to run-scoped staging parquet
-> re-read staging with hive_partitioning=false
-> stable transport/schema/date/freq/key/Basic identity validation
-> Basic request-scope set comparison
-> compare existing formal target if any
-> os.replace new target or reuse equivalent target
-> emit MaterializeResult
```

Python 只做参数、路径、少量计数和样本汇总；分钟明细的读取、join、差集、聚合、排序和 Parquet 写入全部由 DuckDB SQL 完成。

### 14.3 候选关系校验

一个 DuckDB connection 内建立：

```text
basic_all
requestable_targets
expected_targets_for_date
candidate_rows
candidate_codes
existing_target_rows（仅目标已存在时）
```

至少聚合下列字段。它们都进入 Raw metadata/audit 输入，但只有稳定门禁字段参与首次 Raw 提升：

```text
source_row_count
candidate_row_count
distinct_code_count
null_key_count
duplicate_key_count
date_mismatch_count
freq_mismatch_count
exchange_mismatch_count
invalid_ohlc_count
invalid_volume_amount_count
invalid_vwap_count
off_session_time_count
expected_count / present_count / missing_count
known_non_required_present_count
retained_legacy_count
unexplained_new_count
```

每类样本最多 20 个，稳定排序。禁止 `fetchall()` 拉回明细。

首次 Raw 提升的稳定门禁固定为：单次 source relation 与 staging 行数一致、Parquet 可回读、11 字段与物理类型正确、路径/日期/频率一致、主键非空且唯一、Basic reference 可复算、代码/源 `exchange` 按 P0 冻结映射能够解释，以及 `unexplained_new_count=0`。不通过第二次 Prod 查询证明第一次查询；传输正确性由同一 relation 的 source/staging/Raw 对账证明。

日常 Raw asset 由 Sensor coverage 保证启动时五频各代码至少存在一行，因此单频明细返回零行或缺失 expected code 时停止，不生成零行文件。历史 Bootstrap 不使用这条日常启动门禁：对 frozen plan 中每个 `trade_date + freq`，即使源 relation 对该日为零行，也必须生成一份具有完整 11 字段 schema 的显式零行 Raw Parquet，记录 `source_row_count=0/present_count=0/missing_count=expected_count`，再交给 N3A 分类。

`invalid_ohlc_count`、`invalid_volume_amount_count`、`invalid_vwap_count`、`off_session_time_count`、跨频率缺失、日内网格断点和边界点差异只作为 N3 输入，不参与历史 Raw 提升；历史 `missing_count` 和零行也同样进入 N3。日常链只有一个额外的一致性门禁：候选若与本次已经冻结为全绿的 Sensor coverage reference 矛盾，出现零行或 expected 缺失，立即停止且不重查 Prod。换句话说，Raw 前不把价格、成交或网格规则提前写死；日常覆盖引用与实际候选自相矛盾属于运行稳定性失败，数据值和分钟序列是否能进入 Silver 仍由 N3 决定。

### 14.4 N3A 本地 Raw 观察与 N3B 准入决策

N3 只读正式 Raw 和冻结的 Basic/交易日历，不对 Prod 做全量统计，不修改 Raw，不写 Silver，也不写 Dagster event。它必须拆成两个入口，不能在第一次看数据时顺手把规则生效：

```python
def observe_etf_mins_raw(
    *,
    lake_root: Path,
    duckdb: DuckDBResource,
    raw_bootstrap_report_path: Path,
    output_dir: Path,
) -> EtfMinsRawObservationResult: ...

def decide_etf_mins_raw(
    *,
    observation_summary_path: Path,
    approved_policy_version: str,
    output_dir: Path,
) -> EtfMinsRawDecisionResult: ...
```

N3A 是“先把事实摊开”，不能凭股票或指数经验先写死 ETF expected time grid。它生成实测 profile：

```text
每个频率实际 distinct clock time
每个 clock time 覆盖的 code-day 数和比例
每个 code/date/freq 的 row_count、min/max time、distinct time count
按年份、交易所和频率的分布变化
整日零行、零成交 bar、边界点的出现率
```

然后只做问题分类和计数：

- 整日五频全空
- 只有部分原生频率为空
- 某频率有数据但日内中间断点
- 只缺集合竞价或收盘边界点
- 源端合法零成交 bar

同时完成 Basic 六类集合、schema、主键、数值域和 exchange 对账。所有 SQL 使用列投影、分区裁剪和集合化聚合；建议按 `freq + year/date batch` 扫描，不在 Python 中逐文件或逐代码计算。

N3A 输出全部放在本次 `/Volumes/datasource/data_lake_staging/etf_mins/operation_id=<operation_id>/raw-observe/`：

```text
raw_file_manifest.parquet
raw_code_day_freq_profile.parquet
raw_grid_profile.parquet
raw_domain_profile.parquet
raw_issue_details.parquet
raw_partition_observation_manifest.parquet
raw_observation_summary.json
proposed_policy.json
```

所有 Parquet 都必须带 `schema_version`，固定粒度和主键如下：

| 文件 | 一行代表什么 | 业务主键/排序 |
| --- | --- | --- |
| `raw_file_manifest` | 一个 frozen `trade_date + freq` Raw 文件，包括显式零行文件 | `trade_date, source_freq`；记录 path/hash/size/row_count/Basic hash |
| `raw_code_day_freq_profile` | 一个 `ts_code + trade_date + freq` 的实际分钟分布 | `ts_code, trade_date, source_freq`；记录 row/distinct time/min/max 和数值域计数 |
| `raw_grid_profile` | 一个 `freq + clock_time` 的全范围覆盖统计 | `source_freq, clock_time`；记录 code-day count/ratio 和首尾日期 |
| `raw_domain_profile` | 一个 `trade_date + freq` 的字段与数值域汇总 | `trade_date, source_freq`；记录 null、OHLC、成交、时间边界计数 |
| `raw_issue_details` | 一个 `trade_date + freq + reason_code` 的聚合问题与有界样本 | `trade_date, source_freq, reason_code`；`issue_count` + 最多 20 个稳定样本，不逐缺失 bar 展开 |
| `raw_partition_observation_manifest` | 一个 Raw `trade_date + freq` 的完整客观观察 | `trade_date, source_freq`；记录文件/Basic hash、单频与五频联合问题计数，不含 decision |

`raw_issue_details` 的行数上限为 `target_file_count × registered_reason_code_count`，绝对上限 200,000 行、256 MiB；超过任一上限时 N3A 停止并要求缩小 frozen plan，禁止静默截断。`raw_observation_summary.json`、`proposed_policy.json`、decision manifest 和 final report 也必须带 `schema_version`、输入 manifest hash 和自身内容 hash。

`raw_observation_summary` 只回答“看见了什么”，例如某分区有多少代码、各有多少时间点、哪些地方缺 bar、多少行价格为空或 OHLC 关系异常。`proposed_policy` 回答“根据这些事实，建议以后怎么判”，例如建议把“整日五频全空”设为阻断、把某种稳定存在的边界点差异设为 WARN。它只是建议，不产生 `green/warn/blocked`，也不产生 `silver_eligible`。

本文所说“blocking/WARN policy 尚未确认”，精确指 N3A 报告已经生成并交给管理员、但管理员尚未明确批准 N3B 规则的这段时间。这个阶段 Raw 文件保留，所有分区状态都是 `unclassified`；不能把建议规则当成正式口径。

管理员确认后才进入 N3B：把批准的 issue→decision 映射、阈值和例外冻结为有版本的代码合同与正反测试，再由 `decide_etf_mins_raw` 生成：

```text
approved_policy_version
raw_partition_decision_manifest.parquet
raw_decision_summary.json
```

`raw_partition_decision_manifest` 每个 `trade_date + freq` 一行，至少包含 Raw path/hash、Basic hash、policy version、所有问题计数、`decision=green|warn|blocked`、`silver_eligible` 和 reason codes。N3B 只解释观察结果，不重扫 Prod，不改 Raw。明细样本另存 Parquet，JSON 只保留聚合和每类最多 20 个样本。

只有发现异常且需要区分“导出损坏还是 Prod 原始事实”时，审计报告才允许生成明确的 `trade_date + freq + ts_code` 回查清单；回查使用既有只读 allowlist 和半开时间窗口，不得自动扩成 Prod 全量扫描。

N3B policy 冻结前，Raw 物理文件可以存在，文件/身份事实也可以在最终报告中验收，但不能宣称 Raw ready；Silver writer、历史 green check event 和 P10 日常 Sensors 必须 fail closed。policy 冻结后，单个分区的 blocked decision 不回滚 Raw 文件，但正式 `bar_domain` check 失败，日常 Raw/Silver 连续性都停在该日。不能先用一个宽泛 `quality_check` 掩盖未拍板语义。

N3B policy 冻结后，日常链不再运行整套历史 profile，而是调用同一规则合同的日常 evaluator：

```python
def evaluate_etf_mins_raw_bar_domain(
    *,
    partition_key: str,
    approved_policy_version: str,
    duckdb: DuckDBResource,
) -> EtfMinsRawBarDomainResult: ...
```

执行合同固定为：

1. 一个 evaluator、一个 DuckDB connection 集中读取同日五个文件；按规则需要可发少量集合 SQL，但不能由五个 check 各自重扫一遍。
2. 一个共享 `@multi_asset_check` 或行为等价实现发出五个 `bar_domain` evaluations，不新增 asset、reference、manifest 或状态表，也不把大 observation 塞进 Dagster event。
3. `green` 和 policy 明确允许的 `warn` 令对应 check `passed=True`；`blocked` 令 check `passed=False`。每条 check 都记录当前 Raw file hash、policy version、decision、reason codes、计数和最多 20 个样本。
4. 五个 `bar_domain` specs 与其它 Raw checks 一样设置 `blocking=True`。check 失败不删除、不回滚 Raw 文件，但正式 Raw readiness 失败。
5. check event 写入失败不回滚 Raw 文件，也不改变 Lake 上可复算的质量事实；本次 run 记为观测失败，修复后可只重跑正式 checks，不重新导出 Prod 或覆盖 Raw。Sensor 仍以同一纯规则重算 Lake readiness，不把 event 缺口伪装成数据失败。

因此日常 Raw 只有一个 ready 合同：

```text
raw_ready
  = 当前五频 Raw 文件存在
  + file_contract passed
  + request_scope passed
  + 当前 policy 的 bar_domain passed
```

`batch_etf_mins_raw_lake_readiness(...)` 必须在一个 DuckDB connection 中批量复刻上述三项 check 语义，不依赖 Dagster instance 或 event history。Raw 与 Silver Sensor 都消费这份结果；Silver Sensor 再叠加 Silver 自身 readiness。不再建立第二套 Silver 准入状态或引用。

### 14.5 目标文件冲突

- 目标不存在：校验通过后新增。
- 目标存在：DuckDB 用两个方向 `EXCEPT ALL` 比较 11 字段；完全相同则复用。
- 目标存在但内容不同：`etf_mins_target_conflict`，停止，不覆盖。
- 即使新候选“看起来更完整”，也不能在日常或 Bootstrap 中自动替换旧文件。

这就是 N5 的代码级表达。

### 14.6 Raw materialization metadata

每个 Raw asset 必须返回以下稳定字段；样本字段仍受 20 条上限约束：

```text
dagster/uri
dagster/row_count
goldenshare/observed_columns
goldenshare/partition_key
goldenshare/source_freq
goldenshare/source_method = prod_db_readonly
goldenshare/source_row_count / code_count
goldenshare/query_count = 1 / elapsed_ms
goldenshare/basic_raw_snapshot_hash
goldenshare/basic_silver_content_hash
goldenshare/basic_raw_observed_at
goldenshare/basic_silver_observed_at
goldenshare/basic_reference_fingerprint
goldenshare/eligibility_as_of
goldenshare/requestable_code_count / requestable_code_hash
goldenshare/prod_coverage_reference_fingerprint
goldenshare/expected/present/missing/known_non_required_present/retained_legacy/unexplained_new counts
goldenshare/file_sha256
goldenshare/write_disposition = added | reused
```

`reused` 也必须返回当前正式文件的 SHA-256 和行数；不得把候选文件 hash 冒充正式文件 hash。

---

## 15. 分钟 Silver writer

### 15.1 准入条件

Silver 只接受同日五频 Raw 三项 blocking checks 全部通过的分区。准入不放进 Silver writer 的自定义 guard：正式 `silver_etf_mins_update_job` 在同一 run 中先选择并执行五个 Raw assets 的全部 checks，再执行五个 Silver assets/checks。当前 Dagster 1.13.18 的最小定义验证已经确认：Raw writer 不在该 job selection 中；任一 Raw blocking check 失败时，下游 Silver step 不执行，全部通过时才继续。

Silver writer 只读取 `context.partition_key` 对应的 Raw 文件并完成本层确定性的类型表达、候选校验、等价复用或冲突停止。不得用额外 run config、操作者传入的 `passed=true`、第二套准入引用或 writer 内重复质量判断代替正式 Raw checks。

### 15.2 SQL

```sql
SELECT
  CAST(ts_code AS VARCHAR) AS ts_code,
  CAST(freq AS VARCHAR) AS freq,
  CAST(trade_time AS TIMESTAMP) AS trade_time,
  CAST(open AS DOUBLE) AS open,
  CAST(close AS DOUBLE) AS close,
  CAST(high AS DOUBLE) AS high,
  CAST(low AS DOUBLE) AS low,
  CAST(vol AS BIGINT) AS vol,
  CAST(amount AS DOUBLE) AS amount,
  CAST(vwap AS DOUBLE) AS vwap,
  CAST(exchange AS VARCHAR) AS exchange
FROM read_parquet(<raw_path>, hive_partitioning=false)
ORDER BY ts_code, trade_time
```

不允许 `WHERE` 删除行，不允许填空、去重、舍入、重新计算或跨频率 fallback。

### 15.3 Raw/Silver 等价性

发布前和正式 check 都必须验证：

- 行数相等。
- `(ts_code, freq, trade_time)` 主键集合相等。
- 11 字段两个方向 `EXCEPT ALL` 均为零。
- 路径日期和频率一致。

目标存在的处理与 Raw 相同：完全等价复用，内容冲突停止，不自动覆盖。

### 15.4 Silver materialization metadata

Silver 使用 `build_materialization_metadata(...)` 返回 `dagster/uri`、`dagster/row_count`、`goldenshare/observed_columns`，并在 `goldenshare/*` 下记录 `partition_key/source_freq/code_count/raw_uri/raw_sha256/silver_sha256/write_disposition`、`basic_raw_snapshot_hash/basic_silver_content_hash/basic_raw_observed_at/basic_silver_observed_at/basic_reference_fingerprint/eligibility_as_of/requestable_code_hash`，以及 `gap_policy_version/bar_domain_decision/bar_domain_reason_codes`。这些值从目标日 Raw materialization 的有界 metadata 读取和文件复算得到，不从“今天最新 Basic”重新拼装；如果 Raw metadata 缺失、其文件 hash 与当前正式 Raw 不一致或 policy version 不可解释，Silver 停止。不得写裸 metadata key 或 Dagster storage id。

---

## 16. Asset Checks

### 16.1 Basic checks

全部 `blocking=True`，无 Dagster partition：

```text
raw_tushare_etf_basic_source_contract_check
raw_tushare_etf_basic_key_domain_check
raw_tushare_etf_basic_content_hash_check

silver_etf_basic_source_filter_check
silver_etf_basic_key_domain_check
silver_etf_basic_content_hash_check
```

每个 check 只表达一个稳定质量属性，使用 `build_check_metadata`，返回可读 `summary/next_action/reason_code`、计数和有界样本。

### 16.2 分钟 Raw checks

每个五频 Raw asset 各三个 checks：

```text
raw_etf_mins_<freq>m_file_contract_check
raw_etf_mins_<freq>m_request_scope_check
raw_etf_mins_<freq>m_bar_domain_check
```

- `file_contract`：文件、11 字段、日期、频率、非空主键和唯一键。
- `request_scope`：冻结 Basic reference、代码/源 exchange 比较映射、六类集合统计和未解释代码；身份污染与 `unexplained_new` 稳定阻断，`missing` 只作为 N3 输入。
- `bar_domain`：在 N3B policy 冻结后统一判定价格空值、OHLC、成交量/额、分钟网格、内部空洞和时间边界；`blocked` 失败，获准 WARN 的分区通过但写清 reason code。五个 evaluation 必须由一个共享 `@multi_asset_check` 或行为等价的单次 evaluator 产生，在同一个 DuckDB connection 中读取同日五频，不能由五个 check 各自扫描，也不能依赖 op 的偶然执行顺序。

blocking 语义固定为：

```text
file_contract  blocking=True
request_scope  blocking=True
bar_domain     blocking=True
```

Catalog 的 Raw `blocking_check_names` 登记全部三类。Raw readiness helper 必须从同一纯规则/SQL 合同批量复刻它们，不能只检查文件存在和 row count。

### 16.3 分钟 Silver checks

每个五频 Silver asset 各两个 checks：

```text
silver_etf_mins_<freq>m_file_contract_check
silver_etf_mins_<freq>m_raw_equivalence_check
```

五频 Raw 的三类 checks 和所有 Silver checks 必须写：

```python
asset=<目标asset对象>
partitions_def=cn_a_etf_mins_trade_days
blocking=True
```

测试断言全部 check 的 definition、`AssetCheckEvaluation.partition` 和 check execution partition 都等于目标日期，并断言 Raw Catalog blocking list 精确登记三项 blocking checks。

### 16.4 写前安全门禁与正式 Check 的分工

正式 Raw 文件在提升前必须先执行稳定子集的纯 DuckDB validator。这是技术方案已经明确批准的候选提升安全边界，不是用 Asset 内部逻辑替代 Dagster Checks。

- 写前 validator：只阻断传输损坏、合同错误和 `unexplained_new` 身份污染，不对尚未冻结的 gap/grid 下结论；它属于 `CODING_STANDARDS.md` 明确允许的 candidate atomic-promotion integrity validator。
- N3A 观察：在本地 Raw 上批量执行完整覆盖、数值域和网格 profiling，只生成事实与建议。
- N3B 决策：管理员批准 policy 后生成 partition decision manifest；批准前所有 Raw 分区保持 `unclassified`。
- 正式 checks：三类 blocking checks 绑定 Raw materialization并共同定义 Raw readiness；`bar_domain` 复用已冻结 N3 policy。
- Lake readiness：用同一纯 helper/SQL 合同批量复刻三项 checks，供 Raw/Silver Sensors 使用，不读取 Dagster event history。
- Silver 正式 job：选择 Raw checks 后再运行 Silver，不在 writer 内重新发明质量规则或校验第二套 reference。
- 这些入口的共同字段、分类和 SQL contract 必须从同一 helper 派生，不能维护多套不同规则。

---

## 17. Jobs

Jobs 只做 selection：

```python
raw_etf_basic_update_job
  = asset(raw_tushare_etf_basic)
  + checks_for_assets(raw_tushare_etf_basic)

silver_etf_basic_update_job
  = asset(silver_etf_basic)
  + checks_for_assets(silver_etf_basic)

raw_etf_mins_update_job
  = assets(raw_etf_mins_1m ... raw_etf_mins_60m)
  + checks_for_assets(五个Raw)

silver_etf_mins_update_job
  = checks_for_assets(五个Raw)
  + assets(silver_etf_mins_1m ... silver_etf_mins_60m)
  + checks_for_assets(五个Silver)
```

两个分钟 Job 都显式使用 `executor_def=dg.in_process_executor`，与 `stk_mins` 五频 job 保持一致，避免五个 DuckDB writer/check 在同一分区内多进程争抢本机资源。分钟 Job selection 不包含 Basic assets，Silver Job 也不包含 Raw assets，只选择 Raw checks。Basic 是 `deps=["silver_etf_basic"]` 的 lineage/readiness 依赖，并由 Raw run config 中的冻结 reference 指向具体版本；分钟 Job 不顺手重跑 Basic。Raw checks 作为 Silver 的直接上游门禁在同一 run 内执行，任一 blocking failure 都阻止 Silver steps。

---

## 18. Sensors 与 readiness

### 18.1 通用规则

- 全部 `DefaultSensorStatus.STOPPED`。
- 每 tick 最多一个 `RunRequest`。
- 先检查上海运行窗口，再做 DuckDB 或 Prod 查询。
- 日常回看最近 10 个 expected trade dates，一次只推进最早可行动日期。
- Cursor 使用 `build_sensor_cursor`，正常目标小于 2 KB，复杂错误也不得超过 8 KB。
- Cursor 不保存完整代码、完整文件清单、SQL 或 Basic 快照内容。
- Run key 使用统一 builder，不从 run key 解析 config。
- `batch_etf_mins_raw_lake_readiness(...)` 在一个 DuckDB connection 中批量复刻三项 Raw blocking checks；`batch_etf_mins_silver_lake_readiness(...)` 复刻两项 Silver checks。两者都不依赖 Dagster instance，不逐日扫描 event history。

### 18.2 `etf_mins_trade_day_sensor`

只读 `silver_trade_calendar` 的 SSE open dates，补注册 `cn_a_etf_mins_trade_days`。不读取 Prod、不请求 Tushare、不扫描分钟文件。停机后可补注册，仍每 tick 使用有界日期范围。

### 18.3 Basic Raw Sensor

目标是上海当天。决策：

1. 未到 N6 确认的窗口：轻量 skip。
2. 当天 Raw ready：skip。
3. 当天已有 materialization 但 checks 失败：skip closed，人工处理。
4. 缺失或上次成功版本不是当天：提交 `raw_etf_basic_update_job`。

### 18.4 Basic Silver Sensor

只在当天 Raw ready 且当天 Silver 尚未 ready 时提交。Run config 写入冻结 Raw reference。Silver 已 materialized 但 checks 失败时不自动重跑。

### 18.5 分钟 Raw Sensor

读取顺序：

```text
window gate
-> expected dates + registered partitions
-> 10日 Raw Lake batch readiness（三项 blocking checks）
-> select earliest actionable date
-> latest-only same-day Basic reference
-> one bounded Prod Raw five-frequency code-coverage probe
-> build one RunRequest for five Raw assets
```

Sensor 不读取 TaskRun，也不为 N3 对 Prod 做价格、网格或内部空洞预审计。它只用冻结 Basic 的 `expected(D)` 对 Prod Raw 做一次五频代码存在性检查；任一 expected code/freq 缺失都 skip，避免上游仍在写时启动。Raw asset 开始时只重新验证冻结 Basic，并校验 config 携带的 coverage reference 与该 Basic/日期一致；每频只做一次明细导出，再由本地候选完成范围校验，不重复 coverage 或 fingerprint 查询。文件存在但三项 Raw checks 任一失败时不得自动覆盖或越过该日；Basic 不新鲜、物理覆盖不全或全局 N3 policy 尚未冻结，都返回人能看懂的 SkipReason。

### 18.6 分钟 Silver Sensor

只读最近 10 日 Raw/Silver Lake readiness，不访问 Prod/Tushare/Dagster event history。它先调用 `batch_etf_mins_raw_lake_readiness(...)`，只有同日五频三项 Raw checks 的等价语义全部通过，才调用 Silver batch readiness 并提交该日正式 Silver job。最早日期 Raw 或 Silver not-ready 时停在该日，不越过。Silver job 本身再次运行 Raw checks，从而覆盖 Sensor 与 job 触发之间的文件变化或手工从正式 job 启动的情况。

### 18.7 建议 reason codes

```text
etf_basic_not_fresh
etf_basic_materialization_missing
etf_basic_checks_failed
etf_basic_reference_changed
prod_etf_mins_code_coverage_incomplete
prod_etf_mins_source_not_ready
prod_etf_mins_source_query_error
etf_mins_partition_not_registered
etf_mins_existing_file_check_failed
etf_mins_raw_bar_domain_failed
etf_mins_raw_policy_pending
etf_mins_raw_not_ready
etf_mins_request_scope_incomplete
etf_mins_unexplained_new_code
etf_mins_grid_policy_pending
etf_mins_target_conflict
```

---

## 19. Catalog 与 definition metadata

### 19.1 新 partition models

```text
full_file_raw_etf_basic_versioned
full_file_silver_etf_basic_versioned
trade_date_partition_raw_etf_mins
trade_date_partition_silver_etf_mins
```

Basic 两个模型仍属于 `FULL_FILE` family，但 path template 包含 `snapshot_id`，notes 明确“每次 materialization 指向一个不可变单文件版本”。分钟模型属于 `TRADE_DATE_PARTITION`，物理布局为每日期/频率一个文件。

### 19.2 Catalog entries

必须 registry-first 添加 12 条 `LakeAssetCatalogEntry`。下面字段不是示意值，编码时按表逐项落地：

| 资产族 | asset key / dataset | group / domain | source / contract | ingestion | write / event |
| --- | --- | --- | --- | --- | --- |
| Basic Raw | `raw_tushare_etf_basic` / `etf_basic` | `etf_basic` / `DataDomain.BASIC_DATA` | `SourceSystem.TUSHARE` / `DataContractSource.TUSHARE_RAW_CONTRACT` / `data_contract=source_mirror_versioned` | daily/default=`IngestionSource.TUSHARE_API`；无 bootstrap source | `SINGLE_FILE_ATOMIC_REPLACE` / `DAGSTER_RUN_ONLY` |
| Basic Silver | `silver_etf_basic` / `etf_basic` | `etf_basic` / `DataDomain.BASIC_DATA` | `SourceSystem.DERIVED` / `DataContractSource.DERIVED_CONTRACT` / `data_contract=sh_sz_full_status_etf_basic` | daily/default=`IngestionSource.DERIVED_FROM_ASSETS`；无 bootstrap source | `SINGLE_FILE_ATOMIC_REPLACE` / `DAGSTER_RUN_ONLY` |
| 分钟 Raw 五频 | `raw_etf_mins_{1,5,15,30,60}m` / `etf_mins` | `quote` / `DataDomain.QUOTE_DATA` | `SourceSystem.TUSHARE` / `DataContractSource.TUSHARE_RAW_CONTRACT` / `data_contract=source_mirror` | daily/default/bootstrap=`IngestionSource.PROD_DB_READONLY` | `PARTITION_FILE_ATOMIC_REPLACE` / `SUPPORTS_RUNLESS_EVENT_BACKFILL` |
| 分钟 Silver 五频 | `silver_etf_mins_{1,5,15,30,60}m` / `etf_mins` | `quote` / `DataDomain.QUOTE_DATA` | `SourceSystem.DERIVED` / `DataContractSource.DERIVED_CONTRACT` / `data_contract=audited_exact_copy` | daily/default/bootstrap=`IngestionSource.DERIVED_FROM_ASSETS` | `PARTITION_FILE_ATOMIC_REPLACE` / `SUPPORTS_RUNLESS_EVENT_BACKFILL` |

中文名称映射固定新增：

```text
etf_basic = ETF 基础信息
etf_mins  = ETF 历史分钟行情
```

Basic Raw 的 `source_api/source_doc` 固定为 `etf_basic` / `docs/sources/tushare/ETF专题/0385_ETF基础信息.md`；分钟 Raw 固定为 `etf_mins` / `docs/sources/tushare/ETF专题/0387_ETF历史分钟行情.md`。两个 Silver family 的 `source_api/source_doc` 均为 `None`，通过 upstream asset 表达来源。

Basic 的 `SINGLE_FILE_ATOMIC_REPLACE` 表示现有 writer 能力，不表示覆盖旧版本：path 含内容 hash，每个新 hash 都落到新文件；同 path 只有“完全等价复用/内容冲突停止”两种结果。分钟 notes 也必须补充 `add/reuse/conflict-stop` 语义。

分钟 Raw 要与当前 `raw_stk_mins_*` 的 catalog 口径一致：`SourceSystem.TUSHARE` 与 `DataContractSource.TUSHARE_RAW_CONTRACT` 表达数据血缘和字段合同，`IngestionSource.PROD_DB_READONLY` 表达这次 DG 的物理传输通道。notes 必须写清真实读取位置是 `prod-raw-db.raw_tushare.etf_minute_bar`。这既不能写成 `PROD_CORE_DB`，也不能误写成 DG 直接请求 Tushare 分钟接口。

每个分钟 Raw entry 的 `blocking_check_names` 精确登记对应 `file_contract_check`、`request_scope_check` 和 `bar_domain_check`。Catalog notes 与 performance contract 说明三项共同定义 Raw readiness，且 `bar_domain` 由同日五频共享 DuckDB evaluator 产生。静态测试同时证明三项都存在、都是 blocking、没有第四套准入状态。

### 19.3 Definition metadata

每个 asset 使用：

```text
build_asset_tags(layer=..., data_domain=...)
build_asset_definition_metadata(
  dataset_id=...,
  source_system=...,
  source_api=...,
  source_doc=...,
  data_contract=...,
  column_schema=...,
  path_template=...,
)
```

`dataset_id/source_system/source_api/source_doc/data_contract/column_schema/path_template` 必须与上表和第 6、7 节的合同逐项一致。Catalog、definition metadata、path helper、schema、blocking check names 和 partition model 必须由静态测试逐项对账，禁止资产装饰器再写一套不同口径。

### 19.4 人类可读 description 合同

所有 description 使用下面的中文正文，不写 P0/P1、迁移阶段、类名或 selection 技术细节。

| Definition | description 合同 |
| --- | --- |
| `raw_tushare_etf_basic` | 从 Tushare 保存无业务过滤的 ETF 基础信息完整快照，包含沪深场内和源端其它后缀/状态；供同版 Silver 和后续分钟范围校验追溯。 |
| `silver_etf_basic` | 把指定 Raw 快照标准化为 `.SH/.SZ` 全状态 ETF 基础信息，不按上市状态或日期再筛选；供 ETF 分钟任务冻结当次请求范围。 |
| `raw_etf_mins_<freq>m` | 按交易日保存 Prod Raw 中 `<freq>` ETF 分钟物理事实；三项 blocking checks 通过后才 ready，失败不删除已经安全保存的 Raw 文件。 |
| `silver_etf_mins_<freq>m` | 按交易日保存通过当前 N3 policy 的 `<freq>` ETF 分钟完整分区，与对应 Raw 11 字段逐行等价；供下游分析消费。 |
| `raw_etf_basic_update_job` | 获取并验收当天 ETF Basic 完整源快照；相同内容复用，不同内容新建版本，失败不会覆盖旧版本，可在修复源/合同后重跑。 |
| `silver_etf_basic_update_job` | 从已验收的指定 Basic Raw 版本生成沪深场内 Silver 快照；前置 Raw/reference 不一致时停止，修复后可重跑并等价复用。 |
| `raw_etf_mins_update_job` | 为一个交易日批量导出五个原生频率 ETF 分钟 Raw，并执行三项 Raw blocking checks；冲突不覆盖，可按原分区重跑。 |
| `silver_etf_mins_update_job` | 先重跑目标日五频 Raw blocking checks，通过后生成五个 Silver 分区；Raw writer 不在 selection 中，失败时不执行 Silver。 |
| `etf_mins_trade_day_sensor` | 在运行窗口内从 SSE 交易日历补注册 ETF 分钟专属动态分区；不请求行情、不写 Lake，默认停止。 |
| `raw_etf_basic_update_job_sensor` | 在确认的运行窗口检查当天 Basic Raw 是否缺失或过期，满足条件时触发 Basic Raw 更新；已有失败版本时不自动覆盖，默认停止。 |
| `silver_etf_basic_update_job_sensor` | 在当天 Basic Raw 及其 checks 已通过后触发对应 Silver 版本；失败版本要求人工处理，不回退旧 Raw，默认停止。 |
| `raw_etf_mins_update_job_sensor` | 在运行窗口内检查最早 Raw readiness 缺口、最新 Basic 和一次 Prod 五频覆盖，满足后触发五频 Raw；任一 Raw check 失败时停在该日，默认停止。 |
| `silver_etf_mins_update_job_sensor` | 检查最早未完成日期的五频 Raw/Silver Lake readiness，Raw 三项检查通过后触发 Silver；not-ready 时停在该日且不访问 Prod，默认停止。 |

Check description 使用稳定模板：

- Basic `source_contract/key_domain/content_hash`：分别说明源字段与全集、主键/状态/后缀、内容 hash 可复算，失败后查看数量、样本和下一步。
- Basic Silver `source_filter/key_domain/content_hash`：分别说明 `.SH/.SZ` 精确筛选、标准化键域、同版内容 hash。
- 分钟 Raw `file_contract/request_scope`：分别说明“文件/字段/主键/分区”和“冻结 Basic/代码身份/六类集合”；两者是 Raw blocking checks。
- 分钟 Raw `bar_domain`：说明“同日五频共享 N3 policy 的 Raw blocking 结果；失败不删除 Raw 文件，但该日不 ready 且禁止 Silver”。
- 分钟 Silver `file_contract/raw_equivalence`：分别说明正式文件合同和与当前 Raw 11 字段双向等价。

### 19.5 stdout 里程碑与人的排障入口

长耗时路径使用现有 stdout logger 形成运行脚印。稳定事件名固定为：

```text
etf_basic_source_fetch_started
etf_basic_source_page_completed
etf_basic_candidate_validated
etf_basic_snapshot_promoted
etf_mins_source_batch_started
etf_mins_source_batch_exported
etf_mins_candidate_validated
etf_mins_raw_promoted
etf_mins_raw_bar_domain_evaluated
etf_mins_silver_promoted
etf_mins_bootstrap_stage_completed
```

每条只写 asset/operation、partition 或日期批次、频率、行数/文件数、elapsed、结果和短 reason code。禁止打印 token/conninfo、完整 SQL、全量代码/路径列表、DataFrame 或每个文件一条刷屏日志。

| 人遇到的问题 | 第一入口 | 必须看到 | 下一步判断 |
| --- | --- | --- | --- |
| Sensor 为什么没触发 | Sensor cursor / SkipReason | target date、reason code、阻断组件、短 summary、next action | 等运行窗口/Basic/Prod，还是处理已有失败文件/check |
| Asset run 为什么失败 | Run stdout/stderr | 最后一个里程碑、asset、partition/freq、关键数量、失败动作 | 失败在源读取、候选校验、冲突、check 还是 promote |
| Raw 文件/身份 check 为什么失败 | check metadata | failed rule、数量、最多 20 个样本、URI、next action | 修源/合同或人工解释新代码；不能靠覆盖重跑 |
| N3/Raw readiness 为什么失败 | `bar_domain` metadata + observation/decision 报告 | policy version、decision、reason codes、计数、报告路径 | policy 允许 WARN、修复观测链，或回到 Prod 处理数据事实 |
| Bootstrap 为什么停止 | operation frozen plan/checkpoint/final report | stage、fingerprint、stop reason、added/reused/conflict/remaining | 按 checkpoint 续跑，或处理冲突后重新审批计划 |
| 这次实际写了什么 | materialization metadata / final report | URI、row count、hash、write disposition、Basic/policy fingerprint | 对账新增、复用和零行文件，不从少量 Dagster event 推全历史 |
| 当前能否安全重跑 | Job description + final report | 上游 reference 是否仍有效、目标 disposition、checkpoint | 只允许新增/等价复用；冲突或 reference 漂移先人工处理 |

---

## 20. Direct Lake Bootstrap

### 20.1 一个 CLI、七个受控 subcommands

```text
plan          只读 Prod/Lake/Dagster 小状态，输出冻结计划，不写正式 Lake/event
raw-apply     经显式确认后写 staging 和正式 Raw，不写 Silver/event
raw-observe   只读正式 Raw/Basic/交易日历，完成 N3A 并输出事实/profile/建议，不访问 Prod、不作准入决定
raw-decide    只消费 N3A 结果和已批准 policy version，完成 N3B decision，不访问 Prod、不写正式 Lake/event
silver-apply  只消费 N3 decision manifest，经显式确认后写 Silver并生成物理 final report，不访问 Prod、不写 event
partitions    物理验收后注册已批准的历史动态分区，不读 Prod、不写 Lake/event
events        物理对账后单独补 materialization/check event，不写 Lake
```

七个 subcommands 共用 `etf_mins_bootstrap.py` 的计划、校验、checkpoint 和报告类型，以及 `etf_mins_bootstrap_cli.py` 的参数解析；它们仍是七个单独授权阶段，不是一次命令自动跑完全链。禁止把写开关藏在只读入口。`raw-apply`、`silver-apply`、`partitions`、`events` 分别要求 `--confirm-raw-lake-write`、`--confirm-silver-lake-write`、`--confirm-partition-write`、`--confirm-event-write`。本 LLD 只设计入口，不授权执行。

对应调用形状固定为：

```text
python -m orchestrator.defs.bootstrap.etf_mins_bootstrap_cli plan \
  --start-date YYYY-MM-DD --end-date YYYY-MM-DD \
  --report-path <explicit-json-path>

python -m orchestrator.defs.bootstrap.etf_mins_bootstrap_cli raw-apply \
  --plan-path <explicit-json-path> \
  --checkpoint-path <explicit-json-path> \
  --raw-final-report-path <explicit-operation-dir>/raw_final_report.json \
  --confirm-raw-lake-write

python -m orchestrator.defs.bootstrap.etf_mins_bootstrap_cli raw-observe \
  --raw-final-report-path <explicit-json-path> \
  --output-dir <explicit-operation-dir>

python -m orchestrator.defs.bootstrap.etf_mins_bootstrap_cli raw-decide \
  --observation-summary-path <explicit-json-path> \
  --approved-policy-version <registered-version> \
  --output-dir <explicit-operation-dir>

python -m orchestrator.defs.bootstrap.etf_mins_bootstrap_cli silver-apply \
  --raw-decision-summary-path <explicit-json-path> \
  --decision-manifest-path <explicit-parquet-path> \
  --checkpoint-path <explicit-json-path> \
  --final-report-path <explicit-operation-dir>/physical_final_report.json \
  --confirm-silver-lake-write

python -m orchestrator.defs.bootstrap.etf_mins_bootstrap_cli partitions \
  --final-report-path <explicit-json-path> \
  --confirm-partition-write

python -m orchestrator.defs.bootstrap.etf_mins_bootstrap_cli events \
  --final-report-path <explicit-json-path> \
  --confirm-event-write
```

所有报告和 checkpoint 必须放在 `/Volumes/datasource/data_lake_staging/etf_mins/operation_id=<operation_id>/` 及其阶段子目录；CLI 要求绝对路径并校验 operation 边界，不能只检查“位于 staging 根下”。`plan/raw-observe/raw-decide` 没有正式 Lake/event 写参数，`raw-apply` 没有 Silver/event 参数，`silver-apply` 没有 Prod/event 参数，`partitions` 没有 source/Lake/event 参数，`events` 没有 source/Lake/partition write 参数。`raw-decide` 只接受代码中已登记且已有正反测试的 policy version，不能从命令行临时传阈值。历史专项入口另加 `--protect-from-date 2026-01-01`，其值只允许等于合同常量，不能由操作者改成更晚日期。

首次 Direct Bootstrap 发生在分钟日常 Sensors 启用前。七个 subcommands 以同一 `operation_id` 按阶段顺序单独调用；每个写入 subcommand 只允许一个进程，`raw-apply` 在该进程内串行执行各频率和日期批次。它不是长期与日常链并行的第二条写路径，因此不新增跨路径 concurrency pool 或外部锁；日常 Sensors 必须保持 `STOPPED`，直到 Bootstrap、分区、事件和最终验收分别完成并获准启用。

### 20.2 Frozen plan 与阶段指纹

plan 至少固定：

```text
operation_id
schema_version
created_at
requested_start_date / requested_end_date
execution_watermark_date
execution_watermark_coverage_fingerprint
expected_trade_dates + hash
frequencies + hash
plan_coverage_query_count
raw_detail_query_count
expected_remote_query_count
basic_raw_snapshot_hash
basic_silver_content_hash
basic_raw_observed_at
basic_silver_observed_at
eligibility_as_of
requestable_code_count / requestable_code_hash
target_file_count
estimated_source_rows + estimate_basis
estimated_staging_bytes
estimated_final_increment_bytes
preexisting_target_state_summary
preexisting_target_manifest_hash
historical_protection_mode
protected_file_manifest_hash
plan_fingerprint
```

所有 JSON plan/report 的自身 hash 都对“去掉自身 hash 字段后的完整 payload”做稳定键排序和 UTF-8 SHA-256；不得把文件 mtime、绝对 staging 路径或格式化空白算进身份。Parquet manifest 的 hash 对按合同主键排序后的全部逻辑字段计算，不用 Parquet 文件字节 hash 代替。实现只保留一套共享 helper，并用字段换序、行换序和任一业务值变化的正反 fixture 固定语义。

首次 2026 Bootstrap 的 `historical_protection_mode=not_applicable`，`protected_file_manifest_hash` 必须显式为 `null`；因为本次目标本来就会新增或复用 2026 文件，不能把目标范围误当成零变化保护区。只有第 21 节的 2025 年及以前专项使用 `protect_trade_date_gte_2026_01_01`，此时保护清单 hash 必填并参与 plan、apply 和 final report 对账。

`execution_watermark_date` 不能写成配置常量。plan 在提交写入审批前，使用第 11 节冻结的 latest-only Basic reference，对操作者请求上界向前最多 10 个 SSE 开市日做一条批量五频代码覆盖查询：取其中最新一个五频完整日作为水位；10 日内没有完整日就 fail-closed，不继续向历史深扫。`execution_watermark_coverage_fingerprint` 只是这次 coverage 查询输入、聚合结果和观测时间的稳定摘要，不是分钟明细内容 hash。报告必须同时展示操作者请求上界、实际水位和被水位裁掉的日期。

plan 对既有正式 Raw 只能做本地结构预检，逐目标状态只允许：

```text
missing
present_structurally_valid_uncompared
present_invalid
```

`present_invalid` 包括文件不可读、schema/分区/键合同损坏，直接令 plan `should_stop=true`。`present_structurally_valid_uncompared` 只说明旧文件可以进入 apply 比较，不代表内容等价。由于 plan 的远程查询预算只有水位 coverage，没有目标明细，它不得输出 `reusable` 或 `conflict`；这两个结论只能由 raw-apply 的本批唯一一次明细 relation 与既有文件双向 `EXCEPT ALL` 得出。

查询预算在 plan 中写死：`plan_coverage_query_count=1`，`raw_detail_query_count=5 × ceil(expected_trade_date_count / 20)`，`expected_remote_query_count` 为两者之和。`raw-apply` 只能消费管理员明确批准过的完整 `plan_fingerprint`，不能静默扩大、重算水位、改 Basic 或增加查询。

`raw-apply` 只消费 frozen plan，不能重新解释命令行范围或切换 Basic 版本。它在实际读取时为每个 `freq + date_batch` 追加：

```text
source_query_scope_hash
source_row_count
source_code_count
source_min_trade_time / source_max_trade_time
source_assigned_row_count
unexpected_trade_date_count
staging_row_count / staging_sha256
formal_raw_row_count / formal_raw_sha256
promoted_file_count / reused_file_count / zero_row_file_count
source_query_count = 1
batch_elapsed_ms
```

这些都是同一次明细导出 relation 及其本地 staging/Raw 文件的传输证据。要求 `source_assigned_row_count=source_row_count`、`unexpected_trade_date_count=0`，并按冻结日期逐文件对账；不在 Prod 对同一范围增加导出前、导出后或 coverage 重查。

### 20.3 Plan dry-run

顺序：

1. 校验日期、频率和专属交易日历。
2. 按第 11 节冻结 latest-only Basic reference，并把 Raw/Silver 两个 hash 和两个 `observed_at` 写入 plan。
3. 对请求上界向前最多 10 个 SSE 开市日执行一条 Prod Raw 五频代码 coverage 查询，动态冻结 `execution_watermark_date`；不读取 TaskRun，不在 apply 阶段重查。
4. 用日期数、五频、已有物理行数证据和经批准的小样本估计行数与空间；不得为了 dry-run 先全量扫描 Prod。
5. 批量检查正式 Raw 目标为 `missing/present_structurally_valid_uncompared/present_invalid`；Silver 只统计既有路径和结构异常，不在 Raw plan 中预判内容等价。任一 `present_invalid` 都停止。
6. 测算查询数、文件数、staging 峰值、正式增量和剩余空间。
7. 报告请求范围、水位后实际范围及被裁日期；日期、预算、冲突、Basic、水位或适用的保护模式/清单任一不关闭时 `should_stop=true`。N3 尚未执行不是 Raw plan 的停止条件。

plan 只提出 frozen plan，不授权写入。管理员批准的是这份包含动态水位的完整 plan fingerprint；批准后 Raw apply 不得自行把水位往前或往后移动。

### 20.4 Raw apply

```text
for frequency in five freqs:
  for date_batch in chunks(expected_dates, max=20):
    query one bounded frequency/date range into one DuckDB relation
    record source relation counts/bounds and reject unexpected trade dates
    assign every source row to exactly one frozen trade_date
    split to one ordered candidate parquet per frozen trade_date with DuckDB COPY
    create a schema-correct zero-row candidate for every frozen date without source rows
    re-read and run stable transport/schema/Basic identity gates
    reconcile source relation, assigned rows, staging and formal Raw locally
    compare each explicit candidate with any structurally-valid existing Raw
    classify as added / reused / conflict-stop, then promote only added
    write checkpoint after each file
stop current batch at first stable-gate failure
```

每个 `frequency + date_batch` 恰好一条 Prod 明细查询；不把整个历史范围装入 Python，不按 ETF 查询，不并行写相同目标文件。每个 frozen `trade_date + freq` 必须有一个物理结果，包括源端零行时的显式零行 Parquet。`missing`、部分频率缺失、零行和网格异常写入 metadata，不能在此阶段伪装成 N3 结论；`unexplained_new`、源行未分配、传输不一致或合同损坏仍立即停止。目标缺失时 disposition=`added`；结构有效既有目标经 11 字段双向 `EXCEPT ALL` 为零时 disposition=`reused`；否则 disposition=`conflict-stop` 并立即停止，绝不覆盖。失败后通过 checkpoint 从已验收文件后继续；重跑仍会重新验证正式文件，再做等价复用或冲突停止。

Raw apply 只有在 frozen plan 的全部目标都已通过稳定门禁并明确为 `added|reused` 后，才输出覆盖全部目标的 `finalized_raw_manifest.parquet` 和不可变 `raw_final_report.json`。报告至少绑定 `operation_id`、`plan_fingerprint`、finalized manifest hash、source/staging/Raw 汇总行数、added/reused/zero-row 数量、实际远程查询数、checkpoint hash 和自身内容 hash；未完成、冲突或任一批次失败时不得生成完成报告。Raw apply 不生成 Silver、不补 Dagster event，也不宣称 Raw ready。历史全量验收在后续由 N3 decision manifest 和三项 blocking 语义完成，不以是否存在历史 check event 为唯一依据。

### 20.5 N3A Raw observation/profile

raw-observe 必须先验证 frozen plan、`raw_final_report.json`、`finalized_raw_manifest.parquet` 和正式 Raw 文件集合/hash 一致，然后在一个或少量 DuckDB connection 中完成第 14.4 节的本地批量观察。

主扫描使用列投影：覆盖/网格阶段只读 `ts_code/freq/trade_time/exchange/vol`；数值域阶段再读取 OHLC、amount、vwap。允许按频率/年份或受控日期批次建立临时聚合，但不得逐文件重复深扫。

raw-observe 只输出 profile、issue、`raw_observation_summary` 和 `proposed_policy`。异常需要源端确认时只输出有界 Prod 回查清单，raw-observe 自身不得访问 Prod。它不得生成 decision manifest、不得给出 `silver_eligible=true`。

### 20.6 N3B policy freeze 与 Raw decision

管理员审阅 N3A 报告并明确批准 blocking/WARN 映射、阈值和例外后，P7B 才把 policy 写入集中合同、reason codes 和正反测试，产生不可变 `approved_policy_version`。raw-decide 只消费 N3A hash 和该登记版本，生成覆盖全部 Raw 分区的 decision manifest；观察文件或 policy hash 不一致立即停止。

这一步的输出才是 Silver 的准入依据。批准前不存在“暂定 green”，也不能因为某条建议看起来合理就自动执行。

### 20.7 Silver apply

Silver apply 必须同时冻结并验证：

```text
raw_final_report_hash
raw_observation_summary_hash
raw_decision_summary_hash
raw_partition_decision_manifest_hash
basic_raw_snapshot_hash / basic_silver_content_hash
gap_policy_version
```

从完整 `finalized_raw_manifest.parquet` 和 decision manifest 生成 `silver_work_manifest.parquet`：范围是 `silver_eligible=true`，并且 Silver 目标缺失或已有目标需要语义核验的分区。Raw disposition=`reused` 不能成为跳过 Silver 的理由。Silver 缺失则新增；已有目标与 Raw 11 字段双向 `EXCEPT ALL=0` 则复用；冲突立即停止。`blocked` 分区不写 Silver，WARN 只有在冻结 policy 明确为非阻断时才能准入；不能修值、删行、去重或补 bar。全部准入目标闭合后输出覆盖 `added|reused` 的 `finalized_silver_manifest.parquet`。

Silver apply 对全部目标完成 `added|reused|blocked` 分类后，必须先执行第 20.9 节前六项物理集合审计，全部通过才在本 operation 目录写入不可变 `physical_final_report.json`。报告至少绑定：`operation_id`、`plan_fingerprint`、`raw_final_report_hash`、N3 observation/decision hashes、finalized Raw manifest hash、Silver work/finalized manifest hashes、保护模式与保护清单 hash（仅 P11 必填，首次 2026 显式 `not_applicable/null`）、Raw/Silver 文件与行数、blocked/WARN 数量及自身内容 hash。它只是后续 `partitions/events --final-report-path` 的唯一输入证据，不是新 asset，也不进入正式 Lake；任一上游 hash、正式文件或集合发生漂移时不得生成或复用该报告。

### 20.8 历史动态分区注册

`partitions` 入口只在 Raw/Silver 物理验收完成后运行，写入 `cn_a_etf_mins_trade_days` 动态分区，不补事件、不碰 Lake 文件：

- 首次 2026 Bootstrap：候选集合固定为 `2026-01-01..execution_watermark_date` 内 `silver_trade_calendar` 标记的全部 SSE 开市日。日期依据来自交易日历，范围上界跟随本次 Prod coverage 冻结水位；不能只注册“Prod 实际有行”的日期，否则会把零行问题藏掉。
- 2025 年及以前专项：只注册该次获批 frozen plan 中的 SSE 开市日，不顺带补其它历史日期。
- dry-run 必须报告计划日期数、已存在数、待新增数、超范围日期和 partition definition 名称；出现非 SSE 开市日、超水位日期或 final report 未覆盖日期立即停止。
- apply 只新增缺失 partition key，已有 key 等价复用；写后重新读取并证明 `planned - registered = ∅`。对应 materialization/check runless event 只能在本阶段通过后执行。

动态分区是 Dagster 的可寻址索引，不是数据存在证明。注册某日不代表该日 Raw/Silver ready；物理文件、N3 decision 和对应层 check 语义共同决定状态。

### 20.9 完成对账

完成对账分两段执行。Silver apply 先完成以下前六项物理集合审计并生成 `physical_final_report.json`；`partitions` 与 `events` 再分别执行后两项状态审计。不能在物理审计未闭合时先注册分区或补事件，也不能把少量 Dagster event 当作全历史物理验收：

- Frozen plan 目标文件集合与正式 Raw 文件集合差异。
- `raw_final_report.json` 的 source/staging/Raw 行数、范围和 hash 对账。
- N3 decision manifest 是否覆盖每个 Raw `trade_date + freq`，是否存在未知 decision/reason。
- Silver 文件集合是否精确等于 `silver_eligible=true` 集合。
- Raw 与 Silver 行数、主键和 11 字段两个方向 `EXCEPT ALL` 等价性。
- 所有 candidate/staging/checkpoint 是否已结案；operation 报告链与 `physical_final_report.json` 的 hash 完整且一致。
- frozen plan 中应注册的动态分区是否全部存在，是否无越界新增。
- materialization/check event 数量、绑定和幂等状态闭合，并对少量首、中、尾日期抽样完整 blocking semantics。

---

## 21. 2025 年及以前专项补录保护

历史入口使用独立 config，硬校验：

```text
requested_end_date <= 2025-12-31
```

### 21.1 写前保护清单

枚举正式 Raw/Silver ETF 分钟中所有 `trade_date >= 2026-01-01` 文件，记录：

```text
path
row_count
file_size
sha256
```

清单本身计算 SHA-256 并进入 frozen plan。范围是 2026 及以后，不只保护某个固定截止日。

### 21.2 代码级拒绝

下列任一情况在任何候选提升前停止：

- 命令范围碰到 2026-01-01 或以后。
- staging 候选中存在 `trade_time::DATE >= 2026-01-01`。
- target path 解析出的日期与计划日期不一致。
- writer 收到 2026 或以后路径。
- frozen plan 与 apply 的日期/Basic/频率 hash 不一致。

### 21.3 按最终范围补齐，不按 changed-only 漏数据

- Raw target missing 才能新增；等价则 `reused`；冲突立即停止。
- Raw apply 输出完整 `finalized_raw_manifest`，同时包含 `added/reused`。如需新增文件统计，可另出 `added_raw_manifest`，但它不是下游输入边界。
- Silver work manifest 取 `finalized_raw_manifest ∩ silver_eligible` 后再判断 Silver 目标：缺失则新增，已有等价则复用，已有冲突则停止；不 glob 2026，不全范围重建。
- Event helper 消费最终验收的 Raw/Silver `added/reused` 范围，幂等补缺失事件；不能因为文件是 reused 就漏补 Dagster 历史索引。

### 21.4 写后零变化

重新计算写前保护清单的 path/row_count/file_size/SHA-256，必须逐项完全相同。新增的 `>=2026-01-01` 路径数量也必须为零，否则整次补录验收失败。

---

## 22. Runless event 补录

事件入口只消费同一 operation 的 `physical_final_report.json`、已注册动态分区集合和实际正式文件，不调用 source、不写 Lake、不写动态分区、不运行 job/sensor。若报告 fingerprint/hash 不一致或任一目标 partition key 尚未注册，整个 event apply fail-closed。Runless events 只服务 Dagster UI/历史索引，不是全历史物理 readiness 的事实源。

建议规则：

- Raw materialization 只补已经进入 finalized Raw manifest 且被 N3 decision manifest 覆盖的分区；Silver materialization 只补最终 `added/reused` 且 `silver_eligible=true` 的分区。已存在等价 event 时跳过，缺失时补录。
- 正式 checks 只补最近 20 个 `cn_a_etf_mins_trade_days`；包括 Raw 三类 blocking checks 和 Silver 两类 blocking checks。更早质量事实由 finalized manifest、N3 decision 和 Raw/Silver 等价审计报告保存，不能因没有 check event 就宣称历史不完整。
- 每条 event 显式带 asset key、partition、uri、row_count、Basic hash 和 source method。
- Check event 必须绑定对应 materialization storage id。
- 缺前置 materialization、已有同等 event、文件发生变化或 final report fingerprint 不一致时不写。

单个 frozen plan 的 Raw materialization 候选上限等于 `target_file_count`，Silver materialization 候选不超过 `target_file_count`，因此 materialization event 总上限为 `2 × target_file_count`。正式 checks 只覆盖最近 20 个交易日，五频 Raw 的 3 个 blocking 加五频 Silver 的 2 个 blocking，最多 `20 × (5×3 + 5×2) = 500` 条 check event。blocked Raw 可以补 `bar_domain passed=False` 作为真实事实，但不得补 Silver materialization 或伪造 green。dry-run 超过这两个预算中的任一个就停止，不靠放宽上限执行。

事件 dry-run、apply 和 post-audit 分开；误写默认不做数据库级删除，只能另立更正或清理方案。

---

## 23. 性能预算

### 23.1 已有量级证据

| 证据时间 | 事实 | 用途 |
| --- | --- | --- |
| 2026-08-29 | Tushare `etf_basic` 无过滤/显式字段均为 1,829 行 | Basic 当前一页、小内存处理合理 |
| 2026-08-29 技术方案基线 | 当前可请求量级约 1,647 个，Prod 分钟约 6,787 万行 | 只用于预估；说明不能 Python 明细循环或对 Prod 做 N3 全量审计，不是代码常量 |
| 2026-08-30 P0 | 实际 `TushareResource` 的 `offset=0/5000` 分别返回 1,829/0 行，字段一致且无重复代码 | 关闭真实分页边界，不引入新的分页机制或人工行数上限 |
| 2026-08-30 P2 | 实际 `TushareResource` 经正式 P2 writer 写入 `/private/tmp`：source/raw 均为 1,829 行、14 字段一致、主键和值域通过、Raw hash 回读一致，1 个短页请求 | 证明源请求、通用分页、staging、Raw schema、内容 hash 和不可变提升在临时湖闭环；未触碰正式 Lake 或 Dagster instance |
| 2026-08-30 P0 | `.SH/.SZ` 在五频分钟中分别只对应 `XSHG/XSHE`；单日五频 coverage 1 条 SQL 为 4.538 秒，10 个交易日 1 条 SQL 为 14.573 秒 | 冻结 exchange 比较映射，并证明 P4 可按同一查询形状实现单日/最多 10 日 evaluator |
| 2026-08-30 P0 | 20 个交易日按频率聚合约 1,046 万行，最大单频为 `1min` 的 7,854,190 行，聚合耗时 19.916 秒；单日 `1min` 导出并回读 396,927 行、4.44 MB、29.750 秒，DuckDB temp 增量为 0 | 冻结 P6 单频 20 日批次的真实行数量级和明细导出基线；不是正式 Lake 写入 |

所有数字都会变化。Bootstrap 前必须重新测量；Prod 侧只做经批准的小样本导出或有界状态探测，N3 的全量 profiling 在本地 Raw 上完成。

### 23.2 执行预算表

| 入口 | 读取/请求模型 | 写入模型 | 固定上限/拒绝策略 |
| --- | --- | --- | --- |
| Basic Raw asset | `ceil(source_rows/5000)` 次 Tushare 请求，直到短页；当前 1 页 | 1 staging + 0/1 新 Raw version | 不增加 ETF 专属页数/行数熔断；任一页失败、字段漂移、空结果或重复主键时整次不发布 |
| Basic Silver asset | 读 1 个冻结 Raw 文件，1 次 DuckDB set-based COPY | 1 staging + 0/1 新 Silver version | 禁止扫描所有历史 snapshot |
| 分钟 Raw 日常 | Sensor 对最早候选日 1 条五频 coverage SQL；5 个 Raw asset 各 1 条单日单频明细 SQL，Raw 内不重查 coverage/fingerprint；随后五频 `bar_domain` 共用 1 个 DuckDB connection | 最多 5 个 Raw 文件 + 5 个 blocking check evaluations | 每个自然日最多 6 条 Prod SQL；不允许 ETF×频率 N+1；五个 bar_domain 不得五次重扫 |
| 分钟 Silver 日常 | 正式 job 先执行同日五频 Raw checks，其中 `bar_domain` 必须共用 1 个 DuckDB connection/一次 evaluator；随后各读 1 个 Raw 文件做 COPY/对账 | 最多 5 个 Silver 文件 | 不访问 Prod，不跨日期扫描，不重跑 Raw writer，不使用额外 run config/reference；不得把五频 `bar_domain` 拆成五次深扫 |
| Raw Sensor tick | 10 日期 batch Raw Lake readiness；最早候选日最多 1 次五频代码物理覆盖 query，不为 N3 预扫 Prod 价格/网格/空洞 | 0/1 RunRequest，小 cursor | 一次 DuckDB connection 复刻三项 Raw checks；任一失败停在最早日期；coverage/Basic 异常只 skip |
| Silver Sensor tick | 10 日期、Raw/Silver 最多 100 个目标路径的 true batch Lake readiness | 0/1 RunRequest | 1 个 Raw DuckDB batch + 必要时 1 个 Silver DuckDB batch；不读 Dagster event history；最早 not-ready 日不越过 |
| Bootstrap plan | 请求上界前最多 10 个 SSE 开市日的 1 条五频 coverage SQL；其它读本地日期/文件/空间证据 | 1 小 JSON 报告 | 单 plan 目标文件最多 10,000；`expected_remote_query_count=1+5×ceil(日数/20)`；证据不足停止 |
| Bootstrap Raw apply | 每个单频 20 日批次恰好 1 条明细 SQL，不重查 coverage/fingerprint | 每个 frozen 日期/频率独立 staging 和 Raw 原子提升，包括显式零行文件 | 实际查询数必须等于 plan 的 `raw_detail_query_count`；不把全历史装内存；checkpoint 逐文件；不写 Silver/event |
| N3A Raw observe | 只读本地 Raw；按频率/年份或受控日期批次列投影聚合 | staging 下 profile/detail/observation/proposed policy | 禁止访问 Prod、逐文件重复深扫或 Python 明细循环；不生成 decision |
| N3B Raw decide | 只读 N3A 结果和已批准 policy version | staging 下 decision manifest/summary | 不重扫 Prod/Raw；policy 未登记、hash 漂移或分区未覆盖时停止 |
| Bootstrap Silver apply | 只读 finalized Raw manifest、`silver_eligible` decision 和现有 Silver 目标 | 每日/频率独立 Silver staging 和原子提升/等价复用 | 不访问 Prod；blocked 分区零写入；Raw reused 不能漏掉 Silver 缺口；Raw/Silver 双向 `EXCEPT ALL` |
| Partition registration | `physical_final_report.json` + Silver 交易日历 + 当前动态分区集合 | 只新增获批缺失 partition keys | 必须先于 event；禁止按有数据日期推导、禁止越水位或顺带补历史 |
| Event backfill | 聚合文件清单 + 已注册分区 + 有界 Dagster 状态 | materialization 最多 `2×target_file_count`；checks 最多 500 | 先 dry-run 和 event 数上限，再单独审批 |

### 23.3 DuckDB 与磁盘

统一使用现有配置：

```text
temp_directory=/Volumes/datasource/.goldenshare_duckdb_tmp
max_temp_directory_size=512GB
memory_limit=16GB
threads=4
preserve_insertion_order=false
```

正式排序由 SQL `ORDER BY` 保证。Bootstrap 计划要求：

```text
free_bytes >= estimated_staging_peak_bytes * 1.25
           + estimated_final_increment_bytes * 1.25
```

若真实 sample 显示该公式低估，必须提高预算，不能带着超预算进入 apply。

### 23.4 P0/P6/P7 必须补齐的真实指标

```text
source_row_count
expected_trade_day_count
target_file_count
query_count
max_rows_per_20_day_frequency_batch
sample_query_elapsed_seconds
temporary_space_peak
final_space_increment
sample_elapsed_seconds
Basic Tushare request/page/quota impact
Prod detail export elapsed per frequency/date batch
N3A Raw observe scanned file/row/byte count
N3A Raw observe SQL count / spill peak / elapsed
targeted Prod anomaly probe count
```

P0 先用现有 `ProdPostgresResource` 连接路径完成有界样本并记录真实耗时。若一个 20 日批次无法在安全时间内完成，先缩小批次；只有证据表明确实需要统一超时能力时，才另立共享 resource 配置审计，不能为 ETF 写专用 conninfo/timeout 逻辑。N3 的主性能证据来自本地 Raw DuckDB 扫描。

---

## 24. 测试矩阵

### 24.1 Basic contract

```text
tests/test_etf_basic_contracts.py
tests/test_etf_basic_assets.py
tests/test_etf_basic_checks.py
tests/test_etf_basic_sensors.py
```

必须覆盖：

- 显式 14 字段、业务参数 `{}`、5000/offset 短页终止。
- 刚好 5000 行会请求第二页；第二页失败不写。
- 空结果、列漂移、跨页重复、未知状态/后缀、SH/SZ exchange 冲突失败。
- `.OF` 进入 Raw、被 Silver 精确过滤；D/P 仍进入 Silver。
- 日期标准化失败整版失败。
- DG Raw/Silver hash 固定 fixture；Parquet 回读可复算；测试不得依赖或断言与 Prod hash 算法一致。
- 同 hash 复用，不同内容生成新版本，已有 hash 路径冲突停止。
- latest-only selector 分别检查最新 Raw 与最新 Silver materialization 及各自绑定的 checks，要求两层各自 `observed_at` 都与 `eligibility_as_of` 同属上海自然日，并要求 Silver 的 `raw_snapshot_hash` 等于最新 Raw hash；旧 Raw + 当天新 Silver、最新 Raw 已变化而 Silver 未跟上、任一层失败或不新鲜时都 fail-closed，不回退旧成功版本，不按目录/mtime 选版本。
- ETF Basic 原样复用通用 full-file helper 的 `limit/offset` 短页分页，不增加专属页数/行数熔断，且不得在 asset 内复制分页循环。
- 正式 run config、Basic reference、plan identity 和 metadata 中不出现 Dagster `storage_id`。
- Sensor cursor 小、checks failed 不自动重跑。

### 24.2 Prod SQL/物理覆盖

```text
tests/test_etf_mins_prod_db.py
tests/test_etf_mins_prod_readiness.py
```

必须覆盖：

- 显式 11 列、正确表、频率和半开日期窗口。
- SQL 不含 `SELECT *`、Basic join、代码过滤和系统字段。
- attach 强制 `TYPE POSTGRES, READ_ONLY`；远端查询 SQL 不嵌连接信息，内存 attach conninfo 不进入日志/metadata。
- coverage 使用现有只读事务、psycopg 绑定参数和 rollback；明细远端 SQL 使用验证后的 literals + `postgres_query`，禁止保留 `%s` 占位符。DuckDB attach 复用现有 resource conninfo 且测试不泄露凭据；静态测试禁止 ETF 专用 conninfo/timeout helper。
- 同一个 batch coverage evaluator 同时覆盖单日期和最多 10 日期两种输入；每个日期都按自己的 `list_date <= trade_date` 形成 expected 集合，一条索引友好 SQL 按 `trade_date + freq` 返回 expected/present/missing 和有界样本，禁止日期×频率查询循环。
- 单日五频缺一或 expected code 缺一都不 ready；它不检查 OHLC、分钟网格和内部空洞。
- P5 测试五个 Raw writers 合计恰好执行 5 条单频明细 SQL，且每个 writer 只校验携带的 coverage reference 和冻结 Basic，不再发 coverage、汇总 fingerprint 或第二次明细查询；P10 再测试 Sensor 对目标日恰好执行 1 条五频 coverage SQL，最终组成日常最多 6 条 Prod SQL 的完整预算。
- `.SH/.SZ` 有界样本冻结实际源 `exchange` 比较映射，反例会阻断身份校验，同时 Raw 原值不被改写。
- 只允许读取 `raw_tushare.etf_minute_bar`；测试扫描 SQL/模块，证明没有任何 `ops.*`、Serving 或其它 Prod 表。

### 24.3 Raw/Silver writer

```text
tests/test_etf_mins_raw_writer.py
tests/test_etf_mins_silver_writer.py
tests/test_etf_mins_checks.py
```

正向：完整 expected 集合、合法 known_non_required、11 字段、五频、同目标复用、Raw/Silver 完全等价。

负向至少包括：

- 历史 Bootstrap 中 expected 缺代码、部分频率缺失能落 Raw 并进入 N3 issue；不得因此写 Silver。日常链在启动前由 coverage evaluator 返回 not-ready；`unexplained_new` 在两条链的 Raw 提升前都阻断。
- 历史 frozen `trade_date + freq` 源端零行时生成 schema 正确的显式零行 Raw 文件；日常链不会在 coverage 未完成时生成这类文件。
- 批次明细出现 frozen 日期外的行、存在未分配源行，或 source/staging/Raw 行数不闭合时停止。
- 代码在 Basic 但目标日早于上市日，不被误算 expected。
- D/P 代码不被误算 expected，实际存在时保留并报告。
- Basic 版本在 run 中途变化，仍使用冻结版本。
- duplicate/null key、date/freq/exchange mismatch。
- invalid OHLC、负 vol/amount、非有限数、越界时间、N3 网格反例。
- staging 回读失败不触碰旧文件。
- 已有目标语义不同停止，不覆盖。
- Silver 不允许 WHERE 删除、去重、填空、舍入或修值。
- Silver metadata 必须继承目标日 Raw materialization 已冻结的两个 Basic hash、两个 `observed_at`、reference fingerprint 和 policy version，并以正式 Raw 文件复算校验；不得从执行当天最新 Basic 重新拼装历史引用。
- partitioned check event 必须带正确 partition。
- 同日五频 `bar_domain` 只建立一个 DuckDB connection/共享 evaluation，发出五个 `blocking=True` checks；green/WARN passed，blocked failed，metadata 都绑定当前 Raw hash 和 policy。
- 某日 N3 blocked 后，该日 Raw 文件保留；Raw 和 Silver Sensors 都停在该日，不越过继续推进。
- 正式 Silver job selection 包含五个 Raw assets 的 checks，但不包含 Raw assets；Raw check 失败时 Silver steps 不执行，通过时才生成 Silver。
- 两个分钟 job 都使用 `in_process_executor`，测试通过正式 `Definitions` 解析 job，断言 selection 与 executor，不用只 import module 的方式冒充验收。

### 24.4 Readiness/Sensors

```text
tests/test_etf_mins_lake_readiness.py
tests/test_etf_mins_sensors.py
tests/test_etf_mins_continuity_performance.py
```

必须覆盖：

- window-before-heavy-work。
- 10 日 true batch，记录 connection/SQL/file count。
- 文件缺失可选；文件存在但 `file_contract/request_scope/bar_domain` 任一失败都 not-ready，不自动覆盖或越过。
- Basic 不新鲜、Prod 物理 coverage 不完整或 probe 异常时零 RunRequest。
- 一 tick 最多一个 RunRequest，最早日期优先，不越过空洞。
- Silver Sensor 不访问 Prod/Tushare。
- 不调用逐日 Dagster readiness，不深扫 event history。
- cursor 小于 8 KB。
- Raw/Silver Sensors 分别调用 `batch_etf_mins_raw_lake_readiness` 与 `batch_etf_mins_silver_lake_readiness`；Raw batch 完整复刻三项 checks，不依赖 Dagster instance/event history。

### 24.5 Bootstrap/保护门禁

```text
tests/test_etf_mins_bootstrap.py
tests/test_etf_mins_bootstrap_cli.py
tests/test_etf_mins_pre2026_protection.py
```

必须覆盖：

- dry-run 无 Lake/event 写入。
- 正式 plan/report 必须在 operation staging；P0 `/private/tmp` 探索报告不能作为 apply 输入。
- 日期、文件、查询、磁盘预算超限 fail-closed。
- 首次 2026 plan 的 protection mode 必须是 `not_applicable/null`；2025 及以前 plan 必须是 `protect_trade_date_gte_2026_01_01` 且保护清单 hash 非空，反向组合全部拒绝。
- plan 使用 1 条水位 coverage；Raw apply 每个 20 日单频批次恰好 1 条明细 SQL，实际总数与 frozen query budget 一致。
- checkpoint 续跑，成功文件复用，冲突停止。
- plan 只能输出 `missing/present_structurally_valid_uncompared/present_invalid`；只有 apply 单次明细导出后才能输出 `added/reused/conflict-stop`。
- Raw apply 不要求 N3 已关闭、不写 Silver/event，也不对 Prod 做全量预审计。
- Raw apply 只有全部目标闭合才生成 `finalized_raw_manifest.parquet/raw_final_report.json`；raw-observe 遇到 operation、plan、manifest、checkpoint、文件或报告 hash 不一致时停止。
- 每个 frozen 日期/频率都有物理 Raw；零源行文件可回读、schema 正确并进入 N3，unexpected date/unassigned row 失败。
- Raw observe 只读取本地 Raw/Basic/交易日历，只生成 profile/issue/建议，不生成 decision 或 `silver_eligible`。
- Raw decide 只接受已登记并经测试的批准 policy；decision manifest 精确覆盖所有 Raw 目标。
- grid profile 先观察再分类；P7A 与 P7B 之间所有分区为 `unclassified`，不回滚 Raw，但阻断 ready、Silver 和日常 Sensors。
- Silver apply 只消费 `silver_eligible=true`，blocked/未知 decision 都零写入。
- Silver apply 只有在全部 Raw/Silver 文件集合、行数、主键和 11 字段物理对账闭合后才生成 `physical_final_report.json`；报告必须绑定 operation、plan、Raw/N3/manifests hashes，并按 protection mode 校验保护清单或显式 `not_applicable/null`，任一不匹配都停止。
- `requested_end_date=2025-12-31` 允许，`2026-01-01` 拒绝。
- 候选行或目标路径混入 2026 拒绝。
- 写前/写后保护 manifest 零变化。
- finalized Raw manifest 同时包含 `added/reused`；缺失 Silver 即使对应 Raw 是 reused 也会进入 Silver work manifest。
- 首次只注册 `2026-01-01..execution_watermark_date` 内 Silver SSE 开市日；2025 及以前只注册获批 plan 日期。分区 apply 不写 Lake/event，重复执行只复用。
- event apply 在任一目标动态分区未注册时零写入。
- partitions/events 只消费同一 operation 的 `physical_final_report.json`；operation/hash 不一致时零写入。event apply 不写 Lake，checks 只限最近 20 日。

### 24.6 Catalog 与静态门禁

扩展现有治理测试，断言：

- 12 个 asset 都在 `LAKE_ASSET_CATALOG`。
- schema、path、partition model、checks 与 Definitions 一致；分钟 Raw Catalog 精确登记三类 blocking checks，`bar_domain` 必须存在且 `blocking=True`。
- Silver Basic/分钟字段覆盖对应 Raw。
- jobs 只有 selection。
- sensors 使用统一 run key、request、cursor builder。
- 正式 defs 无裸 `duckdb.connect()`、无 Python 明细循环写 Parquet。
- ETF Prod SQL 无代码过滤；ETF 分钟代码不 import `src.foundation`、`src.ops`。
- Catalog/definition 的 dataset、domain、source、contract、ingestion、path、checks 与第 19 节完全一致；名称映射同时包含 `etf_basic/etf_mins`。
- 正式 run config、serialized reference、plan identity 和 materialization metadata 不含 Dagster `storage_id`。
- 没有 active pool、current pointer、旧 Lake 或 Kopia 字符串回流。
- asset/job/sensor/check descriptions 非空且符合第 19.4 节中文合同；长路径 stdout 只使用登记里程碑，不泄露 conninfo/SQL/全量列表。

---

## 25. 开发切片

每个切片单独 review、单独验收；不得一次性全做。

### P0：治理、源合同和性能基线（已完成）

改动：技术方案/LLD、真实 Basic 受控验证、`.SH/.SZ` 分钟 exchange 有界样本、单日/最多 10 日 coverage 只读查询原型，以及经批准的小批次 Prod Raw 只读导出 profiling。不得修改生产代码、Prod `ops.*` allowlist、正式 Lake 或 Dagster instance。

完成条件：N1/N2/N4/N5 已按本文冻结；N6 只保留为 P10 启用门禁；N3A 输入输出与 N3B 拍板边界已确认；实际 `TushareResource` 的 `offset=0/5000`、exchange 比较映射、单日/最多 10 日共用 coverage 查询形状、两类 Prod 只读查询策略、样本耗时和 batch 行数都有有界真实证据。P0 不实现分页或 coverage 生产代码，不提前要求 P2/P4 的 fake 测试。

### P1：Catalog、schema、path、partition 基础合同（已完成）

先更新 registry、schema、path helper、频率/日期/hash 纯函数和专属 dynamic partition，不写 assets。

完成条件：catalog/static/path/schema/hash tests 全绿，定义中还没有可写新 asset。

执行结果：已登记 12 条 contract-only Catalog entries 和 4 个 partition models；已落地 4 份字段 schema、6 个正式/候选路径 helper、ETF Basic 内容/请求范围 hash、分钟频率/日期/exchange 比较纯合同，以及专属 `cn_a_etf_mins_trade_days`。现有 registry-first 治理测试明确把这些条目标记为 planned，`readiness=False`；本阶段没有新增 asset/check/job/sensor，也没有加载或访问正式 Dagster instance、Prod DB、Tushare 或正式 Lake。

### P2：ETF Basic Raw（已完成）

原样复用通用 full-file helper 的 `limit/offset` 短页分页，实现 Tushare staging、全页校验、Raw hash、不可变提升、三个 Raw checks 和 Raw job。不增加 ETF 专属页数/行数熔断，不修改通用 helper，也不得在 ETF asset 复制分页循环；Sensor 统一留到 P10。

完成条件：临时目录 fixture 和经批准的最小真实 Tushare 快照完成 source/raw 行数、字段、主键、hash 对账；不写正式 Lake，除非另行授权。

执行结果：已实现 `raw_tushare_etf_basic`、`raw_tushare_etf_basic_source_contract_check`、`raw_tushare_etf_basic_key_domain_check`、`raw_tushare_etf_basic_content_hash_check` 和 `raw_etf_basic_update_job`。Raw 没有业务 config，固定以 `{}` 和显式 14 字段调用未修改的 `fetch_tushare_full_file_to_raw`；候选按 Raw schema 两次回读复算 hash 后，只允许 `write_new/reuse_existing`，同 hash 路径内容冲突使用 `etf_basic_snapshot_conflict` 停止。测试已覆盖正常短页、5,000 行边界、第二页失败、空结果、列漂移、跨页重复、状态/后缀/exchange 错误、`.OF` 保留、hash 回读、等价复用、新版本和冲突停止；三项 checks 均为非分区 `blocking=True`，Raw job 只选择该资产和三项 checks。正式 Definitions 已通过 `dg check defs`。

真实临时验收：2026-08-30 在 `/private/tmp` 通过实际 `TushareResource` 拉取 1,829 行，写入 Raw 仍为 1,829 行、字段顺序精确为 14 列，状态 `D=127/L=1658/P=44`、后缀 `OF=3/SH=1033/SZ=793`，内容 hash `1b68a978cf1fdae5f457da0c899387b8130314256ee10e0636279335f39b8b44` 可从 Parquet 回读复算。临时目录随验证结束清理；未写正式 Lake、正式 Dagster instance、Prod DB，也未实现 P3 或 P10。

### P3：ETF Basic Silver 与 latest-only selector

实现 Silver SQL、不可变版本、三个 Silver checks、Silver job 和冻结 reference；Sensor 统一留到 P10。

完成条件：`.OF` 精确过滤、D/P 保留、日期/数值标准化、Raw/Silver hash 和两层同日 freshness 全部有正反测试；最新失败、不新鲜或旧 Raw + 新 Silver 均不回退。

### P4：Prod Raw 物理覆盖、SQL 和稳定 Raw validator

实现 P0 已验证查询形状对应的单日/最多 10 日共用 batch coverage evaluator、只读单表 allowlist、纯 SQL builder、供 Sensor 使用的单次五频代码 coverage/reference、单次明细 relation 的本地传输对账、六类集合 SQL，以及只阻断传输/合同/身份污染的 Raw validator。网格只生成诊断，不在本切片先写 blocking 结论；Sensor 本身仍到 P10 才实现。

完成条件：fake 正反样本证明同一 evaluator 同时支持单日和最多 10 日、逐日按 `list_date` 计算 expected、五频缺失返回 not-ready、缺失样本有界、输入超过 10 日拒绝且整个调用只执行 1 条 coverage SQL；其余测试证明 SQL 无 Basic 代码过滤、无日期×频率 N+1、无任何 `ops.*`，validator 对 `unexplained_new` 阻断，对 `missing/grid` 只记录历史 Raw 诊断且不准入 Silver。Raw asset 到 P5、Sensor 到 P10 才实现。

### P5：分钟 Raw writer 与稳定 validator 集成

实现五频共享 writer、staging、稳定候选 validator、冲突停止和元数据 helper，暂不把未知网格口径注册成正式 blocking check，也不启用日常 Definitions。

完成条件：临时湖 + fake/read-only source 样本通过；每个 Raw writer 只执行一次明细查询、不执行 coverage/fingerprint 查询，五频调用合计最多五条明细 SQL；`missing/grid` 被记录但不阻断 Raw，`unexplained_new` 和传输/合同错误阻断；未启用 Sensor，未写正式 Lake。

### P6：Bootstrap plan 与 Raw apply

先实现只读 frozen plan、目标冲突/空间/查询预算和 protection mode 合同；首次 2026 范围显式不启用零变化保护，P11 才生成 2026 保护清单。单独授权后按频率/20 日批次写 staging、执行稳定门禁、提升 Raw 并逐文件 checkpoint。

完成条件：每个 20 日单频批次只有一次明细查询，source/staging/Raw 行数、范围、hash 和文件集合闭合，每个 frozen 日期/频率都有普通或显式零行 Raw；全部目标完成后才生成 `finalized_raw_manifest.parquet/raw_final_report.json`；N4 截止日确定，protection mode 与范围匹配，若为 P11 模式则 2026 保护清单零变化；不写 Silver，不补事件，不宣称 Raw ready。

### P7A：本地 Raw N3 observation/profile

实现第 14.4/20.5 节的 profile、issue、observation summary 和 proposed policy。只读正式 Raw/Basic/交易日历，不访问 Prod；异常回查清单另行执行。

完成条件：全部 Raw 目标都被 observation manifest 覆盖；扫描文件/行/字节、SQL 数、spill 和耗时有真实报告；没有 decision、`silver_eligible` 或生效 policy。

### P7B：N3 policy freeze 与 decision manifest

管理员审阅 P7A 真实报告并拍板后，冻结 issue→blocking/WARN 映射、阈值、例外、reason codes 和 `gap_policy_version`，实现 raw-decide 与正反测试。

完成条件：全部 Raw 目标都有确定 decision；policy/hash 可复算；blocked、WARN 和 green 样本都能解释，Silver 才可进入 P8。

### P8：分钟 Raw/Silver assets/checks/jobs 与 Bootstrap Silver apply

在 N3 policy 冻结后实现五频 Raw/Silver asset factories、Raw 三类 blocking checks、两类 Silver blocking checks、两个 jobs、同日五频单次 `bar_domain` evaluator，以及从 finalized Raw manifest 构造 Silver work manifest、完成物理集合审计并生成 `physical_final_report.json` 的历史入口。

完成条件：11 字段两个方向 `EXCEPT ALL=0`，没有修值或删行；blocked/未知 decision 分区零 Silver 写入且日常连续性停在该日；五个 `bar_domain` evaluations 共用一次扫描，正式 Silver job 的 Raw check 失败会阻断 Silver steps；报告链 hash 和 Raw/Silver 物理集合闭合后才生成 `physical_final_report.json`。

### P9：历史动态分区与 Runless events

只消费 P8 生成并验收的 `physical_final_report.json`：先单独 dry-run/授权注册历史动态分区，再单独 dry-run/授权补 materialization 和最近 20 日 checks，最后做 post-audit。任一 operation/hash 漂移或目标分区未注册时不得写入。

### P10：分区与更新 Sensors

实现 true-batch readiness、五个默认 STOPPED Sensors，完成本地静态/隔离测试。

完成条件：分钟 Raw Sensor 每个目标日只执行一次五频 coverage，结合 P5 已验证的五条单频明细 SQL，日常链最多六条 Prod SQL；Raw/Silver continuity 都只读最近 10 个交易日并停在最早 not-ready 日。启用仍需另一次授权，并按 Basic Raw→Basic Silver→分钟 Raw→分钟 Silver 顺序各观察至少一个自然生产日；任一层异常时不启用下游。

### P11：2026 年以前独立补录

在 P6-P9 主链验收后，使用第 21 节保护合同单独计划、授权和执行；下游消费完整 finalized manifest，按缺失/等价/冲突处理 Silver 与事件，并证明 2026 年及以后文件写前写后零变化。

单个 frozen plan 仍受 10,000 个目标 Raw 文件上限约束。若完整历史范围超限，按连续、互不重叠的日期段拆成多份 plan；每份分别冻结 Basic、水位、查询/空间预算、保护清单和 plan fingerprint，串行完成 Raw→N3→Silver→分区→事件后再进入下一份。不得让相邻计划重叠，也不得为了省审批把多个 plan 合并到一个进程并行写。全部计划完成后，对其日期并集做一次总文件集合审计，并再次证明 2026 保护清单零变化。

---

## 26. 失败停止条件

出现以下任一情况立即停止当前阶段：

1. Basic 源字段、分页、状态、后缀或行数不能解释。
2. Basic 为空、跨页重复、hash 回读不一致或同 hash 路径内容冲突。
3. 最新 Basic Raw/Silver 任一层不是当天、任一层 checks 没有绑定对应当前 materialization、两层内容不对齐，或运行中 reference 漂移。
4. Prod SQL 需要 Basic join/代码过滤才能跑完，或 20 日批次超时/超空间。
5. 实现试图读取任何 Prod `ops.*`、Serving 表，或用执行状态代替 Prod Raw 物理覆盖。
6. 进入 Silver、补 green check event 或启用分钟日常 Sensors 前，N3 仍未解释内部空洞、停牌/空结果和部分频率缺失；该条件不回滚已经通过稳定门禁的 Raw 文件，但 N3B 冻结后失败的 `bar_domain` 会阻断日常连续性。
7. candidate 出现 `unexplained_new`、Basic/exchange 身份污染、主键/字段/物理类型/日期/频率/路径异常；价格空值、负成交量、OHLC、网格和内部空洞不在这里提前判死，而是进入 N3。
8. 正式目标与候选不等价。
9. 2025 及以前补录触碰或改变任何 2026 及以后文件。
10. Sensor 需要超过 10 日重扫、逐日 event history 或调高 RPC timeout 才能工作。

停止时保留旧正式文件，不删除、不覆盖、不自动重跑；输出 reason code、计数、有界样本和下一步。

---

## 27. 完成定义

只有同时满足以下条件才能说“ETF 分钟已经完整接入 DG”：

1. 12 个 assets、对应 checks、4 个 update jobs、5 个 Sensors、专属 partition 和 catalog 全部与本文一致；Raw readiness 只有三项 blocking checks 这一套正式合同。
2. Basic 无业务过滤、14 字段、不可变 Raw/Silver 版本和 latest-only 冻结可独立复算；两层最新 materialization 必须分别通过 checks 且各自满足当天 freshness，不允许回退。
3. 每次分钟 run 都记录并复核固定 Basic 两个 hash、两个 `observed_at`、eligibility date 和 requestable hash。
4. Prod 明细从 `prod-raw-db.raw_tushare.etf_minute_bar` 无 Basic 过滤读取；日常启动前做五频代码物理覆盖，候选提升前完成导出稳定性、六类集合和 Raw 前合同校验，且不访问任何 `ops.*`。
5. N3A 已用本地 Raw DuckDB 产出真实 observation/profile，N3B 的 blocking/WARN 经管理员批准并版本化；日常同日五频只做一次 `bar_domain` evaluation，五个 blocking checks 绑定当前 Raw，Silver 正式 job 在同一 run 内先执行 Raw checks。Prod 只承担 Sensor/plan 的单次有界 coverage、受控单次明细导出和异常有界回查，不做重复 fingerprint 或全量深审计。
6. Raw/Silver 在批准日期范围完成行数、主键、11 字段值和文件集合对账。
7. Bootstrap 可幂等续跑，只新增/复用，冲突停止。
8. 2025 及以前补录证明 2026 及以后文件零变化。
9. 历史动态分区先于 runless events 注册；分区、事件和物理写入分别授权，Sensors 默认 STOPPED 并经自然运行验收。
10. 没有 ETF 激活池、`fund_daily`、旧 Lake、Kopia、Prod N+1 或 Python 明细循环。
