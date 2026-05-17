# 财势乾坤｜Design Token 与视觉规范 v0.4.2

> 所属项目：财势乾坤  
> 文档名称：`03-design-tokens.md`  
> 建议保存路径：`财势乾坤/设计/03-design-tokens.md`  
> 文档角色：01_Design Token 与视觉规范  
> 适用范围：P0 Web 页面、通用组件库 Demo、后续行情终端类页面  
> 默认主题：Dark First，Light Token Ready  
> 市场规则：中国市场红涨绿跌  
> 当前状态：v0.4.2，基于个股详情页 HTML Review v4 补充右侧信息栏 `StockHeader 红框 3` 左右两列、操作区紧凑与删除右侧诊股规则  
> 本轮重点：仅处理个股详情页 Review v4 点名的 `个股详情页 / 右侧信息栏 / StockHeader 红框 3`；明确 StockHeader 左右两列、左侧股票识别组、右侧价格组、下方 `+自选 / +提醒 / +交易计划` 操作区、删除右侧 StockHeader 中的 `诊股` 以及下方模块整体上移的垂直节奏；不修改 TopMarketBar、Breadcrumb、Chart Workspace Toolbar、周期切换、K 线主图、MACD、成交量、KDJ、坐标轴、时间轴、Header Info、MA/BOLL、十字线、Tooltip、盘口/资料 Tab、关联板块、资金统计、默认 144 根 K 线、固定视口 100vh、API 字段和红涨绿跌规则。

---

## 0. 本轮上游文档与修订边界

### 0.1 本轮读取到的上游文档

| 文件 | 版本 / 状态 | 本文档处理 |
|---|---|---|
| `财势乾坤行情软件项目总说明_v_0_2.md` | v0.2 | 继续作为项目级产品与 UI 总控纲领，约束产品名称、A 股优先、红涨绿跌、深色默认、专业沉稳风格。 |
| `个股详情页产品需求文档_v_0_2.md` | v0.2 | 作为个股详情页 PRD，约束固定视口交易终端布局、`100vh`、主内容区 `calc(...)`、禁止 body 级整页滚动、默认日 K、默认副图 MACD/成交量/KDJ、资料 Tab 暂未开通、诊股 disabled。 |
| `stock-detail-html-review-v3-总控解读与变更单.md` | 个股详情 HTML Review v3，总控解读草案 | 作为本轮直接变更依据，限定只修订 `Chart Workspace Toolbar` 紧凑间距、右侧 `StockHeader` 紧凑版、K 线默认最多 144 根视窗；不处理右键拖拽、平移、缩放。 |
| `stock-detail-html-review-v4-总控解读与变更单.md` | 个股详情 HTML Review v4，总控解读草案 | 作为本轮直接变更依据，限定只修订 `个股详情页 / 右侧信息栏 / StockHeader 红框 3`；明确左右两列、股票识别组、价格组、下方操作区与删除右侧诊股。 |
| `03-design-tokens.md` | 当前公共区 Token 基线 | 作为本文档既有内容基线，保留已确认的全局主题、红涨绿跌、通用组件 Token、市场总览既有页面级约束以及个股详情页 v0.3.8/v0.3.9 已确认规则。 |

### 0.2 本轮不变的市场总览基线

即使本轮修订新闻板块，以下基线不得改变：

1. 页面名称是“市场总览”。
2. 页面属于“乾坤行情”。
3. 市场总览不是独立一级菜单。
4. 桌面端不使用固定 SideNav。
5. 页面只展示 A 股市场客观事实。
6. 不展示市场温度、市场情绪指数、资金面分数、风险指数作为首页核心结论。
7. 中国市场红涨绿跌：上涨红色、下跌绿色、平盘白色/灰白色。
8. 不输出买卖建议。


### 0.2A 本轮不变的个股详情页基线

本轮修订不得改变以下个股详情页基线：

1. 页面名称是“个股详情”。
2. 页面属于“乾坤行情”，不是独立一级菜单。
3. 页面根容器使用固定视口 `100vh`。
4. 不使用 body 级整页滚动。
5. 最顶部复用市场总览同款 `TopMarketBar`。
6. Breadcrumb 行只保留路径。
7. 绿色框独立控制行已删除且不得恢复。
8. 前复权位于 `Chart Workspace Toolbar` 右侧。
9. 不显示更新时间、刷新、READY。
10. 不输出买卖建议，不展示诊股结论。
11. 中国市场红涨绿跌。
12. 默认周期为日 K，默认副图为 MACD、成交量、KDJ。
13. 资料 Tab P0 只显示“暂未开通”。
14. 诊股按钮 P0 disabled。

### 0.3 本轮修订边界

本轮只允许补充或修正：

```text
个股详情页 / Chart Workspace Toolbar 内部三分区横向间距
个股详情页 / 股票识别区与周期切换区之间的最小和推荐间距
个股详情页 / 周期切换区紧凑按钮间距
个股详情页 / 右侧操作区与周期区的分隔策略
个股详情页 / 右侧 StockHeader 紧凑版高度、内边距、行距
个股详情页 / 自选、提醒、交易计划、诊股按钮上移后的间距
个股详情页 / K 线默认 144 根视窗视觉说明
```

本轮禁止主动修改：

1. TopMarketBar；
2. Breadcrumb 路径行；
3. 已删除绿色框独立控制行的规则；
4. 前复权在 `Chart Workspace Toolbar` 右侧的规则；
5. 删除更新时间 / 刷新 / READY 的规则；
6. K 线主图绘制风格；
7. MACD；
8. 成交量；
9. KDJ；
10. 坐标轴常驻刻度规则；
11. 时间轴刻度规则；
12. 十字线；
13. Tooltip；
14. Header Info；
15. MA / BOLL 切换；
16. 齿轮 Toast；
17. 盘口 / 资料 Tab；
18. 关联板块；
19. 资金统计；
20. 资料 Tab 暂未开通；
21. 诊股 disabled；
22. 红涨绿跌规则；
23. 固定视口 `100vh` 布局规则。

### 0.4 组件库通用边界继续保留

此前基于《组件库Demo产品需求文档 v0.2.md》补充的通用组件 Token 继续保留，但本轮不新增具体业务专属通用组件。

`CsqStockCompactCard` 可以作为紧凑股票卡片候选组件，但本轮 Review v7 的具体字段结构仅用于市场总览连板天梯场景，不扩大为所有股票卡片的强制唯一结构。

CSS Design Token 变量仍统一使用：

```css
--cs-*
```

## 1. 已确认产品与视觉决策

| 决策项 | 已确认结论 | 对视觉 / Token 的影响 |
|---|---|---|
| 产品名称 | 财势乾坤 | 所有页面标题、文档标题、品牌露出统一使用该名称 |
| 首期形态 | Web 优先 | Token 和布局优先支持桌面 Web |
| 首期市场 | A 股优先 | 涨跌色、指数、榜单、K 线均按中国市场习惯设计 |
| 默认主题 | 深色默认 | 深色主题可直接支持 HTML Showcase |
| 浅色主题 | 保留完整 Token 结构 | 后续可通过配置切换 |
| 视觉方向 | 专业、沉稳、高密度、金融终端感 | 不做官网风、低幼风、廉价大屏风 |
| 涨跌色 | 中国市场红涨绿跌 | 上涨红、下跌绿、平盘白色/灰白色 |
| 系统错误色 | 不使用行情红 | 避免与上涨红冲突 |
| 品牌强调色 | 金色系固定 | 品牌、选中、十字光标、重点入口使用金色系 |
| 组件库边界 | 与具体业务解耦 | Core Component 不使用具体业务命名 |
| Demo 目标 | 展示通用 UI 能力 | 不绑定市场总览 API，不绑定 Tushare 字段 |

---

## 2. 视觉定位

### 2.1 风格关键词

| 关键词 | 说明 |
|---|---|
| 专业 | 面向进阶投资者与专业交易者，不做娱乐化表达 |
| 沉稳 | 低亮度背景、克制强调色、减少视觉噪音 |
| 高密度 | 支撑表格、图表、卡片、热力图等信息密集组件 |
| 金融终端感 | 数字清晰、表格紧凑、图表克制、状态明确 |
| 数据可信 | 明确数据状态、延迟、空态、异常态 |
| 组件可复用 | 组件表达 UI 能力，不固化具体业务流程 |

### 2.2 禁止方向

明确禁止：

1. 低幼卡通风；
2. 官网营销 Hero 风；
3. 廉价大屏风；
4. 霓虹发光边框；
5. 大面积无意义渐变；
6. 把 UI 框架默认 `success=green` 当作上涨色；
7. 绿涨红跌；
8. 把系统错误色和行情上涨红混用；
9. 将通用组件命名为具体业务模块；
10. 在组件 Props 中直接绑定具体 API response 或 Tushare 原字段。

---

## 3. Token 命名规范

### 3.1 CSS Token 前缀

```css
--cs-*
```

### 3.2 命名结构

```text
--cs-[category]-[role]-[state?]
```

示例：

```css
--cs-color-bg-page
--cs-color-surface-panel
--cs-color-text-primary
--cs-color-market-up
--cs-component-panel-padding
--cs-table-row-height-compact
--cs-chart-tooltip-bg
```

### 3.3 Token 分类

| 分类 | 前缀 |
|---|---|
| 色彩 | `--cs-color-*` |
| 字体 | `--cs-font-*` |
| 间距 | `--cs-space-*` |
| 尺寸 / 布局 | `--cs-size-*` / `--cs-layout-*` |
| 组件 | `--cs-component-*` |
| 表格 | `--cs-table-*` |
| 图表 | `--cs-chart-*` |
| 圆角 | `--cs-radius-*` |
| 边框 | `--cs-border-*` |
| 阴影 | `--cs-shadow-*` |
| 层级 | `--cs-z-*` |
| 动效 | `--cs-motion-*` |
| 行情 | `--cs-color-market-*` |
| 状态 | `--cs-color-status-*` |

### 3.4 组件命名规则

通用组件使用 `Csq` 前缀：

```text
CsqPanel
CsqMetricCard
CsqDataTable
CsqPieChartWithCallout
CsqHeatMapGrid
```

规则：

1. 组件名表达 UI 能力，不表达具体业务对象；
2. Core Component 不出现具体页面名；
3. 图表组件按图表形态命名；
4. 表格组件按表格能力命名；
5. 业务组合只能作为 Pattern Example，不进入 Core Component 命名。

---

## 4. 全局基础 Token

### 4.1 Color 基础 Token

```css
:root {
  /* Neutral */
  --cs-color-neutral-0: #FFFFFF;
  --cs-color-neutral-50: #F8FAFC;
  --cs-color-neutral-100: #F1F5F9;
  --cs-color-neutral-200: #E2E8F0;
  --cs-color-neutral-300: #CBD5E1;
  --cs-color-neutral-400: #94A3B8;
  --cs-color-neutral-500: #64748B;
  --cs-color-neutral-600: #475569;
  --cs-color-neutral-700: #334155;
  --cs-color-neutral-800: #1E293B;
  --cs-color-neutral-900: #0F172A;
  --cs-color-neutral-950: #020617;

  /* A-share market semantic base */
  --cs-color-red-500: #FF4D5A;
  --cs-color-red-600: #E23D49;
  --cs-color-red-700: #C92F3B;

  --cs-color-green-500: #15C784;
  --cs-color-green-600: #0EAD70;
  --cs-color-green-700: #07875A;

  /* Brand gold */
  --cs-color-gold-400: #F7C76B;
  --cs-color-gold-500: #D8A747;
  --cs-color-gold-600: #B8872E;

  /* Semantic */
  --cs-color-blue-500: #5AA7FF;
  --cs-color-amber-500: #F59E0B;
  --cs-color-orange-500: #FF8A3D;
}
```

### 4.2 Typography Token

```css
:root {
  --cs-font-family-base:
    -apple-system,
    BlinkMacSystemFont,
    "SF Pro Display",
    "PingFang SC",
    "Microsoft YaHei",
    "Segoe UI",
    sans-serif;

  --cs-font-family-number:
    "DIN Alternate",
    "Roboto Mono",
    "SF Mono",
    "JetBrains Mono",
    ui-monospace,
    monospace;

  --cs-font-size-10: 10px;
  --cs-font-size-11: 11px;
  --cs-font-size-12: 12px;
  --cs-font-size-13: 13px;
  --cs-font-size-14: 14px;
  --cs-font-size-16: 16px;
  --cs-font-size-18: 18px;
  --cs-font-size-20: 20px;
  --cs-font-size-24: 24px;
  --cs-font-size-28: 28px;
  --cs-font-size-32: 32px;

  --cs-font-weight-regular: 400;
  --cs-font-weight-medium: 500;
  --cs-font-weight-semibold: 600;
  --cs-font-weight-bold: 700;

  --cs-line-height-tight: 1.15;
  --cs-line-height-compact: 1.28;
  --cs-line-height-normal: 1.45;
  --cs-line-height-relaxed: 1.6;
}
```

### 4.3 Spacing Token

```css
:root {
  --cs-space-2: 2px;
  --cs-space-4: 4px;
  --cs-space-6: 6px;
  --cs-space-8: 8px;
  --cs-space-10: 10px;
  --cs-space-12: 12px;
  --cs-space-14: 14px;
  --cs-space-16: 16px;
  --cs-space-20: 20px;
  --cs-space-24: 24px;
  --cs-space-28: 28px;
  --cs-space-32: 32px;
  --cs-space-40: 40px;
}
```

### 4.4 Radius Token

```css
:root {
  --cs-radius-none: 0;
  --cs-radius-xs: 3px;
  --cs-radius-sm: 4px;
  --cs-radius-md: 6px;
  --cs-radius-lg: 8px;
  --cs-radius-xl: 10px;
  --cs-radius-panel: 10px;
  --cs-radius-card: 8px;
  --cs-radius-button: 6px;
  --cs-radius-pill: 999px;
}
```

### 4.5 Shadow Token

```css
:root {
  --cs-shadow-none: none;
  --cs-shadow-panel: 0 10px 28px rgba(0, 0, 0, 0.24);
  --cs-shadow-dropdown: 0 16px 40px rgba(0, 0, 0, 0.36);
  --cs-shadow-tooltip: 0 12px 32px rgba(0, 0, 0, 0.42);
  --cs-shadow-dialog: 0 24px 72px rgba(0, 0, 0, 0.52);
}
```

### 4.6 Z-index Token

```css
:root {
  --cs-z-base: 0;
  --cs-z-sticky: 100;
  --cs-z-topbar: 300;
  --cs-z-dropdown: 500;
  --cs-z-popover: 620;
  --cs-z-tooltip: 700;
  --cs-z-modal-mask: 900;
  --cs-z-modal: 1000;
  --cs-z-toast: 1100;
}
```

### 4.7 Motion Token

```css
:root {
  --cs-motion-duration-fast: 120ms;
  --cs-motion-duration-normal: 180ms;
  --cs-motion-duration-slow: 240ms;

  --cs-motion-ease-standard: cubic-bezier(0.2, 0, 0, 1);
  --cs-motion-ease-out: cubic-bezier(0, 0, 0.2, 1);
  --cs-motion-ease-in: cubic-bezier(0.4, 0, 1, 1);
}
```

---

## 5. 深色主题 Token

```css
:root,
[data-theme="dark"] {
  color-scheme: dark;

  /* Background */
  --cs-color-bg-page: #070A12;
  --cs-color-bg-page-alt: #0A0F1A;
  --cs-color-bg-top-market-bar: rgba(8, 13, 22, 0.96);
  --cs-color-bg-breadcrumb: rgba(10, 15, 26, 0.92);
  --cs-color-bg-page-header: #0B1220;

  /* Surface */
  --cs-color-surface-panel: #101827;
  --cs-color-surface-panel-subtle: #0D1422;
  --cs-color-surface-card: #121B2C;
  --cs-color-surface-card-hover: #182235;
  --cs-color-surface-elevated: #162033;
  --cs-color-surface-input: #0B1220;

  /* Table */
  --cs-color-table-bg: #0F1726;
  --cs-color-table-header-bg: #111A2A;
  --cs-color-table-row-bg: #0F1726;
  --cs-color-table-row-alt-bg: #101928;
  --cs-color-table-row-hover-bg: #152033;
  --cs-color-table-row-selected-bg: rgba(247, 199, 107, 0.08);

  /* Chart */
  --cs-color-chart-bg: #0B1220;
  --cs-color-chart-panel-bg: #0D1422;
  --cs-color-chart-grid: rgba(148, 163, 184, 0.12);
  --cs-color-chart-axis: rgba(148, 163, 184, 0.38);
  --cs-color-chart-label: #7B8AA0;
  --cs-color-chart-crosshair: rgba(247, 199, 107, 0.72);

  /* Tooltip */
  --cs-color-tooltip-bg: rgba(8, 13, 22, 0.96);
  --cs-color-tooltip-border: rgba(247, 199, 107, 0.28);

  /* Border / Divider */
  --cs-color-border-subtle: rgba(148, 163, 184, 0.14);
  --cs-color-border-default: rgba(148, 163, 184, 0.22);
  --cs-color-border-strong: rgba(203, 213, 225, 0.34);
  --cs-color-border-hover: rgba(247, 199, 107, 0.34);
  --cs-color-divider: rgba(148, 163, 184, 0.12);

  /* Text */
  --cs-color-text-primary: #E5EDF8;
  --cs-color-text-secondary: #A8B4C6;
  --cs-color-text-muted: #7B8AA0;
  --cs-color-text-weak: #5F6E82;
  --cs-color-text-inverse: #07101D;
  --cs-color-text-on-market: #FFFFFF;

  /* Market semantic: A-share red up, green down */
  --cs-color-market-up: #FF4D5A;
  --cs-color-market-up-hover: #FF6570;
  --cs-color-market-up-bg: rgba(255, 77, 90, 0.12);
  --cs-color-market-up-bg-strong: rgba(255, 77, 90, 0.20);
  --cs-color-market-up-border: rgba(255, 77, 90, 0.34);

  --cs-color-market-down: #15C784;
  --cs-color-market-down-hover: #2BD996;
  --cs-color-market-down-bg: rgba(21, 199, 132, 0.12);
  --cs-color-market-down-bg-strong: rgba(21, 199, 132, 0.20);
  --cs-color-market-down-border: rgba(21, 199, 132, 0.34);

  --cs-color-market-flat: #DDE6F2;
  --cs-color-market-flat-muted: #9AA4B2;
  --cs-color-market-flat-bg: rgba(221, 230, 242, 0.10);
  --cs-color-market-flat-border: rgba(221, 230, 242, 0.24);

  /* Brand gold */
  --cs-color-brand-primary: #C99A3D;
  --cs-color-brand-primary-hover: #E1B75B;
  --cs-color-brand-accent: #F7C76B;
  --cs-color-brand-accent-bg: rgba(247, 199, 107, 0.10);
  --cs-color-brand-accent-border: rgba(247, 199, 107, 0.28);

  /* Semantic status */
  --cs-color-risk: #FF8A3D;
  --cs-color-risk-bg: rgba(255, 138, 61, 0.12);
  --cs-color-warning: #F59E0B;
  --cs-color-warning-bg: rgba(245, 158, 11, 0.12);
  --cs-color-info: #5AA7FF;
  --cs-color-info-bg: rgba(90, 167, 255, 0.12);
  --cs-color-success: #22C55E;
  --cs-color-success-bg: rgba(34, 197, 94, 0.12);

  /* Data status */
  --cs-color-status-live: #15C784;
  --cs-color-status-delayed: #F59E0B;
  --cs-color-status-closed: #7B8AA0;
  --cs-color-status-abnormal: #FF8A3D;
  --cs-color-status-missing: #64748B;

  /* MA / indicators */
  --cs-color-ma-5: #F7C76B;
  --cs-color-ma-10: #5AA7FF;
  --cs-color-ma-20: #A78BFA;
  --cs-color-ma-60: #22D3EE;

  --cs-color-indicator-dif: #5AA7FF;
  --cs-color-indicator-dea: #F7C76B;
  --cs-color-indicator-k: #F7C76B;
  --cs-color-indicator-d: #5AA7FF;
  --cs-color-indicator-j: #A78BFA;
}
```

---

## 6. 浅色主题 Token

浅色主题本轮只保留结构，不要求组件库 Demo 同步做高保真浅色展示。

```css
[data-theme="light"] {
  color-scheme: light;

  /* Background */
  --cs-color-bg-page: #F5F7FB;
  --cs-color-bg-page-alt: #EEF2F7;
  --cs-color-bg-top-market-bar: rgba(255, 255, 255, 0.96);
  --cs-color-bg-breadcrumb: rgba(255, 255, 255, 0.92);
  --cs-color-bg-page-header: #FFFFFF;

  /* Surface */
  --cs-color-surface-panel: #FFFFFF;
  --cs-color-surface-panel-subtle: #F8FAFC;
  --cs-color-surface-card: #FFFFFF;
  --cs-color-surface-card-hover: #F1F5F9;
  --cs-color-surface-elevated: #FFFFFF;
  --cs-color-surface-input: #FFFFFF;

  /* Table */
  --cs-color-table-bg: #FFFFFF;
  --cs-color-table-header-bg: #F3F6FA;
  --cs-color-table-row-bg: #FFFFFF;
  --cs-color-table-row-alt-bg: #F8FAFC;
  --cs-color-table-row-hover-bg: #F1F5F9;
  --cs-color-table-row-selected-bg: rgba(201, 154, 61, 0.08);

  /* Chart */
  --cs-color-chart-bg: #FFFFFF;
  --cs-color-chart-panel-bg: #F8FAFC;
  --cs-color-chart-grid: rgba(15, 23, 42, 0.10);
  --cs-color-chart-axis: rgba(15, 23, 42, 0.34);
  --cs-color-chart-label: #64748B;
  --cs-color-chart-crosshair: rgba(168, 117, 33, 0.72);

  /* Tooltip */
  --cs-color-tooltip-bg: rgba(255, 255, 255, 0.98);
  --cs-color-tooltip-border: rgba(201, 154, 61, 0.30);

  /* Border / Divider */
  --cs-color-border-subtle: rgba(15, 23, 42, 0.10);
  --cs-color-border-default: rgba(15, 23, 42, 0.16);
  --cs-color-border-strong: rgba(15, 23, 42, 0.24);
  --cs-color-border-hover: rgba(201, 154, 61, 0.42);
  --cs-color-divider: rgba(15, 23, 42, 0.10);

  /* Text */
  --cs-color-text-primary: #0F172A;
  --cs-color-text-secondary: #475569;
  --cs-color-text-muted: #64748B;
  --cs-color-text-weak: #94A3B8;
  --cs-color-text-inverse: #FFFFFF;
  --cs-color-text-on-market: #FFFFFF;

  /* Market semantic: A-share red up, green down */
  --cs-color-market-up: #D92D3A;
  --cs-color-market-up-hover: #E54854;
  --cs-color-market-up-bg: rgba(217, 45, 58, 0.10);
  --cs-color-market-up-bg-strong: rgba(217, 45, 58, 0.18);
  --cs-color-market-up-border: rgba(217, 45, 58, 0.28);

  --cs-color-market-down: #059669;
  --cs-color-market-down-hover: #10B981;
  --cs-color-market-down-bg: rgba(5, 150, 105, 0.10);
  --cs-color-market-down-bg-strong: rgba(5, 150, 105, 0.18);
  --cs-color-market-down-border: rgba(5, 150, 105, 0.28);

  --cs-color-market-flat: #475569;
  --cs-color-market-flat-muted: #64748B;
  --cs-color-market-flat-bg: rgba(100, 116, 139, 0.10);
  --cs-color-market-flat-border: rgba(100, 116, 139, 0.24);

  /* Brand */
  --cs-color-brand-primary: #A87521;
  --cs-color-brand-primary-hover: #C28A2E;
  --cs-color-brand-accent: #C99A3D;
  --cs-color-brand-accent-bg: rgba(201, 154, 61, 0.10);
  --cs-color-brand-accent-border: rgba(201, 154, 61, 0.28);

  /* Semantic status */
  --cs-color-risk: #EA580C;
  --cs-color-risk-bg: rgba(234, 88, 12, 0.10);
  --cs-color-warning: #D97706;
  --cs-color-warning-bg: rgba(217, 119, 6, 0.10);
  --cs-color-info: #2563EB;
  --cs-color-info-bg: rgba(37, 99, 235, 0.10);
  --cs-color-success: #16A34A;
  --cs-color-success-bg: rgba(22, 163, 74, 0.10);

  /* Data status */
  --cs-color-status-live: #059669;
  --cs-color-status-delayed: #D97706;
  --cs-color-status-closed: #64748B;
  --cs-color-status-abnormal: #EA580C;
  --cs-color-status-missing: #94A3B8;

  /* MA / indicators */
  --cs-color-ma-5: #A87521;
  --cs-color-ma-10: #2563EB;
  --cs-color-ma-20: #7C3AED;
  --cs-color-ma-60: #0891B2;
}
```

---

## 7. 通用行情语义色规则

### 7.1 硬规则

```text
上涨 / 正变化 / 净流入 / 涨停 / 高于基准 = 红色
下跌 / 负变化 / 净流出 / 跌停 / 低于基准 = 绿色
平盘 / 0变化 / 无方向 / 无数据方向 = 白色或灰白色
```

### 7.2 CSS 类

```css
.cs-market-up {
  color: var(--cs-color-market-up);
}

.cs-market-down {
  color: var(--cs-color-market-down);
}

.cs-market-flat {
  color: var(--cs-color-market-flat);
}

.cs-market-up-bg {
  background: var(--cs-color-market-up-bg);
}

.cs-market-down-bg {
  background: var(--cs-color-market-down-bg);
}

.cs-market-flat-bg {
  background: var(--cs-color-market-flat-bg);
}
```

### 7.3 通用场景规则

| 场景 | 规则 |
|---|---|
| CsqChangeValue | 正值红、负值绿、零值灰白 |
| CsqChangeBadge | 方向由 `direction` 控制，不由组件自行猜测业务 |
| CsqDataTable 数字列 | 金额、数量、比例默认中性色；涨跌字段按方向色 |
| CsqPieChartWithCallout | `rise` 红、`fall` 绿、`flat` 灰白、`neutral/custom` 按传入色 |
| CsqHeatMapGrid | `rise` 红系、`fall` 绿系、`flat` 灰白、`neutral` 中性、`warning` 橙色 |
| CsqChartTooltip | Tooltip 内正负值继续红绿 |
| Mock 数据 | `value`、`changeText`、`direction`、颜色必须一致 |

---

# 8. 通用组件状态 Token

### 8.1 状态枚举

组件库 Demo 必须覆盖：

```ts
type CsqComponentState =
  | "default"
  | "hover"
  | "active"
  | "selected"
  | "disabled"
  | "loading"
  | "empty"
  | "error"
  | "dataDelayed";
```

### 8.2 状态 Token

```css
:root {
  --cs-state-opacity-disabled: 0.44;
  --cs-state-opacity-loading: 0.68;

  --cs-state-bg-hover: var(--cs-color-surface-card-hover);
  --cs-state-bg-active: rgba(247, 199, 107, 0.10);
  --cs-state-bg-selected: var(--cs-color-brand-accent-bg);
  --cs-state-bg-disabled: rgba(100, 116, 139, 0.08);
  --cs-state-bg-loading: rgba(148, 163, 184, 0.10);
  --cs-state-bg-empty: rgba(148, 163, 184, 0.06);
  --cs-state-bg-error: var(--cs-color-risk-bg);
  --cs-state-bg-data-delayed: var(--cs-color-warning-bg);

  --cs-state-border-default: var(--cs-color-border-subtle);
  --cs-state-border-hover: var(--cs-color-border-hover);
  --cs-state-border-active: var(--cs-color-brand-accent-border);
  --cs-state-border-selected: var(--cs-color-brand-accent-border);
  --cs-state-border-disabled: rgba(148, 163, 184, 0.10);
  --cs-state-border-error: rgba(255, 138, 61, 0.34);
  --cs-state-border-data-delayed: rgba(245, 158, 11, 0.34);

  --cs-state-text-disabled: var(--cs-color-text-weak);
  --cs-state-text-empty: var(--cs-color-text-muted);
  --cs-state-text-error: var(--cs-color-risk);
  --cs-state-text-data-delayed: var(--cs-color-status-delayed);
}
```

### 8.3 状态使用规则

| 状态 | 背景 | 边框 | 文字 | 交互 |
|---|---|---|---|---|
| default | 默认组件背景 | 弱边框 | 主文字/次文字 | 正常 |
| hover | 轻微提亮 | hover 边框 | 不改变数据语义色 | 不触发业务动作 |
| active | 弱品牌金背景 | 品牌金边框 | 主文字 | 鼠标按下 / 当前激活 |
| selected | 品牌金弱背景 | 品牌金边框 | 品牌金或主文字 | 当前选中 |
| disabled | 禁用背景 | 禁用边框 | 弱文字 | 不可点击 |
| loading | 骨架背景 | 保留弱边框 | 不显示真实数据 | 保留布局 |
| empty | 空态背景 | 弱边框 | 弱文字 | 可展示下一步动作 |
| error | 风险弱背景 | 风险边框 | 风险文字 | 可重试 |
| data delayed | 警告弱背景 | 警告边框 | 警告文字 | 可查看数据说明 |

---

# 9. 通用容器 Token

## 9.1 CsqPanel

```css
:root {
  --cs-component-panel-bg: var(--cs-color-surface-panel);
  --cs-component-panel-border: 1px solid var(--cs-color-border-subtle);
  --cs-component-panel-radius: var(--cs-radius-panel);
  --cs-component-panel-padding: var(--cs-space-14);
  --cs-component-panel-gap: var(--cs-space-12);
  --cs-component-panel-shadow: var(--cs-shadow-none);
}
```

规则：

- `CsqPanel` 是所有高密度模块的基础容器。
- 默认不使用强阴影。
- 面板标题、内容、操作区之间保持紧凑间距。
- 不承担具体业务含义。

## 9.2 CsqSectionHeader

```css
:root {
  --cs-component-section-header-height: 32px;
  --cs-component-section-header-gap: var(--cs-space-8);
  --cs-component-section-title-size: var(--cs-font-size-14);
  --cs-component-section-title-weight: var(--cs-font-weight-semibold);
  --cs-component-section-desc-size: var(--cs-font-size-12);
  --cs-component-section-action-gap: var(--cs-space-8);
}
```

规则：

- 标题行高度建议 32px。
- 主标题左对齐。
- 说明文字不应长期占正文空间，应进入 `CsqHelpTooltip`。
- 操作区用于 RangeSwitch、按钮、状态说明等。

## 9.3 CsqHelpTooltip

```css
:root {
  --cs-component-help-size: 16px;
  --cs-component-help-icon-size: 12px;
  --cs-component-help-color: var(--cs-color-text-muted);
  --cs-component-help-color-hover: var(--cs-color-brand-accent);
  --cs-component-help-bg-hover: var(--cs-color-brand-accent-bg);
  --cs-component-help-radius: var(--cs-radius-pill);

  --cs-component-help-tooltip-bg: var(--cs-color-tooltip-bg);
  --cs-component-help-tooltip-border: 1px solid var(--cs-color-tooltip-border);
  --cs-component-help-tooltip-radius: var(--cs-radius-lg);
  --cs-component-help-tooltip-padding: 10px 12px;
  --cs-component-help-tooltip-width-max: 280px;
  --cs-component-help-tooltip-text: var(--cs-color-text-secondary);
  --cs-component-help-tooltip-z: var(--cs-z-tooltip);
}
```

规则：

- 圆圈问号尺寸 16px。
- hover 变为品牌金。
- Tooltip 最大宽度 280px。
- 深色主题下必须保证说明文字可读。
- Tooltip 不承载业务结论，只承载口径说明和字段解释。

## 9.4 CsqBadge

```css
:root {
  --cs-component-badge-height: 20px;
  --cs-component-badge-padding-x: 7px;
  --cs-component-badge-radius: var(--cs-radius-pill);
  --cs-component-badge-font-size: var(--cs-font-size-11);
  --cs-component-badge-gap: var(--cs-space-4);

  --cs-component-badge-bg-neutral: rgba(148, 163, 184, 0.12);
  --cs-component-badge-bg-rise: var(--cs-color-market-up-bg);
  --cs-component-badge-bg-fall: var(--cs-color-market-down-bg);
  --cs-component-badge-bg-flat: var(--cs-color-market-flat-bg);
  --cs-component-badge-bg-warning: var(--cs-color-warning-bg);
  --cs-component-badge-bg-brand: var(--cs-color-brand-accent-bg);
}
```

语义：

| semantic | 背景 | 文字 |
|---|---|---|
| neutral | `--cs-component-badge-bg-neutral` | 次级文字 |
| rise | `--cs-component-badge-bg-rise` | 上涨红 |
| fall | `--cs-component-badge-bg-fall` | 下跌绿 |
| flat | `--cs-component-badge-bg-flat` | 平盘灰白 |
| warning | `--cs-component-badge-bg-warning` | 警告色 |
| brand | `--cs-component-badge-bg-brand` | 品牌金 |

## 9.5 CsqStatusDot

```css
:root {
  --cs-component-status-dot-size: 7px;
  --cs-component-status-dot-ring-size: 11px;
  --cs-component-status-dot-live: var(--cs-color-status-live);
  --cs-component-status-dot-delayed: var(--cs-color-status-delayed);
  --cs-component-status-dot-closed: var(--cs-color-status-closed);
  --cs-component-status-dot-error: var(--cs-color-status-abnormal);
  --cs-component-status-dot-missing: var(--cs-color-status-missing);
}
```

## 9.6 CsqSkeleton

```css
:root {
  --cs-component-skeleton-bg: rgba(148, 163, 184, 0.08);
  --cs-component-skeleton-shine: rgba(148, 163, 184, 0.16);
  --cs-component-skeleton-radius: var(--cs-radius-md);
  --cs-component-skeleton-duration: 1.2s;
}
```

## 9.7 CsqEmptyState

```css
:root {
  --cs-component-empty-bg: var(--cs-state-bg-empty);
  --cs-component-empty-border: 1px dashed var(--cs-color-border-subtle);
  --cs-component-empty-radius: var(--cs-radius-card);
  --cs-component-empty-padding: var(--cs-space-16);
  --cs-component-empty-title-color: var(--cs-color-text-secondary);
  --cs-component-empty-desc-color: var(--cs-color-text-muted);
  --cs-component-empty-icon-color: var(--cs-color-text-weak);
}
```

## 9.8 CsqErrorState

```css
:root {
  --cs-component-error-bg: var(--cs-color-risk-bg);
  --cs-component-error-border: 1px solid var(--cs-state-border-error);
  --cs-component-error-radius: var(--cs-radius-card);
  --cs-component-error-padding: var(--cs-space-14);
  --cs-component-error-title-color: var(--cs-color-risk);
  --cs-component-error-desc-color: var(--cs-color-text-secondary);
}
```

---

# 10. 通用数据展示 Token

## 10.1 CsqMetricCard

```css
:root {
  --cs-component-metric-card-bg: var(--cs-color-surface-card);
  --cs-component-metric-card-border: 1px solid var(--cs-color-border-subtle);
  --cs-component-metric-card-radius: var(--cs-radius-card);
  --cs-component-metric-card-padding: var(--cs-space-12);
  --cs-component-metric-card-gap: var(--cs-space-6);

  --cs-component-metric-title-size: var(--cs-font-size-12);
  --cs-component-metric-title-color: var(--cs-color-text-secondary);
  --cs-component-metric-value-size: var(--cs-font-size-24);
  --cs-component-metric-value-weight: var(--cs-font-weight-bold);
  --cs-component-metric-unit-size: var(--cs-font-size-12);
  --cs-component-metric-unit-color: var(--cs-color-text-muted);
  --cs-component-metric-sub-size: var(--cs-font-size-11);
}
```

规则：

- 指标卡不绑定任何具体业务。
- 数值使用 `--cs-font-family-number`。
- 若数值带方向，必须通过 `direction` 映射到 rise/fall/flat。

## 10.2 CsqMetricSummaryGroup

```css
:root {
  --cs-component-metric-group-gap: var(--cs-space-10);
  --cs-component-metric-group-columns-min: 2;
  --cs-component-metric-group-columns-max: 5;
}
```

规则：

- 用于多个 `CsqMetricCard` 的组合。
- 列数由容器宽度和业务页面决定。
- Core Component 只定义布局能力，不定义卡片含义。

## 10.3 CsqChangeValue

```css
:root {
  --cs-component-change-font-family: var(--cs-font-family-number);
  --cs-component-change-font-size: var(--cs-font-size-13);
  --cs-component-change-font-weight: var(--cs-font-weight-semibold);
  --cs-component-change-up-color: var(--cs-color-market-up);
  --cs-component-change-down-color: var(--cs-color-market-down);
  --cs-component-change-flat-color: var(--cs-color-market-flat);
}
```

规则：

- `+1.25%` 红色。
- `-0.83%` 绿色。
- `0.00%` 白色/灰白色。
- 正数必须带 `+`，负数必须带 `-`。

## 10.4 CsqChangeBadge

```css
:root {
  --cs-component-change-badge-height: 22px;
  --cs-component-change-badge-padding-x: 8px;
  --cs-component-change-badge-radius: var(--cs-radius-pill);
  --cs-component-change-badge-font-size: var(--cs-font-size-12);
}
```

语义：

| direction | 背景 | 文字 |
|---|---|---|
| rise | `--cs-color-market-up-bg` | `--cs-color-market-up` |
| fall | `--cs-color-market-down-bg` | `--cs-color-market-down` |
| flat | `--cs-color-market-flat-bg` | `--cs-color-market-flat` |
| neutral | 中性弱背景 | 次级文字 |

## 10.5 CsqInfoRow

```css
:root {
  --cs-component-info-row-height: 28px;
  --cs-component-info-row-gap: var(--cs-space-8);
  --cs-component-info-label-color: var(--cs-color-text-muted);
  --cs-component-info-value-color: var(--cs-color-text-primary);
  --cs-component-info-meta-color: var(--cs-color-text-weak);
  --cs-component-info-row-border: 1px solid var(--cs-color-divider);
}
```

## 10.6 CsqLinkedMetricList

`CsqLinkedMetricList` 是通用“实体 + 指标”行式列表，不是“领涨股表现”专属组件。

```css
:root {
  --cs-component-linked-list-bg: transparent;
  --cs-component-linked-list-row-height: 34px;
  --cs-component-linked-list-row-gap: var(--cs-space-6);
  --cs-component-linked-list-row-padding-x: var(--cs-space-8);
  --cs-component-linked-list-row-radius: var(--cs-radius-md);
  --cs-component-linked-list-row-hover-bg: var(--cs-color-surface-card-hover);
  --cs-component-linked-list-row-selected-bg: var(--cs-color-brand-accent-bg);
  --cs-component-linked-list-row-selected-border: 1px solid var(--cs-color-brand-accent-border);

  --cs-component-linked-list-primary-size: var(--cs-font-size-13);
  --cs-component-linked-list-primary-weight: var(--cs-font-weight-semibold);
  --cs-component-linked-list-secondary-size: var(--cs-font-size-11);
  --cs-component-linked-list-secondary-color: var(--cs-color-text-muted);
  --cs-component-linked-list-meta-size: var(--cs-font-size-11);
  --cs-component-linked-list-meta-color: var(--cs-color-text-weak);
}
```

规则：

1. 每行一个实体；
2. 实体信息与指标信息同一行打通；
3. 行 hover 时整行高亮；
4. 支持标签、数值、状态混合展示；
5. 不绑定股票、板块、涨停、持仓等业务。

## 10.7 CsqProgressList

```css
:root {
  --cs-component-progress-list-row-height: 28px;
  --cs-component-progress-list-gap: var(--cs-space-6);
  --cs-component-progress-track-height: 6px;
  --cs-component-progress-track-bg: rgba(148, 163, 184, 0.14);
  --cs-component-progress-track-radius: var(--cs-radius-pill);
  --cs-component-progress-fill-neutral: var(--cs-color-brand-accent);
  --cs-component-progress-fill-rise: var(--cs-color-market-up);
  --cs-component-progress-fill-fall: var(--cs-color-market-down);
  --cs-component-progress-fill-flat: var(--cs-color-market-flat);
}
```

## 10.8 CsqStatusBadge

```css
:root {
  --cs-component-status-badge-height: 22px;
  --cs-component-status-badge-padding-x: 8px;
  --cs-component-status-badge-radius: var(--cs-radius-pill);
  --cs-component-status-badge-font-size: var(--cs-font-size-11);
}
```

---

# 11. 通用表格 Token

## 11.1 CsqDataTable

```css
:root {
  --cs-table-bg: var(--cs-color-table-bg);
  --cs-table-border: 1px solid var(--cs-color-border-subtle);
  --cs-table-radius: var(--cs-radius-card);

  --cs-table-header-height: 32px;
  --cs-table-header-bg: var(--cs-color-table-header-bg);
  --cs-table-header-color: var(--cs-color-text-secondary);
  --cs-table-header-font-size: var(--cs-font-size-12);
  --cs-table-header-font-weight: var(--cs-font-weight-semibold);

  --cs-table-row-height: 34px;
  --cs-table-row-height-compact: 30px;
  --cs-table-row-height-comfortable: 38px;
  --cs-table-row-bg: var(--cs-color-table-row-bg);
  --cs-table-row-alt-bg: var(--cs-color-table-row-alt-bg);
  --cs-table-row-hover-bg: var(--cs-color-table-row-hover-bg);
  --cs-table-row-selected-bg: var(--cs-color-table-row-selected-bg);

  --cs-table-cell-padding-x: 8px;
  --cs-table-cell-font-size: var(--cs-font-size-12);
  --cs-table-cell-color: var(--cs-color-text-primary);
  --cs-table-cell-muted-color: var(--cs-color-text-muted);
}
```

## 11.2 CsqRankTable

```css
:root {
  --cs-rank-table-row-height: 32px;
  --cs-rank-table-visible-rows-default: 10;
  --cs-rank-table-rank-col-width: 42px;
  --cs-rank-table-name-col-min-width: 120px;
  --cs-rank-table-number-col-width-sm: 72px;
  --cs-rank-table-number-col-width-md: 88px;
  --cs-rank-table-number-col-width-lg: 104px;
}
```

规则：

- 支持 TopN，不绑定股票业务；
- 排名列中性色；
- 名称列左对齐；
- 数字列右对齐；
- 方向列由 `direction` 决定颜色；
- hover 行背景使用中性色提亮，不整行变红/绿；
- selected 行使用品牌金弱背景。

## 11.3 CsqColumnHeader

```css
:root {
  --cs-table-column-header-gap: var(--cs-space-4);
  --cs-table-column-header-sort-icon-size: 12px;
  --cs-table-column-header-help-size: 14px;
}
```

## 11.4 CsqTableRow

```css
:root {
  --cs-table-row-clickable-cursor: pointer;
  --cs-table-row-active-bg: rgba(247, 199, 107, 0.12);
}
```

## 11.5 CsqTableCellNumber

```css
:root {
  --cs-table-number-font-family: var(--cs-font-family-number);
  --cs-table-number-font-size: var(--cs-font-size-12);
  --cs-table-number-font-weight: var(--cs-font-weight-medium);
}
```

格式规则：

| 类型 | 格式 |
|---|---|
| amount | `1.23亿`、`862.4万`、`1.02万亿` |
| volume | `12.35万手`、`2.18亿股` |
| percent | `+1.25%`、`-0.83%`、`0.00%` |
| ratio | `1.26`、`0.82` |
| count | `1,236` |
| empty | `--` |

表格状态：

| 状态 | 规则 |
|---|---|
| loading | 表格保留表头，正文显示骨架行 |
| empty | 表头保留，正文显示空态说明 |
| error | 表头保留，正文显示局部错误块与重试 |
| data delayed | 表格右上角或标题区显示延迟标签 |

---

# 12. 通用图表 Token

## 12.1 图表基础

```css
:root {
  --cs-chart-bg: var(--cs-color-chart-bg);
  --cs-chart-panel-bg: var(--cs-color-chart-panel-bg);
  --cs-chart-radius: var(--cs-radius-card);
  --cs-chart-padding: 10px;
  --cs-chart-title-size: var(--cs-font-size-13);
  --cs-chart-title-weight: var(--cs-font-weight-semibold);
}
```

## 12.2 坐标轴与网格线

```css
:root {
  --cs-chart-axis-color: var(--cs-color-chart-axis);
  --cs-chart-axis-line-width: 1px;
  --cs-chart-axis-label-color: var(--cs-color-chart-label);
  --cs-chart-axis-label-size: var(--cs-font-size-11);

  --cs-chart-grid-color: var(--cs-color-chart-grid);
  --cs-chart-grid-line-width: 1px;
  --cs-chart-grid-dash: 2 4;
  --cs-chart-zero-axis-color: rgba(221, 230, 242, 0.32);
  --cs-chart-zero-axis-width: 1px;
}
```

## 12.3 Crosshair

```css
:root {
  --cs-chart-crosshair-color: var(--cs-color-chart-crosshair);
  --cs-chart-crosshair-width: 1px;
  --cs-chart-crosshair-dash: 3 3;
  --cs-chart-crosshair-label-bg: var(--cs-color-tooltip-bg);
  --cs-chart-crosshair-label-color: var(--cs-color-text-primary);
  --cs-chart-crosshair-label-border: 1px solid var(--cs-color-tooltip-border);
}
```

## 12.4 CsqChartTooltip

```css
:root {
  --cs-chart-tooltip-bg: var(--cs-color-tooltip-bg);
  --cs-chart-tooltip-border: 1px solid var(--cs-color-tooltip-border);
  --cs-chart-tooltip-radius: var(--cs-radius-lg);
  --cs-chart-tooltip-padding: 10px 12px;
  --cs-chart-tooltip-shadow: var(--cs-shadow-tooltip);
  --cs-chart-tooltip-font-size: var(--cs-font-size-12);
  --cs-chart-tooltip-title-color: var(--cs-color-text-primary);
  --cs-chart-tooltip-label-color: var(--cs-color-text-muted);
  --cs-chart-tooltip-value-color: var(--cs-color-text-primary);
  --cs-chart-tooltip-z: var(--cs-z-tooltip);
}
```

## 12.5 CsqRangeSwitch

```css
:root {
  --cs-component-range-switch-height: 26px;
  --cs-component-range-switch-padding-x: 8px;
  --cs-component-range-switch-gap: 2px;
  --cs-component-range-switch-radius: var(--cs-radius-md);
  --cs-component-range-switch-bg: rgba(148, 163, 184, 0.08);
  --cs-component-range-switch-border: 1px solid var(--cs-color-border-subtle);

  --cs-component-range-switch-item-height: 22px;
  --cs-component-range-switch-item-padding-x: 8px;
  --cs-component-range-switch-item-font-size: var(--cs-font-size-12);
  --cs-component-range-switch-item-color: var(--cs-color-text-muted);
  --cs-component-range-switch-item-hover-bg: var(--cs-color-surface-card-hover);
  --cs-component-range-switch-item-hover-color: var(--cs-color-text-primary);
  --cs-component-range-switch-item-selected-bg: var(--cs-color-brand-accent-bg);
  --cs-component-range-switch-item-selected-color: var(--cs-color-brand-accent);
  --cs-component-range-switch-item-disabled-color: var(--cs-color-text-weak);
}
```

## 12.6 CsqMiniTrendChart

```css
:root {
  --cs-chart-mini-height: 30px;
  --cs-chart-mini-line-width: 1.4px;
  --cs-chart-mini-fill-opacity: 0.10;
}
```

## 12.7 CsqHistoryTrendChart

```css
:root {
  --cs-chart-history-height: 180px;
  --cs-chart-history-height-compact: 142px;
  --cs-chart-history-line-width: 1.6px;
  --cs-chart-history-point-size: 4px;
  --cs-chart-history-point-hover-size: 6px;
}
```

## 12.8 CsqDistributionChart

```css
:root {
  --cs-chart-distribution-bar-gap: 4px;
  --cs-chart-distribution-bar-radius: var(--cs-radius-xs);
  --cs-chart-distribution-up: var(--cs-color-market-up);
  --cs-chart-distribution-down: var(--cs-color-market-down);
  --cs-chart-distribution-flat: var(--cs-color-market-flat-muted);
}
```

## 12.9 CsqBarChart

```css
:root {
  --cs-chart-bar-gap: 6px;
  --cs-chart-bar-group-gap: 12px;
  --cs-chart-bar-radius: 3px 3px 0 0;
  --cs-chart-bar-up: var(--cs-color-market-up);
  --cs-chart-bar-down: var(--cs-color-market-down);
  --cs-chart-bar-flat: var(--cs-color-market-flat-muted);
  --cs-chart-bar-neutral: var(--cs-color-brand-accent);
}
```

## 12.10 CsqChartSplitPanel

```css
:root {
  --cs-chart-split-gap: var(--cs-space-12);
  --cs-chart-split-left-min-width: 180px;
  --cs-chart-split-right-min-width: 280px;
  --cs-chart-split-left-ratio: 0.36;
  --cs-chart-split-right-ratio: 0.64;
}
```

规则：

- `CsqChartSplitPanel` 是通用左右图表容器；
- 不绑定资金流、饼图或趋势图业务；
- 左右比例可由组件 props 或 CSS 覆盖；
- 默认左侧适合饼图 / 小图，右侧适合趋势图。

---

# 13. CsqPieChartWithCallout 视觉规则

## 13.1 组件定位

`CsqPieChartWithCallout` 是通用折线标注饼图，用于展示分类占比结构。

它不绑定资金业务，不绑定订单类型，不绑定市场总览。

## 13.2 Token

```css
:root {
  --cs-chart-pie-size: 168px;
  --cs-chart-pie-size-sm: 132px;
  --cs-chart-pie-size-lg: 204px;

  --cs-chart-pie-inner-radius-ratio: 0.52;
  --cs-chart-pie-slice-gap: 2px;
  --cs-chart-pie-slice-stroke: var(--cs-color-bg-page);
  --cs-chart-pie-slice-stroke-width: 2px;
  --cs-chart-pie-slice-hover-opacity: 0.92;
  --cs-chart-pie-slice-hover-filter: brightness(1.08);

  --cs-chart-pie-percent-label-color: #FFFFFF;
  --cs-chart-pie-percent-label-size: var(--cs-font-size-11);
  --cs-chart-pie-percent-label-weight: var(--cs-font-weight-semibold);
  --cs-chart-pie-percent-label-shadow: 0 1px 2px rgba(0, 0, 0, 0.45);

  --cs-chart-pie-callout-line-color: rgba(203, 213, 225, 0.58);
  --cs-chart-pie-callout-line-width: 1px;
  --cs-chart-pie-callout-dot-size: 3px;
  --cs-chart-pie-callout-text-size: var(--cs-font-size-11);
  --cs-chart-pie-callout-label-color: var(--cs-color-text-secondary);
  --cs-chart-pie-callout-value-color: var(--cs-color-text-primary);

  --cs-chart-pie-center-bg: transparent;
  --cs-chart-pie-center-text-display: none;
}
```

## 13.3 饼图尺寸

| 尺寸 | Token | 用途 |
|---|---|---|
| 小 | `--cs-chart-pie-size-sm` | 小容器、组件 Demo 紧凑区 |
| 标准 | `--cs-chart-pie-size` | 默认展示 |
| 大 | `--cs-chart-pie-size-lg` | 图表页或宽容器 |

## 13.4 饼块颜色语义

| colorSemantic | 颜色 |
|---|---|
| `rise` | `--cs-color-market-up` |
| `fall` | `--cs-color-market-down` |
| `flat` | `--cs-color-market-flat` |
| `neutral` | `--cs-color-brand-accent` 或中性蓝灰 |
| `warning` | `--cs-color-warning` |
| `custom` | 由调用方显式传入 |

## 13.5 饼块面积

饼块面积只由 `value` 的绝对数值或传入权重决定。

组件不判断业务含义。

```ts
interface CsqPieChartWithCalloutItem {
  key: string;
  label: string;
  value: number;
  percent?: number;
  valueText?: string;
  colorSemantic?: "rise" | "fall" | "flat" | "neutral" | "warning" | "custom";
  color?: string;
}
```

## 13.6 饼块上占比文字

规则：

1. 占比文字放在对应饼块上；
2. 占比文字必须是白色；
3. 占比文字不放在图例里；
4. 占比文字不放在外部折线标注里；
5. 占比文字不放在饼图中心；
6. 小于 8% 的饼块可隐藏内部占比，改由 callout 承载名称与数值；
7. 占比文字需要有轻微阴影，保证在红/绿/中性色块上可读。

## 13.7 外部 Callout 折线

规则：

1. 每个饼块可引出一条折线；
2. 折线从饼块外缘引出；
3. 折线有一个转折点；
4. 折线末端展示 label 与 valueText；
5. 正值 valueText 可使用上涨红；
6. 负值 valueText 可使用下跌绿；
7. 零值 valueText 使用灰白；
8. callout 不遮挡饼块上的白色占比；
9. callout 不侵入相邻图表区域；
10. 小空间下可只显示两侧主 callout，其余进入 Tooltip。

## 13.8 饼图中心留空规则

默认：

```text
centerContent = null
```

禁止中心显示：

```text
净额结构
absAmount
value
debug
任意英文调试字段
```

允许：

- 空心留白；
- 极简装饰中心点；
- 业务页面如需中心文案，必须由页面级设计单独确认，不作为默认规则。

## 13.9 Tooltip

```css
:root {
  --cs-chart-pie-tooltip-bg: var(--cs-chart-tooltip-bg);
  --cs-chart-pie-tooltip-border: var(--cs-chart-tooltip-border);
  --cs-chart-pie-tooltip-radius: var(--cs-chart-tooltip-radius);
  --cs-chart-pie-tooltip-padding: var(--cs-chart-tooltip-padding);
}
```

Tooltip 内容建议：

```text
分类名称
数值
占比
方向 / 状态
```

---

# 14. CsqHeatMapGrid 视觉规则

## 14.1 组件定位

`CsqHeatMapGrid` 是通用热力图网格组件，不绑定板块业务。

## 14.2 Token

```css
:root {
  --cs-heatmap-grid-gap: 6px;
  --cs-heatmap-grid-cell-min-width: 72px;
  --cs-heatmap-grid-cell-min-height: 46px;
  --cs-heatmap-grid-cell-radius: var(--cs-radius-md);
  --cs-heatmap-grid-cell-padding: 6px;
  --cs-heatmap-grid-cell-border: 1px solid rgba(255, 255, 255, 0.04);
  --cs-heatmap-grid-cell-hover-border: 1px solid var(--cs-color-border-hover);
  --cs-heatmap-grid-cell-selected-border: 1px solid var(--cs-color-brand-accent-border);
  --cs-heatmap-grid-cell-empty-bg: rgba(100, 116, 139, 0.08);

  --cs-heatmap-cell-label-size: var(--cs-font-size-12);
  --cs-heatmap-cell-label-weight: var(--cs-font-weight-semibold);
  --cs-heatmap-cell-value-size: var(--cs-font-size-11);
  --cs-heatmap-cell-value-weight: var(--cs-font-weight-medium);
}
```

## 14.3 语义色

```css
:root {
  --cs-heatmap-rise-1: rgba(255, 77, 90, 0.18);
  --cs-heatmap-rise-2: rgba(255, 77, 90, 0.32);
  --cs-heatmap-rise-3: rgba(255, 77, 90, 0.52);
  --cs-heatmap-rise-4: rgba(255, 77, 90, 0.74);

  --cs-heatmap-fall-1: rgba(21, 199, 132, 0.18);
  --cs-heatmap-fall-2: rgba(21, 199, 132, 0.32);
  --cs-heatmap-fall-3: rgba(21, 199, 132, 0.52);
  --cs-heatmap-fall-4: rgba(21, 199, 132, 0.74);

  --cs-heatmap-flat: rgba(221, 230, 242, 0.14);
  --cs-heatmap-neutral: rgba(90, 167, 255, 0.18);
  --cs-heatmap-warning: rgba(245, 158, 11, 0.18);
}
```

## 14.4 N 行 × M 列

```ts
interface CsqHeatMapGridProps {
  rows: number;
  columns: number;
  items: Array<{
    key: string;
    label: string;
    value?: number;
    valueText?: string;
    semantic?: "rise" | "fall" | "flat" | "neutral" | "warning";
    level?: 1 | 2 | 3 | 4;
    rowIndex?: number;
    columnIndex?: number;
    tooltip?: string;
  }>;
}
```

规则：

1. 支持任意 N 行 × M 列；
2. Demo 中建议展示 5 行 × 4 列，但组件不固化该尺寸；
3. 空格子展示占位背景；
4. hover 时提高边框和亮度；
5. selected 使用品牌金边框；
6. Tooltip 使用 `CsqChartTooltip` 或通用 Tooltip Token；
7. 不允许热力图出现绿涨红跌。

---

# 15. 通用组件 Demo 页面 Token

```css
:root {
  --cs-demo-page-max-width: 1680px;
  --cs-demo-page-padding-x: 24px;
  --cs-demo-page-padding-y: 20px;
  --cs-demo-section-gap: 20px;
  --cs-demo-component-grid-gap: 16px;
  --cs-demo-component-card-min-height: 220px;
  --cs-demo-component-preview-bg: var(--cs-color-surface-panel-subtle);
  --cs-demo-component-code-bg: rgba(2, 6, 23, 0.42);
}
```

Demo 结构建议：

```text
财势乾坤通用组件库 Demo
├── 0. Design Token Overview
├── 1. Foundation Components
├── 2. Navigation Components
├── 3. Data Display Components
├── 4. Table Components
├── 5. Chart Components
├── 6. Pattern Examples
└── 7. Component States
```

每个组件卡片结构：

```text
组件名
中文名
组件类型
使用场景
关键 Props
状态
Design Token
实际预览
禁止误用
```

---

# 16. Core Component 对应 Token 映射

| Core Component | 主要 Token |
|---|---|
| `CsqPanel` | `--cs-component-panel-*`、`--cs-color-surface-panel`、`--cs-color-border-subtle` |
| `CsqSectionHeader` | `--cs-component-section-*`、`--cs-font-size-14`、`--cs-color-text-primary` |
| `CsqHelpTooltip` | `--cs-component-help-*`、`--cs-color-tooltip-*`、`--cs-z-tooltip` |
| `CsqBadge` | `--cs-component-badge-*`、`--cs-color-market-*`、`--cs-color-warning` |
| `CsqStatusDot` | `--cs-component-status-dot-*`、`--cs-color-status-*` |
| `CsqSkeleton` | `--cs-component-skeleton-*` |
| `CsqEmptyState` | `--cs-component-empty-*` |
| `CsqErrorState` | `--cs-component-error-*` |
| `CsqMetricCard` | `--cs-component-metric-*`、`--cs-font-family-number` |
| `CsqMetricSummaryGroup` | `--cs-component-metric-group-*` |
| `CsqChangeValue` | `--cs-component-change-*` |
| `CsqChangeBadge` | `--cs-component-change-badge-*`、`--cs-component-badge-*` |
| `CsqInfoRow` | `--cs-component-info-*` |
| `CsqLinkedMetricList` | `--cs-component-linked-list-*` |
| `CsqProgressList` | `--cs-component-progress-*` |
| `CsqStatusBadge` | `--cs-component-status-badge-*` |
| `CsqDataTable` | `--cs-table-*` |
| `CsqRankTable` | `--cs-rank-table-*`、`--cs-table-*` |
| `CsqColumnHeader` | `--cs-table-column-header-*` |
| `CsqTableRow` | `--cs-table-row-*` |
| `CsqTableCellNumber` | `--cs-table-number-*` |
| `CsqMiniTrendChart` | `--cs-chart-mini-*` |
| `CsqHistoryTrendChart` | `--cs-chart-history-*`、`--cs-chart-axis-*`、`--cs-chart-grid-*` |
| `CsqDistributionChart` | `--cs-chart-distribution-*` |
| `CsqBarChart` | `--cs-chart-bar-*` |
| `CsqPieChartWithCallout` | `--cs-chart-pie-*` |
| `CsqHeatMapGrid` | `--cs-heatmap-*` |
| `CsqChartSplitPanel` | `--cs-chart-split-*` |
| `CsqChartTooltip` | `--cs-chart-tooltip-*` |
| `CsqCrosshairOverlay` | `--cs-chart-crosshair-*` |

---

# 17. Pattern Example 对应 Token 映射

Pattern Example 不作为 Core Component 契约，只展示通用组件在行情场景中的组合方式。

| Pattern | 组合组件 | Token 映射说明 |
|---|---|---|
| `PatternMarketSummary` | `CsqMetricSummaryGroup` + `CsqInfoRow` | 使用指标组、信息行、状态 Token；不固化市场总览业务字段 |
| `PatternIndexGrid` | `CsqMetricCard` + `CsqChangeValue` + `CsqMiniTrendChart` | 使用卡片、涨跌值、小趋势图 Token |
| `PatternLimitStructure` | `CsqProgressList` + `CsqLinkedMetricList` | 使用进度列表、实体指标行式列表 Token |
| `PatternMoneyFlowSplit` | `CsqPieChartWithCallout` + `CsqHistoryTrendChart` + `CsqChartSplitPanel` | 使用饼图 callout、趋势图、左右分栏 Token |
| `PatternSectorHeatMap` | `CsqHeatMapGrid` | 使用热力图网格 Token；可模拟 5×4，但组件不固化 |
| `PatternRankBoard` | `CsqRankTable` + `CsqTabs` | 使用排名表格和切换控件 Token |

---

# 18. 对 03《04-component-guidelines.md》的 Token 使用建议

1. 组件规范中的 Core Component 必须使用本文件定义的 `Csq*` 命名。
2. 组件 Props 应保持抽象，不绑定具体页面或 API response。
3. 具体业务页面的字段映射应通过 adapter 完成，例如：

```text
页面 API response → adapter → Csq Component Props
```

4. `CsqPieChartWithCallout` 不得命名为资金专属组件。
5. `CsqHeatMapGrid` 不得命名为板块专属组件。
6. `CsqLinkedMetricList` 不得命名为领涨股或涨停表现专属组件。
7. Pattern Example 可以使用行情 mock 数据，但必须标记为 Pattern，不进入 Core Component 契约。
8. 组件状态必须覆盖 default、hover、active、selected、disabled、loading、empty、error、data delayed。
9. 所有颜色必须通过 Token 获取，不得在组件内硬编码红绿。
10. 中国市场红涨绿跌应作为组件库默认方向色规则。

---

# 19. 对 02 `component-library-demo-v1.html` 的视觉约束

1. Demo 文件必须是单文件 HTML/CSS/JS。
2. Demo 页面标题为“财势乾坤通用组件库 Demo”。
3. 深色主题优先。
4. 不要求本轮实现完整浅色主题，但 CSS Token 结构必须可切换。
5. 每个组件卡片必须展示：
   - 组件名；
   - 中文名；
   - 组件类型；
   - 使用场景；
   - Props 摘要；
   - 状态；
   - Design Token；
   - 实际预览；
   - 禁止误用。
6. Demo 必须展示组件状态：
   - default；
   - hover；
   - active；
   - selected；
   - disabled；
   - loading；
   - empty；
   - error；
   - data delayed。
7. `CsqPieChartWithCallout` 必须展示：
   - 饼块上白色占比；
   - 外部 callout 折线；
   - callout 文字；
   - 中心留空；
   - 禁止中心显示调试字段。
8. `CsqHeatMapGrid` 必须展示：
   - N 行 × M 列；
   - rise / fall / flat / neutral / warning；
   - hover；
   - selected；
   - Tooltip；
   - 空格子占位。
9. `CsqRankTable` 必须展示：
   - 高密度行高；
   - 表头；
   - hover 行；
   - selected 行；
   - 数字列右对齐；
   - 涨跌色单元格；
   - loading / empty / error 表格态。
10. `CsqLinkedMetricList` 必须展示：
    - 每行一个实体；
    - 实体 + 指标同一行；
    - 标签；
    - hover 整行高亮；
    - 不绑定具体业务名称。
11. Mock 数据必须真实感，但只作为组件抽象样例，不作为 API 契约。
12. Demo 不得使用廉价大屏风、霓虹风、低幼插画。
13. 红涨绿跌必须正确。

---

# 20. 本轮组件库 Demo Token 修改摘要

1. 新增通用组件状态 Token：default、hover、active、selected、disabled、loading、empty、error、data delayed。
2. 新增通用容器 Token：`CsqPanel`、`CsqSectionHeader`、`CsqHelpTooltip`、`CsqBadge`、`CsqStatusDot`、`CsqSkeleton`、`CsqEmptyState`、`CsqErrorState`。
3. 新增通用数据展示 Token：`CsqMetricCard`、`CsqMetricSummaryGroup`、`CsqChangeValue`、`CsqChangeBadge`、`CsqInfoRow`、`CsqLinkedMetricList`、`CsqProgressList`、`CsqStatusBadge`。
4. 新增通用表格 Token：`CsqDataTable`、`CsqRankTable`、`CsqColumnHeader`、`CsqTableRow`、`CsqTableCellNumber`。
5. 新增通用图表 Token：`CsqMiniTrendChart`、`CsqHistoryTrendChart`、`CsqDistributionChart`、`CsqBarChart`、`CsqPieChartWithCallout`、`CsqHeatMapGrid`、`CsqChartSplitPanel`、`CsqChartTooltip`、`CsqCrosshairOverlay`。
6. 明确 `CsqPieChartWithCallout` 是通用饼图，不绑定资金业务。
7. 明确 `CsqHeatMapGrid` 是通用热力图，不绑定板块业务。
8. 明确 `CsqLinkedMetricList` 是通用“实体 + 指标”行式列表，不绑定领涨股或涨停表现业务。
9. 强化红涨绿跌、平盘白色/灰白色规则。
10. 保留既有市场总览已确认内容，但本轮不新增市场总览专属 Token。

---

# 21. 本轮未修改区域说明

本轮未主动修改以下已确认内容：

1. 项目产品名称；
2. A 股优先原则；
3. 深色主题默认策略；
4. 浅色主题 Token 结构；
5. 红涨绿跌规则；
6. 金色品牌强调色；
7. 市场总览已确认的页面级布局约束；
8. 市场总览 TopMarketBar / Breadcrumb / PageHeader / ShortcutBar 约束；
9. 市场总览主要指数清单和排序；
10. 市场总览自动刷新默认 10s；
11. 市场总览板块热力图入口 route 暂空；
12. 既有图表坐标轴、Tooltip、crosshair 基础规则。

说明：

```text
本轮新增的是通用组件库 Demo 所需 Token，不代表修改市场总览业务页面结构。
```

---

# 22. 待产品总控确认问题

1. `Csq` 是否正式作为财势乾坤组件库统一前缀？
2. CSS Token 前缀是否继续保持 `--cs-*`，不新增 `--csq-*`？
3. Core Component 与 Pattern Example 的边界是否认可？
4. `component-library-demo-v1.html` 是否作为后续 Codex 组件实现的标准输入？
5. 组件库 Demo v1 是否需要展示浅色主题预览，还是仅保留浅色 Token 结构？
6. 是否需要在 Demo 中展示移动端 / 窄屏状态？
7. 组件状态是否需要做成可交互切换，还是静态展示即可？
8. 是否需要将组件注册表同步维护在 `04-component-guidelines.md` 中？
9. `CsqPieChartWithCallout` 是否默认允许中心留空，业务页面如需中心文案再单独确认？
10. `CsqHeatMapGrid` 的默认 Demo 是否使用 5×4，还是展示更多 N×M 示例？

---

## 23. 下载与保存路径

本轮输出文件名：

```text
03-design-tokens.md
```

建议放置到 Google Drive：

```text
财势乾坤/设计/03-design-tokens.md
```

---

## 24. 总结

财势乾坤通用组件库 Demo 的 Design Token 修订目标，是在不破坏既有市场总览页面级规范的前提下，将已经多轮验证过的 UI 能力抽象为可复用的组件级 Token。

本轮最重要的边界是：

```text
通用组件库可以服务行情软件场景，但不能绑定具体业务页面、具体 API 或具体数据源。
```

第一版组件库 Demo 应保持克制，优先覆盖 P0 阶段已经验证过的通用 UI 能力，统一命名、状态、密度、图表、表格、卡片、Tooltip、Callout 和热力图表达，为后续 Codex 与前端工程实现提供稳定输入。


---

---

# 25. 市场总览 / 连板天梯 / 标准股票卡片视觉规则（Review v7 修订）

> 本节仅服务 `市场总览 / 连板天梯 / 标准股票卡片`。  
> 本节正式替代 Review v6 的“股票代码右上角 + 主体 2 行 × 3 列”方案。  
> 本节不修改 TopMarketBar、Breadcrumb、PageHeader、ShortcutBar、今日市场客观总结、主要指数、涨跌分布、市场风格、成交额总览、大盘资金流向、榜单速览、涨跌停统计与分布、板块速览、连板天梯层级结构、连板天梯展开 / 收起逻辑、页面整体主题、全局字体或页面整体布局顺序。

## 25.1 Review v7 设计边界

Review v7 只处理连板天梯中的标准股票卡片视觉结构，不改变 Review v5 / v6 已确认的连板天梯层级逻辑。

本轮修改目标：

1. 用户新截图正式替代上一轮股票卡片方案；
2. 废弃上一轮“股票代码右上角角标 + 主体 2 行 × 3 列机械网格”的结构；
3. 新版卡片采用横向三分区结构：左侧识别区 / 中间行情事实区 / 右侧标签区；
4. 股票代码改为左上角胶囊标签；
5. 字段集合不变，仍为股票代码、股票名称、最新价、涨幅、所属板块、板上成交额、N天M板/板型；
6. 保持当前市场总览深色金融终端风格；
7. 不修改连板天梯层级结构、展开/收起逻辑、五板以上规则。

## 25.2 新版标准股票卡片 Token

```css
:root {
  /* Stock compact card - Review v7 */
  --cs-stock-card-width: 176px;
  --cs-stock-card-min-width: 160px;
  --cs-stock-card-height: 82px;
  --cs-stock-card-padding-x: 10px;
  --cs-stock-card-padding-y: 8px;
  --cs-stock-card-radius: var(--cs-radius-card);
  --cs-stock-card-border-width: 1px;

  /* Horizontal zones */
  --cs-stock-card-zone-gap: 8px;
  --cs-stock-card-left-zone-width: 1.08fr;
  --cs-stock-card-center-zone-width: 0.88fr;
  --cs-stock-card-right-zone-width: 0.96fr;
  --cs-stock-card-zone-row-gap: 5px;

  /* Code pill */
  --cs-stock-card-code-pill-height: 17px;
  --cs-stock-card-code-pill-padding-x: 6px;
  --cs-stock-card-code-pill-font-size: var(--cs-font-size-10);
  --cs-stock-card-code-pill-margin-bottom: 5px;

  /* Field sizes */
  --cs-stock-card-name-font-size: var(--cs-font-size-13);
  --cs-stock-card-name-font-weight: var(--cs-font-weight-semibold);
  --cs-stock-card-price-font-size: var(--cs-font-size-12);
  --cs-stock-card-price-font-weight: var(--cs-font-weight-semibold);
  --cs-stock-card-change-font-size: var(--cs-font-size-12);
  --cs-stock-card-change-font-weight: var(--cs-font-weight-bold);
  --cs-stock-card-meta-font-size: var(--cs-font-size-11);
  --cs-stock-card-board-amount-font-size: var(--cs-font-size-11);
  --cs-stock-card-streak-tag-font-size: var(--cs-font-size-11);
  --cs-stock-card-streak-tag-height: 18px;
  --cs-stock-card-streak-tag-padding-x: 7px;
}

[data-theme="dark"] {
  --cs-stock-card-bg: rgba(18, 27, 44, 0.92);
  --cs-stock-card-bg-hover: rgba(24, 34, 53, 0.96);
  --cs-stock-card-bg-active: rgba(21, 30, 48, 0.98);
  --cs-stock-card-bg-selected: rgba(247, 199, 107, 0.08);
  --cs-stock-card-border: rgba(148, 163, 184, 0.16);
  --cs-stock-card-border-hover: rgba(247, 199, 107, 0.34);
  --cs-stock-card-border-active: rgba(247, 199, 107, 0.48);
  --cs-stock-card-border-selected: rgba(247, 199, 107, 0.54);
  --cs-stock-card-shadow-hover: 0 8px 20px rgba(0, 0, 0, 0.24);

  --cs-stock-card-name-text: var(--cs-color-text-primary);
  --cs-stock-card-code-pill-text: rgba(168, 180, 198, 0.80);
  --cs-stock-card-code-pill-bg: rgba(148, 163, 184, 0.08);
  --cs-stock-card-code-pill-border: rgba(148, 163, 184, 0.12);
  --cs-stock-card-sector-text: var(--cs-color-text-secondary);
  --cs-stock-card-board-amount-text: rgba(229, 237, 248, 0.84);
  --cs-stock-card-streak-tag-text: var(--cs-color-brand-accent);
  --cs-stock-card-streak-tag-bg: rgba(247, 199, 107, 0.10);
  --cs-stock-card-streak-tag-border: rgba(247, 199, 107, 0.28);
}

[data-theme="light"] {
  --cs-stock-card-bg: #FFFFFF;
  --cs-stock-card-bg-hover: #F8FAFC;
  --cs-stock-card-bg-active: #F1F5F9;
  --cs-stock-card-bg-selected: rgba(201, 154, 61, 0.08);
  --cs-stock-card-border: rgba(15, 23, 42, 0.12);
  --cs-stock-card-border-hover: rgba(201, 154, 61, 0.36);
  --cs-stock-card-border-active: rgba(201, 154, 61, 0.48);
  --cs-stock-card-border-selected: rgba(201, 154, 61, 0.54);
  --cs-stock-card-shadow-hover: 0 8px 18px rgba(15, 23, 42, 0.10);

  --cs-stock-card-name-text: var(--cs-color-text-primary);
  --cs-stock-card-code-pill-text: rgba(71, 85, 105, 0.74);
  --cs-stock-card-code-pill-bg: rgba(15, 23, 42, 0.04);
  --cs-stock-card-code-pill-border: rgba(15, 23, 42, 0.10);
  --cs-stock-card-sector-text: var(--cs-color-text-secondary);
  --cs-stock-card-board-amount-text: rgba(15, 23, 42, 0.76);
  --cs-stock-card-streak-tag-text: var(--cs-color-brand-accent);
  --cs-stock-card-streak-tag-bg: rgba(201, 154, 61, 0.10);
  --cs-stock-card-streak-tag-border: rgba(201, 154, 61, 0.28);
}
```

说明：

- `--cs-stock-card-width` 建议为 `176px`，用于容纳三分区结构；
- 局部空间紧张时可降级至 `--cs-stock-card-min-width: 160px`；
- 该调整只影响连板天梯标准股票卡片，不修改全局卡片宽度；
- 股票代码胶囊从上一轮右上角角标改为左上角胶囊，旧的 `code-badge-right` 方案不再作为默认结构使用。

## 25.3 新版标准股票卡片整体规则

新版股票卡片必须遵守当前市场总览深色金融终端风格。

用户新截图只用于确定：

1. 信息排布；
2. 三分区结构；
3. 视觉层级关系。

不得照搬截图中的：

1. 浅色背景；
2. 蓝色边框；
3. 非系统字体；
4. 示例图中的具体装饰元素；
5. 与当前市场总览不一致的按钮或高亮样式。

推荐 CSS：

```css
.cs-stock-compact-card {
  width: var(--cs-stock-card-width);
  min-width: var(--cs-stock-card-min-width);
  min-height: var(--cs-stock-card-height);
  padding: var(--cs-stock-card-padding-y) var(--cs-stock-card-padding-x);
  border-radius: var(--cs-stock-card-radius);
  border: var(--cs-stock-card-border-width) solid var(--cs-stock-card-border);
  background: var(--cs-stock-card-bg);
  cursor: pointer;
  display: grid;
  grid-template-columns:
    minmax(0, var(--cs-stock-card-left-zone-width))
    minmax(0, var(--cs-stock-card-center-zone-width))
    minmax(0, var(--cs-stock-card-right-zone-width));
  column-gap: var(--cs-stock-card-zone-gap);
  align-items: stretch;
  transition:
    background var(--cs-motion-duration-fast) var(--cs-motion-ease-standard),
    border-color var(--cs-motion-duration-fast) var(--cs-motion-ease-standard),
    box-shadow var(--cs-motion-duration-fast) var(--cs-motion-ease-standard),
    transform var(--cs-motion-duration-fast) var(--cs-motion-ease-standard);
}

.cs-stock-compact-card:hover {
  background: var(--cs-stock-card-bg-hover);
  border-color: var(--cs-stock-card-border-hover);
  box-shadow: var(--cs-stock-card-shadow-hover);
}

.cs-stock-compact-card:active,
.cs-stock-compact-card.is-active {
  background: var(--cs-stock-card-bg-active);
  border-color: var(--cs-stock-card-border-active);
  transform: translateY(1px);
}

.cs-stock-compact-card.is-selected {
  background: var(--cs-stock-card-bg-selected);
  border-color: var(--cs-stock-card-border-selected);
}
```

交互规则：

1. hover 时整卡高亮；
2. clickable 状态必须通过 `cursor: pointer`、hover 边框和弱阴影提示；
3. active 仅用于鼠标按下或键盘确认；
4. selected 为可选状态，仅当页面需要表达当前选中股票时使用；
5. 卡片点击进入个股详情；
6. 不因为卡片点击态修改连板天梯层级标题交互。

## 25.4 股票代码左上角胶囊

股票代码显示在左上角胶囊中，例如：

```text
603017.SH
```

要求：

1. 不再放右上角；
2. 不再作为普通正文列；
3. 位于左侧识别区顶部；
4. 弱化但清晰可读；
5. 不抢股票名称的视觉权重；
6. 不使用涨跌色。

推荐 CSS：

```css
.cs-stock-card-code-pill {
  align-self: flex-start;
  height: var(--cs-stock-card-code-pill-height);
  padding: 0 var(--cs-stock-card-code-pill-padding-x);
  margin-bottom: var(--cs-stock-card-code-pill-margin-bottom);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--cs-radius-pill);
  border: 1px solid var(--cs-stock-card-code-pill-border);
  background: var(--cs-stock-card-code-pill-bg);
  color: var(--cs-stock-card-code-pill-text);
  font-size: var(--cs-stock-card-code-pill-font-size);
  font-family: var(--cs-font-family-number);
  font-variant-numeric: tabular-nums;
  line-height: 1;
  white-space: nowrap;
}
```

视觉参数：

| 项 | 建议值 |
|---|---:|
| 高度 | `17px` |
| 横向内边距 | `6px` |
| 字号 | `10px` |
| 圆角 | `pill` |
| 颜色 | 弱中性色，透明度约 0.8 |

## 25.5 左 / 中 / 右三分区结构

新版卡片由三个纵向分区组成。

### 25.5.1 左侧识别区

包含：

```text
股票代码胶囊
股票名称
最新价
```

视觉规则：

1. 股票名称是最高识别权重；
2. 最新价为强行情数字；
3. 最新价可按涨跌方向红 / 绿 / 灰显示；
4. 左侧识别区左对齐。

### 25.5.2 中间行情事实区

包含：

```text
涨幅
板上成交额
```

视觉规则：

1. 涨幅红涨绿跌，强强调；
2. 板上成交额为中性或弱强调；
3. 板上成交额不使用涨跌色；
4. 中间区数字右对齐或居中偏右对齐。

### 25.5.3 右侧标签区

包含：

```text
所属板块
N天M板/板型标签
```

视觉规则：

1. 所属板块使用中性色；
2. 所属板块单行省略；
3. N天M板/板型使用胶囊标签；
4. 标签紧凑，不能撑高卡片；
5. 右侧标签区右对齐。

推荐 CSS：

```css
.cs-stock-card-zone {
  min-width: 0;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  row-gap: var(--cs-stock-card-zone-row-gap);
}

.cs-stock-card-left-zone {
  align-items: flex-start;
  text-align: left;
}

.cs-stock-card-center-zone {
  align-items: flex-end;
  text-align: right;
}

.cs-stock-card-right-zone {
  align-items: flex-end;
  text-align: right;
}
```

## 25.6 字段视觉规则

| 字段 | 分区 | 视觉层级 | 字号 / 字重 | 颜色 / 规则 | 对齐 |
|---|---|---|---:|---|---|
| 股票代码 | 左侧识别区顶部 | 弱角标 | `10px / 500` | 弱中性色 | 左对齐胶囊 |
| 股票名称 | 左侧识别区 | 最高识别权重 | `13px / 600` | `--cs-stock-card-name-text` | 左对齐，单行省略 |
| 最新价 | 左侧识别区 | 强行情数字 | `12px / 600` | 可按涨跌方向红/绿/灰 | 左对齐，数字字体 |
| 涨幅 | 中间行情事实区 | 强强调 | `12px / 700` | 红涨绿跌 | 右对齐，数字字体 |
| 板上成交额 | 中间行情事实区 | 辅助事实 | `11px / 500` | 中性或弱强调 | 右对齐，数字字体 |
| 所属板块 | 右侧标签区 | 中性识别 | `11px / 500` | `--cs-stock-card-sector-text` | 右对齐，单行省略 |
| N天M板/板型 | 右侧标签区 | 标签强调 | `11px / 600` | 品牌金弱强调或中性标签 | 右对齐胶囊 |

推荐 CSS：

```css
.cs-stock-card-name {
  color: var(--cs-stock-card-name-text);
  font-size: var(--cs-stock-card-name-font-size);
  font-weight: var(--cs-stock-card-name-font-weight);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.cs-stock-card-price,
.cs-stock-card-change,
.cs-stock-card-board-amount {
  font-family: var(--cs-font-family-number);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.cs-stock-card-price {
  font-size: var(--cs-stock-card-price-font-size);
  font-weight: var(--cs-stock-card-price-font-weight);
}

.cs-stock-card-change {
  font-size: var(--cs-stock-card-change-font-size);
  font-weight: var(--cs-stock-card-change-font-weight);
}

.cs-stock-card-sector {
  color: var(--cs-stock-card-sector-text);
  font-size: var(--cs-stock-card-meta-font-size);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.cs-stock-card-board-amount {
  color: var(--cs-stock-card-board-amount-text);
  font-size: var(--cs-stock-card-board-amount-font-size);
}
```

## 25.7 板上成交额视觉规则

字段口径：**只在板上发生的成交金额**。

明确不是：

1. 封单金额；
2. 全天成交额；
3. 总成交额；
4. 板块成交额；
5. 主力净流入。

展示格式：

```text
3.20亿
8200万
```

视觉规则：

1. 使用中性色或弱强调色；
2. 不使用涨跌红/绿；
3. 不显示为“封单”；
4. 不显示为“成交额”以免误导为全天成交额；
5. Tooltip 或 Help 文案中可解释：`板上成交额：只统计封板状态下发生的成交金额`。

## 25.8 N天M板/板型标签视觉规则

字段口径：一个字段，一个标签。

可能文案：

```text
首板
2连板
3连板
7天5板
9天7板
```

要求：

1. 不拆成两个字段；
2. 不做两个独立标签；
3. 如果视觉上需要区分，可在同一个标签内部用主次文字，但语义仍是同一字段；
4. 标签必须紧凑，适合小卡片；
5. 不使用大面积涨停红背景。

推荐 CSS：

```css
.cs-stock-card-streak-tag {
  height: var(--cs-stock-card-streak-tag-height);
  padding: 0 var(--cs-stock-card-streak-tag-padding-x);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--cs-radius-pill);
  border: 1px solid var(--cs-stock-card-streak-tag-border);
  background: var(--cs-stock-card-streak-tag-bg);
  color: var(--cs-stock-card-streak-tag-text);
  font-size: var(--cs-stock-card-streak-tag-font-size);
  font-weight: var(--cs-font-weight-semibold);
  line-height: 1;
  white-space: nowrap;
}
```

允许样式：

| 样式 | 示例 | 使用场景 |
|---|---|---|
| 普通标签 | `首板` / `2连板` / `3连板` | 连续连板表达简单时 |
| 复合短标签 | `7天5板` / `9天7板` | 近期表现更重要时 |

禁止：

```text
2连板  +  7天5板  // 两个独立标签同时展示
```

默认只展示一个标签文本。

## 25.9 红涨绿跌规则在股票卡片内的应用

| 字段 | 涨跌色规则 |
|---|---|
| 涨幅 | 必须红涨绿跌，正红、负绿、零灰白 |
| 最新价 | 可按涨跌方向红/绿/灰白显示；若信息密度过高，可使用主文字并只让涨幅承载方向色 |
| 股票名称 | 不使用涨跌色 |
| 股票代码 | 不使用涨跌色 |
| 所属板块 | 不使用涨跌色 |
| 板上成交额 | 不使用涨跌色 |
| N天M板/板型 | 使用品牌金 / 中性标签，不使用大面积红绿背景 |

推荐：

```text
方向色优先落在涨幅，最新价可同步弱方向色。
```

## 25.10 与 Review v5 / v6 连板天梯规则的兼容

本轮不改变 Review v5 已确认的连板天梯结构，也不改变 Review v6 确认的字段口径。以下规则保持不变：

1. 昨日层级 → 今日晋级层级；
2. 昨日层级展示昨日该层级所有股票，卡片信息用今日数据；
3. 今日层级展示晋级成功股票；
4. 首板层只展示今日首板；
5. 五板以上层只展示今日六板及以上；
6. 今日五板仍在 `昨日四板 → 今日五板` 层；
7. 每层默认最多 2 行，每行 6 只；
8. 超出后显示展开入口；
9. 展开后支持收起；
10. 股票卡片点击进入个股详情；
11. 层级标题暂不支持点击。

股票卡片字段变化：

| Review v6 方案 | Review v7 处理 |
|---|---|
| 股票代码右上角角标 | 改为左上角胶囊标签 |
| 主体 2 行 × 3 列 | 改为左 / 中 / 右三分区结构 |
| 第一行：股票名称 / 涨幅 / 所属板块 | 保留字段，但按三分区重排 |
| 第二行：最新价 / 板上成交额 / N天M板标签 | 保留字段，但按三分区重排 |
| 右下字段 | 仍由 `N天M板/板型` 标签承载 |

## 25.11 标准股票卡片禁止事项

1. 不再使用 Review v6 的股票代码右上角方案；
2. 不再使用 Review v6 的 `2 行 × 3 列` 机械网格方案；
3. 不照搬用户截图中的浅色背景或非系统视觉元素；
4. 不将股票代码作为普通正文列；
5. 不再使用“收盘价格”口径；
6. 不将板上成交额误写为封单金额或全天成交额；
7. 不将 `N天M板/板型` 拆成两个独立字段；
8. 不修改连板天梯层级结构；
9. 不修改连板天梯展开/收起逻辑；
10. 不修改市场总览其它模块视觉规则。

---

# 26. 本轮 Review v7 修改摘要

1. 仅修订 `市场总览 / 连板天梯 / 标准股票卡片` 的视觉规则。
2. 用户新截图正式替代上一轮股票卡片方案。
3. 股票代码从右上角角标改为左上角胶囊标签。
4. 上一轮 `2 行 × 3 列` 机械网格方案作废。
5. 新版卡片采用横向三分区结构：
   - 左侧识别区：股票代码胶囊、股票名称、最新价；
   - 中间行情事实区：涨幅、板上成交额；
   - 右侧标签区：所属板块、N天M板/板型标签。
6. 股票名称保持最高识别权重。
7. 最新价为强行情数字，可按涨跌方向红/绿/灰显示。
8. 涨幅红涨绿跌，强强调。
9. 板上成交额保持中性或弱强调，不使用涨跌色。
10. N天M板/板型仍为一个字段、一个标签。
11. 保持红涨绿跌规则不变。
12. 不修改 Review v7 未点名区域。

# 27. 本轮未修改区域说明

本轮没有修改以下区域：

1. TopMarketBar；
2. Breadcrumb；
3. PageHeader；
4. ShortcutBar；
5. 今日市场客观总结；
6. 主要指数；
7. 涨跌分布；
8. 市场风格；
9. 成交额总览；
10. 大盘资金流向；
11. 榜单速览；
12. 涨跌停统计与分布；
13. 板块速览；
14. 连板天梯层级结构；
15. 连板天梯展开 / 收起逻辑；
16. 页面整体主题；
17. 全局字体；
18. 与 Review v7 无关的任何视觉规则。

```text
本轮因 Review v7 修改而被动影响的区域：无
原因：无
是否需要产品总控确认：否
```

# 28. 本轮新增或修订 Token 清单

| Token | 类型 | 用途 |
|---|---|---|
| `--cs-stock-card-width` | 修订 | 新版三分区标准股票卡片宽度 |
| `--cs-stock-card-min-width` | 修订 | 小宽度下股票卡片最小宽度 |
| `--cs-stock-card-height` | 修订 | 新版三分区标准股票卡片高度 |
| `--cs-stock-card-padding-x` | 修订 | 股票卡片横向内边距 |
| `--cs-stock-card-padding-y` | 修订 | 股票卡片纵向内边距 |
| `--cs-stock-card-zone-gap` | 新增 | 左 / 中 / 右三分区间距 |
| `--cs-stock-card-left-zone-width` | 新增 | 左侧识别区宽度比例 |
| `--cs-stock-card-center-zone-width` | 新增 | 中间行情事实区宽度比例 |
| `--cs-stock-card-right-zone-width` | 新增 | 右侧标签区宽度比例 |
| `--cs-stock-card-zone-row-gap` | 新增 | 分区内部纵向间距 |
| `--cs-stock-card-code-pill-height` | 新增 | 股票代码胶囊高度 |
| `--cs-stock-card-code-pill-padding-x` | 新增 | 股票代码胶囊横向内边距 |
| `--cs-stock-card-code-pill-font-size` | 新增 | 股票代码胶囊字号 |
| `--cs-stock-card-code-pill-margin-bottom` | 新增 | 股票代码胶囊与股票名称间距 |
| `--cs-stock-card-code-pill-text` | 新增 | 股票代码胶囊文字色 |
| `--cs-stock-card-code-pill-bg` | 新增 | 股票代码胶囊背景 |
| `--cs-stock-card-code-pill-border` | 新增 | 股票代码胶囊边框 |
| `--cs-stock-card-name-font-size` | 保留/修订 | 股票名称字号 |
| `--cs-stock-card-name-font-weight` | 保留/修订 | 股票名称字重 |
| `--cs-stock-card-price-font-size` | 保留/修订 | 最新价字号 |
| `--cs-stock-card-price-font-weight` | 保留/修订 | 最新价字重 |
| `--cs-stock-card-change-font-size` | 保留/修订 | 涨幅字号 |
| `--cs-stock-card-change-font-weight` | 保留/修订 | 涨幅字重 |
| `--cs-stock-card-meta-font-size` | 保留/修订 | 所属板块等次级信息字号 |
| `--cs-stock-card-board-amount-font-size` | 新增 | 板上成交额字号 |
| `--cs-stock-card-board-amount-text` | 保留/修订 | 板上成交额文字色 |
| `--cs-stock-card-streak-tag-font-size` | 新增 | N天M板/板型标签字号 |
| `--cs-stock-card-streak-tag-height` | 新增 | N天M板/板型标签高度 |
| `--cs-stock-card-streak-tag-padding-x` | 新增 | N天M板/板型标签横向内边距 |
| `--cs-stock-card-streak-tag-text` | 新增 | N天M板/板型标签文字色 |
| `--cs-stock-card-streak-tag-bg` | 新增 | N天M板/板型标签背景 |
| `--cs-stock-card-streak-tag-border` | 新增 | N天M板/板型标签边框 |

# 29. 对 03 `04-component-guidelines.md` 的 Token 映射建议

| 组件 / Pattern | 建议使用 Token |
|---|---|
| `CsqStockCompactCard` | `--cs-stock-card-*`、`--cs-color-market-*`、`--cs-font-family-number` |
| `PatternLimitLadder` | 继续使用 `--cs-limit-ladder-*`、`--cs-stock-card-*` |
| `LimitLadderStockGrid` | 继续使用 `--cs-limit-ladder-stock-grid-gap-x`、`--cs-limit-ladder-stock-grid-gap-y`、`--cs-stock-card-width` |

建议 03 修订 `CsqStockCompactCard`：

```ts
interface CsqStockCompactCardProps {
  stockCode: string;
  stockName: string;
  latestPrice: number;
  changePct: number;
  sectorName: string;
  boardTradeAmount: number;
  streakText: string;
  direction?: 'rise' | 'fall' | 'flat';
  selected?: boolean;
  onClick?: () => void;
}
```

展示结构：

```text
codePill: stockCode
leftIdentity: stockName / latestPrice
centerMetrics: changePct / boardTradeAmount
rightTags: sectorName / streakText
```

组件说明：

1. `stockCode` 显示在左上角胶囊中；
2. `stockCode` 不再显示在右上角；
3. `latestPrice` 是最新价，不是收盘价格；
4. `boardTradeAmount` 是板上成交额，只在板上发生的成交金额；
5. `streakText` 是 `N天M板/板型`，一个字段、一个标签；
6. 连板天梯中的标准股票卡片统一使用左 / 中 / 右三分区布局。

# 30. 对 02 `market-overview-v1.6.html` 的视觉约束

1. 只修改连板天梯中的标准股票卡片。
2. 用户新截图正式替代上一轮股票卡片方案。
3. 股票代码必须改为左上角胶囊标签。
4. 不得继续使用右上角代码方案。
5. 不得继续使用 `2 行 × 3 列` 机械网格方案。
6. 卡片必须使用左 / 中 / 右三分区结构：
   - 左侧识别区：股票代码、股票名称、最新价；
   - 中间行情事实区：涨幅、板上成交额；
   - 右侧标签区：所属板块、N天M板/板型标签。
7. 股票名称是最高识别权重。
8. 最新价是强行情数字，可按方向红/绿/灰显示。
9. 涨幅必须红涨绿跌，并强强调。
10. 板上成交额按“只在板上发生的成交金额”理解和展示，不得误写为封单金额或全天成交额。
11. `N天M板/板型` 必须是一个字段、一个标签。
12. 不照搬用户截图中的浅色背景或非系统视觉元素。
13. 必须使用当前市场总览深色金融终端风格。
14. 保持卡片 hover / clickable 状态。
15. 不修改连板天梯层级结构。
16. 不修改连板天梯展开/收起逻辑。
17. 不修改市场总览其它模块。

# 31. 待产品总控确认问题

1. 新版三分区标准股票卡片宽度是否接受 `176px`，以保证三分区信息可读？
2. 在 1366px 下是否允许卡片宽度降级到 `160px`，并通过减少每行卡片数保持可读性？
3. 股票代码胶囊是否只展示代码，不展示交易所中文或市场标签？当前建议只展示 `603017.SH` 这种格式。
4. 最新价是否必须随涨跌方向着色？当前建议可按方向弱着色，也可只让涨幅承载方向色以降低噪音。
5. N天M板标签是否统一使用品牌金描边胶囊？当前建议如此，以避免大面积红色背景增加噪音。
6. 板上成交额是否只在 Tooltip 中补充完整口径？当前建议卡片内只显示金额。

# 32. 本轮输出文件下载链接

本轮输出文件名：

```text
03-design-tokens.md
```

下载链接由本轮对话附件提供。

建议放置到 Google Drive：

```text
财势乾坤/设计/03-design-tokens.md
```



---


# 33. 市场总览新闻速览与个股新闻板块视觉规则（Review v9）

> 本节为 Review v9 修订规则。仅约束 `市场总览 / 新闻速览板块 / 个股新闻板块`，不修改 TopMarketBar、Breadcrumb、PageHeader、ShortcutBar、正文模块、页面整体主题或全局字体。

## 33.1 适用范围

本节适用于市场总览首屏上方的两个独立新闻板块：

```text
新闻速览
个股新闻
```

新版布局关系：

```text
┌──────────────────────────────┬──────────────────────────────┐
│ 新闻速览                      │ 个股新闻                      │
├──────────────────────────────┼──────────────────────────────┤
│ 今日市场客观总结              │ 主要指数                      │
└──────────────────────────────┴──────────────────────────────┘
```

要求：

1. 新闻速览位于“今日市场客观总结”正上方。
2. 个股新闻位于“主要指数”正上方。
3. 新闻速览与今日市场客观总结等宽。
4. 个股新闻与主要指数等宽。
5. 两个新闻板块高度一致。
6. 本轮不修改今日市场客观总结和主要指数的内部视觉规则。

## 33.2 作废上一轮顶部中间统一快讯条方案

Review v8 中的顶部中间统一快讯条方案正式作废。

作废结构：

```text
ICON 预留位 ｜ 新闻速览 ｜ 个股新闻
```

因此：

1. 顶部中间不再放统一快讯条。
2. 不再使用 ICON 预留位。
3. 不再使用竖排标题。
4. 不再使用“ICON｜新闻速览｜个股新闻”的横向结构。
5. PageHeader 中间区域恢复为不承载统一快讯条的状态。

设计与实现注意：

- `--cs-news-ticker-*` 一类 v8 顶部统一快讯条 Token 不再用于市场总览 v1.8。
- 如后续其它页面需要通用横向快讯条，可另行评估，但不得影响本轮市场总览新闻板块规则。

## 33.3 新闻板块结构

每个新闻板块内部结构统一：

```text
┌──────────────────────────────┐
│ 新闻速览 / 个股新闻           │
├──────────────────────────────┤
│ 04-28 15:05:00  新闻标题...   │
│ 04-28 15:04:32  新闻标题...   │
│ ...                           │
└──────────────────────────────┘
```

组成：

1. 左上角板块名称；
2. 下方新闻滚动区域；
3. 新闻 item 列表；
4. hover 后的可滚动浏览区域。

板块名称固定为：

```text
新闻速览
个股新闻
```

## 33.4 新闻板块 Token

```css
:root {
  /* News panels: Review v9 */
  --cs-news-panel-height: 236px;
  --cs-news-panel-min-height: 220px;
  --cs-news-panel-padding-x: 12px;
  --cs-news-panel-padding-y: 10px;
  --cs-news-panel-gap-y: 8px;
  --cs-news-panel-bg: var(--cs-color-surface-panel);
  --cs-news-panel-bg-hover: var(--cs-color-surface-card-hover);
  --cs-news-panel-border: var(--cs-color-border-subtle);
  --cs-news-panel-border-hover: var(--cs-color-border-hover);
  --cs-news-panel-radius: var(--cs-radius-panel);

  /* News panel title */
  --cs-news-panel-title-height: 24px;
  --cs-news-panel-title-font-size: var(--cs-font-size-13);
  --cs-news-panel-title-font-weight: var(--cs-font-weight-semibold);
  --cs-news-panel-title-color: var(--cs-color-text-primary);
  --cs-news-panel-title-dot-size: 6px;
  --cs-news-panel-title-dot-color: var(--cs-color-brand-accent);

  /* News list */
  --cs-news-panel-list-height: calc(var(--cs-news-panel-height) - var(--cs-news-panel-title-height) - var(--cs-news-panel-gap-y) - var(--cs-news-panel-padding-y) * 2);
  --cs-news-panel-visible-count: 10;
  --cs-news-item-height: 19px;
  --cs-news-item-gap: 2px;
  --cs-news-item-padding-x: 6px;
  --cs-news-item-radius: var(--cs-radius-sm);
  --cs-news-item-hover-bg: rgba(247, 199, 107, 0.07);

  /* News text */
  --cs-news-time-width: 92px;
  --cs-news-time-font-size: var(--cs-font-size-11);
  --cs-news-time-color: var(--cs-color-text-muted);
  --cs-news-title-font-size: var(--cs-font-size-12);
  --cs-news-title-color: var(--cs-color-text-secondary);
  --cs-news-title-hover-color: var(--cs-color-text-primary);

  /* News marquee / scroll */
  --cs-news-marquee-duration: 28s;
  --cs-news-marquee-timing: linear;
  --cs-news-hover-transition-duration: var(--cs-motion-duration-fast);
  --cs-news-scrollbar-width: 4px;
  --cs-news-scrollbar-thumb: rgba(148, 163, 184, 0.28);
  --cs-news-scrollbar-thumb-hover: rgba(247, 199, 107, 0.34);

  /* News layout relation */
  --cs-news-panel-to-main-gap: 12px;
}
```

说明：

1. `--cs-news-panel-visible-count` 是默认展示条数，默认 10 条。
2. 02 Showcase 可以通过组件配置覆盖 `visibleItemCount`，但默认值必须为 10。
3. 新闻板块高度需与下方“今日市场客观总结 / 主要指数”所在首屏区域协调，避免挤压首屏其它核心模块。

## 33.5 新闻板块整体容器

```css
.cs-news-panel {
  height: var(--cs-news-panel-height);
  min-height: var(--cs-news-panel-min-height);
  padding: var(--cs-news-panel-padding-y) var(--cs-news-panel-padding-x);
  background: var(--cs-news-panel-bg);
  border: 1px solid var(--cs-news-panel-border);
  border-radius: var(--cs-news-panel-radius);
  overflow: hidden;
}

.cs-news-panel:hover {
  background: var(--cs-news-panel-bg-hover);
  border-color: var(--cs-news-panel-border-hover);
}
```

视觉规则：

1. 容器使用现有市场总览深色面板风格。
2. 不做资讯网站卡片风，不使用大图、摘要、多行正文。
3. 容器不使用大面积红绿背景。
4. 两个新闻板块必须等高。
5. 新闻速览与今日市场客观总结等宽。
6. 个股新闻与主要指数等宽。
7. 新闻板块与下方模块之间使用 `--cs-news-panel-to-main-gap` 控制间距。

## 33.6 新闻板块标题

```css
.cs-news-panel-title {
  height: var(--cs-news-panel-title-height);
  display: flex;
  align-items: center;
  gap: var(--cs-space-6);
  color: var(--cs-news-panel-title-color);
  font-size: var(--cs-news-panel-title-font-size);
  font-weight: var(--cs-news-panel-title-font-weight);
}

.cs-news-panel-title::before {
  content: "";
  width: var(--cs-news-panel-title-dot-size);
  height: var(--cs-news-panel-title-dot-size);
  border-radius: 999px;
  background: var(--cs-news-panel-title-dot-color);
}
```

标题规则：

1. 使用现有市场总览模块标题风格。
2. 标题横向显示，不使用竖排标题。
3. 标题为“新闻速览”或“个股新闻”。
4. 标题不应抢占过多高度，优先保证新闻区可读性。
5. 不使用红绿表达标题状态。

## 33.7 新闻滚动区域

```css
.cs-news-list-viewport {
  height: var(--cs-news-panel-list-height);
  overflow: hidden;
  position: relative;
}

.cs-news-panel:hover .cs-news-list-viewport {
  overflow-y: auto;
}
```

滚动区规则：

1. 默认状态下 `overflow: hidden`，由跑马灯控制内容向上滚动。
2. hover 当前新闻板块后，当前板块停止跑马灯，并允许用户手动滚动。
3. hover 只作用于当前新闻板块，另一新闻板块继续自动滚动。
4. 鼠标离开后，当前板块恢复跑马灯。
5. 恢复时尽量回到同步滚动节奏；如果实现复杂度较高，02 需在 Showcase 说明中标注。

滚动条样式：

```css
.cs-news-list-viewport::-webkit-scrollbar {
  width: var(--cs-news-scrollbar-width);
}

.cs-news-list-viewport::-webkit-scrollbar-thumb {
  background: var(--cs-news-scrollbar-thumb);
  border-radius: var(--cs-radius-pill);
}

.cs-news-list-viewport:hover::-webkit-scrollbar-thumb {
  background: var(--cs-news-scrollbar-thumb-hover);
}
```

## 33.8 新闻 item

每条新闻 item 格式：

```text
MM-DD HH:mm:ss  新闻信息
```

示例：

```text
04-28 15:05:00  央行公开市场开展逆回购操作...
```

CSS 建议：

```css
.cs-news-item {
  height: var(--cs-news-item-height);
  display: grid;
  grid-template-columns: var(--cs-news-time-width) minmax(0, 1fr);
  align-items: center;
  column-gap: var(--cs-space-6);
  padding: 0 var(--cs-news-item-padding-x);
  border-radius: var(--cs-news-item-radius);
  cursor: default;
}

.cs-news-item:hover {
  background: var(--cs-news-item-hover-bg);
}

.cs-news-time {
  color: var(--cs-news-time-color);
  font-size: var(--cs-news-time-font-size);
  font-family: var(--cs-font-family-number);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.cs-news-title {
  min-width: 0;
  color: var(--cs-news-title-color);
  font-size: var(--cs-news-title-font-size);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cs-news-item:hover .cs-news-title {
  color: var(--cs-news-title-hover-color);
}
```

规则：

1. 时间为中性浅色。
2. 新闻标题为主文字或次主文字。
3. 新闻标题单行展示。
4. 超出当前列宽后使用 `...` 省略。
5. 不换行。
6. 不撑开容器。
7. P0 阶段新闻 item 不可点击。
8. 不使用强点击态。
9. 不使用 `cursor: pointer`。
10. hover 只做弱背景提示，用于提示当前列处于暂停 / 可滚动状态，不表示可跳转。

## 33.9 默认展示条数与配置

默认展示条数：

```text
visibleItemCount: 10
```

组件配置建议：

```ts
interface CsqNewsPanelProps {
  title: string;
  items: NewsPanelItem[];
  visibleItemCount?: number; // default: 10
  autoScroll?: boolean;      // default: true
  syncGroupId?: string;
  hoverPause?: boolean;      // default: true
  itemClickable?: false;     // P0 fixed false
}
```

规则：

1. 默认展示 10 条新闻。
2. 展示条数必须可配置，不应在样式或组件中写死。
3. 若新闻少于 10 条，展示实际数量，不强行补空行。
4. 若新闻超过 10 条，默认可视范围按 `visibleItemCount` 控制，后续内容通过跑马灯和 hover 手动滚动查看。
5. 可视高度应由 `visibleItemCount × itemHeight + titleHeight + padding` 推导或由外层布局显式控制。

## 33.10 跑马灯与 hover 暂停

默认状态：

1. 新闻速览和个股新闻两列同步向上滚动。
2. 最新新闻在上，旧新闻在下。
3. 两个新闻模块使用相同滚动节奏。
4. 循环播放。
5. 可视条数由 `visibleItemCount` 控制，默认 10 条。

hover 新闻速览：

1. 新闻速览停止跑马灯。
2. 新闻速览变为可手动滚动区域。
3. 个股新闻继续自动滚动。

hover 个股新闻：

1. 个股新闻停止跑马灯。
2. 个股新闻变为可手动滚动区域。
3. 新闻速览继续自动滚动。

hover 离开：

1. 当前板块恢复自动向上滚动。
2. 尽量回到同步滚动节奏。
3. 不建议强制跳回第一条，避免视觉突跳。

动画建议：

```css
.cs-news-marquee-track {
  animation-name: cs-news-marquee-up;
  animation-duration: var(--cs-news-marquee-duration);
  animation-timing-function: var(--cs-news-marquee-timing);
  animation-iteration-count: infinite;
}

.cs-news-panel:hover .cs-news-marquee-track {
  animation-play-state: paused;
}
```

## 33.11 数据与 Mock 结构建议

本轮需要 04 轻量参与，但 01 只定义视觉 Token。P0 Showcase 可使用 Mock 数据。

```ts
interface MarketOverviewNewsPanels {
  visibleCount: number;
  marketNews: NewsPanelItem[];
  stockNews: NewsPanelItem[];
}

interface NewsPanelItem {
  id: string;
  publishTime: string;
  displayTime?: string; // MM-DD HH:mm:ss
  title: string;
  category: 'market' | 'stock';
  source?: string;
  stockCode?: string;
  stockName?: string;
  clickable: false;
}
```

视觉约束：

1. `clickable` 在 P0 固定为 `false`。
2. `displayTime` 建议前端格式化为 `MM-DD HH:mm:ss`。
3. 新闻标题省略由前端负责。
4. Mock 数据每类不少于 10 条，以验证滚动与 hover 手动滚动状态。

# 34. 本轮 Review v9 修改摘要

1. 作废 Review v8 的顶部中间统一快讯条方案。
2. 不再使用 `ICON 预留位 ｜ 新闻速览 ｜ 个股新闻` 横向结构。
3. 不再使用 ICON 预留位。
4. 不再使用竖排标题。
5. 新闻速览改为独立新闻板块，位于“今日市场客观总结”正上方。
6. 个股新闻改为独立新闻板块，位于“主要指数”正上方。
7. 新闻速览与今日市场客观总结等宽。
8. 个股新闻与主要指数等宽。
9. 两个新闻板块高度一致。
10. 每个新闻板块默认展示 10 条新闻，且展示条数可配置。
11. 每条新闻格式为 `MM-DD HH:mm:ss + 新闻信息`。
12. 新闻标题单行展示，超出显示 `...`。
13. 两个新闻板块默认同步向上滚动。
14. hover 当前新闻板块只暂停当前板块，另一板块继续滚动。
15. hover 后当前新闻板块可手动滚动。
16. 新闻 item P0 不可点击。
17. 本轮不修改市场总览其它模块。

# 35. 本轮未修改区域说明

本轮未修改以下区域的视觉规则：

1. TopMarketBar；
2. Breadcrumb；
3. PageHeader；
4. ShortcutBar；
5. 今日市场客观总结内部内容；
6. 主要指数内部内容；
7. 涨跌分布；
8. 市场风格；
9. 成交额总览；
10. 大盘资金流向；
11. 榜单速览；
12. 涨跌停统计与分布；
13. 连板天梯；
14. 板块速览；
15. 页面整体主题；
16. 全局字体；
17. 与 Review v9 无关的任何视觉规则。

本轮可能产生的被动影响：

```text
本轮因 Review v9 修改而被动影响的区域：
- 今日市场客观总结与主要指数所在首屏区域的局部垂直排布
原因：新闻速览需要位于今日市场客观总结正上方，个股新闻需要位于主要指数正上方
是否需要产品总控确认：否，Review v9 已明确；但 02 Showcase 需要验证高度与密度是否合理
```

# 36. 本轮新增或修订 Token 清单

| Token | 类型 | 用途 |
|---|---|---|
| `--cs-news-panel-height` | 新增 | 独立新闻板块高度 |
| `--cs-news-panel-min-height` | 新增 | 独立新闻板块最小高度 |
| `--cs-news-panel-padding-x` | 新增 | 新闻板块横向内边距 |
| `--cs-news-panel-padding-y` | 新增 | 新闻板块纵向内边距 |
| `--cs-news-panel-gap-y` | 新增 | 标题与新闻列表间距 |
| `--cs-news-panel-bg` | 新增 | 新闻板块背景 |
| `--cs-news-panel-bg-hover` | 新增 | 新闻板块 hover 背景 |
| `--cs-news-panel-border` | 新增 | 新闻板块边框 |
| `--cs-news-panel-border-hover` | 新增 | 新闻板块 hover 边框 |
| `--cs-news-panel-radius` | 新增 | 新闻板块圆角 |
| `--cs-news-panel-title-height` | 新增 | 新闻板块标题高度 |
| `--cs-news-panel-title-font-size` | 新增 | 新闻板块标题字号 |
| `--cs-news-panel-title-font-weight` | 新增 | 新闻板块标题字重 |
| `--cs-news-panel-title-color` | 新增 | 新闻板块标题颜色 |
| `--cs-news-panel-title-dot-size` | 新增 | 标题前导点大小 |
| `--cs-news-panel-title-dot-color` | 新增 | 标题前导点颜色 |
| `--cs-news-panel-list-height` | 新增 | 新闻滚动列表高度 |
| `--cs-news-panel-visible-count` | 新增 | 默认展示条数，默认 10 |
| `--cs-news-item-height` | 新增 | 新闻 item 行高 |
| `--cs-news-item-gap` | 新增 | 新闻 item 间距 |
| `--cs-news-item-padding-x` | 新增 | 新闻 item 横向内边距 |
| `--cs-news-item-radius` | 新增 | 新闻 item 圆角 |
| `--cs-news-item-hover-bg` | 新增 | 新闻 item hover 背景 |
| `--cs-news-time-width` | 新增 | 时间列宽度 |
| `--cs-news-time-font-size` | 新增 | 时间字号 |
| `--cs-news-time-color` | 新增 | 时间颜色 |
| `--cs-news-title-font-size` | 新增 | 新闻标题字号 |
| `--cs-news-title-color` | 新增 | 新闻标题颜色 |
| `--cs-news-title-hover-color` | 新增 | 新闻标题 hover 颜色 |
| `--cs-news-marquee-duration` | 新增 | 新闻跑马灯周期 |
| `--cs-news-marquee-timing` | 新增 | 新闻跑马灯速度曲线 |
| `--cs-news-hover-transition-duration` | 新增 | hover 状态过渡时间 |
| `--cs-news-scrollbar-width` | 新增 | 手动滚动条宽度 |
| `--cs-news-scrollbar-thumb` | 新增 | 手动滚动条颜色 |
| `--cs-news-scrollbar-thumb-hover` | 新增 | 手动滚动条 hover 颜色 |
| `--cs-news-panel-to-main-gap` | 新增 | 新闻板块与下方模块间距 |
| `--cs-news-ticker-*` | 修订 | Review v8 顶部统一快讯条 Token 不再用于市场总览 v1.8 |

# 37. 对 03 `04-component-guidelines.md` 的 Token 映射建议

建议 03 新增或修订以下组件：

| 组件 | 类型 | Token 映射 |
|---|---|---|
| `MarketOverviewNewsPanelGroup` | 市场总览新闻板块组合 | `--cs-news-panel-*`、布局等宽规则 |
| `CsqNewsPanel` | 通用新闻面板 | `--cs-news-panel-*`、`--cs-news-item-*`、`--cs-news-time-*`、`--cs-news-title-*` |
| `CsqNewsItem` | 新闻条 | `--cs-news-time-*`、`--cs-news-title-*`、`--cs-news-item-hover-bg` |
| `CsqSyncedTickerController` | 同步滚动控制逻辑 | `--cs-news-marquee-*`、hover pause 规则 |

建议 Props：

```ts
interface NewsPanelItem {
  id: string;
  publishTime: string;
  displayTime?: string;
  title: string;
  category: 'market' | 'stock';
  source?: string;
  stockCode?: string;
  stockName?: string;
  clickable: false;
}

interface CsqNewsPanelProps {
  title: string;
  items: NewsPanelItem[];
  visibleItemCount?: number; // default 10
  autoScroll?: boolean;
  syncGroupId?: string;
  hoverPause?: boolean;
  clickable?: false;
}
```

组件约束：

1. `CsqNewsPanel` 是独立新闻面板，不是顶部统一快讯条。
2. `CsqNewsItem` 在 P0 中不可点击。
3. `CsqNewsPanel` 支持 hover 暂停当前面板。
4. `CsqNewsPanel` hover 后支持手动滚动。
5. 两个新闻面板通过 `syncGroupId` 或页面控制器实现同步滚动节奏。
6. `MarketOverviewNewsPanelGroup` 只用于市场总览首屏组合，不应成为通用 Core Component。

# 38. Pattern Example 对应 Token 映射说明

在组件库 Demo 中，新闻面板相关能力可作为 Pattern 示例展示：

| Pattern | 组成组件 | Token 映射 | 说明 |
|---|---|---|---|
| `PatternMarketNewsPanels` | `CsqNewsPanel` × 2 + `CsqSyncedTickerController` | `--cs-news-panel-*`、`--cs-news-marquee-*` | 展示市场级新闻与个股新闻并列、同步滚动与 hover 暂停 |

注意：

1. 该 Pattern 可使用真实感 mock 新闻，但不绑定具体新闻 API。
2. 市场总览页面中的新闻速览 / 个股新闻属于页面组合，不是全局必须存在的基础组件。
3. 不复用 v8 的 ICON 预留位和竖排标题结构。

# 39. 对 02 `market-overview-v1.8.html` 的视觉约束

1. 删除上一版头部中间统一快讯条。
2. 不再展示 ICON 预留位。
3. 不再使用竖排标题。
4. 在“今日市场客观总结”正上方增加“新闻速览”独立板块。
5. 在“主要指数”正上方增加“个股新闻”独立板块。
6. 新闻速览与今日市场客观总结等宽。
7. 个股新闻与主要指数等宽。
8. 两个新闻板块高度一致。
9. 每个新闻板块左上角标题分别为“新闻速览”“个股新闻”。
10. 每条新闻展示时间与标题。
11. 时间格式必须为 `MM-DD HH:mm:ss`，例如 `04-28 15:05:00`。
12. 新闻标题必须单行展示，超出宽度以 `...` 省略。
13. 每个新闻板块默认展示 10 条新闻。
14. 展示条数必须通过配置控制，例如 `visibleItemCount: 10`。
15. 两个新闻板块默认同步向上滚动。
16. hover 到新闻速览时，只暂停新闻速览；个股新闻继续滚动。
17. hover 到个股新闻时，只暂停个股新闻；新闻速览继续滚动。
18. hover 后当前新闻板块可手动滚动浏览。
19. 新闻 item 一期不可点击。
20. 新闻 item 不使用 pointer。
21. 不修改 TopMarketBar、Breadcrumb、PageHeader、ShortcutBar、正文模块、连板天梯或其它 Review v9 未点名区域。
22. 不输出买卖建议，不展示主观市场结论。
23. 视觉必须保持专业、沉稳、高密度、金融终端感。

# 40. 待产品总控确认问题

1. `visibleItemCount: 10` 是否会导致新闻面板高度过高，需要 02 在 `market-overview-v1.8.html` 中验证首屏密度。
2. 若新闻条数少于 10 条，是否接受展示实际数量并不补空行。当前建议接受。
3. hover 离开后是否必须精确恢复同步节奏。当前建议“尽量恢复”，不做强像素级同步要求。
4. 后续是否需要支持新闻 item 点击。当前 P0 明确不支持。
5. 后续是否需要接入真实新闻 API。Review v9 建议 04 轻量参与，但本 Token 文档仅定义视觉规则。
6. 两个新闻面板是否始终等高。当前建议等高。
7. `--cs-news-ticker-*` 是否保留为未来其它页面通用 ticker 的候选 Token。当前市场总览 v1.8 不再使用。

# 41. 本轮输出文件下载链接

本轮输出文件名：

```text
03-design-tokens.md
```

下载链接由本轮对话附件提供。

建议放置到 Google Drive：

```text
财势乾坤/设计/03-design-tokens.md
```


---

# 42. 个股详情页固定视口交易终端 Token v0.3.7

本节基于《个股详情页产品需求文档 v0.2》补充。它服务于 `乾坤行情 / 个股详情` 页面，不改变市场总览、组件库 Demo 或其它页面已确认规则。

## 42.1 页面定位与本节边界

个股详情页属于 **乾坤行情**，是 A 股个股事实行情终端页。页面用于查看个股 K 线、周期、技术指标、成交量、资金结构、关联板块和基础行情信息。

本节只定义视觉 Token 与布局规则，不定义买卖建议、不定义诊股结论、不定义真实交易下单能力。

必须保持：

1. 中国市场红涨绿跌。
2. 深色主题优先。
3. 专业、沉稳、高密度、金融终端感。
4. 个股详情页采用固定视口交易终端布局。
5. 不通过 body 级整页滚动解决布局溢出问题。

---

# 43. 固定视口布局 Token

## 43.1 核心高度 Token

个股详情页新增 `--sd-*` Token，`sd` 表示 `Stock Detail`。该前缀用于页面级布局，不替代全局 `--cs-*` Token。

```css
:root {
  /* Stock Detail fixed viewport layout */
  --sd-top-market-bar-h: 44px;
  --sd-breadcrumb-action-bar-h: 34px;
  --sd-chart-toolbar-h: 36px;
  --sd-main-content-h: calc(
    100vh
    - var(--sd-top-market-bar-h)
    - var(--sd-breadcrumb-action-bar-h)
    - var(--sd-chart-toolbar-h)
  );

  /* Right side panel */
  --sd-right-panel-w: 384px;
  --sd-right-panel-w-min: 360px;
  --sd-right-panel-w-max: 400px;

  /* Minimum usable viewport */
  --sd-min-viewport-w: 1440px;
  --sd-min-viewport-h: 900px;

  /* Fixed viewport shell */
  --sd-shell-overflow: hidden;
  --sd-main-grid-gap: 8px;
  --sd-main-border-w: 1px;
}
```

## 43.2 100vh 规则

`100vh` 表示浏览器当前可视区域高度，不是固定 `1080px`，也不是显示器物理高度。

个股详情页根容器必须使用：

```css
.stock-detail-page {
  height: 100vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  background: var(--cs-color-bg-page);
  color: var(--cs-color-text-primary);
}
```

如工程统一支持 `100dvh`，桌面端可使用增强写法：

```css
.stock-detail-page {
  height: 100vh;
  height: 100dvh;
}
```

## 43.3 主内容区高度计算

主内容区高度必须由固定顶部区域扣减得出：

```css
.stock-detail-main {
  height: var(--sd-main-content-h);
  min-height: 0;
  overflow: hidden;
  display: grid;
  grid-template-columns: minmax(0, 1fr) var(--sd-right-panel-w);
  gap: var(--sd-main-grid-gap);
}
```

等价写法：

```css
.stock-detail-main {
  height: calc(
    100vh
    - var(--sd-top-market-bar-h)
    - var(--sd-breadcrumb-action-bar-h)
    - var(--sd-chart-toolbar-h)
  );
}
```

## 43.4 禁止写死高度

禁止：

```css
.stock-detail-page {
  height: 1080px;
}

.stock-detail-main {
  height: 958px;
}
```

正确原则：

```text
设计基准可以按 1920×1080 评估；
实现高度必须按浏览器 100vh 动态计算；
任何 1080px / 958px 数值只能作为设计说明，不得写入最终布局 CSS。
```

## 43.5 禁止 body 级整页滚动

禁止将以下规则作为个股详情页主方案：

```css
body {
  overflow-y: auto;
}
```

必须保证：

```css
html,
body,
#app {
  height: 100%;
}

body {
  overflow: hidden;
}

.stock-detail-page {
  overflow: hidden;
}
```

局部内容溢出时，只允许模块内部滚动、模块内部压缩或局部折叠。

---

# 44. 个股详情页顶部区域 Token

## 44.1 TopMarketBar

个股详情页复用全局 TopMarketBar，但高度在该页面用 `--sd-top-market-bar-h` 控制。

```css
.sd-top-market-bar {
  height: var(--sd-top-market-bar-h);
  background: var(--cs-color-bg-top-market-bar);
  border-bottom: 1px solid var(--cs-color-border-subtle);
  z-index: var(--cs-z-top-market-bar);
}
```

视觉规则：

1. 高度紧凑，建议 44px。
2. 不因个股详情页新增大标题或营销信息而增高。
3. 不改变已确认的全局 TopMarketBar 风格。

## 44.2 BreadcrumbActionBar

BreadcrumbActionBar 替代独立 Compact PageHeader，承载面包屑、复权切换、更新时间、刷新和数据状态。

```css
:root {
  --sd-breadcrumb-action-bg: var(--cs-color-surface-panel-subtle);
  --sd-breadcrumb-action-border: var(--cs-color-border-subtle);
  --sd-breadcrumb-action-padding-x: 12px;
  --sd-breadcrumb-action-gap: 12px;
  --sd-breadcrumb-action-font-size: var(--cs-font-size-12);
  --sd-breadcrumb-action-text: var(--cs-color-text-secondary);
  --sd-breadcrumb-action-current-text: var(--cs-color-text-primary);
}

.sd-breadcrumb-action-bar {
  height: var(--sd-breadcrumb-action-bar-h);
  background: var(--sd-breadcrumb-action-bg);
  border-bottom: 1px solid var(--sd-breadcrumb-action-border);
  padding: 0 var(--sd-breadcrumb-action-padding-x);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sd-breadcrumb-action-gap);
  font-size: var(--sd-breadcrumb-action-font-size);
}
```

左侧固定结构：

```text
财势乾坤 / 乾坤行情 / 个股详情 / 福斯特 603806
```

右侧固定结构：

```text
前复权▼ ｜ 更新时间 14:59:56 ｜ 刷新 ｜ 数据正常
```

## 44.3 ChartToolbar

ChartToolbar 展示周期入口与功能入口。

```css
:root {
  --sd-chart-toolbar-bg: #0B1220;
  --sd-chart-toolbar-border: var(--cs-color-border-subtle);
  --sd-chart-toolbar-padding-x: 10px;
  --sd-chart-toolbar-gap: 6px;
  --sd-chart-toolbar-item-h: 24px;
  --sd-chart-toolbar-item-padding-x: 9px;
  --sd-chart-toolbar-item-radius: var(--cs-radius-button);
  --sd-chart-toolbar-item-font-size: var(--cs-font-size-12);
  --sd-chart-toolbar-item-text: var(--cs-color-text-secondary);
  --sd-chart-toolbar-item-hover-bg: var(--cs-color-surface-card-hover);
  --sd-chart-toolbar-item-active-bg: var(--cs-color-brand-accent-bg);
  --sd-chart-toolbar-item-active-text: var(--cs-color-brand-accent);
  --sd-chart-toolbar-item-disabled-text: var(--cs-color-text-weak);
}
```

P0 展示入口：

```text
分时｜日K｜周K｜月K｜120分｜90分｜60分｜30分｜15分｜5分｜1分｜股票资料｜诊股
```

规则：

1. 默认周期为日K。
2. 周期按钮选中态使用品牌金，不使用红绿。
3. 股票资料进入独立资料页。
4. 诊股 disabled，文字弱化，不可点击。
5. 不展示“多周期、同花顺F10、显示、画线”。

---

# 45. 左侧图表区 Token

## 45.1 图表区整体布局

左侧图表区固定包含：

```text
K线主图
MACD
成交量
KDJ
底部指标栏
```

```css
:root {
  --sd-chart-area-bg: var(--cs-color-chart-bg);
  --sd-chart-area-border: var(--cs-color-border-subtle);
  --sd-chart-panel-bg: var(--cs-color-chart-panel-bg);
  --sd-chart-panel-border: var(--cs-color-border-subtle);
  --sd-chart-panel-divider: rgba(148, 163, 184, 0.14);
  --sd-chart-panel-gap: 0px;

  --sd-kline-panel-ratio: 44;
  --sd-macd-panel-ratio: 17;
  --sd-volume-panel-ratio: 17;
  --sd-kdj-panel-ratio: 17;
  --sd-indicator-bar-h: 34px;
}
```

推荐 CSS：

```css
.sd-chart-area {
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  display: grid;
  grid-template-rows:
    minmax(0, 44fr)
    minmax(0, 17fr)
    minmax(0, 17fr)
    minmax(0, 17fr)
    var(--sd-indicator-bar-h);
  background: var(--sd-chart-area-bg);
  border: 1px solid var(--sd-chart-area-border);
}
```

## 45.2 K 线主图 Token

```css
:root {
  --sd-kline-bg: var(--cs-color-chart-bg);
  --sd-kline-candle-up: var(--cs-color-market-up);
  --sd-kline-candle-down: var(--cs-color-market-down);
  --sd-kline-candle-flat: var(--cs-color-market-flat);
  --sd-kline-wick-up: var(--cs-color-market-up);
  --sd-kline-wick-down: var(--cs-color-market-down);
  --sd-kline-wick-flat: var(--cs-color-market-flat);
  --sd-kline-latest-price-line: rgba(247, 199, 107, 0.54);
  --sd-kline-prev-close-line: rgba(154, 164, 178, 0.38);
}
```

规则：

1. 阳线红，阴线绿，平盘灰白。
2. 最新价线可使用品牌金弱虚线。
3. 昨收线使用灰白弱虚线。
4. 不做发光 K 线，不使用 3D 或霓虹视觉。

## 45.3 MACD / 成交量 / KDJ Token

```css
:root {
  --sd-macd-dif-color: var(--cs-color-indicator-dif);
  --sd-macd-dea-color: var(--cs-color-indicator-dea);
  --sd-macd-bar-up: var(--cs-color-market-up);
  --sd-macd-bar-down: var(--cs-color-market-down);
  --sd-macd-zero-line: rgba(148, 163, 184, 0.26);

  --sd-volume-bar-up: var(--cs-color-market-up);
  --sd-volume-bar-down: var(--cs-color-market-down);
  --sd-volume-bar-flat: var(--cs-color-market-flat);
  --sd-volume-ma5-color: var(--cs-color-ma-5);
  --sd-volume-ma10-color: var(--cs-color-ma-10);

  --sd-kdj-k-color: var(--cs-color-indicator-k);
  --sd-kdj-d-color: var(--cs-color-indicator-d);
  --sd-kdj-j-color: var(--cs-color-indicator-j);
  --sd-kdj-guide-line: rgba(148, 163, 184, 0.18);
}
```

规则：

1. MACD 正柱红、负柱绿。
2. 成交量柱跟随当根 K 线涨跌方向。
3. KDJ 线不使用红绿，避免与涨跌方向冲突。
4. 副图网格和零轴弱化，不抢主图焦点。

## 45.4 坐标轴与网格线 Token

```css
:root {
  --sd-chart-axis-color: var(--cs-color-chart-axis);
  --sd-chart-axis-label-color: var(--cs-color-chart-label);
  --sd-chart-axis-label-font-size: var(--cs-font-size-11);
  --sd-chart-axis-label-font-family: var(--cs-font-family-number);
  --sd-chart-grid-major: rgba(148, 163, 184, 0.12);
  --sd-chart-grid-minor: rgba(148, 163, 184, 0.07);
  --sd-chart-panel-split-line: rgba(148, 163, 184, 0.14);
  --sd-chart-y-axis-w: 58px;
  --sd-chart-x-axis-h: 22px;
}
```

规则：

1. 坐标轴文字使用数字字体，字号 11px。
2. 网格线低对比，不形成廉价大屏风。
3. panel 分割线比普通网格线略强，但仍保持克制。

## 45.5 底部指标栏 Token

```css
:root {
  --sd-indicator-bar-bg: #0A101C;
  --sd-indicator-bar-border: var(--cs-color-border-subtle);
  --sd-indicator-bar-padding-x: 10px;
  --sd-indicator-bar-gap: 4px;
  --sd-indicator-item-h: 24px;
  --sd-indicator-item-padding-x: 8px;
  --sd-indicator-item-radius: var(--cs-radius-button);
  --sd-indicator-item-text: var(--cs-color-text-secondary);
  --sd-indicator-item-hover-bg: var(--cs-color-surface-card-hover);
  --sd-indicator-item-active-bg: var(--cs-color-brand-accent-bg);
  --sd-indicator-item-active-text: var(--cs-color-brand-accent);
  --sd-indicator-item-disabled-text: var(--cs-color-text-weak);
}
```

P0 实际支持：

```text
MACD / 成交量 / KDJ / 均线(MA) / BOLL
```

未支持指标点击后 Toast：

```text
该指标暂未支持
```

---

# 46. ChartPanelHeaderInfo Token

每个 panel 顶部都有 Header Info。它跟随鼠标所在横轴时间点刷新；鼠标离开图表区后恢复最新一根 K 线数据。

## 46.1 Header Info 基础 Token

```css
:root {
  --sd-chart-header-info-h: 26px;
  --sd-chart-header-info-padding-x: 8px;
  --sd-chart-header-info-gap: 8px;
  --sd-chart-header-info-bg: rgba(10, 16, 28, 0.72);
  --sd-chart-header-info-border: rgba(148, 163, 184, 0.10);
  --sd-chart-header-info-font-size: var(--cs-font-size-12);
  --sd-chart-header-info-label-color: var(--cs-color-text-muted);
  --sd-chart-header-info-value-color: var(--cs-color-text-secondary);
  --sd-chart-header-info-number-font: var(--cs-font-family-number);
}
```

推荐样式：

```css
.sd-chart-header-info {
  height: var(--sd-chart-header-info-h);
  padding: 0 var(--sd-chart-header-info-padding-x);
  display: flex;
  align-items: center;
  gap: var(--sd-chart-header-info-gap);
  font-size: var(--sd-chart-header-info-font-size);
  background: var(--sd-chart-header-info-bg);
  border-bottom: 1px solid var(--sd-chart-header-info-border);
  white-space: nowrap;
  overflow: hidden;
}
```

## 46.2 指标颜色 Token

```css
:root {
  --sd-header-ma5-color: var(--cs-color-ma-5);
  --sd-header-ma15-color: #60A5FA;
  --sd-header-ma30-color: #A78BFA;
  --sd-header-ma60-color: #22D3EE;
  --sd-header-ma120-color: #F97316;
  --sd-header-ma250-color: #94A3B8;

  --sd-header-boll-mid-color: var(--cs-color-ma-20);
  --sd-header-boll-upper-color: #F7C76B;
  --sd-header-boll-lower-color: #22D3EE;

  --sd-header-macd-dif-color: var(--sd-macd-dif-color);
  --sd-header-macd-dea-color: var(--sd-macd-dea-color);
  --sd-header-macd-bar-up: var(--cs-color-market-up);
  --sd-header-macd-bar-down: var(--cs-color-market-down);
}
```

## 46.3 MA/BOLL 下拉入口与齿轮按钮

```css
:root {
  --sd-header-indicator-select-h: 22px;
  --sd-header-indicator-select-padding-x: 6px;
  --sd-header-indicator-select-radius: var(--cs-radius-sm);
  --sd-header-indicator-select-bg: rgba(247, 199, 107, 0.08);
  --sd-header-indicator-select-text: var(--cs-color-brand-accent);
  --sd-header-indicator-select-hover-bg: rgba(247, 199, 107, 0.14);

  --sd-header-gear-size: 22px;
  --sd-header-gear-color: var(--cs-color-text-muted);
  --sd-header-gear-hover-bg: var(--cs-color-surface-card-hover);
  --sd-header-gear-hover-color: var(--cs-color-brand-accent);
}
```

规则：

1. `▼ MA` / `▼ BOLL` 为主图叠加指标入口。
2. 当前选中指标使用品牌金弱背景。
3. 齿轮按钮不可强视觉化，hover 仅弱高亮。
4. 点击齿轮 Toast：`指标设置暂未开通`。

---

# 47. 十字线、Tooltip 与浮标 Token

## 47.1 十字线 Token

```css
:root {
  --sd-crosshair-line-color: rgba(247, 199, 107, 0.78);
  --sd-crosshair-line-w: 1px;
  --sd-crosshair-line-style: solid;
  --sd-crosshair-dot-size: 4px;
  --sd-crosshair-dot-bg: var(--cs-color-brand-accent);
  --sd-crosshair-z: 620;
}
```

状态规则：

1. 非激活态不显示十字线与 Tooltip。
2. 鼠标进入任意图表 panel 时显示该 panel 的 Y 轴浮标和底部时间轴浮标。
3. 单击图表区后进入激活态：十字线和 Tooltip 出现。
4. 再次单击后十字线和 Tooltip 消失。
5. 激活态下 K 线主图、MACD、成交量、KDJ 同一横轴时间对齐。

## 47.2 Tooltip Token

```css
:root {
  --sd-kline-tooltip-w: 232px;
  --sd-kline-tooltip-max-w: 260px;
  --sd-kline-tooltip-bg: rgba(8, 13, 22, 0.96);
  --sd-kline-tooltip-border: rgba(247, 199, 107, 0.28);
  --sd-kline-tooltip-radius: var(--cs-radius-lg);
  --sd-kline-tooltip-shadow: var(--cs-shadow-tooltip);
  --sd-kline-tooltip-padding: 10px 12px;
  --sd-kline-tooltip-font-size: var(--cs-font-size-12);
  --sd-kline-tooltip-line-h: 20px;
  --sd-kline-tooltip-label-color: var(--cs-color-text-muted);
  --sd-kline-tooltip-value-color: var(--cs-color-text-primary);
  --sd-kline-tooltip-z: 720;
}
```

Tooltip 固定避让规则：

```text
鼠标在屏幕左半边：Tooltip 固定显示在 K线主图区右上角
鼠标在屏幕右半边：Tooltip 固定显示在 K线主图区左上角
```

Tooltip 不跟随鼠标漂移，避免遮挡 K 线主体。

## 47.3 Tooltip 字段颜色规则

采用方案 A：

| 字段 | 颜色规则 |
|---|---|
| 开盘价 | 与上一根 K 线收盘价比较，高于红色、低于绿色、相等灰白 |
| 收盘价 | 与上一根 K 线收盘价比较，高于红色、低于绿色、相等灰白 |
| 最高价 | 与开盘价比较，高于红色，否则中性或灰白 |
| 最低价 | 与开盘价比较，低于绿色，否则中性或灰白 |
| 涨幅 | 大于 0 红色，小于 0 绿色，等于 0 灰白 |
| 振幅 | 中性色 |
| 成交量 | 中性色 |
| 成交额 | 中性色 |
| 换手率 | 中性色 |

CSS 建议：

```css
.sd-tooltip-value-up { color: var(--cs-color-market-up); }
.sd-tooltip-value-down { color: var(--cs-color-market-down); }
.sd-tooltip-value-flat { color: var(--cs-color-market-flat); }
.sd-tooltip-value-neutral { color: var(--cs-color-text-secondary); }
```

## 47.4 坐标轴浮标 Token

```css
:root {
  --sd-axis-float-label-bg: rgba(247, 199, 107, 0.16);
  --sd-axis-float-label-border: rgba(247, 199, 107, 0.34);
  --sd-axis-float-label-text: var(--cs-color-text-primary);
  --sd-axis-float-label-radius: var(--cs-radius-sm);
  --sd-axis-float-label-font-size: var(--cs-font-size-11);
  --sd-axis-float-label-font-family: var(--cs-font-family-number);
  --sd-axis-float-label-padding-x: 6px;
  --sd-axis-float-label-h: 20px;
  --sd-axis-float-label-z: 680;

  --sd-y-axis-float-label-min-w: 54px;
  --sd-time-axis-float-label-min-w: 88px;
}
```

浮标规则：

1. Y 轴浮标只在鼠标所在 panel 显示。
2. 时间轴浮标显示当前横轴时间。
3. 非激活态鼠标离开图表区后浮标隐藏。
4. 激活态下浮标随十字线保持显示。
5. 浮标使用品牌金弱背景，不使用红绿，避免与涨跌含义冲突。

---

# 48. 右侧信息栏 Token

## 48.1 右侧信息栏容器

```css
:root {
  --sd-right-panel-bg: var(--cs-color-surface-panel);
  --sd-right-panel-border: var(--cs-color-border-subtle);
  --sd-right-panel-radius: 0px;
  --sd-right-panel-padding: 10px;
  --sd-right-panel-section-gap: 10px;
  --sd-right-panel-tab-h: 30px;
  --sd-right-panel-tab-content-min-h: 0;
}
```

推荐结构：

```text
StockHeader
Tabs：盘口 / 资料
TabContent
```

规则：

1. 右侧信息栏固定高度，不参与整页滚动。
2. TabContent 内部可局部滚动。
3. 不展示五档盘口、逐笔成交、委比委差。
4. 资料 Tab P0 只显示 `暂未开通`。

## 48.2 StockHeader Token

```css
:root {
  --sd-stock-header-bg: var(--cs-color-surface-card);
  --sd-stock-header-border: var(--cs-color-border-subtle);
  --sd-stock-header-radius: var(--cs-radius-card);
  --sd-stock-header-padding: 10px;
  --sd-stock-name-font-size: var(--cs-font-size-18);
  --sd-stock-name-font-weight: var(--cs-font-weight-bold);
  --sd-stock-code-font-size: var(--cs-font-size-12);
  --sd-stock-price-font-size: 28px;
  --sd-stock-price-font-weight: var(--cs-font-weight-bold);
  --sd-stock-action-btn-h: 26px;
  --sd-stock-action-btn-radius: var(--cs-radius-button);
}
```

StockHeader 展示：

```text
股票名称、股票代码、最新价、涨跌额、涨跌幅、所属行业或板块标签、自选、提醒、交易计划
```

## 48.3 右侧表格与资金统计 Token

```css
:root {
  --sd-side-table-header-h: 28px;
  --sd-side-table-row-h: 30px;
  --sd-side-table-font-size: var(--cs-font-size-12);
  --sd-side-table-number-font: var(--cs-font-family-number);
  --sd-money-ring-size: 112px;
  --sd-money-bar-h: 8px;
  --sd-money-bar-radius: var(--cs-radius-pill);
  --sd-money-section-title-size: var(--cs-font-size-13);
}
```

规则：

1. 关联板块表字段：名称、涨幅%、成分股数、类别。
2. 个股资金统计左侧环形资金分布图，右侧金额柱状图。
3. 净流入红，净流出绿，零值灰白。
4. 资金统计只展示客观事实，不输出资金判断结论。

---

# 49. 低高度策略 Token

当 viewport height `< 900px` 时进入低高度策略。不得通过 body 级滚动解决。

```css
:root {
  --sd-low-h-threshold: 900px;
  --sd-low-h-top-market-bar-h: 40px;
  --sd-low-h-breadcrumb-action-bar-h: 30px;
  --sd-low-h-chart-toolbar-h: 32px;
  --sd-low-h-chart-header-info-h: 22px;
  --sd-low-h-indicator-bar-h: 28px;
  --sd-low-h-panel-min-ratio-main: 40;
  --sd-low-h-panel-min-ratio-sub: 14;
  --sd-low-h-font-scale: 0.92;
}
```

低高度 CSS 建议：

```css
@media (max-height: 899px) {
  .stock-detail-page {
    --sd-top-market-bar-h: var(--sd-low-h-top-market-bar-h);
    --sd-breadcrumb-action-bar-h: var(--sd-low-h-breadcrumb-action-bar-h);
    --sd-chart-toolbar-h: var(--sd-low-h-chart-toolbar-h);
    --sd-chart-header-info-h: var(--sd-low-h-chart-header-info-h);
    --sd-indicator-bar-h: var(--sd-low-h-indicator-bar-h);
  }
}
```

低高度策略优先级：

1. 压缩 TopMarketBar、BreadcrumbActionBar、ChartToolbar 高度。
2. 压缩 Header Info 高度和指标栏高度。
3. 压缩图表 panel 内边距、字号、图例间距。
4. 保持 K 线主图仍为最高优先级，不压缩到不可读。
5. 右侧 TabContent 内部局部滚动。
6. 图表区必要时局部提示“当前高度较低，建议使用更大窗口查看行情终端视图”。
7. 不启用 body 级整页滚动。

禁止：

```css
@media (max-height: 899px) {
  body { overflow-y: auto; }
}
```

---

# 50. 对 02 `stock-detail-v1.html` 的视觉约束

1. 页面根容器必须 `height: 100vh`，不得写死 `1080px`。
2. 主内容区高度必须使用 `calc(100vh - var(--sd-top-market-bar-h) - var(--sd-breadcrumb-action-bar-h) - var(--sd-chart-toolbar-h))` 或等价 flex `min-height: 0` 实现。
3. 不允许 body 级整页滚动。
4. 左侧图表区必须包含 K 线主图、MACD、成交量、KDJ、底部指标栏。
5. 每个图表 panel 必须有 Header Info。
6. K 线主图 Header Info 默认 MA，并支持 MA / BOLL 切换入口。
7. 齿轮按钮点击 Toast：`指标设置暂未开通`。
8. 非激活态不显示十字线与 Tooltip，但显示鼠标所在 panel 的 Y 轴浮标和底部时间轴浮标。
9. 单击图表区进入十字线激活态，再次单击退出。
10. 激活态下 K 线主图、MACD、成交量、KDJ 十字线同一横轴时间对齐。
11. Tooltip 根据鼠标在屏幕左半边或右半边固定避让显示。
12. Tooltip 字段颜色按方案 A 执行。
13. 右侧信息栏固定宽度 360–400px，建议 384px。
14. 右侧资料 Tab 显示 `暂未开通`。
15. 诊股入口 disabled。
16. 低于 900px 高度时启用低高度策略，不启用整页滚动。
17. 红涨绿跌必须正确。
18. 页面不输出买卖建议、不输出诊股结论、不做真实交易下单。

# 51. 对 03 `04-component-guidelines.md` 的 Token 映射建议

建议 03 补充或修订以下组件：

| 组件 | 类型 | Token 映射 |
|---|---|---|
| `StockDetailPage` | 页面容器 | `--sd-top-market-bar-h`、`--sd-main-content-h`、固定视口规则 |
| `BreadcrumbActionBar` | 顶部操作栏 | `--sd-breadcrumb-action-*` |
| `StockChartToolbar` | 周期工具栏 | `--sd-chart-toolbar-*` |
| `StockDetailFixedLayout` | 左图右栏布局 | `--sd-right-panel-w`、`--sd-main-grid-gap` |
| `StockKlinePanel` | K 线主图 | `--sd-kline-*`、`--sd-chart-grid-*` |
| `ChartPanelHeaderInfo` | 图表 Header Info | `--sd-chart-header-info-*`、`--sd-header-ma*`、`--sd-header-boll-*` |
| `MainOverlayIndicatorMenu` | MA/BOLL 下拉 | `--sd-header-indicator-select-*` |
| `MacdPanel` | MACD 副图 | `--sd-macd-*` |
| `VolumePanel` | 成交量副图 | `--sd-volume-*` |
| `KdjPanel` | KDJ 副图 | `--sd-kdj-*` |
| `ChartCrosshairLayer` | 十字线层 | `--sd-crosshair-*` |
| `ChartAxisFloatLabel` | 坐标轴浮标 | `--sd-axis-float-label-*` |
| `KlineTooltip` | K 线 Tooltip | `--sd-kline-tooltip-*` |
| `IndicatorToolbar` | 底部指标栏 | `--sd-indicator-*` |
| `StockSidePanel` | 右侧信息栏 | `--sd-right-panel-*` |
| `StockHeaderPanel` | 股票头部 | `--sd-stock-header-*` |
| `RelatedSectorTable` | 关联板块表 | `--sd-side-table-*` |
| `StockMoneyFlowPanel` | 个股资金统计 | `--sd-money-*` |

组件规范中必须明确：

1. `--sd-*` 是个股详情页布局和图表专属 Token，不替代 `--cs-*` 全局 Token。
2. 图表交互状态由组件内部管理，但视觉必须使用 Token。
3. 低高度策略属于页面布局组件职责，不能由 body 滚动兜底。

# 52. 本轮个股详情页修改摘要

1. 新增个股详情页固定视口布局 Token。
2. 明确页面根容器高度为 `100vh`。
3. 明确主内容区高度通过 `calc(100vh - TopMarketBar - BreadcrumbActionBar - ChartToolbar)` 得出。
4. 明确禁止写死 `1080px`。
5. 明确禁止 body 级整页滚动。
6. 新增 TopMarketBar、BreadcrumbActionBar、ChartToolbar 对应的个股详情页高度 Token。
7. 新增 K 线主图、MACD、成交量、KDJ、底部指标栏 Token。
8. 新增 ChartPanelHeaderInfo、MA/BOLL 下拉、齿轮按钮 Token。
9. 新增十字线、Tooltip、坐标轴浮标 Token。
10. 新增右侧信息栏、StockHeader、关联板块表、个股资金统计 Token。
11. 新增 viewport height `< 900px` 低高度策略。

# 53. 本轮未修改区域说明

本轮没有主动修改以下既有规则：

1. 市场总览 Review v9 新闻速览与个股新闻板块规则。
2. 市场总览连板天梯股票卡片规则。
3. 市场总览 TopMarketBar、Breadcrumb、PageHeader、ShortcutBar。
4. 通用组件库 Demo Csq 组件 Token。
5. 全局深色 / 浅色主题 Token。
6. 全局字体 Token。
7. 红涨绿跌硬规则。

# 54. 本轮新增或修订 Token 清单

| Token | 类型 | 说明 |
|---|---|---|
| `--sd-top-market-bar-h` | 新增 | 个股详情页 TopMarketBar 高度 |
| `--sd-breadcrumb-action-bar-h` | 新增 | 面包屑操作栏高度 |
| `--sd-chart-toolbar-h` | 新增 | 图表周期工具栏高度 |
| `--sd-main-content-h` | 新增 | 主内容区高度 calc 结果 |
| `--sd-right-panel-w` | 新增 | 右侧信息栏宽度 |
| `--sd-min-viewport-h` | 新增 | 最低可用视口高度 |
| `--sd-min-viewport-w` | 新增 | 最低可用视口宽度 |
| `--sd-chart-area-*` | 新增 | 左侧图表区容器 |
| `--sd-kline-*` | 新增 | K 线主图视觉 |
| `--sd-macd-*` | 新增 | MACD 副图视觉 |
| `--sd-volume-*` | 新增 | 成交量副图视觉 |
| `--sd-kdj-*` | 新增 | KDJ 副图视觉 |
| `--sd-chart-axis-*` | 新增 | 坐标轴视觉 |
| `--sd-chart-grid-*` | 新增 | 网格线视觉 |
| `--sd-chart-header-info-*` | 新增 | 图表 Header Info |
| `--sd-header-indicator-select-*` | 新增 | MA/BOLL 下拉入口 |
| `--sd-header-gear-*` | 新增 | 齿轮按钮 |
| `--sd-crosshair-*` | 新增 | 十字线 |
| `--sd-kline-tooltip-*` | 新增 | K 线 Tooltip |
| `--sd-axis-float-label-*` | 新增 | 坐标轴浮标 |
| `--sd-right-panel-*` | 新增 | 右侧信息栏 |
| `--sd-stock-header-*` | 新增 | 右侧 StockHeader |
| `--sd-side-table-*` | 新增 | 右侧表格 |
| `--sd-money-*` | 新增 | 右侧资金统计 |
| `--sd-low-h-*` | 新增 | 低高度策略 |

# 55. 待产品总控确认问题

1. `--sd-top-market-bar-h: 44px` 是否作为个股详情页最终高度，还是需要与全站 TopMarketBar 高度完全一致。
2. `--sd-right-panel-w: 384px` 是否作为默认值，还是在 1440px 宽度下压缩到 360px。
3. K 线主图与三副图的比例是否采用 `44fr / 17fr / 17fr / 17fr`，还是需要在 Showcase 中微调。
4. Tooltip 字段排序是否最终固定为：时间、开、收、高、低、涨幅、振幅、成交量、成交额、换手率。
5. 低高度 `<900px` 时是否展示显性提示，还是只做静默压缩。
6. 右侧资金统计环形图和金额柱是否需要在 Token 中继续细化颜色与比例。

# 56. 本轮输出文件下载链接

本轮输出文件名：

```text
03-design-tokens.md
```

下载链接由本轮对话附件提供。

建议放置到 Google Drive：

```text
财势乾坤/设计/03-design-tokens.md
```

---

# 57. 个股详情页 Showcase 局部修正规则（v0.3.8）

> 本节仅处理个股详情页 Showcase 的 3 个局部修正：
>
> 1. 顶部复用市场总览 `TopMarketBar`；
> 2. K 线与指标区左右 Y 轴刻度常驻显示；
> 3. 删除图表区顶部右上角额外价格 / 涨幅块。
>
> 本节不修改 K 线主图整体比例、MACD / 成交量 / KDJ 默认副图结构、十字光标交互逻辑、Tooltip 字段和颜色规则、右侧 StockHeader / 盘口 / 资料结构、关联板块表、个股资金统计图、周期 Toolbar、资料 Tab 暂未开通、诊股 disabled、红涨绿跌规则。

## 57.1 本轮读取文件与修订边界

本轮依据：

```text
财势乾坤/项目总说明/财势乾坤行情软件项目总说明_v_0_2.md
财势乾坤/产品文档/个股详情页产品需求文档_v_0_2.md
财势乾坤/设计/03-design-tokens.md
```

本节只补充个股详情页 Showcase 的局部视觉规则，不改变此前 v0.3.7 已确认的固定视口交易终端布局规则：

```text
页面根容器高度 = 100vh
主内容区高度 = calc(100vh - TopMarketBar - BreadcrumbActionBar - ChartToolbar)
不写死 1080px
不使用 body 级整页滚动
```

## 57.2 TopMarketBar 复用规则

### 57.2.1 定义边界

在个股详情页中，本节所说的 **顶部 Header** 只指：

```text
TopMarketBar
```

不包括：

```text
BreadcrumbActionBar
PageHeader
ChartToolbar
```

### 57.2.2 复用要求

个股详情页顶部必须完全复用市场总览既有 `TopMarketBar`。

要求：

1. 不允许个股详情页另做一套顶部栏。
2. 不允许为个股详情页单独设计新的顶部 Header 风格。
3. `TopMarketBar` 中的 Logo、系统入口、指数行情条、当前时间、交易状态、数据状态、用户入口等规则全部继承市场总览已确认规则。
4. 个股详情页不得在 `TopMarketBar` 下方额外新增“大号个股价格 Header”。
5. 个股详情页的页面层级和操作信息放在 `BreadcrumbActionBar`，不放在 `TopMarketBar` 中。

### 57.2.3 Token 映射

```css
:root {
  /* Stock detail top bar reuses global TopMarketBar */
  --sd-top-market-bar-h: var(--cs-layout-top-market-bar-height);
  --sd-top-market-bar-bg: var(--cs-color-bg-top-market-bar);
  --sd-top-market-bar-border: var(--cs-color-border-subtle);
  --sd-top-market-bar-z: var(--cs-z-topbar);
}
```

说明：

- 如果市场总览 `TopMarketBar` 高度后续调整，个股详情页同步继承。
- 不在 `--sd-*` 中定义独立的顶部栏颜色体系。
- `BreadcrumbActionBar` 可继续使用个股详情页局部 Token，但不得被称为 TopMarketBar。

## 57.3 图表左右 Y 轴刻度常驻规则

### 57.3.1 总规则

K 线主图、MACD、成交量、KDJ 每个图表 panel 左右两侧都必须常驻显示 Y 轴刻度。

要求：

1. Y 轴刻度不依赖十字坐标线。
2. 无论十字线是否显示，左右 Y 轴刻度都要显示。
3. 左右 Y 轴刻度必须与横向网格线对齐。
4. 每个 panel 使用自己的 Y 轴单位和格式。
5. 不同 panel 的 Y 轴刻度值不得共用一套价格刻度。
6. 十字线激活时，Y 轴浮标可以覆盖在常驻刻度层之上，但不得导致常驻刻度消失。

### 57.3.2 各 panel 刻度口径

| Panel | 左右 Y 轴刻度内容 | 格式建议 |
|---|---|---|
| K 线主图 | 价格刻度 | `18.20`、`19.45`，保留 2 位小数 |
| MACD | MACD 数值刻度 | `-0.35`、`0.00`、`0.42` |
| 成交量 | 成交量刻度 | `12.5万`、`320万`、`1.2亿` |
| KDJ | KDJ 数值刻度 | `20`、`50`、`80`、`100` |

### 57.3.3 Token

```css
:root {
  /* Permanent Y axes inside stock detail chart panels */
  --sd-chart-y-axis-left-w: 48px;
  --sd-chart-y-axis-right-w: 52px;
  --sd-chart-y-axis-label-size: var(--cs-font-size-11);
  --sd-chart-y-axis-label-color: var(--cs-color-chart-label);
  --sd-chart-y-axis-label-font-family: var(--cs-font-family-number);
  --sd-chart-y-axis-label-padding-x: 6px;
  --sd-chart-y-axis-line-color: rgba(148, 163, 184, 0.16);
  --sd-chart-y-axis-line-width: 1px;
  --sd-chart-y-axis-bg: transparent;

  /* Panel plot area reserves both axis widths */
  --sd-chart-plot-padding-left: var(--sd-chart-y-axis-left-w);
  --sd-chart-plot-padding-right: var(--sd-chart-y-axis-right-w);
}
```

### 57.3.4 CSS 建议

```css
.sd-chart-panel {
  position: relative;
  display: grid;
  grid-template-columns:
    var(--sd-chart-y-axis-left-w)
    minmax(0, 1fr)
    var(--sd-chart-y-axis-right-w);
  overflow: hidden;
}

.sd-chart-y-axis {
  position: relative;
  z-index: var(--sd-chart-axis-z);
  color: var(--sd-chart-y-axis-label-color);
  font-size: var(--sd-chart-y-axis-label-size);
  font-family: var(--sd-chart-y-axis-label-font-family);
  font-variant-numeric: tabular-nums;
  pointer-events: none;
}

.sd-chart-y-axis-left {
  border-right: var(--sd-chart-y-axis-line-width) solid var(--sd-chart-y-axis-line-color);
  text-align: right;
  padding-right: var(--sd-chart-y-axis-label-padding-x);
}

.sd-chart-y-axis-right {
  border-left: var(--sd-chart-y-axis-line-width) solid var(--sd-chart-y-axis-line-color);
  text-align: left;
  padding-left: var(--sd-chart-y-axis-label-padding-x);
}
```

实现约束：

- 图表绘图区必须扣除左右 Y 轴宽度。
- 网格线应延伸至绘图区，不应压到刻度文字上。
- 如果左右刻度使用同一组数值，左右位置必须保持完全对齐。
- 如果未来支持左右不同指标刻度，需另行设计，P0 不做。

## 57.4 横向网格线与 Y 轴刻度对齐

横向网格线数量与 Y 轴刻度数量必须一致或一一映射。

```css
:root {
  --sd-chart-grid-horizontal-count-kline: 5;
  --sd-chart-grid-horizontal-count-indicator: 3;
  --sd-chart-grid-align-y-axis: true;
}
```

规则：

1. K 线主图建议 5 档价格刻度。
2. MACD / 成交量 / KDJ 建议 3～4 档刻度。
3. 刻度值所在 y 坐标必须与对应横向网格线一致。
4. 零轴属于特殊网格线，MACD 和资金类图表应增强显示。
5. Y 轴浮标出现时，应吸附到鼠标 y 坐标，不改变常驻刻度布局。

## 57.5 时间轴刻度常驻规则

### 57.5.1 总规则

时间轴刻度必须常驻显示，不依赖十字坐标线。

要求：

1. 时间轴刻度位于图表底部时间轴区域。
2. 时间轴刻度必须与图表横向坐标对齐。
3. 时间轴浮标出现时，可以覆盖或贴近常驻刻度层，但不得隐藏常驻刻度。
4. 不同周期使用不同时间刻度策略。

### 57.5.2 周期刻度规则

| 周期 | 时间轴刻度策略 | 示例 |
|---|---|---|
| 日线 | 按月份或关键月份节点显示 | `2025/10`、`11`、`12`、`01`、`02`、`03`、`04`、`05` |
| 周线 | 按月份或季度节点显示 | `2025/10`、`2026/01`、`2026/04` |
| 月线 | 按年份或关键年份节点显示 | `2021`、`2022`、`2023`、`2024`、`2025` |
| 分钟线 | 按交易日间隔显示日期刻度 | 每 2 个交易日显示一个日期刻度 |
| 分时 | 按交易时段关键时间显示 | `09:30`、`10:30`、`11:30`、`13:00`、`14:00`、`15:00` |

### 57.5.3 日线示例

日线时间轴可显示：

```text
2025/10    11    12    01    02    03    04    05
```

说明：

- 第一个跨年或跨较长区间节点可显示完整 `YYYY/MM`。
- 后续同一年或同一连续月份可显示 `MM`。
- 如果空间不足，优先保留首尾和跨年节点。

### 57.5.4 分钟线示例

分钟线建议：

```text
每 2 个交易日显示一个日期刻度
```

例如：

```text
04/22    04/24    04/28    04/30    05/06
```

### 57.5.5 Token

```css
:root {
  --sd-chart-x-axis-h: 24px;
  --sd-chart-x-axis-label-size: var(--cs-font-size-11);
  --sd-chart-x-axis-label-color: var(--cs-color-chart-label);
  --sd-chart-x-axis-label-font-family: var(--cs-font-family-number);
  --sd-chart-x-axis-line-color: rgba(148, 163, 184, 0.16);
  --sd-chart-x-axis-tick-color: rgba(148, 163, 184, 0.24);
  --sd-chart-x-axis-tick-height: 4px;
  --sd-chart-x-axis-label-padding-top: 4px;
}
```

### 57.5.6 CSS 建议

```css
.sd-chart-x-axis {
  height: var(--sd-chart-x-axis-h);
  border-top: 1px solid var(--sd-chart-x-axis-line-color);
  color: var(--sd-chart-x-axis-label-color);
  font-size: var(--sd-chart-x-axis-label-size);
  font-family: var(--sd-chart-x-axis-label-font-family);
  font-variant-numeric: tabular-nums;
  pointer-events: none;
}
```

实现约束：

- 时间轴刻度应根据当前周期和数据密度自动抽样。
- 不得把时间轴刻度只放进 Tooltip。
- 不得只有十字线激活时才显示时间。

## 57.6 删除图表区顶部右上角额外价格 / 涨幅块

### 57.6.1 禁止内容

个股详情页不在图表区顶部右上角额外展示大号：

```text
最新价
涨跌额
涨跌幅
```

禁止出现：

```text
图表区顶部右上角价格块
Header 下方独立价格涨幅浮块
K 线主图右上角大号价格模块
```

### 57.6.2 信息归位

个股价格信息应放在：

```text
右侧 StockHeader / 行情信息区
```

而不是放在：

```text
图表区顶部右上角
TopMarketBar 下方
BreadcrumbActionBar 与 ChartToolbar 之间的额外块
```

### 57.6.3 Token 与 CSS 禁用约束

```css
:root {
  --sd-chart-extra-price-block-display: none;
}

.sd-chart-extra-price-block,
.sd-kline-top-price-summary,
.sd-chart-header-price-float {
  display: var(--sd-chart-extra-price-block-display);
}
```

规则：

1. ChartPanelHeaderInfo 只展示指标信息，例如 MA、BOLL、MACD、VOL、KDJ。
2. ChartPanelHeaderInfo 不承担个股实时价格 Header 职责。
3. 右侧 StockHeader 是个股最新价、涨跌额、涨跌幅的唯一主展示区域。
4. 十字线 Tooltip 可展示当前 K 线价格，但不属于常驻价格块。

## 57.7 对既有个股详情页规则的兼容

本轮不改变以下已确认规则：

1. 根容器 `height: 100vh`。
2. 主内容区高度 `calc(100vh - TopMarketBar - BreadcrumbActionBar - ChartToolbar)`。
3. 不写死 `1080px`。
4. 不使用 body 级整页滚动。
5. K 线主图、MACD、成交量、KDJ 默认副图结构。
6. ChartPanelHeaderInfo 跟随鼠标横轴时间点刷新。
7. 单击开启 / 关闭十字线和 Tooltip。
8. Tooltip 左右避让规则。
9. Tooltip 字段与颜色方案 A。
10. 右侧 StockHeader、盘口 / 资料 Tab、关联板块表、个股资金统计图。
11. 周期 Toolbar。
12. 资料 Tab 暂未开通。
13. 诊股 disabled。
14. 红涨绿跌规则。

---

# 58. 本轮个股详情局部修正摘要

1. 明确个股详情页顶部 Header 只指 `TopMarketBar`。
2. 明确个股详情页 `TopMarketBar` 必须完全复用市场总览 `TopMarketBar`。
3. 明确 `BreadcrumbActionBar`、`PageHeader`、`ChartToolbar` 不属于本轮所说的 Header。
4. 明确 K 线主图、MACD、成交量、KDJ 每个 panel 左右两侧都必须常驻显示 Y 轴刻度。
5. 明确 Y 轴刻度不依赖十字坐标线。
6. 明确 Y 轴刻度值必须与横向网格线对齐。
7. 明确每个 panel 使用自己的 Y 轴单位和格式。
8. 明确时间轴刻度常驻显示，不依赖十字坐标线。
9. 明确日线 / 周线 / 月线与分钟线的时间轴刻度策略。
10. 明确删除图表区顶部右上角额外价格 / 涨幅块。
11. 明确个股价格信息归位到右侧 StockHeader / 行情信息区。

# 59. 本轮未修改区域说明

本轮没有主动修改以下区域：

1. K 线主图整体比例；
2. MACD / 成交量 / KDJ 默认副图结构；
3. 十字光标交互逻辑；
4. Tooltip 字段和颜色规则；
5. 右侧 StockHeader / 盘口 / 资料结构；
6. 关联板块表；
7. 个股资金统计图；
8. 周期 Toolbar；
9. 资料 Tab 暂未开通；
10. 诊股 disabled；
11. 红涨绿跌规则；
12. 市场总览既有模块规则；
13. 通用组件库 Demo 规则。

```text
本轮因个股详情 Showcase 局部修正而被动影响的区域：无
原因：仅补充 TopMarketBar 复用、图表轴刻度常驻、删除额外价格块三个局部视觉规则
是否需要产品总控确认：否
```

# 60. 本轮新增或修订 Token 清单

| Token | 类型 | 说明 |
|---|---|---|
| `--sd-top-market-bar-h` | 修订 | 改为继承市场总览 TopMarketBar 高度 |
| `--sd-top-market-bar-bg` | 新增 | 复用市场总览 TopMarketBar 背景 |
| `--sd-top-market-bar-border` | 新增 | 复用市场总览 TopMarketBar 边框 |
| `--sd-top-market-bar-z` | 新增 | 复用全局顶部栏层级 |
| `--sd-chart-y-axis-left-w` | 新增 | 左侧 Y 轴刻度宽度 |
| `--sd-chart-y-axis-right-w` | 新增 | 右侧 Y 轴刻度宽度 |
| `--sd-chart-y-axis-label-size` | 新增 | Y 轴刻度字号 |
| `--sd-chart-y-axis-label-color` | 新增 | Y 轴刻度颜色 |
| `--sd-chart-y-axis-label-font-family` | 新增 | Y 轴刻度数字字体 |
| `--sd-chart-y-axis-label-padding-x` | 新增 | Y 轴刻度横向内边距 |
| `--sd-chart-y-axis-line-color` | 新增 | Y 轴边线颜色 |
| `--sd-chart-y-axis-line-width` | 新增 | Y 轴边线宽度 |
| `--sd-chart-plot-padding-left` | 新增 | 绘图区为左 Y 轴保留宽度 |
| `--sd-chart-plot-padding-right` | 新增 | 绘图区为右 Y 轴保留宽度 |
| `--sd-chart-grid-horizontal-count-kline` | 新增 | K 线主图横向网格线数量建议 |
| `--sd-chart-grid-horizontal-count-indicator` | 新增 | 指标 panel 横向网格线数量建议 |
| `--sd-chart-x-axis-h` | 新增 | 时间轴高度 |
| `--sd-chart-x-axis-label-size` | 新增 | 时间轴刻度字号 |
| `--sd-chart-x-axis-label-color` | 新增 | 时间轴刻度颜色 |
| `--sd-chart-x-axis-label-font-family` | 新增 | 时间轴刻度数字字体 |
| `--sd-chart-x-axis-line-color` | 新增 | 时间轴线颜色 |
| `--sd-chart-x-axis-tick-color` | 新增 | 时间轴刻度短线颜色 |
| `--sd-chart-x-axis-tick-height` | 新增 | 时间轴刻度短线高度 |
| `--sd-chart-extra-price-block-display` | 新增 | 图表区顶部额外价格块禁用显示 |

# 61. 对 03 `04-component-guidelines.md` 的 Token 映射建议

建议 03 对以下组件补充映射：

| 组件 | 映射 Token / 规则 |
|---|---|
| `TopMarketBar` | 个股详情页直接复用市场总览 TopMarketBar，不新增个股详情专属 Header 组件 |
| `StockDetailPageShell` | `--sd-top-market-bar-h`、`--sd-breadcrumb-action-bar-h`、`--sd-chart-toolbar-h`、`--sd-main-content-h` |
| `StockChartPanel` | `--sd-chart-y-axis-left-w`、`--sd-chart-y-axis-right-w`、`--sd-chart-x-axis-h`、`--sd-chart-grid-*` |
| `StockChartYAxis` | `--sd-chart-y-axis-*`，左右常驻显示 |
| `StockChartXAxis` | `--sd-chart-x-axis-*`，时间轴常驻显示 |
| `ChartAxisFloatLabel` | 继续使用既有 `--sd-axis-float-label-*`，仅作为十字线辅助浮标，不取代常驻刻度 |
| `ChartPanelHeaderInfo` | 只展示指标信息，不展示常驻价格涨幅块 |
| `KlineTooltip` | 继续沿用既有 Tooltip 字段和颜色方案 A |
| `StockHeaderPanel` | 作为最新价、涨跌额、涨跌幅的主展示区域 |

组件约束：

1. `StockChartPanel` 必须拆出或显式渲染左右 Y 轴刻度区。
2. `Y-axis float label` 不能替代常驻 Y 轴刻度。
3. `X-axis float label` 不能替代常驻时间轴刻度。
4. 不新增 `StockDetailTopHeader` 一类自定义顶部栏组件。
5. 不在图表区域新增 `PriceSummaryFloat`、`TopRightPriceBlock` 等组件。

# 62. 对 02 `stock-detail-v1.html` 的视觉约束

1. 顶部必须复用市场总览 `TopMarketBar`。
2. 不允许个股详情页另做一套顶部栏。
3. `BreadcrumbActionBar` 不属于本轮所说 Header，不得替代 `TopMarketBar`。
4. K 线主图、MACD、成交量、KDJ 每个 panel 左右都必须常驻显示 Y 轴刻度。
5. Y 轴刻度必须与横向网格线对齐。
6. K 线主图显示价格刻度。
7. MACD 显示 MACD 数值刻度。
8. 成交量显示成交量刻度。
9. KDJ 显示 KDJ 数值刻度。
10. 时间轴刻度必须常驻显示，不依赖十字坐标线。
11. 日线 / 周线 / 月线按月份、关键月份或年份节点显示刻度。
12. 日线示例可以为 `2025/10、11、12、01、02、03、04、05`。
13. 分钟线可按交易日间隔显示日期刻度，建议每 2 个交易日显示一个日期刻度。
14. 图表区顶部右上角不得额外展示大号最新价 / 涨跌额 / 涨跌幅块。
15. 个股价格信息必须放在右侧 StockHeader / 行情信息区。
16. 不修改 K 线主图比例、副图结构、十字线交互、Tooltip 字段、右侧信息栏结构、周期 Toolbar、资料 Tab、诊股 disabled 和红涨绿跌规则。

# 63. 待产品总控确认问题

1. 个股详情页 `TopMarketBar` 是否在所有行情详情页中都强制复用市场总览版本，当前建议是“是”。
2. K 线主图左右 Y 轴是否显示完全相同的价格刻度，当前 P0 建议左右一致。
3. 指标 panel 左右 Y 轴是否显示完全相同的刻度，当前 P0 建议左右一致。
4. 时间轴刻度在低宽度下是否允许只保留首尾与关键月份节点，当前建议允许。
5. 图表区顶部右上价格块是否彻底移除，当前建议彻底移除，价格信息只保留在右侧 StockHeader。
6. 分钟线“每 2 个交易日显示一个日期刻度”是否作为默认规则，当前建议作为默认规则，后续可根据数据密度自适应。

# 64. 本轮输出文件下载链接

本轮输出文件名：

```text
03-design-tokens.md
```

下载链接由本轮对话附件提供。

建议放置到 Google Drive：

```text
财势乾坤/设计/03-design-tokens.md
```

---

# 65. 个股详情页顶部结构视觉规则（Stock Detail Review v2）

> 本节为 `stock-detail-html-review-v2-总控解读与变更单` 的局部修订规则。  
> 本节只处理 `个股详情页 / 顶部结构`：TopMarketBar 复用、Breadcrumb 轻量路径行、删除绿色框独立控制行、Chart Workspace Toolbar 视觉规则。  
> 本节不修改 K 线主图、MACD、成交量、KDJ、坐标轴刻度、时间轴刻度、十字坐标线、Tooltip、Header Info 条、MA / BOLL 切换、右侧 StockHeader、盘口 / 资料 Tab、关联板块表、个股资金统计图、周期按钮集合本身、资料 Tab 暂未开通、诊股 disabled、API 字段、数据字典或红涨绿跌规则。

## 65.1 本节适用范围

适用于：

```text
乾坤行情 / 个股详情
```

页面基线保持：

1. 页面名称是“个股详情”。
2. 页面属于“乾坤行情”。
3. 页面不是独立一级菜单。
4. 页面根容器使用固定视口 `100vh`。
5. 不使用 body 级整页滚动。
6. 页面只展示 A 股个股事实行情。
7. 不输出买卖建议。
8. 不展示诊股结论。
9. 中国市场红涨绿跌。
10. 诊股 P0 disabled。
11. 资料 Tab P0 显示“暂未开通”。

## 65.2 顶部最终结构

修改前问题结构：

```text
TopMarketBar
Breadcrumb
绿色框独立控制行 / 空行
Chart Toolbar
K线主图
MACD
成交量
KDJ
```

修改后目标结构：

```text
TopMarketBar
Breadcrumb
Chart Workspace Toolbar
K线主图
MACD
成交量
KDJ
```

规则：

1. `TopMarketBar` 完全复用市场总览同款全局顶部栏。
2. `Breadcrumb` 只保留路径。
3. 删除绿色框独立控制 / 占位行。
4. `Chart Workspace Toolbar` 紧接 Breadcrumb 下方。
5. `Chart Workspace Toolbar` 承载股票识别、周期切换、前复权、股票资料、诊股、设置。
6. 不显示独立的更新时间、刷新、READY。
7. 不在图表区顶部右上角额外显示大号价格 / 涨跌幅块。

## 65.3 TopMarketBar 复用规则

### 65.3.1 Header 定义

本轮所说 Header 仅指：

```text
TopMarketBar
```

不包括：

```text
Breadcrumb
PageHeader
BreadcrumbActionBar
Compact PageHeader
Chart Workspace Toolbar
StockHeader
右侧 StockHeader / 行情信息区
```

### 65.3.2 复用要求

个股详情页最顶部必须完全复用市场总览的 `TopMarketBar`。

复用内容包括：Logo、产品名称、一级系统入口、当前系统高亮、指数行情条、当前时间、交易状态、数据状态、用户入口。

### 65.3.3 禁止事项

禁止：

1. 为个股详情页单独设计另一套顶部全局栏。
2. 在 `TopMarketBar` 中加入个股名称、代码、最新价、涨跌幅、前复权等个股专属信息。
3. 改变市场总览 `TopMarketBar` 的高度、间距、字号、色彩和视觉层级。
4. 将 `Breadcrumb`、`BreadcrumbActionBar`、`Chart Workspace Toolbar` 当作 Header 替代 `TopMarketBar`。
5. 因个股详情页修改破坏市场总览 `TopMarketBar` 的视觉一致性。

### 65.3.4 Token 约束

个股详情页不得新增专属 TopMarketBar Token。继续使用全局 / 市场总览既有 TopMarketBar Token：

```css
:root {
  --sd-top-market-bar-h: var(--cs-layout-top-market-bar-height);
}
```

说明：

- `--sd-top-market-bar-h` 仅是个股详情固定视口布局的高度引用变量。
- 它不定义新的 TopMarketBar 视觉样式。
- TopMarketBar 的视觉样式仍由既有全局 `TopMarketBar` Token 控制。

## 65.4 Breadcrumb 轻量路径行

### 65.4.1 内容规则

Breadcrumb 行只保留路径：

```text
财势乾坤 / 乾坤行情 / 个股详情 / 福斯特 603806.SH
```

### 65.4.2 不承载内容

Breadcrumb 行不承载：前复权、更新时间、刷新、READY、数据状态、图表周期、图表指标控制、股票价格 / 涨跌幅、任何图表工作区控制职责。

### 65.4.3 视觉规则

Breadcrumb 是轻量路径行，目标是低高度、低视觉权重、清晰定位。

```css
:root {
  --sd-breadcrumb-row-h: 30px;
  --sd-breadcrumb-row-padding-x: 12px;
  --sd-breadcrumb-row-bg: var(--cs-color-bg-breadcrumb);
  --sd-breadcrumb-row-border: 1px solid var(--cs-color-border-subtle);
  --sd-breadcrumb-font-size: var(--cs-font-size-12);
  --sd-breadcrumb-text-color: var(--cs-color-text-muted);
  --sd-breadcrumb-current-color: var(--cs-color-text-secondary);
  --sd-breadcrumb-separator-color: var(--cs-color-text-weak);
}
```

```css
.sd-stock-breadcrumb-row {
  height: var(--sd-breadcrumb-row-h);
  padding: 0 var(--sd-breadcrumb-row-padding-x);
  display: flex;
  align-items: center;
  background: var(--sd-breadcrumb-row-bg);
  border-bottom: var(--sd-breadcrumb-row-border);
  font-size: var(--sd-breadcrumb-font-size);
  color: var(--sd-breadcrumb-text-color);
  overflow: hidden;
  white-space: nowrap;
}

.sd-stock-breadcrumb-row .is-current {
  color: var(--sd-breadcrumb-current-color);
}
```

## 65.5 删除绿色框独立控制行后的垂直节奏

### 65.5.1 删除规则

删除截图中绿色框标出的整条独立控制 / 占位行。

该行不再作为控制条、占位行、空白缓冲区、数据状态行、页面级操作行、前复权容器、更新时间 / 刷新 / READY 容器。

### 65.5.2 垂直节奏规则

删除后：

```text
TopMarketBar
Breadcrumb
Chart Workspace Toolbar
```

必须连续排列。

要求：

1. `Chart Workspace Toolbar` 应紧接 Breadcrumb 下方。
2. 不保留绿色框行的同等高度空白。
3. 不通过 `margin-top` / `padding-top` 模拟被删除行。
4. 顶部视觉应更轻，释放 K 线区域有效高度。
5. 主内容区高度计算仍遵守固定视口布局，不启用 body 级滚动。

### 65.5.3 固定视口高度变量修正

```css
:root {
  --sd-breadcrumb-action-bar-h: var(--sd-breadcrumb-row-h);
  --sd-chart-toolbar-h: 38px;
  --sd-removed-control-row-h: 0px;
  --sd-top-stack-extra-gap: 0px;
}
```

主内容区高度继续使用：

```css
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

禁止：

```css
/* 禁止保留绿色框行高度 */
--sd-removed-control-row-h: 34px;

/* 禁止通过额外 padding/margin 制造旧空白 */
margin-top: 34px;
padding-top: 34px;
```

## 65.6 Chart Workspace Toolbar

### 65.6.1 组件定位

红框区域定义为：

```text
Chart Workspace Toolbar
```

它是 K 线图表工作区的一部分，不是全局 Header，不是 Breadcrumb，不是 PageHeader。

### 65.6.2 布局结构

```text
左侧：股票识别区
中间：周期切换区
右侧：操作区（前复权 / 股票资料 / 诊股 / 设置）
```

### 65.6.3 Token

```css
:root {
  --sd-chart-workspace-toolbar-h: 38px;
  --sd-chart-workspace-toolbar-bg: var(--cs-color-surface-panel-subtle);
  --sd-chart-workspace-toolbar-border-top: 0;
  --sd-chart-workspace-toolbar-border-bottom: 1px solid var(--cs-color-border-subtle);
  --sd-chart-workspace-toolbar-padding-x: 12px;
  --sd-chart-workspace-toolbar-gap: 12px;
  --sd-chart-workspace-toolbar-radius: 0;

  --sd-chart-workspace-stock-id-min-w: 168px;
  --sd-chart-workspace-period-gap: 4px;
  --sd-chart-workspace-actions-gap: 6px;

  --sd-chart-workspace-divider-color: var(--cs-color-divider);
  --sd-chart-workspace-control-h: 26px;
  --sd-chart-workspace-control-padding-x: 9px;
  --sd-chart-workspace-control-radius: var(--cs-radius-md);
  --sd-chart-workspace-control-font-size: var(--cs-font-size-12);
}
```

### 65.6.4 推荐 CSS

```css
.sd-chart-workspace-toolbar {
  height: var(--sd-chart-workspace-toolbar-h);
  padding: 0 var(--sd-chart-workspace-toolbar-padding-x);
  display: grid;
  grid-template-columns: minmax(var(--sd-chart-workspace-stock-id-min-w), auto) 1fr auto;
  align-items: center;
  gap: var(--sd-chart-workspace-toolbar-gap);
  background: var(--sd-chart-workspace-toolbar-bg);
  border-top: var(--sd-chart-workspace-toolbar-border-top);
  border-bottom: var(--sd-chart-workspace-toolbar-border-bottom);
  border-radius: var(--sd-chart-workspace-toolbar-radius);
}
```

### 65.6.5 与 K 线主图的视觉连接关系

1. `Chart Workspace Toolbar` 是图表工作区顶部边界。
2. 下方直接连接 K 线主图 panel。
3. Toolbar 与 K 线主图之间只允许使用 1px 弱分割线。
4. 不允许再插入第二条工具栏、价格摘要条或状态行。
5. Toolbar 背景应略高于图表背景，但低于全局 TopMarketBar 的视觉层级。

### 65.6.6 与 TopMarketBar 的层级差异

| 区域 | 层级 | 职责 | 可包含内容 |
|---|---|---|---|
| TopMarketBar | 全局层 | 系统导航、指数条、全局状态 | Logo、系统入口、指数行情、时间、交易状态、数据状态、用户入口 |
| Breadcrumb | 页面定位层 | 路径定位 | 财势乾坤 / 乾坤行情 / 个股详情 / 股票 |
| Chart Workspace Toolbar | 图表工作区层 | 图表上下文与周期控制 | 股票识别、周期、前复权、股票资料、诊股、设置 |

## 65.7 Chart Workspace Toolbar 左侧股票识别区

### 65.7.1 内容

展示：

```text
福斯特 603806.SH 光伏设备
乾坤行情 / 个股详情 / P0 Mock 行情
```

说明：

- 第一行或主区域用于股票名称、代码、行业 / 板块短标签。
- 第二行说明若空间不足可隐藏或压缩为 Tooltip，不得撑高 toolbar。
- 不展示大号最新价 / 涨跌幅。
- 最新价 / 涨跌幅归右侧 `StockHeader`。

### 65.7.2 Token

```css
:root {
  --sd-chart-toolbar-stock-name-size: var(--cs-font-size-13);
  --sd-chart-toolbar-stock-name-weight: var(--cs-font-weight-semibold);
  --sd-chart-toolbar-stock-name-color: var(--cs-color-text-primary);
  --sd-chart-toolbar-stock-code-size: var(--cs-font-size-12);
  --sd-chart-toolbar-stock-code-color: var(--cs-color-text-muted);
  --sd-chart-toolbar-stock-tag-h: 20px;
  --sd-chart-toolbar-stock-tag-padding-x: 7px;
  --sd-chart-toolbar-stock-tag-bg: rgba(148, 163, 184, 0.10);
  --sd-chart-toolbar-stock-tag-color: var(--cs-color-text-secondary);
  --sd-chart-toolbar-subtitle-size: var(--cs-font-size-11);
  --sd-chart-toolbar-subtitle-color: var(--cs-color-text-weak);
}
```

### 65.7.3 规则

1. 股票识别区只做轻量识别。
2. 不承载价格主视觉。
3. 不与右侧 `StockHeader` 竞争视觉权重。
4. 不导致 toolbar 高度超过 `--sd-chart-workspace-toolbar-h`。

## 65.8 Chart Workspace Toolbar 中间周期切换区

### 65.8.1 周期集合保持不变

周期按钮集合本身不在本轮修改范围内，仍展示：

```text
分时 / 日K / 周K / 月K / 120分 / 90分 / 60分 / 30分 / 15分 / 5分 / 1分
```

默认选中：

```text
日K
```

### 65.8.2 Token

```css
:root {
  --sd-period-switch-height: 26px;
  --sd-period-switch-item-padding-x: 8px;
  --sd-period-switch-item-radius: var(--cs-radius-md);
  --sd-period-switch-item-font-size: var(--cs-font-size-12);
  --sd-period-switch-item-color: var(--cs-color-text-secondary);
  --sd-period-switch-item-hover-bg: var(--cs-color-surface-card-hover);
  --sd-period-switch-item-hover-color: var(--cs-color-text-primary);
  --sd-period-switch-item-active-bg: var(--cs-color-brand-accent-bg);
  --sd-period-switch-item-active-color: var(--cs-color-brand-accent);
  --sd-period-switch-item-active-border: var(--cs-color-brand-accent-border);
}
```

### 65.8.3 规则

1. 不修改周期按钮集合本身。
2. 只明确其位于 Chart Workspace Toolbar 中间。
3. 周期按钮不使用红绿表达选中。
4. 选中态使用品牌金。
5. 空间不足时可横向滚动或压缩 gap，但不得换两行撑高 toolbar。

## 65.9 Chart Workspace Toolbar 右侧操作区

### 65.9.1 内容

右侧操作区包含：

```text
前复权 / 股票资料 / 诊股 / 设置
```

### 65.9.2 操作区 Token

```css
:root {
  --sd-chart-action-button-h: 26px;
  --sd-chart-action-button-padding-x: 9px;
  --sd-chart-action-button-radius: var(--cs-radius-md);
  --sd-chart-action-button-font-size: var(--cs-font-size-12);
  --sd-chart-action-button-bg: rgba(148, 163, 184, 0.08);
  --sd-chart-action-button-border: 1px solid var(--cs-color-border-subtle);
  --sd-chart-action-button-color: var(--cs-color-text-secondary);
  --sd-chart-action-button-hover-bg: var(--cs-color-surface-card-hover);
  --sd-chart-action-button-hover-border: 1px solid var(--cs-color-border-hover);
  --sd-chart-action-button-hover-color: var(--cs-color-text-primary);
  --sd-chart-action-button-active-bg: var(--cs-color-brand-accent-bg);
  --sd-chart-action-button-active-border: 1px solid var(--cs-color-brand-accent-border);
  --sd-chart-action-button-active-color: var(--cs-color-brand-accent);

  --sd-chart-action-button-disabled-bg: rgba(100, 116, 139, 0.06);
  --sd-chart-action-button-disabled-border: 1px solid rgba(148, 163, 184, 0.10);
  --sd-chart-action-button-disabled-color: var(--cs-color-text-weak);
  --sd-chart-action-button-disabled-opacity: 0.58;
  --sd-chart-action-button-gap: 6px;
}
```

### 65.9.3 前复权按钮

规则：

1. 前复权从 Breadcrumb / 独立控制行下移到 Chart Workspace Toolbar 右侧。
2. 显示为紧凑选择按钮。
3. 可带下拉箭头。
4. hover 使用中性提亮。
5. active / selected 使用品牌金弱背景。
6. 不使用红绿。

推荐文案：

```text
前复权 ▾
```

### 65.9.4 股票资料按钮

规则：

1. 常规可点击按钮。
2. 点击进入完整股票资料页。
3. hover 使用中性提亮。
4. active 使用品牌金弱背景。
5. 不承载“资料 Tab 暂未开通”的含义。

推荐文案：

```text
股票资料
```

### 65.9.5 诊股 disabled

业务规则保持不变：诊股 P0 disabled。

视觉规则：

1. 使用 disabled 背景。
2. 使用弱文字。
3. opacity 约 0.58。
4. cursor 使用 `not-allowed` 或 `default`。
5. 不出现 hover 高亮。
6. 不展示诊股结论。

推荐文案：

```text
诊股
```

### 65.9.6 设置按钮

规则：

1. 作为图表 / 指标设置入口。
2. P0 可点击后 Toast：`指标设置暂未开通`。
3. 图标按钮或文字按钮均可。
4. hover 使用中性提亮。
5. 不使用红绿。
6. 不修改 MA / BOLL 切换逻辑。

推荐文案：

```text
设置
```

或图标：

```text
⚙
```

## 65.10 明确删除项

以下元素不再出现在个股详情页顶部结构中：

```text
更新时间
刷新
READY
绿色框独立控制行
图表区顶部右上额外价格/涨幅块
```

### 65.10.1 更新时间

不再在 Breadcrumb、Chart Workspace Toolbar、右侧操作区单独展示：

```text
更新时间 14:59:56
```

如需全局数据时间，优先依赖 `TopMarketBar` 全局数据状态。

### 65.10.2 刷新

不再在个股详情页顶部单独展示刷新按钮。

如后续需要局部刷新，应另行设计，不属于本轮范围。

### 65.10.3 READY

不再展示独立 `READY` 文案或 Badge。

如需数据状态，优先复用 `TopMarketBar` 的全局数据状态表达。

### 65.10.4 图表区顶部右上额外价格 / 涨幅块

不允许在图表区顶部右上角单独新增：

```text
大号最新价
涨跌额
涨跌幅
价格涨幅浮块
```

个股价格信息应归位到：

```text
右侧 StockHeader / 行情信息区
```

## 65.11 与固定视口布局的关系

本轮修改必须继续遵守个股详情页固定视口规则：

```css
.stock-detail-page {
  height: 100vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
```

主内容区高度：

```css
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

注意：

1. 删除绿色框独立行后，不得把该行高度继续计入主内容区扣减。
2. `--sd-breadcrumb-action-bar-h` 仅代表轻量 Breadcrumb 路径行高度。
3. `--sd-chart-toolbar-h` 对应 Chart Workspace Toolbar 高度。
4. 不写死 `1080px`。
5. 不通过 body 级滚动解决顶部过高问题。

# 66. 本轮 Review v2 修改摘要

1. 个股详情页最顶部完全复用市场总览同款 `TopMarketBar`。
2. 本轮所说 Header 只指 `TopMarketBar`，不包括 Breadcrumb、PageHeader、BreadcrumbActionBar、Chart Workspace Toolbar。
3. 禁止为个股详情页单独设计另一套顶部全局栏。
4. 禁止在 TopMarketBar 中加入个股专属信息。
5. Breadcrumb 行只保留路径：`财势乾坤 / 乾坤行情 / 个股详情 / 福斯特 603806.SH`。
6. Breadcrumb 行不承载前复权、更新时间、刷新、READY 或图表控制职责。
7. 删除绿色框独立控制 / 占位行，不保留同等高度空白。
8. `Chart Workspace Toolbar` 紧接 Breadcrumb 下方。
9. `Chart Workspace Toolbar` 承载股票识别区、周期切换区、右侧操作区。
10. `前复权` 下移到 Chart Workspace Toolbar 右侧操作区。
11. 删除顶部结构中的 `更新时间 / 刷新 / READY`。
12. 删除图表区顶部右上额外价格 / 涨幅块，如仍存在。
13. 不修改 K 线主图、指标副图、坐标轴、十字线、Tooltip、Header Info、右侧信息栏或红涨绿跌规则。

# 67. 本轮未修改区域说明

本轮未修改：

1. K 线主图；
2. MACD；
3. 成交量；
4. KDJ；
5. 坐标轴刻度；
6. 时间轴刻度；
7. 十字坐标线；
8. Tooltip；
9. Header Info 条；
10. MA / BOLL 切换；
11. 右侧 StockHeader；
12. 盘口 / 资料 Tab；
13. 关联板块表；
14. 个股资金统计图；
15. 周期按钮集合本身；
16. 资料 Tab 暂未开通；
17. 诊股 disabled 业务规则；
18. 红涨绿跌规则；
19. API 字段和数据字典；
20. 市场总览页面及其它页面视觉规则。

```text
本轮因 Review v2 修改而被动影响的区域：
- 个股详情页顶部垂直节奏
原因：删除绿色框独立控制 / 占位行，并将 Chart Workspace Toolbar 紧接 Breadcrumb 下方
是否需要产品总控确认：否，Review v2 已明确
```

# 68. 本轮新增或修订 Token 清单

| Token | 类型 | 用途 |
|---|---|---|
| `--sd-breadcrumb-row-h` | 新增 | 个股详情 Breadcrumb 轻量路径行高度 |
| `--sd-breadcrumb-row-padding-x` | 新增 | Breadcrumb 轻量路径行横向内边距 |
| `--sd-breadcrumb-row-bg` | 新增 | Breadcrumb 轻量路径行背景 |
| `--sd-breadcrumb-row-border` | 新增 | Breadcrumb 轻量路径行底部分割线 |
| `--sd-breadcrumb-font-size` | 新增 | Breadcrumb 文本字号 |
| `--sd-breadcrumb-text-color` | 新增 | Breadcrumb 默认文字色 |
| `--sd-breadcrumb-current-color` | 新增 | Breadcrumb 当前项文字色 |
| `--sd-breadcrumb-separator-color` | 新增 | Breadcrumb 分隔符颜色 |
| `--sd-removed-control-row-h` | 新增 | 已删除独立控制行高度，必须为 `0px` |
| `--sd-top-stack-extra-gap` | 新增 | 顶部额外间距，必须为 `0px` |
| `--sd-chart-workspace-toolbar-h` | 新增/修订 | Chart Workspace Toolbar 高度 |
| `--sd-chart-workspace-toolbar-bg` | 新增 | Chart Workspace Toolbar 背景 |
| `--sd-chart-workspace-toolbar-border-bottom` | 新增 | Chart Workspace Toolbar 底部分割线 |
| `--sd-chart-workspace-toolbar-padding-x` | 新增 | Toolbar 横向内边距 |
| `--sd-chart-workspace-toolbar-gap` | 新增 | 股票识别区、周期区、操作区间距 |
| `--sd-chart-workspace-stock-id-min-w` | 新增 | 股票识别区最小宽度 |
| `--sd-chart-workspace-period-gap` | 新增 | 周期按钮间距 |
| `--sd-chart-workspace-actions-gap` | 新增 | 右侧操作按钮间距 |
| `--sd-chart-workspace-control-h` | 新增 | Toolbar 控件高度 |
| `--sd-chart-workspace-control-padding-x` | 新增 | Toolbar 控件横向内边距 |
| `--sd-chart-workspace-control-radius` | 新增 | Toolbar 控件圆角 |
| `--sd-chart-workspace-control-font-size` | 新增 | Toolbar 控件字号 |
| `--sd-chart-toolbar-stock-name-size` | 新增 | Toolbar 股票名称字号 |
| `--sd-chart-toolbar-stock-name-weight` | 新增 | Toolbar 股票名称字重 |
| `--sd-chart-toolbar-stock-code-size` | 新增 | Toolbar 股票代码字号 |
| `--sd-chart-toolbar-stock-tag-*` | 新增 | Toolbar 股票标签样式 |
| `--sd-period-switch-*` | 修订 | 周期切换在 Chart Workspace Toolbar 中的样式 |
| `--sd-chart-action-button-*` | 新增 | 前复权、股票资料、诊股、设置按钮样式 |

# 69. 对 03 `04-component-guidelines.md` 的 Token 映射建议

建议 03 修订以下组件 / 组件关系：

| 组件 | 处理建议 | Token / 规则 |
|---|---|---|
| `TopMarketBar` | 直接复用市场总览全局组件 | 不新增个股详情专属 Header Token |
| `StockDetailPage` | 固定视口页面壳 | `--sd-top-market-bar-h`、`--sd-breadcrumb-action-bar-h`、`--sd-chart-toolbar-h` |
| `StockDetailFixedLayout` | 页面高度计算容器 | `height: 100vh`、`overflow: hidden`、`min-height: 0` |
| `StockBreadcrumb` | 轻量路径行 | `--sd-breadcrumb-*` |
| `ChartWorkspaceToolbar` | 图表工作区顶部唯一控制栏 | `--sd-chart-workspace-*`、`--sd-chart-action-button-*` |
| `StockChartToolbar` | 如已有，建议合并或重命名为 `ChartWorkspaceToolbar` | 避免与全局 Header 混淆 |
| `AdjustTypeSelect` | 前复权按钮 / 下拉 | `--sd-chart-action-button-*` |
| `StockProfileButton` | 股票资料按钮 | `--sd-chart-action-button-*` |
| `DiagnosisButton` | 诊股 disabled | `--sd-chart-action-button-disabled-*` |
| `ChartSettingButton` | 设置按钮 | `--sd-chart-action-button-*` |

组件规则：

1. 不得定义 `StockDetailHeader`、`StockGlobalHeader` 等个股详情专属顶部全局栏。
2. `TopMarketBar` 必须作为全局组件直接复用。
3. `Breadcrumb` 只显示路径。
4. `ChartWorkspaceToolbar` 承载图表上下文、周期和操作按钮。
5. 删除更新时间、刷新、READY。
6. 不新增 API 字段。

# 70. 对 02 `stock-detail-v1.2.html` 的视觉约束

1. 最顶部必须完全复用市场总览同款 `TopMarketBar`。
2. 不允许个股详情页另做一套顶部全局栏。
3. 不允许在 TopMarketBar 中加入个股名称、代码、最新价、涨跌幅、前复权等个股专属信息。
4. Breadcrumb 行只显示路径：`财势乾坤 / 乾坤行情 / 个股详情 / 福斯特 603806.SH`。
5. Breadcrumb 行不得显示前复权、更新时间、刷新、READY。
6. 删除绿色框独立控制 / 占位行。
7. 删除后不得保留同等高度空白。
8. `Chart Workspace Toolbar` 必须紧接 Breadcrumb 下方。
9. `Chart Workspace Toolbar` 左侧为股票识别区。
10. `Chart Workspace Toolbar` 中间为周期切换区。
11. `Chart Workspace Toolbar` 右侧为 `前复权 / 股票资料 / 诊股 / 设置`。
12. `前复权` 必须下移到 Chart Workspace Toolbar 右侧。
13. `诊股` 必须保持 P0 disabled。
14. `股票资料` 为可点击入口。
15. `设置` 可点击后 Toast，或保持轻量入口。
16. 删除顶部结构中的 `更新时间`。
17. 删除顶部结构中的 `刷新`。
18. 删除顶部结构中的 `READY`。
19. 删除图表区顶部右上额外价格 / 涨幅块，如仍存在。
20. 个股最新价 / 涨跌额 / 涨跌幅归位到右侧 `StockHeader / 行情信息区`。
21. 不修改 K 线主图、MACD、成交量、KDJ、坐标轴、时间轴、十字坐标线、Tooltip、Header Info、右侧 StockHeader、盘口/资料 Tab、关联板块、个股资金统计、资料 Tab、诊股 disabled 业务规则和红涨绿跌规则。
22. 继续保持固定视口 `100vh`，禁止 body 级整页滚动。

# 71. 待产品总控确认问题

1. `Chart Workspace Toolbar` 高度是否接受 `38px`，当前建议该高度以兼顾周期按钮和操作区。
2. Breadcrumb 轻量路径行高度是否接受 `30px`，当前建议较低高度以释放图表区域。
3. `Chart Workspace Toolbar` 左侧股票识别区是否展示第二行 `乾坤行情 / 个股详情 / P0 Mock 行情`，还是只展示 `福斯特 603806.SH 光伏设备`。
4. 设置按钮点击后是否继续沿用既有 Toast：`指标设置暂未开通`。
5. 股票资料按钮的目标路由是否已确定，当前只定义视觉，不定义 API 或路由。
6. 删除个股详情页单独刷新后，是否完全依赖 TopMarketBar 的全局数据状态，当前按 Review v2 执行。

# 72. 本轮输出文件下载链接

本轮输出文件名：

```text
03-design-tokens.md
```

下载链接由本轮对话附件提供。

建议放置到 Google Drive：

```text
财势乾坤/设计/03-design-tokens.md
```

---

# 73. 个股详情页顶部工具栏与右侧头部紧凑规则（Stock Detail Review v3）

> 本节仅服务 `个股详情 / Chart Workspace Toolbar / 右侧 StockHeader / K 线默认视窗配置`。  
> 本节不修改 TopMarketBar、Breadcrumb 路径行、绿色框独立控制行删除规则、前复权位置、删除更新时间 / 刷新 / READY 规则，也不修改 K 线绘制风格、MACD、成交量、KDJ、坐标轴、时间轴、十字线、Tooltip、Header Info、MA/BOLL、盘口 / 资料 Tab、关联板块、资金统计、资料 Tab 暂未开通、诊股 disabled、红涨绿跌和固定视口 100vh 规则。

## 73.1 Review v3 设计边界

本轮只处理 3 个局部修正：

1. `Chart Workspace Toolbar` 中股票识别区与周期切换区距离收紧；
2. 右侧 `StockHeader` 进一步压缩，使按钮区、盘口摘要、关联板块与资金统计整体上移；
3. K 线默认视窗最多展示 144 根 K 线。

本轮不处理：

```text
鼠标右键拖拽
横向平移历史窗口
K 线缩放
鼠标滚轮缩放
历史窗口拖动
惯性滚动
API 字段变更
```

## 73.2 Chart Workspace Toolbar 紧凑布局目标

修改前不理想状态：

```text
股票识别区                                      周期切换区                    右侧操作区
```

修改后目标状态：

```text
福斯特 603806.SH  光伏设备 ｜ 周期  分时 日K 周K 月K 120分 90分 60分 30分 15分 5分 1分                前复权 股票资料 诊股 设置
```

核心规则：

1. 股票识别区与周期切换区必须靠近；
2. 二者之间只保留必要间距；
3. 不允许股票识别区和周期切换区之间出现大面积空白；
4. 右侧操作区仍靠右；
5. 周期按钮集合不变；
6. 周期切换区不应被挤到页面正中导致和股票识别区割裂；
7. 整体形成“股票上下文 + 周期切换 + 图表操作”的连续工具栏。

## 73.3 Chart Workspace Toolbar 紧凑 Token

```css
:root {
  /* Review v3: compact toolbar grouping */
  --sd-chart-workspace-toolbar-h-compact: 36px;
  --sd-chart-workspace-toolbar-padding-x-compact: 10px;
  --sd-chart-workspace-toolbar-padding-y-compact: 4px;

  /* 股票识别区与周期切换区的距离 */
  --sd-chart-toolbar-identity-period-gap: 14px;
  --sd-chart-toolbar-identity-period-gap-min: 10px;
  --sd-chart-toolbar-identity-period-gap-max: 18px;

  /* 股票识别区 */
  --sd-chart-toolbar-identity-width: auto;
  --sd-chart-toolbar-identity-min-w: 150px;
  --sd-chart-toolbar-identity-max-w: 230px;
  --sd-chart-toolbar-stock-name-size-compact: 13px;
  --sd-chart-toolbar-stock-code-size-compact: 12px;
  --sd-chart-toolbar-stock-tag-size-compact: 11px;
  --sd-chart-toolbar-stock-tag-gap-compact: 5px;

  /* 周期切换区 */
  --sd-period-switch-group-gap-compact: 3px;
  --sd-period-switch-item-h-compact: 24px;
  --sd-period-switch-item-padding-x-compact: 7px;
  --sd-period-switch-item-font-size-compact: 12px;
  --sd-period-switch-item-radius-compact: 5px;

  /* 周期区与右侧操作区分隔 */
  --sd-chart-toolbar-period-actions-min-gap: 16px;
  --sd-chart-toolbar-period-actions-divider-color: rgba(148, 163, 184, 0.14);
  --sd-chart-toolbar-period-actions-divider-h: 18px;

  /* 右侧操作区 */
  --sd-chart-workspace-actions-gap-compact: 6px;
  --sd-chart-action-button-h-compact: 24px;
  --sd-chart-action-button-padding-x-compact: 8px;
  --sd-chart-action-button-font-size-compact: 12px;
}
```

实现建议：

```css
.sd-chart-workspace-toolbar {
  height: var(--sd-chart-workspace-toolbar-h-compact);
  padding: var(--sd-chart-workspace-toolbar-padding-y-compact)
    var(--sd-chart-workspace-toolbar-padding-x-compact);
  display: flex;
  align-items: center;
  gap: 0;
}

.sd-chart-toolbar-left-group {
  display: inline-flex;
  align-items: center;
  gap: var(--sd-chart-toolbar-identity-period-gap);
  min-width: 0;
  flex: 0 1 auto;
}

.sd-stock-identity-inline {
  flex: 0 1 var(--sd-chart-toolbar-identity-width);
  min-width: var(--sd-chart-toolbar-identity-min-w);
  max-width: var(--sd-chart-toolbar-identity-max-w);
  overflow: hidden;
  white-space: nowrap;
}

.sd-period-switch-group {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  gap: var(--sd-period-switch-group-gap-compact);
  white-space: nowrap;
}

.sd-toolbar-actions {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: var(--sd-chart-workspace-actions-gap-compact);
  white-space: nowrap;
}
```

禁止实现方式：

```css
/* 禁止：会把股票识别区和周期切换区拉得过远 */
.sd-chart-workspace-toolbar {
  justify-content: space-between;
}

/* 禁止：周期区被推到页面中心，左侧出现大片空白 */
.sd-period-switch-group {
  margin-left: auto;
}
```

## 73.4 周期按钮单行紧凑规则

周期按钮集合保持不变：

```text
分时 / 日K / 周K / 月K / 120分 / 90分 / 60分 / 30分 / 15分 / 5分 / 1分
```

规则：

1. 周期按钮保持单行；
2. 不允许换行；
3. 不隐藏默认周期项；
4. 日 K 默认选中；
5. 按钮间距使用 `--sd-period-switch-group-gap-compact`；
6. 按钮高度使用 `--sd-period-switch-item-h-compact`；
7. 当前选中态仍明显，使用品牌金弱背景和品牌金文字；
8. hover 只做轻微提亮；
9. 禁用状态不影响其它按钮布局。

推荐 CSS：

```css
.sd-period-switch-item {
  height: var(--sd-period-switch-item-h-compact);
  padding: 0 var(--sd-period-switch-item-padding-x-compact);
  border-radius: var(--sd-period-switch-item-radius-compact);
  font-size: var(--sd-period-switch-item-font-size-compact);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--cs-color-text-secondary);
  background: transparent;
  border: 1px solid transparent;
}

.sd-period-switch-item:hover {
  color: var(--cs-color-text-primary);
  background: var(--cs-color-surface-card-hover);
}

.sd-period-switch-item.is-selected {
  color: var(--cs-color-brand-accent);
  background: var(--cs-color-brand-accent-bg);
  border-color: var(--cs-color-brand-accent-border);
}
```

## 73.5 周期区与右侧操作区分隔策略

右侧操作区仍靠右，但不能破坏左侧“股票上下文 + 周期切换”的连续性。

规则：

1. 右侧操作区使用 `margin-left: auto` 靠右；
2. 周期区与右侧操作区之间允许存在弹性空白；
3. 弹性空白只出现在周期区之后，不得出现在股票识别区与周期区之间；
4. 空间充足时，可在右侧操作区前加弱分割线；
5. 空间不足时，优先取消分割线，不隐藏周期按钮。

可选分割线：

```css
.sd-toolbar-actions::before {
  content: "";
  width: 1px;
  height: var(--sd-chart-toolbar-period-actions-divider-h);
  background: var(--sd-chart-toolbar-period-actions-divider-color);
  margin-right: var(--cs-space-6);
}
```

## 73.6 右侧 StockHeader 紧凑版目标

右侧 `StockHeader` 需要进一步压缩高度，使下方内容整体上移。

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

调整目标：

1. 减少无效留白；
2. 压缩内边距；
3. 压缩标题、价格、标签、按钮之间的行距；
4. 自选 / 提醒 / 交易计划 / 诊股按钮整体上移；
5. 盘口 / 资料 Tab、盘口摘要、关联板块、个股资金统计获得更多垂直空间；
6. 不重新设计右侧盘口 / 资料 Tab 内部结构。

## 73.7 右侧 StockHeader 紧凑 Token

```css
:root {
  /* Review v3: compact right StockHeader */
  --sd-right-stock-header-h-compact: 118px;
  --sd-right-stock-header-min-h-compact: 108px;
  --sd-right-stock-header-padding-x-compact: 12px;
  --sd-right-stock-header-padding-y-compact: 10px;
  --sd-right-stock-header-row-gap-compact: 6px;
  --sd-right-stock-header-section-gap-compact: 8px;

  /* title row */
  --sd-right-stock-name-size-compact: 16px;
  --sd-right-stock-name-weight-compact: var(--cs-font-weight-bold);
  --sd-right-stock-code-size-compact: 11px;
  --sd-right-stock-code-color-compact: var(--cs-color-text-muted);
  --sd-right-stock-tag-h-compact: 20px;
  --sd-right-stock-tag-padding-x-compact: 7px;
  --sd-right-stock-tag-font-size-compact: 11px;

  /* price row */
  --sd-right-stock-price-size-compact: 28px;
  --sd-right-stock-price-weight-compact: var(--cs-font-weight-bold);
  --sd-right-stock-change-size-compact: 13px;
  --sd-right-stock-change-weight-compact: var(--cs-font-weight-semibold);
  --sd-right-stock-price-change-gap-compact: 8px;

  /* action row */
  --sd-right-stock-actions-h-compact: 26px;
  --sd-right-stock-actions-gap-compact: 6px;
  --sd-right-stock-action-button-h-compact: 24px;
  --sd-right-stock-action-button-padding-x-compact: 8px;
  --sd-right-stock-action-button-font-size-compact: 12px;
  --sd-right-stock-action-button-radius-compact: var(--cs-radius-md);

  /* panel continuation */
  --sd-right-stock-header-to-tabs-gap: 8px;
}
```

推荐 CSS：

```css
.sd-right-stock-header {
  min-height: var(--sd-right-stock-header-min-h-compact);
  padding: var(--sd-right-stock-header-padding-y-compact)
    var(--sd-right-stock-header-padding-x-compact);
  display: flex;
  flex-direction: column;
  gap: var(--sd-right-stock-header-row-gap-compact);
}

.sd-right-stock-title-row {
  display: flex;
  align-items: center;
  gap: var(--cs-space-6);
  min-height: 22px;
}

.sd-right-stock-price-row {
  display: flex;
  align-items: baseline;
  gap: var(--sd-right-stock-price-change-gap-compact);
  min-height: 32px;
}

.sd-right-stock-action-row {
  height: var(--sd-right-stock-actions-h-compact);
  display: flex;
  align-items: center;
  gap: var(--sd-right-stock-actions-gap-compact);
  margin-top: 0;
}
```

## 73.8 右侧 StockHeader 字段视觉层级

| 字段 | 视觉层级 | 建议规则 |
|---|---|---|
| 股票名称 | 最高识别权重 | 16px / bold，主文字 |
| 股票代码 | 次级识别 | 11px，中性弱文字，紧随名称或下一小段 |
| 行业 / 题材标签 | 辅助识别 | 20px 高胶囊，弱背景，中性色或品牌金弱强调 |
| 最新价 | 最高行情数字 | 28px / bold，按涨跌方向红 / 绿 / 灰显示 |
| 涨跌额 | 行情变化 | 13px / semibold，红涨绿跌 |
| 涨跌幅 | 行情变化 | 13px / semibold，红涨绿跌 |
| 自选 / 提醒 / 交易计划 | 操作按钮 | 24px 高，紧凑按钮 |
| 诊股 | disabled 操作 | 24px 高，禁用态，不显示主观诊股结论 |

说明：

1. 最新价、涨跌额、涨跌幅继续遵守红涨绿跌；
2. 行业 / 题材标签不使用红绿涨跌色；
3. 诊股按钮保持 disabled，不展示诊股结论；
4. 不改变右侧 StockHeader 的字段集合，只改变密度。

## 73.9 自选 / 提醒 / 交易计划 / 诊股按钮上移规则

按钮区上移来自 StockHeader 压缩，不通过负 margin 或覆盖布局实现。

规则：

1. 压缩 `StockHeader` 内部 padding；
2. 压缩价格行和标签行间距；
3. 按钮区紧跟价格 / 标签信息；
4. 按钮区与 `盘口 / 资料 Tab` 间距使用 `--sd-right-stock-header-to-tabs-gap`；
5. 禁止用 `position: absolute` 强行贴顶；
6. 禁止通过覆盖盘口区域的方式换取上移效果。

按钮建议：

```css
.sd-right-stock-action-button {
  height: var(--sd-right-stock-action-button-h-compact);
  padding: 0 var(--sd-right-stock-action-button-padding-x-compact);
  border-radius: var(--sd-right-stock-action-button-radius-compact);
  font-size: var(--sd-right-stock-action-button-font-size-compact);
  border: 1px solid var(--cs-color-border-subtle);
  background: var(--cs-color-surface-card);
  color: var(--cs-color-text-secondary);
}

.sd-right-stock-action-button:hover:not(.is-disabled) {
  background: var(--cs-color-surface-card-hover);
  border-color: var(--cs-color-border-hover);
  color: var(--cs-color-text-primary);
}

.sd-right-stock-action-button.is-disabled {
  opacity: var(--cs-state-opacity-disabled);
  cursor: not-allowed;
}
```

## 73.10 K 线默认 144 根视窗规则

### 73.10.1 默认配置

```ts
interface KlineViewportState {
  defaultVisibleCount: 144;
  maxInitialVisibleCount: 144;
  anchor: 'latest';
}
```

规则：

1. `defaultVisibleCount = 144`；
2. `144` 是图表默认视窗配置；
3. 不新增强视觉元素；
4. 不改变 K 线绘制风格；
5. 默认锚定最新 K 线；
6. 数据不足 144 根时展示已有全部；
7. 该规则适用于所有周期。

### 73.10.2 周期适用范围

```text
分时 / 1分 / 5分 / 15分 / 30分 / 60分 / 90分 / 120分 / 日K / 周K / 月K
```

示例：

```text
日K：默认展示最近 144 根日 K
周K：默认展示最近 144 根周 K
月K：默认展示最近 144 根月 K
60分：默认展示最近 144 根 60 分钟 K
5分：默认展示最近 144 根 5 分钟 K
1分：默认展示最近 144 根 1 分钟 K
```

### 73.10.3 禁止事项

本轮不实现：

1. 鼠标右键拖拽；
2. 横向平移历史窗口；
3. K 线缩放；
4. 鼠标滚轮缩放；
5. 历史窗口拖动；
6. 惯性滚动；
7. 未来数据边界处理。

说明：

```text
144 根规则是默认视窗，不是数据接口 limit，也不是 API 字段变更。
```

# 74. 本轮 Review v3 修改摘要

1. 仅修订个股详情页 `Chart Workspace Toolbar` 内部横向间距、右侧 `StockHeader` 紧凑版、K 线默认视窗数量。
2. 股票识别区与周期切换区距离收紧。
3. 不允许股票识别区与周期切换区之间出现大面积空白。
4. 周期切换区保持单行紧凑展示，不换行，不隐藏默认周期项。
5. 右侧操作区仍靠右。
6. 右侧 StockHeader 进一步压缩高度、内边距和行距。
7. 自选 / 提醒 / 交易计划 / 诊股按钮整体上移。
8. 盘口 / 资料 Tab、盘口摘要、关联板块、个股资金统计获得更多垂直空间。
9. K 线默认视窗最多展示 144 根当前周期 K 线。
10. 数据不足 144 根时展示已有全部。
11. 默认视窗锚定最新 K 线。
12. 本轮不实现右键拖拽、历史窗口平移、缩放等交互。
13. 本轮不修改未点名区域。

# 75. 本轮未修改区域说明

本轮未修改：

1. TopMarketBar；
2. Breadcrumb 路径行；
3. 已删除绿色框独立控制行的规则；
4. 前复权在 Chart Workspace Toolbar 右侧的规则；
5. 删除更新时间 / 刷新 / READY 的规则；
6. K 线主图绘制风格；
7. MACD；
8. 成交量；
9. KDJ；
10. 坐标轴常驻刻度规则；
11. 时间轴刻度规则；
12. 十字线；
13. Tooltip；
14. Header Info；
15. MA / BOLL 切换；
16. 齿轮 Toast；
17. 盘口 / 资料 Tab；
18. 关联板块；
19. 资金统计；
20. 资料 Tab 暂未开通；
21. 诊股 disabled；
22. 红涨绿跌规则；
23. 固定视口 100vh 布局规则；
24. API 字段和数据字典；
25. 市场总览页面与其它页面视觉规则。

```text
本轮因 Review v3 修改而被动影响的区域：
- 个股详情页右侧栏垂直可用空间
原因：右侧 StockHeader 压缩后，下方按钮、Tab、盘口摘要、关联板块和资金统计整体上移
是否需要产品总控确认：否，Review v3 已明确
```

# 76. 本轮新增或修订 Token 清单

| Token | 类型 | 用途 |
|---|---|---|
| `--sd-chart-workspace-toolbar-h-compact` | 新增/修订 | Chart Workspace Toolbar 紧凑高度 |
| `--sd-chart-workspace-toolbar-padding-x-compact` | 新增 | Toolbar 紧凑横向内边距 |
| `--sd-chart-workspace-toolbar-padding-y-compact` | 新增 | Toolbar 紧凑纵向内边距 |
| `--sd-chart-toolbar-identity-period-gap` | 新增 | 股票识别区与周期切换区推荐间距 |
| `--sd-chart-toolbar-identity-period-gap-min` | 新增 | 股票识别区与周期切换区最小间距 |
| `--sd-chart-toolbar-identity-period-gap-max` | 新增 | 股票识别区与周期切换区最大建议间距 |
| `--sd-chart-toolbar-identity-min-w` | 新增 | 股票识别区最小宽度 |
| `--sd-chart-toolbar-identity-max-w` | 新增 | 股票识别区最大宽度，避免撑开工具栏 |
| `--sd-period-switch-group-gap-compact` | 新增/修订 | 周期按钮紧凑间距 |
| `--sd-period-switch-item-h-compact` | 新增/修订 | 周期按钮紧凑高度 |
| `--sd-period-switch-item-padding-x-compact` | 新增/修订 | 周期按钮紧凑内边距 |
| `--sd-chart-toolbar-period-actions-min-gap` | 新增 | 周期区与右侧操作区最小分隔距离 |
| `--sd-chart-workspace-actions-gap-compact` | 新增/修订 | 右侧操作按钮紧凑间距 |
| `--sd-chart-action-button-h-compact` | 新增/修订 | 右侧操作按钮紧凑高度 |
| `--sd-right-stock-header-h-compact` | 新增/修订 | 右侧 StockHeader 紧凑高度 |
| `--sd-right-stock-header-min-h-compact` | 新增 | 右侧 StockHeader 紧凑最小高度 |
| `--sd-right-stock-header-padding-x-compact` | 新增/修订 | 右侧 StockHeader 横向内边距 |
| `--sd-right-stock-header-padding-y-compact` | 新增/修订 | 右侧 StockHeader 纵向内边距 |
| `--sd-right-stock-header-row-gap-compact` | 新增/修订 | 右侧 StockHeader 行距 |
| `--sd-right-stock-header-section-gap-compact` | 新增 | 右侧 StockHeader 区块间距 |
| `--sd-right-stock-name-size-compact` | 新增/修订 | 右侧股票名称字号 |
| `--sd-right-stock-price-size-compact` | 新增/修订 | 右侧最新价字号 |
| `--sd-right-stock-actions-h-compact` | 新增/修订 | 右侧按钮区高度 |
| `--sd-right-stock-actions-gap-compact` | 新增/修订 | 右侧按钮间距 |
| `--sd-right-stock-header-to-tabs-gap` | 新增 | StockHeader 与盘口/资料 Tab 间距 |
| `KlineViewportState.defaultVisibleCount` | 新增配置 | 默认最多展示 144 根 K 线 |
| `KlineViewportState.maxInitialVisibleCount` | 新增配置 | 初始最大展示 144 根 |
| `KlineViewportState.anchor` | 新增配置 | 默认锚定最新 K 线 |

# 77. 对 03 `04-component-guidelines.md` 的 Token 映射建议

建议 03 修订以下组件 / 配置：

| 组件 / 配置 | 处理建议 | Token / 规则 |
|---|---|---|
| `ChartWorkspaceToolbar` | 改为更紧凑的横向布局 | `--sd-chart-workspace-toolbar-h-compact`、`--sd-chart-toolbar-identity-period-gap` |
| `StockIdentityInline` | 与周期切换区紧邻 | `--sd-chart-toolbar-identity-*` |
| `PeriodSwitchGroup` | 单行紧凑展示 | `--sd-period-switch-*-compact` |
| `StockToolbarActions` | 保持靠右 | `--sd-chart-workspace-actions-gap-compact`、`--sd-chart-action-button-h-compact` |
| `StockHeaderPanel` | 使用紧凑版 | `--sd-right-stock-header-*` |
| `StockActionButtonGroup` | 上移并保持紧凑 | `--sd-right-stock-actions-*` |
| `StockKlinePanel` | 默认视窗 144 根 | `KlineViewportState.defaultVisibleCount = 144` |
| `KlineViewportState` | 新增默认视窗配置 | `defaultVisibleCount`、`maxInitialVisibleCount`、`anchor` |

组件实现约束：

1. `ChartWorkspaceToolbar` 中 `StockIdentityInline` 与 `PeriodSwitchGroup` 应相邻；
2. 不允许通过 `justify-content: space-between` 把股票识别区和周期切换区拉得过远；
3. 右侧操作区可以靠右；
4. `PeriodSwitchGroup` 不换行、不隐藏默认周期项；
5. `StockHeaderPanel` 使用紧凑版布局；
6. `KlineViewportState.defaultVisibleCount = 144`；
7. 数据不足 144 根时展示全部；
8. 默认锚定最新 K 线；
9. 本轮不实现右键拖拽和平移；
10. 本轮不改 API。

# 78. 对 02 `stock-detail-v1.3.html` 的视觉约束

1. 收紧 `Chart Workspace Toolbar` 中股票识别区与周期切换区的距离。
2. 保证股票识别区与周期切换区视觉上连续。
3. 不允许股票识别区与周期切换区之间出现大面积空白。
4. 右侧操作区仍靠右。
5. 周期按钮集合保持不变。
6. 周期按钮必须单行展示，不换行。
7. 周期按钮不得隐藏默认周期项。
8. 默认选中日 K。
9. 压缩右侧 `StockHeader` 高度、内边距、行距。
10. 保留股票名称、股票代码、行业/题材标签、最新价、涨跌额、涨跌幅。
11. 自选 / 提醒 / 交易计划 / 诊股按钮整体上移。
12. 盘口 / 资料 Tab、盘口摘要、关联板块、个股资金统计获得更多垂直空间。
13. K 线默认最多展示 144 根当前周期 K 线。
14. 默认视窗锚定最新 K 线。
15. 数据不足 144 根时展示已有全部。
16. 不实现右键拖拽。
17. 不实现横向平移历史窗口。
18. 不实现 K 线缩放或鼠标滚轮缩放。
19. 不修改 TopMarketBar、Breadcrumb、已删除绿色框独立控制行、前复权位置、删除更新时间 / 刷新 / READY 规则。
20. 不修改 K 线主图绘制风格、MACD、成交量、KDJ、坐标轴、时间轴、十字线、Tooltip、Header Info、MA/BOLL、齿轮 Toast、盘口 / 资料 Tab、关联板块、资金统计、诊股 disabled、资料 Tab 暂未开通、红涨绿跌、固定视口 100vh。

# 79. 待产品总控确认问题

1. 右侧 `StockHeader` 紧凑高度是否接受 `118px`，极限情况下是否允许压缩到 `108px`。
2. 股票识别区与周期切换区推荐间距 `14px` 是否符合视觉预期，最小 `10px` 是否可接受。
3. 周期按钮紧凑高度 `24px` 是否足够可点击，还是需要保留 `26px`。
4. 右侧操作区前是否需要弱分割线，当前建议可选，空间不足时取消。
5. `defaultVisibleCount = 144` 是否作为所有周期长期默认值，后续是否需要用户配置。
6. 数据不足 144 根时展示全部是否接受，当前建议接受。
7. 右键拖拽 / 横向平移 / 缩放是否进入下一轮独立 Review。

# 80. 本轮输出文件下载链接

本轮输出文件名：

```text
03-design-tokens.md
```

下载链接由本轮对话附件提供。

建议放置到 Google Drive：

```text
财势乾坤/设计/03-design-tokens.md
```


---

# 81. 个股详情 / 右侧信息栏 / StockHeader 红框 3 视觉规则（Review v4）

> 本节为 `stock-detail-html-review-v4-总控解读与变更单.md` 对 Design Token 的补充。  
> 只约束 `个股详情页 / 右侧信息栏 / StockHeader 红框 3`。  
> 不修改 TopMarketBar、Breadcrumb、Chart Workspace Toolbar、周期切换区、前复权按钮、股票资料按钮、顶部诊股按钮、设置按钮、K 线主图、MACD、成交量、KDJ、坐标轴刻度、时间轴刻度、Header Info、MA/BOLL、十字线、Tooltip、盘口/资料 Tab、关联板块表、个股资金统计、资料 Tab 暂未开通、默认 144 根 K 线、固定视口 100vh、API 字段和红涨绿跌规则。

## 81.1 本轮修订边界

本轮只处理右侧信息栏顶部的 `StockHeader 红框 3`：

1. `StockHeader` 左右两列布局；
2. `StockHeaderSummaryRow`；
3. 左侧股票识别信息组；
4. 右侧行情价格信息组；
5. 下方 `+自选 / +提醒 / +交易计划` 操作区；
6. 删除右侧 `StockHeader` 中的 `诊股` 后的操作区间距；
7. `StockHeader` 压缩后下方模块整体上移的垂直节奏。

本节不得被解释为完整重做右侧信息栏。

## 81.2 StockHeader 红框 3 结构总览

右侧 `StockHeader` 顶部区域必须是一个整体小板块，内部采用左右两列：

```text
┌────────────────────────────────────────────┐
│ 左侧股票识别组                     右侧价格组 │
│ 股票名称 + 行业题材标签              最新股价 │
│ 股票代码                         涨跌额 + 涨跌幅 │
└────────────────────────────────────────────┘
+自选 / +提醒 / +交易计划
```

示例：

```text
福斯特  光伏设备 / 新材料              18.36
603806.SH                         +0.35  +1.94%
+自选 / +提醒 / +交易计划
```

结构要求：

1. 左侧信息组靠左；
2. 右侧价格组靠右；
3. 左右两组作为整体在垂直方向上居中对齐；
4. 不允许上下堆成高大的详情页 Header；
5. 不允许出现大面积留白；
6. 下方操作区紧接 StockHeaderSummaryRow；
7. 右侧 StockHeader 操作区不再展示 `诊股`。

## 81.3 StockHeader 红框 3 Token

```css
:root {
  /* Stock detail right StockHeader - Review v4 */
  --sd-stock-header-compact-h: 76px;
  --sd-stock-header-compact-min-h: 68px;
  --sd-stock-header-compact-padding-x: 10px;
  --sd-stock-header-compact-padding-y: 8px;
  --sd-stock-header-compact-radius: var(--cs-radius-card);
  --sd-stock-header-compact-bg: var(--cs-color-surface-card);
  --sd-stock-header-compact-border: 1px solid var(--cs-color-border-subtle);

  /* Summary row */
  --sd-stock-header-summary-row-h: 42px;
  --sd-stock-header-summary-column-gap: 10px;
  --sd-stock-header-summary-align: center;
  --sd-stock-header-left-min-w: 0;
  --sd-stock-header-right-min-w: 104px;

  /* Left identity group */
  --sd-stock-header-name-size: var(--cs-font-size-15);
  --sd-stock-header-name-weight: var(--cs-font-weight-semibold);
  --sd-stock-header-name-color: var(--cs-color-text-primary);
  --sd-stock-header-tag-h: 18px;
  --sd-stock-header-tag-padding-x: 6px;
  --sd-stock-header-tag-radius: var(--cs-radius-pill);
  --sd-stock-header-tag-font-size: var(--cs-font-size-10);
  --sd-stock-header-tag-bg: rgba(148, 163, 184, 0.10);
  --sd-stock-header-tag-border: rgba(148, 163, 184, 0.16);
  --sd-stock-header-tag-color: var(--cs-color-text-secondary);
  --sd-stock-header-code-size: var(--cs-font-size-11);
  --sd-stock-header-code-weight: var(--cs-font-weight-medium);
  --sd-stock-header-code-color: var(--cs-color-text-muted);
  --sd-stock-header-left-line-gap: 5px;
  --sd-stock-header-name-tag-gap: 6px;

  /* Right price group */
  --sd-stock-header-price-size: var(--cs-font-size-22);
  --sd-stock-header-price-weight: var(--cs-font-weight-bold);
  --sd-stock-header-price-line-height: 1.05;
  --sd-stock-header-change-size: var(--cs-font-size-12);
  --sd-stock-header-change-weight: var(--cs-font-weight-semibold);
  --sd-stock-header-change-gap: 6px;
  --sd-stock-header-right-line-gap: 5px;

  /* Action links */
  --sd-stock-header-actions-h: 22px;
  --sd-stock-header-actions-margin-top: 6px;
  --sd-stock-header-actions-gap: 7px;
  --sd-stock-header-action-font-size: var(--cs-font-size-12);
  --sd-stock-header-action-font-weight: var(--cs-font-weight-medium);
  --sd-stock-header-action-color: var(--cs-color-text-secondary);
  --sd-stock-header-action-color-hover: var(--cs-color-brand-accent);
  --sd-stock-header-action-plus-color: var(--cs-color-brand-accent);
  --sd-stock-header-action-separator-color: var(--cs-color-text-weak);
  --sd-stock-header-action-hover-bg: rgba(247, 199, 107, 0.08);
  --sd-stock-header-action-radius: var(--cs-radius-sm);

  /* Vertical rhythm after compression */
  --sd-stock-header-to-tabs-gap: 8px;
}
```

说明：

- `--sd-stock-header-compact-h` 是右侧 StockHeader 红框 3 的目标紧凑高度；
- 不通过新增空白保持旧高度；
- 压缩出的空间应释放给 `盘口 / 资料 Tab`、盘口摘要、关联板块与个股资金统计；
- 若实际内容过长，应优先使用单行省略，而不是增加 StockHeader 高度。

## 81.4 StockHeaderSummaryRow 布局规则

```css
.sd-stock-header-summary-row {
  min-height: var(--sd-stock-header-summary-row-h);
  display: grid;
  grid-template-columns: minmax(var(--sd-stock-header-left-min-w), 1fr) minmax(var(--sd-stock-header-right-min-w), auto);
  column-gap: var(--sd-stock-header-summary-column-gap);
  align-items: center;
}

.sd-stock-header-identity-group {
  min-width: 0;
  display: flex;
  flex-direction: column;
  justify-content: center;
  row-gap: var(--sd-stock-header-left-line-gap);
}

.sd-stock-header-price-group {
  min-width: var(--sd-stock-header-right-min-w);
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  justify-content: center;
  row-gap: var(--sd-stock-header-right-line-gap);
  text-align: right;
}
```

布局要求：

1. `StockHeaderSummaryRow` 是左右两列；
2. 左侧为 `StockHeaderIdentityGroup`；
3. 右侧为 `StockHeaderPriceGroup`；
4. 左右两组整体垂直居中；
5. 右侧价格组右对齐；
6. 左右两组之间只保留必要间距，不做大留白；
7. 不允许把价格和股票识别信息上下堆成高 Header。

## 81.5 左侧股票识别信息组

左侧信息组包含两行：

```text
第一行：股票名称 + 行业题材标签
第二行：股票代码
```

视觉规则：

1. 股票名称为主识别信息；
2. 行业题材标签与股票名称同一行；
3. 股票代码位于第二行；
4. 股票代码弱化但可读；
5. 左侧两行之间使用紧凑行距；
6. 左侧信息组整体垂直居中；
7. 不展示 Mock 说明；
8. 不展示路径说明；
9. 不展示状态说明；
10. 不增加额外副说明。

推荐 CSS：

```css
.sd-stock-header-name-row {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: var(--sd-stock-header-name-tag-gap);
}

.sd-stock-header-name {
  min-width: 0;
  color: var(--sd-stock-header-name-color);
  font-size: var(--sd-stock-header-name-size);
  font-weight: var(--sd-stock-header-name-weight);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sd-stock-header-tag {
  height: var(--sd-stock-header-tag-h);
  padding: 0 var(--sd-stock-header-tag-padding-x);
  display: inline-flex;
  align-items: center;
  border-radius: var(--sd-stock-header-tag-radius);
  border: 1px solid var(--sd-stock-header-tag-border);
  background: var(--sd-stock-header-tag-bg);
  color: var(--sd-stock-header-tag-color);
  font-size: var(--sd-stock-header-tag-font-size);
  white-space: nowrap;
  flex: 0 0 auto;
}

.sd-stock-header-code {
  color: var(--sd-stock-header-code-color);
  font-size: var(--sd-stock-header-code-size);
  font-weight: var(--sd-stock-header-code-weight);
  font-family: var(--cs-font-family-number);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
```

## 81.6 右侧行情价格信息组

右侧价格组包含两行：

```text
第一行：最新股价
第二行：涨跌额 + 涨跌幅
```

视觉规则：

1. 最新股价右对齐；
2. 涨跌额 + 涨跌幅右对齐；
3. 最新股价使用数字字体；
4. 涨跌额和涨跌幅使用数字字体；
5. 按中国市场红涨绿跌；
6. 不添加额外价格说明文字；
7. 不在其它位置重复展示价格或涨跌幅。

推荐 CSS：

```css
.sd-stock-header-price {
  color: var(--cs-color-market-up); /* 按 direction 切换 up/down/flat */
  font-family: var(--cs-font-family-number);
  font-variant-numeric: tabular-nums;
  font-size: var(--sd-stock-header-price-size);
  font-weight: var(--sd-stock-header-price-weight);
  line-height: var(--sd-stock-header-price-line-height);
  text-align: right;
  white-space: nowrap;
}

.sd-stock-header-change-row {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--sd-stock-header-change-gap);
  color: var(--cs-color-market-up); /* 按 direction 切换 up/down/flat */
  font-family: var(--cs-font-family-number);
  font-variant-numeric: tabular-nums;
  font-size: var(--sd-stock-header-change-size);
  font-weight: var(--sd-stock-header-change-weight);
  white-space: nowrap;
}
```

红涨绿跌：

| 状态 | 最新股价 | 涨跌额 | 涨跌幅 |
|---|---|---|---|
| 上涨 | 红色 | 红色，带 `+` | 红色，带 `+` |
| 下跌 | 绿色 | 绿色，带 `-` | 绿色，带 `-` |
| 平盘 | 灰白色 | 灰白色，`0.00` | 灰白色，`0.00%` |

## 81.7 下方 `+自选 / +提醒 / +交易计划` 操作区

`StockHeader` 小板块下方紧接操作区：

```text
+自选 / +提醒 / +交易计划
```

要求：

1. 每个操作项前加 `+`；
2. 操作区紧贴 `StockHeaderSummaryRow` 下方；
3. 不要被空白撑开；
4. 不再展示 `诊股`；
5. `/` 分隔符使用弱文字；
6. hover 使用轻量品牌金提示；
7. 操作区保持高密度、金融终端风格。

推荐 CSS：

```css
.sd-stock-header-actions {
  height: var(--sd-stock-header-actions-h);
  margin-top: var(--sd-stock-header-actions-margin-top);
  display: flex;
  align-items: center;
  gap: var(--sd-stock-header-actions-gap);
  color: var(--sd-stock-header-action-color);
  font-size: var(--sd-stock-header-action-font-size);
  font-weight: var(--sd-stock-header-action-font-weight);
}

.sd-stock-header-action {
  height: 20px;
  padding: 0 4px;
  display: inline-flex;
  align-items: center;
  border-radius: var(--sd-stock-header-action-radius);
  color: var(--sd-stock-header-action-color);
  cursor: pointer;
}

.sd-stock-header-action::first-letter {
  color: var(--sd-stock-header-action-plus-color);
}

.sd-stock-header-action:hover {
  color: var(--sd-stock-header-action-color-hover);
  background: var(--sd-stock-header-action-hover-bg);
}

.sd-stock-header-action-separator {
  color: var(--sd-stock-header-action-separator-color);
  user-select: none;
}
```

操作项：

| 操作 | 显示 |
|---|---|
| 自选 | `+自选` |
| 提醒 | `+提醒` |
| 交易计划 | `+交易计划` |

删除项：

```text
诊股
```

原因：顶部 `Chart Workspace Toolbar` 已保留诊股入口，右侧 `StockHeader` 不再重复展示。

## 81.8 StockHeader 压缩后的垂直节奏

StockHeader 精简后，以下内容应整体上移：

1. `+自选 / +提醒 / +交易计划`；
2. `盘口 / 资料 Tab`；
3. 盘口摘要；
4. 关联板块；
5. 个股资金统计。

视觉节奏要求：

1. 不允许通过新增空白保持旧高度；
2. 不允许把压缩空间再次填入无意义说明文字；
3. 不重做下方模块内部结构；
4. 仅通过 StockHeader 高度、padding、行距压缩释放空间；
5. 下方模块与操作区之间保留必要间距，但不得出现大面积空白。

推荐容器关系：

```css
.sd-right-panel-header {
  padding: var(--sd-stock-header-compact-padding-y) var(--sd-stock-header-compact-padding-x);
  border: var(--sd-stock-header-compact-border);
  border-radius: var(--sd-stock-header-compact-radius);
  background: var(--sd-stock-header-compact-bg);
}

.sd-right-panel-tabs {
  margin-top: var(--sd-stock-header-to-tabs-gap);
}
```

## 81.9 StockHeader 红框 3 禁止事项

禁止：

1. 在右侧 `StockHeader` 操作区继续展示 `诊股`；
2. 在右侧 `StockHeader` 中展示 Mock 说明、路径说明、状态说明；
3. 在右侧 `StockHeader` 中重复展示完整路径；
4. 在右侧 `StockHeader` 中加入更新时间、刷新、READY；
5. 在右侧 `StockHeader` 下方保留旧高度空白；
6. 将股票名称、代码、价格、涨跌幅上下堆成高大 Header；
7. 重做盘口 / 资料 Tab 内部结构；
8. 修改关联板块表字段；
9. 修改资金统计结构；
10. 修改红涨绿跌规则。

---

# 82. 本轮 Review v4 修改摘要

1. 仅修订 `个股详情页 / 右侧信息栏 / StockHeader 红框 3`。
2. `StockHeader` 改为左右两列紧凑小板块。
3. 左侧股票识别信息组展示：股票名称 + 行业题材标签、股票代码。
4. 右侧行情价格信息组展示：最新股价、涨跌额 + 涨跌幅。
5. 左右两组整体垂直居中，左侧靠左，右侧靠右。
6. 下方紧接 `+自选 / +提醒 / +交易计划`。
7. 每个操作项前加 `+`。
8. 删除右侧 `StockHeader` 中的 `诊股`。
9. `诊股` 只保留在上方 `Chart Workspace Toolbar`。
10. `StockHeader` 压缩后，盘口 / 资料 Tab、盘口摘要、关联板块、个股资金统计整体上移。
11. 不修改本轮未点名区域。

# 83. 本轮未修改区域说明

本轮未修改：

1. TopMarketBar；
2. Breadcrumb；
3. Chart Workspace Toolbar；
4. 周期切换区；
5. 前复权按钮；
6. 股票资料按钮；
7. 顶部诊股按钮；
8. 设置按钮；
9. K 线主图；
10. MACD；
11. 成交量；
12. KDJ；
13. 坐标轴刻度；
14. 时间轴刻度；
15. Header Info；
16. MA / BOLL 切换；
17. 十字线；
18. Tooltip；
19. 盘口 / 资料 Tab 结构；
20. 关联板块表字段；
21. 个股资金统计结构；
22. 资料 Tab 暂未开通；
23. 默认 144 根 K 线；
24. 固定视口 100vh 布局；
25. API 字段和数据字典；
26. 红涨绿跌规则。

```text
本轮因 Review v4 修改而被动影响的区域：
- 右侧信息栏中 StockHeader 下方模块的整体垂直位置
原因：StockHeader 压缩后，下方 `+自选 / +提醒 / +交易计划`、盘口 / 资料 Tab、盘口摘要、关联板块、个股资金统计需要整体上移
是否需要产品总控确认：否，Review v4 已明确
```

# 84. 本轮新增或修订 Token 清单

| Token | 类型 | 用途 |
|---|---|---|
| `--sd-stock-header-compact-h` | 新增 | 右侧 StockHeader 紧凑高度 |
| `--sd-stock-header-compact-min-h` | 新增 | 极限紧凑高度 |
| `--sd-stock-header-compact-padding-x` | 新增 | StockHeader 横向内边距 |
| `--sd-stock-header-compact-padding-y` | 新增 | StockHeader 纵向内边距 |
| `--sd-stock-header-summary-row-h` | 新增 | 左右两列 SummaryRow 高度 |
| `--sd-stock-header-summary-column-gap` | 新增 | 左右两列间距 |
| `--sd-stock-header-left-min-w` | 新增 | 左侧信息组最小宽度 |
| `--sd-stock-header-right-min-w` | 新增 | 右侧价格组最小宽度 |
| `--sd-stock-header-name-size` | 修订 | 股票名称字号 |
| `--sd-stock-header-name-weight` | 修订 | 股票名称字重 |
| `--sd-stock-header-name-color` | 新增 | 股票名称颜色 |
| `--sd-stock-header-tag-*` | 新增 | 行业题材标签样式 |
| `--sd-stock-header-code-*` | 新增 | 股票代码弱化样式 |
| `--sd-stock-header-left-line-gap` | 新增 | 左侧两行行距 |
| `--sd-stock-header-name-tag-gap` | 新增 | 股票名称与行业标签间距 |
| `--sd-stock-header-price-*` | 修订 | 最新股价字号、字重、行高 |
| `--sd-stock-header-change-*` | 修订 | 涨跌额 + 涨跌幅字号、间距 |
| `--sd-stock-header-actions-*` | 新增 | `+自选 / +提醒 / +交易计划` 操作区样式 |
| `--sd-stock-header-to-tabs-gap` | 新增 | StockHeader 到盘口 / 资料 Tab 的间距 |

# 85. 对 03 `04-component-guidelines.md` 的 Token 映射建议

建议 03 修订以下组件：

| 组件 | 建议使用 Token |
|---|---|
| `StockHeaderPanel` | `--sd-stock-header-compact-*`、`--sd-stock-header-summary-*` |
| `StockHeaderSummaryRow` | `--sd-stock-header-summary-row-h`、`--sd-stock-header-summary-column-gap` |
| `StockHeaderIdentityGroup` | `--sd-stock-header-name-*`、`--sd-stock-header-tag-*`、`--sd-stock-header-code-*` |
| `StockHeaderPriceGroup` | `--sd-stock-header-price-*`、`--sd-stock-header-change-*`、`--cs-color-market-*` |
| `StockHeaderActionLinks` | `--sd-stock-header-actions-*`、`--sd-stock-header-action-*` |

推荐结构：

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

03 组件规范必须明确：

1. `StockHeaderSummaryRow` 为左右两列；
2. 左右两组整体垂直居中；
3. `StockHeaderPriceGroup` 右对齐；
4. `StockHeaderActionLinks` 紧接下方；
5. `StockHeaderActionLinks` 不包含诊股；
6. 诊股只保留在 `Chart Workspace Toolbar`；
7. 不允许 StockHeader 添加大面积留白；
8. 不允许 StockHeader 承担完整详情页 Header 职责。

# 86. 对 02 `stock-detail-v1.4.html` 的视觉约束

1. 只修改右侧 StockHeader 红框 3。
2. StockHeader 必须改为左右两列结构。
3. 左侧第一行展示：股票名称 + 行业题材标签。
4. 左侧第二行展示：股票代码。
5. 右侧第一行展示：最新股价。
6. 右侧第二行展示：涨跌额 + 涨跌幅。
7. 左右两组作为整体在垂直方向上居中对齐。
8. 左侧靠左，右侧价格组靠右。
9. 下方紧接展示：`+自选 / +提醒 / +交易计划`。
10. 每个操作项前必须有 `+`。
11. 操作项之间使用 `/` 或等价弱分隔。
12. 删除右侧 StockHeader 操作区中的 `诊股`。
13. 诊股只保留在上方 Chart Workspace Toolbar。
14. `+自选 / +提醒 / +交易计划`、盘口 / 资料 Tab、盘口摘要、关联板块、个股资金统计应整体上移。
15. 不允许通过新增空白保持旧高度。
16. 不展示 Mock 说明、路径说明、状态说明。
17. 不在右侧 StockHeader 中加入更新时间、刷新、READY。
18. 不在其它位置重复展示价格或涨跌幅。
19. 不修改本轮未点名模块。

# 87. 待产品总控确认问题

1. 右侧 `StockHeader` 目标紧凑高度 `76px` 是否接受，极限高度 `68px` 是否可作为小屏压缩值。
2. 行业题材标签是否允许最多显示 2 个，超出后以 `+N` 或省略处理。当前 Token 只定义标签样式，具体数量由 02/03 控制。
3. 股票名称与行业题材标签同一行时，如果宽度不足，是否优先保留股票名称完整、标签省略。当前建议是股票名称优先。
4. 最新股价是否必须总是使用方向色。当前建议按方向色显示，以符合行情终端习惯。
5. `+自选 / +提醒 / +交易计划` hover 后是否需要 tooltip。当前建议 P0 不需要。
6. 右侧 StockHeader 删除诊股后，是否需要在操作区预留空位。当前建议不预留。

# 88. 本轮输出文件下载链接

本轮输出文件名：

```text
03-design-tokens.md
```

下载链接由本轮对话附件提供。

建议放置到 Google Drive：

```text
财势乾坤/设计/03-design-tokens.md
```

