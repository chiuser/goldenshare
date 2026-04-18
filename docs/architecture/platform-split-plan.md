# platform 拆分准备计划（app / biz / ops）

## 目标与范围

本计划用于启动 `src/platform` 的拆分准备阶段，目标是把 `platform` 中的职责逐步回归到：

- `src/app`：应用壳与组合根（composition root）
- `src/biz`：业务 API / Query / Service / Schema
- `src/ops`：运维 API / Query / Service / Schema

本轮仅做规划，不迁移任何实现代码。

---

## `src/platform` 目录职责盘点与归属倾向

| 目录 | 当前职责（基于现状代码） | 归属倾向 |
| --- | --- | --- |
| `platform/api` | 含 `/api` 与 `/api/v1` 聚合路由；同时挂载 auth/users/admin/share；并桥接 `src.ops.api.router` 与 `src.biz.api.*` | **混合**：聚合层偏 `app`；业务端点偏 `biz`；运维端点偏 `ops`；auth/admin 用户管理偏 `app/auth` |
| `platform/auth` | JWT、密码、鉴权依赖、认证领域对象、用户仓储、安全工具 | **app**（`app/auth`） |
| `platform/dependencies` | DB session 依赖注入（`get_db_session`） | **app**（`app/dependencies` 或 `app/di`） |
| `platform/exceptions` | Web 异常类型与 FastAPI 异常处理注册 | **app**（`app/exceptions`） |
| `platform/models` | 当前主要是 `models/app/*`：用户、角色、权限、refresh token、审计、邀请码等认证账户模型 | **app**（`app/models` 或 `app/auth/models`） |
| `platform/queries` | 目前核心是 `share_market_query_service`，面向行情业务聚合查询 | **biz**（`biz/queries`） |
| `platform/schemas` | `share`（业务返回）、`auth/user_admin/common`（认证与管理端）混合 | **混合**：`share` 偏 `biz`；`auth/user_admin/common` 偏 `app/auth` |
| `platform/services` | `auth_service`、`admin_user_service`、`user_service`，主要是认证与账户管理 | **app**（`app/auth/services`） |
| `platform/web` | FastAPI app 创建、middleware、lifespan、静态资源挂载、运行入口 | **app**（`app/web`） |

---

## 第一批最安全拆分候选（仅候选，不执行）

### A. app 壳直迁候选（低风险）

1. `platform/web/*` -> `app/web/*`（保持接口与运行行为不变）
2. `platform/dependencies/db.py` -> `app/dependencies/db.py`
3. `platform/exceptions/web.py` -> `app/exceptions/web.py`
4. `platform/auth/*` -> `app/auth/*`（先按原文件结构平移）
5. `platform/models/app/*` -> `app/models/*`（或 `app/auth/models/*`，先保持 schema/table 不变）

### B. biz 业务候选（低到中风险）

1. `platform/queries/share_market_query_service.py` -> `biz/queries/share_market_query_service.py`
2. `platform/schemas/share.py` -> `biz/schemas/share.py`
3. `platform/api/v1/share.py` -> `biz/api/share.py`（或并入既有 `biz.api.market`）

### C. ops 候选（当前基本已在 ops）

- `platform/api/v1/router.py` 已挂载 `src.ops.api.router`，说明运维 API 主实现已在 `ops`，本阶段不需要从 `platform` 再拆新的 ops 主实现。

---

## 第一批实际迁移（当前批次）

本轮已明确执行范围仅包含两个 app 壳基础模块：

1. `src/platform/dependencies/db.py` -> `src/app/dependencies/db.py`
2. `src/platform/exceptions/web.py` -> `src/app/exceptions/web.py`

执行原则：

- 仅迁移上述两个模块，不扩大范围
- `src/platform` 旧路径保留 deprecated 兼容壳
- 外部行为保持不变
- 不触碰 `platform/web/app.py`、`platform/auth/*`、`platform/models/*`、`platform/api` 聚合链路

---

## 第一批 biz 迁移链（当前批次）

本轮第一条 biz 业务线迁移仅包含 share 三件套：

1. `src/platform/queries/share_market_query_service.py` -> `src/biz/queries/share_market_query_service.py`
2. `src/platform/schemas/share.py` -> `src/biz/schemas/share.py`
3. `src/platform/api/v1/share.py` -> `src/biz/api/share.py`

执行原则：

- 仅迁移 share query / share schema / share API，不扩大范围
- `src/platform` 旧路径保留 deprecated 兼容壳
- 外部行为与返回契约保持不变
- 不触碰 `platform/api/router.py` 与 `platform/api/v1/router.py` 聚合入口

---

## auth/admin 整链拆分计划（准备阶段）

本阶段只做规划，不迁移任何实现代码。当前 auth/admin 整链范围如下：

- `src/platform/auth/*`
- `src/platform/services/auth_service.py`
- `src/platform/services/admin_user_service.py`
- `src/platform/services/user_service.py`
- `src/platform/schemas/auth.py`
- `src/platform/schemas/user_admin.py`
- `src/platform/models/app/*`
- `src/platform/api/v1/auth.py`
- `src/platform/api/v1/users.py`
- `src/platform/api/v1/admin.py`
- `src/platform/api/v1/admin_users.py`

### 归属建议（目标态）

- `platform/auth/*` -> `app/auth`（认证接线、当前用户/权限依赖、JWT/密码/安全工具、认证域对象）
- `platform/services/{auth,admin_user,user}_service.py` -> `app/auth/services`
- `platform/schemas/{auth,user_admin}.py` -> `app/auth/schemas`
- `platform/models/app/*` -> `app/models`（或 `app/auth/models`，按账户域组织）
- `platform/api/v1/{auth,users,admin,admin_users}.py` -> `app/auth/api`

### 最安全的第一批候选（下一步执行批）

1. 先迁内部依赖最小、对路由聚合无侵入的模块：
   - `platform/auth/constants.py`
   - `platform/auth/domain.py`
   - `platform/auth/password_service.py`
2. 再迁账户域 schema / model 壳层组织文件：
   - `platform/schemas/auth.py`
   - `platform/schemas/user_admin.py`
   - `platform/models/app/__init__.py`（仅组织层）
3. 最后迁 auth/admin API + service 主实现（保持旧路径 shim）：
   - `platform/services/{auth,admin_user,user}_service.py`
   - `platform/api/v1/{auth,users,admin,admin_users}.py`

### 继续暂缓项

- `platform/api/router.py`
- `platform/api/v1/router.py`
- `platform/web/app.py`

暂缓原因：

- 这三处是当前 HTTP 入口与聚合链路核心，提前切入口会放大全局回归面。
- 只有当 auth/admin 子路由在 `src/app/auth` 完整落位并通过回归后，才适合做入口切换。

### 迁移顺序建议

1. 先建 `src/app/auth` 目录边界与 AGENTS（本轮完成）
2. 迁 auth 内核小模块（constants/domain/password）
3. 迁 schemas/models 组织层
4. 迁 services
5. 迁 auth/admin API
6. 最后处理 `platform/api/v1/router.py` 与 `platform/api/router.py` 聚合切换

### 风险点

1. 鉴权依赖链风险：`dependencies -> jwt -> repository -> services -> schemas`，需要整链回归。
2. 账户模型风险：`platform/models/app/*` 与 Alembic/metadata 装载需保持兼容。
3. API 契约风险：登录、权限、管理员接口返回结构不能变化。
4. 聚合入口风险：过早改 router 会影响 biz/ops/app 三方路由挂载稳定性。

---

## auth 第一批真实迁移（当前批次）

本轮仅执行 `src/platform/auth/*` 内低风险 wiring/helper 模块迁移，实际范围如下：

1. `src/platform/auth/constants.py` -> `src/app/auth/constants.py`
2. `src/platform/auth/domain.py` -> `src/app/auth/domain.py`
3. `src/platform/auth/password_service.py` -> `src/app/auth/password_service.py`
4. `src/platform/auth/security_utils.py` -> `src/app/auth/security_utils.py`

执行原则：

- 仅迁移上述 4 个 helper 模块，不扩大范围
- `src/platform/auth/*` 旧路径保留 deprecated 兼容壳
- 外部行为保持不变
- 不触碰 `auth_service/admin_user_service/user_service`
- 不触碰 `schemas/models/api/router/web` 聚合链路

本轮明确暂缓：

- `src/platform/auth/dependencies.py`（依赖 DB 会话、角色权限模型与用户仓储，耦合更高）
- `src/platform/auth/jwt_service.py`（依赖 settings + WebAppError，建议与 dependencies 一起收敛）
- `src/platform/auth/user_repository.py`（直接 ORM 访问 `AppUser`，属于更高耦合层）

---

## 需继续暂缓的部分

1. **router 聚合层**
   - `platform/api/router.py`
   - `platform/api/v1/router.py`
   - 原因：当前承担全局入口聚合（app + biz + ops）。应在子路由完成迁移后最后切换。

2. **auth/admin 端点整体改挂载**
   - `platform/api/v1/auth.py`
   - `platform/api/v1/users.py`
   - `platform/api/v1/admin.py`
   - `platform/api/v1/admin_users.py`
   - 原因：依赖 `platform/auth + platform/services + platform/schemas` 的整链，宜在 app/auth 模块先落位后整体切换。

3. **`platform/schemas/common.py` 的最终归属**
   - 同时被 app-auth 与业务返回使用，需在路由拆分后再决定是否拆成 `app`/`biz` 两份或提炼共享 schema。

---

## router 聚合层的最终处理建议（最后一步）

建议采用“最后切入口”的方式处理：

1. 先完成 app/biz/ops 三侧子路由与依赖迁移。
2. 在 `src/app` 建立新的聚合入口（例如 `app/api/router.py`）。
3. 新入口只负责 `include_router(...)`，不承载业务实现。
4. 验证 `/api/health`、`/api/v1/*` 全量路由兼容后，再将 `platform/api/router.py` 与 `platform/api/v1/router.py` 退化为 deprecated shim。

---

## 风险点

1. **聚合路由耦合风险**
   - `platform/api/v1/router.py` 同时聚合 app-auth、biz、ops。提前迁入口会导致大面积路径回归风险。

2. **auth 链路一致性风险**
   - `auth dependencies -> services -> models -> schemas` 关联紧密，需按“整链迁移”而非零散文件迁移。

3. **schema 双归属风险**
   - `platform/schemas` 当前混合 app-auth 与 biz 返回模型，需避免迁移中出现交叉 import 回流。

4. **运行入口稳定性风险**
   - `platform/web/app.py` 当前承载生产入口语义；迁移必须以行为等价为先，避免顺手改启动逻辑。

---

## 迁移顺序建议（准备阶段之后）

1. **阶段 1（app 壳基础）**
   - 先迁 `web/dependencies/exceptions/auth/models` 到 `src/app`，保持路径兼容壳。
2. **阶段 2（biz 业务块）**
   - 先迁 share query/schema/api 到 `src/biz`，保持返回契约不变。
3. **阶段 3（app-auth API）**
   - 迁 `auth/users/admin/admin_users` API 及其 schema/service 到 `src/app` 子域。
4. **阶段 4（最后切入口）**
   - 收敛 `platform/api/router.py` 与 `platform/api/v1/router.py` 到 app 聚合层，并将旧路径降为 shim。

---

## 与当前主线的边界

- 本计划不触碰 `history_backfill_service.py` 与 `market_mood_walkforward_validation_service.py` 两个专项项。
- 本计划不修改 CLI 与依赖矩阵测试规则。
- 本计划只定义拆分路线与边界，不执行实现迁移。
