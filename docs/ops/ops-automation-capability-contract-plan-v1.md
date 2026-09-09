# Ops 自动任务能力契约 v1

状态：当前代码契约；P1–P4 历史验收已完成。**P5 生产迁移与验收尚无本轮证据，不作完成判断**，最后记录为 2026-08-24 待独立维护窗口，见 [§5](/Users/congming/github/goldenshare/docs/ops/ops-automation-capability-contract-plan-v1.md#p5-production-acceptance)。
校准日期：2026-09-09。适用：Ops 自动任务、Catalog 和自动任务页；不授权创建任务、修改生产配置或执行迁移。

## 1. 契约归属

自动任务“能配置什么”由 `ScheduleAutomationCapabilityResolver.resolve(target_type, target_key)` 统一解析，Catalog 投影，前端消费，保存与 binding 再校验。不能用页面 action-key 白名单或直接 ProbeRule 写 API 绕过。

| 内容 | 维护位置 |
| --- | --- |
| 触发方式、绑定、探测安全与未完成验收 | 本文（已吸收原能力 LLD 的有效内容） |
| 日期策略、日期生成与数据集声明优先级 | [自动任务日期策略](/Users/congming/github/goldenshare/docs/ops/ops-schedule-calendar-policy-plan-v1.md) |
| 请求、响应及完整 capability 字段 | [Ops API §3/11/12.1](/Users/congming/github/goldenshare/docs/ops/ops-api-reference-v1.md#automation-capability-schema) |
| 工作流步骤与执行限制 | [Workflow 清单](/Users/congming/github/goldenshare/docs/ops/ops-workflow-catalog-v1.md) |

所有 Catalog action/workflow item 均包含 `automation_capability`；不可排程时为 null，可排程时必须非空。内部 `AutomationCapability` 是 dataclass，API 的 `AutomationCapabilityResponse` 是 Pydantic 响应模型，不能混写。当前不仅有 trigger/probe，还包含日期规则、时间输入契约、固定排程与重复策略；字段只在 API 参考维护。

工作流和 maintenance action 都只能普通 schedule，但不代表所有 maintenance 都允许 cron/once：固定时刻或重复策略由其自身 capability 限制。前端缺 capability 时不能保存，不能回退本地白名单；condition 只能组合其声明的 trigger mode，不能把两个列表任意组合。

## 2. 触发方式与目标上下文

| trigger_mode | 时序与持久化 | 允许目标 |
| --- | --- | --- |
| `schedule` | 按真实 cron/once 到点创建 TaskRun | 由目标能力决定；workflow/maintenance 只允许这一种 |
| `probe` | 在 ProbeRule 窗口内探测，命中后创建 dataset TaskRun；`schedule_type=cron` 仅表示持续型生命周期，`cron_expr/next_run_at=NULL` | 仅 capability 允许的独立 dataset action |
| `schedule_probe_fallback` | 窗口内探测并保留真实定时兜底；同日已有有效 probe 任务时跳过兜底，细则见 §3.3 | 仅 capability 允许的独立 dataset action |

`probe` 是**自动任务目标的触发能力**，不是数据集在所有调用环境中的执行方式：

- Workflow 不派生 ProbeRule，不等待 source-ready；其中的数据集按工作流下传日期与 filters 直接执行。
- `index_daily` 仍是 `index_extension_maintenance` 和 `index_kline_maintenance_pipeline` 的步骤；独立 `index_daily.maintain` 的探测限制不能套到这两个工作流。
- 手动动作/手动工作流仍是显式发起的直接执行，不改变其契约。
- Workflow 的 probe、fallback、探测配置和 `workflow_dataset_keys` 输入必须被拒绝；不得展开 workflow 生成 dataset 探测规则。

### 2.1 纯 probe 不得伪装成定时任务

Create/Update 拒绝非空 cron 或 next-run（`422 probe_schedule_timing.forbidden`），拒绝 once（`422 schedule_type.forbidden`）。Update 将纯 probe 的遗留无效时间归空；Resume 固定为 cron 分类并清空两时间字段，不计算 next-run；Pause 仅移除活动规则，不改时间字段。

Resolver/audit 同样检查这个不变量，ORM 和迁移声明数据库 CheckConstraint。**约束代码存在不证明生产约束已部署。**前端纯 probe 不调用预览、不生成定时字段；列表/详情显示持续探测或按探测窗口。Fallback 仍显示真实兜底时间，不能随纯 probe 一起清空。

## 3. 探测条件与绑定安全

### 3.1 source-ready 条件

下表是当前 resolver 的专用条件映射，不是生产配置数量或新建任务清单。

| condition | 精确 dataset action | 允许触发方式 | 关键限制 |
| --- | --- | --- | --- |
| `remote_stk_mins_ready` | `stk_mins.maintain` | probe / fallback | 禁固定日期；只接受 freq，可选允许频率的子集，不接受额外 ts_code |
| `remote_index_daily_ready` | `index_daily.maintain` | probe / fallback | 禁固定日期与 calendar policy |
| `remote_index_mins_ready` | `index_mins.maintain` | probe / fallback | 禁固定日期；五个分钟频率须完整；最小 300 秒 |
| `remote_kpl_list_ready` | `kpl_list.maintain` | 仅 probe | 禁固定日期与 calendar policy |
| `remote_idx_factor_pro_ready` | `idx_factor_pro.maintain` | probe / fallback | 禁 filters、固定日期；最小 300 秒、每日一次 |
| `remote_margin_ready` | `margin.maintain` | 仅 probe | 禁 filters、固定日期；固定 09:00–09:30、300 秒、每日一次 |
| `remote_margin_detail_ready` | `margin_detail.maintain` | 仅 probe | 同 margin 配置边界，但独立 condition/service |

`freshness_latest_open` 也须由 resolver 明确提供。`index_mins`、`idx_factor_pro`、`margin`、`margin_detail` 独立自动任务不能以普通 schedule 或本地 freshness 绕过其 source-ready 约束。

来源固定为系统默认：请求显式写 `source_key` 返回 `422 source_key.operator_forbidden`，Catalog 只显示来源说明，无来源选项。`ProbeRule.source_key` 由服务端按 condition 与数据集默认 source 生成，保留用于诊断。

### 3.2 Binding 与 runtime

1. Active schedule 创建/更新/恢复时，先 `validate_schedule()`，通过后才删除旧 rule，并按 validated intent 派生 dataset probe rule；校验失败不能先删旧规则。
2. 普通 schedule 也校验，但不建 rule。非 active（含暂停）清除规则，不让历史无效配置阻止暂停。
3. `on_success_action_json`、source、日期及 filters 来自已验证意图；不得重新从原始请求拼装。正常更新/恢复可能重建规则；**仅 P5 数据迁移承诺保留原 rule id**。
4. Probe Runtime 保留七类 source-ready 显式 dispatch；检查 condition 与 dataset action 精确匹配、系统来源、业务日期来自 probe payload。`margin_detail` 强制全市场单日 point=D、空 filters。
5. 遗留/篡改的 workflow ProbeRule 必须报受控配置错误，不能创建 TaskRun。同日去重、失败/取消后的重试与 ProbeRunLog 仍按现有运行规则。
6. Probe API 只读查询规则及运行日志；不恢复旧 CRUD、`workflow_dataset_keys`、`probe_trigger_enabled`、可写来源或前端 fallback。

相关实现位于 `src/ops/services/schedule_automation_capability_resolver.py`、`schedule_probe_binding_service.py`、`operations_probe_runtime_service.py`；契约装配不引入 foundation → ops 反向依赖，也不改业务表。

<a id="probe-runtime-observation"></a>

### 3.3 样本专题、运行日志与去重边界

抽样及请求规则分别归 [股票分钟探测](/Users/congming/github/goldenshare/docs/ops/ops-stk-mins-remote-source-probe-plan-v1.md) 和 [指数日线探测](/Users/congming/github/goldenshare/docs/ops/ops-index-daily-remote-source-probe-plan-v1.md)，不把两者改成通用探测器。二者的 source-ready 分支不刷新本地 freshness；本地 freshness_latest_open 分支仍会刷新，不能把“不刷新”扩大为所有 Probe 的规则。

共同观测规则（按当前 runtime/query 核验）：

- 未到窗口、未到间隔或达到日限额时，直接跳过本轮规则，不产生一次实际探测日志。完成但未命中通常为 status=success、condition_matched=false、result_code=miss；status=success 不等于源站就绪。
- 被捕获异常为 failed/error，payload 使用 error 字段，并补 dataset_key/source_key；不承诺 source_error 或完整源站错误 JSON。异常后的日志提交不在该捕获内，不能据此承诺任何数据库故障都继续下一规则。
- 新 ProbeRunLog 写 schedule_id；查询按 log.schedule_id、尚存 rule.schedule_id、关联 TaskRun.schedule_id 顺序解析，并使用 left join。页面按 schedule_id + dataset_key 看历史；无法关联的旧日志不会被凭空恢复。字段归 [API 参考 §5/12.4](/Users/congming/github/goldenshare/docs/ops/ops-api-reference-v1.md)，不另复制模型。
- `_should_probe` 按当前 rule.id、规则时区当天的 condition_matched=true 日志数检查 max_triggers_per_day；不是按业务日期的任务唯一键。正常 binding 会重建 rule，因此这个计数不保证跨规则重建连续。

**分钟与指数日线的“只触发一次”不能写成全局保证。**当前 `_has_effective_target_task` 的按目标日期去重不覆盖 stk_mins/index_daily。它们依靠规则日限额等现有机制，不能据此承诺跨重建或多个进程严格唯一；本轮只澄清，不新增去重实现。

Fallback 使用另一项检查：`OperationsScheduleService._has_effective_probe_task_for_schedule_day` 查同一 schedule、requested_at 位于 schedule 时区当天、trigger_source=probe，且状态为 queued/running/canceling/success/partial_success 的任务；不是只查成功，也不是按 time_input.trade_date 去重。failed/canceled 和前一日任务不阻止当天兜底。跳过时不改 last_triggered_at；cron 推进 next_run_at，once 暂停并清空 next_run_at。

Scheduler 单轮实际先处理到期 schedule，再运行 probe；不能将业务描述“先探测再兜底”误读为每轮一定优先探测。现有跳过逻辑只说明已有有效 probe 任务时如何处理兜底，不保证反向场景、规则重建或并发下只有一个任务。核验与防回退入口：`tests/web/test_ops_runtime.py`、`tests/web/test_ops_probe_api.py`、`tests/web/test_ops_schedule_api.py` 及前端自动任务页测试；未因此执行生产调度。

## 4. 只读预检与历史数量

`goldenshare ops-audit-schedule-automation-capability` 在 `REPEATABLE READ, READ ONLY` 事务中执行，结束 rollback。服务对白名单字段做稳定 id keyset 分页；不提交、不修复，不调用 binding 写链（会复用只读模板生成）。

- 默认 batch_size=100、每类 max_records=100，硬上限 1000；截断或数量不符均不能算通过。
- 校验目标 capability、trigger/type、日期/日历、filters、窗口、间隔、上限、系统 source、on-success action，以及 rule 缺失、孤儿与父子关系；active/paused 纯 probe 都检查时间不变量。
- `--expected-schedule-count` / `--expected-probe-rule-count` 是可选门禁。若使用，填写**当次有界只读盘点的基线**，不能机械复制历史 28/6；问题逐条评审，禁止自动重绑或批量 PATCH 来凑数。

历史证据（不是当前规模）：

- 原 P1 验证 81 个可排程目标（76 dataset、1 maintenance、4 workflow）；新增目标后按当次 Catalog 全量覆盖，81 不是固定门禁。
- 2026-08-03 P4 预检为 28 schedule / 6 ProbeRule，各一页；首次发现 rule 10（schedule 31、index_mins）与 rule 12（schedule 33、margin）的 source_key 为 NULL。
- 当时经授权，以 id + schedule_id + dataset_key + source_key IS NULL 乐观条件，在单事务中仅将两条来源回填为 tushare，断言影响 2 行；未改 schedule、TaskRun、业务数据或重绑。再次只读检查为 28/6、零 mismatch，P4 通过。这不是本轮修复授权。
- 原专项禁止顺带 seed `margin_detail` 的首条自动任务，其首次配置另需授权；本次没有核实现在是否已有该配置，不把旧“0 条”写成现状。

<a id="p5-production-acceptance"></a>

## 5. P5：保留生产迁移验收事项

### 5.1 已知证据与状态边界

2026-08-24 只读核验曾发现生产 Schedule #33 自创建起就是纯 probe，却保存了 `0 19 * * *` 与 next-run；运行时排除纯 probe，所以它们是无效配置而非真实兜底。旧表单默认值与通用 next-run 计算造成持久化/界面语义错误。

当日记录：代码及本地验证完成，生产迁移待独立维护窗口。2026-09-09 本次只核验代码与文档，**未连接生产核实迁移版本、约束或 #33 当前字段**；后续先核实是否已执行，不能直接重跑，也不能将待验收项删除。

### 5.2 迁移边界及验收清单

`alembic/versions/20260824_000150_normalize_pure_probe_schedule_timing.py` 仅处理 PostgreSQL：把不符合不变量的纯 probe schedule 归一为 cron 分类、清空 cron/next-run，再建立 `ck_ops_schedule_pure_probe_has_no_schedule_timing`。

它不重建 Schedule/ProbeRule，不修改 ProbeRule id、TaskRun、ConfigRevision 或业务数据。Downgrade 只删除约束，不恢复已清空的无效时间。该迁移的 down_revision 为当时的 `20260824_000149`，不代表今天的 Alembic head。

如仍需生产执行：先按当前部署与迁移 head 制定维护窗口并独立获准，原方案要求暂停 Web、scheduler/worker 后迁移，验收再恢复服务。本文不提供即刻执行授权。迁移前后必须对账：

1. 所有纯 probe 行满足 cron 分类、cron_expr/next_run_at 均为 NULL，数据库约束存在。
2. 普通 schedule 与 fallback 的真实定时字段不变。
3. Schedule、ProbeRule 数量、rule id、父子关系及规则配置不变，不以常规 binding 重建代替迁移。
4. 对历史 #33 先重新核实当前身份/状态；原验收基线为 active、原 ProbeRule、09:00–09:30 窗口，不擅自恢复成旧配置。
5. 当次只读 capability audit 零 mismatch；恢复服务后分别核验普通 schedule、fallback、纯 probe 的契约。该只读验收不主动触发业务 TaskRun，真实运行验证另需授权。

### 5.3 历史本地验证

2026-08-24 记录为后端定向 292 passed，前端 typecheck/规则检查/149 项单测/构建通过，浏览器 smoke/visual 13 passed 且未更新截图基线，文档检查通过。以上为历史证据，不是本轮重跑结果，也不能替代生产验收。

## 6. 回归与维护入口

原 LLD 的 AC-001～015 硬口径合并为以下检查组；不再维护第二份字段模型和已完成的逐阶段改文件清单。

| 原追溯项 | 保留的正反例与当前测试入口 |
| --- | --- |
| AC-001/002/006 | Catalog 所有可排程目标非空、字段完整、按 target context 解析；无 action-key fallback；`tests/test_ops_automation_capability.py`、`tests/web/test_ops_catalog_api.py`、前端自动任务页测试 |
| AC-003/004/007 | Workflow 仅 schedule、步骤直接执行不建 rule；独立 remote-only action 绕过被拒；`tests/web/test_ops_schedule_api.py`、`tests/web/test_ops_runtime.py` |
| AC-005/008 | 七类条件与来源、日期、filters、窗口、上限防篡改；margin_detail 全市场单日；`tests/web/test_ops_probe_api.py`、`tests/web/test_margin_detail_remote_probe.py` |
| AC-009/010 | 只读 audit 正常/missing/orphan/mismatch、校验失败不删旧 rule、pause 可清理；不 seed/批量重绑；`tests/web/test_schedule_automation_capability_audit_service.py`、`tests/test_cli_ops_schedule_automation_audit.py` 及 binding/API 回归 |
| AC-011/012/013/015 | 纯 probe create/update/resume 空时间；非空 cron、next-run、once 拒绝；不预览；fallback 定时/同日跳过保留；Schedule API/runtime 与前端测试 |
| AC-014 | ORM 约束与迁移一致、只改 schedule 时间、不重建规则；`tests/test_ops_pure_probe_schedule_timing_migration.py`；生产对账见 §5 |

前端入口：`frontend/src/pages/ops-v21-task-auto-tab.tsx` 及同名测试；API 模型：`src/ops/schemas/catalog.py`；只读 CLI：`src/cli_parts/ops_handlers.py`。页面回归仍覆盖 workflow 无 probe/source、直接 index_daily 有 probe、margin_detail 固定约束、纯 probe 与 fallback 显示差异。

本轮仅做文档整合与静态核验；没有运行以上数据库/浏览器测试、生产预检、探测或调度，不改变架构依赖和运行行为。
