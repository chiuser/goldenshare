# Ops 自动任务能力契约 LLD v1

状态：P1–P4 已完成
日期：2026-08-03
上位方案：[Ops 自动任务能力契约收敛方案 v1](/Users/congming/github/goldenshare/docs/ops/ops-automation-capability-contract-plan-v1.md)。

---

## 0. 实施硬约束追溯账本

| ID | 硬需求 | 权威落点 | 验收 |
| --- | --- | --- | --- |
| `AC-001` | 每个 Catalog item 都有 capability；可排程目标非空 | Catalog schema + resolver | 81 个可排程目标非空；其余为 `null` |
| `AC-002` | capability 按 `target_type + target_key` 解析 | resolver | 直接 `index_daily` 与 workflow 中 `index_daily` 覆盖 |
| `AC-003` | workflow 仅 `schedule`，禁止 probe/fallback/ProbeRule/`workflow_dataset_keys` | resolver + binding + request schema | workflow probe 全部 422；无 workflow rule |
| `AC-004` | source-ready dataset 可在 workflow 内直接执行 | workflow dispatcher | 两个现有指数 workflow 不建 rule，步骤回归通过 |
| `AC-005` | probe 来源为系统默认，不可编辑 | request schema + binding + Catalog | 无 source Select；提交 `source_key` 为 422；无 ProbeRule 写 API |
| `AC-006` | 前端不再按 action key/condition 维护特殊规则 | Catalog capability | 仅靠 contract fixture 即能渲染 |
| `AC-007` | 直接 API 不可绕过单独 dataset action 的 probe 限制 | resolver + binding | remote-only normal schedule 为 422 |
| `AC-008` | Runtime 7 类探测及防篡改不变 | Probe Runtime | 7 类回归、detail 全市场单日回归 |
| `AC-009` | 不改变现有 28 schedule / 6 ProbeRule 语义 | 只读 preflight | 零 mismatch；无 bulk rebind |
| `AC-010` | 不提前创建 margin_detail 自动任务 | 无 seed/migration | 生产仍为 0；M5b 独立授权 |

## 1. 模块和边界

| 模块 | 改动 |
| --- | --- |
| 新增 `src/ops/services/schedule_automation_capability_resolver.py` | capability 唯一事实源 |
| `src/ops/action_catalog.py` | 删除无消费者的 `probe_trigger_enabled` |
| Catalog schema/query/API | 返回 capability |
| schedule request schema/API | `source_key` 不再是运营可写字段 |
| `schedule_probe_binding_service.py` | 先校验后删除；仅 dataset probe 派生 rule |
| 新增只读 audit service | 扫描 schedule/ProbeRule，不写库 |
| Probe Runtime 和 7 个 service | 保留显式 dispatch；增加 workflow rule 防御 |
| 前端 `types.ts` 与自动任务页 | 只读 Catalog contract，删除本地特例 |

不改 `DatasetDefinition`，不新增 `foundation -> ops` 依赖，不改业务数据表或迁移。

## 2. Catalog 数据契约

### 2.1 基本模型

所有 action/workflow item 都有 `automation_capability`。`schedule_enabled=false` 时它为 `null`；否则必须非空：

```python
class AutomationCapability(BaseModel):
    version: Literal[1] = 1
    default_trigger_mode: Literal["schedule", "probe", "schedule_probe_fallback"]
    trigger_options: list[TriggerModeCapability]
    probe_conditions: list[ProbeConditionCapability]

class TriggerModeCapability(BaseModel):
    mode: Literal["schedule", "probe", "schedule_probe_fallback"]
    allowed_schedule_types: list[Literal["cron", "once"]]

class ProbeConditionCapability(BaseModel):
    kind: str
    label: str
    description: str
    allowed_trigger_modes: list[Literal["probe", "schedule_probe_fallback"]]
    calendar_policy: Literal["dataset_default", "forbidden"]
    time_input: Literal["dataset_default", "forbidden"]
    filters: FilterCapability
    probe: ProbeConfigCapability
```

`trigger_options` 和 `probe_conditions` 不得被前端做笛卡尔积；一个 condition 只能用于其声明的 trigger mode。

### 2.2 来源模型

```python
class ProbeConfigCapability(BaseModel):
    source: Literal["system_default"] = "system_default"
    source_label: str = "系统默认来源"
    window: WindowCapability
    probe_interval_seconds: IntegerCapability
    max_triggers_per_day: IntegerCapability
```

Catalog 不返回可选 source。Create/Update request 不接受可写 `source_key`；任何显式来源输入返回 `422 source_key.operator_forbidden`。持久化 `ProbeRule.source_key` 只由后端按数据集默认 source 和 condition 生成，用于运行诊断。

### 2.3 两类关键投影

单独 `margin_detail.maintain` 自动任务：

```json
{
  "version": 1,
  "default_trigger_mode": "probe",
  "trigger_options": [{"mode": "probe", "allowed_schedule_types": ["cron"]}],
  "probe_conditions": [{
    "kind": "remote_margin_detail_ready",
    "allowed_trigger_modes": ["probe"],
    "calendar_policy": "forbidden",
    "time_input": "forbidden",
    "filters": {"mode": "forbidden"},
    "probe": {
      "source": "system_default",
      "window": {"mode": "fixed", "start": "09:00", "end": "09:30"},
      "probe_interval_seconds": {"mode": "fixed", "value": 300},
      "max_triggers_per_day": {"mode": "fixed", "value": 1}
    }
  }]
}
```

任何 workflow（包括步骤中有 `index_daily` 的 workflow）：

```json
{
  "version": 1,
  "default_trigger_mode": "schedule",
  "trigger_options": [{"mode": "schedule", "allowed_schedule_types": ["cron", "once"]}],
  "probe_conditions": []
}
```

这个差异表达的是自动任务目标不同，不是 `index_daily` 在 workflow 中失去独立自动任务的 probe 能力。

## 3. Resolver 和 binding

### 3.1 Resolver API

```python
def resolve(target_type: str, target_key: str) -> AutomationCapability | None
def validate_schedule(schedule: OpsSchedule) -> ValidatedAutomationIntent
def system_source_for(condition_kind: str, dataset_key: str) -> str
```

Catalog 与 binding 必须使用同一 resolver；不得各自维护 condition、window、filter 或 source 常量。

### 3.2 Target-context validation

| `target_type` | 允许 trigger | rule 行为 |
| --- | --- | --- |
| `dataset_action` | 由它的 capability 决定 | 仅 probe/fallback 且有 condition 时建一条 rule |
| `workflow` | 仅 `schedule` | 从不建 rule |
| `maintenance_action` | 仅 `schedule` | 从不建 rule |

workflow 请求出现 `probe`、`schedule_probe_fallback`、condition、probe window/interval/max daily 或 `workflow_dataset_keys` 时一律 `422`。binding 不得将 workflow 展开为 dataset targets。

工作流运行后仍由既有 dispatcher 把时间和 filters 下传给每一步；它不读取 capability condition、不创建 ProbeRule。因此 workflow 内的 `index_daily` 是一次由用户或普通定时工作流明确发起的直接同步。

### 3.3 专用 condition registry

| condition | 精确 dataset action | modes |
| --- | --- | --- |
| `remote_stk_mins_ready` | `stk_mins.maintain` | probe / fallback |
| `remote_index_daily_ready` | `index_daily.maintain` | probe / fallback |
| `remote_index_mins_ready` | `index_mins.maintain` | probe / fallback |
| `remote_kpl_list_ready` | `kpl_list.maintain` | probe |
| `remote_idx_factor_pro_ready` | `idx_factor_pro.maintain` | probe / fallback |
| `remote_margin_ready` | `margin.maintain` | probe |
| `remote_margin_detail_ready` | `margin_detail.maintain` | probe |

现有日期、calendar、filters、频率、窗口、间隔和每日上限逐项迁入 immutable registry。`index_mins`、`idx_factor_pro`、`margin`、`margin_detail` 在**单独 dataset action 自动任务**场景仍拒绝普通 `schedule + freshness_latest_open`；不得误用于 workflow 步骤。

### 3.4 Binding 顺序

1. 创建、更新、恢复 active schedule 时，先 `validate_schedule()`，不写库。
2. 通过后才删除旧 rule，并仅按 validated dataset-probe intent 新建 rule。
3. 普通 schedule 也必须通过 capability 校验，但不建 rule。
4. pause 只删除 rule，不让遗留无效配置阻止暂停。
5. `on_success_action_json`、内部 source、时间和 filters 只能取自 validated intent，不得重读原始 request。

## 4. Runtime、前端与预检

### 4.1 Runtime

Runtime 保留 7 个探测器的显式 condition dispatch。防御性约束：

1. rule 的 on-success action 必须为 `dataset_action`，且 action key 与 condition 精确匹配。
2. target business date 只能取自 probe payload；`margin_detail` 强制全市场单日 `point=D` 且 filters 为空。
3. connector 只能取系统默认来源。
4. 发现 workflow ProbeRule 时记录受控配置错误，绝不创建 TaskRun。

现有同日去重、失败/取消重试与 ProbeRunLog 行为不变。

### 4.2 前端

1. 仅从 `automation_capability` 渲染 trigger、schedule type、condition、时间/日期、filters 和 probe 配置。
2. workflow 只渲染普通 schedule；绝不出现 probe 或来源控件。
3. probe 表单显示“系统默认来源”，没有 Select，也不提交 `source_key`。
4. 缺 capability 时失败关闭，不能保存，也不能回退 action-key 白名单。
5. 删除 `actionSupportsRemote*`、`defaultProbeConditionForAction`、`buildProbeConditionOptions`、`getStrictRemoteMarginProbeConfig` 及 source option/helper。

### 4.3 只读 preflight

`ScheduleAutomationCapabilityAuditService` 对 `ops.schedule` 和 `ops.probe_rule` 做字段白名单、稳定 `id` keyset 分页扫描，不 commit、不 update、不调用 binding。它检查 capability、trigger、schedule type、condition、日期/日历、filters、窗口、间隔、上限、内部 source、父子关系和 action 一致性；CLI 默认每类最多扫描 100 行，硬上限 1000 行，超过本次上限失败关闭。

`goldenshare ops-audit-schedule-automation-capability` 是唯一执行入口。它在 `REPEATABLE READ, READ ONLY` 事务中运行，完成后只 rollback；可用 `--expected-schedule-count 28 --expected-probe-rule-count 6` 把本次发布基线变成非零退出门禁。

2026-08-03 的首次正式预检读取 28 条 schedule、6 条 ProbeRule（均为一页），未创建 TaskRun，但发现两条历史记录未通过：ProbeRule 10（schedule 31，`index_mins.maintain`）和 12（schedule 33，`margin.maintain`）的 `source_key` 是 `NULL`，按当前 `DatasetDefinition` 及 resolver 均应为 `tushare`。它们来自 P3 前“父任务空 source 写入空 rule source”的旧 binding 语义。经运营明确授权后，以 `id + schedule_id + dataset_key + source_key IS NULL` 乐观条件在单一事务中仅回填这两个 `source_key`，并断言恰好影响 2 行；未重绑、PATCH schedule、迁移或创建 TaskRun。重跑同一只读门禁后为 28 / 6、各一页、零 mismatch，P4 通过。

建议 reason code：`capability.missing`、`trigger_mode.forbidden`、`condition.unsupported`、`source_key.operator_forbidden`、`probe_rule.target_forbidden`、`probe_rule.missing`、`probe_rule.orphan`、`probe_rule.mismatch`、`filters.forbidden`、`filters.incomplete`。

生产门禁：28 条 schedule / 6 条 ProbeRule 零 mismatch；任何问题逐条评审，禁止自动修复。

## 5. 测试和发布验收

后端必须覆盖：

1. 81 个可排程目标 capability；workflow/maintenance 的空 probe conditions。
2. 所有 workflow 的 probe/fallback/condition/`workflow_dataset_keys` 422。
3. 单独 `index_daily.maintain` 的 source-ready probe 正例；两个 index workflow 内该步骤直接执行、不建 rule 的正例。
4. 七类 condition 的 target、source、时间、filters、窗口、间隔、上限正反例。
5. 任意 `source_key` 输入 422；持久化 source 由服务端 default 断言。
6. remote-only 单独 dataset action 的普通 schedule 绕过 422。
7. 校验失败不删旧 rule；pause 可删除遗留 rule；runtime workflow-rule 防御。
8. 只读 audit 的正常、missing、orphan、workflow rule、source/action/window mismatch。

前端/浏览器必须覆盖：workflow 无 probe/source，直接 `index_daily` 有 probe，`margin_detail` 的唯一 condition 和固定约束，缺 capability 失败关闭。

最小门禁：

```bash
pytest -q tests/web/test_ops_catalog_api.py tests/web/test_ops_schedule_api.py tests/web/test_ops_probe_api.py tests/web/test_margin_detail_remote_probe.py
npm --prefix frontend run typecheck
npm --prefix frontend run test
npm --prefix frontend run build
(cd frontend && npm run test:smoke:ci)
python3 scripts/check_docs_integrity.py
git diff --check
```

## 6. 实施顺序和禁止项

1. P1：实现 immutable registry、resolver 和后端正反测试。
2. P2：实现 Catalog 的只读 capability 投影、前端 API 类型与契约测试；旧页面仍使用原有字段，不能在本阶段让 request/response 断链。
3. P3（已完成）：联合实现 request schema、binding/runtime 和自动任务页：删除可写 `source_key`、`workflow_dataset_keys`、来源 Select 与 action-key/condition 特例；删除旧 ProbeRule CRUD，只保留只读规则/运行日志查询，并以正反例验证端到端约束。
4. P4（已完成）：实现并执行只读 preflight；仅 28 条 schedule / 6 条 ProbeRule 零 mismatch 时完成发布验证；不创建 TaskRun、不修改既有排程。2026-08-03 经授权仅定点回填两条历史 rule 的 `source_key` 后重跑通过。

禁止保留 workflow probe、`workflow_dataset_keys`、`probe_trigger_enabled`、frontend fallback 或可写 source；禁止把 dataset action 的 probe 条件用于 workflow 步骤；禁止通过 migration、seed 或批量 PATCH 重建存量 schedule/ProbeRule。
