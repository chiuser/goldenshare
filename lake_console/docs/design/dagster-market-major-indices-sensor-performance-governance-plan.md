# Dagster Market Major Indices Sensor 热路径性能治理技术设计方案

更新时间：2026-06-21

状态：P4 已完成；只读 DuckDB SQL / 性能原型验证、本地单元测试与静态门禁已通过

范围：`market_major_indices_daily_sensor` 及其 readiness 热路径

原则：性能第一优先级；不得因性能优化牺牲 blocking check 语义；不得新增持久化状态实体；不得引入补丁式修复。

对应 LLD：[Dagster Market Major Indices Sensor 热路径性能治理 LLD](dagster-market-major-indices-sensor-performance-governance-low-level-design.md)

与总专项关系：本文档是 [Dagster 非股票分钟线连续性治理专项方案](dagster-non-stk-mins-continuity-governance-plan.md) 的 P4 专项方案。P4 实现必须先复用 [Dagster Bounded Continuity Selector 基础能力 LLD](dagster-bounded-continuity-selector-foundation-low-level-design.md) 中的通用 readiness model、registered gap guard、selector 与 cursor 口径，不再新增平行的长期 selector 数据模型。

2026-06-21 代码审计补充：当前 `market_major_indices_daily_sensor` 的 latest-only 目标选择和旧 Dagster event-history readiness wrapper 已由代码审计确认；旧单日 wrapper 的正式只读 profiling 约 47 秒 / 超时，不能进入 20/60 日循环。

2026-06-21 P4 收口：P4 已实现 `asset_guards/market_major_indices_lake_readiness.py`，`market_major_indices_daily_sensor` 已切到 expected calendar + registered gap guard + first not-ready gold + lake-derived selected-date upstream gate。只读 `/private/tmp` DuckDB 原型显示：60 日 gold batch + selected silver + selected index basic 合计约 24ms；selected-date silver coverage 在 500/1000/2000 个 raw by-code 文件下约 22/38/77ms。P4 本地目标测试和静态门禁通过；未运行 `dg`，未读取正式 Dagster runtime，未写正式 lake。

## 1. 背景

控制台报错中关键异常是：

```text
DagsterUserCodeUnreachableError:
The sensor tick timed out due to taking longer than 60 seconds to execute the sensor function.
```

外层看起来是 user code server unreachable，但真正触发点是 sensor evaluation 超过 Dagster gRPC sensor timeout。

这不是单纯重启 `dg dev` 可以根治的问题，也不是某个分区临时卡住的问题，而是 sensor 热路径读取模型不合理。

本方案目标是从根上解决：

1. `market_major_indices_daily_sensor` 超过 60 秒的问题。
2. 主要指数日线 gold 仍按 latest registered target 推进，可能跳过更早缺口的问题。
3. sensor 热路径使用 Dagster event/check history 深扫，性能不可控的问题。
4. 在优化性能的同时，不允许降低正式 blocking check 语义。

## 2. 代码审计结论

### 2.1 Sensor 当前执行链路

入口：

```text
lake_console/orchestrator/src/orchestrator/defs/sensors/market_major_indices_daily_sensor.py
```

关键代码流：

| 代码位置 | 当前行为 | 问题 |
| --- | --- | --- |
| `market_major_indices_daily_sensor.py:197-202` | 读取 `cn_a_index_trade_days` 和 `cn_a_index_ts_codes` dynamic partitions。 | 本身可接受，但只代表 Dagster 注册状态，不是权威 expected calendar。 |
| `market_major_indices_daily_sensor.py:230` | 调用 `_latest_registered_trade_date(...)`。 | latest-only，会跳过更早 not-ready 日期。 |
| `market_major_indices_daily_sensor.py:244-247` | 调 `gold_market_major_indices_daily_ready_for_trade_date(...)`。 | 进入 Dagster check history 深扫。 |
| `market_major_indices_daily_sensor.py:264-278` | gold 已 materialized 但 checks 未绿则 skip。 | 语义正确，应保留。 |
| `market_major_indices_daily_sensor.py:280-283` | 调 `silver_index_daily_ready_for_trade_date(...)`。 | 进入 Dagster check history 深扫。 |
| `market_major_indices_daily_sensor.py:298` | 调 `silver_index_basic_ready(...)`。 | unpartitioned asset 也走 Dagster check history 深扫。 |
| `market_major_indices_daily_sensor.py:314-319` | 调 `check_market_major_indices_inputs_for_trade_date(...)`。 | 这是小规模 DuckDB seed/input 检查，性能模型相对合理。 |
| `market_major_indices_daily_sensor.py:340-346` | 用统一 builder 提交 `RunRequest`。 | run key 口径正确，应保留。 |

### 2.2 Readiness 当前底层实现

入口：

```text
lake_console/orchestrator/src/orchestrator/defs/sensors/readiness.py
```

关键代码流：

| 代码位置 | 当前行为 | 问题 |
| --- | --- | --- |
| `readiness.py:10` | `CHECK_HISTORY_LIMIT = 5000`。 | 每个 check 最多扫 5000 条历史记录。 |
| `readiness.py:406-422` | `_check_passed_for_materialization(...)` 调 `get_asset_check_execution_history(...)`。 | 每个 blocking check 单独扫 Dagster event/check history。 |
| `readiness.py:520-540` | `asset_readiness_status(...)` 对每个 blocking check 循环调用 `_check_passed_for_materialization(...)`。 | 单个 asset readiness = `blocking_check_count` 次 event history 读取。 |
| `readiness.py:176-183` | `SILVER_INDEX_DAILY_BLOCKING_CHECKS` 7 个。 | 单次 silver readiness 最多 7 次 history 读取。 |
| `readiness.py:185-191` | `SILVER_INDEX_BASIC_BLOCKING_CHECKS` 6 个。 | 单次 index basic readiness 最多 6 次 history 读取。 |
| `readiness.py:193-203` | `GOLD_MARKET_MAJOR_INDICES_DAILY_BLOCKING_CHECKS` 10 个。 | 单次 gold readiness 最多 10 次 history 读取。 |

因此 `market_major_indices_daily_sensor` 单 tick 最坏路径为：

```text
gold readiness:         10 checks * 5000 history limit
silver daily readiness:  7 checks * 5000 history limit
index basic readiness:   6 checks * 5000 history limit
-------------------------------------------------------
合计最多：23 次 event/check history 查询，最多扫描 115000 条 check records
```

这还不包含 materialization 查询、反序列化、Python 逐条匹配 `target_materialization_data.storage_id` 的成本。

### 2.3 已有输入检查并不是主要性能问题

入口：

```text
lake_console/orchestrator/src/orchestrator/defs/sensors/market_major_indices_input_readiness.py
```

`check_market_major_indices_inputs_for_trade_date(...)` 的行为是：

1. 读取仓库 seed。
2. 检查 registered index codes 是否包含 seed codes。
3. 用 DuckDB 检查 `silver_index_basic` 是否包含 seed codes。
4. 用 DuckDB 检查 `silver_index_daily` 是否包含 active seed codes。

这部分是小规模 seed-driven DuckDB 检查，读取量可控，不是本次 60 秒 timeout 的主因。

## 3. 根本原因

### 3.1 热路径使用了冷路径读取模型

Sensor 是调度热路径，应该快速判断：

```text
是否有目标日期需要跑？
上游是否 ready？
目标是否已经 ready？
是否应该提交 RunRequest？
```

当前却在 sensor tick 内读取 Dagster 历史 check event，并对每个 check 做最多 5000 条记录扫描。

Dagster event log 适合审计和 UI 历史，不适合作为大窗口 readiness 热路径数据库。

### 3.2 readiness 没有 batch 化

当前 `asset_readiness_status(...)` 是单 asset、单 partition、单 check 循环模型。

对 sensor 来说，真正需要的是：

```text
一批日期内，哪些日期 ready，哪些缺文件，哪些 materialized 但 checks failed？
```

但当前实现每次只判断一个 partition，而且每个 check 单独读 event history。

### 3.3 目标选择仍是 latest-only

`market_major_indices_daily_sensor` 直接取 latest registered trade date。

这会导致停机恢复后，如果更早日期缺失，而更晚日期已注册或已 ready，sensor 可能永远不处理早期缺口。

### 3.4 性能优化不能靠降低语义

不能把完整 blocking checks 简化成：

```text
文件存在 + row count > 0
```

`gold_market_major_indices_daily` 的正式 checks 包含 seed 覆盖、rank 顺序、价格合理性、index basic 引用、registered index code 覆盖等语义。

性能优化必须复用或抽取这些 SQL 语义，不能用粗筛冒充 ready。

## 4. 设计目标

1. sensor tick 稳态耗时稳定低于 5 秒。
2. 异常路径完整扫描耗时低于 10 秒。
3. 超过 15 秒视为性能门禁失败，停止扩大范围并重新设计。
4. sensor 热路径内 Dagster event/check history 查询次数为 0。
5. 主要指数日线 gold 目标从 latest registered 改为 first not-ready。
6. 保留现有 run key、run config、job 名称、sensor 名称。
7. 保留已 materialized 但 checks 未绿时不自动重跑的安全口径。
8. 不新增 status manifest、summary asset、readiness asset、数据库表或配置项。
9. 不降低任何正式 blocking check 语义。
10. 明确区分 lake fact readiness 与 Dagster 历史 check event readiness：sensor 热路径以 lake 文件事实和正式 check SQL 等价语义作为运行决策依据，不以历史 event log 是否已有 passed check event 作为热路径判断依据。

## 5. 非目标

本轮不做：

1. 不调整 Dagster gRPC timeout。
2. 不通过重启 user code server 作为根治方案。
3. 不全局修改 `asset_readiness_status(...)`。
4. 不降低 `CHECK_HISTORY_LIMIT`。
5. 不删除或改名任何正式 asset/check/job/sensor。
6. 不新增持久化状态实体。
7. 不修改 run key 治理口径。
8. 不处理所有非分钟线资产族，只聚焦 `market_major_indices_daily_sensor` 这条已超时链路。

## 6. 目标架构

### 6.1 当前架构

```text
market_major_indices_daily_sensor
  -> latest registered trade date
  -> gold_market_major_indices_daily_ready_for_trade_date
       -> asset_readiness_status
          -> per-check Dagster event history scan
  -> silver_index_daily_ready_for_trade_date
       -> asset_readiness_status
          -> per-check Dagster event history scan
  -> silver_index_basic_ready
       -> asset_readiness_status
          -> per-check Dagster event history scan
  -> seed/input DuckDB gate
  -> RunRequest
```

### 6.2 目标架构

```text
market_major_indices_daily_sensor
  -> expected index trade dates
  -> registered gap guard
  -> batch lake readiness
       -> gold_market_major_indices_daily readiness by date
       -> selected-date silver_index_daily lake readiness
       -> silver_index_basic lake readiness once
       -> selected-date seed/input gate
  -> first not-ready target
  -> RunRequest or SkipReason
```

核心变化：

```text
Dagster event history readiness
  改为
DuckDB/lake batch readiness + expected calendar first-not-ready selector
```

### 6.3 事实源边界

P4 的核心改变不是“取消 checks”，而是改变 sensor 热路径读取事实的方式。

当前事实源：

```text
Dagster materialization event + Dagster asset check event history
```

P4 后 sensor 热路径事实源：

```text
lake parquet 文件事实 + seed 文件 + dynamic partitions + 正式 blocking check SQL 等价语义
```

含义：

1. `ready=True` 表示 lake 文件事实按当前正式 blocking checks 的等价语义通过。
2. `checks_passed=True` 表示 lake-derived check semantics passed，不表示 Dagster 历史 check event 中已经存在最新 passed event。
3. `materialized=True` 表示目标 lake 文件存在，不要求读取 Dagster materialization event。
4. 若 lake 文件存在但 lake-derived checks failed，必须按“已生成但 checks 未绿”处理：skip，不自动重跑，不推进后续日期。
5. 若 lake 文件缺失，才允许提交正式 asset job 生成。

这个边界必须写进实现注释、测试命名和 cursor payload，避免后续把 `checks_passed` 误解成 Dagster event log 状态。

## 7. 新增组件设计

### 7.1 新增 helper 文件

建议新增：

```text
lake_console/orchestrator/src/orchestrator/defs/asset_guards/market_major_indices_lake_readiness.py
```

职责：

1. 只做内存态 readiness 判断。
2. 不写文件。
3. 不写 Dagster event。
4. 不读取 Dagster check history。
5. 不新增持久化实体。
6. 用 DuckDB/lake 文件事实复用正式 check 语义。

禁止：

1. 不得调用 `get_asset_check_execution_history(...)`。
2. 不得调用 `asset_readiness_status(...)` 或单日 readiness wrapper。
3. 不得把 Dagster check event 缺失当作 lake fact failed。
4. 不得用文件存在、row count 或 materialization event 冒充完整 ready。

### 7.2 数据结构

本文档早期建议定义 `MarketMajorIndicesDateReadiness` / `MarketMajorIndicesBatchReadiness`。LLD 收口后，正式实现应复用基础能力中的 `ContinuityDateReadiness` / `ContinuityBatchReadiness`；主要指数专项只在 `summary`、`failed_check_names`、`missing_check_names` 中写入业务细节，不新增平行长期模型。原建议结构仅作为字段语义参考。

字段参考：

```python
@dataclass(frozen=True)
class MarketMajorIndicesDateReadiness:
    trade_date: str
    ready: bool
    materialized: bool
    checks_passed: bool
    missing_file_paths: tuple[str, ...]
    missing_check_names: tuple[str, ...]
    failed_check_names: tuple[str, ...]
    reason: str
    summary: Mapping[str, object]
```

```python
@dataclass(frozen=True)
class MarketMajorIndicesBatchReadiness:
    expected_trade_dates: tuple[str, ...]
    registered_trade_dates: tuple[str, ...]
    first_missing_registered_date: str | None
    ready_through_trade_date: str | None
    first_not_ready_trade_date: str | None
    statuses_by_trade_date: Mapping[str, MarketMajorIndicesDateReadiness]
    elapsed_ms: int
    scanned_file_count: int

    def status_for_trade_date(self, trade_date: str) -> MarketMajorIndicesDateReadiness: ...
    def to_cursor_details(self) -> dict[str, object]: ...
```

cursor 中只写 summary，不写逐文件明细，避免 cursor 膨胀。

### 7.3 字段语义

`MarketMajorIndicesDateReadiness` 字段必须按以下含义实现：

| 字段 | 含义 |
| --- | --- |
| `materialized` | 目标 parquet 文件是否存在；不读取 Dagster materialization event。 |
| `checks_passed` | lake-derived blocking check 等价语义是否全部通过。 |
| `ready` | `materialized and checks_passed`。 |
| `missing_check_names` | 因文件缺失而无法通过的正式 check 名称。 |
| `failed_check_names` | 文件存在但 lake-derived check 语义失败的正式 check 名称。 |
| `reason` | 面向 cursor / SkipReason 的短原因，不承载逐文件明细。 |

如果未来需要审计 Dagster 历史 check event 是否缺失，应作为冷路径审计或 runless event 专项处理，不得塞回 sensor 热路径。

## 8. Readiness 语义映射

### 8.1 Gold market major indices daily

正式 blocking checks 来自：

```text
lake_console/orchestrator/src/orchestrator/defs/checks/market_major_indices_checks.py
```

必须覆盖：

| check | lake readiness 等价语义 |
| --- | --- |
| `gold_market_major_indices_daily_file_exists` | 对应 partition parquet 文件必须存在。 |
| `gold_market_major_indices_daily_required_columns_and_types` | schema 必须匹配 `MARKET_MAJOR_INDICES_DAILY_COLUMNS` / types。 |
| `gold_market_major_indices_daily_partition_date_matches` | 文件内 `trade_date` 必须等于 partition date。 |
| `gold_market_major_indices_daily_row_count_matches_seed` | 行数必须等于该日 active seed row count。 |
| `gold_market_major_indices_daily_seed_codes_present` | active seed codes 必须全部出现。 |
| `gold_market_major_indices_daily_unique_ts_code` | `ts_code` 不得重复。 |
| `gold_market_major_indices_daily_rank_matches_active_seed_order` | rank/code 必须与 active seed order 一致。 |
| `gold_market_major_indices_daily_price_sanity` | open/high/low/close/pre_close 非负且 OHLC 区间合法。 |
| `gold_market_major_indices_seed_codes_exist_in_index_basic` | seed codes 必须存在于 `silver_index_basic`。 |
| `gold_market_major_indices_seed_codes_exist_in_registered_index_ts_codes` | seed codes 必须存在于 `cn_a_index_ts_codes` registered set。 |

注意：不能只检查文件和 row count。

### 8.2 Silver index daily

当前 `market_major_indices_daily_sensor` 只需要 selected date 的上游 silver ready。

为了消除 event history hot path，第一阶段固定做 lake-based selected-date readiness，不做 60 日 silver batch。原因是 P4 的 first-not-ready 目标只需要从 gold readiness 找出；找出 selected gold target 后，只需要验证该 selected date 的 silver 上游是否 ready。

如果后续另有指数 silver 批量性能治理专项，再单独设计 60 日 silver batch；不得在 P4 中扩大范围。

必须覆盖当前 `SILVER_INDEX_DAILY_BLOCKING_CHECKS`：

| check | lake readiness 等价语义 |
| --- | --- |
| `silver_index_daily_conflicting_duplicate_absent` | 无冲突重复业务键。 |
| `silver_index_daily_partition_date_matches` | 文件内 trade_date 匹配 partition。 |
| `silver_index_daily_price_sanity` | 价格字段合法。 |
| `silver_index_daily_registered_code_coverage` | registered index codes 覆盖语义保持。 |
| `silver_index_daily_required_columns_and_types` | schema/type 匹配。 |
| `silver_index_daily_row_count_positive` | 行数大于 0。 |
| `silver_index_daily_unique_ts_code_trade_date` | `ts_code + trade_date` 唯一。 |

如果已有 `silver_index_daily_sensor` 的 raw gap audit 可复用，优先复用现有 helper；不得复制出语义漂移的第二套 SQL。

### 8.3 Silver index basic

必须覆盖当前 `SILVER_INDEX_BASIC_BLOCKING_CHECKS`：

| check | lake readiness 等价语义 |
| --- | --- |
| `silver_index_basic_file_exists` | 文件存在。 |
| `silver_index_basic_required_columns_and_types` | schema/type 匹配。 |
| `silver_index_basic_row_count_positive` | 行数大于 0。 |
| `silver_index_basic_unique_ts_code` | `ts_code` 唯一。 |
| `silver_index_basic_required_fields_non_null` | 必填字段非空。 |
| `silver_index_basic_no_terminated_indexes` | 不包含 `exp_date <= selected gold target date` 的 terminated indexes；旧 check 从 materialization metadata 读取 `ready_for_trade_date`，P4 热路径不读 Dagster event history，因此显式使用 selected target date 作为等价判断日期。 |

这是 unpartitioned snapshot，每个 sensor tick 最多检查一次。

### 8.4 Seed/input gate

保留现有：

```text
check_market_major_indices_inputs_for_trade_date(...)
```

它已经是 seed-driven DuckDB 检查，读取规模小，且语义与主要指数 seed 强相关。

可在后续实现中与新 batch helper 合并，但第一阶段不强行合并，避免扩大风险。

## 9. Sensor 目标选择算法

### 9.1 expected dates

expected dates 来源：

```text
silver_trade_calendar
WHERE exchange = 'SSE'
  AND is_open = true
```

窗口：

```text
最近 10 个 expected index trade dates
```

约束：

1. expected dates 必须与 `index_trade_day_sensor` 调用的 `build_trade_day_partition_registration_result(...)` 日期口径对齐。
2. 不能简单理解为 `calendar <= today`；必须考虑交易日注册 helper 的 completed-open-day 口径和同日注册窗口。
3. P0 必须只读对账：同一 `evaluated_at` 下，P4 expected window 的 eligible dates 与 `index_trade_day_sensor` 可注册日期集合一致。
4. 如果 expected window 与注册 helper 输出不一致，P4 停止，先修正 calendar 口径，不得继续实现 sensor。

### 9.2 registered gap guard

流程：

```text
expected dates
  -> 对比 cn_a_index_trade_days dynamic partitions
  -> 若存在 first_missing_registered_date
       skip，不提交 RunRequest
```

原因：

Dynamic partitions 是 Dagster 能否提交 partition run 的前置状态。

如果 expected date 没注册，不能跳过它去提交后续日期。

### 9.3 first not-ready gold

无 registered gap 后：

```text
for trade_date in expected_dates:
    gold_status = batch_status.status_for_trade_date(trade_date)

    if gold_status.ready:
        continue

    if gold_status.materialized and not gold_status.checks_passed:
        skip，人工处理，不提交后续日期

    if not gold_status.materialized:
        检查 selected date upstream
        upstream ready -> 提交 gold run
        upstream not ready -> skip
```

### 9.4 upstream gate

selected date 上游必须满足：

1. `silver_index_daily` ready，使用 selected-date lake readiness，不调用 `silver_index_daily_ready_for_trade_date(...)`。
2. `silver_index_basic` ready，使用 lake readiness，不调用 `silver_index_basic_ready(...)`。
3. seed/input gate ready。
4. registered index seed codes ready。

## 10. 性能设计

### 10.1 当前读取模型

| 项 | 当前模型 |
| --- | --- |
| target dates | 1 个 latest registered date |
| Dagster materialization 查询 | gold/silver/index_basic 各至少 1 次 |
| Dagster check history 查询 | 最坏 23 次 |
| 每次 check history limit | 5000 |
| 最坏扫描 records | 115000 |
| DuckDB/lake 查询 | seed/input 小规模检查 |
| 超时风险 | 高，已实际触发 60s timeout |

### 10.2 目标读取模型

| 项 | 目标模型 |
| --- | --- |
| target dates | 最近 10 个 expected index trade dates |
| Dagster check history 查询 | 0 |
| Dagster materialization 查询 | 0 或仅非热路径观测，正式 readiness 不依赖 |
| DuckDB/lake 文件扫描 | gold 最多 60 个文件，silver 第一阶段只扫 selected date，index_basic 1 个 snapshot |
| seed rows | 仓库 seed，小规模 |
| registered partitions | dynamic partitions 读取 2 组 |
| cursor size | summary only |
| 稳态目标 | < 5 秒 |
| 异常完整扫描目标 | < 10 秒 |
| 拒绝阈值 | > 15 秒必须停下重新设计 |

### 10.3 为什么不新增状态实体

新增 status manifest / readiness asset / summary table 会引入：

1. 新写入链路。
2. 写失败一致性问题。
3. 文件事实与状态事实不一致风险。
4. 历史回补成本。
5. 新的修复工具和审计负担。

当前 gold/silver/index_basic 的 readiness 主要都能由 lake parquet + seed + registered partitions 推导。

因此第一阶段必须先用 DuckDB/lake batch readiness 解决，不允许直接新增实体。

## 11. 错误处理语义

### 11.1 缺文件

```text
materialized = False
checks_passed = False
ready = False
```

含义：

目标文件不存在，可以提交正式 asset job 生成。

### 11.2 文件存在但 check 失败

```text
materialized = True
checks_passed = False
ready = False
```

含义：

不能自动重跑，不能推进后续日期。

必须返回 SkipReason，提示人工处理。

### 11.3 上游不 ready

```text
selected gold target 不提交
reason 指明 silver/index_basic/seed/input 哪个阻塞
```

### 11.4 扫描异常

DuckDB scan error、schema read error、路径异常：

```text
ready = False
materialized = path exists
checks_passed = False
reason = scan_error
```

sensor 必须 skip，不得提交 run。

## 12. 测试方案

### 12.1 Helper 单元测试

新增测试建议：

```text
tests/test_market_major_indices_lake_readiness.py
```

覆盖：

1. 10 日窗口全 ready。
2. 某日 gold 文件缺失，返回 first not-ready。
3. gold 文件存在但 schema 缺列，返回 materialized check problem。
4. gold trade_date 不匹配 partition，失败。
5. seed code 缺失，失败。
6. rank 顺序不匹配，失败。
7. price sanity 失败。
8. seed code 不在 index_basic，失败。
9. seed code 不在 registered index codes，失败。
10. index_basic 文件缺失，upstream not ready。
11. silver index daily 文件缺失，upstream not ready。
12. unknown date fail closed。
13. cursor payload 不包含逐文件大对象。

### 12.2 Sensor 契约测试

更新：

```text
tests/test_market_major_indices_daily_sensor.py
```

覆盖：

1. expected 有 `06-17/06-18`，`06-17` gold 缺失时，只提交 `06-17`。
2. `06-17` gold 文件存在但 checks failed 时 skip，不提交 `06-18`。
3. `06-17` gold ready，`06-18` not ready 时提交 `06-18`。
4. registered gap 存在时 skip，不调用 batch readiness。
5. selected date silver not ready 时 skip。
6. selected date index_basic not ready 时 skip。
7. seed/input gate not ready 时 skip。
8. run key 保持 `market_major_indices_daily:{trade_date}`。
9. 不新增直接 `dg.RunRequest(...)`。
10. 不解析 run key。

### 12.3 静态门禁

更新：

```text
tests/test_run_contract_static_gates.py
```

新增断言：

1. `market_major_indices_daily_sensor.py` 不得 import/use：
   - `gold_market_major_indices_daily_ready_for_trade_date`
   - `silver_index_daily_ready_for_trade_date`
   - `silver_index_basic_ready`
   - `asset_readiness_status`
   - `partition_dataset_readiness_status_from_latest_checks`
2. `market_major_indices_daily_sensor.py` 不得出现 `_latest_registered_trade_date` 作为正式目标选择。
3. sensor 热路径不得调用 `get_asset_check_execution_history`。
4. 新 helper 不得调用 Dagster event history。
5. run key 仍必须走统一 builder。

### 12.4 性能测试

本地性能样本必须记录：

| 指标 | 要求 |
| --- | --- |
| expected window | 60 dates |
| gold files scanned | 实际数量 |
| silver files scanned | 实际数量 |
| index_basic scans | 1 |
| DuckDB elapsed_ms | 必须记录 |
| Python total elapsed_ms | 必须记录 |
| Dagster event history calls | 0 |
| cursor payload size | 必须可控 |

不可接受：

1. 单 tick > 15 秒。
2. 出现 Dagster check history 读取。
3. 为了性能减少 check 语义。
4. 读取全历史而不是 10 日窗口。

### 12.5 P0 calendar 对账测试

P0 只读 profiling 必须额外记录：

1. `index_trade_day_sensor` 注册 helper 在同一 `evaluated_at` 下的 eligible dates。
2. P4 expected-date loader 的最近 10 个 expected dates。
3. 二者在窗口边界、今天是否开市、同日注册窗口前后是否一致。

若发现 P4 expected-date loader 会包含尚未允许注册的当天，或漏掉注册 helper 已允许的历史交易日，则 P4 实现不得推进。

## 13. 分阶段落地计划

### P0：只读 profiling 与设计对账

目标：

1. 记录当前实现耗时。
2. 记录 event history 查询次数模型。
3. 记录 DuckDB/lake batch 原型耗时。
4. 确认 10 日窗口下文件数和耗时；20/60 日只作为离线容量参考。
5. 对账 expected calendar 与 `index_trade_day_sensor` 注册 helper 日期口径。
6. 证明 selected-date silver/index_basic lake readiness 能覆盖现有上游门禁语义，且不调用 Dagster event history。

不改代码，不运行 Dagster job，不写 lake。

### P1：lake readiness helper

目标：

1. 新增 `market_major_indices_lake_readiness.py`。
2. 抽取/复用 gold/silver/index_basic blocking check SQL。
3. 完成 helper 单元测试。
4. 完成性能样本测试。
5. 明确 `checks_passed` 是 lake-derived check semantics，不是 Dagster event log 状态。

### P2：sensor 接入

目标：

1. `market_major_indices_daily_sensor` 改为 expected calendar + registered gap guard。
2. 使用 batch lake readiness。
3. 保留 run key/run config/job/sensor 名称。
4. 删除 event-history readiness import。
5. 更新 sensor 契约测试。
6. selected-date upstream gate 不得调用 `silver_index_daily_ready_for_trade_date(...)` / `silver_index_basic_ready(...)`。

### P3：静态门禁与文档收口

目标：

1. 加静态门禁防止回流。
2. 更新非分钟线连续性方案文档。
3. 记录性能结果。
4. 明确本轮不新增状态实体。

## 14. 风险与控制

| 风险 | 控制 |
| --- | --- |
| DuckDB readiness 与正式 check 语义漂移 | 必须逐 check 映射，复用现有 SQL/常量，测试覆盖每个 check。 |
| lake fact readiness 被误解为 Dagster event readiness | 数据结构和 cursor 明确 `checks_passed` 是 lake-derived semantics；缺 Dagster check event 属于冷路径审计，不进入 sensor 热路径。 |
| expected calendar 与 partition registration helper 口径不一致 | P0 必须对账 `index_trade_day_sensor` 注册 helper；不一致时先修 calendar 口径。 |
| cursor 过大 | cursor 只写 summary、sample，不写逐文件明细。 |
| 误把 check failed 当缺文件重跑 | status 必须区分 `materialized=False` 与 `materialized=True, checks_passed=False`。 |
| latest-only 回流 | 静态门禁禁止 `_latest_registered_trade_date` 作为正式目标。 |
| 性能优化引入新实体一致性问题 | 第一阶段禁止新增持久化状态实体。 |
| 只测 row count 导致假 ready | 明确禁止；完整 blocking check 语义必须覆盖。 |

## 15. 验收标准

1. `market_major_indices_daily_sensor` 不再使用 Dagster event/check history readiness。
2. sensor 不再按 latest registered date 选择目标。
3. 缺 `2026-06-17` 时，不会提交 `2026-06-18`。
4. gold 文件存在但 checks failed 时，不自动重跑，不推进后续日期。
5. upstream 不 ready 时，不提交 gold run。
6. run key/run config/job/sensor 名称保持不变。
7. 10 日窗口性能满足：
   - 稳态 < 5 秒
   - 异常完整扫描 < 10 秒
   - > 15 秒必须停止并重新设计
8. 静态门禁阻止 event-history readiness 回流。
9. 文档与代码口径一致。
10. 没有新增持久化状态实体。
11. P0 已证明 expected dates 与 `index_trade_day_sensor` 注册口径一致。
12. selected-date silver/index_basic 上游门禁已从 Dagster event readiness 切到 lake readiness，且不降低 blocking check 语义。

## 16. 已固定口径与执行前审批

已固定口径：

1. 本专项只聚焦 `market_major_indices_daily_sensor`，不扩大到全部非分钟线资产族。
2. expected window 沿用非分钟线连续性专项默认口径：最近 10 个 expected trade dates。
3. `silver_index_daily` 第一阶段只做 selected-date lake readiness，不做 60 日 silver batch。
4. `silver_index_basic` 第一阶段只做一次 lake readiness。
5. `check_market_major_indices_inputs_for_trade_date(...)` 第一阶段保留独立函数，避免把 seed/input gate 与 batch helper 一次性混杂。

执行前审批：

1. P0 只读 profiling 若读取正式 Dagster instance 或正式 lake，必须单独列出命令、`DAGSTER_HOME`、读取范围、预期耗时和风险，等待明确审批。
2. 若 P0 证明 60 日 batch lake readiness 无法满足性能门禁，不得降级 check 语义；必须停下重新设计。
