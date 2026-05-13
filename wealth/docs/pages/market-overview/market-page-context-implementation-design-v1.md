# 市场总览｜页面时间上下文技术方案 v1

## 1. 背景

当前市场总览页面已经按模块逐步接入真实 API，但页面顶部仍使用整页 mock 提供的时间字段：

```ts
tradeDate: "2026-04-28"
updateTime: "2026-04-28 15:05:00"
```

这两个字段现在来自：

```text
wealth/src/features/market-overview/api/marketOverviewMockAdapter.ts
```

页面展示位置：

```text
wealth/src/features/market-overview/layout/PageHeader.tsx
```

现状问题：

1. 页面顶部显示的交易日是 mock，不是后端真实解析的业务日期。
2. 页面顶部显示的数据更新时间是 mock，不代表任何真实数据更新时间或页面生成时间。
3. 每个模块 API 虽然都支持 `tradeDate`，但当前页面调用真实模块时没有显式传入 `tradeDate`。
4. 后端每个模块各自复制一套交易日解析逻辑，默认值一般一致，但不是单一事实源。

本方案目标是把页面级时间锚点收敛为一个明确、轻量、可复用的页面上下文能力。

---

## 2. 目标

1. 页面顶部 `交易日` 不再来自整页 mock。
2. 页面顶部 `页面更新时间` 不再来自整页 mock。
3. 页面打开时先获取页面级时间上下文，再用该上下文驱动模块请求。
4. 所有真实模块 API 显式接收同一个 `tradeDate`。
5. 模块自己的 `DELAYED/PARTIAL/EMPTY/ERROR` 仍由模块自身返回，不被页面上下文吞掉。
6. 不恢复巨型 `/market/overview` 聚合接口，不破坏模块级渐进替换策略。

---

## 3. 不做什么

1. 不把所有模块数据重新合并为一个大接口。
2. 不在前端根据模块返回值自行推导页面交易日。
3. 不用单个模块的 `tradingDay.tradeDate` 反向覆盖页面顶部交易日。
4. 不把模块底层数据更新时间混成一个“全页面数据更新时间”。
5. 不改各模块业务查询逻辑。
6. 不改各模块现有 `tradingDay/pageStatus/debugInfo` 契约。
7. 不处理板块速览业务查询或 UI，本轮只让它和其他真实模块一样消费统一 `tradeDate`。

---

## 4. 术语定义

## 4.1 页面交易日 `tradeDate`

定义：

> 当前市场总览页面正在展示的业务交易日。

规则：

1. 如果 URL 或调用方显式传入 `tradeDate`，页面交易日等于该值。
2. 如果未传入，后端按交易日历和盘后切换规则计算默认交易日。
3. 页面交易日是所有模块请求的统一日期锚点。
4. 某个模块缺少该交易日数据时，不允许模块偷偷改变页面交易日，只能返回模块级 `DELAYED/PARTIAL/EMPTY`。

## 4.2 页面更新时间 `generatedAt`

定义：

> 后端生成本次页面时间上下文的时间。

说明：

1. 它不是所有底层数据表的更新时间。
2. 它不是某个模块的 `asOfTime`。
3. 它不是前端当前时间。
4. 它只回答：“这一屏页面上下文是什么时候由后端生成的？”

展示文案建议：

```text
页面更新时间：2026-05-13 18:30:12
```

不建议继续使用：

```text
数据更新时间
```

原因：容易误导用户以为所有底层数据都在这个时间完成更新。

## 4.3 模块观测时间

每个模块仍保留自己的：

```ts
tradingDay.tradeDate
pageStatus.asOfTime
debugInfo.modules[].expectedTradeDate
debugInfo.modules[].observedTradeDate
```

这些字段用于模块状态、debug、延迟判断，不用于覆盖页面级交易日。

---

## 5. 当前代码事实

## 5.1 前端事实

页面文件：

```text
wealth/src/pages/market-overview/MarketOverviewPage.tsx
```

现状：

1. 页面首次加载调用 `fetchMarketOverviewMock()`。
2. mock 返回 `overview.tradeDate/updateTime/statusText/dataDelayText`。
3. `PageHeader` 使用 `overview.tradeDate/updateTime`。
4. `TopMarketBar` 使用 `overview.statusText/dataDelayText`。
5. 各真实模块请求当前没有传 `tradeDate`。

真实模块调用示例：

```ts
fetchMarketSummary({ market: "CN_A", debug })
fetchMarketLimitUp({ market: "CN_A", debug })
fetchMarketStreakLadder({ market: "CN_A", debug })
```

## 5.2 前端 API client 事实

以下模块 API client 都已经支持可选 `tradeDate` 参数：

1. `summary`
2. `major-indices`
3. `breadth`
4. `style`
5. `turnover`
6. `money-flow`
7. `leaderboards`
8. `limit-up`
9. `streak-ladder`

位置：

```text
wealth/src/features/market-overview/**/api/*Api.ts
```

## 5.3 后端事实

每个模块后端都有独立的 `*_state_query.py`，并重复实现：

1. `expected_trade_date`
2. `prev_trade_date`
3. `is_trading_day`
4. `session_status`
5. `as_of_time`
6. `20:00` 盘后切换规则

当前已知文件：

```text
src/biz/queries/wealth/market/summary/summary_state_query.py
src/biz/queries/wealth/market/major_indices/major_indices_state_query.py
src/biz/queries/wealth/market/breadth/breadth_state_query.py
src/biz/queries/wealth/market/style/style_state_query.py
src/biz/queries/wealth/market/turnover/turnover_state_query.py
src/biz/queries/wealth/market/money_flow/money_flow_state_query.py
src/biz/queries/wealth/market/leaderboards/leaderboards_state_query.py
src/biz/queries/wealth/market/limit_up/limit_up_state_query.py
src/biz/queries/wealth/market/streak_ladder/streak_ladder_state_query.py
```

---

## 6. 目标接口

## 6.1 接口路径

新增轻量页面上下文接口：

```http
GET /api/v1/wealth/market/context
```

请求参数：

```ts
interface MarketPageContextRequest {
  market?: "CN_A";     // default: CN_A
  tradeDate?: string;  // YYYY-MM-DD，可选回看日期
}
```

参数规则：

1. `market` 首期仅支持 `CN_A`。
2. `tradeDate` 非法日期格式返回 `400001`。
3. 显式 `tradeDate` 不要求一定是开市日，但响应必须返回 `isTradingDay=false`。
4. 未传 `tradeDate` 时，由后端按交易日历和盘后切换规则解析。

## 6.2 响应结构

```ts
interface MarketPageContextResponse {
  pageContext: {
    market: "CN_A";
    tradeDate: string;
    prevTradeDate: string | null;
    isTradingDay: boolean;
    sessionStatus: "PRE_OPEN" | "TRADING" | "BREAK" | "CLOSED";
    timezone: "Asia/Shanghai";
    generatedAt: string;
    source: "explicit" | "default";
  };
}
```

字段说明：

| 字段 | 含义 | 来源 |
|---|---|---|
| `market` | 市场 | 请求参数归一化，首期固定 `CN_A` |
| `tradeDate` | 页面统一交易日锚点 | 显式入参或默认解析 |
| `prevTradeDate` | 上一交易日 | `core_serving.trade_calendar.pretrade_date` 或交易日历查询 |
| `isTradingDay` | 是否开市 | `core_serving.trade_calendar.is_open` |
| `sessionStatus` | 当前交易时段状态 | 服务端当前时间 + 交易时间段 |
| `timezone` | 时区 | 固定 `Asia/Shanghai` |
| `generatedAt` | 页面上下文生成时间 | 服务端当前时间 |
| `source` | 日期来源 | 显式入参为 `explicit`，否则 `default` |

---

## 7. 后端设计

## 7.1 代码落位

建议新增：

```text
src/biz/api/wealth/market/context.py
src/biz/queries/wealth/market/context/
  __init__.py
  market_page_context_query.py
src/biz/schemas/wealth/market/context.py
```

路由挂载：

```text
src/app/api/v1/router.py
```

或当前 wealth market router 聚合文件中同级挂载，保持现有模块 API 组织方式。

## 7.2 查询职责

`MarketPageContextQuery` 只负责：

1. 校验 `market`。
2. 解析 `tradeDate`。
3. 查询交易日历。
4. 派生 `sessionStatus`。
5. 返回 `generatedAt`。

不负责：

1. 查询任何模块业务表。
2. 聚合模块状态。
3. 判断 `READY/PARTIAL/DELAYED`。
4. 生成模块 debug 信息。

## 7.3 默认交易日规则

默认交易日规则沿用当前各模块实际实现：

1. 查询 `core_serving.trade_calendar` 中小于等于当天的最新开市日。
2. 如果当前时间小时数 `>= 20`，默认目标日可切到当天最新开市日。
3. 如果当前时间 `< 20`，默认仍取上一已完成交易日。
4. 如果无法从交易日历获得开市日，则返回服务端当天日期，并标记 `isTradingDay=false`。

说明：

1. 该规则当前已经散落在多个模块的 `*_state_query.py` 中。
2. 本接口先复用同一口径。
3. 后续可把这套解析逻辑抽为共享 service，再逐步替换各模块重复实现。

## 7.4 与现有模块的关系

本阶段不强制删除模块内重复 resolver。

短期：

1. 页面先请求 context。
2. 页面把 `pageContext.tradeDate` 显式传给所有真实模块 API。
3. 模块后端收到显式 `tradeDate` 后使用该日期作为 `expected_trade_date`。

中期：

1. 抽出共享 `MarketTradingDayResolver`。
2. 各模块 `*_state_query.py` 统一调用共享 resolver。
3. 删除重复的 `20:00` 规则与交易时段判断代码。

这样可以先解决页面语义不一致问题，再治理后端重复逻辑，避免一次性改太大。

---

## 8. 前端设计

## 8.1 新增 API client

新增：

```text
wealth/src/features/market-overview/context/api/marketPageContextApi.ts
wealth/src/features/market-overview/context/api/marketPageContextAdapter.ts
```

或如果暂不新增目录，也可以放在：

```text
wealth/src/features/market-overview/api/marketPageContextApi.ts
```

建议使用独立 `context/` 目录，因为这是页面级上下文，不属于某个业务模块。

## 8.2 页面加载顺序

目标顺序：

```text
1. MarketOverviewPage mount
2. fetchMarketPageContext()
3. setPageContext()
4. 用 pageContext.tradeDate 请求所有真实模块
5. 顶部 PageHeader 展示 pageContext.tradeDate / pageContext.generatedAt
```

请求示例：

```ts
fetchMarketSummary({ market: "CN_A", tradeDate: pageContext.tradeDate, debug })
fetchMarketMajorIndices({ market: "CN_A", tradeDate: pageContext.tradeDate, debug })
fetchMarketLimitUp({ market: "CN_A", tradeDate: pageContext.tradeDate, debug })
fetchMarketStreakLadder({ market: "CN_A", tradeDate: pageContext.tradeDate, debug })
```

## 8.3 页面 header 字段调整

当前：

```ts
<PageHeader tradeDate={overview.tradeDate} updateTime={overview.updateTime} />
```

目标：

```ts
<PageHeader tradeDate={pageContext.tradeDate} updateTime={pageContext.generatedAt} />
```

文案建议：

```text
页面更新时间：{generatedAt}
```

即把 `数据更新时间` 改为 `页面更新时间`。

## 8.4 mock 的保留边界

`fetchMarketOverviewMock()` 可以暂时继续存在，用于：

1. 页面骨架与历史 mock 数据保留。
2. 本地 mock 展示。

但不能再作为：

1. 页面顶部交易日来源。
2. 页面顶部更新时间来源。
3. 真实模块请求日期来源。

---

## 9. 状态与异常

## 9.1 Context 加载失败

如果 `/context` 失败：

1. 页面进入页面级 error。
2. 不继续请求真实模块。
3. 展示明确错误：

```text
页面时间上下文加载失败
```

原因：

1. 没有统一交易日锚点时继续请求模块，会让页面时间语义再次分裂。
2. 不能回退 mock 日期，否则又回到当前问题。

## 9.2 模块延迟

模块延迟仍由模块自己表达：

```ts
debugInfo.modules[].expectedTradeDate
debugInfo.modules[].observedTradeDate
```

页面级 context 不处理模块延迟。

---

## 10. 测试计划

## 10.1 后端测试

新增：

```text
tests/web/test_wealth_market_context_api.py
```

覆盖：

1. 默认路径返回 `pageContext.tradeDate/generatedAt/sessionStatus`。
2. 显式 `tradeDate` 返回 `source=explicit`。
3. 非 `CN_A` 返回 `400001`。
4. 非法日期格式返回 422 或现有 WebAppError 口径。
5. 非交易日返回 `isTradingDay=false` 且 `prevTradeDate` 可用。

## 10.2 前端测试

新增或更新：

```text
wealth/src/test/market-overview-page-context.smoke.test.tsx
```

覆盖：

1. 页面先请求 `/api/v1/wealth/market/context`。
2. Header 展示 context 的 `tradeDate/generatedAt`。
3. 至少一个真实模块请求携带 `tradeDate=context.tradeDate`。
4. context 失败时页面展示 error，不继续请求模块。

## 10.3 回归

至少执行：

```bash
pytest -q tests/web/test_wealth_market_context_api.py
pytest -q tests/architecture/test_subsystem_dependency_matrix.py
cd wealth && npm run typecheck
cd wealth && npm run test -- market-overview-page-context.smoke.test.tsx
cd wealth && npm run build
```

---

## 11. 分阶段落地

## M1：新增后端 context API

目标：

1. 新增 `/api/v1/wealth/market/context`。
2. 返回 `pageContext`。
3. 补后端测试。

不做：

1. 不改模块接口。
2. 不改前端页面。

## M2：前端接入 context

目标：

1. 新增前端 context client。
2. Header 改用 context。
3. 所有真实模块请求显式传 `tradeDate=context.tradeDate`。
4. context 失败时页面停止模块请求并展示 error。

不做：

1. 不改模块 UI。
2. 不改模块业务字段。
3. 不改板块速览业务查询；板块速览只跟随统一 `tradeDate` 请求。

## M3：后端重复 resolver 收敛

目标：

1. 抽共享 `MarketTradingDayResolver`。
2. 各模块 state query 逐步调用共享 resolver。
3. 删除重复的交易时段与 20:00 切换逻辑。

说明：

1. M3 是治理项，不阻塞 M1/M2。
2. M3 必须单独小步做，避免同时影响所有模块。

---

## 12. 风险与控制

| 风险 | 影响 | 控制 |
|---|---|---|
| context 默认交易日与模块默认交易日不一致 | 模块返回 delayed 或空 | M2 显式传 `tradeDate`，让模块以页面锚点为准 |
| context 失败后页面无数据 | 首屏不可用 | 明确 error，不回退 mock，避免错误语义 |
| 后端 resolver 重复继续存在 | 维护成本高 | M3 专项治理，不混入 M1/M2 |
| generatedAt 被误解为数据更新时间 | 产品语义误导 | 文案改为“页面更新时间” |
| 已接真实 API 的板块速览仍未使用统一交易日 | 板块模块与页面 header 交易日可能不一致 | M2 与其他真实模块一起显式传入 `tradeDate` |

---

## 13. 待拍板项

1. 页面顶部文案是否确认改为：

```text
页面更新时间
```

2. Context 失败时是否确认“不回退 mock 日期”，而是页面级 error。
3. 后端 `generatedAt` 是否保留 ISO 字符串，前端负责展示格式化；还是后端直接返回展示字符串。

推荐：

1. 使用“页面更新时间”。
2. context 失败不回退 mock。
3. 后端返回 ISO 字符串，前端格式化为 `YYYY-MM-DD HH:mm:ss`。

---

## 14. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-13 | 首版：定义市场总览页面级时间上下文、接口、前后端接入与分阶段落地方案 | Codex |
