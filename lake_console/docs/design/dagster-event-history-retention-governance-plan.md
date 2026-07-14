# Dagster 历史 Event 存量清理专项方案

更新时间：2026-06-23

## 1. 目标

本专项的优先级是 **降存量，防增量**。

第一阶段只讨论现有 Dagster storage 中哪些历史 event / check 记录可以在不影响当前数据集状态、后续更新触发判断、Asset UI 当前状态展示的前提下清理。增量治理，例如合并高基数 asset checks、降低未来 check event 写入速度，作为第二阶段单独推进。

本方案不采用“更换 Dagster instance / 新建 Dagster Home / 重建运行库”的路线。该路线风险过高，会牵涉 sensor cursor、run history、run key 去重、dynamic partitions 和 current asset/check state 迁移，不作为主方案。

## 2. 本轮审计边界

本轮已做：

1. 阅读 orchestrator 当前代码，确认 readiness / status helper 如何消费 materialization、asset check、repair metadata。
2. 只读查询本机 Dagster Postgres，统计高基数表、候选清理规模和关键索引。
3. 不运行 `dg`。
4. 不触发 sensor、job、backfill、materialization 或 asset check。
5. 不写 Dagster DB。
6. 不写数据湖文件。

正式 Dagster DB：

```text
postgresql://congming@localhost:5432/goldenshare_dagster
```

## 3. 当前代码事实

### 3.1 普通 readiness 依赖 latest materialization 与目标 check

`orchestrator.defs.sensors.readiness.partition_dataset_readiness_status_from_latest_checks(...)` 的当前逻辑是：

1. 先按 `asset_key + partition_key` 取最新 materialization record。
2. 再按 `asset_key + check_name + partition_key` 批量取 latest asset check execution。
3. 通过 `target_materialization_data.storage_id` 确认 check 是否对应最新 materialization。
4. 只有 blocking checks 全部对应最新 materialization 且 passed，才认为 ready。

因此，清理 active asset 的历史 check event 时，不能只按 `asset_key + check_name + partition` 保留最新一条，还必须确保保留的 check 指向该分区最新 materialization storage id。

### 3.2 qfq factor repair 与 MACD/KDJ repair completion 是状态账本

以下 status / gate helper 会读取 check metadata：

1. `gold_stk_mins_qfq_factor_repair_status(...)`
   - 读取 `gold_stk_mins_qfq_factor_repair_plan_evaluated`。
   - metadata 中的 `producer_run_id`、`upstream_batch_id`、`repair_start_trade_date`、`repair_end_trade_date`、`repair_required_codes_hash` 等字段是下游触发和 repair config 的正式来源。
2. `gold_stk_mins_qfq_macd_kdj_repair_completion_status_for_upstream_batch(...)`
   - 读取 `gold_stk_mins_qfq_macd_kdj_repair_completed_check`。
   - completion 的正式 Dagster partition 是 `qfq_factor_repair_trade_date`；`repair_start_trade_date` 与 `repair_end_trade_date` 仅表达覆盖范围，不得再作为 latest completion 查询分区。
   - metadata 中的 `source_upstream_batch_id`、覆盖范围、代码 hash、freqs 等字段用于防重复和 completion gate。同一触发日若产生新 upstream batch，旧 completion metadata 必须失配并 fail-closed。

这类 check event 数量很小，但语义很重。第一阶段一律禁止清理。R5-P5 对 `2026-07-08/09/10/13` 的旧 `2014-01-02` completion events 只视为历史证据；经 source run、14 条绿 check 和 metadata 精确核验后，最多补 56 条 runless check event 到各自的 trigger-date partition。旧证据和新 identity 状态均不得在 retention 清理中删除。

只读统计：

| check | 当前数量 | 处理口径 |
| --- | ---: | --- |
| `gold_stk_mins_qfq_factor_repair_plan_evaluated` | 188 | 禁删 |
| `gold_stk_mins_qfq_macd_kdj_repair_completed_check` | 126 | 禁删 |

### 3.3 `raw_tushare_index_daily_by_code` 仍是 active definition

代码中仍存在：

1. `assets/index_daily.py::raw_tushare_index_daily_by_code`
2. `jobs/index_daily_update.py`
3. `checks/index_daily_checks.py` 中 raw by-code checks
4. `catalog/lake_assets.py` 中 catalog entry
5. `sensors/readiness.py` 中 `RAW_INDEX_DAILY_BY_CODE_READINESS_SPEC`
6. `asset_guards/market_major_indices_lake_readiness.py` 和 `index_daily_raw_file_readiness.py` 仍读取 raw by-code 文件事实。

所以 `raw_tushare_index_daily_by_code` 虽然是高基数旧模式，但当前还不能按 retired asset 直接清理。只有完成 raw index daily by-date 迁移、active definitions 和 readiness 消费者清零后，才能进入 retired asset 清理。

## 4. Dagster Storage 现状

只读统计结果：

| 表 | 行数 / 体积 |
| --- | ---: |
| `event_logs` | 6,423,756 行，约 11GB |
| `asset_check_executions` | 1,253,712 行，约 3.2GB |
| `asset_event_tags` | 79,329 行，约 32MB |
| `runs` | 71,144 行，约 147MB |
| `run_tags` | 约 125MB |

关键事件规模：

| event type | count |
| --- | ---: |
| `ASSET_CHECK_EVALUATION` | 1,273,675 |
| `ASSET_CHECK_EVALUATION_PLANNED` | 492,593 |
| `ASSET_MATERIALIZATION` | 222,456 |
| `ASSET_MATERIALIZATION_PLANNED` | 96,165 |

`asset_check_executions` 与 materialization 的关联：

| 分类 | 数量 |
| --- | ---: |
| total check rows | 1,253,712 |
| 带 `materialization_event_storage_id` | 1,155,425 |
| 指向当前 latest materialization | 908,351 |
| 指向已被覆盖的旧 materialization | 247,074 |
| 无 `materialization_event_storage_id` | 98,287 |

同一 `asset_key + check_name + materialization_event_storage_id` 的重复 check 很少：

| 分类 | 数量 |
| --- | ---: |
| 同一 materialization/check 的重复旧 check | 336 |
| 每组保留的最新 check | 1,155,089 |

结论：

1. 存量清理的第一大安全候选不是简单重复 check，而是“旧 materialization 及其绑定的旧 checks”。
2. 无 `materialization_event_storage_id` 的 check 不能直接按 latest materialization 规则清理，必须单独审计。
3. `event_logs` 仍是最大体积来源，仅清 `asset_check_executions` 不能完全解决 DB 体积问题。

## 5. 可清理 / 禁止清理分类

### 5.1 第一阶段可进入 dry-run 的候选

#### A. 被最新 materialization 覆盖的旧 check event

定义：

```text
asset_check_executions.materialization_event_storage_id is not null
AND materialization_event_storage_id 不是该 asset_key + partition 的最新 ASSET_MATERIALIZATION event id
```

当前候选总量：

| 项 | 数量 |
| --- | ---: |
| `asset_check_executions` 旧 check rows | 247,074 |
| 对应 `event_logs.ASSET_CHECK_EVALUATION` rows | 247,053 |

Top 来源：

| asset | old check count |
| --- | ---: |
| `raw_tushare_index_daily_by_code` | 114,180 |
| `silver_index_daily` | 78,925 |
| `ch_share_fact_market_breadth_daily` | 18,208 |
| `gold_stock_return_distribution` | 18,186 |
| `prod_ch_share_fact_market_breadth_daily` | 13,072 |
| `silver_stock_daily` | 1,075 |

这些旧 check 已经被同一 asset/partition 的更新 materialization 覆盖，且当前 readiness 只消费 latest materialization 对应 checks。它们是第一阶段主要清理候选。

#### B. 被最新 materialization 覆盖的旧 materialization event

定义：

```text
event_logs.dagster_event_type = 'ASSET_MATERIALIZATION'
AND event id 不是该 asset_key + partition 的最新 materialization id
```

当前候选总量：

| 项 | 数量 |
| --- | ---: |
| old materialization event rows | 67,471 |

Top 来源：

| asset | old materialization count |
| --- | ---: |
| `raw_tushare_index_daily_by_code` | 22,834 |
| `silver_index_daily` | 15,480 |
| `raw_tushare_index_daily` | 11,210 |
| `prod_ch_share_fact_market_breadth_daily` | 5,149 |
| `raw_tushare_suspend_d` | 3,056 |
| `silver_stock_suspend_daily` | 3,056 |
| `ch_share_fact_market_breadth_daily` | 3,037 |
| `gold_stock_return_distribution` | 3,031 |

清理旧 materialization event 时必须先处理：

1. 绑定这些旧 materialization 的旧 check rows。
2. `asset_event_tags` 中对应 `event_id` 的标签。

#### C. 已退出源码引用的旧 check name

当前明确候选：

| check name | DB count | 当前源码引用 |
| --- | ---: | --- |
| `silver_stock_daily_current_listed_only` | 5,175 | `defs` 下 0 命中 |

这个 check 已经退出当前 `defs` 源码引用，可作为 retired check name 候选。但正式删除前仍必须用 active definitions 对账，确认 `dg list defs` 中不再存在该 check definition。

### 5.2 第二阶段候选，第一阶段不删

#### A. 无 `materialization_event_storage_id` 的 check event

当前总量：

| 项 | 数量 |
| --- | ---: |
| check rows without materialization ref | 98,287 |

Top 来源：

| asset | count |
| --- | ---: |
| `silver_stock_daily` | 25,150 |
| `ch_share_fact_market_breadth_daily` | 21,476 |
| `gold_market_breadth_daily` | 12,625 |
| `prod_ch_share_fact_market_breadth_daily` | 9,920 |
| `raw_tushare_stock_daily` | 8,468 |
| `raw_tushare_suspend_d` | 8,388 |
| `raw_tushare_index_daily_by_code` | 4,775 |
| `silver_stock_suspend_daily` | 4,194 |

这些记录无法通过 `latest materialization storage id` 保护规则判断安全性，第一阶段禁止删除。后续如果要清理，必须先确认：

1. 是历史旧定义 bug 产生的无 target check。
2. 当前 latest check state 已经由带 target materialization 的 check 替代。
3. 对应 check name 不被 status helper 读取 metadata。

#### B. planned events

| event type | count |
| --- | ---: |
| `ASSET_CHECK_EVALUATION_PLANNED` | 492,593 |
| `ASSET_MATERIALIZATION_PLANNED` | 96,165 |

这类 event 不承载最终 asset/check status，但会影响 run event history 的完整性。第一阶段不删。后续可以单独设计“历史 planned event 清理”阶段，前提是用户接受历史 run 详情不再完整展示 planned step。

### 5.3 禁止清理范围

第一阶段明确禁止删除：

1. `runs`
2. `run_tags`
3. `dynamic_partitions`
4. `instigators`
5. `daemon_heartbeats`
6. `kvs`
7. `pending_steps`
8. active asset/check 的 latest materialization 与 latest check state
9. `gold_stk_mins_qfq_factor_repair_plan_evaluated`
10. `gold_stk_mins_qfq_macd_kdj_repair_completed_check`
11. 任何 still-running / queued / recent run 相关 event
12. 任何无法证明已被 latest state 覆盖的 event

原因：

1. `runs` / `run_tags` 可能影响 run key 去重、run history、run-status sensor 和排障。
2. `dynamic_partitions` 直接影响 partition 是否存在。
3. `instigators` 保存 sensor/schedule 开关、cursor 和 tick 状态。
4. repair/status 类 check metadata 是业务状态账本，数量小但语义重。

## 6. Dry-run SQL 设计

所有清理必须先 dry-run。dry-run 只读输出候选数量、样本和保护规则命中情况。

### 6.1 最新 materialization 保护集合

```sql
WITH latest_materializations AS (
  SELECT
    asset_key,
    COALESCE(partition, '') AS partition_key,
    max(id) AS latest_materialization_id
  FROM event_logs
  WHERE dagster_event_type = 'ASSET_MATERIALIZATION'
    AND asset_key IS NOT NULL
  GROUP BY asset_key, COALESCE(partition, '')
)
SELECT count(*)
FROM latest_materializations;
```

### 6.2 旧 check 候选

```sql
WITH latest_materializations AS (
  SELECT
    asset_key,
    COALESCE(partition, '') AS partition_key,
    max(id) AS latest_materialization_id
  FROM event_logs
  WHERE dagster_event_type = 'ASSET_MATERIALIZATION'
    AND asset_key IS NOT NULL
  GROUP BY asset_key, COALESCE(partition, '')
)
SELECT
  ace.asset_key,
  count(*) AS candidate_count
FROM asset_check_executions ace
WHERE ace.materialization_event_storage_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1
    FROM latest_materializations lm
    WHERE lm.latest_materialization_id = ace.materialization_event_storage_id
  )
  AND ace.check_name NOT IN (
    'gold_stk_mins_qfq_factor_repair_plan_evaluated',
    'gold_stk_mins_qfq_macd_kdj_repair_completed_check'
  )
GROUP BY ace.asset_key
ORDER BY candidate_count DESC;
```

### 6.3 旧 materialization 候选

```sql
WITH ranked_materializations AS (
  SELECT
    id,
    asset_key,
    COALESCE(partition, '') AS partition_key,
    row_number() OVER (
      PARTITION BY asset_key, COALESCE(partition, '')
      ORDER BY id DESC
    ) AS rn
  FROM event_logs
  WHERE dagster_event_type = 'ASSET_MATERIALIZATION'
    AND asset_key IS NOT NULL
)
SELECT asset_key, count(*) AS candidate_count
FROM ranked_materializations
WHERE rn > 1
GROUP BY asset_key
ORDER BY candidate_count DESC;
```

### 6.4 防误删校验

dry-run 必须证明候选集合不包含：

1. 任意 `latest_materialization_id`
2. 任意 `asset_check_executions.materialization_event_storage_id = latest_materialization_id` 的 check
3. repair/status 类 check names
4. 最近运行中的 run 相关 event
5. 无法解释的 `materialization_event_storage_id IS NULL` check

示例：

```sql
WITH latest_materializations AS (...),
old_check_candidates AS (...)
SELECT count(*)
FROM old_check_candidates c
JOIN latest_materializations lm
  ON lm.latest_materialization_id = c.materialization_event_storage_id;
```

期望结果必须为 `0`。

## 7. 详细推进步骤

### P0：冻结边界

目标：先把本专项的禁止项和执行边界冻结，避免为了瘦身破坏 Dagster 当前状态。

本阶段只做文档与只读确认，不执行删除。

硬口径：

1. 只处理现有 Dagster DB 内历史 event / check 存量。
2. 不换 Dagster instance。
3. 不新建 Dagster Home。
4. 不重建运行库。
5. 不删除 `runs`。
6. 不删除 `run_tags`。
7. 不删除 `dynamic_partitions`。
8. 不删除 `instigators`。
9. 不删除 qfq factor repair / MACD-KDJ repair completion 状态账本 check。
10. 不删除任何无法证明已被 latest state 覆盖的 event。

验收：

1. 本文档中的禁删范围已明确。
2. 第一阶段候选只包含 old materialization 与绑定 old materialization 的 old checks。
3. 正式清理前必须停 `dg dev` / daemon / webserver，并完整备份 Postgres。

### P1：只读 dry-run 工具

目标：实现一个只读 dry-run CLI/helper，把候选集合、保护集合和误删校验固化为可重复执行的报告。

职责：

1. 读取 Dagster Postgres，不写 DB。
2. 生成 latest materialization 保护集合。
3. 生成 old check 候选集合。
4. 生成 old materialization 候选集合。
5. 生成禁删 check name 命中集合。
6. 生成 retired check name 候选集合。
7. 输出 JSON / CSV 报告到 `/private/tmp`。
8. 不执行任何 `DELETE`。

报告至少包含：

| 分类 | 输出 |
| --- | --- |
| 保护集合 | latest materialization 数、latest check 数、repair/status check 数 |
| 候选集合 | old check 数、old materialization 数、对应 `event_logs` 数、对应 `asset_event_tags` 数 |
| 风险集合 | 无 `materialization_event_storage_id` check 数、planned event 数、禁删 check 命中数 |
| 样本 | 每类候选各 20 条样本，包含 asset、partition、check_name、event id、run_id |

防误删断言：

1. 候选 old check 中不得包含最新 materialization 对应的 check。
2. 候选 old materialization 中不得包含任一 `asset_key + partition` 的最新 materialization。
3. 候选集合不得包含 `gold_stk_mins_qfq_factor_repair_plan_evaluated`。
4. 候选集合不得包含 `gold_stk_mins_qfq_macd_kdj_repair_completed_check`。
5. 候选集合不得包含 running / queued / recent run 相关 event。

验收：

1. dry-run 工具本地单元测试覆盖 SQL 生成和保护规则。
2. 正式 Dagster DB 只读 dry-run 成功输出报告。
3. 报告中误删断言全部为 0。

### P2：小样本资产 dry-run

目标：先选低风险资产做只读 dry-run，不进入删除。

本阶段已审计的小样本资产：

1. `ch_share_fact_market_breadth_daily`
2. `gold_stock_return_distribution`
3. `prod_ch_share_fact_market_breadth_daily`

不先选择 `raw_tushare_index_daily_by_code`，原因是它当前仍是 active definition，仍有 job、checks、catalog、readiness 和文件事实消费者。

每个资产输出：

1. 可删 old check 数。
2. 可删 old materialization 数。
3. 涉及 `event_logs` 数。
4. 涉及 `asset_event_tags` 数。
5. 保留 latest materialization 样本。
6. 保留 latest check 样本。
7. 清理前 readiness 结果样本。
8. 清理后预期剩余状态。

验收：

1. dry-run 证明候选不含 latest state。
2. dry-run 证明候选不含 repair/status metadata。
3. dry-run 证明清理后每个样本资产仍有 latest materialization 和 latest blocking checks。

2026-06-23 只读 dry-run 结论：

报告文件：

`/private/tmp/dagster_event_history_retention_sample_dry_run_20260623.json`

样本统计：

| asset | old checks | old materializations | old materialization tags | latest materializations | latest materializations without latest checks | latest checks | 结论 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `ch_share_fact_market_breadth_daily` | 18,208 | 3,037 | 3,037 | 3,028 | 0 | 18,168 | 可进入 P3 小样本删除 |
| `gold_stock_return_distribution` | 18,186 | 3,031 | 3,031 | 3,029 | 0 | 18,174 | 可进入 P3 小样本删除 |
| `prod_ch_share_fact_market_breadth_daily` | 13,072 | 5,149 | 5,145 | 3,028 | 3,007 | 84 | 禁止进入 P3；P2R 只保留未来归属修复，不再做历史全量补录 |

P2 实测结论：

1. `ch_share_fact_market_breadth_daily` 和 `gold_stock_return_distribution` 满足“小样本删除”前置条件：latest materialization 都有 latest check state 覆盖。
2. `prod_ch_share_fact_market_breadth_daily` 不满足前置条件：3,007 个 latest materialization 没有 latest check state。
3. P2 的全量三资产验收没有整体通过，但允许将 P3 缩小到前两个资产继续推进。
4. `prod_ch_share_fact_market_breadth_daily` 不进入 P3/P4 删除白名单；P2R 的历史全量 checks-only 补录已停止，不再作为 P3 前置。

### P2R：`prod_ch_share_fact_market_breadth_daily` check 归属修复（停止历史全量补录）

目标：保留 `prod_ch_share_fact_market_breadth_daily` 的代码层 check 归属修复，确保后续新 run 不再产生“multi-partition materialization + 单条 check result”的归属错误；停止对 3,007 个历史缺口分区做全量 checks-only 补录。

本阶段不是删除阶段，不清理 Dagster event，不清理 lake 文件，不重写 ClickHouse 数据。

2026-06-23 复盘结论：

1. P2R 代码修复仍然有效：prod asset/check 正式路径收敛为 single-partition，四个 prod checks 显式声明 `partitions_def=cn_a_stock_trade_days`，checks-only job 也被修正为可按 partition 运行。
2. P2R 历史全量补录停止：不再对剩余约 3,005 个历史分区逐个运行 `prod_clickhouse_share_fact_market_breadth_check_refresh_job`。
3. 已经做过的少量 pilot check event 作为历史 event 保留，不做删除或回滚；后续也不继续扩大补录。
4. 停止原因是性能与收益不匹配：3,007 个分区逐个 `dg launch` 会写入约 `3,007 * 4 = 12,028` 条 latest check event，并额外产生大量 run / step / planned / log event，执行耗时和 event 增量都与本专项“降存量”目标冲突。
5. 不补录不影响后续数据湖更新、prod sync 日常执行或 serving 数据正确性；影响仅限于 `prod_ch_share_fact_market_breadth_daily` 不能进入当前事件历史删除白名单。

只读审计事实：

1. 当前 `prod_clickhouse_share_fact_market_breadth_sync_job` 同时包含 asset materialization 与 asset checks。
2. 当前 asset/check 都通过 `context.partition_keys` 支持一次 run 处理多个 partitions。
3. 当前每个 check 函数对一批 `context.partition_keys` 只返回一个 `dg.AssetCheckResult`。
4. Dagster 最终只能把这个 check event 绑定到一个 materialization/partition，导致同一批 run 里其它 partitions 有 materialization 但没有对应 latest check。
5. 代表样本：
   - run `7a76df46-0fa1-4cf4-84ea-4b14c5c1eae4` materialize 250 个 partitions，但 4 条 check rows 都绑定到同一个 `materialization_event_storage_id=5397988` / partition `2025-10-16`。
   - run `a9072abe-db76-4c21-9c73-4669ceda49b7` materialize `2026-06-18` 与 `2026-06-17`，4 条 check rows 都绑定到 `2026-06-17`，`2026-06-18` 缺 latest check。

根因判断：

这是实现/设计 bug，不是 P2 dry-run 工具误判，也不是 Dagster DB 损坏。问题来自“multi-partition batch check 写一个 check result”的写法与 Dagster check event 的 partition 归属模型不匹配。

执行步骤：

1. 代码影响面审计
   - 已审计 `prod_ch_share_fact_market_breadth_daily` 的 asset、checks、job、sensor、manual launch、backfill 入口。
   - 风险入口来自 asset/check 对 `context.partition_keys` 的多分区支持，以及 `BackfillPolicy.multi_run(max_partitions_per_run=250)`。
   - 日常 sensor 本身按单日提交，但历史 backfill / manual launch 可能触发 multi-partition execution。

2. 修复策略确认
   - 已确认当前 Dagster 1.13.8 的 `AssetCheckResult` 没有独立 `partition_key` 参数。
   - check event partition 归属来自 step partition，不能靠一个 check function 为多个 partitions 返回一条聚合结果来覆盖全部 partitions。
   - 采用保守且可验证的正式口径：`prod_ch_share_fact_market_breadth_daily` asset/check 只允许 single-partition execution。
   - 禁止继续保留“多 partition materialization + 单条 check result”的实现。

3. 代码修复
   - `PROD_MARKET_BREADTH_SYNC_MAX_PARTITIONS_PER_RUN` 改为 `1`。
   - `prod_ch_share_fact_market_breadth_daily` 正式执行前必须确认 `context.partition_keys` 只有一个值。
   - 四个 prod checks 必须在 decorator 上显式声明 `partitions_def=cn_a_stock_trade_days`，否则 checks-only job 即使按 partition 执行，写出的 `ASSET_CHECK_EVALUATION` event partition 仍可能为空。
   - 四个 prod checks 的 `_selected_partition_keys(...)` 统一改为 single-partition guard；多个 partitions 直接 fail closed。
   - metadata 以单分区为主语义，保留 `partition_key`，不再把正式路径描述为 batch check。
   - 增加单元测试：多 partition check context 必须失败，不允许返回一条无法覆盖全部 partitions 的聚合 check result。
   - 增加静态/契约门禁：`prod_ch_share_fact_market_breadth_daily` 不得回流到 batch partitions 只返回一个 check result 的写法。

4. checks-only 维护入口口径
   - 新增人工维护入口 `prod_clickhouse_share_fact_market_breadth_check_refresh_job`。
   - selection 只能是 `AssetSelection.checks_for_assets(prod_ch_share_fact_market_breadth_daily)`。
   - job 必须显式使用 `partitions_def=cn_a_stock_trade_days` 和基于同一 partition set 的空 `PartitionedConfig`；当前 Dagster 1.13.8 下，checks-only selection 没有 selected asset key，单独传 `partitions_def` 不足以让 `dg launch --partition` 识别 job 为 partitioned。
   - 禁止包含 `AssetSelection.assets(...)`，只跑 checks-only，不重写 ClickHouse 数据。
   - 该 job 只允许作为小范围、经单独审批的维护入口；禁止用于 3,007 个历史缺口分区的全量补录。
   - 如未来确实要修复存量 latest check 缺口，必须先另行设计高性能、低 event 增量的方案，不能恢复逐 partition `dg launch` 补录。

5. P2R 当前验收口径
   - 代码层验收只证明后续新 run/check 不再回流 multi-partition 归属错误。
   - 历史 latest check 缺口不作为本阶段修复目标。
   - `prod_ch_share_fact_market_breadth_daily` 继续保持 `latest_materializations_without_latest_checks > 0` 的风险标记。
   - 该资产不得进入 P3/P4 删除候选，直到另一个经审批的独立方案证明 latest state 保护完整。

P2R 禁止项：

1. 禁止为了通过 P2 直接删除 `prod_ch_share_fact_market_breadth_daily` 的旧 events。
2. 禁止删除 latest materialization。
3. 禁止删除无 check 覆盖的 materialization 来“制造通过”。
4. 禁止用重跑数据同步 job 代替 checks-only 修复，除非另行审批并证明不会重写业务数据。
5. 禁止把该资产纳入 P3/P4 删除白名单，除非未来独立方案证明 latest materialization 与 latest checks 已完整覆盖。

2026-06-23 后当前推荐推进顺序：

1. 先推进缩小版 P3：只处理 `ch_share_fact_market_breadth_daily` 与 `gold_stock_return_distribution`。
2. 停止 P2R 历史全量补录；prod 资产继续排除，不阻塞缩小版 P3。
3. P3 小样本删除验证稳定后，再进入 P4 全局 old-state 清理，但 P4 仍不得包含 `prod_ch_share_fact_market_breadth_daily`。
4. 如未来要让 `prod_ch_share_fact_market_breadth_daily` 进入删除候选，必须另开高性能 latest-check 缺口修复方案，并重新执行 P2 dry-run。
5. P5 retired check / retired asset 清理必须等待 active definitions、readiness、catalog、sensor/status helper 引用清零。
6. P6 物理空间回收只在逻辑删除验证后单独评估，不与 P3/P4/P5 混跑。

### P3：正式小样本清理

目标：在 P2 dry-run 通过后，对小样本资产执行第一轮真实删除。

本阶段必须单独审批。未经审批不得执行。

2026-06-23 后的 P3 范围调整：

P3 第一批只允许包含：

1. `ch_share_fact_market_breadth_daily`
2. `gold_stock_return_distribution`

P3 第一批禁止包含：

1. `prod_ch_share_fact_market_breadth_daily`
2. `raw_tushare_index_daily_by_code`
3. repair/status 类 check asset
4. 任意 P2 dry-run 未证明 latest materialization 与 latest checks 完整的 asset

2026-06-23 P3 前置只读复核：

| asset | latest materializations | latest materializations with latest checks | latest materializations without latest checks | latest check rows | 结论 |
| --- | ---: | ---: | ---: | ---: | --- |
| `ch_share_fact_market_breadth_daily` | 3,028 | 3,028 | 0 | 18,168 | 可进入 P3 |
| `gold_stock_return_distribution` | 3,029 | 3,029 | 0 | 18,174 | 可进入 P3 |
| `prod_ch_share_fact_market_breadth_daily` | 3,028 | 23 | 3,005 | 96 | 继续禁止进入 P3/P4 |

复核口径：

1. latest check 覆盖必须按 `asset_check_executions.materialization_event_storage_id = latest ASSET_MATERIALIZATION event id` 判断。
2. 不得用 `asset_check_executions.partition` 字段单独判断这两个白名单资产是否有 latest check；当前历史 check event 的 `partition` 可能为空，但 materialization id 绑定是正确的。
3. P3 删除 SQL 必须保护所有 latest materialization id 及其绑定 latest check event，不能把 partition 为空的 latest check 误删。
4. `prod_ch_share_fact_market_breadth_daily` 虽然已有少量 pilot partition check event，但仍有 3,005 个 latest materialization 缺 latest check；P2R 历史全量补录已停止，因此该资产继续排除。

执行前置：

1. 停止 `dg dev` / daemon / webserver。
2. 确认无 queued / running runs。
3. 完整备份 Dagster Postgres。
4. 重新执行缩小范围 P2 dry-run，保存报告。
5. dry-run 报告必须按 materialization id 绑定口径显示本次白名单资产 `latest_materializations_without_latest_checks = 0`。
6. 明确本次删除 asset 白名单，白名单只能是本小节允许的两个 asset。

执行顺序：

1. 删除候选 check event 对应的 `asset_event_tags`。
2. 删除候选 check event 对应的 `event_logs.ASSET_CHECK_EVALUATION`。
3. 删除候选 `asset_check_executions`。
4. 删除候选 old materialization event 对应的 `asset_event_tags`。
5. 删除候选 old materialization `event_logs.ASSET_MATERIALIZATION`。
6. `ANALYZE event_logs`。
7. `ANALYZE asset_check_executions`。
8. `ANALYZE asset_event_tags`。

禁止：

1. 不执行 `VACUUM FULL`。
2. 不删除 `runs`。
3. 不删除 `run_tags`。
4. 不删除 planned events。
5. 不删除无 `materialization_event_storage_id` 的 check events。

验收：

1. Asset 页面 Status 正常。
2. 样本资产 latest materialization 不变。
3. 样本资产 latest blocking check status 不变。
4. readiness helper 结果与清理前一致。
5. sensor 不重复触发。
6. `prod_ch_share_fact_market_breadth_daily` 行数与 latest state 不发生任何变化。

### P4：扩大到全局 old-state 清理

目标：P3 小样本验证通过后，将相同规则扩大到所有符合条件的 old-state 记录。

范围：

1. 所有 active asset 中被 latest materialization 覆盖的 old checks。
2. 所有 active asset 中被 latest materialization 覆盖的 old materializations。

仍然不处理：

1. 无 `materialization_event_storage_id` 的 check。
2. planned events。
3. run history。
4. repair/status metadata checks。
5. retired asset 全量清理。
6. latest materialization 缺 latest check state 的 asset。

执行策略：

1. 按 asset 分批。
2. 每批删除前重新 dry-run。
3. 每批删除后做 readiness 样本验证。
4. 单批数量超阈值时继续拆小批。
5. 每个 asset 进入 P4 前必须满足：`latest_materializations_without_latest_checks = 0`。
6. 若发现 latest materialization 缺 latest check state，必须先进入独立修复阶段，不能靠删除历史 event 绕过。

建议批次顺序：

1. serving / gold 派生资产。
2. index daily 相关 active old-state。
3. stock daily / suspend_d old-state。
4. stk mins old-state。

验收：

1. 每批误删断言为 0。
2. 每批 active latest state 不变。
3. 每批 UI Status 抽样正常。

### P5：retired check / retired asset 清理

目标：处理已经从 active definitions 和所有消费者中退出的 check / asset。

候选：

1. `silver_stock_daily_current_listed_only`
2. 后续退出后的 `raw_tushare_index_daily_by_code`
3. 其它 active definitions 已清零的旧 check / asset

每个 retired 对象必须先通过六项审计：

1. 当前源码 0 引用。
2. active definitions 0 命中。
3. readiness specs 0 引用。
4. catalog 0 引用。
5. sensor/status helper 0 引用。
6. UI 当前状态不依赖。

删除范围按对象单独设计，不能复用 P4 的 old-state 规则一刀切。

验收：

1. retired 对象不再出现在 active asset/check definitions。
2. 删除后 active UI 状态不变。
3. 删除后 sensors 不重复提交。

### P6：物理空间回收评估

目标：逻辑删除验证完成后，再评估是否需要释放磁盘空间。

事实：

1. PostgreSQL 普通 `DELETE` 不会立刻缩小表文件。
2. `VACUUM` 主要回收死元组供表内复用，通常不缩小文件。
3. `VACUUM FULL` 会重写表并锁表。
4. `pg_repack` 可能降低锁影响，但需要额外工具和审批。

执行建议：

1. 第一阶段只做 `ANALYZE`，观察 UI 查询是否改善。
2. 如果磁盘空间仍是问题，再设计维护窗口。
3. 物理回收必须单独审批，不与逻辑清理混在同一阶段。

验收：

1. 明确清理前后表行数。
2. 明确清理前后表大小。
3. 明确 UI Status 查询耗时变化。
4. 明确是否需要进入物理回收窗口。

## 8. 清理执行设计

正式清理必须单独审批。本方案阶段不执行任何删除。

执行前置：

1. 停止 `dg dev` / daemon / webserver，避免 UI 或 daemon 同时读写。
2. 确认没有 queued / running runs。
3. 完整备份 Dagster Postgres。
4. 先执行 dry-run SQL 并保存报告。
5. 小样本删除，验证 UI 和 readiness，再扩大。

推荐删除顺序：

1. 删除候选 check event 对应的 `asset_event_tags`。
2. 删除候选 check event 对应的 `event_logs.ASSET_CHECK_EVALUATION`。
3. 删除候选 `asset_check_executions`。
4. 删除候选 old materialization event 对应的 `asset_event_tags`。
5. 删除候选 old materialization `event_logs.ASSET_MATERIALIZATION`。
6. `ANALYZE` 相关表。

注意：

1. PostgreSQL 普通 `DELETE` 不会立刻释放磁盘文件体积。
2. `VACUUM` 可回收死元组给表内复用，但通常不缩小文件。
3. `VACUUM FULL` 可缩小文件，但会重写并锁表，必须单独维护窗口审批。
4. 如要在线回收空间，应另行评估 `pg_repack`，不放在第一阶段。

## 9. 第一批建议范围

第一批不按 asset 直接全删，而按“已被 latest materialization 覆盖”的候选集合删。

2026-06-23 后建议小样本：

1. `ch_share_fact_market_breadth_daily`
2. `gold_stock_return_distribution`

原因：

1. 两者旧 check/materialization 候选数量明显。
2. 不涉及 qfq repair / MACD/KDJ repair metadata。
3. 不直接触碰当前最大但仍 active 的 `raw_tushare_index_daily_by_code`。
4. 可验证 ClickHouse serving / gold 派生资产的 UI current status 是否保持稳定。
5. P2 实测证明两者 latest materialization 与 latest check state 完整，具备小样本删除前置条件。

暂缓资产：

`prod_ch_share_fact_market_breadth_daily` 暂缓进入第一批。

暂缓原因：

1. P2 dry-run 发现 3,007 个 latest materialization 没有 latest check state。
2. 根因是 multi-partition batch check 归属不正确。
3. P2R 代码修复只解决后续新 run/check 的归属正确性，不再做 3,007 个历史分区全量补录。
4. 当前它必须继续排除在 P3/P4 删除候选外；只有未来独立方案证明 `latest_materializations_without_latest_checks = 0` 后，才允许重新讨论是否进入候选。

`raw_tushare_index_daily_by_code` 的清理顺序：

1. 先完成 raw index daily by-date 迁移。
2. active definition、job、checks、catalog、readiness、docs 引用清零。
3. dry-run 确认 UI / sensor 不再消费 by-code asset。
4. 再作为 retired asset 做更大范围清理。

`silver_stock_daily_current_listed_only` 的清理顺序：

1. 先用 definitions 审计确认 check 不再 active。
2. dry-run 确认没有 readiness/spec/status helper 引用。
3. 再清理该 retired check name 的历史 rows。

## 10. 验收标准

每次清理后必须只读验证：

1. Asset 页面核心 Status 字段正常返回。
2. active asset 的 latest materialization 不变。
3. active blocking check latest status 不变。
4. dynamic partitions 数量不变。
5. sensor cursor / instigator 状态不变。
6. qfq factor repair status 能读取最新 metadata。
7. MACD/KDJ repair completion gate 能读取最新 metadata。
8. 目标资产 readiness helper 结果与清理前一致。

建议保留清理前后报告：

| 指标 | 清理前 | 清理后 |
| --- | ---: | ---: |
| `event_logs` rows |  |  |
| `asset_check_executions` rows |  |  |
| `asset_event_tags` rows |  |  |
| `event_logs` size |  |  |
| `asset_check_executions` size |  |  |
| Asset Status GraphQL p95 |  |  |
| selected readiness sample result |  |  |

## 11. 增量治理衔接

存量清理只能降低已有历史压力，不能阻止新 event 继续增长。后续必须推进增量治理：

1. 合并过细 asset checks。
2. 每个 asset/partition 默认不超过 3 到 5 个 blocking checks。
3. 文件存在、row count、schema、required columns、partition date、unique key 合并成一个 contract check。
4. 只有 source coverage、lifecycle coverage、repair completion、state continuity、cross-layer reconciliation 这类真正治理边界保留独立 check。
5. `multi_asset_check` 只减少执行函数数量，不减少 event 数；要减少事件数必须减少 `AssetCheckSpec` 数量。

## 12. 待拍板事项

1. 是否同意第一阶段只处理“旧 materialization 及其绑定旧 check”，不处理 `runs` / `run_tags` / `dynamic_partitions` / `instigators`。
   - 建议：同意。
2. 是否同意第一批小样本缩小为 `ch_share_fact_market_breadth_daily`、`gold_stock_return_distribution`，暂缓 `prod_ch_share_fact_market_breadth_daily`。
   - 建议：同意。P2 实测已证明前两个资产满足 latest state 保护条件；`prod_ch_share_fact_market_breadth_daily` 停止 P2R 历史全量补录，并继续排除在 P3/P4 候选外。
3. 是否接受普通 `DELETE` 后磁盘文件不立即缩小，第一阶段先验证 UI/status/readiness 正确性；物理回收空间另开维护窗口。
   - 建议：同意。
4. 是否将 `silver_stock_daily_current_listed_only` 列为 retired check name 候选，但要求先做 active definitions 审计后再删除。
   - 建议：同意。
