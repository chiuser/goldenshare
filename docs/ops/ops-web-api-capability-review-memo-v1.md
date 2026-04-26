# Ops Web API 与运维数据能力审查备忘 v1

更新时间：2026-04-23  
适用范围：`src/ops/*`、`src/app/api/*`、`src/app/web/*`、`frontend/src/pages/ops*`

---

## 1. 目的

本文件用于沉淀当前 `ops` Web API 与运维数据读模型的审查结论，作为后续专题讨论与 API 增强设计的统一备忘。

定位说明：

1. 本文不是实现方案，不直接定义新接口契约
2. 本文先记录“当前有哪些能力、主要缺口在哪里、后续应按什么顺序讨论”
3. 后续若要推进接口增强，应在本文基础上再产出专项设计文档

---

## 2. 审查范围

本轮已核查：

1. `src/ops/api/*` 当前暴露的 Web API
2. `src/ops/queries/*` 当前主要运维查询能力
3. `src/app/api/*` 的聚合装配方式
4. `frontend/src/pages/ops*` 对当前 API 的真实消费方式
5. `tests/web/*` 中对现有语义的测试约束

本轮未做：

1. 不修改后端实现
2. 不修改前端页面逻辑
3. 不新增接口
4. 不调整前后端契约

---

## 3. 当前总体判断

当前 `ops` API 的问题，不是“完全没有能力”，而是“能力分散、页面级聚合不足”。

当前状态可概括为：

1. API 覆盖面已经比较全，任务中心、审查中心、freshness、pipeline mode、layer snapshot、probe、release、schedule、execution 都已有接口
2. 读模型基础已经具备，其中 `freshness` 是当前最成熟、最接近“页面骨架数据”的一层
3. 现有接口更偏“对象级切片接口”，还不是“页面可直接消费的聚合读模型”
4. 前端为了做更丰富的新页面，仍需要大量并发请求和客户端重组

结论：

1. 继续扩 UI 之前，应该优先补强 `ops` 的聚合查询 API
2. 后续增强应继续落在 `src/ops/**`，不应回流到 `src/app/**` 或 legacy 目录

---

## 4. 当前已具备的主要能力

### 4.1 已有 API 面

当前 `src/ops/api/router.py` 已挂载：

1. `overview`
2. `freshness`
3. `schedules`
4. `executions`
5. `probes`
6. `resolution_releases`
7. `std_rules`
8. `layer_snapshots`
9. `source_management_bridge`
10. `runtime`
11. `catalog`
12. `dataset_pipeline_modes`
13. `review_center`

对应装配入口：

1. [src/ops/api/router.py](/Users/congming/github/goldenshare/src/ops/api/router.py)
2. [src/app/api/v1/router.py](/Users/congming/github/goldenshare/src/app/api/v1/router.py)

### 4.2 当前最强的运维读模型：`freshness`

`freshness` 当前已经具备以下特点：

1. 能优先读取 `ops.dataset_status_snapshot`
2. 对缺失项、共享表数据、cadence 不一致项做 live refresh
3. 能推导最新业务日、预期业务日、lag 天数、freshness 状态
4. 能挂接最近失败摘要、自动任务状态、活动执行状态

关键实现：

1. [src/ops/api/freshness.py](/Users/congming/github/goldenshare/src/ops/api/freshness.py)
2. [src/ops/queries/freshness_query_service.py](/Users/congming/github/goldenshare/src/ops/queries/freshness_query_service.py)

结论：

1. 后续增强型页面 API 应尽量复用 `freshness`，不要另造一套平行状态模型

### 4.3 测试基线已经存在

当前 `tests/web/*` 已覆盖大部分 `ops` API：

1. `overview`
2. `freshness`
3. `schedules`
4. `executions`
5. `layer snapshots`
6. `pipeline modes`
7. `source management bridge`
8. `review center`
9. `catalog`
10. `probes`
11. `releases`
12. `runtime`

结论：

1. 后续增强 API 具备接入现有 Web API 测试体系的基础

---

## 5. 主要问题清单（按优先级）

### 5.1 P0：`run-now` 语义与真实行为不一致

状态更新（2026-04-26）：该问题已通过 TaskRun 观测模型重设计收口。旧 `/api/v1/ops/executions*` 主链已下线，前端任务记录/详情改为消费 `/api/v1/ops/task-runs*`；手动提交任务使用 `/api/v1/ops/manual-actions/{action_key}/task-runs`，页面语义统一为“提交到队列/等待处理/执行过程”。

当前问题：

1. `POST /api/v1/ops/executions/run-now` 只是创建 execution 并返回详情
2. `POST /api/v1/ops/executions/{id}/retry-now` 只是重试并返回新的 queued execution
3. `POST /api/v1/ops/executions/{id}/run-now` 只是返回当前 execution 详情
4. Web 侧 runtime 执行入口已彻底 decouple，不能直接在 Web 进程中拉起执行

关键证据：

1. [src/ops/api/executions.py](/Users/congming/github/goldenshare/src/ops/api/executions.py) 中第 108、134、144 行附近
2. [src/ops/api/runtime.py](/Users/congming/github/goldenshare/src/ops/api/runtime.py) 中第 14 行附近
3. 原测试文件已迁移为 [tests/web/test_ops_task_run_api.py](/Users/congming/github/goldenshare/tests/web/test_ops_task_run_api.py)，并保留旧 `/api/v1/ops/executions` 路由不存在的防回退断言

影响：

1. 新 UI 很容易把“提交任务”误设计成“立即执行”
2. 页面按钮文案、状态反馈、用户预期都会产生偏差
3. 后续如果要补更强的任务控制能力，这块语义必须先统一

当前结论：

1. `run-now / retry-now / {id}/run-now` 三条历史路径不再保留，直接下线

### 5.2 P0：缺少“数据集详情聚合 API”

当前问题：

1. 数据集详情页需要并发请求 `freshness / latest / history / executions / probes / releases / std rules`
2. 页面内部还要做 fallback snapshot 和展示层拼装
3. 后端当前没有单个数据集的一站式详情读模型

关键证据：

1. [frontend/src/pages/ops-v21-dataset-detail-page.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-dataset-detail-page.tsx) 中第 59 行附近
2. [frontend/src/pages/ops-v21-dataset-detail-page.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-dataset-detail-page.tsx) 中第 109 行附近

影响：

1. 新 UI 会继续依赖前端拼接口
2. 页面越来越厚，复用和稳定性都会变差
3. 数据集详情页很难继续扩展出更丰富的信息层级

当前建议：

1. 后续优先讨论单独的数据集详情聚合读模型

### 5.3 P0：缺少“数据源详情聚合 API”

当前问题：

1. source 页当前仍靠前端组合 `pipeline-modes + freshness + layer latest + probes`
2. 现有 bridge 只是过渡聚合，不是 source-centric 的详情模型
3. bridge 输出是平铺对象集合，不是“围绕一个 source 的已归并视图”

关键证据：

1. [frontend/src/pages/ops-v21-source-page.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-source-page.tsx) 中第 79 行附近
2. [src/ops/api/source_management_bridge.py](/Users/congming/github/goldenshare/src/ops/api/source_management_bridge.py) 中第 16 行附近
3. [src/ops/queries/source_management_bridge_query_service.py](/Users/congming/github/goldenshare/src/ops/queries/source_management_bridge_query_service.py) 中第 12 行附近
4. [docs/ops/ops-contract-current.md](/Users/congming/github/goldenshare/docs/ops/ops-contract-current.md) 中第 87 行附近

影响：

1. 数据源页面还在客户端做筛选、归类和状态拼接
2. 后续想做 source 健康趋势、影响面、失败归因时，现有接口不够直接

当前建议：

1. 后续优先讨论 source 维度的详情聚合读模型

### 5.4 P1：overview API 偏浅，不足以支撑更丰富的新总览

当前问题：

1. 当前 overview 主要提供 execution KPI、freshness summary、attention datasets、recent executions、recent failures
2. 前端总览页还需要再拉 `pipeline-modes` 和 `layer-snapshots/latest` 自己组合卡片
3. 当前没有按 domain/source/stage/status 的服务端 breakdown 或 trend

关键证据：

1. [src/ops/api/overview.py](/Users/congming/github/goldenshare/src/ops/api/overview.py) 中第 16 行附近
2. [src/ops/queries/overview_query_service.py](/Users/congming/github/goldenshare/src/ops/queries/overview_query_service.py) 中第 24 行附近
3. [frontend/src/pages/ops-v21-overview-page.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-overview-page.tsx) 中第 149 行附近

影响：

1. 总览页仍然需要前端做二次汇总
2. 后续很难低成本扩到更丰富的总览页面

当前建议：

1. 后续讨论时应明确区分：`summary` 轻接口与 `overview dashboard` 富接口

### 5.5 P1：`pipeline-modes` 与 `layer-snapshots/latest` 是基础投影，不是页面聚合读模型

当前问题：

1. `pipeline-modes` 主要提供 mode、table hint、少量 configured 状态
2. `layer-snapshots/latest` 主要提供 stage/status/rows/lag/message/timestamp
3. 两者都适合作为基础投影，不适合作为新页面的主接口长期直接消费

关键证据：

1. [src/ops/queries/dataset_pipeline_mode_query_service.py](/Users/congming/github/goldenshare/src/ops/queries/dataset_pipeline_mode_query_service.py) 中第 24 行附近
2. [src/ops/queries/layer_snapshot_query_service.py](/Users/congming/github/goldenshare/src/ops/queries/layer_snapshot_query_service.py) 中第 70 行附近
3. [frontend/src/pages/ops-v21-overview-page.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-overview-page.tsx) 中第 154 行附近
4. [frontend/src/pages/ops-v21-source-page.tsx](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-source-page.tsx) 中第 80 行附近

影响：

1. 前端会不断重复“按页面需要二次重组”的逻辑
2. 不同页面之间容易形成不同版本的展示口径

当前建议：

1. 后续增强 API 时，应把它们保留为基础读模型，不再要求前端直接用它们撑所有页面

---

## 6. 当前 API 对新 UI 的支撑度判断

### 6.1 已能支撑的部分

1. 任务中心：当前接口已较完整，尤其 execution / schedule / detail 相关能力
2. 审查中心：当前接口已经比较 page-ready
3. 数据健康度：`freshness` 已具备较好的统一骨架

### 6.2 支撑不足的部分

1. 数据集详情页的聚合读模型
2. 数据源详情页的聚合读模型
3. 更丰富的总览页分析型读模型
4. 围绕执行调度与 dispatch 语义的一致性

---

## 7. 后续建议的讨论顺序

建议后续按以下顺序逐项讨论，不并题：

1. `run-now` / queue-only / dispatch 语义
2. 数据集详情聚合 API
3. 数据源详情聚合 API
4. overview 富接口与分析维度
5. `pipeline-modes` / `layer-snapshots/latest` 作为基础投影的长期定位

原因：

1. 第 1 项会直接影响任务中心和动作文案
2. 第 2、3 项会直接决定新 UI 的页面信息架构
3. 第 4、5 项适合在页面级详情能力稳定后再收口

---

## 8. 当前备忘结论

结论统一如下：

1. 当前 `ops` API 已具备较好的基础覆盖面
2. 当前最成熟的读模型是 `freshness`
3. 当前最大的短板是“缺少面向页面的聚合读模型”
4. 若目标是给新 UI 提供更丰富页面，应优先增强 `ops` 查询 API，而不是继续让前端拼装
5. 后续增强应继续落在 `src/ops/**`，保持 `src/app/api/**` 只做装配

---

## 9. 后续文档关系

本文定位为审查备忘。  
若后续进入设计与实现阶段，建议新增：

1. `ops execution dispatch 语义收口方案`
2. `ops dataset detail aggregate api design`
3. `ops source detail aggregate api design`
4. `ops overview analytics api design`

本文继续保留，用作后续专题讨论的共同起点。
