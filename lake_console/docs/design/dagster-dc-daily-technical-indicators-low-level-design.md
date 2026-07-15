# `dc_daily` 技术指标 Gold 数据集 LLD

> 状态：P8A Gold Bootstrap/lake 只读对账、P8C 临时样本 Bootstrap、P8D 正式 Gold 全量 Bootstrap 和 P9 事件验收均已完成。P10A 已启用 normal sensor；P7 repair sensor 仍未启用，尚未完成 3 个交易日观察。
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
10. P8C 之前的代码阶段只做本地定义、单元测试和临时 lake 测试；P8D/P9 是单独批准的正式 Gold 文件写入与事件验收阶段，不运行 daily job，不启用 sensor。

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
