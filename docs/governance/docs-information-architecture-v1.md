# 文档信息架构与待整合清单 v1

更新时间：2026-09-09（补充 Ops 实时流监控与配置中心整合记录）

## 1. 目标

本文件用于把 `docs/` 从“历史堆叠”整理为“可持续维护”的结构。

原则：

1. 先有单一事实，再有专题补充。
2. 文档按职责分层，不按个人记忆归档。
3. 删除前先确认是否还有现实价值；保留必须有明确定位。

---

## 2. 当前目录结构（目标态）

```text
docs/
  README.md
  architecture/   # 架构基线、边界、分层方案
  ops/            # 运维契约、执行与观测专题
  datasets/       # 数据集开发文档与策略说明
  frontend/       # 前端治理、流程、视觉与执行
  platform/       # 对上业务 API 规范
  release/        # 发布流程
  product/        # 产品原始材料
  templates/      # 开发模板
  sources/        # 数据源接口说明（源站文档摘要）
  governance/     # 文档治理与整合记录
```

---

## 3. 分类规则（必须遵守）

1. `architecture/`
- 只放“系统级”规则与基线。
- 一旦收敛完成，文档应写“现状”而不是“迁移流水账”。

2. `ops/`
- 只放运维平台对象、页面契约、执行流程、专项方案。
- 与代码状态冲突的旧方案必须下线，不保留并行版本。

3. `datasets/`
- 一个数据集一份开发文档。
- 跨数据集策略另建专题文档（如 `moneyflow-*`）。

4. `sources/`
- 存放“数据源接口说明”的本地摘要与落地约束。
- 不替代 `datasets/*` 的开发方案文档。

5. `frontend/`
- 面向前端治理与交付流程。
- 同一主题多文档并存时，应提供主文档并标注专题关系。

---

## 4. 待整合清单（下一轮）

### 4.1 Architecture 组

基线批次状态：2026-09-08 按用户确认将下列 7 份文档合并为 3 份。数据集专题另按下文第二批记录收敛为 4 份。只整合文档，不改代码、依赖规则、数据库或 Lake；未全面审计其他架构方案。

1. [子系统架构基线](/Users/congming/github/goldenshare/docs/architecture/subsystem-boundary-plan.md)：目录、职责、依赖矩阵、现存差距、legacy 边界与护栏。
2. [Foundation 研发基线](/Users/congming/github/goldenshare/docs/architecture/foundation-current-standards.md)：Prod 数据分层、研发原则与上手入口。
3. [多源映射与发布规则](/Users/congming/github/goldenshare/docs/architecture/dataset-publish-governance-spec-v1.md)：只补充多源语义，不重建通用接入门禁。

数据集模板继续独立维护设计与验收填写要求；Ops 契约继续维护状态和展示语义。后续修改规则应回到其归属文档，不再同时更新多个相同清单。

<a id="architecture-consolidation-20260908"></a>

#### 本轮合并去向与删除清单

以下旧文件名仅用于追溯，不是当前入口。删除文件均可从合并前提交 `50b00161` 恢复，不另建空壳跳转文档。

| 原文档（均在 docs/architecture） | 处理 | 有效内容去向 |
| --- | --- | --- |
| `subsystem-boundary-plan.md` | 保留路径，改为子系统架构基线 | 目录与职责 §2、统一依赖 §3、差距 §4、迁移结论 §5、护栏 §6 |
| `dependency-matrix.md` | 并入后删除 | 目标矩阵、零白名单的适用边界、App 现存反向依赖与测试清单，归入架构基线 §3/4/6 |
| `platform-split-plan.md` | 并入后删除 | App 壳/认证/模型/API/Web/静态资源归属、旧试点退出及防回流结论，归入 §5/6 |
| `ops-consolidation-plan.md` | 并入后删除 | Ops runtime/services/action catalog、数据维护主链、市场情绪服务归属与 facade 边界，归入 §5/6 |
| `foundation-current-standards.md` | 保留路径，精简为研发基线 | 分层、事实源、长任务与分阶段验证保留；详细交付清单引用数据集模板 |
| `foundation-onboarding-and-legacy-checklist-v1.md` | 有效入口并入后删除 | 阅读入口与执行授权边界归入研发基线 §2/7；旧遗留事项分类见下表 |
| `dataset-publish-governance-spec-v1.md` | 保留路径，收窄为多源专题 | 映射、可比性、清洗、来源身份、发布优先级/回退/版本追溯、变更与测试要求 |

#### 未原样搬入的旧内容

| 旧内容 | 处理理由与当前去向 |
| --- | --- |
| Platform/Operations 空包删除与外部兼容评估待办 | 当前目录与护栏已证明无 Python 空包，不再列待办；不声称审计了仓库外脚本，仍保留 legacy 禁令 |
| 新人连跑 init-db、seed/apply、状态重建 | 不作为最小静态验证或默认执行授权；研发基线 §2/7 区分读文档、测试和获准写入，本轮未执行这些命令 |
| 前端分类硬编码、unknown/skipped/unobserved 与各层独立观测要求 | 状态与展示交回 Ops 当前契约，字段及消费者验收交回数据集模板 §7；不把旧枚举及分层规则另存为第二套现行定义 |
| 无业务日期时用最近同步日期兜底业务日期 | 与当前模板 §7.4 区分同步迹象的要求冲突，删除旧要求；研发基线 §4 保留明确区分 |
| 单源也须建立 source_status/resolution_policy/std 规则对象 | 不再要求为单源或 pass-through 补造对象/层；按实际 DatasetDefinition.storage 与模板设计，多源特殊规则由专题承载 |
| Source 页只看 Raw、旧页面兼容、新增数据集自动 seed | 不作为全局规则；实际来源/目标表与状态投影按模板 §7 验收，正式执行须另获授权 |
| equity_indicators、adj_factor、fund_adj 及 core 兼容路径旧迁移清单 | 移出新人必做任务；本轮不判定它们全部完成，也不据此下线任何表、字段或消费者。既有 core 保留边界继续由研发基线约束；再处理时须以对应数据集方案及当前实现确认，历史条目可从上述提交追溯 |
| 全部数据集必须经过 Raw/Std/Serving、所有发布均套多源流程 | 与已确认的 direct-serving、Raw 写入/Serving 视图等路径冲突；多源专题按实际获准路径设计，不强制物理 Std 层 |
| 多份通用门禁/PR 清单与 Stock Basic“当前口径”示例 | 通用填写归数据集模板；示例只解释规则写法，不把未经本轮核验的具体数据集生产策略写成事实 |

核验依据：先使用 CodeGraph `codegraph_explore` 查护栏上下文（返回混入无关符号，未据此扩范围），再定向读取三个架构护栏、Ops/Biz 入口的 App 导入及 legacy 目录；导航扫描覆盖 AGENTS、Markdown、HTML 与直接引用方。保留“目标约束/代码现状/测试覆盖”的区分，不以整合文档替代代码整改或生产验收。

本轮验证：文档完整性三个检查组与 `git diff --check` 通过；新增/修改的 40 个本地 Markdown/HTML 链接及锚点通过定向检查；三个架构护栏共 16 项测试通过。旧文件名仅留在上述迁移记录，不再作为当前链接或必读入口。未执行数据库、Lake、部署或安装操作，工作区其他任务修改保留。

### 4.1.1 当前权威入口与专题角色（G1）

Architecture 组按以下顺序判断文档是否具备当前权威性：

1. 当前运行时行为、API 契约和数据字段：以代码、测试、配置与实际运行事实为准。
2. 系统边界与依赖方向：统一以 `subsystem-boundary-plan.md` 为准，目标、现存差距与护栏覆盖分别阅读。
3. 数据集静态事实：以 `src/foundation/datasets/**` 的 `DatasetDefinition` 为准；执行计划以 `src/foundation/ingestion/**` 的 `DatasetExecutionPlan` 为准。
4. 枚举语义已分别并入 DatasetDefinition 与日期指南；完整字段、可用组合和数量由模型、linter、registry 与测试提供，不另维护手工快照。
5. 方案、LLD 与验收记录保留各自角色：方案/LLD 解释设计与局部实现，验收记录提供时点证据，均不能覆盖当前代码事实。
6. 清退专项 M5 的 86 份纯旧 Local Lake 文档与 3 份旧模板退出当前工作树，不建立 archive/tombstone。必要历史结果归入 [单一初始化与修复总账](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-bootstrap-legacy-links.md)，全文通过 Git 历史追溯；当前正式设计与混合文档只局部纠偏，不连带删除。

`docs/README.md` 负责导航和阅读顺序，不重复承载上述事实。

本轮 Architecture 入口治理结论：

1. S0 保留仓库上手总览、QTF 方案、子系统架构基线与 Foundation 研发基线；S1 不再重复列出这些入口；多源专题及下述四份数据集专题各自承担独立职责。
2. `Dataset Maintain M-1 到 M8` 已在第二批提取有效要求后删除；旧阶段记录从 Git 追溯，当前实施状态回到执行专题、代码和测试。
3. 方案与 LLD 成对保留时，必须分别承担上位方案与落地细节；独立验收记录、审计记录和旧 Local Lake 证据不提升为当前主入口。
4. `top_list` 版本收口方案已实施，后续未决范围仅限数值冲突业务规则，不再使用无状态标签的“专项方案”表述。


<a id="dataset-topics-consolidation-20260908"></a>

### 4.1.2 数据集架构专题：11 份收敛为 4 份

2026-09-08，按用户确认的“正确性 + 简洁性”审计建议实施。只改四份承接文档、索引和直接引用，删除以下七份旧文档；没有代码、配置、数据、服务或架构边界变更。合并前全文可从提交 `bf608b7c` 恢复，不另建 archive 或空壳跳转文档。

| 原文档（均在 docs/architecture） | 处理与关键内容去向 |
| --- | --- |
| `dataset-definition-single-source-refactor-plan-v1.md` | 保留路径，现行定义专题：字段归属、输入/来源、对象池例外、存储与观测、消费者 |
| `dataset-definition-enum-reference-v1.md` | 删除；非日期语义并入定义 §2–5，日期枚举并入日期指南 §2，分页/提交规则并入执行 §4–5；全量列表回到代码 |
| `dataset-universe-model-refactor-plan-v1.md` | 删除；对象池来源、覆盖与空池边界并入定义 §4，展开与 Plan 字段关系并入执行 §3 |
| `dataset-definition-input-filter-cleanup-plan-v1.md` | 删除；无效 exchange 的污染原因、已完成结论、合法参数例外和回归入口并入定义 §3 |
| `dataset-execution-plan-refactor-plan-v1.md` | 保留路径，现行执行专题；实际 Plan 字段、分页/stage、unit 与 fund_daily 两阶段提交、进度、历史事故及目标边界 |
| `dataset-maintenance-refactor-m-1-to-m8-execution-index-v1.md` | 删除；主链、状态隔离、枚举哨兵、验收要求并入执行 §1/3/5/8；施工阶段不再单独保留 |
| `dataset-date-model-consumer-guide-v1.md` | 保留路径，日期唯一专题入口；输入/执行/审计三层、字段、特殊锚点、Workflow 和消费者 |
| `workflow-time-shape-vs-time-regime-analysis-v1.md` | 删除；时间形状与制度、默认日期、输入边界并入日期 §5；五个数据集及 workflow 的专项进度仍归参考数据任务组索引 |
| `stk-period-calendar-anchor-date-model-fix-plan-v1.md` | 删除；股票/指数差异、周期无交易的规则排除、共表 freq、空计划边界及测试入口并入日期 §4/6 |
| `weekly-monthly-trade-date-anchor-confirmation-v1.md` | 删除；被推翻的“全部最后交易日”不再作为规则，修正原因并入日期 §4 |
| `core-serving-light-design-v1.md` | 保留路径；实际开关、局部路由、日线 upsert 刷新、视图与实体差异、已知局限及待建设方向 |

四份现行入口：[定义](/Users/congming/github/goldenshare/docs/architecture/dataset-definition-single-source-refactor-plan-v1.md)、[执行](/Users/congming/github/goldenshare/docs/architecture/dataset-execution-plan-refactor-plan-v1.md)、[日期](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md)、[Serving Light](/Users/congming/github/goldenshare/docs/architecture/core-serving-light-design-v1.md)。

#### 没有随精简消失的关键边界

- index_weight 与 index_mins 的显式代码规则不同；index_daily 请求池与 Serving 池不同；dc_member/ths_member 的本地前置依赖保留。
- 输入日期不等于连续完整性；自然周五/月末不等于最后交易日；季度锚点不自动启用连续审计。
- stage 页持久化不等于业务发布；SQL batch 不等于提交；unit commit 不等于已证明持久化续跑。
- 历史 stk_mins 大事务事故的原因与防回归要求保留；不重新执行旧停机清空、seed 或迁移步骤。
- Foundation 只发结构化进度、Ops 统一格式化仍是方向，当前 executor 生成中文 message 的事实保留；不借本轮改造代码。
- 原状态 outcome/coverage/队列及 Light 指标、巡检、通用刷新任务的拟议名称不冒充现行 API；对应安全/观测目标保留，不宣称已验收。
- 源端并发专题、TaskRun 专题和参考数据任务组继续承接各自进度；本文不自动关闭它们。

核验使用 CodeGraph `codegraph_explore` 后定向读取模型、resolver/planner、linter、日期定义/审计、Workflow 默认输入、Light 设置/查询/刷新/CLI 及对应测试。CodeGraph 返回的无关符号未作为判断依据。按文档治理技能先迁入有效信息、区分事实与目标，再更新引用与删除；本轮不增加新的治理体系。

本批结果：11 份专题原有 4,494 行，合并后四份共 493 行；不是按行数目标删规则，重要信息去向按上表对账。文档完整性三个检查组、382 个本地 Markdown 链接及锚点的定向检查、`git diff --check` 均通过；七个旧文件名只保留在本节追溯表，不再作为活跃引用。未运行代码测试或生产验收，未修改代码和数据；其他任务的 README 条目及未跟踪文件保留。文档精简不等于完成文中仍注明的运行态目标。

### 4.2 Ops 组

当前职责：`ops-contract-current.md` 维护边界，`ops-api-reference-v1.md` 维护接口，`ops-workflow-catalog-v1.md` 维护工作流清单。TaskRun、自动任务、freshness、多源对账等继续独立承载其专题；本批不代表这些专题已全面审计。

<a id="ops-manual-consolidation-20260909"></a>

#### 手动维护与时间模式：5 份收敛为 3 份

2026-09-09，按用户批准的审计建议合并；只修改文档和直接引用，不修改代码、配置、数据库或 Lake。两份删除文档的全文可从合并前提交 `4aad5c34` 恢复，不保留空壳或并行历史入口。

| 原文档（均在 docs/ops） | 处理与有效内容去向 |
| --- | --- |
| `ops-contract-current.md` | 保留；修正交付模式来源、审查维护边界、release 路径；§11 承接三类动作、入口、none 语义及回归重点 |
| `ops-api-reference-v1.md` | 保留；§2.4 承接表单字段含义、各时间请求形态、预检与拒绝行为；§12.1 补齐模型及 Workflow 字段来源 |
| `ops-workflow-catalog-v1.md` | 保留六个工作流的用途、步骤、参数、合并优先级、失败策略；修正 29 步清单与两个工作流参数；字段表移交 API，不重复维护 |
| `ops-manual-action-model-alignment-plan-v2.md` | 迁出后删除；动作分工、catalog 保留、TaskRun 主链及防回退规则归总契约 §11，字段与请求示例归 API §2.4/12.1，日期映射引用统一日期指南 |
| `ops-manual-action-time-mode-upgrade-plan-v1.md` | 迁出后删除；mixed modes、trade_cal 默认 none、完整日历刷新与无日期不等于小任务归总契约 §11，工作流不继承步骤时间能力归总契约/Workflow；草稿、复制、预填及 fixture 回归要求一并保留 |

不原样保留的内容：已完成的里程碑、旧类名/表单结构、手动页仍待切换 catalog、交易日历仍偷跑最近 30 天等旧故障描述。它们是历史实现背景，不是当前待办；不借此变更其他数据集的时间语义、自动任务或执行器事务。

**未被文档精简掩盖的实现限制：**当前 Workflow dispatcher 不执行 `depends_on` 阻塞判断；定义/响应含 `parallel_policy` 不代表已支持依赖并行。其步骤异常没有 dataset action 分支的独立取消异常处理，不能直接承诺返回 canceled。这些限制记录在 Workflow §2，是否改造另行决定，本轮不实现、不宣称已解决。`margin` 仅从错误的工作流文档步骤中移除，不删除数据集或独立任务。

核验依据：CodeGraph `codegraph_explore` 的 dispatcher 源码与定向读取的 action registry、manual query/schema/service、前端表单/API 类型及相关测试断言。新增字段说明描述的是现有契约，不是 API 变更。旧文件引用扫描覆盖仓库及 `.agents`；仅保留本节文件名作追溯，README 的无关研究条目保留。

本轮验收范围为文档完整性、链接/引用、结构与差异检查；未运行同步、源站实测、数据库测试或生产验收。API 校准限于手动动作、目录与提交相关章节，其余端点不借本批升级为“全量已验证”。

校验结果：五份原文共 3,313 行，合并后三份共 2,280 行，减少 1,033 行；有效信息按上表迁移，不以行数为删除依据。只读 AST 对账通过 12 个相关请求/响应模型字段、时间控件与选择规则枚举、六个工作流的全部步骤/顺序/参数；7 个时间输入示例通过 JSON 形态检查。18 个新增本地链接及锚点、文档完整性三个检查组和 `git diff --check` 均通过。这些静态检查不替代真实执行测试。

<a id="ops-automation-consolidation-20260909"></a>

#### 自动任务日期与能力：3 份收敛为 2 份

2026-09-09，按用户批准的第一批建议实施；只修改本组文档及直接引用。原文可从合并前提交 `c027f20d` 追溯，不留空壳 LLD 或第二套字段模型。

| 原文档（均在 docs/ops） | 处理与有效内容去向 |
| --- | --- |
| `ops-schedule-calendar-policy-plan-v1.md` | 保留路径、改为当前说明；七种策略、动作声明优先级、计划时刻与时区、固定时间拒绝、季末/成功窗口及回归入口集中维护 |
| `ops-automation-capability-contract-plan-v1.md` | 保留路径；集中维护目标上下文、三种触发方式、七类 source-ready 条件、绑定顺序、runtime 防篡改、只读 audit、P5 与历史证据 |
| `ops-automation-capability-contract-lld-v1.md` | 有效内容迁出后删除；AC-001～015 归能力契约 §6，原位迁移/回退/生产验收归 §5，完整响应字段归 API §12.1 |

直接联动：API §3/11/12.1 校准策略、纯 probe 空时间及六个请求示例，补齐 capability 模型；新闻专项保留用途与历史设计，明确“仅新闻”不是通用策略禁令；README 删除 LLD 入口。

删除重复的已完成实施步骤、旧白名单和“calendar_policy 只保存不生效”等过时描述。81 个目标、28 schedule/6 ProbeRule 只留为带日期/阶段的历史记录，不再作为固定生产数量门禁；两条 source_key 的授权修复证据迁入能力契约，不作为本轮写库授权。

**未完成事项没有被合并抹掉：**P5 最后记录为 2026-08-24 代码及本地验证完成、生产迁移待独立维护窗口。本轮未查生产，不能认定已经执行或仍未执行；能力契约 §5 保留重新核实、独立授权、精确迁移与前后对账要求。新闻专项结案不能替代 P5 验收。

核验依据：CodeGraph `codegraph_explore` 及定向读取的日期能力/自动任务 resolver、Schedule/TaskRun service、binding、runtime、Catalog schema、只读 audit/CLI、P5 迁移、前端 capability 消费和相关测试。只调整文档，不改代码、配置、数据库、Lake 或依赖边界；未运行生产探测、任务、迁移或数据库回归。

校验结果：三份主体文档从 1,245 行收敛为两份 230 行，减少 1,015 行；唯一有效信息按上述去向保留，字段细节集中到 API。只读 AST 对账通过 11 个 capability 响应模型完整字段、7 种策略；6 个纯 probe JSON 示例时间不变量通过。本批 14 处新增/变更本地链接及锚点有效，旧 LLD 在引用扫描范围内只剩本节追溯文件名；文档完整性三个检查组及 `git diff --check` 通过。这些是静态文档验证，不代表接口实调或 P5 生产验收。README 的其他研究条目及工作区无关改动保留。

<a id="ops-catalog-biz-consolidation-20260909"></a>

#### 数据集目录与 Biz 投影：4 份收敛为 2 份

2026-09-09，在自动任务批次提交 `71e284a7` 后，按用户“处理下一批”继续本组文档治理。旧全文可从该提交追溯。本批不改运行代码、分组配置、API 契约或数据，不执行部署、任务和生产验收。

| 原文档（均在 docs/ops） | 处理与重要信息去向 |
| --- | --- |
| `ops-dataset-catalog-view-plan-v1.md` | 保留路径；集中说明默认目录、领域/展示/能力区分、真实消费者、审计外层分组、静态校验与待确认边界；删除过期逐数据集对照表和已完成施工步骤 |
| `ops-biz-dataset-auto-projection-plan-v1.md` | 保留路径为当前投影契约；承接 15 张卡片、生产入口、五类观测、状态、任务身份、异常/性能边界、回归与部署验收 |
| `ops-biz-table-source-display-plan-v1.md` | 迁出后删除；一期原始只读背景及成交额多频率/行情消费区别保留为带日期的历史说明；旧全表 count/MAX SQL 不再作为现行实现 |
| `ops-biz-dataset-auto-projection-lld-v1.md` | 迁出后删除；完整定义字段、逐表生产入口、查询/状态/排序/任务和发布要求并入主契约，不再复制第二套已完成改文件清单 |

审计结论及本轮处理：

| 级别 | 文档问题 | 当前证据与修正 | 是否需新增拍板 |
| --- | --- | --- | --- |
| G0 | 原目录表被写成现行分组输入；resolver 被描述成筛选器和隐藏能力 | 默认配置已有 15 组、94 项；resolver 只解析/校验，visible 没有被查询链统一过滤；写明实际边界，不改变配置 | 文档纠偏不需要；更改分组/隐藏行为需另批批准 |
| G0 | 主案开头仍写只有一张卡片、旧 catalog 未替换，与末尾完成记录冲突 | 当前 Biz registry 为 15 张/4 组，11 维护卡片、4 只读卡片；删除过时现状，保持部署验收未核实 | 否 |
| G0 | 任意新表只加 Definition 即可接入；producer 可填 materialized_view | query 有 _DIRECT_TABLES 与固定模型，linter 仅静态检查；producer 枚举实际只有 maintenance_action/dagster_asset；主案与模板同步纠偏 | 否；新增能力仍须单独评审 |
| G1 | 方案允许进程缓存，LLD 禁止；声称任意失败只影响一张卡片 | 当前只有单请求缓存；八张分析卡共享观测，错误可能共同影响八张；TaskRun/schedule/日历异常不在业务观测 savepoint 中 | 否；本轮不改异常处理或缓存 |
| G1 | 判迟时间自动继承 action；日历缺失一定未知且只用开市日 | 定义是静态时间值；缺当天日历可查最近开市日，lag 计数为 0 仍回退自然日差；如实记录差距，不把兜底升级为推荐规则 | 否；是否改造另行决定 |
| G1 | 排序、limit 和示例容易误读 | Biz 按 group_order/item_order/dataset_key 排卡；先观测全部再截取；API 区分 Biz 四组、外部目录与历史 total=56 示例 | 否 |
| G2 | 三份 Biz 文档重复历史目标、字段、查询及施工清单 | 迁移有效内容后只保留一个投影契约，API 保管字段索引；模板只同步 producer、TaskRun 身份和新增观测边界 | 否 |

尚待核实的原事项保留：目录分组最终确认没有独立结案证据；Biz 投影最后记录为 2026-09-05 代码完成、部署/生产/页面验收待完成。本轮不查生产，不认定仍未部署，也不自动宣布已验收。新增代码局限只记录，不自动升级为本轮开发任务。

核验采用文档治理与开发准入 skill。CodeGraph `codegraph_explore` 两次返回部分 Biz 定义及较多无关同名 resolver；无关结果未用于结论，随后定向读取实际 catalog、查询、schema、页面消费及测试。没有为文档治理运行数据库测试、源端请求、Dagster 或浏览器构建。

静态对账通过：15 张 Biz 卡片逐项 key/名称/分组/顺序/producer/物理表、15 个 Definition 字段、2/5/5 个 producer/观测/新鲜度枚举、外部目录 15 组/94 项；本批 14 处新增本地链接和锚点有效。四份主文档 2,022 行收敛为两份 221 行，减少 1,801 行；行数不是删除依据，信息去向以上表为准。文档完整性三个检查组与差异检查通过，未把它们当作生产性能或运行验收。README 的无关研究条目及其他任务改动保留。

<a id="ops-freshness-consolidation-20260909"></a>

#### Freshness：3 份收敛为 1 份

2026-09-09，按用户批准的正确性与精简建议实施。只修改本组文档及直接引用，不改代码、配置、数据或依赖边界。合并前全文可从提交 `ed16ff48` 恢复，不留 archive 或跳转空壳。

| 原文档（均在 docs/ops） | 处理与有效信息去向 |
| --- | --- |
| `ops-freshness-policy-explicit-mapping-plan-v1.md` | 保留路径，改为现行契约；§1–2 保留事实归属、五类 Policy、日期阈值与失败语义；§3–4 保留查询刷新和消费者边界；§5–6 保留退场证据、未核实验收与回归入口 |
| `ops-freshness-single-source-layer-snapshot-retirement-plan-v1.md` | 迁出后删除；页面不扫描、混合 snapshot_date 轻量重算归 §3，旧表/列/API/页面退场和业务事务保护归 §5 |
| `ops-date-model-freshness-alignment-plan-v1.md` | 删除 17 行历史跳转说明；风险登记簿改指主契约 §5，不丢失风险记录 |

删掉的是已完成施工步骤、重复模型/字段表、旧问题现状和不完整的手工清单：旧表 70 项与代码逐项比对，已列项 Policy 无差异，但当前映射已有 94 项，新增 24 项未被旧文档覆盖。完整清单回到代码与 registry 覆盖测试，不再维护另一份全量表。

本轮纠偏：依赖箭头改为 Ops → Foundation；记录自然日差阈值、源端发布时间、正常 freshness 与近期失败可以并存、Definition 非热更新、本地与远端探测边界。`dividend/stk_holdernumber` 已退出连续审计的事实保留，不删除其数据集或维护能力。API 仍负责字段全集，日期指南仍负责输入/执行/审计三层语义。

**未被合并抹掉的差距：**空快照/读取异常仍可使页面链路回退到实时业务观测；保留页面不扫描的设计要求，明确尚未完全满足，不把差距升级为允许模式。原 M6 快照重建与回归没有本轮独立生产证据，不自动关闭，也不自动重跑。`ops.dataset_status_snapshot` 是现行共享状态投影，必须保留。

核验采用文档治理与开发准入 skill，先迁入有效内容再删除。CodeGraph `codegraph_explore` 提供 freshness 入口及消费者索引；无关同名符号不作为证据，补充定向读取实际 evaluator、snapshot、卡片/总览、probe、完整性查询、迁移及测试。未运行数据库测试、生产任务、部署或前端构建。

校验结果：三份主体从 683 行收敛为一份 104 行，减少 579 行；重要信息去向见上表。五类 Policy、2/14/31 天阈值及 7 天默认值与代码静态对账通过，snapshot 模型未含 Policy/cadence 字段；六份承接及引用文档的 284 个唯一链接文件目标、三个新增锚点和九个测试路径有效。旧文件名在仓库引用扫描中仅剩本节追溯表；文档完整性三个检查组、差异检查通过。这些不替代运行验收。README 中其他任务条目及其余无关改动保留。

<a id="ops-taskrun-consolidation-20260909"></a>

#### TaskRun 执行与完成后处理：3 份收敛为 2 份

2026-09-09，按用户批准的审计建议，只整理本组三份文档、API 参考及直接索引。合并前全文可从提交 `19a50e62` 恢复；不另建 archive 或跳转空壳，不改代码、配置、数据、部署或依赖边界。

| 原文档（均在 docs/ops） | 处理与有效信息去向 |
| --- | --- |
| `ops-task-run-observability-redesign-plan-v1.md` | 保留路径，改为执行与观测契约；§1–3 保留事实归属、请求/节点/计数和查询边界，§4 保留分页进度，§6–8 保留后处理入口、历史事故及验收/回归要求；完整字段统一归 API §12.2 |
| `ops-task-run-live-unit-eta-display-lld-v1.md` | 有效内容迁入主契约 §2/5/7/8 后删除：成功/失败计数、公式、3 秒轮询与 10 秒采样、当前节点范围、重置与纯浏览器内存、历史验收及回归边界均保留 |
| `ops-task-completion-side-effect-worker-plan-v1.md` | 独立保留为运行契约：三项后处理、条件审计、内存游标、通知与七项配置、CLI/systemd、串行及异常限制、历史待核实验收 |

删除依据：大段重复 DDL/JSON、已完成施工步骤、ASCII 页面草图、过期清表/重置指令和互相矛盾的“当前状态”不再提供独立有效信息。原 M8、长分页、ETA、Worker 的历史验收缺口未自动关闭，旧对象池误清空事故及重建依据保留在主契约 §7。

| 级别 | 原问题 | 本轮纠偏与边界 |
| --- | --- | --- |
| G0 | 主链已迁移，仍留停机、drop/truncate、seed 操作单 | 移除过时指令；保留迁移及 index_series_active 事故证据，不重跑清理，不删除现行状态投影或配置 |
| G1 | API 示例使用 page_size/202 或不存在的响应字段 | 以 route/schema 校准；API §4/12.2 承接字段，纠正 success 的 can_retry 示例 |
| G1 | 每个 unit 建节点、view 返回全部或仅变化节点 | 普通动作一个 dataset_plan，Workflow 按到达步骤建节点；view 前 200 个并返回总数和截断标志 |
| G1 | 后处理仍被写成主任务同步刷新，遗漏条件审计 | 写清当前独立 Worker 的刷新、index_daily 条件审计创建、通知三项责任 |
| G1 | 慢刷新只影响自身、任何失败都推进游标 | 写清串行延迟和摘要构建等未捕获异常；重启不提供三项后处理补做保证 |
| G1 | max-cycles 1 被当成后处理功能验收 | 首轮实际只初始化游标；替身测试不证明真实处理，运行验收需隔离环境及独立授权 |
| G1 | ETA 旧计数语义、剩余量分母、虚构 current_node_id | 成功提交计算吞吐，remaining/rate，按返回的 running 节点定位；不改 API/提交边界 |
| G1 | 历史 job_schedule 为空、不同扩展发布状态混为现状 | 当前为 ops.schedule；保留原日期和待核实事项，不据旧记录自动 seed、部署或结案 |

复核另保留一项实现限制：16 KiB 是 diagnostics 预算，sanitizer 最终 fallback 没有再次检查总字节数；不能宣称任意输入已有硬上限。本轮只如实记录，不扩展为代码修复任务。

采用文档治理与开发准入 skill，先迁移有效信息再删除。CodeGraph `codegraph_explore` 返回少量完成 Worker 测试与较多无关 research 命中；无关命中未作证据，随后定向核对 TaskRun route/schema/query/service/dispatcher/worker、进度与提交适配、完成服务、通知、Settings、CLI/systemd、前端 ETA 及测试。没有运行 Worker、生产任务、数据库回归、安装或通知。

校验结果：三份主体从 2,138 行收敛为两份 230 行，减少 1,908 行；行数不作为删除依据。API 的 21 个响应模型字段清单、七项配置默认值与源码 AST 一致；200 个节点、16 个结果、16 KiB 预算、3/10 秒节奏和五个分页阶段与源码静态对账通过。两份主体的 9 个唯一链接（含锚点）及 27 处源码/测试/入口路径有效，旧 ETA 文件名引用只剩本节追溯表。文档完整性三个检查组及差异检查通过；这些不替代数据库、浏览器或生产运行验收。其他任务的 README 条目及无关工作区修改保留。

<a id="ops-source-probe-consolidation-20260909"></a>

#### 股票分钟与指数日线源站探测：3 份收敛为 2 份

2026-09-09，按用户批准的十项审计建议整理。范围是三份探测文档、已有自动任务/API 契约、README 和指数补漏 LLD 的直接引用；只改文档，不改代码、配置、样本池、数据、依赖边界或生产状态。合并前全文可从提交 `1c7960b2` 恢复，不保留跳转空壳。

| 原文档（均在 docs/ops） | 处理与有效信息去向 |
| --- | --- |
| `ops-stk-mins-remote-source-probe-plan-v1.md` | 保留路径为分钟探测说明；§1–5 保留独立任务范围、freq/样本、日期、请求主链、调用上限及诊断，§6 保留历史样本和回归；删除旧新增步骤、重复配置 JSON 及过时现状 |
| `ops-index-daily-remote-source-probe-plan-v1.md` | 保留路径为指数探测说明；§1–4 保留能力边界、五个样本及 index_daily_raw 依赖、resolver 请求和 TaskRun 日期/filters，§5–6 承接测试与历史证据 |
| `ops-index-daily-remote-source-probe-lld-v1.md` | 有效内容迁入指数说明后删除；日志 schedule_id 迁移及无法恢复的历史归属、70/12 项历史测试、生产验收事项保留；通用日志/日限额/兜底语义归自动任务契约 §3.3 |

API 参考继续保管字段和合法配置示例；自动任务契约继续保管 capability、binding、日志和触发限制。两份专题的样本判定不同，不合成通用探测框架。指数补漏 LLD 只更新被合并文档的引用，不改补漏方案。

| 审计项 | 原问题与影响 | 本轮纠偏 |
| --- | --- | --- |
| G1-1 | 已实现与“当前不支持、待新增”混杂，容易重复开发 | 改为现行说明，历史验收单列，不以旧施工清单发起任务 |
| G0-2 | STK 写非交易日回退最近开市日，会误导触发判断 | 改为上海当天日历核验；休市/缺日历零请求，不回退 |
| G1-3 | 把底层 STK 显式 ts_code 分支当成正常配置 | 区分 API 只接受 freq 与服务仍有显式样本分支，不恢复配置也不误删代码 |
| G1-4 | 默认请求上限写成 3×5=15 | 默认最多 5×5=25 次 connector 调用；区别显式分支和底层重试，不承诺 HTTP 次数或耗时硬上限 |
| G0-5 | 指数纯 probe 示例含 cron/source_key，当前拒绝 | 移除重复错误 JSON，引用 API 参考的空时间、系统来源示例 |
| G1-6 | 前端写死条件并默认回退 freshness，偏离能力模型 | 由后端 capability 提供选项/文案/默认，不重建页面白名单 |
| G1-7 | 已无 Probe 写 API，LLD 仍要求直接创建校验返回 422 | 保留旧写路由 404/405 防回退和 Schedule 正常配置校验 |
| G1-8 | 承诺不存在的错日期样本/source_error，误导排障 | 写清 sample_hits 只有命中记录、异常使用 error；日志成功不等于条件命中 |
| G1-9 | “只创建一次”没有限定规则/调度范围 | 记录按 rule ID 的日限额、重建影响及按 schedule/requested_at 的单向兜底跳过；不夸大为跨重建/并发唯一 |
| G1-10 | 历史样本、生产修复、待验收混合，回归命令过时 | 保留日期及日志归属迁移证据，不自动结案/重跑；移除 Ruff 检查 TSX 等错误命令 |

依据：CodeGraph `codegraph_explore` 用于两类探测入口分析；无关同名命中不作为证据，定向核对当前 service、capability、binding、runtime、scheduler、schema/API/query、前端和测试。源文档读取 doc_id=370/95；本轮只说明代码请求形态和历史证据，没有重新实测 Tushare，也没有执行数据库测试、生产探测、迁移、部署或安装。

以上纠偏无需新增业务决策；若未来恢复 STK 指定股票配置、加强跨规则去重或改变样本池，须作为独立代码需求审计并获准，不能借文档治理实施。历史生产验收状态未独立核实，继续显式保留。

静态校验：三份主体从 1,691 行收敛为两份 156 行，减少 1,535 行；行数不是删除依据。十个有序默认样本、频率/condition/action/fields、显式样本上限与 25/5 次调用上界按源码核对；两条承接 API JSON 满足纯 probe 空时间、无运营 source、动态 point 及 filters 边界。两份主体和共享/API 文档的 41 个唯一链接（含锚点）、主体的 11 处源码/测试/迁移路径有效；旧指数 LLD 名称只剩本节追溯表。文档完整性三个检查组及差异检查通过，不替代真实源站、数据库或生产验收；其他任务的 README 条目与无关改动保留。

<a id="ops-minute-lane-consolidation-20260909"></a>

#### 分钟线执行隔离：方案与 LLD 合并为一份运行说明

2026-09-09，按用户批准的八项审计结论实施。只修改两个主体文档、README、治理记录及存储瘦身方案的直接引用；不改代码、配置、数据、依赖边界或部署行为。合并前全文可从提交 `0a2fa759` 恢复，不保留空壳或第二套历史入口。

| 原文档（均在 docs/ops） | 处理与有效信息去向 |
| --- | --- |
| `ops-stk-mins-dedicated-worker-execution-lane-plan-v1.md` | 保留路径为运行说明；§1–2 保留隔离动机、TaskRun 主链、四车道现状和 workflow 边界，§3–4 保留取消/故障及数据执行边界，§5–7 保留 CLI、服务、人工部署检查、测试与历史证据 |
| `ops-minute-datasets-dedicated-worker-execution-lane-lld-v1.md` | 有效内容迁入上述说明后删除；五处车道校验、原子 claim、NULL resource、错误车道、命令默认值、精确权限、D1/D2 与历史验收均有承接 |

| 审计项 | 本轮处理 |
| --- | --- |
| G0-1：排队取消被误写成必须等 worker | 按当前 command service 写明 queued 直接 canceled；worker 仅补充处理仍为 queued 且带取消标记的记录 |
| G1-2：通用车道范围过时 | 补上 QTF 排除，不将旧三车道项目范围写成当前全系统清单 |
| G1-3：已实现/未实现及生产验收混杂 | 删除旧新增步骤；保留 2026-08-20 的 TaskRun 8752、29,430 units、约 298 分钟和 M5/M6 历史未验收状态，本次不推断生产现状 |
| G0-4：回滚范围矛盾且无现行开关 | 删除无目标版本的“通用全量领取”操作清单；说明正常故障处理、数据保留和代码回退需独立审核 |
| G1-5：部署时序与自动保护误导 | 区分 Foundation 与 Ops-only 的真实顺序、unit 同步与重启；保留人工等待自然结束要求，不宣称脚本已有自动/原子门禁 |
| G1-6：CLI 边界模糊 | 标明单轮命令会执行和写入、limit 非并发/max-cycles 非超时、专用命令无 auto-reconcile-limit；Session 按轮而非按任务创建 |
| G1-7：测试证据被夸大 | 区分同 Session 顺序 claim、模拟 CLI、部署静态断言与真实多进程/生产验收；不自动启动补测或代码改造 |
| G2-8：重复内容与旧装配示例 | 删除重复里程碑、伪代码和施工清单；现行工厂/执行器等通过源码链接定位，通用状态与后处理引用已整合契约 |

CodeGraph `codegraph_explore` 用于 worker 工厂、车道函数及调用路径分析；无关同名命中不作证据。当前代码核验覆盖 worker 五个过滤位置、取消 API/service、dispatcher/workflow、CLI/handler、工厂、DatasetDefinition/执行器、进程内 limiter、systemd/部署/sudoers 及测试。没有执行真实 worker、数据库集成测试、Tushare 请求、生产操作或安装；本批不改变现行 API/CLI。

校验：无数据库的车道、workflow 护栏及模拟 CLI 定向测试 11 项通过、12 项未选中；文档完整性三个检查组、Shell 语法、差异和合并引用检查通过。两份主体原为 866 行，精简不以行数为删除依据；README 的其他任务条目与无关工作区改动保留。

<a id="ops-index-completeness-consolidation-20260909"></a>

#### 指数日线完整性与补漏：4 份收敛为 1 份

2026-09-09，按用户批准的八项审计建议整理。只修改本组四份主体、README、API 参考中的日期说明及本记录；不改代码、配置、池、数据、依赖边界或生产状态。旧全文可从提交 `378ed9f6` 恢复，不留历史空壳。

| 原文档（均在 docs/ops） | 处理与有效内容去向 |
| --- | --- |
| `ops-index-daily-completeness-reconciliation-plan-v2.md` | 保留路径，改为现行机制说明；§1–2 保存事实归属及入口，§3–4 保存阶段、选择与 TaskRun，§5–7 保存页面、限制、验收和历史证据 |
| `ops-index-daily-completeness-reconciliation-lld-v2.md` | 迁入后删除；两种时钟、阶段派生、再审计条件、空阶段分支、分类／准入、消费者及原生产验收事项均承接；通用字段归 API 参考 |
| `ops-index-daily-completeness-repair-plan-v1.md` | 迁入后删除；请求池／Serving 池区别、标准维护、人工改池边界、集合完整性归 §1/4/5/7；不保留过时晚间 cron 施工单 |
| `ops-index-daily-completeness-repair-lld-v1.md` | 迁入后删除；矩阵与股票边界、5,000 明细预算、全差集重算、100×20 批次、系统补漏 label、后处理及测试归 §1/2/4/6/7 |

| 审计项 | 纠偏落点 |
| --- | --- |
| 1：已实现／旧根因／验收混杂 | 主说明区分代码现状与 §7 历史；删除重复里程碑和待新增步骤，不自动认定生产验收完成 |
| 2：投影缺口是否入选前后矛盾 | §4 区分 repair 可以处理与 scheduler 不由它单独驱动，保留现行能力 |
| 3：3 日窗口差一天 | §3 写明含目标日及前两个开市日，不扩大代码策略 |
| 4：三阶段覆盖范围和时钟混淆 | §2–4 区分系统／手动／配置式审计，阶段按 requested_at、目标资格按执行日；空阶段仍共用分类事实 |
| 5：补漏成功立即再审计的假闭环 | §2 流程不画无条件回环，§6 保留最终审计可能未更新及去重边界 |
| 6：异常隔离承诺过强 | §6 写明逐任务提交、worker 捕获范围和 scheduler 异常传播，不伪称批次原子或循环必然继续 |
| 7：数量相等代替集合完整 | §7 改为 active－目标日 Serving 差集为空，不误判不同代码或历史多余行 |
| 8：页面原因示例及日期含义错误 | §5 校准内部原因／公开状态／参考日／存在性状态；API §8 同步日期说明并链接准入规则 |

删除的是重复实现草图、旧晚间循环、未落地的 `run_once_detailed()`、过时 payload 与执行命令，不是现行配置式审计、手动维护或投影补漏。三阶段上限、最终审计、scheduler 异常和并发去重的实现限制只记录；是否改造另行决定。

按文档治理 skill 先核对承接内容再删除。前轮 CodeGraph explore/search/node 用于入口定位；本轮 callers 未找到类调用方，不把空结果当作无依赖证据，继续以已核对的源码及测试为准。证据覆盖 completion、日期审计 worker、repair、reconciliation、policy、分类服务、scheduler/CLI、planner/writer、review API/query/command、前端及测试定义。未运行数据库测试、生产任务、浏览器构建、部署或安装。

校验：四份主体从 2,207 行收敛为一份 143 行；行数不是删除依据，重要信息去向见上表。24 个唯一链接／锚点、15 个测试路径有效；7 个策略值及 6 个基础 payload 字段与源码 AST 一致。旧文件名全仓引用只剩本节追溯表；文档完整性三个检查组及差异检查通过。这些不是运行或生产验收。README 的其他任务条目与无关工作区改动保留。

<a id="ops-date-completeness-consolidation-20260909"></a>

#### 日期完整性与对象矩阵：3 份收敛为 1 份

2026-09-09：按管理员确认，只合并日期完整性审计文档及直接引用，不修改审计实现、对象池、API、CLI 或生产状态。以当前代码校准主说明；性能目标和历史验收不冒充已实现能力。

| 原文 | 保留信息与去向 |
| --- | --- |
| `dataset-date-completeness-audit-design-v2.md` | 保留路径，改为现行说明；§1–2 承接独立审计边界、日期／过滤／长假排除／范围口径，§4–6 承接模型职责、API、调度、CLI、页面，§7–8 保留历史验收与测试入口 |
| `dataset-subject-completeness-audit-plan-v1.html` | 有效内容迁入后删除；§3 承接六项矩阵、池语义、计数、明细预算与例外边界，§7 保留 run 27／28 及未解释缺口；不保留重复 HTML 样式、DDL 和已过时分期施工步骤 |
| `date-subject-matrix-audit-performance-optimization-plan-v1.md` | 有效内容迁入后删除；§4 承接逐桶 SQL、提交／心跳、400 桶及 60 秒语句限制，§7 保留 run 29 事故、五项历史 EXPLAIN、索引成本与备选对象池边界；删除重复执行器草图和过期命令 |
| `frontend-date-completeness-audit-page-design-v1.md` | 只补第一期历史标记和现行说明入口；正文交互历史保留，不把“仅日期桶”继续当成当前承诺 |

九项问题对账：

| 问题 | 本轮处理 |
| --- | --- |
| 1：独立审计被误写为禁止 Snapshot／TaskRun 交互 | §1 区分专用运行模型、规则列表范围展示和指数补漏后处理 |
| 2：只有日期桶／五项股票／全量旧名单 | §1/3 改为注册表 94/52/42 的日期快照与六项矩阵，不复制全量目录 |
| 3：取消、杀进程和恢复承诺超过代码 | §4 写明没有取消 API、遗留 running 不接管、同 run 重算不等于断点续跑，以及领取并发限制 |
| 4：API id、分页和筛选错误 | §5 按路由／schema 写 id、limit/offset，删除不存在的日期筛选与 page/page_size |
| 5：规则快照和日历边界说过头 | §4 保留“未冻结完整 completeness／对象池”的真实限制；§5 纠正上轮审计：正常创建／更新拒绝自定义交易所，不能将底层预留分支认定为已开放能力或现行跨市场故障 |
| 6：提交频次、每桶预算互相矛盾 | §3–4 写明每桶开始／完成提交、全 run 5,000 明细、摘要受剩余预算影响，无独立每桶明细预算 |
| 7：详情持续刷新承诺不符页面 | §6 区分列表轮询、选中记录快照、非轮询缺口请求、首批 200 条和额外日期数量估算 |
| 8：阶段状态、历史测量与性能目标混杂 | §7 保留事故和 M3 历史测量，说明 400 桶已在代码中，年度优化后耗时／原远程验收未独立核实；不凭旧里程碑补写已完成 |
| 9：stk_limit 仍被写成旧 Serving 审计目标 | §3 改为当前 Raw，§7 明确旧 Serving 性能记录不迁名为新目标实测 |

原“推荐 10 个交易日／6 个月”、每桶明细限制、未来池物化等提议不升级为当前默认值；未采用的细节从合并前提交 `1fa6dd1a` 追溯。删除两份文件可通过该提交恢复。主说明保留真实风险，不自动开启代码改造或新增性能门禁。

按文档治理 skill 先迁移有效信息再删除；前轮 CodeGraph explore 与本轮 search 定位执行器，补查创建／更新校验、SQL、提交、模型、路由、注册表及页面消费者，不以符号命名作证据。未运行数据库测试、审计 worker、调度、浏览器构建、部署或安装。

校验：三份主体从 2,658 行收敛为一份 192 行；行数不是删除依据，重要内容按上表承接。22 个本地链接／锚点有效；请求／创建响应字段、16 条路由、矩阵常量、日历范围与六项矩阵目标按源码静态对账通过，注册表计数为 94/52/42。旧文件名在引用扫描中只剩本节追溯表；文档完整性三个检查组与差异检查通过。这些不替代数据库或生产运行验收。README 的其他任务条目及无关工作区改动保留。

<a id="ops-review-reconcile-consolidation-20260909"></a>

#### 审查中心与多源对账：分别精简，保留两份入口

2026-09-09：按管理员确认，审查中心与多源字段对账职责不同，不硬合并。两份主文档保留原路径；本轮仅修改文档及直接引用，不修改页面、API、CLI、对象池、业务数据或架构边界。

| 原内容 | 处理及信息去向 |
| --- | --- |
| 审查中心旧只读 V1 与“下一轮”激活池升级 | 合并为现行说明 §1–2；区分板块只读、指数改池和有运行状态的数据集审计，移除重复阶段／施工步骤 |
| 指数准入、供数状态和补漏细节 | 复用指数日线专题 §5；审查中心保留页面要点、记录存在性、确认操作、池写入边界及未实施编辑／详情设想 |
| 板块表、过滤、计数、聚合与 UI | 审查中心 §3–4 保留 THS 当前／DC 日期边界、来源＋代码去重、股票级分页、名称回退；纠正数据库列名被当成 API 字段、HAVING 固定要求和展开行草图 |
| API 细节 | 归 API 参考；补激活池 summary，完整列出其五个字段及三组板块响应，保留旧板块小节编号以免破坏锚点 |
| 股票基础对账原待实现清单 | 对账说明 §1–2/5 改为真实 CLI、标准层来源、归一化、计数、样例与已有测试；标明默认阈值关闭、空输入不拦截、输出样例上限不限制全量读取 |
| 已存在但未列入的资金流对账 | 对账说明 §3 补入口并引用资金流专题，不在两处复制容差算法 |
| 多源平台完整形态 | 对账说明 §4 保留五类对象需求、调度／页面／人工纠偏与数据集扩展方向；未实施、不擅自取消，也不变成现行表结构或开发排期 |

九项审计发现按上表处理：过期阶段与只读矛盾、完整性含义、候选准入缺漏、API／UI 漂移、跨源去重歧义、对账实现状态、读取来源、默认退出码和资金流入口缺漏。无新增业务拍板项；是否新增空输入门禁、改池字段或统一对账平台，仍需独立确认。

按文档治理 skill 保留有效规则再精简；前轮 CodeGraph explore 与本轮 search 定位查询／对账服务，结合路由、schema、命令处理、页面和测试核对。前轮 frontend-qa 静态审计只作消费链证据，不宣称浏览器验收。旧全文从 `39d957f4` 追溯；不删除任何文件，README 及当前契约同步入口说明，其他任务修改保留。

校验：两份主体从 735 行精简为 144 行，重要信息去向见上表，不以行数决定删除。23 个唯一链接／锚点、9 组完整响应字段、9 条审查接口路径及 CLI 样例上限／三项阈值默认值静态对账通过；三个无数据库依赖的对账测试、文档完整性三个检查组及差异检查通过。未进行生产查询、真实源站对账、浏览器构建／验收、部署或安装。

<a id="ops-realtime-consolidation-20260909"></a>

#### 实时流监控与配置中心：4 份收敛为 2 份

2026-09-09，按用户确认的八项审计建议实施。现行入口为[监控说明](/Users/congming/github/goldenshare/docs/ops/ops-realtime-market-data-page-design-v1.md)和[配置中心说明](/Users/congming/github/goldenshare/docs/ops/ops-realtime-config-center-technical-plan-v1.md)。只修改文档、索引及五份架构文档中的直接引用/相邻重复口径，不修改代码、配置、服务、数据或依赖矩阵。

下表旧文件名仅作追溯，原文均可从合并前提交 `ac8b3abd` 恢复，不保留空壳或并行原型。

| 原文档（均在 docs/ops） | 处理与有效内容去向 |
| --- | --- |
| `ops-realtime-market-data-page-design-v1.html` | 删除；页面职责、三组接口、刷新、状态/字段及回归入口归监控 Markdown §1–5；移除静态指标与样式 |
| `ops-realtime-config-center-technical-plan-v1.html` | 删除；配置来源、完整白名单、API、发布/版本上报、重启、交互与消费者归配置 Markdown §1–6 |
| `ops-realtime-config-center-m1-consumer-audit-v1.md` | 删除；有效消费者与测试入口归配置 §6；迁移版本、M1–M8 结论及六月验证摘要归 §7，旧 env 逐项映射和完成阶段不再重复维护 |
| `ops-realtime-config-center-showcase-v1.html` | 删除；查看/编辑分离、频率多选、锁定项及发布要求归配置 §5；固定通过的 mock 校验和不存在的保存草稿流程不冒充实际能力 |

纠偏覆盖：遗漏 ETF health、休市与异常状态混淆、配置 API 读取 Redis/受控重启的边界、启动加载与每轮上报混淆、字段及样例不全、有限确认轮询与缺失超时提示、旧 env/待拍板/历史运行状态混排、旧原型被当最新交互依据。`effective_config` 表示已发布配置，不能代替 collector 的已应用状态；旧超时提示目标注明未实现，不因精简被宣称完成或自动进入代码改造。

原监控/配置四份共 4,041 行，迁入有效规则后两份正文共 211 行，删除的是 HTML 样式和冗余记录，不以行数决定去留。使用文档治理 skill 与 CodeGraph `codegraph_explore`，结合前轮页面/测试静态审计和本轮针对性代码复核；图工具的无关符号与“未找到测试”提示不作为实际覆盖结论。未重新验证生产启停、部署、源接口或浏览器，也未推进独立按需查询、ETF 分钟或暂缓的异动监控重构。

校验：三对象 9/11/10 项编辑字段及全部 seed 默认值与 AST 静态提取结果一致，6 条配置路由和 3 条健康路由匹配；涉及文档的 260 个唯一仓库链接存在，新增治理锚点存在。文档完整性三个检查组、`git diff --check` 通过；旧文件名仅存本节追溯表，无活跃引用。未运行应用测试、安装、生产操作；README 与其他目录的无关改动保留。

<a id="ops-hdd-history-consolidation-20260910"></a>

#### HDD 迁移历史：2 份收敛为 1 份

2026-09-10：分钟线与筹码分布历史迁移合并为[生产 PostgreSQL HDD 历史迁移记录](/Users/congming/github/goldenshare/docs/ops/prod-postgresql-hdd-migration-history-v1.md)，保留时间、对象、验收结果、表空间名称与目录映射；旧施工、回迁命令和年度审计 SQL 不再作为当前操作入口。

| 已移除原文档（Git 历史可查） | 内容去向 |
| --- | --- |
| `docs/ops/stk-mins-tablespace-layout-v1.md` | 新记录 §2：192 个分区、576 个索引等 4 月证据；区分次日瘦身与后续滚动规则 |
| `docs/ops/prod-cyq-chips-hdd-tablespace-migration-plan-v1.md` | 新记录 §3：6 月表空间改名、四对象迁移、约 32G 空间释放及最小读验证 |

原全文可在提交 `c6bb2ec4` 中追溯。主索引、存储治理专项与分钟线滚动方案的引用同步迁移。后两份方案仅改引用，不改 P0 白名单、No-Go 门禁、恢复要求或执行授权；本轮没有数据库与物理数据操作。

### 4.3 Datasets 组

当前状态：已完成第一轮整合（拍板结论回填并下线总览拍板单）。

1. `moneyflow-ths/moneyflow-dc/moneyflow-cnt-ths/moneyflow-ind-ths/moneyflow-ind-dc/moneyflow-mkt-dc` 六份开发文档

整合建议：

1. 后续只维护六份正式开发文档，不再保留独立拍板汇总单。
2. 同类“临时拍板文档”采用同样策略：拍板完成后回填正式文档并下线临时文档。

附加项：

1. 当前数据集事实源应收敛到 `src/foundation/datasets/**` 的 `DatasetDefinition` 投影。
2. 后续若重建数据集目录，应从 DatasetDefinition 生成。

<a id="index-period-docs-consolidation-20260910"></a>

#### 2026-09-10 指数分层与股票周期线说明整合

本批按当前代码审计后合并，减少两个独立文档，不修改代码、对象池、数据库或生产任务。

| 原文档 | 处理与去向 |
| --- | --- |
| `docs/datasets/index-series-active-sync-mechanism.md` | 保留为[指数统一说明](/Users/congming/github/goldenshare/docs/datasets/index-series-active-sync-mechanism.md)：分层与两种池、请求/事务、周线差异、月线硬口径、来源统计、历史证据与测试 |
| `docs/datasets/index-raw-serving-layer-alignment-plan-v1.md` | 删除；有效分层规则并入统一说明 §1–2，月线修复规则与验收矩阵并入 §4，事故与开发记录并入 §6；旧实施步骤和清表重建清单退出当前指引 |
| `docs/datasets/equity-weekly-monthly-sync-logic.md` | 删除；接口映射、固定频率、日期字段区别、源文档和现有测试入口并入[日期指南 §4](/Users/congming/github/goldenshare/docs/architecture/dataset-date-model-consumer-guide-v1.md#period-anchors)；不重复维护通用执行链 |

纠偏：请求池与 Serving 池不混用；来源统计是日期范围内当前 Serving 全部指数构成，不是本次任务写入；周线保留截断周和分支差异，不能套用月线保护；Raw 不等于原始响应逐行存档。月线 2026-09-04 开发与生产验收状态分开，本次没有重新确认生产状态，也不新增部署/重跑授权。

同步主索引、Datasets 必读链接、日期指南与源请求阅读指南。原全文可在提交 `bdc6522f` 中追溯；历史事故、251 项开发回归等原证据与本次 24 项离线定向回归明确分列，不把文档精简当作数据修复或代码问题结案。

<a id="dataset-field-repairs-consolidation-20260910"></a>

#### 2026-09-10 指数基础信息与板块日线修复文档整合

三份旧修复方案收敛为两份现行说明，仅改文档与索引，不改代码、合同、依赖矩阵或生产状态。

| 原文档 | 处理与去向 |
| --- | --- |
| `docs/datasets/index-basic-source-alignment-fix-plan-v1.md` | 原路径保留为[指数基础信息维护说明](/Users/congming/github/goldenshare/docs/datasets/index-basic-source-alignment-fix-plan-v1.md)：修正已实现字段仍写缺失、Raw 索引、index_weight 回退与旧验收对象；market 来源冲突单列，不改现行参数 |
| `docs/datasets/dc-daily-category-identity-fix-plan-v1.md` | 删除；完整三字段身份、分类缺失拒绝、216 组历史碰撞证据及后续 Serving 视图切换，合入[板块日线说明](/Users/congming/github/goldenshare/docs/datasets/board-daily-fields-and-storage.md) §1–2、§4–5 |
| `docs/datasets/ths-daily-valuation-fields-rebuild-plan-v1.md` | 删除；估值可空、两层模型与两字段主键、历史迁移及验证边界合入同一说明 §1、§3–5；旧 Console 白名单/Parquet 验收与分区清理步骤退出当前指引 |

保留历史迁移链接，删除重复字段表、待开发清单和过期清表操作指令。旧全文在 Git 提交 `b8811098` 可追溯；清退 LLD 历史矩阵中保留的 THS 旧路径是当时处理对象，不是当前文档入口。

依据：当前 Definition、builder、planner、DAO、normalizer/writer、ORM、迁移与定向测试；CodeGraph status/query/impact 用于确认有效指数 DAO 到 index_weight 的影响面。DC 2026-08-28/29 生产记录与本轮代码核对分列，不将 THS/index_basic 的已有字段外推为全历史补齐。本轮不请求 Tushare、不执行迁移、同步或物理清理；market 不传值的全集覆盖仍需独立实测，旧重建批准不复用为新授权。

本批验证：上述三个数据集的定向离线测试加 writer 日期转换用例共 18 项通过（210 项未选）；文档完整性三个检查组及 `git diff --check` 通过。三份正文原 742 行，合并后两份共 160 行，减少 582 行。旧文件名仅留在合并去向表与清退历史矩阵，不保留失效的现行导航链接。

<a id="stk-factor-docs-consolidation-20260910"></a>

#### 2026-09-10 股票技术面因子三份说明整合

本批仅整理 `stk_factor_pro` 文档和直接索引，三份收敛为一份；不改代码、字段、依赖矩阵、配置或生产数据。

| 原文档 | 处理与去向 |
| --- | --- |
| `docs/datasets/stk-factor-pro-dataset-development.md` | 保留为[统一维护说明](/Users/congming/github/goldenshare/docs/datasets/stk-factor-pro-dataset-development.md)，以 Definition 为字段依据，描述真实输入、存储、工作流与验证边界 |
| `docs/datasets/stk-factor-pro-adj-factor-driven-refresh-plan-v1.md` | 删除；变化判定、交易日历、Raw 历史起点、例外与不先删规则合入 §2–4；按 unit 提交和既有重跑限制合入 §5，原“不做续跑”不再作为现行长任务门禁的豁免 |
| `docs/datasets/stk-factor-pro-raw-view-adj-factor-gate-plan-v1.md` | 删除；存在性门禁、Raw-only/view 及仍保留的 DAO/target 元数据合入 §3–4；迁移和验证合入 §6；整表 TRUNCATE 操作指引退出维护 |

纠偏：字段数旧写 227，本轮 Definition 实读 261，正文不再维护数量常量；复权门禁只检查目标日至少一行，不保证全市场或指定股票齐备；历史 units 在本次写入前规划，不是当天落库后再发现变化；已提交 unit 与未提交写入分开；区间缺复权因子可导致规划失败，删除“早于可用起点一定只提示”的承诺；限速改为带积分条件的本地来源资料，不宣称当前账户配额。

依据：CodeGraph status/query/impact 与当前 planner、builder、Definition、ORM、source client、executor、workflow 和测试。代码现状与生产验收分列，Raw 起点依赖及单 unit 分页全量缓存等限制保留，不扩展为本轮开发任务。旧文档全文可在 Git 提交 `08216be3` 中追溯；本次删除的是重复文档，不是功能或数据。

验证：`stk_factor_pro` 的 resolver、Definition 和 writer 定向离线测试共 11 项通过（156 项未选）；文档完整性检查和 `git diff --check` 通过，含括号的来源文件路径另行核实存在。正文从三份共 500 行收敛为一份 99 行，减少 401 行；旧路径只保留在上述合并去向表。

### 4.4 Frontend 组

当前状态：已完成第一轮整合（建立统一强约束主文档）。

主文档：

1. `frontend-current-standards.md`

专题文档：

1. `frontend-delivery-workflow-v1.md`
2. `frontend-design-tokens-and-component-catalog-v1.md`
3. `frontend-governance-rollout-plan-v1.md`
4. `frontend-phase2-execution-brief-v1.md`

整合建议：

1. `frontend-current-standards.md` 作为唯一强约束源。
2. 治理/流程/token/阶段执行保留专题定位，不复制主约束。

### 4.5 Sources 组

当前状态：已完成第一轮结构化（按源分治 + Tushare 索引化）。

主文档：

1. `docs/sources/README.md`
2. `docs/sources/tushare/README.md`
3. `docs/sources/biying/README.md`

数据索引：

1. `docs/sources/tushare/docs_index.csv`

整合建议：

1. `sources/*` 仅记录源站事实，不承载工程实现决策。
2. Tushare 文档新增/改名必须同步更新 `docs_index.csv`。
3. 数据集开发文档通过 `doc_id + local_path` 引用 source 文档，避免“口口相传”。

---

## 5. 执行规则

1. 每轮只整合一个文档组（Architecture/Ops/Datasets/Frontend），避免扩散。
2. 整合动作必须同步更新 `docs/README.md`。
3. 删除文档前，先确认无代码路径与流程说明依赖。
4. 文档链接必须可达，禁止保留死链。
5. P0/P1 工程风险统一登记到 [工程风险登记簿](/Users/congming/github/goldenshare/docs/governance/engineering-risk-register.md)，避免风险只停留在口头讨论或单次事故复盘里。

文档维护日常基线见：

- [文档维护基线 v1](/Users/congming/github/goldenshare/docs/governance/docs-maintenance-baseline-v1.md)

---

## 6. 第二轮收尾检查（已完成）

1. `docs/*.md` 绝对路径链接检查：无死链。
2. `docs/sources/tushare/docs_index.csv` 与本地 `local_path` 一致性检查：无缺失文件。
3. 噪音文件清理：已移除 `docs/**/.DS_Store`。

后续新增源文档时，建议继续执行以上三项检查再提交。

推荐命令：

```bash
python3 scripts/check_docs_integrity.py
```
