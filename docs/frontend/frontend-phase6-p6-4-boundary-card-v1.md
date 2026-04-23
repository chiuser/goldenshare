# 前端 Phase 6 P6-4 管理配置推广批边界卡 v1

> 角色说明：本文件用于约束 `Phase 6 / P6-4` 的管理配置页面推广范围。
> 当前统一强约束请以 [frontend-current-standards.md](/Users/congming/github/goldenshare/docs/frontend/frontend-current-standards.md) 为准。

## 1. 本轮主目标

在不改变账号管理契约和业务流程的前提下，把账号管理页继续收敛到统一的反馈条、状态表达、表格壳和详情抽屉模式。

本轮只处理：

1. `frontend/src/pages/ops-v21-account-page.tsx`

---

## 2. 本轮不做

1. 不拆分账号业务流程。
2. 不改邀请码 / 用户管理接口契约。
3. 不把大页拆分和业务改造混做。
4. 不扩到 `review / source detail / source management` 等其他批次页面。
5. 不触碰后端 `src/**` 主线。

---

## 3. 允许复用的共享标准件

1. `SectionCard`
2. `StatusBadge`
3. `AlertBar`
4. `TableShell`
5. `DetailDrawer`

---

## 4. 影响文件

运行时代码默认只允许进入：

1. `frontend/src/pages/ops-v21-account-page.tsx`

测试文件可按需进入：

2. `frontend/src/pages/ops-v21-account-page.test.tsx`

门禁与文档可按需进入：

3. `docs/frontend/frontend-phase6-p6-4-boundary-card-v1.md`
4. `docs/frontend/frontend-phase6-execution-plan-v1.md`
5. `docs/README.md`

---

## 5. 当前代码证据

1. `ops-v21-account-page.tsx` 仍是大页，且此前主要依赖页面内 `Paper / Alert / Badge / Table` 直写展示。
2. 用户编辑和密码重置此前仍以内联块承接，没有进入统一详情抽屉模式。
3. 用户与邀请码列表此前还没有进入统一表格壳。
4. 当前页已有最小页级测试，但还没有覆盖新的状态表达与抽屉模式。

---

## 6. 允许的改动类型

1. 将操作反馈收回 `AlertBar`。
2. 将用户和邀请码列表收进 `TableShell`。
3. 将用户状态和邀请码状态收回统一 `StatusBadge`。
4. 将编辑账号和重置密码动作收进 `DetailDrawer`。
5. 为本批实际改动页面补最小页级测试。
6. 评估是否需要新增 smoke；若价值不够高，可只记录“不进入 smoke”的判断。

---

## 7. 禁止事项

1. 不改变用户创建、更新、停用、重置密码的业务语义。
2. 不改 tab 结构和查询契约。
3. 不引入新的复杂状态管理。
4. 不把这轮推广扩大成账号管理重构。
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

1. 先撤回状态标签、反馈条和详情抽屉统一，不动账号业务逻辑。
2. 再撤回新加页级测试中的非必要断言。
3. 不通过新增共享组件来“兜住”单页问题。
