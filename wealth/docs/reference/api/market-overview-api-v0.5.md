# 财势乾坤｜市场总览 API 草案 v0.5

> 历史参考声明：本文是 Drive 原始 API 草案快照，包含 `/api/market/home-overview`、`/api/moneyflow/market`、`/api/index/summary` 等旧路径和旧聚合模型。当前工程实现不得直接沿用本文路径、参数或字段结构。当前 API 契约以 `wealth/docs/pages/market-overview/**` 模块三件套与 `wealth/docs/pages/market-overview/api-contract-baseline.md` 为准。

建议保存路径：`/docs/wealth/api/market-overview-api.md`  
负责人：`04_API 契约与数据字典`  
版本：`v0.5`  
状态：`历史参考，不作为实现契约`
更新时间：`2026-05-10`

---

## 0. 历史审计结论（已废弃）

本版以市场总览 PRD 为上游约束，收敛 API 到“市场总览开发落地”所需范围：

1. 推荐使用 `GET /api/market/home-overview` 作为首屏聚合接口。
2. 模块接口保留，用于局部刷新、页面下钻和复用。
3. 聚合接口必须覆盖 `TopMarketBar`、`Breadcrumb`、`ShortcutBar`。
4. 首页不返回市场温度、市场情绪、资金面分数、风险指数等主观分数字段。
5. 行业/概念/地域板块使用 `dc_index + dc_member + dc_daily`，板块资金补充 `moneyflow_ind_dc`。
6. 首页榜单使用 `dc_hot` 或由 `daily/daily_basic` 派生的行情榜，均统一为 `StockRankItem`。
7. 所有行情字段支持红涨绿跌。

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
| `0` | 成功 | 200 | 正常渲染 |
| `400001` | 参数错误 | 400 | 提示筛选条件错误 |
| `401001` | 未登录 | 401 | 基础行情游客态，用户状态降级 |
| `403001` | 无权限 | 403 | 展示权限提示 |
| `404001` | 数据不存在 | 404 | 展示空状态 |
| `409001` | 状态冲突 | 409 | 如非交易日请求盘中模式 |
| `429001` | 请求过快 | 429 | 降频重试 |
| `500001` | 服务异常 | 500 | 异常态 + 重试 |
| `503001` | 数据源不可用 | 503 | 使用最近缓存或模块降级 |

### 1.3 禁止字段

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

API 字段使用业务命名，但金额、成交量等数值单位默认保持 Tushare / PostgreSQL 落库口径。前端展示层负责格式化，不要求后端统一换算为元、股。

---

## 2. 历史推荐接口策略（已废弃）

| 场景 | 推荐接口 | 说明 |
|---|---|---|
| 页面首屏加载 | `GET /api/market/home-overview` | 一次性返回主要模块数据，减少请求瀑布 |
| 模块局部刷新 | 对应模块接口 | 例如只刷新涨跌停或榜单 |
| 下钻页面复用 | 对应模块接口 | 板块页、榜单页、情绪页复用事实字段 |
| 数据源异常 | 聚合接口模块级降级 | 非核心模块不可拖垮整页 |

---

## 3. 聚合接口

### GET /api/market/home-overview

#### endpoint

```http
GET /api/market/home-overview
```

#### method

`GET`

#### 前端使用场景

市场总览首屏和主体模块一次性加载。必须覆盖：`tradingDay`、`dataStatus`、`topMarketBar`、`breadcrumb`、`quickEntries`、`marketSummary`、`indices`、`breadth`、`style`、`turnover`、`moneyFlow`、`limitUp`、`limitUpDistribution`、`streakLadder`、`sectorOverview`、`leaderboards`。

#### request params

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---:|---|---|
| `market` | string | 否 | `CN_A` | P0 固定 A 股 |
| `tradeDate` | string(date) | 否 | 最近交易日 | 指定交易日 |
| `dataMode` | enum | 否 | `latest` | `latest` / `eod` / `replay` |
| `includeHistory` | boolean | 否 | `true` | 是否返回历史序列 |
| `sectorLimit` | integer | 否 | `8` | 每组板块榜数量 |
| `leaderboardLimit` | integer | 否 | `10` | 榜单返回数量 |

#### response JSON / Mock 数据示例

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "tradingDay": {
      "tradeDate": "2026-04-28",
      "prevTradeDate": "2026-04-27",
      "market": "CN_A",
      "isTradingDay": true,
      "sessionStatus": "CLOSED",
      "timezone": "Asia/Shanghai"
    },
    "dataStatus": [
      {
        "sourceId": "tushare_daily",
        "dataset": "daily",
        "tableName": "raw_tushare.daily",
        "dataDomain": "QUOTE",
        "status": "READY",
        "latestTradeDate": "2026-04-28",
        "latestDataTime": "2026-04-28T16:10:00+08:00",
        "completenessPct": 99.6
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
        "description": "进入分析页查看温度、情绪、资金与风险",
        "route": "/market/emotion",
        "enabled": true,
        "pendingCount": 0,
        "hasUpdate": true
      }
    ],
    "marketSummary": {
      "title": "A股市场事实概览",
      "facts": [
        {
          "label": "上涨家数",
          "value": 3421,
          "direction": "UP"
        },
        {
          "label": "下跌家数",
          "value": 1488,
          "direction": "DOWN"
        },
        {
          "label": "今日成交额",
          "value": 10523.0
        },
        {
          "label": "主力净流入",
          "value": 1211718400,
          "direction": "UP"
        },
        {
          "label": "涨停家数",
          "value": 59,
          "direction": "UP"
        }
      ],
      "forbiddenConclusion": true
    },
    "indices": [
      {
        "indexCode": "000001.SH",
        "indexName": "上证指数",
        "last": 3128.42,
        "change": 28.66,
        "changePct": 0.92,
        "direction": "UP"
      },
      {
        "indexCode": "399001.SZ",
        "indexName": "深证成指",
        "last": 9842.15,
        "change": -34.21,
        "changePct": -0.35,
        "direction": "DOWN"
      }
    ],
    "breadth": {
      "samplePool": "CN_A_COMMON",
      "totalCount": 5128,
      "riseCount": 3421,
      "fallCount": 1488,
      "flatCount": 219,
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
      "medianChangePct": 0.48,
      "styleLeader": "SMALL_CAP"
    },
    "turnover": {
      "todayTurnoverAmount": 10523.0,
      "previousTradeDate": "2026-04-27",
      "previousTurnoverAmount": 9821.0,
      "turnoverChangeAmount": 702.0,
      "turnoverChangePct": 7.15,
      "ma5TurnoverAmount": 10012.0,
      "ma20TurnoverAmount": 9360.0,
      "historyPoints": [
        {
          "tradeDate": "2026-04-28",
          "turnoverAmount": 10523.0,
          "prevTradeDate": "2026-04-27",
          "rangeType": "1m"
        }
      ]
    },
    "moneyFlow": {
      "todayNetInflowAmount": 1211718400,
      "previousTradeDate": "2026-04-27",
      "previousNetInflowAmount": -3910650112,
      "superLargeOrderNetInflow": 22524846080,
      "largeOrderNetInflow": 5433212928,
      "mediumOrderNetInflow": -1203000000,
      "smallOrderNetInflow": -2203000000,
      "historyPoints": [
        {
          "tradeDate": "2026-04-28",
          "netInflowAmount": 1211718400,
          "rangeType": "1m"
        }
      ]
    },
    "limitUp": {
      "tradeDate": "2026-04-28",
      "limitUpCount": 59,
      "limitDownCount": 8,
      "brokenLimitCount": 27,
      "sealRate": 0.686,
      "maxStreakLevel": 6
    },
    "limitUpDistribution": {
      "bySector": [
        {
          "categoryCode": "BK1184.DC",
          "categoryName": "人形机器人",
          "categoryType": "SECTOR",
          "limitUpCount": 6,
          "limitDownCount": 1,
          "brokenLimitCount": 2
        }
      ],
      "byLimitType": [
        {
          "categoryCode": "LIMIT_UP",
          "categoryName": "涨停",
          "categoryType": "LIMIT_TYPE",
          "limitUpCount": 59,
          "limitDownCount": 0,
          "brokenLimitCount": 0
        }
      ]
    },
    "streakLadder": {
      "tradeDate": "2026-04-28",
      "highestLevel": 6,
      "items": [
        {
          "stockCode": "002888.SZ",
          "stockName": "示例股份",
          "streakLevel": 3,
          "sectorName": "机器人",
          "latestPrice": 18.36,
          "changePct": 10.01,
          "direction": "UP",
          "openTimes": 1,
          "sealedAmount": 328000000,
          "firstLimitTime": "09:42:15"
        }
      ]
    },
    "sectorOverview": {
      "industryRiseTop5": [],
      "industryFallTop5": [],
      "conceptRiseTop5": [],
      "conceptFallTop5": [],
      "regionRiseTop5": [],
      "regionFallTop5": [],
      "moneyInflowTop5": [],
      "moneyOutflowTop5": [],
      "heatMapItems": [
        {
          "sectorCode": "BK1184.DC",
          "sectorName": "人形机器人",
          "sectorType": "CONCEPT",
          "changePct": 4.37,
          "direction": "UP",
          "turnoverAmount": 12860000000,
          "netInflowAmount": 2630000000,
          "riseStockCount": 32,
          "fallStockCount": 62,
          "rowIndex": 0,
          "colIndex": 0
        }
      ]
    },
    "leaderboards": {
      "top10": [
        {
          "rank": 1,
          "stockCode": "601099.SH",
          "stockName": "太平洋",
          "latestPrice": 4.82,
          "changePct": 3.21,
          "direction": "UP",
          "turnoverRate": 5.34,
          "volumeRatio": 2.18,
          "volume": 356200,
          "amount": 1865000
        }
      ]
    }
  },
  "traceId": "req_20260428_000001",
  "serverTime": "2026-04-28T17:12:00+08:00"
}
```

#### 字段说明

字段含义以《P0 数据字典 v0.5》为准。聚合接口只组合业务对象，不复刻 Tushare API。

#### 异常状态

| code | 场景 | 前端处理 |
|---:|---|---|
| `400001` | 参数错误 | 保留旧数据并提示参数错误 |
| `401001` | 未登录 | 基础行情游客态，用户相关字段降级 |
| `403001` | 无权限 | 展示无权限 |
| `404001` | 指定交易日无数据 | 展示空状态，可切换最近交易日 |
| `409001` | 非交易日请求盘中模式 | 提示状态冲突 |
| `429001` | 请求过快 | 前端退避 |
| `500001` | 服务异常 | 展示异常态 |
| `503001` | 数据源不可用 | 模块降级或读取缓存 |


#### 空数据处理

1. `indices` 为空：显示“指数数据暂不可用”。
2. `breadth` 为空：显示“涨跌分布暂不可用”。
3. `moneyFlow.status=PARTIAL/EMPTY`：只隐藏资金流模块，不影响首屏。
4. `sectorOverview.heatMapItems` 不足 20 条时，前端补空格并提示数据不足。
5. `leaderboards.top10` 为空：榜单表格空态。

#### 数据更新时间

| 模块 | 更新频率 |
|---|---|
| `indices` | 日频/按源，实时源接入后 15-60 秒 |
| `breadth` | 日频/按源，实时源接入后 15-60 秒 |
| `style` | 日频/按源 |
| `turnover` | 日频；日内源接入后 1-5 分钟 |
| `moneyFlow` | 按 `moneyflow_mkt_dc` 源，多数盘后 |
| `limitUp` | 按 `limit_list_d` 源，实时源接入后 15-60 秒 |
| `sectorOverview` | 日频/按源 |
| `leaderboards` | `dc_hot` 日内多次，行情榜按源 |

#### 缓存建议

聚合接口盘中缓存 15-60 秒；盘后缓存 1 天。历史序列、板块矩阵、榜单等应读取预聚合视图或缓存表。

#### 性能评估

聚合接口 P95 `<500ms`；payload 建议控制在 `180KB` 内；不得请求时实时扫描全量原始表。

#### 暂缺数据字段清单

实时全市场分钟成交额、实时资金流、实时封单变化、天地板/地天板稳定规则、板块平盘数、热力图排序算法。

#### 与页面模块的映射关系

| 页面模块 | 聚合字段 |
|---|---|
| TopMarketBar | `topMarketBar`、`dataStatus` |
| Breadcrumb | `breadcrumb` |
| ShortcutBar | `quickEntries` |
| 今日市场客观总结 | `marketSummary` |
| 主要指数 | `indices` |
| 涨跌分布 | `breadth` |
| 市场风格 | `style` |
| 成交额总览 | `turnover` |
| 大盘资金流 | `moneyFlow` |
| 涨跌停统计与分布 | `limitUp`、`limitUpDistribution` |
| 连板天梯 | `streakLadder` |
| 板块速览 | `sectorOverview` |
| 榜单速览 | `leaderboards` |

---

## 4. 模块接口

## GET /api/index/summary

### endpoint

```http
GET /api/index/summary
```

### method

`GET`

### 前端使用场景

主要指数卡片、TopMarketBar 指数条、指数详情页入口。

### request params

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---:|---|---|
| `market` | string | 否 | `CN_A` | P0 A 股 |
| `tradeDate` | string(date) | 否 | 最近交易日 | 指定交易日 |
| `indexCodes` | string | 否 | 系统默认核心指数 | 逗号分隔 |

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
        "change": 28.66,
        "changePct": 0.92,
        "direction": "UP"
      },
      {
        "indexCode": "399001.SZ",
        "indexName": "深证成指",
        "last": 9842.15,
        "change": -34.21,
        "changePct": -0.35,
        "direction": "DOWN"
      }
    ]
  },
  "traceId": "req_index_001",
  "serverTime": "2026-04-28T17:12:00+08:00"
}
```

### 字段说明

以《P0 数据字典 v0.5》对应对象为准；本接口不复刻 Tushare API 形态，只返回财势乾坤业务字段。

### 异常状态

| code | 场景 | 前端处理 |
|---:|---|---|
| `400001` | 参数错误 | 保留旧数据并提示参数错误 |
| `401001` | 未登录 | 基础行情游客态，用户相关字段降级 |
| `403001` | 无权限 | 展示无权限 |
| `404001` | 指定交易日无数据 | 展示空状态，可切换最近交易日 |
| `409001` | 非交易日请求盘中模式 | 提示状态冲突 |
| `429001` | 请求过快 | 前端退避 |
| `500001` | 服务异常 | 展示异常态 |
| `503001` | 数据源不可用 | 模块降级或读取缓存 |


### 空数据处理

1. 列表为空返回空数组 `[]`，不返回 `null`。
2. 模块数据不可用时返回 `dataStatus=PARTIAL` 或对应模块空态。
3. 核心首屏字段缺失时，前端展示局部异常，不整页白屏。

### 数据更新时间

按底层数据源和数据基座同步频率：行情类按源刷新，历史类盘后固定，配置类低频缓存。

### 缓存建议

盘中 15-60 秒；盘后 1 天；配置类 5 分钟至 1 天；历史序列 5-30 分钟。

### 性能评估

模块接口 P95 目标 `<200ms`；聚合接口 P95 目标 `<500ms`。必须读取预聚合/物化视图，不允许请求时实时扫全量原始表。

### 暂缺数据字段清单

实时源、分钟聚合、样本池过滤、板块精算字段按模块情况可能缺失，详见文末清单。

### 与页面模块的映射关系

主要指数、TopMarketBar 指数条。


## GET /api/market/breadth

### endpoint

```http
GET /api/market/breadth
```

### method

`GET`

### 前端使用场景

涨跌分布模块局部刷新，支持市场广度和涨跌幅分桶。

### request params

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---:|---|---|
| `market` | string | 否 | `CN_A` | 市场 |
| `tradeDate` | string(date) | 否 | 最近交易日 | 交易日 |
| `samplePool` | string | 否 | `CN_A_COMMON` | 样本池 |

### response JSON / Mock 数据示例

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "samplePool": "CN_A_COMMON",
    "totalCount": 5128,
    "riseCount": 3421,
    "fallCount": 1488,
    "flatCount": 219,
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
  "traceId": "req_breadth_001",
  "serverTime": "2026-04-28T17:12:00+08:00"
}
```

### 字段说明

以《P0 数据字典 v0.5》对应对象为准；本接口不复刻 Tushare API 形态，只返回财势乾坤业务字段。

### 异常状态

| code | 场景 | 前端处理 |
|---:|---|---|
| `400001` | 参数错误 | 保留旧数据并提示参数错误 |
| `401001` | 未登录 | 基础行情游客态，用户相关字段降级 |
| `403001` | 无权限 | 展示无权限 |
| `404001` | 指定交易日无数据 | 展示空状态，可切换最近交易日 |
| `409001` | 非交易日请求盘中模式 | 提示状态冲突 |
| `429001` | 请求过快 | 前端退避 |
| `500001` | 服务异常 | 展示异常态 |
| `503001` | 数据源不可用 | 模块降级或读取缓存 |


### 空数据处理

1. 列表为空返回空数组 `[]`，不返回 `null`。
2. 模块数据不可用时返回 `dataStatus=PARTIAL` 或对应模块空态。
3. 核心首屏字段缺失时，前端展示局部异常，不整页白屏。

### 数据更新时间

按底层数据源和数据基座同步频率：行情类按源刷新，历史类盘后固定，配置类低频缓存。

### 缓存建议

盘中 15-60 秒；盘后 1 天；配置类 5 分钟至 1 天；历史序列 5-30 分钟。

### 性能评估

模块接口 P95 目标 `<200ms`；聚合接口 P95 目标 `<500ms`。必须读取预聚合/物化视图，不允许请求时实时扫全量原始表。

### 暂缺数据字段清单

实时源、分钟聚合、样本池过滤、板块精算字段按模块情况可能缺失，详见文末清单。

### 与页面模块的映射关系

涨跌分布、市场广度面板。


## GET /api/market/style

### endpoint

```http
GET /api/market/style
```

### method

`GET`

### 前端使用场景

市场风格模块局部刷新。

### request params

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---:|---|---|
| `market` | string | 否 | `CN_A` | 市场 |
| `tradeDate` | string(date) | 否 | 最近交易日 | 交易日 |

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
    "medianChangePct": 0.48,
    "styleLeader": "SMALL_CAP"
  },
  "traceId": "req_style_001",
  "serverTime": "2026-04-28T17:12:00+08:00"
}
```

### 字段说明

以《P0 数据字典 v0.5》对应对象为准；本接口不复刻 Tushare API 形态，只返回财势乾坤业务字段。

### 异常状态

| code | 场景 | 前端处理 |
|---:|---|---|
| `400001` | 参数错误 | 保留旧数据并提示参数错误 |
| `401001` | 未登录 | 基础行情游客态，用户相关字段降级 |
| `403001` | 无权限 | 展示无权限 |
| `404001` | 指定交易日无数据 | 展示空状态，可切换最近交易日 |
| `409001` | 非交易日请求盘中模式 | 提示状态冲突 |
| `429001` | 请求过快 | 前端退避 |
| `500001` | 服务异常 | 展示异常态 |
| `503001` | 数据源不可用 | 模块降级或读取缓存 |


### 空数据处理

1. 列表为空返回空数组 `[]`，不返回 `null`。
2. 模块数据不可用时返回 `dataStatus=PARTIAL` 或对应模块空态。
3. 核心首屏字段缺失时，前端展示局部异常，不整页白屏。

### 数据更新时间

按底层数据源和数据基座同步频率：行情类按源刷新，历史类盘后固定，配置类低频缓存。

### 缓存建议

盘中 15-60 秒；盘后 1 天；配置类 5 分钟至 1 天；历史序列 5-30 分钟。

### 性能评估

模块接口 P95 目标 `<200ms`；聚合接口 P95 目标 `<500ms`。必须读取预聚合/物化视图，不允许请求时实时扫全量原始表。

### 暂缺数据字段清单

实时源、分钟聚合、样本池过滤、板块精算字段按模块情况可能缺失，详见文末清单。

### 与页面模块的映射关系

市场风格模块。


## GET /api/market/turnover

### endpoint

```http
GET /api/market/turnover
```

### method

`GET`

### 前端使用场景

成交额总览模块局部刷新。

### request params

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---:|---|---|
| `market` | string | 否 | `CN_A` | 市场 |
| `tradeDate` | string(date) | 否 | 最近交易日 | 交易日 |
| `includeHistory` | boolean | 否 | `true` | 是否返回历史点 |

### response JSON / Mock 数据示例

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "todayTurnoverAmount": 10523.0,
    "previousTradeDate": "2026-04-27",
    "previousTurnoverAmount": 9821.0,
    "turnoverChangeAmount": 702.0,
    "turnoverChangePct": 7.15,
    "ma5TurnoverAmount": 10012.0,
    "ma20TurnoverAmount": 9360.0,
    "historyPoints": [
      {
        "tradeDate": "2026-04-28",
        "turnoverAmount": 10523.0,
        "prevTradeDate": "2026-04-27",
        "rangeType": "1m"
      }
    ]
  },
  "traceId": "req_turnover_001",
  "serverTime": "2026-04-28T17:12:00+08:00"
}
```

### 字段说明

以《P0 数据字典 v0.5》对应对象为准；本接口不复刻 Tushare API 形态，只返回财势乾坤业务字段。

### 异常状态

| code | 场景 | 前端处理 |
|---:|---|---|
| `400001` | 参数错误 | 保留旧数据并提示参数错误 |
| `401001` | 未登录 | 基础行情游客态，用户相关字段降级 |
| `403001` | 无权限 | 展示无权限 |
| `404001` | 指定交易日无数据 | 展示空状态，可切换最近交易日 |
| `409001` | 非交易日请求盘中模式 | 提示状态冲突 |
| `429001` | 请求过快 | 前端退避 |
| `500001` | 服务异常 | 展示异常态 |
| `503001` | 数据源不可用 | 模块降级或读取缓存 |


### 空数据处理

1. 列表为空返回空数组 `[]`，不返回 `null`。
2. 模块数据不可用时返回 `dataStatus=PARTIAL` 或对应模块空态。
3. 核心首屏字段缺失时，前端展示局部异常，不整页白屏。

### 数据更新时间

按底层数据源和数据基座同步频率：行情类按源刷新，历史类盘后固定，配置类低频缓存。

### 缓存建议

盘中 15-60 秒；盘后 1 天；配置类 5 分钟至 1 天；历史序列 5-30 分钟。

### 性能评估

模块接口 P95 目标 `<200ms`；聚合接口 P95 目标 `<500ms`。必须读取预聚合/物化视图，不允许请求时实时扫全量原始表。

### 暂缺数据字段清单

实时源、分钟聚合、样本池过滤、板块精算字段按模块情况可能缺失，详见文末清单。

### 与页面模块的映射关系

成交额总览、历史成交额图。


## GET /api/moneyflow/market

### endpoint

```http
GET /api/moneyflow/market
```

### method

`GET`

### 前端使用场景

大盘资金流向模块局部刷新。

### request params

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---:|---|---|
| `market` | string | 否 | `CN_A` | 市场 |
| `tradeDate` | string(date) | 否 | 最近交易日 | 交易日 |
| `includeHistory` | boolean | 否 | `true` | 是否返回历史资金流 |

### response JSON / Mock 数据示例

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "todayNetInflowAmount": 1211718400,
    "previousTradeDate": "2026-04-27",
    "previousNetInflowAmount": -3910650112,
    "superLargeOrderNetInflow": 22524846080,
    "largeOrderNetInflow": 5433212928,
    "mediumOrderNetInflow": -1203000000,
    "smallOrderNetInflow": -2203000000,
    "historyPoints": [
      {
        "tradeDate": "2026-04-28",
        "netInflowAmount": 1211718400,
        "rangeType": "1m"
      }
    ]
  },
  "traceId": "req_moneyflow_001",
  "serverTime": "2026-04-28T17:12:00+08:00"
}
```

### 字段说明

以《P0 数据字典 v0.5》对应对象为准；本接口不复刻 Tushare API 形态，只返回财势乾坤业务字段。

### 异常状态

| code | 场景 | 前端处理 |
|---:|---|---|
| `400001` | 参数错误 | 保留旧数据并提示参数错误 |
| `401001` | 未登录 | 基础行情游客态，用户相关字段降级 |
| `403001` | 无权限 | 展示无权限 |
| `404001` | 指定交易日无数据 | 展示空状态，可切换最近交易日 |
| `409001` | 非交易日请求盘中模式 | 提示状态冲突 |
| `429001` | 请求过快 | 前端退避 |
| `500001` | 服务异常 | 展示异常态 |
| `503001` | 数据源不可用 | 模块降级或读取缓存 |


### 空数据处理

1. 列表为空返回空数组 `[]`，不返回 `null`。
2. 模块数据不可用时返回 `dataStatus=PARTIAL` 或对应模块空态。
3. 核心首屏字段缺失时，前端展示局部异常，不整页白屏。

### 数据更新时间

按底层数据源和数据基座同步频率：行情类按源刷新，历史类盘后固定，配置类低频缓存。

### 缓存建议

盘中 15-60 秒；盘后 1 天；配置类 5 分钟至 1 天；历史序列 5-30 分钟。

### 性能评估

模块接口 P95 目标 `<200ms`；聚合接口 P95 目标 `<500ms`。必须读取预聚合/物化视图，不允许请求时实时扫全量原始表。

### 暂缺数据字段清单

实时源、分钟聚合、样本池过滤、板块精算字段按模块情况可能缺失，详见文末清单。

### 与页面模块的映射关系

大盘资金流向。


## GET /api/limitup/summary

### endpoint

```http
GET /api/limitup/summary
```

### method

`GET`

### 前端使用场景

涨跌停统计与分布模块局部刷新。

### request params

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---:|---|---|
| `market` | string | 否 | `CN_A` | 市场 |
| `tradeDate` | string(date) | 否 | 最近交易日 | 交易日 |
| `includeDistribution` | boolean | 否 | `true` | 是否返回分布 |

### response JSON / Mock 数据示例

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "summary": {
      "tradeDate": "2026-04-28",
      "limitUpCount": 59,
      "limitDownCount": 8,
      "brokenLimitCount": 27,
      "sealRate": 0.686,
      "maxStreakLevel": 6
    },
    "distribution": {
      "bySector": [
        {
          "categoryCode": "BK1184.DC",
          "categoryName": "人形机器人",
          "categoryType": "SECTOR",
          "limitUpCount": 6,
          "limitDownCount": 1,
          "brokenLimitCount": 2
        }
      ],
      "byLimitType": [
        {
          "categoryCode": "LIMIT_UP",
          "categoryName": "涨停",
          "categoryType": "LIMIT_TYPE",
          "limitUpCount": 59,
          "limitDownCount": 0,
          "brokenLimitCount": 0
        }
      ]
    }
  },
  "traceId": "req_limitup_001",
  "serverTime": "2026-04-28T17:12:00+08:00"
}
```

### 字段说明

以《P0 数据字典 v0.5》对应对象为准；本接口不复刻 Tushare API 形态，只返回财势乾坤业务字段。

### 异常状态

| code | 场景 | 前端处理 |
|---:|---|---|
| `400001` | 参数错误 | 保留旧数据并提示参数错误 |
| `401001` | 未登录 | 基础行情游客态，用户相关字段降级 |
| `403001` | 无权限 | 展示无权限 |
| `404001` | 指定交易日无数据 | 展示空状态，可切换最近交易日 |
| `409001` | 非交易日请求盘中模式 | 提示状态冲突 |
| `429001` | 请求过快 | 前端退避 |
| `500001` | 服务异常 | 展示异常态 |
| `503001` | 数据源不可用 | 模块降级或读取缓存 |


### 空数据处理

1. 列表为空返回空数组 `[]`，不返回 `null`。
2. 模块数据不可用时返回 `dataStatus=PARTIAL` 或对应模块空态。
3. 核心首屏字段缺失时，前端展示局部异常，不整页白屏。

### 数据更新时间

按底层数据源和数据基座同步频率：行情类按源刷新，历史类盘后固定，配置类低频缓存。

### 缓存建议

盘中 15-60 秒；盘后 1 天；配置类 5 分钟至 1 天；历史序列 5-30 分钟。

### 性能评估

模块接口 P95 目标 `<200ms`；聚合接口 P95 目标 `<500ms`。必须读取预聚合/物化视图，不允许请求时实时扫全量原始表。

### 暂缺数据字段清单

实时源、分钟聚合、样本池过滤、板块精算字段按模块情况可能缺失，详见文末清单。

### 与页面模块的映射关系

涨跌停统计与分布。


## GET /api/limitup/streak-ladder

### endpoint

```http
GET /api/limitup/streak-ladder
```

### method

`GET`

### 前端使用场景

连板天梯局部刷新。

### request params

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---:|---|---|
| `market` | string | 否 | `CN_A` | 市场 |
| `tradeDate` | string(date) | 否 | 最近交易日 | 交易日 |
| `minLevel` | integer | 否 | `1` | 最小连板层级 |

### response JSON / Mock 数据示例

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "tradeDate": "2026-04-28",
    "highestLevel": 6,
    "items": [
      {
        "stockCode": "002888.SZ",
        "stockName": "示例股份",
        "streakLevel": 3,
        "sectorName": "机器人",
        "latestPrice": 18.36,
        "changePct": 10.01,
        "direction": "UP",
        "openTimes": 1,
        "sealedAmount": 328000000,
        "firstLimitTime": "09:42:15"
      }
    ]
  },
  "traceId": "req_streak_001",
  "serverTime": "2026-04-28T17:12:00+08:00"
}
```

### 字段说明

以《P0 数据字典 v0.5》对应对象为准；本接口不复刻 Tushare API 形态，只返回财势乾坤业务字段。

### 异常状态

| code | 场景 | 前端处理 |
|---:|---|---|
| `400001` | 参数错误 | 保留旧数据并提示参数错误 |
| `401001` | 未登录 | 基础行情游客态，用户相关字段降级 |
| `403001` | 无权限 | 展示无权限 |
| `404001` | 指定交易日无数据 | 展示空状态，可切换最近交易日 |
| `409001` | 非交易日请求盘中模式 | 提示状态冲突 |
| `429001` | 请求过快 | 前端退避 |
| `500001` | 服务异常 | 展示异常态 |
| `503001` | 数据源不可用 | 模块降级或读取缓存 |


### 空数据处理

1. 列表为空返回空数组 `[]`，不返回 `null`。
2. 模块数据不可用时返回 `dataStatus=PARTIAL` 或对应模块空态。
3. 核心首屏字段缺失时，前端展示局部异常，不整页白屏。

### 数据更新时间

按底层数据源和数据基座同步频率：行情类按源刷新，历史类盘后固定，配置类低频缓存。

### 缓存建议

盘中 15-60 秒；盘后 1 天；配置类 5 分钟至 1 天；历史序列 5-30 分钟。

### 性能评估

模块接口 P95 目标 `<200ms`；聚合接口 P95 目标 `<500ms`。必须读取预聚合/物化视图，不允许请求时实时扫全量原始表。

### 暂缺数据字段清单

实时源、分钟聚合、样本池过滤、板块精算字段按模块情况可能缺失，详见文末清单。

### 与页面模块的映射关系

连板天梯。


## GET /api/sector/top

### endpoint

```http
GET /api/sector/top
```

### method

`GET`

### 前端使用场景

板块速览局部刷新，支持行业、概念、地域、资金流入流出和热力图。

### request params

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---:|---|---|
| `market` | string | 否 | `CN_A` | 市场 |
| `tradeDate` | string(date) | 否 | 最近交易日 | 交易日 |
| `sectorType` | enum | 否 | `ALL` | INDUSTRY / CONCEPT / REGION / ALL |
| `rankBy` | enum | 否 | `changePct` | changePct / netInflowAmount / amount |
| `limit` | integer | 否 | `5` | Top N |
| `includeHeatMap` | boolean | 否 | `true` | 是否返回热力图 |

### response JSON / Mock 数据示例

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "industryRiseTop5": [],
    "industryFallTop5": [],
    "conceptRiseTop5": [],
    "conceptFallTop5": [],
    "regionRiseTop5": [],
    "regionFallTop5": [],
    "moneyInflowTop5": [],
    "moneyOutflowTop5": [],
    "heatMapItems": [
      {
        "sectorCode": "BK1184.DC",
        "sectorName": "人形机器人",
        "sectorType": "CONCEPT",
        "changePct": 4.37,
        "direction": "UP",
        "turnoverAmount": 12860000000,
        "netInflowAmount": 2630000000,
        "riseStockCount": 32,
        "fallStockCount": 62,
        "rowIndex": 0,
        "colIndex": 0
      }
    ]
  },
  "traceId": "req_sector_001",
  "serverTime": "2026-04-28T17:12:00+08:00"
}
```

### 字段说明

以《P0 数据字典 v0.5》对应对象为准；本接口不复刻 Tushare API 形态，只返回财势乾坤业务字段。

### 异常状态

| code | 场景 | 前端处理 |
|---:|---|---|
| `400001` | 参数错误 | 保留旧数据并提示参数错误 |
| `401001` | 未登录 | 基础行情游客态，用户相关字段降级 |
| `403001` | 无权限 | 展示无权限 |
| `404001` | 指定交易日无数据 | 展示空状态，可切换最近交易日 |
| `409001` | 非交易日请求盘中模式 | 提示状态冲突 |
| `429001` | 请求过快 | 前端退避 |
| `500001` | 服务异常 | 展示异常态 |
| `503001` | 数据源不可用 | 模块降级或读取缓存 |


### 空数据处理

1. 列表为空返回空数组 `[]`，不返回 `null`。
2. 模块数据不可用时返回 `dataStatus=PARTIAL` 或对应模块空态。
3. 核心首屏字段缺失时，前端展示局部异常，不整页白屏。

### 数据更新时间

按底层数据源和数据基座同步频率：行情类按源刷新，历史类盘后固定，配置类低频缓存。

### 缓存建议

盘中 15-60 秒；盘后 1 天；配置类 5 分钟至 1 天；历史序列 5-30 分钟。

### 性能评估

模块接口 P95 目标 `<200ms`；聚合接口 P95 目标 `<500ms`。必须读取预聚合/物化视图，不允许请求时实时扫全量原始表。

### 暂缺数据字段清单

实时源、分钟聚合、样本池过滤、板块精算字段按模块情况可能缺失，详见文末清单。

### 与页面模块的映射关系

板块速览、板块热力图。


## GET /api/leaderboard/stock

### endpoint

```http
GET /api/leaderboard/stock
```

### method

`GET`

### 前端使用场景

榜单速览局部刷新，支持 Top10 表格。

### request params

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---:|---|---|
| `market` | string | 否 | `CN_A` | 市场 |
| `tradeDate` | string(date) | 否 | 最近交易日 | 交易日 |
| `rankType` | enum | 否 | `POPULAR` | POPULAR / SURGE / GAINER / LOSER / AMOUNT / TURNOVER / VOLUME_RATIO |
| `limit` | integer | 否 | `10` | Top N |

### response JSON / Mock 数据示例

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "items": [
      {
        "rank": 1,
        "stockCode": "601099.SH",
        "stockName": "太平洋",
        "latestPrice": 4.82,
        "changePct": 3.21,
        "direction": "UP",
        "turnoverRate": 5.34,
        "volumeRatio": 2.18,
        "volume": 356200,
        "amount": 1865000
      }
    ]
  },
  "traceId": "req_leaderboard_001",
  "serverTime": "2026-04-28T17:12:00+08:00"
}
```

### 字段说明

以《P0 数据字典 v0.5》对应对象为准；本接口不复刻 Tushare API 形态，只返回财势乾坤业务字段。

### 异常状态

| code | 场景 | 前端处理 |
|---:|---|---|
| `400001` | 参数错误 | 保留旧数据并提示参数错误 |
| `401001` | 未登录 | 基础行情游客态，用户相关字段降级 |
| `403001` | 无权限 | 展示无权限 |
| `404001` | 指定交易日无数据 | 展示空状态，可切换最近交易日 |
| `409001` | 非交易日请求盘中模式 | 提示状态冲突 |
| `429001` | 请求过快 | 前端退避 |
| `500001` | 服务异常 | 展示异常态 |
| `503001` | 数据源不可用 | 模块降级或读取缓存 |


### 空数据处理

1. 列表为空返回空数组 `[]`，不返回 `null`。
2. 模块数据不可用时返回 `dataStatus=PARTIAL` 或对应模块空态。
3. 核心首屏字段缺失时，前端展示局部异常，不整页白屏。

### 数据更新时间

按底层数据源和数据基座同步频率：行情类按源刷新，历史类盘后固定，配置类低频缓存。

### 缓存建议

盘中 15-60 秒；盘后 1 天；配置类 5 分钟至 1 天；历史序列 5-30 分钟。

### 性能评估

模块接口 P95 目标 `<200ms`；聚合接口 P95 目标 `<500ms`。必须读取预聚合/物化视图，不允许请求时实时扫全量原始表。

### 暂缺数据字段清单

实时源、分钟聚合、样本池过滤、板块精算字段按模块情况可能缺失，详见文末清单。

### 与页面模块的映射关系

榜单速览 Top10 表格。


## GET /api/settings/quick-entry

### endpoint

```http
GET /api/settings/quick-entry
```

### method

`GET`

### 前端使用场景

ShortcutBar 快捷入口配置和用户状态局部刷新。

### request params

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---:|---|---|
| `scene` | string | 否 | `MARKET_OVERVIEW` | 使用场景 |
| `userId` | string | 否 | 当前用户 | 游客可为空 |

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
        "description": "进入分析页查看温度、情绪、资金与风险",
        "route": "/market/emotion",
        "enabled": true,
        "pendingCount": 0,
        "hasUpdate": true
      }
    ]
  },
  "traceId": "req_quick_001",
  "serverTime": "2026-04-28T17:12:00+08:00"
}
```

### 字段说明

以《P0 数据字典 v0.5》对应对象为准；本接口不复刻 Tushare API 形态，只返回财势乾坤业务字段。

### 异常状态

| code | 场景 | 前端处理 |
|---:|---|---|
| `400001` | 参数错误 | 保留旧数据并提示参数错误 |
| `401001` | 未登录 | 基础行情游客态，用户相关字段降级 |
| `403001` | 无权限 | 展示无权限 |
| `404001` | 指定交易日无数据 | 展示空状态，可切换最近交易日 |
| `409001` | 非交易日请求盘中模式 | 提示状态冲突 |
| `429001` | 请求过快 | 前端退避 |
| `500001` | 服务异常 | 展示异常态 |
| `503001` | 数据源不可用 | 模块降级或读取缓存 |


### 空数据处理

1. 列表为空返回空数组 `[]`，不返回 `null`。
2. 模块数据不可用时返回 `dataStatus=PARTIAL` 或对应模块空态。
3. 核心首屏字段缺失时，前端展示局部异常，不整页白屏。

### 数据更新时间

按底层数据源和数据基座同步频率：行情类按源刷新，历史类盘后固定，配置类低频缓存。

### 缓存建议

盘中 15-60 秒；盘后 1 天；配置类 5 分钟至 1 天；历史序列 5-30 分钟。

### 性能评估

模块接口 P95 目标 `<200ms`；聚合接口 P95 目标 `<500ms`。必须读取预聚合/物化视图，不允许请求时实时扫全量原始表。

### 暂缺数据字段清单

实时源、分钟聚合、样本池过滤、板块精算字段按模块情况可能缺失，详见文末清单。

### 与页面模块的映射关系

ShortcutBar 快捷入口。


---

## 5. 文档末尾清单

### 5.1 聚合接口和模块接口的推荐使用方式

1. 首屏加载调用 `GET /api/market/home-overview`。
2. 用户切换单个模块状态、刷新单个模块、下钻复用时调用模块接口。
3. 历史序列、热力图、榜单等建议使用模块级缓存和预聚合视图。
4. 非核心模块失败时聚合接口返回 `PARTIAL`，前端局部降级。

### 5.2 市场总览页面模块与 API 字段映射表

| 页面模块 | 聚合字段 | 模块接口 |
|---|---|---|
| TopMarketBar | `topMarketBar` | `/api/index/summary` |
| Breadcrumb | `breadcrumb` | 聚合返回 |
| ShortcutBar | `quickEntries` | `/api/settings/quick-entry` |
| 今日市场客观总结 | `marketSummary` | 聚合返回 |
| 主要指数 | `indices` | `/api/index/summary` |
| 涨跌分布 | `breadth` | `/api/market/breadth` |
| 市场风格 | `style` | `/api/market/style` |
| 成交额总览 | `turnover` | `/api/market/turnover` |
| 大盘资金流 | `moneyFlow` | `/api/moneyflow/market` |
| 涨跌停统计与分布 | `limitUp`、`limitUpDistribution` | `/api/limitup/summary` |
| 连板天梯 | `streakLadder` | `/api/limitup/streak-ladder` |
| 板块速览 | `sectorOverview` | `/api/sector/top` |
| 榜单速览 | `leaderboards` | `/api/leaderboard/stock` |

### 5.3 给 02 HTML Showcase 的 Mock 数据建议

1. 直接使用 `home_response` 作为根 mock。
2. 指数至少 10 个，榜单 Top10，板块每组 Top5，热力图至少 20 条。
3. 所有涨跌项提供 `direction`。
4. 快捷入口不得出现市场温度/情绪/资金面/风险具体数值。
5. 资金流正负值明确，Tooltip 正红负绿。
6. 空态、加载态、异常态均按模块级处理。

### 5.4 给 03 组件库的 Props 映射建议

| 组件 | Props |
|---|---|
| `TopMarketBar` | `topMarketBar` |
| `Breadcrumb` | `breadcrumb` |
| `ShortcutBar` | `quickEntries` |
| `MarketObjectiveSummaryPanel` | `marketSummary` |
| `IndexGrid` | `indices` |
| `MarketBreadthPanel` | `breadth` |
| `MarketStylePanel` | `style` |
| `TurnoverPanel` | `turnover` |
| `MoneyFlowPanel` | `moneyFlow` |
| `LimitUpPanel` | `limitUp`、`limitUpDistribution` |
| `StreakLadder` | `streakLadder` |
| `SectorOverviewMatrix` | `sectorOverview` |
| `LeaderboardTop10Table` | `leaderboards.top10` |

### 5.5 给 05 Codex 提示词的 API 约束

1. 以 `/api/market/home-overview` 的 mock 作为页面数据根对象。
2. 不允许新增主观分数或交易建议字段。
3. 严格按 `direction` 做红涨绿跌。
4. 金额、成交量单位按 API 字段说明展示。
5. 空值显示 `--`。
6. 模块异常不导致整页白屏。
7. 榜单列顺序固定为：排名｜股票｜最新价｜涨跌幅｜换手率｜量比｜成交量｜成交额。

### 5.6 P0 已具备字段

| 能力 | 来源 |
|---|---|
| 交易日、上一交易日 | `trade_cal` |
| 指数行情 | `index_daily` |
| 个股行情、市场广度、成交额 | `daily` |
| 换手率、量比、市值 | `daily_basic` |
| 大盘资金流 | `moneyflow_mkt_dc` |
| 涨跌停、炸板、连板 | `limit_list_d` |
| 涨跌停价格 | `stk_limit` |
| 行业/概念/地域板块 | `dc_index`、`dc_member`、`dc_daily` |
| 板块资金流 | `moneyflow_ind_dc` |
| 热榜 | `dc_hot` |

### 5.7 P0 暂缺字段

| 字段/能力 | 原因 |
|---|---|
| 实时全市场分钟级成交额 | 需建设分钟聚合视图或接入实时源 |
| 实时资金流 | 当前 `moneyflow_mkt_dc` 更偏盘后/按源 |
| 实时封单变化 | 需实时涨跌停源 |
| 天地板/地天板 | 需稳定规则确认 |
| 板块平盘家数 | `dc_index` 仅有 `up_num/down_num`，需 `dc_member + daily` 精算 |
| 热力图排序算法 | 需产品确认按涨跌幅、成交额、资金流还是综合 |

### 5.8 需要数据基座补充的字段/视图

1. `wealth_market_home_overview_snapshot`
2. `wealth_market_breadth_snapshot`
3. `wealth_turnover_summary_snapshot`
4. `wealth_moneyflow_market_snapshot`
5. `wealth_limitup_snapshot`
6. `wealth_limitup_distribution_snapshot`
7. `wealth_limitup_streak_ladder_snapshot`
8. `wealth_sector_overview_matrix_snapshot`
9. `wealth_sector_heatmap_snapshot`
10. `wealth_stock_leaderboard_snapshot`
11. `wealth_data_source_status`

### 5.9 待产品总控确认问题

1. 榜单速览默认采用 `dc_hot` 热榜，还是传统涨幅/成交额/换手/量比榜？
2. 市场广度样本池是否排除 ST、新股、停牌、无涨跌幅限制股票？
3. 热力图排序依据：涨跌幅、成交额、资金净流入，还是综合排序？
4. 天地板/地天板是否进入市场总览 P0 首屏？
5. 资金流数据盘中缺失时是否允许显示最近盘后数据并标记 `DELAYED`？
