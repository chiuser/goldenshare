# 前端 Ops 事实字段消费审计 v1

更新时间：2026-04-26

## 1. 目的

本文件记录前端 Ops 页面是否仍在自行拼装后端已经定义好的事实字段。

本轮目标不是做视觉优化，也不是重构后端 API；只处理一件事：

前端页面只能消费稳定 API 返回的权威字段，不允许为了展示方便在页面层重新推导状态、时间、表名、来源或层级快照。

## 2. 本轮边界

范围：

1. `frontend/src/pages/**`
2. `frontend/src/shared/api/types.ts`
3. 与前端规则检查相关的 `frontend/scripts/check-rules.mjs`

不做：

1. 不改后端查询服务和数据库表。
2. 不新增状态表、字段或影子模型。
3. 不改页面视觉结构。
4. 不把总览页跨来源合并逻辑临时改成另一套前端拼法。

## 3. 权威来源

| 展示事实 | 前端应消费的权威来源 | 说明 |
| --- | --- | --- |
| 数据集名称 | `/api/v1/ops/freshness` 或 `/api/v1/ops/pipeline-modes` 的 `display_name` | 页面只做展示，不再根据 key 拼中文名。 |
| 数据集 freshness 状态 | `/api/v1/ops/freshness` 的 `freshness_status` | 页面可以映射颜色和中文标签，但不能重新计算新鲜度。 |
| 最近同步日期 | `/api/v1/ops/freshness` 的 `last_sync_date` | `latest_success_at` 是任务成功时间，`last_sync_date` 是服务端给出的同步日期口径。 |
| 最近成功时间 | `/api/v1/ops/freshness.latest_success_at` 或 layer snapshot 的 `last_success_at` | 用于时间戳展示时可以优先显示更精确的成功时间，但不能忽略 `last_sync_date`。 |
| layer 状态 | `/api/v1/ops/layer-snapshots/latest` | 页面不得用 freshness 伪造 raw/serving/std/resolution/light 快照。 |
| raw 表名 | `/api/v1/ops/freshness.raw_table` 或 `/api/v1/ops/pipeline-modes.raw_table` | 页面不得根据 `sourceKey + dataset_key` 拼表名。 |
| 任务运行状态 | `/api/v1/ops/task-runs*` | 页面不得回退到旧 execution/steps/events/logs 拼装任务状态。 |

## 4. 已确认并修复的问题

| 编号 | 页面/文件 | 问题 | 处理 |
| --- | --- | --- | --- |
| F-001 | `ops-v21-source-page.tsx` | “最近同步”只看 `freshItem.latest_success_at || rawLatest.last_success_at`，没有消费服务端 `last_sync_date`，导致 `limit_list_ths` 显示 `—`。 | 已修复：显示顺序调整为 `latest_success_at -> raw.last_success_at -> last_sync_date -> —`，并补回归测试。 |
| F-002 | `ops-v21-dataset-detail-page.tsx` | 没有 layer snapshot 时，页面用 freshness 自行构造 raw/serving 两条假 snapshot。 | 已删除：详情页只展示 layer snapshot API 返回的真实层级状态。 |
| F-003 | `ops-v21-shared.ts` | 保留了未使用的 `groupDatasetSummariesWithFreshnessFallback()`，会把 freshness 转成 synthetic snapshot。 | 已删除：共享文件只保留当前仍被使用的 display name 映射。 |
| F-004 | `ops-v21-source-page.tsx` | 页面用 `sourceKey + dataset_key` 拼 raw 表名，并把 `raw_tushare` 替换成当前来源表名前缀。 | 已删除：表名只来自 freshness 或 pipeline mode 返回字段，缺失则显示 `—`。 |

## 5. 已加门禁

`frontend/scripts/check-rules.mjs` 新增两条规则：

1. 禁止页面层重新引入 freshness -> layer snapshot 的伪造逻辑。
2. 禁止页面层重新引入 raw 表名派生变量。

这两条规则不是为了覆盖所有未来场景，而是先锁死本轮已经确认的旧口径回流点。

## 6. 仍需后续 API 收口的问题

| 编号 | 页面/文件 | 现状 | 后续方向 |
| --- | --- | --- | --- |
| G-001 | `ops-v21-overview-page.tsx` | 总览页仍在前端合并 `pipeline-modes` 与 `layer-snapshots`，并根据 `dataset_key/raw_table/source_scope` 推断来源、合并多源卡片。 | 应由后端提供面向页面的 dataset card view，包含 `card_key/source_groups/stage_statuses/latest_business_date/status_updated_at` 等字段。 |
| G-002 | `ops-v21-source-page-utils.ts` | 数据源页 dedupe 仍用 `dataset_key/raw_table/source_scope` 做来源偏好评分。 | 应由后端直接返回当前 source 下已经去重后的卡片列表，前端不再自己做来源裁决。 |
| G-003 | `ops-v21-overview-page.tsx` | 仍展示 `legacy_core_direct` 这类历史模式文案。 | 如果后端仍返回该模式，应先在后端契约层完成当前模式枚举收口，再改页面展示。 |
| G-004 | `ops-v21-task-auto-tab.tsx` | 自动任务页仍暴露 `spec_type/spec_key` 选择模型，属于后续自动任务页专项。 | 等自动任务页重做时，切到用户视角的维护对象与触发策略，不让用户理解底层 spec。 |

## 7. 后续执行原则

1. 前端能直接消费权威字段的，直接修。
2. 没有权威字段的，不允许继续在页面层拼；先登记为 API 契约缺口。
3. 每修一个旧消费点，必须补一个最小回归测试或规则门禁。
4. 任何“看起来能根据 key 推出来”的字段，都不能当事实字段使用。
