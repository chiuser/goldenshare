# 前端 Phase 6 执行计划 v1

> 角色说明：本文件是“Phase 6 规模化推广”的执行计划文档。
> 当前前端强约束与统一门禁请以 [frontend-current-standards.md](/Users/congming/github/goldenshare/docs/frontend/frontend-current-standards.md) 为准。

## 1. 文档目的

本文用于把前端治理在 `Phase 6` 的执行边界、推广批次、每批边界卡、默认验证档位和完成标准写清楚，避免在 `Phase 5` 已完成后重新回到“页面先改、边界以后再补”的节奏。

适用范围：

- `frontend/**`
- 前端推广批次相关文档
- 前端高可见页面的标准件推广
- 前端回归与 smoke / visual gate 扩面判断

本文不替代：

- 共享组件目录文档
- 页面专项方案
- 后端架构与契约文档

---

## 2. 当前起点

截至 `2026-04-23`，前端治理进度以当前仓库实际状态为准：

1. `Phase 1` 已完成：治理骨架已落地。
2. `Phase 2` 已完成：主题与 token 基线已收敛。
3. `Phase 3` 已完成：高频共享组件标准库与最小领域组件已形成。
4. `Phase 4` 已完成：任务中心试点页与试点支持任务已落地。
5. `Phase 5` 已完成：门禁矩阵、smoke / visual gate、规则自动检查、CI 接入与回归流程已收口。

当前已具备的质量基线：

- `npm run typecheck`
- `npm run check:rules`
- `npm run test`
- `npm run build`
- `npm run test:smoke`
- `.github/workflows/frontend-quality-gate.yml`

当前已具备的推广基线：

- 通用组件：`PageHeader`、`SectionCard`、`StatusBadge`、`StatCard`、`EmptyState`、`AlertBar`、`FilterBar`、`TableShell`、`DetailDrawer`、`ActivityTimeline`
- 领域组件：`PriceText`、`ChangeText`、`TradeDateField`
- 表格基线：`DataTable v1 = TableShell + OpsTable`
- 任务中心试点链路已验证：
  - `task records`
  - `task manual`
  - `task auto`
  - `task detail`

当前候选推广页的真实证据：

1. 低风险页已经部分接入标准件，但仍有局部遗留：
   - `platform-check-page.tsx` 已使用 `PageHeader / SectionCard / StatCard`
   - `user-overview-page.tsx` 仍有 `glass-card`
2. 审查中心页已经部分接入标准件，但仍有旧语义残留：
   - `ops-v21-review-index-page.tsx` 已使用 `SectionCard`
   - `ops-v21-review-board-page.tsx` 仍有 `violet` provider tone，且文件达到 `893` 行
3. 数据详情页已进入新模式，但局部卡面和状态表达仍不完全一致：
   - `ops-v21-source-page.tsx` 仍有 `glass-card`
   - `ops-v21-dataset-detail-page.tsx` 已使用 `MetricPanel / SectionCard / StatusBadge`
4. 管理配置页体量较大，应后置处理：
   - `ops-v21-account-page.tsx` 当前 `788` 行

---

## 3. Phase 6 目标

`Phase 6` 的目标不是再造一套前端，而是把已经在 `Phase 3/4` 验证过的模式，按批次推广到相邻页面与高可见页面。

本阶段目标：

1. 将试点中验证有效的组件模式推广到更多页面。
2. 将仍停留在页面局部的旧展示入口逐步收敛到统一标准件。
3. 让推广页进入统一的回归和截图基线流程。
4. 在不扩大业务改造面的前提下，控制页面厚度继续膨胀。
5. 为后续是否继续新一轮推广、或进入专项重构提供清晰的残留清单。

---

## 4. 非目标

本阶段明确不做：

1. 不做 big-bang 全站翻修。
2. 不重做任务中心试点页。
3. 不改后端 API 契约。
4. 不新起第二套 UI 体系。
5. 不为单页顺手发明新的大而全组件族。
6. 不把 `ops-v21-account-page.tsx` 这类大页的业务重构和视觉收敛混在同一轮处理。
7. 不为了“视觉统一”顺手改无关页面。

---

## 5. 工作包拆分

## 5.1 P6-0：批次确认与边界卡

目标：

- 先把推广批次、可复用标准件、每批默认验证档位和明确非目标写清楚。

交付物：

1. 本文档
2. 更新后的总计划文档
3. 更新后的文档索引与当前基线文档

边界：

- 只做计划与边界卡
- 不进入任何页面实现

---

## 5.2 P6-1：低风险推广批

页面范围：

1. `frontend/src/pages/platform-check-page.tsx`
2. `frontend/src/pages/user-overview-page.tsx`

当前证据：

- `platform-check-page.tsx` 已使用 `PageHeader / SectionCard / StatCard`
- `user-overview-page.tsx` 仍有 `glass-card`

允许复用的标准件：

- `PageHeader`
- `SectionCard`
- `StatCard`
- `StatusBadge`
- `EmptyState`

本批目标：

1. 统一高可见卡面与头部模式
2. 清掉本批页面里明显的旧展示入口
3. 不改变页面主流程和数据契约

本批不做：

1. 不抽新领域组件
2. 不改查询逻辑
3. 不改壳层

默认验证档位：

- `npm run typecheck`
- `npm run check:rules`
- `npm run test`
- `npm run build`
- 若触及高可见截图基线，则评估 `npm run test:smoke`

当前边界卡：

- [frontend-phase6-p6-1-boundary-card-v1.md](/Users/congming/github/goldenshare/docs/frontend/frontend-phase6-p6-1-boundary-card-v1.md)

---

## 5.3 P6-2：审查中心推广批

页面范围：

1. `frontend/src/pages/ops-v21-review-index-page.tsx`
2. `frontend/src/pages/ops-v21-review-board-page.tsx`

当前证据：

- `ops-v21-review-index-page.tsx` 已使用 `SectionCard`
- `ops-v21-review-board-page.tsx` 仍有 `violet` provider tone，且文件较厚

允许复用的标准件：

- `PageHeader`
- `SectionCard`
- `StatusBadge`
- `FilterBar`
- `TableShell`

本批目标：

1. 统一审查中心的列表、筛选和状态表达
2. 收掉旧 provider tone 与局部旧视觉残留
3. 让审查中心进入统一组件口径

本批不做：

1. 不拆大页业务逻辑
2. 不改审查规则语义
3. 不扩成新的审查域重构

默认验证档位：

- `npm run typecheck`
- `npm run check:rules`
- `npm run test`
- `npm run build`
- `npm run test:smoke`

当前边界卡：

- [frontend-phase6-p6-2-boundary-card-v1.md](/Users/congming/github/goldenshare/docs/frontend/frontend-phase6-p6-2-boundary-card-v1.md)

---

## 5.4 P6-3：数据详情推广批

页面范围：

1. `frontend/src/pages/ops-v21-source-page.tsx`
2. `frontend/src/pages/ops-v21-dataset-detail-page.tsx`

当前证据：

- `ops-v21-source-page.tsx` 仍有 `glass-card`
- `ops-v21-dataset-detail-page.tsx` 已使用 `MetricPanel / SectionCard / StatusBadge`

允许复用的标准件：

- `SectionCard`
- `StatusBadge`
- `MetricPanel`
- `DataTable v1`
- `PriceText`
- `ChangeText`

本批目标：

1. 推广指标面板、详情卡面和状态表达
2. 收掉局部旧卡面与旧状态入口
3. 让详情页进入更稳定的展示基线

本批不做：

1. 不改数据链路契约
2. 不新起详情子路由
3. 不扩成数据域整体重构

默认验证档位：

- `npm run typecheck`
- `npm run check:rules`
- `npm run test`
- `npm run build`
- 视触及页面情况评估 `npm run test:smoke`

当前边界卡：

- [frontend-phase6-p6-3-boundary-card-v1.md](/Users/congming/github/goldenshare/docs/frontend/frontend-phase6-p6-3-boundary-card-v1.md)

当前结果：

1. `ops-v21-source-page.tsx` 已清理页面级 `glass-card` 数据卡面，并把状态表达收回统一 `StatusBadge`。
2. `ops-v21-dataset-detail-page.tsx` 已将局部详情卡面和近期执行记录收敛到 `MetricPanel / DataTable`。
3. 本批已补页级测试，但经评估暂不纳入 smoke / visual gate，避免本轮扩成大规模 fixture 工程。

---

## 5.5 P6-4：管理配置推广批

页面范围：

1. `frontend/src/pages/ops-v21-account-page.tsx`

当前证据：

- `ops-v21-account-page.tsx` 当前 `788` 行，体量和风险都明显高于前几批

允许复用的标准件：

- `SectionCard`
- `StatusBadge`
- `AlertBar`
- `TableShell`
- `DetailDrawer`

本批目标：

1. 只做展示层和高频模式收敛
2. 控制页面继续膨胀
3. 不让这一批变成业务重构入口

本批不做：

1. 不拆账号业务流程
2. 不改邀请码/账号管理契约
3. 不把大页拆分和业务改造混做

默认验证档位：

- `npm run typecheck`
- `npm run check:rules`
- `npm run test`
- `npm run build`
- 视改动面评估 `npm run test:smoke`

当前边界卡：

- [frontend-phase6-p6-4-boundary-card-v1.md](/Users/congming/github/goldenshare/docs/frontend/frontend-phase6-p6-4-boundary-card-v1.md)

当前结果：

1. `ops-v21-account-page.tsx` 已将操作反馈收敛到 `AlertBar`，并将用户状态与邀请码状态收回统一 `StatusBadge`。
2. 用户列表与邀请码列表已进入 `TableShell`，编辑账号与重置密码动作已进入 `DetailDrawer`。
3. 本批已补页级测试；经评估本轮暂不进入 smoke / visual gate，避免把管理配置批扩大成新的 fixture 工程。

---

## 5.6 P6-5：收口与残留清单

目标：

- 回看推广结果，整理剩余未推广页、未自动化门禁候选和下轮是否继续推广的依据。

交付物：

1. 推广结果小结
2. 残留清单
3. 是否继续下一轮推广的建议

边界：

- 只做结果整理与评审结论
- 不新增页面改造任务

当前结果：

1. `Phase 6` 第一轮推广已覆盖 `8` 个页面、`4` 个批次。
2. 已形成正式收口文档与残留清单：
   - [frontend-phase6-rollout-summary-v1.md](/Users/congming/github/goldenshare/docs/frontend/frontend-phase6-rollout-summary-v1.md)
3. 当前判断为：`Phase 6` 第一轮规模化推广已完成，下一步不建议默认继续开新批次。

---

## 6. 执行顺序

`Phase 6` 默认按以下顺序推进：

1. `P6-0` 批次确认与边界卡
2. `P6-1` 低风险推广批
3. `P6-2` 审查中心推广批
4. `P6-3` 数据详情推广批
5. `P6-4` 管理配置推广批
6. `P6-5` 收口与残留清单

任何一轮都必须遵守：

1. 只做一个主目标
2. 不顺手扩大到无关页面
3. 不触碰后端主线
4. 不为单页临时需求扩出第二套标准件
5. 先看真实代码，再写边界卡，再动实现

---

## 7. 每批边界卡模板

每一批进入实现前都必须先补一张“改动边界卡”，至少包含：

1. 本轮主目标
2. 本轮不做
3. 影响文件
4. 允许复用的共享组件
5. 是否允许新增共享组件
6. 默认验证档位
7. 是否触及 smoke / visual gate
8. 回滚边界

若本轮触及现有共享组件，还必须说明：

9. 是否需要同步组件目录文档
10. 是否需要同步 HTML Showcase

---

## 8. 默认验证要求

`Phase 6` 每一批至少考虑：

1. `cd frontend && npm run typecheck`
2. `cd frontend && npm run check:rules`
3. `cd frontend && npm run test`
4. `cd frontend && npm run build`

在以下情况额外评估：

1. 触及已进入 smoke 的页面或关键高可见页面：
   - `cd frontend && npm run test:smoke`
2. 需要刷新截图基线：
   - `cd frontend && npm run test:smoke:update`
   - 然后再跑一次 `cd frontend && npm run test:smoke`

具体档位、截图基线刷新纪律与 CI 排查顺序，以 [frontend-regression-and-baseline-workflow-v1.md](/Users/congming/github/goldenshare/docs/frontend/frontend-regression-and-baseline-workflow-v1.md) 为准。

---

## 9. 完成标准

`Phase 6` 结束时，至少应满足：

1. 推广批页面进入统一组件口径。
2. 推广批页面不再新增旧视觉入口。
3. 每一批都有清晰边界与回归记录。
4. 不出现页面改造导致的架构回流。
5. 门禁始终跟得上，不重新退回口头约定。

---

## 10. 当前下一步

当前已完成 `P6-5`。
下一步只建议做一件事：

- 先评审 [frontend-phase6-rollout-summary-v1.md](/Users/congming/github/goldenshare/docs/frontend/frontend-phase6-rollout-summary-v1.md)，再按残留清单决定是否进入专项治理或新一轮推广。
