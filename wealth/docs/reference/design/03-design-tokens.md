# 财势乾坤｜Design Token 与视觉规范 v0.3.1

> 所属项目：财势乾坤
> 文档名称：`03-design-tokens.md`
> 建议保存路径：`财势乾坤/设计/03-design-tokens.md`
> 文档角色：01_Design Token 与视觉规范
> 适用范围：P0 Web 页面、通用组件库 Demo、后续行情终端类页面
> 默认主题：Dark First，Light Token Ready
> 市场规则：中国市场红涨绿跌
> 当前状态：v0.3.1，基于《组件库Demo产品需求文档 v0.2.md》与市场总览 Review v5 修订
> 本轮重点：在保留通用组件库 Demo Token 的基础上，仅补充市场总览 / 连板天梯模块的标准股票卡片、层级容器、晋级箭头、展开收起与五板以上层视觉规则；不修改 Review v5 未点名区域。

---

## 0. 本轮上游文档与修订边界

### 0.1 本轮读取到的上游文档

| 文件 | 版本 / 状态 | 本文档处理 |
|---|---|---|
| `财势乾坤行情软件项目总说明_v_0_2.md` | v0.2 | 继续作为项目级产品与 UI 总控纲领，约束产品名称、A 股优先、红涨绿跌、深色默认、专业沉稳风格。 |
| `组件库Demo产品需求文档 v0.2.md` | v0.2，Review 草案 | 作为本轮主输入，确认组件库 Demo 与具体业务解耦，不绑定市场总览、API、数据字典或具体业务对象。 |
| `03-design-tokens.md` | 当前公共区 Token 基线 | 作为本文档的既有内容基线，保留已确认的全局主题、红涨绿跌、深浅主题结构与市场总览既有页面级约束。 |

### 0.2 本轮不触发停止条件的确认

已读取到的《组件库Demo产品需求文档 v0.2.md》明确：

1. 文档标题为“财势乾坤通用组件库 Demo 产品需求文档 v0.2”；
2. 本版修订重点为“组件库必须与具体业务解耦”；
3. 组件库 Demo 不绑定市场总览、API、数据字典或具体业务对象；
4. `04 API 契约与数据字典` 不参与本轮主流程。

因此，本轮继续修订 `03-design-tokens.md`。

### 0.3 本轮修订边界

本轮目标是支撑：

```text
财势乾坤/showcase/component-library-demo-v1.html
```

本轮新增或强化的是 **通用组件 Token**，不是具体业务页面 Token。

允许新增或强化：

- 通用组件状态 Token；
- 通用容器 Token；
- 通用数据展示 Token；
- 通用表格 Token；
- 通用图表 Token；
- 通用饼图 callout Token；
- 通用热力图 Token；
- 通用 Tooltip、Callout、Skeleton、Empty、Error、Data Delayed 状态 Token。

禁止新增：

- 市场总览专属 Token；
- 涨跌停业务专属 Token；
- 持仓业务专属 Token；
- 机会雷达业务专属 Token；
- 交易计划业务专属 Token；
- Tushare 原字段专属 Token；
- 具体 API response 字段专属 Token。

### 0.4 命名边界

组件命名统一使用：

```text
Csq*
```

CSS Design Token 变量仍统一使用：

```css
--cs-*
```

说明：

- `Csq` 是组件名前缀，例如 `CsqPanel`、`CsqDataTable`。
- `--cs-*` 是 CSS Token 前缀，例如 `--cs-color-bg-page`。
- 本轮不新增 `--csq-*` CSS Token 前缀，避免与既有 Design Token 体系冲突。

---

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

# 25. 市场总览 / 连板天梯模块视觉规则（Review v5 修订）

> 本节仅服务 `市场总览 / 连板天梯模块`。
> 本节不修改 TopMarketBar、Breadcrumb、PageHeader、ShortcutBar、今日市场客观总结、主要指数、涨跌分布、市场风格、成交额总览、大盘资金流向、榜单速览、涨跌停统计与分布、板块速览、页面整体主题、全局字体或页面整体布局顺序。

## 25.1 Review v5 设计边界

Review v5 只处理连板天梯模块，目标是将连板天梯从普通股票卡片列表升级为：

```text
昨日层级 → 今日晋级层级
```

并建立一套可落地的视觉规则：

1. 标准股票卡片；
2. 昨日层级容器；
3. 今日晋级层级容器；
4. 首板独立层；
5. 五板以上独立层；
6. 晋级箭头；
7. 展开 / 收起控件；
8. 股票卡片 hover / clickable 状态；
9. 五板以上卡片右下角“具体板数”样式。

## 25.2 连板天梯专用 Token

```css
:root {
  /* Limit ladder module */
  --cs-limit-ladder-row-gap: 12px;
  --cs-limit-ladder-layer-gap: 10px;
  --cs-limit-ladder-bridge-width: 44px;
  --cs-limit-ladder-layer-padding: 10px;
  --cs-limit-ladder-layer-title-height: 28px;
  --cs-limit-ladder-stock-grid-gap-x: 8px;
  --cs-limit-ladder-stock-grid-gap-y: 8px;

  /* Stock compact card */
  --cs-stock-card-width: 148px;
  --cs-stock-card-height: 72px;
  --cs-stock-card-padding-x: 10px;
  --cs-stock-card-padding-y: 8px;
  --cs-stock-card-radius: var(--cs-radius-card);
  --cs-stock-card-border-width: 1px;

  /* Expand / collapse */
  --cs-limit-ladder-expand-height: 28px;
  --cs-limit-ladder-expand-icon-size: 12px;
  --cs-limit-ladder-expand-font-size: var(--cs-font-size-12);

  /* Arrow */
  --cs-limit-ladder-arrow-size: 18px;
  --cs-limit-ladder-arrow-line-width: 1px;
}

[data-theme="dark"] {
  --cs-limit-ladder-layer-bg: rgba(16, 24, 39, 0.78);
  --cs-limit-ladder-layer-bg-subtle: rgba(13, 20, 34, 0.82);
  --cs-limit-ladder-layer-bg-above-five: rgba(247, 199, 107, 0.07);
  --cs-limit-ladder-layer-border: rgba(148, 163, 184, 0.16);
  --cs-limit-ladder-layer-border-emphasis: rgba(247, 199, 107, 0.28);
  --cs-limit-ladder-layer-title-bg: rgba(255, 255, 255, 0.025);
  --cs-limit-ladder-layer-title-text: var(--cs-color-text-secondary);

  --cs-stock-card-bg: rgba(18, 27, 44, 0.92);
  --cs-stock-card-bg-hover: rgba(24, 34, 53, 0.96);
  --cs-stock-card-bg-active: rgba(21, 30, 48, 0.98);
  --cs-stock-card-border: rgba(148, 163, 184, 0.16);
  --cs-stock-card-border-hover: rgba(247, 199, 107, 0.34);
  --cs-stock-card-border-active: rgba(247, 199, 107, 0.48);
  --cs-stock-card-shadow-hover: 0 8px 20px rgba(0, 0, 0, 0.24);

  --cs-stock-card-name-text: var(--cs-color-text-primary);
  --cs-stock-card-code-text: var(--cs-color-text-muted);
  --cs-stock-card-sector-text: var(--cs-color-text-secondary);
  --cs-stock-card-open-times-text: var(--cs-color-warning);
  --cs-stock-card-streak-level-text: var(--cs-color-brand-accent);
  --cs-stock-card-streak-level-bg: rgba(247, 199, 107, 0.10);
  --cs-stock-card-streak-level-border: rgba(247, 199, 107, 0.28);

  --cs-limit-ladder-arrow-color: rgba(247, 199, 107, 0.72);
  --cs-limit-ladder-arrow-bg: rgba(247, 199, 107, 0.08);
  --cs-limit-ladder-expand-bg: rgba(148, 163, 184, 0.08);
  --cs-limit-ladder-expand-bg-hover: rgba(247, 199, 107, 0.10);
  --cs-limit-ladder-expand-border: rgba(148, 163, 184, 0.14);
  --cs-limit-ladder-expand-text: var(--cs-color-text-secondary);
  --cs-limit-ladder-expand-text-hover: var(--cs-color-brand-accent);
}

[data-theme="light"] {
  --cs-limit-ladder-layer-bg: #FFFFFF;
  --cs-limit-ladder-layer-bg-subtle: #F8FAFC;
  --cs-limit-ladder-layer-bg-above-five: rgba(201, 154, 61, 0.08);
  --cs-limit-ladder-layer-border: rgba(15, 23, 42, 0.10);
  --cs-limit-ladder-layer-border-emphasis: rgba(201, 154, 61, 0.26);
  --cs-limit-ladder-layer-title-bg: rgba(15, 23, 42, 0.025);
  --cs-limit-ladder-layer-title-text: var(--cs-color-text-secondary);

  --cs-stock-card-bg: #FFFFFF;
  --cs-stock-card-bg-hover: #F8FAFC;
  --cs-stock-card-bg-active: #F1F5F9;
  --cs-stock-card-border: rgba(15, 23, 42, 0.12);
  --cs-stock-card-border-hover: rgba(201, 154, 61, 0.36);
  --cs-stock-card-border-active: rgba(201, 154, 61, 0.48);
  --cs-stock-card-shadow-hover: 0 8px 18px rgba(15, 23, 42, 0.10);

  --cs-stock-card-name-text: var(--cs-color-text-primary);
  --cs-stock-card-code-text: var(--cs-color-text-muted);
  --cs-stock-card-sector-text: var(--cs-color-text-secondary);
  --cs-stock-card-open-times-text: var(--cs-color-warning);
  --cs-stock-card-streak-level-text: var(--cs-color-brand-accent);
  --cs-stock-card-streak-level-bg: rgba(201, 154, 61, 0.10);
  --cs-stock-card-streak-level-border: rgba(201, 154, 61, 0.28);

  --cs-limit-ladder-arrow-color: rgba(168, 117, 33, 0.72);
  --cs-limit-ladder-arrow-bg: rgba(201, 154, 61, 0.08);
  --cs-limit-ladder-expand-bg: rgba(15, 23, 42, 0.04);
  --cs-limit-ladder-expand-bg-hover: rgba(201, 154, 61, 0.08);
  --cs-limit-ladder-expand-border: rgba(15, 23, 42, 0.10);
  --cs-limit-ladder-expand-text: var(--cs-color-text-secondary);
  --cs-limit-ladder-expand-text-hover: var(--cs-color-brand-accent);
}
```

## 25.3 标准股票卡片视觉规则

标准股票卡片是连板天梯中的基础展示单元。字段固定为：

```text
左上：股票名称      右上：涨跌幅
左中：股票代码      右中：所属板块
左下：最新价        右下：开板次数
```

五板以上层特殊规则：

```text
右下：具体板数，如 6板 / 7板 / 8板
```

### 25.3.1 尺寸与密度

| 项 | Token / 建议值 | 说明 |
|---|---:|---|
| 卡片宽度 | `--cs-stock-card-width: 148px` | 每行 6 只时适配全宽区域 |
| 卡片高度 | `--cs-stock-card-height: 72px` | 允许 3 行信息，保持高密度 |
| 横向内边距 | `--cs-stock-card-padding-x: 10px` | 保证左右字段不贴边 |
| 纵向内边距 | `--cs-stock-card-padding-y: 8px` | 兼顾密度与可读性 |
| 圆角 | `--cs-stock-card-radius` | 使用既有卡片圆角 |
| 边框 | `--cs-stock-card-border` | 细边框，不做发光 |

推荐 CSS：

```css
.cs-stock-compact-card {
  width: var(--cs-stock-card-width);
  min-height: var(--cs-stock-card-height);
  padding: var(--cs-stock-card-padding-y) var(--cs-stock-card-padding-x);
  border-radius: var(--cs-stock-card-radius);
  border: var(--cs-stock-card-border-width) solid var(--cs-stock-card-border);
  background: var(--cs-stock-card-bg);
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-rows: repeat(3, minmax(16px, auto));
  column-gap: 8px;
  row-gap: 2px;
  cursor: pointer;
  transition:
    background var(--cs-motion-duration-fast) var(--cs-motion-ease-standard),
    border-color var(--cs-motion-duration-fast) var(--cs-motion-ease-standard),
    box-shadow var(--cs-motion-duration-fast) var(--cs-motion-ease-standard),
    transform var(--cs-motion-duration-fast) var(--cs-motion-ease-standard);
}
```

### 25.3.2 字体与对齐

| 字段 | 字号 | 字重 | 颜色 | 对齐 |
|---|---:|---:|---|---|
| 股票名称 | 13px | 600 | `--cs-stock-card-name-text` | 左对齐 |
| 股票代码 | 11px | 400/500 | `--cs-stock-card-code-text` | 左对齐 |
| 最新价 | 12px | 600 | 按涨跌方向红/绿/灰白 | 左对齐，数字字体 |
| 涨跌幅 | 12px | 700 | 红涨绿跌 | 右对齐，数字字体 |
| 所属板块 | 11px | 400/500 | `--cs-stock-card-sector-text` | 右对齐，单行省略 |
| 开板次数 | 11px | 500 | `--cs-stock-card-open-times-text` | 右对齐 |
| 具体板数 | 11px | 700 | `--cs-stock-card-streak-level-text` | 右对齐，pill 标签 |

```css
.cs-stock-card-name {
  font-size: var(--cs-font-size-13);
  font-weight: var(--cs-font-weight-semibold);
  color: var(--cs-stock-card-name-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cs-stock-card-code,
.cs-stock-card-sector,
.cs-stock-card-open-times {
  font-size: var(--cs-font-size-11);
  line-height: var(--cs-line-height-compact);
}

.cs-stock-card-price,
.cs-stock-card-change {
  font-family: var(--cs-font-family-number);
  font-variant-numeric: tabular-nums;
}

.cs-stock-card-change,
.cs-stock-card-sector,
.cs-stock-card-open-times,
.cs-stock-card-streak-level {
  text-align: right;
}
```

### 25.3.3 Hover / clickable / active 状态

```css
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

.cs-stock-compact-card.is-clickable {
  cursor: pointer;
}
```

规则：

1. hover 时整卡高亮；
2. clickable 状态必须通过 cursor 与 hover 边框提示；
3. active 仅用于鼠标按下或键盘确认，不作为常驻选中；
4. 不设置层级标题点击态，因为层级标题暂不支持点击。

## 25.4 层级容器视觉规则

连板天梯层级容器分为四类：

1. 昨日层级容器；
2. 今日晋级层级容器；
3. 首板独立层容器；
4. 五板以上独立层容器。

所有层级容器必须使用现有深色金融终端风格，不照搬草图浅蓝背景。

### 25.4.1 昨日层级容器

用途：展示昨日属于某层级的所有股票，卡片数据使用今日行情。

```css
.cs-limit-ladder-prev-layer {
  background: var(--cs-limit-ladder-layer-bg-subtle);
  border: 1px solid var(--cs-limit-ladder-layer-border);
  border-radius: var(--cs-radius-panel);
  padding: var(--cs-limit-ladder-layer-padding);
}
```

视觉规则：

- 标题如 `昨日首板`、`昨日二板`、`昨日三板`；
- 标题使用次级文字，不做强高亮；
- 容器背景略弱于今日晋级层；
- 容器内股票卡片仍可点击进入个股详情。

### 25.4.2 今日晋级层级容器

用途：展示从昨日层级成功晋级到今日 N 板的股票。

```css
.cs-limit-ladder-current-layer {
  background: var(--cs-limit-ladder-layer-bg);
  border: 1px solid var(--cs-limit-ladder-layer-border-emphasis);
  border-radius: var(--cs-radius-panel);
  padding: var(--cs-limit-ladder-layer-padding);
}
```

视觉规则：

- 标题如 `今日二板`、`今日三板`、`今日四板`、`今日五板`；
- 边框可略带品牌金弱强调；
- 不使用大面积红色背景；
- 成功晋级本身不等于主观推荐，不做过强视觉冲击。

### 25.4.3 首板独立层容器

用途：只展示今日首板股票，没有昨日来源。

```css
.cs-limit-ladder-first-layer {
  background: var(--cs-limit-ladder-layer-bg);
  border: 1px solid var(--cs-limit-ladder-layer-border);
  border-radius: var(--cs-radius-panel);
  padding: var(--cs-limit-ladder-layer-padding);
}
```

视觉规则：

- 标题固定为 `首板`；
- 独立占一行；
- 该层位于低位层，整体顺序靠下；
- 不展示晋级箭头。

### 25.4.4 五板以上独立层容器

用途：只展示今日六板及以上股票，不包含今日五板。

```css
.cs-limit-ladder-above-five-layer {
  background: var(--cs-limit-ladder-layer-bg-above-five);
  border: 1px solid var(--cs-limit-ladder-layer-border-emphasis);
  border-radius: var(--cs-radius-panel);
  padding: var(--cs-limit-ladder-layer-padding);
}
```

视觉规则：

1. 顶部独立层；
2. 标题固定为 `五板以上`；
3. 只展示今日六板及以上；
4. 不包含今日五板；
5. 不展示成“昨日五板 → 今日六板”的晋级结构；
6. 股票卡片右下显示具体板数，如 `6板`、`7板`；
7. 使用弱品牌金边框或弱金背景，不使用夸张发光。

### 25.4.5 层级标题条

```css
.cs-limit-ladder-layer-title {
  height: var(--cs-limit-ladder-layer-title-height);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 2px 6px;
  color: var(--cs-limit-ladder-layer-title-text);
  font-size: var(--cs-font-size-13);
  font-weight: var(--cs-font-weight-semibold);
  border-bottom: 1px solid var(--cs-color-divider);
  margin-bottom: var(--cs-space-8);
}
```

规则：

- 层级标题清晰但不喧宾夺主；
- 标题不支持点击，不出现 link hover；
- 可在标题右侧展示股票数量，例如 `12只`；
- 股票数量使用弱文字或数字字体。

## 25.5 层级排列与网格密度

### 25.5.1 二板及以上晋级结构

```text
昨日 N-1 板     →     今日 N 板
```

推荐 CSS：

```css
.cs-limit-ladder-promotion-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) var(--cs-limit-ladder-bridge-width) minmax(0, 1fr);
  align-items: stretch;
  gap: var(--cs-limit-ladder-layer-gap);
  margin-bottom: var(--cs-limit-ladder-row-gap);
}
```

### 25.5.2 股票卡片网格

默认每层最多展示 2 行 × 每行 6 只。

```css
.cs-limit-ladder-stock-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(var(--cs-stock-card-width), 1fr));
  gap: var(--cs-limit-ladder-stock-grid-gap-y) var(--cs-limit-ladder-stock-grid-gap-x);
  overflow: hidden;
}

.cs-limit-ladder-stock-grid.is-collapsed {
  max-height: calc(var(--cs-stock-card-height) * 2 + var(--cs-limit-ladder-stock-grid-gap-y));
}

.cs-limit-ladder-stock-grid.is-expanded {
  max-height: none;
}
```

规则：

1. 默认最多展示 12 只；
2. 每层独立控制展开状态；
3. 展开不影响其它层；
4. 如果宽度不足，可在 1366px 附近降级为每行 5 只，但不得破坏卡片字段结构；
5. 不因连板天梯改造引入横向固定 SideNav。

## 25.6 晋级箭头视觉规则

晋级箭头用于连接：

```text
昨日 N-1 板 → 今日 N 板
```

```css
.cs-limit-ladder-arrow {
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--cs-limit-ladder-arrow-color);
  font-size: var(--cs-limit-ladder-arrow-size);
  line-height: 1;
  pointer-events: none;
}

.cs-limit-ladder-arrow::before {
  content: "→";
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: var(--cs-radius-pill);
  background: var(--cs-limit-ladder-arrow-bg);
  border: 1px solid var(--cs-limit-ladder-layer-border-emphasis);
}
```

规则：

1. 箭头颜色使用品牌金弱强调；
2. 箭头大小约 18px；
3. 箭头左右与容器间距由 `--cs-limit-ladder-layer-gap` 控制；
4. hover 不变化；
5. 不做点击态；
6. 不表达买卖方向，只表达层级晋级关系。

## 25.7 展开 / 收起控件视觉规则

每层默认最多展示 12 只股票。超过 12 只时，底部显示展开控件。

### 25.7.1 默认收起态

```text
⌄⌄ 展开全部
```

```css
.cs-limit-ladder-expand-control {
  height: var(--cs-limit-ladder-expand-height);
  margin-top: var(--cs-space-8);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--cs-space-4);
  border: 1px solid var(--cs-limit-ladder-expand-border);
  border-radius: var(--cs-radius-pill);
  background: var(--cs-limit-ladder-expand-bg);
  color: var(--cs-limit-ladder-expand-text);
  font-size: var(--cs-limit-ladder-expand-font-size);
  cursor: pointer;
  user-select: none;
}

.cs-limit-ladder-expand-control:hover {
  background: var(--cs-limit-ladder-expand-bg-hover);
  color: var(--cs-limit-ladder-expand-text-hover);
  border-color: var(--cs-color-border-hover);
}
```

### 25.7.2 展开态

展开后文案：

```text
收起
```

规则：

1. 展开/收起只影响当前层；
2. 展开后可以撑开连板天梯模块高度；
3. 如果页面高度压力大，允许连板天梯模块内部滚动；
4. 不允许因此压缩或改动其它非本轮模块；
5. 展开控件不使用红绿，使用中性 + 品牌金 hover。

## 25.8 五板以上具体板数样式

五板以上层股票卡片右下角显示具体板数，而不是开板次数。

```css
.cs-stock-card-streak-level {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 34px;
  height: 18px;
  padding: 0 6px;
  border-radius: var(--cs-radius-pill);
  border: 1px solid var(--cs-stock-card-streak-level-border);
  background: var(--cs-stock-card-streak-level-bg);
  color: var(--cs-stock-card-streak-level-text);
  font-size: var(--cs-font-size-11);
  font-weight: var(--cs-font-weight-bold);
  line-height: 1;
  font-family: var(--cs-font-family-number);
  font-variant-numeric: tabular-nums;
}
```

规则：

1. 文案示例：`6板`、`7板`、`8板`；
2. 只在五板以上层显示；
3. 今日五板仍属于 `昨日四板 → 今日五板` 层，不使用该五板以上样式；
4. 该标签使用品牌金弱强调，不使用涨停红大面积背景；
5. 不输出推荐、强势判断等主观结论。

## 25.9 连板天梯状态规则

| 状态 | 视觉规则 |
|---|---|
| loading | 层级标题骨架 + 2 行股票卡片骨架 |
| empty | 当前层显示“暂无该层级股票”，不隐藏其它层 |
| error | 当前层模块级错误块，允许单层重试 |
| disabled | 通常不出现；如数据不可点击，卡片透明度降低且不显示 pointer |
| data delayed | 层级标题右侧显示延迟 Badge，不改变股票涨跌色 |

## 25.10 连板天梯禁止事项

1. 不照搬草图浅蓝背景；
2. 不把层级标题做成可点击链接；
3. 不把五板以上展示成 `昨日五板 → 今日六板`；
4. 不让今日五板进入五板以上层；
5. 不将晋级箭头做成交易方向或买卖提示；
6. 不使用大面积红色背景强调涨停；
7. 不因连板天梯改造修改页面其它模块视觉规则。

---

# 26. 本轮 Review v5 修改摘要

1. 仅修订 `市场总览 / 连板天梯模块` 的视觉规则。
2. 新增标准股票卡片规则：左上股票名称、左中股票代码、左下最新价、右上涨跌幅、右中所属板块、右下开板次数。
3. 五板以上层股票卡片右下显示具体板数，如 `6板`、`7板`、`8板`。
4. 新增昨日层级容器和今日晋级层级容器视觉规则。
5. 新增首板独立层容器视觉规则。
6. 新增五板以上独立层容器弱强调规则。
7. 新增晋级箭头视觉规则。
8. 新增展开 / 收起控件规则：默认最多 2 行 × 6 只，共 12 只，超出显示 `展开全部`，展开后显示 `收起`。
9. 明确股票卡片 hover / active / clickable 状态。
10. 保持红涨绿跌规则不变。

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
14. 页面整体主题；
15. 全局字体；
16. 与 Review v5 无关的任何视觉规则。

```text
本轮因 Review v5 修改而被动影响的区域：无
原因：无
是否需要产品总控确认：否
```

# 28. 本轮新增或修订 Token 清单

| Token | 类型 | 用途 |
|---|---|---|
| `--cs-limit-ladder-row-gap` | 新增 | 连板天梯层级行间距 |
| `--cs-limit-ladder-layer-gap` | 新增 | 昨日层级、箭头、今日层级之间间距 |
| `--cs-limit-ladder-bridge-width` | 新增 | 晋级箭头连接区宽度 |
| `--cs-limit-ladder-layer-padding` | 新增 | 层级容器内边距 |
| `--cs-limit-ladder-layer-title-height` | 新增 | 层级标题条高度 |
| `--cs-limit-ladder-stock-grid-gap-x` | 新增 | 股票卡片网格横向间距 |
| `--cs-limit-ladder-stock-grid-gap-y` | 新增 | 股票卡片网格纵向间距 |
| `--cs-stock-card-width` | 新增 | 标准股票卡片宽度 |
| `--cs-stock-card-height` | 新增 | 标准股票卡片高度 |
| `--cs-stock-card-padding-x` | 新增 | 标准股票卡片横向内边距 |
| `--cs-stock-card-padding-y` | 新增 | 标准股票卡片纵向内边距 |
| `--cs-stock-card-bg` | 新增 | 股票卡片背景 |
| `--cs-stock-card-bg-hover` | 新增 | 股票卡片 hover 背景 |
| `--cs-stock-card-bg-active` | 新增 | 股票卡片点击态背景 |
| `--cs-stock-card-border` | 新增 | 股票卡片边框 |
| `--cs-stock-card-border-hover` | 新增 | 股票卡片 hover 边框 |
| `--cs-stock-card-border-active` | 新增 | 股票卡片点击态边框 |
| `--cs-stock-card-shadow-hover` | 新增 | 股票卡片 hover 阴影 |
| `--cs-stock-card-name-text` | 新增 | 股票名称文字色 |
| `--cs-stock-card-code-text` | 新增 | 股票代码文字色 |
| `--cs-stock-card-sector-text` | 新增 | 所属板块文字色 |
| `--cs-stock-card-open-times-text` | 新增 | 开板次数文字色 |
| `--cs-stock-card-streak-level-text` | 新增 | 五板以上具体板数文字色 |
| `--cs-stock-card-streak-level-bg` | 新增 | 五板以上具体板数标签背景 |
| `--cs-stock-card-streak-level-border` | 新增 | 五板以上具体板数标签边框 |
| `--cs-limit-ladder-arrow-color` | 新增 | 晋级箭头颜色 |
| `--cs-limit-ladder-arrow-bg` | 新增 | 晋级箭头圆形弱背景 |
| `--cs-limit-ladder-expand-height` | 新增 | 展开 / 收起控件高度 |
| `--cs-limit-ladder-expand-bg` | 新增 | 展开 / 收起控件背景 |
| `--cs-limit-ladder-expand-bg-hover` | 新增 | 展开 / 收起控件 hover 背景 |
| `--cs-limit-ladder-expand-border` | 新增 | 展开 / 收起控件边框 |
| `--cs-limit-ladder-expand-text` | 新增 | 展开 / 收起控件文字 |
| `--cs-limit-ladder-expand-text-hover` | 新增 | 展开 / 收起控件 hover 文字 |

# 29. 对 03 `04-component-guidelines.md` 的 Token 映射建议

| 组件 / Pattern | 建议使用 Token |
|---|---|
| `CsqStockCompactCard` | `--cs-stock-card-*`、`--cs-color-market-*`、`--cs-font-family-number` |
| `PatternLimitLadder` | `--cs-limit-ladder-*`、`--cs-stock-card-*` |
| `LimitLadderPromotionLayer` | `--cs-limit-ladder-layer-bg`、`--cs-limit-ladder-layer-border`、`--cs-limit-ladder-layer-title-*` |
| `LimitLadderSpecialLayer` | `--cs-limit-ladder-layer-bg-above-five`、`--cs-limit-ladder-layer-border-emphasis` |
| `LimitLadderStockGrid` | `--cs-limit-ladder-stock-grid-gap-x`、`--cs-limit-ladder-stock-grid-gap-y`、`--cs-stock-card-width` |
| `LimitLadderExpandControl` | `--cs-limit-ladder-expand-*` |
| `LimitLadderPromotionArrow` | `--cs-limit-ladder-arrow-*` |

建议 03 约束：

1. `CsqStockCompactCard` 是相对通用紧凑股票卡片，可作为 Core Component 候选；
2. `PatternLimitLadder` 是市场总览连板天梯业务 Pattern，不应进入通用组件库 Core Component；
3. 层级标题不支持点击；
4. 股票卡片支持点击进入个股详情；
5. 展开 / 收起只作用于当前层。

# 30. 对 02 `market-overview-v1.4.html` 的视觉约束

1. 只修改连板天梯模块。
2. 使用深色金融终端风格，不照搬草图浅蓝背景。
3. 新增标准股票卡片，字段位置必须为：
   - 左上：股票名称；
   - 左中：股票代码；
   - 左下：最新价；
   - 右上：涨跌幅；
   - 右中：所属板块；
   - 右下：开板次数。
4. 五板以上层卡片右下显示具体板数，不显示开板次数。
5. 二板及以上层级采用 `昨日 N-1 板 → 今日 N 板` 的左右结构。
6. 昨日层级展示昨日该层级所有股票，卡片信息用今日数据。
7. 今日晋级层级只展示晋级成功股票。
8. 首板层独立展示今日首板股票。
9. 五板以上层独立置顶，只展示今日六板及以上，不包含今日五板。
10. 今日五板仍属于 `昨日四板 → 今日五板` 层。
11. 每层默认最多展示 2 行 × 6 只，即 12 只股票。
12. 超出 12 只时底部显示 `展开全部` 控件。
13. 展开后显示 `收起` 控件。
14. 展开 / 收起只影响当前层。
15. 股票卡片 hover 时整卡高亮，点击进入个股详情页。
16. 晋级箭头只表达层级关系，不做点击态。
17. 层级标题不支持点击，不做链接样式。
18. 不修改 Review v5 未点名模块。

# 31. 待产品总控确认问题

1. 标准股票卡片宽度 `148px` 是否满足 1366px 下每行 6 只展示，还是需要降为 136px？
2. 连板天梯在 1366px 宽度下是否允许每行自动降级为 5 只？
3. 展开后优先采用“模块内部滚动”还是“模块向下撑开”？当前建议优先内部滚动或局部展开，不影响其它模块。
4. 五板以上层是否固定标题为“五板以上”，还是显示“六板及以上”？当前按 Review v5 使用“五板以上”。
5. 开板次数为 0 时显示 `0次`、`未开板`，还是弱化为 `--`？当前 Token 只定义样式，文案由 02/03 确认。
6. 层级标题右侧是否展示股票数量，例如 `12只`？当前建议允许展示。

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
