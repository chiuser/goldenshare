# 前端 Ops 事实字段消费审计 v1

更新时间：2026-04-26

## 1. 目的

本文件记录前端 Ops 页面是否仍在自行拼装后端已经定义好的事实字段。

本轮目标不是做视觉优化；只处理一件事：

前端页面只能消费稳定 API 返回的权威字段，不允许为了展示方便在页面层重新推导状态、时间、表名、来源或层级快照。

## 2. 本轮边界

范围：

1. `frontend/src/pages/**`
2. `frontend/src/shared/api/types.ts`
3. `src/ops/api/**`、`src/ops/queries/**`、`src/ops/schemas/**` 中面向页面的只读聚合接口
4. 与前端规则检查相关的 `frontend/scripts/check-rules.mjs`

不做：

1. 不新增状态表、字段或影子模型。
2. 不改页面视觉结构。
3. 不把总览页跨来源合并逻辑临时改成另一套前端拼法。
4. 不触碰自动任务页的交互模型，自动任务页另行专项处理。

## 3. 权威来源

| 展示事实 | 前端应消费的权威来源 | 说明 |
| --- | --- | --- |
| 数据集卡片名称 | `/api/v1/ops/dataset-cards` 的 `display_name` | 总览页、数据源页只做展示，不再根据 key 拼中文名。 |
| 数据集卡片状态 | `/api/v1/ops/dataset-cards` 的 `status/freshness_status` | 页面可以映射颜色和中文标签，但不能重新计算新鲜度或层级健康度。 |
| 最近同步日期 | `/api/v1/ops/dataset-cards` 的 `last_sync_date` | `latest_success_at` 是任务成功时间，`last_sync_date` 是服务端给出的同步日期口径。 |
| 最近成功时间 | `/api/v1/ops/dataset-cards` 的 `latest_success_at` | 用于时间戳展示时可以优先显示更精确的成功时间，但不能忽略 `last_sync_date`。 |
| layer 状态 | `/api/v1/ops/dataset-cards` 的 `stage_statuses/raw_sources` | 总览页、数据源页不得直接拼 layer snapshot；详情页仍直接消费 `/api/v1/ops/layer-snapshots/latest` 的真实快照。 |
| raw 表名 | `/api/v1/ops/dataset-cards` 的 `raw_table/raw_table_label/raw_sources[].table_name` | 页面不得根据 `sourceKey + dataset_key` 拼表名。 |
| 数据源裁决与卡片去重 | `/api/v1/ops/dataset-cards?source_key=...` 返回的结果 | 页面不得用 `dataset_key/raw_table/source_scope` 自己判断某卡片属于哪个数据源。 |
| 任务运行状态 | `/api/v1/ops/task-runs*` | 页面不得回退到旧 execution/steps/events/logs 拼装任务状态。 |

## 4. 已确认并修复的问题

| 编号 | 页面/文件 | 问题 | 处理 |
| --- | --- | --- | --- |
| F-001 | `ops-v21-source-page.tsx` | “最近同步”只看 `freshItem.latest_success_at || rawLatest.last_success_at`，没有消费服务端 `last_sync_date`，导致 `limit_list_ths` 显示 `—`。 | 已修复：显示顺序调整为 `latest_success_at -> raw.last_success_at -> last_sync_date -> —`，并补回归测试。 |
| F-002 | `ops-v21-dataset-detail-page.tsx` | 没有 layer snapshot 时，页面用 freshness 自行构造 raw/serving 两条假 snapshot。 | 已删除：详情页只展示 layer snapshot API 返回的真实层级状态。 |
| F-003 | `ops-v21-shared.ts` | 保留了未使用的 `groupDatasetSummariesWithFreshnessFallback()`，会把 freshness 转成 synthetic snapshot。 | 已删除：共享文件只保留当前仍被使用的 display name 映射。 |
| F-004 | `ops-v21-source-page.tsx` | 页面用 `sourceKey + dataset_key` 拼 raw 表名，并把 `raw_tushare` 替换成当前来源表名前缀。 | 已删除：表名只来自 `/api/v1/ops/dataset-cards` 返回字段，缺失则显示 `—`。 |
| F-005 | `ops-v21-overview-page.tsx` | 总览页直接合并 `pipeline-modes` 与 `layer-snapshots`，在页面层推导 stage、raw_sources、status。 | 已收口：总览页改为消费 `/api/v1/ops/dataset-cards`。 |
| F-006 | `ops-v21-source-page.tsx` / `ops-v21-source-page-utils.ts` | 数据源页用 `dataset_key/raw_table/source_scope` 做来源偏好评分和去重。 | 已收口：数据源页改为消费 `/api/v1/ops/dataset-cards?source_key=...`，旧 utils 删除。 |
| F-007 | `src/ops/api/dataset_cards.py` | 总览页、数据源页缺少稳定卡片视图，只能在前端拼。 | 已新增只读卡片视图 API；不新增状态表，不复制落盘字段。 |
| F-008 | `src/ops/queries/dataset_card_query_service.py` | 卡片视图内部仍把 `pipeline-modes` 查询结果当作静态事实来源。 | 已收口：卡片静态事实从 `DatasetDefinition` 派生，freshness/layer/probe 只作为运行观测输入。 |

## 5. 已加门禁

`frontend/scripts/check-rules.mjs` 已新增三条规则：

1. 禁止页面层重新引入 freshness -> layer snapshot 的伪造逻辑。
2. 禁止页面层重新引入 raw 表名派生变量。
3. 禁止页面层重新引入数据集卡片来源、canonical key 或 raw snapshot 合并推断。

这些规则不是为了覆盖所有未来场景，而是先锁死本轮已经确认的旧口径回流点。

## 6. 仍需后续 API 收口的问题

| 编号 | 页面/文件 | 现状 | 后续方向 |
| --- | --- | --- | --- |
| G-001 | `ops-v21-task-auto-tab.tsx` | 已切到 `target_type/target_key` 调度目标模型，页面显示继续使用后端结构化名称。 | 后续重做自动任务页交互时，继续从用户视角表达维护对象与触发策略，不恢复旧执行规格。 |
| G-002 | Ops 后端卡片视图 | `/api/v1/ops/dataset-cards` 的卡片静态事实已从 DatasetDefinition 派生；旧 `pipeline-modes` API 与 `dataset_pipeline_mode` 主实现已下线。 | 后续如果页面还需要 pipeline/stage 新字段，先补 DatasetDefinition 派生事实，再暴露到 card view，不能让页面或查询层另起事实口径。 |

## 7. 后续执行原则

1. 前端能直接消费权威字段的，直接修。
2. 没有权威字段的，不允许继续在页面层拼；先登记为 API 契约缺口。
3. 每修一个旧消费点，必须补一个最小回归测试或规则门禁。
4. 任何“看起来能根据 key 推出来”的字段，都不能当事实字段使用。
