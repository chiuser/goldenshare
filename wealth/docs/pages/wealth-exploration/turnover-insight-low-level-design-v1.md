# 财势探查｜成交额洞察低层设计 v1

## 0. 文档状态

- 状态：基础版本已开发、部署并验收闭环；5日/20日均值首轮实现已部署，视觉修订已冻结，待代码修正和用户复验
- 编写日期：2026-08-22
- 适用仓库：`/Users/congming/github/goldenshare`
- 上游技术方案：`wealth/docs/pages/wealth-exploration/turnover-insight-implementation-design-v1.md`
- Figma 文件：`RADlZzREU4lPVviYfkLy6x`
- Figma Loaded 页面：`11 Wealth Exploration - Desktop Loaded`（`741:52`）
- Figma 组件页：`11.5 Wealth Exploration - Components`（`797:2`）
- Figma 状态与交互页：`11.8 Wealth Exploration - States and Interaction Notes`（`797:3`）
- 目标路由：`/wealth/exploration`
- 目标 endpoint：`GET /api/v1/wealth/market/turnover-insight`
- 事实审计截止：2026-08-22
- 待拍板项：无

本文档只设计“成交额洞察”及其接入财势探查页面所必需的共享契约。它不实现板块雷达、不修改成交额快照生产、不修改 Dagster/Lake、不扩展旧首页 turnover API。

2026-08-22 补充功能开发完成：基础版本的历史实现与验收记录继续保留；第 15 节定义的 5 日/20 日成交额均值卡片与上图参考线已经落地并通过自动化验证。补充功能尚未经过用户部署与浏览器视觉验收，不得提前标记为验收闭环。

2026-08-23 视觉修订开发完成：首轮部署暴露出的均值标签重叠、虚线节奏偏长、图例缺少均值说明、均值卡金额与线色未建立视觉映射四个问题，已按 Figma 和第 15 节口径完成代码修正。目标测试、全量前端测试、TypeScript 检查和生产构建均通过；待用户部署与视觉复验，尚不标记为验收闭环。

## 1. 冻结口径与代码约束

| 冻结口径 | 代码落点 | 必须证明的测试 |
| --- | --- | --- |
| 在线事实来自预计算表 | `WealthMarketTurnoverSnapshot`，固定 `type=stock/market=CN_A/freq=1/build_status=READY` | 新 query 不引用 `RawStkMins`、Lake 或 Dagster |
| 旧首页半小时数据和新模块共享表事实 | 旧模块继续读取 `freq=30`；新模块独立读取 `freq=1` | 旧 turnover API 回归；新 API 只读取一分钟快照 |
| 5/20 日均值与首页同口径 | 页面中立 `TurnoverDailyAverageQuery`，固定读取最近 20 个 SSE 开市日及 `EquityDailyBar.amount` 日聚合 | 同日期两个 API 的 `avg5d/avg20d` 对账完全一致 |
| 后端接口完全独立 | 新 endpoint/query/service/schema/status/exception | static gate 禁止 import 旧 turnover 业务类 |
| 页面公共时间与首页一致 | 共享 `MarketPageContextQuery` 和前端 `market-context` feature | 两页同参数得到同一 `tradeDate/prevTradeDate/sessionStatus` |
| 页面顶部结构与首页一致 | 直接复用 `TopMarketBar`、共享 `PageBreadcrumb`、共享 CSS | DOM/class/导航高亮和面包屑路径测试 |
| Breadcrumb 内容表示页面层级 | `财势乾坤 / 财势探查` | 不出现“成交额洞察”或“板块雷达”层级 |
| 金额在后端换算 | 后端 `Decimal` 累计、相减、`ROUND_HALF_UP` | 前端不存在 `/100000`、累计或 delta 计算 |
| 展示金额无小数，单位为亿 | API 返回整数 `amountYi` 和 `displayText` | 卡片、tooltip、轴标签逐项断言 |
| 当日红、昨日白 | `TurnoverInsightChart` design token 映射 | canvas draw command/截图验收 |
| 均值卡片与参考线 | `summary.avg5d/avg20d` + 单 Canvas 上图虚线 | 五卡布局；品牌金/紫色 `4/4` 虚线；高值标签在线上、低值标签在线下；四项图例；均值卡金额与线色一致；下图和 tooltip 无均值内容 |
| 差值是累计差值 | 后端 `current cumulative - previous cumulative` | 反例证明不是单分钟差值 |
| 横轴每 15 分钟 | 后端返回 `showAxisLabel`；前端不重新判定业务时点 | 17 个标签，无 13:00 |
| 无预测 | schema、组件和文案均无 forecast 字段 | response extra forbid + 前端文本门禁 |
| 成交额洞察位于板块雷达上方 | `WealthExplorationPage` 模块顺序 | DOM 顺序测试；本轮不实现板块雷达业务 |
| 三个板块维度复用同一成交额组件 | `TurnoverInsightSection` 位于无业务内容的 `sector-radar` slot 之外 | 本轮静态证明请求合同不含 dimension、组件位于 slot 之前；真实维度切换回归留到板块雷达接入阶段 |
| 六种设计状态只有一套组件实现 | `TurnoverInsightSection` 根据 viewState 分支，复用同一组件树 | 六态组件测试；禁止复制六份页面 JSX |
| 1366 参考不裁切 | 模块内容宽度 `1330px` 时重算 canvas geometry | 1366 组件级截图/几何测试；禁止 CSS scale 和视口字体缩放 |

## 2. 开发前实现审计（保留为改动基线）

### 2.1 预计算表与生产链

当前 model：

```text
src/foundation/models/core_serving/wealth_market_turnover_snapshot.py
```

物理表：

```text
core_serving.wealth_market_turnover_snapshot
```

主键和查找索引：

```text
PK(type, market, trade_date, freq)
idx_wealth_market_turnover_snapshot_lookup(
  type,
  market,
  freq,
  build_status,
  trade_date
)
```

生产器 `TurnoverSnapshotMaterializeService` 已固定支持 `1/5/15/30/60` 五种频率。它从分钟事实生成 `points_json`，每个点包含：

```text
tradeTime
tradeTimeTs
amount
vol
securityCount
```

`amount`、`total_amount` 的单位均为 `thousand_yuan`。正式 PostgreSQL 中 `points_json` 的物理类型为 `jsonb`，ORM 使用 SQLAlchemy `JSON` 映射；本需求不做迁移，也不改变该列。

结论：用户记忆中的“每半小时预计算表”已经审计到。首页 `TurnoverQuery.load_intraday_cumulative(..., freq=30)` 读取的就是该表；新模块固定读取同一表的 `freq=1`，而不是再建表或在线扫描分钟线。

### 2.2 旧首页 turnover 模块边界

旧链路：

```text
GET /api/v1/wealth/market/turnover
  -> MarketTurnoverQueryService
  -> TurnoverQuery
  -> EquityDailyBar + freq=30 turnover snapshot
  -> 固定五个日内点
```

旧模块同时包含日总额、5/20 日均值、1/3 月历史和固定五点盘中曲线。其 schema 将 `intradayCumulative` 限定为恰好 5 条。因此本需求禁止复用：

```text
src.biz.queries.wealth.market.turnover.turnover_query.TurnoverQuery
src.biz.queries.wealth.market.turnover.turnover_query_service.MarketTurnoverQueryService
src.biz.schemas.wealth.market.turnover.*
src.biz.services.wealth.market.turnover.turnover_status_resolver.*
src.biz.services.wealth.market.turnover.turnover_exception_builder.*
wealth/src/features/market-overview/turnover/**
```

允许复用的只有 ORM model、数据库 session、鉴权、通用异常壳和共享页面时间能力。

### 2.3 共享时间现状

后端权威实现：

```text
src/biz/queries/wealth/market/context/market_page_context_query.py
GET /api/v1/wealth/market/context
```

当前规则包括：

- 市场固定 `CN_A`。
- SSE 交易日历决定 `tradeDate/prevTradeDate`。
- 当前开市日 20:00 前默认选择上一开市日，20:00 后选择当前开市日。
- session status 使用 `Asia/Shanghai` 和 `PRE_OPEN/TRADING/BREAK/CLOSED`。

前端实现目前位于行情首页私有目录：

```text
wealth/src/features/market-overview/context/api/
```

且 adapter 丢弃了 `market/prevTradeDate/isTradingDay/timezone/source`。本轮必须将其移动到页面中立 feature，并保留完整合同；不复制第二套 20:00 或上一交易日规则。

### 2.4 路由现状

`WealthRouter` 当前只显式识别登录、股票详情、指数详情；其余路径直接渲染 `MarketOverviewPage`。因此 `/wealth/exploration` 目前会被误当成首页。

本轮只增加财势探查精确匹配，不扩大为全站 404 重构：

```text
if isWealthExplorationPath(pathname):
    render WealthExplorationPage(search)
else:
    preserve current fallback
```

### 2.5 TopMarketBar 现状与影响面

`TopMarketBar` 当前：

- 硬编码“乾坤行情”为 active。
- 所有点击通过 `onAction(message)` 返回文本，没有真实路由语义。
- 被行情首页、股票详情、指数详情共同消费。

CodeGraph 与 import 审计覆盖：

```text
wealth/src/pages/market-overview/MarketOverviewPage.tsx
wealth/src/pages/stock-detail/StockDetailPage.tsx
wealth/src/pages/index-detail/IndexDetailPage.tsx
wealth/src/shared/ui/top-market-bar/TopMarketBar.test.tsx
对应三个页面测试
```

因此必须一次性更新全部消费者，不能只在新页面包一层私有导航。

### 2.6 Breadcrumb 现状

行情首页 Breadcrumb 当前位于：

```text
wealth/src/features/market-overview/layout/Breadcrumb.tsx
```

它已经实现：

- 日期、星期、秒级时钟。
- session status 中文映射。
- 与首页一致的 DOM/class。

但路径硬编码为 `财势乾坤 / 乾坤行情 / 市场总览`，CSS 混在 `market-overview-page.css`。本轮将组件和对应 CSS 移到 shared，不保留旧 wrapper。

股票/指数详情的 `*BreadcrumbActionBar` 是详情页另一种“返回首页”组件，不在本轮替换范围。

### 2.7 Figma 设计事实

三个 Loaded frame：

| 变体 | Frame | Breadcrumb 实例 | Turnover 实例 | DimensionTab 实例 |
| --- | --- | --- | --- | --- |
| Industry | `741:53` | `807:152` | `807:164` | `807:289` / `807:291` / `807:294` |
| Concept | `751:52` | `807:297` | `807:309` | `807:414` / `807:417` / `807:419` |
| Region | `752:102` | `807:422` | `807:434` | `807:539` / `807:542` / `807:545` |

三者共享：

- `TopMarketBar`：`x=0,y=0,w=1600,h=56`，财势探查 active。
- `PageShell`：`x=0,y=56,w=1600,h=1656`。
- Breadcrumb：`x=18,y=14,w=1564,h=28`。
- Turnover Insight：`x=18,y=54,w=1564,h=500`。
- Sector Radar：`x=18,y=566,w=1564,h=1056`。

组件页 `797:2` 是组件事实源：

```text
PageBreadcrumb / Wealth Exploration  802:14
TurnoverMetricCard                   803:14 (base component)
Metric Card / Average 5             818:46
Metric Card / Average 20            818:49
TurnoverLegendItem                  803:23 (Current / Previous)
TurnoverTooltip                     804:13
DimensionTab                        804:20 (Active / Inactive)
TurnoverInsight                     805:639 (六态)
TurnoverHoverLayer                  808:68 (Idle / Active)
Average 5 Reference Line/Label      817:50 / 817:51
Average 20 Reference Line/Label     817:48 / 817:49
```

`TurnoverInsight` 六态主件：

| 状态 | Variant |
| --- | --- |
| Loaded | `805:130` |
| Delayed | `805:131` |
| Partial | `805:216` |
| Loading | `805:321` |
| Empty | `805:429` |
| Error | `805:533` |

状态与交互页 `797:3`：

- 六态实例：`809:55`、`809:163`、`809:271`、`809:374`、`809:391`、`809:404`。
- 1366 参考 frame：`809:417`，页面壳 `809:469`，成交额实例 `809:482`（`1330 x 425.19`）。
- Hover 交互样例：`809:583`；Idle variant `808:52` 通过 hover 进入 Active variant `808:67`。

1600 基准中的成交额内部几何：

```text
Panel width       1564
Plot left/right   x=58 / x=1534, width=1476
Cards             x=58/218/378/538/698, y=10, w=148, h=66, gap=12
Upper plot        y=96..270
Lower plot        y=318..392
Time labels       y=408
Shared crosshair  y=96..392
Tooltip           w=248, h=116
```

横轴共 17 个标签：

```text
09:30, 09:45, 10:00, 10:15, 10:30, 10:45, 11:00, 11:15, 11:30,
13:15, 13:30, 13:45, 14:00, 14:15, 14:30, 14:45, 15:00
```

设计中没有 `Alignment Note` 和对比日期说明；图例固定右对齐，包含当日累计、昨日累计、5 日均值、20 日均值四项。

均值补充设计事实：

- 5 日卡片示例 `23,771亿`，20 日卡片示例 `28,064亿`。
- 5 日参考线使用品牌金色，20 日参考线使用紫色，均为 `1px`、`4/4` 短密虚线；图例 swatch 使用相同颜色和虚线节奏。
- 两个值都存在时，高值标签位于参考线右端上方 `2px`，低值标签位于参考线右端下方 `2px`；相等时固定 5 日在上、20 日在下；单值时放在线上方。
- 5 日卡片金额使用品牌金色，20 日卡片金额使用紫色，卡片标题保持中性弱化色。
- 上图示例纵轴扩展为 `0/8000/16000/24000/32000`，证明均值必须参与上图 domain 计算。
- 三个 Loaded 页面实例 `807:164`、`807:309`、`807:434` 均已继承同一 Loaded 主组件的上述节点。

三个 Loaded frame 中的成交额洞察必须视为同一个业务组件的三个实例，不允许按 Industry/Concept/Region 复制实现。`DimensionTab` 只控制板块雷达；本轮不实现板块雷达业务，也不把 dimension 传入成交额 API。

### 2.8 正式数据只读审计

截至 2026-08-22：

- 五个频率各有 154 个 READY 日期，覆盖 2026-01-05 至 2026-08-21。
- 2026-08-21 的 `freq=1`：241 点，09:30 至 15:00，总额 `18,920.6656045亿`，展示 `18,921亿`。
- 2026-08-20 的 `freq=1`：241 点，09:30 至 15:00，总额 `20,939.0832447亿`，展示 `20,939亿`。
- 两日时间集合差异为 0。
- 精确总差 `-2,018.4176402亿`，展示 `-2,018亿`。
- 两个 `points_json` 约 5.6KB/行。
- 当前 lookup index 查询约 0.083ms。

结论：数据、索引和 payload 量级满足在线服务；无数据库迁移、数据补录或新快照任务。

## 3. 目标调用链

```text
/wealth/exploration?market=CN_A&tradeDate=...
    -> WealthRouter explicit route
    -> WealthExplorationPage
         -> fetchMarketPageContext(market, requested tradeDate) [once]
         -> resolved MarketPageContextViewModel
         -> fetchMarketMajorIndices(resolved market/tradeDate) [TopMarketBar]
         -> fetchTurnoverInsight(resolved market/tradeDate)
              -> GET /api/v1/wealth/market/turnover-insight
              -> require_quote_access
              -> MarketPageContextQuery.resolve_context
              -> TurnoverInsightQuery.load_candidates
              -> one bounded snapshot/calendar query, limit 4
              -> TurnoverDailyAverageQuery.load(end_trade_date=observed date)
              -> bounded latest-20 SSE calendar + EquityDailyBar aggregate
              -> TurnoverInsightCalculator
              -> TurnoverInsightStatusResolver
              -> independent DTO
         -> shape-only frontend adapter
         -> TurnoverInsightSection
         -> one Canvas for upper/lower plot
```

页面公共 Context 失败时不发起模块请求。模块失败只影响模块区域，不把已成功的 TopMarketBar 和 Breadcrumb 清空。

## 4. 文件级改动矩阵

### 4.1 后端新增

```text
src/biz/api/wealth/market/turnover_insight.py
src/biz/queries/wealth/market/turnover_insight/__init__.py
src/biz/queries/wealth/market/turnover_insight/turnover_insight_query.py
src/biz/queries/wealth/market/turnover_insight/turnover_insight_calculator.py
src/biz/queries/wealth/market/turnover_insight/turnover_insight_query_service.py
src/biz/schemas/wealth/market/turnover_insight.py
src/biz/services/wealth/market/turnover_insight/__init__.py
src/biz/services/wealth/market/turnover_insight/turnover_insight_status_resolver.py
src/biz/services/wealth/market/turnover_insight/turnover_insight_exception_builder.py
```

### 4.2 后端修改

```text
src/app/api/v1/router.py
wealth/docs/system/exception-code-registry.md
```

不修改：

```text
src/foundation/models/core_serving/wealth_market_turnover_snapshot.py
src/biz/services/wealth/market/turnover/turnover_snapshot_materialize_service.py
src/biz/api/wealth/market/turnover.py
src/biz/queries/wealth/market/turnover/**
src/biz/schemas/wealth/market/turnover.py
```

### 4.3 前端移动

```text
wealth/src/features/market-overview/context/api/marketPageContextApi.ts
  -> wealth/src/features/market-context/api/marketPageContextApi.ts

wealth/src/features/market-overview/context/api/marketPageContextAdapter.ts
  -> wealth/src/features/market-context/api/marketPageContextAdapter.ts

wealth/src/features/market-overview/indices/api/marketMajorIndicesApi.ts
  -> wealth/src/features/major-indices/api/marketMajorIndicesApi.ts

wealth/src/features/market-overview/indices/api/marketMajorIndicesAdapter.ts
  -> wealth/src/features/major-indices/api/marketMajorIndicesAdapter.ts

wealth/src/features/market-overview/layout/Breadcrumb.tsx
  -> wealth/src/shared/ui/page-breadcrumb/PageBreadcrumb.tsx
```

旧文件删除，不保留 re-export 或 wrapper。`marketMajorIndicesAdapter.ts` 移动前必须把页面私有 mock 映射拆出；共享 adapter 不得 import `features/market-overview/**`。

### 4.4 前端新增

```text
wealth/src/pages/wealth-exploration/WealthExplorationPage.tsx
wealth/src/pages/wealth-exploration/wealth-exploration-page.css

wealth/src/features/market-overview/indices/api/marketMajorIndicesMockAdapter.ts

wealth/src/features/wealth-exploration/turnover-insight/api/turnoverInsightApi.ts
wealth/src/features/wealth-exploration/turnover-insight/api/turnoverInsightAdapter.ts
wealth/src/features/wealth-exploration/turnover-insight/model/turnoverInsightTypes.ts
wealth/src/features/wealth-exploration/turnover-insight/model/useTurnoverInsightController.ts
wealth/src/features/wealth-exploration/turnover-insight/ui/TurnoverInsightSection.tsx
wealth/src/features/wealth-exploration/turnover-insight/ui/TurnoverInsightSummary.tsx
wealth/src/features/wealth-exploration/turnover-insight/ui/TurnoverMetricCard.tsx
wealth/src/features/wealth-exploration/turnover-insight/ui/TurnoverInsightLegend.tsx
wealth/src/features/wealth-exploration/turnover-insight/ui/TurnoverInsightChart.tsx
wealth/src/features/wealth-exploration/turnover-insight/ui/TurnoverInsightTooltip.tsx
wealth/src/features/wealth-exploration/turnover-insight/ui/turnoverInsightGeometry.ts
wealth/src/features/wealth-exploration/turnover-insight/ui/turnover-insight.css

wealth/src/shared/ui/page-breadcrumb/page-breadcrumb.css
```

### 4.5 前端修改

```text
wealth/src/app/routes/routerState.ts
wealth/src/app/routes/WealthRouter.tsx
wealth/src/shared/ui/top-market-bar/TopMarketBar.tsx
wealth/src/shared/ui/top-market-bar/topMarketBarTypes.ts
wealth/src/features/market-overview/indices/MajorIndexPanel.tsx
wealth/src/pages/market-overview/MarketOverviewPage.tsx
wealth/src/pages/market-overview/market-overview-page.css
wealth/src/pages/stock-detail/StockDetailPage.tsx
wealth/src/pages/index-detail/IndexDetailPage.tsx
```

### 4.6 测试新增/修改

后端：

```text
tests/test_wealth_market_turnover_insight_query.py
tests/test_wealth_market_turnover_insight_query_service.py
tests/web/test_wealth_market_turnover_insight_api.py
tests/test_wealth_turnover_insight_static_gates.py
```

前端：

```text
wealth/src/pages/wealth-exploration/WealthExplorationPage.test.tsx
wealth/src/features/wealth-exploration/turnover-insight/api/turnoverInsightAdapter.test.ts
wealth/src/features/wealth-exploration/turnover-insight/ui/TurnoverInsightSection.test.tsx
wealth/src/features/wealth-exploration/turnover-insight/ui/TurnoverInsightChart.test.tsx
wealth/src/features/wealth-exploration/turnover-insight/ui/turnoverInsightGeometry.test.ts
wealth/src/features/market-context/api/marketPageContextAdapter.test.ts
wealth/src/features/major-indices/api/marketMajorIndicesAdapter.test.ts
wealth/src/shared/ui/page-breadcrumb/PageBreadcrumb.test.tsx
wealth/src/shared/ui/top-market-bar/TopMarketBar.test.tsx
wealth/src/app/routes/routerState.test.ts
wealth/src/pages/market-overview/MarketOverviewPage.test.tsx
wealth/src/pages/stock-detail/StockDetailPage.test.tsx
wealth/src/pages/index-detail/IndexDetailPage.test.tsx
```

## 5. 后端低层设计

### 5.1 API 函数

文件：`src/biz/api/wealth/market/turnover_insight.py`

```python
router = APIRouter(prefix="/wealth/market", tags=["wealth-market"])

@router.get("/turnover-insight", response_model=TurnoverInsightResponseDto)
def get_turnover_insight(
    market: str = Query(default="CN_A"),
    trade_date: date | None = Query(default=None, alias="tradeDate"),
    debug: int = Query(default=0, ge=0, le=1),
    _user: AuthenticatedUser | None = Depends(require_quote_access),
    session: Session = Depends(get_db_session),
) -> TurnoverInsightResponseDto:
    ...
```

规则：

- `market.strip().upper()` 后只接受 `CN_A`。
- `tradeDate` 沿用 FastAPI `date` 解析。
- `debug` 与现有 Wealth API 一致，只接受 `0/1`。API 通过现有 `get_settings().app_env` 计算 `effective_debug = debug == 1 and app_env in {"local", "dev", "test"}`；只有 `effective_debug` 传给 service。其它环境强制关闭，不新增配置项。
- API 只实例化 `TurnoverInsightQueryService`，不得实例化旧 service。
- router 在 `src/app/api/v1/router.py` 中独立 include，不能挂到旧 turnover router 下。

### 5.2 内部查询数据结构

文件：`turnover_insight_query.py`

```python
@dataclass(frozen=True, slots=True)
class TurnoverInsightSnapshotRow:
    trade_date: date
    pretrade_date: date | None
    latest_trade_time: datetime
    total_amount_thousand_yuan: Decimal
    source_row_count: int
    security_count: int
    points: tuple[dict[str, object], ...]
    built_at: datetime

@dataclass(frozen=True, slots=True)
class TurnoverInsightCandidateSet:
    expected_trade_date: date
    expected_prev_trade_date: date | None
    rows: tuple[TurnoverInsightSnapshotRow, ...]
```

禁止把 SQLAlchemy model 直接传到 calculator 或 schema 层。

### 5.3 查询 SQL

`load_candidates(...)` 单次最多取 4 行：

```sql
SELECT
  s.trade_date,
  c.pretrade_date,
  s.latest_trade_time,
  s.total_amount,
  s.source_row_count,
  s.security_count,
  s.points_json,
  s.built_at
FROM core_serving.wealth_market_turnover_snapshot AS s
LEFT JOIN core_serving.trade_calendar AS c
  ON c.exchange = 'SSE'
 AND c.trade_date = s.trade_date
WHERE s.type = 'stock'
  AND s.market = 'CN_A'
  AND s.freq = 1
  AND s.build_status = 'READY'
  AND s.trade_date <= :expected_trade_date
ORDER BY s.trade_date DESC
LIMIT 4;
```

门禁：

- 必须使用 model/select 构建，不拼用户 SQL。
- `limit(4)` 是硬上限常量。
- 不 select 日线表，不 select 原始分钟表。
- 不使用 offset，不扫描全历史。

### 5.4 日期对选择

`TurnoverInsightQueryService._select_pair(...)`：

1. 优先寻找：
   - current date 等于 `context.trade_date`。
   - previous date 等于 `context.prev_trade_date`。
2. 两者均存在且通过点质量校验，状态候选为 `READY`。
3. expected current 缺失时，在最多 4 条候选中从新到旧寻找第一组：
   - `newer.pretrade_date == older.trade_date`。
   - 两条均通过点质量校验。
4. 找到时为 `DELAYED`；响应必须同时写出 expected/observed，禁止改写 expected。
5. expected current 存在但 expected previous 缺失或不合法时为 `PARTIAL`，不跨日替换“昨日”。
6. expected current 不存在且没有完整相邻回退对时为 `EMPTY`。
7. SQL、JSON 或不可恢复合同异常为 `ERROR`。

回退是有界展示降级，不是重新定义页面交易日。

### 5.5 一分钟点解析

文件：`turnover_insight_calculator.py`

```python
@dataclass(frozen=True, slots=True)
class ExactMinuteAmount:
    time: str
    amount_thousand_yuan: Decimal
```

解析规则：

- `points_json` 必须是 list；元素必须是 dict。
- `tradeTime` 规范化为 `HH:MM`。
- `amount` 使用 `Decimal(str(value))`，禁止先转 float。
- `amount >= 0`。
- 时间唯一并严格升序。
- 精确 241 点。
- 首点 `09:30`，末点 `15:00`。
- 上午 09:30..11:30、下午 13:01..15:00；不得出现 11:31..13:00。
- 两日时间集合必须完全一致。

任何点被拒绝时不静默跳过；记录有限样本后将日期判为 invalid。

### 5.6 累计、差值与取整

```python
_THOUSAND_YUAN_PER_YI = Decimal("100000")

def round_yi(value: Decimal) -> int:
    return int((value / _THOUSAND_YUAN_PER_YI).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
```

每分钟按以下顺序计算：

```text
current_exact_cumulative += current_minute_amount
previous_exact_cumulative += previous_minute_amount
exact_delta = current_exact_cumulative - previous_exact_cumulative

currentAmountYi = round_yi(current_exact_cumulative)
previousAmountYi = round_yi(previous_exact_cumulative)
deltaAmountYi = round_yi(exact_delta)
```

`direction` 必须按 `exact_delta` 判定：`up/down/flat`。禁止用 `deltaAmountYi` 反推方向。

摘要卡片使用最后一个精确累计值；另外校验：

```text
abs(sum(points.amount) - snapshot.total_amount) <= 0.10 thousand_yuan
```

超过容差判为点质量异常，不用 total_amount 覆盖曲线尾值。

### 5.7 横轴标签

固定业务标签集合：

```python
TURNOVER_INSIGHT_AXIS_LABELS = frozenset((
    "09:30", "09:45", "10:00", "10:15", "10:30", "10:45",
    "11:00", "11:15", "11:30",
    "13:15", "13:30", "13:45", "14:00", "14:15", "14:30",
    "14:45", "15:00",
))
```

每条 series point 返回 `showAxisLabel`。前端不得再按分钟数取模决定业务标签。

### 5.8 纵轴合同

后端返回可直接展示的整数亿轴合同：

```python
class TurnoverInsightAxisTickDto(BaseModel):
    valueYi: int
    displayText: str

class TurnoverInsightValueAxisDto(BaseModel):
    minYi: int
    maxYi: int
    zeroYi: int | None
    ticks: list[TurnoverInsightAxisTickDto]
```

累计图：

- `minYi=0`。
- 取两条累计曲线最大值 `domainMax`，增加 `10%` 展示余量，固定生成四个区间。
- `granularity = 10 ^ max(0, floor(log10(abs(domainMax))) - 1)`。
- `step = ceil((domainMax * 1.10 / 4) / granularity) * granularity`。
- `maxYi = step * 4`，ticks 固定为 `0/step/2*step/3*step/4*step`。
- 当前样本 `domainMax=20939` 时得到 `0/6000/12000/18000/24000`。
- 全零时固定为 `minYi=0, maxYi=4, ticks=0/1/2/3/4`。

差值图：

- 必须包含 0。
- 全负时 `maxYi=0`，全正时 `minYi=0`。
- 每个实际存在的正负方向各生成两个区间；每一侧使用该侧绝对极值，按累计图相同的十进制量级规则计算 `step`，但区间数为 2。
- 正负同时存在时允许上下两侧使用不同 step，分别向外取整。
- 当前全负样本绝对极值 `2018` 时得到 `0/-1200/-2400`。
- 全零时固定为 `minYi=-1, maxYi=1, zeroYi=0, ticks=-1/0/1`。

前端只把 API 的 `minYi/maxYi/ticks` 映射为像素和文本，不自行换单位或生成领域刻度。

### 5.9 DTO 冻结

文件：`src/biz/schemas/wealth/market/turnover_insight.py`

所有 model 使用 `ConfigDict(extra="forbid")`。

```python
class TurnoverInsightTradingDayDto(BaseModel):
    market: Literal["CN_A"]
    expectedTradeDate: date
    observedTradeDate: date | None
    previousObservedTradeDate: date | None
    isTradingDay: bool
    sessionStatus: SessionStatusValue
    timezone: Literal["Asia/Shanghai"]
    generatedAt: datetime

class TurnoverInsightAmountDto(BaseModel):
    amountYi: int | None
    displayText: str
    direction: Literal["up", "down", "flat", "neutral"]

class TurnoverInsightAverageAmountDto(TurnoverInsightAmountDto):
    referenceLabel: str

class TurnoverInsightSummaryDto(BaseModel):
    current: TurnoverInsightAmountDto
    previous: TurnoverInsightAmountDto
    delta: TurnoverInsightAmountDto
    avg5d: TurnoverInsightAverageAmountDto
    avg20d: TurnoverInsightAverageAmountDto

class TurnoverInsightSeriesPointDto(BaseModel):
    time: str
    showAxisLabel: bool
    currentAmountYi: int | None
    currentDisplayText: str
    previousAmountYi: int | None
    previousDisplayText: str
    deltaAmountYi: int | None
    deltaDisplayText: str
    deltaDirection: Literal["up", "down", "flat"]

class TurnoverInsightResponseDto(BaseModel):
    status: Literal["READY", "DELAYED", "PARTIAL", "EMPTY", "ERROR"]
    tradingDay: TurnoverInsightTradingDayDto
    asOf: datetime | None
    unit: Literal["yi"]
    unitLabel: Literal["亿"]
    summary: TurnoverInsightSummaryDto
    upperAxis: TurnoverInsightValueAxisDto | None
    deltaAxis: TurnoverInsightValueAxisDto | None
    series: list[TurnoverInsightSeriesPointDto]
    message: str | None
    exceptionCode: str | None
    debugInfo: TurnoverInsightDebugInfoDto | None
```

校验器：

- READY/DELAYED：`series` 必须恰好 241 条，日期对和 axis 均非空。
- PARTIAL：允许只有 current 字段，previous/delta 必须为 null，不得伪造 0。
- EMPTY/ERROR：`series=[]`，axis 可为 null。
- `displayText` 由后端生成；null 使用 `--`。
- `referenceLabel` 由后端生成完整文案；前端不得拼接 `5日均值/20日均值`。
- 不允许任何 forecast 字段。

### 5.10 状态 resolver

文件：`turnover_insight_status_resolver.py`

输入只接受查询/校验结果，不自行查询数据库。

| 条件 | status | chart |
| --- | --- | --- |
| expected 严格日期对完整 | READY | 完整 |
| expected 缺失，有界范围内找到严格相邻完整对 | DELAYED | 完整，显示 observed/asOf |
| expected current 完整，previous 缺失或错网格 | PARTIAL | 只显示 current；不画 delta |
| 没有合法 current | EMPTY | 空态 |
| SQL/解析/服务异常 | ERROR | 错误态 |

### 5.11 异常码

编码前在 `wealth/docs/system/exception-code-registry.md` 登记：

| code | severity | 条件 |
| --- | --- | --- |
| `TI_SOURCE_DELAYED` | warn | expected 未 ready，使用较早严格相邻日期对 |
| `TI_CURRENT_SNAPSHOT_MISSING` | warn | expected current 缺失 |
| `TI_PREVIOUS_SNAPSHOT_MISSING` | warn | expected previous 缺失 |
| `TI_TIME_GRID_MISMATCH` | error | 两日时间集合不同或不满足 241 点 |
| `TI_POINT_QUALITY_INVALID` | error | JSON、时间、金额、重复或尾值对账失败 |
| `TI_QUERY_FAILED` | error | SQL 或未分类服务异常 |

新 builder 只能生成 `TI_*`；旧 `TO_*` 保持不变。

## 6. 前端低层设计

### 6.1 共享 Market Context 迁移

新路径：

```text
wealth/src/features/market-context/api/marketPageContextApi.ts
wealth/src/features/market-context/api/marketPageContextAdapter.ts
```

ViewModel 完整保留：

```ts
export interface MarketPageContextViewModel {
  market: "CN_A";
  tradeDate: string;
  prevTradeDate: string | null;
  isTradingDay: boolean;
  sessionStatus: "PRE_OPEN" | "TRADING" | "BREAK" | "CLOSED";
  timezone: "Asia/Shanghai";
  generatedAt: string;
  updateTime: string;
  source: "explicit" | "default";
}
```

`MarketOverviewPage` 只更新 import 和完整模型消费，不改变已有加载顺序。`WealthExplorationPage` 使用同一 fetcher/adapter。

共享 URL 参数解析函数固定为：

```ts
readMarketContextRequest(search): {
  market: string;
  tradeDate?: string;
}
```

- 无 `market` 时默认 `CN_A`。
- `MarketPageContextRequest.market` 同步放宽为 string；非 `CN_A` 不在前端偷换，原样交给 Context API 返回受控错误。成功后的 ViewModel 仍严格为 `CN_A`。
- `tradeDate` 原样传给 Context API，由后端 date contract 校验。
- `debug` 不是公共时间参数，仍是开发诊断参数。

### 6.2 路由

`routerState.ts` 新增：

```ts
export const WEALTH_EXPLORATION_PATH = "/wealth/exploration";
export function buildWealthExplorationPath(search?: URLSearchParams): string;
export function isWealthExplorationPath(pathname: string): boolean;
```

`isWealthRoute` 必须把该路径视为 Wealth 内部路由，使浏览器 history 返回逻辑正确。

`WealthRouter` 在详情匹配之后、首页 fallback 之前增加：

```tsx
if (isWealthExplorationPath(location.pathname)) {
  return <WealthExplorationPage search={location.search} />;
}
```

### 6.3 TopMarketBar 契约

`TopMarketBar` 改为真实导航，不再让业务页面解析中文 message：

```ts
export type TopMarketNavKey =
  | "market"
  | "exploration"
  | "assistant"
  | "training"
  | "data"
  | "settings";

interface TopMarketBarProps {
  activeNav: TopMarketNavKey;
  tickers: TopMarketTicker[];
  onNavigate: (target: TopMarketNavKey) => void;
  onTickerSelect: (tsCode: string) => void;
}
```

组件内部只维护 label 与 `TopMarketNavKey` 的对应关系，不知道 URL。`routerState.ts` 新增纯函数：

```ts
export function resolveTopMarketNavPath(target: TopMarketNavKey): string | null {
  if (target === "market") return DEFAULT_WEALTH_PATH;
  if (target === "exploration") return WEALTH_EXPLORATION_PATH;
  return null;
}
```

页面收到 `onNavigate` 后使用该函数：有 path 则 `navigateWealth(path)`，无 path 才显示现有未开放 toast。brand 发出 `market`，ticker 只调用 `onTickerSelect`。组件不伪造路径，也不拼中文 message。

消费者：

- MarketOverviewPage：`activeNav="market"`。
- WealthExplorationPage：`activeNav="exploration"`。
- StockDetailPage / IndexDetailPage：`activeNav="market"`，保持详情属于乾坤行情。

### 6.4 TopMarketBar 数据

财势探查使用与首页相同的：

```text
GET /api/v1/wealth/market/major-indices
market=<context.market>
tradeDate=<context.tradeDate>
```

不新建“财势探查专用指数接口”。页面在 Context ready 后发起一次请求，5 秒超时，使用现有 major-indices adapter 映射为 `TopMarketTicker[]`。

现有 API 和 adapter 必须从 `features/market-overview/indices/api` 上移到：

```text
wealth/src/features/major-indices/api/marketMajorIndicesApi.ts
wealth/src/features/major-indices/api/marketMajorIndicesAdapter.ts
```

共享 adapter 固定提供：

```ts
buildMajorIndicesViewModelFromApi(payload): MarketMajorIndicesViewModel;
buildTopMarketTickersFromMajorIndices(model): readonly TopMarketTicker[];
```

`buildTopMarketTickersFromMajorIndices(...)` 只保留 `point/change/pct` 均为有限数字的行，不提供页面 fallback。行情首页若需要 mock/fallback，继续由页面私有的 `marketMajorIndicesMockAdapter.ts` 和现有 overview 数据负责；共享目录不得 import `features/market-overview/**`。

本轮不重构首页 `MajorIndexPanel` 的展示职责；共享的是正式 API、真实响应 adapter、TopMarketBar ticker mapper 和 TopMarketBar，不复制指数计算，也不允许财势探查跨 feature import `features/market-overview/**`。

### 6.5 PageBreadcrumb

新组件：

```ts
export interface PageBreadcrumbItem {
  label: string;
  path?: string;
}

interface PageBreadcrumbProps {
  items: readonly PageBreadcrumbItem[];
  sessionStatus: SessionStatus;
  onNavigate: (path: string) => void;
}
```

规则：

- 保留原 `.breadcrumb-row/.breadcrumb/.breadcrumb-meta/.status-pill` DOM/class。
- 保留秒级时钟、日期、星期和 session status 文案。
- 非末项且有 path 时渲染 button；末项渲染 `.current`。
- 行情首页传：`财势乾坤 / 乾坤行情 / 市场总览`。
- 财势探查传：`财势乾坤 / 财势探查`。
- 不把“成交额洞察”或“板块雷达”加进面包屑。

CSS 从 `market-overview-page.css` 搬到 `page-breadcrumb.css`，旧规则删除，避免两份样式漂移。

### 6.6 WealthExplorationPage 状态机

页面状态：

```ts
type PageContextState =
  | { kind: "loading" }
  | { kind: "ready"; value: MarketPageContextViewModel }
  | { kind: "error"; message: string };
```

顺序：

1. 解析 URL `market/tradeDate/debug`。
2. 请求 Market Context，超时 5 秒。
3. Context ready 后并行请求：
   - major-indices（TopMarketBar）。
   - turnover-insight（模块）。
4. 两个请求使用独立 AbortController，模块失败不清空 header。
5. Context 参数变化时 abort 旧请求并清空旧日期模块数据，防止跨日期闪现。
6. unmount 时取消全部请求。

页面 JSX 顺序：

```tsx
<div className="market-terminal wealth-exploration-page">
  <TopMarketBar activeNav="exploration" ... />
  <main className="page-shell wealth-exploration-shell">
    <PageBreadcrumb items={EXPLORATION_BREADCRUMBS} ... />
    <TurnoverInsightSection ... />
    <div data-module-slot="sector-radar" />
  </main>
</div>
```

`data-module-slot="sector-radar"` 是无业务内容、无高度、无文案的组合插槽，只冻结未来装配顺序；本轮不向它填 mock 数据或实现板块雷达。

Figma 的 Industry/Concept/Region 是板块雷达的三个页面状态，不是三份成交额页面。未来板块雷达接入时，其 dimension state 必须位于 `data-module-slot="sector-radar"` 内；`TurnoverInsightSection` 保持在该状态之外。切换 dimension 不得改变成交额请求键 `market/tradeDate/debug`，不得 remount chart，也不得触发新的 turnover 请求。

### 6.7 API 客户端

`turnoverInsightApi.ts`：

```ts
export interface TurnoverInsightRequest {
  market: "CN_A";
  tradeDate: string;
  debug?: 0 | 1;
}

export async function fetchTurnoverInsight(
  params: TurnoverInsightRequest,
  options: { signal?: AbortSignal } = {},
): Promise<TurnoverInsightResponse>;
```

- 使用 `wealthFetch`。
- query key 名固定 `market/tradeDate/debug`。
- 页面调用时 `tradeDate` 必须来自 resolved Context，不直接使用 URL 原值。
- 非 2xx 解析 `{code,message}`，抛 `TurnoverInsightApiError`。
- 不调用旧 `/wealth/market/turnover`。

### 6.8 Adapter

adapter 只做字段重命名和不可变数组映射：

```ts
export interface TurnoverInsightViewModel {
  status: DataStatus;
  tradingDay: ...;
  summary: ...;
  upperAxis: ...;
  deltaAxis: ...;
  points: readonly TurnoverInsightChartPoint[];
  message: string | null;
}
```

静态禁止：

```text
reduce(
/ 100000
Math.round(amount...
current - previous
new Date(...).previous...
```

允许：字段复制、null 归一化、readonly 包装。任何累计、差值、换算、取整都属于后端职责。

### 6.9 TurnoverInsightSection

组件 props：

```ts
interface TurnoverInsightSectionProps {
  viewState: "loading" | "ready" | "delayed" | "partial" | "empty" | "error";
  model: TurnoverInsightViewModel | null;
  errorMessage?: string;
  onRetry: () => void;
}
```

渲染：

- Header：标题、描述、右侧 as-of chip。
- Panel 顶部：五个 `148x66` 摘要卡片，间距 `12px`，以及右侧图例。
- READY/DELAYED：完整 chart。
- PARTIAL：只画有证据的 current；previous/delta 卡片为 `--`，下图显示受控说明。
- EMPTY：空态，无 canvas。
- ERROR：错误态和重试按钮，无 canvas。
- LOADING：保持 section 500px 的 skeleton，避免页面跳动。

Figma 到 React 的组件映射：

| Figma 主件 | React 落点 | 边界 |
| --- | --- | --- |
| `PageBreadcrumb / Wealth Exploration` | shared `PageBreadcrumb` | 复用首页 DOM/CSS，不创建页面私有副本 |
| `TurnoverMetricCard` | `TurnoverMetricCard.tsx` | feature 私有，只消费 `label/displayText/direction` |
| `TurnoverLegendItem` | `TurnoverInsightLegend.tsx` | feature 私有，只表达 current/previous 两个系列 |
| `TurnoverTooltip` | `TurnoverInsightTooltip.tsx` | feature 私有，只展示后端 displayText |
| `TurnoverInsight` | `TurnoverInsightSection.tsx` | 一个组件树承载六态，不复制六份页面 JSX |
| `TurnoverHoverLayer` | `TurnoverInsightChart.tsx` 内的 hover state | 共享一个 hoverIndex、crosshair 和 tooltip |
| `DimensionTab` | 板块雷达专项 | 不属于本轮代码范围，不进入成交额 feature |

`TurnoverInsightSummary.tsx` 负责五张卡片和图例布局；`TurnoverInsightChart.tsx` 只负责 Canvas 生命周期、均值参考线、曲线/柱、绘制和指针事件；`turnoverInsightGeometry.ts` 只提供纯几何计算。上述组件首次仅用于成交额洞察，全部保留在 feature 内，不提前上升到 `shared/ui`。

六态必须由同一个 `viewState` 穷尽分支：

| viewState | Figma variant | Canvas | Previous/Delta |
| --- | --- | --- | --- |
| `ready` | Loaded | 有 | 完整 |
| `delayed` | Delayed | 有 | 完整，显示实际 observed/as-of |
| `partial` | Partial | 仅 current 可绘制时创建 | `--` 与受控说明 |
| `loading` | Loading | 无 | skeleton |
| `empty` | Empty | 无 | 空态 |
| `error` | Error | 无 | 错误信息与重试 |

### 6.10 Canvas 图表

选择单个 Canvas，而不是上下两个 chart instance。原因：

- 241 点、2 条线和 241 根柱的规模很小。
- Figma 是同一面板、同一 x grid 和共享 crosshair。
- 单 canvas 天然避免上下图区 time scale、right axis 和 resize 偏移。

几何模型：

```ts
interface TurnoverInsightChartGeometry {
  width: number;
  height: number;
  plotLeft: number;
  plotRight: number;
  upperTop: number;
  upperBottom: number;
  lowerTop: number;
  lowerBottom: number;
  timeLabelY: number;
}
```

1600 设计基准映射：

```text
panel width      1564
plotLeft         58
plotRight        1534
upperTop/Bottom  96/270
lowerTop/Bottom  318/392
timeLabelY       408
```

响应式时：

- plotLeft 固定最小 58px，用于 y 轴文本。
- plotRight = width - 30px。
- 上下图共享 `[plotLeft, plotRight]`。
- 高度小于 420px 时按比例压缩垂直间距，但卡片、上图、下图和标签不得重叠。
- 使用 ResizeObserver；设备像素比用于 canvas backing store，不改变 CSS 尺寸。
- 1600 页面基准下 section 宽 `1564px`；1366 Figma 参考下内容宽 `1330px`。
- `1330px` 宽度必须通过 geometry 重算获得可见图形，不允许对整个 section 使用 CSS `transform: scale(...)`，也不允许用 viewport 单位缩放字体。
- 1366 是成交额组件级响应式验收参考，不修改 Design System 当前全局 `body` 最小宽度规则。

x 坐标：

```ts
x(i) = plotLeft + i * (plotWidth / (points.length - 1))
```

y 坐标：

```ts
yUpper(value) = upperBottom - (value - upperMin) / (upperMax - upperMin) * upperHeight
yDelta(value) = lowerBottom - (value - deltaMin) / (deltaMax - deltaMin) * lowerHeight
```

轴范围来自 API。若 `min==max`，视为后端合同错误，不在前端悄悄扩范围。

绘制顺序：

1. 背景。
2. 后端 axis ticks 对应的水平网格。
3. 17 个共享竖向网格，贯穿 upper/lower。
4. 上图区 5 日/20 日均值参考虚线。
5. delta 0 轴。
6. 差值柱。
7. previous 白线。
8. current 红线。
9. y/time 文本与均值参考标签。
10. hover 点、共享 crosshair、tooltip。

### 6.11 Hover 与 tooltip

鼠标位置映射：

```ts
index = clamp(round((mouseX - plotLeft) / plotWidth * (points.length - 1)))
```

同一个 `hoverIndex` 驱动：

- upper current point。
- upper previous point。
- lower delta bar highlight。
- 从 upperTop 到 lowerBottom 的 crosshair。
- 单个 tooltip。

初始和 `pointerleave` 状态对应 Figma `TurnoverHoverLayer/Idle`：不显示 crosshair、点、柱高亮和 tooltip。`pointermove` 命中有效 plot 范围时进入 Active；上下图区都只能产生同一个 Active 层，禁止分别创建两个 tooltip 或两条 crosshair。

tooltip 使用 API 的：

```text
time
currentDisplayText
previousDisplayText
deltaDisplayText
```

它不进行千分位、单位或差值计算。靠右时 tooltip 放在 crosshair 左侧，避免越界。

### 6.12 视觉 token

优先使用现有 Wealth token：

```text
current line/card delta up -> market-up/red
previous line              -> primary text/white
negative delta             -> market-down/green
grid                       -> border-subtle with reduced opacity
panel/card                  -> existing surface tokens
muted labels               -> text-muted
```

禁止新增渐变装饰、圆形背景或营销式大卡片。卡片 radius 不超过当前 Design System 的 8px。

## 7. 完整 API 示例

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
  "unitLabel": "亿",
  "summary": {
    "current": {"amountYi": 18921, "displayText": "18,921亿", "direction": "neutral"},
    "previous": {"amountYi": 20939, "displayText": "20,939亿", "direction": "neutral"},
    "delta": {"amountYi": -2018, "displayText": "-2,018亿", "direction": "down"},
    "avg5d": {
      "amountYi": 23771,
      "displayText": "23,771亿",
      "referenceLabel": "5日均值 23,771亿",
      "direction": "neutral"
    },
    "avg20d": {
      "amountYi": 28064,
      "displayText": "28,064亿",
      "referenceLabel": "20日均值 28,064亿",
      "direction": "neutral"
    }
  },
  "upperAxis": {
    "minYi": 0,
    "maxYi": 32000,
    "zeroYi": 0,
    "ticks": [
      {"valueYi": 0, "displayText": "0"},
      {"valueYi": 8000, "displayText": "8,000亿"},
      {"valueYi": 16000, "displayText": "16,000亿"},
      {"valueYi": 24000, "displayText": "24,000亿"},
      {"valueYi": 32000, "displayText": "32,000亿"}
    ]
  },
  "deltaAxis": {
    "minYi": -2400,
    "maxYi": 0,
    "zeroYi": 0,
    "ticks": [
      {"valueYi": 0, "displayText": "0"},
      {"valueYi": -1200, "displayText": "-1,200亿"},
      {"valueYi": -2400, "displayText": "-2,400亿"}
    ]
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
      "deltaDisplayText": "-17亿",
      "deltaDirection": "down"
    }
  ],
  "message": null,
  "exceptionCode": null,
  "debugInfo": null
}
```

示例只展示一条 series；READY 实际必须是 241 条。

## 8. 测试设计

### 8.1 后端 query

1. SQL 只查询 snapshot + trade calendar，limit=4。
2. exact expected pair 优先于 delayed pair。
3. 不把任意上一条 READY 当成 previous。
4. delayed 只允许 `newer.pretrade_date == older.trade_date`。
5. 不查询 `EquityDailyBar`、RawStkMins、Lake 或 Dagster。

### 8.2 calculator

1. 241 点正常累计。
2. 精确 Decimal 差值后再取整。
3. `0.5/-0.5` 使用 `ROUND_HALF_UP`。
4. 反例：分钟差值与累计差值不同，必须返回累计差值。
5. 重复时间、乱序、负金额、午间非法点、缺 09:30/15:00 均失败。
6. 两日 key 不同进入 mismatch。
7. point sum 与 total 超容差失败。
8. 横轴恰好 17 个，不含 13:00。
9. axis 十进制量级 step 覆盖全正、全负、跨零和全零，并精确断言 Figma 样本 `0/6000/12000/18000/24000` 与 `0/-1200/-2400`。

### 8.3 service/status

1. READY：expected pair 完整。
2. DELAYED：expected 缺失，4 行内存在严格相邻完整 pair。
3. PARTIAL：current 完整，previous 缺失/错网格。
4. EMPTY：无合法 current。
5. ERROR：query/calculator 异常。
6. 每种状态的 response validator 均通过。
7. debug=false 不返回内部 exceptions。

### 8.4 后端 API 集成

使用真实 SQLAlchemy session 和真实 model 表，不 mock service/query：

- 鉴权。
- `market=CN_A` 正常、`US` 400001。
- `tradeDate` 解析。
- response 字段逐项断言。
- 正常数据的卡片尾值等于曲线尾点。
- endpoint 不依赖旧 turnover 表现。

### 8.5 静态门禁

`tests/test_wealth_turnover_insight_static_gates.py` AST 检查：

- 新模块不得 import `.turnover.` 业务类。
- 不出现 `EquityDailyBar`、`RawStkMins`、DuckDB、Dagster、Lake 路径。
- query 必须出现 `freq == 1/build_status == READY/limit(4)`。
- query 通过 `TradeCalendar` model 访问 `core_serving.trade_calendar`，不得出现错误的 `core.trade_calendar` 字面量。
- 新 API 的 `debug` 必须沿用现有 Wealth `0/1` query contract；只有 `APP_ENV in {local, dev, test}` 且 `debug=1` 时允许返回 `debugInfo`，其它环境强制关闭。
- 前端 adapter 不出现累计、delta、亿元换算和取整逻辑。
- `features/wealth-exploration/**` 和 `features/major-indices/**` 不得 import `features/market-overview/**`。
- major-indices 旧 API/adapter 路径必须删除，不得保留 re-export、wrapper 或双份合同。
- response/schema 不出现 forecast/predict。

### 8.6 前端共享契约

TopMarketBar：

- activeNav=market/exploration 对应唯一 active button。
- market/exploration 调用真实 nav target。
- ticker 调用 code，不返回中文 message。
- 四个页面消费者编译和交互回归。

PageBreadcrumb：

- 首页路径保持三层。
- 财势探查路径只有两层。
- DOM class、日期、星期、时钟和 session status 保持一致。
- 点击根路径导航到首页。

Market Context：

- adapter 保留完整字段。
- 两页向 Context API 传相同 `market/tradeDate`。
- turnover 请求收到 resolved date，而不是 URL 原值。

Major Indices：

- 正式 API 和真实响应 adapter 位于 `features/major-indices`，首页与财势探查共同消费。
- 共享 adapter 不依赖 `features/market-overview`，mock mapper 只保留在首页私有目录。
- 两页使用同一个 `buildTopMarketTickersFromMajorIndices(...)`，不能分别实现 ticker 过滤和字段转换。

### 8.7 前端模块

- loading/ready/delayed/partial/empty/error。
- 六态由一个 `TurnoverInsightSection` 组件树表达，不存在按状态复制的页面实现。
- 五个卡片只显示 API `displayText`；前端不得计算 5 日/20 日均值或拼接均值标签。
- 当日红、昨日白、负差绿。
- 17 个横轴标签。
- 卡片一左边沿和 09:30 plotLeft 一致。
- 上下 plot x 坐标一致。
- hoverIndex 同时更新两线、柱、crosshair、tooltip。
- idle 不显示 hover overlay；pointerleave 同时清除 crosshair、点、柱高亮和 tooltip。
- resize 后上下图仍对齐。
- `1564px` 与 `1330px` 两种组件宽度均不裁切、不重叠，且不使用 CSS scale 或 viewport 字体缩放。
- tooltip 在左右边界不溢出。
- EMPTY/ERROR 不创建 Canvas。

### 8.8 页面集成

- `/wealth/exploration` 渲染新页面，不回落首页。
- TopBar active 为财势探查。
- Breadcrumb 为 `财势乾坤 / 财势探查`。
- Context ready 前不请求 turnover。
- turnover 与 major indices 均收到同一 resolved tradeDate。
- Turnover DOM 出现在 sector radar slot 之前。
- turnover request 类型、URL builder 和 controller key 均不存在 industry/concept/region/dimension 字段。
- 本轮不实现板块雷达，因此不伪造 dimension 切换运行测试；真实“切换维度不重新请求或 remount 成交额图表”测试作为板块雷达接入门禁。
- turnover 失败不移除 TopBar/Breadcrumb。

## 9. 性能门禁

### 9.1 后端

| 项目 | 门禁 |
| --- | ---: |
| snapshot SQL | 单次，limit 4 |
| daily average SQL | 2 次有界查询：最近 20 个 SSE 开市日 + 对应日聚合；禁止逐日查询 |
| 解析点数 | 最多 `4 x 241`，实际计算一组 `2 x 241` |
| 原始分钟/Lake/Dagster 查询 | 0 |
| API P95 | <= 120ms |
| 未压缩 payload | <= 64KB |
| DB 新索引/迁移 | 0 |

### 9.2 前端

| 项目 | 门禁 |
| --- | ---: |
| Context 请求 | 每次页面日期变化 1 次 |
| Turnover 请求 | 每次 resolved date 1 次 |
| Major indices 请求 | 每次 resolved date 1 次 |
| Canvas 元素 | 1 个 |
| DOM 柱/点节点 | 0，全部 canvas |
| timeout | 5 秒 |
| resize observer | 1 个，卸载释放 |
| request cancel | 日期变化和卸载必须 abort |

不新增 Redis。超过预算先查重复 effect、StrictMode 双请求保护、JSON 解析和重绘次数，不放宽 timeout。

## 10. 开发顺序

### M1 合同与治理

1. 登记 `TI_*` 异常码。
2. 建立 backend schema 和 TypeScript response contract。
3. 建立 static gates，先让禁止项测试失败。

### M2 后端

1. 实现 query dataclass 和 limit-4 SQL。
2. 实现点解析、累计、差值、取整和 axis calculator。
3. 实现 status resolver 和 exception builder。
4. 实现 query service/API/router。
5. 跑后端单元、集成、正式只读最小样本对账。

### M3 共享前端契约

1. 移动 Market Context 并更新首页 import。
2. 上移 major-indices 正式 API/真实 adapter，拆出首页私有 mock mapper，统一 TopMarketBar ticker 映射。
3. 移动 PageBreadcrumb 和 CSS，证明首页视觉/DOM不变。
4. 修改 TopMarketBar typed navigation，更新四类页面消费者。
5. 增加 exploration route。

### M4 页面与图表

1. 实现 API/adapter/controller。
2. 实现 WealthExplorationPage 和状态隔离。
3. 按 Figma 组件映射实现摘要卡片、图例、单 Canvas 双图区、crosshair/tooltip 和六态。
4. 对照三个 Loaded frame、状态页和 1366 参考验证布局一致。

### M5 收口

1. 后端/前端全量目标测试。
2. 用户部署后执行浏览器人工视觉验收。
3. 确认旧首页 turnover、首页、股票详情、指数详情无回退。
4. 更新技术方案与 LLD 状态。

### M6 5日/20日均值补充功能

1. 新增页面中立 `TurnoverDailyAverageQuery`，迁移首页现有 5/20 日均值读取语义，保持旧 API 输出不变。
2. 扩展成交额洞察 schema、calculator、service 和前端 contract。
3. 将 Loaded 摘要区扩展为五卡，将均值纳入 upper axis domain，并绘制两条上图区参考虚线和标签。
4. 增加同日期 API 对账、DELAYED 截止日、空均值、五卡响应式和 Canvas 绘制测试。
5. 开发完成后更新第 13 节补充功能对账；用户部署和视觉验收后再关闭 M6。

## 11. 验证命令

后端建议：

```bash
cd /Users/congming/github/goldenshare
uv run pytest \
  tests/test_wealth_market_turnover_insight_query.py \
  tests/test_wealth_market_turnover_insight_query_service.py \
  tests/web/test_wealth_market_turnover_insight_api.py \
  tests/web/test_wealth_market_turnover_api.py \
  tests/test_wealth_turnover_insight_static_gates.py
```

前端建议：

```bash
cd /Users/congming/github/goldenshare/wealth
npm test -- \
  src/pages/wealth-exploration/WealthExplorationPage.test.tsx \
  src/features/wealth-exploration/turnover-insight \
  src/features/market-context/api/marketPageContextAdapter.test.ts \
  src/features/major-indices/api/marketMajorIndicesAdapter.test.ts \
  src/shared/ui/page-breadcrumb/PageBreadcrumb.test.tsx \
  src/shared/ui/top-market-bar/TopMarketBar.test.tsx \
  src/app/routes/routerState.test.ts \
  src/pages/market-overview/MarketOverviewPage.test.tsx \
  src/pages/stock-detail/StockDetailPage.test.tsx \
  src/pages/index-detail/IndexDetailPage.test.tsx

npm run typecheck
npm run build
```

前端验证直接使用仓库现有 `npm` scripts，不为本需求修改 package scripts。

## 12. 编码门禁矩阵

以下矩阵是本模块正式编码门禁，替代独立 coding-gate 文件。每一项都必须在开工前具备明确落点，在交付时填写实际测试命令与结果；任一否决项不通过即停止开发或提测。

| ID | 门禁主题 | 适用性 | 落地位置 | 正向证明 | 反向/禁止项 |
| --- | --- | --- | --- | --- | --- |
| G01 | Figma 事实源 | 必须 | 本文 2.7、6.9；Figma `741:52`、`797:2`、`797:3` | 三个 Loaded 实例、六态、Hover 和 1366 参考可定位 | 禁止使用旧 `762:*`/`763:*` 节点或凭截图猜组件 |
| G02 | 独立真实 API | 必须 | `/api/v1/wealth/market/turnover-insight`、独立 query/service/schema | 真实路由集成测试返回页面所需完整字段 | 禁止 import/call 旧 turnover query/service/schema/status/exception |
| G03 | 有界事实源 | 必须 | 分钟曲线固定 `freq=1` snapshot；均值固定页面中立 daily-average query | snapshot 最多 4 行；均值仅最近 20 个 SSE 开市日；两个 API 同日期对账 | 禁止 RawStkMins、Lake、Dagster、全历史日线扫描、逐日 N+1 或前端均值计算 |
| G04 | 后端领域计算 | 必须 | calculator + response DTO | 241 点累计、累计差值、亿元换算、ROUND_HALF_UP 测试通过 | 禁止前端累计、相减、换算、取整或推导上一交易日 |
| G05 | 六态穷尽 | 必须 | `TurnoverInsightSection` + controller | loading/ready/delayed/partial/empty/error 六态组件测试 | 禁止用旧数据或 mock 伪装 ready；禁止复制六份页面 JSX |
| G06 | 图表与 Hover | 必须 | 单 `TurnoverInsightChart` Canvas + geometry + tooltip | 上下图区同 x、单 hoverIndex、单 crosshair、单 tooltip | 禁止双 chart 实例互相同步；禁止两个 tooltip/crosshair |
| G07 | 响应式 | 必须 | ResizeObserver + `turnoverInsightGeometry.ts` | `1564px`、`1330px` 宽度几何与截图验收均无裁切/重叠 | 禁止 CSS scale、viewport 字体缩放和硬编码第二套坐标 |
| G08 | 页面共享契约 | 必须 | shared Market Context、Major Indices API/adapter、TopMarketBar、PageBreadcrumb | 首页与财势探查的参数、ticker 映射、DOM/class、导航回归通过 | 禁止跨 feature 引用 `market-overview`、复制 TopBar/Breadcrumb 或自行解析另一套日期 |
| G09 | 板块维度隔离 | 本轮静态门禁 | Turnover 位于空 `sector-radar` slot 外；request/controller 无 dimension | DOM 顺序测试 + request 类型/URL/static gate 不含 industry/concept/region/dimension | 本轮禁止伪造板块雷达交互；真实切换回归在板块雷达接入阶段执行 |
| G10 | 性能预算 | 必须 | query、calculator、controller、Canvas | snapshot 1 次 + 均值 2 次有界查询、limit 4/20 日、P95 <=120ms、payload <=64KB、页面请求各 1 次 | 禁止 Redis、无界候选、逐日查询、重复 effect 或放宽 5 秒 timeout 掩盖问题 |
| G11 | 无预测与范围边界 | 必须 | schema、文案、静态门禁 | response/页面均不出现 forecast/predict | 禁止修改快照生产、表结构、Lake、Dagster 或实现板块雷达业务 |
| G12 | 异常与安全 | 必须 | exception registry、resolver、API auth | `TI_*` 已登记；非法 market/debug/日期有受控响应 | 禁止泄露 SQL、表名、路径、堆栈或复用 `TO_*` 异常码 |
| G13 | 核心真实测试 | 必须 | 本文 8.4、8.7、8.8、11 | 后端真实 API 集成测试 + 前端真实 API 展示测试同时通过 | 仅 mock、仅 schema、仅状态码测试不能作为交付证据 |
| G14 | 非目标回归 | 必须 | 首页、股票详情、指数详情和旧 turnover 测试 | 共享组件消费者和旧 API 全部回归通过 | 禁止顺手修改非目标模块样式、字段、排序或交互 |

### 12.1 核心测试字段

真实 API 与真实展示测试至少覆盖：

- `status`、`tradingDay.expectedTradeDate`、`observedTradeDate`、`previousObservedTradeDate`、`sessionStatus`、`asOf`。
- `summary.current/previous/delta` 的 `amountYi`、`displayText`、`direction`。
- `summary.avg5d/avg20d` 的 `amountYi`、`displayText`、`referenceLabel`、`direction`。
- `upperAxis`、`deltaAxis` 的边界和 ticks。
- `series.time/showAxisLabel/current/previous/delta` 及其 displayText/direction。
- `message`、`exceptionCode` 和生产环境不暴露 `debugInfo`。

### 12.2 通用清单映射

| 通用原则 | 落地位置 | 验证 |
| --- | --- | --- |
| 单一事实源 | G02-G04 | SQL/static/API 测试 |
| 契约先行 | 本文 5、7、G13 | schema + TypeScript contract |
| 配置一致性 | 本需求无新增配置 | 静态确认不新增 env/settings |
| 状态可观测 | 本文 6.9、G05、G12 | 六态 + 异常测试 |
| 计算下沉 | G03-G04 | adapter 静态门禁 |
| 性能预算前置 | 本文 9、G10 | 查询与 payload 实测 |
| 共享能力复用 | G08-G09 | 全消费者回归 + feature 依赖静态门禁 |
| 用户可见结果优先 | G01、G05-G07、G13 | 真实 API 展示与 Figma 验收 |

### 12.3 例外白名单

无。实现若需要偏离 Figma、API 合同、单 Canvas、六态、性能或共享组件边界，必须先修改本文并重新评审，不能在代码中建立隐式例外。

## 13. 计划对账清单

开发对账结果（2026-08-22）：

以下勾选项仅代表基础版本 M1-M5；M6 补充功能另见第 15 节，不得继承这些完成标记。

- [x] 旧首页半小时预计算事实已保留，旧 API/DTO 未修改。
- [x] 新 API、service、query、schema、status、exception 完全独立。
- [x] 新 query 只读 `freq=1` 预计算表和交易日历。
- [x] 页面公共时间使用与首页相同的 Context 和参数。
- [x] TopMarketBar 直接复用且财势探查高亮正确。
- [x] Breadcrumb 直接复用，路径为 `财势乾坤 / 财势探查`。
- [x] 卡片、曲线、差值、单位、取整全部由后端定义。
- [x] 前端没有累计、相减、亿元换算和取整。
- [x] 17 个横轴标签、单 canvas 双图区和共享 crosshair 已按 Figma 几何落地。
- [x] Figma 六态全部由同一个 `TurnoverInsightSection` 组件树表达。
- [x] `1564px` 与 `1330px` 使用同一响应式 geometry，且未使用 CSS scale/viewport 字体缩放。
- [x] 成交额 request/controller 不包含板块 dimension，且组件位于空 `sector-radar` slot 之前；真实维度切换回归已登记为板块雷达接入门禁。
- [x] 不包含预测能力。
- [x] 成交额洞察位于板块雷达之前。
- [x] 首页、股票详情、指数详情共享组件自动化回归通过。
- [x] 单次候选查询、`LIMIT 4`、响应小于 64KB、5 秒请求超时和单 Canvas 性能门禁已落实。
- [x] 用户完成本地部署和浏览器视觉验收，功能与视觉效果未发现问题。

### 13.1 实际验证结果

后端目标回归：`23 passed`。覆盖 calculator、真实 SQLAlchemy session/真实 API 路由、五种服务状态、debug 环境门禁、静态禁止项和旧 turnover API。

前端完整回归：`46` 个测试文件、`299 passed`。覆盖首页、股票详情、指数详情、财势探查、共享导航、共享 Breadcrumb、Context、Major Indices、六态、请求取消和 Canvas 几何。

构建门禁：

- `npm run typecheck`：通过。
- `npm run build`：通过；保留仓库既有的大 chunk warning，本需求未修改打包策略。
- `git diff --check`：通过。
- 开发阶段未启动后端、前端或浏览器，也未执行部署；部署和浏览器视觉验收随后由用户完成并确认通过。

### 13.2 G01-G14 收口

| Gate | 开发结果 |
| --- | --- |
| G01 | 使用已评审 Figma 节点和本文冻结几何实现；用户部署后的浏览器视觉验收已通过。 |
| G02 | 独立 endpoint/query/service/schema 已落地，旧 turnover 无复用。 |
| G03 | 一分钟 READY snapshot 候选查询上限 4；M6 另通过共享 query 执行一次最近 20 日历查询和一次日成交额聚合查询。 |
| G04 | Decimal 累计、累计差值、亿元换算和 ROUND_HALF_UP 均在后端。 |
| G05 | 一个 `TurnoverInsightSection` 穷尽六态。 |
| G06 | 一个 Canvas、一个 hoverIndex、一个 crosshair、一个 tooltip。 |
| G07 | ResizeObserver 和共享 geometry 覆盖 `1564px/1330px`；无 CSS scale。 |
| G08 | Context、Major Indices、TopMarketBar、PageBreadcrumb 已共享，旧路径已删除。 |
| G09 | 请求合同不含 dimension，空 `sector-radar` slot 位于成交额之后。 |
| G10 | 响应小于 64KB、页面模块各一次请求、5 秒超时已测试；M6 的两次有界均值查询通过查询计数和目标回归。 |
| G11 | 无预测字段、文案或实现；未触碰板块雷达业务。 |
| G12 | 六个 `TI_*` 已登记，参数错误和内部错误均受控。 |
| G13 | 后端真实路由集成与前端真实 API payload 渲染测试通过。 |
| G14 | 首页、股票详情、指数详情和旧 turnover 回归通过。 |

## 14. 边界与风险

### 14.1 不影响架构边界

- 新业务代码只落 `src/biz`、`src/app` 装配和 `wealth` 前端。
- 不新增 `foundation -> biz/app` 反向依赖。
- 不写 `src/platform`、`src/operations` legacy 目录。
- 不修改业务数据表、数据集定义、Dagster 或 Lake。

### 14.2 主要风险

| 风险 | 防线 |
| --- | --- |
| 新接口借用旧 service 导致固定五点回流 | import/static gate + 独立 API 集成测试 |
| 页面和模块日期不一致 | Context first，resolved params 传所有模块 |
| 回退日不相邻 | join calendar 并校验 `pretrade_date` |
| float 累计误差 | 全程 Decimal，最后一次 ROUND_HALF_UP |
| 前端再算一次 | adapter static gate + displayText 断言 |
| 上下图错位 | 单 Canvas、同一 geometry/x function |
| 共享 TopBar/Breadcrumb 回退 | 全消费者测试和首页 DOM 回归 |
| 板块雷达范围扩散 | 本轮只留页面装配顺序，不实现其数据和组件 |

## 15. 5日/20日均值补充功能代码级设计

本节是 M6 的实施依据。基础版本章节用于说明现有代码事实；若基础版本中的“三卡”“只读 snapshot”“DB 单查询”等历史描述与本节冲突，以本节补充口径为准，但不得改动基础版本已经验收的其它行为。

### 15.1 硬约束

1. 卡片顺序固定为：当日累计、昨日累计、累计增减、5 日均值、20 日均值。
2. 5/20 日均值必须与首页相同，不允许成交额洞察复制一套独立算法。
3. DELAYED 场景的均值窗口截止实际 `observedTradeDate`，不能截止 expected date。
4. 后端返回整数亿元、卡片 `displayText` 和完整 `referenceLabel`；前端只做字段映射与像素坐标映射。
5. 均值必须参与 upper axis domain；下方 delta axis、差值柱、tooltip、hover 和 crosshair 不变。
6. 均值为空时卡片显示 `--`、参考线不绘制；禁止填 0。
7. 不修改快照生产、数据表、Lake、Dagster、路由、页面时间合同或旧首页 API schema。
8. 两条均值标签必须按金额高低分配到参考线上下两侧，不允许都固定在线上方。
9. 参考线和均值图例 swatch 统一使用 `4/4` 短密虚线；图例固定包含四项。
10. 5 日/20 日均值卡金额必须分别使用参考线的品牌金/紫色，颜色只表达字段身份，不参与金额或状态计算。

### 15.2 页面中立日成交额均值 Query

新增：

```text
src/biz/queries/wealth/market/turnover_common/__init__.py
src/biz/queries/wealth/market/turnover_common/turnover_daily_average_query.py
```

稳定内存合同：

```python
@dataclass(frozen=True, slots=True)
class TurnoverDailyAverageSnapshot:
    end_trade_date: date
    avg5d_amount: Decimal | None
    avg20d_amount: Decimal | None
    available5d_count: int
    available20d_count: int

class TurnoverDailyAverageQuery:
    def load(
        self,
        session: Session,
        *,
        end_trade_date: date,
    ) -> TurnoverDailyAverageSnapshot: ...
```

`load(...)` 固定执行：

1. 从 `TradeCalendar` 选择 `exchange='SSE' AND is_open=true AND trade_date<=end_trade_date` 的最近 20 个开市日，结果恢复为升序。
2. 单次聚合读取这些日期的 `EquityDailyBar.amount`，按 `trade_date` 分组；禁止逐日 SQL。
3. 5 日窗口取交易日列表最后 5 日，20 日窗口取完整列表。
4. 只对实际存在的日总额求算术平均；没有有效值返回 `None`。这是首页当前 `_average_amount(...)` 的真实语义，本轮不得借机修改成“必须满 5/20 日”。
5. 聚合和均值使用 `Decimal(str(value))`，不在共享 query 中换算成亿元。

`TurnoverQuery.load_metrics(...)` 必须改为调用该 query 取得 `avg5d_amount/avg20d_amount`，其 `TurnoverMetricsDto` 字段、单位和页面结果保持不变。`TurnoverInsightQueryService` 也调用同一 query，但不得 import 旧 `TurnoverQuery` 或旧 service/schema/status/exception。

### 15.3 后端文件与符号改动

修改：

```text
src/biz/queries/wealth/market/turnover/turnover_query.py
src/biz/queries/wealth/market/turnover_insight/turnover_insight_calculator.py
src/biz/queries/wealth/market/turnover_insight/turnover_insight_query_service.py
src/biz/schemas/wealth/market/turnover_insight.py
wealth/docs/system/exception-code-registry.md
```

DTO 增量：

```python
class TurnoverInsightAverageAmountDto(TurnoverInsightAmountDto):
    referenceLabel: str

class TurnoverInsightSummaryDto(_StrictDto):
    current: TurnoverInsightAmountDto
    previous: TurnoverInsightAmountDto
    delta: TurnoverInsightAmountDto
    avg5d: TurnoverInsightAverageAmountDto
    avg20d: TurnoverInsightAverageAmountDto
```

`TurnoverInsightCalculator.calculate_pair(...)` 增加 `daily_averages` 输入，并统一完成：

- `Decimal thousand_yuan -> int yi` 的 `ROUND_HALF_UP`。
- `displayText`：`23,771亿`。
- `referenceLabel`：`5日均值 23,771亿` 或 `20日均值 28,064亿`。
- `direction='neutral'`。
- `build_cumulative_axis(...)` 的 values 必须包含 current、previous 以及所有非空均值。

`TurnoverInsightQueryService` 只有在选定有效 current 快照后才查询均值，截止日期固定为选中的 `current.trade_date`：

- READY：expected current date。
- DELAYED：fallback pair 中较新的实际 observed date。
- PARTIAL：有效 current 的实际 date。
- EMPTY/ERROR：不执行均值 query，返回两个空均值 DTO。

均值 query 抛异常时不得抹掉已经合法的分钟曲线。服务保留原核心状态，返回两个空均值 DTO，并登记 `TI_DAILY_AVERAGE_UNAVAILABLE` 到 debug exception；该异常码必须先写入异常码注册表再编码。自然缺少日总额但 query 正常返回 `None` 时不记系统异常。

### 15.4 前端合同与组件改动

修改：

```text
wealth/src/features/wealth-exploration/turnover-insight/api/turnoverInsightApi.ts
wealth/src/features/wealth-exploration/turnover-insight/api/turnoverInsightAdapter.ts
wealth/src/features/wealth-exploration/turnover-insight/model/turnoverInsightTypes.ts
wealth/src/features/wealth-exploration/turnover-insight/ui/TurnoverInsightSection.tsx
wealth/src/features/wealth-exploration/turnover-insight/ui/TurnoverInsightSummary.tsx
wealth/src/features/wealth-exploration/turnover-insight/ui/TurnoverInsightChart.tsx
wealth/src/features/wealth-exploration/turnover-insight/ui/turnover-insight.css
```

TypeScript 增量合同：

```ts
interface TurnoverInsightAverageViewModel extends TurnoverInsightAmountViewModel {
  referenceLabel: string;
}

summary: {
  current: TurnoverInsightAmountViewModel;
  previous: TurnoverInsightAmountViewModel;
  delta: TurnoverInsightAmountViewModel;
  avg5d: TurnoverInsightAverageViewModel;
  avg20d: TurnoverInsightAverageViewModel;
}
```

adapter 只复制 `avg5d/avg20d` 字段，不得调用 `reduce`、选择交易日、计算平均数、除以 `100000`、取整或拼接 `referenceLabel`。

`TurnoverInsightSummary` 继续复用 `TurnoverMetricCard`，按固定顺序渲染五张卡。`TurnoverMetricCard` 增加显式、可选的视觉身份参数，禁止根据中文 label 判断颜色：

```ts
type TurnoverMetricCardAccent = "default" | "avg5d" | "avg20d";

interface TurnoverMetricCardProps {
  label: string;
  value: TurnoverInsightAmountViewModel;
  accent?: TurnoverMetricCardAccent;
}
```

- 前三张卡保持 `accent="default"`，继续按既有 direction 显示金额色。
- 5 日卡传 `accent="avg5d"`，金额使用 `--cs-color-brand`。
- 20 日卡传 `accent="avg20d"`，金额使用 `--cs-color-purple`。
- `amountYi=null` 时仍显示 `--`，但均值卡身份色不变；不得用灰色假装是另一个状态。

CSS 固定：

```text
card width     148px
card height    66px
card gap       12px
card x         58/218/378/538/698 (1564px Figma 基准)
```

Loading skeleton 的卡片区域宽度同步为 `5 * 148 + 4 * 12 = 788px`。不得新增另一套均值卡组件。

`TurnoverInsightLegend` 固定按以下顺序渲染四项：

1. 当日累计：红色实线。
2. 昨日累计：白色实线。
3. 5 日均值：品牌金色 `4/4` 虚线。
4. 20 日均值：紫色 `4/4` 虚线。

图例仍整体靠右并与文字垂直居中；允许图例容器向左扩展以容纳四项，但不得与五张卡重叠。均值图例不显示金额，不读取或计算 summary 数值。

### 15.5 Canvas 参考线

`TurnoverInsightSection` 向 `TurnoverInsightChart` 传入 `avg5d/avg20d`。图表新增纯绘制 helper：

```ts
drawAverageReferenceLine(
  context,
  geometry,
  upperAxis,
  average,
  color,
): void
```

新增纯布局类型与 resolver：

```ts
type AverageLabelPlacement = "above" | "below";

interface AverageReferenceRenderItem {
  key: "avg5d" | "avg20d";
  average: TurnoverInsightAverageViewModel;
  color: string;
  labelPlacement: AverageLabelPlacement;
}

resolveAverageReferenceRenderItems(avg5d, avg20d, colors): readonly AverageReferenceRenderItem[]
```

resolver 固定规则：

1. 两个 `amountYi` 都存在且不相等：金额较高者 `above`，较低者 `below`。
2. 两个 `amountYi` 相等：`avg5d=above`、`avg20d=below`，保证顺序确定且标签不重叠。
3. 只有一个值存在：该项 `above`。
4. 空值项不进入 render items，不绘制参考线或标签。

不得按 `avg5d/avg20d` 身份固定上下位置，也不得在 Canvas 内通过像素碰撞后临时移动；金额顺序是唯一布局事实。

绘制合同：

- `amountYi=null` 时直接返回。
- `y = yForValue(amountYi, upperAxis, upperTop, upperBottom)`，不得建立第二套 y 公式。
- 线段范围只为 `plotLeft..plotRight`、`y..y`，不进入 lower plot。
- `lineWidth=1`、`setLineDash([4, 4])`，图例 swatch 必须使用相同节奏。
- 5 日线颜色使用现有品牌金 token 值，20 日线使用现有紫色 token 值；禁止新增散落页面色值。
- 标签 `textAlign='right'`，锚点为 `plotRight`，文本直接使用后端 `referenceLabel`。
- `above` 使用 `textBaseline='bottom'`、`y=lineY-2`；`below` 使用 `textBaseline='top'`、`y=lineY+2`。
- 参考线在普通网格之后、累计曲线之前绘制；标签在曲线之后绘制，确保可读。
- 两条均值线加入固定图例说明，但不把金额写入图例；它们不参与 tooltip，不产生 hover 点。

若均值高于当日/昨日累计终值，后端 upper axis 已包含该值并留出展示余量，前端不得裁切或自行扩轴。当前 Figma fixture：

```text
current  18,921
previous 20,939
avg5d    23,771
avg20d   28,064
ticks    0 / 8,000 / 16,000 / 24,000 / 32,000
```

### 15.6 状态合同

| 状态 | 均值卡 | 参考线 |
| --- | --- | --- |
| READY | 有值则展示，否则 `--` | 仅绘制非空值 |
| DELAYED | 以 actual observed date 为截止日 | 仅绘制非空值 |
| PARTIAL | 与 current 同截止日；previous/delta 仍为 `--` | 上图仍可绘制非空均值 |
| LOADING | 五卡 skeleton | 无 Canvas |
| EMPTY/ERROR | 保持现有空态/错误态 | 无 Canvas |

均值缺失不创建第七种状态，也不把 READY 降级为 PARTIAL；现有六态继续只表达分钟对比主体的可用性。

### 15.7 测试增量

后端必须新增或扩展：

```text
tests/test_wealth_market_turnover_daily_average_query.py
tests/test_wealth_market_turnover_insight_query_service.py
tests/web/test_wealth_market_turnover_insight_api.py
tests/web/test_wealth_market_turnover_api.py
tests/test_wealth_turnover_insight_static_gates.py
```

覆盖：

- 最近 5/20 个 SSE 开市日与“只对存在值求均值”的既有语义。
- 首页和成交额洞察在同一截止日期的均值金额完全一致。
- DELAYED 使用 observed date，反例证明不使用 expected date。
- 均值 query 失败时主体曲线保留、均值为空并产生受控异常。
- `summary.avg5d/avg20d/referenceLabel` 的 strict DTO 合同。
- upper axis 同时包含曲线与均值；Figma fixture 必须得到 `0/8000/16000/24000/32000`。
- 静态禁止成交额洞察 import 旧 `TurnoverQuery/MarketTurnoverQueryService`，同时允许且只允许 common query 读取 `EquityDailyBar`。

前端必须扩展：

```text
wealth/src/features/wealth-exploration/turnover-insight/api/turnoverInsightAdapter.test.ts
wealth/src/features/wealth-exploration/turnover-insight/ui/TurnoverInsightSection.test.tsx
wealth/src/features/wealth-exploration/turnover-insight/ui/TurnoverInsightChart.test.tsx
wealth/src/features/wealth-exploration/turnover-insight/ui/turnoverInsightGeometry.test.ts
wealth/src/pages/wealth-exploration/WealthExplorationPage.test.tsx
```

覆盖：

- 五卡顺序、空均值和 5 日/20 日金额身份色。
- 图例固定四项、两条均值 swatch 的颜色和 `4/4` 虚线。
- `avg5d > avg20d` 与 `avg20d > avg5d` 两个反向样本，证明高值在上、低值在下。
- 两值相等时 5 日在上、20 日在下；只有一个均值时单标签在线上方。
- 两条参考线的颜色、`4/4` 虚线、范围、标签基线和 `2px` 间距。
- 参考线只在上图绘制、tooltip 不增加均值、`1564px/1330px` 下五卡与四项图例无重叠。
- 前端无均值计算和标签拼接。

### 15.8 性能门禁

- 每次 insight 请求仍只有一次 snapshot candidate 查询，`LIMIT 4`。
- 均值只增加一次最近 20 日历查询和一次对应日期集合聚合查询；禁止 20 次逐日 SQL。
- 不读取 20 日之外的日线，不扫描全历史。
- 只增加两个 summary 对象，不给 241 个 series 点复制均值字段；未压缩 payload 继续小于 `64KB`。
- 后端 P95 目标继续 `<=120ms`，实现后必须用测试 session 和最小正式只读样本复核，不能通过放宽前端 `5s` timeout 处理性能回退。
- Canvas 只增加两条线和两个标签，不增加 DOM 图元、第二个 Canvas 或第二个 ResizeObserver。

### 15.9 M6 完成条件

以下勾选项是 2026-08-22 首轮实现的历史验收快照；2026-08-23 视觉反馈产生的新工作以第 15.10 节为准，不得由这些旧勾选项推导为当前已闭环。

- [x] Figma、技术方案、本文和代码字段完全一致。
- [x] 首页 API 契约和值无回退。
- [x] 成交额洞察返回五个 summary 项和完整 referenceLabel。
- [x] 两个 API 的 5/20 日均值同日期对账一致。
- [x] 两条均值线只绘制在上图，纵轴包含均值且响应式无重叠。
- [x] 六态、hover、tooltip、下图差值和板块维度隔离无回退。
- [x] 后端/前端目标测试、typecheck、build、`git diff --check` 全部通过。
- [x] 文档状态更新为“开发完成，待用户部署与视觉验收”。

M6 自动化验证结果（2026-08-22）：

- 后端目标回归：`29 passed`，包含首页与洞察同日期均值对账、DELAYED 截止实际观察日、均值查询失败降级、真实 API 路由和响应体积门禁。
- 前端完整回归：`48` 个测试文件、`304 passed`，包含五卡顺序、均值字段直传、上图区参考线、缺失均值省略、六态及共享页面回归。
- `npm run typecheck`：通过。
- `npm run build`：通过；仅保留仓库既有的大 chunk warning，本轮未修改打包策略。
- 未启动服务、未部署、未执行浏览器视觉验收，符合本轮开发边界。

### 15.10 2026-08-23 视觉反馈修订

Figma 组件源已完成以下修订：

- `Average 5/20 Reference Line` 的 `dashPattern` 从 `8/6` 改为 `4/4`。
- 当前样本中 20 日值较高，标签保留在线上方；5 日值较低，标签移到线下方。
- `Turnover Legend Group` 扩展为四项，新增 `Legend Item / Average 5`（`867:50`）和 `Legend Item / Average 20`（`867:53`）。
- `Metric Card / Average 5`、`Metric Card / Average 20` 的金额分别使用品牌金和紫色。
- 三个 Loaded 实例及状态/响应式实例均继承同一个组件源，无需逐实例维护。

代码修订必须依次完成：

1. 为 `TurnoverMetricCard` 增加显式 accent，并由 `TurnoverInsightSummary` 传入。
2. 把 `TurnoverInsightLegend` 扩展为四项，并在 CSS 中实现均值虚线 swatch。
3. 新增 `resolveAverageReferenceRenderItems(...)`，统一决定线、颜色和标签上下位置。
4. 将 Canvas 参考线改为 `4/4`，标签按 resolver 的 placement 绘制。
5. 扩展组件和 Canvas 测试，完成 typecheck/build/diff check。
6. 用户部署复验通过后，才能重新勾选 M6 的视觉验收并关闭本补充功能。

本节当前状态：Figma、文档和代码修订已完成。目标测试 19 项、全量前端测试 313 项、`npm run typecheck` 和 `npm run build` 均通过；待用户部署与视觉复验。

## 16. 结论

本需求不缺数据基础，也不需要新增预计算链路。开发核心是：在共享一分钟快照之上建立完全独立的成交额洞察业务合同，并把财势探查页面接入现有 TopMarketBar、Breadcrumb 和 Market Context 三个共享能力。

当前没有待拍板项。基础版本 M1 至 M5、自动化验证、用户部署和浏览器视觉验收均已完成；M6 均值补充功能及 2026-08-23 视觉修订已完成开发和自动化验证，待用户部署与视觉复验。前端不得引入均值计算，首页与洞察继续共同消费页面中立均值 query，旧 API 契约保持不变。
