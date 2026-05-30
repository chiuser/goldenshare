# 股票详情页｜标杆需求 v1（benchmark-requirement）

> 用途：冻结“财势乾坤 / 个股详情页”首版 UI 还原范围、交互边界与工程约束。  
> 阶段：编码前。  
> 产物性质：业务与体验事实源，不是实现代码。

关联文档：

1. [股票详情页技术实施方案 v1](/Users/congming/github/goldenshare/wealth/docs/pages/stock-detail/stock-detail-implementation-design-v1.md)
2. [股票详情页 M2 编码前门禁 v1](/Users/congming/github/goldenshare/wealth/docs/pages/stock-detail/stock-detail-m2-coding-gate-v1.md)
3. [Showcase：stock-detail-v1.4.3.html](/Users/congming/github/goldenshare/wealth/docs/update/stock-detail-v1.4.3.html)
4. [组件规范参考：component-library-demo-v2.2.html](/Users/congming/github/goldenshare/wealth/docs/reference/showcase/component-library-demo-v2.2.html)

---

## 1. 目标与定位

1. 模块目标：在 `wealth` 独立前端工程内新增“股票详情页”首版，实现对 `stock-detail-v1.4.3.html` 的高保真 UI 还原。
2. 用户价值：用户从行情系统进入单只股票后，能看到固定终端布局的 K 线工作台、指标区、盘口摘要、关联板块与资金结构信息。
3. 业务定位：股票详情页是财势乾坤行情系统的第二类核心页面，与市场总览同属“乾坤行情”业务系统，但不复用运营后台前端工程。
4. 首版数据定位：首版只做 UI 与 mock 数据，不接真实后端 API，不改 `src/biz`，不查询数据库。

---

## 2. 范围与边界

### 2.1 本期覆盖

1. 新增股票详情页页面级三件套与编码前门禁。
2. 高保真还原 `stock-detail-v1.4.3.html` 中的股票详情页布局、模块顺序、视觉密度、交互方式与状态反馈。
3. 抽象并复用当前市场总览页已经实现的 `TopMarketBar`。该任务必须作为 M0 前置任务独立完成。
4. 建立股票详情页 mock 数据模型、mock adapter 与页面 view model。
5. 实现固定视口交易终端布局：
   - 顶部 `TopMarketBar`
   - 面包屑 / 行动条
   - 图表工具栏
   - 左侧图表工作台
   - 右侧信息栏
6. 实现本期所需交互：
   - 周期切换
   - MA / BOLL 覆盖指标切换
   - 指标栏 active 状态切换
   - 不支持指标 toast
   - K 线图 hover 十字线与 tooltip
   - 右侧“盘口 / 资料”tab 切换
   - 操作按钮 toast
7. 保持财势乾坤设计规范：
   - 深色金融终端风
   - A 股红涨绿跌
   - 高信息密度
   - 不做后台管理风

### 2.2 本期不覆盖

1. 不接真实股票详情后端 API。
2. 不设计后端 API、`src/biz` 查询、schema 或服务。
3. 不接真实行情数据；图表库可使用 TradingView / lightweight-charts 类前端图库承载 mock 数据。
4. 不实现真实下单、交易、诊股、买卖建议、仓位建议。
5. 不实现真实自选、提醒、交易计划持久化。
6. 不实现盘口逐笔、五档、实时行情流。
7. 不改市场总览已有模块的数据逻辑。
8. 不重做当前市场总览 `TopMarketBar` 的视觉设计，只做共享组件抽象与原样复用。

### 2.3 与其他模块边界

1. 与市场总览边界：
   - 股票详情页不复制市场总览的 `TopMarketBar`；
   - 市场总览与股票详情页共同消费同一个共享 `TopMarketBar`；
   - 市场总览现有 `TopMarketBar` 视觉与行为是共享组件的事实源。
2. 与登录系统边界：
   - 页面仍处于登录态之后才能访问；
   - 不改登录页、不改认证 API、不改 token 存储策略。
3. 与后端边界：
   - 首版不调用真实 API；
   - 后续真实 API 设计必须单独走三件套。

---

## 3. 核心原则（硬约束）

1. 高保真优先：默认逐项复刻 `stock-detail-v1.4.3.html`，不得自由设计。
2. 顶部栏完全复用：`TopMarketBar` 必须抽象为共享组件，股票详情页不得单独实现新的顶部栏。
3. 现有视觉不回退：抽象共享组件后，市场总览页顶部栏视觉、交互、DOM 语义和跑马灯行为不得变化。
4. Mock 也必须走契约：mock 数据必须按股票详情页 view model 组织，禁止组件内散落硬编码事实。
5. TradingView 优先：首版优先使用 TradingView / lightweight-charts 类能力尽可能仿真 Showcase，并通过样式、覆盖层和组件封装逐步精修；只有在关键交互或视觉经过验证仍不可控时，才允许退回本地 canvas。
6. 不做产品外延：不加入 Showcase 没有的模块、按钮、提示、布局或数据。
7. 只做页面 UI：本期不把真实数据源、API 缓存、查询优化混入实现。

### 3.1 跨模块抽象门禁原则（需求层冻结）

1. 事实源单一：股票详情页视觉事实源为 `stock-detail-v1.4.3.html`；顶部栏事实源为当前市场总览页 `TopMarketBar` 实现。
2. 契约冻结：首版冻结 mock view model，不随组件临时增删字段。
3. 配置一致性：本期不引入策略配置中心；固定 UI 选项写入 mock/view model。
4. 默认行为显式：不支持操作统一 toast；真实接口未接入前所有数据均来自 mock adapter。
5. 排序筛选确定性：指标栏、周期栏、右侧列表均按 Showcase 顺序固定。
6. 性能预算前置：首屏 mock 渲染 P95 低于 300ms；图表绘制不得造成页面交互卡顿。
7. 可观测标准化：首版仅前端 toast 与测试断言，不新增后端异常码。
8. 用户可见结果优先：验收以页面像素级结构、模块完整性和交互行为为主，不以内部分层完成替代。

---

## 4. 业务对象模型（非代码，先语义）

### 4.1 `TopMarketTicker`

顶部行情条单个指数行情。

| 字段 | 含义 | 单位 | 可空 | 产出责任 | 缺失策略 |
|---|---|---|---|---|---|
| `code` | 指数代码 | - | 否 | mock adapter / 后续 API | 缺失不得渲染 |
| `name` | 指数名称 | - | 否 | mock adapter / 后续 API | 缺失展示 code |
| `point` | 最新点位 | 点 | 是 | mock adapter / 后续 API | 展示 `--` |
| `pct` | 涨跌幅 | % | 是 | mock adapter / 后续 API | 展示 `--` |
| `direction` | 涨跌方向 | - | 否 | formatter/model | 缺失按 `flat` |

说明：该对象服务共享 `TopMarketBar`，首版可沿用市场总览当前 `QuoteItem` 语义，但共享组件抽象时必须消除对 `market-overview` feature 私有类型的依赖。

### 4.2 `StockIdentity`

股票详情页当前标的。

| 字段 | 含义 | 单位 | 可空 | 产出责任 | 缺失策略 |
|---|---|---|---|---|---|
| `tsCode` | 股票代码 | - | 否 | route/mock adapter | 缺失进入页面 error |
| `name` | 股票名称 | - | 否 | mock adapter | 缺失展示代码 |
| `market` | 市场 | - | 否 | mock adapter | 默认 `CN_A` |
| `industryTags` | 行业/概念标签 | - | 是 | mock adapter | 缺失隐藏标签 |

### 4.3 `StockQuoteSnapshot`

右侧股票头部与盘口摘要事实。

| 字段 | 含义 | 单位 | 可空 | 产出责任 | 缺失策略 |
|---|---|---|---|---|---|
| `price` | 最新价 | 元 | 是 | mock adapter | 展示 `--` |
| `change` | 涨跌额 | 元 | 是 | mock adapter | 展示 `--` |
| `changePct` | 涨跌幅 | % | 是 | mock adapter | 展示 `--` |
| `open` | 今开 | 元 | 是 | mock adapter | 展示 `--` |
| `preClose` | 昨收 | 元 | 是 | mock adapter | 展示 `--` |
| `high` | 最高 | 元 | 是 | mock adapter | 展示 `--` |
| `low` | 最低 | 元 | 是 | mock adapter | 展示 `--` |
| `turnoverRate` | 换手率 | % | 是 | mock adapter | 展示 `--` |
| `volumeRatio` | 量比 | 倍 | 是 | mock adapter | 展示 `--` |
| `volume` | 成交量 | 手 | 是 | mock adapter | 展示 `--` |
| `amount` | 成交额 | 元/亿元 | 是 | mock adapter | formatter 决定 |
| `direction` | 涨跌方向 | - | 否 | formatter/model | 缺失按 `flat` |

### 4.4 `StockChartSeries`

图表工作台 mock 数据。

| 字段 | 含义 | 单位 | 可空 | 产出责任 | 缺失策略 |
|---|---|---|---|---|---|
| `period` | 周期 | - | 否 | mock adapter | 默认 `日K` |
| `candles` | K 线序列 | - | 否 | mock adapter | 空则图表 empty |
| `macd` | MACD 指标 | - | 是 | mock adapter | 缺失隐藏 MACD 线 |
| `volume` | 成交量序列 | 手 | 是 | mock adapter | 缺失展示空态 |
| `kdj` | KDJ 指标 | - | 是 | mock adapter | 缺失隐藏 KDJ 线 |
| `ma` | 均线指标 | 元 | 是 | mock adapter | 缺失隐藏 MA |
| `boll` | BOLL 指标 | 元 | 是 | mock adapter | 缺失隐藏 BOLL |

### 4.5 `RelatedSectorRow`

右侧关联板块行。

| 字段 | 含义 | 单位 | 可空 | 产出责任 | 缺失策略 |
|---|---|---|---|---|---|
| `name` | 板块名称 | - | 否 | mock adapter | 缺失不展示该行 |
| `changePct` | 板块涨跌幅 | % | 是 | mock adapter | 展示 `--` |
| `membersCount` | 成分数 | 个 | 是 | mock adapter | 展示 `--` |
| `category` | 板块类别 | - | 是 | mock adapter | 展示 `--` |

### 4.6 `StockMoneyFlowStructure`

右侧个股资金结构。

| 字段 | 含义 | 单位 | 可空 | 产出责任 | 缺失策略 |
|---|---|---|---|---|---|
| `label` | 单型名称 | - | 否 | mock adapter | 缺失不展示 |
| `netAmount` | 净额 | 元/万元/亿元 | 是 | mock adapter | 展示 `--` |
| `ratio` | 占比 | % | 是 | mock adapter | 展示 `--` |
| `direction` | 净流向方向 | - | 否 | formatter/model | 缺失按 `flat` |

---

## 5. 数据来源与映射（事实层）

首版全部使用 mock adapter，不接真实表。

| 业务字段 | 来源 | 转换规则 | 备注 |
|---|---|---|---|
| 顶部行情条 | 当前市场总览 mock/API 兼容结构 | 共享 `TopMarketTicker` | 抽象时消除 feature 私有类型依赖 |
| 股票身份 | `stockDetailMockAdapter` | 原样输出 | 以后替换真实 API |
| 图表序列 | `stockDetailMockAdapter` | 生成固定 deterministic 数据 | 禁止组件内随机生成 |
| 盘口摘要 | `stockDetailMockAdapter` | formatter 统一格式化 | 不接真实 API |
| 关联板块 | `stockDetailMockAdapter` | 固定顺序输出 | 首版无点击跳转 |
| 个股资金结构 | `stockDetailMockAdapter` | 按 Showcase 结构输出 | 首版无真实口径 |

补充：

1. 来源优先级：mock adapter 是唯一数据源。
2. 回退策略：mock adapter 不可用则页面 error。
3. 数据时效语义：静态 mock，不表达真实交易日。

---

## 6. 状态语义

1. 页面级状态：
   - `loading`：mock adapter 初始化中；
   - `ready`：mock view model 完整；
   - `empty`：核心 mock 数据为空；
   - `error`：mock adapter 或路由参数异常。
2. 模块级状态：
   - 图表区域、右侧栏、顶部栏各自只负责展示；
   - 首版不引入后端 moduleStatus。
3. debug：
   - 首版不新增 debug 面板；
   - 如需后续接真实 API，再按模块重新设计。

---

## 7. 异常语义

1. 首版只做前端页面异常，不新增后端异常码。
2. 用户可见策略：
   - 不支持功能显示轻量 toast；
   - 页面级异常显示股票详情页 error 态。
3. debug 可见策略：
   - 首版不扩展。

---

## 8. API 契约（需求层）

1. 本期没有真实后端 API。
2. 前端 mock contract：
   - `StockDetailViewModel`
   - `TopMarketTicker[]`
   - `StockChartSeries`
   - `StockQuoteSnapshot`
   - `RelatedSectorRow[]`
   - `StockMoneyFlowStructure[]`
3. 字段命名规则：lowerCamelCase。
4. 向后兼容策略：无；首版是新页面，不保留历史兼容字段。

---

## 9. 验收标准

1. 首页 `TopMarketBar` 与股票详情页 `TopMarketBar` 来自同一共享组件。
2. 抽象共享组件后，市场总览顶部栏视觉、跑马灯方向、速度、品牌区、导航区、用户入口均不变化。
3. 股票详情页整体结构与 `stock-detail-v1.4.3.html` 高保真一致。
4. 页面固定视口，不出现 body 级滚动条。
5. K 线工作台四个图表区域比例与 Showcase 对齐。
6. 周期切换、覆盖指标切换、指标栏、右侧 tab、toast、hover tooltip 均可用。
7. A 股红涨绿跌语义正确。
8. 首版所有内容均来自 mock adapter，组件内不散落事实数据。

---

## 10. 已确认清零项

1. 顶部 `TopMarketBar` 必须完全复用市场总览当前顶部栏。
2. 必须先抽象共享 `TopMarketBar`，再让股票详情页消费。
3. 首版只做 mock UI，不接真实后端 API。
4. 股票详情页必须高保真还原 `stock-detail-v1.4.3.html`。
5. 图表路线已确认：TradingView 优先仿真并精修，canvas 仅作为有证据的兜底方案。
6. 股票详情页正式路由已确认：`/market/stock/:tsCode`。
7. TradingView 路线具体实现已确认：首版使用 `lightweight-charts`。

## 10.1 待拍板项

当前无待拍板项。

---

## 11. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-30 | 初版：冻结股票详情页首版 UI/mock 范围与 TopMarketBar 共享前置任务 | Codex |
| v1.1 | 2026-05-30 | 回填路由 `/market/stock/:tsCode` 与 `lightweight-charts` 拍板结论 | Codex |
