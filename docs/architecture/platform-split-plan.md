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

## auth 第二批链路判定与迁移顺序（本轮仅设计，不改代码）

### 1) 调用链判定（基于当前代码实扫）

#### `src/platform/auth/dependencies.py`

- 直接被以下 API 层消费：
  - `src/platform/api/v1/auth.py`（`require_authenticated`）
  - `src/platform/api/v1/users.py`（`require_authenticated`）
  - `src/platform/api/v1/admin.py`（`require_admin`）
  - `src/platform/api/v1/admin_users.py`（`require_permission(...)`）
  - `src/ops/api/*` 多个路由（大量 `require_admin` / 少量 `require_authenticated`）
  - `src/biz/api/quote.py`、`src/biz/api/market.py`（`require_quote_access`）
  - `src/biz/api/share.py`（`require_admin`）
- 内部依赖：
  - `src/platform/auth/jwt_service.py`
  - `src/platform/auth/user_repository.py`
  - `src/platform/models/app/auth_user_role.py`
  - `src/platform/models/app/auth_role_permission.py`
  - `src/platform/dependencies`（DB session）
  - `src/platform/exceptions`、`src/platform/web/settings`

#### `src/platform/auth/jwt_service.py`

- 被以下模块直接调用：
  - `src/platform/auth/dependencies.py`
  - `src/platform/services/auth_service.py`
  - `src/ops/api/schedules.py`（流式 token 校验）
- 依赖：
  - `src/platform/web/settings`
  - `src/platform/exceptions`
  - `src/app/auth/domain.py`（通过 `TokenPayload`）

#### `src/platform/auth/user_repository.py`

- 被以下模块直接调用：
  - `src/platform/auth/dependencies.py`
  - `src/platform/services/auth_service.py`
  - `src/platform/services/admin_user_service.py`
  - `src/ops/api/schedules.py`
- 依赖：
  - `src/platform/models/app/app_user.py`（ORM）

#### services / schemas / models / api 关联链

- `src/platform/services/auth_service.py`
  - 当前由 `src/platform/api/v1/auth.py` 独占调用
  - 直接依赖 `JWTService` + `UserRepository` + `platform.models.app/*` 全套账户模型
- `src/platform/services/admin_user_service.py`
  - 当前由 `src/platform/api/v1/admin_users.py` 独占调用
  - 依赖 `UserRepository` + `AuthService` + 账户模型
- `src/platform/services/user_service.py`
  - 当前仅被 `src/platform/api/v1/users.py` 调用
  - 逻辑轻（仅透传当前用户）
- `src/platform/schemas/auth.py`
  - 由 `src/platform/api/v1/auth.py` 与 `src/platform/api/v1/users.py` 使用
- `src/platform/schemas/user_admin.py`
  - 由 `src/platform/api/v1/admin_users.py` 使用
- `src/platform/models/app/*`
  - 被 `auth_service/admin_user_service/dependencies` 使用
  - 另有 `src/ops/queries/*`（如 execution/schedule/probe/resolution query）直接读 `AppUser`

### 2) 必须成组迁移 vs 可单独迁移

#### 必须成组迁移

1. **鉴权基础组三件套**
   - `platform/auth/dependencies.py`
   - `platform/auth/jwt_service.py`
   - `platform/auth/user_repository.py`
   - 原因：`dependencies` 同时依赖后两者，且被 `platform + ops + biz` 路由横向复用，拆分时必须保持同一批次兼容切换。

2. **终端用户认证链**
   - `platform/services/auth_service.py`
   - `platform/services/user_service.py`
   - `platform/schemas/auth.py`
   - `platform/api/v1/auth.py`
   - `platform/api/v1/users.py`
   - 原因：API 与 schema/service 强绑定，拆分中不能把 service/schema/api 分开漂移。

3. **管理员账户管理链**
   - `platform/services/admin_user_service.py`
   - `platform/schemas/user_admin.py`
   - `platform/api/v1/admin.py`
   - `platform/api/v1/admin_users.py`
   - 原因：管理端接口依赖用户/角色/邀请/审计同一套服务语义，拆分应成组完成。

#### 可单独先迁（但收益有限）

- `platform/services/user_service.py` 理论上可单独迁，但因其仅被 `/users/me` 一处调用，单迁收益低，建议放入“终端用户认证链”成组处理。

### 3) 第二批推荐顺序（仅计划）

#### 第二批-A（最安全候选）

- 仅做鉴权基础组三件套迁移：
  - `dependencies.py` + `jwt_service.py` + `user_repository.py`
- 并同步维护 `platform/auth/__init__.py` 导出与旧路径 deprecated 兼容壳。
- 目标：先把跨 `platform/ops/biz` 共用的 auth ingress 稳定收敛到 `src/app/auth`。

#### 第二批-B（中风险，成组）

- 迁移“终端用户认证链”：
  - `auth_service.py`、`user_service.py`、`schemas/auth.py`、`api/v1/auth.py`、`api/v1/users.py`
- 前提：第二批-A 已稳定，且登录/刷新/登出链路回归通过。

#### 第二批-C（中高风险，成组）

- 迁移“管理员账户管理链”：
  - `admin_user_service.py`、`schemas/user_admin.py`、`api/v1/admin.py`、`api/v1/admin_users.py`
- 前提：第二批-B 稳定，且 admin 权限链回归通过。

#### 最后处理项（继续暂缓）

- `platform/models/app/*` 的目录归位与统一命名（需联动 `ops/queries` 对 `AppUser` 的引用）
- `platform/api/v1/router.py`、`platform/api/router.py`、`platform/web/app.py` 聚合与入口切换

### 4) 继续暂缓原因与风险点

1. `platform/models/app/*` 仍是 auth/admin 与 ops 查询共用模型层，过早迁移会放大回归面。
2. `platform/api/router.py` 与 `platform/api/v1/router.py` 属全局聚合入口，必须最后切。
3. `platform/web/app.py` 是运行入口，需在子路由稳定后再做组合根切换。

---

## auth 第二批-A 真实迁移（当前批次）

本轮第二批-A 实际执行范围严格限定为鉴权基础组三件套：

1. `src/platform/auth/dependencies.py` -> `src/app/auth/dependencies.py`
2. `src/platform/auth/jwt_service.py` -> `src/app/auth/jwt_service.py`
3. `src/platform/auth/user_repository.py` -> `src/app/auth/user_repository.py`

执行原则：

- 仅迁移上述三个模块，不扩大范围
- 三者按一组迁移，不拆分
- `src/platform/auth/*` 旧路径保留 deprecated 兼容壳，保证旧 import 继续可用
- 外部行为保持不变
- 不触碰 `services / schemas / models / api / router / web` 链路

---

## auth 第二批-B 真实迁移（当前批次）

本轮第二批-B 实际执行范围严格限定为“终端用户认证链”5个模块：

1. `src/platform/services/auth_service.py` -> `src/app/auth/services/auth_service.py`
2. `src/platform/services/user_service.py` -> `src/app/auth/services/user_service.py`
3. `src/platform/schemas/auth.py` -> `src/app/auth/schemas/auth.py`
4. `src/platform/api/v1/auth.py` -> `src/app/auth/api/auth.py`
5. `src/platform/api/v1/users.py` -> `src/app/auth/api/users.py`

执行原则：

- 仅迁移上述 5 个模块，不扩大范围
- 旧路径保留 deprecated 兼容壳，确保旧 import 路径继续可用
- 外部行为、返回契约、鉴权链路保持不变
- 不触碰 `admin` 链、`models/app/*`、`router` 聚合层与 `web/app.py`

---

## auth 第二批-C 真实迁移（当前批次）

本轮第二批-C 实际执行范围严格限定为“管理员账户管理链”4个模块：

1. `src/platform/services/admin_user_service.py` -> `src/app/auth/services/admin_user_service.py`
2. `src/platform/schemas/user_admin.py` -> `src/app/auth/schemas/user_admin.py`
3. `src/platform/api/v1/admin.py` -> `src/app/auth/api/admin.py`
4. `src/platform/api/v1/admin_users.py` -> `src/app/auth/api/admin_users.py`

执行原则：

- 仅迁移上述 4 个模块，不扩大范围
- 旧路径保留 deprecated 兼容壳，确保旧 import 路径继续可用
- 外部行为、返回契约、权限校验链路保持不变
- 不触碰 `platform/models/app/*`
- 不触碰 `platform/api/router.py`、`platform/api/v1/router.py` 与 `platform/web/app.py`

---

## accounts/models 拆分计划（准备阶段）

本节只做拆分准备，不做任何模型实现迁移。本节覆盖范围仅限：

- `src/platform/models/app/*`

当前模型清单：

1. `app_user.py`
2. `auth_role.py`
3. `auth_permission.py`
4. `auth_role_permission.py`
5. `auth_user_role.py`
6. `auth_refresh_token.py`
7. `auth_action_token.py`
8. `auth_audit_log.py`
9. `auth_invite_code.py`
10. `__init__.py`

### 当前调用链（基于代码实扫）

#### 1) `src/app/auth/*`（当前主消费方）

- `src/app/auth/dependencies.py`
  - 直接读取：`AuthUserRole`、`AuthRolePermission`
- `src/app/auth/user_repository.py`
  - 直接读取：`AppUser`
- `src/app/auth/services/auth_service.py`
  - 直接读取：`AppUser`、`AuthRole`、`AuthPermission`、`AuthRolePermission`、`AuthUserRole`、`AuthRefreshToken`、`AuthActionToken`、`AuthAuditLog`、`AuthInviteCode`
- `src/app/auth/services/admin_user_service.py`
  - 直接读取：`AppUser`、`AuthUserRole`、`AuthRefreshToken`、`AuthActionToken`、`AuthAuditLog`、`AuthInviteCode`

#### 2) `src/platform/auth/*` 与 `src/platform/services/*`（过渡兼容层）

- 当前 `platform/auth/*`、`platform/services/*` 已以 deprecated shim 为主，主实现已转发到 `src/app/auth/*`。
- 因此模型的“真实主消费”已在 `src/app/auth/*`，`platform` 侧更多是旧路径兼容入口。

#### 3) `src/ops/queries/*`（ops 查询读取）

- `src/ops/queries/execution_query_service.py` 读取 `AppUser`
- `src/ops/queries/schedule_query_service.py` 读取 `AppUser`
- `src/ops/queries/probe_query_service.py` 读取 `AppUser`
- `src/ops/queries/resolution_release_query_service.py` 读取 `AppUser`

#### 4) model registry / Alembic 关系

- `alembic/env.py` 通过 `src.app.model_registry.register_all_models()` 注册 ORM 模型。
- `src/app/model_registry.py` 当前仍显式导入 `src/platform/models/app/*`。
- 因此模型迁移必须与 model registry 的导入路径兼容策略联动，确保 Alembic metadata 装载稳定。

### 哪些可以先迁，哪些必须成组迁

#### 可先迁（低风险先手）

- `src/platform/models/app/__init__.py`（组织导出层）
- `auth_role.py` 与 `auth_permission.py`（相对独立的角色/权限字典模型）

说明：即使先迁，也需要保留旧路径 shim，避免调用侧提前切换造成连锁改动。

#### 必须成组迁（中高耦合）

1. **账户授权核心组（建议同批）**
   - `app_user.py`
   - `auth_user_role.py`
   - `auth_role_permission.py`
   - （并建议同批带上）`auth_role.py`、`auth_permission.py`

原因：`dependencies + auth_service + ops/queries` 对该链路耦合紧，拆散迁移会增加行为漂移风险。

2. **令牌/审计/邀请码组（建议同批）**
   - `auth_refresh_token.py`
   - `auth_action_token.py`
   - `auth_audit_log.py`
   - `auth_invite_code.py`

原因：`auth_service/admin_user_service` 对这一组存在组合读写语义，拆开迁移会放大回归面。

### 最安全的第一批候选（建议）

第一批真实迁移优先采用“实现平移 + 旧路径 shim”策略，且严格不改字段与表结构：

1. 先平移 `src/platform/models/app/__init__.py` 到 `src/app/models/__init__.py`（保留 platform shim）。
2. 再按“成组迁移”执行两组模型（授权核心组、令牌审计组）。
3. 在模型路径切换稳定后，再考虑调用方 import 的逐步切换（本阶段不做）。

### 继续暂缓项

以下项在模型迁移完成前继续暂缓：

- `platform/api/router.py`
- `platform/api/v1/router.py`
- `platform/web/app.py`

原因：

- 这三处仍是全局入口/聚合层，提前处理会把模型迁移风险扩散到整站路由与启动链路，不符合“低风险分阶段”策略。

### 风险点与迁移约束

1. **Alembic/metadata 稳定性风险**
   - 模型迁移必须保证 `register_all_models()` 在任意阶段都能成功加载目标模型。
2. **ops 查询兼容风险**
   - `ops/queries/*` 直接读取 `AppUser`，必须依赖旧路径 shim 或同批安全切换。
3. **导入路径回归风险**
   - `app/auth/*` 当前大量直接 import `src.platform.models.app.*`，迁移必须保留兼容导出。
4. **强约束**
   - 不允许为迁移顺手改字段、表名、关系定义、schema 名称、Alembic 行为。

---

## accounts/models 第一批真实迁移（当前批次）

本轮 models 第一批实际执行范围严格限定为以下 3 个文件：

1. `src/platform/models/app/__init__.py` -> `src/app/models/__init__.py`
2. `src/platform/models/app/auth_role.py` -> `src/app/models/auth_role.py`
3. `src/platform/models/app/auth_permission.py` -> `src/app/models/auth_permission.py`

执行原则：

- 仅迁移上述 3 个文件，不扩大范围
- `src/platform/models/app/*` 旧路径保留 deprecated 兼容壳
- 保持表结构、metadata 注册、导入路径兼容稳定
- 不改字段、不改表名、不改关系定义
- 不改 Alembic 行为
- `src/app/model_registry.py` 仅做最小兼容调整，不改变整体设计
- 不提前迁移 `AppUser` 与关系表模型

---

## accounts/models 第二批真实迁移（当前批次）

本轮 models 第二批实际执行范围严格限定为以下 3 个文件：

1. `src/platform/models/app/app_user.py` -> `src/app/models/app_user.py`
2. `src/platform/models/app/auth_user_role.py` -> `src/app/models/auth_user_role.py`
3. `src/platform/models/app/auth_role_permission.py` -> `src/app/models/auth_role_permission.py`

执行原则：

- 仅迁移上述 3 个模型，不扩大范围
- 3 个模型按“账户授权核心组”成组迁移，不拆开
- `src/platform/models/app/*` 旧路径保留 deprecated 兼容壳，保证旧 import 可用
- 保持表结构、metadata 注册、Alembic 行为不变
- 仅做最小调用侧切换（`app/auth` 与 `ops/queries` 读取路径收敛）
- `src/app/model_registry.py` 仅做最小兼容调整，不改变整体设计
- 不触碰令牌/审计/邀请码模型：`auth_refresh_token` / `auth_action_token` / `auth_audit_log` / `auth_invite_code`

---

## accounts/models 第三批真实迁移（当前批次）

本轮 models 第三批实际执行范围严格限定为以下 4 个文件：

1. `src/platform/models/app/auth_refresh_token.py` -> `src/app/models/auth_refresh_token.py`
2. `src/platform/models/app/auth_action_token.py` -> `src/app/models/auth_action_token.py`
3. `src/platform/models/app/auth_audit_log.py` -> `src/app/models/auth_audit_log.py`
4. `src/platform/models/app/auth_invite_code.py` -> `src/app/models/auth_invite_code.py`

执行原则：

- 仅迁移上述 4 个模型，不扩大范围
- 4 个模型按“令牌/审计/邀请码组”成组迁移，不拆开
- `src/platform/models/app/*` 旧路径保留 deprecated 兼容壳，保证旧 import 可用
- 保持表结构、metadata 注册、Alembic 行为不变
- 仅做最小调用侧切换（`src/app/auth/services/auth_service.py` 与 `src/app/auth/services/admin_user_service.py`）
- `src/app/model_registry.py` 仅做最小兼容调整，不改变整体设计
- 不触碰 `platform/api/router.py`、`platform/api/v1/router.py` 与 `platform/web/app.py`

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

---

## final cutover 准备（本轮仅规划，不迁代码）

本节只定义最终切换方案，不进行任何实现迁移。

### 1) 当前三处敏感入口职责（基于现状代码）

1. `src/platform/api/router.py`
   - 定义 `/api` 根路由
   - 提供 `/api/health`（依赖 `build_health_response` + `HealthResponse`）
   - 挂载 `platform/api/v1/router.py`

2. `src/platform/api/v1/router.py`
   - 作为 `/api/v1` 聚合入口
   - 聚合 app-auth 子路由（`auth/users/admin/admin_users`）
   - 聚合 ops 路由（`src.ops.api.router`）
   - 聚合 biz 路由（`share/quote/market`）

3. `src/platform/web/app.py`
   - 创建 FastAPI app
   - 注册 middleware / lifespan / 异常处理
   - 挂载静态资源与前端入口
   - 挂载 `api_router`
   - 提供 `/`、`/app`、`/ops` 等重定向与前端路由兜底

### 2) 目标落位（最终态）

1. `platform/api/router.py` -> `src/app/api/router.py`
2. `platform/api/v1/router.py` -> `src/app/api/v1/router.py`
3. `platform/web/app.py` -> `src/app/web/app.py`

约束：

- 新 `src/app/api/*` 仅做聚合与入口编排，不承载业务实现。
- 新 `src/app/web/*` 仅做运行入口装配，不承载业务逻辑。

### 3) 哪些子路由已具备切入 app 聚合层条件

已具备条件（主实现已不在 platform）：

1. app-auth 路由：`src/app/auth/api/*`
2. biz 路由：`src/biz/api/{share,quote,market}.py`
3. ops 路由：`src/ops/api/router.py`

因此，`platform/api/v1/router.py` 已具备“迁聚合壳、不迁业务实现”的切换前提。

### 4) `platform/schemas/common.py` 归属判定建议

判定：优先归 `app` 壳层。

理由：

1. 当前主要承载 `HealthResponse` / `OkResponse` / `ApiErrorResponse` 这类入口通用响应模型。
2. 它既被 health 入口用，也被 auth/admin API 用，更偏“应用入口契约”，不偏 biz/ops 任一子系统。

建议路径：

1. 最终迁到 `src/app/schemas/common.py`（或 `src/app/api/schemas/common.py`，二选一保持单点）。
2. `src/platform/schemas/common.py` 保留 deprecated 兼容壳直到 final cutover 完成。

### 5) 最安全的最终切换顺序（建议）

1. 先在 `src/app/api/*` 落位新聚合入口（仅复制聚合行为，不变更挂载集合与顺序）。
2. 将 `platform/schemas/common.py` 主实现迁到 app 壳位置，platform 保留 shim。
3. 在不改其他行为的前提下，把 `platform/web/app.py` 对 `api_router` 的引用切到 `src/app/api/router.py`。
4. 完成 `/api/health`、`/api/v1/*`、`/api/docs`、`/app`、`/ops` 回归后，将 `platform/api/router.py` 与 `platform/api/v1/router.py` 降为 shim。
5. 最后将 `platform/web/app.py` 主实现迁到 `src/app/web/app.py`，platform 保留入口 shim。

### 6) 风险点与回归重点

风险点：

1. `/api/v1` 路由聚合顺序变化导致覆盖关系变化。
2. `platform/schemas/common.py` 迁移后 import 路径断裂。
3. 入口切换影响 docs/openapi 路径、静态资源与前端重定向逻辑。
4. auth/admin 依赖链与 ops/biz 路由在聚合层的兼容性回归。

回归重点：

1. `GET /api/health`、`GET /api/v1/health`
2. auth/admin/user 全链路登录鉴权与权限接口
3. biz 端 `share/quote/market` 核心只读接口
4. ops 端任务/调度核心接口
5. `GET /`、`GET /app`、`GET /ops` 与前端资源挂载行为

---

## final cutover 第一步真实迁移（当前批次）

本轮实际范围严格限定为以下两个聚合入口：

1. `src/platform/api/router.py` -> `src/app/api/router.py`
2. `src/platform/api/v1/router.py` -> `src/app/api/v1/router.py`

执行原则：

- 仅迁移上述两个聚合入口，不扩大范围
- `src/platform/api/*` 旧路径保留 deprecated 兼容壳，保证 `platform/web/app.py` 继续可用
- 保持 `/api`、`/api/v1/*` 路由行为不变
- 保持 `include_router` 顺序不变
- 不处理 `src/platform/web/app.py`
- 不处理 `src/app/web/*`
- 不处理 `src/platform/schemas/common.py`

---

## health/common/web 最终切换准备（本轮仅规划，不迁代码）

本节用于 final cutover 前最后一轮准备，严格不迁移实现代码。

### 1) `src/platform/api/v1/health.py` 当前职责与推荐归属

当前职责：

1. 提供 `/api/v1/health` 路由
2. 提供 `build_health_response(session)` 供 `/api/health` 与 `/api/v1/health` 共用
3. 执行 DB 连通检查（`SELECT 1`）并构造 `HealthResponse`

推荐最终归属：

- 主实现迁至 `src/app/api/v1/health.py`
- `src/platform/api/v1/health.py` 降级为 deprecated shim（仅转发）

### 2) `src/platform/schemas/common.py` 当前使用方与推荐归属

当前直接使用方（基于代码扫描）：

1. `src/app/api/router.py`（`HealthResponse`）
2. `src/platform/api/v1/health.py`（`HealthResponse`）
3. `src/app/auth/api/auth.py`（`OkResponse`）
4. `src/app/auth/api/admin_users.py`（`OkResponse`）

推荐最终归属：

- 主实现迁至 `src/app/schemas/common.py`
- `src/platform/schemas/common.py` 保留 deprecated shim

归属原则：

1. 仅承接 app 壳层通用响应 schema
2. 不混入 biz/ops 领域返回模型

### 3) `src/platform/web/app.py` 当前职责与最终落位方式

当前职责：

1. FastAPI app 创建与 docs/openapi 配置
2. middleware、lifespan、异常处理安装
3. 静态资源挂载与前端入口/重定向
4. 挂载 API 聚合入口（当前仍通过 `src.platform.api.router`）

最终落位方式：

1. 先将 `api_router` 引用切到 `src.app.api.router`
2. 再将主实现平移到 `src/app/web/app.py`
3. `src/platform/web/app.py` 最终保留 deprecated shim（入口兼容）

### 4) final cutover 前仍缺的前置条件

1. `src/app/schemas/common.py` 承接方案落位（本轮仅确定，不实施）
2. `src/app/api/v1/health.py` 目标文件与 shim 路径确定（本轮仅确定，不实施）
3. `src/platform/web/app.py` 切换回归清单冻结（docs/openapi、静态资源、重定向）
4. 切换窗口执行顺序与回滚步骤冻结

### 5) 最安全的最终切换顺序（建议）

1. 迁 `common schema` 主实现到 `src/app/schemas/common.py`，platform 保留 shim
2. 迁 `health` 主实现到 `src/app/api/v1/health.py`，platform 保留 shim
3. 将 `platform/web/app.py` 的 `api_router` 引用切到 `src.app.api.router`
4. 回归通过后平移 `platform/web/app.py` 主实现到 `src/app/web/app.py`
5. `platform/web/app.py` 降级为 shim

### 6) 风险点与回归重点

风险点：

1. `HealthResponse/OkResponse` 路径切换引发导入断裂
2. `platform/web/app.py` 切换后 docs/openapi 与前端挂载行为漂移
3. `/api/health` 与 `/api/v1/health` 返回一致性被破坏
4. 入口切换引起 auth/admin 与 ops/biz 路由可达性回归

回归重点：

1. `GET /api/health`、`GET /api/v1/health` 响应结构与状态码
2. `/api/docs`、`/api/openapi.json` 可访问性
3. `/`、`/app`、`/ops` 重定向与前端静态资源挂载
4. auth/admin、biz、ops 关键路由冒烟回归
