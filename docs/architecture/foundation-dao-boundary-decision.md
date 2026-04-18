# Foundation 剩余 3 个 DAO 边界判定与迁移方案（仅分析，不改实现）

## 1. 任务范围与结论摘要

本次仅对以下 3 个白名单 DAO 做归属判定与最小迁移方案设计，不改代码实现：

- `src/foundation/dao/sync_run_log_dao.py`
- `src/foundation/dao/sync_job_state_dao.py`
- `src/foundation/dao/index_series_active_dao.py`

结论先行：

1. `sync_run_log_dao` 与 `sync_job_state_dao` 可作为 **一组** 处理（同属“同步运行状态写入”）。
2. `index_series_active_dao` 建议 **单独** 处理（它既被同步链路使用，也被审查中心直接消费，语义不同于通用运行日志/状态）。

---

## 2. 实际追踪到的调用链

> 说明：以下为本次实际扫描的代码链路（src 内业务代码，测试文件仅用于补充语义）。

### 2.1 `sync_run_log_dao` 调用链

- DAO 依赖模型：
  - `src.ops.models.ops.sync_run_log.SyncRunLog`（表：`ops.sync_run_log`）
- 直接调用 DAO 的业务代码：
  - `src/foundation/services/sync/base_sync_service.py`
    - `start_log(...)`
    - `finish_log(...)`
- 读取同一模型（非 DAO）的位置：
  - `src/ops/queries/execution_query_service.py`
  - `src/ops/queries/freshness_query_service.py`
  - `src/operations/services/execution_reconciliation_service.py`
  - `src/operations/services/daily_health_report_service.py`
- `src/ops/**` / `src/biz/**` 内未发现该 DAO 类的直接调用。

### 2.2 `sync_job_state_dao` 调用链

- DAO 依赖模型：
  - `src.ops.models.ops.sync_job_state.SyncJobState`（表：`ops.sync_job_state`）
- 直接调用 DAO 的业务代码：
  - `src/foundation/services/sync/base_sync_service.py`
    - `mark_success(...)`
    - `mark_full_sync_done(...)`
  - `src/operations/services/sync_job_state_reconciliation_service.py`
    - `mark_success(...)`
    - `reconcile_success_date(...)`
- 读取同一模型（非 DAO）的位置：
  - `src/ops/queries/freshness_query_service.py`（全量读取状态构建新鲜度）
  - `src/operations/services/sync_job_state_reconciliation_service.py`（`session.get`）
- `src/ops/**` / `src/biz/**` 内未发现该 DAO 类的直接调用。

### 2.3 `index_series_active_dao` 调用链

- DAO 依赖模型：
  - `src.ops.models.ops.index_series_active.IndexSeriesActive`（表：`ops.index_series_active`）
- 直接调用 DAO 的业务代码：
  - `src/foundation/services/sync/sync_index_daily_service.py`
    - `list_active_codes(...)`
    - `upsert_seen_codes(...)`
  - `src/foundation/services/sync/sync_index_daily_basic_service.py`
    - `upsert_seen_codes(...)`
  - `src/foundation/services/sync/sync_index_weekly_service.py`
    - `list_active_codes(...)`
  - `src/operations/services/history_backfill_service.py`
    - `list_active_codes(...)`
- 读取同一模型（非 DAO）的位置：
  - `src/ops/queries/review_center_query_service.py`（审查中心“激活指数”）
- `src/biz/**` 内未发现该 DAO 类的直接调用。

---

## 3. 逐 DAO 归属判定与推荐迁移方式

## 3.1 `sync_run_log_dao`

- 当前依赖：
  - `ops.sync_run_log` 模型与表
- 语义判定：
  - 偏 **ops**（运维执行可观测性日志），非 foundation 业务主数据。
- 推荐最终归属：
  - **ops**
- 推荐迁移方式：
  - **contract + adapter**
  - 在 foundation 定义最小写入契约（例如“run start / run finish”）
  - ops 侧提供 `SyncRunLog` 适配实现（读写 `ops.sync_run_log`）
  - `BaseSyncService` 只依赖契约，不直接触碰 ops ORM
- 为什么这样划分：
  - 写入发生在 foundation 同步主链路中，但数据本身服务于 ops 查询/报表/执行复盘。
  - 让 foundation 保持“写事件/状态”而不感知 ops 表结构。
- 风险点：
  - `start_log` 当前会提前 `commit` 生成日志记录；迁移时需保证事务语义不变（失败也可追踪到开始记录）。
  - 文本截断策略（`truncate_text`）需要保持一致，否则 UI 日志展示可能回归。

## 3.2 `sync_job_state_dao`

- 当前依赖：
  - `ops.sync_job_state` 模型与表
- 语义判定：
  - 偏 **ops**（新鲜度状态机/同步游标状态），不是 foundation 原始数据资产。
- 推荐最终归属：
  - **ops**
- 推荐迁移方式：
  - 与 `sync_run_log_dao` **同批处理**，采用 **contract + adapter**
  - foundation 侧只调用“同步状态写回契约”
  - ops 侧实现 `mark_success / mark_full_sync_done / reconcile_success_date` 对应能力
- 为什么这样划分：
  - `ops/queries/freshness_query_service` 直接以该表为主状态源，属于运维治理域核心状态。
  - foundation 只是产生状态变化，不应直接依赖 ops ORM。
- 风险点：
  - `mark_success` 对已有记录 `full_sync_done` 的保留逻辑必须保持，否则会破坏历史全量完成标记。
  - reconciliation 流程（operations service）与实时写回流程可能并发，需保持 upsert 幂等行为。

## 3.3 `index_series_active_dao`

- 当前依赖：
  - `ops.index_series_active` 模型与表
- 语义判定：
  - **混合语义**：既是同步过程使用的“活动指数池”，又被 ops 审查中心作为观测对象直接查询。
- 推荐最终归属：
  - 最终归 **ops**（治理视图与运维观测已明确依赖），foundation 通过契约访问。
- 推荐迁移方式：
  - **单独处理**，采用 **contract + adapter**
  - 先抽 `IndexSeriesActiveStore` 契约（list/upsert）
  - foundation 同步与 backfill 仅依赖契约
  - ops 保留模型与查询（review center）
- 为什么不与前两者并批：
  - 它不仅是运行日志/状态，还直接影响指数同步“可拉取集合”的业务行为，误改会影响数据覆盖面。
  - 审查中心直接消费其字段（首收录/最近收录/最近观测）。
- 风险点：
  - `upsert_seen_codes` 使用 `least/greatest` 聚合首末日期，若迁移不一致会导致激活池历史失真。
  - 空池回退路径（`index_daily_basic` discovery）与 backfill 依赖该池，需保证行为不变。

---

## 4. 建议的最小实施顺序（下一步）

1. **第一组优先**：`sync_run_log_dao + sync_job_state_dao`
   - 同属“同步运行状态写回”，对契约抽象边界清晰，且能一次减少 2 个 foundation->ops 白名单点。
2. **第二步单独**：`index_series_active_dao`
   - 在第一组稳定后再处理，避免同步覆盖范围与审查中心同时受影响。

---

## 5. 本次不做的事项（已遵守）

- 未移动 DAO 文件
- 未修改任何业务逻辑
- 未修改依赖矩阵测试规则
- 未扩大为 platform/operations 大范围重构

