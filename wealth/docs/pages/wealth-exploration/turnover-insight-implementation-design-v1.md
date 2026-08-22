# 财势探查｜成交额洞察技术实施方案 v1

## 0. 文档状态

- 状态：已开发、部署并验收闭环
- 编写日期：2026-08-21
- 适用仓库：`/Users/congming/github/goldenshare`
- 目标页面：财势探查（Wealth Exploration）
- Figma 文件：`RADlZzREU4lPVviYfkLy6x`
- Figma 页面与事实节点：
  - Loaded 页面：`11 Wealth Exploration - Desktop Loaded`（`741:52`）
  - 行业板块：`741:53`，成交额洞察实例 `807:164`
  - 概念板块：`751:52`，成交额洞察实例 `807:309`
  - 地域板块：`752:102`，成交额洞察实例 `807:434`
  - 组件页：`11.5 Wealth Exploration - Components`（`797:2`）
  - 状态与交互页：`11.8 Wealth Exploration - States and Interaction Notes`（`797:3`）
- 事实基线：当前代码与 2026-08-21 正式只读数据审计

2026-08-22 开发收口：独立后端接口、财势探查页面、共享顶部栏/面包屑/时间上下文、单 Canvas 双图区和六态均已按本方案落地；自动化测试、TypeScript 类型检查和生产构建通过。开发阶段按约定未启动服务或部署。

2026-08-22 验收闭环：用户已完成部署和浏览器人工验收，功能与视觉效果均未发现问题。本需求正式闭环，后续若调整业务口径应作为新需求重新评审。

2026-08-22 补充冻结：

- 既有行情首页半小时成交额来自预计算表 `core_serving.wealth_market_turnover_snapshot`；新模块读取该表的 `freq=1`，不在线扫描分钟明细。
- 成交额洞察建立独立后端 endpoint、query service、schema、状态和异常，不复用首页 turnover API 或其服务合同。
- 财势探查页面直接复用行情首页的 `TopMarketBar` 和 Breadcrumb 视觉/DOM 实现；面包屑固定为 `财势乾坤 / 财势探查`。
- 页面公共时间口径与行情首页完全一致，继续支持相同的 `market`、`tradeDate` 参数，并以共享 Market Context 为页面唯一时间事实。

本文档是“成交额洞察”模块的技术实施方案，不是低层设计。当前评审通过的 Figma 直接承担视觉/交互 benchmark；不再新增重复的 benchmark requirement 或独立 coding-gate。LLD 必须把本文约束映射到具体符号、测试、验收步骤和内嵌编码门禁矩阵。

## 1. 目标

在财势探查页面的板块雷达上方新增“成交额洞察”模块，用一分钟全市场成交额快照对比最近完整交易日与上一交易日的盘中累计成交额走势。

模块需要同时回答三个问题：

1. 最近完整交易日累计成交额是多少。
2. 上一交易日总成交额是多少。
3. 最近完整交易日每一分钟相对上一交易日同一时刻多成交或少成交多少。

模块由三部分组成：

- 三个紧凑摘要卡片：当日累计成交额、昨日总成交额、较昨日累计增减。
- 上图：当日与昨日累计成交额曲线。
- 下图：当日累计成交额与昨日同一时刻累计成交额的差值柱状图。

## 2. 明确不做

- 不做全天成交额预测。
- 不做实时行情接入；“当日”固定表示页面上下文选中的最近完整交易日。
- 不扫描股票一分钟原始湖文件服务在线请求。
- 不在前端累计一分钟成交额。
- 不在前端计算当日与昨日差值。
- 不在前端执行“千元转亿元”或金额取整。
- 不复用首页成交额总览的固定五点 DTO 冒充本模块接口。
- 不 import 或调用首页 `MarketTurnoverQueryService`、`TurnoverQuery`、旧 schema、旧 status resolver 或旧 exception builder。
- 不把成交额洞察并入板块雷达内部状态或接口。
- 不增加面向用户的计算参数、频率开关或市场开关。

## 3. 已冻结的产品与交互口径

### 3.1 页面位置

- `11 Wealth Exploration - Desktop Loaded` 是财势探查页面，不再被定义成仅承载板块雷达的页面。
- 成交额洞察位于板块雷达上方。
- 成交额洞察和板块雷达是两个独立业务模块，只由页面负责顺序编排。

### 3.2 摘要卡片

固定展示三个卡片：

1. 当日累计成交额。
2. 昨日总成交额。
3. 较昨日累计增减。

展示规则：

- 金额单位固定为“亿”。
- 不显示小数，按四舍五入取整数。
- 第一个卡片左边沿与上图 09:30 纵向网格线对齐。
- 卡片宽度按可完整容纳 `18,921亿` 一类金额设计，不保留大块无意义留白。
- 摘要卡片与曲线、差值柱均来自同一组一分钟快照事实，禁止混用其它日线汇总表。

### 3.3 上图累计曲线

- 当日累计成交额：红色曲线。
- 昨日累计成交额：白色曲线。
- 图例整体靠右，仅保留图例，不显示“对比某日/某日”等额外说明。
- 图例横线与文字垂直居中。
- 横坐标按交易时段每 15 分钟标记。
- 不伪造午间休市点；下午首个实际一分钟点为 13:01，因此不创建 13:00 数据点。

### 3.4 下图差值柱

每个时间点的定义固定为：

```text
累计差值(t) = 当日从开盘累计至 t 的成交额 - 昨日从开盘累计至 t 的成交额
```

该指标不是“当前一分钟成交额减去昨日同一分钟成交额”。

- 正值使用红色柱。
- 负值使用绿色柱。
- 显示 0 轴。
- 上下图共享同一时间网格和可视宽度。

### 3.5 联动交互

- 上下图共享一条纵向 crosshair。
- hover 任一图时，另一图同步到同一时间点。
- tooltip 同时显示时间、当日累计、昨日累计和累计差值。
- tooltip 只消费后端已换算、已取整的“亿”值，不做领域计算。

### 3.6 Figma 组件、状态与响应式事实

组件页固定提供：

- `PageBreadcrumb / Wealth Exploration`（`802:14`）。
- `TurnoverMetricCard` 三种类型（`803:14`）：Current、Previous、Delta。
- `TurnoverLegendItem` 两种类型（`803:23`）：Current、Previous。
- `TurnoverTooltip`（`804:13`）。
- `TurnoverInsight` 六种状态（`805:639`）：Loaded、Delayed、Partial、Loading、Empty、Error。
- `TurnoverHoverLayer` 两种状态（`808:68`）：Idle、Active。
- `DimensionTab`（`804:20`）属于板块雷达维度切换，不属于成交额洞察业务组件。

状态与交互页固定提供：

- 六态矩阵：`809:55`、`809:163`、`809:271`、`809:374`、`809:391`、`809:404`。
- 1366 宽度参考：`809:417`，成交额洞察参考宽度 `1330`。
- Hover 交互样例：`809:583`。

三个 Loaded 页面使用同一个 `TurnoverInsight` 主组件。行业/概念/地域只改变板块雷达维度，不能给成交额接口增加 dimension 参数，不能因维度切换重新计算、重新请求或重置成交额洞察状态。

1366 参考用于证明模块在 `1330px` 内容宽度下不裁切、不重叠；实现不得使用 CSS `transform: scale(...)` 或按视口缩放字体。当前全局宽桌面最小宽度规则保持不变，本需求不修改全站 viewport 策略。

## 4. 开发前代码审计（保留为实现依据）

### 4.1 开发前财势探查页面尚未接入路由

当前 `wealth/src/app/routes/WealthRouter.tsx` 只显式装配：

- 登录页。
- 股票详情页。
- 指数详情页。
- 其余 Wealth 路径回落到行情首页。

仓库中尚无正式的 `WealthExplorationPage`。因此本需求不是向现有板块雷达 React 页面插入一个组件，而是需要先建立财势探查页面壳和明确路由。

建议固定前端路径：

```text
/wealth/exploration
```

`WealthRouter` 必须显式匹配该路径，确保 `/wealth/exploration` 不再被静默识别成行情首页。

本轮只增加财势探查的显式匹配，不顺手改变其它未知 Wealth 路径的既有回落行为；未知路由治理另立范围。

### 4.2 开发前顶部导航没有真实跳转

`wealth/src/shared/ui/top-market-bar/TopMarketBar.tsx` 已展示“财势探查”，但当前按钮只触发文本 action，且“乾坤行情”为硬编码激活状态。

接入财势探查时需要把共享契约收敛为路由语义，例如：

```text
activeNav: market | exploration | ...
onNavigate(target)
```

这是共享组件契约变更，必须同步审计和修改以下消费者及测试：

- `MarketOverviewPage`
- `StockDetailPage`
- `IndexDetailPage`
- `TopMarketBar` 组件测试
- 三类页面的路由/导航测试

禁止只在财势探查页面增加一套私有导航处理。

### 4.3 开发前页面上下文被行情首页私有化

现有交易日上下文实现位于：

```text
wealth/src/features/market-overview/context/
```

行情首页使用其 `pageContext.tradeDate` 驱动各模块。成交额洞察也必须使用同一页面交易日事实，但不能从另一个页面的私有 feature 反向 import。

当前前端 adapter 只保留 `tradeDate/updateTime/sessionStatus`，丢弃了 `market/prevTradeDate/isTradingDay/timezone/source`。迁移为共享 feature 时必须保留完整页面时间合同，避免成交额洞察再次自行推导上一交易日或时区。

实现阶段应将该能力收敛到页面中立目录，例如：

```text
wealth/src/features/market-context/
```

行情首页和财势探查共同消费该契约。迁移时不保留两套上下文实现。

### 4.4 现有首页成交额接口不满足新需求

现有接口：

```text
GET /api/v1/wealth/market/turnover
```

主要实现位于：

```text
src/biz/api/wealth/market/turnover.py
src/biz/queries/wealth/market/turnover/
src/biz/schemas/wealth/market/turnover.py
src/biz/services/wealth/market/turnover/
wealth/src/features/market-overview/turnover/
```

当前行为：

- 日总额和历史趋势读取 `core_serving.equity_daily_bar`。
- 盘中部分默认读取 `freq=30` 快照。
- 盘中输出被压缩为 `09:30 / 10:30 / 11:30 / 14:00 / 15:00` 五个点。
- 只返回目标日，不返回上一交易日完整分钟曲线。
- 不返回按分钟对齐的累计差值。

因此现有接口的查询目标、DTO 和页面职责均与成交额洞察不同。新需求应建立独立模块，不扩充旧 DTO 形成两个页面互相牵制的超大接口。

“独立模块”是代码和合同边界，不是重复建设事实表。允许共享：

- `WealthMarketTurnoverSnapshot` ORM model 和底层预计算表。
- `MarketPageContextQuery`、鉴权依赖和数据库 session 等平台能力。

禁止共享：

- 旧 `/wealth/market/turnover` endpoint。
- `MarketTurnoverQueryService`、`TurnoverQuery` 和固定五点 DTO。
- 旧模块的 status resolver、exception builder 和前端 adapter/controller。

该边界必须由 import/static gate 和集成测试共同证明，不能只靠目录命名区分。

### 4.5 一分钟正式快照已经具备所需源事实

现有快照表：

```text
core_serving.wealth_market_turnover_snapshot
```

主键：

```text
(type, market, trade_date, freq)
```

该表就是现有首页半小时成交额的预计算事实源，不是本需求新增的表。快照生产器同时预计算 `1/5/15/30/60` 五种频率：首页盘中总览默认读取 `freq=30`，本模块固定读取 `freq=1`。

`points_json` 保存完整分钟数组；`amount` 和 `total_amount` 的单位为 `thousand_yuan`。快照生产器按分钟时间戳聚合全市场金额，查询层可以对一分钟金额做累计。

已存在适配最近两日查询的索引：

```text
idx_wealth_market_turnover_snapshot_lookup(
  type,
  market,
  freq,
  build_status,
  trade_date DESC
)
```

新模块正常路径读取目标日和严格上一交易日两条 `freq=1`、`READY` 快照；为受控识别 DELAYED，单次查询最多返回预期日期之前最近 4 条 READY 快照，并且只允许选出交易日历严格相邻的完整日期对。它不读取原始分钟线，也不访问 Dagster/Lake。

## 5. 正式数据只读审计

审计对象固定为：

```text
type=stock
market=CN_A
freq=1
build_status=READY
```

### 5.1 覆盖情况

正式表中 1/5/15/30/60 五个频率各有 154 个 READY 日期，覆盖：

```text
2026-01-05 至 2026-08-21
```

本模块只使用一分钟快照。

### 5.2 最近两个交易日

| 日期 | 总成交额（千元） | 换算为亿 | 前端整数展示 | 分钟点数 | 首末时间 |
| --- | ---: | ---: | ---: | ---: | --- |
| 2026-08-21 | 1,892,066,560.45 | 18,920.6656045 | 18,921亿 | 241 | 09:30-15:00 |
| 2026-08-20 | 2,093,908,324.47 | 20,939.0832447 | 20,939亿 | 241 | 09:30-15:00 |

两日结论：

- 每日均有 241 个唯一时间点。
- 两日时间集合完全一致，单边缺失时间点均为 0。
- 分钟成交额不存在负值。
- 分钟金额求和与 `total_amount` 仅有 0.04/0.06 千元的序列化精度差，可视为同一事实。
- 2026-08-21 相对 2026-08-20 的精确累计差额为约 `-2,018.42亿`，整数展示为 `-2,018亿`。

### 5.3 查询性能

最近两条一分钟 READY 快照的正式只读查询使用现有索引：

- 执行时间约 `0.083ms`。
- 命中两条记录。
- 两个 `points_json` 大小约 `5.6KB/条`。

数据源与索引足以支持在线模块。性能风险不在数据库扫描，而在于避免旧接口额外读取日线汇总、避免前后端重复计算和避免页面发起重复请求。

## 6. 目标架构

```text
WealthExplorationPage
    -> GET /api/v1/wealth/market/context?market&tradeDate
    -> shared MarketContext (page-level time fact)
    -> GET /api/v1/wealth/market/turnover-insight?market&tradeDate=<resolved>
    -> TurnoverInsightQueryService
    -> TurnoverInsightQuery
    -> core_serving.wealth_market_turnover_snapshot (normal 2 rows, bounded max 4, freq=1)
    -> backend cumulative/alignment/delta/unit conversion
    -> frontend adapter (shape only)
    -> TurnoverInsightSection
         -> TurnoverMetricCards
         -> TurnoverInsightLegend
         -> TurnoverInsightChart (single Canvas: upper + lower)
         -> TurnoverInsightTooltip / shared crosshair
```

### 6.1 后端目录

```text
src/biz/api/wealth/market/turnover_insight.py
src/biz/queries/wealth/market/turnover_insight/
  turnover_insight_query.py
  turnover_insight_query_service.py
  turnover_insight_calculator.py
src/biz/schemas/wealth/market/turnover_insight.py
src/biz/services/wealth/market/turnover_insight/
  turnover_insight_status_resolver.py
  turnover_insight_exception_builder.py
```

### 6.2 前端目录

```text
wealth/src/pages/wealth-exploration/
  WealthExplorationPage.tsx
  WealthExplorationPage.css
wealth/src/features/wealth-exploration/turnover-insight/
  api/
  model/
  ui/
wealth/src/features/market-context/
wealth/src/shared/ui/page-breadcrumb/
```

板块雷达继续使用自己的 feature 目录。页面只做布局、页面级状态和模块顺序编排。

## 7. 新 API 契约

### 7.1 Endpoint

```text
GET /api/v1/wealth/market/turnover-insight
```

查询参数：

| 参数 | 类型 | 规则 |
| --- | --- | --- |
| `tradeDate` | `YYYY-MM-DD` | 可选；语义与行情首页一致。页面先通过共享 Market Context 解析，随后对模块请求显式传入解析后的日期 |
| `market` | string | 当前仅允许 `CN_A` |
| `debug` | `0/1` | 仅 `APP_ENV in {local, dev, test}` 且值为 `1` 时返回 `debugInfo`；其它环境强制关闭 |

不开放 `freq`。该模块的事实频率固定为一分钟。

### 7.2 Response 结构

建议响应结构：

```json
{
  "status": "READY",
  "tradingDay": {
    "market": "CN_A",
    "expectedTradeDate": "2026-08-21",
    "observedTradeDate": "2026-08-21",
    "previousObservedTradeDate": "2026-08-20",
    "isTradingDay": true,
    "sessionStatus": "CLOSED",
    "timezone": "Asia/Shanghai",
    "generatedAt": "2026-08-22T10:30:00+08:00"
  },
  "asOf": "2026-08-21T20:08:17+08:00",
  "unit": "yi",
  "summary": {
    "current": {
      "amountYi": 18921,
      "displayText": "18,921亿",
      "direction": "neutral"
    },
    "previous": {
      "amountYi": 20939,
      "displayText": "20,939亿",
      "direction": "neutral"
    },
    "delta": {
      "amountYi": -2018,
      "displayText": "-2,018亿",
      "direction": "down"
    }
  },
  "axis": {
    "timeLabels": ["09:30", "09:45", "10:00", "...", "15:00"],
    "cumulative": {
      "minYi": 0,
      "maxYi": 24000,
      "zeroYi": 0,
      "ticks": ["0", "6000", "12000", "18000", "24000"]
    },
    "delta": {
      "minYi": -2400,
      "maxYi": 0,
      "zeroYi": 0,
      "ticks": ["-2400", "-1200", "0"]
    }
  },
  "series": [
    {
      "time": "09:30",
      "showAxisLabel": true,
      "currentAmountYi": 145,
      "currentDisplayText": "145亿",
      "previousAmountYi": 162,
      "previousDisplayText": "162亿",
      "deltaAmountYi": -17,
      "deltaDisplayText": "-17亿"
    }
  ],
  "message": null,
  "exceptionCode": null
}
```

规则：

- 所有金额数值进入响应前已换算成“亿”。
- 所有页面展示文本由后端生成。
- 前端 adapter 只能改字段形状，禁止重新累计、相减、换算或取整。
- `direction` 由后端根据精确差值判定，不能根据取整后可能为 0 的展示值反推。
- 不返回预测字段，也不预留伪预测字段。
- `tradingDay.expectedTradeDate/sessionStatus/timezone/generatedAt` 与共享 Market Context 同口径；`observedTradeDate` 明确实际展示数据日期，DELAYED 时不得伪装成 expected date。

纵轴合同以已评审 Figma 为准：

- 累计图区取当日、昨日两条累计曲线的最大值并增加 `10%` 展示余量，固定生成四个区间。
- 设原始极值为 `domainMax`，取 `granularity = 10 ^ max(0, floor(log10(abs(domainMax))) - 1)`，再计算 `step = ceil((domainMax * 1.10 / 4) / granularity) * granularity`；纵轴为 `0, step, 2*step, 3*step, 4*step`。当前样本得到 `0/6000/12000/18000/24000`。
- 差值图区必须包含 `0`；每个实际存在的正负方向各生成两个区间，各方向独立按其绝对极值使用同一量级规则向外取整。当前全负样本得到 `0/-1200/-2400`。
- 累计图全零时固定使用 `0..4`；差值图全零时固定使用 `-1/0/1`，防止零跨度。
- 前端只使用 API 返回的 `minYi/maxYi/ticks` 做像素映射，不重新计算刻度。

## 8. 计算口径

### 8.1 交易日选择

- 页面 URL 与行情首页一样支持 `market`、`tradeDate`；页面只调用一次共享 Context endpoint 解析公共时间。
- 成交额洞察请求必须使用 Context 返回的 `market`、`tradeDate`，不得用自己的 SQL 决定页面日期。
- 后端仍调用共享 `MarketPageContextQuery` 做参数与交易日语义校验，不能复制 20:00 切换规则。
- `tradeDate` 是页面上下文选中的 SSE 交易日。
- `previousTradeDate` 必须是交易日历中紧邻的上一 SSE 开市日。
- 禁止简单选择数据库中“任意更早的 READY 行”冒充昨日。
- 如果预期上一交易日快照缺失，模块不能跨日跳过并伪装成正常对比。

### 8.2 分钟累计

对每个交易日按 `trade_time` 升序计算：

```text
cumulative_amount(t) = sum(minute_amount <= t)
```

输入固定为 241 个唯一时间点，范围 09:30 至 15:00。计算在后端查询服务中一次完成。

### 8.3 时间对齐

READY 对比必须满足：

- 两日均恰好 241 个唯一时间点。
- 首点均为 09:30。
- 末点均为 15:00。
- 两日时间集合完全一致。
- 每分钟成交额非负。

对齐使用时间字符串/规范时间键，不按数组下标盲目 zip。

### 8.4 差值

先对精确累计值做差，再换算和取整：

```text
exact_delta(t) = exact_current_cumulative(t) - exact_previous_cumulative(t)
delta_yi(t) = round_half_up(exact_delta(t) / 100000)
```

禁止使用已取整的当日/昨日值再次相减，否则会产生双重舍入误差。

### 8.5 单位与取整

源单位为 `thousand_yuan`：

```text
1 亿人民币 = 100000 千元
```

后端统一使用 Decimal 语义执行 `ROUND_HALF_UP`：

```text
amount_yi = round_half_up(amount_thousand_yuan / 100000)
```

前端只渲染 `displayText`。

### 8.6 横轴标记

后端按交易时段生成 15 分钟标记：

- 上午：09:30 至 11:30。
- 下午：13:15 至 15:00。
- 午间休市不生成标记。
- 不伪造 13:00 数据点。

所有 241 个数据点仍参与绘图，15 分钟规则只控制横轴标签显示。

## 9. 状态与异常

### 9.1 状态定义

| 状态 | 条件 | 页面行为 |
| --- | --- | --- |
| `LOADING` | 请求未完成 | 使用与最终布局同尺寸 skeleton |
| `READY` | 当日和上一交易日快照均完整且严格对齐 | 展示三个卡片、双曲线和差值柱 |
| `DELAYED` | 预期当日尚未 READY，但有界候选中存在上一组完整相邻交易日 | 展示最近完整对比，并同时明确 expected、observed 和 `asOf` 日期 |
| `PARTIAL` | 当日可用，但上一交易日缺失或时间网格不一致 | 只展示可证明的当日摘要/曲线；昨日和差值区域禁用并说明原因 |
| `EMPTY` | 没有可展示的完整当日快照 | 展示空态，不渲染 0 值假数据 |
| `ERROR` | 查询、解析或契约异常 | 展示错误态和重试命令 |

`DELAYED` 只能回退到一组严格相邻且完整的交易日，不能跨过缺失交易日。

### 9.2 异常码

本模块使用独立前缀，不能复用首页成交额的 `TO_*`：

- `TI_SOURCE_DELAYED`
- `TI_CURRENT_SNAPSHOT_MISSING`
- `TI_PREVIOUS_SNAPSHOT_MISSING`
- `TI_TIME_GRID_MISMATCH`
- `TI_POINT_QUALITY_INVALID`
- `TI_QUERY_FAILED`

正式编码前必须先登记异常码，再实现 resolver 和 UI 映射。

## 10. 前端实现边界

### 10.1 页面壳

`WealthExplorationPage` 负责：

- 直接复用行情首页的 `TopMarketBar` 组件、相同 CSS 和相同主要指数数据接口，并设置 `activeNav=exploration`。
- 直接复用从行情首页抽出的共享 Breadcrumb 组件，保持 DOM、字体、间距、时间状态完全一致；只把路径内容配置为 `财势乾坤 / 财势探查`。
- 读取共享 `MarketContext`，只调用一次 Context endpoint。
- 将 Context 解析后的 `market/tradeDate` 显式传给 TopBar 数据请求、成交额洞察和后续页面模块。
- 展示与行情首页一致的日期、星期、时钟和 session status。
- 按顺序放置成交额洞察和板块雷达。
- 隔离模块错误，避免一个模块失败导致整页空白。

### 10.2 模块 adapter

允许：

- 将 API DTO 映射为 chart series 需要的字段名。
- 将后端状态映射到组件状态。

禁止：

- 累计 `amount`。
- 计算 delta。
- 千元转亿元。
- 金额取整或千分位格式化。
- 推导上一交易日。
- 补齐或插值缺失分钟点。

### 10.3 图表

- 上下图使用相同 plot bounds、时间 scale 和右侧轴宽。
- 上下区域使用同一个 Canvas、同一 x scale 和同一个 hover index，不建立两个需要互相同步的图表实例。
- resize 使用现有 ResizeObserver 模式，不通过 viewport 字号缩放。
- 图表销毁时释放 pointer 事件、ResizeObserver、animation frame 和 Canvas 资源。
- 空状态和错误状态不创建空 chart canvas。
- 上下区域使用同一个 Canvas 和同一套 x 坐标映射，避免两个图表实例发生时间轴漂移；前端只做像素坐标换算，不做金额领域计算。

### 10.4 视觉还原

- 使用当前 Wealth Design System token，不新增私有颜色体系。
- 当日红、昨日白、负差绿色。
- 维持紧凑金融终端密度，不把三个摘要卡片扩大成营销卡片。
- 第一个卡片左边沿和 09:30 plot grid 对齐。
- 图例靠右，线段和文字垂直居中。
- 删除 `Alignment Note` 和对比日期说明文案。

## 11. 性能与缓存

### 11.1 查询门禁

- 正常请求读取两条一分钟 READY 快照；单次有界查询最多返回 4 条，用于识别严格相邻的 DELAYED 日期对。
- 使用现有 lookup index。
- 禁止扫描 `raw_stk_mins_*`、Lake Parquet 或 Dagster event。
- 禁止为了摘要卡片额外查询 `equity_daily_bar`。
- 后端最多解析 `4 x 241` 个候选点，只对最终选中的一组 `2 x 241` 个点做累计、差值和轴合同计算。

### 11.2 性能目标

| 指标 | 目标 |
| --- | ---: |
| 数据库往返 | 1 次 |
| 快照行数 | 正常 2 行，硬上限 4 行 |
| 单日分钟点 | 241 |
| 后端 P95 | 不超过 120ms |
| 未压缩响应 | 不超过 64KB |
| 前端 API timeout | 5s |

正式只读审计的索引查询约 `0.083ms`，因此超过预算时优先排查重复请求、JSON 解析、状态装配和前端重复渲染，不通过放宽超时掩盖问题。

### 11.3 缓存

首版不新增 Redis 缓存。快照为盘后不可变读，数据库索引查询成本极低。若后续监控证明并发导致问题，再基于完整请求键增加短期缓存，不能提前引入双重事实源。

## 12. 安全与配置

- API 继续使用 `require_quote_access`。
- 当前市场固定为 `CN_A`，非法市场返回受控参数错误。
- API 参数只接受 `debug=0|1`。仅当 `APP_ENV in {local, dev, test}` 且 `debug=1` 时返回 `debugInfo`；其它环境强制关闭，不新增配置项。
- 不返回 SQL、表名、文件路径或内部堆栈。
- 本需求不新增运行配置项。
- 频率、单位、对比日和横轴标记均是冻结业务合同，不散落为页面常量或环境变量。

## 13. 影响面

### 13.1 新增范围

- 财势探查页面路由和页面壳。
- 成交额洞察后端独立模块。
- 成交额洞察前端独立 feature。
- 新异常码。

### 13.2 共享契约调整

- `TopMarketBar` 的 active nav 和导航回调。
- 页面上下文从行情首页私有 feature 收敛为共享 feature。
- 行情首页 Breadcrumb 从私有组件收敛为共享组件，DOM/CSS 不变。
- `WealthRouter` 增加显式财势探查路由；不改变其它未知路由既有行为。

### 13.3 不受影响

- 首页 `/api/v1/wealth/market/turnover` 的现有契约。
- 首页成交额总览组件。
- 股票详情和指数详情的业务 API。
- 成交额快照生产器和表结构。
- Lake、Dagster 和数据同步任务。
- 板块雷达的数据口径与服务接口。

本轮不改变 `foundation -> ops|biz|app` 依赖方向，不向 legacy `src/platform` 或 `src/operations` 写入新实现。

## 14. 测试方案

### 14.1 后端

- 正常读取指定交易日和严格上一交易日两条快照。
- 证明新 endpoint 没有 import/call 旧 `MarketTurnoverQueryService`、`TurnoverQuery`、旧 DTO/status/exception。
- 不使用“任意上一条 READY”替代预期上一交易日。
- 241 点累计值正确。
- 两日按时间键严格对齐。
- 精确 delta 后换算，避免双重舍入。
- `ROUND_HALF_UP` 的边界测试。
- 15 分钟标签覆盖上午/下午且不伪造 13:00。
- 当前缺失、上一日缺失、时间不一致、重复点、负金额分别进入正确状态。
- DELAYED 只能使用完整相邻交易日对。
- API 权限、日期、market 和 debug 边界。
- 查询实现不引用原始分钟表、Lake 或 `equity_daily_bar`。

### 14.2 前端

- `/wealth/exploration` 显式进入财势探查。
- 页面与行情首页使用同一个 Context endpoint、同名 `market/tradeDate` 参数和同一解析后的 trade date。
- Breadcrumb DOM/CSS 与行情首页一致，路径为 `财势乾坤 / 财势探查`。
- TopMarketBar 正确高亮“财势探查”，并可返回其它页面。
- 行情首页、股票详情、指数详情的共享导航无回退。
- loading/ready/delayed/partial/empty/error 全状态。
- 六态复用同一个 `TurnoverInsight` 组件，不按页面变体复制实现。
- 三个卡片展示后端整数亿文本。
- 当日红线、昨日白线、正红负绿差值柱。
- 15 分钟标签和午间休市行为正确。
- 单 Canvas 上下图区共享 x geometry、hoverIndex 和 crosshair。
- tooltip 使用同一时间点的四项数据。
- `1564px` 和 `1330px` 两种模块宽度均不裁切、不重叠，且不使用 CSS scale 或 viewport 字体缩放。
- 行业/概念/地域切换不改变成交额请求参数、不重新请求或重置成交额状态。
- 成交额洞察始终位于板块雷达上方。
- 页面不出现预测字段、预测图例或预测文案。
- 静态门禁禁止 frontend 出现累计、差值和单位换算逻辑。

### 14.3 真实只读验收

至少使用以下正式日期做只读对账：

- 2026-08-21 对 2026-08-20。
- 一个跨周末的相邻交易日对。
- 一个午间休市正常的日期。
- 一个 DELAYED 场景的固定测试数据。

验收必须对齐：

- 两日各 241 点。
- 当日卡片 `18,921亿`。
- 昨日卡片 `20,939亿`。
- 差值卡片 `-2,018亿`。
- 11:30 等代表时间点的累计值与离线 SQL 一致。

## 15. 开发里程碑

### M1：治理和合同冻结

- 以评审通过的 Figma 作为视觉/交互 benchmark。
- 以本文和 Figma 为基础完成 LLD。
- 在 LLD 中补齐编码门禁矩阵，不新增重复 coding-gate 文件。
- 登记 `TI_*` 异常码。
- 冻结新 API schema、状态和金额口径。

### M2：后端模块

- 实现 query、query service、status resolver、schema 和 API。
- 完成单位、累计、对齐、delta 和状态测试。
- 用正式只读日期做最小对账。

### M3：页面与前端模块

- 接入 `/wealth/exploration`。
- 收敛共享 MarketContext。
- 修正 TopMarketBar 导航契约及全部消费者。
- 实现摘要卡片、单 Canvas 上下图区和六态 UI。
- 将成交额洞察放置在板块雷达上方。

### M4：集成验收

- 前后端合同测试。
- 浏览器视觉和交互验收。
- 响应时间、payload 和重复请求检查。
- Figma 对照验收。
- 更新文档状态并闭环。

## 16. 编码前硬门禁

正式开发前必须全部满足：

1. Figma、本文技术方案、LLD 及其编码门禁矩阵无冲突。
2. 新 API 与旧首页 turnover API 的边界明确，并有 import/static gate 禁止复用旧 query/service/schema/status/exception。
3. TopMarketBar、Breadcrumb 和 MarketContext 的全部消费者列入修改与回归清单。
4. `TI_*` 异常码先登记、后编码。
5. 后端测试明确禁止查询原始分钟线和 `equity_daily_bar`。
6. 前端测试明确禁止金额累计、差值、换算和取整。
7. 真实只读样本继续满足 241 点和时间集合一致。
8. 代码实现不得修改快照生产、Lake 或 Dagster 主链。

## 17. 风险与处理

| 风险 | 后果 | 处理 |
| --- | --- | --- |
| 把最近任意 READY 行当昨日 | 对比日期不真实 | 使用 SSE 预期上一交易日精确查找 |
| 前端自行累计/换算 | 多端口径漂移 | 后端返回最终亿值和展示文本 |
| 新模块复用旧首页大 DTO | 两页面互相牵制 | 建立独立 endpoint 和 feature |
| 误把独立接口理解成重复建表 | 重复事实源、数据漂移 | 只共享预计算表和 ORM model，不共享旧业务接口 |
| 日总额混用其它表 | 卡片与曲线尾值不一致 | 所有内容只用一分钟快照 |
| 两日时间点错位 | 差值柱含义错误 | 按时间键严格集合对账 |
| 页面上下文继续私有化 | 页面间依赖倒置 | 收敛为共享 MarketContext |
| 新模块自行求最近日期 | 与首页同页显示日期不一致 | 页面先解析共享 Context，再把 resolved tradeDate 传给所有模块 |
| 导航只改新页面 | 旧页面高亮或返回回退 | 全量修改 TopMarketBar 消费者和测试 |
| resize 后 geometry 过期 | 上下图区、网格或 hover 错位 | 单 geometry 计算、ResizeObserver 和两种基准宽度测试 |
| 缺数据被填成 0 | 误导用户 | 使用 PARTIAL/EMPTY，不造数据 |

## 18. 方案结论

现有正式一分钟成交额快照已经完整支持本需求：最近两个完整交易日各有 241 个严格对齐的分钟点，金额、时间范围和索引性能均满足在线读取条件。无需新增数据集、无需扫描 Lake，也无需修改快照生产链路。

真正的开发工作集中在三处：

1. 建立独立的成交额洞察后端 API，在后端完成累计、对齐、差值、亿元换算和整数展示合同。
2. 建立正式财势探查页面与独立前端 feature，还原 Figma 中的摘要卡片、双曲线和累计差值柱。
3. 收敛 TopMarketBar、Breadcrumb 和 MarketContext 三个共享契约，保证页面顶部结构、面包屑和时间事实与行情首页一致，同时不让行情首页和详情页产生回退。

本方案没有未决业务口径。LLD 已落于 `turnover-insight-low-level-design-v1.md`，M1 至 M5、自动化验证、部署和浏览器人工验收均已完成，本需求正式闭环。
