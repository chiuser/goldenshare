# 财势乾坤｜市场总览 API 草案 v0.3

建议路径：`/docs/wealth/api/market-overview-api.md`  
负责人：`04_API 契约与数据字典`  
版本：`v0.3`  
日期：`2026-05-06`  
状态：Audit 修订稿

---

## 0. 本轮审计结论

本版以市场总览 PRD 为上游约束，重新收敛 API 到“市场总览开发落地”所需范围：

1. 推荐使用 `GET /api/market/home-overview` 作为首屏聚合接口。
2. 模块接口保留，用于局部刷新、页面下钻和复用。
3. 聚合接口必须覆盖 `TopMarketBar`、`Breadcrumb`、`ShortcutBar`。
4. 首页不返回市场温度、市场情绪、资金面分数、风险指数等主观分数字段。
5. 行业/概念/地域板块使用 `dc_index + dc_member + dc_daily`，板块资金补充 `moneyflow_ind_dc`。
6. 首页榜单使用 `dc_hot`。

---

## 1. API 统一规则

### 1.1 统一响应结构

```json
{
  "code": 0,
  "message": "ok",
  "data": {},
  "traceId": "req_20260428_000001",
  "serverTime": "2026-04-28T09:30:00+08:00"
}
```

### 1.2 错误码

| code | 含义 | HTTP 建议 | 前端处理 |
|---:|---|---:|---|
| `0` | 成功 | 200 | 正常渲染。 |
| `400001` | 参数错误 | 400 | 提示筛选条件错误。 |
| `401001` | 未登录 | 401 | 市场总览基础行情可游客态；用户状态降级。 |
| `403001` | 无权限 | 403 | 展示权限提示。 |
| `404001` | 数据不存在 | 404 | 展示空状态。 |
| `409001` | 状态冲突 | 409 | 如非交易日请求盘中模式，提示切换最近交易日。 |
| `429001` | 请求过快 | 429 | 降频重试。 |
| `500001` | 服务异常 | 500 | 异常态 + 重试。 |
| `503001` | 数据源不可用 | 503 | 使用最近缓存或模块降级。 |

### 1.3 禁止字段

市场总览聚合接口和模块接口不得把以下字段作为首页核心展示字段返回：

```text
marketTemperatureScore
marketSentimentScore
capitalScore
riskIndexScore
buySuggestion
sellSuggestion
positionSuggestion
tomorrowPrediction
subjectiveMarketConclusion
```

### 1.4 单位与字段口径

API 字段使用业务命名，但单位默认保持 Tushare / PostgreSQL 落库口径。前端展示层负责格式化，不要求后端统一换算为元、股。

---

## 2. 推荐接口策略

| 场景 | 推荐接口 | 说明 |
|---|---|---|
| 页面首屏加载 | `GET /api/market/home-overview` | 一次性返回主要模块数据，减少请求瀑布。 |
| 模块局部刷新 | 对应模块接口 | 例如只刷新涨跌停或板块榜。 |
| 下钻页面复用 | 对应模块接口 | 板块页、榜单页、情绪页复用事实字段。 |
| 数据源异常 | 聚合接口模块级降级 | 非核心模块不可拖垮整页。 |

---

## 3. GET /api/market/home-overview

### endpoint

```http
GET /api/market/home-overview
```

### method

`GET`

### 前端使用场景

市场总览首屏和主要模块一次性加载。必须覆盖：`tradingDay`、`dataStatus`、`topMarketBar`、`breadcrumb`、`quickEntries`、`marketSummary`、`indices`、`breadth`、`style`、`turnover`、`moneyFlow`、`limitUp`、`limitUpDistribution`、`streakLadder`、`sectorOverview`、`leaderboards`。

### request params

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---:|---|---|
| `market` | string | 否 | `CN_A` | P0 固定 A 股。 |
| `tradeDate` | string(date) | 否 | 最近交易日 | 指定交易日。 |
| `dataMode` | enum | 否 | `latest` | `latest` / `eod` / `replay`。 |
| `sectorType` | enum | 否 | `ALL` | `INDUSTRY` / `CONCEPT` / `REGION` / `ALL`。 |
| `sectorLimit` | integer | 否 | `8` | 每组板块榜数量。 |
| `leaderboardLimit` | integer | 否 | `10` | 热榜返回数量。 |
| `includeHistory` | boolean | 否 | `true` | 是否返回历史成交额/资金流/涨跌家数曲线。 |

### response JSON / Mock 数据示例

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "tradingDay": {
      "tradeDate": "2026-04-28",
      "market": "CN_A",
      "isTradingDay": true,
      "sessionStatus": "CLOSED",
      "prevTradeDate": "2026-04-27"
    },
    "dataStatus": [
      {
        "sourceId": "tushare_dc_daily",
        "dataset": "dc_daily",
        "tableName": "raw_tushare.dc_daily",
        "dataDomain": "SECTOR",
        "status": "READY",
        "latestTradeDate": "2026-04-28",
        "completenessPct": 99.2
      }
    ],
    "topMarketBar": {
      "brandName": "财势乾坤",
      "activeSystemKey": "quote",
      "globalEntries": [
        {
          "key": "quote",
          "title": "乾坤行情",
          "route": "/market/overview",
          "active": true,
          "enabled": true
        },
        {
          "key": "insight",
          "title": "财势探查",
          "route": "/market/emotion",
          "active": false,
          "enabled": true
        }
      ],
      "indexTickers": [
        {
          "indexCode": "000001.SH",
          "indexName": "上证指数",
          "last": 3128.42,
          "changePct": 0.92,
          "direction": "UP"
        },
        {
          "indexCode": "399001.SZ",
          "indexName": "深证成指",
          "last": 9842.15,
          "changePct": -0.35,
          "direction": "DOWN"
        }
      ],
      "userShortcutStatus": {
        "watchCount": 18,
        "positionCount": 5,
        "activeAlertCount": 12,
        "unreadAlertCount": 2
      }
    },
    "breadcrumb": [
      {
        "label": "财势乾坤",
        "route": "/",
        "current": false
      },
      {
        "label": "乾坤行情",
        "route": "/market",
        "current": false
      },
      {
        "label": "市场总览",
        "route": "/market/overview",
        "current": true
      }
    ],
    "quickEntries": [
      {
        "key": "market-emotion",
        "title": "市场温度与情绪",
        "route": "/market/emotion",
        "enabled": true,
        "pendingCount": 0,
        "hasUpdate": true
      },
      {
        "key": "opportunity-radar",
        "title": "机会雷达",
        "route": "/opportunity/radar",
        "enabled": true,
        "pendingCount": 3,
        "hasUpdate": true
      },
      {
        "key": "watchlist",
        "title": "我的自选",
        "route": "/watchlist",
        "enabled": true,
        "pendingCount": 18,
        "hasUpdate": false
      },
      {
        "key": "positions",
        "title": "我的持仓",
        "route": "/positions",
        "enabled": true,
        "pendingCount": 5,
        "hasUpdate": true
      },
      {
        "key": "alerts",
        "title": "提醒中心",
        "route": "/alerts",
        "enabled": true,
        "pendingCount": 2,
        "hasUpdate": true
      }
    ],
    "marketSummary": {
      "title": "A股市场事实概览",
      "facts": [
        {
          "label": "上涨家数",
          "value": 3421
        },
        {
          "label": "下跌家数",
          "value": 1488
        },
        {
          "label": "涨停",
          "value": 59
        },
        {
          "label": "炸板",
          "value": 27
        }
      ],
      "forbiddenConclusion": true
    },
    "indices": [
      {
        "indexCode": "000001.SH",
        "indexName": "上证指数",
        "last": 3128.42,
        "prevClose": 3099.76,
        "change": 28.66,
        "changePct": 0.92,
        "amount": 482300000,
        "direction": "UP"
      },
      {
        "indexCode": "399001.SZ",
        "indexName": "深证成指",
        "last": 9842.15,
        "prevClose": 9876.36,
        "change": -34.21,
        "changePct": -0.35,
        "amount": 598400000,
        "direction": "DOWN"
      }
    ],
    "breadth": {
      "samplePool": "CN_A_COMMON",
      "stockUniverseCount": 5128,
      "upCount": 3421,
      "downCount": 1488,
      "flatCount": 219,
      "redRate": 0.667,
      "medianChangePct": 0.48,
      "distribution": [
        {
          "bucketKey": "GT_5",
          "bucketName": "涨超5%",
          "count": 186,
          "direction": "UP"
        },
        {
          "bucketKey": "LT_-5",
          "bucketName": "跌超5%",
          "count": 72,
          "direction": "DOWN"
        }
      ]
    },
    "style": {
      "largeCapIndexCode": "000300.SH",
      "smallCapIndexCode": "000852.SH",
      "largeCapChangePct": 0.72,
      "smallCapChangePct": 1.48,
      "smallVsLargeSpreadPct": 0.76,
      "styleLeader": "SMALL_CAP"
    },
    "turnover": {
      "totalAmount": 1052300000,
      "prevTotalAmount": 982100000,
      "amountChange": 70200000,
      "amountChangePct": 7.15,
      "amount20dMedian": 936000000,
      "amountRatio20dMedian": 1.12,
      "history": [
        {
          "tradeDate": "2026-04-28",
          "totalAmount": 1052300000,
          "amountChangePct": 7.15
        }
      ]
    },
    "moneyFlow": {
      "mainNetInflow": -8120000000,
      "mainNetInflowRate": -1.12,
      "superLargeAmount": -3200000000,
      "largeAmount": -4920000000,
      "mediumAmount": 2100000000,
      "smallAmount": 6020000000,
      "history": [
        {
          "tradeDate": "2026-04-28",
          "mainNetInflow": -8120000000,
          "mainNetInflowRate": -1.12
        }
      ]
    },
    "limitUp": {
      "limitUpCount": 59,
      "limitDownCount": 8,
      "failedLimitUpCount": 27,
      "touchedLimitUpCount": 86,
      "sealRate": 0.686,
      "highestStreak": 6,
      "dataScopeNote": "limit_list_d 不含 ST 股票统计"
    },
    "limitUpDistribution": [
      {
        "distributionType": "LIMIT_TYPE",
        "bucketKey": "LIMIT_UP",
        "bucketName": "涨停",
        "count": 59,
        "direction": "UP"
      },
      {
        "distributionType": "LIMIT_TYPE",
        "bucketKey": "LIMIT_DOWN",
        "bucketName": "跌停",
        "count": 8,
        "direction": "DOWN"
      }
    ],
    "streakLadder": {
      "tradeDate": "2026-04-28",
      "highestStreak": 6,
      "items": [
        {
          "stockCode": "002888.SZ",
          "stockName": "示例股份",
          "sectorName": "机器人",
          "streak": 6,
          "firstSealTime": "09:42:15",
          "openTimes": 0
        }
      ]
    },
    "sectorOverview": {
      "topGainers": [
        {
          "rank": 1,
          "sectorId": "BK1184.DC",
          "sectorName": "人形机器人",
          "sectorType": "CONCEPT",
          "changePct": 4.08,
          "direction": "UP",
          "turnoverRate": 4.08,
          "upCount": 2,
          "downCount": 62,
          "leadingStockName": "东港股份",
          "leadingStockCode": "002117.SZ",
          "leadingStockChangePct": 10.02
        }
      ],
      "topMoneyInflow": [
        {
          "rank": 1,
          "sectorId": "BK0493.DC",
          "sectorName": "新能源",
          "sectorType": "CONCEPT",
          "changePct": 1.48,
          "direction": "UP",
          "mainNetInflow": 3056382208
        }
      ],
      "heatmap": [
        {
          "id": "BK1184.DC",
          "name": "人形机器人",
          "type": "CONCEPT",
          "changePct": 4.08,
          "direction": "UP",
          "sizeMetric": "AMOUNT",
          "sizeValue": 987654321
        }
      ]
    },
    "leaderboards": {
      "popular": [
        {
          "rank": 1,
          "rankType": "POPULAR",
          "market": "A股市场",
          "stockCode": "601099.SH",
          "stockName": "太平洋",
          "price": 4.82,
          "changePct": 3.21,
          "direction": "UP",
          "rankTime": "22:30:00",
          "isLatest": true
        }
      ],
      "surge": [
        {
          "rank": 1,
          "rankType": "SURGE",
          "market": "A股市场",
          "stockCode": "002235.SZ",
          "stockName": "安妮股份",
          "price": 9.36,
          "changePct": -1.25,
          "direction": "DOWN",
          "rankTime": "14:30:00",
          "isLatest": false
        }
      ]
    }
  },
  "traceId": "req_20260428_000001",
  "serverTime": "2026-04-28T17:12:00+08:00"
}
```

### 字段说明

| 字段 | 对象 | 页面模块 | 数据来源 |
|---|---|---|---|
| `tradingDay` | `TradingDay` | PageHeader / TopMarketBar | `trade_cal` |
| `dataStatus` | `DataSourceStatus[]` | TopMarketBar / 数据源 Tooltip | 同步任务 |
| `topMarketBar` | `TopMarketBarData` | TopMarketBar | 系统配置 + index_daily |
| `breadcrumb` | `BreadcrumbItem[]` | Breadcrumb | 路由配置 |
| `quickEntries` | `QuickEntry[]` | ShortcutBar | 配置中心 + 用户状态 |
| `marketSummary` | `MarketObjectiveSummary` | 首屏客观摘要 | 统计快照 |
| `indices` | `IndexSnapshot[]` | 主要指数卡片 | `index_daily` |
| `breadth` | `MarketBreadth` | 涨跌分布 | `daily` |
| `style` | `MarketStyle` | 市场风格 | `index_daily` |
| `turnover` | `TurnoverSummary` | 成交额 | `daily` 聚合 |
| `moneyFlow` | `MoneyFlowSummary` | 大盘资金流向 | `moneyflow_mkt_dc` |
| `limitUp` | `LimitUpSummary` | 涨跌停统计 | `limit_list_d` |
| `limitUpDistribution` | `LimitUpDistribution[]` | 涨跌停分布 | `limit_list_d` / `daily` |
| `streakLadder` | `LimitUpStreakLadder` | 连板天梯 | `limit_list_d` |
| `sectorOverview` | object | 板块速览 / 热力图 | `dc_index` / `dc_daily` / `moneyflow_ind_dc` |
| `leaderboards` | object | 东方财富热榜 | `dc_hot` |

### 异常状态

| code | 场景 | 处理 |
|---:|---|---|
| `400001` | 日期、枚举参数错误 | 返回参数错误。 |
| `401001` | 用户状态读取失败或未登录 | 行情数据正常返回，用户相关数量降级为空。 |
| `404001` | 指定交易日无任何行情数据 | 返回空状态。 |
| `409001` | 非交易日请求盘中数据 | 自动回退最近交易日或提示冲突。 |
| `429001` | 高频刷新 | 前端退避。 |
| `500001` | 聚合服务异常 | 整页异常态。 |
| `503001` | 核心数据源不可用 | 可用最近缓存；无缓存则整页异常态。 |

### 空数据处理

- `indices`、`breadth`、`turnover` 缺失：主异常态。
- `moneyFlow` 缺失：模块显示“资金流数据暂缺”。
- `sectorOverview` 缺失：板块模块空态。
- `leaderboards` 缺失：榜单模块空态。
- 用户快捷状态缺失：快捷入口仍展示，数量 badge 置空。

### 数据更新时间

以各模块 `asOf` 或 `DataSourceStatus.latestDataTime` 为准。P0 可先以日频/盘后落库数据支撑；无盘中实时数据时必须标记 `DELAYED`。

### 缓存建议

| 层级 | 建议 TTL |
|---|---:|
| 聚合接口盘中延迟态 | 60 秒 |
| 聚合接口盘后 READY | 1 个交易日 |
| 数据源状态 | 30-60 秒 |
| 快捷入口配置 | 1 天 |

### 性能评估

P95 `< 350ms`；Payload 建议 `< 120KB`。后端应读取预聚合快照，不应在请求时多表全量扫描。

### 暂缺数据字段清单

详见数据字典“P0 暂缺字段”。核心缺口是盘中实时行情、稳定样本池、传统 quote-derived 榜单、历史曲线预聚合。

### 与页面模块的映射关系

见本文档末尾“市场总览页面模块与 API 字段映射表”。

---

## 4. 模块接口总览

| 接口 | 复用模块 | 推荐 P95 | 缓存 |
|---|---|---:|---|
| `/api/index/summary` | 主要指数 / TopMarketBar | `<120ms` | 盘后 1 日 |
| `/api/market/breadth` | 涨跌分布 | `<150ms` | 盘后 1 日 |
| `/api/market/style` | 市场风格 | `<120ms` | 盘后 1 日 |
| `/api/market/turnover` | 成交额 | `<150ms` | 盘后 1 日 |
| `/api/moneyflow/market` | 大盘资金流 | `<150ms` | 盘后 1 日 |
| `/api/limitup/summary` | 涨跌停统计 | `<150ms` | 盘后 1 日 |
| `/api/limitup/streak-ladder` | 连板天梯 | `<180ms` | 盘后 1 日 |
| `/api/sector/top` | 板块速览 | `<200ms` | 盘后 1 日 |
| `/api/leaderboard/stock` | 东方财富热榜 | `<150ms` | 5-30 分钟/盘后 1 日 |
| `/api/settings/quick-entry` | ShortcutBar | `<80ms` | 1 日 |

---

## 5. 模块接口明细

## 5.1 GET /api/index/summary

### endpoint

```http
GET /api/index/summary
```

### method

`GET`

### 前端使用场景

指数卡片和 TopMarketBar 指数条。对应页面模块：**核心指数卡片**。聚合接口中的映射字段为：`indices`。

### request params

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---:|---|---|
| `market` | string | 否 | `CN_A` / `A股市场` | 行情类固定 A 股；`dc_hot` 使用 `A股市场`。 |
| `tradeDate` | string(date) | 否 | 最近交易日 | `YYYY-MM-DD`。 |
| `limit` | integer | 否 | 10 | 返回条数，列表类接口有效。 |
| `dataMode` | enum | 否 | `latest` | `latest` / `eod` / `replay`。 |

### response JSON / Mock 数据示例

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "items": [
      {
        "indexCode": "000001.SH",
        "indexName": "上证指数",
        "last": 3128.42,
        "prevClose": 3099.76,
        "change": 28.66,
        "changePct": 0.92,
        "amount": 482300000,
        "direction": "UP"
      },
      {
        "indexCode": "399001.SZ",
        "indexName": "深证成指",
        "last": 9842.15,
        "prevClose": 9876.36,
        "change": -34.21,
        "changePct": -0.35,
        "amount": 598400000,
        "direction": "DOWN"
      }
    ],
    "dataStatus": "READY"
  },
  "traceId": "req_20260428_000001",
  "serverTime": "2026-04-28T17:12:00+08:00"
}
```

### 字段说明

返回对象类型：`IndexSnapshot[]`。字段口径见《P0 数据字典 v0.3》。主要数据来源：`index_daily`。

### 异常状态

| code | 场景 | 前端处理 |
|---:|---|---|
| `400001` | 参数格式错误或枚举值非法 | 展示筛选错误，保留旧数据。 |
| `404001` | 指定交易日无数据 | 展示空状态。 |
| `429001` | 请求过快 | 前端退避重试。 |
| `500001` | 服务异常 | 展示模块异常态和重试按钮。 |
| `503001` | 数据源不可用 | 展示数据源异常，允许使用最近缓存。 |

### 空数据处理

返回空数组或 `dataStatus=UNAVAILABLE` 时，仅当前模块降级，不应导致市场总览整页白屏。空状态文案需要说明数据源、交易日或筛选条件原因。

### 数据更新时间

随 `index_daily` 的最新落库时间更新。P0 可先按日频/盘后数据支撑；如盘中无实时数据，必须返回 `dataStatus=DELAYED` 或在 `DataSourceStatus` 中说明。

### 缓存建议

- 盘中延迟数据：60 秒。
- 盘后 `READY` 数据：1 个交易日。
- 列表类接口：30-300 秒，依据源数据更新频率。

### 性能评估

P95 建议 `< 200ms`；必须读取 `wealth_*_snapshot` 或等价预聚合视图，不应在请求时扫描全量 raw 表。

### 暂缺数据字段清单

实时盘中字段、细分样本池状态、历史排名变化、异常交易日特殊处理可后续补充；不得为了填充 UI 临时编造字段。

### 与页面模块的映射关系

| 页面模块 | 聚合接口字段 | 模块接口字段 |
|---|---|---|
| 核心指数卡片 | `indices` | `data` 或 `data.items` |

## 5.2 GET /api/market/breadth

### endpoint

```http
GET /api/market/breadth
```

### method

`GET`

### 前端使用场景

涨跌家数、涨跌幅分布和赚钱效应事实。对应页面模块：**涨跌分布模块**。聚合接口中的映射字段为：`breadth`。

### request params

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---:|---|---|
| `market` | string | 否 | `CN_A` / `A股市场` | 行情类固定 A 股；`dc_hot` 使用 `A股市场`。 |
| `tradeDate` | string(date) | 否 | 最近交易日 | `YYYY-MM-DD`。 |
| `limit` | integer | 否 | 10 | 返回条数，列表类接口有效。 |
| `dataMode` | enum | 否 | `latest` | `latest` / `eod` / `replay`。 |

### response JSON / Mock 数据示例

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "samplePool": "CN_A_COMMON",
    "stockUniverseCount": 5128,
    "upCount": 3421,
    "downCount": 1488,
    "flatCount": 219,
    "redRate": 0.667,
    "medianChangePct": 0.48,
    "distribution": [
      {
        "bucketKey": "GT_5",
        "bucketName": "涨超5%",
        "count": 186,
        "direction": "UP"
      },
      {
        "bucketKey": "LT_-5",
        "bucketName": "跌超5%",
        "count": 72,
        "direction": "DOWN"
      }
    ]
  },
  "traceId": "req_20260428_000002",
  "serverTime": "2026-04-28T17:12:00+08:00"
}
```

### 字段说明

返回对象类型：`MarketBreadth`。字段口径见《P0 数据字典 v0.3》。主要数据来源：`daily + stock_basic + limit_list_d`。

### 异常状态

| code | 场景 | 前端处理 |
|---:|---|---|
| `400001` | 参数格式错误或枚举值非法 | 展示筛选错误，保留旧数据。 |
| `404001` | 指定交易日无数据 | 展示空状态。 |
| `429001` | 请求过快 | 前端退避重试。 |
| `500001` | 服务异常 | 展示模块异常态和重试按钮。 |
| `503001` | 数据源不可用 | 展示数据源异常，允许使用最近缓存。 |

### 空数据处理

返回空数组或 `dataStatus=UNAVAILABLE` 时，仅当前模块降级，不应导致市场总览整页白屏。空状态文案需要说明数据源、交易日或筛选条件原因。

### 数据更新时间

随 `daily + stock_basic + limit_list_d` 的最新落库时间更新。P0 可先按日频/盘后数据支撑；如盘中无实时数据，必须返回 `dataStatus=DELAYED` 或在 `DataSourceStatus` 中说明。

### 缓存建议

- 盘中延迟数据：60 秒。
- 盘后 `READY` 数据：1 个交易日。
- 列表类接口：30-300 秒，依据源数据更新频率。

### 性能评估

P95 建议 `< 200ms`；必须读取 `wealth_*_snapshot` 或等价预聚合视图，不应在请求时扫描全量 raw 表。

### 暂缺数据字段清单

实时盘中字段、细分样本池状态、历史排名变化、异常交易日特殊处理可后续补充；不得为了填充 UI 临时编造字段。

### 与页面模块的映射关系

| 页面模块 | 聚合接口字段 | 模块接口字段 |
|---|---|---|
| 涨跌分布模块 | `breadth` | `data` 或 `data.items` |

## 5.3 GET /api/market/style

### endpoint

```http
GET /api/market/style
```

### method

`GET`

### 前端使用场景

大小盘/权重题材风格事实。对应页面模块：**市场风格模块**。聚合接口中的映射字段为：`style`。

### request params

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---:|---|---|
| `market` | string | 否 | `CN_A` / `A股市场` | 行情类固定 A 股；`dc_hot` 使用 `A股市场`。 |
| `tradeDate` | string(date) | 否 | 最近交易日 | `YYYY-MM-DD`。 |
| `limit` | integer | 否 | 10 | 返回条数，列表类接口有效。 |
| `dataMode` | enum | 否 | `latest` | `latest` / `eod` / `replay`。 |

### response JSON / Mock 数据示例

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "largeCapIndexCode": "000300.SH",
    "smallCapIndexCode": "000852.SH",
    "largeCapChangePct": 0.72,
    "smallCapChangePct": 1.48,
    "smallVsLargeSpreadPct": 0.76,
    "styleLeader": "SMALL_CAP"
  },
  "traceId": "req_20260428_000003",
  "serverTime": "2026-04-28T17:12:00+08:00"
}
```

### 字段说明

返回对象类型：`MarketStyle`。字段口径见《P0 数据字典 v0.3》。主要数据来源：`index_daily + 指数配置`。

### 异常状态

| code | 场景 | 前端处理 |
|---:|---|---|
| `400001` | 参数格式错误或枚举值非法 | 展示筛选错误，保留旧数据。 |
| `404001` | 指定交易日无数据 | 展示空状态。 |
| `429001` | 请求过快 | 前端退避重试。 |
| `500001` | 服务异常 | 展示模块异常态和重试按钮。 |
| `503001` | 数据源不可用 | 展示数据源异常，允许使用最近缓存。 |

### 空数据处理

返回空数组或 `dataStatus=UNAVAILABLE` 时，仅当前模块降级，不应导致市场总览整页白屏。空状态文案需要说明数据源、交易日或筛选条件原因。

### 数据更新时间

随 `index_daily + 指数配置` 的最新落库时间更新。P0 可先按日频/盘后数据支撑；如盘中无实时数据，必须返回 `dataStatus=DELAYED` 或在 `DataSourceStatus` 中说明。

### 缓存建议

- 盘中延迟数据：60 秒。
- 盘后 `READY` 数据：1 个交易日。
- 列表类接口：30-300 秒，依据源数据更新频率。

### 性能评估

P95 建议 `< 200ms`；必须读取 `wealth_*_snapshot` 或等价预聚合视图，不应在请求时扫描全量 raw 表。

### 暂缺数据字段清单

实时盘中字段、细分样本池状态、历史排名变化、异常交易日特殊处理可后续补充；不得为了填充 UI 临时编造字段。

### 与页面模块的映射关系

| 页面模块 | 聚合接口字段 | 模块接口字段 |
|---|---|---|
| 市场风格模块 | `style` | `data` 或 `data.items` |

## 5.4 GET /api/market/turnover

### endpoint

```http
GET /api/market/turnover
```

### method

`GET`

### 前端使用场景

成交额和历史成交额曲线。对应页面模块：**成交额模块**。聚合接口中的映射字段为：`turnover`。

### request params

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---:|---|---|
| `market` | string | 否 | `CN_A` / `A股市场` | 行情类固定 A 股；`dc_hot` 使用 `A股市场`。 |
| `tradeDate` | string(date) | 否 | 最近交易日 | `YYYY-MM-DD`。 |
| `limit` | integer | 否 | 10 | 返回条数，列表类接口有效。 |
| `dataMode` | enum | 否 | `latest` | `latest` / `eod` / `replay`。 |

### response JSON / Mock 数据示例

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "totalAmount": 1052300000,
    "prevTotalAmount": 982100000,
    "amountChange": 70200000,
    "amountChangePct": 7.15,
    "amount20dMedian": 936000000,
    "amountRatio20dMedian": 1.12,
    "history": [
      {
        "tradeDate": "2026-04-28",
        "totalAmount": 1052300000,
        "amountChangePct": 7.15
      }
    ]
  },
  "traceId": "req_20260428_000004",
  "serverTime": "2026-04-28T17:12:00+08:00"
}
```

### 字段说明

返回对象类型：`TurnoverSummary`。字段口径见《P0 数据字典 v0.3》。主要数据来源：`daily 聚合`。

### 异常状态

| code | 场景 | 前端处理 |
|---:|---|---|
| `400001` | 参数格式错误或枚举值非法 | 展示筛选错误，保留旧数据。 |
| `404001` | 指定交易日无数据 | 展示空状态。 |
| `429001` | 请求过快 | 前端退避重试。 |
| `500001` | 服务异常 | 展示模块异常态和重试按钮。 |
| `503001` | 数据源不可用 | 展示数据源异常，允许使用最近缓存。 |

### 空数据处理

返回空数组或 `dataStatus=UNAVAILABLE` 时，仅当前模块降级，不应导致市场总览整页白屏。空状态文案需要说明数据源、交易日或筛选条件原因。

### 数据更新时间

随 `daily 聚合` 的最新落库时间更新。P0 可先按日频/盘后数据支撑；如盘中无实时数据，必须返回 `dataStatus=DELAYED` 或在 `DataSourceStatus` 中说明。

### 缓存建议

- 盘中延迟数据：60 秒。
- 盘后 `READY` 数据：1 个交易日。
- 列表类接口：30-300 秒，依据源数据更新频率。

### 性能评估

P95 建议 `< 200ms`；必须读取 `wealth_*_snapshot` 或等价预聚合视图，不应在请求时扫描全量 raw 表。

### 暂缺数据字段清单

实时盘中字段、细分样本池状态、历史排名变化、异常交易日特殊处理可后续补充；不得为了填充 UI 临时编造字段。

### 与页面模块的映射关系

| 页面模块 | 聚合接口字段 | 模块接口字段 |
|---|---|---|
| 成交额模块 | `turnover` | `data` 或 `data.items` |

## 5.5 GET /api/moneyflow/market

### endpoint

```http
GET /api/moneyflow/market
```

### method

`GET`

### 前端使用场景

大盘资金流事实，不返回资金面分数。对应页面模块：**资金流向模块**。聚合接口中的映射字段为：`moneyFlow`。

### request params

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---:|---|---|
| `market` | string | 否 | `CN_A` / `A股市场` | 行情类固定 A 股；`dc_hot` 使用 `A股市场`。 |
| `tradeDate` | string(date) | 否 | 最近交易日 | `YYYY-MM-DD`。 |
| `limit` | integer | 否 | 10 | 返回条数，列表类接口有效。 |
| `dataMode` | enum | 否 | `latest` | `latest` / `eod` / `replay`。 |

### response JSON / Mock 数据示例

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "mainNetInflow": -8120000000,
    "mainNetInflowRate": -1.12,
    "superLargeAmount": -3200000000,
    "largeAmount": -4920000000,
    "mediumAmount": 2100000000,
    "smallAmount": 6020000000,
    "history": [
      {
        "tradeDate": "2026-04-28",
        "mainNetInflow": -8120000000,
        "mainNetInflowRate": -1.12
      }
    ]
  },
  "traceId": "req_20260428_000005",
  "serverTime": "2026-04-28T17:12:00+08:00"
}
```

### 字段说明

返回对象类型：`MoneyFlowSummary`。字段口径见《P0 数据字典 v0.3》。主要数据来源：`moneyflow_mkt_dc`。

### 异常状态

| code | 场景 | 前端处理 |
|---:|---|---|
| `400001` | 参数格式错误或枚举值非法 | 展示筛选错误，保留旧数据。 |
| `404001` | 指定交易日无数据 | 展示空状态。 |
| `429001` | 请求过快 | 前端退避重试。 |
| `500001` | 服务异常 | 展示模块异常态和重试按钮。 |
| `503001` | 数据源不可用 | 展示数据源异常，允许使用最近缓存。 |

### 空数据处理

返回空数组或 `dataStatus=UNAVAILABLE` 时，仅当前模块降级，不应导致市场总览整页白屏。空状态文案需要说明数据源、交易日或筛选条件原因。

### 数据更新时间

随 `moneyflow_mkt_dc` 的最新落库时间更新。P0 可先按日频/盘后数据支撑；如盘中无实时数据，必须返回 `dataStatus=DELAYED` 或在 `DataSourceStatus` 中说明。

### 缓存建议

- 盘中延迟数据：60 秒。
- 盘后 `READY` 数据：1 个交易日。
- 列表类接口：30-300 秒，依据源数据更新频率。

### 性能评估

P95 建议 `< 200ms`；必须读取 `wealth_*_snapshot` 或等价预聚合视图，不应在请求时扫描全量 raw 表。

### 暂缺数据字段清单

实时盘中字段、细分样本池状态、历史排名变化、异常交易日特殊处理可后续补充；不得为了填充 UI 临时编造字段。

### 与页面模块的映射关系

| 页面模块 | 聚合接口字段 | 模块接口字段 |
|---|---|---|
| 资金流向模块 | `moneyFlow` | `data` 或 `data.items` |

## 5.6 GET /api/limitup/summary

### endpoint

```http
GET /api/limitup/summary
```

### method

`GET`

### 前端使用场景

涨停、跌停、炸板、封板率。对应页面模块：**涨跌停统计模块**。聚合接口中的映射字段为：`limitUp`。

### request params

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---:|---|---|
| `market` | string | 否 | `CN_A` / `A股市场` | 行情类固定 A 股；`dc_hot` 使用 `A股市场`。 |
| `tradeDate` | string(date) | 否 | 最近交易日 | `YYYY-MM-DD`。 |
| `limit` | integer | 否 | 10 | 返回条数，列表类接口有效。 |
| `dataMode` | enum | 否 | `latest` | `latest` / `eod` / `replay`。 |

### response JSON / Mock 数据示例

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "limitUpCount": 59,
    "limitDownCount": 8,
    "failedLimitUpCount": 27,
    "touchedLimitUpCount": 86,
    "sealRate": 0.686,
    "highestStreak": 6,
    "dataScopeNote": "limit_list_d 不含 ST 股票统计"
  },
  "traceId": "req_20260428_000006",
  "serverTime": "2026-04-28T17:12:00+08:00"
}
```

### 字段说明

返回对象类型：`LimitUpSummary`。字段口径见《P0 数据字典 v0.3》。主要数据来源：`limit_list_d + stk_limit`。

### 异常状态

| code | 场景 | 前端处理 |
|---:|---|---|
| `400001` | 参数格式错误或枚举值非法 | 展示筛选错误，保留旧数据。 |
| `404001` | 指定交易日无数据 | 展示空状态。 |
| `429001` | 请求过快 | 前端退避重试。 |
| `500001` | 服务异常 | 展示模块异常态和重试按钮。 |
| `503001` | 数据源不可用 | 展示数据源异常，允许使用最近缓存。 |

### 空数据处理

返回空数组或 `dataStatus=UNAVAILABLE` 时，仅当前模块降级，不应导致市场总览整页白屏。空状态文案需要说明数据源、交易日或筛选条件原因。

### 数据更新时间

随 `limit_list_d + stk_limit` 的最新落库时间更新。P0 可先按日频/盘后数据支撑；如盘中无实时数据，必须返回 `dataStatus=DELAYED` 或在 `DataSourceStatus` 中说明。

### 缓存建议

- 盘中延迟数据：60 秒。
- 盘后 `READY` 数据：1 个交易日。
- 列表类接口：30-300 秒，依据源数据更新频率。

### 性能评估

P95 建议 `< 200ms`；必须读取 `wealth_*_snapshot` 或等价预聚合视图，不应在请求时扫描全量 raw 表。

### 暂缺数据字段清单

实时盘中字段、细分样本池状态、历史排名变化、异常交易日特殊处理可后续补充；不得为了填充 UI 临时编造字段。

### 与页面模块的映射关系

| 页面模块 | 聚合接口字段 | 模块接口字段 |
|---|---|---|
| 涨跌停统计模块 | `limitUp` | `data` 或 `data.items` |

## 5.7 GET /api/limitup/streak-ladder

### endpoint

```http
GET /api/limitup/streak-ladder
```

### method

`GET`

### 前端使用场景

连板天梯和连板股票明细。对应页面模块：**连板天梯模块**。聚合接口中的映射字段为：`streakLadder`。

### request params

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---:|---|---|
| `market` | string | 否 | `CN_A` / `A股市场` | 行情类固定 A 股；`dc_hot` 使用 `A股市场`。 |
| `tradeDate` | string(date) | 否 | 最近交易日 | `YYYY-MM-DD`。 |
| `limit` | integer | 否 | 10 | 返回条数，列表类接口有效。 |
| `dataMode` | enum | 否 | `latest` | `latest` / `eod` / `replay`。 |

### response JSON / Mock 数据示例

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "tradeDate": "2026-04-28",
    "highestStreak": 6,
    "items": [
      {
        "stockCode": "002888.SZ",
        "stockName": "示例股份",
        "sectorName": "机器人",
        "streak": 6,
        "firstSealTime": "09:42:15",
        "openTimes": 0
      }
    ]
  },
  "traceId": "req_20260428_000007",
  "serverTime": "2026-04-28T17:12:00+08:00"
}
```

### 字段说明

返回对象类型：`LimitUpStreakLadder`。字段口径见《P0 数据字典 v0.3》。主要数据来源：`limit_list_d`。

### 异常状态

| code | 场景 | 前端处理 |
|---:|---|---|
| `400001` | 参数格式错误或枚举值非法 | 展示筛选错误，保留旧数据。 |
| `404001` | 指定交易日无数据 | 展示空状态。 |
| `429001` | 请求过快 | 前端退避重试。 |
| `500001` | 服务异常 | 展示模块异常态和重试按钮。 |
| `503001` | 数据源不可用 | 展示数据源异常，允许使用最近缓存。 |

### 空数据处理

返回空数组或 `dataStatus=UNAVAILABLE` 时，仅当前模块降级，不应导致市场总览整页白屏。空状态文案需要说明数据源、交易日或筛选条件原因。

### 数据更新时间

随 `limit_list_d` 的最新落库时间更新。P0 可先按日频/盘后数据支撑；如盘中无实时数据，必须返回 `dataStatus=DELAYED` 或在 `DataSourceStatus` 中说明。

### 缓存建议

- 盘中延迟数据：60 秒。
- 盘后 `READY` 数据：1 个交易日。
- 列表类接口：30-300 秒，依据源数据更新频率。

### 性能评估

P95 建议 `< 200ms`；必须读取 `wealth_*_snapshot` 或等价预聚合视图，不应在请求时扫描全量 raw 表。

### 暂缺数据字段清单

实时盘中字段、细分样本池状态、历史排名变化、异常交易日特殊处理可后续补充；不得为了填充 UI 临时编造字段。

### 与页面模块的映射关系

| 页面模块 | 聚合接口字段 | 模块接口字段 |
|---|---|---|
| 连板天梯模块 | `streakLadder` | `data` 或 `data.items` |

## 5.8 GET /api/sector/top

### endpoint

```http
GET /api/sector/top
```

### method

`GET`

### 前端使用场景

东方财富行业/概念/地域板块榜。对应页面模块：**板块速览/热力图**。聚合接口中的映射字段为：`sectorOverview.topGainers/topMoneyInflow`。

### request params

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---:|---|---|
| `market` | string | 否 | `CN_A` / `A股市场` | 行情类固定 A 股；`dc_hot` 使用 `A股市场`。 |
| `tradeDate` | string(date) | 否 | 最近交易日 | `YYYY-MM-DD`。 |
| `limit` | integer | 否 | 10 | 返回条数，列表类接口有效。 |
| `dataMode` | enum | 否 | `latest` | `latest` / `eod` / `replay`。 |

### response JSON / Mock 数据示例

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "items": [
      {
        "rank": 1,
        "sectorId": "BK1184.DC",
        "sectorName": "人形机器人",
        "sectorType": "CONCEPT",
        "changePct": 4.08,
        "direction": "UP",
        "turnoverRate": 4.08,
        "upCount": 2,
        "downCount": 62,
        "leadingStockName": "东港股份",
        "leadingStockCode": "002117.SZ",
        "leadingStockChangePct": 10.02
      }
    ],
    "dataStatus": "READY"
  },
  "traceId": "req_20260428_000008",
  "serverTime": "2026-04-28T17:12:00+08:00"
}
```

### 字段说明

返回对象类型：`SectorRankItem[]`。字段口径见《P0 数据字典 v0.3》。主要数据来源：`dc_index + dc_daily + moneyflow_ind_dc`。

### 异常状态

| code | 场景 | 前端处理 |
|---:|---|---|
| `400001` | 参数格式错误或枚举值非法 | 展示筛选错误，保留旧数据。 |
| `404001` | 指定交易日无数据 | 展示空状态。 |
| `429001` | 请求过快 | 前端退避重试。 |
| `500001` | 服务异常 | 展示模块异常态和重试按钮。 |
| `503001` | 数据源不可用 | 展示数据源异常，允许使用最近缓存。 |

### 空数据处理

返回空数组或 `dataStatus=UNAVAILABLE` 时，仅当前模块降级，不应导致市场总览整页白屏。空状态文案需要说明数据源、交易日或筛选条件原因。

### 数据更新时间

随 `dc_index + dc_daily + moneyflow_ind_dc` 的最新落库时间更新。P0 可先按日频/盘后数据支撑；如盘中无实时数据，必须返回 `dataStatus=DELAYED` 或在 `DataSourceStatus` 中说明。

### 缓存建议

- 盘中延迟数据：60 秒。
- 盘后 `READY` 数据：1 个交易日。
- 列表类接口：30-300 秒，依据源数据更新频率。

### 性能评估

P95 建议 `< 200ms`；必须读取 `wealth_*_snapshot` 或等价预聚合视图，不应在请求时扫描全量 raw 表。

### 暂缺数据字段清单

实时盘中字段、细分样本池状态、历史排名变化、异常交易日特殊处理可后续补充；不得为了填充 UI 临时编造字段。

### 与页面模块的映射关系

| 页面模块 | 聚合接口字段 | 模块接口字段 |
|---|---|---|
| 板块速览/热力图 | `sectorOverview.topGainers/topMoneyInflow` | `data` 或 `data.items` |

## 5.9 GET /api/leaderboard/stock

### endpoint

```http
GET /api/leaderboard/stock
```

### method

`GET`

### 前端使用场景

东方财富 A 股热榜。对应页面模块：**榜单速览**。聚合接口中的映射字段为：`leaderboards`。

### request params

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---:|---|---|
| `market` | string | 否 | `CN_A` / `A股市场` | 行情类固定 A 股；`dc_hot` 使用 `A股市场`。 |
| `tradeDate` | string(date) | 否 | 最近交易日 | `YYYY-MM-DD`。 |
| `limit` | integer | 否 | 10 | 返回条数，列表类接口有效。 |
| `dataMode` | enum | 否 | `latest` | `latest` / `eod` / `replay`。 |

### response JSON / Mock 数据示例

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "items": [
      {
        "rank": 1,
        "rankType": "POPULAR",
        "market": "A股市场",
        "stockCode": "601099.SH",
        "stockName": "太平洋",
        "price": 4.82,
        "changePct": 3.21,
        "direction": "UP",
        "rankTime": "22:30:00",
        "isLatest": true
      }
    ],
    "dataStatus": "READY"
  },
  "traceId": "req_20260428_000009",
  "serverTime": "2026-04-28T17:12:00+08:00"
}
```

### 字段说明

返回对象类型：`StockRankItem[]`。字段口径见《P0 数据字典 v0.3》。主要数据来源：`dc_hot`。

### 异常状态

| code | 场景 | 前端处理 |
|---:|---|---|
| `400001` | 参数格式错误或枚举值非法 | 展示筛选错误，保留旧数据。 |
| `404001` | 指定交易日无数据 | 展示空状态。 |
| `429001` | 请求过快 | 前端退避重试。 |
| `500001` | 服务异常 | 展示模块异常态和重试按钮。 |
| `503001` | 数据源不可用 | 展示数据源异常，允许使用最近缓存。 |

### 空数据处理

返回空数组或 `dataStatus=UNAVAILABLE` 时，仅当前模块降级，不应导致市场总览整页白屏。空状态文案需要说明数据源、交易日或筛选条件原因。

### 数据更新时间

随 `dc_hot` 的最新落库时间更新。P0 可先按日频/盘后数据支撑；如盘中无实时数据，必须返回 `dataStatus=DELAYED` 或在 `DataSourceStatus` 中说明。

### 缓存建议

- 盘中延迟数据：60 秒。
- 盘后 `READY` 数据：1 个交易日。
- 列表类接口：30-300 秒，依据源数据更新频率。

### 性能评估

P95 建议 `< 200ms`；必须读取 `wealth_*_snapshot` 或等价预聚合视图，不应在请求时扫描全量 raw 表。

### 暂缺数据字段清单

实时盘中字段、细分样本池状态、历史排名变化、异常交易日特殊处理可后续补充；不得为了填充 UI 临时编造字段。

### 与页面模块的映射关系

| 页面模块 | 聚合接口字段 | 模块接口字段 |
|---|---|---|
| 榜单速览 | `leaderboards` | `data` 或 `data.items` |

## 5.10 GET /api/settings/quick-entry

### endpoint

```http
GET /api/settings/quick-entry
```

### method

`GET`

### 前端使用场景

页面内快捷入口。对应页面模块：**ShortcutBar**。聚合接口中的映射字段为：`quickEntries`。

### request params

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---:|---|---|
| `market` | string | 否 | `CN_A` / `A股市场` | 行情类固定 A 股；`dc_hot` 使用 `A股市场`。 |
| `tradeDate` | string(date) | 否 | 最近交易日 | `YYYY-MM-DD`。 |
| `limit` | integer | 否 | 10 | 返回条数，列表类接口有效。 |
| `dataMode` | enum | 否 | `latest` | `latest` / `eod` / `replay`。 |

### response JSON / Mock 数据示例

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "items": [
      {
        "key": "market-emotion",
        "title": "市场温度与情绪",
        "route": "/market/emotion",
        "enabled": true,
        "pendingCount": 0,
        "hasUpdate": true
      },
      {
        "key": "opportunity-radar",
        "title": "机会雷达",
        "route": "/opportunity/radar",
        "enabled": true,
        "pendingCount": 3,
        "hasUpdate": true
      },
      {
        "key": "watchlist",
        "title": "我的自选",
        "route": "/watchlist",
        "enabled": true,
        "pendingCount": 18,
        "hasUpdate": false
      },
      {
        "key": "positions",
        "title": "我的持仓",
        "route": "/positions",
        "enabled": true,
        "pendingCount": 5,
        "hasUpdate": true
      },
      {
        "key": "alerts",
        "title": "提醒中心",
        "route": "/alerts",
        "enabled": true,
        "pendingCount": 2,
        "hasUpdate": true
      }
    ],
    "dataStatus": "READY"
  },
  "traceId": "req_20260428_000010",
  "serverTime": "2026-04-28T17:12:00+08:00"
}
```

### 字段说明

返回对象类型：`QuickEntry[]`。字段口径见《P0 数据字典 v0.3》。主要数据来源：`配置中心 + 用户状态`。

### 异常状态

| code | 场景 | 前端处理 |
|---:|---|---|
| `400001` | 参数格式错误或枚举值非法 | 展示筛选错误，保留旧数据。 |
| `404001` | 指定交易日无数据 | 展示空状态。 |
| `429001` | 请求过快 | 前端退避重试。 |
| `500001` | 服务异常 | 展示模块异常态和重试按钮。 |
| `503001` | 数据源不可用 | 展示数据源异常，允许使用最近缓存。 |

### 空数据处理

返回空数组或 `dataStatus=UNAVAILABLE` 时，仅当前模块降级，不应导致市场总览整页白屏。空状态文案需要说明数据源、交易日或筛选条件原因。

### 数据更新时间

随 `配置中心 + 用户状态` 的最新落库时间更新。P0 可先按日频/盘后数据支撑；如盘中无实时数据，必须返回 `dataStatus=DELAYED` 或在 `DataSourceStatus` 中说明。

### 缓存建议

- 盘中延迟数据：60 秒。
- 盘后 `READY` 数据：1 个交易日。
- 列表类接口：30-300 秒，依据源数据更新频率。

### 性能评估

P95 建议 `< 200ms`；必须读取 `wealth_*_snapshot` 或等价预聚合视图，不应在请求时扫描全量 raw 表。

### 暂缺数据字段清单

实时盘中字段、细分样本池状态、历史排名变化、异常交易日特殊处理可后续补充；不得为了填充 UI 临时编造字段。

### 与页面模块的映射关系

| 页面模块 | 聚合接口字段 | 模块接口字段 |
|---|---|---|
| ShortcutBar | `quickEntries` | `data` 或 `data.items` |


---

## 6. 市场总览页面模块与 API 字段映射表

| 页面模块 | 聚合接口字段 | 模块接口 | 组件建议 |
|---|---|---|---|
| TopMarketBar | `topMarketBar`、`dataStatus` | `/api/index/summary` | `TopMarketBar`、`IndexTicker` |
| Breadcrumb | `breadcrumb` | 聚合接口内返回 | `Breadcrumb` |
| ShortcutBar | `quickEntries` | `/api/settings/quick-entry` | `ShortcutBar` |
| 客观摘要 | `marketSummary` | 聚合接口内返回 | `MarketObjectiveSummaryPanel` |
| 指数卡片 | `indices` | `/api/index/summary` | `IndexCardGroup` |
| 涨跌分布 | `breadth` | `/api/market/breadth` | `MarketBreadthPanel` |
| 市场风格 | `style` | `/api/market/style` | `MarketStylePanel` |
| 成交额 | `turnover` | `/api/market/turnover` | `TurnoverPanel` |
| 资金流 | `moneyFlow` | `/api/moneyflow/market` | `MoneyFlowPanel` |
| 涨跌停统计 | `limitUp` | `/api/limitup/summary` | `LimitUpSummaryCard` |
| 涨跌停分布 | `limitUpDistribution` | `/api/limitup/summary` 或后续分布接口 | `LimitUpDistributionChart` |
| 连板天梯 | `streakLadder` | `/api/limitup/streak-ladder` | `StreakLadder` |
| 板块速览 | `sectorOverview` | `/api/sector/top` | `SectorRankTable`、`SectorHeatMap` |
| 榜单速览 | `leaderboards` | `/api/leaderboard/stock` | `StockHotRankTabs` |

## 7. 给 02 HTML Showcase 的 Mock 数据建议

1. 直接使用 `GET /api/market/home-overview` 的 response 作为根 mock。
2. Mock 必须体现红涨绿跌：`UP` 红、`DOWN` 绿、`FLAT` 灰。
3. 快捷入口只显示入口状态、更新、待处理数量，不显示温度/情绪/风险/资金分数。
4. 准备 `moneyFlow.dataStatus=UNAVAILABLE` 的降级态。
5. 准备 `leaderboards.popular` 与 `leaderboards.surge` 两组热榜。
6. 板块数据用 `BKxxxx.DC`，体现行业/概念/地域三类。

## 8. 给 03 组件库的 Props 映射建议

| 组件 | Props |
|---|---|
| `TopMarketBar` | `brandName`、`globalEntries`、`indexTickers`、`tradingDay`、`dataStatus`、`userShortcutStatus` |
| `Breadcrumb` | `items: BreadcrumbItem[]` |
| `ShortcutBar` | `entries: QuickEntry[]` |
| `IndexCardGroup` | `items: IndexSnapshot[]` |
| `MarketBreadthPanel` | `breadth: MarketBreadth` |
| `TurnoverPanel` | `turnover: TurnoverSummary` |
| `MoneyFlowPanel` | `moneyFlow: MoneyFlowSummary` |
| `LimitUpPanel` | `summary: LimitUpSummary`、`distribution: LimitUpDistribution[]` |
| `StreakLadder` | `ladder: LimitUpStreakLadder` |
| `SectorRankTable` | `items: SectorRankItem[]` |
| `SectorHeatMap` | `items: HeatMapItem[]` |
| `StockHotRankTabs` | `popular: StockRankItem[]`、`surge: StockRankItem[]` |

## 9. 给 05 Codex 提示词的 API 约束

1. 不要自行添加市场温度分、情绪分、资金面分数、风险分数到市场总览页面。
2. 页面所有 mock 数据必须来自 `homeOverview` 根对象结构。
3. `direction` 必须按 A 股红涨绿跌渲染。
4. 板块数据使用东方财富板块字段，不使用 `sw_daily` 作为市场总览板块主口径。
5. 榜单使用 `dc_hot` 热榜结构，不要把它实现成普通涨幅榜。
6. TopMarketBar、Breadcrumb、ShortcutBar 必须读取 API 字段，不要在页面硬编码过多业务状态。
7. 空态、加载态、异常态必须按模块处理，非核心模块失败不得白屏。

## 10. P0 已具备字段

详见《P0 数据字典 v0.3》“P0 已具备字段”。

## 11. P0 暂缺字段

详见《P0 数据字典 v0.3》“P0 暂缺字段”。

## 12. 需要数据基座补充的字段

详见《P0 数据字典 v0.3》“需要数据基座补充的字段”。

## 13. 待产品总控确认问题

1. 是否新增传统行情榜单接口，补充涨幅榜、跌幅榜、成交额榜、换手榜？
2. 市场广度样本池是否排除 ST、新股、停牌？
3. 近半年历史曲线是否首屏必需？
4. TopMarketBar 是否需要接入真实用户头像与账号信息？
5. `dc_hot` 的 `is_new=Y/N` 在页面上如何切换展示？
