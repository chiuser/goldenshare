# 股票详情页｜技术实施方案 v1（implementation-design）

> 用途：把股票详情页需求转成可实施的前端工程方案。  
> 阶段：编码前。  
> 产物性质：实现设计基线，不写业务代码。

关联文档：

1. [股票详情页标杆需求 v1](/Users/congming/github/goldenshare/wealth/docs/pages/stock-detail/stock-detail-benchmark-requirement-v1.md)
2. [股票详情页 M2 编码前门禁 v1](/Users/congming/github/goldenshare/wealth/docs/pages/stock-detail/stock-detail-m2-coding-gate-v1.md)
3. [Showcase：stock-detail-v1.4.3.html](/Users/congming/github/goldenshare/wealth/docs/update/stock-detail-v1.4.3.html)
4. [设计 token：03-design-tokens.md](/Users/congming/github/goldenshare/wealth/docs/update/03-design-tokens.md)
5. [组件规范：04-component-guidelines.md](/Users/congming/github/goldenshare/wealth/docs/update/04-component-guidelines.md)

---

## 1. 文档目的

1. 对应需求文档：`stock-detail-benchmark-requirement-v1.md`。
2. 本文目标：冻结股票详情页首版的目录结构、组件拆分、mock view model、交互实现、验证方式与 `TopMarketBar` 共享抽象任务。
3. 本文不做：
   - 不实现代码；
   - 不接真实后端 API；
   - 不改 `src/biz`；
   - 不改市场总览业务模块；
   - 不重新设计顶部栏。
4. 跨模块抽象门禁原则适配结论：
   - 本页唯一允许的跨页面抽象是 `TopMarketBar`；
   - 抽象目标是“当前实现上移到 shared”，不是“重新设计一个新的 Header”。

---

## 1.1 跨模块抽象门禁原则适配

| 原则 | 本模块结论 | 设计落点 | 计划测试 |
|---|---|---|---|
| 事实源单一原则 | 股票详情视觉以 Showcase 为准，顶部栏以市场总览现实现为准 | `stock-detail-v1.4.3.html` + 当前 `TopMarketBar.tsx` | 页面结构 smoke + TopMarketBar shared smoke |
| 契约先行与冻结原则 | 先冻结 `StockDetailViewModel`，再写组件 | `stockDetailTypes.ts` | view model 类型测试 |
| 配置一致性原则 | 本期不接策略配置中心 | mock adapter 固定数据 | 不适用原因写入门禁 |
| 默认行为显式原则 | 不支持功能 toast；mock 初始化失败 error | toast helper + page state | 交互测试 |
| 排序与筛选确定性原则 | 周期、指标、右侧列表按 Showcase 顺序固定 | constants 文件 | 顺序断言 |
| 性能预算前置原则 | 首屏 mock 渲染 P95 < 300ms；图表不阻塞交互 | chart renderer | build/test + 手动浏览器验证 |
| 可观测与异常标准化原则 | 首版仅前端 toast/error，不新增后端异常码 | page state + toast | toast/error 测试 |
| 测试以用户可见结果为中心原则 | 验收围绕可见模块、文字、交互 | smoke test | 路由、模块、交互断言 |

---

## 2. 代码现状审计（基于真实代码）

### 2.1 当前已有路由/页面落点

1. `wealth/src/app/routes/WealthRouter.tsx` 当前登录后默认渲染 `MarketOverviewPage`。
2. 当前没有股票详情页路由与页面实现。
3. 当前 `wealth/src/app/routes/routerState.ts` 中 `DEFAULT_WEALTH_PATH` 为 `/wealth/market/overview`，`/wealth/login` 与 `/login` 是登录路径。
4. 当前 `WealthRouter` 对非登录且已认证路径没有进一步分流，最后统一返回 `MarketOverviewPage`。
5. 股票详情页正式路由已确认：`/market/stock/:tsCode`。
6. 结论：
   - 后续编码必须在 `WealthRouter` 中新增 `/market/stock/:tsCode` 显式分支；
   - 未命中股票详情页时，仍保持现有市场总览 fallback；
   - 不得破坏登录重定向、`DEFAULT_WEALTH_PATH` 与市场总览默认入口。

### 2.2 当前 `TopMarketBar` 现状

1. 当前实现文件：  
   `wealth/src/features/market-overview/layout/TopMarketBar.tsx`
2. 当前样式文件：  
   `wealth/src/pages/market-overview/market-overview-page.css`
3. 当前特征：
   - 品牌 logo + “财势乾坤 / 专业投研平台”
   - 一级导航
   - 主要指数行情条
   - 右向左跑马灯
   - 右侧用户入口“明”
4. 当前问题：
   - 组件位于 `market-overview` feature 内，股票详情页不能直接依赖市场总览 feature；
   - 样式混在市场总览页面 CSS 中，无法作为跨页面组件稳定复用。
5. 结论：
   - 必须先执行 M0：共享 `TopMarketBar` 抽象；
   - 抽象后市场总览页与股票详情页都从 shared 引用同一个组件。

### 2.3 当前设计资料

1. 股票详情页 Showcase 位于：  
   `wealth/docs/update/stock-detail-v1.4.3.html`
2. 相关 token 规则位于：  
   `wealth/docs/update/03-design-tokens.md`
3. 相关组件规范位于：  
   `wealth/docs/update/04-component-guidelines.md`
4. 结论：
   - 股票详情页可吸收 update 区的股票详情相关内容；
   - 不吸收 update 区与本页无关的旧 API 或旧产品口径。

### 2.4 当前依赖与测试结构

1. `wealth/package.json` 当前依赖只有 `react`、`react-dom`，尚未安装 `lightweight-charts`。
2. 图表实现拍板结果：首版使用 `lightweight-charts`。
3. 结论：
   - 后续编码必须将 `lightweight-charts` 加入 `wealth/package.json`；
   - 若产生 lockfile 变化，必须随同提交；
   - 不能假设当前工程已有 TradingView 相关依赖。
4. 当前测试分布：
   - 页面测试已有 `wealth/src/pages/market-overview/MarketOverviewPage.test.tsx`；
   - 模块真实 API smoke 测试位于 `wealth/src/test/**`；
   - 股票详情页首版是 mock UI，应新增页面/组件测试，不新增真实 API 测试。

---

## 3. 分层架构与目录落点

### 3.1 前端目录结构

```text
wealth/src/
  shared/
    ui/
      top-market-bar/
        TopMarketBar.tsx
        top-market-bar.css
        topMarketBarTypes.ts
        TopMarketBar.test.tsx
    lib/
      formatters.ts              # 继续复用已有 formatter
      marketDirection.ts         # 继续复用已有方向规则
  features/
    stock-detail/
      api/
        stockDetailMockAdapter.ts
      model/
        stockDetailTypes.ts
        stockDetailConstants.ts
      chart/
        StockChartWorkspace.tsx
        KlineMainPanel.tsx
        IndicatorPanel.tsx
        chartRenderer.ts
        chartInteractions.ts
      sidebar/
        StockInfoRail.tsx
        StockHeaderPanel.tsx
        StockSideTabs.tsx
        RelatedSectorTable.tsx
        StockMoneyFlowPanel.tsx
      layout/
        StockBreadcrumbActionBar.tsx
        StockChartToolbar.tsx
        StockDetailFixedLayout.tsx
      ui/
        StockDetailToast.tsx
  pages/
    stock-detail/
      StockDetailPage.tsx
      stock-detail-page.css
      StockDetailPage.test.tsx
```

### 3.2 M0：TopMarketBar 共享抽象

#### 3.2.1 目标

把当前市场总览页 `TopMarketBar` 抽象为跨页面共享组件，并保持现有市场总览顶部栏完全不变。

#### 3.2.2 迁移规则

1. 主实现从：
   - `wealth/src/features/market-overview/layout/TopMarketBar.tsx`
2. 迁移到：
   - `wealth/src/shared/ui/top-market-bar/TopMarketBar.tsx`
3. 样式从：
   - `wealth/src/pages/market-overview/market-overview-page.css` 中的 `.top-market-bar`、`.brand`、`.system-nav`、`.ticker-*`、`.top-meta` 等相关片段
4. 迁移到：
   - `wealth/src/shared/ui/top-market-bar/top-market-bar.css`
5. 市场总览页改为引用 shared 组件。
6. 股票详情页后续引用同一个 shared 组件。

#### 3.2.3 禁止事项

1. 禁止新增第二套 `StockDetailTopBar`。
2. 禁止把 `stock-detail-v1.4.3.html` 中旧版 top bar 直接移植进股票详情页。
3. 禁止修改当前顶部栏高度、品牌区、导航文案、跑马灯方向、速度、用户入口。
4. 禁止让 shared 组件依赖 `features/market-overview/**` 的私有类型。

### 3.3 股票详情页接口范围

1. 本期无后端接口。
2. 本期使用前端 mock adapter：
   - `stockDetailMockAdapter.getStockDetailViewModel(tsCode)`
3. 后续真实 API 必须单独设计，不能在本期顺手接入。

---

## 4. 数据流与执行链路

1. 路由入口：用户进入股票详情页路由。
2. 参数解析：从路由读取 `tsCode`。
3. Mock adapter：按 `tsCode` 返回 `StockDetailViewModel`。
4. 页面编排：`StockDetailPage` 拆分为顶部栏、工具栏、图表工作台、右侧栏。
5. 组件渲染：
   - `TopMarketBar` 消费 `topMarketTickers`
   - `StockChartWorkspace` 消费 `chartSeries`
   - `StockInfoRail` 消费 `stock/quote/sectors/moneyFlow`
6. 交互：
   - 周期切换更新当前 `period`
   - MA/BOLL 切换更新图表 overlay
   - 不支持功能调用 toast
   - 右侧 tab 切换本地状态
7. 状态输出：
   - mock 成功：ready
   - mock 失败：error

---

## 5. 组件拆分与职责

### 5.1 `StockDetailPage`

职责：

1. 页面级状态管理。
2. 路由参数读取。
3. mock view model 装载。
4. 组织页面级布局。

禁止：

1. 不直接绘图。
2. 不内联 mock 数据。
3. 不直接实现顶部栏。

### 5.2 `TopMarketBar`

职责：

1. 跨页面顶部栏。
2. 品牌区、系统导航、指数跑马灯、用户入口。
3. 保持市场总览当前视觉与交互。

禁止：

1. 禁止绑定市场总览私有类型。
2. 禁止在股票详情页二次封装出不同视觉。

### 5.3 `StockBreadcrumbActionBar`

职责：

1. 展示 `财势乾坤 / 乾坤行情 / 个股详情 / 股票名`。
2. 展示必要的股票上下文动作。
3. 不承载真实交易功能。

### 5.4 `StockChartToolbar`

职责：

1. 周期按钮：分时、日K、周K、月K、120分、90分、60分、30分、15分、5分、1分。
2. 展示复权/设置类入口。
3. 不支持功能 toast。

### 5.5 `StockChartWorkspace`

职责：

1. 固定左侧图表工作台。
2. 渲染 K 线主图、MACD、成交量、KDJ。
3. 管理 hover 十字线、tooltip、浮动坐标标签。
4. 管理指标栏 active 状态。

实现选择：

1. 默认目标是高保真还原 Showcase。
2. 图表实现路线已确认采用 “TradingView 优先，canvas 兜底”。
3. 首轮明确使用 `lightweight-charts` 完成 K 线、成交量、MACD、KDJ 的基础绘制和联动。
4. 对 TradingView 难以原样覆盖的区域，优先通过外层 React 组件和 CSS 覆盖层精修，包括工具栏、tooltip、crosshair、指标栏、右侧轴视觉和面板比例。
5. `lightweight-charts` 默认的 series 最新值标签不得直接作为页面坐标浮标使用；K 线、均线、MACD、成交量、KDJ 等 series 必须关闭默认 latest-value/price-line 标签，避免出现固定在最新数据点的彩色值条。
6. 坐标轴浮标必须由 `subscribeCrosshairMove` 驱动，随鼠标所在 panel 的 Y 坐标变化；视觉使用品牌金弱背景，不使用红绿，避免与涨跌含义冲突。
7. 十字坐标线必须在 K 线主图、MACD、成交量、KDJ 四个 panel 上按同一横轴时间同步显示；数据同步使用 `setCrosshairPosition/clearCrosshairPosition`，视觉竖线使用图表工作台外层共享 overlay，避免四个独立 chart 实例因内部坐标轴宽度差异产生像素错位。
8. 十字坐标线视觉使用更密的短虚线/点线，避免长虚线造成终端感不足。
9. 四个 chart 的 `rightPriceScale.minimumWidth` 必须使用同一固定宽度，确保 MACD、成交量、KDJ 与 K 线主图右侧坐标轴和绘图区右边界对齐；固定宽度应贴近刻度文字实际需要，禁止为了对齐保留过大的右侧空白；不得依赖 `lightweight-charts` 按各 panel 文本自动计算轴宽。
10. 各 panel 的指标信息条必须是正常布局行，不得绝对定位覆盖图表 canvas；图表区域应从指标信息条下方紧贴开始。
11. `timeScale.rightOffset` 只能保留少量安全留白，禁止在最右侧留下明显空白区。
12. 只有当以下关键项经过验证仍不可控时，才允许退回本地 canvas：
   - 四图 crosshair 联动无法稳定实现；
   - 图表面板比例、右侧坐标轴宽度或底部时间轴无法贴近 Showcase；
   - tooltip / 浮标 / 指标覆盖层无法与设计 token 对齐；
   - TradingView 默认交互或品牌元素无法按本项目设计隐藏或约束。
13. 若触发 canvas 兜底，必须先记录失败证据和影响面，不能直接改实现路线。

### 5.6 `StockInfoRail`

职责：

1. 右侧固定信息栏。
2. 股票头部行情。
3. 盘口 / 资料 tab。
4. 盘口摘要、关联板块、个股资金统计、产品边界。

禁止：

1. 不给用户买卖建议。
2. 不显示真实交易入口。
3. 不自行查询后端。

---

## 6. Mock View Model

```ts
interface StockDetailViewModel {
  topMarketTickers: TopMarketTicker[];
  stock: StockIdentity;
  quote: StockQuoteSnapshot;
  periods: StockPeriodOption[];
  activePeriod: StockPeriodKey;
  chart: StockChartSeries;
  indicatorTabs: StockIndicatorTab[];
  rightRail: {
    sectors: RelatedSectorRow[];
    moneyFlow: StockMoneyFlowStructure[];
    productBoundaryNotes: string[];
  };
}
```

要求：

1. 所有页面可见事实都来自该 view model。
2. mock adapter 内部可以生成 deterministic 数据。
3. 组件不得在 JSX 内临时创建业务事实。

---

## 7. 样式与设计 token 落地

1. 全局 token 继续来自 `wealth/src/styles/design-tokens.css`。
2. 股票详情页专属布局 token 可在 `stock-detail-page.css` 中定义，但必须引用设计文档中的命名语义。
3. 当前 `stock-detail-v1.4.3.html` 中与股票详情页相关的 token 包括：
   - 顶部栏高度；
   - 面包屑行动条高度；
   - 图表工具栏高度；
   - 右侧栏宽度；
   - K 线 / MACD / 成交量 / KDJ 比例；
   - crosshair、tooltip、axis float、panel border。
4. 任何与 Showcase 不一致的视觉调整必须登记为待拍板项。

---

## 8. 状态与异常落地

1. 页面状态：
   - `loading`
   - `ready`
   - `empty`
   - `error`
2. toast：
   - 指标设置暂未开通；
   - 交易计划暂未开通；
   - 自选/提醒首版仅展示提示。
3. 首版不接后端异常码。
4. 首版不接 debug 面板。

---

## 9. 测试与验证计划

1. 单元测试：
   - shared `TopMarketBar` 渲染品牌、导航、ticker。
   - 股票详情 mock adapter 返回完整 view model。
   - 右侧 tab 切换。
   - 周期切换。
   - 不支持指标 toast。
2. 页面 smoke：
   - 股票详情页路由可进入。
   - 顶部栏与市场总览共用组件。
   - K 线工作台四图区域存在。
   - 右侧盘口与资料 tab 存在。
3. 手动视觉验收：
   - 对照 `stock-detail-v1.4.3.html` 逐模块检查。
   - 不允许“看起来差不多”作为通过标准。
4. 通用验证命令：

```bash
cd wealth
npm run typecheck
npm run test
npm run build
```

---

## 10. 分期里程碑

### M0：共享 `TopMarketBar` 抽象

1. 新增 shared `TopMarketBar` 目录。
2. 迁移顶部栏组件与样式。
3. 市场总览改为引用 shared 组件。
4. 增加 shared 组件测试。
5. 验证市场总览顶部栏无视觉和行为回退。

### M1：股票详情页静态骨架

1. 新增 `/market/stock/:tsCode` 路由分支。
2. 新增页面目录。
3. 新增 mock adapter 与 view model 类型。
4. 搭建固定视口布局。
5. 使用 shared `TopMarketBar`。
6. 增加 `lightweight-charts` 依赖，为 M2 图表工作台准备。

### M2：图表工作台

1. 使用 `lightweight-charts` 搭建 K 线主图。
2. 使用同一路线实现 MACD、成交量、KDJ 区域。
3. 实现四图联动 hover crosshair 与外置 tooltip。
4. 实现周期和 overlay 切换。
5. 对照 Showcase 逐步精修图表尺寸、坐标、网格、字体、tooltip 与面板比例。
6. tooltip 换边口径必须与 Showcase 对齐：鼠标靠近 K 线区右侧时，tooltip 固定出现在 K 线主图区左侧安全位置；鼠标靠近左侧时，tooltip 固定出现在右侧安全位置。它不是贴着十字线左侧浮动。
7. 关闭 `lightweight-charts` 默认 latest-value/price-line 标签，改由 `subscribeCrosshairMove` 输出当前 panel 的 Y 轴浮标。
8. 使用 `setCrosshairPosition/clearCrosshairPosition` 同步四个图表 panel 的同一横轴时间数据状态。
9. 使用图表工作台外层共享 overlay 绘制贯穿四个 panel 的竖向十字线，原生 chart 竖线不得作为最终视觉来源。
10. 四个 chart 统一 `rightPriceScale.minimumWidth`，保证右侧坐标轴和绘图区右边界一致，且坐标值尽量贴近右侧设置齿轮所在区域。
11. 指标信息条以正常布局行承载，不覆盖 MACD、成交量、KDJ 等指标图形。
12. 右侧时间轴留白保持极小，不允许出现明显空白段。
13. 十字线线型使用更密的短虚线/点线。
14. 日线底部时间轴使用自定义覆盖层：最左侧展示首个数据点的 `YYYY/MM`，之后每个月展示一次 `MM` 标识；该口径只约束日线，不代表其他周期。
15. 十字线对应底部必须显示日期标签，标签随共享竖向十字线移动，日线格式为 `YYYYMMDD`。
16. 若 TradingView 路线无法满足关键高保真项，按“证据 -> 评审 -> canvas 兜底”的顺序处理。

### M3：右侧信息栏

1. 实现股票头部。
2. 实现盘口摘要。
3. 实现关联板块。
4. 实现个股资金统计。
5. 实现资料 placeholder。

### M4：交互与验收

1. 补齐 toast。
2. 补齐测试。
3. 执行视觉对照。
4. 修正文档与实现差异。

---

## 11. 风险与缓解

| 风险 | 触发条件 | 缓解动作 |
|---|---|---|
| 顶部栏被复制成两套 | 股票详情页单独写 Header | M0 强制抽 shared；测试断言同一组件来源 |
| 抽象 TopMarketBar 导致市场总览回退 | CSS 迁移不完整 | 先写 shared 测试，再做视觉对照 |
| TradingView 无法高保真 | 默认工具栏、样式、交互无法压到 Showcase | 先用外层组件和 CSS 覆盖层精修；仍不可控时记录证据，再评审 canvas 兜底 |
| 页面文件过长 | 图表和侧栏都写在 Page 中 | 严格按 feature/layout/chart/sidebar 拆分 |
| mock 散落组件 | JSX 内直接写业务数据 | mock adapter + view model 测试 |

---

## 12. 已确认事项与待拍板项

### 12.1 已确认事项

1. 图表实现方式已确认：TradingView 优先仿真并精修，canvas 仅作为有证据的兜底方案。
2. 具体图表库已确认：首版使用 `lightweight-charts`。
3. 股票详情页正式路由已确认：`/market/stock/:tsCode`。

### 12.2 待拍板项

当前无待拍板项。

---

## 13. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-30 | 初版：冻结股票详情页实现分层与 TopMarketBar 共享抽象任务 | Codex |
| v1.1 | 2026-05-30 | 回填路由与 `lightweight-charts` 拍板结论，并补充当前代码审计结果 | Codex |
| v1.2 | 2026-05-30 | 明确关闭默认 latest-value 彩条，并用 `subscribeCrosshairMove` 承接 Y 轴浮标 | Codex |
| v1.3 | 2026-05-30 | 补充四图同一横轴时间 crosshair 同步与短虚线视觉口径 | Codex |
| v1.4 | 2026-05-30 | 补充共享竖向 crosshair overlay 与统一右侧坐标轴宽度口径 | Codex |
| v1.5 | 2026-05-30 | 补充指标信息条不覆盖图表和右侧留白收敛口径 | Codex |
| v1.6 | 2026-05-30 | 补充右侧坐标轴固定宽度不得产生过大空白的细化口径 | Codex |
| v1.7 | 2026-05-30 | 补充日线底部时间轴与十字线日期标签口径 | Codex |
