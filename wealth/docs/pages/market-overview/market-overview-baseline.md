# 市场总览页面基线

## 来源

本页面基线来自 Drive：

```text
财势乾坤/showcase/market-overview-v1.1.html
财势乾坤/产品文档/市场总览产品需求文档 v0.2.md
财势乾坤/设计/02-market-overview-page-design.md
财势乾坤/codex/market-overview-codex-prompt-v1.md
wealth/docs/update/market-overview-v1.8.html（仅新闻速览与个股新闻新增需求）
```

## 页面定位

```text
财势乾坤 / 乾坤行情 / 市场总览
```

市场总览是 A 股市场客观事实总览页，不是主观分析结论页。

## 首期路由

```text
/market/overview
```

## 实现基线

必须高保真参考：

```text
market-overview-v1.1.html
```

不要使用旧版：

```text
market-overview-v1.html
```

不要等待或假设：

```text
market-overview-v1.2.html
```

## 页面结构

必须包含：

1. TopMarketBar
2. Breadcrumb
3. PageHeader
4. ShortcutBar
5. 今日市场客观总结
6. 主要指数
7. 涨跌分布
8. 市场风格
9. 成交额总览
10. 大盘资金流向
11. 榜单速览
12. 涨跌停统计与分布
13. 连板天梯
14. 板块速览

模块顺序以 `market-overview-v1.1.html` 为准。

新闻板块新增需求以 `wealth/docs/update/market-overview-v1.8.html` 为准。该版本只用于吸收“新闻速览 + 个股新闻”两个独立新闻面板，不改变其它已落地模块口径。

## 硬性布局

### 今日市场客观总结 + 主要指数

左右结构，各 50%。

左侧：

- 新闻速览位于今日市场客观总结正上方，与今日市场客观总结等宽
- 默认 5 个事实卡片（后端可配置为 5 或 6）
- 说明性文字卡片

右侧：

- 个股新闻位于主要指数正上方，与主要指数等宽
- 10 个主要指数
- 2 行 x 5 列

### 新闻速览 + 个股新闻

1. `新闻速览` 和 `个股新闻` 是两个独立 Panel，不放入 PageHeader、TopMarketBar 或头部中间区域。
2. 两个新闻 Panel 高度一致。
3. 默认每个 Panel 可见 10 条新闻，展示文案为 `10 条可见`。
4. 单条新闻格式固定为 `MM-DD HH:mm:ss  新闻标题`，标题单行省略。
5. 默认向上自动滚动；hover 当前 Panel 只暂停当前 Panel，另一个 Panel 继续滚动。
6. 本期新闻 item 不可点击，不显示 pointer，不跳转详情或外链。
7. 旧 `ICON 预留位｜新闻速览｜个股新闻` 顶部统一快讯条方案已废弃。

### 榜单速览

Top10 表格，列顺序固定：

```text
排名｜股票｜最新价｜涨跌幅｜换手率｜量比｜成交量｜成交额
```

### 涨跌停统计与分布

2 x 2 结构：

```text
左上：8 个统计卡片
右上：今日涨停板块分布 + 跌停/炸板结构
左下：历史涨跌停组合柱状图
右下：昨日涨停板块分布 + 跌停/炸板结构
```

### 板块速览

左侧：

- 4 列 x 2 行榜单矩阵
- 共 8 个 Top5 榜单块

右侧：

- 5 x 4 热力图
- 跨两行高度

## 交互要求

后续页面实现必须覆盖：

1. hover 反馈。
2. Tooltip。
3. 图表定位线或等价 crosshair。
4. RangeSwitch。
5. 刷新状态。
6. loading / empty / error / data delayed / loaded。
7. 榜单行点击进入详情页的预留交互。
8. 板块项点击进入板块与榜单行情页的预留交互。

## 禁止事项

1. 不允许固定 SideNav。
2. 不允许把市场总览做成独立一级菜单。
3. 不允许输出买卖建议、仓位建议、明日预测。
4. 不允许展示市场温度分数、情绪指数、资金面分数、风险指数作为首页核心结论。
5. 不允许重排模块。
6. 不允许删模块。
7. 不允许把页面改成运营后台风。
