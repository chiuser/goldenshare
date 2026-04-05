# 行情主系统接口规范（Quote Detail API v1）

## 1. 目标与边界

本文档定义业务主系统（面向终端用户）的行情图表页接口规范，作为后续接口实现与联调的唯一基线。

边界约束：

- 本文档仅覆盖业务主系统接口，不覆盖内部运维接口。
- 内部运维接口继续保留在 `ops` 域（如 `/api/v1/ops/*`），不与业务接口混用。
- 业务接口统一放在 `/api/v1/quote/*` 与 `/api/v1/market/*`。
- 数据同步、调度、任务执行仍属于数据基座与运维体系，不下沉到业务接口层。

---

## 2. 研发规范（与现有工程一致）

### 2.1 路由与模块分层

- Router：`src/web/api/v1/quote.py`、`src/web/api/v1/market.py`
- Schema：`src/web/schemas/quote.py`
- Query Service：`src/web/queries/quote_query_service.py`
- 复用 `core`/`dm` 数据，不在 web 层新增重型跑数逻辑

### 2.2 协议规范

- 路由前缀：`/api/v1`
- 默认返回 JSON 对象，字段命名 `snake_case`
- 时间字段统一 `YYYY-MM-DD`
- 数值字段默认 `number`（后端 `Decimal` 转 JSON 数字）
- 所有错误返回可读中文 `detail`，禁止暴露内部 SQL/栈信息给前端

### 2.3 鉴权规范

- 当前阶段与现有业务页面一致：需要登录态（JWT）
- 后续若需行情匿名访问，再单独拆“公开行情接口”版本

### 2.4 安全与鉴权预留（必须）

即使当前阶段暂未完成完整登录体系，业务主系统接口也必须预留统一鉴权能力，避免后续返工。

#### v1（当前可落地）

- 统一预留 `Authorization` 请求头：
  - `Authorization: Bearer <token>`
- Router 层预留鉴权依赖入口（例如 `get_current_user_optional`），允许在“开发模式”放行。
- 生产环境支持开关：
  - `QUOTE_API_AUTH_REQUIRED=true|false`
  - `false` 仅允许在开发或内网验收环境使用。

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

- `UNAUTHORIZED`：未提供或无效登录凭证（401）
- `FORBIDDEN`：当前账号无访问权限（403）
- `AUTH_REQUIRED`：当前环境要求鉴权但请求未带凭证（401）

---

## 3. 数据能力映射（基于当前数据基座）

可直接支撑：

- 证券基础：`core.security`、`core.index_basic`、`core.etf_basic`
- 股票日线：`core.equity_daily_bar` + `core.equity_daily_basic`
- 股票周/月：`core.stk_period_bar`、`core.stk_period_bar_adj`
- 指数日/周/月：`core.index_daily_serving`、`core.index_weekly_serving`、`core.index_monthly_serving`
- ETF 日线：`core.fund_daily_bar`
- 复权因子：`core.equity_adj_factor`
- 交易日历：`core.trade_calendar`

当前缺口（v1 明确降级）：

- 分钟线/分时：暂无底表
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
- `symbol + market`（兼容路径）

当同时传入时，以 `ts_code` 为准。

### 5.2 枚举值

- `security_type`: `stock | index | etf`
- `period`: `day | week | month | minute5 | minute15 | minute30 | minute60 | timeline`
- `adjustment`: `none | forward | backward`

### 5.3 参数校验

- `index`/`etf` 请求 `forward/backward` 时：
  - v1 返回 `400`（`UNSUPPORTED_ADJUSTMENT`）
- 分钟周期请求（`timeline`、`minute*`）：
  - v1 返回 `501`（`UNSUPPORTED_PERIOD`）

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
    "latest_price": 1705.0,
    "pre_close": 1690.0,
    "change_amount": 15.0,
    "pct_chg": 0.008876,
    "open": 1696.0,
    "high": 1710.0,
    "low": 1690.0,
    "vol": 2350000,
    "amount": 3523000000,
    "turnover_rate": 0.81,
    "volume_ratio": 1.18,
    "pe_ttm": 31.25,
    "pb": 9.88,
    "total_mv": 2142300000000,
    "circ_mv": 2109000000000
  },
  "default_chart": {
    "default_period": "day",
    "default_adjustment": "forward"
  },
  "chart_header_defaults": {
    "ma5": 1698.32,
    "ma10": 1685.24,
    "ma20": 1662.7,
    "ma60": 1608.42,
    "ma120": 1542.18,
    "ma250": 1476.85,
    "volume_ma5": 2120000,
    "volume_ma10": 2030000,
    "macd": 8.142,
    "dif": 12.356,
    "dea": 8.285,
    "k": 63.428,
    "d": 58.771,
    "j": 72.742
  }
}
```

---

## 6.2 K线与指标序列（核心）

### 路由

`GET /api/v1/quote/detail/kline`

### Query

- `ts_code?: string`
- `symbol?: string`
- `market?: string`
- `security_type?: stock|index|etf`（默认 `stock`）
- `period: day|week|month|minute5|minute15|minute30|minute60|timeline`
- `adjustment?: none|forward|backward`（默认 `forward`，仅 `stock`）
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
      "open": 16.9,
      "high": 17.11,
      "low": 16.36,
      "close": 16.45,
      "pre_close": 16.99,
      "change_amount": -0.54,
      "pct_chg": -3.18,
      "vol": 455000,
      "amount": 75700,
      "turnover_rate": 4.19,
      "ma5": 16.99,
      "ma10": 17.12,
      "ma15": 17.4,
      "ma20": 17.45,
      "ma30": 17.56,
      "ma60": 16.98,
      "ma120": 16.77,
      "ma250": 15.98,
      "volume_ma5": 622000,
      "volume_ma10": 648600,
      "macd": -0.2,
      "dif": -0.15,
      "dea": -0.05,
      "k": 26.33,
      "d": 37.54,
      "j": 3.9
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

- `ts_code?: string`
- `symbol?: string`
- `market?: string`
- `limit?: int`（默认 5，最大 50）

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

- `exchange?: SSE|SZSE`（默认 `SSE`）
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

统一返回结构：

```json
{
  "detail": {
    "code": "UNSUPPORTED_PERIOD",
    "message": "当前数据基座尚未提供分钟级行情，请使用日/周/月周期。"
  }
}
```

错误码表：

- `INVALID_SYMBOL`：标的不存在或无法识别
- `UNSUPPORTED_PERIOD`：请求分钟周期（v1 不支持）
- `UNSUPPORTED_ADJUSTMENT`：指数/ETF 请求复权
- `INVALID_DATE_RANGE`：日期区间非法
- `DATA_NOT_READY`：数据未同步到可用范围

---

## 8. v1 降级与兼容策略

- 分钟线：返回 `501/UNSUPPORTED_PERIOD`
- 公告：返回空数组 + `capability.placeholder`
- 相关 ETF：在 `capability` 中标记不可用，不影响主流程

---

## 9. 实施优先级

P0：

1. `GET /api/v1/quote/detail/kline`
2. `GET /api/v1/quote/detail/page-init`

P1：

3. `GET /api/v1/market/trade-calendar`
4. `GET /api/v1/quote/detail/related-info`

P2：

5. `GET /api/v1/quote/detail/announcements`（占位接口）

---

## 10. 验收标准

- 客户端无需自行计算指标，切周期即可直接绘图
- 同一标的在日/周/月下字段语义一致
- 非支持能力返回明确中文错误，不出现内部术语
- 业务接口与内部运维接口边界清晰，路由不混用
