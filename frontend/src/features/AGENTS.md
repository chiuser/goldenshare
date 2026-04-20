# AGENTS.md — frontend/src/features 特性域规则

## 适用范围

本文件适用于 `frontend/src/features/` 目录及其所有子目录。

若未来更深层目录存在更具体的 `AGENTS.md`，应同时遵守；发生冲突时，以更靠近当前目录的规则为准。

---

## 当前目录职责

`features/` 是前端特性域层，负责承接有明确领域边界的状态、流程、上下文与 feature 级逻辑。

当前已经存在：

- `features/auth`

后续应优先把真正属于某个领域的前端逻辑收敛到这里，而不是继续堆在页面里。
当前最值得预留的下一类 feature，是试点期将要出现的“交易日历读取与缓存能力”。

---

## 当前硬约束

### 1. `features` 不是新的杂项目录

放进 `features/**` 的前提是：

- 有明确领域归属
- 会被一个以上页面或入口复用
- 不是单纯的页面局部 helper

### 2. `features` 不负责壳层与全局 theme

不要放：

- Router
- App shell
- Theme
- 全局 provider 装配

这些仍然属于 `app/**`。

### 3. `features` 不应直接依赖页面

`features/**` 不应 import：

- `pages/**`

页面应消费 feature，而不是反过来。

### 4. `features` 可以有自己的 UI，但应保持 feature 级语义

允许：

- feature hooks
- feature context
- feature-level 状态管理
- feature 内部组件

但不要把“全站共享标准件”放进 `features`；那应进入 `shared/ui`。

---

## 推荐依赖

`features/**` 可以依赖：

- `shared/api/**`
- `shared/hooks/**`
- `shared/ui/**`
- `shared/*` 下通用工具

`features/**` 不应依赖：

- `app/**`（除 provider 被 app 挂载外）
- `pages/**`

---

## 当前目录的发展方向

当前 `features` 只有 `auth`，说明 feature 层还偏弱。

后续若出现以下信号，应优先考虑新建 feature 子目录：

- 某类状态被多个页面共享
- 某类任务流、筛选流、详情流在多个页面重复出现
- 页面中出现大量可识别的领域逻辑

示例方向：

- `features/ops-task-*`
- `features/ops-review-*`
- `features/share-*`
- `features/trade-calendar`

当前试点准备期的额外口径：

- 若后续升级 `TradeDateField v2`，真实交易日能力应优先来自 `features/*` 或 `shared/api + hook`
- `shared/ui/TradeDateField` 仍应保持展示边界，不在组件内部直接发请求
- `features/trade-calendar` 若出现，应优先承接：
  - 交易日历读取
  - 月度或区间缓存
  - 面向组件的只读判断能力

---

## 验证要求

改动 `features/**` 后，至少考虑：

- `npm run typecheck`
- `npm run test`
- `npm run build`

若改动的是：

- context
- 鉴权
- 多页面复用的 hook

应优先补测试或更新测试。
