# AGENTS.md — `src/app/auth` 认证与账户子域规则

## 适用范围

本文件适用于 `src/app/auth/` 及其子目录。

---

## 目录定位

`src/app/auth` 承接认证、权限与管理员账户管理链路。

负责：

1. 认证依赖与权限依赖
2. JWT/密码/安全工具
3. auth/admin/user 相关服务、schema、API

不负责：

1. Biz 业务分析逻辑
2. Ops 运维治理逻辑
3. Foundation 同步与存储逻辑

---

## 硬约束

1. 不在此目录发明跨域业务规则。
2. 保持认证接口契约与权限语义稳定。
3. 模型结构变更需走独立数据库变更流程，不在此目录顺手改。

---

## 改动后说明

每次改动需说明：

1. 改动落在 helpers/dependencies/services/schemas/api 哪一层
2. 是否影响鉴权链路与返回契约
3. 是否引入跨域依赖（应避免）
