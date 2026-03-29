# Goldenshare Web 平台一期 Low Level Design

## 1. 文档目标

本文档是 `goldenshare` Web 平台一期的低层设计文档。

它的目标不是描述愿景，而是为后续实现提供可以直接执行的蓝图。实现时应同时遵守以下文档：

- [design-principles.md](/Users/congming/github/goldenshare/docs/design-principles.md)
- [web-platform-phase1.md](/Users/congming/github/goldenshare/docs/web-platform-phase1.md)

本 LLD 聚焦一期平台能力，不包含业务页面迁移和业务 API。

## 2. 一期边界

### 2.1 一期要做的内容

- 建立独立的 Web 应用入口
- 建立 Web 配置体系
- 建立 `app` schema 和用户表
- 建立认证与权限基础能力
- 建立平台级 API
- 建立平台测试页面
- 建立平台回归测试
- 建立本地开发与远程生产的统一部署方式

### 2.2 一期明确不做的内容

- 不做行情查询 API
- 不做持仓业务 API
- 不做情绪页业务 API
- 不做 admin 业务模块
- 不做旧仓库页面迁移
- 不做 RBAC 全量权限系统
- 不做 refresh token
- 不做用户偏好、收藏、自选等业务表

## 3. 实施结果总览

一期完成后，项目应具备如下能力：

1. 可以通过统一入口启动 Web 服务
2. 可以通过环境配置区分本地开发和生产部署
3. 可以创建用户并进行登录
4. 可以通过 token 获取当前用户
5. 可以区分普通用户和管理员
6. 提供平台级健康检查接口
7. 提供平台级验证页面 `/platform-check`
8. 有一套平台回归测试作为后续防腐基线

## 4. 目录与模块设计

### 4.1 目标目录结构

建议新增如下结构：

```text
docs/
  design-principles.md
  web-platform-phase1.md
  web-platform-phase1-lld.md

src/web/
  __init__.py
  app.py
  lifespan.py
  run.py
  settings.py
  dependencies.py
  exceptions.py
  logging.py

  api/
    __init__.py
    router.py
    v1/
      __init__.py
      router.py
      auth.py
      users.py
      admin.py
      health.py

  auth/
    __init__.py
    jwt_service.py
    password_service.py
    dependencies.py

  schemas/
    __init__.py
    common.py
    auth.py
    user.py

  services/
    __init__.py
    auth_service.py
    user_service.py

  repositories/
    __init__.py
    user_repository.py

  domain/
    __init__.py
    user.py
    auth.py

  middleware/
    __init__.py
    request_id.py
    access_log.py

  scripts/
    __init__.py
    create_user.py

  static/
    platform-check.html
    platform-check.js

src/models/
  app/
    __init__.py
    app_user.py

tests/web/
  test_health_api.py
  test_auth_api.py
  test_admin_api.py
  test_user_repository.py
  test_auth_services.py
  test_platform_check_page.py

.env.web.example
scripts/goldenshare-web.service
```

### 4.2 模块职责

#### `src/web/app.py`

职责：

- 创建 FastAPI app
- 注册中间件
- 注册异常处理器
- 挂载静态文件
- 注册根路由与 API 路由

不负责：

- 业务逻辑
- 数据库查询

#### `src/web/lifespan.py`

职责：

- Web app 启停生命周期管理
- 启动时记录配置摘要
- 可选做数据库可用性预检查

#### `src/web/settings.py`

职责：

- 定义 Web 独立配置模型
- 加载环境变量和环境文件
- 提供强类型配置对象

#### `src/web/dependencies.py`

职责：

- 提供通用依赖，例如数据库 session
- 为 `api` 层提供统一依赖入口

#### `src/web/exceptions.py`

职责：

- 定义 Web 层业务异常
- 注册统一异常处理逻辑
- 输出统一错误响应结构

#### `src/web/logging.py`

职责：

- 配置 Web 日志格式
- 提供 request_id 感知能力

#### `src/web/api/`

职责：

- 组织 API 路由
- 按版本聚合路由
- 控制 HTTP 协议层边界

#### `src/web/auth/`

职责：

- 密码哈希和校验
- JWT 编码和解码
- 鉴权依赖
- 权限依赖

#### `src/web/schemas/`

职责：

- 请求模型
- 响应模型
- 错误响应模型

#### `src/web/services/`

职责：

- 登录流程
- 当前用户流程
- 用户信息读取流程

#### `src/web/repositories/`

职责：

- 操作 `app.app_user`
- 提供明确的用户查询和写入方法

#### `src/web/domain/`

职责：

- 用户状态枚举、权限概念、token payload 概念模型

#### `src/web/middleware/`

职责：

- request_id 注入
- access log 记录

#### `src/web/scripts/`

职责：

- 创建管理员或普通用户
- 为本地和部署后验证提供最小操作入口

## 5. 配置设计

### 5.1 配置原则

- 一套代码，两套环境
- 通过配置区分本地和生产
- 不通过代码分叉区分环境

### 5.2 建议配置项

建议在 `src/web/settings.py` 中定义如下配置项：

- `app_env`
- `database_url`
- `web_host`
- `web_port`
- `web_debug`
- `web_log_level`
- `web_cors_origins`
- `jwt_secret`
- `jwt_expire_minutes`
- `platform_check_enabled`

### 5.3 环境变量建议

建议名称：

- `APP_ENV`
- `DATABASE_URL`
- `WEB_HOST`
- `WEB_PORT`
- `WEB_DEBUG`
- `WEB_LOG_LEVEL`
- `WEB_CORS_ORIGINS`
- `JWT_SECRET`
- `JWT_EXPIRE_MINUTES`
- `PLATFORM_CHECK_ENABLED`
- `GOLDENSHARE_ENV_FILE`

### 5.4 环境文件建议

#### 本地开发

建议文件：

- `.env.web.local`

这里的“本地开发”表示 Web 服务运行在本地机器上，不代表数据库必须是本地数据库。
允许采用“本地 Web + 远程数据库”的开发形态。

示例：

```env
APP_ENV=local
DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/goldenshare
WEB_HOST=127.0.0.1
WEB_PORT=8000
WEB_DEBUG=true
WEB_LOG_LEVEL=DEBUG
WEB_CORS_ORIGINS=http://127.0.0.1:8000,http://localhost:8000
JWT_SECRET=local_dev_secret
JWT_EXPIRE_MINUTES=480
PLATFORM_CHECK_ENABLED=true
```

#### 远程生产

建议文件：

- `/etc/goldenshare/web.env`

示例：

```env
APP_ENV=production
DATABASE_URL=postgresql+psycopg://goldenshare_user:password@127.0.0.1:5432/goldenshare
WEB_HOST=0.0.0.0
WEB_PORT=8000
WEB_DEBUG=false
WEB_LOG_LEVEL=INFO
WEB_CORS_ORIGINS=https://your-domain.example
JWT_SECRET=strong_production_secret
JWT_EXPIRE_MINUTES=480
PLATFORM_CHECK_ENABLED=true
```

### 5.5 配置加载规则

建议按如下优先级加载：

1. 已存在的进程环境变量
2. `GOLDENSHARE_ENV_FILE` 指向的环境文件
3. settings 中的默认值

注意：

- 生产必须显式配置 `JWT_SECRET`
- `WEB_DEBUG` 在生产应为 false

## 6. 启动与部署设计

### 6.1 启动入口

统一入口：

```bash
uvicorn src.web.app:app
```

同时建议提供一个配置驱动的 Python 启动入口：

```bash
python -m src.web.run
```

如果项目已安装，也可以提供命令行入口：

```bash
goldenshare-web
```

### 6.2 本地开发启动方式

```bash
export GOLDENSHARE_ENV_FILE=.env.web.local
python -m src.web.run
```

### 6.3 远程生产启动方式

```bash
export GOLDENSHARE_ENV_FILE=/etc/goldenshare/web.env
python -m src.web.run
```

### 6.4 部署建议

一期建议至少补充：

- `.env.web.example`
- 一份 systemd 样例配置
- 一份 Web 启动文档
- 一份本地 smoke 文档

### 6.5 systemd 样例建议

可在文档中给出类似：

```ini
[Unit]
Description=Goldenshare Web
After=network.target

[Service]
WorkingDirectory=/opt/goldenshare
Environment=GOLDENSHARE_ENV_FILE=/etc/goldenshare/web.env
ExecStart=/opt/goldenshare/.venv/bin/uvicorn src.web.app:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

## 7. 数据库设计

### 7.1 schema

新增：

- `app`

### 7.2 表设计：`app.app_user`

建议字段如下：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer pk | 用户主键 |
| `username` | varchar(64) not null unique | 登录用户名 |
| `password_hash` | varchar(255) not null | 密码哈希 |
| `display_name` | varchar(128) null | 展示名 |
| `email` | varchar(255) null | 邮箱 |
| `is_admin` | boolean not null default false | 是否管理员 |
| `is_active` | boolean not null default true | 是否激活 |
| `last_login_at` | timestamptz null | 最近登录时间 |
| `created_at` | timestamptz not null | 创建时间 |
| `updated_at` | timestamptz not null | 更新时间 |

### 7.3 索引建议

- unique index on `username`
- optional index on `email`
- optional index on `is_active`

### 7.4 migration 设计

建议新增一份 migration，内容包括：

1. 创建 `app` schema
2. 创建 `app.app_user`
3. 创建约束和索引

### 7.5 model 设计

建议新增：

- `src/models/app/app_user.py`

同时更新：

- `src/models/all_models.py`

注意：

- `app.app_user` 是应用层数据
- 不应放进 `core`

## 8. 认证与权限设计

### 8.1 密码服务

文件：

- `src/web/auth/password_service.py`

职责：

- `hash_password(password)`
- `verify_password(password, password_hash)`

建议使用成熟库，不自行实现哈希逻辑。

### 8.2 JWT 服务

文件：

- `src/web/auth/jwt_service.py`

职责：

- 生成 access token
- 解码 token
- 校验过期时间

建议 payload：

- `sub`
- `username`
- `is_admin`
- `exp`

### 8.3 鉴权依赖

文件：

- `src/web/auth/dependencies.py`

建议提供：

- `get_current_user`
- `require_authenticated`
- `require_admin`

实现规则：

- 先解 token
- 再回查数据库
- 再校验 `is_active`

### 8.4 一期权限模型

一期仅支持：

- 未登录
- 已登录用户
- 管理员

权限字段只使用：

- `is_active`
- `is_admin`

## 9. API 详细设计

### 9.1 路由总览

一期 API 如下：

- `GET /api/health`
- `GET /api/v1/health`
- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`
- `POST /api/v1/auth/logout`
- `GET /api/v1/users/me`
- `GET /api/v1/admin/ping`

### 9.2 健康检查接口

#### `GET /api/health`

用途：

- 部署探活
- 最小 smoke

返回示例：

```json
{
  "status": "ok",
  "service": "goldenshare-web",
  "env": "local"
}
```

#### `GET /api/v1/health`

用途：

- 平台 API 版本路径验证

返回结构可与 `/api/health` 保持一致。

### 9.3 登录接口

#### `POST /api/v1/auth/login`

请求：

```json
{
  "username": "admin",
  "password": "your_password"
}
```

返回：

```json
{
  "token": "jwt_token",
  "username": "admin",
  "is_admin": true,
  "display_name": "Administrator"
}
```

处理流程：

1. 根据 `username` 查用户
2. 验证 `is_active`
3. 验证密码
4. 签发 token
5. 更新 `last_login_at`

### 9.4 当前用户接口

#### `GET /api/v1/auth/me`

用途：

- 验证 token 链路
- 返回当前用户最小资料

返回示例：

```json
{
  "id": 1,
  "username": "admin",
  "display_name": "Administrator",
  "is_admin": true,
  "is_active": true
}
```

### 9.5 用户自查接口

#### `GET /api/v1/users/me`

可以与 `auth/me` 结构相同，主要用于保留用户领域边界。

### 9.6 登出接口

#### `POST /api/v1/auth/logout`

一期建议：

- 保持幂等
- 前端删除 token 即完成登出
- 服务端先返回简单成功结果即可

返回示例：

```json
{
  "ok": true
}
```

### 9.7 管理员验证接口

#### `GET /api/v1/admin/ping`

用途：

- 验证管理员权限依赖是否正确
- 作为非业务 admin 回归接口

普通用户：

- 返回 403

管理员：

- 返回 200

返回示例：

```json
{
  "ok": true,
  "role": "admin"
}
```

## 10. 请求与响应 schema 设计

### 10.1 `schemas/common.py`

建议定义：

- `HealthResponse`
- `OkResponse`
- `ApiErrorResponse`

### 10.2 `schemas/auth.py`

建议定义：

- `LoginRequest`
- `TokenResponse`
- `CurrentUserResponse`

### 10.3 错误响应结构

建议统一为：

```json
{
  "code": "unauthorized",
  "message": "Authentication required",
  "request_id": "xxxx"
}
```

建议标准错误码：

- `validation_error`
- `unauthorized`
- `forbidden`
- `not_found`
- `conflict`
- `internal_error`

## 11. Repository 与 Service 详细设计

### 11.1 `UserRepository`

文件：

- `src/web/repositories/user_repository.py`

建议方法：

- `get_by_id(session, user_id)`
- `get_by_username(session, username)`
- `create_user(session, ...)`
- `update_last_login(session, user_id, ts)`

### 11.2 `AuthService`

文件：

- `src/web/services/auth_service.py`

建议方法：

- `login(session, username, password)`
- `build_current_user_response(user)`

### 11.3 `UserService`

文件：

- `src/web/services/user_service.py`

建议方法：

- `get_self_profile(user)`

## 12. 中间件与异常处理设计

### 12.1 `request_id` 中间件

文件：

- `src/web/middleware/request_id.py`

职责：

- 为每个请求生成 request_id
- 如果请求头已有 request id，可透传
- 将 request_id 挂到 request.state
- 回写到响应头

建议响应头：

- `X-Request-ID`

### 12.2 `access_log` 中间件

文件：

- `src/web/middleware/access_log.py`

记录字段建议：

- request_id
- method
- path
- status_code
- duration_ms
- user_id（如可用）

### 12.3 异常处理

文件：

- `src/web/exceptions.py`

建议处理：

- `RequestValidationError`
- `HTTPException`
- 自定义 `WebAppError`
- 未知异常

目标：

- 统一错误响应
- 保留 request_id
- 记录错误日志

## 13. 平台测试页面设计

### 13.1 页面定位

这是平台验证页，不是业务页。

建议路径：

- `/platform-check`

### 13.2 页面用途

验证以下能力：

- 静态资源可访问
- 健康检查可访问
- 登录可用
- token 可用
- 当前用户接口可用
- 管理员权限接口可用
- 错误响应和 request_id 可观察

### 13.3 页面组成建议

#### 区块 1：平台信息

- 当前环境
- 服务状态
- `/api/health` 返回结果

#### 区块 2：登录测试

- 用户名输入框
- 密码输入框
- 登录按钮
- token 状态展示

#### 区块 3：当前用户测试

- 调用 `/api/v1/auth/me`
- 展示返回结果

#### 区块 4：管理员权限测试

- 调用 `/api/v1/admin/ping`
- 展示成功或失败

#### 区块 5：请求信息

- 展示最近一次 request_id
- 展示最近一次错误响应

### 13.4 前端实现建议

文件：

- `src/web/static/platform-check.html`
- `src/web/static/platform-check.js`

要求：

- 简单、稳定、无业务耦合
- 不接入正式业务导航
- 易于人工 smoke

## 14. 测试设计

### 14.1 测试目标

平台测试是长期防腐资产。

后续新增业务功能或平台修改时，必须回归执行。

### 14.2 API 测试清单

#### `tests/web/test_health_api.py`

覆盖：

- `/api/health`
- `/api/v1/health`

#### `tests/web/test_auth_api.py`

覆盖：

- login success
- login invalid password
- login inactive user
- `auth/me` 未登录
- `auth/me` 已登录
- logout

#### `tests/web/test_admin_api.py`

覆盖：

- 普通用户访问 `admin/ping` 返回 403
- 管理员访问 `admin/ping` 返回 200

### 14.3 Repository / Service 测试清单

#### `tests/web/test_user_repository.py`

覆盖：

- create user
- get by username
- get by id
- update last login

#### `tests/web/test_auth_services.py`

覆盖：

- hash password
- verify password
- generate jwt
- decode jwt
- invalid jwt
- expired jwt

### 14.4 页面 smoke 测试

#### `tests/web/test_platform_check_page.py`

最小覆盖：

- `/platform-check` 可访问
- 页面引用的 JS 存在

如果后续引入浏览器自动化，则应优先把 `/platform-check` 作为第一个 E2E smoke 页面。

### 14.5 平台回归规则

以下改动必须执行平台回归：

- 新增任何 Web 业务模块
- 修改认证逻辑
- 修改权限逻辑
- 修改中间件
- 修改异常处理
- 修改配置加载
- 修改 app 启动方式
- 修改部署方式

## 15. 创建用户脚本设计

文件：

- `src/web/scripts/create_user.py`

建议参数：

- `--username`
- `--password`
- `--display-name`
- `--email`
- `--admin`

行为：

- 创建用户
- 密码做哈希
- 可指定管理员

用途：

- 本地初始化
- 部署后初始化管理员
- 平台 smoke 验证

## 16. 实施顺序

### Step 1

建立目录骨架：

- `src/web/`
- `tests/web/`
- 文档文件

### Step 2

实现配置与 app 入口：

- `settings.py`
- `app.py`
- `lifespan.py`
- `api/router.py`
- `api/v1/router.py`

### Step 3

实现中间件和异常处理：

- `request_id`
- `access_log`
- 统一错误响应

### Step 4

实现 migration 和 model：

- `app.app_user`
- `AppUser` model

### Step 5

实现 repository / auth / services：

- `UserRepository`
- `PasswordService`
- `JWTService`
- `AuthService`
- `UserService`

### Step 6

实现平台 API：

- health
- login
- me
- logout
- admin ping

### Step 7

实现用户创建脚本：

- `create_user.py`

### Step 8

实现平台测试页面：

- `platform-check.html`
- `platform-check.js`

### Step 9

实现自动化测试：

- API
- service
- repository
- page smoke

### Step 10

补部署文档与回归说明。

## 17. 验收标准

一期开发完成后，应满足：

1. `uvicorn src.web.app:app --reload` 可在本地启动
2. 通过 `GOLDENSHARE_ENV_FILE` 可切换本地与生产配置
3. 数据库已创建 `app.app_user`
4. 可通过脚本创建管理员用户
5. `/api/health` 返回正常
6. `/api/v1/auth/login` 可登录
7. `/api/v1/auth/me` 可返回当前用户
8. `/api/v1/admin/ping` 权限判断正确
9. `/platform-check` 可正常访问
10. 平台自动化测试通过
11. 文档完整

## 18. 后续衔接

一期完成后，二期才进入业务模块设计。

建议二期起点：

1. `market` 领域基础查询
2. 页面级 BFF 查询服务
3. 第一个真实业务页迁移

但这些都不应提前进入一期实现。
