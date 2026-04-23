# Ops Execution API 队列语义收口方案 v1

更新时间：2026-04-23  
适用范围：`src/ops/api/executions.py`、`src/ops/api/runtime.py`、`src/ops/services/*`、`frontend/src/pages/ops*`

---

## 1. 目的

本文件用于收口 `execution` 相关 Web API 的命名与行为语义，使其与当前任务中心的**队列模型**保持一致。

本文解决的问题：

1. Web UI 已经按“提交到队列”设计
2. 后端 API 曾保留一组 `run-now` 命名的历史路径
3. 这些历史路径会让后续任务中心交互、文案和 API 演进持续别扭

本文不解决：

1. 不讨论新的任务中心页面设计
2. 不讨论新的调度/worker 架构
3. 不直接改动运行时代码

---

## 2. 已确认的统一口径

### 2.1 执行模型

当前确认：

1. `execution` 是一次执行请求的生命周期实例
2. Web/API 负责创建、查询、重试、取消 execution 请求
3. execution 创建后先进入 `queued`
4. 独立 `worker` 负责领取 queued execution 并推进为 `running`
5. Web 请求本身不拥有长任务执行过程

### 2.2 UI 语言

当前确认：

1. 前端任务中心使用“提交任务”“重新提交”“请求停止”“等待处理”“正在处理”
2. 不再保留 `run-now`、`立即执行`、`立即重跑` 作为新 UI 主文案

### 2.3 API 语言

当前确认：

1. 面向新调用方的 API 语义必须体现队列模型
2. 历史 `run-now` 路径不再保留，避免继续制造 immediate execution 幻觉

---

## 3. 当前问题现状

### 3.1 当前主要 route

当前 `execution` 相关 route：

1. `POST /api/v1/ops/executions`
2. `POST /api/v1/ops/executions/{execution_id}/retry`
3. `POST /api/v1/ops/executions/{execution_id}/cancel`

### 3.2 当前真实行为

当前真实行为：

1. `POST /ops/executions`：创建一条新的 `queued` execution
2. `POST /ops/executions/{id}/retry`：创建新的 `queued` execution
3. `POST /ops/runtime/scheduler-tick` 与 `POST /ops/runtime/worker-run`：Web 内固定返回 `409 runtime_decoupled`

### 3.3 当前矛盾点

矛盾集中在：

1. 历史 route 名字曾暗示“立即执行”
2. 真实模型始终是“入队 -> worker 领取 -> 执行”
3. 新前端已经绕开这套命名，因此后端可以直接清理历史路径

---

## 4. 目标态契约

### 4.1 推荐保留的主路径

推荐作为主路径长期保留：

1. `POST /api/v1/ops/executions`
   - 语义：创建 execution request，并进入队列
2. `POST /api/v1/ops/executions/{execution_id}/retry`
   - 语义：基于既有 execution 重新创建 execution request，并进入队列
3. `POST /api/v1/ops/executions/{execution_id}/cancel`
   - 语义：请求停止 execution；若尚未开始则取消，若已运行则进入 `canceling`
4. `GET /api/v1/ops/executions/*`
   - 语义：查询 execution 生命周期与状态

### 4.2 明确不作为主路径的能力

以下能力不应再作为新 UI 的主执行入口：

1. `POST /api/v1/ops/runtime/scheduler-tick`
2. `POST /api/v1/ops/runtime/worker-run`
3. 任何“Web 请求内直接跑长任务”的 route 设计

### 4.3 队列语义下的推荐状态解释

建议统一按以下方式解释：

1. `queued`：请求已被系统接收，等待 worker 处理
2. `running`：worker 已领取并开始执行
3. `canceling`：已收到停止请求，等待当前可中断点结束
4. `canceled`：任务已停止
5. `success / partial_success / failed`：终态

---

## 5. 历史路径收口建议

### 5.1 直接移除 3 条历史路径

本轮已确认：

1. `POST /api/v1/ops/executions/run-now`
2. `POST /api/v1/ops/executions/{id}/retry-now`
3. `POST /api/v1/ops/executions/{id}/run-now`

处理原则：

1. 仓内无前端或其他运行时代码依赖这些路径
2. 不做兼容过渡
3. 直接下掉 route，让历史路径不可用（通常表现为 `404` 或 `405`，取决于路由匹配结果）

原因：

1. 这些路径的命名与当前队列模型冲突
2. 继续保留只会让后续 UI 和 API 文档不断绕弯解释
3. 当前调用面足够可控，直接清理成本最低

---

## 6. 推荐实施顺序

### 6.1 Phase A：先统一文档与调用口径

目标：

1. 所有主文档只使用队列模型描述任务中心
2. 所有新前端文案不再出现 `run-now`
3. 审查 memo 与契约文档口径保持一致

### 6.2 Phase B：后端 API 路径收口

目标：

1. 审计前端与内部调用方是否还在依赖 `run-now`
2. 直接移除 3 条历史 route
3. 明确 `/ops/runtime/*` 是 decoupled runtime，不对新 UI 暴露

---

## 7. 对前端的直接影响

当前判断：

1. 新 V2.1 任务中心页面基本已符合目标态
2. 前端当前无需为这项语义收口做大改
3. 主要需要的是：后端 API 与文档追上前端已经采用的队列模型

需要注意：

1. 后续若新增任务按钮，不得重新引入“立即执行”“立即重跑”文案
2. 后续若新增动作 route，应优先映射到 `submit / retry / cancel / inspect`

---

## 8. 需要 review 的点

本方案当前建议你重点 review 这 3 点：

1. 是否接受：新主路径只保留 `create / retry / cancel / query`
2. 是否接受：3 条历史 `run-now` 路径直接移除
3. 是否接受：历史路径删除后，测试基线同步改为断言“历史路径不可用”

---

## 9. 实施前置与边界

实施时必须遵守：

1. 不改变独立 worker / scheduler 的 ownership
2. 不把长任务重新绑回 Web 请求
3. 不为了兼容历史命名而破坏当前队列模型
4. 先做调用审计，再做路由收口
5. 收口后必须补 Web API 测试与任务中心回归验证

---

## 10. 结论

当前建议的统一方向是：

1. 任务中心继续坚持队列模型
2. 新 UI 不再使用 `run-now`
3. 后端 `execution` API 需要完成一次“命名与语义对齐”
4. 真正需要收口的是后端历史路径，而不是现有前端主页面
