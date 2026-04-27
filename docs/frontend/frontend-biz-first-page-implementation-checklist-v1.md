# 首个业务页面落地清单 v1（页面骨架 + API 契约 + 四态 + smoke）

## 1. 目标

在 `frontend/src/biz-system/**` 下落地首个业务页面，作为后续页面复制模板。

本轮页面选型：`行情详情页（Quote Detail）`。

目标能力：

1. 页面骨架可访问。
2. 接口契约接通（最小 3 个接口）。
3. 完整四态（loading/empty/error/stale）。
4. 可执行 smoke 回归。

---

## 2. 范围与非范围

本轮范围：

1. 前端页面与前端数据组织。
2. 与现有后端接口对接（不改接口语义）。
3. 页面核心区块：基础信息 + K 线区 + 相关信息区。

本轮不做：

1. 分钟线能力（保持 API 降级逻辑）。
2. 公告正文复杂交互。
3. 二级页面（策略详情、新闻详情、深度诊断）。

---

## 3. API 契约基线（必须对齐）

接口依据：`docs/platform/quote-detail-api-spec-v1.md`

首批接入接口：

1. `GET /api/v1/quote/detail/page-init`
2. `GET /api/v1/quote/detail/kline`
3. `GET /api/v1/quote/detail/related-info`
4. 可选占位：`GET /api/v1/quote/detail/announcements`

契约门禁：

1. 页面只消费 ViewModel，不直接消费 DTO。
2. 错误按 `detail.code` 分流，不做字符串匹配。
3. 鉴权失败（401）走统一登录恢复流程。

---

## 4. 首批实现任务包（可执行）

## 4.1 包 A：页面骨架（P0）

目标：先让页面结构可跑通。

新增文件（建议）：

1. `frontend/src/biz-system/app/router.quote.tsx`
2. `frontend/src/biz-system/pages/quote-detail-page.tsx`
3. `frontend/src/biz-system/widgets/quote/quote-detail-layout.tsx`
4. `frontend/src/biz-system/widgets/quote/quote-header-panel.tsx`
5. `frontend/src/biz-system/widgets/quote/quote-chart-panel.tsx`
6. `frontend/src/biz-system/widgets/quote/quote-related-panel.tsx`

验收：

1. 路由可进入。
2. 页面骨架组件渲染完整。
3. 未接入真实数据时可显示 loading 占位。

## 4.2 包 B：契约与映射（P0）

目标：DTO -> ViewModel 单点收敛。

新增文件（建议）：

1. `frontend/src/biz-system/shared/api/quote-client.ts`
2. `frontend/src/biz-system/entities/quote/quote-dto.ts`
3. `frontend/src/biz-system/entities/quote/quote-view-model.ts`
4. `frontend/src/biz-system/entities/quote/mappers/map-page-init.ts`
5. `frontend/src/biz-system/entities/quote/mappers/map-kline.ts`
6. `frontend/src/biz-system/entities/quote/mappers/map-related-info.ts`

验收：

1. 页面无 DTO 直连使用。
2. mapper 单测可覆盖关键字段与默认值。
3. trend/价格/时间字段语义稳定。

## 4.3 包 C：Feature 交互（P1）

目标：页面功能闭环。

新增文件（建议）：

1. `frontend/src/biz-system/features/quote/use-quote-page-state.ts`
2. `frontend/src/biz-system/features/quote/use-quote-page-queries.ts`
3. `frontend/src/biz-system/features/quote/use-quote-kline-controls.ts`

交互最小闭环：

1. 标的切换（`ts_code`）。
2. 周期切换（day/week/month）。
3. 复权切换（none/forward/backward，按 security_type 限制）。

验收：

1. 参数切换会触发正确查询。
2. 不支持能力有明确降级提示（如分钟线）。

## 4.4 包 D：四态统一（P0）

目标：四态必须齐全且一致。

状态定义：

1. `loading`: skeleton 与区块占位。
2. `empty`: “暂无数据” + 下一步动作。
3. `error`: 错误提示 + 重试按钮 + request_id（若有）。
4. `stale`: 数据可能滞后提醒（展示 latest_trade_date 与提示语）。

新增文件（建议）：

1. `frontend/src/biz-system/shared/ui/state/quote-loading-state.tsx`
2. `frontend/src/biz-system/shared/ui/state/quote-empty-state.tsx`
3. `frontend/src/biz-system/shared/ui/state/quote-error-state.tsx`
4. `frontend/src/biz-system/shared/ui/state/quote-stale-banner.tsx`

验收：

1. 四态都能被人为触发验证。
2. 状态组件不与业务 API 强耦合。

## 4.5 包 E：smoke 与门禁（P0）

目标：形成首批回归底线。

新增测试（建议）：

1. `frontend/src/biz-system/entities/quote/mappers/__tests__/map-page-init.test.ts`
2. `frontend/src/biz-system/entities/quote/mappers/__tests__/map-kline.test.ts`
3. `frontend/src/biz-system/features/quote/__tests__/use-quote-page-state.test.tsx`
4. `frontend/src/biz-system/pages/__tests__/quote-detail-page.test.tsx`
5. `frontend/tests/smoke/quote-detail.smoke.spec.ts`

必跑门禁：

1. `npm run check:rules`
2. `npm run test`
3. `npm run build`
4. `npm run test:smoke:ci -- quote-detail`（或等价定向 smoke）

---

## 5. 视觉规范执行点（v13）

必须检查：

1. 红涨绿跌语义正确。
2. Token 化颜色/间距/字号，无页面散乱硬编码。
3. Panel 与模块层级符合 v13 目录规范。
4. 图表区、指标区、说明区信息层级清晰。

---

## 6. 交付物清单

首批实现结束时必须具备：

1. 可访问的 Quote Detail 页面。
2. 3 个核心 API 已接入并可切换参数。
3. 四态可观测。
4. smoke 可执行且通过。
5. 页面实现可作为后续业务页模板复制。

---

## 7. 风险与应对

风险：

1. 页面快速开发时绕过 mapper，直接用 DTO。
2. 组件实现回退到默认模板风格。
3. smoke 只测 happy path，遗漏四态。

应对：

1. PR checklist 强制检查 DTO 泄漏。
2. 视觉评审对照 v13 showcase。
3. smoke 增加错误与空态场景。
