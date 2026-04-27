# AGENTS.md — frontend/src/biz-system/entities

## 职责

1. 定义领域实体与前端 ViewModel。
2. 管理接口 DTO -> ViewModel 的映射规则。
3. 维护前端枚举语义（trend/status/period 等）。

## 规则

1. 保持纯函数映射，禁止副作用。
2. 关键字段必须有默认值策略，避免页面判空分散。
3. 变更字段时必须审计所有消费者（features/widgets）。
