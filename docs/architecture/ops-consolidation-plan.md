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
- 第一批暂缓（已在第二批迁移）的项：
  - `probe_runtime_service`
  - `execution_reconciliation_service`
  - `sync_job_state_reconciliation_service`
  - `dataset_status_snapshot_service`
- 本轮不处理的其余高歧义/跨域项（示例）：
  - `history_backfill_service`
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

---

## services 第二批归并章节（ops 治理域）

### 为什么这一批属于 ops 治理域

本批迁移对象：

- `execution_reconciliation_service`
- `sync_job_state_reconciliation_service`
- `dataset_status_snapshot_service`
- `probe_runtime_service`

共同特征：

- 主要读写 `ops.*` 元数据/状态表（执行状态、探测日志、快照层状态等）；
- 职责集中在 ops 运维治理（修正、对账、快照、探测触发）；
- 不承载平台业务 API 语义，不依赖 platform 的 controller/query 层；
- 可通过兼容壳平滑切换调用路径，外部行为可保持稳定。

### 为什么暂不处理剩余服务

继续暂缓的服务具备至少一项高歧义特征：

- 跨域/跨层写入（foundation/core_serving/ops 多层耦合）；
- 属于分析验证类或业务特化逻辑；
- seed/一次性修复脚本语义，归属与生命周期不稳定。

明确继续暂缓：

- `market_mood_walkforward_validation_service`
- `history_backfill_service`
- `stock_basic_reconcile_service`
- `moneyflow_reconcile_service`
- seed 系列：`dataset_pipeline_mode_seed_service` / `default_single_source_seed_service` / `moneyflow_multi_source_seed_service`
- 其余未迁移项暂按原路径保留，后续再分批判定。

### 第二批迁移最小范围（本轮实施）

1. 将以下主实现迁入 `src/ops/services/*`：
   - `operations_execution_reconciliation_service.py`
   - `operations_sync_job_state_reconciliation_service.py`
   - `operations_dataset_status_snapshot_service.py`
   - `operations_probe_runtime_service.py`
2. 旧路径 `src/operations/services/*.py` 保留 deprecated 兼容壳（模块别名转发）。
3. 最小调用侧切换：
   - `src/ops/runtime/scheduler.py` -> `src.ops.services.operations_probe_runtime_service`
   - `src/ops/runtime/worker.py` -> `src.ops.services.operations_dataset_status_snapshot_service`
4. 不改 CLI 命令设计，不改 query/api/schema 大结构。

### 风险点与兼容策略（第二批）

1. **CLI/测试仍引用旧路径**
   - 用 `operations/services` 兼容壳兜底，避免一次性改动测试与命令入口。
2. **循环依赖风险**
   - 迁移后优先切换到 `src.ops.specs`，避免 `ops -> operations -> ops` 闭环。
3. **行为漂移风险**
   - 严格限定为 import/路径迁移，不改业务流程与 SQL 语义。

### `execution_service` / `schedule_service` 的命名与角色关系

当前采用“双名并存、角色分离”：

- **主实现（core implementation）**
  - `src/ops/services/operations_execution_service.py`
  - `src/ops/services/operations_schedule_service.py`
  - 负责真实业务逻辑。
- **façade / 命令层封装（command façade）**
  - `src/ops/services/execution_service.py`（`OpsExecutionCommandService`）
  - `src/ops/services/schedule_service.py`（`OpsScheduleCommandService`）
  - 面向 API/命令入口做参数编排与权限上下文接入。
- **旧路径兼容层（deprecated shim）**
  - `src/operations/services/execution_service.py`
  - `src/operations/services/schedule_service.py`
  - 仅做模块转发，不承载新逻辑。

---

## 剩余 services 归属判定（第三批前置分析）

本节仅做归属判定与分组，不做实现迁移。

### 逐项判定

| service | 当前主要调用方 | 归属倾向 | 推荐最终归属 | 第三批候选 | 原因 | 风险点 |
| --- | --- | --- | --- | --- | --- | --- |
| `daily_health_report_service.py` | `src/cli.py`、`src/operations/services/__init__.py`、对应单测 | ops | `src/ops/services` | 是（低） | 主要读取 `ops.job_execution/sync_run_log` 与 ops freshness 查询，属于运维日报治理能力 | 报表口径依赖 freshness 结构；迁移时需保持 markdown/json 输出一致 |
| `dataset_pipeline_mode_seed_service.py` | `src/cli.py`、`src/operations/services/__init__.py`、对应单测 | ops | `src/ops/services` | 是（低） | 只负责生成/修正 ops 管线模式配置（`ops.dataset_pipeline_mode`） | 与数据集规格枚举耦合，需确认 `ops.specs` 取数路径稳定 |
| `default_single_source_seed_service.py` | `src/cli.py`、`src/operations/services/__init__.py`、对应单测 | ops（治理） | `src/ops/services` | 是（中） | 虽写入 `foundation.models.meta`，但职责是“运维初始化规则与策略种子”，语义属于 ops 治理 | 同时写 `ops + meta` 多表，迁移时要防止事务语义和幂等判断漂移 |
| `history_backfill_service.py` | `src/ops/runtime/dispatcher.py`、`src/cli.py`、大量回填单测 | 暂缓（高歧义） | 暂定 `ops/services`（后续专项） | 否 | 运行时核心执行路径 + foundation sync/backfill 深耦合，改动面广 | 涉及 job spec executor、执行进度、多资源回填策略，误改风险高 |
| `market_mood_walkforward_validation_service.py` | `src/cli.py`、依赖矩阵白名单、对应单测 | 暂缓（跨域） | 倾向 `biz`（或拆分） | 否 | 直接依赖 `src.biz.services.market_mood_calculator`，不是纯 ops 治理能力 | 现存 `operations -> biz` 历史违规点；需先做边界拆分再迁 |
| `moneyflow_multi_source_seed_service.py` | `src/cli.py`、`src/operations/services/__init__.py`、对应单测 | ops（治理） | `src/ops/services` | 是（中） | 负责多源融合配置种子（pipeline/mapping/cleansing/source_status/resolution） | 牵涉策略版本与多表一致性，迁移时要保持 dry-run/apply 行为完全一致 |
| `moneyflow_reconcile_service.py` | `src/cli.py`、`src/operations/services/__init__.py`、对应单测 | ops | `src/ops/services` | 是（低） | 纯运维核对/审计服务（raw 对账），无 runtime 编排耦合 | 字段映射口径较多，迁移时需保留 diff 统计与样本抽样规则 |
| `serving_light_refresh_service.py` | `src/ops/runtime/dispatcher.py`、`src/cli.py`、`src/operations/services/__init__.py`、单测 | ops | `src/ops/services` | 是（中） | 由 ops runtime 触发的维护动作，语义是运维发布/刷新能力 | SQL 直写 + UPSERT，需谨慎保持参数过滤与行数统计语义 |
| `stock_basic_reconcile_service.py` | `src/cli.py`、`src/operations/services/__init__.py`、对应单测 | ops | `src/ops/services` | 是（低） | 纯运维核对服务（`core_multi.security_std` 双源差异对账） | 规范化规则（名称/交易所）是结果口径关键，迁移要避免细微变化 |

### 第三批候选列表（低到中等歧义）

第三批按当前决策分段执行，先做最小安全范围。

#### 第三批-A（本轮最小范围，仅两项）

1. `daily_health_report_service.py`
2. `dataset_pipeline_mode_seed_service.py`

说明：

- 本轮严格只迁移上述两项，不扩大到 reconcile/seed 其他服务。
- 迁移方式保持“`ops` 主实现 + `operations` 兼容壳”。

#### 第三批-B（本轮最小范围，仅一项）

1. `serving_light_refresh_service.py`

说明：

- 本轮严格只迁移 `serving_light_refresh_service`，不扩大到 reconcile/seed 其他服务。
- 迁移方式保持“`ops` 主实现 + `operations` 兼容壳”。

#### 第三批-C（本轮最小范围，仅两项，seed/config）

1. `default_single_source_seed_service.py`
2. `moneyflow_multi_source_seed_service.py`

说明：

- 本轮严格只迁移上述两项，不扩大到 reconcile 或其他高歧义服务。
- 迁移方式保持“`ops` 主实现 + `operations` 兼容壳”。

#### 第三批后续候选（已于最后一批常规迁移执行）

1. `moneyflow_reconcile_service.py`
2. `stock_basic_reconcile_service.py`

### 继续暂缓处理

继续暂缓（不进入第三批）：

1. `history_backfill_service.py`
2. `market_mood_walkforward_validation_service.py`

暂缓原因：

- `history_backfill_service`：运行时执行主链路关键节点，跨 foundation/ops/runtime/spec 组合复杂，需单独专项迁移计划。
- `market_mood_walkforward_validation_service`：当前直接依赖 biz（依赖矩阵白名单点），必须先做跨域职责拆分再迁移。

---

## 剩余 4 个 service 最终归属判定（本轮）

本节覆盖并收口以下 4 个未迁 service 的最终判定结论（仅归属判定，不实施代码迁移）：

- `history_backfill_service.py`
- `market_mood_walkforward_validation_service.py`
- `moneyflow_reconcile_service.py`
- `stock_basic_reconcile_service.py`

### 逐项最终判定

| service | 当前调用链（真实入口） | 依赖面（foundation / ops / biz / CLI / runtime） | 归属倾向 | 推荐最终归属 | 是否建议继续迁入 ops | 若不迁入 ops 的后续路径 | 风险点 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `history_backfill_service.py` | `src/ops/runtime/dispatcher.py`（`_run_backfill_job`） + `src/cli.py`（`backfill-*` 命令） + `src/ops/specs/registry.py`（`executor_kind=history_backfill_service`） | foundation：重依赖（DAOFactory、sync registry、contracts）；ops：通过 `SyncJobStateReconciliationService` 间接耦合；biz：无；CLI：是；runtime 主链路：是（核心） | ops 运行编排域（高耦合） | 目标仍应进入 `src/ops/services`，但需专项拆分后再迁 | 否（本轮不迁） | 进入“backfill 专项重构”：先拆资源路由/进度上报/状态回写 seam，再迁主实现，最后保留兼容壳 | 涉及执行器主链路、spec 执行类型、进度事件与状态一致性，误改会影响任务执行稳定性 |
| `market_mood_walkforward_validation_service.py` | `src/cli.py`（`ops-validate-market-mood`）+ 对应 CLI/服务单测 | foundation：大量读模型（core/core_serving）；ops：无主依赖；biz：直接依赖 `src.biz.services.market_mood_calculator`；CLI：是；runtime 主链路：否 | biz 分析能力（跨域） | 倾向迁入 `src/biz/services`（或拆为 biz 计算 + CLI 薄编排） | 否 | 进入“跨域边界专项”：先消除 `operations -> biz` 白名单违规，再决定 CLI 入口归属（ops 命令壳 or biz 命令壳） | 指标定义与 walk-forward 口径要保持完全一致；同时要消除依赖矩阵历史白名单 |
| `moneyflow_reconcile_service.py` | `src/cli.py`（`reconcile-moneyflow`）+ 对应 CLI/服务单测 + `src/operations/services/__init__.py` 导出 | foundation：读 `raw.moneyflow` + `raw_biying.moneyflow`；ops：无 runtime 耦合；biz：无；CLI：是；runtime 主链路：否 | ops 治理审计域 | `src/ops/services`（建议命名 `operations_moneyflow_reconcile_service.py`） | 是（可作为最后一批迁移候选） | 不适用 | 字段映射/阈值/样本抽样规则必须保持一致，避免对账结果漂移 |
| `stock_basic_reconcile_service.py` | `src/cli.py`（`reconcile-stock-basic`）+ 对应 CLI/服务单测 + `src/operations/services/__init__.py` 导出 | foundation：读 `core_multi.security_std`；ops：无 runtime 耦合；biz：无；CLI：是；runtime 主链路：否 | ops 治理审计域 | `src/ops/services`（建议命名 `operations_stock_basic_reconcile_service.py`） | 是（可作为最后一批迁移候选） | 不适用 | 名称/交易所规范化规则是结果口径核心，迁移时需防止细节变化 |

### 最终分组结论（本轮）

#### 继续暂缓

1. `history_backfill_service.py`
2. `market_mood_walkforward_validation_service.py`

#### 最后一批常规迁移（本轮仅两项）

1. `moneyflow_reconcile_service.py`
2. `stock_basic_reconcile_service.py`

#### 应转入专项重构（而非沿用常规迁移套路）

1. `history_backfill_service.py`：归入 backfill 主链路专项（运行时核心路径专项）。
2. `market_mood_walkforward_validation_service.py`：归入 operations->biz 跨域边界专项（先消除白名单违规，再定目录归属）。

---

## 最后一批常规 service 迁移（本轮执行）

本轮严格限定为两项 reconcile/audit service，不扩大范围：

1. `src/operations/services/moneyflow_reconcile_service.py`
2. `src/operations/services/stock_basic_reconcile_service.py`

执行策略：

- 主实现迁入 `src/ops/services/operations_moneyflow_reconcile_service.py`
- 主实现迁入 `src/ops/services/operations_stock_basic_reconcile_service.py`
- `src/operations/services/*` 旧路径保留 deprecated shim（模块级薄转发）
- 调用侧仅做最小切换（`src/operations/services/__init__.py` 聚合导出改为指向 `ops` 主实现）

本轮明确不处理：

- `history_backfill_service.py`
- `market_mood_walkforward_validation_service.py`
- platform 相关目录与接口

---

## post-cutover cleanup：`operations/services` 常规 shim 清理（本轮执行）

本轮目标（单目标）：

1. 删除 `src/operations/services` 中已迁移且无运行引用的常规 shim，保留两个专项真实实现不动。

迁移/删除前审计结果：

1. `src/tests/scripts` 里对常规 shim 的引用主要来自 `cli + tests`，均可机械切至 `src.ops.services.*` 主实现。
2. `history_backfill_service.py` 与 `market_mood_walkforward_validation_service.py` 仍为专项真实实现，保持原位。
3. 删除前完成旧导入路径替换后，常规 shim 模块路径在运行代码与测试中无残留引用。

本轮动作（已执行）：

1. 将 `src/cli.py` 中常规 services 导入从 `src.operations.services` 切到 `src.ops.services.operations_*`。
2. 将相关测试导入/monkeypatch 路径同步切到 `src.ops.services.operations_*`。
3. `history_backfill_service.py` 内部对 `SyncJobStateReconciliationService` 的依赖切到 `src.ops.services.operations_sync_job_state_reconciliation_service`。
4. 删除以下常规 shim 文件：
   - `daily_health_report_service.py`
   - `dataset_pipeline_mode_seed_service.py`
   - `dataset_status_snapshot_service.py`
   - `default_single_source_seed_service.py`
   - `execution_reconciliation_service.py`
   - `execution_service.py`
   - `moneyflow_multi_source_seed_service.py`
   - `moneyflow_reconcile_service.py`
   - `probe_runtime_service.py`
   - `schedule_planner.py`
   - `schedule_probe_binding_service.py`
   - `schedule_service.py`
   - `serving_light_refresh_service.py`
   - `stock_basic_reconcile_service.py`
   - `sync_job_state_reconciliation_service.py`

本轮结果：

1. `src/operations/services` 目录从“多 shim 混杂”收敛为“两个专项实现 + 最小导出壳”。
2. 常规 ops 治理服务主路径统一为 `src/ops/services/*`。
3. 当前剩余未迁专项仅两项：
   - `history_backfill_service.py`
   - `market_mood_walkforward_validation_service.py`
4. 新增护栏测试 `tests/architecture/test_operations_legacy_guardrails.py`，防止常规 shim 回流与旧导入反弹。

---

## 专项收口：`history_backfill_service` 主实现迁入 ops（本轮执行）

本轮目标（单目标）：

1. 将 `history_backfill_service` 主实现从 `src/operations/services` 迁入 `src/ops/services`，保留旧路径兼容壳。

迁移前审计结论：

1. `history_backfill_service` 为 runtime/CLI 主链路关键服务，已进入专项迁移窗口。
2. 当前调用点可控（`src/cli.py`、`src/ops/runtime/dispatcher.py`、`src/operations/services/__init__.py`）。
3. `tests/test_history_backfill_service.py` 大量使用旧路径 patch，迁移后需保留旧路径模块兼容。

本轮动作（已执行）：

1. 主实现迁移：
   - `src/operations/services/history_backfill_service.py` -> `src/ops/services/operations_history_backfill_service.py`
2. 旧路径兼容壳保留：
   - `src/operations/services/history_backfill_service.py` 改为 deprecated shim（模块薄转发）
3. 最小调用侧切换：
   - `src/ops/runtime/dispatcher.py` 改为从 `src.ops.services.operations_history_backfill_service` 导入
   - `src/cli.py` 改为从 `src.ops.services.operations_history_backfill_service` 导入
   - `src/operations/services/__init__.py` 中 `HistoryBackfillService/BackfillSummary` 导出改为指向 ops 主实现

本轮结果：

1. backfill 主实现已进入 `src/ops/services` 主承接目录。
2. 旧路径仍可用，确保测试 patch 与外部兼容不被破坏。
3. `src/operations/services` 剩余“真实专项实现”收敛为 1 项：
   - `market_mood_walkforward_validation_service.py`

---

## 专项收口：`market_mood_walkforward_validation_service` 迁入 biz（本轮执行）

本轮目标（单目标）：

1. 将跨域分析服务 `market_mood_walkforward_validation_service` 从 `operations/services` 迁入 `biz/services`，清理 `operations -> biz` 历史违规白名单。

迁移前审计结论：

1. 运行调用点集中在 `src/cli.py`，未进入 runtime 主链路。
2. 该服务语义属于业务分析域，且内部直接依赖 `src.biz.services.market_mood_calculator`。
3. `src/operations/services` 目录收尾目标要求继续减少真实实现。

本轮动作（已执行）：

1. 主实现迁移：
   - `src/operations/services/market_mood_walkforward_validation_service.py` -> `src/biz/services/market_mood_walkforward_validation_service.py`
2. 调用侧切换：
   - `src/cli.py` 改为从 `src.biz.services.market_mood_walkforward_validation_service` 导入
3. 过渡导出收敛：
   - `src/operations/services/__init__.py` 移除 `MarketMoodWalkForwardValidationService` 与 `MoodWalkForwardReport` 的导出
4. 护栏同步：
   - `tests/architecture/test_subsystem_dependency_matrix.py` 移除 `operations -> biz` 白名单项
   - `tests/architecture/test_operations_legacy_guardrails.py` 同步 `operations/services` 允许文件/导入集合

本轮结果：

1. `operations -> biz` 的历史白名单已清零。
2. `src/operations/services` 目录不再包含真实业务分析实现，仅剩最小兼容壳：
   - `history_backfill_service.py`（compat shim）
   - `__init__.py`（过渡导出壳）

---

## post-cutover cleanup：`operations/runtime` 与 `operations/specs` 旧引用收敛（本轮执行）

本轮目标（单目标）：

1. 仅清理 `tests + scripts` 对 `src.operations.runtime/*` 与 `src.operations.specs/*` 的旧导入，统一切到 `src.ops.*` 主路径。
2. 本轮不删除任何 `operations/runtime` 或 `operations/specs` 兼容壳文件。

迁移前审计结论：

1. 旧引用集中在测试与脚本，代码主链路已经走 `src.ops.*`。
2. `operations/runtime/*.py` 与 `operations/specs/*.py` 当前均为 deprecated shim（薄转发），可先做引用收敛再评估删除。

本轮动作（已执行）：

1. 脚本导入切换：
   - `scripts/generate_dataset_catalog.py`：`src.operations.specs.registry` -> `src.ops.specs.registry`
2. 测试导入切换：
   - `tests/web/test_ops_runtime.py`：`src.operations.runtime` 及 monkeypatch 路径 -> `src.ops.runtime`
   - `tests/test_ops_specs.py`
   - `tests/test_dataset_pipeline_mode_seed_service.py`
   - `tests/test_dataset_freshness_registry_validation.py`
   - `tests/test_default_single_source_seed_service.py`
   - `tests/test_ops_freshness_snapshot_query_service.py`
   - `tests/web/test_ops_freshness_api.py`
   以上均从 `src.operations.specs*` 切换到 `src.ops.specs*`
3. 本轮结束后，`tests + scripts` 范围内不再存在 `src.operations.runtime` / `src.operations.specs` 的直接引用。

回归结果：

1. `pytest -q tests/web/test_ops_runtime.py tests/test_ops_specs.py tests/test_dataset_pipeline_mode_seed_service.py tests/test_dataset_freshness_registry_validation.py tests/test_default_single_source_seed_service.py tests/test_ops_freshness_snapshot_query_service.py tests/web/test_ops_freshness_api.py` 通过（54 passed）。
2. `pytest -q tests/architecture/test_subsystem_dependency_matrix.py tests/architecture/test_operations_legacy_guardrails.py` 通过（4 passed）。

下一步建议：

1. 进入单点删除评估轮次：先审计 `src + tests + scripts + docs` 对 `src.operations.runtime.{dispatcher,scheduler,worker}` 与 `src.operations.specs.{dataset_freshness_spec,job_spec,observed_dataset_registry,registry,workflow_spec}` 的残留引用。
2. 若审计清零，再分两小轮删除 shim（先 runtime，后 specs），每轮只删一组并保留 `__init__.py` 聚合壳。

---

## post-cutover cleanup：`operations/runtime` shim 删除执行结果（3 项）

本轮目标（单目标）：

1. 仅删除 `src/operations/runtime` 下三个已无引用的 shim：
   - `dispatcher.py`
   - `scheduler.py`
   - `worker.py`

删除前审计结果：

1. 在 `src + tests + scripts + docs + README* + pyproject.toml + .github` 范围内，未检出对 `src.operations.runtime.dispatcher/scheduler/worker` 的导入引用。
2. 残留命中仅为三文件自身的模块文档字符串，不构成调用依赖。

本轮动作（已执行）：

1. 删除：
   - `src/operations/runtime/dispatcher.py`
   - `src/operations/runtime/scheduler.py`
   - `src/operations/runtime/worker.py`
2. 保留：
   - `src/operations/runtime/__init__.py`（兼容包壳，导出仍指向 `src.ops.runtime`）
3. 护栏增强：
   - `tests/architecture/test_operations_legacy_guardrails.py` 新增两条检查：
     - `operations/runtime` 目录仅允许保留 `__init__.py`
     - 禁止重新引入 `src.operations.runtime.dispatcher/scheduler/worker` 旧路径导入

回归结果：

1. `pytest -q tests/architecture/test_operations_legacy_guardrails.py tests/architecture/test_subsystem_dependency_matrix.py` 通过。
2. `pytest -q tests/web/test_ops_runtime.py` 通过。

下一步建议：

1. 对 `src/operations/specs/*` 五个 shim 做同样审计（先收敛引用，再单轮删除）。
2. 删除时仅处理 `dataset_freshness_spec.py/job_spec.py/observed_dataset_registry.py/registry.py/workflow_spec.py`，保留 `src/operations/specs/__init__.py` 作为包级过渡壳。

---

## post-cutover cleanup：`operations/specs` shim 删除执行结果（5 项）

本轮目标（单目标）：

1. 仅删除 `src/operations/specs` 下五个已无引用的 shim：
   - `dataset_freshness_spec.py`
   - `job_spec.py`
   - `observed_dataset_registry.py`
   - `registry.py`
   - `workflow_spec.py`

删除前审计结果：

1. 在 `src + tests + scripts + docs + README* + pyproject.toml + .github` 范围内，未检出对上述五个 `src.operations.specs.*` 子模块的导入引用。
2. 命中仅为两类：
   - 五个文件自身文档字符串
   - `ops-consolidation-plan` 的历史记录条目

本轮动作（已执行）：

1. 删除上述 5 个 shim 文件。
2. 保留：
   - `src/operations/specs/__init__.py`（包级兼容壳，继续导出 `src.ops.specs`）
3. 护栏增强：
   - `tests/architecture/test_operations_legacy_guardrails.py` 新增两条检查：
     - `operations/specs` 目录仅允许保留 `__init__.py`
     - 禁止重新引入五个已删除 `src.operations.specs.*` 旧路径导入

回归结果：

1. `pytest -q tests/architecture/test_operations_legacy_guardrails.py tests/architecture/test_subsystem_dependency_matrix.py` 通过。
2. `pytest -q tests/test_ops_specs.py tests/web/test_ops_freshness_api.py tests/test_dataset_freshness_registry_validation.py` 通过。

下一步建议：

1. 评估是否删除 `src/operations/runtime/__init__.py` 与 `src/operations/specs/__init__.py` 这两个包级过渡壳（需要先做全仓导入审计并判定是否仍有外部依赖窗口）。
2. 若暂不删，至少在 guardrail 中把 `operations/runtime|specs` 目录状态固定为“仅 `__init__.py` 可存在”。
