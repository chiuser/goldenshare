# 股票分钟线 Dagster Event History Retention 专项方案

更新时间：2026-06-23

## 1. 目标

本专项只解决股票分钟线资产族在 Dagster Postgres 中产生的高基数 event / asset check 历史问题。

用户已确认新的保留口径：

1. 不要求 Dagster UI 继续完整证明 2014 年以来每个历史分区、每个 check 都绿。
2. 历史数据湖 Parquet 已经确认正确，历史 Dagster 普通日志和普通 check 历史不再作为长期证明保存。
3. Dagster DB 只需要保留不影响后续每日更新、计算、自动触发和当前 UI 状态判断的必要状态。
4. 股票分钟线普通历史 event 默认只保留最近 20 个交易日。

本专项不删除数据湖文件，不删除 dynamic partitions，不删除 repair/status/completion 状态账本，不改 run key，不改 sensor 触发逻辑。

## 2. 背景与问题

当前 Assets 页面中，股票分钟线与 `gold_stk_mins_qfq_macd_kdj` 相关资产的 Status 刷新明显变慢。

只读审计结论：

1. latest materialization 查询很快，单个资产约 0.6ms。
2. 慢点集中在高基数 asset check / partition status 查询。
3. 治理前股票分钟线相关 `asset_check_executions` 接近 60 万行；P3C 完成后，正式 Dagster DB 中 `asset_check_executions` 总量约为 `427,099` 行，分钟线普通历史删除候选已归零。
4. 当前标准 `VACUUM` 已完成，只能回收 dead tuples 给表内复用，不能解决仍然活跃的大量历史 check / materialization event。

分钟线资产族天然高基数：

| 资产族 | 频度 / 资产数 | 分区数 | check 数 | 结果 |
| --- | ---: | ---: | ---: | --- |
| raw 分钟线 | 5 | 4,239 左右 | 7 | 高基数 |
| silver 分钟线 | 5 | 3,028 左右 | 10 | 高基数 |
| gold qfq 分钟线 | 7 | 3,028 左右 | native / derived 多个 | 高基数 |
| MACD/KDJ indicator | 7 | 3,028 左右 | 4 | 高基数 |
| MACD/KDJ state | 7 | 3,028 左右 | 2 | 高基数 |

这些历史 check 对证明历史数据曾经正确有价值，但对当前“继续每天更新和计算”不是必需状态。

## 3. 当前代码事实

### 3.1 日常 sensor 已不依赖全历史 Dagster check history

股票分钟线连续性和性能专项已经把日常热路径改为 bounded lake readiness：

1. `stock_mins_raw_sensor.py` 使用 `batch_raw_stk_mins_lake_readiness(...)`。
2. `stock_mins_silver_trade_day_sensor.py` 和 `stock_mins_silver_sensor.py` 使用 raw / silver batch lake readiness。
3. `stock_mins_qfq_daily_sensor.py` 使用 silver / adj factor / gold qfq batch readiness。
4. `stock_mins_qfq_factor_repair_sensor.py` 只在 gold qfq target ready 后读取 qfq factor repair status，且使用 `include_event_storage_ids=False`。
5. `gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor.py` 使用 qfq lake readiness，但仍在目标日期和上一 expected 日期附近读取 MACD/KDJ target/state readiness。
6. `gold_stk_mins_qfq_macd_kdj_repair_job_sensor.py` 读取 MACD/KDJ daily target readiness 和 repair completion gate，但不需要 2014 年以来所有普通历史 check。

结论：删除 20 日窗口之前的普通分钟线 materialization / check event，不应影响日常 first-not-ready、补洞、qfq daily、qfq factor repair、MACD/KDJ daily 的继续推进。

### 3.2 repair/status/completion check 是状态账本，不能删除

以下 check event 不能按普通历史日志处理：

| check | 当前用途 | 处理口径 |
| --- | --- | --- |
| `gold_stk_mins_qfq_factor_repair_plan_evaluated` | qfq factor repair metadata/status、upstream batch id、repair range、codes hash | 禁删 |
| `gold_stk_mins_qfq_macd_kdj_repair_completed_check` | MACD/KDJ repair completion gate、防重复、source upstream batch id | 禁删 |

这类 event 数量很小，但承载正式业务状态。无论分区是否早于最近 20 个交易日，都不得进入本专项删除候选。

### 3.3 dynamic partitions 不是日志，不能删除

`dynamic_partitions` 记录 Dagster 已注册的 partition key。删除后会影响 sensor、Launchpad、job partition、历史补洞和可运行范围。

本专项只删 event history，不删 dynamic partitions。

## 4. 保留策略

### 4.1 保留窗口

股票分钟线普通 event 默认统一保留最近 20 个 `cn_a_stock_mins_trade_days` 交易日。

这里的 keep window 表示“股票分钟线链路整体应保护的最近交易日窗口”，不是“某一层当前已经注册到哪天”。raw 当前可能已经注册到最新交易日，而 silver / qfq / MACD-KDJ 可能因为上游补洞或运行窗口暂时还没追上。retention 口径必须保护统一 expected/current 窗口，不能因为下游 partition 暂时未注册，就把这些日期排除在保护窗口之外。

当前只读审计窗口：

| partition set | keep start | keep end | count |
| --- | --- |
| `cn_a_stock_mins_trade_days` | 2026-05-26 | 2026-06-23 | 20 |

后续正式执行时必须重新计算最近 20 个交易日，不能硬编码上述日期。

### 4.2 保留对象

必须保留：

1. 最近 20 个交易日内的股票分钟线普通 materialization event。
2. 最近 20 个交易日内的股票分钟线普通 asset check event。
3. 每个资产的 latest materialization event，即使未来出现 latest partition 不在 keep20 的异常，也必须保留。
4. 每个资产 latest materialization 绑定的 latest checks。
5. `gold_stk_mins_qfq_factor_repair_plan_evaluated` 全部历史。
6. `gold_stk_mins_qfq_macd_kdj_repair_completed_check` 全部历史。
7. `runs`、`run_tags`、`dynamic_partitions`、`instigators` 等非 event-history 表。
8. 所有数据湖 Parquet 文件。

### 4.3 可删除对象

满足全部条件才可进入候选：

1. asset 属于股票分钟线资产族：
   - `raw_stk_mins_*`
   - `silver_stk_mins_*`
   - `gold_stk_mins_qfq_*`
   - `gold_stk_mins_qfq_macd_kdj_*`
   - `gold_stk_mins_qfq_macd_kdj_state_*`
2. event 或 check 的 `partition` 不在最近 20 个股票分钟线交易日内。
3. event 不是该 asset 的 latest materialization。
4. check 不是 latest materialization 绑定的 latest check。
5. check name 不是 repair/status/completion 禁删 check。
6. event 类型仅限：
   - `ASSET_MATERIALIZATION`
   - `ASSET_CHECK_EVALUATION`
7. 对应 `asset_event_tags` 可随被删 materialization / check event 一起删除。

第一阶段不删除：

1. `ASSET_MATERIALIZATION_PLANNED`
2. `ASSET_CHECK_EVALUATION_PLANNED`
3. `runs`
4. `run_tags`
5. 无法与候选 event 精确绑定的其它 event type

## 5. 候选规模与当前状态

### 5.1 P3C 执行前基线

基于 2026-06-23 P3B 执行后的 post dry-run，按“统一保留最近 20 个 `cn_a_stock_mins_trade_days`，删除更早普通分钟线 event”估算，P3C 执行前剩余候选为：

| 项 | 候选数量 |
| --- | ---: |
| check candidates | 466,333 |
| check evaluation event candidates | 466,333 |
| check event tag candidates | 0 |
| materialization candidates | 57,225 |
| materialization tag candidates | 66 |
| asset count | 31 |

按资产族拆分：

| 资产族 | check candidates | materialization candidates |
| --- | ---: | ---: |
| gold qfq | 168,560 | 21,070 |
| silver_stk_mins | 150,500 | 15,050 |
| raw_stk_mins | 147,273 | 21,105 |
| MACD/KDJ indicator | 0 | 0 |
| MACD/KDJ state | 0 | 0 |

这才是对分钟线 UI Status 慢有实质影响的清理量级。此前 P4 old-state 规则只清“同分区被后续 materialization 覆盖的旧状态”，不适合当前“历史分区只保留最近 20 日”的目标。

P2D 已清理 `gold_stk_mins_qfq_macd_kdj_state_120m` 的旧普通 event；P3A 已继续清理剩余 6 个 state 资产，因此 MACD/KDJ state 当前普通历史 event 候选已归零。P3B 已清理 7 个 MACD/KDJ indicator 资产，因此 MACD/KDJ indicator 当前普通历史 event 候选也已归零。

### 5.2 P3C 完成后状态

2026-06-23 P3C 已继续清理 `raw_stk_mins`、`silver_stk_mins`、`gold_stk_mins_qfq` 三个资产族。基于 P3C3 post dry-run `/private/tmp/stk_mins_event_history_retention_p3c3_gold_qfq_post_dry_run_20260623_235035.json`：

| 资产族 | check candidates | materialization candidates |
| --- | ---: | ---: |
| raw_stk_mins | 0 | 0 |
| silver_stk_mins | 0 | 0 |
| gold qfq | 0 | 0 |
| MACD/KDJ indicator | 0 | 0 |
| MACD/KDJ state | 0 | 0 |

当前 31 个股票分钟线资产的普通历史删除候选已经归零；剩余保留状态包括 latest state、最近 20 个 `cn_a_stock_mins_trade_days`、repair/status/completion 状态账本、runs/run_tags、dynamic partitions 和 planned events。

## 6. 安全断言

任何正式删除前，dry-run 必须输出并全部通过以下断言：

1. 候选 check 数、候选 materialization 数、候选 event log 数、候选 tag 数可对账。
2. 候选不包含 `cn_a_stock_mins_trade_days` 最近 20 个交易日。
3. 候选不包含任何 asset 的 latest materialization。
4. 候选不包含任何 latest materialization 绑定的 latest check。
5. 候选不包含 `gold_stk_mins_qfq_factor_repair_plan_evaluated`。
6. 候选不包含 `gold_stk_mins_qfq_macd_kdj_repair_completed_check`。
7. 候选不包含 `dynamic_partitions`。
8. 候选不包含 `runs` / `run_tags`。
9. 候选不包含 non-stk-mins 资产。
10. 候选不包含 running / queued run 相关 event。
11. 删除后 latest state 对账结果必须与删除前一致。
12. 正式删除前 `runs` 中 `QUEUED / STARTING / STARTED / CANCELING` 必须为 0；P3C 各阶段执行前后均已确认 active runs 为 0。

如果任何断言失败，必须停止，不允许“修补式删除”。

## 7. Dry-run SQL 口径

### 7.1 最近 20 个交易日

```sql
keep20 AS (
  SELECT partition
  FROM dynamic_partitions
  WHERE partitions_def_name = 'cn_a_stock_mins_trade_days'
  ORDER BY partition DESC
  LIMIT 20
)
SELECT min(partition), max(partition), count(*)
FROM keep20;
```

### 7.2 股票分钟线资产集合

正式 dry-run CLI 必须显式列出允许资产 key，或从当前 active definitions / catalog 中生成白名单后再对账。禁止只靠 `LIKE` 宽泛匹配生成删除候选。

正式保护窗口统一来自 `cn_a_stock_mins_trade_days`，不得按 silver/qfq/MACD-KDJ 当前 registered partition 尾部单独裁剪。

### 7.3 latest materialization 保护集合

```sql
WITH latest_asset_materializations AS (
  SELECT
    asset_key::text AS asset_key,
    max(id) AS latest_materialization_id
  FROM event_logs
  WHERE dagster_event_type = 'ASSET_MATERIALIZATION'
    AND asset_key::text IN (:stk_mins_asset_keys)
  GROUP BY asset_key::text
)
SELECT count(*) FROM latest_asset_materializations;
```

### 7.4 check 候选

```sql
WITH keep20 AS (...),
latest_asset_materializations AS (...),
check_candidates AS (
  SELECT ace.*
  FROM asset_check_executions ace
  LEFT JOIN keep20 k
    ON k.partition = ace.partition
  LEFT JOIN latest_asset_materializations lam
    ON lam.latest_materialization_id = ace.materialization_event_storage_id
  WHERE ace.asset_key::text IN (:stk_mins_asset_keys)
    AND ace.partition IS NOT NULL
    AND k.partition IS NULL
    AND lam.latest_materialization_id IS NULL
    AND ace.check_name NOT IN (
      'gold_stk_mins_qfq_factor_repair_plan_evaluated',
      'gold_stk_mins_qfq_macd_kdj_repair_completed_check'
    )
)
SELECT count(*) FROM check_candidates;
```

### 7.5 materialization 候选

```sql
WITH keep20 AS (...),
latest_asset_materializations AS (...),
materialization_candidates AS (
  SELECT el.*
  FROM event_logs el
  LEFT JOIN keep20 k
    ON k.partition = el.partition
  LEFT JOIN latest_asset_materializations lam
    ON lam.latest_materialization_id = el.id
  WHERE el.asset_key::text IN (:stk_mins_asset_keys)
    AND el.dagster_event_type = 'ASSET_MATERIALIZATION'
    AND el.partition IS NOT NULL
    AND k.partition IS NULL
    AND lam.latest_materialization_id IS NULL
)
SELECT count(*) FROM materialization_candidates;
```

## 8. 删除顺序

正式删除必须在完整备份后执行，并且每一批都在显式事务中完成。

推荐删除顺序：

1. 构造临时候选表。
2. 删除 check event 对应的 `asset_event_tags`。
3. 删除 `event_logs` 中候选 `ASSET_CHECK_EVALUATION`。
4. 删除 `asset_check_executions` 中候选 rows。
5. 删除 materialization event 对应的 `asset_event_tags`。
6. 删除 `event_logs` 中候选 `ASSET_MATERIALIZATION`。
7. `ANALYZE event_logs`。
8. `ANALYZE asset_check_executions`。
9. `ANALYZE asset_event_tags`。

第一阶段不执行：

1. `VACUUM FULL`
2. `REINDEX`
3. `pg_repack`
4. `CREATE EXTENSION`
5. run event 删除
6. planned event 删除

## 9. 推进阶段

### P0：方案冻结

目标：冻结“股票分钟线普通历史 event 只保留最近 20 个交易日”的口径。

验收：

1. 本文档通过 review。
2. 资产白名单、禁删 check、保留窗口、删除范围全部明确。
3. 用户确认历史 Dagster UI 不再要求展示 2014 年以来完整绿灯证明。

### P1：只读 dry-run 工具

目标：实现独立 dry-run CLI，不写 DB。

2026-06-23 已落地：

1. 新增分钟线专用 helper：`orchestrator.defs.bootstrap.stk_mins_event_history_retention`。
2. 新增分钟线专用 CLI：`orchestrator.defs.bootstrap.stk_mins_event_history_retention_cli dry-run`。
3. CLI 只暴露 `dry-run`，不提供 `apply`、`delete` 或任何写入入口。
4. 工具白名单固定为 31 个股票分钟线资产，保护窗口统一来自 `cn_a_stock_mins_trade_days` 最近 20 个交易日。
5. 本地测试已覆盖 SQL 只读、资产白名单、禁删 check、latest state 保护、active run 阻断和 keep window 异常阻断。
6. 正式 Dagster Postgres dry-run 已于 2026-06-23 执行完成；报告路径：
   `/private/tmp/stk_mins_event_history_retention_dry_run_20260623.json`。
7. dry-run 只读 Dagster Postgres，未删除 DB 行，未运行 `dg`，未触碰数据湖。

2026-06-23 正式只读 dry-run 结论：

| 项 | 结果 |
| --- | ---: |
| `should_stop` | `false` |
| running / queued run count | `0` |
| keep window | `2026-05-26` 至 `2026-06-23` |
| keep trade days | `20` |
| check candidates | `592,753` |
| check event candidates | `592,753` |
| check event tag candidates | `0` |
| materialization candidates | `99,365` |
| materialization tag candidates | `66` |
| protected check events | `314` |

按资产族拆分：

| 资产族 | check candidates | materialization candidates |
| --- | ---: | ---: |
| gold qfq | `168,560` | `21,070` |
| MACD/KDJ indicator | `84,280` | `21,070` |
| MACD/KDJ state | `42,140` | `21,070` |
| raw_stk_mins | `147,273` | `21,105` |
| silver_stk_mins | `150,500` | `15,050` |

安全断言全部通过：

1. 无 running / queued runs。
2. keep window 正好为 20 个 `cn_a_stock_mins_trade_days`。
3. 31 个股票分钟线资产都有 latest materialization state。
4. 31 个股票分钟线资产都有 latest check state。
5. latest materialization 均有 latest check state。
6. 候选 checks / materializations 均不包含 keep window partition。
7. 候选 checks 不包含 latest materialization 绑定 checks。
8. 候选 materializations 不包含 latest materialization。
9. 候选 checks 不包含 protected status checks。
10. 候选 checks / materializations 均有 partition key。
11. 候选 check event 都存在且 event type 为 `ASSET_CHECK_EVALUATION`。

输出：

1. `/private/tmp/stk_mins_event_history_retention_dry_run_<timestamp>.json`
2. 候选 check/event/materialization/tag 数量。
3. 按资产族、资产、check name 拆分。
4. 保护集合样本。
5. 风险集合样本。
6. 所有安全断言。

验收：

1. dry-run 不写 Dagster DB。
2. dry-run 不触碰数据湖。
3. dry-run 不运行 `dg`。
4. 候选数量与 SQL 原型量级一致。
5. 安全断言全部为 0。

### P2：小样本删除

目标：选择一个低风险分钟线资产做 sample deletion，验证 UI 和后续 readiness 不受影响。

样本资产已固定为：

1. `gold_stk_mins_qfq_macd_kdj_state_120m`

选择依据：

1. 不选 repair/status check asset。
2. 不选当前正在恢复或关注的 target asset。
3. 候选量适中，足以验证 SQL 和 UI 效果。

2026-06-23 已完成 P2A / P2B 本地落地：

1. 新增 P2 专用 sample-delete helper：
   `orchestrator.defs.bootstrap.stk_mins_event_history_retention_sample_delete`。
2. 新增 P2 专用 CLI：
   `orchestrator.defs.bootstrap.stk_mins_event_history_retention_sample_delete_cli sample-delete`。
3. P1 `dry-run` CLI 继续保持只读，不暴露 apply/delete。
4. P2 sample-delete 必须显式传入或默认使用单个样本资产，禁止多资产、禁止非 31 个股票分钟线白名单资产。
5. P2 sample-delete 必须带 `--confirm-sample-delete` 才允许写 DB。
6. 删除候选继续复用 P1 keep20 / latest state / protected checks 规则。
7. 删除在单个显式事务内执行，顺序固定：
   - old check event 的 `asset_event_tags`
   - old `ASSET_CHECK_EVALUATION` in `event_logs`
   - old `asset_check_executions`
   - old materialization event 的 `asset_event_tags`
   - old `ASSET_MATERIALIZATION` in `event_logs`
8. 提交前重新执行 safety assertions；任一断言失败则 rollback。
9. 本地单元测试和静态门禁覆盖确认参数、单资产限制、白名单限制、protected checks 保护、latest 保护、事务 rollback 和删除顺序。

2026-06-23 已完成 P2C / P2D 正式 sample deletion：

1. P2C 正式只读 dry-run 报告：
   `/private/tmp/stk_mins_event_history_retention_p2c_dry_run_20260623_222543.json`。
2. P2C 完整备份：
   `/private/tmp/goldenshare_dagster_stk_mins_retention_p2c_backup_20260623_222543.dump`，大小约 `2.1G`，且 `pg_restore --list` 已验证可读。
3. P2D sample-delete 报告：
   `/private/tmp/stk_mins_event_history_retention_p2d_sample_delete_20260623_223700.json`。
4. P2D post dry-run 报告：
   `/private/tmp/stk_mins_event_history_retention_p2d_post_dry_run_20260623_223700.json`。
5. P2D 仅处理样本资产 `gold_stk_mins_qfq_macd_kdj_state_120m`。
6. P2D 删除结果：
   - `ASSET_CHECK_EVALUATION` event：`6020`
   - `asset_check_executions` rows：`6020`
   - `ASSET_MATERIALIZATION` event：`3010`
   - `asset_event_tags` rows：`0`
7. P2D post dry-run 确认：
   - `should_stop=false`
   - active runs = `0`
   - 样本资产候选已归零
   - 样本资产 latest materialization id 仍为 `6533625`
   - 样本资产 latest partition 仍为 `2026-06-18`
   - 样本资产 latest checks 仍为 `2`
   - protected checks 数量仍为 `314`

P2D 之后 Dagster DB 已发生正式删除动作，因此后续 P3 正式执行前必须重新备份，不能只依赖 P2C 备份。

验收：

1. 删除前完整备份 Dagster Postgres。
2. 删除后 latest materialization / latest checks 不变。
3. 最近 20 个交易日保留。
4. sensor 只读状态正常。
5. Assets 页面对应资产 Status 可正常显示。

### P3：分阶段扩大删除范围

P3 不直接进入五大资产族全量删除。P3A 先只处理 P2D 后剩余的 MACD/KDJ state 6 个资产，继续使用已验证的单资产 sample-delete 路径，逐资产串行执行。

#### P3A：MACD/KDJ state 剩余 6 个资产

P3A 白名单固定为：

1. `gold_stk_mins_qfq_macd_kdj_state_1m`
2. `gold_stk_mins_qfq_macd_kdj_state_5m`
3. `gold_stk_mins_qfq_macd_kdj_state_15m`
4. `gold_stk_mins_qfq_macd_kdj_state_30m`
5. `gold_stk_mins_qfq_macd_kdj_state_60m`
6. `gold_stk_mins_qfq_macd_kdj_state_90m`

已在 P2D 清理完成的 `gold_stk_mins_qfq_macd_kdj_state_120m` 不再进入 P3A。

P3A 执行前候选规模：

| 项 | 数量 |
| --- | ---: |
| check candidates | 36,120 |
| materialization candidates | 18,060 |
| check event tags | 0 |
| materialization event tags | 0 |

按单个资产估算，每个 state 资产约清理 `6020` 条 check event / check execution 和 `3010` 条 materialization event。

P3A 执行方式：

1. 保守复用现有 `stk_mins_event_history_retention_sample_delete_cli sample-delete`。
2. 逐资产串行执行 6 次，每次只传 1 个 `--sample-asset`。
3. 每个资产单独事务、单独输出报告、单独验收。
4. 任一资产失败立即停止，不继续执行后续资产。
5. 不新增 P3A 专用批量删除 SQL；避免在已验证 sample-delete 之外引入新删除路径。

P3A 正式执行前必须重新做：

1. active runs = `0`，查询 `runs` 中 `QUEUED / STARTING / STARTED / CANCELING` 必须为 0。
2. 重新完整备份 Dagster Postgres。因为 P2D 已改变 DB，P3A 不只依赖 P2C 备份。
3. 保存 P3A pre dry-run 报告，例如：
   `/private/tmp/stk_mins_event_history_retention_p3a_pre_dry_run_<timestamp>.json`。
4. pre dry-run 必须满足：
   - `should_stop=false`
   - keep window 仍来自最近 20 个 `cn_a_stock_mins_trade_days`
   - P3A 执行白名单只包含上述 6 个 state 资产；全局 dry-run 中其它资产族候选只记录，不在 P3A 删除
   - 上述 6 个 state 资产候选量与预期对齐
   - 候选不包含 keep20
   - 候选不包含 latest materialization
   - 候选不包含 latest materialization 绑定 checks
   - 候选不包含 protected checks

P3A 正式执行后必须做 post dry-run：

1. 保存 P3A post dry-run 报告，例如：
   `/private/tmp/stk_mins_event_history_retention_p3a_post_dry_run_<timestamp>.json`。
2. `macd_kdj_state` 资产族候选应归零：
   - check candidates = `0`
   - materialization candidates = `0`
3. latest / protected / keep20 安全断言继续全绿。
4. active runs 仍为 `0`。
5. protected checks 数量保持不变。
6. 若当时无法启动 Dagster UI / daemon，只允许把 UI 抽查延后；DB 层 dry-run 和 latest-state 对账仍是 P3A 的硬验收。

2026-06-23 已完成 P3A 正式执行：

1. P3A 重新备份：
   `/private/tmp/goldenshare_dagster_stk_mins_retention_p3a_backup_20260623_225055.dump`，大小约 `2.1G`，且 `pg_restore --list` 已验证可读。
2. P3A pre dry-run 报告：
   `/private/tmp/stk_mins_event_history_retention_p3a_pre_dry_run_20260623_225055.json`。
3. P3A sample-delete 报告：
   - `/private/tmp/stk_mins_event_history_retention_p3a_gold_stk_mins_qfq_macd_kdj_state_1m_20260623_225055.json`
   - `/private/tmp/stk_mins_event_history_retention_p3a_gold_stk_mins_qfq_macd_kdj_state_5m_20260623_225055.json`
   - `/private/tmp/stk_mins_event_history_retention_p3a_gold_stk_mins_qfq_macd_kdj_state_15m_20260623_225055.json`
   - `/private/tmp/stk_mins_event_history_retention_p3a_gold_stk_mins_qfq_macd_kdj_state_30m_20260623_225055.json`
   - `/private/tmp/stk_mins_event_history_retention_p3a_gold_stk_mins_qfq_macd_kdj_state_60m_20260623_225055.json`
   - `/private/tmp/stk_mins_event_history_retention_p3a_gold_stk_mins_qfq_macd_kdj_state_90m_20260623_225055.json`
4. P3A post dry-run 报告：
   `/private/tmp/stk_mins_event_history_retention_p3a_post_dry_run_20260623_225055.json`。
5. P3A 删除结果：
   - `ASSET_CHECK_EVALUATION` event：`36,120`
   - `asset_check_executions` rows：`36,120`
   - `ASSET_MATERIALIZATION` event：`18,060`
   - `asset_event_tags` rows：`0`
6. P3A post dry-run 确认：
   - `should_stop=false`
   - active runs = `0`
   - MACD/KDJ state 资产族候选已归零
   - latest / protected / keep20 安全断言继续全绿
   - protected checks 数量仍为 `314`
   - `dynamic_partitions` 行数仍为 `30,564`

P3A 只完成 MACD/KDJ state 资产族清理，不自动进入 P3B。

#### P3B：MACD/KDJ indicator 7 个资产

P3B 白名单固定为：

1. `gold_stk_mins_qfq_macd_kdj_1m`
2. `gold_stk_mins_qfq_macd_kdj_5m`
3. `gold_stk_mins_qfq_macd_kdj_15m`
4. `gold_stk_mins_qfq_macd_kdj_30m`
5. `gold_stk_mins_qfq_macd_kdj_60m`
6. `gold_stk_mins_qfq_macd_kdj_90m`
7. `gold_stk_mins_qfq_macd_kdj_120m`

2026-06-23 已完成 P3B 正式执行：

1. P3B 重新备份：
   `/private/tmp/goldenshare_dagster_stk_mins_retention_p3b_backup_20260623_230802.dump`，大小约 `2.1G`，且 `pg_restore --list` 已验证可读。
2. P3B pre dry-run 报告：
   `/private/tmp/stk_mins_event_history_retention_p3b_pre_dry_run_20260623_230802.json`。
3. P3B sample-delete 报告：
   - `/private/tmp/stk_mins_event_history_retention_p3b_gold_stk_mins_qfq_macd_kdj_1m_20260623_230802.json`
   - `/private/tmp/stk_mins_event_history_retention_p3b_gold_stk_mins_qfq_macd_kdj_5m_20260623_230802.json`
   - `/private/tmp/stk_mins_event_history_retention_p3b_gold_stk_mins_qfq_macd_kdj_15m_20260623_230802.json`
   - `/private/tmp/stk_mins_event_history_retention_p3b_gold_stk_mins_qfq_macd_kdj_30m_20260623_230802.json`
   - `/private/tmp/stk_mins_event_history_retention_p3b_gold_stk_mins_qfq_macd_kdj_60m_20260623_230802.json`
   - `/private/tmp/stk_mins_event_history_retention_p3b_gold_stk_mins_qfq_macd_kdj_90m_20260623_230802.json`
   - `/private/tmp/stk_mins_event_history_retention_p3b_gold_stk_mins_qfq_macd_kdj_120m_20260623_230802.json`
4. P3B post dry-run 报告：
   `/private/tmp/stk_mins_event_history_retention_p3b_post_dry_run_20260623_230802.json`。
5. P3B 删除结果：
   - `ASSET_CHECK_EVALUATION` event：`84,280`
   - `asset_check_executions` rows：`84,280`
   - `ASSET_MATERIALIZATION` event：`21,070`
   - `asset_event_tags` rows：`0`
6. P3B post dry-run 确认：
   - `should_stop=false`
   - active runs = `0`
   - MACD/KDJ indicator 资产族候选已归零
   - MACD/KDJ state 资产族候选仍为 `0`
   - latest / protected / keep20 安全断言继续全绿
   - protected checks 数量仍为 `314`
   - `dynamic_partitions` 行数仍为 `30,564`

P3B 只完成 MACD/KDJ indicator 资产族清理，不自动进入 P3C。

#### P3C：raw / silver / gold qfq 三族

P3C 拆成三个可单独停止的小阶段，继续沿用 P2D/P3A/P3B 已验证的 `sample-delete` 单资产路径，逐资产串行执行：

1. P3C1：`raw_stk_mins`，5 个资产。
2. P3C2：`silver_stk_mins`，5 个资产。
3. P3C3：`gold_stk_mins_qfq`，7 个资产。

2026-06-23 已完成 P3C1 raw 正式执行：

1. P3C1 重新备份：
   `/private/tmp/goldenshare_dagster_stk_mins_retention_p3c1_raw_backup_20260623_233138.dump`，大小约 `2.0G`，且 `pg_restore --list` 已验证可读。
2. P3C1 pre dry-run 报告：
   `/private/tmp/stk_mins_event_history_retention_p3c1_raw_pre_dry_run_20260623_233138.json`。
3. P3C1 sample-delete 报告：
   - `/private/tmp/stk_mins_event_history_retention_p3c1_raw_raw_stk_mins_1m_20260623_233138.json`
   - `/private/tmp/stk_mins_event_history_retention_p3c1_raw_raw_stk_mins_5m_20260623_233138.json`
   - `/private/tmp/stk_mins_event_history_retention_p3c1_raw_raw_stk_mins_15m_20260623_233138.json`
   - `/private/tmp/stk_mins_event_history_retention_p3c1_raw_raw_stk_mins_30m_20260623_233138.json`
   - `/private/tmp/stk_mins_event_history_retention_p3c1_raw_raw_stk_mins_60m_20260623_233138.json`
4. P3C1 post dry-run 报告：
   `/private/tmp/stk_mins_event_history_retention_p3c1_raw_post_dry_run_20260623_233138.json`。
5. P3C1 删除结果：
   - `ASSET_CHECK_EVALUATION` event：`147,273`
   - `asset_check_executions` rows：`147,273`
   - `ASSET_MATERIALIZATION` event：`21,105`
   - `asset_event_tags` rows：`66`
6. P3C1 post dry-run 确认：
   - `should_stop=false`
   - active runs = `0`
   - raw_stk_mins 资产族候选已归零
   - MACD/KDJ state / indicator 资产族候选仍为 `0`
   - latest / protected / keep20 安全断言继续全绿
   - protected checks 数量仍为 `314`
   - `dynamic_partitions` 行数仍为 `30,564`

2026-06-23 已完成 P3C2 silver 正式执行：

1. P3C2 重新备份：
   `/private/tmp/goldenshare_dagster_stk_mins_retention_p3c2_silver_backup_20260623_234053.dump`，大小约 `2.0G`，且 `pg_restore --list` 已验证可读。
2. P3C2 pre dry-run 报告：
   `/private/tmp/stk_mins_event_history_retention_p3c2_silver_pre_dry_run_20260623_234053.json`。
3. P3C2 sample-delete 报告：
   - `/private/tmp/stk_mins_event_history_retention_p3c2_silver_silver_stk_mins_1m_20260623_234053.json`
   - `/private/tmp/stk_mins_event_history_retention_p3c2_silver_silver_stk_mins_5m_20260623_234053.json`
   - `/private/tmp/stk_mins_event_history_retention_p3c2_silver_silver_stk_mins_15m_20260623_234053.json`
   - `/private/tmp/stk_mins_event_history_retention_p3c2_silver_silver_stk_mins_30m_20260623_234053.json`
   - `/private/tmp/stk_mins_event_history_retention_p3c2_silver_silver_stk_mins_60m_20260623_234053.json`
4. P3C2 post dry-run 报告：
   `/private/tmp/stk_mins_event_history_retention_p3c2_silver_post_dry_run_20260623_234053.json`。
5. P3C2 删除结果：
   - `ASSET_CHECK_EVALUATION` event：`150,500`
   - `asset_check_executions` rows：`150,500`
   - `ASSET_MATERIALIZATION` event：`15,050`
   - `asset_event_tags` rows：`0`
6. P3C2 post dry-run 确认：
   - `should_stop=false`
   - active runs = `0`
   - silver_stk_mins 资产族候选已归零
   - raw_stk_mins 资产族候选仍为 `0`
   - MACD/KDJ state / indicator 资产族候选仍为 `0`
   - latest / protected / keep20 安全断言继续全绿
   - protected checks 数量仍为 `314`
   - `dynamic_partitions` 行数仍为 `30,564`

2026-06-23 已完成 P3C3 gold qfq 正式执行：

1. P3C3 重新备份：
   `/private/tmp/goldenshare_dagster_stk_mins_retention_p3c3_gold_qfq_backup_20260623_235035.dump`，大小约 `2.0G`，且 `pg_restore --list` 已验证可读。
2. P3C3 pre dry-run 报告：
   `/private/tmp/stk_mins_event_history_retention_p3c3_gold_qfq_pre_dry_run_20260623_235035.json`。
3. P3C3 sample-delete 报告：
   - `/private/tmp/stk_mins_event_history_retention_p3c3_gold_qfq_gold_stk_mins_qfq_1m_20260623_235035.json`
   - `/private/tmp/stk_mins_event_history_retention_p3c3_gold_qfq_gold_stk_mins_qfq_5m_20260623_235035.json`
   - `/private/tmp/stk_mins_event_history_retention_p3c3_gold_qfq_gold_stk_mins_qfq_15m_20260623_235035.json`
   - `/private/tmp/stk_mins_event_history_retention_p3c3_gold_qfq_gold_stk_mins_qfq_30m_20260623_235035.json`
   - `/private/tmp/stk_mins_event_history_retention_p3c3_gold_qfq_gold_stk_mins_qfq_60m_20260623_235035.json`
   - `/private/tmp/stk_mins_event_history_retention_p3c3_gold_qfq_gold_stk_mins_qfq_90m_20260623_235035.json`
   - `/private/tmp/stk_mins_event_history_retention_p3c3_gold_qfq_gold_stk_mins_qfq_120m_20260623_235035.json`
4. P3C3 post dry-run 报告：
   `/private/tmp/stk_mins_event_history_retention_p3c3_gold_qfq_post_dry_run_20260623_235035.json`。
5. P3C3 删除结果：
   - `ASSET_CHECK_EVALUATION` event：`168,560`
   - `asset_check_executions` rows：`168,560`
   - `ASSET_MATERIALIZATION` event：`21,070`
   - `asset_event_tags` rows：`0`
6. P3C3 post dry-run 确认：
   - `should_stop=false`
   - active runs = `0`
   - raw_stk_mins / silver_stk_mins / gold qfq 候选均已归零
   - MACD/KDJ state / indicator 候选仍为 `0`
   - 全部 31 个股票分钟线资产普通历史候选已归零
   - latest / protected / keep20 安全断言继续全绿
   - protected checks 数量仍为 `314`
   - `dynamic_partitions` 行数仍为 `30,564`

P3C 完成后，不再有股票分钟线普通历史 event 删除候选。下一步只允许进入 P4 标准 `VACUUM (VERBOSE, ANALYZE)`，不新增删除范围。

### P4：P3 后标准 VACUUM

目标：只执行标准 `VACUUM (VERBOSE, ANALYZE)`，让 dead tuples 可复用并更新统计。

禁止：

1. 不执行 `VACUUM FULL`。
2. 不期待磁盘文件立刻明显变小。
3. 不把 P4 扩展成新的删除阶段。

### P5：增量治理设计

目标：避免未来继续按当前速度增长。

待讨论问题：

1. 哪些分钟线 checks 必须长期作为 Dagster asset check 写入？
2. 哪些 checks 可以只保留最近 20 个交易日？
3. 哪些 checks 应转为 lake readiness / DuckDB SQL，不再长期写 Dagster DB？
4. bootstrap / repair / historical refresh 是否默认不补全所有普通 check event？
5. 是否需要周期性自动 retention job，还是继续人工审批执行？

## 10. 风险

### 10.1 历史 UI 证明能力下降

删除后，Dagster UI 不再完整显示 20 日窗口之前的分钟线历史 materialization / check 绿灯。

可接受原因：用户已确认不要求 Dagster UI 保存 2014 年以来完整证明；数据湖文件本身仍保留。

### 10.2 历史 run 详情不完整

本专项第一阶段不删除 runs，也不删除 planned event。但如果删除 materialization/check event，历史 run 页面中与这些 event 相关的细节会减少。

可接受原因：目标是保护当前状态和未来更新，不再完整保存历史运行证明。

### 10.3 删除 SQL 误伤 latest state

这是最大风险。

控制方式：

1. latest materialization 保护集合。
2. latest materialization 绑定 checks 保护集合。
3. 最近 20 个交易日保护集合。
4. 禁删 check name 保护集合。
5. 事务提交前安全断言。
6. 删除前完整备份。

### 10.4 删除后 UI 仍慢

如果 P3 后 UI 仍慢，说明剩余瓶颈可能来自：

1. planned events。
2. run event history。
3. GraphQL 查询模型。
4. Postgres 索引/统计。
5. 其它非分钟线高基数 check。

此时应进入 Run Event History Retention 或 Asset Check 增量治理，不在本专项继续扩大删除范围。

## 11. 验收标准

本专项完成后必须满足：

1. 股票分钟线普通历史 event 仅保留最近 20 个交易日和 latest state。
2. 数据湖文件不变。
3. dynamic partitions 不变。
4. protected repair/status checks 不变。
5. 最新分钟线 asset status 不变。
6. 后续每日 raw/silver/qfq/MACD-KDJ 更新不受影响。
7. Assets 页面中分钟线和 MACD/KDJ 相关 Status 刷新性能有明显改善，至少不再被 2014 年以来全量 check 历史拖累。
8. 删除前后 dry-run 报告、SQL 日志、VACUUM 日志和验证结果全部保存在 `/private/tmp` 或后续指定归档路径。
