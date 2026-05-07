# 组件规范基线

## 来源

本基线来自 Drive：

```text
财势乾坤/设计/04-component-guidelines.md
财势乾坤/设计/03-design-tokens.md
财势乾坤/showcase/market-overview-v1.1.html
```

## 组件设计原则

1. 组件服务用户任务，不服务后端对象命名。
2. 组件 props 使用业务语义，不暴露接口原始脏字段。
3. 展示组件尽量纯展示。
4. 数据获取通过 adapter 和页面组合层完成。
5. 不为单个页面临时复制一套相同组件。
6. 组件内不得硬编码行情颜色。

## 首期市场总览组件候选

后续实现市场总览时，优先按以下组件拆分：

| 组件 | 职责 |
|---|---|
| `TopMarketBar` | 顶部系统与行情状态栏 |
| `Breadcrumb` | 页面归属路径 |
| `PageHeader` | 页面标题、交易日、刷新状态 |
| `ShortcutBar` | 高频入口 |
| `MarketSummaryIndexSplit` | 今日总结 + 主要指数左右结构 |
| `MarketSummaryPanel` | 今日市场客观总结 |
| `MarketFactCard` | 客观事实卡片 |
| `MarketSummaryNoteCard` | 说明性文字卡 |
| `MajorIndexPanel` | 主要指数区域 |
| `IndexCard` | 指数卡片 |
| `BreadthPanel` | 涨跌分布 |
| `MarketStylePanel` | 市场风格 |
| `TurnoverPanel` | 成交额总览 |
| `MarketMoneyFlowPanel` | 大盘资金流向 |
| `RankingTableTop10` | 榜单 Top10 |
| `LimitDistributionGrid2x2` | 涨跌停 2x2 总区块 |
| `LimitStatCard` | 涨跌停统计卡 |
| `LimitStructurePanel` | 涨停/跌停/炸板结构 |
| `LimitHistoryBarChart` | 历史涨跌停组合柱状图 |
| `StreakLadderPanel` | 连板天梯 |
| `SectorOverviewMatrixHeatmap` | 板块速览总区块 |
| `SectorRankBlock` | 板块 Top5 榜单块 |
| `SectorHeatMap` | 板块 5x4 热力图 |

## 图表规则

首期不引入重型图表库作为捷径。

允许：

- SVG
- Canvas
- CSS 布局图表

必须支持：

- hover
- Tooltip
- 选中态
- RangeSwitch
- crosshair 或等价定位反馈

## 状态组件

每个核心区域必须有：

- loading
- empty
- error
- loaded
- data delayed

数据延迟不是系统错误，不能用行情红作为主色。

## 组件沉淀规则

1. 只在市场总览使用的组件先放 `features/market-overview`。
2. 两个以上页面复用后，再迁入 `shared/ui`。
3. 迁移共享组件前必须补组件说明和最小测试。
4. 不允许为了“看起来整齐”提前抽象过度。
