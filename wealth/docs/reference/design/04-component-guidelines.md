# 财势乾坤｜P0 组件库与交互组件方案 v0.5 完整合并版

> 建议保存路径：`/docs/wealth/04-component-guidelines.md`  
> 负责人：`03_组件库与交互组件方案`  
> 状态：`Draft v0.5 merged-full / HTML Review v2 局部修订版`  
> 更新时间：`2026-05-07`  
> 本轮重点：只围绕“市场总览”桌面端落地收敛组件，不做大而全通用组件库。
> 合并说明：本版以 Google Drive 公共区 `04-component-guidelines.md` v0.4 merged-full 为基线，完整保留此前已确认内容；本轮只合并 Review v2 明确点名的四个区域，不主动重构其它组件。请勿用局部 delta 文档覆盖本文件。

---

## 0. 上游文档与本轮修订边界

### 0.1 上游文档

本文件基于以下文档约束修订：

1. `/docs/wealth/00-project-overview.md`
2. `/docs/wealth/prd/market-overview-prd.md`
3. `/docs/wealth/03-design-tokens.md`
4. `/mnt/data/docs/wealth/api/market-overview-api.md`

### 0.2 v0.3 相对 v0.1 / v0.2 的关键收敛

1. **市场总览归属乾坤行情**，不是独立一级菜单；组件命名和导航状态均按“财势乾坤 / 乾坤行情 / 市场总览”表达。
2. **市场总览桌面端不使用固定 SideNav**，不使用 PersistentLeftRail，不做大型左侧导航栏。
3. 市场总览桌面端框架固定为：`TopMarketBar + GlobalSystemMenu + IndexTickerStrip + Breadcrumb + PageHeader + ShortcutBar / QuickEntryCard + 全宽行情内容区`。
4. 市场总览只展示客观市场事实；快捷入口允许进入市场温度与情绪页，但**不在入口卡中展示市场温度、情绪指数、资金面分数、风险指数的数值或结论**。
5. API 字段使用财势乾坤业务命名；金额、成交量等单位默认遵循 API 字段说明、`unit`、`sourceRefs` 或当前落库口径，前端组件不擅自假设单位。
6. 所有行情方向显示必须遵守中国市场：**红涨、绿跌、灰平**。

### 0.3 本文件不是完整通用 UI Kit

本文件只定义市场总览 P0 落地所需的领域组件和必要容器组件。以下内容不在本轮展开：

- 通用 Button / Input / Select 全量组件库；
- 复杂主题编辑器；
- 移动端完整组件规范；
- K 线详情页完整图表引擎；
- 机会雷达、策略验证、持仓分析的完整组件系统。

---

## 1. 市场总览组件设计原则

### 1.1 行情终端优先

组件服务“高频看盘 + 快速下钻 + 事实判断”，不是官网展示，也不是低密度后台管理。视觉应保持：

- 高信息密度；
- 强数字可读性；
- 清晰分组；
- 弱装饰；
- 可长期盯屏；
- 不使用廉价大屏风、营销式 Hero Banner、过度霓虹动效。

### 1.2 横向空间优先

市场总览桌面端不使用固定 SideNav。横向空间优先给：

- 多个指数卡并排；
- 涨跌分布与历史趋势；
- 板块表格列；
- 个股榜单列；
- 热力图；
- 连板天梯层级。

### 1.3 红涨绿跌硬规则

```ts
type Direction = 'UP' | 'DOWN' | 'FLAT';
```

| 场景 | `UP` / 正值 | `DOWN` / 负值 | `FLAT` / 零值 | 说明 |
|---|---|---|---|---|
| 指数涨跌 | 红色 | 绿色 | 灰色 | 点位、涨跌额、涨跌幅一致 |
| 个股涨跌 | 红色 | 绿色 | 灰色 | 股票列表、榜单、Tooltip 一致 |
| K 线涨跌 | 红 K | 绿 K | 灰/十字 | 后续个股/指数详情页沿用 |
| 上涨/下跌家数 | 上涨家数红色 | 下跌家数绿色 | 平盘灰色 | DistributionChart / MarketBreadthPanel 必须一致 |
| 资金净流入 | 红色 | 绿色 | 灰色 | 正值代表净流入，负值代表净流出 |
| 涨停/跌停 | 涨停红色 | 跌停绿色 | 不适用 | 连板、封板率以红色体系表达 |
| 系统错误 | 不使用行情红 | 不使用行情绿 | 使用系统错误 Token | 避免与上涨红混淆 |

禁止：

- 禁止使用海外习惯“绿涨红跌”。
- 禁止用 UI 框架默认 `success=green` 表达上涨。
- 禁止同一个数据项文字为红色、图形却为绿色。

### 1.4 数字格式与单位规则

组件只负责展示和格式化，不负责改写业务口径。

```ts
interface AmountValue {
  value: number | null;
  unit?: 'yuan' | 'thousand_yuan' | 'ten_thousand_yuan' | 'hundred_million_yuan' | 'raw';
  displayText?: string;
}

interface NumericDisplayProps {
  value: number | null;
  unit?: string;
  precision?: number;
  showSign?: boolean;
  direction?: Direction;
  placeholder?: string;
}
```

要求：

1. API 若返回 `unit`，前端按 `unit` 进行展示格式化。
2. API 若返回 `displayText`，组件优先展示 `displayText`，但仍保留原始 `value` 用于排序和 Tooltip。
3. 百分比字段统一使用 `+1.26% / -0.82%` 显示。
4. 行情数字统一使用等宽数字：`font-variant-numeric: tabular-nums;`。
5. 空值显示 `--`，不显示 `0`，避免误导。

### 1.5 通用状态模型

```ts
type ComponentState =
  | 'default'
  | 'hover'
  | 'active'
  | 'selected'
  | 'disabled'
  | 'loading'
  | 'empty'
  | 'error';

interface DataStatusMeta {
  dataStatus: 'READY' | 'DELAYED' | 'PARTIAL' | 'EMPTY' | 'ERROR' | 'NO_PERMISSION';
  asOf?: string;
  updateTime?: string;
  delaySeconds?: number;
  message?: string;
  sourceRefs?: SourceRef[];
}

interface SourceRef {
  dataset: string;
  docId?: number | null;
  latestTradeDate?: string;
  normalized?: boolean;
}
```

| 状态 | 视觉规则 | 交互规则 |
|---|---|---|
| default | 正常背景、正常文字、弱边框 | 按业务规则可点击 |
| hover | 背景轻微提亮，边框增强 | 不改变数据，不触发跳转 |
| active | 鼠标按下或键盘确认时压暗 | 可触发跳转、切换、刷新 |
| selected | 当前路由、当前 Tab、当前区间高亮 | 作为筛选条件或当前上下文 |
| disabled | 透明度降低、文字降级 | 不触发业务动作，Tooltip 说明原因 |
| loading | 骨架屏、图表网格占位、表格骨架行 | 保留布局，不整页闪烁 |
| empty | 说明无数据原因 | 可提供刷新、查看最近交易日、调整筛选 |
| error | 异常边框、异常文案、重试按钮 | 单模块失败不拖垮整页 |

---

## 2. Design Token 依赖约定

> 具体色值以 `/docs/wealth/03-design-tokens.md` 为准。本文件只约束组件必须使用哪些 Token，不硬编码色值。

### 2.1 颜色 Token

| Token | 用途 | 组件使用 |
|---|---|---|
| `--csq-color-bg-page` | 页面背景 | 市场总览全局背景 |
| `--csq-color-bg-topbar` | 顶部栏背景 | TopMarketBar |
| `--csq-color-bg-panel` | 面板背景 | 所有 Panel 型组件 |
| `--csq-color-bg-panel-hover` | 面板 hover | 卡片、表格行、热力图块 |
| `--csq-color-border-subtle` | 弱分割线 | 面板、表格、顶部栏 |
| `--csq-color-border-strong` | 强边框 | selected / active 状态 |
| `--csq-color-text-primary` | 主要文字 | 标题、关键数值 |
| `--csq-color-text-secondary` | 次级文字 | 标签、说明、更新时间 |
| `--csq-color-text-muted` | 弱文字 | 单位、空态说明 |
| `--csq-color-rise` | 上涨/净流入/涨停 | ChangeBadge、IndexCard、FundFlowBar |
| `--csq-color-rise-bg` | 上涨弱背景 | 涨幅区间、涨停卡背景 |
| `--csq-color-fall` | 下跌/净流出/跌停 | ChangeBadge、DistributionChart、HeatMap |
| `--csq-color-fall-bg` | 下跌弱背景 | 跌幅区间、跌停块背景 |
| `--csq-color-flat` | 平盘/无变化 | ChangeBadge、平盘家数 |
| `--csq-color-brand` | 品牌强调 | TopMarketBar 品牌、选中线 |
| `--csq-color-warning` | 延迟/警告 | DataDelayState、DataStatusBadge |
| `--csq-color-danger-system` | 系统错误 | ErrorState，不用于行情上涨 |

### 2.2 字体、尺寸、间距 Token

| Token | 用途 |
|---|---|
| `--csq-font-family-base` | 中文和普通文本 |
| `--csq-font-family-number` | 行情数字、表格数字、金额 |
| `--csq-font-size-xs/sm/md/lg` | 高密度标题、标签、正文、关键数字 |
| `--csq-line-height-dense` | 高密度表格和榜单 |
| `--csq-space-2/4/6/8/12/16/20/24` | 内边距、组件间距 |
| `--csq-radius-sm/md/lg` | 表格、卡片、Tooltip 圆角 |
| `--csq-shadow-panel` | 面板阴影，深色下应克制 |
| `--csq-z-topbar` | 顶部栏层级 |
| `--csq-z-popover` | Tooltip / 菜单层级 |

### 2.3 密度 Token

| Token | 建议用途 |
|---|---|
| `--csq-density-topbar-height` | TopMarketBar 高度，建议 48–56px |
| `--csq-density-page-header-height` | PageHeader 高度，建议 56–72px |
| `--csq-density-table-row-height` | 榜单行高，建议 34–40px |
| `--csq-density-card-padding` | 指数卡/指标卡内边距，建议 10–14px |
| `--csq-density-panel-gap` | 面板间距，建议 10–16px |

---

## 3. 市场总览页面组件组合

### 3.1 桌面端推荐骨架

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ TopMarketBar：品牌 / GlobalSystemMenu / IndexTickerStrip / 时间 / 状态 / 用户 │
├──────────────────────────────────────────────────────────────────────────────┤
│ Breadcrumb：财势乾坤 / 乾坤行情 / 市场总览                                  │
│ PageHeader：市场总览 / A股 / 交易日 / 更新时间 / 刷新 / 数据说明              │
├──────────────────────────────────────────────────────────────────────────────┤
│ ShortcutBar：市场温度与情绪｜机会雷达｜我的自选｜我的持仓｜提醒中心｜用户设置  │
├──────────────────────────────────────────────────────────────────────────────┤
│ 全宽行情内容区                                                               │
│  ├─ IndexCard 区                                                             │
│  ├─ MarketBreadthPanel / MarketStylePanel / TurnoverSummaryCard              │
│  ├─ MoneyFlowSummaryPanel / FundFlowBar                                      │
│  ├─ LimitUpSummaryCard / LimitUpDistribution / LimitUpStreakLadder           │
│  └─ SectorRankList / HeatMap / RankingTable / StockTable                     │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 聚合 API 到组件的一级映射

| 聚合字段 | 推荐接口 | 主要组件 |
|---|---|---|
| `overview` | `GET /api/market/overview` 或聚合内 `data.overview` | TopMarketBar、PageHeader、MarketStatusPill、DataStatusBadge |
| `indices` | `GET /api/index/summary` 或聚合内 `data.indices` | IndexTickerStrip、IndexCard、QuoteTicker、MiniTrendChart |
| `breadth` | `GET /api/market/breadth` 或聚合内 `data.breadth` | MarketBreadthPanel、DistributionChart、MetricCard |
| `style` | `GET /api/market/style` 或聚合内 `data.style` | MarketStylePanel、MetricCard |
| `turnover` | `GET /api/market/turnover` 或聚合内 `data.turnover` | TurnoverSummaryCard、MiniTrendChart |
| `moneyFlow` | `GET /api/moneyflow/market` 或聚合内 `data.moneyFlow` | MoneyFlowSummaryPanel、FundFlowBar |
| `limitUp` | `GET /api/limitup/summary` 或聚合内 `data.limitUp` | LimitUpSummaryCard、MetricCard |
| `limitUpDistribution` | 聚合字段或 `GET /api/limitup/distribution` | LimitUpDistribution |
| `streakLadder` | `GET /api/limitup/streak-ladder` 或聚合内 `data.streakLadder` | LimitUpStreakLadder |
| `topSectors` | `GET /api/sector/top` 或聚合内 `data.topSectors` | SectorRankList、SectorTable、HeatMap |
| `stockLeaderboards` | `GET /api/leaderboard/stock` 或聚合内 `data.stockLeaderboards` | RankingTable、StockTable、TabPanel、SortableHeader |
| `quickEntries` | `GET /api/settings/quick-entry` 或聚合内 `data.quickEntries` | ShortcutBar、QuickEntryCard、QuickEntryBadge |

---

## 4. 重点组件详细规范


### 4.1 TopMarketBar

| 项 | 说明 |
|---|---|
| 组件名称 | `TopMarketBar` |
| 组件用途 | 顶部全局市场状态栏，用最小高度承载品牌、系统入口、主要指数条、当前时间、开闭市状态、数据状态、用户入口。它替代固定 SideNav 的全局入口职责，但不压缩横向行情内容区。 |
| 使用页面 | 市场总览 P0 必需；后续可复用于板块与榜单、指数详情、个股详情、自选、持仓、提醒中心。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `brand`、`activeSystem`、`systems`、`indices`、`currentTime`、`marketStatus`、`dataStatus`、`user`、`onSystemSelect`、`onIndexClick`、`onDataStatusClick`、`onUserMenuClick`。 |
| 字段类型 | 见下方 TypeScript 接口。 |
| 与 API 字段的映射 | `data.overview.market/tradeDate/sessionStatus/asOf/dataStatus/isDelayed/delaySeconds`；`data.indices[]`；用户入口来自登录态或用户接口，不强依赖市场总览 API。 |
| 视觉结构 | 高度建议 48–56px。左侧：品牌“财势乾坤”；中左：GlobalSystemMenu；中部：IndexTickerStrip 横向紧凑展示；右侧：当前时间、MarketStatusPill、DataStatusBadge、用户头像/菜单。 |
| 交互行为 | 点击系统入口展开二级页面列表或进入系统默认页；点击指数进入指数详情；hover 指数显示更多字段；点击数据状态展示数据源/延迟说明；点击用户入口进入用户菜单或用户设置。 |
| 状态 | default：顶部栏稳定展示；hover：系统入口、指数条、用户入口轻微提亮；active：点击压暗；selected：当前系统“乾坤行情”高亮；disabled：未开放系统置灰；loading：指数条骨架，品牌和菜单不闪烁；empty：指数为空显示 `--` 并保留栏位；error：DataStatusBadge 显示异常，指数条可展示最近缓存。 |
| 涨跌色规则 | 指数点位、涨跌额、涨跌幅按 `direction` 红涨绿跌；开闭市状态不使用涨跌红绿，使用状态 Token；系统异常不使用上涨红。 |
| 与 Design Token 的关系 | `--csq-color-bg-topbar`、`--csq-color-border-subtle`、`--csq-color-brand`、`--csq-color-rise/fall/flat`、`--csq-font-family-number`、`--csq-density-topbar-height`、`--csq-z-topbar`。 |
| 备注 | 不得做成大型官网导航；不得增加营销口号；系统入口需要紧凑，避免挤压指数条。 |

```ts
interface TopMarketBarProps {
  brand: '财势乾坤';
  activeSystem: 'QUANT_QUOTE' | 'CAISHI_SCAN' | 'TRADE_ASSISTANT' | 'TRAINING' | 'DATA_CENTER' | 'SETTINGS';
  systems: GlobalSystemMenuItem[];
  indices: IndexTickerItem[];
  currentTime: string;
  marketStatus: MarketStatusPillProps;
  dataStatus: DataStatusBadgeProps;
  user?: {
    userId: string;
    displayName: string;
    avatarUrl?: string;
    isLoggedIn: boolean;
  };
  onSystemSelect?: (systemKey: string) => void;
  onIndexClick?: (indexCode: string) => void;
  onDataStatusClick?: () => void;
  onUserMenuClick?: () => void;
}
```

### 4.2 Breadcrumb

| 项 | 说明 |
|---|---|
| 组件名称 | `Breadcrumb` |
| 组件用途 | 市场总览桌面端的主要层级表达组件，用于明确当前页面归属，替代固定 SideNav 的“我在哪儿”职责。 |
| 使用页面 | 市场总览 P0 必需；其他高密度行情页推荐使用。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `items`、`currentKey`、`onItemClick`、`onItemHover`。市场总览固定 items：`财势乾坤 / 乾坤行情 / 市场总览`。 |
| 字段类型 | `items: BreadcrumbItem[]`；`BreadcrumbItem = { key:string; label:string; href?:string; clickable:boolean; current?:boolean; menuItems?:RouteItem[] }`。 |
| 与 API 字段的映射 | 主要来自路由静态配置；如聚合接口返回 `breadcrumb`，也只能用于校验文案，不建议动态改变固定层级。 |
| 视觉结构 | 低高度文本链路，放在 PageHeader 上方或同一行左侧。分隔符使用 `/` 或 Chevron，当前项加粗/高亮但不做大色块。 |
| 交互行为 | 点击“财势乾坤”返回默认落地页；点击“乾坤行情”展开同系统页面列表或跳转市场总览；“市场总览”为当前态，不跳转或仅刷新当前页。hover 可显示可点击态。 |
| 状态 | default：三段层级正常展示；hover：可点击段文字提亮；active：点击时压暗；selected：当前“市场总览”使用当前态；disabled：当前项不可点击；loading：不需要骨架，保留静态层级；empty：不允许为空，兜底固定表达；error：路由异常时仍兜底固定表达。 |
| 涨跌色规则 | 不承载涨跌数据，禁止使用红绿表达层级。 |
| 与 Design Token 的关系 | `--csq-color-text-secondary`、`--csq-color-text-primary`、`--csq-color-brand`、`--csq-font-size-xs`、`--csq-space-4/8`。 |
| 备注 | 固定表达必须是：`财势乾坤 / 乾坤行情 / 市场总览`。不要写成“首页 / 市场总览”。 |

### 4.3 ShortcutBar / QuickEntryCard

| 项 | 说明 |
|---|---|
| 组件名称 | `ShortcutBar` / `QuickEntryCard` |
| 组件用途 | 在不使用固定 SideNav 的前提下，承接市场总览到 P0 闭环页面的分流：市场温度与情绪、机会雷达、我的自选、我的持仓、提醒中心、用户设置。 |
| 使用页面 | 市场总览 P0 必需；其他页面可作为轻量快捷入口复用。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `entries`、`layout`、`density`、`onEntryClick`。`QuickEntryCard` 接收 `title`、`description`、`route`、`statusText`、`badge`、`disabledReason`。 |
| 字段类型 | 见下方 TypeScript 接口。 |
| 与 API 字段的映射 | `data.quickEntries[]` 或 `GET /api/settings/quick-entry`；个人数量如自选数量、持仓数量、未读提醒数量可来自用户模块接口；市场总览 API 只保留入口状态，不返回分析分数。 |
| 视觉结构 | `ShortcutBar` 为横向紧凑条，最多一行或两行自动换行。`QuickEntryCard` 应是小型入口卡，不做大面积卡片墙。每个卡片包含标题、短说明、可选徽标/待处理数。 |
| 交互行为 | 点击进入对应页面；未登录点击个人入口时引导登录；disabled 入口不跳转并显示原因；可 hover 显示更详细说明。 |
| 状态 | default：横向轻量入口；hover：卡片描边/背景轻微提亮；active：点击压暗；selected：当前页或当前系统可显示细线高亮；disabled：未登录/未开放置灰；loading：个人数量骨架；empty：个人入口数量为空显示“未配置”而非隐藏；error：个人状态加载失败时仅入口保留、数量显示 `--`。 |
| 涨跌色规则 | 不展示市场涨跌；Badge 不能用红绿表达市场温度/情绪强弱。提醒数量可用品牌/警告色，不使用行情涨跌色。 |
| 与 Design Token 的关系 | `--csq-color-bg-panel`、`--csq-color-bg-panel-hover`、`--csq-color-border-subtle`、`--csq-color-brand`、`--csq-color-warning`、`--csq-font-size-sm/xs`、`--csq-density-card-padding`。 |
| 备注 | 允许展示“3 条待处理提醒”“自选 28 只”“已登记持仓 5 只”；禁止展示“市场温度 82 分”“情绪指数亢奋”“资金面分数偏强”“风险指数建议减仓”。 |

```ts
interface QuickEntryItem {
  key: 'MARKET_SENTIMENT' | 'OPPORTUNITY_RADAR' | 'WATCHLIST' | 'POSITION' | 'ALERT_CENTER' | 'USER_SETTINGS';
  title: string;
  description: string;
  route: string;
  enabled: boolean;
  requireLogin?: boolean;
  badge?: {
    text: string;
    count?: number;
    tone: 'neutral' | 'brand' | 'warning';
  };
  statusText?: string;
  disabledReason?: string;
}

interface ShortcutBarProps {
  entries: QuickEntryItem[];
  layout?: 'single-row' | 'wrap';
  density?: 'compact' | 'normal';
  onEntryClick?: (entry: QuickEntryItem) => void;
}
```

### 4.4 IndexCard

| 项 | 说明 |
|---|---|
| 组件名称 | `IndexCard` |
| 组件用途 | 展示主要指数点位、涨跌额、涨跌幅、成交额和小趋势线，支持点击进入指数详情。 |
| 使用页面 | 市场总览 P0 必需；指数详情页、TopMarketBar 下拉详情可复用。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `indexCode`、`indexName`、`latestPoint`、`change`、`changePct`、`direction`、`amount`、`volume`、`open`、`high`、`low`、`preClose`、`trend`、`asOf`。 |
| 字段类型 | `number | null`、`Direction`、`AmountValue`、`Array<{time:string; value:number}>`。 |
| 与 API 字段的映射 | `data.indices[]` 或 `/api/index/summary`：`code/name/close/change/changePct/direction/amount/vol/open/high/low/preClose/asOf/trend`。字段名以 API 文档为准，组件只要求 ViewModel 适配到以上 props。 |
| 视觉结构 | 卡片顶部指数名和代码，中部大号点位，右侧或下方显示涨跌额/涨跌幅，底部显示成交额和 MiniTrendChart。4–7 个卡片横向网格排列。 |
| 交互行为 | 点击卡片进入指数详情页并携带 `indexCode`、`tradeDate`；hover 显示最高、最低、开盘、昨收、更新时间；可支持排序但首页默认按预设指数顺序。 |
| 状态 | default：正常行情；hover：卡片边框提亮，小趋势线增强；active：点击压暗；selected：从顶部指数条下钻回来时可高亮当前指数；disabled：指数暂停或不可用置灰；loading：点位和趋势线骨架；empty：指数值缺失显示 `--`；error：单卡异常显示“指数数据异常”，不影响其他卡。 |
| 涨跌色规则 | `direction=UP` 点位、涨跌额、涨跌幅、小趋势线用红；`DOWN` 用绿；`FLAT` 用灰。成交额不因涨跌着色，除非展示较昨日变化。 |
| 与 Design Token 的关系 | `--csq-color-bg-panel`、`--csq-color-rise/fall/flat`、`--csq-font-family-number`、`--csq-font-size-lg`、`--csq-density-card-padding`、`--csq-radius-md`。 |
| 备注 | 不允许使用大面积红绿背景，避免多个指数同时上涨时满屏刺眼；优先使用文字色和细线表达方向。 |

### 4.5 DistributionChart

| 项 | 说明 |
|---|---|
| 组件名称 | `DistributionChart` |
| 组件用途 | 展示涨跌幅区间分布、上涨/下跌/平盘家数分布，可用于判断市场赚钱效应的客观事实。 |
| 使用页面 | 市场总览 P0 必需；策略验证、市场温度与情绪页可复用。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `buckets`、`totalCount`、`selectedBucketKey`、`orientation`、`onBucketHover`、`onBucketClick`。 |
| 字段类型 | `buckets: Array<{key:string; label:string; minPct?:number; maxPct?:number; count:number; ratio:number; direction:Direction}>`。 |
| 与 API 字段的映射 | `data.breadth.distribution[]`、`data.breadth.upCount/downCount/flatCount/medianChangePct/redRate`；若 API 字段是区间数组，直接映射；若只有汇总家数，Showcase 可用 mock buckets。 |
| 视觉结构 | 使用水平条、竖向柱或镜像条形图。上涨区间靠右/上方用红，跌幅区间靠左/下方用绿，平盘用灰。显示数量与占比。 |
| 交互行为 | hover 区间显示 Tooltip：区间、家数、占比、代表筛选条件；点击区间跳转板块与榜单行情页，携带 `changePctRange`、`tradeDate`。 |
| 状态 | default：所有区间展示；hover：当前区间高亮并显示 Tooltip；active：点击区间压暗；selected：已选区间保持描边；disabled：不可下钻时只展示 Tooltip；loading：图表网格骨架；empty：无分布数据提示“当前交易日分布未生成”；error：显示模块错误和重试。 |
| 涨跌色规则 | 正涨幅区间红，负跌幅区间绿，平盘灰；绝不使用蓝紫表示涨跌。 |
| 与 Design Token 的关系 | `--csq-color-rise/fall/flat`、`--csq-color-rise-bg/fall-bg`、`--csq-color-chart-grid`、`--csq-color-tooltip-bg`、`--csq-font-family-number`。 |
| 备注 | 点击下钻不在首页弹大抽屉，优先进入板块与榜单行情页，避免首页复杂化。 |

### 4.6 FundFlowBar

| 项 | 说明 |
|---|---|
| 组件名称 | `FundFlowBar` |
| 组件用途 | 展示市场级资金净流入/净流出，以及超大单/大单/中单/小单拆分。首页只展示资金流事实，不计算资金面分数。 |
| 使用页面 | 市场总览 P0 必需；板块、个股详情可复用。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `mainNetInflow`、`superLargeNetInflow`、`largeNetInflow`、`mediumNetInflow`、`smallNetInflow`、`unit`、`segments`、`asOf`。 |
| 字段类型 | `AmountValue` 或 `number + unit`；`segments: Array<{key:string; label:string; value:number; unit?:string; direction:Direction; ratio?:number}>`。 |
| 与 API 字段的映射 | `data.moneyFlow.mainNetInflow`、`superLargeNetInflow`、`largeNetInflow`、`mediumNetInflow`、`smallNetInflow`、`history[]`、`asOf`、`dataStatus`；来源可对应 `moneyflow_mkt_dc.net_amount/buy_elg_amount/buy_lg_amount/buy_md_amount/buy_sm_amount`。 |
| 视觉结构 | 顶部显示净流入/净流出总额；下方用分段条展示超大单/大单/中单/小单。正值段向右或使用红色，负值段向左或使用绿色。 |
| 交互行为 | hover 分段显示金额、占比、更新时间、数据来源；点击可进入资金流向详情页或板块与榜单页资金榜；数据延迟时显示 DataStatusBadge。 |
| 状态 | default：分段条正常；hover：分段高亮 Tooltip；active：点击压暗；selected：选中某一资金类型时描边；disabled：资金模块不可用时置灰；loading：条形骨架；empty：资金源未生成时提示“资金流数据暂缺”；error：显示数据源异常和最近缓存时间。 |
| 涨跌色规则 | 资金正值/净流入为红，负值/净流出为绿，零值灰；不要使用“绿色=好”的通用语义。 |
| 与 Design Token 的关系 | `--csq-color-rise/fall/flat`、`--csq-color-bg-panel`、`--csq-color-chart-grid`、`--csq-color-warning`、`--csq-font-family-number`。 |
| 备注 | `mainNetInflow` 等金额单位必须按 API 的 `unit` 或字段说明格式化；不得在组件内部固定假设为元、万元或亿元。 |

### 4.7 LimitUpStreakLadder

| 项 | 说明 |
|---|---|
| 组件名称 | `LimitUpStreakLadder` |
| 组件用途 | 展示连板层级和个股卡片，用于观察短线连板高度和梯队结构。 |
| 使用页面 | 市场总览 P0 必需；后续涨跌停详情页可复用。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `levels`、`highestStreak`、`tradeDate`、`onStockClick`、`onSectorClick`。 |
| 字段类型 | 见下方 TypeScript 接口。 |
| 与 API 字段的映射 | `data.streakLadder[]` 或 `/api/limitup/streak-ladder`：`streak/count/items[]`，个股项映射 `stockCode/stockName/sectors/latestPrice/changePct/sealAmount/firstLimitTime/openTimes`。 |
| 视觉结构 | 横向或纵向天梯。层级从高到低或从左到右展示：N 板、5 板、4 板、3 板、2 板、首板。每层显示层级标题、数量和个股小卡片。 |
| 交互行为 | 点击股票进入个股详情；点击板块标签进入板块与榜单行情页；hover 个股显示封单金额、首次封板时间、开板次数、所属概念；点击层级标题可进入连板榜筛选。 |
| 状态 | default：层级和卡片展示；hover：股票卡/板块标签提亮；active：点击压暗；selected：选中的层级或个股描边；disabled：停牌/数据不可下钻置灰；loading：层级骨架；empty：当日无连板时显示“今日暂无连板股”；error：显示连板数据异常，保留涨跌停摘要。 |
| 涨跌色规则 | 连板、涨停、涨幅均使用红色体系；跌停相关不放入连板天梯，若展示风险标记用警告色，不用绿色。 |
| 与 Design Token 的关系 | `--csq-color-rise`、`--csq-color-rise-bg`、`--csq-color-bg-panel`、`--csq-color-border-subtle`、`--csq-font-family-number`、`--csq-radius-sm/md`。 |
| 备注 | 首页不宜展示过多股票卡，超过每层展示上限时使用“+N”进入详情，避免撑高页面。 |

```ts
interface LimitUpStreakLadderProps {
  tradeDate: string;
  highestStreak: number;
  levels: Array<{
    streak: number;
    label: string;
    count: number;
    items: Array<{
      stockCode: string;
      stockName: string;
      sectors: Array<{ sectorCode?: string; sectorName: string; sectorType?: 'INDUSTRY' | 'CONCEPT' | 'REGION' }>;
      latestPrice?: number | null;
      changePct?: number | null;
      sealAmount?: number | null;
      unit?: string;
      firstLimitTime?: string | null;
      openTimes?: number | null;
      direction: 'UP';
    }>;
  }>;
  onStockClick?: (stockCode: string) => void;
  onSectorClick?: (sectorCode: string, sectorType?: string) => void;
}
```

### 4.8 RankingTable

| 项 | 说明 |
|---|---|
| 组件名称 | `RankingTable` |
| 组件用途 | 承载市场总览的多榜单速览，包括涨幅榜、跌幅榜、成交额榜、换手榜、量比异动榜，并支持 Tab 切换和个股下钻。 |
| 使用页面 | 市场总览 P0 必需；板块与榜单行情页、机会雷达、策略验证可复用。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `tabs`、`activeTabKey`、`columns`、`rows`、`sort`、`rowKey`、`loading`、`onTabChange`、`onSortChange`、`onRowClick`、`onMoreClick`。 |
| 字段类型 | `columns: RankingColumn[]`；`rows: StockRankItem[] | SectorRankItem[]`；`sort: {field:string; order:'asc'|'desc'}`。 |
| 与 API 字段的映射 | `data.stockLeaderboards` 或 `/api/leaderboard/stock`：`rankType/items[]`；个股字段映射 `rank/stockCode/stockName/latestPrice/changePct/amount/volume/turnoverRate/volumeRatio/industry/concepts`。 |
| 视觉结构 | Panel 内部上方 TabPanel；下方高密度表格。首页默认每个榜单 Top 5–10 行，更多进入板块与榜单行情页。表格列保持稳定，数字右对齐。 |
| 交互行为 | Tab 切换榜单；点击表头排序；点击个股行进入个股详情并携带 `stockCode`、`tradeDate`；点击“查看更多”进入完整榜单页并携带 `rankType`。 |
| 状态 | default：默认榜单展示；hover：行高亮；active：行点击压暗；selected：当前 Tab 高亮，可选中当前行；disabled：榜单无权限或未开放时置灰；loading：表格骨架行；empty：当前榜单无数据时局部空态；error：当前榜单失败时显示重试，不影响其他榜单。 |
| 涨跌色规则 | 个股涨跌幅、涨跌额、最新价方向严格红涨绿跌；成交额、成交量、换手、量比默认中性色；跌幅榜中的负值必须为绿色。 |
| 与 Design Token 的关系 | `--csq-density-table-row-height`、`--csq-font-family-number`、`--csq-color-bg-panel`、`--csq-color-bg-panel-hover`、`--csq-color-rise/fall/flat`、`--csq-color-border-subtle`。 |
| 备注 | 不要一次性在首页塞完整分页表格；首页是速览，完整筛选和分页放到“板块与榜单行情页”。 |

---

## 5. 市场总览 P0 组件目录


> 本节覆盖市场总览 P0 的全部组件。重点组件已在第 4 节展开；本节对其余组件给出实现级契约。第 4 节组件仍以第 4 节为准。


### 5.1. GlobalSystemMenu

| 项 | 说明 |
|---|---|
| 组件名称 | `GlobalSystemMenu` |
| 组件用途 | 顶部全局系统入口，承载乾坤行情、财势探查、交易助手、交易训练、数据中心、系统设置等一级系统跳转，替代固定 SideNav 的全局导航能力。 |
| 使用页面 | 市场总览必需；全站顶部栏可复用。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `systems`、`activeSystem`、`openMode`、`onSystemSelect`、`onPageSelect`。 |
| 字段类型 | `systems: Array<{key:string; label:string; route:string; children?:RouteItem[]; enabled:boolean}>`。 |
| 与 API 字段的映射 | 主要来自路由配置；可结合用户权限接口控制 `enabled`；不依赖市场总览行情 API。 |
| 视觉结构 | TopMarketBar 内的紧凑菜单，可横向展示一级系统，也可收纳到“系统”下拉菜单。 |
| 交互行为 | 点击一级系统进入默认页或展开下级页面；hover 展示菜单；键盘支持方向键切换。 |
| 状态 | default：正常展示；hover：可点击区域轻微提亮；active：点击压暗或描边增强；selected：当前项显示选中底色/左侧标识线；disabled：降低透明度并禁止点击；loading：骨架或占位，不改变布局；empty：显示原因和下一步动作；error：显示异常说明和重试入口。 |
| 涨跌色规则 | 不承载涨跌数据，不使用红绿表达选中；选中使用品牌色或边框。 |
| 与 Design Token 的关系 | `--csq-color-bg-topbar`、`--csq-color-brand`、`--csq-color-text-secondary`、`--csq-z-popover`。 |
| 备注 | 当前系统为“乾坤行情”；市场总览不是独立一级菜单。 |


### 5.2. IndexTickerStrip

| 项 | 说明 |
|---|---|
| 组件名称 | `IndexTickerStrip` |
| 组件用途 | 顶部栏中的主要指数行情条，用极小空间展示上证指数、深证成指、创业板指、科创 50、沪深 300 等简要行情。 |
| 使用页面 | 市场总览必需；全站顶部栏可复用。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `items`、`speed`、`compact`、`onItemClick`。 |
| 字段类型 | `items: IndexTickerItem[]`，字段含 `code/name/latestPoint/change/changePct/direction/asOf`。 |
| 与 API 字段的映射 | `data.indices[]` 或 `/api/index/summary`。 |
| 视觉结构 | 横向 ticker，可固定展示或溢出滚动；每项包含名称、点位、涨跌幅。 |
| 交互行为 | hover 暂停滚动并显示 Tooltip；点击进入指数详情。 |
| 状态 | default：正常展示；hover：可点击区域轻微提亮；active：点击压暗或描边增强；selected：当前项显示选中底色/左侧标识线；disabled：降低透明度并禁止点击；loading：骨架或占位，不改变布局；empty：显示原因和下一步动作；error：显示异常说明和重试入口。 |
| 涨跌色规则 | 指数涨跌按 `direction` 红涨绿跌，平盘灰色。 |
| 与 Design Token 的关系 | `--csq-font-family-number`、`--csq-color-rise/fall/flat`、`--csq-density-topbar-height`。 |
| 备注 | 指数条不得挤掉 GlobalSystemMenu 和状态信息；空间不足时优先隐藏成交额。 |


### 5.3. PageHeader

| 项 | 说明 |
|---|---|
| 组件名称 | `PageHeader` |
| 组件用途 | 页面标题与交易上下文组件，展示市场总览、A 股、交易日、更新时间、刷新和数据说明入口。 |
| 使用页面 | 市场总览必需；其他页面可复用。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `title`、`subtitle`、`market`、`tradeDate`、`asOf`、`marketStatus`、`dataStatus`、`actions`。 |
| 字段类型 | `title:string; market:'CN_A'; tradeDate:string; asOf:string; actions: ActionItem[]`。 |
| 与 API 字段的映射 | `data.overview.market/tradeDate/asOf/sessionStatus/dataStatus`。 |
| 视觉结构 | Breadcrumb 下方或同一区域：左侧标题，右侧状态、更新时间、刷新按钮。 |
| 交互行为 | 点击刷新触发聚合或模块刷新；点击数据说明打开 Popover。 |
| 状态 | default：正常展示；hover：可点击区域轻微提亮；active：点击压暗或描边增强；selected：当前项显示选中底色/左侧标识线；disabled：降低透明度并禁止点击；loading：骨架或占位，不改变布局；empty：显示原因和下一步动作；error：显示异常说明和重试入口。 |
| 涨跌色规则 | 不直接展示涨跌；若标题旁展示市场范围，不使用红绿。 |
| 与 Design Token 的关系 | `--csq-font-size-lg`、`--csq-color-text-primary`、`--csq-color-text-secondary`、`--csq-space-8/12`。 |
| 备注 | PageHeader 不做营销文案，只描述页面事实和时间上下文。 |


### 5.4. MarketStatusPill

| 项 | 说明 |
|---|---|
| 组件名称 | `MarketStatusPill` |
| 组件用途 | 展示开闭市状态：未开盘、集合竞价、交易中、午间休市、已收盘、非交易日。 |
| 使用页面 | 市场总览必需；TopMarketBar、PageHeader 复用。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `sessionStatus`、`isTradingDay`、`label`、`timeRange`。 |
| 字段类型 | `sessionStatus: 'PRE_OPEN'|'CALL_AUCTION'|'OPEN'|'NOON_BREAK'|'CLOSED'|'NON_TRADING_DAY'`。 |
| 与 API 字段的映射 | `data.overview.sessionStatus/isTradingDay/openTime/closeTime`。 |
| 视觉结构 | 小型圆角 Pill，文字 + 状态点。 |
| 交互行为 | hover 展示交易时间段；点击无必要，若点击可打开交易日说明。 |
| 状态 | default：正常展示；hover：可点击区域轻微提亮；active：点击压暗或描边增强；selected：当前项显示选中底色/左侧标识线；disabled：降低透明度并禁止点击；loading：骨架或占位，不改变布局；empty：显示原因和下一步动作；error：显示异常说明和重试入口。 |
| 涨跌色规则 | 不使用涨跌红绿；交易中可用品牌/信息色，非交易日用灰，异常另由 DataStatusBadge 表达。 |
| 与 Design Token 的关系 | `--csq-color-info`、`--csq-color-flat`、`--csq-radius-sm`、`--csq-font-size-xs`。 |
| 备注 | 避免把“交易中”显示成红色，防止误读为上涨。 |


### 5.5. DataStatusBadge

| 项 | 说明 |
|---|---|
| 组件名称 | `DataStatusBadge` |
| 组件用途 | 展示数据就绪、延迟、部分缺失、异常、无权限等数据状态。 |
| 使用页面 | 市场总览必需；所有行情模块可复用。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `dataStatus`、`asOf`、`delaySeconds`、`sourceRefs`、`message`、`onClick`。 |
| 字段类型 | `dataStatus: 'READY'|'DELAYED'|'PARTIAL'|'EMPTY'|'ERROR'|'NO_PERMISSION'`。 |
| 与 API 字段的映射 | `data.overview.dataStatus/asOf/isDelayed/delaySeconds/sourceRefs`，模块级也可使用模块自身 `dataStatus`。 |
| 视觉结构 | 小型 Badge，可放顶部栏、PageHeader、Panel 右上角。 |
| 交互行为 | 点击展示数据源、更新时间、延迟说明；error 状态提供重试或查看缓存。 |
| 状态 | default：正常展示；hover：可点击区域轻微提亮；active：点击压暗或描边增强；selected：当前项显示选中底色/左侧标识线；disabled：降低透明度并禁止点击；loading：骨架或占位，不改变布局；empty：显示原因和下一步动作；error：显示异常说明和重试入口。 |
| 涨跌色规则 | 不使用行情涨跌色；READY 可用中性或信息色，DELAYED 用 warning，ERROR 用系统错误色。 |
| 与 Design Token 的关系 | `--csq-color-warning`、`--csq-color-danger-system`、`--csq-color-text-muted`、`--csq-radius-sm`。 |
| 备注 | 数据异常不能让整页白屏；优先模块级降级。 |


### 5.6. ShortcutBar

| 项 | 说明 |
|---|---|
| 组件名称 | `ShortcutBar` |
| 组件用途 | 页面内快捷入口容器，横向承载 P0 闭环入口。详细规则见 4.3。 |
| 使用页面 | 市场总览必需。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `entries`、`layout`、`density`、`onEntryClick`。 |
| 字段类型 | `entries: QuickEntryItem[]`。 |
| 与 API 字段的映射 | `data.quickEntries[]`。 |
| 视觉结构 | 横向紧凑入口条，一行优先，必要时换行。 |
| 交互行为 | 点击入口跳转；未登录个人入口引导登录。 |
| 状态 | default：正常展示；hover：可点击区域轻微提亮；active：点击压暗或描边增强；selected：当前项显示选中底色/左侧标识线；disabled：降低透明度并禁止点击；loading：骨架或占位，不改变布局；empty：显示原因和下一步动作；error：显示异常说明和重试入口。 |
| 涨跌色规则 | 不承载市场涨跌，不用红绿展示分析强弱。 |
| 与 Design Token 的关系 | `--csq-color-bg-panel`、`--csq-color-border-subtle`、`--csq-color-brand`。 |
| 备注 | 不可做成大面积入口卡片墙。 |


### 5.7. QuickEntryCard

| 项 | 说明 |
|---|---|
| 组件名称 | `QuickEntryCard` |
| 组件用途 | 单个快捷入口卡。详细规则见 4.3。 |
| 使用页面 | 市场总览必需。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `title`、`description`、`route`、`badge`、`enabled`、`requireLogin`。 |
| 字段类型 | `QuickEntryItem`。 |
| 与 API 字段的映射 | `data.quickEntries[].items` 或前端配置合并个人状态。 |
| 视觉结构 | 小卡片：标题、短说明、可选 QuickEntryBadge。 |
| 交互行为 | 点击跳转，disabled 时 Tooltip 说明原因。 |
| 状态 | default：正常展示；hover：可点击区域轻微提亮；active：点击压暗或描边增强；selected：当前项显示选中底色/左侧标识线；disabled：降低透明度并禁止点击；loading：骨架或占位，不改变布局；empty：显示原因和下一步动作；error：显示异常说明和重试入口。 |
| 涨跌色规则 | 不展示行情分数，不使用红绿表达强弱。 |
| 与 Design Token 的关系 | `--csq-density-card-padding`、`--csq-radius-md`、`--csq-color-bg-panel-hover`。 |
| 备注 | 市场温度与情绪入口只写“查看市场综合分析”，不写具体分数。 |


### 5.8. QuickEntryBadge

| 项 | 说明 |
|---|---|
| 组件名称 | `QuickEntryBadge` |
| 组件用途 | QuickEntryCard 内部的小徽标，用于展示待处理数量、是否已配置、自选/持仓/提醒数量。 |
| 使用页面 | 市场总览必需；快捷入口复用。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `text`、`count`、`tone`、`maxCount`。 |
| 字段类型 | `tone: 'neutral'|'brand'|'warning'`；`count?:number`。 |
| 与 API 字段的映射 | `data.quickEntries[].badge`；个人数量来自自选/持仓/提醒模块。 |
| 视觉结构 | 小圆角徽标，位于入口卡右上或标题右侧。 |
| 交互行为 | hover 随卡片高亮；自身通常不单独点击。 |
| 状态 | default：正常展示；hover：可点击区域轻微提亮；active：点击压暗或描边增强；selected：当前项显示选中底色/左侧标识线；disabled：降低透明度并禁止点击；loading：骨架或占位，不改变布局；empty：显示原因和下一步动作；error：显示异常说明和重试入口。 |
| 涨跌色规则 | 不展示行情涨跌，不使用红绿表示市场强弱；提醒数量可用 warning。 |
| 与 Design Token 的关系 | `--csq-color-warning`、`--csq-color-brand`、`--csq-font-size-xs`、`--csq-radius-sm`。 |
| 备注 | 严禁展示市场温度、情绪、资金面、风险指数的分数徽标。 |


### 5.9. MetricCard

| 项 | 说明 |
|---|---|
| 组件名称 | `MetricCard` |
| 组件用途 | 展示单个客观指标，如上涨家数、下跌家数、平盘家数、红盘率、涨跌中位数、成交额变化、封板率等。 |
| 使用页面 | 市场总览必需；全站数据概览可复用。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `label`、`value`、`unit`、`direction`、`subValue`、`compareText`、`tooltip`。 |
| 字段类型 | `value:number|null; unit?:string; direction?:Direction; subValue?:NumericDisplayProps`。 |
| 与 API 字段的映射 | 来自 `breadth`、`style`、`turnover`、`limitUp` 等模块字段。 |
| 视觉结构 | 小型指标卡：标签、主值、单位、辅助说明。可 2–4 列紧凑排列。 |
| 交互行为 | hover 显示指标口径；点击可按业务下钻。 |
| 状态 | default：正常展示；hover：可点击区域轻微提亮；active：点击压暗或描边增强；selected：当前项显示选中底色/左侧标识线；disabled：降低透明度并禁止点击；loading：骨架或占位，不改变布局；empty：显示原因和下一步动作；error：显示异常说明和重试入口。 |
| 涨跌色规则 | 与涨跌方向相关的指标按 direction 着色；纯数量默认中性，涨停数量可红、跌停数量可绿。 |
| 与 Design Token 的关系 | `--csq-color-bg-panel`、`--csq-font-family-number`、`--csq-color-rise/fall/flat`、`--csq-space-8/12`。 |
| 备注 | 不允许把综合分析分数塞入市场总览 MetricCard。 |


### 5.10. ChangeBadge

| 项 | 说明 |
|---|---|
| 组件名称 | `ChangeBadge` |
| 组件用途 | 统一展示涨跌额、涨跌幅、净流入/净流出方向标签。 |
| 使用页面 | 市场总览必需；全站行情组件复用。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `value`、`unit`、`direction`、`showSign`、`variant`。 |
| 字段类型 | `value:number|null; direction:Direction; variant:'text'|'pill'|'cell'`。 |
| 与 API 字段的映射 | 所有含 `direction/change/changePct/netInflow` 的字段。 |
| 视觉结构 | 可为纯文本或小 Pill；表格内用文本型，卡片内可用 Pill。 |
| 交互行为 | hover 可显示原始值；active 不单独处理。 |
| 状态 | default：正常展示；hover：可点击区域轻微提亮；active：点击压暗或描边增强；selected：当前项显示选中底色/左侧标识线；disabled：降低透明度并禁止点击；loading：骨架或占位，不改变布局；empty：显示原因和下一步动作；error：显示异常说明和重试入口。 |
| 涨跌色规则 | UP 红、DOWN 绿、FLAT 灰。必须展示正号 `+`。 |
| 与 Design Token 的关系 | `--csq-color-rise/fall/flat`、`--csq-color-rise-bg/fall-bg`、`--csq-font-family-number`。 |
| 备注 | 禁止套用 Element Plus `success/danger` 默认语义。 |


### 5.11. QuoteTicker

| 项 | 说明 |
|---|---|
| 组件名称 | `QuoteTicker` |
| 组件用途 | 紧凑行情条目，用于展示单个指数、股票或板块的名称、最新值、涨跌幅。 |
| 使用页面 | 市场总览必需；IndexTickerStrip、榜单、详情页复用。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `code`、`name`、`latest`、`changePct`、`direction`、`amount`、`onClick`。 |
| 字段类型 | `latest:number|null; changePct:number|null; direction:Direction`。 |
| 与 API 字段的映射 | `indices[]`、`topSectors.items[]`、`stockLeaderboards.items[]`。 |
| 视觉结构 | 单行紧凑布局：名称/代码 + 数字 + ChangeBadge。 |
| 交互行为 | 点击进入详情；hover 显示更多行情字段。 |
| 状态 | default：正常展示；hover：可点击区域轻微提亮；active：点击压暗或描边增强；selected：当前项显示选中底色/左侧标识线；disabled：降低透明度并禁止点击；loading：骨架或占位，不改变布局；empty：显示原因和下一步动作；error：显示异常说明和重试入口。 |
| 涨跌色规则 | 涨跌字段红涨绿跌；名称不染色或仅轻微跟随。 |
| 与 Design Token 的关系 | `--csq-font-family-number`、`--csq-color-rise/fall/flat`、`--csq-font-size-xs/sm`。 |
| 备注 | 适合 TopMarketBar 和小模块，不替代表格。 |


### 5.12. MiniTrendChart

| 项 | 说明 |
|---|---|
| 组件名称 | `MiniTrendChart` |
| 组件用途 | 小型趋势线，用于指数、成交额、资金流、涨跌家数历史趋势预览。 |
| 使用页面 | 市场总览必需；IndexCard、TurnoverSummaryCard、MoneyFlowSummaryPanel 可复用。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `points`、`direction`、`height`、`showAxis`、`tooltipFormatter`。 |
| 字段类型 | `points: Array<{time:string; value:number}>; direction?:Direction`。 |
| 与 API 字段的映射 | `indices[].trend`、`turnover.history[]`、`moneyFlow.history[]`、`breadth.history[]`。 |
| 视觉结构 | 无坐标轴或弱坐标轴小折线，嵌入卡片底部。 |
| 交互行为 | hover 显示日期和值；首页不做复杂缩放。 |
| 状态 | default：正常展示；hover：可点击区域轻微提亮；active：点击压暗或描边增强；selected：当前项显示选中底色/左侧标识线；disabled：降低透明度并禁止点击；loading：骨架或占位，不改变布局；empty：显示原因和下一步动作；error：显示异常说明和重试入口。 |
| 涨跌色规则 | 若表示价格趋势，按最后方向红绿；若表示成交额/家数，使用中性或模块语义色。 |
| 与 Design Token 的关系 | `--csq-color-chart-grid`、`--csq-color-rise/fall/flat`、`--csq-font-family-number`。 |
| 备注 | Showcase 可用 SVG 或 Canvas 模拟，不依赖完整图表库。 |


### 5.13. MarketBreadthPanel

| 项 | 说明 |
|---|---|
| 组件名称 | `MarketBreadthPanel` |
| 组件用途 | 组合展示上涨/下跌/平盘家数、红盘率、涨跌中位数、涨跌幅分布。 |
| 使用页面 | 市场总览必需。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `upCount`、`downCount`、`flatCount`、`redRate`、`medianChangePct`、`distribution`、`history`。 |
| 字段类型 | `number|null`、`Direction`、`DistributionBucket[]`、`TrendPoint[]`。 |
| 与 API 字段的映射 | `data.breadth` 或 `/api/market/breadth`。 |
| 视觉结构 | Panel 内上方 MetricCard 组，下方 DistributionChart，可附近半年趋势入口。 |
| 交互行为 | 点击涨跌区间下钻榜单；hover 显示口径。 |
| 状态 | default：正常展示；hover：可点击区域轻微提亮；active：点击压暗或描边增强；selected：当前项显示选中底色/左侧标识线；disabled：降低透明度并禁止点击；loading：骨架或占位，不改变布局；empty：显示原因和下一步动作；error：显示异常说明和重试入口。 |
| 涨跌色规则 | 上涨家数红，下跌家数绿，平盘灰；中位涨跌按正负红绿。 |
| 与 Design Token 的关系 | `--csq-color-bg-panel`、`--csq-color-rise/fall/flat`、`--csq-density-panel-gap`。 |
| 备注 | 只展示客观分布，不写“赚钱效应强/弱”的主观结论。 |


### 5.14. MarketStylePanel

| 项 | 说明 |
|---|---|
| 组件名称 | `MarketStylePanel` |
| 组件用途 | 展示大盘/小盘、权重/题材、涨跌中位数、等权平均涨跌幅等市场风格客观统计。 |
| 使用页面 | 市场总览必需。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `medianChangePct`、`equalWeightChangePct`、`largeCapChangePct`、`smallCapChangePct`、`styleItems`。 |
| 字段类型 | `number|null`、`Array<{label:string; value:number; direction:Direction}>`。 |
| 与 API 字段的映射 | `data.style` 或 `/api/market/style`。 |
| 视觉结构 | 紧凑对比条 + MetricCard，避免大仪表盘。 |
| 交互行为 | hover 展示口径；点击可进入板块与榜单页风格筛选。 |
| 状态 | default：正常展示；hover：可点击区域轻微提亮；active：点击压暗或描边增强；selected：当前项显示选中底色/左侧标识线；disabled：降低透明度并禁止点击；loading：骨架或占位，不改变布局；empty：显示原因和下一步动作；error：显示异常说明和重试入口。 |
| 涨跌色规则 | 涨跌百分比按 direction 红绿；风格标签本身不用红绿。 |
| 与 Design Token 的关系 | `--csq-color-rise/fall/flat`、`--csq-color-bg-panel`、`--csq-font-family-number`。 |
| 备注 | 禁止输出“今日不适合题材股”等主观建议。 |


### 5.15. TurnoverSummaryCard

| 项 | 说明 |
|---|---|
| 组件名称 | `TurnoverSummaryCard` |
| 组件用途 | 展示全市场成交额、较上一交易日变化、5 日/20 日均值或中位水平、历史成交额曲线。 |
| 使用页面 | 市场总览必需。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `totalAmount`、`amountChange`、`amountChangePct`、`marketBreakdown`、`history`、`unit`。 |
| 字段类型 | `AmountValue`、`number|null`、`TrendPoint[]`。 |
| 与 API 字段的映射 | `data.turnover` 或 `/api/market/turnover`。 |
| 视觉结构 | 主值大数字 + 同比/环比小标签 + MiniTrendChart。 |
| 交互行为 | hover 趋势线显示日期与成交额；点击进入成交额历史详情或榜单页。 |
| 状态 | default：正常展示；hover：可点击区域轻微提亮；active：点击压暗或描边增强；selected：当前项显示选中底色/左侧标识线；disabled：降低透明度并禁止点击；loading：骨架或占位，不改变布局；empty：显示原因和下一步动作；error：显示异常说明和重试入口。 |
| 涨跌色规则 | 成交额主值默认中性；较昨日增加可红，减少可绿，但需标注“较昨日”。 |
| 与 Design Token 的关系 | `--csq-font-family-number`、`--csq-color-bg-panel`、`--csq-color-rise/fall/flat`。 |
| 备注 | 金额单位按 API `unit/displayText` 格式化，不在组件里固定换算。 |


### 5.16. MoneyFlowSummaryPanel

| 项 | 说明 |
|---|---|
| 组件名称 | `MoneyFlowSummaryPanel` |
| 组件用途 | 资金流向模块容器，组合净流入摘要、FundFlowBar、历史趋势和数据状态。 |
| 使用页面 | 市场总览必需。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `summary`、`segments`、`history`、`dataStatus`、`sourceRefs`。 |
| 字段类型 | `summary: MoneyFlowSummary; segments: FundFlowSegment[]`。 |
| 与 API 字段的映射 | `data.moneyFlow` 或 `/api/moneyflow/market`。 |
| 视觉结构 | 上方净流入/净流出主值，中部 FundFlowBar，下方数据时间/趋势。 |
| 交互行为 | hover 展示来源；点击资金类型进入资金榜。 |
| 状态 | default：正常展示；hover：可点击区域轻微提亮；active：点击压暗或描边增强；selected：当前项显示选中底色/左侧标识线；disabled：降低透明度并禁止点击；loading：骨架或占位，不改变布局；empty：显示原因和下一步动作；error：显示异常说明和重试入口。 |
| 涨跌色规则 | 净流入红、净流出绿、零值灰；数据状态不使用行情红绿。 |
| 与 Design Token 的关系 | `--csq-color-rise/fall/flat`、`--csq-color-warning`、`--csq-color-bg-panel`。 |
| 备注 | 首页不输出资金面分数或“资金面强弱评级”。 |


### 5.17. LimitUpSummaryCard

| 项 | 说明 |
|---|---|
| 组件名称 | `LimitUpSummaryCard` |
| 组件用途 | 展示涨停、跌停、炸板、封板率、连板家数、最高连板、天地板、地天板等短线事实。 |
| 使用页面 | 市场总览必需。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `limitUpCount`、`limitDownCount`、`brokenLimitCount`、`sealRate`、`streakCount`、`highestStreak`、`firstBoardCount`、`secondBoardCount`、`thirdPlusCount`。 |
| 字段类型 | `number|null`、`percent number`。 |
| 与 API 字段的映射 | `data.limitUp` 或 `/api/limitup/summary`。 |
| 视觉结构 | 多 MetricCard 组成的摘要卡，可突出最高连板和封板率。 |
| 交互行为 | 点击涨停/跌停/炸板进入对应榜单；hover 展示定义。 |
| 状态 | default：正常展示；hover：可点击区域轻微提亮；active：点击压暗或描边增强；selected：当前项显示选中底色/左侧标识线；disabled：降低透明度并禁止点击；loading：骨架或占位，不改变布局；empty：显示原因和下一步动作；error：显示异常说明和重试入口。 |
| 涨跌色规则 | 涨停、连板红；跌停绿；炸板可用 warning 或中性，避免误判为涨跌方向。 |
| 与 Design Token 的关系 | `--csq-color-rise/fall/warning`、`--csq-font-family-number`、`--csq-color-bg-panel`。 |
| 备注 | 只展示短线情绪事实，不写“情绪高潮/冰点”。 |


### 5.18. LimitUpDistribution

| 项 | 说明 |
|---|---|
| 组件名称 | `LimitUpDistribution` |
| 组件用途 | 展示涨跌停在板块、连板高度、涨跌幅区间、炸板板块上的分布。 |
| 使用页面 | 市场总览必需。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `items`、`mode`、`onItemClick`。 |
| 字段类型 | `items: Array<{key:string; label:string; count:number; direction?:Direction; sectorCode?:string}>`。 |
| 与 API 字段的映射 | `data.limitUpDistribution` 或由 `data.limitUp`、`data.streakLadder`、`data.topSectors` 派生。 |
| 视觉结构 | 小型条形图/列表/标签云，和 LimitUpSummaryCard 并列。 |
| 交互行为 | 点击板块/层级进入对应榜单；hover 显示数量和占比。 |
| 状态 | default：正常展示；hover：可点击区域轻微提亮；active：点击压暗或描边增强；selected：当前项显示选中底色/左侧标识线；disabled：降低透明度并禁止点击；loading：骨架或占位，不改变布局；empty：显示原因和下一步动作；error：显示异常说明和重试入口。 |
| 涨跌色规则 | 涨停分布红，跌停分布绿，炸板 warning。 |
| 与 Design Token 的关系 | `--csq-color-rise/fall/warning`、`--csq-color-chart-grid`、`--csq-color-bg-panel`。 |
| 备注 | 数据不足时展示可解释空态，不要伪造板块分布。 |


### 5.19. SectorTable

| 项 | 说明 |
|---|---|
| 组件名称 | `SectorTable` |
| 组件用途 | 高密度板块表格，展示板块名称、类型、涨跌幅、成交额、资金净流入、上涨/下跌成分、领涨股。 |
| 使用页面 | 市场总览必需；板块与榜单行情页复用。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `rows`、`columns`、`sort`、`onRowClick`、`onLeaderStockClick`。 |
| 字段类型 | `rows: SectorRankItem[]`。 |
| 与 API 字段的映射 | `data.topSectors.items[]` 或 `/api/sector/top`。 |
| 视觉结构 | 表格行高 34–40px，数字右对齐，板块名左对齐。 |
| 交互行为 | 点击板块进入板块与榜单页；点击领涨股进入个股详情；表头排序。 |
| 状态 | default：正常展示；hover：可点击区域轻微提亮；active：点击压暗或描边增强；selected：当前项显示选中底色/左侧标识线；disabled：降低透明度并禁止点击；loading：骨架或占位，不改变布局；empty：显示原因和下一步动作；error：显示异常说明和重试入口。 |
| 涨跌色规则 | 板块涨跌幅红涨绿跌；资金净流入红、净流出绿。 |
| 与 Design Token 的关系 | `--csq-density-table-row-height`、`--csq-font-family-number`、`--csq-color-rise/fall/flat`。 |
| 备注 | 首页只展示 Top 5–10，完整表放到板块与榜单行情页。 |


### 5.20. SectorRankList

| 项 | 说明 |
|---|---|
| 组件名称 | `SectorRankList` |
| 组件用途 | 板块速览列表，适合展示行业涨幅前五、跌幅前五、概念涨幅前五、资金流入前五等多个小榜。 |
| 使用页面 | 市场总览必需。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `groups`、`activeGroup`、`onGroupChange`、`onSectorClick`。 |
| 字段类型 | `groups: Array<{key:string; title:string; items:SectorRankItem[]}>`。 |
| 与 API 字段的映射 | `data.topSectors.groups[]`；若 API 仅返回平铺数组，由 ViewModel 按 `rankType/sectorType` 分组。 |
| 视觉结构 | 多个紧凑小列表或 Tab + list；每行展示排名、板块、涨跌幅/资金。 |
| 交互行为 | 切换行业/概念/地域/资金；点击板块下钻。 |
| 状态 | default：正常展示；hover：可点击区域轻微提亮；active：点击压暗或描边增强；selected：当前项显示选中底色/左侧标识线；disabled：降低透明度并禁止点击；loading：骨架或占位，不改变布局；empty：显示原因和下一步动作；error：显示异常说明和重试入口。 |
| 涨跌色规则 | 涨幅榜红，跌幅榜绿，资金流入红、流出绿。 |
| 与 Design Token 的关系 | `--csq-color-rise/fall`、`--csq-color-bg-panel`、`--csq-font-family-number`。 |
| 备注 | 比 HeatMap 更适合首页首屏；HeatMap 可放下半屏或作为入口。 |


### 5.21. HeatMap

| 项 | 说明 |
|---|---|
| 组件名称 | `HeatMap` |
| 组件用途 | 板块热力图预览，用面积或矩形块展示板块涨跌、成交额、资金流。 |
| 使用页面 | 市场总览必需，但可作为小型预览或入口；板块页完整展开。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `items`、`colorMetric`、`sizeMetric`、`onItemClick`。 |
| 字段类型 | `items: Array<{sectorCode:string; sectorName:string; changePct:number; amount?:number; netInflow?:number; direction:Direction; weight?:number}>`。 |
| 与 API 字段的映射 | `data.topSectors.heatMapItems`；若暂缺，可由 `topSectors.items[]` 派生预览。 |
| 视觉结构 | 矩形网格，面积表达成交额或市值权重，颜色表达涨跌方向。 |
| 交互行为 | hover 显示板块名、涨跌幅、成交额、资金；点击板块下钻。 |
| 状态 | default：正常展示；hover：可点击区域轻微提亮；active：点击压暗或描边增强；selected：当前项显示选中底色/左侧标识线；disabled：降低透明度并禁止点击；loading：骨架或占位，不改变布局；empty：显示原因和下一步动作；error：显示异常说明和重试入口。 |
| 涨跌色规则 | 上涨红、下跌绿、平盘灰；颜色深浅表达幅度绝对值。 |
| 与 Design Token 的关系 | `--csq-color-rise/fall/flat`、`--csq-color-bg-panel`、`--csq-color-tooltip-bg`。 |
| 备注 | 不做花哨三维大屏热力图，避免廉价感。 |


### 5.22. StockTable

| 项 | 说明 |
|---|---|
| 组件名称 | `StockTable` |
| 组件用途 | 个股高密度行情表，用于展示榜单中股票代码、名称、最新价、涨跌幅、成交额、换手率、量比、行业/概念。 |
| 使用页面 | 市场总览必需；板块、个股列表、自选页复用。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `rows`、`columns`、`sort`、`onRowClick`、`onActionClick`。 |
| 字段类型 | `rows: StockRankItem[]`。 |
| 与 API 字段的映射 | `data.stockLeaderboards.*.items[]`。 |
| 视觉结构 | 高密度表格，股票名和代码双行或同列，数字列右对齐。 |
| 交互行为 | 行 hover；点击进入个股详情；表头排序。 |
| 状态 | default：正常展示；hover：可点击区域轻微提亮；active：点击压暗或描边增强；selected：当前项显示选中底色/左侧标识线；disabled：降低透明度并禁止点击；loading：骨架或占位，不改变布局；empty：显示原因和下一步动作；error：显示异常说明和重试入口。 |
| 涨跌色规则 | 最新价、涨跌额、涨跌幅红涨绿跌；成交额等默认中性。 |
| 与 Design Token 的关系 | `--csq-density-table-row-height`、`--csq-font-family-number`、`--csq-color-rise/fall/flat`。 |
| 备注 | 首页表格不展示过多操作按钮，避免从行情速览变成后台列表。 |


### 5.23. SortableHeader

| 项 | 说明 |
|---|---|
| 组件名称 | `SortableHeader` |
| 组件用途 | 表格表头排序控件，用于涨跌幅、成交额、换手率、量比等字段排序。 |
| 使用页面 | 市场总览必需，RankingTable/SectorTable/StockTable 内部使用。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `field`、`label`、`order`、`disabled`、`onSortChange`。 |
| 字段类型 | `order: 'asc'|'desc'|null`。 |
| 与 API 字段的映射 | 排序字段对应 `stockLeaderboards` 或 `topSectors` 中可排序字段；首页本地排序或跳转完整榜单排序。 |
| 视觉结构 | 表头文字 + 小箭头；选中排序时箭头高亮。 |
| 交互行为 | 点击切换降序/升序/取消；disabled 时显示不可排序。 |
| 状态 | default：正常展示；hover：可点击区域轻微提亮；active：点击压暗或描边增强；selected：当前项显示选中底色/左侧标识线；disabled：降低透明度并禁止点击；loading：骨架或占位，不改变布局；empty：显示原因和下一步动作；error：显示异常说明和重试入口。 |
| 涨跌色规则 | 不承载涨跌色，排序高亮用品牌色。 |
| 与 Design Token 的关系 | `--csq-color-text-secondary`、`--csq-color-brand`、`--csq-font-size-xs`。 |
| 备注 | 首页排序不应触发大量接口风暴；可本地排序 Top 数据。 |


### 5.24. TabPanel

| 项 | 说明 |
|---|---|
| 组件名称 | `TabPanel` |
| 组件用途 | 多榜单 Tab 容器，用于涨幅榜、跌幅榜、成交额榜、换手榜、量比异动榜切换。 |
| 使用页面 | 市场总览必需；全站复用。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `tabs`、`activeKey`、`variant`、`onChange`。 |
| 字段类型 | `tabs: Array<{key:string; label:string; count?:number; disabled?:boolean}>`。 |
| 与 API 字段的映射 | `stockLeaderboards[].rankType` 或前端配置。 |
| 视觉结构 | Panel 顶部紧凑 Tab，选中态使用品牌底线或细描边。 |
| 交互行为 | 点击切换；键盘左右切换；disabled Tab 不响应。 |
| 状态 | default：正常展示；hover：可点击区域轻微提亮；active：点击压暗或描边增强；selected：当前项显示选中底色/左侧标识线；disabled：降低透明度并禁止点击；loading：骨架或占位，不改变布局；empty：显示原因和下一步动作；error：显示异常说明和重试入口。 |
| 涨跌色规则 | 不直接承载涨跌色；涨幅榜/跌幅榜的内容自身着色。 |
| 与 Design Token 的关系 | `--csq-color-brand`、`--csq-color-border-subtle`、`--csq-font-size-sm`。 |
| 备注 | Tab 数量控制在 4–6 个，避免拥挤。 |


### 5.25. LoadingSkeleton

| 项 | 说明 |
|---|---|
| 组件名称 | `LoadingSkeleton` |
| 组件用途 | 行情页面的骨架屏，避免首次加载或局部刷新时整页闪烁。 |
| 使用页面 | 市场总览必需；所有模块复用。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `variant`、`rows`、`height`、`animated`。 |
| 字段类型 | `variant:'card'|'table'|'chart'|'topbar'|'text'`。 |
| 与 API 字段的映射 | 不映射业务 API；由组件加载状态触发。 |
| 视觉结构 | 根据变体显示卡片骨架、表格骨架行、图表网格、顶部 ticker 占位。 |
| 交互行为 | 不可点击；局部刷新时保留旧数据优先，必要时覆盖小 skeleton。 |
| 状态 | default：正常展示；hover：可点击区域轻微提亮；active：点击压暗或描边增强；selected：当前项显示选中底色/左侧标识线；disabled：降低透明度并禁止点击；loading：骨架或占位，不改变布局；empty：显示原因和下一步动作；error：显示异常说明和重试入口。 |
| 涨跌色规则 | 不使用涨跌色，使用中性骨架色。 |
| 与 Design Token 的关系 | `--csq-color-skeleton-bg`、`--csq-color-skeleton-highlight`、`--csq-radius-sm`。 |
| 备注 | 刷新时优先显示小型 loading，不要整页清空。 |


### 5.26. EmptyState

| 项 | 说明 |
|---|---|
| 组件名称 | `EmptyState` |
| 组件用途 | 模块无数据时的解释型空状态。 |
| 使用页面 | 市场总览必需；所有模块复用。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `title`、`description`、`reason`、`actionText`、`onAction`、`variant`。 |
| 字段类型 | `reason:'NON_TRADING_DAY'|'NOT_GENERATED'|'NO_RESULT'|'NO_PERMISSION'`。 |
| 与 API 字段的映射 | 对应 API `code=404001`、模块 `dataStatus='EMPTY'` 或空数组。 |
| 视觉结构 | 小型空态块，图标弱化，文案说明原因和下一步。 |
| 交互行为 | 可点击刷新、查看最近交易日或进入配置。 |
| 状态 | default：正常展示；hover：可点击区域轻微提亮；active：点击压暗或描边增强；selected：当前项显示选中底色/左侧标识线；disabled：降低透明度并禁止点击；loading：骨架或占位，不改变布局；empty：显示原因和下一步动作；error：显示异常说明和重试入口。 |
| 涨跌色规则 | 不使用涨跌红绿，使用中性色。 |
| 与 Design Token 的关系 | `--csq-color-text-muted`、`--csq-color-bg-panel`、`--csq-font-size-sm`。 |
| 备注 | 禁止只写“暂无数据”；必须说明原因。 |


### 5.27. ErrorState

| 项 | 说明 |
|---|---|
| 组件名称 | `ErrorState` |
| 组件用途 | 模块级异常状态，用于网络异常、服务异常、数据源不可用、字段缺失、计算失败。 |
| 使用页面 | 市场总览必需；所有模块复用。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `title`、`message`、`code`、`traceId`、`retryText`、`onRetry`。 |
| 字段类型 | `code?:number|string; traceId?:string`。 |
| 与 API 字段的映射 | 对应统一响应 `code!=0`，尤其 `500001/503001`。 |
| 视觉结构 | 小型错误块，系统错误色细边框，保留模块尺寸。 |
| 交互行为 | 点击重试；可复制 traceId；不阻塞其他模块。 |
| 状态 | default：正常展示；hover：可点击区域轻微提亮；active：点击压暗或描边增强；selected：当前项显示选中底色/左侧标识线；disabled：降低透明度并禁止点击；loading：骨架或占位，不改变布局；empty：显示原因和下一步动作；error：显示异常说明和重试入口。 |
| 涨跌色规则 | 使用系统错误色，不使用行情上涨红。 |
| 与 Design Token 的关系 | `--csq-color-danger-system`、`--csq-color-bg-panel`、`--csq-color-text-secondary`。 |
| 备注 | 单模块异常不允许导致市场总览整页白屏。 |


### 5.28. DataDelayState

| 项 | 说明 |
|---|---|
| 组件名称 | `DataDelayState` |
| 组件用途 | 数据延迟状态提示，用于盘中数据延迟、数据源未同步、使用最近缓存等。 |
| 使用页面 | 市场总览必需；DataStatusBadge 详情复用。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `asOf`、`delaySeconds`、`latestTradeDate`、`sourceRefs`、`message`。 |
| 字段类型 | `delaySeconds:number; sourceRefs:SourceRef[]`。 |
| 与 API 字段的映射 | 模块 `dataStatus='DELAYED'`、`isDelayed=true`、`sourceRefs[]`。 |
| 视觉结构 | 黄色/琥珀弱提示条或 Badge Popover。 |
| 交互行为 | 点击查看数据源状态；可触发刷新。 |
| 状态 | default：正常展示；hover：可点击区域轻微提亮；active：点击压暗或描边增强；selected：当前项显示选中底色/左侧标识线；disabled：降低透明度并禁止点击；loading：骨架或占位，不改变布局；empty：显示原因和下一步动作；error：显示异常说明和重试入口。 |
| 涨跌色规则 | 不使用涨跌色；使用 warning。 |
| 与 Design Token 的关系 | `--csq-color-warning`、`--csq-color-bg-panel`、`--csq-font-size-xs`。 |
| 备注 | 延迟不是错误，不应使用强错误视觉。 |


### 5.29. PermissionState

| 项 | 说明 |
|---|---|
| 组件名称 | `PermissionState` |
| 组件用途 | 无权限或未登录状态提示，主要用于我的自选、我的持仓、提醒中心等个人入口状态。 |
| 使用页面 | 市场总览必需但只用于个人入口/局部状态；市场公共行情不因未登录隐藏。 |
| 是否市场总览 P0 必需 | 是。 |
| 输入字段 / Props | `title`、`description`、`actionText`、`onLogin`、`scope`。 |
| 字段类型 | `scope:'WATCHLIST'|'POSITION'|'ALERT'|'SETTINGS'`。 |
| 与 API 字段的映射 | 对应 `code=401001/403001` 或个人入口 `requireLogin=true`。 |
| 视觉结构 | 小型权限提示，不遮挡公共行情模块。 |
| 交互行为 | 点击登录或进入设置；无权限时显示申请/说明。 |
| 状态 | default：正常展示；hover：可点击区域轻微提亮；active：点击压暗或描边增强；selected：当前项显示选中底色/左侧标识线；disabled：降低透明度并禁止点击；loading：骨架或占位，不改变布局；empty：显示原因和下一步动作；error：显示异常说明和重试入口。 |
| 涨跌色规则 | 不使用涨跌色。 |
| 与 Design Token 的关系 | `--csq-color-info`、`--csq-color-warning`、`--csq-color-text-muted`。 |
| 备注 | 未登录不能影响市场总览主行情事实展示。 |


---

## 6. 明确不作为市场总览 P0 必需的组件

| 组件 / 模式 | 本轮处理方式 | 原因 |
|---|---|---|
| `SideNav` | 全局组件库未来可以保留，但**不用于市场总览 P0 桌面端** | 会压缩行情横向空间，降低表格、图表、热力图可读性 |
| `PersistentLeftRail` | 不用于市场总览 P0 | 与 PRD 的顶部栏 + 面包屑 + 快捷入口框架冲突 |
| 大型左侧导航栏 | 不设计 | 行情终端首页需要最大化横向内容区 |
| 大面积入口卡片墙 | 不设计 | 会挤压首屏核心市场事实 |
| 营销式 Hero Banner | 不设计 | 与专业、沉稳、高密度金融终端风格冲突 |
| `SentimentGauge` | 不用于市场总览首页 | 市场温度、情绪指数、资金面分数、风险指数属于市场温度与情绪分析页 |
| `OpportunityCard` | 不作为市场总览 P0 组件 | 机会雷达页承载，不在市场总览混入机会判断 |
| `ScoreBreakdown` | 不作为市场总览 P0 组件 | 综合评分拆解不属于客观事实首页 |
| `AlertRuleEditor` | 不作为市场总览 P0 组件 | 市场总览只提供提醒中心入口，规则编辑在提醒中心或个股详情完成 |
| `KlineChartShell` | 不作为市场总览 P0 组件 | 指数详情/个股详情使用，市场总览只展示小趋势线 |
| `RadarChart` | 不作为市场总览 P0 组件 | 机会雷达页使用，市场总览不展示机会评分 |

---

## 7. 市场总览 P0 必需组件清单

### 7.1 顶部与层级组件

- `TopMarketBar`
- `GlobalSystemMenu`
- `IndexTickerStrip`
- `Breadcrumb`
- `PageHeader`
- `MarketStatusPill`
- `DataStatusBadge`

### 7.2 页面快捷入口组件

- `ShortcutBar`
- `QuickEntryCard`
- `QuickEntryBadge`

### 7.3 行情指标组件

- `IndexCard`
- `MetricCard`
- `ChangeBadge`
- `QuoteTicker`
- `MiniTrendChart`

### 7.4 市场结构组件

- `DistributionChart`
- `MarketBreadthPanel`
- `MarketStylePanel`
- `TurnoverSummaryCard`
- `FundFlowBar`
- `MoneyFlowSummaryPanel`

### 7.5 涨跌停组件

- `LimitUpSummaryCard`
- `LimitUpDistribution`
- `LimitUpStreakLadder`

### 7.6 板块与榜单组件

- `SectorTable`
- `SectorRankList`
- `HeatMap`
- `RankingTable`
- `StockTable`
- `SortableHeader`
- `TabPanel`

### 7.7 状态组件

- `LoadingSkeleton`
- `EmptyState`
- `ErrorState`
- `DataDelayState`
- `PermissionState`

---

## 8. 可后置组件清单

| 组件 | 后置原因 | 建议进入阶段 |
|---|---|---|
| `SideNav` | 市场总览不用；后续若全站需要可独立评估 | P1 全局框架评审 |
| `FilterBar` | 市场总览首页以默认 A 股和当前交易日为主，复杂筛选放到详情页 | 板块与榜单页 |
| `Drawer` | 市场总览优先下钻页面，不用大量抽屉堆信息 | P1 |
| `Modal` | 首页不做复杂编辑；个人配置在设置/提醒中心处理 | P1 |
| `Pagination` | 首页只展示 Top 5–10，完整分页在榜单页 | 板块与榜单页 |
| `KlineChartShell` | 市场总览只需要 MiniTrendChart | 指数详情 / 个股详情 |
| `IndicatorPanelShell` | 指标区属于详情页 | 指数详情 / 个股详情 |
| `OpportunityCard` | 属于机会雷达 | 财势探查 P0 |
| `SignalBadge` | 属于机会/策略表达 | 财势探查 P0 |
| `ScoreBreakdown` | 属于分析评分拆解 | 市场温度与情绪 / 机会雷达 |
| `RiskHint` | 属于风险提示，不混入市场总览客观页 | 持仓深度分析 / 情绪页 |
| `AlertRuleEditor` | 属于提醒中心和个股详情 | 交易助手 P0 |
| `WatchlistTable` | 我的自选页使用 | 乾坤行情 P0 |
| `PositionTable` | 持仓页面使用 | 交易助手 P0 |
| `TradePlanCard` | 完整交易计划体系后置 | P1 |

---

## 9. 与 01 Design Token 的依赖说明

组件实现必须等待或对齐以下 Token，不能在页面 CSS 中随意硬编码：

1. **行情方向色**：`rise / fall / flat` 及弱背景色。
2. **系统状态色**：`warning / danger-system / info`，与行情红绿分离。
3. **深色主题背景层级**：页面背景、顶部栏、面板、hover、selected、tooltip。
4. **浅色主题映射**：同名 Token 切换，不改组件结构。
5. **数字字体 Token**：行情数字、金额、百分比必须等宽或近似等宽。
6. **高密度尺寸 Token**：顶部栏高度、PageHeader 高度、表格行高、卡片 padding。
7. **图表 Token**：网格线、Tooltip、涨跌柱/线/热力图颜色。
8. **层级 Token**：TopMarketBar、Popover、Tooltip 的 z-index。

建议 01 Token 明确输出以下 CSS 变量：

```css
:root[data-theme="dark"] {
  --csq-color-bg-page: ...;
  --csq-color-bg-topbar: ...;
  --csq-color-bg-panel: ...;
  --csq-color-bg-panel-hover: ...;
  --csq-color-border-subtle: ...;
  --csq-color-text-primary: ...;
  --csq-color-text-secondary: ...;
  --csq-color-rise: ...;
  --csq-color-rise-bg: ...;
  --csq-color-fall: ...;
  --csq-color-fall-bg: ...;
  --csq-color-flat: ...;
  --csq-color-brand: ...;
  --csq-color-warning: ...;
  --csq-color-danger-system: ...;
  --csq-font-family-number: ...;
  --csq-density-topbar-height: ...;
  --csq-density-table-row-height: ...;
}
```

---

## 10. 与 04 API 字段的映射说明

### 10.1 核心原则

1. 市场总览优先使用 `GET /api/market/home-overview` 聚合接口。
2. 模块刷新、懒加载、错误重试使用模块接口。
3. 组件 Props 不直接暴露 Tushare 原始字段名，统一由 ViewModel 适配为业务字段。
4. 金额、成交量等数值单位由 API 字段说明、`unit`、`displayText` 或 `sourceRefs` 决定，组件不自行假设。
5. API 不得向市场总览返回市场温度、情绪指数、资金面分数、风险指数作为首页核心展示字段。

### 10.2 组件到 API 字段映射总表

| 组件 | 聚合字段 | 模块接口 | 关键字段 |
|---|---|---|---|
| `TopMarketBar` | `overview`、`indices` | `/api/market/overview`、`/api/index/summary` | `market`、`tradeDate`、`sessionStatus`、`asOf`、`dataStatus`、`indices[]` |
| `GlobalSystemMenu` | 无 | 路由配置 / 权限接口 | `activeSystem`、`systems[]` |
| `IndexTickerStrip` | `indices` | `/api/index/summary` | `code`、`name`、`latestPoint`、`changePct`、`direction` |
| `Breadcrumb` | 可选 `breadcrumb` | 路由配置 | 固定：财势乾坤 / 乾坤行情 / 市场总览 |
| `PageHeader` | `overview` | `/api/market/overview` | `tradeDate`、`sessionStatus`、`asOf`、`dataStatus` |
| `MarketStatusPill` | `overview` | `/api/market/overview` | `sessionStatus`、`isTradingDay`、`openTime`、`closeTime` |
| `DataStatusBadge` | 各模块 `dataStatus` | 各模块接口 | `dataStatus`、`asOf`、`delaySeconds`、`sourceRefs[]` |
| `ShortcutBar` | `quickEntries` | `/api/settings/quick-entry` | `key`、`title`、`route`、`enabled`、`badge` |
| `IndexCard` | `indices` | `/api/index/summary` | `latestPoint`、`change`、`changePct`、`amount`、`trend[]` |
| `MetricCard` | 多模块 | 多模块接口 | `upCount`、`downCount`、`redRate`、`totalAmount`、`limitUpCount` 等 |
| `DistributionChart` | `breadth` | `/api/market/breadth` | `distribution[]`、`upCount`、`downCount`、`flatCount` |
| `MarketBreadthPanel` | `breadth` | `/api/market/breadth` | `medianChangePct`、`redRate`、`history[]` |
| `MarketStylePanel` | `style` | `/api/market/style` | `largeCapChangePct`、`smallCapChangePct`、`equalWeightChangePct` |
| `TurnoverSummaryCard` | `turnover` | `/api/market/turnover` | `totalAmount`、`amountChange`、`history[]`、`unit` |
| `FundFlowBar` | `moneyFlow` | `/api/moneyflow/market` | `mainNetInflow`、`superLargeNetInflow`、`largeNetInflow`、`mediumNetInflow`、`smallNetInflow` |
| `MoneyFlowSummaryPanel` | `moneyFlow` | `/api/moneyflow/market` | `summary`、`segments[]`、`history[]`、`dataStatus` |
| `LimitUpSummaryCard` | `limitUp` | `/api/limitup/summary` | `limitUpCount`、`limitDownCount`、`brokenLimitCount`、`sealRate`、`highestStreak` |
| `LimitUpDistribution` | `limitUpDistribution` | `/api/limitup/summary` 或后续分布接口 | `items[]`、`sectorDistribution[]`、`streakDistribution[]` |
| `LimitUpStreakLadder` | `streakLadder` | `/api/limitup/streak-ladder` | `streak`、`count`、`items[].stockCode`、`openTimes`、`firstLimitTime` |
| `SectorRankList` / `SectorTable` | `topSectors` | `/api/sector/top` | `sectorCode`、`sectorName`、`sectorType`、`changePct`、`netInflow`、`leaderStock` |
| `HeatMap` | `topSectors.heatMapItems` | `/api/sector/top` 或后续热力图接口 | `sectorCode`、`sectorName`、`changePct`、`amount`、`weight` |
| `RankingTable` / `StockTable` | `stockLeaderboards` | `/api/leaderboard/stock` | `rankType`、`items[].stockCode`、`latestPrice`、`changePct`、`amount`、`turnoverRate`、`volumeRatio` |
| `LoadingSkeleton` | 无 | 前端状态 | `loading=true` |
| `EmptyState` | 各模块 | 各模块接口 | `dataStatus='EMPTY'`、空数组、`code=404001` |
| `ErrorState` | 各模块 | 各模块接口 | `code!=0`、`traceId`、`message` |
| `DataDelayState` | 各模块 | 各模块接口 | `dataStatus='DELAYED'`、`delaySeconds`、`sourceRefs[]` |
| `PermissionState` | 个人入口 | 用户/权限接口 | `code=401001/403001`、`requireLogin=true` |

---

## 11. 给 02 HTML Showcase 的组件使用建议

1. Showcase 文件建议：`/docs/wealth/showcase/market-overview-v1.html`。
2. 单文件 HTML/CSS/JS；不依赖构建工具。
3. 页面标题必须是“市场总览”，层级必须是“财势乾坤 / 乾坤行情 / 市场总览”。
4. 桌面端不得出现固定 SideNav、PersistentLeftRail、大型左侧导航栏。
5. 顶部必须体现：`TopMarketBar + GlobalSystemMenu + IndexTickerStrip + 时间 + MarketStatusPill + DataStatusBadge + 用户入口`。
6. PageHeader 必须体现 A 股、交易日、更新时间、刷新按钮。
7. ShortcutBar 必须包含：市场温度与情绪、机会雷达、我的自选、我的持仓、提醒中心、用户设置。
8. ShortcutBar 不得展示市场温度、情绪指数、资金面分数、风险指数的数值或结论。
9. 首屏必须展示：主要指数、涨跌分布、市场风格、成交额、资金流、涨跌停核心统计。
10. 下半屏或第二屏展示：涨跌停分布、连板天梯、板块速览、热力图、榜单速览。
11. 所有 mock 数据必须真实感：指数点位、涨跌幅、成交额、家数、资金流要符合 A 股语境。
12. 所有涨跌颜色必须红涨绿跌，包括 Tooltip、表格、图表、热力图、趋势线。
13. 图表可用 SVG/Canvas/CSS 模拟，但必须表达 hover、selected、下钻入口。
14. 状态展示至少覆盖：一个 loading 骨架、一个数据延迟 Badge、一个模块级 error 或 empty 示例。

---

## 12. 给 05 Codex 提示词的组件约束

Codex 实现市场总览页面时，提示词必须包含以下约束：

```text
你需要实现“财势乾坤 / 乾坤行情 / 市场总览”页面。

必须阅读：
1. /docs/wealth/00-project-overview.md
2. /docs/wealth/prd/market-overview-prd.md
3. /docs/wealth/03-design-tokens.md
4. /docs/wealth/04-component-guidelines.md
5. /docs/wealth/api/market-overview-api.md
6. /docs/wealth/showcase/market-overview-v1.html（如存在）

实现约束：
- 页面名称为“市场总览”。
- 页面属于“乾坤行情”，不是独立一级菜单。
- 桌面端不允许实现固定 SideNav / PersistentLeftRail / 大型左侧导航栏。
- 必须使用 TopMarketBar、GlobalSystemMenu、IndexTickerStrip、Breadcrumb、PageHeader、ShortcutBar、全宽行情内容区。
- 必须实现 IndexCard、MarketBreadthPanel、DistributionChart、MarketStylePanel、TurnoverSummaryCard、MoneyFlowSummaryPanel、FundFlowBar、LimitUpSummaryCard、LimitUpDistribution、LimitUpStreakLadder、SectorRankList、HeatMap、RankingTable。
- 必须遵守中国市场红涨绿跌。
- ShortcutBar 只能提供市场温度与情绪等页面入口，不展示市场温度、情绪指数、资金面分数、风险指数的具体数值或结论。
- 所有金额、成交量单位按 API 字段说明、unit 或 displayText 格式化，不要在前端组件中擅自改写业务口径。
- 单个模块失败不能导致整页白屏；必须有 loading/empty/error/data-delay/permission 状态。
- 不要新增 PRD 未要求的大型组件或营销区。

Smoke test：
1. 打开市场总览路由无白屏。
2. 顶部栏、面包屑、页面头、快捷入口、核心行情模块全部渲染。
3. 指数卡点击进入指数详情路由参数正确。
4. 涨跌分布区间 hover 有 Tooltip，点击能带筛选参数下钻。
5. 连板天梯股票点击进入个股详情。
6. RankingTable Tab 可切换，行 hover 明显，点击个股可下钻。
7. 红涨绿跌无反向错误。
8. loading/empty/error 至少可通过 mock 状态切换验证。
9. 控制台无明显错误。
```

---

## 13. 待产品总控确认问题

1. 市场总览是否作为系统默认落地页，但导航归属继续固定为“乾坤行情 / 市场总览”？
2. TopMarketBar 中一级系统入口是横向常显，还是折叠到“系统菜单”？建议默认横向展示核心系统，窄屏折叠。
3. 主要指数首屏展示数量：4 个、6 个还是 7 个？建议桌面端 6–7 个，空间不足时 TopMarketBar 保留 3–5 个。
4. ShortcutBar 是否展示个人状态数量：自选数量、持仓数量、未读提醒数量？建议允许，但不能展示分析分数。
5. HeatMap 在市场总览中是直接展示小型预览，还是只作为入口？建议展示小型预览，完整热力图在板块与榜单行情页。
6. 连板天梯首页展示完整层级，还是每层限制最多 3–5 个个股？建议首页限制数量，更多进入详情。
7. 资金流 P0 是否确认包含超大单/大单/中单/小单拆分？若 API 暂缺，FundFlowBar 需要降级为总净流入 + 数据暂缺说明。
8. 市场风格中的“大盘/小盘”口径采用市值分层、指数成分还是固定宽基指数代理？组件可兼容，但 API 需确定口径。
9. API v0.2.1 中单位口径存在“业务字段命名 + 原始落库单位”的修正，是否所有模块都需要返回 `unit` 或 `displayText`？建议必须返回。
10. 浅色主题 P0 是否只要求 Token 可切换，还是要求 Showcase 同时提供浅色预览？建议 Token 支持，Showcase 深色优先。

---

## 14. v0.3 验收清单

| 验收项 | 是否满足 |
|---|---:|
| 组件能完整支撑市场总览 PRD | 是 |
| 组件不依赖固定 SideNav | 是 |
| 明确 TopMarketBar + Breadcrumb + ShortcutBar + 全宽内容区 | 是 |
| 红涨绿跌规则明确 | 是 |
| 状态设计覆盖 default/hover/active/selected/disabled/loading/empty/error | 是 |
| 字段映射到市场总览 API | 是 |
| 不把主观分析分数混入市场总览 | 是 |
| 能指导 HTML Showcase | 是 |
| 能指导 Codex 实现 | 是 |


---

## 15. HTML Review v1 → market-overview-v1.1 增量合并规范

> 本节为 v0.4 新增内容。它不替代前文 v0.3 已有组件规范，而是作为 market-overview-v1.1 的补充实现约束。  
> 合并原则：旧版已有组件说明继续有效；如本节对同一组件提出更具体规则，则以本节为 market-overview-v1.1 的落地准则。

### 0. 本轮实际读取的公共区文件

| 序号 | 公共区文件 | 读取到的版本 / 状态 |
|---:|---|---|
| 1 | `财势乾坤/项目总说明/财势乾坤行情软件项目总说明_v_0_2.md` | v0.2 / Review 草案 |
| 2 | `财势乾坤/产品文档/市场总览产品需求文档 v0.2.md` | v0.2 / Review 草案 |
| 3 | `财势乾坤/设计/02-market-overview-page-design.md` | v0.1 / market-overview-v1.html 基线 |
| 4 | `财势乾坤/设计/03-design-tokens.md` | v0.2.4 / market-overview-v1.1 Token 补充版 |
| 5 | `财势乾坤/设计/04-component-guidelines.md` | v0.3 / Draft，作为完整合并基线 |
| 6 | `财势乾坤/数据字典与API文档/market-overview-api-v0.4.md` | v0.4 / HTML Review v1 补字段修订稿 |
| 7 | `财势乾坤/数据字典与API文档/p0-data-dictionary-v0.4.md` | v0.4 / HTML Review v1 补字段修订稿 |
| 8 | `财势乾坤/review/市场总览html_review_v_1_总控解读与变更单.md` | HTML Review v1 / 目标 market-overview-v1.1.html |
| 9 | `财势乾坤/项目总说明/财势乾坤公共区使用规范_v_0_3.md` | v0.3 / Review 草案 |

#### 0.1 公共区规范执行说明

根据《财势乾坤公共区使用规范 v0.3》：

1. `财势乾坤/` 是项目协作主公共区，用于存放项目总说明、页面级 PRD、Design Token、组件规范、页面设计文档、API、Showcase、Review、Codex 提示词等。
2. `财势乾坤/设计/04-component-guidelines.md` 是组件库与交互组件方案。
3. 同一主题存在多个版本时，默认优先读取最高版本，并说明实际采用哪个版本。
4. Review 变更单是 UI 修改、API 修改、组件修改和 Codex 提示词修改的中间依据。
5. Codex 提示词只应在 PRD、页面设计、Token、组件、API、Showcase 基本稳定后生成。

本轮因此采用：

- Design Token：`03-design-tokens.md v0.2.4`
- API：`market-overview-api-v0.4.md`
- 数据字典：`p0-data-dictionary-v0.4.md`
- 组件基线：`04-component-guidelines.md v0.3`
- 变更单：`市场总览 HTML Review v1`

---

### 1. 修订边界与产品约束

#### 1.1 继续有效的市场总览基线

1. 页面正式名称是 **市场总览**。
2. 页面属于 **乾坤行情**，不是独立一级菜单。
3. 市场总览可以作为系统打开后的默认落地页，但导航归属固定为乾坤行情。
4. 桌面端不使用固定 SideNav，不预留大面积左侧导航占位。
5. 页面采用：
   - `TopMarketBar`
   - `GlobalSystemMenu`
   - `IndexTickerStrip`
   - `Breadcrumb`
   - `PageHeader`
   - `ShortcutBar / QuickEntryCard`
   - 全宽行情内容区
6. 只展示 A 股市场客观事实。
7. 不展示市场温度、市场情绪指数、资金面分数、风险指数作为首页核心结论。
8. 不输出买卖建议、仓位建议、明日预测、看多看空等主观结论。
9. 中国市场红涨绿跌：上涨 / 正变化 / 净流入 / 涨停为红；下跌 / 负变化 / 净流出 / 跌停为绿；平盘 / 零值 / 无变化为白色或灰白色。
10. 视觉风格保持专业、沉稳、高密度、有金融终端感，禁止廉价大屏风、霓虹风、低幼风、无意义渐变。

#### 1.2 v0.4 相对 v0.3 的核心变化

| 类型 | 变化 |
|---|---|
| 图表交互 | 历史趋势图从装饰线升级为有坐标轴、网格、Tooltip、crosshair、RangeSwitch 的可读图表。 |
| 模块说明 | 模块标题下说明文字收纳到 `HelpTooltip`。 |
| 历史范围 | 统一支持 `1个月 / 3个月`，由 `RangeSwitch` 控制。 |
| 成交额 | 增加 `IntradayTurnoverChart` 和历史成交额趋势。 |
| 市场风格 | 增加大盘、小盘、涨跌中位数三线历史趋势图；删除等权平均和说明性文字。 |
| 资金流 | 改为今日 / 昨日净流入双卡 + 历史资金流图；历史主线白色，0 轴居中。 |
| 涨跌停 | 统计、分布、历史柱图合并为“涨跌停统计与分布”大模块。 |
| 连板天梯 | 改为 `HorizontalLimitUpStreakLadder`，独占一行。 |
| 顶部栏 | 修复“系统设置”文字截断风险，必要时折叠系统菜单。 |
| 榜单 | 支持与资金流二等分布局，半宽表格仍需高密度可读。 |

---

### 2. 通用类型、状态与显示规则

#### 2.1 Direction

```ts
type Direction = 'UP' | 'DOWN' | 'FLAT' | 'UNKNOWN';
```

| 场景 | UP / 正值 | DOWN / 负值 | FLAT / 零值 | 备注 |
|---|---|---|---|---|
| 指数涨跌 | 红色 | 绿色 | 白色或灰白色 | 点位、涨跌额、涨跌幅一致 |
| 个股涨跌 | 红色 | 绿色 | 白色或灰白色 | 股票列表、榜单、Tooltip 一致 |
| 资金净流入 | 红色 | 绿色 | 白色或灰白色 | 正值净流入，负值净流出 |
| 涨跌停 | 涨停红色 | 跌停绿色 | 不适用 | 炸板用警示/中性 |
| MoneyFlowHistoryChart 主线 | 白色 | 白色 | 白色 | Tooltip 再按正负红绿 |
| 系统错误 | 不使用行情红 | 不使用行情绿 | 使用系统错误 Token | 避免混淆 |

#### 2.2 NumericDisplay

```ts
interface NumericDisplayProps {
  value: number | null;
  unit?: string;
  displayText?: string;
  precision?: number;
  showSign?: boolean;
  direction?: Direction;
  placeholder?: string;
}
```

规则：

1. API 若返回 `displayText`，组件优先显示 `displayText`。
2. API 若返回 `unit`，前端按 `unit` 格式化，不擅自改写业务口径。
3. 百分比显示为 `+1.26% / -0.82%`。
4. 行情数字使用等宽数字：`font-variant-numeric: tabular-nums;`。
5. 空值显示 `--`，不能显示为 `0`。
6. 平盘关键数字在深色主题下使用白色或灰白色，不得使用红/绿。

#### 2.3 组件状态

```ts
type ComponentState =
  | 'default'
  | 'hover'
  | 'active'
  | 'selected'
  | 'disabled'
  | 'loading'
  | 'empty'
  | 'error';
```

| 状态 | 视觉规则 | 交互规则 |
|---|---|---|
| default | 正常背景、正常文字、弱边框 | 按业务规则可点击 |
| hover | 背景轻微提亮，边框增强 | 不改变数据，不触发跳转 |
| active | 鼠标按下或键盘确认时压暗 | 可触发跳转、切换、刷新 |
| selected | 当前路由、当前 Tab、当前区间高亮 | 作为当前上下文 |
| disabled | 透明度降低、文字降级 | 不触发动作，Tooltip 说明原因 |
| loading | 骨架屏、图表网格占位、表格骨架行 | 保留布局，不整页闪烁 |
| empty | 说明无数据原因 | 可提供刷新、查看最近交易日、调整筛选 |
| error | 异常边框、异常文案、重试按钮 | 单模块失败不拖垮整页 |

---

### 3. Token 依赖

#### 3.1 基础 Token

| Token | 用途 |
|---|---|
| `--cs-color-bg-page` | 页面背景 |
| `--cs-color-bg-top-market-bar` | TopMarketBar 背景 |
| `--cs-color-surface-panel` | Panel 背景 |
| `--cs-color-surface-card` | 卡片背景 |
| `--cs-color-surface-card-hover` | 卡片 hover |
| `--cs-color-border-subtle` | 弱分割线 |
| `--cs-color-border-strong` | selected / active 边框 |
| `--cs-color-text-primary` | 主文字 |
| `--cs-color-text-secondary` | 次级文字 |
| `--cs-color-text-muted` | 弱文字 |
| `--cs-color-market-up` | 上涨 / 净流入 / 涨停 |
| `--cs-color-market-down` | 下跌 / 净流出 / 跌停 |
| `--cs-color-market-flat-strong` | 平盘关键数字 |
| `--cs-color-market-flat-soft` | 平盘弱标签 |
| `--cs-font-family-number` | 行情数字 |
| `--cs-layout-top-market-bar-height` | 顶部栏高度 |
| `--cs-layout-page-header-height` | PageHeader 高度 |
| `--cs-shadow-dropdown` | 下拉菜单 |
| `--cs-z-popover` | Tooltip / Popover 层级 |

#### 3.2 v0.2.4 新增 Token 依赖

| 组件 | 必须使用的 Token |
|---|---|
| HelpTooltip | `--cs-color-help-icon`、`--cs-color-help-icon-hover`、`--cs-color-help-tooltip-bg`、`--cs-color-help-tooltip-border`、`--cs-color-help-tooltip-text` |
| RangeSwitch | `--cs-color-range-switch-bg`、`--cs-color-range-switch-border`、`--cs-color-range-switch-item-selected-bg`、`--cs-color-range-switch-item-selected-text` |
| HistoryTrendChart | `--cs-color-chart-axis-line`、`--cs-color-chart-grid-primary`、`--cs-color-chart-crosshair-line`、`--cs-color-chart-tooltip-bg` |
| MarketStyleTrendChart | `--cs-color-trend-style-large-cap`、`--cs-color-trend-style-small-cap`、`--cs-color-trend-style-median` |
| IntradayTurnoverChart | `--cs-color-trend-turnover-intraday` |
| MoneyFlowHistoryChart | `--cs-color-trend-moneyflow-main`、`--cs-color-chart-zero-line` |
| LimitUpDownHistoryBarChart | `--cs-color-limitup-bar`、`--cs-color-limitdown-bar`、`--cs-color-limit-bar-group-bg` |
| HorizontalLimitUpStreakLadder | `--cs-color-ladder-level-bg`、`--cs-color-ladder-level-header-bg`、`--cs-color-ladder-stock-card-bg`、`--cs-color-ladder-stock-card-hover-bg` |

---

### 4. API 对象与字段总约束

#### 4.1 市场总览聚合接口

```http
GET /api/market/home-overview
```

组件以该聚合接口为首屏数据主来源，模块接口用于局部刷新和 3个月历史数据懒加载。

```ts
interface MarketOverviewData {
  tradingDay: TradingDay;
  dataStatus: DataSourceStatus[];
  topMarketBar: TopMarketBarData;
  breadcrumb: BreadcrumbItem[];
  quickEntries: QuickEntry[];
  marketSummary: MarketObjectiveSummary;
  indices: IndexSnapshot[];
  breadth: MarketBreadth;
  style: MarketStyle;
  turnover: TurnoverSummary;
  moneyFlow: MoneyFlowSummary;
  limitUp: LimitUpSummary;
  streakLadder: LimitUpStreakLadder;
  sectorOverview: SectorOverview;
  leaderboards: LeaderboardGroups;
}
```

#### 4.2 v0.4 关键新增字段

```ts
interface MarketBreadth {
  upCount: number;
  downCount: number;
  flatCount: number;
  redRate: number;
  medianChangePct: number;
  distribution: BreadthDistributionBucket[];
  historyPoints: HistoricalBreadthPoint[];
  rangeType: '1m' | '3m';
}

interface MarketStyle {
  largeCapIndexCode: string;
  smallCapIndexCode: string;
  largeCapChangePct: number;
  smallCapChangePct: number;
  medianChangePct: number;
  styleLeader: 'LARGE_CAP' | 'SMALL_CAP' | 'BALANCED';
  historyPoints: MarketStyleHistoryPoint[];
  rangeType: '1m' | '3m';
}

interface TurnoverSummary {
  totalAmount: number;
  prevTotalAmount: number;
  amountChange: number;
  amountChangePct: number;
  amount20dMedian?: number;
  amountRatio20dMedian?: number;
  intradayPoints: IntradayTurnoverPoint[];
  historyPoints: HistoricalTurnoverPoint[];
  unit?: string;
  rangeType: '1m' | '3m';
}

interface MoneyFlowSummary {
  mainNetInflow: number;
  prevMainNetInflow?: number;
  superLargeAmount?: number;
  largeAmount?: number;
  mediumAmount?: number;
  smallAmount?: number;
  historyPoints: HistoricalMoneyFlowPoint[];
  unit?: string;
  rangeType: '1m' | '3m';
}

interface LimitUpSummary {
  limitUpCount: number;
  limitDownCount: number;
  failedLimitUpCount: number;
  touchedLimitUpCount?: number;
  sealRate?: number;
  highestStreak: number;
  distribution: LimitUpDistribution;
  historyPoints: HistoricalLimitUpDownPoint[];
  dataScopeNote?: string;
  rangeType: '1m' | '3m';
}

interface LimitUpStreakLadder {
  tradeDate: string;
  maxStreak: number;
  levels: LimitUpStreakLevel[];
}
```

---

### 5. market-overview-v1.1 组件清单

| 组件名称 | 组件用途 | 使用页面 | 是否市场总览 P0 必需 | 输入字段 / Props | 与 API 字段的映射 | 视觉结构 | 交互行为 | 涨跌色规则 | 与 Design Token 的关系 | 备注 |
|---|---|---|---|---|---|---|---|---|---|---|
| TopMarketBar | 顶部全局栏，承载品牌、系统入口、指数条、时间、开闭市状态、数据状态、用户入口 | 市场总览；全站高密度行情页 | 是 | brandName, activeSystemKey, globalEntries, indexTickers, sessionStatus, serverTime, dataStatus, userShortcutStatus, collapseMode, callbacks | topMarketBar.*, tradingDay.sessionStatus, dataStatus[] | 48–56px 横向栏；左品牌、中系统入口/指数条、右时间/状态/用户 | 系统入口 hover/click；指数点击下钻；数据状态弹出说明 | 指数红涨绿跌，平盘白/灰；系统状态不用行情红绿 | top-market-bar, market-up/down/flat, number font, dropdown shadow | v1.1 必须修复“系统设置”截断；必要时折叠非当前系统 |
| GlobalSystemMenu | 顶部系统入口折叠菜单 | TopMarketBar | 是 | entries, activeKey, placement, trigger, onSelect | topMarketBar.globalEntries[] | 深色下拉浮层，当前系统金色强调 | hover/click 展开，点击跳转，disabled 展示原因 | 不用行情红绿 | surface-elevated, shadow-dropdown, z-dropdown, brand | 不等同 SideNav，不占内容区 |
| IndexTickerStrip | 顶部主要指数行情条 | TopMarketBar | 是 | items, maxVisible, scrollable, pauseOnHover, onTickerClick | topMarketBar.indexTickers[] | 紧凑横向 ticker，名称+点位+涨跌幅 | hover 暂停滚动，点击指数详情 | 点位/涨跌幅红涨绿跌，平盘白/灰 | market-up/down/flat, number font | 与 IndexCard 色彩规则一致 |
| Breadcrumb | 页面层级表达 | 市场总览 Header | 是 | items, separator, onItemClick, onItemHover | breadcrumb[] | 单行：财势乾坤 / 乾坤行情 / 市场总览 | 财势乾坤回默认页；乾坤行情展开同系统页面；市场总览当前态 | 无行情色 | text-muted, brand, space | 替代固定 SideNav 的层级表达 |
| PageHeader | 页面标题、市场、交易日、更新时间、刷新 | 市场总览 Header | 是 | title, market, tradeDate, sessionStatus, updateTime, refreshMode, onRefresh | tradingDay, dataStatus[], serverTime | 56px 左标题右状态/刷新 | 手动刷新；hover 数据时间显示来源 | 无行情色 | page-header-height, text-primary/secondary | 不是 Hero Banner |
| MarketStatusPill | 开闭市状态标签 | TopMarketBar, PageHeader | 是 | sessionStatus, label, tooltip | tradingDay.sessionStatus | 小圆角 pill | hover 显示交易时段 | 不用行情红绿 | status-info/warning, radius-pill | 已收盘不等于异常 |
| DataStatusBadge | 数据状态标记 | TopMarketBar, PageHeader, Panel | 是 | status, latestDataTime, completenessPct, sourceRefs, onClick | dataStatus[] or module.dataStatus | 小 badge + tooltip | hover 简述；click 数据源详情 | 不用行情红绿 | status colors, help tooltip | PARTIAL 不拖垮整页 |
| ShortcutBar | 页面内快捷入口容器 | 市场总览 | 是 | entries, layout, onEntryClick | quickEntries[] | 6个横向紧凑入口 | hover 提亮，点击跳转，disabled 说明原因 | 待处理数用品牌/中性色，不用行情红绿 | surface-card, brand | 不展示温度/情绪/资金面/风险分数 |
| QuickEntryCard | 单个快捷入口卡 | ShortcutBar | 是 | key,title,description,route,enabled,pendingCount,hasUpdate,badge | quickEntries[] | 标题+短说明+徽标 | 点击跳转 | 不展示主观评分 | card hover, brand | 不做大面积入口卡片墙 |
| QuickEntryBadge | 入口待处理/更新徽标 | QuickEntryCard | 是 | count,dot,variant,label | pendingCount, hasUpdate | 小数字或小圆点 | 随卡片点击 | 不表示涨跌 | brand/status-info | 用户设置一般不显示数量 |
| Panel | 标准模块容器 | 所有模块 | 是 | title, subtitle, helpText, extra, children, state | 模块数据 | Header + Body + optional Footer | 内部元素交互，不整体跳转 | 由内部组件决定 | surface-panel, border, radius | 不做发光大屏风 |
| SectionHeader | 模块标题、HelpTooltip、RangeSwitch、操作区 | 所有 Panel | 是 | title, helpText, helpTitle, actions, rangeSwitchProps | 无固定 | 左标题+问号；右工具区 | HelpTooltip hover/click；RangeSwitch 切换 | 无行情色 | text-primary, help, range-switch | v1.1 模块说明收纳于 HelpTooltip |
| HelpTooltip | 标题旁圆圈问号说明 | 所有 Panel Header | v1.1 必需 | title, content, placement, trigger, maxWidth, disabled, ariaLabel | 静态说明；dataScopeNote；sourceRefs；unit；dataStatus.message | 14–16px 圆圈问号 + 深色浮层 | 桌面 hover/focus；可 click pin；Esc 关闭；小屏用 Popover/底部浮层 | 不输出红绿结论 | help icon/tooltip tokens, z-popover | 最大宽度 280–360px |
| RangeSwitch | 历史范围切换 | 历史图表 Header | v1.1 必需 | options, selectedValue, disabledValues, size, loading, onChange | historyRange/rangeType=1m\|3m | 小型 segmented control | 点击切换，局部刷新，保留旧图直到新数据回来 | 选中用品牌金，不用红绿 | range-switch tokens | 默认 1个月，3个月可按需请求 |
| TabPanel | 榜单/板块切换 | RankingTable, SectorRankList | 是 | tabs, activeKey, onChange | leaderboards groups, sectorOverview groups | 高密度横向 Tab | 点击/键盘切换 | Tab 不用行情红绿 | brand, border-subtle | 半宽布局下高度必须克制 |
| IndexCard | 主要指数卡 | 主要指数区 | 是 | indexCode,indexName,last,prevClose,change,changePct,amount,direction,trendPoints,unit,onClick | indices[] | 名称代码、点位、涨跌额/幅、成交额、小趋势 | hover 提亮，点击指数详情 | 点位/涨跌额/涨跌幅/趋势线统一红涨绿跌，平盘白/灰 | market-up/down/flat, number font, card | v1.1 强制修复颜色一致性 |
| MetricCard | 单项指标卡 | 广度/成交/资金/涨跌停 | 是 | label,value,unit,changeValue,changeDirection,description,helpText | breadth.*, turnover.*, moneyFlow.*, limitUp.* | 标签+大数字+单位+变化值 | hover 说明，可点击下钻 | 按业务语义 | number font, market colors | 不要做巨大空洞卡 |
| MetricMiniCardGroup | 小指标卡组 | 成交额、资金、涨跌停 | v1.1 必需 | items, columns, density, loading, emptyText, onItemClick | turnover.*, moneyFlow.*, limitUp.* | 一行4卡/2卡，高密度小卡 | hover, click, HelpTooltip | 成交额中性；变化值正红负绿；资金正红负绿；涨停红跌停绿 | surface-card, number, market colors | 半宽默认2卡一行，宽容器4卡一行 |
| ChangeBadge | 涨跌标签 | 指数、榜单、板块、资金 | 是 | value,direction,unit,showSign,variant | change/changePct/direction | 文本或小 badge | 无独立交互 | UP红 DOWN绿 FLAT白/灰 | market-up/down/flat | 不要用框架 success 表示上涨 |
| QuoteTicker | 紧凑行情项 | IndexTickerStrip | 是 | code,name,last,changePct,direction | topMarketBar.indexTickers[], indices[] | 名称+最新值+涨跌幅 | hover/click | 红涨绿跌 | number, market colors | 用于顶部高密度展示 |
| MiniTrendChart | 微型趋势线 | IndexCard/QuoteTicker | 是 | points,direction,height | indices[].trendPoints | 无坐标小折线 | 无 | 按 direction | market colors | 正式历史图必须用 HistoryTrendChart |
| DistributionChart | 当日涨跌幅分布 | MarketBreadthPanel | 是 | buckets,orientation,onBucketClick | breadth.distribution[] | 区间分布条/柱形 | hover 数量占比，click 下钻 | 涨幅红跌幅绿平盘灰 | market colors, chart grid | 只表达当日分布 |
| MarketBreadthPanel | 市场广度面板 | 第一行三等分 | 是 | breadth,rangeType,onRangeChange,onBucketClick | breadth.* | MetricMiniCardGroup + DistributionChart + HistoryTrendChart | RangeSwitch, hover tooltip, click bucket | 上涨红下跌绿平盘灰；历史仅上涨/下跌两线 | trend-breadth-up/down | v1.1 去掉平盘历史线 |
| HistoryTrendChart | 通用历史趋势图 | 广度历史、历史成交额 | v1.1 必需 | data,xKey,series,rangeType,rangeOptions,showLegend,showCrosshair,height,formatters,loading,onRangeChange | breadth.historyPoints[], turnover.historyPoints[] | X轴日期、Y轴数值、图例、网格、crosshair、tooltip | RangeSwitch；hover 定位；可点下钻 | 由 series 决定；广度上涨红下跌绿 | chart axis/grid/crosshair/tooltip, trend tokens | 禁止无坐标装饰线 |
| MarketStylePanel | 市场风格当前值与历史 | 第一行三等分 | 是 | style,rangeType,onRangeChange | style.* | MetricMiniCardGroup + MarketStyleTrendChart | RangeSwitch + tooltip | 当前值正红负绿；趋势线按 series token | trend-style tokens | v1.1 删除等权平均和说明文字 |
| MarketStyleTrendChart | 市场风格三线趋势 | MarketStylePanel | v1.1 必需 | data,rangeType,onRangeChange,loading | style.historyPoints[] | 大盘/小盘/中位数三线；X日期；Y百分比 | hover crosshair+tooltip | 线色固定；tooltip 正红负绿 | trend-style-large/small/median | 百分比保留2位 |
| TurnoverSummaryCard | 成交额总览 | 第一行三等分 | 是 | turnover,rangeType,onRangeChange | turnover.* | 4小卡 + IntradayTurnoverChart + HistoryTrendChart | hover tooltip, range switch | 总额中性，变化值正红负绿 | turnover trend tokens | v1.1 必须有今日/昨日对比 |
| IntradayTurnoverChart | 当日累计成交额趋势 | TurnoverSummaryCard | v1.1 必需 | data,timeKey,valueKey,unit,marketSessionMarks,loading | turnover.intradayPoints[] | 横轴时间，纵轴累计成交额，标注09:30/11:30/15:00 | hover 时间和累计成交额 | 曲线中性/品牌金，不用红绿 | trend-turnover-intraday, chart tokens | 点不足时空态，不伪造曲线 |
| FundFlowBar | 分单结构条 | MoneyFlowSummaryPanel | 是 | segments,totalValue,unit,showLegend | moneyFlow.superLargeAmount/largeAmount/mediumAmount/smallAmount | 横向分段条 | hover segment tooltip | 净流入红，净流出绿 | market colors | 只展示事实，不算资金面分数 |
| MoneyFlowSummaryPanel | 大盘资金流向 | 第二行二等分左侧 | 是 | moneyFlow,rangeType,onRangeChange | moneyFlow.* | 2小卡 + FundFlowBar + MoneyFlowHistoryChart | RangeSwitch, hover/click | 今日/昨日正红负绿；历史主线白，tooltip正红负绿 | moneyflow-main, zero-line | historyPoints 为空时展示卡片和分单 |
| MoneyFlowHistoryChart | 资金历史趋势 | MoneyFlowSummaryPanel | v1.1 必需 | data,rangeType,onRangeChange,unit,loading | moneyFlow.historyPoints[] | 白色主线，0轴居中，X日期，Y金额 | hover crosshair/tooltip | 主线白；tooltip 正红负绿 | trend-moneyflow-main, zero-line | 单位建议亿元，按 API unit 格式化 |
| LimitUpSummaryCard | 涨跌停核心统计 | 涨跌停统计与分布大模块 | 是 | summary,onMetricClick | limitUp.* | MetricMiniCardGroup | 点击涨停/跌停/炸板下钻 | 涨停红跌停绿，炸板警示/中性 | limitup/down tokens | v1.1 与分布面板和历史柱图合并 |
| LimitUpDistributionPanel | 图形化涨跌停分布 | 涨跌停统计与分布大模块 | v1.1 必需 | distribution,layout,onItemClick,loading | limitUp.distribution or limitUpDistribution | 分布条/板块块/矩阵，不用普通列表 | hover 数量占比，click 类别/板块下钻 | 涨停红跌停绿，炸板警示/中性 | market colors, limit group bg | 替代普通列表 |
| LimitUpDownHistoryBarChart | 历史涨跌停组合柱图 | 涨跌停统计与分布大模块 | v1.1 必需 | data,rangeType,onRangeChange,loading | limitUp.historyPoints[] | 日期柱组：涨停/跌停/炸板 | hover tooltip, RangeSwitch | 涨停红，跌停绿，炸板警示/中性 | limitup-bar, limitdown-bar | 必须有坐标和tooltip |
| LimitUpStreakLadder | 连板天梯通用名 | 市场总览/后续详情 | 是 | ladder,variant,onStockClick,onSectorClick | streakLadder | 市场总览使用 horizontal 变体 | 点击股票/板块下钻 | 涨幅红，标签中性 | ladder tokens | 保留兼容名 |
| HorizontalLimitUpStreakLadder | 横向连板天梯 | 第四行独占一行 | v1.1 必需 | levels,maxVisibleStocksPerLevel,scrollMode,onStockClick,onSectorClick | streakLadder.levels[].stockCount/stocks[] | 首板/二板/三板/四板/五板+横向层级，内含股票卡 | 层级/卡片 hover；点击下钻；空间不足横向滚动 | 涨幅红，板块标签中性 | ladder level/card tokens | 必须独占一行 |
| RankingTable | 榜单速览表格 | 第二行二等分右侧 | 是 | columns,rows,rankType,density,onRowClick,onSortChange | leaderboards.*[] | TabPanel + 高密度半宽表格 | Tab切换，行hover，点击个股 | 股价/涨跌幅红涨绿跌 | table row hover, density, number | 半宽时隐藏次要列 |
| StockTable | 个股表格基础 | RankingTable 内部 | 是 | rows,columns,density,onRowClick | leaderboards.*[] | 高密度行 | hover/click | 股价和涨跌幅红涨绿跌 | table tokens | 行高34-40px |
| SectorTable | 板块表格 | 板块速览 | 是 | items,sectorType,rankType,onSectorClick | sectorOverview.*[] | 多列紧凑表 | 点击板块/领涨股下钻 | 板块涨跌幅红绿，资金正负红绿 | table, market colors | 板块速览独占一行 |
| SectorRankList | 板块Top N列表 | 板块速览子区 | 是 | title,items,rankType,onItemClick | sectorOverview.*[] | 标题+Top N行 | hover/click | 同 SectorTable | density row, market colors | 不是完整板块详情 |
| HeatMap | 板块/个股热力图 | 市场总览入口/板块页完整 | 入口必需，完整图后置 | items,sizeKey,colorKey,onItemClick | sectorOverview.heatmapEntry / heatMap.items[] | 矩形热力图或入口卡 | hover tooltip, click 下钻 | 涨红跌绿，深浅表达强度 | market colors | 市场总览不展示大面积热力图 |
| SortableHeader | 表头排序 | RankingTable/SectorTable/StockTable | 是 | label,sortKey,sortOrder,onSort | 排序请求参数或本地排序 | 表头文字+箭头 | 点击切换排序 | 不用红绿 | text-secondary, brand | 首页Top N可禁用 |
| LoadingSkeleton | 加载占位 | 所有模块 | 是 | variant,rows,height | 请求 pending | 骨架卡/行/图表网格 | 无 | 不用红绿 | surface tokens | 刷新保留旧数据 |
| EmptyState | 空态 | 所有模块 | 是 | title,description,actionText,onAction | 空数组/404001/dataStatus=EMPTY | 小型空态块 | 可刷新/切最近交易日 | 不用红绿 | text-muted | 说明原因，不只写暂无数据 |
| ErrorState | 错误态 | 所有模块 | 是 | code,message,traceId,retryText,onRetry | code!=0, 500001,503001 | 小错误块保留模块尺寸 | 重试/复制traceId | 系统错误不用行情红 | status-danger | 单模块失败不拖垮整页 |
| DataDelayState | 延迟态 | 资金/日内成交/涨跌停/榜单 | 是 | delaySeconds,latestDataTime,message,sourceRefs | dataStatus=DELAYED/PARTIAL | 小提示条或 badge tooltip | hover查看来源 | 不用行情红绿 | status-warning | 允许使用最近缓存 |
| PermissionState | 无权限/未登录 | 个人入口/用户模块 | 是 | title,description,loginText,onLogin | 401001/403001 | 小权限提示 | 点击登录/授权 | 不用红绿 | status-info | 不影响基础行情 |

---

### 6. 重点组件实现规格

#### 6.1 TopMarketBar v1.1 覆盖规则

```ts
interface TopMarketBarProps {
  brandName: string;
  activeSystemKey: string;
  globalEntries: GlobalSystemEntry[];
  indexTickers: IndexTickerItem[];
  sessionStatus: 'PRE_OPEN' | 'OPEN' | 'NOON_BREAK' | 'CLOSED' | 'NON_TRADING_DAY';
  serverTime?: string;
  dataStatus: DataSourceStatus[];
  userShortcutStatus?: UserShortcutStatus;
  collapseMode?: 'auto' | 'never' | 'always';
  onSystemClick?: (entry: GlobalSystemEntry) => void;
  onTickerClick?: (ticker: IndexTickerItem) => void;
  onDataStatusClick?: () => void;
  onUserMenuClick?: () => void;
}
```

实现要求：

1. “系统设置”必须完整展示，不允许被截断。
2. 若横向空间不足，优先折叠非当前系统入口到 `GlobalSystemMenu`。
3. 不得新增固定 SideNav。
4. 当前系统 `乾坤行情` 必须 selected。
5. 指数条可以滚动，但 hover 时暂停滚动。
6. 点击指数进入指数详情页，携带 `indexCode`、`tradeDate`。
7. 数据状态点击展示数据源状态，不影响市场总览主内容。

#### 6.2 Breadcrumb 固定表达

固定显示：

```text
财势乾坤 / 乾坤行情 / 市场总览
```

交互规则：

1. “财势乾坤”：点击返回默认落地页。
2. “乾坤行情”：点击或 hover 展开乾坤行情页面列表。
3. “市场总览”：当前态，默认不可跳转，也可触发当前页刷新但不推荐。
4. Breadcrumb 高度要克制，不替代导航栏。
5. 不引入 SideNav 来补充层级。

#### 6.3 ShortcutBar / QuickEntryCard

必须包含：

1. 市场温度与情绪；
2. 机会雷达；
3. 我的自选；
4. 我的持仓；
5. 提醒中心；
6. 用户设置。

允许展示：

- 待处理数量；
- 未读提醒数；
- 是否有更新；
- 是否 enabled。

不允许展示：

```text
市场温度 82 分
情绪指数进入亢奋区
资金面分数 76
风险指数提示减仓
```

QuickEntryCard 只承担跳转，不承担主观分析表达。

#### 6.4 IndexCard

必须展示：

- 指数名称；
- 指数代码；
- 最新点位；
- 涨跌额；
- 涨跌幅；
- 成交额；
- MiniTrendChart；
- 更新时间或共享页面更新时间。

点击进入指数详情页。点位、涨跌额、涨跌幅必须统一方向色：

```text
UP   -> 红色
DOWN -> 绿色
FLAT -> 白色或灰白色
```

TopMarketBar 内的 IndexTickerStrip 必须完全遵守同一规则。

#### 6.5 HelpTooltip

```ts
interface HelpTooltipProps {
  title?: string;
  content: string | React.ReactNode;
  placement?: 'top' | 'right' | 'bottom' | 'left' | 'auto';
  trigger?: 'hover' | 'click' | 'focus' | 'hover-click';
  maxWidth?: number;
  disabled?: boolean;
  ariaLabel?: string;
}
```

实现要求：

1. 用于模块标题旁圆圈问号。
2. 最大宽度默认 320px，允许 280–360px。
3. 桌面默认 hover/focus；可 click pin。
4. 小屏使用居中 Popover 或底部浮层。
5. 不遮挡 RangeSwitch 和关键数字。
6. 内容应短，不承载长篇指标字典。
7. 不输出买卖建议和主观结论。

#### 6.6 RangeSwitch

```ts
interface RangeOption {
  label: string;       // 1个月 / 3个月
  value: '1m' | '3m';
  disabled?: boolean;
}

interface RangeSwitchProps {
  options: RangeOption[];
  selectedValue: '1m' | '3m';
  disabledValues?: Array<'1m' | '3m'>;
  size?: 'xs' | 'sm';
  loading?: boolean;
  onChange: (value: '1m' | '3m') => void;
}
```

联动规则：

1. 默认 `1m`。
2. 切换 `3m` 时，模块局部刷新。
3. 请求中保留旧图并显示局部 loading。
4. 请求失败保留旧图并显示 ErrorState。
5. 空数据展示图表空态，不隐藏 Panel。
6. 选中态使用品牌金，不使用红绿。

#### 6.7 HistoryTrendChart

```ts
interface ChartPoint {
  x?: string;
  tradeDate?: string;
  [key: string]: number | string | null | undefined;
}

interface ChartSeries {
  key: string;
  name: string;
  type?: 'line' | 'bar' | 'area';
  colorToken: string;
  valueFormatter?: (value: number | null) => string;
}

interface HistoryTrendChartProps {
  data: ChartPoint[];
  xKey: string;
  series: ChartSeries[];
  rangeType: '1m' | '3m';
  rangeOptions?: RangeOption[];
  showLegend?: boolean;
  showCrosshair?: boolean;
  height?: number;
  yAxisFormatter?: (value: number) => string;
  xAxisFormatter?: (value: string) => string;
  tooltipFormatter?: (point: ChartPoint) => React.ReactNode;
  loading?: boolean;
  emptyText?: string;
  onRangeChange?: (value: '1m' | '3m') => void;
  onPointClick?: (point: ChartPoint) => void;
}
```

适用：

- `breadth.historyPoints[]`：上涨 / 下跌家数趋势；
- `turnover.historyPoints[]`：历史成交额趋势；
- 后续其他历史趋势。

必须具备：

1. X 轴；
2. Y 轴；
3. series；
4. legend；
5. RangeSwitch；
6. crosshair；
7. tooltip；
8. empty state；
9. loading state；
10. 坐标数值格式化；
11. 系列色规则。

#### 6.8 IntradayTurnoverChart

```ts
interface IntradayTurnoverPoint {
  time: string; // HH:mm
  cumulativeAmount: number | null;
  unit?: string;
}

interface IntradayTurnoverChartProps {
  data: IntradayTurnoverPoint[];
  unit?: string;
  loading?: boolean;
  emptyText?: string;
  yAxisFormatter?: (value: number) => string;
}
```

要求：

1. 横轴为交易时间。
2. 至少标注 `09:30`、`11:30`、`15:00`。
3. 纵轴为累计成交额。
4. Tooltip 显示时间和累计成交额。
5. 数据点不足时：
   - 0 点：显示“暂无日内成交额数据”；
   - 1 点：显示单点，不连线；
   - 2 点以上：正常连线。
6. 曲线用中性 / 品牌金，不用红绿暗示涨跌。

#### 6.9 MarketStyleTrendChart

```ts
interface MarketStyleHistoryPoint {
  tradeDate: string;
  largeCapChangePct: number | null;
  smallCapChangePct: number | null;
  medianChangePct: number | null;
  rangeType?: '1m' | '3m';
}
```

三条线：

1. 大盘平均涨跌幅；
2. 小盘平均涨跌幅；
3. 涨跌中位数。

要求：

- 百分比格式；
- X 轴日期；
- 1个月/3个月切换；
- crosshair；
- tooltip；
- Tooltip 内正红负绿、零值灰白；
- 不展示等权平均和说明性文字。

#### 6.10 MoneyFlowHistoryChart

```ts
interface HistoricalMoneyFlowPoint {
  tradeDate: string;
  mainNetInflow: number | null;
  unit?: string;
  rangeType?: '1m' | '3m';
}
```

要求：

1. 主趋势线白色。
2. Y 轴 0 值居中。
3. 正值为净流入。
4. 负值为净流出。
5. Tooltip 正数红色，负数绿色。
6. 单位建议亿元；实际按 API `unit` 格式化。
7. 支持 1个月/3个月切换。

#### 6.11 LimitUpDownHistoryBarChart

```ts
interface HistoricalLimitUpDownPoint {
  tradeDate: string;
  limitUpCount: number | null;
  limitDownCount: number | null;
  failedLimitUpCount?: number | null;
  rangeType?: '1m' | '3m';
}
```

要求：

1. 横轴日期。
2. 纵轴数量。
3. 涨停红色。
4. 跌停绿色。
5. 同一日期柱组中同时展示涨停 / 跌停。
6. Tooltip 显示日期、涨停数、跌停数、炸板数。
7. 支持 1个月/3个月切换。

#### 6.12 LimitUpDistributionPanel

```ts
interface LimitUpDistribution {
  limitUpSectors?: LimitUpDistributionItem[];
  limitDownSectors?: LimitUpDistributionItem[];
  failedLimitUpSectors?: LimitUpDistributionItem[];
  streakHeight?: LimitUpDistributionItem[];
}

interface LimitUpDistributionItem {
  key: string;
  label: string;
  count: number;
  rate?: number;
  direction?: Direction;
  routeParams?: Record<string, string | number>;
}

interface LimitUpDistributionPanelProps {
  distribution: LimitUpDistribution;
  layout?: 'bars' | 'blocks' | 'matrix' | 'compact';
  loading?: boolean;
  emptyText?: string;
  onItemClick?: (item: LimitUpDistributionItem) => void;
}
```

要求：

1. 不使用普通列表。
2. 可使用分布条、板块分布块、矩阵或紧凑图形。
3. 需要和涨跌停统计合并成一个大模块。
4. 支持点击板块或类别下钻。
5. 涨停红，跌停绿，炸板用警示/中性。

#### 6.13 HorizontalLimitUpStreakLadder

```ts
interface HorizontalLimitUpStreakLadderProps {
  levels: LimitUpStreakLevel[];
  maxVisibleStocksPerLevel?: number;
  scrollMode?: 'x-scroll' | 'wrap';
  loading?: boolean;
  emptyText?: string;
  onStockClick?: (stock: LimitUpStreakStock) => void;
  onSectorClick?: (sectorName: string, stock: LimitUpStreakStock) => void;
}

interface LimitUpStreakLevel {
  levelKey: 'FIRST' | 'SECOND' | 'THIRD' | 'FOURTH' | 'FIFTH_PLUS';
  levelLabel: string;
  streak: number;
  stockCount: number;
  stocks: LimitUpStreakStock[];
}

interface LimitUpStreakStock {
  stockCode: string;
  stockName: string;
  sectorName?: string;
  latestPrice?: number | null;
  changePct?: number | null;
  openTimes?: number | null;
  sealAmount?: number | null;
  firstLimitTime?: string | null;
  direction?: Direction;
}
```

要求：

1. 独占一行。
2. 横向层级：首板、二板、三板、四板、五板及以上。
3. 每个层级显示股票数量。
4. 每层内部展示股票卡片。
5. 股票卡片字段：
   - 股票名称；
   - 股票代码；
   - 所属板块；
   - 最新价；
   - 涨跌幅；
   - 开板次数；
   - 封单金额；
   - 首次封板时间。
6. 横向空间不足：
   - 优先模块内部横向滚动；
   - 可换行，但层级顺序不能乱；
   - 单层股票过多时显示“更多 N 只”。
7. hover 股票卡片展示补充 Tooltip。
8. 点击股票进入个股详情。
9. 点击板块进入板块与榜单行情页。

---

### 7. market-overview-v1.1 页面组件组合建议

```text
MarketOverviewPage
├── TopMarketBar
├── Breadcrumb
├── PageHeader
├── ShortcutBar
├── MarketObjectiveSummaryPanel
├── IndexGrid
│   └── IndexCard[]
├── Row: 3 columns
│   ├── MarketBreadthPanel
│   ├── MarketStylePanel
│   └── TurnoverSummaryCard
├── Row: 2 columns
│   ├── MoneyFlowSummaryPanel
│   └── RankingTable
├── LimitUpPanel
│   ├── LimitUpSummaryCard
│   ├── LimitUpDistributionPanel
│   └── LimitUpDownHistoryBarChart
├── HorizontalLimitUpStreakLadder
└── SectorOverviewPanel
```

---

### 8. API 字段映射补充

| 数据需求 | 推荐 API 字段 |
|---|---|
| 历史上涨 / 下跌家数序列 | `breadth.historyPoints[].upCount`、`breadth.historyPoints[].downCount` |
| 市场风格历史序列 | `style.historyPoints[].largeCapChangePct`、`smallCapChangePct`、`medianChangePct` |
| 日内累计成交额序列 | `turnover.intradayPoints[].time`、`turnover.intradayPoints[].cumulativeAmount` |
| 历史成交额序列 | `turnover.historyPoints[].tradeDate`、`turnover.historyPoints[].turnoverAmount` |
| 今日大盘资金净流入 | `moneyFlow.mainNetInflow` |
| 昨日大盘资金净流入 | `moneyFlow.prevMainNetInflow` |
| 历史大盘资金净流入序列 | `moneyFlow.historyPoints[].mainNetInflow` |
| 历史涨停 / 跌停数量序列 | `limitUp.historyPoints[].limitUpCount`、`limitUp.historyPoints[].limitDownCount` |
| 历史炸板数量序列 | `limitUp.historyPoints[].failedLimitUpCount` |
| 当日涨跌停分布 | `limitUp.distribution` |
| 连板层级股票数量 | `streakLadder.levels[].stockCount` |
| 连板股票列表 | `streakLadder.levels[].stocks[]` |

---

### 9. 给 02 HTML Showcase 的组件使用建议

1. 按 v1.1 主体布局顺序重排。
2. 图表必须有坐标、Tooltip、crosshair、RangeSwitch。
3. 模块说明文字收纳到 HelpTooltip。
4. 涨跌停分布不得使用普通列表。
5. 连板天梯必须横向、独占一行。
6. 大盘资金流向与榜单速览二等分。
7. TopMarketBar 中“系统设置”完整展示。
8. 指数、榜单、资金、涨跌停全部红涨绿跌。
9. 平盘用白色或灰白色。
10. 数据点不足时显示局部空态，不伪造趋势。

---

### 10. 给 04 API 的字段需求

本轮组件落地依赖 API v0.4 的以下字段：

1. `breadth.historyPoints[]`
2. `style.historyPoints[]`
3. `turnover.intradayPoints[]`
4. `turnover.historyPoints[]`
5. `moneyFlow.prevMainNetInflow`
6. `moneyFlow.historyPoints[]`
7. `limitUp.historyPoints[]`
8. `limitUp.distribution`
9. `streakLadder.levels[].stockCount`
10. `streakLadder.levels[].stocks[]`

字段原则：

- `rangeType` 使用 `1m | 3m`；
- 聚合接口默认返回 `1m`；
- `3m` 支持模块接口局部刷新；
- 金额和成交量单位必须通过字段表、`unit` 或 `displayText` 明确；
- 不返回市场温度、情绪、资金面分数、风险指数作为首页核心展示字段。

---

### 11. 给 01 Token 的依赖

v1.1 组件落地依赖 Token v0.2.4，尤其：

1. HelpTooltip Token；
2. RangeSwitch Token；
3. 图表坐标轴、网格、Tooltip、crosshair Token；
4. 历史涨跌分布线颜色；
5. 市场风格三线颜色；
6. 日内成交额线颜色；
7. 历史成交额线颜色；
8. 大盘资金流主线白色；
9. 0 轴线；
10. 涨跌停组合柱颜色；
11. 横向连板天梯层级与股票卡片 Token；
12. 平盘白色 / 灰白色 Token。

---

### 12. 给 05 Codex 提示词的组件约束

Codex 实现 `market-overview-v1.1.html` 或前端页面时，提示词必须强调：

1. 必须读取项目总说明、PRD、页面设计、Token、组件、API v0.4、Review v1。
2. 不允许新增固定 SideNav。
3. 不允许把市场总览做成独立一级菜单。
4. 不允许展示市场温度、情绪指数、资金面分数、风险指数。
5. 不允许输出买卖建议、仓位建议、明日预测。
6. TopMarketBar 中“系统设置”必须完整展示。
7. 指数和榜单必须红涨绿跌，平盘白色/灰白色。
8. 模块说明文字必须收纳到 HelpTooltip。
9. 历史图表必须有坐标、Tooltip、crosshair、RangeSwitch。
10. 涨跌停分布不得使用普通列表。
11. 连板天梯必须横向，独占一行。
12. 单模块失败不能导致整页不可用。

Smoke test 至少验证：

```text
1. 启动项目成功
2. 打开 /market/overview 成功
3. 页面无白屏
4. 控制台无明显错误
5. TopMarketBar 系统设置完整展示
6. RangeSwitch 可切换
7. HelpTooltip 可显示
8. 图表 crosshair 和 Tooltip 可用
9. 涨跌停分布不是普通列表
10. 连板天梯横向展示
11. 榜单行 hover 明确
12. 红涨绿跌正确
```

---

### 13. 本轮新增组件清单

| 组件 | 用途 | P0 |
|---|---|---:|
| HelpTooltip | 模块说明收纳 | 是 |
| RangeSwitch | 1m / 3m 切换 | 是 |
| HistoryTrendChart | 通用历史趋势图 | 是 |
| IntradayTurnoverChart | 当日累计成交额趋势 | 是 |
| MarketStyleTrendChart | 市场风格三线趋势 | 是 |
| MoneyFlowHistoryChart | 大盘资金历史趋势 | 是 |
| LimitUpDownHistoryBarChart | 涨跌停历史组合柱 | 是 |
| LimitUpDistributionPanel | 图形化涨跌停分布 | 是 |
| HorizontalLimitUpStreakLadder | 横向连板天梯 | 是 |
| MetricMiniCardGroup | 小指标卡组 | 是 |

---

### 14. 本轮修改组件清单

| 组件 | 修改点 |
|---|---|
| TopMarketBar | 修复系统入口文字截断；系统设置完整展示；空间不足折叠菜单 |
| IndexTickerStrip | 与 IndexCard 统一红涨绿跌和平盘颜色 |
| IndexCard | 点位、涨跌额、涨跌幅、趋势线统一方向色 |
| RankingTable | 支持半宽二等分布局；行 hover 明确；列密度优化 |
| TurnoverSummaryCard | 增加 4 小卡、日内成交额图、历史成交额图 |
| MoneyFlowSummaryPanel | 改为今日/昨日净流入双卡 + 历史资金图 |
| LimitUpSummaryCard | 与分布面板和历史柱图合并成大模块 |
| LimitUpStreakLadder | 增加 horizontal 变体，市场总览默认横向 |

---

### 15. 可后置组件清单

| 组件 / 能力 | 后置原因 |
|---|---|
| 完整 HeatMap 大图 | 市场总览只保留入口，完整热力图进入板块与榜单页 |
| KlineChartShell 完整实现 | 属于指数详情/个股详情页重点 |
| IndicatorPanelShell 完整实现 | 属于 K 线详情页 |
| OpportunityCard | 机会雷达页重点 |
| ScoreBreakdown | 市场温度与情绪 / 机会雷达页重点 |
| AlertRuleEditor | 提醒中心重点 |
| TradePlanCard | 交易助手后续重点 |
| SideNav | 全局可后置，但市场总览桌面端禁用 |
| Drawer / Modal 完整通用规范 | P0 Showcase 可轻量模拟，完整交互库后置 |

---

### 16. 不用于市场总览桌面端的组件清单

| 组件 / 设计形态 | 说明 |
|---|---|
| SideNav | 不作为市场总览桌面端 P0 组件 |
| PersistentLeftRail | 禁用 |
| 大型左侧导航栏 | 禁用 |
| 大面积入口卡片墙 | 禁用 |
| 营销式 Hero Banner | 禁用 |
| 廉价大屏风发光边框 | 禁用 |
| 主观评分大仪表盘 | 禁用，市场温度/情绪页再使用 |
| 无坐标装饰趋势线 | v1.1 禁用 |

---

### 17. 待产品总控确认问题

1. `market-overview-v1.1.html` 的历史趋势默认是否统一返回 `1m`，`3m` 全部按模块接口懒加载？
2. 日内累计成交额是否已有稳定全市场分钟聚合表？若没有，P0 是否以 mock / 延迟态表达？
3. 大盘资金流 `moneyflow_mkt_dc` 多数为盘后数据，盘中是否需要标记为 `DELAYED`？
4. 涨跌停数据是否需要显性展示“ST 股票是否纳入口径”的说明？
5. `LimitUpDistributionPanel` 最终采用“分布条 + 板块块”还是“矩阵”作为正式高保真样式？
6. `HorizontalLimitUpStreakLadder` 每层最多展示几只股票？超出后是“更多”还是层内滚动？
7. `RankingTable` 半宽布局下，各榜单隐藏列是否由组件自动判断还是页面配置？
8. 平盘关键数字使用纯白还是灰白，需要 01 Token 最终确认。
9. 组件规范 v0.4 是否作为 `market-overview-v1.1.html` 的当前实现基线？

---

### 18. 修订记录

| 版本 | 日期 | 说明 |
|---|---|---|
| v0.3 | 2026-05-06 | 市场总览 P0 组件规范基线，收敛无固定 SideNav、TopMarketBar、Breadcrumb、ShortcutBar、指数、市场结构、涨跌停、榜单等组件。 |
| v0.4 | 2026-05-07 | 完整合并 HTML Review v1 变更：新增 HelpTooltip、RangeSwitch、历史趋势图、日内成交图、资金历史图、涨跌停柱图、涨跌停分布面板、横向连板天梯、MetricMiniCardGroup；同步 API v0.4 / Token v0.2.4。 |
---

## 16. HTML Review v2 → market-overview-v1.2 局部修订合并规范

> 本节为 `market-overview-html-review-v2` 的全量合并内容。它不替代前文已确认的组件规范，而是在完整保留 v0.4 merged-full 基线的前提下，对 Review v2 明确点名的四个区域进行组件级修订。除本节列出的组件外，不主动改动 TopMarketBar、Breadcrumb、PageHeader、ShortcutBar、涨跌分布、市场风格、成交额总览、大盘资金流向、连板天梯及其它未点名组件。

### 16.1 本轮修订边界

#### 16.1.1 允许修改区域

| 区域 | Review v2 要求 | 本节对应组件 |
|---|---|---|
| 今日市场客观总结与主要指数 | 恢复左右 50% / 50%；左侧 5 个事实卡片 + 说明性文字卡；右侧主要指数两行，每行 5 个 | `MarketSummaryIndexSplit`、`MarketSummaryFactCard`、`MarketSummaryNoteCard`、`IndexGrid` |
| 榜单速览 | 表格展示 Top10；固定列：排名、股票、最新价、涨跌幅、换手率、量比、成交量、成交额 | `RankingTable` v2 变体 |
| 涨跌停统计与分布 | 2×2：左上 8 卡，右上今日分布结构，左下历史组合柱状图，右下昨日分布结构 | `LimitUpDistributionGrid`、`LimitUpDistributionMiniPanel` |
| 板块速览 | 左侧 4 列 × 2 行榜单矩阵；右侧 5×4 热力图跨两行 | `SectorOverviewMatrix`、`SectorHeatMap` |

#### 16.1.2 禁止主动修改区域

以下组件和模块本轮保持 v0.4 merged-full 规范，不因为 Review v2 主动重构：

- `TopMarketBar`
- `Breadcrumb`
- `PageHeader`
- `ShortcutBar`
- `MarketBreadthPanel` / 涨跌分布
- `MarketStylePanel` / 市场风格
- `TurnoverSummaryCard` / 成交额总览
- `MoneyFlowSummaryPanel` / 大盘资金流向
- `HorizontalLimitUpStreakLadder` / 连板天梯
- 其它未被 Review v2 点名的组件

---

### 16.2 MarketSummaryIndexSplit

| 项 | 说明 |
|---|---|
| 组件名称 | `MarketSummaryIndexSplit` |
| 组件用途 | 承载“今日市场客观总结 + 主要指数”的左右组合布局，恢复 Review v2 指定的 50% / 50% 首屏结构。 |
| 使用页面 | 市场总览 / `market-overview-v1.2.html`。 |
| 是否市场总览 P0 必需 | 是，Review v2 点名。 |
| 输入字段 / Props | `summary`、`indices`、`layout`、`loading`、`error`、`onIndexClick`、`onFactClick`。 |
| 字段类型 | 见下方 TypeScript 接口。 |
| 与 API 字段的映射 | `marketSummary`、`indices[]`、`tradingDay.tradeDate`、`dataStatus[]`。 |
| 视觉结构 | 左右两栏各占 50%。左侧为标题 + 5 个事实卡片 + 说明性文字卡片；右侧为标题 + `IndexGrid`，固定两行，每行 5 个指数卡。两栏高度尽量对齐。 |
| 响应式降级 | 桌面宽度 ≥ 1280px：50% / 50%；1024–1279px：仍保持两栏，但卡片内文字压缩；<1024px：上下堆叠，先市场总结后主要指数；禁止在桌面端改为两个独占整行模块。 |
| 交互行为 | 左侧事实卡 hover 展示口径 Tooltip；可点击事实卡下钻到对应模块或榜单；右侧指数卡点击进入指数详情页。 |
| 状态 | default：左右布局正常；hover：子卡片高亮；active：点击卡片压暗；selected：可高亮从外部路由返回的指数；disabled：数据不可下钻时禁用点击；loading：左侧 5 卡骨架 + 右侧 10 指数卡骨架；empty：左侧显示事实缺失说明，右侧指数不足时补 `--` 占位；error：单侧异常不拖垮另一侧。 |
| 涨跌色规则 | 左侧事实卡按 `semanticType` 着色；右侧指数点位、涨跌额、涨跌幅严格红涨绿跌，平盘白色或灰白。 |
| 与 Design Token 的关系 | 使用 `--cs-color-surface-card`、`--cs-color-surface-card-hover`、`--cs-color-market-up/down/flat`、`--cs-font-family-number`、`--cs-space-12/16`、`--cs-radius-card`、`--cs-color-border-subtle`。 |
| 备注 | 本组件只调整今日总结与指数的组合关系，不改变 TopMarketBar、PageHeader、ShortcutBar。 |

```ts
interface MarketSummaryIndexSplitProps {
  summary: {
    title: string;
    facts: MarketSummaryFactCardProps[]; // 固定展示 5 个
    note: MarketSummaryNoteCardProps;
    tradeDate: string;
    dataStatus?: DataStatusMeta;
  };
  indices: IndexCardProps[]; // 目标 10 个
  layout?: 'half-half';
  loading?: boolean;
  error?: ErrorStateProps | null;
  onIndexClick?: (indexCode: string) => void;
  onFactClick?: (fact: MarketSummaryFactCardProps) => void;
}
```

---

### 16.3 MarketSummaryFactCard

| 项 | 说明 |
|---|---|
| 组件名称 | `MarketSummaryFactCard` |
| 组件用途 | 今日市场客观总结中的事实指标卡，固定用于展示 5 个核心事实指标。 |
| 使用页面 | 市场总览 / 今日市场客观总结。 |
| 是否市场总览 P0 必需 | 是，Review v2 点名。 |
| 输入字段 / Props | `title`、`value`、`unit`、`change`、`semanticType`、`tooltip`、`route`、`disabled`。 |
| 字段类型 | 见下方 TypeScript 接口。 |
| 与 API 字段的映射 | 可映射 `breadth.upCount/downCount/flatCount/redRate/medianChangePct`、`turnover.totalAmount/amountChangePct`、`moneyFlow.mainNetInflow`、`limitUp.limitUpCount/limitDownCount/failedLimitUpCount/highestStreak` 等客观事实。 |
| 视觉结构 | 小型数字卡。上方 `title`，中间主值 `value + unit`，下方可选 `change` 或说明。五张卡建议一行 5 个或在左栏内 3+2 排布，优先保证数字可读性。 |
| 交互行为 | hover 时显示指标口径 Tooltip；点击可下钻到相关模块或详情页；无 route 时仅展示 Tooltip。 |
| 状态 | default：正常展示；hover：背景提亮、边框增强；active：压暗；selected：外部筛选命中时描边；disabled：置灰并展示 disabledReason；loading：数字骨架；empty：显示 `--`；error：显示局部错误标记。 |
| 涨跌色规则 | `semanticType=up/limitUp/inflow/positive` 使用红；`down/limitDown/outflow/negative` 使用绿；`flat/neutral` 使用白色或灰白；系统错误不使用行情红。 |
| 与 Design Token 的关系 | `--cs-color-market-up/down/flat-strong/flat-soft`、`--cs-color-surface-card`、`--cs-font-family-number`、`--cs-color-help-icon`。 |
| 备注 | FactCard 只陈列客观事实，不输出“适合买入”“情绪升温”“风险下降”等主观结论。 |

```ts
type MarketSummaryFactSemanticType =
  | 'up'
  | 'down'
  | 'flat'
  | 'limitUp'
  | 'limitDown'
  | 'inflow'
  | 'outflow'
  | 'positive'
  | 'negative'
  | 'neutral';

interface MarketSummaryFactCardProps {
  key: string;
  title: string;
  value: number | string | null;
  unit?: string;
  change?: {
    value: number | null;
    unit?: string;
    direction?: Direction;
    label?: string;
  };
  semanticType: MarketSummaryFactSemanticType;
  tooltip?: string;
  route?: string;
  disabled?: boolean;
  disabledReason?: string;
}
```

---

### 16.4 MarketSummaryNoteCard

| 项 | 说明 |
|---|---|
| 组件名称 | `MarketSummaryNoteCard` |
| 组件用途 | 今日市场客观总结左侧下方的说明性文字卡片，用于放置客观事实摘要或数据口径说明。 |
| 使用页面 | 市场总览 / 今日市场客观总结。 |
| 是否市场总览 P0 必需 | 是，Review v2 点名。 |
| 输入字段 / Props | `title`、`text`、`maxLength`、`helpTooltip`、`dataScopeNote`、`tone`。 |
| 字段类型 | `text:string; maxLength?:number; tone:'neutral'|'info'|'warning'`。 |
| 与 API 字段的映射 | `marketSummary.summaryText`、`marketSummary.note`、`marketSummary.dataScopeNote`，也可由 ViewModel 根据 `breadth/turnover/moneyFlow/limitUp` 拼出客观摘要。 |
| 视觉结构 | 位于 5 个事实卡片下方，弱背景、弱边框、小字号。可选标题，不宜过高。 |
| 文案长度限制 | 建议 60–90 个中文字符；超过后截断并通过 HelpTooltip / 展开查看完整说明。 |
| 交互行为 | 支持 HelpTooltip；不需要点击跳转；如有“查看口径”可打开数据说明 Popover。 |
| 状态 | default：展示短文案；hover：边框微亮；active：无特殊；selected：不使用；disabled：不使用；loading：文字骨架；empty：隐藏或显示“暂无摘要”；error：不因摘要失败影响事实卡和指数卡。 |
| 涨跌色规则 | 文案本身使用中性色；如内嵌数值，仍按红涨绿跌；不得用红绿渲染整张说明卡。 |
| 与 Design Token 的关系 | `--cs-color-surface-card`、`--cs-color-border-subtle`、`--cs-color-text-secondary`、`--cs-color-help-tooltip-bg`、`--cs-radius-card`。 |
| 备注 | 禁止输出主观交易建议、仓位建议、明日预测、看多看空。 |

```ts
interface MarketSummaryNoteCardProps {
  title?: string;
  text: string;
  maxLength?: number; // 建议 90
  helpTooltip?: string;
  dataScopeNote?: string;
  tone?: 'neutral' | 'info' | 'warning';
}
```

---

### 16.5 IndexGrid

| 项 | 说明 |
|---|---|
| 组件名称 | `IndexGrid` |
| 组件用途 | 在 MarketSummaryIndexSplit 右侧展示主要指数，两行、每行 5 个。 |
| 使用页面 | 市场总览 / 主要指数。 |
| 是否市场总览 P0 必需 | 是，Review v2 点名。 |
| 输入字段 / Props | `items`、`columns`、`rows`、`minCardWidth`、`onIndexClick`、`placeholderStrategy`。 |
| 字段类型 | `items: IndexCardProps[]; columns:5; rows:2; minCardWidth?:number`。 |
| 与 API 字段的映射 | `indices[]`，字段包括 `indexCode/indexName/last/change/changePct/amount/direction/trend/asOf`。 |
| 视觉结构 | 固定 2 行 × 5 列，共 10 个位置。每个格子承载轻量 IndexCard，数字右对齐或垂直堆叠。 |
| 指数数量不足处理 | 少于 10 个时用 `--` 占位卡补足，避免网格塌陷；占位卡不响应点击。 |
| 指数数量超出处理 | 超过 10 个时首页只取前 10 个，剩余进入指数详情或更多指数列表；本区域不得横向滚动。 |
| IndexCard 最小宽度 | 建议 ≥ 108px；低于该宽度时隐藏成交额和趋势线，只保留指数名、点位、涨跌幅。 |
| 交互行为 | 点击真实指数卡进入指数详情；hover 显示开高低收、成交额、更新时间。 |
| 状态 | default：10 宫格；hover：单卡高亮；active：点击压暗；selected：可高亮当前指数；disabled：占位/不可用指数置灰；loading：10 个骨架卡；empty：全部占位并提示指数数据暂缺；error：右侧网格显示局部错误，不影响左侧总结。 |
| 涨跌色规则 | IndexCard 内点位、涨跌额、涨跌幅、小趋势严格红涨绿跌，平盘白色或灰白。 |
| 与 Design Token 的关系 | `--cs-color-market-up/down/flat`、`--cs-grid-index-card-min-width`、`--cs-font-family-number`、`--cs-space-8/10`。 |
| 备注 | Review v2 明确要求主要指数维持两行，每行 5 个；不要改成一行、独占整行或横向滚动。 |

```ts
interface IndexGridProps {
  items: IndexCardProps[];
  columns?: 5;
  rows?: 2;
  minCardWidth?: number;
  placeholderStrategy?: 'fill-to-10' | 'hide-empty';
  loading?: boolean;
  error?: ErrorStateProps | null;
  onIndexClick?: (indexCode: string) => void;
}
```

---

### 16.6 RankingTable：Review v2 Top10 变体

| 项 | 说明 |
|---|---|
| 组件名称 | `RankingTable` / `RankingTable.Top10` |
| 组件用途 | 榜单速览 Top10 表格，补全行情观察字段，支持个股下钻。 |
| 使用页面 | 市场总览 / 榜单速览。 |
| 是否市场总览 P0 必需 | 是，Review v2 点名修订。 |
| 输入字段 / Props | `rankType`、`rows`、`columns`、`maxRows`、`density`、`containerMode`、`loading`、`error`、`onRowClick`、`onSortChange`。 |
| 字段类型 | 见下方 TypeScript 接口。 |
| 与 API 字段的映射 | `leaderboards[rankType].items[]` 或 `stockLeaderboards[rankType].items[]`；字段映射 `rank/stockCode/stockName/latestPrice/changePct/turnoverRate/volumeRatio/volume/amount/direction`。 |
| Top 数量 | 首页固定展示 Top10。少于 10 行时保留表格高度并显示空行占位；多于 10 行时仅展示前 10，完整榜单通过“查看更多”进入板块与榜单行情页。 |
| 固定列顺序 | `排名｜股票｜最新价｜涨跌幅｜换手率｜量比｜成交量｜成交额`。 |
| 半宽容器策略 | 在大盘资金流向｜榜单速览二等分布局中，表格仍需可读。优先压缩“股票”列为名称+代码双行；成交量、成交额使用万/亿等 displayText；必要时隐藏次级行业/概念，不隐藏 Review v2 指定列。 |
| 列宽建议 | 排名 44px；股票 128–156px；最新价 74px；涨跌幅 72px；换手率 70px；量比 62px；成交量 86px；成交额 92px。低宽度时字号降至 11px，行高保持 30–34px。 |
| 数字格式化 | 最新价保留 2 位；涨跌幅带 `%` 和正负号；换手率 `%`；量比 2 位；成交量使用 `万手/万股` 或 API `displayText`；成交额使用 `亿/万` 或 API `displayText`。 |
| 交互行为 | Tab 切换榜单；行 hover 高亮；点击股票行进入个股详情并携带 `stockCode`、`tradeDate`；表头可排序但首页默认只排序当前 Top10 数据。 |
| 状态 | default：Top10 表格；hover：行背景提亮、股票名下划线或品牌色；active：点击压暗；selected：当前行可描边；disabled：未开放榜单置灰；loading：10 行骨架；empty：显示“当前榜单暂无数据”；error：局部错误 + 重试按钮，不影响其它榜单 Tab。 |
| 涨跌色规则 | 最新价、涨跌幅按 `direction` 红涨绿跌；换手率、量比、成交量、成交额默认中性色；跌幅榜中的负涨跌幅必须绿色。 |
| 与 Design Token 的关系 | `--cs-density-ranking-table-row-height`、`--cs-font-family-number`、`--cs-color-table-row-hover-bg`、`--cs-color-market-up/down/flat`、`--cs-color-border-subtle`。 |
| 备注 | 不得删除 Review v2 指定列；不得把榜单降回 Top5。 |

```ts
interface RankingTableTop10Props {
  rankType: 'GAINERS' | 'LOSERS' | 'AMOUNT' | 'TURNOVER' | 'VOLUME_RATIO' | string;
  rows: StockRankTop10Row[];
  maxRows?: 10;
  density?: 'compact' | 'normal';
  containerMode?: 'half-width' | 'full-width';
  loading?: boolean;
  error?: ErrorStateProps | null;
  onRowClick?: (row: StockRankTop10Row) => void;
  onSortChange?: (field: keyof StockRankTop10Row, order: 'asc' | 'desc') => void;
}

interface StockRankTop10Row {
  rank: number;
  stockCode: string;
  stockName: string;
  latestPrice: number | null;
  changePct: number | null;
  turnoverRate: number | null;
  volumeRatio: number | null;
  volume: number | null;
  amount: number | null;
  volumeDisplayText?: string;
  amountDisplayText?: string;
  direction: Direction;
}
```

---

### 16.7 LimitUpDistributionGrid

| 项 | 说明 |
|---|---|
| 组件名称 | `LimitUpDistributionGrid` |
| 组件用途 | 承载 Review v2 指定的“涨跌停统计与分布”2×2 区域。 |
| 使用页面 | 市场总览 / 涨跌停统计与分布。 |
| 是否市场总览 P0 必需 | 是，Review v2 点名。 |
| 输入字段 / Props | `summaryCards`、`todayDistribution`、`historyBars`、`previousDistribution`、`loading`、`error`、`onSectorClick`、`onCategoryClick`。 |
| 字段类型 | 见下方 TypeScript 接口。 |
| 与 API 字段的映射 | `limitUp`、`limitUp.distribution.today`、`limitUp.distribution.previousTradeDay`、`limitUp.historyPoints`；若 API 仍拆为 `limitUpDistribution`，ViewModel 需合并为本组件所需结构。 |
| 布局结构 | 2×2 网格。左上：8 个统计卡片；右上：今日涨停板块分布 + 跌停/炸板结构；左下：历史涨跌停组合柱状图；右下：昨天涨停板块分布 + 跌停/炸板结构。 |
| 今日/昨天标签 | 右上标题必须含“今日”；右下标题必须含“上一交易日”或“昨日”；Tooltip 展示对应 `tradeDate`。 |
| 历史柱状图嵌入方式 | 左下嵌入 `LimitUpDownHistoryBarChart`，展示涨停红、跌停绿，同一日期柱组并列；支持 1个月/3个月切换沿用 v1.1 规则。 |
| 交互行为 | 点击统计卡进入对应榜单；点击板块分布进入板块与榜单行情页；点击跌停/炸板结构类别进入对应筛选榜单。 |
| 状态 | default：2×2 完整展示；hover：子块和板块块高亮；active：点击压暗；selected：外部筛选命中时描边；disabled：无下钻能力时置灰；loading：四块分别骨架；empty：缺少昨日数据时右下显示“上一交易日分布暂缺”；error：某块异常只影响该块。 |
| 涨跌色规则 | 涨停统计和涨停分布红；跌停结构绿；炸板使用 warning；历史柱图涨停红、跌停绿。 |
| 与 Design Token 的关系 | `--cs-color-limitup-bar`、`--cs-color-limitdown-bar`、`--cs-color-market-up/down`、`--cs-color-warning`、`--cs-color-chart-grid-primary`、`--cs-radius-card`。 |
| 备注 | 本组件替代“普通长列表式涨跌停分布”。不得把右上/右下做成长列表，必须使用分布条、矩阵、紧凑图形或分组块。 |

```ts
interface LimitUpDistributionGridProps {
  summaryCards: MarketSummaryFactCardProps[]; // 固定 8 个统计卡片
  todayDistribution: LimitUpDistributionMiniPanelProps;
  previousDistribution: LimitUpDistributionMiniPanelProps;
  historyBars: LimitUpDownHistoryBarChartProps;
  loading?: boolean;
  error?: ErrorStateProps | null;
  onSectorClick?: (sectorCode: string, dateType: 'today' | 'previousTradeDay') => void;
  onCategoryClick?: (categoryKey: string, dateType: 'today' | 'previousTradeDay') => void;
}
```

---

### 16.8 LimitUpDistributionMiniPanel

| 项 | 说明 |
|---|---|
| 组件名称 | `LimitUpDistributionMiniPanel` |
| 组件用途 | 展示今日或上一交易日的涨停板块分布 + 跌停/炸板结构，用于 `LimitUpDistributionGrid` 的右上和右下区域。 |
| 使用页面 | 市场总览 / 涨跌停统计与分布。 |
| 是否市场总览 P0 必需 | 是，Review v2 点名。 |
| 输入字段 / Props | `dateType`、`tradeDate`、`limitUpSectorDistribution`、`limitDownStructure`、`brokenLimitStructure`、`maxItems`、`onSectorClick`、`onCategoryClick`。 |
| 字段类型 | 见下方 TypeScript 接口。 |
| 与 API 字段的映射 | `limitUp.distribution.today.limitUpSectorDistribution`、`limitUp.distribution.today.limitDownStructure`、`limitUp.distribution.today.brokenLimitStructure`；上一交易日使用 `previousTradeDay` 同构字段。 |
| 图形表达方式 | 推荐使用：顶部日期标签 + 板块分布条 / 分布块；下方使用跌停/炸板小矩阵或双条结构。不要使用普通长列表。 |
| Tooltip | hover 板块块显示 `sectorName`、涨停数、占比、代表股票；hover 跌停/炸板块显示数量、占比和口径。 |
| 点击行为 | 点击板块进入板块与榜单行情页并携带 `sectorCode`、`tradeDate`、`limitType=LIMIT_UP`；点击跌停/炸板结构进入对应榜单筛选。 |
| 状态 | default：分布图正常；hover：图形块高亮；active：点击压暗；selected：命中筛选时描边；disabled：不可下钻项置灰；loading：图形骨架；empty：显示“暂无该日分布数据”；error：局部错误和重试。 |
| 涨跌色规则 | 涨停板块分布红色强弱；跌停结构绿色；炸板结构 warning；中性标签灰白。 |
| 与 Design Token 的关系 | `--cs-color-market-up/down`、`--cs-color-warning`、`--cs-color-chart-tooltip-bg`、`--cs-color-chart-grid-secondary`。 |
| 备注 | `dateType=today` 展示“今日”；`dateType=previousTradeDay` 展示“上一交易日 / 昨日”。 |

```ts
interface LimitUpDistributionMiniPanelProps {
  dateType: 'today' | 'previousTradeDay';
  tradeDate: string;
  limitUpSectorDistribution: Array<{
    sectorCode: string;
    sectorName: string;
    count: number;
    ratio?: number;
    leadingStocks?: Array<{ stockCode: string; stockName: string }>;
  }>;
  limitDownStructure: Array<{
    key: string;
    label: string;
    count: number;
    ratio?: number;
  }>;
  brokenLimitStructure: Array<{
    key: string;
    label: string;
    count: number;
    ratio?: number;
  }>;
  maxItems?: number;
  loading?: boolean;
  error?: ErrorStateProps | null;
  onSectorClick?: (sectorCode: string) => void;
  onCategoryClick?: (categoryKey: string) => void;
}
```

---

### 16.9 SectorOverviewMatrix

| 项 | 说明 |
|---|---|
| 组件名称 | `SectorOverviewMatrix` |
| 组件用途 | 板块速览左侧 4 列 × 2 行榜单矩阵，承载八个 Top5 榜单块。 |
| 使用页面 | 市场总览 / 板块速览。 |
| 是否市场总览 P0 必需 | 是，Review v2 点名。 |
| 输入字段 / Props | `groups`、`columns`、`rows`、`topN`、`loading`、`error`、`onSectorClick`、`onLeaderStockClick`。 |
| 字段类型 | 见下方 TypeScript 接口。 |
| 与 API 字段的映射 | `sectorOverview.industryTopGainers`、`conceptTopGainers`、`regionTopGainers`、`fundInflowTop`、`industryTopLosers`、`conceptTopLosers`、`regionTopLosers`、`fundOutflowTop`。 |
| 固定布局 | 左侧 4 列 × 2 行。上排：行业涨幅前五｜概念涨幅前五｜地域涨幅前五｜资金流入前五。下排：行业跌幅前五｜概念跌幅前五｜地域跌幅前五｜资金流出前五。 |
| 每个榜单块字段 | 排名、板块名称、涨跌幅或资金额、领涨股。资金榜展示净流入/净流出金额；涨跌榜展示涨跌幅。每块固定 Top5。 |
| 交互行为 | 点击板块进入板块与榜单行情页；点击领涨股进入个股详情；hover 行显示成交额、成分上涨/下跌家数、数据更新时间。 |
| 状态 | default：8 个榜单块完整展示；hover：榜单行高亮；active：点击压暗；selected：外部筛选命中时高亮对应板块；disabled：不可下钻项置灰；loading：8 个榜单块骨架；empty：单榜为空时保留块并显示“暂无数据”；error：单榜错误不影响其它榜。 |
| 涨跌色规则 | 涨幅榜红、跌幅榜绿；资金流入红、资金流出绿；榜单标题不使用红绿大色块，可用细线或小标签提示方向。 |
| 与 Design Token 的关系 | `--cs-color-market-up/down/flat`、`--cs-color-table-row-hover-bg`、`--cs-density-table-row-height`、`--cs-font-family-number`。 |
| 备注 | 该组件只覆盖板块速览左侧矩阵；右侧热力图由 `SectorHeatMap` 承载。 |

```ts
type SectorOverviewGroupKey =
  | 'industryTopGainers'
  | 'conceptTopGainers'
  | 'regionTopGainers'
  | 'fundInflowTop'
  | 'industryTopLosers'
  | 'conceptTopLosers'
  | 'regionTopLosers'
  | 'fundOutflowTop';

interface SectorOverviewMatrixProps {
  groups: Record<SectorOverviewGroupKey, SectorOverviewGroup>;
  columns?: 4;
  rows?: 2;
  topN?: 5;
  loading?: boolean;
  error?: ErrorStateProps | null;
  onSectorClick?: (sectorCode: string, groupKey: SectorOverviewGroupKey) => void;
  onLeaderStockClick?: (stockCode: string) => void;
}

interface SectorOverviewGroup {
  title: string;
  metricType: 'changePct' | 'moneyFlow';
  direction: 'UP' | 'DOWN';
  items: SectorOverviewRankItem[];
}

interface SectorOverviewRankItem {
  rank: number;
  sectorCode: string;
  sectorName: string;
  sectorType: 'INDUSTRY' | 'CONCEPT' | 'REGION' | 'FUND_FLOW';
  changePct?: number | null;
  netInflow?: number | null;
  amountDisplayText?: string;
  leadingStockCode?: string;
  leadingStockName?: string;
  leadingStockChangePct?: number | null;
}
```

---

### 16.10 SectorHeatMap

| 项 | 说明 |
|---|---|
| 组件名称 | `SectorHeatMap` |
| 组件用途 | 板块速览右侧跨两行的 5×4 板块热力图，展示 20 个板块格子。 |
| 使用页面 | 市场总览 / 板块速览。 |
| 是否市场总览 P0 必需 | 是，Review v2 点名。 |
| 输入字段 / Props | `items`、`rows`、`columns`、`colorMetric`、`title`、`loading`、`error`、`onSectorClick`。 |
| 字段类型 | 见下方 TypeScript 接口。 |
| 与 API 字段的映射 | `sectorOverview.heatMapItems[]` 或 `sectorOverview.heatMap.items[]`；字段包含 `sectorCode/sectorName/sectorType/changePct/amount/netInflow/direction/rank/weight`。 |
| 位置与尺寸 | 位于板块速览右侧，跨左侧 4×2 榜单矩阵的两行高度。不得只放在第一行。 |
| 内部结构 | 固定 5 行 × 4 列，共 20 个格子。少于 20 个用空格占位；多于 20 个只展示前 20，完整热力图进入板块与榜单行情页。 |
| 每个格子字段 | 板块名称、涨跌幅、可选成交额/资金净流入、sectorType。格子大小一致或轻微按权重变化；v1.2 推荐固定 5×4 更稳定。 |
| 交互行为 | hover 显示 Tooltip：板块名、类型、涨跌幅、成交额、资金净流入、上涨/下跌成分数；点击板块下钻。 |
| 状态 | default：20 格热力图；hover：格子提亮、边框增强；active：点击压暗；selected：选中板块描边；disabled：不可下钻格子置灰；loading：5×4 骨架；empty：显示“暂无板块热力数据”；error：热力图错误不影响左侧榜单矩阵。 |
| 涨跌色规则 | 上涨红、下跌绿、平盘白色或灰白；颜色深浅表达涨跌幅绝对值；资金色不覆盖涨跌色，资金只在 Tooltip 中展示。 |
| 与 Design Token 的关系 | `--cs-color-market-up/down/flat`、`--cs-color-surface-card`、`--cs-color-chart-tooltip-bg`、`--cs-color-border-subtle`、`--cs-radius-card`。 |
| 备注 | 热力图是右侧独立跨两行组件，不是左侧榜单矩阵的附属第一行，也不是只提供入口。 |

```ts
interface SectorHeatMapProps {
  title?: string;
  items: SectorHeatMapItem[];
  rows?: 5;
  columns?: 4;
  colorMetric?: 'changePct';
  loading?: boolean;
  error?: ErrorStateProps | null;
  onSectorClick?: (sectorCode: string) => void;
}

interface SectorHeatMapItem {
  sectorCode: string;
  sectorName: string;
  sectorType: 'INDUSTRY' | 'CONCEPT' | 'REGION';
  changePct: number | null;
  direction: Direction;
  amount?: number | null;
  amountDisplayText?: string;
  netInflow?: number | null;
  netInflowDisplayText?: string;
  upCount?: number | null;
  downCount?: number | null;
  rank?: number;
  weight?: number;
}
```

---

### 16.11 本轮 Review v2 组件与 API 字段映射表

| Review v2 区域 | 组件 | API 字段 / ViewModel 字段 | 字段需求 |
|---|---|---|---|
| 今日市场客观总结 + 主要指数 | `MarketSummaryIndexSplit` | `marketSummary`、`indices[]` | `marketSummary.facts[5]`、`marketSummary.note`、`indices[10]` |
| 今日市场客观总结事实卡 | `MarketSummaryFactCard` | `marketSummary.facts[]`，可由 `breadth/turnover/moneyFlow/limitUp` 派生 | `title/value/unit/change/semanticType/tooltip` |
| 今日市场客观总结说明卡 | `MarketSummaryNoteCard` | `marketSummary.note`、`marketSummary.dataScopeNote` | 文案不得包含主观交易建议 |
| 主要指数网格 | `IndexGrid` | `indices[]` | 10 个指数，字段同 `IndexCard` |
| 榜单速览 Top10 | `RankingTable.Top10` | `leaderboards[rankType].items[]` | `rank/stockCode/stockName/latestPrice/changePct/turnoverRate/volumeRatio/volume/amount/direction` |
| 涨跌停 2×2 | `LimitUpDistributionGrid` | `limitUp`、`limitUp.distribution`、`limitUp.historyPoints` | 左上 8 卡、右上今日分布、左下历史柱图、右下昨日分布 |
| 今日/昨日涨跌停分布 | `LimitUpDistributionMiniPanel` | `limitUp.distribution.today`、`limitUp.distribution.previousTradeDay` | `limitUpSectorDistribution/limitDownStructure/brokenLimitStructure` |
| 板块速览左侧矩阵 | `SectorOverviewMatrix` | `sectorOverview.industryTopGainers/conceptTopGainers/regionTopGainers/fundInflowTop/industryTopLosers/conceptTopLosers/regionTopLosers/fundOutflowTop` | 每组 Top5，含排名、板块名、涨跌幅/资金、领涨股 |
| 右侧板块热力图 | `SectorHeatMap` | `sectorOverview.heatMapItems[]` | 20 个格子，5×4，含板块名、类型、涨跌幅、方向、Tooltip 扩展字段 |

---

### 16.12 对 02 market-overview-v1.2.html 的组件使用建议

1. `MarketSummaryIndexSplit` 必须紧跟 ShortcutBar 之后，保持左右 50% / 50%。
2. 左侧“今日市场客观总结”先渲染 5 个 `MarketSummaryFactCard`，下方渲染 `MarketSummaryNoteCard`。
3. 右侧“主要指数”使用 `IndexGrid`，固定两行，每行 5 个；不要横向滚动，不要缩成单行。
4. 榜单速览使用 `RankingTable.Top10`，Top10、固定 8 列，不得缺少换手率、量比、成交量、成交额。
5. 涨跌停统计与分布使用 `LimitUpDistributionGrid`，严格 2×2 排列。
6. 板块速览使用一个大容器：左侧 `SectorOverviewMatrix`，右侧 `SectorHeatMap` 跨两行。
7. 热力图为右侧 5×4 共 20 格，不得只放在第一行。
8. 本轮不调整 TopMarketBar、Breadcrumb、PageHeader、ShortcutBar、涨跌分布、市场风格、成交额、资金流、连板天梯。

---

### 16.13 对 04 API 的字段需求

| 字段需求 | 必要性 | 说明 |
|---|---:|---|
| `marketSummary.facts[]` 固定 5 个事实卡 | 必需 | 每项需要 `title/value/unit/change/semanticType/tooltip`。 |
| `marketSummary.note` | 必需 | 今日总结说明性文字卡，限制为客观事实表达。 |
| `indices[]` 至少 10 个 | 必需 | 用于 `IndexGrid` 两行 × 五列。 |
| `leaderboards[rankType].items[]` Top10 | 必需 | 每条需包含排名、股票、最新价、涨跌幅、换手率、量比、成交量、成交额。 |
| `limitUp.summaryCards[]` 或可派生 8 个统计卡 | 必需 | 支撑 2×2 左上角 8 卡。 |
| `limitUp.distribution.today` | 必需 | 今日涨停板块分布 + 跌停/炸板结构。 |
| `limitUp.distribution.previousTradeDay` | 必需 | 上一交易日涨停板块分布 + 跌停/炸板结构。 |
| `limitUp.historyPoints[]` | 必需 | 历史涨跌停组合柱状图。 |
| `sectorOverview.regionTopGainers[]` / `regionTopLosers[]` | 必需 | Review v2 新增地域涨跌前五。 |
| `sectorOverview.heatMapItems[]` 至少 20 个 | 必需 | 右侧 5×4 热力图。 |

---

### 16.14 本轮 Review v2 修改摘要

1. 新增 `MarketSummaryIndexSplit`，恢复今日市场客观总结与主要指数左右 50% / 50% 结构。
2. 新增 `MarketSummaryFactCard` 和 `MarketSummaryNoteCard`，规范左侧 5 个事实卡 + 说明性文字卡。
3. 新增 `IndexGrid`，规范主要指数两行，每行 5 个。
4. 修订 `RankingTable` 为 Top10 变体，固定列顺序为：排名、股票、最新价、涨跌幅、换手率、量比、成交量、成交额。
5. 新增 `LimitUpDistributionGrid` 和 `LimitUpDistributionMiniPanel`，规范涨跌停统计与分布 2×2 区域。
6. 新增 `SectorOverviewMatrix`，规范板块速览左侧 4 列 × 2 行榜单矩阵。
7. 新增 `SectorHeatMap`，规范右侧跨两行 5×4 热力图。
8. 明确本轮不修改 Review v2 未点名组件。

### 16.15 本轮新增或修订组件清单

| 类型 | 组件 | 处理方式 |
|---|---|---|
| 新增 | `MarketSummaryIndexSplit` | 新增布局组件 |
| 新增 | `MarketSummaryFactCard` | 新增事实卡组件 |
| 新增 | `MarketSummaryNoteCard` | 新增说明卡组件 |
| 新增 | `IndexGrid` | 新增主要指数网格组件 |
| 修订 | `RankingTable` | 增加 Review v2 Top10 表格变体 |
| 新增 | `LimitUpDistributionGrid` | 新增 2×2 容器组件 |
| 新增 | `LimitUpDistributionMiniPanel` | 新增今日/昨日分布图形组件 |
| 新增 | `SectorOverviewMatrix` | 新增板块榜单矩阵组件 |
| 新增 | `SectorHeatMap` | 新增 5×4 热力图组件；区别于旧 `HeatMap` 的通用形态 |

### 16.16 本轮未修改组件清单

以下组件保持 v0.4 merged-full 规范，不做主动改动：

- `TopMarketBar`
- `GlobalSystemMenu`
- `IndexTickerStrip`
- `Breadcrumb`
- `PageHeader`
- `MarketStatusPill`
- `DataStatusBadge`
- `ShortcutBar`
- `QuickEntryCard`
- `QuickEntryBadge`
- `MarketBreadthPanel`
- `DistributionChart`
- `HistoryTrendChart`
- `MarketStylePanel`
- `MarketStyleTrendChart`
- `TurnoverSummaryCard`
- `IntradayTurnoverChart`
- `MoneyFlowSummaryPanel`
- `FundFlowBar`
- `MoneyFlowHistoryChart`
- `HorizontalLimitUpStreakLadder`
- `HelpTooltip`
- `RangeSwitch`
- `LoadingSkeleton`
- `EmptyState`
- `ErrorState`
- `DataDelayState`
- `PermissionState`

### 16.17 待产品总控确认问题

1. `marketSummary.facts[]` 的 5 个事实卡具体字段是否固定为：上涨家数、下跌家数、成交额、资金净流入、涨停家数？还是允许页面 ViewModel 按数据状态选择？
2. `MarketSummaryNoteCard` 是否由 API 直接返回文案，还是由前端 ViewModel 基于客观字段拼接？建议 API 返回结构化事实，前端拼接。
3. 榜单速览 Top10 是否仍支持多个 Tab，还是默认展示某一个榜单并通过 Tab 切换？当前建议保留 Tab。
4. 榜单 Top10 的 `成交量` 单位采用股、手、万手还是 API `displayText`？建议 API 返回 `volumeDisplayText`。
5. 涨跌停右下角“昨天”应统一命名为“上一交易日”，还是 UI 文案直接用“昨日”？建议组件 props 使用 `previousTradeDay`，UI 可展示“上一交易日”。
6. `SectorHeatMap` 的 20 个格子按涨跌幅、成交额、资金净流入还是综合排序？建议 API 明确 `heatMapItems` 排序口径。
7. 地域板块 Top5 的数据源和覆盖范围是否已确认？若暂缺，`SectorOverviewMatrix` 需要显示单块空态，不影响其它 7 个榜单。

### 16.18 Review v2 验收清单

| 验收项 | 要求 |
|---|---|
| 完整文档 | 本文件仍是完整 `04-component-guidelines.md`，不是 delta 文档。 |
| 修改边界 | 只新增/修订 Review v2 点名区域组件。 |
| 今日总结 + 指数 | 左右 50% / 50%，左 5 卡 + 说明卡，右 2×5 指数。 |
| 榜单速览 | Top10，列顺序固定，字段完整。 |
| 涨跌停统计与分布 | 2×2：8 卡、今日分布、历史柱图、昨日分布。 |
| 板块速览 | 左侧 4×2 榜单矩阵，右侧跨两行 5×4 热力图。 |
| 红涨绿跌 | 指数、榜单、热力图、涨跌停全部遵守中国市场红涨绿跌。 |
| API 映射 | 所有新增组件均有 props 与 API 字段映射。 |
