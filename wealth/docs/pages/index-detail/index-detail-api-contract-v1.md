# 指数详情页正式 API / DTO 合同 v1

> 合同版本：`1.3.1`
>
> 冻结日期：2026-08-17
>
> 状态：M1～M5-B 与 S7/M5 已实现；S7/M5 仅升级 page-init 九转 capability，不扩展股票详情或主要指数卡片 DTO。

## 1. 合同边界

本合同冻结三个正式日线接口及指数详情页的环境能力声明：

1. `GET /api/v1/wealth/market/index-detail/page-init`
2. `GET /api/v1/wealth/market/index-detail/kline`
3. `GET /api/v1/wealth/market/index-detail/weights`

趋势通道继续直接消费既有 `GET /api/v1/quote/detail/trend-channel`，不在本合同复制。九转数据继续由独立的日线/分钟九转接口提供；本合同只在 page-init 声明当前环境允许请求的九转周期，不复制 marker payload。技术结论和本地指数分钟仍由各自独立合同治理，不向本合同预留 `any`、占位 payload 或未定义字段。

## 2. 全局序列化规则

1. 成功响应使用 lowerCamelCase；现有全局错误响应中的 `request_id` 保持 snake_case。
2. 所有日期为 `YYYY-MM-DD`，时间为带时区 ISO-8601。
3. 数值使用 JSON number；缺失值使用 `null`，禁止 `NaN/Infinity/"--"/0` 代替缺失。
4. 数组字段永远存在；没有元素时返回 `[]`，不返回 `null`。
5. 本文列出的响应字段全部 required；nullable 不等于 optional。
6. `debugInfo` 始终存在：`debug=0` 时为 `null`，`debug=1` 时为完整对象。
7. Pydantic DTO 使用 `ConfigDict(extra="forbid")`；TypeScript 不使用 index signature 或 `unknown` 扩展响应。
8. 数据库字段名只允许出现在 query/mapper，不进入 HTTP DTO。

## 3. 共用类型

```ts
type IndexDetailDataStatusValue = "READY" | "DELAYED" | "PARTIAL" | "EMPTY";
type IndexDetailDirection = "UP" | "DOWN" | "FLAT" | "UNKNOWN";
type IndexDetailSeverity = "info" | "warn" | "error";

interface IndexDetailPageContextDto {
  market: "CN_A";
  tradeDate: string;
  prevTradeDate: string | null;
  isTradingDay: boolean;
  sessionStatus: "PRE_OPEN" | "TRADING" | "BREAK" | "CLOSED";
  timezone: "Asia/Shanghai";
  generatedAt: string;
  source: "explicit" | "default";
}

interface IndexDetailDataStatusDto {
  status: IndexDetailDataStatusValue;
  expectedTradeDate: string;
  observedTradeDate: string | null;
}
```

`ERROR` 和 `FORBIDDEN` 不伪装成 HTTP 200 的 `dataStatus`：

1. Loading 是前端请求阶段。
2. 401/403 由认证层处理。
3. 404/400/500 使用错误响应。
4. `dataStatus` 只表达成功响应内的数据就绪程度。

状态优先级：`EMPTY > PARTIAL > DELAYED > READY`。HTTP 错误优先于所有成功状态。

### 3.1 debug 合同

```ts
type IndexDetailDebugModule =
  | "pageInit"
  | "quote"
  | "dailyBasic"
  | "breadth"
  | "kline"
  | "weights";

type IndexDetailExceptionModule =
  | "indexDetail"
  | "indexDetailPageInit"
  | "indexDetailKline"
  | "indexDetailWeights";

type IndexDetailExceptionCode =
  | "ID_REQUEST_INVALID"
  | "ID_NOT_FOUND"
  | "ID_SOURCE_EMPTY"
  | "ID_SOURCE_DELAYED"
  | "ID_FACTOR_PARTIAL"
  | "ID_BASIC_DAILY_PARTIAL"
  | "ID_BASIC_BREADTH_PARTIAL"
  | "ID_WEIGHT_EMPTY"
  | "ID_WEIGHT_CONTRIBUTION_PARTIAL"
  | "ID_QUERY_FAILED";

interface IndexDetailModuleDebugDto {
  module: IndexDetailDebugModule;
  status: IndexDetailDataStatusValue | "ERROR";
  expectedTradeDate: string;
  observedTradeDate: string | null;
  rowCount: number | null;
  missingCount: number | null;
}

interface IndexDetailExceptionDto {
  module: IndexDetailExceptionModule;
  code: IndexDetailExceptionCode;
  severity: IndexDetailSeverity;
  message: string;
}

interface IndexDetailDebugInfoDto {
  modules: IndexDetailModuleDebugDto[];
  exceptions: IndexDetailExceptionDto[];
}
```

debug 信息不得返回 SQL、Lake 绝对路径、环境变量、连接信息、凭据或 Python exception repr。

## 4. `GET /page-init`

### 4.1 请求

| 参数 | 类型 | required | 冻结规则 |
|---|---|---:|---|
| `tsCode` | string | 是 | trim + upper；必须属于 `majorIndices/CN_A` 10 code |
| `tradeDate` | ISO date | 否 | 隐藏锚点；页面不提供日期选择器 |
| `debug` | 0 或 1 | 否 | 默认 0 |

日期、debug 或 code 解析失败统一返回 `ID_REQUEST_INVALID`；code 语法合法但不属于 10 code 返回 `ID_NOT_FOUND`。

### 4.2 响应

```ts
interface IndexDetailIdentityDto {
  tsCode: string;
  name: string;
  market: string | null;
  category: string | null;
  publisher: string | null;
  tags: string[];
}

interface IndexDetailQuoteDto {
  tradeDate: string;
  point: number | null;
  change: number | null;
  changePct: number | null;
  direction: IndexDetailDirection;
  open: number | null;
  high: number | null;
  low: number | null;
  preClose: number | null;
  vol: number | null;
  amount: number | null;
}

interface IndexDetailDailyBasicDto {
  tradeDate: string;
  pe: number | null;
  peTtm: number | null;
  pb: number | null;
  turnoverRate: number | null;
  floatMv: number | null;
  totalMv: number | null;
}

interface IndexDetailConstituentBreadthDto {
  tradeDate: string;
  weightTradeDate: string;
  upCount: number;
  flatCount: number;
  downCount: number;
  totalConstituentCount: number;
  matchedCount: number;
  missingCount: number;
  dataStatus: IndexDetailDataStatusDto;
}

type IndexDetailPeriod = "day" | "m1" | "m5" | "m15" | "m30" | "m60" | "m90" | "m120";
type IndexDetailMinuteFrequency = 1 | 5 | 15 | 30 | 60 | 90 | 120;
type IndexDetailNineTurnPeriod = "day" | "5" | "15" | "30" | "60" | "90" | "120";

interface IndexDetailPageInitResponseDto {
  pageContext: IndexDetailPageContextDto;
  asOfTradeDate: string | null;
  index: IndexDetailIdentityDto;
  quote: IndexDetailQuoteDto | null;
  dailyBasic: IndexDetailDailyBasicDto | null;
  constituentBreadth: IndexDetailConstituentBreadthDto | null;
  chartDefaults: {
    defaultPeriod: "day";
    availablePeriods: IndexDetailPeriod[];
    availableMainOverlays: Array<"MA" | "BOLL" | "TREND_CHANNEL">;
    availableIndicatorTabs: Array<"VOL" | "amount" | "MA" | "MACD" | "KDJ" | "BOLL">;
  };
  capabilities: {
    supportsTimeShare: false;
    supportsWeeklyMonthly: false;
    supportsMinute: boolean;
    minuteFrequencies: IndexDetailMinuteFrequency[];
    supportsTrendChannel: boolean;
    supportsNineTurn: true;
    nineTurnPeriods: IndexDetailNineTurnPeriod[];
    supportsTechnicalConclusion: false;
    supportsTradePlanEntry: true;
  };
  dataStatus: IndexDetailDataStatusDto;
  debugInfo: IndexDetailDebugInfoDto | null;
}
```

### 4.3 状态与字段规则

1. `pageContext.tradeDate` 是期望完成交易日。
2. `asOfTradeDate` 是 `index_daily_serving.trade_date <= expectedTradeDate` 的最新观测日。
3. quote 的日期与价格取 `index_daily_serving`：`close -> point`、`change_amount -> change`、`pct_chg -> changePct`，其余价格字段同名；`vol/amount` 唯一取同 code、`tradeDate=asOfTradeDate` 的 `index_factor_pro`。direction 按 changePct 正/负/零判定，null 为 UNKNOWN。
4. 无 quote：`asOfTradeDate=null`、quote/dailyBasic/breadth 为 null、页面 `EMPTY`。
5. `dailyBasic` 只查 `tradeDate=asOfTradeDate` 的 `pe/pe_ttm/pb/turnover_rate/float_mv/total_mv`；无同日行时为 null，不向前取旧值。
6. breadth 先取 `max(weight.trade_date) <= asOfTradeDate` 的源权重批次，再只保留能在 `security_serving` 识别为 A 股的成分：`security_type=EQUITY`、`exchange in (SSE,SZSE,BSE)`、`curr_type=CNY`。源批次中的 B 股不属于页面成分范围，不进入 `totalConstituentCount/missingCount`，也不触发 PARTIAL。
7. A 股成分的涨跌分类按以下优先级解析：同日 `equity_daily_bar.pct_chg` 非空时按 `> 0 / = 0 / < 0` 分类；同日行情为空但 `equity_suspend_d` 存在 `suspend_type=S` 时按 `pct_chg=0` 计入 FLAT；两者都不存在时才计入 missing。日线有值时不得被停牌记录覆盖。
8. `matchedCount` 表示已完成涨跌分类的 A 股成分数，包括有同日涨跌幅的成员和已确认停牌并按 FLAT 处理的成员。`upCount + flatCount + downCount = matchedCount`；`matchedCount + missingCount = totalConstituentCount`。
9. 无权重批次时 breadth 为 null；不是三项 0。
10. 同日 factor 行或其 `vol/amount` 缺失、dailyBasic 缺行/缺字段、breadth 为 null 或真实 A 股 `missingCount>0` 时 page-init 为 PARTIAL，并在 debug 分别登记 `ID_FACTOR_PARTIAL`、`ID_BASIC_DAILY_PARTIAL`、`ID_WEIGHT_EMPTY` 或 `ID_BASIC_BREADTH_PARTIAL`。B 股被排除和已确认停牌都不是数据缺失。
11. 无 partial 原因且 observed 早于 expected 时为 DELAYED。
12. `supportsTrendChannel=true` 只允许 `000001.SH`；其余 9 个 code 为 false 且 overlays 不含 `TREND_CHANNEL`。
13. 生产和 local flag=false：periods 只有 `day`，minuteFrequencies 为空。
14. `supportsTradePlanEntry=true` 只表示顶部入口存在；技术结论和任何数据 effect 都不得触发交易动作。
15. `supportsNineTurn=true` 只表示指数日线九转接口已经部署，不表示当前窗口一定有 1～9 marker。
16. 生产、local/dev 分钟九转能力未就绪时，`nineTurnPeriods=["day"]`；local/dev 且指数分钟九转 capability 与分钟 router 同时就绪时，返回 `day,5,15,30,60,90,120`。指数 1 分钟永不进入列表。
17. page-init 与 App router 必须消费同一个指数分钟九转 capability resolver；页面只能请求 `nineTurnPeriods` 中的周期，禁止以 K 线周期列表推导九转能力。

## 5. `GET /kline`

### 5.1 请求

| 参数 | 类型 | required | 默认/规则 |
|---|---|---:|---|
| `tsCode` | string | 是 | 同 page-init |
| `period` | `day` | 否 | 默认 day；其它值拒绝 |
| `startDate` | ISO date | 否 | 不得晚于 endDate |
| `endDate` | ISO date | 否 | 页面传 asOfTradeDate |
| `limit` | integer | 否 | 默认 300，范围 1..2000 |
| `debug` | 0 或 1 | 否 | 默认 0 |

请求不声明也不接受 `adjustment`。FastAPI 参数进入业务前必须统一映射非法输入为 `ID_REQUEST_INVALID`，不能让同一语义随机落为全局 `validation_error`。

### 5.2 响应

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
    ma: {
      ma5: number | null;
      ma10: number | null;
      ma20: number | null;
      ma30: number | null;
      ma60: number | null;
      ma90: number | null;
      ma250: number | null;
    };
    boll: {
      upper: number | null;
      middle: number | null;
      lower: number | null;
    };
    macd: {
      dif: number | null;
      dea: number | null;
      macd: number | null;
    };
    kdj: {
      k: number | null;
      d: number | null;
      j: number | null;
    };
  };
}

interface IndexDetailKlineResponseDto {
  pageContext: IndexDetailPageContextDto;
  indexRef: {
    tsCode: string;
    name: string | null;
  };
  period: "day";
  bars: IndexKlineBarDto[];
  meta: {
    count: number;
    limit: number;
    startDate: string | null;
    endDate: string | null;
  };
  dataStatus: IndexDetailDataStatusDto;
  debugInfo: IndexDetailDebugInfoDto | null;
}
```

### 5.3 唯一字段来源

生产审计发现 factor 与 daily 的深市量额从 2026-07-06 起分叉；产品方完成外部数据源核对后确认 factor 准确，故冻结为：

| DTO | 来源 |
|---|---|
| 日期、OHLC、昨收、涨跌、涨跌幅 | `IndexFactorPro` 同名字段；`pct_change -> changePct` |
| `vol/amount` | `IndexFactorPro.vol/amount` |
| MA | `ma_bfq_5/10/20/30/60/90/250` |
| BOLL | `boll_upper_bfq/boll_mid_bfq/boll_lower_bfq` |
| MACD | `macd_dif_bfq/macd_dea_bfq/macd_bfq` |
| KDJ | `kdj_k_bfq/kdj_d_bfq/kdj_bfq` |
| amplitude | `(high-low)/preClose*100`；缺输入或昨收为 0 时 null |

Kline 的价格、量额与技术指标均来自同一 `IndexFactorPro` 行。禁止倍率修正，禁止从 `IndexDailyServing.vol/amount` 读取或 fallback。factor 行存在但 `vol/amount` 缺失时，对应字段为 null 且 K 线 PARTIAL。

### 5.4 排序、null 与状态

1. 查询按 `trade_date DESC LIMIT`，返回前反转为 ASC。
2. `meta.count=bars.length`，`meta.limit` 是归一化后的请求上限。
3. `meta.startDate` 是归一化请求下界；`meta.endDate` 是实际查询上界（显式 endDate，否则 pageContext.tradeDate），不是最后一根 bar 日期。
4. 不返回 MA15/MA120，不在请求链临时计算技术指标。
5. MA 不设指数或日期特例。`maN` 的源值非 null 时原样返回；为 null 时保持 null，图表断点，不补 0、不向前填充，也不在请求链临时重算。
6. 只有同一 code 截至该 bar 的实际有效历史 K 线根数小于 N 时，`maN=null` 才属于合理的历史不足；判断不得使用当前请求 `limit`、前端可见窗口、固定 code、固定日期或当前表起点代替真实历史。
7. 实际有效历史已达到 N 根但 `maN` 仍为 null，或其它预期技术因子缺失时，返回 PARTIAL 并登记 `ID_FACTOR_PARTIAL`。接口仍返回 null，不制造推算值。
8. factor 最新日落后，或可绘制 bar 的 factor `vol/amount` 缺失，同样返回 PARTIAL 并登记 `ID_FACTOR_PARTIAL`。
9. factor 完全无行返回 EMPTY；SQL/映射失败返回 HTTP error，不返回成功态 ERROR。

## 6. `GET /weights`

### 6.1 请求

| 参数 | 类型 | required | 规则 |
|---|---|---:|---|
| `tsCode` | string | 是 | 同 page-init |
| `tradeDate` | ISO date | 否 | 隐藏锚点 |
| `debug` | 0 或 1 | 否 | 默认 0 |

不接受 `limit/offset/sort/weightDate`；服务必须返回选定源权重批次中的完整 A 股子集。

### 6.2 响应

```ts
interface IndexDetailWeightRowDto {
  conCode: string;
  name: string | null;
  weight: number;
  changePct: number | null;
  contributionPoint: number | null;
  direction: IndexDetailDirection;
}

interface IndexDetailWeightsResponseDto {
  indexRef: {
    tsCode: string;
    name: string | null;
  };
  contributionTradeDate: string;
  weightTradeDate: string | null;
  isEstimated: true;
  rows: IndexDetailWeightRowDto[];
  coverage: {
    totalCount: number;
    returnedCount: number;
    contributionAvailableCount: number;
    contributionMissingCount: number;
    isTruncated: false;
  };
  dataStatus: IndexDetailDataStatusDto;
  note: "基于最新月度权重估算，非指数公司官方归因";
  debugInfo: IndexDetailDebugInfoDto | null;
}
```

### 6.3 日期、完整性与贡献

1. `contributionTradeDate` 等于 page-init 同口径 `asOfTradeDate`；完全没有指数日线时取 expected date、rows 为空、状态 EMPTY。
2. `weightTradeDate=max(index_weight.trade_date) <= contributionTradeDate`，当前生产验收基线是 2026-07-31，但代码不硬编码。
3. A 股范围与 breadth 完全一致：`security_type=EQUITY`、`exchange in (SSE,SZSE,BSE)`、`curr_type=CNY`。B 股不返回，不计入 coverage；不得使用代码前缀判断 A/B 股。
4. A 股子集出现 null weight 或重复成分时返回错误，禁止过滤异常行后返回半批次。
5. rows 按四位小数的 `contributionPoint DESC NULLS LAST, weight DESC, conCode ASC` 返回：正贡献在前，其后依次为 0、负贡献和 `null`；不得按绝对值排序。`rows.length=totalCount=returnedCount`、`isTruncated=false`。
6. `contributionAvailableCount + contributionMissingCount = totalCount`。
7. 名称缺失保留行，以 code 展示；正常 A 股集合由 Security 身份确定，因此名称为空只属于字段缺失，不改变 A 股身份。
8. 贡献公式：`indexPreClose * weight/100 * constituentPctChg/100`。
9. 内部使用 `Decimal(str(value))`，不归一化权重、不按指数实际涨跌点缩放。排除 B 股后仍保留 A 股官方原始 weight，不把 A 股子集重新归一到 100%。
10. 输出值按 `0.0001 + ROUND_HALF_UP` 舍入后转 JSON number；UI 独立格式化 2 位和正负号。
11. `changePct` 优先取成分同日行情；同日行情为空但同日 `suspend_type=S` 时返回 `0`，`direction=FLAT`、`contributionPoint=0`，并计入 contributionAvailableCount。行情和停牌依据都不存在时才返回 null/UNKNOWN，贡献为 null。
12. 真实 A 股贡献缺失大于 0 时状态 PARTIAL，并登记 `ID_WEIGHT_CONTRIBUTION_PARTIAL`；B 股排除和已确认停牌不得触发该异常。

## 7. 错误响应

沿用当前 `WebAppError` 形状：

```ts
interface IndexDetailErrorResponseDto {
  code:
    | "ID_REQUEST_INVALID"
    | "ID_NOT_FOUND"
    | "ID_QUERY_FAILED"
    | "unauthorized"
    | "forbidden";
  message: string;
  request_id: string | null;
}
```

正式三个日线接口只产生上述 `ID_*` 和认证层 code。`IM_*` 只由已启用的 local/dev 独立分钟合同产生，仍不得出现在 page-init/kline/weights。

| 场景 | HTTP | code |
|---|---:|---|
| 参数非法 | 400 | `ID_REQUEST_INVALID` |
| code 不属于 10 指数或身份不存在 | 404 | `ID_NOT_FOUND` |
| 配置缺失/非法、SQL 或映射失败 | 500 | `ID_QUERY_FAILED` |
| 未登录/无权限 | 401/403 | 沿用认证层 `unauthorized/forbidden` |

`ID_SOURCE_EMPTY` 等状态型异常只在 `debugInfo.exceptions` 和结构化日志出现；用户看到的是稳定空态/局部状态，不直接显示异常码。

## 8. 兼容与变更规则

1. v1 实现不得向股票详情、主要指数卡片或 Quote trend DTO 添加字段。
2. 新增 response 字段、修改 nullable/required、枚举值、来源或状态语义都需要提升合同版本并同步 LLD、M2 gate、后端 schema、前端类型和契约测试。
3. 技术结论、九转数据和分钟数据必须以独立合同扩展；page-init 只声明稳定的九转 capability 与周期列表，不能嵌入 marker 或临时对象。
4. API 测试必须断言 `extra="forbid"`、debug null/object、非法字段、null 保留、字段来源和旧 DTO 无漂移。

## 9. 版本记录

| 版本 | 日期 | 变更摘要 |
|---|---|---|
| `1.3.1` | 2026-08-17 | 权重股贡献列表改为按四位小数 `contributionPoint` 数值降序，缺失值置底；同贡献点按 `weight DESC, conCode ASC` 保持确定性；DTO 字段结构不变 |
| `1.3.0` | 2026-08-15 | S7/M5 升级指数 page-init 九转 capability：生产仅开放日线，local/dev 在同一 router capability 就绪时开放 5/15/30/60/90/120 分钟；指数 1 分钟永不开放，九转数据仍由独立接口提供 |
| `1.2.0` | 2026-08-12 | 成分范围统一收敛为 Security 事实字段识别的 A 股；B 股不进入 rows/coverage/missing；同日无行情但确认停牌的 A 股按 0%/FLAT 参与 breadth 与贡献；DTO 字段结构不变，提升版本以冻结语义变更 |
| `1.1.0` | 2026-08-11 | 外部数据源核对确认 factor 量额准确；page-init 与 Kline 的成交量、成交额统一取 `IndexFactorPro`，禁止 daily fallback；DTO 字段结构不变 |
| `1.0.1` | 2026-08-11 | 删除 A500/固定日期 warm-up 特例；MA null 改为依据同 code、同交易日实际有效历史根数动态判断，DTO 字段结构不变 |
| `1.0.0` | 2026-08-11 | 首次冻结 page-init/kline/weights 独立 DTO |
