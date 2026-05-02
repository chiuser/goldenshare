# AGENTS.md — frontend/src/shared/ui 共享组件规则

## 适用范围

本文件适用于 `frontend/src/shared/ui/` 目录及其所有子目录。

若未来更深层目录存在更具体的 `AGENTS.md`，应同时遵守；发生冲突时，以更靠近当前目录的规则为准。

---

## 当前目录职责

`shared/ui/` 是前端共享组件标准库，负责沉淀跨页面复用的展示组件与交互模式。

当前应承接的内容包括：

- 共享展示组件
- 共享表单输入模式
- 共享状态展示模式
- 共享空状态 / 帮助提示 / 卡片 / 表格壳
- 领域展示组件（如价格、涨跌、交易日输入）
- 与当前设计 token 对齐的 UI 标准件

---

## 当前硬约束

### 1. 共享 UI 优先偏展示

共享组件应优先做到：

- props 语义明确
- 易读
- 可复用
- 不依赖具体页面接口路径

默认不要让共享 UI 直接承接：

- fetch
- React Query
- 页面 search param
- 页面级业务状态流转
- 路由跳转

### 2. 不允许反向依赖页面与壳层

`shared/ui/**` 不应 import：

- `pages/**`
- `app/**`

默认也不应直接依赖：

- `features/**`

除非出现真正跨页面复用、且语义足够稳定的 feature-level 展示约束。

### 3. 不要把后端对象名直接暴露为组件语义

共享组件的 props 名和展示语义，应尽量面向前端交互与用户语言，而不是后端对象名。

例如：

- 优先 `status`
- 慎用 `execution_status_raw`

### 4. 共享组件不是页面临时样式仓库

不要把“只为当前单页服务、且没有复用证据”的组件强行塞进 `shared/ui`。

至少满足以下之一再进入共享层：

- 已在两个以上页面出现
- 明确属于设计系统标准件
- 是计划中的高频基础组件

### 5. 领域组件仍然优先保持展示边界

像 `PriceText`、`ChangeText`、`TradeDateField` 这类领域组件可以进入 `shared/ui`，但默认仍应保持展示边界。

不要在组件内部直接承接：

- 页面级查询
- 交易日历请求
- 页面状态组合
- 与单页绑定的业务流程

补充约束：

- `TradeDateField` 若承接周/月锚点规则，只能表达“最后一个交易日”语义
- 自然周五 / 自然月末这类非交易日历锚点必须由 `DateField` 承接，并且只能消费后端 `selection_rule` 派生结果，不能在页面按数据集 key 特判

---

## 推荐依赖

`shared/ui/**` 可以依赖：

- React
- Mantine
- Tabler
- `shared/*` 下语义稳定的通用工具

应尽量避免依赖：

- `shared/api/types`

若只是为了展示而需要某些类型，优先提取更小的前端视图型 props，而不是把整段后端响应类型穿进组件。

---

## 当前目录的重点方向

当前这一层已经有基础，但还没有形成完整标准库。
当前这一层已经形成第一批可复用标准件，后续重点从“补空白”转向“稳定边界并服务试点页”。

当前优先方向是：

1. 把已有基础件稳定下来
2. 补高频壳组件
3. 统一 token 和样式约束

当前高优先级组件包括：

- `SectionCard`
- `StatusBadge`
- `EmptyState`
- `StatCard`
- `AlertBar`
- `DetailDrawer`
- `DateField`
- `MonthField`
- `FilterBar`
- `TableShell`
- `ActivityTimeline`
- `PriceText`
- `ChangeText`
- `TradeDateField`

当前表格基线说明：

- `TableShell + OpsTable` 是当前仓库的 `DataTable v1` 基线
- 若后续进入更完整的 `DataTable`，应优先保持外部契约稳定，而不是急着替换内部实现

---

## 组件设计默认要求

新增共享组件时，至少明确：

1. 组件解决什么重复问题
2. 是否已有相近组件
3. props 是否稳定
4. 是否需要测试
5. 是否已经遵守 token 规则

若组件属于以下类型，还应额外明确：

- 表格壳：当前是否仍沿用 `TableShell + OpsTable`
- 领域输入组件：能力来自哪里，是否保持展示边界
- 高可见标准件：是否需要同步更新组件目录文档与 HTML Showcase

优先避免：

- 直接透传一大坨页面状态
- 组件内部知道过多业务字段
- 使用处还要写大量重复样式修补

---

## 验证要求

当 `shared/ui/**` 有以下变化时，优先补测试：

- 组件行为变化
- 组件样式语义变化
- 组件 props 契约变化
- 组件被新增到组件目录或 HTML Showcase 的标准清单中

至少考虑：

- `npm run typecheck`
- `npm run test`
- `npm run build`

若影响的是高可见组件或试点页正在消费的组件，还应评估：

- `npm run test:smoke`
- 组件目录文档是否需要同步
- HTML Showcase 是否需要同步

共享组件的最小验证档位与截图基线更新纪律，以 [frontend-regression-and-baseline-workflow-v1.md](/Users/congming/github/goldenshare/docs/frontend/frontend-regression-and-baseline-workflow-v1.md) 为准。
