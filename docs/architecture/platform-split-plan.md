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

## final cutover 第二步真实迁移（当前批次）

本轮实际范围严格限定为以下单点迁移：

1. `src/platform/api/v1/health.py` -> `src/app/api/v1/health.py`

执行原则：

- 仅迁移 `health.py` 主实现，不扩大范围
- `src/platform/api/v1/health.py` 保留 deprecated 兼容壳（仅转发）
- 保持 `/api/health`、`/api/v1/health`、`/api/docs`、`/api/openapi.json` 行为不变
- 不处理 `src/platform/schemas/common.py`
- 不处理 `src/platform/web/app.py`
- 不处理 `src/platform/api/router.py`
- 不处理 `src/platform/api/v1/router.py`

---

## final cutover 第三步真实迁移（当前批次）

本轮实际范围严格限定为以下单点迁移：

1. `src/platform/schemas/common.py` -> `src/app/schemas/common.py`

执行原则：

- 仅迁移 `common.py` 主实现，不扩大范围
- `src/platform/schemas/common.py` 保留 deprecated 兼容壳（仅转发）
- 保持 app-auth / app-api 共享 schema 行为与返回契约不变
- 不处理 `src/platform/web/app.py`
- 不处理 `src/platform/api/router.py`
- 不处理 `src/platform/api/v1/router.py`

---

## final cutover 第四步真实迁移（当前批次）

本轮实际范围严格限定为以下单点迁移：

1. `src/platform/web/app.py` -> `src/app/web/app.py`

执行原则：

- 仅迁移 `platform/web/app.py` 主实现，不扩大范围
- `src/platform/web/app.py` 保留 deprecated 兼容壳（入口兼容）
- 保持 FastAPI app 创建、middleware 顺序、lifespan、异常处理装配行为不变
- 保持静态资源挂载、`/`、`/app`、`/ops`、`/api`、`/api/v1/*`、`/api/docs`、`/api/openapi.json` 行为不变
- 不处理 `src/platform/api/router.py`
- 不处理 `src/platform/api/v1/router.py`

---

## health/common/web 最终切换准备（health/common/web 已迁移，入口收口待清理）

本节用于 `health`、`common schema` 与 `web` 入口迁移后，继续做 post-cutover 收口准备。

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
2. `src/app/api/v1/health.py`（`HealthResponse`）
3. `src/app/auth/api/auth.py`（`OkResponse`）
4. `src/app/auth/api/admin_users.py`（`OkResponse`）
5. `src/platform/schemas/common.py`（deprecated shim 转发）

推荐最终归属：

- 主实现迁至 `src/app/schemas/common.py`（已完成）
- `src/platform/schemas/common.py` 保留 deprecated shim（已完成）

归属原则：

1. 仅承接 app 壳层通用响应 schema
2. 不混入 biz/ops 领域返回模型

### 3) `src/platform/web/app.py` 当前职责与最终落位方式

当前职责（迁移前）：

1. FastAPI app 创建与 docs/openapi 配置
2. middleware、lifespan、异常处理安装
3. 静态资源挂载与前端入口/重定向
4. 挂载 API 聚合入口（当前仍通过 `src.platform.api.router`）

最终落位方式：

1. 先将 `api_router` 引用切到 `src.app.api.router`
2. 再将主实现平移到 `src/app/web/app.py`
3. `src/platform/web/app.py` 最终保留 deprecated shim（入口兼容）

当前状态：

1. `src/app/web/app.py` 已承接主实现（已完成）
2. `src/platform/web/app.py` 已降级为 deprecated shim（已完成）

### 4) final cutover 前仍缺的前置条件

1. post-cutover 清理范围冻结（本轮不执行）
2. shim 保留期与下线窗口策略冻结

### 5) 最安全的最终切换顺序（建议）

1. 迁 `common schema` 主实现到 `src/app/schemas/common.py`，platform 保留 shim（已完成）
2. 迁 `health` 主实现到 `src/app/api/v1/health.py`，platform 保留 shim（已完成）
3. 将 `platform/web/app.py` 的 `api_router` 引用切到 `src.app.api.router`（已完成）
4. 回归通过后平移 `platform/web/app.py` 主实现到 `src/app/web/app.py`（已完成）
5. `platform/web/app.py` 降级为 shim（已完成）

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

---

## post-cutover cleanup plan（仅规划，不执行删除）

### 1) 当前 `platform` 下已转为 shim/compat layer 的内容

已明确为 compat-only（主实现已迁出）：

1. `platform/api/router.py`
2. `platform/api/v1/{router,health,auth,users,admin,admin_users,share}.py`
3. `platform/auth/{constants,domain,password_service,security_utils,dependencies,jwt_service,user_repository}.py`
4. `platform/dependencies/db.py`
5. `platform/exceptions/web.py`
6. `platform/queries/share_market_query_service.py`
7. `platform/schemas/{share,auth,user_admin,common}.py`
8. `platform/services/{auth_service,user_service,admin_user_service}.py`
9. `platform/models/app/*`
10. `platform/web/app.py`

注：以上文件当前职责是兼容旧 import 路径，不再承接主实现。

### 2) 第一批清理候选（优先）

候选原则：仅清理“无运行入口依赖、无外部脚本默认引用、无测试直接 import”的 shim。

建议第一批候选：

1. `platform/models/app/*` shim（前提：确认 `app/models/*` 被统一引用）
2. `platform/services/*` shim（前提：确认调用全部切到 `app/auth/services/*`）
3. `platform/schemas/{auth,user_admin,share}.py` shim
4. `platform/queries/share_market_query_service.py` shim

### 3) 仍需后置保留的 shim

以下 shim 建议延后删除：

1. `platform/web/app.py`
理由：`platform/web/run.py` 当前仍以 `src.platform.web.app:app` 作为运行入口字符串。
2. `platform/api/router.py` 与 `platform/api/v1/router.py`
理由：仍是历史入口路径，需等待运行入口与测试引用全部切换后再删。
3. `platform/schemas/common.py`
理由：属于 app 入口通用返回模型，建议在全量 import 收敛后再下线，避免残留调用方断裂。

### 4) 当前仍有真实实现的目录（禁止误删）

post-cutover 当前仍有真实实现，不应按 shim 删除：

1. `platform/web/run.py`（当前运行命令入口）
2. `platform/web/settings.py`
3. `platform/web/lifespan.py`
4. `platform/web/logging.py`
5. `platform/web/middleware/*`
6. `platform/web/static/*`
7. `platform/*/__init__.py`（包结构与兼容导出承载）

### 5) cleanup 建议顺序

1. 先做“调用链审计”：确认 compat shim 的真实引用清单（代码 + 脚本 + 部署命令）。
2. 清理第一批低风险 shim（models/services/schemas/queries）。
3. 切换运行入口引用（`platform/web/run.py` 指向 app 路径）后，再评估 `platform/web/app.py` 删除。
4. 最后处理 `platform/api/router.py`、`platform/api/v1/router.py`、`platform/schemas/common.py`。
5. 每批删除后都保留回滚窗口（tag 或可回滚提交点）。

### 6) 每批删除前的回归基线

每一批 cleanup 之前至少执行：

1. `tests/architecture/test_subsystem_dependency_matrix.py`
2. `tests/web/test_health_api.py`
3. `tests/web/test_ops_pages.py`
4. `tests/web/test_platform_check_page.py`
5. 关键接口冒烟：
   - `/api/health`
   - `/api/v1/health`
   - `/api/docs`
   - `/api/openapi.json`
   - `/`
   - `/app`
   - `/ops`

### 7) cleanup 候选真实引用审计（本轮，仅审计不删除）

审计范围（代码 + 测试 + 脚本）：

- `src`
- `tests`
- `scripts`

审计方式：`rg` 按候选 shim 路径逐项扫描 import/引用。

#### A. `platform/models/app/*` shim

审计结论：**仍有真实引用，暂不能删**。

当前引用方（已确认）：

1. `tests/web/conftest.py`
   - 引用了 `src.platform.models.app.*` 全套账户模型 shim。
2. `tests/web/test_auth_api.py`
   - 引用 `src.platform.models.app.app_user.AppUser`。
3. `tests/web/test_auth_registration_api.py`
   - 引用 `src.platform.models.app.auth_refresh_token.AuthRefreshToken`。

是否可进入第一批真实删除候选：**否**。

删除前前置条件：

1. 先将上述测试 import 切换到 `src.app.models.*`。
2. 确认无残留脚本/测试引用后再进入删除批次。

#### B. `platform/services/*` shim

审计结论：在 `src/tests/scripts` 中未检出直接引用。

检索项（已扫）：

1. `src.platform.services.auth_service`
2. `src.platform.services.admin_user_service`
3. `src.platform.services.user_service`
4. `from src.platform.services import ...`

是否可进入第一批真实删除候选：**是（候选）**。

删除前前置条件：

1. 以当前分支代码再次跑一次全量引用扫描，确认仍为 0。
2. 通过下文“第一批删除前回归清单”后再执行删除。

#### C. `platform/schemas/{auth,user_admin,share}.py` shim

审计结论：在 `src/tests/scripts` 中未检出直接引用。

检索项（已扫）：

1. `src.platform.schemas.auth`
2. `src.platform.schemas.user_admin`
3. `src.platform.schemas.share`
4. `from src.platform.schemas import ...`

是否可进入第一批真实删除候选：**是（候选）**。

删除前前置条件：

1. 删除前再次扫描确认 0 引用。
2. 回归通过后再删除。

#### D. `platform/queries/share_market_query_service.py` shim

审计结论：在 `src/tests/scripts` 中未检出直接引用。

检索项（已扫）：

1. `src.platform.queries.share_market_query_service`
2. `from src.platform.queries import ...`

是否可进入第一批真实删除候选：**是（候选）**。

删除前前置条件：

1. 删除前再次扫描确认 0 引用。
2. 回归通过后再删除。

### 8) 明确继续后置（本轮排除项）

以下项按策略明确排除，不进入第一批真实删除：

1. `platform/web/app.py`
2. `platform/api/router.py`
3. `platform/api/v1/router.py`
4. `platform/schemas/common.py`
5. `platform/web/run.py`
6. `platform/web/settings.py`
7. `platform/web/lifespan.py`
8. `platform/web/logging.py`
9. `platform/web/middleware/*`
10. `platform/web/static/*`

后置原因摘要：

1. `platform/web/run.py` 当前仍是兼容入口（systemd 命令已切到 `python -m src.app.web.run`，但代码/测试链路仍有后置项）。
2. `platform/web/settings.py`、`lifespan.py`、`logging.py`、`middleware/*` 仍被 app/web 与 auth 运行链路直接使用。
3. `platform/web/app.py`、`platform/api/router.py`、`platform/api/v1/router.py`、`platform/schemas/common.py` 属 final cutover 后置兼容层，需在入口切换策略窗口中统一处理，避免误删造成运行入口与聚合路由抖动。

### 9) 第一批真实删除前必须跑的回归清单

1. 架构约束：
   - `pytest -q tests/architecture/test_subsystem_dependency_matrix.py`
2. Web 核心回归：
   - `pytest -q tests/web/test_health_api.py`
   - `pytest -q tests/web/test_ops_pages.py`
   - `pytest -q tests/web/test_platform_check_page.py`
3. 关键接口冒烟：
   - `GET /api/health`
   - `GET /api/v1/health`
   - `GET /api/docs`
   - `GET /api/openapi.json`
   - `GET /`
   - `GET /app`
   - `GET /ops`
4. 删除前再次执行引用审计（`src + tests + scripts`）并记录结果；仅当候选项均为 0 引用才进入真实删除。

### 10) 第一批真实删除执行结果（当前批次）

本轮按“仅删除低风险 shim”的范围执行，删除前后均完成引用审计（`src + tests + scripts`）。

已删除 shim（7 个）：

1. `src/platform/services/auth_service.py`
2. `src/platform/services/user_service.py`
3. `src/platform/services/admin_user_service.py`
4. `src/platform/schemas/auth.py`
5. `src/platform/schemas/user_admin.py`
6. `src/platform/schemas/share.py`
7. `src/platform/queries/share_market_query_service.py`

删除后复审结果：

1. 上述 7 条旧路径在 `src/tests/scripts` 中均未检出直接引用。
2. `platform/models/app/*` shim 仍有测试引用，继续保留（不在本轮删除范围）。
3. `platform/web/*` 运行链路与 `platform/api*` 聚合兼容层继续后置，未触碰。

### 11) 第二批真实删除执行结果（platform/models/app shim）

本轮仅处理 `platform/models/app/*` 兼容壳删除，删除前再次完成引用审计（`src + tests + scripts`）。

删除前审计结果：

1. `src.platform.models.app.*` 在 `src/tests/scripts` 中未检出直接引用。
2. 触发条件满足，进入本轮真实删除。

已删除 shim（10 个）：

1. `src/platform/models/app/__init__.py`
2. `src/platform/models/app/app_user.py`
3. `src/platform/models/app/auth_role.py`
4. `src/platform/models/app/auth_permission.py`
5. `src/platform/models/app/auth_user_role.py`
6. `src/platform/models/app/auth_role_permission.py`
7. `src/platform/models/app/auth_refresh_token.py`
8. `src/platform/models/app/auth_action_token.py`
9. `src/platform/models/app/auth_audit_log.py`
10. `src/platform/models/app/auth_invite_code.py`

删除后状态：

1. `platform/models/app/*` shim 已完成清理。
2. `platform/web/*`、`platform/api*`、`platform/schemas/common.py` 等后置兼容层仍保持不动。

### 12) cleanup 单点迁移执行结果（platform/web/run.py）

本轮 cleanup 实际范围严格限定为：

1. `src/platform/web/run.py`

执行结果：

1. `src/app/web/run.py` 新增为运行入口主实现。
2. `src/platform/web/run.py` 降级为 deprecated 兼容壳，仅转发 `main()` 到 `src.app.web.run`。
3. 启动参数解析与运行语义保持兼容（host/port/reload/env-file 行为不变）。
4. `uvicorn` 目标字符串保持兼容（仍使用 `src.platform.web.app:app`），避免启动语义漂移。

本轮未触碰：

1. `src/platform/web/app.py`
2. `src/platform/api/router.py`
3. `src/platform/api/v1/router.py`
4. `src/platform/schemas/common.py`
5. `src/platform/web/settings.py`
6. `src/platform/web/lifespan.py`
7. `src/platform/web/logging.py`
8. `src/platform/web/middleware/*`
9. `src/platform/web/static/*`

### 13) 运行入口 cleanup 配置/文档切换执行结果（本轮）

本轮目标：只切配置/文档层到 `src.app.web.run`，不改实现、不删 shim、不改测试入口与 `app-target` 默认值。

审计范围（已执行）：

1. `src`
2. `tests`
3. `scripts`
4. `docs`
5. `README.md`
6. `pyproject.toml`
7. `.github`（仓库内 CI/脚本检索）

#### A. 本轮已完成切换（配置/文档层）

1. `pyproject.toml`
   - `goldenshare-web` 入口已改为 `src.app.web.run:main`
2. `scripts/goldenshare-web.service`
   - `ExecStart` 已改为 `python -m src.app.web.run`
3. `README.md`
   - 本地/构建/运维示例命令已改为 `python3 -m src.app.web.run` / `python -m src.app.web.run`
4. `docs/architecture/current-architecture-baseline.md`
   - Web 入口与 systemd 示例均改为 `src.app.web.run`
5. `docs/platform/web-platform-phase1-lld.md`
   - 文档示例中的模块运行命令已改为 `src.app.web.run`

#### B. 本轮明确未触碰（后置项）

1. `tests/web/conftest.py` 仍导入 `src.platform.web.app`（按本轮约束保留）
2. `src/app/web/run.py` 默认 `--app-target` 仍为 `src.platform.web.app:app`（按本轮约束保留）
3. `src/platform/web/run.py` 与 `src/platform/web/app.py` shim 均未删除

#### C. 删除 `platform/web/run.py` 前的最小前置条件

1. 配置/文档层已经完成切换（本轮已完成）
2. 测试入口切换到 `src.app.web.app`（后置）
3. `src/app/web/run.py` 默认 `--app-target` 切到 `src.app.web.app:app`（后置）
4. 至少完成以下回归：
   - `/api/health`
   - `/api/v1/health`
   - `/api/docs`
   - `/api/openapi.json`
   - `pytest -q tests/web/test_health_api.py`
   - `pytest -q tests/web/test_ops_pages.py`

#### D. 删除 `platform/web/app.py` 前的最小前置条件

1. 全仓无 `src.platform.web.app` 运行级引用（含测试、脚本、部署配置）
2. `src/app/web/run.py` 默认 `--app-target` 已切到 `src.app.web.app:app`
3. 测试与启动链路验证通过后，再进入 shim 删除评估

#### E. 下一步最安全切换目标（建议顺序）

1. 先完成测试入口与 `app-target` 默认值切换
2. 回归验证 web 入口与路由行为
3. 最后评估删除 `platform/web/run.py`，再评估删除 `platform/web/app.py`

### 14) 运行入口 cleanup 第二步执行结果（测试入口 + app-target）

本轮范围（仅两项）：

1. `tests/web/conftest.py` 中测试 app 入口切换到 `src.app.web.app`
2. `src/app/web/run.py` 默认 `uvicorn` app target 切换到 `src.app.web.app:app`

本轮明确未触碰：

1. `src/platform/web/run.py`
2. `src/platform/web/app.py`
3. `src/platform/api/router.py`
4. `src/platform/api/v1/router.py`

切换后残留说明：

1. `platform/web/run.py` 仍作为兼容壳存在（预期保留）
2. `src.platform.web.app` 仍作为兼容壳存在（预期保留）

### 15) 运行入口 shim 删除执行结果（仅 `platform/web/run.py`）

本轮删除范围严格限定为：

1. `src/platform/web/run.py`

删除前审计结果：

1. 在 `src/tests/scripts/docs/README.md/pyproject.toml/.github` 范围内，未检出旧运行入口表达（模块路径、`python -m` 启动命令、脚本入口字符串）残留。

删除后状态：

1. `src/platform/web/run.py` 已删除。
2. `src/platform/web/app.py` 与 `platform/api*`、`platform/schemas/common.py` 等后置兼容层未触碰。

### 16) `platform/auth` helper shim 删除执行结果（4 项）

目标 shim：

1. `src/platform/auth/constants.py`
2. `src/platform/auth/domain.py`
3. `src/platform/auth/password_service.py`
4. `src/platform/auth/security_utils.py`

审计范围：

1. `src`
2. `tests`
3. `scripts`
4. `docs`
5. `README.md`
6. `pyproject.toml`
7. `.github`

删除前审计与收敛结果：

1. 已完成 import 路径收敛：`src/ops/*`、`src/biz/*`、`src/scripts/*`、相关测试中的 `src.platform.auth.*` 已切至 `src.app.auth.*`。
2. 当前 `src/tests/scripts` 范围内已无 `src.platform.auth.domain` / `password_service` / `security_utils` / `constants` 的直接引用。
3. 旧路径字符串仅保留在本节历史说明文本中，不影响运行链路。

本轮动作（已执行）：

1. 已删除以下 4 个 compat shim：
   - `src/platform/auth/constants.py`
   - `src/platform/auth/domain.py`
   - `src/platform/auth/password_service.py`
   - `src/platform/auth/security_utils.py`
2. 未触碰 `src/platform/auth/dependencies.py`、`jwt_service.py`、`user_repository.py`。

删除后状态：

1. 仓库中不再存在上述 4 个 shim 文件。
2. `src.platform.auth.(constants|domain|password_service|security_utils)` 在 `src/tests/scripts/docs/README/pyproject/.github` 范围内无运行引用残留（仅本节历史文本描述中出现）。

### 17) `platform/auth` 剩余 3 个 shim 删除执行结果（3 项）

本轮目标（单目标）：

1. `src/platform/auth/dependencies.py`
2. `src/platform/auth/jwt_service.py`
3. `src/platform/auth/user_repository.py`

删除前审计结果：

1. 先做全路径审计（`src/tests/scripts/docs/README/pyproject/.github`）。
2. 审计范围内已无 `src.platform.auth.(dependencies|jwt_service|user_repository)` 真实运行引用。

本轮动作（已执行）：

1. 已删除以下 3 个 compat shim：
   - `src/platform/auth/dependencies.py`
   - `src/platform/auth/jwt_service.py`
   - `src/platform/auth/user_repository.py`
2. 未触碰 `src/platform/auth/__init__.py`（保留包级兼容导出）。

删除后状态：

1. 仓库中不再存在上述 3 个 shim 文件。
2. 旧路径字符串仅出现在本节历史说明文本中，不影响运行链路。

### 18) 高风险后置项引用审计（仅审计，不删除）

本轮审计对象：

1. `src/platform/web/app.py`
2. `src/platform/api/router.py`
3. `src/platform/api/v1/router.py`
4. `src/platform/schemas/common.py`

审计范围：

1. `src`
2. `tests`
3. `scripts`
4. `docs`
5. `README*`
6. `pyproject.toml`
7. `.github`

审计结果：

1. 在 `src/tests/scripts` 范围内，未检出对 `src.platform.web.app`、`src.platform.api.router`、`src.platform.api.v1.router`、`src.platform.schemas.common` 的直接导入引用。
2. 上述旧路径当前仅在文档示例中仍有历史文本（不影响运行链路）。
3. 4 个文件当前均为 shim 实现，主实现已分别落位：
   - `src.app.web.app`
   - `src.app.api.router`
   - `src.app.api.v1.router`
   - `src.app.schemas.common`
4. 但 `src.app.api.v1.router` 目前仍通过 `src.platform.api.v1.{auth,users,admin,admin_users,share}` 聚合子路由，属于下一轮应先收敛的依赖点。

本轮动作：

1. 仅执行审计与文档更新。
2. 未删除上述 4 个后置 shim 文件。

下一步建议（单独一轮）：

1. 先把 `src.app.api.v1.router` 对 `src.platform.api.v1.*` 的聚合导入切到主路径（`src.app.auth.api.*` / `src.biz.api.share`），并跑最小回归。
2. 收敛完成后，再进入 `platform/api/*.py`、`platform/web/app.py`、`platform/schemas/common.py` 的删除窗口评估。

### 19) `app/api/v1/router` 聚合导入收敛执行结果（单点）

本轮目标（单目标）：

1. 仅收敛 `src/app/api/v1/router.py` 对 `src.platform.api.v1.*` 的聚合导入。

本轮动作（已执行）：

1. `src.platform.api.v1.{admin,admin_users,auth,users}` -> `src.app.auth.api.{admin,admin_users,auth,users}`
2. `src.platform.api.v1.share` -> `src.biz.api.share`
3. 保持 `include_router` 顺序不变，未改路由行为。

本轮结果：

1. `src/app/api/v1/router.py` 已不再依赖 `src.platform.api.v1.*`。
2. `platform/api/v1/*` 兼容壳仍保留，尚未进入删除动作。

### 20) `platform/api` 聚合 shim 删除执行结果（2 项）

本轮目标（单目标）：

1. `src/platform/api/router.py`
2. `src/platform/api/v1/router.py`

删除前审计结果：

1. 在 `src/tests/scripts` 范围内，未检出对上述 2 个 shim 的直接导入引用。
2. 在 `docs/README/pyproject/.github` 范围内，旧路径仅出现在 `platform-split-plan.md` 的历史说明文本。
3. 对应主实现已稳定落位于：
   - `src.app.api.router`
   - `src.app.api.v1.router`

本轮动作（已执行）：

1. 删除 `src/platform/api/router.py`
2. 删除 `src/platform/api/v1/router.py`

删除后状态：

1. `platform/api` 聚合 shim 已清零。
2. `platform/web/app.py` 与 `platform/schemas/common.py` 仍为后置 compat 文件，未触碰。

### 21) `platform/schemas/common.py` shim 删除执行结果（单文件）

本轮目标（单目标）：

1. `src/platform/schemas/common.py`

删除前审计结果：

1. 在 `src/tests/scripts` 范围内，未检出对 `src.platform.schemas.common` 的直接导入引用。
2. 在 `docs/README/pyproject/.github` 范围内，旧路径仅出现在 `platform-split-plan.md` 的历史说明文本。
3. 主实现已稳定落位于 `src.app.schemas.common`。

本轮动作（已执行）：

1. 删除 `src/platform/schemas/common.py`

删除后状态：

1. `platform/schemas/common.py` compat shim 已删除。
2. 高风险后置 compat 目前仅剩 `src/platform/web/app.py`（其余未迁/未删项需单独审计）。

### 22) `platform/api/v1` 子路由 shim 删除执行结果（6 项）

本轮目标（单目标）：

1. `src/platform/api/v1/auth.py`
2. `src/platform/api/v1/users.py`
3. `src/platform/api/v1/admin.py`
4. `src/platform/api/v1/admin_users.py`
5. `src/platform/api/v1/share.py`
6. `src/platform/api/v1/health.py`

删除前审计结果：

1. 在 `src/tests/scripts` 范围内，未检出 `src.platform.api.v1.*` 的直接运行引用。
2. 在 `docs/README/pyproject/.github` 范围内，仅有历史说明文本提及旧路径。
3. 对应主实现已稳定落位于：
   - `src.app.auth.api.{auth,users,admin,admin_users}`
   - `src.biz.api.share`
   - `src.app.api.v1.health`

本轮动作（已执行）：

1. 删除上述 6 个 compat shim 文件。

删除后状态：

1. `platform/api/v1` 子路由 shim 已清零（保留包目录 `__init__.py`）。
2. 平台后置 compat 重点剩余项收敛为：`src/platform/web/app.py`。

### 23) `platform/web/app.py` shim 删除执行结果（单文件）

本轮目标（单目标）：

1. `src/platform/web/app.py`

删除前审计结果：

1. 在 `src/tests/scripts` 范围内，未检出对 `src.platform.web.app` 的直接导入引用。
2. 在 `docs/README/pyproject/.github` 范围内，旧路径仅出现在历史文档文本示例。
3. 运行入口主实现已稳定落位于 `src.app.web.app`，且 `src.app.web.run` 默认 app target 已切换到新路径。

本轮动作（已执行）：

1. 删除 `src/platform/web/app.py`

删除后状态：

1. `platform/web/app.py` compat shim 已删除。
2. `platform` 目录下 web 运行入口 compat 已清零（`run.py` 与 `app.py` 均已删除）。

### 24) `platform/dependencies` 与 `platform/exceptions` 引用收敛（不删 shim）

本轮目标（单目标）：

1. 将运行链路中的 `src.platform.dependencies*` 与 `src.platform.exceptions*` 导入收敛到 `src.app.dependencies*` 与 `src.app.exceptions*`。

本轮动作（已执行）：

1. 将 `src/ops/api/*`、`src/ops/services/*`、`src/ops/queries/*`、`src/ops/runtime/*` 中相关导入切到 `src.app.*`。
2. 将 `src/biz/api/*` 中相关导入切到 `src.app.*`。
3. 将 `tests/web/conftest.py`、`tests/web/test_auth_services.py` 的相关导入切到 `src.app.*`。
4. 本轮不删除 `platform/dependencies` 与 `platform/exceptions` shim 文件。

本轮结果：

1. 运行链路已不再依赖 `src.platform.dependencies*` 与 `src.platform.exceptions*`。
2. `platform/dependencies` 与 `platform/exceptions` 当前仅保留兼容壳角色，可进入下一轮“二次审计 + 实删”评估窗口。

### 25) `platform/dependencies` shim 删除执行结果（2 项）

本轮目标（单目标）：

1. `src/platform/dependencies/__init__.py`
2. `src/platform/dependencies/db.py`

删除前审计结果：

1. 在 `src/tests/scripts` 范围内，未检出对 `src.platform.dependencies*` 的直接运行引用。
2. 在 `docs/README/pyproject/.github` 范围内，旧路径仅在 `platform-split-plan.md` 的历史说明文本出现。
3. 主实现已稳定落位于 `src.app.dependencies.db` / `src.app.dependencies`。

本轮动作（已执行）：

1. 删除上述 2 个 compat shim 文件。

删除后状态：

1. `platform/dependencies` compat shim 已清零。
2. `platform/exceptions` 仍保留 compat shim（下一轮可评估删除）。

### 26) `platform/exceptions` shim 删除执行结果（2 项）

本轮目标（单目标）：

1. `src/platform/exceptions/__init__.py`
2. `src/platform/exceptions/web.py`

删除前审计结果：

1. 在 `src/tests/scripts` 范围内，未检出对 `src.platform.exceptions*` 的直接运行引用。
2. 在 `docs/README/pyproject/.github` 范围内，旧路径仅在 `platform-split-plan.md` 的历史说明文本出现。
3. 主实现已稳定落位于 `src.app.exceptions.web` / `src.app.exceptions`。

本轮动作（已执行）：

1. 删除上述 2 个 compat shim 文件。

删除后状态：

1. `platform/exceptions` compat shim 已清零。
2. 平台目录下 app/auth/api/schemas 主兼容壳已大幅收敛；剩余需单独审计的重点转为 `platform` 包级与 `platform/web` 非 shim 文件。

### 27) `platform/auth` 包级 shim 删除执行结果（单文件）

本轮目标（单目标）：

1. `src/platform/auth/__init__.py`

删除前审计结果：

1. 在 `src/tests/scripts` 范围内，未检出对 `src.platform.auth` 包级导入的直接运行引用。
2. 在 `docs/README/pyproject/.github` 范围内，旧路径仅在 `platform-split-plan.md` 历史说明文本出现。
3. 认证主实现已稳定落位于 `src.app.auth.*`。

本轮动作（已执行）：

1. 删除 `src/platform/auth/__init__.py`

删除后状态：

1. `platform/auth` 目录下 compat shim 已清零（仅剩 `__pycache__` 产物目录）。
2. 平台目录 cleanup 重点继续收敛到 `platform/api` 包级壳与 `platform/web` 非 shim 子模块。

### 28) `platform/web` 支撑模块主实现迁移到 `app/web`（保留 compat 壳）

本轮目标（单目标）：

1. 将 `platform/web` 中仍承载主实现的支撑模块迁移到 `app/web`：
   - `settings.py`
   - `logging.py`
   - `lifespan.py`
   - `middleware/*`
2. 同时保留 `platform/web` 薄 compat 壳，不删除目录和静态资源。

本轮动作（已执行）：

1. 新增主实现：
   - `src/app/web/settings.py`
   - `src/app/web/logging.py`
   - `src/app/web/lifespan.py`
   - `src/app/web/middleware/{__init__,access_log,request_id}.py`
2. 更新调用侧导入到 `src.app.web.*`：
   - `src/app/web/app.py`
   - `src/app/web/run.py`
   - `tests/web/test_health_api.py`
3. 将 `src/platform/web/{settings,logging,lifespan,middleware/*}.py` 改为 deprecated compat shim（仅转发）。

本轮结果：

1. `app/web` 已承接 web 支撑模块主实现。
2. `platform/web` 当前仅承担 compat + 静态资源目录角色，后续可按窗口继续评估清理。

### 29) `platform.web.settings` 剩余引用收敛（不删文件）

本轮目标（单目标）：

1. 收敛 app 运行链路中剩余 `src.platform.web.settings` 导入到 `src.app.web.settings`。

本轮动作（已执行）：

1. 更新以下文件导入路径：
   - `src/app/api/v1/health.py`
   - `src/app/auth/dependencies.py`
   - `src/app/auth/jwt_service.py`
   - `src/app/auth/services/auth_service.py`

本轮结果：

1. `src/tests/scripts` 范围内已无 `src.platform.web.settings` 运行引用。
2. `platform/web/settings.py` 继续仅保留 compat 壳角色，等待下一轮删除评估。

### 30) `platform/web` 支撑 shim 删除执行结果（6 项）

本轮目标（单目标）：

1. 删除以下 `platform/web` compat shim：
   - `src/platform/web/settings.py`
   - `src/platform/web/logging.py`
   - `src/platform/web/lifespan.py`
   - `src/platform/web/middleware/__init__.py`
   - `src/platform/web/middleware/access_log.py`
   - `src/platform/web/middleware/request_id.py`

删除前审计结果：

1. 在 `src/tests/scripts` 范围内，未检出对上述 `src.platform.web.*` shim 的运行导入引用。
2. 在 `docs/README/pyproject/.github` 范围内，旧路径仅保留在历史说明文本。
3. 主实现已稳定落位于：
   - `src.app.web.settings`
   - `src.app.web.logging`
   - `src.app.web.lifespan`
   - `src.app.web.middleware.*`

本轮动作（已执行）：

1. 删除上述 6 个 compat shim 文件。

删除后状态：

1. `platform/web` 目录已从“实现+shim混合”收敛为“静态资源目录为主”。
2. 运行入口与 web 支撑实现均由 `src.app.web.*` 承接。

### 31) 收口里程碑：运行代码对 `src.platform.*` 直接导入清零

本轮审计范围：

1. `src`
2. `tests`
3. `scripts`

审计结果：

1. `from src.platform ...` / `import src.platform ...` 在运行代码与测试代码中已清零。
2. `platform` 目录当前主要保留：
   - 架构说明与过渡目录结构（`AGENTS.md`、少量包目录）
   - 静态资源目录（`src/platform/web/static/*`）
   - `__pycache__` 产物目录

后续建议（收尾可选）：

1. 如需进一步收口，可在单独轮次评估是否清理 `platform` 下仅用于包声明的 `__init__.py` 文件（需先确认对外部启动/工具链无隐性依赖）。
2. 文档层旧路径示例可在后续“文档清扫轮次”统一替换，不与代码清理轮次混做。

### 32) 基线护栏固化（防回退）

本轮目标（单目标）：

1. 将 post-cutover 的平台收口状态固化为可执行护栏，避免后续开发把主实现写回 `platform` 或重新引入 `src.platform.*` 运行依赖。

本轮动作（已执行）：

1. 新增架构护栏测试：`tests/architecture/test_platform_legacy_guardrails.py`
2. 护栏规则：
   - `src/tests/scripts` 范围内（排除 `src/platform` 自身）禁止 import `src.platform.*`
   - `src/platform` 仅允许保留包骨架 Python 文件（`__init__.py` 级）；出现新增实现文件即失败
3. 收紧 `src/platform/AGENTS.md`，将上述测试作为长期硬约束写入目录规则。

本轮结果：

1. 平台目录从“靠约定维护”升级为“约定 + 自动化测试”双护栏。
2. 后续新增代码若出现以下回退，会在 CI/本地测试中立即暴露：
   - 运行代码再次直接依赖 `src.platform.*`
   - `src/platform` 出现新的主实现 Python 文件

当前剩余阻塞项（非本轮处理）：

1. 文档历史章节中仍有旧路径描述（属于历史记录，不影响运行）
2. `platform` 目录静态资源与包骨架是否做最终归档/裁剪，需在独立轮次评估
3. `operations/services` 剩余专项项（`history_backfill_service.py`、`market_mood_walkforward_validation_service.py`）仍按既定策略暂缓

### 33) web 静态资源主路径收口到 `app/web/static`

本轮目标（单目标）：

1. 将 web 运行所需静态资源从 legacy `src/platform/web/static` 收口到 `src/app/web/static`，让运行资源与 `app/web` 主实现共址。

删除/迁移前审计：

1. `src/tests/scripts` 范围内无 `src.platform.web*` 运行导入。
2. 静态目录引用仅来自 `src/app/web/settings.py` 的 `STATIC_DIR` 配置。
3. `src/app/web/app.py` 通过 `STATIC_DIR` 挂载 `/static` 与 `platform-check.html`，迁移不涉及路由语义变化。

本轮动作（已执行）：

1. `git mv src/platform/web/static -> src/app/web/static`
2. 更新 `src/app/web/settings.py`：
   - `STATIC_DIR` 从 `.../platform/web/static` 改为 `src/app/web/static` 同目录定位

本轮结果：

1. 运行静态资源完全由 `app/web` 承接。
2. `platform/web` 不再承接任何运行时代码或静态资源主路径，仅保留目录骨架（compat/legacy）。
