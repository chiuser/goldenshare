# AGENTS.md — frontend/src/biz-system/features

## 职责

1. 承载业务功能切片（如行情详情、情绪分析、板块观察）。
2. 组织用户交互流程与页面状态机。
3. 调用 `entities` 和 `shared/api` 完成功能编排。

## 规则

1. 一个 feature 一个边界，不跨 feature 直接改状态。
2. API 返回先映射到 ViewModel 再渲染。
3. 必须覆盖 loading/empty/error/stale 四态。
4. 禁止在 feature 内写通用组件样式常量。
