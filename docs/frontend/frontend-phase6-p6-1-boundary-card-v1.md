# 前端 Phase 6 P6-1 低风险推广批边界卡 v1

> 角色说明：本文件用于约束 `Phase 6 / P6-1` 的单批页面推广范围。
> 当前统一强约束请以 [frontend-current-standards.md](/Users/congming/github/goldenshare/docs/frontend/frontend-current-standards.md) 为准。

## 1. 本轮主目标

在不改变数据契约和页面主流程的前提下，把低风险页继续收敛到统一的头部、卡片与状态展示模式。

本轮只处理：

1. `frontend/src/pages/platform-check-page.tsx`
2. `frontend/src/pages/user-overview-page.tsx`

---

## 2. 本轮不做

1. 不新增领域组件。
2. 不改查询逻辑。
3. 不改路由和壳层。
4. 不扩到 `review / source detail / account` 等后续批次页面。
5. 不为本批顺手抽新一层共享组件。
6. 不进入后端 API 契约或 `src/**` 主线改造。

---

## 3. 允许复用的共享标准件

1. `PageHeader`
2. `SectionCard`
3. `StatCard`
4. `StatusBadge`
5. `EmptyState`

---

## 4. 影响文件

运行时代码默认只允许进入：

1. `frontend/src/pages/platform-check-page.tsx`
2. `frontend/src/pages/user-overview-page.tsx`
3. `frontend/src/shared/ui/status-badge.tsx`

测试文件可按需进入：

4. `frontend/src/pages/platform-check-page.test.tsx`
5. `frontend/src/pages/user-overview-page.test.tsx`
6. `frontend/src/shared/ui/status-badge.test.tsx`

文档文件可按需进入：

7. `docs/frontend/frontend-phase6-p6-1-boundary-card-v1.md`
8. `docs/README.md`

---

## 5. 当前代码证据

1. `platform-check-page.tsx` 已使用 `PageHeader / SectionCard / StatCard`，主问题是高可见状态表达还可以更统一。
2. `user-overview-page.tsx` 仍直接使用 `glass-card` 与手写头部结构。

---

## 6. 允许的改动类型

1. 页面头部改为统一 `PageHeader` 模式。
2. 旧 `glass-card` 的直接页面入口改为已有标准件承接。
3. 页面内空态和状态摘要改为已有标准件或更一致的表达。
4. 为本批实际改动页面补最小页面测试。
5. 为本批正在消费的 `StatusBadge` 补最小状态映射修正与测试。

---

## 7. 禁止事项

1. 不改变接口路径和返回字段使用方式。
2. 不改变业务按钮动作语义。
3. 不抽象新的通用表格、筛选或领域能力。
4. 不为了统一视觉顺手改别的页面。
5. 不把本批推进成“全站收旧视觉”的入口。

---

## 8. 默认验证档位

本轮至少执行：

1. `cd frontend && npm run typecheck`
2. `cd frontend && npm run check:rules`
3. `cd frontend && npm run test`
4. `cd frontend && npm run build`

本轮默认不强制新增 smoke，但若改动导致现有高可见截图基线受影响，应重新评估 `npm run test:smoke`。

---

## 9. 回滚边界

若本轮推进中发现范围失控，优先按以下顺序回滚：

1. 先撤回局部展示层统一，不动页面逻辑。
2. 再撤回新增测试中的非必要断言。
3. 不通过扩大共享组件改造来“补救”单页问题。
