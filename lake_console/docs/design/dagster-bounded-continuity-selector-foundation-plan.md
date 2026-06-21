# Dagster Bounded Continuity Selector 基础能力专项方案

更新时间：2026-06-21

状态：已拍板方案，作为非分钟线连续性优化前置专项

范围：为非分钟线历史连续资产提供统一的显式补洞选择能力。本文档只定义基础能力，不直接修改任何 sensor、asset、job、check 或 Dagster runtime。

对应 LLD：[Dagster Bounded Continuity Selector 基础能力 LLD](dagster-bounded-continuity-selector-foundation-low-level-design.md)

## 1. 背景

股票分钟线连续性专项已经证明：历史连续资产不能依赖 latest-only 目标选择，也不能在 sensor 热路径里逐日深扫 Dagster event/check history。

非分钟线专项继续暴露同一类问题：

1. 一部分手写 sensor 仍需要从 latest-only 改成 first-not-ready。
2. 一部分 declarative automation 资产使用 `AutomationCondition.eager() & all_deps_blocking_checks_passed()`，默认不等于历史补洞能力。
3. 多个资产族需要重复实现以下流程：

```text
expected calendar
  -> registered gap guard
  -> batch / bounded readiness
  -> first missing / first not-ready
  -> selected-date upstream gate
  -> RunRequest or SkipReason
```

因此需要先沉淀一个通用基础能力，再应用到各个 sensor，避免每个资产族各写一套近似但不一致的补洞逻辑。

## 2. 官方语义依据

Dagster 官方文档对 declarative automation 的语义说明决定了本专项边界：

1. `AutomationCondition.eager()` 默认只更新 time-partitioned asset 的 latest time partition；若历史分区更新也要触发下游，需要移除 `in_latest_time_window()`。
   - 参考：<https://docs.dagster.io/guides/automate/declarative-automation/customizing-automation-conditions/customizing-eager-condition>
2. `AutomationCondition.on_missing()` 默认也只更新 latest time partition；延迟超过新 partition 出现时间时，不会自动 catch up，必须移除或替换 `in_latest_time_window()`。
   - 参考：<https://docs.dagster.io/guides/automate/declarative-automation/customizing-automation-conditions/customizing-on-missing-condition>
3. automation condition 必须由 `AutomationConditionSensorDefinition` 评估；对应 sensor 未开启时，不会提交 run。
   - 参考：<https://docs.dagster.io/guides/automate/declarative-automation/automation-condition-sensors>

结论：

```text
默认 eager / on_missing 可以服务 latest propagation，
但不能作为历史连续资产的正式补洞机制。
```

## 3. 适用范围

适用：

1. 历史连续日频资产。
2. 使用 trade date partition，且任一历史交易日缺失都会形成数据洞的资产。
3. 需要停机恢复后按最早缺口补齐的资产。
4. 需要明确性能门禁和补洞顺序的 sensor。

不适用：

1. current snapshot 资产，例如 current-listed 股票基础快照。
2. 只关心最新上游更新传播的 latest/event-driven 资产。
3. 不支持历史日期输入或没有 trade date partition 的资产。
4. 需要人工审批的全历史 bootstrap / migration 任务。

## 4. 设计目标

1. 提供统一的 bounded continuity selector。
2. 默认窗口为最近 60 个 expected trade dates。
3. 统一处理 registered gap、first missing、first not-ready、check failed stop、ready frontier。
4. 支持不同资产族接入不同 readiness provider。
5. sensor 热路径禁止无界 Dagster event/check history 深扫。
6. 不新增持久化状态实体：不新增 manifest、summary asset、readiness asset、数据库表或配置项。
7. 不改变 run key 治理口径；RunRequest 必须继续走统一 builder。
8. cursor 只写 summary，不写逐文件明细。

## 5. 标准组件

### 5.1 Expected Dates Loader

职责：

1. 从 `silver_trade_calendar` 读取 `exchange='SSE' AND is_open=true` 的 expected trade dates。
2. 支持 `min_trade_date`。
3. 支持同日窗口；若资产族不允许当天提前跑，必须与对应 partition registration sensor 的日期口径一致。
4. 输出最近 60 个 expected trade dates。

约束：

1. 不能用 dynamic partitions 替代权威 calendar。
2. 不能简单写成 `trade_date <= today`；必须对齐对应注册 helper 的 completed-open-day / same-day window 口径。
3. 各资产族接入前必须做只读 calendar 对账。

### 5.2 Registered Gap Guard

职责：

1. 对比 expected dates 与 dynamic partition set。
2. 如果存在最早未注册日期，sensor 必须 skip。
3. 不允许跳过未注册日期去提交后续数据 run。

输出：

```text
first_missing_registered_date
registered_count
expected_count
sample_missing_registered_dates
```

### 5.3 Readiness Model

标准日期状态：

```python
@dataclass(frozen=True)
class ContinuityDateReadiness:
    trade_date: str
    ready: bool
    materialized: bool
    checks_passed: bool
    reason: str
    failed_check_names: tuple[str, ...]
    missing_file_paths: tuple[str, ...]
    summary: Mapping[str, object]
```

字段语义：

| 字段 | 含义 |
| --- | --- |
| `materialized` | 目标物理事实是否存在；按资产族可来自 lake 文件、bounded materialization set 或其它正式事实。 |
| `checks_passed` | 当前 readiness provider 的正式 blocking check 等价语义是否通过。 |
| `ready` | `materialized and checks_passed`。 |
| `failed_check_names` | 物理事实存在但质量语义失败的 check 名称。 |
| `missing_file_paths` | 缺失的必要文件路径样本。 |
| `summary` | 小型可观测摘要，禁止塞逐文件明细。 |

标准批量状态：

```python
@dataclass(frozen=True)
class ContinuityBatchReadiness:
    expected_trade_dates: tuple[str, ...]
    first_missing_registered_date: str | None
    first_not_ready_trade_date: str | None
    ready_through_trade_date: str | None
    statuses_by_trade_date: Mapping[str, ContinuityDateReadiness]
    elapsed_ms: int

    def status_for_trade_date(self, trade_date: str) -> ContinuityDateReadiness: ...
    def to_cursor_details(self) -> dict[str, object]: ...
```

### 5.4 Readiness Provider

每个资产族必须显式选择 readiness provider，不允许默认逐日调用 Dagster 单日 wrapper。

可选实现：

1. DuckDB/lake batch readiness：优先方案，适合能从 Parquet 文件事实和正式 check SQL 推导 ready 的资产。
2. Bounded metadata readiness：仅在 lake 文件事实无法表达正式语义时使用，必须证明读取次数和记录上限可控。
3. Selected-date upstream gate：只在已经选定 target date 后调用，不得放进 60 日循环。

禁止：

1. 在 60 日窗口中逐日调用 `asset_readiness_status(...)`。
2. 在 60 日窗口中逐日调用 `dataset_readiness_status(...)`。
3. 在 60 日窗口中逐日调用单日 readiness wrapper。
4. 用 row count 或 file exists 冒充完整 blocking check 语义。

### 5.5 Selector Algorithm

标准顺序：

```text
load expected dates
  -> read registered partitions
  -> if registered gap: skip
  -> batch readiness
  -> scan dates oldest to newest:
       ready -> continue
       materialized but checks failed -> skip, require manual handling
       not materialized -> selected target
  -> selected target upstream gate
  -> build RunRequest or SkipReason
```

关键口径：

1. first-not-ready 必须从窗口最早日期向后找。
2. 已 materialized 但 checks failed 必须停止推进，不自动重跑后续日期。
3. 缺文件 / 未生成才允许提交 run。
4. 上游不 ready 时 skip，不提交目标 run。

### 5.6 Cursor Contract

cursor 必须包含：

1. `schema_version`
2. `evaluated_at`
3. `target_date`
4. `selected_trade_date`
5. `first_missing_registered_date`
6. `first_not_ready_trade_date`
7. `ready_through_trade_date`
8. `blocked_reason`
9. `batch_elapsed_ms`
10. 小型 status samples

禁止：

1. 写入逐文件明细。
2. 写入大数组。
3. 写入无法稳定解析的临时字段。

## 6. 性能门禁

默认门禁：

| 项 | 口径 |
| --- | --- |
| expected window | 最近 60 个 expected trade dates。 |
| Dagster event history | sensor 热路径默认 0 次；确需使用必须 bounded 并单独说明。 |
| DuckDB | 优先批量读取，不做 Python 明细行循环。 |
| cursor | summary only。 |
| 状态实体 | 不新增。 |
| 稳态目标 | 单 tick < 5 秒。 |
| 异常完整扫描目标 | 单 tick < 10 秒。 |
| 拒绝阈值 | > 15 秒必须停下重设读取模型。 |

任何资产族接入前必须记录：

1. 日期窗口大小。
2. 文件数量 / partition 数量。
3. readiness provider 读取次数。
4. 20 日与 60 日耗时对比，或明确无需对比的理由。
5. 是否读取正式 Dagster instance；若读取，必须按正式只读审批。

## 7. P6 Automation 派生资产的应用口径

P6 不再继续把默认 `eager()` 当作历史补洞候选。

已拍板：

1. 对历史连续派生资产使用显式 bounded continuity sensor。
2. 当前 `AutomationCondition.eager() & all_deps_blocking_checks_passed()` 只可理解为 latest propagation，不作为历史补洞保证。
3. P6 显式 sensor 成为正式补洞入口后，必须移除这四个派生资产上的 `automation_condition`，避免它们继续被默认 automation condition sensor 识别。
4. P6 必须删除或退出对应 `AutomationConditionSensorDefinition`，不保留 active automation sensor 作为辅助触发路径。
5. 如果未来确实需要 latest propagation 辅助能力，必须单独立项设计；不得和 P6 显式 bounded sensor 同时作为 active 入口。

P6 初始资产：

| 资产 | 显式补洞目标 |
| --- | --- |
| `gold_market_breadth_daily` | 最近 60 个 `cn_a_stock_trade_days`，上游 `silver_stock_daily` ready 后补 first missing / first not-ready。 |
| `gold_stock_return_distribution` | 同上。 |
| `ch_share_fact_market_breadth_daily` | 上游两个 gold 派生资产 ready 后补 first missing / first not-ready。 |
| `prod_ch_share_fact_market_breadth_daily` | 上游本机 ClickHouse serving asset ready 后补 first missing / first not-ready。 |

## 8. 推进阶段

### F1：基础能力设计与测试

目标：

1. 完成本文档评审。
2. 设计 `ContinuityDateReadiness` / `ContinuityBatchReadiness` 等基础数据结构。
3. 提供通用 selector 的纯函数单测。
4. 不接入任何正式 sensor。

### F2：第一个非分钟线 sensor 接入

目标：

1. 选择一个已通过性能准入的资产族做首个接入。
2. 验证 cursor、run request、skip reason、静态门禁。
3. 对账基础能力是否足够表达实际场景。

### F3：P6 显式 bounded sensor 设计

目标：

1. 基于基础能力写 P6 LLD。
2. 明确移除四个派生资产上的 `automation_condition`，并删除或退出对应 `AutomationConditionSensorDefinition`。
3. 确定四个派生资产是否共用一个 sensor，还是按资产族拆分。
4. 先做只读性能方案，再进入代码开发。

## 9. 验收标准

1. 基础 selector 单测覆盖 registered gap、all ready、first missing、materialized failed、upstream blocked。
2. 静态门禁禁止新接入 sensor 回流 latest-only 目标选择。
3. 静态门禁禁止在 60 日 selector 中调用单日 Dagster readiness wrapper。
4. cursor 输出稳定、小型、可观测。
5. 不新增持久化状态实体。
6. 文档明确区分历史连续资产、current snapshot 资产、latest propagation 资产。
