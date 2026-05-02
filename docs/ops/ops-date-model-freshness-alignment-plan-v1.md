# Ops 新鲜度按 Date Model 收口方案 v1

- 状态：已按干净方案落地到现行 freshness 主链
- 更新时间：2026-04-26
- 归属：`docs/ops`
- 关联基线：[数据集日期模型消费指南 v1](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)
- 代码现状参考：
  - [freshness_query_service.py](/Users/congming/github/goldenshare/src/ops/queries/freshness_query_service.py)
  - [operations_dataset_status_snapshot_service.py](/Users/congming/github/goldenshare/src/ops/services/operations_dataset_status_snapshot_service.py)
  - [dataset_definition_projection.py](/Users/congming/github/goldenshare/src/ops/dataset_definition_projection.py)
  - [dataset_observation_registry.py](/Users/congming/github/goldenshare/src/ops/dataset_observation_registry.py)
  - `date_models.py`（历史路径，已删除）

---

## 1. 一句话结论

Ops 数据新鲜度必须以 `DatasetDefinition.date_model` 为唯一事实源。

现行实现只允许从 `DatasetDefinition.date_model` 读取日期语义。旧 freshness metadata、旧同步状态表、旧合约日期模型不得再作为 freshness 判断依据。

历史触发问题之一是：周/月 bucket freshness 曾只按简单日期差判断，没有严格消费 `DatasetDefinition.date_model`。当前实现已进一步区分交易日 bucket 与自然日期 bucket：指数周/月线按最后一个开市交易日判断，股票周/月线按源接口要求的自然周五 / 自然月末判断。

本方案只收口日期型 bucket freshness 规则，不新增数据表，不新增状态字段，不设计主数据/快照类健康模型。`not_applicable` 主数据/快照类问题已登记为 P1 风险，后续单独评审。

---

## 2. 当前问题

### 2.1 当前代码如何判断新鲜度

现行主链路是：

```text
OpsFreshnessQueryService.build_live_items()
  -> 读取由 DatasetDefinition 派生的 DatasetFreshnessProjection
  -> 读取 DatasetDefinition.date_model 的 date_axis/bucket_rule/window_mode/observed_field
  -> 从目标表按同一个 bucket_rule 观测 actual bucket
  -> _expected_business_date_for_projection(reference_date, latest_open_date)
  -> lag_days = expected bucket - actual bucket
  -> _freshness_status_for_date_model(...)
```

已修正的旧问题：

1. `ops.specs.registry` 不再承载 freshness 静态事实，改为由 `DatasetDefinition` 派生 `DatasetFreshnessProjection`。
2. `freshness_query_service.py` 不再只做简单 `max(observed_field)`，周/月 bucket 会按交易日历压缩到应观测锚点。
3. `week_last_open_day`、`month_last_open_day`、`week_friday`、`month_last_calendar_day`、`month_window_has_data` 已进入 expected/actual 判断。
4. `cadence` 不再作为 freshness 事实源，只保留展示和分组语境。
5. 本方案没有新增表，也没有新增状态字段。

### 2.2 为什么这会误导页面

页面看到的是 `ops.dataset_status_snapshot` 和 `ops.dataset_layer_snapshot_current` 的派生结果。

如果 freshness 规则算错，页面不会知道“规则错了”，只会忠实展示错误结论，例如：

1. 周线缺少 `2026-04-24`，但仍显示新鲜。
2. 月线在月中被拿 `2026-04-24` 做 expected date，导致 `expected_business_date` 与 `lag_days` 字段本身就不符合“每月最后一个交易日”的语义。
3. `index_monthly` 这类数据如果目标表里出现非月末日期，当前 `max(trade_date)` 可能取到非 bucket 日期，实际应该按 `month_last_open_day` 过滤后再判断。

---

## 3. 目标规则

### 3.1 统一原则

1. `DatasetDefinition.date_model` 是日期语义唯一事实源。
2. Ops freshness 不再用 `cadence` 决定 expected date。
3. `cadence` 最多作为现有字段用于展示分组，并应在后续收口中评估删除，不允许作为 freshness 判断依据。
4. expected date / expected bucket 必须由 `date_axis + bucket_rule` 计算。
5. actual latest date 也必须按同一个 `bucket_rule` 过滤，不能简单 `max(observed_field)`。
6. `fresh` 的核心判断是：最新有效 bucket 已覆盖当前应完成的 expected bucket。
7. 本方案不得新增数据表或新增状态字段；只修正计算规则，并通过现有 `ops.dataset_status_snapshot`、`ops.dataset_layer_snapshot_current`、`ops.dataset_layer_snapshot_history` 投影重建消除旧结果。

### 3.2 Bucket Rule 到 freshness 的映射

| date_axis | bucket_rule | expected bucket 计算方式 | actual latest 观测方式 | Fresh 条件 |
|---|---|---|---|---|
| `trade_open_day` | `every_open_day` | 交易日历中当前日期前后已开市的最新交易日 | 目标表 `max(trade_date)` | actual >= expected |
| `trade_open_day` | `week_last_open_day` | 每周最后一个开市交易日，且该锚点日期已经到达 | 只统计每周最后开市交易日上的数据 | actual bucket >= expected bucket |
| `trade_open_day` | `month_last_open_day` | 每月最后一个开市交易日，且该锚点日期已经到达 | 只统计每月最后开市交易日上的数据 | actual bucket >= expected bucket |
| `month_key` | `every_natural_month` | 当前已到达的自然月份键 | 按 `YYYYMM` 月份键归一化 | actual month >= expected month |
| `month_window` | `month_window_has_data` | 当前已到达的自然月窗口 | 目标表在该月窗口内是否存在数据 | expected window 内有数据 |
| `natural_day` | `every_natural_day` | 当前自然日或业务定义的最新应覆盖自然日 | 目标表 `max(ann_date)` | actual >= expected |
| `natural_day` | `week_friday` | 当前已到达的自然周周五 | 只统计自然周五上的数据 | actual bucket >= expected bucket |
| `natural_day` | `month_last_calendar_day` | 当前已到达的自然月最后一天 | 只统计自然月最后一天上的数据 | actual bucket >= expected bucket |
| `none` | `not_applicable` | 不生成日期 freshness bucket | 不按业务日期判断 | 本方案不展开；已登记 P1 风险 |

### 3.3 以 2026-04-26 为例

当前已知交易日历中，`2026-04-24` 是 `2026-04-26` 之前最新开市日。

| 数据集类型 | 正确 expected bucket | 当前旧逻辑 expected date | 说明 |
|---|---:|---:|---|
| 日线 `every_open_day` | `2026-04-24` | `2026-04-24` | 旧逻辑碰巧正确 |
| 周线 `week_last_open_day` | `2026-04-24` | `2026-04-24` | expected date 对，但 `weekly <= 7 天 fresh` 阈值错误 |
| 月线 `month_last_open_day` | `2026-03-31` | `2026-04-24` | 旧逻辑错误，4 月月末交易日尚未到达 |
| 股票周线 `week_friday` | `2026-04-24` | `2026-04-24` | 源接口要求自然周五，不按交易日历压缩 |
| 股票月线 `month_last_calendar_day` | `2026-03-31` | `2026-04-24` | 4 月自然月末尚未到达 |
| 月份键 `every_natural_month` | `2026-04` | `2026-04-24` | 应按月比较，不应按日 lag |
| 月窗口 `month_window_has_data` | `2026-04` 窗口 | `2026-04-24` | 应判断窗口内是否有数据 |

---

## 4. 已识别影响面

### 4.1 明确会被修正的数据集

| 数据集 | date_model rule | 当前风险 | 修正后预期 |
|---|---|---|---|
| `index_weekly` | `week_last_open_day` | 最新停在上周最后交易日时仍可能 fresh | 缺少本周应完成周锚点时不能 fresh |
| `stk_period_bar_week` | `week_friday` | 源接口要求自然周五，不能用最后交易日判断 | 按自然周五判断 |
| `stk_period_bar_adj_week` | `week_friday` | 源接口要求自然周五，不能用最后交易日判断 | 按自然周五判断 |
| `index_monthly` | `month_last_open_day` | expected date 被算成最新开市日；actual 可能取到非月末日期 | 只按已到达的月末交易日锚点判断 |
| `stk_period_bar_month` | `month_last_calendar_day` | 源接口要求自然月末，不能用最后交易日判断 | 按自然月最后一天判断 |
| `stk_period_bar_adj_month` | `month_last_calendar_day` | 源接口要求自然月末，不能用最后交易日判断 | 按自然月最后一天判断 |
| `broker_recommend` | `every_natural_month` | 按 day lag 展示不符合月份键语义 | 按月份键判断 |
| `index_weight` | `month_window_has_data` | 按 day lag 展示不符合月窗口语义 | 按自然月窗口是否有数据判断 |

### 4.2 需要二次确认的数据集

| 数据集 | 当前 date_model | 风险 | 需要确认 |
|---|---|---|---|
| `dividend` | `natural_day + every_natural_day` | 按 date model 后会严格按自然日 bucket 判断，可能从 fresh 变为 lagging/stale | 已决策：以 date model rule 为准，不做特殊规则 |
| `stk_holdernumber` | `natural_day + every_natural_day` | 同上 | 已决策：以 date model rule 为准，不做特殊规则 |
| `stk_mins` | `trade_open_day + every_open_day`，但 `audit_applicable=False` | 新鲜度可以按交易日看，完整性不能只按日期看 | freshness 与完整性审计要分开，不能把分钟级完整性简化成日级 bucket |
| 主数据/快照类 | `not_applicable` | 当前可能仍按最近同步日期显示类似 freshness | 本方案不处理，不新增表/字段；已登记 P1 风险，后续单独评审 |

---

## 5. 历史脏数据判断

### 5.1 哪些不是脏数据

这次问题不会直接污染业务数据表。

以下表中的业务数据本身不是因为 freshness 规则而变脏：

1. `raw_tushare.*`
2. `core.*`
3. `core_serving.*`
4. `core_serving_light.*`

如果某个数据集缺少某个应完成 bucket，那是“数据缺口”或“任务未补齐”，不是 status 规则写坏了业务表。

### 5.2 哪些是脏数据

这次脏数据主要是 Ops 派生状态表。

| 表 | 脏数据类型 | 原因 | 处理方式 |
|---|---|---|---|
| `ops.dataset_status_snapshot` | `expected_business_date`、`lag_days`、`freshness_status`、部分 `latest_business_date` 可能错误 | 当前规则按 cadence/day lag 计算 | 代码修正后全量 rebuild，可直接覆盖 |
| `ops.dataset_layer_snapshot_current` | raw / serving 阶段状态可能被错误 freshness 传播 | `_upsert_current_items()` 会把 item freshness status 写入 current | 代码修正后全量 rebuild，可更新当前行 |
| `ops.dataset_layer_snapshot_history` | 历史快照按旧规则追加，无法自动纠正 | rebuild 只追加 history，不删除旧 history | 建议在修正规则后清空旧 history，再重建新的当前状态 |

### 5.3 不建议改动的表

| 表 | 结论 | 原因 |
|---|---|---|
| 旧同步状态表 | 不参与现行 freshness 主链 | 该旧状态模型已退场；数据集 freshness/status 只允许依赖 `DatasetDefinition.date_model + 真实业务表观测 + TaskRun` |
| `ops.task_run` / `ops.task_run_node` / `ops.task_run_issue` | 本轮不作为脏数据清洗对象 | 它们是任务观测记录，不是数据集新鲜度快照 |

### 5.4 推荐清洗策略

本仓还未正式上线，可以停机处理，不需要兼容旧状态。

推荐策略：

1. 先修正 Ops freshness 代码，使其按 `date_model` 计算 expected / actual bucket。
2. 停机窗口内清空 `ops.dataset_layer_snapshot_history`。该项已决策，不保留旧规则历史。
3. 执行 `ops-rebuild-dataset-status` 重建当前状态。
4. 用重点数据集抽样校验：
   - `stk_period_bar_adj_week`
   - `stk_period_bar_week`
   - `index_weekly`
   - `stk_period_bar_adj_month`
   - `index_monthly`
   - `broker_recommend`
   - `index_weight`
5. 确认页面和 API 不再出现旧 rule 的 expected date / lag_days / freshness_status。

---

## 6. rebuild freshness 命令影响

### 6.1 命令现状

当前仓库中所谓“rebuild freshness”对应的是：

```bash
goldenshare ops-rebuild-dataset-status
```

入口在 `run_ops_rebuild_dataset_status()`，内部调用：

```text
DatasetStatusSnapshotService().rebuild_all(session, strict=True)
```

### 6.2 rebuild_all 当前做什么

当前 `rebuild_all()` 的行为是：

```text
build_live_items()
  -> delete ops.dataset_status_snapshot
  -> upsert ops.dataset_status_snapshot
  -> append ops.dataset_layer_snapshot_history
  -> upsert ops.dataset_layer_snapshot_current
  -> commit
```

重要影响：

1. 会删除并重建 `ops.dataset_status_snapshot`。
2. 会更新 `ops.dataset_layer_snapshot_current`。
3. 会向 `ops.dataset_layer_snapshot_history` 追加新记录。
4. 不会清空 `ops.dataset_layer_snapshot_history` 中旧规则产生的历史记录。
5. 不会修改业务数据表。
6. 不会读取或修改旧同步状态表。
7. 不会修改 `ops.task_run*`。

### 6.3 修正代码后运行 rebuild 的页面影响

运行后，下列页面/API 的状态可能变化：

1. 数据源/数据集卡片页的新鲜度状态。
2. 运维概览中的滞后数据集统计。
3. 数据层快照 current 展示。
4. `/api/v1/ops/freshness` 返回的 summary 和 group item。
5. `/api/v1/ops/layer-snapshots/latest` 返回的 raw / serving 阶段状态。
6. 任何依赖 `dataset_status_snapshot` 或 `dataset_layer_snapshot_current` 的提醒/看板。

其中周线数据集最可能从 `fresh` 变为 `lagging` 或 `stale`，这是正确修复，不是回归。

### 6.4 rebuild 前后必须验证的内容

| 验证项 | 目标 |
|---|---|
| `stk_period_bar_adj_week` | 如果最新有效周锚点仍是 `2026-04-17`，而 expected 是 `2026-04-24`，则不能显示 fresh |
| `stk_period_bar_adj_month` | 在 `2026-04-26` 时 expected 应是 `2026-03-31`，不是 `2026-04-24` |
| `index_monthly` | actual latest 必须按月末交易日锚点过滤，不能取非月末 `trade_date` |
| `broker_recommend` | 应按月份键判断，不应展示日级 lag 造成误导 |
| `index_weight` | 应按自然月窗口是否有数据判断，不应简单用最新交易日差值 |
| `dataset_layer_snapshot_history` | 如果决定清历史，重建后不应再混有旧规则记录 |

---

## 7. 实施里程碑

### M1：新增 date_model bucket resolver

目标：

1. 以 `DatasetDefinition.date_model` 生成 expected bucket。
2. 支持 `every_open_day`、`week_last_open_day`、`month_last_open_day`、`week_friday`、`month_last_calendar_day`、`every_natural_month`、`month_window_has_data`、`every_natural_day`、`not_applicable`。
3. 交易日相关规则必须读取交易日历；自然周五 / 自然月末规则必须从 `bucket_rule` 明确派生，不能用数据集 key 特判。

边界：

1. 不改业务数据同步逻辑。
2. 不改 TaskRun。
3. 不新增前端交互。

### M2：修正 actual latest 观测

目标：

1. 对 `week_last_open_day` 只取周最后交易日上的数据作为 actual latest。
2. 对 `month_last_open_day` 只取月最后交易日上的数据作为 actual latest。
3. 对 `week_friday` 只取自然周五上的数据作为 actual latest。
4. 对 `month_last_calendar_day` 只取自然月最后一天上的数据作为 actual latest。
5. 对 shared table 继续保留必要的 `freq=week/month` 过滤。
6. 对 `month_window_has_data` 改为判断窗口内是否存在数据。

边界：

1. 不把非 bucket 日期拿来冒充最新有效 bucket。
2. 不改原始数据表。

### M3：修正 freshness 状态和展示字段

目标：

1. 状态按 bucket 是否覆盖 expected 判断。
2. `lag_days` 如继续保留，必须只作为现有兼容展示信息，不再作为核心判断。
3. 不新增 `missing_bucket_count`、`expected_bucket_label` 或任何新状态字段；如后续确需 schema 变化，必须另立方案评审。

边界：

1. 不再通过 `weekly <= 7 days fresh` 这种宽限规则掩盖缺失 bucket。
2. 不用 `cadence` 推导 date model。

### M4：补测试

必须覆盖：

1. `2026-04-26` 下，周线 expected 是 `2026-04-24`。
2. `2026-04-26` 下，月线 expected 是 `2026-03-31`。
3. `index_monthly` 不能把非月末交易日当成 actual latest bucket。
4. `month_window_has_data` 判断当前月窗口是否有数据。
5. `not_applicable` 不走业务日期 freshness，且本方案不新增其替代健康模型。
6. rebuild 后 `dataset_status_snapshot` 和 `dataset_layer_snapshot_current` 结果一致。

### M5：处理历史脏数据并 rebuild

目标：

1. 停机。
2. 清理旧规则产生的历史派生记录。
3. 执行 `ops-rebuild-dataset-status`。
4. 抽样核验重点数据集。
5. 再恢复页面验收。

---

## 8. 明确不做

1. 不改业务同步路径。
2. 不改 raw/core/core_serving 表数据。
3. 不把 `cadence` 再扩展成新的规则表。
4. 不通过前端隐藏错误状态。
5. 不保留新旧 freshness 双规则。
6. 不引入临时兼容逻辑。
7. 不新增 Ops 状态表、策略表或字段。
8. 不在本方案中处理主数据/快照类健康模型。

---

## 9. 待决策项

**D1：是否清空 `ops.dataset_layer_snapshot_history`。**

已决策：清空。原因是旧记录按旧 freshness 规则追加，保留会污染后续趋势判断。

**D2：`dividend` / `stk_holdernumber` 是否继续使用 `every_natural_day`。**

已决策：以 date model 的 rule 为准，不做特殊规则。

**D3：主数据/快照类是否从业务日期 freshness 中退出。**

已移出本方案。这里说的是 `stock_basic`、`index_basic`、`ths_member` 这类 `date_model.bucket_rule=not_applicable` 的数据集，它们没有连续业务日期 bucket，不能像日线/周线一样回答“最新业务日期是否覆盖 expected bucket”。该问题已登记到 [工程风险登记簿](/Users/congming/github/goldenshare/docs/governance/engineering-risk-register.md) 的 `RISK-2026-04-26-003`，后续单独评审；本方案不得为它新增表、字段或并行状态副本。
