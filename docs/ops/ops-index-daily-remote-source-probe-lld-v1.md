# `index_daily` 远程源站探测触发 LLD v1

状态：已实现，待生产验收
创建时间：2026-06-22
实现时间：2026-06-22
依据方案：`docs/ops/ops-index-daily-remote-source-probe-plan-v1.md`
适用范围：`index_daily.maintain` 自动任务探测触发、Probe Runtime、自动任务页面、Probe API 测试。

实现摘要：

1. 已新增 `remote_index_daily_ready` 探测条件，只允许绑定 `index_daily.maintain`。
2. 已新增 `IndexDailyRemoteReadinessProbeService`，探测参数经 `DatasetActionResolver -> _index_daily_params()` 生成，再追加 `limit=1/offset=0` 和最小字段。
3. 已接入 Schedule API、Direct Probe API、Probe Runtime 和自动任务页面。
4. 已补后端与前端定向测试；生产环境仍需创建自动任务后观察真实探测记录与 TaskRun 触发。

## 1. 本轮目标

在不修改 `index_daily` 正式同步链路的前提下，新增一个 `index_daily` 专用源站探测条件：

```text
remote_index_daily_ready
```

中文展示：

```text
源站已有指数日线
```

它只允许绑定：

```text
target_type = dataset_action
target_key = index_daily.maintain
trigger_mode in [probe, schedule_probe_fallback]
```

探测命中后只创建一个正式 TaskRun：

```json
{
  "task_type": "dataset_action",
  "resource_key": "index_daily",
  "action": "maintain",
  "trigger_source": "probe",
  "time_input": {
    "mode": "point",
    "trade_date": "<latest_open_date>"
  },
  "filters": "<继承自动任务 filters>",
  "request_payload": {
    "run_scope": "probe_triggered"
  }
}
```

## 2. 硬边界

1. 不改 `index_daily` writer、DAO、raw/serving 写入策略、表结构。
2. 不新增数据库表，不新增 Alembic 迁移。
3. 不改变 `freshness_latest_open` 语义。
4. 不把 `remote_stk_mins_ready` 改成通用探测器。
5. 不支持 workflow 级探测。
6. 不在 V1 暴露样本指数代码 UI。
7. 不让 Ops 自己拼 `ts_code/trade_date/start_date/end_date`，必须通过 `DatasetActionResolver -> _index_daily_params()` 生成。
8. 默认样本必须来自 `ops.index_series_active resource='index_daily_raw'`，禁止 fallback 到 `index_basic` 或 `index_daily` serving 池。
9. 默认 5 个样本必须全部命中，才允许创建 TaskRun。

## 3. 已核验事实

### 3.1 AGENTS 与架构约束

已读取并按以下约束设计：

| 文件 | 本 LLD 使用到的约束 |
| --- | --- |
| `AGENTS.md` | 开发前明确目标、依据、范围；涉及服务/契约必须做 CodeGraph；Tushare 参数必须看文档和实测；Ops/TaskRun 只保存意图，源接口参数只能在 request builder 生成 |
| `src/AGENTS.md` | `ops` 可依赖 `foundation`，`foundation` 不得反向依赖 `ops` |
| `src/ops/AGENTS.md` | Probe/TaskRun 属于 Ops；Ops 不扩展源接口参数，不恢复旧 executions API |
| `src/foundation/AGENTS.md` | DatasetDefinition 与 ingestion 主链属于 foundation；本需求不把 ops 逻辑写入 foundation |
| `frontend/AGENTS.md` | 前端只消费后端契约，不自行拼事实字段；不恢复旧 API |
| `frontend/src/pages/AGENTS.md` | 页面层做容器编排，避免把业务规则散落在页面 |
| `docs/ops/AGENTS.md` | 当前主线是 TaskRun、ProbeRule、OpsSchedule，不使用旧 execution API |

### 3.2 CodeGraph 审计范围

已用 CodeGraph 覆盖以下符号和文件链路：

```text
ScheduleProbeBindingService
ProbeRuntimeService
StkMinsRemoteReadinessProbeService
ProbeRule
OpsSchedule
ScheduleProbeConfig
OpsProbeCommandService
DatasetActionResolver
build_index_daily_units
_index_daily_params
_resolve_index_codes
IndexSeriesActiveDAO
ops-v21-task-auto-tab
test_ops_schedule_api
test_ops_probe_api
ops-v21-task-auto-tab.test.tsx
```

结论：本需求影响面集中在 `src/ops/**` 和自动任务页面；`src/foundation/ingestion/**` 只作为被调用主链，不需要改生产代码。

### 3.3 Tushare 文档与实测

已读取：

```text
docs/sources/tushare/指数专题/0095_指数日线行情.md
```

接口事实：

| 项 | 事实 |
| --- | --- |
| API | `index_daily` |
| 必填 | `ts_code` |
| 可选 | `trade_date`、`start_date`、`end_date`、`limit`、`offset` |
| 返回关键字段 | `ts_code`、`trade_date` |
| 单次上限 | 8000 |

已用 `tushareMcp.index_daily` 做最小真实验证，参数形态：

```json
{
  "ts_code": "000001.SH",
  "trade_date": "20260424",
  "fields": ["ts_code", "trade_date"]
}
```

5 个默认样本均能用 `ts_code + trade_date + fields=ts_code,trade_date` 返回目标日期样本行：

| 样本 | 实测结果 |
| --- | --- |
| `000001.SH` | 返回 `ts_code=000001.SH, trade_date=20260424` |
| `399001.SZ` | 返回 `ts_code=399001.SZ, trade_date=20260424` |
| `399300.SZ` | 返回 `ts_code=399300.SZ, trade_date=20260424` |
| `000016.SH` | 返回 `ts_code=000016.SH, trade_date=20260424` |
| `000905.SH` | 返回 `ts_code=000905.SH, trade_date=20260424` |

## 4. 当前代码审计

### 4.1 `index_daily` 正式同步链路

| 文件 | 当前事实 | 对本需求的影响 |
| --- | --- | --- |
| `src/foundation/datasets/definitions/index_series.py:200` | `index_daily` source api 是 `index_daily`，request builder 是 `_index_daily_params` | 探测必须复用这个定义，不新增另一套参数生成 |
| `src/foundation/datasets/definitions/index_series.py:220` | `date_model` 是交易日 point/range | probe 命中后只能创建 point 单日任务 |
| `src/foundation/datasets/definitions/index_series.py:251` | `ts_code` 是可选 filter | 自动任务可以不填 `ts_code`，默认由请求池展开 |
| `src/foundation/datasets/definitions/index_series.py:272` | `unit_builder_key="build_index_daily_units"`，`page_limit=8000` | probe 构造 sample unit 时会进入当前 unit builder |
| `src/foundation/ingestion/unit_planner.py:256` | `_resolve_index_codes()` 显式 `ts_code` 优先 | 显式样本探测应传入 `filters.ts_code`，不查默认池 |
| `src/foundation/ingestion/unit_planner.py:260` | 默认池读取 `index_series_active.list_active_codes("index_daily_raw")` | 默认样本必须从该池校验存在 |
| `src/foundation/ingestion/unit_planner.py:564` | `_build_index_daily_units()` 用 `_resolve_index_codes()` 生成 `ts_code` unit | Probe sample unit 可复用 resolver 主链 |
| `src/foundation/ingestion/request_builders.py:575` | `_index_daily_params()` 要求 `ts_code` | Probe 不能缺样本代码 |
| `src/foundation/ingestion/request_builders.py:580` | point 模式生成 `trade_date=YYYYMMDD` | Probe 不直接拼 `trade_date`，只读取生成后的 params |

### 4.2 Schedule 绑定链路

| 文件 | 当前事实 | 必改点 |
| --- | --- | --- |
| `src/ops/services/schedule_probe_binding_service.py:24` | `FRESHNESS_LATEST_OPEN_CONDITION="freshness_latest_open"` | 保留 |
| `src/ops/services/schedule_probe_binding_service.py:25` | `SUPPORTED_PROBE_CONDITIONS` 只有 freshness 与 `remote_stk_mins_ready` | 加入 `remote_index_daily_ready` |
| `src/ops/services/schedule_probe_binding_service.py:96` | 从 `schedule.params_json` 提取 filters | `index_daily` 显式 `ts_code` 会从这里进入 probe rule |
| `src/ops/services/schedule_probe_binding_service.py:97` | 当前只对 `remote_stk_mins_ready` 做专用校验 | 新增 `remote_index_daily_ready` 专用校验 |
| `src/ops/services/schedule_probe_binding_service.py:109` | 只有 `remote_stk_mins_ready` 会把 filters 写入 `on_success_action_json.request.filters` | 改为远程源站探测条件都继承 filters |
| `src/ops/services/schedule_probe_binding_service.py:132` | workflow 目标会被展开成多个 dataset targets | `remote_index_daily_ready` 必须在专用校验中提前拒绝 workflow |
| `src/ops/services/schedule_probe_binding_service.py:214` | `_has_fixed_trade_date()` 只检查 `trade_date` | 新条件还要拒绝 `start_date/end_date` 和非 point time_input |

### 4.3 Probe Runtime 链路

| 文件 | 当前事实 | 必改点 |
| --- | --- | --- |
| `src/ops/services/operations_probe_runtime_service.py:42` | runtime 只持有 `stk_mins_remote_probe` | 增加 `index_daily_remote_probe` |
| `src/ops/services/operations_probe_runtime_service.py:128` | `_evaluate_rule()` 只分发 `remote_stk_mins_ready` | 增加 `remote_index_daily_ready` 分发 |
| `src/ops/services/operations_probe_runtime_service.py:161` | `_enqueue_on_match()` 只支持 dataset_action | 符合本需求 |
| `src/ops/services/operations_probe_runtime_service.py:173` | 只有 STK 条件会注入 `latest_open_date` | 改成远程源站条件都注入最新开市日 |
| `src/ops/services/operations_probe_runtime_service.py:278` | 缺 `latest_open_date` 的错误文案写死为分钟行情 | 改为通用文案或按 condition label 传入 |

### 4.4 Direct Probe API 链路

| 文件 | 当前事实 | 必改点 |
| --- | --- | --- |
| `src/ops/services/probe_service.py:47` | 创建 ProbeRule 时会校验 remote condition binding | 需要纳入 `remote_index_daily_ready` |
| `src/ops/services/probe_service.py:135` | 更新 ProbeRule 时也会校验 remote condition binding | 需要纳入 `remote_index_daily_ready` |
| `src/ops/services/probe_service.py:248` | 非 `remote_stk_mins_ready` 直接 return | 新条件不能漏过校验 |
| `src/ops/services/probe_service.py:257` | direct API 只检查 `time_input.trade_date` | 新条件要拒绝固定日期和 range |

### 4.5 现有 STK 远程探测服务

| 文件 | 当前事实 | 对新服务的复用边界 |
| --- | --- | --- |
| `src/ops/services/stk_mins_remote_probe_service.py:21` | STK 条件常量集中定义 | 新增独立 `index_daily_remote_probe_service.py`，不把 STK 改通用 |
| `src/ops/services/stk_mins_remote_probe_service.py:41` | `evaluate()` 不写业务表，只做源站请求 | `index_daily` 服务沿用这个原则 |
| `src/ops/services/stk_mins_remote_probe_service.py:43` | 用北京时间当前日期作为 business date | `index_daily` 沿用 |
| `src/ops/services/stk_mins_remote_probe_service.py:46` | 用 `TradeCalendarDAO.fetch_by_pk()` 判断当天是否开市 | `index_daily` 沿用，不使用自然日猜 |
| `src/ops/services/stk_mins_remote_probe_service.py:79` | STK 按 freq 循环，每个 freq 至少命中一个样本 | `index_daily` 不需要 freq，改为全部 sample code 必须命中 |
| `src/ops/services/stk_mins_remote_probe_service.py:159` | sample unit 由 `DatasetActionResolver` 生成 | `index_daily` 必须沿用 |
| `src/ops/services/stk_mins_remote_probe_service.py:210` | STK 默认样本来自 `SecurityDAO` 并按上市状态过滤 | `index_daily` 默认样本必须改为 `index_series_active resource='index_daily_raw'` |
| `src/ops/services/stk_mins_remote_probe_service.py:229` | 用 `trade_time` 判断日期 | `index_daily` 应用 `trade_date` 判断日期 |

### 4.6 前端自动任务页面

| 文件 | 当前事实 | 必改点 |
| --- | --- | --- |
| `frontend/src/pages/ops-v21-task-auto-tab.tsx:90` | 只定义 `REMOTE_STK_MINS_READY_CONDITION` | 增加 `REMOTE_INDEX_DAILY_READY_CONDITION` |
| `frontend/src/pages/ops-v21-task-auto-tab.tsx:347` | `formatProbeConditionLabel()` 只识别 STK | 增加指数日线文案 |
| `frontend/src/pages/ops-v21-task-auto-tab.tsx:356` | `actionSupportsRemoteStkMinsProbe()` 写死 STK | 增加通用判断或独立指数判断 |
| `frontend/src/pages/ops-v21-task-auto-tab.tsx:790` | `selectedActionSupportsRemoteStkMinsProbe` 单一布尔 | 增加指数支持布尔或统一 helper |
| `frontend/src/pages/ops-v21-task-auto-tab.tsx:793` | 探测条件选项只会按 STK 动态追加 | `index_daily.maintain` 时追加“源站已有指数日线” |
| `frontend/src/pages/ops-v21-task-auto-tab.tsx:817` | 只在 STK 不支持时重置条件 | 改成当前 action 不支持当前 remote condition 时重置 |
| `frontend/src/pages/ops-v21-task-auto-tab.tsx:1168` | 保存前只校验 STK remote condition | 增加 index remote condition 校验 |
| `frontend/src/pages/ops-v21-task-auto-tab.tsx:1193` | `probe_config.condition_kind` 已随表单提交 | 复用，不改 API shape |
| `frontend/src/pages/ops-v21-task-auto-tab.tsx:1884` | 只有 STK remote condition 有说明文案 | 增加 index daily 的说明文案 |

## 5. 后端 LLD

### 5.1 新增文件与常量

新增：

```text
src/ops/services/index_daily_remote_probe_service.py
```

常量：

```python
INDEX_DAILY_REMOTE_READY_CONDITION = "remote_index_daily_ready"
INDEX_DAILY_REMOTE_READY_LABEL = "源站已有指数日线"
INDEX_DAILY_ACTION_KEY = "index_daily.maintain"
INDEX_DAILY_DATASET_KEY = "index_daily"
INDEX_DAILY_RAW_REQUEST_POOL = "index_daily_raw"
INDEX_DAILY_REMOTE_PROBE_FIELDS = ("ts_code", "trade_date")
DEFAULT_INDEX_DAILY_SAMPLE_CODES = (
    "000001.SH",
    "399001.SZ",
    "399300.SZ",
    "000016.SH",
    "000905.SH",
)
MAX_EXPLICIT_INDEX_DAILY_SAMPLE_CODES = 5
```

新增结果对象：

```python
@dataclass(frozen=True, slots=True)
class IndexDailyRemoteReadinessProbeResult:
    matched: bool
    message: str
    payload: dict[str, Any]
```

### 5.2 `IndexDailyRemoteReadinessProbeService.evaluate()`

输入：

```python
evaluate(session: Session, rule: ProbeRule, *, current: datetime) -> IndexDailyRemoteReadinessProbeResult
```

处理顺序：

1. `_validate_rule(rule)`：只允许 `dataset_key=index_daily`、`action_type=dataset_action`、`action_key=index_daily.maintain`。
2. 将 `current` 转为北京时间日期，得到 `business_date`。
3. 读取交易日历：

```python
exchange = condition.exchange or settings.default_exchange
business_day = TradeCalendarDAO(session).fetch_by_pk(exchange, business_date)
```

4. 若交易日历缺失或当天非开市日，返回 `matched=False`，不请求 Tushare，不创建 TaskRun。
5. 若当天开市，`latest_open_date = business_date`。
6. 从 `rule.on_success_action_json.request.filters` 读取 filters，并移除 `source_key`。
7. `_resolve_sample_codes(session, filters)`：
   - 若显式配置 `filters.ts_code`，拆分、去重、转大写，最多取 5 个。
   - 若未显式配置，从 `DAOFactory(session).index_series_active.list_active_codes("index_daily_raw")` 读取请求池。
   - 默认 5 个样本必须全部存在于请求池；缺少任意一个，抛出 `ValueError("指数日线默认探测样本未配置完整：...")`。
8. 创建 Tushare connector：

```python
connector = create_source_connector(get_dataset_definition("index_daily").source.source_key_default)
```

9. 对每个样本 code 构造 sample unit：

```python
request = DatasetActionRequest(
    dataset_key="index_daily",
    action="maintain",
    time_input=DatasetTimeInput(mode="point", trade_date=latest_open_date),
    filters={**base_filters, "ts_code": sample_code},
    trigger_source="probe",
    requested_by_user_id=rule.updated_by_user_id or rule.created_by_user_id,
    schedule_id=rule.schedule_id,
)
plan = DatasetActionResolver(session).build_plan(request)
unit = plan.units[0]
```

10. 探测请求参数只允许在 unit 参数上追加低成本探测覆盖：

```python
params = {**dict(unit.request_params), "limit": 1, "offset": 0}
rows = connector.call("index_daily", params=params, fields=("ts_code", "trade_date"))
```

11. `_row_matches_trade_date(row, latest_open_date)`：
   - 支持 `date`、`datetime`。
   - 支持 `YYYYMMDD`。
   - 支持 `YYYY-MM-DD`。
   - 不支持解析时返回 false，不抛异常。
12. 所有样本 code 都命中目标日期，返回 `matched=True`。
13. 任意样本未命中，返回 `matched=False`，message 带缺失 code。
14. Tushare 报错不吞掉，由 ProbeRuntime 捕获并写 ProbeRunLog failed，不创建 TaskRun。

返回 payload：

```json
{
  "dataset_key": "index_daily",
  "condition_type": "remote_index_daily_ready",
  "business_date": "2026-06-22",
  "latest_open_date": "2026-06-22",
  "sample_codes": ["000001.SH", "399001.SZ", "399300.SZ", "000016.SH", "000905.SH"],
  "matched_codes": ["000001.SH", "399001.SZ", "399300.SZ", "000016.SH", "000905.SH"],
  "missing_codes": [],
  "sample_request_count": 5,
  "sample_hits": [
    {"ts_code": "000001.SH", "trade_date": "20260622"}
  ],
  "message": "源站已返回目标交易日指数日线"
}
```

### 5.3 Schedule 绑定校验

修改：

```text
src/ops/services/schedule_probe_binding_service.py
```

新增导入：

```python
from src.ops.services.index_daily_remote_probe_service import (
    INDEX_DAILY_ACTION_KEY,
    INDEX_DAILY_DATASET_KEY,
    INDEX_DAILY_REMOTE_READY_CONDITION,
)
```

新增集合：

```python
REMOTE_SOURCE_PROBE_CONDITIONS = {
    STK_MINS_REMOTE_READY_CONDITION,
    INDEX_DAILY_REMOTE_READY_CONDITION,
}
```

改动点：

1. `SUPPORTED_PROBE_CONDITIONS` 加入 `INDEX_DAILY_REMOTE_READY_CONDITION`。
2. `_build_templates()` 中：
   - `condition_kind == INDEX_DAILY_REMOTE_READY_CONDITION` 时调用 `_validate_remote_index_daily_schedule()`。
   - `action_json.request.filters` 对所有远程源站探测条件都继承 schedule filters。
3. 新增 `_validate_remote_index_daily_schedule(schedule, filters)`：
   - `trigger_mode` 必须是 `probe` 或 `schedule_probe_fallback`。
   - `schedule.target_type` 必须是 `dataset_action`。
   - `schedule.target_key` 必须是 `index_daily.maintain`。
   - `schedule.calendar_policy` 必须为空。
   - `params_json.time_input.mode` 只能为空或 `point`。
   - `params_json` 或 `params_json.time_input` 不允许出现固定日期字段：`trade_date/start_date/end_date/start_month/end_month/month/ann_date`。
   - `_dataset_from_action_target(schedule.target_key)` 必须解析到 `index_daily`。

需要替换现有 `_has_fixed_trade_date()` 的使用方式：

```python
def _has_fixed_time_input(params_json: dict) -> bool:
    if any(params_json.get(key) not in (None, "") for key in TIME_PARAM_KEYS):
        return True
    time_input = params_json.get("time_input")
    if not isinstance(time_input, dict):
        return False
    if str(time_input.get("mode") or "point") != "point":
        return True
    return any(time_input.get(key) not in (None, "") for key in TIME_PARAM_KEYS)
```

说明：STK 现有逻辑可以继续只检查 `trade_date`，但为了避免以后同类问题，建议远程探测统一用 `_has_fixed_time_input()`。这不是兼容逻辑，是把源站探测的日期所有权收口到 probe runtime。

### 5.4 Direct Probe API 校验

修改：

```text
src/ops/services/probe_service.py
```

当前 `_validate_remote_condition_binding()` 只认识 `remote_stk_mins_ready`。如果直接通过 `/api/v1/ops/probes` 创建 `remote_index_daily_ready`，会绕过绑定校验，直到 runtime 才失败。因此需要纳入 direct Probe API 校验。

设计：

```python
if condition_kind == STK_MINS_REMOTE_READY_CONDITION:
    return _validate_remote_stk_mins_binding(...)
if condition_kind == INDEX_DAILY_REMOTE_READY_CONDITION:
    return _validate_remote_index_daily_binding(...)
return
```

`_validate_remote_index_daily_binding()` 校验：

1. `dataset_key == "index_daily"`。
2. `action_type == "dataset_action"`。
3. `action_key == "index_daily.maintain"`。
4. `request.time_input.mode` 只能为空或 `point`。
5. `request.time_input` 不允许有 `trade_date/start_date/end_date`。

错误文案：

```text
源站指数日线探测只支持指数日线行情维护
源站指数日线探测不能与固定维护日期混用
```

### 5.5 Runtime 分发与入队

修改：

```text
src/ops/services/operations_probe_runtime_service.py
```

新增实例：

```python
self.index_daily_remote_probe = IndexDailyRemoteReadinessProbeService()
```

`_evaluate_rule()` 新增分支：

```python
if condition_type == INDEX_DAILY_REMOTE_READY_CONDITION:
    result = self.index_daily_remote_probe.evaluate(session, rule, current=current)
    return result.matched, result.message, result.payload
```

`_enqueue_on_match()` 新增远程条件分支：

```python
if condition_type in REMOTE_SOURCE_PROBE_CONDITIONS:
    expected_action_key = _remote_condition_action_key(condition_type)
    if action_key != expected_action_key:
        raise ValueError(_remote_condition_binding_error(condition_type))
    latest_open_date = self._parse_probe_latest_open_date(probe_payload, condition_label=...)
    time_input = {**time_input, "mode": "point", "trade_date": latest_open_date.isoformat()}
```

`filters.pop("source_key", None)` 保持不变，避免把 source selection 传进正式维护参数。

`_parse_probe_latest_open_date()` 改为通用文案：

```text
源站探测命中缺少 latest_open_date
```

或者传入 condition label：

```text
源站已有指数日线探测命中缺少 latest_open_date
```

## 6. 前端 LLD

修改：

```text
frontend/src/pages/ops-v21-task-auto-tab.tsx
```

新增常量：

```ts
const REMOTE_INDEX_DAILY_READY_CONDITION = "remote_index_daily_ready";
const INDEX_DAILY_ACTION_KEY = "index_daily.maintain";
```

新增或替换 helper：

```ts
export function actionSupportsRemoteProbeCondition(actionType: string, actionKey: string, conditionKind: string): boolean {
  if (conditionKind === REMOTE_STK_MINS_READY_CONDITION) {
    return actionType === "dataset_action" && actionKey === STK_MINS_ACTION_KEY;
  }
  if (conditionKind === REMOTE_INDEX_DAILY_READY_CONDITION) {
    return actionType === "dataset_action" && actionKey === INDEX_DAILY_ACTION_KEY;
  }
  return conditionKind === FRESHNESS_LATEST_OPEN_CONDITION;
}
```

`formatProbeConditionLabel()`：

```ts
if (conditionKind === REMOTE_STK_MINS_READY_CONDITION) return "源站已有分钟行情";
if (conditionKind === REMOTE_INDEX_DAILY_READY_CONDITION) return "源站已有指数日线";
return "最新业务日命中最新交易日";
```

`probeConditionOptions`：

1. 默认保留 freshness。
2. `stk_mins.maintain` 追加“源站已有分钟行情”。
3. `index_daily.maintain` 追加“源站已有指数日线”。
4. 非对应 action 不展示远程源站选项。

保存前校验：

```ts
if (!actionSupportsRemoteProbeCondition(form.action_type, form.action_key, form.probe_condition_kind)) {
  throw new Error("当前维护对象不支持该探测条件。");
}
```

重置逻辑：

当前 action 不支持当前 remote condition 时，将 `probe_condition_kind` 重置为 `freshness_latest_open`。

说明文案：

```text
系统会在探测窗口内请求少量代表指数；源站返回最新交易日指数日线后，再自动发起正式指数日线维护任务。
```

无需改：

1. 纯探测触发隐藏执行时间的逻辑已经存在。
2. 定时 + 探测兜底把执行时间展示为“兜底执行时间”的逻辑已经存在。
3. `probe_config.condition_kind` 已随保存 payload 提交。

## 7. API 与文档

修改：

```text
docs/ops/ops-api-reference-v1.md
```

新增 `ScheduleProbeConfig.condition_kind` 可选值：

| 值 | 含义 | 允许绑定 |
| --- | --- | --- |
| `freshness_latest_open` | 本地最新业务日命中最新交易日 | 连续交易日 freshness 数据集 |
| `remote_stk_mins_ready` | 源站已有股票分钟行情 | `stk_mins.maintain` |
| `remote_index_daily_ready` | 源站已有指数日线 | `index_daily.maintain` |

补充 API 示例：

```json
{
  "target_type": "dataset_action",
  "target_key": "index_daily.maintain",
  "display_name": "指数日线源站就绪后同步",
  "schedule_type": "cron",
  "trigger_mode": "probe",
  "cron_expr": "*/5 16-20 * * 1-5",
  "timezone": "Asia/Shanghai",
  "calendar_policy": null,
  "probe_config": {
    "source_key": "tushare",
    "window_start": "16:00",
    "window_end": "20:00",
    "probe_interval_seconds": 300,
    "max_triggers_per_day": 1,
    "condition_kind": "remote_index_daily_ready"
  },
  "params_json": {
    "time_input": {
      "mode": "point"
    },
    "filters": {}
  }
}
```

## 8. 测试设计

### 8.1 后端 Schedule API

修改：

```text
tests/web/test_ops_schedule_api.py
```

新增用例：

| 测试 | 断言 |
| --- | --- |
| `test_ops_schedule_remote_index_daily_probe_mode_creates_probe_rule` | 创建 schedule 成功；ProbeRule dataset_key 是 `index_daily`；condition 是 `remote_index_daily_ready`；action_key 是 `index_daily.maintain` |
| `test_ops_schedule_remote_index_daily_probe_mode_preserves_explicit_ts_code_filter` | `params_json.filters.ts_code` 写入 ProbeRule 的 on_success request filters |
| `test_ops_schedule_remote_index_daily_probe_mode_rejects_invalid_binding` | workflow、非 index_daily action、calendar_policy、固定 `trade_date`、range time_input 均 422 |

### 8.2 后端 Probe Runtime

修改：

```text
tests/web/test_ops_probe_api.py
```

新增用例：

| 测试 | 断言 |
| --- | --- |
| `test_index_daily_remote_probe_requires_default_samples_in_raw_request_pool` | 默认样本缺任意一个时失败，不创建 TaskRun |
| `test_index_daily_remote_probe_builds_sample_request_from_resolver` | connector 收到 `api_name=index_daily`，params 来自 resolver 并追加 `limit=1/offset=0`，fields 是 `ts_code/trade_date` |
| `test_index_daily_remote_probe_requires_all_default_samples` | 5 个样本全部命中才 matched true；部分命中 matched false |
| `test_index_daily_remote_probe_uses_explicit_ts_code_without_raw_pool` | 显式 `ts_code` 不读取默认池，显式样本全部命中才 true |
| `test_probe_runtime_remote_index_daily_hit_creates_task_run_with_latest_open_date` | TaskRun `resource_key=index_daily`，`time_input.trade_date` 来自 probe payload |
| `test_probe_runtime_remote_index_daily_miss_does_not_create_task_run` | miss 只写 ProbeRunLog，不创建 TaskRun |
| `test_ops_probe_create_rejects_invalid_remote_index_daily_condition` | direct Probe API 非 index_daily 绑定直接 422 |

### 8.3 前端测试

修改：

```text
frontend/src/pages/ops-v21-task-auto-tab.test.tsx
```

新增或更新：

| 测试 | 断言 |
| --- | --- |
| remote probe helper | `index_daily.maintain` 支持 `remote_index_daily_ready`，其他 action 不支持 |
| label formatter | `remote_index_daily_ready` 展示“源站已有指数日线” |
| condition option | 选择 `index_daily.maintain` 时选项存在，选择其他 action 时不存在 |

## 9. 实施顺序

| 阶段 | 文件 | 动作 |
| --- | --- | --- |
| M1 | `src/ops/services/index_daily_remote_probe_service.py` | 新增指数日线专用探测服务 |
| M2 | `src/ops/services/schedule_probe_binding_service.py` | 增加 condition、绑定校验、filters 继承 |
| M3 | `src/ops/services/probe_service.py` | Direct Probe API 增加新 condition 校验 |
| M4 | `src/ops/services/operations_probe_runtime_service.py` | 增加 runtime 分发和 latest_open_date 注入 |
| M5 | `frontend/src/pages/ops-v21-task-auto-tab.tsx` | 增加选项、说明、保存前校验与重置逻辑 |
| M6 | `docs/ops/ops-api-reference-v1.md` | 更新 condition_kind 文档与示例 |
| M7 | `tests/web/**`、`frontend/**/*.test.tsx` | 加后端与前端护栏 |

## 10. 验证命令

后端：

```bash
uv run ruff check src/ops/services/index_daily_remote_probe_service.py src/ops/services/schedule_probe_binding_service.py src/ops/services/probe_service.py src/ops/services/operations_probe_runtime_service.py tests/web/test_ops_schedule_api.py tests/web/test_ops_probe_api.py
uv run pytest -q tests/web/test_ops_schedule_api.py tests/web/test_ops_probe_api.py
```

前端：

```bash
cd frontend
npm run test -- ops-v21-task-auto-tab
```

文档：

```bash
uv run python scripts/check_docs_integrity.py
```

若文档检查出现非本轮既有失败，只记录，不顺手修非本需求文档。

## 11. 验收标准

1. 已实现：自动任务页选择 `index_daily.maintain` 时，可选择“源站已有指数日线”。
2. 已实现：后端拒绝 workflow、非 index_daily、calendar_policy、固定日期、range time_input。
3. 已实现：默认 5 个代表指数必须全部存在于 `index_daily_raw` 请求池。
4. 已实现：默认 5 个代表指数全部返回最新开市日 `trade_date` 后，只创建一个 `index_daily.maintain` TaskRun。
5. 已实现：TaskRun 的 `trade_date` 与 probe 命中的 `latest_open_date` 一致。
6. 已实现：显式 `filters.ts_code` 时，只探测显式样本，且显式样本全部命中才触发。
7. 已实现：Probe 过程不写业务表、不刷新 freshness、不修改 `raw_tushare.index_daily`。
8. 待生产验收：创建 `index_daily.maintain` 自动任务后，确认探测窗口内产生 ProbeRunLog，全部样本命中时只创建一个正式 TaskRun。

本地验证结果：

```text
uv run ruff check src/ops/services/index_daily_remote_probe_service.py src/ops/services/operations_probe_runtime_service.py src/ops/services/probe_service.py src/ops/services/schedule_probe_binding_service.py tests/web/test_ops_probe_api.py tests/web/test_ops_schedule_api.py
All checks passed.

uv run pytest -q tests/web/test_ops_probe_api.py tests/web/test_ops_schedule_api.py
70 passed.

npm --prefix frontend test -- --run src/pages/ops-v21-task-auto-tab.test.tsx
12 passed.
```

## 12. 风险与控制

| 风险 | 控制 |
| --- | --- |
| 误用 `index_daily` serving active 池 | 默认样本只查 `index_daily_raw`，测试断言 DAO 调用参数 |
| Ops 自己拼参数 | 探测服务必须经 `DatasetActionResolver`，测试断言 connector 参数来自 resolver |
| 源站只有部分指数更新就误触发 | 默认样本 5 个必须全部命中 |
| 非交易日误触发 | 交易日历缺失或非开市直接 miss |
| Direct Probe API 绕过 Schedule 校验 | `OpsProbeCommandService` 同步增加新 condition 校验 |
| 前端切换维护对象后保留不兼容条件 | 通用 helper 校验当前 action 与 condition，自动重置 |

## 13. 不做事项

1. 不实现样本指数 UI 配置。
2. 不支持 workflow 探测。
3. 不改 `index_daily_raw` 请求池维护方式。
4. 不改 serving active 池门禁。
5. 不清理、不删除、不迁移任何数据表。
6. 不新增配置项。
