# 前端质量门禁矩阵 v1

> 角色说明：本文件用于完成 `Phase 5 / P5-1` 的门禁基线盘点。
> 当前执行边界请以 [frontend-phase5-execution-plan-v1.md](/Users/congming/github/goldenshare/docs/frontend/frontend-phase5-execution-plan-v1.md) 为准。

## 1. 文档目的

本文用于把当前前端已经存在的质量门禁、覆盖范围、薄弱点和待自动化规则整理成一份真实矩阵，作为后续：

- `P5-2` smoke / visual gate 扩面
- `P5-3` 规则自动检查
- `P5-4` CI 深化

的依据。

本文不负责新增门禁实现；只做盘点与结论。

---

## 2. 当前门禁入口

## 2.1 本地命令链

| 门禁 | 命令 | 当前作用 |
| --- | --- | --- |
| 类型检查 | `npm run typecheck` | 校验 TypeScript 类型与引用正确性 |
| 前端规则检查 | `npm run check:rules` | 校验旧业务语义、旧紫色名和 `pages/**` 中新增 `glass-card` |
| 单元测试 | `npm run test` | 校验页面、共享组件、feature hook 的当前测试基线 |
| 构建 | `npm run build` | 校验生产构建可通过 |
| smoke / 视觉门禁 | `npm run test:smoke` | `build + Playwright`，对关键页面做最小断言与截图比对 |
| smoke 基线更新 | `npm run test:smoke:update` | 在确认视觉变更是预期改动后刷新截图基线 |

## 2.2 CI 入口

当前前端质量门禁统一通过：

- `.github/workflows/frontend-quality-gate.yml`

触发条件：

| 触发方式 | 当前条件 |
| --- | --- |
| `pull_request` | 变更命中 `frontend/**` 或 workflow 文件 |
| `push` | 推到 `dev-interface` / `main`，且变更命中 `frontend/**` 或 workflow 文件 |
| `workflow_dispatch` | 手动触发 |

CI 当前执行顺序：

1. `npm ci`
2. Playwright Chromium 安装
3. `npm run typecheck`
4. `npm run check:rules`
5. `npm run test`
6. `npm run build`
7. `npm run test:smoke:ci`

结论：

- 当前已有一条可运行的统一门禁链
- workflow 已进入规则专项检查阶段
- 规则失败现在会以独立 step 暴露，便于定位是“规则问题”还是“测试/构建问题”

---

## 3. 当前页面级覆盖矩阵

当前仓库已落下 `10` 条 smoke / visual 基线，对应 `8` 个高价值页面入口或关键状态。

| 页面 / 路径 | smoke / visual | 页级单测 | 当前判断 |
| --- | --- | --- | --- |
| `login` | 有 | 有 | 认证页基线较稳 |
| `ops/v21/overview` | 有 | 有 | 壳层与概览卡片已受保护 |
| `ops/v21/datasets/tasks?tab=records` | 有 | 有 | 任务记录试点页保护较稳 |
| `ops/manual-sync` | 有 | 有 | 手动维护主路径保护较稳 |
| `ops/automation` | 有 | 无 | 依赖 smoke 保护，缺少页级单测 |
| `ops/tasks/:id` | 有 | 有 | 详情页主路径保护较稳 |
| `ops/v21/review/index` | 有 | 无 | 依赖 smoke 保护，缺少页级单测 |
| `share` | 有 | 无 | 依赖 smoke 保护，缺少页级单测 |

补充说明：

- `ops-v21-task-center-page.tsx` 有路由级单测，但当前 smoke 是直接覆盖其子入口页，不是单独做路由页截图。
- 当前已补入 2 条更深一层的任务中心状态基线：
  - `ops/v21/datasets/tasks` 默认入口与 tab 切换
  - `ops/manual-sync` 已选维护对象、交易日输入与提交流程
- `ops/automation` 当前 smoke 也已前进到“主表 + 详情 + 修改抽屉”状态。
- 当前 smoke 仍主要覆盖“主路径 + 有数据”的稳定基线，尚未形成系统化的空态 / 错误态 / 边界态矩阵。

当前未进入 smoke 的高可见页面包括：

1. `ops-v21-review-board-page.tsx`
2. `platform-check-page.tsx`
3. `user-overview-page.tsx`
4. `ops-v21-account-page.tsx`
5. `ops-v21-source-page.tsx`
6. `ops-v21-dataset-detail-page.tsx`

这些页面不应在 `P5-1` 直接扩 smoke，但应作为 `P5-2` 的候选风险池。

---

## 4. 当前共享组件覆盖矩阵

## 4.1 已有单测，且已有高可见页面回归保护

以下组件当前同时具备“组件单测 + smoke 页面使用”的双层保护：

| 组件 | 当前保护方式 |
| --- | --- |
| `AuthPageLayout` | 组件单测 + `login` smoke |
| `AlertBar` | 组件单测 + `task-manual / task-auto / task-detail / share` smoke |
| `StatusBadge` | 组件单测 + `overview / task-records / task-auto / task-detail` smoke |
| `FilterBar` | 组件单测 + `task-records` smoke |
| `DetailDrawer` | 组件单测 + `task-auto` smoke |
| `ActivityTimeline` | 组件单测 + `task-auto / task-detail` smoke |
| `TradeDateField` | 组件单测 + `task-manual / task-auto` smoke |
| `PriceText` | 组件单测 + `share` smoke |
| `ChangeText` | 组件单测 + `share` smoke |
| `DataTable` | 组件单测 + `task-records / task-auto / task-detail` smoke |
| `MetricPanel` | 组件单测 + `task-detail` smoke |
| `TableShell` | 组件单测 + 通过 `DataTable` 间接受到 smoke 保护 |

## 4.2 已有单测，但高可见回归保护较弱

| 组件 | 当前情况 | 风险 |
| --- | --- | --- |
| `PageHeader` | 有组件单测，但主要落在 `platform-check-page.tsx`，该页未进入 smoke | 高可见头部模式仍主要靠单测保护 |

## 4.3 高频可见，但缺少独立组件单测

| 组件 | 当前情况 | 风险 |
| --- | --- | --- |
| `SectionCard` | 多页高频使用，但无独立单测 | 视觉和结构变更更容易只在页面中被动暴露 |
| `StatCard` | 多页高频使用，但无独立单测 | 数值呈现与卡片语义缺少最小单测保护 |
| `EmptyState` | 多页使用，但无独立单测 | 空态文案和动作区的回归主要依赖页面覆盖 |

结论：

- 共享组件层已经形成第一批双层保护样板
- 但 `PageHeader / SectionCard / StatCard / EmptyState` 这类基础件仍存在保护不均衡问题

---

## 5. 当前 feature 与页面测试基线

截至当前仓库状态，前端共有 `28` 个测试文件。

覆盖类型包括：

1. `app` 层文案/回归测试
2. `features/trade-calendar` hook 测试
3. 关键页面测试
4. `shared/api` 客户端测试
5. `shared/ui` 组件测试

当前薄弱点：

1. `task-auto` 仍主要依赖 smoke，没有独立页级单测
2. `review-index` 与 `share` 仍主要依赖 smoke，没有独立页级单测
3. smoke fixtures 目前以“主路径、数据存在”为主，未系统覆盖空态 / 错误态

结论：

- 当前测试体系已从“只有组件测试”进化到“组件 + 页面 + smoke”
- 但页级测试和 smoke 的分布仍不均匀，后续需要按价值补齐，而不是平均铺开

---

## 6. 当前未自动化的规则清单

以下规则已经进入自动检查，并已接入现有前端 CI：

| 规则 | 当前状态 | 备注 |
| --- | --- | --- |
| 禁止新增旧业务语义，如 `week_friday` | 已自动检查并接入 CI | 通过 `npm run check:rules` |
| 禁止在 `pages/**` 中新增 `glass-card` | 已自动检查并接入 CI | 当前遗留点通过白名单保留 |
| 禁止新增旧紫色名，如 `violet / grape / pink / magenta` | 已自动检查并接入 CI | 当前遗留点通过白名单保留 |

以下规则虽然已经在 AGENTS 或前端文档中被明确，但当前还没有独立自动检查：

| 规则 | 当前状态 | 证据 |
| --- | --- | --- |
| 数字列右对齐与 `tabular-nums` | 仅文档规范 | 当前无专项检查 |
| 高可见共享组件改动后默认评估 smoke | 仅流程要求 | workflow 不感知“改了哪个共享组件” |
| 刷新截图基线必须给出理由 | 仅流程要求 | 当前无自动检查或 PR 校验脚本 |

当前残留证据示例：

1. `ops-v21-overview-page.tsx`、`user-overview-page.tsx`、`ops-v21-source-page.tsx` 仍直接使用 `glass-card`
2. `ops-v21-review-board-page.tsx` 仍存在 `violet` 颜色返回
3. 这些遗留点当前通过规则脚本白名单显式记录，避免继续无意识扩散

结论：

- 当前门禁已经进入“前端规则本身是否被破坏”的自动检查阶段
- 但规则检查目前只覆盖第一批低歧义规则，还没有覆盖数字展示和 smoke 纪律这类更高层规则

---

## 7. 当前风险清单

基于当前门禁矩阵，最主要的风险是：

1. smoke 覆盖面已能保护任务中心主链路，但对空态 / 错误态 / 分支态保护仍弱
2. 若后续直接修改 `PageHeader / SectionCard / StatCard / EmptyState`，当前保护不如试点组件稳
3. 旧视觉遗留与旧业务语义目前仍靠人工 review 发现，没有自动阻断
4. workflow 已经稳定，但失败原因仍主要聚合在“某个命令没过”，缺少规则层面的细分反馈

---

## 8. 对 P5-2 / P5-3 的直接输入

## 8.1 对 P5-2 的建议

优先补强：

1. `task center` 默认入口与 tab 切换
2. `task-auto` 的主表与详情联动
3. `task-manual` 的关键日期输入与提交反馈
4. `task-detail` 的状态摘要与时间线分支

注意：

- 继续优先主路径，不做全量页面扩面
- 应先补关键状态，而不是平均给所有页面加截图

## 8.2 对 P5-3 的建议

第一批最适合自动化的规则：

1. 禁止新增 `week_friday`
2. 禁止在页面中新增 `glass-card`
3. 禁止新增旧色名如 `violet / grape`
4. 对高可见共享组件改动给出 smoke 提示或检查入口

默认实现方向：

- 优先轻量脚本或 grep 型检查
- 不在 `P5-3` 一开始就引入复杂 lint 体系

---

## 9. 当前结论

当前前端已经具备：

1. 一条统一的本地与 CI 质量门禁链
2. `8` 个关键页面的 smoke / visual gate
3. `28` 个测试文件组成的组件、页面、feature 基线
4. 一批已经形成双层保护的高频共享组件

但当前还没有完成的，是：

1. 空态 / 错误态的 smoke 深化
2. 高频基础件保护均衡化
3. 规则自动检查
4. CI 对规则层失败的可读反馈

因此，`P5-1` 的结论是：

- 当前门禁已具备继续深化的基础
- 后续最该做的不是再扩页面重构，而是按本矩阵推进 `P5-2` 与 `P5-3`
