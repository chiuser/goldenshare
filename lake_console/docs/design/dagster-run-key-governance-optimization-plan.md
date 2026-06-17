# Dagster Run Key 治理技术专项优化方案

状态：M1-M8 已按本文核心口径落地并完成本地完整回归，legacy bridge 已退出。本文保留为 run key 治理长期方案与后续回归依据。

更新时间：2026-06-17

## 0. 实施状态

截至 2026-06-17，本文的核心治理口径已完成以下落地：

1. 已新增统一 run key / upstream batch id builder：`run_contracts/run_keys.py`。
2. 普通 asset update 与 repair attempt run key 已迁移到统一 builder，输出字符串保持不变。
3. qfq factor repair metadata/status 已写入并暴露 `producer_run_id` 与 `upstream_batch_id`。
4. 前复权分钟线 MACD/KDJ 修复正式链路已切换为 `consumer + upstream_batch_id`，run config 与 completion metadata 不再写入旧 `source_qfq_factor_repair_event_storage_ids` 字段。
5. 前复权分钟线 MACD/KDJ 修复 completion gate 已按 `source_upstream_batch_id` 判断完成。
6. M6 已按审批完成正式 Dagster run history 只读审计，确认无活跃旧格式修复 run，且新 upstream batch 均已有 `source_upstream_batch_id` completion checks。
7. M7 已删除 legacy bridge 读取逻辑和相关测试；生产代码不再依赖旧 `source_qfq_factor_repair_event_storage_ids` 字段。
8. M8 已完成本地完整 pytest 回归，并把 M7 后手工重放、`upstream_batch_id`、legacy bridge 退出和 qfq 普通 event reconciliation 撤销口径同步到长期规范与业务设计文档。

M7 只做 legacy bridge 退出和文档/静态门禁收口；M8 只做本地完整回归和文档对账。两轮均不改变资产写入语义、job selection、sensor 启用状态或正式 Dagster instance 状态。

## 1. 背景

当前 orchestrator 的 sensor 已经大量使用 `RunRequest.run_key` 做幂等去重。现有代码能工作，但 run key 生成逻辑分散在多个 sensor 文件中，且不同场景直接把日期、代码、修复批次、hash、Dagster event storage id 等细节拼进字符串。

这会带来三个长期问题：

1. run key 模板散落，新增 sensor 时容易继续手写字符串。
2. run key 名称会随着数据集和业务场景不断膨胀，形成大量不可审计的特例。
3. 下游触发场景容易泄漏上游内部实现细节，例如把 Dagster `event_storage_id` 暴露到下游 run key 中。

本专项不是新业务开发，不改变资产写入语义、job selection、sensor 启用状态或正式 Dagster instance 状态。目标是规范 run key 的生成和使用方式。

## 2. 已确认原则

1. `run_key` 只用于 Dagster sensor / schedule 提交 `RunRequest` 时的幂等去重。
2. 禁止解析 `run_key` 生成 `run_config`。
3. 执行参数只能来自显式 `run_config`、`partition_key`、上游 metadata/status，或正式定义的 `upstream_batch_id`。
4. run key 生成逻辑必须集中管理，不允许散落在各个 sensor 文件中手写字符串模板。
5. 集中管理不能演变成每个数据集一个专属函数，例如不应新增 `raw_stock_daily_update_run_key(...)` 这类函数爆炸。
6. run key 应收敛到少数稳定类型；具体数据集、日期、代码、阶段、attempt、upstream batch 等都是 identity，不是函数名或类型名。
7. 方案文档和代码说明禁止使用历史事项编号、计划编号或里程碑编号代替业务对象名，必须直接写清楚实际业务对象，例如“前复权分钟线 MACD/KDJ 修复”。
8. 上下游触发场景中，下游不应理解上游如何判断“新一轮结果”。上游必须提供 opaque 的 `upstream_batch_id`，下游只用它判断是否需要触发。
9. `event_storage_id` 是 Dagster event log storage 的内部记录号，不应作为下游 run key 的长期业务契约。

## 3. 治理前 run key 分类

治理前代码中的 run key 可归纳为三类，另需新增一类 batch id 生成能力。

| 分类 | 治理前例子 | 治理前问题 | 目标抽象 |
| --- | --- | --- | --- |
| 资产更新 | `raw_stock_daily_update:{trade_date}`、`silver_index_daily:{trade_date}`、`index_daily:{trade_date}:{index_code}` | 各 sensor 手写模板 | `build_asset_update_run_key(...)` |
| 有界修复尝试 | `raw_stock_daily_update:{trade_date}:missing_code_repair:{hash}:{attempt}`、`index_daily:{trade_date}:{index_code}:repair:{evaluation_date}:{attempt}` | repair 维度各自命名，attempt 口径散落 | `build_repair_attempt_run_key(...)` |
| 上游触发下游 | `gold_stk_mins_qfq_macd_kdj_repair:{target_trade_date}:{repair_required_codes_hash}:{qfq_event_identity}` | 暴露上游内部 hash 和 event storage ids，下游 key 过长 | `build_upstream_triggered_run_key(...)` |
| 上游批次 ID | 当前无统一能力，前复权分钟线 MACD/KDJ 修复用 event storage ids 拼 identity | 没有正式 opaque batch id | `build_batch_id(...)` |

## 4. 目标 API 形态

新增或调整 run contract 模块时，必须使用少数通用 builder，而不是数据集专属函数。

固定文件：

```text
lake_console/orchestrator/src/orchestrator/defs/run_contracts/run_keys.py
```

### 4.1 `build_asset_update_run_key(...)`

用途：某个明确输出单元只允许 sensor 自动提交一次。

固定入参：

```text
subject: str
unit_id: str
```

语义：

```text
subject = 稳定任务/资产更新身份
unit_id = 本次输出单元身份，例如 trade_date、trade_date:index_code、trade_date:stage
```

示例：

```text
build_asset_update_run_key(
    subject="raw_stock_daily_update",
    unit_id="2026-06-09",
)

build_asset_update_run_key(
    subject="index_daily_raw_update",
    unit_id="2026-06-02:000001.SH",
)
```

注意：`subject` 可以包含数据集或 job 语义，因为不同输出入口必须区分；但 builder 类型不能因数据集膨胀。

固定输出：

```text
{subject}:{unit_id}
```

### 4.2 `build_repair_attempt_run_key(...)`

用途：同一个 repair scope 允许在受控预算内多次自动提交。

固定入参：

```text
subject: str
repair_scope_id: str
attempt: int
attempt_scope: str | None
```

语义：

```text
subject = 稳定 repair 所属入口
repair_scope_id = 修复对象身份，例如 trade_date、trade_date:index_code、missing_codes_hash
attempt_scope = attempt 预算归属，例如 evaluation_date 或 stage；无预算归属时可为空
attempt = 第几次自动 repair，必须为正整数
```

示例：

```text
build_repair_attempt_run_key(
    subject="index_daily_raw_update",
    repair_scope_id="2026-06-02:000001.SH",
    attempt_scope="20260604",
    attempt=1,
)
```

硬口径：

1. `attempt` 必须来自正式 guard 或 planner，不得由 cursor 文本随意递增。
2. 同一 repair scope 的并发保护和上限判断必须在提交 `RunRequest` 前完成。
3. repair 具体执行参数必须写入 `run_config`，不得从 run key 反解析。
4. 固定输出为 `{subject}:{repair_scope_id}:{attempt_scope}:{attempt}`；当 `attempt_scope` 为空时省略该段，输出 `{subject}:{repair_scope_id}:{attempt}`。

### 4.3 `build_upstream_triggered_run_key(...)`

用途：下游因为上游产生新一轮结果而触发。

固定入参：

```text
consumer: str
upstream_batch_id: str
```

语义：

```text
consumer = 下游触发入口身份
upstream_batch_id = 上游给下游消费的 opaque 批次 ID
```

示例目标：

```text
build_upstream_triggered_run_key(
    consumer="gold_stk_mins_qfq_macd_kdj_repair",
    upstream_batch_id="qfq_factor_repair:2026-06-09:7f3a9c2d8b41",
)
```

固定输出：

```text
{consumer}:{upstream_batch_id}
```

硬口径：

1. 下游 run key 只使用 `consumer + upstream_batch_id`。
2. 下游不得把 `repair_required_codes_hash`、`event_storage_id`、上游 run config 结构等上游内部细节展开到 run key 中。
3. 下游执行所需的 `start_trade_date`、`stock_codes`、`freqs`、`reason` 等必须进入 `run_config`，上下游批次身份只传 `upstream_batch_id`。
4. 下游审计所需的上游业务摘要应保留在 metadata/status 中；Dagster `event_storage_id` 不得进入正式 run key、正式 run config 或正式 completion identity。

### 4.4 `build_batch_id(...)`

用途：上游生成给下游判断“新一轮结果”的 opaque ID。它不是 run key builder。

固定入参：

```text
producer: str
scope: str
payload: Mapping[str, object]
```

语义：

```text
producer = 上游结果生产者身份，例如 qfq_factor_repair
scope = 上游批次作用域，例如 trade_date
payload = 能代表本轮上游结果幂等语义的最小事实集合
```

输出形态：

```text
{producer}:{scope}:{digest}
```

示例：

```text
qfq_factor_repair:2026-06-09:7f3a9c2d8b41
```

digest 生成要求：

1. payload 必须先 canonicalize，例如稳定排序、稳定 JSON 序列化、禁止非确定性字段。
2. digest 只用于身份识别，不承载执行参数。
3. payload 必须包含上游 `run_id`。当同一上游 scope 和 affected codes 再次执行时，新的 `run_id` 必须生成新的 batch id。
4. payload 禁止使用 Dagster `event_storage_id` 作为正式身份字段。
5. 上游执行完成后，必须把生成好的 `upstream_batch_id` 写入上游正式 metadata；本专项中的 qfq factor repair 固定写入现有 check metadata，供下游 sensor 读取。

## 5. 前复权分钟线 MACD/KDJ 修复目标口径

当前 run key：

```text
gold_stk_mins_qfq_macd_kdj_repair:{target_trade_date}:{repair_required_codes_hash}:{qfq_event_identity}
```

目标 run key：

```text
gold_stk_mins_qfq_macd_kdj_repair:{upstream_batch_id}
```

示例：

```text
gold_stk_mins_qfq_macd_kdj_repair:qfq_factor_repair:2026-06-09:7f3a9c2d8b41
```

其中 `upstream_batch_id` 由 qfq factor repair 生成，并写入 qfq factor repair 现有的 factor repair check metadata。payload 必须覆盖：

```text
producer = qfq_factor_repair
scope = target_trade_date
payload:
  producer_run_id
  repair_required_codes_hash
```

说明：

1. 同一轮 qfq factor repair 重复被 sensor 看到时，`upstream_batch_id` 不变，下游不重复触发。
2. qfq factor repair 新跑一轮，即使 affected codes hash 不变，只要代表新批次的事实变化，`upstream_batch_id` 就变化，下游可以再次触发。
3. 下游 sensor 读取 qfq factor repair check metadata 中的业务字段和 `upstream_batch_id`，不再把 Dagster event storage ids 当成上游批次身份。
4. 前复权分钟线 MACD/KDJ 修复的 `run_config` 仍显式传入执行参数，包括 `start_trade_date`、`freqs`、`stock_codes`、`reason`、`repair_required_codes_hash`、`upstream_batch_id`。
5. 前复权分钟线 MACD/KDJ 修复 completion metadata 必须记录 `source_upstream_batch_id` 和实际执行结果，便于排查和后续 completion gate 判断。
6. 新链路不得继续写入 `source_qfq_factor_repair_event_storage_ids` 作为正式 completion identity；M7 后生产代码也不得继续读取旧字段防重复。
7. Dagster UI 人工提交只允许重放真实 qfq factor repair upstream batch，必须提供完整 config 并通过上游 metadata/status 一致性校验；禁止只传 `start_trade_date + stock_codes` 的无批次手工修复，也不得为散装参数生成临时 `upstream_batch_id`。

目标流程：

1. qfq factor repair 执行完成后，在 `GOLD_STK_MINS_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME` 对应的现有 check metadata 中写入 `upstream_batch_id`、`producer_run_id`、`repair_required_codes_hash`、修复起止日期、affected codes 摘要等业务结果。
2. 前复权分钟线 MACD/KDJ 修复 sensor 读取这份 metadata，判断是否需要触发下游修复。
3. sensor 在提交 `RunRequest` 前，先用 `upstream_batch_id` 检查下游 completion gate；如果已有 completion check 证明这轮上游批次已完成，直接返回 `SkipReason`。
4. 需要触发时，sensor 使用 `gold_stk_mins_qfq_macd_kdj_repair:{upstream_batch_id}` 作为 run key，并通过 run config 显式传入执行参数。
5. 前复权分钟线 MACD/KDJ 修复完成后，在自己的 completion metadata 中写入 `source_upstream_batch_id`，表示这次下游修复消费的是哪一轮上游批次。
6. 如果自动提交受阻，允许人工在 Dagster UI 重放同一真实上游批次；这只是提交方式不同，不改变业务来源，也不允许绕过上游 batch 契约。

## 6. 现有场景最终迁移口径

本节是当前正式 sensor run key 的全量迁移清单。除前复权分钟线 MACD/KDJ 修复切换为 `upstream_batch_id` 外，其它普通 asset update 与 repair attempt 必须保持现有输出字符串不变，只把字符串生成迁移到统一 builder。

| 当前 run key 模板 | 所属场景 | 目标 builder | 固定身份口径 | 切换口径 |
| --- | --- | --- | --- | --- |
| `raw_stock_basic_update:{trade_date}` | 股票基础 raw 日更 | `build_asset_update_run_key` | `subject=raw_stock_basic_update`，`unit_id=trade_date` | 保持字符串不变 |
| `silver_stock_basic_update:{trade_date}` | 股票基础 silver 日更 | `build_asset_update_run_key` | `subject=silver_stock_basic_update`，`unit_id=trade_date` | 保持字符串不变 |
| `raw_namechange_update:{trade_date}:{stage}` | 股票曾用名 raw 两阶段更新 | `build_asset_update_run_key` | `subject=raw_namechange_update`，`unit_id=trade_date:stage` | 保持字符串不变 |
| `silver_namechange_update:{trade_date}:{stage}` | 股票曾用名 silver 两阶段更新 | `build_asset_update_run_key` | `subject=silver_namechange_update`，`unit_id=trade_date:stage` | 保持字符串不变 |
| `stock_identity_map:{trade_date}` | 股票身份映射更新 | `build_asset_update_run_key` | `subject=stock_identity_map`，`unit_id=trade_date` | 保持字符串不变 |
| `raw_suspend_d_update:{trade_date}` | 停复牌 raw 日更 | `build_asset_update_run_key` | `subject=raw_suspend_d_update`，`unit_id=trade_date` | 保持字符串不变 |
| `silver_suspend_d_update:{trade_date}` | 停复牌 silver 日更 | `build_asset_update_run_key` | `subject=silver_suspend_d_update`，`unit_id=trade_date` | 保持字符串不变 |
| `raw_stock_daily_update:{trade_date}` | 股票日线 raw 日更 | `build_asset_update_run_key` | `subject=raw_stock_daily_update`，`unit_id=trade_date` | 保持字符串不变 |
| `raw_stock_daily_update:{trade_date}:missing_code_repair:{missing_codes_hash}:{repair_attempt}` | 股票日线 raw 缺失代码修复 | `build_repair_attempt_run_key` | `subject=raw_stock_daily_update`，`repair_scope_id=trade_date:missing_code_repair:missing_codes_hash`，`attempt_scope=None`，`attempt=repair_attempt` | 保持字符串不变 |
| `silver_stock_daily_update:{trade_date}` | 股票日线 silver 日更 | `build_asset_update_run_key` | `subject=silver_stock_daily_update`，`unit_id=trade_date` | 保持字符串不变 |
| `raw_adj_factor_update:{trade_date}` | 复权因子 raw 日更 | `build_asset_update_run_key` | `subject=raw_adj_factor_update`，`unit_id=trade_date` | 保持字符串不变 |
| `silver_adj_factor_update:{trade_date}` | 复权因子 silver 日更 | `build_asset_update_run_key` | `subject=silver_adj_factor_update`，`unit_id=trade_date` | 保持字符串不变 |
| `stock_mins_raw_update_from_prod:{trade_date}` | 股票分钟线 raw 从 prod 导出 | `build_asset_update_run_key` | `subject=stock_mins_raw_update_from_prod`，`unit_id=trade_date` | 保持字符串不变 |
| `stock_mins_silver_update:{trade_date}` | 股票分钟线 silver 日更 | `build_asset_update_run_key` | `subject=stock_mins_silver_update`，`unit_id=trade_date` | 保持字符串不变 |
| `stock_mins_qfq_daily_update:{trade_date}` | 股票分钟线前复权日常更新 | `build_asset_update_run_key` | `subject=stock_mins_qfq_daily_update`，`unit_id=trade_date` | 保持字符串不变 |
| `stock_mins_qfq_factor_repair:{trade_date}` | 股票分钟线前复权因子修复 | `build_asset_update_run_key` | `subject=stock_mins_qfq_factor_repair`，`unit_id=trade_date` | 保持字符串不变 |
| `gold_stk_mins_qfq_macd_kdj_daily_update:{trade_date}` | 前复权分钟线 MACD/KDJ 日常更新 | `build_asset_update_run_key` | `subject=gold_stk_mins_qfq_macd_kdj_daily_update`，`unit_id=trade_date` | 保持字符串不变；上游 run-status 只是唤醒 sensor 与 readiness gate，不按上游批次重复触发 |
| `gold_stk_mins_qfq_macd_kdj_repair:{target_trade_date}:{repair_required_codes_hash}:{qfq_event_identity}` | 前复权分钟线 MACD/KDJ 修复 | `build_upstream_triggered_run_key` + `build_batch_id` | `consumer=gold_stk_mins_qfq_macd_kdj_repair`，`upstream_batch_id=qfq_factor_repair:target_trade_date:digest` | 改为 `gold_stk_mins_qfq_macd_kdj_repair:{upstream_batch_id}`；M4 迁移期曾走 completion gate 与 legacy bridge 防重复，M7 后只保留 `source_upstream_batch_id` completion gate |
| `index_daily:{trade_date}:{index_code}` | 指数日线 raw by code 更新 | `build_asset_update_run_key` | `subject=index_daily`，`unit_id=trade_date:index_code` | 保持字符串不变 |
| `index_daily:{trade_date}:{index_code}:repair:{evaluation_date}:{repair_attempt}` | 指数日线 raw late-arrival 修复 | `build_repair_attempt_run_key` | `subject=index_daily`，`repair_scope_id=trade_date:index_code:repair`，`attempt_scope=evaluation_date`，`attempt=repair_attempt` | 保持字符串不变 |
| `silver_index_daily:{trade_date}` | 指数日线 silver 日更 | `build_asset_update_run_key` | `subject=silver_index_daily`，`unit_id=trade_date` | 保持字符串不变 |
| `market_major_indices_daily:{trade_date}` | 主要指数日线更新 | `build_asset_update_run_key` | `subject=market_major_indices_daily`，`unit_id=trade_date` | 保持字符串不变 |

## 7. 迁移步骤与当前状态

截至 M8，7.1 至 7.4 均已完成代码落地；legacy bridge 已删除；业务设计文档中的旧字段、旧 run key 与散装手工 repair 口径已完成对账。

### 7.1 步骤一：集中 builder 与静态门禁

状态：已完成。

1. 新增 `run_contracts/run_keys.py`。
2. 定义并测试四个通用能力：
   - `build_asset_update_run_key(...)`
   - `build_repair_attempt_run_key(...)`
   - `build_upstream_triggered_run_key(...)`
   - `build_batch_id(...)`
3. 增加静态门禁：正式 sensor 文件中禁止直接写 `run_key=f"...` 或直接拼 `RunRequest(run_key=(...))`。
4. 允许 `RunRequest` 继续通过 `build_run_request(...)` 创建，但传入的 run key 必须来自统一 builder。

### 7.2 步骤二：迁移普通 asset update 与 repair attempt

状态：已完成。

1. 将简单日常更新 run key 迁移到 `build_asset_update_run_key(...)`。
2. 将指数 late-arrival repair、股票日线 missing code repair 迁移到 `build_repair_attempt_run_key(...)`。
3. 保持输出字符串可兼容现有幂等语义，除非方案明确要求换 key。
4. 对所有迁移补充单元测试，确保同输入同 key、不同幂等身份不同 key。

### 7.3 步骤三：引入 upstream batch

状态：已完成。正式 Dagster run history 只读审计已在前复权分钟线 MACD/KDJ 修复正式切换前按审批执行，审计结论为无待执行或运行中的旧格式修复 run。

1. 为 qfq factor repair 生成正式 `upstream_batch_id`。
2. qfq factor repair 必须在 `GOLD_STK_MINS_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME` 对应的现有 check metadata 写入 `upstream_batch_id` 和生成该 id 所依据的业务摘要字段，至少包括 `producer_run_id`、`repair_required_codes_hash`、`repair_start_trade_date`、`repair_end_trade_date`、`repair_required_code_count`、`repair_required_codes`、`repair_required_codes_truncated`。
3. 前复权分钟线 MACD/KDJ 修复 sensor 必须从 qfq factor repair check metadata 读取 `upstream_batch_id` 和业务结果，不得把 event storage ids 当成上游批次身份。
4. 正式切换前，必须按正式 Dagster 环境执行门禁单独审批，只读审计 Dagster run history，确认不存在待执行或运行中的旧 run key 格式前复权分钟线 MACD/KDJ 修复 run。
5. 将前复权分钟线 MACD/KDJ 修复 run key 改为 `consumer + upstream_batch_id`。
6. 将前复权分钟线 MACD/KDJ 修复 run config 增加显式 `upstream_batch_id`，并停止在新正式 run config 中传递 `source_qfq_factor_repair_event_storage_ids`。
7. 前复权分钟线 MACD/KDJ 修复 completion metadata 必须写入 `source_upstream_batch_id`。
8. 更新前复权分钟线 MACD/KDJ 修复 op 的一致性校验，不再以 event storage ids 作为下游 run key、正式 run config 字段或 completion identity。
9. 在前复权分钟线 MACD/KDJ 修复 sensor 提交新 run key 前，先检查 completion gate 是否已经覆盖同一 `upstream_batch_id`；已覆盖时必须 skip，不得依赖新 run key 去重。
10. M7 之前迁移期曾保留 legacy completion gate，防止新 run key 切换造成同一业务动作重新执行；M6 审计确认退出条件满足后，M7 已删除该旧读取路径。
11. `dagster-stk-mins-qfq-macd-kdj-indicators-plan.md` 中的旧 repair run key、event storage ids completion identity、散装手工 repair 与普通 qfq event reconciliation 历史口径已在 M8 对账修正。

### 7.4 legacy bridge 退出机制

状态：已完成。legacy bridge 只用于迁移期防止旧 completion metadata 因 run key 切换被重复执行，不是长期兼容层。

退出条件与完成结果：

1. 新链路已经稳定写入 `source_upstream_batch_id`，且前复权分钟线 MACD/KDJ 修复 sensor 的 completion gate 已能通过 `upstream_batch_id` 判断已完成批次；M6 审计已确认。
2. 经正式 Dagster 环境只读审计确认，不存在待执行或运行中的旧 run key 格式修复 run；M6 审计已确认。
3. 对可能被 sensor 再次评估的历史修复范围，已确认不存在只靠旧 event storage ids 才能识别的未迁移完成状态；M6 审计已确认新 upstream batch 均有 `source_upstream_batch_id` completion checks。
4. 静态门禁确认正式 sensor、op 和 completion metadata 写入路径不再新增 `source_qfq_factor_repair_event_storage_ids`；M7 已升级为生产代码彻底禁止旧字段。
5. M7 已删除 legacy bridge 读取逻辑和相关测试，只保留 `upstream_batch_id` / `source_upstream_batch_id` 口径。

## 8. 测试与验收

必须新增或调整以下测试：

1. run key builder 单元测试：
   - 同输入生成同一 key。
   - 不同 `unit_id`、`attempt`、`attempt_scope`、`upstream_batch_id` 生成不同 key。
   - 非法 `attempt <= 0` 直接报错。
   - payload 字段顺序不同但语义相同时，`build_batch_id(...)` 结果一致。
   - 第 6 节全量清单中的每一条现有 run key 模板都必须有 builder 测试覆盖；除前复权分钟线 MACD/KDJ 修复外，生成结果必须与旧字符串完全一致。
2. 静态门禁测试：
   - 正式 sensor 禁止手写 run key 字符串模板。
   - 正式 sensor 禁止解析 run key 生成 run config。
   - 下游 upstream-triggered run key 禁止包含 `event_storage_id`。
   - 生产代码彻底禁止出现 `source_qfq_factor_repair_event_storage_ids` 和 legacy bridge symbols。
   - 静态门禁必须排除测试文件、历史设计文档和 Dagster 官方示例，避免误伤非正式运行代码。
3. qfq factor repair metadata 测试：
   - `GOLD_STK_MINS_QFQ_FACTOR_REPAIR_PLAN_CHECK_NAME` 对应 check metadata 必须写入 `upstream_batch_id`。
   - check metadata 必须写入 `producer_run_id`、`repair_required_codes_hash`、修复起止日期、`repair_required_code_count`、`repair_required_codes`、`repair_required_codes_truncated`。
   - `upstream_batch_id` digest payload 必须包含 `producer_run_id`，不得包含 Dagster `event_storage_id`。
4. 前复权分钟线 MACD/KDJ 修复 sensor 测试：
   - 同一个 `upstream_batch_id` 重复 tick 只生成同一 run key。
   - 新的 `upstream_batch_id` 即使 `repair_required_codes_hash` 相同，也生成新的下游 run key。
   - run config 显式包含执行参数和 `upstream_batch_id`。
   - sensor 从 qfq factor repair check metadata 读取 `upstream_batch_id` 和业务结果，不从 event storage ids 推导批次身份。
   - 已存在 `source_upstream_batch_id` completion metadata 时，sensor 返回 `SkipReason`，不提交 `RunRequest`。
   - 新 completion gate 未命中时，sensor 直接提交 `RunRequest`，不再回退读取旧 completion metadata。
   - 新 completion metadata 只写 `source_upstream_batch_id`，不再写 `source_qfq_factor_repair_event_storage_ids` 作为正式身份字段。
5. 现有 sensor 回归：
   - 普通 asset update 的 run key 幂等语义不变。
   - repair attempt 的 attempt 上限和 backoff 语义不变。
6. 正式切换前审计验收：
   - run key 切换前必须完成经审批的 Dagster run history 只读审计。
   - 审计结果必须明确旧格式前复权分钟线 MACD/KDJ 修复 run 是否存在待执行或运行中记录。
   - 审计未完成或发现旧格式待执行/运行 run 时，不得切换正式 sensor emit 逻辑。
7. legacy bridge 退出测试：
   - legacy bridge 删除后，正式 completion gate 仍能仅凭 `source_upstream_batch_id` 识别已完成批次。
   - 静态门禁能阻止正式路径重新写入或依赖 `source_qfq_factor_repair_event_storage_ids`。
8. M8 本地完整回归：
   - 执行 `PYTHONPATH=src uv run --project . --with pytest python -m pytest tests`。
   - 结果为 `617 passed`。
   - 未执行 `dg`，未读取或写入正式 Dagster instance。

## 9. 不做范围

本专项不做：

1. 不启停任何 sensor。
2. 不执行 Dagster job、backfill、materialization、asset check 或 automation evaluation。
3. 不读取或修改正式 Dagster instance 状态。
4. 不改变资产数据写入、路径、schema、catalog 或 checks 语义。
5. 不把 run key 变成执行参数通道。
6. 不新增数据库表、summary asset、readiness asset 或外部状态表。
7. 不为每个数据集创建专属 run key helper。

## 10. 文档同步影响

实现本专项时，至少需要同步以下文档口径。M5 已完成治理文档和长期编码规范收口；M8 已完成前复权分钟线 MACD/KDJ 业务设计文档与 qfq asset HTML 文档对账：

1. `lake_console/orchestrator/AGENTS.md`：保留并扩展 run key 禁止解析规则。
2. `lake_console/orchestrator/CODING_STANDARDS.md`：追加 run key 命名与集中 builder 规范。
3. `lake_console/docs/design/dagster-stk-mins-qfq-macd-kdj-indicators-plan.md`：M8 已同步为真实 qfq factor repair upstream batch、完整 config 人工重放、`source_upstream_batch_id` completion identity 和散装手工 repair 禁止口径。
4. `lake_console/docs/design/dagster-basic-facts-two-stage-refresh-plan.md`：同步 stage/attempt run key 的通用 builder 口径。
5. `lake_console/docs/design/dagster-namechange-asset-design.md`、`dagster-stock-identity-map-design.md`：完成 run key 引用审计；存在 run key 示例时必须同步改为统一 builder 表述。
6. `lake_console/docs/design/dagster-stk-mins-asset-design.html`：M8 已同步 qfq factor repair 只写 repair check 作为历史改写账本，普通 qfq event/check reconciliation 独立入口已撤销、不保留。

## 11. 风险与执行门禁

1. `upstream_batch_id` 的 payload 已确认使用上游 `run_id`，不引入额外 batch sequence。
2. 前复权分钟线 MACD/KDJ 修复新 completion metadata 已确认写入 `source_upstream_batch_id`；不再把 event storage ids 作为正式 completion identity。
3. 前复权分钟线 MACD/KDJ 修复的人工提交只允许重放真实 qfq factor repair upstream batch；如果未来需要运营主动发起非 qfq factor repair 来源的修复，必须另行设计正式 manual repair batch producer。
4. 旧 run key 与新 run key 切换后，同一业务动作可能被 Dagster 视为新请求；M4 迁移期已通过 sensor 提交前 completion gate 和旧 completion 只读保护规避，M7 后只保留正式 `source_upstream_batch_id` completion gate。
5. 静态门禁需要避免误伤测试文件和 Dagster 官方示例文档；该点已确认。
6. 如果已有待执行或运行中的 run 使用旧 run key，正式切换前必须只读审计 Dagster run history；审计需按正式 Dagster 环境执行门禁单独审批。
7. legacy bridge 已按 7.4 退出并删除；不得恢复旧 event storage ids 读取逻辑作为正式路径。

## 12. 初始硬口径清单

后续按本文开发时，至少必须逐条对账：

1. 必须集中定义 run key builder。
2. 必须禁止 sensor 文件手写 run key 模板。
3. 必须禁止解析 run key 生成 run config。
4. 必须保留普通 asset update、repair attempt、upstream-triggered 三类清晰边界。
5. 必须将 `upstream_batch_id` 作为上下游触发的唯一 opaque 批次身份。
6. 必须让下游 run key 不再暴露 Dagster `event_storage_id`。
7. 必须保留执行参数在 `run_config` 中显式传递。
8. 必须为正向与反向口径补测试或静态门禁。
9. 必须让上游正式 metadata 产出 `upstream_batch_id`，下游 completion metadata 记录 `source_upstream_batch_id`。
10. 必须在 sensor 提交 `RunRequest` 前执行 completion gate；已完成批次必须 skip。
11. legacy bridge 已删除；后续不得恢复旧 completion metadata 读取防重复逻辑。
12. 必须用第 6 节全量清单逐项迁移所有现有 run key；不得只迁移示例或局部 sensor。
13. 正式切换前必须完成经审批的 Dagster run history 只读审计。
