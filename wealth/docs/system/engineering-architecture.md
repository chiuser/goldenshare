# wealth 工程架构规范

## 目标

建立一个长期可维护的独立行情系统前端工程，避免与运营后台互相污染。

## 目录结构

```text
wealth/
  AGENTS.md
  README.md
  package.json
  vite.config.ts
  tsconfig.json
  index.html
  docs/
    system/
    pages/
  src/
    app/
      App.tsx
    features/
    pages/
    shared/
      api/
      lib/
      model/
      ui/
    styles/
      design-tokens.css
      global.css
    test/
      setup.ts
```

## 分层原则

### app

负责应用装配，不承载业务页面逻辑。

允许：

- 根组件
- 路由装配
- Provider
- 全局样式引入
- ErrorBoundary

禁止：

- 市场总览模块实现
- 业务 API 拼装
- 页面内状态堆叠

### pages

负责页面级编排。

市场总览页面后续放入：

```text
src/pages/market-overview/
```

### features

负责领域模块。

市场总览后续模块建议：

```text
src/features/market-overview/
  summary/
  indices/
  breadth/
  style/
  turnover/
  money-flow/
  leaderboards/
  limit-up/
  sectors/
```

### shared

负责跨页面基础能力。

```text
src/shared/api/
src/shared/lib/
src/shared/model/
src/shared/ui/
```

## 状态要求

每个重要页面或容器必须明确：

- loading
- empty
- error
- loaded
- data delayed

首期 mock 也要覆盖这些状态，不能只做 happy path。

## 数据流

首期数据流：

```text
Page -> marketOverviewApi mock adapter -> typed mock data -> components
```

后续真实 API 数据流：

```text
Page -> marketOverviewApi client -> /api/v1/wealth/market/overview -> typed response -> components
```

前端不得绕过 adapter 直接拼接口，也不得调用 ops 后台接口凑数据。

## 组件拆分原则

1. 一个组件只表达一个清晰职责。
2. 页面文件超过 400 行前必须拆分。
3. 相同 UI 模式出现两次以上，优先沉淀到 `shared/ui`。
4. 领域模块组件优先放 `features`，确认跨页面复用后再上升到 `shared/ui`。
5. 图表组件可以先使用 SVG/CSS 实现，不为首期引入重型图表库。

## 验证门禁

代码改动后默认执行：

```bash
npm run typecheck
npm run test
npm run build
```

页面实现阶段还需要补 smoke 检查。

## 与现有工程的关系

`wealth` 可以参考现有 `frontend/` 的通用研发流程，但不能复用其运营后台 Shell、路由和页面架构。

禁止为了省事把市场总览接入 `frontend/src/app/router.tsx`。
