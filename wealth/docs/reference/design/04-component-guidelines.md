# 财势乾坤｜P0 组件库与交互组件方案 v1.1 完整合并版

> 建议保存路径：`/docs/wealth/04-component-guidelines.md`  
> 负责人：`03_组件库与交互组件方案`  
> 状态：`Draft v1.1 merged-full / Review v7 标准股票卡片局部修订版`  
> 更新时间：`2026-05-13`  
> 本轮重点：在完整保留此前市场总览组件规范、通用组件库注册表、Review v5 连板天梯规则与 Review v6 标准股票卡片字段口径的基础上，只修订“市场总览 / 连板天梯 / 标准股票卡片”的布局结构。
> 合并说明：本版以已交付的 Review v6 完整合并版为基线，完整保留此前已确认内容，并合并 Review v7 对 `CsqStockCompactCard` 的局部修订。Review v7 正式替代 Review v6 中“股票代码右上角 + 主体 2 行 × 3 列”的卡片结构，但不改变字段集合、连板天梯层级结构、展开/收起逻辑或其它市场总览模块。请勿用局部 delta 文档覆盖本文件。

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

| 区域 | Review v2 要求 | 本节对应组件 |
|---|---|---|
| 今日市场客观总结与主要指数 | 恢复左右 50% / 50%；左侧 5 个事实卡片 + 说明性文字卡；右侧主要指数两行，每行 5 个 | `MarketSummaryIndexSplit`、`MarketSummaryFactCard`、`MarketSummaryNoteCard`、`IndexGrid` |
| 榜单速览 | 表格展示 Top10；固定列：排名、股票、最新价、涨跌幅、换手率、量比、成交量、成交额 | `RankingTable` v2 Top10 变体 |
| 涨跌停统计与分布 | 2×2：左上 8 卡，右上今日分布结构，左下历史组合柱状图，右下昨日分布结构 | `LimitUpDistributionGrid`、`LimitUpDistributionMiniPanel` |
| 板块速览 | 左侧 4 列 × 2 行榜单矩阵；右侧 5×4 热力图跨两行 | `SectorOverviewMatrix`、`SectorHeatMap` |

以下组件和模块保持 v0.4 merged-full 规范，不因为 Review v2 主动重构：`TopMarketBar`、`Breadcrumb`、`PageHeader`、`ShortcutBar`、`MarketBreadthPanel`、`MarketStylePanel`、`TurnoverSummaryCard`、`MoneyFlowSummaryPanel`、`HorizontalLimitUpStreakLadder` 以及其它未点名组件。

---

### 16.2 MarketSummaryIndexSplit

| 项 | 说明 |
|---|---|
| 组件名称 | `MarketSummaryIndexSplit` |
| 组件用途 | 承载“今日市场客观总结 + 主要指数”的左右组合布局，恢复 Review v2 指定的 50% / 50% 首屏结构。 |
| 使用页面 | 市场总览 / `market-overview-v1.2.html`。 |
| 输入字段 / Props | `summary`、`indices`、`layout`、`loading`、`error`、`onIndexClick`、`onFactClick`。 |
| 与 API 字段的映射 | `marketSummary`、`indices[]`、`tradingDay.tradeDate`、`dataStatus[]`。 |
| 视觉结构 | 左右两栏各占 50%。左侧为标题 + 5 个事实卡片 + 说明性文字卡片；右侧为标题 + `IndexGrid`，固定两行，每行 5 个指数卡。 |
| 响应式降级 | 桌面宽度 ≥ 1280px：50% / 50%；1024–1279px：仍保持两栏但压缩卡片；<1024px：上下堆叠。桌面端禁止改成两个独占整行模块。 |
| 交互行为 | 左侧事实卡 hover 展示口径 Tooltip；点击事实卡下钻到对应模块或榜单；右侧指数卡点击进入指数详情页。 |
| 状态 | default、hover、active、selected、disabled、loading、empty、error 均沿用通用状态模型。loading 时左侧 5 卡骨架 + 右侧 10 指数卡骨架；error 时单侧异常不拖垮另一侧。 |
| 涨跌色规则 | 左侧事实卡按 `semanticType` 着色；右侧指数点位、涨跌额、涨跌幅严格红涨绿跌，平盘白色或灰白。 |
| 备注 | 本组件只调整今日总结与指数组合，不改变 TopMarketBar、PageHeader、ShortcutBar。 |

```ts
interface MarketSummaryIndexSplitProps {
  summary: {
    title: string;
    facts: MarketSummaryFactCardProps[];
    note: MarketSummaryNoteCardProps;
    tradeDate: string;
    dataStatus?: DataStatusMeta;
  };
  indices: IndexCardProps[];
  layout?: 'half-half';
  loading?: boolean;
  error?: ErrorStateProps | null;
  onIndexClick?: (indexCode: string) => void;
  onFactClick?: (fact: MarketSummaryFactCardProps) => void;
}
```

### 16.3 MarketSummaryFactCard

| 项 | 说明 |
|---|---|
| 组件名称 | `MarketSummaryFactCard` |
| 组件用途 | 今日市场客观总结中的事实指标卡，固定用于展示 5 个核心事实指标。 |
| Props | `title`、`value`、`unit`、`change`、`semanticType`、`tooltip`、`route`、`disabled`。 |
| API 映射 | 可来自 `breadth`、`turnover`、`moneyFlow`、`limitUp` 等客观事实字段，也可由 `marketSummary.facts[]` 直接返回。 |
| 视觉结构 | 小型数字卡：标题、主值、单位、变化值或说明。五张卡建议一行 5 个或在左栏内 3+2 排布。 |
| hover 状态 | hover 时显示指标口径 Tooltip，卡片边框和背景轻微提亮。 |
| 涨跌色规则 | `semanticType=up/limitUp/inflow/positive` 使用红；`down/limitDown/outflow/negative` 使用绿；`flat/neutral` 使用白色或灰白。 |
| 禁止事项 | 不输出“适合买入”“情绪升温”“风险下降”等主观结论。 |

```ts
type MarketSummaryFactSemanticType =
  | 'up' | 'down' | 'flat'
  | 'limitUp' | 'limitDown'
  | 'inflow' | 'outflow'
  | 'positive' | 'negative'
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

### 16.4 MarketSummaryNoteCard

| 项 | 说明 |
|---|---|
| 组件名称 | `MarketSummaryNoteCard` |
| 组件用途 | 今日市场客观总结左侧下方说明性文字卡片，用于放置客观事实摘要或数据口径说明。 |
| Props | `title`、`text`、`maxLength`、`helpTooltip`、`dataScopeNote`、`tone`。 |
| API 映射 | `marketSummary.summaryText`、`marketSummary.note`、`marketSummary.dataScopeNote`，也可由 ViewModel 基于客观字段生成。 |
| 文案长度限制 | 建议 60–90 个中文字符；超过后截断，并通过 HelpTooltip 展示完整说明。 |
| 视觉结构 | 弱背景、弱边框、小字号，位于 5 个事实卡下方。 |
| HelpTooltip | 支持，但只用于口径说明，不承载长篇指标字典。 |
| 禁止事项 | 不得输出主观交易建议、仓位建议、明日预测、看多看空。 |

```ts
interface MarketSummaryNoteCardProps {
  title?: string;
  text: string;
  maxLength?: number;
  helpTooltip?: string;
  dataScopeNote?: string;
  tone?: 'neutral' | 'info' | 'warning';
}
```

### 16.5 IndexGrid

| 项 | 说明 |
|---|---|
| 组件名称 | `IndexGrid` |
| 组件用途 | 在 `MarketSummaryIndexSplit` 右侧展示主要指数，两行、每行 5 个。 |
| Props | `items`、`columns`、`rows`、`minCardWidth`、`onIndexClick`、`placeholderStrategy`。 |
| API 映射 | `indices[]`，字段同 `IndexCard`。 |
| 固定布局 | 两行 × 五列，共 10 个位置。 |
| 指数数量不足 | 少于 10 个时用 `--` 占位卡补足，避免网格塌陷；占位卡不点击。 |
| 指数数量超出 | 超过 10 个时首页只展示前 10 个，剩余进入指数详情或更多指数列表；本区域不得横向滚动。 |
| IndexCard 最小宽度 | 建议 ≥ 108px；低于该宽度时隐藏成交额和趋势线，只保留指数名、点位、涨跌幅。 |
| 涨跌色规则 | 点位、涨跌额、涨跌幅、小趋势严格红涨绿跌，平盘白色或灰白。 |
| 禁止事项 | 不得改成一行、独占整行或横向滚动。 |

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

### 16.6 RankingTable：Review v2 Top10 变体

| 项 | 说明 |
|---|---|
| 组件名称 | `RankingTable` / `RankingTable.Top10` |
| 组件用途 | 榜单速览 Top10 表格，补全行情观察字段，支持个股下钻。 |
| Top 数量 | 首页固定展示 Top10。少于 10 行时保留表格高度并显示空行占位；多于 10 行时仅展示前 10。 |
| 固定列顺序 | `排名｜股票｜最新价｜涨跌幅｜换手率｜量比｜成交量｜成交额`。 |
| 半宽容器策略 | 在资金流向｜榜单速览二等分布局中仍需可读；压缩股票列为名称+代码双行；成交量/成交额使用 displayText；不隐藏 Review v2 指定列。 |
| 列宽建议 | 排名 44px；股票 128–156px；最新价 74px；涨跌幅 72px；换手率 70px；量比 62px；成交量 86px；成交额 92px。 |
| 数字格式化 | 最新价保留 2 位；涨跌幅带 `%` 和正负号；换手率 `%`；量比 2 位；成交量和成交额优先使用 API `displayText`。 |
| 交互行为 | Tab 切换榜单；行 hover；点击股票进入个股详情；表头可排序但首页默认只排序当前 Top10。 |
| 状态 | loading：10 行骨架；empty：显示“当前榜单暂无数据”；error：局部错误 + 重试。 |
| 涨跌色规则 | 最新价、涨跌幅按 `direction` 红涨绿跌；换手率、量比、成交量、成交额默认中性色。 |
| 禁止事项 | 不得删除指定列；不得降回 Top5。 |

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

### 16.7 LimitUpDistributionGrid

| 项 | 说明 |
|---|---|
| 组件名称 | `LimitUpDistributionGrid` |
| 组件用途 | 承载 Review v2 指定的“涨跌停统计与分布”2×2 区域。 |
| Props | `summaryCards`、`todayDistribution`、`historyBars`、`previousDistribution`、`loading`、`error`、`onSectorClick`、`onCategoryClick`。 |
| API 映射 | `limitUp`、`limitUp.distribution.today`、`limitUp.distribution.previousTradeDay`、`limitUp.historyPoints`。 |
| 2×2 结构 | 左上：8 个统计卡片；右上：今日涨停板块分布 + 跌停/炸板结构；左下：历史涨跌停组合柱状图；右下：上一交易日涨停板块分布 + 跌停/炸板结构。 |
| 标签 | 右上含“今日”；右下含“上一交易日”或“昨日”；Tooltip 显示对应 `tradeDate`。 |
| 历史柱状图 | 左下嵌入 `LimitUpDownHistoryBarChart`，涨停红、跌停绿，同一日期柱组并列，支持 1个月/3个月。 |
| 状态 | loading：四块分别骨架；empty：缺少昨日数据时右下显示“上一交易日分布暂缺”；error：某块异常只影响该块。 |
| 涨跌色规则 | 涨停统计和分布红；跌停结构绿；炸板 warning；历史柱图涨停红、跌停绿。 |
| 备注 | 不得使用普通长列表式涨跌停分布。Review v3 后右上/右下子区会进一步由 `LimitUpSectorLeaderPanel` 替换，但 2×2 外层结构仍保持。 |

```ts
interface LimitUpDistributionGridProps {
  summaryCards: MarketSummaryFactCardProps[];
  todayDistribution: LimitUpDistributionMiniPanelProps | LimitUpSectorLeaderPanelProps;
  previousDistribution: LimitUpDistributionMiniPanelProps | LimitUpSectorLeaderPanelProps;
  historyBars: LimitUpDownHistoryBarChartProps;
  loading?: boolean;
  error?: ErrorStateProps | null;
  onSectorClick?: (sectorCode: string, dateType: 'today' | 'previousTradeDay') => void;
  onCategoryClick?: (categoryKey: string, dateType: 'today' | 'previousTradeDay') => void;
}
```

### 16.8 LimitUpDistributionMiniPanel

| 项 | 说明 |
|---|---|
| 组件名称 | `LimitUpDistributionMiniPanel` |
| 组件用途 | 展示今日或上一交易日的涨停板块分布 + 跌停/炸板结构，用于 v2 的 `LimitUpDistributionGrid` 右上和右下区域。 |
| Props | `dateType`、`tradeDate`、`limitUpSectorDistribution`、`limitDownStructure`、`brokenLimitStructure`、`maxItems`、`onSectorClick`、`onCategoryClick`。 |
| API 映射 | `limitUp.distribution.today.*`、`limitUp.distribution.previousTradeDay.*`。 |
| 图形表达方式 | 顶部日期标签 + 板块分布条 / 分布块；下方跌停/炸板小矩阵或双条结构；不使用普通长列表。 |
| Tooltip | hover 板块块显示板块名、涨停数、占比、代表股票；hover 跌停/炸板块显示数量、占比和口径。 |
| 点击行为 | 点击板块进入板块与榜单行情页；点击跌停/炸板结构进入对应榜单筛选。 |
| 涨跌色规则 | 涨停板块分布红；跌停结构绿；炸板 warning。 |
| Review v3 说明 | Review v3 要求用 `LimitUpSectorLeaderPanel` 替代本组件在右上/右下的具体内容。本组件仍保留用于历史追溯和其它页面复用。 |

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
  limitDownStructure: Array<{ key: string; label: string; count: number; ratio?: number }>;
  brokenLimitStructure: Array<{ key: string; label: string; count: number; ratio?: number }>;
  maxItems?: number;
  loading?: boolean;
  error?: ErrorStateProps | null;
  onSectorClick?: (sectorCode: string) => void;
  onCategoryClick?: (categoryKey: string) => void;
}
```

### 16.9 SectorOverviewMatrix

| 项 | 说明 |
|---|---|
| 组件名称 | `SectorOverviewMatrix` |
| 组件用途 | 板块速览左侧 4 列 × 2 行榜单矩阵，承载八个 Top5 榜单块。 |
| Props | `groups`、`columns`、`rows`、`topN`、`loading`、`error`、`onSectorClick`、`onLeaderStockClick`。 |
| API 映射 | `sectorOverview.industryTopGainers`、`conceptTopGainers`、`regionTopGainers`、`fundInflowTop`、`industryTopLosers`、`conceptTopLosers`、`regionTopLosers`、`fundOutflowTop`。 |
| 固定布局 | 左侧 4 列 × 2 行。上排：行业涨幅前五｜概念涨幅前五｜地域涨幅前五｜资金流入前五。下排：行业跌幅前五｜概念跌幅前五｜地域跌幅前五｜资金流出前五。 |
| 每个榜单块字段 | 排名、板块名称、涨跌幅或资金额、领涨股。资金榜展示净流入/净流出金额；涨跌榜展示涨跌幅。每块固定 Top5。 |
| 交互行为 | 点击板块进入板块与榜单行情页；点击领涨股进入个股详情；hover 行显示扩展字段。 |
| 状态 | 单榜 loading/empty/error 不影响其它榜。 |
| 涨跌色规则 | 涨幅榜红、跌幅榜绿；资金流入红、资金流出绿；榜单标题不使用红绿大色块。 |

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
```

### 16.10 SectorHeatMap

| 项 | 说明 |
|---|---|
| 组件名称 | `SectorHeatMap` |
| 组件用途 | 板块速览右侧跨两行的 5×4 板块热力图，展示 20 个板块格子。 |
| Props | `items`、`rows`、`columns`、`colorMetric`、`title`、`loading`、`error`、`onSectorClick`。 |
| API 映射 | `sectorOverview.heatMapItems[]` 或 `sectorOverview.heatMap.items[]`。 |
| 位置与尺寸 | 位于板块速览右侧，跨左侧 4×2 榜单矩阵的两行高度。不得只放在第一行。 |
| 内部结构 | 固定 5 行 × 4 列，共 20 个格子。少于 20 个用空格占位；多于 20 个只展示前 20。 |
| 每个格子字段 | 板块名称、涨跌幅、可选成交额/资金净流入、sectorType。v1.2 推荐固定 5×4。 |
| 交互行为 | hover 显示板块名、类型、涨跌幅、成交额、资金净流入、上涨/下跌成分数；点击板块下钻。 |
| 状态 | 热力图 loading/empty/error 不影响左侧榜单矩阵。 |
| 涨跌色规则 | 上涨红、下跌绿、平盘白色或灰白；颜色深浅表达涨跌幅绝对值；资金色不覆盖涨跌色。 |

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

### 16.11 Review v2 组件与 API 字段映射表

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

### 16.12 Review v2 修改摘要与验收

1. 新增 `MarketSummaryIndexSplit`，恢复今日市场客观总结与主要指数左右 50% / 50% 结构。
2. 新增 `MarketSummaryFactCard` 和 `MarketSummaryNoteCard`，规范左侧 5 个事实卡 + 说明性文字卡。
3. 新增 `IndexGrid`，规范主要指数两行，每行 5 个。
4. 修订 `RankingTable` 为 Top10 变体，固定列顺序为：排名、股票、最新价、涨跌幅、换手率、量比、成交量、成交额。
5. 新增 `LimitUpDistributionGrid` 和 `LimitUpDistributionMiniPanel`，规范涨跌停统计与分布 2×2 区域。
6. 新增 `SectorOverviewMatrix`，规范板块速览左侧 4 列 × 2 行榜单矩阵。
7. 新增 `SectorHeatMap`，规范右侧跨两行 5×4 热力图。
8. 本节仍为完整文档的一部分，不是 delta 文档；Review v2 未点名组件不主动修改。
---

## 17. HTML Review v3 → market-overview-v1.2 局部修订合并规范

> 本节为 `market-overview-html-review-v3` 的全量合并内容。它不替代前文已确认的组件规范，而是在完整保留 v0.5 merged-full 基线的前提下，只对 Review v3 明确点名的两个区域进行组件级修订。除本节列出的组件外，不主动改动 TopMarketBar、Breadcrumb、PageHeader、ShortcutBar、今日市场客观总结、主要指数、涨跌分布、市场风格、成交额总览、榜单速览、连板天梯、板块速览及其它未点名组件。

### 17.1 本轮读取文档与采用基线

| 序号 | 公共区文件 | 读取到的版本 / 状态 | 本轮用途 |
|---:|---|---|---|
| 1 | `财势乾坤/项目总说明/财势乾坤行情软件项目总说明_v_0_2.md` | `财势乾坤项目总说明 v0.2` / Review 草案 v0.2 | 继续约束产品定位、P0 范围、市场总览客观事实边界、红涨绿跌、无固定 SideNav。 |
| 2 | `财势乾坤/产品文档/市场总览产品需求文档 v0.2.md` | `市场总览产品需求文档 v0.2` / Review 草案 | 继续约束市场总览名称、归属、非目标、用户任务、页面框架。 |
| 3 | `财势乾坤/设计/02-market-overview-page-design.md` | `市场总览页面设计文档 v0.1` / `market-overview-v1.html` 基线 | 作为页面设计基线，Review v3 不主动重构非点名区域。 |
| 4 | `财势乾坤/设计/03-design-tokens.md` | `Design Token 与视觉规范 v0.2.6` | 采用 Review v3 相关的三段式涨停结构、单型资金净流向饼图、资金模块左右布局 Token 约束。 |
| 5 | `财势乾坤/设计/04-component-guidelines.md` | `P0 组件库与交互组件方案 v0.5 merged-full` | 本文件的修订基线，完整保留此前内容，只追加 Review v3 局部修订。 |
| 6 | `财势乾坤/数据字典与API文档/market-overview-api-v0.5.md` | `市场总览 API 草案 v0.5` / 市场总览开发落地基线 | 作为组件 Props 与 API 字段映射依据。 |
| 7 | `财势乾坤/review/market-overview-html-review-v3.pdf` | `市场总览页review-v3` | 原始 Review 反馈依据。 |
| 8 | `财势乾坤/review/market-overview-html-review-v3-总控解读与变更单.md` | `市场总览 HTML Review v3｜总控解读与变更单` / 产品总控解读草案 | 本轮直接变更单，规定只处理两个点名区域。 |

本轮未能读取但应读取的文档：无。  
本轮是否继续：是。

---

### 17.2 本轮修订边界

#### 17.2.1 允许修改区域

| 区域 | Review v3 要求 | 本节对应组件 |
|---|---|---|
| 涨跌停统计与分布中的今日/昨日同类区域 | 将原“涨停板块分布 + 跌停/炸板结构”替换为“三段式：涨停板块分布｜领涨股｜涨停表现”。今日与昨日共用同一套组件。 | `LimitUpSectorLeaderPanel`、`LimitUpSectorBars`、`LimitUpLeaderStockList`、`LimitUpPerformanceList` |
| 大盘资金流向模块内部 | 增加一个“单型资金净流向结构饼图”；不做两个饼图；模块内部改为左饼图 + 右趋势图。 | `OrderSizeNetPieChart`、`MoneyFlowNetStructurePanel` |

#### 17.2.2 禁止主动修改区域

以下组件和模块本轮保持 v0.5 merged-full 规范，不做主动改动：

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
- `MarketSummaryIndexSplit`
- `MarketSummaryFactCard`
- `MarketSummaryNoteCard`
- `IndexGrid`
- `MarketBreadthPanel`
- `DistributionChart`
- `HistoryTrendChart`
- `MarketStylePanel`
- `MarketStyleTrendChart`
- `TurnoverSummaryCard`
- `IntradayTurnoverChart`
- `RankingTable`
- `LimitUpDistributionGrid` 的 2×2 外层结构
- `LimitUpDownHistoryBarChart`
- `HorizontalLimitUpStreakLadder`
- `SectorOverviewMatrix`
- `SectorHeatMap`
- 页面整体主题、全局字体、页面整体布局顺序、与 Review v3 无关的 Mock 数据结构

---

### 17.3 LimitUpSectorLeaderPanel

| 项 | 说明 |
|---|---|
| 组件名称 | `LimitUpSectorLeaderPanel` |
| 组件用途 | 替代原“涨停板块分布 + 跌停/炸板结构”，用于表达“板块涨停集中度 → 领涨股 → 个股涨停表现”的联动关系。 |
| 使用位置 | `LimitUpDistributionGrid` 的右上“今日”区域和右下“上一交易日 / 昨日”区域。 |
| 是否市场总览 P0 必需 | 是，Review v3 点名。 |
| 固定结构 | 三段式横向结构：`涨停板块分布｜领涨股｜涨停表现`。三列标题必须固定，不能改为“跌停/炸板结构”。 |
| 输入字段 / Props | `dateType`、`tradeDate`、`sectors`、`leaderStocks`、`performanceItems`、`selectedSectorCode`、`selectedStockCode`、`loading`、`error`、`onSectorHover`、`onSectorClick`、`onStockHover`、`onStockClick`。 |
| 数据结构 | 左侧由 `LimitUpSectorBars` 渲染，中间由 `LimitUpLeaderStockList` 渲染，右侧由 `LimitUpPerformanceList` 渲染。 |
| 默认选中逻辑 | 默认选中 `limitUpCount` 最大的板块；若并列，按 API 返回顺序选第一个；若 `selectedSectorCode` 由外部传入，则以外部值为准。默认选中板块内 `rank=1` 的领涨股。 |
| hover / click 交互 | hover 左侧板块时可临时预览中间/右侧数据；click 左侧板块时固定选中并触发板块下钻或状态更新；hover 中间股票时右侧高亮对应表现；click 中间股票进入个股详情。 |
| 点击板块跳转 | 点击板块进入板块与榜单行情页，携带 `sectorCode`、`sectorType`、`tradeDate`、`limitType=LIMIT_UP`。 |
| 点击领涨股跳转 | 点击股票进入个股详情页，携带 `stockCode`、`tradeDate`。 |
| 状态 | default：三列完整展示；hover：板块条、股票行、表现项高亮；active：点击压暗；selected：当前板块/股票使用品牌描边或弱底色；disabled：不可下钻项置灰；loading：三列骨架；empty：显示“暂无涨停板块领涨股数据”；error：局部错误和重试，不影响左上统计卡与左下历史柱图。 |
| 涨跌色规则 | 涨停相关数量、涨停板块条使用红色体系；领涨股最新价/涨跌幅按红涨绿跌；表现标签如“3连板”“7天5板”使用红色弱背景；不再使用跌停绿色结构块。 |
| 与 API 字段映射 | `limitUp.todayDistribution.sectorLeaderPanel`、`limitUp.previousTradeDayDistribution.sectorLeaderPanel`，或 ViewModel 从 `limitUpDistribution`、`limitUp`、`streakLadder`、`stockLeaderboards` 派生。 |
| 与 Design Token 映射 | `--cs-color-market-up`、`--cs-color-market-up-bg`、`--cs-color-market-up-border`、`--cs-color-surface-card`、`--cs-color-surface-card-hover`、`--cs-color-border-subtle`、`--cs-color-brand-accent`、`--cs-font-family-number`、`--cs-shadow-tooltip`。 |
| 备注 | 用户草图中的右侧残留数字不进入组件设计，不作为字段、不作为视觉占位、不作为 Mock 数据。 |

```ts
interface LimitUpSectorLeaderPanelProps {
  dateType: 'today' | 'previousTradeDay';
  tradeDate: string;
  title?: string;
  sectors: LimitUpSectorBarItem[];
  leaderStocks: LimitUpLeaderStockItem[];
  performanceItems: LimitUpPerformanceItem[];
  selectedSectorCode?: string;
  selectedStockCode?: string;
  loading?: boolean;
  error?: ErrorStateProps | null;
  emptyText?: string;
  onSectorHover?: (sector: LimitUpSectorBarItem) => void;
  onSectorClick?: (sector: LimitUpSectorBarItem) => void;
  onStockHover?: (stock: LimitUpLeaderStockItem) => void;
  onStockClick?: (stock: LimitUpLeaderStockItem) => void;
}
```

---

### 17.4 LimitUpSectorBars

| 项 | 说明 |
|---|---|
| 组件名称 | `LimitUpSectorBars` |
| 组件用途 | `LimitUpSectorLeaderPanel` 左侧“涨停板块分布”，展示涨停数量集中在哪些板块。 |
| 使用位置 | 今日 / 昨日 `LimitUpSectorLeaderPanel` 左列。 |
| 是否市场总览 P0 必需 | 是，Review v3 点名。 |
| 输入字段 / Props | `sectors`、`selectedSectorCode`、`maxItems`、`onSectorHover`、`onSectorClick`。 |
| 每个 sector 字段 | `sectorCode`、`sectorName`、`sectorType`、`limitUpCount`、`ratio`、`selected`。 |
| 视觉结构 | 使用水平分布条，不使用普通长列表。左侧板块名，中间红色分布条，右侧涨停数量。条长按 `limitUpCount` 或 `ratio` 归一化。 |
| 默认排序 | 按 `limitUpCount` 降序；相同数量按 API 顺序。 |
| hover 行为 | hover 某板块时分布条高亮，Tooltip 显示板块名称、类型、涨停数量、占比、交易日。 |
| click 行为 | click 某板块触发 `onSectorClick`；若业务设计为选中而非直接跳转，则由页面层决定是否跳转。组件只暴露事件。 |
| 状态 | default：显示分布条；hover：条和边框提亮；selected：使用品牌描边或弱底色；loading：分布条骨架；empty：显示“暂无涨停板块分布”；error：显示错误块。 |
| 涨跌色规则 | 全部为涨停板块分布，主色使用上涨红；不使用绿色。 |
| 与 API 字段映射 | `sectorLeaderPanel.sectors[]`；如 API 暂未直接返回，可从 `limitUp.distribution.today.limitUpSectorDistribution[]` / `previousTradeDay` 映射。 |
| 与 Design Token 映射 | `--cs-color-market-up`、`--cs-color-market-up-bg`、`--cs-color-market-up-border`、`--cs-color-text-primary`、`--cs-color-text-secondary`、`--cs-font-family-number`。 |
| 备注 | `ratio` 可由 API 返回，也可前端按 `limitUpCount / sum(limitUpCount)` 计算；口径应由 API 文档明确。 |

```ts
interface LimitUpSectorBarItem {
  sectorCode: string;
  sectorName: string;
  sectorType: 'INDUSTRY' | 'CONCEPT' | 'REGION' | string;
  limitUpCount: number;
  ratio?: number;
  selected?: boolean;
}

interface LimitUpSectorBarsProps {
  sectors: LimitUpSectorBarItem[];
  selectedSectorCode?: string;
  maxItems?: number;
  loading?: boolean;
  emptyText?: string;
  onSectorHover?: (sector: LimitUpSectorBarItem) => void;
  onSectorClick?: (sector: LimitUpSectorBarItem) => void;
}
```

---

### 17.5 LimitUpLeaderStockList

| 项 | 说明 |
|---|---|
| 组件名称 | `LimitUpLeaderStockList` |
| 组件用途 | `LimitUpSectorLeaderPanel` 中间“领涨股”，展示当前选中涨停板块中的代表性涨停股。 |
| 使用位置 | 今日 / 昨日 `LimitUpSectorLeaderPanel` 中列。 |
| 是否市场总览 P0 必需 | 是，Review v3 点名。 |
| 输入字段 / Props | `stocks`、`selectedStockCode`、`maxItems`、`onStockHover`、`onStockClick`。 |
| 每个 stock 字段 | `stockCode`、`stockName`、`latestPrice`、`changePct`、`sectorName`、`rank`。 |
| 视觉结构 | 高密度股票列表；每行展示排名、股票名称/代码、最新价、涨跌幅。空间不足时股票名称与代码上下两行，数字右对齐。 |
| 默认排序 | 按 `rank` 升序；rank 缺失时按涨跌幅、连板强度或 API 顺序。 |
| hover 行为 | hover 股票行时高亮，并在右侧 `LimitUpPerformanceList` 高亮对应股票表现。Tooltip 显示所属板块、最新价、涨跌幅、排名。 |
| click 行为 | 点击股票进入个股详情页，携带 `stockCode`、`tradeDate`。 |
| 状态 | default：显示股票列表；hover：行背景提亮；selected：当前股票使用品牌描边或弱底色；loading：行骨架；empty：显示“当前板块暂无领涨股”；error：显示错误块。 |
| 涨跌色规则 | 最新价和涨跌幅按 `changePct` / `direction` 红涨绿跌；涨停股通常为红色，但仍应保留 direction 字段兜底。 |
| 与 API 字段映射 | `sectorLeaderPanel.leaderStocks[]`。如 API 暂缺，可由 `limitUp` 明细、`streakLadder` 或涨停榜按板块过滤派生。 |
| 与 Design Token 映射 | `--cs-color-table-row-hover-bg`、`--cs-color-market-up/down/flat`、`--cs-font-family-number`、`--cs-color-brand-accent-border`。 |
| 备注 | 领涨股列表不是交易建议，不显示“推荐”“买入”“强机会”等字样。 |

```ts
interface LimitUpLeaderStockItem {
  stockCode: string;
  stockName: string;
  latestPrice: number | null;
  changePct: number | null;
  sectorName: string;
  rank: number;
  direction?: Direction;
}

interface LimitUpLeaderStockListProps {
  stocks: LimitUpLeaderStockItem[];
  selectedStockCode?: string;
  maxItems?: number;
  loading?: boolean;
  emptyText?: string;
  onStockHover?: (stock: LimitUpLeaderStockItem) => void;
  onStockClick?: (stock: LimitUpLeaderStockItem) => void;
}
```

---

### 17.6 LimitUpPerformanceList

| 项 | 说明 |
|---|---|
| 组件名称 | `LimitUpPerformanceList` |
| 组件用途 | `LimitUpSectorLeaderPanel` 右侧“涨停表现”，展示领涨股的短线涨停强度和封板事实。 |
| 使用位置 | 今日 / 昨日 `LimitUpSectorLeaderPanel` 右列。 |
| 是否市场总览 P0 必需 | 是，Review v3 点名。 |
| 输入字段 / Props | `stocks`、`selectedStockCode`、`showSealInfo`。 |
| 每项字段 | `stockCode`、`stockName`、`streakLabel`、`recentLimitText`、可选 `firstLimitTime`、`openTimes`、`sealedAmount`。 |
| 视觉结构 | 高密度表现列表。左侧股票名或与中列对齐的股票缩写，右侧展示 `streakLabel` 与 `recentLimitText` 标签；可选小字展示首次封板时间、开板次数、封单金额。 |
| hover 行为 | hover 表现项时高亮对应股票，与中列联动；Tooltip 展示完整封板信息。 |
| click 行为 | 右侧表现项不强制独立跳转；如实现点击，应进入同一股票详情页，与中列点击行为一致。 |
| 状态 | default：显示表现标签；hover：表现项高亮；selected：对应中列选中股票高亮；loading：标签骨架；empty：显示“暂无涨停表现”；error：显示错误块。 |
| 涨跌色规则 | `streakLabel`、`recentLimitText` 使用涨停红弱背景；封单金额正向使用红色；开板次数使用中性色或 warning，不使用绿色表达风险。 |
| 与 API 字段映射 | `sectorLeaderPanel.leaderStocks[]` 中的 `streakLabel`、`recentLimitText`、`firstLimitTime`、`openTimes`、`sealedAmount`；也可由涨停明细字段派生。 |
| 与 Design Token 映射 | `--cs-color-market-up`、`--cs-color-market-up-bg`、`--cs-color-warning`、`--cs-color-text-secondary`、`--cs-radius-pill`、`--cs-font-family-number`。 |
| 备注 | 用户草图右侧残留数字不进入该组件设计，不作为字段、不作为排序、不作为 UI 标记。 |

```ts
interface LimitUpPerformanceItem {
  stockCode: string;
  stockName: string;
  streakLabel: string;       // 例如：3连板
  recentLimitText: string;   // 例如：7天5板
  firstLimitTime?: string | null;
  openTimes?: number | null;
  sealedAmount?: number | null;
  sealedAmountDisplayText?: string;
}

interface LimitUpPerformanceListProps {
  stocks: LimitUpPerformanceItem[];
  selectedStockCode?: string;
  showSealInfo?: boolean;
  loading?: boolean;
  emptyText?: string;
}
```

---

### 17.7 OrderSizeNetPieChart

| 项 | 说明 |
|---|---|
| 组件名称 | `OrderSizeNetPieChart` |
| 组件用途 | 展示大盘资金流向中超大单、大单、中单、小单四类单型资金净额结构。 |
| 使用位置 | `MoneyFlowNetStructurePanel` 左侧。 |
| 是否市场总览 P0 必需 | 是，Review v3 点名。 |
| 输入字段 / Props | `items`、`totalNetAmount`、`unit`、`tooltipFormatter`、`loading`、`error`。 |
| 每个 item 字段 | `orderSize`、`orderSizeName`、`netAmount`、`netAmountRate`、`absAmount`、`direction`。 |
| 饼块面积规则 | 按 `absAmount` 计算饼块面积：`absAmount / sum(absAmount)`。不得用正负号抵消后的总净额作为面积。 |
| 颜色规则 | `direction=inflow` 用红色；`direction=outflow` 用绿色；`direction=flat` 用白色或灰白色。 |
| Tooltip | 显示单型名称、净额、净占比、结构占比。正数红色，负数绿色，零值灰白。 |
| 视觉结构 | 单个饼图或环形图，图例列出超大单/大单/中单/小单。图例数值右对齐。 |
| hover 行为 | hover 饼块时突出该块，并同步高亮图例。 |
| click 行为 | 可选：点击单型进入资金流详情或筛选资金榜；如未实现详情页，点击只高亮。 |
| 状态 | default：饼图 + 图例；hover：饼块和图例高亮；selected：选中单型描边；loading：饼图骨架；empty：显示“暂无单型资金净额结构”；error：显示错误块。 |
| 与 API 字段映射 | `moneyFlow.orderSizeNetStructure.items[]`；若 API 暂未返回该对象，可由 `moneyFlow.superLargeOrderNetInflow`、`largeOrderNetInflow`、`mediumOrderNetInflow`、`smallOrderNetInflow` 适配。 |
| 与 Design Token 映射 | `--cs-color-market-up`、`--cs-color-market-down`、`--cs-color-market-flat-strong`、`--cs-color-chart-tooltip-bg`、`--cs-color-chart-tooltip-border`、`--cs-font-family-number`。 |
| 备注 | 不使用两个“流入/流出”饼图，因为当前数据是各单型净额，不是真实流入额和流出额拆分。组件文案推荐“单型资金净流向”或“单型净额结构”，不推荐“流入结构 / 流出结构”。 |

```ts
type OrderSize = 'superLarge' | 'large' | 'medium' | 'small';
type OrderSizeDirection = 'inflow' | 'outflow' | 'flat';

interface OrderSizeNetPieItem {
  orderSize: OrderSize;
  orderSizeName: '超大单' | '大单' | '中单' | '小单';
  netAmount: number | null;
  netAmountRate?: number | null;
  absAmount: number;
  direction: OrderSizeDirection;
  displayText?: string;
}

interface OrderSizeNetPieChartProps {
  items: OrderSizeNetPieItem[];
  totalNetAmount?: number | null;
  unit?: string;
  loading?: boolean;
  error?: ErrorStateProps | null;
  tooltipFormatter?: (item: OrderSizeNetPieItem) => React.ReactNode;
  onItemClick?: (item: OrderSizeNetPieItem) => void;
}
```

#### 17.7.1 ViewModel 适配建议

```ts
function toOrderSizeNetPieItems(moneyFlow: MoneyFlowSummary): OrderSizeNetPieItem[] {
  const raw = [
    { orderSize: 'superLarge', orderSizeName: '超大单', netAmount: moneyFlow.superLargeOrderNetInflow },
    { orderSize: 'large', orderSizeName: '大单', netAmount: moneyFlow.largeOrderNetInflow },
    { orderSize: 'medium', orderSizeName: '中单', netAmount: moneyFlow.mediumOrderNetInflow },
    { orderSize: 'small', orderSizeName: '小单', netAmount: moneyFlow.smallOrderNetInflow },
  ] as const;

  return raw.map((item) => ({
    ...item,
    absAmount: Math.abs(item.netAmount ?? 0),
    direction:
      (item.netAmount ?? 0) > 0 ? 'inflow' :
      (item.netAmount ?? 0) < 0 ? 'outflow' :
      'flat',
  }));
}
```

---

### 17.8 MoneyFlowNetStructurePanel

| 项 | 说明 |
|---|---|
| 组件名称 | `MoneyFlowNetStructurePanel` |
| 组件用途 | 组织大盘资金流向模块内部的“左侧单型资金净流向饼图 + 右侧历史资金流向趋势图”。 |
| 使用位置 | 大盘资金流向模块内部，替换原先上下堆叠式空间安排。 |
| 是否市场总览 P0 必需 | 是，Review v3 点名。 |
| 输入字段 / Props | `pieItems`、`totalNetAmount`、`historyPoints`、`rangeType`、`loading`、`error`、`onRangeChange`。 |
| 左右布局 | 左侧为 `OrderSizeNetPieChart`，右侧为既有 `MoneyFlowHistoryChart`。建议比例为 `38% / 62%`，可在 35/65 到 42/58 范围内微调。 |
| 高度约束 | 不改变大盘资金流向模块整体高度；只调整模块内部饼图、趋势图、图例和间距。 |
| 空间约束 | 不影响右侧榜单速览结构；不改变“大盘资金流向 ｜ 榜单速览”二等分行布局。 |
| 趋势图规则 | 右侧趋势图沿用既有 `MoneyFlowHistoryChart`：主趋势线白色，0 轴居中，Tooltip 中正值红、负值绿，支持 1个月/3个月切换。 |
| 交互行为 | 饼图 hover 高亮单型和 Tooltip；趋势图 hover 显示 crosshair 和 Tooltip；RangeSwitch 仅刷新趋势图历史区间，不改变饼图今日结构。 |
| 状态 | default：左饼图右趋势图；hover：各自子组件高亮；selected：选中单型时饼图图例高亮；loading：左饼图骨架 + 右图表骨架；empty：饼图为空时保留右趋势图，趋势图为空时保留饼图；error：子组件局部错误，不拖垮整个资金模块。 |
| 涨跌色规则 | 饼图按净额方向红/绿/灰；趋势图主线白色，Tooltip 正红负绿；总净额卡仍按正红负绿。 |
| 与 API 字段映射 | `moneyFlow.orderSizeNetStructure.items[]`、`moneyFlow.todayNetInflowAmount`、`moneyFlow.historyPoints[]`；兼容 v0.5 已有 `superLargeOrderNetInflow/largeOrderNetInflow/mediumOrderNetInflow/smallOrderNetInflow` 字段。 |
| 与 Design Token 映射 | `--cs-color-market-up/down/flat`、`--cs-color-trend-moneyflow-main`、`--cs-color-chart-zero-axis`、`--cs-color-chart-grid`、`--cs-color-chart-tooltip-bg`、`--cs-space-12/16`。 |
| 备注 | 本组件只调整大盘资金流向模块内部布局，不改变成交额总览、榜单速览、页面整体顺序。 |

```ts
interface MoneyFlowNetStructurePanelProps {
  pieItems: OrderSizeNetPieItem[];
  totalNetAmount?: number | null;
  historyPoints: HistoricalMoneyFlowPoint[];
  rangeType: '1m' | '3m';
  unit?: string;
  loading?: boolean;
  error?: ErrorStateProps | null;
  onRangeChange?: (rangeType: '1m' | '3m') => void;
  onPieItemClick?: (item: OrderSizeNetPieItem) => void;
}
```

---

### 17.9 Review v3 组件与 API 字段映射表

| Review v3 区域 | 组件 | API 字段 / ViewModel 字段 | 字段需求 |
|---|---|---|---|
| 今日涨停板块分布 + 领涨股 + 涨停表现 | `LimitUpSectorLeaderPanel` | `limitUp.todayDistribution.sectorLeaderPanel` | `tradeDate/selectedSectorCode/sectors[]/leaderStocks[]` |
| 昨日涨停板块分布 + 领涨股 + 涨停表现 | `LimitUpSectorLeaderPanel` | `limitUp.previousTradeDayDistribution.sectorLeaderPanel` | 与 today 同构，仅 `dateType` 和 `tradeDate` 不同 |
| 涨停板块分布 | `LimitUpSectorBars` | `sectorLeaderPanel.sectors[]` | `sectorCode/sectorName/sectorType/limitUpCount/ratio/selected` |
| 领涨股 | `LimitUpLeaderStockList` | `sectorLeaderPanel.leaderStocks[]` | `stockCode/stockName/latestPrice/changePct/sectorName/rank` |
| 涨停表现 | `LimitUpPerformanceList` | `sectorLeaderPanel.leaderStocks[]` 或 `performanceItems[]` | `stockCode/stockName/streakLabel/recentLimitText/firstLimitTime/openTimes/sealedAmount` |
| 单型资金净流向饼图 | `OrderSizeNetPieChart` | `moneyFlow.orderSizeNetStructure.items[]` | `orderSize/orderSizeName/netAmount/netAmountRate/absAmount/direction` |
| 大盘资金流左右结构 | `MoneyFlowNetStructurePanel` | `moneyFlow.orderSizeNetStructure`、`moneyFlow.historyPoints[]` | 左饼图 + 右既有资金历史趋势图 |

---

### 17.10 对 02 market-overview-v1.2.html 的组件使用建议

1. 只改 Review v3 点名区域，不改其它区域。
2. 在“涨跌停统计与分布”右上区域，将原“今日涨停板块分布 + 跌停/炸板结构”替换为 `LimitUpSectorLeaderPanel(dateType='today')`。
3. 在“涨跌停统计与分布”右下区域，将原“昨日涨停板块分布 + 跌停/炸板结构”替换为 `LimitUpSectorLeaderPanel(dateType='previousTradeDay')`。
4. 两个 `LimitUpSectorLeaderPanel` 的三列标题固定为：`涨停板块分布｜领涨股｜涨停表现`。
5. 删除跌停/炸板结构在这两个子区域中的展示，但不要删除左上 8 个统计卡、左下历史涨跌停柱图，也不要修改 2×2 外层布局。
6. 不使用用户草图中的右侧残留数字。
7. 大盘资金流向模块内部改为 `MoneyFlowNetStructurePanel`。
8. `MoneyFlowNetStructurePanel` 左侧渲染一个 `OrderSizeNetPieChart`，右侧沿用既有 `MoneyFlowHistoryChart`。
9. 不显示两个饼图；不使用“流入结构 / 流出结构”文案；推荐标题为“单型资金净流向”。
10. 不改变大盘资金流向模块所在行的外部布局，不影响右侧榜单速览。
11. 饼图面积按 `absAmount`，颜色按净额正负；正红、负绿、零灰白。
12. 趋势图仍使用已确认的白色主线、0 轴居中和 Tooltip 正红负绿规则。

---

### 17.11 对 04 API 的字段需求

| 字段需求 | 必要性 | 说明 |
|---|---:|---|
| `limitUp.todayDistribution.sectorLeaderPanel` | 必需 | 今日三段式组件数据根对象。 |
| `limitUp.previousTradeDayDistribution.sectorLeaderPanel` | 必需 | 上一交易日三段式组件数据根对象，与 today 同构。 |
| `sectorLeaderPanel.tradeDate` | 必需 | 当前区域对应交易日。 |
| `sectorLeaderPanel.selectedSectorCode` | 建议 | 默认选中的板块代码。若不返回，前端按 `limitUpCount` 最大项计算。 |
| `sectorLeaderPanel.sectors[]` | 必需 | `LimitUpSectorBars` 数据源。 |
| `sectorLeaderPanel.sectors[].sectorCode` | 必需 | 板块代码。 |
| `sectorLeaderPanel.sectors[].sectorName` | 必需 | 板块名称。 |
| `sectorLeaderPanel.sectors[].sectorType` | 必需 | 行业 / 概念 / 地域。 |
| `sectorLeaderPanel.sectors[].limitUpCount` | 必需 | 板块涨停数量。 |
| `sectorLeaderPanel.sectors[].ratio` | 建议 | 板块涨停占比。 |
| `sectorLeaderPanel.leaderStocks[]` | 必需 | 领涨股和涨停表现共同数据源。 |
| `leaderStocks[].stockCode` | 必需 | 股票代码。 |
| `leaderStocks[].stockName` | 必需 | 股票名称。 |
| `leaderStocks[].latestPrice` | 必需 | 最新价。 |
| `leaderStocks[].changePct` | 必需 | 涨跌幅。 |
| `leaderStocks[].sectorName` | 建议 | 所属板块。 |
| `leaderStocks[].rank` | 必需 | 当前选中板块内排名。 |
| `leaderStocks[].streakLabel` | 必需 | 如“3连板”。 |
| `leaderStocks[].recentLimitText` | 必需 | 如“7天5板”。 |
| `leaderStocks[].firstLimitTime` | 可选 | 首次封板时间。 |
| `leaderStocks[].openTimes` | 可选 | 开板次数。 |
| `leaderStocks[].sealedAmount` | 可选 | 封单金额。 |
| `moneyFlow.orderSizeNetStructure` | 必需 | 单型资金净流向结构饼图数据根对象。 |
| `orderSizeNetStructure.totalNetAmount` | 建议 | 四类单型合计净额或主力净流入净额，口径需 API 明确。 |
| `orderSizeNetStructure.items[]` | 必需 | 饼图四类单型数组。 |
| `items[].orderSize` | 必需 | `superLarge / large / medium / small`。 |
| `items[].orderSizeName` | 必需 | `超大单 / 大单 / 中单 / 小单`。 |
| `items[].netAmount` | 必需 | 单型净流入净额。 |
| `items[].netAmountRate` | 建议 | 净占比；需明确为源字段净占比还是按绝对值结构占比。 |
| `items[].absAmount` | 必需 | 饼图面积字段，可 API 返回或前端派生。 |
| `items[].direction` | 必需 | `inflow / outflow / flat`。 |

---

### 17.12 对 01 Design Token 的依赖

Review v3 组件落地依赖 Token v0.2.6 或同等 Token，尤其：

1. 三段式涨停结构列间距 Token；
2. 涨停板块条形分布背景、填充、hover、selected 边框；
3. 领涨股列表 hover / selected 背景；
4. 涨停表现标签背景、文字、边框；
5. 单型资金净流向饼图正值红、负值绿、零值灰白；
6. 饼图 Tooltip 背景、边框、文字；
7. 饼图图例数字字体和右对齐规则；
8. 大盘资金流向模块内部左右布局间距；
9. 资金趋势图与饼图之间的分割线或弱边框；
10. 不得为 Review v3 修改全局主题、全局字体、TopMarketBar、Breadcrumb、PageHeader、ShortcutBar 的 Token。

建议 Token 命名：

```css
:root {
  --cs-color-limit-sector-bar-bg: ...;
  --cs-color-limit-sector-bar-fill: var(--cs-color-market-up);
  --cs-color-limit-sector-bar-hover-bg: ...;
  --cs-color-limit-sector-bar-selected-border: ...;

  --cs-color-limit-leader-row-hover-bg: ...;
  --cs-color-limit-leader-row-selected-bg: ...;

  --cs-color-limit-performance-tag-bg: var(--cs-color-market-up-bg);
  --cs-color-limit-performance-tag-text: var(--cs-color-market-up);
  --cs-color-limit-performance-tag-border: var(--cs-color-market-up-border);

  --cs-color-order-pie-inflow: var(--cs-color-market-up);
  --cs-color-order-pie-outflow: var(--cs-color-market-down);
  --cs-color-order-pie-flat: var(--cs-color-market-flat-strong);
  --cs-color-order-pie-stroke: ...;

  --cs-layout-moneyflow-pie-width-ratio: 0.38;
  --cs-layout-moneyflow-trend-width-ratio: 0.62;
}
```

---

### 17.13 本轮 Review v3 修改摘要

1. 将“涨跌停统计与分布”中的今日和昨日同类子模块，从“涨停板块分布 + 跌停/炸板结构”改为“三段式：涨停板块分布｜领涨股｜涨停表现”。
2. 新增 `LimitUpSectorLeaderPanel`，作为今日/昨日两个区域的统一容器。
3. 新增 `LimitUpSectorBars`，负责左侧涨停板块分布条。
4. 新增 `LimitUpLeaderStockList`，负责中间领涨股列表。
5. 新增 `LimitUpPerformanceList`，负责右侧涨停表现。
6. 新增 `OrderSizeNetPieChart`，用于大盘资金流向的单型资金净流向结构饼图。
7. 新增 `MoneyFlowNetStructurePanel`，用于大盘资金流向内部“左饼图 + 右趋势图”布局。
8. 明确不做两个“流入/流出”饼图，因为当前字段是净额，不是真实流入额/流出额拆分。
9. 明确本轮不修改 Review v3 未点名组件。

### 17.14 本轮新增或修订组件清单

| 类型 | 组件 | 处理方式 |
|---|---|---|
| 新增 | `LimitUpSectorLeaderPanel` | 新增三段式容器组件 |
| 新增 | `LimitUpSectorBars` | 新增涨停板块分布条组件 |
| 新增 | `LimitUpLeaderStockList` | 新增领涨股列表组件 |
| 新增 | `LimitUpPerformanceList` | 新增涨停表现组件 |
| 新增 | `OrderSizeNetPieChart` | 新增单型资金净流向饼图组件 |
| 新增 | `MoneyFlowNetStructurePanel` | 新增大盘资金流内部左右布局组件 |
| 修订 | `LimitUpDistributionGrid` | 只替换右上/右下子区域内容，不改变 2×2 外层结构 |
| 修订 | `MoneyFlowSummaryPanel` | 只增加内部 `MoneyFlowNetStructurePanel` 组合，不改变模块外部布局和高度目标 |

### 17.15 本轮未修改组件清单

以下组件保持 v0.5 merged-full 规范，不做主动改动：

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
- `MarketSummaryIndexSplit`
- `MarketSummaryFactCard`
- `MarketSummaryNoteCard`
- `IndexGrid`
- `IndexCard`
- `MetricCard`
- `ChangeBadge`
- `QuoteTicker`
- `MiniTrendChart`
- `MarketBreadthPanel`
- `DistributionChart`
- `HistoryTrendChart`
- `MarketStylePanel`
- `MarketStyleTrendChart`
- `TurnoverSummaryCard`
- `IntradayTurnoverChart`
- `RankingTable`
- `StockTable`
- `SortableHeader`
- `TabPanel`
- `LimitUpSummaryCard`
- `LimitUpDownHistoryBarChart`
- `HorizontalLimitUpStreakLadder`
- `SectorOverviewMatrix`
- `SectorHeatMap`
- `HelpTooltip`
- `RangeSwitch`
- `LoadingSkeleton`
- `EmptyState`
- `ErrorState`
- `DataDelayState`
- `PermissionState`

### 17.16 本轮因 Review v3 修改而被动影响的区域

```text
本轮因 Review v3 修改而被动影响的区域：
- LimitUpDistributionGrid 的右上和右下子区域
原因：原右上/右下子区域承载“涨停板块分布 + 跌停/炸板结构”，Review v3 要求替换为“涨停板块分布｜领涨股｜涨停表现”。
是否需要产品总控确认：否，属于 Review v3 明确点名区域。

本轮因 Review v3 修改而被动影响的区域：
- MoneyFlowSummaryPanel 内部布局
原因：Review v3 要求大盘资金流向内部新增单型资金净流向饼图，并改为左饼图 + 右趋势图。该修改仅发生在资金模块内部，不影响模块外部布局和右侧榜单速览。
是否需要产品总控确认：否，属于 Review v3 明确点名区域。
```

### 17.17 待产品总控确认问题

1. `sectorLeaderPanel.leaderStocks[]` 是否由 API 直接按选中板块返回，还是由前端从全量涨停个股中按 `sectorCode` 过滤？建议 API 直接返回默认板块对应列表，并支持后续下钻接口。
2. `LimitUpSectorLeaderPanel` 中 hover 板块是否只预览数据，click 才固定选中？建议 hover 预览、click 固定。
3. `recentLimitText` 的计算口径是否统一为 N 天 M 板？例如“7天5板”是否排除 ST、是否按自然日或交易日？需 API/数据字典明确。
4. `sealedAmount` 字段单位是否固定为元，还是保持来源口径并返回 `displayText`？建议 API 返回 `sealedAmountDisplayText`。
5. `orderSizeNetStructure.totalNetAmount` 应表示四类单型净额之和，还是主力净流入 `net_amount`？建议 API 明确，不让组件猜测。
6. `netAmountRate` 使用源字段净占比，还是按四类 `absAmount` 重新计算结构占比？建议同时返回 `netAmountRate` 与 `structureRatio`，组件 Tooltip 可区分展示。
7. `OrderSizeNetPieChart` 点击单型后是否需要进入资金流详情页？如 P0 暂无详情页，点击仅高亮。
8. 大盘资金流向模块内部左右比例是否固定为 38% / 62%，还是允许 35% / 65% 响应式浮动？建议桌面固定 38% / 62%，中屏降级为上下堆叠但不影响桌面 Showcase。
9. Review v3 是否允许保留原跌停/炸板结构在 Tooltip 或详情下钻中？当前规范按总控变更单：右上/右下子区域不再展示跌停/炸板结构。

### 17.18 Review v3 验收清单

| 验收项 | 要求 |
|---|---|
| 完整文档 | 本文件仍是完整 `04-component-guidelines.md`，不是 delta 文档。 |
| 修改边界 | 只新增/修订 Review v3 点名的两个区域组件。 |
| 涨停三段式 | `LimitUpSectorLeaderPanel` 可完整支撑“涨停板块分布｜领涨股｜涨停表现”。 |
| 今日/昨日复用 | 今日和昨日两个区域共用同一套三段式组件，只切换 `dateType` 和 `tradeDate`。 |
| 板块分布 | `LimitUpSectorBars` 支持 sectorCode、sectorName、sectorType、limitUpCount、ratio、selected。 |
| 领涨股 | `LimitUpLeaderStockList` 支持 stockCode、stockName、latestPrice、changePct、sectorName、rank。 |
| 涨停表现 | `LimitUpPerformanceList` 支持 streakLabel、recentLimitText、firstLimitTime、openTimes、sealedAmount。 |
| 单型资金饼图 | `OrderSizeNetPieChart` 面积按 absAmount，颜色按 direction 红/绿/灰。 |
| 资金左右布局 | `MoneyFlowNetStructurePanel` 支持左饼图、右趋势图，不改变资金模块外部布局和高度目标。 |
| 红涨绿跌 | 涨停、净流入为红；净流出为绿；平盘或零值灰白。 |
| API 映射 | 所有新增组件均有 Props 与 API 字段映射。 |
| 未授权改动 | 未修改 TopMarketBar、Breadcrumb、PageHeader、ShortcutBar、今日总结、主要指数、涨跌分布、市场风格、成交额、榜单、连板天梯、板块速览等非点名区域。 |

### 17.19 建议放置到 Google Drive 的路径

```text
财势乾坤/设计/04-component-guidelines.md
```

### 17.20 建议仓库保存路径

```text
/docs/wealth/04-component-guidelines.md
```

### 17.21 本轮输出文件下载链接

对话交付文件：

```text
sandbox:/mnt/data/review-v3-output-final/04-component-guidelines.md
```

---

## 18. HTML Review v4 → market-overview-v1.3 局部修订合并规范

> 本节为 `market-overview-html-review-v4` 的全量合并内容。它不替代前文已确认的组件规范，而是在完整保留 v0.6 merged-full 基线的前提下，只对 Review v4 明确点名的两个区域进行组件级修订。除本节列出的组件外，不主动改动 TopMarketBar、Breadcrumb、PageHeader、ShortcutBar、今日市场客观总结、主要指数、涨跌分布、市场风格、成交额总览、榜单速览、连板天梯、板块速览及其它未点名组件。

### 18.1 本轮读取文档与采用基线

| 序号 | 公共区文件 | 读取到的版本 / 状态 | 本轮用途 |
|---:|---|---|---|
| 1 | `财势乾坤/项目总说明/财势乾坤行情软件项目总说明_v_0_2.md` | `财势乾坤项目总说明 v0.2` / Review 草案 v0.2 | 继续约束产品定位、P0 范围、市场总览客观事实边界、红涨绿跌、无固定 SideNav。 |
| 2 | `财势乾坤/产品文档/市场总览产品需求文档 v0.2.md` | `市场总览产品需求文档 v0.2` / Review 草案 | 继续约束市场总览名称、归属、非目标、用户任务、页面框架。 |
| 3 | `财势乾坤/设计/02-market-overview-page-design.md` | `市场总览页面设计文档 v0.1` | 作为页面设计基线，Review v4 不主动重构非点名区域。 |
| 4 | `财势乾坤/设计/03-design-tokens.md` | `Design Token 与视觉规范 v0.2.6` | 必读新版 Token，采用 Review v4 的行式领涨股涨停表现、饼图 callout 折线、饼块白色占比文字等约束。 |
| 5 | `财势乾坤/设计/04-component-guidelines.md` | `P0 组件库与交互组件方案 v0.6 merged-full` | 本文件的修订基线，完整保留此前内容，只追加 Review v4 局部修订。 |
| 6 | `财势乾坤/数据字典与API文档/market-overview-api-v0.5.md` | `市场总览 API 草案 v0.5` / 市场总览开发落地基线 | 作为组件 Props 与 API 字段映射依据；本轮原则上不改数据 model。 |
| 7 | `财势乾坤/review/market-overview-html-review-v4.pdf` | `市场总览页review-v4` | 原始 Review 反馈依据。 |
| 8 | `财势乾坤/review/market-overview-html-review-v4-总控解读与变更单.md` | `市场总览 HTML Review v4｜总控解读与变更单` / 产品总控解读草案 | 本轮直接变更单，规定只处理两个点名区域。 |

本轮未能读取但应读取的文档：无。  
本轮是否继续：是。

---

### 18.2 本轮修订边界

#### 18.2.1 允许修改区域

| 区域 | Review v4 要求 | 本节对应组件 |
|---|---|---|
| 涨跌停统计与分布中的今日/昨日同类区域 | 将 v3 中分离的“领涨股”和“涨停表现”合并为一个行式打通模块，标题固定为“领涨股涨停表现”；一只股票对应一行涨停表现；最多显示 3 行。 | `LimitUpLeaderPerformanceTable`、修订 `LimitUpSectorLeaderPanel` |
| 大盘资金流向模块内部 | 单型资金净流向饼图使用 callout 折线标注；饼块上用白色文字展示占比；饼图中心不显示“净额结构”、`absAmount` 或任何调试字段。 | 修订 `OrderSizeNetPieChart`，新增子规范 `PieCalloutLabel`、`PieSlicePercentLabel`；`MoneyFlowNetStructurePanel` 仅沿用左右结构，不改外部布局。 |

#### 18.2.2 禁止主动修改区域

以下组件和模块本轮保持 v0.6 merged-full 规范，不做主动改动：

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
- `MarketSummaryIndexSplit`
- `MarketSummaryFactCard`
- `MarketSummaryNoteCard`
- `IndexGrid`
- `IndexCard`
- `MetricCard`
- `ChangeBadge`
- `QuoteTicker`
- `MiniTrendChart`
- `MarketBreadthPanel`
- `DistributionChart`
- `HistoryTrendChart`
- `MarketStylePanel`
- `MarketStyleTrendChart`
- `TurnoverSummaryCard`
- `IntradayTurnoverChart`
- `RankingTable`
- `StockTable`
- `SortableHeader`
- `TabPanel`
- `LimitUpSummaryCard`
- `LimitUpDistributionGrid` 的 2×2 外层结构
- `LimitUpDownHistoryBarChart`
- `HorizontalLimitUpStreakLadder`
- `SectorOverviewMatrix`
- `SectorHeatMap`
- `HelpTooltip`
- `RangeSwitch`
- `LoadingSkeleton`
- `EmptyState`
- `ErrorState`
- `DataDelayState`
- `PermissionState`
- 页面整体主题、全局字体、页面整体布局顺序、API 数据模型、与 Review v4 无关的 Mock 数据结构

---

### 18.3 LimitUpLeaderPerformanceTable

| 项 | 说明 |
|---|---|
| 组件名称 | `LimitUpLeaderPerformanceTable` |
| 组件用途 | 合并后的“领涨股涨停表现”行式组件，用于在同一行展示一只领涨股及其对应涨停表现，替代 v3 中分离的 `LimitUpLeaderStockList` + `LimitUpPerformanceList` 展示方式。 |
| 使用位置 | `LimitUpSectorLeaderPanel` 右侧；用于涨跌停统计与分布的今日区域和昨日区域。 |
| 是否市场总览 P0 必需 | 是，Review v4 点名。 |
| title | 固定为 `领涨股涨停表现`。不得拆成“领涨股”和“涨停表现”两个标题。 |
| 输入字段 / Props | `title`、`stocks`、`selectedStockCode`、`maxRows`、`showMore`、`loading`、`error`、`emptyText`、`onStockHover`、`onStockClick`、`onMoreClick`。 |
| 数据结构 | 数据 model 沿用 v3 `sectorLeaderPanel.leaderStocks[]`，不新增 API model。组件层把股票信息字段和涨停表现字段在同一行中组合展示。 |
| 行数规则 | 最多展示 3 行；每行是一只股票；超过 3 条时显示“更多”入口或省略提示，由 `showMore` 控制。 |
| 每行字段 | `rank`、`stockCode`、`stockName`、`latestPrice`、`changePct`、`streakLabel`、`recentLimitText`、可选 `firstLimitTime`、`openTimes`、`sealedAmount`。 |
| 视觉结构 | 行式高密度表格/列表。每行左侧展示排名、股票名称、股票代码、最新价、涨跌幅；右侧展示 `streakLabel`、`recentLimitText`、可选封板事实。左右信息必须在同一行视觉上打通。 |
| hover / active | hover 时整行高亮，不是只高亮股票半边或表现半边；active 时整行压暗。 |
| selected | 当 `selectedStockCode` 命中时，整行使用品牌弱背景或细描边。 |
| click | 点击股票行进入个股详情页，携带 `stockCode`、`tradeDate`。点击“更多”进入板块与榜单行情页或涨停详情页。 |
| loading | 显示 3 行骨架，每行包含股票信息骨架和表现标签骨架。 |
| empty | 显示“暂无领涨股涨停表现”，保留模块尺寸。 |
| error | 显示局部错误和重试入口，不影响左侧涨停板块分布和涨跌停大模块其它区域。 |
| 涨跌色规则 | `latestPrice`、`changePct` 按 direction 红涨绿跌；`streakLabel`、`recentLimitText` 使用涨停红弱背景；`openTimes` 使用中性或 warning，不使用绿色表达风险；平盘白色或灰白。 |
| 与 API 字段映射 | `limitUp.todayDistribution.sectorLeaderPanel.leaderStocks[]`、`limitUp.previousTradeDayDistribution.sectorLeaderPanel.leaderStocks[]`，字段包括 `stockCode`、`stockName`、`latestPrice`、`changePct`、`rank`、`streakLabel`、`recentLimitText`、`firstLimitTime`、`openTimes`、`sealedAmount`。 |
| 与 Design Token 映射 | `--cs-color-limit-leader-performance-row-bg`、`--cs-color-limit-leader-performance-row-hover-bg`、`--cs-color-limit-leader-performance-row-selected-bg`、`--cs-color-limit-performance-tag-bg`、`--cs-color-limit-performance-tag-text`、`--cs-color-limit-performance-tag-border`、`--cs-color-market-up`、`--cs-font-family-number`。 |
| 备注 | 用户草图中的右侧残留数字不进入组件设计，不作为字段、不作为排序、不作为 UI 标记。 |

```ts
interface LimitUpLeaderPerformanceRow {
  rank: number;
  stockCode: string;
  stockName: string;
  latestPrice: number | null;
  changePct: number | null;
  direction?: Direction;
  sectorName?: string;
  streakLabel: string;       // 例如：3连板、首板
  recentLimitText: string;   // 例如：7天5板、1天1板
  firstLimitTime?: string | null;
  openTimes?: number | null;
  sealedAmount?: number | null;
  sealedAmountDisplayText?: string;
}

interface LimitUpLeaderPerformanceTableProps {
  title?: '领涨股涨停表现';
  stocks: LimitUpLeaderPerformanceRow[];
  selectedStockCode?: string;
  maxRows?: 3;
  showMore?: boolean;
  loading?: boolean;
  error?: ErrorStateProps | null;
  emptyText?: string;
  onStockHover?: (stock: LimitUpLeaderPerformanceRow) => void;
  onStockClick?: (stock: LimitUpLeaderPerformanceRow) => void;
  onMoreClick?: () => void;
}
```

#### 18.3.1 行内字段排列建议

```text
┌───────────────────────────────────────────────────────────────┐
│ 1  汇川技术  300124.SZ  68.25  +10.01%  3连板  7天5板  封单3.20亿 │
│ 2  三花智控  002050.SZ  25.88  +10.00%  首板   1天1板  封单1.46亿 │
│ 3  瑞迪智驱  301596.SZ  42.16  +20.01%  2连板  2天2板  封单1.02亿 │
└───────────────────────────────────────────────────────────────┘
```

优先级：股票名称 > 涨跌幅 > 连板表现 > 近期表现 > 封板事实。空间不足时优先隐藏 `firstLimitTime`、`openTimes`、`sealedAmount` 的细节，不能隐藏股票名称、涨跌幅、`streakLabel`、`recentLimitText`。

---

### 18.4 LimitUpSectorLeaderPanel：Review v4 修订版

| 项 | 说明 |
|---|---|
| 组件名称 | `LimitUpSectorLeaderPanel` |
| 组件用途 | 表达“涨停板块分布 → 领涨股涨停表现”的联动关系。Review v4 后，不再将领涨股和涨停表现拆成两个视觉小模块。 |
| 使用位置 | `LimitUpDistributionGrid` 的右上“今日”区域和右下“上一交易日 / 昨日”区域。 |
| 是否市场总览 P0 必需 | 是，Review v3 / v4 连续点名。 |
| 固定结构 | 两段式横向结构：`涨停板块分布 ｜ 领涨股涨停表现`。 |
| 左侧 | `LimitUpSectorBars`，展示涨停板块分布。 |
| 右侧 | `LimitUpLeaderPerformanceTable`，展示当前选中板块下的领涨股涨停表现，最多 3 行。 |
| 不再使用 | 市场总览 v1.3 中不再使用 `LimitUpLeaderStockList` + `LimitUpPerformanceList` 的分离展示方式。它们可保留为历史兼容/其它页面复用组件，但不是市场总览当前展示结构。 |
| 输入字段 / Props | `dateType`、`tradeDate`、`sectors`、`leaderPerformanceRows`、`selectedSectorCode`、`selectedStockCode`、`loading`、`error`、`onSectorHover`、`onSectorClick`、`onStockHover`、`onStockClick`、`onMoreClick`。 |
| 默认选中逻辑 | 默认选中 `limitUpCount` 最大的板块；若并列，按 API 返回顺序选第一个；若外部传入 `selectedSectorCode`，以外部状态为准。右侧默认展示该板块 `rank` 前 3 的领涨股涨停表现。 |
| hover | hover 左侧板块时可预览右侧 3 行；hover 右侧股票行时整行高亮。 |
| click | 点击左侧板块可固定选中或下钻至板块与榜单行情页；点击右侧股票行进入个股详情。由页面层决定点击板块是“选中”还是“跳转”，组件只暴露事件。 |
| loading | 左侧分布条骨架 + 右侧 3 行表格骨架。 |
| empty | 若无板块分布，显示“暂无涨停板块分布”；若选中板块无领涨股，右侧显示“暂无领涨股涨停表现”。 |
| error | 左右两侧允许局部错误，不影响涨跌停统计 2×2 外层其他区域。 |
| 涨跌色规则 | 左侧涨停板块分布使用红色体系；右侧股票涨跌幅红涨绿跌；表现标签使用红色弱背景。 |
| 与 API 字段映射 | `limitUp.todayDistribution.sectorLeaderPanel.sectors[]`、`leaderStocks[]`；`limitUp.previousTradeDayDistribution.sectorLeaderPanel.sectors[]`、`leaderStocks[]`。 |
| 与 Design Token 映射 | `--cs-color-limit-sector-bar-*`、`--cs-color-limit-leader-performance-row-*`、`--cs-color-limit-performance-tag-*`、`--cs-color-market-up/down/flat`、`--cs-color-border-subtle`。 |
| 备注 | 今日和昨日两个区域共用同一套组件，只切换 `dateType`、`tradeDate` 和数据源。 |

```ts
interface LimitUpSectorLeaderPanelPropsV4 {
  dateType: 'today' | 'previousTradeDay';
  tradeDate: string;
  title?: string;
  sectors: LimitUpSectorBarItem[];
  leaderPerformanceRows: LimitUpLeaderPerformanceRow[];
  selectedSectorCode?: string;
  selectedStockCode?: string;
  loading?: boolean;
  error?: ErrorStateProps | null;
  emptyText?: string;
  onSectorHover?: (sector: LimitUpSectorBarItem) => void;
  onSectorClick?: (sector: LimitUpSectorBarItem) => void;
  onStockHover?: (stock: LimitUpLeaderPerformanceRow) => void;
  onStockClick?: (stock: LimitUpLeaderPerformanceRow) => void;
  onMoreClick?: () => void;
}
```

#### 18.4.1 Review v3 到 Review v4 的结构差异

| 版本 | 结构 | 说明 |
|---|---|---|
| Review v3 | `涨停板块分布 ｜ 领涨股 ｜ 涨停表现` | 三段式，领涨股和涨停表现是两个独立视觉小模块。 |
| Review v4 | `涨停板块分布 ｜ 领涨股涨停表现` | 两段式，右侧用一个行式组件打通股票和表现。 |

---

### 18.5 OrderSizeNetPieChart：Review v4 Callout 版

| 项 | 说明 |
|---|---|
| 组件名称 | `OrderSizeNetPieChart` |
| 组件用途 | 展示大盘资金流向中超大单、大单、中单、小单四类单型资金净额结构。Review v4 后，饼图采用 callout 折线标注样式，并在饼块上显示白色占比文字。 |
| 使用位置 | `MoneyFlowNetStructurePanel` 左侧。 |
| 是否市场总览 P0 必需 | 是，Review v3 / v4 连续点名。 |
| 输入字段 / Props | `items`、`totalNetAmount`、`unit`、`labelMode`、`showSlicePercent`、`centerMode`、`tooltipFormatter`、`loading`、`error`。 |
| 每个 item 字段 | `orderSize`、`orderSizeName`、`netAmount`、`netAmountRate`、`absAmount`、`direction`、可选 `structureRatio`、`displayText`。 |
| 饼块面积规则 | 按 `absAmount` 计算饼块面积：`absAmount / sum(absAmount)`。不得用正负抵消后的总净额作为面积。 |
| 饼块颜色规则 | `direction=inflow` 用红色；`direction=outflow` 用绿色；`direction=flat` 用白色或灰白色。 |
| 饼块占比文字 | 占比文字必须直接放在对应饼块上，使用白色文字。占比表示该饼块在整个饼图中的面积占比，建议由 `structureRatio` 或前端 `absAmount / sum(absAmount)` 计算。 |
| 外部折线标注 | 每个饼块通过折线引出 `PieCalloutLabel`。标注内容为 `orderSizeName + netAmountDisplayText`，例如 `超大单 +12.3亿`。 |
| 饼图中心 | 中心保持为空或仅作为环形留白；不得显示“净额结构”、`absAmount`、英文调试字段、总额结构等文字。 |
| Tooltip | hover 饼块显示单型名称、净额、净占比、结构占比。正数红，负数绿，零值灰白。 |
| hover / selected | hover 饼块时突出该块，并同步高亮折线标注；selected 单型可使用细描边或轻微外扩。 |
| click | 可选：点击单型后高亮该项；如 P0 暂无资金详情页，不强制跳转。 |
| loading | 饼图骨架 + callout 线骨架。 |
| empty | 显示“暂无单型资金净流向结构”。 |
| error | 显示局部错误块，不影响右侧资金趋势图。 |
| 与 API 字段映射 | `moneyFlow.orderSizeNetStructure.items[]`；兼容 `moneyFlow.superLargeOrderNetInflow`、`largeOrderNetInflow`、`mediumOrderNetInflow`、`smallOrderNetInflow` 派生。 |
| 与 Design Token 映射 | `--cs-color-order-pie-inflow`、`--cs-color-order-pie-outflow`、`--cs-color-order-pie-flat`、`--cs-color-order-pie-stroke`、`--cs-color-order-pie-callout-line`、`--cs-color-order-pie-callout-text`、`--cs-color-order-pie-slice-percent-text`、`--cs-font-family-number`。 |
| 备注 | 不使用两个“流入/流出”饼图；不使用普通 legend 替代 callout；不在中心显示文字。 |

```ts
type OrderSize = 'superLarge' | 'large' | 'medium' | 'small';
type OrderSizeDirection = 'inflow' | 'outflow' | 'flat';

type OrderSizePieLabelMode = 'callout' | 'legend';
type OrderSizePieCenterMode = 'empty' | 'none';

interface OrderSizeNetPieItem {
  orderSize: OrderSize;
  orderSizeName: '超大单' | '大单' | '中单' | '小单';
  netAmount: number | null;
  netAmountRate?: number | null;
  absAmount: number;
  structureRatio?: number | null; // 饼块面积占比，0-1；可由前端派生
  direction: OrderSizeDirection;
  displayText?: string;
}

interface OrderSizeNetPieChartProps {
  items: OrderSizeNetPieItem[];
  totalNetAmount?: number | null;
  unit?: string;
  labelMode?: OrderSizePieLabelMode; // market-overview-v1.3 固定使用 callout
  showSlicePercent?: boolean;        // market-overview-v1.3 固定 true
  centerMode?: OrderSizePieCenterMode; // market-overview-v1.3 固定 empty
  loading?: boolean;
  error?: ErrorStateProps | null;
  tooltipFormatter?: (item: OrderSizeNetPieItem) => React.ReactNode;
  onItemHover?: (item: OrderSizeNetPieItem) => void;
  onItemClick?: (item: OrderSizeNetPieItem) => void;
}
```

#### 18.5.1 饼块占比计算建议

```ts
function getStructureRatio(item: OrderSizeNetPieItem, items: OrderSizeNetPieItem[]): number {
  const totalAbsAmount = items.reduce((sum, it) => sum + Math.abs(it.absAmount ?? 0), 0);
  if (!totalAbsAmount) return 0;
  return Math.abs(item.absAmount ?? 0) / totalAbsAmount;
}
```

展示格式：

```text
42.5%
18.1%
10.7%
28.7%
```

饼块过小时可隐藏饼块内文字，但必须在 Tooltip 和 callout 中完整展示信息。隐藏阈值建议：结构占比 `< 6%` 时隐藏 slice 内文字，避免挤压重叠。

---

### 18.6 PieCalloutLabel

| 项 | 说明 |
|---|---|
| 组件名称 | `PieCalloutLabel` |
| 组件用途 | `OrderSizeNetPieChart` 的外部折线标注子组件，用折线明确说明某个饼块对应的单型名称与净额。 |
| 使用位置 | `OrderSizeNetPieChart` 外围。 |
| 输入字段 / Props | `item`、`anchorPoint`、`elbowPoint`、`labelPoint`、`placement`、`lineStyle`、`valueFormatter`。 |
| 标注内容 | `orderSizeName + netAmountDisplayText`，例如 `超大单 +12.3亿`、`大单 -5.2亿`。 |
| 折线规则 | 折线从饼块外缘引出，经过 elbow 点，末端放说明文字；说明文字可在折线上方或下方。 |
| 方向与颜色 | 折线可使用中性灰或弱金色；净额文字按正红、负绿、零灰白着色；单型名称使用主/次级文字。 |
| 避让规则 | 标注不能与饼图中心重叠，不能遮挡饼块上的白色占比文字。必要时自动调整 labelPoint 或隐藏最小扇区 label。 |
| hover 联动 | hover 标注时同步高亮饼块；hover 饼块时同步高亮标注。 |
| 与 Token 映射 | `--cs-color-order-pie-callout-line`、`--cs-color-order-pie-callout-text`、`--cs-color-market-up/down/flat`、`--cs-font-family-number`。 |

```ts
interface PiePoint {
  x: number;
  y: number;
}

interface PieCalloutLabelProps {
  item: OrderSizeNetPieItem;
  anchorPoint: PiePoint;
  elbowPoint: PiePoint;
  labelPoint: PiePoint;
  placement?: 'left' | 'right' | 'top' | 'bottom';
  lineStyle?: 'solid' | 'dashed';
  valueFormatter?: (value: number | null, item: OrderSizeNetPieItem) => string;
}
```

---

### 18.7 PieSlicePercentLabel

| 项 | 说明 |
|---|---|
| 组件名称 | `PieSlicePercentLabel` |
| 组件用途 | 在 `OrderSizeNetPieChart` 的饼块内部显示白色结构占比文字。 |
| 使用位置 | `OrderSizeNetPieChart` 饼块内部。 |
| 输入字段 / Props | `item`、`percent`、`position`、`visible`、`formatter`。 |
| 文本规则 | 使用白色文字，显示结构占比，例如 `42.5%`；不显示在饼图中心、不显示在 legend 中。 |
| 可见性规则 | 扇区过小或文字重叠时可隐藏，但 Tooltip 和 callout 必须保留完整信息。建议 `percent < 0.06` 时隐藏。 |
| 视觉规则 | 字号 10–12px；数字使用等宽字体；必要时加极弱文字阴影，提高在红/绿饼块上的可读性。 |
| 与 Token 映射 | `--cs-color-order-pie-slice-percent-text`、`--cs-font-family-number`、`--cs-shadow-pie-slice-percent-text`。 |

```ts
interface PieSlicePercentLabelProps {
  item: OrderSizeNetPieItem;
  percent: number; // 0-1
  position: PiePoint;
  visible?: boolean;
  formatter?: (percent: number) => string;
}
```

---

### 18.8 MoneyFlowNetStructurePanel：Review v4 保持外层约束

| 项 | 说明 |
|---|---|
| 组件名称 | `MoneyFlowNetStructurePanel` |
| Review v4 处理方式 | 沿用 Review v3 的“左饼图 + 右趋势图”内部布局，不改变大盘资金流向模块整体高度，不影响右侧榜单速览。本轮只替换左侧饼图为 callout 标注样式。 |
| 左侧 | `OrderSizeNetPieChart(labelMode='callout', showSlicePercent=true, centerMode='empty')`。 |
| 右侧 | 既有 `MoneyFlowHistoryChart`，趋势图交互、0 轴、Tooltip、RangeSwitch 规则不变。 |
| 左右比例 | 沿用 v3 建议：约 `38% / 62%`，可在 35/65 到 42/58 范围内微调。 |
| 高度约束 | 不改变大盘资金流向模块整体高度；仅调整饼图、趋势图、标注和间距。 |
| 禁止事项 | 不把饼图移到趋势图上方；不新增第二个饼图；不改变右侧榜单速览结构；不改动趋势图规则。 |

```ts
interface MoneyFlowNetStructurePanelPropsV4 extends MoneyFlowNetStructurePanelProps {
  pieLabelMode?: 'callout';
  showPieSlicePercent?: true;
  pieCenterMode?: 'empty';
}
```

---

### 18.9 Review v4 组件与 API 字段映射表

| Review v4 区域 | 组件 | API 字段 / ViewModel 字段 | 字段需求 |
|---|---|---|---|
| 今日领涨股涨停表现 | `LimitUpLeaderPerformanceTable` | `limitUp.todayDistribution.sectorLeaderPanel.leaderStocks[]` | `rank/stockCode/stockName/latestPrice/changePct/streakLabel/recentLimitText/firstLimitTime/openTimes/sealedAmount` |
| 昨日领涨股涨停表现 | `LimitUpLeaderPerformanceTable` | `limitUp.previousTradeDayDistribution.sectorLeaderPanel.leaderStocks[]` | 与 today 同构，仅 `dateType` 和 `tradeDate` 不同 |
| 今日涨停板块分布 + 领涨股涨停表现 | `LimitUpSectorLeaderPanel` v4 | `limitUp.todayDistribution.sectorLeaderPanel.sectors[]` + `leaderStocks[]` | 左侧板块分布，右侧行式表现表 |
| 昨日涨停板块分布 + 领涨股涨停表现 | `LimitUpSectorLeaderPanel` v4 | `limitUp.previousTradeDayDistribution.sectorLeaderPanel.sectors[]` + `leaderStocks[]` | 同构字段 |
| 单型资金净流向 callout 饼图 | `OrderSizeNetPieChart` v4 | `moneyFlow.orderSizeNetStructure.items[]` | `orderSize/orderSizeName/netAmount/netAmountRate/absAmount/direction/structureRatio?` |
| 饼图外部折线标注 | `PieCalloutLabel` | `OrderSizeNetPieItem` 派生 | 单型名称 + 净额展示，无新增 API 字段 |
| 饼块白色占比 | `PieSlicePercentLabel` | `item.structureRatio` 或 `absAmount / sum(absAmount)` | 可前端派生；不强制 API 新增字段 |
| 大盘资金内部左右结构 | `MoneyFlowNetStructurePanel` v4 | `moneyFlow.orderSizeNetStructure`、`moneyFlow.historyPoints[]` | 左 callout 饼图 + 右既有资金历史趋势图 |

---

### 18.10 对 02 market-overview-v1.3.html 的组件使用建议

1. 只改 Review v4 点名区域，不改其它区域。
2. 在“涨跌停统计与分布”右上区域，将 v3 的“领涨股 + 涨停表现”两个分离模块合并为 `LimitUpLeaderPerformanceTable(title='领涨股涨停表现')`。
3. 在“涨跌停统计与分布”右下区域做同样修改；今日和昨日必须同步，不能只改一个。
4. `LimitUpLeaderPerformanceTable` 最多显示 3 行；每行一只股票，股票信息与涨停表现必须同一行打通。
5. 保留左侧 `LimitUpSectorBars`，右侧使用 `LimitUpLeaderPerformanceTable`，整体结构为 `涨停板块分布 ｜ 领涨股涨停表现`。
6. 不使用用户草图中的残留数字。
7. 大盘资金流向模块仍为左饼图、右趋势图；只修改左侧饼图的说明样式。
8. 饼图中心保持为空，不显示“净额结构”、`absAmount` 或任何英文调试字段。
9. 饼块上直接显示白色占比文字。
10. 饼图外部用折线标注单型名称和净额，文字可在折线上方或下方。
11. 正值标注红色，负值标注绿色，零值灰白色。
12. 不改变 MoneyFlowHistoryChart 的白色主线、0 轴居中、Tooltip、RangeSwitch 规则。
13. 不改动 Review v4 未点名区域，包括 TopMarketBar、Breadcrumb、PageHeader、ShortcutBar、今日总结、主要指数、涨跌分布、市场风格、成交额、榜单、连板天梯、板块速览。

---

### 18.11 对 04 API 的字段需求

本轮原则上不强制 04 API 参与；数据 model 沿用 Review v3 / API v0.5，不因展示样式新增必需字段。

| 字段需求 | 必要性 | 说明 |
|---|---:|---|
| `limitUp.todayDistribution.sectorLeaderPanel.leaderStocks[]` | 必需 | 继续作为今日领涨股涨停表现数据源。 |
| `limitUp.previousTradeDayDistribution.sectorLeaderPanel.leaderStocks[]` | 必需 | 继续作为昨日领涨股涨停表现数据源。 |
| `leaderStocks[].rank` | 必需 | 行式表格排名。 |
| `leaderStocks[].stockCode` | 必需 | 个股详情下钻。 |
| `leaderStocks[].stockName` | 必需 | 股票展示名。 |
| `leaderStocks[].latestPrice` | 必需 | 最新价。 |
| `leaderStocks[].changePct` | 必需 | 涨跌幅。 |
| `leaderStocks[].streakLabel` | 必需 | 如“3连板”“首板”。 |
| `leaderStocks[].recentLimitText` | 必需 | 如“7天5板”“1天1板”。 |
| `leaderStocks[].firstLimitTime` | 可选 | 首次封板时间。 |
| `leaderStocks[].openTimes` | 可选 | 开板次数。 |
| `leaderStocks[].sealedAmount` | 可选 | 封单金额。 |
| `leaderStocks[].sealedAmountDisplayText` | 建议 | 避免前端猜测单位。 |
| `moneyFlow.orderSizeNetStructure.items[]` | 必需 | 单型资金净流向饼图数据源。 |
| `items[].absAmount` | 必需或前端派生 | 饼图面积字段；若 API 不返回，前端可由 `Math.abs(netAmount)` 派生。 |
| `items[].direction` | 必需或前端派生 | `inflow/outflow/flat`；若 API 不返回，前端可由 `netAmount` 正负派生。 |
| `items[].structureRatio` | 可选 | 饼块白色占比；若 API 不返回，前端按 `absAmount / sum(absAmount)` 派生。 |

需要 04 后续确认的问题：

1. `netAmountRate` 是源字段净占比，还是饼图面积结构占比？
2. 是否建议 API 同时返回 `structureRatio`，避免前端和后端口径不一致？
3. `sealedAmountDisplayText` 是否由 API 返回，以避免前端自行换算封单金额单位？

---

### 18.12 对 01 Design Token 的依赖

本轮已读取 `03-design-tokens.md v0.2.6`，组件实现需对齐其中 Review v4 相关 Token。重点依赖：

1. `LimitUpLeaderPerformanceTable` 行式结构：行背景、hover 背景、selected 背景、行内分隔线。
2. 股票信息层级：股票名、股票代码、最新价、涨跌幅、排名的字体和颜色。
3. 涨停表现标签：`streakLabel`、`recentLimitText` 的背景、边框、文字色。
4. 饼图 callout 折线：折线颜色、转折点样式、文本间距。
5. 饼图 callout 文本：单型名称、净额值、正红负绿的层级。
6. 饼块上白色占比文字：字号、字重、阴影或描边，提高红/绿饼块上的可读性。
7. 饼图中心留白：中心区域不承载文本，保持干净视觉。
8. 不得为本轮修改全局主题、全局字体、TopMarketBar、Breadcrumb、PageHeader、ShortcutBar 的 Token。

建议 Token 命名：

```css
:root {
  --cs-color-limit-leader-performance-row-bg: ...;
  --cs-color-limit-leader-performance-row-hover-bg: ...;
  --cs-color-limit-leader-performance-row-selected-bg: ...;
  --cs-color-limit-leader-performance-row-border: ...;

  --cs-color-limit-performance-tag-bg: var(--cs-color-market-up-bg);
  --cs-color-limit-performance-tag-text: var(--cs-color-market-up);
  --cs-color-limit-performance-tag-border: var(--cs-color-market-up-border);

  --cs-color-order-pie-callout-line: ...;
  --cs-color-order-pie-callout-text: ...;
  --cs-color-order-pie-slice-percent-text: #FFFFFF;
  --cs-shadow-order-pie-slice-percent-text: ...;
}
```

---

### 18.13 本轮 Review v4 修改摘要

1. 新增 `LimitUpLeaderPerformanceTable`，用于合并后的“领涨股涨停表现”行式结构。
2. 修订 `LimitUpSectorLeaderPanel`，将 v3 的三段式 `涨停板块分布｜领涨股｜涨停表现` 改为 v4 的两段式 `涨停板块分布｜领涨股涨停表现`。
3. 明确今日和昨日两个区域必须同时使用 `LimitUpLeaderPerformanceTable`，不能只改一个。
4. 修订 `OrderSizeNetPieChart`，采用 callout 折线标注样式。
5. 新增 `PieCalloutLabel` 作为饼图外部折线标注子组件。
6. 新增 `PieSlicePercentLabel` 作为饼块白色占比文字子组件。
7. 修订 `MoneyFlowNetStructurePanel` 的左侧饼图使用方式，但不改变左饼图 + 右趋势图布局，不影响右侧榜单速览。
8. 明确本轮不改变 API 数据 model，`absAmount`、`direction`、`structureRatio` 可按既有字段派生。
9. 明确不修改 Review v4 未点名组件和页面整体布局。

### 18.14 本轮新增或修订组件清单

| 类型 | 组件 | 处理方式 |
|---|---|---|
| 新增 | `LimitUpLeaderPerformanceTable` | 新增合并后的“领涨股涨停表现”行式组件 |
| 修订 | `LimitUpSectorLeaderPanel` | 从三段式修订为两段式：左板块分布、右领涨股涨停表现 |
| 修订 | `OrderSizeNetPieChart` | 增加 callout 标注、饼块白色占比、中心留白规则 |
| 新增 | `PieCalloutLabel` | 新增饼图外部折线标注子组件 |
| 新增 | `PieSlicePercentLabel` | 新增饼块内部白色占比文字子组件 |
| 修订 | `MoneyFlowNetStructurePanel` | 左侧饼图替换为 callout 版，外部布局保持不变 |

### 18.15 本轮未修改组件清单

以下组件保持 v0.6 merged-full 规范，不做主动改动：

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
- `MarketSummaryIndexSplit`
- `MarketSummaryFactCard`
- `MarketSummaryNoteCard`
- `IndexGrid`
- `IndexCard`
- `MetricCard`
- `ChangeBadge`
- `QuoteTicker`
- `MiniTrendChart`
- `MarketBreadthPanel`
- `DistributionChart`
- `HistoryTrendChart`
- `MarketStylePanel`
- `MarketStyleTrendChart`
- `TurnoverSummaryCard`
- `IntradayTurnoverChart`
- `RankingTable`
- `StockTable`
- `SortableHeader`
- `TabPanel`
- `LimitUpSummaryCard`
- `LimitUpDistributionGrid` 外层 2×2 结构
- `LimitUpDownHistoryBarChart`
- `HorizontalLimitUpStreakLadder`
- `SectorOverviewMatrix`
- `SectorHeatMap`
- `HelpTooltip`
- `RangeSwitch`
- `LoadingSkeleton`
- `EmptyState`
- `ErrorState`
- `DataDelayState`
- `PermissionState`

### 18.16 本轮因 Review v4 修改而被动影响的区域

```text
本轮因 Review v4 修改而被动影响的区域：
- LimitUpSectorLeaderPanel 的右侧内部结构
原因：Review v4 明确要求将“领涨股”和“涨停表现”合并为“领涨股涨停表现”，并按行打通。
是否需要产品总控确认：否，属于 Review v4 明确点名区域。

本轮因 Review v4 修改而被动影响的区域：
- MoneyFlowNetStructurePanel 左侧饼图渲染方式
原因：Review v4 明确要求单型资金净流向饼图改为折线 callout 标注，饼块上显示白色占比，中心不显示文字。
是否需要产品总控确认：否，属于 Review v4 明确点名区域。
```

### 18.17 待产品总控确认问题

1. `LimitUpLeaderPerformanceTable` 超过 3 条时，“更多”入口应跳转至板块与榜单行情页，还是涨停详情页？建议跳转板块与榜单行情页并携带 `sectorCode`、`tradeDate`、`limitType=LIMIT_UP`。
2. 饼块面积占比在扇区过小时是否允许隐藏？建议小于 6% 时隐藏扇区内白色占比，但 Tooltip 和 callout 保留完整信息。
3. 饼图外部 callout 是否最多展示 4 条全部单型，还是允许空间不足时合并较小扇区说明？建议 P0 固定 4 条，避免隐藏单型信息。
4. `OrderSizeNetPieChart` 是否采用普通饼图还是环形图？建议环形图但中心留空，不显示文字。
5. `netAmountRate` 是否作为 callout 展示内容？当前建议 callout 展示“单型名称 + 净额”，占比仅放饼块内，Tooltip 展示完整占比。
6. `sealedAmountDisplayText` 是否由 API 返回？建议返回，避免组件自行换算封单金额单位。
7. 今日和昨日区域的 `LimitUpLeaderPerformanceTable` 是否必须使用相同 maxRows=3？建议固定一致，保证对比清晰。

### 18.18 Review v4 验收清单

| 验收项 | 要求 |
|---|---|
| 完整文档 | 本文件仍是完整 `04-component-guidelines.md`，不是 delta 文档。 |
| 修改边界 | 只新增/修订 Review v4 点名的两个区域组件。 |
| 领涨股涨停表现 | `LimitUpLeaderPerformanceTable` 可完整支撑“领涨股涨停表现”行式结构。 |
| 行式打通 | 每一行是一只股票，股票信息和涨停表现同一行展示。 |
| 行数限制 | 最多展示 3 行，超过显示“更多”或省略。 |
| 今日/昨日同步 | 今日和昨日两个区域都使用同一结构。 |
| 草图残留数字 | 不展示用户草图中的残留数字。 |
| 饼图 callout | `OrderSizeNetPieChart` 支持外部折线标注单型名称和净额。 |
| 饼块占比 | 饼块上使用白色文字显示结构占比。 |
| 饼图中心 | 中心不显示“净额结构”、`absAmount` 或调试字段。 |
| 外部布局 | `MoneyFlowNetStructurePanel` 仍保持左饼图、右趋势图，不影响榜单速览。 |
| API model | 不强制修改 API 数据 model，可由既有字段派生结构占比。 |
| 未授权改动 | 未修改 TopMarketBar、Breadcrumb、PageHeader、ShortcutBar、今日总结、主要指数、涨跌分布、市场风格、成交额、榜单、连板天梯、板块速览等非点名区域。 |

### 18.19 建议放置到 Google Drive 的路径

```text
财势乾坤/设计/04-component-guidelines.md
```

### 18.20 建议仓库保存路径

```text
/docs/wealth/04-component-guidelines.md
```

### 18.21 本轮输出文件下载链接

对话交付文件：

```text
sandbox:/mnt/data/review-v4-output-final/04-component-guidelines.md
```

---

## 19. 通用组件库注册表 v0.8

> 本节为基于《组件库 Demo 产品需求文档 v0.2》的新增全量修订内容。它不删除前文市场总览组件规范，但从本节开始明确：**Core Components 必须与具体业务解耦，统一使用 `Csq` 前缀；市场总览、涨跌停、资金流、板块热力图等只作为 Pattern Examples 或页面适配层，不进入 Core Component 契约。**

### 19.1 本轮采用的组件库边界

1. 组件库与具体业务解耦。
2. Core Component 不使用具体业务命名。
3. Core Component 不绑定市场总览、涨跌停、持仓、机会雷达等业务模块。
4. 组件 Props 是通用抽象，不是 API response。
5. 不引用 Tushare 原始字段作为组件 Props。
6. Pattern Example 可以说明组件如何组合到行情场景，但 Pattern 不是核心组件契约。
7. 04 API 与数据字典不参与本轮组件库主流程；页面级 API 只负责把 response 适配到组件 Props。
8. 组件统一使用 `Csq` 前缀；Pattern 不使用 `Csq` 前缀。

### 19.2 命名规则

```text
Core Component: Csq + UI能力名
Pattern Example: Pattern + 业务/场景示例名
```

| 类型 | 正确示例 | 禁止示例 | 说明 |
|---|---|---|---|
| Core | `CsqPieChartWithCallout` | `CsqOrderSizeNetPieChartWithCallout` | Core 表达图表能力，不表达资金业务 |
| Core | `CsqLinkedMetricList` | `CsqLimitUpLeaderPerformanceTable` | Core 表达实体 + 指标列表能力，不表达涨停业务 |
| Core | `CsqHeatMapGrid` | `CsqSectorHeatMap` | Core 表达热力网格能力，不表达板块业务 |
| Core | `CsqRankTable` | `CsqStockRankingTable` | Core 表达排名表格能力，不表达股票榜单业务 |
| Pattern | `PatternMoneyFlowSplit` | `CsqMoneyFlowPanel` | 资金流是业务组合，只能作为 Pattern 示例 |

### 19.3 Core Component 注册表

| 层级 | 组件名 | 中文名 | P0 必需 | 核心能力 |
|---|---|---|---:|---|
| Foundation Components | `CsqPanel` | 标准面板 | 是 | 提供通用内容容器，承载标题区、主体区、页脚区和局部状态。 |
| Foundation Components | `CsqSectionHeader` | 模块标题栏 | 是 | 提供模块标题、说明、HelpTooltip、右侧操作区和 RangeSwitch 容器。 |
| Foundation Components | `CsqHelpTooltip` | 问号说明 | 是 | 收纳口径、字段、数据延迟、图表阅读方式等短说明。 |
| Foundation Components | `CsqBadge` | 标签 | 是 | 展示类型、数量、状态、轻量属性。 |
| Foundation Components | `CsqStatusDot` | 状态点 | 是 | 以小圆点表达在线、延迟、异常、关闭、未知等状态。 |
| Foundation Components | `CsqSkeleton` | 骨架屏 | 是 | 为卡片、表格、图表、文本提供 loading 占位。 |
| Foundation Components | `CsqEmptyState` | 空状态 | 是 | 解释无数据原因并提供下一步动作。 |
| Foundation Components | `CsqErrorState` | 异常状态 | 是 | 展示局部模块异常、服务错误、数据源不可用、字段缺失。 |
| Navigation Components | `CsqTopBar` | 顶部栏 | 是 | 通用顶部容器，承载品牌区、主导航区、状态区和用户区。 |
| Navigation Components | `CsqBreadcrumb` | 面包屑 | 是 | 展示页面层级和当前所在位置。 |
| Navigation Components | `CsqPageHeader` | 页面头部 | 是 | 展示页面标题、副标题、状态、操作区。 |
| Navigation Components | `CsqShortcutBar` | 快捷入口栏 | 是 | 横向承载页面内快捷入口或功能入口。 |
| Navigation Components | `CsqTabs` | 标签页 | 是 | 提供分组切换、榜单切换、图表切换。 |
| Navigation Components | `CsqRangeSwitch` | 时间范围切换 | 是 | 用于 1个月/3个月等范围切换的 segmented control。 |
| Data Display Components | `CsqMetricCard` | 指标卡 | 是 | 展示一个指标的名称、主值、单位、变化和说明。 |
| Data Display Components | `CsqMetricSummaryGroup` | 指标摘要组 | 是 | 按栅格组织多个 CsqMetricCard。 |
| Data Display Components | `CsqChangeValue` | 涨跌数值 | 是 | 统一展示带方向的数值、百分比或金额变化。 |
| Data Display Components | `CsqChangeBadge` | 涨跌标签 | 是 | 以 badge/pill/cell 形式展示方向值。 |
| Data Display Components | `CsqInfoRow` | 信息行 | 是 | 展示 label + value + extra 的紧凑信息行。 |
| Data Display Components | `CsqLinkedMetricList` | 关联指标列表 | 是 | 展示“实体 + 一组指标/标签”的行式列表，每行一个实体，适用于通用关联指标展示。 |
| Data Display Components | `CsqProgressList` | 进度条列表 | 是 | 展示名称、横向进度条、数值、占比。 |
| Data Display Components | `CsqStatusBadge` | 状态标记 | 是 | 展示 ready/delayed/partial/error/disabled 等状态。 |
| Table Components | `CsqDataTable` | 数据表格 | 是 | 通用高密度数据表格，支持列配置、行状态和空/错/加载。 |
| Table Components | `CsqRankTable` | 排名表格 | 是 | 排名类表格，支持 TopN、高密度和自定义列。 |
| Table Components | `CsqColumnHeader` | 表头 | 是 | 表格列标题、排序、对齐、HelpTooltip。 |
| Table Components | `CsqTableRow` | 表格行 | 是 | 统一行 hover、selected、clickable、disabled 状态。 |
| Table Components | `CsqTableCellNumber` | 数字单元格 | 是 | 统一数字对齐、单位、精度、方向色。 |
| Chart Components | `CsqMiniTrendChart` | 小型趋势图 | 是 | 卡片内轻量趋势线，不承载复杂坐标交互。 |
| Chart Components | `CsqHistoryTrendChart` | 历史趋势图 | 是 | 带坐标轴、图例、Tooltip、crosshair 的通用历史趋势图。 |
| Chart Components | `CsqDistributionChart` | 分布图 | 是 | 展示区间桶、数量、占比和方向。 |
| Chart Components | `CsqBarChart` | 柱状图 | 是 | 支持单组/多组柱状图。 |
| Chart Components | `CsqPieChartWithCallout` | 折线标注饼图 | 是 | 通用分类占比饼图，支持饼块占比文字和外部折线标注。 |
| Chart Components | `CsqHeatMapGrid` | 热力图网格 | 是 | 通用 N×M 热力图，支持语义色和中性热度色。 |
| Chart Components | `CsqChartSplitPanel` | 图表分栏面板 | 是 | 通用左右图表组合容器。 |
| Chart Components | `CsqChartTooltip` | 图表 Tooltip | 是 | 统一图表浮层、序列值、时间和值格式。 |
| Chart Components | `CsqCrosshairOverlay` | 十字定位线 | 是 | 图表坐标定位层。 |

### 19.4 Core Component 详细定义


#### CsqPanel

| 项 | 说明 |
|---|---|
| 组件名 | `CsqPanel` |
| 中文名 | 标准面板 |
| 所属层级 | Foundation Components |
| 组件用途 | 提供通用内容容器，承载标题区、主体区、页脚区和局部状态。 |
| 适用场景 | 所有高密度数据模块、图表模块、表格模块、设置卡片。 |
| Props 摘要 | `title、subtitle、extra、body、footer、density、state、bordered、scrollable` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | Panel 内部元素交互；面板本身默认不整体跳转，可配置 onClick 但不推荐滥用。 |
| Design Token 映射 | surface、border、radius、shadow、space、text。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止把具体业务模块名写入组件名；禁止用发光边框或大屏风装饰；禁止在 Panel 内直接写死 API response 字段。 |
| 是否 P0 必需 | 是 |

#### CsqSectionHeader

| 项 | 说明 |
|---|---|
| 组件名 | `CsqSectionHeader` |
| 中文名 | 模块标题栏 |
| 所属层级 | Foundation Components |
| 组件用途 | 提供模块标题、说明、HelpTooltip、右侧操作区和 RangeSwitch 容器。 |
| 适用场景 | Panel 标题区、图表标题区、表格标题区。 |
| Props 摘要 | `title、description、tooltip、actions、extra、density、align` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | hover 操作项显示可点击态；HelpTooltip 由 CsqHelpTooltip 承载；操作区不得挤压标题可读性。 |
| Design Token 映射 | text、help、range-switch、space。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止把大段说明直接铺在模块正文；禁止在标题栏输出主观交易建议。 |
| 是否 P0 必需 | 是 |

#### CsqHelpTooltip

| 项 | 说明 |
|---|---|
| 组件名 | `CsqHelpTooltip` |
| 中文名 | 问号说明 |
| 所属层级 | Foundation Components |
| 组件用途 | 收纳口径、字段、数据延迟、图表阅读方式等短说明。 |
| 适用场景 | 模块标题旁、表头旁、指标卡说明旁。 |
| Props 摘要 | `title、content、placement、trigger、maxWidth、disabled、ariaLabel` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | 桌面 hover/focus，必要时 click pin；Esc 关闭；小屏降级为 Popover 或底部浮层。 |
| Design Token 映射 | help-icon、tooltip-bg、tooltip-border、tooltip-text、z-tooltip。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止承载长篇指标字典；禁止输出买卖建议；禁止遮挡关键数字。 |
| 是否 P0 必需 | 是 |

#### CsqBadge

| 项 | 说明 |
|---|---|
| 组件名 | `CsqBadge` |
| 中文名 | 标签 |
| 所属层级 | Foundation Components |
| 组件用途 | 展示类型、数量、状态、轻量属性。 |
| 适用场景 | 快捷入口、表格行、指标说明、图例。 |
| Props 摘要 | `label、count、semantic、size、variant、icon、maxCount` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | 通常随父项 hover；可配置 clickable，但默认仅展示。 |
| Design Token 映射 | badge-bg、badge-border、text、brand、warning、market colors。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止用 success=green 表示上涨；行情方向必须走 rise/fall/flat 语义。 |
| 是否 P0 必需 | 是 |

#### CsqStatusDot

| 项 | 说明 |
|---|---|
| 组件名 | `CsqStatusDot` |
| 中文名 | 状态点 |
| 所属层级 | Foundation Components |
| 组件用途 | 以小圆点表达在线、延迟、异常、关闭、未知等状态。 |
| 适用场景 | TopBar、数据状态、连接状态、模块刷新状态。 |
| Props 摘要 | `status、label、pulse、size、tooltip` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | hover 显示状态说明；不承载业务跳转。 |
| Design Token 映射 | status-live、status-delayed、status-error、status-muted。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止用行情红绿表达系统状态；状态色与涨跌色必须分离。 |
| 是否 P0 必需 | 是 |

#### CsqSkeleton

| 项 | 说明 |
|---|---|
| 组件名 | `CsqSkeleton` |
| 中文名 | 骨架屏 |
| 所属层级 | Foundation Components |
| 组件用途 | 为卡片、表格、图表、文本提供 loading 占位。 |
| 适用场景 | 所有组件 loading 态。 |
| Props 摘要 | `variant、rows、height、width、animated、density` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | 不可点击；局部刷新优先保留旧数据而不是清空整个区域。 |
| Design Token 映射 | skeleton-bg、skeleton-highlight、radius。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止整页白屏；禁止用红绿骨架色。 |
| 是否 P0 必需 | 是 |

#### CsqEmptyState

| 项 | 说明 |
|---|---|
| 组件名 | `CsqEmptyState` |
| 中文名 | 空状态 |
| 所属层级 | Foundation Components |
| 组件用途 | 解释无数据原因并提供下一步动作。 |
| 适用场景 | 表格空数据、图表无点、模块暂无数据、筛选无结果。 |
| Props 摘要 | `title、description、reason、actionText、onAction、compact` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | 可触发刷新、切换最近交易日或调整筛选；不要阻断其它模块。 |
| Design Token 映射 | text-muted、surface、info、space。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止只写“暂无数据”；禁止把空数据误显示为 0。 |
| 是否 P0 必需 | 是 |

#### CsqErrorState

| 项 | 说明 |
|---|---|
| 组件名 | `CsqErrorState` |
| 中文名 | 异常状态 |
| 所属层级 | Foundation Components |
| 组件用途 | 展示局部模块异常、服务错误、数据源不可用、字段缺失。 |
| 适用场景 | 所有模块 error 态。 |
| Props 摘要 | `title、message、code、traceId、retryText、onRetry、compact` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | 点击重试；可复制 traceId；单模块错误不得拖垮整页。 |
| Design Token 映射 | danger-system、surface、border、text。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止使用行情上涨红作为系统错误色；禁止整页失败覆盖局部错误。 |
| 是否 P0 必需 | 是 |

#### CsqTopBar

| 项 | 说明 |
|---|---|
| 组件名 | `CsqTopBar` |
| 中文名 | 顶部栏 |
| 所属层级 | Navigation Components |
| 组件用途 | 通用顶部容器，承载品牌区、主导航区、状态区和用户区。 |
| 适用场景 | 全站顶部、行情终端主框架、组件库 Demo 顶栏。 |
| Props 摘要 | `brand、navItems、activeKey、leading、center、trailing、height、density` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | 支持 hover、selected、dropdown、折叠菜单；不绑定乾坤行情等具体系统。 |
| Design Token 映射 | topbar-bg、border、brand、z-topbar。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止命名或绑定为 TopMarketBar；禁止在 Core Props 中写死指数、交易日、用户账户业务结构。 |
| 是否 P0 必需 | 是 |

#### CsqBreadcrumb

| 项 | 说明 |
|---|---|
| 组件名 | `CsqBreadcrumb` |
| 中文名 | 面包屑 |
| 所属层级 | Navigation Components |
| 组件用途 | 展示页面层级和当前所在位置。 |
| 适用场景 | 页面头部、详情页、Demo 页面。 |
| Props 摘要 | `items、separator、currentKey、maxItems、onItemClick` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | 可点击项 hover 提亮；当前项不可点击或点击刷新由页面决定。 |
| Design Token 映射 | breadcrumb-bg、text-muted、brand、space。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止把固定业务层级写入核心组件；业务层级由调用方传 items。 |
| 是否 P0 必需 | 是 |

#### CsqPageHeader

| 项 | 说明 |
|---|---|
| 组件名 | `CsqPageHeader` |
| 中文名 | 页面头部 |
| 所属层级 | Navigation Components |
| 组件用途 | 展示页面标题、副标题、状态、操作区。 |
| 适用场景 | 所有页面顶部。 |
| Props 摘要 | `title、subtitle、meta、actions、status、density` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | 操作按钮 hover/active；状态信息可带 tooltip。 |
| Design Token 映射 | page-header-height、text、space、button。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止做成营销 Hero Banner；禁止硬编码“市场总览”。 |
| 是否 P0 必需 | 是 |

#### CsqShortcutBar

| 项 | 说明 |
|---|---|
| 组件名 | `CsqShortcutBar` |
| 中文名 | 快捷入口栏 |
| 所属层级 | Navigation Components |
| 组件用途 | 横向承载页面内快捷入口或功能入口。 |
| 适用场景 | 市场总览入口、设置页快捷项、Demo 导航。 |
| Props 摘要 | `items、layout、density、selectedKey、onItemClick` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | 点击入口跳转；disabled 显示原因；可展示 badge。 |
| Design Token 映射 | shortcut-bg、card-hover、brand、badge。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止把具体入口如“机会雷达/持仓”写死到 Core Component。 |
| 是否 P0 必需 | 是 |

#### CsqTabs

| 项 | 说明 |
|---|---|
| 组件名 | `CsqTabs` |
| 中文名 | 标签页 |
| 所属层级 | Navigation Components |
| 组件用途 | 提供分组切换、榜单切换、图表切换。 |
| 适用场景 | 表格、图表、分组内容。 |
| Props 摘要 | `tabs、activeKey、variant、size、onChange` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | 点击/键盘切换；disabled Tab 不响应。 |
| Design Token 映射 | tab-bg、tab-selected、brand、border。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止用红绿表示 Tab 选中；选中态用品牌色。 |
| 是否 P0 必需 | 是 |

#### CsqRangeSwitch

| 项 | 说明 |
|---|---|
| 组件名 | `CsqRangeSwitch` |
| 中文名 | 时间范围切换 |
| 所属层级 | Navigation Components |
| 组件用途 | 用于 1个月/3个月等范围切换的 segmented control。 |
| 适用场景 | 历史趋势图、柱图、Demo 图表区。 |
| Props 摘要 | `options、selectedValue、disabledValues、size、loading、onChange` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | 切换时触发局部刷新；请求中保留旧图并展示 loading。 |
| Design Token 映射 | range-switch-bg、selected-bg、brand、border。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止将范围值绑定为 API 字段名；它只输出通用 selectedValue。 |
| 是否 P0 必需 | 是 |

#### CsqMetricCard

| 项 | 说明 |
|---|---|
| 组件名 | `CsqMetricCard` |
| 中文名 | 指标卡 |
| 所属层级 | Data Display Components |
| 组件用途 | 展示一个指标的名称、主值、单位、变化和说明。 |
| 适用场景 | 行情指标、统计指标、系统指标、Demo 指标。 |
| Props 摘要 | `label、value、unit、valueText、change、semantic、tooltip、onClick` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | hover 显示说明；可点击下钻；disabled 时显示原因。 |
| Design Token 映射 | metric-card-bg、number-font、market colors、space。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止写死上涨家数、涨停家数等业务名；业务由 label/value 传入。 |
| 是否 P0 必需 | 是 |

#### CsqMetricSummaryGroup

| 项 | 说明 |
|---|---|
| 组件名 | `CsqMetricSummaryGroup` |
| 中文名 | 指标摘要组 |
| 所属层级 | Data Display Components |
| 组件用途 | 按栅格组织多个 CsqMetricCard。 |
| 适用场景 | 事实卡组、统计卡组、页面摘要。 |
| Props 摘要 | `items、columns、density、responsive、loading、onItemClick` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | 支持卡片 hover/click；响应式调整列数。 |
| Design Token 映射 | grid-gap、card-bg、space。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止把市场总览五事实卡写成 Core 契约；它只是 PatternMarketSummary 的一种组合。 |
| 是否 P0 必需 | 是 |

#### CsqChangeValue

| 项 | 说明 |
|---|---|
| 组件名 | `CsqChangeValue` |
| 中文名 | 涨跌数值 |
| 所属层级 | Data Display Components |
| 组件用途 | 统一展示带方向的数值、百分比或金额变化。 |
| 适用场景 | 价格、涨跌幅、净流入、变化值。 |
| Props 摘要 | `value、valueText、direction、unit、showSign、precision、variant` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | hover 可显示原始值；默认不可点击。 |
| Design Token 映射 | market-up/down/flat、number-font。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止用绿色表示上涨；禁止根据字段名猜方向，必须由 direction 或数值显式决定。 |
| 是否 P0 必需 | 是 |

#### CsqChangeBadge

| 项 | 说明 |
|---|---|
| 组件名 | `CsqChangeBadge` |
| 中文名 | 涨跌标签 |
| 所属层级 | Data Display Components |
| 组件用途 | 以 badge/pill/cell 形式展示方向值。 |
| 适用场景 | 表格单元格、指标卡、榜单。 |
| Props 摘要 | `value、label、direction、semantic、variant、showSign` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | 跟随父行 hover；可配置 tooltip。 |
| Design Token 映射 | market-bg、market-border、number-font。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止套用框架 success/danger；必须遵守红涨绿跌。 |
| 是否 P0 必需 | 是 |

#### CsqInfoRow

| 项 | 说明 |
|---|---|
| 组件名 | `CsqInfoRow` |
| 中文名 | 信息行 |
| 所属层级 | Data Display Components |
| 组件用途 | 展示 label + value + extra 的紧凑信息行。 |
| 适用场景 | 详情页、Tooltip、Popover、卡片元信息。 |
| Props 摘要 | `label、value、valueText、extra、semantic、align` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | hover 可显示 copy 或 tooltip；默认仅展示。 |
| Design Token 映射 | text、number-font、divider。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止作为表格替代用于大量行；大量数据用 CsqDataTable。 |
| 是否 P0 必需 | 是 |

#### CsqLinkedMetricList

| 项 | 说明 |
|---|---|
| 组件名 | `CsqLinkedMetricList` |
| 中文名 | 关联指标列表 |
| 所属层级 | Data Display Components |
| 组件用途 | 展示“实体 + 一组指标/标签”的行式列表，每行一个实体，适用于通用关联指标展示。 |
| 适用场景 | 领涨股表现、板块指标、指数表现、实体强弱列表。 |
| Props 摘要 | `title、maxRows、items、onItemClick、loading、emptyText` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | 整行 hover 高亮；点击行回调；超过 maxRows 展示更多入口。 |
| Design Token 映射 | row-hover、tag、number-font、market colors。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止命名或绑定为股票/涨停专用；不得把 stockCode 等业务字段作为 Core Props。 |
| 是否 P0 必需 | 是 |

#### CsqProgressList

| 项 | 说明 |
|---|---|
| 组件名 | `CsqProgressList` |
| 中文名 | 进度条列表 |
| 所属层级 | Data Display Components |
| 组件用途 | 展示名称、横向进度条、数值、占比。 |
| 适用场景 | 分布排行、结构占比、完成率、集中度。 |
| Props 摘要 | `items、valueKey、maxValue、semantic、showValue、onItemClick` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | hover 高亮条形，Tooltip 展示详细值；点击项回调。 |
| Design Token 映射 | progress-track、market colors、brand。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止直接写死涨停板块分布；该业务通过 PatternLimitStructure 适配。 |
| 是否 P0 必需 | 是 |

#### CsqStatusBadge

| 项 | 说明 |
|---|---|
| 组件名 | `CsqStatusBadge` |
| 中文名 | 状态标记 |
| 所属层级 | Data Display Components |
| 组件用途 | 展示 ready/delayed/partial/error/disabled 等状态。 |
| 适用场景 | 数据状态、功能状态、同步状态。 |
| Props 摘要 | `status、label、message、tooltip、variant` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | hover/click 可显示状态说明。 |
| Design Token 映射 | status colors、warning、danger-system。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止使用行情涨跌色表达系统状态。 |
| 是否 P0 必需 | 是 |

#### CsqDataTable

| 项 | 说明 |
|---|---|
| 组件名 | `CsqDataTable` |
| 中文名 | 数据表格 |
| 所属层级 | Table Components |
| 组件用途 | 通用高密度数据表格，支持列配置、行状态和空/错/加载。 |
| 适用场景 | 榜单、列表、设置表、数据明细。 |
| Props 摘要 | `columns、rows、rowKey、density、loading、empty、error、onRowClick` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | 行 hover、selected、排序、点击行；支持局部 loading。 |
| Design Token 映射 | table-bg、row-hover、border、number-font。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止在 Core 表格内写死股票列、板块列或 API response 字段。 |
| 是否 P0 必需 | 是 |

#### CsqRankTable

| 项 | 说明 |
|---|---|
| 组件名 | `CsqRankTable` |
| 中文名 | 排名表格 |
| 所属层级 | Table Components |
| 组件用途 | 排名类表格，支持 TopN、高密度和自定义列。 |
| 适用场景 | 榜单速览、TopN 排名、行业排名、Demo 排名表。 |
| Props 摘要 | `rankField、topN、columns、rows、density、onRowClick` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | TopN 截断；行 hover；列可排序；点击行回调。 |
| Design Token 映射 | table-density、row-hover、market colors。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止绑定为股票榜单；股票榜单属于业务适配层。 |
| 是否 P0 必需 | 是 |

#### CsqColumnHeader

| 项 | 说明 |
|---|---|
| 组件名 | `CsqColumnHeader` |
| 中文名 | 表头 |
| 所属层级 | Table Components |
| 组件用途 | 表格列标题、排序、对齐、HelpTooltip。 |
| 适用场景 | CsqDataTable、CsqRankTable。 |
| Props 摘要 | `label、field、sortable、sortOrder、align、tooltip` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | 点击切换排序；hover 显示可排序态。 |
| Design Token 映射 | text-secondary、brand、border。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止使用红绿表达排序方向。 |
| 是否 P0 必需 | 是 |

#### CsqTableRow

| 项 | 说明 |
|---|---|
| 组件名 | `CsqTableRow` |
| 中文名 | 表格行 |
| 所属层级 | Table Components |
| 组件用途 | 统一行 hover、selected、clickable、disabled 状态。 |
| 适用场景 | 所有表格组件内部。 |
| Props 摘要 | `rowKey、selected、disabled、clickable、density` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | hover 高亮；active 压暗；selected 品牌色边线。 |
| Design Token 映射 | row-bg、row-hover、selected-bg、brand。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止整行用涨跌色作为背景；涨跌只作用于具体单元格。 |
| 是否 P0 必需 | 是 |

#### CsqTableCellNumber

| 项 | 说明 |
|---|---|
| 组件名 | `CsqTableCellNumber` |
| 中文名 | 数字单元格 |
| 所属层级 | Table Components |
| 组件用途 | 统一数字对齐、单位、精度、方向色。 |
| 适用场景 | 价格、金额、比例、数量、排名。 |
| Props 摘要 | `value、valueText、unit、precision、direction、align` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | hover 可显示完整值；默认右对齐。 |
| Design Token 映射 | number-font、market colors、text。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止自行换算业务口径；优先展示 valueText 或外部 formatter。 |
| 是否 P0 必需 | 是 |

#### CsqMiniTrendChart

| 项 | 说明 |
|---|---|
| 组件名 | `CsqMiniTrendChart` |
| 中文名 | 小型趋势图 |
| 所属层级 | Chart Components |
| 组件用途 | 卡片内轻量趋势线，不承载复杂坐标交互。 |
| 适用场景 | 指标卡、顶部 ticker、简短趋势预览。 |
| Props 摘要 | `points、height、direction、semantic、tooltip` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | hover 可显示简短 tooltip；不支持缩放。 |
| Design Token 映射 | chart-grid、market colors、series。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止作为历史分析主图；主图使用 CsqHistoryTrendChart。 |
| 是否 P0 必需 | 是 |

#### CsqHistoryTrendChart

| 项 | 说明 |
|---|---|
| 组件名 | `CsqHistoryTrendChart` |
| 中文名 | 历史趋势图 |
| 所属层级 | Chart Components |
| 组件用途 | 带坐标轴、图例、Tooltip、crosshair 的通用历史趋势图。 |
| 适用场景 | 历史序列、成交额、资金、家数、指数趋势。 |
| Props 摘要 | `data、xKey、series、range、showLegend、showCrosshair、formatters` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | hover crosshair；RangeSwitch 外部控制；点点击回调。 |
| Design Token 映射 | chart-axis、grid、crosshair、tooltip、series。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止写死某一业务序列名；series 由调用方配置。 |
| 是否 P0 必需 | 是 |

#### CsqDistributionChart

| 项 | 说明 |
|---|---|
| 组件名 | `CsqDistributionChart` |
| 中文名 | 分布图 |
| 所属层级 | Chart Components |
| 组件用途 | 展示区间桶、数量、占比和方向。 |
| 适用场景 | 涨跌幅分布、评分分布、区间统计。 |
| Props 摘要 | `buckets、orientation、selectedKey、onBucketClick` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | hover bucket tooltip；点击区间回调。 |
| Design Token 映射 | market colors、chart-grid、tooltip。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止只用颜色不显示数量；分布必须有可读标签或 Tooltip。 |
| 是否 P0 必需 | 是 |

#### CsqBarChart

| 项 | 说明 |
|---|---|
| 组件名 | `CsqBarChart` |
| 中文名 | 柱状图 |
| 所属层级 | Chart Components |
| 组件用途 | 支持单组/多组柱状图。 |
| 适用场景 | 组合柱图、历史统计、分类数量。 |
| Props 摘要 | `data、xKey、series、stacked、grouped、tooltip` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | hover 柱体；可点击柱组；支持空态。 |
| Design Token 映射 | bar-colors、chart-axis、tooltip。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止在 Core 中写死涨停/跌停；这些是 series 配置。 |
| 是否 P0 必需 | 是 |

#### CsqPieChartWithCallout

| 项 | 说明 |
|---|---|
| 组件名 | `CsqPieChartWithCallout` |
| 中文名 | 折线标注饼图 |
| 所属层级 | Chart Components |
| 组件用途 | 通用分类占比饼图，支持饼块占比文字和外部折线标注。 |
| 适用场景 | 资金结构、分类占比、行业结构、任意占比数据。 |
| Props 摘要 | `items、showSlicePercent、showCallout、centerContent、tooltipFormatter` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | hover 扇区突出；callout 对应扇区；点击扇区回调。 |
| Design Token 映射 | pie colors、callout-line、percent-text、tooltip。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止显示调试字段；禁止绑定资金业务；中心默认留空。 |
| 是否 P0 必需 | 是 |

#### CsqHeatMapGrid

| 项 | 说明 |
|---|---|
| 组件名 | `CsqHeatMapGrid` |
| 中文名 | 热力图网格 |
| 所属层级 | Chart Components |
| 组件用途 | 通用 N×M 热力图，支持语义色和中性热度色。 |
| 适用场景 | 板块热力、风险矩阵、分布矩阵、状态格。 |
| Props 摘要 | `rows、columns、items、semanticMode、tooltipFormatter` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | hover Tooltip；点击格子回调；空格占位。 |
| Design Token 映射 | heatmap colors、grid-gap、tooltip。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止命名为 SectorHeatMap；板块只是 Pattern 示例。 |
| 是否 P0 必需 | 是 |

#### CsqChartSplitPanel

| 项 | 说明 |
|---|---|
| 组件名 | `CsqChartSplitPanel` |
| 中文名 | 图表分栏面板 |
| 所属层级 | Chart Components |
| 组件用途 | 通用左右图表组合容器。 |
| 适用场景 | 饼图+趋势图、指标+图表、表格+图表。 |
| Props 摘要 | `left、right、ratio、gap、responsive、loading` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | 子组件独立交互；可响应式降级。 |
| Design Token 映射 | split-gap、surface、border。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止绑定为资金流模块；资金流只是 PatternMoneyFlowSplit。 |
| 是否 P0 必需 | 是 |

#### CsqChartTooltip

| 项 | 说明 |
|---|---|
| 组件名 | `CsqChartTooltip` |
| 中文名 | 图表 Tooltip |
| 所属层级 | Chart Components |
| 组件用途 | 统一图表浮层、序列值、时间和值格式。 |
| 适用场景 | 所有图表 hover。 |
| Props 摘要 | `title、items、position、formatter、maxWidth` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | 跟随鼠标或固定点位；支持键盘 focus。 |
| Design Token 映射 | tooltip-bg、border、text、shadow。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止在 Tooltip 中输出业务建议；只展示事实和值。 |
| 是否 P0 必需 | 是 |

#### CsqCrosshairOverlay

| 项 | 说明 |
|---|---|
| 组件名 | `CsqCrosshairOverlay` |
| 中文名 | 十字定位线 |
| 所属层级 | Chart Components |
| 组件用途 | 图表坐标定位层。 |
| 适用场景 | 历史趋势图、K线、分布图辅助定位。 |
| Props 摘要 | `x、y、visible、mode、labelFormatter` |
| 状态 | `default`、`hover`、`active`、`selected`、`disabled`、`loading`、`empty`、`error`。 |
| 交互 | 跟随 hover/focus；离开隐藏。 |
| Design Token 映射 | crosshair-line、axis-label。具体色值以 `03-design-tokens.md` 为准，组件只引用 Token，不硬编码颜色。 |
| 禁止误用 | 禁止滥用发光效果；不要遮挡图表主数据。 |
| 是否 P0 必需 | 是 |


### 19.5 重点组件详细契约

#### 19.5.1 CsqPieChartWithCallout

**定义**：通用折线标注饼图。它不绑定资金业务，支持任意分类占比结构。

**核心规则**：

1. 支持任意分类占比，建议 2～8 个分类。
2. 饼块面积按 `value` 计算。
3. `percent` 可由调用方传入，也可由组件基于 `value / sum(value)` 计算。
4. 饼块可显示占比，且饼块上的占比文字必须为白色。
5. 外部折线标注显示分类名称和数值。
6. 中心默认留空；`centerContent` 默认为 `null`。
7. 不显示调试字段、内部字段名或 API 字段名。
8. 不绑定“资金”“超大单”“大单”等业务概念；这些只能出现在 Pattern 或业务页面传入的数据中。

```ts
interface CsqPieChartWithCalloutProps {
  items: Array<{
    key: string;
    label: string;
    value: number;
    percent?: number;
    colorSemantic?: 'rise' | 'fall' | 'flat' | 'neutral' | 'custom';
    valueText?: string;
  }>;
  showSlicePercent?: boolean;
  showCallout?: boolean;
  centerContent?: null | string;
  size?: number;
  innerRadiusRatio?: number;
  minPercentLabelVisible?: number;
  tooltipFormatter?: (item: CsqPieCalloutItem) => string;
  onItemClick?: (key: string) => void;
}
```

**视觉结构**：饼图主体 + 饼块白色占比 + 外部折线 + 折线末端标签。Callout 线默认中性灰白，正负含义由文字或饼块色表达。

**状态**：default 正常展示；hover 扇区轻微外扩并高亮 callout；selected 使用品牌描边；loading 显示圆形骨架；empty 显示 CsqEmptyState；error 显示 CsqErrorState。

**Design Token 映射**：`--cs-chart-pie-size`、`--cs-chart-pie-slice-stroke`、`--cs-chart-pie-percent-color`、`--cs-chart-pie-callout-line-color`、`--cs-color-market-up/down/flat`、`--cs-color-tooltip-bg`。

**禁止误用**：不得在 Core 组件内写“净额结构”、`absAmount`、Tushare 字段、资金字段；不得使用两个饼图表达真实流入/流出，除非业务层明确提供真实流入额和流出额。

#### 19.5.2 CsqLinkedMetricList

**定义**：通用“实体 + 指标表现”的行式列表。它不绑定股票、板块、涨停、持仓或机会业务。

**核心规则**：

1. 每行一个实体。
2. 每行展示实体主信息、辅助信息、数值、涨跌文本、标签和元信息。
3. 行内信息必须打通，不做左右割裂的两个独立小模块。
4. 支持 `maxRows`，超出可由页面显示“更多”。
5. 行 hover 整行高亮，点击行触发 `onItemClick`。

```ts
interface CsqLinkedMetricListProps {
  title?: string;
  maxRows?: number;
  items: Array<{
    key: string;
    primaryText: string;
    secondaryText?: string;
    valueText?: string;
    changeText?: string;
    changeDirection?: 'rise' | 'fall' | 'flat' | 'neutral';
    tags?: Array<{
      label: string;
      semantic?: 'rise' | 'fall' | 'warning' | 'neutral' | 'brand';
    }>;
    meta?: string;
  }>;
  loading?: boolean;
  emptyText?: string;
  onItemClick?: (key: string) => void;
}
```

**视觉结构**：排名/图标可选 + 主文本 + 副文本 + 数值/变化 + 标签组 + meta。移动或窄容器下允许副文本换到第二行，但 tags 必须仍与同一实体关联。

**状态**：default 正常；hover 整行高亮；active 压暗；selected 品牌弱背景；loading 行骨架；empty 空态；error 局部错误。

**Design Token 映射**：`--cs-color-table-row-hover-bg`、`--cs-color-brand-accent-bg`、`--cs-color-market-up/down/flat`、`--cs-radius-sm`、`--cs-font-family-number`。

**禁止误用**：不得命名为 `CsqLimitUpLeaderPerformanceTable`；不得在 Props 中直接使用 `stockCode`、`streakLabel` 等业务字段作为 Core 契约。业务页面应通过 adapter 映射为 `primaryText`、`secondaryText`、`tags`、`meta`。

#### 19.5.3 CsqHeatMapGrid

**定义**：通用 N 行 × M 列热力图网格。

```ts
interface CsqHeatMapGridProps {
  rows: number;
  columns: number;
  items: Array<{
    key: string;
    label: string;
    value?: number;
    valueText?: string;
    semantic?: 'rise' | 'fall' | 'flat' | 'neutral' | 'warning';
    rowIndex?: number;
    columnIndex?: number;
    tooltip?: string;
  }>;
  colorMode?: 'market' | 'heat' | 'neutral';
  emptyCellStrategy?: 'placeholder' | 'hidden';
  onCellClick?: (key: string) => void;
}
```

**视觉结构**：固定行列网格，格子内展示 label 与 valueText。`colorMode='market'` 时红涨绿跌；`colorMode='heat'` 时使用中性热度色阶；`neutral` 用灰阶。

**交互**：hover 显示 CsqChartTooltip；点击格子回调；selected 由调用方控制。

**状态**：loading 显示网格骨架；empty 显示占位格或空态；error 显示局部错误。

**禁止误用**：不得把 `sectorCode`、`sectorName` 写入 Core Props；板块热力图应由 `PatternSectorHeatMap` 做适配。

#### 19.5.4 CsqRankTable

**定义**：通用排名表格，支持 TopN、高密度、列配置、涨跌色单元格。

```ts
interface CsqRankTableProps<Row = Record<string, unknown>> {
  rows: Row[];
  rowKey: keyof Row | ((row: Row) => string);
  columns: Array<{
    key: string;
    title: string;
    dataIndex?: keyof Row;
    width?: number | string;
    align?: 'left' | 'center' | 'right';
    sortable?: boolean;
    cellType?: 'text' | 'number' | 'change' | 'badge' | 'custom';
    formatter?: (value: unknown, row: Row) => string;
  }>;
  rankField?: keyof Row;
  topN?: number;
  density?: 'compact' | 'normal';
  loading?: boolean;
  emptyText?: string;
  onRowClick?: (row: Row) => void;
}
```

**视觉结构**：排名列 + 自定义列；数字右对齐；高密度行高 28～34px；表头可使用 CsqColumnHeader。

**状态**：loading TopN 行骨架；empty 空态；error 局部错误；hover 行高亮；selected 品牌弱背景。

**禁止误用**：不得把股票榜单字段固定为 Core 列；股票、板块、持仓等都应通过 columns 配置和业务 adapter 进入表格。

#### 19.5.5 CsqChartSplitPanel

**定义**：左右图表组合容器，可用于“饼图 + 趋势图”“柱图 + 表格”“分布图 + 指标组”等布局。

```ts
interface CsqChartSplitPanelProps {
  left: React.ReactNode;
  right: React.ReactNode;
  ratio?: [number, number];
  gap?: number | string;
  minLeftWidth?: number;
  minRightWidth?: number;
  responsive?: 'stack-below-md' | 'keep-split';
  loading?: boolean;
  error?: ErrorStateProps | null;
}
```

**视觉结构**：一个 Panel 内左右两区，默认比例 `[0.38, 0.62]` 或调用方指定；中间使用弱分割或间距，不使用强边框。

**交互**：左右子图各自独立交互；容器仅负责布局，不拦截子组件事件。

**禁止误用**：不得命名为 `CsqMoneyFlowPanel`；资金流只是 `PatternMoneyFlowSplit` 的使用示例。

### 19.6 Pattern Example 注册表

| Pattern | 中文名 | 组合方式 | 可参考业务场景 | 不是 Core 的原因 |
|---|---|---|---|---|
| `PatternMarketSummary` | 市场摘要组合 | `CsqMetricSummaryGroup` + `CsqMetricCard` + `CsqInfoRow` + `CsqHelpTooltip` | 今日市场客观总结、账户摘要、风控摘要 | 它绑定具体页面语义，不能作为通用组件契约 |
| `PatternIndexGrid` | 指数卡片矩阵 | `CsqMetricSummaryGroup` + `CsqMetricCard` + `CsqChangeValue` + `CsqMiniTrendChart` | 主要指数、宽基指数、策略指标矩阵 | 指数是业务对象，核心层只提供指标卡和栅格能力 |
| `PatternLimitStructure` | 涨停结构展示 | `CsqProgressList` + `CsqLinkedMetricList` + `CsqMetricSummaryGroup` + `CsqBarChart` | 涨停板块分布、领涨股涨停表现、历史涨跌停柱图 | 涨停属于市场总览/短线业务，不能进入 Core 命名 |
| `PatternMoneyFlowSplit` | 资金结构 + 趋势 | `CsqChartSplitPanel` + `CsqPieChartWithCallout` + `CsqHistoryTrendChart` + `CsqChartTooltip` | 单型资金净流向 + 历史资金流趋势 | 资金字段和净额口径属于业务适配层 |
| `PatternSectorHeatMap` | 板块热力图展示 | `CsqHeatMapGrid` + `CsqChartTooltip` + `CsqChangeValue` | 5×4 板块热力图、行业/概念矩阵 | 板块是业务对象，核心层只提供热力网格 |


### 19.7 Pattern Example 说明

#### PatternMarketSummary

由 `CsqMetricSummaryGroup`、`CsqMetricCard`、`CsqInfoRow`、`CsqHelpTooltip` 组合。可用于市场摘要、账户摘要、策略摘要等事实型摘要场景。Pattern 可以使用业务文案，但不得反向污染 Core 组件 Props。

#### PatternIndexGrid

由 `CsqMetricCard`、`CsqChangeValue`、`CsqMiniTrendChart` 和栅格布局组合。指数只是示例，未来也可展示宏观指标、板块指数、策略指标。

#### PatternLimitStructure

由 `CsqProgressList`、`CsqLinkedMetricList`、`CsqMetricSummaryGroup`、`CsqBarChart` 组合。用于说明涨停结构如何由通用组件拼装，不能把 `LimitUp*` 作为 Core。

#### PatternMoneyFlowSplit

由 `CsqChartSplitPanel`、`CsqPieChartWithCallout`、`CsqHistoryTrendChart` 组合。用于说明资金结构 + 历史趋势的组合方式。资金字段由页面 ViewModel 适配为通用分类占比和趋势 series。

#### PatternSectorHeatMap

由 `CsqHeatMapGrid`、`CsqChartTooltip`、`CsqChangeValue` 组合。板块名称、涨跌幅、成交额等只存在于 Pattern mock 或页面 adapter，不进入 Core Props。

### 19.8 不再作为 Core Component 的业务化旧命名清单

| 旧业务化命名 | 处理方式 | 推荐 Core / Pattern 替代 |
|---|---|---|
| `TopMarketBar` | 保留在市场总览章节中作为业务页面组件说明，不进入 Core 注册表 | `CsqTopBar` + `PatternIndexGrid` / 页面适配 |
| `GlobalSystemMenu` | 业务系统入口模式，不进入 Core 注册表 | `CsqTopBar`、`CsqTabs`、`CsqShortcutBar` |
| `IndexTickerStrip` | 行情 ticker 场景，不进入 Core 注册表 | `CsqTopBar` + `CsqChangeValue` + `CsqMiniTrendChart` |
| `IndexCard` | 指数业务卡，不进入 Core 注册表 | `CsqMetricCard` + `CsqChangeValue` + `CsqMiniTrendChart` |
| `MarketSummaryIndexSplit` | 市场总览布局 Pattern，不进入 Core 注册表 | `PatternMarketSummary` + `PatternIndexGrid` |
| `MarketSummaryFactCard` | 市场事实卡，不进入 Core 注册表 | `CsqMetricCard` |
| `MarketSummaryNoteCard` | 市场说明卡，不进入 Core 注册表 | `CsqInfoRow` / `CsqPanel` |
| `RankingTable` / `StockTable` | 历史业务页命名，后续实现应收敛为通用表格能力 | `CsqRankTable` / `CsqDataTable` |
| `SectorHeatMap` / `HeatMap` | 板块业务热力图命名，不进入 Core 注册表 | `CsqHeatMapGrid` / `PatternSectorHeatMap` |
| `LimitUpDistributionGrid` | 涨跌停 2×2 业务结构，不进入 Core 注册表 | `PatternLimitStructure` |
| `LimitUpSectorLeaderPanel` | 涨停板块业务组合，不进入 Core 注册表 | `CsqProgressList` + `CsqLinkedMetricList` |
| `LimitUpLeaderPerformanceTable` | 业务名不进入 Core 注册表 | `CsqLinkedMetricList` |
| `OrderSizeNetPieChart` / `OrderSizeNetPieChartWithCallout` | 单型资金业务名不进入 Core 注册表 | `CsqPieChartWithCallout` |
| `MoneyFlowNetStructurePanel` | 资金模块业务组合，不进入 Core 注册表 | `CsqChartSplitPanel` + `PatternMoneyFlowSplit` |
| `FundFlowBar` | 资金业务条形图，不进入 Core 注册表 | `CsqProgressList` / `CsqBarChart` |
| `LimitUpStreakLadder` / `HorizontalLimitUpStreakLadder` | 连板天梯业务组件，不进入 Core 注册表 | `PatternLimitStructure`，未来可抽象为通用 `CsqTimelineLadder` 后再评审 |


### 19.9 对 02 `component-library-demo-v1.html` 的组件使用建议

1. Demo 必须按组件层级展示：Foundation、Navigation、Data Display、Table、Chart、Pattern Examples、Component States。
2. Demo 使用单文件 HTML/CSS/JS，不依赖构建工具。
3. Demo 应优先深色主题，保留浅色主题切换入口或 Token 说明。
4. Demo 中的所有组件名必须使用 `Csq` 前缀，Pattern 区域不得使用 `Csq` 前缀。
5. 每个组件卡片展示：组件名、中文名、所属层级、用途、Props 摘要、状态、Design Token、预览、禁止误用。
6. `CsqPieChartWithCallout` 必须展示饼块白色占比、外部折线标注、中心留空、Tooltip。
7. `CsqLinkedMetricList` 必须展示 3 行以内实体 + 指标表现，并演示 hover 整行高亮。
8. `CsqHeatMapGrid` 必须展示 N×M 通用网格，不绑定板块字段，但 mock 可使用行情感名称。
9. `CsqRankTable` 必须展示 TopN、高密度、涨跌色单元格、loading/empty/error。
10. Pattern Examples 可以引用市场总览场景，但必须明确它们不是核心组件契约。
11. Demo 的 mock 数据必须真实感，但必须是组件级抽象数据，不绑定 API response 和 Tushare 字段。
12. 红涨绿跌必须正确；系统错误状态不能使用行情上涨红。

### 19.10 对 05 Codex 提示词的组件实现边界

给 Codex 实现组件库 Demo 或前端组件时，提示词必须包含：

```text
你要实现的是财势乾坤通用组件库 Demo，不是市场总览页面。

必须读取：
1. 财势乾坤/项目总说明/财势乾坤行情软件项目总说明_v_0_2.md
2. 财势乾坤/产品文档/组件库Demo产品需求文档 v0.2.md
3. 财势乾坤/设计/03-design-tokens.md
4. 财势乾坤/设计/04-component-guidelines.md

实现目标：
- 输出完整 component-library-demo-v1.html。
- Core Components 全部使用 Csq 前缀。
- Pattern Examples 不使用 Csq 前缀。
- 不把市场总览业务模块直接搬进组件库。
- Props 采用通用抽象，不引用 API response，不引用 Tushare 原始字段。
- 必须展示 default、hover、selected、active、loading、empty、error、disabled/data-delayed 等状态。
- 必须严格红涨绿跌。
- 视觉必须专业、沉稳、高密度、有金融终端感。

不要做：
- 不要实现 API 请求。
- 不要设计市场总览页面。
- 不要生成业务字段契约。
- 不要把 CsqPieChartWithCallout 命名为资金饼图。
- 不要把 CsqLinkedMetricList 命名为涨停表现组件。
- 不要把 CsqHeatMapGrid 命名为板块热力图。

Smoke test：
1. 打开 component-library-demo-v1.html 无白屏。
2. 每个分层至少展示一个组件预览。
3. CsqPieChartWithCallout 有白色饼块占比、外部折线标注、中心留空。
4. CsqLinkedMetricList 行 hover 整行高亮。
5. CsqHeatMapGrid hover 有 Tooltip。
6. CsqRankTable TopN、涨跌色、空态、加载态可见。
7. 红涨绿跌正确。
8. Pattern 区域清楚标明不是 Core Component 契约。
```

### 19.11 本轮组件库规范修改摘要

1. 新增通用组件库 Core Component 注册表，统一 `Csq` 前缀。
2. 将组件分为 Foundation、Navigation、Data Display、Table、Chart 五个 Core 层级。
3. 新增 Pattern Examples 层，承接行情业务组合示例，但不作为核心组件契约。
4. 明确旧业务化组件名不再作为 Core Component，例如 `LimitUpLeaderPerformanceTable`、`OrderSizeNetPieChartWithCallout`、`SectorHeatMap` 等。
5. 强化 `CsqPieChartWithCallout`、`CsqLinkedMetricList`、`CsqHeatMapGrid`、`CsqRankTable`、`CsqChartSplitPanel` 的 Props、状态、交互、Token 和禁用边界。
6. 明确 04 API 与数据字典不参与本轮组件库主流程；业务页面通过 adapter 将 API response 转为组件 Props。
7. 保留前文市场总览组件规范作为页面级历史基线，但从组件库 Core 层开始，命名和 Props 必须业务解耦。

### 19.12 待产品总控确认问题

1. 是否确认 `Csq` 作为所有 Core Component 的唯一前缀？
2. `Pattern Examples` 是否统一不使用 `Csq` 前缀？当前建议不使用，避免被误认为可直接导入的 Core 组件。
3. 是否需要在下一版中把旧市场总览业务组件章节整体移动到“页面 Pattern / Legacy Page Components”附录？当前本版为避免破坏基线，只新增注册表，不重排旧章节。
4. `CsqTopBar` 是否需要包含内置 ticker 插槽，还是只提供 `center` slot？当前建议只提供 slot，不绑定 ticker 业务。
5. `CsqRankTable` 是否需要内置 pagination？当前 Demo v1 建议不做，TopN 为主。
6. `CsqHeatMapGrid` 是否支持面积权重？当前建议 v1 固定网格，后续再引入 treemap 变体。
7. `CsqPieChartWithCallout.centerContent` 是否允许字符串？当前按 PRD 保留 `null | string`，但默认必须为 `null`。
8. 是否需要新增 `CsqStatsMatrixPanel` 作为通用 2×2 或 4×2 统计矩阵容器？PRD 示例提到旧命名可替换，但本轮清单未要求，建议后续评审。
9. 组件库 Demo 是否只展示深色主题，还是同时展示浅色主题切换？当前建议深色主展示 + 浅色 Token 对照。

### 19.13 建议放置路径与下载说明

建议保存到 Google Drive：

```text
财势乾坤/设计/04-component-guidelines.md
```

建议仓库路径：

```text
/docs/wealth/04-component-guidelines.md
```

对话交付文件：

```text
sandbox:/mnt/data/component-registry-output/04-component-guidelines.md
```

---

# 20. HTML Review v5 → market-overview-v1.4 连板天梯局部修订合并规范

> 本节为 Review v5 对“市场总览 / 连板天梯模块”的组件级修订。它不替代前文已确认的通用组件库注册表、市场总览页面组件规范或 Review v1～v4 已确认内容，而是在完整保留 v0.8 merged-full 基线的前提下，只追加连板天梯模块的新组件、Pattern、动态层级规则、展开/收起规则和 Mock 结构建议。  
> 本节不修改 TopMarketBar、Breadcrumb、PageHeader、ShortcutBar、今日市场客观总结、主要指数、涨跌分布、市场风格、成交额总览、大盘资金流向、榜单速览、涨跌停统计与分布、板块速览及其它 Review v5 未点名组件。

## 20.1 本轮读取文档与采用基线

| 序号 | 公共区文件 | 读取到的版本 / 状态 | 本轮用途 |
|---:|---|---|---|
| 1 | `财势乾坤/项目总说明/财势乾坤行情软件项目总说明_v_0_2.md` | `财势乾坤项目总说明 v0.2` / Review 草案 v0.2 | 继续约束产品定位、P0 范围、A 股优先、红涨绿跌、深色默认、专业沉稳风格。 |
| 2 | `财势乾坤/产品文档/市场总览产品需求文档 v0.2.md` | `市场总览产品需求文档 v0.2` / Review 草案 | 继续约束市场总览页面名称、归属、非目标、无固定 SideNav、客观事实页边界。 |
| 3 | `财势乾坤/设计/02-market-overview-page-design.md` | `市场总览页面设计文档 v0.1` | 作为市场总览页面设计基线；本轮仅修订连板天梯模块，不主动调整页面其它模块。 |
| 4 | `财势乾坤/设计/03-design-tokens.md` | `Design Token 与视觉规范 v0.3.1` | 采用 Review v5 中标准股票卡片、层级容器、晋级箭头、展开收起、五板以上层等 Token。 |
| 5 | `财势乾坤/设计/04-component-guidelines.md` | `P0 组件库与交互组件方案 v0.8 merged-full` | 本文件修订基线，完整保留此前内容并追加 Review v5 连板天梯修订。 |
| 6 | `财势乾坤/review/market-overview-html-review-v5.pdf` | `市场总览页review-v5` | 原始 Review 反馈依据。 |
| 7 | `财势乾坤/review/market-overview-html-review-v5-总控解读与变更单.md` | `市场总览 HTML Review v5｜总控解读与变更单` | 本轮直接变更单，规定只处理连板天梯模块。 |

本轮未能读取但应读取的文档：无。  
本轮是否继续：是。

---

## 20.2 本轮修订边界

### 20.2.1 允许修改区域

```text
市场总览 / 连板天梯模块
```

本轮允许新增或修订：

1. `CsqStockCompactCard`：标准股票卡片；
2. `MarketOverviewLimitLadder`：市场总览连板天梯业务复合组件；
3. `LimitLadderPromotionLayer`：昨日 N-1 板 → 今日 N 板晋级层；
4. `LimitLadderSpecialLayer`：五板以上独立层；
5. `LimitLadderFirstLayer`：首板独立层；
6. `LimitLadderExpandControl`：单层展开 / 收起控件；
7. 动态层级渲染规则；
8. 昨日层级与今日层级展示规则；
9. Showcase Mock 数据结构建议。

### 20.2.2 禁止主动修改区域

以下组件和模块保持 v0.8 merged-full 规范，不做主动改动：

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
- 今日市场客观总结相关组件
- 主要指数相关组件
- `MarketBreadthPanel` / 涨跌分布
- `MarketStylePanel` / 市场风格
- `TurnoverSummaryCard` / 成交额总览
- `MoneyFlowSummaryPanel` / 大盘资金流向
- `RankingTable` / 榜单速览
- `LimitUpDistributionGrid` / 涨跌停统计与分布
- `LimitUpSectorLeaderPanel` / 领涨股涨停表现
- `OrderSizeNetPieChart` / 资金饼图
- `SectorOverviewMatrix` / 板块速览矩阵
- `SectorHeatMap` / 板块热力图
- `CsqPieChartWithCallout`
- `CsqLinkedMetricList`
- `CsqHeatMapGrid`
- `CsqRankTable`
- 页面整体主题、全局字体、页面整体布局顺序、与 Review v5 无关的 Mock 数据结构

---

## 20.3 组件注册表补充：连板天梯相关组件与 Pattern

| 名称 | 类型 | 是否 Core Component | 是否 P0 必需 | 说明 |
|---|---|---:|---:|---|
| `CsqStockCompactCard` | Data Display Component | 是，行情终端领域通用组件 | 是 | 标准紧凑股票卡片，不绑定连板天梯，但绑定“股票”这一行情实体；可用于连板天梯、异动股、短线列表等场景。 |
| `MarketOverviewLimitLadder` | Market Overview Business Component / Pattern | 否 | 是 | 市场总览连板天梯业务复合组件，内部组合 `CsqStockCompactCard`、`LimitLadderPromotionLayer`、`LimitLadderSpecialLayer`、`LimitLadderFirstLayer`。 |
| `LimitLadderPromotionLayer` | Business Layer Component | 否 | 是 | 二板到五板的晋级层，表达“昨日 N-1 板 → 今日 N 板”。 |
| `LimitLadderSpecialLayer` | Business Layer Component | 否 | 是 | 五板以上独立层，只展示今日六板及以上。 |
| `LimitLadderFirstLayer` | Business Layer Component | 否 | 是 | 首板独立层，只展示今日首板。 |
| `LimitLadderExpandControl` | Interaction Subcomponent | 否，可作为局部子组件 | 是 | 单层展开 / 收起控件，默认 2 行 × 6 只，超出时出现。 |

说明：

1. `CsqStockCompactCard` 进入 Core Component 注册表，属于行情终端领域的通用股票展示组件。
2. `MarketOverviewLimitLadder` 是市场总览业务复合组件，不进入 Core Component。
3. `LimitLadderPromotionLayer`、`LimitLadderSpecialLayer`、`LimitLadderFirstLayer`、`LimitLadderExpandControl` 是连板天梯 Pattern 的内部结构组件，不作为通用组件库 Core 契约。
4. 后续若要抽象为更通用的“层级流转图”，应另起通用组件评审，不在本轮完成。

---

## 20.4 CsqStockCompactCard

| 项 | 说明 |
|---|---|
| 组件名 | `CsqStockCompactCard` |
| 中文名 | 标准紧凑股票卡片 |
| 所属层级 | Data Display Components / 行情终端领域通用组件 |
| 组件用途 | 以高密度卡片展示单只股票的名称、代码、最新价、涨跌幅、所属板块、开板次数或具体板数。 |
| 适用场景 | 市场总览连板天梯、短线异动股、股票候选列表、板块领涨股、机会雷达候选股等。 |
| 是否 P0 必需 | 是，Review v5 点名。 |
| 是否 Core Component | 是，但它是“股票展示领域组件”，不是市场总览专属组件；Props 不绑定 API response。 |
| 输入字段 / Props | `stockName`、`stockCode`、`latestPrice`、`changePct`、`sectorName`、`openTimes`、`currentStreakLevel`、`variant`、`clickable`、`loading`、`disabled`、`onClick`。 |
| 字段类型 | 见下方 TypeScript 接口。 |
| 视觉结构 | 左右两列、三行信息区：左上股票名称、左中股票代码、左下最新价；右上涨跌幅、右中所属板块、右下开板次数。五板以上层右下改显示具体板数。 |
| 交互行为 | hover 整卡高亮；click 进入个股详情页；支持键盘 focus / Enter 触发点击；层级标题不影响该卡点击行为。 |
| 状态 | default：正常卡片；hover：整卡背景、边框、阴影增强；active：轻微压暗或下移 1px；selected：品牌金弱背景/边框，可选；disabled：透明度降低且不触发点击；loading/empty/error 由父容器处理，卡片自身可支持 skeleton 但不是本轮重点。 |
| 涨跌色规则 | `changePct > 0` 和涨停相关为红；`changePct < 0` 为绿；`changePct = 0` 为灰白。最新价可跟随涨跌方向；股票名称、代码、板块为中性色；开板次数使用警示/中性色；五板以上具体板数使用品牌金弱强调。 |
| Design Token 映射 | `--cs-stock-card-*`、`--cs-color-market-up/down/flat`、`--cs-font-family-number`、`--cs-color-brand-accent-*`、`--cs-color-warning`。 |
| 禁止误用 | 不要在卡片中展示买卖建议、机会评分、市场温度、风险指数；不要把整卡背景涂成大面积红色/绿色；不要用绿色表示上涨；不要让卡片承载 API 原始字段名。 |

```ts
interface CsqStockCompactCardProps {
  stockName: string;
  stockCode: string;
  latestPrice: number | null;
  changePct: number | null;
  sectorName: string;
  openTimes?: number | null;
  currentStreakLevel?: number | null;
  variant?: 'normal' | 'aboveFive';
  clickable?: boolean;
  disabled?: boolean;
  selected?: boolean;
  loading?: boolean;
  priceText?: string;
  changePctText?: string;
  openTimesText?: string;
  onClick?: (stockCode: string) => void;
}
```

### 20.4.1 字段位置规则

```text
┌──────────────────────────────┐
│ 左上：股票名称      右上：涨跌幅 │
│ 左中：股票代码      右中：所属板块 │
│ 左下：最新价        右下：开板次数 │
└──────────────────────────────┘
```

五板以上层特殊结构：

```text
┌──────────────────────────────┐
│ 左上：股票名称      右上：涨跌幅 │
│ 左中：股票代码      右中：所属板块 │
│ 左下：最新价        右下：6板/7板 │
└──────────────────────────────┘
```

### 20.4.2 展示规则

1. `stockName`：左上，主文字，单行省略。
2. `stockCode`：左中，弱文字，等宽数字。
3. `latestPrice`：左下，等宽数字；可根据涨跌方向着色。
4. `changePct`：右上，等宽数字，红涨绿跌，正数必须带 `+`。
5. `sectorName`：右中，中性文字，单行省略。
6. `openTimes`：右下，普通层级显示；文案可为 `0次`、`未开板`、`开板2次`，具体文案由 02 Showcase 决定。
7. `currentStreakLevel`：五板以上层显示，文案如 `6板`、`7板`、`8板`，不显示 openTimes。
8. 若 `latestPrice`、`changePct` 缺失，显示 `--`，不伪造数据。

### 20.4.3 点击与可访问性

1. `clickable=true` 时整卡可点击，进入个股详情页。
2. 点击回调只传 `stockCode`，页面层决定路由参数，例如 `tradeDate`。
3. 支持 `tabIndex=0`、`role=button`、`Enter` / `Space` 触发。
4. disabled 卡片不触发点击，Tooltip 可说明原因。
5. loading、empty、error 不建议在单卡内逐个展示，优先由父层容器处理。

---

## 20.5 MarketOverviewLimitLadder

| 项 | 说明 |
|---|---|
| 组件名 | `MarketOverviewLimitLadder` |
| 中文名 | 市场总览连板天梯 |
| 所属层级 | Pattern Examples / Market Overview Business Component |
| 组件用途 | 在市场总览中展示当日连板结构，以“昨日层级 → 今日晋级层级”的方式呈现短线连板梯队。 |
| 是否 Core Component | 否。它是市场总览业务复合组件，不进入通用组件库 Core Component。 |
| 是否 P0 必需 | 是，Review v5 点名。 |
| 内部组件 | `LimitLadderSpecialLayer`、`LimitLadderPromotionLayer`、`LimitLadderFirstLayer`、`LimitLadderExpandControl`、`CsqStockCompactCard`。 |
| 输入字段 / Props | `highestStreakLevel`、`specialLayer`、`promotionLayers`、`firstLayer`、`expandedLayerKeys`、`maxRows`、`maxColumns`、`onToggleLayer`、`onStockClick`。 |
| 字段类型 | 见下方 TypeScript 接口。 |
| 视觉结构 | 高板层在上，首板层在下。若出现六板及以上，最顶部渲染“五板以上”独立层；二板至五板使用左右晋级结构；首板为独立层。 |
| 交互行为 | 股票卡片点击进入个股详情；每层独立展开/收起；层级标题不支持点击；晋级箭头不支持点击。 |
| 状态 | default：按最高板动态渲染层级；loading：层级标题骨架 + 2 行股票卡片骨架；empty：无连板数据时显示空态，但如果有首板只显示首板层；error：连板模块局部错误，不影响其它模块。 |
| 涨跌色规则 | 股票卡片内部红涨绿跌；层级容器不大面积红绿；五板以上使用品牌金弱强调；晋级箭头使用品牌金弱强调，不表达买卖方向。 |
| Design Token 映射 | `--cs-limit-ladder-*`、`--cs-stock-card-*`、`--cs-color-brand-accent-*`、`--cs-color-market-*`。 |
| 禁止误用 | 不输出“强势推荐”“买入”“短线机会”等主观判断；不因天梯重构修改页面其它模块；不将今日五板归入五板以上层。 |

```ts
interface MarketOverviewLimitLadderProps {
  tradeDate: string;
  highestStreakLevel: number;
  specialLayer?: LimitLadderSpecialLayerData | null;
  promotionLayers: LimitLadderPromotionLayerData[];
  firstLayer: LimitLadderFirstLayerData;
  expandedLayerKeys?: string[];
  maxRows?: number;      // default: 2
  maxColumns?: number;   // default: 6
  loading?: boolean;
  error?: ErrorStateProps | null;
  onToggleLayer?: (layerKey: string, expanded: boolean) => void;
  onStockClick?: (stockCode: string) => void;
}
```

---

## 20.6 LimitLadderPromotionLayer

| 项 | 说明 |
|---|---|
| 组件名 | `LimitLadderPromotionLayer` |
| 中文名 | 连板晋级层 |
| 所属层级 | Market Overview Business Subcomponent |
| 组件用途 | 展示二板到五板的晋级关系：`昨日 N-1 板 → 今日 N 板`。 |
| 是否 Core Component | 否。它是连板天梯业务 Pattern 内部结构。 |
| 使用范围 | 今日二板、今日三板、今日四板、今日五板。 |
| Props | `level`、`previousLabel`、`currentLabel`、`previousStocks`、`currentStocks`、`expanded`、`maxRows`、`maxColumns`、`onToggleExpand`、`onStockClick`。 |
| 视觉结构 | 左侧昨日层级容器，中间品牌金弱箭头，右侧今日晋级层级容器。 |
| previousStocks 规则 | 展示昨日该层级全量股票，卡片信息使用今日行情数据，不只是晋级成功股票。 |
| currentStocks 规则 | 只展示从 previousStocks 中成功晋级到今日 N 板的股票，卡片信息使用今日行情数据。 |
| 标题规则 | 左标题为 `昨日 N-1 板`，右标题为 `今日 N 板`；标题不支持点击。 |
| 交互 | 股票卡片点击进入个股详情；展开/收起只影响当前层；箭头和标题不点击。 |
| 状态 | loading：左右容器显示骨架；empty：某侧无数据时保留容器并显示空态；error：当前层错误不影响其它层。 |
| 涨跌色规则 | 股票卡片内部按红涨绿跌；箭头和选中态使用品牌金；容器背景中性。 |

```ts
interface LimitLadderPromotionLayerProps {
  level: number; // 2..5
  previousLabel: string; // 昨日首板 / 昨日二板 / 昨日三板 / 昨日四板
  currentLabel: string;  // 今日二板 / 今日三板 / 今日四板 / 今日五板
  previousStocks: LimitLadderStockCard[];
  currentStocks: LimitLadderStockCard[];
  expanded?: boolean;
  maxRows?: number;
  maxColumns?: number;
  loading?: boolean;
  error?: ErrorStateProps | null;
  onToggleExpand?: (expanded: boolean) => void;
  onStockClick?: (stockCode: string) => void;
}
```

### 20.6.1 展示示例

```text
昨日二板                         →                         今日三板
[股票卡][股票卡][股票卡]                                  [股票卡][股票卡]
[股票卡][股票卡][股票卡]                                  [股票卡]
```

规则：

1. 左侧昨日层级展示昨日二板的全量股票，包括今日未晋级的股票。
2. 右侧今日层级只展示成功晋级到今日三板的股票。
3. 两侧股票卡片均使用今日行情数据。

---

## 20.7 LimitLadderSpecialLayer

| 项 | 说明 |
|---|---|
| 组件名 | `LimitLadderSpecialLayer` |
| 中文名 | 五板以上独立层 |
| 所属层级 | Market Overview Business Subcomponent |
| 组件用途 | 展示今日六板及以上股票。 |
| 是否 Core Component | 否。 |
| 使用条件 | 今日出现六板及以上股票时渲染。 |
| 结构规则 | 顶部独立层，不展示晋级箭头。 |
| 股票范围 | 只展示今日六板及以上，不包含今日五板。 |
| 卡片特殊规则 | `CsqStockCompactCard.variant='aboveFive'`；右下显示 `currentStreakLevel`，如 `6板`、`7板`，不显示 openTimes。 |
| 交互 | 股票卡片点击进入个股详情；支持展开/收起；标题不点击。 |
| 视觉规则 | 背景使用弱品牌金或中性强化边框；不得大面积使用红色。 |
| 状态 | loading、empty、error 同层级容器处理。 |

```ts
interface LimitLadderSpecialLayerProps {
  type: 'aboveFive';
  label: '五板以上';
  stocks: LimitLadderStockCard[];
  expanded?: boolean;
  maxRows?: number;
  maxColumns?: number;
  loading?: boolean;
  error?: ErrorStateProps | null;
  onToggleExpand?: (expanded: boolean) => void;
  onStockClick?: (stockCode: string) => void;
}
```

### 20.7.1 五板以上层约束

1. “五板以上”只展示今日六板及以上。
2. 今日五板仍属于 `昨日四板 → 今日五板` 的晋级层。
3. 五板以上层不显示成 `昨日五板 → 今日六板`。
4. 五板以上层不显示晋级箭头。
5. 五板以上卡片右下显示具体板数，不显示开板次数。

---

## 20.8 LimitLadderFirstLayer

| 项 | 说明 |
|---|---|
| 组件名 | `LimitLadderFirstLayer` |
| 中文名 | 首板独立层 |
| 所属层级 | Market Overview Business Subcomponent |
| 组件用途 | 展示今日首板股票。 |
| 是否 Core Component | 否。 |
| 使用条件 | 只要今日存在首板股票即可渲染；如果今日只有首板，则整个连板天梯只渲染该层。 |
| 股票范围 | 只展示今日首板。 |
| 结构规则 | 独立一层，无昨日来源，无晋级箭头。 |
| 交互 | 股票卡片点击进入个股详情；支持展开/收起；标题不点击。 |
| 状态 | loading、empty、error 同层级容器处理。 |
| 涨跌色规则 | 股票卡片内部红涨绿跌；层级容器中性。 |

```ts
interface LimitLadderFirstLayerProps {
  type: 'first';
  label: '首板';
  stocks: LimitLadderStockCard[];
  expanded?: boolean;
  maxRows?: number;
  maxColumns?: number;
  loading?: boolean;
  error?: ErrorStateProps | null;
  onToggleExpand?: (expanded: boolean) => void;
  onStockClick?: (stockCode: string) => void;
}
```

---

## 20.9 LimitLadderExpandControl

| 项 | 说明 |
|---|---|
| 组件名 | `LimitLadderExpandControl` |
| 中文名 | 连板层级展开 / 收起控件 |
| 所属层级 | Interaction Subcomponent |
| 组件用途 | 控制单个层级股票卡片列表的展开和收起。 |
| 是否 Core Component | 否，可作为局部子组件。 |
| 默认折叠规则 | 每层最多展示 2 行 × 6 只 = 12 只股票。 |
| 出现条件 | 当前层股票数量超过 `maxRows * maxColumns` 时出现。 |
| 折叠态文案 | `展开全部`，可带双向下箭头。 |
| 展开态文案 | `收起`。 |
| 作用范围 | 只影响当前层，不影响其它层。 |
| 交互 | 点击切换 expanded；hover 使用中性 + 品牌金强调；不使用红绿。 |
| 状态 | default、hover、active、disabled。loading/empty/error 由父层处理。 |

```ts
interface LimitLadderExpandControlProps {
  expanded: boolean;
  totalCount: number;
  visibleCount: number;
  disabled?: boolean;
  expandText?: string;   // default: 展开全部
  collapseText?: string; // default: 收起
  onToggle: (expanded: boolean) => void;
}
```

### 20.9.1 展开 / 收起规则

1. 默认折叠时，最多展示 `2 行 × 6 只`。
2. 股票数超过 12 只时，显示“展开全部”。
3. 展开后显示全部股票，并显示“收起”。
4. 点击“收起”后恢复 12 只展示。
5. 展开/收起只影响当前层级。
6. 展开后允许当前层向下撑开，或在连板天梯模块内部滚动；不得压缩或重排 Review v5 未点名模块。

---

## 20.10 动态层级渲染规则

### 20.10.1 今日最高板 <= 5

如果今日最高板为 `N`，且 `N <= 5`，则渲染 `N` 层。

示例：今日最高三板：

```text
第 3 层：昨日二板 → 今日三板
第 2 层：昨日首板 → 今日二板
第 1 层：首板
```

示例：今日只有首板：

```text
第 1 层：首板
```

示例：今日最高五板：

```text
第 5 层：昨日四板 → 今日五板
第 4 层：昨日三板 → 今日四板
第 3 层：昨日二板 → 今日三板
第 2 层：昨日首板 → 今日二板
第 1 层：首板
```

### 20.10.2 今日出现六板及以上

如果今日出现六板及以上，则渲染 6 层：

```text
第 6 层：五板以上
第 5 层：昨日四板 → 今日五板
第 4 层：昨日三板 → 今日四板
第 3 层：昨日二板 → 今日三板
第 2 层：昨日首板 → 今日二板
第 1 层：首板
```

规则：

1. 五板以上只展示今日六板及以上；
2. 五板以上不包含今日五板；
3. 今日五板仍属于 `昨日四板 → 今日五板`；
4. 五板以上层独立置顶；
5. 五板以上层不显示晋级箭头；
6. 五板以上卡片右下显示 `currentStreakLevel`。

### 20.10.3 昨日层级展示规则

1. 昨日层级展示昨日属于该层级的所有股票。
2. 昨日层级中的卡片数据使用今天行情数据。
3. 昨日层级不只是晋级成功股票。
4. 如果某股昨天是二板、今天未晋级，它仍显示在 `昨日二板` 左侧。
5. 昨日层级用于观察昨日该层级股票今日的整体去向与状态。

### 20.10.4 今日晋级层级展示规则

1. 今日层级只展示晋级成功股票。
2. 今日层级中的卡片数据使用今天行情数据。
3. 成功晋级股票也会出现在左侧昨日层级中，因为左侧是昨日层级全量集合。
4. 今日层级用于突出晋级结果。

### 20.10.5 首板层规则

1. 首板层只展示今日首板。
2. 首板层没有昨日来源。
3. 首板层独立成层。
4. 首板层支持展开/收起。
5. 首板股票点击进入个股详情。

---

## 20.11 Mock 数据结构建议

> 本节结构仅用于 Showcase Mock 和组件设计，不作为正式 API 契约。  
> 本轮不要求 04 API 与数据字典参与，也不正式修改 API 文档。

```ts
interface LimitLadderStockCard {
  stockCode: string;
  stockName: string;
  latestPrice: number;
  changePct: number;
  sectorName: string;
  openTimes: number;
  currentStreakLevel?: number;
}

interface LimitLadderPromotionLayer {
  level: number;
  previousLabel: string;
  currentLabel: string;
  previousStocks: LimitLadderStockCard[];
  currentStocks: LimitLadderStockCard[];
  expanded?: boolean;
}

interface LimitLadderSpecialLayer {
  type: 'aboveFive';
  label: '五板以上';
  stocks: LimitLadderStockCard[];
  expanded?: boolean;
}

interface LimitLadderFirstLayer {
  type: 'first';
  label: '首板';
  stocks: LimitLadderStockCard[];
  expanded?: boolean;
}

interface MarketOverviewLimitLadderMock {
  tradeDate: string;
  highestStreakLevel: number;
  specialLayer?: LimitLadderSpecialLayer | null;
  promotionLayers: LimitLadderPromotionLayer[];
  firstLayer: LimitLadderFirstLayer;
}
```

### 20.11.1 Mock 结构规则

1. `previousStocks` 是昨日该层级全量股票，但股票信息使用今日数据。
2. `currentStocks` 是今日晋级成功股票。
3. `aboveFive.stocks` 仅展示今日六板及以上。
4. `currentStreakLevel` 只在五板以上层右下显示具体板数时使用。
5. `openTimes` 在普通层右下显示；五板以上层不显示 `openTimes`。
6. 该结构不绑定正式 API，不引用 Tushare 原字段。

---

## 20.12 对 02 `market-overview-v1.4.html` 的组件使用建议

1. 只修改连板天梯模块。
2. 不修改 TopMarketBar、Breadcrumb、PageHeader、ShortcutBar、今日市场客观总结、主要指数、涨跌分布、市场风格、成交额总览、大盘资金流向、榜单速览、涨跌停统计与分布、板块速览。
3. 使用 `CsqStockCompactCard` 作为天梯内的股票展示单元。
4. 股票卡字段位置必须固定：左上股票名称、左中股票代码、左下最新价、右上涨跌幅、右中所属板块、右下开板次数。
5. 五板以上层卡片右下显示具体板数，不显示开板次数。
6. 二板及以上层级使用 `LimitLadderPromotionLayer`：`昨日 N-1 板 → 今日 N 板`。
7. 昨日层级展示昨日该层级全量股票，且卡片使用今日行情数据。
8. 今日层级只展示晋级成功股票。
9. 首板层使用 `LimitLadderFirstLayer`，只展示今日首板，无昨日来源。
10. 六板及以上使用 `LimitLadderSpecialLayer`，标题为“五板以上”，独立置顶。
11. 五板以上不包含今日五板；今日五板仍在 `昨日四板 → 今日五板`。
12. 每层默认最多展示 2 行 × 6 只；超过 12 只时显示 `LimitLadderExpandControl`。
13. 展开/收起只影响当前层。
14. 股票卡片 hover 整卡高亮，click 进入个股详情页。
15. 层级标题不支持点击，不做链接样式。
16. 晋级箭头只表达层级关系，不做点击态。
17. 使用深色金融终端风格，不照搬用户草图中的浅色背景。
18. 红涨绿跌必须正确；不得输出买卖建议或主观结论。

---

## 20.13 对 01 Design Token 的依赖

本节依赖 `03-design-tokens.md v0.3.1` 中以下 Token 或规则：

| 组件 / Pattern | Token / 规则 |
|---|---|
| `CsqStockCompactCard` | `--cs-stock-card-*`、`--cs-color-market-*`、`--cs-font-family-number` |
| `MarketOverviewLimitLadder` | `--cs-limit-ladder-*`、`--cs-stock-card-*` |
| `LimitLadderPromotionLayer` | `--cs-limit-ladder-layer-bg`、`--cs-limit-ladder-layer-border`、`--cs-limit-ladder-layer-title-*` |
| `LimitLadderSpecialLayer` | `--cs-limit-ladder-layer-bg-above-five`、`--cs-limit-ladder-layer-border-emphasis` |
| `LimitLadderFirstLayer` | `--cs-limit-ladder-layer-bg`、`--cs-limit-ladder-layer-border` |
| `LimitLadderExpandControl` | `--cs-limit-ladder-expand-*` |
| 晋级箭头 | `--cs-limit-ladder-arrow-*` |
| 股票卡片网格 | `--cs-limit-ladder-stock-grid-gap-x`、`--cs-limit-ladder-stock-grid-gap-y`、`--cs-stock-card-width` |

必须遵守：

1. 股票卡 hover / active / clickable 状态使用 `--cs-stock-card-*`；
2. 展开 / 收起使用中性 + 品牌金 hover，不使用红绿；
3. 晋级箭头使用品牌金弱强调，不表达买卖方向；
4. 五板以上层使用弱品牌金强调，不大面积红色；
5. 红涨绿跌规则不变；
6. Review v5 未点名区域 Token 不修改。

---

## 20.14 是否需要后续拉 04 参与的条件

本轮不要求 04 API 与数据字典参与，因为当前任务只要求组件设计和 Showcase Mock 结构建议。

后续在以下任一条件出现时，需要单独拉 04 参与：

1. 需要把 `MarketOverviewLimitLadderMock` 转为正式 API 契约；
2. 现有 `streakLadder` 数据无法区分昨日层级全量股票与今日晋级股票；
3. 无法获取“昨日 N-1 板全量股票但使用今日行情数据”的 ViewModel；
4. 无法识别今日六板及以上股票并排除今日五板；
5. 缺少 `openTimes`、`currentStreakLevel`、`sectorName`、`latestPrice`、`changePct` 等字段；
6. 需要定义连板层级跨交易日追踪口径；
7. 需要明确 ST 股票是否纳入连板层级；
8. 需要将展开/收起后的分页或增量加载从前端 mock 改为后端接口。

---

## 20.15 本轮 Review v5 修改摘要

1. 只修订 `市场总览 / 连板天梯模块`。
2. 新增 `CsqStockCompactCard`，作为标准紧凑股票卡片。
3. 新增 `MarketOverviewLimitLadder`，作为市场总览连板天梯业务复合组件。
4. 新增 `LimitLadderPromotionLayer`，用于 `昨日 N-1 板 → 今日 N 板` 晋级层。
5. 新增 `LimitLadderSpecialLayer`，用于“五板以上”独立层。
6. 新增 `LimitLadderFirstLayer`，用于首板独立层。
7. 新增 `LimitLadderExpandControl`，用于当前层展开/收起。
8. 写入动态层级规则：最高板 <= 5 时渲染 N 层；出现六板及以上时渲染 6 层。
9. 明确昨日层级展示昨日该层级全量股票，卡片信息使用今日数据。
10. 明确今日层级只展示晋级成功股票。
11. 明确首板层只展示今日首板。
12. 明确五板以上只展示今日六板及以上，不包含今日五板。
13. 明确股票卡片点击进入个股详情页，层级标题不支持点击。
14. 明确本轮不修改 Review v5 未点名组件。

---

## 20.16 本轮新增或修订组件清单

| 类型 | 组件 / Pattern | 处理方式 |
|---|---|---|
| 新增 | `CsqStockCompactCard` | 新增标准紧凑股票卡片，Core Component 候选。 |
| 新增 | `MarketOverviewLimitLadder` | 新增市场总览连板天梯业务复合组件，不进入 Core。 |
| 新增 | `LimitLadderPromotionLayer` | 新增二板到五板晋级层。 |
| 新增 | `LimitLadderSpecialLayer` | 新增五板以上独立层。 |
| 新增 | `LimitLadderFirstLayer` | 新增首板独立层。 |
| 新增 | `LimitLadderExpandControl` | 新增单层展开/收起控件。 |
| 修订 | `HorizontalLimitUpStreakLadder` / 旧连板天梯表达 | 市场总览 v1.4 起由 `MarketOverviewLimitLadder` 替代；旧组件名保留历史兼容，但不作为新 Showcase 的推荐实现。 |
| 修订 | `PatternLimitStructure` | 可在 Pattern Examples 中引用 `MarketOverviewLimitLadder` 的组合思路，但 Pattern 本身不替代业务组件。 |

---

## 20.17 本轮未修改组件清单

以下组件保持 v0.8 merged-full 规范，不做主动改动：

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
- 今日市场客观总结相关组件
- `IndexGrid`
- `IndexCard`
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
- `MoneyFlowNetStructurePanel`
- `OrderSizeNetPieChart`
- `RankingTable`
- `StockTable`
- `SortableHeader`
- `TabPanel`
- `LimitUpSummaryCard`
- `LimitUpDistributionGrid`
- `LimitUpSectorLeaderPanel`
- `LimitUpLeaderPerformanceTable`
- `LimitUpDownHistoryBarChart`
- `SectorOverviewMatrix`
- `SectorHeatMap`
- `CsqPieChartWithCallout`
- `CsqLinkedMetricList`
- `CsqHeatMapGrid`
- `CsqRankTable`
- `CsqChartSplitPanel`
- `HelpTooltip`
- `RangeSwitch`
- `LoadingSkeleton`
- `EmptyState`
- `ErrorState`
- `DataDelayState`
- `PermissionState`

本轮因 Review v5 修改而被动影响的区域：无。  
原因：本轮只替换连板天梯模块内部结构，不影响其它模块。  
是否需要产品总控确认：否。

---

## 20.18 待产品总控确认问题

1. `CsqStockCompactCard` 宽度是否固定为 148px，还是允许在 1366px 下压缩到 136px？
2. 连板天梯在 1366px 宽度下是否允许每行从 6 只自动降级为 5 只？当前建议允许，但不破坏字段结构。
3. 展开后优先使用“模块内部滚动”还是“模块向下撑开”？当前建议优先模块内部滚动或局部展开，避免影响其它模块。
4. 五板以上层标题是否固定为“五板以上”，还是展示“六板及以上”？当前按 Review v5 使用“五板以上”。
5. `openTimes=0` 时显示 `0次`、`未开板`，还是 `--`？建议 `未开板`，但由 02 Showcase 最终确认。
6. 层级标题右侧是否展示股票数量，例如 `12只`？当前建议允许展示。
7. 昨日层级中今日已断板或下跌股票是否仍使用红涨绿跌显示今日涨跌幅？当前规则是使用今日行情数据，因此应按今日涨跌方向显示。
8. 是否需要在 Tooltip 中解释“昨日层级股票使用今日行情数据”？建议通过 HelpTooltip 或层级说明提供。
9. 如果某层 currentStocks 为空但 previousStocks 不为空，右侧今日层级是否显示空态“暂无晋级”？当前建议保留右侧容器并显示空态。

---

## 20.19 Review v5 验收清单

| 验收项 | 要求 |
|---|---|
| 完整文档 | 本文件仍是完整 `04-component-guidelines.md`，不是 delta 文档。 |
| 修改边界 | 只新增/修订 Review v5 点名的连板天梯模块。 |
| 标准股票卡 | `CsqStockCompactCard` 字段位置、hover、click、五板以上右下具体板数定义清晰。 |
| 业务组件 | `MarketOverviewLimitLadder` 明确为市场总览业务复合组件，不进入 Core。 |
| 动态层级 | 最高板 <= 5 与出现六板及以上两种渲染规则完整。 |
| 昨日层级 | 展示昨日该层级全量股票，卡片使用今日数据。 |
| 今日层级 | 只展示晋级成功股票，卡片使用今日数据。 |
| 首板层 | 只展示今日首板，独立一层。 |
| 五板以上 | 只展示今日六板及以上，不包含今日五板。 |
| 展开收起 | 默认 2 行 × 6 只；超出展开全部；展开后收起；只影响当前层。 |
| 交互 | 股票卡片点击进入个股详情；标题和箭头不点击。 |
| 红涨绿跌 | 最新价和涨跌幅必须红涨绿跌，平盘灰白。 |
| 04 参与 | 本轮只提供 Mock 结构建议，不正式修改 API；明确后续拉 04 条件。 |
| 未授权改动 | 未修改 Review v5 未点名组件或页面整体布局。 |

---

## 20.20 建议放置到 Google Drive 的路径

```text
财势乾坤/设计/04-component-guidelines.md
```

## 20.21 建议仓库保存路径

```text
/docs/wealth/04-component-guidelines.md
```

## 20.22 本轮输出文件下载链接

对话交付文件：

```text
sandbox:/mnt/data/review-v5-output-final/04-component-guidelines.md
```

---

## 21. HTML Review v6 → market-overview-v1.5 标准股票卡片局部修订合并规范

> 本节为 `market-overview-html-review-v6` 的全量合并内容。它不替代前文已确认的组件规范，而是在完整保留 v0.9 merged-full 基线的前提下，只对 Review v6 明确点名的 `CsqStockCompactCard` 做结构修订。  
> 自 `market-overview-v1.5.html` 起，市场总览连板天梯中的标准股票卡片默认结构以本节为准。此前 Review v5 中关于 `openTimes` 右下默认展示、`currentStreakLevel` 五板以上覆盖展示的描述，降级为历史规则或可选扩展，不再作为本卡片默认结构。  
> 本节不修改 `MarketOverviewLimitLadder`、`LimitLadderPromotionLayer`、`LimitLadderSpecialLayer`、`LimitLadderFirstLayer`、`LimitLadderExpandControl` 的层级逻辑、展开/收起逻辑和点击逻辑。

### 21.1 本轮读取文档与采用基线

| 序号 | 公共区文件 | 读取到的版本 / 状态 | 本轮用途 |
|---:|---|---|---|
| 1 | `财势乾坤/项目总说明/财势乾坤行情软件项目总说明_v_0_2.md` | `财势乾坤项目总说明 v0.2` / Review 草案 v0.2 | 继续约束项目定位、P0 范围、专业沉稳风格、A 股红涨绿跌和不输出买卖建议。 |
| 2 | `财势乾坤/产品文档/市场总览产品需求文档 v0.2.md` | `市场总览产品需求文档 v0.2` / Review 草案 | 继续约束市场总览页面名称、归属、非目标、无固定 SideNav 和客观事实边界。 |
| 3 | `财势乾坤/设计/02-market-overview-page-design.md` | `市场总览页面设计文档 v0.1` | 作为页面设计基线；本轮不改页面整体布局。 |
| 4 | `财势乾坤/设计/03-design-tokens.md` | `Design Token 与视觉规范 v0.3.2` / Review v6 修订 | 作为 `CsqStockCompactCard` 的视觉 Token 依据。 |
| 5 | `财势乾坤/设计/04-component-guidelines.md` | `P0 组件库与交互组件方案 v0.9 merged-full` | 本文件的完整修订基线，保留此前内容并追加本节。 |
| 6 | `财势乾坤/review/market-overview-html-review-v6.pdf` | `市场总览页review-v6` | 原始 Review 反馈依据。 |
| 7 | `财势乾坤/review/market-overview-html-review-v6-总控解读与变更单.md` | `市场总览 HTML Review v6｜总控解读与变更单` / 产品总控解读草案 | 本轮直接变更单，限定只修订标准股票卡片。 |

本轮未能读取但应读取的文档：无。  
本轮是否继续：是。

---

### 21.2 本轮修订边界

#### 21.2.1 允许修改区域

本轮只允许修订：

```text
市场总览 / 连板天梯 / 标准股票卡片
```

具体对应组件：

```text
CsqStockCompactCard
```

#### 21.2.2 禁止主动修改区域

以下组件、模块和规则保持 v0.9 merged-full 规范，不做主动改动：

- `TopMarketBar`
- `Breadcrumb`
- `PageHeader`
- `ShortcutBar`
- 今日市场客观总结
- 主要指数
- 涨跌分布
- 市场风格
- 成交额总览
- 大盘资金流向
- 榜单速览
- 涨跌停统计与分布
- 板块速览
- `MarketOverviewLimitLadder` 的层级结构
- `LimitLadderPromotionLayer` 的昨日/今日晋级结构
- `LimitLadderSpecialLayer` 的五板以上层级规则
- `LimitLadderFirstLayer` 的首板层规则
- `LimitLadderExpandControl` 的展开/收起逻辑
- 昨日层级展示规则
- 今日层级展示规则
- 五板以上层级规则
- 股票点击进入个股详情的交互
- 页面整体主题
- 全局字体
- 页面整体布局顺序
- 与 Review v6 无关的组件、Mock 数据结构和业务规则

---

### 21.3 `CsqStockCompactCard` 修订版

| 项 | 说明 |
|---|---|
| 组件名 | `CsqStockCompactCard` |
| 中文名 | 紧凑型股票卡片 |
| 所属层级 | Core Component 候选 / Data Display Component。它是紧凑股票信息展示组件，本轮主要用于市场总览连板天梯。 |
| 组件定位 | 用于在高密度场景中展示一只股票的核心行情事实和短线表现信息。组件具备一定复用性，但本轮展示结构优先服务市场总览连板天梯。 |
| 是否市场总览 P0 必需 | 是，用于 `MarketOverviewLimitLadder` 内的股票卡片。 |
| 是否改变连板天梯逻辑 | 否。本轮只修改卡片内部字段与布局，不修改天梯层级、展开/收起、昨日/今日规则。 |
| 默认结构 | 右上角股票代码角标 + 主体 2 行 × 3 列。 |
| 点击行为 | 点击卡片进入个股详情页，携带 `stockCode` 和当前 `tradeDate`。 |
| 状态 | default / hover / active / selected / disabled / loading / empty / error。loading、empty、error 主要由父容器或层级容器处理，卡片自身只定义 default、hover、active、selected、disabled 的视觉。 |
| 涨跌色规则 | `changePct` 必须红涨绿跌；`latestPrice` 可按方向弱着色或使用主文字，由页面实现统一；股票名称、股票代码、所属板块、板上成交额不使用涨跌色。 |
| Design Token 依赖 | 依赖 `03-design-tokens.md v0.3.2` 中 `--cs-stock-card-*`、`--cs-color-market-*`、`--cs-font-family-number`、`--cs-color-brand-accent-*`。 |
| 禁止误用 | 不得把 `boardTradeAmount` 写成封单金额或全天成交额；不得把 `streakText` 拆成两个默认字段；不得把股票代码放入主体 2×3 网格。 |

#### 21.3.1 Props

本轮修订后的默认 Props：

```ts
interface CsqStockCompactCardProps {
  stockCode: string;
  stockName: string;
  latestPrice: number;
  changePct: number;
  sectorName: string;
  boardTradeAmount: number;
  streakText: string;
  onClick?: () => void;
}
```

说明：

1. 以上 Props 是组件默认展示契约，不是正式 API response。
2. 页面 API response 到组件 Props 的转换应由页面 ViewModel / Adapter 完成。
3. `direction`、`selected`、`disabled` 等状态字段可在前端实现中作为扩展 UI props，但不进入本轮用户指定的最小 Props 契约。
4. `openTimes`、`currentStreakLevel` 不再作为默认展示字段；如未来业务需要，可作为扩展信息进入 Tooltip 或高级变体，不影响本轮默认结构。

#### 21.3.2 展示结构

新的 `CsqStockCompactCard` 由两部分组成：

1. 右上角股票代码角标；
2. 主体 2 行 × 3 列信息区。

```text
┌────────────────────────────────────────────────────┐
│                                            600172.SH│
│ 股票名称              涨幅              所属板块    │
│ 最新价                板上成交额        N天M板标签  │
└────────────────────────────────────────────────────┘
```

结构规则：

| 区域 | 字段 | 说明 |
|---|---|---|
| 右上角角标 | `stockCode` | 股票代码，弱化但可读，不属于主体 2×3 信息区。 |
| 第一行左侧 | `stockName` | 股票名称，主识别信息，视觉权重最高。 |
| 第一行中间 | `changePct` | 涨幅，红涨绿跌，带正负号和百分号。 |
| 第一行右侧 | `sectorName` | 所属板块，中性信息，右对齐，超出省略。 |
| 第二行左侧 | `latestPrice` | 最新价，不再使用“收盘价格”口径。 |
| 第二行中间 | `boardTradeAmount` | 板上成交额，只在板上发生的成交金额。 |
| 第二行右侧 | `streakText` | N天M板/板型，一个字段、一个标签。 |

---

### 21.4 字段口径与显示规则

#### 21.4.1 `stockCode`

| 项 | 说明 |
|---|---|
| 业务含义 | 股票代码。 |
| 显示位置 | 卡片右上角角标。 |
| 是否主体字段 | 否，不属于主体 2×3 信息区。 |
| 视觉权重 | 弱化但可读。 |
| 示例 | `600172.SH`、`300124.SZ`。 |
| 禁止 | 禁止放回左中；禁止作为普通正文列；禁止使用涨跌色。 |

#### 21.4.2 `stockName`

| 项 | 说明 |
|---|---|
| 业务含义 | 股票名称。 |
| 显示位置 | 第一行左侧。 |
| 视觉权重 | 最高，是卡片主识别信息。 |
| 规则 | 单行展示，过长省略；不使用涨跌色。 |
| 示例 | `黄河旋风`、`汇川技术`。 |

#### 21.4.3 `latestPrice`

| 项 | 说明 |
|---|---|
| 业务含义 | 最新价。 |
| 显示位置 | 第二行左侧。 |
| 口径说明 | 盘中展示实时或最近行情价；收盘后最新价等于收盘价。 |
| 修订说明 | 不再使用“收盘价格”作为字段名或显示口径。 |
| 颜色 | 可按涨跌方向弱着色，也可使用主文字，仅让 `changePct` 承载方向色。 |
| 示例 | `10.76`。 |

#### 21.4.4 `changePct`

| 项 | 说明 |
|---|---|
| 业务含义 | 涨幅 / 涨跌幅。 |
| 显示位置 | 第一行中间。 |
| 颜色 | 必须红涨绿跌，正红、负绿、零灰白。 |
| 格式 | 正数带 `+`，保留百分号。 |
| 示例 | `+10.02%`、`-3.18%`、`0.00%`。 |

#### 21.4.5 `sectorName`

| 项 | 说明 |
|---|---|
| 业务含义 | 所属板块。 |
| 显示位置 | 第一行右侧。 |
| 颜色 | 中性文字，不使用涨跌色。 |
| 规则 | 单行展示，过长省略；右对齐。 |
| 示例 | `通用设备`、`机器人`、`固态电池`。 |

#### 21.4.6 `boardTradeAmount`

| 项 | 说明 |
|---|---|
| 业务含义 | 板上成交额。 |
| 显示位置 | 第二行中间。 |
| 口径 | 只在板上发生的成交金额。 |
| 明确不是 | 不是封单金额；不是全天成交额；不是总成交额；不是板块成交额；不是资金净流入。 |
| 颜色 | 中性或弱强调，不使用涨跌红/绿。 |
| 格式 | 建议由 ViewModel 格式化为 `3.20亿`、`8200万`。 |
| Tooltip | 可说明“板上成交额：只统计封板状态下发生的成交金额”。 |

#### 21.4.7 `streakText`

| 项 | 说明 |
|---|---|
| 业务含义 | N天M板 / 板型文本。 |
| 显示位置 | 第二行右侧。 |
| 字段规则 | 一个字段，一个标签。 |
| 禁止 | 不拆成两个独立字段；不默认同时展示两个独立标签。 |
| 示例 | `首板`、`2连板`、`3连板`、`7天5板`、`9天7板`、`6板`。 |
| 五板以上 | 五板以上层也通过 `streakText` 承载具体板数或近期表现；不再用 `currentStreakLevel` 覆盖右下字段。 |

---

### 21.5 旧默认字段移除 / 降级说明

本轮默认结构中不再使用以下字段：

| 旧字段 / 口径 | Review v6 处理 | 说明 |
|---|---|---|
| `openTimes` 作为右下默认字段 | 移除默认展示，降级为未来扩展字段 | 若后续需要展示开板次数，可进入 Tooltip 或扩展变体，但不作为本轮默认卡片结构。 |
| `currentStreakLevel` 作为五板以上右下覆盖字段 | 移除默认覆盖，统一由 `streakText` 承载 | 五板以上可传入 `streakText: '6板'` 或 `streakText: '9天7板'`。 |
| 收盘价格 | 改为 `latestPrice` | 市场总览可盘中展示，字段口径必须是最新价。 |
| 封单金额 | 不进入本轮默认结构 | 本轮字段是板上成交额，不是封单金额。 |
| 全天成交额 | 不进入本轮默认结构 | 本轮字段是板上成交额，不是全天成交额。 |

---

### 21.6 状态与交互

| 状态 | 规则 |
|---|---|
| default | 深色卡片背景、弱边框、2×3 信息区正常展示。 |
| hover | 整卡高亮，边框提亮，可有弱阴影；不改变字段颜色语义。 |
| active | 鼠标按下或键盘确认时轻微压暗或下移 1px。 |
| selected | 可选状态；如页面需要选中股票，使用品牌金弱背景 / 品牌金边框。 |
| disabled | 通常不出现；如股票不可点击，降低透明度并取消 pointer。 |
| loading | 由父容器或层级容器处理，展示股票卡片骨架。 |
| empty | 由父容器或层级容器处理，展示“暂无该层级股票”。 |
| error | 由父容器或层级容器处理，展示单层错误块。 |

交互要求：

1. 卡片 hover 时整卡高亮；
2. 卡片 click 进入个股详情页；
3. 组件通过 `onClick?: () => void` 暴露点击事件；
4. 组件不关心路由细节，路由由页面层处理；
5. 点击卡片不改变连板天梯展开 / 收起状态；
6. 点击卡片不改变层级标题行为；
7. 层级标题仍不支持点击。

---

### 21.7 与连板天梯其它组件的关系

本轮不修改以下组件逻辑，只说明它们内部使用新版 `CsqStockCompactCard`：

| 组件 / Pattern | 本轮处理 |
|---|---|
| `MarketOverviewLimitLadder` | 保持市场总览业务复合组件定位；内部股票卡片改用 Review v6 版 `CsqStockCompactCard`。 |
| `LimitLadderPromotionLayer` | 结构仍为 `昨日 N-1 板 → 今日 N 板`；`previousStocks` 和 `currentStocks` 均使用新版卡片展示。 |
| `LimitLadderSpecialLayer` | 仍用于“五板以上”独立层；不修改五板以上只展示今日六板及以上的规则；卡片右下由 `streakText` 承载，如 `6板`。 |
| `LimitLadderFirstLayer` | 仍只展示今日首板；股票卡片使用新版结构。 |
| `LimitLadderExpandControl` | 展开 / 收起逻辑保持不变；默认最多 2 行 × 6 只，超出展开全部。 |
| `LimitLadderPromotionLayer.previousStocks` | 仍展示昨日该层级所有股票，卡片信息使用今日数据。 |
| `LimitLadderPromotionLayer.currentStocks` | 仍只展示今日晋级成功股票，卡片信息使用今日数据。 |

---

### 21.8 Mock 数据结构建议

本轮不让 04 修改 API，以下结构仅用于 Showcase Mock 和组件设计，不作为正式 API 契约。

```ts
interface LimitLadderStockCard {
  stockCode: string;
  stockName: string;
  latestPrice: number;
  changePct: number;
  sectorName: string;
  boardTradeAmount: number;
  streakText: string;
}
```

Mock 示例：

```ts
const mockLimitLadderStock: LimitLadderStockCard = {
  stockCode: '600172.SH',
  stockName: '黄河旋风',
  latestPrice: 10.76,
  changePct: 10.02,
  sectorName: '通用设备',
  boardTradeAmount: 320000000,
  streakText: '7天5板',
};
```

ViewModel 展示格式建议：

```ts
interface LimitLadderStockCardViewModel extends LimitLadderStockCard {
  latestPriceText: string;        // 例如：10.76
  changePctText: string;          // 例如：+10.02%
  boardTradeAmountText: string;   // 例如：3.20亿 / 8200万
  direction: 'rise' | 'fall' | 'flat';
}
```

说明：

1. `boardTradeAmountText` 可由前端 mock adapter 生成，不要求 API 本轮提供；
2. `direction` 可由 `changePct` 派生，仅用于 UI 着色；
3. `streakText` 是单一展示字段，不拆分；
4. 04 本轮不参与，不正式修改 API 文档和数据字典。

---

### 21.9 对 02 `market-overview-v1.5.html` 的组件使用建议

1. 只修改连板天梯中的标准股票卡片。
2. 股票代码必须放在卡片右上角角标。
3. 股票代码不得进入主体 2×3 信息区。
4. 主体信息必须为 2 行 × 3 列：
   - 第一行：股票名称、涨幅、所属板块；
   - 第二行：最新价、板上成交额、N天M板/板型。
5. 股票名称为最高识别权重。
6. 涨幅必须红涨绿跌，并保留正负号。
7. 最新价显示为最新价，不得写成收盘价格。
8. 板上成交额按“只在板上发生的成交金额”理解和展示，不得误写为封单金额或全天成交额。
9. `N天M板/板型` 必须是一个字段、一个标签。
10. 五板以上层不再通过 `currentStreakLevel` 单独覆盖右下角，而是通过 `streakText` 显示 `6板`、`7板` 或 `9天7板`。
11. 不照搬 Review v6 示意图浅色背景、蓝色边框、按钮样式或字体。
12. 必须使用当前市场总览深色金融终端风格。
13. 保持卡片 hover / clickable 状态。
14. 不修改连板天梯层级结构。
15. 不修改连板天梯展开/收起逻辑。
16. 不修改连板天梯五板以上层级规则。
17. 不修改市场总览其它模块。
18. 若卡片空间不足，优先缩短 `boardTradeAmountText`，例如 `3.2亿`；不得删除 `streakText`。

---

### 21.10 对 01 Design Token 的依赖

本轮依赖 `03-design-tokens.md v0.3.2` 中以下 Token 和规则：

| Token / 规则 | 用途 |
|---|---|
| `--cs-stock-card-width` / `--cs-stock-card-min-width` / `--cs-stock-card-height` | 新版卡片尺寸。 |
| `--cs-stock-card-code-badge-*` | 右上角股票代码角标样式。 |
| `--cs-stock-card-body-*` | 主体 2 行 × 3 列布局。 |
| `--cs-stock-card-name-*` | 股票名称字号和字重。 |
| `--cs-stock-card-change-*` | 涨幅字号和字重。 |
| `--cs-stock-card-price-*` | 最新价字号和字重。 |
| `--cs-stock-card-board-amount-*` | 板上成交额中性 / 弱强调样式。 |
| `--cs-stock-card-tag-*` | `N天M板/板型` 标签样式。 |
| `--cs-color-market-up/down/flat` | 红涨绿跌。 |
| `--cs-font-family-number` | 价格、涨幅、金额等数字字段。 |
| `--cs-stock-card-bg-hover` / `--cs-stock-card-border-hover` / `--cs-stock-card-shadow-hover` | 整卡 hover 高亮。 |

03 实现时不得绕过 Token 直接硬编码卡片颜色、边框、字号和 hover 样式。

---

### 21.11 是否需要后续拉 04 参与的条件

本轮不正式修改 API 契约，不要求 04 参与。

后续只有在以下条件出现时，再单独拉 04 API 与数据字典参与：

| 条件 | 是否需要 04 | 原因 |
|---|---:|---|
| 需要正式在接口中增加 `boardTradeAmount` | 是 | `boardTradeAmount` 涉及明确业务口径，需要数据字典定义来源和计算方式。 |
| 需要正式在接口中增加 `streakText` | 是 | `N天M板/板型` 文案可能需要统一生成口径。 |
| 需要区分 `streakText` 的“首板 / 连板 / N天M板”类型 | 是 | 可能需要新增字段或枚举，而不是单一文本。 |
| 需要展示 `boardTradeAmountDisplayText` | 是 | 若希望后端统一格式化金额，需要 API 字段确认。 |
| 只在 Showcase Mock 中展示新版卡片 | 否 | 本轮可由前端 mock adapter 生成。 |
| 仅调整卡片 CSS 和布局 | 否 | 不涉及 API 契约。 |

本轮结论：

```text
04 本轮不参与；本节 Mock 字段只用于 Showcase 和组件设计，不作为正式 API 契约。
```

---

### 21.12 本轮 Review v6 修改摘要

1. 仅修订 `CsqStockCompactCard`。
2. 股票代码改为右上角角标，弱化但可读。
3. 主体信息改为 `2 行 × 3 列`：
   - 第一行：股票名称、涨幅、所属板块；
   - 第二行：最新价、板上成交额、N天M板/板型。
4. “收盘价格”口径修正为“最新价”。
5. 新增 `boardTradeAmount` 字段作为板上成交额，仅指板上发生的成交金额。
6. 明确 `boardTradeAmount` 不是封单金额、不是全天成交额、不是总成交额。
7. `streakText` 明确为一个字段、一个标签，不拆成两个独立字段。
8. `openTimes` 不再作为卡片默认右下字段。
9. `currentStreakLevel` 不再作为五板以上默认右下覆盖字段，由 `streakText` 承载。
10. 不修改连板天梯其它组件、层级结构、展开/收起逻辑和股票点击交互。

### 21.13 本轮修订组件清单

| 类型 | 组件 | 处理方式 |
|---|---|---|
| 修订 | `CsqStockCompactCard` | 修订默认 Props、字段口径、显示结构和旧字段降级说明。 |
| 影响说明 | `MarketOverviewLimitLadder` | 仅说明内部使用新版 `CsqStockCompactCard`，不修改层级逻辑。 |
| 影响说明 | `LimitLadderPromotionLayer` | 仅说明 `previousStocks/currentStocks` 卡片使用新版结构，不修改昨日/今日规则。 |
| 影响说明 | `LimitLadderSpecialLayer` | 仅说明五板以上卡片通过 `streakText` 承载具体板数，不修改五板以上层级规则。 |
| 影响说明 | `LimitLadderFirstLayer` | 仅说明首板层卡片使用新版结构，不修改首板层规则。 |
| 影响说明 | `LimitLadderExpandControl` | 无逻辑修改。 |

### 21.14 本轮未修改组件清单

以下组件和模块保持 v0.9 merged-full 规范，不主动修改：

- `TopMarketBar`
- `Breadcrumb`
- `PageHeader`
- `ShortcutBar`
- 今日市场客观总结
- 主要指数
- 涨跌分布
- 市场风格
- 成交额总览
- 大盘资金流向
- 榜单速览
- 涨跌停统计与分布
- 板块速览
- `MarketOverviewLimitLadder` 的层级结构
- `LimitLadderPromotionLayer` 的昨日 / 今日晋级逻辑
- `LimitLadderSpecialLayer` 的五板以上层级规则
- `LimitLadderFirstLayer` 的首板层规则
- `LimitLadderExpandControl` 的展开 / 收起逻辑
- `CsqPanel`
- `CsqSectionHeader`
- `CsqHelpTooltip`
- `CsqBadge`
- `CsqStatusDot`
- `CsqSkeleton`
- `CsqEmptyState`
- `CsqErrorState`
- `CsqMetricCard`
- `CsqMetricSummaryGroup`
- `CsqChangeValue`
- `CsqChangeBadge`
- `CsqInfoRow`
- `CsqLinkedMetricList`
- `CsqProgressList`
- `CsqStatusBadge`
- `CsqDataTable`
- `CsqRankTable`
- `CsqColumnHeader`
- `CsqTableRow`
- `CsqTableCellNumber`
- `CsqMiniTrendChart`
- `CsqHistoryTrendChart`
- `CsqDistributionChart`
- `CsqBarChart`
- `CsqPieChartWithCallout`
- `CsqHeatMapGrid`
- `CsqChartSplitPanel`
- `CsqChartTooltip`
- `CsqCrosshairOverlay`

```text
本轮因 Review v6 修改而被动影响的区域：无
原因：本轮只替换标准股票卡片内部字段结构，不改变父组件逻辑。
是否需要产品总控确认：否
```

### 21.15 待产品总控确认问题

1. `CsqStockCompactCard` 的默认宽度是否采用 Token v0.3.2 建议的 `168px`，并在窄宽度下允许降级到 `152px`？
2. `latestPrice` 是否需要随涨跌方向弱着色，还是仅让 `changePct` 承载红涨绿跌？当前建议：`changePct` 必须方向色，`latestPrice` 可弱方向色。
3. `boardTradeAmount` 在卡片内是否只展示金额，不展示“板上成交额”标签？当前建议：卡片内只展示金额，完整口径放入 Tooltip / 组件说明。
4. `boardTradeAmount` 为空时展示 `--`，还是隐藏中列内容？建议展示 `--` 并保留布局。
5. `streakText` 是否允许同时出现“连板型”和“N天M板型”的不同文案？当前按一个字段一个标签处理，由上游 mock 决定文本。
6. 是否需要保留 `openTimes` 在卡片 Tooltip 中展示？当前默认结构不展示，但可作为未来扩展。
7. 五板以上层是否统一传 `streakText='6板'`，还是优先传 `streakText='9天7板'`？当前组件只接受文本，不判断业务优先级。

### 21.16 Review v6 验收清单

| 验收项 | 要求 |
|---|---|
| 完整文档 | 本文件仍是完整 `04-component-guidelines.md`，不是 delta 文档。 |
| 修改边界 | 只修订 `CsqStockCompactCard`。 |
| 右上角代码 | `stockCode` 位于卡片右上角，弱化但可读，不进入主体 2×3。 |
| 主体结构 | 第一行 `stockName / changePct / sectorName`；第二行 `latestPrice / boardTradeAmount / streakText`。 |
| 最新价 | 使用 `latestPrice`，不再使用“收盘价格”口径。 |
| 板上成交额 | `boardTradeAmount` 口径明确：只在板上发生的成交金额，不是封单金额或全天成交额。 |
| N天M板标签 | `streakText` 是一个字段、一个标签，不拆分。 |
| 旧字段降级 | `openTimes` 和 `currentStreakLevel` 不作为默认结构字段。 |
| 连板天梯逻辑 | 不修改层级结构、昨日/今日规则、五板以上规则、展开/收起逻辑。 |
| 交互 | 卡片点击进入个股详情；父组件逻辑不变。 |
| API | 不正式修改 API 契约，只提供 Mock 字段建议。 |
| 未授权改动 | 未修改 Review v6 未点名组件或页面整体布局。 |

### 21.17 建议放置到 Google Drive 的路径

```text
财势乾坤/设计/04-component-guidelines.md
```

### 21.18 建议仓库保存路径

```text
/docs/wealth/04-component-guidelines.md
```

### 21.19 本轮输出文件下载链接

对话交付文件：

```text
sandbox:/mnt/data/review-v6-output-final/04-component-guidelines.md
```

---

## 22. HTML Review v7 → market-overview-v1.6 标准股票卡片局部修订合并规范

> 本节为 Review v7 对 `市场总览 / 连板天梯 / 标准股票卡片` 的组件级修订。它不替代前文已确认的通用组件库注册表、市场总览页面组件规范或 Review v1～v6 已确认内容，而是在完整保留 v1.0 merged-full 基线的前提下，只修订 `CsqStockCompactCard` 的布局结构与组件说明。  
> 本节是当前最新覆盖规则：**Review v7 正式替代 Review v6 中“股票代码右上角 + 主体 2 行 × 3 列”的标准股票卡片结构。**  
> 本节不修改 TopMarketBar、Breadcrumb、PageHeader、ShortcutBar、今日市场客观总结、主要指数、涨跌分布、市场风格、成交额总览、大盘资金流向、榜单速览、涨跌停统计与分布、板块速览、连板天梯层级结构、连板天梯展开/收起逻辑及其它 Review v7 未点名组件。

### 22.1 本轮读取文档与采用基线

| 序号 | 公共区文件 | 读取到的版本 / 状态 | 本轮用途 |
|---:|---|---|---|
| 1 | `财势乾坤/项目总说明/财势乾坤行情软件项目总说明_v_0_2.md` | `财势乾坤项目总说明 v0.2` / Review 草案 v0.2 | 继续约束产品定位、P0 范围、A 股优先、红涨绿跌、深色默认、专业沉稳风格。 |
| 2 | `财势乾坤/产品文档/市场总览产品需求文档 v0.2.md` | `市场总览产品需求文档 v0.2` / Review 草案 | 继续约束市场总览页面名称、归属、非目标、无固定 SideNav、客观事实页边界。 |
| 3 | `财势乾坤/设计/02-market-overview-page-design.md` | `市场总览页面设计文档 v0.1` | 作为市场总览页面设计基线；本轮仅修订连板天梯标准股票卡片，不主动调整页面其它模块。 |
| 4 | `财势乾坤/设计/03-design-tokens.md` | `Design Token 与视觉规范 v0.3.3` | 采用 Review v7 中股票代码左上角胶囊、三分区卡片、标签区、hover/clickable/selected 状态等 Token。 |
| 5 | `财势乾坤/设计/04-component-guidelines.md` | 公共区当前读取到 `P0 组件库与交互组件方案 v0.9 merged-full / Review v5 连板天梯局部修订版`；本文件合并时以已交付的 Review v6 完整合并版为防回退基线 | 公共区文件用于核验当前组件基线；为避免丢失已确认的 Review v6 标准股票卡片字段口径，本版在 v6 完整合并版基础上追加 Review v7 修订。 |
| 6 | `财势乾坤/review/market-overview-html-review-v7-总控解读与变更单.md` | `市场总览 HTML Review v7｜总控解读与变更单` | 本轮直接变更单，规定只处理 `CsqStockCompactCard`。 |

本轮未能读取但应读取的文档：无。  
本轮是否继续：是。

---

### 22.2 本轮修订边界

#### 22.2.1 允许修改区域

```text
市场总览 / 连板天梯 / 标准股票卡片 / CsqStockCompactCard
```

本轮只允许修订：

1. `CsqStockCompactCard` 的内部结构；
2. `CsqStockCompactCard` 的字段位置；
3. `CsqStockCompactCard` 的布局分区；
4. `CsqStockCompactCard` 的废弃旧结构说明；
5. 组件内部使用新版 `CsqStockCompactCard` 的父组件兼容说明；
6. Showcase Mock 字段建议。

#### 22.2.2 禁止主动修改区域

以下组件和模块保持 v1.0 merged-full 规范，不做主动改动：

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
- 今日市场客观总结相关组件
- 主要指数相关组件
- `MarketBreadthPanel` / 涨跌分布
- `MarketStylePanel` / 市场风格
- `TurnoverSummaryCard` / 成交额总览
- `MoneyFlowSummaryPanel` / 大盘资金流向
- `RankingTable` / 榜单速览
- `LimitUpDistributionGrid` / 涨跌停统计与分布
- `LimitUpSectorLeaderPanel` / 领涨股涨停表现
- `OrderSizeNetPieChart` / 资金饼图
- `SectorOverviewMatrix` / 板块速览矩阵
- `SectorHeatMap` / 板块热力图
- `MarketOverviewLimitLadder` 的层级结构
- `LimitLadderPromotionLayer`
- `LimitLadderSpecialLayer`
- `LimitLadderFirstLayer`
- `LimitLadderExpandControl`
- 昨日层级展示规则
- 今日层级展示规则
- 五板以上层级规则
- 展开 / 收起逻辑
- 页面整体主题、全局字体、页面整体布局顺序
- 与 Review v7 无关的任何组件或 Mock 数据结构

---

### 22.3 CsqStockCompactCard：Review v7 最新结构

| 项 | 说明 |
|---|---|
| 组件名 | `CsqStockCompactCard` |
| 中文名 | 标准紧凑股票卡片 |
| 所属层级 | Data Display Components / 行情终端领域通用组件 |
| 组件定位 | 用于紧凑型股票信息展示。当前主要用于市场总览连板天梯，也可作为后续短线异动股、板块领涨股、股票候选列表的复用基础。 |
| 是否 Core Component | 是，但它是“股票展示领域组件”，不是市场总览专属组件；Props 不绑定 API response。 |
| 是否市场总览 P0 必需 | 是，Review v5 / v6 / v7 连续点名。 |
| 本轮结构结论 | 新版结构正式替代 Review v6 的右上角代码 + 2 行 × 3 列机械网格方案。 |
| 输入字段 / Props | `stockCode`、`stockName`、`latestPrice`、`changePct`、`sectorName`、`boardTradeAmount`、`streakText`、`onClick`。字段集合保持稳定。 |
| 视觉结构 | `codePill` + `leftIdentity` + `centerMetrics` + `rightTags`。股票代码位于左上角胶囊；主体为横向三分区，而不是机械 2×3 网格。 |
| 交互行为 | hover 整卡高亮；click 进入个股详情页；支持键盘 focus / Enter 触发点击；父级层级标题、晋级箭头和展开控件逻辑不变。 |
| 状态 | default：正常卡片；hover：整卡背景、边框、弱阴影增强；active：轻微压暗或下移 1px；selected：品牌金弱背景/边框，可选；disabled：透明度降低且不触发点击；loading/empty/error 由父容器处理。 |
| 涨跌色规则 | `changePct` 必须红涨绿跌；`latestPrice` 可跟随方向弱着色；`stockName`、`stockCode`、`sectorName` 使用中性色；`boardTradeAmount` 使用中性或弱强调色；`streakText` 使用标签样式，不拆字段。 |
| Design Token 映射 | `--cs-stock-card-*`、`--cs-color-market-*`、`--cs-font-family-number`、`--cs-color-brand-accent-*`、`--cs-color-warning`。以 `03-design-tokens.md v0.3.3` 为准。 |
| 禁止误用 | 不展示买卖建议、机会评分、市场温度、风险指数；不使用右上角股票代码方案；不使用 2×3 机械网格；不将 `streakText` 拆成两个标签；不把板上成交额误写为封单金额或全天成交额。 |

```ts
interface CsqStockCompactCardProps {
  stockCode: string;
  stockName: string;
  latestPrice: number;
  changePct: number;
  sectorName: string;
  boardTradeAmount: number;
  streakText: string;
  onClick?: () => void;
}
```

#### 22.3.1 结构树

新版 `CsqStockCompactCard` 必须按以下结构组织：

```text
CsqStockCompactCard
├── codePill
├── leftIdentity
│   ├── stockName
│   └── latestPrice
├── centerMetrics
│   ├── changePct
│   └── boardTradeAmount
└── rightTags
    ├── sectorName
    └── streakTextPill
```

说明：

1. `codePill` 是独立的左上角胶囊，不属于主体普通列。
2. `leftIdentity` 是股票识别区，负责股票名称和最新价。
3. `centerMetrics` 是行情事实区，负责涨幅和板上成交额。
4. `rightTags` 是标签区，负责所属板块和 N天M板 / 板型。
5. 三分区是视觉和信息架构分区，不改变字段集合，不引入新 API 字段。

#### 22.3.2 结构示意

```text
┌──────────────────────────────────────────────┐
│ [603017.SH]                                  │
│ 中衡设计          +10.02%          低空经济   │
│ 12.74             1.27亿            3连板     │
└──────────────────────────────────────────────┘
```

推荐布局理解：

```text
┌──────────────────────────────────────────────┐
│ codePill                                     │
│ leftIdentity      centerMetrics    rightTags │
│ stockName         changePct        sectorName│
│ latestPrice       boardTradeAmount streakText│
└──────────────────────────────────────────────┘
```

---

### 22.4 字段说明与显示位置

#### 22.4.1 stockCode

| 项 | 说明 |
|---|---|
| 字段 | `stockCode` |
| 显示位置 | 左上角 `codePill`。 |
| 显示规则 | 胶囊标签，弱化但清晰可读；建议使用等宽数字字体。 |
| 禁止 | 不显示在右上角；不作为主体普通列；不与 `stockName` 混排。 |

#### 22.4.2 stockName

| 项 | 说明 |
|---|---|
| 字段 | `stockName` |
| 显示位置 | `leftIdentity` 第一行。 |
| 显示规则 | 主识别字段，视觉权重最高，单行省略。 |
| 禁止 | 不使用涨跌色，不做标签化。 |

#### 22.4.3 latestPrice

| 项 | 说明 |
|---|---|
| 字段 | `latestPrice` |
| 显示位置 | `leftIdentity` 第二行。 |
| 口径 | 最新价。盘中展示实时或最近行情价；收盘后最新价自然等于收盘价。 |
| 显示规则 | 数字字体；可跟随涨跌方向弱着色，或使用主文字色并由 `changePct` 承载方向色。 |
| 禁止 | 不使用“收盘价格”作为字段名或展示口径。 |

#### 22.4.4 changePct

| 项 | 说明 |
|---|---|
| 字段 | `changePct` |
| 显示位置 | `centerMetrics` 第一行。 |
| 显示规则 | 红涨绿跌，正数带 `+`，负数带 `-`，保留 2 位小数。 |
| 视觉层级 | 强强调，仅次于股票名称和最新价。 |

#### 22.4.5 boardTradeAmount

| 项 | 说明 |
|---|---|
| 字段 | `boardTradeAmount` |
| 显示位置 | `centerMetrics` 第二行。 |
| 口径 | 只在板上发生的成交金额。 |
| 显示规则 | 建议格式化为 `3.20亿`、`8200万`；使用中性色或弱强调色；数字字体。 |
| 明确不是 | 不是封单金额；不是全天成交额；不是总成交额；不是板块成交额；不是主力净流入。 |
| Tooltip 建议 | `板上成交额：只统计封板状态下发生的成交金额`。 |

#### 22.4.6 sectorName

| 项 | 说明 |
|---|---|
| 字段 | `sectorName` |
| 显示位置 | `rightTags` 第一行。 |
| 显示规则 | 所属板块，中性色，单行省略。 |
| 禁止 | 不使用涨跌红绿，不与 `streakText` 合并为一个字段。 |

#### 22.4.7 streakText

| 项 | 说明 |
|---|---|
| 字段 | `streakText` |
| 显示位置 | `rightTags` 第二行，作为 `streakTextPill`。 |
| 口径 | N天M板 / 板型，一个字段，一个标签。 |
| 示例 | `首板`、`2连板`、`3连板`、`7天5板`、`9天7板`。 |
| 显示规则 | 胶囊标签，可使用红色描边、弱红背景或品牌弱强调；不得使用大面积红背景。 |
| 禁止 | 不拆成两个字段；不同时展示两个独立标签；不再通过 `currentStreakLevel` 特殊覆盖右下字段。 |

#### 22.4.8 onClick

| 项 | 说明 |
|---|---|
| 字段 | `onClick` |
| 交互 | 点击股票卡片进入个股详情页。 |
| 路由参数 | 页面层负责携带 `stockCode`、`tradeDate`。组件本身不绑定路由实现。 |
| 可访问性 | clickable 状态建议提供 `role="button"`、`tabIndex=0`、Enter / Space 触发。 |

---

### 22.5 废弃旧规则

Review v7 正式废弃以下 Review v6 规则：

| 废弃项 | 原规则 | Review v7 新规则 |
|---|---|---|
| 股票代码位置 | 股票代码在右上角角标 | 股票代码在左上角胶囊 `codePill` |
| 主体布局 | 第一行：`stockName / changePct / sectorName`；第二行：`latestPrice / boardTradeAmount / streakText` | 横向三分区：`leftIdentity / centerMetrics / rightTags` |
| 视觉组织方式 | 2 行 × 3 列机械网格 | 行情终端式横向信息卡片 |
| 五板以上右下覆盖 | 右下字段可由 `currentStreakLevel` 覆盖为 `6板 / 7板` | 统一通过 `streakText` 承载 N天M板 / 板型信息 |
| openTimes 默认展示 | Review v5 曾以 openTimes 作为右下默认字段 | Review v7 默认结构不展示 openTimes；如未来需要，只能作为扩展或 Tooltip 字段，不进入默认结构 |

说明：

1. 字段集合基本不变；
2. 变化的是布局结构和视觉层级；
3. `streakText` 统一承载 N天M板 / 板型信息；
4. 废弃旧结构不代表删除历史 Review 记录，但当前实现必须以本节为准。

---

### 22.6 视觉结构与密度建议

#### 22.6.1 三分区宽度建议

| 分区 | 建议宽度 | 说明 |
|---|---:|---|
| `leftIdentity` | 38%～44% | 股票名称和最新价需要优先可读。 |
| `centerMetrics` | 24%～30% | 涨幅和板上成交额偏数字展示，居中或右对齐。 |
| `rightTags` | 28%～34% | 板块和 streak 标签需要完整可读。 |

#### 22.6.2 对齐建议

| 元素 | 对齐 |
|---|---|
| codePill | 左上角，独立胶囊。 |
| stockName | 左对齐。 |
| latestPrice | 左对齐。 |
| changePct | 居中或右对齐，保持与 boardTradeAmount 垂直对齐。 |
| boardTradeAmount | 居中或右对齐。 |
| sectorName | 右对齐，单行省略。 |
| streakTextPill | 右对齐，胶囊标签。 |

#### 22.6.3 推荐视觉层级

1. `stockName`：最高识别权重。
2. `latestPrice` / `changePct`：主要行情事实。
3. `streakTextPill`：连板标签强调。
4. `boardTradeAmount`：辅助事实。
5. `sectorName`：上下文信息。
6. `codePill`：弱化但清晰。

#### 22.6.4 红涨绿跌规则

| 字段 | 颜色规则 |
|---|---|
| `changePct` | 必须红涨绿跌。正红、负绿、零灰白。 |
| `latestPrice` | 可跟随涨跌方向弱着色；若视觉噪音过高，可用主文字色。 |
| `stockName` | 中性主文字，不用涨跌色。 |
| `stockCode` | 中性弱文字，不用涨跌色。 |
| `sectorName` | 中性文字，不用涨跌色。 |
| `boardTradeAmount` | 中性或弱强调，不用涨跌色。 |
| `streakText` | 标签样式，可用红色描边 / 弱红背景 / 品牌弱强调；不拆字段。 |

---

### 22.7 状态与交互

| 状态 | 规则 |
|---|---|
| default | 深色卡片底、弱边框、字段按三分区展示。 |
| hover | 整卡背景轻微提亮，边框增强，cursor 为 pointer。 |
| active | 卡片轻微压暗或下移 1px。 |
| selected | 可选：使用品牌金弱背景或细描边，不能与涨停红混淆。 |
| disabled | 降低透明度，不触发点击。 |
| loading | 由父容器处理；若卡片局部 loading，保持 codePill、三分区骨架。 |
| empty | 由父容器处理，不建议单卡空态。 |
| error | 由父容器处理，不建议单卡错误态。 |

交互规则：

1. 整卡 hover 高亮。
2. 整卡 click 进入个股详情页。
3. 不在 `codePill`、`streakTextPill` 上拆分独立点击行为。
4. 不改变 `MarketOverviewLimitLadder` 的层级标题点击规则。
5. 不改变 `LimitLadderExpandControl` 的展开/收起规则。
6. 不改变晋级箭头的非点击状态。

---

### 22.8 与连板天梯其它组件的关系

以下组件只需说明其内部股票卡片换用新版 `CsqStockCompactCard`，不修改自身逻辑：

| 组件 | 本轮处理 |
|---|---|
| `MarketOverviewLimitLadder` | 内部股票展示单元换用 Review v7 版 `CsqStockCompactCard`；动态层级、昨日/今日规则、五板以上规则、展开/收起逻辑不变。 |
| `LimitLadderPromotionLayer` | 左侧 `previousStocks` 和右侧 `currentStocks` 均使用新版卡片；标题、箭头、层级规则不变。 |
| `LimitLadderSpecialLayer` | 继续只展示今日六板及以上；不再使用 `currentStreakLevel` 覆盖右下字段，而由 `streakText` 承载具体板型或板数。 |
| `LimitLadderFirstLayer` | 继续只展示今日首板；股票卡片使用新版三分区结构。 |
| `LimitLadderExpandControl` | 展开/收起规则不变；默认折叠仍最多展示 2 行 × 6 只。 |

必须保持：

1. 昨日层级展示昨日该层级所有股票，卡片信息用今日数据；
2. 今日层级只展示晋级成功股票；
3. 首板层只展示今日首板；
4. 五板以上层只展示今日六板及以上；
5. 今日五板仍在 `昨日四板 → 今日五板`；
6. 展开 / 收起只影响当前层；
7. 股票点击进入个股详情。

---

### 22.9 Mock 数据结构建议

> 本节结构仅用于 Showcase Mock 和组件设计，不作为正式 API 契约。  
> 本轮不要求 04 API 与数据字典参与，也不正式修改 API 文档。

```ts
interface LimitLadderStockCard {
  stockCode: string;
  stockName: string;
  latestPrice: number;
  changePct: number;
  sectorName: string;
  boardTradeAmount: number;
  streakText: string;
}
```

Mock 示例：

```ts
const stockCardMock: LimitLadderStockCard = {
  stockCode: '603017.SH',
  stockName: '中衡设计',
  latestPrice: 12.74,
  changePct: 10.02,
  sectorName: '低空经济',
  boardTradeAmount: 127000000,
  streakText: '3连板',
};
```

Mock 规则：

1. `stockCode` 显示在左上角胶囊。
2. `stockName` 与 `latestPrice` 进入 `leftIdentity`。
3. `changePct` 与 `boardTradeAmount` 进入 `centerMetrics`。
4. `sectorName` 与 `streakText` 进入 `rightTags`。
5. `boardTradeAmount` 格式化为 `1.27亿`、`8200万` 等展示文案。
6. `streakText` 只传一个文本，不拆分为多个标签。
7. 不再在 Mock 中为默认卡片传 `openTimes` 或 `currentStreakLevel`。
8. 该结构不作为正式 API 契约，不引用 Tushare 原字段。

---

### 22.10 对 02 `market-overview-v1.6.html` 的组件使用建议

1. 只修改连板天梯中的标准股票卡片。
2. 股票代码必须改为左上角胶囊标签。
3. 不再使用右上角代码方案。
4. 不再使用 `2 行 × 3 列` 机械网格方案。
5. 卡片结构必须改为：`codePill + leftIdentity + centerMetrics + rightTags`。
6. 左侧识别区展示：`stockName`、`latestPrice`。
7. 中间行情事实区展示：`changePct`、`boardTradeAmount`。
8. 右侧标签区展示：`sectorName`、`streakTextPill`。
9. `boardTradeAmount` 按“只在板上发生的成交金额”展示，不得写成封单金额或全天成交额。
10. `streakText` 是一个字段、一个标签，不拆分为多个标签。
11. 使用现有市场总览深色金融终端风格，不机械照搬用户截图的像素、色值、边框或字体。
12. hover / clickable 状态必须清晰。
13. 不修改连板天梯层级结构。
14. 不修改连板天梯展开 / 收起逻辑。
15. 不修改连板天梯五板以上层级规则。
16. 不修改市场总览其它模块。
17. 红涨绿跌必须正确。
18. 不输出买卖建议或主观结论。

---

### 22.11 对 01 Design Token 的依赖

本节依赖 `03-design-tokens.md v0.3.3` 中以下 Token 或规则：

| 组件 / 区域 | Token / 规则 |
|---|---|
| `CsqStockCompactCard` | `--cs-stock-card-*`、`--cs-color-market-*`、`--cs-font-family-number` |
| `codePill` | 股票代码左上角胶囊背景、边框、文字色、字号、内边距、圆角 |
| `leftIdentity` | 股票名称、最新价的字体层级、行距、左侧宽度比例 |
| `centerMetrics` | 涨幅、板上成交额的字体层级、对齐方式、数字字体 |
| `rightTags` | 所属板块、`streakTextPill` 的对齐、标签样式、描边、弱背景 |
| hover / selected | 卡片 hover 背景、边框、弱阴影；selected 品牌弱强调 |
| 红涨绿跌 | `changePct` 必须使用 `--cs-color-market-up/down/flat` |

必须遵守：

1. 股票代码胶囊在左上角；
2. 三分区结构不使用 Review v6 的右上角代码与机械 2×3 网格；
3. `streakTextPill` 是一个标签；
4. `boardTradeAmount` 使用中性或弱强调，不使用涨跌红绿；
5. Review v7 未点名区域 Token 不修改。

---

### 22.12 是否需要后续拉 04 参与的条件

本轮不要求 04 API 与数据字典参与，因为当前任务只要求组件结构和 Showcase Mock 字段建议。

后续在以下任一条件出现时，需要单独拉 04 参与：

1. 需要把 `boardTradeAmount` 从 Mock 字段转为正式 API 字段；
2. 需要明确“板上成交额”的真实计算来源、交易状态筛选、成交明细聚合口径；
3. 需要在正式 API 中返回 `boardTradeAmountDisplayText`，避免前端自行换算单位；
4. 需要把 `streakText` 的 N天M板 / 板型生成逻辑放到后端统一计算；
5. 现有 `streakLadder` 数据无法提供 `latestPrice`、`changePct`、`sectorName`、`boardTradeAmount`、`streakText`；
6. 需要明确 ST 股票是否纳入连板天梯与 N天M板统计；
7. 需要将连板天梯 Mock 结构转为正式 API 契约。

---

### 22.13 本轮 Review v7 修改摘要

1. 只修订 `CsqStockCompactCard`。
2. 用户新截图正式替代 Review v6 的股票卡片结构。
3. 股票代码从右上角改为左上角胶囊 `codePill`。
4. 废弃 Review v6 的 `2 行 × 3 列` 机械网格方案。
5. 新结构改为：`codePill + leftIdentity + centerMetrics + rightTags`。
6. `leftIdentity` 包含 `stockName`、`latestPrice`。
7. `centerMetrics` 包含 `changePct`、`boardTradeAmount`。
8. `rightTags` 包含 `sectorName`、`streakTextPill`。
9. Props 字段集合保持稳定，不新增 API 字段。
10. `boardTradeAmount` 口径保持：只在板上发生的成交金额，不是封单金额，不是全天成交额。
11. `streakText` 继续是一个字段、一个标签。
12. 不修改连板天梯层级结构、展开/收起逻辑、五板以上规则或其它市场总览模块。

---

### 22.14 本轮修订组件清单

| 类型 | 组件 | 处理方式 |
|---|---|---|
| 修订 | `CsqStockCompactCard` | 由 Review v6 的右上角代码 + 2×3 机械网格，修订为 Review v7 的左上角代码胶囊 + 横向三分区结构。 |

---

### 22.15 本轮未修改组件清单

以下组件保持 v1.0 merged-full 规范，不做主动改动：

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
- 今日市场客观总结相关组件
- `IndexGrid`
- `IndexCard`
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
- `MoneyFlowNetStructurePanel`
- `OrderSizeNetPieChart`
- `RankingTable`
- `StockTable`
- `SortableHeader`
- `TabPanel`
- `LimitUpSummaryCard`
- `LimitUpDistributionGrid`
- `LimitUpSectorLeaderPanel`
- `LimitUpLeaderPerformanceTable`
- `LimitUpDownHistoryBarChart`
- `SectorOverviewMatrix`
- `SectorHeatMap`
- `MarketOverviewLimitLadder` 的层级结构与渲染规则
- `LimitLadderPromotionLayer`
- `LimitLadderSpecialLayer`
- `LimitLadderFirstLayer`
- `LimitLadderExpandControl`
- 昨日层级展示规则
- 今日层级展示规则
- 五板以上层级规则
- 展开 / 收起逻辑
- `CsqPieChartWithCallout`
- `CsqLinkedMetricList`
- `CsqHeatMapGrid`
- `CsqRankTable`
- `CsqChartSplitPanel`
- `HelpTooltip`
- `RangeSwitch`
- `LoadingSkeleton`
- `EmptyState`
- `ErrorState`
- `DataDelayState`
- `PermissionState`

```text
本轮因 Review v7 修改而被动影响的区域：
- MarketOverviewLimitLadder / LimitLadderPromotionLayer / LimitLadderSpecialLayer / LimitLadderFirstLayer 内部股票卡片渲染
原因：这些父组件内部使用 CsqStockCompactCard，因此视觉上会切换到新版卡片结构，但父组件层级逻辑、展开/收起逻辑和数据规则不变。
是否需要产品总控确认：否，属于 Review v7 明确点名的标准股票卡片替换范围。
```

---

### 22.16 Mock 数据结构建议

```ts
interface LimitLadderStockCard {
  stockCode: string;
  stockName: string;
  latestPrice: number;
  changePct: number;
  sectorName: string;
  boardTradeAmount: number;
  streakText: string;
}
```

使用说明：

1. 该结构只用于 Showcase Mock 和组件设计。
2. 不作为正式 API 契约。
3. 04 本轮不参与。
4. 如果真实 API 暂无 `boardTradeAmount` 或 `streakText`，02 Showcase 可以先使用 Mock 字段。
5. 后续进入真实开发时，若数据源无法支撑，需要单独发起 04 API / 数据字典任务。

---

### 22.17 待产品总控确认问题

1. `CsqStockCompactCard` 默认宽度是否需要从 Review v6 的 168px 再调整，以适配左 / 中 / 右三分区？当前建议允许 168～180px 范围内微调。
2. `codePill` 是否显示完整交易所后缀，如 `603017.SH`，还是显示简写 `603017`？当前建议完整显示，保持股票代码可识别。
3. `boardTradeAmount` 卡片内是否只显示金额，例如 `1.27亿`，完整口径放 Tooltip？当前建议如此。
4. `streakTextPill` 是否使用红色描边弱背景，还是品牌金弱背景？当前建议红色弱描边更贴近涨停语义，但不要大面积红底。
5. `latestPrice` 是否跟随方向弱着色？当前建议可弱着色，但 `changePct` 是唯一强方向色。
6. 右侧 `sectorName` 过长时是省略还是 Tooltip 展示完整？当前建议单行省略 + Tooltip。
7. 若一只股票属于多个板块，`sectorName` 是主板块、行业板块还是触发涨停的主题板块？当前组件只接收单一文本，业务层需决定。

---

### 22.18 Review v7 验收清单

| 验收项 | 要求 |
|---|---|
| 完整文档 | 本文件仍是完整 `04-component-guidelines.md`，不是 delta 文档。 |
| 修改边界 | 只修订 `CsqStockCompactCard`。 |
| codePill | `stockCode` 位于左上角胶囊，不在右上角，不进入主体普通列。 |
| 三分区 | `leftIdentity / centerMetrics / rightTags` 三分区清晰。 |
| leftIdentity | 包含 `stockName` 和 `latestPrice`。 |
| centerMetrics | 包含 `changePct` 和 `boardTradeAmount`。 |
| rightTags | 包含 `sectorName` 和 `streakTextPill`。 |
| 最新价 | 使用 `latestPrice`，不使用“收盘价格”。 |
| 板上成交额 | `boardTradeAmount` 口径明确：只在板上发生的成交金额，不是封单金额或全天成交额。 |
| N天M板标签 | `streakText` 是一个字段、一个标签，不拆分。 |
| 旧规则废弃 | 明确废弃右上角代码、2×3 机械网格、`currentStreakLevel` 右下覆盖方案。 |
| 连板天梯逻辑 | 不修改层级结构、昨日/今日规则、五板以上规则、展开/收起逻辑。 |
| 交互 | 卡片点击进入个股详情；父组件逻辑不变。 |
| API | 不正式修改 API 契约，只提供 Mock 字段建议。 |
| 未授权改动 | 未修改 Review v7 未点名组件或页面整体布局。 |

---

### 22.19 建议放置到 Google Drive 的路径

```text
财势乾坤/设计/04-component-guidelines.md
```

### 22.20 建议仓库保存路径

```text
/docs/wealth/04-component-guidelines.md
```

### 22.21 本轮输出文件下载链接

对话交付文件：

```text
sandbox:/mnt/data/review-v7-output-final/04-component-guidelines.md
```

