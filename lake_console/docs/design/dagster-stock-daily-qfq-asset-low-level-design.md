# Dagster 股票日线前复权资产 Low-Level Design

## 1. Summary

本 LLD 细化 `gold_stock_daily_qfq` 的代码级落地方案。目标是在 gold 层新增一个基于 `silver_stock_daily` 与 `silver_adj_factor` 生成的股票日线前复权行情资产，供后续 MA250、日线指标、研究报告和其它下游消费。

本 LLD 只设计数据湖与 Dagster 资产能力，不纳入报告生成逻辑。报告改造后续单独推进。

已确认的用户口径：

1. `gold_stock_daily_qfq` 保留 `pre_close`、`change_amount`、`pct_chg` 字段。
2. 物理布局采用 `trade_date=...`：
   `gold/quote/stock_daily_qfq/trade_date={YYYY-MM-DD}/part-000.parquet`。
3. 日常生成和复权因子变化后的 repair 放在同一专项 / LLD 中设计，但实现上分成不同 entrypoint、job 和测试阶段。
4. 报告相关工作不进入本需求开发范围。
5. 上市首日或湖中无 previous source row 时，`pre_close/change_amount/pct_chg` 统一写 `0`，不写 `NULL`。
6. repair 初版不开放手写 `stock_codes`；repair config、正式 CLI 参数和 sensor payload 都不得暴露股票池输入，affected codes 必须由 `silver_adj_factor` 相邻 expected trade date diff 自动计算。
7. repair 初版必须增加自动 run-status sensor；触发逻辑参考股票分钟线 MACD/KDJ repair：`gold_stock_daily_qfq_update_job` 成功后自动做 bounded plan 判断并提交 scoped repair job。
8. 历史 bootstrap 不是逐日 daily update，也不是逐日回放 repair。第一次全量初始化必须选择明确的 `bootstrap_as_of_trade_date`，用该 as-of 一次性生成全历史前复权序列。
9. P8 历史重建必须先删除旧错误 lake 文件和旧 Dagster materialization / ordinary check events，再按正确 as-of 从零重建并补录新事件；不得在旧文件和旧事件上做局部 patch。
10. `gold_stock_daily_qfq_qfq_semantics_check` 从 P8 后 active ordinary check 口径中移除，不再作为 bootstrap、runless event backfill、readiness、catalog blocking、验收证明或阻断项。公式自检无法证明公式本身正确，P8 不做每行公式一致性 check，也不新增公式级聚合对账、固定样本公式验收或任何替代性公式正确性 check；P8 只验收旧错误文件/event 清零、显式 as-of 重建、结构性 contract 和 runless event 补录事实。文件结构 contract 只证明文件结构和分区契约正确，不证明公式正确。

截至 2026-06-27，第 5、6、7 项均已关闭为正式口径，不再作为待拍板项保留。

代码实现必须按下面三条解释落地：

1. `pre_close/change_amount/pct_chg = 0` 只表示“该股票在湖中没有上一条可用 source row”。它不是数据缺失兜底；如果 previous source row 存在但 previous adj factor 缺失，writer 必须 fail closed，并由契约测试锁死。这里不新增公式正确性 check。
2. repair op、repair config、正式 CLI、sensor payload 和测试都不得出现手写 `stock_codes` 正式入口。affected codes 只能从相邻 expected trade date 的 `silver_adj_factor` diff 得到，并通过 `repair_required_codes_hash` 与 `upstream_batch_id` 校验。
3. repair 自动化只由 `gold_stock_daily_qfq_update_job` 成功 run 触发。不得新增定时全量 repair sensor，不得在 daily job 内混入 repair 写入，也不得让 sensor 扫全历史 Dagster event 或全历史 lake 文件。
4. daily update 的 `as_of_trade_date=partition_key` 只适用于新交易日分区本身；bootstrap 必须显式传入最新完整 as-of，不能靠 writer 默认值。
5. bootstrap as-of factor 对每只股票取“不晚于 bootstrap as-of 的最后可用 `silver_adj_factor`”。已退市股票在 as-of 当天没有因子是正常事实，不能被当成缺口；如果某个 source code 在 as-of 之前从未有过 factor，才必须 fail closed。
6. P8 必须把 `gold_stock_daily_qfq_qfq_semantics_check` 从 active ordinary check、readiness、runless event backfill 和 catalog blocking 口径中移除。保留的 ordinary check 只负责结构性 contract；公式正确性不再写成 Dagster blocking check，也不换成另一种公式级 check。
7. bootstrap 不做公式正确性验收，不复用生产 writer/check 公式实现做自我证明，也不再设计固定样本公式验收或公式级聚合对账。`2026-06-26` 是本次 P8 已确认的 bootstrap as-of；P8 执行期只校验命令显式使用该 as-of、旧文件/event 已清零、文件结构 contract 通过、runless event 按新事实补录，并在同一 P8 阶段完成报告重算前置验收。

## 2. Audit Scope

### 2.1 规范与设计依据

本 LLD 依据：

- 根目录 `AGENTS.md`
- `lake_console/AGENTS.md`
- `lake_console/orchestrator/AGENTS.md`
- `lake_console/orchestrator/CODING_STANDARDS.md`
- `lake_console/docs/design/dagster-data-pipeline-performance-governance.md`
- `lake_console/docs/design/dagster-asset-schema-contract-design.md`
- `lake_console/docs/templates/dagster-dataset-onboarding-template.html`
- `lake_console/docs/design/dagster-stock-daily-qfq-asset-design.md`
- `lake_console/docs/design/dagster-adj-factor-asset-design.md`

### 2.2 当前代码审计范围

已用 CodeGraph 和文本审计覆盖：

- `orchestrator/defs/assets/stock_daily.py`
  - `raw_stock_daily`
  - `silver_stock_daily`
  - `silver_stock_daily_update_job`
  - `silver_stock_daily_update_job_sensor`
- `orchestrator/defs/assets/adj_factor.py`
  - `raw_adj_factor`
  - `silver_adj_factor`
  - `silver_adj_factor_update_job`
  - `silver_adj_factor_update_job_sensor`
- `orchestrator/defs/stk_mins_qfq.py`
  - `build_daily_qfq_select_sql(...)`
  - `execute_gold_stk_mins_qfq_factor_repair(...)`
  - `build_adj_factor_changed_codes_sql(...)`
- `orchestrator/defs/asset_column_schemas.py`
  - `SILVER_STOCK_DAILY_SCHEMA`
  - `SILVER_ADJ_FACTOR_SCHEMA`
  - `GOLD_STK_MINS_QFQ_SCHEMA`
- `orchestrator/defs/catalog/lake_assets.py`
  - partition model
  - asset catalog
  - check catalog
- `orchestrator/defs/checks/stock_daily_checks.py`
  - stock daily check grouping pattern
- `orchestrator/defs/sensors/readiness.py`
  - readiness specs and payload pattern
- `orchestrator/defs/run_contracts/run_keys.py`
  - run key builder
  - upstream batch id
  - forbidden legacy payload fields
- `orchestrator/defs/run_contracts/cursors.py`
  - sensor cursor schema
  - reason code / summary / next action payload rules
- `orchestrator/defs/paths.py`
  - raw / silver / gold lake path helper pattern

### 2.3 当前代码事实

1. `silver_stock_daily` 是未复权股票日线，字段包含：
   `ts_code`、`trade_date`、`open`、`high`、`low`、`close`、`pre_close`、`change_amount`、`pct_chg`、`vol`、`amount`。
2. `silver_adj_factor` 是复权因子日线，字段至少包含：
   `ts_code`、`trade_date`、`adj_factor`。
3. 现有分钟线 qfq 公式不是简单乘以因子，而是：
   `source_price * trade_date_adj_factor / as_of_adj_factor`。
4. `stock_mins_qfq` 的物理布局是 stock-year 文件；股票日线 qfq 已拍板使用 `trade_date=...` 布局，不能复用分钟线 writer。
5. `RunRequest` 必须经统一 `build_run_request(...)` 和 run key builder；不得新增直接 `dg.RunRequest(...)`。
6. sensor cursor 必须使用结构化 payload，不得塞大样本、大 SQL 或大文件清单。

### 2.4 2026-06-27 Bootstrap As-Of 事故审计

本节记录当前 LLD 的原始 P5/P6 口径与正式数据事实之间的冲突，后续 P8 修复必须以这里为基线。

只读审计结论：

1. 用户确认 `600030.SH[2025-06-17]` 的前复权 close 不应等于未复权的 `silver_stock_daily.close=26.70`；这暴露了历史 bootstrap 口径问题。
2. 当前 lake 中 `gold_stock_daily_qfq[2025-06-17]` 的 `600030.SH.close=26.70`，等于 silver close，不是用户需要的 latest-as-of 前复权历史结果。
3. 抽查 `2014-01-02`、`2020-01-02`、`2025-06-17`、`2026-06-09`、`2026-06-10`、`2026-06-26`，`gold_stock_daily_qfq` 的 OHLC 与 `silver_stock_daily` 完全一致，说明问题不是单股或单日样本，而是历史 bootstrap 口径错误。
4. 代码事实：`write_gold_stock_daily_qfq_partition(...)` 默认 `as_of_trade_date = trade_date`；`generate_gold_stock_daily_qfq_history(...)` 调用 writer 时未传 `as_of_trade_date`，导致历史文件按 self-as-of 生成。
5. 代码事实：`gold_stock_daily_qfq_qfq_semantics_check` 及其等价审计当前也按 `as_of_adj_factor_path=adj_factor_path`、`as_of_trade_date=partition_key` 校验，无法发现 self-as-of bootstrap 错误。该 check 属于同公式自检，P8 不再把它作为 readiness 或 bootstrap 正确性证明。
6. Dagster DB 只读审计仅看到 `gold_stock_daily_qfq_update_job[2026-06-26]`，没有看到 `gold_stock_daily_qfq_factor_repair_job` run。历史初始化不能依赖“已经逐日 repair 过”的假设。

结论：

- P6 已执行的历史 bootstrap 文件不能作为 MA250、研究报告或其它需要 current-as-of 前复权历史序列的事实源。
- 不应通过逐日 replay repair 来修正初始历史；正确做法是先删除旧错误文件和旧事件，再按正确 bootstrap as-of 重新生成历史文件和新事件。
- 修复前，报告切换到 `gold_stock_daily_qfq` 必须暂停。

## 3. Target Dataset Contract

### 3.1 Asset Contract

新增 Dagster asset：

- Asset key: `gold_stock_daily_qfq`
- Dataset id: `stock_daily_qfq`
- 中文名: `股票日线前复权`
- Layer: `gold`
- Domain: `quote_data`
- Group: `quote`
- Partition definition: `cn_a_stock_trade_days`

使用 `cn_a_stock_trade_days` 的原因：

- `silver_stock_daily` 是该资产的直接行情输入。
- 输出是按交易日组织的历史日线资产。
- 不使用 `cn_a_stock_current_trade_days`，避免把 current snapshot 口径混入 gold 历史日线资产。

### 3.2 Lake Path

新增 path helper：

```python
def gold_stock_daily_qfq_path(root: Path, partition_key: str) -> Path:
    return (
        root
        / "gold"
        / "quote"
        / "stock_daily_qfq"
        / f"trade_date={partition_key}"
        / "part-000.parquet"
    )
```

禁止：

- 不使用 stock-year 布局。
- 不新增第二套 raw/silver 风格路径。
- 不让下游自己拼路径。

### 3.3 Column Schema

新增 `GOLD_STOCK_DAILY_QFQ_SCHEMA`：

```python
GOLD_STOCK_DAILY_QFQ_SCHEMA = {
    "ts_code": "VARCHAR",
    "trade_date": "DATE",
    "open": "DOUBLE",
    "high": "DOUBLE",
    "low": "DOUBLE",
    "close": "DOUBLE",
    "pre_close": "DOUBLE",
    "change_amount": "DOUBLE",
    "pct_chg": "DOUBLE",
    "vol": "DOUBLE",
    "amount": "DOUBLE",
}
```

字段语义：

- `open/high/low/close`: 前复权价格。
- `pre_close`: 前复权后的上一可交易日收盘价。
- `change_amount`: `close - pre_close`。
- `pct_chg`: `change_amount / pre_close * 100`。
- `vol/amount`: 成交量、成交额不复权，沿用 `silver_stock_daily`。

上市首日或湖中找不到上一可交易日 source row 时：

- `pre_close = 0`
- `change_amount = 0`
- `pct_chg = 0`

理由：

- 新上市股票首个可计算交易日本身没有上一可交易日收盘价。
- 不能 fallback 到任意更早、不属于该股票生命周期的行。
- 这类 0 是“无上一可交易日”的业务占位，不是错误兜底。
- 若 previous source row 存在但 previous factor 缺失，仍必须 fail closed，不得静默写 0。

### 3.4 Catalog Entry

在 `catalog/lake_assets.py` 新增：

- `PartitionModel.TRADE_DATE_PARTITION_GOLD_STOCK_DAILY_QFQ`
- `GOLD_STOCK_DAILY_QFQ_CHECKS`
- `LAKE_ASSET_CATALOG["gold_stock_daily_qfq"]`

catalog 口径：

- `storage_path_template = "gold/quote/stock_daily_qfq/trade_date={trade_date}/part-000.parquet"`
- `partition_model = TRADE_DATE_PARTITION_GOLD_STOCK_DAILY_QFQ`
- `source_assets = ["silver_stock_daily", "silver_adj_factor"]`
- P8 前 ordinary check count = 2；P8 后 ordinary check count 收敛为 1，只保留 `gold_stock_daily_qfq_contract_check`。
- repair status check 单独列为 protected status check，不纳入 ordinary check count。

## 4. QFQ Formula

### 4.1 Daily As-Of Formula

对目标交易日 `D`，日常生成使用：

```text
as_of_trade_date = D
```

每个 source price 的前复权公式：

```text
qfq_price = source_price * adj_factor(row_trade_date) / adj_factor(as_of_trade_date)
```

日常生成中 `row_trade_date = as_of_trade_date = D`，因此 `open/high/low/close` 通常与未复权价一致；但仍必须通过统一 SQL 公式生成。

原因：

- 和 repair 公式保持一致。
- 下游永远只读 gold qfq，不需要理解 source/as-of 差异。
- 后续历史 repair 时同一套公式可以用新的 as-of factor 重算历史行。

### 4.2 Previous Close Formula

`pre_close` 不直接照抄 `silver_stock_daily.pre_close`。正式口径为：

```text
previous_source_close = latest silver_stock_daily.close for same ts_code before D
previous_adj_factor = silver_adj_factor for same ts_code at previous_source_trade_date
as_of_adj_factor = silver_adj_factor for same ts_code at D
pre_close_qfq = previous_source_close * previous_adj_factor / as_of_adj_factor
change_amount = close_qfq - pre_close_qfq
pct_chg = change_amount / pre_close_qfq * 100
```

previous source row 按股票自身在 `silver_stock_daily` 中的上一可用交易日计算，不按全市场上一交易日硬推。

没有 previous source row 时：

```text
pre_close = 0
change_amount = 0
pct_chg = 0
```

这个分支只适用于上市首日或湖中该股票第一条可用日线。存在 previous source row 但缺 previous factor 时，必须 fail closed。

这样可以覆盖：

- 新上市股票。
- 临停或长期停牌后恢复交易。
- 个股缺某日 source row 的情况。

### 4.3 Repair As-Of Formula

当复权因子在交易日 `R` 发生变化时，repair 使用：

```text
as_of_trade_date = R
historical_qfq_price = source_price_at_trade_date * adj_factor(source_trade_date) / adj_factor(R)
```

即 repair 会按 `R` 的复权因子重写受影响股票在历史日期范围内的 qfq 行。

禁止：

- 不用 `silver_stock_daily.close * adj_factor` 这种简化公式。
- 不允许下游报告临时拼复权公式。
- 不允许用缺失上一日时 fallback 到任意更早、不属于股票生命周期的行。

## 5. Code Layout

### 5.1 New Files

建议新增：

```text
lake_console/orchestrator/src/orchestrator/defs/stock_daily_qfq.py
lake_console/orchestrator/src/orchestrator/defs/assets/stock_daily_qfq.py
lake_console/orchestrator/src/orchestrator/defs/checks/stock_daily_qfq_checks.py
lake_console/orchestrator/src/orchestrator/defs/ops/gold_stock_daily_qfq_factor_repair.py
lake_console/orchestrator/src/orchestrator/defs/sensors/stock_daily_qfq_sensor.py
lake_console/orchestrator/src/orchestrator/defs/sensors/gold_stock_daily_qfq_factor_repair_job_sensor.py
```

职责：

- `defs/stock_daily_qfq.py`: SQL、writer、repair range helper、metadata helper。
- `defs/assets/stock_daily_qfq.py`: asset、daily job、repair job definition。
- `defs/checks/stock_daily_qfq_checks.py`: P8 前包含 2 个 ordinary blocking checks 和 1 个 protected repair status check；P8 后 ordinary blocking check 收敛为 retained contract check。
- `defs/ops/gold_stock_daily_qfq_factor_repair.py`: repair op 与 config 消费。
- `defs/sensors/stock_daily_qfq_sensor.py`: daily sensor。
- `defs/sensors/gold_stock_daily_qfq_factor_repair_job_sensor.py`: repair run-status sensor。

### 5.2 Existing Files To Modify

需要修改：

```text
lake_console/orchestrator/src/orchestrator/defs/paths.py
lake_console/orchestrator/src/orchestrator/defs/asset_column_schemas.py
lake_console/orchestrator/src/orchestrator/defs/catalog/lake_assets.py
lake_console/orchestrator/src/orchestrator/defs/catalog/name_mapping.py
lake_console/orchestrator/src/orchestrator/defs/sensors/readiness.py
lake_console/orchestrator/src/orchestrator/defs/run_contracts/configs.py
```

实现前必须再次确认 current definitions loader 是否会自动发现新文件；不得凭历史印象手写注册。

## 6. Asset Write Path

### 6.1 Asset Function

建议：

```python
@dg.asset(
    key="gold_stock_daily_qfq",
    partitions_def=cn_a_stock_trade_days,
    deps=[silver_stock_daily, silver_adj_factor],
    group_name="quote",
    metadata=...,
    tags=...,
)
def gold_stock_daily_qfq(
    context: dg.AssetExecutionContext,
    lake_root: LakeRootResource,
    duckdb: DuckDBResource,
) -> dg.MaterializeResult:
    ...
```

执行流程：

1. 读取 `partition_key`。
2. 计算目标输入：
   - `silver_stock_daily_path(root, partition_key)`
   - `silver_adj_factor_path(root, partition_key)`
3. 计算 previous lookup：
   - 从 `silver_trade_calendar` 取 `partition_key` 前最多 20 个 expected trade dates。
   - 生成这些日期的 `silver_stock_daily_path` 与 `silver_adj_factor_path` 候选。
   - 只读取存在的文件。
4. 若目标日 `silver_stock_daily` 或目标日 `silver_adj_factor` 缺失，抛 `dg.Failure`。
5. 使用 DuckDB set-based SQL 生成 qfq rows。
6. 写临时文件，再原子替换目标 Parquet。
7. 返回 `dg.MaterializeResult`。

materialization metadata：

- `row_count`
- `observed_columns`
- `output_file_path`
- `source_silver_stock_daily_file_path`
- `source_silver_adj_factor_file_path`
- `previous_lookup_trade_date_count`
- `missing_previous_row_count`

### 6.2 SQL Helper

新增：

```python
def build_stock_daily_qfq_select_sql(
    *,
    stock_daily_path: Path,
    trade_adj_factor_path: Path,
    previous_stock_daily_paths: Sequence[Path],
    previous_adj_factor_paths: Sequence[Path],
    as_of_adj_factor_path: Path,
    trade_date: str,
    as_of_trade_date: str,
) -> str:
    ...
```

SQL 结构：

1. `source_daily`: 读取目标日 `silver_stock_daily`。
2. `trade_factor`: 读取 row trade date 对应 factor。
3. `as_of_factor`: 读取 as-of 日 factor。
4. `previous_daily`: 从 previous paths 读取，并按 `ts_code` 取最大 `trade_date`。
5. `previous_factor`: 读取 previous row 对应 factor。
6. 输出 qfq 字段。

性能约束：

- 使用 DuckDB `read_parquet([...])` 或等价批量读取。
- 禁止 Python 行循环。
- previous lookup 默认最多 20 个 expected dates。
- SQL 和 metadata 不写大样本行。

### 6.3 Writer Helper

新增：

```python
def write_gold_stock_daily_qfq_partition(
    *,
    connection: duckdb.DuckDBPyConnection,
    lake_root: Path,
    trade_date: str,
    previous_lookup_trade_dates: Sequence[str],
) -> StockDailyQfqWriteResult:
    ...
```

`StockDailyQfqWriteResult` 字段：

- `trade_date`
- `output_path`
- `row_count`
- `source_row_count`
- `missing_previous_row_count`
- `previous_lookup_start_date`
- `previous_lookup_end_date`
- `previous_lookup_file_count`

## 7. Asset Checks

### 7.1 Check Count

P8 后 ordinary blocking check 收敛为 1 个：

- `gold_stock_daily_qfq_contract_check`

`gold_stock_daily_qfq_qfq_semantics_check` 退出 ordinary readiness、catalog blocking checks、runless event backfill 和历史 bootstrap 证明链路。

原因：

- 公式自检会复用同一套前复权计算逻辑；如果公式本身写错，自检仍可能全绿，不能证明数据正确。
- 本次事故已经证明“formula check 全绿”不等于 bootstrap 结果正确。
- Dagster DB 只保留对自动触发有实际价值的结构性 check，避免为低价值 check 继续制造历史 event 增量。
- P8 不做每行公式一致性 check，也不做固定样本、公式级聚合对账或替代性公式正确性 check；P8 只确认旧错误文件/event 清零、显式 as-of 重建、文件结构 contract 验收和 runless event 补录事实，不写成 daily blocking check。
- 文件结构 contract 验收只检查文件是否存在、schema、分区日期、主键唯一性、必要字段非空等结构契约，不承担“公式正确”的证明职责。

### 7.2 Check Names

retained ordinary check：

```text
gold_stock_daily_qfq_contract_check
```

ordinary check 必须显式声明：

```python
partitions_def=cn_a_stock_trade_days
```

这是分区归属门禁，不是样式要求。`gold_stock_daily_qfq_update_job` 成功后，Dagster
必须能在 `asset_check_executions.partition=<trade_date>` 下读取该 check；否则
repair run-status sensor 会把该分区误判为 missing blocking checks，从而跳过
`gold_stock_daily_qfq_factor_repair_job`。

protected status check：

```text
gold_stock_daily_qfq_factor_repair_plan_evaluated
```

`gold_stock_daily_qfq_factor_repair_plan_evaluated` 不属于 daily readiness checks；它是 repair 状态账本，后续 event retention 必须保护。

### 7.3 Contract Check

`gold_stock_daily_qfq_contract_check` 覆盖：

- 文件存在。
- row count > 0。
- schema 与 `GOLD_STOCK_DAILY_QFQ_SCHEMA` 一致。
- `trade_date` 列非空。
- 文件内 `trade_date` 必须等于 partition key。
- `ts_code` 非空。
- `(ts_code, trade_date)` 唯一。

metadata：

- `checked_row_count`
- `failed_rule_names`
- `file_path`
- `partition_key`
- `duplicate_key_count`
- `null_key_count`
- `sample_rows`

### 7.4 Removed QFQ Semantics Check

P8 删除 `gold_stock_daily_qfq_qfq_semantics_check` 的 ordinary check 地位。

删除范围：

- 从 `GOLD_STOCK_DAILY_QFQ_CHECK_NAMES` 移除。
- 从 `GOLD_STOCK_DAILY_QFQ_READINESS_SPECS` 移除。
- 从 `GOLD_STOCK_DAILY_QFQ_CHECKS` / catalog blocking checks 移除。
- 从 `gold_stock_daily_qfq_update_job` 的 ordinary check 预期中移除。
- 从历史 runless ordinary check event 规划和补录中移除。

它不再作为“数据正确”的证明，也不再作为 sensor 自动触发的阻断条件。P8 只保留执行事实与结构契约验收，不再设计任何公式正确性检查：

- 使用 DuckDB / 文件系统只确认旧文件已清零、新文件已生成、schema / partition / primary key / row count 等结构 contract 成立，以及 runless event 补录范围正确。
- 不使用固定已知样本直接读取重建结果做公式验收，不复用生产 writer/check helper，也不新增公式级聚合差异对账或替代性公式正确性 check。
- `600030.SH[2025-06-17]` 等样本只保留为事故分析背景和 as-of 口径说明，不作为 P8 自动验收项。
- 输出审计 JSON/CSV 到 `/private/tmp` 或审批指定位置，不写 Dagster check event。
- 结构 contract 或事件范围验收失败时不得补录 materialization 或 contract check event。

## 8. Daily Job

新增：

```python
gold_stock_daily_qfq_update_job = dg.define_asset_job(
    name="gold_stock_daily_qfq_update_job",
    selection=(
        dg.AssetSelection.assets(gold_stock_daily_qfq)
        | dg.AssetSelection.checks_for_assets(gold_stock_daily_qfq)
    ),
)
```

checks-only 维护入口：

```python
gold_stock_daily_qfq_check_refresh_job = dg.define_asset_job(
    name="gold_stock_daily_qfq_check_refresh_job",
    selection=dg.AssetSelection.checks_for_assets(gold_stock_daily_qfq),
    partitions_def=cn_a_stock_trade_days,
    executor_def=dg.in_process_executor,
)
```

该入口只用于人工 checks-only 修复，不接 sensor，不选择
`AssetSelection.assets(...)`，不重写 `gold_stock_daily_qfq` Parquet。

禁止：

- job 内不写 SQL。
- job 不包含 repair op。
- job 不包含报告逻辑。
- job 不直接构造 run key。

## 9. Daily Sensor

### 9.1 Sensor Definition

新增：

```python
@dg.sensor(
    name="gold_stock_daily_qfq_update_job_sensor",
    job=gold_stock_daily_qfq_update_job,
    default_status=dg.DefaultSensorStatus.STOPPED,
    minimum_interval_seconds=600,
    required_resource_keys={"lake_root", "duckdb"},
)
def gold_stock_daily_qfq_update_job_sensor(...):
    ...
```

默认 `STOPPED`，由运营确认后再开启。

### 9.2 Target Selection

target selection 口径：

1. 用 `silver_trade_calendar` 生成最近 10 个 expected trade dates。
2. partition set 使用 `cn_a_stock_trade_days`。
3. 先查 registered gap。
4. 再查 `gold_stock_daily_qfq` 自身 readiness。
5. 选择 first not-ready date。
6. selected date 上检查上游：
   - `silver_stock_daily` ready。
   - `silver_adj_factor` ready。
7. 上游 ready 后提交 selected date run。

禁止：

- 不按 latest registered 直接推进。
- 不扫描全历史 Dagster event。
- 不解析 run key 反推 config。
- 不新增直接 `dg.RunRequest(...)`。

### 9.3 Run Request

使用统一 builder：

```python
build_run_request(
    job_name="gold_stock_daily_qfq_update_job",
    partition_key=trade_date,
    run_key=build_asset_update_run_key(
        subject="gold_stock_daily_qfq_update",
        unit_id=trade_date,
    ),
    run_config=None,
    tags=...,
)
```

run key：

```text
gold_stock_daily_qfq_update:{trade_date}
```

### 9.4 Cursor

cursor 使用 `build_sensor_cursor(...)`。

cursor details：

- `continuity_status`
- `gold_stock_daily_qfq_status`
- `silver_stock_daily_status`
- `silver_adj_factor_status`
- `reason_code`

`reason_code` 必须是英文枚举，例如：

- `missing_registered_partition`
- `gold_stock_daily_qfq_not_ready`
- `upstream_silver_stock_daily_not_ready`
- `upstream_silver_adj_factor_not_ready`
- `selected_for_update`
- `all_ready`

不允许中文 reason code。

## 10. Repair Job

### 10.1 Why Separate Repair

日常生成和 repair 不合并为同一个 job。

原因：

- 日常生成只写一个 trade date partition。
- repair 会改写多个历史 trade date partition，风险和耗时明显更高。
- repair 需要 status metadata、affected code hash、effective range 等审计信息。
- 合并入口会让 sensor、run key、config、权限和回滚边界混在一起。

### 10.2 Repair Job Definition

新增：

```python
gold_stock_daily_qfq_factor_repair_job = dg.job(
    name="gold_stock_daily_qfq_factor_repair_job",
    resource_defs=...,
)(...)
```

内部只包含一个 op：

```text
gold_stock_daily_qfq_factor_repair_op
```

repair job 不由定时 sensor 直接扫描全量触发，而是由 run-status sensor 在 daily qfq 成功后做 bounded plan 判断并自动提交。

### 10.3 Repair Config

在 `run_contracts/configs.py` 新增显式 config：

```python
class GoldStockDailyQfqFactorRepairConfig(dg.Config):
    qfq_factor_trade_date: str
    repair_required_codes_hash: str
    upstream_batch_id: str
```

已拍板：初版不支持手写 `stock_codes`，config schema、正式 CLI 参数和 sensor payload 中都不得出现 `stock_codes` 字段。

原因：

- 受影响股票应来自 `silver_adj_factor` 与 previous expected date 的因子 diff。
- 手写 code list 容易产生散装 repair 和审计口径漂移。
- repair op 内部重新计算 affected codes，并校验 config 中的 `repair_required_codes_hash`。
- `upstream_batch_id` 来自触发本次判断的 daily qfq run 和 affected codes hash，用于 run key 幂等和 repair completion 对账。
- 如果未来需要人工限定 stock_codes，必须另开设计并要求 hash/source/audit metadata；不得在本入口上追加兼容字段。

### 10.4 Repair Run-Status Sensor

已拍板：repair 初版必须增加自动 run-status sensor。它不是定时扫全量日期的 sensor，而是只监听 `gold_stock_daily_qfq_update_job` 成功 run，并对触发 run 的单个 `trade_date` 做 bounded repair plan 判断。

新增：

```python
@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.SUCCESS,
    request_job=gold_stock_daily_qfq_factor_repair_job,
    monitored_jobs=[gold_stock_daily_qfq_update_job],
    default_status=dg.DefaultSensorStatus.STOPPED,
    tags=...,
)
def gold_stock_daily_qfq_factor_repair_job_sensor(
    context: dg.RunStatusSensorContext,
) -> dg.RunRequest | dg.SkipReason:
    ...
```

触发口径：

1. 只监听 `gold_stock_daily_qfq_update_job` 成功。
2. 从触发 run 的 partition tag 读取 `qfq_factor_trade_date`。
3. 只对该交易日计算 repair plan。
4. 不定时扫全量日期。
5. 不扫描全历史 Dagster event。
6. 不在 sensor 中写 lake 文件或 Dagster event。

sensor 决策流程：

1. 解析 target trade date；无法解析则 skip。
2. 确认 target date 的 `gold_stock_daily_qfq` ordinary readiness ready；不 ready 则 skip。
3. 读取 target date 和上一 expected trade date 的 `silver_adj_factor`。
4. 用 DuckDB set-based SQL 计算 affected codes。
5. 若 affected codes 为空，skip。
6. 若 affected codes 数量超过自动上限，skip，要求人工 dry-run 后再处理。
7. 计算 `repair_required_codes_hash`。
8. 用触发 daily run id、target trade date、hash 构造 `upstream_batch_id`。
9. 查询同一 `upstream_batch_id` 的 repair status；已 ready 则 skip。
10. 未完成则提交 `gold_stock_daily_qfq_factor_repair_job`。

run key：

```python
build_upstream_triggered_run_key(
    consumer="gold_stock_daily_qfq_factor_repair",
    upstream_batch_id=upstream_batch_id,
)
```

run config：

```python
{
    "ops": {
        "gold_stock_daily_qfq_factor_repair_op": {
            "config": {
                "qfq_factor_trade_date": target_trade_date,
                "repair_required_codes_hash": repair_required_codes_hash,
                "upstream_batch_id": upstream_batch_id,
            }
        }
    }
}
```

自动上限：

```python
GOLD_STOCK_DAILY_QFQ_FACTOR_REPAIR_AUTO_CODE_LIMIT = 500
```

超过上限不代表不能修，只代表不能自动修。后续必须通过 repair dry-run 报告单独审批。

### 10.5 Affected Code Detection

新增：

```python
def build_stock_daily_qfq_factor_changed_codes_sql(
    *,
    current_adj_factor_path: Path,
    previous_adj_factor_path: Path,
) -> str:
    ...
```

语义：

- `qfq_factor_trade_date = R`。
- 找 previous expected trade date `P`。
- 比较 `silver_adj_factor[R]` 与 `silver_adj_factor[P]`。
- `adj_factor` 变化的股票进入 affected set。
- 新上市导致 previous factor 不存在、且没有历史 qfq 行的股票不进入 repair set。

### 10.6 Effective Repair Range

repair range 不使用全局历史起点。

计算：

1. 读取 affected codes。
2. 从现有 `gold_stock_daily_qfq/trade_date=*/part-000.parquet` 中批量查询 affected codes 的最早 `trade_date`。
3. `effective_start_trade_date = min(existing qfq trade_date for affected codes)`。
4. `repair_end_trade_date = qfq_factor_trade_date`。
5. target dates = expected calendar between effective start and repair end。

如果 affected codes 非空但没有任何现有 qfq row：

- fail closed。
- 不写 success metadata。
- 提示需要先完成历史 bootstrap。

### 10.7 Repair Write Strategy

对每个 target trade date：

1. 必须存在现有 `gold_stock_daily_qfq` partition 文件。
2. 必须存在对应 `silver_stock_daily` source 文件。
3. 必须存在 target trade date 的 `silver_adj_factor`。
4. 必须存在 as-of trade date 的 `silver_adj_factor`。
5. 生成 affected codes 的 replacement rows。
6. 读取 existing gold qfq rows。
7. 删除 existing 中 affected codes 的旧 rows。
8. union unaffected rows + replacement rows。
9. 校验 `(ts_code, trade_date)` 唯一。
10. 写临时文件后原子替换目标文件。

禁止：

- 不创建原本不存在的历史 partition。
- 不跳过中间缺失 partition 后继续写。
- 不在 Python 中逐行循环计算价格。
- 不写旧 storage id 字段。

### 10.8 Repair Status Check

新增 protected check：

```text
gold_stock_daily_qfq_factor_repair_plan_evaluated
```

metadata：

- `qfq_factor_trade_date`
- `repair_start_trade_date`
- `repair_end_trade_date`
- `repair_required_codes`
- `repair_required_codes_count`
- `repair_required_codes_hash`
- `rewritten_partition_count`
- `rewritten_row_count`
- `skipped_partition_count`
- `upstream_batch_id`
- `producer_run_id`

`upstream_batch_id` 使用统一 `build_batch_id(...)`。

禁止：

- 不写 `event_storage_id`。
- 不写旧 storage id 字段。
- 不把完整大 code list 写到 cursor。
- metadata 中 code list 必须有上限；超过上限写 hash 和 truncated 标记，并 fail closed 或要求分批设计。

## 11. Historical Bootstrap And Event Backfill

### 11.1 Why Bootstrap Is Needed

`gold_stock_daily_qfq` 的主要业务价值是计算长期均线和指标。如果只从上线日起增量生成，则 MA250 等下游会缺历史基础。

因此需要历史 bootstrap。

### 11.2 Bootstrap Scope

历史 bootstrap 生成文件：

- 从 `silver_stock_daily` 已有最早日期开始。
- 到当前最新 `cn_a_stock_trade_days`。
- 只处理 `silver_stock_daily` 与 `silver_adj_factor` 都存在的日期。
- 必须显式指定 `bootstrap_as_of_trade_date`。该日期通常等于本次 bootstrap 覆盖范围内最新完整交易日，并且该日 `silver_adj_factor` 必须存在。
- 所有历史分区都按同一个 `bootstrap_as_of_trade_date` 生成；不得对每个 partition 使用自身日期作为 as-of。

历史 bootstrap 不通过 Dagster sensor 自动触发。

P5 已新增 bootstrap dry-run / sample CLI：

```text
python -m orchestrator.defs.bootstrap.gold_stock_daily_qfq_history_cli profile-history
python -m orchestrator.defs.bootstrap.gold_stock_daily_qfq_history_cli write-sample
python -m orchestrator.defs.bootstrap.gold_stock_daily_qfq_history_cli build-history
```

参数：

- `--lake-root`
- `--start-date`
- `--end-date`
- `--partition-keys`
- `--as-of-trade-date`
- `--apply`
- `--overwrite`
- `--report-dir`

P8 正式重建不得用 `--overwrite` 替代删除旧错误文件；必须先执行独立 delete/reset dry-run 与审批后的旧文件删除，再重新 build。

口径：

1. `profile-history` 永远只读，只输出 JSON report，不写 lake，不写 Dagster event；report 必须输出 `bootstrap_as_of_trade_date`、as-of factor 分区存在性、selected partition 范围和预计重写文件数。
2. `write-sample` 默认仍是 dry-run；只有显式传入 `--apply` 才会写 sample partition。
3. `build-history` 默认仍是 dry-run；只有显式传入 `--apply` 且显式传入 `--as-of-trade-date` 才会写 full selected partition 文件。
4. P5 不做正式全量写入，不做 runless materialization/check event backfill。
5. P6 已提供 full file bootstrap 与 runless event backfill 工具；正式执行仍必须单独审批。

纠错口径：

- 2026-06-27 审计确认：旧 P6 正式 bootstrap 未传 `as_of_trade_date`，实际生成了 self-as-of 文件。这是错误历史结果，不应继续作为消费事实。
- 修复后的 bootstrap 不需要逐日执行 repair；它必须一次性写出“截至 `bootstrap_as_of_trade_date` 的正确历史前复权序列”。
- 后续日常 `gold_stock_daily_qfq_update_job` 仍按当天 self-as-of 写新分区，之后由 run-status sensor 根据相邻因子变化触发 scoped repair，维护历史序列。

### 11.3 Runless Event Backfill Policy

为兼顾历史可追溯性与 Dagster DB 增长控制，历史 bootstrap 的 materialization event 与 retained ordinary check event 分开补录。P8 后 retained ordinary check 只指 `gold_stock_daily_qfq_contract_check`。

默认策略：

1. 文件全历史生成，且所有文件必须对应同一个已记录的 `bootstrap_as_of_trade_date`。
2. Dagster runless materialization event 全历史补录，metadata 必须包含 `qfq_as_of_trade_date` / `bootstrap_as_of_trade_date`。
3. Dagster runless ordinary check event 只补保留的结构性 contract check：
   - 最近 20 个 `cn_a_stock_trade_days`。
   - latest partition。
4. `gold_stock_daily_qfq_qfq_semantics_check` 不补录、不回填、不作为 bootstrap 正确性证明。
5. repair/status protected check event 按 repair trade date 单独写入，不参与 ordinary check event 补录窗口。
6. 如果运营明确要求 UI 可证明全部历史 partition 的 retained ordinary check 都 ready，再单独审批全历史 contract check event backfill；不得恢复 qfq semantics 公式自检作为证明。

理由：

- materialization event 表达“历史分区文件存在且已按指定 as-of 生成”，全历史补录成本可控。
- 报告和计算读取 Parquet 文件，不依赖 Dagster 历史 event。
- sensor 日常推进只依赖 recent window 和 latest 的 check 状态。
- 20 日以前不要求 Dagster DB 长期保存每个历史分区的 check 绿灯，历史文件存在、结构和事件补录事实以 bootstrap 执行报告为准。
- 避免新数据集一上线就制造数千个历史 ordinary check event。

### 11.4 Bootstrap Safety

bootstrap 必须：

- 先 dry-run 输出日期数、预计文件数、预计行数。
- 先 dry-run 输出 `bootstrap_as_of_trade_date`，并证明 as-of factor 分区存在。
- 样本执行 1 个 partition。
- 再分批执行全量。
- 每批写入后只做 row count / schema / 分区日期 / 主键唯一性等结构性审计。
- 不再设计“历史分区 + 后续 as-of factor”的公式样本验收；`600030.SH[2025-06-17]` 的差异只作为本次事故根因说明，不进入 P8 验收门禁。
- 不删除已有 `silver_stock_daily` 或 `silver_adj_factor`。
- P8 正式重建前必须清理旧的 `gold_stock_daily_qfq` Dagster materialization / ordinary check events，清理范围必须由 dry-run SQL 精确限定到该 asset；不删除 runs、run_tags、dynamic partitions、instigators、其它资产事件或 repair/status protected checks。

## 12. Readiness

### 12.1 New Readiness Specs

在 `sensors/readiness.py` 中新增：

```python
GOLD_STOCK_DAILY_QFQ_READINESS_SPECS = (
    AssetReadinessSpec(
        asset_key=dg.AssetKey("gold_stock_daily_qfq"),
        required_check_names=GOLD_STOCK_DAILY_QFQ_CHECK_NAMES,
    ),
)
```

P8 后 ordinary readiness 只包含 retained contract check：

```python
GOLD_STOCK_DAILY_QFQ_CHECK_NAMES = (
    "gold_stock_daily_qfq_contract_check",
)
```

不包含：

- `gold_stock_daily_qfq_factor_repair_plan_evaluated`
- `gold_stock_daily_qfq_qfq_semantics_check`

### 12.2 Readiness Helper

新增：

```python
def gold_stock_daily_qfq_ready_for_trade_date(
    instance: dg.DagsterInstance,
    trade_date: str,
) -> DatasetReadinessStatus:
    ...
```

使用现有 `partition_dataset_readiness_status_from_latest_checks(...)` pattern。

注意：

- 只用于 selected date。
- 不允许在 sensor hot path 对 10 天窗口逐日扫 Dagster event。
- 如未来发现性能问题，应补 DuckDB lake readiness batch helper，而不是扩大 Dagster event scan。

## 13. Performance Gate

### 13.1 Daily Update

目标规模：

- 每日 source 行数：约 A 股日线几千行。
- 输入文件：
  - 目标日 `silver_stock_daily` 1 个文件。
  - 目标日 `silver_adj_factor` 1 个文件。
  - previous lookup 最多 20 个 `silver_stock_daily` 文件。
  - previous lookup 最多 20 个 `silver_adj_factor` 文件。
- 输出文件：1 个 Parquet。
- Dagster event：1 materialization + 1 retained ordinary contract check。

不可接受：

- 每日 job 读全历史日线。
- 每日 sensor 扫全历史 Dagster event。
- 每日 sensor 对每个股票逐个查询。

### 13.2 Repair

repair 必须先 dry-run。

dry-run 输出：

- affected code count
- effective start date
- target partition count
- expected source file count
- estimated rewrite row count
- estimated output file count
- missing source partition samples

不可接受：

- 未 dry-run 直接全量 rewrite。
- Python row loop 计算全市场历史价格。
- 写完整历史所有股票，而不是 affected codes。
- repair status metadata 写超大 code list。

### 13.3 Event Growth

ordinary check event 增量：

- 日常：每个交易日 1 条 retained ordinary contract check event。
- bootstrap materialization event 全历史补录。
- bootstrap ordinary check event 默认只补 retained contract check 的最近 20 日 + latest。
- repair：每个 repair trade date 1 条 protected status check。

这比把细粒度 SQL 规则拆成十几个 check 更可控。

## 14. Tests

### 14.1 Test Files

新增：

```text
tests/test_stock_daily_qfq_contracts.py
tests/test_stock_daily_qfq_checks.py
tests/test_stock_daily_qfq_sensor_contracts.py
tests/test_stock_daily_qfq_repair_contracts.py
```

### 14.2 Asset Write Tests

覆盖：

- 目标日 source 和 factor 都存在时写入成功。
- `open/high/low/close` 按 formula 生成。
- 显式 `as_of_trade_date` 与 `trade_date` 不同时，历史分区必须按
  `source_price * adj_factor(trade_date) / adj_factor(as_of_trade_date)`
  生成，不得继续等于 `silver_stock_daily`。
- `pre_close/change_amount/pct_chg` 按上一可交易日生成。
- 新上市首日 previous row 缺失时 `pre_close/change_amount/pct_chg` 为 0。
- previous row 缺失时 0 是合法业务占位；previous row 存在但 previous factor 缺失时仍 fail closed。
- 合法 previous row 缺失场景不得写 `NULL`；`pre_close/change_amount/pct_chg` 必须稳定写 `0`。
- 目标日 `silver_stock_daily` 缺失 fail closed。
- 目标日 `silver_adj_factor` 缺失 fail closed。
- previous row 存在但 previous factor 缺失 fail closed。

### 14.3 Check Tests

覆盖：

- contract: 缺文件、空文件、schema mismatch、partition date mismatch。
- key integrity: null key、duplicate key。
- P8 删除 qfq semantics ordinary check 后：
  - `GOLD_STOCK_DAILY_QFQ_CHECK_NAMES` 只包含 `gold_stock_daily_qfq_contract_check`。
  - readiness specs 只要求 retained contract check。
  - catalog blocking checks 不包含 `gold_stock_daily_qfq_qfq_semantics_check`。
  - runless event plan/report 不生成 qfq semantics check event。
- bootstrap 独立测试：
  - `build-history` 必须显式传入 `as_of_trade_date`，省略时失败。
  - 传入的 `as_of_trade_date` 必须进入 plan/report metadata，并传给 writer。
  - 测试只证明 as-of 参数链路正确，不做公式正确性验收。
  - 不得复用 production qfq semantics check helper。

### 14.4 Sensor Tests

覆盖：

Daily sensor：

- registered gap 时 skip。
- output 缺失时提交 selected date run。
- output materialized but check failed 时 skip，不自动重跑。
- selected date `silver_stock_daily` not ready 时 skip。
- selected date `silver_adj_factor` not ready 时 skip。
- all ready 时 skip。
- run key 为 `gold_stock_daily_qfq_update:{trade_date}`。
- 不出现直接 `dg.RunRequest(...)`。

Repair run-status sensor：

- 监听 `gold_stock_daily_qfq_update_job` success。
- 只由 run-status sensor 驱动 scoped repair；不新增 schedule sensor、普通 polling sensor 或全量 repair sensor。
- target trade date 解析失败时 skip。
- target `gold_stock_daily_qfq` ordinary readiness 不 ready 时 skip。
- affected codes 为空时 skip。
- affected codes 超过自动上限时 skip。
- repair status 已 ready 时 skip。
- affected codes 未超过上限、completion 未 ready 时提交 repair job。
- run key 使用 `build_upstream_triggered_run_key(...)`。
- run config 不包含 `stock_codes`。
- sensor payload 不包含 `stock_codes`；payload 只允许携带 `qfq_factor_trade_date`、`repair_required_codes_hash`、`upstream_batch_id` 这类 bounded identity。

### 14.5 Repair Tests

覆盖：

- factor unchanged no-op，写 repair status。
- factor changed，effective start 来自现有 qfq rows。
- affected codes 起点不同，effective start 取最早 qfq row。
- affected code 无现有 qfq rows 时 fail closed。
- missing intermediate qfq partition fail closed。
- repair 只改 affected codes，不改 unaffected rows。
- metadata 写 `repair_required_codes_hash` 与 `upstream_batch_id`。
- repair op 重新计算 affected codes，并校验 config 里的 `repair_required_codes_hash`。
- config 不允许 `stock_codes`。

### 14.6 Static Gates

更新 `tests/test_run_contract_static_gates.py`：

- `gold_stock_daily_qfq` writer / contract tests 必须锁住合法 previous row 缺失时写 `0`，不得回流 `NULL`。
- 新 sensor 禁止直接 `dg.RunRequest(...)` / `RunRequest(...)`。
- 新 sensor 禁止手写 `run_key=f`。
- repair config 禁止 `event_storage_id` / `storage_id`。
- repair config 禁止 `stock_codes`。
- repair sensor 文件禁止出现 `stock_codes` payload、cursor 或 config 映射。
- repair 自动化只能使用 `@dg.run_status_sensor`，不得改成定时全量 sensor。
- repair run-status sensor 必须使用 `build_upstream_triggered_run_key(...)`。
- repair run-status sensor 必须监控 `gold_stock_daily_qfq_update_job`。
- ordinary check count 在 P8 后固定为 1。
- protected repair status check 不得进入 ordinary readiness spec。
- bootstrap CLI 不得有默认 apply/delete。
- bootstrap `build-history --apply` 缺 `--as-of-trade-date` 时必须失败。
- bootstrap / runless event helper 不得生成或依赖 qfq semantics ordinary check event。
- bootstrap formula validation 禁止项不得复用 production qfq semantics check helper。

## 15. Development Phases

### P0: LLD Review

当前阶段。

输出：

- 本 LLD。
- 用户 review 后确认是否进入编码。

### P1: Core Formula And Writer

状态：已完成。

范围：

- path helper
- schema
- SQL helper
- writer helper
- asset materialization
- asset write unit tests

不做：

- sensor
- repair
- bootstrap

已落地文件：

- `defs/paths.py`: `gold_stock_daily_qfq_path(...)`
- `defs/run_contracts/asset_column_schemas.py`: `GOLD_STOCK_DAILY_QFQ_SCHEMA`
- `defs/catalog/name_mapping.py`: `stock_daily_qfq` 中文名。该项原列在 P2，但 P1 asset definition metadata 必须立即解析 dataset 中文名，否则 definitions 导入会失败；catalog registry 仍留到 P2。
- `defs/stock_daily_qfq.py`: qfq SQL、coverage validation、previous lookup、writer helper。
- `defs/assets/stock_daily_qfq.py`: `gold_stock_daily_qfq` asset definition。
- `tests/test_stock_daily_qfq_contracts.py`: P1 formula/writer/asset definition tests。

本地验证：

```bash
cd lake_console/orchestrator
PYTHONPATH=src uv run --project . --with pytest python -m pytest tests/test_stock_daily_qfq_contracts.py
```

结果：`6 passed`。测试只使用临时目录和本地 DuckDB，不读取正式 Dagster runtime，不触碰正式数据湖。

### P2: Checks And Catalog

范围（P8 前历史事实，P8 将收敛 ordinary check 口径）：

- catalog entry
- name mapping
- P8 前 2 ordinary checks；P8 后 retained ordinary check 只保留 contract
- readiness specs
- check tests
- static gates

已落地文件：

- `defs/catalog/lake_assets.py`: `gold_stock_daily_qfq` catalog entry、`TRADE_DATE_PARTITION_GOLD_STOCK_DAILY_QFQ` partition model；P8 前包含 2 条 ordinary blocking checks，P8 后必须移除 qfq semantics。
- `defs/checks/stock_daily_qfq_checks.py`: P8 前包含 `gold_stock_daily_qfq_contract_check` 与 `gold_stock_daily_qfq_qfq_semantics_check`；P8 后 `gold_stock_daily_qfq_qfq_semantics_check` 不再作为 ordinary readiness/check event 口径。
- `defs/sensors/readiness.py`: `GOLD_STOCK_DAILY_QFQ_READINESS_SPECS` 与 `gold_stock_daily_qfq_ready_for_trade_date(...)`。
- `tests/test_stock_daily_qfq_checks.py`: P8 前 contract/qfq semantics check 正反例；P8 后改为 contract check 与公式验证禁用门禁。
- `tests/test_stock_daily_qfq_contracts.py`: catalog/readiness 对账、ordinary checks 分区归属、checks-only refresh job 只选 checks、update job 本地执行后 readiness 可按 partition 读到 checks。
- `tests/test_asset_governance_contracts.py`: active asset / catalog 数量与 blocking check 对账。
- `tests/test_run_contract_static_gates.py`: ordinary check 数量、防 repair status 进入 ordinary readiness、ordinary checks 必须显式 `partitions_def`、checks-only refresh job 禁止选择 materializable asset、DuckDB 连接门禁。

P8 前已确认口径：

- ordinary readiness 只包含：
  - `gold_stock_daily_qfq_contract_check`
  - `gold_stock_daily_qfq_qfq_semantics_check`
- `gold_stock_daily_qfq_factor_repair_plan_evaluated` 不进入 ordinary readiness。
- 两个 ordinary checks 内部用 `failed_rule_names` 表达子规则，不拆成更多 Dagster check，避免 asset check event 过快膨胀。
- 两个 ordinary checks 必须带 `cn_a_stock_trade_days` 分区定义，避免 check event 缺 partition 后让 run-status repair sensor 误判 ordinary checks missing。
- check 只读临时/目标 Parquet 与上游 silver 文件，不写 lake，不写 Dagster event。

P8 纠偏口径：

- ordinary readiness 只保留 `gold_stock_daily_qfq_contract_check`。
- `gold_stock_daily_qfq_qfq_semantics_check` 从 readiness、catalog blocking checks、runless event backfill 和 P8 bootstrap 证明链路中移除。
- P8 不做每行公式一致性 check，也不做固定样本、公式级聚合对账或其它公式正确性验收；P8 只确认显式 as-of 重建、文件结构 contract 验收、旧错误文件/event 清零和 runless event 补录事实，不再写入公式类 Dagster check event。

本地验证：

```bash
cd lake_console/orchestrator
PYTHONPATH=src uv run --project . --with pytest python -m pytest \
  tests/test_stock_daily_qfq_contracts.py \
  tests/test_stock_daily_qfq_checks.py \
  tests/test_asset_governance_contracts.py \
  tests/test_run_contract_static_gates.py
```

结果：`93 passed`。测试只使用临时目录、本地 DuckDB 和静态扫描，不运行 `dg`，不读取正式 Dagster instance，不触碰正式数据湖。

### P3: Daily Job And Sensor

状态：已完成。

落地文件：

- `lake_console/orchestrator/src/orchestrator/defs/jobs/stock_daily_qfq_update.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/stock_daily_qfq_sensor.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/readiness.py`
- `lake_console/orchestrator/tests/test_stock_daily_qfq_readiness_selector.py`
- `lake_console/orchestrator/tests/test_stock_daily_qfq_sensor_contracts.py`
- `lake_console/orchestrator/tests/test_run_contract_static_gates.py`

已落地口径：

1. `gold_stock_daily_qfq_update_job` 只选择 `gold_stock_daily_qfq` asset 与其 ordinary checks，不包含 repair op、报告逻辑或 SQL。
2. `gold_stock_daily_qfq_update_job_sensor` 默认 `STOPPED`，`minimum_interval_seconds=600`，资源依赖为 `lake_root` / `duckdb`。
3. sensor 使用 `silver_trade_calendar` 读取最近 10 个 `cn_a_stock_trade_days` expected dates，先拦截 registered gap，再用 bounded readiness selector 选择 first not-ready partition。
4. selected date 上只检查 `silver_stock_daily` 与 `silver_adj_factor` upstream readiness；output materialized 但 checks 未绿时 skip，不自动重跑。
5. run request 经 `build_run_request(...)` 和 `build_asset_update_run_key(...)` 生成，run key 为 `gold_stock_daily_qfq_update:{trade_date}`。
6. cursor 使用 `build_sensor_cursor(...)`，只写小型结构化 payload 和 ASCII `reason_code`。

P3 验证：

```bash
cd lake_console/orchestrator
PYTHONPATH=src uv run --project . --with pytest python -m pytest \
  tests/test_stock_daily_qfq_readiness_selector.py \
  tests/test_stock_daily_qfq_sensor_contracts.py \
  tests/test_stock_daily_qfq_contracts.py \
  tests/test_stock_daily_qfq_checks.py \
  tests/test_run_contract_static_gates.py
```

结果：`95 passed, 94 warnings`。测试只使用本地临时目录、静态扫描和 fake instance，不运行 `dg`，不读取正式 Dagster instance，不触碰正式数据湖。

### P4: Repair Core

状态：已完成。

范围：

- repair config
- affected code detection
- effective range
- rewrite logic
- protected status check
- repair run-status sensor
- upstream-triggered run key / completion status tests
- repair tests

落地文件：

- `defs/stock_daily_qfq.py`：repair plan、affected code diff、effective range、repair rewrite、protected status check metadata。
- `defs/run_contracts/configs.py`：`GoldStockDailyQfqFactorRepairConfig` 与 `build_gold_stock_daily_qfq_factor_repair_run_config(...)`；config 只包含 `qfq_factor_trade_date`、`repair_required_codes_hash`、`upstream_batch_id`。
- `defs/ops/gold_stock_daily_qfq_factor_repair.py`：repair op，读取 expected calendar，执行 scoped repair，并写 `gold_stock_daily_qfq_factor_repair_plan_evaluated` check。
- `defs/jobs/gold_stock_daily_qfq_factor_repair.py`：`gold_stock_daily_qfq_factor_repair_job`。
- `defs/sensors/gold_stock_daily_qfq_factor_repair_job_sensor.py`：监听 `gold_stock_daily_qfq_update_job` 成功 run 的 run-status sensor。
- `defs/asset_guards/stock_daily_qfq_factor_repair.py`：repair status helper，按 partition + upstream batch 校验 protected check metadata，不读旧 storage id。
- `tests/test_stock_daily_qfq_repair_contracts.py`、`tests/test_stock_daily_qfq_factor_repair_sensor_contracts.py`、`tests/test_run_contract_configs.py`、`tests/test_run_contract_static_gates.py`：repair core、run config、run-status sensor 与静态门禁。

验证：

```bash
cd lake_console/orchestrator
PYTHONPATH=src uv run --project . --with pytest python -m pytest \
  tests/test_stock_daily_qfq_contracts.py \
  tests/test_stock_daily_qfq_checks.py \
  tests/test_stock_daily_qfq_sensor_contracts.py \
  tests/test_stock_daily_qfq_repair_contracts.py \
  tests/test_stock_daily_qfq_factor_repair_sensor_contracts.py \
  tests/test_run_contract_configs.py \
  tests/test_run_contract_static_gates.py
```

结果：`110 passed, 94 warnings`。测试只使用本地临时目录、静态扫描和 fake instance；未运行 `dg`，未读取正式 Dagster instance，未触碰正式数据湖。

### P5: Bootstrap Dry-Run

状态：已完成。

范围：

- bootstrap CLI dry-run
- sample partition build
- performance report

不做正式全量写入，除非单独审批。

落地文件：

- `defs/bootstrap/gold_stock_daily_qfq_history.py`：历史 bootstrap plan、输入分区发现、sample 生成 helper。
- `defs/bootstrap/gold_stock_daily_qfq_history_cli.py`：`profile-history` 与 `write-sample` CLI，默认只读，`--apply` 才写 sample。
- `tests/test_stock_daily_qfq_history.py`：dry-run 不写目标文件、sample 写入、skip existing、CLI JSON report。
- `tests/test_run_contract_static_gates.py`：bootstrap helper/CLI 禁止写 Dagster event、禁止读 Dagster instance。

验证：

```bash
cd lake_console/orchestrator
PYTHONPATH=src uv run --project . --with pytest python -m pytest \
  tests/test_stock_daily_qfq_history.py \
  tests/test_stock_daily_qfq_contracts.py \
  tests/test_run_contract_static_gates.py
```

结果：`85 passed, 32 warnings`。

组合回归：

```bash
cd lake_console/orchestrator
PYTHONPATH=src uv run --project . --with pytest python -m pytest \
  tests/test_stock_daily_qfq_contracts.py \
  tests/test_stock_daily_qfq_checks.py \
  tests/test_stock_daily_qfq_sensor_contracts.py \
  tests/test_stock_daily_qfq_repair_contracts.py \
  tests/test_stock_daily_qfq_factor_repair_sensor_contracts.py \
  tests/test_stock_daily_qfq_history.py \
  tests/test_run_contract_configs.py \
  tests/test_run_contract_static_gates.py
```

结果：`116 passed, 122 warnings`。测试只使用临时目录、静态扫描和 fake instance；未运行 `dg`，未读取正式 Dagster instance，未触碰正式数据湖。

### P6: Historical Bootstrap And Runless Event Backfill

状态：代码工具已完成；正式 lake 写入与正式 runless event 写入已在用户批准后执行至 `2026-06-25`。

范围：

- full file bootstrap
- full-history runless materialization event backfill
- recent 20 + latest runless ordinary check event backfill
- post-bootstrap readiness verification

正式写入必须单独审批；2026-06-27 用户批准后已执行一次正式写入。

落地文件：

- `defs/bootstrap/gold_stock_daily_qfq_history_cli.py`：新增 `build-history` stage，默认 dry-run，`--apply` 才执行 full selected partition 文件写入。
- `defs/bootstrap/gold_stock_daily_qfq_history_events.py`：runless event plan/report helper；materialization event 全历史，ordinary check event 只覆盖最近 20 个 `cn_a_stock_trade_days` 与 latest partition。
- `defs/bootstrap/gold_stock_daily_qfq_history_events_cli.py`：`plan-events` 与 `report-events` CLI；默认 dry-run，`--apply` 才写 Dagster runless events。
- `tests/test_stock_daily_qfq_history.py`：`build-history` 默认 dry-run 不写文件。
- `tests/test_stock_daily_qfq_history_events.py`：event plan、dry-run 不写事件、临时 instance apply、check audit failure 阻断。
- `tests/test_run_contract_static_gates.py`：event helper/CLI 不注册 active definitions，ordinary check event 窗口固定 recent 20 + latest。

runless event 写入规则：

1. materialization event 可覆盖 full history target partitions，但只记录已存在且可读取 row count/observed columns 的 `gold_stock_daily_qfq` 文件。
2. P8 前 ordinary check event 默认只覆盖最近 20 个 `cn_a_stock_trade_days` 与 latest partition；P8 后只补 retained contract check event。
3. P8 前 ordinary check event 写入曾要求通过 `gold_stock_daily_qfq_contract_check` 与 `gold_stock_daily_qfq_qfq_semantics_check` 等价审计；P8 后删除 qfq semantics event backfill，只保留 contract event backfill，并只用文件结构 contract 验收、显式 as-of 重建记录和旧错误文件/event 清零后的重建事实作为验收依据。
4. 已 ready 的 recent check partition 默认跳过，避免重复写 event。
5. helper/CLI 不读取旧 storage id 字段，不写 `event_storage_id`，不解析 run key，不新增 Dagster asset/job/sensor/check。

验证：

```bash
cd lake_console/orchestrator
PYTHONPATH=src uv run --project . --with pytest python -m pytest \
  tests/test_stock_daily_qfq_history.py \
  tests/test_stock_daily_qfq_history_events.py \
  tests/test_stock_daily_qfq_contracts.py \
  tests/test_run_contract_static_gates.py
```

结果：`91 passed, 72 warnings`。

组合回归：

```bash
cd lake_console/orchestrator
PYTHONPATH=src uv run --project . --with pytest python -m pytest \
  tests/test_stock_daily_qfq_contracts.py \
  tests/test_stock_daily_qfq_checks.py \
  tests/test_stock_daily_qfq_sensor_contracts.py \
  tests/test_stock_daily_qfq_repair_contracts.py \
  tests/test_stock_daily_qfq_factor_repair_sensor_contracts.py \
  tests/test_stock_daily_qfq_history.py \
  tests/test_stock_daily_qfq_history_events.py \
  tests/test_run_contract_configs.py \
  tests/test_run_contract_static_gates.py
```

结果：`122 passed, 162 warnings`。测试只使用临时 lake、ephemeral Dagster instance、静态扫描和 fake instance；未运行 `dg`，未读取正式 Dagster instance，未触碰正式数据湖。

正式执行记录（2026-06-27）：

1. preflight：正式 Dagster Postgres active runs 为 0。
2. 初始 `profile-history` 显示 `2014-01-02` 到 `2026-06-26` 可见输入文件，但 `write-sample[2026-06-26]` 被 writer 拦截；只读审计确认 `silver_stock_daily[2026-06-26]` 中 `001399.SZ / N惠科股份` 暂缺同日 `silver_adj_factor`。该日期未写入 `gold_stock_daily_qfq`，避免生成输入事实不完整的文件。
3. 调整正式 bootstrap 范围为 `2014-01-02` 到 `2026-06-25`；row-level same-day adj factor 覆盖审计缺口数为 0。
4. sample 写入 `2026-06-25` 成功：`source_row_count=5511`，`output_row_count=5511`，`missing_previous_row_count=0`；P8 只读事故复盘确认这类 self-as-of 等价审计不能证明历史前复权结果正确。
5. full `build-history --apply --end-date 2026-06-25` 成功：selected partitions `3032`，written `3031`，skipped existing sample `1`，elapsed `70527.69ms`。
6. post-profile：`existing_target_file_count=3032`，`planned_write_count=0`，`missing_input_count=0`。
7. runless event plan 使用显式 recent20 check partitions（`2026-05-28` 到 `2026-06-25`），避免默认交易日历未来日期进入 check window。正式 `report-events --apply` 写入 materialization events `3032`、ordinary check partitions `20`、ordinary check events `40`，合计 `3072` events；P8 必须先删除这些旧 ordinary check events，再按 retained contract check 口径重新补录。
8. post-plan：`planned_materialization_event_count=0`，`planned_check_event_count=0`，`failed_check_partition_count=0`，`existing_materialized_partition_keys=3032`，`existing_ready_check_partition_keys=20`。
9. readiness 抽查：`2026-05-28` 与 `2026-06-25` ready；`2026-06-26` 未 materialized，状态为 `gold_stock_daily_qfq has no materialization`。

### P7: Documentation Closeout

范围：

- 更新高层设计文档状态。
- 更新 asset schema contract / onboarding index 如需要。
- 更新 performance governance 的新增数据集样例或 check count。

状态：已完成。

P7 文档对账结果：

1. `dagster-stock-daily-qfq-asset-design.md` 已更新状态为 P1-P7 已完成；正式全量 lake 写入与正式 runless event 写入仍保留单独审批门禁。
2. `dagster-asset-schema-contract-design.md` 已按当前 `LAKE_ASSET_CATALOG` 代码事实更新：active catalog entries 为 58，除 `lake_root_health` 外 57 个 table-like / serving assets 均有 definition column schema；`gold_stock_daily_qfq` 已纳入 gold 日频资产覆盖范围。
3. `dagster-data-pipeline-performance-governance.md` 是通用性能规范，本专项没有新增需要写回的通用规则；性能口径仍以本 LLD 的 P5/P6 dry-run、runless event 和 sensor 热路径限制为准。

### P8: Bootstrap As-Of Semantics Fix And Rebootstrap

状态：已完成。P8 是 2026-06-27 只读审计发现的专项修复阶段，不属于 P1-P7 的自然收口项；正式删除、重建、runless event 补录和 MA250 报告重算已在 2026-06-28 收口。

P8 完成后的目标状态：

- `gold_stock_daily_qfq` lake 文件全部按同一个明确 `bootstrap_as_of_trade_date` 从零重建。
- P6 旧 self-as-of 文件和旧 materialization / ordinary check events 不再作为 current 状态存在。
- ordinary readiness 只依赖 `gold_stock_daily_qfq_contract_check`。
- `gold_stock_daily_qfq_qfq_semantics_check` 不再作为 active blocking check、runless event、readiness、catalog blocking 或 bootstrap 证明。
- P8 不再证明“公式正确性”；只验收文件结构 contract、显式 as-of 重建记录、旧错误文件/event 清零和新 runless event 补录这些执行事实，不写入公式类 Dagster check event，也不做固定样本或聚合公式验收。

#### P8.1 修复目标

修复 `gold_stock_daily_qfq` 历史 bootstrap 的 as-of 语义：

- 历史 bootstrap 必须直接生成“截至 bootstrap as-of 交易日”的完整前复权历史序列。
- bootstrap as-of factor 必须按 `ts_code` 从 `silver_adj_factor` 历史中取 `trade_date <= bootstrap_as_of_trade_date` 的最后一条记录。`000638.SZ`、`688287.SH` 这类已退市股票在 `2026-06-26` 没有同日 factor 是正常事实，应分别使用其最后可用 factor，而不是停止重建。
- 不采用“先按每天 self-as-of 生成，再逐日 replay repair”的初始化方式。
- P6 已写入的 self-as-of 历史文件必须先删除，再按正确 as-of 从零重新生成；不得在旧错误文件上 patch。
- P6 已写入的 runless materialization / ordinary check event 必须先删除，再按新文件事实重新规划和补录；不得让旧错误 event 留在 current 状态里。
- P8 不再补录 `gold_stock_daily_qfq_qfq_semantics_check`，也不把它作为 readiness 阻断项；P8 不再保留任何公式正确性 ordinary check。
- 修复完成前，`gold_stock_daily_qfq` 不得作为 MA250 报告、研究报告或其它 current-as-of 历史消费的数据源。

#### P8.2 代码改动范围

只允许触碰以下范围：

- `defs/bootstrap/gold_stock_daily_qfq_history.py`
  - `plan_gold_stock_daily_qfq_history(...)` 增加 `as_of_trade_date` / `bootstrap_as_of_trade_date`。
  - `generate_gold_stock_daily_qfq_history(...)` 增加必填 `as_of_trade_date`，并传给 `write_gold_stock_daily_qfq_partition(...)`。
  - `generate_gold_stock_daily_qfq_history(...)` 必须在单次 bootstrap 执行中用 DuckDB 生成临时 effective as-of factor snapshot：每个 `ts_code` 一行，取 `trade_date <= bootstrap_as_of_trade_date` 的最后可用 factor。该 snapshot 只是执行期工作表，不新增 lake 实体、不新增 Dagster asset。
  - plan/report 输出 `bootstrap_as_of_trade_date`、as-of factor path、selected partition count、planned rewrite count。
- `defs/bootstrap/gold_stock_daily_qfq_history_cli.py`
  - `build-history --apply` 必须要求 `--as-of-trade-date`。
  - dry-run / sample / full report 都必须写入 as-of 口径。
  - P8 正式重建前必须提供 delete/reset dry-run：列出即将删除的 `gold_stock_daily_qfq` 目标文件，不允许匹配其它 lake 路径。
- `defs/bootstrap/gold_stock_daily_qfq_history_events.py`
  - runless materialization metadata 增加 `qfq_as_of_trade_date`。
  - runless ordinary check event 只规划 retained contract check。
  - 旧 self-as-of materialization/check event 不得被继续视为正确事件；P8 必须提供只读 dry-run 统计和显式 apply 删除路径。
- `defs/bootstrap/gold_stock_daily_qfq_history_events_cli.py`
  - `plan-events` / `report-events` 增加 `--as-of-trade-date`。
- `defs/bootstrap/gold_stock_daily_qfq_history_reset_cli.py` 或等价邻近 CLI
  - dry-run 输出 old lake file candidates、old materialization events、old ordinary check events、latest/protected/runs/dynamic partition 安全断言。
  - `--apply` 前必须要求显式确认参数、active runs = 0、备份路径或确认记录。
  - `--apply` 必须显式二选一：`--delete-lake-files` 或 `--delete-dagster-events`。lake 文件删除与 Dagster event 删除必须作为两个单独审批步骤执行，不允许一个命令同时跨文件系统和 Dagster DB 删除。
  - 删除范围只允许 asset key `gold_stock_daily_qfq`，不删除 runs、run_tags、dynamic_partitions、instigators、其它资产事件或 protected repair status event。
- `defs/checks/stock_daily_qfq_checks.py`
  - 删除或彻底取消注册 `gold_stock_daily_qfq_qfq_semantics_check`，不得继续作为 active asset check definition。
  - active definitions、catalog、readiness、runless event plan 不得再依赖它。
  - 不新增替代性的公式正确性 check，也不把固定样本、聚合差异或其它公式复算包装成验收项。
- 测试：
  - `tests/test_stock_daily_qfq_contracts.py`
  - `tests/test_stock_daily_qfq_history.py`
  - `tests/test_stock_daily_qfq_history_events.py`
  - `tests/test_stock_daily_qfq_history_reset.py`
  - `tests/test_run_contract_static_gates.py`

不改：

- 不改 `gold_stock_daily_qfq_update_job` 的 run key / job 名称 / sensor 名称。
- 不开放手写 `stock_codes`。
- 不新增细粒度 Dagster checks。
- 不用旧 storage id，不解析 run key。
- 不在 P8 里改 MA250 报告逻辑；报告必须等 qfq 文件修复验收后再重算。

#### P8.3 本地测试计划

必须新增或更新以下测试：

1. writer / bootstrap：
   - `build-history` 必须显式传入 `as_of_trade_date`，并把该值写入 plan/report metadata。
   - `build-history --apply` 未传 `--as-of-trade-date` 时失败。
   - `build-history --apply --as-of-trade-date 2026-06-26` 时，writer 调用链必须使用该 as-of；测试不做公式正确性验收。
   - 历史分区包含已退市股票，且该股票在 bootstrap as-of 当天没有 factor、但在 as-of 之前有最后可用 factor 时，bootstrap 必须用最后可用 factor 生成该分区，不得误报 missing as-of factor。
2. check / audit：
   - `GOLD_STOCK_DAILY_QFQ_CHECK_NAMES` 只保留 `gold_stock_daily_qfq_contract_check`。
   - readiness specs、catalog blocking checks、checks-only job 只要求 retained contract check。
   - runless event plan/report 不生成 `gold_stock_daily_qfq_qfq_semantics_check`。
3. bootstrap formula validation 禁止项：
   - 不新增固定样本公式验收。
   - 不新增公式正确性 check 或公式级聚合对账 helper。
   - 不复用 qfq semantics check helper。
   - P8 测试只覆盖 as-of 参数链路、reset/delete 范围、结构性 contract 和 runless event 补录口径。
4. reset / delete：
   - dry-run 候选只包含 `gold_stock_daily_qfq` lake path 和该 asset 的 materialization / ordinary check event。
   - 删除 old event 不触碰 runs、run_tags、dynamic partitions、其它资产事件、protected repair status check。
   - apply 缺确认参数时失败。
5. static gates：
   - bootstrap apply 路径禁止省略 `as_of_trade_date`。
   - runless event helper 禁止生成 qfq semantics ordinary check event。
   - readiness / catalog 禁止重新加入 `gold_stock_daily_qfq_qfq_semantics_check`。
   - active check definitions 禁止重新注册 `gold_stock_daily_qfq_qfq_semantics_check` 或其它公式正确性 ordinary check。

本地验证命令：

```bash
cd lake_console/orchestrator
PYTHONPATH=src uv run --project . --with pytest python -m pytest \
  tests/test_stock_daily_qfq_contracts.py \
  tests/test_stock_daily_qfq_history.py \
  tests/test_stock_daily_qfq_history_events.py \
  tests/test_stock_daily_qfq_history_reset.py \
  tests/test_run_contract_static_gates.py
```

#### P8.4 正式数据恢复步骤

正式恢复必须单独审批，且每一步都先 dry-run：

1. 停止把 `gold_stock_daily_qfq` 用作报告源。
2. 选择并记录 bootstrap as-of trade date：
   - 本次 P8 按用户确认口径固定使用 `2026-06-26`。
   - 目标 as-of 的 `silver_adj_factor` 分区必须存在；对每只股票的 as-of factor 使用不晚于该日期的最后可用 factor。已退市股票 as-of 当天缺同日 factor 不属于缺口。
   - 如果 selected source code 在 as-of 之前完全找不到 factor，必须停止，不能生成。
   - 如果 as-of 变更，必须单独拍板；P8 执行期不动态推导 as-of，也不通过公式样本重新证明 as-of。
3. 只读审计当前 lake：
   - 统计 `gold_stock_daily_qfq` 与 `silver_stock_daily` 完全相等的分区数量。
   - 该只读确认只用于说明旧文件属于 self-as-of 事故范围，不作为新文件公式验收。
4. 只读 dry-run 旧文件删除清单：
   - 候选只允许位于 `gold/quote/stock_daily_qfq/trade_date=*/part-000.parquet`。
   - 输出待删分区数、文件数、总字节数、样本路径。
   - 候选为 0 或包含其它路径时停止。
5. 只读 dry-run 旧 Dagster event 删除清单：
   - 候选只允许 asset key `gold_stock_daily_qfq` 的旧 materialization / ordinary check event。
   - 不删除 runs、run_tags、dynamic_partitions、instigators。
   - 不删除 protected repair status check。
   - 输出 latest collision、protected collision、其它 asset collision；任一非 0 停止。
6. 备份：
   - lake 删除前必须有文件清单和可恢复备份/快照策略。
   - Dagster DB 删除前必须有 Postgres 备份并验证可读。
7. 经审批后用 `apply --delete-lake-files --confirm-reset --backup-path <...>` 删除旧 `gold_stock_daily_qfq` lake 文件。
8. 经审批后用 `apply --delete-dagster-events --confirm-reset --backup-path <...>` 删除旧 `gold_stock_daily_qfq` Dagster materialization / ordinary check events。
9. 执行 `profile-history --as-of-trade-date <bootstrap_as_of_trade_date>`，确认：
   - selected partition 范围。
   - planned rewrite count。
   - missing input count 为 0。
   - expected row count / file count 在预算内。
10. 执行 sample build：
   - 先选一个历史分区样本，确认命令、写入路径和结构性 contract 可用。
   - 不验证 qfq close 公式结果，不把样本公式复算作为验收门槛。
11. 执行 full `build-history --apply --as-of-trade-date <bootstrap_as_of_trade_date>`。
12. 写后文件验收：
   - row count / schema 全部通过。
   - 文件结构 contract 验收通过。
   - 不抽查公式计算样本，不做公式正确性验收。
13. 重新规划 runless events：
   - materialization event 全历史，metadata 包含 `qfq_as_of_trade_date`。
   - ordinary check event 只补 retained contract check 的 recent 20 + latest。
   - 先 `plan-events` dry-run，确认旧 self-as-of event 已清空且不会被当作当前正确状态。
14. 经审批后执行 `report-events --apply`。
15. post-plan / readiness 验收：
   - recent 20 + latest ready。
   - protected repair status 不受影响。
   - Dagster DB event 增量符合预算。
16. 重新生成 MA250 报告；报告生成只作为下游消费恢复动作，不作为公式正确性验收。

#### P8.5 性能门禁

P8 不允许通过逐日 replay repair 初始化历史，因为这会把初始化复杂度放大成“复权因子变化日 × 历史分区”的模型，并制造大量 repair metadata。

正式路径必须满足：

- 文件重写按 selected partition 分批，使用 DuckDB set-based SQL。
- effective as-of factor snapshot 只能在每次 bootstrap 执行开始时生成一次，禁止在每个历史分区里重复全量扫描 `silver_adj_factor`。
- 单分区写入仍是一个 `trade_date` 文件，不改物理布局。
- Python 只负责批次编排和报告，不逐行处理行情数据。
- runless ordinary check event 只补 retained contract check 的 recent 20 + latest，不补全历史 ordinary checks，不补 qfq semantics check，也不新增任何公式正确性 check。
- 如果 full rewrite 发现输入缺口、文件结构 contract 验收失败或耗时超预算，停止并重新设计，不允许先报绿。

#### P8.6 正式执行记录

正式执行结果（2026-06-27 至 2026-06-28）：

1. preflight：正式 Dagster Postgres active runs 为 0。
2. reset dry-run：
   - 报告：`/private/tmp/gold_stock_daily_qfq_p8_reset_dry_run_20260627.json`
   - old lake file candidates：`3033`
   - old materialization candidates：`3033`
   - old ordinary check candidates：`40`
   - `should_stop=false`
3. 备份：
   - Dagster Postgres：`/private/tmp/goldenshare_dagster_gold_stock_daily_qfq_p8_20260627.dump`
   - old lake files：`/private/tmp/gold_stock_daily_qfq_p8_lake_backup_20260627/`
4. 删除旧 lake 文件：
   - 报告：`/private/tmp/gold_stock_daily_qfq_p8_delete_lake_20260627.json`
   - deleted lake files：`3033`
   - 删除后正式 lake old file candidate count：`0`
5. 删除旧 Dagster events：
   - 报告：`/private/tmp/gold_stock_daily_qfq_p8_delete_events_20260627.json`
   - deleted materialization events：`3033`
   - deleted check events / executions：`40`
   - deleted materialization event tags：`1`
   - 不删除 runs、run_tags、dynamic partitions、其它资产事件或 protected repair status check。
6. full build：
   - 报告：`/private/tmp/gold_stock_daily_qfq_history_build-history_20260628_002919.json`
   - `bootstrap_as_of_trade_date=2026-06-26`
   - selected partitions：`3033`
   - written partitions：`3032`
   - skipped existing sample partition：`1`
   - elapsed：约 `67539ms`
   - 正式 lake 当前文件数：`3033`
   - 正式 lake 目录大小：约 `775M`
7. runless event backfill：
   - plan 报告：`/private/tmp/gold_stock_daily_qfq_history_events_plan-events_20260628_005022.json`
   - apply 报告：`/private/tmp/gold_stock_daily_qfq_history_events_report-events_20260628_005202.json`
   - materialization events reported：`3033`
   - retained contract check partitions：`20`
   - reported event count：`3053`
8. post-plan dry-run：
   - 报告：`/private/tmp/gold_stock_daily_qfq_history_events_plan-events_20260628_005659.json`
   - `qfq_as_of_trade_date=2026-06-26`
   - existing materialized partitions：`3033`
   - existing ready check partitions：`20`
   - planned materialization events：`0`
   - planned check events：`0`
   - failed check partitions：`0`
   - sample audits 只包含 `gold_stock_daily_qfq_contract_check`，不包含 `gold_stock_daily_qfq_qfq_semantics_check`。
9. MA250 报告重算：
   - 输出：`lake_console/docs/reports/stock_below_ma250_2026-06-26.csv`
   - 使用 `gold_stock_daily_qfq.close` 计算 250MA。
   - 数据行：`3652`
   - 已过滤名称包含 `ST`、以“退”开头或以“退”结尾的股票。
   - 报告重算是下游消费恢复动作，不作为公式正确性验收。

## 16. Stop Conditions

任一情况立即停止：

1. 发现 `silver_stock_daily` 与 `silver_adj_factor` 无法稳定表达日线前复权。
2. 发现必须改 `silver_stock_daily` schema 才能实现。
3. 发现需要报告逻辑才能验证本资产正确性。
4. 发现 daily update 必须读全历史。
5. 发现 repair 必须重写全市场全历史所有股票。
6. 发现必须新增大量细粒度 Dagster checks 才能表达 readiness。
7. 发现必须直接读取或写正式 Dagster runtime 才能完成代码阶段测试。
8. 发现必须使用旧 storage id 或解析 run key 反推 config。

## 17. Confirmed Decisions

以下口径已拍板，不再作为待确认项：

1. 上市首日或无 previous source row 时，`pre_close/change_amount/pct_chg` 统一写 0，不写 NULL。
2. repair 初版不开放手写 `stock_codes`；repair config、正式 CLI 参数和 sensor payload 都不得暴露股票池输入，affected codes 必须由 `silver_adj_factor` 相邻 expected trade date diff 自动计算。
3. repair 初版增加自动 run-status sensor；触发方式参考股票分钟线 MACD/KDJ repair：`gold_stock_daily_qfq_update_job` 成功后自动判断并提交 scoped repair job。

补充约束：

1. `0` 只用于无 previous source row；previous source row 存在但 previous factor 缺失时仍失败。
2. `stock_codes` 不得作为 repair config、正式 CLI 参数或 sensor payload 暴露；repair op 必须自行重算 affected codes 并校验 hash。
3. 自动 sensor 必须是 run-status sensor，只处理触发 run 的单个 `trade_date`，并受 affected code 上限、hash、completion/status 和性能门禁约束。
