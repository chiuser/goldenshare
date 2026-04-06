# 虚拟拆仓目录重构方案 v1（Foundation / Ops / Biz）

> 历史迁移文档（归档）：该方案用于记录拆分过程。当前生效结构请以 [current-architecture-baseline.md](/Users/congming/github/goldenshare/docs/architecture/current-architecture-baseline.md) 为准。

## 1. 目标

在**单仓库**内完成“可拆仓”结构改造，使三团队可以低耦合并行开发，同时保持现有一键发布能力。

本阶段仅做“虚拟拆仓”：

- 调整目录和代码边界
- 保持当前运行行为不变
- 不做物理拆仓

---

## 2. 目标目录树（v1）

```text
src/
  foundation/
    clients/
    config/
    dao/
    models/
      raw/
      core/
      dm/                 # 预留，后续补齐
    services/
      sync/
      transform/
    scripts/

  ops/
    models/ops/
    runtime/
    services/
    specs/
    api/                  # 对应 /api/v1/ops
    queries/
    schemas/

  biz/
    api/                  # 对应 /api/v1/quote, /api/v1/market
    queries/
    schemas/
    services/

  platform/
    web/                  # FastAPI app 装配、middleware、auth、router 聚合
    auth/
    dependencies/
    exceptions/

  shared/
    contracts/            # 跨子系统稳定 DTO / 错误码 / 常量
    utils/
```

说明：

- `platform` 放“跨系统运行时基础设施”，避免 Ops/Biz 各自重复造轮子。
- `shared/contracts` 只放稳定契约，禁止放具体业务实现。

---

## 3. 现有目录映射（迁移映射表）

- `src/clients/*` -> `src/foundation/clients/*`
- `src/config/*` -> `src/foundation/config/*`（平台启动读取通过适配层导出）
- `src/dao/*` -> `src/foundation/dao/*`
- `src/foundation/models/raw/*` -> `src/foundation/models/raw/*`
- `src/foundation/models/core/*` -> `src/foundation/models/core/*`
- `src/ops/models/ops/*` -> `src/ops/models/ops/*`
- `src/foundation/services/sync/*` -> `src/foundation/services/sync/*`
- `src/foundation/services/transform/*` -> `src/foundation/services/transform/*`
- `src/operations/*` -> `src/ops/*`
- `src/ops/api/*` -> `src/ops/api/*`
- `src/ops/queries/*` -> `src/ops/queries/*`
- `src/ops/schemas/*` -> `src/ops/schemas/*`
- `src/ops/services/*` -> `src/ops/services/*`
- `src/biz/api/quote.py` + `market.py` -> `src/biz/api/*`
- `src/biz/queries/quote_query_service.py` -> `src/biz/queries/*`
- `src/biz/schemas/quote.py` -> `src/biz/schemas/*`
- `src/platform/web/app.py`, `src/platform/web/middleware/*`, `src/platform/web/lifespan.py` -> `src/platform/web/*`
- `src/platform/auth/*` -> `src/platform/auth/*`
- `src/platform/dependencies/db.py` -> `src/platform/dependencies/*`
- `src/platform/exceptions/web.py` -> `src/platform/exceptions/*`

---

## 4. 分阶段迁移清单（每步可独立回滚）

## Phase 0：冻结与基线

目标：

- 先建立“可验证基线”，避免迁移过程误伤。

动作：

1. 跑全量预检：`bash scripts/release-preflight.sh`
2. 记录基线 commit（tag：`virtual-split-baseline`）
3. 锁定非迁移功能开发（仅修复阻塞 bug）

回滚点：

- 直接 `git checkout virtual-split-baseline`

---

## Phase 1：目录骨架与兼容导出层

目标：

- 新建目标目录，不动业务逻辑。

动作：

1. 创建 `src/foundation`, `src/ops`, `src/biz`, `src/platform`, `src/shared`
2. 在新路径下创建 `__init__.py`
3. 对关键模块先“复制 + 兼容导出”：
   - 旧路径保留，内部 `from 新路径 import *`

回滚点：

- 删除新目录并恢复旧导出文件（单次 commit 回滚）

---

## Phase 2：Foundation 迁移

目标：

- 完成数据基座代码迁移，保证同步/回补可运行。

动作：

1. 迁移 `clients/config/dao/models(raw/core)/services(sync,transform)`
2. 修改 import 指向新路径
3. 保留旧路径兼容导出（至少一个迭代周期）

回滚点：

- 回滚 Foundation 迁移 commit（不影响 Ops/Biz）

验收：

- `pytest` 中基础同步与 DAO 测试通过
- CLI 同步命令可运行

---

## Phase 3：Ops 迁移

目标：

- 完成运维控制面迁移，保持 `/api/v1/ops/*` 行为一致。

动作：

1. 迁移 `operations/*` 与 `web/api/v1/ops/*` 相关代码到 `src/ops/*`
2. `src/platform/web/router` 引入 `ops.api.router`
3. 旧路径保留兼容导出

回滚点：

- 回滚 Ops 迁移 commit，恢复旧 router 引用

验收：

- `tests/web/test_ops_*` 全部通过
- 运维前端关键页面 smoke 通过

---

## Phase 4：Biz 迁移

目标：

- 完成业务接口层迁移，保持 `/api/v1/quote/*` 与 `/api/v1/market/*` 行为一致。

动作：

1. 迁移 Biz API/Query/Schema 到 `src/biz/*`
2. `src/platform/web/router` 引入 `biz.api.router`
3. 旧路径兼容导出

回滚点：

- 回滚 Biz 迁移 commit

验收：

- `tests/web/test_quote_api.py` 通过
- 行情页面接口联调通过

---

## Phase 5：平台层收口

目标：

- 将 `web` 入口收敛到 `platform`，完成统一装配。

动作：

1. `app.py/lifespan/middleware/auth/dependencies/exceptions` 迁移到 `src/platform/*`
2. `src/web/*` 仅保留兼容入口（薄封装）

回滚点：

- 回滚平台迁移 commit

验收：

- 健康检查、登录、ops、biz 全部可用

---

## Phase 6：边界门禁上锁

目标：

- 从“约定”升级为“工程约束”。

动作：

1. 增加 import 边界检查（禁止 Biz 直连 Foundation 内部实现）
2. 增加 `CODEOWNERS`
3. CI 分轨：`foundation-ci`, `ops-ci`, `biz-ci`, `contract-ci`

回滚点：

- 关闭新增 CI 规则，保留目录结构

---

## 5. 风险与控制

高风险点：

- import 链路迁移导致运行时找不到模块
- alembic/model 导入路径变更影响迁移脚本
- 脚本入口（CLI / systemd）路径不一致

控制措施：

- 每个 Phase 独立 commit + 可回滚
- 旧路径兼容导出至少保留一个迭代
- 每个 Phase 必跑预检与关键测试

---

## 6. 每阶段固定验收命令

```bash
bash scripts/release-preflight.sh
pytest -q tests/web/test_quote_api.py tests/web/test_health_api.py
pytest -q tests/web/test_ops_overview_api.py tests/web/test_ops_execution_api.py tests/web/test_ops_schedule_api.py tests/web/test_ops_runtime_api.py
```

---

## 7. 迁移进展（2026-04-05）

### 已完成

- `platform.auth` 已成为认证真实实现层：
  - 新增 `src/platform/auth/domain.py`（`AuthenticatedUser` / `TokenPayload`）
  - 新增 `src/platform/auth/user_repository.py`
  - `src/web/domain/*` 与 `src/web/repositories/user_repository.py` 改为兼容壳
- `ops` 与 `biz` 已去除对 `src.web.domain` / `src.web.repositories` 的直接依赖。
- `operations.services.dataset_status_snapshot_service` 已从 `web` 查询层切换到 `ops` 查询层：
  - `src.web.queries.ops.*` -> `src.ops.queries.*`
  - `src.web.schemas.ops.*` -> `src.ops.schemas.*`
- 业务代码中（`src/models/**` 之外）`from src.models.*` 引用已清零：
  - `src.models.core.*` -> `src.foundation.models.core.*`
  - `src.models.raw.*` -> `src.foundation.models.raw.*`
  - `src.models.ops.*` -> `src.ops.models.ops.*`
- 新增 `src/platform/models/app/__init__.py`，承接 `AppUser` 的平台命名空间。
- API 聚合入口已上提到 `platform`：
  - 新增 `src/platform/api/router.py`
  - 新增 `src/platform/api/v1/router.py`
  - 新增 `src/platform/api/v1/{health,auth,users,admin,share}.py`
  - `src/platform/web/app.py` 已改为引用 `platform.api.router`
  - `src/web/api/router.py` 与 `src/web/api/v1/{router,health,auth,users,admin,share}.py` 改为兼容壳

### 兼容层现状

- `web.api` / `web.api.v1` 包入口已改为无副作用壳，避免路由导入循环。
- `ops/biz/operations` 已不再依赖 `src.web.*`。
- 为避免“平台直连 web 实现”，已新增兼容命名空间：
  - `src/platform/schemas/*`
  - `src/platform/services/*`
  - `src/platform/queries/*`
  当前已完成真实实现上提（不再从 `platform` 反向 import `src.web.*`）：
  - `platform.schemas.{common,auth,share}`
  - `platform.services.{auth_service,user_service}`
  - `platform.queries.share_market_query_service`
  对应 `web` 模块已降级为兼容壳。
- 新增架构守门测试：
  - `tests/architecture/test_virtual_split_boundaries.py`
  - 防止 `platform/ops/biz/foundation/operations` 重新引入 `src.web.*` / `src.models.*` 旧依赖。
- Foundation 与 Operations 解耦再推进：
  - `foundation.services.sync.base_sync_service` 不再反向依赖 `operations` 刷新 snapshot 服务。
  - snapshot 刷新改为由 `ops/operations/cli` 调用方显式触发（控制面职责收口）。
  - `ExecutionCanceledError` 已下沉至 `foundation.services.sync.errors`，`operations.runtime.errors` 改为兼容壳。
- Backfill 编排服务已收口到 Operations：
  - 新增 `src/operations/services/history_backfill_service.py`（真实实现）。
  - `src/operations/services/history_backfill_service.py` 改为兼容壳。
  - `cli` 与 `operations.runtime.dispatcher` 已切换到新路径。
- 基础 schema 已归并到 Foundation：
  - 新增 `src/foundation/schemas.py`（`TushareEnvelope` / `SyncResult` 等）。
  - `src/schemas.py` 改为兼容壳。

### 本轮验证结果

- `python3 -m compileall src` 通过
- 回归测试通过：
  - `32 passed`（认证/基础 ops/foundation 相关）
  - `52 passed`（ops api + quote api + runtime 相关）
  - `25 passed`（health/auth/admin/runtime/quote 路由回归）
  - `44 passed`（ops api 全链路回归）
  - `19 passed`（foundation dao/sync/spec 回归）
  - `60 passed`（platform api 上提后的 web 接口回归）
  - `93 passed`（platform 实化后综合回归）
  - `1 passed`（架构边界守门测试）
  - `30 passed`（关键链路快速回归）
  - `5 passed`（架构边界 + foundation 解耦相关测试）
  - `89 passed`（综合回归，含 ops/biz/web/foundation 主路径）
  - `52 passed`（history backfill + cli + ops runtime 相关回归）
  - `57 passed`（继续迁移后的关键回归）

### 发版脚本（分层）

- 新增 `scripts/deploy-layered-systemd.sh`，支持按子系统分层重启与自检。
- 层级开关：
  - `DEPLOY_FOUNDATION`
  - `DEPLOY_OPS`
  - `DEPLOY_PLATFORM`
- 与旧脚本 `scripts/deploy-systemd.sh` 可并存，便于平滑过渡。

---

## 7. 当前迁移进度（2026-04-05）

- [x] Phase 1：目录骨架建立（`foundation/ops/biz/platform/shared`）
- [x] Foundation 第一批：`config`、`clients` 已实迁移，旧路径兼容导出已保留
- [x] Biz 第一批：
  - `biz/queries/quote_query_service.py` 实迁移
  - `biz/schemas/quote.py` 实迁移
  - `biz/api/quote.py`、`biz/api/market.py` 实迁移
  - `web` 对应路径改为兼容 shim
- [x] Platform 第一批：
  - `platform/web/app.py` 实迁移
  - `web/app.py` 改为兼容 shim
- [x] Ops 第一批：
  - `ops/schemas/*`、`ops/queries/*`、`ops/services/*` 已实迁移
  - `web/api/v1/ops/*` 已改为依赖 `src.ops.*`
  - `web` 侧 `queries/schemas/services` 聚合入口（`__init__.py`）已切换到 `src.ops.*`
- [x] Ops 第二批：
  - `ops/api/{overview,freshness,schedules,executions,runtime,catalog}.py` 已实迁移
  - `ops/api/router.py` 已改为真实聚合入口
  - `web/api/v1/ops/*` 已改为兼容 shim（并保留测试 patch 需要的符号透传）
- [x] 回归验证：
  - `tests/web/test_ops_*` 关键集通过
  - `tests/web/test_quote_api.py`、`tests/web/test_health_api.py` 通过
- [x] Platform 第二批：
  - `platform/exceptions` 已实迁移（`web/exceptions.py` shim）
  - `platform/dependencies` 已实迁移（`web/dependencies.py` shim）
  - `platform/auth` 已实迁移（`web/auth/*` shim）
  - `platform/web/app.py` 已改用 `platform.exceptions`
- [x] Platform 第三批（进行中）：
  - `platform/web/lifespan.py` 已实迁移（`web/lifespan.py` shim）
  - `platform/web/middleware/*` 已实迁移（`web/middleware/*` shim）
  - `platform/web/settings.py`、`platform/web/logging.py` 已实迁移（`web/settings.py`、`web/logging.py` shim）
- [x] 兼容债清理（阶段性）：
  - `web/queries/ops/*`、`web/services/ops/*`、`web/schemas/ops/*` 已全部改为兼容 shim，消除双份实现漂移风险
  - `ops/biz/operations/platform` 已不再直接依赖 `src.web.{auth,dependencies,exceptions,settings,logging}`
  - `ops/operations` 已不再直接依赖 `src.models.ops.*`，统一切到 `src.ops.models.ops.*`
- [x] Foundation 第二批（进行中）：
  - `foundation/services/sync/{base_sync_service,fields,resource_sync,registry}.py` 已成为真实实现落位
  - `services/sync` 对应四个模块已改为兼容 shim
  - `src/foundation/services/sync/*.py` 内部依赖已切到 `src.foundation.services.sync.*`
  - `cli / operations / history_backfill` 对 `sync registry` 已切到 `foundation` 路径
  - `foundation/services/transform/*` 已成为真实实现落位（6 个模块）
  - `services/transform/*` 已切换为兼容 shim
  - `sync` 服务与脚本对 `transform` 依赖已切到 `foundation` 路径
  - `foundation/dao/{base_dao,generic,factory}.py` 已成为真实实现落位
  - `dao/{base_dao,generic,factory}.py` 已切换为兼容 shim
  - `history_backfill` 与 `sync_job_state_reconciliation` 已切到 `foundation.dao.factory` 路径

### 下一步（建议顺序）

1. Foundation 第二批：`models`、`services(sync/transform)` 从“映射层”推进到“真实实现落位”。
2. 兼容层收敛：在确认外部入口稳定后，逐步移除 `web/*` shim（先内部引用清零，再删文件）。
3. 边界门禁落地：补 import-lint 与 CI 分轨初版（先告警后阻断）。

---

## 7. 完成标准（Definition of Done）

满足以下条件视为“虚拟拆仓完成”：

1. 三子系统目录与代码归属稳定
2. 旧路径兼容层仍可运行（临时）
3. CI 分轨和边界规则生效
4. 发布脚本仍支持一键发布
5. 对外接口行为与错误码无破坏性变化

---

## 8. 下一步（Phase 1 开始执行）

执行顺序建议：

1. 先做 Phase 1（目录骨架 + 兼容导出层）
2. 通过后进入 Phase 2（Foundation）
3. 再按 3 -> 4 -> 5 -> 6 逐步推进
