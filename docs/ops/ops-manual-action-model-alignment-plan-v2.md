# 手动维护动作模型收敛方案 v2

更新时间：2026-04-24  
状态：当前执行口径  
适用范围：`src/ops/api/*`、`src/ops/queries/*`、`src/ops/schemas/*`、`src/ops/services/*`、`frontend/src/pages/ops-v21-task-manual-tab.tsx`

---

## 1. 一句话结论

手动维护任务只允许暴露“维护动作”给用户；日期语义必须从 `DatasetSyncContract.date_model` 派生；后端只新增 action 到现有 spec 的解析层，第一阶段不改变真实同步执行路径。

目标三层模型：

1. `ManualAction`：用户看到的“维护什么数据”
2. `DatasetSyncContract.date_model`：数据集日期语义的单一事实源
3. `ExecutionRoute`：后端内部把 action 解析到现有 `spec_type/spec_key/params_json`

---

## 2. 已确认口径

1. 用户不需要理解 `sync_daily / backfill_* / sync_history`。
2. 手动维护页不再把 `日常同步 / 按交易日回补 / 历史同步 / 所属类型` 作为主路径文案。
3. 前端不再持有 `syncDailySpecKey / backfillSpecKey / directSpecKey`。
4. `/api/v1/ops/catalog` 保留为系统级 spec catalog。
5. `/api/v1/ops/manual-actions` 是新增的手动维护专用用户动作 catalog，不替代 `catalog`。
6. 第一阶段 route resolver 只镜像现有真实执行路径，不改 `registry`、不改 `dispatcher`、不合并底层执行实现。
7. 日期输入、控件选择、单点/区间能力从 `date_model.window_mode/input_shape/date_axis/bucket_rule` 派生，不新增第二套日期规则表。

---

## 3. 当前 `/ops/catalog` 边界

`GET /api/v1/ops/catalog` 当前仍被以下运行时代码使用：

1. 手动任务页：构造当前过渡期手动维护对象。
2. 自动任务页：创建和编辑 schedule，仍需要系统级 `job/workflow spec`。
3. 任务记录页：提供 `spec_key` 筛选项。

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
          "action_key": "daily",
          "action_type": "job",
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
          "route_spec_keys": [
            "sync_daily.daily",
            "backfill_equity_series.daily",
            "sync_history.daily"
          ]
        }
      ]
    }
  ]
}
```

说明：

1. `route_spec_keys` 只用于“从任务记录 / 自动任务配置返回手动页时”的上下文匹配。
2. 前端不得用 `route_spec_keys` 自行决定执行路径；提交时仍必须调用 `POST /ops/manual-actions/{action_key}/executions`。
3. 真正的 `spec_type/spec_key/params_json` 解析只允许在后端 resolver 中完成。

### 4.2 按 action 发起 execution

新增：

```text
POST /api/v1/ops/manual-actions/{action_key}/executions
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
3. 后端用 `action_key + time_input + filters` 解析为现有 `spec_type/spec_key/params_json`，再复用现有 execution 创建链路。
4. 返回继续复用 `ExecutionDetailResponse`。
5. 第一阶段已落地的后端路由只做解析层，不修改 `registry` / `dispatcher` / 同步服务执行路径。

---

## 5. `date_model` 到表单的映射

手动维护页不再维护自己的日期规则。后端 API 必须从 `DatasetSyncContract.date_model` 派生表单契约，前端只消费 API 返回值。

| `input_shape` | 控件 | `time_input` | 选择规则 |
|---|---|---|---|
| `trade_date_or_start_end` | 交易日单点或区间 | `trade_date` 或 `start_date/end_date` | 由 `bucket_rule` 决定普通交易日、周最后交易日、月最后交易日 |
| `ann_date_or_start_end` | 自然日单点或区间 | `ann_date` 或 `start_date/end_date` | 不强制交易日 |
| `month_or_range` | 月份单点或区间 | `month` 或 `start_month/end_month` | 自然月键 |
| `start_end_month_window` | 自然月窗口 | `start_month/end_month` | 后端展开为自然月窗口 |
| `none` | 无日期控件 | `mode=none` | 不展示日期输入 |

补充：

1. `ann_date_or_start_end` 当前用于 `dividend` / `stk_holdernumber`，前端展示为自然日区间。
2. 低频事件的自然日区间提交后，后端解析到现有 `sync_history.<resource>` 路径，并传入 `start_date/end_date`。
3. `start_end_month_window` 当前用于 `index_weight`，前端提交 `start_month/end_month`，后端转换为自然月首日到末日的 `start_date/end_date`，再进入现有指数回补路径。

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

第一阶段新增 `ManualActionResolver`，但不改变真实执行路径。

要求：

1. `ManualActionResolver` 输出现有 `spec_type/spec_key/params_json`。
2. 输出结果必须继续进入现有 execution 创建链路。
3. 不改 `src/ops/runtime/dispatcher.py` 的 category 分发逻辑。
4. 不改 `src/ops/specs/registry.py` 的现有 spec 注册结构。
5. 不把单日请求强行统一改走区间 route，除非当前 action 现状已经只能通过区间 route 承接。

示例：

| action | time input | 第一阶段解析 |
|---|---|---|
| `daily` | `trade_date` | `sync_daily.daily` |
| `daily` | `start_date/end_date` | `backfill_equity_series.daily` |
| `trade_cal` | `start_date/end_date` | `backfill_trade_cal.trade_cal` |
| `broker_recommend` | `month` | `sync_daily.broker_recommend` |
| `broker_recommend` | `start_month/end_month` | `backfill_by_month.broker_recommend` |
| `stock_basic` | `none` | `sync_history.stock_basic` |

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
2. 从现有 spec 与 `DatasetSyncContract.date_model` 构建 action 目录
3. API 测试

### M3：ManualAction Resolver 与创建 API

交付：

1. `POST /api/v1/ops/manual-actions/{action_key}/executions`
2. `ManualActionResolver`
3. resolver 测试和 Web API 测试

### M4：前端手动任务页切换

交付：

1. 手动任务页改用 `GET /ops/manual-actions`
2. 提交改用 `POST /ops/manual-actions/{action_key}/executions`
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
pytest -q tests/web/test_ops_execution_api.py
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

1. 不把用户动作模型收敛和底层执行路径重构绑在一轮。
2. 不在前端复制 `date_model` 规则。
3. 不删除 `/ops/catalog`。
4. 不在第一阶段更改自动任务页的 spec-centric 模型。
5. 不在第一阶段重写 `dispatcher`。
