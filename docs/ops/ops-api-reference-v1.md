# Ops 运营后台 API 全量说明 v1

- 版本：v1
- 最近校准：2026-09-09（手动/自动任务契约、目录字段及相关提交说明；其余接口与专用探测算法未在本轮全面复核）
- 状态：当前口径（随代码演进）
- 代码依据：
  - `/Users/congming/github/goldenshare/src/ops/api/*.py`
  - `/Users/congming/github/goldenshare/src/ops/schemas/*.py`
  - `/Users/congming/github/goldenshare/src/app/api/v1/router.py`

---

## 0. 当前重要状态

当前入口边界：

1. 旧任务运行 API 主链已下线，接口说明不再以旧详情、步骤、事件或日志模型为当前口径。
2. 任务记录、任务详情、重试、停止走 `/api/v1/ops/task-runs*`；手动维护提交入口见下一条。
3. 手动维护页提交入口为 `POST /api/v1/ops/manual-actions/{action_key}/task-runs`。
4. 新任务详情页只消费 `GET /api/v1/ops/task-runs/{id}/view`，完整技术诊断只在需要时读取 `GET /api/v1/ops/task-runs/{id}/issues/{issue_id}`。
5. 自动任务配置表为 `ops.schedule`，调度目标统一使用 `target_type/target_key`。

---

## 1. 说明与约定

1. **统一前缀**：所有本文接口最终路径均为 ` /api/v1/ops/... `。  
2. **鉴权**：
   - 除 `GET /api/v1/ops/overview-summary` 外，均要求 `admin`。
   - `GET /api/v1/ops/overview-summary` 要求登录用户（`authenticated`）。
   - `GET /api/v1/ops/schedules/stream` 使用 query `token` 做流式鉴权。
3. **返回模型**：以 `src/ops/schemas` 的 Pydantic 模型为准。
4. **示例约定**：
   - 示例 host 用 `http://127.0.0.1:8000`。
   - 鉴权头统一：`Authorization: Bearer <TOKEN>`。
   - JSON 示例为关键字段示例，不代表完整业务数据。

---

## 2. 总览与目录类接口

### 2.1 GET /api/v1/ops/overview

- 功能：返回运营首页完整概览（今日 KPI、执行 KPI、freshness 汇总、最近执行/失败）。
- Query 参数：无。
- 返回：`OpsOverviewResponse`
  - `today_kpis, kpis, freshness_summary, lagging_datasets, recent_task_runs, recent_failures`
- 示例（字段节选）：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/overview"
```

```json
{
  "today_kpis": {"business_date": "2026-04-23", "total_requests": 18},
  "kpis": {"total_task_runs": 320, "running_task_runs": 1},
  "freshness_summary": {"total_datasets": 56}
}
```

### 2.2 GET /api/v1/ops/overview-summary

- 功能：返回轻量概览（仅 freshness 汇总），用于轻页面/顶部摘要。
- Query 参数：无。
- 返回：`OpsOverviewSummaryResponse`
  - `freshness_summary`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/overview-summary"
```

```json
{"freshness_summary": {"total_datasets": 56, "fresh_datasets": 51}}
```

### 2.3 GET /api/v1/ops/freshness

- 功能：返回按领域分组的数据新鲜度视图。
- 状态与查询边界见 [Freshness 现行契约](/Users/congming/github/goldenshare/docs/ops/ops-freshness-policy-explicit-mapping-plan-v1.md)；`fresh` 不代表最近任务无失败，也不证明全历史完整。
- Query 参数：无。
- 返回：`OpsFreshnessResponse`
  - `summary`（总体计数）
  - `groups[]`（每个领域的 `DatasetFreshnessItem[]`）
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/freshness"
```

```json
{
  "summary": {"total_datasets": 56, "lagging_datasets": 2},
  "groups": [{"domain_key": "equity_core", "items": []}]
}
```

### 2.4 GET /api/v1/ops/catalog

- 功能：返回可调度动作与工作流目录。数据集动作来自 `DatasetDefinition`，维护动作与工作流来自 `src/ops/action_catalog.py`。
- Query 参数：无。
- 返回：`OpsCatalogResponse`
  - `actions[]`
  - `workflows[]`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/catalog"
```

```json
{
  "actions": [
    {
      "key": "daily.maintain",
      "action_type": "dataset_action",
      "display_name": "维护股票日线",
      "target_key": "daily",
      "group_key": "equity_market",
      "group_label": "A股行情",
      "domain_key": "equity_market",
      "domain_display_name": "股票行情"
    }
  ],
  "workflows": [
    {
      "key": "daily_market_close_maintenance",
      "display_name": "每日收盘后维护",
      "group_key": "workflow",
      "group_label": "工作流"
    }
  ]
}
```

### 2.4.1 GET /api/v1/ops/manual-actions

- 功能：返回手动维护页专用动作目录。该接口面向用户任务语言，隐藏底层执行分支。
- Query 参数：无。
- 返回：`ManualActionListResponse`
  - `groups[]`
  - `groups[].actions[]`
  - dataset action 的 `actions[].date_model` 来自 `DatasetDefinition.date_model`；workflow / maintenance action 为 `null`，使用各自定义派生表单
  - `actions[].time_form` 用于前端选择日期 / 月份控件
  - `actions[].filters` 为页面可展示的非时间、非内部参数
- 关键口径：
  - `time_form` 当前已升级为 `default_mode + modes[]`
  - 每个 `mode item` 声明 `mode/label/description/control/selection_rule`；`date_field` 可为 `null`，不能当成所有模式必填的日期字段
  - `trade_cal.maintain` 正式支持 `none + point + range`；`mode=none` 表示不传日期，按分页拉完整交易日历
  - 默认值、条件限制、单次 unit 上限及时间请求形态见下文 [手动时间契约](#manual-action-time-contract)；下列 JSON 仅为结构节选，不是完整响应
- 鉴权：管理员。
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/manual-actions"
```

```json
{
  "groups": [
    {
      "group_key": "equity_market",
      "group_label": "A股行情",
      "group_order": 2,
      "actions": [
        {
          "action_key": "daily.maintain",
          "action_type": "dataset_action",
          "display_name": "维护股票日线",
          "time_form": {
            "default_mode": "point",
            "modes": [
              {
                "mode": "point",
                "label": "只处理一天",
                "description": "指定单个交易日。",
                "control": "trade_date",
                "selection_rule": "trading_day_only",
                "date_field": "trade_date"
              },
              {
                "mode": "range",
                "label": "处理一个时间区间",
                "description": "指定开始和结束交易日。",
                "control": "trade_date_range",
                "selection_rule": "trading_day_only",
                "date_field": "trade_date"
              }
            ]
          },
          "filters": []
        }
      ]
    }
  ]
}
```

### 2.4.2 POST /api/v1/ops/manual-actions/{action_key}/task-runs

- 功能：按手动维护动作提交一次任务请求。后端先解析并校验 `action_key + time_input + filters`；dataset action 还须通过计划预检，之后才创建 queued TaskRun，不在 Web 请求内执行同步。
- Path 参数：
  - `action_key`：来自 `GET /api/v1/ops/manual-actions`。
- Body：`ManualActionTaskRunCreateRequest`
  - `time_input`：日期、月份或无日期输入。
  - `filters`：对象筛选和附加参数。
- 返回：`TaskRunViewResponse`。
- 鉴权：管理员。
- 拒绝行为：未知动作返回 `404 not_found`；不支持的时间模式、缺必填时间或过滤条件、违反过滤联动规则等返回 `422`。dataset 计划预检的 `IngestionError` 转为 `422`，保留结构化错误 code 和面向运营的说明；预检失败不会创建任务。见 `ManualActionCommandService._preflight_dataset_action`。
- 示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  "http://127.0.0.1:8000/api/v1/ops/manual-actions/daily.maintain/task-runs" \
  -d '{
    "time_input": {"mode": "point", "trade_date": "2026-04-24"},
    "filters": {}
  }'
```

```json
{
  "run": {
    "id": 1001,
    "task_type": "dataset_action",
    "resource_key": "daily",
    "action": "maintain",
    "title": "股票日线",
    "status": "queued"
  },
  "progress": {"unit_total": 0, "unit_done": 0, "unit_failed": 0, "progress_percent": 0, "rows_fetched": 0, "rows_saved": 0, "rows_rejected": 0, "current_object": null, "period_source_summary": null},
  "primary_issue": null,
  "nodes": [],
  "node_total": 0,
  "nodes_truncated": false,
  "actions": {"can_retry": false, "can_cancel": true, "can_copy_params": true}
}
```

<a id="manual-action-time-contract"></a>

### 2.4.3 手动时间、过滤与请求形态

当前类型见 [manual_action schema](/Users/congming/github/goldenshare/src/ops/schemas/manual_action.py)，派生见 [ManualActionQueryService](/Users/congming/github/goldenshare/src/ops/queries/manual_action_query_service.py)。完整字段集中列于 §12.1，不在多个方案维护副本。

| 字段 | 使用语义 |
| --- | --- |
| `time_form.default_mode` | 初始选中模式；`trade_cal.maintain` 为 `none` |
| `time_form.modes[]` | 当前可声明的模式明细，每项为 `none/point/range` 之一；控件属于该模式，不属于整个 action |
| `time_form.max_units_per_execution` | 单次执行 unit 上限，正整数或 `null`；不是最大行数或统一自然日天数，最终按后端计划校验 |
| `conditional_time_rules[]` | `filter_key` 对应值非空时，按 `allowed_time_modes` 收紧模式，显示 `help_text`；多个生效规则取共同允许模式，后端也校验 |
| `filters[]` | 非时间、非内部请求参数；`default_value`、`option_labels`、`select_all_enabled` 分别提供默认值、选项文案和全选能力，前端不自行补造默认策略 |

`control`：`none`、`trade_date`、`trade_date_range`、`calendar_date`、`calendar_date_range`、`month`、`month_range`、`month_window_range`。

`selection_rule`：`none`、`trading_day_only`、`week_last_trading_day`、`month_last_trading_day`、`calendar_day`、`week_friday`、`month_end`、`quarter_end`、`month_key`、`month_window`。来源与输入/执行/审计区别见 [日期指南](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)；不能仅根据 `trade_date` 字段名判定必须是开市日。

请求外壳始终是 `{"time_input": {...}, "filters": {...}}`。下面只列 `time_input` 形态，使用前须确认动作返回的模式、控件、选择规则和过滤限制；不是所有动作都支持全部行。

| 输入 | `time_input` 示例 |
| --- | --- |
| 日期单点 | `{"mode":"point","trade_date":"2026-04-24"}` |
| 日期区间 | `{"mode":"range","start_date":"2026-04-01","end_date":"2026-04-24"}` |
| 公告日期单点 | `{"mode":"point","ann_date":"2026-04-24"}` |
| 公告日期区间 | `{"mode":"range","start_date":"2026-04-01","end_date":"2026-04-24","date_field":"ann_date"}` |
| 月份单点 | `{"mode":"point","month":"202604"}` |
| 月份区间或自然月窗口 | `{"mode":"range","start_month":"202604","end_month":"202606"}` |
| 无显式时间 | `{"mode":"none"}` |

自然月窗口由 resolver 展开，Ops 与页面不把它提前换成月首/月末日期。`none` 不是隐含最近几天或统一清空重建；字段省略时 schema 的 mode 默认值虽为 `none`，仍须通过动作能力校验，调用方应按当前表单明确提交模式。

Workflow 手动动作键为 `workflow:{key}`，与 catalog / schedule 中的 workflow `key/target_key` 区分；调用方消费返回值，不自行拼装或猜测动作类型。表单派生边界及页面回归要求见 [Ops 当前契约 §11](/Users/congming/github/goldenshare/docs/ops/ops-contract-current.md#manual-maintenance)。

### 2.5 GET /api/v1/ops/dataset-cards

- 功能：返回运营后台总览页、数据源页使用的数据集卡片视图。
- 口径：页面不得再自行拼装数据集来源、raw 表名、层级状态、最近同步日期和卡片去重结果；这些展示事实由本接口统一返回。
- 静态事实来源：外部数据集身份、名称、底层领域、来源、raw 表、目标表、交付模式和维护入口从 `DatasetDefinition` 派生；用户可见展示分组来自 Ops 默认展示目录；健康度只来自统一 freshness 事实。`source_key=biz_tableset` 的身份、表、分组、观测策略和生产入口来自 Ops `BizDatasetDefinition`，不进入外部数据集的 `DatasetDefinition`。其中 maintenance producer 复用现有 `MaintenanceActionDefinition` 提供维护入口，Dagster producer 保持只读。
- Query 参数：
  - `source_key`：可选；传入 `tushare`、`biying` 等来源时，返回该来源下已经裁决和去重后的卡片；传入 `biz_tableset` 时进入独立 Biz 分支。当前注册 15 张 Biz 卡片，实际返回量受 limit 限制。
  - `limit`：默认 2000，范围 `1..2000`。
- 返回：`DatasetCardListResponse`
  - `total`：截取前完整卡片数，不一定等于返回 items 数；当前 Biz 查询先完成全部卡片观测再截取，limit 不限制查询工作量。
  - `groups[]`：外部数据集按 Ops 默认展示目录；Biz 按 BizDatasetDefinition 的独立分组，当前为数据集市、板块分析、内容关联、技术指标。
  - `groups[].items[]`（`DatasetCardItem`）
- 示例（字段节选）：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/dataset-cards?source_key=tushare&limit=2000"
```

Biz 数据集示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/dataset-cards?source_key=biz_tableset&limit=2000"
```

Biz 的 11 张 maintenance producer 卡片可提供维护入口，4 张 Dagster producer 卡片保持 Ops 只读；具体观测、排序、错误隔离范围及部署验收见 [Biz 投影契约](/Users/congming/github/goldenshare/docs/ops/ops-biz-dataset-auto-projection-plan-v1.md)。这里仅描述代码，不证明线上已有这些卡片。

下列 JSON 是外部股票日线卡片的字段节选，不是上面 Biz 请求的响应；total=56 仅为历史示例值。

```json
{
  "total": 56,
  "groups": [
    {
      "group_key": "equity_market",
      "group_label": "A股行情",
      "group_order": 2,
      "items": [
        {
          "card_key": "daily",
          "dataset_key": "daily",
          "detail_dataset_key": "daily",
          "display_name": "股票日线",
          "group_key": "equity_market",
          "group_label": "A股行情",
          "domain_key": "equity_market",
          "domain_display_name": "股票行情",
          "status": "healthy",
          "freshness_status": "fresh",
          "delivery_mode_label": "单源服务",
          "raw_table_label": "raw_tushare.daily",
          "last_sync_date": "2026-04-24",
          "primary_action_type": "dataset_action",
          "primary_action_key": "daily.maintain"
        }
      ]
    }
  ]
}
```

## 3. 调度（Schedule）接口

### 3.1 GET /api/v1/ops/schedules

- 功能：分页查询调度配置。
- Query 参数：
  - `status`：可选
  - `target_type`：可选（`dataset_action|workflow|maintenance_action`）
  - `limit`：默认 50，`1..200`
  - `offset`：默认 0，`>=0`
- 返回：`ScheduleListResponse`（`items[], total`）
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/schedules?status=active&limit=50&offset=0"
```

```json
{"total": 12, "items": [{"id": 101, "display_name": "日线自动更新", "status": "active"}]}
```

### 3.2 GET /api/v1/ops/schedules/stream

- 功能：SSE 流式通知调度/执行签名变化。
- Query 参数：
  - `token`：必填，管理员 JWT。
- 返回：`text/event-stream`
  - 事件名：`schedules`
  - payload 字段：`schedule_updated_at, task_run_requested_at, active_task_runs`
- 示例：

```bash
curl -N "http://127.0.0.1:8000/api/v1/ops/schedules/stream?token=<TOKEN>"
```

```text
event: schedules
data: {"schedule_updated_at":"2026-04-23T09:02:00","task_run_requested_at":"2026-04-23T09:03:11","active_task_runs":2}
```

### 3.3 POST /api/v1/ops/schedules

- 功能：创建调度。
- Body：`CreateScheduleRequest`
  - 关键字段：`target_type, target_key, display_name, schedule_type, trigger_mode, cron_expr, next_run_at, timezone, calendar_policy, probe_config, params_json`
  - 目标允许哪些 trigger/schedule type、日期策略和重复方式，以 Catalog 的 `automation_capability` 为准；workflow/maintenance 仅支持普通 schedule，不派生 ProbeRule。
  - `calendar_policy` 当前枚举为 `monthly_last_day / monthly_last_trading_day / monthly_window_current_month / trigger_day_single_range / trigger_day_point / latest_completed_calendar_quarter / since_last_success_day_range`。不是每个目标都支持全部策略；显式动作声明优先于 date_model 派生，详见[日期策略表](/Users/congming/github/goldenshare/docs/ops/ops-schedule-calendar-policy-plan-v1.md#calendar-policies)。
  - `trigger_day_point` 不再限于新闻：news/major_news 仅日内重复，fund_share 还支持每日/每周/每月，fund_div 仅每日/每周/每月且生成 ann_date。只有日内方式要求 `*/N * * * *` 且 N ≥ 3，不能把这个限制套到所有 point 策略。
  - 固定日期/窗口是否允许，读取规则的 `explicit_time_input`；声明 forbidden 时不能混用。策略参数由 `policy_parameters` 声明，实际提交到 `params_json.schedule_policy_params`，如成功窗口策略的 `initial_start_date`。
  - 纯 `trigger_mode=probe` 必须为 `schedule_type=cron`，但 `cron_expr/next_run_at` 均为空；非空时间字段返回 `422 probe_schedule_timing.forbidden`，once 返回 `422 schedule_type.forbidden`。它依靠探测窗口，不计算定时触发。Fallback 仍保留真实定时字段。
- 返回：`ScheduleDetailResponse`
- 示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  "http://127.0.0.1:8000/api/v1/ops/schedules" \
  -d '{
    "target_type":"dataset_action",
    "target_key":"daily.maintain",
    "display_name":"股票日线自动更新",
    "schedule_type":"cron",
    "trigger_mode":"schedule",
    "cron_expr":"0 18 * * 1-5",
    "timezone":"Asia/Shanghai",
    "params_json":{"trade_date":"2026-04-24"}
  }'
```

```json
{"id": 201, "display_name": "股票日线自动更新", "status": "active"}
```

自然月末自动任务示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  "http://127.0.0.1:8000/api/v1/ops/schedules" \
  -d '{
    "target_type":"dataset_action",
    "target_key":"stk_period_bar_month.maintain",
    "display_name":"股票月线自动维护",
    "schedule_type":"cron",
    "trigger_mode":"schedule",
    "cron_expr":"0 19 * * *",
    "timezone":"Asia/Shanghai",
    "calendar_policy":"monthly_last_day",
    "params_json":{"time_input":{"mode":"point"}}
  }'
```

自然月窗口自动任务示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  "http://127.0.0.1:8000/api/v1/ops/schedules" \
  -d '{
    "target_type":"dataset_action",
    "target_key":"index_weight.maintain",
    "display_name":"指数成分权重自动维护",
    "schedule_type":"cron",
    "trigger_mode":"schedule",
    "cron_expr":"0 19 * * *",
    "timezone":"Asia/Shanghai",
    "calendar_policy":"monthly_window_current_month",
    "params_json":{"time_input":{"mode":"range"},"filters":{"index_code":"000300.SH"}}
  }'
```

月末交易日自动任务示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  "http://127.0.0.1:8000/api/v1/ops/schedules" \
  -d '{
    "target_type":"dataset_action",
    "target_key":"index_monthly.maintain",
    "display_name":"指数月线自动维护",
    "schedule_type":"cron",
    "trigger_mode":"schedule",
    "cron_expr":"0 19 * * *",
    "timezone":"Asia/Shanghai",
    "calendar_policy":"monthly_last_trading_day",
    "params_json":{"time_input":{"mode":"point"}}
  }'
```

### 3.4 GET /api/v1/ops/schedules/{schedule_id}

- 功能：读取单个调度详情。
- Path 参数：`schedule_id:int`
- 返回：`ScheduleDetailResponse`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/schedules/201"
```

```json
{"id": 201, "target_type": "dataset_action", "target_key": "daily.maintain", "status": "active"}
```

### 3.5 PATCH /api/v1/ops/schedules/{schedule_id}

- 功能：更新调度（部分字段）。
- Path 参数：`schedule_id:int`
- Body：`UpdateScheduleRequest`
- 返回：`ScheduleDetailResponse`
- 示例：

```bash
curl -X PATCH -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  "http://127.0.0.1:8000/api/v1/ops/schedules/201" \
  -d '{"display_name":"股票日线自动更新（新）","status":"active"}'
```

```json
{"id": 201, "display_name": "股票日线自动更新（新）"}
```

### 3.6 POST /api/v1/ops/schedules/{schedule_id}/pause

- 功能：暂停调度。
- Path 参数：`schedule_id:int`
- 返回：`ScheduleDetailResponse`
- 示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/schedules/201/pause"
```

```json
{"id": 201, "status": "paused"}
```

### 3.7 POST /api/v1/ops/schedules/{schedule_id}/resume

- 功能：恢复调度。
- Path 参数：`schedule_id:int`
- 返回：`ScheduleDetailResponse`
- 示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/schedules/201/resume"
```

```json
{"id": 201, "status": "active"}
```

### 3.8 DELETE /api/v1/ops/schedules/{schedule_id}

- 功能：删除调度。
- Path 参数：`schedule_id:int`
- 返回：`DeleteScheduleResponse`
- 示例：

```bash
curl -X DELETE -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/schedules/201"
```

```json
{"id": 201, "status": "deleted"}
```

### 3.9 GET /api/v1/ops/schedules/{schedule_id}/revisions

- 功能：查询调度修订历史。
- Path 参数：`schedule_id:int`
- 返回：`ScheduleRevisionListResponse`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/schedules/201/revisions"
```

```json
{"total": 3, "items": [{"id": 1, "action": "update"}]}
```

### 3.10 POST /api/v1/ops/schedules/preview

- 功能：预览调度触发时间。
- Body：`SchedulePreviewRequest`
  - `calendar_policy=monthly_last_day` 时，`cron_expr` 只作为执行时分载体，返回时间落在自然月最后一天。
  - `calendar_policy=monthly_last_trading_day` 时，`cron_expr` 只作为执行时分载体，返回时间落在当月最后一个开市交易日（按 `core_serving.trade_calendar` 计算）。
  - `calendar_policy=monthly_window_current_month` 时，`cron_expr` 同样只作为执行时分载体，返回时间落在自然月最后一天；真正维护窗口意图在调度到点创建 TaskRun 时按计划触发时间生成，日期展开由 `DatasetActionResolver` 完成。
  - `trigger_day_single_range / trigger_day_point / latest_completed_calendar_quarter / since_last_success_day_range` 的周期预览使用普通 cron；季末策略还支持 once。业务日期/窗口在创建 TaskRun 时按计划触发时间与时区生成，规则见[日期策略](/Users/congming/github/goldenshare/docs/ops/ops-schedule-calendar-policy-plan-v1.md)。
  - 纯 probe 不调用此接口。此请求不包含 target_type/target_key，不校验目标 capability；预览成功只代表可以计算时间，不代表该目标允许保存或源端已就绪。
- 返回：`SchedulePreviewResponse`
- 示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  "http://127.0.0.1:8000/api/v1/ops/schedules/preview" \
  -d '{"schedule_type":"cron","cron_expr":"0 18 * * 1-5","timezone":"Asia/Shanghai","count":5}'
```

```json
{"schedule_type":"cron","timezone":"Asia/Shanghai","preview_times":["2026-04-23T18:00:00+08:00"]}
```

自然月末预览示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  "http://127.0.0.1:8000/api/v1/ops/schedules/preview" \
  -d '{"schedule_type":"cron","cron_expr":"0 19 * * *","timezone":"Asia/Shanghai","calendar_policy":"monthly_last_day","count":5}'
```

自然月窗口预览示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  "http://127.0.0.1:8000/api/v1/ops/schedules/preview" \
  -d '{"schedule_type":"cron","cron_expr":"0 19 * * *","timezone":"Asia/Shanghai","calendar_policy":"monthly_window_current_month","count":5}'
```

月末交易日预览示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  "http://127.0.0.1:8000/api/v1/ops/schedules/preview" \
  -d '{"schedule_type":"cron","cron_expr":"0 19 * * *","timezone":"Asia/Shanghai","calendar_policy":"monthly_last_trading_day","count":5}'
```

新闻日内高频预览示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  "http://127.0.0.1:8000/api/v1/ops/schedules/preview" \
  -d '{"schedule_type":"cron","cron_expr":"*/3 * * * *","timezone":"Asia/Shanghai","calendar_policy":"trigger_day_point","count":5}'
```

---

## 4. 任务运行（TaskRun）接口

说明：旧任务运行 API 主链已下线。任务记录、任务详情、重试、停止与手动任务提交均以 TaskRun 为当前口径。

### 4.1 GET /api/v1/ops/task-runs

- 功能：分页查询任务队列/历史。
- Query 参数：
  - `status, trigger_source, task_type, resource_key, schedule_id`（可选过滤）
  - `page`：默认 1，`>=1`
  - `limit`：默认 20，`1..200`
  - `offset`：可选，`>=0`；前端为了返回上下文稳定会与 `page` 同步传入
- 返回：`TaskRunListResponse`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/task-runs?status=running&page=1&limit=20&offset=0"
```

```json
{
  "total": 1,
  "items": [
    {
      "id": 285,
      "task_type": "dataset_action",
      "resource_key": "daily",
      "action": "maintain",
      "title": "股票日线",
      "trigger_source": "manual",
      "trigger_source_label": "手动",
      "status": "running",
      "time_scope_label": "2026-04-24",
      "unit_total": 3,
      "unit_done": 1,
      "rows_saved": 1200,
      "primary_issue_title": null,
      "requested_at": "2026-04-26T10:00:00+08:00"
    }
  ]
}
```

### 4.2 GET /api/v1/ops/task-runs/summary

- 功能：按当前筛选条件统计任务状态分布，不受分页影响。
- Query 参数：同 `GET /api/v1/ops/task-runs` 的筛选参数。
- 返回：`TaskRunSummaryResponse`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/task-runs/summary?resource_key=daily"
```

```json
{"total": 41, "queued": 3, "running": 4, "success": 28, "failed": 5, "canceled": 1}
```

### 4.3 POST /api/v1/ops/task-runs

- 功能：创建一次通用 TaskRun 请求。
- 成功状态码：200（路由默认值），不是 202。
- Body：`CreateTaskRunRequest`
  - `task_type`：默认 `dataset_action`
  - `resource_key`：数据集 key
  - `action`：默认 `maintain`
  - `time_input`：日期、月份或无日期输入
  - `filters`：对象筛选和附加参数
- 返回：`TaskRunCreateResponse`
- 示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  "http://127.0.0.1:8000/api/v1/ops/task-runs" \
  -d '{"task_type":"dataset_action","resource_key":"daily","action":"maintain","time_input":{"mode":"point","trade_date":"2026-04-24"},"filters":{}}'
```

```json
{"id": 286, "status": "queued", "title": "股票日线", "resource_key": "daily", "created_at": "2026-04-26T10:01:00+08:00"}
```

### 4.4 GET /api/v1/ops/task-runs/{task_run_id}/view

- 功能：查询任务详情主视图。任务详情页只消费这个聚合 view，不再拼接 steps/events/logs。
- 节点按 sequence_no/id 排序，最多返回 200 个；`node_total/nodes_truncated` 表达总数与截断，不保证返回全部节点，也不是增量响应。
- 执行、计数、3 秒轮询与浏览器 ETA 见 [TaskRun 契约](/Users/congming/github/goldenshare/docs/ops/ops-task-run-observability-redesign-plan-v1.md)；ETA 不新增 API 字段。
- Path 参数：`task_run_id:int`
- 返回：`TaskRunViewResponse`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/task-runs/285/view"
```

```json
{
  "run": {"id": 285, "title": "股票日线", "resource_key": "daily", "status": "success", "trigger_source": "manual", "trigger_source_label": "手动"},
  "progress": {"unit_total": 3, "unit_done": 3, "unit_failed": 0, "progress_percent": 100, "rows_fetched": 5496, "rows_saved": 5496, "rows_rejected": 0, "current_object": null, "period_source_summary": null},
  "primary_issue": null,
  "nodes": [],
  "node_total": 0,
  "nodes_truncated": false,
  "actions": {"can_retry": true, "can_cancel": false, "can_copy_params": true}
}
```

### 4.5 GET /api/v1/ops/task-runs/{task_run_id}/issues/{issue_id}

- 功能：按需读取任务问题完整技术诊断。
- Path 参数：
  - `task_run_id:int`
  - `issue_id:int`
- 返回：`TaskRunIssueDetailResponse`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/task-runs/285/issues/88"
```

```json
{
  "id": 88,
  "task_run_id": 285,
  "severity": "error",
  "code": "ingestion_failed",
  "title": "任务处理失败",
  "operator_message": "任务处理过程中发生异常，需要查看技术诊断后决定是否重提。",
  "technical_message": "Tushare API error: 查询数据失败，请确认参数！可以反馈管理员协助您排查问题",
  "technical_payload": {
    "source_phase": "execute",
    "structured_error": {
      "error_code": "internal_error",
      "error_type": "internal",
      "phase": "source_client",
      "retryable": false,
      "unit_id": "stk_mins:ts_code=000001.SZ:freq=5min:...",
      "details": {
        "api_name": "stk_mins",
        "source_code": 50101,
        "source_response_json": {
          "code": 50101,
          "msg": "查询数据失败，请确认参数！可以反馈管理员协助您排查问题",
          "data": null
        }
      }
    }
  },
  "source_phase": "execute",
  "occurred_at": "2026-04-26T10:02:00+08:00"
}
```

当 Tushare 返回非零业务 `code` 时，`technical_payload.structured_error.details` 会额外提供 `api_name`、`source_code` 和 `source_response_json`。其中 `source_response_json` 保存源端原始 JSON 对象，不做截断；请求 token、请求头不保存。

### 4.6 POST /api/v1/ops/task-runs/{task_run_id}/retry

- 功能：基于指定 TaskRun 复制参数并创建新的 queued 任务。
- Path 参数：`task_run_id:int`
- 返回：`TaskRunCreateResponse`
- 示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/task-runs/285/retry"
```

```json
{"id": 287, "status": "queued", "title": "股票日线", "resource_key": "daily", "created_at": "2026-04-26T10:03:00+08:00"}
```

### 4.7 POST /api/v1/ops/task-runs/{task_run_id}/cancel

- 功能：请求停止 queued/running 任务。
- queued 直接转 canceled，运行中转 canceling；已经标记取消的活动任务重复请求幂等返回，终态请求返回 409。响应仍是 TaskRunCreateResponse，不额外返回 cancel_requested_at。
- Path 参数：`task_run_id:int`
- 返回：`TaskRunCreateResponse`
- 示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/task-runs/285/cancel"
```

```json
{"id": 285, "status": "canceling", "title": "股票日线", "resource_key": "daily", "created_at": "2026-04-26T10:00:00+08:00"}
```

---

## 5. Probe 接口

### 5.1 GET /api/v1/ops/probes

- 功能：分页查询 probe 规则。
- Query 参数：
  - `status, dataset_key, source_key, schedule_id`（可选过滤）
  - `limit` 默认 50（`1..200`）
  - `offset` 默认 0
- 返回：`ProbeRuleListResponse`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/probes?status=active&limit=50"
```

```json
{"total": 4, "items": [{"id": 31, "name": "日线探测", "status": "active"}]}
```

ProbeRule 仅由自动任务的 schedule binding 创建和维护；本接口不提供创建、修改、暂停、恢复或删除规则的写入端点。

### 5.2 GET /api/v1/ops/probes/runs

- 功能：分页查询 probe 运行日志（全局）。
- Query 参数：
  - `probe_rule_id, schedule_id, status, dataset_key, source_key, condition_matched`（可选）
  - `limit` 默认 100（`1..500`）
  - `offset` 默认 0
- 返回：`ProbeRunLogListResponse`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/probes/runs?schedule_id=12&dataset_key=index_daily&condition_matched=true&limit=50"
```

```json
{"total": 10, "items": [{"id": 1, "schedule_id": 12, "status": "success", "triggered_task_run_id": 285}]}
```

### 5.3 GET /api/v1/ops/probes/{probe_rule_id}

- 功能：读取 probe 规则详情。
- Path 参数：`probe_rule_id:int`
- 返回：`ProbeRuleDetailResponse`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/probes/31"
```

```json
{"id": 31, "dataset_key": "daily", "status": "active"}
```

### 5.4 GET /api/v1/ops/probes/{probe_rule_id}/runs

- 功能：查询某条 probe 规则的运行日志。
- Path 参数：`probe_rule_id:int`
- Query 参数：
  - `status`（可选）
  - `limit` 默认 100（`1..500`）
  - `offset` 默认 0
- 返回：`ProbeRunLogListResponse`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/probes/31/runs?status=hit&limit=20"
```

```json
{"total": 2, "items": [{"id": 102, "status": "hit"}]}
```

---

## 6. Resolution Release 接口

### 6.1 GET /api/v1/ops/releases

- 功能：分页查询发布记录。
- Query 参数：`dataset_key, status, limit(1..200), offset`
- 返回：`ResolutionReleaseListResponse`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/releases?dataset_key=daily&limit=50"
```

```json
{"total": 3, "items": [{"id": 9, "dataset_key": "daily", "status": "running"}]}
```

### 6.2 POST /api/v1/ops/releases

- 功能：创建发布记录。
- Body：`CreateResolutionReleaseRequest`
- 返回：`ResolutionReleaseDetailResponse`
- 示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  "http://127.0.0.1:8000/api/v1/ops/releases" \
  -d '{"dataset_key":"daily","target_policy_version":3,"status":"previewing"}'
```

```json
{"id": 9, "dataset_key": "daily", "status": "previewing"}
```

### 6.3 GET /api/v1/ops/releases/{release_id}

- 功能：读取发布详情。
- Path 参数：`release_id:int`
- 返回：`ResolutionReleaseDetailResponse`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/releases/9"
```

```json
{"id": 9, "dataset_key": "daily", "status": "running"}
```

### 6.4 PATCH /api/v1/ops/releases/{release_id}/status

- 功能：更新发布状态。
- Path 参数：`release_id:int`
- Body：`UpdateResolutionReleaseStatusRequest`
- 返回：`ResolutionReleaseDetailResponse`
- 示例：

```bash
curl -X PATCH -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  "http://127.0.0.1:8000/api/v1/ops/releases/9/status" \
  -d '{"status":"finished"}'
```

```json
{"id": 9, "status": "finished"}
```

### 6.5 GET /api/v1/ops/releases/{release_id}/stages

- 功能：分页查询发布分层状态。
- Path 参数：`release_id:int`
- Query 参数：`dataset_key, source_key, stage, limit(1..500), offset`
- 返回：`ResolutionReleaseStageStatusListResponse`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/releases/9/stages?stage=raw&limit=100"
```

```json
{"total": 1, "items": [{"id": 11, "stage": "raw", "status": "success"}]}
```

### 6.6 PUT /api/v1/ops/releases/{release_id}/stages

- 功能：批量 upsert 发布分层状态。
- Path 参数：`release_id:int`
- Body：`UpsertResolutionReleaseStageStatusRequest`
- 返回：`ResolutionReleaseStageStatusListResponse`
- 示例：

```bash
curl -X PUT -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  "http://127.0.0.1:8000/api/v1/ops/releases/9/stages" \
  -d '{"items":[{"dataset_key":"daily","stage":"raw","status":"success","rows_in":5000,"rows_out":5000}]}'
```

```json
{"total": 1, "items": [{"stage": "raw", "status": "success"}]}
```

---

## 7. Std Rule 接口

### 7.1 GET /api/v1/ops/std-rules/mapping

- 功能：分页查询 std mapping 规则。
- 口径：只返回已落库的规则；不会在查询层临时生成默认规则。
- Query 参数：`dataset_key, source_key, status, limit(1..500), offset`
- 返回：`StdMappingRuleListResponse`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/std-rules/mapping?dataset_key=daily&limit=200"
```

```json
{"total": 2, "items": [{"id": 1, "src_field": "open", "std_field": "open"}]}
```

### 7.2 POST /api/v1/ops/std-rules/mapping

- 功能：新增 mapping 规则。
- Body：`CreateStdMappingRuleRequest`
- 返回：`StdMappingRuleListResponse`（当前 dataset/source 下最新列表）
- 示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  "http://127.0.0.1:8000/api/v1/ops/std-rules/mapping" \
  -d '{"dataset_key":"daily","source_key":"tushare","src_field":"open","std_field":"open","status":"active"}'
```

```json
{"total": 3, "items": [{"id": 3, "dataset_key": "daily"}]}
```

### 7.3 PATCH /api/v1/ops/std-rules/mapping/{rule_id}

- 功能：更新 mapping 规则。
- Path 参数：`rule_id:int`
- Body：`UpdateStdMappingRuleRequest`
- 返回：`StdMappingRuleListResponse`
- 示例：

```bash
curl -X PATCH -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  "http://127.0.0.1:8000/api/v1/ops/std-rules/mapping/3" \
  -d '{"transform_fn":"identity_pass_through"}'
```

```json
{"total": 3, "items": [{"id": 3, "transform_fn": "identity_pass_through"}]}
```

### 7.4 POST /api/v1/ops/std-rules/mapping/{rule_id}/disable

- 功能：禁用 mapping 规则。
- Path 参数：`rule_id:int`
- 返回：`StdMappingRuleListResponse`
- 示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/std-rules/mapping/3/disable"
```

```json
{"items": [{"id": 3, "status": "disabled"}], "total": 3}
```

### 7.5 POST /api/v1/ops/std-rules/mapping/{rule_id}/enable

- 功能：启用 mapping 规则。
- Path 参数：`rule_id:int`
- 返回：`StdMappingRuleListResponse`
- 示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/std-rules/mapping/3/enable"
```

```json
{"items": [{"id": 3, "status": "active"}], "total": 3}
```

### 7.6 GET /api/v1/ops/std-rules/cleansing

- 功能：分页查询 std cleansing 规则。
- 口径：只返回已落库的规则；不会在查询层临时生成默认规则。
- Query 参数：`dataset_key, source_key, status, limit(1..500), offset`
- 返回：`StdCleansingRuleListResponse`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/std-rules/cleansing?dataset_key=daily&limit=200"
```

```json
{"total": 2, "items": [{"id": 9, "rule_type": "drop_null"}]}
```

### 7.7 POST /api/v1/ops/std-rules/cleansing

- 功能：新增 cleansing 规则。
- Body：`CreateStdCleansingRuleRequest`
- 返回：`StdCleansingRuleListResponse`
- 示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  "http://127.0.0.1:8000/api/v1/ops/std-rules/cleansing" \
  -d '{"dataset_key":"daily","source_key":"tushare","rule_type":"drop_null","target_fields_json":["open"],"action":"drop_row"}'
```

```json
{"total": 3, "items": [{"id": 11, "status": "active"}]}
```

### 7.8 PATCH /api/v1/ops/std-rules/cleansing/{rule_id}

- 功能：更新 cleansing 规则。
- Path 参数：`rule_id:int`
- Body：`UpdateStdCleansingRuleRequest`
- 返回：`StdCleansingRuleListResponse`
- 示例：

```bash
curl -X PATCH -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  "http://127.0.0.1:8000/api/v1/ops/std-rules/cleansing/11" \
  -d '{"status":"disabled"}'
```

```json
{"items": [{"id": 11, "status": "disabled"}], "total": 3}
```

### 7.9 POST /api/v1/ops/std-rules/cleansing/{rule_id}/disable

- 功能：禁用 cleansing 规则。
- Path 参数：`rule_id:int`
- 返回：`StdCleansingRuleListResponse`
- 示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/std-rules/cleansing/11/disable"
```

```json
{"items": [{"id": 11, "status": "disabled"}], "total": 3}
```

### 7.10 POST /api/v1/ops/std-rules/cleansing/{rule_id}/enable

- 功能：启用 cleansing 规则。
- Path 参数：`rule_id:int`
- 返回：`StdCleansingRuleListResponse`
- 示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/std-rules/cleansing/11/enable"
```

```json
{"items": [{"id": 11, "status": "active"}], "total": 3}
```

---

## 8. Review Center 接口

### 8.1 GET /api/v1/ops/review/index/active

- 功能：查询激活指数池（按资源池）。
- Query 参数：
  - `resource` 默认 `index_daily`
  - `keyword` 可选
  - `data_status` 可选
  - `source_serviceability_status` 可选，仅 `index_daily` 支持：`ready`、`source_delayed`、`serviceability_review_required`
  - `page` 默认 1（`>=1`）
  - `page_size` 默认 50（`1..500`）
- 返回：`ReviewActiveIndexListResponse`。`index_daily` 每行额外提供：
  - `latest_raw_trade_date`：raw 源站日线最新业务日。
  - `source_serviceability_status`：后端统一判定的 public 状态。
  - `source_serviceability_label`、`source_serviceability_action`：页面直接展示的中文状态与下一步建议。
  - `serviceability_reference_date`：本次判断使用的最近已结束开市日。
  - `source_serviceability_reason`：仅供 API 诊断；页面不展示。
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/review/index/active?resource=index_daily&page=1&page_size=50"
```

```json
{"total": 1200, "items": [{"ts_code": "000001.SH", "latest_raw_trade_date": "2026-07-14", "source_serviceability_status": "ready", "source_serviceability_label": "正常", "source_serviceability_action": "无需处理", "serviceability_reference_date": "2026-07-14", "source_serviceability_reason": "ready", "first_seen_date": "2024-01-02"}]}
```

### 8.2 GET /api/v1/ops/review/index/active/candidates

- 功能：搜索不在指定指数激活池中的候选。
- Query 参数：`resource`（默认 `index_daily`）、`keyword`（必填）、`limit`（默认 20，`1..50`）。
- 当 `resource=index_daily` 时，每个候选额外返回 `eligible_for_activation`、`eligibility_message`、`latest_raw_trade_date`、`serviceability_reference_date`。候选必须在最近已结束开市日及之前连续 3 个开市日都已有 raw 日线，才可加入。

### 8.3 POST /api/v1/ops/review/index/active

- 功能：人工加入指数激活池。
- 请求体：`{"resource":"index_daily","ts_code":"000300.SH"}`。
- `resource=index_daily` 时服务端再次校验连续 3 个已结束开市日 raw 供数；不满足返回 HTTP 422 与 `code="source_serviceability_not_ready"`。其它资源保持既有加入规则。

### 8.4 DELETE /api/v1/ops/review/index/active/{ts_code}

- 功能：人工移出指数激活池。
- Query 参数：`resource`，默认 `index_daily`。
- 只删除 `ops.index_series_active` 对应行；不会删除 raw 或 serving 历史数据。

### 9.2 GET /api/v1/ops/review/board/ths

- 功能：查询同花顺板块及成分股。
- Query 参数：
  - `board_type, keyword`（可选）
  - `min_constituent_count` 默认 0
  - `include_members` 默认 true
  - `page` 默认 1
  - `page_size` 默认 30（`1..200`）
- 返回：`ReviewThsBoardListResponse`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/review/board/ths?min_constituent_count=20&page=1&page_size=30"
```

```json
{"total": 100, "items": [{"board_code": "BK001", "constituent_count": 35, "members": []}]}
```

### 9.3 GET /api/v1/ops/review/board/dc

- 功能：查询东财板块及成分股。
- Query 参数：
  - `trade_date`（可选）
  - `idx_type, keyword`（可选）
  - `min_constituent_count` 默认 0
  - `include_members` 默认 true
  - `page` 默认 1
  - `page_size` 默认 30（`1..200`）
- 返回：`ReviewDcBoardListResponse`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/review/board/dc?trade_date=2026-04-23&page=1&page_size=30"
```

```json
{"trade_date": "2026-04-23", "total": 120, "items": [{"board_code": "BK1001"}]}
```

### 9.4 GET /api/v1/ops/review/board/equity-membership

- 功能：查询股票所属板块聚合视图（THS + DC）。
- Query 参数：
  - `trade_date`（可选）
  - `keyword`（可选）
  - `min_board_count` 默认 0
  - `provider` 默认 `all`
  - `page` 默认 1
  - `page_size` 默认 30（`1..200`）
- 返回：`ReviewEquityBoardMembershipListResponse`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/review/board/equity-membership?provider=all&page=1&page_size=30"
```

```json
{"total": 5000, "items": [{"ts_code": "000001.SZ", "board_count": 4, "boards": []}]}
```

### 9.5 GET /api/v1/ops/review/board/equity-suggest

- 功能：股票代码/名称联想建议。
- Query 参数：
  - `keyword`：必填，最短 1 字符
  - `limit`：默认 20（`1..50`）
- 返回：`ReviewEquitySuggestResponse`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/review/board/equity-suggest?keyword=平安&limit=20"
```

```json
{"items": [{"ts_code": "000001.SZ", "name": "平安银行"}]}
```

---

## 10. Runtime（Web 侧兼容占位）接口

> 注意：这两个接口当前不会直接触发执行，固定返回 409（runtime_decoupled）。

### 10.1 POST /api/v1/ops/runtime/scheduler-tick

- 功能：历史兼容入口；提示调度已解耦到独立进程。
- Body：`RuntimeTickRequest`（`limit` 默认 1，`1..1000`）
- 返回：`409 WebAppError`
  - `code=runtime_decoupled`
- 示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  "http://127.0.0.1:8000/api/v1/ops/runtime/scheduler-tick" \
  -d '{"limit":1}'
```

```json
{
  "code": "runtime_decoupled",
  "message": "请通过独立调度器进程处理自动任务，不再由 Web 服务直接执行。"
}
```

### 10.2 POST /api/v1/ops/runtime/worker-run

- 功能：历史兼容入口；提示 worker 已解耦到独立进程。
- Body：`RuntimeTickRequest`
- 返回：`409 WebAppError`（`code=runtime_decoupled`）
- 示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  "http://127.0.0.1:8000/api/v1/ops/runtime/worker-run" \
  -d '{"limit":1}'
```

```json
{
  "code": "runtime_decoupled",
  "message": "请通过独立执行器进程处理等待中的任务，不再由 Web 服务直接执行。"
}
```

---

## 11. 请求体模型字段索引

### 11.1 任务运行与调度

- `CreateTaskRunRequest`：`task_type, resource_key, action, time_input, filters, request_payload, schedule_id`
- `TaskRunTimeInput`：`mode, trade_date, start_date, end_date, month, start_month, end_month, date_field`
- `ManualActionTaskRunCreateRequest`：`time_input, filters`
- `ManualActionTimeInput`：`mode, trade_date, start_date, end_date, month, start_month, end_month, ann_date, date_field`
- `CreateScheduleRequest`：`target_type, target_key, display_name, schedule_type, trigger_mode, cron_expr, timezone, calendar_policy, probe_config, params_json, retry_policy_json, concurrency_policy_json, next_run_at`
- `UpdateScheduleRequest`：`target_type, target_key, display_name, schedule_type, trigger_mode, cron_expr, timezone, calendar_policy, probe_config, params_json, retry_policy_json, concurrency_policy_json, next_run_at`
- `SchedulePreviewRequest`：`schedule_type, cron_expr, timezone, calendar_policy, next_run_at, count`
- `ScheduleProbeConfig`：`window_start, window_end, probe_interval_seconds, max_triggers_per_day, condition_kind`；`source_key` 和 `workflow_dataset_keys` 不可提交，分别返回 `422 source_key.operator_forbidden` 与 `422 workflow_dataset_keys.operator_forbidden`。

`ScheduleProbeConfig.condition_kind` 当前支持：

1. `freshness_latest_open`：读取本地 freshness，判断本地最新业务日是否命中最新开市日。
2. `remote_stk_mins_ready`：仅用于 `stk_mins.maintain`；上海当天经交易日历确认开市后，每个所选频率至少一个样本命中当天数据才创建 TaskRun。正常配置只接受 freq，不接受额外 ts_code；休市或缺日历不回退前一交易日。抽样与调用上限见[分钟探测说明](/Users/congming/github/goldenshare/docs/ops/ops-stk-mins-remote-source-probe-plan-v1.md)。
3. `remote_index_daily_ready`：仅用于 `index_daily.maintain`；上海当天经交易日历确认开市后，全部所选样本命中当天数据才创建 TaskRun。默认五个样本须在 index_daily_raw 请求池，显式 ts_code 最多选前五个作探测；休市或缺日历直接跳过。见[指数探测说明](/Users/congming/github/goldenshare/docs/ops/ops-index-daily-remote-source-probe-plan-v1.md)。
4. `remote_index_mins_ready`：仅用于 `index_mins.maintain`。自动任务必须显式选择 `1min/5min/15min/30min/60min`，探测按 15 个固定代表指数和五个频率串行验证；任一组合未返回目标交易日数据即停止本轮，全部 75 项命中后才创建 TaskRun。最小探测间隔为 300 秒；不支持本地 freshness 作为该数据集的探测条件。
5. `remote_idx_factor_pro_ready`：仅用于 `idx_factor_pro.maintain`，在探测窗口内请求 Tushare 当日指数技术因子的一条最小样本；样本具有非空 `ts_code` 且 `trade_date` 命中最新开市日后，才创建正式全市场单日维护 TaskRun。必须使用空 `filters`、point 时间意图、无 `calendar_policy`；最小探测间隔为 300 秒、每日最多触发一次。此条件不以本地 freshness 代替源站就绪判断。
6. `remote_kpl_list_ready`：仅用于 `kpl_list.maintain`，以“竞价”样本确认源站已在次日 08:30 发布前一开市日榜单；命中后只为该目标交易日创建一次有效的 `kpl_list.maintain` TaskRun。此条件只支持探测触发，不支持定时兜底。
7. `remote_margin_ready`：仅用于 `margin.maintain`。在下一个开市日 `09:00~09:30` 验证 SSE、SZSE、BSE 是否均返回前一开市日数据；三者齐备才创建一个 `margin.maintain(point=D)` TaskRun。此条件只能使用纯探测、空维护参数、无日期策略、固定 `300` 秒间隔与每日一次触发；09:30 前 freshness 保持 `unconfirmed`。
8. `remote_margin_detail_ready`：仅用于 `margin_detail.maintain`。与融资融券汇总相同，在下一个开市日 `09:00~09:30` 验证三个市场的代表证券；三者齐备才创建一个全市场 `margin_detail(point=D)` TaskRun。只能使用纯探测、空维护参数、无日期策略、固定 `300` 秒间隔与每日一次触发。

<a id="remote-source-probe-examples"></a>

以下纯 probe 示例的 cron/next-run 均为空；其他窗口、频率与来源限制仍由目标 capability 校验。示例不是本轮生产配置或源站实测结果。日志状态、日限额与兜底去重的边界见[自动任务契约 §3.3](/Users/congming/github/goldenshare/docs/ops/ops-automation-capability-contract-plan-v1.md#probe-runtime-observation)，不能把一次命中等同于全量完整或全局只触发一次。

`remote_stk_mins_ready` 示例：

```json
{
  "target_type": "dataset_action",
  "target_key": "stk_mins.maintain",
  "display_name": "股票分钟行情源站就绪后同步",
  "schedule_type": "cron",
  "trigger_mode": "probe",
  "cron_expr": null,
  "next_run_at": null,
  "timezone": "Asia/Shanghai",
  "probe_config": {
    "window_start": "15:20",
    "window_end": "18:30",
    "probe_interval_seconds": 300,
    "max_triggers_per_day": 1,
    "condition_kind": "remote_stk_mins_ready"
  },
  "params_json": {
    "time_input": {
      "mode": "point"
    },
    "filters": {
      "freq": ["1min", "5min", "15min", "30min", "60min"]
    }
  }
}
```

`remote_index_daily_ready` 示例：

```json
{
  "target_type": "dataset_action",
  "target_key": "index_daily.maintain",
  "display_name": "指数日线源站就绪后同步",
  "schedule_type": "cron",
  "trigger_mode": "probe",
  "cron_expr": null,
  "next_run_at": null,
  "timezone": "Asia/Shanghai",
  "calendar_policy": null,
  "probe_config": {
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

`remote_idx_factor_pro_ready` 示例：

```json
{
  "target_type": "dataset_action",
  "target_key": "idx_factor_pro.maintain",
  "display_name": "指数技术因子源站就绪后同步",
  "schedule_type": "cron",
  "trigger_mode": "probe",
  "cron_expr": null,
  "next_run_at": null,
  "timezone": "Asia/Shanghai",
  "calendar_policy": null,
  "probe_config": {
    "window_start": "16:00",
    "window_end": "20:00",
    "probe_interval_seconds": 300,
    "max_triggers_per_day": 1,
    "condition_kind": "remote_idx_factor_pro_ready"
  },
  "params_json": {
    "time_input": {
      "mode": "point"
    },
    "filters": {}
  }
}
```

`remote_index_mins_ready` 示例：

```json
{
  "target_type": "dataset_action",
  "target_key": "index_mins.maintain",
  "display_name": "指数分钟行情源站就绪后同步",
  "schedule_type": "cron",
  "trigger_mode": "probe",
  "cron_expr": null,
  "next_run_at": null,
  "timezone": "Asia/Shanghai",
  "calendar_policy": null,
  "probe_config": {
    "window_start": "15:20",
    "window_end": "18:30",
    "probe_interval_seconds": 300,
    "max_triggers_per_day": 1,
    "condition_kind": "remote_index_mins_ready"
  },
  "params_json": {
    "time_input": {"mode": "point"},
    "filters": {"freq": ["1min", "5min", "15min", "30min", "60min"]}
  }
}
```

`remote_kpl_list_ready` 示例：

```json
{
  "target_type": "dataset_action",
  "target_key": "kpl_list.maintain",
  "trigger_mode": "probe",
  "schedule_type": "cron",
  "cron_expr": null,
  "next_run_at": null,
  "timezone": "Asia/Shanghai",
  "probe_config": {
    "window_start": "08:35",
    "window_end": "23:30",
    "probe_interval_seconds": 1800,
    "max_triggers_per_day": 1,
    "condition_kind": "remote_kpl_list_ready"
  },
  "params_json": {
    "time_input": {"mode": "point"},
    "filters": {}
  }
}
```

`remote_margin_ready` 示例：

```json
{
  "target_type": "dataset_action",
  "target_key": "margin.maintain",
  "schedule_type": "cron",
  "trigger_mode": "probe",
  "cron_expr": null,
  "next_run_at": null,
  "timezone": "Asia/Shanghai",
  "probe_config": {
    "window_start": "09:00",
    "window_end": "09:30",
    "probe_interval_seconds": 300,
    "max_triggers_per_day": 1,
    "condition_kind": "remote_margin_ready"
  },
  "params_json": {"time_input": {"mode": "point"}, "filters": {}}
}
```

### 11.2 Probe

ProbeRule 没有对外写入 request；规则只由 `OpsSchedule` 的自动任务 capability 和 binding 生成。Probe API 仅提供规则与运行日志的只读查询。

### 11.3 发布与规则

- `CreateResolutionReleaseRequest`：`dataset_key, target_policy_version, status, rollback_to_release_id`
- `UpdateResolutionReleaseStatusRequest`：`status, finished_at`
- `UpsertResolutionReleaseStageStatusRequest`：`items[]`
- `UpsertResolutionReleaseStageStatusItem`：`dataset_key, source_key, stage, status, rows_in, rows_out, message, updated_at`
- `CreateStdMappingRuleRequest`：`dataset_key, source_key, src_field, std_field, src_type, std_type, transform_fn, lineage_preserved, status, rule_set_version`
- `UpdateStdMappingRuleRequest`：`src_type, std_type, transform_fn, lineage_preserved, status, rule_set_version`
- `CreateStdCleansingRuleRequest`：`dataset_key, source_key, rule_type, target_fields_json, condition_expr, action, status, rule_set_version`
- `UpdateStdCleansingRuleRequest`：`rule_type, target_fields_json, condition_expr, action, status, rule_set_version`

### 11.4 Runtime

- `RuntimeTickRequest`：`limit`

---

## 12. 响应模型字段索引

> 以下为返回模型导航；代码演进后须同步对应章节。2026-09-09 补齐手动动作、ActionParameter、自动任务 capability 及 TaskRun 字段，不表示其余模型已逐字段复验，完整类型以 `src/ops/schemas` 为准。

### 12.1 目录与模式

- `OpsCatalogResponse`：`actions, workflows`
- `ActionCatalogItem`：`key, action_type, display_name, target_key, target_display_name, group_key, group_label, group_order, item_order, domain_key, domain_display_name, freshness_policy, date_selection_rule, description, target_tables, manual_enabled, schedule_enabled, automation_capability, retry_enabled, schedule_binding_count, active_schedule_count, parameters`
- `WorkflowCatalogItem`：`key, display_name, description, group_key, group_label, group_order, domain_key, domain_display_name, parallel_policy, default_schedule_policy, schedule_enabled, automation_capability, manual_enabled, schedule_binding_count, active_schedule_count, parameters, steps`
- `ActionParameterResponse`：`key, display_name, param_type, description, required, options, multi_value, default_value, option_labels, select_all_enabled`
- `WorkflowStepCatalogItem`：`step_key, action_key, dataset_key, display_name, depends_on, default_params`
- `ManualActionListResponse`：`groups`
- `ManualActionGroupResponse`：`group_key, group_label, group_order, actions`
- `ManualActionItemResponse`：`action_key, action_type, display_name, description, resource_key, resource_display_name, date_model, time_form, conditional_time_rules, filters, search_keywords, action_order`
- `ManualActionDateModelResponse`：`date_axis, bucket_rule, window_mode, input_shape, observed_field, audit_applicable, not_applicable_reason`
- `ManualActionTimeFormResponse`：`default_mode, modes, max_units_per_execution`
- `ManualActionTimeModeResponse`：`mode, label, description, control, selection_rule, date_field`
- `ManualActionConditionalTimeRuleResponse`：`filter_key, allowed_time_modes, help_text`
- `DatasetCardListResponse`：`total, groups`
- `DatasetCardGroup`：`group_key, group_label, group_order, items`
- `DatasetCardItem`：`card_key, dataset_key, detail_dataset_key, resource_key, display_name, group_key, group_label, group_order, item_order, domain_key, domain_display_name, status, freshness_status, delivery_mode, delivery_mode_label, delivery_mode_tone, layer_plan, freshness_policy, raw_table, raw_table_label, target_table, latest_business_date, earliest_business_date, latest_observed_at, earliest_observed_at, last_sync_date, latest_success_at, expected_business_date, latest_observed_date, latest_observed_date_label, expected_observed_date, expected_observed_date_label, last_success_label, lag_days, freshness_note, primary_action_type, primary_action_key, active_task_run_status, active_task_run_started_at, auto_schedule_status, auto_schedule_total, auto_schedule_active, auto_schedule_next_run_at, probe_total, probe_active, std_mapping_configured, std_cleansing_configured, resolution_policy_configured`
  - `primary_action_type/primary_action_key` 必须成对使用：外部数据集维护入口为 `dataset_action`；Biz maintenance producer 为 `maintenance_action`；只读卡片两者均为 `null`。页面不得根据 key 自行猜动作类型。

Workflow 字段由 `catalog_query_service.py` 装配：名称、步骤、参数及默认策略来自 `action_catalog.py` 的定义，绑定/激活数由 `ops.schedule` 按 `target_type=workflow, target_key=workflow.key` 统计，展示分组与能力经查询层投影。步骤的 `depends_on/default_params` 返回定义值，不意味着 dispatcher 已实现依赖调度。

当前 catalog 不返回 `WorkflowDefinition.time_regime/workflow_profile/failure_policy_default/resume_supported`，也不返回步骤的 `failure_policy_override/params_override/max_retry_per_unit`。其中 `time_regime` 会参与手动表单派生；“未暴露”与“未使用”不能混同。运行限制见 [Workflow 清单 §2](/Users/congming/github/goldenshare/docs/ops/ops-workflow-catalog-v1.md#2-工作流运行机制代码级)。若未来要新增 API 字段，须先获契约变更批准并同步 schema/query/消费者及测试。

<a id="automation-capability-schema"></a>

#### 自动任务能力字段

代码：`src/ops/schemas/catalog.py`。字段来自现有响应，不是本轮新增 API。不可排程目标的 `automation_capability` 为 null；可排程目标返回以下模型。

| 响应模型 | 完整字段 |
| --- | --- |
| `AutomationCapabilityResponse` | `version, default_trigger_mode, trigger_options, probe_conditions, calendar_policy_rules, time_input_contract, fixed_schedule, repeat_policy` |
| `TriggerModeCapabilityResponse` | `mode, allowed_schedule_types` |
| `ProbeConditionCapabilityResponse` | `kind, label, description, allowed_trigger_modes, calendar_policy, time_input, filters, probe` |
| `FilterCapabilityResponse` | `mode, required_fields, allowed_values, require_complete_allowed_values` |
| `ProbeConfigCapabilityResponse` | `source, source_label, window, probe_interval_seconds, max_triggers_per_day` |
| `ProbeWindowCapabilityResponse` | `mode, start, end` |
| `ProbeIntegerCapabilityResponse` | `mode, value` |
| `CalendarPolicyCapabilityResponse` | `policy, schedule_types, cron_repeat_modes, explicit_time_input, generated_time_mode, generated_time_field, policy_parameters` |
| `AutomationTimeInputContractResponse` | `supported_modes, point_field, range_start_field, range_end_field, granularity` |
| `FixedScheduleCapabilityResponse` | `cron_expr, timezone, display_text` |
| `RepeatPolicyCapabilityResponse` | `allowed_modes, default_mode, default_interval_minutes, minimum_interval_minutes, timezone` |

消费规则：

- `trigger_options` 给出触发方式及允许的 cron/once；`probe_conditions` 只能用于各自的 `allowed_trigger_modes`，不能任意组合。纯 probe 的 cron 分类不代表有 cron 表达式。
- Probe filters 的 mode 为 dataset_default/forbidden/required_allowed_values；完整频率集合要求由 `require_complete_allowed_values` 表达。window 的 mode 为 operator_default/fixed；间隔/上限的 mode 为 operator_default/minimum/fixed，不能忽略固定值或最小值。
- Probe 来源 `source=system_default`；`source_label` 只作说明，不提供来源选择。condition 的 `calendar_policy/time_input` 为 dataset_default 或 forbidden。
- `calendar_policy_rules` 同时表达允许的 schedule types、cron 重复方式、固定时间能否输入、生成 point/range 以及生成字段。生成字段枚举为 trade_date/ann_date/start_date_end_date，不能硬编码为 trade_date。`policy_parameters` 为 ActionParameterResponse 列表，参数值保存到 `params_json.schedule_policy_params`。
- `time_input_contract` 指明普通时间输入模式、point/range 字段与 day/month/none 粒度；不等同于日历策略。`fixed_schedule` 限定固定 cron/时区，`repeat_policy` 表达日内重复的允许方式、默认/最小分钟与时区。三者均可为空，维护动作不能一律当作自由 cron/once。
- 前端缺能力时禁止保存；更完整的目标、绑定与 runtime 边界见[自动任务能力契约](/Users/congming/github/goldenshare/docs/ops/ops-automation-capability-contract-plan-v1.md)。

<a id="task-run-schemas"></a>

### 12.2 任务运行

2026-09-09 按 `src/ops/schemas/task_run.py` 逐字段校准；这里是响应字段索引，类型、可空性和默认值查 schema。创建请求见 §4.3，执行与计数语义见 TaskRun 契约。

- `TaskRunCreateResponse`：`id, status, title, resource_key, created_at`
- `TaskRunTimeScope`：`kind, start, end, label`
- `TaskRunListItem`：`id, task_type, resource_key, action_key, action, title, trigger_source, trigger_source_label, status, status_reason_code, requested_by_username, requested_at, started_at, ended_at, time_scope, time_scope_label, schedule_display_name, unit_total, unit_done, unit_failed, progress_percent, rows_fetched, rows_saved, rows_rejected, rows_deduplicated, primary_issue_id, primary_issue_title`
- `TaskRunListResponse`：`items, total`
- `TaskRunSummaryResponse`：`total, queued, running, success, failed, canceled`
- `TaskRunInfo`：`id, task_type, resource_key, source_key, action_key, action, title, trigger_source, trigger_source_label, status, status_reason_code, requested_by_username, schedule_display_name, time_input, filters, time_scope, time_scope_label, requested_at, queued_at, started_at, ended_at, cancel_requested_at, canceled_at`
- `TaskRunDisplayField`：`label, value`
- `TaskRunDisplayObject`：`title, description, fields`
- `TaskRunRejectionSampleItem`：`field, value, message, row`
- `TaskRunRejectionReasonItem`：`reason_key, reason_code, field, count, label, suggested_action, samples`
- `TaskRunPeriodSourceSummary`：`total_rows, api_rows, derived_daily_rows, other_rows, start_date, end_date`
- `TaskRunPagedUnitTime`：`field, point`
- `TaskRunPagedUnitActive`：`unit_id, unit_index, unit_total, time, phase, current_page_number, completed_page_count, page_limit, unit_rows_fetched, unit_rows_normalized_before_dedupe, unit_rows_staged_unique, unit_rows_deduplicated, unit_rows_rejected, retry_count, observed_short_page, terminal_page_rows`
- `TaskRunPagedUnitResult`：`unit_id, unit_index, time, page_count, retry_count, terminal_page_rows, observed_short_page, rows_fetched, rows_normalized_before_dedupe, rows_staged_unique, rows_deduplicated, rows_rejected, rows_inserted_new, rows_matched_existing, rows_committed, final_scope_count`
- `TaskRunPagedUnitProgress`：`active, completed, completed_truncated`
- `TaskRunProgress`：`unit_total, unit_done, unit_failed, progress_percent, rows_fetched, rows_saved, rows_rejected, rows_deduplicated, ingestion_diagnostics, rejected_reason_counts, rejected_reasons, current_object, period_source_summary, paged_unit_progress`
- `TaskRunIssueSummary`：`id, severity, code, title, operator_message, suggested_action, object, has_technical_detail, occurred_at`
- `TaskRunNodeItem`：`id, parent_node_id, node_key, node_type, sequence_no, title, resource_key, status, time_input, context, rows_fetched, rows_saved, rows_rejected, rows_deduplicated, ingestion_diagnostics, rejected_reason_counts, rejected_reasons, issue_id, started_at, ended_at, duration_ms`
- `TaskRunActions`：`can_retry, can_cancel, can_copy_params`
- `TaskRunViewResponse`：`run, progress, primary_issue, nodes, node_total, nodes_truncated, actions`
- `TaskRunIssueDetailResponse`：`id, task_run_id, node_id, severity, code, title, operator_message, suggested_action, object, technical_message, technical_payload, source_phase, occurred_at`

拒绝样本只用于定位异常行，不是业务事实源；TaskRunRejectionSampleItem 没有 unit_id 字段。period_source_summary 仅为 index_weekly/index_monthly 日期范围内当前 Serving 数据来源统计，不证明本任务写入来源。

paged_unit_progress 为可空强类型投影：active 最多一个，completed 最多 16 个并用 completed_truncated 标记截断；无分页诊断时为空。current_node_id 是内部模型字段，当前 view 不暴露它；页面从 nodes 的 running 状态定位当前节点。

### 12.3 调度

- `ScheduleListResponse`：`items, total`
- `ScheduleListItem`：`id, target_type, target_key, target_display_name, display_name, status, schedule_type, trigger_mode, cron_expr, timezone, calendar_policy, next_run_at, last_triggered_at, created_by_username, updated_by_username, created_at, updated_at`
- `ScheduleDetailResponse`：`id, target_type, target_key, target_display_name, display_name, status, schedule_type, trigger_mode, cron_expr, timezone, calendar_policy, probe_config, params_json, retry_policy_json, concurrency_policy_json, next_run_at, last_triggered_at, created_by_username, updated_by_username, created_at, updated_at`
- `ScheduleRevisionListResponse`：`items, total`
- `ScheduleRevisionItem`：`id, object_type, object_id, action, before_json, after_json, changed_by_username, changed_at`
- `SchedulePreviewResponse`：`schedule_type, timezone, preview_times`
- `DeleteScheduleResponse`：`id, status`
- `ScheduleProbeConfigResponse`：`source, source_label, window_start, window_end, probe_interval_seconds, max_triggers_per_day, condition_kind`；其中 `source` 固定为 `system_default`。

### 12.4 Probe

- `ProbeRuleListResponse`：`items, total`
- `ProbeRuleListItem`：`id, schedule_id, name, dataset_key, trigger_mode, workflow_key, step_key, rule_version, source_key, status, window_start, window_end, probe_interval_seconds, probe_condition_json, on_success_action_json, max_triggers_per_day, timezone_name, last_probed_at, last_triggered_at, created_at, updated_at`
- `ProbeRuleDetailResponse`：`id, schedule_id, name, dataset_key, trigger_mode, workflow_key, step_key, rule_version, source_key, status, window_start, window_end, probe_interval_seconds, probe_condition_json, on_success_action_json, max_triggers_per_day, timezone_name, last_probed_at, last_triggered_at, created_at, updated_at, created_by_username, updated_by_username`
- `ProbeRunLogListResponse`：`items, total`
- `ProbeRunLogItem`：`id, probe_rule_id, schedule_id, probe_rule_name, dataset_key, dataset_display_name, source_key, source_display_name, status, condition_matched, message, payload_json, probed_at, triggered_task_run_id, duration_ms, rule_version, result_code, result_reason, correlation_id`

### 12.5 发布与规则

- `ResolutionReleaseListResponse`：`items, total`
- `ResolutionReleaseListItem`：`id, dataset_key, target_policy_version, status, triggered_by_username, triggered_at, finished_at, rollback_to_release_id, created_at, updated_at`
- `ResolutionReleaseDetailResponse`：同 `ResolutionReleaseListItem`
- `ResolutionReleaseStageStatusListResponse`：`items, total`
- `ResolutionReleaseStageStatusItem`：`id, release_id, dataset_key, source_key, stage, status, rows_in, rows_out, message, updated_at`
- `StdMappingRuleListResponse`：`items, total`
- `StdMappingRuleItem`：`id, dataset_key, source_key, src_field, std_field, src_type, std_type, transform_fn, lineage_preserved, status, rule_set_version, created_at, updated_at`
- `StdCleansingRuleListResponse`：`items, total`
- `StdCleansingRuleItem`：`id, dataset_key, source_key, rule_type, target_fields_json, condition_expr, action, status, rule_set_version, created_at, updated_at`

### 12.6 Review/Freshness

- `OpsFreshnessResponse`：`summary, groups`
- `OpsFreshnessSummary`：`total_datasets, fresh_datasets, lagging_datasets, stale_datasets, unconfirmed_datasets, unknown_datasets, disabled_datasets`
- `FreshnessGroup`：`domain_key, domain_display_name, items`
- `DatasetFreshnessItem`：`dataset_key, resource_key, display_name, domain_key, domain_display_name, target_table, raw_table, freshness_policy, earliest_business_date, observed_business_date, latest_business_date, earliest_observed_at, latest_observed_at, freshness_note, latest_success_at, last_sync_date, expected_business_date, latest_observed_date, latest_observed_date_label, expected_observed_date, expected_observed_date_label, last_success_label, lag_days, freshness_status, recent_failure_message, recent_failure_summary, recent_failure_at, primary_action_key, auto_schedule_status, auto_schedule_total, auto_schedule_active, auto_schedule_next_run_at, active_task_run_status, active_task_run_started_at`
- `ReviewActiveIndexListResponse`：`total, items`
- `ReviewActiveIndexItem`：`resource, ts_code, index_name, first_seen_date, last_seen_date, last_checked_at`
- `ReviewThsBoardListResponse`：`total, items`
- `ReviewThsBoardItem`：`board_code, board_name, exchange, board_type, constituent_count, members`
- `ReviewDcBoardListResponse`：`trade_date, idx_type_options, total, items`
- `ReviewDcBoardItem`：`board_code, board_name, idx_type, constituent_count, members`
- `ReviewEquityBoardMembershipListResponse`：`dc_trade_date, total, items`
- `ReviewEquityBoardMembershipItem`：`ts_code, equity_name, board_count, boards`
- `ReviewEquitySuggestResponse`：`items`
- `ReviewEquitySuggestItem`：`ts_code, name`
- `DateCompletenessRuleListResponse`：`summary, groups`
- `DateCompletenessRuleGroup`：`group_key, group_label, items`；这里的 `group_key` 表示审计能力分组（`supported/unsupported`）。
- `DateCompletenessRuleItem`：`dataset_key, display_name, group_key, group_label, group_order, item_order, domain_key, domain_display_name, target_table, date_axis, bucket_rule, window_mode, input_shape, observed_field, audit_applicable, not_applicable_reason, rule_label`
- `DateCompletenessRunListResponse`：`total, items`
- `DateCompletenessRunItem`：`id, dataset_key, display_name, target_table, run_mode, run_status, result_status, start_date, end_date, date_axis, bucket_rule, window_mode, input_shape, observed_field, bucket_window_rule, bucket_applicability_rule, audit_scope, subject_kind, expected_bucket_count, actual_bucket_count, missing_bucket_count, excluded_bucket_count, gap_range_count, expected_cell_count, actual_cell_count, missing_cell_count, affected_bucket_count, affected_subject_count, detail_truncated, processed_bucket_count, current_bucket_value, current_bucket_label, progress_message, heartbeat_at, current_stage, operator_message, technical_message, requested_by_user_id, schedule_id, requested_at, started_at, finished_at, created_at, updated_at`
---

## 13. 运营后台页面与接口映射（前端调用）

> 代码依据：  
> - 路由：[frontend/src/app/router.tsx](/Users/congming/github/goldenshare/frontend/src/app/router.tsx)  
> - 页面实现：[frontend/src/pages](/Users/congming/github/goldenshare/frontend/src/pages)  
> - 共享请求客户端：[frontend/src/shared/api/client.ts](/Users/congming/github/goldenshare/frontend/src/shared/api/client.ts)

### 13.1 全局登录态相关（运营页通用）

- 只要进入运营后台壳层（`/ops/**`），都会经过 auth context 的当前用户查询：
  - `GET /api/v1/auth/me`
  - 代码：[frontend/src/features/auth/auth-context.tsx](/Users/congming/github/goldenshare/frontend/src/features/auth/auth-context.tsx)

### 13.2 页面 -> 接口清单

1. `OpsTodayPage`（`/ops/today`、`/ops/v21/today`）
   - `GET /api/v1/ops/overview`
   - 代码：[ops-today-page.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-today-page.tsx)
2. `OpsV21OverviewPage`（`/ops/v21/overview`）
   - `GET /api/v1/ops/overview`
   - `GET /api/v1/ops/dataset-cards?limit=2000`
   - 代码：[ops-v21-overview-page.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-overview-page.tsx)
3. `OpsV21TusharePage`（`/ops/v21/datasets/tushare`，复用 `OpsV21SourcePage`）
   - `GET /api/v1/ops/dataset-cards?source_key=tushare&limit=2000`
   - 代码：[ops-v21-tushare-page.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-tushare-page.tsx)、[ops-v21-source-page.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-source-page.tsx)
4. `OpsV21BiyingPage`（`/ops/v21/datasets/biying`，复用 `OpsV21SourcePage`）
   - `GET /api/v1/ops/dataset-cards?source_key=biying&limit=2000`
   - 代码：[ops-v21-biying-page.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-biying-page.tsx)、[ops-v21-source-page.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-source-page.tsx)
5. `OpsV21BizTablePage`（`/ops/v21/datasets/biz`，复用 `OpsV21SourcePage`）
   - `GET /api/v1/ops/dataset-cards?source_key=biz_tableset&limit=2000`
   - 代码：[ops-v21-biz-table-page.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-biz-table-page.tsx)、[ops-v21-source-page.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-source-page.tsx)
6. `OpsV21TaskCenterPage`（`/ops/v21/datasets/tasks`，本体不直接请求 API，三 tab 分别请求）
   - 代码：[ops-v21-task-center-page.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-task-center-page.tsx)
7. `OpsTasksPage`（任务记录 tab）
   - `GET /api/v1/ops/catalog`
   - `GET /api/v1/ops/task-runs?...`
   - `GET /api/v1/ops/task-runs/summary?...`
   - `POST /api/v1/ops/task-runs/{task_run_id}/retry`
   - `POST /api/v1/ops/task-runs/{task_run_id}/cancel`
   - 代码：[ops-v21-task-records-tab.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-task-records-tab.tsx)
8. `OpsManualSyncPage`（手动同步 tab）
   - `GET /api/v1/ops/manual-actions`
   - `GET /api/v1/ops/task-runs/{task_run_id}/view`（从任务记录预填时）
   - `GET /api/v1/ops/schedules/{schedule_id}`（预填时）
   - `POST /api/v1/ops/manual-actions/{action_key}/task-runs`
   - 代码：[ops-v21-task-manual-tab.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-task-manual-tab.tsx)
9. `OpsAutomationPage`（自动运行 tab）
   - `GET /api/v1/ops/catalog`
   - `GET /api/v1/ops/schedules?limit=100`
   - `GET /api/v1/ops/schedules/stream?token=...`（SSE）
   - `GET /api/v1/ops/schedules/{schedule_id}`
   - `GET /api/v1/ops/schedules/{schedule_id}/revisions`
   - `GET /api/v1/ops/task-runs?schedule_id={id}&limit=1`
   - `GET /api/v1/ops/probes?schedule_id={id}&limit=50`
   - `GET /api/v1/ops/probes/runs?schedule_id={id}&dataset_key={dataset_key}&limit=1`
   - `POST /api/v1/ops/schedules/preview`
   - `POST /api/v1/ops/schedules`
   - `PATCH /api/v1/ops/schedules/{schedule_id}`
   - `POST /api/v1/ops/schedules/{schedule_id}/pause`
   - `POST /api/v1/ops/schedules/{schedule_id}/resume`
   - `DELETE /api/v1/ops/schedules/{schedule_id}`
   - 代码：[ops-v21-task-auto-tab.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-task-auto-tab.tsx)
10. `OpsV21DatasetDetailPage`（`/ops/v21/datasets/detail/{datasetKey}`）
   - `GET /api/v1/ops/dataset-cards?limit=2000`
   - `GET /api/v1/ops/task-runs?resource_key=...&limit=20`
   - `GET /api/v1/ops/probes?dataset_key=...&limit=20`
   - `GET /api/v1/ops/releases?dataset_key=...&limit=20`
   - `GET /api/v1/ops/std-rules/mapping?dataset_key=...&limit=100`
   - `GET /api/v1/ops/std-rules/cleansing?dataset_key=...&limit=100`
   - 代码：[ops-v21-dataset-detail-page.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-dataset-detail-page.tsx)
11. `OpsTaskDetailPage`（`/ops/tasks/{taskRunId}`）
    - `GET /api/v1/ops/task-runs/{task_run_id}/view`
    - `GET /api/v1/ops/task-runs/{task_run_id}/issues/{issue_id}`（点击“查看技术诊断”时）
    - `POST /api/v1/ops/task-runs/{task_run_id}/retry`
    - `POST /api/v1/ops/task-runs/{task_run_id}/cancel`
    - 代码：[ops-task-detail-page.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-task-detail-page.tsx)
12. `OpsV21ReviewIndexPage`（`/ops/v21/review/index`）
    - `GET /api/v1/ops/review/index/active?...`
    - 代码：[ops-v21-review-index-page.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-review-index-page.tsx)
13. `OpsV21ReviewBoardPage`（`/ops/v21/review/board`）
    - `GET /api/v1/ops/review/board/ths?...`
    - `GET /api/v1/ops/review/board/dc?...`
    - `GET /api/v1/ops/review/board/equity-membership?...`
    - `GET /api/v1/ops/review/board/equity-suggest?...`
    - 代码：[ops-v21-review-board-page.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-review-board-page.tsx)
14. `OpsV21AccountPage`（`/ops/v21/account`，账户管理页）
    - 该页主要调用 `admin` 路由（不是 `/api/v1/ops/*`）：
    - `GET /api/v1/admin/users?...`
    - `POST /api/v1/admin/users`
    - `PATCH /api/v1/admin/users/{id}`
    - `PATCH /api/v1/admin/users/{id}/roles`
    - `POST /api/v1/admin/users/{id}/suspend`
    - `POST /api/v1/admin/users/{id}/activate`
    - `DELETE /api/v1/admin/users/{id}`
    - `POST /api/v1/admin/users/{id}/reset-password`
    - `GET /api/v1/admin/invites?...`
    - `POST /api/v1/admin/invites`
    - `DELETE /api/v1/admin/invites/{id}`
    - `DELETE /api/v1/admin/invites/{id}/hard-delete`
    - 代码：[ops-v21-account-page.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-account-page.tsx)
### 13.3 路由别名与重定向（无直接接口请求）

- `/ops` -> 重定向到 `/ops/v21/overview`
- `/ops/data-status` -> 重定向到 `/ops/v21/overview`
- `/ops/automation` -> 重定向到 `/ops/v21/datasets/tasks?tab=auto`
- `/ops/manual-sync` -> 重定向到 `/ops/v21/datasets/tasks?tab=manual`
- `/ops/tasks` -> 重定向到 `/ops/v21/datasets/tasks?tab=records`
- `/ops/overview` -> 重定向到 `/ops/v21/today`
- `/ops/freshness` -> 重定向到 `/ops/v21/overview`
- `/ops/schedules` -> 重定向到 `/ops/v21/datasets/tasks?tab=auto`
- `/ops/catalog` -> 重定向到 `/ops/v21/datasets/tasks?tab=manual`

---

## 14. 维护建议

1. 新增/删除 `src/ops/api/*` 路由时，同步更新本文。
2. 新增请求体/响应模型字段时，同步更新第 11、12 节。
3. 前端页面改动（新增/删减页面、页面改调用链）时，同步更新第 13 节。
4. 接口行为与本文不一致时，以代码为准，并在一轮提交内修正文档。
