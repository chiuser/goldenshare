# 手动维护动作模型收敛方案 v1

更新时间：2026-04-24  
适用范围：`src/ops/specs/*`、`src/ops/queries/*`、`src/ops/api/*`、`frontend/src/pages/ops-v21-task-manual-tab.tsx`

---

## 1. 目的

本方案用于收敛“手动维护任务”这一条链路的产品模型、API 模型和前端交互模型。

本文解决的问题：

1. 当前手动维护页把“维护什么数据”和“底层怎么执行”混在了一起
2. 当前前端使用 `syncDailySpecKey / backfillSpecKey / directSpecKey` 维护底层执行分支，用户心智无法理解
3. 当前“数据分组”“所属类型”“按交易日回补 / 日常同步”等词，暴露了系统内部实现，而不是用户任务语言
4. 当前分组逻辑是前端硬编码，后续新增资源时容易继续漂移

本文不解决：

1. 不重写底层 `sync_service / history_backfill_service / maintenance` 的执行实现
2. 不合并现有全部 job spec 到单一 runtime handler
3. 不在本方案阶段直接改动任务中心其他页面

---

## 2. 已确认的产品判断

以下判断已明确，后续方案以此为准：

1. 用户只关心“要维护什么对象”和“处理一天还是一段时间”，不关心底层是 `日常同步` 还是 `回补`
2. `按交易日回补 / 日常同步 / 历史同步` 这类术语不应在手动维护主路径里作为主要文案出现
3. 手动维护页第一步应该表达“维护什么”，而不是“系统内部会跑哪条 spec”
4. 第二步才表达“怎么处理”，例如：
   - 只处理一天
   - 处理一个时间区间
   - 只处理一个月
   - 处理一个月份区间
5. 前端不应继续承担底层 spec 选择逻辑
6. 后端应提供面向“手动维护动作”的正式契约，而不是让前端从通用 catalog 中自行推导

---

## 3. 当前实现现状

### 3.1 当前前端实际模型

当前手动维护页的真实做法：

1. 先调用 `GET /api/v1/ops/catalog`
2. 从 `job_specs + workflow_specs` 中自行合并出 `manualActions`
3. 每个 `manualAction` 内部同时保留：
   - `syncDailySpecKey`
   - `backfillSpecKey`
   - `backfillNoDateSpecKey`
   - `directSpecKey`
   - `workflowKey`
4. 用户提交时，前端根据时间输入形态，自己挑一个底层 spec 去创建 execution

关键代码依据：

1. 前端合并动作：[frontend/src/pages/ops-v21-task-manual-tab.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-task-manual-tab.tsx)
2. 前端选择执行目标：[frontend/src/pages/ops-v21-task-manual-tab.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-task-manual-tab.tsx)
3. 时间能力推导：[frontend/src/shared/ops-time-capability.ts](/Users/congming/github/goldenshare/frontend/src/shared/ops-time-capability.ts)

### 3.2 当前后端实际模型

当前后端是按 job spec 的执行策略分类建模的，而不是按“手动维护动作”建模。

典型 category 包括：

1. `sync_history`
2. `sync_daily`
3. `backfill_trade_cal`
4. `backfill_equity_series`
5. `backfill_by_trade_date`
6. `backfill_by_date_range`
7. `backfill_low_frequency`
8. `backfill_fund_series`
9. `backfill_index_series`
10. `backfill_by_month`
11. `maintenance`

关键代码依据：

1. job spec 定义：[src/ops/specs/job_spec.py](/Users/congming/github/goldenshare/src/ops/specs/job_spec.py)
2. registry 注册：[src/ops/specs/registry.py](/Users/congming/github/goldenshare/src/ops/specs/registry.py)
3. dispatcher 分发：[src/ops/runtime/dispatcher.py](/Users/congming/github/goldenshare/src/ops/runtime/dispatcher.py)

### 3.3 当前 catalog 的边界

当前 `GET /api/v1/ops/catalog` 返回的是系统级 spec 目录，不是“手动维护页专用目录”。

返回字段包括：

1. `key`
2. `display_name`
3. `resource_key`
4. `resource_display_name`
5. `category`
6. `description`
7. `strategy_type`
8. `executor_kind`
9. `supported_params`

它没有返回：

1. `manual_group_key`
2. `manual_group_label`
3. `manual_action_key`
4. `manual_time_modes`
5. `单日/区间/月份` 这种用户任务语义

关键代码依据：

1. catalog query service：[src/ops/queries/catalog_query_service.py](/Users/congming/github/goldenshare/src/ops/queries/catalog_query_service.py)
2. catalog schema：[src/ops/schemas/catalog.py](/Users/congming/github/goldenshare/src/ops/schemas/catalog.py)

---

## 4. 当前方案的核心问题

### 4.1 把“对象选择”和“执行方式”混在一起

当前页面第一步实际上同时暴露了两类信息：

1. 维护对象：例如 `股票日线`、`分红送转`
2. 内部执行方式：例如 `按交易日回补`、`日常同步`

这会直接制造困惑：

1. 用户先选对象时，不应该被迫理解系统内部 category
2. 第二步已经在选时间范围，第一步再暴露 `回补 / 日常同步` 会产生重复和冲突

### 4.2 前端承担了不该承担的 spec 选择逻辑

当前前端不是“发起一个维护动作”，而是在做：

1. 根据时间模式判断是 point 还是 range
2. 判断该走 `syncDailySpecKey` 还是 `backfillSpecKey`
3. 若没有再退到 `directSpecKey`

这使得页面层绑定了后端内部策略结构，后续很难演进。

### 4.3 当前 3 个执行能力是系统实现细节，不是用户概念

当前前端里这 3 个键：

1. `syncDailySpecKey`
2. `backfillSpecKey`
3. `directSpecKey`

本质上只是对现有后端 spec 体系的适配，不是用户需要知道的概念。

### 4.4 分组维度不稳定

当前“数据分组”来自前端的 `inferActionDomain`，它混杂了：

1. 数据对象：股票 / 指数 / 板块
2. 数据性质：基础主数据 / 低频事件 / 榜单
3. 执行形态：工作流 / 维护动作

这是另一个结构性问题，但它和“执行能力暴露”本质上属于同一类：当前页面没有一个正式的“手动维护动作模型”。

---

## 5. 目标模型

### 5.1 用户模型：只有一个“维护动作”

目标态下，对前端和用户来说，每个对象只应有一个统一的 `manual_action`。

例如：

1. `维护股票日线`
2. `维护交易日历`
3. `维护分红送转`
4. `维护指数周线`

用户只需要知道：

1. 要维护什么
2. 可怎么处理
3. 需要填什么参数

用户不需要知道：

1. 对应的是 `sync_daily.*`
2. 还是 `backfill_*.*`
3. 还是 `sync_history.*`

### 5.2 系统模型：执行路由仍可保留多条

目标态下，底层后端仍可保留多条执行 route，只是这些 route 不再直接暴露给前端页面。

例如对同一个 `manual_action = equity_daily`：

1. 单日 -> `sync_daily.daily`
2. 区间 -> `backfill_equity_series.daily`

再例如对 `manual_action = trade_cal`：

1. 单日 -> `backfill_trade_cal.trade_cal`，并自动转成 `start_date = end_date`
2. 区间 -> `backfill_trade_cal.trade_cal`

也就是说：

1. 前端只有一个 action
2. 后端根据时间模式和参数自动 resolve 到真正 spec

### 5.3 统一原则

后续方案统一按以下原则设计：

1. 用户模型按“维护动作”建模
2. 后端模型按“执行路由”建模
3. 前端不再直接持有 `spec_key` 分支逻辑
4. action 与 route 的映射由后端维护

---

## 6. 目标 API 设计

## 6.1 新增：手动维护动作目录接口

建议新增：

- `GET /api/v1/ops/manual-actions`

用途：

1. 专门服务“手动维护页”
2. 不再让前端从通用 catalog 中自行推导动作模型

建议返回结构：

```json
{
  "groups": [
    {
      "group_key": "equity_market",
      "group_label": "股票行情",
      "group_order": 20,
      "actions": [
        {
          "action_key": "equity_daily",
          "display_name": "维护股票日线",
          "description": "维护股票日线数据",
          "resource_key": "daily",
          "resource_display_name": "股票日线",
          "supported_time_modes": ["single_day", "date_range"],
          "default_time_mode": "single_day",
          "time_granularity": "day",
          "param_specs": [],
          "search_keywords": ["daily", "股票日线", "日线"]
        }
      ]
    }
  ]
}
```

### 6.2 新增：按 action 发起执行

建议新增：

- `POST /api/v1/ops/manual-actions/{action_key}/executions`

请求体建议：

```json
{
  "time_mode": "single_day",
  "trade_date": "2026-04-24",
  "params_json": {
    "ts_code": "000001.SZ"
  }
}
```

或：

```json
{
  "time_mode": "date_range",
  "start_date": "2026-04-01",
  "end_date": "2026-04-24",
  "params_json": {}
}
```

返回：

- 仍然复用现有 `ExecutionDetailResponse`

### 6.3 当前 catalog 的定位

目标态下：

- `GET /api/v1/ops/catalog`

继续保留为系统 catalog，用于：

1. 调度配置
2. 工作流目录
3. 系统级 spec 审计
4. 管理页或高级页

但不再作为手动维护页的主数据来源。

---

## 7. 手动维护动作目录的字段设计

### 7.1 Group 级字段

建议字段：

1. `group_key`
2. `group_label`
3. `group_order`

建议默认分组：

1. `reference_data` -> `基础资料`
2. `equity_market` -> `股票行情`
3. `index_fund` -> `指数 / ETF`
4. `board_theme` -> `板块 / 题材`
5. `moneyflow` -> `资金流向`
6. `event_stats` -> `事件 / 统计`
7. `workflow` -> `工作流`
8. `system_maintenance` -> `系统维护`（默认可隐藏）

说明：

1. 分组只表达“维护对象是什么”
2. 不再混入 `回补 / 同步 / 工作流 category` 这类执行方式概念

### 7.2 Action 级字段

建议字段：

1. `action_key`
2. `display_name`
3. `description`
4. `resource_key`
5. `resource_display_name`
6. `supported_time_modes`
7. `default_time_mode`
8. `time_granularity`
9. `param_specs`
10. `search_keywords`
11. `action_order`

### 7.3 时间模式枚举

建议固定成用户语言，而不是 spec category 语言：

1. `none`
2. `single_day`
3. `date_range`
4. `single_month`
5. `month_range`

说明：

1. 用户看到的是“处理一天 / 处理一个时间区间 / 处理一个月 / 处理月份区间”
2. 不再看到 `回补 / 日常同步`

---

## 8. 后端路由解析规则

### 8.1 引入 ExecutionRoute 概念

建议在后端内部新增 `ExecutionRoute` 概念，用于表达：

1. 某个 action 在某种时间模式下应该落到哪条底层 spec
2. 参数如何归一化

建议结构：

```python
ExecutionRoute(
    spec_type="job",
    spec_key="sync_daily.daily",
    param_transform="single_day_trade_date"
)
```

### 8.2 路由解析优先级

建议按以下规则解析：

1. `single_day`
   - 若存在单日增量 route，优先走它
   - 否则若存在 `date_range` route，则转成 `start_date = end_date`
2. `date_range`
   - 走区间 route
3. `single_month`
   - 若存在单月 route，则走单月 route
   - 否则若存在 `month_range` route，则转成 `start_month = end_month`
4. `month_range`
   - 走月份区间 route
5. `none`
   - 走 direct / full / maintenance route

### 8.3 示例

#### `equity_daily`

```text
single_day  -> sync_daily.daily
date_range  -> backfill_equity_series.daily
```

#### `trade_cal`

```text
single_day  -> backfill_trade_cal.trade_cal (start_date=end_date)
date_range  -> backfill_trade_cal.trade_cal
```

#### `broker_recommend`

```text
single_month -> backfill_by_month.broker_recommend (start_month=end_month)
month_range  -> backfill_by_month.broker_recommend
```

#### `stock_basic`

```text
none -> sync_history.stock_basic
```

### 8.4 重要判断

这意味着：

1. 不是每个 action 都必须真的有单独 `syncDailySpecKey`
2. 有些 action 完全可以用“区间 route + start=end”承接单日处理
3. 这正是用户视角更合理的地方：用户只选“处理一天”，系统自己决定是不是复用区间 route

---

## 9. 前端页面目标结构

### 9.1 第一步：选择维护对象

不再展示：

1. `日常同步`
2. `按交易日回补`
3. `历史同步`
4. `所属类型`

只展示：

1. 维护对象分类
2. 维护对象列表
3. 最近使用

示例：

```text
维护对象分类：股票行情
维护对象：股票日线
```

### 9.2 第二步：选择处理方式

这里才展示用户理解得懂的方式：

1. 只处理一天
2. 处理一个时间区间
3. 只处理一个月
4. 处理一个月份区间

必要时可显示：

- `支持处理方式：单日、日期区间`

但不再显示：

- `所属类型：按交易日回补`

### 9.3 第三步：附加筛选条件

继续沿用现有 param 表单，但由新 `manual_action` 的 `param_specs` 驱动。

---

## 10. 现有前端字段的收敛建议

### 10.1 应从前端删除的内部字段

在目标态里，以下字段不应继续存在于手动维护页页面模型：

1. `syncDailySpecKey`
2. `backfillSpecKey`
3. `backfillNoDateSpecKey`
4. `directSpecKey`
5. `workflowKey` 直接暴露到页面控制路径

这些字段未来应只留在后端 `ManualActionResolver` 或 route registry 内部。

### 10.2 前端应保留的模型

前端应保留：

1. `action_key`
2. `display_name`
3. `group`
4. `supported_time_modes`
5. `time_granularity`
6. `param_specs`

也就是说，前端页面从“spec 选择器”收敛成“manual_action 表单”。

---

## 11. 实施阶段建议

### Phase A：契约设计

目标：

1. 定稿 `manual_actions` 的 API 契约
2. 定稿 `POST /manual-actions/{action_key}/executions` 的请求模型
3. 定稿分组口径和 `time_mode` 枚举

本阶段不改前端页面。

### Phase B：后端能力补齐

目标：

1. 新增 `ManualActionCatalogQueryService`
2. 新增 `ManualActionResolver`
3. 新增 action-based execution API
4. 补后端单元测试和 Web API 测试

本阶段不删除现有 `/ops/catalog`。

### Phase C：前端切换

目标：

1. 手动维护页改用 `GET /ops/manual-actions`
2. 提交改为 `POST /ops/manual-actions/{action_key}/executions`
3. 去掉页面里的 `specKey` 分支逻辑
4. 去掉“所属类型”“日常同步/回补”等主文案

### Phase D：收口

目标：

1. 页面层删除 `syncDailySpecKey / backfillSpecKey / directSpecKey`
2. 旧的前端推导逻辑下线
3. 补充文档、回归和 smoke

---

## 12. 测试与回归要求

### 12.1 后端

至少补：

1. `manual_actions` catalog 构建测试
2. `action_key + time_mode -> spec route` 解析测试
3. `single_day -> range route with start=end` 这类回退逻辑测试
4. Web API 创建 execution 的契约测试

### 12.2 前端

至少补：

1. 手动维护页对象选择与分组展示测试
2. `time_mode` 切换测试
3. action 提交 payload 测试
4. smoke / visual gate 中手动维护页主路径回归

---

## 13. 风险与注意事项

### 13.1 不要误解成“底层只能有一个 job spec”

本方案不是要把底层执行实现硬合并成一个 spec。

本方案的重点是：

1. 对前端和用户来说只保留一个 action
2. 底层 route 仍可多条
3. 但 route 选择下沉到后端

### 13.2 `sync_history` 资源要区分“无时间”与“可合成单日”

不是所有动作都应该支持 `single_day`。

例如：

1. `stock_basic` 更适合 `none`
2. `trade_cal` 适合 `single_day + date_range`

所以每个 action 的 `supported_time_modes` 必须显式定义，不能靠前端猜。

### 13.3 分组口径不要再放在前端硬编码

当前前端 `inferActionDomain` 只适合作为过渡期逻辑。  
目标态分组必须由后端统一输出，避免新增资源时继续分叉。

---

## 14. 结论

当前建议的统一方向是：

1. 用户模型从“spec 选择”收敛成“manual action 选择”
2. 前端不再感知 `syncDailySpecKey / backfillSpecKey / directSpecKey`
3. 用户只选择：
   - 维护什么
   - 怎么处理
   - 还要带哪些筛选条件
4. 后端负责把 `action_key + time_mode + params` 解析到真正的执行 spec
5. `GET /ops/catalog` 保持系统 catalog 角色，手动维护页改用新的 `manual_actions` 契约

这个方向能同时解决：

1. 页面文案难懂
2. 前端页面承担 spec 路由逻辑
3. 分组口径漂移
4. 用户无法理解“为什么会有日常同步/回补”这类问题
