# 财势乾坤行情系统 · Component Catalog v13

> 本文档对应 `caishiqiankun_design_system_v13.md` 与 `caishiqiankun_component_showcase_v13.html`。  
> 目标：给 Codex / 前端开发提供组件级落地说明，避免每次原型迭代后组件风格漂移。

---

## 0. 文件分工

| 文件 | 职责 |
|---|---|
| `caishiqiankun_design_system_v13.md` | 设计原则、Token、交互规则、评审红线 |
| `caishiqiankun_component_showcase_v13.html` | 可视化组件展示 |
| `caishiqiankun_component_catalog_v13.md` | 本文：组件职责、Props、使用规则、数据结构 |

---

## 1. 技术栈建议

当前组件可落地到 Vue 或 React。若使用 Vue 3 + Element Plus / pure-admin-thin，建议保留领域组件命名，不要让 Element Plus 默认样式主导视觉。

推荐：

```text
Vue 3 + TypeScript + Vite
CSS Variables + CSS Modules / scoped css
ECharts for financial charts
dayjs for date formatting
```

不建议：

- 直接使用 Ant Design Pro 默认风格。
- 使用亮蓝/紫色作为主视觉。
- 在业务组件中写死颜色值。
- 将行情涨跌色映射为 danger/success。

---

## 2. Token 使用约定

### 2.1 CSS 变量语义

| 变量 | 用途 |
|---|---|
| `--bg-page` | 页面背景 |
| `--bg-panel` | 一级面板 |
| `--bg-card` | 子卡片 |
| `--border-default` | 常规边框 |
| `--text-primary` | 标题、主文本 |
| `--text-secondary` | 辅助文本 |
| `--color-rise` | 上涨、涨停 |
| `--color-fall` | 下跌、跌停 |
| `--color-flat` | 中性、观察 |
| `--color-info` | 系统信息 |

### 2.2 趋势枚举

```ts
type Trend = 'rise' | 'fall' | 'flat';
```

规则：

```ts
const trendClassMap = {
  rise: 'is-rise',
  fall: 'is-fall',
  flat: 'is-flat',
};
```

---

## 3. UI 通用组件

### 3.1 AppShell

页面根容器。

```ts
interface AppShellProps {
  title: string;
  subtitle?: string;
  activePage: string;
  pages: NavItem[];
}
```

职责：

- 控制最大宽度。
- 承载顶部品牌、导航、搜索、状态。
- 不处理具体业务数据。

### 3.2 Topbar

顶部栏。

字段：

| Prop | 类型 | 说明 |
|---|---|---|
| `brand` | string | 产品名 |
| `subtitle` | string | 当前版本 / 更新时间 |
| `navItems` | NavItem[] | 顶部导航 |
| `activeKey` | string | 当前页面 |
| `onNavChange` | function | 页面切换 |
| `searchPlaceholder` | string | 搜索占位 |
| `marketStatus` | string | 交易中 / 已收盘 |

状态：

- active
- hover
- disabled / coming soon

### 3.3 Panel

一级模块。

```ts
interface PanelProps {
  title: string;
  subtitle?: string;
  meta?: string;
  children: ReactNode;
}
```

使用场景：

- 市场总览
- 主要指数
- 成交额与涨跌分布
- 涨跌停板与连板天梯
- 新闻板块
- 操作建议

注意：

- Panel 内部不要直接写大量 grid，应拆成 `PanelBody` 或业务组件。
- Panel 标题不要超过 12 个字，长说明放 subtitle。

### 3.4 Tabs

用于模块内切换。

```ts
interface TabsProps {
  items: { key: string; label: string; disabled?: boolean }[];
  activeKey: string;
  onChange: (key: string) => void;
  size?: 'sm' | 'md';
}
```

使用场景：

- 领涨板块 / 领跌板块
- 今日热点 / 政策宏观 / 财经新闻 / 个股新闻
- 5日 / 10日 / 20日
- 按连板数 / 按行业

---

## 4. 行情领域组件

### 4.1 PriceText / ChangeText

显示价格、涨跌额、涨跌幅。

```ts
interface PriceTextProps {
  value: number | string;
  change?: number;
  changePct?: number;
  trend?: Trend;
  precision?: number;
}
```

规则：

- `trend='rise'` 使用红色。
- `trend='fall'` 使用绿色。
- 数字必须 tabular-nums。
- 正数必须显示 `+`。

### 4.2 MetricCard

指标卡。

```ts
interface MetricCardProps {
  label: string;
  value: string | number;
  unit?: string;
  trend?: Trend;
  badge?: string;
  description?: string;
  facts?: { label: string; value: string; trend?: Trend }[];
}
```

使用场景：

- 市场温度
- 情绪指数
- 今日成交额
- 主力净流向
- 晋级率
- 淘汰率

### 4.3 IndexCard

主要指数卡。

```ts
interface IndexCardProps {
  name: string;
  value: number;
  change: number;
  changePct: number;
  trend: Trend;
}
```

规则：

- 卡片内只保留指数名称、点位、涨跌额、涨跌幅。
- 不要在首页指数卡里堆标签。
- 右侧指数区域可用 4行3列或 2列4行，按布局选择。

### 4.4 RankList

榜单列表。

```ts
interface RankItem {
  rank: number;
  name: string;
  description: string;
  meta: string;
  changePct: number;
  trend: Trend;
}

interface RankListProps {
  title?: string;
  items: RankItem[];
}
```

使用场景：

- 板块领涨领跌
- 个股领涨领跌
- 新闻相关个股
- 热点题材榜

### 4.5 NewsTabs / NewsFeed

新闻模块。

```ts
type NewsCategory = 'hot' | 'macro' | 'finance' | 'stock';

interface NewsItem {
  category: NewsCategory;
  tag: string;
  title: string;
  summary: string;
  time: string;
  relatedSymbols?: string[];
}
```

规则：

- 首页新闻不追求多，最多 4–6 条。
- 新闻要服务于解释盘面，不要做普通资讯流。
- category 使用二级 tab：今日热点、政策宏观、财经新闻、个股新闻。

### 4.6 ActionAdvice

操作建议模块。

```ts
interface ActionAdviceVM {
  title: string;
  summary: string;
  recommendedPosition: string;
  strategy: string;
  doList: string[];
  avoidList: string[];
  risks: string[];
}
```

规则：

- 只给框架性建议，不做个股买卖指令。
- 建议应能由市场温度、情绪指数、成交额和主线板块推导出来。
- 需要保留风险提示。

---

## 5. 情绪分析组件

### 5.1 TurnoverOverview

今日成交额。

```ts
interface TurnoverTodayVM {
  amount: number;
  amountText: string;
  changeAmount: number;
  changePct: number;
  mainNetFlow: number;
  superLargeNetFlow?: number;
  volumeQuantile?: number;
  conclusion: string;
}
```

布局：

```text
今日成交额主数字
较昨日变化
三张小指标：主力净流向 / 超大单 / 量能分位
事实 chips
```

### 5.2 DistributionBars

今日涨跌分布。

```ts
interface DistributionBucket {
  label: string;
  count: number;
  trend: Trend | 'neutral';
  heightRatio: number;
}
```

规则：

- 区间从左到右：大涨 → 小涨 → 平盘 → 小跌 → 大跌。
- 红色表示上涨区间，绿色表示下跌区间。
- 柱状图下方必须有汇总：上涨家数、下跌家数、平盘、跌停。

### 5.3 HistoryLineChart

历史图表通用组件。

```ts
interface TimeSeriesPoint {
  date: string;
  turnover?: number;
  upCount?: number;
  downCount?: number;
  netFlow?: number;
}

interface HistoryLineChartProps {
  range: 5 | 10 | 20;
  data: TimeSeriesPoint[];
  series: ChartSeries[];
  onHoverDate?: (date: string) => void;
}
```

交互：

- hover 显示 tooltip。
- hover 日期时同步联动其他图。
- 5 / 10 / 20 日切换应保持 active 状态。
- Tooltip 不应遮挡鼠标。

### 5.4 MarketBreadthLinkage

成交额 × 市场广度联动观察。

```ts
interface MarketBreadthLinkageVM {
  date: string;
  turnover: number;
  upCount: number;
  downCount: number;
  netFlow: number;
  insight: string;
}
```

用途：

- 解释成交额变化是否带来赚钱效应。
- 判断是放量上涨、放量下跌、缩量修复还是缩量退潮。
- 作为历史成交额和历史涨跌之间的综合解读层。

### 5.5 LimitBoard

涨跌停板。

```ts
interface LimitBoardVM {
  limitUp: LimitMetric;
  limitUpSealRate: LimitMetric;
  limitUpOpen: LimitMetric;
  limitDown: LimitMetric;
  limitDownSealRate: LimitMetric;
  limitDownOpen: LimitMetric;
}

interface LimitMetric {
  label: string;
  today: number | string;
  yesterday: number | string;
  delta: number | string;
  trend: Trend;
}
```

布局规则：

```text
涨停板 | 涨停封板率 | 涨停打开 | 跌停板 | 跌停封板率 | 跌停打开
```

注意：

- 六张卡片必须内部结构一致。
- 涨停指标使用红色头部倾向。
- 跌停指标使用绿色头部倾向。
- 变化字段需要明确是改善还是恶化，不能仅显示数字。

### 5.6 LadderStage / LimitUpLadder

连板天梯。

```ts
interface LadderStageVM {
  level: string;           // 首板 / 2板 / 3板
  count: number;
  promotionRate: number;
  eliminationRate: number;
  hint: string;
  stocks: LadderStockVM[];
}

interface LadderStockVM {
  name: string;
  code?: string;
  theme: string;
  reason?: string;
  turnoverRate?: number;
  sealAmount?: number;
  status: string;
}
```

布局规则：

- 首板在左，高板在右。
- 每列固定结构：顶部 / 晋级淘汰 / 代表股票 / hint / 查看全部。
- 默认最多展示 3 只代表股。
- 完整列表通过 Drawer 查看。

### 5.7 LadderDrawer

连板股票抽屉。

```ts
interface LadderDrawerProps {
  open: boolean;
  stage: LadderStageVM;
  sortBy: 'sealAmount' | 'turnoverRate' | 'amount';
  keyword?: string;
}
```

抽屉内容：

- 标题：`3板 · 全部 5 只`
- 搜索框
- 排序按钮：封单、换手、成交额
- 股票列表：名称、题材、状态、封单 / 换手

---

## 6. 页面级组件

### 6.1 MarketHomePage

组合：

```text
Topbar
MarketOverviewPanel
IndexGridPanel
SectorLeaderPanel + StockLeaderPanel
NewsPanel + ActionAdvicePanel
```

数据入口：

```ts
interface MarketHomePageProps {
  data: MarketHomeViewModel;
  loading?: boolean;
  error?: Error;
}
```

### 6.2 EmotionAnalysisPage

组合：

```text
EmotionHero
TurnoverAndBreadthPanel
LimitAndLadderPanel
LadderDrawer
```

数据入口：

```ts
interface EmotionAnalysisPageProps {
  data: EmotionAnalysisViewModel;
  activeRange: 5 | 10 | 20;
  activeDate: string;
}
```

---

## 7. 状态规范

### 7.1 Loading

- Panel 内使用 skeleton。
- 图表使用灰色坐标骨架。
- 不使用全屏 loading。

### 7.2 Empty

文案结构：

```text
暂无数据
当前交易日尚未同步完成，请稍后刷新
```

### 7.3 Error

需要有：

- 错误原因。
- 重试按钮。
- 数据更新时间。

### 7.4 Stale Data

行情系统必须显示数据时间戳：

- 交易中超过 60s 未刷新：弱提醒。
- 超过 5min：显示“数据可能延迟”。
- 收盘后：显示“已收盘数据”。

---

## 8. Codex 实现提示词片段

```text
请按照 caishiqiankun_design_system_v13.md 和 caishiqiankun_component_catalog_v13.md 实现组件。
必须保持 A 股红涨绿跌。
不要直接使用第三方 UI 默认主题。
不要大面积渐变和强阴影。
所有颜色、字号、间距必须来自 CSS Token。
组件必须支持 loading / empty / error / stale 状态。
```

---

## 9. 验收清单

- [ ] 首页和情绪页可通过顶部 Tab 切换。
- [ ] 红涨绿跌无误。
- [ ] 今日成交额与今日涨跌分布平级。
- [ ] 历史成交额与历史涨跌可按 5/10/20 日切换。
- [ ] hover 历史图可联动解读卡。
- [ ] 涨跌停板六卡片横向对齐。
- [ ] 连板天梯首板在左，高板在右。
- [ ] 点击连板数量可打开 Drawer。
- [ ] 全部组件在 1280px 宽度下不破版。
- [ ] 组件风格与 V13 原型一致。
