# 行情业务系统工程基线 v1

## 1. 文档定位

本文件定义“新建行情业务系统”的工程环境基线，覆盖：

1. 目录结构
2. 目录 AGENTS 约束
3. 设计与开发原则
4. 集成开发流程
5. 验证与测试门禁

本文件是工程执行入口，具体技术细节见配套文档：

1. `frontend-biz-technology-stack-and-library-standard-v1.md`
2. `frontend-biz-web-api-contract-standard-v1.md`
3. `frontend-biz-data-model-and-composition-standard-v1.md`

---

## 2. 目录结构（已建立）

```text
frontend/src/biz-system/
  AGENTS.md
  app/
    AGENTS.md
  features/
    AGENTS.md
  entities/
    AGENTS.md
  widgets/
    AGENTS.md
  shared/
    AGENTS.md
```

分层职责：

1. `app`: 组合根、路由装配、Provider 装配。
2. `features`: 功能切片、用户流程、页面状态。
3. `entities`: 领域实体和 ViewModel 映射。
4. `widgets`: 页面级模块组合。
5. `shared`: 通用组件、请求层、hooks、utils。

---

## 3. 核心设计原则

1. 只复用页面架构，不复用外部后端与鉴权实现。
2. 视觉与组件只走 v13 设计系统，不回退默认模板风格。
3. 后端接口、鉴权、用户体系只走本仓 `app/auth + biz/api`。
4. 页面消费稳定 ViewModel，不直接拼装底层原始字段。
5. 先定义契约，再写页面，再做联调。

---

## 4. 集成开发流程（强制）

## 4.1 Phase A：契约先行

1. 在 `biz` 侧确认 API schema（输入/输出/错误）。
2. 在 `entities` 侧定义 DTO -> ViewModel 映射。
3. 明确状态语义：`loading/empty/error/stale`。

交付物：

1. 接口契约文档更新
2. 前端 ViewModel 定义
3. 错误语义与降级策略

## 4.2 Phase B：页面骨架

1. `app` 完成路由与权限装配。
2. `widgets` 完成页面骨架（Panel 区块组合）。
3. `features` 接入 mock 或最小真实数据。

交付物：

1. 可访问页面
2. 骨架与状态页可用

## 4.3 Phase C：组件与视觉落位

1. 领域组件按 v13 catalog 接入。
2. token 对齐、排版对齐、涨跌色语义对齐。
3. 修复空态/错态/滞后态渲染。

交付物：

1. 视觉一致性通过
2. 页面行为与交互达标

## 4.4 Phase D：联调与门禁

1. 接入真实 biz API。
2. 跑前端规则检查和自动化测试。
3. 做关键路径 smoke（登录 -> 业务页 -> 关键交互）。

交付物：

1. 可交付页面
2. 回归记录

---

## 5. 验证与测试门禁

每次合并前最小门禁：

1. `npm run check:rules`
2. `npm run test`
3. 受影响页面 smoke（按变更范围执行）

建议增加：

1. 关键页面截图基线（如行情详情页）
2. 关键接口契约测试（字段变更告警）

---

## 6. 风险与回滚

1. 若 API 契约未稳定，不进入页面细化。
2. 若设计 token 未对齐，不批量复制页面。
3. 若鉴权链路异常，先修 auth，再继续业务页联调。

回滚策略：

1. 页面路由可按 feature 级别回滚。
2. API 变更需保持 schema 版本标记，避免静默破坏。

---

## 7. 里程碑建议

1. M1：目录与 AGENTS 基线完成（已完成）。
2. M2：技术栈与 API 契约文档冻结。
3. M3：首个业务页面骨架联调通过。
4. M4：v13 视觉规范与回归门禁通过。
