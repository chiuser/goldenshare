# AGENTS.md — frontend/src/biz-system/widgets

## 职责

1. 负责页面级区块组合（Panel、图表区、榜单区）。
2. 承接可复用的大块 UI 布局。
3. 连接 feature 提供的数据与 shared/ui 组件。

## 规则

1. Widget 只做组合，不直接请求 API。
2. 视觉规范必须遵守 v13 组件目录。
3. 复杂交互逻辑应回落 feature 层，避免 widget 膨胀。
