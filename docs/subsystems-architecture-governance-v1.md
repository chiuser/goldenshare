# 三子系统架构治理规范（Foundation / Ops / Biz）v1

## 1. 目的

本规范用于支撑三团队并行开发：

- Foundation 团队（数据基座）
- Ops 团队（运维平台）
- Biz 团队（业务接口服务）

目标是“单仓库、强边界、低耦合、可持续迭代”。

---

## 2. 当前工程结构评估（基于现状）

当前仓库已经具备三子系统雏形，优点：

- 数据层按 schema 分离清晰（`raw/core/ops/app/dm`）
- 运维能力独立在 `src/operations/*`
- Web 层有独立 router/schema/query/service 分层
- Biz 接口已开始独立在 `/api/v1/quote/*` 与 `/api/v1/market/*`

当前主要风险：

- 依赖边界尚未被“工程化强制”（主要靠约定）
- `src/web` 内 Ops/Biz 代码并存，新增同学容易跨边界引用
- 缺少目录级代码所有权与跨团队变更门禁
- 缺少分层 CI（Foundation/Ops/Biz 分轨）

结论：

- 代码架构“可用但未固化治理”，适合继续开发，但不适合长期无约束扩张。

---

## 3. 三子系统定义与职责

## 3.1 Foundation（数据基座）

职责：

- 数据采集、同步、回补、转换、落库
- `raw/core/dm` 模型与数据质量治理
- 数据能力对外契约（供 Ops/Biz 消费）

代码归属（当前）：

- `src/clients/*`
- `src/services/sync/*`
- `src/services/transform/*`
- `src/dao/*`
- `src/models/raw/*`
- `src/models/core/*`
- `src/models/dm/*`（未来）

禁止行为：

- 直接实现页面交互逻辑
- 为临时页面需求破坏 `core` 语义

## 3.2 Ops（运维平台）

职责：

- 调度、执行、重试、取消、进度、日志、新鲜度
- 运维管理台 API 与前端
- ops 控制面状态与可观测性

代码归属（当前）：

- `src/operations/*`
- `src/models/ops/*`
- `src/web/api/v1/ops/*`
- `src/web/queries/ops/*`
- `src/web/services/ops/*`
- `src/web/schemas/ops/*`

禁止行为：

- 直接修改 Biz 对外契约
- 绕过 Foundation 边界执行临时数据逻辑

## 3.3 Biz（业务接口服务）

职责：

- 面向业务主系统的对外 API（BFF/业务服务）
- 统一聚合 `core/dm` 数据，输出业务语义
- 业务安全、兼容策略、接口版本治理

代码归属（当前）：

- `src/web/api/v1/quote.py`
- `src/web/api/v1/market.py`
- `src/web/queries/quote_query_service.py`
- `src/web/schemas/quote.py`
- `src/web/auth/*`（与 Ops 共用）

禁止行为：

- 直接触发重型同步任务
- 直接依赖 `src/services/sync/*` 与 `src/operations/runtime/*`

---

## 4. 强制边界规则（必须遵守）

## 4.1 数据库边界

- Foundation 可变更：`raw/core/dm`
- Ops 可变更：`ops`
- Biz 可变更：`app` 与业务接口层，不直接写入 `raw/core/ops`

跨 schema 改动必须评审：

- 涉及 `core` 字段语义变化，需 Foundation + 消费方双签
- 涉及 `ops` 执行语义变化，需 Ops + Biz 双签

## 4.2 代码依赖边界

允许：

- Ops/Biz 读取 Foundation 模型与数据
- Biz 读取 Ops 的只读状态（必要时）

禁止：

- Biz import `src/services/sync/*`
- Biz import `src/operations/runtime/*`
- Foundation import `src/web/*`（测试桩除外）

## 4.3 API 边界

- Ops 内部接口固定在 `/api/v1/ops/*`
- Biz 对外接口固定在 `/api/v1/quote/*`、`/api/v1/market/*`
- 不允许将内部控制语义直接暴露为 Biz API 参数

## 4.4 文案边界

- Biz/用户界面禁止暴露内部实现字符串（如 `spec_key`, `execution_id`）
- 内部语义仅出现在日志、诊断页或调试接口中

---

## 5. 工程层治理落地（v1）

## 5.1 目录治理（在现有结构上最小改动）

短期不强制大搬家，先按“归属清单 + 审批规则”治理。

建议新增目录约定文档：

- `docs/subsystems-architecture-governance-v1.md`（本文）
- 后续可补 `docs/code-ownership-map-v1.md`

## 5.2 代码所有权

建议新增 `CODEOWNERS`：

- Foundation 路径由 Foundation 团队审批
- Ops 路径由 Ops 团队审批
- Biz 路径由 Biz 团队审批
- 跨域文件（如 `src/web/auth/*`、`src/config/*`）要求至少两方审批

## 5.3 CI 分轨

建议至少四条流水线：

1. `foundation-ci`：DAO/同步/模型/数据变换测试
2. `ops-ci`：运维服务与 API 测试
3. `biz-ci`：业务接口测试（含 `tests/web/test_quote_api.py`）
4. `contract-ci`：对外接口兼容检查（字段/错误码）

## 5.4 发版分级

- Foundation 变更：必须跑 Foundation + Ops + Biz 关键回归
- Ops 变更：必须跑 Ops + Biz 关键回归
- Biz 变更：必须跑 Biz + 平台健康回归

参考执行：`scripts/release-preflight.sh`

---

## 6. 团队协作协议

## 6.1 变更类型

- `Foundation-only`：不改对外接口契约
- `Ops-contract`：改内部控制契约
- `Biz-contract`：改对外业务契约
- `Cross-system`：跨系统改动，必须设计评审

## 6.2 契约变更规则

- 新增字段：允许，默认向后兼容
- 修改字段语义：必须先废弃再替换
- 删除字段：至少一个发布周期的 deprecate 窗口
- 错误码：稳定可枚举，不可随意替换

---

## 7. 近期行动项（两周内）

1. 落 `CODEOWNERS`（强制跨团队审批）
2. 在 CI 加入分轨任务（至少 Biz/Health/Quote）
3. 增加 import 边界检查（禁止 Biz 直接依赖 sync/runtime）
4. 将 Biz 新接口全部纳入发布验收清单

---

## 8. 回答“代码架构是否清晰”

结论：

- **方向清晰**：三子系统边界在概念上已经成立。
- **治理不足**：边界尚未通过工程手段强制，存在随迭代变模糊的风险。
- **可行路径**：在不大规模重构目录的前提下，通过“边界规则 + 所有权 + CI + 契约治理”即可实现三团队低冲突并行开发。

