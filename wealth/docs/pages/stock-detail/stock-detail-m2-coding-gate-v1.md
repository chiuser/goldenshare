# 股票详情页｜真实 API 接入 M2 编码前门禁 v1

> 2026-11-04数量合同修订：股票日线 `kline` 默认500根、合法范围1～500；超限保持原HTTP 400、`code=400001`，不截断或拆分。页面现有显式300请求保持合法，本轮不推进页面或后续产品开发。此修改仅校准下文日线数量合同，不改变分钟线、新闻、九转、趋势等独立API。

> 用途：在编码前冻结股票详情页真实 API 接入的执行门禁。
> 阶段：真实 API 接入开工前。
> 产物性质：执行清单，不通过不允许编码。

关联文档：

1. [股票详情页标杆需求 v1](/Users/congming/github/goldenshare/wealth/docs/pages/stock-detail/stock-detail-benchmark-requirement-v1.md)
2. [股票详情页技术实施方案 v1](/Users/congming/github/goldenshare/wealth/docs/pages/stock-detail/stock-detail-implementation-design-v1.md)
3. [股票详情页真实 API 对接方案 v1](/Users/congming/github/goldenshare/wealth/docs/pages/stock-detail/stock-detail-real-api-stk-factor-pro-integration-plan-v1.html)
4. [stk_factor_pro 数据覆盖审计 v1](/Users/congming/github/goldenshare/wealth/docs/pages/stock-detail/stk-factor-pro-data-coverage-audit-v1.md)

---

## 1. 开工前硬门禁

1. [x] 已确认本轮新 API 不复用旧 `/api/v1/quote/detail/*`。
2. [x] 已确认旧 `quote.py` / `quote_query_service.py` 当前仍被使用，本轮不删除。
3. [x] 已确认 `defaultAdjustment` 对外为 `forward`，底层映射 `qfq`。
4. [x] 已确认首期只展示源表已有 MA，不计算 MA15/MA120。
5. [x] 已确认首期只接 `equity_factor_pro + security_serving`。
6. [x] 已确认股票详情页需要复用 `pageContext.tradeDate`。
7. [x] 已确认首期不接分钟线、资金、板块、用户动作。

---

## 2. API 门禁

### 2.1 路由门禁

必须新增：

```text
GET /api/v1/wealth/market/stock-detail/page-init
GET /api/v1/wealth/market/stock-detail/kline
```

禁止：

1. 禁止把新接口放到 `/api/v1/quote/detail/*`。
2. 禁止继续扩写 `src/biz/api/quote.py`。
3. 禁止继续扩写 `src/biz/queries/quote_query_service.py`。
4. 禁止把 schema/query/service 扁平堆在 `src/biz` 根层。

### 2.2 参数门禁

`page-init`：

| 参数 | 门禁 |
|---|---|
| `tsCode` | 必填。 |
| `tradeDate` | 可选；缺省时由 context query 决定。 |
| `debug` | 可选；默认 false。 |

`kline`：

| 参数 | 门禁 |
|---|---|
| `tsCode` | 必填。 |
| `period` | 首期只允许 `day`。 |
| `adjustment` | 首期只允许 `forward`。 |
| `limit` | 默认 500，合法范围 1～500；超限报原参数错误。 |
| `startDate/endDate` | 可选；同时传入时必须校验起止顺序。 |

---

## 3. 数据源门禁

允许读取：

1. `core_serving.equity_factor_pro`
2. `core_serving.security_serving`
3. `trade_calendar` 仅通过 `MarketPageContextQuery` 间接使用。

禁止读取：

1. `raw_tushare.*`
2. `stk_mins`
3. 板块成员表
4. moneyflow 表
5. 用户自选 / 提醒 / 交易计划表

---

## 4. 字段映射门禁

### 4.1 复权门禁

1. API 对外值：`forward`。
2. 底层字段后缀：`qfq`。
3. 响应中允许返回 `sourceAdjustment="qfq"` 作为 debug/映射说明。
4. 不允许前端用 `qfq` 作为 adjustment 枚举值。

### 4.2 MA 门禁

必须返回源表已有：

```text
MA5 / MA10 / MA20 / MA30 / MA60 / MA90 / MA250
```

禁止返回：

```text
MA15 / MA120
```

禁止：

1. 后端临时计算。
2. 前端临时计算。
3. 用别的 MA 冒充 MA15/MA120。

### 4.3 KDJ 门禁

映射必须写死：

| DTO | 源字段 |
|---|---|
| `k` | `kdj_k_qfq` |
| `d` | `kdj_d_qfq` |
| `j` | `kdj_qfq` |

---

## 5. 响应对象门禁

`page-init` 必须包含：

1. `pageContext`
2. `stock`
3. `quote`
4. `chartDefaults`
5. `capabilities`
6. `dataStatus`

`kline` 必须包含：

1. `pageContext`
2. `stockRef`
3. `period`
4. `adjustment`
5. `sourceAdjustment`
6. `bars[]`
7. `meta`
8. `dataStatus`

---

## 6. 前端接入门禁

1. 前端必须通过 `stockDetailApiClient` 请求真实 API。
2. API DTO 必须经过 `stockDetailViewModelAdapter` 转为页面 view model。
3. 组件禁止直接读取 API DTO。
4. loading 状态不得展示 mock 行情。
5. error 状态不得吞掉异常。
6. 未接真实数据区域可以继续 mock，但必须与真实日 K 数据分离。
7. `chartDefaults.available*` 必须驱动周期、复权、指标可用状态。

---

## 7. 测试门禁

### 7.1 后端测试

必须新增或更新：

```text
tests/web/test_wealth_stock_detail_api.py
```

覆盖：

1. `page-init` 返回 `pageContext`。
2. `page-init` 返回 `chartDefaults.defaultAdjustment == "forward"`。
3. `page-init` 返回 `chartDefaults.sourceAdjustment == "qfq"`。
4. `kline period=day adjustment=forward` 成功。
5. `kline period!=day` 失败。
6. `kline adjustment!=forward` 失败。
7. `bars[].factors.ma` 不含 `ma15` / `ma120`。
8. `bars[].factors.kdj.j` 来自 `kdj_qfq` 口径。

### 7.2 前端测试

必须覆盖：

1. 股票详情页真实 API happy path。
2. loading。
3. error。
4. chart defaults 驱动可用周期与指标。
5. 不出现 MA15 / MA120。

### 7.3 回归命令

后端：

```bash
pytest -q tests/web/test_wealth_stock_detail_api.py
```

前端：

```bash
cd wealth
npm run typecheck
npm run test
npm run build
```

---

## 8. 性能门禁

1. `page-init` 只查 1 行 identity + 1 行 factor。
2. `kline` 默认 500 根，最大 500 根；显式1～500均合法，短历史返回实际数量。
3. `kline` 只查询图表所需字段，不 `select *`。
4. 必须利用 `equity_factor_pro(ts_code, trade_date)` 查询条件。
5. 响应不得把整张宽表字段直接透出。

---

## 9. 文档一致性门禁

编码完成后必须回写：

1. `stock-detail-benchmark-requirement-v1.md`
2. `stock-detail-implementation-design-v1.md`
3. `stock-detail-m2-coding-gate-v1.md`
4. `stock-detail-real-api-stk-factor-pro-integration-plan-v1.html`

若实现与三件套不一致，必须先改文档并说明原因，不允许让代码和文档漂移。

---

## 10. 开工签字清单

1. [x] `defaultAdjustment` 口径已拍板。
2. [x] 旧 quote 链路处理方式已拍板。
3. [x] MA 档位口径已拍板。

---

## 11. 本轮落地对账

### 11.1 计划硬口径落点

| 硬口径 | 落点 | 状态 |
|---|---|---|
| 新 API 不走旧 quote | `src/biz/api/wealth/market/stock_detail.py`，`src/app/api/v1/router.py` | 已落地 |
| `page-init` 不返回 K 线数组 | `stock_detail_query_service.py` | 已落地 |
| `kline` 只支持 `day/forward` | `stock_detail_query_service.py` 与后端测试 | 已落地 |
| `forward -> qfq` | `stock_detail_field_mapper.py` 与 DTO `sourceAdjustment` | 已落地 |
| 不返回 MA15/MA120 | `stockDetailTypes.ts`、`StockChartWorkspace.tsx`、后端/前端测试 | 已落地 |
| 前端 DTO 必须经 adapter | `stockDetailViewModelAdapter.ts`、`StockDetailPage.tsx` | 已落地 |
| loading/error 不展示 mock 行情 | `StockDetailPage.tsx`、`StockDetailPage.test.tsx` | 已落地 |

### 11.2 已执行门禁

必须保留以下回归作为本轮完成条件：

```bash
pytest -q tests/web/test_wealth_stock_detail_api.py
cd wealth && npm run typecheck
cd wealth && npm run test
cd wealth && npm run build
```

### 11.3 后续不在本轮处理

1. 旧 `/api/v1/quote/detail/*` 下线。
2. 分时、分钟线、周 K、月 K 真实接入。
3. 关联板块、个股资金、用户自选/提醒/交易计划真实接入。
4. [x] 后端 DTO 完成。
5. [x] 后端 API 完成。
6. [x] 前端 API client 完成。
7. [x] 前端 adapter 完成。
8. [x] 前后端测试完成。
9. [x] 文档与实现复核完成。

---

## 11. 本轮实现对账记录

实现日期：2026-05-31

已落地：

1. 新增 `/api/v1/wealth/market/stock-detail/page-init`。
2. 新增 `/api/v1/wealth/market/stock-detail/kline`。
3. 前端股票详情页主行情从 mock 切到真实 `page-init + kline`。
4. loading / error 状态不再展示 mock 主行情。
5. `MA15 / MA120` 已从股票详情主行情类型、图表展示和测试中移除。

验证命令：

```bash
pytest -q tests/web/test_wealth_stock_detail_api.py
cd wealth && npm run typecheck
cd wealth && npm run test -- StockDetailPage
```

<a id="top-market-indices-bugfix"></a>

## 12. Bugfix（2026-11-05）股票详情页顶部指数行情

依据为[技术实施方案第 11 节](./stock-detail-implementation-design-v1.md#top-market-indices-bugfix)。已核对 `WatchlistPage → useWatchlistTickers → fetchMarketMajorIndices` 和 `StockDetailPage → buildStockDetailViewModel → stockDetailMockAdapter`，以及主要指数路由、响应结构和共享 `TopMarketBar` 的字段消费。

| 检查项 | 实现和验收条件 |
| --- | --- |
| 请求与展示 | 将自选页的 `useWatchlistTickers` 移至主要指数模块并命名为 `useMajorIndexTickers`。自选页继续传原参数，股票详情页调用时省略日期。复用 API client、指数映射和 `TopMarketBar`。默认自选页点击股票后，详情页应发起主要指数请求，按返回的指数名称、点位、涨跌幅与方向渲染。 |
| 页面模型与状态 | 从 `StockDetailViewModel` 和 `stockDetailMockAdapter` 移除 `topMarketTickers`。详情页加载中、成功与失败均使用指数模块提供的列表。指数请求失败或无可用数据时列表为空，个股请求与状态独立。回归测试覆盖等待中、成功、失败和无数据，断言示例行情不会进入顶部栏。 |
| 读写边界与性能 | 正常鉴权下，每次进入已构建的股票详情页发起一次只读主要指数请求，与个股请求并行。现有合同返回 10 个配置项，无分页。切换图表周期或同一详情组件的股票代码时不重复发起指数请求。离开页面取消该请求，取数逻辑不额外重试，重新进入按同一请求开销重新读取。登录续期沿用现有 API client。 |
| 验证 | 运行 `npm run typecheck`、`npm run test` 和 `npm run build`。真实 API 展示验收使用隔离数据库和现有主要指数路由，通过浏览器在默认自选页和股票详情页分别对照接口响应与顶部栏的名称、点位、涨跌幅和方向，并检查控制台及请求。 |

### 验收记录

- 回归测试确认旧代码在指数数据等待中仍显示 10 条示例。修复后覆盖自选到详情跳转、指数请求等待和返回、HTTP 失败、行情字段全空，以及个股请求失败时指数仍独立显示。
- 前端类型检查和构建通过。全量前端测试 187 个文件、1,618 项通过。文档完整性和差异空白检查通过。
- 主要指数后端路由测试 2 项通过。Chromium 使用构建产物、隔离 PostgreSQL 和真实主要指数路由，从默认自选页点进 `000001.SZ`。两页各发起一次默认主要指数请求，均返回 HTTP 200 和测试交易日 `2026-09-02`。两页各 10 条指数的名称、点位、涨跌幅和方向与各自响应一致，未发现 API 失败或浏览器控制台错误。个股日 K 的指标值由测试夹具提供，本轮浏览器验收范围是顶部指数取数与展示。
