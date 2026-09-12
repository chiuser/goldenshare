# 前端 Phase 6 推广记录与后续边界

状态：第一轮推广已完成；本文是历史收口说明，不是新页面改造授权。2026-09-12 合并执行计划与四份边界卡。
现行视觉规则见[前端基线](/Users/congming/github/goldenshare/docs/frontend/frontend-current-standards.md)，验证方法见[回归与截图流程](/Users/congming/github/goldenshare/docs/frontend/frontend-regression-and-baseline-workflow-v1.md)。

## 1. 历史目标与范围

2026-04-23 的起点记录为 Phase1 治理骨架、Phase2 主题/token、Phase3 组件、Phase4 任务中心试点、Phase5 门禁均已建立。Phase6 推广已验证模式，不重做任务中心，不新建 UI 体系，不改后端/API、路由、搜索参数、业务按钮或账号流程，不以视觉统一扩大到业务重构。

| 批次 | 当时页面范围（frontend/src/pages） | 主要收敛与允许复用 |
| --- | --- | --- |
| P6-1 | platform-check-page.tsx、user-overview-page.tsx | PageHeader、SectionCard、StatCard、StatusBadge、EmptyState；允许连同 status-badge.tsx 及其测试作最小状态映射修正 |
| P6-2 | ops-v21-review-index-page.tsx、ops-v21-review-board-page.tsx | PageHeader、FilterBar、TableShell、StatusBadge、EmptyState、OpsTable；旧 violet provider tone 退出，审查规则与 tab 不改 |
| P6-3 | ops-v21-source-page.tsx、ops-v21-dataset-detail-page.tsx | SectionCard、StatusBadge、MetricPanel、DataTable、EmptyState，已有 PriceText/ChangeText；数据卡片、详情卡面、近期执行记录收敛 |
| P6-4 | ops-v21-account-page.tsx | AlertBar、StatusBadge、TableShell、DetailDrawer、SectionCard；用户/邀请码列表、编辑与重置动作展示收敛，不拆账号业务 |

P6-0 只确认范围、组件与边界卡；P6-1→P6-4 分批实施；P6-5 只汇总结果和遗留，不新增页面任务。原执行计划称“8 页”，但保留下来的四批明细列出 7 个文件，总结另提旧数据源桥接页后续下线；不能据此补造第 8 个页面，也不把历史文件清单当作当前路由全集。

共同边界：只做局部展示，不引入复杂状态管理、新领域组件或为单页扩新抽象；不向相邻批次扩散。测试围绕各实际页面，P6-2 可修改 smoke fixtures/spec/截图；P6-3 仅在明确纳入 smoke 后允许进入这些文件。后续任务必须重新确定实际文件白名单，不能复用已完成批次授权。

## 2. 当时结果与验收口径

原收口记录确认四批完成：高可见页面进入统一组件模式，审查中心获得 smoke 保护，账号反馈/状态/列表/抽屉收敛。P6-3、P6-4 已补页级测试，当时评估暂不新增 smoke，避免扩成大规模 fixture 工程；这不是永久豁免。

当时每批基础门禁是 typecheck、check:rules、test、build；P6-2 另跑 smoke，P6-1 按高可见截图影响评估，P6-3/P6-4 按纳入范围评估。预期视觉变化才更新截图，并重跑普通 smoke。完成标准包括页面组件口径、无新增旧入口、明确回归记录、无架构回流，不是只看截图。

历史规模证据保留，但不作为今天的数量：

- 原总结：34 个测试文件、67 个测试、11 条视觉基线/9 个页面或关键状态。
- 原计划：review-board 893 行、account 788 行；原总结：task-auto 1618、task-manual 1134、review-board 920、account 851、task-detail 838 行。
- 文件长度、测试数量均会变化，不能据旧数字直接安排重构或宣称当前覆盖完整。

## 3. 2026-09-12 静态复核与未完成边界

1. Overview、user-overview、source 页当前没有直接写 glass-card；不再把它们列作尚未完成的旧类清理。规则脚本仍保留这些文件的白名单，白名单不是实际命中证据。
2. SectionCard、StatCard、AuthPageLayout 仍使用 glass-card；这只是代码中的类名事实，不证明当前页面视觉效果，不能据此自行删除 CSS 或宣布兼容层清零。
3. task-auto 已有独立页级测试；“没有页测”不再是现行结论。smoke 仍是有限代表场景，不等于所有页面/空态/错误态已覆盖。
4. 旧总结提出的大页控厚、兼容样式清理、smoke 扩面仍是不同议题，必须按实际代码与收益单独评审；不因历史建议而自动启动。
5. 本轮没有重跑浏览器或全量前端测试；Phase6 完成记录不等于今天所有页面重新验收通过。

依据：[规则脚本](/Users/congming/github/goldenshare/frontend/scripts/check-rules.mjs)、[smoke spec](/Users/congming/github/goldenshare/frontend/e2e/smoke-visual.spec.ts)、[task-auto 测试](/Users/congming/github/goldenshare/frontend/src/pages/ops-v21-task-auto-tab.test.tsx)、[组件](/Users/congming/github/goldenshare/frontend/src/shared/ui/section-card.tsx)。

## 4. 后续任务如何划界

不默认开启第二轮推广。先明确是页面推广、大页拆分、旧样式清理还是测试扩面，再复核页面、消费者和回归成本，不把三类专项捆绑实施。

原边界卡的有效内容保留为每次任务说明，而不是继续维护四张过期卡：

1. 主目标、非目标、影响文件及允许复用/新增的组件。
2. 默认验证档位、是否触及 smoke、预期截图变化与更新理由。
3. 涉及共享组件时，是否同步组件目录和 HTML Showcase。
4. 回滚边界：先撤局部展示，不动查询/账号逻辑；撤不必要的新增断言不能用来掩盖错误，不靠扩大共享抽象补救失控范围。
5. 一个清晰主目标；不改未获准的后端契约、业务流程或其他页面。

旧执行计划及 P6-1～P6-4 独立卡已合并删除，完整原文从 Git 追溯。本记录不替代新任务的范围确认。
