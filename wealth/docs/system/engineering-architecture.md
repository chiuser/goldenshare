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

## wealth 后端 API 代码组织规范（系统级）

> 本规范用于后续接真实 API 阶段。  
> 当前首期仍以 mock 为主，但目录规范先冻结，避免后续代码走样。

### 目标

1. 后端按“业务域 + 页面域 + 模块域”分层组织。
2. 禁止 `src/biz/api|queries|schemas|services` 扁平堆文件。
3. 模块接口只返回模块数据，不伪装成整页聚合接口。

### 统一目录模板

```text
src/biz/
  api/
    wealth/
      market/
        <module>.py
  queries/
    wealth/
      market/
        <module>/
          *_query.py
          *_query_service.py
  schemas/
    wealth/
      market/
        <module>.py
  services/
    wealth/
      market/
        <module>/
          *_registry.py
          *_resolver.py
          *_builder.py
```

### 命名与边界约束

1. `<module>` 必须是页面可识别模块名（如 `leaderboards`、`sector_overview`、`limit_up`）。
2. `schemas/.../<module>.py` 只承载该模块 DTO，不承载整页 DTO。
3. 整页 DTO 必须独立文件（如 `overview.py`），禁止和模块 DTO 混放。
4. 模块接口（如 `/api/v1/wealth/market/leaderboards`）只返回模块对象，不返回整页对象。
5. 规则定义（registry）、状态归并（resolver）、异常组装（builder）必须独立职责，不得塞入一个大文件。
6. 任何新增模块都必须先在文档中确定目录落点，再编码。

## 组件拆分原则

1. 一个组件只表达一个清晰职责。
2. 页面文件超过 400 行前必须拆分。
3. 相同 UI 模式出现两次以上，优先沉淀到 `shared/ui`。
4. 领域模块组件优先放 `features`，确认跨页面复用后再上升到 `shared/ui`。
5. 图表组件可以先使用 SVG/CSS 实现，不为首期引入重型图表库。

## 模块开发流程规范（三件套）

新增业务模块时，必须按以下顺序推进，禁止跳步：

1. 先写标杆需求文档（benchmark requirement）  
   模板：`wealth/docs/templates/benchmark-requirement-template.md`
2. 再写技术实施方案（implementation design）  
   模板：`wealth/docs/templates/implementation-design-template.md`
3. 再写编码前门禁（coding gate）  
   模板：`wealth/docs/templates/coding-gate-template.md`
4. 三件套评审通过后，才能进入代码实现阶段。

硬约束：

1. 三件套文档必须互相引用，形成可追溯链路。
2. coding gate 未通过，不允许提交模块实现代码。
3. 异常码必须先登记到 `wealth/docs/system/exception-code-registry.md`，再进入设计与代码。

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
