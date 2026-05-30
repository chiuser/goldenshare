# 股票详情页｜M2 编码前门禁 v1

> 用途：在编码前冻结股票详情页首版 UI/mock 的执行门禁。  
> 阶段：M2 开工前。  
> 产物性质：执行清单，不通过不允许编码。

关联文档：

1. [股票详情页标杆需求 v1](/Users/congming/github/goldenshare/wealth/docs/pages/stock-detail/stock-detail-benchmark-requirement-v1.md)
2. [股票详情页技术实施方案 v1](/Users/congming/github/goldenshare/wealth/docs/pages/stock-detail/stock-detail-implementation-design-v1.md)
3. [Showcase：stock-detail-v1.4.3.html](/Users/congming/github/goldenshare/wealth/docs/update/stock-detail-v1.4.3.html)

---

## 1. 目的

1. 本门禁对应页面：`stockDetail`
2. 本门禁对应需求文档：`stock-detail-benchmark-requirement-v1.md`
3. 本门禁对应实施方案：`stock-detail-implementation-design-v1.md`
4. 本门禁特别约束：必须先完成 `TopMarketBar` shared 抽象，才能进入股票详情页主体编码。

---

## 2. 总门禁清单（全通过才能开工）

1. [ ] `TopMarketBar` 共享抽象任务拆为独立 M0，并确认不改变市场总览现有效果。
2. [ ] 股票详情页路由已确认并落实现：`/market/stock/:tsCode`。
3. [ ] 图表实现方式已确认并落依赖：`lightweight-charts` 优先仿真并精修，canvas 仅作为有证据的兜底方案。
4. [ ] `StockDetailViewModel` 字段冻结。
5. [ ] 页面组件拆分冻结。
6. [ ] mock adapter 输出冻结。
7. [ ] 核心交互清单冻结。
8. [ ] 高保真验收清单冻结。
9. [ ] 测试命令与 smoke case 冻结。
10. [ ] 不接真实 API、不改后端的边界冻结。

---

## 3. 请求与响应冻结

### 3.1 路由参数冻结

```ts
interface StockDetailRouteParams {
  tsCode: string; // e.g. 603806.SH
}
```

参数校验规则：

1. `tsCode` 为空 -> 页面 error。
2. `tsCode` 格式非法 -> 页面 error。
3. 首版不请求后端，不返回 HTTP 错误。
4. 当前正式路由固定为 `/market/stock/:tsCode`。

### 3.2 Mock View Model 冻结

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

约束：

1. 组件只能消费 view model。
2. 禁止组件内自行拼 mock 业务数据。
3. 后续真实 API 接入时，必须先重开 API 三件套。

---

## 4. 核心样例响应（最小集合）

### 4.1 正常样例

```json
{
  "stock": {
    "tsCode": "603806.SH",
    "name": "福斯特",
    "market": "CN_A",
    "industryTags": ["光伏设备", "新材料"]
  },
  "quote": {
    "price": 18.36,
    "change": 0.35,
    "changePct": 1.94,
    "direction": "UP"
  },
  "periods": [
    { "key": "timeShare", "label": "分时" },
    { "key": "day", "label": "日K" },
    { "key": "week", "label": "周K" }
  ],
  "activePeriod": "day"
}
```

### 4.2 error 样例

```json
{
  "error": {
    "code": "STOCK_DETAIL_MOCK_UNAVAILABLE",
    "message": "股票详情页 mock 数据不可用"
  }
}
```

---

## 5. 代码落点冻结

### 5.1 共享组件 M0

```text
wealth/src/shared/ui/top-market-bar/
  TopMarketBar.tsx
  top-market-bar.css
  topMarketBarTypes.ts
  TopMarketBar.test.tsx
```

门禁：

1. `TopMarketBar` 不得依赖 `features/market-overview/**`。
2. 市场总览必须从 shared 引用。
3. 股票详情页必须从 shared 引用。
4. 抽象前后市场总览顶部栏视觉不变。

### 5.2 股票详情页

```text
wealth/src/features/stock-detail/
wealth/src/pages/stock-detail/
```

门禁：

1. `pages/stock-detail` 只做页面编排。
2. `features/stock-detail/chart` 负责图表。
3. `features/stock-detail/sidebar` 负责右侧栏。
4. `features/stock-detail/api` 只放 mock adapter。

---

## 6. 高保真验收清单

### 6.1 顶部栏

1. [ ] 与市场总览使用同一 `TopMarketBar` 组件。
2. [ ] 品牌区、导航、ticker 跑马灯、用户入口与市场总览一致。
3. [ ] 不使用 Showcase 中旧版 top bar 的时间、状态、延迟元素。

### 6.2 股票详情页面骨架

1. [ ] 固定视口布局。
2. [ ] 顶部栏、面包屑行动条、图表工具栏、主内容区顺序一致。
3. [ ] 左侧图表工作台与右侧信息栏比例一致。
4. [ ] 不出现 body 级滚动。

### 6.3 图表工作台

1. [ ] K 线主图存在。
2. [ ] MACD、成交量、KDJ 三个副图区存在。
3. [ ] hover 十字线可用。
4. [ ] tooltip 内容可见。
5. [ ] tooltip 换边符合 Showcase：靠右时固定在 K 线区左侧安全位置，靠左时固定在右侧安全位置，不跟随十字线贴边。
6. [ ] 默认 latest-value/price-line 彩条已关闭，不能把最新值固定标签当成坐标浮标。
7. [ ] Y 轴浮标由 `subscribeCrosshairMove` 驱动，随鼠标所在 panel 的 Y 坐标变化。
8. [ ] MA / BOLL 可切换。
9. [ ] 周期按钮 active 状态正确。

### 6.4 右侧信息栏

1. [ ] 股票头部显示名称、标签、代码、价格、涨跌额、涨跌幅。
2. [ ] 盘口 tab 默认 active。
3. [ ] 盘口摘要字段完整。
4. [ ] 关联板块表格完整。
5. [ ] 个股资金统计完整。
6. [ ] 资料 tab 可切换到 placeholder。

### 6.5 Toast 与禁用能力

1. [ ] 不支持指标点击显示 toast。
2. [ ] 设置按钮显示 toast。
3. [ ] 自选、提醒、交易计划首版显示 toast。

---

## 7. 测试门禁

1. 单元测试：
   - `TopMarketBar.test.tsx`
   - `StockDetailPage.test.tsx`
   - `stockDetailMockAdapter.test.ts`
2. 组件交互测试：
   - 周期切换；
   - overlay 切换；
   - 右侧 tab 切换；
   - toast 出现与关闭。
3. 页面 smoke：
   - 股票详情页可渲染；
   - 核心模块标题与核心字段存在。
4. 执行命令：

```bash
cd wealth
npm run typecheck
npm run test
npm run build
```

通过标准：

1. 所有命令通过。
2. 测试覆盖用户可见结构。
3. 无新增真实 API 调用。

---

## 8. 性能门禁

1. 首屏 mock 渲染 P95 < 300ms。
2. 图表 hover 不出现明显卡顿。
3. `lightweight-charts` 图表实例必须限定在图表区域，不触发整页重排。
4. 若切换到 canvas 兜底，canvas 重绘必须限定在图表区域，不触发整页重排。
4. ticker 跑马灯保持当前性能特征。

---

## 9. 通用清单映射矩阵

| 原则 | 是否适用 | 落地位置 | 测试落地 | 备注 |
|---|---|---|---|---|
| 事实源单一原则 | 是 | Showcase + shared TopMarketBar | 页面 smoke | 顶部栏事实源是当前市场总览实现 |
| 契约先行与冻结原则 | 是 | `StockDetailViewModel` | mock adapter test | 先冻结字段再编码 |
| 配置一致性原则 | 否 | 本期不接策略配置 | 不适用 | 固定 mock UI |
| 默认行为显式原则 | 是 | toast/page state | 交互测试 | 不支持操作必须 toast |
| 排序与筛选确定性原则 | 是 | constants | 顺序断言 | 周期、指标、列表顺序固定 |
| 性能预算前置原则 | 是 | chart renderer | build + 手动验证 | 图表不可卡顿 |
| 可观测与异常标准化原则 | 部分适用 | page error/toast | error test | 首版无后端异常码 |
| 测试以用户可见结果为中心原则 | 是 | page smoke | 结构与交互断言 | 不以内部分层替代验收 |

---

## 10. 模块门禁清单（复盘增强版）

1. [ ] 先证据后设计：已逐项读取 `stock-detail-v1.4.3.html`、design token、component guidelines。
2. [ ] 先规则后实现：已冻结 TopMarketBar 共享抽象、mock view model、组件拆分。
3. [ ] 可判定性优先：图表实现方式已在编码前确认。
4. [ ] 状态分层明确：首版仅前端 page state，不引入后端 moduleStatus。
5. [ ] 后端定义事实：本期不接后端；后续真实 API 单独三件套。
6. [ ] 三件套强一致：benchmark、implementation、coding gate 无冲突项。
7. [ ] 反超前设计：不加入交易、诊股、实时流、真实 API。
8. [ ] 字段链路完整：UI -> mock view model -> mock adapter 可追溯。

---

## 11. 签字清单

### 11.1 前端负责人

1. [ ] 共享 TopMarketBar 抽象方案可执行。
2. [ ] 股票详情页组件拆分可执行。
3. [ ] 高保真验收标准明确。

### 11.2 架构/产品负责人

1. [ ] 路由路径已确认：`/market/stock/:tsCode`。
2. [ ] 图表实现方式已确认：`lightweight-charts` 优先，canvas 兜底。
3. [ ] 本期只做 UI/mock，无真实 API。

---

## 12. 已确认事项与待拍板项

### 12.1 已确认事项

1. 图表实现方式已确认：TradingView 优先仿真并精修；只有关键高保真项经验证不可控时，才允许带证据评审后退回 canvas。
2. 具体图表库已确认：首版使用 `lightweight-charts`。
3. 股票详情页正式路由已确认：`/market/stock/:tsCode`。

### 12.2 待拍板项

当前无待拍板项。

---

## 13. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-30 | 初版：冻结股票详情页编码前门禁与 TopMarketBar 共享前置任务 | Codex |
| v1.1 | 2026-05-30 | 回填路由与 `lightweight-charts` 拍板结论 | Codex |
| v1.2 | 2026-05-30 | 补充默认 latest-value 彩条关闭与 Y 轴浮标门禁 | Codex |
