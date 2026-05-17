# 日期对象矩阵审计性能与可观测性专项优化方案 v1

- 状态：M0/M1 已进入落地；M2 及以后待评审/排期
- 更新时间：2026-05-17
- 适用范围：`ops` 审查中心 `date_subject_matrix` 对象矩阵完整性审计
- 关联文档：
  - [数据集日期完整性审计设计 v2](/Users/congming/github/goldenshare/docs/ops/dataset-date-completeness-audit-design-v2.md)
  - [数据集日期对象矩阵完整性审计方案 v1](/Users/congming/github/goldenshare/docs/ops/dataset-subject-completeness-audit-plan-v1.html)

---

## 1. 背景

2026-05-17 在生产环境手动创建 `stk_factor_pro` 对象矩阵审计任务时，出现长时间无结果、页面只显示 `running / reading_actual`、无任何进度输出的问题。

本次远程核查事实：

| 项 | 结果 |
|---|---|
| run_id | `29` |
| dataset_key | `stk_factor_pro` |
| 审计范围 | `2025-01-02 ~ 2026-05-15` |
| 交易日数量 | `328` |
| 预估对象矩阵 cell | `1,778,629` |
| 目标表范围内行数 | `1,823,978` |
| 运行表现 | 超过 77 分钟未完成，最终人工取消 |
| 取消方式 | `pg_cancel_backend` 取消 PostgreSQL 活跃 SQL |
| 最终状态 | `failed / error`，错误为 `QueryCanceled` |

本问题不影响业务数据表读写，但会影响审查中心可用性，并可能长期占用数据库资源。

---

## 2. 问题定义

本专项只解决问题 2：对象矩阵审计效率与可观测性。

不在本专项解决：

1. 停牌、上市首日、源端不产出等对象矩阵口径问题。
2. `DatasetDefinition.completeness` 的对象池语义重设计。
3. 审计页面交互大改。
4. 普通 `date_bucket` 日期桶审计重构。
5. TaskRun、freshness、dataset status snapshot 等其他 Ops 主链路调整。

对象池口径问题将作为后续独立专项处理。

---

## 3. 当前实现问题

### 3.1 执行方式不可控

当前 `SubjectCompletenessMatrixExecutor` 采用全范围 CTE 方式：

1. 生成全范围 `expected_buckets`。
2. 基于 `security_serving` 与生命周期规则生成全范围 `expected_matrix`。
3. 从目标表生成全范围 `actual_matrix`。
4. 通过 join / anti join 计算 covered 与 missing。
5. 最后一次性写入 run 汇总、gap summary、gap detail。

问题：

1. 单条 SQL 查询时间不可控。
2. 无法在日期桶维度中断或恢复。
3. 数据库执行期间页面无法知道已处理到哪里。
4. 大查询被取消后，只能得到一个巨大的 SQL 错误，不利于运营理解。

### 3.2 重复执行大矩阵

当前 executor 为了读取：

1. summary
2. gap summaries
3. details

会重复构造和执行相似的矩阵 CTE。对 `stk_factor_pro` 这类宽表和长范围审计，这是主要浪费来源之一。

### 3.3 宽表读取路径不理想

对象矩阵审计只需要目标表的两个字段：

1. `trade_date`
2. `ts_code`

但 `core_serving.equity_factor_pro` 是宽表。当前索引包括：

| 索引 | 说明 |
|---|---|
| `pk_equity_factor_pro (ts_code, trade_date)` | 主键，适合按股票查日期 |
| `idx_equity_factor_pro_trade_date (trade_date)` | 可按日期定位，但不能覆盖 `ts_code` |
| `idx_equity_factor_pro_ts_code_trade_date (ts_code, trade_date)` | 与主键方向接近 |

审计按日期桶查实际覆盖，更需要 `(trade_date, ts_code)` 覆盖索引，以避免从宽表 heap 读取不必要字段。

### 3.4 无进度与心跳

当前 `ops.dataset_date_completeness_run` 只有：

1. `current_stage`
2. 汇总计数字段

这些字段只有阶段级含义。大 SQL 执行期间：

1. `current_stage` 长时间停留在 `reading_actual`。
2. `expected_cell_count` 等汇总字段仍为 0。
3. 页面无法展示当前日期、已处理桶数、预计总桶数。
4. worker 日志只有整轮完成后才输出。

---

## 4. 优化目标

### 4.1 第一层：止血和可控

目标是让对象矩阵审计不会再出现“一个任务无输出跑一小时”的状态。

必须实现：

1. 大范围审计按日期桶或小窗口分批执行。
2. 每批处理后写入 heartbeat 与进度。
3. 页面能够展示至少以下信息：
   - 当前阶段
   - 当前日期桶
   - 已处理日期桶数
   - 总日期桶数
   - 已发现缺失 cell 数
   - 最后心跳时间
4. 单桶或单批 SQL 必须有 statement timeout。
5. worker 取消或 SQL 取消后，run 必须收敛为 `failed/error` 或 `canceled`，不能永久 `running`。

### 4.2 第二层：真正提速

目标是让 `stk_factor_pro` 这类大数据集的年度范围审计进入可接受时间。

预期目标：

| 阶段 | 目标耗时 |
|---|---|
| M1 止血版 | 不再长时间无进度；可接受 10~30 分钟 |
| M2 提速版 | 1~5 分钟 |
| M3 索引与 SQL 收敛后 | 30 秒~2 分钟 |

提速来源：

1. 避免重复执行全范围大 CTE。
2. 按日期桶读取轻量键集合。
3. 使用 `(trade_date, ts_code)` 覆盖索引。
4. 只写必要 summary/detail，不无限制写缺失明细。
5. 对大范围审计采用批量提交与可观测进度。

---

## 5. 目标执行模型

### 5.1 当前模型

```text
run
  -> 一次性生成全范围 expected_matrix
  -> 一次性生成全范围 actual_matrix
  -> 一次性计算 summary
  -> 再次计算 gap summary
  -> 再次计算 detail
  -> 一次性写结果
```

### 5.2 目标模型

```text
run
  -> plan expected buckets
  -> 初始化进度
  -> for bucket in expected_buckets:
       -> 生成当日 expected subjects
       -> 读取当日 actual subjects
       -> SQL 内计算当日 missing subjects
       -> 写入当日 gap summary
       -> 按全局 detail limit 写入样本 detail
       -> 更新 run 进度与 heartbeat
       -> 每 N 个 bucket commit
  -> 汇总最终 run counters
  -> 标记 succeeded/failed
```

说明：

1. 仍保持审计只读业务表。
2. 仍写入现有审计结果表。
3. 不把对象池口径问题混入本轮。
4. 第一版可以只支持 `subject_kind=stock`、单字段 `ts_code`，与当前实现一致。

---

## 6. 建议数据模型调整

### 6.1 run 主表新增进度字段

表：`ops.dataset_date_completeness_run`

| 字段 | 类型 | 含义 |
|---|---|---|
| `processed_bucket_count` | int | 已处理日期桶数 |
| `current_bucket_value` | date nullable | 当前正在处理或最近完成的日期桶 |
| `current_bucket_label` | varchar(64) nullable | 当前桶展示标签 |
| `progress_message` | text nullable | 给运营看的进度说明 |
| `heartbeat_at` | timestamptz nullable | 最近一次 worker 心跳时间 |

字段原则：

1. 这些字段只表示审计执行进度，不参与结论判断。
2. 审计失败时保留最后进度，便于定位。
3. 普通 `date_bucket` 审计可以不写这些字段，保持兼容。

### 6.2 不新增业务表

本专项不新增业务数据表，不改 `raw_*`、`core_*`、`core_serving*`。

### 6.3 暂不新增 subject exclusion 表

停牌、上市首日等 subject-cell 级规则排除属于对象池口径专项。本专项只预留执行结构，不在本轮新增：

1. `dataset_subject_completeness_exclusion`
2. `subject_applicability_rule`
3. 人工确认白名单

---

## 7. SQL 执行策略

### 7.1 单桶差集 SQL

每个日期桶只查询当天键集合：

```sql
with expected as (
  select
    s.ts_code as subject_key,
    s.name as subject_name,
    s.list_date as lifecycle_start,
    s.delist_date as lifecycle_end
  from core_serving.security_serving s
  where s.ts_code is not null
    and s.list_status in ('L')
    and (s.list_date is null or s.list_date <= :bucket_value)
    and (s.delist_date is null or s.delist_date >= :bucket_value)
),
actual as (
  select distinct f.ts_code as subject_key
  from core_serving.equity_factor_pro f
  where f.trade_date = :bucket_value
    and f.ts_code is not null
),
missing as (
  select e.*
  from expected e
  left join actual a on a.subject_key = e.subject_key
  where a.subject_key is null
)
select
  (select count(*) from expected) as expected_count,
  (select count(*) from expected e join actual a on a.subject_key = e.subject_key) as covered_count,
  (select count(*) from missing) as missing_count;
```

细节查询可复用同一桶逻辑，仅在 `missing_count > 0` 且 detail 剩余额度大于 0 时读取样本。

### 7.2 全局 affected_subject_count

为了避免保存全部缺失 cell，本轮建议在 worker session 内创建临时表：

```sql
create temporary table audit_missing_subject_seen (
  subject_key varchar primary key
) on commit preserve rows;
```

每个桶将缺失 subject_key 去重插入临时表，最终：

```sql
select count(*) from audit_missing_subject_seen;
```

这样可以得到准确的 `affected_subject_count`，同时空间上限约等于对象池规模，而不是缺失 cell 总量。

### 7.3 detail 写入策略

沿用当前全局 detail limit，建议：

1. 每个 run 最多写入 `DETAIL_LIMIT` 条对象缺失 detail。
2. 每个日期桶最多写入 `per_bucket_detail_limit` 条，避免单日异常吃满全部 detail。
3. run 上设置 `detail_truncated=true` 表示 detail 被截断。

第一版可保持当前 `DETAIL_LIMIT=1000`，后续再根据页面体验调整。

### 7.4 事务与提交

推荐：

1. 每处理 `N` 个 bucket commit 一次，默认 `N=5` 或 `10`。
2. 每个 commit 前更新 run 进度和 heartbeat。
3. 若中途失败，已写入的部分 gap/detail 保留，run 标记为 `error`。
4. 新 run 不复用旧 run 结果，不做断点续跑。

说明：保留部分结果有利于诊断，但页面必须明确显示 run 为失败，不允许误认为审计结论。

### 7.5 statement timeout

对象矩阵审计 worker 应在每个单桶 SQL 前设置本地超时：

```sql
set local statement_timeout = '60s';
```

建议第一版：

| 场景 | timeout |
|---|---|
| 单桶 expected/actual/missing 统计 | 60s |
| 单桶 detail 采样 | 60s |
| 普通日期桶审计 | 暂不调整 |

若单桶超时，说明索引或口径存在问题，应失败并展示具体 bucket，不继续吞掉问题。

---

## 8. 索引策略

### 8.1 `stk_factor_pro` 建议索引

目标表：`core_serving.equity_factor_pro`

建议新增：

```sql
create index concurrently if not exists idx_equity_factor_pro_trade_date_ts_code
on core_serving.equity_factor_pro (trade_date, ts_code);
```

理由：

1. 对象矩阵审计按日期桶读取 `ts_code`。
2. 当前 `idx_equity_factor_pro_trade_date` 只能定位日期，不能覆盖 `ts_code`。
3. `stk_factor_pro` 是宽表，覆盖索引能减少 heap 读取。

### 8.2 索引 rollout 约束

1. 必须使用 concurrent index，避免长时间阻塞业务读写。
2. Alembic migration 必须先检查真实 head。
3. 生产执行前必须评估磁盘空间。
4. 索引创建失败不得影响现有数据。

### 8.3 其他数据集索引策略

后续每个 `date_subject_matrix` 数据集接入前，都必须确认目标表是否具备：

```text
(observed_field, actual_key_field)
```

方向的索引。

示例：

| 数据集 | 建议索引 |
|---|---|
| `daily` | `(trade_date, ts_code)` |
| `daily_basic` | `(trade_date, ts_code)` |
| `stk_limit` | `(trade_date, ts_code)` |
| `stk_factor_pro` | `(trade_date, ts_code)` |

若已有等价索引，可以不新增。

---

## 9. API 与前端展示调整

### 9.1 API 返回字段

`DateCompletenessRunItem` 建议新增：

| 字段 | 含义 |
|---|---|
| `processed_bucket_count` | 已处理桶数 |
| `current_bucket_value` | 当前或最近处理桶 |
| `current_bucket_label` | 展示标签 |
| `progress_message` | 进度说明 |
| `heartbeat_at` | 最近心跳 |

### 9.2 页面展示

审计记录列表和详情页至少展示：

```text
运行中：已处理 42 / 328 个日期桶，当前 2025-03-07，最后心跳 10:31:12
```

若 `heartbeat_at` 超过阈值未更新，例如 5 分钟：

```text
运行中但心跳滞后，请检查 worker 或数据库查询。
```

### 9.3 不做复杂 ETA

第一版不计算预计剩余时间。因为不同日期桶数据量、IO 状态、缓存状态差异明显，过早估算 ETA 容易误导。

---

## 10. 里程碑

### M0：现状止血与防误用（本轮落地）

目标：避免继续创建无上限大范围对象矩阵审计。

任务：

1. 文档标记 `date_subject_matrix` 当前不建议大范围运行。
2. API 或 service 层增加对象矩阵审计范围保护。
3. 若超过安全阈值，返回明确错误或要求后续由分批 worker 执行。
4. worker 执行前再次检查安全阈值，防止历史 queued run 或自动调度绕过手动创建保护。

建议阈值：

| 审计类型 | 第一版保护 |
|---|---|
| `date_bucket` | 不变 |
| `date_subject_matrix` | 超过 30 个日期桶先拒绝，待 M2 分桶执行后再评估放开 |

验收：

1. 大范围 `stk_factor_pro` 不会再直接进入长 SQL。
2. 页面能看到明确错误，而不是无限 running。

### M1：进度字段与 worker 心跳（本轮落地）

目标：先解决“看不到状态”的问题。

任务：

1. Alembic 新增 run 进度字段。
2. schema/query/API 返回进度字段。
3. 前端列表或详情展示进度字段。
4. worker 在进入对象矩阵审计时写入总桶数与 heartbeat。
5. 进度只覆盖更新 `ops.dataset_date_completeness_run` 当前 run 行，不新增进度流水表，避免行数无限膨胀。

验收：

1. 小窗口对象矩阵审计运行中能看到心跳。
2. worker 卡住时页面能看到心跳滞后。

### M2：按日期桶执行小闭环

目标：替换全范围大 CTE。

任务：

1. 新增 bucket-by-bucket 对象矩阵 executor。
2. 每个 bucket 独立统计 expected / covered / missing。
3. 每个 bucket 写入 gap summary。
4. 按全局 detail limit 写入 detail。
5. 每 N 个 bucket commit 一次。
6. 保持普通 `date_bucket` 审计路径不变。

验收：

1. `stk_factor_pro` 8 个交易日以内审计结果与旧逻辑一致。
2. 运行中能看到 processed bucket 递增。
3. 中途取消后 run 能收敛为 error/canceled。

### M3：覆盖索引与查询计划优化

目标：真正降低宽表读取成本。

任务：

1. 为 `core_serving.equity_factor_pro` 增加 `(trade_date, ts_code)` 索引。
2. 对 `daily`、`daily_basic`、`stk_limit` 检查是否已有等价索引。
3. 用 `EXPLAIN ANALYZE` 固化单桶查询性能基线。

验收：

1. `stk_factor_pro` 单桶查询命中合适索引。
2. 单桶统计查询稳定在秒级以内，目标为 100ms 以内。

### M4：恢复大范围审计能力

目标：在可观测、可取消、可控的基础上恢复年度范围审计。

任务：

1. 放开 M0 中的临时范围保护。
2. 对 `stk_factor_pro` 跑 `2025-01-02 ~ 2026-05-15` 范围。
3. 记录耗时、bucket 进度、最终结果。
4. 根据结果决定是否需要进一步优化对象池日快照。

验收：

1. 年度范围审计不再出现长时间无进度。
2. 目标总耗时进入 1~5 分钟；若加索引后仍超过 5 分钟，进入 M5。

### M5：可选的对象池日快照

目标：如果 M4 性能仍不达标，再考虑物化对象池。

说明：

1. 这是可选阶段，不应提前做。
2. 只有在 bucket-by-bucket 与覆盖索引仍不能满足性能目标时才进入。

候选方案：

```text
ops.dataset_subject_universe_snapshot
  dataset_key
  bucket_value
  subject_kind
  subject_key
  subject_name
  lifecycle_start
  lifecycle_end
  generated_at
```

风险：

1. 需要维护快照生成时机。
2. 对象池口径变更时需要重建。
3. 容易与 DatasetDefinition 事实源产生重复事实。

因此 M5 不是首选。

---

## 11. 测试与验证门禁

### 11.1 单元测试

必须覆盖：

1. 普通 `date_bucket` 审计不受影响。
2. `date_subject_matrix` 小窗口无缺失。
3. `date_subject_matrix` 小窗口有缺失。
4. detail limit 生效。
5. run 进度字段在处理中更新。
6. 单桶 SQL 出错时 run 收敛为 error。

### 11.2 API 测试

必须覆盖：

1. run 列表返回进度字段。
2. run 详情返回进度字段。
3. 大范围保护提示明确。
4. subject gaps 与 detail 查询保持兼容。

### 11.3 远程验证

按顺序执行：

1. `stk_factor_pro` 单日窗口。
2. `stk_factor_pro` 8 个交易日窗口。
3. `stk_factor_pro` 30 个交易日窗口。
4. `stk_factor_pro` 年度窗口。

每步必须记录：

1. 总耗时。
2. 最大单桶耗时。
3. processed bucket 进度是否正常。
4. missing / affected 结果是否可信。
5. 数据库是否出现长时间 active query。

---

## 12. 风险与回滚

### 12.1 风险

| 风险 | 影响 | 控制方式 |
---|---|---|
| 分批后汇总计数与旧逻辑不一致 | 审计结论不可信 | 小窗口新旧逻辑对照 |
| 新索引创建占用磁盘 | 影响生产空间 | 创建前检查磁盘，使用 concurrent |
| 进度频繁 commit 增加开销 | 吞吐下降 | 默认每 5~10 个桶 commit |
| detail 写入过多 | 结果表膨胀 | 全局 limit + 每桶 limit |
| 取消后留下部分结果 | 页面误读 | run_status 必须显示 error/canceled |

### 12.2 回滚

1. M1 字段新增可保留，不影响旧路径。
2. M2 executor 切换应保留旧 executor 类，但不作为默认路径；若新 executor 有问题，可通过代码回滚恢复旧逻辑。
3. M3 索引可单独 drop，不影响表数据。
4. 不涉及业务数据表写入，回滚不需要修复业务数据。

---

## 13. 下一步建议

建议按以下顺序推进：

1. 先做 M0 + M1：防止再次跑出无进度大任务。
2. 再做 M2：完成按日期桶执行小闭环。
3. 再做 M3：补 `stk_factor_pro` 覆盖索引并验证。
4. M4 前不要继续扩大对象矩阵数据集接入。
5. 对象池口径问题作为独立方案，在 M2/M3 稳定后再处理。
