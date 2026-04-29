# 前端 Smoke 与视觉回归门禁 v1

## 1. 文档目的

本文件用于定义前端在 `Phase 5` 建立、并在 `Phase 6` 持续扩面的 smoke 与视觉回归门禁基线，避免后续改动破坏 `Phase 2-4` 已经收敛下来的视觉、共享组件和任务中心试点成果。

当前策略不是一次性铺开全站 E2E，而是先维护一条可运行、可维护、可扩展的最小门禁，并在高价值主路径上逐步扩面。

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

当前已覆盖 `11` 条最能代表前端收敛成果和任务中心试点成果的 smoke / visual 基线，落在 `9` 个高价值页面或关键状态上：

1. 登录页
2. `ops/v21/overview`
3. `ops/v21/datasets/tasks?tab=records`
4. `ops/v21/datasets/tasks` 默认入口与 tab 切换
5. `ops/v21/datasets/tasks?tab=manual` 引导态
6. `ops/v21/datasets/tasks?tab=manual` 已选维护对象 + 交易日输入 + 提交流程
7. `ops/automation` 主表 + 详情 + 修改抽屉
8. `ops/tasks/:id`
9. `ops/v21/review/index`
10. `ops/v21/review/board?tab=equity`

覆盖目标：

- 认证页布局
- 管理壳层
- SectionCard / StatCard / StatusBadge
- 任务中心主链路：默认入口 / tab 切换 / 列表 / 表单 / 抽屉 / 详情 / 提交流程
- 审查中心列表与板块审查页
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
- 刷新基线前，应在变更说明中明确写出允许刷新的原因
- 详细刷新纪律与交付说明要求，以 [frontend-regression-and-baseline-workflow-v1.md](/Users/congming/github/goldenshare/docs/frontend/frontend-regression-and-baseline-workflow-v1.md) 为准

---

## 5. CI 入口

当前 CI 入口：

- `.github/workflows/frontend-quality-gate.yml`

CI 默认执行：

1. 安装依赖
2. 安装 Playwright Chromium
3. `typecheck`
4. `frontend rule check`
5. `unit test`
6. `build`
7. `smoke + visual gate`

当前 workflow 运行在 macOS runner 上，优先保证与当前本地截图基线的一致性。

---

## 6. 使用纪律

1. 新增 smoke 页面前，先确认它是否能代表一类稳定页面模式。
2. 先用 mock 固定 API，再做截图，不把后端波动带进视觉门禁。
3. 截图门禁优先服务于“发现非预期变化”，不是代替页面专项验收。
4. 若视觉变更涉及新共享组件或壳层，应同步评估是否要扩充 smoke 覆盖面。
5. 若涉及任务中心主链路或高可见共享组件，应默认评估是否需要补 smoke 页面或更新截图基线说明。
