# 财势量化平台（QTF）首版低层设计 v1

## 0. 文档状态

| 项目 | 当前结论 |
|---|---|
| 文档性质 | 代码级 LLD 与内嵌编码门禁矩阵 |
| 当前状态 | M1 开发已收口，生产迁移待部署；下一步只可进入 M2 |
| 审计日期 | 2026-08-22 |
| 目标产品 | 财势乾坤 / 财势探查 / 量化研究工作台 |
| 首个垂直切片 | 东财二级行业统一参数研究 |
| 本文是否批准 R2 回测 | 否。R2 仍处于事前计划待评审状态 |
| 本文是否授权生产写入或发布 | 否 |
| 当前 Alembic head | M1 实施前重新确认仓库单一 head 为 `20260822_000142`；M1 迁移已接为 `20260822_000143`。本轮未连接或修改 Prod，生产部署仍须核对远端 head |

本文把已经确认的 QTF 系统架构、当前 Figma 六个正式页面、东财行业量化研究口径和仓库真实代码接入点落成可编码设计。本文不代表 QTF 已实现，也不把 Figma 中的示例数值解释为真实研究结果。

### 0.1 依据与优先级

1. 用户已经确认的 QTF 产品与架构口径。
2. [财势量化平台首版系统架构方案 v1](./qtf-quant-platform-architecture-v1.html)。
3. Figma `Goldenshare Web`：
   - `12 QTF Quant Platform - First Flow`，页面节点 `774:52`；
   - `12.5 QTF Quant Platform - Components`，页面节点 `774:53`。
4. [东财行业板块雷达量化因子与回测设计 v1](../../wealth/docs/pages/wealth-exploration/sector-radar-quant-factor-backtest-design-v1.md)。
5. [板块雷达数据覆盖审计 v1](../../wealth/docs/pages/wealth-exploration/sector-radar-data-coverage-audit-v1.md)。
6. 当前仓库代码、测试、包配置、迁移链与 Design System。

冲突处理顺序：用户最新拍板 > 当前代码事实与本 LLD 记录的接入约束 > QTF 架构方案 > Figma 示例文案。Figma 负责视觉和用户流程，不负责批准某次真实回测的参数与数据范围。

### 0.2 本次只完成什么

1. 冻结 QTF 顶层包、依赖方向、数据库模型、API、TaskRun 接入、前端路由和状态机。
2. 冻结首个二级行业研究能力在平台中的接口边界。
3. 列出 Figma 与当前代码尚未闭合的点，形成实施前门禁。
4. 给出文件级改动面、正反例测试和开发顺序。

本次不修改业务代码、数据库、Figma 或生产数据，不执行 R2，不生成候选参数，不发布任何行情信号。

---

## 1. 开发硬约束

| 编号 | 硬约束 | 实现含义 |
|---|---|---|
| C01 | `qtf/` 是仓库根目录新的正式产品域 | 不把主实现塞入 `src/biz`、`src/ops` 或 `scripts/research` |
| C02 | QTF 上游只读 Prod 或正式 Lake | 首个切片只读 Prod；不写来源表 |
| C03 | QTF 不清洗、不修复、不回填上游 | 单次 Run 输入门禁不合格即 BLOCKED，并指出由 Prod 或 Lake 修复 |
| C04 | 不保存输入快照、缓存或副本 | 只保存平台业务状态、单次 Run 输入门禁证据、内容指纹和派生结果 |
| C05 | 每个新 Run 重新直读并完整计算 | 不自动复用历史 Run 结果；同一 Run 内允许候选共享一次内存读取 |
| C06 | 公式和参数受控、完整、可版本化 | 公式由代码注册；网页不能提交或执行任意 Python；冻结时保存所有生效值 |
| C07 | 研究状态与执行状态分开 | TaskRun success 不等于研究 VALID；VALID 也不等于必须提名或发布 |
| C08 | QTF 与 Ops 事务隔离 | QTF 业务产物提交不能被 TaskRun 观测写入失败回滚 |
| C09 | 不新增角色、权限键、数据库账号 | 全部 QTF API 复用现有 `require_admin` |
| C10 | 候选、审核、批准、发布是四个动作 | 即使同一管理员执行，也要分别记录，不允许一步自动发布 |
| C11 | 不自动扩参或 Hyperopt | 只执行冻结、获批、带预算的有限参数矩阵 |
| C12 | 同一研究类别使用统一参数 | 首轮不按父行业或单个二级行业配置专属参数 |
| C13 | 交易日、时间前沿和未来标签严格分开 | 因子最多看到 `t`，标签从 `t+1` 开始；窗口使用交易日 |
| C14 | 用户页面只读 QTF 业务 API | `wealth` 不调用 `/ops/task-runs`、数据库或实验文件 |
| C15 | 发布产物与研究产物分开 | `src/biz` 只消费稳定 serving，不读取 QTF 实验表 |
| C16 | 单次规模按能力逐案批准 | 平台不设置一个虚假的全局“最大回测量”；每个冻结计划必须给出自己的预算 |
| C17 | R2 尚未获批 | Figma 的 128 个对象、8 组参数和结果百分比都是交互示例，不得触发真实读取或运行 |
| C18 | 申万研究暂缓 | 首个切片不得加入申万、跨体系映射或相关性 |
| C19 | 既有来源与覆盖审计直接复用 | M1、M2 不读取 Prod、不重复盘点数据源；只有来源或字段契约变化时才另立数据审计，正常 Run 只做精确范围输入门禁 |

---

## 2. 当前代码与设计审计

### 2.1 后端现状

| 位置 | 当前事实 | 对 QTF 的影响 |
|---|---|---|
| 仓库根目录 | 当前不存在正式 `qtf/` 包；`src/**`、`wealth/**` 也没有 QTF 实现 | 当前仍是目标设计，任何 Figma loaded 内容都不能表述成已开发 |
| `pyproject.toml` | `[tool.setuptools] packages = ["src"]` | 根目录 `qtf/` 目前不会作为正式包发布；M1 开工第一步必须修改包发现并做安装验证 |
| `docs/architecture/dependency-matrix.md` | 只定义 `foundation / ops / biz / app` | M1 开工第一步必须加入 QTF；禁止靠口头约定维持边界 |
| `tests/architecture/test_subsystem_dependency_matrix.py` | 只扫描现有四类规则 | M1 开工第一步必须增加 QTF 和“现有子系统不得反向导入 QTF”的自动护栏 |
| `src/app/model_registry.py` | 只注册 Foundation、App、Ops 模型 | QTF ORM 必须由 App 组合根显式注册，不能让 Foundation 反向导入 QTF |
| `alembic/env.py` | 调用 `register_all_models()`，使用共享 `Base.metadata` | QTF ORM 可继承共享 `Base`，由 App 注册后进入现有 Alembic 链 |
| `src/app/api/v1/router.py` | 聚合 Auth、Ops、Biz 路由 | QTF FastAPI 接线应在这里完成；QTF 核心不得导入 App |
| `src/ops/services/task_run_service.py` | 只允许 `dataset_action / workflow / maintenance_action` | 不能直接创建 `qtf_experiment`，需要通用、注入式扩展点 |
| `src/ops/runtime/task_run_dispatcher.py` | 只派发三类现有任务 | 需要通用外部任务执行器合同；Ops 不得导入 `qtf` |
| `src/ops/runtime/worker_lane.py` | GENERAL 车道当前会接纳所有非分钟任务 | 技术方案要求 QTF 与 Web、通用任务进程隔离；必须新增 QTF 专用 lane，并让 GENERAL 明确排除 `qtf_experiment` |
| `src/app/runtime/ops_worker_factory.py` | App 已负责向 Ops 注入 Heat executor | QTF executor 同样由 App 装配，但不得伪装成 maintenance action |
| `src/ops/models/ops/task_run*.py` | 已有任务、节点、问题、取消和进度事实 | 继续复用；不在 QTF 再建一套执行状态表 |
| `src/db.py` | 单一 `DATABASE_URL`、engine、session factory | QTF 复用当前连接，不新增数据库或专用账号 |

当前书面架构要求 Ops 只依赖 Foundation，但现有 `src/ops/**` 仍有多处导入 `src.app`，而当前自动依赖测试没有禁止这类导入。这是既有架构债务，不在 QTF 首版中顺手重构。QTF 首次实现只增加新边界，且不得新增任何 `src.ops -> qtf`、`qtf -> src.app|src.ops|src.biz` 依赖。

TaskRun 共享契约的现有消费者不只有 Web API：`manual_action_service`、`operations_schedule_service`、`operations_probe_runtime_service`、`index_daily_completeness_repair_service` 和相关测试都会直接构造 `TaskRunCommandService`；worker、CLI 与测试也会直接构造 `TaskRunDispatcher`。因此新增外部任务 registry 必须是可选注入，未注入时保持现有三类任务的行为和错误语义不变，不能把 QTF 注册成全局默认能力。

### 2.2 现有研究代码现状

当前本地存在：

```text
scripts/research/sector_radar_backtest.py
scripts/research/sector_radar_signal_grid.py
scripts/research/sector_radar_robustness.py
tests/test_sector_radar_backtest.py
tests/test_sector_radar_robustness.py
```

它们已经在一级行业探索中执行过 60/120 日候选计算，并以单元测试覆盖部分计算语义；这不等于算法预测有效，也不能证明同一公式适用于二级行业：

1. 脚本含固定实验 ID、固定一级行业对象数和固定候选常量。
2. 输出以本地文件为主，没有 Research、Revision、Run Input Preflight、Run、Candidate、Release 状态。
3. 没有 TaskRun、管理员 API、数据库元数据或 Wealth 页面接入。
4. R2 所需父级内比较、小同组门禁和二级行业计划尚未实现。

实施时不得由 `qtf` import `scripts.research.*`。M2 迁移的是“已在历史探索中使用过的候选公式实现”，并重新用正反例验证公式、窗口、缺失值和时间前沿语义；预测有效性只能由后续获批的 R2 回测判断。历史脚本保留为探索证据，不能被改名后冒充平台内核或正式参数。

### 2.3 前端现状

1. `WealthRouter` 是自有 History API 路由，不使用 React Router。
2. 当前正式路径只有市场总览、股票详情、指数详情和 `/wealth/exploration`。
3. `WealthExplorationPage` 已复用 `TopMarketBar`、`PageBreadcrumb`、公共市场时间上下文和主要指数 ticker。
4. 页面当前只装配成交额洞察，另有空的 `data-module-slot="sector-radar"`；没有 QTF 路由、页面或 API client。
5. 认证存储能携带 token，但当前前端路由不做管理员权限判断；最终权限仍必须由后端 `require_admin` 决定。
6. Wealth 的正式数据流是 `API DTO -> feature adapter -> view model -> component`，页面不得拼装研究事实。
7. 当前 Design System 事实源为 `wealth/src/styles/design-tokens.css`；数字样式 `.num` 位于 `wealth/src/styles/global.css`。`TopMarketBar` 和 `PageBreadcrumb` 与 Figma 合同一致，可直接复用。
8. 现有 `DataStatusBadge` 只有 `ready/delayed`，不能表达 QTF 的五种系统 tone；现有 `SkeletonBlock` 带固定 `loading` 文案。它们不能被强行复用成 QTF 组件，也不能为了 QTF 擅自扩大共享 contract。`Panel` 只在标题/meta DOM 与 Figma 一致时复用。
9. 现有 `wealthFetch` 已统一处理 access token、401 refresh 和重新登录通知；QTF client 必须复用它。403 由 QTF 页面转换为 forbidden 状态，不增加前端角色或权限判断。
10. `routerState.isWealthRoute()` 当前只把精确 `/wealth/exploration` 当成探查页。增加 QTF 子路由时必须同时扩展内部路由识别，否则从 QTF 页面导航时的返回语义会丢失。

### 2.4 Figma 正式页面映射

六个正式画板均为 `1600 × 1200`，根节点为纵向 Auto Layout，并复用当前 TopMarketBar 与页面 Shell。

| Figma 节点 | 页面 | 目标前端路由 |
|---|---|---|
| `778:52` | 研究总览 | `/wealth/exploration/quant` |
| `778:120` | 定义研究 | `/wealth/exploration/quant/researches/{researchKey}/edit` |
| `778:188` | 输入审计与冻结计划（Figma 当前名称；实际语义为单次输入检查） | `/wealth/exploration/quant/researches/{researchKey}/freeze` |
| `778:256` | 运行详情 | `/wealth/exploration/quant/runs/{runKey}` |
| `778:324` | 结果比较 | `/wealth/exploration/quant/runs/{runKey}/results` |
| `778:392` | 候选评审 | `/wealth/exploration/quant/candidates/{candidateKey}` |

正式组件页已经包含：

| 节点 | 组件 |
|---|---|
| `776:24` | `QTF / Workflow Step` |
| `776:35` | `QTF / Status Badge` |
| `776:54` | `QTF / Audit Check Row` |
| `776:71` | `QTF / Evidence Metric` |
| `776:100` | `QTF / Run Stage` |
| `833:13` | `QTF / Button` |
| `834:3524` | `QTF / Choice Chip` |
| `835:3538` | `QTF / Template Option` |
| `837:3576` | `QTF / Research List Row` |

开发交付属性已经按 Figma 节点树复核，不依赖截图猜测：

| 区域/组件 | Figma 真实属性 | 前端实现约束 |
|---|---|---|
| 六个 Desktop 根画板 | `1600×1200`，纵向 Auto Layout，Fixed/Fixed，2 个直属子节点 | 根只装 `TopMarketBar + PageShell`，不得加绝对定位补偿层 |
| TopMarketBar 实例 | `1600×56`，横向 Auto Layout，左右 padding 18，gap 12，横向 Fill | 直接复用现有组件，不复制视觉壳 |
| 六个 PageShell | `1600×1144`，纵向 Auto Layout，gap 12，padding `14 18 34 18` | 与 Header 正好组成 1200 高；页面内容宽固定 1564 |
| Breadcrumb | `1564×28`，横向 Auto Layout，gap 18；路径和 Meta 均 Hug | 复用现有 `PageBreadcrumb`，长文本不得挤压右侧 Meta |
| Content | `1564×1056`，纵向 Auto Layout，gap 12，横纵 Fill | 主区域按画板子区块高度实现，不用绝对坐标堆叠 |
| Workflow Step | 单实例 `220×64`，横向 Auto Layout，padding `10 12`，gap 12；3 个状态 | `Complete/Current/Upcoming` 显式 variant |
| Status Badge | 单实例 `92×28`，横向 Auto Layout，padding `6 10`；5 个 tone | `Neutral/Info/Success/Warning/Danger`，不得用行情涨跌色替代系统状态色 |
| Audit Check Row | 单实例 `520×52`，横向 Auto Layout，padding `8 12`，gap 12；3 个状态 | `Pass/Warning/Blocked` 共用列结构 |
| Evidence Metric | 单实例 `230×106`，纵向 Auto Layout，padding 14，gap 8；4 个 tone | 数值文本使用 tabular numbers |
| Run Stage | 单实例 `620×58`，横向 Auto Layout，padding `9 12`，gap 12；4 个状态 | `Done/Running/Pending/Failed` 共用骨架 |
| Button | 单实例 `110×30`，横向 Auto Layout，padding `8 12`；3 个 style | `Neutral/Brand/Danger` 必须是真实 button 组件 |
| Choice Chip | 单实例 `108×25`，横向 Auto Layout，padding `6 10` | `Selected=False/True`，不能只改文本颜色模拟选中 |
| Template Option | 单实例 `491×112`，纵向 Auto Layout，padding `14 16`，gap 7 | 两列模板项等宽，Selected 为组件状态 |
| Research List Row | 单实例 `948×78`，横向 Auto Layout，左右 padding 12，5 个直属列 | 表头和行复用同一列宽合同；状态、最后活动、操作不得各自定位 |

六页 Content 的正式区块顺序也已核对：研究总览为 `Page Header / Overview Summary / Overview Main`；定义研究和冻结计划为 `Page Header / Workflow / Main / Actions`；运行详情增加 `Run Summary`；结果比较增加 `Trust Gates / Result Metrics`；候选评审使用 `Release Workflow / Candidate Main / Actions`。前端 DOM 顺序必须与此一致，只有图表绘图区内部才允许绝对定位。

| 页面 | Content 子区块固定高度，按顺序 |
|---|---|
| 研究总览 | `76 / 106 / 842` |
| 定义研究 | `70 / 88 / 808 / 54` |
| 冻结计划 | `70 / 88 / 808 / 54` |
| 运行详情 | `70 / 88 / 100 / 696 / 54` |
| 结果比较 | `70 / 88 / 92 / 106 / 586 / 54` |
| 候选评审 | `70 / 88 / 808 / 54` |

主区两列均使用 12px gap，宽度合同为：总览 `980/572`、定义研究 `1030/522`、冻结计划 `820/732`、运行详情 `940/612`、结果比较 `1000/552`、候选评审 `980/572`。Research List 外容器为 `980×842`、padding 16；内部正式行宽 `948`，五列依次为 `360/190/110/150/110`，行左右 padding 12。表头必须复用这组列宽，不能再单独写一组 grid template。

### 2.5 Figma 尚未闭合的交付门禁

这些不是后端可以自行猜测的视觉问题：

| 编号 | 缺口 | 严重程度 | 处理门禁 |
|---|---|---:|---|
| F01 | 研究总览的“公式与参数”按钮没有目标页面 | 中 | M2 建 registry，M6 可提供只读 API；对应前端页面必须等 Figma 补齐后开发 |
| F02 | “保存草稿、返回修改、取消运行、拒绝候选、确认审核”没有原型目标 | 低 | 本 LLD 冻结其业务动作；若需要弹窗或新页面，M7 前补 Figma，不在代码中自由设计 |
| F03 | Figma 没有展示冻结输入日期范围、父级最小可比组阈值和完整 PLAN 预算 | 高 | 冻结页进入开发前必须把这些字段补入设计，不能隐藏成后端默认值 |
| F04 | 候选页声明“批准版本”和“发布生效”是独立动作，但没有对应按钮、状态或页面 | 高 | M8 前必须补齐 Figma；确认审核不能代替批准或发布 |
| F05 | 当前 `/wealth/exploration` 没有进入量化研究工作台的正式入口设计 | 中 | QTF 深链路可先开发；M7 页面验收前必须补入口或明确固定入口位置 |
| F06 | 六个画板只有 loaded 示例，没有 loading、empty、error、forbidden、conflict 状态稿 | 中 | API 和组件状态可先实现；最终视觉验收前必须补稳定骨架状态 |

Figma 中 `W=5/10/20/30`、`B=60/120`、128 个二级行业、8 个组合及所有百分比均是交互示例。它们只说明页面需要承载哪些信息，不构成 R2 读取或执行批准。

---

## 3. 目标依赖与组合方式

### 3.1 允许依赖

```text
qtf -> qtf, src.foundation
src.app -> qtf, src.foundation, src.ops, src.biz, src.app
wealth -> /api/v1/qtf, /api/v1/wealth
src.biz -> src.foundation, src.biz
src.ops -> src.foundation, src.ops
src.foundation -> src.foundation
```

### 3.2 明确禁止

```text
qtf -X-> src.ops | src.biz | src.app | src.platform | src.operations
src.foundation -X-> qtf
src.ops -X-> qtf
src.biz -X-> qtf
wealth -X-> /api/v1/ops/* | PostgreSQL | 本地研究文件
```

QTF 需要任务能力时，定义自身的 `RunObserver` 端口；App 用 Ops TaskRun 实现该端口。Ops 只看通用任务合同，不知道“行业热度、公式、参数、VALID、候选”是什么。

### 3.3 包发现

M1 开工第一步把固定 `packages = ["src"]` 改为受控包发现：

```toml
[tool.setuptools.packages.find]
where = ["."]
include = ["src", "src.*", "qtf", "qtf.*"]
exclude = ["tests", "tests.*", "scripts", "scripts.*", "wealth", "wealth.*", "frontend", "frontend.*", "lake_console", "lake_console.*"]
```

必须用构建后的 wheel 内容测试证明只包含 `src*` 与 `qtf*`，不能只验证源码目录下能 import。

---

## 4. 目标目录与文件级落点

### 4.1 新增 QTF 产品域

```text
qtf/
  AGENTS.md
  __init__.py
  contracts/
    errors.py
    formula.py
    parameters.py
    research.py
    runtime.py
  engine/
    robust_stats.py
    canonical_hash.py
    ranking.py
    time_frontier.py
  modules/
    sector/
      templates.py
      parameter_schema.py
      input_contract.py
      input_preflight.py
      input_reader.py
      factor_kernel.py
      signal_engine.py
      evaluator.py
      validator.py
      executor.py
  application/
    ports/
      input_source.py
      run_observer.py
      repositories.py
    services/
      overview_service.py
      research_service.py
      input_preflight_service.py
      experiment_service.py
      run_query_service.py
      candidate_service.py
      release_service.py
  adapters/
    prod/
      sector_source_adapter.py
    persistence/
      models/
      repositories/
  api/
    schemas/
      common.py
      overview.py
      research.py
      run.py
      candidate.py
      release.py
  tests/
```

职责：

1. `contracts` 只放跨能力稳定合同，不放 FastAPI、SQLAlchemy Session 或 React 语义。
2. `engine` 只放无 IO 纯算法。
3. `modules/sector` 承载首个行业研究能力，不把行业字段污染成平台通用字段。
4. `application` 组织用例并依赖端口。
5. `adapters/prod` 直接只读当前 Prod serving；不生成输入文件。
6. `adapters/persistence` 只保存 QTF 元数据与派生结果。
7. `api/schemas` 冻结 QTF 业务 DTO；FastAPI 的认证、Session 和路由装配放在 App。

### 4.2 现有后端改动点

| 文件 | 目标改动 |
|---|---|
| `pyproject.toml` | 发现 `src*` 与 `qtf*` |
| `docs/architecture/dependency-matrix.md` | 增加 QTF 依赖规则 |
| 根 `AGENTS.md`、`src/AGENTS.md` | 增加 QTF 目录责任和禁止回流规则 |
| `tests/architecture/test_subsystem_dependency_matrix.py` | 扫描 QTF，并禁止现有三个业务子系统反向导入 QTF |
| `src/app/model_registry.py` | 由 App 注册 QTF ORM |
| `alembic/versions/<new>_add_qtf_<milestone_scope>.py` | 按里程碑拆分迁移：M1 只创建 `qtf` schema 与 Research/Revision，M3 增加 preflight/Run，M4 增加结果证据，M8 增加 candidate/release；每次实施日连接真实 head |
| `src/ops/contracts/external_task.py` | 定义通用外部任务 definition/executor 合同 |
| `src/ops/services/task_run_service.py` | 通过注入 definition 校验外部任务；默认 Ops API 仍不接受 QTF |
| `src/ops/runtime/task_run_dispatcher.py` | 通过注入 executor 派发外部任务；不 import QTF |
| `src/ops/runtime/worker_lane.py` | 增加 `QTF` lane；QTF 只领取 `qtf_experiment`，GENERAL 明确排除它 |
| `src/ops/services/task_run_progress_service.py` | 提供独立 session 的阶段、进度和问题写入接口 |
| `src/app/runtime/qtf_task_definition_adapter.py` | 把 QTF 冻结运行映射为 TaskRun 意图 |
| `src/app/runtime/qtf_task_executor.py` | 把 TaskRun 请求映射给 QTF executor，并提供进度/取消适配 |
| `src/app/runtime/ops_worker_factory.py` | 新增 `build_qtf_worker()`；只在 QTF worker 注入 QTF executor |
| `src/app/api/v1/qtf.py` | FastAPI、`require_admin`、Session 和 QTF facade 接线 |
| `src/app/api/v1/router.py` | include QTF router |
| `src/cli.py`、`src/cli_parts/ops_handlers.py` | 增加 `qtf-worker-run/serve`，复用现有 lane worker handler |
| `scripts/goldenshare-qtf-worker.service` | 新增独立常驻 QTF worker unit |
| `scripts/deploy-systemd.sh`、`scripts/deploy-layered-systemd.sh`、`scripts/goldenshare-deploy.sudoers` | 纳入 unit 同步、enable/restart/status 和最小 sudo 白名单 |

`qtf_experiment` 不是数据维护、工作流或系统维护动作，不得注册成 `maintenance_action`，也不得被 GENERAL worker 领取。

### 4.3 Wealth 前端落点

```text
wealth/src/
  app/routes/
    qtfRouteState.ts
  pages/quant-platform/
    QuantPlatformPage.tsx
    quant-platform-page.css
  features/quant-platform/
    api/
    model/
    shell/
    overview/
    research-editor/
    plan-freeze/
    run-detail/
    result-comparison/
    candidate-review/
    ui/
```

`WealthRouter.tsx` 必须在精确 `/wealth/exploration` 之前识别 QTF 子路由；`routerState.ts` 的 Wealth 内部路径判断必须覆盖 QTF 前缀。QTF API client 复用 `shared/api/wealthApiClient.ts`。只在 QTF feature 内实现 Figma 的 QTF 组件；除已经证明合同一致的 `TopMarketBar`、`PageBreadcrumb`、token、`.num` 和个别 Panel 外，不提前提升到 `shared/ui`。

---

## 5. 平台代码注册表

### 5.1 ResearchTemplate

模板是代码注册对象，不是任意表单：

```python
ResearchTemplate(
    template_key="sector_l2_turn_hot_v1",
    title="二级行业逐渐转热",
    capability_key="sector_heat_research",
    formula_key="sector_heat_research_v1",
    parameter_schema_key="sector_l2_heat_params_v1",
    input_contract_key="sector_l2_prod_input_v1",
    validation_contract_key="sector_l2_continuation_validation_v1",
    active=True,
)
```

首版只注册已经开发和测试的模板。新增一种研究不是在网页写自由公式，而是新增模板、能力实现、正反例测试和版本。

### 5.2 FormulaDefinition

每个公式定义至少包含：

```text
formula_key
formula_version
input_fields
output_fields
lookback_requirement
time_frontier
implementation_version
parameter_schema_key
```

公式版本和 git commit 一起写入 Run。网页只能查看、选择已激活版本，不允许上传源码或执行表达式。

### 5.3 ParameterSchema

参数 schema 必须定义类型、范围、枚举、是否允许成为候选维度、默认值和依赖校验。运行时禁止使用“代码默认值补齐冻结参数”；`effective_params_json` 必须包含全部最终值。

首个行业能力至少能表达：

```text
baseline_days
trend_days
amount_lookback_days
ewma_lambda
price_weight
amount_weight
z_clip
signal_threshold
reset_threshold
up_move_share_min
future_horizons
comparison_scope
minimum_group_size
ranking_rule
event_cluster_rule
```

Figma 目前只让用户选择 `baseline_days` 和 `trend_days`。其余值必须由获批计划明确展示为“固定参数”，不能悄悄来自函数默认值。R2 的这些固定值仍待事前计划批准。

---

## 6. 数据库低层设计

### 6.1 总体规则

1. 使用现有 PostgreSQL 的 `qtf` schema、现有 `DATABASE_URL` 和共享 `Base`。
2. 不创建数据库、登录账号、角色或专用连接配置。
3. QTF 表只保存 Research/Revision/Run 等平台业务状态、单次 Run 输入门禁证据、派生结果、评审和发布记录；这些不是来源数据元数据。
4. 不在 QTF 表中保存 `dc_daily`、hierarchy 或 Lake 原始行副本。
5. 用户 ID 只保存为审计字段，不对 App 用户表建立 ORM 依赖。
6. `task_run_id` 只作逻辑关联和唯一索引，不建立迫使 QTF 依赖 Ops 模型的 ORM 关系。
7. QTF ORM 继承 `src.foundation.models.base.Base`；这是允许的 QTF → Foundation 依赖。
8. QTF service/repository 不调用 `src.db` 创建连接；App 把现有 Session 或 session factory 注入 QTF，保证连接配置仍只有一个事实源。

### 6.2 `qtf.research`

| 字段 | 约束 | 含义 |
|---|---|---|
| `id` | bigint PK | 内部键 |
| `research_key` | varchar(96), unique | 稳定公开键 |
| `create_request_key` | varchar(96), unique | 创建命令幂等键 |
| `title` | varchar(160) | 用户研究标题 |
| `template_key` | varchar(96) | 受控模板 |
| `capability_key` | varchar(96) | 能力归属 |
| `status` | varchar(24) | `DRAFT/ACTIVE/ENDED` |
| `latest_revision_no` | int | 最新版本号 |
| `created_by_user_id` | bigint | 创建人 |
| `created_at/updated_at` | timestamptz | 时间 |

索引：`status, updated_at desc`，用于研究总览“最后活动”排序。

### 6.3 `qtf.experiment_revision`

| 字段 | 约束 | 含义 |
|---|---|---|
| `id` | bigint PK | 内部键 |
| `revision_key` | varchar(96), unique | 公开版本键 |
| `request_key` | varchar(96), unique | 创建/派生版本幂等键 |
| `research_id` | FK `qtf.research` | 所属研究 |
| `revision_no` | int | 同研究递增版本；`research_id + revision_no` unique |
| `parent_revision_id` | nullable FK self | 派生来源 |
| `status` | varchar(24) | `DRAFT/FROZEN/RETIRED` |
| `problem_statement` | text | 研究问题 |
| `success_definition_json` | json | 主目标、辅助结果 |
| `non_goals_json` | json | 明确不做 |
| `source_contract_json` | json | 数据集、字段、过滤、日期规则 |
| `universe_spec_json` | json | 对象池和层级版本 |
| `comparison_spec_json` | json | 父级内比较和小组规则 |
| `formula_key/version` | varchar | 公式身份 |
| `parameter_schema_key/version` | varchar | 参数合同身份 |
| `effective_params_json` | json | 完整固定值与候选值 |
| `validation_spec_json` | json | IS/OOS、成功定义、门禁 |
| `budget_json` | json | 本次获批扫描、组合、时间、内存和产物预算 |
| `draft_version` | int | 乐观并发控制 |
| `revision_hash` | char(64), unique | 冻结内容哈希 |
| `frozen_by_user_id/frozen_at` | nullable | 冻结记录 |
| `created_at/updated_at` | timestamptz | 时间 |

只有 DRAFT 可编辑。FROZEN 的 JSON、公式、参数、预算和哈希都不可修改；任何变更创建新 revision。

### 6.4 `qtf.input_preflight` 与 `qtf.input_preflight_issue`

这里的 preflight 只检查某个草稿或 Run 已批准的对象池与日期范围，不重新选择数据源，也不重新执行平台级历史覆盖审计。

`input_preflight`：

| 字段 | 含义 |
|---|---|
| `preflight_key` | 公开键 |
| `request_key` | 本次输入检查命令幂等键；unique |
| `revision_id` | 检查所依据的 revision；草稿预检可绑定 `draft_hash` |
| `phase` | `DRAFT_PREVIEW/RUN_PREFLIGHT` |
| `status` | `PASS/BLOCKED` |
| `source_kind` | 首版固定 `PROD` |
| `source_contract_hash` | 来源、字段、过滤合同哈希 |
| `as_of` | 输入检查完成时点 |
| `requested_start/end_date` | 申请范围 |
| `effective_start/end_date` | 实际有效交易日范围 |
| `dataset_evidence_json` | 每张表的字段、行数、日期、唯一键、缺失和内容指纹 |
| `universe_count/group_count` | 对象数和父级组数 |
| `valid_group_day_count` | 完整父级组日数量 |
| `excluded_group_day_count` | 被排除组日数量 |
| `plan_estimate_json` | 扫描行数、组合数、预估时间、内存和派生行数 |
| `content_hash` | 按稳定键顺序计算的输入内容指纹 |
| `completed_at` | 完成时间 |

`input_preflight_issue` 每条保存 `preflight_id / code / severity / dataset_key / trade_date / field_name / object_key / message / remediation_owner / evidence_json`。`remediation_owner` 只能是 `PROD` 或 `LAKE`，不能写成 QTF 自修复。

输入门禁只保存计数、键、缺口和摘要样本，不保存来源原始行。

### 6.5 `qtf.experiment_run`

| 字段 | 含义 |
|---|---|
| `run_key` | 公开键 |
| `request_key` | 启动命令幂等键；unique |
| `revision_id` | 冻结 revision |
| `input_preflight_id` | 本 Run 的 `RUN_PREFLIGHT` 输入门禁记录 |
| `task_run_id` | Ops TaskRun ID，nullable unique |
| `status` | `PLANNED/QUEUED/EXECUTING/COMPLETED/FAILED/CANCELED/BLOCKED` |
| `validation_status` | `PENDING/VALID/INVALID/INSUFFICIENT/BLOCKED` |
| `code_commit` | 执行代码提交；worker 认领前 nullable，执行前必须补齐 |
| `runtime_fingerprint_json` | Python、QTF 包和关键计算依赖版本；不含主机 secret |
| `formula_version` | 实际公式版本 |
| `source_content_hash` | 本 Run 输入指纹 |
| `result_hash` | 派生结果指纹 |
| `completed_parameter_set_count` | 已完整落库的参数组合数 |
| `failure_code/failure_message` | 用户可读失败摘要 |
| `started_at/ended_at` | 时间 |

Run 不保存 TaskRun 的进度副本。QTF API 查询运行详情时，由 App 只读组合安全 TaskRun 视图。

### 6.6 结果与证据表

1. `qtf.run_gate_result`
   - 唯一键：`run_id + gate_key`。
   - `gate_key` 固定为 `INPUT/TIME_FRONTIER/FUTURE_LEAKAGE/WARMUP/COVERAGE/OUT_OF_SAMPLE_SENSITIVITY`；最后一项把样本外衰减、简单基线和邻近参数敏感性作为同一道门禁，与技术方案及 Figma 六格一致。
   - 保存 `status/summary/evidence_json/checked_at`。
2. `qtf.run_parameter_result`
   - 公开键为 `result_key`；唯一键：`run_id + parameter_set_key`。
   - 保存完整 `parameter_values_json`、主指标、基线值、Lift、覆盖率、样本量、置信区间、全部指标 JSON、结论和结果哈希。
3. `qtf.sector_signal_event`
   - 只保存实际触发的派生事件，不保存每日完整输入或完整因子矩阵。
   - 唯一键：`run_id + parameter_set_key + signal_trade_date + sector_code + entry_type`。
   - 保存层级、父级、信号状态、信号日排名、未来 1/3/5 日结果、输入完整性摘要和事件哈希。

首个二级行业能力使用 PostgreSQL 保存上述结构化结果，不新增 Parquet 产物。若获批 R2 PLAN 估算的事件结果超过该轮预算，必须停止并单独评审产物介质，不能自动切换到文件。

### 6.7 结论、候选和发布

1. `qtf.run_conclusion`
   - 每个完成 Run 最多一条当前结论；保存 unique `request_key`、`ENDED/OBSERVED/NOMINATED`、操作者、意见和时间。
2. `qtf.candidate`
   - 关联一个 VALID Run 和一个 `run_parameter_result`；只有提名后才生成真正的 Candidate。
   - 状态：`CANDIDATE/UNDER_REVIEW/REVIEWED/CHANGES_REQUESTED/APPROVED/REJECTED/PUBLISHED/RETIRED`。
   - 保存不可变公式、参数、适用范围、验证报告哈希和 candidate hash。
3. `qtf.candidate_action`
   - 追加写 `SUBMIT/CONFIRM_REVIEW/REQUEST_NEW_EXPERIMENT/APPROVE/REJECT/PUBLISH/RETIRE`。
   - 保存 unique `request_key`、前后状态、actor、意见、时间和 action hash。
4. `qtf.release`
   - 由 APPROVE 创建不可变 release 内容。
   - 保存 `release_key/candidate_id/formula_version/params_json/scope_json/effective_trade_date/supersedes_release_id/release_hash`。
   - 生命周期字段只允许由独立 publish/retire 动作更新；公式、参数、范围和 hash 不可改。

批准只创建可发布版本；发布必须另行执行并验证生产计算与 serving。首版平台框架不在没有专项生产 LLD 的情况下创建板块 serving 表。

### 6.8 Key、hash 与时间

1. `researchKey/revisionKey/preflightKey/runKey/resultKey/parameterSetKey/candidateKey/releaseKey/requestKey` 都是后端生成或校验的 opaque string；前端不得解析其前缀获得业务含义。
2. 所有 `*_hash` 使用 SHA-256 小写十六进制。JSON 先按 UTF-8、key 排序、无多余空白的 canonical 形式序列化；日期为 ISO `YYYY-MM-DD`，时间为带时区 ISO-8601，Decimal 转为不丢精度的十进制字符串。
3. 来源内容指纹按冻结字段、稳定业务键顺序流式更新 hash；不为计算 hash 保存完整输入副本。
4. `revision_hash` 覆盖问题、成功定义、非目标、来源、对象池、比较范围、公式、全部生效参数、验证合同和预算；任何一项变化都必须产生新 hash。
5. `result_hash` 覆盖运行指纹、门禁、候选摘要和 signal events；排序必须稳定，重算相同事实应得到相同 hash。
6. 数据库时间统一保存 UTC `timestamptz`；业务交易日单独使用 `date`。前端只格式化，不以浏览器时间生成研究日期。

---

## 7. 状态机与动作语义

### 7.1 研究版本

```text
DRAFT --freeze--> FROZEN
DRAFT --discard--> RETIRED
FROZEN --derive new revision--> new DRAFT
```

1. “保存草稿”只更新 DRAFT，并校验 `draftVersion`。
2. “返回修改”回到同一 DRAFT；FROZEN 不可返回后直接覆盖。
3. FROZEN 需要修改时创建下一 revision。

### 7.2 Run

```text
PLANNED -> QUEUED -> EXECUTING -> COMPLETED
                    |            |
                    |            +-> validation VALID / INVALID / INSUFFICIENT
                    +-> FAILED / CANCELED / BLOCKED
```

1. `BLOCKED`：输入或计划门禁不合格，未开始公式计算。
2. `FAILED`：程序或基础设施执行失败。
3. `CANCELED`：用户请求取消，并在当前参数组合安全点结束。
4. `COMPLETED + INVALID/INSUFFICIENT` 是合法研究结论，不改写成系统失败。
5. 只有 `COMPLETED + VALID` 才允许“提名候选”；仍可选择结束或观察。

### 7.3 TaskRun 对应关系

| QTF | TaskRun |
|---|---|
| `PLANNED` | 尚未创建或创建失败 |
| `QUEUED` | `queued` |
| `EXECUTING` | `running/canceling` |
| `COMPLETED` | `success` |
| `FAILED/BLOCKED` | `failed` |
| `CANCELED` | `canceled` |

TaskRun success 只表示执行完成。QTF `validation_status` 是研究可信度的唯一事实。

### 7.4 候选与发布

```text
CANDIDATE -> UNDER_REVIEW -> REVIEWED -> APPROVED -> PUBLISHED -> RETIRED
       |            |            |
       +----------> REJECTED     +-> CHANGES_REQUESTED -> new DRAFT revision
```

1. “确认审核”只到 REVIEWED。
2. “批准版本”只到 APPROVED，并生成 release 内容。
3. “发布生效”单独到 PUBLISHED。
4. 同一管理员可以依次操作，但每一步必须有独立 action row。
5. 新版本生产计算或校验失败时，旧 PUBLISHED release 保持生效。

---

## 8. QTF API 契约

### 8.1 通用规则

1. 前缀：`/api/v1/qtf`。
2. 全部接口使用 `require_admin`，不新增 QTF 权限。
3. DTO 使用 camelCase，`extra="forbid"`。
4. 写接口必须带当前对象版本或 hash，防止重复点击和旧页面覆盖。
5. POST 动作通过业务键幂等；同一动作重复提交返回当前结果，不重复创建 Run、候选或 release。
6. API 不返回 TaskRun 的 `technical_payload_json`、SQL、连接信息或内部堆栈。

里程碑开放顺序：M3 只开放二级行业垂直切片所需的 template、draft、preflight、freeze、run command 和 run detail；M4 增加 results/conclusion；M6 才补齐 overview、完整 registry、candidate 查询并收敛为工作台稳定合同。所有阶段调用同一 application service，不建设临时脚本 API。

### 8.2 总览和注册表

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/overview` | 卡片计数、下一决策、研究列表、当前 release |
| GET | `/templates` | 可用研究模板 |
| GET | `/formulas` | 已注册公式与版本，只读 |
| GET | `/parameter-schemas/{schemaKey}` | 参数字段、范围、依赖和展示说明 |

研究列表固定按 `updated_at desc, research_key asc`，不能由前端自行排序出“最后活动”。

### 8.3 草稿、单次输入预检和冻结

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/researches` | 从 template 创建 research 和 revision 1 DRAFT |
| GET | `/researches/{researchKey}` | 当前研究和版本摘要 |
| PUT | `/researches/{researchKey}/draft` | 保存 DRAFT；要求 `draftVersion` |
| POST | `/researches/{researchKey}/revisions` | 从已冻结版本或候选派生新 DRAFT |
| POST | `/researches/{researchKey}/input-preflights` | 复用既有来源合同，对当前 draft hash 的精确对象池和日期范围做有界 Prod 只读预检 |
| POST | `/researches/{researchKey}/freeze` | 绑定 PASS preflight、完整参数和批准的 PLAN hash，生成 FROZEN revision |

冻结请求至少包含：

```json
{
  "draftVersion": 4,
  "inputPreflightKey": "PREFLIGHT-QTF-...",
  "approvedPlanHash": "sha256:...",
  "acknowledgedExclusions": true
}
```

冻结服务必须重新计算 revision hash，并拒绝已变化的草稿、过期输入预检、缺少预算或不完整参数。

### 8.4 Run

| 方法 | 路径 | 作用 |
|---|---|---|
| POST | `/revisions/{revisionKey}/runs` | 从 FROZEN revision 创建新 Run；每次重读，不复用旧结果 |
| GET | `/runs/{runKey}` | QTF 状态 + 安全 TaskRun 进度视图 |
| POST | `/runs/{runKey}/cancel` | 请求在安全点取消 |
| GET | `/runs/{runKey}/results` | 门禁、候选比较、敏感性和失败样本 |
| POST | `/runs/{runKey}/conclusion` | `END/OBSERVE/NOMINATE` |

创建 Run 使用一个短暂的“执行意图事务”：

1. App 使用同一个现有数据库 session 创建 `PLANNED` QTF Run。
2. 在同一事务中调用已注入 QTF definition 的 TaskRun command service，创建 `task_type=qtf_experiment` 的 QUEUED TaskRun。
3. 回写 `task_run_id`，把 QTF Run 转为 `QUEUED`，然后一次提交。

任一步失败都整体回滚本次启动意图，不留下无 TaskRun 的 Run，也不留下可能被 worker 抢走的孤儿 TaskRun；FROZEN revision 保留，用户可以重新启动。这个原子事务只用于创建执行意图。worker 开始后，QTF 业务结果与 Ops 进度/终态必须继续使用不同 session 和事务，不能借此把运行期事务重新耦合。

运行视图只返回：业务阶段、组合进度、可取消性、最近用户可读进展、开始/结束时间和简化失败原因。技术详情仍留在 Ops 管理端。

### 8.5 候选和发布

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/candidates/{candidateKey}` | 候选、证据、评审清单和动作状态 |
| POST | `/candidates/{candidateKey}/review` | 确认审核 |
| POST | `/candidates/{candidateKey}/request-experiment` | 标记需新实验并派生 DRAFT |
| POST | `/candidates/{candidateKey}/reject` | 拒绝候选 |
| POST | `/candidates/{candidateKey}/approve` | 生成 APPROVED release |
| POST | `/releases/{releaseKey}/publish` | 独立发布 |
| GET | `/releases/current` | 当前生效 release |

`publish` 在 M8 前不得实现为空操作。没有生产计算、同核校验、serving 原子切换和回滚合同，就只能保留 APPROVED，不能返回 PUBLISHED。

### 8.6 六页读取 DTO

所有 DTO 返回业务事实和业务动作，不返回 CSS tone、TaskRun 原始字段或 Figma 示例值。以下字段是首版最小合同；Pydantic 模型不得以无约束 `dict[str, Any]` 代替这些顶层结构。

#### `OverviewResponse`

```text
asOf
summary { activeResearchCount, runningRunCount, pendingDecisionCount, currentReleaseCount }
nextDecision? { decisionType, title, summary, targetType, targetKey }
researches[] {
  researchKey, title, templateKey, templateTitle, researchStatus,
  latestRevisionNo, latestRunStatus?, validationStatus?, lastActivityAt,
  nextAction { action, targetType, targetKey, enabled, disabledReason? }
}
currentRelease? {
  releaseKey, title, formulaVersion, parameterSummary,
  effectiveTradeDate, consumers[], publishedAt
}
```

#### `ResearchEditorResponse`

```text
researchKey, revisionKey, revisionNo, draftVersion, revisionStatus
template { templateKey, title, description, formulaKey, parameterSchemaKey }
problemStatement
successDefinitions[] { key, label, selected }
nonGoals[] { key, label, selected, required }
scope {
  sourceKind, objectType, objectCount?, hierarchyVersion?, comparisonScope,
  candidateTrendDays[], candidateBaselineDays[], futureHorizons[],
  sharedParameterScope, runPolicy, dataResponsibility
}
canEdit, canPreflight, blockingReasons[]
```

对象数只来自最近一次输入预检；没有预检时为 null，不能使用 Figma 的 128。模板和参数 schema 分别来自代码 registry；草稿只保存用户选择及完整生效值。

#### `FreezePlanResponse`

```text
researchKey, revisionKey, draftVersion, draftHash
preflight {
  preflightKey, preflightStatus, sourceKind, asOf,
  requestedStartDate, requestedEndDate, effectiveStartDate, effectiveEndDate,
  universeCount, groupCount, validGroupDayCount, excludedGroupDayCount,
  datasetEvidence[], issues[], contentHash
}
plan {
  parameterMatrix[], fixedParameters[], futureHorizons[], comparisonScope,
  sampleSplit, primaryObjective, hardGates[], stopConditions[], budget, planHash
}
acknowledgements[] { key, label, required, acknowledged }
canFreeze, blockingReasons[]
```

`datasetEvidence` 至少包含 `datasetKey/fields/dateRange/rowCount/uniqueKeyStatus/missingCount/duplicateCount/contentHash`；issue 至少包含 `code/severity/datasetKey/tradeDate?/objectKey?/message/remediationOwner`。

#### `RunDetailResponse`

```text
runKey, researchKey, revisionKey, revisionNo, runStatus, validationStatus
formulaVersion, codeCommit?, sourceContentHash?, startedAt?, endedAt?
progress {
  percent?, completedParameterSetCount, totalParameterSetCount,
  currentStageKey?, currentParameterSet?, canCancel,
  observerStatus, latestUpdates[] { occurredAt, stageKey, message }
}
stages[] { stageKey, label, status, summary? }
frozenPlanSummary { objectCount, comparisonScope, candidateCount, sampleSplit, sourceKind }
failure? { code, message, retryable }
```

`observerStatus=DEGRADED` 只表示 TaskRun 观测异常；不能覆盖 QTF `runStatus/validationStatus`。percent 为空时展示不确定进度，不伪造百分比。

#### `RunResultsResponse`

```text
runKey, runStatus, validationStatus, resultHash?
gates[] { gateKey, status, summary, evidenceMetrics[] }
decisionSummary { conclusion, explanation, canNominate }
parameterResults[] {
  resultKey, parameterSetKey, displayOrder, parameterValues,
  sampleSize, coverageRate, primarySuccessRate,
  baselineSuccessRate, lift, confidenceInterval?,
  entryMetrics, retentionMetrics, diagnosticMetrics, resultStatus
}
sensitivity[]
failureSamples[]
allowedConclusions[]
```

`parameterResults[]` 是“可比较的参数组合结果”，不是已经提名的 Candidate。`displayOrder` 由后端在全部参数组合完成且门禁结论生成后给出；未完成 Run 不返回排名。`parameterValues` 的 key 必须属于冻结 schema，指标集合由首个 sector template 的显式 Pydantic 子模型承载。

#### `CandidateReviewResponse`

```text
candidateKey, candidateStatus, researchKey, revisionKey, runKey
formulaVersion, parameterValues, scope, validationReportHash, candidateHash
evidenceSummary, checklist[] { checkKey, status, label, evidence }
actionHistory[] { action, fromStatus, toStatus, actorDisplayName, comment?, occurredAt }
allowedActions[] { action, enabled, disabledReason? }
release? { releaseKey, releaseStatus, effectiveTradeDate?, publishedAt? }
```

Actor 只用于审计展示；接口不引入分析员/审核员等新角色。M8 设计闭合前，`allowedActions` 只可返回 `REJECT/REQUEST_NEW_EXPERIMENT/CONFIRM_REVIEW`，不能提前返回 APPROVE/PUBLISH。

### 8.7 写请求最小字段

1. 创建 Research：`requestKey/templateKey/title`。
2. 保存草稿：`draftVersion/problemStatement/successDefinitionKeys/nonGoalKeys/parameterSelections`。
3. 单次输入预检：`requestKey/draftVersion/requestedStartDate/requestedEndDate`。
4. 冻结：第 8.3 节字段外加 `requestKey`；相同 revision hash 重试返回已有 FROZEN revision。
5. 创建 Run：`requestKey/revisionHash`；App 必须调用 `stage_task_run()`，与 Run/link 一次 commit，不能调用会自行 commit 的 `create_task_run()`。
6. 取消、结论和所有候选动作：`requestKey/currentVersion/comment?`；`NOMINATE` 额外要求 `resultKey`；重复 requestKey 返回原结果。
7. publish 额外要求 `releaseHash/effectiveTradeDate`；M8 前路由不存在。

---

## 9. TaskRun 与 Worker 接入

### 9.1 通用 Ops 扩展合同

Ops 新增与业务无关的合同：

```python
ExternalTaskDefinition(
    task_type: str,
    validate_context: Callable,
    resolve_title: Callable,
)

ExternalTaskExecutor.execute(
    task_run_id: int,
    request_payload: Mapping[str, object],
) -> TaskRunDispatchOutcome
```

App 注入：

```text
task_type = qtf_experiment
resource_key = sector_heat_research
action = execute_backtest
request_payload = {runKey, revisionKey, revisionHash}
```

现有 `/api/v1/ops/task-runs` 使用未注入 QTF definition 的默认 command service，因此不能绕过 QTF API 手工拼任务。

### 9.2 独立 QTF worker lane

```text
WorkerLane.QTF
  accepts: task_type == "qtf_experiment"

WorkerLane.GENERAL
  rejects: task_type == "qtf_experiment"

WorkerLane.STK_MINS / INDEX_MINS
  keep current dataset-only rules
```

1. App 新增 `build_qtf_worker()`，仅向该 worker 的 dispatcher 注入 QTF executor。
2. `qtf-worker-run/serve` 复用现有 lane worker CLI handler，不复制轮询循环。
3. 生产以 `goldenshare-qtf-worker.service` 独立常驻；Web 进程只创建意图和查询，不执行回测。
4. GENERAL、股票分钟和指数分钟 worker 都不能领取 QTF TaskRun；QTF worker 也不能领取既有任务。
5. QTF worker 仍使用现有数据库连接和部署版本，不新增服务数据库、账号或消息队列。

### 9.3 QTF 执行阶段

1. `RUN_PREFLIGHT`：复用既有来源合同重新直读，并生成本 Run 的 input preflight；不做新的来源选型或全库覆盖审计。
2. `LOAD_INPUT`：一次性读取冻结字段和范围，形成只存在于进程内的不可变输入集合。
3. `RUN_PARAMETER_SETS`：按冻结顺序逐组合计算并单独提交完整参数结果。
4. `VALIDATE`：运行六道可信门禁。
5. `SUMMARIZE`：生成主要目标、基线、敏感性、失败样本和 result hash。
6. `FINALIZE`：更新 QTF Run 业务终态。

TaskRun 节点标题使用上述业务语言，不展示 DAO、SQL 或内部类名。

### 9.4 取消安全点

1. 参数组合开始前检查一次取消。
2. 当前组合计算并完整提交后再检查一次。
3. 不在一组结果写到一半时中止。
4. 已完成组合保留为运行证据，但 canceled Run 不允许提名候选。
5. queued Run 沿用现有 TaskRun 立即取消语义。

### 9.5 事务隔离

1. QTF executor 用 QTF business session 提交输入门禁记录、参数组合结果、可信门禁和 Run 状态。
2. App observer 用另一条 Ops session 写 TaskRun 进度、节点和问题。
3. Ops 进度写失败由 observer 捕获并降级为观测异常；不得 rollback 已提交的 QTF 结果。
4. Worker 最终 TaskRun 状态写失败时，QTF Run 仍保留真实终态；QTF API 显示“结果已生成，运行观测异常”。
5. QTF 业务写失败时，TaskRun 可以失败，但不得生成 VALID、候选或 release。

---

## 10. 首个二级行业能力

### 10.1 Prod 输入合同

| 表 | 读取字段 | 过滤与用途 |
|---|---|---|
| `core_serving.trade_calendar` | `exchange, trade_date, is_open, pretrade_date` | `exchange='SSE' AND is_open=true`；生成交易日序列 |
| `core_serving.wealth_sector_hierarchy` | `sector_code, sector_name, industry_level, parent_sector_code, root_sector_code, display_order, baseline_version, published_at` | 当前唯一发布版本，`industry_level=2`；生成对象池和父级组 |
| `core_serving.dc_daily` | `ts_code, trade_date, category, pct_change, amount` | `category='行业板块'`、冻结交易日范围、当前二级行业代码池 |

不读取 `dc_member`、资金流、新闻、宽基指数、申万或分钟数据。

来源选择、字段和历史覆盖直接复用 2026-08-16 的[板块雷达数据覆盖审计](../../wealth/docs/pages/wealth-exploration/sector-radar-data-coverage-audit-v1.md)：当时已确认当前行业层级共 496 个节点（一级 31、二级 128、三级 337），`dc_daily` 覆盖 634 个交易日，最近 250 个交易日的板块日行情与相关核心输入为 250/250。该结论同时保留一个已知限制：行业层级只有当前发布基线，没有历史版本。除非来源表、字段合同或层级发布机制发生变化，M1、M2 以及 R2 计划阶段不得再做一次同类 Prod 覆盖审计。

### 10.2 只读与查询要求

1. 草稿输入预检和每个 Run 都显式开启 read-only transaction。
2. 只选择上述字段，查询必须用交易日范围、category 和代码池下推。
3. 稳定排序为 `trade_date, ts_code`，用于内容指纹。
4. Run 内只读一次来源；8 个候选可以共享进程内输入，Run 结束即释放。
5. 新 Run 必须重新执行精确范围查询与输入门禁，不能加载旧 CSV、旧 JSON 或旧 Run 事件作为输入；这不是重新盘点数据源或重做全库覆盖审计。

### 10.3 单次研究输入门禁

以下检查只针对当前草稿或 Run 已批准的对象池、日期范围和来源合同。

范围级门禁：

1. 既有合同中的三张表在本次只读事务中可访问。
2. hierarchy 非空且只有一个 baseline version。
3. 二级节点的父级存在、层级为 1、root 闭包正确。
4. `dc_daily` 业务键 `trade_date + ts_code + category` 唯一。
5. `pct_change`、`amount` 对参与计算的行不为空；非法值不由 QTF 修复。
6. 日期必须来自 SSE 开放日；不补自然日。

能力门禁：

1. 每个父级的直属二级行业数和有效组日逐项统计。
2. 父级组日只有在该组全部冻结成员当日事实齐备时才有效。
3. 缺失只排除对应父级组日，不前向填充，不用其他父级数据补齐。
4. 小组是否可产生二元“上榜”由冻结 `minimum_group_size + ranking_rule` 决定；未获批前不得默认成前 20%。
5. 所有排除组日、原因、父级、缺少对象和来源表写入 preflight issue。

### 10.4 因子与时间语义

首版迁移现有一级行业探索中使用过的价格和成交候选公式。以下公式已具备历史实现和部分计算语义测试，但其预测有效性、二级行业适用性和最终参数均未验证：

```text
relativeReturn1d(i,t)
  = pctChange(i,t) - median(pctChange(siblings(parent(i)),t))

amountRatio20(i,t)
  = amount(i,t) / median(amount(i,t-20...t-1))

logAmountRatio20(i,t) = log(amountRatio20(i,t))

robustZ_B(x(i,t))
  = (x(i,t) - median(x(i,t-B...t-1)))
    / (1.4826 * MAD(x(i,t-B...t-1)))
```

1. 历史窗口不含 `t`。
2. `MAD=0`、历史不足、组日不完整时生成无效原因，不补分数。
3. 状态合成、EWMA、阈值、reset、事件簇规则均来自冻结参数。
4. 未来标签只使用 `t+1` 之后的交易日。
5. 未来成功不得用同一平滑 heat 序列自我证明，必须使用独立的未来父级内横向排名与客观价格/成交结果。

EWMA 的唯一公式合同为：

```text
heatState_B(i,t)
  = lambda * stateInput_B(i,t)
  + (1 - lambda) * heatState_B(i,t-1)
```

### 10.5 R2 仍需批准的内容

平台 schema 支持但本文不拍板：

1. 本次 Run 根据当前已发布层级解析出的二级行业对象数和父级组分布；这是 PLAN 运行范围，不是新的数据覆盖审计。
2. 实际研究起止日期、完整组日和排除规则结果。
3. `W` 是否一次执行 `5/10/20/30` 全部候选。
4. 信号阈值、reset、向上占比、lambda、权重和事件簇规则。
5. 小组最小规模与上榜规则。
6. IS/OOS 切分、主要成功定义和置信区间方法。
7. 扫描行数、组合数、预计耗时、峰值内存和事件产物预算。

M5 执行时，这些字段必须先由正式 QTF application service 生成可读 PLAN 报告和 canonical plan hash，由用户在任务中明确批准后，再通过同一管理员 API 冻结；不能直接调用研究脚本。M7 页面实现后，同一合同必须完整显示在冻结页并由用户点击确认，不能另造一套页面默认值。

---

## 11. Wealth 前端低层设计

### 11.1 路由解析

`qtfRouteState.ts` 只负责识别和生成 QTF 路径，不读取业务数据：

```ts
type QtfRoute =
  | { kind: "overview" }
  | { kind: "researchEdit"; researchKey: string }
  | { kind: "researchFreeze"; researchKey: string }
  | { kind: "runDetail"; runKey: string }
  | { kind: "runResults"; runKey: string }
  | { kind: "candidateReview"; candidateKey: string };
```

路径参数必须 `decodeURIComponent`，空值和多余段落不匹配。`WealthRouter` 在普通 `/wealth/exploration` 之前识别 QTF 子路由。

`isWealthRoute()` 同时把 `/wealth/exploration/quant` 及其合法子路由识别为 Wealth 内部页面，确保 `hasWealthReferrer`、浏览器返回和登录 redirect 保持现有语义；未知 QTF 子路径进入明确 not-found/error 状态，不得静默回退市场总览。

### 11.2 页面 Shell

`QuantPlatformPage` 负责：

1. 复用 `TopMarketBar`，activeNav 固定 `exploration`。
2. 复用 `PageBreadcrumb`，内容为 `财势乾坤 / 财势探查 / 当前步骤`。
3. 复用现有 market context 与主要指数 ticker 请求。
4. 按 QTF route 装配一个子页面。
5. 处理 401 登录跳转和 403 Forbidden 稳定骨架。

它不得聚合或重算参数结果、Lift、门禁或研究状态。

### 11.3 Feature 数据流

```text
qtfApi client -> strict response type -> adapter -> page view model -> QTF component
```

1. 后端直接返回业务状态和展示所需事实。
2. adapter 只做日期、百分比、数字和状态文案格式化。
3. 组件不从 TaskRun status 推断 VALID。
4. 结果表排序由 API 明确提供 `displayOrder`，前端不挑“冠军”。
5. 示例数据和 mock 不得进入 real API error fallback。
6. 所有请求经 `wealthFetch` 发出；401 沿用统一 refresh/登录流程，403 留在页面稳定骨架内显示 forbidden。

### 11.4 六页行为

#### 研究总览 `778:52`

1. 展示真实计数、下一决策、研究列表和当前 release。
2. “查看运行 / 阅读证据 / 继续编辑 / 查看结论”只使用 API 返回的目标 key 构造路由。
3. “新建研究”先打开模板选择，不创建空白自由研究。

#### 定义研究 `778:120`

1. 只能选择注册模板和 schema 允许的候选。
2. 保存草稿调用 PUT；成功后更新 draftVersion。
3. “继续：输入检查”先保存，再触发精确对象池和日期范围的有界输入预检；失败留在当前页。

#### 冻结计划 `778:188`

1. 展示本次输入门禁通过/阻断、所有排除项、日期范围、参数矩阵、固定参数和预算。
2. 任一 BLOCKED、缺少确认或 PLAN hash 变化时禁用“冻结并启动”。
3. 前端顺序调用 freeze、create Run；启动失败时保留已冻结版本并展示“重试启动”。

#### 运行详情 `778:256`

1. 轮询 QTF Run API，不轮询 Ops API。
2. 关闭页面不影响后台任务。
3. cancel 仅在 `canCancel=true` 时可用；重复点击幂等。
4. Ops 观测失败和 QTF 业务失败使用不同文案。

#### 结果比较 `778:324`

1. 先显示六道门禁，再显示参数组合结果。
2. INVALID/INSUFFICIENT 时禁用提名，但允许结束或保留观察。
3. 不提前展示运行中的局部冠军。
4. Figma 百分比全部替换为 API 真实值；开发测试不得断言示例百分比。

#### 候选评审 `778:392`

1. “拒绝候选”写 REJECT action。
2. “要求新实验”写 CHANGES_REQUESTED，并派生新 DRAFT。
3. “确认审核”只写 REVIEWED。
4. 批准和发布等待 F04 设计闭合，不得借确认审核自动执行。

### 11.5 页面状态

每个子页面至少有：

| 状态 | 行为 |
|---|---|
| loading | 保留 TopMarketBar、Breadcrumb 和页面骨架，局部 skeleton |
| empty | 说明没有研究、运行、结果或 release，不制造示例数据 |
| error | 显示用户可读错误和重试；不回退 mock |
| forbidden | 稳定骨架 + “需要管理员权限”，不展示业务数据 |
| conflict | 版本/hash 已变化，提示刷新；不覆盖新内容 |
| loaded | 按 Figma 正常展示 |

最终视觉验收前需要在 Figma 补 F06 状态。代码不能以临时大段说明文字代替状态设计。

### 11.6 Design System

1. 只使用 `wealth/src/styles/design-tokens.css` 已存在的 `--cs-*` token；缺 token 时先补 Design System 合同，禁止在 QTF CSS 中散落同义 hex/rgba。
2. 直接复用当前 56px `TopMarketBar`，不得复制 Header。
3. 页面保持 `1600 × 1200` 设计基线；实际浏览器遵循现有宽桌面最小宽度和纵向滚动规则。
4. 表头、状态、最后活动和操作列严格使用 `Research List Row` 同列宽；操作必须是真实 Button。
5. 数字、百分比、时间和 hash 复用 `wealth/src/styles/global.css` 的 `.num` 与 tabular numbers。
6. 系统成功/失败使用现有 info/warning/danger-system token，不能与 A 股 market-up/market-down 红绿混用。
7. `TopMarketBar`、`PageBreadcrumb`、token 与 `.num` 直接复用；Figma 已定义的 QTF Status Badge、Button、Workflow Step、Audit Row、Evidence Metric、Run Stage、Choice Chip、Template Option 和 Research List Row 保持 feature-local。
8. 不修改现有 `DataStatusBadge` 或 `SkeletonBlock` 来迁就 QTF；只有后续证明两个以上业务域合同一致时，才另立共享组件提升任务。

---

## 12. 异常码设计

进入 API 编码前，必须先把以下条目登记到 `wealth/docs/system/exception-code-registry.md`；401/403 继续复用认证层。

| code | 语义 | HTTP / 状态 | 前端动作 |
|---|---|---|---|
| `QTF_REQUEST_INVALID` | 请求、参数或日期合同非法 | 400 | 保留表单并定位字段 |
| `QTF_TEMPLATE_NOT_FOUND` | 模板/公式/schema 不存在或未激活 | 404/409 | 阻止创建或冻结 |
| `QTF_STATE_CONFLICT` | 当前状态不允许该动作 | 409 | 刷新最新状态 |
| `QTF_DRAFT_CONFLICT` | draftVersion 或 hash 已变化 | 409 | 禁止覆盖，重新加载 |
| `QTF_INPUT_PREFLIGHT_BLOCKED` | 本次输入门禁不合格 | 200 + BLOCKED 或 422 | 展示问题和上游责任，不启动 |
| `QTF_PLAN_NOT_APPROVED` | PLAN hash 未确认或已变化 | 409 | 返回冻结页重新确认 |
| `QTF_PLAN_BUDGET_EXCEEDED` | 实际范围超过本 Run 获批预算 | 409/BLOCKED | 停止并重新审批 |
| `QTF_INPUT_CHANGED_DURING_RUN` | preflight 后输入内容在同一 Run 内变化 | FAILED/BLOCKED | 新建 Run，不覆盖旧 Run |
| `QTF_RUN_FAILED` | 执行程序失败 | 500/FAILED | 展示简要原因和新 Run 入口 |
| `QTF_VALIDATION_INVALID` | 执行成功但可信门禁失败 | 200 + INVALID | 禁止提名 |
| `QTF_VALIDATION_INSUFFICIENT` | 样本不足 | 200 + INSUFFICIENT | 禁止提名，可保留观察 |
| `QTF_RELEASE_CONFLICT` | 批准、发布或替代关系冲突 | 409 | 保留当前 release，刷新状态 |
| `QTF_QUERY_FAILED` | 未分类查询/服务异常 | 500 | 页面 error，可重试 |

---

## 13. 测试设计

### 13.1 架构与打包

1. QTF 只能 import `qtf` 与 `src.foundation`。
2. Foundation、Ops、Biz 不得 import QTF。
3. App 可以 import QTF；legacy 目录不得承载 QTF。
4. wheel 内容含 `qtf/**`，不含 `scripts/tests/wealth/frontend/lake_console`。
5. `qtf/AGENTS.md`、根边界文档和依赖矩阵一致。

### 13.2 迁移与模型

1. 实施日先断言单一 Alembic head，再生成 migration。
2. M1 migration 只创建 `qtf` schema、Research/Revision 及其约束；不得顺手创建尚未进入里程碑的 Run、结果、候选或发布表。
3. M3、M4、M8 分别以实施当日真实 head 追加各自范围的 preflight/Run、结果证据、candidate/release 表和约束，不预先猜测 `down_revision`。
4. SQLite 测试使用兼容类型；不能因测试方便移除 PostgreSQL 约束。
5. FROZEN revision 不能更新冻结字段。
6. 同一 Run、候选或 action 的幂等键不能重复。
7. `task_run_id` 唯一但无跨域 ORM 关系。

### 13.3 单次 Run 输入门禁正反例

正例：

1. 单一 hierarchy version、父子闭包正确。
2. 每个父级完整组日只出现一次。
3. 交易日、有界字段、行数、对象数、组数和 content hash 稳定。
4. 同样输入重复预检产生相同内容指纹，但生成新的 preflight 记录。

反例：

1. hierarchy 空、多个版本、父级缺失或层级跳跃。
2. `dc_daily` 重复业务键、空涨跌幅、空成交额、非交易日。
3. 某父级缺一个子行业时，只排除该父级组日，不补零、不前向填充。
4. 小组低于冻结门槛时不能生成二元上榜标签。
5. 扫描或派生规模超过获批预算时 BLOCKED，零公式执行。
6. 输入门禁失败只写 issue，不修改来源表。

### 13.4 公式、未来泄漏与验证

1. `robustZ` 历史窗口不含当日，MAD=0 返回无效原因。
2. 修改 `t+1` 及未来输入不能改变 `t` 日因子或信号。
3. 60/120 分别预热，不允许用 60 的有效结果填 120。
4. 父级内排名不混入其他一级行业的二级行业。
5. 所有二级行业共享同一 effective parameter set。
6. 未来成功使用独立横向事实，不以未来平滑 heat 自证。
7. INVALID、INSUFFICIENT 与 VALID 三态均有正反例。
8. 简单价格/成交基线和候选使用相同未来窗口与有效组日。

### 13.5 Run、TaskRun 与事务

1. DRAFT、BLOCKED preflight、缺参数、未确认 PLAN 均不能创建执行 TaskRun。
2. Run 与 TaskRun 的启动意图同事务成功或同事务回滚，不产生单边孤儿记录。
3. 每个新 Run 都调用 Prod reader；不得读取旧 Run 结果作为输入。
4. 同一 Run 多个候选只触发一次来源读取。
5. QTF worker 只领取 `qtf_experiment`；GENERAL 和分钟 worker 均不能领取它；QTF worker 不能领取既有任务。
6. TaskRun success + validation INVALID 时 API 必须显示“执行完成、研究未通过”。
7. queued 取消立即 canceled；running 取消在组合安全点结束。
8. 已完成候选保留，但 canceled Run 不可提名。
9. 模拟 Ops 进度写失败，QTF 已提交候选和终态不回滚。
10. 模拟 QTF 业务提交失败，TaskRun 失败且不产生 VALID/候选/release。
11. TaskRun API 默认入口不能创建 `qtf_experiment`。
12. release commit 缺失或非法时，在读取 Prod 和公式执行前失败；合法 commit 与 runtime fingerprint 写入 Run。

### 13.6 候选与发布

1. 只有 COMPLETED + VALID Run 可 NOMINATE。
2. END/OBSERVE 不创建 candidate。
3. review、approve、publish 分别写一条 action；重复请求幂等。
4. 同一管理员可以执行全部动作，但不能跳状态。
5. 发布失败不改变旧 current release。
6. release 内容 hash 固定，批准后不可修改参数或范围。
7. 没有生产 serving 合同时 publish 必须失败关闭，不能空成功。

### 13.7 API 集成

1. 无 token 401；非管理员 403；管理员正常。
2. 核心真实 API case 覆盖 overview、draft、preflight、freeze、run、result、candidate。
3. 响应断言覆盖前端实际字段，不只测 HTTP 状态。
4. 技术 payload、SQL 和连接信息不能出现在 QTF API。
5. 版本冲突、幂等重试和状态跳跃都有 409 反例。

### 13.8 Wealth 前端

1. 路由生成/解析覆盖六页、非法编码、空 key、未知 QTF 子路径、内部 referrer 和浏览器前进后退。
2. 每页覆盖 loading、empty、error、forbidden、conflict、loaded。
3. 真实 API DTO 经过 adapter 后驱动可见文本、按钮 enablement 和路由。
4. TaskRun success 不得渲染成 VALID。
5. 结果 INVALID 时“提名候选”不可用。
6. “确认审核”不会调用 approve 或 publish。
7. 页面不请求 `/api/v1/ops/*`，不读取研究 JSON 文件。
8. Figma 1600px 基线做截图对账；普通 UI 元素相对设计偏差不超过 2px。
9. TopMarketBar、Breadcrumb 和既有 `/wealth/exploration` 回归不变。

---

## 14. 性能、规模和安全门禁

### 14.1 本能力的保存策略

1. QTF metadata、候选汇总、六道门禁和实际 signal events 保存到 PostgreSQL `qtf` schema。
2. 不保存每日完整输入和每日完整因子矩阵。
3. 不生成输入 CSV/Parquet、缓存或快照。
4. 是否为后续大能力使用派生 Parquet，必须另立具体能力 LLD。

### 14.2 每个 PLAN 必填预算

```text
estimatedSourceRows
estimatedGroupDays
parameterCombinationCount
executionPassCount
estimatedSignalEventRows
estimatedRuntimeSeconds
peakMemoryMb
resultStorageMb
sourceStatementTimeoutMs
```

这些值是每个 revision 的批准事实，不是平台全局常量。执行中任何一项超过该 Run 冻结的停止阈值时，在安全点 BLOCKED/FAILED 并要求重新审批。

### 14.3 查询与执行

1. hierarchy 只读一次。
2. trade calendar 按范围一次读取。
3. `dc_daily` 按字段、category、日期和代码池一次读取。
4. 候选在内存中的同一不可变输入上运行，避免 8 次重复扫 Prod。
5. 不增加 numpy/pandas/分布式框架；首个切片先以现有 Python/SQLAlchemy 能力完成基准。
6. 如 PLAN 证明 Prod 查询会影响热路径，停止并另行批准切换正式 Lake 直读；仍不复制输入。

### 14.4 配置与部署口径

1. 首版不新增数据库、连接串、账号、权限、消息队列或计算资源上限配置。
2. QTF worker 的批量数与轮询间隔沿用 CLI 显式参数及其受测默认值，不把能力级回测预算藏进 Settings。
3. 部署脚本增加 `QTF_WORKER_SERVICE` 和 `DEPLOY_QTF` 两个脚本级变量：全量部署默认处理 QTF；`--qtf-only` 只安装依赖、执行已批准迁移并同步/重启 QTF worker，不重启无关 worker。
4. `DEPLOY_QTF` 只存在于部署进程环境，不写数据库、不写应用配置文件；消费者仅限两个部署脚本。
5. 新 unit 必须按 `scripts/AGENTS.md` 同步到 `/etc/systemd/system`、执行 `daemon-reload`、enable、restart 并检查 status；sudoers 只增加该 unit 的 install/enable/restart/status 精确命令。
6. 为满足运行代码可追溯，新增唯一运行配置 `GOLDENSHARE_RELEASE_COMMIT`：部署脚本在安装当前 revision 后读取精确 commit，原子写入 `/etc/goldenshare/release.env`；只有 QTF worker unit 读取。它不进入 Web 请求、不写业务配置表，也没有代码默认值。
7. QTF worker 开始计算前把 `GOLDENSHARE_RELEASE_COMMIT` 和无敏感信息的 runtime version 组成运行指纹；变量缺失或不是 40 位十六进制 commit 时，在读取 Prod 前失败关闭。测试显式注入固定 commit。

---

## 15. 开发顺序

执行顺序保持 `M0 → M1 → M2 → M3 → ...`，但依赖含义必须明确：M1 只建立 QTF 包、依赖边界和研究状态；M2 在该包内建立候选公式内核；M3 同时依赖 M1 的平台状态和 M2 的计算内核，才接入 Prod、输入门禁和 TaskRun。从纯代码依赖看，M2 只依赖 M1 的包与边界骨架，不依赖 Research/Revision 已落库，更不依赖 Prod 审计；为保持每个里程碑独立验收，交付时仍先完整收口 M1 再进入 M2。M1 不包含重复数据审计，M2 不包含预测有效性结论；不得因为 Figma 有完整示例就跳过执行合同。

### M0：架构评审与边界冻结

**状态：2026-08-22 已收口。**

1. 已评审 QTF 架构方案、本 LLD、Figma 差距 F01–F06 和门禁 G01–G26。
2. 已冻结顶层 `qtf/`、只读上游、现有管理员、独立 QTF worker、业务审核动作和二级行业首切片。
3. M0 收口时 F01–F06 和 G01–G26 均未通过；此后只有 G01、G02 随 M1 完成，其余差距和门禁仍按各自后续里程碑处理。
4. 当前代码中尚无顶层 `qtf/`；M0 未改代码、未建表、未读 Prod、未执行研究，也未授权 R2 回测或生产发布。
5. M0 当时只批准进入 M1；当前后续顺序以紧邻的 M1 状态为准，仍不得越级进入 Prod 接入、TaskRun、真实回测、前端或发布工作。

### M1：QTF 平台基础与研究状态

**状态：2026-08-22 开发已收口，生产迁移待部署。**

1. 已建立 `qtf/AGENTS.md`、M1 包骨架、受控包发现、根目录责任、依赖矩阵和自动护栏；实际 wheel 已验证只包含 `src*`、`qtf*` 与发行元数据。
2. 已建立 Research/Revision 最小平台状态合同、应用端口、服务和 SQLAlchemy repository；只保存研究草稿与版本状态，不保存来源数据副本。
3. 实施前已确认仓库单一 Alembic head 为 `20260822_000142`；新增 `20260822_000143`，且迁移范围只包含 `qtf` schema、`research` 与 `experiment_revision`。App 已显式注册 QTF ORM。
4. 已完成状态约束、FROZEN 不可变、canonical revision hash、创建幂等、draftVersion 乐观并发及正反例测试。
5. 本轮未实现 Prod adapter、未读取或修改 Prod、未重复审计来源或历史覆盖、未接入 TaskRun，也未执行参数回测。当前配置指向远程生产库，因此只验证离线 PostgreSQL DDL，未执行远程 `alembic upgrade`。
6. G01、G02 已通过 M1 自动化与 wheel 验收；G03–G26 继续保持 `OPEN`，分别等待其所属后续里程碑。

### M2：二级行业候选公式内核

1. 建立 template/formula/parameter registry 和完整生效参数合同。
2. 从一级行业历史探索脚本迁移曾经使用过的价格、成交候选公式，不 import `scripts.research.*`。
3. 实现父级内排名、稳健标准化、EWMA、时间前沿，并以正反例验证公式、窗口、缺失值和无未来数据语义。
4. M2 的“验证通过”只表示计算实现符合冻结公式合同，不表示候选具有预测效果，也不表示适用于二级行业；不预设 R2 最终固定参数，不执行真实 R2。

### M3：输入门禁、有限计划与执行主链

1. 实施日重新确认 Alembic head，增加 Run、Run Input Preflight 及执行主链所需的平台状态表。
2. 复用第 10.1 节既有 Prod 来源合同，实现只针对当前草稿或 Run 精确对象池和日期范围的只读 adapter 与输入门禁；不重新做来源选型或全库覆盖审计。
3. 实施 PLAN 预算、revision freeze 和原子 Run/TaskRun 启动意图；增加 Ops 通用 external task 扩展点、QTF 独立 lane 和 App QTF adapter。
4. 先登记第 12 节异常码，再增加二级行业垂直切片的最小管理员 API，以及 QTF worker CLI、systemd unit、release commit、部署脚本与最小 sudo 白名单；API 不得拥有另一套公式或默认参数。
5. 完成输入门禁正反例、lane 隔离、启动原子性、每 Run 重读、同 Run 单次读取、安全取消、进度和运行期事务隔离测试。

### M4：可信门禁与结果证据

1. 实现逐参数组合安全提交、六道门禁、结果摘要、敏感性、signal event 和 results/conclusion API。
2. 完成合成数据、冻结历史样本、未来泄漏差分、预热稳定、覆盖和 IS/OOS 回归。
3. 形成明确 `VALID/INVALID/INSUFFICIENT`；仍不自动执行真实 R2。

### M5：R2 真实研究验收

1. 先单独提交第 10.5 节的完整 R2 事前 PLAN，列出对象、日期、参数、成功定义、IS/OOS、预算和停止条件。
2. 只有用户批准该 PLAN 后，才执行一次有界真实 R2；批准本 LLD 不等于批准 R2。
3. 交付有效候选、失败样本或“本轮未找到”；禁止看到结果后在同一 Run 扩参。

### M6：提炼通用平台合同与业务 API

1. 只从 M1–M5 已证明的共同点收敛 overview、research、preflight、freeze、run、result、candidate 合同，不保留脚本旁路。
2. 补齐工作台全部管理员 API、registry 查询和安全 TaskRun 视图。
3. 完成真实路由集成测试、状态冲突、幂等和技术信息泄漏反例。

### M7：Figma 交互闭合与前端六页

1. 先补 F03、F05、F06；F01 可以独立后置，但按钮必须 disabled 或移除。
2. 按六个正式节点实现路由、Shell、API、adapter、view model 和组件。
3. 完成 1600px 截图与状态验收。
4. 不实现未设计的批准/发布页面。

### M8：候选、批准与发布

1. 先补 F04 设计。
2. 实现候选动作、不可变 release 和独立 approve/publish。
3. 发布前必须另有 sector production 同核计算、serving 原子切换和回滚 LLD。

### M9：财势乾坤下游接入

1. Biz 只读正式 serving。
2. Wealth 行情页面只读 Biz/QTF 已发布事实，不读取实验表。
3. 板块雷达、板块速览如何消费信号另立页面和 serving 合同。

### M5 的单独授权门禁

完成 M1–M4 只表示平台已经具备执行条件，不自动授权 M5。真实 R2 必须再次提交第 10.5 节事前计划；用户批准具体日期、对象、参数、验证、预算和停止条件后，才允许创建并运行该 revision。

---

## 16. 编码门禁矩阵

| Gate | 用户可见结果/硬口径 | 代码落点 | 正向测试 | 反向测试 | 当前状态 |
|---|---|---|---|---|---|
| G01 | QTF 是顶层产品域 | `qtf/**`、package config | wheel 可 import qtf | qtf 未被打包时失败 | PASS (M1) |
| G02 | 不破坏依赖方向 | architecture guardrails | App 可装配 QTF | QTF/下层反向导入被阻断 | PASS (M1) |
| G03 | 复用现有 DB/管理员 | App DI、`require_admin` | admin 200 | 新账号/非管理员不可绕过 | OPEN |
| G04 | 不保存输入副本 | Prod adapter、preflight model | 只保存 hash/summary | QTF 表/产物含原始输入时失败 | OPEN |
| G05 | 数据问题交回上游 | run input preflight | PASS 可继续 | BLOCKED 零修复、零公式执行 | OPEN |
| G06 | 每个新 Run 重读 | experiment service | 新 Run 调 reader | 复用旧 result/input 被阻断 | OPEN |
| G07 | 同一 Run 不重复扫 Prod | sector executor | 多候选一次 load | 每候选重查来源测试失败 | OPEN |
| G08 | 公式和参数完整冻结 | registry/revision | 所有有效值入 hash | 缺值/运行时默认值被拒绝 | OPEN |
| G09 | 不允许任意 Python | registry/API | 选择注册 formula | 上传源码/表达式被拒绝 | OPEN |
| G10 | 时间前沿正确 | engine/time_frontier | t 只看历史 | 修改未来不影响 t | OPEN |
| G11 | 父级内比较 | sector ranking | 同父排名正确 | 其他父级不能改变结果 | OPEN |
| G12 | 小组规则显式 | preflight/parameter schema | 达门槛可评价 | 低于门槛不生成伪标签 | OPEN |
| G13 | 缺失不补数 | run input preflight | 完整组日参与 | 缺行不补零/不前填 | OPEN |
| G14 | TaskRun success != VALID | run/result API | success+VALID 可提名 | success+INVALID 不可提名 | OPEN |
| G15 | 取消在安全点 | executor/observer | 组合后停止 | 半条参数组合结果不可见 | OPEN |
| G16 | Ops 与 QTF 事务隔离 | App runtime adapter | Ops 正常观测 | Ops 写失败不回滚 QTF | OPEN |
| G17 | 有限计划获批 | plan/freeze service | hash 相同可冻结 | hash 漂移/超预算阻断 | OPEN |
| G18 | 候选不自动发布 | candidate/release | 四步分别成功 | 跳步、确认审核即发布被拒绝 | OPEN |
| G19 | 发布失败保护旧版本 | release service | 原子生效 | 新版失败时旧版仍 current | OPEN |
| G20 | Wealth 只读 QTF API | frontend client | QTF API 驱动页面 | `/ops`/文件/mock fallback 为零 | OPEN |
| G21 | 六页匹配 Figma | QTF pages/components | 1600px 截图通过 | 表头错位、按钮非组件失败 | OPEN |
| G22 | 六类页面状态稳定 | controllers/UI | 状态逐一渲染 | error 回退示例数据失败 | OPEN |
| G23 | R2 未经批准不执行 | freeze/run service | 获批 hash 后可建 Run | Figma 示例直接启动被阻断 | OPEN |
| G24 | 申万与跨体系为零 | sector contracts | 只接受 DC L2 | SW/跨体系参数被拒绝 | OPEN |
| G25 | QTF 独立 worker 进程 | worker lane/CLI/systemd | QTF lane 领取实验 | GENERAL/分钟 lane 抢占或 QTF 领取既有任务时失败 | OPEN |
| G26 | 运行代码可追溯 | release env/run fingerprint | 合法 commit 写入 Run | 缺失/伪 commit 时零来源读取 | OPEN |

所有 Gate 在实现、测试和真实验收完成前保持 OPEN。文档完成不等于 Gate 通过。

---

## 17. 实施验证命令

实施阶段至少执行：

```bash
python3 -m pytest -q tests/architecture/test_subsystem_dependency_matrix.py
python3 -m pytest -q qtf/tests
python3 -m pytest -q tests/web/test_qtf_api.py
python3 -m pytest -q tests/test_worker_lane.py tests/test_cli_ops_runtime.py tests/web/test_ops_runtime.py
alembic heads
alembic upgrade head
python3 -m pytest -q tests/test_qtf_models.py tests/test_qtf_task_runtime.py
cd wealth && npm run typecheck
cd wealth && npm run test
cd wealth && npm run build
bash -n scripts/deploy-systemd.sh scripts/deploy-layered-systemd.sh
python3 scripts/check_docs_integrity.py
git diff --check
```

真实 R2 只读验收、性能证据和具体运行命令必须由获批 PLAN 生成，不能提前在本 LLD 中写死。

---

## 18. 开发进入结论

1. M1–M6 的代码落点、依赖、存储、状态、API、TaskRun 和测试边界已经具备进入评审的 LLD 条件。
2. Figma 六个 loaded 页面和组件结构可以支撑 M7 主流程，但 F03、F05、F06 必须在前端最终实现前闭合。
3. 公式与参数页 F01 可以后置；未设计时入口必须 disabled 或暂不出现，不能做假页面。
4. 候选批准与发布 F04 是 M8 阻断项；当前候选页只能做到确认审核。
5. 真实 R2 仍未获批；平台开发和真实研究执行是两次独立授权。
6. M9 的生产 serving 与板块雷达/板块速览消费必须另立能力 LLD，不能在平台框架开发中顺手接入。

因此，**M1：QTF 平台基础与研究状态** 已于 2026-08-22 完成开发收口，生产迁移等待部署；下一步只能进入 **M2：二级行业候选公式内核**，不能重复开展 Prod 数据覆盖审计，也不能直接进入 Prod 接入、TaskRun、真实回测、前端或发布。
