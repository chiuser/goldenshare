# `cadence` 退场清单 v1

状态：待执行  
更新时间：2026-05-05  
适用范围：`DatasetDefinition.domain.cadence`、Ops freshness/status/card 链路、前端数据源页与相关 API 契约。

---

## 1. 背景

当前代码中，`cadence` 仍作为一个“数据更新节奏标签”在多条 Ops 观测链路中流转，但它已经不再适合作为核心事实字段：

1. 对用户价值很低。用户真正关心的是维护对象、时间口径、最近同步到哪一天、是否滞后，而不是“每日 / 快照 / 低频”这类抽象节奏标签。
2. 与 `date_model` 职责重叠。真正决定 freshness、expected business date、审计适用性的，应该是 `date_model`，不是 `cadence`。
3. 语义容易误导。`low_frequency` 这类取值既不稳定，也容易和“事件型数据”“快照主数据”混在一起。
4. 当前仍存在旧依赖残留，导致它不是一个可直接忽略的字段。

本清单的目标是：在不影响当前 5 个新数据集接入推进的前提下，为后续彻底退场 `cadence` 提供一份明确的实施顺序与门禁清单。

---

## 2. 当前传播链

### 2.1 定义层

`cadence` 当前定义在：

- [src/foundation/datasets/models.py](/Users/congming/github/goldenshare/src/foundation/datasets/models.py)

当前表现：

1. `DatasetDomain` 包含 `cadence`
2. `cadence_display_name` 由该字段派生

### 2.2 Ops 投影与读模型

当前传播到：

- [src/ops/dataset_definition_projection.py](/Users/congming/github/goldenshare/src/ops/dataset_definition_projection.py)
- [src/ops/queries/dataset_card_query_service.py](/Users/congming/github/goldenshare/src/ops/queries/dataset_card_query_service.py)
- [src/ops/queries/freshness_query_service.py](/Users/congming/github/goldenshare/src/ops/queries/freshness_query_service.py)
- [src/ops/services/operations_dataset_status_snapshot_service.py](/Users/congming/github/goldenshare/src/ops/services/operations_dataset_status_snapshot_service.py)
- [src/ops/models/ops/dataset_status_snapshot.py](/Users/congming/github/goldenshare/src/ops/models/ops/dataset_status_snapshot.py)

当前表现：

1. `DatasetFreshnessProjection` 持有 `cadence`
2. `DatasetCardFact` / `DatasetCardItem` 持有 `cadence` 与 `cadence_display_name`
3. `DatasetFreshnessItem` 持有 `cadence`
4. `ops.dataset_status_snapshot` 表持久化 `cadence`

### 2.3 前端消费

当前直接用户可见的消费点：

- [frontend/src/pages/ops-v21-source-page.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-source-page.tsx)

当前表现：

1. 数据源页展示“更新频率：每日 / 快照 / 低频 / 盘中”

### 2.4 逻辑依赖

当前仍存在的逻辑依赖：

1. freshness snapshot 与 live projection 会检查 `cadence` 是否一致；不一致时触发 live refresh。
2. freshness 仍保留基于 `cadence` 的兜底状态判断和 expected business date 兜底逻辑。
3. dataset status snapshot 会把 `cadence` 当成快照事实保存。

结论：

`cadence` 已经不是执行主链依赖，但仍是 Ops 观测链中的残留事实字段。

---

## 3. 退场目标

退场后的目标状态：

1. 用户界面不再展示 `cadence`。
2. freshness / expected business date / lag 判断只认 `date_model`，不再保留 `cadence` 兜底规则。
3. `ops.dataset_status_snapshot` 不再保存 `cadence`。
4. `DatasetCardItem`、`DatasetFreshnessItem`、相关 API 契约不再返回 `cadence`。
5. `DatasetDefinition.domain` 只保留真正有意义的底层领域信息；`cadence` 不再作为 `domain` 的组成部分。

---

## 4. 非目标

本次不做的事：

1. 不在当前 5 个新数据集集成过程中顺手推进 `cadence` 退场。
2. 不为了保留 `cadence` 再新增新表、新镜像字段或新兼容层。
3. 不把 `cadence` 替换成另一套新的“抽象节奏标签”继续回流。

---

## 5. 退场步骤

### M1. 冻结新增依赖

目标：

1. 新代码、新文档、新 API 契约不再把 `cadence` 当成必要字段。
2. 新数据集接入不再围绕 `cadence` 设计业务规则。

门禁：

1. 新增数据集文档不得把 `cadence` 作为 freshness 或审计依据。
2. 新前端页面不得新增 `cadence` 展示。

### M2. 先去掉用户可见展示

目标：

1. 数据源页不再显示“更新频率”。
2. 前端类型与测试移除 `cadence_display_name` 的用户可见依赖。

涉及链路：

- `frontend/src/pages/ops-v21-source-page.tsx`
- `frontend/src/shared/api/types.ts`
- 对应前端测试

门禁：

1. 用户界面不再出现“每日 / 快照 / 低频 / 盘中”这类 cadence 文案。
2. 去掉展示后，不影响数据源页其他卡片信息。

### M3. 去掉 freshness 逻辑兜底

目标：

1. `OpsFreshnessQueryService` 不再用 `cadence` 推导 `expected_business_date`。
2. `OpsFreshnessQueryService` 不再用 `cadence` 推导 `fresh / lagging / stale`。

替代规则：

1. 有 `date_model` 的数据集，只认 `date_model`。
2. `bucket_rule=not_applicable` 的数据集继续返回 `unknown` 或“仅最近任务迹象”，不伪造业务日期状态。
3. 不再保留 `cadence` fallback 分支。

门禁：

1. freshness 相关测试全部改为只验证 `date_model` 口径。
2. 不允许因为去掉 `cadence` fallback 而重新引入新的影子规则表。

### M4. 去掉 snapshot / API 契约残留

目标：

1. `DatasetFreshnessItem` 去掉 `cadence`
2. `DatasetCardItem` 去掉 `cadence` / `cadence_display_name`
3. `ops.dataset_status_snapshot` 去掉 `cadence` 列

涉及：

- ops schema
- snapshot service
- Alembic 迁移
- 对应 API 文档

门禁：

1. snapshot 重建后前后端功能正常。
2. 数据源页、freshness API、dataset cards API 不再输出 `cadence`。

### M5. 去掉定义层字段

目标：

1. `DatasetDomain` 删除 `cadence`
2. `cadence_display_name` 删除
3. 所有 `DatasetDefinition` 定义行不再填写 `cadence`

门禁：

1. registry、projection、schema、前端、文档均无 `cadence` 残留。
2. `rg "\\bcadence\\b" src frontend docs/tests` 只允许命中历史归档文档或退场方案说明。

---

## 6. 验证清单

实施退场时至少需要覆盖：

1. `pytest -q tests/web/test_ops_freshness_api.py`
2. `pytest -q tests/web/test_ops_overview_api.py`
3. `pytest -q tests/test_dataset_status_snapshot_service.py`
4. `pytest -q tests/architecture/test_subsystem_dependency_matrix.py`
5. `cd frontend && npm run typecheck`
6. `cd frontend && npm test -- --run src/pages/ops-v21-source-page.test.tsx`
7. `python3 scripts/check_docs_integrity.py`

按改动范围追加：

1. snapshot 迁移验证
2. docs / API reference 更新
3. `rg "\\bcadence\\b"` 残留审计

---

## 7. 推进时机

当前拍板：

1. 先完成本轮 5 个新数据集接入。
2. 接入完成后，再回头处理 `cadence` 退场。

因此本清单当前状态是：

- 已登记
- 未实施
- 后续作为 P1 治理任务单独推进

---

## 8. 关联文档

- [工程风险登记簿](/Users/congming/github/goldenshare/docs/governance/engineering-risk-register.md)
- [Ops 当前契约（统一版）](/Users/congming/github/goldenshare/docs/ops/ops-contract-current.md)
- [Ops 数据集展示目录配置方案 v1](/Users/congming/github/goldenshare/docs/ops/ops-dataset-catalog-view-plan-v1.md)
- [Ops 新鲜度按 Date Model 收口方案 v1](/Users/congming/github/goldenshare/docs/ops/ops-date-model-freshness-alignment-plan-v1.md)
