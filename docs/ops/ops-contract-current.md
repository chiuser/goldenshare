# Ops 当前契约（统一版）

更新时间：2026-04-19  
适用范围：`src/ops/*`、`src/app/*`、`src/foundation/*`（Ops 相关）

---

## 1. 目的

本文件是 Ops 领域的**单一事实文档**，统一收口以下历史内容：

1. 多源运维契约（页面与对象边界）
2. Source 管理桥接契约
3. 数据集 pipeline mode 与层级观测契约
4. 数据集停用策略（`disabled` 状态语义）
5. 融合策略中心准备度与上线前置条件

历史分散文档已下线，后续仅维护本文件。

---

## 2. 信息架构（当前）

### 2.1 数据状态总览

目标：按数据集查看 `raw/std/resolution/serving` 状态与风险分级。  
要求：

1. 卡片点击进入数据集详情
2. “去处理”跳转任务中心并携带上下文
3. 支持显示模式标识（单源直出/多源流程/raw-only）

### 2.2 数据源管理

目标：按 source 维度查看上游可用性与失败情况。  
边界：

1. 只关注 source 与 raw 层状态
2. 不承载策略编辑逻辑
3. 不承载复杂发布流程

### 2.3 任务中心

目标：统一承接手动同步、自动调度、任务记录。  
要求：

1. 调度支持 cron/probe
2. 任务详情可追踪层级进度与错误摘要
3. 保持与 `job_execution` 体系一致

### 2.4 审查中心

目标：只读审查视图（指数、板块等领域）。  
边界：

1. 一期只读，不做写操作
2. 按领域组织路由，避免按技术对象暴露

---

## 3. 核心对象模型

### 3.1 `ops.dataset_pipeline_mode`

主键：`dataset_key`  
用途：定义数据集当前运行模式与启用层级。

关键字段：

1. `mode`：`single_source_direct | multi_source_pipeline | raw_only | legacy_core_direct`
2. `source_scope`
3. `raw_enabled/std_enabled/resolution_enabled/serving_enabled`
4. `notes`

### 3.2 `ops.dataset_layer_snapshot_current`

主键：`(dataset_key, source_key, stage)`  
用途：作为 Ops 页面“当前层级状态”读模型。

关键字段：

1. `status`：`fresh | lagging | stale | failed | unknown | skipped`
2. `rows_in/rows_out/error_count`
3. `last_success_at/last_failure_at`
4. `lag_seconds/message/calculated_at`

状态语义约束：

1. `fresh/lagging/stale/failed`：健康度核心状态
2. `skipped`：该层在当前 mode 下未启用
3. `unknown`：数据缺失或不可判定（异常态，不应长期存在）
4. `disabled`：数据集停用（保留执行链路，但从健康度告警口径排除）

### 3.3 相关运行对象

1. `ops.job_execution*`：执行生命周期与进度
2. `ops.job_schedule`：调度对象
3. `ops.probe_rule`：探测触发规则

---

## 4. 查询与桥接契约

### 4.1 推荐主查询接口

1. `GET /api/v1/ops/pipeline-modes`
2. `GET /api/v1/ops/layer-snapshots/latest`
3. `GET /api/v1/ops/freshness`

### 4.2 Source 管理桥接

接口：`GET /api/v1/ops/source-management/bridge`  
定位：过渡期聚合接口，供 Source 页面低成本读取多对象快照。

聚合内容：

1. `summary`
2. `probe_rules`
3. `releases`
4. `std_mapping_rules`
5. `std_cleansing_rules`
6. `layer_latest`

约束：

1. 桥接层仅做只读聚合，不承载业务计算
2. 新页面稳定后可逐步收缩桥接层

---

## 5. 模式推导与默认策略

默认推导（seed）：

1. `stock_basic`：`multi_source_pipeline`
2. `target_table` 以 `raw_` 开头：`raw_only`
3. `target_table` 以 `core_serving.` 开头：`single_source_direct`
4. 其他历史口径：`legacy_core_direct`

---

## 6. 运维规则（必须遵守）

1. 页面口径优先读取统一读模型，不在前端临时拼装状态
2. 模式与层级状态必须可追溯（pipeline mode + layer snapshot）
3. 新增数据集必须接入 Ops 可观测能力，不允许“只落表不可见”
4. 页面文案优先业务语义，不暴露底层字段实现细节
5. `disabled` 数据集可见但不计入滞后/失败告警统计
6. 停用能力当前为代码级控制，后续应收敛到配置化控制表

---

## 7. 数据集停用策略（当前口径）

目标：

1. 保留同步能力（手动/自动任务仍可执行）
2. 从健康度重点告警中剔除停用数据集
3. 在总览和详情明确展示“已停用”

当前实现边界：

1. 停用名单由代码常量维护（非数据库配置）
2. 仅影响观测与展示口径，不影响执行能力
3. 前端不提供启停开关

后续演进（目标态）：

1. 引入 `ops.dataset_control`（`dataset_key/is_disabled/reason/updated_at`）
2. 新鲜度计算读取控制表覆盖状态
3. 接入审计记录与权限控制

---

## 8. 融合策略中心准备度（当前）

当前结论：

1. 已具备开发条件（底层对象齐备）
2. 未具备完整交付条件（页面工作区与发布闭环仍需补齐）

已具备能力：

1. std 规则 API：`/api/v1/ops/std-rules/*`
2. release 对象 API：`/api/v1/ops/resolution-releases/*`
3. pipeline mode API：`/api/v1/ops/pipeline-modes`
4. source bridge API：`/api/v1/ops/source-management/bridge`
5. 层级快照模型：`dataset_layer_snapshot_current/history`
6. Foundation 融合引擎：`policy_store/policy_engine/publish_service`
7. 可运行回归基线：`stock_basic`

当前缺口：

1. 融合策略中心独立页面入口与工作区仍缺失
2. 策略对象管理（草稿/版本/diff）尚未形成完整 UI 闭环
3. 发布执行到 `execution/stage` 的通用闭环尚未覆盖全部数据集

优先待办（按优先级）：

1. P0：先开只读页面（pipeline/rules/releases/layers）
2. P0：补最小策略对象管理闭环（草稿、版本、差异）
3. P1：补发布执行可观测闭环（release -> execution -> stages）
4. P1：补全前后端测试基线

---

## 9. Ops 专题文档边界

以下文档保留为专题补充，不再重复定义主契约：

1. `ops-workflow-catalog-v1.md`：工作流目录与实现清单
2. `ops-review-center-design-v1.md`：审查中心设计
3. `reconcile-capability-requirements-v1.md`：多源对账专项

---

## 10. 验收基线

1. 能查询每个数据集的 `mode + layer_plan + latest status`
2. 数据状态总览与数据源管理展示口径一致
3. 任务中心可查看执行记录并定位失败原因
4. 审查中心可按领域展示只读审查数据
5. 停用数据集在页面可见且不计入重点告警
6. 融合策略中心具备从对象到执行的可观测闭环后再进入正式上线
