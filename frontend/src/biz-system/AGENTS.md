# AGENTS.md — frontend/src/biz-system 研发基线

## 适用范围

本文件适用于 `frontend/src/biz-system/` 及其子目录。
若子目录存在更近的 `AGENTS.md`，以更近规则为准。

---

## 1. 目标定位

`biz-system` 是行情业务前端主工程目录，职责是：

1. 复用页面架构（布局、路由组织、页面骨架）。
2. 使用自有设计系统与组件目录（v13）。
3. 消费自有后端接口（`/api/v1/quote/*`、`/api/v1/market/*` 等）。

不允许：

1. 复用 `example/app` 的后端、鉴权、业务实现。
2. 直接引入旧平台遗留页面实现作为主代码。

---

## 2. 分层边界

- `app/`：组合根、路由装配、provider 装配。
- `features/`：业务功能切片（页面功能和交互流程）。
- `entities/`：领域实体与 ViewModel 映射。
- `widgets/`：页面级区块（Panel 级组合模块）。
- `shared/`：通用 UI、api、hooks、utils。

硬约束：

1. `shared` 不依赖 `features/widgets`。
2. `entities` 不依赖具体页面组件。
3. `app` 只做装配，不写业务规则。

---

## 3. 设计与组件规范

必须遵守：

1. `docs/frontend/frontend-biz_design_system_v13.md`
2. `docs/frontend/frontend-biz_component_catalog_v13.md`
3. `docs/frontend/frontend-biz_component_showcase_v13.html`
4. `docs/frontend/frontend-current-standards.md`

---

## 4. 开发与验证流程

每个功能最小流程：

1. 明确接口契约（参数/返回/错误）。
2. 先写 ViewModel 与空/错/加载状态。
3. 再落组件和交互。
4. 补最小测试（至少渲染 + 关键交互）。
5. 跑规则检查与 smoke。

最小门禁：

1. `npm run check:rules`
2. `npm run test`
3. 受影响页面 smoke（按变更范围执行）

中等及以上需求（新增页面、复杂交互、跨接口数据编排）必须新增“详细技术方案”并先评审，评审通过后方可编码。

---

## 5. 质量红线（补充）

1. 不允许页面层直接拼接后端原始数据形成业务结论，必须走 `entities` 映射。
2. 不允许兼容方案、临时方案；若发现契约不合理，先提后端/前端契约收敛方案。
3. bug 修复必须先定位根因并说明修复合理性，不允许“只改表现层”。
4. 单文件超过 `400` 行必须评估拆分；超过 `600` 行必须拆分。
5. 同一模式出现三次以上必须抽象，不允许继续复制粘贴。

---

## 6. 禁止事项

1. 禁止页面直接拼接后端原始字段绕过 schema。
2. 禁止硬编码颜色破坏 token 体系。
3. 禁止把鉴权逻辑散落在页面组件中。
4. 禁止无文档的跨层依赖。
