# 股票前复权九转资产族低层设计

状态更新（2026-10-26）：第22节为22日四个分钟分区的写入修正及补齐LLD，当前仅完成代码审计与文档，未开发、未正式执行。现有两股票sensor保持STOPPED；23日数据补齐后再启用的TODO不变。

历史结果：P0至P7R和分钟去价格S0至S5在2026-08-15均已完成，12,272个分钟分区切为八列，并完成当时event、check、Reader/readiness和sensor恢复。2026-08-14旧九列重建只保留为历史，不代表现行合同；日线后续独立修正的六列合同以当前代码为准，本轮不修改日线。

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
| 分钟九转日常 sensor 只推进新增日期，不会发现历史 QFQ 已被重写 | `defs/sensors/stk_mins_qfq_nineturn_sensor.py` |
| 现有 scoped rebuild 面向少量代码/日期，不适合全市场四频全历史重建 | `defs/bootstrap/qfq_nineturn_history.py`、`qfq_nineturn_history_cli.py` |

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
orchestrator/src/orchestrator/defs/qfq_nineturn_integrity.py
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
orchestrator/src/orchestrator/defs/asset_guards/stk_mins_lake_readiness.py
orchestrator/src/orchestrator/defs/run_contracts/asset_column_schemas.py
orchestrator/src/orchestrator/defs/catalog/name_mapping.py
orchestrator/src/orchestrator/defs/catalog/lake_assets.py
orchestrator/tests/test_asset_governance_contracts.py
orchestrator/tests/test_run_contract_static_gates.py
orchestrator/tests/test_stk_mins_lake_readiness.py
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

`trade_date`必须等于partition key；分钟`trade_time`所属日期也必须相同，`freq`必须等于asset频度。分钟当前八列、日线当前六列，均不保存价格；依据是现行`asset_column_schemas.py`。本轮不改schema。公式内部仍使用上游QFQ价格；跨年度context只能在规定的staging临时保存，不能进入正式文件或业务Reader。

## 6. Path Helpers

在 `paths.py` 新增：

```python
def gold_stock_daily_qfq_nineturn_path(root: Path, partition_key: str) -> Path

def gold_stk_mins_qfq_nineturn_path(
    root: Path,
    freq: int | str,
    partition_key: str,
) -> Path

def gold_stock_daily_qfq_nineturn_staging_path(
    root: Path,
    run_id: str,
    partition_key: str,
) -> Path

def gold_stk_mins_qfq_nineturn_staging_path(
    root: Path,
    run_id: str,
    freq: int | str,
    partition_key: str,
) -> Path
```

返回：

```text
gold/indicator/stock_daily_qfq_nineturn/trade_date=<date>/part-000.parquet
gold/indicator/stk_mins_qfq_nineturn/freq=<freq>/trade_date=<date>/part-000.parquet
```

现行规则：所有候选只能位于`/Volumes/datasource/data_lake_staging`，并在提升前检查与正式目标处于同一文件系统。不得在正式Gold内新建`_staging`。第22节定义本轮分钟writer的替代路径和恢复规则。

以下是2026-10-26代码审计发现的旧路径，**不是可执行设计**：

```text
gold/indicator/stock_daily_qfq_nineturn/_staging/run_id=<run_id>/trade_date=<date>/part-000.parquet
gold/indicator/stk_mins_qfq_nineturn/_staging/run_id=<run_id>/freq=<freq>/trade_date=<date>/part-000.parquet
```

旧共享writer失败删除候选，亦不符合本轮失败留存/续跑要求。分钟调用本轮改为第22节；旧分钟helper删除。日线旧helper和writer现状作为范围外问题记录，不能据本文历史段落继续执行日线写入，亦不因本轮分钟修正被认定已修好。

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
2. 计算需要目标日及每代码前4根实际bar；当前分钟实现实际读取目标年和前一年文件后在公式中计算LAG4，再筛目标日，不能把所需4根误写成物理只读4根。日线按自己的context规则执行。
3. 计算目标日期方向与连续段；若第一段方向等于种子方向，第一段 count 在种子 count 上递增。
4. 新股没有历史 bar 时从 0 开始。
5. 目标代码有更早 source bar、但上一分区没有对应种子时，进入 code-scoped fallback，从该代码 source 历史精确重算。
6. fallback 代码超过 `QFQ_NINETURN_FALLBACK_CODE_LIMIT` 时 fail closed，要求离线恢复；不得把大量历史扫描塞进普通日常 run。

日线 fallback 通过全历史日线 QFQ 文件投影指定代码；分钟 fallback 直接读取指定代码的 QFQ 股票年份文件。禁止 Python 按 bar 循环。

P1 已将上述计算口径落为四个纯 SQL builder：

```python
build_gold_stock_daily_qfq_nineturn_select_sql(...)
build_gold_stk_mins_qfq_nineturn_select_sql(...)
build_gold_stock_daily_qfq_nineturn_partition_select_sql(...)
build_gold_stk_mins_qfq_nineturn_partition_select_sql(...)
```

前两个用于全历史精确计算和 fallback；后两个只计算目标分区，接收上一九转分区作为种子，并要求调用方显式传入需要精确重算的 code-scoped fallback。builder 不自行判断资产 readiness，也不读取 Dagster event。

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

`qfq_nineturn_checks.py` 为每个资产创建一个 check。分钟内部 rule 名固定为：

```text
file_contract
partition_alignment
key_integrity
value_domain
source_key_coverage
```

日线在上述五条之外继续包含：

```text
source_value_consistency
```

检查模型：

```python
@dataclass(frozen=True, slots=True)
class QfqNineturnIntegrityDiagnostics:
    passed: bool
    checked_row_count: int
    source_row_count: int
    duplicate_key_count: int
    source_duplicate_key_count: int
    null_key_count: int
    invalid_value_count: int
    missing_source_key_count: int
    extra_output_key_count: int
    source_value_mismatch_count: int  # 仅日线使用，分钟不执行源值比较
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

Check禁止import或调用九转select/calculation helper。分钟检查覆盖文件/schema、分区与时间归属、目标/源键非空唯一、源键覆盖、计数和信号值域；不比较目标价格或重算公式。当前日线也是无价格合同，旧`close_qfq`及`source_value_consistency`文字不再代表现行检查。静态门禁扫描`qfq_nineturn_checks.py`，禁止出现`LAG(close`、`segment_id`、`QFQ_NINETURN_COMPARISON_LAG`等公式实现。

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

分钟上游 QFQ readiness 必须只验证 30/60/90/120m，同时完整保留现有 QFQ blocking checks 语义。实现方式固定为：

1. 在 `stk_mins_lake_readiness.py` 把现有七频度 batch 的内部计算抽成可显式接收 native/derived frequency tuple 的共享私有内核。
2. 现有公开 `batch_gold_stk_mins_qfq_lake_readiness(...)` 继续固定传入全部七频度，签名、消费者和结果语义保持不变。
3. `qfq_nineturn_lake_readiness.py` 新增九转专用上游入口，只传 native `(30, 60)` 和 derived `(90, 120)`。
4. 禁止复制一份 QFQ SQL，禁止用 Dagster materialization-only 或缺少 check event 代替 Lake 完整语义。

P0 中现有七频度 helper 的 5 日窗口实测为 16.267 秒，不满足本专项预算；用同一内核限定为四个所需频度后实测 6.309 秒、五日全部 ready。静态门禁必须禁止新 sensor 直接调用七频度公开 helper。

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
python -m orchestrator.defs.bootstrap.qfq_nineturn_history_cli build \
  --plan-report <reviewed plan> \
  --plan-fingerprint <reviewed fingerprint> \
  --apply
python -m orchestrator.defs.bootstrap.qfq_nineturn_events_cli plan \
  --history-plan <history plan> \
  --history-audit <final audit>
python -m orchestrator.defs.bootstrap.qfq_nineturn_events_cli report \
  --plan-report <reviewed event plan> \
  --plan-fingerprint <reviewed fingerprint> \
  --apply
```

默认均只读。全量 build、scoped rebuild 和 runless event report 都必须要求新鲜 plan path 与 fingerprint；CLI 不能提供绕过 plan 的直接写入口。

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

1. 读取该年 source，以及上一批生成的两份紧凑临时状态：每个代码最多 4 根尾部 source bar、每个代码 1 条末尾方向/计数种子。仅有 4 根尾部 bar 只能恢复跨年比较方向，不能恢复已累计计数，禁止据此把新年首段静默重置为 1。
2. DuckDB 一次计算该批所有代码，不在 Python 中逐 bar 递推。
3. `COPY ... PARTITION_BY (trade_date)` 写 staging。
4. 每个 trade_date 恰好生成一个 Parquet，规范化为 `part-000.parquet`。
5. 校验 source/output key 差异为 0 后原子 promote。
6. 从本批 source/output 生成下一批紧凑上下文和计数种子；它们只存在于 bootstrap staging/progress 目录，不是新 asset、state 数据集或正式 Lake 契约。
7. 每个年度完成后写 progress report。

该模式使每个 source 年份只被业务计算读取一次。跨年附加状态的上界为每个历史代码 5 行，不随已完成年份增长；禁止为计算某一年反复扫描从 2014 年到该年的全部历史。

### 14.4 Runless events

正式 apply 只调用 `DagsterInstance.report_runless_asset_event(...)`：

- 所有实际历史分区：1 条 materialization。
- 每个资产最近 20 个实际交易日：1 条聚合 check evaluation。
- check evaluation 必须绑定本轮或现有目标 materialization。
- 已有一致 event 跳过；已有失败或冲突状态停止。

P0 已确认五个资产各有 3,063 个实际日期，因此正式上界为 15,315 条 materialization 加 100 条最近窗口 check，共 15,415 条。不得为更早分区补 check。

## 15. 上游历史修正策略

不新增自动 repair sensor。

普通 QFQ repair 若只产生每个代码统一的正比例缩放，且 bar key、时间戳和相对价格关系均不变，
九转比较方向才保持不变。日常 sensor 只等待该 repair 完成后生产当前分区，不回写历史九转。

若非等比例历史修正被确认，使用离线 history CLI 的 scoped rebuild 模式：

```text
python -m orchestrator.defs.bootstrap.qfq_nineturn_history_cli plan-rebuild \
  --asset-family daily|minute \
  --freqs 30 60 90 120 \
  --stock-codes-file <approved file> \
  --start-date <date> \
  --end-date <date>

python -m orchestrator.defs.bootstrap.qfq_nineturn_history_cli rebuild \
  --plan-report <reviewed plan> \
  --plan-fingerprint <reviewed fingerprint> \
  --apply
```

scoped rebuild 仍按完整代码序列计算，不能从 `start-date` 把老股票计数归零。它只替换明确范围内目标日期文件中的受影响代码行，并保留其它代码行；所有 staging 文件先完整生成再逐分区原子替换。

### 15.1 Canonical Bars 历史重建属于全量重建

股票 QFQ canonical bars 重建同时改变了 30m/60m 的 key 集合和 90m/120m 的部分价格，不能按
“统一正比例缩放”处理，也不能把当前日常 sensor 视为历史 reconciliation。

2026-08-14 只读审计样本 `2026-08-12`：

| freq | 当前九转与当前 QFQ 的差异 |
| --- | --- |
| 30m | 九转多 5,539 条独立 09:30 行 |
| 60m | 九转多 5,539 条独立 09:30 行 |
| 90m | 9 只股票、27 行 `close_qfq` 不一致 |
| 120m | 9 只股票、18 行 `close_qfq` 不一致 |

四个频率都必须从各自最早实际 QFQ 日期重算到正式执行时冻结的共同 frontier。原因是
`up_count/down_count` 跨 bar、跨日、跨年递推；只修差异日期会把旧 seed 继续传给后续日期。

### 15.2 P7R 专用执行模式

本 LLD 的 P7R 对应 canonical bars 重建 LLD 的 P12，两个编号指向同一项遗漏补偿工作。

在现有 `qfq_nineturn_history.py` / `qfq_nineturn_history_cli.py` 中增加 canonical rebuild 模式，
复用同一公式、schema、compact context 和 seed，不新增第二套计算实现。阶段固定为：

```text
plan-canonical-rebuild
build-canonical-candidates
audit-canonical-candidates
promote-canonical-rebuild
audit-canonical-formal
```

代码级要求：

1. plan 固定 `30/60/90/120m`、QFQ 物理 source 日期集合、source identity、目标 pre-image、
   schema 和 `plan_hash`；frontier 从实际 QFQ 与注册 expected dates 交集取得，不硬编码日期。
2. candidate 固定写入
   `/Volumes/datasource/data_lake_staging/cn_a_minute_gold_p12_nineturn/<plan_hash>/`，目录镜像正式
   `freq/trade_date/part-000.parquet` 布局。
3. 仍按 `freq + year` 计算。第一年从空 seed 开始；后续年份只消费本轮 candidate 生成的最多
   4 根 source context 和 1 条末尾方向/计数 seed，禁止读取当前正式九转作为 seed。
4. 现有 scoped rebuild 保持少量代码/日期用途。本次禁止给它传全市场代码和全历史日期，因为
   它会为整个频率建立全历史临时表，并按分区复制旧目标，不符合 candidate-first 和性能门禁。
5. 全频 candidate 完整后才 audit；audit 通过后才 promote。promote 前重新验证 source
   fingerprint、candidate hash 和目标 pre-image，任一变化 fail closed。
6. promote 按单分区 `os.replace()`，每个完成分区写 checkpoint；中断只允许在同一 plan 下续跑。
7. 不删除旧 Dagster event，不运行普通 daily job，不改变现有 asset/check/job/sensor 名称。

### 15.3 P7R 审计与事件

审计只做统计和固定样本，每个独立动作不得超过 5 分钟：

1. source/output 日期、row count、key 集合一致，主键唯一、schema exact。
2. `close_qfq` 对当前 QFQ 的绝对误差不超过 `1e-7`。
3. 30m/60m 独立 09:30 行为 0；90m/120m 首根为 11:00/11:30；四频最后一根均为 15:00，
   15:00 后行数为 0。
4. SH/SZ/BJ、跨年、停牌恢复、退市边界和最新日期用字面 fixture 抽查递推连续性。
5. 已知 30m/60m extra key 和 90m/120m stale price mismatch 全部归零。

Lake 验收后单独执行 runless event refresh：

1. 四个资产全部实际历史分区追加本轮 materialization，metadata 带 `plan_hash/revision`。
2. 只对最近 20 个 `cn_a_stock_mins_silver_trade_days` 追加现有 integrity check。
3. 新 check 必须绑定本轮同分区最新 materialization；旧 event 保留。
4. 现有 event planner 需要增加 rebuild revision 语义，不能因旧 materialization 已存在而跳过。

### 15.4 防复发

canonical QFQ 历史重建计划必须从 Definitions dependency graph 枚举直接和递推下游，至少覆盖
QFQ bars、MACD/KDJ、MACD/KDJ state 和 QFQ 九转。每个下游资产族必须显式标记
`rebuild`、`equivalence_audit` 或有代码证据的 `no_impact`；未分类资产阻断 plan。

该门禁放在离线维护计划和静态测试中，不进入日常 sensor 热路径，也不新增九转自动 repair
sensor。未来历史 QFQ 改写仍须走显式、有界、可审计的离线重建。

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

同时在 `test_stk_mins_lake_readiness.py` 锁定频度参数化内核：旧七频度公开 helper 结果不变；九转专用入口只返回 30/60/90/120m，任一所需频度失败仍 fail closed，1/5/15m 状态不影响九转门禁。性能测试使用 5 日容量样本，四频度完整语义必须小于 10 秒。

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

P7R 追加覆盖：

1. candidate promote 前正式文件字节不变。
2. existing stale target 不得被错误当作 reusable target。
3. 四频 candidate 只使用本轮 seed，禁止读取正式九转 seed。
4. source、candidate 或 target pre-image 漂移时禁止 promote。
5. promote 中断后同 plan checkpoint 可续跑，跨 plan checkpoint 被拒绝。
6. 30m/60m 无 09:30，90m/120m price 与当前 QFQ 在 `1e-7` 内一致。
7. event refresh 对全历史写新 materialization、只对最近 20 日写 check，并绑定本轮 materialization。

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
12. 九转分钟 sensor/readiness 禁止直接调用默认七频度 `batch_gold_stk_mins_qfq_lake_readiness(...)`；必须调用固定 30/60/90/120m 的专用入口。
13. 现有七频度公开 helper 的签名、默认频度集合和既有消费者不得因本专项改变。
14. canonical QFQ rebuild 下游清单必须覆盖 `gold_stk_mins_qfq_nineturn`；dependency graph 出现
    未分类 QFQ 下游时静态门禁失败。

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

### 18.1 P0 实际结果

P0 于 2026-08-08 完成，报告：

```text
/private/tmp/qfq_nineturn_p0_profile_20260808_102030.json
```

报告 `decision=pass`、`stop_reasons=[]`，没有 Lake、Dagster event、动态分区或 prod 写入。临时 Parquet 只写入 `/private/tmp`，测量完成后已删除。

历史真实基线：

| Asset | Source 文件 | Source 行数 | 实际日期 | 历史代码 | Source 字节 |
| --- | ---: | ---: | ---: | ---: | ---: |
| daily | 3,063 | 11,622,020 | 3,063 | 5,553 | 819,518,029 |
| 30m | 52,881 | 104,576,189 | 3,063 | 5,553 | 3,755,888,912 |
| 60m | 52,876 | 58,245,695 | 3,063 | 5,553 | 2,380,613,616 |
| 90m | 52,881 | 34,804,311 | 3,063 | 5,553 | 1,582,122,815 |
| 120m | 52,876 | 23,223,508 | 3,063 | 5,553 | 1,160,259,185 |

五个频度范围均为 `2014-01-02` 至 `2026-08-07`，空 key 为 0。目标预计 15,315 个文件、232,471,723 行、985,229,462 字节；按最新样本压缩比给出的正负 20% 区间为 788,183,569 至 1,182,275,354 字节。Lake 可用空间约 2.53 TB，不构成阻断。

最新日 `2026-08-07` 行数为 daily 5,535、30m 49,815、60m 27,675、90m 16,605、120m 11,070；公式原型输出与 source key 一一对应，五个 check 原型全部通过。

| 热路径 | 预算 | P0 实测 | 结果 |
| --- | ---: | ---: | --- |
| 日线增量公式 + 临时写入 | 15 s | 13.7 ms | 通过 |
| 四分钟增量公式 + 临时写入 | 30 s | 2.459 s | 通过 |
| 最新日五个 checks | 10 s | 1.111 s | 通过 |
| 10 日 daily 目标 readiness | 3 s | 18.6 ms | 通过 |
| 5 日四分钟目标 readiness | 10 s | 1.152 s | 通过 |
| 5 日四频度上游 QFQ readiness | 10 s | 6.309 s | 通过 |

增量公式测量使用最近 5 个交易日的有界上下文，目的是验证日常文件打开、窗口计算和 Parquet 写入形状，不把临时样本的 signal count 当作公式正确性证据。公式正确性由 P1 受保护金样本承担。

### 18.2 P1 实际结果

P1 已完成以下代码边界：

1. `run_contracts/qfq_nineturn.py` 集中定义公式、频度、窗口、fallback 上限和不可变写入结果；没有新增环境变量、Settings、resource 或 Dagster config。
2. `asset_column_schemas.py` 新增日线与分钟九转 schema；`paths.py` 新增正式目标与同卷 staging helper，分钟路径只接受 30/60/90/120m。
3. `qfq_nineturn.py` 实现全历史与目标分区两套 set-based SQL。目标分区入口支持上一分区种子、真新股从 0 开始、显式老股票 code-scoped fallback，并在 fallback 超过 500 个代码时 fail closed。
4. 通用 writer 通过 `DuckDBResource` 写 staging，校验 schema、主键、分区日期、频度和值域；再复核由相对路径、文件大小和纳秒 mtime 组成的 source fingerprint，只有前后一致时才原子替换目标。
5. 受保护金样本用人工字面 expected 锁定少于 5 根、上涨/下跌 1 至 11、相等与方向切换重置、跨年和停牌间隔、四个分钟频度、正比例缩放、上一分区种子、真新股和老股票 fallback。

本阶段没有新增 asset、check、job、sensor、catalog 或 readiness，没有访问正式 Lake、Dagster instance、prod DB 或 dynamic partitions。聚焦测试与全仓静态门禁共 110 个用例通过；新文件 `ruff check` 通过。Definitions 治理测试留到 P2 新资产和 catalog 同时落地后执行。

### 18.3 P2 实际结果

P2 已完成以下 Definition 与热路径边界：

1. `assets/qfq_nineturn.py` 定义一个日线资产和四个分钟资产，沿用已冻结的交易日分区、上游依赖和分钟 writer pool；运行时通过 P1 的 source plan 选择有界正常输入，只有缺少有效种子的老代码才进入 code-scoped fallback。
2. `qfq_nineturn_integrity.py` 提供 formula-free 共享审计，固定验证 file contract、partition alignment、key integrity、value domain 和 source key coverage；`checks/qfq_nineturn_checks.py` 只生成每资产一条聚合 blocking check，不调用九转公式。
3. `qfq_nineturn_lake_readiness.py` 复用同一审计语义。日线窗口最多 10 个交易日，分钟窗口最多 5 个交易日；源文件按频度一次预加载且只投影身份字段，不逐日重复读取完整价格列。
4. `stk_mins_lake_readiness.py` 的内部 QFQ batch 内核支持显式频度集合；原公开七频度 helper 的签名和行为不变，新专用入口只检查 30/60/90/120m，因此 1/5/15m 的状态不会误阻断本资产族。
5. catalog 新增五条 derived Gold 记录、两种 trade-date partition model 和中文名；blocking check 名称与 Definition 一一对应。没有新增 job、sensor、cursor、resource、配置项或 Dagster 状态实体。

验证结果：九转资产、check、readiness、source plan、公式金样本、writer、现有 QFQ readiness 和静态门禁共 141 个用例通过。全局 `test_asset_governance_contracts` 仍有 4 项失败，差异来自同一工作区中另一个尚未收敛的指数分钟线/主要指数分钟线专项：catalog 已包含 26 个相关资产，但测试的 active-definition 清单尚未接入；九转五个资产已正确纳入清单且未出现在差异中。本专项未越界修改该专项。

P2 没有访问正式 Lake、Dagster instance、prod DB 或 dynamic partitions，也没有运行 job、sensor、materialize、backfill 或 runless event。

### 18.4 P3 实际结果

P3 已完成以下运行入口与治理边界：

1. 新增两个纯 asset-selection job：日线 job 只选择日线九转资产与聚合 check；分钟 job 只选择四个分钟九转资产与 checks，并使用 in-process executor。job 文件没有 SQL、path 或 writer。
2. 日线 sensor 固定读取最近 10 个股票交易日，按注册缺口、目标 readiness、同日普通 QFQ、必要 factor repair 和上一九转分区顺序 fail closed；无需 repair 时不会等待一个本来就不存在的 repair event。
3. 分钟 sensor 固定读取最近 5 个分钟 Silver 交易日，selected date 的上游只调用 30/60/90/120m 专用 QFQ readiness，再等待同日 factor repair 和上一九转分区；没有退回七频度扫描。
4. 两个 sensor 均默认 `STOPPED`、最短间隔 600 秒、每 tick 最多一个 `RunRequest`，run key 由统一 builder 生成。LLD 没有冻结额外钟点，因此 P3 不擅自增加固定时刻；正式运行窗口由已冻结的注册分区、上游 QFQ、factor repair 和上一分区门禁共同确定。
5. cursor 使用 v1 模板，只保留目标、阻断组件、短中文摘要、下一步、有界 frontier 和必要计数；普通 request/skip 小于 2KB，不包含完整 readiness、路径/code 列表、factor repair metadata 或报告型 `to_cursor_details()`。
6. topology 与 run-contract 治理文档已登记五个资产、两个 job、两个 sensor、分类 tags、run request/run key、cursor 和默认停止边界。

P3 聚焦 job/sensor/静态门禁新增 19 个用例；与 P1/P2 九转用例合并验证共 160 个用例通过。新改 Python 文件 `ruff check` 通过。全局 asset governance 的既有外部阻断仍来自同一工作区的指数分钟线/主要指数分钟线专项，本阶段未越界修改。

P3 没有访问正式 Lake、Dagster instance、prod DB 或 dynamic partitions，也没有运行 job、sensor、materialize、backfill、runless event 或 `dg check defs`。

### 18.5 P4 实际结果

P4 已完成四个非 active 离线模块：历史 plan/build、scoped rebuild plan/apply、runless event plan/report 及对应 CLI。它们不注册 asset、check、job、sensor、resource 或动态分区；默认路径只写 `/private/tmp` 报告，所有正式写入口都要求显式 `--apply`、reviewed plan path 和 fingerprint。

历史 build 没有按年份反复重扫累计历史。每个 `asset/freq/year` 批次只对当年 source 做一次九转计算，并携带每个代码最多 4 根 source bar 和 1 条方向/计数种子；因此跨年序列不会归零，附加状态固定为每个代码最多 5 行，不随历史年份增长。每个年度先生成完整 staging、验证 source/output key、schema、日期、频度和主键，再逐分区原子 promote；已有且逐行一致的目标可幂等复用。

scoped rebuild 必须先生成包含代码集合、资产/频度、日期范围、目标文件身份和完整 source plan fingerprint 的专用只读计划；apply 从完整代码历史计算，只替换批准日期内批准代码，保留其它代码行，并把原文件备份到同卷 quarantine。runless event 工具只计划全部物理分区的 materialization 和每资产最近 20 日的聚合 check，已有失败且绑定当前 materialization 的 check 会阻断 apply。

P4 新增 16 个 history/events/governance/performance 用例；与 P1-P3 相关用例及全仓静态门禁合并运行 156 个用例全部通过，`ruff check` 通过。测试只使用临时 Lake 和 ephemeral Dagster instance；没有读取或写入正式 Lake、正式 Dagster DB、prod、动态分区，也没有运行 `dg check defs`。

### 18.6 P5 实际结果

P5 已执行本地完整门禁、Definitions 加载验证和正式环境只读 preflight：

1. 九转资产族与全仓静态门禁共 156 个用例全部通过；P4 相关文件 `ruff check` 和 `git diff --check` 通过。
2. `uv run dg check defs` 通过，组件 YAML 与全部 Definitions 均成功加载。五个资产、五个 check、两个 job 和两个 sensor 可由现有 `load_from_defs_folder` 正常发现，无需手工 Definitions 清单。
3. 正式历史只读 plan 为 `/private/tmp/qfq_nineturn_history_plan_20260808_115819.json`，fingerprint 为 `28ff31a548e0a555afefaca33a307e652c7da8ff76550598b15485ea913af4dc`。实际规模为 5 个资产、65 个年度批次、214,577 个源文件、232,471,723 行、9,698,402,557 bytes；预计生成 15,315 个目标文件、232,471,723 行，估算目标与 staging 各约 1,162,358,615 bytes。源端空 key、重复 key、年份错位、频度错位均为 0，已有目标文件为 0；聚合只读扫描耗时 66.508 秒，历史重扫倍数为 1。
4. 正式 Dagster instance 只读报告为 `/private/tmp/qfq_nineturn_p5_preflight_20260808_120003.json`。日线和四个分钟资产各有 3,063 个源交易日，范围均为 `2014-01-02` 至 `2026-08-07`；`cn_a_stock_trade_days` 与 `cn_a_stock_mins_silver_trade_days` 均完整覆盖对应日期，注册缺口为 0。五个新资产均无既有 materialization/check，两个 job 无活动 run，两个 sensor 无 instance state、未运行；最终 `should_stop=false`。
5. 额外抽查全仓 asset governance 的五条相关门禁时，两条通过，三条仍被同一工作区中尚未收口的 `index_mins/major_index_mins` catalog 与 active-definition 清单差异阻断（catalog 94、测试 active 清单 68，以及对应 blocking-check 映射差异）。九转资产已经进入实际清单且 `dg check defs` 通过，本专项不越界修改该外部专项；该结果不改变上述九转 P5 验收事实。

P5 全程只读取正式 Lake 与 Dagster instance，并仅向 `/private/tmp` 写报告；没有写 Lake、Dagster event/check、run、cursor、动态分区或 prod，也没有启停 sensor 或提交 job。

### 18.7 P6A 正式写入前样本门禁

P6A 已完成正式历史源只读复核和只写 `/private/tmp` 的真实年度样本，没有进入正式 Lake 写入：

1. 新鲜只读计划为 `/private/tmp/qfq_nineturn_history_plan_20260808_122656.json`，fingerprint 仍为 `28ff31a548e0a555afefaca33a307e652c7da8ff76550598b15485ea913af4dc`，`should_stop=false`。计划仍为 5 个资产、65 个年度批次、214,577 个源文件、232,471,723 行、15,315 个目标文件，已有正式目标文件为 0；只读扫描耗时 112.480 秒。
2. 第一次正式源样本发现 DuckDB 对真实年度数据执行 `PARTITION_BY (trade_date)` 时，同一交易日可能产生多个 Parquet shard。旧 helper 把“每个日期只能有一个 staging shard”错误当成契约，因此样本在正式写入前主动停止；正式 Lake 未被写入。
3. history helper 已改为接受同日一个或多个 staging shard，并使用 DuckDB 显式字段投影和稳定主键排序，将它们列式合并为唯一 `part-000.parquet`。合并仍发生在 staging 内，输出继续执行 schema、日期、频度、空 key、重复 key 和 source/output key 校验；不使用 Python 逐行合并，也不改变年度扫描、正式目标路径或原子 promote 边界。
4. 修复后的正式源样本报告为 `/private/tmp/qfq_nineturn_p6_sample_20260808_123444.json`。样本覆盖五个资产各自的 2014 年批次，共生成 1,225 个临时目标文件、10,463,797 行、86,156,316 bytes；五批 source/output 行数逐批一致，`should_stop=false`，耗时 81.091 秒。真实样本约为 8.23 bytes/row，据此校准的全历史输出约 1.78 GiB，staging 约同量级；即便两者同时存在，也远低于当前约 2.3 TiB 可用空间。
5. 新增多 shard 同日合并回归测试后，九转资产族、bootstrap、governance、性能和静态门禁共 157 个用例全部通过，相关文件 `ruff check` 与 `git diff --check` 通过。
6. 两个九转 job 无活动 run，两个 sensor 未运行。P6A 没有写正式 Lake、Dagster event/check、动态分区或 prod，也没有启停 sensor。

P6 下一写入边界为 P6B 正式历史 Lake build。必须单独批准后，才可使用上述新鲜 plan 和 fingerprint 写入 15,315 个正式目标文件；完成聚合文件审计前不得进入 runless event 补录。

### 18.8 P6B 首次执行停止与恢复口径

P6B 首次正式 build 在 compact state 校验处停止，没有进入 runless event 或 sensor 阶段：

1. 第一次 build 完成 13 个日线年度批次和 30m 的 2014 年批次后，在 30m 2015 年批次触发 `Compact context exceeded its fixed row bound`。只读审计确认正式 Lake 当时新增了完整日线 3,063 个分区和 30m 的 2014-2015 年 489 个分区，共 3,552 个文件；其它分钟频度为 0。
2. 根因不是阈值过小，而是旧 helper 只为当年出现过的代码生成下一年度 seed，却为历史出现过的代码保留 4 根 context。整年无数据的代码会丢 seed，若以后重新出现，其九转连续计数可能错误。
3. helper 已改为让当年无数据的代码继续携带上一年度 seed，并增加 context/seed 代码集合、seed 唯一性和每代码 context 行数校验。compact state 现在必须在当前年度正式分区 promote 前生成并通过契约，state 失败不会再留下当前年度半批文件。
4. 修复后的跨年正式源样本为 `/private/tmp/qfq_nineturn_p6_sample_20260808_125040.json`，覆盖五个资产各自连续两个年度，共 10 个批次、2,445 个临时分区、21,025,279 行，`should_stop=false`。完整回归增至 158 个用例并全部通过。
5. 新鲜恢复计划 `/private/tmp/qfq_nineturn_history_plan_20260808_125226.json` 确认 65 个批次的源文件、行数、字节、hash、日期和代码事实与原计划完全一致，唯一变化是识别出上述 3,552 个已有目标，`should_stop=false`。
6. 恢复 build 在复用 `gold_stock_daily_qfq_nineturn[2016-01-11]` 时发现旧输出与修正后的跨年结果不一致并停止。这证明受旧 seed 语义影响的部分文件不能继续复用。五个新资产仍无 materialization/check，两个 job 无活动 run，两个 sensor 未启用。

恢复必须先把本轮新建的 `gold/indicator/stock_daily_qfq_nineturn` 与 `gold/indicator/stk_mins_qfq_nineturn` 两个根目录整体原子移动到同卷 quarantine，保留完整回滚证据，再生成 existing target 为 0 的新鲜计划并从零重建。禁止直接删除、就地覆盖冲突文件或继续补剩余分区；quarantine apply 属于 P6B 内新增的明确正式 Lake 治理边界，需单独确认。

P6B 恢复与最终结果已完成：

1. 3,552 个失败输出、185,042,243 bytes 已按 manifest fingerprint `a7ad55fbe81868daa1fd28c1ecc3cc8478b598a80bb4eb436bca989dab62d951` 原子移动到 `/Volumes/datasource/data_lake/_quarantine/qfq_nineturn_p6b_failed_20260808_130229`。计划与执行报告分别为 `/private/tmp/qfq_nineturn_p6b_quarantine_plan_20260808_130229.json` 和 `/private/tmp/qfq_nineturn_p6b_quarantine_apply_20260808_130303.json`。
2. 隔离后的新鲜计划为 `/private/tmp/qfq_nineturn_history_plan_20260808_130414.json`，existing target 恢复为 0，源端 65 个批次事实与原计划完全一致，fingerprint 恢复为 `28ff31a548e0a555afefaca33a307e652c7da8ff76550598b15485ea913af4dc`。
3. 修正后的正式 build run id 为 `75dd720b-bf27-4550-b0ef-092951bdbf37`，完成 65 个年度批次、15,315 个目标文件、232,471,723 行，零复用，耗时 510.000 秒。正式输出实际占用 1,782,333,668 bytes，约 1.66 GiB。
4. 最终聚合审计为 `/private/tmp/qfq_nineturn_history_final_audit_20260808_131457.json`，`should_stop=false`。五个资产各有 3,063 个分区；日线、30m、60m、90m、120m 行数分别为 11,622,020、104,576,189、58,245,695、34,804,311、23,223,508，逐资产 source/output 行数一致。缺文件、schema 错误、重复 key、空 key、分区日期错位和频度错位均为 0。
5. P6B 没有写 Dagster materialization/check、run、cursor 或 dynamic partitions，也没有启停 sensor。下一阶段只能先生成 P6C runless event 只读计划；event apply 仍需单独批准。

### 18.9 P6C runless event 只读计划

P6C 只读计划已生成，正式 Dagster DB 尚未写入：

1. 计划报告为 `/private/tmp/qfq_nineturn_events_plan_20260808_131827.json`，候选 manifest 为 `/private/tmp/qfq_nineturn_events_manifest_20260808_131827.jsonl`。
2. 计划 fingerprint 为 `7c1caba91c5dee35f30111a921a06a2c4c3943fc9fcb4895f287f700674633bc`，物理文件 fingerprint 为 `0e0068aa85833c5ef55b1839192a70f2447a02c5d053ece7984e13200dd14848`，并绑定 P6B 最终审计 SHA-256。
3. 候选为全历史 15,315 条 materialization，以及五个资产各最近 20 个交易日的一条聚合 integrity check，共 100 条 check event；总计 15,415 条。没有历史全量 check，也不新增 check 名称。
4. 现有 materialization/check 为 0，`should_stop=false`。event apply、post-audit 与 sensor 启用仍是后续独立边界。

P6C 正式 apply 已完成：

1. event batch id 为 `4ebe7f19-8e8f-4a06-aaa7-7e979bf19bcd`，实际追加 15,315 条 materialization 和 100 条最近窗口聚合 check，共 15,415 条 event，耗时 370.379 秒。
2. apply 后计划 `/private/tmp/qfq_nineturn_events_plan_20260808_133743.json` 的 materialization/check/event 候选均为 0，`should_stop=false`；所有 check 均绑定本轮对应分区 materialization。
3. P6C 没有运行 job、写 Lake、修改 dynamic partitions 或启用 sensor。

### 18.10 P6D 初步只读 readiness 验收

P6D 初步报告为 `/private/tmp/qfq_nineturn_p6d_readiness_audit_20260808_134036.json`：

1. 五个资产的 expected/materialized partition 均为 3,063，missing/extra 均为 0；event post-plan 候选为 0。
2. 日线最近 10 个交易日全部 ready，耗时 55.46 ms。
3. 分钟最近 5 个交易日的 30/60/90/120m 全部 ready，但耗时 11,076.53 ms，超过已冻结的 `<10s` sensor readiness 性能门禁。
4. 两个 job 无活动 run，两个 sensor 均无 instance state、未运行。数据和状态正确，但该次分钟 readiness 性能未通过，因此先停止 sensor 启用。

独立重复测量确认该问题不是单次冷缓存波动。优化前五次独立 DuckDB 连接耗时为 `11,132.56 / 9,353.20 / 9,356.90 / 10,107.61 / 10,093.88 ms`，其中三次超过 10 秒，均值为 10,008.83 ms。

代码级 profiling 冻结了真实读取模型：最近 5 日四频度共有 20 个目标文件；每个频度需要枚举 5,553 个按股票年度保存的普通 QFQ 源文件，共 22,212 个唯一源文件。旧实现对同一年度目录按日期重复枚举，并把源定义为 lazy temp view，导致后续 20 次逐日期/频度 integrity audit 重复打开同一批年度文件。实测路径准备约 2.42 秒，20 次 audit 合计约 8.60 秒。

P6D 只优化读取模型，不改变 integrity 语义：

1. 分钟源路径改为每个频度、每个年度只枚举一次；跨年窗口按 distinct year 处理，日线仍按实际日期文件处理。
2. 每个频度一次读取年度 Parquet，只投影 `ts_code/freq/trade_date/trade_time`，并把窗口内日期物化为 DuckDB 临时表。
3. 目标文件 schema、分区/频度、重复键、空键、值域和 source/output 双向 identity coverage 继续调用同一 `audit_qfq_nineturn_integrity(...)`，没有删减或降级 check。
4. 不新增 Lake 文件、state/readiness asset、数据库表、cache manifest、cursor 字段或 Dagster event。

优化后的正式 Lake 五次独立连接重测为 `4,746.74 / 3,265.10 / 3,530.56 / 3,021.27 / 3,304.18 ms`；最小值 3,021.27 ms，中位数 3,304.18 ms，最大值 4,746.74 ms，均值 3,573.57 ms，五次均低于 10 秒且最近 5 日全部 ready。P6D readiness 性能门禁已通过。这里的“sensor 未启用”是 P6D 当时的历史状态；2026-08-15 正式实例复核显示日线与分钟 sensor 均为持久化 `RUNNING`。日线最近 tick 仍被既有目标聚合 check 阻断；分钟去价格专项完成后，分钟 sensor 最近 tick 已自然评估最近 5 日全部 ready、0 run。周六没有新增交易日，下一交易日新增分区只作为运维观察。

### 18.11 P7R Canonical Bars 执行前审计与过程阻断

2026-08-14 已完成代码链路和正式 Lake 的只读审计，结论为：

1. 四个分钟九转 asset 的 Definition 依赖、source planner 和 SQL 都读取对应当前
   `gold_stk_mins_qfq_{30,60,90,120}m` 文件；设计方向没有读错层。
2. 当前分钟九转历史文件是在 QFQ canonical rebuild 之前生成的。普通日常 sensor 只选择新增
   first-not-ready 日期，不会对已 materialized 的历史日期做 source-version reconciliation。
3. 最新样本存在 30m/60m 旧 09:30 key 和 90m/120m stale `close_qfq`，证明 P7/P8 下游清单
   实际漏掉了九转，不是 UI 或 event 展示误差。
4. 现有 scoped rebuild 适合少量代码/日期，不适合四频全市场全历史；直接复用会扩大临时表、
   旧文件复制和执行时间，不能进入正式写入。
5. 上述结论是 P7R 正式开发前的冻结基线；当时尚无 canonical candidate/promote 模式，
   Lake 与 Dagster event 也尚未更新。最终执行结果见 18.12。

2026-08-14 执行更新：P7R-A candidate/plan/promote 与强制 event refresh 能力已经完成本地测试，
但首轮 30m candidate 审计在 promote 前发现 `002348.SZ`、`688790.SH` 的 12 个历史交易日
存在上游缺口或 stale QFQ30 09:30 key。根因是这些日期原生 5m 源全空，而完整 1m 源可用；旧 P7 source-driven
manifest 没有覆盖不在当前 source 清单中的 stale stock-year 文件。因此该执行阶段的状态是“正式九转
Lake 写入 0、旧 plan 作废、bounded 上游修复执行中”，不能把该异常当作九转公式失败，也不能
绕过后继续 60m/90m/120m。

前置修复固定为：只对目标粗周期整日缺失且 1m 完整 241 根的 code-day 启用 Silver set-based
fallback；完成 12 日 Silver5、受影响 QFQ15/30 和两只股票的 MACD/KDJ/state bounded 修复
后，再重新生成四频九转 plan。已有原生粗周期行永远优先，fallback 不覆盖、不混合原生行；
所有 candidate 继续位于正式 staging 卷，正式 promote 前必须验证 pre-image、candidate hash 与
source fingerprint。

### 18.12 P7R 正式完成结果

P7R 已于 2026-08-14 完成，不再处于“bounded 上游修复执行中”状态：

1. 两轮 bounded source prerequisite 均完成。第一轮补齐两只股票 12 日 Silver5，并重建对应
   QFQ15/30 与 15/30m MACD/KDJ/state；第二轮补齐 7 只股票 3,790 个 code-date 的 Silver30，
   共新增 34,110 行，既有行变化为 0。
2. QFQ60/90 的 32 个受影响 stock-year 已重建并提升；QFQ120 的 16 个候选与正式文件逐行差异
   为 0，因此保持正式文件不变。7 只股票的 60/90m MACD/KDJ/state 已从历史覆盖起点重建，
   QFQ/indicator key 双向缺口、指标 09:30 和 state 重复 key 均为 0。
3. 最终 canonical 九转 plan hash 为
   `bc95ab53df6141894386a132fdea356c55a57156d9c77b6984623ef3c86189b8`，覆盖
   `2014-01-02..2026-08-13` 共 3,067 个交易日。30/60/90/120m 均按
   candidate -> audit -> promote -> formal audit 完成。
4. 四频最终行数为 93,000,216、46,509,532、34,882,149、23,267,820；每个资产 3,067 个
   分区。最终聚合报告为
   `/Volumes/datasource/data_lake_staging/cn_a_minute_gold_p12_nineturn/bc95ab53df6141894386a132fdea356c55a57156d9c77b6984623ef3c86189b8/qfq_nineturn_history_final_audit_20260814_022612.json`，
   `should_stop=false`，缺文件、schema、重复/空 key、日期/频度错位均为 0。
5. 强制事件刷新 revision 为 `canonical-bars-p12-bc95ab53`，event plan fingerprint 为
   `3023e820794752306b48b3c5eb4d04b3d25f0603547fa12707e4b2987c1b790b`。批次
   `e28be5a6-64e1-4eef-8735-a0121049f3cb` 追加 12,268 条全历史 materialization 和 80 条最近
   20 日 latest-bound check，post-plan 候选为 0；没有创建 run 或修改 dynamic partitions。
6. 所有 candidate audit 单次低于 5 分钟，构建峰值 RSS 低于 20GiB。普通九转
   asset/check/job/sensor、公式版本、分区定义和日常 run key 均未改变。

P7R-A/B/C 已完成；P7R-D 的代码门禁已落地。以上只记录 2026-08-14 旧九列 schema 的历史执行结果：它证明 canonical bar 对齐和公式结果，但不再证明当前最终字段合同。2026-08-15 去价格专项随后已独立完成 S2～S5，包括八列 candidate、正式原子替换和四个分钟资产的 event refresh；当前结果见第 21 节。

## 19. 建议验证命令

开发后本地测试：

```bash
cd /Users/congming/github/goldenshare/lake_console/orchestrator
uv run python -m unittest \
  tests.test_qfq_nineturn_formula_golden \
  tests.test_qfq_nineturn_writer \
  tests.test_qfq_nineturn_checks \
  tests.test_qfq_nineturn_readiness \
  tests.test_qfq_nineturn_source_plan \
  tests.test_qfq_nineturn_assets \
  tests.test_qfq_nineturn_jobs \
  tests.test_stock_daily_qfq_nineturn_sensor \
  tests.test_stk_mins_qfq_nineturn_sensor \
  tests.test_qfq_nineturn_history \
  tests.test_qfq_nineturn_events \
  tests.test_qfq_nineturn_governance \
  tests.test_qfq_nineturn_performance \
  tests.test_run_contract_static_gates
git diff --check
```

本段命令与审批描述记录原 P6 历史边界。当前去价格迁移以 S0～S5 为唯一执行顺序；S2 仍只读，S3/S4/S5 只能在前一阶段退出条件通过后依次进入。

## 20. 实施顺序

1. P0 只读 profiling。已完成。
2. P1 contract、schema、path、公式金样本、calculator 和原子 writer 内核。已完成。
3. P2 assets、checks、catalog、readiness。已完成。
4. P3 jobs、sensors、cursor，并同步 topology 与 run-contract 两份治理文档。已完成。
5. P4 bootstrap/rebuild/events 工具。已完成代码与本地临时环境验证。
6. P5 本地全量测试、`dg check defs` 与正式只读 preflight。已完成。
7. P6A 正式源只读复核和 `/private/tmp` 年度样本。已完成。
8. P6B 经批准的历史 Lake 写入和聚合文件审计。已完成。
9. P6C 经批准的 runless events。已完成。
10. P6D readiness 性能收口、日常 sensor 启用与最近窗口自然评估已完成；下一交易日新增分区继续作为运维观察。
11. P7R-A canonical rebuild candidate/plan/promote 能力开发和临时 Lake 测试。已完成。
12. P7R-B 停止相关 writer，冻结 frontier，按 30m/60m/90m/120m 完成正式全历史重建和
    每次小于 5 分钟的统计/抽样审计。已完成。
13. P7R-C 全历史 materialization refresh、最近 20 日 latest-bound check refresh 和 partition
    归属验收。已完成。
14. P7R-D 下游覆盖静态门禁、分钟九转 sensor 恢复和最近窗口自然评估已完成；下一交易日新增分区继续作为运维观察。
15. S0 去价格文档与合同冻结。已完成。
16. S1 四个分钟资产、check、Reader 与历史工具改为八列无价格合同；日线无漂移。已完成，Definitions、102 个 Orchestrator 专项用例、24 个 Foundation/API 用例与专项静态门禁通过。canonical plan/build/audit 专用 DuckDB 固定 2GB/1线程、按年度释放连接，并以 16GiB 进程真实峰值 RSS 自动 fail closed；首次 4GB/2线程 S2 计划实测约 6.40GiB，后续 2GB/1线程试跑降至约 4.42GiB，两份试跑计划均因合同继续修订而作废。
17. S2 重新生成正式只读计划，冻结 ready 范围、文件/行数/空间、批次、内存、指纹与事件上限。已完成。
18. S3 停止分钟 sensor/Reader，在 `/Volumes/datasource/data_lake_staging` 生成并审计 candidate，通过后逐文件原子替换正式分钟九转文件。已完成。
19. S4 只刷新四个分钟资产全部 materialization 和每资产最近 20 日 check，日线事件不变。已完成。
20. S5 恢复分钟 sensor/Reader，完成 latest state、readiness、API、性能/内存与自然评估。已完成；2026-08-15 为周六，下一交易日新增分区继续作为运维观察项。

每一阶段只在前一阶段验收全绿后进入；P0 性能门禁不通过时不得靠增加 timeout 继续。

## 21. 2026-08-15 正式执行结果

1. S2 正式计划 hash 为 `01d63b246a602f7c0b511beee19695bb85d07159c1ad815d5573c31e68d03757`，历史 fingerprint 为 `5112fcc3656a9ea1a0d58294eba9f4adae54ba198b20a5a831f595db1dd93533`。范围为 2014-01-02～2026-08-14，共 3,068 个交易日、52 个年度批次、12,272 个目标文件、211,583 个源文件和 197,753,897 行。
2. S3 按 30/60/90/120 顺序生成并审计四频 candidate；行数分别为 93,044,536、46,531,692、34,898,769、23,278,900。四份 candidate manifest 均 `ready=true`，失败批次为 0；12,268 个旧目标 preimage 未变化，4 个新目标为空位后才开始提升。逐文件 `os.replace()` 后，正式文件缺失、hash 不一致和 candidate 残留均为 0；最终聚合审计的 schema、重复键、空键、分区、频度与值域失败均为 0。
3. candidate build/audit 使用 DuckDB 2GB/1线程并按年度释放连接。候选阶段单进程峰值不高于 5.74GB；提升前总门禁峰值 10.61GB，均低于 16GiB 硬门禁。正式聚合审计峰值 4.84GB。
4. S4 事件计划 fingerprint 为 `2140016f3d4e29384bb78dfd01838c389a5907e132059fa3e30d22dd9affa7f5`。工具新增显式 asset selection 并进入计划/物理指纹，正式计划只含四个分钟资产：12,272 条 materialization、80 条最近 20 日 check，日线候选 0。实际写入数量一致，post-plan 候选为 0；没有删除历史 event 或创建 Dagster run。
5. S5 对 `000001.SZ` 四频各执行 10 次正式 Reader，全部逐根匹配且返回字段无价格；观测 P95 为 150/32/29/25ms。最近 5 日 readiness 检查 20/20 文件、470,832 行，失败行 0，耗时 2.11 秒。Orchestrator 专项 61 项和 16 个子测试、Foundation/API 32 项通过，Definitions 加载成功。

6. reload `orchestrator` code location 后，只恢复正式 `gold_stk_mins_qfq_nineturn_update_job_sensor` origin；当前状态 `RUNNING`，2026-08-15 12:13:01 最近 tick 为 `SKIPPED — 最近 5 个分钟前复权九转分区均已 ready`，run 数 0。周六没有新增交易日，不伪造新分区触发；下一交易日只做自然观察，不改变本次正式数据结论。

## 22. 2026-10-22分钟九转写入修正与补齐LLD（待开发）

### 22.1 本步状态、范围及依据

2026-10-26仅审计当前代码和已有报告、完善原方案与本LLD；未修改Python、运行测试/job、读取正式数据正文或写Lake/数据库。以下均是拟实施细节，不能当成已实现或已通过。开发须先获本方案确认；正式读取/写入仍单独按具体范围批准。

目标仅为`gold_stk_mins_qfq_nineturn_{30,60,90,120}m`在2026-10-22的四个文件。正式根`/Volumes/datasource/data_lake`、候选根`/Volumes/datasource/data_lake_staging`；原job、四个blocking check、八列合同、公式和正式路径不变。既有MACD/QFQ已完成结果保持。不得引入备份、旧Lake、Kopia、独立九转state、Prod写入、新配置、性能样本或自行设置的资源中断阈值。

本轮使用CodeGraph的`codegraph_status/explore/node/callers/impact`，并核验其未完整覆盖的工厂生成资产及测试引用。索引根为仓库根；`_write_qfq_nineturn_partition`生产调用为日线/分钟两个wrapper，分钟writer生产调用仅`assets/qfq_nineturn.py`的工厂资产；`QfqNineturnSourcePlan`仅日线/分钟planner两处构造、对应两支资产读取。未发现该plan的序列化、前端/API消费者。历史bootstrap走独立builder/writer，Reader和checks只读正式路径。该事实决定仅迁移分钟wrapper，不能直接改共享writer而影响日线。

官方API依据通过Context7核对Dagster官方源码/文档：资产通过`context.run`取得run；重执行保留root/parent身份，创建run不等于提交。分钟调用沿用仓库QFQ/MACD已有的`context.run.root_run_id or context.run.run_id`写法，不新增job或改变Dagster执行器。[资产context](https://github.com/dagster-io/dagster/blob/master/docs/docs/guides/build/assets/defining-assets.md)、[重执行run实现](https://github.com/dagster-io/dagster/blob/master/python_modules/dagster/dagster/_core/instance/runs/run_domain.py)。

### 22.2 当前代码事实与必须保留的语义

| 当前实现 | 本次核验结论 |
| --- | --- |
| `assets/qfq_nineturn.py:_previous_registered_trade_date` | 取小于目标日的最大注册日；不是日历验证。22日执行前必须确认它确为21日 |
| `qfq_nineturn.py:plan_gold_stk_mins_qfq_nineturn_source` | 正常两年QFQ、上一九转种子、候选代码历史探查、最终fallback名单；当前planner会直接读历史，不能未经范围批准用它“探一下” |
| `_bounded_candidate_codes` | 先读两年身份/日期字段及种子找候选，另一次目标日count；候选条件为前序不足4根或缺该代码种子 |
| `_fallback_codes_with_history` | 读候选代码各年身份字段，实际至少4根旧历史才列入回算；501个新股候选可能最终0个回算 |
| `_build_qfq_nineturn_partition_select_sql` | 最终fallback最多500，原限制不变；不是历史查询前限制候选数 |
| `_minute_seed_sql` | 读取上一分区各代码最后一根的方向与最大计数；有前序日期但整个文件缺失时现有helper报错，不改为静默空种子 |
| 分钟公式/`nineturn_formula.py` | 先在两年source上做LAG4，再筛目标日；源阶段没有`<=22日`裁剪。新股不足4根输出0，老股票不能从0伪造接续 |
| `build_qfq_nineturn_source_fingerprint` | QFQ相对路径、size、mtime摘要，不读业务正文、不含上一九转。原metadata语义保留；新输入身份另存 |
| 旧共享writer | 开头和finally删除候选，缺逐文件恢复；候选validator没有逐键来源覆盖及`trade_time`跨日校验 |
| `qfq_nineturn_integrity.py:audit_qfq_nineturn_integrity` | 可对指定候选路径做完整合同/分区/键/值域/来源覆盖检查，不计算公式；复用它，不能声称旧validator已覆盖这些内容 |
| sensor与人工job | 因子、QFQ、前序九转ready在sensor中检查，人工job不执行sensor。原job含四资产与四checks、in-process及共用writer pool；四频无固定顺序，不具备整体事务 |

第15节继续适用：只有每代码统一正比例缩放且键/时间不变，旧九转种子才不受QFQ历史修复影响。已完成因子repair及其来源记录可复用，但必须从其实际范围/公式核清是否满足这一条件；不能只凭`SUCCESS`、`ready=true`认定。若发现非等比例历史修正或无法确认条件，先报告并补受影响代码的scoped rebuild方案，不做全历史扫描来猜结论，也不擅自把本轮扩成九转repair。

### 22.3 代码修改清单及内部输入

| 文件/位置 | 具体修改 | 边界 |
| --- | --- | --- |
| `run_contracts/qfq_nineturn.py:QfqNineturnSourcePlan` | 末尾新增`input_file_identities`（默认None），为按路径排序的不可变tuple，每项`(Path, (st_dev, st_ino, st_size, st_mtime_ns, st_ctime_ns))`；另加`history_candidate_codes`（默认空tuple）保存实际探查的候选 | 默认值仅保持日线构造不变；分钟必须填身份，不能由writer晚抓一次stat兜底。候选名单包括没有历史路径的代码，才能发现后续新加入的历史文件。原字段和输出result不变 |
| `qfq_nineturn.py`分钟planner | 正常source及seed在第一次查询前取身份；候选历史在其查询前扩充；每次查询后、返回前复核 | 只增加metadata保护，不改路径选择、日期、公式、fallback条件或500上限。history扩充遇到已记录路径必须核对首次身份，禁止覆盖旧身份 |
| `qfq_nineturn.py`分钟writer | 必须接收完整`source_plan`，转入分钟发布实现 | 日线wrapper仍调用原共享writer；分钟旧参数整体迁移，不能保留可漏传种子的新旧两条分钟路径 |
| `assets/qfq_nineturn.py`分钟工厂 | 传`source_plan`和root run身份 | 日线调用、materialization metadata结构和四资产定义不变 |
| `io/stk_mins_qfq_publication.py` | 允许family=`nineturn`，复用原候选、锁、输入冻结、一次摘要、receipt和原子提升 | 不改qfq/macd_kdj分支行为、阈值、目录、schema或配置；九转频率仍由原normalize函数限制 |
| `paths.py`与引用/测试 | 删除已无生产消费者的`gold_stk_mins_qfq_nineturn_staging_path`及旧分钟路径断言 | 保留正式path helper；日线旧helper不动。不得留一条仍能把分钟候选指向正式Gold的备用函数 |
| 定向测试 | 见22.7逐项迁移和新增 | 不改业务Reader/API、历史CLI、job/sensor/检查名称和选择 |

分钟writer的目标内部签名：

```python
write_gold_stk_mins_qfq_nineturn_partition(
    *, duckdb_resource, lake_root, freq, partition_key, run_id,
    select_sql, source_plan: QfqNineturnSourcePlan,
) -> QfqNineturnPartitionWriteResult
```

这是DG内部调用迁移，已核生产调用一处及writer测试；日线签名不改。`run_id`由分钟asset传root或本次run ID，直接隔离测试传明确身份；不增加环境变量或运营参数。result的`source_file_count/source_fingerprint`仍以原`fingerprint_source_paths`为准，不把种子或只探查未回算的历史混进该字段。

身份记录必须包括实际查询过、最终却未选为fallback的候选历史，因为它参与了“是否需要回算”的判断。无前序交易日时记录明确的None；有前序日期但文件缺失继续报错。正常两年路径集合、各候选代码历史路径集合在结束/提升前重新枚举metadata并核对，防止只检查旧路径而漏掉新加入的输入文件；不枚举其他频率或无关代码正文。stat不是源内容SHA，不能把这项保护说成全历史内容比对。

### 22.4 输入说明、候选目录与写入过程

复用现有publication构造参数：`family='nineturn'`、单freq、`trade_dates=(partition_key,)`、`publication_id=run_id`。现有组件将root、run、scope映射为摘要，实际目录为：

```text
/Volumes/datasource/data_lake_staging/stk_mins_qfq/nineturn/
  root=<root摘要>/freq=<freq>/run_id=<run摘要>/scope=<scope摘要>/
    operation.json
    attempts/<attempt>/nineturn_inputs.parquet
    files/<target摘要>.json
    candidates/<candidate-id>/gold/indicator/stk_mins_qfq_nineturn/
      freq=<freq>/trade_date=2026-10-22/part-000.parquet
```

目录是现有组件的真实规则，不再维护第二个候选path helper。测试使用临时Lake及其同级staging，测试结束两者和DuckDB工作目录都清除；正式失败现场保留，不自动清理候选或operation。

`bind`的`inputs`只传一份**输入说明的SQL**，返回按确定顺序序列化的一条说明：格式版本、候选校验规则版本、公式版本、freq、partition、前序路径或None、正常/fallback路径集合、全部已读文件五字段身份、history_candidate_codes、fallback代码及计数、source_row_count、原八列名称/类型/顺序、完整计算SQL。先将字符串作为SQL字面量安全转义，再由现有bind保存并对这份小文件取摘要。它不是行情副本、资产、状态表或新配置。不能把计算SQL直接放进bind后再COPY计算一遍；也不冻结两年价格明细。

每个频率的正常流程：

1. 接收并核验分钟plan身份完整、freq合法、行数正、fallback名单/数量合法；源文件必须位于约定QFQ路径，种子必须位于对应前序九转正式路径，均为普通文件且路径无符号链接。planner首次取身份前即检查这些边界，writer再次检查并复核所有输入身份/集合，生成原source fingerprint。取得原publication非阻塞文件锁。
2. 用现有`bind`冻结输入说明及唯一正式目标；同一root若已有不一致operation/receipt，拒绝复用，不另建身份躲过冲突。
3. 同连接建立目标日source key临时表，只投影当前年QFQ的`ts_code/freq/trade_date/trade_time`并筛22日/本频；使用原source路径选择helper，不读取价格。保留原始行以检查重复键，不能先DISTINCT掩盖重复。此表只用于候选检查和股票数，不持久化为新数据集。
4. `candidate(target)`返回`(candidate_path, None)`表示需要新建；返回`(None, row_count)`表示已有validated/promoting/promoted结果通过组件恢复核验。两个分支必须显式区分。
5. **新候选分支**：只执行一次原`select_sql`的COPY，复核输入身份；调用现有`audit_qfq_nineturn_integrity(target_path=candidate, source_relation=<临时表>, source_paths=(), partition_key=D, freq=freq)`，要求passed、输出/来源行数均等于plan行数。股票数从目标日键表统计，完整覆盖通过后等同于输出股票数；fallback数量不得超过它。随后调用`validated`，候选fsync、仅一遍SHA并保存记录。分钟以此替代旧私有validator重复检查，日线原validator不变。
6. **已有结果分支**：要求返回行数等于plan行数，当前目标日键表行数及股票数符合plan/fallback约束；输入说明及校验版本必须一致。跳过COPY、候选audit和`validated`，不能对None路径调用检查，也不能重写已提升文件。两分支汇合后再复核全部输入身份/集合，调用现有`promote()`处理原记录：新结果先核同设备、候选/目标身份、无符号链接，记录`promoting`后原子替换、目录fsync、记录`promoted`；已完成者跳过替换。正常同进程不再做第二遍SHA，跨进程恢复的那一遍已由现有组件核验。
7. 两分支均按原结构返回result：目标为正式path，source行数来自plan，output行数来自新候选诊断或恢复返回值，股票数来自目标日键表，fallback数量为原名单长度；source_file_count/fingerprint沿用原口径，observed_columns取已通过完整schema检查所对应的合同列序。恢复不为重建metadata另读一次正式文件。原job继续运行四条正式checks，独立读取正式文件和目标年来源键，不用receipt替代，不重算公式。正常收尾仅核逐文件记录/stat、检查绑定及两sensor状态，不再做全局审计或SHA。

输入说明必须包含本次校验规则的版本，防止以后规则变更时误把旧候选当成已按新规则通过。全量源SHA没有获准，也没有必要为此新增；五字段stat、输入集合及目标/候选摘要各自证明的范围要分别报告。

### 22.5 失败、中断和继续

| 记录/现场 | 处理规则 | 再读取开销 |
| --- | --- | --- |
| 尚未完成COPY、`building` | 保留原部分候选与记录；同输入、原目标未变才能创建新的候选完成该文件 | 重做此freq planner/计算及必要检查，原半文件不作正式结果 |
| 已`validated`未提升 | 原输入说明必须匹配；现有组件重新核一次候选摘要，复用候选，不能再次COPY | planner/目标日键可能重新读；候选一次恢复摘要 |
| `promoting`时进程退出 | 仅按原组件核候选是否仍在、正式文件是否对应原候选；能唯一确认才完成记录 | 对实际保留文件一次恢复摘要；不能只凭“目标存在”宣告成功 |
| 已`promoted`但事件未完成 | 核正式文件身份及摘要，同root返回原结果，重做必要原check/event步骤 | 正式结果一次恢复摘要；不替换文件 |
| 输入、seed、SQL/校验版本、候选、外部目标、receipt冲突或丢失 | 拒绝自动恢复，保留现场并报告 | 不通过新root或删除记录绕过，不做全历史审计补猜 |
| 某一频率/check失败 | 以原Dagster实际执行状态和逐文件记录汇报；已完成其他频率保持 | 不承诺其他独立step已经被阻止、不回滚四频，也不自动重跑 |

恢复仍需检查实际代码版本和从失败执行的step选择，再明确本次额外读写，单独获得必要授权；“预算含一次续跑估计”不等于批准自动续跑。不要修改原资源配置、添加运行时间/空间中断器，或人工给正在正常计算的job发送中断信号。

### 22.6 正常、前检、续跑及收尾开销

已有证据来自[MACD预检](../../reports/datasets_recovery_20261022_20261024/macd_recovery_20261025/preflight.json)、[最终来源身份核验](../../reports/datasets_recovery_20261022_20261024/macd_recovery_20261025/final-control-status.json)及[QFQ完成汇总](../../reports/datasets_recovery_20261022_20261024/qfq_recovery_20261025/summary.json)，本轮未新扫正式文件。

四频两年44,224文件大小记为R=1,654,696,422B（1.541056GiB）；其中2026年Y=753,265,659B（0.701533GiB）。22日总输出94,690行。P=21日四份九转大小；Hc=实际候选代码所有年份的历史文件大小（含与R重合的路径）；Hf=最终fallback计算文件大小，Hf≤Hc；C=四份新候选大小；M=输入说明及小记录大小；B/W分别为DuckDB临时工作文件实际读/写量。这些符号仅用于预算，不是代码配置或新字段。

| 操作 | 业务列与次数 | 文件大小口径的保守估计 |
| --- | --- | --- |
| planner候选/前序计数及目标日count | 身份、日期、freq；第一个SQL的source CTE有两处引用，另一个count SQL；seed一次 | 至多按3R+P计，不声称物理读了三遍全列 |
| 候选历史探查 | 仅候选代码各年身份/日期/freq，判断是否至少4根旧历史 | Hc；不得因最终fallback为空而漏计 |
| 原公式计算并COPY | 正常两年五字段一次，seed一次；必要fallback完整序列五字段一次 | R+P+Hf，写C；仅22日进入输出 |
| 候选source key临时表 | 当前年、目标日四身份字段，保留重复行 | Y；只冻结目标日键，不拷贝全年数据 |
| 完整候选检查 | schema/键/日期/值域/覆盖；来源从临时键表复用 | 按最多4C计，键表内存/临时读单列B |
| 候选SHA | 正常一遍 | C |
| 原四个正式checks | 正式八列及当前年目标日来源键；coverage SQL有两个source读取入口 | 按2Y+3C计；没有两年价格计算 |
| bind输入说明及记录 | 只含路径/stat/SQL/口径 | 读M、写M，不冻结历史价格 |
| 最后验收 | 原检查绑定、receipt、path/stat/控制状态 | 不读正文/摘要；不重复前序或全局检查 |

所以一次正常执行按`4R+3Y+2P+Hc+Hf+8C+M+B`估读，写`C+M+W`，峰值新增空间约`C+M+W`加目标日键及计算内存；提升后C成为正式结果，不另复制一份。已知源集合重复计费部分`4R+3Y=8,878,582,665B=8.268824GiB`，不是整条链的精确磁盘I/O，也不是此次已批准额度。列裁剪、Parquet日期裁剪、CTE物化/缓存会减少文件正文读取，临时溢写会增加B/W；没有测量，不编造精确实际量或耗时。旧历史bootstrap的bytes/row不能保证本次候选压缩大小。

必要前检分开计费：若控制记录和metadata不能证明最终fallback范围，先申请仅2025/2026身份键及21日种子的读范围，复用`_bounded_candidate_codes`取得候选，并只stat这些代码的历史路径，**此时不调用完整planner、不读更早历史正文**。这一轮至多另计`3R+P`（已知部分4.623168GiB），无正式写入。得到Hc后可以用`Hf≤Hc`核完整历史上界，无需先全量读历史才申请。正常job后会重新planner，该前检不冒充可直接续用的执行计划；两阶段已知部分合计`7R+3Y=12.891993GiB`，另加种子、候选历史和小结果等。若现有证据已能确定范围，则省去这一轮，不为了补预算数字而重复审计。

中断后的继续按实际未完成freq计算。为提前解释最多同范围重做一次的开销，保守增加一份上述正常执行成本，且计入原部分候选留存占用；已验证/已提升目标通常只需一次恢复SHA和planner/键读取，实际应从receipt缩小范围。包含必要前检且四freq都重新计算的已知部分为`11R+6Y=21.160817GiB`，其他项按实际集合追加；这不批准重跑，也不表示将完整重跑四freq。没有完成过的文件可能新增C，原半文件和attempt说明继续占空间，不能在预算中假设已被删除。

本轮没有对P、Hc、Hf、C、M、B/W填伪造实测值，亦未冻结新的数值额度。正式前须用有限metadata和已有记录补P、Hc等，提交具体范围/开销；不能把1.54GiB当作总量或把MACD272GiB批准挪到九转。本节当前用途是把必需/重复/恢复读取逐项说明清楚，不是已可直接执行的审批卡。

### 22.7 开发约束、夹具和验收

夹具先对照真实生产者`stk_mins_qfq.py`的写入和`GOLD_STK_MINS_QFQ_SCHEMA`：11列`ts_code/freq/trade_date/trade_time/open/high/low/close/vol/amount/exchange`，其中日期为DATE、分钟时间TIMESTAMP、freq INTEGER、价格量额DOUBLE、其余VARCHAR。seed按当前八列合同构造。沿用的`marker`文件只能测某些文件写入失败，不能证明真实上游接入通过；修改分钟writer测试时换成上述合同，不迁就假输入放宽实现。

每项硬口径落实如下，开发交付时逐项补实际测试结果，不能以“测试全绿”代替对账：

| 要求 | 代码位置 | 正向/反向验证 |
| --- | --- | --- |
| 四频、八列、LAG4、>=9及超过9、零/相等价格规则不变 | 原公式/contract；分钟wrapper | 字面金样本核每根结果、四频及正比例缩放；不足4根真新股为0；不允许提前裁目标日丢LAG上下文 |
| 前序种子接续与fallback原规则不变 | 分钟planner/source plan测试 | 21日末根接22日；整前序文件缺失拒绝；老股缺单代码seed走历史；真新股无旧历史正常；500实际fallback接受、501拒绝；501候选但无旧历史不误拦 |
| 身份从第一次读取前开始保护 | planner/input_file_identities | 正常读取后源/seed变动、fallback重叠路径变化、探查未入最终fallback的文件变化都拒绝；内容正常但身份变更也拒绝同root复用；未变者通过 |
| 完整候选通过才写正式 | 分钟writer/原integrity helper | 缺列/错类型/重复/空键/非法信号/错误频度/跨日拒绝；行数相等但换代码或时间键也拒绝；原目标字节不变；合法NULL信号、新股0不误拦 |
| 候选只在staging、无旧分钟分支 | publication/paths及引用测试 | 临时root和正式路径纯函数边界；异设备、越界、符号链接、并发锁、外部目标变化拒绝；无正式Lake`_staging`创建 |
| 原SQL只COPY一次、正常候选SHA一遍 | 分钟writer及publication摘要计数测试 | bind只写输入说明；正常流程不重复计算/SHA；最终验收不读正文；隔离计数证明，不做正式性能样本 |
| 失败留存并正确继续 | writer/publication | COPY失败、validated后、rename前后、事件前分别注入退出；部分候选保留；同root恢复有效候选/正式结果不COPY、不重写；输入/seed/SQL/规则版本变化、receipt缺失/损坏、外部目标变化拒绝 |
| 日线与既有QFQ/MACD不受影响 | wrapper分流/shared publication | 原日线writer、日线plan默认None、历史bootstrap及既有QFQ/MACD publication定向回归；旧类型路径与行为不变 |
| 原job/check/sensor行为不扩大 | minute asset/root身份与job测试 | 首run与子run传同一root；原四asset+四checks、pool/executor不变；不依赖固定频率顺序；不启动sensor |

已有目标测试文件：`test_qfq_nineturn_writer.py`、`test_qfq_nineturn_source_plan.py`、`test_qfq_nineturn_assets.py`、`test_qfq_nineturn_checks.py`、`test_qfq_nineturn_jobs.py`、`test_qfq_nineturn_history.py`、`test_stk_mins_qfq_publication_single_digest.py`、`test_stk_mins_qfq_staging_publication.py`。公式金样本`test_qfq_nineturn_formula_golden.py`按其现有受保护启动器执行；开发前核对启动器与测试文件实际状态，不另写预期或绕过保护。

不安装/同步依赖。使用本项目现有`.venv`，临时DAGSTER_HOME、DuckDB工作目录、Lake及staging全部在隔离临时目录；测试禁止连接正式instance、网络或正式源。先核资源没有正式地址，再运行定向测试与必要ruff。小规模真实合同集成必须串过真实planner→原SQL→新writer→原完整性检查，预期来自可人工逐根核算的字面样本，不能用待测helper生成expected。测试结束清除本次临时资源并验证无残留；正式staging证据不在此清理范围。

### 22.8 后续执行步骤与未关闭条件

1. **设计确认**：本轮只提交方案/LLD供审阅。开发目标、各代码点与测试已列清，不代表已经获准执行22日job。
2. **开发和隔离验证**：按22.3逐项修改，执行22.7；记录实际代码SHA、每条规则对应测试、无临时残留。发现现行合同与夹具不符先纠正依据，不扩大为算法/历史框架改造。
3. **仅必要前检**：优先复用已有QFQ/因子/控制证据；补21日四份九转metadata、相应原check/物化绑定、精确前序、统一缩放适用依据、目标缺失/既有receipt、共享pool与活动run。需要读取全市场键集合时先按22.6批准；不在此阶段额外执行原完整性检查去重复已通过证据。
4. **冻结本链执行卡**：在本节填入实测metadata的P/Hc、需要的历史范围和预算，获明确批准。执行入口仍是原job，工作目录`lake_console/orchestrator`，正式`DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home`，partition仅2026-10-22；保留既有DuckDB/pool配置，选且仅选四asset+四checks。正式前根据当时可用的原提交入口记录完整命令/脚本、实例、代码SHA及config摘要；本轮尚未生成或执行提交脚本，不以不完整命令冒充可执行步骤。
5. **正式一次执行**：不另写补数计算；仅原job运行四频及四原checks。记录真实频率顺序和逐文件结果；失败不自动重跑、不自动删现场、不回滚已完成文件。如需继续，先用receipt/stat限定尚未完成部分及预算，再恢复原root。
6. **唯一收尾**：核四原checks绑定正确及4份正式文件与receipt/stat一致；复核输入身份/集合及范围外21/23日九转stat，保持其他频率/日期不写。若前序/邻日文件原本不存在，记录为不存在，不能制造文件。销账后仅表示22日原清单109/109通过，不证明23日齐备；两个sensor仍STOPPED，TODO保留。

正式前尚未关闭的事实：21日seed当前质量/身份，因子修复是否符合旧seed继续使用条件，实际候选/fallback名单与Hc，具体历史读写批准及开发后的正式提交命令。它们没有被本轮代码审计或1.54GiB源大小替代。范围变化或代码与本节不符，先同步原方案/LLD后再继续，不能先执行再补文档。
