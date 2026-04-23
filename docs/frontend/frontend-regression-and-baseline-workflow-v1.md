# 前端回归与截图基线流程 v1

> 角色说明：本文件用于完成 `Phase 5 / P5-5` 的回归与截图基线流程固化。
> 当前统一强约束请以 [frontend-current-standards.md](/Users/congming/github/goldenshare/docs/frontend/frontend-current-standards.md) 为准。

## 1. 文档目的

本文用于把前端的最小回归口径、截图基线更新纪律、CI 失败排查顺序和不同改动类型的默认验证要求写成统一流程，避免后续继续靠口头约定推进。

本文适用于：

- `frontend/**`
- 前端相关 smoke / visual gate
- 前端共享组件与试点页改动
- 前端 CI 门禁排查

本文不替代：

- 页面专项方案
- 共享组件设计说明
- 后端架构与契约文档

---

## 2. 核心原则

前端回归流程遵循 5 条原则：

1. 先判断改动类型，再决定验证深度，不做无边界全量回归。
2. 截图基线只用于确认“有意的视觉变化”，不是掩盖功能问题。
3. 高可见共享组件和任务中心试点页优先使用更强回归。
4. CI 失败必须能本地复现，不接受黑盒排查。
5. 若改动无法覆盖到完整自动化回归，必须明确说明缺口。

---

## 3. 改动类型与最小验证矩阵

| 改动类型 | 最小验证 |
| --- | --- |
| 文档 / AGENTS 仅变更 | `python3 scripts/check_docs_integrity.py` |
| 前端 workflow / 门禁脚本 / `package.json` 脚本 | `npm run typecheck` + `npm run check:rules` + `npm run test` + `npm run build` + 对应 smoke 命令 |
| `shared/ui/**` 普通组件 | `npm run typecheck` + `npm run test` + `npm run build` |
| `shared/ui/**` 高可见组件 | `npm run typecheck` + `npm run check:rules` + `npm run test` + `npm run build` + `npm run test:smoke` |
| `pages/**` 非关键流程小改动 | `npm run typecheck` + `npm run test` + `npm run build` |
| 任务中心试点页 / 高可见页面 | `npm run typecheck` + `npm run check:rules` + `npm run test` + `npm run build` + `npm run test:smoke` |
| `features/trade-calendar/**` 或影响试点页的 `shared/api/**` | `npm run typecheck` + `npm run test` + `npm run build` + `npm run test:smoke` |
| smoke / visual gate 本身变更 | `npm run typecheck` + `npm run check:rules` + `npm run test` + `npm run build` + `npm run test:smoke:update` + `npm run test:smoke` |

补充说明：

- `高可见组件` 默认指：`PageHeader`、`SectionCard`、`StatCard`、`StatusBadge`、`AlertBar`、`DetailDrawer`、`TableShell`、`DataTable`、`TradeDateField`、`ActivityTimeline`
- `任务中心试点页` 默认指：`task center` 主链路与其直接相邻页
- 若本轮同时改了共享组件和试点页，按更高验证档执行

---

## 4. 截图基线更新纪律

## 4.1 允许更新截图基线的情况

只有以下情况允许执行 `npm run test:smoke:update`：

1. 有意的视觉设计变更
2. 有意的页面结构或信息层级调整
3. 有意新增 smoke 覆盖页或关键状态
4. 有意更新固定 mock 数据，且该数据本身属于设计基线的一部分

## 4.2 不允许刷新截图掩盖的问题

以下情况不允许直接刷新截图基线：

1. 功能断言本身失败
2. 页面元素未加载完整
3. 只是为了“让 CI 先过”
4. 后端波动或随机时间戳导致的噪音
5. 当前视觉变化并非本轮目标，而是顺手带出的副作用

## 4.3 更新截图基线时必须说明

刷新截图基线后，交付说明里至少要写清：

1. 为什么这次视觉变化是预期行为
2. 影响了哪些 smoke 页面或状态
3. 是否同步影响了共享组件或壳层
4. 是否已经重新执行 `npm run test:smoke`

---

## 5. 共享组件最小验证口径

## 5.1 普通共享组件

若改动的是普通共享组件，默认至少要确认：

1. 组件单测通过
2. `typecheck / test / build` 通过
3. 若影响 props 契约，调用处没有被静默破坏

## 5.2 高可见共享组件

若改动的是高可见共享组件，默认还要额外确认：

1. 是否影响当前 smoke 覆盖页
2. 是否需要更新截图基线
3. 组件目录文档是否需要同步
4. HTML Showcase 是否需要同步

默认高可见共享组件最小门禁：

```bash
cd frontend
npm run typecheck
npm run check:rules
npm run test
npm run build
npm run test:smoke
```

---

## 6. 试点页与推广页最小验证口径

## 6.1 任务中心试点页

若改动涉及：

- `task records`
- `task manual`
- `task auto`
- `task detail`
- `task center` 默认入口与 tab 切换

默认最小门禁为：

```bash
cd frontend
npm run typecheck
npm run check:rules
npm run test
npm run build
npm run test:smoke
```

并额外确认：

1. 主流程可进入
2. 空状态 / 错误态 / 加载态是否受影响
3. 是否需要刷新截图基线

## 6.2 相邻推广页

若改动的是非试点页、但属于高可见推广页，默认至少确认：

1. `typecheck / test / build`
2. 页面是否已有 smoke
3. 若当前没有 smoke，是否需要补页级单测或记录为后续门禁候选

---

## 7. CI 失败排查顺序

当前 `Frontend Quality Gate` 失败时，默认按以下顺序排查：

1. `Typecheck`
2. `Frontend rule check`
3. `Unit test`
4. `Build`
5. `Smoke and visual gate`

推荐本地复现顺序：

```bash
cd frontend
npm run typecheck
npm run check:rules
npm run test
npm run build
npm run test:smoke:ci
```

排查口径：

- `typecheck` 失败：先看类型与引用边界，不要先刷测试
- `check:rules` 失败：先看是否新增了旧语义或旧视觉入口，不要先改白名单
- `test` 失败：优先判断是组件契约回归还是页面断言过期
- `build` 失败：优先看打包与类型残留，不要先怀疑 smoke
- `smoke` 失败：先判断是断言失败、截图差异，还是本地预览服务问题

---

## 8. 交付说明最低要求

若本轮前端改动触发了回归或截图基线更新，最终说明至少要包含：

1. 本轮改动类型
2. 实际执行的门禁命令
3. 是否刷新了截图基线
4. 若刷新了截图，为什么允许刷新
5. 是否存在未覆盖的回归缺口

---

## 9. 当前结论

从本文件生效开始，前端不再只依赖“记住该跑什么”。

统一口径是：

1. 先按改动类型选择验证档位
2. 再按固定顺序执行门禁
3. 再决定是否允许刷新截图基线
4. 最后在交付说明中写清楚本轮实际验证与缺口
