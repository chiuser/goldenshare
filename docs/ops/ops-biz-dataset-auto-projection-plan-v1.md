# Ops Biz 数据集投影契约 v1

状态：当前代码说明；原 2026-09-05 记录为“代码已实现，待部署验收”。本次 2026-09-09 仅静态核验，未核实生产版本或页面验收，不自动结案。
适用：Biz 数据集目录、Ops 卡片查询及页面消费；不修改业务生产、数据、任务配置或数据库结构。

## 1. 边界与阅读入口

Biz 卡片展示本系统生成的业务表/物化视图，不是外部源站数据集；不进入 Foundation 的 DatasetDefinition、ingestion 或源请求构造链。页面来源标识仍为 `biz_tableset / Biz数据集`，接口仍为 `GET /api/v1/ops/dataset-cards?source_key=biz_tableset`。

`BizDatasetDefinition → BizTableCardQueryService → DatasetCardListResponse → OpsV21SourcePage`

- 静态身份、表、组、观测策略与 producer 由 [Biz 定义](/Users/congming/github/goldenshare/src/ops/catalog/biz_dataset_definitions.py)维护。
- 查询、状态与任务摘要由 [Biz 卡片查询](/Users/congming/github/goldenshare/src/ops/queries/biz_table_card_query_service.py)投影；不扫描数据库自动发现表，不按表名猜日期。
- `manual_enabled/schedule_enabled`、参数及自动任务能力归现有 MaintenanceActionDefinition 和自动任务能力契约，Biz 定义不复制开关。
- API 字段只在 [API §2.5/12.1](/Users/congming/github/goldenshare/docs/ops/ops-api-reference-v1.md)维护；新增 Biz 数据集用[开发模板](/Users/congming/github/goldenshare/docs/templates/biz-dataset-development-template.md)。
- 外部数据集的展示目录见[目录说明](/Users/congming/github/goldenshare/docs/ops/ops-dataset-catalog-view-plan-v1.md)，不能把它的 ops_dataset_default 强套到 Biz 四组。

旧一期只展示一张只读成交额卡片的限制已经过时；旧 `biz_table_catalog.py / BizTableCatalogItem / BIZ_TABLE_CATALOG` 已移除，不恢复兼容导出。原一期文档和二期 LLD 的有效内容合并到本文。

## 2. 定义、注册与新增边界

`BizDatasetDefinition` 完整字段：

`dataset_key, display_name, description, table_name, group_key, group_label, group_order, item_order, observation_query_key, freshness_policy_key, business_date_column, observed_at_column, ready_after_local_time, producer_type, producer_key`。

| 字段组 | 职责 |
| --- | --- |
| dataset_key / table_name | 卡片身份与 schema.table；表或物化视图的对象类型不决定 producer_type |
| group_* / item_order | Biz 分组与排序，不反向改变业务领域或生产链 |
| observation_query_key / freshness_policy_key | 分开描述“怎么读”和“读后如何判状态” |
| business_date_column / observed_at_column | 观测日期/时间列；任务轨迹型明确为空 |
| ready_after_local_time | 日度卡片开始判迟的北京时间；不改变生产调度 |
| producer_type / producer_key | 当前枚举仅 maintenance_action、dagster_asset，分别引用动作 key 或资产 key；materialized_view 不是合法 producer 枚举 |

公开入口为 `list_biz_dataset_definitions / get_biz_dataset_definition / lint_biz_dataset_definitions`。Linter 检查 key/table 唯一、标识符与 schema.table 格式、策略/producer 白名单、日期/时间字段组合、维护动作存在且 target_tables 包含本表、Dagster key 非空，并禁止注册发布控制表。它不连接业务数据库，也不验证 Dagster 资产部署状态。

**“自动投影”不等于任意表零代码接入：**

1. 复用已支持的观测语义后，API 和页面无需逐表增加白名单；注册清单与固定数量测试须同步更新。
2. direct_trade_date 还依赖查询服务的 `_DIRECT_TABLES` 显式表映射；新增不同物理表必须补映射并测试，单独通过 linter 不足以证明能查询。
3. static_snapshot、turnover、published_batch 目前分别查询固定模型，不是把任意新表填入同一 query key 就能生效。
4. 增加观测策略、producer 类型或生产动作仍需独立设计与批准，不能为展示卡片伪造 Ops 维护动作。

## 3. 当前 15 张卡片与生产入口

这是 2026-09-09 静态注册清单，不是本轮数据库逐表验收。原 14 张新增卡片加成交额快照共 15 张；11 张绑定 4 个维护动作，4 张 Dagster producer 保持 Ops 只读。

下表物理对象除 `dm.equity_daily_snapshot` 外均为 `core_serving.<dataset_key>`。组顺序为数据集市 10、板块分析 20、内容关联 30、技术指标 40，表内次序与 item_order 一致。

| dataset_key | 显示名 | 分组 / item_order | producer_key |
| --- | --- | --- | --- |
| `wealth_market_turnover_snapshot` | 成交额分钟快照 | 数据集市 / 10 | `prod_core_wealth_market_turnover` |
| `equity_daily_snapshot` | 股票日线数据集市快照 | 数据集市 / 20 | `maintenance.rebuild_dm` |
| `wealth_sector_hierarchy` | 板块层级 | 板块分析 / 10 | `prod_core_wealth_sector_hierarchy` |
| `wealth_sector_heat_daily` | 每日板块热度 | 板块分析 / 20 | `maintenance.materialize_wealth_sector_heat_daily` |
| `wealth_sector_momentum_daily` | 板块动量 | 板块分析 / 30 | `maintenance.materialize_wealth_sector_analysis_daily` |
| `wealth_sector_dual_momentum_daily` | 板块双动量 | 板块分析 / 40 | `maintenance.materialize_wealth_sector_analysis_daily` |
| `wealth_sector_relative_rotation_daily` | 板块相对轮动 | 板块分析 / 50 | `maintenance.materialize_wealth_sector_analysis_daily` |
| `wealth_sector_member_breadth_daily` | 板块成员涨跌广度 | 板块分析 / 60 | `maintenance.materialize_wealth_sector_analysis_daily` |
| `wealth_sector_member_ma_breadth_daily` | 板块成员均线广度 | 板块分析 / 70 | `maintenance.materialize_wealth_sector_analysis_daily` |
| `wealth_sector_price_volume_daily` | 板块价量分析 | 板块分析 / 80 | `maintenance.materialize_wealth_sector_analysis_daily` |
| `wealth_sector_daily_insight_summary` | 板块每日洞察汇总 | 板块分析 / 90 | `maintenance.materialize_wealth_sector_analysis_daily` |
| `wealth_sector_daily_insight_item` | 板块每日洞察明细 | 板块分析 / 100 | `maintenance.materialize_wealth_sector_analysis_daily` |
| `news_stock_link` | 新闻个股关联 | 内容关联 / 10 | `maintenance.materialize_news_stock_links` |
| `equity_qfq_nineturn_daily` | 股票日线前复权神奇九转 | 技术指标 / 10 | `prod_core_stock_daily_qfq_nineturn` |
| `index_nineturn_daily` | 指数日线神奇九转 | 技术指标 / 20 | `prod_core_index_daily_nineturn` |

分组 key 为 `data_mart / sector_analysis / content_relation / technical_indicators`。不保留旧 wealth_market/财势乾坤组。`wealth_sector_analysis_publish_batch` 是八张分析表的发布控制事实，不另建可见卡片。

## 4. 五类观测与新鲜度

| observation_query_key | 实际读取 | 对应 freshness_policy_key 与日期字段 |
| --- | --- | --- |
| `wealth_turnover_ready_snapshot` | 成交额快照，仅 stock/CN_A/READY；trade_date 最早/最新边界，最新日按 built_at 取一行 | `wealth_turnover_snapshot`；trade_date / built_at，latest_observed_at 取该行 latest_trade_time |
| `direct_trade_date` | 热度、两张九转表；日期升序 LIMIT 1 与日期/观测时间降序 LIMIT 1 | `latest_completed_trade_day`；均 trade_date，热度时间列 calculated_at、九转 published_at |
| `static_snapshot` | 板块层级，取 published_at 最新一行的 code_reference_trade_date | `static_snapshot_ready`；有基准日期和发布时间即正常，不要求每日变化 |
| `maintenance_task_trace` | 数据集市快照、新闻个股关联不扫描业务表，只取维护 TaskRun 轨迹 | `maintenance_task_trace`；业务日期/观测列为空，不假定任务成功即证明某日数据完整 |
| `sector_analysis_published_batch` | 发布控制表仅 status=PUBLISHED 的最早/最新边界，最新日按 published_at 取一行 | `published_batch_trade_day`；八张卡共用 trade_date / published_at，不独立扫描八张事实表 |

五个 freshness key 进入静态、任务轨迹或统一交易日判断分支；不能把 key 数量与函数分支数量混为一谈。

### 4.1 日期、时间与状态

- 判迟时间当前直接写在 Biz 定义：成交额及九转 20:00、板块热度 21:15、八张分析卡 20:05。并非运行时自动继承 action readiness；以后调整任一方须同时核对，本文不改配置。
- 使用 Asia/Shanghai 和 settings.default_exchange 的交易日历。当天开市且到判迟时间取当天；未到取上一开市日。当天不开市或当天日历行缺失时查最近开市日；完全得不到期望日期才未知。
- 无业务数据为 unknown；日期达到期望为 healthy/fresh；落后 1 个开市日为 warning/lagging，超过 1 日为 stale/stale。
- 当前 `_trading_day_lag` 优先统计开市日，计数为 0 时仍退回自然日差。这是现有兜底，不应写成“日历任何缺失都未知、绝不使用自然日”；是否改造另行决定。
- Task trace 用 success 与 failed/partial_success 的最近时间比较，失败更新则 failed、有成功则 healthy、无记录则 unknown；时间采用 ended_at，缺失时回退 started_at/requested_at。Canceled 不计为失败。
- 业务观测异常优先 unknown；否则活动 maintenance TaskRun 可把卡片 status 覆盖为 running，freshness_status 仍保留底层判定。直接业务观测卡片不以历史 TaskRun 失败覆盖已就绪事实。

### 4.2 查询范围、缓存与失败隔离

`list_cards()` 先对全部定义排序/lint，读取维护动作运行摘要，再完成观测与建卡，最后按 limit 截取返回；limit 不缩减前面的全部查询工作。total 是完整卡片数。

仅有**单请求内 observation_cache**，没有跨请求/进程级缓存。八张分析卡共享一次发布观测（最早/最新各一条 SQL），不等于整个请求只发一条 SQL；交易日历、新鲜度和任务查询另算。

业务观测在 `session.begin_nested()` 内执行；异常回滚该 savepoint，记录日志并返回 unknown。同一个发布观测失败会影响共享它的八张卡。注册/lint、TaskRun/schedule 聚合和后续日历查询不在这层保护内，异常仍可能让整个请求失败；不能承诺“任意查询失败都只影响一张卡片”。

性能边界保留：禁止页面轮询对大业务表 count(*) 或无索引全表扫描；当前不再计算成交额行数，只查边界，交易日历计数不属于大业务表 count。现有 SQL 形态与索引声明不证明生产计划/延迟已验收，须在真实部署验收中核实。不得为了满足文档新增缓存、索引或迁移。

### 4.3 成交额卡片不等于行情页完整性

当前卡片不按 freq 过滤，读取所有 READY 频率中的最新日及该日最新构建行；它不证明五个频率全部完成，也不证明行情页消费的特定频率已就绪。不得用独立 MAX(built_at/latest_trade_time) 拼出一条不存在的最新业务事实。

一期历史记录（2026-06-24）：构建 CLI 不传 freq 时覆盖 1/5/15/30/60 五套同频分钟聚合；行情页累计曲线默认取 30 分钟 READY 快照，今日/昨日/均值/历史成交额来自日线聚合。此生产/消费背景保留用于解释“卡片健康不等于行情所有模块完整”，本次不把它升级为重新审计过的现行行情契约，也不重跑构建。

## 5. 动作、任务与页面

- 维护动作卡片的 type/key 成对返回：仅当 producer 是 maintenance_action 且 action.manual_enabled，才给 `primary_action_type=maintenance_action` 与动作 key。Dagster producer 两者为空，Ops 卡片只读不等于该数据不能由原生产链维护。
- TaskRun 按 `task_type=maintenance_action` 与 `request_payload_json.target_key` 关联，不按 resource_key 猜；活动状态取 queued/running/canceling，按 requested_at/id 最新一条，开始时间取 started_at 或 requested_at。
- 成功/失败聚合当前对全部登记的 maintenance action keys 执行，不仅为两张 task-trace 卡执行。直接 schedule 也按 maintenance_action + target_key 汇总，不展开 workflow。
- Schedule 总数来自匹配行；启用数只统计 active，取启用行最早 next_run_at。有启用为 active，只有非启用记录为 paused，无配置为 none；不复制或重建现有自动任务。
- 八张分析表复用同一 action 的 runtime 摘要，不创建八份配置。Biz 卡片 probe_total/probe_active 为 0，不接入 Dagster 运行状态。
- 当前后端先按 group_order、item_order、dataset_key 排卡，外层按 group_order/group_label 排组；页面按 API 顺序 map，不再按中文名重排。
- 页面每 5 秒请求卡片。Biz 有 type/key 时健康状态下也显示“去操作”，外部数据集仍仅非健康状态显示；链接必须携带服务端动作类型与 key。
- 自动任务文案区分 active 的“自动”、paused 的“自动已暂停”、无配置但可维护的“未配置自动更新”、无动作的“只读展示”。保留加载、错误、空列表处理。

## 6. 新增与改动时的回归入口

| 范围 | 代码/测试与核验要求 |
| --- | --- |
| 静态定义 | `tests/architecture/test_ops_biz_dataset_definition_guardrails.py`：15 key/table、4 组、11 维护绑定、控制表排除、错误定义与旧实现禁回流 |
| 查询与状态 | `tests/web/test_ops_biz_table_cards_api.py`：最新日对应时间、PUBLISHED、轨迹/直接 schedule、相关观测错误隔离、turnover 无 count |
| 外部卡片 | `tests/web/test_ops_dataset_cards_api.py`：Tushare/Biying 分流及 dataset_action 类型，不被 Biz 修改影响 |
| 页面消费 | `frontend/src/pages/ops-v21-source-page.tsx` 及同名测试：分组、顺序、11/4 入口、自动/暂停/未配置/只读与轮询 |

现有定向测试不等于完整覆盖所有旧 LLD 设计用例；生产 SQL 计划、共享查询错误和日历缺口仍需按实际改动补验。新增定义须更新固定集合测试，不能为通过测试删除原卡片；linter、表映射及真实查询缺一不可。

纯文档变更只运行完整性、引用、字段/清单静态对账与 git diff 检查。后续代码变更使用既有环境做定向回归，未经授权不安装依赖，不直接运行可能同步环境的命令。

## 7. 历史收口与尚待核实的部署验收

2026-05-10 一期只读卡片、2026-06-24 构建/消费解释、2026-09-05 自动投影开发记录保留为历史；旧“还要添加 primary_action_type”“Biz 查询只支持一张表”的施工步骤不再是当前待办。

2026-09-05 原记录为代码开发完成、部署/生产数据/页面验收待完成；本次未查询生产，不能据当前代码判定已发布。后续先核实是否已有独立验收，再决定是否需要部署，保留以下清单：

1. 后端/前端同版本，默认 limit 足够时返回 15 张卡片、四组、准确顺序，控制表不展示；limit 较小时 total 与返回量区分正确。
2. 11 张可维护卡片跳转正确且直接自动任务摘要可读，4 张只读卡片不出现伪入口；八张共享维护动作不重复配置。
3. 核实 READY/PUBLISHED/静态/任务轨迹各类真实样本与页面，空数据、异常和失败有明确解释。
4. 核实在线查询开销及索引计划，不因五秒轮询反复扫描大表；界定单卡错误与整体请求错误。
5. 不新增 DDL/DML、数据迁移、重算或 snapshot 刷新。Biz 不依赖 ops.dataset_status_snapshot，但这不改变外部 freshness 对该现行状态投影的使用。
6. 不改历史 TaskRun、schedule 或生产者配置；展示已有维护能力不授权触发它们。

本次文档治理不解决 §2/4 所列代码局限，也不自动把它们升级为新的开发任务。
