# 行情业务系统技术栈与库规范 v1

## 1. 前端框架与运行时

固定采用：

1. `React 19`
2. `TypeScript 5`
3. `Vite 7`
4. `@tanstack/react-router`
5. `@tanstack/react-query`

原则：

1. 保持与现有 `frontend` 主工程一致，避免多框架并存。
2. 不新引入第二套路由与请求状态管理框架。

---

## 2. UI 与设计系统

基础组件库：

1. `@mantine/core`
2. `@mantine/hooks`
3. `@mantine/dates`
3. `@mantine/notifications`

视觉规范：

1. 统一覆盖到 v13 token 与组件语义。
2. 不使用 Mantine 默认主题直接出页面。
3. 红涨绿跌、深色终端风格必须在主题层统一控制。

---

## 3. 图表与时间处理

1. 图表：ECharts（业务图）
2. 时间处理：`dayjs`

约束：

1. 图表封装放到 `widgets` 或 `shared/ui/chart`，禁止页面散落配置。
2. 时间格式在 `shared/utils/time` 统一处理。

---

## 4. 请求层与鉴权

1. 统一使用 `shared/api` 封装。
2. 鉴权头统一注入。
3. token 刷新、401 跳转、超时策略在请求层统一。

不允许：

1. 页面里直接 `fetch`。
2. 页面内拼装 auth header。

---

## 5. 状态管理策略

1. 服务端状态：`react-query`
2. 页面局部 UI 状态：组件 state
3. 跨页面会话态：auth context

原则：

1. 不引入额外全局状态库（如 Redux/Zustand）除非专项评审通过。
2. 尽量保持 query-key 语义化，防止缓存污染。

---

## 6. 开发工具与检查

1. 类型检查：`npm run typecheck`
2. 规则检查：`npm run check:rules`
3. 单测：`npm run test`
4. 烟测：`npm run test:smoke` / `test:smoke:ci`

---

## 7. 依赖新增准入规则

新增第三方库前必须说明：

1. 为什么现有栈无法满足。
2. 影响范围（包体积、样式冲突、学习成本）。
3. 回滚方案。

无上述说明，不允许引入新库。
