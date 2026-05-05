# 指数行情 active 池与周/月线派生机制说明

状态：当前实现说明
核验日期：2026-05-05
适用范围：`index_daily`、`index_weekly`、`index_monthly`、`ops.index_series_active`

---

## 1. 当前结论

当前指数日线、周线、月线已经收敛为一套明确机制：

1. `ops.index_series_active` 是指数行情维护对象池。
2. 当前业务口径使用 `resource='index_daily'` 作为指数日线、周线、月线共同的 `core_serving` 入库门禁。
3. active 池不是 TaskRun 观测表，不允许随任务观测表清空。
4. 当前 ingestion 主链不会用 active 池裁剪源站请求结果或 raw 写入。
5. raw 层对齐 Tushare 源站事实；`core_serving` 层只写 active 池命中的指数代码。
6. 显式 `ts_code` 只是源站请求参数，不是写入 `core_serving` 的特权；非 active 代码只能写 raw，不能写穿 `core_serving`。
7. 周线、月线的派生发生在同步 `index_weekly`、`index_monthly` 时，不发生在同步 `index_daily` 时。
8. 周线、月线最终 serving 表通过 `source` 字段区分来源：
   - `api`：来自 Tushare 周线/月线接口。
   - `derived_daily`：由指数日线派生补齐。

当前远程生产库核验结果：

| 项目 | 当前值 |
| --- | ---: |
| `ops.index_series_active resource='index_daily'` | 1130 个代码 |
| active 池来源 | 基于 2026-04-15 指数日线 code 集合审阅后写入 |
| 周线/月线展示来源 | TaskRun view 按最终 serving 表只读统计 |

---

## 2. 表与代码位置

active 池表：`ops.index_series_active`

主键：

- `(resource, ts_code)`

关键字段：

- `resource`：对象池资源名。当前指数行情统一使用 `index_daily`。
- `ts_code`：指数代码。
- `first_seen_date`：首次纳入或观测日期。
- `last_seen_date`：最近纳入或观测日期。
- `last_checked_at`：最近检查时间。

定义位置：

- 模型：[src/ops/models/ops/index_series_active.py](/Users/congming/github/goldenshare/src/ops/models/ops/index_series_active.py)
- DAO：[src/foundation/dao/index_series_active_dao.py](/Users/congming/github/goldenshare/src/foundation/dao/index_series_active_dao.py)
- 迁移：[alembic/versions/20260404_000028_add_index_series_active.py](/Users/congming/github/goldenshare/alembic/versions/20260404_000028_add_index_series_active.py)

---

## 3. 执行口径

### 3.1 `index_daily`

当前行为：

1. 默认维护不按 active 池拆 `ts_code` 请求；请求参数只带 `trade_date` 或 `start_date/end_date`。
2. 如果用户显式传入 `ts_code`，它只限定源站请求范围。
3. raw 表写入源站返回的完整行。
4. `core_serving.index_daily_serving` 写入前必须经过 active 池过滤，只保留 `resource='index_daily'` 命中的代码。
5. 显式传入非 active `ts_code` 时，raw 可以写入，`core_serving` 不得写入。
6. 日线任务只写日线相关表，不派生周线或月线。
7. 当前主链不会因为日线同步成功而自动更新 `ops.index_series_active`。

说明：

- active 池当前是运维审阅后的 serving 门禁集合，不是日线同步过程中的自动产物。
- 如果要调整 active 池，应走单独的指数对象池审阅/重建流程，不应依赖“跑一次日线任务”隐式改变对象池。

### 3.2 `index_weekly`

当前行为：

1. 周线任务按周锚点执行。
2. raw 表写入 Tushare 周线接口返回的完整行，不按 active 池过滤。
3. `core_serving.index_weekly_serving` 写入前读取 `resource='index_daily'` active 池作为门禁。
4. active 池命中的 API 行写入 serving，来源标记为 `source='api'`。
5. 对 active 池中接口未返回的代码，使用已存在的 `core_serving.index_daily_serving` 日线数据派生补齐，来源标记为 `source='derived_daily'`。
6. 显式传入非 active `ts_code` 时，raw 可以写入，serving 不得写入，也不得触发日线派生写入 serving。
7. 派生补齐发生在周线任务内。

### 3.3 `index_monthly`

当前行为：

1. 月线任务按月锚点执行。
2. 写入逻辑与周线一致，只是目标表和周期粒度不同。
3. raw 表写入 Tushare 月线接口返回的完整行，不按 active 池过滤。
4. `core_serving.index_monthly_serving` 写入前读取 `resource='index_daily'` active 池作为门禁。
5. active 池命中的 API 行写入 serving，来源标记为 `source='api'`。
6. 对 active 池中接口未返回的代码，使用已存在的 `core_serving.index_daily_serving` 日线数据派生补齐，来源标记为 `source='derived_daily'`。
7. 显式传入非 active `ts_code` 时，raw 可以写入，serving 不得写入，也不得触发日线派生写入 serving。
8. 派生补齐发生在月线任务内。

---

## 4. 重跑顺序

指数行情大范围重跑时，推荐顺序固定为：

```text
1. index_daily
2. index_weekly
3. index_monthly
```

原因：

1. 周线/月线派生依赖日线 serving 表。
2. 如果日线未先完成，周线/月线即使进入派生逻辑，也没有足够的基础数据。
3. 周线/月线任务会在自己的写入阶段完成接口数据与日线派生结果的合并。

---

## 5. 周线/月线来源展示

任务详情页通过 TaskRun view API 展示周线/月线来源统计。

后端口径：

1. 只在任务资源为 `index_weekly` 或 `index_monthly` 时返回 `progress.period_source_summary`。
2. 统计数据来自最终 serving 表：
   - `core_serving.index_weekly_serving`
   - `core_serving.index_monthly_serving`
3. 统计维度为任务处理范围内的 `source` 字段。
4. 这是只读观测，不参与 writer、executor 或业务事务。

返回字段：

```json
{
  "period_source_summary": {
    "total_rows": 1130,
    "api_rows": 560,
    "derived_daily_rows": 570,
    "other_rows": 0,
    "start_date": "2026-04-17",
    "end_date": "2026-04-17"
  }
}
```

前端展示：

- `API 返回`
- `日线派生`
- `其他来源`
- 覆盖日期范围

---

## 6. 快速核验 SQL

### 6.1 active 池规模

```sql
select resource, count(*) as code_count, min(first_seen_date), max(last_seen_date)
from ops.index_series_active
where resource = 'index_daily'
group by resource;
```

### 6.2 周线/月线来源构成

```sql
select source, count(*) as rows
from core_serving.index_weekly_serving
where trade_date between date '2026-04-01' and date '2026-04-30'
group by source
order by source;

select source, count(*) as rows
from core_serving.index_monthly_serving
where trade_date between date '2026-04-01' and date '2026-04-30'
group by source
order by source;
```

### 6.3 日/周/月 code 集合一致性

```sql
with
d as (select distinct ts_code from core_serving.index_daily_serving where trade_date between date '2025-01-01' and date '2026-04-30'),
w as (select distinct ts_code from core_serving.index_weekly_serving where trade_date between date '2025-01-01' and date '2026-04-30'),
m as (select distinct ts_code from core_serving.index_monthly_serving where trade_date between date '2025-01-01' and date '2026-04-30')
select 'daily_only_vs_weekly' as diff, count(*) from (select ts_code from d except select ts_code from w) x
union all select 'weekly_only_vs_daily', count(*) from (select ts_code from w except select ts_code from d) x
union all select 'daily_only_vs_monthly', count(*) from (select ts_code from d except select ts_code from m) x
union all select 'monthly_only_vs_daily', count(*) from (select ts_code from m except select ts_code from d) x;
```

---

## 7. 必守边界

1. 不允许把 `ops.index_series_active` 当作 TaskRun、freshness、snapshot 这类可随时清空重建的观测表。
2. 不允许在前端或 Ops 层重新实现周线/月线派生规则。
3. 不允许在同步日线时顺手派生周线/月线。
4. 不允许让 TaskRun 观测统计影响业务表写入或事务提交。
5. 不允许把 active 池门禁前移到源站请求或 raw 写入前；active 池只能约束 `core_serving` 入库。
6. 如果要调整 active 池来源，必须同步更新：
   - 本文档。
   - DatasetDefinition / planning 相关说明。
   - 对应 planner/writer 测试。
   - TaskRun view 来源展示测试。
