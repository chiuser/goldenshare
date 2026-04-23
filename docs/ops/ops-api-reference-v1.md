# Ops 运营后台 API 全量说明 v1

- 版本：v1
- 日期：2026-04-23
- 状态：当前口径（随代码演进）
- 代码依据：
  - `/Users/congming/github/goldenshare/src/ops/api/*.py`
  - `/Users/congming/github/goldenshare/src/ops/schemas/*.py`
  - `/Users/congming/github/goldenshare/src/app/api/v1/router.py`

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
- 示例：

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

- 功能：返回可调度对象目录（job spec + workflow spec + 参数规格）。
- Query 参数：无。
- 返回：`OpsCatalogResponse`
  - `job_specs[]`
  - `workflow_specs[]`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/catalog"
```

```json
{
  "job_specs": [{"key": "sync_daily.daily", "display_name": "股票日线（日常同步）"}],
  "workflow_specs": [{"key": "daily_market_close_sync", "display_name": "每日收盘同步"}]
}
```

### 2.5 GET /api/v1/ops/pipeline-modes

- 功能：返回数据集 pipeline mode 列表（单源直出/多源融合等）。
- Query 参数：
  - `limit`：默认 500，范围 `1..2000`
  - `offset`：默认 0，`>=0`
- 返回：`DatasetPipelineModeListResponse`
  - `total`
  - `items[]`（`DatasetPipelineModeItem`）
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/pipeline-modes?limit=200&offset=0"
```

```json
{
  "total": 56,
  "items": [{"dataset_key": "daily", "mode": "single_source_direct"}]
}
```

### 2.6 GET /api/v1/ops/source-management/bridge

- 功能：返回数据源页面聚合桥接数据（probe/release/std rule/layer snapshot）。
- Query 参数：
  - `probe_limit`：默认 20，`1..200`
  - `release_limit`：默认 20，`1..200`
  - `std_rule_limit`：默认 200，`1..500`
  - `layer_limit`：默认 500，`1..5000`
- 返回：`SourceManagementBridgeResponse`
  - `summary`
  - `probe_rules, releases, std_mapping_rules, std_cleansing_rules, layer_latest`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/source-management/bridge?probe_limit=10&release_limit=10"
```

```json
{
  "summary": {"probe_total": 8, "release_total": 5, "layer_latest_total": 120},
  "probe_rules": [],
  "releases": []
}
```

---

## 3. 调度（Schedule）接口

### 3.1 GET /api/v1/ops/schedules

- 功能：分页查询调度配置。
- Query 参数：
  - `status`：可选
  - `spec_type`：可选（`job|workflow`）
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
  - 关键字段：`spec_type, spec_key, display_name, schedule_type, trigger_mode, cron_expr, timezone, probe_config, params_json`
- 返回：`ScheduleDetailResponse`
- 示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  "http://127.0.0.1:8000/api/v1/ops/schedules" \
  -d '{
    "spec_type":"job",
    "spec_key":"sync_daily.daily",
    "display_name":"股票日线自动更新",
    "schedule_type":"cron",
    "trigger_mode":"schedule",
    "cron_expr":"0 18 * * 1-5",
    "timezone":"Asia/Shanghai",
    "params_json":{"trade_date":"20260423"}
  }'
```

```json
{"id": 201, "display_name": "股票日线自动更新", "status": "active"}
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
{"id": 201, "spec_key": "sync_daily.daily", "status": "active"}
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

---

## 4. 执行（Execution）接口

### 4.1 GET /api/v1/ops/executions

- 功能：分页查询执行请求队列/历史。
- Query 参数：
  - `status, trigger_source, spec_type, spec_key, dataset_key, source_key, stage, run_scope, schedule_id`（可选过滤）
  - `limit`：默认 50，`1..200`
  - `offset`：默认 0，`>=0`
- 返回：`ExecutionListResponse`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/executions?status=running&limit=50&offset=0"
```

```json
{"total": 1, "items": [{"id": 285, "status": "running", "spec_key": "sync_daily.daily"}]}
```

### 4.2 GET /api/v1/ops/executions/{execution_id}

- 功能：查询单个 execution 详情（含 steps/events）。
- Path 参数：`execution_id:int`
- 返回：`ExecutionDetailResponse`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/executions/285"
```

```json
{"id": 285, "status": "running", "steps": [], "events": []}
```

### 4.3 GET /api/v1/ops/executions/{execution_id}/steps

- 功能：查询 execution 的步骤视图。
- Path 参数：`execution_id:int`
- 返回：`ExecutionStepsResponse`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/executions/285/steps"
```

```json
{"execution_id": 285, "items": [{"id": 901, "step_key": "raw", "status": "running"}]}
```

### 4.4 GET /api/v1/ops/executions/{execution_id}/events

- 功能：查询 execution 事件流。
- Path 参数：`execution_id:int`
- 返回：`ExecutionEventsResponse`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/executions/285/events"
```

```json
{"execution_id": 285, "items": [{"id": 1, "event_type": "unit_started", "level": "info"}]}
```

### 4.5 GET /api/v1/ops/executions/{execution_id}/logs

- 功能：查询 execution 兼容日志视图。
- Path 参数：`execution_id:int`
- 返回：`ExecutionLogsResponse`
- 示例：

```bash
curl -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/executions/285/logs"
```

```json
{"execution_id": 285, "items": [{"id": 11, "job_name": "sync_daily.daily", "status": "running"}]}
```

### 4.6 POST /api/v1/ops/executions

- 功能：创建一次手动 execution 请求（入队）。
- Body：`CreateExecutionRequest`
  - `spec_type, spec_key, params_json`
- 返回：`ExecutionDetailResponse`（新 execution 详情）
- 示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" -H "Content-Type: application/json" \
  "http://127.0.0.1:8000/api/v1/ops/executions" \
  -d '{"spec_type":"job","spec_key":"sync_daily.daily","params_json":{"trade_date":"20260423"}}'
```

```json
{"id": 286, "status": "queued", "spec_key": "sync_daily.daily"}
```

### 4.7 POST /api/v1/ops/executions/{execution_id}/retry

- 功能：重试指定 execution，创建新的 execution。
- Path 参数：`execution_id:int`
- 返回：`ExecutionDetailResponse`（新 execution）
- 示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/executions/285/retry"
```

```json
{"id": 287, "status": "queued"}
```

### 4.8 POST /api/v1/ops/executions/{execution_id}/cancel

- 功能：取消执行（queued/running）。
- Path 参数：`execution_id:int`
- 返回：`ExecutionDetailResponse`
- 示例：

```bash
curl -X POST -H "Authorization: Bearer <TOKEN>" \
  "http://127.0.0.1:8000/api/v1/ops/executions/285/cancel"
```

```json
{"id": 285, "status": "canceling"}
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
{"total": 10, "items": [{"id": 1, "status": "hit", "triggered_execution_id": 285}]}
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

### 11.1 执行与调度

- `CreateExecutionRequest`：`spec_type, spec_key, params_json`
- `CreateScheduleRequest`：`spec_type, spec_key, display_name, schedule_type, trigger_mode, cron_expr, timezone, calendar_policy, probe_config, params_json, retry_policy_json, concurrency_policy_json, next_run_at`
- `UpdateScheduleRequest`：`spec_type, spec_key, display_name, schedule_type, trigger_mode, cron_expr, timezone, calendar_policy, probe_config, params_json, retry_policy_json, concurrency_policy_json, next_run_at`
- `SchedulePreviewRequest`：`schedule_type, cron_expr, timezone, next_run_at, count`
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

- `OpsCatalogResponse`：`job_specs, workflow_specs`
- `JobSpecCatalogItem`：`key, display_name, resource_key, resource_display_name, category, description, strategy_type, executor_kind, target_tables, supports_manual_run, supports_schedule, supports_retry, schedule_binding_count, active_schedule_count, supported_params`
- `WorkflowSpecCatalogItem`：`key, display_name, description, parallel_policy, default_schedule_policy, supports_schedule, supports_manual_run, schedule_binding_count, active_schedule_count, supported_params, steps`
- `ParameterSpecResponse`：`key, display_name, param_type, description, required, options, multi_value`
- `WorkflowStepResponse`：`step_key, job_key, display_name, depends_on, default_params`
- `DatasetPipelineModeListResponse`：`total, items`
- `DatasetPipelineModeItem`：`dataset_key, display_name, domain_key, domain_display_name, mode, source_scope, layer_plan, raw_table, std_table_hint, serving_table, freshness_status, latest_business_date, std_mapping_configured, std_cleansing_configured, resolution_policy_configured`

### 12.2 执行

- `ExecutionListResponse`：`items, total`
- `ExecutionListItem`：`id, spec_type, spec_key, dataset_key, source_key, stage, policy_version, run_scope, run_profile, workflow_profile, correlation_id, rerun_id, resume_from_step_key, status_reason_code, spec_display_name, schedule_display_name, trigger_source, status, requested_by_username, requested_at, started_at, ended_at, rows_fetched, rows_written, progress_current, progress_total, progress_percent, progress_message, last_progress_at, summary_message, error_code`
- `ExecutionDetailResponse`：`id, schedule_id, spec_type, spec_key, dataset_key, source_key, stage, policy_version, run_scope, run_profile, workflow_profile, correlation_id, rerun_id, resume_from_step_key, status_reason_code, spec_display_name, schedule_display_name, trigger_source, status, requested_by_username, requested_at, queued_at, started_at, ended_at, params_json, summary_message, rows_fetched, rows_written, progress_current, progress_total, progress_percent, progress_message, last_progress_at, cancel_requested_at, canceled_at, error_code, error_message, steps, events`
- `ExecutionStepsResponse`：`execution_id, items`
- `ExecutionStepItem`：`id, step_key, display_name, sequence_no, unit_kind, unit_value, status, started_at, ended_at, rows_fetched, rows_written, message, failure_policy_effective, depends_on_step_keys_json, blocked_by_step_key, skip_reason_code, unit_total, unit_done, unit_failed`
- `ExecutionEventsResponse`：`execution_id, items`
- `ExecutionEventItem`：`id, step_id, event_type, level, message, payload_json, occurred_at, event_id, event_version, correlation_id, unit_id, producer, dedupe_key`
- `ExecutionLogsResponse`：`execution_id, items`
- `ExecutionLogItem`：`id, execution_id, job_name, run_type, status, started_at, ended_at, rows_fetched, rows_written, message`

### 12.3 调度

- `ScheduleListResponse`：`items, total`
- `ScheduleListItem`：`id, spec_type, spec_key, spec_display_name, display_name, status, schedule_type, trigger_mode, cron_expr, timezone, calendar_policy, next_run_at, last_triggered_at, created_by_username, updated_by_username, created_at, updated_at`
- `ScheduleDetailResponse`：`id, spec_type, spec_key, spec_display_name, display_name, status, schedule_type, trigger_mode, cron_expr, timezone, calendar_policy, probe_config, params_json, retry_policy_json, concurrency_policy_json, next_run_at, last_triggered_at, created_by_username, updated_by_username, created_at, updated_at`
- `ScheduleRevisionListResponse`：`items, total`
- `ScheduleRevisionItem`：`id, object_type, object_id, action, before_json, after_json, changed_by_username, changed_at`
- `SchedulePreviewResponse`：`schedule_type, timezone, preview_times`
- `DeleteScheduleResponse`：`id, status`

### 12.4 Probe

- `ProbeRuleListResponse`：`items, total`
- `ProbeRuleListItem`：`id, schedule_id, name, dataset_key, trigger_mode, workflow_key, step_key, rule_version, source_key, status, window_start, window_end, probe_interval_seconds, probe_condition_json, on_success_action_json, max_triggers_per_day, timezone_name, last_probed_at, last_triggered_at, created_at, updated_at`
- `ProbeRuleDetailResponse`：`id, schedule_id, name, dataset_key, trigger_mode, workflow_key, step_key, rule_version, source_key, status, window_start, window_end, probe_interval_seconds, probe_condition_json, on_success_action_json, max_triggers_per_day, timezone_name, last_probed_at, last_triggered_at, created_at, updated_at, created_by_username, updated_by_username`
- `ProbeRunLogListResponse`：`items, total`
- `ProbeRunLogItem`：`id, probe_rule_id, probe_rule_name, dataset_key, source_key, status, condition_matched, message, payload_json, probed_at, triggered_execution_id, duration_ms, rule_version, result_code, result_reason, correlation_id`
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
- `DatasetFreshnessItem`：`dataset_key, resource_key, display_name, domain_key, domain_display_name, job_name, target_table, raw_table, cadence, state_business_date, earliest_business_date, observed_business_date, latest_business_date, business_date_source, freshness_note, latest_success_at, last_sync_date, expected_business_date, lag_days, freshness_status, recent_failure_message, recent_failure_summary, recent_failure_at, primary_execution_spec_key, full_sync_done, auto_schedule_status, auto_schedule_total, auto_schedule_active, auto_schedule_next_run_at, active_execution_status, active_execution_started_at`
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
- `SourceManagementBridgeResponse`：`summary, probe_rules, releases, std_mapping_rules, std_cleansing_rules, layer_latest`
- `SourceManagementBridgeSummary`：`probe_total, probe_active, release_total, release_running, std_mapping_total, std_mapping_active, std_cleansing_total, std_cleansing_active, layer_latest_total, layer_latest_failed`

---

## 13. 维护建议

1. 新增/删除 `src/ops/api/*` 路由时，同步更新本文。
2. 新增请求体/响应模型字段时，同步更新第 11、12 节。
3. 接口行为与本文不一致时，以代码为准，并在一轮提交内修正文档。

