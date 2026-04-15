# Ops 数据集模式与层级观测补齐方案 v1

更新时间：2026-04-15  
适用范围：`src/ops/*`、`src/operations/*`、`src/platform/*`  
目标：在不强制物化 std 的前提下，完整表达“单源直出 / 多源实体流程 / 仅采集”三类数据集运行模式，并在 Ops 可视化中可查询、可追溯。

---

## 1. 背景与约束

当前系统在数据面采用“单源阶段优先直出 `core_serving`”策略，以节省存储和同步成本；控制面保留 std / resolution 规则对象，便于未来扩展多源融合。

现实状态：
1. `stock_basic` 已落地 `raw -> std -> resolution -> serving`。
2. 大多数数据集为 `raw_tushare -> core_serving` 单源直出。
3. 少量数据集为 `raw-only`（例如 `biying_equity_daily`）。

问题：
1. Ops 无统一“模式对象”，页面无法明确显示每个数据集当前处于哪种模式。
2. `dataset_layer_snapshot_history` 只有历史，没有“当前层级快照”读模型，页面聚合复杂且易慢。

---

## 2. 本轮目标（v1）

### 2.1 必做

1. 新增 `ops.dataset_pipeline_mode`：记录每个数据集的配置模式与层级开关。
2. 新增 `ops.dataset_layer_snapshot_current`：记录每个数据集/来源/层级的当前状态。
3. 提供 seed 命令：根据现有 freshness spec 自动回填默认模式。
4. 提供查询接口：返回“数据集模式 + 层级关系 + 当前状态 + 规则配置状态”。

### 2.2 暂不做（留待 v2）

1. 所有数据集统一进入实体 std 物化。
2. 模式切换开关触发自动重算执行器。
3. 前端全面重构（先补后端契约）。

---

## 3. 数据模型设计

## 3.1 `ops.dataset_pipeline_mode`

主键：`dataset_key`

字段：
- `dataset_key`：数据集 key
- `mode`：`single_source_direct | multi_source_pipeline | raw_only | legacy_core_direct`
- `source_scope`：`tushare | biying | tushare,biying | custom`
- `raw_enabled`：是否启用 raw 层
- `std_enabled`：是否启用 std 层
- `resolution_enabled`：是否启用 resolution 层
- `serving_enabled`：是否启用 serving 层
- `notes`：说明（例如“保留在 core 的中间表”）
- `created_at` / `updated_at`

说明：
- `legacy_core_direct` 用于仍在 `core.*` 的历史例外数据集（例如 `equity_adj_factor`）。

## 3.2 `ops.dataset_layer_snapshot_current`

主键：`(dataset_key, source_key, stage)`

字段：
- `dataset_key`
- `source_key`（无来源维度时写 `__all__`）
- `stage`：`raw | std | resolution | serving`
- `status`：`fresh | lagging | stale | failed | unknown | skipped`
- `rows_in` / `rows_out`
- `error_count`
- `last_success_at` / `last_failure_at`
- `lag_seconds`
- `message`
- `calculated_at`

说明：
- `skipped` 由模式推导得出（例如单源直出时，std/resolution 默认为 skipped）。

---

## 4. 默认模式推导规则（seed）

基于 `DatasetFreshnessSpec`：

1. `dataset_key == stock_basic`  
   -> `multi_source_pipeline`，`source_scope=tushare,biying`，四层全开。

2. `target_table` 以 `raw_` 开头  
   -> `raw_only`，仅 `raw_enabled=true`。

3. `target_table` 以 `core_serving.` 开头  
   -> `single_source_direct`，`raw+serving` 开，`std+resolution` 关。

4. 其他（当前在 `core.*`）  
   -> `legacy_core_direct`，保守标记。

---

## 5. 查询接口契约（v1）

新增接口：`GET /api/v1/ops/pipeline-modes`

返回项：
- 数据集基础：`dataset_key`、`display_name`、`domain_key`
- 模式信息：`mode`、`source_scope`、`layer_plan`
- 层级关系：`raw_table`、`std_table_hint`、`serving_table`
- 当前状态：`freshness_status`、`latest_business_date`
- 规则状态：`std_mapping_configured`、`std_cleansing_configured`、`resolution_policy_configured`

`layer_plan` 示例：
- `raw->serving`
- `raw->std->resolution->serving`
- `raw-only`

---

## 6. 实施步骤

1. 新增两张 ops 表 + Alembic 迁移。
2. 新增 PipelineMode seed service + CLI 命令。
3. 新增 pipeline 模式查询 service / schema / API。
4. 在 snapshot 刷新时同步更新 `dataset_layer_snapshot_current` 的 serving 层记录。
5. 增加单测（seed 推导 + 查询返回）。

---

## 7. 验收标准

1. 可通过 CLI 一次性回填全量数据集模式。
2. `/api/v1/ops/pipeline-modes` 能正确区分 `stock_basic` 与普通单源直出数据集。
3. `ops.dataset_layer_snapshot_current` 有 serving 当前记录。
4. 不影响现有 freshness / source-management 接口行为。

