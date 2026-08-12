# 股票详情页｜真实 API 接入标杆需求 v1

> 用途：冻结“财势乾坤 / 个股详情页”从 mock UI 过渡到真实日频数据的业务范围、数据口径与验收边界。
> 阶段：真实 API 接入编码前。
> 产物性质：业务与体验事实源，不是实现代码。

关联文档：

1. [股票详情页技术实施方案 v1](/Users/congming/github/goldenshare/wealth/docs/pages/stock-detail/stock-detail-implementation-design-v1.md)
2. [股票详情页 M2 编码前门禁 v1](/Users/congming/github/goldenshare/wealth/docs/pages/stock-detail/stock-detail-m2-coding-gate-v1.md)
3. [股票详情页真实 API 对接方案 v1](/Users/congming/github/goldenshare/wealth/docs/pages/stock-detail/stock-detail-real-api-stk-factor-pro-integration-plan-v1.html)
4. [stk_factor_pro 数据覆盖审计 v1](/Users/congming/github/goldenshare/wealth/docs/pages/stock-detail/stk-factor-pro-data-coverage-audit-v1.md)
5. [Showcase：stock-detail-v1.4.3.html](/Users/congming/github/goldenshare/wealth/docs/update/stock-detail-v1.4.3.html)
6. [股票与主要指数详情页九转接入总方案 v1](../../system/detail-page-nine-turn-integration-implementation-design-v1.md)

> 九转专项说明：本文描述的是股票详情真实日频 API 首期边界，其中“分钟线不覆盖”等条目是当时阶段事实。后续九转产品合同、正式 Figma、支持周期、独立 API、共享图层和实施顺序统一以九转总方案及其后续 LLD 为准；在新专项完成前，不将历史文档改写成已接入。

---

## 1. 目标与定位

1. 模块目标：让股票详情页首期接入真实日频数据，替换核心行情与指标 mock。
2. 用户价值：用户进入单只股票后，可以看到真实的日 K、日频技术因子和基础盘口摘要。
3. 数据定位：首期数据不是实时行情，只是基于当前数据基座的盘后 / 最新交易日日频数据。
4. API 定位：新接口属于财势乾坤行情系统，命名空间固定为 `/api/v1/wealth/market/stock-detail/*`。
5. 旧链路定位：本轮不复用 `/api/v1/quote/detail/*`，也不删除旧 quote 链路；后续单独做 legacy 下线计划。

---

## 2. 已拍板口径

1. `defaultAdjustment` 对外统一使用 `forward`，底层字段映射到 `qfq`。
2. 本轮股票详情新 API 不复用 `src/biz/api/quote.py` 和 `src/biz/queries/quote_query_service.py`；旧 quote 后续单独开下线计划。
3. 首期只展示源表已有 MA，不做后端临时计算，也不让前端计算。

---

## 3. 本期覆盖范围

### 3.1 后端覆盖

1. 新增股票详情页真实 API：
   - `GET /api/v1/wealth/market/stock-detail/page-init`
   - `GET /api/v1/wealth/market/stock-detail/kline`
2. 读取数据表：
   - `core_serving.equity_factor_pro`
   - `core_serving.security_serving`
3. 复用市场总览页面级日期锚点：
   - `MarketPageContextQuery`
   - `MarketPageContextDto`
4. 返回模块级数据状态：
   - 期望交易日
   - 实际观测交易日
   - READY / DELAYED / EMPTY / ERROR

### 3.2 前端覆盖

1. 股票详情页从真实 API 获取：
   - 股票身份
   - 价格摘要
   - 图表默认值
   - 日 K bars
   - MA / BOLL / MACD / KDJ
2. 未接真实数据的区域保留现有 mock 或 disabled/toast：
   - 分钟线 / 分时
   - 周 K / 月 K
   - 关联板块
   - 个股资金结构
   - 自选 / 提醒 / 交易计划

---

## 4. 本期不覆盖

1. 不接分钟线、分时、1/5/15/30/60/90/120 分钟。
2. 不接周 K、月 K。
3. 不接关联板块。
4. 不接个股资金结构。
5. 不接用户自选、提醒、交易计划持久化。
6. 不做 MA15、MA120 等源表没有的指标计算。
7. 不新增交易、诊股、买卖建议、仓位建议。
8. 不删除旧 `quote.py` / `quote_query_service.py`。

---

## 5. 数据源与用途

| 表 | schema | 本期用途 | 是否必需 | 说明 |
|---|---|---|---|---|
| `equity_factor_pro` | `core_serving` | 日 K、复权价格、量额、换手、量比、MA、BOLL、MACD、KDJ | 是 | 主数据源，对应 `stk_factor_pro`。 |
| `security_serving` | `core_serving` | 股票名称、代码、行业、交易所、上市状态 | 是 | 身份信息源。 |

不直接读取 raw 表。若后续需要分钟线或资金，需要另开模块方案。

---

## 6. 页面数据对象需求

### 6.1 `pageContext`

用途：统一页面级交易日锚点，避免每个页面自己计算日期。

必备字段：

| 字段 | 含义 |
|---|---|
| `market` | 当前固定 `CN_A`。 |
| `tradeDate` | 页面期望交易日。 |
| `prevTradeDate` | 上一交易日。 |
| `isTradingDay` | 是否交易日。 |
| `sessionStatus` | PRE_OPEN / TRADING / BREAK / CLOSED。 |
| `timezone` | `Asia/Shanghai`。 |
| `generatedAt` | 服务端生成时间。 |
| `source` | explicit / default。 |

### 6.2 `stock`

用途：页面标题、右侧股票头部、面包屑。

必备字段：

| 字段 | 来源 | 缺失策略 |
|---|---|---|
| `tsCode` | `security_serving.ts_code` | 必须有。 |
| `symbol` | `security_serving.symbol` | 可空。 |
| `name` | `security_serving.name` | 缺失时展示代码。 |
| `exchange` | `security_serving.exchange` | 可空。 |
| `industry` | `security_serving.industry` | 可空。 |
| `listStatus` | `security_serving.list_status` | 可空。 |

### 6.3 `quote`

用途：右侧盘口摘要和头部价格。

必备字段：

| 字段 | 来源 | 展示口径 |
|---|---|---|
| `observedTradeDate` | `equity_factor_pro.trade_date` | 实际数据日期。 |
| `open` | `open_qfq` | 前复权今开。 |
| `high` | `high_qfq` | 前复权最高。 |
| `low` | `low_qfq` | 前复权最低。 |
| `close` | `close_qfq` | 前复权盘后静态最新价。 |
| `preClose` | `pre_close` | 昨收。 |
| `change` | `change` | 涨跌额。 |
| `pctChg` | `pct_chg` | 涨跌幅。 |
| `turnoverRate` | `turnover_rate` | 换手率。 |
| `volumeRatio` | `volume_ratio` | 量比。 |
| `vol` | `vol` | 成交量，源单位手。 |
| `amount` | `amount` | 成交额，源单位千元。 |

### 6.4 `chartDefaults`

用途：告诉前端首期哪些图表能力可用。

| 字段 | 值 |
|---|---|
| `defaultPeriod` | `day` |
| `defaultAdjustment` | `forward` |
| `sourceAdjustment` | `qfq` |
| `availablePeriods` | `["day"]` |
| `availableAdjustments` | `["forward"]` |
| `availableMainOverlays` | `["MA", "BOLL"]` |
| `availableIndicatorTabs` | `["VOL", "amount", "MA", "MACD", "KDJ", "BOLL"]` |

### 6.5 `bars[]`

用途：K 线主图、成交量、成交额、技术指标图。

每根 bar 必须包含：

1. `tradeDate`
2. `price`
   - `open`
   - `high`
   - `low`
   - `close`
   - `preClose`
   - `change`
   - `pctChg`
3. `volume`
   - `vol`
   - `amount`
4. `factors`
   - `ma`
   - `boll`
   - `macd`
   - `kdj`

### 6.6 `dataStatus`

用途：说明数据是否满足当前页面期望日期。

字段：

| 字段 | 含义 |
|---|---|
| `expectedTradeDate` | 来自 `pageContext.tradeDate`。 |
| `observedTradeDate` | 实际查询到的数据日期。 |
| `status` | READY / DELAYED / EMPTY / ERROR。 |
| `message` | 人可读说明。 |

---

## 7. 用户可见语义

1. 页面展示的是静态日频数据，不是实时行情。
2. 如果 `observedTradeDate` 早于 `expectedTradeDate`，页面应能识别为数据延迟。
3. 首期图表周期只有日 K，其他周期按钮如果保留，只能 disabled 或 toast。
4. 首期复权只支持前复权，对外参数是 `forward`。
5. 首期均线只展示源表已有档位：`MA5/MA10/MA20/MA30/MA60/MA90/MA250`。

---

## 8. 验收标准

1. `page-init` 能返回真实股票身份、价格摘要和图表默认值。
2. `kline` 能返回指定股票的日 K 与技术因子序列。
3. 前端股票详情页不再用 mock 填充日 K、盘口摘要、MA/BOLL/MACD/KDJ。
4. 未接真实数据的区域仍保持现有 UI，不伪造真实来源。
5. 旧 quote API 不被本轮新页面调用。
6. `defaultAdjustment` 对外值是 `forward`，底层字段读取 `*_qfq`。
7. 源表没有的 MA 不返回、不计算、不在前端补。

---

## 9. 实现对账记录

本轮已按上述口径落地真实 API 接入，当前事实如下：

1. 新增接口固定落在 `/api/v1/wealth/market/stock-detail/*`，未复用旧 `/api/v1/quote/detail/*`。
2. `page-init` 只负责页面上下文、股票身份、最新价格摘要、图表能力与数据状态，不返回 K 线数组。
3. `kline` 只支持 `period=day` 与 `adjustment=forward`，底层读取 `core_serving.equity_factor_pro` 的 qfq 字段。
4. 前端股票详情页已切为 `page-init -> kline` 两段加载，loading/error 状态不再展示 mock K 线或 mock 盘口摘要。
5. 未接真实数据的右侧资金、板块、用户动作仍保留独立 mock / disabled / toast，不与真实日 K 数据混入同一事实对象。
6. 前端与后端均已清除股票详情真实数据链路中的 `MA15/MA120` 依赖，仅展示 `MA5/MA10/MA20/MA30/MA60/MA90/MA250`。
