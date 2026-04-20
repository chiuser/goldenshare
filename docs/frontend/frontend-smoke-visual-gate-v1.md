# 前端 Smoke 与视觉回归门禁 v1

## 1. 文档目的

本文件用于定义前端在进入 `Phase 3` 和试点重构前的最小自动化门禁，避免后续改动破坏 `Phase 2` 已经收敛下来的视觉和基础交互成果。

当前策略不是一次性铺开全站 E2E，而是先建立一条可运行、可维护、可扩展的最小门禁。

---

## 2. 当前门禁组成

当前前端门禁由 4 部分组成：

1. `npm run typecheck`
2. `npm run test`
3. `npm run build`
4. `npm run test:smoke`

其中 `test:smoke` 采用 Playwright，在固定时区、固定 viewport、固定 mock 数据下，对代表性页面做：

- 最小 smoke 断言
- Chromium 截图基线比对

---

## 3. 当前覆盖页面

v1 先覆盖 5 个最能代表当前前端收敛成果的页面：

1. 登录页
2. `ops/v21/overview`
3. `ops/v21/datasets/tasks?tab=records`
4. `ops/v21/review/index`
5. `share`

覆盖目标：

- 认证页布局
- 管理壳层
- SectionCard / StatCard / StatusBadge
- 任务表格与状态操作
- 审查中心列表
- 行情展示页与红涨绿跌语义

---

## 4. 命令约定

本地运行：

```bash
cd frontend
npm run test:smoke
```

说明：该命令会先执行一次 `build`，再启动 `preview` 服务跑 Playwright，确保截图基线对齐生产态资源路径。
默认会优先使用仓库内 `frontend/.playwright` 浏览器缓存。

更新截图基线：

```bash
cd frontend
npm run test:smoke:update
```

说明：

- 只有在确认视觉变更是“有意为之”时，才允许更新截图基线
- 若只是功能改动，不应顺手刷新截图
- 在 Codex 桌面沙箱里，`preview` 绑定本地端口可能需要提升权限；这属于本地运行约束，不影响 CI

---

## 5. CI 入口

当前 CI 入口：

- `.github/workflows/frontend-quality-gate.yml`

CI 默认执行：

1. 安装依赖
2. 安装 Playwright Chromium
3. `typecheck`
4. `unit test`
5. `build`
6. `smoke + visual gate`

当前 workflow 运行在 macOS runner 上，优先保证与当前本地截图基线的一致性。

---

## 6. 使用纪律

1. 新增 smoke 页面前，先确认它是否能代表一类稳定页面模式。
2. 先用 mock 固定 API，再做截图，不把后端波动带进视觉门禁。
3. 截图门禁优先服务于“发现非预期变化”，不是代替页面专项验收。
4. 若视觉变更涉及新共享组件或壳层，应同步评估是否要扩充 smoke 覆盖面。
