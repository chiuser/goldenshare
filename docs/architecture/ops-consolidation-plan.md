# operations -> ops 收敛计划（runtime/specs 第一批）

## 目标

在不触碰 `platform`、不做 `services` 大归并的前提下，优先收敛 `operations` 与 `ops` 的双中心结构，先完成 `runtime/specs` 第一批安全迁移。

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

