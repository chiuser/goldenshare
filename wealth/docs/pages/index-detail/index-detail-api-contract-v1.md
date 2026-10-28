# 指数详情页正式 API / DTO 合同 v1

> 2026-10-28 P1：§10新增已确认的r4日线识别目标合同，尚未改变运行时。§1—9原有page-init/kline/weights及其`debugInfo`规则不在本次修改范围；r4使用独立普通/debug响应，不能套用§2第6条的`debugInfo`规则。正式r4实施与验收按[产品LLD](index-detail-top-bottom-recognition-low-level-design-v1.md)P2—P4推进。

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


## 10. r4日线顶底识别目标合同（P1已登记，运行时尚未迁移）

本节只扩展独立`xxm-signals`接口，不向page-init/kline/weights添加识别字段，不改变这三个接口的版本、错误码或debugInfo。当前产品代码仍是r2、响应包含根层历史等辅助字段；本节是管理员已确认的后续r4目标，P1只回写文档和独立样例。代码级顺序及完整校验见[LLD§3—5、§9](index-detail-top-bottom-recognition-low-level-design-v1.md)。

### 10.1 路由、环境与请求

```http
GET /api/v1/wealth/market/index-detail/xxm-signals
```

| 参数 | 必填 | 规则 |
|---|---:|---|
| tsCode | 是 | trim+upper后严格六位代码及SH/SZ/BJ后缀；仅000001.SH支持，其他合法标的404，格式非法400 |
| period | 否 | 缺省day，仅day合法 |
| startDate/endDate | 否 | 非空标准YYYY-MM-DD，开始不得晚于结束；仅筛响应窗口，不能作为算法/MACD重算起点 |
| limit | 否 | 缺省300，1..2000；指数页显式1000，不改变API默认值 |
| debug | 否 | 缺省或文本0为普通，文本1为debug；空、true、01、2及其他值400 |

未知参数、重复参数及非法空值均400 `XXM_REQUEST_INVALID`。普通客户端省略debug；没有算法选择、r2回退或另一个r4路径。

服务端最终Settings须**显式配置dev/local**才注册本接口；默认dev但未显式配置也不注册。生产、未知环境和缺配置均由原框架返回404，不进入源读取/计算；生产日线也无r4，debug=1不能绕过。不改变全局配置优先级、原鉴权或生产正常日线能力；本地日线不依赖分钟开关/Lake。日线来源仍为原IndexFactorPro收盘及DIF/DEA/MACD柱，只消费已完成根，不补值、不重算实际MACD。

### 10.2 普通与debug的完整字段

下列字段全部必有；nullable表示允许为null，实际没有值时必须显式返回null，不能省略字段。所有对象封闭字段集合，不接受额外字段；number仅有限int/float，拒bool、字符串数值、NaN和无穷，close/price严格大于0。日线time均YYYY-MM-DD；分钟同结构的时间规则见[分钟合同§8](index-detail-minutes-api-contract-v1.md#8-r4分钟顶底识别目标合同p1已登记运行时尚未迁移)。

| 对象 | 必有字段、类型与含义 |
|---|---|
| 普通根XxmResponseDto | tsCode:string固定000001.SH；period:day；algorithmVersion:string固定xxm-direction-v0.1-r4；specHash:string为正式MAIN_SPEC完整hash；source:XxmSourceDto；points:XxmPointDto[]；events:XxmEventDto[]；meta:XxmMetaDto；dataStatus:XxmDataStatusDto |
| source | kind固定daily_factor；startTime/computedThrough:time或null；initialHistoryIncomplete:boolean；indicatorVersion:int或null（日线null）。**没有inputId** |
| point | time；close:number>0；dif/dea/hist:number；ordinaryState:NONE/DULL/STRUCTURE；ordinaryDirection:TOP/BOTTOM/null |
| event | id:string非空；time；direction:TOP/BOTTOM；type:DULL/STRUCTURE/CANCEL/RESEARCH_HISTORICAL_WITHDRAWAL/STRUCTURE_DISAPPEARED |
| meta | count:int≥0；responseStart/responseEnd:time或null |
| dataStatus | status:READY/DELAYED/EMPTY；message:string或null；asOf:time或null |
| debug根XxmDebugResponseDto | **全部普通根字段**加必有非null的debug:XxmDebugDto；不是根层透传原内部模型 |
| debug | sourceInputId:string；points:DebugPoint[]；events:DebugEvent[]；topHistories:TopHistory[]；bottomHistories:BottomHistory[]；rearmRecords:RearmRecord[] |
| DebugPoint | time；activeReference:Reference或null；pendingTopHistoryId/pendingBottomHistoryId/pendingRearmId:string或null |
| DebugEvent | id；route:activation/dif_turn/dif_return/color_flip/dif_break/dif_break_on_flip/historical_price_break/reactivation；fromState:NONE/DULL/STRUCTURE；eventReference:Reference或null；relatedTopHistoryId/relatedBottomHistoryId/relatedRearmId:string或null |
| Reference | startTime/endTime:time；price:number>0；dif:number。历史参照时间不得晚于相应当前段 |
| TopHistory | id；confirmedAt；confirmationRoute:dif_turn/color_flip；pricePeak:number>0；pricePeakAt；originalReference:Reference；status:PENDING/ENDED；endedAt:time或null；endReason:下述枚举或null；observedThrough:time；ageBars:int≥0 |
| BottomHistory | id；structureEventId；confirmedAt；confirmationRoute:dif_turn/color_flip；originSegmentStart；leftOriginAt:time或null；priceLow:number>0；priceLowAt；originalReference:Reference；status:PENDING/ENDED；endedAt:time或null；endReason:下述枚举或null；observedThrough；ageBars:int≥0 |
| RearmRecord | id；direction固定BOTTOM；bottomHistoryId/structureEventId:string；structureConfirmedAt；structureRoute固定dif_turn；segmentStart；nearestPriceGate:number>0；reference:Reference；disappearedAt/observedThrough:time；status:WAITING/REACTIVATED/INVALIDATED/SEGMENT_ENDED；endedAt:time或null；endReason:下述枚举或null |

未另注明的id为非空string、日期为本周期time。历史/等待结束原因的完整集合：

- TopHistory：original_reference_break/new_top_DULL/new_top_STRUCTURE/historical_price_break。
- BottomHistory：original_reference_break/new_bottom_DULL/new_bottom_STRUCTURE/historical_price_break/structure_disappeared。
- RearmRecord：price_requalified/reference_dif_break/color_flip；**不接受zero**。WAITING时endedAt/endReason均null，其他状态按上述原因对应；PENDING历史同样没有结束值，ENDED必须有结束时间及原因。

普通响应没有debug键、sourceInputId、参照、route、历史、等待或离线decision；不能用debug:null占位。DIF/DEA/柱仍为正常指标原值，event.id用于去重。RESEARCH_HISTORICAL_WITHDRAWAL仍是正常可见的“结构消失”，不得因枚举含RESEARCH过滤。普通悬停仅状态/当根事件/发生时间；debug可展示实际参照、编号和原历史，不能另跑算法猜解释。

### 10.3 数据、关联及身份校验

1. points按time升序唯一，events保持真实发生顺序；meta.count及首末精确对应points，event.time在响应points内。source.startTime可早于显示窗口，computedThrough和dataStatus.asOf一致，不能带未来值。
2. ordinaryState为NONE则direction为null，DULL/STRUCTURE则为TOP或BOTTOM。内部完整状态/参照/历史/等待先校验，再投影普通字段；普通不显示不等于内部不检查。
3. debug.points.time与普通points逐一相同，debug.events.id与普通events逐一相同，全部编号及双向历史/等待关联必须存在、唯一且日期一致。原结构可以在可见窗口之前形成，不得误作悬挂；截至时点之后的确认和结束不能泄露。
4. 已钝化同根B→A只改变当根活动参照；原DULL事件及历史的原参照不回写。debug保留这个真实区别，不要求旧事件参照等于最新活动参照。
5. READY按实际完成前缀返回；DELAYED保留真实可用结果并说明截止，不补最新根、不挪标签。EMPTY时points/events为空、count0、首末及源起止/asOf为null，debug数组为空，sourceInputId仍为原空源sha256(b'empty')身份字符串，不虚构历史或用请求日补日期。
6. algorithmVersion固定上述r4版本，specHash须与同次构建的完整MAIN_SPEC精确相等，不只验64位格式。P1样例hash是显式必填参数，无默认r2值；P2固定Spec后统一生成并填入各消费者，业务预期不由程序重算。这里的数据hash不是运行时源码SHA保护。

### 10.4 返回、预算、错误及消费者

query目标签名为`build(session, *, period, start_date, end_date, limit, debug=False, now=None) -> bytes`。同源内部计算/cache可被两种模式复用；分别新建公开模型，不能原地删debug字段或把普通投影存回完整内部缓存。普通/debug的公共字段、事件ID完全相同，debug不进入算法身份。

内部/公开字段及关联全部校验后，仅`model_dump_json().encode('utf-8')`一次；检查最终字节和原deadline，再由API以`Response(content=body, media_type='application/json')`发送，OpenAPI声明普通/debug联合。保留现no-store策略，不让框架在检查后重新编码，不用exclude_none删除合法null。debug合同错误整份失败，不降级普通成功。

固定预算：总4秒（含共享等待、读取、历史恢复、完整/公开校验及编码），并发2，返回≤2000根且≤1MiB，缓存≤64MiB/16系列；普通/debug同上限，不能截断关联凑容量。客户端沿原scheduler及5秒截止，覆盖解析和最终显示，模式/日期变化清理旧请求，迟到结果不能串用。

| HTTP | code/行为 | 场景 |
|---:|---|---|
| 400 | XXM_REQUEST_INVALID | 请求格式、日期、debug、未知/重复参数非法 |
| 404 | XXM_NOT_SUPPORTED | 合法但不支持的标的；生产/未注册路径为原框架404，不伪造此业务错误或EMPTY |
| 500 | XXM_SOURCE_CONTRACT_INVALID | 源缺口、非法数值/时点、完整或公开结果合同不合法 |
| 500 | XXM_QUERY_FAILED | 一般查询失败 |
| 503 | XXM_BUDGET_EXCEEDED | 读取/处理超时、数量或字节预算超限 |
| 503 | XXM_QUERY_FAILED | 保留当前直接query调用缺本地分钟reader的显式例外；不把一般QUERY_FAILED全改503。日线不因缺分钟reader失败 |
| 401/403 | 原unauthorized/forbidden | 既有鉴权 |

错误体仍为现Wealth的code/message/request_id，不改成另一个包装。错误不能吞成EMPTY；失败清本请求失效标记及辅助结果，正常K线保留。完整错误及异常登记以[LLD§9](index-detail-top-bottom-recognition-low-level-design-v1.md#9-预算错误取消及数据读写边界)为准，不新增错误码。

P2—P4须同步query直接调用、Python schema/API、前端xxm类型/decoder/client/hook、日线和分钟图表及悬停、web测试和保留核验工具；旧DTO返回或根层辅助字段没有兼容别名。P1仅冻结目标，不能用尚未实现的r4合同验证当前r2并声称通过；独立样例位于现主题tests，详见LLD§16。后续本地/生产/真实来源和删后验收完成前，不宣称产品迁移完成。
