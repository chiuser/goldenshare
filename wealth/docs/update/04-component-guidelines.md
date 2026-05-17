# 财势乾坤｜P0 组件库与交互组件方案 v1.4 完整合并版

> 建议保存路径：`/docs/wealth/04-component-guidelines.md`  
> 负责人：`03_组件库与交互组件方案`  
> 状态：`Draft v1.4 merged-full / 个股详情页 StockHeader 红框 3 局部修订版`  
> 更新时间：`2026-05-16`  
> 本轮重点：在完整保留此前市场总览组件规范、通用组件库注册表、Review v5～v9 市场总览局部修订、个股详情页固定视口组件体系、Review v2 顶部结构修正与 Review v3 局部精修规则的基础上，只补充个股详情页 Review v4 对右侧 `StockHeader 红框 3` 的组件结构修正规则。
> 合并说明：本版以已交付的个股详情页 Review v3 完整合并版为基线，完整保留此前已确认内容，并只合并本轮针对 `StockHeaderPanel`、`StockHeaderSummaryRow`、`StockHeaderIdentityGroup`、`StockHeaderPriceGroup`、`StockHeaderActionLinks` 的局部修订。本轮不修改 TopMarketBar、Breadcrumb、Chart Workspace Toolbar、周期切换、前复权、股票资料、顶部诊股、设置、K 线主图、副图、坐标轴、时间轴、Header Info、MA/BOLL、十字线、Tooltip、盘口/资料 Tab、关联板块、个股资金统计图、API 字段和数据结构。请勿用局部 delta 文档覆盖本文件。

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
---

## 23. HTML Review v8 → market-overview-v1.7 顶部快讯板块局部修订合并规范

> 本节为 Review v8 对“市场总览 / 顶部快讯板块”的组件级修订。它不替代前文已确认的市场总览组件规范、通用组件库注册表、连板天梯规则或标准股票卡片规则，而是在完整保留 Review v7 完整合并版基线的前提下，只追加顶部快讯板块相关组件、交互规则、Mock 数据结构建议和后续 API 字段建议。  
> 本节不修改 TopMarketBar、Breadcrumb、PageHeader 左侧标题主体、ShortcutBar、今日市场客观总结、主要指数、涨跌分布、市场风格、成交额总览、大盘资金流向、榜单速览、涨跌停统计与分布、连板天梯、板块速览及 Review v8 未点名组件。

### 23.1 本轮读取文档与采用基线

| 序号 | 公共区文件 | 读取到的版本 / 状态 | 本轮用途 |
|---:|---|---|---|
| 1 | `财势乾坤/项目总说明/财势乾坤行情软件项目总说明_v_0_2.md` | `财势乾坤项目总说明 v0.2` / Review 草案 v0.2 | 继续约束产品定位、P0 范围、A 股优先、红涨绿跌、深色默认、专业沉稳风格。 |
| 2 | `财势乾坤/产品文档/市场总览产品需求文档 v0.2.md` | `市场总览产品需求文档 v0.2` / Review 草案 | 继续约束市场总览页面名称、归属、非目标、无固定 SideNav、客观事实页边界。 |
| 3 | `财势乾坤/设计/02-market-overview-page-design.md` | `市场总览页面设计文档 v0.1` | 作为市场总览页面设计基线；本轮仅修订顶部中间快讯板块，不主动调整正文模块。 |
| 4 | `财势乾坤/设计/03-design-tokens.md` | `Design Token 与视觉规范 v0.3.4` | 采用 Review v8 中快讯容器、ICON 预留位、竖排标题、新闻 item、跑马灯、hover 暂停与手动滚动 Token。 |
| 5 | `财势乾坤/设计/04-component-guidelines.md` | 公共区当前为 `P0 组件库与交互组件方案 v0.9 merged-full / Review v5 连板天梯局部修订版`；本文件实际以本会话已交付的 Review v7 完整合并版为直接基线 | 公共区文件被读取用于满足公共区基线检查；为避免回退 Review v6 / v7 已确认修订，本轮合并以 Review v7 完整合并版为实际内容基线。 |
| 6 | `财势乾坤/review/market-overview-html-review-v8-总控解读与变更单.md` | `市场总览 HTML Review v8｜总控解读与变更单` / 产品总控解读草案 | 本轮直接变更依据，限定只处理“市场总览 / 顶部快讯板块”。 |

本轮未能读取但应读取的文档：无。  
本轮是否继续：是。

---

### 23.2 本轮修订边界

#### 23.2.1 允许修改区域

```text
市场总览 / 顶部快讯板块
```

本轮允许新增或修订：

1. `MarketOverviewNewsFlashPanel`：市场总览顶部快讯板块业务组件；
2. `CsqNewsTickerColumn`：通用新闻滚动列组件；
3. `CsqNewsTickerItem`：通用新闻 item 数据结构与展示组件；
4. `CsqNewsTickerIconSlot`：ICON 预留位组件；
5. `CsqSyncedTickerController`：同步滚动交互约定或逻辑控制器；
6. 顶部快讯板块默认同步向上滚动规则；
7. hover 当前列暂停、另一列继续滚动规则；
8. P0 新闻 item 不可点击规则；
9. Showcase Mock 数据结构建议；
10. 后续如需接真实新闻源时给 04 API 的字段需求建议。

#### 23.2.2 禁止主动修改区域

以下组件和模块保持前文规范，不做主动改动：

- `TopMarketBar`
- `GlobalSystemMenu`
- `IndexTickerStrip`
- `Breadcrumb`
- `PageHeader` 左侧标题主体
- `MarketStatusPill`
- `DataStatusBadge`
- `ShortcutBar`
- `QuickEntryCard`
- `QuickEntryBadge`
- 今日市场客观总结相关组件
- `IndexGrid`
- `IndexCard`
- `MarketBreadthPanel` / 涨跌分布
- `DistributionChart`
- `HistoryTrendChart`
- `MarketStylePanel` / 市场风格
- `MarketStyleTrendChart`
- `TurnoverSummaryCard` / 成交额总览
- `IntradayTurnoverChart`
- `MoneyFlowSummaryPanel` / 大盘资金流向
- `MoneyFlowNetStructurePanel`
- `OrderSizeNetPieChart`
- `RankingTable` / 榜单速览
- `StockTable`
- `LimitUpSummaryCard`
- `LimitUpDistributionGrid` / 涨跌停统计与分布
- `LimitUpSectorLeaderPanel`
- `LimitUpLeaderPerformanceTable`
- `LimitUpDownHistoryBarChart`
- `MarketOverviewLimitLadder`
- `LimitLadderPromotionLayer`
- `LimitLadderSpecialLayer`
- `LimitLadderFirstLayer`
- `LimitLadderExpandControl`
- `CsqStockCompactCard`
- `SectorOverviewMatrix` / 板块速览
- `SectorHeatMap`
- 页面整体主题、全局字体、页面主体布局顺序、与 Review v8 无关的 Mock 数据结构

---

### 23.3 顶部快讯板块组件注册表补充

| 名称 | 类型 | 是否 Core Component | 是否 P0 必需 | 说明 |
|---|---|---:|---:|---|
| `MarketOverviewNewsFlashPanel` | Market Overview Business Component / Pattern | 否 | 是 | 市场总览页头部中间区域的业务组合组件，结构为 `ICON 预留位｜新闻速览｜个股新闻`。 |
| `CsqNewsTickerColumn` | Data Display / Interaction Component | 是，通用新闻滚动列 | 是 | 通用新闻 ticker 列，支持竖排或横排标题、新闻 item、向上滚动、hover 当前列暂停和手动滚动。 |
| `CsqNewsTickerItem` | Data Display Subcomponent / Data Model | 是，通用新闻 item | 是 | 展示单条新闻时间和标题；P0 不可点击。 |
| `CsqNewsTickerIconSlot` | Foundation / Slot Component | 是，通用图标预留位 | 是 | 固定尺寸 ICON 占位，不可点击，后续可替换正式图标。 |
| `CsqSyncedTickerController` | Interaction Controller / Hook / Agreement | 是，逻辑能力 | 是 | 描述同一 `syncGroupId` 下的滚动节奏同步、hover 当前列暂停、离开后恢复节奏。 |

说明：

1. `MarketOverviewNewsFlashPanel` 是市场总览业务组件，不进入 Core Component 契约。
2. `CsqNewsTickerColumn`、`CsqNewsTickerItem`、`CsqNewsTickerIconSlot`、`CsqSyncedTickerController` 可作为通用组件库能力，但本轮只要求支撑市场总览顶部快讯板块。
3. P0 阶段新闻 item 与 ICON 均不可点击；后续若接入资讯详情页，需要单独 Review 和 API 契约支持。

---

### 23.4 MarketOverviewNewsFlashPanel

| 项 | 说明 |
|---|---|
| 组件名 | `MarketOverviewNewsFlashPanel` |
| 中文名 | 市场总览顶部快讯板块 |
| 所属层级 | Market Overview Business Component / Pattern Example |
| 组件用途 | 在市场总览页头部中间区域展示快讯信息，帮助用户在不进入资讯页的情况下快速扫读市场级新闻和个股新闻。 |
| 是否 Core Component | 否。它是市场总览页面业务组件，不作为通用组件库 Core Component。 |
| 是否 P0 必需 | 是，Review v8 点名。 |
| 使用页面 | 市场总览 `market-overview-v1.7.html`。 |
| 固定结构 | `ICON 预留位 ｜ 新闻速览 ｜ 个股新闻`。 |
| 内部组件 | `CsqNewsTickerIconSlot`、`CsqNewsTickerColumn(title='新闻速览')`、`CsqNewsTickerColumn(title='个股新闻')`、`CsqSyncedTickerController`。 |
| 输入字段 / Props | `icon`、`marketNews`、`stockNews`、`syncGroupId`、`autoScroll`、`hoverPause`、`loading`、`emptyText`、`error`。 |
| 字段类型 | 见下方 TypeScript 接口。 |
| 与 API 字段映射 | P0 只使用 Showcase Mock：`newsFlash.marketNews[]`、`newsFlash.stockNews[]`；正式 API 暂不在本轮定义。 |
| 视觉结构 | 横向三段结构。左侧固定 ICON 预留位；中间和右侧为等宽新闻滚动列；每列左侧为竖排标题，右侧为新闻滚动列表。 |
| 交互行为 | 两列默认同步向上滚动；hover 到某一列只暂停当前列，当前列变为可手动滚动区域；另一列继续滚动；hover 离开后当前列恢复自动滚动并尽量回到同步节奏。 |
| 状态 | default：两列自动滚动；hover：当前列暂停并弱高亮；active：不需要强 active；selected：不使用；disabled：整体禁用时停止滚动并置灰；loading：ICON 保留、两列显示行骨架；empty：显示“暂无快讯”；error：局部错误，不影响 PageHeader 和正文模块。 |
| 点击行为 | P0 中 ICON 不可点击，新闻 item 不可点击，不跳转新闻详情，不打开外链。 |
| 涨跌色规则 | 该组件不展示行情涨跌值，不使用红绿表达新闻重要性；如后续新闻类型需要语义色，必须另行评审。 |
| Design Token 映射 | `--cs-news-ticker-*`、`--cs-color-surface-*`、`--cs-color-border-*`、`--cs-color-text-*`、`--cs-font-family-number`。 |
| 禁止误用 | 禁止做成营销 Banner；禁止新闻 item 加 pointer；禁止 hover 全板块时暂停两列；禁止压缩 TopMarketBar 或正文模块。 |

```ts
interface MarketOverviewNewsFlashPanelProps {
  icon?: React.ReactNode;
  marketNews: CsqNewsTickerItem[];
  stockNews: CsqNewsTickerItem[];
  syncGroupId?: string; // default: 'market-overview-news-flash'
  autoScroll?: boolean; // default: true
  hoverPause?: boolean; // default: true
  loading?: boolean;
  emptyText?: string;
  error?: ErrorStateProps | null;
}
```

#### 23.4.1 结构示意

```text
MarketOverviewNewsFlashPanel
├── CsqNewsTickerIconSlot
├── CsqNewsTickerColumn title="新闻速览"
│   ├── CsqNewsTickerItem[]
│   └── syncedTickerBehavior
└── CsqNewsTickerColumn title="个股新闻"
    ├── CsqNewsTickerItem[]
    └── syncedTickerBehavior
```

#### 23.4.2 页面位置规则

快讯板块推荐放在市场总览页头部中间区域：

```text
左侧：页面标题区 / 市场总览 / A股 / 交易日
中间：MarketOverviewNewsFlashPanel
右侧：数据更新时间 / 手动刷新
```

允许轻微调整 PageHeader 中间区域，但不得改动 PageHeader 左侧标题主体、TopMarketBar、Breadcrumb、ShortcutBar 和正文模块顺序。

---

### 23.5 CsqNewsTickerColumn

| 项 | 说明 |
|---|---|
| 组件名 | `CsqNewsTickerColumn` |
| 中文名 | 新闻滚动列 |
| 所属层级 | Data Display Components / Interaction Components |
| 组件用途 | 通用新闻滚动列，用于以高密度方式展示一组按时间倒序排列的新闻 item，并支持自动向上滚动与 hover 当前列暂停。 |
| 是否 Core Component | 是。组件不绑定市场总览、不绑定新闻源、不绑定 API response。 |
| 是否 P0 必需 | 是，Review v8 点名。 |
| 使用场景 | 市场总览顶部快讯、未来资讯条、公告滚动列、系统消息滚动列。 |
| 输入字段 / Props | `title`、`titleDirection`、`items`、`syncGroupId`、`autoScroll`、`scrollDirection`、`hoverPause`、`itemClickable`、`loading`、`emptyText`。 |
| 字段类型 | 见下方 TypeScript 接口。 |
| 视觉结构 | 左侧窄标题区 + 右侧新闻列表区。标题可竖排或横排；市场总览使用竖排。新闻列表区域显示 `timestamp + title`。 |
| 默认滚动 | `autoScroll=true` 时自动向上滚动；`scrollDirection` 目前只支持 `up`；同一 `syncGroupId` 下默认节奏一致。 |
| hover 暂停 | hover 当前列时，仅暂停当前列；当前列变成可手动滚动区域；另一列不受影响。 |
| 手动滚动 | hover 后当前列 `overflow-y: auto`，允许鼠标滚轮上下浏览；滚动条细而弱。 |
| 恢复滚动 | hover 离开后恢复自动滚动，并尽量回到同组 ticker 的全局滚动节奏。 |
| 点击行为 | P0 固定 `itemClickable=false`；item 不跳转，不打开详情，不打开外链，不显示强点击态。 |
| 状态 | default：自动滚动；hover：当前列弱高亮并暂停；active：不需要；selected：不使用；disabled：停滚置灰；loading：新闻行骨架；empty：展示空态；error：展示局部错误。 |
| Design Token 映射 | `--cs-news-ticker-title-*`、`--cs-news-ticker-list-height`、`--cs-news-ticker-item-*`、`--cs-news-ticker-scrollbar-*`。 |
| 禁止误用 | 禁止使用 pointer；禁止默认点击跳转；禁止在 Core Props 中绑定 marketNews / stockNews 等业务字段名。 |

```ts
interface CsqNewsTickerColumnProps {
  title: string;
  titleDirection?: 'vertical' | 'horizontal';
  items: CsqNewsTickerItem[];
  syncGroupId?: string;
  autoScroll?: boolean;
  scrollDirection?: 'up';
  hoverPause?: boolean;
  itemClickable?: false;
  loading?: boolean;
  emptyText?: string;
  error?: ErrorStateProps | null;
}
```

#### 23.5.1 标题规则

市场总览中固定使用：

```ts
titleDirection = 'vertical'
```

标题文案：

```text
新闻速览
个股新闻
```

竖排标题应弱强调，不使用大面积红、绿、黄背景，不照搬截图标注框。

#### 23.5.2 可视行数规则

可视行数不固定写死，由容器高度和 item 行高动态计算：

```ts
visibleCount = Math.floor(newsListHeight / newsItemLineHeight);
```

市场总览视觉目标约 3 条，但组件契约不写死 3 条。

---

### 23.6 CsqNewsTickerItem

| 项 | 说明 |
|---|---|
| 组件名 / 数据名 | `CsqNewsTickerItem` |
| 中文名 | 新闻滚动条目 |
| 所属层级 | Data Display Subcomponent / Data Model |
| 组件用途 | 表示新闻滚动列中的单条新闻，展示时间与标题。 |
| 是否 Core Component | 是。它是通用新闻 item 展示契约，不绑定市场总览或具体新闻源。 |
| 是否 P0 必需 | 是，Review v8 点名。 |
| 字段 | `id`、`timestamp`、`title`、`type`。 |
| 时间格式 | 显示为 `MM-DD HH:mm:ss`，例如 `04-28 15:05:00`。 |
| 标题展示 | 单行展示，超出列宽使用 `...` 省略。 |
| 点击行为 | P0 不可点击；不跳转新闻详情、不打开外链、不进入公告或资讯页。 |
| hover 行为 | hover 仅用于阅读状态，允许弱背景高亮；不触发跳转，不显示强点击态。 |
| cursor | 必须使用 `default`，不使用 `pointer`。 |
| 状态 | default：正常行；hover：弱高亮；disabled：弱化；loading：行骨架；empty/error 由父列处理。 |
| Design Token 映射 | `--cs-news-ticker-time-*`、`--cs-news-ticker-title-text-*`、`--cs-news-ticker-item-hover-bg`、`--cs-font-family-number`。 |
| 禁止误用 | 禁止携带 URL 并默认点击；禁止使用红绿表达新闻重要性；禁止标题换行撑高列表。 |

```ts
interface CsqNewsTickerItem {
  id: string;
  timestamp: string; // MM-DD HH:mm:ss
  title: string;
  type?: 'market' | 'stock' | 'system';
}
```

#### 23.6.1 显示规则

```text
04-28 15:05:00  央行公开市场开展逆回购操作，市场流动性保持合理充裕
```

实现建议：

```css
.csq-news-ticker-item {
  cursor: default;
}

.csq-news-ticker-title {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
```

---

### 23.7 CsqNewsTickerIconSlot

| 项 | 说明 |
|---|---|
| 组件名 | `CsqNewsTickerIconSlot` |
| 中文名 | 快讯 ICON 预留位 |
| 所属层级 | Foundation Components / Slot Component |
| 组件用途 | 为快讯板块提供固定尺寸的图标占位，后续可替换正式 ICON。 |
| 是否 Core Component | 是。它是通用占位 slot，不绑定市场总览。 |
| 是否 P0 必需 | 是，Review v8 点名。 |
| 输入字段 / Props | `icon`、`size`、`ariaLabel`、`placeholder`。 |
| 视觉结构 | 固定宽度和高度，居中显示占位图标。 |
| 点击行为 | 不可点击，不设置 `onClick`，不使用 pointer。 |
| hover 行为 | 可保持静态或轻微视觉反馈，但不能表现为可点击。hover ICON 不暂停新闻滚动。 |
| 状态 | default：占位图标；loading：仍显示占位；disabled：弱化；empty/error 不单独处理。 |
| Design Token 映射 | `--cs-news-ticker-icon-slot-width`、`--cs-news-ticker-icon-size`、`--cs-news-ticker-icon-bg`、`--cs-news-ticker-icon-border`、`--cs-news-ticker-icon-color`。 |
| 禁止误用 | 禁止做成按钮；禁止绑定新闻详情入口；禁止 hover ICON 暂停两列 ticker。 |

```ts
interface CsqNewsTickerIconSlotProps {
  icon?: React.ReactNode;
  size?: number;
  ariaLabel?: string;
  placeholder?: boolean;
}
```

---

### 23.8 CsqSyncedTickerController

| 项 | 说明 |
|---|---|
| 组件名 / 交互约定 | `CsqSyncedTickerController` |
| 中文名 | 同步滚动控制器 |
| 所属层级 | Interaction Controller / Hook / Agreement |
| 组件用途 | 描述同一 `syncGroupId` 下多个 ticker column 的默认同步滚动节奏，以及 hover 当前列暂停、离开后恢复滚动的交互约定。 |
| 是否 Core Component | 是，作为逻辑能力或 hook 进入组件库；可实现为 `useSyncedTickerController`、状态机或 JS 控制器。 |
| 是否 P0 必需 | 是，Review v8 点名。 |
| 输入字段 / Props | `syncGroupId`、`columns`、`duration`、`direction`、`hoverPauseMode`、`resumeStrategy`。 |
| 默认同步 | 同一 `syncGroupId` 下的列共用滚动周期、方向和节奏。 |
| hover 暂停 | `hoverPauseMode='current-column-only'`：只暂停当前 hover 列；其它列继续滚动。 |
| 手动滚动 | 当前列 hover 后变为可手动滚动容器；手动滚动不影响其它列。 |
| 恢复策略 | hover 离开后当前列恢复自动滚动，并尽量对齐全局同步节奏。 |
| 不要求 | 不要求像素级强同步；不要求两列新闻数量一致；不要求暂停列追帧动画。 |
| 禁止误用 | 禁止 hover 任意列时暂停整个 group；禁止把 item 点击逻辑放入同步控制器。 |

```ts
interface CsqSyncedTickerControllerOptions {
  syncGroupId: string;
  columnIds: string[];
  duration?: number;
  direction?: 'up';
  hoverPauseMode?: 'current-column-only';
  resumeStrategy?: 'align-to-group-clock' | 'continue-from-current-offset';
}
```

#### 23.8.1 交互状态机建议

```ts
type NewsTickerColumnState =
  | 'autoScrolling'
  | 'hoverPausedManualScrollable'
  | 'resuming'
  | 'disabled';
```

状态转换：

```text
autoScrolling
  ├─ mouseenter column -> hoverPausedManualScrollable
  ├─ disabled -> disabled

hoverPausedManualScrollable
  ├─ mouseleave column -> resuming
  ├─ disabled -> disabled

resuming
  ├─ aligned or animation resumed -> autoScrolling
```

---

### 23.9 顶部快讯板块交互规则

#### 23.9.1 默认滚动

1. 两列默认同步向上滚动。
2. 滚动方向为 `up`。
3. 最新新闻在上，旧新闻在下。
4. 滚动循环播放。
5. 可视行数由容器高度和 item 行高动态计算。
6. 两列使用同一 `syncGroupId`，默认同一滚动节奏。
7. 两列新闻数量可以不同；数量不足时可以静止、克隆补位或低频滚动，但不能伪造新闻。

#### 23.9.2 hover 暂停

1. hover 到新闻速览，只暂停新闻速览。
2. hover 到个股新闻，只暂停个股新闻。
3. 当前列变成可手动滚动区域。
4. 另一列继续自动滚动。
5. hover ICON 不暂停新闻。
6. hover 快讯容器空白区域不强制暂停。
7. hover 离开后当前列恢复跑马灯，并尽量回到同步节奏。

#### 23.9.3 点击行为

P0 固定：

1. 新闻 item 不可点击；
2. ICON 不可点击；
3. 不跳转新闻详情；
4. 不跳转外链；
5. 不显示强点击态；
6. 不出现 `cursor: pointer`；
7. 不设置 `onItemClick`。

如后续 P1 需要新闻详情或外链跳转，必须由 PRD / 04 API / 05 Codex 提示词另行定义。

---

### 23.10 Mock 数据结构建议

> 本节结构仅用于 Showcase Mock 和组件设计，不作为正式 API 契约。  
> 本轮 03 只提出 Mock 结构建议，不正式修改 API；04 后续如需接真实新闻源再单独定义 API / 数据字典口径。

```ts
interface MarketOverviewNewsFlash {
  marketNews: CsqNewsTickerItem[];
  stockNews: CsqNewsTickerItem[];
}

const marketOverviewNewsFlashMock: MarketOverviewNewsFlash = {
  marketNews: [
    {
      id: 'news-001',
      timestamp: '04-28 15:05:00',
      title: '央行公开市场开展逆回购操作，市场流动性保持合理充裕',
      type: 'market',
    },
    {
      id: 'news-002',
      timestamp: '04-28 14:58:12',
      title: '两市成交额持续放大，主要宽基指数尾盘窄幅震荡',
      type: 'market',
    },
  ],
  stockNews: [
    {
      id: 'stock-news-001',
      timestamp: '04-28 15:03:44',
      title: '中衡设计封住涨停，低空经济概念股活跃度提升',
      type: 'stock',
    },
    {
      id: 'stock-news-002',
      timestamp: '04-28 14:51:09',
      title: '工业富联成交额居前，AI 服务器方向资金关注度较高',
      type: 'stock',
    },
  ],
};
```

Mock 规则：

1. 每列建议至少 6～10 条新闻，用于验证循环滚动、hover 暂停和手动滚动。
2. `timestamp` 必须使用 `MM-DD HH:mm:ss`。
3. `title` 必须具有真实新闻感，但不得包含买卖建议。
4. `type='market'` 用于新闻速览；`type='stock'` 用于个股新闻；`type='system'` 可用于后续系统公告场景。
5. Mock 不包含 URL、详情页 ID 或点击路由。

---

### 23.11 对 02 `market-overview-v1.7.html` 的组件使用建议

1. 只新增或修改市场总览页顶部中间区域的快讯板块。
2. 不修改 TopMarketBar。
3. 不修改 Breadcrumb。
4. 不修改 PageHeader 左侧标题主体。
5. 不修改 ShortcutBar。
6. 不修改正文模块。
7. 使用 `MarketOverviewNewsFlashPanel` 组合快讯板块。
8. 快讯板块必须包含 `CsqNewsTickerIconSlot`、`新闻速览` 列、`个股新闻` 列。
9. `新闻速览` 与 `个股新闻` 均使用 `CsqNewsTickerColumn`。
10. 两列均使用竖排标题。
11. 每条新闻使用 `CsqNewsTickerItem` 展示 `timestamp + title`。
12. 时间格式必须为 `MM-DD HH:mm:ss`。
13. 标题必须单行展示，超出宽度以 `...` 省略。
14. 默认从下向上跑马灯。
15. 新闻速览与个股新闻默认同步滚动。
16. hover 到新闻速览时，只暂停新闻速览；个股新闻继续滚动。
17. hover 到个股新闻时，只暂停个股新闻；新闻速览继续滚动。
18. hover 后当前列可手动滚动浏览。
19. hover 离开后当前列恢复跑马灯，并尽量回到全局同步节奏。
20. 新闻 item 一期不可点击。
21. ICON 不可点击。
22. 不照搬用户截图中的红框、绿框、黄色框等标注元素。
23. 使用当前市场总览深色金融终端风格。

---

### 23.12 对 01 Design Token 的依赖

本节依赖 `03-design-tokens.md v0.3.4` 中以下 Token 或规则：

| 组件 / Pattern | Token / 规则 |
|---|---|
| `MarketOverviewNewsFlashPanel` | `--cs-news-ticker-*`、`--cs-color-surface-*`、`--cs-color-border-*` |
| `CsqNewsTickerIconSlot` | `--cs-news-ticker-icon-slot-width`、`--cs-news-ticker-icon-size`、`--cs-news-ticker-icon-bg`、`--cs-news-ticker-icon-border`、`--cs-news-ticker-icon-color` |
| `CsqNewsTickerColumn` | `--cs-news-ticker-title-*`、`--cs-news-ticker-column-gap`、`--cs-news-ticker-list-height`、`--cs-news-ticker-scrollbar-*` |
| `CsqNewsTickerItem` | `--cs-news-ticker-item-*`、`--cs-news-ticker-time-*`、`--cs-news-ticker-title-text-*` |
| `CsqSyncedTickerController` | `--cs-news-ticker-marquee-duration`、`--cs-news-ticker-marquee-step-duration` |

必须遵守：

1. 深色主题优先；
2. 新闻 item 不使用红绿表达重要性；
3. hover 仅弱高亮，不表现为强点击态；
4. ICON slot 不使用 pointer；
5. 竖排标题使用弱强调，不做彩色大标签；
6. 滚动条使用弱中性色，hover 可轻微品牌金。

---

### 23.13 对 04 API 的字段需求建议

本轮不正式修改 API 契约。若后续需要接真实新闻接口，建议 04 单独设计新闻 API，并考虑以下字段：

| 字段 | 建议类型 | 说明 |
|---|---|---|
| `id` | `string` | 新闻唯一 ID。 |
| `timestamp` | `string` | 展示时间，前端格式化为 `MM-DD HH:mm:ss`。 |
| `title` | `string` | 新闻标题，单行省略。 |
| `type` | `'market' | 'stock' | 'system'` | 新闻类型。 |
| `source` | `string` | 新闻来源，可选。 |
| `stockCode` | `string` | 个股新闻关联股票代码，可选。 |
| `stockName` | `string` | 个股新闻关联股票名称，可选。 |
| `sectorCode` | `string` | 关联板块，可选。 |
| `priority` | `number` | 排序优先级，可选。 |
| `detailUrl` | `string` | P1/P2 点击详情时再启用，P0 不使用。 |

P0 阶段页面组件只需要：

```ts
interface MarketOverviewNewsFlash {
  marketNews: CsqNewsTickerItem[];
  stockNews: CsqNewsTickerItem[];
}
```

---

### 23.14 是否需要后续拉 04 参与的条件

本轮不要求 04 API 与数据字典参与，因为当前任务只要求组件设计和 Showcase Mock 结构建议。

后续在以下任一条件出现时，需要单独拉 04 参与：

1. 需要接入真实新闻数据源；
2. 需要区分市场新闻、个股新闻、公告、系统消息；
3. 需要新闻来源、优先级、标签、关联股票或关联板块字段；
4. 需要支持新闻详情页或外链跳转；
5. 需要通过 API 控制新闻是否可点击；
6. 需要服务端决定排序、置顶、去重或过期策略；
7. 需要审计新闻时效性、数据源延迟和免责声明。

---

### 23.15 本轮 Review v8 修改摘要

1. 新增 `MarketOverviewNewsFlashPanel`，用于市场总览页顶部中间区域快讯板块。
2. 新增 `CsqNewsTickerColumn`，作为通用新闻滚动列组件。
3. 新增 `CsqNewsTickerItem`，作为新闻 item 展示契约。
4. 新增 `CsqNewsTickerIconSlot`，作为 ICON 预留位。
5. 新增 `CsqSyncedTickerController`，作为同步滚动交互约定或逻辑控制器。
6. 快讯板块固定结构为 `ICON 预留位 ｜ 新闻速览 ｜ 个股新闻`。
7. 新闻速览与个股新闻默认同步向上滚动。
8. hover 到某一列时，只暂停当前列，另一列继续滚动。
9. hover 后当前列可手动滚动浏览。
10. hover 离开后当前列恢复自动滚动，并尽量回到同步节奏。
11. 新闻 item P0 不可点击；ICON P0 不可点击。
12. 本轮不修改市场总览正文模块和 Review v8 未点名组件。

---

### 23.16 本轮新增或修订组件清单

| 类型 | 组件 / Pattern | 处理方式 |
|---|---|---|
| 新增 | `MarketOverviewNewsFlashPanel` | 新增市场总览顶部快讯板块业务组件，不进入 Core。 |
| 新增 | `CsqNewsTickerColumn` | 新增通用新闻滚动列组件。 |
| 新增 | `CsqNewsTickerItem` | 新增通用新闻 item 展示契约。 |
| 新增 | `CsqNewsTickerIconSlot` | 新增 ICON 预留位组件。 |
| 新增 | `CsqSyncedTickerController` | 新增同步滚动控制器 / hook / 交互约定。 |

---

### 23.17 本轮未修改组件清单

以下组件保持前文规范，不做主动改动：

- `TopMarketBar`
- `GlobalSystemMenu`
- `IndexTickerStrip`
- `Breadcrumb`
- `PageHeader` 左侧标题主体
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
- `MoneyFlowNetStructurePanel`
- `OrderSizeNetPieChart`
- `RankingTable`
- `StockTable`
- `LimitUpSummaryCard`
- `LimitUpDistributionGrid`
- `LimitUpSectorLeaderPanel`
- `LimitUpLeaderPerformanceTable`
- `LimitUpDownHistoryBarChart`
- `MarketOverviewLimitLadder`
- `LimitLadderPromotionLayer`
- `LimitLadderSpecialLayer`
- `LimitLadderFirstLayer`
- `LimitLadderExpandControl`
- `CsqStockCompactCard`
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

本轮因 Review v8 修改而被动影响的区域：

```text
本轮因 Review v8 修改而被动影响的区域：
- PageHeader / 页头部中间区域
原因：需要在页面标题区和数据更新时间区域之间安放顶部快讯板块
是否需要产品总控确认：否，Review v8 已明确该位置；但 02 Showcase 需要验证横向空间是否足够
```

---

### 23.18 待产品总控确认问题

1. 快讯板块最终宽度是否固定，还是随 PageHeader 中间区域自适应？当前建议 `min-width: 520px; max-width: 760px`。
2. ICON 预留位最终图标是否使用品牌图标、新闻图标，还是单独设计快讯图标？当前建议 P0 使用占位图标。
3. 新闻速览与个股新闻是否必须始终两列等宽？当前建议基本等宽。
4. 快讯可视行数是否允许随高度动态变化？当前建议目标约 3 行，但不写死。
5. hover 离开后是否必须精确恢复到全局同步位置？当前建议“尽量恢复”，不强制像素级同步。
6. P0 是否明确不支持新闻点击？当前规范已按不可点击处理。
7. 后续是否需要 04 API 设计真实新闻接口？当前 P0 可以先使用 Mock 数据。
8. 如果顶部空间不足，是否允许隐藏 ICON 预留位以优先保留两列新闻？当前建议不隐藏 ICON，先压缩标题宽度并做 ellipsis。
9. 新闻 item 是否需要展示来源？当前建议 P0 不展示来源，仅 Mock 中保留 `type`。

---

### 23.19 Review v8 验收清单

| 验收项 | 要求 |
|---|---|
| 完整文档 | 本文件仍是完整 `04-component-guidelines.md`，不是 delta 文档。 |
| 修改边界 | 只新增/修订 Review v8 点名的顶部快讯板块相关组件。 |
| 业务组件 | `MarketOverviewNewsFlashPanel` 结构清晰，明确不作为 Core Component。 |
| 新闻列 | `CsqNewsTickerColumn` 支持竖排标题、新闻列表、自动向上滚动、hover 当前列暂停和手动滚动。 |
| 新闻 item | `CsqNewsTickerItem` 字段清晰，时间格式为 `MM-DD HH:mm:ss`，标题单行省略。 |
| ICON | `CsqNewsTickerIconSlot` 固定尺寸、不可点击、可替换正式图标。 |
| 同步滚动 | `CsqSyncedTickerController` 明确两列默认同步滚动，同组节奏一致。 |
| hover 暂停 | hover 新闻速览只暂停新闻速览；hover 个股新闻只暂停个股新闻；另一列继续滚动。 |
| 点击规则 | 新闻 item P0 不可点击，ICON 不可点击，不显示 pointer。 |
| Mock | `MarketOverviewNewsFlash` Mock 结构只用于 Showcase，不作为正式 API 契约。 |
| API | 本轮不正式修改 API，只列出后续 04 字段需求建议。 |
| 未授权改动 | 未修改 TopMarketBar、Breadcrumb、PageHeader 左侧标题主体、ShortcutBar、正文模块或 Review v8 未点名组件。 |

---

### 23.20 建议放置到 Google Drive 的路径

```text
财势乾坤/设计/04-component-guidelines.md
```

### 23.21 建议仓库保存路径

```text
/docs/wealth/04-component-guidelines.md
```

### 23.22 本轮输出文件下载链接

对话交付文件：

```text
sandbox:/mnt/data/review-v8-output-final/04-component-guidelines.md
```



---

# 24. HTML Review v9 → market-overview-v1.8 新闻板块局部修订合并规范

> 本节为 Review v9 对“市场总览 / 新闻速览板块 / 个股新闻板块”的组件级修订。它不替代前文已确认的通用组件库注册表、市场总览页面组件规范或 Review v1～v8 已确认内容，而是在完整保留 Review v8 merged-full 基线的前提下，只追加新闻板块新布局、新组件契约、滚动控制、Mock 结构和后续 API 字段建议。  
> 本节明确废弃 Review v8 的“顶部中间统一快讯条”方案；不修改 TopMarketBar、Breadcrumb、PageHeader、ShortcutBar、今日市场客观总结内部内容、主要指数内部内容、涨跌分布、市场风格、成交额总览、大盘资金流向、榜单速览、涨跌停统计与分布、连板天梯、板块速览及其它 Review v9 未点名组件。

## 24.1 本轮读取文档与采用基线

| 序号 | 公共区文件 | 读取到的版本 / 状态 | 本轮用途 |
|---:|---|---|---|
| 1 | `财势乾坤/项目总说明/财势乾坤行情软件项目总说明_v_0_2.md` | `财势乾坤项目总说明 v0.2` / Review 草案 v0.2 | 继续约束产品定位、P0 范围、A 股优先、红涨绿跌、深色默认、专业沉稳风格。 |
| 2 | `财势乾坤/产品文档/市场总览产品需求文档 v0.2.md` | `市场总览产品需求文档 v0.2` / Review 草案 | 继续约束市场总览页面名称、归属、非目标、无固定 SideNav、客观事实页边界。 |
| 3 | `财势乾坤/设计/02-market-overview-page-design.md` | `市场总览页面设计文档 v0.1` | 作为市场总览页面设计基线；本轮仅修订新闻板块与首屏上方局部上下组合关系。 |
| 4 | `财势乾坤/设计/03-design-tokens.md` | `Design Token 与视觉规范 v0.3.5` 或公共区当前 Review v9 更新版 | 采用 Review v9 中独立新闻面板、新闻 item、标题、省略、hover 暂停、手动滚动态等 Token。 |
| 5 | `财势乾坤/设计/04-component-guidelines.md` | 公共区当前版本仍可能落后于本会话 Review v6/v7/v8 已交付文件 | 本轮以本会话 Review v8 完整版为安全合并基线，避免回退已确认内容。 |
| 6 | `财势乾坤/review/market-overview-html-review-v9-总控解读与变更单.md` | `市场总览 HTML Review v9｜总控解读与变更单` | 本轮直接变更单，规定只处理新闻速览板块、个股新闻板块和滚动交互。 |

本轮未能读取但应读取的文档：无。  
本轮是否继续：是。

---

## 24.2 本轮修订边界

### 24.2.1 允许修改区域

```text
市场总览 / 新闻速览板块
市场总览 / 个股新闻板块
新闻板块与“今日市场客观总结 / 主要指数”的上下布局关系
```

允许轻微调整：

```text
今日市场客观总结与主要指数所在首屏区域的局部垂直排布
```

### 24.2.2 禁止主动修改区域

以下组件和模块保持 Review v8 merged-full 规范，不做主动改动：

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
- 今日市场客观总结内部内容
- 主要指数内部内容
- `MarketBreadthPanel` / 涨跌分布
- `MarketStylePanel` / 市场风格
- `TurnoverSummaryCard` / 成交额总览
- `MoneyFlowSummaryPanel` / 大盘资金流向
- `RankingTable` / 榜单速览
- `LimitUpDistributionGrid` / 涨跌停统计与分布
- `MarketOverviewLimitLadder` / 连板天梯
- `SectorOverviewMatrix` / 板块速览矩阵
- `SectorHeatMap` / 板块热力图
- 与 Review v9 无关的 Core Components、Pattern Examples、Mock 数据结构和页面整体主题。

---

## 24.3 废弃 Review v8 顶部中间统一快讯条方案

Review v8 的以下结构从 `market-overview-v1.8.html` 起作废：

```text
ICON 预留位 ｜ 新闻速览 ｜ 个股新闻
```

本轮明确不再使用：

1. `MarketOverviewNewsFlashPanel` 作为顶部中间统一快讯条业务组件；
2. `CsqNewsTickerIconSlot`；
3. 顶部中间统一横向快讯容器；
4. 竖排标题；
5. PageHeader 中间区域承载快讯板块的布局；
6. ICON hover / 占位相关交互。

兼容处理：

- `CsqNewsTickerColumn` 与 `CsqNewsTickerItem` 的部分滚动逻辑可被 `CsqNewsTickerList` 复用，但 v9 推荐组件名和结构以本节为准。
- Review v8 的顶部快讯条规范只保留为历史记录，不作为 `market-overview-v1.8.html` 的实现依据。

---

## 24.4 新版新闻板块布局规则

### 24.4.1 左侧组合

```text
┌──────────────────────────────┐
│ 新闻速览                      │
│ 04-28 15:05:00  新闻标题...   │
│ ...                           │
└──────────────────────────────┘

┌──────────────────────────────┐
│ 今日市场客观总结              │
│ ...                           │
└──────────────────────────────┘
```

规则：

1. `新闻速览` 位于 `今日市场客观总结` 正上方。
2. `新闻速览` 与 `今日市场客观总结` 等宽。
3. `新闻速览` 与右侧 `个股新闻` 高度一致。
4. `新闻速览` 不改变今日市场客观总结内部的 5 个事实卡片与说明卡结构。

### 24.4.2 右侧组合

```text
┌──────────────────────────────┐
│ 个股新闻                      │
│ 04-28 15:05:00  新闻标题...   │
│ ...                           │
└──────────────────────────────┘

┌──────────────────────────────┐
│ 主要指数                      │
│ ...                           │
└──────────────────────────────┘
```

规则：

1. `个股新闻` 位于 `主要指数` 正上方。
2. `个股新闻` 与 `主要指数` 等宽。
3. `个股新闻` 与左侧 `新闻速览` 高度一致。
4. `个股新闻` 不改变主要指数的两行、每行五个指数卡结构。

### 24.4.3 左右整体关系

```text
┌──────────────────────────────┬──────────────────────────────┐
│ 新闻速览                      │ 个股新闻                      │
├──────────────────────────────┼──────────────────────────────┤
│ 今日市场客观总结              │ 主要指数                      │
└──────────────────────────────┴──────────────────────────────┘
```

说明：

- 上图只是结构示意，不代表最终边框和像素样式。
- 最终视觉必须遵守 `03-design-tokens.md` 的深色金融终端风格。
- 本轮不在 TopMarketBar、Breadcrumb、PageHeader、ShortcutBar 中放置新闻板块。

---

## 24.5 MarketOverviewNewsPanel

| 项 | 说明 |
|---|---|
| 组件名 | `MarketOverviewNewsPanel` |
| 中文名 | 市场总览新闻面板 |
| 所属层级 | Market Overview Business Component / 页面业务组件 |
| 组件用途 | 在市场总览首屏上方分别展示“新闻速览”和“个股新闻”两个独立新闻板块。 |
| 是否 Core Component | 否。它是市场总览页面业务组件，不进入通用组件库 Core Component。内部应组合 `CsqNewsTickerList` 与 `CsqNewsTickerItem`。 |
| 是否市场总览 P0 必需 | 是，Review v9 点名。 |
| 使用页面 | 市场总览 `market-overview-v1.8.html`。 |
| 使用位置 | `新闻速览` 位于今日市场客观总结正上方；`个股新闻` 位于主要指数正上方。 |
| 输入字段 / Props | `title`、`items`、`visibleItemCount`、`syncGroupId`、`autoScroll`、`hoverPause`、`itemClickable`。 |
| 默认值 | `visibleItemCount=10`、`autoScroll=true`、`hoverPause=true`、`itemClickable=false`。 |
| 视觉结构 | 标准 Panel：横向标题 + 新闻滚动列表。标题不竖排，不需要 ICON 预留位。 |
| 交互行为 | 面板内部默认向上滚动；hover 当前面板只暂停当前面板；hover 后可手动滚动；item 不可点击。 |
| 状态 | default、hover、active、selected、disabled、loading、empty、error。active/selected 通常由外部少量使用；P0 新闻 item 不触发强点击态。 |
| 涨跌色规则 | 新闻本身不承载涨跌色；若标题中出现股票涨跌，不在新闻 item 内用红绿自动解析。红涨绿跌仍适用于页面其它行情组件。 |
| 与 Design Token 映射 | `--cs-news-panel-*`、`--cs-news-item-*`、`--cs-news-scroll-*`、`--cs-color-surface-panel`、`--cs-color-border-subtle`、`--cs-font-family-number`。 |
| 禁止误用 | 禁止重新实现 Review v8 的顶部中间统一快讯条；禁止显示 ICON 预留位；禁止竖排标题；禁止把 item 做成可点击新闻链接。 |

```ts
interface MarketOverviewNewsPanelProps {
  title: '新闻速览' | '个股新闻';
  items: CsqNewsTickerItem[];
  visibleItemCount?: number; // default: 10
  syncGroupId?: string;
  autoScroll?: boolean;      // default: true
  hoverPause?: boolean;      // default: true
  itemClickable?: false;     // P0 固定 false
}
```

### 24.5.1 使用示例

```tsx
<MarketOverviewNewsPanel
  title="新闻速览"
  items={marketNews}
  visibleItemCount={10}
  syncGroupId="market-overview-news"
  autoScroll
  hoverPause
  itemClickable={false}
/>

<MarketOverviewNewsPanel
  title="个股新闻"
  items={stockNews}
  visibleItemCount={10}
  syncGroupId="market-overview-news"
  autoScroll
  hoverPause
  itemClickable={false}
/>
```

---

## 24.6 CsqNewsTickerList

| 项 | 说明 |
|---|---|
| 组件名 | `CsqNewsTickerList` |
| 中文名 | 新闻滚动列表 |
| 所属层级 | Data Display Components / 通用列表交互组件 |
| 组件用途 | 承载新闻 item 的向上滚动、同步滚动、hover 暂停和手动滚动能力。 |
| 是否 Core Component | 可以作为通用组件库组件，但 Props 保持抽象，不绑定市场总览 API。 |
| 是否市场总览 P0 必需 | 是，Review v9 点名。 |
| 输入字段 / Props | `items`、`visibleItemCount`、`syncGroupId`、`autoScroll`、`scrollDirection`、`hoverPause`、`itemClickable`、`itemRenderer`。 |
| 默认值 | `visibleItemCount=10`、`autoScroll=true`、`scrollDirection='up'`、`hoverPause=true`、`itemClickable=false`。 |
| 视觉结构 | 一个固定高度滚动视窗 + track + `CsqNewsTickerItem[]`。视窗高度由 `visibleItemCount × itemHeight` 或外部 CSS 决定。 |
| 同步滚动 | 同一 `syncGroupId` 下的多个列表默认共用滚动节奏。两列数量不同时，各自循环，但节奏一致。 |
| hover 暂停 | hover 当前列表时只暂停当前列表；同组其它列表继续自动滚动。 |
| 手动滚动 | hover 后当前列表 `overflow-y:auto`，允许鼠标滚轮查看。 |
| 恢复滚动 | hover 离开后恢复自动向上滚动，并尽量回到同组节奏。 |
| 状态 | loading：显示 `visibleItemCount` 行骨架；empty：显示“暂无新闻”；error：局部错误与重试；disabled：停止滚动且置灰。 |
| 与 Design Token 映射 | `--cs-news-list-height`、`--cs-news-item-height`、`--cs-news-scrollbar-*`、`--cs-news-item-hover-bg`。 |
| 禁止误用 | 禁止将 `visibleItemCount=10` 写死在组件内部；禁止 item 默认可点击；禁止 hover 当前列表时暂停同组所有列表。 |

```ts
interface CsqNewsTickerListProps {
  items: CsqNewsTickerItem[];
  visibleItemCount?: number; // default: 10
  syncGroupId?: string;
  autoScroll?: boolean;      // default: true
  scrollDirection?: 'up';    // P0 只支持 up
  hoverPause?: boolean;      // default: true
  itemClickable?: false;     // P0 fixed false
  loading?: boolean;
  emptyText?: string;
  error?: ErrorStateProps | null;
  itemRenderer?: (item: CsqNewsTickerItem) => React.ReactNode;
}
```

### 24.6.1 可视条数规则

1. `visibleItemCount` 默认 10。
2. 10 条是默认配置，不是硬编码常量。
3. 页面或调用方可以调整 `visibleItemCount`。
4. 视窗高度建议由以下规则计算：

```text
listViewportHeight = visibleItemCount × itemHeight
```

5. 若视觉设计希望固定高度，可由 CSS Token 限定，但仍保留 `visibleItemCount` 作为数据和渲染配置。
6. 数据不足 10 条时，展示实际条数，不强行补空行；是否循环由 `autoScroll` 和实现决定。

---

## 24.7 CsqNewsTickerItem

| 项 | 说明 |
|---|---|
| 组件名 | `CsqNewsTickerItem` |
| 中文名 | 新闻滚动条目 |
| 所属层级 | Data Display Components |
| 组件用途 | 展示单条新闻的时间与标题。 |
| 是否 Core Component | 是，可作为通用新闻/快讯列表 item。 |
| 是否市场总览 P0 必需 | 是，Review v9 点名。 |
| 输入字段 | `id`、`timestamp`、`title`、`type`。 |
| 时间格式 | `timestamp` 展示为 `MM-DD HH:mm:ss`，例如 `04-28 15:05:00`。若传入 ISO 时间，应由上层 adapter 或 formatter 转换为显示格式。 |
| 标题规则 | 标题单行展示，超出宽度显示 `...`。 |
| 点击规则 | P0 不可点击；不跳转详情；不跳转外链；不显示 pointer；hover 仅用于阅读状态。 |
| hover | hover 可轻微高亮行背景，但不能表现为强点击态。 |
| 状态 | default 正常；hover 弱背景；disabled 置灰；loading 由列表骨架处理；empty/error 由列表处理。 |
| 与 Design Token 映射 | `--cs-news-item-height`、`--cs-news-time-width`、`--cs-news-time-color`、`--cs-news-title-color`、`--cs-news-item-hover-bg`。 |
| 禁止误用 | 禁止把 `type='stock'` 自动渲染成可点击股票跳转；P0 下所有新闻 item 均不可点击。 |

```ts
interface CsqNewsTickerItem {
  id: string;
  timestamp: string; // display format: MM-DD HH:mm:ss
  title: string;
  type?: 'market' | 'stock';
}
```

### 24.7.1 Item 显示结构

```text
04-28 15:05:00  央行公开市场开展逆回购操作，市场流动性保持合理充裕...
```

建议布局：

```text
timestamp fixed width ｜ title flexible ellipsis
```

CSS 约束：

```css
white-space: nowrap;
overflow: hidden;
text-overflow: ellipsis;
cursor: default;
```

---

## 24.8 新闻滚动控制规则

### 24.8.1 默认滚动

1. `新闻速览` 和 `个股新闻` 默认同步向上滚动。
2. 最新新闻在上，旧新闻在下。
3. 默认展示 10 条，且 `visibleItemCount` 可配置。
4. 滚动循环播放。
5. 同一 `syncGroupId` 下使用统一滚动节奏。
6. 若两列数量不同，允许各自循环，但滚动速度和节奏保持一致。

### 24.8.2 hover 暂停

| hover 对象 | 暂停对象 | 继续滚动对象 |
|---|---|---|
| 新闻速览 | 新闻速览 | 个股新闻 |
| 个股新闻 | 个股新闻 | 新闻速览 |
| 非新闻区域 | 无 | 两者继续 |

规则：

1. hover 当前新闻板块，只暂停当前板块。
2. 当前板块变成可手动滚动区域。
3. 另一个板块继续自动滚动。
4. hover 离开后，当前板块恢复自动滚动。
5. 恢复时尽量回到同步节奏；若因实现复杂度无法精确同步，允许自然恢复，但需在 Showcase 说明。

### 24.8.3 手动滚动

hover 当前列表后：

```text
overflow-y: auto
```

要求：

1. 允许鼠标滚轮查看超出 `visibleItemCount` 的新闻。
2. 可显示细滚动条或使用隐式滚动条。
3. 手动滚动只作用于当前列表。
4. 鼠标离开后恢复自动滚动。

### 24.8.4 点击行为

P0 阶段新闻 item 不可点击。

明确禁止：

1. 不跳转新闻详情；
2. 不打开外链；
3. 不跳转公告页；
4. 不跳转股票详情；
5. 不使用 `cursor: pointer`；
6. 不显示强点击态；
7. hover 不触发跳转。

---

## 24.9 CsqSyncedTickerController：v9 修订说明

| 项 | 说明 |
|---|---|
| 组件 / 约定名 | `CsqSyncedTickerController` |
| 组件用途 | 描述同一 `syncGroupId` 下多个 `CsqNewsTickerList` 的同步滚动、独立暂停和恢复规则。 |
| 是否 UI 组件 | 否。它是逻辑组件或交互约定，可由 hook、controller、class 或父组件状态管理实现。 |
| 适用对象 | `新闻速览` 与 `个股新闻` 两个独立新闻板块。 |
| 同步规则 | 同组列表默认使用同一滚动周期、滚动方向、item 高度和 tick 节奏。 |
| 暂停规则 | hover 某个列表只暂停该列表，不暂停同组其它列表。 |
| 恢复规则 | hover 离开后该列表恢复自动滚动，并尽量对齐同组节奏。 |
| 禁止事项 | 禁止 hover 一个列表后暂停整个 syncGroup；禁止强制重置另一列滚动位置。 |

伪代码：

```ts
interface SyncedTickerState {
  syncGroupId: string;
  tickerIds: string[];
  pausedTickerIds: Set<string>;
  baseStartTime: number;
  durationMs: number;
}

function pauseTicker(tickerId: string) {
  state.pausedTickerIds.add(tickerId);
}

function resumeTicker(tickerId: string) {
  state.pausedTickerIds.delete(tickerId);
  // 恢复时尽量用 baseStartTime + elapsed 对齐同组节奏
}
```

---

## 24.10 MarketOverviewNewsPanelGroup

| 项 | 说明 |
|---|---|
| 组件名 | `MarketOverviewNewsPanelGroup` |
| 中文名 | 市场总览新闻板块组 |
| 所属层级 | Market Overview Business Component / 页面组合组件 |
| 组件用途 | 在首屏左右两栏上方组织 `新闻速览` 与 `个股新闻`，并使其分别与下方的今日市场客观总结、主要指数等宽。 |
| 是否 Core Component | 否。它是市场总览页面布局组合组件，不进入 Core Component。 |
| 是否市场总览 P0 必需 | 是，Review v9 推荐。 |
| 内部组件 | 左侧 `MarketOverviewNewsPanel(title='新闻速览')`，右侧 `MarketOverviewNewsPanel(title='个股新闻')`。 |
| 布局关系 | 2 列布局，与下方 `MarketSummaryIndexSplit` 的左右 50% / 50% 对齐。 |
| 输入字段 / Props | `marketNews`、`stockNews`、`visibleItemCount`、`syncGroupId`、`loading`、`error`。 |
| 交互 | 交互由内部 `CsqNewsTickerList` 控制。 |
| 禁止误用 | 不得放回 PageHeader 中间区域；不得包含 ICON 预留位；不得使用竖排标题。 |

```ts
interface MarketOverviewNewsPanelGroupProps {
  marketNews: CsqNewsTickerItem[];
  stockNews: CsqNewsTickerItem[];
  visibleItemCount?: number; // default: 10
  syncGroupId?: string;
  loading?: boolean;
  error?: ErrorStateProps | null;
}
```

### 24.10.1 推荐页面组合

```text
MarketOverviewFirstScreen
├── MarketOverviewNewsPanelGroup
│   ├── MarketOverviewNewsPanel(title="新闻速览")
│   └── MarketOverviewNewsPanel(title="个股新闻")
└── MarketSummaryIndexSplit
    ├── MarketSummary
    └── IndexGrid
```

其中：

- `MarketOverviewNewsPanelGroup` 的两列宽度必须与 `MarketSummaryIndexSplit` 的左右两列宽度对齐。
- 左上新闻板块正下方是今日市场客观总结。
- 右上新闻板块正下方是主要指数。

---

## 24.11 Mock 数据结构建议

> 本节结构用于 Showcase Mock 和组件设计，不作为正式 API 契约。正式 API 由 04 后续定义。

```ts
interface MarketOverviewNewsBlocks {
  marketNews: CsqNewsTickerItem[];
  stockNews: CsqNewsTickerItem[];
  visibleItemCount: number; // default: 10
}

interface CsqNewsTickerItem {
  id: string;
  timestamp: string; // MM-DD HH:mm:ss
  title: string;
  type?: 'market' | 'stock';
}
```

示例：

```ts
const newsBlocks: MarketOverviewNewsBlocks = {
  visibleItemCount: 10,
  marketNews: [
    {
      id: 'market-news-001',
      timestamp: '04-28 15:05:00',
      title: '央行公开市场开展逆回购操作，市场流动性保持合理充裕',
      type: 'market',
    },
  ],
  stockNews: [
    {
      id: 'stock-news-001',
      timestamp: '04-28 14:58:23',
      title: '中衡设计盘中触及涨停，低空经济概念持续活跃',
      type: 'stock',
    },
  ],
};
```

Mock 规则：

1. 每类新闻建议不少于 10 条。
2. 时间格式直接使用 `MM-DD HH:mm:ss`，便于 Showcase 展示。
3. 标题需要足够长，以验证省略号。
4. P0 `itemClickable=false`，Mock 不包含跳转 URL。
5. 不将 Mock 结构直接视为正式 API 契约。

---

## 24.12 对 02 `market-overview-v1.8.html` 的组件使用建议

1. 删除 Review v8 的顶部中间统一快讯条。
2. 删除 ICON 预留位。
3. 删除竖排标题。
4. 不在 PageHeader 中间区域放置新闻快讯。
5. 在今日市场客观总结正上方新增 `MarketOverviewNewsPanel(title='新闻速览')`。
6. 在主要指数正上方新增 `MarketOverviewNewsPanel(title='个股新闻')`。
7. 两个新闻板块与下方对应模块等宽。
8. 两个新闻板块高度一致。
9. 两个新闻板块默认展示 10 条新闻；10 是默认配置，不写死，保留 `visibleItemCount`。
10. 两个新闻板块默认同步向上滚动。
11. hover 新闻速览时，只暂停新闻速览，个股新闻继续滚动。
12. hover 个股新闻时，只暂停个股新闻，新闻速览继续滚动。
13. hover 后当前板块变成可手动滚动区域。
14. hover 离开后当前板块恢复自动滚动。
15. 新闻 item 不可点击，不显示 pointer，不跳转详情或外链。
16. 新闻标题单行展示，超出宽度显示 `...`。
17. 不修改 TopMarketBar、Breadcrumb、PageHeader、ShortcutBar 和正文其它模块。
18. 若新闻板块高度导致首屏视觉偏高，只允许在首屏上方组合内部微调垂直间距，不得改动后续模块顺序。

---

## 24.13 对 01 Design Token 的依赖

本轮依赖 `03-design-tokens.md` 中 Review v9 新闻板块 Token 或等价 Token，重点包括：

1. 新闻板块容器背景、边框、圆角、内边距；
2. 新闻板块标题字号、字重、颜色、横向标题样式；
3. 新闻列表高度与 `visibleItemCount` 对应关系；
4. 新闻 item 行高、内边距、hover 背景；
5. 时间字段宽度、字号、数字字体和颜色；
6. 新闻标题字号、颜色、单行省略；
7. 默认跑马灯动画周期；
8. hover 暂停状态；
9. 手动滚动状态和滚动条样式；
10. 两个新闻板块等高规则；
11. 新闻板块与下方模块间距。

建议 Token 方向：

```css
:root {
  --cs-news-panel-height: ...;
  --cs-news-panel-bg: ...;
  --cs-news-panel-border: ...;
  --cs-news-panel-radius: ...;
  --cs-news-panel-padding-x: ...;
  --cs-news-panel-padding-y: ...;
  --cs-news-panel-title-size: ...;
  --cs-news-list-visible-count-default: 10;
  --cs-news-item-height: ...;
  --cs-news-item-hover-bg: ...;
  --cs-news-time-width: ...;
  --cs-news-title-color: ...;
  --cs-news-scrollbar-thumb: ...;
}
```

---

## 24.14 对 04 API 的字段需求建议

> 本节只是 03 对后续 04 的字段需求建议，不正式修改 API 契约。

建议后续 04 仅新增或确认市场总览新闻相关字段，不修改其它市场总览 API 模块。

```ts
interface MarketOverviewNewsBlocksApiCandidate {
  visibleCount: number;
  marketNews: NewsPanelItem[];
  stockNews: NewsPanelItem[];
}

interface NewsPanelItem {
  id: string;
  publishTime: string;       // ISO datetime or backend standard datetime
  displayTime?: string;      // optional: MM-DD HH:mm:ss
  title: string;
  category: 'market' | 'stock';
  source?: string;
  stockCode?: string;
  stockName?: string;
  clickable: false;          // P0 fixed false
}
```

字段需求：

| 字段 | 必要性 | 说明 |
|---|---:|---|
| `visibleCount` | 建议 | 默认 10，可由前端配置兜底。 |
| `marketNews[]` | 必需 | 新闻速览数据。 |
| `stockNews[]` | 必需 | 个股新闻数据。 |
| `id` | 必需 | 稳定 key。 |
| `publishTime` | 必需 | 标准时间，用于排序和格式化。 |
| `displayTime` | 可选 | 若后端返回，可直接展示为 `MM-DD HH:mm:ss`。 |
| `title` | 必需 | 新闻标题。 |
| `category` | 必需 | `market` 或 `stock`。 |
| `source` | 可选 | 新闻来源，P0 不展示也可保留。 |
| `stockCode` / `stockName` | 可选 | 个股新闻关联股票，P0 不点击。 |
| `clickable` | 建议 | P0 固定 false，避免前端误做点击态。 |

---

## 24.15 本轮 Review v9 修改摘要

1. 废弃 Review v8 的顶部中间统一快讯条方案。
2. 废弃 `ICON 预留位｜新闻速览｜个股新闻` 横向结构。
3. 废弃 ICON 预留位和竖排标题。
4. 新增两个独立新闻板块：`新闻速览` 和 `个股新闻`。
5. `新闻速览` 位于今日市场客观总结正上方，并与其等宽。
6. `个股新闻` 位于主要指数正上方，并与其等宽。
7. 两个新闻板块高度一致。
8. 新增 / 修订 `MarketOverviewNewsPanel`、`MarketOverviewNewsPanelGroup`、`CsqNewsTickerList`、`CsqNewsTickerItem`、`CsqSyncedTickerController`。
9. `visibleItemCount` 默认 10，并可配置。
10. 两个新闻板块默认同步向上滚动。
11. hover 当前新闻板块只暂停当前板块，另一板块继续自动滚动。
12. hover 后当前板块可手动滚动。
13. P0 新闻 item 不可点击。
14. 本轮不修改 Review v9 未点名组件。

---

## 24.16 本轮新增或修订组件清单

| 类型 | 组件 / 方案 | 处理方式 |
|---|---|---|
| 新增 | `MarketOverviewNewsPanel` | 新增市场总览独立新闻面板业务组件，用于“新闻速览”和“个股新闻”。 |
| 新增 | `MarketOverviewNewsPanelGroup` | 新增市场总览新闻板块组，用于组织左右两个新闻板块并与下方两栏对齐。 |
| 新增/修订 | `CsqNewsTickerList` | 新增通用新闻滚动列表，承载同步滚动、hover 暂停、手动滚动能力。 |
| 修订 | `CsqNewsTickerItem` | 沿用新闻 item 概念，明确 P0 不可点击、时间格式、标题省略。 |
| 修订 | `CsqSyncedTickerController` | 从顶部快讯条逻辑调整为两个独立新闻面板的同步滚动控制。 |

---

## 24.17 本轮废弃组件 / 方案说明

| 废弃项 | 废弃原因 | 后续处理 |
|---|---|---|
| `MarketOverviewNewsFlashPanel` | Review v9 废弃顶部中间统一快讯条 | 保留历史记录，不用于 `market-overview-v1.8.html`。 |
| `CsqNewsTickerIconSlot` | 新版不再需要 ICON 预留位 | 不用于市场总览 P0 新闻板块。 |
| 顶部中间统一横向快讯条 | 效果不符合新布局要求 | 删除，不在 PageHeader 中间区域放置新闻。 |
| 竖排标题 | 新版两个独立新闻板块使用横向标题 | 不用于 Review v9 新闻板块。 |
| `ICON 预留位｜新闻速览｜个股新闻` 结构 | 已被“新闻速览 / 个股新闻独立面板”替代 | 不作为 v1.8 实现依据。 |

---

## 24.18 本轮未修改组件清单

以下组件保持 Review v8 merged-full 规范，不做主动改动：

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
- `MarketSummaryIndexSplit` 内部内容
- `MarketSummaryFactCard`
- `MarketSummaryNoteCard`
- `IndexGrid` 内部内容
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
- `MarketOverviewLimitLadder`
- `CsqStockCompactCard`
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

本轮因 Review v9 修改而被动影响的区域：

```text
本轮因 Review v9 修改而被动影响的区域：
- 今日市场客观总结与主要指数所在首屏区域的局部垂直排布
原因：新闻速览需要位于今日市场客观总结正上方，个股新闻需要位于主要指数正上方，并与下方模块等宽。
是否需要产品总控确认：否，Review v9 已明确该位置；但 02 Showcase 需要验证两个新闻板块高度与首屏整体密度。
```

---

## 24.19 待产品总控确认问题

1. `visibleItemCount=10` 在真实首屏中是否过高？如果 10 条导致首屏偏高，是否允许 02 在 Showcase 中通过更紧凑行高保持 10 条而不是减少数量？
2. 新闻板块高度是否严格由 `10 × itemHeight` 决定，还是允许固定高度 + 内部滚动？当前建议由 `visibleItemCount` 和 Token 控制高度。
3. `新闻速览` 与 `个股新闻` 是否必须完全等高？当前按 Review v9 要求：必须等高。
4. hover 离开后是否必须精确恢复同步节奏？当前建议尽量恢复，不做像素级强制。
5. 新闻 item 是否未来会点击？P0 明确不可点击；后续若开放点击，需要重新设计 hover/click 状态和 API URL 字段。
6. 个股新闻中是否需要展示股票代码或股票简称标签？当前 P0 只展示时间 + 标题，不额外展示股票字段。
7. 04 API v0.6 是否需要本轮同步推进？总控变更单建议 04 轻量参与，但本 03 文档只提出字段需求，不正式修改 API。
8. 是否保留 Review v8 组件名作为 Deprecated 历史段落？当前保留历史记录，但明确不用于 v1.8。

---

## 24.20 Review v9 验收清单

| 验收项 | 要求 |
|---|---|
| 完整文档 | 本文件仍是完整 `04-component-guidelines.md`，不是 delta 文档。 |
| 修改边界 | 只新增/修订 Review v9 点名的新闻速览、个股新闻、滚动控制组件。 |
| 旧方案废弃 | 明确废弃顶部中间统一快讯条、ICON 预留位和竖排标题。 |
| 新闻速览位置 | 新闻速览位于今日市场客观总结正上方，并与其等宽。 |
| 个股新闻位置 | 个股新闻位于主要指数正上方，并与其等宽。 |
| 等高 | 两个新闻板块高度一致。 |
| visibleItemCount | 默认 10，且可配置，不能写死。 |
| 同步滚动 | 两个新闻板块默认同步向上滚动。 |
| hover 暂停 | hover 当前板块只暂停当前板块，另一板块继续滚动。 |
| 手动滚动 | hover 后当前板块可手动滚动。 |
| 新闻 item | P0 不可点击，不跳详情、不跳外链、不显示 pointer。 |
| Mock | Mock 结构只用于 Showcase，不作为正式 API 契约。 |
| API | 只提出字段需求建议，不正式修改 API。 |
| 未授权改动 | 未修改 TopMarketBar、Breadcrumb、PageHeader、ShortcutBar、正文其它模块或 Review v9 未点名组件。 |

---

## 24.21 建议放置到 Google Drive 的路径

```text
财势乾坤/设计/04-component-guidelines.md
```

## 24.22 建议仓库保存路径

```text
/docs/wealth/04-component-guidelines.md
```

## 24.23 本轮输出文件下载链接

对话交付文件：

```text
sandbox:/mnt/data/review-v9-output-final/04-component-guidelines.md
```


---

# 25. 个股详情页组件与交互组件方案 v0.1（基于《个股详情页产品需求文档 v0.2》）

> 本节为 `个股详情页产品需求文档_v_0_2.md` 的组件库修订内容。它不替代前文已确认的市场总览、通用组件库注册表和 Review v1～v9 内容，而是在完整保留此前 `04-component-guidelines.md` 的基础上，补充个股详情页 P0 所需的固定视口布局组件、K 线图表面板组件、十字线 / Tooltip / 坐标轴浮标组件、右侧信息栏组件。  
> 本节重点不是设计完整图表引擎，而是为 02 `stock-detail-v1.html` Showcase 与后续 Codex 工程实现提供可落地的组件契约与布局约束。

## 25.1 本轮读取文档与采用基线

| 序号 | 公共区文件 | 读取到的版本 / 状态 | 本轮用途 |
|---:|---|---|---|
| 1 | `财势乾坤/项目总说明/财势乾坤行情软件项目总说明_v_0_2.md` | `财势乾坤项目总说明 v0.2` / Review 草案 v0.2 | 继续约束产品定位、A 股优先、红涨绿跌、深色默认、专业金融终端风格。 |
| 2 | `财势乾坤/产品文档/个股详情页产品需求文档_v_0_2.md` | `个股详情页产品需求文档 v0.2` | 本轮直接上游，约束固定视口、K 线图表区、右侧信息栏、十字线、Tooltip、坐标轴浮标、低高度策略。 |
| 3 | `财势乾坤/设计/03-design-tokens.md` | `Design Token 与视觉规范 v0.3.7` | 采用个股详情页固定视口交易终端布局、图表、Tooltip、右侧信息栏相关 Token。 |
| 4 | `财势乾坤/设计/04-component-guidelines.md` | 当前完整合并基线 | 作为本节合并基线，完整保留此前内容，并追加个股详情页组件规范。 |

本轮未能读取但应读取的文档：无。  
本轮是否继续：是。

---

## 25.2 个股详情页组件设计边界

### 25.2.1 页面定位

个股详情页属于 **乾坤行情**，不是独立一级菜单。页面是 A 股个股事实行情终端页，用于查看：

1. 个股基础行情；
2. 分时、分钟线、日 K、周 K、月 K 等周期走势；
3. MA / BOLL 主图叠加指标；
4. MACD、成交量、KDJ 副图；
5. 十字坐标线、OHLC、成交量、成交额、换手率、指标值；
6. 关联板块；
7. 个股资金统计；
8. 自选、提醒、交易计划入口。

个股详情页不输出：

```text
买卖建议
诊股结论
真实交易下单
仓位建议
明日预测
主观交易动作
```

### 25.2.2 本轮组件范围

本节定义或修订：

1. `StockDetailPage`
2. `BreadcrumbActionBar`
3. `StockChartToolbar`
4. `StockDetailFixedLayout`
5. `ChartPanelHeaderInfo`
6. `MainOverlayIndicatorMenu`
7. `ChartCrosshairLayer`
8. `ChartAxisFloatLabel`
9. `KlineTooltip`
10. `IndicatorToolbar`
11. `StockHeaderPanel`
12. `StockSideTabs`
13. `RelatedSectorTable`
14. `StockMoneyFlowPanel`

### 25.2.3 本节不做的事情

1. 不设计完整图表引擎内部算法；
2. 不正式定义 API 契约；
3. 不设计真实交易下单；
4. 不启用 body 级整页滚动；
5. 不写死 `height: 1080px`；
6. 不替代市场总览组件规范；
7. 不修改 Review v1～v9 已确认的市场总览组件；
8. 不新增诊股结论组件。

---

## 25.3 固定视口布局总规则

### 25.3.1 100vh 的定义

`100vh` 表示 **浏览器当前内容可视区域高度的 100%**。

它不是：

```text
固定 1080px
显示器物理高度
设计稿固定高度
```

示例：

```text
浏览器内容可视高度 1080px → 100vh = 1080px
浏览器内容可视高度 900px  → 100vh = 900px
浏览器内容可视高度 760px  → 100vh = 760px
```

浏览器地址栏、书签栏、系统 Dock、窗口边框都会影响真实 `100vh`。

### 25.3.2 设计基准与实现基准

| 项 | 规则 |
|---|---|
| 推荐设计基准 | `1920 × 1080` |
| 最低可用尺寸 | `1440 × 900` |
| 代码实现高度 | `100vh` / 可兼容 `100dvh` |
| 禁止写死 | `height: 1080px` |
| 低高度策略 | 可视高度低于 `900px` 时压缩图表区、字号、间距或显示低高度提示 |
| 滚动策略 | 禁止 body 级整页滚动；只允许模块内部局部滚动 |

### 25.3.3 页面高度构成

```text
页面总高度 = 100vh

100vh =
TopMarketBar
+ BreadcrumbActionBar
+ StockChartToolbar
+ MainContent
```

主内容区高度：

```text
MainContent =
100vh
- TopMarketBar 高度
- BreadcrumbActionBar 高度
- StockChartToolbar 高度
```

代码表达：

```css
.stock-detail-page {
  --sd-top-market-bar-h: var(--cs-layout-top-market-bar-height, 44px);
  --sd-breadcrumb-action-bar-h: var(--cs-stock-detail-breadcrumb-action-bar-height, 34px);
  --sd-chart-toolbar-h: var(--cs-stock-detail-chart-toolbar-height, 36px);

  height: 100vh;
  height: 100dvh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.stock-detail-main {
  height: calc(
    100vh
    - var(--sd-top-market-bar-h)
    - var(--sd-breadcrumb-action-bar-h)
    - var(--sd-chart-toolbar-h)
  );
  min-height: 0;
  overflow: hidden;
}
```

如果工程使用 flex：

```css
.stock-detail-main {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
```

`min-height: 0` 是硬性要求，用于避免图表区或右侧信息栏把父容器撑爆，导致整页滚动。

### 25.3.4 禁止整页滚动

禁止把个股详情页主方案做成：

```css
body {
  overflow-y: auto;
}
```

应保证：

```css
html,
body,
#app {
  height: 100%;
}

.stock-detail-page {
  height: 100vh;
  overflow: hidden;
}
```

当局部内容超出时，只允许：

1. 图表面板内部压缩；
2. 右侧 `StockSideTabs` 内容区内部滚动；
3. 表格内部滚动；
4. 指标栏横向滚动；
5. 显示局部“更多”；
6. 低高度提示。

---

## 25.4 个股详情页整体组件树

```text
StockDetailPage
├── TopMarketBar
├── BreadcrumbActionBar
├── StockChartToolbar
└── StockDetailFixedLayout
    ├── ChartWorkspace
    │   ├── KlineMainPanel
    │   │   ├── ChartPanelHeaderInfo
    │   │   ├── MainOverlayIndicatorMenu
    │   │   ├── ChartCanvasLayer
    │   │   ├── ChartCrosshairLayer
    │   │   ├── ChartAxisFloatLabel
    │   │   └── KlineTooltip
    │   ├── MacdPanel
    │   │   ├── ChartPanelHeaderInfo
    │   │   ├── ChartCrosshairLayer
    │   │   └── ChartAxisFloatLabel
    │   ├── VolumePanel
    │   │   ├── ChartPanelHeaderInfo
    │   │   ├── ChartCrosshairLayer
    │   │   └── ChartAxisFloatLabel
    │   ├── KdjPanel
    │   │   ├── ChartPanelHeaderInfo
    │   │   ├── ChartCrosshairLayer
    │   │   └── ChartAxisFloatLabel
    │   └── IndicatorToolbar
    └── StockInfoSidebar
        ├── StockHeaderPanel
        ├── StockSideTabs
        │   ├── 盘口
        │   │   ├── RelatedSectorTable
        │   │   └── StockMoneyFlowPanel
        │   └── 资料
        │       └── StockProfilePlaceholder
```

说明：

1. `TopMarketBar` 继续复用全局顶部栏，不在本节重写。
2. `BreadcrumbActionBar` 替代独立 Compact PageHeader。
3. `StockChartToolbar` 承载周期切换和资料/诊股入口。
4. `StockDetailFixedLayout` 承载左图表区 + 右信息栏。
5. 左侧图表区和右侧信息栏都不能撑出整页滚动。
6. 右侧信息栏内部 Tab 内容可局部滚动。

---

## 25.5 StockDetailPage

| 项 | 说明 |
|---|---|
| 组件名称 | `StockDetailPage` |
| 中文名 | 个股详情页根容器 |
| 组件用途 | 个股详情页根容器，负责固定视口、高度计算、主结构组织、全页状态与防止 body 级滚动。 |
| 使用页面 | 个股详情页 P0 必需。 |
| 是否 P0 必需 | 是。 |
| 输入字段 / Props | `stockCode`、`period`、`adjustType`、`initialData`、`loading`、`error`、`onRefresh`、`onPeriodChange`、`onAdjustTypeChange`。 |
| 状态 | default、loading、empty、error、dataDelayed、lowHeight。 |
| 交互 | 加载默认数据；响应周期、复权、刷新；把图表交互状态下发给图表区。 |
| Design Token 映射 | `--cs-stock-detail-*`、`--cs-layout-top-market-bar-height`、`--cs-color-bg-page`、`--cs-color-surface-panel`。 |
| 禁止误用 | 禁止 `height:1080px`；禁止 body 级整页滚动；禁止用普通后台详情页布局替代行情终端布局。 |

```ts
interface StockDetailPageProps {
  stockCode: string;
  period?: KlinePeriod;
  adjustType?: 'none' | 'qfq' | 'hfq';
  initialData?: StockDetailViewModel;
  loading?: boolean;
  error?: ErrorStateProps | null;
  onRefresh?: () => void;
  onPeriodChange?: (period: KlinePeriod) => void;
  onAdjustTypeChange?: (adjustType: 'none' | 'qfq' | 'hfq') => void;
}

type KlinePeriod =
  | 'time'
  | '1m'
  | '5m'
  | '15m'
  | '30m'
  | '60m'
  | '90m'
  | '120m'
  | 'day'
  | 'week'
  | 'month';
```

### 25.5.1 CSS 约束

```css
.stock-detail-page {
  height: 100vh;
  height: 100dvh;
  min-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  background: var(--cs-color-bg-page);
}

.stock-detail-page__main {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
```

### 25.5.2 低高度策略

当可视高度 `< 900px`：

1. 图表面板 header 高度压缩；
2. 指标区间距压缩；
3. 右侧信息栏卡片 padding 压缩；
4. 底部 `IndicatorToolbar` 可横向滚动；
5. 仍禁止 body 整页滚动；
6. 若高度低于可操作阈值，显示顶部弱提示：`当前窗口高度较低，建议使用更大窗口查看行情终端视图`。

---

## 25.6 BreadcrumbActionBar

| 项 | 说明 |
|---|---|
| 组件名称 | `BreadcrumbActionBar` |
| 中文名 | 面包屑操作栏 |
| 组件用途 | 替代独立 Compact PageHeader，在固定高度内承载页面层级、股票上下文、复权选择、更新时间、刷新和数据状态。 |
| 使用页面 | 个股详情页 P0 必需。 |
| 是否 P0 必需 | 是。 |
| 输入字段 / Props | `breadcrumbItems`、`stockName`、`stockCode`、`adjustType`、`updateTime`、`dataStatus`、`onAdjustTypeChange`、`onRefresh`、`onBreadcrumbClick`。 |
| 状态 | default、hover、active、selected、disabled、loading、error、dataDelayed。 |
| 交互 | 点击面包屑上级返回；复权下拉；刷新；数据状态 Tooltip。 |
| Design Token 映射 | `--cs-stock-detail-breadcrumb-action-bar-height`、`--cs-color-bg-breadcrumb`、`--cs-color-border-subtle`、`--cs-color-text-secondary`。 |
| 禁止误用 | 不做大型 PageHeader，不插入营销文案，不撑高页面。 |

```ts
interface BreadcrumbActionBarProps {
  breadcrumbItems: Array<{
    key: string;
    label: string;
    route?: string;
    current?: boolean;
  }>;
  stockName: string;
  stockCode: string;
  adjustType: 'none' | 'qfq' | 'hfq';
  updateTime: string;
  dataStatus: 'READY' | 'DELAYED' | 'PARTIAL' | 'ERROR';
  onAdjustTypeChange?: (adjustType: 'none' | 'qfq' | 'hfq') => void;
  onRefresh?: () => void;
  onBreadcrumbClick?: (key: string) => void;
}
```

固定表达示例：

```text
财势乾坤 / 乾坤行情 / 个股详情 / 福斯特 603806
```

右侧：

```text
前复权▼ ｜ 更新时间 14:59:56 ｜ 刷新 ｜ 数据正常
```

---

## 25.7 StockChartToolbar

| 项 | 说明 |
|---|---|
| 组件名称 | `StockChartToolbar` |
| 中文名 | 个股图表周期工具栏 |
| 组件用途 | 承载分时、K 线周期、资料、诊股等入口，是图表区上方固定工具条。 |
| 使用页面 | 个股详情页 P0 必需。 |
| 是否 P0 必需 | 是。 |
| 输入字段 / Props | `periods`、`activePeriod`、`extraActions`、`disabledActions`、`onPeriodChange`、`onActionClick`。 |
| 状态 | default、hover、active、selected、disabled、loading。 |
| 交互 | 点击周期切换图表数据；点击股票资料进入资料页；诊股 disabled；未支持入口 Toast。 |
| Design Token 映射 | `--cs-stock-detail-chart-toolbar-height`、`--cs-component-range-switch-*`、`--cs-color-brand-accent`。 |
| 禁止误用 | 禁止加入“多周期、同花顺F10、显示、画线”；P0 诊股必须 disabled。 |

```ts
interface StockChartToolbarProps {
  periods: Array<{
    key: KlinePeriod;
    label: string;
    enabled: boolean;
  }>;
  activePeriod: KlinePeriod;
  extraActions?: Array<{
    key: 'stockProfile' | 'diagnosis';
    label: string;
    enabled: boolean;
    route?: string;
    disabledReason?: string;
  }>;
  onPeriodChange?: (period: KlinePeriod) => void;
  onActionClick?: (key: string) => void;
}
```

P0 展示：

```text
分时｜日K｜周K｜月K｜120分｜90分｜60分｜30分｜15分｜5分｜1分｜股票资料｜诊股
```

默认周期：`日K`。

点击未支持或 disabled 项：

```text
Toast：该指标暂未支持
```

或：

```text
Toast：诊股暂未开通
```

---

## 25.8 StockDetailFixedLayout

| 项 | 说明 |
|---|---|
| 组件名称 | `StockDetailFixedLayout` |
| 中文名 | 个股详情固定视口布局 |
| 组件用途 | 组织左侧图表工作区与右侧信息栏，确保主内容区域高度由视口计算，不发生整页滚动。 |
| 使用页面 | 个股详情页 P0 必需。 |
| 是否 P0 必需 | 是。 |
| 输入字段 / Props | `left`、`right`、`rightWidth`、`leftRatio`、`rightRatio`、`minHeightPolicy`、`lowHeightMode`。 |
| 状态 | default、lowHeight、sidebarCollapsed、loading。 |
| 交互 | 可选支持右侧折叠，但 P0 默认固定右栏；低高度时启用压缩策略。 |
| Design Token 映射 | `--cs-stock-detail-main-gap`、`--cs-stock-detail-sidebar-width`、`--cs-stock-detail-chart-area-ratio`。 |
| 禁止误用 | 禁止用页面滚动解决右侧信息栏或图表高度问题。 |

```ts
interface StockDetailFixedLayoutProps {
  left: React.ReactNode;
  right: React.ReactNode;
  rightWidth?: number | string; // 建议 360px～400px
  leftRatio?: number;           // 默认 0.76
  rightRatio?: number;          // 默认 0.24
  lowHeightMode?: boolean;
}
```

CSS 建议：

```css
.stock-detail-fixed-layout {
  height: 100%;
  min-height: 0;
  overflow: hidden;
  display: grid;
  grid-template-columns: minmax(0, 1fr) var(--cs-stock-detail-sidebar-width, 380px);
  gap: var(--cs-stock-detail-main-gap, 8px);
}

.stock-detail-chart-workspace,
.stock-detail-info-sidebar {
  min-height: 0;
  overflow: hidden;
}
```

左侧图表区建议：

```text
K线主图：42%～46%
MACD：16%～18%
成交量：16%～18%
KDJ：16%～18%
底部指标栏：30～36px 固定
```

---

## 25.9 ChartPanelHeaderInfo

| 项 | 说明 |
|---|---|
| 组件名称 | `ChartPanelHeaderInfo` |
| 中文名 | 图表面板头部信息栏 |
| 组件用途 | 每个图表 panel 顶部信息栏，展示当前横轴时间点对应的指标信息；鼠标移动时刷新，离开后恢复最新一根数据。 |
| 使用页面 | K 线主图、MACD、成交量、KDJ。 |
| 是否 P0 必需 | 是。 |
| 输入字段 / Props | `panelType`、`activeTime`、`latestTime`、`items`、`indicatorMode`、`indicatorOptions`、`onIndicatorModeChange`、`onSettingsClick`。 |
| 状态 | default、hover、active、selected、loading、empty。 |
| 交互 | 主图支持 MA / BOLL 下拉切换；齿轮点击 Toast；Header Info 跟随 crosshair 横轴刷新。 |
| Design Token 映射 | `--cs-chart-panel-header-height`、`--cs-chart-panel-header-bg`、`--cs-color-text-secondary`、`--cs-font-family-number`。 |
| 禁止误用 | 不把 Header Info 做成可拖拽工具栏；不显示主观分析结论。 |

```ts
interface ChartPanelHeaderInfoProps {
  panelType: 'kline' | 'macd' | 'volume' | 'kdj';
  activeTime?: string | null;
  latestTime: string;
  indicatorMode?: 'MA' | 'BOLL' | 'MACD' | 'VOL' | 'KDJ';
  indicatorOptions?: Array<{ key: string; label: string; enabled: boolean }>;
  items: Array<{
    key: string;
    label: string;
    value: number | string | null;
    valueText?: string;
    direction?: 'rise' | 'fall' | 'flat' | 'neutral';
    colorToken?: string;
  }>;
  onIndicatorModeChange?: (mode: string) => void;
  onSettingsClick?: () => void;
}
```

K 线主图 Header Info 示例：

```text
▼ MA  MA5:19.01  MA15:18.28  MA30:18.10  MA60:18.18  MA120:16.46  MA250:15.18  [齿轮]
```

交互规则：

1. 鼠标位于图表区：显示当前横轴时间点数据；
2. 鼠标离开图表区：恢复最新一根 K 线数据；
3. 主图指标可在 `MA / BOLL` 间切换；
4. 齿轮点击后 Toast：`指标设置暂未开通`；
5. 非主图 Header Info 只展示该面板指标，不承担指标设置。

---

## 25.10 MainOverlayIndicatorMenu

| 项 | 说明 |
|---|---|
| 组件名称 | `MainOverlayIndicatorMenu` |
| 中文名 | 主图叠加指标菜单 |
| 组件用途 | 控制 K 线主图上的 MA / BOLL 叠加指标。 |
| 使用页面 | 个股详情页 K 线主图 P0 必需。 |
| 是否 P0 必需 | 是。 |
| 输入字段 / Props | `activeIndicator`、`options`、`onChange`、`onSettingsClick`。 |
| 状态 | default、hover、active、selected、disabled。 |
| 交互 | 点击切换 MA / BOLL；齿轮点击 Toast；与底部 `IndicatorToolbar` 的 BOLL 入口同步。 |
| Design Token 映射 | `--cs-component-range-switch-*`、`--cs-color-brand-accent`。 |
| 禁止误用 | 不在 P0 弹出完整指标参数设置。 |

```ts
interface MainOverlayIndicatorMenuProps {
  activeIndicator: 'MA' | 'BOLL';
  options: Array<{ key: 'MA' | 'BOLL'; label: string; enabled: boolean }>;
  onChange?: (indicator: 'MA' | 'BOLL') => void;
  onSettingsClick?: () => void;
}
```

同步规则：

1. Header Info 中选择 BOLL 后，底部 `IndicatorToolbar` 的 BOLL 进入 selected。
2. 底部 `IndicatorToolbar` 点击 BOLL 后，主图叠加指标同步切换为 BOLL。
3. MA 与 BOLL 是主图叠加指标，不是副图 panel。

---

## 25.11 ChartCrosshairLayer

| 项 | 说明 |
|---|---|
| 组件名称 | `ChartCrosshairLayer` |
| 中文名 | 图表十字坐标线层 |
| 组件用途 | 在 K 线主图、MACD、成交量、KDJ 多 panel 中显示同一横轴时间点的联动十字线。 |
| 使用页面 | 个股详情页 P0 必需。 |
| 是否 P0 必需 | 是。 |
| 输入字段 / Props | `active`、`x`、`yByPanel`、`panels`、`visiblePanels`、`mode`、`onToggle`、`onMove`。 |
| 状态 | hidden、hoverPreview、activeLocked。 |
| 交互 | 鼠标进入 panel 显示浮标；单击激活十字线和 Tooltip；再次单击关闭；移动时同步刷新所有 panel。 |
| Design Token 映射 | `--cs-chart-crosshair-color`、`--cs-chart-crosshair-width`、`--cs-chart-crosshair-dash`。 |
| 禁止误用 | 非激活态不显示完整十字线和 KlineTooltip；不让各 panel 横轴错位。 |

```ts
interface ChartCrosshairLayerProps {
  active: boolean;
  x: number | null;
  yByPanel: Record<string, number | null>;
  panels: Array<{
    panelId: 'kline' | 'macd' | 'volume' | 'kdj';
    top: number;
    height: number;
  }>;
  mode?: 'hover-preview' | 'click-lock';
  onToggle?: (active: boolean) => void;
  onMove?: (payload: ChartPointerPayload) => void;
}

interface ChartPointerPayload {
  x: number;
  y: number;
  time: string;
  panelId: 'kline' | 'macd' | 'volume' | 'kdj';
  dataIndex: number;
}
```

### 25.11.1 非激活态规则

非激活态：

1. 不显示完整十字线；
2. 不显示 `KlineTooltip`；
3. 鼠标进入任意 panel 时显示该 panel 的 Y 轴浮标；
4. 底部时间轴显示当前横轴时间浮标；
5. Header Info 跟随鼠标刷新；
6. 鼠标离开图表区后浮标隐藏，Header Info 恢复最新数据。

### 25.11.2 激活态规则

激活态：

1. 单击图表区后十字线和 Tooltip 出现；
2. K 线主图、MACD、成交量、KDJ 在同一横轴时间点对齐；
3. 鼠标移动时十字线和 Tooltip 同步刷新；
4. 再次单击后十字线和 Tooltip 消失；
5. 激活态不阻止 Header Info 更新。

---

## 25.12 ChartAxisFloatLabel

| 项 | 说明 |
|---|---|
| 组件名称 | `ChartAxisFloatLabel` |
| 中文名 | 坐标轴浮标 |
| 组件用途 | 在 Y 轴和底部时间轴上显示当前鼠标位置或十字线位置对应的浮动标签。 |
| 使用页面 | 个股详情页图表区 P0 必需。 |
| 是否 P0 必需 | 是。 |
| 输入字段 / Props | `axis`、`value`、`valueText`、`position`、`visible`、`panelId`、`direction`。 |
| 状态 | hidden、hover、locked。 |
| 交互 | 跟随鼠标或十字线移动；离开图表隐藏；激活态保持显示。 |
| Design Token 映射 | `--cs-chart-axis-float-label-bg`、`--cs-chart-axis-float-label-text`、`--cs-chart-axis-float-label-border`。 |
| 禁止误用 | 不在非图表区域显示；不遮挡右侧信息栏。 |

```ts
interface ChartAxisFloatLabelProps {
  axis: 'x' | 'y';
  value: number | string | null;
  valueText?: string;
  position: { x: number; y: number };
  visible: boolean;
  panelId?: 'kline' | 'macd' | 'volume' | 'kdj';
  direction?: 'rise' | 'fall' | 'flat' | 'neutral';
}
```

显示规则：

1. Y 轴浮标显示当前 panel 的价格 / 指标值；
2. X 轴浮标显示当前横轴时间；
3. K 线主图价格浮标可按涨跌方向弱着色；
4. MACD / 成交量 / KDJ 浮标一般使用中性或指标色；
5. 时间浮标使用中性背景和等宽字体。

---

## 25.13 KlineTooltip

| 项 | 说明 |
|---|---|
| 组件名称 | `KlineTooltip` |
| 中文名 | K 线详情 Tooltip |
| 组件用途 | 在十字线激活态显示当前 K 线 OHLC、涨幅、振幅、成交量、成交额、换手率等数据。 |
| 使用页面 | 个股详情页 K 线主图 P0 必需。 |
| 是否 P0 必需 | 是。 |
| 输入字段 / Props | `visible`、`positionMode`、`data`、`compareBase`、`formatter`。 |
| 状态 | hidden、visible、loading、empty。 |
| 交互 | 激活态随鼠标横轴移动刷新；根据鼠标位于屏幕左/右半区自动固定在右上/左上。 |
| Design Token 映射 | `--cs-chart-tooltip-*`、`--cs-kline-tooltip-*`、`--cs-color-market-up/down/flat`。 |
| 禁止误用 | 非激活态不显示；不输出交易建议；不随鼠标遮挡 K 线中心区域。 |

```ts
interface KlineTooltipProps {
  visible: boolean;
  positionMode: 'left-top' | 'right-top';
  data: {
    time: string;
    open: number | null;
    close: number | null;
    high: number | null;
    low: number | null;
    prevClose: number | null;
    changePct: number | null;
    amplitude: number | null;
    volume: number | null;
    amount: number | null;
    turnoverRate: number | null;
  } | null;
  formatter?: {
    price?: (value: number | null) => string;
    percent?: (value: number | null) => string;
    volume?: (value: number | null) => string;
    amount?: (value: number | null) => string;
  };
}
```

### 25.13.1 Tooltip 位置规则

```text
鼠标在屏幕左半边：Tooltip 固定显示在 K线主图区右上角
鼠标在屏幕右半边：Tooltip 固定显示在 K线主图区左上角
```

说明：

1. Tooltip 不跟随鼠标自由漂浮；
2. Tooltip 不遮挡鼠标附近 K 线；
3. Tooltip 只在主图区域固定显示；
4. 副图数据通过 Header Info 或后续扩展字段展示。

### 25.13.2 Tooltip 字段

P0 字段顺序：

```text
时间
开盘
收盘
最高
最低
涨幅
振幅
成交量
成交额
换手率
```

### 25.13.3 Tooltip 颜色方案 A

1. 开盘价 / 收盘价与上一根 K 线收盘价比较：
   - 高于：红色；
   - 低于：绿色；
   - 相等：灰白。
2. 最高价与开盘价比较：
   - 高于：红色；
   - 相等：灰白。
3. 最低价与开盘价比较：
   - 低于：绿色；
   - 相等：灰白。
4. 涨幅：
   - 大于 0：红色；
   - 小于 0：绿色；
   - 等于 0：灰白。
5. 振幅、成交量、成交额、换手率：
   - 中性色。

---

## 25.14 IndicatorToolbar

| 项 | 说明 |
|---|---|
| 组件名称 | `IndicatorToolbar` |
| 中文名 | 底部指标栏 |
| 组件用途 | 位于左侧图表区底部，展示 P0 和后续指标入口，控制副图和主图叠加指标。 |
| 使用页面 | 个股详情页 P0 必需。 |
| 是否 P0 必需 | 是。 |
| 输入字段 / Props | `items`、`activeKeys`、`supportedKeys`、`onItemClick`。 |
| 状态 | default、hover、active、selected、disabled。 |
| 交互 | 支持指标点击；未支持指标 Toast；BOLL 与主图叠加指标同步。 |
| Design Token 映射 | `--cs-indicator-toolbar-*`、`--cs-color-brand-accent`。 |
| 禁止误用 | 不把所有指标都真正渲染为副图；P0 实际支持 MACD、成交量、KDJ、MA、BOLL。 |

```ts
interface IndicatorToolbarProps {
  items: Array<{
    key: string;
    label: string;
    type: 'overlay' | 'subPanel' | 'future';
    supported: boolean;
  }>;
  activeKeys: string[];
  onItemClick?: (key: string) => void;
}
```

P0 展示：

```text
VOL｜成交额｜均线｜大单净量｜MACD｜KDJ｜主力密码｜融资融券｜陆股通资金｜陆股通持股｜AI机构活跃度｜资金抄底｜资金仓位｜BOLL｜更多
```

P0 实际支持：

```text
MACD / 成交量 / KDJ / 均线(MA) / BOLL
```

点击未支持指标：

```text
Toast：该指标暂未支持
```

---

## 25.15 StockHeaderPanel

| 项 | 说明 |
|---|---|
| 组件名称 | `StockHeaderPanel` |
| 中文名 | 个股右侧头部行情面板 |
| 组件用途 | 右侧信息栏顶部展示股票名称、代码、最新价、涨跌额、涨跌幅、所属行业 / 板块标签、自选、提醒、交易计划入口。 |
| 使用页面 | 个股详情页 P0 必需。 |
| 是否 P0 必需 | 是。 |
| 输入字段 / Props | `stockName`、`stockCode`、`latestPrice`、`changeAmount`、`changePct`、`direction`、`industryName`、`sectorTags`、`tradeStatus`、`actions`。 |
| 状态 | default、loading、empty、error、dataDelayed。 |
| 交互 | 加入自选、设置提醒、创建交易计划入口；未实现功能 Toast 或进入预留页。 |
| Design Token 映射 | `--cs-stock-header-*`、`--cs-color-market-up/down/flat`、`--cs-font-family-number`。 |
| 禁止误用 | 不显示诊股结论；不显示买卖建议；不显示真实交易按钮。 |

```ts
interface StockHeaderPanelProps {
  stockName: string;
  stockCode: string;
  latestPrice: number | null;
  changeAmount: number | null;
  changePct: number | null;
  direction: 'UP' | 'DOWN' | 'FLAT' | 'UNKNOWN';
  industryName?: string;
  sectorTags?: Array<{ key: string; label: string; route?: string }>;
  tradeStatus?: 'TRADING' | 'SUSPENDED' | 'CLOSED' | 'UNKNOWN';
  updateTime?: string;
  actions?: Array<{
    key: 'watchlist' | 'alert' | 'tradePlan';
    label: string;
    enabled: boolean;
  }>;
}
```

颜色规则：

1. 最新价、涨跌额、涨跌幅统一红涨绿跌；
2. 平盘使用灰白；
3. 行业 / 板块标签中性或品牌弱强调；
4. `tradeStatus` 不使用行情涨跌色，使用状态色。

---

## 25.16 StockSideTabs

| 项 | 说明 |
|---|---|
| 组件名称 | `StockSideTabs` |
| 中文名 | 个股右侧信息栏 Tab |
| 组件用途 | 右侧信息栏中切换盘口 / 资料。 |
| 使用页面 | 个股详情页 P0 必需。 |
| 是否 P0 必需 | 是。 |
| 输入字段 / Props | `tabs`、`activeKey`、`onChange`、`contentHeightMode`。 |
| 状态 | default、hover、active、selected、disabled、loading。 |
| 交互 | 点击切换 Tab；盘口展示行情摘要、关联板块、资金统计；资料 Tab P0 显示“暂未开通”。 |
| Design Token 映射 | `--cs-stock-side-tabs-*`、`--cs-color-brand-accent`。 |
| 禁止误用 | 不展示五档盘口、逐笔成交、委比委差；资料 Tab 不伪造完整资料。 |

```ts
interface StockSideTabsProps {
  tabs: Array<{
    key: 'quote' | 'profile';
    label: '盘口' | '资料';
    enabled: boolean;
  }>;
  activeKey: 'quote' | 'profile';
  onChange?: (key: 'quote' | 'profile') => void;
  contentHeightMode?: 'fill-sidebar' | 'auto';
}
```

右侧信息栏固定高度，`TabContent` 内部允许局部滚动：

```css
.stock-side-tabs-content {
  min-height: 0;
  overflow: auto;
}
```

---

## 25.17 RelatedSectorTable

| 项 | 说明 |
|---|---|
| 组件名称 | `RelatedSectorTable` |
| 中文名 | 关联板块表 |
| 组件用途 | 展示个股所属行业、概念、地域等关联板块，支持点击板块进入板块与榜单行情页。 |
| 使用页面 | 个股详情页右侧盘口 Tab P0 必需。 |
| 是否 P0 必需 | 是。 |
| 输入字段 / Props | `rows`、`loading`、`emptyText`、`onSectorClick`。 |
| 状态 | default、hover、active、selected、loading、empty、error。 |
| 交互 | 行 hover；点击板块跳转板块与榜单行情页。 |
| Design Token 映射 | `--cs-table-*`、`--cs-color-market-up/down/flat`。 |
| 禁止误用 | 不在 P0 展示过多板块指标；不输出主观板块推荐。 |

```ts
interface RelatedSectorTableProps {
  rows: RelatedSectorRow[];
  loading?: boolean;
  error?: ErrorStateProps | null;
  emptyText?: string;
  onSectorClick?: (sector: RelatedSectorRow) => void;
}

interface RelatedSectorRow {
  sectorCode: string;
  sectorName: string;
  sectorType: 'INDUSTRY' | 'CONCEPT' | 'REGION' | string;
  changePct: number | null;
  componentStockCount: number | null;
  direction: 'UP' | 'DOWN' | 'FLAT' | 'UNKNOWN';
}
```

表格列：

```text
名称｜涨幅%｜成分股数｜类别
```

颜色：

1. 板块涨幅红涨绿跌；
2. 成分股数中性；
3. 类别中性标签。

---

## 25.18 StockMoneyFlowPanel

| 项 | 说明 |
|---|---|
| 组件名称 | `StockMoneyFlowPanel` |
| 中文名 | 个股资金统计面板 |
| 组件用途 | 展示个股资金流事实，左侧环形资金分布图，右侧金额柱状图。 |
| 使用页面 | 个股详情页右侧盘口 Tab P0 必需。 |
| 是否 P0 必需 | 是。 |
| 输入字段 / Props | `summary`、`items`、`loading`、`error`、`unit`。 |
| 状态 | default、hover、selected、loading、empty、error、dataDelayed。 |
| 交互 | hover 图表显示 Tooltip；P0 不点击下钻。 |
| Design Token 映射 | `--cs-chart-pie-*`、`--cs-chart-bar-*`、`--cs-color-market-up/down/flat`、`--cs-font-family-number`。 |
| 禁止误用 | 不输出资金面评分；不输出买卖建议；不把净流入解释为操作建议。 |

```ts
interface StockMoneyFlowPanelProps {
  summary: {
    mainInflow: number | null;
    mainOutflow: number | null;
    mainNetInflow: number | null;
    unit?: string;
  };
  items: Array<{
    key: 'superLarge' | 'large' | 'medium' | 'small' | string;
    label: string;
    netAmount: number | null;
    amount?: number | null;
    ratio?: number | null;
    direction: 'inflow' | 'outflow' | 'flat';
    displayText?: string;
  }>;
  loading?: boolean;
  error?: ErrorStateProps | null;
}
```

视觉结构：

```text
StockMoneyFlowPanel
├── 左侧：环形资金分布图，显示比例
└── 右侧：金额柱状图，显示金额
```

资金颜色：

1. 净流入红；
2. 净流出绿；
3. 零值灰白；
4. 柱状图方向与数值一致；
5. Tooltip 内正负值继续红绿。

---

## 25.19 图表区面板状态规则

### 25.19.1 Loading

1. 首次加载：图表区可显示整体骨架；
2. 切换周期：只刷新图表区，不清空右侧信息栏；
3. 指标切换：只刷新对应 panel 或重新计算指标；
4. 骨架保留 panel 分区，不改变高度比例。

### 25.19.2 Empty

空态场景：

1. 股票不存在；
2. 周期数据为空；
3. 指标数据为空；
4. 关联板块为空；
5. 资金数据为空；
6. 资料 Tab 暂未开通。

资料 Tab 空态固定：

```text
暂未开通
```

### 25.19.3 Error

错误场景：

1. K 线数据加载失败；
2. 指标计算失败；
3. 资金数据加载失败；
4. 关联板块加载失败；
5. 网络异常。

原则：

```text
局部异常不导致整页不可用
```

---

## 25.20 个股详情页 Mock 数据结构建议

本节只提出 Showcase Mock 和组件设计结构，不作为正式 API 契约。

```ts
interface StockDetailViewModel {
  stock: StockHeaderPanelProps;
  chart: {
    period: KlinePeriod;
    adjustType: 'none' | 'qfq' | 'hfq';
    candles: CandlePoint[];
    indicators: {
      ma?: MaPoint[];
      boll?: BollPoint[];
      macd?: MacdPoint[];
      volume?: VolumePoint[];
      kdj?: KdjPoint[];
    };
  };
  relatedSectors: RelatedSectorRow[];
  moneyFlow: StockMoneyFlowPanelProps;
  dataStatus: {
    updateTime: string;
    status: 'READY' | 'DELAYED' | 'PARTIAL' | 'ERROR';
  };
}

interface CandlePoint {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  prevClose: number;
  volume: number;
  amount: number;
  turnoverRate: number;
  changePct: number;
  amplitude: number;
}

interface MaPoint {
  time: string;
  ma5?: number;
  ma15?: number;
  ma30?: number;
  ma60?: number;
  ma120?: number;
  ma250?: number;
}

interface BollPoint {
  time: string;
  upper?: number;
  mid?: number;
  lower?: number;
}

interface MacdPoint {
  time: string;
  dif: number;
  dea: number;
  macd: number;
}

interface VolumePoint {
  time: string;
  volume: number;
  amount?: number;
  ma5?: number;
  ma10?: number;
}

interface KdjPoint {
  time: string;
  k: number;
  d: number;
  j: number;
}
```

---

## 25.21 对 02 `stock-detail-v1.html` 的组件使用建议

1. 必须输出完整单文件 HTML/CSS/JS。
2. 根容器使用 `height: 100vh` 或兼容 `100dvh`。
3. 不写死 `height: 1080px`。
4. 禁止 body 级整页滚动。
5. 页面结构固定为：`TopMarketBar + BreadcrumbActionBar + StockChartToolbar + StockDetailFixedLayout`。
6. 主内容区高度通过 `calc(100vh - TopMarketBar - BreadcrumbActionBar - ChartToolbar)` 或 flex `flex: 1; min-height: 0` 获得。
7. 左侧图表区包含：K 线主图、MACD、成交量、KDJ、底部指标栏。
8. 每个 chart panel 必须有 `ChartPanelHeaderInfo`。
9. 主图 Header Info 支持 MA / BOLL 切换。
10. 齿轮点击 Toast：`指标设置暂未开通`。
11. 非激活态不显示完整十字线和 Tooltip，但显示坐标轴浮标与 Header Info 跟随。
12. 单击图表区激活十字线和 Tooltip，再次单击关闭。
13. Tooltip 位置按鼠标左右半屏固定在主图区右上 / 左上。
14. Tooltip 字段和颜色方案 A 必须正确。
15. 底部 `IndicatorToolbar` 展示全部入口，P0 实际支持 MACD / 成交量 / KDJ / MA / BOLL。
16. 未支持指标点击 Toast：`该指标暂未支持`。
17. 右侧信息栏固定高度，内部 TabContent 可局部滚动。
18. 盘口 Tab 展示 `StockHeaderPanel`、`RelatedSectorTable`、`StockMoneyFlowPanel`。
19. 资料 Tab 显示 `暂未开通`。
20. 红涨绿跌必须正确。
21. 低于 900px 高度时启用压缩或提示，不启用整页滚动。

---

## 25.22 对 01 Design Token 的依赖

本节依赖 `03-design-tokens.md v0.3.7` 或同等 Token，重点包括：

1. 固定视口布局 Token：
   - `--cs-stock-detail-page-height`
   - `--cs-stock-detail-breadcrumb-action-bar-height`
   - `--cs-stock-detail-chart-toolbar-height`
   - `--cs-stock-detail-main-gap`
   - `--cs-stock-detail-sidebar-width`
2. 图表面板 Token：
   - `--cs-chart-panel-*`
   - `--cs-chart-panel-header-*`
   - `--cs-chart-axis-*`
   - `--cs-chart-grid-*`
3. 十字线与坐标轴浮标 Token：
   - `--cs-chart-crosshair-*`
   - `--cs-chart-axis-float-label-*`
4. K 线 Tooltip Token：
   - `--cs-kline-tooltip-*`
   - `--cs-chart-tooltip-*`
5. 底部指标栏 Token：
   - `--cs-indicator-toolbar-*`
6. 右侧信息栏 Token：
   - `--cs-stock-sidebar-*`
   - `--cs-stock-header-*`
   - `--cs-stock-side-tabs-*`
7. 资金统计图 Token：
   - `--cs-chart-pie-*`
   - `--cs-chart-bar-*`
8. 红涨绿跌 Token：
   - `--cs-color-market-up`
   - `--cs-color-market-down`
   - `--cs-color-market-flat`

硬约束：

```text
实现必须引用 Token，不得在组件中硬编码大量颜色、尺寸、固定 1080px 高度。
```

---

## 25.23 对 04 API 的字段需求建议

本轮 03 不正式修改 API，只提出字段需求。后续如拉 04，应围绕以下接口与字段设计：

### 25.23.1 个股详情聚合接口

```http
GET /api/stocks/{stockCode}/detail-overview
```

用途：

1. `StockHeaderPanel`
2. 右侧盘口 / 资料 Tab 基础状态
3. `RelatedSectorTable`
4. `StockMoneyFlowPanel`
5. 默认周期、复权状态、更新时间、数据状态

### 25.23.2 K 线接口

```http
GET /api/stocks/{stockCode}/candles
```

参数：

```text
stockCode
period
adjustType
startDate
endDate
limit
```

K 线字段：

```text
time
open
high
low
close
prevClose
volume
amount
turnoverRate
changePct
amplitude
```

### 25.23.3 指标接口

```http
GET /api/stocks/{stockCode}/indicators
```

支持：

```text
ma
boll
macd
volume
kdj
```

P0 可前端 Mock 或前端计算，后续由后端返回。

### 25.23.4 禁止 API 返回字段

```text
buySuggestion
sellSuggestion
positionAdvice
tradeAction
tomorrowPrediction
diagnosticConclusion
```

诊股 P0 disabled，不进入个股详情聚合接口的推荐展示字段。

---

## 25.24 本轮新增或修订组件清单

| 类型 | 组件 | 处理方式 |
|---|---|---|
| 新增 | `StockDetailPage` | 个股详情根容器，固定 100vh，禁止整页滚动。 |
| 新增 | `BreadcrumbActionBar` | 个股详情面包屑与操作栏。 |
| 新增 | `StockChartToolbar` | 周期与资料/诊股入口工具栏。 |
| 新增 | `StockDetailFixedLayout` | 左图表区 + 右信息栏固定视口布局。 |
| 新增 | `ChartPanelHeaderInfo` | 每个图表 panel 顶部指标信息栏。 |
| 新增 | `MainOverlayIndicatorMenu` | 主图 MA / BOLL 叠加指标切换。 |
| 新增 | `ChartCrosshairLayer` | 多 panel 联动十字线层。 |
| 新增 | `ChartAxisFloatLabel` | X/Y 坐标轴浮标。 |
| 新增 | `KlineTooltip` | 十字线激活态 K 线 Tooltip。 |
| 新增 | `IndicatorToolbar` | 底部指标栏。 |
| 新增 | `StockHeaderPanel` | 右侧股票头部行情面板。 |
| 新增 | `StockSideTabs` | 右侧盘口 / 资料 Tab。 |
| 新增 | `RelatedSectorTable` | 关联板块表。 |
| 新增 | `StockMoneyFlowPanel` | 个股资金统计面板。 |

---

## 25.25 本轮未修改组件清单

本轮未修改：

1. `TopMarketBar`
2. 市场总览 `Breadcrumb`
3. 市场总览 `PageHeader`
4. 市场总览 `ShortcutBar`
5. 市场总览新闻板块组件
6. 市场总览今日市场客观总结
7. 市场总览主要指数
8. 市场总览涨跌分布
9. 市场总览市场风格
10. 市场总览成交额总览
11. 市场总览大盘资金流向
12. 市场总览榜单速览
13. 市场总览涨跌停统计与分布
14. 市场总览连板天梯
15. 市场总览板块速览
16. 通用组件库 Core Component 注册表中的既有组件

本轮因个股详情页新增组件而被动影响的区域：无。  
原因：个股详情页是新增页面组件体系，不修改市场总览既有组件。  
是否需要产品总控确认：否。

---

## 25.26 低高度策略验收清单

| 条件 | 处理 |
|---|---|
| 视口高度 ≥ 900px | 正常固定视口布局 |
| 视口高度 760px～899px | 压缩 Header、Toolbar、Panel Header、间距；右侧内容局部滚动 |
| 视口高度 < 760px | 显示低高度提示；图表区仍不启用 body 整页滚动 |
| 图表内容溢出 | 图表区内部压缩或局部处理 |
| 右侧信息栏溢出 | TabContent 内部滚动 |
| 底部指标栏溢出 | 水平滚动 |
| 任何高度 | 禁止 `height:1080px`；禁止 body 级整页滚动 |

---

## 25.27 待产品总控确认问题

1. `TopMarketBar`、`BreadcrumbActionBar`、`StockChartToolbar` 的最终高度是否采用 PRD 建议：44px / 34px / 36px？
2. 右侧信息栏宽度是否固定 380px，还是在 360px～400px 范围内自适应？
3. 主图高度占比是否固定 44%，副图各占 17%，还是由 CSS 变量配置？
4. Tooltip 字段顺序是否固定为：时间、开盘、收盘、最高、最低、涨幅、振幅、成交量、成交额、换手率？
5. Tooltip 颜色方案 A 是否作为最终实现准则？
6. Header Info 中 MA 周期是否固定为 MA5、MA15、MA30、MA60、MA120、MA250？
7. BOLL 与底部指标栏的同步是否只支持开关，还是后续要支持参数设置？
8. 右侧资金统计环形图与柱状图比例是否需要进一步由 01 / 02 高保真确认？
9. 低于 900px 时是否允许隐藏部分非核心右侧内容，还是必须完整但局部滚动？
10. 个股详情页是否后续需要独立 API v0.1 文档，由 04 单独输出？

---

## 25.28 个股详情页组件规范验收清单

| 验收项 | 要求 |
|---|---|
| 完整文档 | 本文件仍是完整 `04-component-guidelines.md`，不是 delta 文档。 |
| 固定视口 | `StockDetailPage` 使用 `height:100vh` / `100dvh`，`overflow:hidden`。 |
| 主内容区 | 使用 `calc(100vh - TopMarketBar - BreadcrumbActionBar - ChartToolbar)` 或 flex `flex:1; min-height:0`。 |
| 禁止固定高度 | 不写死 `height:1080px`。 |
| 禁止整页滚动 | 不用 body 级滚动解决布局问题。 |
| 最低可用 | 1440×900 为最低可用尺寸，低于 900px 进入压缩 / 提示策略。 |
| 图表 Header Info | `ChartPanelHeaderInfo` 定义清楚，能随鼠标横轴刷新。 |
| 主图叠加指标 | `MainOverlayIndicatorMenu` 支持 MA / BOLL，齿轮 Toast。 |
| 十字线 | `ChartCrosshairLayer` 区分非激活态和激活态。 |
| 坐标浮标 | `ChartAxisFloatLabel` 覆盖 X/Y 浮标。 |
| Tooltip | `KlineTooltip` 字段、位置、颜色方案 A 清楚。 |
| 底部指标栏 | `IndicatorToolbar` 展示 P0 与后置指标，未支持 Toast。 |
| 右侧信息栏 | `StockHeaderPanel`、`StockSideTabs`、`RelatedSectorTable`、`StockMoneyFlowPanel` 定义清楚。 |
| 红涨绿跌 | 价格、涨跌幅、资金正负均遵守红涨绿跌。 |
| 非目标 | 不输出买卖建议、诊股结论、真实交易下单。 |

---

## 25.29 建议放置到 Google Drive 的路径

```text
财势乾坤/设计/04-component-guidelines.md
```

## 25.30 建议仓库保存路径

```text
/docs/wealth/04-component-guidelines.md
```

## 25.31 本轮输出文件下载链接

对话交付文件：

```text
sandbox:/mnt/data/stock-detail-output-final/04-component-guidelines.md
```

---

# 26. 个股详情页 Showcase 局部修正规则（TopMarketBar / 常驻坐标轴 / 顶部价格块废弃）

> 本节为个股详情页 Showcase 局部修正规则。  
> 本节只处理 3 个点名问题：顶部复用市场总览 `TopMarketBar`、图表左右 Y 轴刻度常驻显示、删除图表区顶部右上角额外价格 / 涨幅块。  
> 本节不修改 K 线主图绘制组件、MACD / 成交量 / KDJ 默认副图结构、十字光标组件逻辑、Tooltip 字段和颜色规则、`StockHeaderPanel`、`StockSideTabs`、`RelatedSectorTable`、`StockMoneyFlowPanel`、`StockChartToolbar`、资料 Tab 占位或诊股 disabled 规则。

## 26.1 本轮修订边界

本轮只允许围绕以下组件或规则修订：

1. `StockDetailPage` 顶部结构；
2. `StockDetailFixedLayout` 顶部固定区域计算；
3. `ChartYAxis`；
4. `ChartDualYAxis`；
5. `ChartAxisTickLabel`；
6. `ChartTimeAxis`；
7. `ChartTimeTickLabel`；
8. 图表区顶部右上角额外价格 / 涨幅块的废弃规则。

本轮禁止主动修改：

1. K 线主图绘制组件；
2. MACD / 成交量 / KDJ 默认副图结构；
3. 十字光标组件逻辑；
4. `KlineTooltip` 字段和颜色规则；
5. `StockHeaderPanel` 结构；
6. `StockSideTabs`；
7. `RelatedSectorTable`；
8. `StockMoneyFlowPanel`；
9. `StockChartToolbar`；
10. 资料 Tab 占位；
11. 诊股 disabled；
12. 与本轮 3 个修正点无关的市场总览组件或个股详情组件。

---

## 26.2 TopMarketBar 复用规则

### 26.2.1 规则结论

个股详情页必须复用市场总览同款 `TopMarketBar`。

```text
StockDetailPage
├── TopMarketBar              // 复用市场总览同款全局顶部栏
├── BreadcrumbActionBar       // 页面内部面包屑 + 操作区
├── StockChartToolbar         // 周期与入口工具栏
└── StockDetailFixedLayout    // 左图表区 + 右信息栏
```

### 26.2.2 禁止事项

个股详情页不得新增或重写以下顶部全局栏能力：

1. 不允许定义 `StockDetailHeader` 作为新的顶部全局栏；
2. 不允许在个股详情页单独重写 Logo；
3. 不允许在个股详情页单独重写系统入口；
4. 不允许在个股详情页单独重写指数行情条；
5. 不允许在个股详情页单独重写交易状态；
6. 不允许在个股详情页单独重写数据状态；
7. 不允许在个股详情页用局部标题栏替代全局 `TopMarketBar`。

### 26.2.3 BreadcrumbActionBar 不等于全局 Header

`BreadcrumbActionBar` 是页面内部结构，不属于本轮所说的全局 Header。

`BreadcrumbActionBar` 只负责：

```text
财势乾坤 / 乾坤行情 / 个股详情 / 股票名称 股票代码
前复权 / 更新时间 / 刷新 / 数据正常
```

它不得承载：

1. 项目 Logo；
2. 一级系统菜单；
3. TopMarketBar 指数行情条；
4. 用户入口；
5. 全局交易状态。

### 26.2.4 Props 与依赖关系

`StockDetailPage` 不直接定义新的顶部栏 Props，而是复用 `TopMarketBarProps`。

```ts
interface StockDetailPageProps {
  topMarketBar: TopMarketBarProps;
  breadcrumbAction: BreadcrumbActionBarProps;
  chartToolbar: StockChartToolbarProps;
  layout: StockDetailFixedLayoutProps;
}
```

`TopMarketBarProps` 的契约沿用市场总览已定义内容，不在个股详情页重复定义。

### 26.2.5 与固定视口高度计算的关系

`TopMarketBar` 是顶部固定区域的一部分。个股详情主内容区高度计算必须包含其高度：

```css
.stock-detail-page {
  --sd-top-market-bar-h: var(--cs-top-market-bar-height, 44px);
  --sd-breadcrumb-action-bar-h: var(--cs-stock-detail-breadcrumb-action-bar-height, 34px);
  --sd-chart-toolbar-h: var(--cs-stock-detail-chart-toolbar-height, 36px);

  height: 100vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.stock-detail-main {
  height: calc(
    100vh
    - var(--sd-top-market-bar-h)
    - var(--sd-breadcrumb-action-bar-h)
    - var(--sd-chart-toolbar-h)
  );
  min-height: 0;
  overflow: hidden;
}
```

如果工程使用 flex：

```css
.stock-detail-main {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
```

注意：`100vh` 是浏览器当前可视区域高度，不是固定 `1080px`。任何实现都不得写死：

```css
height: 1080px; /* 禁止 */
```

---

## 26.3 StockDetailFixedLayout 顶部结构修订

### 26.3.1 组件用途

`StockDetailFixedLayout` 是个股详情页主内容区布局组件，只负责 `ChartArea + RightInfoPanel` 的固定视口内排布。

它不负责渲染全局顶部栏。

### 26.3.2 修订后结构

```text
StockDetailPage
├── TopMarketBar
├── BreadcrumbActionBar
├── StockChartToolbar
└── StockDetailFixedLayout
    ├── chartArea
    │   ├── KLinePanel
    │   ├── MACDPanel
    │   ├── VolumePanel
    │   ├── KDJPanel
    │   └── IndicatorToolbar
    └── sidePanel
        ├── StockHeaderPanel
        ├── StockSideTabs
        └── TabContent
```

### 26.3.3 Props 摘要

```ts
interface StockDetailFixedLayoutProps {
  chartArea: React.ReactNode;
  sidePanel: React.ReactNode;
  chartAreaRatio?: number; // 默认 0.76
  sidePanelRatio?: number; // 默认 0.24
  sidePanelWidth?: number; // 可选，建议 360-400
  lowHeightMode?: boolean;
}
```

### 26.3.4 禁止误用

1. 不在 `StockDetailFixedLayout` 内再创建 `TopMarketBar`；
2. 不在 `StockDetailFixedLayout` 内创建 `StockDetailHeader`；
3. 不用 `StockDetailFixedLayout` 解决全局导航问题；
4. 不启用 body 级整页滚动；
5. 不写死 1080px。

---

## 26.4 ChartYAxis

### 26.4.1 组件名称

`ChartYAxis`

### 26.4.2 中文名

图表 Y 轴刻度组件。

### 26.4.3 所属层级

个股详情页图表组件 / 通用图表基础组件候选。

### 26.4.4 组件用途

用于在单个图表 panel 的左侧或右侧常驻显示 Y 轴刻度。它是图表坐标体系的基础展示组件，不依赖十字坐标线激活状态。

### 26.4.5 适用场景

1. K 线主图价格轴；
2. MACD 指标轴；
3. 成交量轴；
4. KDJ 指标轴；
5. 后续其它副图指标轴。

### 26.4.6 Props 摘要

```ts
type ChartYAxisSide = 'left' | 'right';
type ChartYAxisValueType = 'price' | 'macd' | 'volume' | 'amount' | 'kdj' | 'percent' | 'number';

interface ChartYAxisTick {
  value: number;
  label: string;
  y: number;
  major?: boolean;
}

interface ChartYAxisProps {
  side: ChartYAxisSide;
  valueType: ChartYAxisValueType;
  ticks: ChartYAxisTick[];
  width?: number;
  panelId: string;
  visible?: boolean; // 默认 true，常驻显示
  alignGridLines?: boolean; // 默认 true
  formatter?: (value: number) => string;
}
```

### 26.4.7 视觉结构

```text
ChartYAxis
├── axisLine 可选弱线
├── tickLabels[]
└── gridLineAnchor[] 与横向网格线对齐
```

视觉规则：

1. 左右轴均为弱文字，不抢主图；
2. 使用等宽数字；
3. 价格轴可显示两位小数；
4. 成交量轴可格式化为 `万手` / `亿股` 等展示口径；
5. MACD 可保留 2～3 位小数；
6. KDJ 通常显示 0～100 范围；
7. 轴文字常驻显示，不等十字线出现。

### 26.4.8 交互

`ChartYAxis` 本身不响应点击，不参与缩放拖拽。

hover 图表时：

1. 常驻刻度不隐藏；
2. 只允许 `ChartAxisFloatLabel` 临时叠加在对应 Y 轴位置；
3. 浮标不替代常驻刻度。

### 26.4.9 状态

| 状态 | 规则 |
|---|---|
| default | 左/右 Y 轴常驻显示 tick label |
| hover | 常驻刻度不变，浮标可叠加显示 |
| active | 十字线激活后常驻刻度仍显示 |
| selected | 不适用 |
| disabled | 图表 panel disabled 时弱化刻度 |
| loading | 保留轴区域，可显示骨架刻度或空刻度 |
| empty | 显示轴区域，刻度可为空或显示 `--` |
| error | 显示轴区域，panel 内显示错误态 |

### 26.4.10 Design Token 映射

使用 01 Token 中的个股详情图表轴相关变量，建议包括：

```text
--cs-stock-chart-axis-label-color
--cs-stock-chart-axis-label-font-size
--cs-stock-chart-axis-width
--cs-stock-chart-grid-line-color
--cs-font-family-number
```

如 01 Token 中命名不同，以 `03-design-tokens.md` 最新版本为准。

### 26.4.11 禁止误用

1. 不把 Y 轴刻度绑定到十字线状态；
2. 不只在 hover 时显示 Y 轴刻度；
3. 不让主图和副图共用同一刻度范围；
4. 不用 `ChartAxisFloatLabel` 替代常驻 Y 轴；
5. 不因空间不足而完全隐藏左右 Y 轴。

---

## 26.5 ChartDualYAxis

### 26.5.1 组件名称

`ChartDualYAxis`

### 26.5.2 中文名

图表左右双 Y 轴组件。

### 26.5.3 组件用途

用于在每个图表 panel 中同时常驻显示左侧和右侧 Y 轴刻度，确保图表在没有十字线时也具备可读坐标参考。

### 26.5.4 Props 摘要

```ts
interface ChartDualYAxisProps {
  panelId: string;
  valueType: ChartYAxisValueType;
  leftTicks: ChartYAxisTick[];
  rightTicks: ChartYAxisTick[];
  leftFormatter?: (value: number) => string;
  rightFormatter?: (value: number) => string;
  showLeft?: boolean;  // 默认 true
  showRight?: boolean; // 默认 true
  alignGridLines?: boolean; // 默认 true
}
```

### 26.5.5 使用规则

1. 每个 panel 独立计算刻度范围；
2. K 线主图使用价格范围；
3. MACD 使用 MACD 值范围；
4. 成交量使用成交量范围；
5. KDJ 使用 0～100 或当前数据范围；
6. 左右轴可以显示同一组刻度，也可以根据图表需要显示不同格式；
7. 左右轴刻度必须与横向网格线对齐。

### 26.5.6 常驻显示规则

`ChartDualYAxis` 必须常驻显示。

```text
非 hover：显示左右 Y 轴常驻刻度
hover：显示左右 Y 轴常驻刻度 + 当前鼠标 Y 轴浮标
十字线激活：显示左右 Y 轴常驻刻度 + 十字线浮标
十字线关闭：左右 Y 轴常驻刻度仍然显示
```

### 26.5.7 与 ChartCrosshairLayer 的关系

`ChartDualYAxis` 是基础坐标轴层。`ChartCrosshairLayer` 是交互叠加层。

```text
ChartPanel
├── ChartGridLayer
├── ChartSeriesLayer
├── ChartDualYAxis          // 常驻坐标轴层
├── ChartTimeAxis           // 常驻时间轴层
├── ChartCrosshairLayer     // 交互层，按状态显示/隐藏
└── ChartAxisFloatLabel     // 浮标层，hover/crosshair 时显示
```

`ChartCrosshairLayer` 不负责绘制常驻刻度。

---

## 26.6 ChartAxisTickLabel

### 26.6.1 组件名称

`ChartAxisTickLabel`

### 26.6.2 中文名

图表轴刻度文字。

### 26.6.3 组件用途

用于渲染 Y 轴或 X 轴的单个常驻刻度标签。

### 26.6.4 Props 摘要

```ts
type ChartAxisOrientation = 'x' | 'y';
type ChartAxisLabelAlign = 'left' | 'right' | 'center';

interface ChartAxisTickLabelProps {
  orientation: ChartAxisOrientation;
  label: string;
  x: number;
  y: number;
  align?: ChartAxisLabelAlign;
  major?: boolean;
  muted?: boolean;
  valueType?: ChartYAxisValueType | 'time';
}
```

### 26.6.5 规则

1. 数字类标签使用等宽数字；
2. 主要刻度可略强，次要刻度弱化；
3. 标签不得遮挡 K 线主体；
4. X 轴标签不得与 `ChartAxisFloatLabel` 混淆；
5. 标签是常驻坐标轴的一部分，不随十字线开关隐藏。

---

## 26.7 ChartTimeAxis

### 26.7.1 组件名称

`ChartTimeAxis`

### 26.7.2 中文名

图表时间轴组件。

### 26.7.3 组件用途

用于在图表底部常驻显示时间刻度。它与十字线下方的时间浮标不同，是常驻坐标轴。

### 26.7.4 Props 摘要

```ts
type StockChartPeriod = 'time' | '1m' | '5m' | '15m' | '30m' | '60m' | '90m' | '120m' | 'day' | 'week' | 'month';

interface ChartTimeTick {
  time: string;
  label: string;
  x: number;
  major?: boolean;
}

interface ChartTimeAxisProps {
  period: StockChartPeriod;
  ticks: ChartTimeTick[];
  height?: number;
  visible?: boolean; // 默认 true
  formatter?: (time: string, period: StockChartPeriod) => string;
}
```

### 26.7.5 日线 / 周线 / 月线刻度规则

日线、周线、月线应优先显示月份或关键月份刻度。

建议：

```text
日线：按月份边界显示，如 2025-11、2025-12、2026-01
周线：按月份或季度显示，如 2025-10、2026-01、2026-04
月线：按年份或关键月份显示，如 2024、2025、2026
```

规则：

1. 不需要每根 K 线都显示日期；
2. 刻度密度根据图表宽度自动抽样；
3. 标签不得重叠；
4. 标签位置必须与图表横向坐标对齐；
5. 时间轴常驻显示，不依赖 hover 或十字线。

### 26.7.6 分钟线刻度规则

分钟线按交易日间隔显示日期刻度。

建议：

```text
1m / 5m / 15m / 30m / 60m / 90m / 120m：每 2 个交易日显示一个日期刻度
```

规则：

1. 按交易日边界生成刻度；
2. 默认每 2 个交易日显示一个日期刻度；
3. 如果图表宽度不足，可以进一步降采样；
4. 如果图表宽度充足，可以显示更多交易日刻度；
5. 分钟线不需要在常驻时间轴上显示每个分钟时间点；
6. 具体分钟时间由十字线时间浮标和 Tooltip 展示。

### 26.7.7 与时间轴浮标的区别

`ChartTimeAxis` 是常驻底部时间刻度。

`ChartAxisFloatLabel` 的 X 轴浮标是 hover / 十字线激活时显示的当前时间标签。

二者不能混用：

| 组件 | 显示时机 | 内容 | 是否常驻 |
|---|---|---|---|
| `ChartTimeAxis` | 始终显示 | 月份 / 日期刻度 | 是 |
| `ChartAxisFloatLabel` X 轴浮标 | hover 或十字线激活 | 当前鼠标所在 K 线时间 | 否 |

---

## 26.8 ChartTimeTickLabel

### 26.8.1 组件名称

`ChartTimeTickLabel`

### 26.8.2 中文名

时间轴刻度标签。

### 26.8.3 组件用途

用于渲染 `ChartTimeAxis` 上的单个时间刻度文本。

### 26.8.4 Props 摘要

```ts
interface ChartTimeTickLabelProps {
  label: string;
  x: number;
  y: number;
  major?: boolean;
  period: StockChartPeriod;
}
```

### 26.8.5 规则

1. 日线 / 周线 / 月线可显示月份、季度或年份；
2. 分钟线显示日期刻度，不密集显示分钟；
3. 与 K 线横向坐标严格对齐；
4. 不遮挡底部指标栏；
5. 不替代十字线时间浮标。

---

## 26.9 ChartAxisFloatLabel 与常驻轴的关系修订

此前 `ChartAxisFloatLabel` 已定义为 X/Y 坐标轴浮标。本轮补充其边界：

1. `ChartAxisFloatLabel` 只在 hover 或十字线激活态出现；
2. 它用于显示当前鼠标所在价格 / 指标值 / 时间；
3. 它不得承担常驻 Y 轴刻度职责；
4. 它不得承担常驻时间轴刻度职责；
5. 常驻轴必须由 `ChartDualYAxis` 和 `ChartTimeAxis` 提供。

---

## 26.10 废弃：ChartTopRightPriceBlock

### 26.10.1 废弃结论

个股详情页图表区顶部右上角不应存在额外价格 / 涨幅块。

以下组件或类似结构必须标记为废弃：

```text
ChartTopRightPriceBlock
ChartHeaderPriceBlock
ChartFloatingPriceSummary
ChartTopRightQuoteBlock
图表区顶部右上角额外价格 / 涨幅展示
```

### 26.10.2 废弃原因

1. 个股价格信息已经归属 `StockHeaderPanel` 或右侧行情信息区；
2. 图表区顶部右上角重复展示价格和涨幅会造成信息冗余；
3. 图表顶部空间应优先给 `ChartPanelHeaderInfo`、主图指标、图表绘制区和坐标体系；
4. 额外价格块容易干扰 K 线主图阅读；
5. 会与十字线 Tooltip / Header Info 的动态信息产生歧义。

### 26.10.3 正确归属

个股价格信息归属：

```text
StockHeaderPanel
右侧行情信息区
```

图表区顶部应保留：

```text
ChartPanelHeaderInfo
MainOverlayIndicatorMenu
必要的指标设置入口
```

不得在 K 线图表区右上角再次展示：

```text
最新价
涨跌额
涨跌幅
行情摘要卡片
```

---

## 26.11 对现有个股详情组件的修订说明

### 26.11.1 StockDetailPage

修订点：

1. 顶部必须复用市场总览 `TopMarketBar`；
2. 保持根容器 `height: 100vh`、`overflow: hidden`；
3. 保持主内容区 `flex: 1; min-height: 0; overflow: hidden`；
4. 保持 `100vh` 是浏览器当前可视区域高度，不是固定 1080px；
5. 不新增 `StockDetailHeader`。

### 26.11.2 StockDetailFixedLayout

修订点：

1. 只管理主内容区内部布局；
2. 不渲染 `TopMarketBar`；
3. 与 `BreadcrumbActionBar`、`StockChartToolbar` 一起参与高度计算；
4. 继续保持左图表区 / 右信息栏固定视口布局；
5. 不启用整页滚动。

### 26.11.3 ChartCrosshairLayer

本轮不修改逻辑，仅补充层级关系：

```text
常驻坐标轴：ChartDualYAxis + ChartTimeAxis
交互叠加层：ChartCrosshairLayer + ChartAxisFloatLabel
```

### 26.11.4 KlineTooltip

本轮不修改字段和颜色方案。仍沿用此前定义：时间、开盘、收盘、最高、最低、涨幅、振幅、成交量、成交额、换手率，以及 Tooltip 颜色方案 A。

### 26.11.5 StockHeaderPanel

本轮不修改结构，仅明确：图表区顶部右上角额外价格块废弃后，个股价格信息继续由 `StockHeaderPanel` 或右侧行情信息区承载。

---

## 26.12 对 02 `stock-detail-v1.html` / Showcase 的组件使用建议

1. 保留市场总览同款 `TopMarketBar`，不要重新画一套个股详情顶部栏。
2. 删除图表区顶部右上角额外价格 / 涨幅块。
3. 保留 `StockHeaderPanel` 中的价格、涨跌额、涨跌幅展示。
4. 每个图表 panel 常驻显示左右 Y 轴刻度。
5. 每个 panel 的 Y 轴范围独立计算。
6. Y 轴刻度与横向网格线对齐。
7. 时间轴常驻显示在图表底部。
8. 日线 / 周线 / 月线显示月份、关键月份、季度或年份刻度。
9. 分钟线按交易日间隔显示日期刻度，建议每 2 个交易日显示一个日期刻度。
10. 十字线时间浮标和常驻时间轴必须区分显示。
11. 不修改 MACD、成交量、KDJ 默认副图结构。
12. 不修改十字光标激活/取消逻辑。
13. 不修改 Tooltip 字段和颜色规则。
14. 不启用 body 级整页滚动。
15. 不写死 `height: 1080px`。

---

## 26.13 对 01 Design Token 的依赖

本节依赖 `03-design-tokens.md` 中的以下 Token 类型：

1. `TopMarketBar` 高度、背景、边框、文字、指数条 Token；
2. 个股详情固定视口布局高度 Token；
3. `BreadcrumbActionBar` 高度 Token；
4. `StockChartToolbar` 高度 Token；
5. 图表网格线 Token；
6. 图表 Y 轴刻度文字 Token；
7. 图表时间轴文字 Token；
8. 图表坐标轴浮标 Token；
9. 图表 Tooltip Token；
10. 右侧信息栏 Token；
11. 红涨绿跌行情语义色 Token。

若 01 Token 中具体命名与本文件建议名不一致，以 `03-design-tokens.md` 最新版本为准；组件实现不得硬编码颜色、字号、轴宽和主内容高度。

---

## 26.14 本轮新增或修订组件清单

| 类型 | 组件 / 规则 | 处理方式 |
|---|---|---|
| 修订 | `StockDetailPage` | 明确顶部复用市场总览 `TopMarketBar`，禁止新增 `StockDetailHeader`。 |
| 修订 | `StockDetailFixedLayout` | 明确只负责主内容区布局，不负责全局顶部栏。 |
| 新增 | `ChartYAxis` | 单侧 Y 轴常驻刻度组件。 |
| 新增 | `ChartDualYAxis` | 左右双 Y 轴常驻刻度组件。 |
| 新增 | `ChartAxisTickLabel` | 常驻坐标轴刻度文字组件。 |
| 新增 | `ChartTimeAxis` | 图表底部常驻时间轴组件。 |
| 新增 | `ChartTimeTickLabel` | 时间轴刻度文字组件。 |
| 修订 | `ChartAxisFloatLabel` | 明确只作为 hover / 十字线浮标，不承担常驻轴职责。 |
| 废弃 | `ChartTopRightPriceBlock` / 类似结构 | 废弃图表区顶部右上角额外价格 / 涨幅块。 |

---

## 26.15 本轮未修改组件清单

本轮未修改：

1. K 线主图绘制组件；
2. MACD / 成交量 / KDJ 默认副图结构；
3. 十字光标组件逻辑；
4. `KlineTooltip` 字段和颜色规则；
5. `StockHeaderPanel` 结构；
6. `StockSideTabs`；
7. `RelatedSectorTable`；
8. `StockMoneyFlowPanel`；
9. `StockChartToolbar`；
10. 资料 Tab 占位；
11. 诊股 disabled；
12. 市场总览已确认组件；
13. 通用组件库 Core Component 注册表中与本轮无关的组件。

本轮因局部修正而被动影响的区域：无。  
原因：本轮只补充顶部复用、常驻坐标轴和价格块废弃规则，不改动其它图表和右侧信息组件。  
是否需要产品总控确认：否。

---

## 26.16 验收清单

| 验收项 | 要求 |
|---|---|
| 完整文档 | 本文件仍是完整 `04-component-guidelines.md`，不是 delta 文档。 |
| TopMarketBar | 个股详情页复用市场总览同款 `TopMarketBar`。 |
| 禁止新 Header | 不新增 `StockDetailHeader` 作为全局顶部栏。 |
| 固定视口 | 根容器保持 `height:100vh` / `100dvh`，`overflow:hidden`。 |
| 主内容区 | 使用 `calc(100vh - TopMarketBar - BreadcrumbActionBar - ChartToolbar)` 或 flex `flex:1; min-height:0`。 |
| 禁止固定高度 | 不写死 `height:1080px`。 |
| 禁止整页滚动 | 不用 body 级整页滚动解决布局问题。 |
| 左右 Y 轴 | 每个图表 panel 常驻显示左侧和右侧 Y 轴刻度。 |
| 独立刻度范围 | K 线、MACD、成交量、KDJ 各自独立计算刻度范围。 |
| 网格对齐 | Y 轴刻度与横向网格线对齐。 |
| 时间轴 | `ChartTimeAxis` 常驻显示，日线 / 周线 / 月线显示月份或关键月份，分钟线按交易日间隔显示日期刻度。 |
| 浮标边界 | `ChartAxisFloatLabel` 只作为 hover / 十字线浮标，不替代常驻轴。 |
| 废弃价格块 | 图表区顶部右上角额外价格 / 涨幅块明确废弃。 |
| 价格归属 | 个股价格信息归属 `StockHeaderPanel` 或右侧行情信息区。 |
| 未点名组件 | 不修改 K 线绘制、MACD / 成交量 / KDJ、十字线、Tooltip、右侧信息栏等未点名组件。 |

---

## 26.17 待产品总控确认问题

1. `ChartDualYAxis` 左右两侧默认是否显示完全相同刻度，还是右侧可做压缩版？当前建议默认同刻度，同步对齐横向网格线。
2. K 线主图价格轴是否保留 2 位小数，还是根据价格区间自动调整精度？当前建议自动格式化但默认 2 位。
3. 分钟线每 2 个交易日显示一个日期刻度是否作为默认规则？当前建议是默认规则，可随图表宽度降采样。
4. 日线 / 周线 / 月线是否统一使用月份标签，还是月线改用年份标签？当前建议日线 / 周线用月份，月线用年份或关键月份。
5. 低高度模式下是否允许弱化右侧 Y 轴文字透明度，但仍常驻显示？当前建议允许弱化，不允许完全隐藏。
6. 图表区顶部右上角额外价格块废弃后，`StockHeaderPanel` 的价格信息是否需要在视觉上更突出？当前本轮不修改 `StockHeaderPanel`，后续可由产品总控另行发起。

---

## 26.18 本轮输出文件下载链接

对话交付文件：

```text
sandbox:/mnt/data/stock-detail-corrections-output-final/04-component-guidelines.md
```

## 26.19 建议放置到 Google Drive 的路径

```text
财势乾坤/设计/04-component-guidelines.md
```

## 26.20 建议仓库保存路径

```text
/docs/wealth/04-component-guidelines.md
```

---

# 个股详情页顶部结构组件关系修正规则（Stock Detail Review v2）

> 本节为《个股详情 HTML Review v2｜总控解读与变更单》的 03 组件规范修订。  
> 本节只处理个股详情页顶部结构的组件关系，不修改 K 线主图、MACD、成交量、KDJ、坐标轴、时间轴、十字线、Tooltip、Header Info、右侧信息栏、关联板块表、个股资金统计图、资料 Tab、诊股 disabled 或 API 字段。  
> 本节对旧文中涉及 `BreadcrumbActionBar`、`StockChartToolbar`、独立更新时间/刷新/READY 行、图表区顶部右上价格块的描述具有覆盖效力；其它已确认内容继续保留。

## 1. 本轮 Review v2 修改摘要

本轮只修正个股详情页顶部结构关系：

1. 个股详情页最顶部必须完全复用市场总览同款 `TopMarketBar`。
2. `TopMarketBar` 是全局组件，不允许为个股详情页定义 `StockDetailHeader` 作为新的顶部全局栏。
3. `StockBreadcrumb` 只显示路径，例如：`财势乾坤 / 乾坤行情 / 个股详情 / 福斯特 603806.SH`。
4. `StockBreadcrumb` 不包含前复权、更新时间、刷新、READY，也不承担图表控制职责。
5. 删除绿色框所对应的独立控制行 / 独立占位行 / 独立数据状态行。
6. 新增或修订 `ChartWorkspaceToolbar`，作为红框区域的核心组件。
7. `ChartWorkspaceToolbar` 承载股票识别、周期切换、前复权、股票资料、诊股、设置。
8. `前复权` 从 Breadcrumb / 独立控制行中移除，进入 `ChartWorkspaceToolbar` 右侧，可由 `AdjustTypeSelect` 实现。
9. 删除 `更新时间`、`刷新`、`READY` 在个股详情页顶部结构中的独立展示。
10. 如果旧文存在 `ChartTopRightPriceBlock` 或图表区顶部右上角额外价格 / 涨幅块，本轮明确废弃。

本轮目标是降低顶部无效高度占用，使 K 线与指标区域获得更多有效视口空间，同时不破坏固定视口交易终端布局。

## 2. 个股详情页最终顶部结构

个股详情页最终顶部结构必须为：

```text
StockDetailPage
├── TopMarketBar
├── StockBreadcrumb
├── ChartWorkspaceToolbar
└── MainContent / StockDetailFixedLayout
```

对应视觉顺序：

```text
TopMarketBar
StockBreadcrumb
ChartWorkspaceToolbar
K线主图
MACD
成交量
KDJ
右侧信息栏
```

禁止出现以下结构：

```text
TopMarketBar
Breadcrumb
独立更新时间 / 刷新 / READY 行
ChartToolbar
MainContent
```

也禁止出现：

```text
StockDetailHeader
BreadcrumbActionBar 带前复权 / 更新时间 / 刷新 / READY
IndependentStockDetailControlBar
MainContent
```

## 3. StockDetailPage

| 项 | 说明 |
|---|---|
| 组件名称 | `StockDetailPage` |
| 中文名 | 个股详情页根组件 |
| 所属层级 | 页面级业务组件 |
| 组件用途 | 组织个股详情页固定视口结构，承接全局顶部栏、路径栏、图表工作区工具栏和主内容区。 |
| 使用页面 | 个股详情页 P0。 |
| 是否 P0 必需 | 是。 |
| 输入字段 / Props 摘要 | `stockCode`、`initialPeriod`、`initialAdjustType`、`topMarketBarProps`、`breadcrumbItems`、`stockIdentity`、`toolbarState`、`layoutState`。 |
| 状态 | `loading`、`ready`、`partial`、`error`、`empty`。页面级状态不能导致整页滚动，只允许局部模块状态降级。 |
| 交互 | 管理周期切换、复权类型切换、图表工作区按钮事件、路由跳转。 |
| Design Token 映射 | 复用 `TopMarketBar` 全局 Token；`StockBreadcrumb` 与 `ChartWorkspaceToolbar` 使用个股详情页顶部结构 Token；固定视口使用 `--cs-stock-detail-*` / `--cs-chart-workspace-*` 类 Token。 |
| 禁止误用 | 不得定义 `StockDetailHeader` 取代 `TopMarketBar`；不得在根组件上启用 body 级整页滚动；不得写死 `height: 1080px`。 |

推荐结构：

```tsx
function StockDetailPage(props: StockDetailPageProps) {
  return (
    <div className="stock-detail-page">
      <TopMarketBar {...props.topMarketBarProps} />
      <StockBreadcrumb items={props.breadcrumbItems} />
      <ChartWorkspaceToolbar
        stockIdentity={props.stockIdentity}
        activePeriod={props.activePeriod}
        periodTabs={props.periodTabs}
        adjustType={props.adjustType}
        diagnosisDisabled
      />
      <StockDetailFixedLayout />
    </div>
  );
}
```

固定视口规则继续保持：

```css
.stock-detail-page {
  height: 100vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
```

如工程支持桌面端 `100dvh`，可使用：

```css
.stock-detail-page {
  height: 100vh;
  height: 100dvh;
}
```

但文档口径仍为：`100vh` 表示浏览器当前可视区域高度，不是固定 `1080px`。

## 4. StockDetailFixedLayout

| 项 | 说明 |
|---|---|
| 组件名称 | `StockDetailFixedLayout` |
| 中文名 | 个股详情固定视口主布局 |
| 所属层级 | 页面布局组件 |
| 组件用途 | 在 `TopMarketBar + StockBreadcrumb + ChartWorkspaceToolbar` 下方承载左侧图表工作区与右侧信息栏。 |
| 使用页面 | 个股详情页 P0。 |
| 是否 P0 必需 | 是。 |
| 输入字段 / Props 摘要 | `leftChartArea`、`rightInfoPanel`、`rightWidth`、`layoutMode`、`lowHeightMode`。 |
| 状态 | `default`、`low-height`、`loading`、`partial`、`error`。 |
| 交互 | 本组件不处理行情交互，只负责布局分配与局部 overflow 约束。 |
| Design Token 映射 | `--cs-stock-detail-main-gap`、`--cs-stock-detail-side-width`、`--cs-stock-detail-main-bg`、`--cs-stock-detail-border`。 |
| 禁止误用 | 不得承担 Breadcrumb、前复权、更新时间、刷新、READY 的职责。 |

主内容区高度必须由顶部固定区域动态扣除：

```text
MainContentHeight =
100vh
- TopMarketBar 高度
- StockBreadcrumb 高度
- ChartWorkspaceToolbar 高度
```

推荐 CSS：

```css
.stock-detail-main {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  display: grid;
  grid-template-columns: minmax(0, 1fr) var(--cs-stock-detail-side-width, 380px);
  gap: var(--cs-stock-detail-main-gap, 8px);
}
```

如必须使用 `calc`，应使用变量，而不是固定像素总高度：

```css
.stock-detail-main {
  height: calc(
    100vh
    - var(--cs-top-market-bar-height)
    - var(--cs-stock-breadcrumb-height)
    - var(--cs-chart-workspace-toolbar-height)
  );
  min-height: 0;
  overflow: hidden;
}
```

禁止：

```css
.stock-detail-main {
  height: 1080px;
  overflow-y: auto;
}
```

## 5. TopMarketBar 复用约束

`TopMarketBar` 是财势乾坤全局顶部栏组件。个股详情页必须复用市场总览同款 `TopMarketBar`。

### 5.1 必须复用的内容

个股详情页顶部 `TopMarketBar` 必须复用：

1. Logo / 产品名称；
2. 全局系统入口；
3. 当前系统高亮；
4. 指数行情条；
5. 当前时间；
6. 交易状态；
7. 数据状态；
8. 用户入口。

### 5.2 禁止事项

`TopMarketBar` 中禁止塞入个股详情页局部信息：

1. 禁止放入个股名称；
2. 禁止放入个股代码；
3. 禁止放入个股最新价；
4. 禁止放入个股涨跌幅；
5. 禁止放入前复权 / 不复权 / 后复权；
6. 禁止放入图表周期切换；
7. 禁止放入股票资料 / 诊股 / 设置；
8. 禁止为个股详情页单独重写 Logo、系统入口、指数行情条、交易状态、数据状态。

### 5.3 与 StockDetailHeader 的关系

`StockDetailHeader` 不应存在为一个新的顶部全局栏。

如果旧实现或旧文档存在 `StockDetailHeader`，处理方式为：

```text
StockDetailHeader = 废弃
TopMarketBar = 全局复用
StockBreadcrumb + ChartWorkspaceToolbar = 页面内部结构
```

## 6. StockBreadcrumb

| 项 | 说明 |
|---|---|
| 组件名称 | `StockBreadcrumb` |
| 中文名 | 个股详情路径面包屑 |
| 所属层级 | 页面内部导航组件 |
| 组件用途 | 显示个股详情页在财势乾坤系统内的路径位置。 |
| 使用页面 | 个股详情页 P0。 |
| 是否 P0 必需 | 是。 |
| 输入字段 / Props 摘要 | `items`、`stockName`、`stockCode`、`onItemClick`。 |
| 状态 | `default`、`hover`、`current`、`disabled`。不需要 loading。 |
| 交互 | 可点击上级路径；当前项不可点击或点击刷新当前页。 |
| Design Token 映射 | `--cs-stock-breadcrumb-height`、`--cs-color-text-muted`、`--cs-color-text-primary`、`--cs-color-border-subtle`。 |
| 禁止误用 | 不得放前复权、更新时间、刷新、READY；不得承担图表控制职责。 |

示例：

```text
财势乾坤 / 乾坤行情 / 个股详情 / 福斯特 603806.SH
```

Props 建议：

```ts
interface StockBreadcrumbProps {
  items: Array<{
    key: string;
    label: string;
    route?: string;
    current?: boolean;
    clickable?: boolean;
  }>;
  stockName: string;
  stockCode: string;
  onItemClick?: (itemKey: string) => void;
}
```

错误示例：

```text
财势乾坤 / 乾坤行情 / 个股详情 / 福斯特 603806.SH / 前复权 / READY
```

错误原因：Breadcrumb 只显示路径，不能混入图表控制或数据状态。

## 7. ChartWorkspaceToolbar

| 项 | 说明 |
|---|---|
| 组件名称 | `ChartWorkspaceToolbar` |
| 中文名 | 图表工作区工具栏 |
| 所属层级 | 个股详情页业务组件 / 图表工作区上下文组件 |
| 组件用途 | 作为红框区域核心组件，承载股票识别、周期切换、前复权、股票资料、诊股、设置。 |
| 使用页面 | 个股详情页 P0。 |
| 是否 P0 必需 | 是。 |
| 输入字段 / Props 摘要 | `stockIdentity`、`periodTabs`、`activePeriod`、`adjustType`、`rightActions`、`diagnosisDisabled`、事件回调。 |
| 状态 | `default`、`hover`、`selectedPeriod`、`disabledAction`、`loadingIdentity`。 |
| 交互 | 切换周期、切换复权类型、进入股票资料页、诊股 disabled 提示、打开图表设置 Toast。 |
| Design Token 映射 | `--cs-chart-workspace-toolbar-height`、`--cs-chart-workspace-toolbar-bg`、`--cs-chart-workspace-toolbar-border`、`--cs-chart-period-tab-*`、`--cs-chart-action-*`。 |
| 禁止误用 | 不是全局 Header；不显示更新时间、刷新、READY；不替代右侧 StockHeaderPanel。 |

结构：

```text
ChartWorkspaceToolbar
├── leftIdentity
│   ├── stockName
│   ├── stockCode
│   ├── industryTag
│   └── secondaryText
├── periodTabs
│   ├── 分时
│   ├── 日K
│   ├── 周K
│   ├── 月K
│   ├── 120分
│   ├── 90分
│   ├── 60分
│   ├── 30分
│   ├── 15分
│   ├── 5分
│   └── 1分
└── rightActions
    ├── AdjustTypeSelect
    ├── StockProfileButton
    ├── DiagnosisButton
    └── ChartSettingButton
```

Props 建议：

```ts
interface ChartWorkspaceToolbarProps {
  stockIdentity: {
    stockName: string;
    stockCode: string;
    industryName?: string;
    secondaryText?: string;
  };
  periodTabs: Array<{
    key: 'time' | 'day' | 'week' | 'month' | '120m' | '90m' | '60m' | '30m' | '15m' | '5m' | '1m';
    label: string;
    disabled?: boolean;
  }>;
  activePeriod: 'time' | 'day' | 'week' | 'month' | '120m' | '90m' | '60m' | '30m' | '15m' | '5m' | '1m';
  adjustType: 'qfq' | 'none' | 'hfq';
  diagnosisDisabled?: boolean;
  onPeriodChange?: (period: string) => void;
  onAdjustTypeChange?: (adjustType: 'qfq' | 'none' | 'hfq') => void;
  onStockProfileClick?: () => void;
  onDiagnosisClick?: () => void;
  onChartSettingClick?: () => void;
}
```

视觉与布局规则：

1. `ChartWorkspaceToolbar` 紧接 `StockBreadcrumb` 下方。
2. 它与 K 线主图形成视觉连续区域。
3. 高度必须克制，避免再次形成头重脚轻。
4. 左侧 `leftIdentity` 不应重复右侧 `StockHeaderPanel` 的全部行情信息，只表达图表上下文。
5. 中间 `periodTabs` 是主要交互区，默认 `日K` 选中。
6. 右侧 `rightActions` 顺序固定：`前复权 / 股票资料 / 诊股 / 设置`。
7. 不显示 `更新时间`、`刷新`、`READY`。
8. 不显示图表区顶部右上额外价格 / 涨幅块。

## 8. StockChartToolbar 合并 / 重命名规则

如果旧文档或旧实现中存在 `StockChartToolbar`，本轮处理方式为：

```text
StockChartToolbar → 合并 / 重命名为 ChartWorkspaceToolbar
```

原因：

1. `ChartWorkspaceToolbar` 更准确表达其作为图表工作区顶部上下文栏的定位；
2. 它不仅承载周期切换，也承载股票识别、复权、资料、诊股、设置；
3. 它不是全局 Header，也不是独立绿色框控制行。

兼容策略：

```ts
// 可选过渡期兼容，不建议长期保留
export const StockChartToolbar = ChartWorkspaceToolbar;
```

但组件规范主名必须使用：

```text
ChartWorkspaceToolbar
```

## 9. AdjustTypeSelect

| 项 | 说明 |
|---|---|
| 组件名称 | `AdjustTypeSelect` |
| 中文名 | 复权类型选择器 |
| 所属层级 | 图表工作区操作组件 |
| 组件用途 | 在图表工作区右侧切换或展示复权类型。 |
| 使用页面 | 个股详情页 P0。 |
| 是否 P0 必需 | 是，P0 可先 Mock。 |
| Props 摘要 | `value`、`options`、`disabled`、`onChange`。 |
| 状态 | `default`、`hover`、`active`、`disabled`、`mock`。 |
| 交互 | 点击展开复权选项；P0 如未接真实切换，可 Toast 或本地 Mock 切换。 |
| 禁止误用 | 不得放在 Breadcrumb；不得作为独立控制行；不得放入 TopMarketBar。 |

Props 建议：

```ts
interface AdjustTypeSelectProps {
  value: 'qfq' | 'none' | 'hfq';
  options: Array<{
    label: '前复权' | '不复权' | '后复权';
    value: 'qfq' | 'none' | 'hfq';
    disabled?: boolean;
  }>;
  disabled?: boolean;
  onChange?: (value: 'qfq' | 'none' | 'hfq') => void;
}
```

默认展示：

```text
前复权
```

## 10. StockProfileButton

| 项 | 说明 |
|---|---|
| 组件名称 | `StockProfileButton` |
| 中文名 | 股票资料按钮 |
| 所属层级 | 图表工作区操作组件 |
| 组件用途 | 进入独立股票资料页。 |
| 使用页面 | 个股详情页 P0。 |
| 是否 P0 必需 | 是。 |
| Props 摘要 | `enabled`、`route`、`onClick`。 |
| 状态 | `default`、`hover`、`active`、`disabled`。 |
| 禁止误用 | 不得在 P0 中实现为同花顺 F10；不得放入 TopMarketBar。 |

## 11. DiagnosisButton

| 项 | 说明 |
|---|---|
| 组件名称 | `DiagnosisButton` |
| 中文名 | 诊股按钮 |
| 所属层级 | 图表工作区操作组件 |
| 组件用途 | 暂时作为诊股能力入口占位。 |
| 使用页面 | 个股详情页 P0。 |
| 是否 P0 必需 | 是，但 P0 disabled。 |
| Props 摘要 | `disabled`、`disabledReason`、`onClick`。 |
| 状态 | `disabled` 固定；hover 可展示原因。 |
| 禁止误用 | P0 不输出诊股结论，不输出买卖建议，不请求诊股 API。 |

默认状态：

```text
诊股 disabled
```

点击或 hover 提示：

```text
诊股暂未开通
```

## 12. ChartSettingButton

| 项 | 说明 |
|---|---|
| 组件名称 | `ChartSettingButton` |
| 中文名 | 图表设置按钮 |
| 所属层级 | 图表工作区操作组件 |
| 组件用途 | 作为图表 / 指标设置入口。 |
| 使用页面 | 个股详情页 P0。 |
| 是否 P0 必需 | 是。 |
| Props 摘要 | `enabled`、`onClick`。 |
| 状态 | `default`、`hover`、`active`、`disabled`。 |
| 交互 | P0 点击后 Toast：`指标设置暂未开通`。 |
| 禁止误用 | 不得修改 MA/BOLL 切换规则；不得在本轮新增复杂指标设置面板。 |

## 13. 废弃组件 / 元素清单

以下组件或元素在个股详情页顶部结构中废弃：

| 废弃项 | 废弃原因 | 替代方式 |
|---|---|---|
| `StockDetailHeader` | 不允许为个股详情页创建新的全局顶部栏 | 复用 `TopMarketBar` |
| `BreadcrumbActionBar` 作为混合控制栏 | Breadcrumb 只能显示路径，不能混合控制项 | 拆分为 `StockBreadcrumb` + `ChartWorkspaceToolbar` |
| `StockChartToolbar` 作为主名 | 语义不完整 | 合并 / 重命名为 `ChartWorkspaceToolbar` |
| `StockDetailUpdateTime` | 顶部独立更新时间占用高度，本轮删除 | 由全局数据状态或后续局部说明处理；P0 不单独展示 |
| `StockDetailRefreshButton` | 本轮删除独立刷新 | P0 不单独展示 |
| `StockDetailReadyStatus` | 本轮删除 READY 独立状态 | 全局数据状态由 `TopMarketBar` 表达 |
| `IndependentStockDetailControlBar` | 绿色框独立控制行无效 | 删除；控制项并入 `ChartWorkspaceToolbar` |
| `ChartTopRightPriceBlock` | 图表区不重复展示个股价格 / 涨幅 | 价格归属右侧 `StockHeaderPanel` 或行情信息区 |
| 绿色框独立占位行 | 造成头重脚轻和无效高度 | 删除 |

## 14. 本轮未修改组件清单

本轮不修改以下组件与规则：

1. `StockKlinePanel`；
2. `MacdPanel`；
3. `VolumePanel`；
4. `KdjPanel`；
5. `ChartPanelHeaderInfo`；
6. `ChartCrosshairLayer`；
7. `ChartYAxis` / `ChartDualYAxis` / `ChartAxisTickLabel`；
8. `ChartTimeAxis` / `ChartTimeTickLabel`；
9. `ChartAxisFloatLabel`；
10. `KlineTooltip`；
11. `IndicatorToolbar`；
12. `MainOverlayIndicatorMenu`；
13. MA / BOLL 切换；
14. `StockHeaderPanel`；
15. `StockSideTabs`；
16. `RelatedSectorTable`；
17. `StockMoneyFlowPanel`；
18. 资料 Tab `暂未开通`；
19. 诊股 disabled 业务状态；
20. API 字段和数据结构；
21. 红涨绿跌规则；
22. 固定视口 `100vh` / `min-height: 0` / 禁止整页滚动规则。

```text
本轮因 Review v2 修改而被动影响的区域：
- StockDetailPage 顶部结构
- StockDetailFixedLayout 顶部扣减高度变量
原因：删除独立控制行，并将 ChartWorkspaceToolbar 作为主内容区上方的唯一图表工作区控制栏
是否需要产品总控确认：否，Review v2 已明确该处理方向；02 需要在 stock-detail-v1.2.html 中验证顶部有效高度是否改善
```

## 15. 对 02 `stock-detail-v1.2.html` 的组件使用建议

02 Showcase 必须按以下结构实现：

```text
TopMarketBar
StockBreadcrumb
ChartWorkspaceToolbar
StockDetailFixedLayout
```

具体要求：

1. `TopMarketBar` 直接复用市场总览同款样式和结构。
2. `StockBreadcrumb` 只显示：`财势乾坤 / 乾坤行情 / 个股详情 / 福斯特 603806.SH`。
3. 删除绿色框独立控制行，不保留等高空白。
4. `ChartWorkspaceToolbar` 紧接 `StockBreadcrumb` 下方。
5. `ChartWorkspaceToolbar.leftIdentity` 展示股票名称、代码、行业标签、副说明。
6. `ChartWorkspaceToolbar.periodTabs` 展示：`分时 / 日K / 周K / 月K / 120分 / 90分 / 60分 / 30分 / 15分 / 5分 / 1分`。
7. `ChartWorkspaceToolbar.rightActions` 展示：`前复权 / 股票资料 / 诊股 / 设置`。
8. `前复权` 不得出现在 Breadcrumb 或独立行中。
9. 删除 `更新时间`、`刷新`、`READY`。
10. 不显示 `ChartTopRightPriceBlock`。
11. 不修改 K 线、MACD、成交量、KDJ、Tooltip、坐标轴、右侧信息栏等未点名组件。
12. 保持固定视口，不启用整页滚动。

## 16. 对 01 Design Token 的依赖

本轮依赖 01 已补充或确认以下 Token 方向：

1. `TopMarketBar` 继续复用市场总览全局顶部栏 Token；
2. `StockBreadcrumb` 的轻量路径行高度、背景、边框、文字层级；
3. `ChartWorkspaceToolbar` 的高度、背景、边框、间距；
4. `leftIdentity` 的股票名称、代码、行业标签、副说明文字层级；
5. `periodTabs` 的 default / hover / active / selected / disabled 状态；
6. `rightActions` 的 `AdjustTypeSelect`、`StockProfileButton`、`DiagnosisButton`、`ChartSettingButton` 状态；
7. 删除独立控制行后的顶部垂直节奏；
8. 主内容区高度扣减变量从旧 `BreadcrumbActionBar + ChartToolbar` 调整为 `StockBreadcrumb + ChartWorkspaceToolbar`。

如 01 文档未列出具体 Token 名称，02 可先基于现有 `--cs-*` 体系实现，但不得硬编码与主题冲突的颜色。

## 17. 待产品总控确认问题

1. `StockChartToolbar` 是否允许在代码中过渡期保留为 `ChartWorkspaceToolbar` 的 alias？当前建议允许短期兼容，但文档主名统一为 `ChartWorkspaceToolbar`。
2. `ChartWorkspaceToolbar.leftIdentity.secondaryText` 是否固定为 `乾坤行情 / 个股详情 / P0 Mock 行情`，还是由 02 Showcase 临时决定？
3. `前复权` 下拉是否在 P0 允许真实切换 Mock 数据，还是只展示不改变数据？当前建议允许本地 Mock 切换。
4. `设置` 按钮点击是否统一 Toast：`指标设置暂未开通`？当前建议继续沿用该行为。
5. 删除 `更新时间 / 刷新 / READY` 后，是否需要在右侧信息栏或 Tooltip 中保留局部更新时间？当前 Review v2 要求顶部不显示，后续可另行确认。

## 18. 本轮输出文件下载链接

本轮输出文件名：

```text
04-component-guidelines.md
```

下载链接由本轮对话附件提供。

建议放置到 Google Drive：

```text
财势乾坤/设计/04-component-guidelines.md
```

---

# 个股详情页局部组件精修规则（Stock Detail Review v3）

> 本节为 `stock-detail-html-review-v3-总控解读与变更单.md` 的组件级合并内容。它不替代前文已确认的个股详情页固定视口、顶部结构、图表区、右侧信息栏、十字线、Tooltip、坐标轴、Header Info 等规范，而是在完整保留此前内容的基础上，只补充本轮 Review v3 明确点名的 3 个局部修正规则：  
> 1. `ChartWorkspaceToolbar` 中股票识别区与周期切换区距离收紧；  
> 2. `StockHeaderPanel` 紧凑化；  
> 3. `KlineViewportState.defaultVisibleCount = 144`。  
> 本节不修改 `TopMarketBar`、`StockBreadcrumb`、已删除绿色框独立行的结构、`AdjustTypeSelect` / `StockProfileButton` / `DiagnosisButton` 的业务规则、K 线绘制、副图、坐标轴、时间轴、十字线、Tooltip、Header Info、MA/BOLL、右侧 Tab、关联板块、资金统计图、API 字段和数据结构。

## 1. 本轮 Review v3 修改摘要

本轮只处理个股详情页局部组件密度与默认视窗配置，不重做页面整体结构。

| 修改项 | 处理结论 | 影响组件 |
|---|---|---|
| 股票识别区与周期切换区距离过大 | 收紧两者间距，必须相邻，避免被 `space-between` 拉开 | `ChartWorkspaceToolbar`、`StockIdentityInline`、`PeriodSwitchGroup` |
| 右侧 StockHeader 偏高 | 启用紧凑版，减少内边距、行距和信息堆叠高度，使下方按钮、Tab、盘口摘要、关联板块整体上移 | `StockHeaderPanel` |
| K 线默认展示根数未明确 | 新增 `KlineViewportState`，默认最多展示 144 根当前周期 K 线，锚定最新 K 线 | `StockKlinePanel`、`KlineViewportState` |
| 鼠标右键拖拽 / 平移 / 缩放 | 本轮明确不实现 | 不涉及 |
| API 字段 | 本轮不修改 API 契约 | 不涉及 04 |

必须保持的既有基线：

1. 个股详情页最顶部仍复用市场总览同款 `TopMarketBar`。
2. `StockBreadcrumb` 只显示路径。
3. 绿色框独立控制行已经删除，不得恢复。
4. `ChartWorkspaceToolbar` 仍为图表工作区顶部唯一控制栏。
5. `前复权` 仍位于 `ChartWorkspaceToolbar` 右侧。
6. 不显示更新时间、刷新、READY。
7. 页面仍采用固定视口交易终端布局：`height: 100vh`，不使用 body 级整页滚动。
8. 中国市场红涨绿跌，不输出买卖建议，不展示诊股结论。

---

## 2. 本轮新增或修订组件清单

| 类型 | 组件 / 规则 | 处理方式 |
|---|---|---|
| 修订 | `ChartWorkspaceToolbar` | 收紧 `StockIdentityInline` 与 `PeriodSwitchGroup` 的距离；右侧 `StockToolbarActions` 仍靠右。 |
| 新增 / 修订 | `StockIdentityInline` | 定义股票名称、代码、弱行业标签 / 副说明的紧凑展示规则。 |
| 新增 / 修订 | `PeriodSwitchGroup` | 定义周期集合单行、不换行、不隐藏默认周期项，并与股票识别区紧凑相邻。 |
| 新增 / 修订 | `StockToolbarActions` | 定义右侧操作区：前复权 / 股票资料 / 诊股 / 设置；不显示更新时间、刷新、READY。 |
| 修订 | `StockHeaderPanel` | 定义右侧 StockHeader 紧凑版布局，保留关键信息和操作按钮。 |
| 修订 | `StockKlinePanel` 默认 viewport 配置 | 默认接收 `KlineViewportState`，最多展示 144 根当前周期 K 线。 |
| 新增 | `KlineViewportState` | 定义默认视窗状态：`defaultVisibleCount=144`、`anchor='latest'`。 |

---

## 3. ChartWorkspaceToolbar：紧凑相邻布局规则

| 项 | 说明 |
|---|---|
| 组件名称 | `ChartWorkspaceToolbar` |
| 中文名 | 图表工作区顶部栏 |
| 组件用途 | 个股详情页图表工作区顶部唯一控制栏，承载股票识别、周期切换和右侧图表/页面操作。 |
| 使用页面 | 个股详情页 P0。 |
| 本轮修订重点 | 收紧 `StockIdentityInline` 与 `PeriodSwitchGroup` 之间的距离，使二者视觉上连续，不再被横向大空白拉开。 |
| 内部结构 | `StockIdentityInline` + `PeriodSwitchGroup` + `StockToolbarActions`。 |
| 禁止布局 | 禁止使用 `justify-content: space-between` 直接把股票识别区和周期切换区分推到两端。 |
| 允许布局 | 可使用左侧组合容器 + 右侧 actions 容器：左侧组合内部紧凑排列，右侧 actions `margin-left:auto` 靠右。 |
| 周期按钮 | 单行展示，不换行，不隐藏默认周期项。 |
| 右侧操作 | `StockToolbarActions` 可以靠右展示。 |
| 空间不足策略 | 优先保持 `StockIdentityInline` 与 `PeriodSwitchGroup` 相邻；弱说明可隐藏；周期组可横向压缩或内部横向滚动，但不得换行。 |
| 禁止内容 | 不显示更新时间、不显示刷新、不显示 READY，不恢复绿色框独立行。 |
| 关联 Token | `--cs-stock-detail-chart-toolbar-*`、`--cs-stock-detail-toolbar-identity-gap`、`--cs-stock-detail-toolbar-period-gap`、`--cs-stock-detail-toolbar-actions-gap`。 |

### 3.1 推荐结构

```text
ChartWorkspaceToolbar
├── leftCluster
│   ├── StockIdentityInline
│   └── PeriodSwitchGroup
└── StockToolbarActions
```

推荐 CSS 结构：

```css
.stock-chart-workspace-toolbar {
  display: flex;
  align-items: center;
  gap: var(--cs-stock-detail-toolbar-main-gap, 12px);
  min-width: 0;
}

.stock-chart-workspace-toolbar__left-cluster {
  display: flex;
  align-items: center;
  gap: var(--cs-stock-detail-toolbar-identity-period-gap, 12px);
  min-width: 0;
  flex: 0 1 auto;
}

.stock-chart-workspace-toolbar__actions {
  margin-left: auto;
  flex: 0 0 auto;
}
```

明确禁止：

```css
.stock-chart-workspace-toolbar {
  justify-content: space-between; /* 禁止直接用于三组整体布局 */
}
```

如果工程确实需要使用 `space-between`，必须只作用于“左侧组合容器”和“右侧操作区”之间，不得作用于 `StockIdentityInline` 与 `PeriodSwitchGroup` 之间。

### 3.2 Props 建议

```ts
interface ChartWorkspaceToolbarProps {
  identity: StockIdentityInlineProps;
  periods: PeriodSwitchGroupProps;
  actions: StockToolbarActionsProps;
  density?: 'compact' | 'normal';
  lowWidthMode?: boolean;
}
```

### 3.3 状态

| 状态 | 规则 |
|---|---|
| default | 股票识别区、周期切换区紧凑相邻；右侧操作区靠右。 |
| hover | 只高亮被 hover 的按钮或可交互元素，不让整条 toolbar 大面积高亮。 |
| active | 按钮或周期项按下态压暗。 |
| selected | 当前周期项 selected；不把整个 toolbar 标为 selected。 |
| disabled | 只禁用对应操作项，不禁用整个 toolbar。 |
| loading | 周期数据切换时可在图表区局部 loading，不建议 toolbar 整体 skeleton。 |
| empty | 不适用；股票识别区缺失时由页面错误态处理。 |
| error | 不在 toolbar 内显示全局错误，错误交由图表或页面状态处理。 |

---

## 4. StockIdentityInline

| 项 | 说明 |
|---|---|
| 组件名称 | `StockIdentityInline` |
| 中文名 | 行内股票识别区 |
| 组件用途 | 在 `ChartWorkspaceToolbar` 左侧紧凑展示当前股票名称、代码和弱化行业 / 副说明。 |
| 使用页面 | 个股详情页 P0。 |
| 是否 P0 必需 | 是。 |
| 输入字段 / Props | `stockName`、`stockCode`、`industryName`、`secondaryText`、`compact`。 |
| 视觉结构 | 股票名称 + 股票代码为一组；行业标签或副说明弱化展示。 |
| 空间约束 | 不应占用过大横向空间；不得把周期切换区推得过远。 |
| 空间不足策略 | 优先保留股票名称和代码；隐藏 `secondaryText`；行业标签可缩短或省略。 |
| 交互 | 默认不可点击；如需要点击进入股票资料，应由 `StockProfileButton` 承担，不由本组件承担。 |
| 涨跌色规则 | 不承载涨跌色；股票名称、代码和行业标签使用中性色。 |
| 关联 Token | `--cs-stock-detail-toolbar-identity-*`、`--cs-color-text-primary`、`--cs-color-text-secondary`、`--cs-color-text-muted`。 |

```ts
interface StockIdentityInlineProps {
  stockName: string;
  stockCode: string;
  industryName?: string;
  secondaryText?: string;
  compact?: boolean;
  hideSecondaryWhenNarrow?: boolean;
}
```

### 4.1 展示规则

推荐展示：

```text
福斯特 603806.SH 光伏设备
```

或在空间允许时：

```text
福斯特 603806.SH 光伏设备 · P0 Mock 行情
```

规则：

1. `stockName` 为主识别字段，视觉权重最高。
2. `stockCode` 紧随股票名称展示，不另起一大块区域。
3. `industryName` / `secondaryText` 使用弱文字或弱标签。
4. 不显示更新时间、刷新、READY。
5. 不显示最新价、涨跌幅；这些归属右侧 `StockHeaderPanel` 或图表 Tooltip，不放入本组件。

---

## 5. PeriodSwitchGroup

| 项 | 说明 |
|---|---|
| 组件名称 | `PeriodSwitchGroup` |
| 中文名 | 周期切换组 |
| 组件用途 | 在 `ChartWorkspaceToolbar` 中展示分时和 K 线周期集合。 |
| 使用页面 | 个股详情页 P0。 |
| 是否 P0 必需 | 是。 |
| 输入字段 / Props | `periods`、`activePeriod`、`onPeriodChange`、`density`、`nowrap`。 |
| 默认选中 | `日K` / `period='day'`。 |
| 展示规则 | 单行展示，不换行，不隐藏默认周期项。 |
| 与股票识别区关系 | 必须与 `StockIdentityInline` 紧凑相邻，中间只保留必要 gap。 |
| 空间不足策略 | 保持单行；可压缩按钮 padding；可允许当前组内部横向滚动；不得换行。 |
| 禁止 | 不得被布局推到页面正中或远离股票识别区。 |
| 关联 Token | `--cs-stock-detail-period-tab-*`、`--cs-stock-detail-toolbar-period-gap`、`--cs-color-brand-accent`。 |

```ts
interface PeriodSwitchGroupProps {
  periods: Array<{
    key: KlinePeriod;
    label: string;
    enabled: boolean;
  }>;
  activePeriod: KlinePeriod; // default: 'day'
  density?: 'compact' | 'normal';
  nowrap?: true;
  onPeriodChange?: (period: KlinePeriod) => void;
}
```

必须展示周期集合：

```text
分时 / 日K / 周K / 月K / 120分 / 90分 / 60分 / 30分 / 15分 / 5分 / 1分
```

状态规则：

| 状态 | 规则 |
|---|---|
| default | 周期项紧凑排列。 |
| hover | 单个周期项弱高亮。 |
| active | 点击压暗。 |
| selected | 当前周期使用品牌金弱背景 / 下划线 / 边框。 |
| disabled | 未支持周期置灰，但仍保留位置。 |
| loading | 周期切换后图表区 loading，不建议周期组本身 loading。 |
| empty/error | 不适用。 |

---

## 6. StockToolbarActions

| 项 | 说明 |
|---|---|
| 组件名称 | `StockToolbarActions` |
| 中文名 | 个股图表工具栏右侧操作区 |
| 组件用途 | 在 `ChartWorkspaceToolbar` 右侧承载前复权、股票资料、诊股、设置。 |
| 使用页面 | 个股详情页 P0。 |
| 是否 P0 必需 | 是。 |
| 输入字段 / Props | `adjustType`、`profileEnabled`、`diagnosisEnabled`、`settingEnabled`、`onAdjustTypeChange`、`onProfileClick`、`onDiagnosisClick`、`onSettingClick`。 |
| 布局 | 靠右展示，`margin-left:auto`。 |
| 包含项 | `前复权 / 股票资料 / 诊股 / 设置`。 |
| 禁止项 | 不显示更新时间；不显示刷新；不显示 READY。 |
| 业务规则 | `AdjustTypeSelect`、`StockProfileButton`、`DiagnosisButton`、`ChartSettingButton` 的既有业务规则不变。 |
| 关联 Token | `--cs-stock-detail-toolbar-actions-*`、`--cs-color-brand-accent`、`--cs-color-text-secondary`。 |

```ts
interface StockToolbarActionsProps {
  adjustType: 'none' | 'qfq' | 'hfq';
  profileEnabled?: boolean;
  diagnosisEnabled?: boolean; // P0 false
  settingEnabled?: boolean;
  onAdjustTypeChange?: (adjustType: 'none' | 'qfq' | 'hfq') => void;
  onProfileClick?: () => void;
  onDiagnosisClick?: () => void;
  onSettingClick?: () => void;
}
```

实现要求：

1. `前复权` 作为 `AdjustTypeSelect` 展示在右侧操作区。
2. `股票资料` 点击进入完整股票资料页或保留路由入口。
3. `诊股` P0 disabled，业务规则不变。
4. `设置` 点击沿用既有 Toast 或设置入口规则。
5. 不恢复任何独立控制行。
6. 不增加更新时间、刷新、READY。

---

## 7. StockHeaderPanel：紧凑版

| 项 | 说明 |
|---|---|
| 组件名称 | `StockHeaderPanel` |
| 中文名 | 个股右侧头部行情面板 |
| 本轮修订 | 增加 `compact` 变体，压缩高度、内边距和行间距，使下方按钮、盘口 Tab、盘口摘要、关联板块整体上移。 |
| 使用页面 | 个股详情页右侧信息栏 P0。 |
| 是否 P0 必需 | 是。 |
| 不改变内容 | 仍保留股票名称、代码、行业 / 题材标签、最新价、涨跌额、涨跌幅、自选、提醒、交易计划、诊股。 |
| 不改变业务结构 | 不修改右侧栏结构，不删除按钮，不改变诊股 disabled 业务规则。 |
| 视觉目标 | 高密度、低高度、价格与涨跌信息清晰，下方内容获得更多垂直空间。 |
| 关联 Token | `--cs-stock-header-compact-*`、`--cs-stock-header-padding-compact`、`--cs-stock-header-line-gap-compact`、`--cs-stock-header-price-size-compact`。 |

```ts
interface StockHeaderPanelProps {
  stockName: string;
  stockCode: string;
  latestPrice: number | null;
  changeAmount: number | null;
  changePct: number | null;
  direction: 'UP' | 'DOWN' | 'FLAT' | 'UNKNOWN';
  industryName?: string;
  sectorTags?: Array<{ key: string; label: string; route?: string }>;
  tradeStatus?: 'TRADING' | 'SUSPENDED' | 'CLOSED' | 'UNKNOWN';
  updateTime?: string;
  actions?: Array<{
    key: 'watchlist' | 'alert' | 'tradePlan' | 'diagnosis';
    label: string;
    enabled: boolean;
  }>;
  compact?: boolean; // Review v3 default true on stock-detail-v1.3.html
}
```

### 7.1 紧凑版布局建议

推荐压缩为 3 个紧凑区：

```text
StockHeaderPanel.compact
├── identityLine：股票名称 / 股票代码 / 行业或题材标签
├── priceLine：最新价 / 涨跌额 / 涨跌幅
└── actionLine：自选 / 提醒 / 交易计划 / 诊股
```

允许把行业 / 题材标签和股票代码压缩在第一行，减少垂直高度。

### 7.2 保留信息

必须保留：

1. 股票名称；
2. 股票代码；
3. 行业 / 题材标签；
4. 最新价；
5. 涨跌额；
6. 涨跌幅；
7. 自选；
8. 提醒；
9. 交易计划；
10. 诊股 disabled。

### 7.3 可压缩项

允许压缩：

1. 内边距；
2. 行间距；
3. 标签高度；
4. 按钮高度；
5. 价格区上下空白；
6. 操作按钮与价格区之间距离。

不允许：

1. 删除核心信息；
2. 删除自选 / 提醒 / 交易计划 / 诊股；
3. 改变右侧 `StockSideTabs` 结构；
4. 改变 `RelatedSectorTable` 字段；
5. 改变 `StockMoneyFlowPanel` 结构；
6. 将诊股从 disabled 改为 enabled；
7. 输出买卖建议。

### 7.4 红涨绿跌规则

| 字段 | 颜色规则 |
|---|---|
| `latestPrice` | 可按 `direction` 红涨绿跌，也可使用主文字色；需要与页面整体一致。 |
| `changeAmount` | 红涨绿跌。 |
| `changePct` | 红涨绿跌。 |
| `stockName` / `stockCode` | 中性。 |
| `industryName` / `sectorTags` | 中性或品牌弱强调。 |
| 操作按钮 | 中性 / 品牌色 / disabled 色，不使用涨跌红绿。 |

### 7.5 下方内容上移要求

`StockHeaderPanel.compact` 生效后，应使以下区域整体上移：

1. 自选 / 提醒 / 交易计划 / 诊股按钮行；
2. `StockSideTabs`；
3. 盘口摘要；
4. `RelatedSectorTable`；
5. `StockMoneyFlowPanel`。

这属于布局密度调整，不改变这些模块内部业务结构。

---

## 8. StockKlinePanel 默认 viewport 配置

| 项 | 说明 |
|---|---|
| 组件名称 | `StockKlinePanel` |
| 中文名 | 个股 K 线主图面板 |
| 本轮修订 | 增加默认视窗配置，默认最多展示 144 根当前周期 K 线。 |
| 是否改变绘制风格 | 否。本轮不修改 K 线绘制风格、K 线颜色、坐标轴、十字线、Tooltip、Header Info。 |
| 是否 P0 必需 | 是。 |
| 输入字段 / Props | `candles`、`period`、`viewportState`、`onViewportChange`。 |
| 默认 viewport | `defaultVisibleCount=144`、`anchor='latest'`。 |
| 数据不足 | `candles.length < 144` 时展示全部。 |
| 禁止交互 | 本轮不实现右键拖拽、横向平移历史窗口、缩放、滚轮缩放。 |

```ts
interface StockKlinePanelProps {
  candles: CandlePoint[];
  period: KlinePeriod;
  viewportState?: KlineViewportState;
  onViewportChange?: (state: KlineViewportState) => void;
}
```

### 8.1 默认可见数据计算

```ts
function getVisibleCandles(candles: CandlePoint[], viewport: KlineViewportState): CandlePoint[] {
  const visibleCount = Math.min(candles.length, viewport.visibleCount);
  if (viewport.anchor === 'latest') {
    return candles.slice(-visibleCount);
  }
  return candles.slice(-visibleCount);
}
```

注意：上方只是 Showcase / ViewModel 计算建议，不是图表引擎正式实现。

---

## 9. KlineViewportState

| 项 | 说明 |
|---|---|
| 组件 / 状态名 | `KlineViewportState` |
| 中文名 | K 线视窗状态 |
| 组件用途 | 描述当前 K 线主图默认可见数据范围，不改变数据源本身。 |
| 使用页面 | 个股详情页 K 线主图 P0。 |
| 是否 P0 必需 | 是，Review v3 点名。 |
| 是否 API 字段 | 否。它是前端视窗状态，不进入 API 契约。 |
| 默认可见根数 | `defaultVisibleCount = 144`。 |
| 当前可见根数 | `visibleCount` 默认等于 144。 |
| 锚定 | `anchor='latest'`，默认锚定最新 K 线。 |
| 周期 | 适用于所有周期：分时、1分、5分、15分、30分、60分、90分、120分、日K、周K、月K。 |
| 数据不足 | 少于 144 根时展示全部。 |
| 禁止本轮实现 | 右键拖拽、横向平移历史窗口、缩放、滚轮缩放、历史窗口拖动、惯性滚动。 |

```ts
interface KlineViewportState {
  period: KlinePeriod;
  visibleCount: number;
  defaultVisibleCount: 144;
  anchor: 'latest';
}
```

初始化建议：

```ts
const defaultKlineViewportState: KlineViewportState = {
  period: 'day',
  visibleCount: 144,
  defaultVisibleCount: 144,
  anchor: 'latest',
};
```

### 9.1 周期切换规则

当用户切换周期时：

1. `period` 更新为目标周期；
2. `visibleCount` 重置为 `144`；
3. `defaultVisibleCount` 仍为 `144`；
4. `anchor` 重置为 `latest`；
5. 图表展示该周期最近的最多 144 根 K 线；
6. 数据不足 144 根时展示全部；
7. 不保留上一周期的平移或缩放状态，因为本轮不支持平移和缩放。

### 9.2 分时周期说明

`period='time'` 时，`visibleCount=144` 仍作为默认视窗配置。由于分时数据点密度和 K 线数据可能不同，02 Showcase 可以使用模拟分时点，但组件规范仍要求最多展示 144 个当前周期点位或等价采样点。

### 9.3 与后续平移 / 缩放的边界

本轮明确不实现：

1. 右键拖拽；
2. 横向平移历史窗口；
3. 鼠标滚轮缩放；
4. 双指缩放；
5. 时间轴拖动；
6. 惯性滚动；
7. 历史窗口分页加载。

后续如需实现，应新增字段，例如：

```ts
interface KlineViewportStateFuture {
  startIndex?: number;
  endIndex?: number;
  scale?: number;
  panOffset?: number;
  anchor?: 'latest' | 'custom';
}
```

但这些字段不进入本轮规范。

---

## 10. 本轮未修改组件清单

以下组件保持前文规范，不做主动改动：

1. `TopMarketBar`；
2. `StockBreadcrumb`；
3. 已删除绿色框独立行的结构；
4. `AdjustTypeSelect` 的业务规则；
5. `StockProfileButton` 的业务规则；
6. `DiagnosisButton` 的 disabled 业务规则；
7. K 线主图绘制组件；
8. `MacdPanel`；
9. `VolumePanel`；
10. `KdjPanel`；
11. `ChartYAxis`；
12. `ChartDualYAxis`；
13. `ChartAxisTickLabel`；
14. `ChartTimeAxis`；
15. `ChartTimeTickLabel`；
16. `ChartCrosshairLayer`；
17. `ChartAxisFloatLabel`；
18. `KlineTooltip`；
19. `ChartPanelHeaderInfo`；
20. `MainOverlayIndicatorMenu`；
21. MA / BOLL 切换规则；
22. `IndicatorToolbar`；
23. `StockSideTabs`；
24. `RelatedSectorTable`；
25. `StockMoneyFlowPanel`；
26. 资料 Tab 占位；
27. 诊股 disabled；
28. API 字段和数据结构。

---

## 11. 对 02 `stock-detail-v1.3.html` 的组件使用建议

1. 保持最顶部复用市场总览同款 `TopMarketBar`，不改。
2. 保持 `StockBreadcrumb` 只显示路径，且不恢复前复权、更新时间、刷新、READY。
3. 保持绿色框独立控制行已删除，不恢复任何占位行。
4. `ChartWorkspaceToolbar` 内部必须使用 `leftCluster + actions` 布局。
5. `leftCluster` 内部必须让 `StockIdentityInline` 与 `PeriodSwitchGroup` 紧凑相邻。
6. 不要使用会把股票识别区和周期切换区拉开的 `justify-content: space-between`。
7. `StockToolbarActions` 靠右显示，包含前复权 / 股票资料 / 诊股 / 设置。
8. 周期按钮集合必须单行展示，不换行，不隐藏默认周期项。
9. 空间不足时，优先隐藏 `StockIdentityInline.secondaryText`，不要把周期组推远。
10. 右侧 `StockHeaderPanel` 使用 `compact=true`，压缩内边距、行距和标签高度。
11. 右侧下方按钮、盘口 Tab、盘口摘要、关联板块和资金统计整体上移。
12. 不改变 `StockSideTabs`、`RelatedSectorTable`、`StockMoneyFlowPanel` 内部结构。
13. K 线主图默认只展示最近最多 144 根当前周期 K 线。
14. 数据不足 144 根时展示全部数据。
15. 默认锚定最新 K 线，右侧对齐最新数据。
16. 本轮不要实现右键拖拽、横向平移、缩放、滚轮缩放。
17. 不修改 K 线绘制风格、MACD、成交量、KDJ、坐标轴、时间轴、十字线、Tooltip、Header Info 和 MA/BOLL。
18. 不修改 API 字段和 Mock 数据结构，除非是前端本地 viewport 配置。

---

## 12. 对 01 Design Token 的依赖

本轮依赖 `03-design-tokens.md` 的个股详情 Review v3 相关 Token 或等价变量，重点包括：

| Token / 规则 | 用途 |
|---|---|
| `--cs-stock-detail-toolbar-identity-period-gap` | 股票识别区与周期切换区之间的紧凑间距。 |
| `--cs-stock-detail-toolbar-main-gap` | Toolbar 内部主 gap。 |
| `--cs-stock-detail-toolbar-actions-gap` | 右侧操作按钮间距。 |
| `--cs-stock-detail-period-tab-padding-x-compact` | 周期按钮紧凑内边距。 |
| `--cs-stock-detail-period-tab-gap-compact` | 周期按钮之间的紧凑间距。 |
| `--cs-stock-detail-identity-secondary-display-threshold` | 弱说明隐藏阈值或策略。 |
| `--cs-stock-header-padding-compact` | 右侧 StockHeader 紧凑版内边距。 |
| `--cs-stock-header-line-gap-compact` | StockHeader 行间距。 |
| `--cs-stock-header-price-size-compact` | 最新价字号。 |
| `--cs-stock-header-action-gap-compact` | 自选 / 提醒 / 交易计划 / 诊股按钮间距。 |
| `--cs-stock-kline-default-visible-count` | 可选 Token，建议值 144，用于文档化默认视窗数量；不作为视觉色值。 |

实现要求：

1. 组件层只引用 Token，不硬编码大量尺寸。
2. `KlineViewportState.defaultVisibleCount = 144` 是行为配置，不是纯视觉 Token。
3. 如果 Token 尚未落地，02 Showcase 可使用 CSS 变量 fallback，但最终工程应回收至 `03-design-tokens.md`。
4. 本轮不得修改 TopMarketBar、StockBreadcrumb、坐标轴、Tooltip、右侧 Tab、资金图等未点名组件的 Token 使用方式。

---

## 13. 是否需要后续拉 04 参与的条件

本轮 04 不参与。

原因：

1. `ChartWorkspaceToolbar` 紧凑化是布局问题；
2. `StockHeaderPanel.compact` 是视觉密度问题；
3. `KlineViewportState.defaultVisibleCount=144` 是前端视窗状态配置；
4. 不涉及 K 线接口字段变更；
5. 不涉及指标、资金、关联板块数据结构；
6. 不涉及 API response 变更。

后续只有在以下场景出现时，才需要拉 04 参与：

| 条件 | 是否需要 04 | 原因 |
|---|---:|---|
| 需要服务端分页返回 K 线窗口 | 是 | 需要定义 `limit`、`endTime`、`anchor` 等接口参数。 |
| 需要右键拖拽平移历史窗口并动态加载更早 K 线 | 是 | 需要历史分页和边界处理 API。 |
| 需要缩放后按不同 visibleCount 请求数据 | 是 | 需要明确前后端视窗策略。 |
| 当前接口默认返回不足 144 根且无法补足 | 可能 | 需要确认 `limit` 默认值。 |
| 仅前端从已加载 candles 中取最近 144 根 | 否 | 属于前端 ViewModel / Chart viewport 配置。 |

---

## 14. 待产品总控确认问题

1. `StockIdentityInline` 与 `PeriodSwitchGroup` 之间的推荐间距是否固定为 12px，还是允许 8–16px 自适应？当前建议 12px，窄屏 8px。
2. `StockIdentityInline.secondaryText` 是否默认显示 `行业标签`，还是默认隐藏，只保留股票名称与代码？当前建议显示弱行业标签，空间不足时隐藏。
3. `PeriodSwitchGroup` 在 1440px 宽度下如果按钮过多，是否允许内部横向滚动？当前建议允许，但不换行、不隐藏日K。
4. `StockHeaderPanel.compact` 中行业 / 题材标签最多展示几个？当前建议最多 2 个，更多 Tooltip。
5. `latestPrice` 在右侧 StockHeader 中是否继续保持大号主视觉，还是明显压缩？当前建议压缩但仍是价格区主视觉。
6. `KlineViewportState.visibleCount` 是否允许用户偏好覆盖？当前 P0 建议不支持用户偏好，固定默认 144。
7. 分时图是否严格按 144 个点显示，还是允许按交易时段采样？当前组件规范统一按 144 个当前周期点位处理，02 可在 Showcase 中用模拟点。
8. 后续右键拖拽和平移是否作为 Review v4 单独处理？当前建议单独进入图表交互专项，不混入本轮。

---

## 15. Review v3 验收清单

| 验收项 | 要求 |
|---|---|
| 完整文档 | 本文件仍是完整 `04-component-guidelines.md`，不是 delta 文档。 |
| 修改边界 | 只修订 Review v3 点名的 3 个局部规则。 |
| Toolbar 相邻 | `StockIdentityInline` 与 `PeriodSwitchGroup` 必须紧凑相邻。 |
| 禁止拉开 | 不允许用 `justify-content: space-between` 把股票识别区和周期切换区拉远。 |
| Actions | `StockToolbarActions` 可以靠右，但不得影响左侧相邻关系。 |
| 周期组 | 周期集合单行展示，不换行，不隐藏日K等默认周期项。 |
| 右侧头部 | `StockHeaderPanel.compact` 规则清晰，保留核心信息和按钮。 |
| 下方上移 | 紧凑版应使按钮、盘口 Tab、盘口摘要、关联板块整体上移。 |
| 144 根 | `KlineViewportState.defaultVisibleCount = 144`。 |
| 锚定最新 | 默认展示最近最多 144 根，数据不足展示全部。 |
| 不实现拖拽 | 明确本轮不实现右键拖拽、横向平移、缩放。 |
| 未授权改动 | 不修改 TopMarketBar、StockBreadcrumb、K线绘制、副图、坐标轴、十字线、Tooltip、Header Info、右侧 Tab、关联板块、资金图、API。 |

---

## 16. 本轮输出文件下载链接

本轮输出文件名：

```text
04-component-guidelines.md
```

下载链接由本轮对话附件提供。

建议放置到 Google Drive：

```text
财势乾坤/设计/04-component-guidelines.md
```

---

# 个股详情页 StockHeader 红框 3 局部组件修正规则（Stock Detail Review v4）

> 本节为 `stock-detail-html-review-v4-总控解读与变更单.md` 的组件级合并内容。它不替代前文已确认的市场总览组件规范、通用组件库注册表、个股详情固定视口布局、图表坐标轴、十字线、Tooltip、Chart Workspace Toolbar、KlineViewportState 等规则，而是在完整保留 Review v3 完整合并版的基础上，只修订个股详情页右侧信息栏顶部 `StockHeader 红框 3` 的组件结构。  
> 本节禁止主动修改 Review v4 未点名组件。

## 1. 本轮 Review v4 修改摘要

本轮只处理右侧 `StockHeader 红框 3`：

1. `StockHeaderPanel` 改为紧凑的左右两列结构。
2. 左侧为 `StockHeaderIdentityGroup`，展示股票名称、行业 / 题材标签、股票代码。
3. 右侧为 `StockHeaderPriceGroup`，展示最新股价、涨跌额和涨跌幅。
4. 左右两组通过 `StockHeaderSummaryRow` 作为整体垂直居中对齐。
5. 下方紧接 `StockHeaderActionLinks`，只展示 `+自选 / +提醒 / +交易计划`。
6. 右侧 `StockHeaderActionLinks` 删除 `诊股`。
7. 诊股入口只保留在上方 `ChartWorkspaceToolbar` 的顶部 `DiagnosisButton`。
8. 不修改 TopMarketBar、Breadcrumb、Chart Workspace Toolbar、周期切换、K 线、指标、副图、坐标轴、十字线、Tooltip、右侧 Tab、关联板块、资金统计图、API 字段和数据结构。

---

## 2. 本轮新增或修订组件清单

| 类型 | 组件 | 处理方式 |
|---|---|---|
| 修订 | `StockHeaderPanel` | 重构为 `StockHeaderSummaryRow + StockHeaderActionLinks` 的紧凑结构。 |
| 新增 | `StockHeaderSummaryRow` | 新增左右两列摘要行，左侧股票识别，右侧价格信息。 |
| 新增 | `StockHeaderIdentityGroup` | 新增股票识别组：第一行股票名称 + 行业题材标签，第二行股票代码。 |
| 新增 | `StockHeaderPriceGroup` | 新增价格组：第一行最新股价，第二行涨跌额 + 涨跌幅，整体右对齐。 |
| 新增 / 修订 | `StockHeaderActionLinks` | 只展示 `+自选 / +提醒 / +交易计划`，删除右侧 `诊股`。 |

---

## 3. StockHeaderPanel：Review v4 结构

| 项 | 说明 |
|---|---|
| 组件名称 | `StockHeaderPanel` |
| 中文名 | 个股右侧头部行情面板 |
| 使用页面 | 个股详情页右侧信息栏顶部。 |
| 本轮处理 | 只修订右侧 `StockHeader 红框 3` 的内部结构，不修改右侧栏其它模块。 |
| 固定结构 | `StockHeaderSummaryRow` + `StockHeaderActionLinks`。 |
| 布局目标 | 紧凑、左右两列、垂直居中、释放下方盘口 / 资料 / 关联板块 / 资金统计空间。 |
| 视觉要求 | 不做高大详情页 Header，不加入大面积留白，不展示 Mock 说明、路径说明、状态说明或额外副标题。 |
| 交互 | 股票识别与价格本身不单独点击；下方操作链接可点击。 |
| 涨跌色规则 | `latestPrice`、`changeAmount`、`changePct` 按中国市场红涨绿跌；平盘灰白。股票名称、代码、行业标签中性。 |
| 与 API 字段关系 | 沿用已有股票基础行情 ViewModel 字段，不新增 API 字段。 |
| 与 Design Token 关系 | 使用 `03-design-tokens.md v0.4.2` 中 StockHeader 紧凑版、左右两列、价格右对齐、操作区紧凑相关 Token。 |
| 禁止误用 | 禁止在右侧再出现 `诊股`；禁止把 `StockHeaderPanel` 做成完整页面 Header；禁止在此处重复展示 Chart Workspace Toolbar 已有控件。 |

结构固定为：

```text
StockHeaderPanel
├── StockHeaderSummaryRow
│   ├── StockHeaderIdentityGroup
│   │   ├── stockName + industryTags
│   │   └── stockCode
│   └── StockHeaderPriceGroup
│       ├── latestPrice
│       └── changeAmount + changePct
└── StockHeaderActionLinks
    ├── +自选
    ├── +提醒
    └── +交易计划
```

### 3.1 Props 建议

```ts
interface StockHeaderPanelProps {
  stockName: string;
  stockCode: string;
  industryTags?: Array<{
    key: string;
    label: string;
    type?: 'industry' | 'theme' | 'concept' | 'custom';
  }>;
  latestPrice: number | null;
  changeAmount: number | null;
  changePct: number | null;
  direction: 'UP' | 'DOWN' | 'FLAT' | 'UNKNOWN';
  actions: StockHeaderActionLinkItem[];
  compact?: true;
  loading?: boolean;
  error?: ErrorStateProps | null;
}
```

说明：

1. `actions` 在 Review v4 中只能包含 `watchlist`、`alert`、`tradePlan`。
2. 不得把 `diagnosis` 放入右侧 `actions`。
3. `compact` 在个股详情页 P0 中默认为 `true`。
4. 该 Props 是组件展示契约，不是 API response。

---

## 4. StockHeaderSummaryRow

| 项 | 说明 |
|---|---|
| 组件名称 | `StockHeaderSummaryRow` |
| 中文名 | 个股头部摘要行 |
| 组件用途 | 组织 `StockHeaderIdentityGroup` 与 `StockHeaderPriceGroup`，形成左右两列紧凑摘要结构。 |
| 使用位置 | `StockHeaderPanel` 顶部。 |
| 结构 | 左侧 `StockHeaderIdentityGroup`，右侧 `StockHeaderPriceGroup`。 |
| 对齐 | 左右两组作为整体垂直居中。 |
| 横向规则 | 左侧靠左，右侧靠右，中间保留必要呼吸空间。 |
| 高度规则 | 不允许上下多行堆叠成高 Header；不允许加入大面积空白。 |
| 状态 | default、loading、empty、error；hover 不改变结构。 |
| 禁止误用 | 不承载按钮、不承载 Tab、不承载数据状态、不承载更新时间或刷新。 |

```ts
interface StockHeaderSummaryRowProps {
  identity: StockHeaderIdentityGroupProps;
  price: StockHeaderPriceGroupProps;
  compact?: true;
  loading?: boolean;
}
```

实现建议：

```css
.stock-header-summary-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  column-gap: var(--cs-stock-header-summary-column-gap);
  min-height: var(--cs-stock-header-summary-row-min-height);
}
```

禁止：

```css
/* 禁止用高 Header 式纵向堆叠替代左右两列 */
.stock-header-summary-row {
  display: block;
}
```

---

## 5. StockHeaderIdentityGroup

| 项 | 说明 |
|---|---|
| 组件名称 | `StockHeaderIdentityGroup` |
| 中文名 | 股票识别组 |
| 组件用途 | 在右侧 StockHeader 左列展示股票身份信息。 |
| 第一行 | `stockName + industryTags`。 |
| 第二行 | `stockCode`。 |
| 视觉权重 | `stockName` 是主识别信息，权重最高；行业题材标签弱于股票名；股票代码弱化。 |
| 空间规则 | 行业 / 题材标签过多时最多展示 1～2 个，其余通过 Tooltip 或省略处理。 |
| 禁止内容 | 不显示 Mock 说明；不显示路径说明；不显示状态说明；不显示额外副标题。 |
| 与 Token 关系 | 使用 `--cs-stock-header-name-*`、`--cs-stock-header-tag-*`、`--cs-stock-header-code-*`。 |

```ts
interface StockHeaderIdentityGroupProps {
  stockName: string;
  stockCode: string;
  industryTags?: Array<{
    key: string;
    label: string;
    type?: 'industry' | 'theme' | 'concept' | 'custom';
  }>;
  maxVisibleTags?: number; // default: 2
}
```

展示示例：

```text
第一行：福斯特  光伏设备 / 新材料
第二行：603806.SH
```

### 5.1 字段规则

| 字段 | 位置 | 规则 |
|---|---|---|
| `stockName` | 第一行左侧 | 主识别信息，单行省略，不使用涨跌色。 |
| `industryTags` | 第一行 stockName 后 | 与股票名称同行，弱标签样式，过多省略。 |
| `stockCode` | 第二行 | 弱文字，等宽数字，可复制但 P0 不要求复制交互。 |

---

## 6. StockHeaderPriceGroup

| 项 | 说明 |
|---|---|
| 组件名称 | `StockHeaderPriceGroup` |
| 中文名 | 股票价格组 |
| 组件用途 | 在右侧 StockHeader 右列展示最新价与涨跌信息。 |
| 第一行 | `latestPrice`。 |
| 第二行 | `changeAmount + changePct`。 |
| 对齐规则 | 两行均右对齐。 |
| 颜色规则 | 使用红涨绿跌；上涨红、下跌绿、平盘灰白。 |
| 禁止内容 | 不显示额外价格说明；不在其它位置重复展示价格或涨跌幅。 |
| 与 Token 关系 | 使用 `--cs-stock-header-price-*`、`--cs-stock-header-change-*`、`--cs-color-market-up/down/flat`、`--cs-font-family-number`。 |

```ts
interface StockHeaderPriceGroupProps {
  latestPrice: number | null;
  changeAmount: number | null;
  changePct: number | null;
  direction: 'UP' | 'DOWN' | 'FLAT' | 'UNKNOWN';
  latestPriceText?: string;
  changeAmountText?: string;
  changePctText?: string;
}
```

展示示例：

```text
第一行：18.36
第二行：+0.35 +1.94%
```

### 6.1 右对齐规则

1. `latestPrice` 右对齐。
2. `changeAmount + changePct` 作为一个整体右对齐。
3. 数字使用等宽数字字体。
4. `changeAmount` 与 `changePct` 之间保留紧凑间距。
5. 不在价格区下方增加第三行说明。

### 6.2 红涨绿跌规则

| direction | 显示 |
|---|---|
| `UP` | `latestPrice` 可红色；`changeAmount`、`changePct` 必须红色。 |
| `DOWN` | `latestPrice` 可绿色；`changeAmount`、`changePct` 必须绿色。 |
| `FLAT` | 灰白色。 |
| `UNKNOWN` | 主文字或弱文字，不使用红绿。 |

---

## 7. StockHeaderActionLinks

| 项 | 说明 |
|---|---|
| 组件名称 | `StockHeaderActionLinks` |
| 中文名 | 个股头部操作链接 |
| 组件用途 | 在 `StockHeaderSummaryRow` 下方展示右侧头部的轻量操作入口。 |
| 固定操作 | `+自选 / +提醒 / +交易计划`。 |
| 禁止操作 | 不包含 `诊股`。 |
| 位置 | 紧接 `StockHeaderSummaryRow` 下方，不被大空白隔开。 |
| 分隔 | 操作项之间使用 `/` 或等价弱分隔。 |
| 交互 | 每个操作项可点击；hover 弱高亮；disabled 显示原因。 |
| 与 Token 关系 | 使用 `--cs-stock-header-action-*`、`--cs-color-brand-accent`、`--cs-color-text-secondary`。 |

```ts
interface StockHeaderActionLinkItem {
  key: 'watchlist' | 'alert' | 'tradePlan';
  label: '+自选' | '+提醒' | '+交易计划';
  enabled: boolean;
  disabledReason?: string;
}

interface StockHeaderActionLinksProps {
  items: StockHeaderActionLinkItem[];
  separator?: '/' | 'dot' | 'space';
  onActionClick?: (key: StockHeaderActionLinkItem['key']) => void;
}
```

固定渲染顺序：

```text
+自选 / +提醒 / +交易计划
```

### 7.1 删除右侧诊股规则

1. `StockHeaderActionLinks` 中不得出现 `诊股`。
2. 右侧 StockHeader 不得出现第二个诊股入口。
3. 诊股只保留在上方 `ChartWorkspaceToolbar` 的 `DiagnosisButton`。
4. 顶部 `DiagnosisButton` 的 disabled 业务规则保持不变。
5. 本轮不修改顶部 `DiagnosisButton` 的文案、状态、交互或 Tooltip。

---

## 8. 与右侧下方模块的关系

StockHeader 精简后，应释放垂直空间，使以下内容整体上移：

1. `StockHeaderActionLinks`；
2. `StockSideTabs`；
3. 盘口摘要；
4. `RelatedSectorTable`；
5. `StockMoneyFlowPanel`。

说明：

1. 这是 StockHeader 紧凑化带来的布局结果。
2. 本轮不改变 `StockSideTabs`、盘口摘要、`RelatedSectorTable`、`StockMoneyFlowPanel` 的内部结构。
3. 不允许通过新增空白维持旧高度。
4. 不允许把释放出的空间又塞入额外副标题、状态说明或诊股入口。

---

## 9. 本轮未修改组件清单

以下组件和规则保持 Review v3 完整合并版，不做主动改动：

- `TopMarketBar`
- `StockBreadcrumb`
- `ChartWorkspaceToolbar`
- `StockChartToolbar`
- `AdjustTypeSelect`
- `StockProfileButton`
- 顶部 `DiagnosisButton`
- `ChartSettingButton`
- `StockKlinePanel`
- `MacdPanel`
- `VolumePanel`
- `KdjPanel`
- `ChartYAxis`
- `ChartDualYAxis`
- `ChartAxisTickLabel`
- `ChartTimeAxis`
- `ChartTimeTickLabel`
- `ChartPanelHeaderInfo`
- `ChartCrosshairLayer`
- `ChartAxisFloatLabel`
- `KlineTooltip`
- `IndicatorToolbar`
- `StockSideTabs`
- `RelatedSectorTable`
- `StockMoneyFlowPanel`
- `KlineViewportState.defaultVisibleCount = 144`
- 固定视口 `100vh` 规则
- 不使用 body 级整页滚动规则
- API 字段和数据结构

---

## 10. 对 02 `stock-detail-v1.4.html` 的组件使用建议

1. 只修改右侧 `StockHeader 红框 3`。
2. `StockHeaderPanel` 必须采用左右两列结构。
3. 左侧第一行展示：股票名称 + 行业 / 题材标签。
4. 左侧第二行展示：股票代码。
5. 右侧第一行展示：最新股价。
6. 右侧第二行展示：涨跌额 + 涨跌幅。
7. 左右两组必须在垂直方向居中对齐。
8. 最新价、涨跌额、涨跌幅必须右对齐。
9. 下方紧接展示：`+自选 / +提醒 / +交易计划`。
10. 每个操作项前面都带 `+`。
11. 操作项之间使用 `/` 或等价弱分隔。
12. 删除右侧 StockHeader 中的 `诊股`。
13. 诊股只保留在上方 `ChartWorkspaceToolbar`。
14. 不显示 Mock 说明、路径说明、状态说明或额外副标题。
15. 不通过新增空白维持旧高度。
16. 盘口 / 资料 Tab、盘口摘要、关联板块、资金统计应随 StockHeader 压缩整体上移。
17. 不修改本轮未点名模块。

---

## 11. 对 01 Design Token 的依赖

本轮依赖 `03-design-tokens.md v0.4.2` 中 StockHeader 红框 3 相关 Token 或等价规则，重点包括：

1. StockHeader 左右两列布局 Token；
2. StockHeader 紧凑高度、内边距、行距；
3. `StockHeaderSummaryRow` 的列间距和垂直居中；
4. `StockHeaderIdentityGroup` 的股票名称、行业标签、代码样式；
5. `StockHeaderPriceGroup` 的最新股价、涨跌额、涨跌幅右对齐样式；
6. `StockHeaderActionLinks` 的操作项字号、间距、分隔符、hover、disabled；
7. 删除右侧诊股后的操作区间距；
8. 下方内容上移后的垂直节奏；
9. 红涨绿跌 Token：`--cs-color-market-up`、`--cs-color-market-down`、`--cs-color-market-flat`；
10. 数字字体 Token：`--cs-font-family-number`。

03 实现时不得绕过 Token 直接硬编码 StockHeader 的背景、字号、价格颜色、间距和 hover 样式。

---

## 12. 是否需要后续拉 04 参与的条件

本轮 04 不参与。

原因：

1. 本轮只调整 `StockHeaderPanel` 展示结构。
2. 不新增字段。
3. 不改变股票基础行情字段。
4. 不改变右侧资金、关联板块、K 线数据结构。
5. 不涉及 API response 变更。

后续只有在以下条件出现时，才需要拉 04 参与：

| 条件 | 是否需要 04 | 原因 |
|---|---:|---|
| 行业 / 题材标签来源需要正式定义 | 是 | 需要明确来自行业、概念、主题还是组合标签。 |
| 右侧 StockHeader 需要展示更多标签类型 | 可能 | 需要数据字典定义标签枚举。 |
| `actions` 状态需要由后端返回 | 可能 | 需要定义是否已加入自选、是否已设置提醒、是否有交易计划。 |
| 仅调整布局和操作链接排列 | 否 | 属于前端组件与 Showcase 范围。 |

---

## 13. 待产品总控确认问题

1. `industryTags` 是否最多展示 2 个？当前建议最多 2 个，更多通过 Tooltip 展示。
2. 行业 / 题材标签之间使用 `/` 还是独立 pill？当前建议在极紧凑头部中使用弱 pill 或简短文本，避免占高。
3. `latestPrice` 是否保持较大字号，还是进一步压缩？当前建议仍保持价格组主视觉，但高度必须紧凑。
4. `StockHeaderActionLinks` 中 `+自选` 在已加入自选后是否变为 `已自选`？当前本节只约束入口文案形态，具体状态可后续确认。
5. `+提醒` 是否需要显示已有提醒状态？当前建议 P0 仍保持入口，不在红框 3 中增加状态说明。
6. `+交易计划` 是否在已有计划时显示数量？当前建议不显示数量，避免重新撑高头部。
7. 右侧 StockHeader 中是否完全不显示交易状态？当前按 Review v4：不显示状态说明；如需状态说明，优先在 TopMarketBar 或右侧其它区域处理。
8. 是否允许 `StockHeaderActionLinks` 使用 `·` 分隔而不是 `/`？当前允许“或等价弱分隔”，02 可根据视觉选择。

---

## 14. Review v4 验收清单

| 验收项 | 要求 |
|---|---|
| 完整文档 | 本文件仍是完整 `04-component-guidelines.md`，不是 delta 文档。 |
| 修改边界 | 只修订右侧 `StockHeader 红框 3`。 |
| 左右两列 | `StockHeaderSummaryRow` 明确左侧 `StockHeaderIdentityGroup`、右侧 `StockHeaderPriceGroup`。 |
| 垂直居中 | 左右两组作为整体垂直居中。 |
| 左侧识别 | 第一行股票名称 + 行业题材标签，第二行股票代码。 |
| 右侧价格 | 第一行最新股价，第二行涨跌额 + 涨跌幅，全部右对齐。 |
| 操作区 | `StockHeaderActionLinks` 只包含 `+自选 / +提醒 / +交易计划`。 |
| 删除诊股 | 右侧删除 `诊股`，诊股只保留在 `ChartWorkspaceToolbar`。 |
| 紧凑高度 | 不使用上下多行堆叠成高 Header，不加入大面积留白。 |
| 下方上移 | 盘口 / 资料 Tab、盘口摘要、关联板块、资金统计随头部压缩整体上移。 |
| 红涨绿跌 | 最新价、涨跌额、涨跌幅遵守红涨绿跌。 |
| API | 不修改 API 字段和数据结构。 |
| 未授权改动 | 未修改 TopMarketBar、Breadcrumb、Chart Workspace Toolbar、周期切换、K 线、副图、坐标轴、Header Info、十字线、Tooltip、右侧 Tab、关联板块、资金统计图等非点名组件。 |

---

## 15. 本轮输出文件下载链接

本轮输出文件名：

```text
04-component-guidelines.md
```

下载链接由本轮对话附件提供。

建议放置到 Google Drive：

```text
财势乾坤/设计/04-component-guidelines.md
```

