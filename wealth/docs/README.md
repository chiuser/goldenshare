# wealth 文档索引

`wealth/docs` 是财势乾坤行情系统前端工程的本地文档基线。

外部 Drive 文档已经按类别归档到 `reference/`。实际编码必须优先读取本目录中的本地资料，避免依赖聊天记录或远程文档记忆。

## 目录分层

```text
docs/
  reference/              # Drive 原始资料本地拷贝与索引
  system/                 # 系统级：工程、设计、组件、开发原则
  templates/              # 模块开发模板（需求/实施/门禁）
  pages/                  # 页面级：页面需求、API contract、实现提示词
    market-overview/
    stock-detail/
    index-detail/
```

## 文档优先级

发生冲突时，按以下顺序处理：

1. 用户最新明确指令。
2. 当前实际页面的 DOM、CSS、共享组件与已验证交互行为。
3. `system/` 下的当前系统基线。
4. `pages/` 下的页面设计、模块三件套和编码门禁。
5. `reference/` 中的 Drive 原始资料。

第 2 项是当前视觉事实源。`reference/` 只保留历史设计意图、原型与评审记录，不能覆盖已落地页面的真实尺寸、布局、组件结构、交互、数据模型或 API 契约。

## Drive 原始资料

- [Drive 原始资料索引](./reference/README.md)
- [市场总览 V4 Showcase 原型（历史视觉参考）](./reference/showcase/market-overview-v4.html)
- [市场总览 V1.1 Showcase 原型（历史视觉参考）](./reference/showcase/market-overview-v1.1.html)
- [Design Token 原始文档 v0.2.7（历史参考）](./reference/design/03-design-tokens-v0.2.7.md)
- [组件规范原始文档 v0.7（历史参考）](./reference/design/04-component-guidelines-v0.7.md)
- [市场总览 API 草案 v0.5（历史参考，不作为实现契约）](./reference/api/market-overview-api-v0.5.md)
- [P0 数据字典 v0.5（历史参考，不作为实现契约）](./reference/api/p0-data-dictionary-v0.5.md)
- [Codex 实现提示词原始文档](./reference/codex/market-overview-codex-prompt-v1.md)
- [Review v2 原始文档](./reference/review/market-overview-html-review-v2.md)

`reference/` 保存从 Drive 拷贝到本地的原始资料，包括历史版本、review、Logo、HTML Showcase、设计文档、API 与数据字典。它用于防止后续开发只依赖聊天记录或远程 Drive 记忆。

注意：`reference/api/**`、旧 Codex prompt、旧产品稿中的 API 路径和字段结构是历史输入材料，不再作为当前工程实现契约。当前 API、数据模型、字段映射、测试门禁以 `system/` 与 `pages/` 下的当前基线和模块三件套为准。

编码前应先读取当前页面实现和系统基线，再按需使用 `reference/` 中的 Showcase、Design Token、组件规范和 review 变更单补足视觉/产品背景。`reference/api/**` 不得直接作为实现依据。

当前页面事实源：

1. 全局 token 与基础工具样式：`../src/styles/design-tokens.css`、`../src/styles/global.css`。
2. 共享顶部栏：`../src/shared/ui/top-market-bar/`。
3. 市场总览：`../src/pages/market-overview/` 与 `../src/features/market-overview/`。
4. 股票详情：`../src/pages/stock-detail/` 与 `../src/features/stock-detail/`。
5. 指数详情：`pages/index-detail/`；M1 后端已在仓库根 `src/biz/**/index_detail` 落地，M2 已在 `../src/shared/charts/detail-workspace/` 提取共享图表，M3 已建立 Loaded 页面、三 Tab 与趋势 primitive，M4 已在 `../src/features/index-detail/state/` 和页面 controller 中完成五态、404、Delayed 与模块级重试。
6. 当前正式视觉与组件规则：[设计系统基线](./system/design-system-baseline.md)、[组件规范基线](./system/component-guidelines-baseline.md)。
7. API/数据字典：以 `pages/market-overview/*-benchmark-requirement-v1.md`、`*-implementation-design-v1.md`、`*-m2-coding-gate-v1.md` 和 `pages/market-overview/api-contract-baseline.md` 为准；`reference/api/*` 仅保留历史参考。

## 系统级文档

- [系统定位基线](./system/wealth-system-baseline.md)
- [工程架构规范](./system/engineering-architecture.md)
- [模块级渐进替换开发规范 v1](./system/module-incremental-delivery-spec-v1.md)
- [模块交付通用清单 v1](./system/module-delivery-checklist-v1.md)
- [财势乾坤行情系统 Design System v1](./system/design-system-baseline.md)
- [财势乾坤行情系统组件规范 v1](./system/component-guidelines-baseline.md)
- [异常码注册表（统一管理）](./system/exception-code-registry.md)
- [策略配置中心 v1（统一策略读取）](./system/strategy-config-center-v1.md)
- [策略配置中心 M1 编码门禁 v1](./system/strategy-config-center-m1-coding-gate-v1.md)
- [策略配置中心一页式接入手册 v1](./system/strategy-config-consumer-guide-v1.md)

## 页面级文档

- [市场总览页面基线](./pages/market-overview/market-overview-baseline.md)
- [市场总览 API 契约基线](./pages/market-overview/api-contract-baseline.md)
- [市场总览 API 与数据模型设计 v1](./pages/market-overview/market-overview-api-model-design-v1.md)
- [今日市场客观总结标杆需求 v1](./pages/market-overview/market-summary-benchmark-requirement-v1.md)
- [今日市场客观总结技术实施方案 v1](./pages/market-overview/market-summary-implementation-design-v1.md)
- [今日市场客观总结 M2 编码前门禁 v1](./pages/market-overview/market-summary-m2-coding-gate-v1.md)
- [榜单标杆需求（前后端贯通）v1](./pages/market-overview/leaderboard-benchmark-requirement-v1.md)
- [榜单标杆技术实施方案 v1（仅方案）](./pages/market-overview/leaderboard-implementation-design-v1.md)
- [榜单 M2 编码前门禁 v1](./pages/market-overview/leaderboard-m2-coding-gate-v1.md)
- [主要指数标杆需求 v1](./pages/market-overview/major-indices-benchmark-requirement-v1.md)
- [主要指数技术实施方案 v1（仅方案）](./pages/market-overview/major-indices-implementation-design-v1.md)
- [主要指数 M2 编码前门禁 v1](./pages/market-overview/major-indices-m2-coding-gate-v1.md)
- [涨跌分布标杆需求 v1](./pages/market-overview/breadth-benchmark-requirement-v1.md)
- [涨跌分布技术实施方案 v1（仅方案）](./pages/market-overview/breadth-implementation-design-v1.md)
- [涨跌分布 M2 编码前门禁 v1](./pages/market-overview/breadth-m2-coding-gate-v1.md)
- [市场风格标杆需求 v1](./pages/market-overview/market-style-benchmark-requirement-v1.md)
- [市场风格技术实施方案 v1（仅方案）](./pages/market-overview/market-style-implementation-design-v1.md)
- [市场风格 M2 编码前门禁 v1](./pages/market-overview/market-style-m2-coding-gate-v1.md)
- [成交额总览标杆需求 v1](./pages/market-overview/turnover-benchmark-requirement-v1.md)
- [成交额总览技术实施方案 v1（仅方案）](./pages/market-overview/turnover-implementation-design-v1.md)
- [成交额总览分钟线快照长期方案 v1（HTML）](./pages/market-overview/turnover-minute-snapshot-plan-v1.html)
- [成交额总览分钟线快照 M2 编码前门禁 v1](./pages/market-overview/turnover-minute-snapshot-m2-coding-gate-v1.md)
- [成交额总览 M2 编码前门禁 v1](./pages/market-overview/turnover-m2-coding-gate-v1.md)
- [大盘资金流向标杆需求 v1](./pages/market-overview/money-flow-benchmark-requirement-v1.md)
- [大盘资金流向技术实施方案 v1（仅方案）](./pages/market-overview/money-flow-implementation-design-v1.md)
- [大盘资金流向 M2 编码前门禁 v1](./pages/market-overview/money-flow-m2-coding-gate-v1.md)
- [新闻速览与个股新闻标杆需求 v1](./pages/market-overview/market-news-benchmark-requirement-v1.md)
- [新闻速览与个股新闻技术实施方案 v1](./pages/market-overview/market-news-implementation-design-v1.md)
- [新闻速览与个股新闻 M2 编码前门禁 v1](./pages/market-overview/market-news-m2-coding-gate-v1.md)
- [市场总览 Codex 实现提示词基线](./pages/market-overview/implementation-prompt-baseline.md)
- [市场总览 homepage 代码架构设计](./pages/market-overview/implementation-architecture-v1.md)
- [市场总览原生 Figma 设计稿还原计划 v1（历史准备稿，不得继续执行）](./pages/market-overview/market-overview-figma-reconstruction-plan-v1.md)
- [市场总览 Figma 像素级还原审计 v1](./pages/market-overview/market-overview-figma-pixel-audit-v1.md)
- [市场总览 Figma 像素级还原执行计划 v2（执行中，M0-M6 已完成，M7 验收持续进行）](./pages/market-overview/market-overview-figma-pixel-reconstruction-plan-v2.md)
- [市场总览 Figma 像素级验收账本 v1](./pages/market-overview/market-overview-figma-pixel-verification-ledger-v1.md)
- [市场总览 Figma 像素级执行运行手册 v1](./pages/market-overview/market-overview-figma-pixel-execution-runbook-v1.md)
- [股票详情页标杆需求 v1](./pages/stock-detail/stock-detail-benchmark-requirement-v1.md)
- [股票详情页技术实施方案 v1](./pages/stock-detail/stock-detail-implementation-design-v1.md)
- [股票详情页 M2 编码前门禁 v1](./pages/stock-detail/stock-detail-m2-coding-gate-v1.md)
- [股票详情分钟线与分钟技术指标 API 标杆需求 v1](./pages/stock-detail/stock-detail-minutes-api-benchmark-requirement-v1.md)
- [股票详情分钟线与分钟技术指标 API 技术实施方案 v1](./pages/stock-detail/stock-detail-minutes-api-implementation-design-v1.md)
- [股票详情分钟线与分钟技术指标 API LLD v1](./pages/stock-detail/stock-detail-minutes-api-low-level-design-v1.md)
- [股票详情分钟线与分钟技术指标 API M2 编码前门禁 v1](./pages/stock-detail/stock-detail-minutes-api-m2-coding-gate-v1.md)
- [股票详情页 Figma 像素级还原执行计划 v1（M0-M7 已完成）](./pages/stock-detail/stock-detail-figma-pixel-reconstruction-plan-v1.md)
- [股票详情页 Figma 像素级验收台账 v1](./pages/stock-detail/stock-detail-figma-pixel-verification-ledger-v1.md)
- [指数详情页标杆需求 v1（M1-M4 完成）](./pages/index-detail/index-detail-benchmark-requirement-v1.md)
- [指数详情页技术实施方案 v1（M1-M4 完成）](./pages/index-detail/index-detail-implementation-design-v1.md)
- [指数详情页低层设计（LLD）v1（M1-M4 完成）](./pages/index-detail/index-detail-low-level-design-v1.md)
- [指数详情页正式 API / DTO 合同 v1（1.1.0 已冻结）](./pages/index-detail/index-detail-api-contract-v1.md)
- [指数详情页 M0 生产因子审计 v1](./pages/index-detail/index-detail-m0-production-audit-v1.md)
- [指数详情页 M2 编码前门禁 v1（M1-M4 条目通过，后续里程碑受控）](./pages/index-detail/index-detail-m2-coding-gate-v1.md)

## 模块开发模板

- [标杆需求模板](./templates/benchmark-requirement-template.md)
- [技术实施方案模板](./templates/implementation-design-template.md)
- [编码前门禁模板](./templates/coding-gate-template.md)

## 维护规则

1. 系统级规则写入 `system/`。
2. 单页面需求、API、验收写入 `pages/<page-key>/`。
3. 不要把系统级规则和页面级细节混在同一个文档。
4. Drive 文档更新后，必须同步更新本地基线，不允许代码实现与本地文档脱节。
5. 本目录文档只服务 `wealth` 工程，不替代仓库根 `docs/` 的数据基座与 ops 文档。
6. 新模块开发必须先按 templates 产出三件套文档（benchmark requirement / implementation design / coding gate），评审通过后才能进入编码。
