# AGENTS.md — frontend/src/biz-system/app

## 职责

1. 路由注册与页面装配。
2. 全局 Provider（QueryClient、AuthContext、ThemeProvider）。
3. 全局错误边界与应用级壳组件。

## 不负责

1. 不负责业务查询细节。
2. 不负责接口字段转换。
3. 不负责页面视觉细节实现。

## 规则

1. 页面仅通过 `features/widgets` 装配。
2. 新路由必须附带访问控制策略（匿名/登录/角色）。
3. 入口层改动必须补最小路由 smoke。
