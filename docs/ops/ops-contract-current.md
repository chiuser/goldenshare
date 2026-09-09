# Ops 当前契约（统一版）

更新时间：2026-09-09（手动维护专题合并与已核验边界纠偏；不代表全部 Ops 能力重新验收）
适用范围：`src/ops/*`、`src/app/*`、`src/foundation/*`（Ops 相关）

---

## 1. 目的

本文件是 Ops 职责与行为边界的统一入口，当前实现以代码和对应测试为依据。接口字段由 [API 参考](/Users/congming/github/goldenshare/docs/ops/ops-api-reference-v1.md)维护，工作流明细由 [Workflow 清单](/Users/congming/github/goldenshare/docs/ops/ops-workflow-catalog-v1.md)维护。本文收口：

1. 多源运维契约（页面与对象边界）
2. 数据源卡片与治理对象查询契约
3. 数据集 pipeline mode 与层级观测契约
4. 数据集停用策略（`disabled` 状态语义）
5. 融合策略中心准备度与上线前置条件
6. 手动维护的动作来源、时间输入与页面边界

已合并的历史全文从 Git 追溯，不再维护平行规则或已完成的施工步骤。

---

## 2. 信息架构（当前）

### 2.1 数据状态总览

目标：按数据集查看 freshness 健康度与风险分级。
要求：

1. 卡片点击进入数据集详情
2. “去处理”跳转任务中心并携带上下文
3. 支持显示模式标识（单源服务/多源融合/raw-only 等静态存储事实）

### 2.2 数据源管理

目标：按 source 维度查看上游可用性与失败情况。  
边界：

1. 只展示该 source 下数据集的统一 freshness 健康度
2. 不承载策略编辑逻辑
3. 不承载复杂发布流程

### 2.3 任务中心

目标：统一承接手动同步、自动调度、任务记录。  
要求：

1. 调度支持 cron/probe
2. 任务详情可追踪 TaskRun 节点进度与问题摘要
3. 保持与 `ops.task_run / task_run_node / task_run_issue` 体系一致

### 2.3.1 任务中心执行语义（已确认）

当前确认口径：

1. 任务中心采用**队列模型**
2. Web/API 负责创建、查询、重试、取消 TaskRun 请求
3. Web 不是长任务执行 owner，不在请求内直接跑同步任务
4. 真正执行由独立 scheduler / worker 进程推进

前端展示口径：

1. 使用“提交任务”“重新提交”“请求停止”“等待处理”“正在处理”
2. 不再使用历史“立即执行”类文案作为主文案
3. 用户点击动作后，默认预期是“任务进入队列并等待 worker 处理”

后端契约要求：

1. 任务查询、重试、取消使用 `/api/v1/ops/task-runs*`；手动维护提交使用 `/api/v1/ops/manual-actions/{action_key}/task-runs`
2. 旧任务运行 API 主链已下线，不作为当前契约入口
3. `/api/v1/ops/runtime/*` 不作为新 UI 的正常执行入口

### 2.4 审查中心

目标：按指数、板块等领域审查数据，并提供明确授权的运营维护入口。

边界：

1. 数据审查查询与维护动作分开；当前支持管理员通过 `POST /api/v1/ops/review/index/active` 添加、通过 `DELETE /api/v1/ops/review/index/active/{ts_code}` 移除活跃指数，不能将整个审查中心描述为只读
2. 按领域组织路由，避免按技术对象暴露

---

## 3. 核心对象模型

### 3.1 `DatasetDefinition -> DatasetCard/Freshness Projection`

用途：从 DatasetDefinition 派生数据集来源、raw 表、目标表、交付模式、维护入口和 freshness 观测目标等静态事实。
约束：Ops 页面和查询层不得再依赖旧数据集模式落库表，也不得自行推断这些事实。

### 3.1.1 Ops 数据集展示目录

用途：统一数据源页、今日运行 / 数据状态总览、手动任务、自动任务和数据集审计页的用户可见数据集分组。

当前口径：

1. 默认展示目录为 `ops_dataset_default`。
2. 配置事实位于 `src/ops/catalog/dataset_catalog_views.py`。
3. 解析与缺配置校验位于 `src/ops/catalog/dataset_catalog_view_resolver.py`。
4. API 面向前端的展示目录字段统一使用 `group_key/group_label/group_order/item_order`。
5. `DatasetDefinition.domain` 仍是底层领域事实，可作为 item 补充字段返回，但不得再作为 UI 分组事实。
6. 新增数据集必须补齐默认展示目录配置；缺配置不允许静默落入“其他”。

### 3.2 `ops.dataset_status_snapshot`

用途：保存 freshness 观测与状态投影，并向日期完整性规则列表提供已观测范围；不是业务数据事实源，与 Kopia 备份无关。
来源：`DatasetDefinition` 的日期模型、显式 freshness Policy、源端发布策略，加上真实目标表观测与 TaskRun 成功/失败信息。
约束：

1. 该表是现行共享状态投影，必须保留；读取范围不等于已经完成该范围的完整性审计。
2. 页面查询层只能读取缓存中的观测事实，并按当前北京时间业务日轻量重算 `expected_business_date / lag_days / freshness_status`。
3. 页面查询不得因为缓存日期不一致或字段缺失而同步扫描真实业务表。后台状态重建、任务完成后的资源刷新及本地 freshness 探测承担观测；页面不扫描是设计要求，空快照/读取异常仍有实时回退的实现差距见[Freshness 查询边界](/Users/congming/github/goldenshare/docs/ops/ops-freshness-policy-explicit-mapping-plan-v1.md#query-safety-gap)，本轮不改代码、不放宽要求。
4. 不再保存 raw/std/resolution/serving 分层状态。
5. 不再由已退场的分层观测旧表推导页面健康度。

策略、阈值、失败展示与退场证据统一见 [Freshness 现行契约](/Users/congming/github/goldenshare/docs/ops/ops-freshness-policy-explicit-mapping-plan-v1.md)。

### 3.3 相关运行对象

1. `ops.task_run`：一次任务运行的唯一主记录
2. `ops.task_run_node`：任务内部阶段、单元与进度节点
3. `ops.task_run_issue`：失败原因、问题摘要与完整技术诊断唯一落点
4. `ops.schedule`：调度对象；目标对象统一用 `target_type/target_key` 表达
5. `ops.probe_rule`：探测触发规则

已退场对象：

1. 旧执行观测主链：已被 TaskRun 三表替代
2. 旧内部运行日志：不再作为任务详情或页面事实源
3. 旧数据集模式配置表：已由 DatasetDefinition 派生投影替代
4. 旧分层观测链路：不再作为数据集健康度或页面事实源

---

## 4. 查询契约

### 4.1 推荐主查询接口

1. `GET /api/v1/ops/dataset-cards`
2. `GET /api/v1/ops/freshness`

## 5. 交付模式事实

Dataset 卡片的交付模式直接读取 `DatasetDefinition.storage.delivery_mode`，层级计划读取 `storage.layer_plan`；查询层只映射展示标签，不再按 `target_table` 前缀推断模式或执行旧 seed 规则。实现见 [DatasetCardQueryService](/Users/congming/github/goldenshare/src/ops/queries/dataset_card_query_service.py)。

---

## 6. 运维规则（必须遵守）

1. 页面口径优先读取统一读模型，不在前端临时拼装状态
2. 交付模式等静态事实必须来自 DatasetDefinition，不允许页面自行推断
3. 新增数据集必须接入 Ops 可观测能力，不允许“只落表不可见”
4. 页面文案优先业务语义，不暴露底层字段实现细节
5. `disabled` 数据集可见但不计入滞后/失败告警统计
6. 停用能力当前为代码级控制，后续应收敛到配置化控制表
7. 任务动作默认采用队列语义，不在 Web 层暴露“立即执行长任务”的主交互
8. 新增任务 API 时，优先围绕 `TaskRun -> queued -> worker claim -> running -> terminal` 生命周期设计

---

## 7. 数据集停用策略（当前口径）

目标：

1. 保留同步能力（手动/自动任务仍可执行）
2. 从健康度重点告警中剔除停用数据集
3. 在总览和详情明确展示“已停用”

当前实现边界：

1. 停用名单由代码常量维护（非数据库配置）
2. 仅影响观测与展示口径，不影响执行能力
3. 前端不提供启停开关

后续演进（目标态）：

1. 引入 `ops.dataset_control`（`dataset_key/is_disabled/reason/updated_at`）
2. 新鲜度计算读取控制表覆盖状态
3. 接入审计记录与权限控制

---

## 8. 融合策略中心准备度（当前）

当前结论：

1. 已具备开发条件（底层对象齐备）
2. 未具备完整交付条件（页面工作区与发布闭环仍需补齐）

已具备能力：

1. std 规则 API：`/api/v1/ops/std-rules/*`
2. release 对象 API：`/api/v1/ops/releases` 及其子路由
3. dataset card API：`/api/v1/ops/dataset-cards`
4. 数据源卡片页：`/ops/v21/datasets/tushare`、`/ops/v21/datasets/biying`
5. DatasetDefinition 派生展示事实与 freshness 健康度模型
6. Foundation 融合引擎：`policy_store/policy_engine/publish_service`
7. 可运行回归基线：`stock_basic`

当前缺口：

1. 融合策略中心独立页面入口与工作区仍缺失
2. 策略对象管理（草稿/版本/diff）尚未形成完整 UI 闭环
3. 发布执行到 `TaskRun/node` 的通用闭环尚未覆盖全部数据集

优先待办（按优先级）：

1. P0：先开只读页面（pipeline/rules/releases）
2. P0：补最小策略对象管理闭环（草稿、版本、差异）
3. P1：补发布执行可观测闭环（release -> TaskRun -> nodes）
4. P1：补全前后端测试基线

---

## 9. Ops 专题文档边界

以下文档保留为专题补充，不再重复定义主契约：

1. `ops-workflow-catalog-v1.md`：工作流目录与实现清单
2. [审查中心使用与查询说明](/Users/congming/github/goldenshare/docs/ops/ops-review-center-design-v1.md)：页面导航、板块统计及人工改池边界；指数资格与补漏规则归指数专题，字段归 API 参考
3. [多源对账工具与后续需求](/Users/congming/github/goldenshare/docs/ops/reconcile-capability-requirements-v1.md)：现行 CLI、退出码边界及未实施平台设想，不等于已建成统一对账平台
4. `ops-task-run-observability-redesign-plan-v1.md`：TaskRun 执行观测模型

说明：旧 API 语义、旧状态表退场、旧能力审查备忘等过渡文档已下线；当前边界由本契约维护，字段及专题细节分别归 API 参考和上述专题。

---

## 10. 验收基线

1. 能查询每个数据集的 `mode + layer_plan + freshness status`
2. 数据状态总览与数据源管理展示口径一致
3. 任务中心可查看执行记录并定位失败原因
4. 审查中心可按领域展示只读审查数据
5. 停用数据集在页面可见且不计入重点告警
6. 融合策略中心具备从对象到执行的可观测闭环后再进入正式上线

<a id="manual-maintenance"></a>

## 11. 手动维护：现行规则与回归重点

本节承接原手动动作模型与时间模式升级方案的有效结论。这里的页面操作者是运营人员，不是行情系统终端用户。

### 11.1 动作来源与提交链路

| 动作类型 | 定义与时间输入来源 |
| --- | --- |
| `dataset_action` | `DatasetDefinition` 的 maintain action、`date_model`、`input_model` 和 planning 限制共同派生 |
| `workflow` | `WorkflowDefinition.parameters` 与 `time_regime`；不继承某个步骤的数据集时间能力 |
| `maintenance_action` | `MaintenanceActionDefinition.parameters` 与 `manual_time_regime`；不伪造 DatasetDefinition 或日期模型 |

手动页读取 `GET /api/v1/ops/manual-actions`，按返回的 `action_key/action_type` 选择动作，提交至对应 `/manual-actions/{action_key}/task-runs`。`catalog` 仍服务自动任务等消费者，不因手动页切换而删除；自动任务仍保存 `target_type/target_key`。

`ManualActionTaskRunResolver` 解析时间和过滤条件；dataset action 在创建 TaskRun 前经 `DatasetActionResolver` 预检，校验不通过不会创建队列任务。通过后进入 TaskRun 队列，worker 再走 `DatasetActionRequest -> DatasetExecutionPlan -> IngestionExecutor`。Workflow 和维护动作按各自目标路由创建任务，不把三类动作统称为 DatasetDefinition 执行路径。

### 11.2 时间与表单边界

- `time_form.default_mode + modes[]` 是现行表单结构。每个模式独立声明控件和选择规则；支持 `none` 不等于隐藏整个动作的日期选项。
- 数据集声明支持哪些模式与每种模式怎样选日期是两层事实；前端消费 API，不根据字段名或数据集名重建规则。通用日期语义、自然月窗口展开及季度锚点见 [日期指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)。
- `none` 只表示无显式时间输入，按该动作已定义的无日期语义处理；不是最近几天、自动猜日期或统一清空重建。未声明支持 `none` 的数据集动作不得据此绕过校验。
- **已确认的交易日历口径保留：** `trade_cal.maintain` 默认 `none`，仍可选单日或区间；当前 builder 的无日期分支保留交易所、不附加日期窗口，按分页刷新完整日历。`reference_data_refresh` 不展示日期控件，其帮助语义明确为“交易日历按完整日历刷新”。完整刷新不等于小任务，不能根据无日期输入推断请求量、内存或事务体量很小。
- `conditional_time_rules`、单次 unit 上限及参数默认值也是表单契约的一部分；页面切换对象过滤后可能需要收紧时间选项，最终仍由后端校验。字段及请求形态只在 [API 手动维护章节](/Users/congming/github/goldenshare/docs/ops/ops-api-reference-v1.md#manual-action-time-contract)维护。

### 11.3 变更时必须保护的消费者

实现入口：`src/ops/queries/manual_action_query_service.py`、`src/ops/schemas/manual_action.py`、`src/ops/services/manual_action_service.py`、`frontend/src/shared/api/types.ts` 与 `frontend/src/pages/ops-v21-task-manual-tab.tsx`。

涉及该契约的代码变更时，回归须覆盖：默认模式、模式切换与请求体一致；未支持模式及过滤联动限制被拒绝；日期/月/季度规则与 unit 上限；从数据集、TaskRun、Schedule 预填，复制参数、浏览器返回及草稿恢复。不能只测控件显示而漏测实际提交内容。

后端入口为 `tests/web/test_ops_manual_actions_api.py`、`tests/web/test_ops_task_run_api.py`、`tests/test_dataset_action_resolver.py`、`tests/test_dataset_definition_registry.py`；前端为手动页与任务中心页测试，并同步 `frontend/e2e/support/smoke-fixtures.ts`。前端具体门禁依目录规则执行。以上是后续代码变更的回归范围，不代表本次纯文档整合已重跑这些测试或重新完成生产验收。
