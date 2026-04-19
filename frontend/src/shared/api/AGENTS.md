# AGENTS.md — frontend/src/shared/api API 传输与契约规则

## 适用范围

本文件适用于 `frontend/src/shared/api/` 目录及其所有子目录。

若未来更深层目录存在更具体的 `AGENTS.md`，应同时遵守；发生冲突时，以更靠近当前目录的规则为准。

---

## 当前目录职责

`shared/api/` 是前端统一 API 传输与契约层。

当前应承接的内容包括：

- 通用请求客户端
- 通用错误模型
- 请求超时与鉴权刷新处理
- 前端使用的接口类型定义

---

## 当前硬约束

### 1. 这里只做 transport 与 contract

允许：

- `apiRequest`
- `ApiError`
- 类型定义
- 与鉴权相关的通用传输处理

不允许：

- React hooks
- Context
- 页面级请求组合
- 页面文案
- Mantine 组件
- 页面格式化逻辑

### 2. 不允许反向依赖页面和壳层

`shared/api/**` 不应 import：

- `pages/**`
- `app/**`
- `features/**`

### 3. 类型定义不要无限长成新的巨型文件

当前 `types.ts` 已经承载了较多领域类型。

后续若继续增长，应优先考虑按领域拆分，而不是无边界把所有响应继续堆进一个文件。

建议拆分方向示例：

- `auth-types.ts`
- `ops-types.ts`
- `share-types.ts`

### 4. API 层不直接承接页面语义

不要在这里写：

- 页面状态解释
- 面向用户的 label
- 页面特定的字段拼装

这些应留在 `shared/*` 的格式化层、`features/*` 或 `pages/*`。

---

## 当前目录改动规则

### `client.ts`

若修改：

- 超时策略
- 鉴权刷新
- 未授权处理
- 重试行为

必须说明：

- 是否影响全站
- 是否影响登录态恢复
- 是否影响关键接口行为

### `types.ts`

新增类型时，优先考虑：

- 是否属于现有领域
- 是否应该拆到更小的领域文件
- 是否只是页面局部视图模型

### `errors.ts`

错误模型应保持稳定、可测试、可被页面理解。

---

## 验证要求

改动 `shared/api/**` 后，至少考虑：

- `npm run typecheck`
- `npm run test`
- `npm run build`

若涉及以下行为，必须优先补测试或更新测试：

- token 刷新
- 401 处理
- 超时处理
- 错误模型变化

