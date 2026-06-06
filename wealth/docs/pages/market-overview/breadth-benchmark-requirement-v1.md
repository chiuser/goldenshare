# 市场总览｜涨跌分布标杆需求 v1（benchmark-requirement）

> 用途：定义“涨跌分布”模块的业务边界与固定规则。  
> 阶段：需求冻结前。  
> 产物性质：业务规则事实源（不是实现细节文档）。

关联文档：

1. [涨跌分布技术实施方案 v1（仅方案）](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/breadth-implementation-design-v1.md)
2. [涨跌分布 M2 编码前门禁 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/breadth-m2-coding-gate-v1.md)

---

## 1. 目标与定位

1. 模块目标：输出“上涨/下跌/平盘家数 + 近 1 月/3 月上涨下跌趋势线”的客观事实。
2. 用户价值：用户快速判断当日市场广度与近阶段赚钱效应变化。
3. 业务定位：市场总览首屏核心模块，提供客观统计，不输出主观建议。

---

## 2. 范围与边界

### 2.1 本期覆盖

1. 指标卡：上涨家数、下跌家数、平盘家数（分别展示红盘率/绿盘率/平盘率）。
2. 图表模式：右上角只提供 `涨跌家数` 与 `涨跌分布` 两个切换按钮。
3. `涨跌家数`：复用当前 `1个月` 上涨家数 / 下跌家数双折线图，不改变折线图视觉。
4. `涨跌分布`：使用当日 `distributionBuckets + flatCount` 渲染分桶柱状图，仅展示柱状图本体，不展示底部“涨跌 / 涨停 / 跌停”等汇总文字。
3. API 契约：后端返回当日与历史点的完整市场宽度事实字段，包括涨跌幅分桶字段。
4. 前端接收：前端 DTO 必须接收分桶字段，但当前 UI 只使用 `up/down/flat/total/redRate` 相关 count 字段。
5. 模块级 debug 状态（仅调试模式）。

### 2.2 本期不覆盖

1. 不渲染涨跌幅区间柱状分布图；分桶字段仅作为契约预埋，后续需求再决定 UI。
2. 不做可配置时间范围。
3. 不做前端样式/交互改造。

### 2.3 与其他模块边界

1. 上游依赖：`goldenshare_serving.share_fact_market_breadth_daily`、`core_serving.trade_calendar`。
2. 下游消费者：`MarketBreadthPanel`。
3. 职责分割：
   - 本模块只负责涨跌广度事实；
   - 不负责市场风格、成交额、资金流或榜单逻辑；
   - 不负责在 Web 后端重新计算涨跌幅分桶。

---

## 3. 核心原则（硬约束）

1. 无配置能力：本模块不接入策略配置中心，不读取任何模块策略配置文件。
2. 固定图表模式：仅支持 `涨跌家数` 与 `涨跌分布`。
3. UI 结构不变：保持当前模块标题、3 卡片、图表容器和 RangeSwitch 位置不变；RangeSwitch 语义改为图表模式切换。
4. 图表纵轴冻结：纵轴从 `0` 开始，固定刻度值为 `0/1500/3000/4500/6000`。
5. 统计口径冻结：基于 `goldenshare_serving.share_fact_market_breadth_daily` 的单日市场宽度事实行直接读取；Web 后端不得再通过 `equity_daily_bar.pct_chg` 自行聚合。
6. 分桶字段冻结：后端必须返回涨跌幅分桶字段，前端 DTO 必须接收；`涨跌分布` 模式必须使用这些字段渲染柱状图。

禁止事项：

1. 临时增加 `6个月`、`12个月` 等范围；
2. 在 `涨跌分布` 柱状图下方增加底部汇总文字；
3. 前端自行计算涨跌家数；
4. Web 后端自行按个股日线明细重新聚合本模块主指标。

---

## 4. 业务对象模型（非代码，先语义）

1. `MarketBreadthPanel`：涨跌分布模块返回根对象。
2. `BreadthMetrics`：当日核心指标。
3. `BreadthDistributionBuckets`：涨跌幅分桶计数事实。
4. `BreadthHistoryPoint`：历史趋势点。

字段语义要求：

| 对象 | 字段 | 含义 | 单位 | 可空 | 产出责任 | 缺失降级 |
|---|---|---|---|---|---|---|
| `MarketBreadthPanel` | `tradeDate` | 模块观测交易日 | - | 否 | 后端 | 缺失即异常 |
| `BreadthMetrics` | `upCount` | 当日上涨家数 | 家 | 否 | 后端 | 缺失即异常 |
| `BreadthMetrics` | `downCount` | 当日下跌家数 | 家 | 否 | 后端 | 缺失即异常 |
| `BreadthMetrics` | `flatCount` | 当日平盘家数 | 家 | 否 | 后端 | 缺失即异常 |
| `BreadthMetrics` | `totalCount` | 当日参与统计总家数 | 家 | 否 | 后端 | 缺失即异常 |
| `BreadthMetrics` | `redRate` | 红盘率 | % | 否 | 后端 | 缺失即异常 |
| `BreadthMetrics` | `distributionBuckets` | 涨跌幅分桶事实 | - | 否 | 后端 | 缺失即异常 |
| `BreadthDistributionBuckets` | `downGt10Count` | 跌幅大于 10% 家数 | 家 | 否 | 后端 | 缺失即异常 |
| `BreadthDistributionBuckets` | `down7To10Count` | 跌幅 7% 到 10% 家数 | 家 | 否 | 后端 | 缺失即异常 |
| `BreadthDistributionBuckets` | `down5To7Count` | 跌幅 5% 到 7% 家数 | 家 | 否 | 后端 | 缺失即异常 |
| `BreadthDistributionBuckets` | `down3To5Count` | 跌幅 3% 到 5% 家数 | 家 | 否 | 后端 | 缺失即异常 |
| `BreadthDistributionBuckets` | `down0To3Count` | 跌幅 0% 到 3% 家数 | 家 | 否 | 后端 | 缺失即异常 |
| `BreadthDistributionBuckets` | `up0To3Count` | 涨幅 0% 到 3% 家数 | 家 | 否 | 后端 | 缺失即异常 |
| `BreadthDistributionBuckets` | `up3To5Count` | 涨幅 3% 到 5% 家数 | 家 | 否 | 后端 | 缺失即异常 |
| `BreadthDistributionBuckets` | `up5To7Count` | 涨幅 5% 到 7% 家数 | 家 | 否 | 后端 | 缺失即异常 |
| `BreadthDistributionBuckets` | `up7To10Count` | 涨幅 7% 到 10% 家数 | 家 | 否 | 后端 | 缺失即异常 |
| `BreadthDistributionBuckets` | `upGt10Count` | 涨幅大于 10% 家数 | 家 | 否 | 后端 | 缺失即异常 |
| `MarketBreadthPanel` | `historyByRange` | 各时间范围趋势点 | - | 否 | 后端 | 空数组 + 模块 empty |
| `BreadthHistoryPoint` | `tradeDate` | 历史交易日 | - | 否 | 后端 | 丢弃异常点 |
| `BreadthHistoryPoint` | `upCount` | 当日上涨家数 | 家 | 否 | 后端 | 丢弃异常点 |
| `BreadthHistoryPoint` | `downCount` | 当日下跌家数 | 家 | 否 | 后端 | 丢弃异常点 |
| `BreadthHistoryPoint` | `flatCount` | 当日平盘家数 | 家 | 否 | 后端 | 丢弃异常点 |
| `BreadthHistoryPoint` | `totalCount` | 当日参与统计总家数 | 家 | 否 | 后端 | 丢弃异常点 |
| `BreadthHistoryPoint` | `redRate` | 当日红盘率 | % | 否 | 后端 | 丢弃异常点 |
| `BreadthHistoryPoint` | `distributionBuckets` | 当日涨跌幅分桶事实 | - | 否 | 后端 | 丢弃异常点 |

---

## 5. 数据来源与映射（事实层）

| 业务字段 | 来源表 | 来源列 | 转换规则 | 备注 |
|---|---|---|---|---|
| `tradeDate` | `core_serving.trade_calendar` | `trade_date` | date -> `YYYY-MM-DD` | 用于期望交易日与窗口解析 |
| `upCount` | `goldenshare_serving.share_fact_market_breadth_daily` | `up_count` | 直接读取 | 单日事实行 |
| `downCount` | `goldenshare_serving.share_fact_market_breadth_daily` | `down_count` | 直接读取 | 单日事实行 |
| `flatCount` | `goldenshare_serving.share_fact_market_breadth_daily` | `flat_count` | 直接读取 | 单日事实行 |
| `totalCount` | `goldenshare_serving.share_fact_market_breadth_daily` | `total_count` | 直接读取 | 单日事实行 |
| `redRate` | `goldenshare_serving.share_fact_market_breadth_daily` | `red_rate` | 直接读取 | 不在 Web 后端重算 |
| `distributionBuckets.downGt10Count` | `goldenshare_serving.share_fact_market_breadth_daily` | `down_gt_10_count` | 直接读取 | `涨跌分布` 柱状图展示 |
| `distributionBuckets.down7To10Count` | `goldenshare_serving.share_fact_market_breadth_daily` | `down_7_10_count` | 直接读取 | `涨跌分布` 柱状图展示 |
| `distributionBuckets.down5To7Count` | `goldenshare_serving.share_fact_market_breadth_daily` | `down_5_7_count` | 直接读取 | `涨跌分布` 柱状图展示 |
| `distributionBuckets.down3To5Count` | `goldenshare_serving.share_fact_market_breadth_daily` | `down_3_5_count` | 直接读取 | `涨跌分布` 柱状图展示 |
| `distributionBuckets.down0To3Count` | `goldenshare_serving.share_fact_market_breadth_daily` | `down_0_3_count` | 直接读取 | `涨跌分布` 柱状图展示 |
| `distributionBuckets.up0To3Count` | `goldenshare_serving.share_fact_market_breadth_daily` | `up_0_3_count` | 直接读取 | `涨跌分布` 柱状图展示 |
| `distributionBuckets.up3To5Count` | `goldenshare_serving.share_fact_market_breadth_daily` | `up_3_5_count` | 直接读取 | `涨跌分布` 柱状图展示 |
| `distributionBuckets.up5To7Count` | `goldenshare_serving.share_fact_market_breadth_daily` | `up_5_7_count` | 直接读取 | `涨跌分布` 柱状图展示 |
| `distributionBuckets.up7To10Count` | `goldenshare_serving.share_fact_market_breadth_daily` | `up_7_10_count` | 直接读取 | `涨跌分布` 柱状图展示 |
| `distributionBuckets.upGt10Count` | `goldenshare_serving.share_fact_market_breadth_daily` | `up_gt_10_count` | 直接读取 | `涨跌分布` 柱状图展示 |
| `historyByRange[*]` | `goldenshare_serving.share_fact_market_breadth_daily` | 同上 | 按交易日窗口读取并升序输出 | `1m`=22 点，`3m`=62 点 |

补充：

1. 来源优先级：单源 `share_fact_market_breadth_daily`。
2. 回退策略：不跨日补值；数据落后时标记 delayed。
3. 时效语义：盘后快照语义（非实时流）。
4. 行唯一性：业务契约要求每个 `trade_date` 至多一行；若发现重复行，属于上游事实表异常，模块应报错或拒绝静默合并。
5. 历史趋势展示：`涨跌家数` 模式仍只画 1 个月上涨/下跌两条线；历史点返回的平盘、总数、红盘率和分桶字段为后续能力预埋。
6. 分桶柱状图展示顺序固定：`跌 >10%`、`跌 7~10%`、`跌 5~7%`、`跌 3~5%`、`跌 0~3%`、`平盘`、`涨 0~3%`、`涨 3~5%`、`涨 5~7%`、`涨 7~10%`、`涨 >10%`；其中 `平盘` 使用 `flatCount`，其余使用 `distributionBuckets`。
7. 分桶比例不作为 API 独立字段；如前端展示比例，只能基于 `bucketCount / totalCount` 派生，不允许后端和前端各自定义不同口径。

---

## 6. 状态语义

1. 页面级状态：`READY/PARTIAL/DELAYED/EMPTY/ERROR`。
2. 模块级状态（debug）：返回 `expectedTradeDate/observedTradeDate/lagDays/status/note`。
3. delayed 判定：`observedTradeDate < expectedTradeDate`。
4. partial 判定：本模块 delayed/empty 且其他模块可用。

---

## 7. 异常语义

1. 异常对象结构：`module/code/severity/message/details`。
2. 用户可见策略：正式态不展示异常码。
3. debug 可见策略：`debug=1` 返回模块异常明细（生产禁用）。

异常码要求：

1. 必须登记到 [exception-code-registry.md](/Users/congming/github/goldenshare/wealth/docs/system/exception-code-registry.md)。
2. 未登记异常码禁止进入代码与 API 契约。

---

## 8. API 契约（需求层）

1. 接口路径：`GET /api/v1/wealth/market/breadth`。
2. 请求参数：`market/tradeDate/debug`。
3. 响应结构：`tradingDay + pageStatus + breadth + debugInfo?`。
4. 字段命名规则：lowerCamelCase + 语义化字段。
5. 向后兼容策略：本轮是契约升级，必须同步前后端 DTO 和测试；不得让前端继续只知道旧字段。
6. 分桶字段策略：后端返回、前端接收，`涨跌分布` 模式用于柱状图展示。

---

## 9. 验收标准

1. 功能验收：返回当日 3 指标 + `1m/3m` 历史数据；UI 按 `涨跌家数/涨跌分布` 两种图表模式切换。
2. 契约验收：当日指标和历史点均包含 `totalCount` 与完整 `distributionBuckets`。
3. 语义验收：`涨跌家数` 模式只展示上涨家数、下跌家数；`涨跌分布` 模式只展示分桶柱状图，不展示底部汇总文字。
4. 状态验收：debug 可见模块 delayed/empty/error 追因。
5. 异常验收：仅使用注册表异常码。
6. 展示验收：平盘家数卡片副文案必须展示 `平盘率 x%`，不得展示“当前日统计”。
7. 图表验收：纵轴刻度必须为 `0/1500/3000/4500/6000`，不得出现负值刻度。
8. 来源验收：Web 后端不得再通过 `equity_daily_bar.pct_chg` 计算本模块指标。

---

## 10. 已确认清零项

1. 本模块不做配置化能力。
2. 图表模式固定 `涨跌家数/涨跌分布`。
3. 保持当前页面样式不变；右上角切换按钮语义改为图表模式切换。
4. 统计口径已拍板：读取 `goldenshare_serving.share_fact_market_breadth_daily`，不再由 Web 后端按个股日线明细自行聚合。
5. 本模块接入真实 API 时，必须遵守 `loading -> ready`、`timeout(5s) -> error`，且 timeout/error 不允许回填 mock 数据。
6. 本轮仅允许 `breadth` 模块 source 从当前实现切换到新的事实表来源，其余模块 source 必须保持原值不变。
7. 本轮无未决拍板项。
8. 平盘家数卡片副文案统一为 `平盘率 x%`。
9. 纵轴刻度固定为 `0/1500/3000/4500/6000`。
10. 分桶字段进入 API 和前端 DTO，并用于 `涨跌分布` 柱状图；不得展示参考图底部汇总文字。

---

## 11. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-08 | 首版：冻结涨跌分布模块边界（无配置、固定范围、UI 不变） | Codex |
| v1.1 | 2026-05-09 | 对齐模块交付清单：补充真实源 loading/error 门禁与模块 source 单模块切换约束 | Codex |
| v1.2 | 2026-05-09 | 对齐实现修复：平盘卡副文案改为平盘率；纵轴刻度固定为 0/1500/3000/4500/6000 | Codex |
| v1.3 | 2026-06-05 | 数据源口径切到 ClickHouse 市场宽度事实表；分桶字段纳入契约但 UI 暂不渲染 | Codex |
| v1.4 | 2026-06-06 | 对齐生产 fact 表新 schema：`>7%` 拆为 `7~10%` 与 `>10%`；按钮改为 `涨跌家数/涨跌分布`，分桶柱状图进入当前需求 | Codex |
