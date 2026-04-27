# 行情页架构复用与自研栈落地方案 v1

## 1. 目标与边界

本方案用于落地以下约束：

1. 只复用参考实现（`example/app`）的页面架构与交互骨架。
2. 视觉与组件必须使用我们自己的设计系统与组件目录：
   - `docs/frontend/frontend-biz_design_system_v13.md`
   - `docs/frontend/frontend-biz_component_catalog_v13.md`
   - `docs/frontend/frontend-biz_component_showcase_v13.html`
3. 后端接口、鉴权、用户体系、业务查询全部走我们现有架构（`src/app + src/biz + src/foundation`），不复用 `example` 里的后端实现。

明确不做：

1. 不引入 `example` 的路由实现、鉴权实现、JS 业务实现。
2. 不把业务主实现写回 `src/platform`（legacy 目录）。
3. 不改现有运维任务链路（TaskRun/ops）作为本方案主线。

---

## 2. 参考样本拆解（仅取“架构”，不取“实现”）

参考代码：

1. `example/app/main.py`
2. `example/app/routers/*`
3. `example/app/static/*.html`
4. `example/app/static/*.js`

可复用的“页面架构模式”：

1. Page Shell：顶部工具栏 + 主图区域 + 辅助面板。
2. Page Router：页面路由与 API 路由分离。
3. Feature 模块化：按页面域拆分模块（行情、情绪、组合、管理）。
4. 数据驱动渲染：页面状态由后端返回的 ViewModel 驱动。

禁止复用项：

1. 直接复用 `example/app/routers/*.py` 的接口协议。
2. 直接复用 `example/app/static/app.js` 的请求与鉴权逻辑。
3. 直接复用 `example/app/static/style.css` 的视觉样式。

---

## 3. 前端落地架构（使用自研设计体系）

## 3.1 页面分层

页面层按以下结构落地：

1. `Page`: 页面容器与路由入口（只编排，不写重业务逻辑）。
2. `FeatureSection`: 页面一级业务区块（行情概览、K 线区、指标区、新闻区）。
3. `DomainComponent`: 领域组件（PriceText、ChangeText、MetricCard、IndexCard、RankList、LimitBoard、LadderStage）。
4. `UIComponent`: 通用组件（Panel、Tabs、Drawer、Table、EmptyState、Skeleton）。

## 3.2 视觉与组件约束

必须遵循：

1. 红涨绿跌、深色金融终端风格（v13 口径）。
2. 所有颜色、间距、字号通过 token 管理，不允许页面内硬编码散色值。
3. 组件 props 与行为按照 `Component Catalog v13` 执行。
4. 页面状态必须覆盖：`loading` / `empty` / `error` / `stale`。

## 3.3 页面信息骨架（复用对象）

复用“结构骨架”而不是实现：

1. 顶部：检索 + 筛选 + 周期切换 + 复权切换 + 状态提示。
2. 中区：主图（K 线） + 成交量或辅助图。
3. 侧区/下区：指标卡、榜单、新闻、策略建议。
4. 下钻：Drawer/详情页承载大数据量列表，主页面不堆满。

---

## 4. 后端落地架构（使用自研体系）

## 4.1 入口与路由

统一走现有应用入口与路由聚合：

1. 应用入口：`src/app/web/app.py`
2. API 聚合：`src/app/api/router.py` 与 `src/app/api/v1/router.py`
3. 业务接口域：`src/biz/api/**`

不新增 `example` 风格的独立后端进程或独立路由体系。

## 4.2 鉴权与用户体系

统一使用现有 auth/admin 体系（已在 `src/app/auth/**`）：

1. 认证依赖、token 校验、当前用户解析走 `src/app/auth`。
2. 用户、角色、权限模型走 `src/app/models/**`。
3. 不接受页面侧自行持有“简化 token 逻辑”。

## 4.3 业务查询与接口契约

统一走 `biz`：

1. 查询逻辑：`src/biz/queries/**`
2. 接口 schema：`src/biz/schemas/**`
3. API 路由：`src/biz/api/**`

行情接口基线参考：

1. `docs/platform/quote-detail-api-spec-v1.md`

---

## 5. 前后端契约对齐原则

## 5.1 ViewModel 先行

页面不消费底层原始字段组合，接口返回页面所需聚合 ViewModel。

## 5.2 字段口径一致

1. 数值精度、单位、涨跌符号后端统一处理。
2. 时间字段统一格式化约定（日期与时间戳口径固定）。
3. 状态字段必须有明确枚举与中文语义。

## 5.3 错误语义一致

1. 业务错误返回稳定 code 与可读中文 message。
2. 前端按错误语义渲染（重试、提醒、降级显示），不显示后端内部栈信息。

---

## 6. 交付里程碑（可执行）

## M1：架构骨架落地

1. 页面路由与模块目录建立（不写视觉细节）。
2. 页面骨架组件（toolbar/chart/panel/drawer）装配完成。
3. API 调用层接入我们现有鉴权链路。

验收：

1. 页面可打开，可切路由，可带登录态访问。
2. 不存在对 `example` 后端或静态资源的运行依赖。

## M2：设计系统接入

1. 接入 v13 token。
2. 接入 v13 领域组件目录（优先高频组件）。
3. 关键页面达到 v13 视觉一致性。

验收：

1. 红涨绿跌正确。
2. 组件与 show case 对照无明显漂移。

## M3：业务接口切入

1. 对接 `biz` 业务接口与 schema。
2. 页面所有主数据由 `biz` API 返回，不直连 `ops` 接口。
3. 处理空态、异常态、滞后态。

验收：

1. 页面可完整展示主流程数据。
2. 异常和空态行为符合规范。

## M4：联调回归与门禁

1. 页面 smoke。
2. 鉴权链路回归。
3. 核心接口契约回归（字段、状态、错误码）。

验收：

1. 关键路径可用。
2. 不引入架构回流（`platform`/`operations`）。

---

## 7. 风险与防偏离

主要风险：

1. “只想快点跑起来”导致复用 `example` 的后端或 JS 实现。
2. 页面为了赶进度绕过组件目录，出现样式漂移。
3. 页面直接拼装底层字段，导致契约不稳定。

防偏离措施：

1. 代码评审明确检查：是否引用 `example` 代码进入正式实现。
2. 页面 PR 必须附上 v13 组件映射说明。
3. 接口 PR 必须附上 schema 变更与前端消费者清单。

---

## 8. 验收清单

1. 页面架构复用了骨架模式，但未复用 `example` 的实现代码。
2. 视觉、token、组件全部走 v13 文档与 catalog。
3. 后端仅使用我们自己的 auth/user/biz 体系。
4. 前后端契约可回归，错误语义稳定。
5. 无 `platform/operations` 主实现回流。
