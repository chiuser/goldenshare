# Ops TaskRun 执行与观测契约

- 校准日期：2026-09-09。
- 性质：现行代码契约；历史部署和待核实验收单列在 §7，不以旧计划状态代替当前生产证据。
- 范围：TaskRun 执行、详情查询、长分页进度和浏览器 ETA。只整理文档，不改变 API、CLI、数据、执行行为或依赖边界。
- 字段全集归 [Ops API 参考 §4/12.2](/Users/congming/github/goldenshare/docs/ops/ops-api-reference-v1.md#task-run-schemas)；总体边界归 [Ops 当前契约](/Users/congming/github/goldenshare/docs/ops/ops-contract-current.md)。本文保留原路径，原 ETA LLD 的有效内容已并入 §5。

## 1. 事实归属与入口

| 对象 | 职责 | 不承担的职责 |
| --- | --- | --- |
| `ops.task_run` | 一次任务的请求意图、计划摘要、状态、当前进度和主问题引用 | 不保存逐页事件流，不复制完整错误 |
| `ops.task_run_node` | 执行节点的状态、时间、计数和问题引用 | 不等于每个逻辑 unit 一条记录 |
| `ops.task_run_issue` | 面向运营的原因、建议及完整技术诊断 | 不作为业务数据或任务进度事实源 |

模型在 `src/ops/models/ops/task_run*.py`；字段类型以模型和 `src/ops/schemas/task_run.py` 为准，不再维护第二套 DDL。旧 Execution、steps/events/logs 不是当前主链，不恢复兼容双写。

执行入口为 `src/ops/runtime/task_run_dispatcher.py`：内置处理 dataset_action、workflow、maintenance_action，并支持组合根注入的 external_executors；不能把内置三个分支误写为全仓任务类型的封闭全集。

## 2. 提交、节点与进度

1. 手动页通过 `POST /api/v1/ops/manual-actions/{action_key}/task-runs` 提交动作意图；通用入口为 `POST /api/v1/ops/task-runs`。前者返回 TaskRunViewResponse，后者返回 TaskRunCreateResponse，当前成功响应均使用路由默认 200，不是旧方案的 202。
2. Ops 保存意图；DatasetActionResolver 按 DatasetDefinition 归一化执行计划，源接口参数归 ingestion request builder。Web 请求不直接执行数据同步。
3. 普通 dataset action 建一个 `dataset_plan` 节点，逻辑 units 在该节点内执行；不是每个 unit 建一个 dataset_unit。Workflow 顺序到达某步时建立 `workflow_step` 节点，不预建全部未来节点。维护任务另有 maintenance_action/maintenance_plan/maintenance_unit 节点。
4. `unit_done` 统计已成功提交的 unit，`unit_failed` 单列失败数；处理百分比按 `(unit_done + unit_failed) / unit_total` 计算并封顶 100，总量为零时不伪造百分比。失败不能计入 ETA 的成功吞吐。
5. Workflow 运行某步时，TaskRun 进度用于该步的 units；工作流收尾时再写入步骤总数、完成数和失败数。不能据此计算整个工作流的统一 unit ETA。Workflow 的其他执行限制见 [清单 §2](/Users/congming/github/goldenshare/docs/ops/ops-workflow-catalog-v1.md#2-工作流运行机制代码级)。
6. 进度由 `TaskRunIngestionContext.update_progress` 使用独立 Session 覆盖更新，失败只回滚该进度事务；`rows_saved` 对应已提交行数，不得把 staging 写入当成业务提交。不得为观测写入阻断或回滚业务数据。
7. 完整技术错误及 Tushare 非零业务响应的原始 JSON 归 issue；run/node 只引用问题和短摘要，不保存 token、请求头。主页面同一失败原因只出现一次。

停止 queued 任务会直接转 canceled；运行中请求转 canceling，重复请求在已标记取消时幂等返回，终态请求返回冲突。执行器在自身取消检查点退出，不承诺立即中断任意底层调用。

重新提交创建新 TaskRun，复制原任务意图，`trigger_source=retry`；Workflow/maintenance 缺 target_key 时可从关联的当前 schedule 补足。它不是原任务的断点续跑 API。view 当前允许 success/failed/partial_success/canceled 重新提交，queued/running/canceling 可请求停止；实际拒绝规则仍以 command service 为准。

代码核验入口：`src/ops/services/task_run_service.py`、`src/ops/services/task_run_ingestion_context.py`、`src/ops/runtime/worker.py` 和上述 dispatcher。

## 3. 任务详情与查询边界

- 页面：`/app/ops/tasks/{id}`，实现为 `frontend/src/pages/ops-task-detail-page.tsx`。
- 主视图：`GET /api/v1/ops/task-runs/{id}/view`，聚合 run/progress/primary_issue/nodes/actions。每次查询返回按 sequence_no/id 排序的前 **200** 个节点，并附 `node_total/nodes_truncated`；不是全量节点保证，也不是只返回变化节点。
- queued/running/canceling 每 **3 秒**轮询主视图；进入终态后停止。仅打开技术诊断抽屉时，另请求 `/{id}/issues/{issue_id}`，不默认拉完整技术错误。
- 列表分页使用 `page/limit`，可提供 offset；不是 page_size。统计接口将 canceling 归 running、partial_success 归 failed，不能与原始状态枚举逐项直接相等比较。
- `progress.current_object` 是当前对象的展示投影，不是原始请求参数全集。
- `period_source_summary` 仅对 index_weekly/index_monthly 按任务日期范围读取**当前 Serving 表**，分 api/derived_daily/other；这是范围内现存数据来源统计，不是“本任务实际写入行”的溯源证据，不参与 writer 或业务提交。

查询依据：`src/ops/queries/task_run_query_service.py`；请求、响应及取消/重提示例统一查 API 参考，本文不复制大段 JSON。

<a id="paged-unit-progress"></a>

## 4. 长分页 unit：页进度不等于业务完成

场景：一个日期或季度 unit 内有多页请求，例如 fund_portfolio。分页仍是一个逻辑 unit；不新增 page node、page event 或内部运行日志。具体采集与提交设计归 [基金 B7 LLD](/Users/congming/github/goldenshare/docs/datasets/public-fund-b7-fund-portfolio-low-level-design-v1.md)。

- 存储位置：`ingestion_diagnostics_json.runtime.paged_unit`。同时最多一个 active；completed 最多 **16** 个结果，超出由 completed_truncated 表达。它是有界摘要，不是完整历史。
- API 投影为 `progress.paged_unit_progress`，包含 active/completed/completed_truncated；类型 TaskRunPagedUnitTime/Active/Result/Progress 见 API §12.2。无此诊断的任务返回 null，不按数据集 action key 特判页面。
- 保留 **16 KiB** diagnostics 预算和裁剪要求。当前 sanitizer 会裁剪样本并生成 fallback，但 fallback 携带 paged_unit 后没有再次检查总字节数；不能把预算写成“任意输入都已保证硬上限”。这是实现限制，本轮不修改代码。
- 查询层按类型归一化诊断，忽略无效片段；相关畸形输入回归不等于整个 view 在任意异常下都不会失败。

| phase / 状态 | 含义与计数边界 |
| --- | --- |
| processing_page | current_page_number 是正在处理页；completed_page_count 只含已获取、归一化并完成 stage commit 的页 |
| reconciling | 源分页已结束，正在核对最终结果；尚不能算业务提交完成 |
| publishing | 正在正式发布；不能提前增加 unit_done/rows_saved |
| 正式提交成功 | active 移入 completed，增加 unit_done/rows_saved；completed 包含最终对账计数，不另设 completed phase |
| failed / canceled | 保留最后页和累计计数，不生成成功 completed result；完整错误仍归 issue |

`rows_fetched` 可包含 active unit 的源端返回，`rows_saved` 只含已经正式提交的 units。源端页数、stage 行数、去重数和正式提交行数必须分开；未知总页数时不伪造页百分比。

页面先显示任务计数，再显示 active 实时信息及最新在前的 completed 摘要；processing/reconciling/publishing 与失败/取消必须能区分。一次 unit 的 final commit 失败时，不得把该 unit 记成已写入或已完成。

<a id="live-unit-eta"></a>

## 5. 当前节点预计完成时间（ETA）

目的：回答“**当前节点**按最近成功提交速度，大约何时完成”，不是整个 Workflow、页请求或读取行数的 ETA。

实现：`frontend/src/pages/ops-task-detail-eta.ts` 与任务详情页。API 不暴露 current_node_id；页面从返回 nodes 中选择第一个 status=running 的节点。因此 ETA 也受主视图节点截断边界影响，找不到运行节点时不猜测。

采样只存在浏览器内存中，不新增数据库、Redis、TaskRun JSON、API、SSE/WebSocket，也不写 localStorage/sessionStorage/URL。不同标签页独立采样，刷新或重新打开后重新积累。

计算规则：

1. 主视图继续每 3 秒轮询；浏览器定时器每 **10 秒**读取最新快照采样，使用真实单调时钟间隔，不假定精确经过 10 秒。
2. 样本包含 nodeId、unitDone、unitTotal、monotonicMs、wallClockMs；至少两个同一上下文的样本才可计算。第一次定时触发只建基线，不能保证打开页面 10 秒就有 ETA。
3. `rate = (本次 unit_done - 上次 unit_done) / 实际间隔秒数`。
4. `remaining = max(unit_total - unit_done, 0)`；`eta_seconds = remaining / rate`；预计完成时刻 = 本次墙钟时间 + eta_seconds。剩余量是分子，不是分母；unit_failed 不参与 rate。
5. 任务或节点切换、总量变化、成功计数回退时重置采样；不能沿用上个节点的速度。总量无效、增量为零或间隔无效时显示不可估算，不伪造倒计时。
6. 运行中完成全部已知 units 可显示“已完成”；canceling 显示“停止中”。终态 success 显示“已完成”，failed/canceled 显示“未完成”；其他非活动节点不套用当前节点 ETA。

ETA 不改变 unit 提交边界，也不把预计完成时刻持久化成任务事实。页面仍是轮询观测，不能拿 ETA 的短期抖动判断数据损坏或任务挂死。

## 6. 主任务结束后的处理

主任务 Worker 完成业务执行及 TaskRun 终态提交后可以继续领取任务，不再同步刷新数据集状态投影。独立完成 Worker 顺序尝试：状态投影刷新、符合条件的 index_daily 日期完整性审计创建、飞书通知。

三项的触发条件、游标、配置和失败限制统一见 [完成后处理 Worker 契约](/Users/congming/github/goldenshare/docs/ops/ops-task-completion-side-effect-worker-plan-v1.md)。`ops.dataset_status_snapshot` 是现行共享状态投影，必须保留，与 Kopia 备份无关。

<a id="history-and-acceptance"></a>

## 7. 历史证据与尚未核实的验收

以下是原文记载，保留日期和证据性质；**不是可重跑的迁移或清表操作单**。

| 历史记录 | 保留的结论与当前边界 |
| --- | --- |
| 2026-04-26 主链迁移，原 M0–M7 | 原文记录远程迁移至 20260426_000074、daily 单日小窗口通过、旧执行主链退出。不能据此重跑旧清理 |
| 原 M8 恢复记录 | 当时服务已恢复、状态快照已重建，旧 ops.job_schedule 为空且默认配置待重建；当前配置模型已是 ops.schedule，不能把“当时为空”当成现状或自动 seed 授权。后续验收状态本轮未核实 |
| 2026-08-10 长分页扩展 | 原文记录本地测试及 12 类浏览器 fixture 通过，提交 14effd17 已经管理员确认部署 Prod；当时仍待下一次真实长分页运行的页面验收，本轮未补做 |
| 2026-08-21 ETA 扩展 | 原 LLD 记录本地实现、84 项后端目标测试及前端检查通过，当时待发版验收；本轮确认代码存在，未独立核实此后的部署/运行验收 |

必须保留的事故：2026-05-05 原记录确认，迁移 `alembic/versions/20260426_000074_task_run_observability_redesign.py` 的 RESET_TABLES 错将 `ops.index_series_active` 纳入清理，曾造成对象池误清空；后来依据审阅后的 2026-04-15 指数代码集重建 index_daily 池，当时为 1,130 个代码。该数字是历史重建证据，不是当前数量。

对象池不是 TaskRun 观测数据，其后续执行用途见 [指数 active 池机制](/Users/congming/github/goldenshare/docs/datasets/index-series-active-sync-mechanism.md)。本轮不更改历史迁移。任何新的清理都须独立逐表确认用途、执行规划依赖、恢复依据与差异并取得批准；不得把旧“可重置”名单当成持续授权，也不得因本次文档合并清空状态投影、业务规则、配置或对象池。

## 8. 回归入口与维护方式

- API、节点上限、旧路由防回退与诊断投影：`tests/web/test_ops_task_run_api.py`。
- 调度执行、主任务不刷新 snapshot、成功/失败计数与事务隔离：`tests/web/test_ops_runtime.py`、`tests/test_dataset_progress.py`。
- ETA 公式与页面：`frontend/src/pages/ops-task-detail-eta.test.ts`、`frontend/src/pages/ops-task-detail-page.test.tsx`。维护时覆盖预热、零增量、完成、任务/节点/总量变化、计数回退、失败不计吞吐及无持久化。
- 长分页须保留第一页/页间/短页/发布/完成序列、final commit 失败不记成功、观测失败隔离、active 加 8 个 completed 的预算样本、旧/新/畸形诊断、各阶段页面与延迟 fixture 回归；具体执行器测试归 B7 LLD。样本通过不能替代任意输入的硬字节上限证明。

本次只做静态代码、字段和文档对账，不运行生产任务、数据库迁移或真实源请求；未核实的历史验收不自动关闭。信息迁移与校验记录见 [本批治理记录](/Users/congming/github/goldenshare/docs/governance/docs-information-architecture-v1.md#ops-taskrun-consolidation-20260909)。
