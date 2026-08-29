# 日期对象矩阵审计性能与可观测性专项优化方案 v1

- 状态：M0/M1 已落地；M2 已落地；M3 只读评估已完成，暂不新增索引；M4 及以后待评审/排期
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

本专项的设计原则：

1. 能稳定复用的能力，沉淀为通用执行骨架。
2. 不能稳定复用的业务语义，不做硬抽象。
3. 第一版只覆盖当前已经存在的股票类 `trade_date × ts_code` 对象矩阵审计。
4. 后续如果要支持指数、ETF、基金、板块等对象池，必须单独补对象池 resolver 与语义评审，不允许假装所有对象池都可以共用股票生命周期规则。

不在本专项解决：

1. 停牌、上市首日、源端不产出等对象矩阵口径问题。
2. `DatasetDefinition.completeness` 的对象池语义重设计。
3. 审计页面交互大改。
4. 普通 `date_bucket` 日期桶审计重构。
5. TaskRun、freshness、dataset status snapshot 等其他 Ops 主链路调整。

对象池口径问题将作为后续独立专项处理。

### 2.1 当前第一版直接覆盖范围

当前代码中已经配置 `date_subject_matrix` 的数据集如下：

| 数据集 | 目标表 | 对象类型 | 对象池策略 | 对象键 |
|---|---|---|---|---|
| `adj_factor` | `core.equity_adj_factor` | `stock` | `stock_basic_active_lifecycle` | `ts_code` |
| `daily` | `core_serving.equity_daily_bar` | `stock` | `stock_basic_active_lifecycle` | `ts_code` |
| `daily_basic` | `core_serving.equity_daily_basic` | `stock` | `stock_basic_active_lifecycle` | `ts_code` |
| `stk_limit` | `raw_tushare.stk_limit` | `stock` | `stock_basic_active_lifecycle` | `ts_code` |
| `stk_factor_pro` | `core_serving.equity_factor_pro` | `stock` | `stock_basic_active_lifecycle` | `ts_code` |

M2 第一版只承诺覆盖以上 5 个数据集。它们共享的是“执行方式”，不是所有对象池业务语义。

`stk_limit` 已在 2026-08-30 的 raw 直出 M1 中把 Definition 审计目标改为 Raw；原 `core_serving.equity_stk_limit` 名称继续服务业务只读消费者，不再作为 completeness 的物理事实源。第 8.2 节保留 2026-05-17 对旧 Serving 物理表的历史性能证据，不将其改写成切换后的测量结果。

### 2.2 可通用与不可硬通用的边界

可通用能力：

1. 按日期桶循环执行，避免一次性构造全年大矩阵。
2. 单桶 expected / actual / missing 计算流程。
3. run 进度、heartbeat、当前桶、已处理桶数更新。
4. gap summary、gap detail 的写入节制与截断标记。
5. statement timeout、错误收敛、失败时保留最后进度。
6. API 与前端进度展示字段。

不可硬通用能力：

1. 对象池来源与生命周期规则。
2. 停牌、上市首日、源端不产出等业务排除语义。
3. 指数、ETF、基金、板块等非股票对象的有效对象池定义。
4. 每张目标表的索引选择与 SQL 性能门禁。
5. 是否需要对象池日快照。

因此，M2 的实现形态应是“小通用执行内核 + 显式对象池 resolver”，而不是一个覆盖所有对象类型的万能 DSL。

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
4. 第一版只支持 `subject_kind=stock`、单字段 `ts_code`，与当前实现一致。
5. 通用的是 executor 生命周期与分桶执行方式；对象池语义通过 resolver 显式接入，不在 executor 主流程里写死更多业务规则。

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

### 7.1 执行结构

M2 第一版拆成两层：

| 层 | 职责 | 是否通用 |
|---|---|---|
| 分桶执行内核（当前落在 `SubjectCompletenessMatrixExecutor` 内部） | 分桶循环、进度心跳、结果写入、错误收敛、detail limit | 通用 |
| 对象池读取逻辑（当前只实现 `stock_basic_active_lifecycle`） | 根据对象池策略读取某个日期桶应存在的对象集合 | 半通用，按策略实现 |
| 实际对象读取逻辑 | 根据目标表、日期字段、对象键读取某桶实际存在对象 | 通用，但依赖目标表索引 |

第一版只实现一个对象池 resolver：

| resolver | 支持对象 | 来源 | 规则 |
|---|---|---|---|
| `stock_basic_active_lifecycle` | 股票 | `core_serving.security_serving` | `list_status in active_status_values` 且 `list_date <= bucket_value <= delist_date` |

后续新增对象类型时，只允许新增 resolver，不允许把指数、基金、板块规则硬塞进股票 resolver。

### 7.2 单桶差集 SQL

每个日期桶只查询当天键集合。以下 SQL 是股票类 resolver 的第一版示意，不是所有对象池的通用 SQL：

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

### 7.3 全局 affected_subject_count

为了避免保存全部缺失 cell，M2 第一版不使用数据库临时表，而是在 worker 进程内用 Python `set` 记录缺失对象键。

这样做的原因：

1. 当前测试环境使用 SQLite，PostgreSQL 临时表不能作为主逻辑直接落地。
2. 当前第一版只覆盖股票对象池，去重对象规模约几千只，内存可控。
3. `affected_subject_count` 统计的是“出现过缺失的不同对象数”，用 `set` 可以准确表达该语义。

后续如果对象池规模显著变大，再单独评估 PostgreSQL 临时表或物化中间表方案；不得在 M2 第一版中引入数据库方言绑定。

### 7.4 detail 写入策略

沿用当前全局 detail limit，建议：

1. 每个 run 最多写入 `DETAIL_LIMIT` 条对象缺失 detail。
2. 每个日期桶最多写入 `per_bucket_detail_limit` 条，避免单日异常吃满全部 detail。
3. run 上设置 `detail_truncated=true` 表示 detail 被截断。

第一版保持当前代码口径 `DETAIL_LIMIT=5000`，不在本轮改变 detail 截断行为。

### 7.5 事务与提交

推荐：

1. M2 第一版每处理 1 个 bucket commit 一次，优先保证页面进度与故障定位可见。
2. 每个 bucket commit 前更新 run 进度和 heartbeat。
3. 若中途失败，已写入的部分 gap/detail 保留，run 标记为 `error`。
4. 新 run 不复用旧 run 结果，不做断点续跑。

说明：保留部分结果有利于诊断，但页面必须明确显示 run 为失败，不允许误认为审计结论。

### 7.6 statement timeout

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

### 8.1 覆盖索引含义

本方案里说的覆盖索引，指目标表上能同时满足：

1. 用 `trade_date` 快速定位某个日期桶。
2. 直接从索引里读出 `ts_code`。

也就是：

```text
(trade_date, ts_code)
```

它和现有主键方向不同：

1. `(ts_code, trade_date)` 适合“先给股票，再查日期”。
2. `(trade_date, ts_code)` 适合“先给日期桶，再查该日有哪些股票”。

对象矩阵审计属于第二种访问方式。

在 PostgreSQL 中，如果可见性条件满足，这类索引还有机会让查询走 index-only scan，减少回表读取；即使不能完全 index-only，也能减少宽表读取压力。

### 8.2 M3 只读评估结论

评估日期：2026-05-17

评估库：生产库，只读 `EXPLAIN (ANALYZE, BUFFERS)`

评估日期桶：`2026-05-15`

当前 5 个 `date_subject_matrix` 数据集的单桶查询都已进入毫秒级。M3 本轮结论是：**先不新增索引，继续使用 M2 分桶执行结果观察真实年度任务耗时**。

| 数据集 | 目标表 | 当前大小 | 现有访问路径 | 单表实际对象读取 | 单桶完整矩阵查询 | 判断 |
|---|---|---:|---|---:|---:|---|
| `adj_factor` | `core.equity_adj_factor` | 2028 MB | `idx_equity_adj_factor_trade_date` + heap | 3.237 ms | 16.431 ms | 当前不加索引 |
| `daily` | `core_serving.equity_daily_bar` | 3468 MB | `idx_equity_daily_bar_trade_date` + heap | 3.399 ms | 16.517 ms | 当前不加索引 |
| `daily_basic` | `core_serving.equity_daily_basic` | 4320 MB | `idx_equity_daily_basic_trade_date` + heap | 3.543 ms | 16.885 ms | 当前不加索引 |
| `stk_limit` | `core_serving.equity_stk_limit` | 541 MB | `idx_equity_stk_limit_trade_date` + heap | 5.081 ms | 18.782 ms | 当前不加索引 |
| `stk_factor_pro` | `core_serving.equity_factor_pro` | 5131 MB | `idx_equity_factor_pro_trade_date` + heap | 6.460 ms | 19.529 ms | 暂不立即加索引，保留为候选 |

说明：

1. `stk_factor_pro` 的确是最需要关注的表。单日实际对象读取用了 `Bitmap Heap Scan`，访问 `2077` 个 heap block，说明 `(trade_date, ts_code)` 覆盖索引仍有优化价值。
2. 但当前 M2 单桶完整矩阵查询已经约 `20ms`，即使按年度 `328` 个交易日粗略估算，数据库读取部分也不再是“一小时级”瓶颈。
3. 新增索引会增加磁盘占用、写入维护成本和建索引过程的生产风险，因此本轮不应因为“看起来更完整”而直接加。
4. 下一步应先部署并运行 M2 分桶执行，用真实 run 耗时判断是否还需要 M3-B 索引落地。

### 8.3 索引 rollout 约束

1. 必须使用 concurrent index，避免长时间阻塞业务读写。
2. Alembic migration 必须先检查真实 head。
3. 生产执行前必须评估磁盘空间。
4. 索引创建失败不得影响现有数据。

如果 M2 部署后 `stk_factor_pro` 年度审计仍明显超过目标耗时，再单独进入 M3-B，候选 SQL 为：

```sql
create index concurrently if not exists idx_equity_factor_pro_trade_date_ts_code
on core_serving.equity_factor_pro (trade_date, ts_code);
```

### 8.4 其他数据集索引策略

后续每个 `date_subject_matrix` 数据集接入前，都必须按目标表逐项确认是否具备：

```text
(observed_field, actual_key_field)
```

方向的索引或等价访问路径。索引不能作为框架自动行为，必须逐表评估数据量、现有主键方向、写入影响和磁盘空间。

当前 M3 评估后的口径：

| 数据集 | 索引判断 |
|---|---|
| `adj_factor` | 现有日期索引足够，暂不新增 |
| `daily` | 现有日期索引足够，暂不新增 |
| `daily_basic` | 现有日期索引足够，暂不新增 |
| `stk_limit` | 现有日期索引足够，暂不新增 |
| `stk_factor_pro` | 保留 `(trade_date, ts_code)` 为候选索引，等待 M2 线上真实耗时验证 |

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

### M0：现状止血与防误用（已落地）

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
| `date_subject_matrix` | M0/M1 阶段超过 30 个日期桶先拒绝；M4 阶段在分桶执行与心跳已上线后调整为 400 个日期桶 |

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

目标：替换全范围大 CTE，并沉淀可复用的对象矩阵分桶执行骨架。

落地状态：已完成第一版小闭环。当前实现保留 `SubjectCompletenessMatrixExecutor` 入口名称，但内部已从全范围大 CTE 改为按日期桶执行；结果写入在每个 bucket 内完成，最终收尾只更新 run 汇总状态，不再删除分桶写入的 subject gap/detail。

覆盖范围：

1. 只覆盖当前 5 个股票类对象矩阵数据集。
2. 只支持 `subject_kind=stock`。
3. 只支持单字段对象键 `ts_code`。
4. 只支持 `universe_strategy=stock_basic_active_lifecycle`。
5. 不处理停牌、上市首日、源端不产出等业务排除口径。

任务：

1. 保留 `SubjectCompletenessMatrixExecutor` 入口名称，内部改为分桶循环、进度、结果写入和错误收敛。
2. 使用最小对象池读取逻辑，第一版只实现 `stock_basic_active_lifecycle`。
3. 使用最小实际对象读取逻辑，按 `target_table + observed_field + actual_key_fields` 读取某个 bucket 的实际对象键。
4. 每个 bucket 独立统计 expected / covered / missing。
5. 每个 bucket 写入 gap summary。
6. 按全局 detail limit 与每桶 detail limit 写入 detail。
7. 每个 bucket commit 一次，并更新 run 进度与 heartbeat。
8. 保持普通 `date_bucket` 审计路径不变。
9. 不新增对象池排除表，不修改 `DatasetDefinition.completeness` 语义。

验收：

1. `stk_factor_pro` 8 个交易日以内审计结果与旧逻辑一致。
2. 运行中能看到 processed bucket 递增。
3. 中途取消后 run 能收敛为 error/canceled。
4. `daily`、`daily_basic`、`adj_factor`、`stk_limit` 小窗口审计能复用同一执行骨架。
5. 非 `stock_basic_active_lifecycle` 的对象池策略必须明确报“不支持”，不得静默套用股票规则。

### M3：覆盖索引与查询计划优化

目标：真正降低目标表读取成本，但索引必须逐表评估，不能作为通用框架自动创建。

M3 拆为两步：

1. M3-A：只读评估现有查询计划、体量、现有索引和单桶耗时。
2. M3-B：只有当 M3-A 证明有必要，才创建具体索引。

M3-A 已完成，结论是：5 张表单桶完整矩阵查询都在 `20ms` 内，暂不进入 M3-B。

原候选任务：

1. 为 `core_serving.equity_factor_pro` 增加 `(trade_date, ts_code)` 索引。
2. 对 `daily`、`daily_basic`、`adj_factor`、`stk_limit` 检查是否已有等价索引。
3. 用 `EXPLAIN ANALYZE` 固化单桶查询性能基线。
4. 若某表数据量较小且现有索引足够，不强制新增索引。

当前验收结论：

1. `stk_factor_pro` 当前命中 `idx_equity_factor_pro_trade_date`，单桶完整矩阵查询约 `19.529ms`。
2. 5 张表单桶查询均稳定在 `100ms` 以内。
3. 本轮没有新增索引，因此没有索引回滚项。
4. 若后续真实年度 run 仍超过目标，再进入 M3-B，并补充磁盘空间、建索引 SQL、回滚 SQL 和验证命令。

### M4：恢复大范围审计能力（本轮落地）

目标：在可观测、可取消、可控的基础上恢复年度范围审计。

任务：

1. 将 M0 中的临时 30 桶保护调整为 400 桶单次安全上限，允许年度审计，但继续阻止多年超大范围任务。
2. 对 `stk_factor_pro` 跑 `2025-01-02 ~ 2026-05-15` 范围。
3. 记录耗时、bucket 进度、最终结果。
4. 根据结果决定是否需要进一步优化对象池日快照。

验收：

1. 年度范围审计不再出现长时间无进度。
2. 运行过程中 `processed_bucket_count/current_bucket_value/progress_message/heartbeat_at` 持续更新。
3. 若真实耗时明显不可接受，允许终止 worker，并将 run 收敛为失败/取消结果。
4. 超过 400 个日期桶的对象矩阵审计仍被拒绝，避免再次创建不可控超大任务。
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

### M6：非股票对象池扩展评审（后置）

目标：如果未来要把指数、ETF、基金、板块等对象矩阵接入审计，先评审对象池语义，再新增 resolver。

进入条件：

1. M2/M3 在股票类 5 个数据集上稳定。
2. 新对象类型已经明确“什么对象在什么日期应该存在”。
3. 已确认目标表业务键、生命周期字段、停用/退市/失效规则。
4. 已确认目标表访问路径与索引策略。

禁止事项：

1. 禁止复用 `stock_basic_active_lifecycle` 去审计非股票对象。
2. 禁止为了省事把对象池语义写死在 executor 主流程里。
3. 禁止在未确认语义前把数据集配置为 `date_subject_matrix`。

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
3. 超过 400 桶的大范围保护提示明确。
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
2. M2 executor 切换应以代码提交为回滚边界；若新 executor 有问题，通过 git 回滚恢复，不在仓库里长期保留双主链或兼容分支。
3. M3 索引可单独 drop，不影响表数据。
4. 不涉及业务数据表写入，回滚不需要修复业务数据。

---

## 13. 下一步建议

建议按以下顺序推进：

1. M0 + M1 已完成：防止再次跑出无进度大任务。
2. M2 已完成：按日期桶执行小闭环已上线。
3. M3-A 已完成：5 张股票类对象矩阵目标表单桶查询均在 100ms 以内，暂不创建索引。
4. M4 本轮执行：允许年度范围审计并记录真实耗时。
5. 若 M4 年度真实耗时仍明显不可接受，再进入 M3-B 或 M5，不提前建索引。
6. 对象池口径问题作为独立方案，在 M4 真实验证后再处理。
7. 非股票对象池扩展必须走 M6 评审，不得在 M2/M4 中顺手实现。
