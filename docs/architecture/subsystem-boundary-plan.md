# 子系统架构基线

更新时间：2026-09-08。合并目录职责、依赖矩阵及 Platform/Ops 收尾结论；不改变架构约束，不实施代码迁移。

## 1. 范围与阅读方式

本文是后端主体分层与 QTF 依赖边界的统一入口。目录归属、目标依赖与当前差距分开说明；目录已形成或护栏通过，都不代表全部架构目标已实现。

Foundation 数据分层与研发原则见 [Foundation 研发基线](/Users/congming/github/goldenshare/docs/architecture/foundation-current-standards.md)，Ops 状态与接口语义见 [Ops 当前契约](/Users/congming/github/goldenshare/docs/ops/ops-contract-current.md)。具体产品域仍须阅读其目录规则。

## 2. 目录与职责

| 位置 | 负责 | 不负责 |
| --- | --- | --- |
| `src/foundation/` | 数据源接入、同步、存储、基础 DAO/模型、kernel/contracts 与底层通用能力 | 运维/业务 API、应用装配 |
| `src/ops/` | runtime 调度与执行编排，运维 API/query/schema/service/model，任务与 freshness 观测 | 对上业务语义、应用壳装配 |
| `src/biz/` | 业务 API、查询、聚合服务与业务 schema | 调度治理、应用装配 |
| `src/app/` | Web 创建与运行、路由聚合、认证与依赖注入、异常处理、模型/schema 接线 | Biz/Ops 核心规则、Foundation 同步规则 |
| `qtf/` | 量化研究、计算、验证与发布产品域，由 App 装配 | 其他子系统的共享实现来源 |

`foundation / ops / biz` 是三个业务子系统，`app` 是组合根，不是业务子系统；根目录的 QTF 不属于 `src` 四层。

辅助目录与入口：

- `src/cli.py`、`src/cli_parts/`：CLI 入口及拆分实现；注册入口为 `goldenshare = src.cli:app`。
- `src/app/web/`：Web 主入口；`goldenshare-web = src.app.web.run:main`，systemd 参考 `scripts/goldenshare-web.service` 使用 `python -m src.app.web.run`。
- `src/scripts/`：Python 工具入口；与根目录 `scripts/` 的部署、发版、自检工具不同，两者都不新增业务分层。
- `src/shared/`：仅包说明骨架，不能据此认定已有共享主实现。
- `src/platform/`、`src/operations/`：legacy 说明目录，状态与禁令见第 5 节。

## 3. 目标依赖方向

下表只列仓库内子系统依赖，不是第三方依赖清单。

| 来源 | 允许依赖 |
| --- | --- |
| Foundation | Foundation 自身 |
| Ops | Foundation、Ops 自身 |
| Biz | Foundation、Biz 自身 |
| QTF | Foundation、QTF 自身 |
| App | Foundation、Ops、Biz、QTF、App 自身 |

因此 Foundation 不得依赖上层；Ops 不得依赖 Biz，Biz 不得依赖 Ops/Operations；各下层不得反向依赖 QTF。QTF 不得依赖除 `src.foundation` 外的其他 `src` 模块。旧 Operations 不得依赖 Biz，也不得恢复实现。

测试可以覆盖现行模块，但仍须遵守 legacy 导入禁令和隔离/执行规则，不能以测试为由恢复旧包。未来若确需依赖例外，须经批准，按“单文件、原因、允许模块、清理计划”登记，不能静默放宽矩阵。

## 4. 当前差距与测试覆盖

2026-09-08 核对：

- [依赖护栏配置](/Users/congming/github/goldenshare/tests/architecture/test_subsystem_dependency_matrix.py)的白名单为空；旧 `all_models.py`、Sync V1 `base_sync_service.py` 白名单不再适用。
- QTF 的单向依赖已纳入护栏；Platform/Operations 另有防回流测试。
- **App 不被下层反向依赖仍是目标，但尚未全部实现。** [Ops dataset cards API](/Users/congming/github/goldenshare/src/ops/api/dataset_cards.py)与 [Biz market API](/Users/congming/github/goldenshare/src/biz/api/market.py)等入口仍导入 App 的认证、数据库依赖等能力。
- 当前配置对 Ops 禁止 `biz/qtf`，对 Biz 禁止 `ops/operations/qtf`，未禁止二者导入 App。“零白名单”不等于测试覆盖全部目标，也不能作为新增反向依赖的理由。

这些差距不因文档合并而变成允许模式。是否迁移、如何迁移需另行设计与批准，本轮不改代码。

## 5. 已完成的迁移与 legacy 边界

原 Platform 拆分与 Ops 收敛文档的有效结论归入本节，旧全文通过 Git 历史追溯。

- Platform 的应用壳、认证、账户模型、通用 schema、聚合 API、Web 入口分别归入 `src/app/` 及其 `auth/models/schemas/api/web`；静态资源主路径为 `src/app/web/static`。旧市场快照试点业务线已退出，不作为新业务基线。
- 运维主实现归入 `src/ops/runtime/`、`src/ops/services/`；动作目录与工作流定义归入 `src/ops/action_catalog.py`。数据维护主链为 `DatasetDefinition -> DatasetExecutionPlan -> IngestionExecutor`，通过 Ops TaskRun 编排与观测。
- 市场情绪 walk-forward 业务服务归入 `src/biz/services/market_mood_walkforward_validation_service.py`，不回流 Ops。
- `src/platform` 只保留规则说明；`src/operations` 只保留根目录及 `services/` 的 AGENTS。两者均无 Python 源文件，包括 `__init__.py`；禁止恢复包、主实现或旧路径导入。
- 新运维能力进入 Ops；现行 facade 只做薄转发，不隐藏业务规则，也不作为恢复旧兼容层的理由。

“是否删除 legacy 空包”已不是待办。保留说明文档和防回退护栏；本次文档整合不授权删除目录、物理数据或 ignored 环境。历史迁移记录不代表对仓库外脚本兼容性的保证。

## 6. 变更与验证

边界归属不清时先明确判定，再改代码。按[根 AGENTS](/Users/congming/github/goldenshare/AGENTS.md)执行影响面审计、单目标推进、兼容层引用核验、最小回归及文档同步，不在多份文档重复维护执行流程。

<a id="architecture-guardrails"></a>

### 架构护栏

1. `tests/architecture/test_subsystem_dependency_matrix.py`：已配置的依赖方向、白名单与 QTF 规则。
2. `tests/architecture/test_platform_legacy_guardrails.py`：旧导入、Python 文件及静态资源路径防回退。
3. `tests/architecture/test_operations_legacy_guardrails.py`：旧包、旧服务/runtime/specs/status projection 路径防回退。

涉及目录边界代码变更时，至少运行以上三项；涉及数据维护主链再补 `test_dataset_runtime_registry_guardrails.py` 与 `test_dataset_codebook_guardrails.py`（均在 `tests/architecture/`）。使用现有环境，先确认测试无正式资源副作用，不自动安装依赖。

纯文档修改运行文档完整性、差异及引用检查即可；代码与获准运行验证按 [Foundation 研发基线 §7](/Users/congming/github/goldenshare/docs/architecture/foundation-current-standards.md#7-按改动类型选择验收)区分。`bash scripts/deploy-systemd.sh --help` 只证明帮助入口可用，不代表构建、迁移或部署成功，也不是文档检查必跑项。
