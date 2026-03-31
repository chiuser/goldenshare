# 前端技术与组件体系选型建议

## 1. 文档目的

本文用于为 `goldenshare / 财势乾坤` 的未来前端体系做统一选型判断。

这不是只针对当前运维系统页面的 UI 选择，而是面向整个产品长期演进的技术决策文档。

本文重点回答三个问题：

1. 整个产品的主前端基座应该如何选
2. 组件体系应该优先服务什么样的产品形态
3. 哪些库适合作为主基础，哪些库更适合作为能力补充

## 2. 产品背景与选型前提

从高层产品文档来看，`财势乾坤` 未来不是单一的运维后台，也不是一个简单的行情展示站。

它更接近一个持续生长的专业交易工作系统，至少会包含以下长期子系统：

- 行情工作台
- 机会探查 / 条件筛选
- 交易计划与跟踪
- 复盘与训练
- 数据中心 / 运维系统

这意味着前端选型不能只围绕“当前最先落地的是运维系统”来做判断。

如果只用“后台组件库是否省事”来决定主技术栈，后续很容易出现两个问题：

- 主产品长成“企业后台”的味道，而不是“专业交易工作台”
- 为了做行情工作台、密集信息视图、图表联动，又被迫引入第二套主 UI 体系，导致维护成本和设计割裂迅速上升

因此，本次选型必须遵守一个核心原则：

**主前端基座要优先服务整个财势乾坤产品，而不是只服务当前运维系统。**

## 3. 评估维度

结合未来需求，我建议从以下维度综合判断：

### 3.1 研发效率

关注点：

- 页面和组件搭建速度
- 表单、表格、详情页、抽屉、弹窗等基础件是否成熟
- 文档质量与上手成本
- 团队是否容易形成统一写法

### 3.2 易用性

这里分两层：

- 对开发者是否易用
- 对最终用户是否易用

对于交易系统，用户易用性尤其体现在：

- 信息密度高但不乱
- 操作路径短
- 筛选、联动、切换足够顺手
- 页面在高频使用下不让人疲劳

### 3.3 维护性

关注点：

- 是否容易沉淀统一设计语言
- 是否容易封装自己的业务组件
- 后续复杂页面增长时是否会越做越乱
- 是否容易形成清晰的前端工程边界

### 3.4 功能全面性

未来产品既有：

- 运维控制台类页面
- 行情与图表类页面
- 工作台与任务流类页面
- 筛选、计划、复盘类页面

因此不能只看按钮和表单是否全，还要看：

- 布局能力
- 数据密集型表格能力
- 图表整合能力
- 搜索、筛选、侧栏、抽屉、时间线等工作流组件的适配度

### 3.5 性能与响应速度

行情软件的体验很大程度上由“快不快”决定。

这里要特别说明：

**UI 组件库本身不是响应速度的唯一决定因素。**

真正影响行情系统响应速度的关键通常是：

- 表格和列表是否支持虚拟化
- 图表渲染性能如何
- 请求缓存、去重、预取是否成熟
- 页面状态切换是否足够轻
- 高频局部更新时是否会引发整页重渲染

所以前端选型不能只看视觉风格，还要看它是否容易和这些高性能能力组合起来。

### 3.6 长期产品化能力

财势乾坤未来不是内部一次性工具，而是长期产品。

因此还要看：

- 是否容易做出自己的产品气质
- 是否会天然把产品拉向“后台模板感”
- 是否利于后续做统一工作台体验

## 4. 候选方案分析

## 4.1 Ant Design + ProComponents

官方资料：

- [Ant Design](https://ant.design/)
- [Ant Design 组件总览](https://ant.design/components/overview/)
- [Ant Design 数据展示规范](https://ant.design/docs/spec/data-display/)
- [Ant Design ProComponents](https://procomponents.ant.design/)
- [Ant Design Pro](https://github.com/ant-design/ant-design-pro)

### 优点

- 对中后台极其成熟，表单、表格、抽屉、详情、通知、状态标签等几乎开箱即用
- `ProTable`、`ProDescriptions`、`ProForm` 这类组件对运维、配置、列表页非常省心
- 文档成熟，中文语境资料多，研发启动成本低
- 适合快速把控制台、配置中心、审计页、任务页做出来

### 缺点

- 整体气质天然偏企业后台，容易把产品往“管理系统”方向拉
- 对“专业交易工作台”这种高密度、强联动、多面板场景，不是最自然的母体
- 如果后期大量自定义工作台、图表面板、定制交互，实际会逐步绕开它的高阶封装
- 容易让研发习惯落到“CRUD + 列表页 + 表单页”模式，而这不是未来产品的主形态

### 适合度判断

- 对运维系统：很高
- 对整个财势乾坤：中等
- 作为全产品主基座：不推荐作为首选

### 我的结论

如果我们只做运维后台，这套会很稳。

但结合整个产品目标，它更适合做“内部控制台风格”的系统，不适合做财势乾坤的主前端母体。

## 4.2 Semi Design

官方资料：

- [Semi Design Overview](https://semi.design/en-US/start/overview)
- [Semi Design Introduction](https://semi.design/en-US/start/introduction)
- [Semi Design Form](https://semi.design/en-US/input/form)
- [Semi Design Table](https://semi.design/en-US/show/table)
- [Semi Design GitHub](https://github.com/DouyinFE/semi-design)

### 优点

- 同样偏中后台，但比传统后台模板感稍轻
- 表格、表单、SideSheet、Descriptions、Timeline 这类组件对运营控制面很顺手
- 组件比较完整，做配置中心、审计中心、任务页会比较舒服
- 中文团队理解成本较低

### 缺点

- 本质上仍然偏企业级后台场景
- 对未来的行情工作台、交易工作台、训练系统这类产品形态，没有明显天然优势
- 如果后面需要做更强的品牌化和产品化外观，仍然会碰到“后台味”问题

### 适合度判断

- 对运维系统：高
- 对整个财势乾坤：中等偏上
- 作为全产品主基座：谨慎，不建议优先选

### 我的结论

Semi 比纯后台风格更柔和，但仍然没有真正解决“主产品不是后台”的根问题。

## 4.3 Mantine

官方资料：

- [Mantine AppShell](https://mantine.dev/core/app-shell/)
- [Mantine Table](https://mantine.dev/core/table)
- [Mantine use-form](https://mantine.dev/form/use-form/)
- [Mantine About](https://mantine.dev/about/)

### 优点

- 对应用壳、工作台布局、侧栏、抽屉、弹窗、通知、时间线这类基础件支持很好
- `AppShell` 非常适合做未来的专业工作台框架
- `@mantine/form` 对中等复杂度表单和状态管理足够顺手
- 视觉基调相对中性，不会天然把产品拖向传统后台
- 既能做运维控制台，也能做更现代的行情工作台
- 自定义成本比 Ant Design / MUI 更低一些，产品化空间更大

### 缺点

- 没有像 `ProTable` 那样“后台页面一把梭”的高级封装
- 内建表格偏基础，复杂数据表还是需要外接更强的表格方案
- 对大型数据密集型专业系统，需要组合更多能力库一起用

### 适合度判断

- 对运维系统：中高
- 对行情工作台：高
- 对整个财势乾坤：很高
- 作为全产品主基座：推荐

### 我的结论

Mantine 是一个非常平衡的选择。

它不像 Ant Design 那样强行把系统拉成后台，也不像纯 headless 方案那样要求我们一开始就自己拼太多底层件。

如果我们要兼顾：

- 运维系统
- 行情工作台
- 计划与训练类页面
- 后续长期产品化

那么 Mantine 是当前最均衡的主基座候选。

## 4.4 shadcn/ui + Radix

官方资料：

- [shadcn/ui Overview](https://ui.shadcn.com/docs/overview)
- [shadcn/ui Sidebar](https://ui.shadcn.com/docs/components/radix/sidebar)
- [shadcn/ui Data Table](https://ui.shadcn.com/docs/components/data-table)
- [shadcn/ui GitHub](https://github.com/shadcn-ui/ui)

### 优点

- 可组合性非常强，几乎不会被组件库审美绑住
- 很适合做有自己气质的专业产品，而不是模板式后台
- 和 `TanStack Table`、图表库、状态管理工具组合时非常灵活
- 如果未来我们非常重视产品体验和品牌感，它的上限很高

### 缺点

- 它更像“组件代码分发与组装体系”，不是一套高度封装的完整后台组件库
- 很多能力要自己装、自己定规范、自己沉淀设计系统
- 对前端工程能力和设计一致性要求更高
- 一开始研发速度可能不如 Mantine / AntD / Semi

### 适合度判断

- 对运维系统：中
- 对行情工作台：很高
- 对整个财势乾坤：很高
- 作为全产品主基座：可选，但要求更高

### 我的结论

如果我们愿意在前端体系上投入更强的设计和工程能力，`shadcn/ui + Radix` 的长期上限非常高。

但它不是“省心型方案”，而是“高自由度、高定制度、高责任”的方案。

对于当前阶段，它更适合作为“强定制路线”的备选，而不是默认首选。

## 4.5 MUI + MUI X

官方资料：

- [Material UI Overview](https://mui.com/material-ui/getting-started/)
- [Material UI Core](https://mui.com/material-ui/)
- [MUI X Overview](https://mui.com/x/introduction/)
- [MUI X Licensing](https://mui.com/x/introduction/licensing/)

### 优点

- 组件生态很成熟，基础件非常全
- `MUI X` 针对复杂数据场景提供了 Data Grid、Tree View、Charts、Date Pickers 等增强件
- 国际化、工程化、主题能力都不错

### 缺点

- 视觉语言天然带有较强的 Material Design 气质，不一定是财势乾坤最自然的产品语气
- `MUI X` 是 open core，部分高级能力需要商业授权
- 如果后面我们大量依赖它的高级数据组件，许可和成本需要提前纳入考虑

### 适合度判断

- 对运维系统：高
- 对数据密集型页面：中高
- 对整个财势乾坤：中高
- 作为全产品主基座：可行，但不是我最优先的推荐

### 我的结论

MUI 是一个很成熟的强方案，但它会带来两个长期问题：

- 视觉语言未必最贴合我们的产品气质
- `MUI X` 的商业授权边界需要长期纳入决策

如果团队本来就强偏 MUI 生态，它是可行的；但如果从零选型，我不会把它排在最前面。

## 4.6 Tremor

官方资料：

- [Tremor](https://www.tremor.so/)
- [Tremor Table](https://tremor.so/docs/ui/table)
- [Tremor Charts](https://tremor.so/charts)

### 优点

- 做 dashboard、指标卡片、概览页很快
- 图表和概览视觉通常比较好看

### 缺点

- 更适合作为“看板补充库”，不适合作为整个前端主组件体系
- 对复杂交互、复杂工作流、专业行情工作台来说不够全面

### 我的结论

Tremor 可以作为“仪表盘页补充件”去看，但不适合做主前端基础。

## 5. 需要单独补上的专业能力层

无论主 UI 基座选什么，我都建议把下面这些能力视为独立决策，而不是指望主组件库全部解决。

## 5.1 TanStack Query

官方资料：

- [TanStack Query React Overview](https://tanstack.com/query/latest/docs/framework/react/overview)

官方文档明确强调它解决的是获取、缓存、同步和更新 server state 的问题，并且会直接让应用“感觉更快、更响应”。

### 为什么它重要

对行情软件和专业工作台来说，页面体验很大程度上取决于：

- 缓存
- 去重
- 后台刷新
- 预取
- 分页和懒加载
- 服务器状态一致性

这些不是 UI 组件库的强项，但却是体验快不快的核心。

### 建议

无论选 Mantine、shadcn、MUI 还是别的，我都建议把 `TanStack Query` 作为默认 server-state 层。

## 5.2 TanStack Router

官方资料：

- [TanStack Router Overview](https://tanstack.com/router/latest/docs/framework/react/overview)

官方文档强调它有：

- 强类型导航
- 嵌套路由
- 预取
- 内建 loader 缓存
- 面向搜索参数的类型化状态管理

### 为什么它重要

财势乾坤未来会有大量页面状态天然应该进 URL：

- 筛选条件
- 代码
- 时间窗口
- 对比对象
- 排序方式
- 工作台布局上下文

这类系统如果 URL 状态做不好，后面分享链接、恢复上下文、前进后退、页面协作都会很痛苦。

### 建议

如果我们决定做一个真正长期可扩展的 React 前端，我建议认真考虑 `TanStack Router`，而不是只把路由看成“页面切换工具”。

## 5.3 TanStack Table + TanStack Virtual

官方资料：

- [TanStack Table Overview](https://tanstack.com/table/v8/docs/overview)
- [shadcn/ui Data Table](https://ui.shadcn.com/docs/components/data-table)

官方文档明确说明 `TanStack Table` 是 headless 的，核心优势就是灵活和框架无关。  
对我们这种未来会有大量自定义列、筛选、排序、联动的系统，这非常重要。

### 为什么它重要

行情软件和运维系统都离不开高密度表格：

- 自选池
- 条件筛选结果
- 涨跌幅排行
- 板块热度
- execution 列表
- 日志与事件列表

而这些表往往不是普通表，而是：

- 自定义渲染
- 高亮
- 批量选择
- 快捷操作
- 大量筛选排序
- 未来可能还要虚拟滚动

### 建议

不论 Mantine 还是 shadcn，都建议把 `TanStack Table` 作为复杂数据表的统一底层。

## 5.4 Lightweight Charts

官方资料：

- [Lightweight Charts](https://tradingview.github.io/lightweight-charts/)
- [Lightweight Charts Chart Types](https://tradingview.github.io/lightweight-charts/docs/chart-types)

官方文档明确指出它是为交互式金融图表设计的，当前版本还支持 pane。

### 为什么它重要

对财势乾坤来说，K 线和时间序列行情图不是“附属图表”，而是产品核心能力。

这类图如果只用通用图表库替代，往往在：

- 交互细节
- 金融图语义
- 使用体验

上不够自然。

### 建议

对于主行情图、K 线图、叠加均线和多 pane 时间序列图，优先考虑 `Lightweight Charts`。

## 5.5 Apache ECharts

官方资料：

- [Apache ECharts](https://echarts.apache.org/en/index.html)
- [ECharts Get Started](https://echarts.apache.org/handbook/en/get-started/)
- [ECharts Dynamic Data](https://echarts.apache.org/handbook/en/how-to/data/dynamic-data/)

官方站点强调它支持 20 多种图表类型，并且具有 progressive rendering、stream loading 和大数据实时渲染能力。

### 为什么它重要

除了核心 K 线图，未来产品还会有大量分析型图：

- 情绪指标
- 板块热度
- 宏观统计
- 指标分布
- 训练与复盘图表

这部分用 `ECharts` 会比把所有图都压到金融图表库上更合适。

### 建议

把 `ECharts` 定位成：

- 分析图
- 汇总图
- 仪表盘图

而不是替代主行情图。

## 6. 综合对比

下面给出一个面向财势乾坤整体产品的主观评分，分数越高越好。

| 方案 | 研发效率 | 易用性 | 维护性 | 功能全面性 | 高密度工作台适配 | 产品化空间 | 对运维系统适配 | 对行情工作台适配 | 综合判断 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Ant Design + ProComponents | 5 | 4 | 4 | 5 | 3 | 2 | 5 | 2 | 更适合后台，不适合作为全产品主基座 |
| Semi Design | 4 | 4 | 4 | 4 | 3 | 3 | 4 | 3 | 比 AntD 更柔和，但仍偏后台 |
| Mantine | 4 | 4 | 5 | 4 | 4 | 5 | 4 | 5 | 当前最均衡的主基座候选 |
| shadcn/ui + Radix | 3 | 4 | 4 | 4 | 5 | 5 | 3 | 5 | 上限最高，但研发和维护要求更高 |
| MUI + MUI X | 4 | 4 | 4 | 5 | 4 | 3 | 4 | 4 | 成熟强大，但风格与授权边界需谨慎 |

说明：

- 这里的“功能全面性”不等于“最适合作为主基座”
- 对财势乾坤这种产品，`高密度工作台适配` 和 `产品化空间` 的权重非常高

## 7. 我的推荐

## 7.1 首选方案

我当前最推荐的整体方案是：

**React + TypeScript + Vite + Mantine + TanStack Query + TanStack Router + TanStack Table/Virtual + Lightweight Charts + Apache ECharts**

### 理由

这套组合比较好地平衡了：

- 研发效率
- 长期维护
- 专业工作台产品形态
- 运维系统和行情系统的统一性
- 性能优化空间

它不会像 Ant Design 那样过早把产品拉成后台，也不会像纯 `shadcn` 路线那样一开始就给团队太高的自建压力。

## 7.2 第二推荐方案

如果你明确希望：

- 更强的品牌化
- 更强的 UI 自定义
- 愿意承担更高的前端工程复杂度

那么第二推荐是：

**React + TypeScript + Vite + shadcn/ui + Radix + TanStack Query + TanStack Router + TanStack Table/Virtual + Lightweight Charts + Apache ECharts**

### 适用前提

- 前端工程能力要更强
- 我们愿意投入更多时间打磨自己的设计系统
- 愿意用更高的初期成本换更高的长期表达力

## 7.3 不建议作为主基座的方案

### 不建议把 Ant Design / ProComponents 作为整个产品主基座

原因不是它不强，而是它更适合：

- 中后台
- CRUD 控制台
- 配置管理系统

而财势乾坤未来的主系统并不是一个 CRUD 中后台。

### 不建议过早采用双主组件体系

比如：

- 运维系统用 Ant Design
- 主产品用 Mantine / shadcn

这种做法短期看起来很合理，但长期会带来：

- 两套主题系统
- 两套交互语言
- 两套封装规范
- 两套维护成本

除非未来明确把运维系统独立成一条单独前端线，否则不建议早期就双栈。

## 8. 响应速度与性能的专门说明

对于行情软件，响应速度确实是核心。

但这里需要特别强调一个常见误区：

**组件库不是性能瓶颈的主要决定因素。**

真正决定前端体验的，通常是：

- 图表库是否适合金融场景
- 表格是否支持 headless + 虚拟化
- server state 是否有缓存、去重、预取
- 页面拆分是否合理
- 是否避免大面积重复渲染
- URL 状态和局部状态是否组织清晰

所以如果只追求“UI 组件库是不是轻”，但没有配好：

- `TanStack Query`
- `TanStack Table / Virtual`
- `Lightweight Charts`
- `ECharts`

那么整体体验依然不会好。

换句话说：

**主 UI 基座决定的是“系统长成什么样”；真正的专业交互体验，还要靠数据表、图表、缓存和渲染策略共同完成。**

## 9. 对当前项目阶段的建议

基于我们目前已经落地的后端与运维系统控制面，我建议下一步这样推进：

### 阶段 1：确立主前端技术栈

优先确定：

- React
- TypeScript
- Vite
- 主 UI 基座
- 数据请求层
- 路由层
- 图表和表格底层

### 阶段 2：建立独立前端应用壳

后端 BFF 保持当前 FastAPI 方案不变。  
在此前提下新增真正的前端应用工程，而不是继续在原生静态页面上堆功能。

### 阶段 3：先迁移运维系统

运维系统是很好的第一块前端迁移试验田，因为它已经有：

- 清晰 API
- 管理员权限
- 结构化页面
- 较少复杂图表依赖

### 阶段 4：再进入行情工作台

等前端技术骨架稳定后，再做行情工作台、机会探查、计划跟踪和训练复盘，会更稳。

## 10. 最终结论

如果只看当前运维系统，`Ant Design / Semi Design` 会显得很有吸引力。

但从财势乾坤的全局产品形态看，我不建议按“后台最省事”来决定主前端体系。

当前更合理的判断是：

- 运维系统只是整个产品的一部分
- 主前端基座必须服务未来的专业交易工作台
- 需要兼顾高密度信息展示、图表联动、筛选和训练系统

因此，我当前的最终建议是：

### 推荐结论

首选：

**Mantine 作为主 UI 基座**

并组合：

- `TanStack Query`
- `TanStack Router`
- `TanStack Table / Virtual`
- `TradingView Lightweight Charts`
- `Apache ECharts`

备选：

**shadcn/ui + Radix**  
适合在明确愿意投入更高前端体系建设成本时采用。

不建议：

- 把 `Ant Design / ProComponents` 作为整个财势乾坤的主前端基座
- 在项目早期引入两套并行的主组件体系

## 11. 参考资料

- [Ant Design](https://ant.design/)
- [Ant Design 组件总览](https://ant.design/components/overview/)
- [Ant Design 数据展示规范](https://ant.design/docs/spec/data-display/)
- [Semi Design Overview](https://semi.design/en-US/start/overview)
- [Semi Design Form](https://semi.design/en-US/input/form)
- [Semi Design Table](https://semi.design/en-US/show/table)
- [Mantine AppShell](https://mantine.dev/core/app-shell/)
- [Mantine Table](https://mantine.dev/core/table)
- [Mantine use-form](https://mantine.dev/form/use-form/)
- [Mantine About](https://mantine.dev/about/)
- [shadcn/ui Overview](https://ui.shadcn.com/docs/overview)
- [shadcn/ui Sidebar](https://ui.shadcn.com/docs/components/radix/sidebar)
- [shadcn/ui Data Table](https://ui.shadcn.com/docs/components/data-table)
- [Material UI Overview](https://mui.com/material-ui/getting-started/)
- [MUI X Overview](https://mui.com/x/introduction/)
- [MUI X Licensing](https://mui.com/x/introduction/licensing/)
- [TanStack Query Overview](https://tanstack.com/query/latest/docs/framework/react/overview)
- [TanStack Router Overview](https://tanstack.com/router/latest/docs/framework/react/overview)
- [TanStack Table Overview](https://tanstack.com/table/v8/docs/overview)
- [Lightweight Charts](https://tradingview.github.io/lightweight-charts/)
- [Lightweight Charts Chart Types](https://tradingview.github.io/lightweight-charts/docs/chart-types)
- [Apache ECharts](https://echarts.apache.org/en/index.html)
- [Apache ECharts Get Started](https://echarts.apache.org/handbook/en/get-started/)
- [Apache ECharts Dynamic Data](https://echarts.apache.org/handbook/en/how-to/data/dynamic-data/)
