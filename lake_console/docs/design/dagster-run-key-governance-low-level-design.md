# Dagster Run Key 治理 Low Level 编码设计

状态：M1-M9 已完成实现、本地完整回归与最终专项验收。legacy bridge 已退出，本文保留为实现对账和回归测试参考。

更新时间：2026-06-17

上层方案：`lake_console/docs/design/dagster-run-key-governance-optimization-plan.md`

## 1. 本文目标

本文用于记录 Dagster run key 治理专项的编码落点、已实现口径和后续收口门禁。M1-M9 已按本文完成核心实现、文档对账、本地完整回归和最终专项验收，后续维护 run key、upstream batch 或 completion gate 时仍必须按本文逐项对账。

M6 已按审批完成正式 Dagster run history 只读审计；M7 已删除 legacy bridge；M8 已完成业务文档对账和本地完整 pytest 回归；M9 已完成最终专项验收。M7/M8/M9 均未执行 Dagster job、sensor、backfill、materialization、asset check，也未读取或修改正式 Dagster instance 状态。

## 1.1 M1-M9 实施对账

| Milestone | 实际业务内容 | 当前状态 |
| --- | --- | --- |
| M1 | 新增集中 run key / upstream batch id builder 与 builder 测试。 | 已完成。 |
| M2 | 普通 asset update / repair attempt run key 迁移到统一 builder，输出字符串保持不变；静态门禁第一阶段落地。 | 已完成。 |
| M3 | qfq factor repair metadata/status 写入并读取 `producer_run_id` 与 `upstream_batch_id`。 | 已完成。 |
| M4 | 前复权分钟线 MACD/KDJ 修复 sensor、op、completion gate 从 event storage id 身份切到 `upstream_batch_id`；legacy bridge 只读旧 completion metadata 防重复提交。 | 已完成。 |
| M5 | 文档状态、长期编码规范和静态门禁命名收口。 | 已完成。 |
| M6 | 正式 Dagster run history 只读审计，确认无活跃旧格式前复权分钟线 MACD/KDJ 修复 run，且新批次 completion 已写 `source_upstream_batch_id`。 | 已完成。 |
| M7 | 删除前复权分钟线 MACD/KDJ 修复 legacy bridge，生产代码彻底清零旧 completion identity 字段依赖。 | 已完成。 |
| M8 | 本地完整 pytest 回归；把 M7 后 `upstream_batch_id`、legacy bridge 退出和手工重放口径同步到业务设计文档与长期编码规范。 | 已完成。 |
| M9 | 最终专项验收：确认正式 run key 全部经统一 builder、无手写 run key、无直接 `RunRequest`、无 run key 反解析、无旧 storage id 正式路径回流。 | 已完成。 |

M7 之后的正式口径是：前复权分钟线 MACD/KDJ 修复的业务来源只能是真实 qfq factor repair upstream batch；Dagster UI 只允许人工重放真实 upstream batch 的完整 config；散装 `start_trade_date + stock_codes` 手工修复不支持；completion gate 只使用 `source_upstream_batch_id` 判断已完成批次。

## 1.2 M9 最终验收结论

M9 最终验收的五条硬口径均已通过：

1. 没有散落手写正式 run key。
2. 没有新增直接 `dg.RunRequest(...)` / `RunRequest(...)`。
3. 没有解析 `run_key` 反推 `run_config`。
4. 没有正式路径写旧 storage id 字段。
5. 所有正式 run key 都经统一 builder。

验收依据：

1. `tests/test_run_contract_static_gates.py` 已覆盖正式 sensor 不得直接构造 `RunRequest`、不得手写 run key、不得写 run tags、生产代码不得出现旧 storage id 字段和 legacy bridge symbol。
2. `tests/test_run_contract_run_keys.py` 已覆盖普通 asset update、repair attempt、upstream-triggered run key 和 `build_batch_id(...)` 的输出与拒绝规则。
3. M9 静态审计确认 `lake_console/orchestrator/src` 中旧 storage id 字段和 legacy bridge symbol 零命中。
4. M9 静态审计确认正式 sensor 中直接 `RunRequest`、手写 run key 模板零命中。
5. M9 静态审计确认生产代码中未发现 `run_key` 解析反推 config 的可疑命中。
6. M9 静态审计确认旧 qfq ordinary event reconciliation active Python definitions 不存在。
7. M9 目标测试结果为 `83 passed`；完整本地回归结果为 `617 passed`。

## 2. 已读取规则与约束

编码前规则来源：

1. 仓库根 `AGENTS.md`
2. `lake_console/orchestrator/AGENTS.md`
3. `lake_console/orchestrator/CODING_STANDARDS.md`
4. `lake_console/docs/design/dagster-run-key-governance-optimization-plan.md`

必须遵守的硬约束：

1. `run_key` 只做 Dagster `RunRequest` 幂等去重身份，不承载执行参数。
2. 禁止解析 `run_key` 生成 `run_config`。
3. 执行参数只能来自显式 `run_config`、`partition_key`、上游 metadata/status，或正式 `upstream_batch_id`。
4. run key 生成必须集中到统一 builder 文件，不允许正式 sensor 继续手写字符串模板。
5. 不允许为每个数据集新增专属 run key 函数。
6. 上下游触发场景必须用 `upstream_batch_id` 屏蔽上游内部语义。
7. 新正式链路不得把 Dagster `event_storage_id` 写入 run key、run config 或 completion identity。
8. 普通资产更新和有界修复尝试必须保持现有 run key 字符串输出不变。
9. 前复权分钟线 MACD/KDJ 修复切换新 run key 前，曾通过 completion gate 和 legacy bridge 防止重复提交；M7 后正式链路只保留 `source_upstream_batch_id` completion gate。
10. 正式 Dagster run history 审计属于正式环境操作，必须单独审批后才能执行。
11. 前复权分钟线 MACD/KDJ 修复的正式业务来源只能是真实 qfq factor repair upstream batch；Dagster UI 人工提交只允许重放这个真实上游批次，不允许只给 `start_trade_date + stock_codes` 的无批次手工修复。

## 3. 代码审计范围

本次审计使用 CodeGraph 和源码文本搜索完成，未触发 Dagster 运行时。

CodeGraph 重点覆盖：

1. `build_run_request`
2. `gold_stk_mins_qfq_macd_kdj_repair_job_sensor`
3. `GoldStkMinsQfqMacdKdjRepairRunStatusDecision`
4. `gold_stk_mins_qfq_macd_kdj_repair_op`
5. `GOLD_STK_MINS_QFQ_MACD_KDJ_REPAIR_CONFIG_SCHEMA`
6. `build_gold_stk_mins_qfq_factor_repair_check_metadata`
7. `GoldStkMinsQfqFactorRepairStatus`
8. `gold_stk_mins_qfq_factor_repair_status`
9. `MacdKdjRepairCompletionGateStatus`
10. `gold_stk_mins_qfq_macd_kdj_repair_completion_status`

文本搜索重点覆盖：

1. `run_key=`
2. `RunRequest`
3. `source_qfq_factor_repair_event_storage_ids`
4. `qfq_factor_repair_event_storage_ids`
5. `repair_required_codes_hash`
6. `upstream_batch_id`

## 4. 治理前审计事实与编码影响

本节保留 M1 实现前的代码审计事实，用于解释为什么需要后续改造；M1-M4 已按“编码影响”列完成核心实现。

| 位置 | 治理前事实 | 编码影响 |
| --- | --- | --- |
| `src/orchestrator/defs/run_contracts/requests.py` | `build_run_request(...)` 只是 `dg.RunRequest` 薄封装，不生成 run key。 | 保留该职责；新增 run key builder 不塞进 `requests.py`。 |
| `src/orchestrator/defs/sensors/**` | 多数 sensor 直接用 `run_key=f"...` 或 `dg.RunRequest(run_key=(...))` 手写模板。 | 全量迁移到统一 builder；除前复权分钟线 MACD/KDJ 修复外，输出字符串必须不变。 |
| `src/orchestrator/defs/sensors/index_daily_late_arrival_repair.py` | 已有 `base_index_daily_run_key(...)`、`repair_index_daily_run_key(...)` 两个局部 helper。 | 删除局部 helper，改用统一 `build_asset_update_run_key` / `build_repair_attempt_run_key`。 |
| `src/orchestrator/defs/sensors/stock_daily_sensor.py` | raw 日更和 missing-code repair run key 在 sensor 内拼接。 | 日更迁到 asset update builder；missing-code repair 迁到 repair attempt builder，字符串保持不变。 |
| `src/orchestrator/defs/sensors/gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor.py` | 日常更新 run key 是 `gold_stk_mins_qfq_macd_kdj_daily_update:{trade_date}`。 | 这是普通资产更新，不使用 `upstream_batch_id`；字符串保持不变。 |
| `src/orchestrator/defs/sensors/gold_stk_mins_qfq_macd_kdj_repair_job_sensor.py` | 治理前修复 run key 是 `gold_stk_mins_qfq_macd_kdj_repair:{target_trade_date}:{repair_required_codes_hash}:{qfq_event_identity}`，其中 `qfq_event_identity` 来自上游 check event storage ids。 | 改为 `build_upstream_triggered_run_key(consumer, upstream_batch_id)`；run config 显式传 `upstream_batch_id` 和执行参数。 |
| `src/orchestrator/defs/stk_mins_qfq.py` | `build_gold_stk_mins_qfq_factor_repair_check_metadata(...)` 已写入修复起止日期、代码列表、`repair_required_codes_hash` 等业务 metadata。 | 在这里新增 `producer_run_id`、`upstream_batch_id`，继续写入现有 check metadata，不新增状态资产。 |
| `src/orchestrator/defs/asset_guards/stk_mins_qfq_factor_repair.py` | 治理前 `GoldStkMinsQfqFactorRepairStatus` 暴露 `qfq_factor_repair_event_storage_ids`，并用 event storage id 参与状态结果。 | 新增 `upstream_batch_id`、`producer_run_id`；新链路不再把 event storage ids 当下游批次身份。 |
| `src/orchestrator/defs/ops/gold_stk_mins_qfq_macd_kdj_repair.py` | 治理前 repair op config schema 包含 `source_qfq_factor_repair_event_storage_ids`；当传 `qfq_factor_repair_trade_date` 时，会从上游 metadata 派生 event storage ids 并校验。 | 替换为 `upstream_batch_id` 一致性校验；completion metadata 改写 `source_upstream_batch_id`。 |
| `src/orchestrator/defs/asset_guards/stk_mins_qfq_macd_kdj.py` | 治理前 completion gate 要求 `source_qfq_factor_repair_event_storage_ids`，并用 completion event storage id 大于上游 max storage id 来判断“新”。 | 新正式 gate 改为匹配 `source_upstream_batch_id`；M7 后删除旧 storage id 读取逻辑。 |
| `tests/test_run_contract_static_gates.py` | 已有 run contract 静态门禁基础。 | 扩展门禁：禁止正式 sensor 手写 run key，禁止 run key 解析，禁止生产代码出现旧 storage id 字段和 legacy bridge symbol。 |

## 5. 新增 run key builder 模块

新增文件：

```text
lake_console/orchestrator/src/orchestrator/defs/run_contracts/run_keys.py
```

职责：

1. 集中生成正式 run key。
2. 集中生成 upstream batch id。
3. 做最小输入校验，防止空 segment、非法 attempt、非确定性 payload 或 storage id 泄漏进 batch id。

不做：

1. 不读取 Dagster instance。
2. 不读取 event log。
3. 不解析 run key。
4. 不生成 run config。
5. 不包含任何数据集专属函数名。

### 5.1 API

```python
from collections.abc import Mapping
from typing import Any

def build_asset_update_run_key(*, subject: str, unit_id: str) -> str:
    ...

def build_repair_attempt_run_key(
    *,
    subject: str,
    repair_scope_id: str,
    attempt: int,
    attempt_scope: str | None = None,
) -> str:
    ...

def build_upstream_triggered_run_key(
    *,
    consumer: str,
    upstream_batch_id: str,
) -> str:
    ...

def build_batch_id(
    *,
    producer: str,
    scope: str,
    payload: Mapping[str, Any],
    digest_length: int = 12,
) -> str:
    ...
```

### 5.2 输入校验

通用 segment 校验：

1. `subject`、`unit_id`、`repair_scope_id`、`consumer`、`producer`、`scope`、`upstream_batch_id` 必须是非空字符串。
2. 字符串只做 `strip()` 后判空，不自动改写大小写、不替换分隔符。
3. builder 不禁止 `:`，因为现有兼容字符串依赖复合 identity，例如 `trade_date:index_code`。

repair attempt 校验：

1. `attempt` 必须是 `int` 且不是 `bool`。
2. `attempt` 必须大于 0。
3. `attempt_scope` 为空或空白时省略该段。

batch id 校验：

1. `payload` 必须非空。
2. `payload` 必须包含 `producer_run_id`。
3. `payload` 的 key 必须是非空字符串。
4. `payload` 禁止出现 `event_storage_id`、`event_storage_ids`、`storage_id`、`storage_ids` 这类字段名。
5. `payload` 只允许 JSON 可稳定序列化的基础值：`str`、`int`、`float`、`bool`、`None`、list/tuple、dict。
6. digest 使用 canonical JSON：`sort_keys=True`、紧凑 separators。
7. digest 使用 `sha256`，默认截断 12 个 hex 字符。
8. `digest_length` 必须大于 0 且不超过 64。

### 5.3 输出格式

```text
build_asset_update_run_key:
{subject}:{unit_id}

build_repair_attempt_run_key with attempt_scope:
{subject}:{repair_scope_id}:{attempt_scope}:{attempt}

build_repair_attempt_run_key without attempt_scope:
{subject}:{repair_scope_id}:{attempt}

build_upstream_triggered_run_key:
{consumer}:{upstream_batch_id}

build_batch_id:
{producer}:{scope}:{digest}
```

## 6. 现有 run key 迁移表

除前复权分钟线 MACD/KDJ 修复外，下表输出必须与当前字符串完全一致。

| 现有模板 | 目标 builder 调用 |
| --- | --- |
| `raw_stock_basic_update:{trade_date}` | `build_asset_update_run_key(subject="raw_stock_basic_update", unit_id=trade_date)` |
| `silver_stock_basic_update:{trade_date}` | `build_asset_update_run_key(subject="silver_stock_basic_update", unit_id=trade_date)` |
| `raw_namechange_update:{trade_date}:{stage}` | `build_asset_update_run_key(subject="raw_namechange_update", unit_id=f"{trade_date}:{stage}")` |
| `silver_namechange_update:{trade_date}:{stage}` | `build_asset_update_run_key(subject="silver_namechange_update", unit_id=f"{trade_date}:{stage}")` |
| `stock_identity_map:{trade_date}` | `build_asset_update_run_key(subject="stock_identity_map", unit_id=trade_date)` |
| `raw_suspend_d_update:{trade_date}` | `build_asset_update_run_key(subject="raw_suspend_d_update", unit_id=trade_date)` |
| `silver_suspend_d_update:{trade_date}` | `build_asset_update_run_key(subject="silver_suspend_d_update", unit_id=trade_date)` |
| `raw_stock_daily_update:{trade_date}` | `build_asset_update_run_key(subject="raw_stock_daily_update", unit_id=trade_date)` |
| `raw_stock_daily_update:{trade_date}:missing_code_repair:{missing_codes_hash}:{repair_attempt}` | `build_repair_attempt_run_key(subject="raw_stock_daily_update", repair_scope_id=f"{trade_date}:missing_code_repair:{missing_codes_hash}", attempt=repair_attempt)` |
| `silver_stock_daily_update:{trade_date}` | `build_asset_update_run_key(subject="silver_stock_daily_update", unit_id=trade_date)` |
| `raw_adj_factor_update:{trade_date}` | `build_asset_update_run_key(subject="raw_adj_factor_update", unit_id=trade_date)` |
| `silver_adj_factor_update:{trade_date}` | `build_asset_update_run_key(subject="silver_adj_factor_update", unit_id=trade_date)` |
| `stock_mins_raw_update_from_prod:{trade_date}` | `build_asset_update_run_key(subject="stock_mins_raw_update_from_prod", unit_id=trade_date)` |
| `stock_mins_silver_update:{trade_date}` | `build_asset_update_run_key(subject="stock_mins_silver_update", unit_id=trade_date)` |
| `stock_mins_qfq_daily_update:{trade_date}` | `build_asset_update_run_key(subject="stock_mins_qfq_daily_update", unit_id=trade_date)` |
| `stock_mins_qfq_factor_repair:{trade_date}` | `build_asset_update_run_key(subject="stock_mins_qfq_factor_repair", unit_id=trade_date)` |
| `gold_stk_mins_qfq_macd_kdj_daily_update:{trade_date}` | `build_asset_update_run_key(subject="gold_stk_mins_qfq_macd_kdj_daily_update", unit_id=trade_date)` |
| `index_daily:{trade_date}:{index_code}` | `build_asset_update_run_key(subject="index_daily", unit_id=f"{trade_date}:{index_code}")` |
| `index_daily:{trade_date}:{index_code}:repair:{evaluation_date}:{repair_attempt}` | `build_repair_attempt_run_key(subject="index_daily", repair_scope_id=f"{trade_date}:{index_code}:repair", attempt_scope=evaluation_date, attempt=repair_attempt)` |
| `silver_index_daily:{trade_date}` | `build_asset_update_run_key(subject="silver_index_daily", unit_id=trade_date)` |
| `market_major_indices_daily:{trade_date}` | `build_asset_update_run_key(subject="market_major_indices_daily", unit_id=trade_date)` |

### 6.1 基础事实两阶段刷新增量口径

`lake_console/docs/design/dagster-basic-facts-two-stage-refresh-plan.md` 将基础事实日常自动化从“一天一个 asset update run key”调整为“同一 `trade_date/stage` 最多 3 次自动提交”。这类 run 不再适合 `build_asset_update_run_key(...)`，因为 asset update builder 表达的是同一输出单元只允许自动提交一次。

两阶段基础事实刷新必须使用 `build_repair_attempt_run_key(...)` 表达有界 attempt 语义。这里的 `repair` 是 run key builder 的通用类型名，表示“同一 scope 允许受控 attempt”，不表示业务 job 改名为 repair job。

固定调用口径：

```python
build_repair_attempt_run_key(
    subject=subject,
    repair_scope_id=f"{trade_date}:{stage}",
    attempt=attempt,
)
```

固定输出：

```text
{subject}:{trade_date}:{stage}:{attempt}
```

两阶段基础事实 subject 表：

| job | subject | 输出示例 |
| --- | --- | --- |
| `raw_stock_basic_update_job` | `raw_stock_basic_update` | `raw_stock_basic_update:2026-06-17:morning:1` |
| `silver_stock_basic_update_job` | `silver_stock_basic_update` | `silver_stock_basic_update:2026-06-17:morning:1` |
| `raw_suspend_d_update_job` | `raw_suspend_d_update` | `raw_suspend_d_update:2026-06-17:morning:1` |
| `silver_suspend_d_update_job` | `silver_suspend_d_update` | `silver_suspend_d_update:2026-06-17:morning:1` |
| `raw_namechange_update_job` | `raw_namechange_update` | `raw_namechange_update:2026-06-17:morning:1` |
| `silver_namechange_update_job` | `silver_namechange_update` | `silver_namechange_update:2026-06-17:morning:1` |
| `stock_identity_map_update_job` | `stock_identity_map` | `stock_identity_map:2026-06-17:morning:1` |
| `raw_adj_factor_update_job` | `raw_adj_factor_update` | `raw_adj_factor_update:2026-06-17:morning:1` |
| `silver_adj_factor_update_job` | `silver_adj_factor_update` | `silver_adj_factor_update:2026-06-17:morning:1` |

硬门禁：

1. 不新增 `basic_fact_run_key(...)`、`basic_fact_run_key_prefix(...)` 或任何数据集专属 run key helper。
2. 不使用 `attempt-1` 这类自定义字符串段；attempt 只能是 `build_repair_attempt_run_key(...)` 的数字末段。
3. active run guard 和提交次数统计必须先用统一 builder 构造 1..3 候选 run key，再按 `dagster/run_key` 精确匹配，不得用 prefix 或 `startswith(...)`。
4. `run_key` 不承载执行参数；`trade_date`、`stage`、`attempt` 只能从 stage target、guard 结果、`partition_key` 或显式 config 进入执行逻辑，不得从 run key 反解析。

前复权分钟线 MACD/KDJ 修复：

```python
upstream_batch_id = qfq_factor_repair_status.upstream_batch_id

run_key = build_upstream_triggered_run_key(
    consumer="gold_stk_mins_qfq_macd_kdj_repair",
    upstream_batch_id=upstream_batch_id,
)
```

目标输出：

```text
gold_stk_mins_qfq_macd_kdj_repair:{upstream_batch_id}
```

## 7. qfq factor repair metadata 改造

涉及文件：

```text
lake_console/orchestrator/src/orchestrator/defs/stk_mins_qfq.py
lake_console/orchestrator/src/orchestrator/defs/ops/stock_mins_qfq_factor_repair.py
lake_console/orchestrator/src/orchestrator/defs/asset_guards/stk_mins_qfq_factor_repair.py
```

### 7.1 metadata 生产

`stock_mins_qfq_factor_repair_op` 在调用 `build_gold_stk_mins_qfq_factor_repair_check_metadata(...)` 时，必须传入 `producer_run_id=context.run_id`。

`build_gold_stk_mins_qfq_factor_repair_check_metadata(...)` 增加入参：

```python
producer_run_id: str
```

该函数内部继续基于现有 `repair_required_codes` 生成 `repair_required_codes_hash`，然后构造：

```python
upstream_batch_id = build_batch_id(
    producer="qfq_factor_repair",
    scope=plan.trade_date,
    payload={
        "producer_run_id": producer_run_id,
        "repair_required_codes_hash": repair_required_codes_hash,
    },
)
```

必须写入现有 check metadata：

```text
producer_run_id
upstream_batch_id
repair_required_codes_hash
repair_start_trade_date
repair_end_trade_date
repair_required_code_count
repair_required_codes
repair_required_codes_truncated
```

不得写入 `event_storage_id` 作为 batch identity。

### 7.2 metadata 消费

`GoldStkMinsQfqFactorRepairStatus` 增加字段：

```python
upstream_batch_id: str | None = None
producer_run_id: str | None = None
```

`to_payload()` 增加：

```text
upstream_batch_id
producer_run_id
```

`_QFQ_FACTOR_REPAIR_REQUIRED_METADATA_KEYS` 增加：

```text
upstream_batch_id
producer_run_id
```

`_evaluate_qfq_factor_repair_records(...)` 必须读取并校验：

1. 所有 asset check 的 `upstream_batch_id` 一致。
2. 所有 asset check 的 `producer_run_id` 一致。
3. `repair_required_codes_hash`、代码列表、截断标记仍按现有逻辑一致。

现有 `qfq_factor_repair_event_storage_ids` 字段只能保留为 Dagster event log 观测字段，不得被 sensor run key、run config 或 completion identity 使用；M7 后也不得作为 legacy bridge 辅助字段继续读取。

## 8. 前复权分钟线 MACD/KDJ 修复 sensor 改造

涉及文件：

```text
lake_console/orchestrator/src/orchestrator/defs/sensors/gold_stk_mins_qfq_macd_kdj_repair_job_sensor.py
lake_console/orchestrator/src/orchestrator/defs/asset_guards/stk_mins_qfq_macd_kdj.py
```

### 8.0 业务来源与提交方边界

M4 的正式业务来源固定为 qfq factor repair 产生的真实 `upstream_batch_id`。日常自动触发由 repair sensor 提交 `RunRequest`。

允许 Dagster UI 人工重放自动路径，但这不是新的手工业务来源。人工重放必须提供与 qfq factor repair metadata/status 完全一致的完整 config：

```text
qfq_factor_repair_trade_date
start_trade_date
stock_codes
repair_required_codes_hash
upstream_batch_id
```

op 启动后必须重新读取 `qfq_factor_repair_trade_date` 对应的上游 metadata/status，并校验显式 config 与上游事实完全一致。

禁止无上游批次的散装手工修复：

```text
start_trade_date + stock_codes
```

不得为这种散装参数生成临时 `upstream_batch_id`，也不得写 completion identity。

如果未来确实需要运营主动发起非 qfq factor repair 来源的修复，必须另行设计正式 manual repair batch producer，由它先产出可审计的 upstream batch metadata；不得把 repair op 改回直接消费散装参数。

### 8.1 Decision 数据结构

`GoldStkMinsQfqMacdKdjRepairRunStatusDecision` 删除新正式路径对 `qfq_factor_repair_event_storage_ids` 的依赖，增加：

```python
upstream_batch_id: str | None = None
```

当 qfq factor repair status ready 且需要修复时，decision 必须携带：

```text
target_trade_date
selected_trade_date
stock_codes
repair_required_codes_hash
upstream_batch_id
```

如果 `upstream_batch_id` 缺失，decision 必须 skip，原因写清楚是上游 metadata 缺少正式 batch id。

### 8.2 run config

`_run_config_for_repair_decision(...)` 输出：

```python
{
    "ops": {
        "gold_stk_mins_qfq_macd_kdj_repair_op": {
            "config": {
                "start_trade_date": decision.selected_trade_date,
                "freqs": list(STK_MINS_QFQ_FREQS),
                "stock_codes": list(decision.stock_codes),
                "reason": f"qfq_factor_repair:{decision.target_trade_date}",
                "repair_required_codes_hash": decision.repair_required_codes_hash,
                "upstream_batch_id": decision.upstream_batch_id,
            }
        }
    }
}
```

新正式 run config 禁止继续写入：

```text
source_qfq_factor_repair_event_storage_ids
```

### 8.3 run request

`_run_request_for_repair_decision(...)` 必须改为：

```python
return build_run_request(
    run_key=build_upstream_triggered_run_key(
        consumer="gold_stk_mins_qfq_macd_kdj_repair",
        upstream_batch_id=decision.upstream_batch_id,
    ),
    run_config=_run_config_for_repair_decision(decision),
)
```

不得继续直接调用 `dg.RunRequest(...)`。

### 8.4 提交前 completion gate

`gold_stk_mins_qfq_macd_kdj_repair_job_sensor(...)` 在返回 `RunRequest` 前必须先检查新 completion gate：

1. 是否已有 `source_upstream_batch_id == decision.upstream_batch_id` 的完成 check。
2. 已完成时返回 `SkipReason`，不得提交新 run key。
3. 未完成时直接提交 `RunRequest`。

伪代码：

```python
completion_status = gold_stk_mins_qfq_macd_kdj_repair_completion_status_for_upstream_batch(
    context.instance,
    repair_start_trade_date=decision.selected_trade_date,
    repair_end_trade_date=qfq_factor_repair_status.repair_end_trade_date,
    upstream_batch_id=decision.upstream_batch_id,
    repair_required_code_count=qfq_factor_repair_status.repair_required_code_count,
    repair_required_codes_hash=decision.repair_required_codes_hash,
)
if completion_status.ready:
    return dg.SkipReason(completion_status.reason)

return _run_request_for_repair_decision(decision)
```

固定函数名：

```python
gold_stk_mins_qfq_macd_kdj_repair_completion_status_for_upstream_batch(...)
```

该函数是正式 completion gate；M7 已删除 legacy bridge，不再读取旧 completion metadata 防重复提交。

## 9. 前复权分钟线 MACD/KDJ 修复 op 改造

涉及文件：

```text
lake_console/orchestrator/src/orchestrator/defs/ops/gold_stk_mins_qfq_macd_kdj_repair.py
```

### 9.1 config schema

删除新正式路径字段：

```text
source_qfq_factor_repair_event_storage_ids
```

新增字段：

```python
"upstream_batch_id": dg.Field(
    str,
    is_required=False,
    default_value="",
    description="触发本次 MACD/KDJ repair 的上游 opaque batch id。",
)
```

`upstream_batch_id` 的生效规则：

1. sensor 自动触发路径必须显式传入 `qfq_factor_repair_trade_date` 和 `upstream_batch_id`。
2. Dagster UI 人工提交只允许重放自动路径，也必须显式传入 `qfq_factor_repair_trade_date` 和 `upstream_batch_id`。
3. op 必须从 `qfq_factor_repair_trade_date` 对应的上游 metadata/status 派生 `upstream_batch_id`，并与显式值校验一致。
4. 如果缺少 `qfq_factor_repair_trade_date` 或显式 `upstream_batch_id`，直接失败，错误原因必须写清 `manual repair is unsupported`。
5. 禁止仅凭 `start_trade_date + stock_codes` 执行 repair；这类散装手工路径不得写入 `source_upstream_batch_id` completion metadata。
6. 自动修复路径和人工重放路径都不得静默生成临时 batch id。

如果实现时发现确实需要运营主动发起非 qfq factor repair 来源的修复，必须停下并单独设计 manual repair batch producer；不得在本轮恢复“无上游批次”的 repair op 手工路径。

### 9.2 scope 派生

`_repair_scope_from_qfq_factor_repair_status(...)` 返回值从：

```python
tuple[str, tuple[str, ...], str, tuple[int, ...]]
```

调整为包含 `upstream_batch_id`：

```python
tuple[str, tuple[str, ...], str, str]
```

含义：

```text
repair_start_trade_date
repair_required_codes
repair_required_codes_hash
upstream_batch_id
```

函数必须校验：

1. status ready。
2. status rewrote history。
3. 自动修复允许。
4. `repair_start_trade_date` 非空。
5. `repair_required_codes_hash` 非空。
6. `upstream_batch_id` 非空。

### 9.3 显式 config 与上游 metadata 一致性校验

`_assert_explicit_scope_matches_qfq_metadata(...)` 删除 event storage ids 相关参数，增加：

```python
explicit_upstream_batch_id: str
derived_upstream_batch_id: str
```

必须继续校验：

1. 显式 `start_trade_date` 与上游 metadata 一致。
2. 显式 `stock_codes` 与上游 metadata 一致。
3. 显式 `repair_required_codes_hash` 与上游 metadata 一致。
4. 显式 `upstream_batch_id` 与上游 metadata 一致。

### 9.4 completion metadata

新 completion metadata 必须写：

```text
source_upstream_batch_id
covered_start_trade_date
covered_end_trade_date
freqs
qfq_factor_repair_trade_date
stock_code_scope
stock_code_count
repair_required_code_count
repair_required_codes_hash
reason
indicator_file_count
indicator_row_count
state_file_count
state_row_count
```

新正式路径禁止写：

```text
source_qfq_factor_repair_event_storage_ids
```

## 10. completion gate

涉及文件：

```text
lake_console/orchestrator/src/orchestrator/defs/asset_guards/stk_mins_qfq_macd_kdj.py
```

### 10.1 completion status

`MacdKdjRepairCompletionGateStatus` 保留正式 upstream identity 字段：

```python
source_upstream_batch_id: str | None = None
```

`to_payload()` 暴露：

```text
source_upstream_batch_id
```

新正式 completion required metadata：

```text
covered_start_trade_date
covered_end_trade_date
stock_code_scope
stock_code_count
repair_required_code_count
repair_required_codes_hash
source_upstream_batch_id
freqs
```

### 10.2 新 gate 判断

新 gate 只按 `source_upstream_batch_id` 判断 upstream identity，必须验证：

1. 每个 MACD/KDJ asset 的 completion check 都存在且 passed/blocking。
2. partition 等于 `repair_start_trade_date`。
3. metadata 包含新 required keys。
4. `source_upstream_batch_id == upstream_batch_id`。
5. `covered_start_trade_date <= repair_start_trade_date`。
6. `covered_end_trade_date >= repair_end_trade_date`。
7. `freqs` 覆盖全部 `STK_MINS_QFQ_FREQS`。
8. `repair_required_code_count` 与上游一致。
9. `repair_required_codes_hash` 与上游一致。
10. `stock_code_scope == "explicit"`。
11. `stock_code_count >= repair_required_code_count`。

新 gate 不再要求 completion event storage id 大于上游 event storage id。

### 10.3 legacy bridge 退出结果

legacy bridge 已在 M7 删除。删除前 M6 正式 Dagster 只读审计确认：

1. 不存在待执行或运行中的旧 run key 格式前复权分钟线 MACD/KDJ 修复 run。
2. 带 `upstream_batch_id` 的 qfq factor repair 批次均已有对应 `source_upstream_batch_id` completion checks。
3. 生产代码不再读取旧 completion metadata 字段：

```text
source_qfq_factor_repair_event_storage_ids
```

## 11. 静态门禁

涉及文件：

```text
lake_console/orchestrator/tests/test_run_contract_static_gates.py
```

新增或调整门禁：

1. 正式 sensor 文件禁止直接出现 `run_key=f"`、`run_key = f"`、`dg.RunRequest(run_key=...)` 这类手写 run key 构造。
2. 正式 sensor 必须通过 `build_run_request(...)` 提交 `RunRequest`，且传入 run key 必须来自 `run_contracts/run_keys.py` builder。
3. 禁止生产代码解析 `run_key` 来生成 `run_config`。
4. 禁止 upstream-triggered run key 中出现 `event_storage_id`、`event_storage_ids`、`storage_id`、`storage_ids`。
5. 生产代码禁止出现 `source_qfq_factor_repair_event_storage_ids`。
6. 生产代码禁止出现 legacy bridge 函数、legacy completion required metadata 常量或 legacy completion status 字段。
7. 静态门禁必须排除 tests、历史设计文档、Dagster 官方示例文档。
8. 基础事实两阶段 sensor 必须使用 `build_repair_attempt_run_key(...)`；禁止 `attempt-` 字符串段、基础事实专属 run key helper、run key prefix 匹配和 `startswith(...)` 匹配。

## 12. 测试计划

### 12.1 run key builder 测试

新增测试文件：

```text
lake_console/orchestrator/tests/test_run_contract_run_keys.py
```

覆盖：

1. 四个 builder 的正常输出。
2. 第 6 节迁移表所有兼容 run key 的精确字符串。
3. 前复权分钟线 MACD/KDJ 修复新 run key 输出。
4. 空 segment 报错。
5. `attempt <= 0` 报错。
6. payload key 顺序不同但 digest 一致。
7. payload 缺 `producer_run_id` 报错。
8. payload 含 storage id 字段报错。

### 12.2 普通 sensor 回归

更新现有 sensor 测试，确保：

1. 股票基础、曾用名、身份映射、停复牌、股票日线、复权因子、分钟线、指数日线、主要指数的 run key 字符串不变。
2. 股票日线 missing-code repair 的 run key 字符串不变。
3. 指数日线 late-arrival repair 的 run key 字符串不变。
4. repair attempt 上限、backoff、cursor 状态语义不变。

### 12.3 qfq factor repair metadata 测试

覆盖：

1. check metadata 写入 `producer_run_id`。
2. check metadata 写入 `upstream_batch_id`。
3. `upstream_batch_id` payload 包含 `producer_run_id` 和 `repair_required_codes_hash`。
4. 不同 `producer_run_id` 生成不同 `upstream_batch_id`。
5. 相同 payload 生成相同 `upstream_batch_id`。
6. status 能读取 `upstream_batch_id`。
7. 多个 asset check 的 `upstream_batch_id` 不一致时 status 不 ready。

### 12.4 前复权分钟线 MACD/KDJ 修复 sensor 测试

覆盖：

1. qfq factor repair status 缺 `upstream_batch_id` 时 skip。
2. qfq factor repair status ready 且需要修复时，run key 为 `gold_stk_mins_qfq_macd_kdj_repair:{upstream_batch_id}`。
3. run config 显式包含 `start_trade_date`、`freqs`、`stock_codes`、`repair_required_codes_hash`、`upstream_batch_id`。
4. run config 不包含 `source_qfq_factor_repair_event_storage_ids`。
5. 新 completion gate 已完成时 skip，不提交 `RunRequest`。
6. 新 completion gate 未完成时提交 `RunRequest`，不再回退检查旧 completion metadata。
7. 同一 `upstream_batch_id` 重复 tick 生成同一 run key。
8. 不同 `upstream_batch_id` 即使 `repair_required_codes_hash` 相同，也生成不同 run key。

现有前复权分钟线 MACD/KDJ 修复相关测试文件名包含历史编号。实施时不新增这种命名；凡 touched 的测试应优先改成业务语义命名，避免继续用编号代表业务对象。

### 12.5 repair op 与 completion gate 测试

覆盖：

1. 显式 `upstream_batch_id` 与上游 metadata 一致时通过。
2. 显式 `upstream_batch_id` 与上游 metadata 不一致时报错。
3. `qfq_factor_repair_trade_date` 派生路径能得到 `upstream_batch_id`。
4. Dagster UI 人工重放自动路径时，完整 config 与上游 metadata 一致则通过。
5. 缺少 `qfq_factor_repair_trade_date` 时报错，错误信息包含 `manual repair is unsupported`。
6. 缺少 `upstream_batch_id` 时报错，错误信息包含 `manual repair is unsupported`。
7. 仅传 `start_trade_date + stock_codes` 的散装手工路径报错，且不会写文件或 completion metadata。
8. 新 completion metadata 写 `source_upstream_batch_id`。
9. 新 completion metadata 不写 `source_qfq_factor_repair_event_storage_ids`。
10. 新 gate 仅凭 `source_upstream_batch_id` 判断已完成。
11. 新 gate 不依赖 completion event storage id 大小。

## 13. 实现顺序

M1-M9 已按以下顺序完成：

1. 新增 `run_contracts/run_keys.py` 与 `test_run_contract_run_keys.py`。
2. 迁移普通 asset update 和 repair attempt run key，保持字符串不变。
3. 扩展静态门禁，禁止正式 sensor 手写 run key。
4. 为 qfq factor repair metadata 写入 `producer_run_id` 和 `upstream_batch_id`。
5. 扩展 qfq factor repair status，读取并校验 `upstream_batch_id`。
6. 改造前复权分钟线 MACD/KDJ 修复 sensor，使用 `build_upstream_triggered_run_key` 和 completion gate。
7. 改造前复权分钟线 MACD/KDJ 修复 op config、scope 派生、一致性校验和 completion metadata。
8. 改造 completion gate，新增 `source_upstream_batch_id` 正式判断；M7 删除 legacy bridge 读取路径。
9. 更新相关测试与静态门禁。
10. 更新相关设计文档和编码规范。
11. 在正式切换前，单独申请正式 Dagster run history 只读审计。
12. 删除 legacy bridge 读取逻辑、旧字段 allowlist 和对应测试；静态门禁升级为生产代码彻底禁止旧字段。
13. 完成 M8 文档对账和本地完整 pytest 回归，确认生产代码旧字段/legacy symbol 仍为零命中。
14. 完成 M9 最终专项验收，逐条确认无手写正式 run key、无直接 `RunRequest`、无 run key 反解析、无旧 storage id 正式路径回流，且所有正式 run key 均经统一 builder。

第 11 项已在前复权分钟线 MACD/KDJ 修复正式切换前按审批完成一次只读审计。M6 删除 legacy bridge 前再次按审批完成正式 Dagster 只读审计，结论为无活跃旧格式修复 run，且新 upstream batch 均已有 `source_upstream_batch_id` completion checks。M7 已完成第 12 项。M8 已完成第 13 项，本地完整回归结果为 `617 passed`。M9 已完成第 14 项，不包含正式 Dagster runtime 只读审计。

## 14. 验证命令

开发实现后，优先跑纯本地单元测试和静态门禁，不触发正式 Dagster instance：

```bash
cd lake_console/orchestrator
uv run pytest tests/test_run_contract_run_keys.py
uv run pytest tests/test_run_contract_static_gates.py
uv run pytest tests/test_stock_daily_sensor.py
uv run pytest tests/test_index_daily_late_arrival_repair.py
uv run pytest tests -k "qfq and macd"
```

M8 收口时已执行完整本地回归：

```bash
cd lake_console/orchestrator
PYTHONPATH=src uv run --project . --with pytest python -m pytest tests
```

结果：`617 passed`。本次回归未执行 `dg`，未触碰正式 Dagster instance。

M9 最终验收时已执行目标测试：

```bash
cd lake_console/orchestrator
PYTHONPATH=src uv run --project . --with pytest python -m pytest \
  tests/test_run_contract_run_keys.py \
  tests/test_run_contract_static_gates.py \
  tests/test_stk_mins_qfq_factor_repair_contracts.py \
  tests/test_stk_mins_qfq_macd_kdj_repair_gate.py \
  tests/test_stk_mins_qfq_macd_kdj_repair_sensor_contracts.py \
  tests/test_stk_mins_qfq_macd_kdj_repair_op_contracts.py
```

结果：`83 passed`。

M9 最终验收时已再次执行完整本地回归：

```bash
cd lake_console/orchestrator
PYTHONPATH=src uv run --project . --with pytest python -m pytest tests
```

结果：`617 passed`。本次回归未执行 `dg`，未读取或触碰正式 Dagster instance。

正式 Dagster 环境相关命令不在普通验证中执行。凡涉及 `dg`、Dagster daemon/webserver、正式 `DAGSTER_HOME`、正式 run history、sensor tick 或 automation evaluation，必须按 `lake_console/orchestrator/AGENTS.md` 单独申请用户审批。

## 15. 停手机制

遇到以下情况必须停下来确认，不得自行补丁绕过：

1. 发现新的正式 run key 模板不在本文第 6 节清单中。
2. 发现生产代码存在解析 run key 得到执行参数的真实逻辑。
3. 发现 qfq factor repair op 无法可靠拿到 `context.run_id`。
4. 发现上游 check metadata 不能稳定写入或读取 `upstream_batch_id`。
5. 发现必须支持无上游 batch 的手工前复权分钟线 MACD/KDJ 修复；此时必须停下并单独设计 manual repair batch producer，不得在本轮恢复散装手工路径。
6. 发现生产链路仍需要读取旧 `source_qfq_factor_repair_event_storage_ids` 才能防重复。
7. 删除 legacy bridge 前的正式 run history 审计未获审批，或审计发现旧格式 run 正在排队/运行。

## 16. M1-M9 完成对账清单

M1-M9 已完成实现时必须逐项说明；后续维护按本清单确认现实代码和文档一致：

1. `run_contracts/run_keys.py` 是否集中承接所有正式 run key 生成。
2. 正式 sensor 是否已清零手写 run key 模板。
3. 普通 asset update 与 repair attempt 输出字符串是否保持不变。
4. 前复权分钟线 MACD/KDJ 修复 run key 是否已切到 `consumer + upstream_batch_id`。
5. qfq factor repair metadata 是否写入 `producer_run_id` 和 `upstream_batch_id`。
6. 前复权分钟线 MACD/KDJ 修复 run config 是否停止写入旧 storage id 字段。
7. completion metadata 是否写入 `source_upstream_batch_id`。
8. completion gate 是否能在提交 `RunRequest` 前按 `upstream_batch_id` skip。
9. legacy bridge 是否已删除，生产代码是否不再出现旧 completion identity 字段。
10. 静态门禁是否阻止生产代码重新引入旧口径。
11. 是否执行了本地测试。
12. 是否未触碰正式 Dagster instance。
13. 业务设计文档是否不再保留旧 storage id completion identity、旧 repair run key 或散装手工 repair 口径。
14. 是否确认没有散落手写正式 run key。
15. 是否确认没有新增直接 `dg.RunRequest(...)` / `RunRequest(...)`。
16. 是否确认没有解析 `run_key` 反推 `run_config`。
17. 是否确认没有正式路径写旧 storage id 字段。
18. 是否确认所有正式 run key 都经统一 builder。
