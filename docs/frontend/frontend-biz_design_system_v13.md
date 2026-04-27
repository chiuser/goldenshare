# 财势乾坤行情系统 · Design System v13

> 适用范围：财势乾坤 Web 行情系统、首页、情绪分析页、市场温度页、资金面页、板块轮动页、个股列表页。  
> 设计基准：沿用 V13 原型的深色金融终端风格，保留红涨绿跌、深色玻璃面板、金色强调、弱边框、紧凑信息密度。  
> 技术目标：后续可直接迁移到 Vue/React，组件命名、Design Token、交互模式和数据结构都保持稳定。

---

## 0. 文档定位

| 文件 | 职责 |
|---|---|
| `caishiqiankun_design_system_v13.md` | **为什么这么设计**：设计原则、Token、布局、交互红线 |
| `caishiqiankun_component_showcase_v13.html` | **长什么样**：可直接浏览器打开的组件展示页 |
| `caishiqiankun_component_catalog_v13.md` | **怎么在代码里用**：组件清单、Props、字段、使用规则 |

---

## 1. 设计原则

### 1.1 先判断，再展开

行情系统首页和情绪页都不是数据堆叠页。每屏必须先回答：

1. 当前市场发生了什么？
2. 现在适不适合交易？
3. 情绪是修复、发酵、分歧、退潮，还是冰点？

因此每个页面都应遵守：

- 顶部给结论。
- 中部用指标佐证。
- 底部提供下钻入口。
- 复杂名单进入抽屉、弹层或二级页，不在主视图直接全部展开。

### 1.2 专业紧凑，但不压迫

V13 风格的信息密度比普通 SaaS 高，但不能像老式终端一样混乱。

- 字号克制：常规文本 11–13px，模块标题 15–18px，关键数字 22–42px。
- 间距紧凑：模块 gap 16px，卡片内 padding 14–18px。
- 重要信息靠位置、字重、色彩和留白共同形成层级。
- 不使用大面积炫光、霓虹、强模糊、强阴影。

### 1.3 A 股语义优先：红涨绿跌

本系统固定使用中国市场语义：

- 红色 = 上涨、涨停、正反馈、进攻。
- 绿色 = 下跌、跌停、负反馈、回撤。
- 金色 = 中性偏强、警示、观察。
- 蓝色 / 青色 = 系统信息、工具、非涨跌状态。

任何组件不得把上涨写成绿色，或者把下跌写成红色。

### 1.4 页面骨架优先于单个卡片

组件可以继续打磨，但页面骨架不能松：

- 双列模块必须对齐。
- 面板标题、说明、状态角标位置一致。
- 列表行高、数字列、涨跌列必须对齐。
- 历史图使用统一坐标系统、图例、hover tooltip。

---

## 2. Design Token

所有 Token 推荐落地为 CSS 变量。组件中禁止直接写散乱十六进制色值。

### 2.1 主题色：V13 Deep Finance

```css
:root {
  --bg-page: #080c14;
  --bg-page-2: #0a1020;
  --bg-page-3: #101827;

  --bg-panel: rgba(19, 29, 48, 0.92);
  --bg-panel-strong: rgba(14, 22, 37, 0.96);
  --bg-panel-soft: rgba(255, 255, 255, 0.035);
  --bg-card: rgba(255, 255, 255, 0.04);
  --bg-card-hover: rgba(255, 255, 255, 0.065);

  --border-subtle: rgba(148, 163, 184, 0.12);
  --border-default: rgba(148, 163, 184, 0.16);
  --border-strong: rgba(148, 163, 184, 0.24);

  --text-primary: #e5edf8;
  --text-secondary: #8fa1b8;
  --text-tertiary: #65748a;
  --text-inverse: #fff6ea;
}
```

### 2.2 涨跌色

```css
:root {
  --color-rise: #ff4d5a;
  --color-rise-soft: rgba(255, 77, 90, 0.12);
  --color-rise-border: rgba(255, 77, 90, 0.24);
  --color-rise-deep: rgba(54, 10, 16, 0.96);

  --color-fall: #15c784;
  --color-fall-soft: rgba(21, 199, 132, 0.10);
  --color-fall-border: rgba(21, 199, 132, 0.22);
  --color-fall-deep: rgba(7, 34, 24, 0.96);

  --color-flat: #f7c76b;
  --color-flat-soft: rgba(247, 199, 107, 0.12);
  --color-info: #5aa7ff;
  --color-cyan: #22d3ee;
}
```

### 2.3 语义映射

| 语义 | Token | 典型组件 |
|---|---|---|
| 页面底色 | `--bg-page` | body |
| 一级面板 | `--bg-panel` | Panel |
| 二级卡片 | `--bg-card` | MetricCard、StockChip |
| 弱边框 | `--border-default` | Panel、Card、Tab |
| 主文本 | `--text-primary` | 标题、关键描述 |
| 辅助文本 | `--text-secondary` | subtitle、caption |
| 上涨 | `--color-rise` | PriceText、LimitUp |
| 下跌 | `--color-fall` | PriceText、LimitDown |
| 中性/警示 | `--color-flat` | 风险提示、观察状态 |
| 系统信息 | `--color-info` | 链接、工具、筛选 |

---

## 3. Typography

### 3.1 字体

```css
--font-sans: -apple-system, BlinkMacSystemFont, "SF Pro Display",
  "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif;

--font-mono: "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;
```

### 3.2 字号

| Token | 值 | 用途 |
|---|---:|---|
| `--font-10` | 10px | 迷你角标、图表轴标签 |
| `--font-11` | 11px | caption、tag、辅助说明 |
| `--font-12` | 12px | 常规辅助文本、按钮 |
| `--font-13` | 13px | 正文、列表副标题 |
| `--font-14` | 14px | 列表主标题、小卡片标题 |
| `--font-15` | 15px | Panel 标题 |
| `--font-18` | 18px | 小型关键数字 |
| `--font-22` | 22px | 指数点位、统计数字 |
| `--font-28` | 28px | 操作结论、模块主数字 |
| `--font-42` | 42px | 市场温度、情绪指数 |

### 3.3 字重

- 普通正文：400。
- 卡片标题：600。
- 强数字：700–800。
- 避免全页面大量 800 字重；只用于关键数字。

---

## 4. Spacing

```css
--space-4: 4px;
--space-6: 6px;
--space-8: 8px;
--space-10: 10px;
--space-12: 12px;
--space-14: 14px;
--space-16: 16px;
--space-18: 18px;
--space-20: 20px;
--space-24: 24px;
```

### 4.1 页面级

| 场景 | 值 |
|---|---:|
| 页面左右 padding | 24–28px |
| 顶栏到底部内容 | 16–24px |
| 一级模块之间 | 16–18px |
| 二级卡片之间 | 10–14px |
| Panel header padding | 18px 22px 0 |
| Panel body padding | 14–22px |

### 4.2 组件内部

| 组件 | 推荐 |
|---|---|
| MetricCard padding | 14–18px |
| RankItem padding | 10–14px |
| LimitCard body padding | 12–16px |
| LadderStage padding | 14px 12px |
| StockChip padding | 8px 10px |
| Tab padding | 7px 10px |

---

## 5. Radius / Shadow / Border

```css
--radius-xs: 8px;
--radius-sm: 12px;
--radius-md: 14px;
--radius-lg: 16px;
--radius-panel: 20px;
--radius-pill: 999px;

--shadow-panel: 0 18px 44px rgba(0,0,0,0.34);
--shadow-float: 0 18px 36px rgba(0,0,0,0.34);
```

规则：

- Panel 使用 20px。
- 子卡片使用 14–16px。
- 按钮 / Tab 使用 pill。
- 阴影只用于一级 Panel、Drawer、Tooltip；普通卡片靠边框和背景层次区分。

---

## 6. Layout System

### 6.1 页面容器

```css
.app-shell {
  max-width: 1480px;
  margin: 0 auto;
  padding: 24px 28px 40px;
}
```

### 6.2 首页骨架

首页推荐结构：

```text
Topbar
MarketOverview + IndexGrid
SectorLeaders + StockLeaders
NewsPanel + ActionAdvice
```

规则：

- 上方市场总览左宽右窄。
- 主要指数放右侧，4 行 3 列或 2 行 4 列取决于屏幕宽度。
- 新闻和操作建议应与上方双列对齐。

### 6.3 情绪分析页骨架

```text
EmotionHero
成交额与涨跌分布
  今日成交总额 | 今日涨跌分布
  历史成交额 | 历史涨跌
  成交额 × 市场广度联动观察
涨跌停板与连板天梯
  涨跌停板 6 卡片
  连板天梯
```

---

## 7. Core Components

### 7.1 Panel

一级模块容器。

```html
<section class="panel">
  <div class="panel-header">
    <div>
      <h2 class="panel-title">标题</h2>
      <p class="panel-subtitle">说明</p>
    </div>
    <div class="meta-note">状态</div>
  </div>
  <div class="panel-body">...</div>
</section>
```

要求：

- header 与 body 明确分离。
- 标题区不堆过多按钮。
- 状态类信息放右上角 `meta-note`。
- Panel 不嵌套超过两层。

### 7.2 MetricCard

用于温度、情绪、成交额、资金流向、晋级率等。

字段：

| 字段 | 说明 |
|---|---|
| `label` | 指标名 |
| `value` | 主值 |
| `unit` | 单位 |
| `trend` | rise / fall / flat |
| `description` | 解释 |
| `chips` | 附加事实 |

### 7.3 IndexCard

用于主要指数卡片。

字段：

| 字段 | 说明 |
|---|---|
| `name` | 指数名称 |
| `value` | 当前点位 |
| `change` | 涨跌点数 |
| `changePct` | 涨跌幅 |
| `trend` | rise / fall / flat |

卡片规则：

- 不在卡片内堆过多标签。
- 点位使用等宽数字。
- 涨跌点数和涨跌幅同色展示。

### 7.4 RankList

用于板块领涨领跌、个股领涨领跌。

字段：

| 字段 | 说明 |
|---|---|
| `rank` | 排名 |
| `name` | 名称 |
| `desc` | 逻辑描述 |
| `meta` | 热度、换手、成交额等 |
| `changePct` | 涨跌幅 |
| `trend` | rise / fall |

### 7.5 ChartCard

用于历史成交额、历史涨跌。

要求：

- 必须有图例。
- 必须有 5/10/20 日切换。
- hover 日期后联动更新所有相关图和解读卡。
- x 轴使用日期，y 轴使用对应数值。
- tooltip 内容最多 3 行。

### 7.6 LimitBoard

涨跌停板模块。

推荐结构：

```text
涨停板 | 涨停封板率 | 涨停打开 | 跌停板 | 跌停封板率 | 跌停打开
```

要求：

- 六卡片横向铺开。
- 左三张使用涨色系，右三张使用跌色系。
- 每张卡片内部结构一致：标题 / 今日 / 昨日 / 变化。

### 7.7 LadderStage

连板天梯列。

字段：

| 字段 | 说明 |
|---|---|
| `level` | 首板 / 2板 / 3板... |
| `count` | 数量 |
| `promotionRate` | 晋级率 |
| `eliminationRate` | 淘汰率 |
| `stocks` | 代表股 |
| `hint` | 梯队提示 |

交互：

- 首板在左，高板在右。
- 点击数量或“查看全部”打开右侧抽屉。
- 只展示代表股，不在天梯中展开完整股票列表。

### 7.8 Drawer

用于查看连板股票完整列表。

要求：

- 右侧滑出。
- 标题包含梯队和数量。
- 支持搜索、排序、行业筛选。
- 列表字段：股票名、题材、换手、封单、状态。

---

## 8. Interaction Patterns

### 8.1 页面 Tab

- 顶部 Tab 用于一级页面切换：首页、情绪分析、市场温度、资金面等。
- 当前激活状态使用红金弱渐变。
- 未启用页面点击后不应跳空白页，可保持当前页或显示“建设中”。

### 8.2 模块 Tab

用于切换：

- 领涨板块 / 领跌板块
- 领涨个股 / 领跌个股
- 今日热点 / 政策宏观 / 财经新闻 / 个股新闻
- 按连板数 / 按行业

### 8.3 Chart Hover

当用户 hover 历史图日期：

- Tooltip 显示该日明细。
- 同日期在其他图中高亮。
- 联动观察卡同步更新。
- 不改变页面布局，不弹大浮层。

### 8.4 查看全部

在连板天梯中：

- 点击梯队数量。
- 点击“查看全部 N 只”。
- 触发右侧 Drawer。

---

## 9. Data ViewModel 建议

### 9.1 首页 ViewModel

```ts
interface MarketHomeViewModel {
  snapshot: {
    summary: string;
    marketTemperature: ScoreMetric;
    emotionScore: ScoreMetric;
    tradeSuitability: SuitabilityMetric;
  };
  indices: IndexCardVM[];
  sectorLeaders: RankItemVM[];
  stockLeaders: RankItemVM[];
  news: NewsItemVM[];
  actionAdvice: AdviceVM;
}
```

### 9.2 情绪分析 ViewModel

```ts
interface EmotionAnalysisViewModel {
  emotionSummary: EmotionSummaryVM;
  turnover: {
    today: TurnoverTodayVM;
    history: TimeSeriesPoint[];
  };
  breadth: {
    distribution: DistributionBucket[];
    history: BreadthPoint[];
  };
  limitBoard: LimitBoardVM;
  ladder: LadderStageVM[];
}
```

---

## 10. 评审红线

以下问题视为 UI bug：

1. 红涨绿跌语义错误。
2. Panel 间距不一致。
3. 同类卡片高度或内部结构不一致。
4. 数字未使用等宽数字。
5. 图表无图例、无 tooltip、无时间范围切换。
6. 把完整股票列表直接塞进连板天梯主视图。
7. 使用过强霓虹、过强阴影或过亮渐变破坏专业感。
8. 页面字号整体过大，呈现“老年版”观感。
9. 新闻、操作建议等双列模块没有对齐。
10. Drawer、Tooltip、Tab 等交互没有 active / hover / empty 状态。

---

## 11. 推荐落地目录

```text
src/
  design/
    tokens.css
    theme.ts
  components/
    ui/
      Panel/
      Tabs/
      Drawer/
      Tooltip/
      ChartCard/
      MetricCard/
    domain/
      PriceText/
      ChangeText/
      IndexCard/
      RankList/
      LimitBoard/
      LadderStage/
      MarketBreadthChart/
      TurnoverChart/
  features/
    market-home/
    emotion-analysis/
```
