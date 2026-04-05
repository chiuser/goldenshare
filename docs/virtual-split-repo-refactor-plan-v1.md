# 虚拟拆仓目录重构方案 v1（Foundation / Ops / Biz）

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
- `src/models/raw/*` -> `src/foundation/models/raw/*`
- `src/models/core/*` -> `src/foundation/models/core/*`
- `src/models/ops/*` -> `src/ops/models/ops/*`
- `src/services/sync/*` -> `src/foundation/services/sync/*`
- `src/services/transform/*` -> `src/foundation/services/transform/*`
- `src/operations/*` -> `src/ops/*`
- `src/web/api/v1/ops/*` -> `src/ops/api/*`
- `src/web/queries/ops/*` -> `src/ops/queries/*`
- `src/web/schemas/ops/*` -> `src/ops/schemas/*`
- `src/web/services/ops/*` -> `src/ops/services/*`
- `src/web/api/v1/quote.py` + `market.py` -> `src/biz/api/*`
- `src/web/queries/quote_query_service.py` -> `src/biz/queries/*`
- `src/web/schemas/quote.py` -> `src/biz/schemas/*`
- `src/web/app.py`, `src/web/middleware/*`, `src/web/lifespan.py` -> `src/platform/web/*`
- `src/web/auth/*` -> `src/platform/auth/*`
- `src/web/dependencies.py` -> `src/platform/dependencies/*`
- `src/web/exceptions.py` -> `src/platform/exceptions/*`

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

