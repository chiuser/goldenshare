# AGENTS.md — src/platform 拆分准备阶段规则

## 适用范围

本文件适用于 `src/platform/` 目录及其所有子目录。

---

## 当前阶段定义（已收紧）

`src/platform` 现已进入 **拆分准备阶段**，目标是按职责拆解到：

- `src/app`（应用壳 / composition root）
- `src/biz`（业务 API / Query / Schema / Service）
- `src/ops`（运维 API / Query / Schema / Service）

`src/platform` 不再是可持续承接新主实现的目录。

---

## 明确归属方向（硬约束）

### 未来进入 `app`

- `platform/web`
- `platform/auth`
- `platform/dependencies`
- `platform/exceptions`
- `platform/services/{auth_service,admin_user_service,user_service}`
- `platform/schemas/{auth,user_admin}`
- `platform/api/v1/{auth,users,admin,admin_users}`
- `platform/models/app/*`（账户/认证模型，未来归 `src/app/models`）
- 以及最终的 router 聚合职责

### 未来进入 `biz`

- 业务 API / Query / Schema / Service

### 未来进入 `ops`

- 运维 API / Query / Schema / Service

### 例外说明

- `platform/models` 仍需按语义细分：账户/认证模型归 `app/models`，业务/运维模型分别归 `biz`/`ops`。

---

## 本目录允许做什么

### 允许

1. 现有 bug 的最小修复
2. 为拆分准备增加注释与文档化说明
3. 将旧路径改薄（compat shim / 转发）
4. 不改变外部行为的最小维护

### 不允许

1. 在 `platform` 新增长期主实现
2. 在 `platform/api|queries|schemas|services` 新增应归属 `biz/ops` 的新能力
3. 把 `platform` 当成第四个业务子系统继续扩张
4. 未经计划直接做大规模搬迁

---

## router 聚合层处理规则（必须最后动）

以下文件属于当前入口聚合层，**默认最后迁移**，不在第一批拆分中处理：

- `platform/api/router.py`
- `platform/api/v1/router.py`

原因：

- 它们同时聚合 app-auth、biz、ops 路由，提前切入口会放大回归风险。
- auth/admin 整链拆分期间，本轮也不允许迁移上述聚合入口。
- 账户模型拆分准备期间，本轮同样不允许迁移上述聚合入口与 `platform/web/app.py`。

### final cutover 准备阶段（当前）

以下文件已进入 final cutover 准备阶段：

- `platform/api/router.py`
- `platform/api/v1/router.py`
- `platform/web/app.py`
- `platform/api/v1/health.py`
- `platform/schemas/common.py`

当前阶段仅允许：

1. 规划文档完善
2. AGENTS 边界补位

当前阶段明确禁止：

1. 真实代码迁移
2. 入口行为改写
3. import 路径大切换

---

## 迁移执行规则

当任务涉及 `platform`，先判定目标归属：

1. app 壳逻辑 -> `src/app`
2. 业务逻辑 -> `src/biz`
3. 运维逻辑 -> `src/ops`

若归属明确，禁止继续把新增主逻辑放在 `platform`。

---

## 依赖与边界提醒

1. 禁止引入 `foundation -> platform` 反向依赖。
2. `platform` 不应继续承接共享基础设施（db/contracts/utils）。
3. 拆分过程中优先“路径收敛 + 兼容壳”，避免行为改写。

---

## 完成任务后的说明要求

每次改动 `platform` 后，必须说明：

1. 本次改动是否只做准备/收敛，而非新增主实现
2. 改动内容更偏 `app` / `biz` / `ops` 哪一类
3. 是否触及 router 聚合层（如触及需说明必要性）
4. 下一步建议迁出的最小单元

---

## 禁止扩大范围

处理 `platform` 相关任务时，不得顺手做：

1. 认证体系大重写
2. router 全量改造
3. schema 全量重写
4. 一次性整体搬迁 platform

每轮只做一个清晰阶段目标，并保持外部行为稳定。
