# 股票详情页｜真实 API 接入技术实施方案 v1

> 用途：把股票详情页真实 API 接入需求转成可实施的前后端工程方案。
> 阶段：编码前。  
> 产物性质：实现设计基线。

关联文档：

1. [股票详情页标杆需求 v1](/Users/congming/github/goldenshare/wealth/docs/pages/stock-detail/stock-detail-benchmark-requirement-v1.md)
2. [股票详情页 M2 编码前门禁 v1](/Users/congming/github/goldenshare/wealth/docs/pages/stock-detail/stock-detail-m2-coding-gate-v1.md)
3. [股票详情页真实 API 对接方案 v1](/Users/congming/github/goldenshare/wealth/docs/pages/stock-detail/stock-detail-real-api-stk-factor-pro-integration-plan-v1.html)
4. [stk_factor_pro 数据覆盖审计 v1](/Users/congming/github/goldenshare/wealth/docs/pages/stock-detail/stk-factor-pro-data-coverage-audit-v1.md)

---

## 1. 本轮实现目标

1. 新增财富系统股票详情 API：
   - `/api/v1/wealth/market/stock-detail/page-init`
   - `/api/v1/wealth/market/stock-detail/kline`
2. 前端股票详情页接入真实 API。
3. 保留未接真实数据区域的现有 mock / disabled / toast。
4. 不复用旧 `/api/v1/quote/detail/*`。
5. 不删除旧 quote 代码。

---

## 2. 代码落点

### 2.1 后端目录

```text
src/biz/
  api/
    wealth/
      market/
        stock_detail.py
  queries/
    wealth/
      market/
        stock_detail/
          __init__.py
          stock_detail_query.py
          stock_detail_query_service.py
  schemas/
    wealth/
      market/
        stock_detail.py
  services/
    wealth/
      market/
        stock_detail/
          __init__.py
          stock_detail_field_mapper.py
```

约束：

1. 不放到 `src/biz/api/quote.py`。
2. 不在 `src/biz/queries/quote_query_service.py` 上继续堆逻辑。
3. 不扁平堆到 `src/biz/queries/wealth/market` 根下。
4. 不改 `platform` / `operations`。

### 2.2 前端目录

```text
wealth/src/
  features/
    stock-detail/
      api/
        stockDetailApiClient.ts
        stockDetailApiTypes.ts
        stockDetailViewModelAdapter.ts
      model/
        stockDetailTypes.ts
        stockDetailConstants.ts
      chart/
      sidebar/
      layout/
  pages/
    stock-detail/
      StockDetailPage.tsx
      stock-detail-page.css
      StockDetailPage.test.tsx
```

约束：

1. 页面文件只做编排。
2. API response 到 UI view model 必须经过 adapter。
3. 组件内禁止散落真实字段映射。
4. 未接真实的右侧板块/资金/用户动作继续走独立 mock，不与真实 K 线数据混在一个对象里。

---

## 3. 后端 API 设计

### 3.1 `GET /api/v1/wealth/market/stock-detail/page-init`

参数：

| 参数 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `tsCode` | 是 | string | 股票代码，例如 `603806.SH`。 |
| `tradeDate` | 否 | date | 页面期望交易日；不传时复用 `MarketPageContextQuery` 默认规则。 |
| `debug` | 否 | boolean | 返回调试信息，默认 false。 |

查询：

1. `MarketPageContextQuery.resolve_context(...)`
2. `security_serving` 按 `ts_code` 查 1 行。
3. `equity_factor_pro` 按 `ts_code` + `trade_date <= pageContext.tradeDate` 查最近 1 行。

返回：

1. `pageContext`
2. `stock`
3. `quote`
4. `chartDefaults`
5. `capabilities`
6. `dataStatus`
7. `debugInfo?`

性能要求：

1. 不加载 K 线数组。
2. 不 `select *`。
3. 查询必须命中 `ts_code, trade_date` 索引。

### 3.2 `GET /api/v1/wealth/market/stock-detail/kline`

参数：

| 参数 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `tsCode` | 是 | string | 股票代码。 |
| `period` | 否 | string | 首期只允许 `day`。 |
| `adjustment` | 否 | string | 首期只允许 `forward`。 |
| `startDate` | 否 | date | 起始日期。 |
| `endDate` | 否 | date | 截止日期。 |
| `limit` | 否 | int | 默认 300，最大 2000。 |
| `debug` | 否 | boolean | 返回调试信息。 |

查询：

1. 校验 `period == "day"`。
2. 校验 `adjustment == "forward"`。
3. 读取 `equity_factor_pro` 中 qfq 价格字段和 qfq 技术因子。
4. 如果传日期区间，则按区间升序返回。
5. 如果不传日期区间，则取最近 `limit` 根后按日期升序返回。

返回：

1. `pageContext`
2. `stockRef`
3. `period`
4. `adjustment`
5. `sourceAdjustment`
6. `bars[]`
7. `meta`
8. `dataStatus`

性能要求：

1. 默认最多 300 根。
2. 最大不超过 2000 根。
3. 只查询页面首期所需字段。
4. 不查询分钟线、不查询板块、不查询资金。

---

## 4. DTO 设计

### 4.1 `StockDetailPageInitResponseDto`

包含：

1. `pageContext: MarketPageContextDto`
2. `stock: StockIdentityDto`
3. `quote: StockQuoteSnapshotDto | null`
4. `chartDefaults: StockChartDefaultsDto`
5. `capabilities: StockDetailCapabilitiesDto`
6. `dataStatus: DataStatusDto`
7. `debugInfo?: StockDetailDebugInfoDto`

### 4.2 `StockDetailKlineResponseDto`

包含：

1. `pageContext: MarketPageContextDto`
2. `stockRef: StockRefDto`
3. `period: "day"`
4. `adjustment: "forward"`
5. `sourceAdjustment: "qfq"`
6. `bars: StockKlineBarDto[]`
7. `meta: StockKlineMetaDto`
8. `dataStatus: DataStatusDto`
9. `debugInfo?: StockDetailDebugInfoDto`

### 4.3 `StockChartDefaultsDto`

固定值：

```json
{
  "defaultPeriod": "day",
  "defaultAdjustment": "forward",
  "sourceAdjustment": "qfq",
  "availablePeriods": ["day"],
  "availableAdjustments": ["forward"],
  "availableMainOverlays": ["MA", "BOLL"],
  "availableIndicatorTabs": ["VOL", "amount", "MA", "MACD", "KDJ", "BOLL"]
}
```

说明：

1. 对外 API 统一 `forward`。
2. 底层字段映射到 `*_qfq`。
3. 不返回 `qfq` 作为前端枚举值。

### 4.4 `StockTechnicalFactorsDto`

字段：

| 子对象 | 字段 | 来源 |
|---|---|---|
| `ma` | `ma5/ma10/ma20/ma30/ma60/ma90/ma250` | `ma_qfq_*` |
| `boll` | `upper/middle/lower` | `boll_upper_qfq/boll_mid_qfq/boll_lower_qfq` |
| `macd` | `dif/dea/macd` | `macd_dif_qfq/macd_dea_qfq/macd_qfq` |
| `kdj` | `k/d/j` | `kdj_k_qfq/kdj_d_qfq/kdj_qfq` |

禁止：

1. 不返回 `MA15`。
2. 不返回 `MA120`。
3. 不做临时计算。
4. 不让前端计算。

---

## 5. 字段映射规则

### 5.1 价格字段

| DTO 字段 | 来源字段 |
|---|---|
| `price.open` | `open_qfq` |
| `price.high` | `high_qfq` |
| `price.low` | `low_qfq` |
| `price.close` | `close_qfq` |
| `price.preClose` | `pre_close` |
| `price.change` | `change` |
| `price.pctChg` | `pct_chg` |

说明：首期图表价格用前复权 qfq；涨跌额与涨跌幅承接源表字段，不在前端重新计算。

### 5.2 量额字段

| DTO 字段 | 来源字段 | 源单位 |
|---|---|---|
| `volume.vol` | `vol` | 手 |
| `volume.amount` | `amount` | 千元 |

展示格式由前端 formatter 处理，API 不返回中文格式化字符串。

### 5.3 盘口摘要字段

| DTO 字段 | 来源字段 |
|---|---|
| `quote.open` | `open_qfq` |
| `quote.high` | `high_qfq` |
| `quote.low` | `low_qfq` |
| `quote.close` | `close_qfq` |
| `quote.preClose` | `pre_close` |
| `quote.turnoverRate` | `turnover_rate` |
| `quote.volumeRatio` | `volume_ratio` |
| `quote.vol` | `vol` |
| `quote.amount` | `amount` |

说明：盘口摘要展示日频静态事实，不是实时盘口。

---

## 6. 前端接入设计

### 6.1 API client

新增：

```text
wealth/src/features/stock-detail/api/stockDetailApiClient.ts
wealth/src/features/stock-detail/api/stockDetailApiTypes.ts
```

职责：

1. 请求 page-init。
2. 请求 kline。
3. 处理超时与 HTTP error。
4. 不做字段业务解释。

### 6.2 ViewModel adapter

新增：

```text
wealth/src/features/stock-detail/api/stockDetailViewModelAdapter.ts
```

职责：

1. 把 API DTO 转为页面现有 `StockDetailViewModel`。
2. 把源表已有 MA 档位转为图表显示项。
3. 禁止补造 MA15/MA120。
4. 未接真实的板块、资金、用户动作继续引用独立 mock fixture。

### 6.3 页面状态

1. loading：page-init 或 kline 未返回。
2. error：API 返回错误或请求超时。
3. ready：page-init 与 kline 均可用。
4. delayed：`dataStatus.status == "DELAYED"` 时在 debug/状态区展示，不阻断页面。

---

## 7. 测试设计

### 7.1 后端测试

1. `page-init`：
   - 返回 `pageContext`。
   - 返回 `stock`。
   - 返回 `quote`。
   - 返回 `chartDefaults.defaultAdjustment == "forward"`。
   - 返回 `chartDefaults.sourceAdjustment == "qfq"`。
2. `kline`：
   - `period=day` 成功。
   - 非 day 周期失败。
   - `adjustment=forward` 成功。
   - 非 forward 失败。
   - bars 中不含 MA15/MA120。
   - bars 中含 `ma5/ma10/ma20/ma30/ma60/ma90/ma250`。
3. 旧 quote：
   - 本轮不新增依赖旧 quote 的测试。

### 7.2 前端测试

1. 股票详情页能调用真实 API client。
2. loading 不展示 mock 行情。
3. error 显示错误态。
4. ready 显示真实日 K 与盘口摘要。
5. 未接真实模块仍保持 mock 或 disabled/toast。
6. MA 选项只来自 API 返回能力，不出现 MA15/MA120。

### 7.3 命令

```bash
cd wealth
npm run typecheck
npm run test
npm run build
```

后端：

```bash
pytest -q tests/web/test_wealth_stock_detail_api.py
```

---

## 8. 实施里程碑

### M1：后端 DTO 与路由骨架

目标：

1. 新增 schema。
2. 新增 API router。
3. 挂载到 wealth market 路由。

验收：

1. 路由存在。
2. 空实现不可上线，必须尽快进入 M2。

### M2：page-init 查询实现

目标：

1. 查询 `security_serving`。
2. 查询最新可用 `equity_factor_pro`。
3. 返回 `pageContext`、`stock`、`quote`、`chartDefaults`。

验收：

1. 真实样本能返回。
2. 日期状态正确。

### M3：kline 查询实现

目标：

1. 查询日 K bars。
2. 映射 qfq 价格。
3. 映射 MA/BOLL/MACD/KDJ。

验收：

1. bars 顺序正确。
2. limit 生效。
3. 不返回源表没有的指标。

### M4：前端接入

目标：

1. 新增 API client。
2. 新增 adapter。
3. 股票详情页使用真实 page-init + kline。
4. 未接模块继续 mock。

验收：

1. 页面打开能看到真实日频数据。
2. loading/error/ready 可测。

### M5：quote legacy 下线计划另开

目标：

1. 不在本轮执行。
2. 单独审计旧引用后再做。

---

## 9. 风险与约束

1. `quote.py` / `quote_query_service.py` 当前仍被使用，不能本轮删除。
2. `stk_factor_pro` 是日频数据，不可表达实时行情。
3. `stk_factor_pro` 不覆盖分钟、周月、资金、板块、用户动作。
4. MA 档位必须尊重源表，不补造。
5. `defaultAdjustment` 必须对外 `forward`，底层 `qfq`。

---

## 10. 实现对账记录

### 10.1 后端实际落点

本轮实际落地文件为：

```text
src/biz/api/wealth/market/stock_detail.py
src/biz/schemas/wealth/market/stock_detail.py
src/biz/queries/wealth/market/stock_detail/
  __init__.py
  stock_detail_query.py
  stock_detail_query_service.py
src/biz/services/wealth/market/stock_detail/
  __init__.py
  stock_detail_field_mapper.py
```

说明：

1. `stock_detail_query.py` 负责最小 SQL 查询，不 `select *`。
2. `stock_detail_query_service.py` 负责参数校验、上下文解析和响应组装。
3. `stock_detail_field_mapper.py` 负责 qfq 字段到 DTO 的映射、数值规整与数据状态构造。
4. 本轮没有修改旧 `src/biz/api/quote.py` 与 `src/biz/queries/quote_query_service.py`。

### 10.2 前端实际落点

本轮实际落地文件为：

```text
wealth/src/features/stock-detail/api/
  stockDetailApiClient.ts
  stockDetailApiTypes.ts
  stockDetailViewModelAdapter.ts
wealth/src/features/stock-detail/model/stockDetailTypes.ts
wealth/src/features/stock-detail/api/stockDetailMockAdapter.ts
wealth/src/features/stock-detail/chart/StockChartWorkspace.tsx
wealth/src/features/stock-detail/layout/StockChartToolbar.tsx
wealth/src/pages/stock-detail/
  StockDetailPage.tsx
  StockDetailPage.test.tsx
  stock-detail-page.css
```

说明：

1. `StockDetailPage` 先请求 `page-init`，再使用 `pageContext.tradeDate` 作为 `kline.endDate` 请求 K 线。
2. API DTO 必须经 `stockDetailViewModelAdapter` 转成页面 ViewModel。
3. loading/error 阶段不展示 mock K 线和 mock 盘口摘要。
4. 未接真实能力的区域仍由独立 mock 或 disabled/toast 承接。

### 10.3 字段口径对账

1. 对外复权口径仍为 `forward`，响应中保留 `sourceAdjustment="qfq"` 说明底层字段。
2. KDJ 的 `j` 明确来自 `kdj_qfq`。
3. MA 只保留 `ma5/ma10/ma20/ma30/ma60/ma90/ma250`，不返回、不展示 `ma15/ma120`。
4. `kline` 返回按日期升序排列的 bars，默认最近 300 根，最大 2000 根。
