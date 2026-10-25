# `dc_daily` 技术指标 Gold 数据集 LLD

> 状态：P8A Gold Bootstrap/lake 只读对账、P8C 临时样本 Bootstrap、P8D 正式 Gold 全量 Bootstrap 和 P9 事件验收均已完成。P10A 已启用 normal sensor；P7 repair sensor 仍未启用，尚未完成 3 个交易日观察。
>
> 本文建立在 [`dagster-dc-daily-technical-indicators-plan.md`](dagster-dc-daily-technical-indicators-plan.md) 的冻结口径上。若实现前发现代码事实冲突，必须先更新方案和本 LLD，不能在代码里留下隐式兼容分支。

> 2026-10-09 路径硬约束校准：本链 Gold 日更及限定 repair 候选统一放在现有 `/Volumes/datasource/data_lake_staging` 的 run-scoped DC 目录；正式 Gold 分区旁不再创建 `.tmp`。复用 DC candidate helper 做同文件系统检查，不改指标公式、实际行范围、repair 协议或入口参数。详见 [行情可用性 LLD](./dagster-dc-board-quote-availability-low-level-design-v1.md#5-写入与恢复)。

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
10. P8C 之前的代码阶段只做本地定义、单元测试和临时 lake 测试；P8D/P9 是单独批准的正式 Gold 文件写入与事件验收阶段，不运行 daily job，不启用 sensor。
11. Gold writer 读取历史 `silver_dc_daily` 时，每次 DuckDB `read_parquet` 最多传入 32 个文件；
    全部批次顺序加载到同一个临时 source relation，不能以一个超长文件列表同时打开全历史文件。

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
| `orchestrator/defs/assets/dc_daily_technical.py` | Gold writer、staging promote 和 metadata |
| `orchestrator/defs/assets/dc_daily_technical_asset.py` | active Gold asset wrapper |
| `orchestrator/defs/checks/dc_daily_technical_checks.py` | 一个 partitioned core check |
| `orchestrator/defs/asset_guards/dc_daily_technical_lake_readiness.py` | 最近 10 日 Gold batch readiness |
| `orchestrator/defs/jobs/dc_daily_technical.py` | normal update job，只选择 Gold asset 与核心 check；不承载 repair |
| `orchestrator/defs/sensors/dc_daily_technical_sensor.py` | normal update sensor |
| `orchestrator/defs/asset_guards/dc_daily_silver_repair.py` | P5 已落地的 `silver_dc_daily` repair batch 适配器 |
| `orchestrator/defs/assets/dc_daily_technical_repair.py` | P7 bounded repair writer；独立于 normal writer，负责 set-based 计算、逐日期 staging、全量校验和原子替换 |
| `orchestrator/defs/ops/silver_dc_daily_repair.py` | P7 Silver repair producer op；调用 P6 producer 并发布 scalar run tags |
| `orchestrator/defs/jobs/silver_dc_daily_repair.py` | P7 Silver repair producer job；不新增 asset |
| `orchestrator/defs/ops/dc_daily_technical_repair.py` | P7 Gold op；解析 batch、调用 writer、按目标日期写 partitioned events |
| `orchestrator/defs/jobs/dc_daily_technical_repair.py` | P7 op-based Gold repair job；不使用多分区 asset job |
| `orchestrator/defs/sensors/dc_daily_technical_repair_sensor.py` | P7 STOPPED run-status sensor；只读 producer tags 和当前 Silver lake，不扫事件历史 |
| `orchestrator/defs/bootstrap/dc_daily_technical_events.py` | P9 有界 Bootstrap 事件规划、样本写入、全量 materialization/最近 20 日 check 补录 |
| `orchestrator/defs/bootstrap/dc_daily_technical_events_cli.py` | P9 dry-run/sample/apply CLI；正式写入必须显式确认 |
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
  -> DuckDB source schema batches (at most 32 files each)
  -> one DuckDB temp relation populated by bounded batches
  -> compute indicators
  -> COPY result TO unique staging parquet
  -> re-read staging schema/date/key/row-count
  -> compare target path conflict state
  -> os.replace(staging, target)
```

目标不存在才 promote；目标存在且当前 contract 通过则按幂等策略跳过；目标存在但错误则停止，不覆盖。进程异常、DuckDB 错误、Parquet 回读失败时，既有目标必须保持原样，staging 文件清理到可审计状态。

不把写入和 Dagster event 写入放在同一事务里；event 失败不能回滚已经验证通过的 lake 文件。

`DC_DAILY_TECHNICAL_SOURCE_FILE_BATCH_SIZE = 32` 是 writer 的固定性能合同。每个批次先做
`SILVER_DC_DAILY_SCHEMA` 校验；第一批创建 `dc_daily_technical_source`，后续批次仅向同一临时
relation 追加。这样仍然以一次 set-based 指标 SQL 计算完整上下文，但不会因数百个独立
Parquet 文件被同一 `read_parquet([...])` 同时打开而耗尽文件描述符。批次仅改变输入装载方式，
不得改变日期范围、公式、输出、文件布局或 repair 语义。

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
producer_run_id
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
protocol_version
```

这里必须区分两个范围：

- `source_repair_*`：Silver 实际被修正的源数据范围；
- `indicator_recompute_*`：Gold 指标必须重新计算的有效范围。

MA250 至少需要足够的历史窗口；MACD EMA 具有递推影响，源数据修正后后续结果可能持续变化。若没有可验证的 EMA baseline，`context_start_trade_date` 必须回到指标历史起点，不能为了性能擅自截短。这个范围由上游 repair planner 或统一 repair status helper 计算并写入，Gold sensor 不自行推断。

这个 metadata 可以来自已审计的统一 repair status helper，但不能由新 sensor 自己扫描 event history 拼出来。若当前 Silver repair 入口还不能提供，P5 必须先补齐协议生产端；否则 repair sensor 保持 `STOPPED`。

#### P5 已落地的协议基础

代码审计确认，当前 `silver_dc_daily` 只有 normal asset/writer，没有可以直接提供 repair batch 的 Silver repair job。股票 QFQ repair 的 metadata 有自己的资产、字段和消费者，不是本数据集的 Silver source revision，禁止跨资产族冒用。

P5 已完成以下无持久化协议基础：

| 文件 | 职责 | 约束 |
| --- | --- | --- |
| `orchestrator/defs/run_contracts/silver_repair.py` | 通用 `SilverRepairBatch`、稳定 series hash、upstream batch id、plain/namespaced metadata 解析和日历范围校验 | 不导入 Dagster，不读 event history，不写 lake/DB |
| `orchestrator/defs/asset_guards/dc_daily_silver_repair.py` | 固定 `source_asset=silver_dc_daily` 的窄适配器 | 只能构造/解析显式 batch，不能扫描历史事件推断范围 |
| `orchestrator/defs/asset_guards/dc_daily_silver_repair_producer.py` | 从 Raw 重建有界 Silver source range、计算 source revision、比较旧/新 Silver 并生产 ready batch | 单 DuckDB connection；source <=20 日、indicator <=60 日；不读 event history |
| `tests/test_dc_daily_technical_repair_protocol.py` | producer/consumer 协议、范围、计数、版本、注册和预算的正负测试 | 不运行 job/sensor，不写 lake/DB |

字段语义已经写死：

- `source_repair_start/end_trade_date` 是 Silver 实际被修正的 source 日期范围；
- `indicator_recompute_start/end_trade_date` 是 Gold 必须重新输出的有效日期范围，必须覆盖 source repair 范围；
- `context_start_trade_date` 是指标计算读取的最早上下文日期，不能晚于 indicator recompute 起点；
- `affected_date_count` 必须等于 source repair 范围内 expected 交易日数；
- `selected_partition_count` 必须等于 indicator recompute 范围内 expected 交易日数；
- `affected_series_hash` 只保存稳定 hash，不把完整 series/code 列表写进 metadata；
- `source_revision` 是上游 Silver producer 提供的非空、可追溯版本，不由 Gold sensor 通过文件 mtime 或事件历史猜测；
- `producer_run_id` 用于 provenance，`upstream_batch_id` 用统一 batch builder 生成或由上游显式提供；
- `truncated=true`、非 ready 状态、范围越界、注册缺口、计数不一致或超出预算都 fail closed。

P5 的边界是“协议已具备可生产/可消费的验证基础”；P6 已补齐真正的 Silver repair producer。P7 在不改变 normal asset/job/sensor 的前提下补齐 repair handoff 和 Gold bounded repair。

P5 验证结果（2026-07-15）：`tests/test_dc_daily_technical_repair_protocol.py` 与 P2-P4 定向回归共 `106 passed`；协议模块通过 `py_compile`，definitions 加载成功，asset graph 保持 67 个资产且没有新增 repair asset/sensor。

### 10.2.1 P6 Silver repair producer

`dc_daily_silver_repair_producer.py` 的执行顺序固定为：

```text
显式日期/注册/预算预校验
  -> 单 DuckDB connection staging 全部 source 日期
  -> 旧 Silver 与 staging set-based 差异
  -> 规范化 close/high/low 输入内容 SHA-256 source_revision
  -> build + validate ready SilverRepairBatch
  -> 仅 promote changed partitions
```

- source repair 日期由调用方显式传入；indicator recompute 起点固定覆盖 source 起点，终点和 target frontier 显式传入。
- `context_start_trade_date` 未显式提供时只能回到 expected calendar 第一日，不能按最近文件或 event 推断。
- source revision 只覆盖 Gold 实际使用的 `ts_code/trade_date/category/close/high/low`，保证同一 Silver 内容产生稳定版本；不使用文件 mtime。
- 旧目标不存在时整份 staging 作为变化；旧目标 schema 损坏或不可读时 fail closed，保持旧文件不动。
- 所有 staging 在 producer 返回前要么已原子 promote，要么清理；no-op 不返回 ready batch。
- producer 本身不产生 Gold materialization/check event，不读取 event history；P7 producer op 只把 ready batch 的有限标量写入当前 producer run tags，Gold sensor 不从事件历史猜范围。

P6 验证结果（2026-07-15）：`tests/test_dc_daily_silver_repair_producer.py`、`tests/test_dc_board_silver.py`、`tests/test_dc_daily_technical_repair_protocol.py` 共 `26 passed`；producer 与共享 staging 模块通过 `py_compile`。测试只使用临时 lake，未写正式 lake、Dagster DB 或 event。

### 10.2 P7 Silver producer 与 Gold repair sensor

`silver_dc_daily_repair_job` 的 op 读取显式 repair config，调用 P6 producer，并按以下规则发布 tags：

- ready batch 使用 `goldenshare/silver_repair/` 前缀和 `SilverRepairBatch.to_run_tags()`；每个值都是标量字符串；不写完整 series 列表、storage id 或逐文件明细；
- no-op 只标记 `status=no_op`，不发布可消费的 ready batch；
- tag 写入失败时 producer run 不被 Gold sensor 消费，保留失败事实等待人工处理；
- producer job 是独立 job，不新增 asset，不向 Gold normal sensor 热路径注入逻辑。

`gold_dc_daily_technical_repair_job_sensor` 使用 `@dg.run_status_sensor`，监控成功的 `silver_dc_daily_repair_job`，默认 `STOPPED`。其用户逻辑只读取触发 run 的 tags、交易日历、dynamic partitions 和当前 Silver 文件，验证：

- `status=ready` 且 source asset 为 `silver_dc_daily`；
- `producer_run_id` 必须等于触发 run 的真实 `run_id`；
- 范围在 expected calendar 内；
- start <= end；
- `truncated=false`；
- source revision 与 source repair 范围内 Silver 内容匹配；
- indicator recompute 范围已注册且不超过 60 个 expected 日期；
- 不调用 `get_event_records`、不读取 Dagster check/materialization history、不访问 Tushare/Prod DB。

通过后使用 `build_upstream_triggered_run_key(consumer="gold_dc_daily_technical_repair", upstream_batch_id=...)` 提交一个 RunRequest，config 传完整 `batch.to_payload()`。无效 batch、缺 metadata、revision 不一致或范围超限时返回 ASCII reason code 的 skip，不扩大范围。

### 10.3 P7 Gold bounded repair writer 与 job

`write_gold_dc_daily_technical_repair_batch(...)` 接收完整 `SilverRepairBatch` 和 expected/registered dates，执行：

```text
batch/range/registration/budget validation
  -> context_start..indicator_end 显式 Silver 文件列表
  -> source_revision 对账
  -> 一个 DuckDB temp source/output relation 的 set-based 指标计算
  -> 每个 indicator target 日期独立 staging + schema/key/domain 回读
  -> 所有 staging 通过后逐文件 os.replace
```

repair writer 与 normal writer 分开：normal writer 对已有合法 Gold 文件 skip；repair writer 明确重算并允许替换已有 Gold 文件。任一 source/schema/日期/key/output 校验失败时，所有尚未 promote 的 staging 清理，且不产生 repair completion event；不从 `affected_series_hash` 推导代码列表，默认重算有效日期范围内的全部合法序列。

`gold_dc_daily_technical_repair_job` 是 op-based job，不使用 `define_asset_job` 或多分区 asset selection。op 解析完整 batch、调用 writer，并对每个实际重算日期分别写：

- 一个带 `partition=<trade_date>` 的 `AssetMaterialization(asset_key="gold_dc_daily_technical")`；
- 一个带同一 partition 的现有 `gold_dc_daily_technical_core_check` `AssetCheckEvaluation`；
- metadata 包含 upstream batch、source revision、source/indicator/context/frontier 范围、source/output rows、耗时和重算分区数。

不新增 repair check，不写无 partition 聚合 check，不把多日期 repair 拆成无界的一日一个 run。

单次 repair 不得从 2014 起点无条件重算到当前，也不得改成每个日期单独提交一个 Dagster run。范围、文件数、耗时或输出行数超预算时整批 fail closed。

### 10.4 P8A Bootstrap/lake 只读对账结果

P8A 不把交易日历的未来预注册日期误当成历史数据缺口。当前日历已包含到 `2026-12-31`，历史 Bootstrap 的日期集合固定为：

```text
SSE open dates >= 2024-01-02 and <= latest existing silver_dc_daily date
```

2026-07-15 的有效只读报告为：
`/private/tmp/dc_daily_technical_p8_lake_reconciliation_20260715_v2.json`。

- Silver source frontier 为 `2026-07-14`；历史 expected 为 611 个交易日；
- `silver_dc_daily` 共 611 个文件、596,200 行，schema 与 `SILVER_DC_DAILY_SCHEMA` 一致；
- `trade_date` 与物理分区错位 0，身份字段异常 0，`(ts_code, trade_date, category)` 重复行 0；
- 1,065 个 `(ts_code, category)` 序列、3 个 category，历史 expected 文件全部存在；
- Silver staging 残留 0，异常路径 0；
- Gold `dc_daily_technical` 目标目录目前没有文件，目标冲突 0，Gold staging 残留 0；
- 只读 DuckDB 聚合耗时约 `735ms`，没有 Dagster event history 调用、Dagster DB 写入或 lake 写入；
- `should_stop=false`，允许进入 Gold 临时样本 Bootstrap；这是 P8A 对账时的状态，正式 Gold 文件随后由 P8D 生成。

首次报告 `/private/tmp/dc_daily_technical_p8_lake_reconciliation_20260715.json` 因将日历未来的 116 个日期计入缺失而停止，已判定为审计范围错误；不得把该报告作为数据缺失结论。

### 10.5 P8B 事件验收设计（已完成）

Gold 611 个分区文件全部生成并通过同一套 core predicates 后，事件验收严格拆成两类：

1. **只读 dry-run**：统计 611 个 materialization 目标、最近 20 个 check 目标、已有 event、缺文件、计划事件和保护项；dry-run 不调用 `report_runless_asset_event`。
2. **小样本**：选择起始日、中间日、最新日各 1 个，先报告带正确 partition 的 `AssetMaterialization`，再以该 materialization 为 target 报告 partitioned `gold_dc_daily_technical_core_check`；只读确认 partition attribution、target materialization 和 readiness。
3. **正式批量**：materialization 全历史 611 个；check 只补最近 20 个交易日，当前范围是 `2026-06-16..2026-07-14`，计划总量 631 个 event。每批失败立即停止，不运行 Gold daily job，不启用 sensor。
4. **最终验收**：聚合核对 materialization/check 数量、partition 归属、latest state、最近 20 日 readiness 和后续 sensor 判断；不补 611 个历史 check，不删除历史 event。

正式事件阶段必须复用 `audit_gold_dc_daily_technical_partition` 的 blocking 语义，只对已通过文件事实校验的分区写绿事件；该口径已在 P8D/P9 正式执行中验证。

### 10.6 P8C Gold 临时样本 Bootstrap 结果

本阶段使用正式 Silver 文件的只读符号链接，在 `/private/tmp/dc_daily_technical_p8_sample_lake_20260715_174919` 中执行正常 Gold writer；报告为 `/private/tmp/dc_daily_technical_p8_sample_bootstrap_20260715_174919.json`。

- 样本日期固定为 `2024-01-02`、`2025-04-10`、`2026-07-14`，覆盖起始、历史中段和当前 source frontier；
- 三个样本分区均通过 schema、日期、业务主键、Silver key/close 对账、指标有限值和 warmup NULL 规则；输出行数为 `940`、`975`、`1022`；
- 最新日读取 611 个 Silver 分区，DuckDB 计算约 `607ms`，端到端约 `1049ms`；中间日读取 306 个分区，端到端约 `589ms`；
- 目标文件均经过 staging 回读和原子 promote，临时 lake 无 `.tmp` 残留；
- 临时 Gold 与正式 Gold 目录隔离；样本阶段 Dagster event history、Tushare、Prod DB 调用均为 0，正式 lake/DB/event 写入均为 0；
- 样本通过后进入 P8D 正式全量 Bootstrap，不能由样本结果自动触发正式写入。

### 10.7 P8D/P9 正式执行结果

#### P8D：正式 Gold 全量 Bootstrap 与文件对账

2026-07-15 按 P8A 冻结的 `2024-01-02..2026-07-14` 611 个 SSE expected dates，串行生成正式 Gold 文件。preflight、Bootstrap 和全量对账报告分别为：

- `/private/tmp/dc_daily_technical_p8_full_bootstrap_preflight_20260715_175436.json`
- `/private/tmp/dc_daily_technical_p8_full_bootstrap_20260715_175530.json`
- `/private/tmp/dc_daily_technical_p8_full_bootstrap_audit_20260715_180211.json`

结果为 611/611 文件、596,200 行、611/611 日期通过共享质量 predicates，失败日期/意外文件/staging 残留均为 0；Bootstrap 约 369.7 秒，全量 DuckDB 对账约 3.22 秒。writer 继续遵守 staging 回读校验后原子替换。该阶段不运行 Dagster job/sensor，不调用 Tushare/Prod DB，不写 Dagster event。

#### P9：事件验收

新增的 `dc_daily_technical_events.py` 与 CLI 只做有界事件规划和显式确认写入：

- dry-run `/private/tmp/dc_daily_technical_p8_events_dry_run_20260715.json`：计划 611 个 materialization、最近 20 日 20 个 partitioned core check，共 631 个 event；
- sample `/private/tmp/dc_daily_technical_p8_events_sample_20260715.json`：3 个 materialization + 最新日 1 个 check；
- apply `/private/tmp/dc_daily_technical_p8_events_apply_20260715.json`：新增 608 个 materialization + 19 个 check；
- final `/private/tmp/dc_daily_technical_p8_events_final_20260715_180652.json`：materialization 611/611、最近 check 20/20，所有 check partition 正确、target materialization 精确匹配、readiness 失败 0。

P9 没有运行 Gold daily job、没有启用 normal/repair sensor、没有补历史 611 个 check，也没有改写 Gold 文件。

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
5. **P5 repair prerequisite**：已完成 Silver repair batch 协议、`silver_dc_daily` 适配器和本地 fail-closed 校验；P5 不开发 Gold repair。P6 补齐 producer，P7 补齐 Gold repair，但 sensor 仍默认 `STOPPED`。
6. **P6 Silver repair producer**：已完成 bounded source rebuild、内容 revision、旧/新差异、ready batch 和临时湖验证；未新增 Gold repair definition。
7. **P7 repair definition**：已完成 producer job/tag handoff、bounded Gold repair writer、op-based repair job 和 STOPPED run-status sensor；定向测试通过，未执行正式 repair。
8. **P8A lake 对账**：已完成；以 source frontier 冻结 611 个历史 expected 日期，报告为 `/private/tmp/dc_daily_technical_p8_lake_reconciliation_20260715_v2.json`。
9. **P8B event acceptance design**：已完成；materialization 全历史、check 最近 20 日，随后由 P9 按该口径执行。
10. **P8C temporary sample Bootstrap**：已完成三日临时 lake 生成与质量审计。
11. **P8D full Gold Bootstrap**：已完成 611 个正式 Gold 分区生成和全量文件对账。
12. **P9 event acceptance**：已完成 611 个 materialization 与最近 20 个 partitioned check 的有界补录和最终对账。
13. **P10 enablement**：P10A 已完成 normal sensor 启用和只读 preview；当前因 Silver source frontier 未覆盖 Gold 目标日期而正常 skip，尚未启动 daemon 观察，也未启用 repair sensor。后续仍需观察至少 3 个交易日，再单独评估 repair sensor。

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

## 15. 2026-10-22 板块三项补齐执行卡（已完成）

管理员已明确批准“批准，按三步顺序执行”，覆盖本节必要历史读取和一次Gold→本机CH→Prod CH三步补齐，读256MiB、写32MiB、额外空间64MiB，失败停止不自动重读。本节已按批准范围进入执行；复用现有实现，不改代码。

### 15.1 目标、已有事实和授权边界

本执行卡只处理22日的 `gold_dc_daily_technical`、`ch_dc_daily_technical`、`prod_ch_dc_daily_technical` 三项，依次使用现有 Gold、本机 ClickHouse、Prod ClickHouse job及各自原核心检查。不新增或修改代码、公式、schema、配置、入口、分区、sensor或状态表，不运行性能样本，不重跑已完成的板块 Raw/Silver。

已有证据为恢复报告 `datasets_recovery_20261022_20261024/resume_20261025/batch2-final.json`：22日分类 Raw/Silver各1,043行、成员各98,530行、行情各1,043行，六项及六项检查通过，邻日未变。该结果是当时完成事实，执行前仍需核同日来源身份和目标现状，不能把旧证据当作当前连接/目标状态。按原缺失集合，三项全部完成后只扣这三项，不重新扫描其他数据集。

Gold现行实现需要历史上下文，不能把只补一个分区当作只读22日。本节15.3的历史读取及正常一次计算已获管理员单独批准，股票因子修复的授权与本项分开记录。

### 15.2 当前实现、配置和读写位置

代码依据如下，实际执行不另写计算或发布入口：

| 步骤 | 当前代码和范围 | 正式目标 |
| --- | --- | --- |
| Gold | `assets/dc_daily_technical.py::write_gold_dc_daily_technical_partition`；按SSE日历取2024-01-02至22日的Silver路径；每32文件校验schema并载入同一DuckDB临时关系，原SQL计算指标，仅输出22日 | `/Volumes/datasource/data_lake/gold/board/dc_daily_technical/trade_date=2026-10-22/part-000.parquet` |
| 本机CH | `assets/dc_daily_technical_serving.py::ch_dc_daily_technical`；显式读取22日Gold业务列，增加本次上海时间 `updated_at`，一次批量发布 | resource `clickhouse`的 `goldenshare_serving.board_fact_technical_daily`，只22日 |
| Prod CH | 同文件 `prod_ch_dc_daily_technical`；先完整取得本机22日显式列含 `updated_at`，非空后再连接Prod并一次批量发布 | resource `prod_clickhouse`的同名表，只22日 |

Gold候选经 `io/dc_board_candidate.py`生成，位于 `/Volumes/datasource/data_lake_staging/dc_board/run_id=<uuid>/gold/board/dc_daily_technical/trade_date=2026-10-22/part-000.parquet`；回读schema、键、行数等通过，同文件系统检查后 `os.replace()`。没有业务备份、Kopia或正式目标旁临时文件。当前writer异常会清理自己的候选，没有QFQ publication的receipt复用能力；失败不承诺直接复用已删除候选。

复用 `DuckDBResource`现行配置：`memory_limit=16GB`、`threads=4`、`preserve_insertion_order=false`，临时目录 `/Volumes/datasource/.goldenshare_duckdb_tmp`、spill上限512GB。上述是既有配置上限，不是预计实际占用，本次不改变全局或单任务连接设置。spill量若非零须单列实际开销，不能只按Parquet文件大小声称没有临时I/O；空间/读取预算条件不成立则停止，不放宽配置。

CH连接仍从 `resources.py`使用各自 `CLICKHOUSE_*` 与 `PROD_CLICKHOUSE_*` 环境来源，不复制凭证、不混用两个resource、不新增持久设置。writer保持现有 `SET lightweight_deletes_sync = 1`、同日 `DELETE`、确认同日计数为0、显式列一次 `INSERT`、再次计数的顺序；不改为DDL、`ALTER TABLE DELETE`、整月分区删除、异步提交或 `OPTIMIZE FINAL`。

### 15.3 历史读取、检查和正常一次预算

必要历史仅为 `silver/board/dc_daily` 在2024-01-02至2026-10-22的全部预期SSE开市日，读取六列 `ts_code,trade_date,category,close,high,low`，另读必要schema/footer及既有Silver日历。2026-10-25前一轮元数据676文件37,531,917B，加已有22日Silver记录58,691B，推导为677文件37,590,608B（约35.849MiB）；这是旧元数据和完成报告推导，未重新读取正式内容或确认当前文件未变。读取前按当前日历和stat冻结准确文件数/字节，不以普通周一至周五推断交易日，也不因677是旧估计就忽略额外或缺失输入。

本次不再获取Raw source proof，不请求Tushare，不重扫Raw历史。Gold正式核心检查只读取22日Gold与同日Silver，不重复读取历史或重算完整指标。后续本机CH的原检查也只读同日Gold和本机同日行；Prod CH原检查只读取本机/Prod同日行。保留MA/BOLL合法warmup NULL，不为统一类型而填0。

| 项目 | 拟执行/验收成本及停止条件 |
| --- | --- |
| 正常历史计算 | 一次677文件上下文读取，32文件/批约22批；六列进入一个临时关系，随后计算22日；源明细不读第二遍做独立公式审计 |
| Gold文件与结果预算 | 历史文件/schema/footer、Gold候选回读、三个原检查及一次必要收尾合计暂按256MiB文件及有界结果读取、32MiB文件/日志/小型报告写入、64MiB额外候选与报告空间测算；其中Gold候选暂留4MiB上限。执行前stat/现状不符合即重新测算，不自行扩大 |
| 内存和临时I/O | 沿既有16GB/4线程配置；原7月611日单日0.664秒/526MB只作旧参考，不作为本次保证。DuckDB临时关系是内存工作集，若实际spill或额外空间超过本卡假设则停，不把512GB配置上限当本次批准空间 |
| 两处CH | 预计每端1,043行、每端一个同步INSERT，原核心检查及一次同日收尾；这些是业务行/有界结果预算，不能当作CH内部parts、delete mask、后台merge的精确物理读写量 |
| 耗时 | Gold沿原单目标日读/算/写/回读≤15秒门禁；当前代码没有相应15秒自动中断，超限记录阶段并停止后续链，不调整超时掩盖。CLI加载及每个CH发布/检查暂留各2分钟，整批正常观察预算10分钟，不以等待日志为空为由重跑 |
| 失败后继续 | 默认失败即停，不自动第二次历史读取。若Gold必须重新运行，至少再计一次完整历史输入、其候选及检查，上述读取/写入/空间额外额度和现场另行确认；旧批准不覆盖任意重试。仅CH失败时不重跑Gold或历史计算 |
| 最后验收 | 复用三run的物化/检查metadata及已记录源stat，只做一次目标日必要读回；不做全局audit、不重新扫描677份历史、不追加摘要遍历或性能样本 |

该预算依据执行前已有规模制定，不是已测物理设备I/O，也不是原生代码已经实施的自动硬限。管理员已按“正常一次，包含原检查和下述有界收尾；失败不自动再读”批准，实际结果见15.8。不以本次小规模板块文件体积抵扣其他股票历史任务的读取额度。

### 15.4 正式启动前的有界检查建议

以下为启动前检查条件；本次已获批准并完成预检，现场结果见15.7。

1. 核正式Lake/staging挂载、无符号链接、同设备、读写权限与剩余空间；记录Gold目标及21/23日邻日Gold stat。读取已有日历规划677个左右的预期输入，stat核全部所需Silver及22日来源与已有身份一致；缺失预期文件则停，不使用其他日期替代。
2. 只读核22日Silver当前行数、日期/唯一业务键，预期1,043；读必要schema、source stat并冻结本次来源。若与已有完成证据不符先解释，不直接重跑Raw/Silver。输入全历史行数仅可复用可靠footer计数或原writer metadata，不为估规模先扫六列历史。
3. 检查当前目标Gold是否存在、本机/Prod目标22日count；旧缺失结果不能代替当前检查。若Gold已存在且对应现行检查/源事实已通过，复用而不为本次任务重跑历史；若CH已有行，先按当前明确列投影核对该日是否已齐备，完全一致则不重复发布，有差异先说明，不能以补缺失为名无条件覆盖。
4. CH连接复用已有resource；先限定单表读取当前 `system.tables` 的engine/partition_key/sorting_key及必要 `system.columns`，核与V4迁移/现行字段合同一致。预期MergeTree、月分区 `toYYYYMM(trade_date)`、排序前缀 `trade_date`，但须由当前schema确认；缺表/漂移不自行执行DDL或迁移。
5. 计数和收尾查询只过滤 `trade_date=2026-10-22`，显式字段；明细最多2,000行、超时30秒、扫描上限100,000行/64MiB、超限抛错不接收截断结果。必要元数据限表名，不列举全库业务明细。上述为审计查询保护，不修改原生writer或其他任务的连接profile。
6. 只读检查相关活动run/并发writer、板块sensor和daemon当前状态，确认不会发生同日写入冲突或范围外自动补数。本卡不授权启停daemon/sensor、修改cursor或注册分区；缺动态分区或需调整自动化时停下说明。既已停止的股票MACD/九转sensor保持原状态，不因本板块完成而启用。

### 15.5 精确执行顺序和验收

工作目录：`/Users/congming/github/goldenshare/lake_console/orchestrator`。正式 `DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home`，使用已有项目 `.venv/bin/dg`，不使用会隐式同步依赖的入口，不安装依赖。三个job均无新增config：

```sh
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job gold_dc_daily_technical_update_job --partition 2026-10-22
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job ch_dc_daily_technical_update_job --partition 2026-10-22
DAGSTER_HOME=/Users/congming/.goldenshare/dagster_home .venv/bin/dg launch --module-name orchestrator.definitions --job prod_ch_dc_daily_technical_sync_job --partition 2026-10-22
```

每条命令仅在前一步SUCCESS且该run目标资产及原blocking检查通过后执行。保存run_id/root_run_id、目标日期、物化storage_id和检查绑定；检查分别为 `gold_dc_daily_technical_core_check`、`ch_dc_daily_technical_core_check`、`prod_ch_dc_daily_technical_core_check`。每run只查本次有界事件，确认无截断/失败，不重查全局历史。

- Gold：schema、目标日1,043行及与22日Silver的主键/close关系、数值有限性、warmup等由原check验证；目标路径只22日，21/23邻日stat不变，历史Silver输入stat不变。候选回读是原writer动作，不另重算公式。
- 本机CH：原check验证行数、键、日期、版本；它没有逐业务字段与Gold比较。收尾额外保留一次22日Gold显式业务列与本机同日列的逐键完整比较，最多1,043行附近，超2,000停止；NULL保持NULL，不重新计算历史指标。
- Prod CH：原check已比较两端同日完整业务列、缺/多键、重复键及 `updated_at`不落后；优先复用该check结果，不再全表对比。必要提交后收尾只核22日count与metadata，无新一轮历史读取。

若本机收尾不一致，停止Prod发布。CH的同日DELETE与INSERT不是整体事务；删除成功后插入失败可能留下空目标，不能因run失败就宣称未写入。此时先精确读回同日计数/键和本run事件，保持已经成功的Gold/本机结果，不删其他日，不清表，不用备份或runless event补绿。只在重新确认现场及本日重发范围后，重跑失败的原生CH job一次；不得自动重复整个三步链。

### 15.6 本次ClickHouse规则复核

本卡已读取 `clickhouse-best-practices` 技能及适用规则，不是CH架构或schema迁移授权：

- Per `schema-pk-filter-on-orderby`、`agent-discovery-schema`：按现行V4排序前缀trade_date限定目标日，并在执行前限定单表核当前schema；不因旧文档DDL直接假定在线结构一致。
- Per `agent-query-safety`：审计查询设置日期、结果/扫描/超时边界，超限失败，不把LIMIT当成扫描上限；实际连接与执行结果见15.7～15.8。
- Per `insert-batch-size`：现有1,043行同日单批达到规则所列1,000最低量；不拆逐行，不为达到理想10K而混入其他日期。
- Per `insert-mutation-avoid-delete`、`insert-mutation-avoid-update`：保留现行同日轻量DELETE及INSERT，不执行ALTER UPDATE/DELETE或整月DROP；非事务失败风险按15.5处理。
- Per `insert-async-small-batches`、`insert-optimize-avoid-final`：这是各端一次同步补齐，不属于高频小批，不引入异步设置，不运行OPTIMIZE FINAL。JOIN算法/ANY/过滤前置规则和新增跳数索引在该单表发布链不适用，不因此新增查询或索引。

本节规则审查在执行前完成，后续经管理员明确批准完成有界预检及三步正式执行；当前结果见15.8，不再处于草案状态。

### 15.7 本次执行前核验（2026-10-25）

修改及因子恢复证据已提交 `1f54c5297`，本节板块执行记录属于提交后的下一批。`board_technical_20261025/preflight.json`记录677份Silver共37,590,608B、22日1,043个唯一键，来源22日与既有恢复证据身份相同；Gold22日不存在，两端CH22日均0行、21日均1,043行、23日0行。`schema-review.json`已将两端在线25列(name,type)、MergeTree、月分区及完整排序与V4精确比较，通过。股票MACD/九转sensor均STOPPED，daemon无进程、无活动run，动态分区已存在。首次元数据查询因Prod账号无system.data_skipping_indices权限中断，未产生正式写入；后续省去非必要的该查询，不改权限、不读取历史行情内容，只完成必要预检。

### 15.8 正式执行与验收结果

2026-10-25按Gold→本机CH→Prod CH完成三个原job，各一次正常执行、各1,043行、各原blocking检查通过。run依次为 `4890e8c3-2221-46e5-99d8-bd14515a885b`、`dcf5f252-c3aa-4801-b13e-a5012a1f184b`、`76480b90-680d-428a-a467-c0219396175b`；物化storage_id依次7726601、7726627、7726653，check均绑定本run物化及22日。

Gold输入677份/664,211行，writer总耗时1,337.872ms，峰值内存739,016,704B，输出151,343B，满足15秒门禁；原check无失败、无输入拒绝/重复键，合法warmup NULL保留。本机额外一次22日24列完整业务比较差异0；Prod原check的内容、缺/多键、重复及updated_at落后均0。最后只核元数据和三天计数：所有来源/日历及邻日Gold身份未变；两端21日1,043行、22日1,043行、23日0行；候选文件不存在，两个股票sensor保持STOPPED、daemon未运行、无活动run。没有全局审计、第二轮历史价格读取、代码/配置变更或真实性能样本。设备物理I/O与瞬时spill未单独采样，不将文件字节当作精确物理读取量。

首次Prod可选跳数索引元数据查询无权限497，省去非必要查询后继续必要预检；Gold审计脚本误用未带goldenshare/前缀的耗时键，按已保存原run证据修正断言，未重跑业务job。三原run都SUCCESS，未自动续跑。执行、验收和每步证据见恢复报告第43节及 `board_technical_20261025/summary.json`；本次从原缺失清单扣三项，剩18。
