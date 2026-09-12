# 前端治理决策、阶段记录与后续边界

更新时间：2026-09-12。适用 `frontend/**`；Phase0–6 是已完成的第一轮治理记录，不是重启推广的授权。本文承接 Phase2、Phase5 和 Overview 独立边界卡；原文从 Git 追溯。

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
| Phase6 | 第一轮推广完成、M6 达成；页面范围、测试数字、四批边界及剩余议题见 [Phase6 记录](/Users/congming/github/goldenshare/docs/frontend/frontend-phase6-rollout-summary-v1.md) |

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
