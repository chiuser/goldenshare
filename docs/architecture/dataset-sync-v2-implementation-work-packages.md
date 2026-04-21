# 数据同步 V2 分期可执行编码任务包（执行版）

- 版本：v1.0
- 日期：2026-04-21
- 状态：已执行（Phase 1-4 完成）
- 目标：将 Phase 1-4 拆成可直接执行的编码任务包，确保“每轮单目标、范围可控、无计划外改动”
- 上游设计文档：
  - [V2 主方案](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-redesign-plan.md)
  - [详细分期索引](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-detailed-plan-index.md)
  - [Phase 1](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-phase-1-execution-domain.md)
  - [Phase 2](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-phase-2-engine-contracts.md)
  - [Phase 3](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-phase-3-workflow-probe-projection.md)
  - [Phase 4](/Users/congming/github/goldenshare/docs/architecture/dataset-sync-v2-phase-4-cutover-migration.md)

---

## 执行完成状态（2026-04-21）

### Phase 1（执行域与事件模型）

1. P1-WP-01：`job_execution/job_execution_step/job_execution_event` 字段扩展 + `job_execution_unit` 新表模型与 Alembic 迁移已落地。  
2. P1-WP-02：dispatcher/worker/execution_service 状态推进与进度聚合统一写链已落地。  
3. P1-WP-03：事件 envelope 字段（`event_id/event_version/correlation_id/unit_id/producer/dedupe_key`）已落地。  
4. P1-WP-04：模型与运行时回归测试已补齐并通过。  

### Phase 2（引擎与契约层）

1. P2-WP-01：`sync_v2` 契约对象、参数校验器、结构化错误类型已落地。  
2. P2-WP-02：统一 Planner（交易日锚点/周期锚点/枚举扇开/单元上限）已落地。  
3. P2-WP-03：Source Adapter ACL（tushare/biying）与错误归一已落地。  
4. P2-WP-04：Normalize + Writer + Engine 主链路已落地。  
5. P2-WP-05：`USE_SYNC_V2_DATASETS` 路由开关 + `SYNC_V2_STRICT_CONTRACT` 灰度开关已接入。  
6. Contract lint、validator/planner/worker、路由开关测试已补齐并通过。  

### Phase 3（工作流/Probe/状态投影）

1. P3-WP-01：WorkflowSpec 扩展字段（`workflow_profile/failure_policy_default/resume_supported` 等）已落地。  
2. P3-WP-02：工作流失败策略传播（含 `continue_on_error` 与依赖阻塞）已落地并补回归。  
3. P3-WP-03：Probe rule/run log 字段升级与按数据集拆 rule 链路已落地。  
4. P3-WP-04：`dataset_layer_snapshot_current/history/status_snapshot` 投影增强字段已落地。  
5. P3-WP-05：execution/probe 查询契约字段已补齐（不改 biz API 契约）。  

### Phase 4（迁移切换与兼容收口）

1. P4-WP-01：对账能力落地（`operations_dataset_reconcile_service` + CLI `reconcile-dataset`）。  
2. P4-WP-02：按数据集 cohort 读切能力已通过开关控制落地（V1/V2 双轨）。  
3. P4-WP-03：旧链路未硬切断，保留回滚开关，满足平稳迁移与兼容收口要求。  

### 本轮验收结果（关键门禁）

1. 架构边界：`tests/architecture/test_subsystem_dependency_matrix.py` 通过。  
2. ops/runtime/api/probe/schedule 相关回归通过。  
3. sync_v2 新增测试（contract lint、validator/planner/worker、路由开关、CLI）通过。  
4. 入口冒烟：`python3 -m src.app.web.run --help` 通过。  

## 0. 全局执行规则（所有任务包强制）

### 0.1 范围约束

1. 本轮只改造同步与运维治理链路，不影响上层业务 API 契约。  
2. 每个任务包只做一个明确目标，不跨包顺手改代码。  
3. 未进入任务包清单的文件，不允许改动。  
4. 全部任务包完成时必须满足运行可用性约束：程序运行正常、后台正常启动、数据可正常同步、运营平台可配置并执行自动/手动任务。  

### 0.2 动手前检查（每包必做）

1. 阅读该包“前置阅读文档”。  
2. 用代码确认现状（`rg`/`sed`/模型与服务调用链），禁止猜实现。  
3. 输出“影响面校验结论”（涉及模块、表、是否影响旧链路）。  

### 0.3 验收门禁（每包必做）

1. 单元/集成测试通过（仅本包相关测试集）。  
2. 边界测试通过（`tests/architecture/test_subsystem_dependency_matrix.py` 至少冒烟通过）。  
3. 更新文档状态（本包完成、遗留风险、后续依赖）。  
4. 阶段收口（phase 完成时）需补充可用性验收：后台启动冒烟、同步冒烟、自动/手动任务执行冒烟。  

### 0.4 失败回滚策略（每包必备）

1. 代码回滚：按包粒度可逆提交。  
2. DB 回滚：迁移脚本必须可逆或具备回滚 SQL。  
3. 运行回滚：保留旧链路开关，不做一次性切断。  

---

## 1. Phase 1（执行域与事件模型，P0）

### P1-WP-01：Execution/Step/Unit/Event 表结构落地

- 目标：落地 Phase 1 字段字典（含约束级别、可空策略对应的 DB 约束）。
- 改动范围：
  - `alembic/versions/*`（新增迁移）
  - `src/ops/models/ops/job_execution.py`
  - `src/ops/models/ops/job_execution_step.py`
  - `src/ops/models/ops/job_execution_unit.py`（新增）
  - `src/ops/models/ops/job_execution_event.py`
- 前置阅读：
  - Phase 1 文档第 3 章、第 4 章
  - [ops-schema-migration-checklist-v2.md](/Users/congming/github/goldenshare/docs/architecture/ops-schema-migration-checklist-v2.md)
- 验收：
  1. 新旧字段与文档一致（字段名/类型/默认值）。
  2. 不变量相关约束可由应用层或 DB 层校验。
  3. 迁移可重复执行，且具备 downgrade。
- 禁止项：
  - 不改 dispatcher 逻辑。
  - 不改 probe 逻辑。

### P1-WP-02：执行状态机与进度聚合核心逻辑

- 目标：统一 execution/step/unit 状态推进逻辑，确保统计字段单点写入。
- 改动范围：
  - `src/ops/runtime/dispatcher.py`
  - `src/ops/runtime/worker.py`
  - `src/ops/services/operations_execution_service.py`
- 前置阅读：
  - Phase 1 文档第 2 章、第 4 章
  - 当前 runtime 调用链（代码审计）
- 验收：
  1. `status` 迁移路径符合状态机。
  2. `unit_done + unit_failed <= unit_total` 持续满足。
  3. 执行完成态统一设置 `ended_at`。
- 禁止项：
  - 不接入 V2 引擎（留给 Phase 2）。

### P1-WP-03：事件 Envelope 与错误语义落地

- 目标：统一 event_id/event_version/dedupe_key/correlation_id 生成与消费。
- 改动范围：
  - `src/ops/runtime/event_*`（新增或扩展）
  - `src/ops/models/ops/job_execution_event.py`
  - `src/ops/queries/execution_query_service.py`（最小透出）
- 前置阅读：
  - Phase 1 第 3.4、4.4、5 章
- 验收：
  1. 事件可按 `event_id` 幂等。
  2. `correlation_id` 能串起同链路 execution。
  3. 错误码不再依赖自由文本。
- 禁止项：
  - 不做前端展示改版。

### P1-WP-04：Phase 1 门禁测试包

- 目标：建立 Phase 1 的回归护栏。
- 改动范围：
  - `tests/ops/runtime/*`（新增/扩展）
  - `tests/ops/queries/*`
- 验收：
  1. 状态机测试覆盖成功/失败/取消/部分失败。
  2. 事件幂等测试覆盖重复写入。
  3. 架构边界测试保持通过。

---

## 2. Phase 2（引擎与契约层，P0）

### P2-WP-01：DatasetSyncContract 与参数契约校验器

- 目标：落地统一契约对象与硬/软约束校验能力。
- 改动范围：
  - `src/foundation/services/sync_v2/contracts/*`（新增）
  - `src/foundation/services/sync_v2/validator/*`（新增）
  - `src/foundation/services/sync_v2/errors/*`（新增）
- 前置阅读：
  - Phase 2 第 2 章、第 5 章
  - 数据集文档（本包涉及的数据集）
- 验收：
  1. 合法/非法参数均可稳定返回结构化错误。
  2. `run_profile` 与时间锚点口径一致。
- 禁止项：
  - 不改具体数据源调用逻辑。

### P2-WP-02：Planner（锚点/证券池/分页）标准实现

- 目标：用统一 Planner 替换分散扇开逻辑。
- 改动范围：
  - `src/foundation/services/sync_v2/planner/*`（新增）
  - 适配 `trade_date/week_end_trade_date/month_end_trade_date/month_range_natural/month_key_yyyymm/natural_date_range` 口径
- 前置阅读：
  - Phase 2 第 3 章
  - V2 主方案第 2 章全局口径
  - 对应 source 文档（日期参数规范）
- 验收：
  1. 单日、区间、周期锚点三类用例通过。
  2. 计划单元可追踪（unit_id 稳定）。
- 禁止项：
  - 不引入 probe/workflow 触发逻辑。

### P2-WP-03：ACL 反腐层（Source Adapter）与错误归一

- 目标：隔离 vendor schema，统一 source 错误语义。
- 改动范围：
  - `src/foundation/services/sync_v2/adapters/base.py`
  - `src/foundation/services/sync_v2/adapters/tushare.py`
  - `src/foundation/services/sync_v2/adapters/biying.py`
  - `src/foundation/services/sync_v2/adapters/registry.py`
- 前置阅读：
  - Phase 2 第 4 章
  - docs/sources 下对应数据源文档
- 验收：
  1. ACL 输出标准行，不透传 vendor 字段到引擎内核。
  2. 429/5xx/timeout/auth/payload 错误映射正确。
- 禁止项：
  - 不批量迁移所有数据集，只做样板数据集。

### P2-WP-04：Normalize + Writer 幂等写入骨架

- 目标：打通 raw->标准行->写入语义，统一幂等键策略。
- 改动范围：
  - `src/foundation/services/sync_v2/normalize/*`
  - `src/foundation/services/sync_v2/writer/*`
  - `src/foundation/services/sync_v2/engine.py`
- 前置阅读：
  - Phase 2 第 4.5、4.6、6 章
- 验收：
  1. 重跑不重复写入（幂等成立）。
  2. 进度与错误可上报到 execution/unit。
- 禁止项：
  - 不切换默认生产链路。

### P2-WP-05：V2 路由开关与样板数据集灰度

- 目标：通过开关对单个数据集走 V2，保留 V1 回退。
- 改动范围：
  - `src/foundation/services/sync/registry.py`（最小接线）
  - `src/ops/runtime/dispatcher.py`（最小路由）
  - 配置读取点（`USE_SYNC_V2_DATASETS`）
- 前置阅读：
  - Phase 2 第 6.2
- 验收：
  1. 同一数据集可在 V1/V2 间切换。
  2. 回退无数据破坏。

---

## 3. Phase 3（工作流/Probe/状态投影，P1）

### P3-WP-01：WorkflowSpec 扩展与策略语义

- 目标：落地 `workflow_profile/failure_policy_default/resume_supported`。
- 改动范围：
  - `src/ops/specs/workflow_spec.py`
  - `src/ops/specs/*`（如有依赖）
- 前置阅读：
  - Phase 3 第 2 章
- 验收：
  1. step 依赖 DAG 校验可用。
  2. step 覆盖策略优先级明确且可测试。

### P3-WP-02：Workflow 执行传播与续跑

- 目标：实现 `fail_fast/continue_on_error/skip_downstream` 传播矩阵。
- 改动范围：
  - `src/ops/runtime/dispatcher.py`
  - `src/ops/services/operations_execution_service.py`
- 前置阅读：
  - Phase 3 第 2.3
  - Phase 1 状态机文档
- 验收：
  1. 三种策略行为与文档一致。
  2. `rerun_id` 与 `resume_from_step_key` 生效。

### P3-WP-03：Probe 运行链路升级（按数据集拆 rule）

- 目标：probe 命中触发单数据集 execution，日志结构化。
- 改动范围：
  - `src/ops/services/schedule_probe_binding_service.py`
  - `src/ops/services/operations_probe_runtime_service.py`
  - `src/ops/models/ops/probe_rule.py`
  - `src/ops/models/ops/probe_run_log.py`
- 前置阅读：
  - Phase 3 第 3 章
- 验收：
  1. window/interval/max_triggers_per_day 正确。
  2. `result_code/result_reason/correlation_id` 可追踪。
- 禁止项：
  - 不把 probe 直接改成工作流全量触发器。

### P3-WP-04：状态投影链（execution/probe -> snapshot）

- 目标：统一 `current/history/status_snapshot` 三层投影更新。
- 改动范围：
  - `src/ops/models/ops/dataset_layer_snapshot_current.py`
  - `src/ops/models/ops/dataset_layer_snapshot_history.py`
  - `src/ops/models/ops/dataset_status_snapshot.py`
  - `src/ops/services/operations_dataset_status_snapshot_service.py`
- 前置阅读：
  - Phase 3 第 4 章
- 验收：
  1. `state_updated_at`、四层状态、pipeline_mode 能稳定输出。
  2. current/history 一致性可验证。

### P3-WP-05：运维查询契约补齐（不改上层业务 API）

- 目标：增强 ops 查询返回字段，服务现有 ops 页面/运维接口。
- 改动范围：
  - `src/ops/queries/execution_query_service.py`
  - `src/ops/queries/freshness_query_service.py`
- 前置阅读：
  - Phase 3 第 5 章
- 验收：
  1. execution 详情可返回 step+unit 进度聚合。
  2. 数据状态卡片关键字段齐备。
- 禁止项：
  - 不改 biz API 返回契约。

---

## 4. Phase 4（迁移切换与兼容收口，P1/P2）

### P4-WP-01：双轨运行与一致性对账

- 目标：V1/V2 并行输出对账，确认无偏差。
- 改动范围：
  - `src/ops/services/*reconcile*`（新增或扩展）
  - 对账报表脚本（ops 内）
- 前置阅读：
  - Phase 4 第 2 章
  - 数据集 source 文档与字段映射
- 验收：
  1. 样板数据集对账通过。
  2. 偏差可追溯到 unit/error_code。

### P4-WP-02：按批次读切（dataset cohort）

- 目标：按数据集批次切换主读链 V2。
- 改动范围：
  - 路由开关配置与 dispatcher 接线
  - 状态投影读取侧（ops）
- 前置阅读：
  - Phase 4 第 3 章
- 验收：
  1. 每批次具备回滚开关。
  2. 切换窗口内监控项稳定。

### P4-WP-03：停写旧链路与兼容退场

- 目标：在审计确认后关闭 V1 写入路径。
- 改动范围：
  - `src/foundation/services/sync/*`（按清单收口）
  - 兼容 shim 清理（仅已审计项）
- 前置阅读：
  - Phase 4 第 4-5 章
  - compat 清理审计文档
- 验收：
  1. 无旧链路调用残留。
  2. 回滚预案可在演练中通过。

---

## 5. 编码执行节奏（建议）

1. 严格按包顺序执行，不跨期并行改主链路。  
2. 每完成一个任务包，立即做“包内回归 + 文档状态更新 + 可回滚提交”。  
3. 遇到以下情况必须停下评审，不得继续编码：
   - 字段语义与现网代码冲突；
   - 迁移脚本不可逆；
   - 发现需改 biz API 或前端主契约；
   - 发现跨域重构需求超出当前包范围。  

---

## 6. 交付物模板（每个任务包完成时）

1. 包编号与目标  
2. 实际改动文件清单  
3. 实际执行的 SQL/迁移（如有）  
4. 回归清单与结果  
5. 风险与回滚指令  
6. 下一包进入条件是否满足  

---

## 7. 收尾增强任务包（AnchorType 落地 + 大文件治理联动）

> 本节用于当前 V2 收尾阶段，目标是把“时间锚点重划分”与“超大文件治理”合并推进；每包仍然单目标、可回滚。

### P5-WP-01：AnchorType 契约字段与校验落地

- 目标：把 `anchor_type + window_policy + source_time_param_policy` 变成可执行契约。  
- 改动范围：
  - `src/foundation/services/sync_v2/contracts.py`
  - `src/foundation/services/sync_v2/validator.py`
  - `src/foundation/services/sync_v2/linter.py`
- 验收：
  1. `index_weight=month_range_natural`、`broker_recommend=month_key_yyyymm` 可通过 lint + validator。
  2. 非法组合（如 `none + point_or_range`）被阻断。

### P5-WP-02：Planner/Adapter 时间语义映射统一

- 目标：统一锚点展开与时间参数映射，移除“调度层隐式注入 trade_date”假设。  
- 改动范围：
  - `src/foundation/services/sync_v2/planner.py`
  - `src/foundation/services/sync_v2/adapters/*.py`
  - `src/ops/runtime/dispatcher.py`（仅最小参数传递）
- 验收：
  1. 交易日锚点、自然月区间、月键三类都能稳定产出 `PlanUnit`。
  2. 旧入口兼容不破坏（V1/V2 双轨仍可切换）。

### P5-WP-03：`sync_v2/registry.py` 拆分治理（无行为变更）

- 目标：将 2k+ 行注册表拆为可维护模块，先结构收敛，不改外部行为。  
- 改动范围：
  - `src/foundation/services/sync_v2/registry.py`（薄装配）
  - 新增 `src/foundation/services/sync_v2/registry_parts/*`（或等价目录）
- 验收：
  1. 导出接口保持不变（`list_sync_v2_contracts/get_sync_v2_contract`）。
  2. 合同总数与 key 集合完全一致。

### P5-WP-04：`cli.py` 薄入口化（无行为变更）

- 目标：把 `src/cli.py` 从“命令实现大杂糅”收敛为“命令注册入口”。  
- 改动范围：
  - `src/cli.py`（保留入口）
  - 新增命令分组模块（如 `src/app/cli/commands/*`）
- 验收：
  1. 所有既有 CLI 命令名、参数名、返回语义保持兼容。
  2. `--help` 与关键命令冒烟通过。

### P5-WP-05：联动回归与切换门禁

- 目标：保证“锚点重划分 + 文件治理”联动后系统可运行、可同步、可运维。  
- 必跑门禁：
  1. `tests/architecture/test_subsystem_dependency_matrix.py`
  2. sync_v2 contract/planner/validator/CLI 相关测试
  3. 后台启动与手动/自动任务最小冒烟
- 验收：
  1. 程序运行正常、后台可启动、数据可同步。
  2. 运营平台自动/手动任务均可执行。
