# Ops Biz 数据集自动投影与 14 表展示技术方案 v1

状态：代码已实现，待部署验收
日期：2026-09-05
适用范围：`src/ops/catalog/**`、`src/ops/queries/**`、Ops 数据卡片 API、Biz 数据源页面与对应测试
开发模板：[Biz 数据集开发说明模板](/Users/congming/github/goldenshare/docs/templates/biz-dataset-development-template.md)
详细设计：[Ops Biz 数据集自动投影与 14 表展示 LLD v1](/Users/congming/github/goldenshare/docs/ops/ops-biz-dataset-auto-projection-lld-v1.md)

## 1. 目标

本需求解决两个问题：

1. 将当前已经存在、但没有出现在任何数据源页面上的 14 张内部业务数据表，逐表展示在“Biz数据集”页面。
2. 将现有手写单表逻辑升级为单一事实源自动投影：以后新增 Biz 数据集时，只定义一次，卡片 API 和页面自动出现，不再分别修改查询、API 和前端常量。

完成后：

- 原有 `core_serving.wealth_market_turnover_snapshot` 卡片继续保留。
- 原有“成交额分钟快照”并入“数据集市”分组，删除 Biz 页面上的“财势乾坤”分组。
- 新增 14 张卡片，Biz 页面合计 15 张卡片。
- 每张物理业务表对应一张卡片，不把 14 张表合并成 7 张逻辑卡片。
- `core_serving.wealth_sector_analysis_publish_batch` 是内部发布控制表，不作为第 15 张新增业务卡片。

## 2. 当前代码事实

### 2.1 外部数据集为什么能够自动显示

Tushare/Biying 卡片当前从 `DatasetDefinition` 生成：

```text
DatasetDefinition
  -> DatasetCardQueryService
  -> GET /api/v1/ops/dataset-cards?source_key=<source>
  -> OpsV21SourcePage
```

`DatasetDefinition.source.source_keys` 决定数据集出现在哪个外部数据源页面，Ops 展示目录决定分组与顺序。

### 2.2 Biz 页面为什么只能显示一张卡片

Biz 页面走独立分支：

```text
source_key=biz_tableset
  -> BizTableCardQueryService
  -> BIZ_TABLE_CATALOG
```

当前存在两个限制：

1. `BIZ_TABLE_CATALOG` 只有 `wealth_market_turnover_snapshot` 一项。
2. `BizTableCardQueryService._load_observation()` 只实现了 `wealth_turnover_snapshot`，增加第二种状态策略就会抛出不支持错误。

因此，本需求不能只向 tuple 追加 14 行配置；必须先把 Biz 定义、观测和卡片投影做成通用能力。

### 2.3 Biz 卡片与维护任务当前是两套事实

当前手动任务和自动任务不读取 `BIZ_TABLE_CATALOG`：

- 手动维护动作来自 `MaintenanceActionDefinition.manual_enabled`。
- 自动任务目标来自 `MaintenanceActionDefinition.schedule_enabled` 与 `ScheduleAutomationCapabilityResolver`。
- 实际任务使用 `target_type=maintenance_action`，由 TaskRun dispatcher 调用已注册执行器。

卡片能否显示，与是否支持手动/自动维护必须分开定义。不能因为某张表有卡片，就自动假设它能被 Ops 重建。

## 3. 设计原则

1. **显式定义，自动投影**：数据库只知道表结构，不知道中文名、业务日期、新鲜度和生产入口；禁止扫描数据库后按表名猜卡片语义。
2. **不进入 `DatasetDefinition`**：Biz 数据集不是外部源站维护对象，不进入 ingestion planner、request builder 或 DatasetActionResolver。
3. **定义一次**：显示名、物理表、分组、观测、新鲜度和生产入口只在 `BizDatasetDefinition` 定义；页面与 API 不再复制。
4. **任务能力不复制**：`manual_enabled`、`schedule_enabled`、参数和自动任务能力继续以 `MaintenanceActionDefinition` 为事实源，Biz 定义只引用生产入口。
5. **不为展示新造任务**：没有现成 Ops 维护动作的 Biz 数据集保持只读。本需求不为 Dagster 资产增加 Ops 包装动作。
6. **业务表逐表展示**：本轮 14 张物理业务表各有一张卡片；控制表、临时表、staging 表不展示。
7. **观测不影响生产**：卡片查询只读；观测失败只影响卡片状态，不写业务表、不创建 TaskRun、不改变生产事务。
8. **不做昂贵轮询**：页面每 5 秒刷新，禁止对大表反复 `count(*)`、全表排序或无索引扫描。

## 4. 目标模型

### 4.1 `BizDatasetDefinition`

将现有 `BizTableCatalogItem` 升级为正式的 Biz 数据集事实定义。建议结构：

```python
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
    observation_query_key: str
    freshness_policy_key: str
    business_date_column: str | None
    observed_at_column: str | None
    ready_after_local_time: str | None
    producer_type: str
    producer_key: str
```

字段职责：

| 字段 | 作用 |
| --- | --- |
| `dataset_key` | Biz 卡片唯一身份，不等于 `DatasetDefinition.dataset_key` |
| `table_name` | 被观测的真实业务表或物化视图 |
| `group_* / item_order` | Biz 页面分组与顺序的唯一来源 |
| `observation_query_key` | 决定如何从业务表读取最早/最新日期和构建时间 |
| `freshness_policy_key` | 决定如何把观测事实判断为正常、滞后、未确认或失败 |
| `business_date_column` | 业务日期列；无业务日期时必须明确为 `None` |
| `observed_at_column` | 构建/发布时间列；没有时明确为 `None` |
| `ready_after_local_time` | 日度数据可被判迟的最早北京时间；非日度策略不填写 |
| `producer_type` | `maintenance_action`、`dagster_asset` 或 `materialized_view` |
| `producer_key` | 真实生产入口；若为维护动作，直接引用 action key |

不在 Biz 定义中保存：

- `manual_enabled`
- `schedule_enabled`
- 自动任务日期策略
- 手动参数
- 执行器名称

这些继续从生产入口的当前契约读取，避免同一能力出现两个开关。

### 4.2 注册表与校验器

目标位置：

```text
src/ops/catalog/biz_dataset_definitions.py
```

提供：

```python
list_biz_dataset_definitions()
get_biz_dataset_definition(dataset_key)
lint_biz_dataset_definitions()
```

校验规则：

1. `dataset_key`、`table_name` 唯一。
2. 表名必须是静态定义的合法 `schema.table`，禁止接受请求参数拼接 SQL 标识符。
3. 日度新鲜度策略必须有业务日期列和判迟时间。
4. 静态/事件型策略不得伪装成每日连续数据。
5. `producer_type=maintenance_action` 时，action 必须存在，且 `action.target_tables` 必须包含本表。
6. `producer_type=dagster_asset` 时只记录资产 key，不在 Ops 中 import orchestrator。
7. 控制表 `wealth_sector_analysis_publish_batch` 不得注册为用户可见卡片。
8. 本轮定义集合必须完整覆盖已确认的 14 张表。

## 5. 观测与新鲜度

### 5.1 分开定义“怎么读”和“怎么判断”

当前 `status_policy_key` 同时承担 SQL 查询和状态判断，扩展后容易形成一个策略一个特殊分支。本轮拆成：

```text
observation_query_key：怎么读真实表
freshness_policy_key：读到以后怎么判断
```

V1 只实现本轮确实需要的少量策略，不做通用规则引擎。

### 5.2 观测查询

| query key | 用途 |
| --- | --- |
| `direct_trade_date` | 从有索引的业务日期列读取最早/最新日期，并可读取最大构建时间 |
| `static_snapshot` | 读取小型静态表的基准日期、发布时间和是否有数据 |
| `maintenance_task_trace` | 不扫描大型无日期/无索引表，读取对应维护动作最近成功 TaskRun |
| `sector_analysis_published_batch` | 只认 `status=PUBLISHED` 的发布批次，并将同一批次事实投影给 8 张子表 |
| `wealth_turnover_ready_snapshot` | 保留当前成交额快照的 READY/type/market 过滤口径 |

性能要求：

1. 不再为卡片计算未展示的全表 `count(*)`。
2. 日度表只能使用已有业务日期索引读取边界。
3. `dm.equity_daily_snapshot` 和 `news_stock_link` 不做周期性全表扫描，使用维护动作成功记录展示最近构建。
4. 8 张板块分析表共享一次已发布批次观测，不重复计算同一发布事实。
5. 业务观测可使用短周期进程内缓存；TaskRun 和自动任务状态仍按当前请求读取。缓存不是持久化状态，不新增数据库表。

### 5.3 新鲜度策略

| policy key | 人话语义 |
| --- | --- |
| `latest_completed_trade_day` | 到该数据的可用时点后，应至少覆盖最近一个已完成交易日 |
| `published_batch_trade_day` | 只有正式发布批次才算可用，BUILDING/FAILED 不算完成 |
| `static_snapshot_ready` | 有完整静态快照和发布时间即正常，不要求每天变化 |
| `maintenance_task_trace` | 只展示最近一次构建是否成功和时间，不凭空要求每天必须有新数据 |
| `wealth_turnover_snapshot` | 保留现有成交额分钟快照口径 |

禁止：

- 根据表名包含 `_daily` 就自动判断为每日必须更新。
- 用当前自然日直接减 `MAX(trade_date)`。
- 把 TaskRun 成功等同于业务表一定有目标日期数据；日度表仍以业务表观测为准。

## 6. 15 张 Biz 卡片目标清单

### 6.1 数据集市

| key | 显示名 | 物理表 | 观测/新鲜度 | 生产入口 |
| --- | --- | --- | --- | --- |
| `wealth_market_turnover_snapshot` | 成交额分钟快照 | `core_serving.wealth_market_turnover_snapshot` | `wealth_turnover_ready_snapshot` / `wealth_turnover_snapshot` | 现有 Dagster 生产入口 |
| `equity_daily_snapshot` | 股票日线数据集市快照 | `dm.equity_daily_snapshot` | `maintenance_task_trace` | `maintenance.rebuild_dm` |

“数据集市”统一使用 `group_key=data_mart`、`group_label=数据集市`。不得继续注册或返回 `wealth_market / 财势乾坤` 分组。

### 6.2 板块分析

| key | 显示名 | 物理表 | 观测/新鲜度 | 生产入口 |
| --- | --- | --- | --- | --- |
| `wealth_sector_hierarchy` | 板块层级 | `core_serving.wealth_sector_hierarchy` | `static_snapshot` / `static_snapshot_ready` | Dagster `prod_core_wealth_sector_hierarchy` |
| `wealth_sector_heat_daily` | 每日板块热度 | `core_serving.wealth_sector_heat_daily` | `direct_trade_date` / `latest_completed_trade_day` | `maintenance.materialize_wealth_sector_heat_daily` |
| `wealth_sector_momentum_daily` | 板块动量 | `core_serving.wealth_sector_momentum_daily` | `sector_analysis_published_batch` / `published_batch_trade_day` | `maintenance.materialize_wealth_sector_analysis_daily` |
| `wealth_sector_dual_momentum_daily` | 板块双动量 | `core_serving.wealth_sector_dual_momentum_daily` | 同上 | 同上 |
| `wealth_sector_relative_rotation_daily` | 板块相对轮动 | `core_serving.wealth_sector_relative_rotation_daily` | 同上 | 同上 |
| `wealth_sector_member_breadth_daily` | 板块成员涨跌广度 | `core_serving.wealth_sector_member_breadth_daily` | 同上 | 同上 |
| `wealth_sector_member_ma_breadth_daily` | 板块成员均线广度 | `core_serving.wealth_sector_member_ma_breadth_daily` | 同上 | 同上 |
| `wealth_sector_price_volume_daily` | 板块价量分析 | `core_serving.wealth_sector_price_volume_daily` | 同上 | 同上 |
| `wealth_sector_daily_insight_summary` | 板块每日洞察汇总 | `core_serving.wealth_sector_daily_insight_summary` | 同上 | 同上 |
| `wealth_sector_daily_insight_item` | 板块每日洞察明细 | `core_serving.wealth_sector_daily_insight_item` | 同上 | 同上 |

板块分析 8 张子表必须只认 `wealth_sector_analysis_publish_batch.status=PUBLISHED` 的批次。控制表负责证明原子发布，不单独展示。

### 6.3 内容关联

| key | 显示名 | 物理表 | 观测/新鲜度 | 生产入口 |
| --- | --- | --- | --- | --- |
| `news_stock_link` | 新闻—个股关联 | `core_serving.news_stock_link` | `maintenance_task_trace` | `maintenance.materialize_news_stock_links` |

### 6.4 技术指标

| key | 显示名 | 物理表 | 观测/新鲜度 | 生产入口 |
| --- | --- | --- | --- | --- |
| `equity_qfq_nineturn_daily` | 股票日线前复权神奇九转 | `core_serving.equity_qfq_nineturn_daily` | `direct_trade_date` / `latest_completed_trade_day` | Dagster `prod_core_stock_daily_qfq_nineturn` |
| `index_nineturn_daily` | 指数日线神奇九转 | `core_serving.index_nineturn_daily` | `direct_trade_date` / `latest_completed_trade_day` | Dagster `prod_core_index_daily_nineturn` |

## 7. 手动任务与自动任务投影

### 7.1 卡片与动作的绑定

新增卡片字段：

```text
primary_action_type: dataset_action | maintenance_action | null
primary_action_key: string | null
```

原因：当前前端看到 `primary_action_key` 后固定按 `dataset_action` 跳转，无法正确打开 Biz 的 `maintenance_action`。

投影规则：

1. `producer_type=maintenance_action`：从 action catalog 读取 `manual_enabled`、`schedule_enabled`、参数和自动任务能力。
2. `manual_enabled=True`：卡片可以跳转到该维护动作的手动任务表单。
3. `schedule_enabled=True`：卡片展示该 action 的自动任务数量、启用状态和下次运行时间。
4. `producer_type=dagster_asset`：本轮保持只读，不显示“去操作”，不伪造 Ops 自动任务状态。
5. 多张表由同一个 action 原子生成时，可以绑定同一个 action；其任务状态一致，但表观测状态仍逐卡返回。

### 7.2 当前 14 张表的任务能力

| 范围 | 手动任务 | 自动任务 | 处理方式 |
| --- | --- | --- | --- |
| 数据集市快照 | 已有 | 已有 | 复用 `maintenance.rebuild_dm` |
| 每日板块热度 | 已有 | 已有 | 复用 `maintenance.materialize_wealth_sector_heat_daily` |
| 8 张板块分析事实 | 已有 | 已有 | 全部复用同一个原子发布 action |
| 新闻—个股关联 | 已有 | 已有 | 复用 `maintenance.materialize_news_stock_links` |
| 板块层级 | 无 | 无 | Dagster 生产，Biz 卡片只读 |
| 股票/指数神奇九转 | 无 Ops 动作 | 无 Ops 自动任务 | Dagster sensor 生产，Biz 卡片只读 |

本需求不新增、删除或改变上述生产动作，只把已存在能力正确投影到卡片。

## 8. API 与页面

### 8.1 API

继续使用：

```http
GET /api/v1/ops/dataset-cards?source_key=biz_tableset
```

不新增第二套卡片 API。响应仍为 `DatasetCardListResponse`，但 `DatasetCardItem` 增加 `primary_action_type`。

后端必须返回：

- 完整 15 张卡片。
- 每张卡片的分组、物理表、观测时间、业务日期和状态。
- 已绑定维护动作的 action type/key、活动 TaskRun 和自动任务摘要。
- 只读卡片的 action 字段为 `null`。

### 8.2 前端

现有 Biz 页面和卡片组件继续复用，只做必要契约适配：

1. “去操作”根据服务端 `primary_action_type` 生成链接，不再固定 `dataset_action`。
2. 有维护动作但未配置自动任务时显示“未配置自动更新”，不显示“只读展示”。
3. 没有维护动作的 Dagster 资产显示“只读展示”。
4. 页面不根据表名推断中文名、状态、分组或动作。
5. 仍由服务端返回顺序；前端不得按中文名重新打乱同组 `item_order`。

## 9. 代码影响面

计划内：

```text
src/ops/catalog/biz_dataset_definitions.py
src/ops/queries/biz_table_card_query_service.py
src/ops/queries/dataset_card_query_service.py
src/ops/schemas/dataset_card.py
frontend/src/shared/api/types.ts
frontend/src/pages/ops-v21-source-page.tsx
tests/web/test_ops_biz_table_cards_api.py
frontend/src/pages/ops-v21-source-page.test.tsx
tests/architecture/（Biz registry 门禁）
docs/ops/ops-api-reference-v1.md
docs/ops/ops-biz-table-source-display-plan-v1.md
docs/templates/biz-dataset-development-template.md
```

计划外：

- `DatasetDefinition`、ingestion、request builder、writer。
- 14 张业务表结构和数据。
- Alembic 迁移。
- 现有维护动作的计算逻辑。
- Dagster asset/sensor 执行逻辑。
- 新增 Ops 状态表或数据快照表。

## 10. 开发里程碑

| 里程碑 | 目标 | 完成标准 |
| --- | --- | --- |
| M0 | 当前契约与查询性能基线 | 复核 CodeGraph、14 表索引/日期字段、现有 API/前端测试；禁止直接编码猜测 |
| M1 | Biz 定义与 linter | `BizDatasetDefinition`、registry、唯一性/动作绑定/策略校验完成 |
| M2 | 通用观测与状态策略 | 5 类观测、5 类状态口径完成；无大表 count/无索引轮询 |
| M3 | 15 张卡片注册 | 14 张新增表逐表定义；成交额分钟快照并入数据集市；控制表明确排除；最终卡片总数为 15，且不存在“财势乾坤”分组 |
| M4 | 任务状态投影 | `primary_action_type`、活动任务和自动任务摘要正确；Dagster 卡片只读 |
| M5 | API 与页面 | Biz 页面展示 15 张卡片，分组、文案、操作链接正确 |
| M6 | 测试与文档 | 后端、前端、架构、文档检查通过，逐条对账本方案 |

## 11. 测试计划

### 11.1 Registry

1. 15 个 Biz 定义 key/table 唯一。
2. 新增 14 张表全部存在，发布控制表不存在于用户卡片定义。
3. action 绑定存在，且 action 的 `target_tables` 包含目标表。
4. 非法表名、缺少日期字段、未知策略、错误 producer 直接 lint 失败。

### 11.2 查询与状态

1. 日度表正确读取最早/最新业务日期。
2. 发布批次只认 `PUBLISHED`，忽略 `BUILDING/FAILED`。
3. 静态表不因为日期没变化而标滞后。
4. 事件/构建型表不做全表日期猜测。
5. 空表、查询失败、TaskRun 失败均返回清晰状态；查询异常不拖垮其他卡片。
6. SQL 记录证明不包含大表 `count(*)`。

### 11.3 任务投影

1. 维护动作卡片返回 `primary_action_type=maintenance_action`。
2. 手动任务链接携带正确 action type/key。
3. 自动任务数量按 `OpsSchedule(target_type=maintenance_action, target_key=...)` 计算。
4. 多表共享 action 时每张卡都显示相同任务摘要。
5. Dagster 卡片不显示“去操作”和 Ops 自动任务徽标。

### 11.4 回归

1. Tushare/Biying 卡片继续返回 `primary_action_type=dataset_action`。
2. 原成交额分钟快照口径不变。
3. 原成交额分钟快照只改变展示分组，不改变表、查询和生产入口。
4. Biz 查询失败不影响 Tushare/Biying API。
5. 前端仍支持 loading、error、空列表和轮询刷新。

## 12. 验收标准

1. Biz 数据集页面合计显示 15 张卡片，其中 14 张为本轮新增。
2. 15 张卡片名称、物理表、分组、状态和观测字段与定义一致；成交额分钟快照位于“数据集市”，页面不存在“财势乾坤”分组。
3. 11 张已有 Ops 维护动作的卡片能正确进入手动任务，并显示自动任务摘要。
4. 3 张 Dagster 生产表保持只读，不出现错误操作入口。
5. 不新增数据库表，不修改业务数据，不改变任何生产任务行为。
6. 新增一份合法 `BizDatasetDefinition` 后，无需再改 API 和页面即可自动出现卡片。
7. 定向后端、前端和架构测试通过；`python3 scripts/check_docs_integrity.py` 通过。

## 13. 已确认决策

1. 14 张物理业务表分别显示 14 张卡片，不合并。
2. `wealth_sector_analysis_publish_batch` 是控制表，不计入 14 张业务表，也不显示卡片。
3. Biz 数据集通过独立 Definition 自动投影，不进入外部数据集的 `DatasetDefinition`。
4. 14 张新增卡片中，已有维护动作的 11 张显示正确的手动入口和自动任务状态；其余 3 张 Dagster 生产表保持只读。
5. 页面固定采用“数据集市、板块分析、内容关联、技术指标”四组。
6. 成交额分钟快照并入“数据集市”；删除“财势乾坤”分组，不保留兼容分组或双重展示。

## 14. 既有数据与上线影响

本需求不迁移、不重算、不清理任何既有业务数据或 Ops 状态数据。

1. `BizDatasetDefinition`、卡片查询、API 字段和前端展示属于代码契约调整，不新增 Alembic 迁移，也不修改 15 张业务表结构或数据。
2. 卡片请求实时读取业务表观测；活动任务和历史结果实时读取现有 `ops.task_run`，自动任务摘要实时读取现有 `ops.schedule`。不依赖 `ops.dataset_status_snapshot`，因此不需要重建或刷新 snapshot。
3. 已有 TaskRun 历史记录无需改写。11 张可维护卡片按既有 `maintenance_action` key 查询，历史任务会自然显示。
4. 已有自动任务无需删除、重建或改写。只要其 `target_type/target_key` 与现有 maintenance action 契约一致，部署后会自然投影到对应卡片。
5. 8 张板块分析表共享同一个维护动作时，只读取同一份任务和 schedule 事实，不复制 Ops 数据，也不新增 8 份配置。
6. 成交额分钟快照改到“数据集市”只是展示目录变更，不改变其物理表、生产入口、查询口径或历史数据。
7. 上线只要求后端和前端按同一版本部署并刷新页面。新增 `primary_action_type` 是前后端共同契约，不能只部署其中一端；这属于发布配套，不是数据库数据刷新。

## 15. 实施结果

截至 2026-09-05，代码开发已完成：

1. `BizDatasetDefinition` 已成为 15 张 Biz 卡片的唯一静态事实源，旧 `BizTableCatalogItem/BIZ_TABLE_CATALOG` 已删除且无兼容导出。
2. 卡片查询已按定义读取业务观测、现有 TaskRun 和直接绑定的 maintenance schedule；单张业务表查询失败只影响对应卡片。
3. `DatasetCardItem` 已增加 `primary_action_type`，外部数据集和 Biz 维护动作均由服务端明确返回动作类型，页面不再自行猜测。
4. Biz 页面保留服务端分组和排序；11 张维护动作卡片提供操作入口与自动任务状态，4 张 Dagster 生产卡片保持只读。
5. 本轮未新增迁移、状态表或业务数据处理；部署和页面验收仍由运营侧执行。
