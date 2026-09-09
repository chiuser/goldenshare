# 文档信息架构与待整合清单 v1

更新时间：2026-09-09（补充 Ops 手动维护文档整合记录）

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

### 4.3 Datasets 组

当前状态：已完成第一轮整合（拍板结论回填并下线总览拍板单）。

1. `moneyflow-ths/moneyflow-dc/moneyflow-cnt-ths/moneyflow-ind-ths/moneyflow-ind-dc/moneyflow-mkt-dc` 六份开发文档

整合建议：

1. 后续只维护六份正式开发文档，不再保留独立拍板汇总单。
2. 同类“临时拍板文档”采用同样策略：拍板完成后回填正式文档并下线临时文档。

附加项：

1. 当前数据集事实源应收敛到 `src/foundation/datasets/**` 的 `DatasetDefinition` 投影。
2. 后续若重建数据集目录，应从 DatasetDefinition 生成。

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
