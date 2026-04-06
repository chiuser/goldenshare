# 前端应用一期设计

## 1. 目标

本文档定义 `goldenshare` 前端应用一期的实现边界与工程结构。

一期目标不是迁完业务页面，而是把未来长期使用的前端应用骨架搭起来。该骨架需要满足：

- 服务整个财势乾坤产品，而不是只服务当前运维系统
- 与现有 FastAPI BFF 平滑协作
- 适合逐步迁移运维系统、行情工作台和后续业务页面
- 在高密度信息与高频交互场景下具备良好的扩展基础

本设计同时遵守：

- [design-principles.md](/Users/congming/github/goldenshare/docs/architecture/design-principles.md)
- [frontend-technology-and-component-selection.md](/Users/congming/github/goldenshare/docs/frontend/frontend-technology-and-component-selection.md)

## 2. 一期范围

### 2.1 一期要做

- 建立独立前端应用工程
- 采用 React + TypeScript + Vite
- 建立 Mantine 为主的 UI 基座
- 引入 TanStack Query 与 TanStack Router
- 建立统一 API client 和鉴权状态层
- 建立基础应用壳
- 建立 `/app` 路由入口
- 建立最小页面样板：
  - 登录页
  - 平台检查页
  - 运维系统导航壳
  - 运维系统 overview / freshness / schedules / executions / catalog 的基础页面骨架

### 2.2 一期明确不做

- 不迁移行情工作台完整功能
- 不做复杂图表集成
- 不引入多套前端主组件体系
- 不把现有 `/ops` 原生静态控制台立即下线
- 不在前端一期内改动现有后端 BFF 的领域边界

## 3. 技术选型

前端应用一期采用：

- React
- TypeScript
- Vite
- Mantine
- TanStack Query
- TanStack Router

其中：

- Mantine 负责应用壳、表单、导航、通知、基础布局
- TanStack Query 负责服务端状态缓存、请求协调与刷新
- TanStack Router 负责长期可扩展的路由与 URL 状态模型

后续能力预留：

- TanStack Table / Virtual
- Lightweight Charts
- Apache ECharts

## 4. 目录结构

建议采用如下结构：

```text
frontend/
  package.json
  tsconfig.json
  tsconfig.app.json
  tsconfig.node.json
  vite.config.ts
  index.html

  src/
    main.tsx
    styles.css
    env.d.ts

    app/
      providers.tsx
      router.tsx
      shell.tsx
      theme.ts

    features/
      auth/
        auth-context.tsx
        auth-storage.ts

    shared/
      api/
        client.ts
        errors.ts
      ui/
        page-header.tsx
        stat-card.tsx

    pages/
      login-page.tsx
      platform-check-page.tsx
      ops-overview-page.tsx
      ops-freshness-page.tsx
      ops-schedules-page.tsx
      ops-executions-page.tsx
      ops-catalog-page.tsx
```

## 5. 路由设计

一期采用 `/app` 作为新的前端应用入口，避免立即替换现有：

- `/platform-check`
- `/ops`

这样可以做到：

- 新旧前端并行
- 后端 API 保持不变
- 迁移风险可控

一期路由建议：

- `/app`
- `/app/login`
- `/app/platform-check`
- `/app/ops`
- `/app/ops/overview`
- `/app/ops/freshness`
- `/app/ops/schedules`
- `/app/ops/executions`
- `/app/ops/catalog`

## 6. 与 FastAPI 的协作方式

后端继续作为 BFF 与 API 主体存在。

协作方式：

- API 仍由 FastAPI 提供，路径保持 `/api/...`
- 前端开发模式下，Vite 本地 dev server 代理 `/api` 到 FastAPI
- 前端构建模式下，FastAPI 直接托管 `frontend/dist`
- 新前端入口挂在 `/app`

## 7. 鉴权设计

一期继续复用当前 Web 平台已有的 token 机制：

- 登录接口：`POST /api/v1/auth/login`
- 当前用户：`GET /api/v1/auth/me`

前端策略：

- token 保存在 `localStorage`
- 应用启动时读取 token
- 通过 `TanStack Query` 请求 `/api/v1/auth/me`
- 若 token 失效，则清除本地登录状态并跳回登录页

## 8. 运维系统迁移策略

一期不要求把运维系统完整迁完，但需要在新前端里先落下“能持续长”的结构。

建议迁移顺序：

1. 先做 ops overview
2. 再做 freshness
3. 再做 schedules
4. 再做 executions
5. 最后再逐步替换旧 `/ops` 控制台

## 9. 验证方式

一期前端应用至少要通过：

- TypeScript 类型检查
- Vite build
- 基础页面可访问 smoke

推荐命令：

```bash
cd frontend
npm install
npm run build
```

## 10. 后续衔接

当前一期完成后，下一阶段就可以逐步接入：

- 运维系统页面迁移
- 行情工作台
- 图表层能力
- 表格与筛选器体系

因此，一期的核心价值不是“做出很多页面”，而是：

**把未来几年都会继续使用的前端应用地基搭好。**
