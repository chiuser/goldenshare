# 指数行情筛选池同步机制说明（index_series_active）

状态：当前筛选池行为说明；历史 `backfill_index_series` 入口已退场，当前执行入口应通过 `Dataset Maintain + DatasetExecutionPlan + TaskRun` 表达。

---

## 1. 目的

这份文档用于固化当前“指数日线/周线/月线按筛选池同步”的真实实现，避免后续维护时遗忘关键行为。

适用范围：
- `index_daily`
- `index_weekly`
- `index_monthly`
- `index_daily_basic`
- 历史回补流程 `backfill_index_series` 的有效规则映射

---

## 2. 筛选池数据表

筛选池表：`ops.index_series_active`

主键：
- `(resource, ts_code)`

关键字段：
- `resource`: 资源名（如 `index_daily`、`index_daily_basic`）
- `ts_code`: 指数代码
- `first_seen_date`: 首次观测到该代码的业务日期
- `last_seen_date`: 最近观测到该代码的业务日期
- `last_checked_at`: 最近检查时间

定义位置：
- 模型：[src/ops/models/ops/index_series_active.py](/Users/congming/github/goldenshare/src/ops/models/ops/index_series_active.py)
- DAO：[src/foundation/dao/index_series_active_dao.py](/Users/congming/github/goldenshare/src/foundation/dao/index_series_active_dao.py)
- 迁移：[alembic/versions/20260404_000028_add_index_series_active.py](/Users/congming/github/goldenshare/alembic/versions/20260404_000028_add_index_series_active.py)

---

## 3. 同步行为（当前实现）

## 3.1 `index_daily`

实现文件：
- `src/foundation/services/sync_v2/registry_parts/contracts/index_series.py`（历史路径，已删除）

行为：
1. 如果传了 `ts_code`，只同步该代码，成功后写回筛选池 `resource=index_daily`。
2. 如果未传 `ts_code`，先读 `list_active_codes("index_daily")`。
3. 若筛选池为空，回退到 `index_basic` 全量活跃指数列表。
4. 同步结束后，把本次看到的代码与日期 upsert 回筛选池。

结论：
- `index_daily` 是筛选池的主要生产者。

## 3.2 `index_weekly`

实现文件：
- `src/foundation/services/sync_v2/registry_parts/contracts/index_series.py`（历史路径，已删除）

行为：
1. 目标代码集合由 `_target_codes()` 决定。
2. `_target_codes()` 固定读取 `list_active_codes("index_daily")`。
3. 若池为空，则返回空集合，不回退 `index_basic`。
4. 接口返回后会按目标代码过滤，非目标代码不写 serving。

结论：
- `index_weekly` 依赖 `index_daily` 筛选池。
- 如果 `index_daily` 池为空，周线将基本没有可写入对象。

## 3.3 `index_monthly`

实现文件：
- `src/foundation/services/sync_v2/registry_parts/contracts/index_series.py`（历史路径，已删除）

行为：
1. 继承 `SyncIndexWeeklyService`。
2. 仅切换 `api_name/表名/period_kind`，目标代码选择逻辑不变。

结论：
- 月线与周线一致，依赖 `index_daily` 筛选池。

## 3.4 `index_daily_basic`

实现文件：
- `src/foundation/services/sync_v2/registry_parts/contracts/index_series.py`（历史路径，已删除）

行为：
1. 同步后会把观测到的代码 upsert 到 `resource=index_daily_basic` 的筛选池。
2. 与 `index_daily` 的池是分资源维护。

---

## 4. 历史回补行为（`backfill_index_series`）

实现文件：
- `src/ops/services/operations_history_backfill_service.py`（历史实现，已退场）

关键点（仅作历史规则映射参考）：
1. `resource in {"index_daily", "index_daily_basic"}` 时：
   - 先读取对应 resource 的筛选池代码。
   - `index_daily_basic` 在池为空时，会先尝试跑一次最近交易日增量做“发现”，再读池。
2. `resource in {"index_weekly", "index_monthly"}` 时：
   - 按周末/月末日期驱动增量调用。
   - 但写入对象仍由对应服务里的 `_target_codes()` 决定，即依赖 `index_daily` 池。

---

## 5. 运维侧可见现象与解释

1. 现象：周线/月线回补执行了，但写入很少或为 0。  
   原因：`index_daily` 筛选池为空或覆盖面太小。

2. 现象：`index_daily` 能跑全量，周线/月线却不全。  
   原因：日线有 `index_basic` 回退；周线/月线没有该回退逻辑。

3. 现象：`index_daily_basic` 初次回补能逐步恢复。  
   原因：池为空时有“最近交易日发现”兜底。

---

## 6. 建议的日常操作顺序

1. 先维护一次 `index_daily`（确保筛选池有代码）。
2. 再维护 `index_weekly`、`index_monthly`。
3. 如果做大范围历史回补，优先确认：
   - `ops.index_series_active` 中 `resource='index_daily'` 的代码数量是否符合预期。

---

## 7. 快速排查 SQL

```sql
-- 看各资源筛选池规模
select resource, count(*) as code_count
from ops.index_series_active
group by resource
order by resource;

-- 看 index_daily 筛选池最近观测日期
select min(last_seen_date) as min_seen, max(last_seen_date) as max_seen
from ops.index_series_active
where resource = 'index_daily';
```

---

## 8. 当前已知设计特点（非问题清单）

1. `index_daily` 与 `index_weekly/index_monthly` 的回退策略不一致（前者可回退到 `index_basic`，后者不可）。
2. 周/月线默认把 `index_daily` 视为代码池“上游来源”。
3. 该机制本质上是“先发现，再收敛”的索引池模式，适合控制同步范围，但需注意初始化顺序。
