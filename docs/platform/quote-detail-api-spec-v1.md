# 行情主系统接口规范（Quote Detail API v1）

> 文档状态：保留，作为 Quote Detail API v1 核心接口专题；不是全量业务 API 的唯一基线。
>
> 权威来源：当前实现代码、契约测试和当前消费者；本文档只描述已列明的 Quote v1 接口。

## 1. 目标与边界

本文档定义当前 Quote Detail API v1 核心接口的实现与联调口径。它不是整个业务主系统的 API 总规范，也不替代其他业务域的接口文档。

边界约束：

- 本文档仅覆盖下方接口清单中的 Quote v1 核心接口，不覆盖内部运维接口。
- 内部运维接口继续保留在 `ops` 域（如 `/api/v1/ops/*`），不与业务接口混用。
- 本文档覆盖 `/api/v1/quote/detail/*` 中列明的核心接口，以及 `/api/v1/market/trade-calendar`。
- `/api/v1/wealth/**`、`/api/v1/realtime/**` 和独立专题接口不在本文档范围内。
- 数据同步、调度、任务执行仍属于数据基座与运维体系，不下沉到业务接口层。

---

## 2. 研发规范（与现有工程一致）

### 2.1 路由与模块分层

- Router：`src/biz/api/quote.py`、`src/biz/api/market.py`
- Schema：`src/biz/schemas/quote.py`
- Query Service：`src/biz/queries/quote_query_service.py`
- 复用已接入的 `core_serving`、`core_serving_light` 数据模型，不在 web 层新增重型跑数逻辑

### 2.2 协议规范

- 路由前缀：`/api/v1`
- 默认返回 JSON 对象，字段命名 `snake_case`
- 时间字段统一 `YYYY-MM-DD`
- 价格、指标等后端 `Decimal` 字段序列化为 JSON 字符串，以保留四位小数精度；计数、布尔等原生字段按 JSON 原生类型返回
- 所有错误返回顶层 `code`、`message`、`request_id` 字段，禁止暴露内部 SQL/栈信息给前端

### 2.3 鉴权规范

- 行情接口统一复用 JWT 鉴权依赖；是否强制登录由 `QUOTE_API_AUTH_REQUIRED` 运行时配置决定，当前代码默认值为 `false`
- 后续若需行情匿名访问，再单独拆“公开行情接口”版本

### 2.4 安全与鉴权预留（必须）

行情接口始终接入统一鉴权依赖；开发或内网验收环境可以通过配置放行，生产环境应按部署安全策略决定是否强制登录。

#### v1（当前可落地）

- 统一预留 `Authorization` 请求头：
  - `Authorization: Bearer <token>`
- Router 层预留鉴权依赖入口（例如 `get_current_user_optional`），允许在“开发模式”放行。
- 生产环境支持开关：
  - `QUOTE_API_AUTH_REQUIRED=true|false`
  - `false` 仅允许在开发或内网验收环境使用。

以下 v1.1/v1.2 内容属于后续安全治理建议，不代表当前代码已经实现。

#### v1.1（上线前必须开启）

- 开启强制 token 校验：
  - 无 token -> `401`
  - token 无效/过期 -> `401`
  - 权限不足 -> `403`
- Token 采用短期有效期（如 30~120 分钟）+ 刷新机制。
- 审计日志记录最小字段：`request_id`、`user_id`、`path`、`status`、`duration_ms`。

#### v1.2（面向公网时建议）

- 增加访问频控（IP + user 双维度）。
- 增加 CORS 白名单（按环境配置）。
- 增加关键接口缓存与防刷策略（尤其 `kline`）。
- 增加统一错误脱敏策略，禁止返回底层异常栈。

#### 错误码补充

- `unauthorized`：未提供或无效登录凭证（401）
- `forbidden`：当前账号无访问权限（403）
- `auth_required`：当前环境要求鉴权但请求未带凭证（401）

---

## 3. 数据能力映射（基于当前数据基座）

可直接支撑：

- 证券基础：`core_serving.security_serving`、`core_serving.index_basic`、`core_serving.etf_basic`
- 股票日线：默认优先读取 `core_serving_light.equity_daily_bar_light`，按配置回退到 `core_serving.equity_daily_bar`；基础指标读取 `core_serving.equity_daily_basic`
- 股票周/月：`core_serving.stk_period_bar`、`core_serving.stk_period_bar_adj`
- 指数日/周/月：`core_serving.index_daily_serving`、`core_serving.index_weekly_serving`、`core_serving.index_monthly_serving`
- ETF 日线：`core_serving.fund_daily_bar`
- 复权因子：`core.equity_adj_factor`
- 交易日历：`core_serving.trade_calendar`
- 股票日线 MACD/KDJ 已有值时还会读取 `core_serving.equity_factor_pro` 进行覆盖；其余指标由查询服务计算。

当前缺口（v1 明确降级）：

- `/api/v1/quote/detail/kline` 暂不支持分钟线/分时；其他业务域的分钟接口不属于本文档范围
- 公告正文流：暂无稳定数据源
- 股票->ETF 推荐映射：暂无统一映射表

---

## 4. 接口清单（v1）

1. `GET /api/v1/quote/detail/page-init`
2. `GET /api/v1/quote/detail/kline`
3. `GET /api/v1/quote/detail/related-info`
4. `GET /api/v1/quote/detail/announcements`
5. `GET /api/v1/market/trade-calendar`

---

## 5. 统一参数规则

### 5.1 标的标识

支持两种输入方式（二选一）：

- `ts_code`（推荐，主路径）
- `symbol + market`（可选路径）

当同时传入时，以 `ts_code` 为准。

### 5.2 枚举值

- `security_type`: `stock | index | etf`；未传时由服务端按标的事实自动识别
- `period`: `day | week | month | minute5 | minute15 | minute30 | minute60 | timeline`
- `adjustment`: `none | forward | backward`

### 5.3 参数校验

- `index`/`etf` 请求 `forward/backward` 时：
  - v1 返回 `400`（`UNSUPPORTED_ADJUSTMENT`）
- 分钟周期请求（`timeline`、`minute*`）：
  - v1 返回 `501`（`UNSUPPORTED_PERIOD`）
- ETF 当前仅支持 `day` 周期；请求 `week`/`month` 返回 `400`（`INVALID_ARGUMENT`）

---

## 6. 接口详细定义

## 6.1 页面初始化

### 路由

`GET /api/v1/quote/detail/page-init`

### Query

- `ts_code?: string`
- `symbol?: string`
- `market?: string`
- `security_type?: stock|index|etf`

### Response（200）

```json
{
  "instrument": {
    "instrument_id": "SH.600519",
    "ts_code": "600519.SH",
    "symbol": "600519",
    "name": "贵州茅台",
    "market": "SH",
    "security_type": "stock",
    "exchange": "SSE",
    "industry": "白酒",
    "list_status": "L"
  },
  "price_summary": {
    "trade_date": "2026-04-03",
    "latest_price": "1705.0000",
    "pre_close": "1690.0000",
    "change_amount": "15.0000",
    "pct_chg": "0.0089",
    "open": "1696.0000",
    "high": "1710.0000",
    "low": "1690.0000",
    "vol": "2350000.0000",
    "amount": "3523000000.0000",
    "turnover_rate": "0.8100",
    "volume_ratio": "1.1800",
    "pe_ttm": "31.2500",
    "pb": "9.8800",
    "total_mv": "2142300000000.0000",
    "circ_mv": "2109000000000.0000"
  },
  "default_chart": {
    "default_period": "day",
    "default_adjustment": "forward"
  },
  "chart_header_defaults": {
    "ma5": "1698.3200",
    "ma10": "1685.2400",
    "ma20": "1662.7000",
    "ma60": "1608.4200",
    "ma120": "1542.1800",
    "ma250": "1476.8500",
    "volume_ma5": "2120000.0000",
    "volume_ma10": "2030000.0000",
    "macd": "8.1420",
    "dif": "12.3560",
    "dea": "8.2850",
    "k": "63.4280",
    "d": "58.7710",
    "j": "72.7420"
  }
}
```

股票 page-init 默认使用 `forward`；当复权因子或复权锚点不完整时，服务端会将 `default_adjustment` 回退为 `none`，并按不复权数据返回头部指标。

---

## 6.2 K线与指标序列（核心）

### 路由

`GET /api/v1/quote/detail/kline`

### Query

- `ts_code?: string`
- `symbol?: string`
- `market?: string`
- `security_type?: stock|index|etf`（未传时由服务端自动识别）
- `period: day|week|month|minute5|minute15|minute30|minute60|timeline`
- `adjustment?: none|forward|backward`（默认 `forward`；股票支持三种取值，指数/ETF 必须使用 `none`）
- `start_date?: YYYY-MM-DD`
- `end_date?: YYYY-MM-DD`
- `limit?: int`（默认 300，最大 2000）

### Response（200）

```json
{
  "instrument": {
    "instrument_id": "SZ.002245",
    "ts_code": "002245.SZ",
    "symbol": "002245",
    "name": "蔚蓝锂芯",
    "security_type": "stock"
  },
  "period": "day",
  "adjustment": "forward",
  "bars": [
    {
      "trade_date": "2026-04-03",
      "open": "16.9000",
      "high": "17.1100",
      "low": "16.3600",
      "close": "16.4500",
      "pre_close": "16.9900",
      "change_amount": "-0.5400",
      "pct_chg": "-3.1800",
      "vol": "455000.0000",
      "amount": "75700.0000",
      "turnover_rate": "4.1900",
      "ma5": "16.9900",
      "ma10": "17.1200",
      "ma15": "17.4000",
      "ma20": "17.4500",
      "ma30": "17.5600",
      "ma60": "16.9800",
      "ma120": "16.7700",
      "ma250": "15.9800",
      "volume_ma5": "622000.0000",
      "volume_ma10": "648600.0000",
      "macd": "-0.2000",
      "dif": "-0.1500",
      "dea": "-0.0500",
      "k": "26.3300",
      "d": "37.5400",
      "j": "3.9000"
    }
  ],
  "meta": {
    "bar_count": 300,
    "has_more_history": true,
    "next_start_date": "2025-01-01"
  }
}
```

### 服务端职责

- 周期切换：按请求返回 `day/week/month`
- 复权切换：`stock` 支持 `none/forward/backward`
- 统一计算并返回指标：
  - MA：5/10/15/20/30/60/120/250
  - 成交量均线：5/10
  - MACD：12/26/9
  - KDJ：9/3/3
- 按时间升序返回 bars

### 技术指标计算规则（面向调用方）

为避免“只查 1 天就把该天当首日计算”导致的指标失真，服务端在计算指标时使用**预热窗口**：

1. 先按请求条件确定返回区间（最终只返回这个区间的 bars）。
2. 对 `stock + day` 计算指标时，会在返回区间起点前向历史多取最多 `250` 根有效 K 线作为预热数据。
3. 指标在“预热数据 + 返回区间”上统一计算，最后只裁剪返回区间。

边界规则：

1. 若是新股或历史不足 250 根，则按实际可得历史计算，不做补值。
2. MA 类指标在样本不足对应周期时返回 `null`（例如不足 60 根则 `ma60=null`）。
3. MACD/KDJ 采用统一初始化规则，但不会因请求窗口过短而重置整条历史状态。
4. 停牌/非交易日不补空 bar，只按有效交易日序列递推。

一致性约束：

1. 同一标的同一交易日，指标值应与“请求范围长度”无关（查 1 天与查 1 年结果一致）。

---

## 6.3 相关信息

### 路由

`GET /api/v1/quote/detail/related-info`

### Query

- `ts_code?: string`
- `symbol?: string`
- `market?: string`
- `security_type?: stock|index|etf`

### Response（200）

```json
{
  "items": [
    { "type": "industry", "title": "行业", "value": "锂电池", "action_target": null },
    { "type": "concept", "title": "概念", "value": "储能", "action_target": "CONCEPT:储能" }
  ],
  "capability": {
    "related_etf": "not_available_in_v1"
  }
}
```

---

## 6.4 公告

### 路由

`GET /api/v1/quote/detail/announcements`

### Query

当前占位实现不接收业务查询参数，调用只返回空列表和能力状态。

### Response（200，占位）

```json
{
  "items": [],
  "capability": {
    "status": "placeholder",
    "reason": "announcement_source_not_ready"
  }
}
```

---

## 6.5 交易日历

### 路由

`GET /api/v1/market/trade-calendar`

### Query

- `exchange?: string`（默认 `SSE`；服务端统一转为大写后查询）
- `start_date: YYYY-MM-DD`
- `end_date: YYYY-MM-DD`

### Response（200）

```json
{
  "exchange": "SSE",
  "items": [
    { "trade_date": "2026-04-03", "is_open": true, "pretrade_date": "2026-04-02" }
  ]
}
```

---

## 7. 错误码规范（业务接口）

统一错误返回结构：

```json
{
  "code": "UNSUPPORTED_PERIOD",
  "message": "当前数据基座尚未提供分钟级行情，请使用日/周/月周期。",
  "request_id": "..."
}
```

错误码表：

- `INVALID_SYMBOL`：标的不存在或无法识别
- `UNSUPPORTED_PERIOD`：请求分钟周期（v1 不支持）
- `INVALID_ADJUSTMENT`：请求了不支持的复权枚举值
- `UNSUPPORTED_ADJUSTMENT`：指数/ETF 请求复权
- `INVALID_DATE_RANGE`：日期区间非法
- `INVALID_ARGUMENT`：查询服务无法按当前参数构造结果

---

## 8. v1 能力降级说明

- 分钟线：返回 `501/UNSUPPORTED_PERIOD`
- 公告：返回空数组 + `capability.status=placeholder`，并提供 `capability.reason=announcement_source_not_ready`
- 相关 ETF：在 `capability` 中标记不可用，不影响主流程

---

## 9. 当前实现状态

- `page-init`、`kline`、`related-info`、`trade-calendar`：当前代码已实现，并有接口测试覆盖。
- `announcements`：当前代码已实现为占位接口，返回空列表和 `announcement_source_not_ready` 能力状态。
- 分钟线/分时：Quote v1 的 `kline` 接口仍按约定返回 `501/UNSUPPORTED_PERIOD`。
- 新增接口或能力的优先级，应在对应专题方案中单独确定，不在本 v1 清单中保留 P0/P1/P2 排序。

---

## 10. 验收标准

- 客户端无需自行计算指标，切周期即可直接绘图
- 同一标的在日/周/月下字段语义一致
- 非支持能力返回明确中文错误，不出现内部术语
- 业务接口与内部运维接口边界清晰，路由不混用
