# Dagster 股票日线前复权资产 Low-Level Design

> 2026-10-19当前状态：管理员已认可先完善回刷能力、再修历史数据。第19节记录方向，第20节为[代码级开发说明](#qfq-code-design-20261019)，已按本轮代码复核补充函数、配置、文件格式、SQL步骤、恢复分支、消费者迁移及测试。仍未开发或正式执行。第1—18节保留原建设记录；本次实施细节以第20节为准，不把设计冒充当前实现。
>
> 另一个[25股历史因子专项](./dagster-stock-adj-factor-history-repair-plan-v1.md)已于2026-10-18完成文件修复和DG登记，专用工具已清退，详见[专项LLD](./dagster-stock-adj-factor-history-repair-low-level-design-v1.md) §22—24。原“尚未实现”状态已失效。本次复用其完成证据，不恢复入口、不重跑、不修改原计划/hash。P8删除文件/事件也不作为本次授权或执行步骤。

## 1. Summary

本 LLD 细化 `gold_stock_daily_qfq` 的代码级落地方案。目标是在 gold 层新增一个基于 `silver_stock_daily` 与 `silver_adj_factor` 生成的股票日线前复权行情资产，供后续 MA250、日线指标、研究报告和其它下游消费。

本 LLD 只设计数据湖与 Dagster 资产能力，不纳入报告生成逻辑。报告改造后续单独推进。

原资产建设已确认的用户口径（本次拟改造项见第19节）：

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

以下为原建设阶段已拍板口径；本次对自动触发和范围推导的修订见第19节，其余仍适用：

1. 上市首日或无 previous source row 时，`pre_close/change_amount/pct_chg` 统一写 0，不写 NULL。
2. repair 初版不开放手写 `stock_codes`；repair config、正式 CLI 参数和 sensor payload 都不得暴露股票池输入，affected codes 必须由 `silver_adj_factor` 相邻 expected trade date diff 自动计算。
3. repair 初版增加自动 run-status sensor；触发方式参考股票分钟线 MACD/KDJ repair：`gold_stock_daily_qfq_update_job` 成功后自动判断并提交 scoped repair job。

补充约束：

1. `0` 只用于无 previous source row；previous source row 存在但 previous factor 缺失时仍失败。
2. `stock_codes` 不得作为 repair config、正式 CLI 参数或 sensor payload 暴露；repair op 必须自行重算 affected codes 并校验 hash。
3. 自动 sensor 必须是 run-status sensor，只处理触发 run 的单个 `trade_date`，并受 affected code 上限、hash、completion/status 和性能门禁约束。

## 18. 2026-07-16 因子生命周期版本错位防护

### 18.1 事故事实与根因

`gold_stock_daily_qfq_update_job[2026-07-16]` 的 run
`910ef350-eb28-4b07-b9a9-898fc5c1caf3` 在写入前失败。失败前没有覆盖或写入
`gold/quote/stock_daily_qfq` 文件。

当日事实如下：

| 时间 | 已发生的事实 |
| --- | --- |
| 01:39 | `raw_tushare_adj_factor[2026-07-16]` 已有 `920117.BJ` 的 `adj_factor=1.0`。 |
| 04:00 | `silver_adj_factor[2026-07-16]` 按当时的 `silver_stock_lifecycle` 快照生成，共 5,528 行，未包含该新股。 |
| 09:11 | `silver_stock_lifecycle` 刷新后新增 `920117.BJ / N龙鑫`，上市日为 2026-07-16。 |
| 09:22 / 09:32 | `raw_tushare_stock_daily` 与 `silver_stock_daily` 已有该股票当日行情。 |
| 09:41 | QFQ sensor 只看到较早的 `silver_adj_factor` materialization/check 仍为绿色，提交 QFQ run；writer 发现当日行情有 1 个代码找不到同日 factor 后失败。 |

根因不是 Tushare 缺数据，也不是 QFQ 公式错误。它是同一交易日内两份 silver 文件使用了不同版本的生命周期快照：因子文件较早、日线文件较晚；而 QFQ sensor 只读取 Dagster 的历史绿色状态，未核对现在落盘的两个输入文件是否仍相互覆盖。

审计同时确认：`silver_adj_factor_update_job_sensor` 的 batch lake readiness 已用当前
`silver_stock_lifecycle` 对 factor 文件做代码覆盖检查。因此它会把这类旧 factor 文件识别为
not-ready；但当文件已 materialized 时，通用连续性选择器会保守返回
`materialized_check_failed` 并使 sensor skip。该窄范围情况现已由 lifecycle fresh gate 与
安全 rebuild run 收口：只有 lifecycle 覆盖类失败、同日 raw 覆盖当前生命周期代码集合时才会
重建，其它失败仍严格 skip。本节的 QFQ 输入覆盖门禁仍是必要的最后保护；上游自动恢复职责由
`dagster-adj-factor-asset-design.md` 第 13 节的“生命周期日内刷新后的依赖顺序与安全重建方案”
定义。

### 18.2 目标、边界与失败语义

目标是在 QFQ sensor 提交 `gold_stock_daily_qfq_update_job` 前，确认目标交易日的
`silver_stock_daily` 每个代码都能在同日 `silver_adj_factor` 找到因子。该门禁只防止本节描述的“生命周期刷新后，日线与因子版本不同步”失败。

本节不承诺消除 QFQ writer 的所有其它前置失败。writer 仍保留 as-of factor、前序日 factor、输出行数和写后文件等完整 fail-closed 防线。

硬边界：

1. 不新增 asset、job、sensor、asset check、catalog entry、dynamic partition、run key 或 Dagster event。
2. 不改 `silver_adj_factor` asset、job、sensor、check、路径、schema、生命周期过滤或补数职责。
3. 不改 QFQ 公式、QFQ 文件布局、QFQ writer 的计算 SQL、分区、写入策略或 repair 逻辑。
4. 不写 lake、Dagster DB、prod DB；sensor 发现不一致时只 `skip`，不跨链路提交 adj factor run。
5. 不把公式比较放入 sensor 或 production check；公式正确性继续由受保护的金样本测试负责。本门禁只验证输入文件的代码覆盖事实。

失败语义：

| 条件 | sensor 行为 | cursor 口径 | 后续处理 |
| --- | --- | --- | --- |
| 两个文件都存在，日线代码全部有同日 factor | 保持现有 `RunRequest`，行为不变。 | `qfq_input_coverage.ready=true`。 | 执行既有 QFQ job。 |
| 任一输入文件不存在 | `skip`，不提交 QFQ run。 | `reason_code=upstream_qfq_input_coverage_not_ready`，`blocked_component` 指向缺失层。 | 等待对应上游文件/状态修复。 |
| 日线代码缺同日 factor | `skip`，不提交 QFQ run。 | 记录缺口数量和最多 5 个 `ts_code`。 | 等待上游 adj factor 链路：生命周期未 fresh 时等待 lifecycle；满足安全重建白名单时由 adj factor sensor 提交重建；否则人工修复。 |
| 同日 factor 有额外代码 | 不阻断。 | 只记录日线到因子的覆盖结论。 | QFQ 只要求日线输入可被 factor 覆盖。 |

### 18.3 实现设计

在 `defs/stock_daily_qfq.py` 新增稳定、只读的输入覆盖 helper：

```python
assess_stock_daily_qfq_trade_factor_coverage(
    *, connection, lake_root, trade_date, sample_limit=5
) -> StockDailyQfqTradeFactorCoverage
```

它只读取：

- `silver/quote/stock_daily/trade_date=<trade_date>/part-000.parquet`
- `silver/quote/adj_factor/trade_date=<trade_date>/part-000.parquet`

正常路径使用一条 DuckDB 聚合 SQL，显式只投影 `ts_code`、`trade_date`，输出：

- `source_row_count`
- `matched_row_count`
- `missing_trade_adj_factor_row_count`
- 两个输入文件是否存在
- 稳定的 `reason_code` 与 `ready`。

仅当覆盖失败时，额外运行一条按 `ts_code` 排序、`LIMIT 5` 的诊断 SQL。不得在成功路径读取样本，不得传递完整路径列表、完整 SQL、全量代码或 readiness 报告。

`gold_stock_daily_qfq_update_job_sensor` 的插入位置固定为：

1. 现有 gold QFQ 未 materialized 判断后；
2. 现有 `stock_daily_ready_for_trade_date(...)` 通过后；
3. 现有 `adj_factor_ready_for_trade_date(...)` 通过后；
4. 构造既有 `_gold_stock_daily_qfq_run_request_for_trade_date(...)` 前。

该顺序保留当前 Dagster readiness 为第一层门禁。只有历史状态已绿且 QFQ 确实待生成时，才读取两份当前 Parquet；所有既有 skip、run key、partition、job target 与 `MAX_RUN_REQUESTS_PER_TICK` 语义保持不变。

`_build_cursor(...)` 只增加紧凑的 `qfq_input_coverage` 摘要：`ready`、`reason_code`、两个行数、缺口数量、最多 5 个代码样本。顶层 cursor v1 contract 不变，失败时 `blocked_component=silver_adj_factor`；缺 stock daily 文件时为 `silver_stock_daily`；两个输入都缺失时为 `qfq_input_files`。

### 18.4 性能预算与拒绝策略

| 项 | 设计上限 | 说明 |
| --- | ---: | --- |
| 热路径执行时机 | 仅 QFQ 缺分区且两个 Dagster 上游已绿时 | 已 ready、交易日缺口、gold check 问题或上游 Dagster not-ready 时不执行。 |
| 读取日期 / 文件 | 1 日 / 2 个 Parquet | 只读目标交易日，不读前序 20 日，也不读生命周期文件。 |
| 读取列 | 2 列 | 只读 `ts_code`、`trade_date`，不读 OHLC、不计算 QFQ 公式。 |
| SQL 数 | 正常 1；失败最多 2 | 第二条仅用于 `LIMIT 5` 的人类可读诊断。 |
| 数据量基线 | 约 5,524 日线行 + 5,528 因子行 | 2026-07-16 真实事故日；复杂度为单日两文件线性扫描。 |
| 写入 | 0 | 无 lake、Dagster、数据库、cursor 以外状态写入。 |
| cursor | 正常/失败均不超过 2 KiB；硬上限 8 KiB | 样本严格限制为 5。 |
| 失败策略 | fail closed / skip | 不提交必然失败的 QFQ run，交给既有 adj factor 链路自然修复。 |

测试必须用临时 Parquet fixture 证明成功路径恰为一次聚合查询、失败路径最多追加一次样本查询，且没有前序日期循环、Dagster event/check history 扩展或 `duckdb.connect()` 进入生产代码。

### 18.5 精确改动点与测试

| 文件 | 改动 |
| --- | --- |
| `defs/stock_daily_qfq.py` | 新增小型 coverage result dataclass、两文件聚合 SQL builder 和只读评估 helper。保留 writer 的完整写前 guard。 |
| `defs/sensors/stock_daily_qfq_sensor.py` | 在既有两个上游 readiness 之后、RunRequest 之前调用 helper；coverage 不绿则 compact cursor + skip。 |
| `tests/test_stock_daily_qfq_contracts.py` | 验证正常覆盖、缺同日 factor、extra factor 不阻断、缺输入文件、样本上限与只投影身份列。 |
| `tests/test_stock_daily_qfq_sensor_contracts.py` | 验证两个 Dagster 上游已绿但实时 coverage 缺口时不提交 run；coverage 通过时原 run key / partition / job target 不变；上游未绿时不调用 helper。 |
| `tests/test_run_contract_static_gates.py` | 锁定 sensor 采用 coverage helper、无 `write_gold_stock_daily_qfq_partition` 调用、无 event-history 扩展和无大样本 cursor。 |
| 本 LLD、QFQ/adj factor 高层设计文档 | 记录 lifecycle-version skew 与最终职责边界。 |

本地验证只运行相关 unit/static tests 与 `git diff --check`。不运行 `dg check defs`，不运行正式 job/sensor/materialize/backfill，不访问或写入正式数据库和 lake。

### 18.6 实施验收

完成后必须满足：

1. 事故等价 fixture 中，Dagster 的两个 upstream status 都为 ready、但同日日线缺 1 个 factor 时，sensor 返回 `skip` 且没有 `RunRequest`。
2. cursor 能一眼说明“同日 adj factor 缺覆盖”、缺口数量和最多 5 个代码；不包含报告型 payload。
3. 覆盖一致时，sensor 的 run key、job target、partition key 与现状完全一致。
4. QFQ 不修改或替代 `silver_adj_factor` 的生命周期覆盖语义；其上游日内顺序与安全重建由
   `dagster-adj-factor-asset-design.md` 第 13 节独立治理。
5. 公式 SQL、gold 文件内容、asset/check 数量及 Dagster event 数量均不改变。

### 18.7 实施结果

代码已按本节完成：

1. `GoldStockDailyQfqTradeFactorCoverage` 与
   `assess_stock_daily_qfq_trade_factor_coverage(...)` 已在
   `defs/stock_daily_qfq.py` 落地；成功时只执行一条两文件聚合 SQL，缺口时才追加一条
   `LIMIT 5` 样本查询。
2. `gold_stock_daily_qfq_update_job_sensor` 已在两个既有 upstream Dagster readiness
   通过后、构造 RunRequest 前调用该 helper；缺覆盖会以
   `upstream_qfq_input_coverage_not_ready` 跳过，不写任何状态或文件。
3. cursor 只保留 coverage 摘要；已经绿色的 upstream readiness 不再重复写入 cursor。
4. 覆盖、空输入、文件缺失、extra factor、sensor skip/request、不调用前置 gate、查询次数、
   cursor 体积和静态边界均已由单元测试覆盖。

本地验证（不触发正式 Dagster）：

```bash
cd lake_console/orchestrator
uv run python -m unittest \
  tests.test_stock_daily_qfq_contracts \
  tests.test_stock_daily_qfq_sensor_contracts \
  tests.test_stock_daily_qfq_checks \
  tests.test_sensor_cursor_contracts \
  tests.test_run_contract_static_gates \
  tests.test_asset_governance_contracts
git diff --check
```

结果：128 tests 通过；`git diff --check` 通过。

<a id="qfq-repair-lld-20261019"></a>
## 19. 历史回刷和遗漏发现：初版实现方案（2026-10-19）

### 19.1 状态、依据和本轮边界

管理员已认可总体方向，并追加三项要求：已有审计尽量只做一次、遗漏能够发现或报错、错误历史应修尽修。
本节记录初版方向；代码实施细节已补入第20节。只修改方案、LLD并保存已有证据；不修改Python、配置、正式数据、事件或sensor状态。
本节对应[原方案第10节](dagster-stock-daily-qfq-asset-design.md#qfq-history-repair-20261019)，不另建同主题方案。

通用规则复用[性能治理规范](dagster-data-pipeline-performance-governance.md)、[编码规范](../../orchestrator/CODING_STANDARDS.md)、根与目录AGENTS。
Dagster依据为[普通sensor与cursor](https://docs.dagster.io/guides/automate/sensors)、[并发控制](https://docs.dagster.io/guides/operate/managing-concurrency)，以及当前安装的run-status筛选实现；不安装或升级依赖。
Tushare复权依据为[doc_id=146](https://tushare.pro/document/2?doc_id=146)，沿用已确认公式与此前实测，不重新请求五股样本。

源接口、价格字段、分区和正式Lake根不变。无新增资产、数据库表或状态资产；普通结构check继续只证明结构。
拟修改repair config、触发方式、完成metadata与对应消费者，实施前必须一起迁移并补齐测试，不保留两套活动合同。
过去的事件保留为历史证据；新消费者不能把旧事件直接认作本次完整历史已经验收。

### 19.2 已确认的事实和代码落点

[审计报告及17份证据](../../reports/stock_daily_qfq_audit_20261019/report.md)已持久保存，包含样本、运行来源和源端核验。
五股原因结论直接使用；缺少原Lake文件hash的限制也已写明，不能为弥补这一缺项重做原因审计。

| 当前事实 | 已查代码 | 本次需要改变的地方 |
| --- | --- | --- |
| 四次日更成功，但没有正式运行来源，未匹配监听器 | `defs/sensors/gold_stock_daily_qfq_factor_repair_job_sensor.py`及Dagster run-status来源筛选 | 核对未完成事项，不以成功运行来源为唯一入口 |
| 只比较某日与前一交易日因子，查不到旧遗漏 | `build_gold_stock_daily_qfq_factor_repair_plan` | 从已验收范围接续，合并待处理日期和发生更正的输入 |
| 回刷截止日等于触发日 | `execute_gold_stock_daily_qfq_factor_repair` | 发生原因日期与统一修复截止日分开，防止旧任务改回旧口径 |
| 日更writer默认按分区当天因子写 | `assets/stock_daily_qfq.py`、`write_gold_stock_daily_qfq_partition` | 新交易日正常生成；历史补跑必须显式遵守已有截止日 |
| 循环重写历史文件，最后返回汇总，再写完成检查 | `defs/stock_daily_qfq.py`、`ops/gold_stock_daily_qfq_factor_repair.py` | 候选、逐文件证明、提交前后进度、可恢复完成登记 |
| 完成身份以run、日期和股票hash为主 | `asset_guards/stock_daily_qfq_factor_repair.py` | 同时绑定输入版本、截止日、全部目标和已完成证明 |
| 写目标旁固定`.tmp`再replace | `_replace_parquet_from_query` | 候选移到规定staging、校验一次、正式写入者互斥 |
| 结构检查通过不代表历史回刷完成 | `checks/stock_daily_qfq_checks.py` | 保留结构合同，下游额外核对匹配的历史完成证据 |

CodeGraph已使用`codegraph_explore`、`codegraph_impact`分析执行与完成判断。
`gold_stock_daily_qfq_factor_repair_status`影响结果包括趋势通道日更sensor、回刷sensor与回刷op。
路径函数的CodeGraph结果未完整解析动态/SQL消费者，不能据此判断只有一个调用方；已用定向文本和源码补核：

- `assets/stock_daily_trend_channel.py`：直接读QFQ，生成结果和递推状态；其回刷op与sensor消费QFQ完成信息。
- `qfq_nineturn.py`：读取QFQ上下文和历史，生成日九转；目前来源标识使用路径、大小、mtime，不能当作内容hash。
- `assets/stock_daily_qfq_nineturn_prod_core.py`：日九转可进入Prod serving；本次不执行该发布，修复维护期间必须协调其自动消费。
- `bootstrap/gold_stock_daily_qfq_history.py`：已有统一截止日和退市股票最后可用因子的历史生成办法，可复用其数学语义，不直接复用跳过已有文件作为验收。
- `bootstrap/qfq_nineturn_history.py`、趋势历史入口、历史事件工具和研究直接读文件：实现阶段核对接续/读取边界，不恢复已清退的25股工具。

相关调用与测试纳入迁移；没有证据证明日线还存在独立EMA/MACD正式资产，不按名称假设新增改造范围。
本次不改变`src/foundation/ops/biz/app`或QTF依赖矩阵，不导入Prod Ops承载Lake状态；Web/API字段不改。
直接绕过DG读Parquet的外部程序不能由sensor强制阻断，正式执行必须通过维护安排防止读到混合结果。

### 19.3 已有审计怎样复用

本次已保存的报告是审阅证据，不接入sensor。完整历史审计和正式执行各自在获批目录保存自己的计划与结果，不把仓库reports变成运行依赖。

| 证据 | 复用方式 | 何时补查 |
| --- | --- | --- |
| 五股根因、源样本和运行来源 | 直接引用，制作回归夹具时注明出处 | 只在相关代码语义改变或发现具体反证时核对对应部分 |
| 今年188日筛选证据 | 证明已覆盖日期与已有异常线索，不证明全历史总量 | 补全尚未覆盖日期、字段及股票，不重新跑筛选 |
| 已完成25股专项 | 引用原范围、输入/输出证明和完成记录，不改原hash、不重新下载 | 新输入、目标变化或新错误落在原证明外时，只处理相应差异 |
| 本次后续完整历史审计 | 每完成一批保存范围、源/目标内容标识、方法版本、通过/异常/未知清单 | 仅变化文件、增加范围或实质规则改变时局部失效 |
| 候选验证和已提交文件 | 复用同计划下已保存证明和输出身份 | 真实不一致或证据损坏才重验，不因取消/重启重新计算 |

不设置按小时/天自动过期，也不因换阶段、换进程重复验证稳定数据。
保留原证据，补查形成追加结果并标明替代范围，不能覆盖旧报告或混用不同截止日的通过数量。
证据索引不能访问、损坏或不含所需字段时，写清缺项和受影响范围，不默默全量重跑。

### 19.4 一次完整历史审计的输入与结果

读取范围以正式股票日线资产已有批准历史覆盖、SSE开市日历及`silver_stock_lifecycle`为依据，包含退市和北交所；
不用当前上市快照、ST过滤、名称过滤或因子相邻INNER JOIN得到的集合代替全部历史股票。
同时核对实际源行情键与目标键的差异，避免缺整个文件或缺某股被集合筛选掩盖。
没有报价不自动解释为合法停牌；按现行生命周期/停牌合同区分合法空缺和输入问题。

主要数据集为`silver_stock_daily`、`silver_adj_factor`、`gold_stock_daily_qfq`，日历和生命周期作为范围依据。
Raw只在已有证据不能解释具体Silver缺项时定点读取；本版不安排再次下载全市场Tushare或重新审计所有Raw。
需要扩大到Raw/源站的具体问题，先形成精确清单和读取预算。

采用日期批次、列投影和DuckDB集合计算。输入身份在首次必要读取时取得并复用，禁止每股再扫一次全历史。
对已有合格范围直接复用其证明，其余范围按以下事项完成一次检查：

1. 交易日、源/目标文件、股票行情键是否齐全；不存在的分区也必须出现在结果中。
2. 相同股票历史是否统一使用固定截止日的因子，旧/新因子是否混用；不能只靠K线跳空发现错误。
3. 价格四字段、昨收/涨跌额/涨跌幅，以及量额保留是否符合既有合同。
4. 上一行情取该股上一实际源行。历史批次使用已排序实际行和必要批前上下文，不能只取市场前一日。
5. 缺因子、重复键、非有限数或无法确定的范围分别记录，不用0、删行或取第一条掩盖。

离线比较实现独立于生产writer的expected生成，不调用生产helper计算expected后再比较自己；
小型字面样本和五股真实样本用来检验比较方法，普通运行不新增公式复算check。
浮点比较按现行DOUBLE运算误差设明确绝对/相对容差并写入方法版本；不得四舍五入到两位后掩盖基准差异。
精确容差在开发前以既有独立样本核定，不直接拿K线显示精度当数据合同，也不自动推翻25股专项已确认的精度保留口径。

每批输出：覆盖股票/日期/键数、源/目标文件标识、无需修改范围、错误字段与键、原因、缺输入/未知、推导的回刷范围和成本。
明细逐批写入执行证据，Python仅取汇总和有界样本；不得把全部明细常驻内存或塞入cursor。
总范围要能拆成已验证无需修改、需修复、尚未检查；这些集合不得重复计数。
完整审计未结束时只能称部分完成，不得先根据已发现错误集合宣布覆盖全部。

### 19.5 自动发现遗漏的入口

拟将既有`gold_stock_daily_qfq_factor_repair_job_sensor`改为普通、有界核对sensor，仍提交原repair job。
原run-status来源筛选不再承担必要触发；不新增第二个活动repair sensor，也不在daily job内写历史。
这是现有definition类型和cursor合同的变化，切换前保存旧状态并核对全部消费者；启停/重载需对应正式授权。
旧cursor只作历史证据，新cursor必须从本次已验收历史截止位置初始化，不能任取最近日期跳过更早事项。

拟定单tick合同如下，数值是初版设计预算，非已测结果：

| 项 | 初版选择 |
| --- | --- |
| 名称/目标 | 沿用现有sensor名称与`gold_stock_daily_qfq_factor_repair_job` |
| 分类 | 沿用`QUOTE_DATA / GOLD / ASSET_UPDATE`，通过现有helper；不新增动态分类tag |
| 最小间隔 | 600秒，与股票日线日更sensor对齐；不得据此承诺600秒内一定运行 |
| 默认状态 | 保持definition默认STOPPED；正式instance启用状态不由本轮文档修改 |
| 日期依据 | SSE expected dates与已验收范围；分区是否注册另行核对 |
| 每次工作量 | 最多10个从最早未完成日期起的日期、最多1个RunRequest、自动受影响股票上限仍为500 |
| 读取 | 同类materialization/check完成信息批量读；对应因子最多11个文件，一次集合比较，不逐日history深扫 |
| cursor | 已完成位置、核对位置、当前计划引用/摘要、失败原因；正常不超2KiB、硬上限8KiB，不存完整股票/文件清单 |
| 注册/写入 | 不注册分区，不写Parquet，不在sensor写完成check；由job完成无变化确认或实际回刷 |

核对顺序：

1. 检查正式根和时间条件，读取已验收范围与当前未完成计划的小型状态。
2. 有未结束任务先跟踪/恢复，不因后续日更成功跳过它；已提交、运行中、失败都不是完成。
3. 按日历挑选最早待核对范围，批量检查已批准上游/ordinary结构ready，不用文件存在冒充ready。
4. 有因子变化则合并股票，固定最新完整截止日；没有变化也由原job记录本范围已经核对。
5. 超限、缺输入、缺注册或证据不全时保留位置，cursor与UI显示具体原因、数量和下一步。
6. 全部目标及完成登记通过后才推进已完成位置。位置丢失时按已保存验收/完成记录重建；无法重建就阻断，不默认跳到今天。

每次最多10日是工作批次，不是只承认最近10日。超出日常预算的积压由离线任务分批处理，发现后持续显示未完成，不能进入成功状态。
运行去重与失败恢复分开：相同工作范围只有一个活动任务；失败不能因原run_key已使用就永久无法重试。
复用统一upstream-triggered/repair-attempt builder；工作身份由输入版本、截止日和范围确定，重试仍绑定同一工作计划。
不使用event storage id构造身份。具体重试参数及run config迁移须与run-key治理原方案/LLD一起核定后才能编码。

### 19.6 历史输入后来变化，怎样发现

只把已完成日期往前推进不能发现旧输入更正。本次必须同时具备两条发现依据：

1. 正式上游写入的materialization/发布记录改变，旧日期也重新加入核对；记录无变化不重复扫描行情。
2. 上游文件已替换但事件登记失败时，通过有界的目录/文件属性巡检发现实际变化。按日期分批轮转所有已纳入范围的输入和目标，下一轮继续，不能每次只扫最近日期。

巡检只列目录/路径、文件大小及更新时间等轻量属性；发现变化/新增/缺失才读取该文件内容并更新强标识。
路径/大小/mtime仅用于筛选变化，不能称为内容hash，也不能单凭它们补发成功。
首次完整审计或候选生成时取得的内容hash直接复用；同一次执行中稳定输入只建一次索引。
巡检已在20.11固定为每tick至多500日、按日期记录和实际属性轮转；批量事件API及真实查询模型见20.10，不再留作开发时选择。
轮转没有推进、完成状态损坏或文件变化来源不明时明确报错，保留受影响范围。
缺输入超过自动预算也不能skip后遗忘；无需自动修时仍有持续待处理状态。

对正常正式写入可通过发布与文件变化补漏；绕过所有正式入口、同时伪造原文件属性的修改不在轻量检查可证明范围内。
发现这类实际异常时仅检查对应文件，不能宣称无需读内容就能发现任意篡改；尚未同步到本地的源站更正由源链路负责。

### 19.7 修复计划、截止日和配置合同

拟在原repair入口内区分“发现变化的日期范围”和“实际使用的复权截止日”。
计划至少固定：来源证据、错误/待核对范围、受影响股票hash、输入版本、统一截止日、输出范围、原目标内容标识、实现版本、预计开销和逐文件清单。
执行参数来自显式config与受控计划，不解析run_key，不接受任意路径或运营手写stock_codes。
初稿中的三个字段扩展方式已由第20.3节替换：迁移为明确的action及计划引用，内部从计划推导股票、截止日和批次；不保留旧参数兜底。
日常计划自动推导；历史修复计划采用完整审计所得清单。两者共用同一计算、候选验证和恢复能力。

| 原因 | 价格范围 | 截止日规则 |
| --- | --- | --- |
| 因子变化遗漏、历史混用旧新基准 | 受影响股票全部有效历史至截止日，多个遗漏合并 | 固定最新完整截止日，逐股取不晚于它的最后可用因子 |
| 已发布历史源行情或因子更正 | 源更正实际影响行；昨收等延伸到下一实际行情；若分母变化则全历史 | 维持或推进已确认截止日，禁止倒退 |
| 历史补跑/缺分区 | 先纳入问题清单，按同一截止日补齐相应范围 | 不得重新默认按历史partition当天 |
| 已有合格输出、输入与口径都未变 | 无需重写，复用既有证明 | 不以新run_id强迫再算 |

退市/长停牌股票采用实际最后可用因子和上一实际行情。查找窗口不足时不能写合法0，须定点补上下文或报错。
候选生成使用现有统一公式；历史计算按股票实际行情一次排序接续，批前seed只读，不能每日期重复扫全历史。
源文件行被更正/删除/新增导致股票集合不变时，也要使旧计划失效；只用stock_codes hash或因子变化股票数作为身份不够。

### 19.8 候选、提升和续跑

正式输出仍为`/Volumes/datasource/data_lake/gold/quote/stock_daily_qfq/trade_date=.../part-000.parquet`。
计划、候选、验证结果和checkpoint只在`/Volumes/datasource/data_lake_staging`下本次运行目录保存；复用正式paths约束，不在正式Lake旁写固定.tmp，不引入Kopia或备份。
本初稿不新增跨数据集状态表/资产；这些文件只为获批历史执行与恢复服务。

执行顺序：

1. **准备一次。** 确认范围、挂载、权限、同文件系统、空间和唯一写入者，加载计划和已完成记录。固定输入/目标标识并建立批内索引；不每文件重验全计划。
2. **先识别成果。** 已有合格候选/完成记录先核对并复用，不先算完再发现文件存在。已知稳定输入的hash在本次执行中复用。
3. **生成候选。** DuckDB按日期批次计算受影响行，同一物理文件内合并所有本批股票。保留其他股票及量额，Python不处理行情明细。
4. **校验一次。** 检查schema、日期、键、源覆盖、允许修改范围和其他行双向EXCEPT ALL等守恒事实。保存实际结果、候选hash、原目标hash；不再用同公式重算一遍候选作证明。
5. **逐文件提升。** 先持久记录即将替换的文件及两种hash，再确认目标仍为原版本，执行os.replace，补记已完成。新候选内容已先验证；不声称跨文件整体原子。
6. **完成登记。** 汇总所有文件和未解决项，写匹配计划的完成metadata。状态登记失败不撤销已提交数据，保持未完成，恢复时只补缺失登记。

恢复只允许下列情况：目标仍是计划原文件，继续提升已验证候选；目标已是本计划输出，补记完成；目标是第三种内容，冲突停止。
若候选或证明损坏只处理该单元；不删除其他已完成文件、不重新生成整个候选集合。
mtime/大小只作便宜的变化提示；需要确认归属时读必要内容hash，不能用路径存在代替验证。
每文件/批次边界检查取消；长SQL使用现有可中断连接能力，停止后不领取新单元。正式实现前用隔离测试证明取消和两次持久记录之间的恢复。

同一日期文件包含多只股票，股票集合不同也会发生整文件覆盖冲突。
日更、回刷、历史CLI及手动入口必须共用一个经批准的写入协调方式；优先Dagster正式并发机制，不增加锁文件。
绕过队列的CLI不能假定受run并发限制保护，正式执行期间必须禁止其他QFQ写者；精确配置与入口约束在19.13补齐。

### 19.9 完成记录与下游

沿用`gold_stock_daily_qfq_factor_repair_plan_evaluated`作为protected完成说明，不新增同义check，不塞回ordinary readiness。
保留原字段有明确语义的部分，新完成记录须能证明：

- 本次计划/合同版本、输入版本、统一截止日、原因日期范围与工作身份匹配。
- 选定文件数 = 实际替换数 + 已验证无需替换数；未完成数和失败数都为0。
- 受影响股票/键范围可核对、逐文件证明完整；无变化也有核对范围与输入版本。
- 不存在已知更早未完成事项；计划或输出变化时，旧成功不能继续作为新结果成功。

完整文件清单只放执行证据，metadata保留计数、hash与受控引用；自动代码列表上限仍受500限制，cursor不携带明细。
历史成功事件仍可查看，但不满足新合同就不作为新完成证据；本次完整历史验收形成明确起点，避免要求为所有旧日期重补ordinary checks。
资产description、catalog写入/事件政策和metadata字段说明在开发时同步，价格schema不增加运行字段。

下游必须同时核对普通结构状态和本次匹配的历史完成状态。价格文件被修复后：

- 趋势通道结果与state从首个受影响处按真实seed接续至各自已有末端，不沿用受污染的递推状态。
- 日九转核对实际上下文/来源变化与计数接续，不仅看同日文件存在；同一比例调整是否影响其结果由现行算法与独立测试判定，不能先假设无需处理。
- DG下游未完成与价格未完成分别显示，不能用QFQ一次成功代表整条链成功。
- Prod/serving未在本次写权限内，先列受影响交付和协调暂停，不能顺手运行其sensor或发布job；需要修复时另列精确步骤。
- 全历史直读研究和报告在维护窗口结束前不消费本次混合结果；已导出报告由使用方按清单重算，不在本轮自动改写。

### 19.10 性能预算和拒绝条件

已有测量只证明2026年188个QFQ文件约63,204,586字节，筛选扫描约0.83秒；
它不包含全历史Silver读取、文件hash、候选生成、替换、恢复和下游接续，不能用作正式修复ETA。
五股/25条源核验、25股专项的耗时都只复用其自身范围，不重复测量或外推。

| 路径 | 数量/读取模型 | 初版预算和拒绝方式 |
| --- | --- | --- |
| 常规待处理核对 | 最多10日，最多11个因子文件；按asset/check类批量取状态 | 每tick最多1个请求；API每类最多1个有界页，页未取全保留位置；预算目标10秒，超过则停止本tick、不推进完成位置 |
| 旧文件变化巡检 | 只读文件属性，内容未变时不读行情 | 500日/≤1500个实际文件属性，执行记录≤8MiB，实际推进与容量验收见20.11、20.17 |
| 一次完整历史检查 | 历史N日，至多约3N份行情/因子/QFQ文件，加日历/生命周期；按既有合格证据扣减已覆盖范围 | 精确N、行数、列字节、hash成本和批次上限先用已有库存/计数估算；全局读获准后每批读取一次并保存结果，不跑第二条完整审计 |
| 修复 | K个受影响日期文件；计算只改受影响股票，整文件合并仍需读取保留行 | 一个文件只合并/验证一次；记录输入/输出字节、DuckDB内存和spill、候选峰值与剩余空间，未有上界不得正式执行 |
| 中断恢复 | 未完成单元及必要输入/输出身份核对 | 已完成单元业务计算/COPY为0；必要文件识别不等同于行情重算；恢复成本单列，不拿正常耗时替代 |
| 最后验收 | 汇总全部已保存覆盖/逐文件证明，补查不一致部分 | 完成集合无缺失；全历史业务重算/COPY为0，不逐分区扫描DG历史绿灯 |
| 源请求/事件 | 方案阶段0；日常无新源请求，离线只对具体源疑点另批 | 保留完成事件有界；不批量清理旧事件，不按历史文件逐条补ordinary checks |

正式执行单必须补实际规模、时间/空间预算、连接/SQL次数、事件数和上界；包括中断继续及最后验收。
内存/线程/spill使用当前受控DuckDB配置，不借文档增加配置；新增批次/巡检/并发参数先完成配置项审计。
进度报告当前阶段、实际文件/日期、已完成量、总量与最后更新时间，正常可见更新目标不超过30秒；未知ETA如实显示。
超预算、源变更、第三方覆盖、缺输入、校验失败、证明缺失都停止对应执行，不绕过或静默截断。

### 19.11 测试与真实验收

先列测试输入的独立来源、预期及替代边界，再运行隔离测试。测试不用正式instance、Lake、数据库或token。

| 必须证明的行为 | 正向与反向用例 | 现有落点/拟扩展 |
| --- | --- | --- |
| 本次真实遗漏能被补齐 | 正常来源成功被处理；无external origin成功、未进原回调也由新核对发现 | `test_stock_daily_qfq_factor_repair_sensor_contracts.py`，增加真实临时Dagster运行/事件夹具，不只调用内部函数 |
| 旧日期不被窗口丢弃 | 停机超过10日仍从最早未完成推进；更早缺输入不能跳过 | 原sensor契约测试与状态判断测试 |
| 无变化可完成，超限不能遗忘 | 无变化记录核对完成；>500、坏hash、空输入留待处理且说明原因 | 原repair/sensor契约测试 |
| 同股多次变化只修一次且不倒退 | 合并旧原因、统一新截止日；旧任务不得覆盖更晚结果；同截止日源更正不能被跳过 | `test_stock_daily_qfq_repair_contracts.py`、history测试 |
| 边界正确 | 退市最后因子、长停牌上一真实行、新上市合法0；有历史/缺因子不能伪造0 | `test_stock_daily_qfq_contracts.py`与独立字面金样本 |
| 审计与完成结果可以复用 | 同版同输入重复调用不重新业务扫描/计算；真实变化只使对应范围失效 | 审计/修复计数测试，来源为保存报告和临时Parquet |
| 中断不会漏文件或重复改写 | 候选完成后、rename前、rename后登记前、最终事件失败分别取消/恢复；第三种hash拒绝 | 原repair测试扩展；临时文件实际replace，不仅mock成功 |
| 不互相覆盖或误改 | 同日期不同股票仍禁止并发写；无冲突合法重复可复用；其他行与量额保留 | writer/并发入口与范围保持测试 |
| 历史更正能被发现 | 旧日期materialization变化；只有文件替换而无事件；巡检中断继续；来源未知报错 | 触发/巡检契约测试与读取次数门禁 |
| 下游不吃旧结果 | 修复未结束阻断；完成后趋势/state和九转正确接续；Prod发布不得自动夹带 | 对应下游契约测试，按实际改动选择 |
| 热路径与元数据有界 | SQL/文件/API次数、cursor上限、无历史深扫、无报告运行依赖 | `test_run_contract_static_gates.py`及针对性性能样本 |

验收顺序：必要小样本与故障测试→一条含取消/恢复的隔离修复链→批准范围的真实候选/提交→汇总完成证明。
同版完整链只跑一条，不另跑正常全链、续跑全链、audit全链各一遍。
新改动只重跑真正受影响测试；不为凑测试数重复耗时计算。
修复前用事故等价样本证明旧链路漏接/漏修，修复后证明同一问题被捕获；正常交易变化不能被误报成故障。
文档本轮只跑完整性、链接、证据hash与差异检查，不运行上述开发测试或正式DG。

### 19.12 分步交付和“没有遗漏”的判定

1. **本轮初稿。** 原方案、原LLD、持久审计证据齐全，已确认事实与拟改造分开。完成文档校验后交管理员评审。
2. **开发前补齐。** 只补19.13的代码/配置/成本依据，沿本节修改原文，不重复五股原因或25股专项审计。随后做方案与实现影响审查。
3. **能力开发。** 先实现待处理核对、统一截止日、可靠候选与恢复、完成身份及下游判断；完成必要隔离验收，不先改正式数据。
4. **完整历史审计。** 提交精确范围和成本，获准全局读取后按批检查一次。记录全部已覆盖、无需修改、需修改、未知和缺输入，形成完整修复清单。
5. **正式修复。** 在相应写入授权内，用新链路准备候选、必要样本、逐批提交、接续DG下游。保留已完成成果，中断后继续，不重建整份计划。
6. **汇总验收。** 应检查=无需修改+需修改+未检查；需修改=已修复验证+未解决。历史完成要求未检查/未解决均为0，所有文件证明齐全、下游状态分别明确。恢复日常接续时再核对下一日最小范围，不重审全历史。

若源输入缺失、原覆盖有缺分区或发现上游错误，登记具体范围并进入相应修复步骤；
不能为了只用现有回刷writer而把它们删出清单。超本次写入边界的事项需要精确补充步骤和授权，问题未解决时总体保持未完成。
无需修改的股票不强制重写；“应修尽修”要求覆盖全部问题，不要求无差别覆盖所有文件。

### 19.13 初版缺项的处理结果

原四项缺口已分别细化为第20节的参数/身份、队列准入、输入变化核对、SQL范围及下游接续规则。
后续开发必须按第20节的文件与函数清单执行，不能再用本节的流程描述代替代码设计。
完整历史的实际文件数、字节和执行耗时仍属于正式读取前的执行单，不伪造为已经测量；代码先具备明确批次、资源上界和越界拒绝规则。

<a id="qfq-code-design-20261019"></a>
## 20. 代码级开发说明（2026-10-19复核后补充）

### 20.1 实施依据和约束

[代码复核记录](../../reports/stock_daily_qfq_audit_20261019/code-review.md)保存本轮核实的函数行为及27份源码索引。
本节所有“新增/改为/删除”都是拟实施内容，当前Python未变。代码复核没有重新读取行情或正式DG数据库。

本次实施同时满足：

1. 数学公式只有一套；审计expected不调用这套生产公式。价格schema和Raw/Silver业务值不改。
2. 任何正式QFQ写入都走受控Dagster运行；历史CLI不能再直接覆盖正式根。
3. 先识别已完成成果，再计算；每个新完整候选只业务验证一次，最后汇总不重放。
4. 文件范围按物理日期合并；同日多股只COPY一个完整候选，不按股反复改同一文件。
5. 股票从源差异或审计结果推导；操作参数不接受stock_codes、任意SQL或任意文件路径。
6. 未完成、输入缺失、审计范围未覆盖均保留并阻断完成，不把它们从总数中滤掉。
7. Dagster事件失败不撤销已经提交的数据；提交前必要的执行记录不能省略。
8. 不新增资产、状态资产、数据库表、锁文件或备用公式；不恢复25股专用模块。

### 20.2 模块和函数归属

下表路径相对`lake_console/orchestrator/src/orchestrator/`。开发不能另写平行入口绕过本表。

| 文件 | 明确改动 |
| --- | --- |
| `defs/run_contracts/stock_daily_qfq_repair.py`（新增） | 仅放本节的数据类、枚举、校验与预算值；无instance、DuckDB或文件写入 |
| `defs/stock_daily_qfq.py` | 保留列合同、纯价格SQL和输入覆盖；抽出relation级公式；移走repair编排、计划、结果类型和合并SQL，不留转发兼容层 |
| `defs/stock_daily_qfq_repair.py`（新增） | 承接原相邻因子比较、范围规划及repair执行；增加按统一计划准备、提交、结束登记的编排 |
| `defs/stock_daily_qfq_repair_records.py`（新增） | 本次执行记录的原子JSON、内容hash、路径安全、逐文件记录、恢复及进度；不包含价格公式 |
| `defs/bootstrap/stock_daily_qfq_history_audit.py`（新增） | 一次历史检查、逐批结果、异常键与可复用证明；不得写正式Gold或DG事件 |
| `defs/io/stock_daily_qfq_writer.py`（新增） | 候选生成、现行结构合同及范围验证、逐文件提升；复用执行记录，不自行生成计划 |
| `defs/ops/gold_stock_daily_qfq_factor_repair.py` | 原dict config迁移为统一类型；按action分派上述helper；只在完成条件成立时写protected完成事件 |
| `defs/run_contracts/configs.py` | 替换QFQ与趋势repair config及builder，禁止多余/旧字段；定义见20.3 |
| `defs/run_contracts/run_keys.py` | 复用现有通用builder，不新增数据集专属builder；原run key治理文档同步此次payload变化 |
| `defs/sensors/gold_stock_daily_qfq_factor_repair_job_sensor.py` | 替换run-status decorator与整段按触发run决策；读进度、变化提示、最早未完成范围，提交原job |
| `defs/asset_guards/stock_daily_qfq_factor_repair.py` | 替换旧metadata判断；新增历史消费、输入变更和阶段完成读取；不计算价格 |
| `defs/assets/stock_daily_qfq.py` | 使用同一候选writer；正式准入检查；先记录待核对日期，再写新分区，metadata记录实际来源/输出身份 |
| `defs/sensors/stock_daily_qfq_sensor.py` | 有未完成正式提交/维护时阻断新写；普通新增日仍按原上游门禁，不能拿历史自as-of覆盖 |
| `defs/bootstrap/gold_stock_daily_qfq_history.py` | 保留发现日期和有效分母计算；正式写入改用统一repair执行，不再用exists/skip证明正确 |
| `defs/bootstrap/gold_stock_daily_qfq_history_cli.py` | 保留原只读阶段；增加生成audit/repair运行配置；正式根的旧`--apply`明确拒绝，见20.12 |
| `defs/stock_daily_trend_channel.py` | 将现有repair拆成候选生成/校验与提升，接入同一逐文件恢复；不改递推核 |
| `defs/ops/gold_stock_daily_trend_channel_repair.py` | 从价格计划取真实日期/股票，不再前一天或日期数减1；使用统一提交记录 |
| `defs/sensors/gold_stock_daily_trend_channel_repair_job_sensor.py` | 改为有界普通sensor，查尚未完成的趋势事项，避免再次依赖run-status漏接 |
| `defs/sensors/stock_daily_trend_channel_sensor.py` | `_qfq_reconciliation`只读新完成状态；删除自身按producer_run_id重拼批次、日期数减1的分支 |
| `defs/qfq_nineturn.py` | 保留日九转纯SQL；新增只生成指定日候选的helper，交统一writer提交；不改分钟分支 |
| `defs/assets/qfq_nineturn.py`、`defs/sensors/stock_daily_qfq_nineturn_sensor.py` | 仅日线新增历史消费门禁；旧结果受影响时不冒充ready |
| `defs/assets/stock_daily_qfq_nineturn_prod_core.py`及对应sensor | 只加未完成/源版本门禁；修复中不自动发布，本轮不执行Prod写入 |
| `defs/paths.py` | 新增本节固定staging/记录路径helper；复用既有根和安全校验 |
| `defs/catalog/lake_assets.py`、资产metadata、运行合同/拓扑文档 | 描述新的写入、完成和sensor类型；资产key、分区、价格列不变 |

原`stock_daily_qfq.py`移出的符号包括`GoldStockDailyQfqFactorRepairPlan/Result`、`GoldStockDailyQfqRepairPartitionWriteResult`、
`build_stock_daily_qfq_factor_changed_codes_sql`、`build_gold_stock_daily_qfq_factor_repair_plan`、
`execute_gold_stock_daily_qfq_factor_repair`、`write_gold_stock_daily_qfq_factor_repair_partition`、
`build_gold_stock_daily_qfq_factor_repair_check_metadata`及它们专用的范围/合并helper。
更新20.2表中的导入、`test_stock_daily_qfq_*`、趋势M4/M5和静态测试；旧模块不重新导出这些符号。
`gold_stock_daily_qfq_factor_repair_codes_hash`保留纯函数，供计划和下游共用。
旧GoldStockDailyQfqFactorRepairPlan/Result类型退出，由本节QfqRepairPlan/QfqExecutionResult替代；旧build-plan签名也退出，不能只改import后继续调用旧语义。
原两个正式写函数从数学模块移到`io/stock_daily_qfq_writer.py`，该模块调用数学模块，数学模块不得再反向import writer；所有调用方改到新落点，不留转发函数。
既有500股QFQ常量迁入纯合同模块，原值不变；趋势自己的自动限制继续参与自动准入，历史计划使用明确的历史模式，不凭代码数量猜模式。

依赖固定为：纯合同→无项目运行依赖；记录→合同/paths；数学SQL→合同/SQL工具；writer→记录/数学；
repair→writer/记录/审计；guard→记录/合同/Dagster读取；op和sensor负责装配。helper不得import op/sensor或Prod Ops。

不直接复用以下完整入口：

- `rebuild_qfq_nineturn_scope`：会重新做fresh_plan、先算全范围再判断已完成、复制backup并清理staging；本次只复用纯计算/合同，不能带入这些行为。
- moneyflow提升入口：它绑定moneyflow计划且拒绝不同目标，不适用于覆盖错误QFQ；参考其提交意图顺序，不增加跨数据域导入。
- 公告checkpoint：绑定公告状态及锁；不作为通用修复依赖。

### 20.3 操作参数、身份和旧合同退出

`configs.py`中的新`GoldStockDailyQfqFactorRepairConfig`使用`extra='forbid'`，字段固定如下：

| 字段 | 类型/默认值 | 校验 |
| --- | --- | --- |
| `action` | `Literal['reconcile','audit_history','prepare_history','apply_history','finalize_history','repair_nineturn']`；无默认 | 必填，不允许未知操作 |
| `start_trade_date`、`end_trade_date`、`as_of_trade_date` | `str | None = None` | reconcile/audit必填ISO日期，start≤end≤as_of；其他action必须为空，取计划 |
| `patrol_start_trade_date`、`expected_progress_revision` | `str | None`、`int | None`，均默认None | 仅reconcile由sensor显式提供；前者是日历内巡检起点，后者非负且拒绝bool；其他action必须为空 |
| `audit_id` | `str | None = None` | audit/prepare必填64位小写hex；由首次审计请求内容算出，不是股票池 |
| `audit_sha256` | `str | None = None` | prepare必填；审计未封存/存在未解决项拒绝准备 |
| `plan_id`、`plan_sha256` | `str | None = None` | apply/finalize/repair_nineturn必填64位hex；其他action为空，不能任意路径 |
| `repair_attempt` | `int = 1` | 必须为正整数且拒绝bool；失败/取消后的人工恢复递增，不改变计划 |

`build_gold_stock_daily_qfq_factor_repair_run_config(*, action, start_trade_date=None, end_trade_date=None, as_of_trade_date=None, patrol_start_trade_date=None, expected_progress_revision=None, audit_id=None, audit_sha256=None, plan_id=None, plan_sha256=None, repair_attempt=1)`
只构造该类型并`model_dump(exclude_none=True)`到原op的config；op直接接收这个类型，删除原手写dict schema与重复日期/hash解析。
原`qfq_factor_trade_date/repair_required_codes_hash/upstream_batch_id`不再是输入字段，出现即报`qfq_config_legacy_fields`。
它们仍可作为输出说明字段，值只能从冻结计划推导，不从原config兜底。

趋势config改为`source_plan_id: str`、`source_plan_sha256: str`、`repair_attempt: int=1`，同样extra=forbid。
删除其可输入的stock_codes、原因日、start/end和旧source_upstream_batch_id；op从价格计划及当前完成记录取得，不允许手写范围。
`build_gold_stock_daily_trend_channel_repair_run_config`同步只接收这三个字段。

三个身份按以下顺序计算，均用canonical JSON（UTF-8、sort_keys、无空白、拒绝NaN），不含时间戳、run_id或event storage id：

```text
audit_id = SHA256({schema_version:2, scope_start, scope_end, as_of,
                   comparison_version, source_inventory_sha256})
plan_sha256 = SHA256(完整plan.json正文，排除自身id/hash和created_at)
plan_id = plan_sha256
upstream_batch_id = build_batch_id(producer='gold_stock_daily_qfq_factor_repair',
                                  scope=as_of_trade_date,
                                  payload={plan_id, source_revision, pricing_version},
                                  digest_length=64)
run_key = build_repair_attempt_run_key(subject='gold_stock_daily_qfq_factor_repair',
                                     repair_scope_id=request_id, attempt=repair_attempt,
                                     attempt_scope=action)
```

`request_id`是输入请求（action、日期/计划hash、已确认进度revision）的SHA256。请求尚未执行时无plan，用请求身份去重；
op生成计划后保存request→plan引用，重复请求先读引用，不重新规划。
重试只改attempt；已在QUEUED/STARTING/STARTED/CANCELING的同请求不重复提交。失败/取消保持阻断，明确显示人工恢复，不自行重启用户取消的任务。
sensor使用标准`dagster/run_key`过滤`instance.get_runs(RunsFilter(job_name=..., tags={RUN_KEY_TAG:run_key}), limit=1)`，不能扫描全部runs。
恢复已有plan时计算/COPY只发生于没有合格成果的单元。

删除原sensor里的`build_gold_stock_daily_qfq_factor_repair_upstream_batch_id(producer_run_id=...)`；
趋势日更不再调用它。旧事件保留供查阅，缺schema_version=2不能满足新完成合同，不保留生产双读分支。

### 20.4 数据类和文件格式

`run_contracts/stock_daily_qfq_repair.py`定义以下不可变数据类，日期内部用`date`，序列排序去重；JSON中日期用ISO字符串：

```python
QfqFileIdentity(relative_path: str, exists: bool, size: int,
                mtime_ns: int, ctime_ns: int, device: int, inode: int,
                sha256: str | None)
QfqAffectedScope(ts_code: str, first_changed_date: date,
                 last_changed_date: date, reason: str, repair_all_history: bool)
QfqFileProof(asset_key: str, trade_date: date, target: str,
             original: QfqFileIdentity, candidate_sha256: str | None,
             input_revision: str, scope_sha256: str, row_count: int,
             status: str, candidate_relative_path: str | None,
             validation_ref: str | None, validation_sha256: str | None,
             dependency_ref: str, dependency_sha256: str,
             actual_target: QfqFileIdentity | None, last_error: str | None)
QfqRepairPlan(schema_version: int, plan_id: str, as_of_trade_date: date,
              reconcile_start: date, reconcile_end: date, source_revision: str,
              affected_scope_ref: str, affected_scope_sha256: str,
              target_index_ref: str, target_index_sha256: str,
              audit_id: str | None, audit_sha256: str | None, pricing_version: str,
              supersedes_plan_id: str | None,
              expected_file_count: int, consumer_scopes: tuple)
```

`QfqAffectedScope`只允许reason=`factor_change/mixed_basis/source_correction/missing_gold/value_mismatch`；不接受未经解释的自由股票列表。
`target`和所有ref都是本节指定根下的相对路径，由paths helper重建，拒绝`..`、绝对ref、符号链接和越界。
`exists=false`时size=0、sha256=None；这是计划中明确的缺Gold文件，不是运行时任意缺失都允许创建。

执行目录固定为：

```text
/Volumes/datasource/data_lake_staging/stock_daily_qfq_repair/
  progress.json                         # 小型进行位置和活动计划
  dates/YYYY-MM-DD.json                 # 已核对文件属性、内容hash及证明引用
  requests/<request_id>.json            # 请求与生成的audit/plan对应关系
  audits/<audit_id>/audit.json           # 审计总范围、口径、汇总；封存后不改
  audits/<audit_id>/batches/000001.json   # 本批输入、覆盖、问题及成果引用
  audits/<audit_id>/issues/000001.parquet
  audits/<audit_id>/context/000001.parquet
  plans/<plan_id>/plan.json              # 不可变计划
  plans/<plan_id>/scope.parquet          # 受影响股票和实际键范围
  plans/<plan_id>/targets.parquet        # 每个目标文件、原版本及动作
  plans/<plan_id>/files/<asset>/<date>.json
  plans/<plan_id>/candidates/<asset>/<date>/attempt-<generation>/part-000.parquet
  plans/<plan_id>/segments/<consumer>/<segment>.json
  plans/<plan_id>/completion.json
```

对应paths helper为`stock_daily_qfq_repair_root(staging_root)`、`stock_daily_qfq_repair_plan_path(staging_root, plan_id)`、
`stock_daily_qfq_repair_file_record_path(staging_root, plan_id, asset_key, trade_date)`，均先严格校验组件。
临时隔离根只允许测试注入的`/private/tmp`子目录；正式默认根不能被环境变量偷偷替换。

这是原方案中“计划、checkpoint和逐文件证明”的具体格式，会被正式入口读取，并非纯审阅报告。
新增这些文件的原因是：Dagster事件不能与文件rename组成一个事务，小cursor也无法保存逐文件提交前/后hash。
不另建正式状态资产或数据库表；记录不能独立充当价格源，计算仍以绑定版本的Silver及本次候选为依据。
旧审计及计划不覆盖；`dates`是当前文件证明索引，必须指向不可变audit/plan，不能只有一个可修改的“通过=true”。
进度和文件记录不能随退出自动删除；仅在后继证明完整替代、无恢复需求且获清理指令后清理。

`progress.json`字段固定：`schema_version=2`、`revision`、`baseline_audit_id/hash`、`baseline_as_of`、
`reconciled_through`、`active_request_id`、`active_plan_id/hash`、`active_phase`、`attempt`、`run_id`、
`unverified_from`、`unresolved_count`、`pending_consumers`、`patrol_next_date`、`last_error`、`updated_at`。
文件上限64KiB，不存所有日期或股票；`pending_consumers`仅允许当前计划的trend/nineturn两个引用。
每个消费者引用的字段为consumer、source_plan_id/hash、status、request_id、attempt、run_id、scope_ref/hash、output_revision、last_error；
status只允许PENDING/RUNNING/COMPLETE/NOT_REQUIRED/NOT_APPLICABLE，失败保留所在阶段并附last_error，不能移出pending后伪装完成。
缺失baseline时返回`qfq_history_baseline_missing`并阻断；不得以日期最小值或今天自动初始化成功。

`dates/<D>.json`包括`trade_date`、各实际输入/输出`QfqFileIdentity`、`proof_ref/proof_sha256`、
`as_of_trade_date`、`input_revision`、`checked_scope_sha256`、`unverified`、`last_source_dates_ref`。
同股前序日期索引仅作查找位置，writer必须读对应正式Silver行并核对输入；不能把staging索引当作源价格。
初始化完整历史审计批次会建立这些记录，日常新文件沿同一格式追加，不重新枚举历史业务行。

上文函数返回类型的字段也必须具体实现，不能留给调用方自行拼dict：

| 类型 | 必须字段 |
| --- | --- |
| `QfqHistoryProgress` | 与progress.json逐字段相同，revision非负；active字段全空或成组齐全；reconciled_through≤已验收覆盖末端 |
| `QfqAuditPlan` | audit_id、start/end/as_of、comparison_version、inventory_ref/hash、batch_count、budget、reused_evidence_refs |
| `QfqAuditBatchResult` | batch_id、covered_start/end、covered_key_count、pass_key_count、repair_key_count、unknown_key_count、issue_ref/hash、context_ref/hash、input_revision、complete |
| `QfqAuditSummary` | audit_id、audit_sha256、上述各批计数总和、expected_batch_count、completed_batch_count、source_revision、sealed；缺批/unknown>0时sealed=false |
| `QfqCandidateValidation` | passed、schema/date/key/coverage/preserved_row/preserved_field规则计数、expected/output_row_count、failure_samples最多20条；任一失败则passed=false |
| `QfqPrepareResult` | plan_id/hash、selected_file_count、validated_file_count、unchanged_file_count、pending_file_count、candidate_bytes |
| `QfqApplyResult` | plan_id/hash、selected_file_count、committed_file_count、unchanged_file_count、pending_file_count、failed_file_count |
| `QfqCompletion` | QfqApplyResult全部字段，另有covered_key_count、unresolved_count、completion_sha256、event_recorded、consumer_status；仅pending/failed/unresolved全0可发价格完成 |
| `QfqExecutionResult` | action、request_id、plan_id/hash可空、stage、reason_code、summary计数、completion_ref可空；没有完成对象就不能写完成check |
| `QfqEventReadiness` | trade_date、ready、missing_check_count、failed_check_count、stale_check_count、reason_code；不含storage id身份字段 |
| `QfqWorkDecision` | action可空、request_id、start/end/as_of可空、plan_id/hash可空、attempt、reason_code、summary、next_action；不放股票列表 |
| `QfqFileChangeHint` | checked_start/end、next_date、checked_date_count、changed_file_count、missing_record_count、最多5个路径样本；op重新按同一起点核实，不依赖样本完整性 |
| `QfqSourceChangeResult` | verified_input_revision、changed_scope_ref/hash、unknown_count、next_patrol_date、content_changed；unknown>0不能no-op |
| `QfqConsumerScope` | consumer、source_plan_id/hash、affected_scope_ref、result_dates_ref/hash、state_dates_ref/hash可空、seed_ref/hash可空、existing_tail、not_applicable_reason可空 |
| `QfqConsumerPrepareResult/ApplyResult` | consumer/source_plan_id、selected/validated或committed/unchanged/pending/failed文件计数、segment_refs、output_revision；所有目标键须等于scope |
| `QfqHistoryConsumptionStatus` | ready、reason_code、as_of_trade_date、source_plan_id、source_revision、unresolved_count、pending_consumer_count |

所有`record_store`参数统一为`QfqRepairRecordStore`数据类，字段为lake_root、staging_root、run_id、identity_cache、
loaded_plan_cache、已加载文件记录索引和budget累计值；不保存行情明细。实际读写只通过20.5的函数，没有另一套同名转发方法。
op每run只构造一次record_store，阶段和worker复用；新进程可重建索引但不能重算已封存业务成果。

JSON加载与dataclass构造使用同一validate方法，禁止调用方补默认成功计数。
plan文件包含所引用Parquet的hash；`load_qfq_repair_plan`验证其正文hash及这些引用，不接受只改路径不改内容hash。
初始inventory hash只绑定路径/属性/范围，不能冒充内容校验；内容强依据是audit各批实际取得的source_revision和audit_sha256。
同audit_id的范围/口径一旦保存便不可修改；计划或比较方法实际改变需新id，已完成证明仍保留供可复用部分使用。
`expected_file_count`及QFQ完成metadata仅计算价格文件；消费者在各自scope内单独计数，不再用减1等推导。
`targets.parquet`逐行保存asset_key、trade_date、CREATE_MISSING/REPLACE/KEEP、原身份、允许修改范围ref/hash；
`scope.parquet`逐行保存ts_code、影响起止、reason、repair_all_history，局部改键/字段另存有hash的允许范围表。
`QfqEvidenceRef`字段为id、path、sha256、covered_dates、covered_codes_ref/hash、covered_fields、input_revision、conclusion_type；无强输入身份只能复用原因结论。
`QfqRepairControl`字段为check_cancelled回调、emit_progress回调、monotonic时钟、当前连接及预算累计值；
提供before_unit/after_unit、hash_progress和run_sql方法，25秒定时器只调用该连接interrupt，finally取消定时器，不创建第二个业务线程/任务。
KeyboardInterrupt和Dagster中断异常先保存当前已完成状态再原样抛出，不能转成功或自动重试用户取消。

### 20.5 执行记录的写入函数和状态

`stock_daily_qfq_repair_records.py`新增以下接口；所有写路径只由op/正式writer调用，sensor只读：

```python
load_qfq_progress(*, staging_root: Path) -> QfqHistoryProgress
save_qfq_progress(*, staging_root: Path, expected_revision: int,
                  progress: QfqHistoryProgress) -> None
read_qfq_file_identity(path: Path, *, with_hash: bool,
                       cache: dict, check_cancelled: Callable) -> QfqFileIdentity
load_qfq_repair_plan(*, staging_root: Path, plan_id: str,
                     expected_sha256: str) -> QfqRepairPlan
save_qfq_file_proof(*, record_path: Path, proof: QfqFileProof) -> None
recover_qfq_file(*, proof: QfqFileProof, lake_root: Path,
                 staging_root: Path, control: QfqRepairControl) -> str
summarize_qfq_completion(*, plan: QfqRepairPlan, records: Iterable) -> QfqCompletion
```

`save_qfq_progress`执行：读当前revision→必须等于expected_revision→写同目录唯一临时JSON→flush/fsync→os.replace→fsync目录。
新revision严格加1；意外并发不覆盖，报`qfq_progress_conflict`。这不是用JSON文件当锁，正式写者串行前提见20.12。
JSON序列化拒绝NaN、额外字段及负数计数，读取设置单文件大小上限，错误不能返回空进度。
文件身份另保存`st_dev/st_ino/st_ctime_ns`，连同size/mtime构成进程内复用hash的key；hash以1MiB块读取，前后fstat不同则`qfq_file_changed_during_read`。
同一次稳定执行每个身份只算一次hash。重启后先看记录和文件属性；属性变更、提交归属不明确时才补读必要hash，不重新跑业务SQL。
计划source_revision用于整次身份；文件/计算段的dependency_sha256只覆盖该单元实际使用的Source行、factor键、分母向量和seed。
dependency表保存源路径、实际键范围、相关列、文件hash及相关行hash；相关行hash由DuckDB对固定列struct_pack→to_json，按键排序string_agg后sha256取得，不能把全部行拉到Python逐行hash。
序列化字段顺序与类型固定，并包含规则版本、列合同及行数；空关系显式用空串计算摘要且另核预期行数，不能让string_agg的NULL掩盖缺输入。
函数依据见DuckDB的[JSON创建](https://duckdb.org/docs/current/data/json/creating_json)、[有序聚合](https://duckdb.org/docs/current/sql/functions/aggregates#order-by-clause-in-aggregate-functions)与[SHA-256](https://duckdb.org/docs/current/sql/functions/text#sha256value)；本轮只查资料，未在正式环境执行SQL实验。
同一as-of分母向量只计算一次并复用。源文件实际变化但只改了其他股票时，重读该文件所需投影、相关行hash不变即可复用该单元，不重新跑价格或指标。
新计划可通过supersedes_plan_id引用旧计划的合格成果，但必须逐单元验证允许范围、pricing_version、dependency和原目标/实际输出身份相同。
输入真正影响到的单元/后续递推段才重算，不能因为整个source_revision或plan_id改变就把所有已完成成果清零。

逐文件状态只能按以下路径前进，错误另记`last_error`，不把已有合格成果退回初始状态：

```text
PLANNED → CANDIDATE_VALIDATED → REPLACE_INTENT → COMMITTED
PLANNED → UNCHANGED
```

`UNCHANGED`必须有完整比较/范围证明和正式文件hash，不能因为exists就进入此状态。
`COMMITTED`前已经封存候选证明；`REPLACE_INTENT`同时保存原目标和候选两个hash、候选字节数与输入版本。
checkpoint写失败发生在rename前则不rename；发生在rename后则保留新目标，后续凭意图恢复，禁止回换旧文件。

恢复判定固定为：

| 实际目标 | 候选/证明 | 动作 |
| --- | --- | --- |
| 等于原目标，或计划明确原本不存在且仍不存在 | 候选与封存hash相符 | 完成原定rename，不重新COPY |
| 等于本计划候选hash | 即使候选已被rename移走，意图/证明完整 | 补COMMITTED记录，不再rename |
| 等于第三种hash，或计划已有目标突然消失 | 任意 | `qfq_target_conflict`停止，不覆盖 |
| 目标仍旧，候选/证明损坏 | 未动正式数据 | 仅该文件/所属未完成计算段重新生成；保留损坏证据供诊断 |
| 目标已新但缺少可证明的候选意图 | 无法确认归属 | `qfq_output_proof_missing`，不能猜测成功 |

阶段状态为`AUDITING/AUDIT_COMPLETE/PREPARING/PREPARED/APPLYING/FILES_COMPLETE/COMPLETION_PENDING/PRICE_COMPLETE/COMPLETE`。
`PRICE_COMPLETE`只表示价格和匹配完成事件成立；`COMPLETE`还要求本计划已有DG下游接续完成。
`FAILED/INTERRUPTED`通过last_error和run终态表达，阶段保留最后已完成事实；不能清空进度后从头再来。

### 20.6 一次历史检查的函数与SQL步骤

`bootstrap/stock_daily_qfq_history_audit.py`接口固定：

```python
plan_stock_daily_qfq_history_audit(*, lake_root, staging_root,
    start_trade_date, end_trade_date, as_of_trade_date,
    reused_evidence: Sequence[QfqEvidenceRef], connection) -> QfqAuditPlan
audit_stock_daily_qfq_history_batch(*, audit_plan, batch_id: int,
    connection, control: QfqRepairControl) -> QfqAuditBatchResult
seal_stock_daily_qfq_history_audit(*, audit_plan, control) -> QfqAuditSummary
```

`plan_...`枚举日历范围及实际正式文件集合，只规划一次。检查范围取应有历史与实际Source/Gold的并集，不能只遍历Gold已存在分区。
范围外多出的日期/键单列，不删除。SSE日历覆盖、开市标志、生命周期/停牌来源合同先核对；缺事实记UNKNOWN，不假设停牌。
已有五股和25股证据逐条登记可复用的字段、日期和源/目标标识；没有全文件hash的证据可证明原因，不能冒充全文件已检查。
原证明只覆盖部分股票时，只扣除该范围，不能把整个共享文件设成通过。

每批默认20个交易日。一次处理全部股票，用`COPY`保存异常和上下文；Python最多取20条错误样本与计数。
先执行一次因子列投影，形成本次运行的临时因子关系和逐股不晚于as-of的最后因子；分批计算复用它，不为每个日期再次扫描因子全史。
临时关系可落本次staging，绑定正式输入hash，仅供本次计算；不能成为独立正式因子事实源。

批内SQL关系与顺序固定：

```sql
-- 1. 读取本批实际Source及批前最后实际行；保留来源日期，不凭市场前一天推断。
WITH ordered_source AS (
  SELECT ts_code, trade_date, open, high, low, close, vol, amount,
         lag(trade_date) OVER w AS previous_trade_date,
         lag(close) OVER w AS previous_close
  FROM source_with_verified_prefix
  WINDOW w AS (PARTITION BY ts_code ORDER BY trade_date)
), priced_source AS (
  SELECT s.*, f.adj_factor AS row_factor, pf.adj_factor AS previous_factor,
         a.adj_factor AS as_of_factor
  FROM ordered_source s
  LEFT JOIN trade_factors f USING (ts_code, trade_date)
  LEFT JOIN trade_factors pf
    ON s.ts_code=pf.ts_code AND s.previous_trade_date=pf.trade_date
  LEFT JOIN effective_as_of_factors a ON s.ts_code=a.ts_code
)
-- 2. 先记录缺因子/重复/非有限数，不能用INNER JOIN把缺项过滤掉。
-- 3. 独立审计SQL给出四价、昨收、涨跌额/幅；仅比较本批，不输出批前上下文。
-- 4. FULL OUTER JOIN到Gold键，分别标出missing_gold/extra_gold/value_mismatch。
-- 5. 按日/股票汇总问题和首次影响日，同时COPY异常键及下一批必要上下文。
```

四价参考=`source_price*row_factor/as_of_factor`；昨收参考=`previous_close*previous_factor/as_of_factor`。
无前序且已确认是本股第一条实际行才参考0；否则缺前序/因子进入UNKNOWN。涨跌额和幅按既有零值合同处理。
比较条件固定为`abs(actual-expected) <= greatest(1e-10, 1e-12*abs(expected))`；NULL/NaN/Inf先按错误处理，不参与近似比较。
量额使用源值的`IS NOT DISTINCT FROM`，不复权，不四舍五入。容差是DOUBLE运算误差，不能用于接受另一复权基准。
量额不一致先记UNKNOWN并查明原因，不能把复权回刷变成未经说明的量额改写；它未解决时总体仍未完成。
纯精度因子保留合同不变；若出现源合同与结果矛盾，记录明确键并停止该范围，不自动改源。
审计SQL不import生产价格SQL builder；用独立字面/Decimal样本检验审计方法本身。

批前上下文从前一已完成批的保存结果接续，包含每股最后实际日线定位及相应因子来源；不每批重新向前扫历史。
完成批落盘后立即写批记录，封存结果hash。恢复读取已有批记录及其输入身份，无变化就接下一批，不再次计算该批。
`seal_...`只汇总批记录及集合：每个应检查键只能落在PASS/REPAIR/UNKNOWN之一，缺批、重复计数、UNKNOWN>0拒绝封存。
Gold缺文件/缺键属于REPAIR，源缺失属于UNKNOWN；能够修的目标不会因不存在而漏出清单。
extra_gold先核对权威源覆盖；无法解释时属于UNKNOWN，不能直接删行让它消失。需要删除的错误键必须有独立依据和明确批准范围后才可进入变更计划。

### 20.7 受影响范围和统一公式的代码修改

`stock_daily_qfq.py`新增纯函数：

```python
build_stock_daily_qfq_price_relation_sql(*, source_relation_sql: str,
    factor_relation_sql: str, as_of_relation_sql: str,
    previous_relation_sql: str) -> str
build_stock_daily_qfq_effective_asof_sql(*, factor_relation_sql: str,
    as_of_trade_date: date) -> str
```

只接收内部SQL关系，不接受运营SQL。将现有`_stock_daily_qfq_base_ctes_sql`中的四价/昨收表达抽到此函数；
现有单日`build_stock_daily_qfq_select_sql`和新批次writer都调用它，禁止复制两套生产数学表达。
effective-asof函数从既有bootstrap的ranked_factors SQL抽取，逐股取<=as-of最后可用因子，输出ts_code、trade_date=as-of、source_trade_date、adj_factor。
bootstrap、审计准备分母与repair共用这个来源选择；审计数值比较仍独立于价格公式builder。
调用前统一核对源键唯一、因子覆盖且>0、前序存在时因子不能缺失；不能让WHERE条件把缺因子行静默丢掉。
候选行数必须与计划Source键相等，不为通过校验删行。

`stock_daily_qfq_repair.py`接口：

```python
detect_stock_daily_qfq_factor_changes(*, connection, factor_paths,
    expected_trade_dates, start_date, end_date) -> tuple[QfqAffectedScope, ...]
build_stock_daily_qfq_repair_plan(*, connection, lake_root, staging_root,
    source_audit: QfqAuditSummary | None, reconcile_dates,
    as_of_trade_date, progress, control) -> QfqRepairPlan
prepare_stock_daily_qfq_repair(*, connection, plan, control) -> QfqPrepareResult
apply_stock_daily_qfq_repair(*, plan, control) -> QfqApplyResult
execute_gold_stock_daily_qfq_factor_repair(*, connection, lake_root, staging_root,
    config: GoldStockDailyQfqFactorRepairConfig, record_store,
    control: QfqRepairControl) -> QfqExecutionResult
```

`detect_...`一次比较最多10个待处理日及其前一日因子，union受影响股票；用完整键检查后比较，不用INNER JOIN隐去缺因子。
仅新上市、没有任何更早历史Source/Gold且上市事实相符时，前日无因子可免历史回刷；有更早历史却缺前日因子必须报错。
同股多个原因合并，分母变化/混基准设`repair_all_history=true`；仅Source局部更正按实际键及下一实际报价昨收扩展。
范围推导具体为：日线close更正影响当日及下一实际报价的昨收/涨跌额/幅；open/high/low仅影响当日相应字段；
某历史factor更正影响当日四价及下一实际报价昨收。若该factor恰为该股截至as-of最后可用的那条，则分母改变，改为全历史。
不能只用“更正日期等于as-of日期”判断分母变化，否则会漏掉退市股票最后因子的更正。
审计保存的Gold/独立期望close比值在同股历史出现多个口径时归mixed_basis；整体同一非1比例归factor_change；
仅个别字段错误且无法证明是源更正时归value_mismatch，按明确错误键修，不编造源端原因。归类只处理已保存审计结果，不再扫描Gold。
源文件身份改变但差异仍未核清时不得直接no-op，先对这个文件做局部审计。

全历史扩展起点取该股源/目标有效历史的并集，不能只从已存在Gold取最小日。需要创建Gold的日期必须在计划中标`CREATE_MISSING`并有完整Source证明。
无法产生价格的源缺口不得生成候选，返回待处理问题。计划内已存在的目标为`REPLACE`；经完整比较没有变化则`KEEP`。
计划保存每个日期所有受影响股票和字段范围；局部源更正仍保留未受影响字段，四价回刷不得改量额。
as-of固定不晚于本次上游完整末端且不早于当前已确认as-of；更早的请求报`qfq_as_of_regression`。
退市股票的分母取截至该日最后可用因子，不要求当日仍有记录。

日更保留20日快速前序查询，但没有查到某股时调用：
`resolve_stock_daily_qfq_previous_rows(connection, source_codes, trade_date, history_records)`。
它先从已验收日期索引定位上一实际日，读取对应正式Silver行和factor；定位记录不一致/缺输入报错。
没有索引时不能直接写0，交离线检查补齐；仅生命周期与完整覆盖证明首次实际行时允许0。
这里的首次实际行包括已经确认的正式Lake覆盖起点第一条可计算行，不要求其等于上市日；不能因上市早于湖覆盖而误拦合法首行。
原默认`as_of_trade_date=None`退出正式writer签名；所有调用显式传as-of，日更新D才允许D。

### 20.8 候选准备和范围验证

`io/stock_daily_qfq_writer.py`接口固定：

```python
prepare_stock_daily_qfq_partition_candidate(*, connection, plan,
    trade_date: date, source_relations, record_store, control) -> QfqFileProof
validate_stock_daily_qfq_candidate(*, connection, candidate_path, original_path,
    trade_date, allowed_scope_relation, expected_source_keys) -> QfqCandidateValidation
promote_stock_daily_qfq_candidate(*, proof, record_store, control) -> QfqFileProof
```

准备顺序：先查文件记录；COMMITTED/UNCHANGED直接复用；CANDIDATE_VALIDATED读取必要hash确认，不重新COPY；其余才计算。
每次实际重新生成分配新的generation并在COPY前记入文件记录；未封存的失败候选不覆盖、不unlink，保留原attempt目录。
本批Source和批前上下文先形成有界临时关系；同日所有变化行合并成一个replacement关系。
输出SQL为原文件中不允许修改的行/字段，加本计划replacement；CREATE_MISSING输出完整合法Source键。
缺原目标却未标CREATE_MISSING、或已有目标却标CREATE_MISSING，立即冲突停止。

候选校验一次，返回各规则计数和至多20个失败样本：

1. 对照`GOLD_STOCK_DAILY_QFQ_SCHEMA`核对列顺序和物理类型；复用`stock_factor_price_checks.py`的日期/键非空/唯一规则。
2. Source实际应输出键与候选受影响键双向EXCEPT ALL为0；不以总行数相同代替键集合正确。
3. 未受影响行对原文件做一次双向EXCEPT ALL；受影响行的量额、未批准修改字段逐项相等。
4. 全部输入缺项已在准备前解决，输出计数与计划相等；不再次调用价格公式生成另一份expected。
5. 结构/范围校验、候选hash和输入版本一起落入CANDIDATE_VALIDATED；失败候选保留，正式目标未动。

整计划正式提升前要求所有价格候选均已通过，不能一边才发现后半段缺源、一边先改前半段。
默认20日计算段，段末保存候选/上下文；下次先复用已封存段，不按股票重复跑整段Source。
临时查询有25秒取消预算；超时中断后把未完成日期批减半，最小1日仍超时则明确失败，不能无限重试或偷偷扩大资源。

### 20.9 提交与完成登记的严格顺序

op根据action只执行对应阶段，`reconcile`是同一受控run内依次规划→准备→价格提交→价格完成登记；
history将audit/prepare/apply分开，以便管理员审阅真实候选和范围。
价格apply入口伪代码如下，函数调用和异常路径是开发约束：

```python
assert_formal_qfq_run(context)                 # 正式根；临时隔离root走测试合同
plan = load_qfq_repair_plan(plan_id, plan_sha256)
progress = load_qfq_progress()
assert_no_other_active_plan(progress, plan)
assert_all_candidates_validated(plan, asset_key='gold_stock_daily_qfq')
assert_plan_source_identities(plan)            # 首次rename前一次核对全部实际依赖
save_progress(active_phase='APPLYING', active_plan=plan)
for proof in iter_target_proofs(plan, asset_key='gold_stock_daily_qfq'):
    control.check_cancelled()
    outcome = recover_qfq_file(proof)           # 先识别成果；不能先算
    if outcome == 'needs_replace':
        assert_input_and_target_identity(proof) # 稳定记录复用；实际变化才补查hash
        save_file_proof(status='REPLACE_INTENT')
        fsync(candidate)
        assert_same_device(candidate, target_parent)
        os.replace(candidate, target)
        fsync(target_parent)
        save_file_proof(status='COMMITTED', actual_target_identity=...)
save_completion(stage='FILES_COMPLETE')
save_progress(active_phase='COMPLETION_PENDING')
emit_qfq_completion_check(plan, summarize_qfq_completion(plan))
save_completion(stage='PRICE_COMPLETE')
save_progress(active_phase='PRICE_COMPLETE', pending_consumers=...)
```

`iter_target_proofs`按asset/date稳定顺序流式读，不把全部行情或完整文件清单复制到每个worker。
同文件系统rename保证单个文件不是半截内容；不保证全历史同时切换。
rename后checkpoint失败：run失败，目标保留，恢复见20.5；完成事件失败：FILES_COMPLETE保留，恢复只补事件。
prepare与apply之间发生源更正时，先核全部依赖再开始rename；变化按上述dependency局部失效，不能等改到半途才首次检查那份已变输入。
正常正式运行受同一全局队列串行保护；中断期间实际输入改变则按已保存的范围形成后继计划，沿用未受影响成果，不能带着已失效的旧输入硬续跑。
事件已写但后续记录失败：先按plan/batch读取现有protected完成事件，匹配则补文件记录，不重复写事件。
不匹配/旧合同事件不能当成成功；只追加更正，不删除历史事件。

`summarize_qfq_completion`必须逐项断言：target_index与文件记录键集合完全一致、无多余记录、
`selected=COMMITTED+UNCHANGED`、pending/failed=0、全部证明引用/hash成立、审计未知和缺批均为0。
无变化时selected=0但必须记录实际已核对日期范围和输入版本，不能省略整个完成记录。
这里不运行生产公式、COPY或全历史ordinary readiness；仅核对执行成果及必要的文件归属。

### 20.10 sensor的实际读取与决策代码

原QFQ repair sensor改为`@dg.sensor(job=原repair_job, minimum_interval_seconds=600, default_status=STOPPED, resource_defs沿用现有装配)`。
分类仍由`build_sensor_tags(QUOTE_DATA, GOLD, ASSET_UPDATE)`生成。函数参数改`SensorEvaluationContext`，返回`SensorResult`。
删掉`context.dagster_run`、`monitored_jobs`、`_trade_date_from_dagster_run`及只判断触发日的决策函数。
新增纯决策函数`select_stock_daily_qfq_repair_work(progress, expected_dates, current_sources, run_status, consumer_status) -> QfqWorkDecision`。

有界批量事件核对新增：

```python
batch_stock_daily_qfq_event_readiness(instance, trade_dates: Sequence[str])
    -> Mapping[str, QfqEventReadiness]
```

输入最多10日。check keys从现行`STOCK_DAILY_READINESS_SPECS`、`ADJ_FACTOR_READINESS_SPECS`、`GOLD_STOCK_DAILY_QFQ_READINESS_SPECS`展开并去重。
调用当前安装版本真实支持的：

```python
infos = instance.event_log_storage.get_asset_check_partition_info(
    keys=check_keys, partition_keys=list(trade_dates))
# 按(check_key, partition_key)映射；不得逐日期再调用scalar readiness。
ready = (每个所需info都存在
         and info.latest_execution_status == SUCCEEDED
         and info.latest_materialization_storage_id is not None
         and info.is_current)
```

源码已核实SUCCEEDED来源于evaluation.passed；`is_current`本身允许无materialization，所以非空条件不可删。
该API内部按check key发查询，读取模型为`1+C`条左右（C为check key数），不是一条SQL，也不是`10*C`；隔离假客户端与SQL计数都要验证。
接口是当前Dagster内部API，集中在这个adapter；升级时由契约测试阻断不兼容。关联storage id不进入业务身份。
历史baseline范围不要求重补全史ordinary事件；它使用已保存的文件合同证明。这里的事件核对只用于新增日常日期。

每tick按以下顺序，只读取一次progress并构造一个结果：

1. 根不可用/时间未到，立即skip；不扫描文件或事件。
2. progress不存在/坏JSON/无已验收baseline，返回`qfq_history_baseline_missing`，不自动从最近10日初始化。
3. 当前活动run还在排队/运行则只显示等待。失败或取消显示对应原因，保留未完成位置，等待人工按同计划递增attempt恢复。
4. 有FILES_COMPLETE/COMPLETION_PENDING，则提交同计划finalize，不重新算价格；有pending nineturn则提交`repair_nineturn`；只有pending trend时等待其sensor；PRICE_COMPLETE且消费者均完成时提交finalize推进COMPLETE，不新建价格计划。
5. 读取至多3个上游最新materialization（每个asset limit=1），仅作为变化提示；不能据此证明期间每个旧日期都未变。
6. 对20.11规定的500日期文件属性核对；变化提示/缺项不写进cursor明细，提交一个受控reconcile核对任务持久处理。
7. 按日历从`unverified_from`或`reconciled_through`之后取最早连续未完成日期，批量核对ready。积压超过10日返回`qfq_history_backlog_requires_plan`，留给一次合并的历史任务，不重复逐日回刷同股。
8. ≤10日且完整时提交一个reconcile请求。sensor不写JSON执行记录或Parquet，op接到请求后先持久登记才处理。
9. 无工作时skip，不重复生成no-op任务；无因子变化但日期尚未核对过时仍必须生成一次有完成记录的reconcile。

变化核对请求可先不提供新增日期：此时reconcile使用`start=end=当前已验收末端`，再由op核实旧文件变化。
巡检起点必须来自显式`patrol_start_trade_date`，不能在op重新猜测为progress中更早位置。
op先比较`expected_progress_revision`；排队期间位置已变化则返回`reason_code=qfq_request_superseded`，不写完成check，由下一tick重新选择。
真实受影响范围从核实结果推导，不能仅因config这一天的因子不变就no-op，必须处理本次发现的旧文件变化。
sensor里的轻量核对结果只决定“需要核实”，真正日期/范围在op内重新按固定progress revision确认，避免提交后输入变化使用旧判断。

cursor继续使用`build_sensor_cursor/load_sensor_cursor`，details只保存`summary/next_action/reason_code`、
`progress_revision`、`reconciled_through`、`active_plan_id`、`selected_date`、计数和至多5个错误代码。
cursor不是完成事实；重置不导致跳过历史。旧run-status cursor无法解析时只读progress恢复；progress也不能恢复就报错。
巡检未发现属性变化时，cursor还保存`patrol_next_date/patrol_progress_revision`供下一tick继续；这只表示巡检位置，不改变业务完成日期，不为保存无变化位置创建一次job。
正常cursor目标2KiB、硬上限8KiB。提交RunRequest后不推进`reconciled_through`，该字段只能由完成op更新。

### 20.11 输入变化、巡检和局部失效

`stock_daily_qfq_repair_records.py`新增：

```python
inspect_stock_daily_qfq_file_changes(*, lake_root, staging_root,
    expected_dates, next_date: date, date_limit: int = 500) -> QfqFileChangeHint
verify_stock_daily_qfq_changed_files(*, connection, hints,
    progress, control) -> QfqSourceChangeResult
```

`inspect_...`只按日历构造500日以内的3类已知路径（Silver日线、Silver因子、Gold QFQ），每类最多一次stat；
读取对应500份日期记录。禁止glob后再读全部行情，也不运行价格SQL。读记录总字节预算8MiB，超过则减小本次日期数，不能丢日期。
mtime/size/ctime/inode有变、缺文件、新文件或没有证明记录均返回变化提示；属性未变则复用已保存内容hash。
有变化时核实op保存巡检位置；没有属性变化时只推进cursor的巡检位置，不创建无意义的no-op job。
cursor丢失最多重复属性核对，从progress内最近保存的位置重新轮转，不重复行情审计；业务完成位置仍只认progress和不可变证明。
按起点到当前覆盖末端再回起点轮转，不把更早历史永久留在范围外。
满批且无中断时一轮需要`ceil(N/500)`个tick；实际若因字节/时间预算缩小批次，按已完成日期继续，不能把500上限当成保证吞吐。
最小间隔600秒只用于估算；UI记录实际最后推进时间，不伪造固定完成时刻。

核实op对变化文件计算必要hash：内容相同则仅更新属性记录，不重算；内容不同则只对该日期实际Source/Gold做局部检查。
只有巡检属性变化而内容未变时，不生成新价格计划或重复protected完成check，返回该请求已核实即可；
新增业务日期没有因子变化时仍生成一次no-op完成计划，两种情况不得混用。
Source更正需要检查该股下一实际报价的昨收和下游后续范围；as-of因子变化/混基准则扩该股全历史。
如果只是同日期某股新增/删除，键差异也必须记录；不能因为受影响股票数量或codes hash未变就忽略。
日期记录找不到对应不可变证明时返回`qfq_history_proof_missing`，不能重新标绿。

成功提交价格后及时更新相关dates记录的目标身份，因此巡检不会把自己刚完成的修复再次认成外部错误。
源发布记录只作加速提示，遗漏事件仍能由轮转发现；一次tick/一次触发遗漏不影响下一次继续。
进程停机期间没有运行时不承诺主动发现；恢复时从保存位置继续；巡检操作失败/损坏在UI明确报错。
同文件内容被改变但所有文件属性被恶意伪造不由轻量巡检保证；正式入口禁止这种写法，出现具体证据才定点内容检查，不安排周期性全史重算。

### 20.12 正式并发、历史CLI和初始化

本轮只读本机配置确认：`~/.goldenshare/dagster_home/dagster.yaml`使用QueuedRunCoordinator，
`concurrency.runs.max_concurrent_runs=1`，`pools.granularity=run`。不新增pool、锁或并发配置。
不能把“当前配置是1”当永久假设，正式写入口统一调用：

```python
assert_formal_qfq_run(context, *, lake_root) -> None
```

在正式根时要求：`context.instance.is_persistent`、run_coordinator为QueuedRunCoordinator、
`context.instance.get_concurrency_config().run_queue_config.max_concurrent_runs == 1`、
`context.dagster_run.remote_job_origin`存在且location/repository为本正式orchestrator来源。
另用`get_runs(RunsFilter(statuses=[STARTED]), limit=2)`检查实际运行；在全局1的合同下应只有本run，返回另一个实际STARTED run就报`qfq_concurrent_writer`。
过滤条件不包含QUEUED，其他排队任务不会被误报并发；不通过逐job无界查询证明互斥。
正式直接`execute_in_process`通常无remote origin，必须拒绝，不接受传一个bool声称已经排队。
此检查用于生产写入保护，不是用run来源判断历史是否已经处理；历史遗漏发现仍独立于来源。

新写入`gold_stock_daily_qfq`时，先把本日`unverified=true`和`unverified_from`持久记录，再生成候选/提升；
普通checks通过后也要等reconcile确认历史。已有目标只允许与同输入证明完全相同的复用，不允许日更入口覆盖旧历史。
`progress`处于历史audit/prepare/apply/下游恢复期间，QFQ日更sensor和asset都报`qfq_history_maintenance`，防止手工绕过sensor。
源Silver的新日期可以由既有队列正常生成，固定截止日外的新增不使本次旧范围过期；计划输入范围内的真实变化才局部失效。

历史CLI的行为改动要在开发交付中明确：

- `profile-history`及不带`--apply`的原阶段继续只读规划；不改成隐式生产执行。
- 原`write-sample/build-history --apply --lake-root=<正式根>`在任何扫描/写入前报`qfq_formal_write_requires_queued_job`，输出应提交原repair job的配置说明。
- 新增`plan-audit`和`plan-repair`两个stage，只生成本节config JSON和预计范围；没有自动启动job或安装依赖。
- 正式执行由Dagster UI/获准队列提交原job，action依次audit_history、prepare_history、apply_history、finalize_history；不能仍直接调用原generate写正式根。
- 现有`generate_gold_stock_daily_qfq_history`的正式写分支迁移到统一执行器并要求context；仅测试临时根可直接调用候选路径。去掉未授权正式写绕路。

第一次建立baseline时，只有`audit_history`允许创建初始progress（AUDITING、baseline未验收）；sensor/日更不能自建通过状态。
审计封存可包含REPAIR，但UNKNOWN必须0；准备/提交后实际错误集合清零，finalize才设置baseline_as_of/reconciled_through。
若没有错误也必须保存全覆盖证明，再设置baseline；不是一个空计划就宣告全历史正确。
新日常进度初始化使用这次完整历史的实际截止日，不能补齐几天事件后直接跳到最新。
历史缺Gold文件可由明确CREATE_MISSING计划补齐；缺动态分区先列出注册范围，正式注册单独按既有入口和授权执行，不在repair里顺手注册。

### 20.13 趋势结果/state的准确迁移

趋势repair保留原job名称。其sensor改为普通600秒轮询，读取progress中当前计划的`pending_consumers.trend`，
不再从触发run_config解析原因日；无pending直接skip，每tick最多一个请求，失败/取消保留并显示。
首次run key复用`build_upstream_triggered_run_key(consumer=趋势消费者, upstream_batch_id=价格完成记录提供的值)`；
人工恢复复用`build_repair_attempt_run_key(subject=趋势消费者, repair_scope_id=同一opaque upstream_batch_id, attempt_scope='resume', attempt=N)`。
下游不从plan字段重拼上游batch；plan_id/hash只作为准确读取执行参数的引用，attempt取该消费者恢复次数。

`ops/gold_stock_daily_trend_channel_repair.py`修改点：

1. `_validated_qfq_repair_status`改为按source_plan_id/hash核对PRICE_COMPLETE及实际文件证明，取得内部股票集合；不接受输入股票池。
2. `_trend_repair_trade_dates`改签名为`(expected_trade_dates, affected_start, result_existing_dates, state_existing_dates) -> QfqConsumerScope`。
3. 起点为首个受影响价格在趋势覆盖内对应日期，终点分别取结果/state已有末端；不能继续固定原因日前一日，也不能把QFQ日期数减1。
4. 结果/state覆盖原本应配对却缺一边时记未解决；不得取两者交集后假装完整。没有该股/资产历史覆盖时记录NOT_APPLICABLE及依据，不新增覆盖。
5. seed取起点前一个expected日的有效state，仅当未被本次价格变化污染且证明匹配时复用；否则从现行已确认初始化起点重算必要前缀，前缀只作上下文不扩输出。
6. 若现有初始化合同无法提供可靠seed，报`qfq_consumer_seed_unverified`保留未解决；不能随意取更早任意state或补0。

原`write_stock_daily_trend_channel_factor_repair`拆为：

```python
prepare_stock_daily_trend_channel_repair(*, connection, source_plan,
    consumer_scope, record_store, control) -> QfqConsumerPrepareResult
apply_stock_daily_trend_channel_repair(*, source_plan,
    record_store, control) -> QfqConsumerApplyResult
```

复用`_compute_trend_repair_segment`、现行递推核和结构/覆盖/修改范围校验；保持原SEGMENT_TRADE_DAY_LIMIT，
原`_normalize_trend_repair_codes`中的500上限改由计划模式决定：自动模式仍500，已封存历史模式按10000单计划资源上界，不能让自动上限漏掉批准对象。
每段候选及末端seed保存后封存。恢复从第一个未完成段开始，前段仅核成果，不重新递推。
`_prepare_trend_repair_candidates`不得unlink合格候选。结果/state分别按20.5提交，段/日期只有两者都COMMITTED才完成。
替换顺序沿用state→result，但中间异常由两份REPLACE_INTENT恢复，消费门禁在成对完成前不放行。
移除原writer“提升后再全量业务校验”的循环；候选验证证明+rename输出归属证明用于最后汇总。
现有趋势两个protected completion名称保留，metadata加入source_plan_id/hash与真实结果/state文件计数。

`stock_daily_trend_channel_sensor._qfq_reconciliation`改为调用历史状态helper，删除最新materialization run_id重拼批次、相邻因子重算和数量减1。
日更asset本身也在读价格前检查history状态，避免手工调用绕过；历史repair凭匹配source_plan读取PRICE_COMPLETE结果，不被自身pending标记死锁。

### 20.14 日九转、发布及消费门禁

日九转历史接续由原QFQ repair job的`action=repair_nineturn`执行，不新增每日数千个run或新job。
原QFQ sensor看到pending nineturn时提交一次该action；它只能消费已PRICE_COMPLETE计划，不能重新修价格。
`qfq_nineturn.py`新增：

```python
prepare_stock_daily_qfq_nineturn_repair(*, connection, source_plan,
    existing_target_dates, record_store, control) -> QfqConsumerPrepareResult
```

对计划受影响股票，使用现有`build_gold_stock_daily_qfq_nineturn_select_sql`和同一公式核，
按实际行情顺序计算至九转已有末端。计数可能延续超过20日，不能只改close或只处理固定20日窗口。
首次受影响之前的有效上下文必须覆盖比较lag=4及连续计数的正确seed；不能直接沿用受污染旧九转计数。
候选仅输出计划覆盖内已有目标日期，其他股票原样保留。close类展示字段也要随新价格更新，不能以计数碰巧没变就跳过价格字段。
同一计算段一次计算并分日期输出，候选/提交使用20.5—20.9的记录；完成后pending nineturn清零，追加一条日九转观察说明引用真实计划和数量，不伪造全市场ordinary checks通过。
不调用`rebuild_qfq_nineturn_scope`完整入口，不复制backup、失败回换或finally清理成果；不改分钟九转逻辑。

`asset_guards/stock_daily_qfq_factor_repair.py`新增统一消费接口：

```python
stock_daily_qfq_history_consumption_status(*, lake_root, staging_root,
    consumer: str, target_trade_date: str, source_plan_id: str | None = None)
    -> QfqHistoryConsumptionStatus
```

daily模式要求baseline已验收、无maintenance/未解决、目标日已reconcile、对应消费者没有更早pending；
repair模式要求明确source_plan_id/hash、价格PRICE_COMPLETE且输入输出证明匹配，只允许对应计划读取，不能传bool绕过。
返回`ready/reason_code/as_of_trade_date/source_plan_id/source_revision`及计数，不返回行情明细。
调用位置固定在趋势日更asset/sensor、日九转日线asset/sensor、Prod日九转发布asset/sensor的源读取之前。
Prod发布还需九转当前输出记录与价格计划一致；本轮仅实施阻断合同，不执行Prod重发或改旧serving数据。
研究直接读文件不受函数强制控制，正式历史修复维护期对这些读者明确暂停安排，不宣称仅改sensor就能隔离所有外部读者。

### 20.15 完成metadata、状态函数和错误码

原protected名称`gold_stock_daily_qfq_factor_repair_plan_evaluated`保留，partition取计划as_of，blocking=True。
`build_gold_stock_daily_qfq_factor_repair_check_metadata(plan, completion, producer_run_id)`必须先调用20.9的完整断言，
再用现有`build_check_metadata`生成，不裸写另一套顶层metadata。

必填extra_metadata为：`schema_version=2`、`plan_id/plan_sha256`、`source_revision`、`pricing_version`、
`as_of_trade_date`、`reconcile_start_trade_date/reconcile_end_trade_date`、`repair_start_trade_date/repair_end_trade_date`、
`selected_partition_count`、`rewritten_partition_count`、`unchanged_partition_count`、`pending_partition_count=0`、`failed_partition_count=0`、
`repair_required`、`repair_required_code_count`、`repair_required_codes_hash`、`repair_required_codes`、`repair_required_codes_truncated`、
`completion_ref/completion_sha256`、`upstream_batch_id`、`producer_run_id`、`covered_key_count`、`unresolved_count=0`。
其中repair_start/end是实际价格输出范围，不等同于原因日范围；无修改时为空且selected/rewrite/unchanged都为0。
≤500股写完整有序代码；更多只写前20样本及truncated=true，完整范围从同hash计划读取，不能因此跳过其余股票。
新下游从计划取全范围，不继续使用“truncated就永远不能修”的旧自动合同。

状态函数替换为：

```python
gold_stock_daily_qfq_factor_repair_status(instance, *, staging_root,
    plan_id: str, plan_sha256: str) -> GoldStockDailyQfqFactorRepairStatus
```

它读取计划、completion.json，再用已知as-of精确读取这个protected check，
要求passed、blocking、partition、schema、plan/hash、input revision、全部计数与完成文件一致。
latest check属于别的计划时不得误用；完成记录表明已写事件但查询不到时`qfq_completion_event_missing`，可在队列内finalize补齐，不假装已绿。
数据/日期记录不匹配、缺文件证明、计数不等式失败分别返回明确not-ready，不回退旧合同。
`GoldStockDailyQfqFactorRepairStatus`增加plan/as-of/input revision、unchanged/pending/failed计数；由计划内部加载股票，cursor只取摘要。

`finalize_stock_daily_qfq_repair(context, plan)`分两步：

1. FILES_COMPLETE后只补匹配价格完成事件与PRICE_COMPLETE；已有事件匹配则直接补状态，价格计算/COPY为0。
2. PRICE_COMPLETE后只检查当前计划trend/nineturn完成记录和未解决项；齐全才COMPLETE，并更新reconciled_through、baseline和巡检日期索引。

普通reconcile没有价格变化时消费者明确记`NOT_REQUIRED`，有范围但该下游从未有覆盖则记`NOT_APPLICABLE`并附范围依据；
两者都不能掩盖已有覆盖缺文件。完整历史baseline首次验收必须审计集合无未知、全部REPAIR已提交，才允许reconciled_through跨过历史。
pending trend存在时QFQ sensor只等其独立repair sensor，不再创建新价格计划，避免覆盖尚未消费的完成身份。

错误码集中在本数据集合同，异常对象同时带中文说明和有界样本；下表锁定不可静默继续的分支：

| 错误码 | 触发条件/动作 |
| --- | --- |
| `qfq_history_baseline_missing` | baseline/执行记录不能证明已有历史；只允许人工历史audit初始化 |
| `qfq_config_legacy_fields` | 旧配置或手写stock_codes；解析即拒绝，无读写 |
| `qfq_source_missing` / `qfq_previous_source_unverified` | 源/前序事实不足；记UNKNOWN，不填0 |
| `qfq_source_changed` | 计划范围内源身份实际变化；局部重新审计/规划，旧候选不提升 |
| `qfq_as_of_regression` | 旧截止日试图覆盖新结果；拒绝 |
| `qfq_history_backlog_requires_plan` | 自动积压>10日或受影响>500股；保持位置、显示离线处理范围 |
| `qfq_candidate_invalid` / `qfq_scope_mismatch` | 结构、键、保留字段或允许范围不符；留候选和具体规则，不写正式文件 |
| `qfq_target_conflict` / `qfq_output_proof_missing` | 第三方改写、意外缺目标或提交归属不明；停止，不回换旧文件 |
| `qfq_progress_conflict` / `qfq_checkpoint_io_error` | revision冲突或进度保存失败；提交前不动文件，提交后留现场等待恢复 |
| `qfq_formal_write_requires_queued_job` / `qfq_concurrent_writer` | 绕过正式队列/并发条件失效；正式写入前拒绝 |
| `qfq_consumer_seed_unverified` | 递推seed无法证明；保持下游未完成，不随意初始化 |
| `qfq_budget_exceeded` / `qfq_sql_timeout` | 批次、空间、内存/SQL预算不满足；按预定边界缩小未完成批次或停止，不截断对象 |
| `qfq_completion_event_missing` / `qfq_completion_event_write_failed` | 事件未登记；已有文件保留，finalize只补登记 |

UI通过已有run日志、check metadata和sensor cursor显示阶段、当前对象、完成/总量、最后更新时间和下一步。
进度只报真实已完成文件/读取字节/已封存批次；心跳不增加业务完成量，未知ETA显示暂无法估算。
无需新页面、报警服务或消息发送权限。

### 20.16 配置来源和预算的唯一位置

不新增env、Settings项或数据库配置。运行意图只来自20.3的Dagster run config，保存在run与不可变计划；
所有规模预算由`run_contracts/stock_daily_qfq_repair.py`的`QfqRepairBudget`和一个`DEFAULT_QFQ_REPAIR_BUDGET`提供，
生成计划时记录其完整值和hash，writer/sensor不得各自手写不同数字。
日常500股限制引用既有常量而非重复定义；历史模式不把自动限制当作修复对象过滤条件。

| 名称 | 默认/来源 | 消费者、生效与运维可见性 |
| --- | --- | --- |
| `sensor_interval_seconds` | 600，合同常量 | 两个改造sensor定义；Definitions重载生效，Automation可见 |
| `automatic_trade_date_limit` | 10，合同常量 | QFQ sensor/自动计划；超限持续阻断 |
| `automatic_code_limit` | 原500常量 | QFQ自动计划和趋势自动准入；不限制批准历史计划 |
| `patrol_date_limit` | 500，合同常量 | 属性巡检/op；单次读取约1500个文件属性和≤8MiB记录 |
| `audit_batch_trade_dates` | 20，合同默认，写入计划 | 审计/价格准备；只对未完成批次减半，不改已封存批次 |
| `maximum_scope_trade_dates` | 4000，合同默认，写入计划 | 单次历史执行范围保护；不是历史截断起点，超过须分计划覆盖，不遗漏剩余日期 |
| `maximum_stock_count` | 10000，合同默认，写入计划 | 单次临时关系/集合上限；超限给出全部对象分批方案，不能过滤多出的股票 |
| `maximum_batch_rows` | 200000，20日×10000股上界 | Source/价格临时关系；超过先按日期减半；Python不fetch全部行 |
| `maximum_candidate_bytes` | 32GiB，合同默认，写入计划 | 单计划候选/中间结果预算；准备前估算、运行累计；不包含既有正式文件 |
| `sql_timeout_seconds` | 25，合同常量 | 有界SQL包装器；超时interrupt并停止/减小未完成批次 |
| `hash_chunk_bytes` | 1MiB，合同常量 | 文件hash；可检查取消并报告真实读取量 |
| `maximum_progress_bytes` / `maximum_patrol_record_bytes` | 64KiB / 8MiB | JSON读写/巡检；超过明确报错或减小单批，不能悄悄截断 |
| 正式Lake/staging根 | 既有DEFAULT_LAKE_ROOT/DEFAULT_LAKE_STAGING_ROOT | paths与正式准入；不增加别名或新目录层级 |
| DuckDB内存/线程/spill | 既有受控DuckDBResource配置 | 不在QFQ脚本覆盖；执行单记录实际配置和累计spill |
| 正式并发 | 现有dagster.yaml：QueuedRunCoordinator、全局1 | 所有正式写者执行前核实；本轮不改变全局配置 |

预算不是另一份“已完成”状态；运行完成位置只在20.4记录。
变更预算必须修改唯一合同、相应测试和原LLD，旧冻结计划不原地改hash。
如果现有正式范围超过单计划上界，完整审计结果仍保留；后续按原清单分段生成有覆盖关系的计划，全部完成前总体未完成。
这些是代码设计值，不声称是已获正式执行规模或测量通过。

### 20.17 读取、计算、恢复与最后验收的成本

设N为纳入的交易日、C为事件check key数、K为受影响日期文件、T为候选字节。
只读范围和预计开销必须先获得对应全局读取授权；以下模型供执行单按真实库存填值，不重新做五股原因审计。

| 路径 | 明确次数模型 | 允许保存/复用的成果 |
| --- | --- | --- |
| 日常repair tick | 1份progress；最多500日期记录和1500次stat；至多3个最新mat查询各limit1；1次C项批量check API；1次run查询limit1 | 不读历史OHLC；因子比较放到已选job。C项API内部约1+C条查询，不宣称只有1条 |
| 新增≤10日reconcile job | 相邻因子最多11份，1次集合diff；变化文件才局部核实；无变化无需重写历史 | 一份无变化/修复完成证明，重复tick不再建同任务 |
| 完整历史audit | 一次库存；因子必要列一次正式扫描并保存本次临时关系；Source/Gold按20日批各一次业务扫描 | 每批覆盖/异常/上下文和全部必要文件hash；不按股重扫 |
| hash成本 | 首次实际使用的每个源/目标身份一次顺序内容读取；与SQL读取是不同I/O，计入预算 | 同运行稳定身份复用；不是“整个任务只读文件一次”的虚假承诺 |
| 价格准备 | 有影响股票Source按段计算，已有目标保留行只读；每个实际目标至多1次完整COPY和1次范围校验 | 合格候选、输入版本、目标原版本、校验结果；不在正式提交时再算 |
| 趋势/九转 | 仅实际受影响对象及必要前缀至各自已有末端；段间保存seed/context | 每段候选/校验/末端状态；恢复从未完成段开始 |
| 正式apply | K条文件记录、每文件至多1次replace与对应持久记录；必要属性/归属hash | rename前后结果，已COMMITTED文件不再COPY/replace |
| 中断恢复 | 只识别既有记录及未完成单元；必要hash和未完成后缀 | 已封存批/段的业务SQL=0、COPY=0；明确不包括必要的小文件/身份核对 |
| 最后验收 | 汇总审计覆盖与完整文件记录，核对已提交归属；无变化输入不重读行情 | 全历史价格重算=0、指标重算=0、COPY=0；不逐日期扫DG绿灯 |

准备前空间估算至少包含T、临时因子/上下文、段间状态及现有DuckDB spill配额；
按当前目标字节和CREATE_MISSING行数估算，生成阶段预留，完成后累计结算，结束一次汇总。
不每秒递归目录，也不每文件重算全部空间。预算不足停止并保留已有成果，不引入备份或自动清理。
任一单元SQL超过25秒由同连接interrupt；未完成日期批减半后重新请求，最小1日仍超时停止并报告，不无限重试。
hash按块检查取消；文件COPY/校验/replace前后也检查取消，取消不领取新文件。
阶段与真实文件进度至少每30秒可见；SQL超时比该上界短，不通过假计数制造进度。

本轮没有运行容量实验或生产性能测量。开发的第一批隔离验收必须验证最大单批、500日期属性查询、调用计数和中断；
正式执行前只补缺少的真实库存/字节与必要最小样本，不重跑已保存完整审计。

### 20.18 测试文件、独立夹具和断言

表内新增测试名是实施要求，不代表本轮已经运行。测试数据来自已保存五股样本、独立字面数据和真实临时Parquet；
Dagster相关测试用临时instance和真实event/运行来源字段，不用正式库或token。

| 文件/用例 | 必须断言，含正常对照 |
| --- | --- |
| `test_stock_daily_qfq_factor_repair_sensor_contracts.py::test_success_without_remote_origin_remains_actionable` | 建正常来源与remote_job_origin=None的成功run；旧run-status路径漏接可复现，新sensor不读触发来源仍选相同未完成日期 |
| 同文件`test_progress_not_advanced_on_submission_or_failure` | QUEUED/STARTED不重复提交；FAILURE/CANCELED持续阻断；attempt2同计划恢复；不能因用过run_key永久丢项 |
| 同文件`test_gap_older_than_window_is_not_discarded` | 长停机、最早缺项、>10日积压、>500股分别保留；正常≤10日可推进；无变化仅确认一次 |
| 新`test_stock_daily_qfq_history_records.py` | JSON损坏/revision冲突/越界路径/symlink拒绝；合法临时路径可用；进度/文件记录有限大小；缺baseline不默认为成功 |
| 新`test_stock_daily_qfq_history_audit.py::test_full_union_finds_missing_and_extra_keys` | Gold整分区缺失、缺一股、额外键、重复源、缺因子都被分类；正常退市/停牌不误报；不能只比行数 |
| 同文件`test_completed_audit_batch_is_not_scanned_twice` | 两批中完成第一批后停止；续跑第一批业务查询=0；原输入真变只重审相应批，重启本身不失效 |
| 同文件`test_changed_source_invalidates_only_actual_dependencies` | 同一源文件改另一股票时已封存目标复用；改本股close使当日和下一实际报价范围失效；后继计划引用合格旧成果，不因全局plan/source hash变化重算所有单元 |
| 同文件`test_audit_reference_is_independent` | 生产builder替身直接抛错，审计仍能按独立预期工作；四价、昨收、量额及容差边界有字面expected |
| `test_stock_daily_qfq_contracts.py::test_price_relation_golden_values` | source close=10、row factor=1.5、as-of=2得7.5；前close=8、factor=1得昨收4、涨跌3.5和87.5%；expected为字面，不调用被测函数生成 |
| 同文件`test_long_suspend_is_not_first_source_row` | >20交易日无报价但有历史源时取真实前序；缺factor失败；真实第一条及已验证Lake覆盖首条可为0；合法正常前日不误拦 |
| `test_stock_daily_qfq_repair_contracts.py::test_merge_missed_dates_and_reject_asof_regression` | 同股多次变化合并、新统一截止日；旧任务拒绝；同as-of源值更正仍重新规划；退市取最后因子；更正其较早最后因子仍触发全历史分母更新 |
| 新`test_stock_daily_qfq_candidate_writer.py` | 正常REPLACE/KEEP/明确CREATE_MISSING；范围外行/量额/未改字段守恒；第三方改目标、缺原目标、错键/类型拒绝 |
| 同文件`test_rename_before_checkpoint_recovers_without_copy` | 真实临时os.replace后故障；恢复补COMMITTED，COPY=0、replace=0；目标是第三种内容失败；目标仍旧则只继续原rename |
| 同文件`test_event_failure_does_not_undo_files` | 文件已提交但事件失败不回换；finalize仅补事件；事件已写而记录失败时不重复写事件 |
| 新`test_stock_daily_qfq_history_patrol.py` | 旧Source改写无事件也能被发现；只改属性但内容同值只更新属性；新增/缺失文件、索引缺证明有明确结果；末端轮转回起点；自己刚修复文件不再触发 |
| 新`test_stock_daily_qfq_formal_write_admission.py` | 队列1+正常来源可写；队列>1、无队列、本地直接运行拒绝；其他QUEUED不误报并发；另一个STARTED写者拒绝；dry-run正式根不写 |
| `test_stock_daily_trend_channel_m4.py`、`test_stock_daily_trend_channel_m5.py` | 删除“日期数减1/自己拼producer批次”预期，改为source_plan；任意历史起止、首影响前seed污染、结果/state缺一边、state提交后result前中断；正常范围成对完成 |
| 新`test_stock_daily_qfq_nineturn_repair.py` | lag4与连续计数超20日接续；前段封存后恢复不重算；显示价格一起改；其他股票不变；不调用旧scope rebuild/backup/清理函数 |
| 日九转/趋势/Prod sensor和asset契约测试 | 日常未完成阻断，匹配repair计划可读不死锁；旧绿灯/旧source版本不通过；完整结果可恢复正常日更；不改变分钟分支 |
| `test_run_contract_static_gates.py` | 旧QFQ批次builder与旧config入参引用清零；无新增状态asset/DB/锁/旧工具导入；QFQ正式writer不再旁写固定.tmp；无逐日期event深扫或Python行情行循环 |
| 新`test_stock_daily_qfq_repair_costs.py` | 500日期巡检无OHLC SQL；batch API按C项/10日期有界，materialization为None即使is_current也拒绝；已完成恢复/最后验收业务SQL和COPY=0 |

五股回归至少固定保存报告中的一条原Source/因子/旧Gold及独立正确值，证明旧数据确实失败、新候选正确。
具体夹具拟保存为`tests/fixtures/stock_daily_qfq/missed_repair_202607.json`，只摘取已有证据，不请求源站：
600020.SH、2026-07-10，原close=3.76、当日factor=4.6443、截至2026-10-16最后factor=4.7974，旧Gold.close=3.76；
正确close字面值为3.6400066702797353。必须断言旧值失败、候选在既定容差内通过，不从被测SQL反推expected。
用两次合理因子变化的正常样本证明门禁不会把正常更新当作错误。
最大单批测试使用明确生成规则的临时数据验证资源和读取模型，不把它当真实源端验收。

固定实现只运行一条包含audit、prepare、取消/恢复、提交及消费者的完整隔离链，不另跑三份全链做正常/续跑/audit对比。
隔离实例中实际事件与文件分别读回；mock只替代未声称验收的远程发布，不用mock替代rename和schema。
正式最小样本和全量执行仍按对应读写授权，不把本轮文档修改当作运行许可。

### 20.19 开发顺序、迁移对账与实施前检查

按下面顺序在当前dev-interface实施，每一步有明确可交付内容；不先修数据再补机制：

1. **合同与记录。** 新类型/config、记录/路径、身份、队列准入和恢复；完成20.18对应文件/状态正反测试。旧调用方同时迁移，不能保留一段旧参数兼容。
2. **公式抽取与候选。** 纯relation价格SQL、真实前序定位、完整候选验证；字面/真实样本回归；日更及history writer统一入口，关闭正式CLI直写绕路。
3. **审计与计划。** 一次检查/局部失效/作用范围，完整文件/键集合和缓存上下文；证明已完成批次不重审。此步只用隔离数据，不提前扫正式全史。
4. **触发与完成。** 新普通sensor、真实batch状态adapter、文件巡检、no-op和完成事件；旧run来源不再影响遗漏发现，提交不推进完成位置。
5. **下游迁移。** 趋势候选与成对恢复、日九转分段接续、日常/发布门禁；准确起止由计划提供，清除旧批次拼接和日期数减1。
6. **集中验收。** 必要定向回归与一条隔离取消/恢复全链；统计调用/COPY/replace与已完成复用；逐条对照20.1硬要求。
7. **正式数据阶段。** 填精确执行单、确认全局读和写入范围后，一次完整历史审计→冻结范围→准备真实候选→受控提交→DG下游→汇总证明；不重做五股或25股已完成专项。

具体实施文件以20.2和20.18为白名单；新增Python不允许阶段编号或宽泛utils名称。
本次改变的正式名称仅类型/函数/config合同；asset/job/check名称保持，两个repair sensor名称保持但类型改为普通sensor。
部署切换时先按获准维护步骤停止相关QFQ/趋势/日九转及发布自动消费，保存原sensor状态/cursor；
只对这些job的非终态runs做有界清点，已有旧config任务先结束或经明确授权取消，不能让新代码接旧config运行。
核对新Definitions和队列合同后，用受控历史动作建立完整baseline、完成下游，再按保存状态恢复日常接续。
新代码缺baseline时会明确阻断，这一切换顺序不能省略；本轮不执行启停、重载或运行清点。
实施时同步以下原文档，不把当前拓扑直接写成新代码已经上线：

- 本方案与LLD。
- `dagster-run-key-governance-optimization-plan.md`、`dagster-run-key-governance-low-level-design.md`：QFQ按请求/计划+attempt，取消producer_run_id身份。
- `dagster-run-contract-governance.html`、`dagster-asset-job-topology.html`：sensor类型、目标job和分类。
- 趋势通道及日九转原专项的实际输入完成合同、范围和恢复说明；不复制第二套规则，以本节为QFQ计划定义。

配置审计已在20.3/20.16给出唯一来源与消费者；生产启用前必须验证实际队列合同未变，不能在文档阶段改全局并发。
真实全史规模、文件字节和执行时间留给经批准执行单；这是正式执行事实，不能在无读取授权时伪造数字。
所有代码路径已有范围上界、失败/恢复分支和验收方法；未满足隔离成本/正确性门禁时停止推进，不靠增加内存或删对象凑通过。
