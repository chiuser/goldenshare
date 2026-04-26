# 前端专项：Overview 旧视觉遗留收口边界卡 v1

> 角色说明：本文件用于约束 `ops-v21-overview-page.tsx` 的旧视觉遗留收口范围。
> 当前统一强约束请以 [frontend-current-standards.md](/Users/congming/github/goldenshare/docs/frontend/frontend-current-standards.md) 为准。

## 1. 本轮主目标

在不改数据状态总览页业务语义和数据契约的前提下，清理页面层明确遗留的旧视觉入口，收回统一反馈条、状态表达和中性卡面。

本轮只处理：

1. `frontend/src/pages/ops-v21-overview-page.tsx`

---

## 2. 本轮不做

1. 不改 `/api/v1/ops/overview`、`/api/v1/ops/dataset-cards`、`/api/v1/ops/layer-snapshots/latest` 契约。
2. 不重做页面信息架构。
3. 不把页面拆成新的子组件或新共享组件。
4. 不扩到 `review / source / account` 等其他页面。
5. 不触碰后端 `src/**` 主线。

---

## 3. 允许复用的共享标准件

1. `SectionCard`
2. `StatCard`
3. `StatusBadge`
4. `AlertBar`

---

## 4. 影响文件

运行时代码默认只允许进入：

1. `frontend/src/pages/ops-v21-overview-page.tsx`

测试与门禁可按需进入：

2. `frontend/src/pages/ops-v21-overview-page.test.tsx`
3. `frontend/e2e/smoke-visual.spec.ts-snapshots/*overview*`

文档可按需进入：

4. `docs/frontend/frontend-overview-legacy-visual-cleanup-boundary-card-v1.md`
5. `docs/README.md`

---

## 5. 当前代码证据

1. 页面层当前仍直接写 `glass-card`。
2. 卡片内部仍有黄底自定义提示块与手写 `Badge` 颜色样式。
3. 页面错误态和空态仍使用旧 `Alert` 入口。
4. 当前页已进入 smoke / visual gate，说明这轮视觉调整应走截图基线更新纪律。

---

## 6. 允许的改动类型

1. 清理页面层 `glass-card` 直写。
2. 将错误态与空态反馈收回 `AlertBar`。
3. 将配置状态块收回中性卡面和统一 `StatusBadge`。
4. 为页面补最小单测，保护“不再使用页面级旧视觉类”。
5. 刷新 overview 页现有 smoke / visual 基线。

---

## 7. 禁止事项

1. 不改变分组方式、状态计算和详情跳转语义。
2. 不新增新的共享组件族。
3. 不顺手处理大页控厚。
4. 不把这轮扩大成 overview 页面重构。

---

## 8. 默认验证档位

本轮至少执行：

1. `cd frontend && npm run typecheck`
2. `cd frontend && npm run check:rules`
3. `cd frontend && npm run test`
4. `cd frontend && npm run build`
5. `cd frontend && npm run test:smoke:update`
6. `cd frontend && npm run test:smoke`

---

## 9. 回滚边界

若本轮推进中发现范围失控，优先按以下顺序回滚：

1. 先撤回卡片内部视觉收敛，不动页面结构。
2. 再撤回 `AlertBar` 替换。
3. 不通过新增共享抽象来“兜住”单页问题。
