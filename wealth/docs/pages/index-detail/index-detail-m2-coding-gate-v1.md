# 指数详情页 M2 编码前门禁 v1

> 状态：草案，待评审；所有未勾选项完成前禁止进入编码。
> 需求：[指数详情页标杆需求 v1](./index-detail-benchmark-requirement-v1.md)
> 方案：[指数详情页技术实施方案 v1](./index-detail-implementation-design-v1.md)

---

## 1. 已确认产品口径

1. [x] 10 张主要指数卡片进入对应详情页。
2. [x] 默认正式能力为日线。
3. [x] 生产分钟周期置灰；本地可按 Lake capability 解锁分钟。
4. [x] 不保留“前复权”。
5. [x] 右侧三个 tab 可切换。
6. [x] 技术结论首期为空，后续独立 API。
7. [x] 九转首期为空，后续独立 API。
8. [x] 贡献点使用估算公式，不归一化、不强制对账、不把缺失当 0。
9. [x] 当前权重验收批次为 `2026-07-31`。
10. [x] 交易计划只允许用户主动点击，技术内容不触发交易动作。
11. [x] 权重加载完整批次；表头固定、视窗显示 10 行、列表内部滚动并使用虚拟化渲染。

## 2. 总门禁

1. [ ] 三件套评审通过，待评审项全部签字。
2. [ ] 10 指数 `index_factor_pro` 生产覆盖与性能审计通过。
3. [ ] 趋势通道十指数适配层与旧 SSE 契约边界冻结。
4. [ ] 请求/响应 DTO 与核心样例冻结。
5. [ ] 权重 SQL、贡献公式、日期和排序冻结。
6. [ ] 状态归并与异常矩阵冻结。
7. [ ] `ID_*` / `IM_*` 异常码已登记到统一注册表。
8. [ ] shared 图表提取边界和股票回归 case 冻结。
9. [ ] local/prod 分钟配置与路由矩阵冻结。
10. [ ] Figma Loaded 节点台账确认；`09` 状态页 `412:4` / `425:178` 已确认，Weights/Technical 根画板跨页位置需登记或归位。
11. [ ] 真实 API + 前端可见结果测试 case 冻结。
12. [ ] 后端、前端、架构/产品签字完成。

## 3. 请求参数门禁

### 3.1 正式接口

| 接口 | 参数 | 冻结规则 |
|---|---|---|
| page-init | `tsCode` | 必填、trim+upper、必须属于 `majorIndices` 10 code |
| page-init | `tradeDate` | 可选，隐藏日期锚点；不提供页面日期选择器 |
| page-init | `debug` | `0/1`，默认 0 |
| kline | `tsCode` | 同上 |
| kline | `period` | 只允许 `day`，默认 day |
| kline | `startDate/endDate` | 可选；start 不得晚于 end |
| kline | `limit` | 默认 300，范围 1..2000 |
| weights | `tsCode/tradeDate/debug` | 同 page-init；返回完整权重批次，不接受 limit，不得静默截断 |
| trend-channel | `tsCode` | 只允许 10 code |
| trend-channel | `period` | 只允许 day |
| trend-channel | `endDate/limit` | limit 默认 300，范围 1..2000 |

禁止：

1. [ ] kline 不接受 `adjustment`。
2. [ ] 不接受前端传 EMA 周期、通道公式、贡献公式或权重日期。
3. [ ] 不允许前端传 Lake path、SQL、指标参数或任意指数 code。

### 3.2 本地分钟接口

1. [ ] `freq` 必填且只能为 `1/5/15/30/60/90/120`。
2. [ ] `limit` 默认 500，最大 10000。
3. [ ] cursor 绑定 code/freq/date/time，不使用无界 OFFSET。
4. [ ] prod/staging 不挂路由；访问结果为 404。

## 4. 响应结构冻结

### 4.1 page-init 最小响应

```json
{
  "pageContext": {
    "market": "CN_A",
    "tradeDate": "2026-08-07",
    "prevTradeDate": "2026-08-06",
    "isTradingDay": true,
    "sessionStatus": "CLOSED",
    "timezone": "Asia/Shanghai",
    "generatedAt": "2026-08-10T22:45:00+08:00",
    "source": "default"
  },
  "asOfTradeDate": "2026-08-07",
  "index": {
    "tsCode": "000001.SH",
    "name": "上证指数",
    "market": "SSE",
    "category": "综合指数",
    "publisher": "中证指数有限公司",
    "tags": ["综合指数", "SSE"]
  },
  "quote": {
    "tradeDate": "2026-08-07",
    "point": 3453.24,
    "change": 13.12,
    "changePct": 0.38,
    "direction": "UP",
    "open": 3438.57,
    "high": 3462.75,
    "low": 3431.28,
    "preClose": 3440.12,
    "amplitude": 0.92,
    "vol": 482000000.0,
    "amount": 528634000.0,
    "amountChangePct": 6.8
  },
  "chartDefaults": {
    "defaultPeriod": "day",
    "availablePeriods": ["day"],
    "availableMainOverlays": ["MA", "BOLL", "TREND_CHANNEL"],
    "availableIndicatorTabs": ["VOL", "amount", "MA", "MACD", "KDJ", "BOLL"]
  },
  "capabilities": {
    "supportsTimeShare": false,
    "supportsWeeklyMonthly": false,
    "supportsMinute": false,
    "minuteFrequencies": [],
    "supportsTrendChannel": true,
    "supportsNineTurn": false,
    "supportsTechnicalConclusion": false,
    "supportsUserActions": false
  },
  "dataStatus": {
    "status": "READY",
    "expectedTradeDate": "2026-08-07",
    "observedTradeDate": "2026-08-07",
    "note": null
  }
}
```

说明：以上数值是契约形状示例，不作为 Figma 示例数值的真实性证明；真实测试必须读取 fixture/生产只读样本逐字段断言。

### 4.2 kline bar

```ts
interface IndexKlineBarDto {
  tradeDate: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  preClose: number | null;
  change: number | null;
  changePct: number | null;
  amplitude: number | null;
  vol: number | null;
  amount: number | null;
  factors: {
    ma: { ma5: number | null; ma10: number | null; ma20: number | null; ma30: number | null; ma60: number | null; ma90: number | null; ma250: number | null };
    boll: { upper: number | null; middle: number | null; lower: number | null };
    macd: { dif: number | null; dea: number | null; macd: number | null };
    kdj: { k: number | null; d: number | null; j: number | null };
  };
}
```

门禁：

1. [ ] 所有 warm-up/源缺失值保持 `null`。
2. [ ] `pct_change -> changePct` 映射集中在后端 mapper。
3. [ ] `kdj_bfq -> j`、`kdj_k_bfq -> k`、`kdj_d_bfq -> d` 固定。
4. [ ] 不返回 MA15/MA120，不临时计算。

### 4.3 权重正常样例

```json
{
  "indexRef": { "tsCode": "000300.SH", "name": "沪深300" },
  "contributionTradeDate": "2026-08-07",
  "weightTradeDate": "2026-07-31",
  "isEstimated": true,
  "rows": [
    {
      "conCode": "600519.SH",
      "name": "贵州茅台",
      "weight": 5.43,
      "changePct": 1.26,
      "contributionPoint": 2.353,
      "direction": "UP"
    }
  ],
  "coverage": {
    "totalCount": 300,
    "returnedCount": 300,
    "contributionAvailableCount": 300,
    "contributionMissingCount": 0,
    "isTruncated": false
  },
  "dataStatus": {
    "status": "READY",
    "expectedTradeDate": "2026-08-07",
    "observedTradeDate": "2026-08-07",
    "note": null
  },
  "note": "基于最新月度权重估算，非指数公司官方归因"
}
```

该样例特意说明：`3440.12 × 5.43% × 1.26% ≈ 2.35`，不是 Figma 示例中的 `+4.18`。Figma 数值只作视觉占位，不能进入业务测试金标。

### 4.4 权重 PARTIAL 样例

```json
{
  "weightTradeDate": "2026-07-31",
  "isEstimated": true,
  "rows": [
    {
      "conCode": "600000.SH",
      "name": "浦发银行",
      "weight": 1.23,
      "changePct": null,
      "contributionPoint": null,
      "direction": "UNKNOWN"
    }
  ],
  "coverage": {
    "totalCount": 300,
    "returnedCount": 300,
    "contributionAvailableCount": 299,
    "contributionMissingCount": 1,
    "isTruncated": false
  },
  "dataStatus": {
    "status": "PARTIAL",
    "expectedTradeDate": "2026-08-07",
    "observedTradeDate": "2026-08-07",
    "note": "constituent_daily_missing"
  }
}
```

### 4.5 EMPTY / ERROR

1. [ ] 主日线空：HTTP 200 + page/kline `dataStatus=EMPTY`，保留页面空态。
2. [ ] 标的非法/不在名单：404 + `ID_NOT_FOUND`。
3. [ ] 权重无批次：weights HTTP 200 + `EMPTY`，不影响主图。
4. [ ] 趋势计算失败：trend endpoint 标准错误，页面保留 kline 并局部 error。
5. [ ] 403 不能转换为 EMPTY。

## 5. 查询草案

### 5.1 标的与完成交易日

1. [ ] `StrategyConfigService.get_payload(module_key="majorIndices", market="CN_A")` 是名单唯一来源。
2. [ ] `MarketPageContextQuery` 是日期上下文唯一来源。
3. [ ] 服务层不根据 `sessionStatus` 二次减一天；默认期望日直接使用 `pageContext.tradeDate`。
4. [ ] quote 查询 `<= pageContext.tradeDate` 的最近行；该 observed date 是 `asOfTradeDate`。
5. [ ] 权重贡献使用 `asOfTradeDate`，source delayed 时仍保持同日输入并标记 DELAYED。
6. [ ] 默认日期、显式日期、非交易日和 source delayed 均有测试。

### 5.2 日线与因子

```sql
SELECT
  ts_code, trade_date,
  open, high, low, close, pre_close, change, pct_change, vol, amount,
  ma_bfq_5, ma_bfq_10, ma_bfq_20, ma_bfq_30, ma_bfq_60, ma_bfq_90, ma_bfq_250,
  boll_upper_bfq, boll_mid_bfq, boll_lower_bfq,
  macd_dif_bfq, macd_dea_bfq, macd_bfq,
  kdj_k_bfq, kdj_d_bfq, kdj_bfq
FROM core_serving.index_factor_pro
WHERE ts_code = :ts_code
  AND trade_date <= :end_date
  AND (:start_date IS NULL OR trade_date >= :start_date)
ORDER BY trade_date DESC
LIMIT :limit;
```

返回前在服务层反转为升序。必须利用 raw 基表 `(ts_code, trade_date)` 主键索引；真实 `EXPLAIN ANALYZE` 与 300/2000 根 P95 是数据门禁。

### 5.3 权重与贡献

```sql
SELECT max(trade_date)
FROM core_serving.index_weight
WHERE index_code = :index_code
  AND trade_date <= :contribution_trade_date;
```

```sql
SELECT index_code, trade_date, con_code, weight
FROM core_serving.index_weight
WHERE index_code = :index_code
  AND trade_date = :weight_trade_date
  AND weight IS NOT NULL
ORDER BY weight DESC, con_code ASC;
```

```sql
SELECT ts_code, trade_date, pct_chg
FROM core_serving.equity_daily_bar
WHERE ts_code IN (:all_constituent_codes)
  AND trade_date = :contribution_trade_date;
```

门禁：

1. [ ] 名称查询与成分日线查询均为批量查询，无 N+1。
2. [ ] 原始权重不归一化。
3. [ ] 贡献点内部用 Decimal 计算，输出精度在 DTO 评审时冻结。
4. [ ] 缺失贡献点不影响权重行展示。
5. [ ] `sum(contributionPoint)` 不用于重写任何单行值。
6. [ ] `rows.length = coverage.totalCount = coverage.returnedCount` 且 `isTruncated=false`；任何保护门禁触发时返回明确错误，禁止返回半批次。

### 5.4 趋势通道

1. [ ] query 的 `tsCode` 参数参与 watermark、source rows 和 cache key。
2. [ ] 旧 SSE endpoint 仍拒绝其他 code。
3. [ ] 新 Wealth endpoint 只允许 10 code。
4. [ ] 每个 code 只发布完整、稳定的正式日线快照。
5. [ ] 中轴由服务端最新短期上下轨平均得到，内部未量化值计算后再按价格精度输出。

## 6. 状态归并门禁

| page-init | kline | trend | 当前 tab | 页面结果 |
|---|---|---|---|---|
| READY | READY | READY | basic | READY |
| READY | READY | ERROR | basic | PARTIAL；主图无通道，基本行情可用 |
| READY | PARTIAL | READY | basic | PARTIAL；缺失指标断点，不补 0 |
| READY | READY | READY | weights loading/error | 页面 READY；权重 tab 局部 loading/error |
| READY | EMPTY | 任意 | 任意 | EMPTY 主图；保留身份与 tab 壳 |
| ERROR/404 | 未请求 | 未请求 | 任意 | 页面 fatal error/not-found |
| 403 | 未请求 | 未请求 | 任意 | FORBIDDEN |

1. [ ] 权重和技术 tab 状态不覆盖页面主状态。
2. [ ] minute 状态不污染日线缓存。
3. [ ] delayed 必须显示 observed date，不仅在 debug 中存在。
4. [ ] 真实失败不回退 mock/scaffold 数值。

## 7. 异常码登记门禁

以下 code 目前只是方案候选，登记前不得进入代码：

| code | 触发 | 预期 |
|---|---|---|
| `ID_REQUEST_INVALID` | 参数非法 | 400 |
| `ID_NOT_FOUND` | 非 10 code/身份不存在 | 404 |
| `ID_SOURCE_EMPTY` | 日线无数据 | 200 + EMPTY |
| `ID_SOURCE_DELAYED` | 日线日期落后 | 200 + DELAYED |
| `ID_FACTOR_PARTIAL` | 因子缺失 | 200 + PARTIAL |
| `ID_WEIGHT_EMPTY` | 无权重批次 | weights EMPTY |
| `ID_WEIGHT_CONTRIBUTION_PARTIAL` | 贡献输入缺失 | weights PARTIAL |
| `ID_TREND_UNAVAILABLE` | 通道源/计算失败 | trend error/页面 PARTIAL |
| `ID_QUERY_FAILED` | 查询异常 | 对应模块 error |
| `IM_SOURCE_NOT_READY` | Lake 日期缺失 | minutes DELAYED |
| `IM_SOURCE_CONTRACT_INVALID` | Parquet 合同错误 | minutes ERROR |
| `IM_QUERY_FAILED` | DuckDB/IO 错误 | minutes ERROR |

1. [ ] code、module、severity、frontendAction 已登记。
2. [ ] 旧股票分钟 `SM_*` 不被复用成指数分钟新语义。
3. [ ] 401/403 沿用认证层语义，不自造业务 EMPTY。

## 8. 前端门禁

### 8.1 路由与导航

1. [ ] `buildIndexDetailPath()` trim+upper+encode。
2. [ ] router 同时支持 `/wealth/market/index/:code`，不影响 stock route。
3. [ ] `MajorIndexPanel` 只上报码，不自行拼路径。
4. [ ] 10 卡顺序和数据仍由 major-indices API 决定。

### 8.2 Loaded 页面

1. [ ] 复用 `TopMarketBar`。
2. [ ] 不存在“前复权”文本、按钮或 hidden action。
3. [ ] 默认 Basic tab，三个 tab 都有 keyboard/ARIA tab 语义。
4. [ ] 权重表头固定、视窗恰好显示 10 行、内部纵向滚动、虚拟化渲染完整批次，并展示估算说明。
5. [ ] 技术结论和九转显示 `--`，不引用 Figma 示例文案。
6. [ ] `+交易计划` 只绑定用户点击 toast，不被 effect/数据状态调用。

### 8.3 图表共享

1. [ ] 没有复制 `StockChartWorkspace.tsx` 主实现。
2. [ ] shared chart 不含 stock/index 业务文案。
3. [ ] null 指标被过滤或绘制断点，不转 0。
4. [ ] 股票详情 90 根窗口、crosshair、tooltip、MA/BOLL、四面板回归通过。
5. [ ] 指数趋势短/长期四线可按日期对齐，无未来数据。

### 8.4 周期与环境

1. [ ] prod：日线 active；分时/周/月/所有分钟 disabled。
2. [ ] local flag false：同 prod。
3. [ ] local flag true + Lake ready：仅七个分钟 frequency enabled。
4. [ ] 权重 tab 不随分钟切换成盘中贡献。

## 9. 数据审计门禁

### 9.1 已完成：权重

1. [x] raw 与 serving 最新日均为 `2026-07-31`。
2. [x] 10 指数 serving 总行数 5274，与 raw 一致。
3. [x] 无 null weight、无批次内重复成分。
4. [x] 权重和约 `99.984~100.006`，确认不归一化。

### 9.2 待完成：指数因子

1. [ ] 10 code 均有数据。
2. [ ] 最新日与 index daily 对齐或状态可解释。
3. [ ] 每 code 至少覆盖默认 300 根；MA250 warm-up 可解释。
4. [ ] OHLC/量额与日线源抽样一致。
5. [ ] MA/BOLL/MACD/KDJ 字段非空率与 warm-up 规则通过。
6. [ ] 300/2000 根查询计划与 P95 通过。

### 9.3 待完成：本地分钟

1. [ ] Silver 七频率/10 code 覆盖符合当前日期合同。
2. [ ] Gold 指标与 Silver 时间键无重复、可对齐。
3. [ ] `899050.BJ` 历史边界明确进入状态语义。
4. [ ] API 只读正式 Lake `/Volumes/datasource/data_lake`，不读旧 Lake，不读 staging。

## 10. 性能门禁

| 项目 | 目标 | 硬门禁 |
|---|---:|---:|
| page-init P95 | 200ms | 500ms |
| kline 300 P95 | 400ms | 1s |
| weights P95 | 500ms | 1s |
| trend 热缓存 P95 | 100ms | 300ms |
| trend 冷计算 P95 | 500ms | 1s |
| local minutes P95 | 1.5s | 5s |
| kline 默认/最大 | 300 | 2000 |
| weights 行数 | 当前有效批次全量 | 不截断；响应体目标不超过 1 MiB |
| minute 默认/最大 | 500 | 10000 |

1. [ ] 所有查询只选所需列，不 `SELECT *`。
2. [ ] 权重名称/行情补列无 N+1。
3. [ ] trend cache 至少容纳 10 code，key 含 source identity/code/version/watermark。
4. [ ] 超预算先优化查询/reader，不调高 timeout 掩盖。

## 11. 测试门禁

### 11.1 后端真实 API

1. [ ] 真实 FastAPI route，禁止只 mock query/service。
2. [ ] 10 code page-init 参数化测试。
3. [ ] kline 字段、null、排序、limit、非法 adjustment 负向测试。
4. [ ] 权重 2026-07-31、完整批次、排序、覆盖计数、不截断、公式、缺失、不归一化、不缩放。
5. [ ] trend 10 code + 旧 SSE endpoint 全回归。
6. [ ] auth、not-found、delayed、empty、partial、error。
7. [ ] prod 分钟 route 不存在；local 临时真实 Parquet 可查询。

### 11.2 前端真实 API 展示

1. [ ] 不使用 mock adapter 证明 ready。
2. [ ] 10 卡导航和 router history。
3. [ ] page loading/error/empty/partial/forbidden。
4. [ ] 三 tab、权重懒加载缓存、10 行虚拟滚动并可到达末行、技术空字段。
5. [ ] prod/local 周期能力。
6. [ ] 页面无“前复权”。
7. [ ] 股票详情共享图表回归。

### 11.3 命令

```bash
pytest -q tests/web/test_wealth_index_detail_api.py tests/test_quote_trend_channel_query_service.py
cd wealth && npm run typecheck
cd wealth && npm run test
cd wealth && npm run build
```

## 12. 签字清单

### 后端

1. [ ] 数据源和查询可实现。
2. [ ] DTO、状态、异常无歧义。
3. [ ] 贡献公式与趋势复用边界正确。

### 前端

1. [ ] Figma Loaded 结构可实现。
2. [ ] shared chart 重构范围可控。
3. [ ] 三 tab、周期、异常态可落地。

### 架构/产品

1. [ ] 需求未扩散到技术结论、九转或交易流程。
2. [ ] 五个技术口径已逐项确认；其中权重全量与 10 行滚动已由产品确认，其余四项仍需签字。
3. [ ] 同意进入 M1 数据与契约开发。

## 13. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1.1 | 2026-08-11 | 权重门禁改为完整批次、10 行虚拟滚动与不截断；确认 09 状态页并补异常恢复要求 | Codex |
| v1 | 2026-08-10 | 首版编码门禁草案，已区分已拍板产品口径与未通过实施门禁 | Codex |
