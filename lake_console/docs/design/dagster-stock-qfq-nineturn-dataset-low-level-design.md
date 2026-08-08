# 股票前复权九转资产族低层设计

状态：代码级设计已完成，待 P0 profiling 和开发批准

上位方案：
[`dagster-stock-qfq-nineturn-dataset-plan.md`](./dagster-stock-qfq-nineturn-dataset-plan.md)

## 1. 设计依据与当前代码事实

本 LLD 依据：

1. 根 `AGENTS.md`、`lake_console/orchestrator/AGENTS.md`、`CODING_STANDARDS.md`。
2. `dagster-data-pipeline-performance-governance.md`。
3. `dagster-asset-schema-contract-design.md`。
4. `dagster-dataset-onboarding-template.html`。
5. 现有股票日线 QFQ、分钟 QFQ、MACD/KDJ 和 Tushare 九转代码。

CodeGraph 影响面审计覆盖：

- `gold_stock_daily_qfq` 的 asset、ordinary check、update job/sensor、factor repair helper/job/sensor。
- `gold_stk_mins_qfq_30m/60m/90m/120m` 的 asset、path、schema、readiness、daily job/sensor 和 factor repair。
- `raw_tushare_stk_nineturn`、`silver_stock_nineturn_daily` 的现行分区和源镜像职责。
- `LAKE_ASSET_CATALOG`、partition model、字段 schema、中文名、静态门禁和治理测试。

当前稳定事实：

| 事实 | 当前代码锚点 |
| --- | --- |
| 日线 QFQ 按交易日单文件 | `defs/assets/stock_daily_qfq.py`、`gold_stock_daily_qfq_path(...)` |
| 30m/60m QFQ 是 native 频度 | `defs/assets/stk_mins.py` |
| 90m 从 30m、120m 从 60m 派生 | `qfq_source_freq_for_derived_freq(...)`、`write_gold_stk_mins_qfq_derived_asset_partition(...)` |
| 分钟 QFQ 按股票年份文件 | `gold_stk_mins_qfq_path(...)` |
| 分钟 QFQ 分区集 | `cn_a_stock_mins_silver_trade_days` |
| 日线 QFQ 分区集 | `cn_a_stock_trade_days` |
| MACD/KDJ 单独保存 state 是因为递推公式 | `defs/assets/stk_mins_qfq_macd_kdj.py` |
| Tushare 九转 Silver 不自行重算 | `defs/assets/stk_nineturn.py` |

## 2. 最终 Definition 名称

### 2.1 Assets

```text
gold_stock_daily_qfq_nineturn
gold_stk_mins_qfq_nineturn_30m
gold_stk_mins_qfq_nineturn_60m
gold_stk_mins_qfq_nineturn_90m
gold_stk_mins_qfq_nineturn_120m
```

### 2.2 Checks

```text
gold_stock_daily_qfq_nineturn_integrity_check
gold_stk_mins_qfq_nineturn_30m_integrity_check
gold_stk_mins_qfq_nineturn_60m_integrity_check
gold_stk_mins_qfq_nineturn_90m_integrity_check
gold_stk_mins_qfq_nineturn_120m_integrity_check
```

### 2.3 Jobs 和 Sensors

```text
gold_stock_daily_qfq_nineturn_update_job
gold_stock_daily_qfq_nineturn_update_job_sensor

gold_stk_mins_qfq_nineturn_update_job
gold_stk_mins_qfq_nineturn_update_job_sensor
```

不新增 schedule、AutomationCondition、state asset、summary asset 或 serving asset。

## 3. 代码文件清单

### 3.1 新增文件

```text
orchestrator/src/orchestrator/defs/run_contracts/qfq_nineturn.py
orchestrator/src/orchestrator/defs/qfq_nineturn.py
orchestrator/src/orchestrator/defs/assets/qfq_nineturn.py
orchestrator/src/orchestrator/defs/checks/qfq_nineturn_checks.py
orchestrator/src/orchestrator/defs/asset_guards/qfq_nineturn_lake_readiness.py
orchestrator/src/orchestrator/defs/jobs/stock_daily_qfq_nineturn_update.py
orchestrator/src/orchestrator/defs/jobs/stk_mins_qfq_nineturn_update.py
orchestrator/src/orchestrator/defs/sensors/stock_daily_qfq_nineturn_sensor.py
orchestrator/src/orchestrator/defs/sensors/stk_mins_qfq_nineturn_sensor.py
orchestrator/src/orchestrator/defs/bootstrap/qfq_nineturn_history.py
orchestrator/src/orchestrator/defs/bootstrap/qfq_nineturn_history_cli.py
orchestrator/src/orchestrator/defs/bootstrap/qfq_nineturn_events.py
orchestrator/src/orchestrator/defs/bootstrap/qfq_nineturn_events_cli.py
```

### 3.2 修改文件

```text
orchestrator/src/orchestrator/defs/paths.py
orchestrator/src/orchestrator/defs/run_contracts/asset_column_schemas.py
orchestrator/src/orchestrator/defs/catalog/name_mapping.py
orchestrator/src/orchestrator/defs/catalog/lake_assets.py
orchestrator/tests/test_asset_governance_contracts.py
orchestrator/tests/test_run_contract_static_gates.py
```

Definitions 通过现有 `load_from_defs_folder` 自动发现，不新增手工 definitions 列表。

### 3.3 治理文档同步

代码落地时同时修改：

```text
docs/architecture/dagster-asset-job-topology.html
docs/design/dagster-run-contract-governance.html
```

前者只登记五个资产、两个 job、两个 sensor、依赖关系和两套交易日分区；后者只登记 sensor definition tags、run key、run request、cursor v1 和默认启停边界。两份治理文档链接回本 LLD，不复制公式、SQL、历史写入或 repair 细节。

## 4. 稳定 Contract

`defs/run_contracts/qfq_nineturn.py` 定义：

```python
QFQ_NINETURN_COMPARISON_LAG = 4
QFQ_NINETURN_SIGNAL_THRESHOLD = 9
QFQ_NINETURN_VERSION = 1
QFQ_NINETURN_MINUTE_FREQS = (30, 60, 90, 120)
QFQ_NINETURN_HISTORY_CHECK_WINDOW = 20
QFQ_NINETURN_SENSOR_WINDOW_DAILY = 10
QFQ_NINETURN_SENSOR_WINDOW_MINUTE = 5
QFQ_NINETURN_FALLBACK_CODE_LIMIT = 500
```

同时定义不可变结果模型：

```python
@dataclass(frozen=True, slots=True)
class QfqNineturnPartitionWriteResult:
    target_path: Path
    source_row_count: int
    output_row_count: int
    stock_code_count: int
    fallback_recomputed_code_count: int
    source_file_count: int
    source_fingerprint: str
    observed_columns: tuple[str, ...]
```

`source_fingerprint` 只由排序后的相对路径、文件大小和纳秒 mtime 生成 SHA-256，用于确认本次读取期间上游没有变化。禁止读取完整文件计算 SHA-256，避免日常执行退化。

### 4.1 配置项审计结论

本专项不新增配置项：

| 配置载体 | 结论 | 原因 |
| --- | --- | --- |
| 环境变量 | 不新增 | 没有账号、地址、密钥或部署环境差异 |
| `Settings` / 数据库 / 配置文件 | 不新增 | 九转公式不是运营可调策略 |
| Dagster resource | 不新增 | 只消费现有 Lake QFQ 文件 |
| Dagster typed config / run config 业务字段 | 不新增 | partition key 已完整表达一次运行的业务输入 |
| 公式运行开关 | 禁止新增 | 同一资产不能因一次运行参数不同而改变业务含义 |

`QFQ_NINETURN_COMPARISON_LAG`、`QFQ_NINETURN_SIGNAL_THRESHOLD`、`QFQ_NINETURN_VERSION`、`QFQ_NINETURN_MINUTE_FREQS` 是版本化的数据 contract 常量，不是运维配置。所有生产消费者必须从 `defs/run_contracts/qfq_nineturn.py` 导入；sensor、asset、check、bootstrap 和测试不得重复字面定义。

改变上述常量必须先更新方案与 LLD、升级 `QFQ_NINETURN_VERSION`、补充金样本并设计历史 rebuild。禁止用环境变量、Dagster UI config 或临时 CLI 参数绕过版本治理。

## 5. Schema

在 `asset_column_schemas.py` 新增：

```python
GOLD_STOCK_DAILY_QFQ_NINETURN_SCHEMA = (
    ColumnContract("ts_code", "VARCHAR", "标准股票代码"),
    ColumnContract("trade_date", "DATE", "交易日"),
    ColumnContract("close_qfq", "DOUBLE", "九转使用的前复权收盘价"),
    ColumnContract("up_count", "INTEGER", "连续上九转计数"),
    ColumnContract("down_count", "INTEGER", "连续下九转计数"),
    ColumnContract("nine_up_turn", "VARCHAR", "上九转信号，+9 或空"),
    ColumnContract("nine_down_turn", "VARCHAR", "下九转信号，-9 或空"),
)

GOLD_STK_MINS_QFQ_NINETURN_SCHEMA = (
    ColumnContract("ts_code", "VARCHAR", "标准股票代码"),
    ColumnContract("freq", "INTEGER", "分钟频度，30、60、90 或 120"),
    ColumnContract("trade_date", "DATE", "交易日"),
    ColumnContract("trade_time", "TIMESTAMP", "分钟 bar 时间"),
    ColumnContract("close_qfq", "DOUBLE", "九转使用的前复权收盘价"),
    ColumnContract("up_count", "INTEGER", "连续上九转计数"),
    ColumnContract("down_count", "INTEGER", "连续下九转计数"),
    ColumnContract("nine_up_turn", "VARCHAR", "上九转信号，+9 或空"),
    ColumnContract("nine_down_turn", "VARCHAR", "下九转信号，-9 或空"),
)
```

主键：

```text
daily:  (ts_code, trade_date)
minute: (ts_code, freq, trade_time)
```

`trade_date` 必须等于 partition key；分钟文件内 `freq` 必须等于 asset 频度。

## 6. Path Helpers

在 `paths.py` 新增：

```python
def gold_stock_daily_qfq_nineturn_path(root: Path, partition_key: str) -> Path

def gold_stk_mins_qfq_nineturn_path(
    root: Path,
    freq: int | str,
    partition_key: str,
) -> Path
```

返回：

```text
gold/indicator/stock_daily_qfq_nineturn/trade_date=<date>/part-000.parquet
gold/indicator/stk_mins_qfq_nineturn/freq=<freq>/trade_date=<date>/part-000.parquet
```

staging 固定在同卷：

```text
gold/indicator/stock_daily_qfq_nineturn/_staging/run_id=<run_id>/trade_date=<date>/part-000.parquet
gold/indicator/stk_mins_qfq_nineturn/_staging/run_id=<run_id>/freq=<freq>/trade_date=<date>/part-000.parquet
```

writer 使用 `.tmp -> contract validate -> os.replace`，失败时删除 staging，原目标文件保持不变。

## 7. 计算 SQL

### 7.1 全历史公式

共享 SQL 只读取业务键与 `close`：

```sql
direction = CASE
  WHEN close_qfq > LAG(close_qfq, 4) OVER code_order THEN 1
  WHEN close_qfq < LAG(close_qfq, 4) OVER code_order THEN -1
  ELSE 0
END
```

再用窗口函数生成连续段，不使用 recursive CTE：

```sql
segment_start = direction = 0 OR direction != LAG(direction) OVER code_order
segment_id = SUM(segment_start::INTEGER) OVER code_order
segment_count = ROW_NUMBER() OVER (PARTITION BY ts_code, segment_id ORDER BY bar_time)
```

输出：

```sql
up_count = CASE WHEN direction = 1 THEN segment_count ELSE 0 END
down_count = CASE WHEN direction = -1 THEN segment_count ELSE 0 END
nine_up_turn = CASE WHEN up_count >= 9 THEN '+9' END
nine_down_turn = CASE WHEN down_count >= 9 THEN '-9' END
```

`bar_time` 对日线为 `trade_date`，对分钟为 `trade_time`。

### 7.2 日常增量

正常路径只处理目标分区：

1. 读取上一 expected trade date 的九转输出，取每个股票最后一行的方向和 count 作为连续段种子。
2. 从 QFQ source 读取目标日期所有行，以及每个目标股票前 4 根实际 bar。
3. 计算目标日期方向与连续段；若第一段方向等于种子方向，第一段 count 在种子 count 上递增。
4. 新股没有历史 bar 时从 0 开始。
5. 目标代码有更早 source bar、但上一分区没有对应种子时，进入 code-scoped fallback，从该代码 source 历史精确重算。
6. fallback 代码超过 `QFQ_NINETURN_FALLBACK_CODE_LIMIT` 时 fail closed，要求离线恢复；不得把大量历史扫描塞进普通日常 run。

日线 fallback 通过全历史日线 QFQ 文件投影指定代码；分钟 fallback 直接读取指定代码的 QFQ 股票年份文件。禁止 Python 按 bar 循环。

### 7.3 上游并发保护

writer 在计算前后各生成一次 source fingerprint。两次不一致时：

1. 不 promote staging。
2. 日志写 `qfq_nineturn_source_changed`。
3. run 失败并提示等待上游 QFQ 写入或 repair 完成后重跑。

分钟资产同时复用现有 `GOLD_STK_MINS_QFQ_WRITER_POOL`，避免与分钟 QFQ daily/repair 并发读写同一股票年份文件。日线通过 repair readiness 和前后 fingerprint 保证稳定读取，不修改现有日线 QFQ pool 口径。

## 8. Asset Definitions

### 8.1 Daily

```python
@dg.asset(
    name="gold_stock_daily_qfq_nineturn",
    deps=[dg.AssetDep(gold_stock_daily_qfq, partition_mapping=dg.IdentityPartitionMapping())],
    partitions_def=cn_a_stock_trade_days,
    group_name="quote",
    tags=build_asset_tags(layer=AssetLayer.GOLD, data_domain=DataDomain.QUOTE_DATA),
    metadata=build_asset_definition_metadata(...),
)
```

definition metadata：

```text
dataset_id=stock_daily_qfq_nineturn
source_system=derived
data_contract=qfq_stock_daily_nineturn
formula_version=1
comparison_lag=4
signal_threshold=9
calculation_model=fixed_formula_non_repainting
physical_layout=trade_date_single_file
```

description：

```text
股票日线前复权九转指标，按交易日保存全市场收盘价、连续计数和正负九信号，供每日扫描和多周期研究使用。
```

### 8.2 Minute assets

通过一个局部 builder 生成四个独立 `@dg.asset` definition，但最终 asset key 必须是明确常量，禁止用动态资产 key 逃避治理测试。

每个 asset：

- `deps` 只含同频度 QFQ asset。
- `partitions_def=cn_a_stock_mins_silver_trade_days`。
- `pool=GOLD_STK_MINS_QFQ_WRITER_POOL`。
- `group_name="quote"`。
- `dataset_id=stk_mins_qfq_nineturn`。
- `data_contract=qfq_stock_minute_nineturn`。
- metadata 记录固定 `freq`，不记录运行日期。

### 8.3 Materialization metadata

统一通过 `build_materialization_metadata(...)`，只记录本次事实：

```text
dagster/uri
dagster/row_count
goldenshare/observed_columns
goldenshare/summary
goldenshare/next_action
goldenshare/result_status
goldenshare/input_summary
goldenshare/filter_summary
goldenshare/diagnostic_ref
goldenshare/source_fingerprint
goldenshare/source_row_count
goldenshare/stock_code_count
goldenshare/fallback_recomputed_code_count
goldenshare/formula_version
```

禁止写完整代码列表、全部路径、SQL、DataFrame 或 source schema map。

### 8.4 stdout 事件

使用 `DgStdoutLogger("qfq_nineturn")`：

```text
qfq_nineturn_started
qfq_nineturn_source_loaded
qfq_nineturn_fallback_started
qfq_nineturn_validation_failed
qfq_nineturn_completed
```

日志只写 asset、partition、freq、行数、股票数、fallback 数和耗时。

## 9. 聚合 Blocking Check

`qfq_nineturn_checks.py` 为每个资产创建一个 check，内部 rule 名固定：

```text
file_contract
partition_alignment
key_integrity
value_domain
source_key_coverage
```

检查模型：

```python
@dataclass(frozen=True, slots=True)
class QfqNineturnIntegrityDiagnostics:
    passed: bool
    checked_row_count: int
    source_row_count: int
    duplicate_key_count: int
    null_key_count: int
    invalid_value_count: int
    missing_source_key_count: int
    extra_output_key_count: int
    failed_rule_names: tuple[str, ...]
    failure_samples: tuple[dict[str, object], ...]
```

AssetCheckResult metadata 必须通过 `build_check_metadata(...)`，并增加中文：

```text
summary
next_action
rule_summary
failed_rule_names  # 转成 list，不能传 tuple
diagnostic_ref
```

Check 禁止 import 或调用九转 select/calculation helper。静态门禁扫描 `qfq_nineturn_checks.py`，禁止出现 `LAG(close`、`segment_id`、`QFQ_NINETURN_COMPARISON_LAG` 等公式实现。

## 10. Readiness

`qfq_nineturn_lake_readiness.py` 定义：

```python
GOLD_STOCK_DAILY_QFQ_NINETURN_READINESS_SPEC
GOLD_STK_MINS_QFQ_NINETURN_READINESS_SPECS

batch_gold_stock_daily_qfq_nineturn_readiness(...)
batch_gold_stk_mins_qfq_nineturn_readiness(...)
```

readiness 复刻聚合 check 的文件、schema、键、值域和 source key coverage，不计算公式。

读取模型：

- 日线 sensor 最多 10 个日期，一次规划目标文件和 QFQ source 文件。
- 分钟 sensor 最多 5 个日期，按 4 个频度批量执行。
- 不逐日期读取 Dagster event history。
- selected date 的 factor repair 状态复用现有 bounded helper。

## 11. Jobs

`jobs/stock_daily_qfq_nineturn_update.py`：

```python
gold_stock_daily_qfq_nineturn_update_job = dg.define_asset_job(
    name="gold_stock_daily_qfq_nineturn_update_job",
    selection=(
        dg.AssetSelection.assets(gold_stock_daily_qfq_nineturn)
        | dg.AssetSelection.checks_for_assets(gold_stock_daily_qfq_nineturn)
    ),
)
```

`jobs/stk_mins_qfq_nineturn_update.py`：

```python
gold_stk_mins_qfq_nineturn_update_job = dg.define_asset_job(
    name="gold_stk_mins_qfq_nineturn_update_job",
    selection=(
        dg.AssetSelection.assets(*GOLD_STK_MINS_QFQ_NINETURN_ASSETS)
        | dg.AssetSelection.checks_for_assets(*GOLD_STK_MINS_QFQ_NINETURN_ASSETS)
    ),
    executor_def=dg.in_process_executor,
)
```

job 文件禁止 import DuckDB SQL、path helper 或 writer。

## 12. Sensors

### 12.1 日线 sensor

决策顺序：

1. 加载最近 10 个 expected stock trade dates。
2. 检查 `cn_a_stock_trade_days` 注册缺口。
3. 选择第一个九转未 ready 日期。
4. 检查同日 `gold_stock_daily_qfq` ordinary readiness。
5. 复用 `build_gold_stock_daily_qfq_factor_repair_plan(...)` 计算同日计划。`repair_required=false` 时直接通过；`repair_required=true` 时再读取 `gold_stock_daily_qfq_factor_repair_status(...)`，且必须 ready。不得等待一个“无需修复”时本来就不会产生的 repair event。
6. 非首日要求上一 expected 九转分区 ready。
7. 目标已 materialized 但 check failed 时 skip。
8. 提交一个 `RunRequest`。

### 12.2 分钟 sensor

决策顺序相同，但：

- 读取最近 5 个 expected minute silver trade dates。
- 上游只要求 30/60/90/120m QFQ ready。
- 必须等待同日 `stock_mins_qfq_factor_repair_job` 的最终状态。现行分钟 repair job 无论是否需要改写都会完成检测并写入七个 repair plan checks，因此直接复用 `gold_stk_mins_qfq_factor_repair_status(...)`。
- 四个目标资产作为一个日期级原子业务批次，任一上游频度未 ready 都不提交。

### 12.3 Run key

复用统一 builder：

```python
build_asset_update_run_key(
    subject="gold_stock_daily_qfq_nineturn_update",
    unit_id=trade_date,
)

build_asset_update_run_key(
    subject="gold_stk_mins_qfq_nineturn_update",
    unit_id=trade_date,
)
```

### 12.4 Cursor

使用 v1 标准顶层 contract，普通 cursor 小于 2KB：

```text
sensor_name
job_name
asset_family
partition_set
reason_code
blocked_component
summary
next_action
frontier
gate_statuses
evidence
performance_ms
diagnostic_ref
```

`blocked_component` 允许值：

```text
cn_a_stock_trade_days
cn_a_stock_mins_silver_trade_days
gold_stock_daily_qfq
gold_stock_daily_qfq_factor_repair
gold_stk_mins_qfq
gold_stk_mins_qfq_factor_repair
previous_qfq_nineturn_partition
target_qfq_nineturn_check
none
```

禁止 `status_samples`、完整 readiness 报告、路径列表、代码列表和 factor repair metadata 全量复制。

### 12.5 Sensor tags

```text
goldenshare/sensor_domain=quote_data
goldenshare/sensor_target_layer=gold
goldenshare/sensor_role=asset_update
```

最终枚举值必须由现有 `build_sensor_tags(...)` 支持的正式枚举生成，禁止手写 tag dict。

### 12.6 人的排障入口

每一层只回答一个问题，禁止把同一份大报告复制到 cursor、日志和 metadata：

| 问题 | 第一入口 | 必须可见的最小信息 | 禁止内容 |
| --- | --- | --- | --- |
| sensor 为什么没触发 | cursor | `target_date`、`reason_code`、`blocked_component`、短中文 `summary`、`next_action` | 完整 readiness、路径/code 列表、factor repair metadata |
| run 为什么失败 | stdout/stderr | asset、partition、freq、当前阶段、关键数量、失败动作 | 完整 SQL、DataFrame、全量股票列表 |
| 本次写出了什么 | materialization metadata | URI、row count、股票数、fallback 数、source fingerprint、结果摘要 | 稳定 schema 的重复副本、完整源路径集合 |
| check 为什么失败 | check metadata | `failed_rule_names`、各规则摘要、失败数量、最多有限样本、下一步动作 | 二次计算公式、全量失败行 |
| 历史流程为什么停止 | plan/progress/final audit | batch、fingerprint、stop reason、已写/待写数量、回滚事实 | 把全历史明细塞进 Dagster cursor/event |

具体排障顺序固定为：

1. 没触发先看 cursor，按 `next_action` 定位阻断的上游 QFQ、factor repair、上一九转分区或目标 check。
2. run 失败先看最后一个 stdout 里程碑，确认失败发生在 source load、fallback、validation 还是 promote 前；再看异常栈和本次 metadata。
3. check 失败直接看聚合 check 的失败规则、数量和样本，不去读 sensor cursor 猜质量问题。
4. 历史 bootstrap/rebuild 失败只以 `/private/tmp` 的 plan/progress/final audit 和 manifest 为执行证据，不从 Dagster UI 的少量事件反推全历史完成情况。

## 13. Catalog

新增两个 dataset 中文名：

```text
stock_daily_qfq_nineturn -> 股票日线前复权九转
stk_mins_qfq_nineturn -> 股票分钟线前复权九转
```

新增两个 partition model：

```text
trade_date_partition_gold_stock_daily_qfq_nineturn
trade_date_partition_gold_stock_mins_qfq_nineturn
```

physical layout 均为 `PartitionPhysicalLayout.PARTITION_FILE`。四个分钟 entry 共用分钟 partition model。

Catalog entries：

```text
source_system=derived
ingestion_sources=(derived_from_assets,)
bootstrap_sources=(derived_from_assets,)
write_policy=partition_file_atomic_replace
event_policy=supports_runless_event_backfill
batch_grain=trade_date / freq_trade_date
compute_engine=duckdb_sql
```

blocking check 必须与第 2.2 节五个名称完全一致。

## 14. 历史 Bootstrap 与 Event

### 14.1 CLI

```text
python -m orchestrator.defs.bootstrap.qfq_nineturn_history_cli plan
python -m orchestrator.defs.bootstrap.qfq_nineturn_history_cli build --apply
python -m orchestrator.defs.bootstrap.qfq_nineturn_events_cli plan
python -m orchestrator.defs.bootstrap.qfq_nineturn_events_cli report --apply
```

默认均只读。`--apply` 还必须要求新鲜 plan path 和 fingerprint。

### 14.2 History plan

报告输出 `/private/tmp/qfq_nineturn_history_plan_<timestamp>.json`，至少包含：

```text
source ranges by asset/freq
source row counts
expected output row counts
expected trade-date file counts
year batch row counts
estimated source/output/staging bytes
duplicate/null/date/freq diagnostics
latest 20 trade dates
plan fingerprint
stop reasons
```

### 14.3 History build

按 `asset/freq/year` 分批：

1. 读取该年 source 和上一年尾部计算上下文。
2. DuckDB 一次计算该批所有代码，不在 Python 中逐 bar 递推。
3. `COPY ... PARTITION_BY (trade_date)` 写 staging。
4. 每个 trade_date 恰好生成一个 Parquet，规范化为 `part-000.parquet`。
5. 校验 source/output key 差异为 0 后原子 promote。
6. 每个年度完成后写 progress report。

### 14.4 Runless events

正式 apply 只调用 `DagsterInstance.report_runless_asset_event(...)`：

- 所有实际历史分区：1 条 materialization。
- 每个资产最近 20 个实际交易日：1 条聚合 check evaluation。
- check evaluation 必须绑定本轮或现有目标 materialization。
- 已有一致 event 跳过；已有失败或冲突状态停止。

按当前约 3,062 个日线 QFQ 分区静态估算，materialization 上界约为 `5 * 3,062 = 15,310` 条；checks 固定上界为 `5 * 20 = 100` 条。P0 必须用真实各频度日期集合替换该估算。

## 15. 上游历史修正策略

不新增自动 repair sensor。

普通 QFQ repair 若只产生每个代码统一的正比例缩放，九转比较方向保持不变。日常 sensor 只等待该 repair 完成后生产当前分区，不回写历史九转。

若非等比例历史修正被确认，使用离线 history CLI 的 scoped rebuild 模式：

```text
--asset-family daily|minute
--freqs 30 60 90 120
--stock-codes-file <approved file>
--start-date <date>
--end-date <date>
--apply
```

scoped rebuild 仍按完整代码序列计算，不能从 `start-date` 把老股票计数归零。它只替换明确范围内目标日期文件中的受影响代码行，并保留其它代码行；所有 staging 文件先完整生成再逐分区原子替换。

## 16. 测试文件与用例

新增：

```text
tests/test_qfq_nineturn_formula_golden.py
tests/test_qfq_nineturn_writer.py
tests/test_qfq_nineturn_checks.py
tests/test_qfq_nineturn_readiness.py
tests/test_stock_daily_qfq_nineturn_sensor.py
tests/test_stk_mins_qfq_nineturn_sensor.py
tests/test_qfq_nineturn_history.py
tests/test_qfq_nineturn_events.py
tests/test_qfq_nineturn_governance.py
tests/test_qfq_nineturn_performance.py
```

### 16.1 金样本

固定输入和人工字面 expected 覆盖：

1. 少于 5 根 bar 全 0。
2. 连续上涨比较形成 `1..11`。
3. 连续下跌比较形成 `1..11`。
4. 相等重置。
5. 正负方向切换重置。
6. 跨交易日和跨年份连续。
7. 新股、停牌恢复和种子 fallback。
8. 30/60/90/120m 时间排序。
9. 全部价格乘相同正数后 count/signals 不变。

金样本文件头注明：业务公式未正式变更时禁止修改 expected；确需变更必须同步方案、版本和历史重建计划。

### 16.2 Writer

覆盖：

- 正常目标分区写入。
- schema、日期、频度、重复/空 key 错误不 promote。
- source fingerprint 变化不 promote。
- 上一分区缺失 fail closed。
- 真新股允许从 0 初始化。
- 老股票缺种子走 fallback。
- fallback 超上限失败。
- OHLC 等未使用字段不会进入输出。

### 16.3 Check/readiness

覆盖 5 个 rule 的正反例，并锁定 check 不调用公式 helper。目标 materialized 但 check failed 时两个 sensor 都不得自动重跑。

### 16.4 Sensor

覆盖：

- 注册缺口。
- 上游 QFQ missing/failed。
- factor repair 未评估、进行中、失败、完成和无需 repair。
- 上一九转分区缺失。
- 目标 ready、目标 failed、提交一个 run。
- cursor 小于 2KB 且能直接看懂阻断原因。
- 每 tick 最多一个 `RunRequest`。
- 中文 `summary`、`next_action` 和 `blocked_component` 能分别解释注册分区、上游 QFQ、factor repair、上一九转分区和目标 check 阻断。
- cursor 不包含报告型 readiness、完整 metadata、路径或 code 集合。

### 16.5 历史与 event

覆盖 plan 零写入、stale plan、fingerprint 变化、年度连续性、重复 apply、失败回滚、全历史 materialization 和最近 20 日 check 上限。

## 17. 静态门禁

`test_run_contract_static_gates.py` 增加：

1. check/readiness 禁止导入公式 select helper。
2. 正式计算禁止 recursive CTE 和 Python bar 循环。
3. 不得出现 `qfq_nineturn_state` asset/path/schema。
4. sensor 不得读取 Tushare、prod DB 或全历史 event log。
5. sensor cursor 不得写完整路径、代码列表、`status_samples` 或 batch report。
6. jobs 不得出现 SQL、path 或 writer。
7. production 代码不得硬编码迁移截止日期。
8. 正式资产频度只允许 daily、30、60、90、120。
9. 公式 lag、threshold、version 和 minute freqs 只能在 `run_contracts/qfq_nineturn.py` 定义，生产消费者不得重复字面常量。
10. 禁止九转生产代码通过环境变量、`Settings`、Dagster config 或 CLI 参数改变公式口径。
11. 两个 sensor 的 description、中文 cursor 摘要和 definition tags 必须满足数据集接入模板的人类可读契约。

## 18. P0 Profiling 门禁

开发前先实现或使用 `/private/tmp` 只读脚本，完成：

| 测量 | 验收 |
| --- | --- |
| 最新日五频度 source rows | 与输出预计行数一一对应 |
| 日线普通增量读取 | 小于 15 秒 |
| 四分钟普通增量读取 + 计算 | 合计小于 30 秒 |
| 五个聚合 check | 合计小于 10 秒 |
| 10 日 daily readiness | 小于 3 秒 |
| 5 日 minute readiness | 小于 10 秒 |
| 历史行数/文件数/空间 | 明确数字，不接受经验估计 |

profiling 只读 QFQ 和现有 Dagster 分区注册事实，报告写 `/private/tmp`。不创建目标目录，不写 event，不运行 asset/job/sensor。

若普通增量只有扫描全历史才能正确完成，或任何热路径超过预算，停止开发。优先调整 DuckDB 读取模型，不默认增加 state asset。

## 19. 建议验证命令

开发后本地测试：

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator
uv run python -m unittest \
  tests.test_qfq_nineturn_formula_golden \
  tests.test_qfq_nineturn_writer \
  tests.test_qfq_nineturn_checks \
  tests.test_qfq_nineturn_readiness \
  tests.test_stock_daily_qfq_nineturn_sensor \
  tests.test_stk_mins_qfq_nineturn_sensor \
  tests.test_qfq_nineturn_history \
  tests.test_qfq_nineturn_events \
  tests.test_qfq_nineturn_governance \
  tests.test_qfq_nineturn_performance \
  tests.test_asset_governance_contracts \
  tests.test_run_contract_static_gates
git diff --check
```

`dg check defs`、正式 instance 只读 preflight、Lake 写入、runless event 和 sensor 启用均需后续单独批准。

## 20. 实施顺序

1. P0 只读 profiling。
2. P1 contract、schema、path、公式金样本和 calculator。
3. P2 assets、checks、catalog、readiness。
4. P3 jobs、sensors、cursor、治理测试，并同步 topology 与 run-contract 两份治理文档。
5. P4 bootstrap/rebuild/events 工具。
6. P5 本地全量测试和经批准的 `dg check defs`。
7. P6 经批准的历史写入、runless events、日常 sensor 启用。

每一阶段只在前一阶段验收全绿后进入；P0 性能门禁不通过时不得靠增加 timeout 继续。
