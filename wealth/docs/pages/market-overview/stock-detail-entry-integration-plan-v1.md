# 市场总览｜股票详情入口接入方案 v1

> 状态：Draft / 待评审  
> 范围：只处理“市场总览页中股票名称、股票代码可点击进入股票详情页”。  
> 本文不写业务代码，作为后续编码门禁与验收依据。

---

## 0. 已拍板口径

1. 榜单速览：整行点击进入股票详情，不再限定为股票名称/代码单元格。
2. 连板天梯：停牌、缺行情、掉队股票仍允许进入股票详情页。
3. 涨跌停统计与分布：领涨股行整行可点击进入股票详情页。
4. 个股新闻：本轮不跳转股票详情；后续若要支持新闻主体跳转，必须单独定义 subject 点击口径。

---

## 1. 目标

把市场总览页中已经展示股票主体的入口，统一串联到股票详情页：

```text
/wealth/market/stock/:tsCode
```

其中 `tsCode` 使用当前前端与后端契约中的标准证券代码，例如：

```text
/wealth/market/stock/002245.SZ
/wealth/market/stock/603806.SH
```

本轮目标不是新增股票详情页能力，也不是改股票详情页数据源；只把市场总览中已有股票入口接到现有股票详情路由。

---

## 2. 当前代码事实

### 2.1 股票详情路由已存在

当前 `WealthRouter` 已支持：

```text
/wealth/market/stock/:tsCode
```

命中后渲染 `StockDetailPage`。

代码依据：

1. `/Users/congming/github/goldenshare/wealth/src/app/routes/WealthRouter.tsx`
2. `/Users/congming/github/goldenshare/wealth/src/app/routes/routerState.ts`

### 2.2 市场总览入口仍是 toast 或展示态

当前 `MarketOverviewPage` 把 `showToast` 传给多个模块。部分模块虽然文案写着“进入个股详情”，但实际只是显示 toast，没有真实导航。

代码依据：

1. `/Users/congming/github/goldenshare/wealth/src/pages/market-overview/MarketOverviewPage.tsx`
2. `/Users/congming/github/goldenshare/wealth/src/features/market-overview/leaderboards/LeaderboardPanel.tsx`
3. `/Users/congming/github/goldenshare/wealth/src/features/market-overview/limit-up/StreakLadderPanel.tsx`
4. `/Users/congming/github/goldenshare/wealth/src/features/market-overview/limit-up/LimitBoardPanel.tsx`

---

## 3. 接入范围

本轮只接入以下 3 类股票入口。

| 模块 | 当前展示 | 当前行为 | 接入目标 |
|---|---|---|---|
| 榜单速览 | 股票名称、股票代码 | 行点击触发 toast | 点击榜单行进入股票详情 |
| 连板天梯 | 股票卡片中的股票名称、股票代码 | 卡片点击触发 toast | 点击股票卡片进入股票详情 |
| 涨跌停统计与分布 | 领涨股涨停表现中的股票名称、股票代码 | 仅 hover 选中，无 click | 点击领涨股行进入股票详情 |

### 3.1 榜单速览

目标文件：

```text
wealth/src/features/market-overview/leaderboards/LeaderboardPanel.tsx
```

当前入口：

1. `LeaderboardTableRow`
2. `row.name`
3. `row.code`

目标行为：

1. 点击榜单股票行整行，跳转到 `/wealth/market/stock/{row.code}`。
2. 榜单 tab 切换不受影响。
3. 榜单行内的价格、涨跌幅、换手率、量比、成交量、成交额等指标跟随整行点击，不单独定义其它行为。
4. 视觉保持现状，不新增明显按钮风格。

### 3.2 连板天梯

目标文件：

```text
wealth/src/features/market-overview/limit-up/StreakLadderPanel.tsx
```

当前入口：

1. `renderCard(stock, mode)`
2. `stock.stockName`
3. `stock.stockCode`

目标行为：

1. 每张股票卡片代表一个股票主体，点击整张股票卡片进入 `/wealth/market/stock/{stock.stockCode}`。
2. 停牌、缺行情、掉队股票仍然可进入股票详情页；行情状态不作为跳转门禁。
3. 展开/收起按钮只控制天梯层级，不触发股票跳转。
4. 视觉保持现状。

### 3.3 涨跌停统计与分布

目标文件：

```text
wealth/src/features/market-overview/limit-up/LimitBoardPanel.tsx
```

当前入口：

1. `LeaderPerformanceRow`
2. `stock.stockName`
3. `stock.stockCode`

目标行为：

1. 点击“领涨股涨停表现”中的股票行，进入 `/wealth/market/stock/{stock.stockCode}`。
2. hover 选中逻辑保留。
3. 板块分布行仍只负责切换板块，不进入股票详情。
4. 视觉保持现状。

---

## 4. 非接入范围

以下内容本轮明确不接入股票详情页。

| 模块 | 原因 |
|---|---|
| 顶部行情跑马灯 | 当前展示指数，不是股票 |
| 主要指数 | 当前展示指数，未来应接指数详情，不接股票详情 |
| 板块速览 | 当前展示行业、概念、地域、资金流、板块热力图，不是股票主体 |
| 新闻速览 | 当前无股票标识点击区域 |
| 个股新闻 | 当前契约 `clickable=false`，UI 只展示新闻标题；即使 API 有 `subjectCode`，本轮也不接入 |
| 市场客观总结、涨跌分布、市场风格、大盘资金流向 | 当前无股票名称或股票代码入口 |

约束：

1. 不得把指数代码误跳到股票详情页。
2. 不得把板块名称误跳到股票详情页。
3. 不得从新闻标题里解析股票名称或代码。
4. 不新增股票详情之外的新页面。

---

## 5. 路由与导航方案

### 5.1 统一路径生成

建议在路由工具中新增一个股票详情路径生成函数：

```ts
export function buildStockDetailPath(tsCode: string): string {
  return `/wealth/market/stock/${encodeURIComponent(tsCode.trim().toUpperCase())}`;
}
```

建议落点：

```text
wealth/src/app/routes/routerState.ts
```

原因：

1. 当前 `navigateWealth` 已在同文件中管理前端路由状态。
2. 路由路径集中管理，避免各模块手写 `/wealth/market/stock/` 字符串。
3. 后续如果路径改动，只改一个地方。

### 5.2 页面级导航函数

`MarketOverviewPage` 增加页面级函数：

```ts
const openStockDetail = (tsCode: string) => {
  navigateWealth(buildStockDetailPath(tsCode));
};
```

页面负责导航编排，模块组件只负责上报股票选择事件。

### 5.3 模块 props 口径

新增统一回调：

```ts
onStockSelect: (tsCode: string) => void
```

约束：

1. 股票入口必须调用 `onStockSelect(tsCode)`。
2. 不允许继续用 `onAction("进入个股详情：xxx")` 字符串表达股票跳转。
3. 非股票交互仍可保留 `onAction`，例如板块热力图、快捷入口、导航占位 toast。

---

## 6. 组件改造点

### 6.1 `MarketOverviewPage`

目标文件：

```text
wealth/src/pages/market-overview/MarketOverviewPage.tsx
```

改造点：

1. 从路由工具引入 `navigateWealth` 与 `buildStockDetailPath`。
2. 新增 `openStockDetail(tsCode)`。
3. 给以下组件传入 `onStockSelect={openStockDetail}`：
   - `LeaderboardPanel`
   - `StreakLadderPanel`
   - `LimitBoardPanel`

不做：

1. 不改模块数据请求。
2. 不改页面布局。
3. 不改股票详情页加载逻辑。

### 6.2 `LeaderboardPanel`

目标文件：

```text
wealth/src/features/market-overview/leaderboards/LeaderboardPanel.tsx
```

改造点：

1. `LeaderboardPanelProps` 增加 `onStockSelect`。
2. `LeaderboardTableRow` 接收 `onStockSelect`。
3. 榜单行整行触发 `onStockSelect(row.code)`。

建议交互：

1. 榜单行使用可访问的 click target 或等价语义，不额外拆出单元格按钮。
2. `aria-label` 使用：`查看股票详情：{row.name} {row.code}`。
3. 保持当前表格视觉，不出现默认按钮边框和背景。

### 6.3 `StreakLadderPanel`

目标文件：

```text
wealth/src/features/market-overview/limit-up/StreakLadderPanel.tsx
```

改造点：

1. `StreakLadderPanelProps` 增加 `onStockSelect`。
2. 股票卡片点击调用 `onStockSelect(stock.stockCode)`。
3. 卡片 title 保留当前行情说明。
4. 展开/收起按钮必须阻断自身点击，不触发股票跳转。

### 6.4 `LimitBoardPanel`

目标文件：

```text
wealth/src/features/market-overview/limit-up/LimitBoardPanel.tsx
```

改造点：

1. `LimitBoardPanelProps` 增加 `onStockSelect`。
2. `LimitStructureBlock` 传递 `onStockSelect`。
3. `LeaderPerformanceRow` 增加点击行为：`onStockSelect(stock.stockCode)`。
4. hover 选中逻辑保持不变。

建议交互：

1. 整个领涨股行作为股票主体可点击。
2. `aria-label` 使用：`查看股票详情：{stock.stockName} {stock.stockCode}`。
3. 保持当前 `leader-performance-row` 视觉。

---

## 7. 测试计划

### 7.1 前端行为测试

目标文件：

```text
wealth/src/pages/market-overview/MarketOverviewPage.test.tsx
```

必须覆盖：

1. 点击榜单速览中的股票行，路由切到 `/wealth/market/stock/{tsCode}`。
2. 点击连板天梯股票卡片，路由切到 `/wealth/market/stock/{tsCode}`。
3. 点击涨跌停统计与分布的领涨股行，路由切到 `/wealth/market/stock/{tsCode}`。
4. 点击主要指数，不跳股票详情。
5. 点击板块速览，不跳股票详情。
6. 个股新闻仍不可点击，不跳股票详情。

### 7.2 组件级测试

按现有测试结构补充或调整：

1. `LeaderboardPanel`：榜单行回调参数必须是 `row.code`。
2. `StreakLadderPanel`：股票卡片回调参数必须是 `stock.stockCode`。
3. `LimitBoardPanel`：领涨股行回调参数必须是 `stock.stockCode`。

### 7.3 回归命令

```bash
cd wealth && npm run typecheck
cd wealth && npm run test
cd wealth && npm run build
```

涉及页面交互时，还需要人工浏览器验收：

```text
/wealth/market/overview
```

验收动作：

1. 点击榜单股票。
2. 返回市场总览，再点击连板天梯股票。
3. 返回市场总览，再点击涨跌停统计与分布中的领涨股。
4. 确认地址栏进入 `/wealth/market/stock/{tsCode}`。
5. 确认股票详情页正常加载对应股票。

---

## 8. 风险与控制

### 8.1 误跳指数或板块

风险：

1. 顶部跑马灯和主要指数也有代码。
2. 板块速览也有名称和点击态。

控制：

1. 只给股票数据结构传 `onStockSelect`。
2. 非股票模块继续走 `onAction` 或原有占位行为。
3. 测试加入“主要指数不跳股票详情”和“板块速览不跳股票详情”。

### 8.2 字符串式 action 漂移

风险：

当前已有 `onAction("进入个股详情：xxx")` 这种字符串式行为，后续容易靠解析字符串做跳转。

控制：

1. 股票跳转必须使用结构化回调 `onStockSelect(tsCode)`。
2. 不允许解析 `onAction` 字符串。

### 8.3 样式漂移

风险：

把 `div/tr` 改成 button 后可能出现默认按钮样式。

控制：

1. 保持原 class。
2. 对新增 button/link 样式做 reset。
3. 浏览器验收只检查交互与视觉，不调整其它模块样式。

---

## 9. 实施步骤

1. 在 `routerState.ts` 增加 `buildStockDetailPath(tsCode)`。
2. 在 `MarketOverviewPage.tsx` 增加 `openStockDetail`。
3. 改造 `LeaderboardPanel`：榜单行调用 `onStockSelect`。
4. 改造 `StreakLadderPanel`：股票卡片调用 `onStockSelect`。
5. 改造 `LimitBoardPanel`：领涨股行调用 `onStockSelect`。
6. 补前端测试，覆盖正向入口和负向非入口。
7. 执行 `typecheck/test/build`。
8. 浏览器人工验收 3 类入口。

---

## 10. 验收标准

1. 榜单速览股票行点击进入对应股票详情页。
2. 连板天梯股票卡片点击进入对应股票详情页。
3. 涨跌停统计与分布的领涨股行点击进入对应股票详情页。
4. 主要指数、顶部指数跑马灯、板块速览、新闻不进入股票详情页。
5. 市场总览布局和视觉不因本轮改造发生明显变化。
6. 股票详情页不因本轮改造改变数据请求或展示逻辑。
7. 自动化测试覆盖正向与负向入口。

---

## 11. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-06-24 | 基于当前代码审计，新增市场总览股票详情入口接入方案 | Codex |
| v1.1 | 2026-06-24 | 同步拍板口径：榜单整行跳转、连板异常态可跳转、领涨股整行跳转、个股新闻不跳转 | Codex |
