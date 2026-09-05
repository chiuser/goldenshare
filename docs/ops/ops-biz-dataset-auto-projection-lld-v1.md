# Ops Biz 数据集自动投影与 14 表展示 LLD v1

状态：代码已实现，待部署验收
日期：2026-09-05
依据方案：[Ops Biz 数据集自动投影与 14 表展示技术方案 v1](/Users/congming/github/goldenshare/docs/ops/ops-biz-dataset-auto-projection-plan-v1.md)
开发模板：[Biz 数据集开发说明模板](/Users/congming/github/goldenshare/docs/templates/biz-dataset-development-template.md)
适用范围：`src/ops/catalog/**`、`src/ops/queries/**`、数据卡片 API 契约、Biz 数据源页面与对应测试

## 0. 决策状态

没有新增需要拍板的业务问题。

以下口径已由技术方案和当前代码共同确定，本 LLD 不再引入新的产品概念：

1. 原有成交额分钟快照保留，并从“财势乾坤”移入“数据集市”。
2. 新增 14 张业务表卡片，最终共 15 张卡片。
3. 11 张已有维护动作的表复用当前 `maintenance_action`，开放正确的手动入口并展示自动任务状态。
4. 新增的板块层级、股票神奇九转、指数神奇九转 3 张 Dagster 生产表保持只读；原有成交额分钟快照也保持只读。
5. 不修改或刷新任何业务数据、TaskRun、schedule、snapshot，不新增数据库迁移。
6. 页面只消费卡片 API 返回的分组、状态和动作事实，不自行推断。

## 1. 开发目标与边界

### 1.1 目标

本轮将当前单表手写实现替换为明确的 Biz 数据集定义和自动投影链：

```text
BizDatasetDefinition
  -> BizTableCardQueryService 读取真实业务表与现有 Ops 状态
  -> DatasetCardListResponse
  -> GET /api/v1/ops/dataset-cards?source_key=biz_tableset
  -> OpsV21SourcePage
```

新增一个合法定义后，只需实现或复用已登记的观测查询，卡片即可自动进入 API 和页面。不得再为单个 Biz 表分别修改 API 路由和页面常量。

### 1.2 硬边界

计划内：

- Biz 定义、校验器和卡片查询。
- `DatasetCardItem.primary_action_type` 前后端契约。
- Biz 页面顺序、操作入口和自动任务文案。
- 后端、前端及架构测试。
- 方案、LLD、API 参考文档和索引。

计划外：

- `DatasetDefinition`、ingestion、resolver、planner、request builder、writer、DAO。
- 15 张业务表、物化视图及发布批次表的结构和数据。
- 现有 maintenance action 的参数、执行器和生产逻辑。
- Dagster asset、job、sensor 或运行状态接入 Ops。
- 新 API、新状态表、Alembic 迁移、snapshot 刷新或历史数据回填。

## 2. 开发前代码审计

### 2.1 已读取规则

本 LLD 已按以下规则核验：

| 文件 | 使用到的约束 |
| --- | --- |
| `AGENTS.md` | 共享契约修改前做全量消费者审计；Ops 状态不得影响业务事务；不增加临时兼容；开发前明确目标、依据、范围和影响面 |
| `src/AGENTS.md` | `ops` 可以依赖 `foundation`，`foundation` 不得反向依赖 `ops` |
| `src/ops/AGENTS.md` | TaskRun、schedule 和卡片属于当前 Ops 主线，不恢复旧 execution 模型 |
| `src/ops/catalog/AGENTS.md` | 展示目录必须有单一事实来源，不允许前端复制目录事实 |
| `frontend/AGENTS.md` | 页面只消费后端契约，不自行拼装业务事实 |
| `docs/AGENTS.md`、`docs/ops/AGENTS.md` | 新文档同步主索引；当前任务模型使用 TaskRun 和 `target_type/target_key` |

### 2.2 CodeGraph 影响面

已使用 CodeGraph 核验以下入口、调用链和消费者：

```text
DatasetCardQueryService.list_cards
BizTableCardQueryService.list_cards
DatasetCardItem / DatasetCardListResponse
GET /ops/dataset-cards
OpsV21SourcePage
buildManualTaskHref / matchesActionKey
MaintenanceActionDefinition
ManualActionQueryService
ScheduleAutomationCapabilityResolver
TaskRunCommandService.create_from_schedule_target
OpsSchedule / TaskRun
OpsFreshnessQueryService runtime metadata helpers
后端数据卡测试与前端 source page 测试
```

结论：影响面只在 `ops -> foundation model` 的允许方向和现有前端卡片消费者内，不改变子系统依赖矩阵。

### 2.3 当前 Biz 卡片链路

| 位置 | 当前事实 | 本轮处理 |
| --- | --- | --- |
| `src/ops/catalog/biz_table_catalog.py` | `BIZ_TABLE_CATALOG` 只有成交额分钟快照；模型仍叫 TableCatalog | 删除该文件，改为 `biz_dataset_definitions.py`，不保留兼容导出 |
| `src/ops/queries/dataset_card_query_service.py` | `source_key=biz_tableset` 时直接委托 Biz 查询服务 | 保留分流，只改新定义常量的 import |
| `src/ops/queries/biz_table_card_query_service.py` | 只支持 `wealth_turnover_snapshot`；动作、任务和 schedule 全部写死为空 | 改为定义驱动的通用查询与投影 |
| `src/ops/schemas/dataset_card.py` | 只有 `primary_action_key` | 增加 `primary_action_type` |
| `frontend/src/pages/ops-v21-source-page.tsx` | Biz 卡片一律显示“只读展示”；链接固定使用 `dataset_action`；同组按中文名重新排序 | 按 API 契约显示动作和自动任务，保留服务端顺序 |
| `frontend/src/pages/ops-v21-biz-table-page.tsx` | 页面说明写死“暂不提供写入和调度入口” | 改为业务数据集状态与维护入口说明 |

### 2.4 维护动作与任务身份

当前 11 张可维护业务表已经有正式生产入口，不需要新动作：

| action key | 目标业务表 | 手动 | 自动 |
| --- | --- | --- | --- |
| `maintenance.rebuild_dm` | `dm.equity_daily_snapshot` | 是 | 是 |
| `maintenance.materialize_wealth_sector_heat_daily` | `core_serving.wealth_sector_heat_daily` | 是 | 是 |
| `maintenance.materialize_wealth_sector_analysis_daily` | 8 张板块分析事实表及 1 张发布控制表 | 是 | 是 |
| `maintenance.materialize_news_stock_links` | `core_serving.news_stock_link` | 是 | 是 |

现有身份传导如下：

```text
MaintenanceActionDefinition.key
  -> 手动/自动任务 target_type=maintenance_action, target_key=<action key>
  -> TaskRun.task_type=maintenance_action
  -> TaskRun.request_payload_json.target_key=<action key>
```

`TaskRun.resource_key` 对 maintenance action 为 `NULL`，因此 Biz 卡片不能按 `resource_key` 查维护任务，必须按 `task_type + request_payload_json.target_key` 查。自动任务直接按 `OpsSchedule.target_type + target_key` 查，现有复合索引已经覆盖。

### 2.5 前端跳转链路

`buildManualTaskHref()` 已支持 `action_type` 和 `action_key`，手动任务页也会同时匹配二者。当前缺陷只在卡片没有返回 action type，并且页面固定传 `dataset_action`。

因此本轮不新增路由：

```text
/app/ops/v21/datasets/tasks
  ?tab=manual
  &action_type=maintenance_action
  &action_key=maintenance.materialize_wealth_sector_heat_daily
```

## 3. Biz 数据集定义

### 3.1 文件与类型

新增：

```text
src/ops/catalog/biz_dataset_definitions.py
```

删除：

```text
src/ops/catalog/biz_table_catalog.py
```

不保留旧类、旧常量或兼容 import。

```python
from dataclasses import dataclass
from typing import Literal

BizProducerType = Literal["maintenance_action", "dagster_asset"]
BizObservationQueryKey = Literal[
    "direct_trade_date",
    "static_snapshot",
    "maintenance_task_trace",
    "sector_analysis_published_batch",
    "wealth_turnover_ready_snapshot",
]
BizFreshnessPolicyKey = Literal[
    "latest_completed_trade_day",
    "published_batch_trade_day",
    "static_snapshot_ready",
    "maintenance_task_trace",
    "wealth_turnover_snapshot",
]

@dataclass(frozen=True, slots=True)
class BizDatasetDefinition:
    dataset_key: str
    display_name: str
    description: str
    table_name: str
    group_key: str
    group_label: str
    group_order: int
    item_order: int
    observation_query_key: BizObservationQueryKey
    freshness_policy_key: BizFreshnessPolicyKey
    business_date_column: str | None
    observed_at_column: str | None
    ready_after_local_time: str | None
    producer_type: BizProducerType
    producer_key: str
```

公开函数：

```python
list_biz_dataset_definitions() -> tuple[BizDatasetDefinition, ...]
get_biz_dataset_definition(dataset_key: str) -> BizDatasetDefinition
lint_biz_dataset_definitions() -> tuple[BizDatasetLintIssue, ...]
```

### 3.2 注册清单

| 顺序 | dataset key | 显示名 | group | query / policy | 日期列 / 时间列 | 判迟时间 | producer |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 10/10 | `wealth_market_turnover_snapshot` | 成交额分钟快照 | `data_mart / 数据集市` | `wealth_turnover_ready_snapshot / wealth_turnover_snapshot` | `trade_date / built_at` | `20:00` | Dagster `prod_core_wealth_market_turnover` |
| 10/20 | `equity_daily_snapshot` | 股票日线数据集市快照 | `data_mart / 数据集市` | `maintenance_task_trace / maintenance_task_trace` | `None / None` | `None` | `maintenance.rebuild_dm` |
| 20/10 | `wealth_sector_hierarchy` | 板块层级 | `sector_analysis / 板块分析` | `static_snapshot / static_snapshot_ready` | `code_reference_trade_date / published_at` | `None` | Dagster `prod_core_wealth_sector_hierarchy` |
| 20/20 | `wealth_sector_heat_daily` | 每日板块热度 | `sector_analysis / 板块分析` | `direct_trade_date / latest_completed_trade_day` | `trade_date / calculated_at` | `21:15` | `maintenance.materialize_wealth_sector_heat_daily` |
| 20/30 | `wealth_sector_momentum_daily` | 板块动量 | `sector_analysis / 板块分析` | `sector_analysis_published_batch / published_batch_trade_day` | `trade_date / published_at` | `20:05` | `maintenance.materialize_wealth_sector_analysis_daily` |
| 20/40 | `wealth_sector_dual_momentum_daily` | 板块双动量 | 同上 | 同上 | 同上 | `20:05` | 同上 |
| 20/50 | `wealth_sector_relative_rotation_daily` | 板块相对轮动 | 同上 | 同上 | 同上 | `20:05` | 同上 |
| 20/60 | `wealth_sector_member_breadth_daily` | 板块成员涨跌广度 | 同上 | 同上 | 同上 | `20:05` | 同上 |
| 20/70 | `wealth_sector_member_ma_breadth_daily` | 板块成员均线广度 | 同上 | 同上 | 同上 | `20:05` | 同上 |
| 20/80 | `wealth_sector_price_volume_daily` | 板块价量分析 | 同上 | 同上 | 同上 | `20:05` | 同上 |
| 20/90 | `wealth_sector_daily_insight_summary` | 板块每日洞察汇总 | 同上 | 同上 | 同上 | `20:05` | 同上 |
| 20/100 | `wealth_sector_daily_insight_item` | 板块每日洞察明细 | 同上 | 同上 | 同上 | `20:05` | 同上 |
| 30/10 | `news_stock_link` | 新闻个股关联 | `content_relation / 内容关联` | `maintenance_task_trace / maintenance_task_trace` | `None / None` | `None` | `maintenance.materialize_news_stock_links` |
| 40/10 | `equity_qfq_nineturn_daily` | 股票日线前复权神奇九转 | `technical_indicators / 技术指标` | `direct_trade_date / latest_completed_trade_day` | `trade_date / published_at` | `20:00` | Dagster `prod_core_stock_daily_qfq_nineturn` |
| 40/20 | `index_nineturn_daily` | 指数日线神奇九转 | `technical_indicators / 技术指标` | `direct_trade_date / latest_completed_trade_day` | `trade_date / published_at` | `20:00` | Dagster `prod_core_index_daily_nineturn` |

说明：

1. 板块热度和板块分析的判迟时间直接取当前 maintenance action 的 readiness 起始时间，避免页面与任务能力出现两个时点。
2. 神奇九转当前没有 Ops 维护动作，也没有独立的 Ops 发布时间契约；V1 使用现有成交额卡片的 `20:00` 盘后基线。该值只影响页面何时开始判迟，不改变 Dagster 生产。
3. `wealth_sector_analysis_publish_batch` 是控制表，只为 8 张卡片提供共享发布事实，不能注册为卡片。

### 3.3 Linter

新增 `BizDatasetLintIssue(dataset_key, code, message)`，校验器只做静态契约检查，不连接数据库：

1. `dataset_key`、`table_name` 唯一。
2. `dataset_key`、group key 和列名只允许小写字母、数字、下划线；`table_name` 必须精确匹配 `schema.table`。
3. query key、policy key、producer type 必须在 V1 白名单内。
4. `latest_completed_trade_day`、`published_batch_trade_day`、`wealth_turnover_snapshot` 必须同时声明日期列和 `HH:MM` 判迟时间。
5. `static_snapshot_ready` 必须声明日期列和时间列，不得声明判迟时间。
6. `maintenance_task_trace` 不得声明日期列、时间列和判迟时间。
7. `producer_type=maintenance_action` 时必须找到 action，且 action `target_tables` 包含本定义的 `table_name`。
8. `producer_type=dagster_asset` 时 `producer_key` 必须非空，但 `src/ops` 不 import Dagster。
9. 禁止把 `core_serving.wealth_sector_analysis_publish_batch` 注册成可见定义。
10. 架构测试固定校验本轮 15 个 key 和 15 张表完整存在；以后新增 Biz 数据集必须显式更新该门禁。

## 4. 查询与状态设计

### 4.1 内部结果模型

在 `biz_table_card_query_service.py` 内保留轻量内部模型，不落数据库：

```python
@dataclass(frozen=True, slots=True)
class BizDatasetObservation:
    earliest_business_date: date | None = None
    latest_business_date: date | None = None
    latest_success_at: datetime | None = None
    latest_observed_at: datetime | None = None
    query_error: bool = False

@dataclass(frozen=True, slots=True)
class BizActionRuntimeSnapshot:
    active_status: str | None = None
    active_started_at: datetime | None = None
    latest_success_at: datetime | None = None
    latest_failure_at: datetime | None = None
    schedule_total: int = 0
    schedule_active: int = 0
    schedule_next_run_at: datetime | None = None
```

不得保留当前未展示的 `row_count`。

### 4.2 单次请求读取顺序

```text
读取并 lint Biz definitions
  -> 收集 4 个 maintenance action key
  -> 一次读取 active maintenance TaskRun
  -> 一次读取 direct maintenance schedules
  -> maintenance_task_trace 所需时读取成功/失败时间
  -> 按 observation cache key 读取业务表事实
       sector analysis 8 张表只读一次 published batch
  -> 按每张 definition 计算卡片状态
  -> active TaskRun 最后覆盖为 running
  -> 按 group_order/item_order 返回 15 张卡片
```

本轮不增加进程缓存。原因是最终查询数量固定、查询均走现有索引或小型控制表；先以真实 SQL 测试守住查询形态，只有生产测量证明仍有压力时再单独设计缓存。

### 4.3 业务表查询

所有表名和列名只来自通过 linter 的静态定义，禁止接收 API 参数。实现优先使用 SQLAlchemy table/column 对象；确需静态 SQL 时只允许由已校验定义拼装标识符，值条件必须绑定参数。

#### A. `wealth_turnover_ready_snapshot`

保持当前过滤：

```sql
type = 'stock'
AND market = 'CN_A'
AND build_status = 'READY'
```

通过现有复合索引按 `trade_date` 取最早、最新 READY 快照；最新一行返回 `built_at` 和 `latest_trade_time`。删除 `count(*)`。

#### B. `direct_trade_date`

适用于每日板块热度和两张神奇九转表。每张表最多两个边界查询：

```text
ORDER BY business_date_column ASC LIMIT 1
ORDER BY business_date_column DESC, observed_at_column DESC LIMIT 1
```

不得用 `MAX(observed_at)` 代替最新业务日的发布时间，否则历史重算会把旧业务日的晚发布时间误认为最新业务事实。

现有索引依据：

- `wealth_sector_heat_daily` 主键以 `trade_date` 开头。
- `equity_qfq_nineturn_daily` 有 `(trade_date, ts_code)` 索引。
- `index_nineturn_daily` 有 `(trade_date, ts_code)` 索引。

#### C. `static_snapshot`

`wealth_sector_hierarchy` 是小型全量快照，不要求每日变化。读取最新 `published_at` 对应的 `code_reference_trade_date`；有数据且二者都存在即正常。不得按当前日期计算滞后。

#### D. `maintenance_task_trace`

适用于 `dm.equity_daily_snapshot` 和 `news_stock_link`。这两张对象分别是无观测时间的物化视图和无业务日期的关联表，不做每 5 秒全表扫描。

TaskRun 查询身份固定为：

```text
TaskRun.task_type = maintenance_action
TaskRun.request_payload_json.target_key IN (<definition producer keys>)
```

聚合读取：

- 最近 `success` 的结束时间。
- 最近 `failed/partial_success` 的结束时间。
- `canceled` 不证明数据错误，不作为失败状态。

状态判断：最近失败时间晚于最近成功时间则显示失败；否则有成功即正常；都没有则未知。活动任务由单独的 active 查询覆盖为执行中。

#### E. `sector_analysis_published_batch`

只查询：

```sql
core_serving.wealth_sector_analysis_publish_batch.status = 'PUBLISHED'
```

使用现有 `(status, trade_date, published_at)` 索引取最早和最新发布批次。8 张事实表共享同一个 observation，禁止分别扫描 8 张事实表，也禁止把 `BUILDING`、`FAILED` 或 `SUPERSEDED` 当成当前发布完成。

### 4.4 查询失败隔离

每个独立 observation query key 使用 SQLAlchemy nested transaction/savepoint。某类查询异常时：

1. 回滚该 savepoint，不回滚 API 会话中的其他只读查询。
2. 仅受影响卡片返回 `status=unknown`、`freshness_status=unknown`、`freshness_note=状态读取失败`。
3. 后端日志记录 definition key 和异常，不把数据库技术错误写到页面。
4. 其他卡片继续返回。

## 5. 新鲜度与状态优先级

### 5.1 期望业务日

`latest_completed_trade_day`、`published_batch_trade_day` 和成交额现有策略复用同一计算：

1. 今天开市且未到 `ready_after_local_time`：期望上一开市日。
2. 今天开市且已到判迟时间：期望今天。
3. 今天不开市：期望今天或之前最近开市日。
4. 交易日历缺失：返回未知，不用自然日猜。

滞后天数只统计开市日：

- 最新日期达到期望日期：`healthy/fresh`。
- 滞后 1 个开市日：`warning/lagging`。
- 滞后超过 1 个开市日：`stale/stale`。
- 表为空：`unknown/unknown`。

### 5.2 非连续策略

| policy | 状态规则 |
| --- | --- |
| `static_snapshot_ready` | 有业务基准日期和发布时间为正常；缺任一事实为未知；永不按日判迟 |
| `maintenance_task_trace` | 活动任务为执行中；最近失败晚于最近成功为失败；否则有成功为正常；无记录为未知 |

### 5.3 状态优先级

```text
观测查询失败 -> unknown
否则存在 queued/running/canceling 的目标 maintenance TaskRun -> running
否则按该卡片 freshness policy 计算
```

对直接读取业务表或发布批次的卡片，历史 TaskRun 失败不能覆盖已经就绪的业务表事实；TaskRun 只提供活动状态。对 `maintenance_task_trace` 卡片，TaskRun 本身就是唯一可用的构建观测。

## 6. TaskRun 与自动任务投影

### 6.1 动作绑定

`BizDatasetDefinition` 只引用 producer，不复制动作能力：

```python
action = get_maintenance_action(definition.producer_key)
primary_action_type = "maintenance_action" if action and action.manual_enabled else None
primary_action_key = action.key if action and action.manual_enabled else None
```

Dagster producer 的两个字段始终为 `None`。

### 6.2 活动任务

一次查询所有活动 maintenance TaskRun：

```text
status IN (queued, running, canceling)
task_type = maintenance_action
```

在 Python 中从 `request_payload_json.target_key` 取 action key，只保留本轮已登记 action。每个 action 取 `requested_at/id` 最新的一条，`active_task_run_started_at` 使用 `started_at or requested_at`。

活动任务通常数量很小，按 status 过滤命中现有 `idx_task_run_status_requested_at`；无需新增 JSON 索引或迁移。

### 6.3 自动任务

一次查询：

```text
OpsSchedule.target_type = maintenance_action
OpsSchedule.target_key IN (<4 action keys>)
```

每个 action 聚合：

- `total`：active + paused 总数。
- `active`：启用数。
- `next_run_at`：启用任务中最早的下次时间。
- `status`：有 active 为 `active`；只有 paused 为 `paused`；没有为 `none`。

只统计直接绑定该 maintenance action 的 schedule，不把 workflow schedule 展开后重复计入 Biz 卡片。原因是 Biz 卡片展示的是该维护入口自身的自动任务配置，而不是所有可能间接生产该表的流程。

多张表共享 `maintenance.materialize_wealth_sector_analysis_daily` 时，8 张卡片读取同一个 runtime snapshot，不复制 schedule 或 TaskRun 数据。

## 7. API 契约

### 7.1 Schema

在 `DatasetCardItem` 增加：

```python
primary_action_type: Literal["dataset_action", "maintenance_action"] | None = None
```

并保留：

```python
primary_action_key: str | None = None
```

投影规则：

| 卡片 | type | key |
| --- | --- | --- |
| 普通外部数据集且支持手动维护 | `dataset_action` | `<dataset>.maintain` |
| Biz maintenance producer 且 action `manual_enabled=True` | `maintenance_action` | action key |
| Dagster 只读 Biz 卡片 | `null` | `null` |

两个字段必须同时为空或同时有值，架构测试守住该约束。

### 7.2 路由

继续使用：

```http
GET /api/v1/ops/dataset-cards?source_key=biz_tableset
```

不增加 query 参数和新路由。返回顺序固定为 `group_order, item_order, display_name, card_key`。

## 8. 前端编码方案

### 8.1 类型与映射

`frontend/src/shared/api/types.ts` 增加：

```ts
primary_action_type: "dataset_action" | "maintenance_action" | null;
```

`SourceCardItem` 增加 `primaryActionType` 和 `autoScheduleStatus`，不在页面根据 key 前缀猜类型。

### 8.2 顺序

删除当前 `.sort((a, b) => a.displayName.localeCompare(...))`。页面必须保持 API 的 group 顺序和 group 内 item 顺序，不能覆盖 `group_order/item_order`。

实现时直接按每个 `group.items.map()` 构造 UI 项，避免先 flatten、再按中文名排序、再通过 `some()` 反向拼组。

### 8.3 操作入口

链接使用：

```tsx
buildManualTaskHref({
  actionKey: item.primaryActionKey,
  actionType: item.primaryActionType,
})
```

显示规则：

1. Biz 卡片只要 type/key 存在，就始终显示“去操作”，不因当前状态正常而隐藏维护入口。
2. 非 Biz 数据源保持现有行为，只在非正常状态显示入口，避免本轮扩大外部数据集交互范围。
3. type/key 为空时不显示入口。

### 8.4 自动任务文案

| API 状态 | 页面展示 |
| --- | --- |
| `active` | “自动”徽标，tooltip 显示启用数/总数和最近下次运行时间 |
| `paused` | “自动已暂停”弱提示，tooltip 显示 `0/总数` |
| `none` 且有 maintenance action | “未配置自动更新” |
| `none` 且无 action | “只读展示” |

Biz 卡片不展示伪造的 probe 状态，`probe_total/probe_active` 保持 0。

### 8.5 页面说明

`ops-v21-biz-table-page.tsx` 改为：

```text
展示本系统自建业务数据集的状态、维护入口和自动任务配置。
```

## 9. 逐文件改动清单

| 文件 | 精确改动 |
| --- | --- |
| `src/ops/catalog/biz_dataset_definitions.py` | 新增 dataclass、15 个定义、lookup、linter |
| `src/ops/catalog/biz_table_catalog.py` | 删除，不留兼容 |
| `src/ops/queries/biz_table_card_query_service.py` | 定义驱动查询、5 类观测、5 类状态、TaskRun/schedule 投影、失败隔离 |
| `src/ops/queries/dataset_card_query_service.py` | 更新 Biz import；普通卡片返回 `primary_action_type=dataset_action` |
| `src/ops/schemas/dataset_card.py` | 增加 action type 契约 |
| `frontend/src/shared/api/types.ts` | 同步 action type |
| `frontend/src/pages/ops-v21-source-page.tsx` | 保留服务端顺序、正确跳转、区分只读/未配置/暂停 |
| `frontend/src/pages/ops-v21-biz-table-page.tsx` | 修正页面说明 |
| `tests/web/test_ops_biz_table_cards_api.py` | 15 张卡片、观测、状态、动作、schedule、查询失败测试 |
| `tests/web/test_ops_dataset_cards_api.py` | 普通卡片 action type 回归 |
| `tests/architecture/test_ops_biz_dataset_definition_guardrails.py` | 新增定义集合与 linter 门禁 |
| `frontend/src/pages/ops-v21-source-page.test.tsx` | Biz 分组、顺序、维护链接、自动任务、只读卡片测试 |
| `docs/ops/ops-api-reference-v1.md` | 补充 `primary_action_type` 和 Biz 卡片语义 |
| 本方案与 LLD、`docs/README.md` | 更新状态和索引 |

不修改 action catalog、TaskRun/schedule 模型或现有 executor。

## 10. 测试设计

### 10.1 Registry 与架构

1. 定义总数为 15，key/table 唯一。
2. 14 张新增表全部登记，原成交额卡片保留。
3. `wealth_sector_analysis_publish_batch` 不在可见定义中。
4. 页面分组只有 `data_mart`、`sector_analysis`、`content_relation`、`technical_indicators`，不存在 `wealth_market/财势乾坤`。
5. 4 个 maintenance producer 均存在，目标表绑定正确。
6. Dagster producer 不触发 `src/ops -> lake_console` import。
7. 构造非法 definition，逐项验证 linter reason code。

### 10.2 观测与状态

1. turnover 只认 `stock/CN_A/READY`，且不执行 `count(*)`。
2. direct daily 表读取最早、最新日期，并只使用最新日期的发布时间。
3. hierarchy 有快照即正常，不按自然日判迟。
4. sector analysis 忽略 BUILDING/FAILED/SUPERSEDED，只认 PUBLISHED；8 张卡共享结果。
5. task trace 最近失败晚于成功时失败，新成功覆盖旧失败。
6. canceled 不覆盖最近成功。
7. 判迟时间前期望上一开市日，时间后期望当前开市日。
8. 一个观测查询抛错时，仅相关卡片未知，其他卡片仍返回。

### 10.3 TaskRun 与 schedule

1. maintenance active TaskRun 按 JSON `target_key` 命中，resource_key 为 null 仍能显示执行中。
2. 多张板块表共享同一个 active 状态。
3. schedule 聚合 active/paused/none 和最早 `next_run_at` 正确。
4. workflow schedule 不计入 direct maintenance action 卡片。
5. Dagster 卡片 action、TaskRun、schedule 均为空。

### 10.4 API 与前端

1. API 返回 15 张卡片，分组和 item 顺序与定义一致。
2. 11 张卡片返回 `maintenance_action` 和正确 key。
3. 3 张新增 Dagster 卡片及原 turnover 卡片只读。
4. 普通外部数据集继续返回 `dataset_action`。
5. maintenance card 的“去操作”链接同时携带 type/key，正常状态下仍可进入。
6. active、paused、未配置、只读四种自动任务文案正确。
7. loading、error、空列表和 5 秒轮询回归不变。

### 10.5 验证命令

```bash
uv run ruff check \
  src/ops/catalog/biz_dataset_definitions.py \
  src/ops/queries/biz_table_card_query_service.py \
  src/ops/queries/dataset_card_query_service.py \
  src/ops/schemas/dataset_card.py \
  tests/web/test_ops_biz_table_cards_api.py \
  tests/web/test_ops_dataset_cards_api.py \
  tests/architecture/test_ops_biz_dataset_definition_guardrails.py

uv run pytest -q \
  tests/web/test_ops_biz_table_cards_api.py \
  tests/web/test_ops_dataset_cards_api.py \
  tests/architecture/test_ops_biz_dataset_definition_guardrails.py

cd frontend && npm run test -- ops-v21-source-page
cd frontend && npm run typecheck
python3 scripts/check_docs_integrity.py
```

测试路径或脚本若与实施时仓库现实不一致，先核实当前命令，不得通过删除测试或放宽断言绕过。

## 11. 开发步骤

| 里程碑 | 编码顺序 | 停止条件 |
| --- | --- | --- |
| M0 | 重读本 LLD、同步 CodeGraph、确认工作区脏文件和测试基线 | 当前代码与 LLD 的 action/table/字段不一致 |
| M1 | 新建 Biz definition、linter 和架构测试；删除旧 catalog | 15 张表或 producer 无法静态证明 |
| M2 | 实现 observation 与 freshness；先完成后端服务级测试 | 查询需要无索引全表轮询或出现新的业务语义 |
| M3 | 投影 action type、active TaskRun 和 schedule；补 API 测试 | 必须新增状态表或修改 TaskRun 数据才能实现 |
| M4 | 前端消费契约、保留服务端顺序、修正入口和文案 | 页面必须自行推断动作或状态 |
| M5 | 跑定向回归，更新 API 文档与方案状态，逐条对账 | 任一现有外部数据集卡片发生非计划行为变化 |

每个里程碑只暂存本需求文件，禁止 `git add .`。

## 12. 数据与发布影响

本轮没有数据处理步骤：

1. 不执行 SQL DDL/DML，不清表、不迁移、不重算。
2. 不刷新 `ops.dataset_status_snapshot`，Biz 卡片不依赖它。
3. 不修改历史 TaskRun。现有 maintenance action TaskRun 已保存 `request_payload_json.target_key`，部署后可直接读取。
4. 不修改现有 schedule。直接绑定 maintenance action 的自动任务会自然显示。
5. 后端与前端必须同版本发布，因为 `primary_action_type` 是共同契约；这不是数据库迁移。

## 13. 完成门禁

只有同时满足以下条件才可把方案和 LLD 改为“已实现”：

1. API 精确返回 15 张卡片和 4 个已确认分组。
2. 11 张可维护卡片能进入正确 maintenance action 表单，并显示 direct schedule 状态。
3. 3 张新增 Dagster 卡片和原 turnover 卡片保持只读。
4. 8 张板块分析卡片只认一次 PUBLISHED batch 观测。
5. 页面不再按中文名重新排序，不再把所有 Biz 卡片写死为只读。
6. 查询中没有大表 `count(*)`、无索引周期排序或页面端事实拼装。
7. 不存在旧 `BizTableCatalogItem`、`BIZ_TABLE_CATALOG` 或兼容导出。
8. 后端、前端、架构和文档检查全部通过。

## 14. 实施对账

截至 2026-09-05，M1 至 M5 已按本 LLD 落地：

1. 新定义与 linter 位于 `src/ops/catalog/biz_dataset_definitions.py`，15 个 key、15 张表、4 个分组和 producer/action 绑定由架构测试固定。
2. `BizTableCardQueryService` 已实现五类观测策略、四类 freshness 策略、业务查询隔离、TaskRun 状态和直接 schedule 聚合；板块分析八张卡共享一次 PUBLISHED batch 观测。
3. 数据卡片契约已增加 `primary_action_type`；普通数据集返回 `dataset_action`，Biz 可维护卡片返回 `maintenance_action`，只读卡片返回 `null`。
4. Biz 页面已改为保留服务端顺序，并按服务端动作类型生成维护入口；未配置、暂停和只读文案不再混用。
5. 旧 `src/ops/catalog/biz_table_catalog.py` 已删除，不保留旧类型、旧常量或兼容导出。
6. 部署、生产数据核验和页面验收不属于本轮开发动作，仍待运营侧完成。
