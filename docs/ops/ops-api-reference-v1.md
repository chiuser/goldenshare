# Ops 运营后台 API 全量说明 v1

- 版本：v1
- 日期：2026-04-26
- 状态：当前口径（随代码演进）
- 代码依据：
  - `/Users/congming/github/goldenshare/src/ops/api/*.py`
  - `/Users/congming/github/goldenshare/src/ops/schemas/*.py`
  - `/Users/congming/github/goldenshare/src/app/api/v1/router.py`

---

## 0. 当前重要状态

截至 2026-04-26：

1. 旧任务运行 API 主链已下线，接口说明不再以旧详情、步骤、事件或日志模型为当前口径。
2. 任务记录、任务详情、重试、停止、手动任务提交统一走 `/api/v1/ops/task-runs*`。
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
  - `today_kpis, kpis, freshness_summary, lagging_datasets, recent_executions, recent_failures`
- 示例（字段节选）：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/overview"
```

```json
{
  "today_kpis": {"business_date": "2026-04-23", "total_requests": 18},
  "kpis": {"total_executions": 320, "running_executions": 1},
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
  - `actions[].date_model` 来自 `DatasetDefinition.date_model`
  - `actions[].time_form` 用于前端选择日期 / 月份控件
  - `actions[].filters` 为页面可展示的非时间、非内部参数
- 关键口径：
  - `time_form` 当前已升级为 `default_mode + modes[]`
  - 每个 `mode item` 必须显式声明 `mode/label/description/control/selection_rule/date_field`
  - `trade_cal.maintain` 正式支持 `none + point + range`；`mode=none` 表示不传日期，按分页拉完整交易日历
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

- 功能：按手动维护动作提交一次任务请求。后端将 `action_key + time_input + filters` 解析为 TaskRun，创建 queued 任务。
- Path 参数：
  - `action_key`：来自 `GET /api/v1/ops/manual-actions`。
- Body：`ManualActionTaskRunCreateRequest`
  - `time_input`：日期、月份或无日期输入。
  - `filters`：对象筛选和附加参数。
- 返回：`TaskRunViewResponse`。
- 鉴权：管理员。
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
  "progress": {"unit_total": 0, "unit_done": 0, "unit_failed": 0, "progress_percent": 0, "rows_fetched": 0, "rows_saved": 0, "rows_rejected": 0, "current_context": {}},
  "primary_issue": null,
  "nodes": [],
  "node_total": 0,
  "nodes_truncated": false,
  "actions": {"can_retry": false, "can_cancel": true, "can_copy_params": true}
}
```

### 2.5 GET /api/v1/ops/dataset-cards

- 功能：返回运营后台总览页、数据源页使用的数据集卡片视图。
- 口径：页面不得再自行拼装数据集来源、raw 表名、层级状态、最近同步日期和卡片去重结果；这些展示事实由本接口统一返回。
- 静态事实来源：数据集身份、名称、底层领域、来源、raw 表、目标表、stage 计划、手动维护入口均从 `DatasetDefinition` 派生；用户可见展示分组来自 Ops 默认展示目录；freshness、layer snapshot、probe 只作为运行观测输入。
- Query 参数：
  - `source_key`：可选；传入 `tushare`、`biying` 等来源时，返回该来源下已经裁决和去重后的卡片。
  - `limit`：默认 2000，范围 `1..2000`。
- 返回：`DatasetCardListResponse`
  - `total`
  - `groups[]`（按 Ops 默认展示目录分组）
  - `groups[].items[]`（`DatasetCardItem`）
- 示例（字段节选）：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/dataset-cards?source_key=tushare&limit=2000"
```

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
          "stage_statuses": [],
          "raw_sources": []
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
  - payload 字段：`schedule_updated_at, execution_requested_at, active_executions`
- 示例：

```bash
curl -N "http://127.0.0.1:8000/api/v1/ops/schedules/stream?token=<TOKEN>"
```

```text
event: schedules
data: {"schedule_updated_at":"2026-04-23T09:02:00","execution_requested_at":"2026-04-23T09:03:11","active_executions":2}
```

### 3.3 POST /api/v1/ops/schedules

- 功能：创建调度。
- Body：`CreateScheduleRequest`
  - 关键字段：`target_type, target_key, display_name, schedule_type, trigger_mode, cron_expr, timezone, calendar_policy, probe_config, params_json`
  - `calendar_policy` 当前支持：
    - `monthly_last_day`：只允许用于 `DatasetDefinition.date_model.bucket_rule=month_last_calendar_day` 的数据集维护动作，且不能与固定 `trade_date` 混用。
    - `monthly_window_current_month`：只允许用于 `month_window + month_window_has_data + start_end_month_window` 的数据集维护动作。运行时按计划触发时间所属月份生成 `start_month/end_month` 自然月窗口意图，`DatasetActionResolver` 再展开为自然月首尾日期；不能与固定维护日期或固定窗口混用。
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
  - `calendar_policy=monthly_window_current_month` 时，`cron_expr` 同样只作为执行时分载体，返回时间落在自然月最后一天；真正维护窗口意图在调度到点创建 TaskRun 时按计划触发时间生成，日期展开由 `DatasetActionResolver` 完成。
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
- Path 参数：`task_run_id:int`
- 返回：`TaskRunViewResponse`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/task-runs/285/view"
```

```json
{
  "run": {"id": 285, "title": "股票日线", "resource_key": "daily", "status": "success", "trigger_source": "manual"},
  "progress": {"unit_total": 3, "unit_done": 3, "unit_failed": 0, "progress_percent": 100, "rows_fetched": 5496, "rows_saved": 5496, "rows_rejected": 0, "current_context": {}},
  "primary_issue": null,
  "nodes": [],
  "node_total": 0,
  "nodes_truncated": false,
  "actions": {"can_retry": false, "can_cancel": false, "can_copy_params": true}
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
  "code": "execution_failed",
  "title": "任务处理失败",
  "operator_message": "任务处理过程中发生异常，需要查看技术诊断后决定是否重提。",
  "technical_message": "psycopg.errors.UniqueViolation",
  "technical_payload": {"source_phase": "execute"},
  "source_phase": "execute",
  "occurred_at": "2026-04-26T10:02:00+08:00"
}
```

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

### 5.2 POST /api/v1/ops/probes

- 功能：创建 probe 规则。
- Body：`CreateProbeRuleRequest`
- 说明：`on_success_action_json` 如需触发数据集维护，使用 `action_type/action_key/request`，不得再写旧动作字段。
- 返回：`ProbeRuleDetailResponse`
- 示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  "http://127.0.0.1:8000/api/v1/ops/probes" \
  -d '{
    "name":"日线探测",
    "dataset_key":"daily",
    "source_key":"tushare",
    "window_start":"15:30",
    "window_end":"17:00",
    "probe_interval_seconds":300,
    "max_triggers_per_day":1
  }'
```

```json
{"id": 31, "name": "日线探测", "status": "active"}
```

### 5.3 GET /api/v1/ops/probes/runs

- 功能：分页查询 probe 运行日志（全局）。
- Query 参数：
  - `probe_rule_id, status, dataset_key, source_key`（可选）
  - `limit` 默认 100（`1..500`）
  - `offset` 默认 0
- 返回：`ProbeRunLogListResponse`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/probes/runs?dataset_key=daily&limit=50"
```

```json
{"total": 10, "items": [{"id": 1, "status": "hit", "triggered_task_run_id": 285}]}
```

### 5.4 GET /api/v1/ops/probes/{probe_rule_id}

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

### 5.5 PATCH /api/v1/ops/probes/{probe_rule_id}

- 功能：更新 probe 规则（部分字段）。
- Path 参数：`probe_rule_id:int`
- Body：`UpdateProbeRuleRequest`
- 返回：`ProbeRuleDetailResponse`
- 示例：

```bash
curl -X PATCH -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  "http://127.0.0.1:8000/api/v1/ops/probes/31" \
  -d '{"probe_interval_seconds":120,"window_end":"16:30"}'
```

```json
{"id": 31, "probe_interval_seconds": 120}
```

### 5.6 POST /api/v1/ops/probes/{probe_rule_id}/pause

- 功能：暂停 probe 规则。
- Path 参数：`probe_rule_id:int`
- 返回：`ProbeRuleDetailResponse`
- 示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/probes/31/pause"
```

```json
{"id": 31, "status": "paused"}
```

### 5.7 POST /api/v1/ops/probes/{probe_rule_id}/resume

- 功能：恢复 probe 规则。
- Path 参数：`probe_rule_id:int`
- 返回：`ProbeRuleDetailResponse`
- 示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/probes/31/resume"
```

```json
{"id": 31, "status": "active"}
```

### 5.8 DELETE /api/v1/ops/probes/{probe_rule_id}

- 功能：删除 probe 规则。
- Path 参数：`probe_rule_id:int`
- 返回：`DeleteProbeRuleResponse`
- 示例：

```bash
curl -X DELETE -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/probes/31"
```

```json
{"id": 31, "status": "deleted"}
```

### 5.9 GET /api/v1/ops/probes/{probe_rule_id}/runs

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

## 8. Layer Snapshot 接口

### 8.1 GET /api/v1/ops/layer-snapshots/history

- 功能：按条件分页查询 layer snapshot 历史。
- Query 参数：
  - `snapshot_date_from, snapshot_date_to`（`YYYY-MM-DD`）
  - `dataset_key, source_key, stage, status`
  - `limit` 默认 200（`1..1000`）
  - `offset` 默认 0
- 返回：`LayerSnapshotHistoryResponse`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/layer-snapshots/history?dataset_key=daily&limit=100"
```

```json
{"total": 20, "items": [{"id": 1, "snapshot_date": "2026-04-23", "status": "success"}]}
```

### 8.2 GET /api/v1/ops/layer-snapshots/latest

- 功能：查询 latest layer snapshot 视图。
- Query 参数：
  - `dataset_key, source_key, stage, status`
  - `limit` 默认 500（`1..5000`）
- 返回：`LayerSnapshotLatestResponse`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/layer-snapshots/latest?stage=raw&limit=500"
```

```json
{"total": 56, "items": [{"dataset_key": "daily", "stage": "raw", "status": "success"}]}
```

---

## 9. Review Center 接口

### 9.1 GET /api/v1/ops/review/index/active

- 功能：查询激活指数池（按资源池）。
- Query 参数：
  - `resource` 默认 `index_daily`
  - `keyword` 可选
  - `page` 默认 1（`>=1`）
  - `page_size` 默认 50（`1..500`）
- 返回：`ReviewActiveIndexListResponse`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/review/index/active?resource=index_daily&page=1&page_size=50"
```

```json
{"total": 1200, "items": [{"ts_code": "000001.SH", "first_seen_date": "2024-01-02"}]}
```

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

## 11. 请求体模型字段（完整）

### 11.1 任务运行与调度

- `CreateTaskRunRequest`：`task_type, resource_key, action, time_input, filters, request_payload, schedule_id`
- `TaskRunTimeInput`：`mode, trade_date, start_date, end_date, month, start_month, end_month, date_field`
- `ManualActionTaskRunCreateRequest`：`time_input, filters`
- `ManualActionTimeInput`：`mode, trade_date, start_date, end_date, month, start_month, end_month, ann_date, date_field`
- `CreateScheduleRequest`：`target_type, target_key, display_name, schedule_type, trigger_mode, cron_expr, timezone, calendar_policy, probe_config, params_json, retry_policy_json, concurrency_policy_json, next_run_at`
- `UpdateScheduleRequest`：`target_type, target_key, display_name, schedule_type, trigger_mode, cron_expr, timezone, calendar_policy, probe_config, params_json, retry_policy_json, concurrency_policy_json, next_run_at`
- `SchedulePreviewRequest`：`schedule_type, cron_expr, timezone, calendar_policy, next_run_at, count`
- `ScheduleProbeConfig`：`source_key, window_start, window_end, probe_interval_seconds, max_triggers_per_day, condition_kind, min_rows_in, workflow_dataset_keys`

### 11.2 Probe

- `CreateProbeRuleRequest`：`name, dataset_key, source_key, status, window_start, window_end, probe_interval_seconds, probe_condition_json, on_success_action_json, max_triggers_per_day, timezone_name`
- `UpdateProbeRuleRequest`：`name, dataset_key, source_key, status, window_start, window_end, probe_interval_seconds, probe_condition_json, on_success_action_json, max_triggers_per_day, timezone_name`

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

## 12. 响应模型字段（完整）

> 以下为 `src/ops/schemas` 中与 API 直接相关的返回模型字段清单。

### 12.1 目录与模式

- `OpsCatalogResponse`：`actions, workflows`
- `ActionCatalogItem`：`key, action_type, display_name, target_key, target_display_name, group_key, group_label, group_order, item_order, domain_key, domain_display_name, date_selection_rule, description, target_tables, manual_enabled, schedule_enabled, retry_enabled, schedule_binding_count, active_schedule_count, parameters`
- `WorkflowCatalogItem`：`key, display_name, description, group_key, group_label, group_order, domain_key, domain_display_name, parallel_policy, default_schedule_policy, schedule_enabled, manual_enabled, schedule_binding_count, active_schedule_count, parameters, steps`
- `ActionParameterResponse`：`key, display_name, param_type, description, required, options, multi_value`
- `WorkflowStepCatalogItem`：`step_key, action_key, dataset_key, display_name, depends_on, default_params`
- `DatasetCardListResponse`：`total, groups`
- `DatasetCardGroup`：`group_key, group_label, group_order, items`
- `DatasetCardItem`：`card_key, dataset_key, detail_dataset_key, resource_key, display_name, group_key, group_label, group_order, item_order, domain_key, domain_display_name, status, freshness_status, delivery_mode, delivery_mode_label, delivery_mode_tone, layer_plan, cadence, raw_table, raw_table_label, target_table, latest_business_date, earliest_business_date, last_sync_date, latest_success_at, expected_business_date, lag_days, freshness_note, primary_action_key, active_task_run_status, active_task_run_started_at, auto_schedule_status, auto_schedule_total, auto_schedule_active, auto_schedule_next_run_at, probe_total, probe_active, std_mapping_configured, std_cleansing_configured, resolution_policy_configured, status_updated_at, stage_statuses, raw_sources`
- `DatasetCardStageStatus`：`stage, stage_label, table_name, source_key, status, rows_in, rows_out, error_count, lag_seconds, message, calculated_at, last_success_at, last_failure_at`
- `DatasetCardSourceStatus`：`source_key, table_name, status, calculated_at`

### 12.2 任务运行

- `TaskRunCreateResponse`：`id, status, title, resource_key, created_at`
- `TaskRunListResponse`：`items, total`
- `TaskRunListItem`：`id, task_type, resource_key, action, title, trigger_source, status, status_reason_code, requested_by_username, requested_at, started_at, ended_at, time_scope, time_scope_label, schedule_display_name, unit_total, unit_done, unit_failed, progress_percent, rows_fetched, rows_saved, rows_rejected, primary_issue_id, primary_issue_title`
- `TaskRunSummaryResponse`：`total, queued, running, success, failed, canceled`
- `TaskRunViewResponse`：`run, progress, primary_issue, nodes, node_total, nodes_truncated, actions`
- `TaskRunInfo`：`id, task_type, resource_key, action, title, trigger_source, status, status_reason_code, requested_by_username, schedule_display_name, time_input, filters, time_scope, time_scope_label, requested_at, queued_at, started_at, ended_at, cancel_requested_at, canceled_at`
- `TaskRunProgress`：`unit_total, unit_done, unit_failed, progress_percent, rows_fetched, rows_saved, rows_rejected, current_context`
- `TaskRunNodeItem`：`id, parent_node_id, node_key, node_type, sequence_no, title, resource_key, status, time_input, context, rows_fetched, rows_saved, rows_rejected, issue_id, started_at, ended_at, duration_ms`
- `TaskRunIssueSummary`：`id, severity, code, title, operator_message, suggested_action, has_technical_detail, occurred_at`
- `TaskRunIssueDetailResponse`：`id, task_run_id, node_id, severity, code, title, operator_message, suggested_action, technical_message, technical_payload, source_phase, occurred_at`
- `TaskRunActions`：`can_retry, can_cancel, can_copy_params`

### 12.3 调度

- `ScheduleListResponse`：`items, total`
- `ScheduleListItem`：`id, target_type, target_key, target_display_name, display_name, status, schedule_type, trigger_mode, cron_expr, timezone, calendar_policy, next_run_at, last_triggered_at, created_by_username, updated_by_username, created_at, updated_at`
- `ScheduleDetailResponse`：`id, target_type, target_key, target_display_name, display_name, status, schedule_type, trigger_mode, cron_expr, timezone, calendar_policy, probe_config, params_json, retry_policy_json, concurrency_policy_json, next_run_at, last_triggered_at, created_by_username, updated_by_username, created_at, updated_at`
- `ScheduleRevisionListResponse`：`items, total`
- `ScheduleRevisionItem`：`id, object_type, object_id, action, before_json, after_json, changed_by_username, changed_at`
- `SchedulePreviewResponse`：`schedule_type, timezone, preview_times`
- `DeleteScheduleResponse`：`id, status`

### 12.4 Probe

- `ProbeRuleListResponse`：`items, total`
- `ProbeRuleListItem`：`id, schedule_id, name, dataset_key, trigger_mode, workflow_key, step_key, rule_version, source_key, status, window_start, window_end, probe_interval_seconds, probe_condition_json, on_success_action_json, max_triggers_per_day, timezone_name, last_probed_at, last_triggered_at, created_at, updated_at`
- `ProbeRuleDetailResponse`：`id, schedule_id, name, dataset_key, trigger_mode, workflow_key, step_key, rule_version, source_key, status, window_start, window_end, probe_interval_seconds, probe_condition_json, on_success_action_json, max_triggers_per_day, timezone_name, last_probed_at, last_triggered_at, created_at, updated_at, created_by_username, updated_by_username`
- `ProbeRunLogListResponse`：`items, total`
- `ProbeRunLogItem`：`id, probe_rule_id, probe_rule_name, dataset_key, dataset_display_name, source_key, source_display_name, status, condition_matched, message, payload_json, probed_at, triggered_task_run_id, duration_ms, rule_version, result_code, result_reason, correlation_id`
- `DeleteProbeRuleResponse`：`id, status`

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

### 12.6 Snapshot/Review/Freshness

- `LayerSnapshotHistoryResponse`：`items, total`
- `LayerSnapshotHistoryItem`：`id, snapshot_date, dataset_key, source_key, stage, status, rows_in, rows_out, error_count, last_success_at, last_failure_at, lag_seconds, message, calculated_at`
- `LayerSnapshotLatestResponse`：`items, total`
- `LayerSnapshotLatestItem`：`snapshot_date, dataset_key, source_key, stage, status, rows_in, rows_out, error_count, last_success_at, last_failure_at, lag_seconds, message, calculated_at`
- `OpsFreshnessResponse`：`summary, groups`
- `OpsFreshnessSummary`：`total_datasets, fresh_datasets, lagging_datasets, stale_datasets, unknown_datasets, disabled_datasets`
- `FreshnessGroup`：`domain_key, domain_display_name, items`
- `DatasetFreshnessItem`：`dataset_key, resource_key, display_name, domain_key, domain_display_name, target_table, raw_table, cadence, earliest_business_date, observed_business_date, latest_business_date, freshness_note, latest_success_at, last_sync_date, expected_business_date, lag_days, freshness_status, recent_failure_message, recent_failure_summary, recent_failure_at, primary_action_key, auto_schedule_status, auto_schedule_total, auto_schedule_active, auto_schedule_next_run_at, active_execution_status, active_execution_started_at`
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
5. `OpsV21TaskCenterPage`（`/ops/v21/datasets/tasks`，本体不直接请求 API，三 tab 分别请求）
   - 代码：[ops-v21-task-center-page.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-task-center-page.tsx)
6. `OpsTasksPage`（任务记录 tab）
   - `GET /api/v1/ops/catalog`
   - `GET /api/v1/ops/task-runs?...`
   - `GET /api/v1/ops/task-runs/summary?...`
   - `POST /api/v1/ops/task-runs/{task_run_id}/retry`
   - `POST /api/v1/ops/task-runs/{task_run_id}/cancel`
   - 代码：[ops-v21-task-records-tab.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-task-records-tab.tsx)
7. `OpsManualSyncPage`（手动同步 tab）
   - `GET /api/v1/ops/manual-actions`
   - `GET /api/v1/ops/task-runs/{task_run_id}/view`（从任务记录预填时）
   - `GET /api/v1/ops/schedules/{schedule_id}`（预填时）
   - `POST /api/v1/ops/manual-actions/{action_key}/task-runs`
   - 代码：[ops-v21-task-manual-tab.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-task-manual-tab.tsx)
8. `OpsAutomationPage`（自动运行 tab）
   - `GET /api/v1/ops/catalog`
   - `GET /api/v1/ops/schedules?limit=100`
   - `GET /api/v1/ops/schedules/stream?token=...`（SSE）
   - `GET /api/v1/ops/schedules/{schedule_id}`
   - `GET /api/v1/ops/schedules/{schedule_id}/revisions`
   - `GET /api/v1/ops/task-runs?schedule_id={id}&limit=1`
   - `GET /api/v1/ops/probes?schedule_id={id}&limit=50`
   - `POST /api/v1/ops/schedules/preview`
   - `POST /api/v1/ops/schedules`
   - `PATCH /api/v1/ops/schedules/{schedule_id}`
   - `POST /api/v1/ops/schedules/{schedule_id}/pause`
   - `POST /api/v1/ops/schedules/{schedule_id}/resume`
   - `DELETE /api/v1/ops/schedules/{schedule_id}`
   - 代码：[ops-v21-task-auto-tab.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-task-auto-tab.tsx)
9. `OpsV21DatasetDetailPage`（`/ops/v21/datasets/detail/{datasetKey}`）
   - `GET /api/v1/ops/dataset-cards?limit=2000`
   - `GET /api/v1/ops/layer-snapshots/history?dataset_key=...&limit=50`
   - `GET /api/v1/ops/task-runs?resource_key=...&limit=20`
   - `GET /api/v1/ops/probes?dataset_key=...&limit=20`
   - `GET /api/v1/ops/releases?dataset_key=...&limit=20`
   - `GET /api/v1/ops/std-rules/mapping?dataset_key=...&limit=100`
   - `GET /api/v1/ops/std-rules/cleansing?dataset_key=...&limit=100`
   - 代码：[ops-v21-dataset-detail-page.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-dataset-detail-page.tsx)
10. `OpsTaskDetailPage`（`/ops/tasks/{taskRunId}`）
    - `GET /api/v1/ops/task-runs/{task_run_id}/view`
    - `GET /api/v1/ops/task-runs/{task_run_id}/issues/{issue_id}`（点击“查看技术诊断”时）
    - `POST /api/v1/ops/task-runs/{task_run_id}/retry`
    - `POST /api/v1/ops/task-runs/{task_run_id}/cancel`
    - 代码：[ops-task-detail-page.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-task-detail-page.tsx)
11. `OpsV21ReviewIndexPage`（`/ops/v21/review/index`）
    - `GET /api/v1/ops/review/index/active?...`
    - 代码：[ops-v21-review-index-page.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-review-index-page.tsx)
12. `OpsV21ReviewBoardPage`（`/ops/v21/review/board`）
    - `GET /api/v1/ops/review/board/ths?...`
    - `GET /api/v1/ops/review/board/dc?...`
    - `GET /api/v1/ops/review/board/equity-membership?...`
    - `GET /api/v1/ops/review/board/equity-suggest?...`
    - 代码：[ops-v21-review-board-page.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-review-board-page.tsx)
13. `OpsV21AccountPage`（`/ops/v21/account`，账户管理页）
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
