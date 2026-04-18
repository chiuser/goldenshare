# operations -> ops 收敛计划（runtime/specs + services 第一批）

## 目标

在不触碰 `platform`、不做高歧义服务归并的前提下，优先收敛 `operations` 与 `ops` 的双中心结构，分批完成：

1. `runtime/specs` 第一批安全迁移（已完成）。
2. `services` 低歧义第一批安全迁移（本轮）。

## 当前现状（迁移前）

- 实现主路径仍在：
  - `src/operations/runtime/*`
  - `src/operations/specs/*`
- `src/ops/runtime` 与 `src/ops/specs` 仍为 skeleton。
- 典型调用链：
  - CLI 与 runtime service 仍从 `src.operations.runtime` 引入。
  - dispatcher 通过 `src.operations.specs` 获取 job/workflow spec。

## 归并清单

### runtime：应并入 `src/ops/runtime`

- `src/operations/runtime/dispatcher.py`
- `src/operations/runtime/scheduler.py`
- `src/operations/runtime/worker.py`

说明：
- `src/operations/runtime/__init__.py` 保留为兼容壳。

### specs：应并入 `src/ops/specs`

- `src/operations/specs/dataset_freshness_spec.py`
- `src/operations/specs/job_spec.py`
- `src/operations/specs/observed_dataset_registry.py`
- `src/operations/specs/workflow_spec.py`
- `src/operations/specs/registry.py`

说明：
- `src/operations/specs/__init__.py` 保留为兼容壳。

## `ops` skeleton 承接方式

### `src/ops/runtime`

- 由 skeleton 升级为主实现目录。
- `__init__.py` 提供稳定导出：
  - `DispatchOutcome`
  - `OperationsDispatcher`
  - `OperationsScheduler`
  - `OperationsWorker`

### `src/ops/specs`

- 由 skeleton 升级为主实现目录。
- `__init__.py` 提供完整导出（与原 `operations/specs` 一致），供上层统一依赖。

## 兼容壳策略（允许保留）

保留以下旧路径作为 deprecated 兼容壳，避免一次性修改所有调用点：

- `src/operations/runtime/__init__.py`
- `src/operations/runtime/dispatcher.py`
- `src/operations/runtime/scheduler.py`
- `src/operations/runtime/worker.py`
- `src/operations/specs/__init__.py`
- `src/operations/specs/dataset_freshness_spec.py`
- `src/operations/specs/job_spec.py`
- `src/operations/specs/observed_dataset_registry.py`
- `src/operations/specs/workflow_spec.py`
- `src/operations/specs/registry.py`

兼容壳要求：
- 仅做薄转发/别名；
- 不新增业务逻辑；
- 文件头标注 deprecated。

## 第一批迁移最小范围（本次实施）

1. 将 runtime/specs 主实现文件迁移到 `src/ops/**`。
2. 更新 `src/ops/**` 内部 import 指向（使用 `src.ops.*`）。
3. 在 `src/operations/**` 保留 deprecated 兼容壳。
4. 将少量入口调用改为新中心：
   - `src/cli.py` -> `src.ops.runtime`
   - `src/ops/services/runtime_service.py` -> `src.ops.runtime`

## 本次不做

- 不处理 `src/operations/services` 与 `src/ops/services` 的大归并。
- 不处理 `platform` 相关目录。
- 不调整 CLI 体系与命令设计。
- 不修改依赖矩阵规则。

## 风险点

1. **测试 monkeypatch 路径风险**  
   - 旧测试常以 `src.operations.runtime.*` patch 模块级符号。  
   - 通过兼容壳将模块名映射到新模块对象，降低行为偏差。

2. **跨模块导入循环风险**  
   - 迁移后统一改为 `src.ops.specs.*` 内部引用，避免 `ops -> operations -> ops` 循环。

3. **历史调用点未改完风险**  
   - 兼容壳先兜住，后续按批次逐步把 `operations.*` 引用替换为 `ops.*`。

## 后续批次建议

1. 批次 2：清点并迁移 `operations/services` 中与 runtime 强耦合的服务（仍不触碰 platform）。
2. 批次 3：收缩 `operations` 对外导出面，减少兼容壳数量。
3. 批次 4：完成 `operations` 目录下 runtime/specs 兼容壳退役。

---

## services 归并章节（本轮新增）

### 现状：`operations/services` 与 `ops/services` 双中心

- `src/ops/services` 目前同时承载：
  - 面向 API/命令层的 command service（`Ops*CommandService`）
  - 部分 ops 业务实现（新迁入的 `operations_*` service）
- `src/operations/services` 仍保留大量历史实现，是运行时和作业链路的老入口。

### 同名/近同名关系清单

#### 已判定为低歧义（本轮第一批）

- `execution_service`：
  - 原：`src/operations/services/execution_service.py`
  - 新：`src/ops/services/operations_execution_service.py`
- `schedule_service`：
  - 原：`src/operations/services/schedule_service.py`
  - 新：`src/ops/services/operations_schedule_service.py`
- `schedule_planner`：
  - 原：`src/operations/services/schedule_planner.py`
  - 新：`src/ops/services/schedule_planner.py`
- `schedule_probe_binding_service`：
  - 原：`src/operations/services/schedule_probe_binding_service.py`
  - 新：`src/ops/services/schedule_probe_binding_service.py`

判定依据：
- 职责集中在 ops 调度/触发/编排侧；
- 与 platform 无直接耦合；
- `src/ops/services` 已具备承接位；
- 可通过兼容壳保持外部行为稳定。

#### 暂缓处理（跨域/高歧义）

- 明确暂缓：
  - `market_mood_walkforward_validation_service`（按任务要求禁止处理）
- 本轮不处理的其余高歧义/跨域项（示例）：
  - `history_backfill_service`
  - `probe_runtime_service`
  - `execution_reconciliation_service`
  - `sync_job_state_reconciliation_service`
  - `dataset_status_snapshot_service`
  - `daily_health_report_service`
  - `stock_basic_reconcile_service`
  - `moneyflow_reconcile_service`
  - `moneyflow_multi_source_seed_service`
  - `dataset_pipeline_mode_seed_service`
  - `default_single_source_seed_service`
  - `serving_light_refresh_service`

这些服务多数涉及跨域读写（ops/foundation/core_serving）或历史脚本语义，需单独分批。

### 第一批迁移的最小范围（本轮实施）

1. 仅迁移上面 4 个低歧义 service 的主实现到 `src/ops/services/*`。
2. `src/operations/services/*` 同名旧路径保留 deprecated 兼容壳（模块别名转发）。
3. 最小调用侧切换：
  - `src/ops/services/execution_service.py`
  - `src/ops/services/schedule_service.py`
  - `src/ops/runtime/scheduler.py`
4. 外部行为保持不变，不改 API/schema/query 结构。

### 风险点与兼容策略

1. **旧导入路径仍被使用**
   - 通过 `src/operations/services/*.py` 兼容壳转发到 `src/ops/services/*`。
2. **运行时链路行为偏差风险**
   - 只做 import 路径切换，不改业务分支与事务语义。
3. **后续清理难度**
   - 每轮仅迁移低歧义服务，并在文档维护“暂缓列表”，避免一次性大迁移。
