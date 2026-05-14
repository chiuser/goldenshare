# 设计系统基线

## 来源

本基线来自 Drive：

```text
财势乾坤/设计/03-design-tokens.md
财势乾坤/showcase/market-overview-v1.1.html
wealth/docs/reference/showcase/market-overview-v1.8.html（仅新闻速览与个股新闻视觉参考）
```

## 视觉定位

财势乾坤行情系统首期采用深色金融终端风。

关键词：

- 专业
- 沉稳
- 高信息密度
- 金融终端感
- 数据可信
- 客观事实

## 主题

首期默认：

```text
Dark First
```

浅色主题只保留未来可能性，本阶段不实现。

## Token 前缀

统一使用：

```css
--cs-*
```

## 核心颜色

```css
:root,
[data-theme="dark"] {
  --cs-color-bg-page: #070A12;
  --cs-color-surface-panel: #101827;
  --cs-color-surface-card: #121B2C;
  --cs-color-text-primary: #E5EDF8;
  --cs-color-text-secondary: #A8B4C6;
  --cs-color-text-muted: #7B8AA0;
  --cs-color-market-up: #FF4D5A;
  --cs-color-market-down: #15C784;
  --cs-color-market-flat: #D8DEE8;
  --cs-color-brand-accent: #F7C76B;
}
```

## A 股颜色规则

必须红涨绿跌：

| 语义 | 颜色 |
|---|---|
| 上涨 / 正值 / 净流入 / 涨停 | 红色 |
| 下跌 / 负值 / 净流出 / 跌停 | 绿色 |
| 平盘 / 零值 / 无变化 | 中性灰白 |

禁止：

- 绿涨红跌。
- 用 UI 框架的 `success=green` 表达上涨。
- 用行情红作为系统错误主色。

## 布局基线

桌面端结构：

```text
TopMarketBar
Breadcrumb
PageHeader
ShortcutBar
全宽行情内容区
```

禁止固定 SideNav。

## 市场总览关键布局

1. 今日市场客观总结 + 主要指数：左右 50% / 50%。
2. 新闻速览：位于今日市场客观总结正上方，与今日市场客观总结等宽。
3. 个股新闻：位于主要指数正上方，与主要指数等宽。
4. 今日市场客观总结：默认 5 个事实卡 + 说明性文字卡（后端可配置为 6 卡）。
5. 主要指数：2 行 x 5 列，共 10 个指数。
6. 榜单速览：Top10 表格。
7. 涨跌停统计与分布：2 x 2 结构。
8. 板块速览：左侧 4 列 x 2 行榜单矩阵，右侧 5 x 4 热力图跨两行。

## 新闻面板视觉基线

新闻速览与个股新闻只吸收 `market-overview-v1.8.html` 中的独立新闻面板，不吸收旧顶部统一快讯条。

关键视觉规则：

1. 面板使用深色金融终端 Panel，标题为横向标题。
2. 标题左侧使用品牌色小圆点，不使用 ICON 预留位。
3. 右侧展示 `10 条可见` 这类可见条数说明。
4. 列表 viewport 是深色内嵌区域，默认可见 10 行。
5. 单条新闻为 `时间 + 标题` 两列；时间窄列、标题单行省略。
6. hover item 只做轻微背景强化，不出现点击态。

## 禁止方向

1. 不做普通后台管理风格。
2. 不做廉价大屏风。
3. 不做霓虹发光边框。
4. 不做欢迎页或营销页。
5. 不输出主观交易建议。
6. 不主动重排 Showcase 模块。
