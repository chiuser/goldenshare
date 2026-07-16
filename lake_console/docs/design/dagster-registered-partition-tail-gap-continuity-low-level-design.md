# Dagster 注册分区尾部缺口 Continuity 修复 LLD

更新时间：2026-07-16

状态：P1/P2 已落地，P3 专项审计待执行

## 1. 文档目的

本文定义一类注册分区判断错误的修复方案：把“expected trade date 尚未注册，但它位于当前已注册日期之后的尾部”与“expected trade date 位于已注册日期之间的内部缺口”分开处理。

本问题已经在 `gold_stock_daily_qfq_update_job_sensor` 的实际运行中暴露。当前股票交易日注册器有明确的同日注册时间窗口，消费者却把尚未注册的当日尾部当成整个连续性窗口的硬缺口，导致已经具备上游数据的前一交易日也不能触发。

设计阶段已结束。本轮已按 P0/P1/P2 执行共享模型、股票族和指数族的代码修改与本地回归；未启动 Dagster，不写 Dagster DB，不写数据湖。第三批专属 sensor 仍按本文 P3 规则单独审计，不能因为共享模型已扩展就直接批量迁移。

## 2. 本次审计结论

### 2.1 真实运行事实

审计时观察到的 qfq 场景如下：

| 项目 | 事实 |
|---|---|
| sensor | `gold_stock_daily_qfq_update_job_sensor` 正常运行 |
| sensor 最近目标 | `gold_stock_daily_qfq_update:2026-07-14` |
| expected window | 最近 10 个股票交易日，包含 `2026-07-16` |
| registered partitions | `cn_a_stock_trade_days` 已注册到 `2026-07-15` |
| 未注册日期 | `2026-07-16`，属于已注册日期之后的尾部 |
| `silver_stock_daily[2026-07-15]` | 文件存在，约 5525 行 |
| `silver_adj_factor[2026-07-15]` | 文件存在，约 5528 行 |
| `gold_stock_daily_qfq[2026-07-15]` | 缺失 |
| 结果 | qfq sensor 在注册分区门禁处提前 skip，没有进入 first-not-ready readiness 选择 |

股票交易日注册器当前仍使用 `STOCK_TRADE_DAY_REGISTER_START = 17:00`。因此在 17:00 前，当前交易日尚未注册并不是异常事实，而是注册策略的正常结果。

### 2.2 根因

根因是连续性判断把两种不同事实压缩成了一个条件：

```python
if gap_status.first_missing_registered_date is not None:
    skip
```

当前 `build_registered_gap_status(...)` 会把 expected window 中所有未注册日期放入 `missing_registered_dates`，并把最早一个作为 `first_missing_registered_date`。它没有判断缺口后方是否已经有更晚的注册日期，因此不能区分：

1. **内部缺口**：中间某个日期未注册，但更晚日期已经注册。例如 expected 为 `07-14, 07-15, 07-16`，registered 为 `07-14, 07-16`，`07-15` 是真实连续性缺口。
2. **尾部未注册**：所有已注册日期形成前缀，后面的日期尚未注册。例如 expected 为 `07-14, 07-15, 07-16`，registered 为 `07-14, 07-15`，`07-16` 是待注册尾部，不应阻断 `07-15` 的更新。

这不是数据湖文件事实错误，也不是必须调整 17:00 注册策略才能修复的问题。正确修复是在消费者选择目标时，忽略尚未注册的尾部，同时继续硬阻断真正的内部缺口。

## 3. 代码审计依据

### 3.1 连续性基础模型

文件：

`/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/asset_guards/bounded_continuity.py`

当前实现：

- `ContinuityRegisteredGapStatus` 只有 `first_missing_registered_date` 和 `missing_registered_dates`，没有内部/尾部分类。
- `load_expected_trade_date_window(...)` 默认把日历中的日期加载到 `evaluated_at.date()`；只有传入 `same_day_register_start` 且当前时间未到门槛时，才会排除当天。
- qfq sensor 调用 `load_expected_trade_date_window(...)` 时没有传 `same_day_register_start`，所以会把尚未注册的当天放入 expected window。
- `build_registered_gap_status(...)` 以 expected 顺序构造缺口，并把第一缺口直接暴露给所有消费者。
- `select_first_not_ready_trade_date(...)` 本身只负责在给定日期集合内按 first-not-ready 语义选择，它不负责注册分区分类。
- `build_continuity_cursor_details(...)` 直接输出旧的 `first_missing_registered_date` 和缺口样本，需要增加尾部/内部摘要。

### 3.2 qfq sensor

文件：

`/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/sensors/stock_daily_qfq_sensor.py`

当前流程：

1. 读取最近 10 个 expected 股票交易日。
2. 读取 `cn_a_stock_trade_days` dynamic partitions。
3. 调用 `build_registered_gap_status(...)`。
4. 只要 `first_missing_registered_date` 非空，就返回 `missing_registered_partition`。
5. 只有注册分区完全无缺口时，才调用 `select_first_not_ready_gold_stock_daily_qfq_partition(...)`。
6. 之后才检查 qfq、stock daily、adj factor readiness。

因此，`2026-07-15` 的 qfq 缺失无法进入选择器，因为 `2026-07-16` 的尾部注册缺口在前面已经触发 skip。

### 3.3 股票分区注册器

文件：

`/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/sensors/stock_trade_day_sensor.py`

当前规则：

```python
STOCK_TRADE_DAY_REGISTER_START = time(17, 0)
```

该 sensor 通过 `build_trade_day_partition_registration_result(...)` 注册 `cn_a_stock_trade_days`，每个 tick 最多处理有限数量分区。它的职责是注册分区，不触发股票日线/qfq 数据任务。本修复不调整注册时间、不修改注册数量、不让业务 sensor 越权注册分区。

### 3.4 共享消费者审计

`build_registered_gap_status(...)` 当前被以下 sensor 使用：

- `stock_daily_qfq_sensor.py`
- `stock_daily_sensor.py`
- `suspend_d_sensor.py`
- `market_breadth_continuity_sensor.py`
- `clickhouse_market_breadth_continuity_sensor.py`
- `stock_return_distribution_continuity_sensor.py`
- `raw_index_daily_update_job_sensor.py`
- `silver_index_daily_sensor.py`
- `market_major_indices_daily_sensor.py`
- `stock_adj_factor_sensor.py`
- `stock_current_trade_day_sensor.py`
- `dc_board_sensor.py`
- `dc_board_silver_sensor.py`
- `dc_daily_technical_sensor.py`
- `stk_nineturn_sensor.py`
- `stock_mins_silver_trade_day_sensor.py`

并非所有消费者都可以直接套用同一迁移方式。它们的 expected calendar、dynamic partition、同日注册时间和数据前置条件不同，必须按资产族分级迁移。

## 4. 正确的连续性口径

### 4.1 注册日期分类

给定一个 bounded expected window 和当前已注册日期集合：

```text
expected = 最近窗口内的有序交易日
registered = 当前 dynamic partition 中已注册的日期
```

定义：

- **已注册 expected 日期**：同时存在于 expected 和 registered 的日期。
- **内部注册缺口**：缺失日期之后仍存在更晚的已注册 expected 日期。
- **尾部未注册日期**：缺失日期之后不存在更晚的已注册 expected 日期；它们位于当前已注册前缀之后。
- **可行动日期集合**：当前窗口中已经注册的 expected 日期；只有在内部缺口为空时，才允许送入 readiness selector。

示例：

| expected | registered | 分类 | 结果 |
|---|---|---|---|
| `07-14, 07-15, 07-16` | `07-14, 07-15` | `07-16` 是尾部未注册 | 允许判断 `07-14/07-15`，不评价 `07-16` |
| `07-14, 07-15, 07-16` | `07-14, 07-16` | `07-15` 是内部缺口 | 整个消费者 skip |
| `07-14, 07-15, 07-16` | 空 | 没有可行动日期 | skip，不发起更新 |
| `07-14, 07-15, 07-16` | 全部注册 | 无注册缺口 | 正常判断完整窗口 |

### 4.2 硬规则

1. 内部注册缺口必须继续阻断，不能跳过中间日期直接更新后续日期。
2. 纯尾部未注册不阻断已注册日期的 first-not-ready 选择。
3. 目标分区必须已经注册，绝不能为未注册日期提交 RunRequest。
4. 如果窗口没有任何已注册日期，sensor 只能 skip。
5. 文件已存在但 blocking check 失败，继续保持人工处理口径，不自动覆盖。
6. 上游 readiness 未满足，继续阻断下游。
7. 不改变 asset、job、check、partition set、run key、run config 名称和生成规则。
8. 不在业务 sensor 中补注册 dynamic partition。

### 4.3 2026-07-16 场景的目标行为

在 expected 为 `2026-07-07` 至 `2026-07-16`、registered 只到 `2026-07-15` 时：

1. 把 `2026-07-16` 分类为尾部未注册。
2. 将有效判断窗口裁剪到已注册日期，末日为 `2026-07-15`。
3. 读取 `gold_stock_daily_qfq` 最近已注册日期的 readiness。
4. 若 `2026-07-15` 文件缺失且 silver daily、adj factor ready，则提交 `gold_stock_daily_qfq_update:2026-07-15`。
5. 若 `2026-07-15` 已 ready，则返回 all-ready，并在 cursor 中记录待注册尾部。
6. 等交易日注册 sensor 注册 `2026-07-16` 后，下一次 tick 才把它纳入评价。

## 5. 目标内存态 API 设计

### 5.1 不新增持久化实体

本修复不新增数据库表、status manifest、readiness asset、Dagster definition 或状态文件。新增字段只存在于内存态 dataclass 和 compact cursor details 中。

### 5.2 推荐扩展 `ContinuityRegisteredGapStatus`

在现有 dataclass 基础上增加以下内存字段：

```python
internal_missing_registered_dates: tuple[str, ...]
trailing_unregistered_dates: tuple[str, ...]
first_internal_missing_date: str | None
first_trailing_unregistered_date: str | None
last_registered_expected_date: str | None
```

保留现有字段：

```python
expected_trade_dates
registered_trade_dates
first_missing_registered_date
missing_registered_dates
```

保留旧字段是为了让现有 cursor 和测试在迁移期间仍能读取已有事实；消费者不得再把 `first_missing_registered_date` 当作“所有缺口都必须阻断”的唯一判断依据。

建议增加只读属性：

```python
@property
def has_internal_gap(self) -> bool: ...

@property
def has_trailing_gap(self) -> bool: ...

@property
def actionable_expected_trade_dates(self) -> tuple[str, ...]: ...
```

`actionable_expected_trade_dates` 必须只返回已注册 expected 日期，且在 `has_internal_gap` 为 true 时返回空集合，避免调用方遗漏内部缺口门禁。

### 5.3 分类算法

分类只使用当前 expected/registered 内存集合：

```text
1. 规范化并去重 expected，保留日期升序。
2. 规范化 registered，并只取 expected 中已注册日期。
3. 计算 missing = expected - registered。
4. 找到 last_registered_expected_date。
5. missing 中位于 last_registered_expected_date 之前的日期属于 internal。
6. missing 中位于 last_registered_expected_date 之后的日期属于 trailing。
7. registered 为空时，不产生可行动日期。
8. internal 非空时，actionable_expected_trade_dates 为空。
9. internal 为空时，actionable_expected_trade_dates 为窗口内已注册日期。
```

实现必须保留 bounded sample，不把全窗口以外的 registered partition 写入 cursor。

### 5.4 兼容字段和 cursor

当前 `build_sensor_cursor(...)` 的顶层 `SENSOR_CURSOR_SCHEMA_VERSION` 为 `1`，本次只增加 details 内的小字段，不改变顶层 envelope，不需要改变全局版本。

新增 cursor 字段建议为：

```text
registration_gap_class: none | internal | trailing | empty
first_internal_missing_date
first_trailing_unregistered_date
trailing_unregistered_count
actionable_registered_count
last_registered_expected_date
```

保留：

```text
first_missing_registered_date
missing_registered_dates
registered_count
expected_count
```

约束：

- `reason_code` 必须保持 ASCII。
- 不写完整 dynamic partition 列表。
- 不写逐文件明细、完整股票代码、完整板块代码或 batch status。
- cursor 继续保持不超过 8192 bytes。

建议 reason code：

- `internal_missing_registered_partition`：存在内部注册缺口。
- `pending_registered_partition_tail`：只有尾部未注册，且当前没有可行动日期。
- 原有 `missing_registered_partition` 仅在兼容场景或未迁移消费者中继续出现；迁移后的消费者应显式区分内部和尾部。

## 6. Sensor 目标流程

迁移后的通用流程：

```text
读取 bounded expected window
    -> 读取当前 registered partitions
    -> 分类 internal / trailing registration gap
    -> internal 非空：skip
    -> 取 actionable_expected_trade_dates
    -> 对 actionable dates 执行 batch lake readiness
    -> select_first_not_ready_trade_date
    -> 校验 selected date 已注册
    -> 执行 selected-date upstream gates
    -> 最多提交一个 RunRequest
```

关键点：

1. readiness batch 不应把尾部未注册日期作为“缺文件”目标继续扫描；优先将有效窗口裁剪到 actionable dates。
2. 如果实现上必须保留完整 expected window 扫描，selector 也必须显式过滤未注册日期；首选方案仍是直接传入 actionable dates，减少无效文件规划。
3. 内部缺口在 readiness 之前阻断，保持当前的连续性保护。
4. 选中的日期必须在 registered set 中，形成最后一道安全断言。
5. sensor 仍然不读取 Dagster event/check history，不调用 Tushare，不访问 Prod DB。

## 7. 代码修改清单

### 7.1 第一批必须修改

#### A. 共享连续性基础

文件：

`/Users/congming/github/goldenshare/lake_console/orchestrator/src/orchestrator/defs/asset_guards/bounded_continuity.py`

修改内容：

- 扩展 `ContinuityRegisteredGapStatus`。
- 在 `build_registered_gap_status(...)` 中完成内部/尾部分类，或新增内部分类 helper 并由现有 builder 调用。
- 增加 actionable 日期属性/helper。
- 扩展 `to_cursor_details()` 和 `build_continuity_cursor_details(...)` 的 compact 输出。
- 保持现有 `select_first_not_ready_trade_date(...)` 的纯选择语义，不把注册分区规则塞入 selector。

#### B. 股票日线/qfq 共享注册尾部消费者

文件：

- `sensors/stock_daily_qfq_sensor.py`
- `sensors/stock_daily_sensor.py`
- `sensors/suspend_d_sensor.py`
- `sensors/market_breadth_continuity_sensor.py`
- `sensors/clickhouse_market_breadth_continuity_sensor.py`
- `sensors/stock_return_distribution_continuity_sensor.py`

修改内容：

- 用 `has_internal_gap` 替代“任意 `first_missing_registered_date` 都 skip”。
- readiness 输入改为 actionable registered dates。
- 只有纯尾部且没有可行动日期时使用 `pending_registered_partition_tail`。
- 更新 cursor 的 registration gap 摘要。
- 保留 materialized check failed、upstream not ready、first-not-ready 等既有门禁。

### 7.2 第二批必须修改

#### C. 指数日线消费者

文件：

- `sensors/raw_index_daily_update_job_sensor.py`
- `sensors/silver_index_daily_sensor.py`
- `sensors/market_major_indices_daily_sensor.py`

修改内容与股票族一致，但必须使用 `cn_a_index_trade_days` 对应的 expected/registered 集合和 index-specific cursor。不得复用股票分区集合。

### 7.3 第三批审计后决定

以下代码需要先用专门测试确认是否存在相同尾部问题，再决定是否纳入同一实现批次：

- `sensors/stock_adj_factor_sensor.py`
- `sensors/stock_current_trade_day_sensor.py`
- `sensors/dc_board_sensor.py`
- `sensors/dc_board_silver_sensor.py`
- `sensors/dc_daily_technical_sensor.py`
- `sensors/stk_nineturn_sensor.py`
- `sensors/stock_mins_silver_trade_day_sensor.py`

原因：

- `stock_adj_factor_sensor.py` 使用 `cn_a_stock_current_trade_days`，注册起点和源任务开始时间是独立口径。
- `dc_board` 与 `dc_daily_technical` 使用专属分区集，且 expected window 通常不设同日注册时间。
- `stk_nineturn_sensor.py` 有自己的 raw/silver 链路和 repair 语义。
- `stock_mins_silver_trade_day_sensor.py` 使用 `stk_mins_continuity.py` 的分钟线专项模型，不能通过通用 helper 盲改。

第三批不允许直接批量替换条件；必须先增加各自 tail/internal 测试，再根据真实 registration timing 选择迁移或维持现状。

### 7.4 明确不修改

本专项不修改：

- `stock_trade_day_sensor.py` 的 17:00 注册时刻。
- `cn_a_trade_day_sensor.py` 的 dynamic partition 注册算法。
- asset、job、check、partition set 名称。
- run key、run config、job/sensor 名称。
- lake 文件布局、DuckDB readiness SQL 的业务规则。
- Dagster event history API 使用方式；本专项不引入 event history 查询。
- `stock_mins_continuity.py`，除非专项测试证明它有同类尾部误判。

## 8. 影响面评估

### 8.1 直接受益

以下资产族使用股票/指数交易日分区，并有明确的同日注册延迟，属于第一、第二批直接受益范围：

| 资产族 | 典型消费者 | 影响 |
|---|---|---|
| 股票日线 raw/silver | `stock_daily_sensor.py` | 已注册前序交易日不再被当天尾部注册缺口挡住 |
| 股票日线 qfq | `stock_daily_qfq_sensor.py` | 修复本次 `2026-07-15` 未触发问题 |
| 停复牌日线 | `suspend_d_sensor.py` | 保留内部缺口阻断，允许已注册前缀继续推进 |
| 市场宽度 | `market_breadth_continuity_sensor.py`、ClickHouse variant | 下游只评价已注册交易日 |
| 股票收益分布 | `stock_return_distribution_continuity_sensor.py` | 同上 |
| 指数日线 raw/silver | `raw_index_daily_update_job_sensor.py`、`silver_index_daily_sensor.py` | 适配 16:00 同日注册前的尾部日期 |
| 主要指数日线 | `market_major_indices_daily_sensor.py` | 不再因 index 分区尾部未注册而阻断已注册目标 |

### 8.2 安全行为保持不变

- 中间日期缺失但更晚日期已经注册时，仍然 skip。
- 已有物理文件但 blocking check 失败时，仍然不自动覆盖。
- upstream readiness 不满足时，仍然不提交下游 run。
- 未注册目标日期永远不提交 RunRequest。
- 交易日注册器仍是唯一注册入口。

### 8.3 可能的行为变化

修复后，股票族在 17:00 前、指数族在 16:00 前，可能会对“已经注册的前一交易日”提交更新。这是有意的行为变化：它消除了注册尾部对已注册日期的错误阻断，并不会让 sensor 处理未注册日期。

如果前序数据源本身尚未完成，现有 silver/qfq/upstream readiness 会继续阻断，因此不会把“提前解除注册门禁”变成“无条件提前请求”。

### 8.4 不影响的边界

- 不修改历史数据文件。
- 不修改 Dagster historical event。
- 不改变 dynamic partition 数量和注册时间规则。
- 不改变运行 key 幂等性。
- 不新增持久化状态。
- 不改变 UI 中资产名称、job 名称或 check 名称。

## 9. 性能评估

### 9.1 算法成本

注册分区分类只在最近窗口内运行：

```text
W = 最近 10 个 expected trade dates
```

复杂度：

- expected 规范化、去重、排序：`O(W log W)`。
- registered set 构造：`O(W)`，只保留当前窗口交集。
- internal/trailing 分类：`O(W)`。
- actionable 日期生成：`O(W)`。

在当前窗口上限 10 的情况下，这部分成本可以忽略，不产生新的数据库、网络或文件扫描压力。

### 9.2 热路径门禁

本修复不得引入：

- Dagster event/check history 查询。
- Tushare 请求。
- Prod DB 查询。
- 全历史 dynamic partition 扫描。
- 逐日创建多个 DuckDB connection。
- 逐行 Python 数据处理。

现有 batch readiness 仍使用本地 DuckDB/lake；将输入从完整 expected window 裁剪到 actionable registered dates后，尾部未注册日期不会再触发无意义的文件规划和状态汇总，理论上扫描文件数不增，通常减少。

### 9.3 性能验收指标

每个迁移后的 sensor tick 至少记录或测试以下指标：

| 指标 | 门禁 |
|---|---|
| expected 日期数 | 不超过现有 10 日窗口 |
| registered 窗口日期数 | 不超过 10 |
| internal gap 分类耗时 | 仅内存计算，不应成为可见耗时来源 |
| DuckDB connection 数 | 每个 tick 不增加；现有 helper 约束保持 |
| event history 调用次数 | 0 |
| Tushare/Prod DB 调用次数 | 0 |
| RunRequest 数 | 每 tick 最多 1 个 |
| cursor 大小 | 不超过 8192 bytes |
| 扫描文件数 | 不高于修复前，尾部未注册时应不增加 |

## 10. 测试计划

### 10.1 基础连续性测试

修改/扩展：

`/Users/congming/github/goldenshare/lake_console/orchestrator/tests/test_bounded_continuity.py`

必须覆盖：

1. expected `07-14,07-15,07-16`，registered `07-14,07-15`：
   - internal gap 为空。
   - trailing 为 `07-16`。
   - actionable 为 `07-14,07-15`。
2. expected `07-14,07-15,07-16`，registered `07-14,07-16`：
   - internal 为 `07-15`。
   - actionable 为空。
   - sensor 仍应 skip。
3. registered 为空：
   - 没有可行动日期。
   - 不产生 run request。
4. 多个连续尾部未注册日期：
   - 分类和 sample 有界。
5. registered 含 expected window 外日期：
   - 不影响当前窗口分类。
6. 日期重复、格式不合法、顺序乱：
   - 继续复用现有规范化和 fail-closed 语义。

### 10.2 qfq sensor 测试

修改：

`/Users/congming/github/goldenshare/lake_console/orchestrator/tests/test_stock_daily_qfq_sensor_contracts.py`

新增：

- 尾部 `2026-07-16` 未注册、`2026-07-15` qfq 缺失且上游 ready 时，提交 `gold_stock_daily_qfq_update:2026-07-15`。
- 只有尾部未注册且已注册日期全部 ready 时，skip，reason code 为 pending tail 或 all-ready，并保留尾部摘要。
- `2026-07-15` 内部缺口、`2026-07-16` 已注册时，仍在 readiness 前 skip。
- 被选择日期未注册时强制失败测试，证明最后一道 registered target guard 存在。
- materialized but checks failed 的既有测试继续通过。
- cursor 保持 ASCII reason code，大小不超过 8192 bytes。

### 10.3 股票族与指数族回归

至少覆盖：

- `tests/test_stock_daily_sensor.py`
- `tests/test_suspend_d_sensor.py`
- `tests/test_market_breadth_continuity_sensors.py`
- `tests/test_raw_index_daily_update_job_sensor.py`
- `tests/test_silver_index_daily_sensor.py`
- `tests/test_market_major_indices_daily_sensor.py`
- `tests/test_stock_return_distribution_continuity_sensor.py`
- `tests/test_run_contract_static_gates.py`

测试要证明：

- 内部缺口仍阻断。
- 纯尾部未注册不阻断已注册日期。
- readiness scan 不包含未注册目标。
- 每 tick 仍最多一个 RunRequest。
- 不调用 `instance.get_event_records(...)`。
- 不引入手写 run key 或新的持久化状态。

### 10.4 第三批专属测试

在决定迁移 `stock_adj_factor`、`dc_board`、`dc_daily_technical`、`stk_nineturn` 和分钟线前，分别增加针对其 partition registration timing 的 tail/internal fixture。若专属契约要求“全窗口注册后才允许处理”，则保留原规则并在文档中说明，不因共享 helper 自动放宽。

## 11. 开发推进步骤

### P0：基础模型与测试

1. 修改 `bounded_continuity.py` 的内存态 gap model。
2. 保留旧字段，新增 internal/trailing/actionable 字段。
3. 完成基础分类单测。
4. 不改任何生产 sensor 行为，先确保基础测试通过。

### P1：股票日线与 qfq

1. 迁移 `stock_daily_sensor.py`。
2. 迁移 `stock_daily_qfq_sensor.py`。
3. 迁移 `suspend_d_sensor.py`。
4. 迁移市场宽度、ClickHouse 市场宽度、收益分布 sensor。
5. 运行股票族 targeted tests 和静态门禁。

### P2：指数日线

1. 迁移 raw index、silver index、major indices sensor。
2. 使用 index-specific expected/registered partition set。
3. 运行指数族 targeted tests。

### P3：第三批专属审计

1. 对 current trade day、adj factor、dc board、technical、nineturn、分钟线做 tail/internal 行为测试。
2. 根据测试结果决定迁移或保持当前硬门禁。
3. 不以“调用了共享 helper”为理由直接批量替换。

### P4：只读验证与回归

1. 本地运行基础、股票族、指数族和静态测试。
2. 只读加载 definitions，确认 asset/job/check/sensor 数量和名称不变。
3. 只读查看传感器 cursor，确认 2026-07-15 能进入 qfq 目标选择、2026-07-16 仍未被提交。
4. 记录 DuckDB 扫描文件数、elapsed_ms、cursor bytes。
5. 不启动正式任务，不写 lake，不写 Dagster event。

## 12. 验收标准

修复完成必须同时满足：

- 纯尾部未注册不再阻断已注册日期的 first-not-ready 选择。
- 内部注册缺口仍然阻断。
- 未注册目标不会产生 RunRequest。
- qfq 场景在 `2026-07-16` 未注册时能够评价并触发 `2026-07-15`，前提是上游 readiness 满足。
- 股票族和指数族的 run key、run config、job/sensor/asset/check 名称不变。
- sensor 不读取 Dagster event history，不调用 Tushare/Prod DB。
- 每个 sensor tick 最多一个 RunRequest。
- cursor 为 bounded、ASCII reason code 且不超过 8192 bytes。
- 现有 materialized check failed、upstream not ready、first-not-ready 保护不回退。
- 只读 definitions 检查通过，targeted tests 和静态门禁通过。

## 13. 风险与控制

### 风险一：错误放宽内部缺口

控制：分类算法以“缺失日期后是否存在更晚已注册日期”为依据；内部缺口单独字段和单独测试，任何内部缺口仍 fail closed。

### 风险二：未注册日期被误选

控制：readiness 输入使用 actionable 日期，选中后再做 registered set membership 断言；未注册日期不得进入 `build_run_request(...)`。

### 风险三：第三方专属分区语义被误改

控制：第三批先审计、后迁移；分钟线继续遵守独立 continuity model，不能直接套股票日线实现。

### 风险四：cursor 体积增长

控制：只写 bounded count/date/sample，保持现有 cursor 8KB 上限和禁止大对象字段门禁。

### 风险五：以放宽注册门禁掩盖源数据未完成

控制：注册门禁只允许已注册日期进入选择；silver/adj factor/上游 readiness 仍是独立硬门禁，不改变数据源成功判定。

## 14. 参考代码、规则与文档

代码：

- `lake_console/orchestrator/src/orchestrator/defs/asset_guards/bounded_continuity.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/stock_daily_qfq_sensor.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/stock_trade_day_sensor.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/cn_a_trade_day_sensor.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/stock_daily_sensor.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/suspend_d_sensor.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/raw_index_daily_update_job_sensor.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/silver_index_daily_sensor.py`
- `lake_console/orchestrator/src/orchestrator/defs/sensors/market_major_indices_daily_sensor.py`
- `lake_console/orchestrator/src/orchestrator/defs/run_contracts/cursors.py`

设计文档：

- `lake_console/docs/design/dagster-bounded-continuity-selector-foundation-low-level-design.md`
- `lake_console/docs/design/dagster-bounded-continuity-selector-foundation-plan.md`
- `lake_console/docs/design/dagster-data-pipeline-performance-governance.md`
- `lake_console/docs/design/dagster-asset-schema-contract-design.md`

规则：

- `/Users/congming/github/goldenshare/AGENTS.md`
- `/Users/congming/github/goldenshare/lake_console/AGENTS.md`
- `/Users/congming/github/goldenshare/lake_console/orchestrator/AGENTS.md`
- `/Users/congming/github/goldenshare/lake_console/orchestrator/CODING_STANDARDS.md`

本 LLD 的核心边界是：**不改变分区注册器的业务时间策略，只修复消费者对“尾部未注册”和“内部缺口”的错误分类。**

## 15. 实现对账

### 15.1 已落地代码

共享模型和 cursor 压缩层：

- `lake_console/orchestrator/src/orchestrator/defs/asset_guards/bounded_continuity.py`
  - 增加 internal/trailing/empty 分类。
  - 增加 `has_internal_gap`、`has_trailing_gap`、`actionable_expected_trade_dates`。
  - 保留旧 `first_missing_registered_date` 字段，避免历史 cursor 结构失去兼容读取能力；迁移消费者不再用它作为唯一硬门禁。
- `lake_console/orchestrator/src/orchestrator/defs/run_contracts/cursor_payloads.py`
  - compact cursor 保留 registration gap class、首个 internal/trailing 日期、计数、最后注册日期和 actionable 数量。

已迁移股票族：

- `stock_daily_qfq_sensor.py`
- `stock_daily_sensor.py`
- `suspend_d_sensor.py`
- `market_breadth_continuity_sensor.py`
- `clickhouse_market_breadth_continuity_sensor.py`
- `stock_return_distribution_continuity_sensor.py`

已迁移指数族：

- `raw_index_daily_update_job_sensor.py`
- `silver_index_daily_sensor.py`
- `market_major_indices_daily_sensor.py`

上述消费者统一遵守：内部缺口先阻断；纯尾部只裁剪到已注册 actionable 日期；无 actionable 日期时返回 bounded skip；readiness 不读取尾部未注册日期；每 tick 最多一个 run request。

### 15.2 测试与验证结果

新增/更新测试：

- `tests/test_bounded_continuity.py`
  - 覆盖 trailing、internal、empty 三类注册状态和 actionable 日期集合。
- `tests/test_stock_daily_qfq_sensor_contracts.py`
  - 覆盖尾部未注册仍可提交已注册前一日期，且 selector 不接收尾部日期。
- 更新股票族、指数族内部缺口文案断言。

本地回归命令覆盖共享模型、qfq、股票/停牌/市场宽度、raw/silver index、major indices 和静态门禁，共 `155 passed`。另已通过：

- 受影响 Python 文件 `py_compile`。
- `git diff --check`。
- 迁移消费者静态检索：未发现仍以 `first_missing_registered_date` 作为注册缺口硬门禁。

### 15.3 尚未落地范围

以下 sensor 尚未因本轮改动而自动放宽，必须按本文 P3 单独设计 tail/internal fixture 后再决定：

- `stock_adj_factor_sensor.py`
- `stock_current_trade_day_sensor.py`
- `dc_board_sensor.py`
- `dc_board_silver_sensor.py`
- `dc_daily_technical_sensor.py`
- `stk_nineturn_sensor.py`
- `stock_mins_silver_trade_day_sensor.py`

本轮没有运行 `dg check defs`、sensor tick、job、materialization、event backfill 或正式 lake 操作；正式启用前仍需在 definitions 重载后做只读加载与运行态观察。
