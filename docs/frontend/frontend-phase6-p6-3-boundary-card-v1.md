# 前端 Phase 6 P6-3 数据详情推广批边界卡 v1

> 角色说明：本文件用于约束 `Phase 6 / P6-3` 的数据详情页面推广范围。
> 当前统一强约束请以 [frontend-current-standards.md](/Users/congming/github/goldenshare/docs/frontend/frontend-current-standards.md) 为准。

## 1. 本轮主目标

在不改变数据链路契约和页面主流程的前提下，把数据源详情页与数据集详情页继续收敛到统一的详情卡面、指标面板和状态表达模式。

本轮只处理：

1. `frontend/src/pages/ops-v21-source-page.tsx`
2. `frontend/src/pages/ops-v21-dataset-detail-page.tsx`

---

## 2. 本轮不做

1. 不改数据链路契约与查询参数。
2. 不新增数据域专用共享组件。
3. 不拆分详情页业务逻辑或新增子路由。
4. 不扩到 `account / review / source-management` 等其他批次页面。
5. 不触碰后端 `src/**` 主线。

---

## 3. 允许复用的共享标准件

1. `SectionCard`
2. `StatusBadge`
3. `MetricPanel`
4. `DataTable`
5. `EmptyState`

---

## 4. 影响文件

运行时代码默认只允许进入：

1. `frontend/src/pages/ops-v21-source-page.tsx`
2. `frontend/src/pages/ops-v21-dataset-detail-page.tsx`

测试文件可按需进入：

3. `frontend/src/pages/ops-v21-source-page.test.tsx`
4. `frontend/src/pages/ops-v21-dataset-detail-page.test.tsx`

门禁与文档可按需进入：

5. `docs/frontend/frontend-phase6-p6-3-boundary-card-v1.md`
6. `docs/frontend/frontend-phase6-execution-plan-v1.md`
7. `docs/frontend/frontend-quality-gate-matrix-v1.md`
8. `docs/README.md`

若本轮评估后确认需要纳入 smoke / visual gate，才允许进一步进入：

9. `frontend/e2e/support/smoke-fixtures.ts`
10. `frontend/e2e/smoke-visual.spec.ts`
11. `frontend/e2e/smoke-visual.spec.ts-snapshots/**`

---

## 5. 当前代码证据

1. `ops-v21-source-page.tsx` 仍直接使用 `glass-card` 承接数据集卡片。
2. `ops-v21-source-page.tsx` 的状态表达仍使用页面内 `Badge` 逻辑，没有完全复用 `StatusBadge`。
3. `ops-v21-dataset-detail-page.tsx` 已接入 `MetricPanel / SectionCard / StatusBadge`，但仍保留多块页面内 `Paper` 卡面和手写表格结构。
4. 当前这两页还没有独立页级测试，也未进入 smoke / visual gate。

---

## 6. 允许的改动类型

1. 收掉 `glass-card` 这类旧卡面入口。
2. 将页面内状态表达收回统一 `StatusBadge`。
3. 将局部详情卡面收敛到 `MetricPanel` 或现有标准卡面模式。
4. 将近期执行记录接入 `DataTable`。
5. 为本批实际改动页面补最小页级测试。
6. 评估是否需要新增 smoke；若价值不够高，可只记录“不进入 smoke”的判断。

---

## 7. 禁止事项

1. 不改变现有接口请求与响应结构。
2. 不引入新的复杂状态管理。
3. 不把这轮推广扩大成数据详情架构重做。
4. 不顺手处理与本批无关的旧视觉残留。
5. 不为了统一视觉而新增不必要的共享抽象。

---

## 8. 默认验证档位

本轮至少执行：

1. `cd frontend && npm run typecheck`
2. `cd frontend && npm run check:rules`
3. `cd frontend && npm run test`
4. `cd frontend && npm run build`

若本轮确认要把页面纳入 smoke / visual gate：

5. `cd frontend && npm run test:smoke`
6. 若截图基线发生变化，再执行 `cd frontend && npm run test:smoke:update`
7. 再执行一次 `cd frontend && npm run test:smoke`

---

## 9. 回滚边界

若本轮推进中发现范围失控，优先按以下顺序回滚：

1. 先撤回局部卡面和表格壳统一，不动查询逻辑。
2. 再撤回新加页级测试中的非必要断言。
3. 不通过新增共享组件来“兜住”单页问题。
