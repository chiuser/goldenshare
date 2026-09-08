# DatasetExecutionPlan 执行计划与可靠执行

更新时间：2026-09-08。状态：现行模型与执行约束说明。原重构主案和 M-1～M8 索引中的有效规则归入本文；历史步骤不是当前实施计划。本文区分代码事实与尚须按需求验证的可靠性目标。

## 1. 主链与职责

```text
手动 / Schedule / Workflow 意图
  -> Ops TaskRun 编排
  -> DatasetActionRequest
  -> DatasetActionResolver（读取 DatasetDefinition、校验、规划 units）
  -> DatasetExecutionPlan
  -> IngestionExecutor（拉取、归一化、校验、写入和提交）
  -> 结构化进度与结果 -> Ops TaskRun 观测
```

- Definition 是静态事实源；Plan 是本次请求的执行投影，不是第二份配置。
- Ops 负责触发、领取、停止、重试、任务状态和页面投影，不重新解释底层日期模型。
- Resolver/planner 属于 Foundation；request builder 只将已归一化的值映射为源接口参数。
- 执行器入口是 `IngestionExecutor`，不是旧草案中的 `DatasetPlanExecutor`。旧 sync/backfill/history 路由不得重新成为长期业务模型。
- 子系统目标边界与已知差距见 [架构基线](/Users/congming/github/goldenshare/docs/architecture/subsystem-boundary-plan.md)，不以本图证明下层反向依赖已全部清零。

当前实现入口：[execution_plan.py](/Users/congming/github/goldenshare/src/foundation/ingestion/execution_plan.py)、[resolver.py](/Users/congming/github/goldenshare/src/foundation/ingestion/resolver.py)、[unit_planner.py](/Users/congming/github/goldenshare/src/foundation/ingestion/unit_planner.py)、[executor.py](/Users/congming/github/goldenshare/src/foundation/ingestion/executor.py)、[TaskRun dispatcher](/Users/congming/github/goldenshare/src/ops/runtime/task_run_dispatcher.py)。

## 2. 请求与解析

`DatasetActionRequest` 承载 `dataset_key/action/time_input/filters` 及触发、请求人、schedule/workflow/run 上下文；当前 Resolver 维护动作是 `maintain`。

`DatasetTimeInput` 使用 `mode` 和相应日期/月字段：`trade_date/ann_date/start_date/end_date/month/start_month/end_month/date_field`。哪些组合合法由 Definition、动作能力及 validator 决定，不因为模型中存在字段就全部开放。

| 请求模式 | 内部 run_profile | 说明 |
| --- | --- | --- |
| `point` | `point_incremental` | 单点；可能是日期或月份键，不等于最后交易日 |
| `range` | `range_rebuild` | 日期/月份范围；名称不代表一定清空目标表 |
| `none` | `snapshot_refresh` | 无时间意图；名称不代表每种 writer 都整体替换 |

Resolver 先归一化并校验请求，再生成 units。月份键、自然月窗口和日期锚点的准确规则见 [日期指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)。禁止把股票与指数周/月线都归一化为最后交易日。

`plan_id` 按 dataset、action、run profile、校验后参数和 unit IDs 生成；它不是数据库行主键或断点记录。当前 `plan.filters` 保存的是校验后参数，可能包含归一化日期等执行参数，不能误当成用户原始筛选条件。

## 3. Plan 字段与 unit

完整字段以模型为准，以下只说明容易混淆的投影：

| 部分 | 主要内容与限制 |
| --- | --- |
| `time_scope` | 本次输入范围、模式、标签，不是完整日期模型 |
| `source` | 来源、adapter、API、源字段 |
| `planning` | `universe_policy`、`enum_fanout_fields/defaults`、`request_variant_fields/defaults`、分页策略、规模限制、拉取并发、unit 数量、分页处理模式 |
| `writing` | DAO、目标表、冲突键、write path、Serving 冲突策略、observation/stage、替换范围 |
| `quality` | 拒绝策略、空结果策略、写前校验器 |
| `transaction` | `commit_policy/idempotent_write_required/write_volume_assessment` |
| `observability` | 进度标签、取自 Definition 日期模型的 `observed_field/audit_applicable` |
| `units` | 本次展开后的 `PlanUnitSnapshot` 序列 |

Plan 没有 `planning.universe`、`enum_fanout` 或 `enum_defaults` 字段。对象池声明在 Definition，planner 使用后把具体对象写入 units；不要按旧文档补出另一份 Plan 配置。

一个 unit 保存 `unit_id`、dataset/source、日期、实际 `request_params`、`progress_context`，以及分页、请求变体等执行信息。`page_limit` 存在于 Definition planning 和 unit，而不是当前 PlanPlanning 的字段。

### 如何理解展开

日期/窗口、对象池、枚举组合与请求变体是不同维度：

- 对象池来源、优先级、显式代码限制见 [Definition 对象池合同](/Users/congming/github/goldenshare/docs/architecture/dataset-definition-single-source-refactor-plan-v1.md#universe-contract)。
- 枚举组合生成独立 unit；同一 unit 的 request variants 不能当作独立完成量。
- `index_daily` 的按代码窗口请求不改变其交易日观测语义；请求池与 Serving 筛选池不能合并。
- `index_weight` 的自然月窗口由 Resolver 归一化，planner 按代码和窗口构造请求。
- 全选必须是实际枚举集合，禁止 `__ALL__` 哨兵进入请求或数据。

不要只按 `unit_builder_key` 的名字判断粒度。修改 unit 之前必须核验 request builder、写入身份、进度、测试及实际规模。

## 4. 分页、内存与并发

| 模式 | 当前含义 |
| --- | --- |
| `buffer_all` | 默认聚合一个 unit 的分页结果后归一化、写入；不等于整个任务所有 unit 一起缓冲 |
| `staged_stream` | 显式选择逐页归一化并持久化到非服务 stage，完整 unit 校验后发布 Serving |

`staged_stream` 不是“每页业务数据都可以对外可见”。它受当前 [Definition linter](/Users/congming/github/goldenshare/src/foundation/ingestion/linter.py)的 stage DAO/table、write path、offset 分页、单并发和 `commit_policy=unit` 组合门禁约束；不能只切换一个字符串。

`pagination_policy=offset_limit` 表示通用 offset/limit 分页；`none` 表示不使用该通用分页策略，不保证单请求一定覆盖全集。结束条件、上限和分页一致性须按 source client 与数据集合同验证。

拉取并发不等于多线程共享写库 session；当前 linter 对 `fetch_concurrency` 限定 1～4，专用路径还有更严格约束。具体并发设计与未完成验收留在 [源端拉取并发专题](/Users/congming/github/goldenshare/docs/architecture/dataset-fetch-concurrency-execution-plan-v1.md)，本次合并不将其升级为生产已验收。

## 5. 提交、幂等与取消

### 当前可用提交策略

| `commit_policy` | 边界 |
| --- | --- |
| `unit` | 按 planned unit 完成业务提交；隔离 stage 的页持久化不是业务发布 |
| `raw_then_serving` | 仅 `fund_daily` 专用两阶段 write path；先提交 Raw，再提交 Serving，Serving 失败不能回滚已提交 Raw |

当前合同没有 `data_commit_policy/ops_state_policy`，也没有 `per_unit/per_execution` 取值。不得据旧示例创建无效配置，或恢复任务末尾统一提交的大事务。

### 必须维持的安全要求

1. 数据提交与 Ops 状态观察分离。TaskRun、freshness、snapshot 等状态失败不得回滚、阻塞或污染已获准的业务写入。
2. DAO 的 batch size 只是 SQL 分批，不是事务分段。writer 写入成功、业务 commit 成功、TaskRun 状态成功是三件事。
3. 行级幂等由真实冲突键、替换范围和 writer 决定；unit_id/plan_id 不能替代行身份。
4. 后续 unit 失败或取消，不得回滚之前已提交 unit；不把部分处理的 unit 标为已完成。
5. 逐 unit/页取消检查、内存上限、持久化续跑、进度与终态一致按 [根 AGENTS 的 Prod 长任务门禁](/Users/congming/github/goldenshare/AGENTS.md#prod-数据集长任务可恢复性与可观测性门禁)和 [模板 §0.3.5](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)评审及验收。DG/Lake 使用自己的规则，不套用本合同。
6. 不因已有 unit commit 就声称通用“进程退出后可靠续跑”已经完成；必须证明续跑依据持久化、重放幂等和真实取消—续跑结果。
7. 迁移工具的按表事务、大表重建与日常 ingestion 不是同一条链；迁移需单独授权和规模评估，不自动继承安全结论。

### 历史事故保留的原因

2026-04 原重构记录记载：一次 `stk_mins` 约 1.2 亿行任务，把数据与两个状态创建动作放在最终同一事务提交；状态唯一键冲突导致业务成果回滚。这是历史记录，不是本轮重新测量或当前仍存在该旧服务的结论。

必须保留的教训是：按业务单元提交、状态幂等且与业务隔离、提交后才报告完成量。原停机清空、重新 seed、旧服务删除的施工步骤不再作为当前指令。风险跟踪继续看 [工程风险登记簿](/Users/congming/github/goldenshare/docs/governance/engineering-risk-register.md)，不在本文重复维护另一份状态账本。

## 6. 进度与状态：当前事实和目标分开

当前 [ProgressSnapshot](/Users/congming/github/goldenshare/src/foundation/ingestion/progress.py)提供结构化进度；`IngestionExecutor._build_progress_message()` 仍生成中文 message。因此不能写“Foundation 当前只上报结构化数据、不生成文案”。

原“文案统一由 Ops 格式化”保留为架构方向，不是本次已完成事项，也不在文档整理中启动代码改造。

展示必须分清：

- `rows_fetched`：源端读取量。
- `rows_written`：写入执行量，不单独证明事务提交。
- `rows_committed`：已提交业务量；stage 行数不能冒充 Serving 已发布量。
- 拒绝量与原因、当前阶段、当前 unit、完成/总量和更新时间；心跳不能替代业务进度。

中文字段标签优先取 Definition/display label，错误和原因须进入 [codebook.py](/Users/congming/github/goldenshare/src/foundation/ingestion/codebook.py)，不让前端猜机器 token。TaskRun/node 终态、部分提交和状态失败的实际呈现按 [TaskRun 观测专题](/Users/congming/github/goldenshare/docs/ops/ops-task-run-observability-redesign-plan-v1.md)核验。

原草案的 `record_execution_outcome(...)`、`coverage_status`、状态对账队列等名称不作为现行字段/API 承诺；状态隔离和可对账的要求仍保留，不能凭目标名称宣布实现完成。

## 7. Workflow、Schedule 与接口

Workflow step 引用 dataset action，Schedule 绑定动作或 workflow；二者表达触发/业务意图，不恢复旧 job/spec 路由。流程可包含其他现行维护动作，不能把全部 workflow step 强制改成数据集同步。

时间形状、默认时间制度与数据集锚点的区别统一见 [日期指南的 Workflow 说明](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md#workflow-time)。实际接口与 TaskRun 字段看 [Ops 当前契约](/Users/congming/github/goldenshare/docs/ops/ops-contract-current.md)，不使用旧方案中拟建的 execution API 作为实现参考。

## 8. 验证入口与本轮边界

代码改动按 [数据集模板 §8](/Users/congming/github/goldenshare/docs/templates/dataset-development-template.md)选择 registry、resolver、writer/executor、Ops/API、前端与真实最小验收；只创建 TaskRun 或通过静态 lint，不证明请求范围、目标行数或恢复行为正确。

当前关键证据入口：

- [registry 测试](/Users/congming/github/goldenshare/tests/test_dataset_definition_registry.py)、[resolver 测试](/Users/congming/github/goldenshare/tests/test_dataset_action_resolver.py)。
- [fund_daily 两阶段执行测试](/Users/congming/github/goldenshare/tests/test_ingestion_executor_fund_daily_two_phase.py)。
- [维护模型护栏](/Users/congming/github/goldenshare/tests/architecture/test_dataset_maintenance_refactor_guardrails.py)、[codebook 护栏](/Users/congming/github/goldenshare/tests/architecture/test_dataset_codebook_guardrails.py)。
- 旧执行模型防回流、依赖边界与通用验证入口见 [子系统架构基线](/Users/congming/github/goldenshare/docs/architecture/subsystem-boundary-plan.md#architecture-guardrails)。

本次只合并文档、纠正现状描述，不新增字段、状态机、Worker、迁移或生产动作，也不宣称完成未验收的长任务与运行态治理目标。
