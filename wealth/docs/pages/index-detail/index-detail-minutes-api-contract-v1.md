# 指数详情本地分钟 API / DTO 合同 v1

> 版本：`1.0.1`
> 状态：M5-A 已实现并通过验证；Silver bars 使用正式数据，Gold indicators 的正式数据接入保留到 M5-B。
> 命名空间：`/api/v1/wealth/market/index-detail/*`

## 1. 边界

1. 本合同只在 `APP_ENV in {dev, local}`、本地分钟开关开启、正式 Lake 根可读且 DuckDB 可用时挂载；prod/staging 不挂载，访问返回 404。
2. bars 唯一读取 `/Volumes/datasource/data_lake/silver/quote/major_index_mins`；indicators 唯一读取正式 Gold `major_index_mins_technical`，不读取 state、旧 Lake 或 staging。
3. `899050.BJ` 属于页面十指数名单，但不在 Silver 源覆盖中；分钟 bars 返回 `EMPTY + IM_SOURCE_NOT_READY`。
4. Lake 中存在但不属于页面十指数名单的代码，例如 `000680.SH`，返回 `ID_NOT_FOUND`。
5. M5-A 前端开发态指标 Mock 不是 HTTP 接口返回值，不进入本合同的后端实现，不写 Lake，也不在真实接口错误时回退。

## 2. 请求

### 2.1 路由

```http
GET /api/v1/wealth/market/index-detail/minutes
GET /api/v1/wealth/market/index-detail/minute-indicators
```

### 2.2 参数

| 参数 | 类型 | 必填 | 规则 |
|---|---|---:|---|
| `tsCode` | string | 是 | trim + upper；必须属于 `majorIndices/CN_A` 十指数名单 |
| `freq` | integer | 是 | 只允许 `1/5/15/30/60/90/120` |
| `startDate` | `YYYY-MM-DD` | 否 | 不得晚于 `endDate` |
| `endDate` | `YYYY-MM-DD` | 否 | 页面默认使用当前日线观测日 `asOfTradeDate`，保持分钟图表与右栏日频快照的时间边界一致 |
| `limit` | integer | 否 | 默认 500，范围 `1..10000` |
| `cursor` | string | 否 | v1 URL-safe base64；绑定 dataset/code/freq/start/end/before time |

未知参数、重复参数、非法日期、非法 limit、cursor 解析失败或 cursor 与当前请求错配均返回 HTTP 400 `ID_REQUEST_INVALID`。分页不使用 OFFSET。

## 3. 响应 DTO

所有对象 `extra=forbid`，JSON 字段统一 lowerCamelCase。`tradeTime` 以带 `+08:00` 的 ISO-8601 返回。

### 3.1 通用分页与状态

```json
{
  "meta": {
    "count": 500,
    "limit": 500,
    "hasMore": true,
    "nextCursor": "...",
    "startDate": null,
    "endDate": "2026-08-11",
    "observedStartDate": "2026-08-08",
    "observedEndDate": "2026-08-11"
  },
  "dataStatus": {
    "status": "READY",
    "code": null,
    "expectedEndDate": "2026-08-11",
    "observedEndDate": "2026-08-11",
    "message": null
  }
}
```

`dataStatus.status` 只允许 `READY/DELAYED/EMPTY`。文件未覆盖、观测日期落后或已知源不支持时，`code="IM_SOURCE_NOT_READY"`；文件合同或查询错误走非 200 HTTP 错误，不返回伪 `ERROR` 状态。

### 3.2 Bars

```json
{
  "tsCode": "000001.SH",
  "freq": 5,
  "bars": [
    {
      "tsCode": "000001.SH",
      "freq": 5,
      "tradeDate": "2026-08-11",
      "tradeTime": "2026-08-11T09:35:00+08:00",
      "open": 3900.0,
      "high": 3902.0,
      "low": 3899.0,
      "close": 3901.0,
      "vol": 123456.0,
      "amount": 987654321.0,
      "exchange": "SSE"
    }
  ],
  "meta": {},
  "dataStatus": {}
}
```

不返回 `preClose/change/changePct/amplitude/turnoverRate/vwap`，前端不得自行伪造日线字段。

### 3.3 Indicators

```json
{
  "tsCode": "000001.SH",
  "freq": 5,
  "items": [
    {
      "tsCode": "000001.SH",
      "freq": 5,
      "tradeDate": "2026-08-11",
      "tradeTime": "2026-08-11T09:35:00+08:00",
      "ma5": 3900.2,
      "ma10": 3899.8,
      "ma20": 3898.6,
      "ma30": 3897.1,
      "ma60": 3894.3,
      "ma90": 3890.4,
      "ma250": null,
      "bollMiddle": 3898.6,
      "bollUpper": 3908.1,
      "bollLower": 3889.1,
      "macdDif": 1.2,
      "macdDea": 0.9,
      "macd": 0.6,
      "kdjK": 62.0,
      "kdjD": 57.0,
      "kdjJ": 72.0,
      "observationCount": 120,
      "paramsKey": "ma_5_10_20_30_60_90_250__boll_20_2__macd_12_26_9__kdj_9_3_3",
      "indicatorVersion": 1
    }
  ],
  "meta": {},
  "dataStatus": {}
}
```

MA/BOLL warm-up 不足时保持 null；MACD/KDJ 由 Gold 合同负责，不由 BFF 重新计算。

## 4. 异常

| HTTP | code | 语义 |
|---:|---|---|
| 400 | `ID_REQUEST_INVALID` | 参数、limit、文件数量上界或 cursor 不合法 |
| 404 | `ID_NOT_FOUND` | 非页面十指数名单 |
| 500 | `IM_SOURCE_CONTRACT_INVALID` | 路径、Parquet schema、身份、日期、时间键或版本不符合合同 |
| 500 | `IM_QUERY_FAILED` | DuckDB、文件 IO、查询或结果校验失败 |

401/403 沿用认证层。响应体超过 5MB 按 `ID_REQUEST_INVALID` 拒绝，调用方必须降低 limit 或使用 cursor。

## 5. M5-A Mock 边界

1. Mock provider 仅在 Vite 开发模式且 page-init 宣布分钟能力时工作。
2. Mock 输入真实 bars，按相同时间键确定性生成 MA/BOLL/MACD/KDJ；使用 `paramsKey=mock_index_minute_technical_v1`、`indicatorVersion=0`。
3. Mock 成功生成时页面必须显示“模拟指标”；空数据或 Mock 生成失败后的 bars-only PARTIAL 不得显示该标识。Mock 不改变 bars 的 READY/EMPTY/DELAYED 状态。
4. M5-B 真实 Gold 验收通过后删除 Mock provider、标识和测试，切换到本合同的 indicator endpoint，不保留双源兼容。

## 6. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| 1.0.1 | 2026-08-11 | 回填 M5-A 实现状态与验收：七频率、cursor/5MB/5000 分区门禁、正式 Silver 性能、北证50 EMPTY、开发态 Mock v0 与生产 404 均通过 | Codex |
| 1.0.0 | 2026-08-11 | 冻结 local-only 双接口、Silver bars、Gold indicators、状态/异常/cursor/5MB 边界与 M5-A 开发态 Mock 例外 | Codex |
