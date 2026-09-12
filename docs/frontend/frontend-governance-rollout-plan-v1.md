# 前端治理决策、阶段记录与后续边界

更新时间：2026-09-12。适用 `frontend/**`；Phase0–6 是已完成的第一轮治理记录，不是重启推广的授权。本文承接 Phase2、Phase5、Overview 独立边界卡、Phase6 收口和 Ops 事实消费历史审计；原文从 Git 追溯。

现行规则见[统一基线](/Users/congming/github/goldenshare/docs/frontend/frontend-current-standards.md)，任务执行见[交付流程](/Users/congming/github/goldenshare/docs/frontend/frontend-delivery-workflow-v1.md)，测试命令与截图纪律见[回归流程](/Users/congming/github/goldenshare/docs/frontend/frontend-regression-and-baseline-workflow-v1.md)。不改后端、API 或页面业务合同。

## 1. 为什么做这轮治理

原计划针对交付流程、token、共享组件、目录规则、自动化和上下文沉淀不足，采用“治理骨架 → 主题 → 组件 → 任务中心试点 → 门禁 → 推广”。这些是当时的问题，不能继续写成今天全部缺失。

五项已确认设计决策由[组件目录 §12](/Users/congming/github/goldenshare/docs/frontend/frontend-design-tokens-and-component-catalog-v1.md#12-已确认基线)维护：渐进切换、亮色、桌面宽度、红涨绿跌、保留但克制的品牌头部。暗色正式支持、全面 Storybook、目录迁移、将全部设计规则升级为硬门禁均未自动获准。

## 2. 阶段与里程碑记录

以下完成状态沿用原计划与 2026-04-20/23 阶段记录，不代表本轮重新完成浏览器或生产验收。

| 阶段 | 历史范围与结果 |
| --- | --- |
| Phase0 | 计划、范围、节奏、风险与评审基线形成 |
| Phase1 | AGENTS、交付流程、组件目录形成，M1 达成 |
| Phase2 | theme.ts 与 styles.css 收敛主 token，中性灰/深海军蓝及低阴影方向建立，M2 达成；独有执行边界见 §3 |
| Phase3 | PageHeader、SectionCard、StatusBadge、StatCard、FilterBar、TableShell、EmptyState、AlertBar、DetailDrawer、ActivityTimeline；领域最小版本 PriceText、ChangeText、TradeDateField；M3 达成 |
| 上下文分层 | app、shared/ui、shared/api、features、pages 的目录规则建立，M3.5 达成 |
| Phase4 | DataTable v1、TradeDateField v2 支持任务及 records → manual → auto → detail 试点完成，M4 达成；边界见 §4 |
| Phase5 | P5-0 文档同步 → P5-1 门禁盘点 → P5-2 smoke 扩面 → P5-3 文本规则 → P5-4 CI → P5-5 回归流程；原 M5 曾记“基础版达成”，后续 Phase5 记录已完成，不能再把深化全部排作待办 |
| Phase6 | 第一轮推广完成、M6 达成；页面范围、测试数字、四批边界及剩余议题见 [Phase6 记录](/Users/congming/github/goldenshare/docs/frontend/frontend-governance-rollout-plan-v1.md#phase6-history) |

原规模快照保留作历史证据：34 个页面/相关文件、28 个测试文件、1 组 smoke；auto 1649 行、manual 1123、review-board 893、task-detail 870、account 788。原总计划列 8 个代表页面，Phase5 起点列 7 个，属于不同盘点记录，不合成为今日覆盖数量。当前 smoke 静态盘点归回归流程，不用旧数字触发重构。

## 3. Phase2 与 Phase5 的有效边界

Phase2 原主文件为 `frontend/src/app/theme.ts`、`frontend/src/styles.css`；仅允许必要联动 shell 与直接消费 token/class 的共享组件。顺序是盘点旧入口 → neutral/brand/up/down/semantic 与间距/圆角/阴影主 token → 全局字体、底色、壳与卡面 → Mantine Button/Badge/NavLink/Card 默认样式 → 最小联动 → 验证记录。

不重做任务中心、API、路由、全站页面或完整暗色，不过早细拆 token。发现必须连带业务重构、全站回归或未确认设计决策时，先停下核实。旧“兼容式替换”仅描述当时渐进样式迁移，不授权今天新增兼容层。

Phase5 只深化既有 CI 和高价值主路径，不新增共享组件群、后端重构、全量 E2E 或第二套 CI/视觉平台。规则优先低歧义、可解释的轻量检查；数字对齐和高可见组件评审等候选不等于全部已自动化。当前实现、命令、截图更新条件统一见回归流程，不再维护独立命令表。

## 4. 试点支持合同与范围

- DataTable v1：沿用 Mantine Table 与 TableShell/OpsTable，不以前置引入 TanStack Table 为目标。原候选包括 columns/rows/loading/emptyState/toolbar/density/stickyHeader；当前组件实际 props 见 [data-table.tsx](/Users/congming/github/goldenshare/frontend/src/shared/ui/data-table.tsx)，包含 getRowKey/getRowProps/summary/tableProps/minWidth，但没有独立 density 或 stickyHeader prop。设计目标不能当成已实现 API。
- 不因文档整合扩展虚拟滚动、列拖拽/重排、列配置中心或页面业务状态。原升级触发条件保留：排序/过滤/显隐明显复杂、多页共享列定义，或数据量与交互成本证明现有实现不足；需另行批准。
- TradeDateField v2：日历读取归 features/trade-calendar，展示组件通过 isTradingDay/holidayDates 注入判断，不自行请求。主要消费者是手动与自动任务；优先 A 股，不扩多市场平台。回调未提供结果时仍回退到周末/holidayDates 判断，不能承诺所有调用都已获得真实日历。
- 周/月交易日选择与自然日期控件语义分开；前者为周/月最后交易日，后者保留有说明的自然周五用途，不做 week_friday 关键词清零。

原试点重构优先级：P0 为阻塞主链/稳定性及必要拆分，P1 为有明确复用或测试收益的结构调整，P2 为弱相关美化、壳层重做及广泛 API 改动。每轮明确主目标、非目标、文件、重构权限、回归和回滚边界，不默认并行改全站。

## 5. Overview 独立卡的承接与纠偏

原专项只允许改 Overview 页面；测试范围为其页测与 overview 截图，文档为边界卡和索引。不改 overview/dataset-cards API、页面信息架构、分组/状态计算/详情跳转，不扩 review/source/account，不新建组件族或拆分业务。

2026-09-12 核对 [页面](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-overview-page.tsx)及[页测](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-overview-page.test.tsx)：
- 页面无直接 glass-card，错误/空态采用 AlertBar，配置状态采用中性 Paper 和 StatusBadge；页测已有卡片不带旧类的断言。
- 页面仍有普通 Badge 和局部样式，不能扩大成“所有手写展示均已清零”。旧卡的重做指令退出，不据此授权再次修改。
- 原卡要求更新截图只适用于当时有意视觉调整；后续遵循回归流程，不能无条件刷新。原回滚思路为先撤局部卡面/反馈改动，不动业务结构，不扩共享抽象。
- 本轮静态核对不替代历史截图验收，也不宣称今天所有空态/错误态均已重验。

## 6. 后续如何进入新任务

不默认开启新推广批次。先从真实问题选一个目标：大页控厚、共享样式清理、测试缺口或新业务页面，再明确当前代码和消费者、收益、范围、验收与回滚。Phase6 的建议和本表历史完成状态均不能替代批准。

控制风险的方法仍是缩小页面和组件范围、只抽已确认复用模式、保护业务与接口，不是引入第二套主 UI 或删除已有门禁来赶进度。暂缓新增次级能力不等于关闭已有 CI/smoke。具体需求、状态设计、评审与交付产物只在交付流程维护。

<a id="phase6-history"></a>

## 7. Phase6 推广历史与后续边界

### 7.1. 历史目标与范围

2026-04-23 的起点记录为 Phase1 治理骨架、Phase2 主题/token、Phase3 组件、Phase4 任务中心试点、Phase5 门禁均已建立。Phase6 推广已验证模式，不重做任务中心，不新建 UI 体系，不改后端/API、路由、搜索参数、业务按钮或账号流程，不以视觉统一扩大到业务重构。

| 批次 | 当时页面范围（frontend/src/pages） | 主要收敛与允许复用 |
| --- | --- | --- |
| P6-1 | platform-check-page.tsx、user-overview-page.tsx | PageHeader、SectionCard、StatCard、StatusBadge、EmptyState；允许连同 status-badge.tsx 及其测试作最小状态映射修正 |
| P6-2 | ops-v21-review-index-page.tsx、ops-v21-review-board-page.tsx | PageHeader、FilterBar、TableShell、StatusBadge、EmptyState、OpsTable；旧 violet provider tone 退出，审查规则与 tab 不改 |
| P6-3 | ops-v21-source-page.tsx、ops-v21-dataset-detail-page.tsx | SectionCard、StatusBadge、MetricPanel、DataTable、EmptyState，已有 PriceText/ChangeText；数据卡片、详情卡面、近期执行记录收敛 |
| P6-4 | ops-v21-account-page.tsx | AlertBar、StatusBadge、TableShell、DetailDrawer、SectionCard；用户/邀请码列表、编辑与重置动作展示收敛，不拆账号业务 |

P6-0 只确认范围、组件与边界卡；P6-1→P6-4 分批实施；P6-5 只汇总结果和遗留，不新增页面任务。原执行计划称“8 页”，但保留下来的四批明细列出 7 个文件，总结另提旧数据源桥接页后续下线；不能据此补造第 8 个页面，也不把历史文件清单当作当前路由全集。

共同边界：只做局部展示，不引入复杂状态管理、新领域组件或为单页扩新抽象；不向相邻批次扩散。测试围绕各实际页面，P6-2 可修改 smoke fixtures/spec/截图；P6-3 仅在明确纳入 smoke 后允许进入这些文件。后续任务必须重新确定实际文件白名单，不能复用已完成批次授权。

### 7.2. 当时结果与验收口径

原收口记录确认四批完成：高可见页面进入统一组件模式，审查中心获得 smoke 保护，账号反馈/状态/列表/抽屉收敛。P6-3、P6-4 已补页级测试，当时评估暂不新增 smoke，避免扩成大规模 fixture 工程；这不是永久豁免。

当时每批基础门禁是 typecheck、check:rules、test、build；P6-2 另跑 smoke，P6-1 按高可见截图影响评估，P6-3/P6-4 按纳入范围评估。预期视觉变化才更新截图，并重跑普通 smoke。完成标准包括页面组件口径、无新增旧入口、明确回归记录、无架构回流，不是只看截图。

历史规模证据保留，但不作为今天的数量：

- 原总结：34 个测试文件、67 个测试、11 条视觉基线/9 个页面或关键状态。
- 原计划：review-board 893 行、account 788 行；原总结：task-auto 1618、task-manual 1134、review-board 920、account 851、task-detail 838 行。
- 文件长度、测试数量均会变化，不能据旧数字直接安排重构或宣称当前覆盖完整。

### 7.3. 2026-09-12 静态复核与未完成边界

1. Overview、user-overview、source 页当前没有直接写 glass-card；不再把它们列作尚未完成的旧类清理。规则脚本仍保留这些文件的白名单，白名单不是实际命中证据。
2. SectionCard、StatCard、AuthPageLayout 仍使用 glass-card；这只是代码中的类名事实，不证明当前页面视觉效果，不能据此自行删除 CSS 或宣布兼容层清零。
3. task-auto 已有独立页级测试；“没有页测”不再是现行结论。smoke 仍是有限代表场景，不等于所有页面/空态/错误态已覆盖。
4. 旧总结提出的大页控厚、兼容样式清理、smoke 扩面仍是不同议题，必须按实际代码与收益单独评审；不因历史建议而自动启动。
5. 本轮没有重跑浏览器或全量前端测试；Phase6 完成记录不等于今天所有页面重新验收通过。

依据：[规则脚本](/Users/congming/github/goldenshare/frontend/scripts/check-rules.mjs)、[smoke spec](/Users/congming/github/goldenshare/frontend/e2e/smoke-visual.spec.ts)、[task-auto 测试](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-task-auto-tab.test.tsx)、[组件](/Users/congming/github/goldenshare/frontend/src/shared/ui/section-card.tsx)。

### 7.4. 后续任务如何划界

不默认开启第二轮推广。先明确是页面推广、大页拆分、旧样式清理还是测试扩面，再复核页面、消费者和回归成本，不把三类专项捆绑实施。

原边界卡的有效内容保留为每次任务说明，而不是继续维护四张过期卡：

1. 主目标、非目标、影响文件及允许复用/新增的组件。
2. 默认验证档位、是否触及 smoke、预期截图变化与更新理由。
3. 涉及共享组件时，是否同步组件目录和 HTML Showcase。
4. 回滚边界：先撤局部展示，不动查询/账号逻辑；撤不必要的新增断言不能用来掩盖错误，不靠扩大共享抽象补救失控范围。
5. 一个清晰主目标；不改未获准的后端契约、业务流程或其他页面。

旧执行计划及 P6-1～P6-4 独立卡已合并删除，完整原文从 Git 追溯。本记录不替代新任务的范围确认。

<a id="ops-fact-audit-history"></a>

## 8. Ops 事实消费历史审计

原审计时间：2026-04-26；2026-09-12 补字段口径。以下 F-001～F-008 原表保留为历史，不能用 F-001 的旧日期描述覆盖 §8.3 的后续口径；不是独立 API 合同或新改造授权。

### 8.1. 目的

本文件记录前端 Ops 页面是否仍在自行拼装后端已经定义好的事实字段。

原审计目标不是做视觉优化；只处理一件事：

前端页面只能消费稳定 API 返回的权威字段，不允许为了展示方便在页面层重新推导状态、时间、表名、来源或层级快照。

### 8.2. 原审计边界

范围：

1. `frontend/src/pages/**`
2. `frontend/src/shared/api/types.ts`
3. `src/ops/api/**`、`src/ops/queries/**`、`src/ops/schemas/**` 中面向页面的只读聚合接口
4. 与前端规则检查相关的 `frontend/scripts/check-rules.mjs`

不做：

1. 不新增状态表、字段或影子模型。
2. 不改页面视觉结构。
3. 不把总览页跨来源合并逻辑临时改成另一套前端拼法。
4. 不触碰自动任务页的交互模型，自动任务页另行专项处理。

### 8.3. 权威来源

下表限定为原外部数据集审计范围，当前字段合同以 [Ops API](/Users/congming/github/goldenshare/docs/ops/ops-api-reference-v1.md)及[数据集目录说明](/Users/congming/github/goldenshare/docs/ops/ops-dataset-catalog-view-plan-v1.md)为准。Biz 卡片走 BizDatasetDefinition → BizTableCardQueryService，不能套用“全部来自 DatasetDefinition”；见 [Biz 投影契约](/Users/congming/github/goldenshare/docs/ops/ops-biz-dataset-auto-projection-plan-v1.md)。

| 展示事实 | 前端应消费的权威来源 | 说明 |
| --- | --- | --- |
| 数据集卡片名称 | `/api/v1/ops/dataset-cards` 的 `display_name` | 总览页、数据源页、数据集详情页只做展示，不再根据 key 拼中文名。 |
| 数据集卡片状态 | `/api/v1/ops/dataset-cards` 的 `status/freshness_status` | 页面可以映射颜色和中文标签，但不能重新计算新鲜度或层级健康度。 |
| 观测日期/时间 | dataset-cards 的观测字段 | 当前 source 页先用带 label 的 latest_observed_date，再用 latest_observed_at、latest_business_date，最后才用 last_sync_date；后两类时间可展示 earliest/latest 范围。不是要求始终显示同步日期。 |
| 最近成功/执行中 | dataset-cards 的任务字段 | queued/running/canceling 时显示执行中及 active_task_run_started_at；否则显示 latest_success_at，缺失为 —。标题优先 last_success_label；与观测日期分开，不用 last_sync_date 冒充成功时间。 |
| 数据集健康度 | `/api/v1/ops/dataset-cards` 的 `status/freshness_status` | 总览页、数据源页、数据集详情页不得自行计算健康度。 |
| raw 表名 | `/api/v1/ops/dataset-cards` 的 `raw_table/raw_table_label` | 页面不得根据 `sourceKey + dataset_key` 拼表名。 |
| 数据源裁决与卡片去重 | `/api/v1/ops/dataset-cards?source_key=...` 返回的结果 | 页面不得用 `dataset_key/raw_table/source_scope` 自己判断某卡片属于哪个数据源。 |
| 任务运行状态 | `/api/v1/ops/task-runs*` | 页面不得回退到旧 execution/steps/events/logs 拼装任务状态。 |

### 8.4. 已确认并修复的问题

| 编号 | 页面/文件 | 问题 | 处理 |
| --- | --- | --- | --- |
| F-001 | `ops-v21-source-page.tsx` | “最近同步”曾绕开服务端同步日期口径，导致 `limit_list_ths` 显示 `—`。 | 已修复：数据源卡片页只消费 `/api/v1/ops/dataset-cards` 返回的 `last_sync_date` 与运行状态字段。 |
| F-002 | `ops-v21-dataset-detail-page.tsx` | 页面曾展示旧分层观测信息，导致健康度口径重复。 | 已删除：详情页只消费 `/api/v1/ops/dataset-cards` 返回的健康度、任务、调度和规则信息。 |
| F-003 | 前端详情页共享 helper | 曾保留未使用的 freshness 转 snapshot helper，后续又残留了详情页 display name 映射 helper。 | 已删除：详情页标题与手动动作入口改为消费 `/api/v1/ops/dataset-cards`，不再从 freshness 建本地 map。 |
| F-004 | `ops-v21-source-page.tsx` | 页面用 `sourceKey + dataset_key` 拼 raw 表名，并把 `raw_tushare` 替换成当前来源表名前缀。 | 已删除：表名只来自 `/api/v1/ops/dataset-cards` 返回字段，缺失则显示 `—`。 |
| F-005 | `ops-v21-overview-page.tsx` | 总览页曾直接合并旧模式 API，并在页面层推导分层状态和健康状态。 | 已收口：总览页改为消费 `/api/v1/ops/dataset-cards`。 |
| F-006 | `ops-v21-source-page.tsx` / `ops-v21-source-page-utils.ts` | 数据源页用 `dataset_key/raw_table/source_scope` 做来源偏好评分和去重。 | 已收口：数据源页改为消费 `/api/v1/ops/dataset-cards?source_key=...`，旧 utils 删除。 |
| F-007 | `src/ops/api/dataset_cards.py` | 总览页、数据源页缺少稳定卡片视图，只能在前端拼。 | 已新增只读卡片视图 API；不新增状态表，不复制落盘字段。 |
| F-008 | `src/ops/queries/dataset_card_query_service.py` | 卡片视图内部曾把旧模式查询结果当作静态事实来源。 | 已收口：卡片静态事实从 `DatasetDefinition` 派生，健康度只来自 freshness，probe 只作为调度观测输入。 |

### 8.5. 已加门禁

原审计记录新增三条规则：

1. 禁止页面层重新引入 freshness -> 旧分层观测 的伪造逻辑。
2. 禁止页面层重新引入 raw 表名派生变量。
3. 禁止页面层重新引入数据集卡片来源、canonical key 或旧原始层快照合并推断。

这些规则不是为了覆盖所有未来场景，而是先锁死本轮已经确认的旧口径回流点。

### 8.6. 仍需后续 API 收口的问题

这是原审计的后续方向，不是已批准的新字段清单。G-002 的 DatasetDefinition 限定外部数据集；Biz 使用自身定义。缺口必须对照当前代码及完整消费者后再判断，不因为历史建议直接扩 mode/stage。

| 编号 | 页面/文件 | 现状 | 后续方向 |
| --- | --- | --- | --- |
| G-001 | `ops-v21-task-auto-tab.tsx` | 已切到 `target_type/target_key` 调度目标模型，页面显示继续使用后端结构化名称。 | 后续重做自动任务页交互时，继续从用户视角表达维护对象与触发策略，不恢复旧执行规格。 |
| G-002 | Ops 后端卡片视图 | `/api/v1/ops/dataset-cards` 的卡片静态事实已从 DatasetDefinition 派生；旧模式 API 与旧落库配置主实现已下线。 | 后续如果页面还需要 mode/stage 新字段，先补 DatasetDefinition 派生事实，再暴露到 card view，不能让页面或查询层另起事实口径。 |

### 8.7. 后续执行原则

1. 前端能直接消费权威字段的，直接修。
2. 没有权威字段的，不允许继续在页面层拼；先登记为 API 契约缺口。
3. 每修一个旧消费点，必须补一个最小回归测试或规则门禁。
4. 任何“看起来能根据 key 推出来”的字段，都不能当事实字段使用。

2026-09-12 静态核对证据：source 页 buildObservedText/buildLastSyncText/resolveTableLabel 与 DatasetCardQueryService 的 Biz 分支。Biz 表名使用 target_table，外部卡片优先 raw_table_label，缺失时可展示服务表；不把旧 raw 表名说明套到所有卡片。通用规则门禁与当前检查范围统一见[前端回归流程](/Users/congming/github/goldenshare/docs/frontend/frontend-regression-and-baseline-workflow-v1.md)，本记录不再维护第二份现行规则清单。
