# 财势乾坤｜市场总览首页 API 草案 v0.2

建议路径：`/docs/wealth/api/market-overview-api.md`  
建议 Drive 文件夹：`数据字典与API文档`  
负责人：`04_API 契约与数据字典`  
状态：Draft v0.2

---

## 0. v0.2 变更说明

## 0.1 v0.2.1 口径修正：API 默认保持 Tushare / 落库字段单位

根据产品总控确认，市场总览首页 API 从 v0.2.1 起执行以下规则：

1. API 字段使用财势乾坤业务命名，但单位、数值尺度默认保持 Tushare 原字段或当前 PostgreSQL 落库口径。
2. 不再默认把 `daily.amount`、`index_daily.amount` 等金额字段转为“元”，也不再默认把 `daily.vol` 等成交量字段转为“股”。
3. 已确认特例：`trade_cal.is_open` 当前落库已改为 boolean，因此接口中的 `isTradingDay` 直接使用 boolean。
4. 前端展示层负责单位格式化；API 响应应通过字段说明、`unit` 或 `sourceRefs` 明确原始单位。
5. 若后端需要输出展示型换算字段，必须使用显式字段名，例如 `amountInYuan`，不能覆盖与 Tushare 同口径的 `amount`。

本条修正规则优先级高于 v0.2 文档中“金额统一元、成交量统一股”的旧描述。

---

相对 v0.1，本版主要变化：

1. 明确 Tushare 是已落库数据基座来源和字段口径参考，不是财势乾坤前端 API 形态。
2. 每个首页模块增加推荐数据基座视图与 Tushare 数据集依赖。
3. 统一 response 业务字段命名和单位：金额 `元`，成交量 `股`，涨跌幅为百分数数值。
4. 首页仍然只展示客观事实，不返回市场温度、市场情绪、资金面分数、风险指数作为核心结论。
5. 增加 `sourceRefs` 和 `dataStatus`，让前端可展示数据来源、延迟和异常降级状态。

## 0.1 首页聚合接口推荐数据来源

| 聚合字段 | 推荐基座视图 | Tushare 来源 | 说明 |
|---|---|---|---|
| `overview` | `wealth_trade_day_view` | `trade_cal` | 交易日、是否开市、上一交易日 |
| `indices` | `wealth_index_snapshot_view` | `index_daily` | 核心指数快照，金额归一为元 |
| `breadth` | `wealth_market_breadth_snapshot` | `daily`、`stock_basic`、`limit_list_d` | 涨跌家数、红盘率、中位涨跌幅 |
| `style` | `wealth_market_style_snapshot` | `index_daily` | 大小盘和风格指数对比 |
| `turnover` | `wealth_turnover_summary_snapshot` | `daily`、`stock_basic` | 全市场成交额和 20 日中位量能 |
| `moneyFlow` | `wealth_moneyflow_market_snapshot` | `moneyflow_mkt_dc` | 大盘资金流事实；不是资金面分数 |
| `limitUp` | `wealth_limitup_snapshot` | `limit_list_d`、`stk_limit`、`daily` | 涨停、跌停、炸板、封板率 |
| `streakLadder` | `wealth_limitup_streak_snapshot` | `limit_list_d` | 连板天梯 |
| `topSectors` | `wealth_sector_rank_snapshot` | `sw_daily`、`moneyflow_ind_dc` | 板块涨跌和资金榜 |
| `stockLeaderboards` | `wealth_stock_rank_snapshot` | `daily`、`daily_basic`、`stock_basic`、`limit_list_d` | 个股榜单 |
| `quickEntries` | `wealth_quick_entry_config` | 内部配置 | 首页分流入口 |
| `dataSources` | `wealth_data_source_status` | 同步任务 | 数据源状态 |

## 0.2 sourceRefs 约定

模块级 response 建议包含：

```json
{
  "dataStatus": "READY",
  "asOf": "2026-04-28T17:10:00+08:00",
  "sourceRefs": [
    {"dataset": "daily", "docId": 27, "latestTradeDate": "2026-04-28", "normalized": true}
  ]
}
```

| 字段 | 说明 |
|---|---|
| `dataset` | 数据基座中的 Tushare 数据集名或内部视图名 |
| `docId` | Tushare 文档编号；内部配置可为空 |
| `latestTradeDate` | 该数据集最新交易日 |
| `normalized` | 是否与当前业务口径一致；默认不代表单位换算 |

---


## 0. API 设计原则

1. 首页是“市场客观事实驾驶舱”，不是主观分析结论页。
2. 首页接口只返回指数、涨跌家数、成交额、资金流事实、涨跌停、板块榜、个股榜、快捷入口等客观数据。
3. 首页接口不返回 `MarketTemperature.score`、`MarketSentiment.score`、`RiskIndex.riskScore` 作为核心结论。
4. 市场温度、市场情绪、风险指数独立放在“市场温度与情绪分析页”的接口中。
5. A 股红涨绿跌：所有行情对象必须返回 `direction`，前端统一 `UP=red`、`DOWN=green`、`FLAT=gray`。
6. P0 推荐“聚合接口优先 + 模块接口兜底”：首屏用聚合接口减少请求数，模块刷新、降级、调试使用模块接口。
7. 所有金额默认人民币元，百分比字段默认百分数数值，占比字段默认 0-1 小数。

---

## 1. 统一响应结构

```json
{
  "code": 0,
  "message": "ok",
  "data": {},
  "traceId": "req_20260428_000001",
  "serverTime": "2026-04-28T09:30:00+08:00"
}
```

### 1.1 通用字段说明


| 字段 | 类型 | 说明 |
| --- | --- | --- |
| code | integer | 业务状态码，0 成功 |
| message | string | 业务消息 |
| data | object / array / null | 响应数据 |
| traceId | string | 请求追踪 ID |
| serverTime | string(datetime) | 服务端时间 |


### 1.2 错误码


| code | 含义 | HTTP 建议 | 前端处理 |
| --- | --- | --- | --- |
| 0 | 成功 | 200 | 正常渲染 |
| 400001 | 参数错误 | 400 | 展示参数错误提示，保留页面旧数据 |
| 401001 | 未登录 | 401 | 跳转登录或使用游客配置 |
| 403001 | 无权限 | 403 | 展示无权限占位 |
| 404001 | 数据不存在 | 404 | 展示空状态 |
| 409001 | 状态冲突 | 409 | 提示当前市场状态不支持该请求 |
| 429001 | 请求过快 | 429 | 前端降频重试 |
| 500001 | 服务异常 | 500 | 展示异常态，可重试 |
| 503001 | 数据源不可用 | 503 | 展示数据源异常与最近缓存 |


### 1.3 通用请求参数


| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| tradeDate | string(date) | 否 | 当前交易日 | 指定交易日；盘中首页通常不传 |
| market | string(enum) | 否 | CN_A | P0 默认 A 股 |
| asOf | string(datetime) | 否 | 服务端最新 | 指定数据截至时间，主要用于回放 |
| limit | integer | 否 | 视接口而定 | 返回条数 |
| source | string | 否 | default | 数据源选择，P0 可不开放 |


---

## 2. 首页 API 推荐方案

### 2.1 推荐结论

首页首屏推荐使用：

```http
GET /api/market/home-overview
```

原因：

1. 首页首屏模块多，使用聚合接口可以减少请求瀑布。
2. 后端可以统一控制数据时间、缓存、降级策略。
3. 首页 Mock 数据可以直接映射到一个 response，方便 02 HTML Showcase 和 Codex 还原。
4. 模块接口仍保留，用于局部刷新、懒加载、错误重试、后续页面复用。

### 2.2 聚合关系


| 聚合字段 | 来源模块接口 | 首页模块 |
| --- | --- | --- |
| overview | /api/market/overview | 顶部市场状态 |
| indices | /api/index/summary | 核心指数卡片 |
| breadth | /api/market/breadth | 涨跌家数 / 红盘率 |
| style | /api/market/style | 大盘 / 小盘 / 成长价值风格 |
| turnover | /api/market/turnover | 全市场成交额 |
| moneyFlow | /api/moneyflow/market | 资金流事实摘要，可降级 |
| limitUp | /api/limitup/summary | 涨跌停摘要 |
| streakLadder | /api/limitup/streak-ladder | 连板天梯摘要 |
| topSectors | /api/sector/top | 板块榜 |
| stockLeaderboards | /api/leaderboard/stock | 个股榜 |
| quickEntries | /api/settings/quick-entry | 快捷入口配置 |

---

## 3. API 明细


### 3.1 GET /api/market/home-overview


#### endpoint


```http
GET /api/market/home-overview
```


#### method

`GET`


#### 前端使用场景

首页首屏一次性加载市场总览数据，包括交易状态、核心指数、市场广度、成交额、涨跌停、连板天梯、板块榜、个股榜和快捷入口。该接口是首页首屏推荐主接口。


#### request params


| 参数 | 类型 | 必填 | 示例 | 说明 |
| --- | --- | --- | --- | --- |
| market | string | 否 | CN_A | P0 默认 A 股 |
| tradeDate | string(date) | 否 | 2026-04-28 | 不传取当前交易日 |
| include | string | 否 | all | 可选模块，逗号分隔 |
| sectorLimit | integer | 否 | 8 | 板块榜返回数量 |
| stockLimit | integer | 否 | 10 | 每类个股榜返回数量 |


#### response JSON

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "overview": {
      "market": "CN_A",
      "tradeDate": "2026-04-28",
      "sessionStatus": "OPEN",
      "timezone": "Asia/Shanghai",
      "openTime": "2026-04-28T09:30:00+08:00",
      "closeTime": "2026-04-28T15:00:00+08:00",
      "prevTradeDate": "2026-04-27",
      "isDelayed": true,
      "dataStatus": "READY",
      "asOf": "2026-04-28T14:56:00+08:00"
    },
    "indices": [
      {
        "indexCode": "000001.SH",
        "indexName": "上证指数",
        "last": 3128.42,
        "prevClose": 3099.76,
        "open": 3108.91,
        "high": 3138.66,
        "low": 3098.12,
        "change": 28.66,
        "changePct": 0.92,
        "amount": 482300000000,
        "direction": "UP",
        "asOf": "2026-04-28T14:56:00+08:00"
      },
      {
        "indexCode": "399001.SZ",
        "indexName": "深证成指",
        "last": 9842.15,
        "prevClose": 9876.36,
        "open": 9890.23,
        "high": 9931.4,
        "low": 9788.15,
        "change": -34.21,
        "changePct": -0.35,
        "amount": 598400000000,
        "direction": "DOWN",
        "asOf": "2026-04-28T14:56:00+08:00"
      }
    ],
    "breadth": {
      "tradeDate": "2026-04-28",
      "samplePool": "CN_A_COMMON",
      "stockUniverseCount": 5128,
      "upCount": 3421,
      "downCount": 1488,
      "flatCount": 219,
      "redRate": 0.667,
      "medianChangePct": 0.48,
      "upGt3Pct": 0.142,
      "downGt3Pct": 0.041,
      "limitUpCount": 59,
      "limitDownCount": 8,
      "advancersDeclinersRatio": 2.3,
      "asOf": "2026-04-28T14:56:00+08:00"
    },
    "style": {
      "tradeDate": "2026-04-28",
      "largeCapIndexCode": "000300.SH",
      "smallCapIndexCode": "399303.SZ",
      "largeCapChangePct": 0.72,
      "smallCapChangePct": 1.48,
      "smallVsLargeSpreadPct": 0.76,
      "growthIndexCode": "399006.SZ",
      "valueIndexCode": "000016.SH",
      "growthChangePct": 1.21,
      "valueChangePct": 0.35,
      "styleLeader": "SMALL_CAP",
      "asOf": "2026-04-28T14:56:00+08:00"
    },
    "turnover": {
      "tradeDate": "2026-04-28",
      "totalAmount": 1052300000000,
      "prevTotalAmount": 982100000000,
      "amountChange": 70200000000,
      "amountChangePct": 7.15,
      "amount20dMedian": 936000000000,
      "amountRatio20dMedian": 1.12,
      "sseAmount": 438200000000,
      "szseAmount": 598400000000,
      "bseAmount": 15600000000,
      "asOf": "2026-04-28T14:56:00+08:00"
    },
    "moneyFlow": {
      "tradeDate": "2026-04-28",
      "netInflow": -5280000000,
      "mainNetInflow": -8120000000,
      "superLargeNetInflow": -3200000000,
      "largeNetInflow": -4920000000,
      "mediumNetInflow": 2100000000,
      "smallNetInflow": 6020000000,
      "northboundNetInflow": null,
      "dataStatus": "PARTIAL",
      "asOf": "2026-04-28T14:55:00+08:00"
    },
    "limitUp": {
      "tradeDate": "2026-04-28",
      "limitUpCount": 59,
      "limitDownCount": 8,
      "touchedLimitUpCount": 86,
      "failedLimitUpCount": 27,
      "sealRate": 0.686,
      "oneWordLimitUpCount": 7,
      "tradableLimitUpCount": 52,
      "highestStreak": 6,
      "firstBoardCount": 42,
      "secondBoardCount": 8,
      "asOf": "2026-04-28T14:56:00+08:00"
    },
    "streakLadder": [
      {
        "tradeDate": "2026-04-28",
        "streak": 6,
        "count": 1,
        "highestStreak": 6,
        "stocks": [
          {
            "stockCode": "002888.SZ",
            "stockName": "示例股份",
            "changePct": 10.01,
            "direction": "UP",
            "sectorName": "机器人",
            "amount": 920000000
          }
        ],
        "asOf": "2026-04-28T14:56:00+08:00"
      },
      {
        "tradeDate": "2026-04-28",
        "streak": 3,
        "count": 5,
        "highestStreak": 6,
        "stocks": [],
        "asOf": "2026-04-28T14:56:00+08:00"
      }
    ],
    "topSectors": [
      {
        "rank": 1,
        "sectorId": "BK0421",
        "sectorName": "储能",
        "sectorType": "CONCEPT",
        "changePct": 3.86,
        "direction": "UP",
        "redRate": 0.82,
        "riseCount": 63,
        "fallCount": 12,
        "amount": 128600000000,
        "amountRatio20dMedian": 1.45,
        "mainNetInflow": 2630000000,
        "leadingStockCode": "300750.SZ",
        "leadingStockName": "宁德时代",
        "leadingStockChangePct": 5.82
      }
    ],
    "stockLeaderboards": {
      "topGainers": [
        {
          "rank": 1,
          "rankType": "GAINER",
          "stockCode": "300123.SZ",
          "stockName": "示例科技",
          "price": 18.36,
          "changePct": 20.01,
          "direction": "UP",
          "amount": 3280000000,
          "volume": 182000000,
          "turnoverRate": 18.4,
          "volumeRatio": 2.8,
          "sectorName": "半导体",
          "isLimitUp": true,
          "isLimitDown": false,
          "asOf": "2026-04-28T14:56:00+08:00"
        }
      ],
      "topLosers": [
        {
          "rank": 1,
          "rankType": "LOSER",
          "stockCode": "600123.SH",
          "stockName": "示例能源",
          "price": 7.62,
          "changePct": -8.41,
          "direction": "DOWN",
          "amount": 880000000,
          "volume": 116000000,
          "turnoverRate": 7.6,
          "volumeRatio": 1.9,
          "sectorName": "煤炭",
          "isLimitUp": false,
          "isLimitDown": false,
          "asOf": "2026-04-28T14:56:00+08:00"
        }
      ],
      "topAmount": []
    },
    "quickEntries": [
      {
        "key": "market-emotion",
        "title": "市场温度与情绪",
        "route": "/market/emotion",
        "description": "查看温度、情绪、风险等分析页",
        "icon": "pulse",
        "enabled": true,
        "sortOrder": 10,
        "badge": null
      },
      {
        "key": "watchlist",
        "title": "自选",
        "route": "/watchlist",
        "description": "跟踪自选股表现",
        "icon": "star",
        "enabled": true,
        "sortOrder": 20,
        "badge": null
      },
      {
        "key": "positions",
        "title": "持仓",
        "route": "/positions",
        "description": "查看手工登记持仓",
        "icon": "briefcase",
        "enabled": true,
        "sortOrder": 30,
        "badge": "手工"
      }
    ],
    "dataSources": [
      {
        "sourceId": "daily_quote",
        "sourceName": "行情数据",
        "dataDomain": "QUOTE",
        "status": "READY",
        "latestDataTime": "2026-04-28T14:56:00+08:00",
        "completenessPct": 99.6
      },
      {
        "sourceId": "money_flow",
        "sourceName": "资金流数据",
        "dataDomain": "MONEY_FLOW",
        "status": "PARTIAL",
        "latestDataTime": "2026-04-28T14:55:00+08:00",
        "completenessPct": 82.4
      }
    ]
  },
  "traceId": "req_20260428_000001",
  "serverTime": "2026-04-28T14:56:30+08:00"
}
```


#### 字段说明


| 字段 | 说明 |
| --- | --- |
| overview | 首页顶部交易日、交易状态、数据状态 |
| indices | 首页核心指数卡片 |
| breadth | 市场广度事实，不含温度分 |
| style | 市场风格事实 |
| turnover | 成交额事实 |
| moneyFlow | 资金流事实；若源不足可 PARTIAL 或 UNAVAILABLE |
| limitUp | 涨跌停事实 |
| streakLadder | 连板天梯摘要 |
| topSectors | 首页板块榜 |
| stockLeaderboards | 首页个股榜，按榜单分组 |
| quickEntries | 首页快捷入口 |
| dataSources | 数据源状态 |


#### 异常状态


| code | 场景 | 前端处理 |
| --- | --- | --- |
| 400001 | tradeDate 格式错误 | 保留旧数据并提示 |
| 404001 | 指定交易日无数据 | 展示空状态 |
| 429001 | 首页频繁刷新 | 前端退避 |
| 500001 | 聚合服务异常 | 展示异常态 |
| 503001 | 核心行情源不可用 | 展示最近缓存或异常态 |


#### 空数据处理

模块级空数据使用空数组或 dataStatus 降级；资金流不可用时隐藏卡片或展示“资金流数据暂缺”。


#### 数据更新时间

核心行情 15-60 秒；板块 / 榜单 1-5 分钟；资金流 1-5 分钟；快捷入口低频。


#### 缓存建议

API Gateway 3-5 秒；服务端聚合缓存 10-15 秒；盘后缓存 1 天。


#### 性能评估

P95 < 350ms；Payload 控制 80KB 内；避免首页实时扫全表，使用预聚合表或内存快照。


#### 暂缺数据字段清单


- 实时资金分档：mainNetInflow、superLargeNetInflow、largeNetInflow
- 北向资金 northboundNetInflow
- 连板晋级率 promotionRate
- 完整 heatmap 树
- 实时换手率、量比


#### Mock 数据示例

上方 response JSON 可直接作为 02 HTML Showcase 首页 mock 根对象。



### 3.2 GET /api/market/overview


#### endpoint


```http
GET /api/market/overview
```


#### method

`GET`


#### 前端使用场景

首页顶部状态条：显示当前交易日、交易状态、更新时间、是否延迟、整体数据状态。


#### request params


| 参数 | 类型 | 必填 | 示例 | 说明 |
| --- | --- | --- | --- | --- |
| market | string | 否 | CN_A | 市场 |
| tradeDate | string(date) | 否 | 2026-04-28 | 交易日 |


#### response JSON

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "market": "CN_A",
    "tradeDate": "2026-04-28",
    "sessionStatus": "OPEN",
    "timezone": "Asia/Shanghai",
    "openTime": "2026-04-28T09:30:00+08:00",
    "closeTime": "2026-04-28T15:00:00+08:00",
    "prevTradeDate": "2026-04-27",
    "isDelayed": true,
    "dataStatus": "READY",
    "asOf": "2026-04-28T14:56:00+08:00"
  },
  "traceId": "req_20260428_000002",
  "serverTime": "2026-04-28T14:56:30+08:00"
}
```


#### 字段说明


| 字段 | 说明 |
| --- | --- |
| sessionStatus | 当前交易阶段 |
| isDelayed | 是否延迟行情 |
| dataStatus | 首页核心数据状态 |
| asOf | 行情数据截至时间 |


#### 异常状态


| code | 场景 | 前端处理 |
| --- | --- | --- |
| 400001 | 参数错误 | 提示参数错误 |
| 404001 | 交易日不存在 | 展示非交易日或空状态 |
| 500001 | 服务异常 | 重试 |
| 503001 | 交易日历源不可用 | 显示异常状态 |


#### 空数据处理

交易日不存在时返回 404001；非交易日返回 sessionStatus=HOLIDAY，不作为异常。


#### 数据更新时间

交易阶段每分钟刷新；交易日表每日刷新。


#### 缓存建议

交易日状态缓存 30 秒；非交易日缓存 1 小时。


#### 性能评估

P95 < 80ms；只读交易日历与状态缓存。


#### 暂缺数据字段清单


- 半日市
- 临时休市
- 交易所特殊公告状态


#### Mock 数据示例

使用 response JSON。



### 3.3 GET /api/index/summary


#### endpoint


```http
GET /api/index/summary
```


#### method

`GET`


#### 前端使用场景

首页指数卡片、市场风格模块、顶部行情条。


#### request params


| 参数 | 类型 | 必填 | 示例 | 说明 |
| --- | --- | --- | --- | --- |
| market | string | 否 | CN_A | 市场 |
| indexCodes | string | 否 | 000001.SH,399001.SZ,399006.SZ | 指数代码逗号分隔 |
| tradeDate | string(date) | 否 | 2026-04-28 | 交易日 |


#### response JSON

```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {
      "indexCode": "000001.SH",
      "indexName": "上证指数",
      "last": 3128.42,
      "prevClose": 3099.76,
      "open": 3108.91,
      "high": 3138.66,
      "low": 3098.12,
      "change": 28.66,
      "changePct": 0.92,
      "amount": 482300000000,
      "direction": "UP",
      "asOf": "2026-04-28T14:56:00+08:00"
    },
    {
      "indexCode": "399001.SZ",
      "indexName": "深证成指",
      "last": 9842.15,
      "prevClose": 9876.36,
      "open": 9890.23,
      "high": 9931.4,
      "low": 9788.15,
      "change": -34.21,
      "changePct": -0.35,
      "amount": 598400000000,
      "direction": "DOWN",
      "asOf": "2026-04-28T14:56:00+08:00"
    }
  ],
  "traceId": "req_20260428_000003",
  "serverTime": "2026-04-28T14:56:30+08:00"
}
```


#### 字段说明


| 字段 | 说明 |
| --- | --- |
| indexCode | 指数代码 |
| indexName | 指数名称 |
| last | 最新点位 / 收盘点位 |
| changePct | 涨跌幅 |
| direction | 涨跌方向，UP=红、DOWN=绿 |
| amount | 成交额 |
| asOf | 数据时间 |


#### 异常状态


| code | 场景 | 前端处理 |
| --- | --- | --- |
| 400001 | 指数代码非法 | 提示 |
| 404001 | 指数不存在 | 剔除或空状态 |
| 503001 | 指数行情源不可用 | 展示缓存或异常 |


#### 空数据处理

某个指数无数据时从数组中剔除并提示；全部无数据返回空数组。


#### 数据更新时间

盘中 15-60 秒；若仅日线源则盘后日更。


#### 缓存建议

盘中 10 秒；盘后 1 天。


#### 性能评估

P95 < 120ms；指数数量不超过 20。


#### 暂缺数据字段清单


- 实时指数成交额
- 指数分钟行情


#### Mock 数据示例

使用 response JSON。



### 3.4 GET /api/market/breadth


#### endpoint


```http
GET /api/market/breadth
```


#### method

`GET`


#### 前端使用场景

首页涨跌家数、红盘率、中位涨跌幅模块；情绪分析页市场广度区域。


#### request params


| 参数 | 类型 | 必填 | 示例 | 说明 |
| --- | --- | --- | --- | --- |
| market | string | 否 | CN_A | 市场 |
| tradeDate | string(date) | 否 | 2026-04-28 | 交易日 |
| samplePool | string | 否 | CN_A_COMMON | 样本池 |


#### response JSON

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "tradeDate": "2026-04-28",
    "samplePool": "CN_A_COMMON",
    "stockUniverseCount": 5128,
    "upCount": 3421,
    "downCount": 1488,
    "flatCount": 219,
    "redRate": 0.667,
    "medianChangePct": 0.48,
    "upGt3Pct": 0.142,
    "downGt3Pct": 0.041,
    "limitUpCount": 59,
    "limitDownCount": 8,
    "advancersDeclinersRatio": 2.3,
    "asOf": "2026-04-28T14:56:00+08:00"
  },
  "traceId": "req_20260428_000004",
  "serverTime": "2026-04-28T14:56:30+08:00"
}
```


#### 字段说明


| 字段 | 说明 |
| --- | --- |
| stockUniverseCount | 样本池股票数 |
| upCount/downCount/flatCount | 涨跌平家数 |
| redRate | 红盘率 |
| medianChangePct | 中位涨跌幅 |
| upGt3Pct/downGt3Pct | 涨跌超 3% 占比 |
| limitUpCount/limitDownCount | 涨跌停家数 |


#### 异常状态


| code | 场景 | 前端处理 |
| --- | --- | --- |
| 400001 | 样本池非法 | 提示 |
| 404001 | 无样本数据 | 空状态 |
| 503001 | 股票行情源不可用 | 异常态 |


#### 空数据处理

stockUniverseCount=0 时展示“暂无有效样本”。


#### 数据更新时间

盘中 15-60 秒；盘后固定。


#### 缓存建议

盘中 10-15 秒；盘后 1 天。


#### 性能评估

P95 < 150ms；后端应使用预计算市场快照，不应每次全市场扫描。


#### 暂缺数据字段清单


- isSuspended
- isST
- isDelisting
- limitPct
- listDate


#### Mock 数据示例

使用 response JSON。



### 3.5 GET /api/market/style


#### endpoint


```http
GET /api/market/style
```


#### method

`GET`


#### 前端使用场景

首页风格强弱模块，展示大盘 / 小盘、成长 / 价值等相对表现。


#### request params


| 参数 | 类型 | 必填 | 示例 | 说明 |
| --- | --- | --- | --- | --- |
| market | string | 否 | CN_A | 市场 |
| tradeDate | string(date) | 否 | 2026-04-28 | 交易日 |


#### response JSON

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "tradeDate": "2026-04-28",
    "largeCapIndexCode": "000300.SH",
    "smallCapIndexCode": "399303.SZ",
    "largeCapChangePct": 0.72,
    "smallCapChangePct": 1.48,
    "smallVsLargeSpreadPct": 0.76,
    "growthIndexCode": "399006.SZ",
    "valueIndexCode": "000016.SH",
    "growthChangePct": 1.21,
    "valueChangePct": 0.35,
    "styleLeader": "SMALL_CAP",
    "asOf": "2026-04-28T14:56:00+08:00"
  },
  "traceId": "req_20260428_000005",
  "serverTime": "2026-04-28T14:56:30+08:00"
}
```


#### 字段说明


| 字段 | 说明 |
| --- | --- |
| largeCapChangePct | 大盘代表指数涨跌幅 |
| smallCapChangePct | 小盘代表指数涨跌幅 |
| smallVsLargeSpreadPct | 小盘相对大盘强弱差 |
| styleLeader | 领先风格 |
| asOf | 数据时间 |


#### 异常状态


| code | 场景 | 前端处理 |
| --- | --- | --- |
| 404001 | 代表指数无数据 | 空状态 |
| 503001 | 指数行情源不可用 | 异常态 |


#### 空数据处理

成长 / 价值指数暂缺时，只返回大盘 / 小盘字段，前端隐藏成长价值行。


#### 数据更新时间

1-5 分钟；P0 可日频。


#### 缓存建议

盘中 30 秒；盘后 1 天。


#### 性能评估

P95 < 120ms；只依赖少量指数快照。


#### 暂缺数据字段清单


- 成长 / 价值代表指数口径
- 内部风格桶成分股口径


#### Mock 数据示例

使用 response JSON。



### 3.6 GET /api/market/turnover


#### endpoint


```http
GET /api/market/turnover
```


#### method

`GET`


#### 前端使用场景

首页成交额模块，展示全市场成交额、较昨日变化、相对 20 日量能、沪深北分市场成交额。


#### request params


| 参数 | 类型 | 必填 | 示例 | 说明 |
| --- | --- | --- | --- | --- |
| market | string | 否 | CN_A | 市场 |
| tradeDate | string(date) | 否 | 2026-04-28 | 交易日 |


#### response JSON

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "tradeDate": "2026-04-28",
    "totalAmount": 1052300000000,
    "prevTotalAmount": 982100000000,
    "amountChange": 70200000000,
    "amountChangePct": 7.15,
    "amount20dMedian": 936000000000,
    "amountRatio20dMedian": 1.12,
    "sseAmount": 438200000000,
    "szseAmount": 598400000000,
    "bseAmount": 15600000000,
    "asOf": "2026-04-28T14:56:00+08:00"
  },
  "traceId": "req_20260428_000006",
  "serverTime": "2026-04-28T14:56:30+08:00"
}
```


#### 字段说明


| 字段 | 说明 |
| --- | --- |
| totalAmount | 全市场成交额 |
| prevTotalAmount | 上一交易日成交额 |
| amountChangePct | 较昨日变化 |
| amountRatio20dMedian | 相对 20 日中位量能 |
| sseAmount/szseAmount/bseAmount | 分市场成交额 |


#### 异常状态


| code | 场景 | 前端处理 |
| --- | --- | --- |
| 404001 | 无成交额数据 | 空状态 |
| 503001 | 行情源不可用 | 异常态 |


#### 空数据处理

totalAmount 为 null 或 0 时展示“成交额暂不可用”，不要显示 0 亿误导用户。


#### 数据更新时间

盘中 15-60 秒；盘后固定。


#### 缓存建议

盘中 10-15 秒；盘后 1 天。


#### 性能评估

P95 < 150ms；必须使用全市场成交额预聚合，不要实时 sum 全量股票表。


#### 暂缺数据字段清单


- 北交所成交额
- 分板块成交额


#### Mock 数据示例

使用 response JSON。



### 3.7 GET /api/moneyflow/market


#### endpoint


```http
GET /api/moneyflow/market
```


#### method

`GET`


#### 前端使用场景

首页资金流事实摘要；资金面分析页入口数据。该接口只返回资金流事实，不返回资金面分数。


#### request params


| 参数 | 类型 | 必填 | 示例 | 说明 |
| --- | --- | --- | --- | --- |
| market | string | 否 | CN_A | 市场 |
| tradeDate | string(date) | 否 | 2026-04-28 | 交易日 |


#### response JSON

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "tradeDate": "2026-04-28",
    "netInflow": -5280000000,
    "mainNetInflow": -8120000000,
    "superLargeNetInflow": -3200000000,
    "largeNetInflow": -4920000000,
    "mediumNetInflow": 2100000000,
    "smallNetInflow": 6020000000,
    "northboundNetInflow": null,
    "dataStatus": "PARTIAL",
    "asOf": "2026-04-28T14:55:00+08:00"
  },
  "traceId": "req_20260428_000007",
  "serverTime": "2026-04-28T14:56:30+08:00"
}
```


#### 字段说明


| 字段 | 说明 |
| --- | --- |
| netInflow | 全市场净流入 |
| mainNetInflow | 主力净流入 |
| superLargeNetInflow/largeNetInflow | 超大单 / 大单净流入 |
| mediumNetInflow/smallNetInflow | 中单 / 小单净流入 |
| dataStatus | 资金流数据状态 |


#### 异常状态


| code | 场景 | 前端处理 |
| --- | --- | --- |
| 404001 | 指定交易日无资金流数据 | 空状态 |
| 503001 | 资金流源不可用 | 返回 UNAVAILABLE 或异常态 |


#### 空数据处理

资金流源不可用时返回 {dataStatus:'UNAVAILABLE', asOf:null}，前端隐藏或显示“资金流数据暂缺”。


#### 数据更新时间

1-5 分钟，取决于数据源。


#### 缓存建议

盘中 30-60 秒；盘后 1 天。


#### 性能评估

P95 < 180ms；第三方资金流应异步同步入库，不要首页请求直连第三方。


#### 暂缺数据字段清单


- 主力净流入
- 超大单
- 大单
- 中单
- 小单
- 北向资金


#### Mock 数据示例

准备 PARTIAL 和 UNAVAILABLE 两套 mock。



### 3.8 GET /api/limitup/summary


#### endpoint


```http
GET /api/limitup/summary
```


#### method

`GET`


#### 前端使用场景

首页涨跌停摘要卡片，情绪分析页涨跌停模块。


#### request params


| 参数 | 类型 | 必填 | 示例 | 说明 |
| --- | --- | --- | --- | --- |
| market | string | 否 | CN_A | 市场 |
| tradeDate | string(date) | 否 | 2026-04-28 | 交易日 |
| samplePool | string | 否 | CN_A_COMMON | 样本池 |


#### response JSON

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "tradeDate": "2026-04-28",
    "limitUpCount": 59,
    "limitDownCount": 8,
    "touchedLimitUpCount": 86,
    "failedLimitUpCount": 27,
    "sealRate": 0.686,
    "oneWordLimitUpCount": 7,
    "tradableLimitUpCount": 52,
    "highestStreak": 6,
    "firstBoardCount": 42,
    "secondBoardCount": 8,
    "asOf": "2026-04-28T14:56:00+08:00"
  },
  "traceId": "req_20260428_000008",
  "serverTime": "2026-04-28T14:56:30+08:00"
}
```


#### 字段说明


| 字段 | 说明 |
| --- | --- |
| limitUpCount/limitDownCount | 涨跌停数 |
| touchedLimitUpCount | 触板数 |
| failedLimitUpCount | 炸板数 |
| sealRate | 封板率 |
| highestStreak | 最高连板高度 |
| firstBoardCount/secondBoardCount | 首板 / 二板数量 |


#### 异常状态


| code | 场景 | 前端处理 |
| --- | --- | --- |
| 400001 | 样本池错误 | 提示 |
| 503001 | 行情源或涨跌停规则不可用 | 异常态 |


#### 空数据处理

无涨停时返回 limitUpCount=0，不返回空对象。规则数据不可用时返回 503001。


#### 数据更新时间

15-60 秒；盘后固定。


#### 缓存建议

盘中 10-15 秒；盘后 1 天。


#### 性能评估

P95 < 150ms；涨跌停价格应提前写入交易参考表。


#### 暂缺数据字段清单


- oneWordLimitUpCount
- tradableLimitUpCount
- 炸板依赖 open/high/low/close/upLimitPrice


#### Mock 数据示例

使用 response JSON。



### 3.9 GET /api/limitup/streak-ladder


#### endpoint


```http
GET /api/limitup/streak-ladder
```


#### method

`GET`


#### 前端使用场景

首页连板天梯摘要；情绪分析页完整连板天梯。


#### request params


| 参数 | 类型 | 必填 | 示例 | 说明 |
| --- | --- | --- | --- | --- |
| market | string | 否 | CN_A | 市场 |
| tradeDate | string(date) | 否 | 2026-04-28 | 交易日 |
| minStreak | integer | 否 | 2 | 最小连板高度 |
| limitPerLevel | integer | 否 | 5 | 每个高度最多返回股票数 |


#### response JSON

```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {
      "tradeDate": "2026-04-28",
      "streak": 6,
      "count": 1,
      "highestStreak": 6,
      "stocks": [
        {
          "stockCode": "002888.SZ",
          "stockName": "示例股份",
          "changePct": 10.01,
          "direction": "UP",
          "sectorName": "机器人",
          "amount": 920000000
        }
      ],
      "asOf": "2026-04-28T14:56:00+08:00"
    },
    {
      "tradeDate": "2026-04-28",
      "streak": 3,
      "count": 5,
      "highestStreak": 6,
      "stocks": [],
      "asOf": "2026-04-28T14:56:00+08:00"
    }
  ],
  "traceId": "req_20260428_000009",
  "serverTime": "2026-04-28T14:56:30+08:00"
}
```


#### 字段说明


| 字段 | 说明 |
| --- | --- |
| streak | 连板高度 |
| count | 该高度股票数量 |
| stocks | 股票列表 |
| highestStreak | 最高连板高度 |
| asOf | 数据时间 |


#### 异常状态


| code | 场景 | 前端处理 |
| --- | --- | --- |
| 400001 | 参数错误 | 提示 |
| 503001 | 涨停历史链路不可用 | 异常态 |


#### 空数据处理

无连板时返回空数组，展示“今日暂无连板股”。


#### 数据更新时间

1-5 分钟；盘后固定。


#### 缓存建议

盘中 30 秒；盘后 1 天。


#### 性能评估

P95 < 180ms；需要预计算当日连板高度，不建议请求时递归回查历史。


#### 暂缺数据字段清单


- promotionRate
- breakCount
- 昨日连板池断板明细


#### Mock 数据示例

使用 response JSON。



### 3.10 GET /api/sector/top


#### endpoint


```http
GET /api/sector/top
```


#### method

`GET`


#### 前端使用场景

首页板块涨幅榜、成交额榜、主线候选榜；板块轮动页可复用。


#### request params


| 参数 | 类型 | 必填 | 示例 | 说明 |
| --- | --- | --- | --- | --- |
| market | string | 否 | CN_A | 市场 |
| tradeDate | string(date) | 否 | 2026-04-28 | 交易日 |
| sectorType | string | 否 | CONCEPT | INDUSTRY / CONCEPT / STYLE |
| rankBy | string | 否 | changePct | changePct / amount / mainNetInflow / redRate |
| direction | string | 否 | desc | 排序方向 |
| limit | integer | 否 | 10 | 返回数量 |


#### response JSON

```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {
      "rank": 1,
      "sectorId": "BK0421",
      "sectorName": "储能",
      "sectorType": "CONCEPT",
      "changePct": 3.86,
      "direction": "UP",
      "redRate": 0.82,
      "riseCount": 63,
      "fallCount": 12,
      "amount": 128600000000,
      "amountRatio20dMedian": 1.45,
      "mainNetInflow": 2630000000,
      "leadingStockCode": "300750.SZ",
      "leadingStockName": "宁德时代",
      "leadingStockChangePct": 5.82
    }
  ],
  "traceId": "req_20260428_000010",
  "serverTime": "2026-04-28T14:56:30+08:00"
}
```


#### 字段说明


| 字段 | 说明 |
| --- | --- |
| rank | 排名 |
| sectorId/sectorName/sectorType | 板块标识 |
| changePct/direction | 涨跌幅与方向 |
| redRate | 板块红盘率 |
| amount | 板块成交额 |
| leadingStock* | 领涨股票信息 |


#### 异常状态


| code | 场景 | 前端处理 |
| --- | --- | --- |
| 400001 | 参数非法 | 提示 |
| 404001 | 板块体系无数据 | 空状态 |
| 503001 | 板块计算服务不可用 | 异常态 |


#### 空数据处理

返回空数组，展示“暂无板块数据”。


#### 数据更新时间

1-5 分钟；P0 可日频。


#### 缓存建议

盘中 30 秒；盘后 1 天。


#### 性能评估

P95 < 200ms；板块聚合需预计算，不应每次实时 join 全量成分股。


#### 暂缺数据字段清单


- 板块资金流
- 板块 20 日成交额中位
- 动态概念成分有效期


#### Mock 数据示例

使用 response JSON。



### 3.11 GET /api/leaderboard/stock


#### endpoint


```http
GET /api/leaderboard/stock
```


#### method

`GET`


#### 前端使用场景

首页个股榜单：涨幅榜、跌幅榜、成交额榜、换手榜、涨停榜。


#### request params


| 参数 | 类型 | 必填 | 示例 | 说明 |
| --- | --- | --- | --- | --- |
| market | string | 否 | CN_A | 市场 |
| tradeDate | string(date) | 否 | 2026-04-28 | 交易日 |
| rankType | string | 是 | GAINER | GAINER / LOSER / AMOUNT / TURNOVER / VOLUME_RATIO / LIMIT_UP |
| limit | integer | 否 | 10 | 返回数量 |
| excludeST | boolean | 否 | true | 是否剔除 ST |


#### response JSON

```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {
      "rank": 1,
      "rankType": "GAINER",
      "stockCode": "300123.SZ",
      "stockName": "示例科技",
      "price": 18.36,
      "changePct": 20.01,
      "direction": "UP",
      "amount": 3280000000,
      "volume": 182000000,
      "turnoverRate": 18.4,
      "volumeRatio": 2.8,
      "sectorName": "半导体",
      "isLimitUp": true,
      "isLimitDown": false,
      "asOf": "2026-04-28T14:56:00+08:00"
    }
  ],
  "traceId": "req_20260428_000011",
  "serverTime": "2026-04-28T14:56:30+08:00"
}
```


#### 字段说明


| 字段 | 说明 |
| --- | --- |
| rank/rankType | 排名与榜单类型 |
| stockCode/stockName | 股票标识 |
| price/changePct/direction | 价格、涨跌幅与颜色方向 |
| amount/volume | 成交额与成交量 |
| turnoverRate/volumeRatio | 换手率与量比，可为空 |
| isLimitUp/isLimitDown | 涨跌停标记 |


#### 异常状态


| code | 场景 | 前端处理 |
| --- | --- | --- |
| 400001 | 榜单类型非法 | 提示 |
| 503001 | 个股行情源不可用 | 异常态 |


#### 空数据处理

返回空数组，前端展示对应榜单空状态。


#### 数据更新时间

15-60 秒；榜单刷新可 30 秒。


#### 缓存建议

盘中 15-30 秒；盘后 1 天。


#### 性能评估

P95 < 180ms；建议维护榜单快照表或 Redis sorted set。


#### 暂缺数据字段清单


- 实时换手率
- 量比
- 市值
- 分钟涨速榜


#### Mock 数据示例

使用 response JSON；跌幅榜必须包含 direction=DOWN 并渲染绿色。



### 3.12 GET /api/settings/quick-entry


#### endpoint


```http
GET /api/settings/quick-entry
```


#### method

`GET`


#### 前端使用场景

首页快捷入口配置：市场温度与情绪、资金面、板块轮动、自选、持仓、交易计划等。


#### request params


| 参数 | 类型 | 必填 | 示例 | 说明 |
| --- | --- | --- | --- | --- |
| scene | string | 否 | HOME | 使用场景 |
| userId | string | 否 | u_1001 | 已登录用户可个性化；游客返回默认配置 |


#### response JSON

```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {
      "key": "market-emotion",
      "title": "市场温度与情绪",
      "route": "/market/emotion",
      "description": "查看温度、情绪、风险等分析页",
      "icon": "pulse",
      "enabled": true,
      "sortOrder": 10,
      "badge": null
    },
    {
      "key": "watchlist",
      "title": "自选",
      "route": "/watchlist",
      "description": "跟踪自选股表现",
      "icon": "star",
      "enabled": true,
      "sortOrder": 20,
      "badge": null
    },
    {
      "key": "positions",
      "title": "持仓",
      "route": "/positions",
      "description": "查看手工登记持仓",
      "icon": "briefcase",
      "enabled": true,
      "sortOrder": 30,
      "badge": "手工"
    }
  ],
  "traceId": "req_20260428_000012",
  "serverTime": "2026-04-28T14:56:30+08:00"
}
```


#### 字段说明


| 字段 | 说明 |
| --- | --- |
| key | 入口唯一 key |
| title | 展示名称 |
| route | 前端路由 |
| description | 说明 |
| icon | 图标 key，由组件库映射 |
| enabled | 是否启用 |
| sortOrder | 排序 |
| badge | 角标，可为空 |


#### 异常状态


| code | 场景 | 前端处理 |
| --- | --- | --- |
| 401001 | 个性化配置需要登录但未登录 | 游客模式返回默认配置，不应阻塞首页 |
| 500001 | 配置服务异常 | 回退默认配置 |


#### 空数据处理

返回默认配置，不建议首页快捷入口为空。


#### 数据更新时间

低频，配置发布时更新。


#### 缓存建议

浏览器本地缓存 1 天；服务端缓存 5 分钟。


#### 性能评估

P95 < 80ms。


#### 暂缺数据字段清单


- 用户自定义入口排序
- 权限灰度
- 未读角标数量


#### Mock 数据示例

使用 response JSON。



---

## 4. 首页模块接口汇总

| 接口 | 首页首屏必需 | 可独立刷新 | 推荐缓存 | P95 目标 |
|---|---:|---:|---|---:|
| `/api/market/home-overview` | 是 | 是 | 10-15 秒 | `<350ms` |
| `/api/market/overview` | 是 | 是 | 30 秒 | `<80ms` |
| `/api/index/summary` | 是 | 是 | 10 秒 | `<120ms` |
| `/api/market/breadth` | 是 | 是 | 10-15 秒 | `<150ms` |
| `/api/market/style` | 是 | 是 | 30 秒 | `<120ms` |
| `/api/market/turnover` | 是 | 是 | 10-15 秒 | `<150ms` |
| `/api/moneyflow/market` | 否 | 是 | 30-60 秒 | `<180ms` |
| `/api/limitup/summary` | 是 | 是 | 10-15 秒 | `<150ms` |
| `/api/limitup/streak-ladder` | 是 | 是 | 30 秒 | `<180ms` |
| `/api/sector/top` | 是 | 是 | 30 秒 | `<200ms` |
| `/api/leaderboard/stock` | 是 | 是 | 15-30 秒 | `<180ms` |
| `/api/settings/quick-entry` | 是 | 否 | 5 分钟 | `<80ms` |

---

## 5. 首页 API 推荐方案：聚合接口优先还是模块接口优先

推荐：**聚合接口优先，模块接口保留**。

1. 首页首屏：`GET /api/market/home-overview`。
2. 模块懒加载 / 局部刷新：调用对应模块接口。
3. 数据源异常：聚合接口允许某些模块 `dataStatus=UNAVAILABLE`，但不要让资金流或热力图失败拖垮首页。
4. 后续页面复用：板块页、情绪分析页、个股榜单页使用模块接口。

---

## 6. P0 已具备数据字段

> 说明：此处按“可由基础行情、交易日历、日线、指数、板块映射直接计算”的角度标记，具体仍需后端实际库表核验。

1. 交易日：`tradeDate`、`prevTradeDate`、`isTradingDay`、`sessionStatus`。
2. 指数行情：`indexCode`、`indexName`、`last`、`prevClose`、`change`、`changePct`、`amount`。
3. 个股行情：`stockCode`、`stockName`、`open`、`high`、`low`、`close/lastPrice`、`prevClose`、`volume`、`amount`。
4. 市场广度：`upCount`、`downCount`、`flatCount`、`redRate`、`medianChangePct`。
5. 成交额：`totalAmount`、`amountChangePct`、`amountRatio20dMedian`。
6. 涨跌停：在具备涨跌停价后可计算 `limitUpCount`、`limitDownCount`、`touchedLimitUpCount`、`failedLimitUpCount`。
7. 板块榜：在具备板块成分映射后可计算 `changePct`、`amount`、`redRate`。
8. 自选 / 持仓 / 计划 / 提醒：用户手工数据可先落地。

---

## 7. P0 暂缺数据字段

1. 资金流分档：主力、超大单、大单、中单、小单。
2. 北向资金净流入。
3. 实时换手率、量比、流通市值。
4. 连板晋级率、断板数、昨日连板池延续情况。
5. 高位崩塌率。
6. 盘中分钟级涨速榜。
7. 完整热力图树和内部主题映射版本。
8. 资金面分数、风险分数、情绪分数的正式模型版本；这些不属于首页核心 API。

---

## 8. 需要数据基座补充的字段

| 数据表 / 能力 | 字段 |
|---|---|
| 交易参考表 | `trade_date`、`stock_code`、`up_limit_price`、`down_limit_price`、`limit_pct`、`is_suspended`、`is_no_price_limit` |
| 股票基础表 | `stock_code`、`stock_name`、`exchange`、`list_date`、`is_st`、`is_delisting`、`board`、`total_share`、`float_share` |
| 行情快照表 | `open`、`high`、`low`、`last`、`prev_close`、`volume`、`amount`、`as_of` |
| 指数快照表 | `index_code`、`last`、`prev_close`、`amount`、`as_of` |
| 板块映射表 | `sector_id`、`sector_name`、`sector_type`、`stock_code`、`effective_start_date`、`effective_end_date` |
| 市场统计快照表 | `up_count`、`down_count`、`flat_count`、`red_rate`、`median_change_pct`、`total_amount` |
| 涨跌停快照表 | `limit_up_count`、`limit_down_count`、`touched_limit_up_count`、`failed_limit_up_count`、`streak` |
| 数据源状态表 | `source_id`、`domain`、`status`、`latest_data_time`、`completeness_pct`、`error_code` |

---

## 9. 给 02 HTML Showcase 的 Mock 数据建议

1. 直接使用 `GET /api/market/home-overview` 的 response 作为首页 mock 根对象。
2. HTML 内部 mock 命名建议：

```js
const mockHomeOverview = {
  overview: {},
  indices: [],
  breadth: {},
  style: {},
  turnover: {},
  moneyFlow: {},
  limitUp: {},
  streakLadder: [],
  topSectors: [],
  stockLeaderboards: {},
  quickEntries: [],
  dataSources: []
};
```

3. 必须体现红涨绿跌：
   - `direction: "UP"` 使用红色。
   - `direction: "DOWN"` 使用绿色。
   - `direction: "FLAT"` 使用灰色。
4. 首页不要出现“市场温度 68 分”“情绪分 62”“风险分 38”这类核心评分，只出现“市场温度与情绪分析”快捷入口。
5. 可在数据源状态处展示“资金流数据部分可用”，体现降级能力。
6. 板块榜建议 mock 8 条，个股榜建议每组 6-10 条，连板天梯展示 2-6 板即可。

---

## 10. 给 03 组件库的字段映射建议

| 组件 | 使用接口 | 字段映射 |
|---|---|---|
| `HomeOverviewPage` | `/api/market/home-overview` | 根聚合对象 |
| `MarketStatusBar` | `/api/market/overview` | `sessionStatus`、`asOf`、`dataStatus`、`isDelayed` |
| `IndexCardGroup` | `/api/index/summary` | `indices[]` |
| `BreadthPanel` | `/api/market/breadth` | `upCount`、`downCount`、`flatCount`、`redRate` |
| `StyleStrengthPanel` | `/api/market/style` | `largeCapChangePct`、`smallCapChangePct`、`styleLeader` |
| `TurnoverPanel` | `/api/market/turnover` | `totalAmount`、`amountChangePct`、`amountRatio20dMedian` |
| `MoneyFlowPanel` | `/api/moneyflow/market` | `mainNetInflow`、`dataStatus` |
| `LimitUpPanel` | `/api/limitup/summary` | `limitUpCount`、`limitDownCount`、`sealRate`、`highestStreak` |
| `StreakLadderMini` | `/api/limitup/streak-ladder` | `streak`、`count`、`stocks[]` |
| `SectorTopTable` | `/api/sector/top` | `rank`、`sectorName`、`changePct`、`redRate`、`amount` |
| `StockLeaderboardTabs` | `/api/leaderboard/stock` | `rankType`、`stockName`、`price`、`changePct`、`amount` |
| `QuickEntryGrid` | `/api/settings/quick-entry` | `key`、`title`、`route`、`icon`、`badge` |

---

## 11. 待产品总控确认问题

1. 首页是否允许展示“资金流事实摘要”？建议可以展示，但如果数据源不足必须允许隐藏。
2. 首页顶部是否展示“行情延迟”标签？建议必须展示。
3. 板块体系 P0 用申万行业、概念板块，还是内部主题？建议先行业 + 概念双榜。
4. 首页个股榜单保留几个 Tab？建议 P0：涨幅、跌幅、成交额、涨停。
5. 是否需要游客态首页？建议需要，首页行情无须登录；自选 / 持仓 / 计划需要登录。
6. 是否允许首页快捷入口显示情绪页角标？建议 v0.1 不显示分数角标，避免违背“首页客观事实驾驶舱”定位。
7. P0 是先盘后日频还是盘中延迟行情？建议 API 按盘中延迟行情设计，数据源不足时降级。
8. 是否在 response 中加入 `warnings` 数组？建议 v0.2 可加入，用于模块级降级提示。

---

## 23. v0.2 首页接口字段来源映射补充

### 23.1 `/api/market/home-overview` 聚合字段来源

| response 字段 | 业务对象 | 推荐来源 |
|---|---|---|
| `overview.tradeDate` | `TradingDay` | `trade_cal.cal_date` |
| `overview.isTradingDay` | `TradingDay` | `trade_cal.is_open` |
| `indices[].last` | `IndexSnapshot` | `index_daily.close` |
| `indices[].amount` | `IndexSnapshot` | `index_daily.amount * 1000` |
| `breadth.upCount/downCount/flatCount` | `MarketBreadth` | `daily.pct_chg` 聚合 |
| `breadth.medianChangePct` | `MarketBreadth` | `median(daily.pct_chg)` |
| `turnover.totalAmount` | `TurnoverSummary` | `sum(daily.amount * 1000)` |
| `moneyFlow.mainNetInflow` | `MoneyFlowSummary` | `moneyflow_mkt_dc.net_amount` |
| `moneyFlow.superLargeNetInflow` | `MoneyFlowSummary` | `moneyflow_mkt_dc.buy_elg_amount` |
| `limitUp.limitUpCount` | `LimitUpSummary` | `count(limit_list_d.limit = "U")` |
| `limitUp.limitDownCount` | `LimitUpSummary` | `count(limit_list_d.limit = "D")` |
| `limitUp.failedLimitUpCount` | `LimitUpSummary` | `count(limit_list_d.limit = "Z")` |
| `limitUp.highestStreak` | `LimitUpSummary` | `max(limit_list_d.limit_times)` |
| `streakLadder[].stocks[].openTimes` | `LimitUpStreakLadder` | `limit_list_d.open_times` |
| `topSectors[].changePct` | `SectorRankItem` | `sw_daily.pct_change` 或 `moneyflow_ind_dc.pct_change` |
| `topSectors[].amount` | `SectorRankItem` | `sw_daily.amount * 10000` |
| `topSectors[].mainNetInflow` | `SectorRankItem` | `moneyflow_ind_dc.net_amount` |
| `stockLeaderboards[].price` | `StockRankItem` | `daily.close` |
| `stockLeaderboards[].amount` | `StockRankItem` | `daily.amount * 1000` |
| `stockLeaderboards[].turnoverRate` | `StockRankItem` | `daily_basic.turnover_rate` |
| `stockLeaderboards[].marketCap` | `StockRankItem` | `daily_basic.total_mv * 10000` |

### 23.2 v0.2 推荐 response 扩展示例

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "overview": {
      "market": "CN_A",
      "tradeDate": "2026-04-28",
      "sessionStatus": "CLOSED",
      "dataStatus": "READY",
      "sourceRefs": [
        {"dataset": "trade_cal", "docId": 26, "latestTradeDate": "2026-04-28", "normalized": true}
      ]
    },
    "moneyFlow": {
      "mainNetInflow": -8120000000,
      "superLargeNetInflow": -3200000000,
      "dataStatus": "READY",
      "sourceRefs": [
        {"dataset": "moneyflow_mkt_dc", "docId": 345, "latestTradeDate": "2026-04-28", "normalized": true}
      ]
    },
    "limitUp": {
      "limitUpCount": 59,
      "limitDownCount": 8,
      "failedLimitUpCount": 27,
      "highestStreak": 6,
      "dataScopeNote": "limit_list_d 不含 ST 股票统计",
      "sourceRefs": [
        {"dataset": "limit_list_d", "docId": 298, "latestTradeDate": "2026-04-28", "normalized": true}
      ]
    }
  },
  "traceId": "req_20260428_000001",
  "serverTime": "2026-04-28T17:12:00+08:00"
}
```

### 23.3 每个 API 的 v0.2 统一性能建议

| API | 推荐读取对象 | P95 目标 | 缓存建议 |
|---|---|---:|---|
| `/api/market/home-overview` | 多个 `wealth_*_snapshot` | `<350ms` | 盘中 60 秒，盘后 1 天 |
| `/api/index/summary` | `wealth_index_snapshot_view` | `<120ms` | 盘后 1 天 |
| `/api/market/breadth` | `wealth_market_breadth_snapshot` | `<150ms` | 盘后 1 天 |
| `/api/market/turnover` | `wealth_turnover_summary_snapshot` | `<150ms` | 盘后 1 天 |
| `/api/moneyflow/market` | `wealth_moneyflow_market_snapshot` | `<150ms` | 盘后 1 天 |
| `/api/limitup/summary` | `wealth_limitup_snapshot` | `<150ms` | 盘后 1 天 |
| `/api/sector/top` | `wealth_sector_rank_snapshot` | `<200ms` | 盘后 1 天 |
| `/api/leaderboard/stock` | `wealth_stock_rank_snapshot` | `<180ms` | 盘后 1 天 |

### 23.4 v0.2 明确不进入首页核心 response 的字段

以下字段属于“市场温度与情绪分析页”或后续探查页，不进入首页核心结论：

1. `MarketTemperature.score`
2. `MarketSentiment.score`
3. `RiskIndex.riskScore`
4. `fundScore` / `moneyFlowScore`
5. `OpportunitySignal.strengthScore` 作为荐股式首页结论

首页只可通过 `quickEntries` 暴露“市场温度与情绪”“机会雷达”等入口。
