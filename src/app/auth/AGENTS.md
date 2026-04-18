# AGENTS.md — src/app/auth 子域规则

## 适用范围

本文件适用于 `src/app/auth/` 目录及其所有子目录。

若更深层目录存在更具体的 `AGENTS.md`，应同时遵守；发生冲突时，以更靠近当前目录的规则为准。

---

## 目录定位（硬约束）

`src/app/auth` 是 app 壳下的 auth/admin 子域，不是 `biz` 或 `ops` 子系统目录。

它负责“应用壳中的认证与账户管理装配”，不承接跨域业务计算。

---

## 这里负责什么

`src/app/auth` 负责：

1. 认证接线（JWT/密码/安全相关接线）
2. 当前用户与权限依赖（dependencies / guards）
3. `auth/admin/user` 相关服务
4. 对应 schema 与账户模型组织
5. auth/admin 路由最终落位

---

## 这里不负责什么

`src/app/auth` 不负责：

1. `biz` 查询逻辑
2. `ops` 运维治理逻辑
3. `foundation` 底层同步逻辑

若出现以上职责，应分别归位到 `src/biz`、`src/ops`、`src/foundation`。

---

## 拆分阶段规则

platform 拆分期间，auth/admin 新主实现优先进入 `src/app/auth`，并对旧 `src/platform` 路径保留薄兼容壳。

禁止在本目录中发明新的跨域业务规则；本目录只承接认证与账户域的壳层与服务组织职责。

---

## 完成任务时说明要求

每次修改 `src/app/auth` 后需说明：

1. 本次改动属于认证接线 / 依赖 / 服务 / schema / 模型 / 路由中的哪一类
2. 是否引入了跨域业务规则（如有应回滚并归位）
3. 是否影响 `platform -> app/auth` 的拆分路径与兼容壳策略
