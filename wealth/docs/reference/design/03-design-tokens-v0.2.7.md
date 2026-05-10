# 财势乾坤｜Design Token 与视觉规范 v0.2.7

> 所属项目：财势乾坤  
> 文档名称：`03-design-tokens.md`  
> 建议保存路径：`财势乾坤/设计/03-design-tokens.md`  
> 文档角色：01_Design Token 与视觉规范  
> 适用范围：P0 Web 页面，优先服务“乾坤行情 / 市场总览”  
> 默认主题：Dark First，Light Token Ready  
> 市场规则：中国市场红涨绿跌  
> 当前状态：v0.2.7，基于市场总览 HTML Review v4 局部修订  
> 本轮修订边界：仅补充 Review v4 点名的两个展示问题视觉规则，不主动修改 TopMarketBar、Breadcrumb、PageHeader、ShortcutBar、今日市场客观总结、主要指数、涨跌分布、市场风格、成交额总览、榜单速览、连板天梯、板块速览、页面整体主题、全局字体、页面整体布局顺序。

---

## 0. 文档目标与本轮修订边界

本规范用于指导“财势乾坤”P0 阶段 Web 页面视觉落地，重点服务“市场总览”页面的 HTML Showcase、组件库设计和前端实现。

市场总览是系统打开后的默认落地页，但导航归属固定为“乾坤行情”。该页面是 A 股市场客观事实总览页，不是主观分析结论页。

本规范不做完整品牌手册，重点解决以下问题：

1. 明确深色主题下市场总览的可落地视觉 Token。
2. 保留浅色主题 Token 结构，后续可通过配置切换。
3. 固化 A 股红涨绿跌规则。
4. 明确市场总览无固定 SideNav 的桌面端布局规则。
5. 为 02 页面原型、03 组件库、04 API、05 Codex 提示词提供一致的视觉和字段约束。
6. 基于 Review v1 补齐图表坐标、Tooltip、RangeSwitch、HelpTooltip、资金趋势线、涨跌停组合柱图、横向连板天梯等规则。
7. 基于 Review v2 轻量补充以下区域视觉规则：
   - 今日市场客观总结与主要指数左右结构；
   - 榜单速览 Top10 表格密度；
   - 涨跌停统计与分布 2×2 区域；
   - 板块速览 4 列 × 2 行榜单矩阵 + 右侧跨两行 5×4 热力图。
8. 基于 Review v3 仅补充以下两个区域视觉规则：
   - 涨跌停统计与分布中的“涨停板块分布｜领涨股｜涨停表现”三段式结构；
   - 大盘资金流向模块中的单型资金净流向饼图与“左饼图 + 右趋势图”内部布局。

### 0.1 本轮允许修改区域

本轮只允许围绕 Review v4 明确点名的两个展示问题补充或修订视觉规则：

1. 涨跌停统计与分布中的：
   - 今日“领涨股涨停表现”行式结构；
   - 昨日“领涨股涨停表现”行式结构。
2. 大盘资金流向模块中的：
   - 单型资金净流向饼图；
   - 饼图折线标注；
   - 饼块上的白色占比文字；
   - 饼图中心留白规则。

### 0.2 本轮禁止主动修改区域

本轮禁止主动修改：

1. TopMarketBar。
2. Breadcrumb。
3. PageHeader。
4. ShortcutBar。
5. 今日市场客观总结。
6. 主要指数。
7. 涨跌分布。
8. 市场风格。
9. 成交额总览。
10. 榜单速览。
11. 连板天梯。
12. 板块速览。
13. 页面整体主题。
14. 全局字体。
15. 页面整体布局顺序。
16. 与 Review v4 无关的视觉规则。

若后续实现中因为 Review v4 指定区域的内部展示修正而被动影响相邻模块，需要在页面设计或 Codex 执行报告中单独说明。

---

## 1. 已确认产品决策

| 决策项 | 已确认结论 | 对视觉 / Token 的影响 |
|---|---|---|
| 产品名称 | 财势乾坤 | 所有页面标题、品牌露出、文档标题统一使用该名称 |
| 首期形态 | Web 优先 | Token 和布局优先支持桌面 Web |
| 首期市场 | A 股优先 | 涨跌色、指数、榜单、K 线均按中国市场习惯设计 |
| 默认落地页 | 市场总览 | 系统打开后默认进入市场总览 |
| 页面归属 | 市场总览属于乾坤行情 | Breadcrumb 固定为“财势乾坤 / 乾坤行情 / 市场总览” |
| 页面职责 | 市场客观事实总览 | 不展示市场温度、情绪指数、资金面分数、风险指数的具体分数 |
| 桌面端导航 | 不使用固定 SideNav | 使用 TopMarketBar + Breadcrumb + PageHeader + ShortcutBar + 全宽行情内容区 |
| TopMarketBar | 乾坤行情展开，其他系统折叠 | 当前系统横向展开，其他系统进入 GlobalSystemMenu |
| PageHeader 高度 | 56px | 固化 `--cs-layout-page-header-height: 56px` |
| 主要指数 | 10 个，2 行 × 5 列 | IndexGrid 固化高密度两行排布 |
| ShortcutBar 状态 | 只展示未读提醒数量 | 不展示自选数量、持仓数量等个人状态 |
| 板块热力图 | Review v2 要求在板块速览右侧跨两行展示 5×4 热力图 | 不再只是入口；本轮仅在板块速览指定区域补充展示规则 |
| 连板天梯 | 展示完整结构 | 允许模块内部滑动；Review v3 不修改该区域 |
| 市场风格口径 | API 侧定义 | Token 只定义展示样式，不定义大盘 / 小盘计算口径 |
| 资金流拆分 | 支持超大单 / 大单 / 中单 / 小单 | Review v3 仅补充单型资金净流向饼图和左饼图 + 右趋势图内部布局 |
| 自动刷新 | 可配置，默认 10s | RefreshControl 默认展示“自动 10s”；Review v3 不修改该区域 |
| 浅色主题 | P0 只保留 Token 结构 | Showcase 优先深色高保真 |
| 品牌强调色 | 金色系固定 | 品牌、选中、十字光标、重点入口使用金色系 |
| Review v2 范围 | 只改 4 个点名区域 | 本文保留 v0.2.5 已确认的布局密度和视觉规则 |
| Review v3 范围 | 只改 2 个点名区域 | 本文保留三段式涨停板块结构、单型资金净流向饼图和资金模块内部左右布局规则 |
| Review v4 范围 | 只改 2 个展示问题 | 将“领涨股 + 涨停表现”合并为“领涨股涨停表现”行式结构；饼图增加折线标注、白色占比文字并清空中心文案 |

---

## 2. 视觉定位

### 2.1 风格关键词

| 关键词 | 说明 |
|---|---|
| 专业 | 面向进阶投资者与专业交易者，不做娱乐化表达 |
| 沉稳 | 低亮度背景、克制强调色、减少视觉噪音 |
| 高密度 | 支撑 10 个指数、分布、资金、涨跌停、板块、榜单同屏展示 |
| 金融终端感 | 数字清晰、表格紧凑、图表克制、状态明确 |
| 数据可信 | 明确交易日、开闭市、更新时间、数据延迟和异常 |
| 客观事实 | 市场总览只呈现市场事实，不输出主观买卖结论 |

### 2.2 适用场景

本规范适用于：

- 市场总览；
- 板块与榜单行情；
- 指数详情；
- 个股详情；
- 我的自选；
- 市场温度与情绪分析页的基础容器和图表部分；
- 机会雷达、持仓分析、提醒中心的行情数据表达部分。

其中，“市场总览”是 v0.2.6 的优先落地页面。

### 2.3 禁止方向

明确禁止：

1. 市场总览桌面端使用固定 SideNav。
2. 为左侧导航预留大面积空白。
3. 把市场总览做成独立一级菜单。
4. 把市场总览做成欢迎页、营销页或品牌展示页。
5. 使用廉价大屏风、霓虹风、发光边框、大面积无意义渐变。
6. 使用低幼插画、过度圆角、卡通化图标。
7. 在市场总览展示市场温度、情绪指数、资金面分数、风险指数的具体分数。
8. 在市场总览输出“建议买入、建议减仓、看多、看空、明日大概率上涨”等主观结论。
9. 出现绿涨红跌。
10. 把行情红作为系统错误主色。

---

## 3. Token 命名规范

### 3.1 命名前缀

统一使用：

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
--cs-layout-top-market-bar-height
--cs-radius-card
--cs-shadow-dropdown
```

### 3.3 Token 分类

| 分类 | 前缀 |
|---|---|
| 色彩 | `--cs-color-*` |
| 字体 | `--cs-font-*` |
| 间距 | `--cs-space-*` |
| 尺寸 / 布局 | `--cs-size-*` / `--cs-layout-*` |
| 圆角 | `--cs-radius-*` |
| 边框 | `--cs-border-*` |
| 阴影 | `--cs-shadow-*` |
| 层级 | `--cs-z-*` |
| 动效 | `--cs-motion-*` |
| 图表 | `--cs-chart-*` |
| 行情 | `--cs-color-market-*` |
| 状态 | `--cs-color-status-*` |

---

## 4. 全局基础 Token

> 本轮 Review v3 不修改全局主题色、全局字体和基础间距体系。本节保留既有基线。

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
  --cs-z-top-market-bar: 300;
  --cs-z-dropdown: 500;
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

> 本轮 Review v3 不修改全局主题色。本节保留既有深色主题基线，并承接 Review v1 已确认的图表与 Tooltip Token。

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
  --cs-color-chart-grid-strong: rgba(148, 163, 184, 0.20);
  --cs-color-chart-axis: rgba(148, 163, 184, 0.38);
  --cs-color-chart-axis-strong: rgba(203, 213, 225, 0.42);
  --cs-color-chart-label: #7B8AA0;
  --cs-color-chart-crosshair: rgba(247, 199, 107, 0.72);
  --cs-color-chart-zero-axis: rgba(229, 237, 248, 0.34);
  --cs-color-chart-point-hover-fill: #0B1220;
  --cs-color-chart-point-hover-stroke: #F7C76B;

  /* Tooltip */
  --cs-color-tooltip-bg: rgba(8, 13, 22, 0.96);
  --cs-color-tooltip-border: rgba(247, 199, 107, 0.28);
  --cs-color-tooltip-text: #E5EDF8;
  --cs-color-tooltip-muted: #A8B4C6;

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

  --cs-color-market-flat: #D8DEE8;
  --cs-color-market-flat-soft: #A8B4C6;
  --cs-color-market-flat-bg: rgba(216, 222, 232, 0.10);
  --cs-color-market-flat-border: rgba(216, 222, 232, 0.26);

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

  /* Review v1: historical chart series */
  --cs-color-series-large-cap: #5AA7FF;
  --cs-color-series-small-cap: #A78BFA;
  --cs-color-series-median: #F7C76B;
  --cs-color-series-turnover: #5AA7FF;
  --cs-color-series-fundflow-main: #E5EDF8;

  /* Limit-up / break board */
  --cs-color-limit-up: var(--cs-color-market-up);
  --cs-color-limit-down: var(--cs-color-market-down);
  --cs-color-limit-break: var(--cs-color-warning);
  --cs-color-limit-break-bg: var(--cs-color-warning-bg);
}
```

---

## 6. 浅色主题 Token

> P0 阶段只保留浅色主题 Token 结构，后续通过配置即可切换，不要求在 P0 Showcase 中同步实现高保真浅色页面。本轮 Review v3 不修改浅色主题结构。

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
  --cs-color-chart-grid-strong: rgba(15, 23, 42, 0.18);
  --cs-color-chart-axis: rgba(15, 23, 42, 0.34);
  --cs-color-chart-axis-strong: rgba(15, 23, 42, 0.44);
  --cs-color-chart-label: #64748B;
  --cs-color-chart-crosshair: rgba(168, 117, 33, 0.72);
  --cs-color-chart-zero-axis: rgba(15, 23, 42, 0.34);
  --cs-color-chart-point-hover-fill: #FFFFFF;
  --cs-color-chart-point-hover-stroke: #A87521;

  /* Tooltip */
  --cs-color-tooltip-bg: rgba(255, 255, 255, 0.98);
  --cs-color-tooltip-border: rgba(201, 154, 61, 0.30);
  --cs-color-tooltip-text: #0F172A;
  --cs-color-tooltip-muted: #64748B;

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
  --cs-color-market-flat-soft: #64748B;
  --cs-color-market-flat-bg: rgba(100, 116, 139, 0.10);
  --cs-color-market-flat-border: rgba(100, 116, 139, 0.24);

  /* Brand gold */
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

  /* Chart series */
  --cs-color-series-large-cap: #2563EB;
  --cs-color-series-small-cap: #7C3AED;
  --cs-color-series-median: #A87521;
  --cs-color-series-turnover: #2563EB;
  --cs-color-series-fundflow-main: #0F172A;

  --cs-color-limit-up: var(--cs-color-market-up);
  --cs-color-limit-down: var(--cs-color-market-down);
  --cs-color-limit-break: var(--cs-color-warning);
  --cs-color-limit-break-bg: var(--cs-color-warning-bg);
}
```

---

## 7. 市场总览基础布局 Token

> 本节为既有市场总览布局基线。Review v3 没有修改 TopMarketBar、Breadcrumb、PageHeader、ShortcutBar、全局主题和全局字体。

```css
:root {
  /* Top layout */
  --cs-layout-top-market-bar-height: 52px;
  --cs-layout-breadcrumb-height: 32px;
  --cs-layout-page-header-height: 56px;
  --cs-layout-shortcut-bar-height: 44px;

  /* Page width */
  --cs-layout-content-min-width: 1180px;
  --cs-layout-content-max-width: 1680px;
  --cs-layout-content-max-width-wide: 1920px;

  /* Page padding */
  --cs-layout-page-padding-x: 20px;
  --cs-layout-page-padding-y: 16px;
  --cs-layout-page-padding-x-wide: 24px;

  /* Module spacing */
  --cs-layout-module-gap: 14px;
  --cs-layout-section-gap: 16px;
  --cs-layout-card-gap: 12px;

  /* Card padding */
  --cs-layout-panel-padding: 14px;
  --cs-layout-card-padding: 12px;
  --cs-layout-card-padding-compact: 10px;

  /* Table density */
  --cs-layout-table-header-height: 32px;
  --cs-layout-table-row-height: 34px;
  --cs-layout-table-row-height-compact: 30px;

  /* Index cards */
  --cs-layout-index-card-count: 10;
  --cs-layout-index-card-rows: 2;
  --cs-layout-index-card-columns: 5;
  --cs-layout-index-card-min-width: 152px;
  --cs-layout-index-card-height: 92px;
  --cs-layout-index-card-height-compact: 86px;

  /* Mini chart */
  --cs-layout-mini-chart-width: 96px;
  --cs-layout-mini-chart-height: 32px;
  --cs-layout-sparkline-height: 28px;

  /* Ranking base */
  --cs-layout-ranking-table-row-height: 32px;
  --cs-layout-ranking-table-visible-rows: 8;

  /* Limit-up ladder */
  --cs-layout-limit-ladder-min-height: 280px;
  --cs-layout-limit-ladder-level-min-width: 148px;
  --cs-layout-limit-ladder-max-height: 420px;

  /* No SideNav dependency */
  --cs-layout-market-overview-sidebar-width: 0px;
}
```

---

## 8. Review v1 已确认的图表、Tooltip 与切换控件 Token

> 本节来自 Review v1 后的视觉基线。本轮 Review v3 未修改这些规则，仅作为全量文档保留。

### 8.1 HelpTooltip / 圆圈问号

```css
:root {
  --cs-help-icon-size: 16px;
  --cs-help-icon-font-size: 11px;
  --cs-help-icon-color: var(--cs-color-text-muted);
  --cs-help-icon-color-hover: var(--cs-color-brand-accent);
  --cs-help-icon-color-active: var(--cs-color-brand-primary-hover);
  --cs-help-icon-bg: transparent;
  --cs-help-icon-bg-hover: var(--cs-color-brand-accent-bg);
  --cs-help-icon-border: var(--cs-color-border-default);
  --cs-help-icon-border-hover: var(--cs-color-brand-accent-border);

  --cs-help-tooltip-max-width: 320px;
  --cs-help-tooltip-padding-x: 12px;
  --cs-help-tooltip-padding-y: 10px;
  --cs-help-tooltip-radius: var(--cs-radius-lg);
  --cs-help-tooltip-bg: var(--cs-color-tooltip-bg);
  --cs-help-tooltip-border: var(--cs-color-tooltip-border);
  --cs-help-tooltip-text: var(--cs-color-tooltip-text);
  --cs-help-tooltip-muted: var(--cs-color-tooltip-muted);
  --cs-help-tooltip-z: var(--cs-z-tooltip);
}
```

规则：

1. 模块标题下方的解释性文字不直接占用正文空间，应收纳到标题旁 HelpTooltip。
2. 圆圈问号尺寸 16px，字号 11px，默认弱文字，hover 使用品牌金。
3. Tooltip 深色主题下必须有足够可读性，背景接近不透明。
4. Tooltip 最大宽度 320px，避免解释文字横向过长。

### 8.2 RangeSwitch：1个月 / 3个月

```css
:root {
  --cs-range-switch-height: 26px;
  --cs-range-switch-padding-x: 8px;
  --cs-range-switch-font-size: 12px;
  --cs-range-switch-gap: 4px;
  --cs-range-switch-radius: var(--cs-radius-md);
  --cs-range-switch-bg: var(--cs-color-surface-panel-subtle);
  --cs-range-switch-border: var(--cs-color-border-subtle);
  --cs-range-switch-text: var(--cs-color-text-secondary);
  --cs-range-switch-bg-hover: var(--cs-color-surface-card-hover);
  --cs-range-switch-text-hover: var(--cs-color-text-primary);
  --cs-range-switch-bg-selected: var(--cs-color-brand-accent-bg);
  --cs-range-switch-border-selected: var(--cs-color-brand-accent-border);
  --cs-range-switch-text-selected: var(--cs-color-brand-accent);
  --cs-range-switch-disabled-opacity: 0.45;
  --cs-chart-header-control-gap: 8px;
}
```

适用模块：

- 涨跌分布历史趋势图；
- 市场风格历史趋势图；
- 历史成交额趋势图；
- 大盘资金流历史趋势图；
- 涨跌停历史柱状图。

### 8.3 HistoryTrendChart 基础视觉

```css
:root {
  --cs-history-chart-height-sm: 160px;
  --cs-history-chart-height-md: 190px;
  --cs-history-chart-height-lg: 220px;
  --cs-history-chart-padding-top: 12px;
  --cs-history-chart-padding-right: 12px;
  --cs-history-chart-padding-bottom: 22px;
  --cs-history-chart-padding-left: 34px;
  --cs-history-chart-legend-gap: 10px;
  --cs-history-chart-legend-font-size: 11px;
  --cs-history-chart-axis-font-size: 11px;
  --cs-history-chart-line-width: 1.5px;
  --cs-history-chart-line-width-emphasis: 2px;
  --cs-history-chart-point-size: 4px;
  --cs-history-chart-point-size-hover: 6px;
}
```

规则：

1. 图表背景使用 `--cs-color-chart-bg`。
2. X / Y 轴使用 `--cs-color-chart-axis`。
3. 坐标文字使用 `--cs-color-chart-label`。
4. 网格线使用 `--cs-color-chart-grid`。
5. 鼠标定位线使用 `--cs-color-chart-crosshair`。
6. Tooltip 使用 `--cs-color-tooltip-*`。
7. 数据点 hover 使用空心点或描边点，不做发光效果。
8. 图例字号 11px，避免占用图表主体。

### 8.4 涨跌分布趋势线

| 系列 | 颜色 | 说明 |
|---|---|---|
| 上涨家数线 | `--cs-color-market-up` | 红色 |
| 下跌家数线 | `--cs-color-market-down` | 绿色 |
| 平盘家数 | 不进入历史趋势图 | 平盘只在当日卡片中展示 |

Tooltip 显示：

```text
日期
上涨家数：xxxx
下跌家数：xxxx
```

### 8.5 市场风格趋势线

市场风格趋势图是百分比曲线。系列色不直接表达涨跌方向，而是表达“数据系列身份”；Tooltip 内具体数值仍按正负红绿显示。

| 系列 | 颜色 | 说明 |
|---|---|---|
| 大盘平均涨跌幅 | `--cs-color-series-large-cap` | 系列身份色，不代表涨跌方向 |
| 小盘平均涨跌幅 | `--cs-color-series-small-cap` | 系列身份色，不代表涨跌方向 |
| 涨跌中位数 | `--cs-color-series-median` | 系列身份色，不代表涨跌方向 |

规则：

1. 曲线颜色不使用红绿，以避免与正负语义冲突。
2. Y 轴 0 线需要清晰展示。
3. Tooltip 中百分比为正时红色，为负时绿色，为 0 时白色 / 灰白色。

### 8.6 成交额趋势图

成交额趋势图包括：

1. 日内累计成交额趋势线；
2. 历史成交额趋势线。

规则：

- 日内累计成交额 X 轴为盘中时间；
- 历史成交额 X 轴为交易日期；
- 金额单位自动显示为亿元 / 万亿元；
- Tooltip 金额格式示例：`成交额：1.24 万亿元`、`成交额：8564.32 亿元`；
- 成交额本身不使用红绿，默认使用系列色或主文字色。

### 8.7 大盘资金流向趋势图

必须遵守：

1. 主趋势线使用白色：`--cs-color-series-fundflow-main`。
2. Y 轴 0 值在视觉中线位置。
3. 净流入为正数，净流出为负数。
4. Tooltip 中净流入正数用红色。
5. Tooltip 中净流出负数用绿色。
6. 坐标轴单位为亿元。

### 8.8 涨跌停历史组合柱图

| 柱类型 | 颜色 |
|---|---|
| 涨停柱 | `--cs-color-market-up` |
| 跌停柱 | `--cs-color-market-down` |

规则：

1. 同一日期下涨停和跌停在同一柱组中表达。
2. Tooltip 显示日期、涨停数、跌停数。
3. 支持 1个月 / 3个月切换。
4. 炸板不进入该组合柱图；炸板在统计卡和结构块中使用警示色展示。

---

## 9. 行情涨跌色规则

### 9.1 硬规则

```text
上涨 / 正变化 / 净流入 / 涨停 / 高于基准 = 红色
下跌 / 负变化 / 净流出 / 跌停 / 低于基准 = 绿色
平盘 / 0变化 / 无方向 / 无数据方向 = 白色或灰白色
```

### 9.2 CSS 类

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

.cs-market-flat-soft {
  color: var(--cs-color-market-flat-soft);
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

### 9.3 平盘白色 / 灰白色规则

| 场景 | 平盘颜色 | 说明 |
|---|---|---|
| 指数卡主数字 | 白色 / 灰白色 `--cs-color-market-flat` | 保持可读，避免误判为缺失 |
| 涨跌幅 `0.00%` | 灰白色 `--cs-color-market-flat-soft` | 低于上涨/下跌视觉权重 |
| 表格最新价平盘 | 灰白色 | 不使用红绿 |
| Tooltip 平盘值 | 灰白色 | 与正负值区分 |
| K 线十字 / 平盘柱 | 灰色 / 灰白色 | 不用红绿 |
| 无数据 | `--` + 弱文字 | 不等同平盘 |

### 9.4 场景规则

| 场景 | 规则 |
|---|---|
| 指数卡 | 点位、涨跌额、涨跌幅红涨绿跌，平盘白色 / 灰白色 |
| 个股价格 | 最新价相对昨收红涨绿跌 |
| K 线 | 阳线红，阴线绿，平盘灰白 |
| 涨跌幅文字 | 正数红且带 `+`，负数绿且带 `-`，零值灰白 |
| 榜单 | 最新价与涨跌幅列红绿；换手率、量比、成交量、成交额中性色 |
| 热力图 | 涨幅越大红越深，跌幅越大绿越深，平盘灰白 |
| 资金流 | 净流入红，净流出绿，零值灰白；资金流历史主线白色，Tooltip 正负红绿 |
| Tooltip | 所有涨跌字段继续红绿，平盘灰白 |
| 图表曲线 | 方向型曲线红绿；身份型曲线不用红绿 |
| 表格行 | 行背景不随涨跌变色，只对数字上色 |
| Mock 数据 | `change`、`pctChg`、`trend`、颜色必须一致 |

---

## 10. Review v2：今日市场客观总结 + 主要指数左右结构

> 本节是 v0.2.5 新增规则，只影响 Review v2 点名区域，不改变其它首屏模块。

### 10.1 布局结构

“今日市场客观总结 + 主要指数”必须保持左右结构，各占一半空间。

```text
┌──────────────────────────────┬──────────────────────────────┐
│ 今日市场客观总结              │ 主要指数                      │
│ 50%                           │ 50%                           │
└──────────────────────────────┴──────────────────────────────┘
```

禁止：

1. 将“今日市场客观总结”和“主要指数”拆成两个独占整行模块。
2. 将 10 个指数改成单行横向滚动。
3. 因左右结构而删除主要指数。
4. 因左右结构而引入固定 SideNav。

### 10.2 布局 Token

```css
:root {
  --cs-layout-summary-index-gap: 14px;
  --cs-layout-summary-index-columns: 1fr 1fr;
  --cs-layout-summary-panel-min-height: 214px;
  --cs-layout-summary-fact-card-count: 5;
  --cs-layout-summary-fact-card-height: 58px;
  --cs-layout-summary-fact-card-min-width: 104px;
  --cs-layout-summary-note-card-min-height: 82px;
  --cs-layout-summary-note-card-padding: 12px;
  --cs-layout-summary-note-card-font-size: 12px;
  --cs-layout-summary-note-card-line-height: 1.55;

  --cs-layout-split-index-card-height: 72px;
  --cs-layout-split-index-card-height-compact: 66px;
  --cs-layout-split-index-card-gap: 8px;
  --cs-layout-split-index-card-padding: 9px;
  --cs-layout-split-index-card-title-size: 11px;
  --cs-layout-split-index-card-value-size: 18px;
  --cs-layout-split-index-card-change-size: 12px;
}
```

### 10.3 推荐 CSS

```css
.cs-summary-index-row {
  display: grid;
  grid-template-columns: var(--cs-layout-summary-index-columns);
  gap: var(--cs-layout-summary-index-gap);
  align-items: stretch;
}

.cs-market-summary-panel,
.cs-major-index-panel {
  min-height: var(--cs-layout-summary-panel-min-height);
}

.cs-summary-fact-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(var(--cs-layout-summary-fact-card-min-width), 1fr));
  gap: var(--cs-space-8);
}

.cs-summary-fact-card {
  min-height: var(--cs-layout-summary-fact-card-height);
  padding: var(--cs-space-8);
  background: var(--cs-color-surface-card);
  border: 1px solid var(--cs-color-border-subtle);
  border-radius: var(--cs-radius-card);
}

.cs-summary-note-card {
  min-height: var(--cs-layout-summary-note-card-min-height);
  padding: var(--cs-layout-summary-note-card-padding);
  margin-top: var(--cs-space-10);
  background: var(--cs-color-surface-panel-subtle);
  border: 1px solid var(--cs-color-border-subtle);
  border-radius: var(--cs-radius-card);
  color: var(--cs-color-text-secondary);
  font-size: var(--cs-layout-summary-note-card-font-size);
  line-height: var(--cs-layout-summary-note-card-line-height);
}

.cs-major-index-grid--split {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  grid-template-rows: repeat(2, var(--cs-layout-split-index-card-height));
  gap: var(--cs-layout-split-index-card-gap);
}

.cs-index-card--split {
  height: var(--cs-layout-split-index-card-height);
  padding: var(--cs-layout-split-index-card-padding);
}
```

### 10.4 左侧 5 个事实卡片密度

| 项目 | 规则 |
|---|---|
| 数量 | 固定 5 个事实卡片 |
| 排列 | 半宽容器内 5 列，宽度不足时允许 3+2 自动换行，但不能变成纵向长列表 |
| 高度 | 58px 左右，最高不超过 68px |
| 标题字号 | 11px |
| 主数字字号 | 18–22px |
| 单位字号 | 11px |
| 内边距 | 8px |
| 背景 | `--cs-color-surface-card` |
| 边框 | `--cs-color-border-subtle` |
| 涨跌色 | 涉及方向的数字红涨绿跌，平盘灰白 |

### 10.5 左侧说明性文字卡片

说明性文字卡片用于放置今日市场事实摘要，不输出主观结论。

| 项目 | 规则 |
|---|---|
| 高度 | 最小 82px，可随内容扩展，但不应超过 120px |
| 字号 | 12px |
| 行高 | 1.55 |
| 背景 | `--cs-color-surface-panel-subtle` |
| 边框 | `--cs-color-border-subtle` |
| 文字 | `--cs-color-text-secondary` |
| 强调 | 仅对客观事实数字用行情色；不使用大段红绿文字 |

允许表达：

```text
主要指数多数上涨，上涨家数多于下跌家数，成交额较上一交易日放大。
```

禁止表达：

```text
市场已经转强，适合积极加仓。
```

### 10.6 右侧主要指数两行 × 每行 5 个

| 项目 | 规则 |
|---|---|
| 数量 | 10 个指数 |
| 排列 | 2 行 × 5 列 |
| 单卡高度 | 66–72px，半宽区域专用紧凑卡片 |
| 卡片间距 | 8px |
| 指数名称字号 | 11px |
| 点位字号 | 18px 左右 |
| 涨跌幅字号 | 12px |
| 小趋势图 | 可选；若空间不足可隐藏，不影响主信息 |
| 涨跌色 | 点位、涨跌额、涨跌幅红涨绿跌，平盘灰白 |

指数顺序保持既有确认：

第一行：上证指数、深证 A 指、创业板指、科创综指、北证 50。  
第二行：沪深 300、上证 50、中证 A500、中证 500、中证 1000。

---

## 11. Review v2：榜单速览 Top10 表格

> 本节是 v0.2.5 新增规则，只影响榜单速览表格，不修改其它表格体系。

### 11.1 列顺序

榜单速览表格必须支持以下列顺序：

```text
排名｜股票｜最新价｜涨跌幅｜换手率｜量比｜成交量｜成交额
```

### 11.2 表格密度 Token

```css
:root {
  --cs-ranking-top10-header-height: 30px;
  --cs-ranking-top10-row-height: 30px;
  --cs-ranking-top10-row-height-compact: 28px;
  --cs-ranking-top10-font-size-header: 11px;
  --cs-ranking-top10-font-size-cell: 12px;
  --cs-ranking-top10-font-size-code: 10px;
  --cs-ranking-top10-cell-padding-x: 6px;
  --cs-ranking-top10-cell-padding-y: 0px;
  --cs-ranking-top10-table-min-height: 330px;

  --cs-ranking-col-rank-width: 42px;
  --cs-ranking-col-stock-width: 118px;
  --cs-ranking-col-price-width: 68px;
  --cs-ranking-col-pct-width: 72px;
  --cs-ranking-col-turnover-width: 66px;
  --cs-ranking-col-volume-ratio-width: 58px;
  --cs-ranking-col-volume-width: 82px;
  --cs-ranking-col-amount-width: 88px;
}
```

### 11.3 半宽容器中的密度规则

榜单速览在半宽容器中展示 Top10 时，必须控制行高和字号。

| 项目 | 规则 |
|---|---|
| 展示数量 | Top10 |
| 表头高度 | 30px |
| 正文行高 | 30px，极限紧凑可 28px |
| 表头字号 | 11px |
| 单元格字号 | 12px |
| 股票代码字号 | 10px |
| 单元格横向 padding | 6px |
| 表格总高度 | 约 330px，不应显著撑高同排模块 |
| 表格滚动 | 优先完整显示 Top10；半宽极窄时可横向滚动，不允许隐藏列 |

### 11.4 列宽建议

| 列 | 宽度建议 | 对齐 | 颜色规则 |
|---|---:|---|---|
| 排名 | 42px | 居中 | 中性色 |
| 股票 | 118px | 左对齐 | 名称主文字，代码弱文字 |
| 最新价 | 68px | 右对齐 | 按个股涨跌方向红绿，平盘灰白 |
| 涨跌幅 | 72px | 右对齐 | 正红、负绿、零灰白 |
| 换手率 | 66px | 右对齐 | 中性色 |
| 量比 | 58px | 右对齐 | 中性色；异常高不自动红绿，可由业务另加标签 |
| 成交量 | 82px | 右对齐 | 中性色 |
| 成交额 | 88px | 右对齐 | 中性色 |

### 11.5 hover / selected 状态

```css
.cs-ranking-table--top10 tbody tr:hover {
  background: var(--cs-color-table-row-hover-bg);
}

.cs-ranking-table--top10 tbody tr[aria-selected="true"] {
  background: var(--cs-color-table-row-selected-bg);
  box-shadow: inset 2px 0 0 var(--cs-color-brand-accent);
}
```

规则：

1. hover 只改变行背景，不改变数字涨跌色。
2. selected 使用品牌金竖线或弱背景，不使用红绿。
3. 排名、股票、换手率、量比、成交量、成交额保持中性色。
4. 最新价和涨跌幅仍按红涨绿跌。
5. 平盘使用白色或灰白色，不使用红绿。

### 11.6 数字格式规则

| 字段 | 格式示例 |
|---|---|
| 最新价 | `12.34` |
| 涨跌幅 | `+3.21%` / `-2.18%` / `0.00%` |
| 换手率 | `7.35%` |
| 量比 | `1.82` |
| 成交量 | `128.4万手` / `1.26亿股`，按 API displayText 优先 |
| 成交额 | `8.42亿` / `1264万`，按 API displayText 优先 |

---

## 12. Review v2 / v3 / v4：涨跌停统计与分布 2×2 区域

> 本节保留 Review v2 确认的 2×2 大结构，保留 Review v3 确认的“涨停板块分布 + 领涨股 + 涨停表现”业务含义；本轮 Review v4 仅将“领涨股”和“涨停表现”两个分离小模块合并为“领涨股涨停表现”行式结构。本节不修改连板天梯，不修改其它模块。

### 12.1 2×2 结构

涨跌停统计与分布区域保持 2×2 网格：

```text
┌──────────────────────────────┬─────────────────────────────────────────┐
│ 左上：8 个统计卡片            │ 右上：今日涨停板块分布｜领涨股涨停表现 │
├──────────────────────────────┼─────────────────────────────────────────┤
│ 左下：历史涨跌停组合柱状图    │ 右下：昨日涨停板块分布｜领涨股涨停表现 │
└──────────────────────────────┴─────────────────────────────────────────┘
```

### 12.2 布局 Token

```css
:root {
  --cs-limit-dist-grid-gap: 12px;
  --cs-limit-dist-grid-row-min-height: 214px;
  --cs-limit-dist-panel-padding: 12px;

  --cs-limit-stat-card-count: 8;
  --cs-limit-stat-card-height: 58px;
  --cs-limit-stat-card-gap: 8px;
  --cs-limit-stat-card-title-size: 11px;
  --cs-limit-stat-card-value-size: 20px;
  --cs-limit-stat-card-unit-size: 11px;

  --cs-limit-history-chart-height: 186px;
  --cs-limit-history-chart-min-height: 176px;
  --cs-limit-history-chart-padding-top: 10px;
  --cs-limit-history-chart-padding-bottom: 22px;

  --cs-limit-day-label-height: 22px;
  --cs-limit-day-label-padding-x: 8px;
  --cs-limit-day-label-font-size: 11px;

  /* Review v3/v4: 涨停板块分布 + 领涨股涨停表现结构 */
  --cs-limit-leader-panel-column-gap: 10px;
  --cs-limit-leader-panel-column-title-height: 22px;
  --cs-limit-leader-panel-column-title-size: 12px;
  --cs-limit-leader-panel-row-height: 26px;
  --cs-limit-leader-panel-row-gap: 6px;
  --cs-limit-leader-panel-bar-height: 8px;
  --cs-limit-leader-panel-bar-radius: 999px;
  --cs-limit-leader-stock-code-size: 10px;
  --cs-limit-performance-tag-height: 20px;
  --cs-limit-performance-tag-padding-x: 7px;
  --cs-limit-performance-tag-font-size: 11px;

  /* Review v4: 领涨股涨停表现行式结构 */
  --cs-limit-leader-performance-row-height: 32px;
  --cs-limit-leader-performance-row-gap: 6px;
  --cs-limit-leader-performance-row-padding-x: 6px;
  --cs-limit-leader-performance-rank-width: 20px;
  --cs-limit-leader-performance-price-width: 52px;
  --cs-limit-leader-performance-pct-width: 58px;
  --cs-limit-leader-performance-meta-size: 10px;
  --cs-limit-leader-performance-tag-gap: 4px;
}
```

### 12.3 推荐 CSS

```css
.cs-limit-distribution-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  grid-template-rows: repeat(2, minmax(var(--cs-limit-dist-grid-row-min-height), auto));
  gap: var(--cs-limit-dist-grid-gap);
}

.cs-limit-distribution-cell {
  padding: var(--cs-limit-dist-panel-padding);
  background: var(--cs-color-surface-card);
  border: 1px solid var(--cs-color-border-subtle);
  border-radius: var(--cs-radius-card);
}

.cs-limit-stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  grid-template-rows: repeat(2, var(--cs-limit-stat-card-height));
  gap: var(--cs-limit-stat-card-gap);
}
```

### 12.4 左上：8 个统计卡片

建议 8 个统计卡片：

1. 涨停家数；
2. 跌停家数；
3. 炸板家数；
4. 封板率；
5. 连板家数；
6. 最高连板；
7. 天地板；
8. 地天板。

| 项目 | 规则 |
|---|---|
| 排列 | 4 列 × 2 行 |
| 卡片高度 | 58px |
| 卡片间距 | 8px |
| 标题字号 | 11px |
| 主数字字号 | 20px |
| 内边距 | 8px |
| 背景 | `--cs-color-surface-panel-subtle` |
| 涨停 / 连板 | 红色或品牌金；涨停主色为红 |
| 跌停 | 绿色 |
| 炸板 | 警示色 / 中性警示色，不使用红绿 |
| 封板率 | 默认主文字，异常低时可警示色 |

### 12.5 右上 / 右下：涨停板块分布｜领涨股涨停表现

Review v4 后，今日和昨日两个结构块使用同一套视觉规则：

```text
涨停板块分布 ｜ 领涨股涨停表现
```

右上用于今日数据，右下用于昨日数据。两者只是数据日期不同，视觉规则、交互规则、Token 完全一致。

#### 12.5.1 双列容器布局

“领涨股”和“涨停表现”不再拆成两个视觉小模块，而是在同一行内打通展示。

```css
.cs-limit-sector-leader-panel {
  display: grid;
  grid-template-columns: minmax(120px, 0.95fr) minmax(240px, 1.55fr);
  gap: var(--cs-limit-leader-panel-column-gap);
  min-height: 0;
}

.cs-limit-sector-leader-column {
  min-width: 0;
}

.cs-limit-sector-leader-title {
  height: var(--cs-limit-leader-panel-column-title-height);
  font-size: var(--cs-limit-leader-panel-column-title-size);
  font-weight: var(--cs-font-weight-semibold);
  color: var(--cs-color-text-secondary);
}
```

| 列 | 宽度建议 | 说明 |
|---|---:|---|
| 涨停板块分布 | `0.95fr` | 展示条形分布、板块名、涨停数量 |
| 领涨股涨停表现 | `1.55fr` | 每行一只股票，股票信息与涨停表现必须在同一行展示 |

#### 12.5.2 列标题样式

| 项目 | 规则 |
|---|---|
| 标题文字 | `涨停板块分布`、`领涨股涨停表现` 固定显示 |
| 字号 | 12px |
| 字重 | 600 |
| 颜色 | `--cs-color-text-secondary` |
| 高度 | 22px |
| 下边距 | 6px |
| 分隔 | 可使用弱分割线，不使用红绿 |

#### 12.5.3 涨停板块条形分布样式

```css
.cs-limit-sector-bar-row {
  display: grid;
  grid-template-columns: minmax(56px, 1fr) minmax(56px, 1.2fr) auto;
  align-items: center;
  gap: 6px;
  min-height: var(--cs-limit-leader-panel-row-height);
  padding: 2px 4px;
  border-radius: var(--cs-radius-sm);
  cursor: pointer;
}

.cs-limit-sector-bar-track {
  height: var(--cs-limit-leader-panel-bar-height);
  border-radius: var(--cs-limit-leader-panel-bar-radius);
  background: rgba(148, 163, 184, 0.12);
  overflow: hidden;
}

.cs-limit-sector-bar-fill {
  height: 100%;
  border-radius: var(--cs-limit-leader-panel-bar-radius);
  background: var(--cs-color-market-up);
}
```

| 元素 | 规则 |
|---|---|
| 板块名称 | 主文字或次级文字，超出省略 |
| 涨停数量 | 使用上涨红；格式如 `12`、`9` |
| 条形背景 | 弱灰背景 |
| 条形填充 | 上涨红，表达涨停数量集中度 |
| 当前选中板块 | 品牌金弱背景 + 品牌金边框，不能用红色选中态 |
| hover | 背景轻微提亮，板块名称变主文字 |
| active | 轻微压暗，不改变数据颜色 |

#### 12.5.4 领涨股涨停表现行式结构

模块标题为：`领涨股涨停表现`。

结构规则：

1. 每一行是一只股票。
2. 股票信息和涨停表现必须在同一行内打通展示。
3. 最多展示 3 行。
4. 超过 3 只时，可显示“更多”入口或进入详情页。
5. 今日和昨日两个区域都复用同一套视觉规则。
6. 不使用用户草图里的残留数字。

```css
.cs-limit-leader-performance-list {
  display: grid;
  gap: var(--cs-limit-leader-performance-row-gap);
}

.cs-limit-leader-performance-row {
  display: grid;
  grid-template-columns:
    var(--cs-limit-leader-performance-rank-width)
    minmax(0, 1.2fr)
    var(--cs-limit-leader-performance-price-width)
    var(--cs-limit-leader-performance-pct-width)
    auto;
  align-items: center;
  min-height: var(--cs-limit-leader-performance-row-height);
  padding: 0 var(--cs-limit-leader-performance-row-padding-x);
  border-radius: var(--cs-radius-sm);
  background: transparent;
  border: 1px solid transparent;
  cursor: pointer;
}

.cs-limit-leader-performance-row:hover {
  background: var(--cs-color-surface-card-hover);
  border-color: var(--cs-color-border-hover);
}

.cs-limit-leader-performance-row.is-active,
.cs-limit-leader-performance-row.is-selected {
  background: var(--cs-color-brand-accent-bg);
  border-color: var(--cs-color-brand-accent-border);
}
```

| 元素 | 规则 |
|---|---|
| 行高 | 32px，紧凑但保证股票名和标签可读 |
| 行间距 | 6px |
| 行 hover | 整行高亮，不只高亮股票名或标签 |
| 行 active / selected | 品牌金弱背景 + 品牌金边框，不使用红绿选中态 |
| 点击 | 点击股票行进入个股详情 |

#### 12.5.5 行内字段样式

```css
.cs-limit-leader-rank {
  color: var(--cs-color-text-muted);
  font-family: var(--cs-font-family-number);
  font-size: var(--cs-font-size-11);
}

.cs-limit-leader-stock-main {
  min-width: 0;
}

.cs-limit-leader-stock-name {
  color: var(--cs-color-text-primary);
  font-size: var(--cs-font-size-12);
  font-weight: var(--cs-font-weight-semibold);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.cs-limit-leader-stock-code {
  color: var(--cs-color-text-muted);
  font-size: var(--cs-limit-leader-performance-meta-size);
  font-family: var(--cs-font-family-number);
}

.cs-limit-leader-price,
.cs-limit-leader-pct {
  font-family: var(--cs-font-family-number);
  font-variant-numeric: tabular-nums;
  color: var(--cs-color-market-up);
  text-align: right;
}
```

| 字段 | 视觉规则 |
|---|---|
| 排名 | 弱文字，等宽数字，宽度固定 |
| 股票名称 | 主文字，12px，字重 600，超出省略 |
| 股票代码 | 弱文字，10px，等宽数字 |
| 最新价 | 方向色；涨停股通常为红色，平盘灰白 |
| 涨跌幅 | 上涨红，必须带 `+` 号；如 `+10.01%`、`+20.00%` |
| 封单金额 | 可选事实，弱文字或等宽数字，不抢主信息 |
| 首次封板时间 | 可选事实，弱文字，格式如 `09:42` |

#### 12.5.6 连板标签与近期涨停表现标签

```css
.cs-limit-streak-tag,
.cs-limit-recent-tag {
  display: inline-flex;
  align-items: center;
  height: var(--cs-limit-performance-tag-height);
  padding: 0 var(--cs-limit-performance-tag-padding-x);
  border-radius: var(--cs-radius-pill);
  font-size: var(--cs-limit-performance-tag-font-size);
  white-space: nowrap;
}

.cs-limit-streak-tag {
  background: var(--cs-color-market-up-bg);
  color: var(--cs-color-market-up);
  border: 1px solid var(--cs-color-market-up-border);
}

.cs-limit-recent-tag {
  background: var(--cs-color-brand-accent-bg);
  color: var(--cs-color-brand-accent);
  border: 1px solid var(--cs-color-brand-accent-border);
}
```

| 标签 | 规则 |
|---|---|
| `首板` | 红色弱背景 + 红色文字 |
| `2连板` / `3连板` / `N连板` | 红色弱背景；高连板可叠加品牌金强调 |
| `7天5板` / `2天2板` / `1天1板` | 品牌金弱背景，表达表现强度，不表示涨跌方向 |
| 开板次数 | 若展示，使用警示色或弱文字，不使用绿色 |
| 封单金额 | 默认数字色或弱文字，可在 Tooltip 中展示完整值 |

#### 12.5.7 Tooltip 样式

Tooltip 复用全局图表 / 数据 Tooltip Token：

```css
.cs-limit-leader-performance-tooltip {
  max-width: 280px;
  padding: 10px 12px;
  background: var(--cs-color-tooltip-bg);
  border: 1px solid var(--cs-color-tooltip-border);
  border-radius: var(--cs-radius-lg);
  box-shadow: var(--cs-shadow-tooltip);
  color: var(--cs-color-text-primary);
  z-index: var(--cs-z-tooltip);
}
```

Tooltip 内容建议：

```text
股票：汇川技术 300124.SZ
板块：机器人
最新价：68.25
涨跌幅：+10.01%
涨停表现：3连板 / 7天5板
首次封板：09:42:16
封单金额：3.20亿
```

规则：

1. 涨停数量和涨跌幅使用上涨红。
2. 股票名称、板块名称使用主文字。
3. 股票代码、时间、开板次数使用次级文字或弱文字。
4. 用户草图中的右侧残留数字不进入设计，不进入 Tooltip，不进入 Mock 数据。

### 12.6 左下：历史涨跌停组合柱状图

| 项目 | 规则 |
|---|---|
| 图表高度 | 176–186px |
| 柱组 | 同一日期下涨停柱 + 跌停柱 |
| 涨停柱 | 红色 |
| 跌停柱 | 绿色 |
| X 轴 | 交易日期 |
| Y 轴 | 数量 |
| Tooltip | 日期、涨停数、跌停数 |
| RangeSwitch | 支持 1个月 / 3个月 |
| 炸板 | 不进入组合柱图 |

### 12.7 今日 / 昨日标签样式

```css
.cs-day-label {
  height: var(--cs-limit-day-label-height);
  padding: 0 var(--cs-limit-day-label-padding-x);
  border-radius: var(--cs-radius-pill);
  font-size: var(--cs-limit-day-label-font-size);
  background: var(--cs-color-brand-accent-bg);
  border: 1px solid var(--cs-color-brand-accent-border);
  color: var(--cs-color-brand-accent);
}
```

规则：

1. `今日` 和 `昨日` 是时间标签，不表达涨跌方向。
2. 标签使用品牌金或中性色，不使用红绿。
3. 若昨日数据不可用，使用 `--cs-color-status-missing`。

## 13. Review v2：板块速览 4列×2行榜单矩阵 + 右侧跨两行 5×4 热力图

> 本节是 v0.2.5 新增规则，只影响“板块速览”模块。

### 13.1 总体结构

板块速览必须改为：左侧 4 列 × 2 行榜单矩阵，右侧板块热力图独立跨两行。

```text
┌────────────┬────────────┬────────────┬────────────┬──────────────────┐
│ 行业涨幅前五 │ 概念涨幅前五 │ 地域涨幅前五 │ 资金流入前五 │                  │
│ Top5       │ Top5       │ Top5       │ Top5       │                  │
├────────────┼────────────┼────────────┼────────────┤ 板块热力图 5×4   │
│ 行业跌幅前五 │ 概念跌幅前五 │ 地域跌幅前五 │ 资金流出前五 │                  │
│ Top5       │ Top5       │ Top5       │ Top5       │                  │
└────────────┴────────────┴────────────┴────────────┴──────────────────┘
```

热力图必须在右侧独立占两行高度，不是只放在第一行。

### 13.2 布局 Token

```css
:root {
  --cs-sector-overview-gap: 12px;
  --cs-sector-overview-list-columns: 4;
  --cs-sector-overview-list-rows: 2;
  --cs-sector-overview-heatmap-width: 360px;
  --cs-sector-overview-heatmap-min-width: 320px;
  --cs-sector-overview-row-min-height: 170px;
  --cs-sector-rank-block-padding: 10px;
  --cs-sector-rank-block-title-height: 24px;
  --cs-sector-rank-block-title-font-size: 12px;
  --cs-sector-rank-row-height: 24px;
  --cs-sector-rank-row-font-size: 12px;
  --cs-sector-rank-row-gap: 4px;

  --cs-sector-heatmap-rows: 5;
  --cs-sector-heatmap-columns: 4;
  --cs-sector-heatmap-cell-gap: 6px;
  --cs-sector-heatmap-cell-min-height: 46px;
  --cs-sector-heatmap-cell-padding: 8px;
  --cs-sector-heatmap-cell-radius: 6px;
  --cs-sector-heatmap-title-height: 24px;
}
```

### 13.3 推荐 CSS

```css
.cs-sector-overview-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr)) minmax(
    var(--cs-sector-overview-heatmap-min-width),
    var(--cs-sector-overview-heatmap-width)
  );
  grid-template-rows: repeat(2, minmax(var(--cs-sector-overview-row-min-height), auto));
  gap: var(--cs-sector-overview-gap);
}

.cs-sector-heatmap-panel {
  grid-column: 5;
  grid-row: 1 / span 2;
}

.cs-sector-rank-block {
  padding: var(--cs-sector-rank-block-padding);
  background: var(--cs-color-surface-card);
  border: 1px solid var(--cs-color-border-subtle);
  border-radius: var(--cs-radius-card);
}

.cs-sector-heatmap-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  grid-template-rows: repeat(5, minmax(var(--cs-sector-heatmap-cell-min-height), 1fr));
  gap: var(--cs-sector-heatmap-cell-gap);
}
```

### 13.4 左侧 8 个榜单块

榜单块分别为：

第一行：

1. 行业涨幅前五；
2. 概念涨幅前五；
3. 地域涨幅前五；
4. 资金流入前五。

第二行：

1. 行业跌幅前五；
2. 概念跌幅前五；
3. 地域跌幅前五；
4. 资金流出前五。

| 项目 | 规则 |
|---|---|
| 榜单块标题高度 | 24px |
| 标题字号 | 12px，字重 600 |
| Top5 行高 | 24px |
| Top5 行字号 | 12px |
| 榜单块内边距 | 10px |
| 榜单块间距 | 12px |
| 排名列 | 弱文字，最小宽度 20px |
| 板块名称 | 主文字，超出省略 |
| 涨跌幅 | 红涨绿跌，平盘灰白 |
| 资金净流入 / 流出 | 净流入红，净流出绿 |
| hover | 背景提亮，边框保持克制 |

### 13.5 右侧板块热力图 5×4

| 项目 | 规则 |
|---|---|
| 位置 | 右侧独立区域，跨两行 |
| 内部结构 | 5 行 × 4 列，共 20 个格子 |
| 格子间距 | 6px |
| 格子最小高度 | 46px |
| 格子内边距 | 8px |
| 格子圆角 | 6px |
| 颜色 | 红涨绿跌，平盘灰白 |
| 面积 | v1.2 Showcase 中格子尺寸可以一致；如后续要表达成交额权重，需另行确认 |
| hover | 边框品牌金，亮度轻微提升 |
| Tooltip | 展示板块名称、板块类型、涨跌幅、成交额、资金净流入、上涨/下跌成分股数量 |

### 13.6 热力图颜色分档

```css
:root,
[data-theme="dark"] {
  --cs-sector-heat-up-1: rgba(255, 77, 90, 0.18);
  --cs-sector-heat-up-2: rgba(255, 77, 90, 0.32);
  --cs-sector-heat-up-3: rgba(255, 77, 90, 0.52);
  --cs-sector-heat-up-4: rgba(255, 77, 90, 0.74);

  --cs-sector-heat-down-1: rgba(21, 199, 132, 0.18);
  --cs-sector-heat-down-2: rgba(21, 199, 132, 0.32);
  --cs-sector-heat-down-3: rgba(21, 199, 132, 0.52);
  --cs-sector-heat-down-4: rgba(21, 199, 132, 0.74);

  --cs-sector-heat-flat: rgba(216, 222, 232, 0.12);
  --cs-sector-heat-missing: rgba(100, 116, 139, 0.10);
}
```

分档规则：

| 区间 | 颜色 |
|---|---|
| `pctChg >= +7%` | 强红 `--cs-sector-heat-up-4` |
| `+3% <= pctChg < +7%` | 中强红 `--cs-sector-heat-up-3` |
| `0 < pctChg < +3%` | 弱红 / 中红 |
| `pctChg = 0` | 灰白 |
| `-3% < pctChg < 0` | 弱绿 / 中绿 |
| `-7% < pctChg <= -3%` | 中强绿 |
| `pctChg <= -7%` | 强绿 `--cs-sector-heat-down-4` |

### 13.7 热力图 hover 与 Tooltip

```css
.cs-sector-heatmap-cell:hover {
  border-color: var(--cs-color-border-hover);
  filter: brightness(1.08);
}

.cs-sector-heatmap-tooltip {
  max-width: 260px;
  padding: 10px 12px;
  background: var(--cs-color-tooltip-bg);
  border: 1px solid var(--cs-color-tooltip-border);
  color: var(--cs-color-tooltip-text);
  border-radius: var(--cs-radius-lg);
  box-shadow: var(--cs-shadow-tooltip);
  z-index: var(--cs-z-tooltip);
}
```

Tooltip 字段建议：

```text
板块名称
板块类型：行业 / 概念 / 地域
涨跌幅：+3.24%
成交额：xxx 亿
资金净流入：+xx 亿
上涨成分股：xx
下跌成分股：xx
```

---

## 14. Review v3 / v4：大盘资金流向单型资金净流向饼图与左右结构

> 本节只影响“大盘资金流向”模块内部结构，不改变模块在页面中的位置，不改变页面整体布局顺序，不修改右侧榜单速览、成交额总览、市场风格等未被 Review v4 点名区域。Review v4 仅修订饼图标注、饼块占比文字和中心留白规则；趋势图 0 轴、Tooltip、坐标线沿用既有规则。

### 14.1 模块内部结构

大盘资金流向模块内部保持左饼图、右趋势图结构：

```text
┌──────────────────────────────┬──────────────────────────────────┐
│ 左：单型资金净流向饼图        │ 右：历史资金流向趋势图            │
│ 饼块白色占比 + 外部折线标注   │ 净流入为正，净流出为负，0轴居中   │
└──────────────────────────────┴──────────────────────────────────┘
```

禁止：

1. 不显示两个饼图。
2. 不使用“流入结构 / 流出结构”这种会误导为真实流入额、真实流出额的标题。
3. 不为了加入饼图而改变整个大盘资金流向模块的外部高度。
4. 不因此改动右侧榜单速览或其它模块。
5. 饼图中心不得显示“净额结构”、`absAmount` 或任何英文调试字段。

### 14.2 单型资金净流向饼图 Token

```css
:root {
  --cs-moneyflow-split-gap: 14px;
  --cs-moneyflow-pie-panel-min-width: 220px;
  --cs-moneyflow-trend-panel-min-width: 360px;
  --cs-moneyflow-pie-size: 138px;
  --cs-moneyflow-pie-size-compact: 122px;
  --cs-moneyflow-pie-inner-radius-ratio: 0.48;
  --cs-moneyflow-pie-slice-stroke: #0B1220;
  --cs-moneyflow-pie-slice-stroke-width: 1.5px;
  --cs-moneyflow-pie-slice-hover-offset: 3px;

  /* Review v4: 饼块上白色占比文字 */
  --cs-moneyflow-pie-percent-color: #FFFFFF;
  --cs-moneyflow-pie-percent-font-size: 11px;
  --cs-moneyflow-pie-percent-font-weight: 700;
  --cs-moneyflow-pie-percent-shadow: 0 1px 2px rgba(0, 0, 0, 0.55);

  /* Review v4: 外部折线标注 */
  --cs-moneyflow-pie-callout-line-color: rgba(203, 213, 225, 0.46);
  --cs-moneyflow-pie-callout-line-width: 1px;
  --cs-moneyflow-pie-callout-dot-size: 3px;
  --cs-moneyflow-pie-callout-label-size: 11px;
  --cs-moneyflow-pie-callout-value-size: 12px;
  --cs-moneyflow-pie-callout-gap: 6px;
  --cs-moneyflow-pie-callout-max-width: 82px;

  --cs-moneyflow-pie-tooltip-max-width: 260px;
}
```

### 14.3 左右布局规则

| 项目 | 规则 |
|---|---|
| 左右比例 | 左侧饼图区域 `minmax(220px, 0.8fr)`；右侧趋势图区域 `minmax(360px, 1.4fr)` |
| 左右间距 | `--cs-moneyflow-split-gap: 14px` |
| 饼图区域最小宽度 | 220px |
| 趋势图区域最小宽度 | 360px |
| 模块高度 | 尽量沿用现有大盘资金流向模块高度，不因饼图新增而整体拉高 |
| 内部密度 | 饼图、Callout、趋势图均使用紧凑排布；顶部标题区不增加额外说明文字 |
| 趋势图规则 | 继续沿用第 8.7 节：白色主趋势线、0 轴居中、Tooltip 正红负绿、单位亿元 |

推荐 CSS：

```css
.cs-moneyflow-body {
  display: grid;
  grid-template-columns: minmax(var(--cs-moneyflow-pie-panel-min-width), 0.8fr) minmax(var(--cs-moneyflow-trend-panel-min-width), 1.4fr);
  gap: var(--cs-moneyflow-split-gap);
  align-items: stretch;
  min-height: 0;
}

.cs-moneyflow-pie-panel {
  min-width: 0;
  display: grid;
  place-items: center;
  position: relative;
  overflow: visible;
}

.cs-moneyflow-trend-panel {
  min-width: 0;
}
```

### 14.4 饼图面积规则

饼图表示四类单型：

1. 超大单；
2. 大单；
3. 中单；
4. 小单。

每个饼块的面积使用对应单型净额的绝对值决定占比：

```text
abs(buy_elg_amount)
abs(buy_lg_amount)
abs(buy_md_amount)
abs(buy_sm_amount)
```

若 API 已返回 `absAmount`，前端优先使用 `absAmount`；否则前端按 `Math.abs(netAmount)` 计算仅用于图形面积。

### 14.5 饼图颜色规则

| 单型净额 | 饼块颜色 | 说明 |
|---:|---|---|
| `> 0` | `--cs-color-market-up` | 净流入，红色 |
| `< 0` | `--cs-color-market-down` | 净流出，绿色 |
| `= 0` | `--cs-color-market-flat-soft` | 零值，灰白色 |

注意：

1. 颜色表达的是该单型净额正负，不表达单型类别。
2. 同一个饼图中可以同时出现红色块、绿色块、灰白色块。
3. 不得用固定颜色分别代表“超大单 / 大单 / 中单 / 小单”，否则会和红涨绿跌语义冲突。

### 14.6 饼图内环 / 外环样式

如果使用环形图：

| 项目 | 规则 |
|---|---|
| 外径 | `--cs-moneyflow-pie-size`，紧凑状态使用 `--cs-moneyflow-pie-size-compact` |
| 内环比例 | `--cs-moneyflow-pie-inner-radius-ratio: 0.48` |
| 分隔线 | 使用 `--cs-moneyflow-pie-slice-stroke`，宽度 `--cs-moneyflow-pie-slice-stroke-width` |
| hover | 饼块轻微外扩 `--cs-moneyflow-pie-slice-hover-offset`，不改变颜色语义 |
| 中心 | 留空；不显示“净额结构”、`absAmount`、总净额或英文调试字段 |

### 14.7 饼块上的白色占比文字

占比必须显示在对应饼块上。

```css
.cs-moneyflow-pie-percent-label {
  fill: var(--cs-moneyflow-pie-percent-color);
  color: var(--cs-moneyflow-pie-percent-color);
  font-size: var(--cs-moneyflow-pie-percent-font-size);
  font-weight: var(--cs-moneyflow-pie-percent-font-weight);
  text-shadow: var(--cs-moneyflow-pie-percent-shadow);
  pointer-events: none;
}
```

规则：

1. 占比文字直接放在饼块上。
2. 占比文字必须是白色。
3. 占比表示该饼块在整个饼图中的面积占比。
4. 占比不得放在图例里。
5. 占比不得放在外部折线标注里。
6. 占比不得放在饼图中心。
7. 当饼块过小导致文字无法放入时，可隐藏该饼块占比文字，但仍需在外部折线标注和 Tooltip 中展示单型名称与净额。

### 14.8 外部折线标注 Callout

每个饼块需要外部折线标注。标注内容为：

```text
单型名称 + 净额
```

示例：

```text
超大单 +12.3亿
大单 -5.2亿
中单 +3.1亿
小单 -8.7亿
```

```css
.cs-moneyflow-pie-callout-line {
  stroke: var(--cs-moneyflow-pie-callout-line-color);
  stroke-width: var(--cs-moneyflow-pie-callout-line-width);
  fill: none;
}

.cs-moneyflow-pie-callout-dot {
  width: var(--cs-moneyflow-pie-callout-dot-size);
  height: var(--cs-moneyflow-pie-callout-dot-size);
  background: var(--cs-moneyflow-pie-callout-line-color);
  border-radius: 999px;
}

.cs-moneyflow-pie-callout-label {
  max-width: var(--cs-moneyflow-pie-callout-max-width);
  font-size: var(--cs-moneyflow-pie-callout-label-size);
  color: var(--cs-color-text-secondary);
  white-space: nowrap;
}

.cs-moneyflow-pie-callout-value {
  font-size: var(--cs-moneyflow-pie-callout-value-size);
  font-family: var(--cs-font-family-number);
  font-variant-numeric: tabular-nums;
}
```

| 标注元素 | 规则 |
|---|---|
| 折线颜色 | 默认灰白半透明，不使用红绿作为线色，避免干扰饼块语义 |
| 折线粗细 | 1px |
| 转折点 | 可使用小圆点，尺寸 3px；不做发光 |
| 文字位置 | 可在折线上方或下方，根据象限自动排布 |
| 正值文字 | 红色 |
| 负值文字 | 绿色 |
| 零值文字 | 灰白色 |
| 遮挡规则 | 不得遮挡饼块上的白色占比文字 |
| 趋势图边界 | 不得占用右侧趋势图区域 |

### 14.9 小空间压缩策略

当饼图区域空间不足时：

1. 饼图尺寸可降为 `--cs-moneyflow-pie-size-compact`。
2. 外部 Callout 可缩短折线长度。
3. Callout 文案可换行：第一行单型名称，第二行净额。
4. 小于 6% 的饼块可隐藏饼块内占比文字，但 Tooltip 必须保留完整信息。
5. 不允许把占比挪到图例、中心或外部折线标注中。
6. 不允许隐藏整个饼图或趋势图任意一侧。
7. 不允许将左右结构改为上下结构，除非进入移动端适配范围；P0 桌面 Showcase 不做该降级。

### 14.10 饼图 Tooltip

Tooltip 复用全局 Tooltip，但必须明确资金正负色：

```css
.cs-moneyflow-pie-tooltip {
  max-width: var(--cs-moneyflow-pie-tooltip-max-width);
  padding: 10px 12px;
  background: var(--cs-color-tooltip-bg);
  border: 1px solid var(--cs-color-tooltip-border);
  border-radius: var(--cs-radius-lg);
  box-shadow: var(--cs-shadow-tooltip);
  color: var(--cs-color-text-primary);
  z-index: var(--cs-z-tooltip);
}
```

Tooltip 内容示例：

```text
超大单
净流入：+12.3 亿
结构占比：42.5%
源字段：buy_elg_amount
```

规则：

1. 正值使用上涨红。
2. 负值使用下跌绿。
3. 零值使用灰白色。
4. 占比使用中性色；占比口径由 API 明确，前端不自行解释为真实流入 / 流出占比。
5. 字段说明可进入 HelpTooltip，不直接占用模块正文空间。

## 15. 市场总览专用组件视觉规则

### 15.1 TopMarketBar（本轮未修改）

TopMarketBar 用于承载产品标识、乾坤行情展开菜单、其它系统折叠入口、指数条、时间、开闭市状态、数据状态和用户入口。

本轮 Review v4 禁止主动修改该区域。现有 Token 和视觉规则继续沿用。

### 15.2 Breadcrumb（本轮未修改）

固定表达：

```text
财势乾坤 / 乾坤行情 / 市场总览
```

本轮 Review v4 禁止主动修改该区域。

### 15.3 PageHeader（本轮未修改）

已确认高度：56px。本轮 Review v4 禁止主动修改该区域。

### 15.4 ShortcutBar（本轮未修改）

ShortcutBar 是轻量快捷入口，不是大卡片入口墙。本轮 Review v4 禁止主动修改该区域。

### 15.5 MarketSummaryIndexSplit（Review v2 已确认）

对应“今日市场客观总结 + 主要指数”左右结构。必须使用第 10 章 Token。

组件要求：

- `MarketSummaryPanel`：左侧 50%。
- `MajorIndexPanel`：右侧 50%。
- `MarketFactCard`：5 个事实卡。
- `MarketSummaryNoteCard`：说明性文字卡。
- `IndexCard--split`：半宽紧凑指数卡。

### 15.6 RankingTableTop10（Review v2 已确认）

对应榜单速览 Top10 表格。必须使用第 11 章 Token。

组件要求：

- 固定列顺序；
- Top10；
- 半宽容器高密度；
- 最新价、涨跌幅红涨绿跌；
- 换手率、量比、成交量、成交额中性色。

### 15.7 LimitDistributionGrid2x2（Review v2 / v3 已确认）

对应涨跌停统计与分布 2×2 区域。必须使用第 12 章 Token。

组件要求：

- 左上 8 个统计卡；
- 右上今日结构；
- 左下历史组合柱图；
- 右下昨日结构；
- 今日 / 昨日标签不使用红绿。

### 15.8 SectorOverviewMatrixHeatmap（Review v2 已确认）

对应板块速览 4 列 × 2 行榜单矩阵 + 右侧跨两行 5×4 热力图。必须使用第 13 章 Token。

组件要求：

- 左侧 8 个榜单块；
- 每个榜单块 Top5；
- 右侧热力图跨两行；
- 热力图内部 5×4；
- 热力图红涨绿跌，平盘灰白。

### 15.9 LimitUpSectorLeaderPanel / LimitUpLeaderPerformanceTable（Review v3 / v4 修订）

对应涨跌停统计与分布右上 / 右下结构：`涨停板块分布｜领涨股涨停表现`。必须使用第 12 章 Token。Review v4 要求“领涨股”和“涨停表现”合并为行式结构，每行一只股票并同一行展示涨停表现。

组件要求：

- `LimitUpSectorBars`：左列涨停板块条形分布；
- `LimitUpLeaderStockList`：中列领涨股列表；
- `LimitUpPerformanceList`：右列涨停表现标签；
- `LimitUpLeaderTooltip`：展示板块、领涨股、涨停表现、封板时间、开板次数等信息；
- 当前选中板块和领涨股使用品牌金选中态，不使用红绿选中态；
- 用户草图中的右侧残留数字不进入组件。

### 15.10 MoneyFlowNetStructurePanel / OrderSizeNetPieChartWithCallout（Review v3 / v4 修订）

对应大盘资金流向模块内部左饼图 + 右趋势图结构。必须使用第 14 章 Token。

组件要求：

- `MoneyFlowNetStructurePanel`：承载左侧饼图与右侧趋势图；
- `OrderSizeNetPieChartWithCallout`：展示超大单 / 大单 / 中单 / 小单的单型资金净流向结构，并支持饼块白色占比文字与外部折线标注；
- `OrderSizeNetPieLegend`：展示单型名称、净额与正负颜色；
- `MoneyFlowPieTooltip`：展示单型、净额、结构占比与字段口径；
- 饼图只显示一个，不显示流入 / 流出两个饼图；
- 饼块面积按净额绝对值计算；
- 正值红色、负值绿色、零值灰白色。

---

## 16. 状态规范

> 本轮 Review v3 不修改全局状态规范。本节保留既有规则。

### 16.1 Loading

- 首次加载使用骨架屏。
- 自动刷新时保留旧数据，显示刷新中状态，不整页闪烁。
- 表格、图表、热力图、2×2 区块均应支持局部 loading。

### 16.2 Empty

| 空态 | 文案 |
|---|---|
| 非交易日 | 当前为非交易日，展示最近一个交易日数据 |
| 数据未生成 | 数据正在生成，请稍后刷新 |
| 单模块无数据 | 当前模块暂无数据 |
| 无权限 | 登录后查看个人入口状态 |

### 16.3 Error

异常类型：

- 网络异常；
- 服务异常；
- 数据源不可用；
- 数据延迟；
- 字段缺失；
- 部分模块计算失败；
- 自动刷新失败。

系统异常使用橙色，不使用行情红。

### 16.4 Selected

选中态统一使用品牌金。

```css
.cs-selected {
  color: var(--cs-color-brand-accent);
  background: var(--cs-color-brand-accent-bg);
  border-color: var(--cs-color-brand-accent-border);
}
```

---

## 17. 前端落地建议

### 17.1 推荐样式文件

```text
src/styles/
├── design-tokens.css
├── theme-dark.css
├── theme-light.css
├── market-colors.css
├── chart-tokens.css
└── market-overview-layout.css
```

P0 也可以先合并为：

```text
src/styles/design-tokens.css
```

### 17.2 行情方向工具函数

```ts
export type MarketTrend = "up" | "down" | "flat";

export function getMarketTrend(value: number): MarketTrend {
  if (value > 0) return "up";
  if (value < 0) return "down";
  return "flat";
}

export function getMarketTrendClass(trend: MarketTrend): string {
  if (trend === "up") return "cs-market-up";
  if (trend === "down") return "cs-market-down";
  return "cs-market-flat";
}
```

### 17.3 Mock 数据校验

```ts
export interface MarketNumber {
  value: number;
  change?: number;
  pctChg?: number;
  trend: MarketTrend;
}

export function assertMarketTrend(item: MarketNumber) {
  if (item.pctChg == null) return;

  if (item.pctChg > 0 && item.trend !== "up") {
    throw new Error("pctChg > 0 must use trend=up");
  }

  if (item.pctChg < 0 && item.trend !== "down") {
    throw new Error("pctChg < 0 must use trend=down");
  }

  if (item.pctChg === 0 && item.trend !== "flat") {
    throw new Error("pctChg = 0 must use trend=flat");
  }
}
```

### 17.4 禁止硬编码颜色

禁止：

```tsx
<span style={{ color: "green" }}>+1.23%</span>
```

必须：

```tsx
<span className={getMarketTrendClass(item.trend)}>
  {formatPct(item.pctChg)}
</span>
```

---

## 18. 本轮 Review v4 修改摘要

本轮基于 Review v4 只做局部修订，不重做完整视觉体系，不修改 Review v4 未点名区域。

| 区域 | 本轮处理 |
|---|---|
| 涨跌停统计与分布：今日结构 | 将“领涨股”和“涨停表现”合并为“领涨股涨停表现”行式结构 |
| 涨跌停统计与分布：昨日结构 | 与今日区域使用同一套“领涨股涨停表现”行式结构 |
| 大盘资金流向：单型资金净流向饼图 | 补充饼图折线标注、饼块白色占比文字、饼图中心留白 / 禁止中心文字规则 |
| 大盘资金流向：左右结构 | 继续保持左饼图 + 右趋势图；趋势图 0 轴、Tooltip、坐标线沿用既有规则 |

---

## 19. 本轮未修改区域说明

按 Review v4 总控变更单，本轮未修改以下区域：

1. TopMarketBar。
2. Breadcrumb。
3. PageHeader。
4. ShortcutBar。
5. 今日市场客观总结。
6. 主要指数。
7. 涨跌分布。
8. 市场风格。
9. 成交额总览。
10. 榜单速览。
11. 连板天梯。
12. 板块速览。
13. 页面整体主题。
14. 全局字体。
15. 页面整体布局顺序。
16. 路由结构。
17. API 数据模型。
18. 与 Review v4 无关的 Mock 数据结构。

本轮因 Review v4 修改而被动影响的区域：

| 区域 | 原因 | 是否需要产品总控确认 |
|---|---|---|
| 涨跌停统计与分布右上 / 右下内部展示结构 | “领涨股”和“涨停表现”由两个小模块合并为行式单模块 | 否，Review v4 已点名 |
| 大盘资金流向饼图内部标注样式 | 中心文案移除，改为饼块白色占比 + 外部折线标注 | 否，Review v4 已点名 |

---

## 20. 本轮新增或修订 Token 清单

### 20.1 新增 Token

| Token | 用途 |
|---|---|
| `--cs-limit-leader-performance-row-height` | 领涨股涨停表现行高 |
| `--cs-limit-leader-performance-row-gap` | 领涨股涨停表现行间距 |
| `--cs-limit-leader-performance-row-padding-x` | 行式结构横向内边距 |
| `--cs-limit-leader-performance-rank-width` | 排名列宽度 |
| `--cs-limit-leader-performance-price-width` | 最新价列宽度 |
| `--cs-limit-leader-performance-pct-width` | 涨跌幅列宽度 |
| `--cs-limit-leader-performance-meta-size` | 股票代码、封板时间、封单金额等弱化事实字号 |
| `--cs-limit-leader-performance-tag-gap` | 连板标签与近期表现标签间距 |
| `--cs-moneyflow-pie-inner-radius-ratio` | 环形图内环比例 |
| `--cs-moneyflow-pie-slice-stroke` | 饼块分隔线颜色 |
| `--cs-moneyflow-pie-slice-stroke-width` | 饼块分隔线宽度 |
| `--cs-moneyflow-pie-slice-hover-offset` | 饼块 hover 外扩距离 |
| `--cs-moneyflow-pie-percent-color` | 饼块上占比文字颜色，固定白色 |
| `--cs-moneyflow-pie-percent-font-size` | 饼块上占比文字字号 |
| `--cs-moneyflow-pie-percent-font-weight` | 饼块上占比文字字重 |
| `--cs-moneyflow-pie-percent-shadow` | 饼块上占比文字阴影，保证深色图块可读 |
| `--cs-moneyflow-pie-callout-line-color` | 饼图外部折线标注线色 |
| `--cs-moneyflow-pie-callout-line-width` | 折线标注线宽 |
| `--cs-moneyflow-pie-callout-dot-size` | 折线转折点 / 端点小圆点尺寸 |
| `--cs-moneyflow-pie-callout-label-size` | 折线标注单型名称字号 |
| `--cs-moneyflow-pie-callout-value-size` | 折线标注净额字号 |
| `--cs-moneyflow-pie-callout-gap` | 折线标注与饼图 / 文本间距 |
| `--cs-moneyflow-pie-callout-max-width` | 折线标注文案最大宽度 |

### 20.2 修订 Token 使用方式

| Token / 规则 | 修订说明 |
|---|---|
| `--cs-limit-performance-tag-*` | 继续用于连板标签和近期涨停表现标签，但标签必须出现在“领涨股涨停表现”同一行内 |
| `--cs-color-market-up` | 继续用于上涨、净流入、涨停；用于净额为正的饼块、涨停股涨跌幅、连板标签 |
| `--cs-color-market-down` | 继续用于下跌、净流出、跌停；用于净额为负的饼块和饼图标注文字 |
| `--cs-color-market-flat-soft` | 继续用于平盘 / 0 值；用于净额为 0 的饼块 |
| `--cs-color-tooltip-bg` / `--cs-color-tooltip-border` | 复用到领涨股涨停表现 Tooltip 和单型资金饼图 Tooltip |
| `--cs-shadow-tooltip` | 复用到新增 Tooltip |
| 饼图中心规则 | 由 Review v3 可显示中心文案修订为 Review v4 中心留空；不得显示“净额结构”、`absAmount` 或任何调试字段 |

---

## 21. 对 03 组件规范的 Token 映射建议

| 组件 | 应映射 Token / 规则 |
|---|---|
| `LimitUpSectorLeaderPanel` | `--cs-limit-leader-panel-*`；结构为“涨停板块分布｜领涨股涨停表现” |
| `LimitUpSectorBars` | `--cs-limit-leader-panel-bar-*`、`--cs-color-market-up`、`--cs-color-brand-accent-bg` |
| `LimitUpLeaderPerformanceTable` | `--cs-limit-leader-performance-*`；每行一只股票，股票信息与涨停表现同一行展示 |
| `LimitUpStreakTag` | `--cs-limit-performance-tag-*`、`--cs-color-market-up-bg`、`--cs-color-market-up-border` |
| `LimitUpRecentTag` | `--cs-limit-performance-tag-*`、`--cs-color-brand-accent-bg`、`--cs-color-brand-accent-border` |
| `LimitUpLeaderTooltip` | `--cs-color-tooltip-bg`、`--cs-color-tooltip-border`、`--cs-shadow-tooltip` |
| `OrderSizeNetPieChartWithCallout` | `--cs-moneyflow-pie-*`、`--cs-color-market-up/down/flat-soft`、饼块白色占比文字、外部折线标注 |
| `PieCalloutLabel` | `--cs-moneyflow-pie-callout-*`；正值文字红色、负值文字绿色、零值灰白色 |
| `PieSlicePercentLabel` | `--cs-moneyflow-pie-percent-*`；占比文字固定白色并位于饼块上 |
| `MoneyFlowNetStructurePanel` | `--cs-moneyflow-split-gap`、`--cs-moneyflow-pie-panel-min-width`、`--cs-moneyflow-trend-panel-min-width` |
| `MoneyFlowTrendChart` | 继续沿用 `--cs-color-series-fundflow-main`、图表坐标轴、0 轴、Tooltip Token |
| `MoneyFlowPieTooltip` | `--cs-moneyflow-pie-tooltip-max-width`、`--cs-color-tooltip-bg`、`--cs-color-tooltip-border` |

---

## 22. 对 02 `market-overview-v1.3.html` 的视觉约束

1. 页面名称仍为“市场总览”。
2. 页面归属仍为“乾坤行情”。
3. 不得使用固定 SideNav。
4. 不得修改 TopMarketBar、Breadcrumb、PageHeader、ShortcutBar。
5. 不得修改今日市场客观总结、主要指数、涨跌分布、市场风格、成交额总览、榜单速览、连板天梯、板块速览。
6. 涨跌停统计与分布右上必须使用：`今日涨停板块分布｜领涨股涨停表现`。
7. 涨跌停统计与分布右下必须使用：`昨日涨停板块分布｜领涨股涨停表现`。
8. 今日和昨日两个区域必须使用同一套行式结构视觉规则。
9. “领涨股”和“涨停表现”不得做成两个分离独立小模块。
10. 每一行必须是一只股票，股票信息与涨停表现必须在同一行内打通展示。
11. 最多展示 3 行。
12. 行 hover 时整行高亮。
13. 点击股票进入个股详情。
14. 不使用用户草图里的残留数字。
15. 大盘资金流向仍是左饼图 + 右趋势图布局。
16. 单型资金净流向饼图只显示一个，不显示两个饼图。
17. 饼图四个饼块对应超大单、大单、中单、小单。
18. 饼块面积按各单型净额绝对值计算。
19. 饼块颜色按净额正负确定：正值红色，负值绿色，零值灰白色。
20. 饼块上的占比文字必须是白色，并放在对应饼块上。
21. 占比文字不得放在图例、外部折线标注或饼图中心。
22. 饼图中心不得显示“净额结构”、`absAmount`、总净额或任何英文调试字段。
23. 饼图中心建议留空，或仅保留环形图视觉空心。
24. 每个饼块需要外部折线标注，标注内容为单型名称 + 净额。
25. 外部折线标注正值文字红色，负值文字绿色，零值灰白色。
26. 外部折线不得遮挡饼块上的白色占比，不得占用右侧趋势图区域。
27. 右侧历史资金流向趋势图继续沿用白色趋势线、0 轴居中、Tooltip 正红负绿规则。
28. 不得输出买卖建议、看多看空、仓位建议等主观结论。

---

## 23. 待产品总控确认问题

本轮 Review v4 相关视觉规则已经可以支持 HTML Showcase 落地。仍建议产品总控在 `market-overview-v1.3.html` 产出后确认以下细节：

1. `领涨股涨停表现` 行式结构是否符合预期。
2. 今日和昨日两个区域是否都已同步修改。
3. 最多展示 3 行是否满足当前页面密度。
4. 行内是否需要默认展示封单金额，还是仅在 Tooltip 中展示。
5. 行内是否需要默认展示首次封板时间，还是仅在 Tooltip 中展示。
6. 饼块上的白色占比是否清晰可读。
7. 外部折线标注是否美观并与饼块对应清楚。
8. 饼图中心留空是否符合预期。
9. 小于 6% 的饼块是否允许隐藏饼块内占比文字。
10. 本轮是否存在未授权改动。

---

## 24. 本轮输出文件下载链接

本轮输出文件：`03-design-tokens.md`。

下载链接由本次对话附件提供：`sandbox:/mnt/data/design_token_v027/03-design-tokens.md`。

建议放置到 Google Drive：

```text
财势乾坤/设计/03-design-tokens.md
```

---

## 25. 当前版本结论

`03-design-tokens.md v0.2.7` 是基于 Review v4 的全量 Design Token 与视觉规范文档。

本版满足：

1. 输出文件名保持 `03-design-tokens.md`。
2. 文档为全量文档，不是增量补丁。
3. 只围绕 Review v4 点名两个展示问题补充视觉规则。
4. “领涨股涨停表现”行式结构视觉规则明确。
5. 单型资金净流向饼图折线标注规则明确。
6. 饼块上的白色占比文字规则明确。
7. 饼图中心禁止文字规则明确。
8. 正值红色、负值绿色、零值灰白色规则明确。
9. 红涨绿跌规则无误。
10. 不引入 SideNav 相关市场总览桌面端依赖。
11. 未主动修改 Review v4 未点名区域。
