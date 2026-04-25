# Sync V2 事务风险审计与整改方案 v1

状态：待评审  
日期：2026-04-25  
适用范围：`src/foundation/services/sync_v2/**`、`src/ops/runtime/**`、`src/ops/services/operations_history_backfill_service.py`、相关 DAO 与迁移脚本。  
本轮性质：事故复盘后的事务边界审计与整改方案，不包含代码改动。

---

## 1. 背景与结论

`stk_mins` 全市场分钟线同步暴露出严重问题：任务执行过程中页面持续显示 `fetched/written` 增长，但数据主事务直到任务末尾才提交。最终 `ops.sync_job_state` 写回触发唯一键冲突后，主事务整体 rollback，导致前面长时间写入全部不可见。

本次事故不是单个数据库异常，而是三类问题叠加：

1. Sync V2 主链采用任务级事务，`execute()` 全部结束后才提交。
2. 进度上报用独立 session 提交，导致页面能看到“写入进度”，但数据并未提交。
3. `OpsSyncJobStateStore` 曾经无法复用同事务 pending row，导致 `mark_success()` 与 `mark_full_sync_done()` 连续调用时重复插入同一 `job_name`。

直接状态写回 bug 已有修复提交 `fix: reuse pending sync job state`，但这只解决最后的唯一键冲突，不解决大任务失败整体回滚问题。真正必须整改的是：Sync V2 对大数据集必须具备 unit 级 data transaction 提交能力，并且页面只能展示已真实提交的数据口径。

---

## 2. 审计口径

本次按以下标准判断风险：

1. **高风险大事务**：循环内大量写入，commit 在任务末尾；失败时会回滚整个任务。
2. **中风险局部大事务**：外层循环分段调用服务，每段内部仍可能是大事务；失败时至少丢当前段。
3. **低风险事务**：每个操作范围小，或每个步骤/任务单独提交，失败回滚范围可控。
4. **展示误导风险**：进度单独提交，但数据事务未提交，页面展示容易被误解为已安全落库。

---

## 3. 逐行审计结果

### 3.1 Sync V2 BaseSyncService：任务级提交是核心风险

文件：`src/foundation/services/sync_v2/base_sync_service.py`

| 行号 | 代码行为 | 风险判断 |
|---|---|---|
| 61-65 | `run_full()` / `run_incremental()` 都进入 `_run()` | 所有 Sync V2 数据集共享同一事务边界。 |
| 72 | 调用 `self.execute(...)`，内部会完成全部 fetch / normalize / write | 大量写入发生在 commit 前。 |
| 80-87 | 写 `sync_job_state`，`FULL` 任务还会调用 `mark_full_sync_done()` | 状态写回发生在数据写入之后，任何状态写失败都会拖垮前面数据写入。 |
| 88 | 唯一成功提交点：`self.session.commit()` | 这是任务级大事务根因。 |
| 98-117 | 异常后 `rollback()`，然后只提交失败日志 | 前面所有未提交数据写入全部撤销。 |

结论：这是 P0。任何单次 `execute()` 内产生大量 PlanUnit 或大量分页数据的数据集，都存在长时间白跑风险。

### 3.2 SyncV2Engine：unit 循环写入但缺少 unit 级提交

文件：`src/foundation/services/sync_v2/engine.py`

| 行号 | 代码行为 | 风险判断 |
|---|---|---|
| 48-57 | 一次性生成完整 `units` | 大范围任务会先形成大量执行单元。 |
| 68-69 | 进入 `for index, unit in enumerate(units)` | 多 unit 数据集在同一个主事务中循环。 |
| 75 | `worker.fetch(...)` 拉取数据 | 拉取成功不代表落库安全。 |
| 76-77 | normalize 并校验 | 内存中生成 normalized batch。 |
| 78-83 | `writer.write(...)` 执行写入 | SQL 执行了，但仍未提交。 |
| 84-89 | 累加 `rows_fetched / rows_written` | 当前 `rows_written` 是“执行过写入 SQL”，不是“已提交”。 |
| 103-127 | finally 中上报进度 | 失败前也可能上报大量 written，造成展示误导。 |
| 129-142 | 返回 summary | summary 仍不代表已提交，提交在上层 BaseSyncService。 |

结论：这是 P0。engine 缺少 unit 级提交边界，导致大任务无法保住已完成 unit。

### 3.3 SyncV2Writer：所有 write_path 都不提交

文件：`src/foundation/services/sync_v2/writer.py`

| 行号 | 代码行为 | 风险判断 |
|---|---|---|
| 51-130 | 根据 `write_path` 分发写入策略 | writer 只写，不提交。 |
| 497-508 | `raw_core_upsert`：raw 与 core 连续 upsert | 两层都在同一未提交事务中。 |
| 510-570 | `raw_std_publish_stock_basic`：raw/std/serving 多层写入 | 多层写入如果最后失败会一起回滚。 |
| 614-648 | `raw_std_publish_moneyflow`：raw/std/serving 发布 | 多表链路同事务，失败回滚范围较大。 |
| 650-684 | `raw_std_publish_moneyflow_biying` | 同上。 |
| 687-707 | `raw_only_upsert` | `stk_mins` 当前使用该路径，仍由外层统一提交。 |
| 710-730 | `raw_core_snapshot_insert_by_trade_date`：先删再插 | 如果未来按 unit 级提交，必须保证 unit 日期边界正确，否则可能出现半替换。 |

结论：writer 不提交本身可以接受，但 engine 必须掌握 unit 级提交。当前没有 unit 级提交，所以所有写入路径都被动落入任务级事务。

### 3.4 BaseDAO：批量分批执行不是事务分段

文件：`src/foundation/dao/base_dao.py`

| 行号 | 代码行为 | 风险判断 |
|---|---|---|
| 49-58 | `bulk_upsert()` 按 batch 执行多条 insert/update | batch 只是 SQL 分批，不是事务提交分批。 |
| 66-71 | `bulk_insert()` 按 batch 执行 insert | 同上。 |

结论：不要把 `sync_batch_size` 误认为事务提交边界。它只控制单 SQL 批量大小，不控制事务落盘。

### 3.5 Worker / Pagination：分页会累积单 unit 全量 rows

文件：`src/foundation/services/sync_v2/worker_client.py`、`src/foundation/services/sync_v2/strategy_helpers/pagination_loop.py`

| 文件行号 | 代码行为 | 风险判断 |
|---|---|---|
| `worker_client.py:27-37` | 调用 `fetch_rows_with_pagination(...)` 获取完整 rows | 单 unit 分页结果会一次性返回给 normalizer。 |
| `pagination_loop.py:16-28` | `rows_raw.extend(rows)`，直到最后一页 | 单 unit 大分页会形成内存峰值。 |

结论：这是 P1。它不是本次 1 亿行回滚的直接原因，但对 `dc_member`、`stk_factor_pro`、`stk_mins` 这类大数据集也不安全。

### 3.6 JobExecutionSyncContext：进度独立提交导致展示语义误导

文件：`src/ops/services/job_execution_sync_context.py`

| 行号 | 代码行为 | 风险判断 |
|---|---|---|
| 31-46 | 使用新 `progress_session` 更新 execution progress 并 commit | 进度独立提交，数据主事务未提交也能显示 `written`。 |

结论：这是 P0 展示语义风险。独立提交进度本身合理，但字段名与 UI 语义必须改，不能把未提交写入展示成安全落库。

### 3.7 Ops Dispatcher：运行入口把大任务交给 Sync V2 单次执行

文件：`src/ops/runtime/dispatcher.py`

| 行号 | 代码行为 | 风险判断 |
|---|---|---|
| 379-397 | `sync_minute_history`：无 `trade_date` 时调用 `service.run_full(...)` | 分钟线区间任务进入 BaseSyncService 的 `FULL` 单次执行。 |
| 398-407 | 其他普通 job 默认 `run_full(...)` | snapshot / range 任务也共享任务级事务。 |
| 409-427 | 根据 `result.rows_written` 拼接 summary | 这里同样使用未提交前统计，语义不等于 committed。 |

结论：P0/P1。dispatcher 不直接写大数据，但它决定了大任务是否走单次 Sync V2 执行。

### 3.8 HistoryBackfillService：外层分段，但单段内部仍依赖 Sync V2 事务

文件：`src/ops/services/operations_history_backfill_service.py`

| 行号 | 代码行为 | 风险判断 |
|---|---|---|
| 121-142 | `daily/adj_factor` 按交易日循环，每日调用 `run_incremental()` | 每个交易日内部单独提交，风险低于全范围单事务。 |
| 157-178 | 股票周/月线按锚点循环，每个锚点调用 `run_incremental()` | 单锚点失败回滚，整体风险中低。 |
| 189-212 | 部分 equity series 按证券循环，每个证券调用 `run_full(start/end)` | 每个证券内部仍可能是大事务，P1。 |
| 249-295 | trade-date backfill 按交易日循环调用 `run_incremental()` | 每个交易日一个事务，风险中低。 |
| 316-333 | `dividend/stk_holdernumber` 按证券循环调用 `run_full()` | 每个证券内部可能大，但不会整批一起回滚，P1。 |
| 356-377 | fund series 按交易日循环调用 `run_incremental()` | 风险中低。 |
| 411-429 / 442-460 | index 周/月按锚点循环调用 `run_incremental()` | 风险中低。 |
| 483-512 | `index_daily/index_daily_basic/index_weight` 按指数循环调用 `run_full(start/end)` | 单指数区间仍是大事务，P1。 |
| 537-555 | `broker_recommend` 按月份循环调用 `run_full(month)` | 单月事务，风险中低。 |

结论：HistoryBackfillService 比 `sync_minute_history` 好，因为外层做了分段；但每段内部仍依赖 Sync V2 的任务级事务。大段范围仍需 unit 级提交支持。该服务是迁移对象，不是目标架构组件；重构最终完成时，`HistoryBackfillService` 不能继续存在为独立执行器。

### 3.9 Worker 执行生命周期：调度状态提交是小事务

文件：`src/ops/runtime/worker.py`

| 行号 | 代码行为 | 风险判断 |
|---|---|---|
| 106-133 | claim queued execution 并 commit | 小事务，合理。 |
| 155-206 | finalize execution 并 commit | 小事务，合理。 |
| 246-260 | snapshot refresh failure 单独记录并 commit | 小事务，合理。 |

结论：worker 自身不是大数据回滚根因。

### 3.10 RawTushareBootstrapService：迁移脚本按表大事务

文件：`src/foundation/services/migration/raw_tushare_bootstrap_service.py`

| 行号 | 代码行为 | 风险判断 |
|---|---|---|
| 75-102 | 每张表 `TRUNCATE` 后 `INSERT INTO ... SELECT * ...`，最后 commit | 单表迁移可能是大事务。 |

结论：这是 P2/P1，属于迁移辅助，不是日常同步主链。但迁移大表时也可能长事务，应增加“维护窗口使用/大表禁用/分批复制”说明或保护。

---

## 4. 高风险数据集初步分层

以下分层基于当前 contract、分页上限、请求扇出和写入路径。最终整改时还需逐数据集确认幂等语义。

### 4.1 P0：必须先保护，禁止大范围任务裸跑

| 数据集 | 原因 | 当前写入路径 |
|---|---|---|
| `stk_mins` | 全市场分钟线，unit 多、运行长、数据量巨大；事故已发生。 | `raw_only_upsert` |
| `stk_factor_pro` | 宽表，全市场日频，单次 10000 上限。 | `raw_core_upsert` |
| `dc_member` | 单日可返回大量成分数据，分页量大。 | `raw_core_upsert` |
| `index_daily` | 活跃指数池按代码扇出，区间任务可形成多 unit。 | `raw_core_upsert` |
| `index_weight` | 按指数区间/月度窗口，可能较长。 | `raw_core_upsert` |
| `dc_hot` / `ths_hot` / `kpl_list` / `limit_list_ths` 的 `__ALL__` 哨兵链路 | `__ALL__` 可能进入请求、query context 或落库字段，造成主键碰撞和脏数据。 | 多数为 `raw_core_upsert` |

### 4.2 P1：需要纳入 unit 级提交治理，但可排在 P0 后

| 数据集 | 原因 |
|---|---|
| `dc_daily` / `ths_daily` | 板块日频，按日期分页。 |
| `dc_hot` / `ths_hot` | 枚举扇出 + 日期 + 分页。 |
| `cyq_perf` | 日频全市场分页。 |
| `moneyflow_*` 全族 | 多数是日频分页，部分还有 std/serving 发布。 |
| `stock_basic` | 多源 raw/std/serving 发布，虽然 snapshot 较小，但多层写入。 |
| `biying_equity_daily` / `biying_moneyflow` | 按股票池与窗口扇出。 |

### 4.3 P2：当前风险可控，但仍需统一语义

| 数据集 | 原因 |
|---|---|
| `daily` / `adj_factor` / `fund_daily` / `fund_adj` | 通常按单交易日执行，单次规模中等。 |
| `broker_recommend` | 月维度，小范围。 |
| `hk_basic` / `us_basic` / `index_basic` / `etf_basic` / `ths_index` | snapshot / master 类，通常规模可控。 |

---

## 5. 整改目标

1. 大数据集失败时不能整批丢失。
2. 页面不能把未提交写入展示成已落库。
3. 所有 Sync V2 数据集必须显式声明事务策略。
4. 默认仍可保持任务级事务，但大数据集必须启用 unit 级提交。
5. 删除“隐式大事务”：任何写入任务都必须先评估单个事务的写入量，做真实的计算。

---

## 6. 整改方案

### 6.0 P0：删除分裂状态写入模型

`mark_success()` 与 `mark_full_sync_done()` 连续写同一条 `ops.sync_job_state(job_name)` 是本次事故链路的一部分，不能作为长期设计继续保留。

整改要求：

1. 主链删除 `mark_success() -> mark_full_sync_done()` 连续调用。
2. 目标模型不保留 `FULL/INCREMENTAL` 作为执行语义；改用 `action + time_scope + run_profile` 表达 point/range/none/month/window。
3. 目标模型不保留 `full_sync_done` 作为资源健康判断字段；改用 `coverage_status`、`coverage_scope`、`latest_observed_business_date`、`last_success_at`、`data_completeness_status`。
4. 新增单一资源状态写入接口，例如 `record_execution_outcome(...)`。
5. 单一接口一次性接收 `execution_id`、`dataset_key`、`resource_key`、`action`、`time_scope`、`run_profile`、`coverage_scope`、`result_business_date`、`committed_rows`。
6. 有业务日期的数据集不得因为旧 full sync 语义清空业务日期；无业务日期的数据集必须由 date model 显式声明。
7. 旧 `mark_success()` / `mark_full_sync_done()` 如果短期保留，只能作为 legacy facade 调用单一接口，不得分别写同一行。
8. 对应测试必须覆盖：point、range、none、有业务日期、无业务日期、重复重试、状态写失败。

### 6.1 M0：立即止血保护

目标：避免再次运行缺少事务写入量评估的高风险任务。

建议动作：

1. 开发时必须评估单个事务的写入量，做真实的计算。
2. 文案明确：
   - `written` 在 data transaction 提交前不得展示成已落库。
3. 对 `dc_hot`、`ths_hot`、`kpl_list`、`limit_list_ths` 增加 `__ALL__` P0 guard：
   - 全选必须展开为真实业务枚举值。
   - `PlanUnit.request_params`、adapter 注入字段、normalized rows、writer 入参不得出现 `__ALL__`。
   - 无法展开真实枚举时拒绝执行或 dry-run/preview，不得用 `__ALL__` 兜底。

### 6.2 M1：引入最小事务策略

不做复杂抽象，先只做必要字段：

```python
@dataclass(slots=True, frozen=True)
class TransactionSpec:
    commit_policy: str = "task"  # task / unit
    idempotent_write_required: bool = False
```

字段含义：

| 字段 | 含义 |
|---|---|
| `commit_policy=task` | 保持现状，整个 service run 最后提交。 |
| `commit_policy=unit` | 每个 PlanUnit 写入成功后提交一次。 |
| `idempotent_write_required` | 声明该数据集启用 unit 级提交时必须具备幂等写入能力。 |

只支持任务级和 unit 级两种提交粒度，不引入分页级或行级提交。源接口分页只作为 unit 内部获取数据的技术细节，不作为事务提交点。

验收：

1. 未确认幂等写入能力的数据集不得使用 `unit`。
2. P0 数据集必须显式声明事务策略。
3. linter 能阻止 `stk_mins` 继续使用默认任务级事务。
4. 实时或 snapshot 类数据集每次执行都重新请求数据源。

### 6.3 M2：engine 支持 unit 级提交

目标：每个 unit 成功写入后可以提交，失败时只 rollback 当前 unit。

建议动作：

1. 在 engine 循环中，`writer.write()` 成功后根据 contract 判断是否 `session.commit()`。
2. 失败时：
   - 当前未提交事务 rollback。
   - 已提交 unit 数据保留。
   - 任务状态仍为 failed 或 partial_failed，由 ops 层明确展示。

验收：

1. 测试模拟第 N 个 unit 失败，前 N-1 个 unit 数据已提交。
2. 测试模拟最终状态写回失败，已提交业务数据仍保留。
3. 任务级事务数据集行为保持原样。

### 6.4 M3：进度语义修正

目标：页面不再把未提交写入展示成已安全落库。

建议动作：

1. 后端 progress message 增加：
   - `committed`
2. 兼容旧字段：
   - `written` 暂时保留，但 Web 不把它展示成已落库。
3. 前端展示：
   - unit 级提交数据集展示“已提交行数”。
   - 任务级事务数据集只展示任务完成后的最终行数，不在阶段进度里写成已落库。

验收：

1. `stk_mins` 进度能看到当前 unit、当前股票、当前频率、已提交行数。
2. 任务失败时页面能区分“失败但已提交部分数据”和“失败且全部回滚”。

### 6.5 M4：P0 数据集逐个启用 unit 级提交

顺序必须保守：

1. `stk_mins`
2. `dc_member`
3. `stk_factor_pro`
4. `index_daily`
5. `index_weight`

每个数据集都要单独完成：

1. 确认 write_path 幂等。
2. 单 unit 成功测试。
3. 中途失败测试。
4. 远程验证。
5. 对账或行数核验。

### 6.6 M5：P1 数据集分批启用 unit 级提交 / 分页内存优化

P1 分两类：

1. unit 级提交足够解决的问题：
   - `dc_daily`
   - `ths_daily`
   - `dc_hot`
   - `ths_hot`
   - `cyq_perf`
   - `moneyflow_*`
2. 仍有单 unit 内存峰值的问题：
   - `dc_member`
   - `stk_factor_pro`
   - 后续可能还有大分页接口

第二类如果存在单 unit 内存峰值，必须基于真实计算结果评估单个事务写入量；无法通过业务边界拆分时，才允许做 unit 内部的流式读取/分块处理。该优化不改变提交粒度：事务提交仍然只按 unit 执行。

---

## 7. 必须新增的测试门禁

### 7.1 单元测试

1. `tests/test_sync_v2_transaction_policy.py`
   - 默认 `task` 行为不变。
   - `unit` policy 成功后逐 unit commit。
   - unit 失败只 rollback 当前 unit。
2. `tests/test_sync_v2_progress_commit_semantics.py`
   - progress 中只把已提交数据展示为 committed。
   - 任务级事务数据集不得把阶段性 written 表示成 committed。
3. `tests/test_sync_v2_transaction_write_volume.py`
   - 执行计划必须包含单事务写入量真实计算依据。
4. `tests/test_sync_v2_no_all_sentinel.py`
   - `dc_hot` 默认提交扇出真实 `market + hot_type + is_new`。
   - `ths_hot` 默认提交扇出真实 `market + is_new`。
   - `kpl_list` / `limit_list_ths` 不生成 `__ALL__` request params 或 query context。
   - normalizer / writer 看到落库 query 字段含 `__ALL__` 时失败。

### 7.2 架构门禁

1. Registry guardrail 增加：
   - P0 数据集必须声明 `TransactionSpec`。
   - `commit_policy=unit` 必须确认幂等写入能力。
2. Linter 增加：
   - 单事务写入量评估必须有测试覆盖。
   - Sync V2 主链禁止 `__ALL__` 业务哨兵；如文档或迁移测试保留字符串，必须显式 allowlist。

### 7.3 回归命令

每批改动至少执行：

```bash
pytest -q tests/test_sync_v2_validator.py tests/test_sync_v2_planner.py tests/test_sync_v2_linter.py
pytest -q tests/test_sync_v2_registry_routing.py
pytest -q tests/architecture/test_sync_v2_registry_guardrails.py
pytest -q tests/architecture/test_subsystem_dependency_matrix.py
GOLDENSHARE_ENV_FILE=.env.web.local goldenshare sync-v2-lint-contracts
```

涉及前端展示时追加：

```bash
cd frontend && npm run test -- ops-task-detail
cd frontend && npm run typecheck
```

---

## 8. 代码改动范围评估

### 8.1 必改文件

| 文件 | 改动 |
|---|---|
| `src/foundation/services/sync_v2/contracts.py` | 新增事务策略字段。 |
| `src/foundation/services/sync_v2/engine.py` | 支持 unit 级提交与 committed 统计。 |
| `src/foundation/services/sync_v2/base_sync_service.py` | 成功/失败收尾要识别 partial committed 语义。 |
| `src/foundation/services/sync_v2/observer.py` | 扩展 committed progress。 |
| `src/foundation/services/sync_v2/linter.py` | 增加事务策略门禁。 |
| `src/foundation/services/sync_v2/registry_parts/contracts/*.py` | P0/P1 数据集声明事务策略。 |
| `src/ops/runtime/dispatcher.py` | summary 语义避免把未提交行数当 committed。 |
| `src/ops/schemas/execution.py` | 如前端需要结构化 committed 字段，则扩展 schema。 |
| `frontend/src/pages/ops-task-detail-page.tsx` | 只把 committed 展示为入库结果。 |

### 8.2 暂不改文件

| 文件 | 原因 |
|---|---|
| `src/foundation/services/sync_v2/writer.py` | 第一阶段保持 writer 只负责写，不负责提交。 |
| `src/foundation/dao/base_dao.py` | batch size 不等于事务提交边界，不在 DAO 层提交。 |
| `src/ops/services/operations_history_backfill_service.py` | 只作为迁移对象审计旧规则；区间循环、证券池循环、月份循环必须迁入 planner/executor，最终删除独立执行器。 |

---

## 9. 风险评估

### 9.1 unit 级提交带来的风险

1. 任务失败后可能出现“部分数据已提交”。
2. 需要 UI/任务状态明确表达 partial committed。
3. 写入必须幂等，否则重跑可能重复或污染数据。

### 9.2 为什么仍然必须做

对大数据集而言，任务级事务的风险已经被实际事故证明不可接受。unit 级提交的复杂度可以通过单数据集逐步启用控制；任务级大事务的损失不可控。

### 9.3 回滚方案

1. `commit_policy` 回退为 `task`。
2. 保留单事务写入量真实计算要求，防止回退后再次进入隐式大事务。
3. 已提交的数据通过幂等 upsert 重跑修正。

---

## 10. 建议实施顺序

1. **先落 M0**：补单事务写入量真实计算要求，避免再次事故。
2. **再落 M1/M2**：最小 unit 级提交。
3. **同步落 M3**：修正进度语义。
4. **先用 `stk_mins` 验证单事务写入量计算与 unit 级提交**。
5. **再扩展 P0 其他数据集**。
6. **最后处理 P1 数据集与必要的分页内存优化**。

---

## 11. Review 需要拍板的问题

1. 已拍板：事务提交只支持 `task` 或 `unit`，不做分页级或行级提交。
2. 任务状态是否允许引入 `partial_failed`，还是沿用 `failed` 并在 summary 中标注部分已提交？
3. 前端是否立即展示 `committed` 字段，还是先改文案避免误导？
