# 市场总览｜股票详情入口接入 LLD v1

> 状态：Draft / 待评审  
> 上游方案：`wealth/docs/pages/market-overview/stock-detail-entry-integration-plan-v1.md`  
> 范围：只设计市场总览页中股票主体点击进入股票详情页的代码级落地方案。  
> 本文不实现代码；后续编码必须逐条对照本文。

---

## 1. 本轮目标

把市场总览页中明确代表股票主体的入口，接到既有股票详情路由：

```text
/wealth/market/stock/:tsCode
```

本轮只做前端路由串联与交互回调治理：

1. 榜单速览：榜单行整行点击进入股票详情。
2. 连板天梯：股票卡片点击进入股票详情；停牌、缺行情、掉队股票仍允许进入。
3. 涨跌停统计与分布：领涨股行整行点击进入股票详情。
4. 个股新闻：本轮不跳转。

---

## 2. 硬约束

1. 不改后端 API。
2. 不改股票详情页数据请求、展示逻辑或加载状态。
3. 不改市场总览模块数据源，不切换 mock/real source。
4. 不新增页面，不新增指数详情、板块详情、新闻详情。
5. 不解析 `onAction("进入个股详情：xxx")` 字符串做跳转。
6. 股票跳转必须走结构化回调：`onStockSelect(tsCode)`。
7. 页面层统一负责导航，模块层只上报股票代码。
8. 视觉保持当前样式，不新增按钮外观，不重排模块。
9. 非股票主体不得误跳股票详情：主要指数、顶部指数跑马灯、板块速览、新闻标题均不接入。

---

## 3. 代码审计结论

### 3.1 路由能力已存在

文件：

```text
wealth/src/app/routes/WealthRouter.tsx
wealth/src/app/routes/routerState.ts
```

当前事实：

1. `WealthRouter` 已通过 `parseStockDetailTsCode(pathname)` 支持 `/market/stock/:tsCode` 与 `/wealth/market/stock/:tsCode`。
2. 命中后渲染 `<StockDetailPage tsCode={stockDetailTsCode} />`。
3. `routerState.ts` 当前有 `navigateWealth(path)`，会 `pushState/replaceState` 并派发 `wealth-route-change`。
4. `routerState.ts` 当前没有股票详情 path builder。

结论：

1. 不需要新增路由分支。
2. 只需要在 `routerState.ts` 增加统一的 `buildStockDetailPath(tsCode)`，避免页面或模块手写路径。

### 3.2 市场总览页当前仍使用 toast 占位

文件：

```text
wealth/src/pages/market-overview/MarketOverviewPage.tsx
```

当前事实：

1. 页面维护 `toast` 状态。
2. `showToast(message)` 只负责展示页面 toast。
3. `LeaderboardPanel` 当前接收 `onAction={showToast}`。
4. `StreakLadderPanel` 当前接收 `onAction={showToast}`。
5. `LimitBoardPanel` 当前没有接收股票选择回调。

结论：

1. `showToast` 继续保留给非股票动作。
2. 页面新增 `openStockDetail(tsCode)`，内部调用 `navigateWealth(buildStockDetailPath(tsCode))`。
3. 页面向股票入口模块传 `onStockSelect={openStockDetail}`。

### 3.3 榜单速览当前行点击只是 toast

文件：

```text
wealth/src/features/market-overview/leaderboards/LeaderboardPanel.tsx
```

当前事实：

1. `LeaderboardPanelProps` 只有 `onAction(message)`，没有 `onStockSelect`。
2. `LeaderboardTableRow` 当前 `onClick={() => onAction(\`进入个股详情：${row.code}\`)}`。
3. 表格行已经有 hover、active、cursor 样式。

结论：

1. 不需要新增视觉样式。
2. 要把 `onAction` 的股票跳转用途替换为 `onStockSelect(row.code)`。
3. 榜单行整行点击，不拆成股票单元格点击。

### 3.4 连板天梯当前卡片点击只是 toast

文件：

```text
wealth/src/features/market-overview/limit-up/StreakLadderPanel.tsx
```

当前事实：

1. `StreakLadderPanelProps` 只有 `onAction(message)`，没有 `onStockSelect`。
2. `renderCard(stock, mode)` 当前卡片 `onClick={() => onAction(\`进入个股详情：${stock.stockCode}\`)}`。
3. 卡片已有 `stock-compact-card-v5` hover、cursor、状态样式。
4. 停牌或缺行情时，卡片仍展示 `stockName/stockCode/停牌/--` 等信息。

结论：

1. 卡片点击改为 `onStockSelect(stock.stockCode)`。
2. 不以 `quoteStatus` 作为跳转门禁。
3. 展开/收起按钮只控制层级展开，不允许触发股票详情导航。

### 3.5 涨跌停统计与分布当前领涨股行只 hover

文件：

```text
wealth/src/features/market-overview/limit-up/LimitBoardPanel.tsx
```

当前事实：

1. `LimitBoardPanelProps` 当前没有 `onAction` 或 `onStockSelect`。
2. `LimitStructureBlock` 内部维护 `selectedSectorCode`、`selectedStockCode`。
3. `sector-bar-row` 只代表板块，当前 hover 切换板块。
4. `LeaderPerformanceRow` 代表单一股票，当前只有 `onMouseEnter`，没有 click。
5. `leader-performance-row` 已有 cursor、hover、selected 样式。

结论：

1. 只给 `LeaderPerformanceRow` 增加整行点击。
2. `sector-bar-row` 不得接入股票详情。
3. `hover` 选中逻辑必须保留。

### 3.6 新闻与指数不是本轮股票入口

文件：

```text
wealth/src/features/market-overview/news/MarketNewsPanel.tsx
wealth/src/features/market-overview/indices/MajorIndexPanel.tsx
wealth/src/shared/ui/top-market-bar/TopMarketBar.tsx
```

当前事实：

1. `MarketNewsPanel` 的新闻 item 当前 `aria-disabled="true"`，只展示新闻时间与标题。
2. `MajorIndexPanel` 当前点击指数卡片只走 `onAction("进入详情：indexCode")`。
3. `TopMarketBar` 展示的是主要指数行情条。

结论：

1. 个股新闻本轮不接入股票详情。
2. 主要指数与顶部跑马灯不接股票详情。
3. 不能从新闻标题或指数代码中推断股票跳转。

---

## 4. 目标数据流

```text
用户点击股票主体
  ↓
模块组件调用 onStockSelect(tsCode)
  ↓
MarketOverviewPage.openStockDetail(tsCode)
  ↓
buildStockDetailPath(tsCode)
  ↓
navigateWealth("/wealth/market/stock/{tsCode}")
  ↓
WealthRouter 收到 wealth-route-change
  ↓
parseStockDetailTsCode(pathname)
  ↓
StockDetailPage(tsCode)
```

职责边界：

1. 模块组件只知道“用户点了哪个股票代码”。
2. 页面层知道“点击股票代码后应该跳到股票详情页”。
3. 路由工具知道“股票详情路径怎么生成”。
4. 股票详情页继续负责“如何加载并展示该股票数据”。

---

## 5. 文件级改造设计

### 5.1 `routerState.ts`

目标文件：

```text
wealth/src/app/routes/routerState.ts
```

新增函数：

```ts
export function buildStockDetailPath(tsCode: string): string {
  const normalized = tsCode.trim().toUpperCase();
  return `/wealth/market/stock/${encodeURIComponent(normalized)}`;
}
```

设计约束：

1. 只做路径生成，不做导航。
2. 只做 `trim + toUpperCase + encodeURIComponent`。
3. 不做股票代码合法性校验；合法性来自模块数据契约。
4. 不做空值 fallback；调用方不得传空字符串。
5. 不修改 `parseStockDetailTsCode`，不修改现有登录重定向逻辑。

测试要求：

1. `buildStockDetailPath("002245.sz")` 返回 `/wealth/market/stock/002245.SZ`。
2. `buildStockDetailPath(" 603806.SH ")` 返回 `/wealth/market/stock/603806.SH`。

### 5.2 `MarketOverviewPage.tsx`

目标文件：

```text
wealth/src/pages/market-overview/MarketOverviewPage.tsx
```

新增 import：

```ts
import { buildStockDetailPath, navigateWealth } from "../../app/routes/routerState";
```

新增页面函数：

```ts
const openStockDetail = (tsCode: string) => {
  navigateWealth(buildStockDetailPath(tsCode));
};
```

组件传参调整：

```tsx
<LeaderboardPanel
  ...
  onAction={showToast}
  onStockSelect={openStockDetail}
/>

<LimitBoardPanel
  ...
  onStockSelect={openStockDetail}
/>

<StreakLadderPanel
  ...
  onAction={showToast}
  onStockSelect={openStockDetail}
/>
```

设计约束：

1. `showToast` 保留给非股票动作。
2. `openStockDetail` 不展示 toast。
3. `openStockDetail` 不读接口、不读模块数据、不做业务判断。
4. 不改变页面 loading/error/ready 状态流。
5. 不改变 `TopMarketBar`、`MajorIndexPanel`、`MarketNewsPanel`、`SectorOverviewPanel` 的行为。

### 5.3 `LeaderboardPanel.tsx`

目标文件：

```text
wealth/src/features/market-overview/leaderboards/LeaderboardPanel.tsx
```

Props 设计：

```ts
interface LeaderboardPanelProps {
  viewState: "loading" | "ready" | "error";
  leaderboards?: MarketLeaderboardsViewModel;
  errorMessage?: string;
  onAction: (message: string) => void;
  onStockSelect: (tsCode: string) => void;
}
```

`LeaderboardTableRow` 参数设计：

```ts
function LeaderboardTableRow({
  row,
  onStockSelect,
}: {
  row: MarketLeaderboardsViewModel["tabs"][number]["rows"][number];
  onStockSelect: (tsCode: string) => void;
}) {
  ...
}
```

行点击设计：

```tsx
<tr
  aria-label={`查看股票详情：${row.name} ${row.code}`}
  onClick={() => onStockSelect(row.code)}
>
```

设计约束：

1. 榜单行整行点击。
2. 不再用 `onAction("进入个股详情：...")` 表达股票跳转。
3. `onAction` 仍可保留给未来非股票交互；如果本文件暂时无非股票 `onAction` 消费，也不要用它承载股票跳转。
4. 不改 columns、tab、排序、数据字段。
5. 不新增按钮元素，避免表格视觉漂移。

### 5.4 `StreakLadderPanel.tsx`

目标文件：

```text
wealth/src/features/market-overview/limit-up/StreakLadderPanel.tsx
```

Props 设计：

```ts
interface StreakLadderPanelProps {
  overview: MarketOverview;
  ladder?: MarketOverview["ladderV5"];
  viewState?: "loading" | "ready" | "error";
  errorMessage?: string;
  onAction: (message: string) => void;
  onStockSelect: (tsCode: string) => void;
}
```

卡片点击设计：

```tsx
<article
  ...
  aria-label={`查看股票详情：${stock.stockName} ${stock.stockCode}`}
  onClick={() => onStockSelect(stock.stockCode)}
>
```

展开按钮防误触设计：

```tsx
onClick={(event) => {
  event.stopPropagation();
  toggleLayer(layer.key);
}}
```

设计约束：

1. 所有股票卡片均可跳转，包括 `quoteStatus !== "READY"` 的卡片。
2. `quoteUnavailable` 只影响展示，不影响跳转。
3. 展开/收起按钮只展开收起，不跳转。
4. 不改天梯层级排序、折叠数量、卡片视觉。
5. `titleText` 可继续使用现有说明文案，但股票跳转行为不得再依赖 title 或 toast 文案。

### 5.5 `LimitBoardPanel.tsx`

目标文件：

```text
wealth/src/features/market-overview/limit-up/LimitBoardPanel.tsx
```

Props 设计：

```ts
interface LimitBoardPanelProps {
  viewState: "loading" | "ready" | "error";
  limitUp?: MarketLimitUpViewModel;
  errorMessage?: string;
  onStockSelect: (tsCode: string) => void;
}
```

传递链路：

```text
LimitBoardPanel
  -> LimitStructureBlock
    -> LeaderPerformanceRow
```

`LimitStructureBlock` 参数：

```ts
function LimitStructureBlock({
  label,
  structure,
  onStockSelect,
}: {
  label: string;
  structure: LimitSectorLeaderStructureView;
  onStockSelect: (tsCode: string) => void;
}) {
  ...
}
```

`LeaderPerformanceRow` 参数：

```ts
function LeaderPerformanceRow({
  onMouseEnter,
  onStockSelect,
  selected,
  stock,
}: {
  onMouseEnter: () => void;
  onStockSelect: (tsCode: string) => void;
  selected: boolean;
  stock: LimitLeaderPerformanceItemView;
}) {
  ...
}
```

领涨股行点击设计：

```tsx
<div
  className={`leader-performance-row${selected ? " selected" : ""}`}
  onMouseEnter={onMouseEnter}
  onClick={() => onStockSelect(stock.stockCode)}
  aria-label={`查看股票详情：${stock.stockName} ${stock.stockCode}`}
  title={`${stock.stockName}｜...`}
>
```

设计约束：

1. `LeaderPerformanceRow` 整行可点击。
2. `onMouseEnter` 继续保留，用于选中展示。
3. `sector-bar-row` 不增加 `onStockSelect`。
4. “更多 N 只涨停股”不接股票详情，因为它不是单一股票主体。
5. 不改历史柱图、不改 RangeSwitch、不改统计卡。

---

## 6. 可访问性与交互细节

### 6.1 可访问性

最低要求：

1. 三类股票入口必须有 `aria-label`，格式统一为：

```text
查看股票详情：{stockName} {tsCode}
```

2. 不把新闻、板块、指数伪装成股票详情入口。

建议：

1. 榜单 `<tr>` 与领涨股 `<div>` 已有 hover/cursor，首轮可不引入额外 button，避免表格视觉漂移。
2. 若后续需要键盘可达，再单独评审是否改为 button 或增加 `role="button"`、`tabIndex={0}`、键盘事件。首轮不强行扩大。

### 6.2 交互冲突处理

1. 榜单 tab 按钮只切 tab，不跳股票详情。
2. 连板天梯展开/收起按钮只展开，不跳股票详情。
3. 涨跌停板块分布行只切板块，不跳股票详情。
4. 个股新闻 item 本轮继续 `aria-disabled="true"`。

---

## 7. 测试设计

### 7.1 页面级行为测试

目标文件：

```text
wealth/src/pages/market-overview/MarketOverviewPage.test.tsx
```

新增测试建议分组：

```ts
describe("stock detail entry navigation", () => {
  ...
});
```

必须覆盖：

1. 点击榜单速览股票行后，`window.location.pathname === "/wealth/market/stock/00001.SZ"` 或对应 mock 中的股票代码路径。
2. 点击连板天梯股票卡片后，进入对应 `/wealth/market/stock/{stockCode}`。
3. 点击涨跌停统计与分布领涨股行后，进入对应 `/wealth/market/stock/{stockCode}`。
4. 点击主要指数卡，不进入 `/wealth/market/stock/*`。
5. 点击板块速览区域，不进入 `/wealth/market/stock/*`。
6. 个股新闻仍不可点击，不进入股票详情。

实现建议：

1. 测试前把 `window.history.pushState({}, "", "/wealth/market/overview")`。
2. 使用已有 `mockSuccessfulMarketFetch()`。
3. 点击后无需渲染完整 `WealthRouter`，可直接断言 `window.location.pathname`，因为 `navigateWealth` 会调用 `pushState`。
4. 若点击后渲染进入股票详情导致接口请求复杂化，不要在本测试里引入真实股票详情 API；本测试只验证路径变化。

### 7.2 路由工具测试

可放在现有页面测试中，也可新增：

```text
wealth/src/app/routes/routerState.test.ts
```

必须覆盖：

1. `buildStockDetailPath("002245.sz")` 大写化。
2. `buildStockDetailPath(" 603806.SH ")` trim。
3. 特殊字符通过 `encodeURIComponent` 编码。

### 7.3 组件回调测试

如果后续补组件级测试，建议覆盖：

1. `LeaderboardPanel`：点击行调用 `onStockSelect(row.code)`。
2. `StreakLadderPanel`：点击卡片调用 `onStockSelect(stock.stockCode)`；点击展开按钮不调用 `onStockSelect`。
3. `LimitBoardPanel`：点击领涨股行调用 `onStockSelect(stock.stockCode)`；hover 仍调用选中逻辑。

### 7.4 负向残留检查

编码完成后执行：

```bash
rg -n "onAction\\(`进入个股详情|onAction\\(\"进入个股详情" wealth/src/features/market-overview wealth/src/pages/market-overview
```

预期：

```text
无结果
```

---

## 8. 验证命令

编码完成后执行：

```bash
cd wealth && npm run typecheck
cd wealth && npm run test
cd wealth && npm run build
```

人工验收路径：

```text
/wealth/market/overview
```

人工验收动作：

1. 点击榜单任一股票行，确认进入 `/wealth/market/stock/{tsCode}`。
2. 返回市场总览，点击连板天梯股票卡片，确认进入股票详情。
3. 返回市场总览，点击涨跌停统计与分布领涨股行，确认进入股票详情。
4. 点击主要指数卡，只保留原有占位行为，不进入股票详情。
5. 点击板块速览，不进入股票详情。
6. 点击或 hover 个股新闻，不进入股票详情。

---

## 9. 推进步骤

### M1：路由工具收口

1. 在 `routerState.ts` 新增 `buildStockDetailPath(tsCode)`。
2. 补路由工具测试或页面级路径断言。

验收：

1. path builder 大写、trim、encode 行为正确。
2. 不改 `WealthRouter` 的 parse 逻辑。

### M2：页面级导航函数

1. `MarketOverviewPage.tsx` 引入 `buildStockDetailPath` 与 `navigateWealth`。
2. 新增 `openStockDetail(tsCode)`。
3. 向三类股票入口模块传 `onStockSelect`。

验收：

1. `showToast` 仍用于非股票动作。
2. `openStockDetail` 不包含业务判断。

### M3：榜单速览接入

1. `LeaderboardPanelProps` 增加 `onStockSelect`。
2. `LeaderboardTableRow` 用 `onStockSelect(row.code)` 替代 `onAction("进入个股详情...")`。
3. 保持整行点击与现有表格样式。

验收：

1. 点击榜单行进入股票详情。
2. 榜单 tab 切换不受影响。

### M4：连板天梯接入

1. `StreakLadderPanelProps` 增加 `onStockSelect`。
2. 股票卡片点击调用 `onStockSelect(stock.stockCode)`。
3. 展开/收起按钮阻断自身点击，不触发股票导航。
4. 停牌、缺行情、掉队股票不做跳转拦截。

验收：

1. 任意股票卡片进入股票详情。
2. 展开按钮只展开，不跳转。

### M5：涨跌停统计与分布接入

1. `LimitBoardPanelProps` 增加 `onStockSelect`。
2. `LimitStructureBlock` 透传 `onStockSelect`。
3. `LeaderPerformanceRow` 整行点击调用 `onStockSelect(stock.stockCode)`。
4. 板块行不接股票跳转。

验收：

1. 领涨股行进入股票详情。
2. 板块分布行只切换板块。

### M6：测试与残留清理

1. 补页面级正向入口测试。
2. 补非入口负向测试。
3. 执行残留检查，清掉 `onAction("进入个股详情...")`。
4. 执行 `typecheck/test/build`。

验收：

1. 自动化测试通过。
2. 负向残留检查无结果。
3. 市场总览视觉无明显变化。

---

## 10. 计划对账清单

| 计划口径 | LLD 落点 | 测试落点 |
|---|---|---|
| 榜单速览整行跳转 | `LeaderboardTableRow.onClick -> onStockSelect(row.code)` | 点击榜单行进入股票详情 |
| 连板异常态可跳转 | `StreakLadderPanel.renderCard` 不判断 `quoteStatus` | 停牌/缺行情样本可点击，或至少断言不被禁用 |
| 涨跌停领涨股整行跳转 | `LeaderPerformanceRow.onClick -> onStockSelect(stock.stockCode)` | 点击领涨股行进入股票详情 |
| 个股新闻不跳转 | `MarketNewsPanel` 不新增回调 | 点击/查询新闻 item 不改变为股票详情路径 |
| 页面层负责导航 | `MarketOverviewPage.openStockDetail` | 三类模块点击后路径变化一致 |
| 模块只上报股票代码 | `onStockSelect(tsCode)` props | 组件级或页面级断言传入路径只来自 stock code |
| 禁止字符串 action 承载股票跳转 | 删除 `onAction("进入个股详情...")` | `rg` 负向检查 |

---

## 11. 风险与控制

### 11.1 表格行可访问性不足

风险：

1. `<tr onClick>` 对键盘用户不如 button 友好。

控制：

1. 首轮遵循“视觉不漂移”优先，保持现有表格结构。
2. 增加 `aria-label`。
3. 键盘可达优化单独评审，不混入本轮。

### 11.2 非股票主体误跳

风险：

1. 指数、板块、新闻也有点击或代码。

控制：

1. 只给三类股票入口传 `onStockSelect`。
2. 负向测试覆盖主要指数、板块速览、个股新闻。

### 11.3 字符串 action 残留

风险：

1. 未来继续靠 `onAction("进入个股详情...")` 表达真实导航。

控制：

1. 本轮清零股票跳转字符串 action。
2. 增加 `rg` 负向检查。

### 11.4 连板展开按钮误触

风险：

1. 如果按钮事件冒泡到股票卡片，会误进入详情。

控制：

1. 展开按钮显式 `event.stopPropagation()`。
2. 测试点击展开按钮不改变路径。

---

## 12. 交付边界

本 LLD 通过后，下一轮编码交付只应包含：

1. `wealth/src/app/routes/routerState.ts`
2. `wealth/src/pages/market-overview/MarketOverviewPage.tsx`
3. `wealth/src/features/market-overview/leaderboards/LeaderboardPanel.tsx`
4. `wealth/src/features/market-overview/limit-up/StreakLadderPanel.tsx`
5. `wealth/src/features/market-overview/limit-up/LimitBoardPanel.tsx`
6. `wealth/src/pages/market-overview/MarketOverviewPage.test.tsx`
7. 可选：`wealth/src/app/routes/routerState.test.ts`
8. 必要时同步本文档和上游 plan 文档

不应包含：

1. 后端 API 文件。
2. 股票详情页业务逻辑。
3. 市场总览视觉重排。
4. 新闻主体跳转。
5. 指数或板块详情跳转。

---

## 13. CodeGraph 分析记录

本轮已使用 CodeGraph 分析以下范围：

1. `MarketOverviewPage`
2. `LeaderboardPanel`
3. `StreakLadderPanel`
4. `LimitBoardPanel`
5. `navigateWealth`
6. `WealthRouter`
7. `StockDetailPage`

CodeGraph 结论：

1. `WealthRouter -> StockDetailPage` 路由链路已存在。
2. 三类市场总览股票入口当前未接真实导航。
3. 本轮影响面集中在 wealth 前端页面装配与三个 market-overview feature 组件。
4. 不涉及后端 API、TaskRun、数据集、数据库或真实行情查询链路。

---

## 14. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-06-24 | 基于接入方案和当前代码审计，新增股票详情入口接入 LLD | Codex |

---

## 15. 实施记录

| 阶段 | 状态 | 代码落点 | 验证/对账 |
|---|---|---|---|
| M1：路由工具收口 | 已落地 | `wealth/src/app/routes/routerState.ts`、`wealth/src/app/routes/routerState.test.ts` | 新增 `buildStockDetailPath(tsCode)`，覆盖 trim、大写和路径段编码；未修改 `WealthRouter` parse 逻辑 |
| M2：页面级导航函数 | 已落地 | `wealth/src/pages/market-overview/MarketOverviewPage.tsx` | 新增 `openStockDetail(tsCode)`，统一调用 `navigateWealth(buildStockDetailPath(tsCode))`；组件传参按 M3-M5 分模块落地，避免中间提交破坏类型检查 |
| M3：榜单速览接入 | 已落地 | `wealth/src/features/market-overview/leaderboards/LeaderboardPanel.tsx`、`wealth/src/pages/market-overview/MarketOverviewPage.tsx`、`wealth/src/pages/market-overview/MarketOverviewPage.test.tsx` | 榜单行整行调用 `onStockSelect(row.code)`；清除榜单中的 `onAction("进入个股详情...")`；页面测试覆盖榜单行跳转 `/wealth/market/stock/{tsCode}` |
