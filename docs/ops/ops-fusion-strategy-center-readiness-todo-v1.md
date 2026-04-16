# 融合策略中心开发准备度与待办清单 v1

更新时间：2026-04-16  
适用范围：`src/ops/*`、`src/foundation/*`、`frontend/src/pages/*`（Ops V2.1 相关）

---

## 1. 目标

记录“融合策略中心”当前真实落地状态，明确：

1. 现在能做什么（已具备能力）  
2. 现在不能做什么（缺口）  
3. 后续开发顺序（TODO）

本清单用于后续排期，不在本轮立即实现。

---

## 2. 当前结论（是否具备开发条件）

结论：**具备开发条件（可开工），但不具备完整交付条件（不可直接作为最终版上线）。**

原因：底层对象与查询 API 已有基础能力，但“融合策略中心”缺独立入口页与完整策略对象工作区。

---

## 3. 已具备能力（代码已存在）

### 3.1 规则与发布对象 API（可用）

1. std 规则 API（mapping + cleansing）  
- `src/ops/api/std_rules.py`

2. release 对象 API（list/create/detail/status/stages）  
- `src/ops/api/resolution_releases.py`

3. pipeline mode API（模式可见性）  
- `src/ops/api/dataset_pipeline_modes.py`

4. source bridge 聚合 API（桥接看板）  
- `src/ops/api/source_management_bridge.py`

### 3.2 层级观测数据模型（可用）

1. latest 快照表：  
- `src/ops/models/ops/dataset_layer_snapshot_current.py`

2. history 快照表：  
- `src/ops/models/ops/dataset_layer_snapshot_history.py`

3. 查询服务：  
- `src/ops/queries/layer_snapshot_query_service.py`

### 3.3 融合引擎基础能力（Foundation）

1. 策略读取：  
- `src/foundation/resolution/policy_store.py`

2. 策略执行：  
- `src/foundation/resolution/policy_engine.py`

3. serving 发布：  
- `src/foundation/serving/publish_service.py`

4. 已验证走融合发布的数据集：`stock_basic`  
- `src/foundation/services/sync/sync_stock_basic_service.py`

### 3.4 测试基础（已覆盖）

1. std 规则 API 测试  
- `tests/web/test_ops_std_rules_api.py`

2. release API 测试  
- `tests/web/test_ops_resolution_release_api.py`

3. pipeline mode API 测试  
- `tests/web/test_ops_pipeline_modes_api.py`

4. bridge API 测试  
- `tests/web/test_ops_source_management_bridge_api.py`

---

## 4. 当前缺口（导致“未完整可交付”）

### 4.1 前端入口缺失

`OpsShell` 中“融合策略中心”仍为禁用占位文案：  
- `frontend/src/app/shell.tsx`

当前路由未提供融合策略中心独立页面（仅有总览/数据源/任务中心/详情页）：  
- `frontend/src/app/router.tsx`

### 4.2 缺“策略对象工作区”页面

目前只有规则与发布数据的展示能力，没有完整的“策略对象管理工作流”（草稿、版本、diff、发布前预览）的独立 UI 工作区。

### 4.3 发布动作尚未形成“通用数据集”执行闭环

release 对象已可写入与状态流转，但“发布 -> 执行 -> 回写 stage 状态 -> 与数据集联动”的通用闭环尚未在全部数据集统一落地；目前主要在 `stock_basic` 具备可运行链路。

---

## 5. 待办清单（TODO）

## 5.1 P0：开页面但不改旧流程

1. 新增融合策略中心路由与菜单入口（V2.1 新页面，不替换旧页）  
2. 页面先接“只读真实数据”：  
- pipeline modes  
- std mapping/cleansing  
- release 列表与 stage 状态  
- layer latest/history

验收：页面可打开、无 mock、可筛选数据集。

## 5.2 P0：策略对象管理最小闭环（MVP）

1. 明确“策略对象”与“发布对象”职责边界（策略声明 vs 发布执行）。  
2. 提供策略对象的最小 CRUD 与版本管理入口。  
3. 支持“从当前策略复制为 draft”与“查看版本差异（先字段级）”。

验收：可以完成“编辑策略草稿 -> 保存版本 -> 发起发布对象”。

## 5.3 P1：发布执行可观测闭环

1. 发布动作触发后，统一写 release stage 状态（raw/std/resolution/serving）。  
2. 统一把 release 与 execution 关联展示（至少 execution_id 可追踪）。  
3. 数据集详情页展示“当前策略版本 + 最近发布结果 + stage 明细”。

验收：从数据集详情能追溯到最近发布与执行结果。

## 5.4 P1：测试补齐

1. 策略对象 CRUD + 版本流测试。  
2. 发布闭环集成测试（创建 release -> 写 stages -> 页面查询一致）。  
3. 前端关键查询契约测试（至少路由打开 + 数据渲染 smoke case）。

---

## 6. 非本轮范围（明确不做）

1. 不在本轮做“全部数据集的多源融合物化”。  
2. 不在本轮改旧版页面 IA 与旧流程。  
3. 不在本轮引入复杂自动回滚编排（仅先保留对象与状态位）。

---

## 7. 启动条件（后续开工前检查）

满足以下三项即可进入融合策略中心编码：

1. `ops` 相关表已迁移并可读写（release/std-rule/pipeline/layer snapshot）  
2. `stock_basic` 链路保持可运行（作为回归基线）  
3. 旧页面仍可正常处理手动/自动任务（避免迁移期阻断）

---

## 8. 备注

本清单是当前阶段的“工程现实基线”，后续每完成一项 TODO 应同步更新状态，避免文档与代码再度脱节。
