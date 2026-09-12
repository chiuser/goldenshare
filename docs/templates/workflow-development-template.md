# 工作流开发说明模板（Workflow Development Template）

更新时间：2026-09-12。适用于当前 Ops Workflow，不用于 Dagster job。运行事实见[工作流目录 §2](/Users/congming/github/goldenshare/docs/ops/ops-workflow-catalog-v1.md#2-工作流运行机制代码级)，字段以 [WorkflowDefinition/WorkflowStepDefinition](/Users/congming/github/goldenshare/src/ops/action_catalog.py)为准。模板要求填写目标与证据，不表示所有候选能力已经实现。

> 使用规则：
> - 每新增或重大调整一个 workflow，必须基于本模板新增一份文档，放在 `docs/ops/`。
> - 文档名建议：`ops-workflow-<workflow-key>-development.md`
> - 模板中的“必须/应当”视为交付门禁（Definition of Done）。

## 1. 基本信息

- Workflow Key：
- Workflow 显示名：
- 负责人：
- 关联需求/任务：
- 代码变更范围（文件）：

## 2. 设计目标与边界

- 目标：
- 非目标：
- 为什么需要 workflow（而不是单数据集 action）：

## 3. 调度与执行能力

- 是否支持自动调度：是/否
- 是否支持手动执行：是/否
- 默认调度策略（如有）：
- workflow_profile / time_regime：
- manual_enabled / schedule_enabled：
- failure_policy_default / resume_supported（分别说明声明值和实际执行证据）：
- 支持参数：
  - 参数名：
  - 类型：
  - 是否必填：
  - 默认值：
  - 对应业务语义：

## 4. 步骤编排清单（必须详细）

| 序号 | step_key | 显示名 | action_key / dataset_key | depends_on | default_params | params_override | failure_policy_override / max_retry_per_unit |
|---:|---|---|---|---|---|---|---|
| 1 |  |  |  |  |  |  |  |

补充说明：
- 为什么采用这个顺序：
- 当前按 steps 顺序串行；依赖关系如何由顺序保证：
- 失败后的影响范围：

当前 dispatcher 不按 depends_on/parallel_policy 做依赖阻塞或并行调度。需要这些新行为必须单独设计、批准和验证，不能只填写字段就声明支持。

## 5. 参数传递与覆盖规则

- 按真实合并顺序填写：request_payload_json → step.default_params → step.params_override，同名键后者覆盖前者；提供冲突样例与期望值：
- 时间输入如何经 dataset action resolver 归一化（不把 request params 当源接口参数）：
- 数据集 action 与 maintenance action 两种 step 的入口和参数消费者：

## 6. 异常与回滚策略

- 单 step 失败时整体状态：
- 部分成功时补偿策略：
- 取消请求处理策略：
- 可否安全重试：

区分目标与现状：步骤失败策略以 step override 优先、workflow default 次之，continue_on_error 可继续执行并形成 partial_success；不是自动补偿或依赖跳过。当前 workflow 异常分支统一捕获 Exception，不能承诺取消异常必然变 canceled，也不能把 resume_supported/max_retry_per_unit 字段当作已完成持久化续跑和自动重试的证据。逐项引用实现和测试；涉及新行为先批准，不在模板里补造承诺。

## 7. 可观测性与运维交互

- 进度上报粒度：
- TaskRun 与 node_type=workflow_step 的节点状态、计数和 issue 证据：
- 任务详情页需要展示的信息：

现行步骤观测使用 task_run_node/task_run_issue；不恢复旧 step_started/step_succeeded/... 事件契约。根 AGENTS 的 Prod 长任务约束适用时另行逐项对账。

## 8. 测试计划（必须落地）

- 单元测试：
  - 规格注册测试
  - 参数合成测试
- 集成测试：
  - 正常链路
  - 中途失败
  - 取消场景
- 回归测试：
  - 不影响既有 workflow
  - 不影响 catalog/schedule 页面

## 9. 发布与回滚

- 发布前检查项：
- 回滚策略（按 commit / 配置）：
- 风险提示：

发布和恢复操作遵循[正式发版流程](/Users/congming/github/goldenshare/docs/release/release-process-v1.md)；代码回退不自动撤销已提交数据，现有部署脚本不是固定旧 SHA 回滚工具。

## 10. 文档同步清单

- [ ] 更新 `docs/ops/ops-workflow-catalog-v1.md`
- [ ] 更新 `docs/README.md` 索引
- [ ] 如涉及交互变更，更新对应页面说明文档
- [ ] 提交信息明确标注 workflow 变更范围
