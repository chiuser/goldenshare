# AGENTS.md — frontend/src/biz-system/shared

## 职责

1. 提供通用 UI 组件、api client、hooks、utils。
2. 维护设计 token 与通用交互模式。
3. 提供与后端契约对齐的基础请求层。

## 规则

1. shared 不依赖 feature/widgets/app。
2. API 错误模型统一，禁止页面各自定义错误协议。
3. 涉及鉴权头、刷新逻辑的修改必须回归 auth 相关页面。
