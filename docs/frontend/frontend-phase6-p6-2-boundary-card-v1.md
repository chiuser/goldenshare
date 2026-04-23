# 前端 Phase 6 P6-2 审查中心推广批边界卡 v1

> 角色说明：本文件用于约束 `Phase 6 / P6-2` 的审查中心页面推广范围。
> 当前统一强约束请以 [frontend-current-standards.md](/Users/congming/github/goldenshare/docs/frontend/frontend-current-standards.md) 为准。

## 1. 本轮主目标

在不改变审查业务语义和后端契约的前提下，把审查中心两页继续收敛到统一的页头、筛选栏、表格壳与状态表达模式。

本轮只处理：

1. `frontend/src/pages/ops-v21-review-index-page.tsx`
2. `frontend/src/pages/ops-v21-review-board-page.tsx`

---

## 2. 本轮不做

1. 不拆分 `ops-v21-review-board-page.tsx` 的业务逻辑。
2. 不重做审查中心的路由结构。
3. 不新增审查域专用共享组件。
4. 不改变搜索参数语义和接口参数命名。
5. 不扩到 `source detail / account` 等后续批次页面。
6. 不触碰后端 `src/**` 主线。

---

## 3. 允许复用的共享标准件

1. `PageHeader`
2. `SectionCard`
3. `StatusBadge`
4. `FilterBar`
5. `TableShell`
6. `EmptyState`
7. `OpsTable`

---

## 4. 影响文件

运行时代码默认只允许进入：

1. `frontend/src/pages/ops-v21-review-index-page.tsx`
2. `frontend/src/pages/ops-v21-review-board-page.tsx`

测试文件可按需进入：

3. `frontend/src/pages/ops-v21-review-index-page.test.tsx`
4. `frontend/src/pages/ops-v21-review-board-page.test.tsx`

门禁与文档可按需进入：

5. `frontend/e2e/support/smoke-fixtures.ts`
6. `frontend/e2e/smoke-visual.spec.ts`
7. `frontend/e2e/smoke-visual.spec.ts-snapshots/**`
8. `docs/frontend/frontend-phase6-p6-2-boundary-card-v1.md`
9. `docs/frontend/frontend-phase6-execution-plan-v1.md`
10. `docs/README.md`

---

## 5. 当前代码证据

1. `ops-v21-review-index-page.tsx` 已使用 `SectionCard`，但筛选区与表格区仍是页面内手写结构。
2. `ops-v21-review-board-page.tsx` 仍有 `violet` provider tone，并且同样使用了手写筛选区、表格壳和空态。
3. 当前 smoke 已覆盖 `review-index`，但还未覆盖 `review-board`。

---

## 6. 允许的改动类型

1. 接入统一 `PageHeader`。
2. 将筛选区接到 `FilterBar`。
3. 将结果区接到 `TableShell` 与 `EmptyState`。
4. 将旧 `violet` provider tone 收回当前语义色基线。
5. 为本批实际改动页面补最小页面测试。
6. 更新现有 `review-index` smoke 基线；若必要，可新增 `review-board` smoke 基线。

---

## 7. 禁止事项

1. 不改变 tab 结构和搜索参数行为。
2. 不改审查接口的请求与响应结构。
3. 不引入新的复杂状态管理。
4. 不把这轮推广扩大成审查中心重构。
5. 不顺手处理与本批无关的旧视觉残留。

---

## 8. 默认验证档位

本轮至少执行：

1. `cd frontend && npm run typecheck`
2. `cd frontend && npm run check:rules`
3. `cd frontend && npm run test`
4. `cd frontend && npm run build`
5. `cd frontend && npm run test:smoke`

若截图基线发生变化：

6. `cd frontend && npm run test:smoke:update`
7. 再执行一次 `cd frontend && npm run test:smoke`

---

## 9. 回滚边界

若本轮推进中发现范围失控，优先按以下顺序回滚：

1. 先撤回局部页头、筛选栏和表格壳统一，不动查询逻辑。
2. 再撤回新加 smoke 或测试中的非必要断言。
3. 不通过新增共享抽象来“兜住”单页问题。
