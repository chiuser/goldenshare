# 手动维护动作模型收敛方案 v2

更新时间：2026-04-24  
状态：当前执行口径  
适用范围：`src/ops/api/*`、`src/ops/queries/*`、`src/ops/schemas/*`、`src/ops/services/*`、`frontend/src/pages/ops-v21-task-manual-tab.tsx`

---

## 1. 一句话结论

手动维护任务只允许暴露“维护动作”给用户；日期语义、输入条件和动作键必须从 `DatasetDefinition` 派生；后端通过 `DatasetActionRequest -> DatasetExecutionPlan -> IngestionExecutor` 执行，不再把旧执行分支或旧 spec 口径暴露给页面。

目标三层模型：

1. `ManualAction`：用户看到的“维护什么数据”
2. `DatasetDefinition.date_model`：数据集日期语义的单一事实源
3. `DatasetActionRequest`：后端内部把 action、time_input、filters 解析为执行计划

---

## 2. 已确认口径

1. 用户不需要理解历史执行路由。
2. 手动维护页不再把 `日常同步 / 按交易日回补 / 历史同步 / 所属类型` 作为主路径文案。
3. 前端不再持有旧的多执行规格字段。
4. `/api/v1/ops/catalog` 输出当前 action/workflow 目录，不再表达旧执行规格。
5. `/api/v1/ops/manual-actions` 是手动维护专用用户动作目录，不替代 `catalog`。
6. 手动 dataset action 提交直接创建 TaskRun，不再还原成旧执行路径。
7. 日期输入、控件选择、单点/区间能力从 `date_model.window_mode/input_shape/date_axis/bucket_rule` 派生，不新增第二套日期规则表。

---

## 3. 当前 `/ops/catalog` 边界

`GET /api/v1/ops/catalog` 当前仍被以下运行时代码使用：

1. 手动任务页：构造当前过渡期手动维护对象。
2. 自动任务页：创建和编辑 schedule，仍需要系统级 `job/workflow spec`。
3. 任务记录页：使用 TaskRun API 返回的结构化 `action_key/resource_display_name/action_display_name` 做筛选和展示，不从 key 反推名称。

因此，目标态不是删除 `catalog`，而是：

1. 手动维护页切到 `GET /api/v1/ops/manual-actions`。
2. 自动任务页继续使用 `GET /api/v1/ops/catalog`。
3. 任务记录页短期继续使用 `GET /api/v1/ops/catalog`。
4. 后续若任务记录筛选需要更轻量接口，再单独设计。

---

## 4. API 设计

### 4.1 手动维护动作目录

新增：

```text
GET /api/v1/ops/manual-actions
```

响应结构：

```json
{
  "groups": [
    {
      "group_key": "equity_market",
      "group_label": "股票行情",
      "group_order": 20,
      "actions": [
        {
          "action_key": "daily.maintain",
          "action_type": "dataset_action",
          "display_name": "维护股票日线",
          "description": "维护股票日线数据",
          "resource_key": "daily",
          "resource_display_name": "股票日线",
          "date_model": {
            "date_axis": "trade_open_day",
            "bucket_rule": "every_open_day",
            "window_mode": "point_or_range",
            "input_shape": "trade_date_or_start_end",
            "observed_field": "trade_date",
            "audit_applicable": true,
            "not_applicable_reason": null
          },
          "time_form": {
            "control": "trade_date_or_range",
            "default_mode": "point",
            "allowed_modes": ["point", "range"],
            "selection_rule": "trading_day_only",
            "point_label": "只处理一天",
            "range_label": "处理一个时间区间"
          },
          "filters": [],
          "search_keywords": ["daily", "股票日线", "日线"],
          "action_order": 100,
          "route_keys": ["daily.maintain"]
        }
      ]
    }
  ]
}
```

说明：

1. `route_keys` 只用于“从任务记录 / 自动任务配置返回手动页时”的上下文匹配。
2. 前端不得用 `route_keys` 自行决定执行路径；提交时仍必须调用 `POST /ops/manual-actions/{action_key}/task-runs`。
3. `route_keys` 只表达“哪些后端返回的 action/workflow key 可以回填到这个用户动作”，不表达执行路径。

### 4.2 按 action 发起 TaskRun

新增：

```text
POST /api/v1/ops/manual-actions/{action_key}/task-runs
```

请求体统一外壳：

```json
{
  "time_input": {},
  "filters": {}
}
```

规则：

1. `time_input` 只表达日期、月份或无日期输入。
2. `filters` 只表达对象筛选和附加参数，例如 `ts_code`、`exchange`、`con_code`。
3. 后端用 `action_key + time_input + filters` 创建 `TaskRunCreateContext`。
4. 返回 `TaskRunViewResponse`。
5. Dataset action 进入 `DatasetActionRequest -> DatasetExecutionPlan -> IngestionExecutor` 主链，不再降级为旧执行路径。

---

## 5. `date_model` 到表单的映射

手动维护页不再维护自己的日期规则。后端 API 必须从 `DatasetDefinition.date_model` 派生表单契约，前端只消费 API 返回值。

| `input_shape` | 控件 | `time_input` | 选择规则 |
|---|---|---|---|
| `trade_date_or_start_end` | 交易日单点或区间 | `trade_date` 或 `start_date/end_date` | 由 `bucket_rule` 决定普通交易日、周最后交易日、月最后交易日 |
| `ann_date_or_start_end` | 自然日单点或区间 | `ann_date` 或 `start_date/end_date` | 不强制交易日 |
| `month_or_range` | 月份单点或区间 | `month` 或 `start_month/end_month` | 自然月键 |
| `start_end_month_window` | 自然月窗口 | `start_month/end_month` | 后端展开为自然月窗口 |
| `none` | 无日期控件 | `mode=none` | 不展示日期输入 |

补充：

1. `ann_date_or_start_end` 当前用于 `dividend` / `stk_holdernumber`，前端展示为自然日区间。
2. 低频事件的自然日区间提交后，后端保留自然日 `start_date/end_date`，由 DatasetExecutionPlan 执行自然日 unit 规划。
3. `start_end_month_window` 当前用于 `index_weight`，前端提交 `start_month/end_month`，后端转换为自然月首日到末日的 `start_date/end_date`，再由 DatasetExecutionPlan 生成指数权重维护 unit。

`bucket_rule` 映射：

1. `every_open_day` -> `selection_rule=trading_day_only`
2. `week_last_open_day` -> `selection_rule=week_last_trading_day`
3. `month_last_open_day` -> `selection_rule=month_last_trading_day`
4. `every_natural_day` -> `selection_rule=calendar_day`
5. `every_natural_month` -> `selection_rule=month_key`
6. `month_window_has_data` -> `selection_rule=month_window`
7. `not_applicable` -> `selection_rule=none`

---

## 6. `time_input` 形态

### 6.1 交易日单点

```json
{
  "time_input": {
    "mode": "point",
    "trade_date": "2026-04-24"
  },
  "filters": {
    "ts_code": "000001.SZ"
  }
}
```

### 6.2 交易日区间

```json
{
  "time_input": {
    "mode": "range",
    "start_date": "2026-04-01",
    "end_date": "2026-04-24"
  },
  "filters": {
    "ts_code": "000001.SZ"
  }
}
```

### 6.3 自然日公告日期

```json
{
  "time_input": {
    "mode": "range",
    "start_date": "2026-04-01",
    "end_date": "2026-04-24",
    "date_field": "ann_date"
  },
  "filters": {
    "ts_code": "000001.SZ"
  }
}
```

### 6.4 月份键

```json
{
  "time_input": {
    "mode": "point",
    "month": "202604"
  },
  "filters": {}
}
```

### 6.5 月份区间或自然月窗口

```json
{
  "time_input": {
    "mode": "range",
    "start_month": "202604",
    "end_month": "202606"
  },
  "filters": {}
}
```

### 6.6 无日期

```json
{
  "time_input": {
    "mode": "none"
  },
  "filters": {
    "exchange": "SSE"
  }
}
```

---

## 7. 执行路径原则

现行手动维护路径已经切到 TaskRun + DatasetExecutionPlan：

要求：

1. `ManualActionTaskRunResolver` 只负责把 `time_input/filters` 规范化为 TaskRun 上下文。
2. Dataset action 不再输出旧执行规格字段，也不再进入旧 execution 创建链路。
3. `TaskRunDispatcher` 根据 `task_run.task_type=dataset_action` 创建 `DatasetActionRequest`。
4. `DatasetActionResolver` 只读取 `DatasetDefinition` 生成 `DatasetExecutionPlan`。
5. `IngestionExecutor` 只消费 plan units，不按旧入口名称分支。

示例：

| action | time input | 现行解析 |
|---|---|---|
| `daily.maintain` | `trade_date` | `DatasetActionRequest(mode=point)` |
| `daily.maintain` | `start_date/end_date` | `DatasetActionRequest(mode=range)` |
| `trade_cal.maintain` | `start_date/end_date` | `DatasetActionRequest(mode=range)` |
| `broker_recommend.maintain` | `month` | `DatasetActionRequest(mode=point, month=YYYYMM)` |
| `broker_recommend.maintain` | `start_month/end_month` | `DatasetActionRequest(mode=range, start_month/end_month)` |
| `stock_basic.maintain` | `none` | `DatasetActionRequest(mode=none)` |

---

## 8. 实施里程碑

### M0：方案文档 v2 定稿

交付：

1. 本文作为当前执行口径。
2. v1 标记为历史方案。
3. 主索引更新。

### M1：ManualAction 契约设计

交付：

1. `ManualActionGroup`
2. `ManualAction`
3. `ManualActionDateModel`
4. `ManualActionTimeForm`
5. `ManualActionFilterSpec`
6. `ManualActionExecutionCreateRequest`
7. `ManualActionTimeInput`

### M2：ManualAction Catalog API

交付：

1. `GET /api/v1/ops/manual-actions`
2. 从现有 spec 与 `DatasetDefinition.date_model` 构建 action 目录
3. API 测试

### M3：ManualAction Resolver 与创建 API

交付：

1. `POST /api/v1/ops/manual-actions/{action_key}/task-runs`
2. `ManualActionResolver`
3. resolver 测试和 Web API 测试

### M4：前端手动任务页切换

交付：

1. 手动任务页改用 `GET /ops/manual-actions`
2. 提交改用 `POST /ops/manual-actions/{action_key}/task-runs`
3. 页面移除底层 spec 分支字段
4. 日期控件按 `time_form` 渲染
5. 页测和 smoke 回归

### M5：收口与防回退

交付：

1. 手动页不再依赖 `/ops/catalog`
2. 旧文案和前端推导逻辑下线
3. 更新 API reference 与相关文档
4. 补必要防回退测试

---

## 9. 验证要求

后端至少执行：

```bash
pytest -q tests/web/test_ops_manual_actions_api.py
pytest -q tests/web/test_ops_task_run_api.py
```

前端至少执行：

```bash
cd frontend && npm run typecheck
cd frontend && npm run test
cd frontend && npm run build
cd frontend && PLAYWRIGHT_BROWSERS_PATH=.playwright npm run test:smoke
```

文档改动必须执行：

```bash
python3 scripts/check_docs_integrity.py
```

---

## 10. 风险控制

1. 不在前端复制 `date_model` 规则。
2. 不删除 `/ops/catalog`，自动任务仍需要 action/workflow 目录。
3. 自动任务页保存 schedule 的 `target_type/target_key` 调度目标，页面显示必须使用后端返回的结构化名称。
4. 不允许手动任务、任务记录或任务详情把旧执行路径作为用户主语。
