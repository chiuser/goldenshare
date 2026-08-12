# 指数详情页 M2 编码前门禁 v1

> 状态：M1–M4 与 M5-A 条目已通过；共享图表缩放门禁已由 `61a5adea` 闭环；M5-B 正式 Gold 数据门禁已通过，前端真实 provider 与 Mock 清零进入本轮实施。
> 需求：[指数详情页标杆需求 v1](./index-detail-benchmark-requirement-v1.md)
> 方案：[指数详情页技术实施方案 v1](./index-detail-implementation-design-v1.md)
> LLD：[指数详情页低层设计 v1](./index-detail-low-level-design-v1.md)
> 正式 DTO：[指数详情页正式 API / DTO 合同 v1](./index-detail-api-contract-v1.md)
> M0 生产审计：[指数详情页 M0 生产因子审计 v1](./index-detail-m0-production-audit-v1.md)
> 分钟 DTO：[指数详情本地分钟 API / DTO 合同 v1](./index-detail-minutes-api-contract-v1.md)

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
15. [x] 上涨/平盘/下跌只统计最新有效权重批次中的 A 股；同日 daily `pct_chg` 优先，缺 daily 且有精确日 `suspend_type='S'` 时按平盘，只有两类证据都没有才计 missing；B 股不进入 total/missing。
16. [x] Loading、Empty、Error、Partial、Forbidden 已生成五个 `1600×1200` 完整视觉稿，根节点分别为 `498:516`、`499:579`、`501:761`、`502:1625`、`504:1009`。
17. [x] 五态复用同一 TopMarketBar、面包屑和周期工具栏；Loading/Empty/Partial 保持双栏尺寸，Error/Forbidden 只把 MainContent 改成全宽状态面板。
18. [x] 系统状态色冻结：Error 使用 danger-system，Partial 使用 warning，Forbidden 使用 info，不复用行情红绿。

## 2. 总门禁

1. [ ] 三件套评审通过，待评审项全部签字。
2. [x] 10 指数 `index_factor_pro` 生产覆盖与当前生产数据库内性能审计通过；真实 2000 行 API P95 仍属实现后门禁。
3. [x] 趋势通道边界冻结：既有 SSE 契约保持不变，仅上证指数消费；无十指数适配层。
4. [x] page-init/kline/weights 请求、响应 DTO 与核心样例已按 `1.2.0` 冻结；字段集不变，收紧 A 股集合与停牌解析语义。
5. [x] 权重 SQL、贡献公式、日期、完整批次和排序已冻结。
6. [x] 状态归并与异常矩阵冻结。
7. [x] `ID_*` / `IM_*` 异常码已登记到统一注册表。
8. [x] shared 图表提取边界和股票回归 case 冻结。
9. [x] local/prod 分钟配置与路由矩阵冻结：prod/staging 404；local 仅在既有 capability 与正式 Lake 根满足时挂路由。
10. [x] Figma 节点台账已确认：Basic Loaded `417:2`、Weights `423:2`、Technical `423:910`、Components `412:3`、交互说明 `425:178`、五态根画板已登记；Weights/Technical 的 Cover 跨页位置已显式记录。
11. [x] 真实 API + 前端可见结果测试 case 冻结。
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
| weights | `tsCode/tradeDate/debug` | 同 page-init；返回官方批次中的完整 A 股子集，不接受 limit，不得静默截断，不归一化 A 股权重 |
| 既有 Quote trend-channel | `tsCode` | 固定 `000001.SH`；由 capability 控制是否请求 |
| 既有 Quote trend-channel | `period` | 固定 day |
| 既有 Quote trend-channel | `endDate/limit` | 沿用既有契约，不在指数详情模块扩展 |

禁止：

1. [x] kline 不接受 `adjustment`。
2. [x] 不接受前端传 EMA 周期、通道公式、贡献公式或权重日期。
3. [x] 不允许前端传 Lake path、SQL、指标参数或任意指数 code。

### 3.2 本地分钟接口

1. [x] `freq` 必填且只能为 `1/5/15/30/60/90/120`。
2. [x] `limit` 默认 500，最大 10000；响应上限 5MB。
3. [x] cursor 绑定 dataset/code/freq/start/end/date/time，不使用无界 OFFSET。
4. [x] prod/staging 不挂路由；访问结果为 404。
5. [x] M5-A Mock 仅位于前端 indicator provider，显示“模拟指标”，不进入后端、不作真实接口 fallback。

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
    "totalConstituentCount": 2184,
    "matchedCount": 2184,
    "missingCount": 0,
    "dataStatus": {
      "status": "READY",
      "expectedTradeDate": "2026-08-10",
      "observedTradeDate": "2026-08-10"
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
    "supportsTradePlanEntry": true
  },
  "dataStatus": {
    "status": "READY",
    "expectedTradeDate": "2026-08-10",
    "observedTradeDate": "2026-08-10"
  },
  "debugInfo": null
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

1. [ ] 所有历史不足/源缺失值保持 `null`，不补 0、不向前填充、不临时重算 MA。
2. [ ] `pct_change -> changePct` 映射集中在后端 mapper。
3. [ ] `kdj_bfq -> j`、`kdj_k_bfq -> k`、`kdj_d_bfq -> d` 固定。
4. [ ] 不返回 MA15/MA120，不临时计算。
5. [x] DTO 源已冻结：Kline 价格/量额/技术指标均取 factor；page-init `vol/amount` 取 `asOfTradeDate` 同日 factor；禁止 daily 量额 fallback/倍率换算。
6. [x] MA null 口径不含 code/date 特例：同 code 截至该日有效历史根数小于 N 才属于合理历史不足；达到 N 后仍为空则 PARTIAL。
7. [ ] 正向测试：有效历史为 249 根且 `ma250=null` 时保留 null，不因该字段单独标记 PARTIAL。
8. [ ] 负向测试：有效历史达到 250 根但 `ma250=null` 时返回 null + `ID_FACTOR_PARTIAL`。
9. [ ] 回填测试：加入更早历史后，同一 bar 无需修改 code/date 规则即可按新历史根数重新分类。
10. [ ] 静态审计：kline service/mapper 中不存在 `000510.SH`、`2025-09-30` 或其它 MA warm-up 特例。

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
      "contributionPoint": 2.3537,
      "direction": "UP"
    }
  ],
  "coverage": {
    "totalCount": 1,
    "returnedCount": 1,
    "contributionAvailableCount": 1,
    "contributionMissingCount": 0,
    "isTruncated": false
  },
  "dataStatus": {
    "status": "READY",
    "expectedTradeDate": "2026-08-07",
    "observedTradeDate": "2026-08-07"
  },
  "note": "基于最新月度权重估算，非指数公司官方归因",
  "debugInfo": null
}
```

该样例是单行最小 contract fixture，因此 coverage 为 1；生产响应必须返回完整批次。公式特意说明：`3440.12 × 5.43% × 1.26% = 2.3537`（四位舍入），不是 Figma 示例中的 `+4.18`。Figma 数值只作视觉占位，不能进入业务测试金标。

### 4.4 权重 PARTIAL 样例

```json
{
  "indexRef": { "tsCode": "000300.SH", "name": "沪深300" },
  "contributionTradeDate": "2026-08-07",
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
    "totalCount": 1,
    "returnedCount": 1,
    "contributionAvailableCount": 0,
    "contributionMissingCount": 1,
    "isTruncated": false
  },
  "dataStatus": {
    "status": "PARTIAL",
    "expectedTradeDate": "2026-08-07",
    "observedTradeDate": "2026-08-07"
  },
  "note": "基于最新月度权重估算，非指数公司官方归因",
  "debugInfo": null
}
```

### 4.5 EMPTY / ERROR

1. [x] 主日线空：HTTP 200 + page/kline `dataStatus=EMPTY`，保留页面空态。
2. [x] code 格式/其它参数非法：400 + `ID_REQUEST_INVALID`；格式合法但不在名单：404 + `ID_NOT_FOUND`。
3. [x] 权重无批次：weights HTTP 200 + `EMPTY`，不影响主图。
4. [x] 趋势计算失败：trend endpoint 标准错误，页面保留 kline 并局部 error。
5. [x] 403 不能转换为 EMPTY。

### 4.6 五态视觉响应合同

1. [x] LOADING：保留外层页面骨架；左图表与右栏均为 skeleton；清空上一标的详情 ViewModel，不展示旧行情或 mock；主文案固定为“正在加载指数行情”，副文案仅上证指数包含“趋势通道”，其余 9 个指数只写“正在读取日线与技术指标”。
2. [x] EMPTY：保留指数身份、工具栏、三个 Tab 和 Basic 卡片；主价格、涨跌与 15 个指标值全部为 `--`；提供“重新加载 / 查看最近交易日”。
3. [x] ERROR：保留 TopMarketBar、面包屑和工具栏；MainContent 使用 `1580×1038` 全宽错误面板；提供“重新加载 / 返回指数首页”。
4. [x] PARTIAL：保留 Loaded 图表和所有可用数据；仅真实缺失项显示 `--`；提示文案由缺失字段集合生成，不得写死 Figma 示例的金额、TTM 市盈率、平盘数。
5. [x] FORBIDDEN：保留外层页面骨架；MainContent 使用 `1580×1038` 全宽权限面板；不自动重试、不发起后续详情请求，提供“返回指数首页”。
6. [x] 404 没有独立像素稿，复用 ERROR 全宽壳并显示“指数不存在”；DELAYED 保留 Loaded 数据并显示实际观测日期，不伪装 EMPTY。
7. [x] 真实接口失败后禁止回填 mock；TopMarketBar 的全局 ticker 不属于当前指数详情旧数据，可以保留。
8. [x] EMPTY“重新加载”保留当前查询参数；“查看最近交易日”移除隐藏 `tradeDate` 后 replace 到同一指数路由。默认日期仍无数据时继续 EMPTY，不任意回退历史日期。

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
  f.ts_code, f.trade_date,
  f.open, f.high, f.low, f.close, f.pre_close, f.change, f.pct_change,
  f.vol, f.amount,
  f.ma_bfq_5, f.ma_bfq_10, f.ma_bfq_20, f.ma_bfq_30, f.ma_bfq_60, f.ma_bfq_90, f.ma_bfq_250,
  f.boll_upper_bfq, f.boll_mid_bfq, f.boll_lower_bfq,
  f.macd_dif_bfq, f.macd_dea_bfq, f.macd_bfq,
  f.kdj_k_bfq, f.kdj_d_bfq, f.kdj_bfq
FROM core_serving.index_factor_pro AS f
WHERE f.ts_code = :ts_code
  AND f.trade_date <= :end_date
  AND (:start_date IS NULL OR f.trade_date >= :start_date)
ORDER BY f.trade_date DESC
LIMIT :limit;
```

返回前在服务层反转为升序。价格、量额与技术指标全部取 factor；禁止 daily 量额 fallback 或倍率修正。查询必须利用 factor `(ts_code, trade_date)` 主键索引。M0 旧候选 joined 查询的数据库内 P95 为 300 根 1.636ms、2000-limit 2.127ms，可作保守参考；factor-only 精确 SQL、真实 2000 行与 API P95 仍是实现后门禁。

### 5.2.1 基本行情日度指标与成分涨跌统计

1. [x] `dailyBasic` 只查询 `trade_date = asOfTradeDate` 的 `pe/pe_ttm/pb/turnover_rate/float_mv/total_mv`；无行或字段为空保持 `null`。
2. [x] page-init quote 的日期/价格取 latest daily，`vol/amount` 只取同 code、`trade_date=asOfTradeDate` 的 factor；factor 缺失时为 null + `ID_FACTOR_PARTIAL`，不得回退 daily。
3. [x] `constituentBreadth.weightTradeDate = max(index_weight.trade_date) <= asOfTradeDate`，随后将该批次 INNER JOIN `Security`，只保留 `security_type=EQUITY`、`exchange in (SSE,SZSE,BSE)`、`curr_type=CNY` 的 A 股；禁止按代码前缀过滤。
4. [x] A 股精确日 `equity_daily_bar.pct_chg` 非空时优先：`> 0` 计 up、`= 0` 计 flat、`< 0` 计 down；daily 缺失/空值但精确日有 `equity_suspend_d.suspend_type='S'` 时计 matched/flat；两类证据都没有才计 missing。daily 与停牌同时存在时 daily 优先。
5. [x] `upCount + flatCount + downCount = matchedCount`，`matchedCount + missingCount = totalConstituentCount`。
6. [x] 只有 A 股 missing 大于 0 时保留三项计数并返回模块 PARTIAL；B 股排除和已证实停牌不触发 PARTIAL；无权重批次时三项为不可用，不返回伪 0。
7. [x] page-init 不查询前一交易日成交额，不返回 `amountChangePct`。

### 5.3 权重与贡献

```sql
SELECT max(trade_date)
FROM core_serving.index_weight
WHERE index_code = :index_code
  AND trade_date <= :contribution_trade_date;
```

```sql
SELECT w.index_code, w.trade_date, w.con_code, w.weight
FROM core_serving.index_weight w
JOIN core_serving.security_serving s
  ON s.ts_code = w.con_code
 AND s.security_type = 'EQUITY'
 AND s.exchange IN ('SSE', 'SZSE', 'BSE')
 AND s.curr_type = 'CNY'
WHERE w.index_code = :index_code
  AND w.trade_date = :weight_trade_date
  AND w.weight IS NOT NULL
ORDER BY weight DESC, con_code ASC;
```

```sql
SELECT
  w.con_code,
  CASE
    WHEN e.pct_chg IS NOT NULL THEN e.pct_chg
    WHEN EXISTS (
      SELECT 1
      FROM core_serving.equity_suspend_d sd
      WHERE sd.ts_code = w.con_code
        AND sd.trade_date = :contribution_trade_date
        AND sd.suspend_type = 'S'
    ) THEN 0
    ELSE NULL
  END AS resolved_pct_chg
FROM core_serving.index_weight w
JOIN core_serving.security_serving s
  ON s.ts_code = w.con_code
 AND s.security_type = 'EQUITY'
 AND s.exchange IN ('SSE', 'SZSE', 'BSE')
 AND s.curr_type = 'CNY'
LEFT JOIN core_serving.equity_daily_bar e
  ON e.ts_code = w.con_code
 AND e.trade_date = :contribution_trade_date
WHERE w.index_code = :index_code
  AND w.trade_date = :weight_trade_date;
```

门禁：

1. [x] 名称查询与成分日线查询均为集合查询，无 N+1。
2. [x] A 股官方原始权重不归一化；B 股不进入 rows/coverage，也不在前端二次过滤。
3. [x] 贡献点内部用 Decimal 计算，输出按 4 位 `ROUND_HALF_UP` 冻结。
4. [x] 停牌证据解析为 `changePct=0/direction=FLAT/contributionPoint=0` 并计 available；真实缺失贡献点不影响权重行展示。
5. [x] `sum(contributionPoint)` 不用于重写任何单行值。
6. [x] `rows.length = coverage.totalCount = coverage.returnedCount` 且 `isTruncated=false`；任何保护门禁触发时返回明确错误，禁止返回半批次。
7. [x] 以 1.2.0 最终 SQL 对 10 指数重跑只读查询计划与服务链性能：page-init P95 245.589ms、weights P95 267.319ms，最大 2184 行/275,543B；上证 breadth/weights SQL 约 21.993ms/19.290ms。2026-08-11 的 1.1.0 数值只作历史基线。

### 5.4 趋势通道

1. [x] 不新增 Wealth trend endpoint，不修改 `QuoteTrendChannelQuery`、计算器、公式版本或 cache key。
2. [x] 既有 SSE endpoint 继续只接受 `000001.SH + day` 并拒绝其他 code。
3. [x] `page-init.supportsTrendChannel` 仅对 `000001.SH + day` 为 true；其余 9 个指数无入口、无请求。
4. [x] 每个交易日都绘制短期/长期上轨、下轨和同日竖向连接，不能抽样省略；相邻交易日分别连接上下轨，不绘制中轴或辅助分区。
5. [x] 页面颜色不用趋势 `state`，而是逐日比较收盘与下轨：短期 `close < shortLower` 为绿、否则红；长期 `close < longLower` 为蓝、否则粉。交易日 `t` 的竖线和连到 `t+1` 的上下轨线段使用 `t` 日颜色，到下一日重新判定。
6. [x] 右侧技术页签展示短期上轨、短期下轨、长期上轨、长期下轨；缺失显示 `--`。

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

1. [x] 权重和技术 tab 状态不覆盖页面主状态。
2. [ ] minute 状态不污染日线缓存。
3. [x] delayed 必须显示 observed date，不仅在 debug 中存在。
4. [x] 真实失败不回退 mock/scaffold 数值。
5. [x] 页面级状态优先级固定为：401 认证跳转 > 403 FORBIDDEN > 404/非法指数 > fatal ERROR > EMPTY > PARTIAL/DELAYED > READY。
6. [x] 页面级 ERROR/EMPTY/FORBIDDEN 的恢复动作与 Figma 文案一致；模块级错误只能局部重试。

## 7. 异常码登记门禁

以下 code 已登记到 [wealth 异常码注册表](../../system/exception-code-registry.md)，实现必须使用登记语义：

| code | 触发 | 预期 |
|---|---|---|
| `ID_REQUEST_INVALID` | 参数非法 | 400 |
| `ID_NOT_FOUND` | 非 10 code/身份不存在 | 404 |
| `ID_SOURCE_EMPTY` | 日线无数据 | 200 + EMPTY |
| `ID_SOURCE_DELAYED` | 日线日期落后 | 200 + DELAYED |
| `ID_FACTOR_PARTIAL` | page-init 同日 factor 量额缺失，或 Kline 因子缺失 | 200 + PARTIAL |
| `ID_BASIC_DAILY_PARTIAL` | 同日 dailyBasic 缺行/缺字段 | page-init 基本行情模块 PARTIAL |
| `ID_BASIC_BREADTH_PARTIAL` | A 股成分同日既无有效 daily pct 也无停牌证据 | page-init 基本行情模块 PARTIAL；B 股排除/停牌不触发 |
| `ID_WEIGHT_EMPTY` | 无权重批次 | weights EMPTY |
| `ID_WEIGHT_CONTRIBUTION_PARTIAL` | preClose 缺失，或 A 股既无有效 daily pct 也无停牌证据 | weights PARTIAL；停牌贡献 0 不触发 |
| `ID_QUERY_FAILED` | 查询异常 | 对应模块 error |
| `IM_SOURCE_NOT_READY` | Lake 日期缺失 | minutes DELAYED |
| `IM_SOURCE_CONTRACT_INVALID` | Parquet 合同错误 | minutes ERROR |
| `IM_QUERY_FAILED` | DuckDB/IO 错误 | minutes ERROR |

1. [x] code、module、severity、frontendAction 已登记。
2. [x] 旧股票分钟 `SM_*` 不被复用成指数分钟新语义。
3. [x] 401/403 沿用认证层语义，不自造业务 EMPTY。

## 8. 前端门禁

### 8.1 路由与导航

1. [x] `buildIndexDetailPath()` trim+upper+encode。
2. [x] router 同时支持 `/wealth/market/index/:code`，不影响 stock route。
3. [x] `MajorIndexPanel` 只上报码，不自行拼路径。
4. [x] 10 卡顺序和数据仍由 major-indices API 决定。

### 8.2 Loaded 页面

1. [x] 复用 `TopMarketBar`。
2. [x] 不存在“前复权”文本、按钮或 hidden action。
3. [x] 默认 Basic tab，三个 tab 都有 keyboard/ARIA tab 语义。
4. [x] 权重表头固定、视窗恰好显示 10 行、内部纵向滚动、虚拟化渲染完整批次，并展示估算说明。
5. [x] 技术结论和九转显示 `--`，不引用 Figma 示例文案。
6. [x] `+交易计划` 只绑定用户点击 toast，不被 effect/数据状态调用。
7. [x] 基本行情严格按顺序展示 15 项；缺值显示 `--`，不存在“成交状态”和“较昨日”。
8. [x] 上涨/平盘/下跌使用 API 聚合值；前端不遍历权重行重算，不把 missing 算作平盘。
9. [x] Loading 使用图表/右栏骨架，不只显示居中文案；不得直接复制股票详情当前简化 loading DOM。
10. [x] Empty 右栏保留身份和三个 Tab，主价格、涨跌及 15 个指标值均为 `--`。
11. [x] Error/Forbidden 使用全宽主面板但不删除外层页面壳；Partial 不清空图表或可用字段。
12. [x] Error/Partial/Forbidden 分别使用 `--cs-color-danger-system`、`--cs-color-warning`、`--cs-color-info`，测试断言未使用 `--cs-color-market-up/down`。

### 8.3 图表共享

1. [x] 没有复制 `StockChartWorkspace.tsx` 主实现。
2. [x] shared chart 不含 stock/index 业务文案。
3. [x] null 指标被过滤或绘制断点，不转 0。
4. [x] M2 历史基线的股票详情 90 根窗口、crosshair、tooltip、MA/BOLL、四面板回归通过；当前 120 根/缩放已通过独立[共享图表缩放门禁](../../system/detail-chart-zoom-m2-coding-gate-v1.md)并由 `61a5adea` 提交，不改写本条历史验收事实。
5. [x] 上证指数趋势短/长期四轨与每日竖线可按日期对齐，无未来数据；每个交易日都有竖线，颜色切换点连续；短期红/绿、长期粉/蓝四种组合均有测试。
6. [x] 其余 9 个指数不渲染趋势入口、不调用趋势接口。

### 8.4 周期与环境

1. [x] prod：日线 active；分时/周/月/所有分钟 disabled。
2. [x] local flag false：同 prod。
3. [x] local flag true + Lake ready：仅七个分钟 frequency enabled。
4. [x] 权重 tab 不随分钟切换成盘中贡献。

### 8.5 Figma 结构与像素门禁

1. [x] 页面为 `1600×1200`：TopMarketBar 56px、面包屑 42px、工具栏 44px、主内容区 1058px。
2. [x] Loaded/Loading/Empty/Partial 双栏保持：左 `1193.1953125×1038`、间距 10px、右 `376.796875×1038`、主内容内边距 10px。
3. [x] TopMarketBar 使用共享组件，不复制第二套；右栏三个 Tab 共享稳定 Header/Tabs 骨架。
4. [x] 页面骨架、状态内容、按钮组、指标卡片和列表使用 Auto Layout/CSS Grid/Flex；不得用大量补偿坐标模拟布局。
5. [x] K 线、趋势通道、九转位置、指标、坐标轴、Tooltip、十字线保留图表坐标定位，状态切换不得使其位移。
6. [x] 普通 UI 相对 Figma 基线偏差不超过 2px，无新增换行、裁剪、重叠或溢出。
7. [x] Partial 提示内部为流式布局；若以右栏覆盖层定位，必须只有一个稳定锚点，不能改变 Info Rail 组件实例结构。
8. [x] `425:190` 是过期概述，不进入实现或测试；Basic 字段金标只能来自 `414:446`、`425:219` 和三件套 15 项清单。

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
4. [x] 2026-08-12 复核上证最新页面日 `2026-08-11`、权重日 `2026-07-31`：官方源批次 2224 行，其中 Security 事实字段认定 A 股 2184 行、B 股 40 行。A 股 daily 原始计数为 up 648、flat 49、down 1485，另有 2 个精确日 `suspend_type='S'`；按冻结规则结果为 total/matched 2184、up 648、flat 51、down 1485、missing 0。B 股不计缺失，A 股权重不归一化。
5. [x] 1.2.0 最终查询已完成只读性能复验：10 指数各 5 轮 page-init P95 245.589ms、weights P95 267.319ms；最大权重响应 2184 行/275,543B，数据库内上证最终 SQL 约 19~22ms。

### 9.3 已完成：指数因子

1. [x] 10 code 均有 388 行，日期范围 2025-01-02 ~ 2026-08-10，无重复主键。
2. [x] 10 code 最新日均与 index daily 对齐到 2026-08-10。
3. [x] 每 code 至少覆盖默认 300 根；审计时 `000510.SH` 有 182 行 MA250 前缀空值，但该结果仅为 2026-08-11 快照，不进入代码规则。
4. [x] 最近 300 根 OHLC/昨收/涨跌/涨跌幅同日最大绝对差为 0。
5. [x] 发现 `399001.SZ`、`399006.SZ` 自 2026-07-06 起 26 日量额分叉；外部核对确认 factor 准确，基本行情与 Kline 量额统一取 factor，不做换算或 daily fallback。
6. [x] MA/BOLL/MACD/KDJ 除上述 MA250 快照空值外均满足最近 300 根覆盖；MA 合理历史不足按实际根数动态判断。
7. [x] 旧候选 factor/daily join 命中两侧主键；数据库内 P95：300 根 1.636ms、2000-limit 2.127ms，作为更复杂查询的保守参考。
8. [ ] 真实 2000 行响应体与 Web-host 端到端 P95：当前 factor 仅 388 行，待 API 落地且数据具备后验收。
9. [ ] 2024 技术因子同步完成后重跑 10 指数覆盖审计，并验证 MA null 分类随实际历史变化而变化。
10. [ ] factor-only 主查询 + MA 历史基数条件查询的完整 Kline 链路通过索引计划、300/2000 上限和 Web-host P95 验收。

### 9.4 M5-A 已完成：本地分钟

1. [x] Silver 七频率物理文件、schema、最新时间键和当前 UI 九个可用 code 通过只读审计。
2. [x] M5-B 准备：Definitions 已发现七频率 14 个 Gold 资产及全部 70 个 blocking checks。
3. [x] M5-B 准备：Orchestrator/Web Reader 七频率、23 列、参数键和版本由静态合同门禁锁定；`/minute-indicators` fixture 覆盖七频率、错误版本、重复时间键和 Gold 缺失隔离。
4. [x] M5-B 正式数据验收：正式 Gold 物理覆盖、Silver 时间键无重复且全量可对齐，默认 500 根 P95 通过；10000 参数上限受 5MB 优先门禁，正确拒绝与固定 5000 根正常分页共同构成最大响应门禁。
5. [x] `899050.BJ` 明确返回分钟模块 EMPTY，不 fallback。
6. [x] API 只读正式 Lake `/Volumes/datasource/data_lake`，不读旧 Lake，不读 staging。
7. [x] 七频率各 10 次、默认 500 根的正式 Silver 只读 P95 为 257–321ms；10000 根为 2,217,412 bytes，游标有效且低于 5MB。

M5-B 准备批次验证记录（2026-08-12）：42 项分钟相关测试、14 项子系统边界测试、Ruff、文档完整性和 diff 检查均通过。正式只读预检为 Silver 每频率 4,276 个分区、Gold technical 每频率 0 个分区，正确返回 `SOURCE_NOT_READY / IM_SOURCE_NOT_READY`；正式 Gold 性能仍未验收。

M5-B 正式数据验证记录（2026-08-13）：Definitions 为 14 assets/70 checks；Silver/Gold technical 七频率各 4,276 个分区，29,932 个全历史分区对零失败；Technical/state 共 59,864 个文件、10,147,176 行；630 个默认 500 根样本全部 READY，频率级 P95 295.855–324.620ms。代表性 7,862 根响应为 4,999,968 bytes，7,863 根触发 5MB 拒绝，因此最终工具必须验证 10000 正确拒绝与固定 5000 根 cursor，而不是要求 10000 根 DTO 必然成功返回。

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

1. [x] 所有 M1 查询只选所需列，不 `SELECT *`。
2. [x] 权重名称/行情补列使用集合 LEFT JOIN，无 N+1。
3. [x] M1 未修改趋势接口或新增十指数缓存。
4. [x] M1 当前实现链 P95 全部低于硬门禁，未调整 timeout；page-init 跨网络 P95 仍需在生产 Web-host 同拓扑复核 200ms 目标。

M1 实现后 50 样本跨网络服务链 P95：page-init 246.054ms、kline 300 211.169ms、kline 2000 上限实返 455~630 行 248.925ms、weights 271.337ms；最大 payload 分别为 1,653 B、162,606 B、337,689 B、276,419 B。page-init 通过 500ms 硬门禁但高于 200ms 目标；本机跨网络结果不替代生产 Web-host 同拓扑验收。真实 2000 行仍未具备物理数据，不得标成已验收。

## 11. 测试门禁

### 11.1 后端真实 API

1. [x] 真实 FastAPI route，禁止只 mock query/service。
2. [x] 10 code page-init 参数化测试。
3. [x] kline 字段、null、排序、limit、非法 adjustment 负向测试。
4. [x] 权重 2026-07-31、完整批次、排序、覆盖计数、不截断、公式、缺失、不归一化、不缩放。
5. [x] 既有 SSE endpoint 全回归；上证指数请求成功，其余 9 个指数前端断言零请求。
6. [x] auth、not-found、delayed、empty、partial、error。
7. [x] prod 分钟 route 不存在；local 临时真实 Parquet 可查询。

### 11.2 前端真实 API 展示

1. [x] 不使用 mock adapter 证明 ready。
2. [x] 10 卡导航和 router history。
3. [x] page loading/error/empty/partial/forbidden 分别对照 `498:516`、`501:761`、`499:579`、`502:1625`、`504:1009`。
4. [x] 三 tab、权重懒加载缓存、10 行虚拟滚动并可到达末行、技术空字段。
5. [x] prod/local 周期能力。
6. [x] 页面无“前复权”。
7. [x] 股票详情共享图表回归。
8. [x] Loading 无上一标的详情值；Empty 的指数头部价格/涨跌与 15 项指标均使用 `--` 占位。
9. [x] Partial 以两组不同缺失组合证明提示与占位由真实响应驱动，不写死 Figma 示例字段。
10. [x] Error/FORBIDDEN 外层骨架尺寸不变，MainContent 为全宽面板；恢复按钮执行正确动作。
11. [x] 状态颜色 token 与行情颜色 token 语义分离。

### 11.3 命令

```bash
pytest -q tests/web/test_wealth_index_detail_api.py tests/test_quote_trend_channel_query_service.py
cd wealth && npm run typecheck
cd wealth && npm run test
cd wealth && npm run build
```

## 12. 签字清单

### 后端

1. [x] 数据源和查询已按 M1 实现并通过生产只读复验。
2. [x] DTO、状态、异常已由真实路由测试冻结。
3. [x] 贡献公式已实现；趋势复用边界保持既有 SSE-only 合同不变。

### 前端

1. [x] Figma Loaded 结构已实现并通过 1600×1200 浏览器量测。
2. [x] shared chart 重构范围可控。
3. [x] 三 tab、生产日线周期、异常态与 M5-A 本地七频率已落地；分钟切换不改变日频右栏和权重语义。
4. [x] 五态逐画板结构、文案、动作、颜色与数据保留规则已落地并通过截图验收。
5. [ ] M5-B 真实 `/minute-indicators` provider、bars-only PARTIAL、Mock provider/标识/测试清零和本地七频率浏览器回归通过。

### 架构/产品

1. [x] 需求未扩散到技术结论、九转或交易流程。
2. [x] 技术口径已逐项确认：SSE-only 趋势、逐日四轨绘制与每日竖线、A 股完整权重滚动、基本行情 15 项、A 股成分涨跌与停牌解析规则。
3. [x] 右侧基本行情最终展示组合已完成产品选择并同步 Figma。
4. [x] 已由用户明确同意并完成 M1 数据与契约开发。

## 13. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1.19 | 2026-08-13 | 标记 M5-B 正式 Gold 全历史和性能门禁通过；冻结 10000/5MB 正确拒绝 + 5000 正常分页验收，并增加真实 provider、bars-only PARTIAL 和 Mock 清零前端门禁 | Codex |
| v1.18 | 2026-08-12 | M3 对账：共享图表缩放已提交为 `61a5adea`，保留原指数 M2 的 90 根历史证据并登记当前 120 根合同 | Codex |
| v1.17 | 2026-08-12 | 链接独立共享图表缩放门禁，保留 M2 的 90 根历史验收事实，后续 120 根与缩放不混入已完成里程碑 | Codex |
| v1.16 | 2026-08-12 | 将 M5-B Definitions 70 checks 标记为已完成，并拆分正式 Gold 物理覆盖/对齐/性能待验项；登记跨边界合同、七频率异常 fixture 与只读验收入口门禁 | Codex |
| v1.15 | 2026-08-12 | 完成 A 股集合与停牌解析编码门禁：查询、异常、合同测试、83 项后端相关、108 项 Wealth、生产只读性能和真实页面 READY 验收全部通过 | Codex |
| v1.14 | 2026-08-12 | 冻结 A 股成分集合与停牌解析门禁：B 股不进入 rows/coverage/missing；daily 优先，缺 daily 且有精确日停牌证据时按 flat、贡献 0；补生产只读样本、SQL 和负向测试要求，DTO 提升至 1.2.0 | Codex |
| v1.13 | 2026-08-11 | 完成 M5-A 门禁：Reader/API/本地路由、七频率、Mock v0 标识、缓存与旧响应隔离、北证50局部空态、Tooltip、正式 Silver 性能与 1600×1200 无溢出验收通过；Gold 门禁继续保留 | Codex |
| v1.12 | 2026-08-11 | 冻结 M5-A local/prod 路由、双接口、cursor/limit/5MB、正式 Silver、北证50 EMPTY 与可见开发态 Mock 边界；Gold/70 checks/对齐保留 M5-B | Codex |
| v1.11 | 2026-08-11 | 完成 M4 门禁：五态、404、Delayed、页面/模块状态分层、整页/局部重试、请求中止防串标、动态 Partial 文案、系统状态色与 1600×1200 逐状态截图通过；100 项 Wealth 与 82 项后端相关回归通过，M5 分钟项保持未勾选 | Codex |
| v1.10 | 2026-08-11 | 完成 M3 Loaded 门禁：真实指数路由、10 卡导航、三 Tab、15 项基本行情、权重懒加载缓存/十行虚拟滚动、SSE-only 逐日四色趋势和技术空字段通过；M4/M5 项保持未勾选 | Codex |
| v1.9 | 2026-08-11 | 完成 M2 shared chart：通用四面板生命周期、90 根窗口、同步 crosshair/tooltip、MA/BOLL 可选线、null-safe series 与可选 primitive 接口落地；股票 adapter、全量 Wealth 测试、生产构建和 1600×1200 浏览器尺寸对账通过；趋势与指数 adapter 仍留在 M3 | Codex |
| v1.8 | 2026-08-11 | 回填 M1 实施结果：三条真实路由、严格非法参数、10 code、动态 MA、完整权重、源字段负例、旧契约回归和生产只读 P95 条目通过；保留前端/M5/真实 2000 行未通过项 | Codex |
| v1.7 | 2026-08-11 | 外部核对确认 factor 量额准确；page-init/Kline 量额统一取 factor，增加 daily fallback 负向门禁和 factor-only 性能复验；DTO 提升为 1.1.0 | Codex |
| v1.6 | 2026-08-11 | 修正 MA null 门禁：删除 A500/固定日期特例；增加实际历史根数、回填重分类、负向测试与完整链路性能复验；DTO 提升为 1.0.1 | Codex |
| v1.5 | 2026-08-11 | 完成 M0 数据/契约门禁：登记异常码、冻结 DTO 1.0.0、记录 10 指数 factor 覆盖/索引/P95、深市量额分叉、当时 A500 MA250 空值与真实 2000 行性能待验项；量额最终来源已由 v1.7 修订 | Codex |
| v1.4 | 2026-08-11 | 登记最新 Loaded/Components/五态节点台账；补五态响应、状态优先级、Auto Layout/图表定位、系统颜色和逐画板像素/测试门禁；排除 Figma 旧概述文案 | Codex |
| v1.3 | 2026-08-11 | 冻结逐日趋势判色/每日竖线、15 项基本行情、成分涨跌聚合与缺失规则；移除成交状态/较昨日门禁并补生产证据 | Codex |
| v1.2 | 2026-08-11 | 趋势门禁改为仅上证指数直接消费既有 API；删除十指数适配、中轴和十指数缓存门禁；补双通道绘制/配色、成交状态与字段选择门禁 | Codex |
| v1.1 | 2026-08-11 | 权重门禁改为完整批次、10 行虚拟滚动与不截断；确认 09 状态页并补异常恢复要求 | Codex |
| v1 | 2026-08-10 | 首版编码门禁草案，已区分已拍板产品口径与未通过实施门禁 | Codex |
