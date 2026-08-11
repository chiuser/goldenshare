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
12. [x] 趋势通道仅支持 `000001.SH + day`，直接消费既有 Quote API；其余指数不展示、不请求，不开发适配层。
13. [x] 趋势通道为短期25/长期90双通道；每个交易日都有竖线，按当日收盘相对各自下轨逐日着色并允许在交易日边界切换；右侧展示四轨、不展示中轴。
14. [x] 基本行情固定展示 15 项，缺值显示 `--`；删除“成交状态”和“较昨日”。
15. [x] 上涨/平盘/下跌按最新有效成分批次与同日股票涨跌幅 `> 0 / = 0 / < 0` 聚合；缺失成员不计入平盘。
16. [x] Loading、Empty、Error、Partial、Forbidden 已生成五个 `1600×1200` 完整视觉稿，根节点分别为 `498:516`、`499:579`、`501:761`、`502:1625`、`504:1009`。
17. [x] 五态复用同一 TopMarketBar、面包屑和周期工具栏；Loading/Empty/Partial 保持双栏尺寸，Error/Forbidden 只把 MainContent 改成全宽状态面板。
18. [x] 系统状态色冻结：Error 使用 danger-system，Partial 使用 warning，Forbidden 使用 info，不复用行情红绿。

## 2. 总门禁

1. [ ] 三件套评审通过，待评审项全部签字。
2. [ ] 10 指数 `index_factor_pro` 生产覆盖与性能审计通过。
3. [x] 趋势通道边界冻结：既有 SSE 契约保持不变，仅上证指数消费；无十指数适配层。
4. [ ] 请求/响应 DTO 与核心样例冻结。
5. [ ] 权重 SQL、贡献公式、日期和排序冻结。
6. [ ] 状态归并与异常矩阵冻结。
7. [ ] `ID_*` / `IM_*` 异常码已登记到统一注册表。
8. [ ] shared 图表提取边界和股票回归 case 冻结。
9. [ ] local/prod 分钟配置与路由矩阵冻结。
10. [x] Figma 节点台账已确认：Basic Loaded `417:2`、Weights `423:2`、Technical `423:910`、Components `412:3`、交互说明 `425:178`、五态根画板已登记；Weights/Technical 的 Cover 跨页位置已显式记录。
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
| 既有 Quote trend-channel | `tsCode` | 固定 `000001.SH`；由 capability 控制是否请求 |
| 既有 Quote trend-channel | `period` | 固定 day |
| 既有 Quote trend-channel | `endDate/limit` | 沿用既有契约，不在指数详情模块扩展 |

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
    "tradeDate": "2026-08-10",
    "prevTradeDate": "2026-08-07",
    "isTradingDay": true,
    "sessionStatus": "CLOSED",
    "timezone": "Asia/Shanghai",
    "generatedAt": "2026-08-11T10:00:00+08:00",
    "source": "default"
  },
  "asOfTradeDate": "2026-08-10",
  "index": {
    "tsCode": "000001.SH",
    "name": "上证指数",
    "market": "SSE",
    "category": "综合指数",
    "publisher": "中证指数有限公司",
    "tags": ["综合指数", "SSE"]
  },
  "quote": {
    "tradeDate": "2026-08-10",
    "point": 3966.5935,
    "change": 26.5564,
    "changePct": 0.674,
    "direction": "UP",
    "open": 3943.816,
    "high": 3967.5919,
    "low": 3938.625,
    "preClose": 3940.0371,
    "vol": 542118110.0,
    "amount": 1166893282.3538
  },
  "dailyBasic": {
    "tradeDate": "2026-08-10",
    "pe": 17.16,
    "peTtm": 16.88,
    "pb": 1.49,
    "turnoverRate": 1.10,
    "floatMv": 61120718611804.02,
    "totalMv": 77487881305217.33
  },
  "constituentBreadth": {
    "tradeDate": "2026-08-10",
    "weightTradeDate": "2026-07-31",
    "upCount": 1613,
    "flatCount": 37,
    "downCount": 534,
    "totalConstituentCount": 2224,
    "matchedCount": 2184,
    "missingCount": 40,
    "dataStatus": {
      "status": "PARTIAL",
      "expectedTradeDate": "2026-08-10",
      "observedTradeDate": "2026-08-10",
      "note": "constituent_daily_missing"
    }
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
    "status": "PARTIAL",
    "expectedTradeDate": "2026-08-10",
    "observedTradeDate": "2026-08-10",
    "note": "constituent_daily_missing"
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

### 4.6 五态视觉响应合同

1. [ ] LOADING：保留外层页面骨架；左图表与右栏均为 skeleton；清空上一标的详情 ViewModel，不展示旧行情或 mock；主文案固定为“正在加载指数行情”，副文案仅上证指数包含“趋势通道”，其余 9 个指数只写“正在读取日线与技术指标”。
2. [ ] EMPTY：保留指数身份、工具栏、三个 Tab 和 Basic 卡片；主价格、涨跌与 15 个指标值全部为 `--`；提供“重新加载 / 查看最近交易日”。
3. [ ] ERROR：保留 TopMarketBar、面包屑和工具栏；MainContent 使用 `1580×1038` 全宽错误面板；提供“重新加载 / 返回指数首页”。
4. [ ] PARTIAL：保留 Loaded 图表和所有可用数据；仅真实缺失项显示 `--`；提示文案由缺失字段集合生成，不得写死 Figma 示例的金额、TTM 市盈率、平盘数。
5. [ ] FORBIDDEN：保留外层页面骨架；MainContent 使用 `1580×1038` 全宽权限面板；不自动重试、不发起后续详情请求，提供“返回指数首页”。
6. [ ] 404 没有独立像素稿，复用 ERROR 全宽壳并显示“指数不存在”；DELAYED 保留 Loaded 数据并显示实际观测日期，不伪装 EMPTY。
7. [ ] 真实接口失败后禁止回填 mock；TopMarketBar 的全局 ticker 不属于当前指数详情旧数据，可以保留。
8. [ ] EMPTY“重新加载”保留当前查询参数；“查看最近交易日”移除隐藏 `tradeDate` 后 replace 到同一指数路由。默认日期仍无数据时继续 EMPTY，不任意回退历史日期。

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

### 5.2.1 基本行情日度指标与成分涨跌统计

1. [ ] `dailyBasic` 只查询 `trade_date = asOfTradeDate` 的 `pe/pe_ttm/pb/turnover_rate/float_mv/total_mv`；无行或字段为空保持 `null`。
2. [ ] `constituentBreadth.weightTradeDate = max(index_weight.trade_date) <= asOfTradeDate`，随后对完整批次 `con_code` 与同日 `equity_daily_bar.pct_chg` 做集合聚合。
3. [ ] `pct_chg > 0` 计入 up、`= 0` 计入 flat、`< 0` 计入 down；无行情或 `pct_chg IS NULL` 只计入 missing。
4. [ ] `upCount + flatCount + downCount = matchedCount`，`matchedCount + missingCount = totalConstituentCount`。
5. [ ] missing 大于 0 时保留三项计数并返回模块 PARTIAL；无权重批次时三项为不可用，不返回伪 0。
6. [ ] page-init 不查询前一交易日成交额，不返回 `amountChangePct`。

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

1. [ ] 不新增 Wealth trend endpoint，不修改 `QuoteTrendChannelQuery`、计算器、公式版本或 cache key。
2. [ ] 既有 SSE endpoint 继续只接受 `000001.SH + day` 并拒绝其他 code。
3. [ ] `page-init.supportsTrendChannel` 仅对 `000001.SH + day` 为 true；其余 9 个指数无入口、无请求。
4. [ ] 每个交易日都绘制短期/长期上轨、下轨和同日竖向连接，不能抽样省略；相邻交易日分别连接上下轨，不绘制中轴或辅助分区。
5. [ ] 页面颜色不用趋势 `state`，而是逐日比较收盘与下轨：短期 `close < shortLower` 为绿、否则红；长期 `close < longLower` 为蓝、否则粉。交易日 `t` 的竖线和连到 `t+1` 的上下轨线段使用 `t` 日颜色，到下一日重新判定。
6. [ ] 右侧技术页签展示短期上轨、短期下轨、长期上轨、长期下轨；缺失显示 `--`。

## 6. 状态归并门禁

| page-init | kline | trend | 当前 tab | 页面结果 |
|---|---|---|---|---|
| READY | READY | READY | basic | READY |
| READY | READY | ERROR | basic | PARTIAL；主图无通道，基本行情可用 |
| READY | PARTIAL | READY | basic | PARTIAL；缺失指标断点，不补 0 |
| PARTIAL | READY | READY | basic | 基本行情保留可用字段/计数；缺失字段显示 `--`，缺失成分不计入平盘 |
| READY | READY | READY | weights loading/error | 页面 READY；权重 tab 局部 loading/error |
| READY | EMPTY | 任意 | 任意 | EMPTY 主图；保留身份与 tab 壳 |
| ERROR/404 | 未请求 | 未请求 | 任意 | 页面 fatal error/not-found |
| 403 | 未请求 | 未请求 | 任意 | FORBIDDEN |

1. [ ] 权重和技术 tab 状态不覆盖页面主状态。
2. [ ] minute 状态不污染日线缓存。
3. [ ] delayed 必须显示 observed date，不仅在 debug 中存在。
4. [ ] 真实失败不回退 mock/scaffold 数值。
5. [ ] 页面级状态优先级固定为：401 认证跳转 > 403 FORBIDDEN > 404/非法指数 > fatal ERROR > EMPTY > PARTIAL/DELAYED > READY。
6. [ ] 页面级 ERROR/EMPTY/FORBIDDEN 的恢复动作与 Figma 文案一致；模块级错误只能局部重试。

## 7. 异常码登记门禁

以下 code 目前只是方案候选，登记前不得进入代码：

| code | 触发 | 预期 |
|---|---|---|
| `ID_REQUEST_INVALID` | 参数非法 | 400 |
| `ID_NOT_FOUND` | 非 10 code/身份不存在 | 404 |
| `ID_SOURCE_EMPTY` | 日线无数据 | 200 + EMPTY |
| `ID_SOURCE_DELAYED` | 日线日期落后 | 200 + DELAYED |
| `ID_FACTOR_PARTIAL` | 因子缺失 | 200 + PARTIAL |
| `ID_BASIC_BREADTH_PARTIAL` | 成分股当日行情缺失 | page-init 基本行情模块 PARTIAL |
| `ID_WEIGHT_EMPTY` | 无权重批次 | weights EMPTY |
| `ID_WEIGHT_CONTRIBUTION_PARTIAL` | 贡献输入缺失 | weights PARTIAL |
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
7. [ ] 基本行情严格按顺序展示 15 项；缺值显示 `--`，不存在“成交状态”和“较昨日”。
8. [ ] 上涨/平盘/下跌使用 API 聚合值；前端不遍历权重行重算，不把 missing 算作平盘。
9. [ ] Loading 使用图表/右栏骨架，不只显示居中文案；不得直接复制股票详情当前简化 loading DOM。
10. [ ] Empty 右栏保留身份和三个 Tab，主价格、涨跌及 15 个指标值均为 `--`。
11. [ ] Error/Forbidden 使用全宽主面板但不删除外层页面壳；Partial 不清空图表或可用字段。
12. [ ] Error/Partial/Forbidden 分别使用 `--cs-color-danger-system`、`--cs-color-warning`、`--cs-color-info`，测试断言未使用 `--cs-color-market-up/down`。

### 8.3 图表共享

1. [ ] 没有复制 `StockChartWorkspace.tsx` 主实现。
2. [ ] shared chart 不含 stock/index 业务文案。
3. [ ] null 指标被过滤或绘制断点，不转 0。
4. [ ] 股票详情 90 根窗口、crosshair、tooltip、MA/BOLL、四面板回归通过。
5. [ ] 上证指数趋势短/长期四轨与每日竖线可按日期对齐，无未来数据；每个交易日都有竖线，颜色切换点连续；短期红/绿、长期粉/蓝四种组合均有测试。
6. [ ] 其余 9 个指数不渲染趋势入口、不调用趋势接口。

### 8.4 周期与环境

1. [ ] prod：日线 active；分时/周/月/所有分钟 disabled。
2. [ ] local flag false：同 prod。
3. [ ] local flag true + Lake ready：仅七个分钟 frequency enabled。
4. [ ] 权重 tab 不随分钟切换成盘中贡献。

### 8.5 Figma 结构与像素门禁

1. [ ] 页面为 `1600×1200`：TopMarketBar 56px、面包屑 42px、工具栏 44px、主内容区 1058px。
2. [ ] Loaded/Loading/Empty/Partial 双栏保持：左 `1193.1953125×1038`、间距 10px、右 `376.796875×1038`、主内容内边距 10px。
3. [ ] TopMarketBar 使用共享组件，不复制第二套；右栏三个 Tab 共享稳定 Header/Tabs 骨架。
4. [ ] 页面骨架、状态内容、按钮组、指标卡片和列表使用 Auto Layout/CSS Grid/Flex；不得用大量补偿坐标模拟布局。
5. [ ] K 线、趋势通道、九转位置、指标、坐标轴、Tooltip、十字线保留图表坐标定位，状态切换不得使其位移。
6. [ ] 普通 UI 相对 Figma 基线偏差不超过 2px，无新增换行、裁剪、重叠或溢出。
7. [ ] Partial 提示内部为流式布局；若以右栏覆盖层定位，必须只有一个稳定锚点，不能改变 Info Rail 组件实例结构。
8. [ ] `425:190` 是过期概述，不进入实现或测试；Basic 字段金标只能来自 `414:446`、`425:219` 和三件套 15 项清单。

## 9. 数据审计门禁

### 9.1 已完成：权重

1. [x] raw 与 serving 最新日均为 `2026-07-31`。
2. [x] 10 指数 serving 总行数 5274，与 raw 一致。
3. [x] 无 null weight、无批次内重复成分。
4. [x] 权重和约 `99.984~100.006`，确认不归一化。

### 9.2 已完成：基本行情字段与成分涨跌统计

1. [x] 10 指数 `2026-08-10` 的昨收、今开、总量、最高、最低、金额均有值。
2. [x] PE/PE TTM/PB/换手率/流通市值/总市值只覆盖 6 个指数，合同必须可空且 UI 缺值显示 `--`。
3. [x] 10 指数均解析到 `2026-07-31` 有效权重批次；9 个指数成分日线完整匹配。
4. [x] `000001.SH` total 2224、matched 2184、up 1613、flat 37、down 534、missing 40；missing 不计入 flat。

### 9.3 待完成：指数因子

1. [ ] 10 code 均有数据。
2. [ ] 最新日与 index daily 对齐或状态可解释。
3. [ ] 每 code 至少覆盖默认 300 根；MA250 warm-up 可解释。
4. [ ] OHLC/量额与日线源抽样一致。
5. [ ] MA/BOLL/MACD/KDJ 字段非空率与 warm-up 规则通过。
6. [ ] 300/2000 根查询计划与 P95 通过。

### 9.4 待完成：本地分钟

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
3. [ ] 趋势接口沿用既有 SSE 单标的缓存与性能门禁，不新增十指数缓存。
4. [ ] 超预算先优化查询/reader，不调高 timeout 掩盖。

## 11. 测试门禁

### 11.1 后端真实 API

1. [ ] 真实 FastAPI route，禁止只 mock query/service。
2. [ ] 10 code page-init 参数化测试。
3. [ ] kline 字段、null、排序、limit、非法 adjustment 负向测试。
4. [ ] 权重 2026-07-31、完整批次、排序、覆盖计数、不截断、公式、缺失、不归一化、不缩放。
5. [ ] 既有 SSE endpoint 全回归；上证指数请求成功，其余 9 个指数前端断言零请求。
6. [ ] auth、not-found、delayed、empty、partial、error。
7. [ ] prod 分钟 route 不存在；local 临时真实 Parquet 可查询。

### 11.2 前端真实 API 展示

1. [ ] 不使用 mock adapter 证明 ready。
2. [ ] 10 卡导航和 router history。
3. [ ] page loading/error/empty/partial/forbidden 分别对照 `498:516`、`501:761`、`499:579`、`502:1625`、`504:1009`。
4. [ ] 三 tab、权重懒加载缓存、10 行虚拟滚动并可到达末行、技术空字段。
5. [ ] prod/local 周期能力。
6. [ ] 页面无“前复权”。
7. [ ] 股票详情共享图表回归。
8. [ ] Loading 无上一标的详情值；Empty 有 17 个指数专属 `--` 占位（主价格、涨跌、15 项指标）。
9. [ ] Partial 的 Figma fixture 仅缺金额、TTM 市盈率、平盘数，同时有另一缺失组合证明提示与占位不是写死。
10. [ ] Error/FORBIDDEN 外层骨架尺寸不变，MainContent 为全宽面板；恢复按钮执行正确动作。
11. [ ] 状态颜色 token 与行情颜色 token 语义分离。

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
4. [ ] 五态逐画板结构、文案、动作、颜色与数据保留规则可落地。

### 架构/产品

1. [ ] 需求未扩散到技术结论、九转或交易流程。
2. [x] 技术口径已逐项确认：SSE-only 趋势、逐日四轨绘制与每日竖线、权重全量滚动、基本行情 15 项、成分涨跌统计与缺失规则。
3. [x] 右侧基本行情最终展示组合已完成产品选择并同步 Figma。
4. [ ] 同意进入 M1 数据与契约开发。

## 13. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1.4 | 2026-08-11 | 登记最新 Loaded/Components/五态节点台账；补五态响应、状态优先级、Auto Layout/图表定位、系统颜色和逐画板像素/测试门禁；排除 Figma 旧概述文案 | Codex |
| v1.3 | 2026-08-11 | 冻结逐日趋势判色/每日竖线、15 项基本行情、成分涨跌聚合与缺失规则；移除成交状态/较昨日门禁并补生产证据 | Codex |
| v1.2 | 2026-08-11 | 趋势门禁改为仅上证指数直接消费既有 API；删除十指数适配、中轴和十指数缓存门禁；补双通道绘制/配色、成交状态与字段选择门禁 | Codex |
| v1.1 | 2026-08-11 | 权重门禁改为完整批次、10 行虚拟滚动与不截断；确认 09 状态页并补异常恢复要求 | Codex |
| v1 | 2026-08-10 | 首版编码门禁草案，已区分已拍板产品口径与未通过实施门禁 | Codex |
