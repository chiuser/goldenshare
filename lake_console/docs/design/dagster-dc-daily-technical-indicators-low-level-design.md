# `dc_daily` 技术指标 Gold 数据集 LLD

> 状态：P4 Gold asset、核心 check、normal job、bounded readiness 与默认 STOPPED sensor 已完成；repair、Bootstrap、事件验收和正式启用尚未开始。
>
> 本文建立在 [`dagster-dc-daily-technical-indicators-plan.md`](dagster-dc-daily-technical-indicators-plan.md) 的冻结口径上。若实现前发现代码事实冲突，必须先更新方案和本 LLD，不能在代码里留下隐式兼容分支。

## 1. 设计输入与硬约束

本 LLD 受以下硬约束控制：

1. 只有一个 Gold asset：`gold_dc_daily_technical`。
2. 输入是 `silver_dc_daily`，按 `cn_a_index_trade_days` 分区，业务序列按 `(ts_code, category)` 隔离。
3. MA 预热不足写 `NULL`；BOLL 三线预热不足写 `NULL`；不写 0 冒充结果。
4. BOLL 固定 `N=20,P=2`，标准差冻结为总体标准差 `ddof=0`，使用 `stddev_pop` 等价实现。
5. MACD/KDJ 参数与分钟线实现一致，但不复制分钟线的高频 state asset 拓扑。
6. 生产 blocking check 只保留一个结构性合并 check，不重算完整公式。
7. normal sensor 最近 10 个 expected dates、一个 DuckDB connection、最多一个 RunRequest、零 Dagster event history 查询。
8. repair 只能消费显式 upstream batch，不允许从历史 event 猜范围。
9. 任何 writer 都必须 `staging -> validate -> atomic replace`；已存在但错误的目标文件不得静默覆盖。
10. 本轮只写文档，不运行 `dg`、job、sensor、Bootstrap，不写 lake 或 Dagster DB。

## 2. 已审计代码与影响面

### 2.1 输入资产与合同

| 当前文件 | 已核对事实 | 对新实现的影响 |
| --- | --- | --- |
| `orchestrator/defs/assets/dc_board_silver.py` | `silver_dc_daily` 是 `cn_a_index_trade_days` 分区 asset，依赖 `raw_tushare_dc_daily`，通过 writer 写分区文件 | 新 Gold 只依赖 Silver；不把 Raw 依赖直接带入 Gold |
| `orchestrator/defs/run_contracts/dc_board.py` | `DC_DAILY_HISTORY_START_DATE=2024-01-02`，分区和 category 合同已存在 | 新 Gold 复用日期起点和 `cn_a_index_trade_days` |
| `orchestrator/defs/run_contracts/asset_column_schemas.py` | `SILVER_DC_DAILY_SCHEMA` 明确列出 close/open/high/low 和 category | 新 Gold schema 以此为输入合同，不能用 `SELECT *` 隐式吸收列变更 |
| `orchestrator/defs/paths.py` | Raw/Silver board 路径按 `trade_date` 分区 | 新增同样风格的 Gold path helper |
| `orchestrator/defs/catalog/lake_assets.py` | Raw/Silver catalog 有分区、source 和性能合同 | 新 Gold 必须新增 catalog entry、blocking check 映射和治理规则 |
| `orchestrator/defs/assets/stock_daily_qfq.py` | 日期 Gold 资产使用 DuckDB resource、metadata 和原子写入模式 | 复用其资源/metadata 结构，不复制其业务字段或 qfq 语义 |

### 2.2 指标与自动化参考

| 当前文件 | 已核对事实 | 新实现如何复用 |
| --- | --- | --- |
| `orchestrator/defs/assets/stk_mins_qfq_macd_kdj.py` | MACD 12/26/9、KDJ 9/3/3、HHV/LLV 边界、EMA/K/D seed 已实现 | 复用公式常量和数值 fixture；不复用分钟线的大规模 state asset |
| `orchestrator/defs/sensors/dc_board_silver_sensor.py` | 最近 10 日、batch readiness、单连接、无 event history、materialized check failure 不自动覆盖 | 新 normal sensor 使用相同热路径原则 |
| `orchestrator/defs/jobs/dc_board_silver.py` | job 只负责 selection，单资产/单分区 | 新 normal/repair job 保持 selection 与业务计算分离 |
| `orchestrator/defs/asset_guards/dc_board_silver_lake_readiness.py` | Silver readiness 为内存态 batch 状态，不持久化 | 新 Gold readiness 复用该状态模型和 failure 语义 |
| `orchestrator/defs/run_contracts/run_keys.py` | run key 使用统一 builder | 新 job/sensor 禁止手写 run key 或反解析历史 key |

### 2.3 CodeGraph 影响面

本轮已用 CodeGraph 以仓库根 `/Users/congming/github/goldenshare` 做了 `dc_daily -> silver_dc_daily -> writer/schema/path/catalog` 和 `stk_mins_qfq_macd_kdj -> calculation/check/sensor/job` 的探索与调用链核对。当前只新增文档，不发生依赖矩阵或架构边界变化；进入代码阶段后，新增 catalog、asset、check、readiness、job、sensor、repair helper 必须重新做 callers/callees/impact 核验。

## 3. 拟新增文件与职责

以下是实现阶段的稳定文件边界，不在多个文件之间重复实现公式：

| 文件 | 职责 |
| --- | --- |
| `orchestrator/defs/run_contracts/dc_daily_technical.py` | 参数、字段、起点、性能预算、reason code、版本常量 |
| `orchestrator/defs/paths.py` | `gold_dc_daily_technical_path(lake_root, trade_date)` |
| `orchestrator/defs/run_contracts/asset_column_schemas.py` | Gold 输出 schema |
| `orchestrator/defs/asset_guards/dc_daily_technical_quality.py` | check/readiness 共用 predicates、schema、有限样本规则 |
| `orchestrator/defs/assets/dc_daily_technical.py` | Gold asset、writer、staging promote 和 metadata |
| `orchestrator/defs/checks/dc_daily_technical_checks.py` | 一个 partitioned core check |
| `orchestrator/defs/asset_guards/dc_daily_technical_lake_readiness.py` | 最近 10 日 Gold batch readiness |
| `orchestrator/defs/jobs/dc_daily_technical.py` | normal update job 和 repair job selection |
| `orchestrator/defs/sensors/dc_daily_technical_sensor.py` | normal update sensor |
| `orchestrator/defs/assets/dc_daily_technical_repair.py` | repair range planner/执行辅助；不新增 asset |
| `orchestrator/defs/sensors/dc_daily_technical_repair_sensor.py` | 消费显式上游 repair batch |
| `orchestrator/defs/catalog/lake_assets.py` | Gold catalog、性能合同和 check 治理映射 |
| `orchestrator/tests/test_dc_daily_technical_*.py` | 公式、writer、readiness、sensor、repair、性能和静态门禁 |

如果当前仓库把 repair helper 放在 `asset_guards` 而不是 `assets`，实现时必须以现有模块边界为准，但不能让 repair sensor 直接读 lake 后自行复制写入逻辑。

## 4. Contract 常量与配置审计

第一版不新增运营可调配置；固定参数写入版本化 contract 常量：

```text
DC_DAILY_TECHNICAL_HISTORY_START_DATE = 2024-01-02
DC_DAILY_TECHNICAL_MA_PERIODS = (5, 10, 15, 20, 30, 60, 120, 250)
DC_DAILY_TECHNICAL_MACD = (12, 26, 9)
DC_DAILY_TECHNICAL_KDJ = (9, 3, 3)
DC_DAILY_TECHNICAL_BOLL = (20, 2)
DC_DAILY_TECHNICAL_BOLL_STD_DDOF = 0
DC_DAILY_TECHNICAL_SENSOR_WINDOW_LIMIT = 10
DC_DAILY_TECHNICAL_INDICATOR_VERSION = "v1"
```

`params_key` 必须由这些常量确定性生成，例如：

```text
ma_5_10_15_20_30_60_120_250__macd_12_26_9__kdj_9_3_3__boll_20_2
```

若后续确需修改性能阈值或 repair 最大范围，必须先完成配置项审计：默认值、来源、持久化位置、消费者、生效方式、运维可见性、测试门禁。不能把同一参数散落在 sensor、writer、文档和测试中。

## 5. 输入扫描与目标日期规划

### 5.1 日期计划

`cn_a_index_trade_days` 是日期事实源。writer 接收到一个目标 `trade_date` 后，先验证该日期属于 expected calendar，并生成目标日之前所需的显式 Silver path 列表。禁止直接对 lake root 做无界 `glob("**/*.parquet")`。

当前输入范围是 611 个交易日，理论上需要读取 611 个 Silver 日期文件；实现应优先在一个 DuckDB connection 中注册显式文件列表，按列投影读取：

```text
ts_code, trade_date, category, close, high, low
```

不读取指标不需要的 `amount/vol/turnover_rate` 等列。

### 5.2 输入事实检查

先在临时 DuckDB relation 中完成：

1. `trade_date` 为 DATE 且在目标日期之前；
2. `(ts_code, trade_date, category)` 唯一；
3. `close/high/low` 为有限数值，身份字段非空；
4. `category` 为合同内的三类值；
5. 序列按 `(ts_code, category, trade_date)` 排序；
6. 发现源重复、日期越界、schema 漂移或非法数值时 fail closed。

不在 Python 中把 611 个文件先读成全历史对象列表再计算；Python 只传文件路径和少量摘要，数据计算留在 DuckDB。

## 6. DuckDB 计算计划

### 6.1 CTE 顺序

生产查询按以下逻辑组织，最终只返回目标日期：

```text
source_files
  -> normalized_source
  -> source_key_guard
  -> ordered_series
  -> observation_count
  -> rolling_windows
  -> boll_and_kdj_windows
  -> ema_series
  -> macd_series
  -> target_date_projection
  -> output_contract_projection
```

`ordered_series` 的分组键永远是 `(ts_code, category)`。`observation_count` 使用该分组的 `row_number()`，不能用全局行号。

### 6.2 MA/BOLL/KDJ 窗口

窗口采用 `ROWS BETWEEN ... PRECEDING AND CURRENT ROW`，因为口径是有效观测数，不是自然日差值：

- MA_N 使用 `N-1 PRECEDING`；
- BOLL 使用 19 PRECEDING；
- KDJ 使用 8 PRECEDING；
- `COUNT(close)` 达到窗口长度后才释放对应数值；否则 `NULL`。

KDJ 先在 SQL 中得到每行 `HHV/LLV/RSV`，`HHV=LLV` 时 RSV=50。K/D 的递推不允许按 Python 大表逐行处理；实现必须采用经过 benchmark 的 set-based EMA/递推策略，且公式 fixture 要逐值对齐分钟线参考实现。

BOLL 标准差必须显式使用总体标准差：

```text
stddev_pop(close over last 20 observations)
```

不能调用没有明确 `ddof` 语义的默认 `stddev`，也不能直接照搬 Pandas `.rolling().std()` 的默认 `ddof=1`。测试使用人工 20 点 fixture 验证 `ddof=0`，并与 TA-Lib 或等价独立实现逐值对齐。

### 6.3 EMA/MACD 实现约束

MACD 的 EMA 是有序递推。生产实现可以采用：

- 与分钟线实现一致的 set-based 分段/闭式 EMA；或
- 经过性能验证的 DuckDB SQL 递推辅助。

不能直接用未验证的递归 CTE，也不能退回 Python `for row in rows`。实现选择必须在 P1 性能测试中以“数据行数、CPU、内存、临时空间、耗时”做对照，不能凭“SQL 看起来更优”决定。

首行 seed：fast/slow EMA 以首个 close，DEA 以 0。新序列独立初始化，不能串接其它 code/category。

### 6.4 输出投影

目标日输出：

- 只保留同日 Silver 中存在且通过输入门禁的 `(ts_code, category)`；
- `close` 原样保留；
- `observation_count` 从 1 开始；
- warmup 字段明确写 SQL `NULL`；
- `params_key`、`indicator_version` 为常量；
- 输出 schema 与 contract 严格一致。

不在输出文件中写调试列、窗口起点、失败样本或完整来源文件列表；这些进入有限 materialization metadata / 离线报告。

## 7. Writer、事务与原子替换

### 7.1 结果对象

建议 writer 返回内存态 `DcDailyTechnicalWriteResult`，至少包含：

```text
trade_date
target_path
source_file_count
source_row_count
written_row_count
series_count
null_warmup_counts
duplicate_key_count
input_rejection_count
duckdb_elapsed_ms
parquet_write_elapsed_ms
validation_elapsed_ms
total_elapsed_ms
peak_memory_bytes
staging_path
```

不把完整 code/category 列表塞进 cursor；失败只保留有限样本。

### 7.2 写入阶段

```text
validate target date and source paths
  -> DuckDB temp relation
  -> compute indicators
  -> COPY result TO unique staging parquet
  -> re-read staging schema/date/key/row-count
  -> compare target path conflict state
  -> os.replace(staging, target)
```

目标不存在才 promote；目标存在且当前 contract 通过则按幂等策略跳过；目标存在但错误则停止，不覆盖。进程异常、DuckDB 错误、Parquet 回读失败时，既有目标必须保持原样，staging 文件清理到可审计状态。

不把写入和 Dagster event 写入放在同一事务里；event 失败不能回滚已经验证通过的 lake 文件。

## 8. Core check 详细规则

`gold_dc_daily_technical_core_check`：

- `asset=gold_dc_daily_technical`；
- `partitions_def=cn_a_index_trade_days`；
- `blocking=True`；
- 正式路径每次只接受一个 partition。

check 只读取当前目标 Gold 文件和同日 Silver 文件，用 DuckDB 聚合验证：

```text
file_exists_and_rows_positive
schema_matches_contract
partition_date_matches_trade_date
business_key_not_null_and_unique
gold_keys_equal_silver_keys
close_matches_silver_close
observation_count_starts_at_one_and_is_monotonic
warmup_null_rules_hold
post_warmup_values_are_finite
params_and_version_match
```

失败 metadata 必须使用共享 builder，至少包含 `failed_rules`、`reason_code`、`partition_key`、`checked_row_count`、`failed_row_count` 和有限样本。check 不计算“正确公式值”来与自身比较，不新增公式 check。

## 9. Batch readiness 与 normal sensor

### 9.1 Readiness

`batch_gold_dc_daily_technical_lake_readiness(...)` 输入：一个 DuckDB connection、lake root、expected dates、registered dates和 source readiness map。它只规划最近 10 日 Gold 文件，批量读取文件聚合结果，返回现有内存态 `ContinuityBatchReadiness`。

每个日期状态区分：

- 缺 Gold 文件：`materialized=False`，可触发；
- Gold 文件存在但核心语义失败：`materialized=True, checks_passed=False`，人工处理；
- Gold ready：ready；
- 扫描异常：`scan_error`，fail closed。

check/readiness 共享 `dc_daily_technical_quality.py` predicates。不得实现一个只检查行数的快速版本。

### 9.2 Sensor

`gold_dc_daily_technical_update_job_sensor`：

1. 读取最近 10 个 expected date；
2. 检查 `cn_a_index_trade_days` registered gap；
3. 批量读取 Silver readiness；
4. 批量读取 Gold readiness；
5. 选择第一个 Gold not-ready 日期；
6. 若 Silver first-not-ready 早于或等于目标，skip；
7. 目标是“文件存在但 check 失败”，skip；
8. 否则用 `build_run_request` 和 `build_asset_update_run_key` 提交一个 RunRequest；
9. 用 `build_sensor_cursor` 写小型 ASCII cursor。

sensor 禁止：逐日 Dagster readiness、`instance.get_event_records`、Tushare/Prod DB、完整 candidate 列表、逐文件错误明细和大对象 cursor。

## 10. Repair 协议与实现

### 10.1 上游 batch 合同

在启用 repair sensor 前，上游 Silver repair 入口必须能产生并稳定读取以下 bounded metadata：

```text
upstream_batch_id
status=ready
source_revision
source_repair_start_trade_date
source_repair_end_trade_date
indicator_recompute_start_trade_date
indicator_recompute_end_trade_date
context_start_trade_date
target_frontier_trade_date
affected_date_count
affected_series_count
affected_series_hash
truncated=false
selected_partition_count
```

这里必须区分两个范围：

- `source_repair_*`：Silver 实际被修正的源数据范围；
- `indicator_recompute_*`：Gold 指标必须重新计算的有效范围。

MA250 至少需要足够的历史窗口；MACD EMA 具有递推影响，源数据修正后后续结果可能持续变化。若没有可验证的 EMA baseline，`context_start_trade_date` 必须回到指标历史起点，不能为了性能擅自截短。这个范围由上游 repair planner 或统一 repair status helper 计算并写入，Gold sensor 不自行推断。

这个 metadata 可以来自已审计的统一 repair status helper，但不能由新 sensor 自己扫描 event history 拼出来。若当前 Silver repair 入口还不能提供，P5 必须先补齐协议生产端；否则 repair sensor 保持 `STOPPED`。

### 10.2 Repair sensor

sensor 只读取最新、明确、ready 的上游 batch，验证：

- 范围在 expected calendar 内；
- start <= end；
- `truncated=false`；
- source revision 与 lake 事实匹配；
- 范围未超过修复预算。

通过后提交一个 repair RunRequest，config 传完整 batch identity，不把日期写进 run key 后再反解析。无效 batch、缺 metadata、范围超限时 skip + ASCII reason code。

### 10.3 Repair job

repair job 只选择 `gold_dc_daily_technical` 及其 check，接收 explicit `indicator_recompute_start_trade_date`、`indicator_recompute_end_trade_date`、`context_start_trade_date`、`source_revision`、`upstream_batch_id` 和必要的 series scope。它读取 context 起点到重算终点的最小必要历史上下文，批量重算有效范围内日期，再按日期 staging/promote。不能把 source repair 起止日期直接当作 indicator recompute 起止日期。

单次 repair 不得从 2014 起点无条件重算到当前，也不得改成每个日期单独提交一个 Dagster run。范围、文件数、耗时或输出行数超预算时整批 fail closed。

## 11. 测试矩阵

### 11.1 公式 fixture

- MA 各 N 在不足 N 和恰好 N 时的 NULL/数值边界；
- category 隔离，不能跨 category 串指标；
- 稀疏日期按有效观测计数；
- MACD 首行 seed、DIF/DEA/MACD 倍率；
- KDJ `HHV=LLV` 时 RSV=50、K/D seed；
- BOLL 20 个窗口不足时全 NULL；
- `ddof=0` BOLL 人工 fixture 与 TA-Lib/等价实现逐值对齐；
- params/version 固定且可识别。

### 11.2 Writer 与数据安全

- 输入重复、日期错位、schema 漂移、非法 category fail closed；
- 输出键集合与 Silver 完全一致；
- source/output row count 对账；
- staging schema 回读失败不替换目标；
- 已存在正确文件跳过；已存在错误文件不覆盖；
- 重跑不追加重复；
- 异常后 staging 清理可审计。

### 11.3 Dagster 合同

- asset/check/job/sensor 名称和分区合同稳定；
- check 显式 `cn_a_index_trade_days`，多分区调用 fail closed；
- job 不选择其它层资产；
- normal sensor 最多一个 RunRequest；
- repair sensor 不调用 `get_event_records`；
- cursor ASCII 且小于 8 KB；
- check 没有被拆成每指标一个 event；
- catalog governance 映射完整。

## 12. 性能测试与验收阈值

P1 必须使用当前 lake 事实和临时合成样本双轨测试，禁止只测 1,000 行 toy data：

| 场景 | 测试规模 | 记录指标 | 暂定门禁 |
| --- | --- | --- | --- |
| 单目标日 | 611 日历史上下文，输出 1 日 | 读/算/写/回读/内存 | <= 15 秒，超限停止优化 |
| 10 日 batch readiness | 10 Silver + 10 Gold 文件 | 文件数、连接数、耗时、event API 次数 | < 10 秒，event API=0 |
| 全历史 Bootstrap | 596,200 行，611 日 | 全部读/算/写、20 日批次、磁盘、峰值内存 | 无无界增长、无 Python 行循环 |
| repair 20 日 | 20 日输出及上下文 | 总耗时、文件数、行数、staging | <= 60 秒，超限 fail closed |
| repair 250 日 | 250 日输出及上下文 | 同上 | 必须单独 benchmark，不通过则禁止该范围自动化 |

查询、写入、回读分别计时。若使用递归 SQL 或临时 spill，必须报告实际 temp 空间；不可接受的结果包括 sensor 接近 60 秒 RPC deadline、全历史 event 扫描、逐行 Python 计算、重复扫描同一输入文件和未解释的内存增长。

### 12.1 P1 实测结果与实现约束（2026-07-15）

本阶段只读验证使用当前正式 lake 的 611 个 `silver_dc_daily` 分区文件和临时 Gold fixture；未写正式 lake、Dagster DB、event 或运行任务。报告：
`/private/tmp/dc_daily_technical_p1_report_20260715.json`、
`/private/tmp/dc_daily_technical_p1_memory_report_20260715.json`。

- BOLL 20 点 fixture 的总体标准差为 `5.766281297335398`，DuckDB `stddev_pop` 与独立计算一致；样本标准差为 `5.916079783099616`。
- 40 行 MACD/KDJ fixture 与独立 Python 递推的最大误差为 `1.14e-13`。
- 最近 10 日 readiness：扫描 10 个 Silver + 10 个临时 Gold 文件，使用 1 个 DuckDB connection，`8.13ms`，Dagster event history/Tushare/Prod DB 均为 0 次调用。
- 隔离进程的直接分区并行写出：单目标日 `0.664s / 526MB`；20 日 `0.675s / 553MB`；250 日 `1.013s / 992MB`；全历史 `1.585s / 1.56GiB`。该方式会在部分日期生成多个 parquet 文件，因此不能进入正式 writer。
- 有界写出验证：先执行一次完整 set-based SQL 到 DuckDB 临时关系，再按交易日逐个 `COPY` 到 `part-000.parquet`。20 日 `2.52s / 490MiB / 20 文件`；全历史 `9.57s / 511MiB / 611 文件`，输入文件只扫描一次。

P1 通过，但正式 writer 必须固定采用“单次临时关系 + 逐交易日单文件 COPY + staging 回读 + 原子 promote”。禁止直接使用并行 `COPY ... PARTITION_BY(trade_date)`，禁止使用 Python 大表逐行计算。repair 范围仍由显式 upstream batch 的 source/context 日期协议控制，不能因为本次性能通过而自动扩大到全历史。

## 13. 实施顺序与停机点

1. **P1 标准公式与性能**：完成 `ddof=0` BOLL fixture、MACD/KDJ 对照和完整 writer benchmark；失败则停止，不写代码。该阶段已于 2026-07-15 通过：只读使用当前 611 日 Silver lake 与临时 Gold fixture；BOLL 总体标准差、MACD/KDJ 逐值对照、10 日 readiness、单目标日/20 日/250 日/全历史写出均完成。报告位于 `/private/tmp/dc_daily_technical_p1_report_20260715.json` 和 `/private/tmp/dc_daily_technical_p1_memory_report_20260715.json`。
2. **P2 contract**：新增 constants/schema/path/catalog 草案和静态测试；catalog governance 必须同步。该阶段已于 2026-07-15 完成：新增 `run_contracts/dc_daily_technical.py`、`GOLD_DC_DAILY_TECHNICAL_SCHEMA`、`gold_dc_daily_technical_path(...)`、contract-only catalog entry、`trade_date` Gold partition model、展示名称和治理矩阵映射；新增 `tests/test_dc_daily_technical_contracts.py`，聚焦测试 `103 passed`。本阶段没有创建 active asset/check/job/sensor，也没有写正式 lake、Dagster DB 或 event。
3. **P3 writer**：已于 2026-07-15 完成。新增 `assets/dc_daily_technical.py` 作为无 decorator 的 writer，使用显式 Silver 文件列表、单 DuckDB source relation、set-based 窗口/闭式 EMA、staging 回读和原子替换；新增 `tests/test_dc_daily_technical.py`，P2/P3 聚焦回归共 `113 passed`。10 日、250 日和 611 日输入上下文性能分别为 `45.4ms`、`419.6ms`、`981.3ms`，报告为 `/private/tmp/dc_daily_technical_p3_report_20260715.json`。本阶段未写正式 lake、Dagster DB 或 event。
4. **P4 normal definition**：已完成。新增 active asset、唯一 partitioned core check、normal job、最近 10 日 batch readiness 和默认 STOPPED sensor；完成本地 definitions 加载、临时 lake readiness 和负向安全测试，未启用 sensor、未写正式 lake/DB/event。
5. **P5 repair prerequisite**：先核对/补齐 Silver repair batch metadata 生产端；没有明确 source revision 不接 sensor。
6. **P6 repair definition**：bounded repair job/sensor、超预算 fail closed、无 event history。
7. **P7 bootstrap**：dry-run -> sample -> full lake files -> aggregate audit；不写 Dagster event。
8. **P8 event acceptance**：文件完全对账后，materialization 与最近 20 日 check event 分开处理。
9. **P9 enablement**：手动启用 normal，再启用 repair；至少观察 3 个交易日。

每一步都必须保存临时报告；任一失败只保留已验证事实，不跳过阶段、不自动扩大范围。

## 14. 代码阶段的交付对账

实现完成时必须逐项回答：

- 新增文件是否与本 LLD 的职责表一致；
- 每个冻结常量是否只有一个来源；
- 公式 fixture 是否明确包含 `ddof=0`，并通过 TA-Lib/等价实现对照；
- check/readiness 是否共享 predicates；
- sensor 是否 10 日、有界、零 event history；
- repair 是否只消费 explicit upstream batch；
- writer 是否 staging、回读、原子替换；
- 数据湖、Dagster DB、运行事件是否在正确阶段才写入；
- 现有 `dc_board` M3-M9 行为是否无回退。

未完成项必须标明原因和风险，不能用“后续再看”算完成。
