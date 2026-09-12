# 前端技术选型历史决策记录

更新时间：2026-09-12。保留最初选型的目标、比较和理由，不作为今日依赖推荐、能力测评或新建工程指令。历史意见中的产品适配和评分是主观判断，外部库功能、版本和许可未在本轮重新核验；重新选型时需另做验证。

现行 `frontend/**` 规则见[统一基线](/Users/congming/github/goldenshare/docs/frontend/frontend-current-standards.md)和[frontend AGENTS](/Users/congming/github/goldenshare/frontend/AGENTS.md)。本文最初讨论全产品愿景，但不能替代其他产品域自己的规则，也不授权将它们迁入同一工程。

## 1. 当时解决什么问题

目标产品不仅是运维后台，还包含行情工作台、机会筛选、交易计划、复盘训练。选型因此兼顾研发效率、开发者与用户易用性、维护性、功能覆盖、高密度交互、响应速度与长期产品化，不只比较 CRUD 搭建速度。

历史主张是主 UI 负责一致的交互/视觉语言，数据缓存、路由状态、表格和图表独立选配。性能不能仅凭 UI 库轻重判断：要看数据量、缓存/去重/预取、局部更新、渲染和状态组织。

## 2. 历史候选与取舍

| 候选 | 当时保留的优点 | 当时顾虑与结论 |
| --- | --- | --- |
| Ant Design + ProComponents | 中后台表单/表格/详情成熟，中文资料与启动效率 | 担心产品被 CRUD 模式和后台视觉约束；不作全产品首选，不等于技术能力不足 |
| Semi Design | 运营页面组件完整、中文团队易用 | 仍偏企业后台；非优先主基座 |
| Mantine | 中性视觉、应用壳/抽屉/表单、可定制工作台 | 高阶数据表需自行组合；历史首选 |
| shadcn/ui + Radix | 自由组合、强定制 | 自建规范与维护投入更高；有明确投入时的备选 |
| MUI + MUI X | 成熟生态和增强数据组件 | 风格适配及商业授权成本须验证；可行但非首选 |
| Tremor | 看板与概览搭建 | 仅作看板补充候选，不作完整工作流主体系 |

原五方案主观分数保留（不是实测排名，也不是今天库版本的比较）：

| 方案 | 研发效率 | 易用性 | 维护性 | 功能全面性 | 高密度工作台适配 | 产品化空间 | 对运维系统适配 | 对行情工作台适配 | 综合判断 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Ant Design + ProComponents | 5 | 4 | 4 | 5 | 3 | 2 | 5 | 2 | 更适合后台，不适合作为全产品主基座 |
| Semi Design | 4 | 4 | 4 | 4 | 3 | 3 | 4 | 3 | 比 AntD 更柔和，但仍偏后台 |
| Mantine | 4 | 4 | 5 | 4 | 4 | 5 | 4 | 5 | 当前最均衡的主基座候选 |
| shadcn/ui + Radix | 3 | 4 | 4 | 4 | 5 | 5 | 3 | 5 | 上限最高，但研发和维护要求更高 |
| MUI + MUI X | 4 | 4 | 4 | 5 | 4 | 3 | 4 | 4 | 成熟强大，但风格与授权边界需谨慎 |


当时高密度工作台和产品化空间权重较高；“功能多”不等于“适合本产品”。原首选为 React/TypeScript/Vite/Mantine，shadcn/Radix 为更高自建投入的备选；不建议在未明确独立产品边界前维护两套主组件体系。

## 3. 能力层的历史定位与当前落点

| 能力 | 原定位 | 2026-09-12 本仓静态核对 |
| --- | --- | --- |
| TanStack Query | 服务端状态、缓存/去重/刷新/预取 | frontend 已声明依赖，providers.tsx 已接入 QueryClient |
| TanStack Router | 类型化导航、URL 筛选/时间/对象等上下文 | frontend 已声明依赖并创建 router |
| TanStack Table / Virtual | 复杂列、过滤、排序、大量行交互 | 原候选不是强制安装清单；frontend 当前 package.json 未声明，DataTable 以 TableShell/OpsTable/Mantine Table 实现 |
| Lightweight Charts | 主行情/K线、多面板时间序列 | 原能力候选；frontend package.json 未声明，不据此判断其他产品域是否使用 |
| ECharts | 分析、分布、汇总与看板，不替代主行情图 | 同上；库能力与数量不作为本轮实测结论 |

[package.json](/Users/congming/github/goldenshare/frontend/package.json)、[providers](/Users/congming/github/goldenshare/frontend/src/app/providers.tsx)、[router](/Users/congming/github/goldenshare/frontend/src/app/router.tsx)、[DataTable](/Users/congming/github/goldenshare/frontend/src/shared/ui/data-table.tsx)是上述当前落点的依据。依赖存在不证明每项缓存/预取等能力已使用。

## 4. 已退出的开工建议

原“先定技术栈 → 新建独立前端壳 → 迁移运维 → 再做行情工作台”是建项时期的顺序。frontend 工程、Provider、Router 和任务中心已经存在，不能再次执行“新建工程”或重启迁移。

现行 Mantine 主基座不在本轮重选；表格升级或补充图表必须依据真实需求、已有消费者、性能证据和独立批准。不要为凑齐原推荐组合安装库。交付和门禁分别见[交付流程](/Users/congming/github/goldenshare/docs/frontend/frontend-delivery-workflow-v1.md)与[回归流程](/Users/congming/github/goldenshare/docs/frontend/frontend-regression-and-baseline-workflow-v1.md)。

## 5. 原始参考入口

以下是原选型所引用的官方资料，不表示本轮重新核验了当前网页内容或许可；已保留去重后的入口，完整旧论述可从 Git 追溯。

- [Ant Design](https://ant.design/)
- [Ant Design 组件总览](https://ant.design/components/overview/)
- [Ant Design 数据展示规范](https://ant.design/docs/spec/data-display/)
- [Ant Design ProComponents](https://procomponents.ant.design/)
- [Ant Design Pro](https://github.com/ant-design/ant-design-pro)
- [Semi Design Overview](https://semi.design/en-US/start/overview)
- [Semi Design Introduction](https://semi.design/en-US/start/introduction)
- [Semi Design Form](https://semi.design/en-US/input/form)
- [Semi Design Table](https://semi.design/en-US/show/table)
- [Semi Design GitHub](https://github.com/DouyinFE/semi-design)
- [Mantine AppShell](https://mantine.dev/core/app-shell/)
- [Mantine Table](https://mantine.dev/core/table)
- [Mantine use-form](https://mantine.dev/form/use-form/)
- [Mantine About](https://mantine.dev/about/)
- [shadcn/ui Overview](https://ui.shadcn.com/docs/overview)
- [shadcn/ui Sidebar](https://ui.shadcn.com/docs/components/radix/sidebar)
- [shadcn/ui Data Table](https://ui.shadcn.com/docs/components/data-table)
- [shadcn/ui GitHub](https://github.com/shadcn-ui/ui)
- [Material UI Overview](https://mui.com/material-ui/getting-started/)
- [Material UI Core](https://mui.com/material-ui/)
- [MUI X Overview](https://mui.com/x/introduction/)
- [MUI X Licensing](https://mui.com/x/introduction/licensing/)
- [Tremor](https://www.tremor.so/)
- [Tremor Table](https://tremor.so/docs/ui/table)
- [Tremor Charts](https://tremor.so/charts)
- [TanStack Query React Overview](https://tanstack.com/query/latest/docs/framework/react/overview)
- [TanStack Router Overview](https://tanstack.com/router/latest/docs/framework/react/overview)
- [TanStack Table Overview](https://tanstack.com/table/v8/docs/overview)
- [Lightweight Charts](https://tradingview.github.io/lightweight-charts/)
- [Lightweight Charts Chart Types](https://tradingview.github.io/lightweight-charts/docs/chart-types)
- [Apache ECharts](https://echarts.apache.org/en/index.html)
- [ECharts Get Started](https://echarts.apache.org/handbook/en/get-started/)
- [ECharts Dynamic Data](https://echarts.apache.org/handbook/en/how-to/data/dynamic-data/)
- [TanStack Query Overview](https://tanstack.com/query/latest/docs/framework/react/overview)
- [Apache ECharts Get Started](https://echarts.apache.org/handbook/en/get-started/)
- [Apache ECharts Dynamic Data](https://echarts.apache.org/handbook/en/how-to/data/dynamic-data/)
