# 财势乾坤｜市场总览 API 草案 v0.4

建议保存路径：`/docs/wealth/api/market-overview-api.md`  
公共区建议保存路径：`财势乾坤/数据字典与API文档/market-overview-api-v0.4.md`  
负责人：`04_API 契约与数据字典`  
版本：`v0.4`  
状态：`HTML Review v2 全量修订稿`  
更新时间：`2026-05-07`

---

## 本轮实际读取的公共区文件

| 序号 | 文件名 | 实际读取到的版本 / 状态 |
|---:|---|---|
| 1 | `财势乾坤行情软件项目总说明_v_0_2.md` | `财势乾坤项目总说明 v0.2`，Review 草案 v0.2 |
| 2 | `市场总览产品需求文档 v0.2.md` | `市场总览产品需求文档 v0.2`，Review 草案 |
| 3 | `02-market-overview-page-design.md` | `市场总览页面设计文档 v0.1` |
| 4 | `04-component-guidelines.md` | `P0 组件库与交互组件方案 v0.3`，Draft v0.3 |
| 5 | `p0-data-dictionary-v0.4.md` | `P0 数据字典 v0.4`，HTML Review v1 补字段修订稿 |
| 6 | `market-overview-api-v0.4.md` | `市场总览 API 草案 v0.4`，HTML Review v1 补字段修订稿 |
| 7 | `market-overview-html-review-v2.md` | `市场总览页review-v2` |
| 8 | `市场总览html_review_v_2_总控解读与变更单.md` | `市场总览 HTML Review v2｜总控解读与变更单`，目标 `market-overview-v1.2.html` |
| 9 | `tushare接口文档/README.md` | Tushare 接口说明目录（本地镜像） |
| 10 | `tushare接口文档/docs_index.csv` | Tushare 文档总索引，含 `doc_id/title/api_name/local_path` |


---

## 0. 本轮 Review v2 修订范围

本版是完整全量文档，包含此前 v0.4 已确认内容，并仅对 Review v2 明确点名区域做修订：

1. 今日市场客观总结与主要指数左右结构所需字段；
2. 榜单速览 Top10 表格字段；
3. 涨跌停统计与分布 2×2 区域字段；
4. 板块速览 4列×2行榜单矩阵 + 右侧跨两行 5×4 热力图字段。

本轮不主动修改：资金流、成交额、市场风格、涨跌分布、连板天梯、路由、ShortcutBar、TopMarketBar 等未被 Review v2 点名的模块。

---

## 1. 统一响应结构与错误码

### 1.1 响应结构

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
| `403001` | 无权限 | 403 | 展示无权限提示 |
| `404001` | 数据不存在 | 404 | 展示空状态 |
| `409001` | 状态冲突 | 409 | 例如非交易日请求盘中数据 |
| `429001` | 请求过快 | 429 | 降频重试 |
| `500001` | 服务异常 | 500 | 异常态 + 重试 |
| `503001` | 数据源不可用 | 503 | 使用最近缓存或模块降级 |

### 1.3 禁止字段

市场总览聚合接口和模块接口不得把以下字段作为核心字段返回：

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

---

## 2. 推荐接口策略

| 场景 | 推荐接口 | 本轮是否修改 |
|---|---|---|
| 页面首屏加载 | `GET /api/market/home-overview` | 是，仅修订 v2 点名字段 |
| 榜单速览局部刷新 | `GET /api/leaderboard/stock` | 是 |
| 涨跌停统计与分布局部刷新 | `GET /api/limitup/summary` | 是 |
| 板块速览局部刷新 | `GET /api/sector/top` | 是 |
| 其它模块局部刷新 | 原 v0.4 模块接口 | 否 |

---

## 3. GET /api/market/home-overview

### endpoint

```http
GET /api/market/home-overview
```

### method

`GET`

### 前端使用场景

市场总览首屏和主体模块加载。Review v2 重点要求该聚合接口覆盖：

1. `marketSummary`：左侧 5 个事实卡 + 说明卡；
2. `indices`：右侧主要指数 2 行 × 5 个；
3. `leaderboards`：Top10，列包含换手率、量比、成交量、成交额；
4. `limitUp`：2×2 结构；
5. `sectorOverview`：8 个 Top5 + 20 个热力图格子。

### request params

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---:|---|---|
| `market` | string | 否 | `CN_A` | P0 固定 A 股 |
| `tradeDate` | string(date) | 否 | 最近交易日 | 指定交易日 |
| `dataMode` | enum | 否 | `latest` | `latest` / `eod` / `replay` |
| `leaderboardLimit` | integer | 否 | `10` | Review v2 要求 Top10 |
| `sectorTopLimit` | integer | 否 | `5` | Review v2 要求每组 Top5 |
| `heatMapRows` | integer | 否 | `5` | 热力图行数 |
| `heatMapCols` | integer | 否 | `4` | 热力图列数 |

### response JSON / Mock 数据示例

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
    "marketSummary": {
      "layout": "LEFT_HALF",
      "cards": [
        {
          "key": "riseCount",
          "label": "上涨家数",
          "value": 3421,
          "unit": "只",
          "direction": "UP",
          "displayText": "3421只"
        },
        {
          "key": "fallCount",
          "label": "下跌家数",
          "value": 1488,
          "unit": "只",
          "direction": "DOWN",
          "displayText": "1488只"
        },
        {
          "key": "todayTurnoverAmount",
          "label": "今日成交额",
          "value": 10523.0,
          "unit": "daily.amount源聚合口径",
          "displayText": "1.05万亿"
        },
        {
          "key": "todayNetInflowAmount",
          "label": "主力净流入",
          "value": 1211718400,
          "unit": "元",
          "direction": "UP",
          "displayText": "+12.12亿"
        },
        {
          "key": "limitUpCount",
          "label": "涨停家数",
          "value": 59,
          "unit": "只",
          "direction": "UP",
          "displayText": "59只"
        }
      ],
      "textCard": {
        "title": "客观事实说明",
        "content": "本页仅展示A股市场客观运行事实，不展示市场温度、情绪指数、资金面分数或风险指数，不构成投资建议。",
        "tooltip": "更多分析请进入市场温度与情绪页面。"
      },
      "forbiddenConclusion": true
    },
    "indices": [
      {
        "indexCode": "000001.SH",
        "indexName": "上证指数",
        "last": 3128.42,
        "change": 28.66,
        "changePct": 0.92,
        "direction": "UP",
        "amount": 482300000,
        "gridRow": 1,
        "gridCol": 1
      },
      {
        "indexCode": "399001.SZ",
        "indexName": "深证成指",
        "last": 9842.15,
        "change": -34.21,
        "changePct": -0.35,
        "direction": "DOWN",
        "amount": 598400000,
        "gridRow": 1,
        "gridCol": 2
      },
      {
        "indexCode": "399006.SZ",
        "indexName": "创业板指",
        "last": 1928.16,
        "change": 18.16,
        "changePct": 0.95,
        "direction": "UP",
        "gridRow": 1,
        "gridCol": 3
      },
      {
        "indexCode": "000300.SH",
        "indexName": "沪深300",
        "last": 3688.32,
        "change": 26.32,
        "changePct": 0.72,
        "direction": "UP",
        "gridRow": 1,
        "gridCol": 4
      },
      {
        "indexCode": "000852.SH",
        "indexName": "中证1000",
        "last": 5821.36,
        "change": 84.36,
        "changePct": 1.48,
        "direction": "UP",
        "gridRow": 1,
        "gridCol": 5
      },
      {
        "indexCode": "000688.SH",
        "indexName": "科创50",
        "last": 842.51,
        "change": -3.22,
        "changePct": -0.38,
        "direction": "DOWN",
        "gridRow": 2,
        "gridCol": 1
      },
      {
        "indexCode": "000016.SH",
        "indexName": "上证50",
        "last": 2540.12,
        "change": 8.62,
        "changePct": 0.34,
        "direction": "UP",
        "gridRow": 2,
        "gridCol": 2
      },
      {
        "indexCode": "000905.SH",
        "indexName": "中证500",
        "last": 5480.78,
        "change": 48.6,
        "changePct": 0.89,
        "direction": "UP",
        "gridRow": 2,
        "gridCol": 3
      },
      {
        "indexCode": "399303.SZ",
        "indexName": "国证2000",
        "last": 7268.22,
        "change": 102.18,
        "changePct": 1.43,
        "direction": "UP",
        "gridRow": 2,
        "gridCol": 4
      },
      {
        "indexCode": "399005.SZ",
        "indexName": "中小100",
        "last": 6120.35,
        "change": -12.3,
        "changePct": -0.2,
        "direction": "DOWN",
        "gridRow": 2,
        "gridCol": 5
      }
    ],
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
        },
        {
          "rank": 2,
          "stockCode": "601995.SH",
          "stockName": "中金公司",
          "latestPrice": 36.18,
          "changePct": -1.28,
          "direction": "DOWN",
          "turnoverRate": 2.11,
          "volumeRatio": 1.08,
          "volume": 98500,
          "amount": 3580000
        },
        {
          "rank": 3,
          "stockCode": "002235.SZ",
          "stockName": "安妮股份",
          "latestPrice": 8.16,
          "changePct": 10.01,
          "direction": "UP",
          "turnoverRate": 18.42,
          "volumeRatio": 3.55,
          "volume": 421300,
          "amount": 3386000
        },
        {
          "rank": 4,
          "stockCode": "600127.SH",
          "stockName": "金健米业",
          "latestPrice": 7.45,
          "changePct": 2.62,
          "direction": "UP",
          "turnoverRate": 6.08,
          "volumeRatio": 1.92,
          "volume": 210500,
          "amount": 1568000
        },
        {
          "rank": 5,
          "stockCode": "600519.SH",
          "stockName": "贵州茅台",
          "latestPrice": 1688.0,
          "changePct": -0.42,
          "direction": "DOWN",
          "turnoverRate": 0.28,
          "volumeRatio": 0.86,
          "volume": 12600,
          "amount": 21270000
        },
        {
          "rank": 6,
          "stockCode": "300750.SZ",
          "stockName": "宁德时代",
          "latestPrice": 188.42,
          "changePct": 2.63,
          "direction": "UP",
          "turnoverRate": 1.12,
          "volumeRatio": 1.36,
          "volume": 468200,
          "amount": 8812000
        },
        {
          "rank": 7,
          "stockCode": "300059.SZ",
          "stockName": "东方财富",
          "latestPrice": 15.82,
          "changePct": 1.74,
          "direction": "UP",
          "turnoverRate": 3.42,
          "volumeRatio": 1.58,
          "volume": 880000,
          "amount": 13920000
        },
        {
          "rank": 8,
          "stockCode": "002594.SZ",
          "stockName": "比亚迪",
          "latestPrice": 246.3,
          "changePct": -0.66,
          "direction": "DOWN",
          "turnoverRate": 0.92,
          "volumeRatio": 0.97,
          "volume": 124300,
          "amount": 3061000
        },
        {
          "rank": 9,
          "stockCode": "688981.SH",
          "stockName": "中芯国际",
          "latestPrice": 55.6,
          "changePct": 4.12,
          "direction": "UP",
          "turnoverRate": 2.63,
          "volumeRatio": 2.21,
          "volume": 266000,
          "amount": 1479000
        },
        {
          "rank": 10,
          "stockCode": "000001.SZ",
          "stockName": "平安银行",
          "latestPrice": 10.2,
          "changePct": 0.0,
          "direction": "FLAT",
          "turnoverRate": 0.52,
          "volumeRatio": 0.88,
          "volume": 162300,
          "amount": 1655000
        }
      ]
    },
    "limitUp": {
      "tradeDate": "2026-04-28",
      "summaryCards": [
        {
          "key": "limitUpCount",
          "label": "涨停家数",
          "value": 59,
          "unit": "只",
          "direction": "UP"
        },
        {
          "key": "limitDownCount",
          "label": "跌停家数",
          "value": 8,
          "unit": "只",
          "direction": "DOWN"
        },
        {
          "key": "brokenLimitCount",
          "label": "炸板家数",
          "value": 27,
          "unit": "只"
        },
        {
          "key": "sealRate",
          "label": "封板率",
          "value": 0.686,
          "unit": "ratio",
          "displayText": "68.6%"
        },
        {
          "key": "maxStreakLevel",
          "label": "最高连板",
          "value": 6,
          "unit": "板",
          "direction": "UP"
        },
        {
          "key": "streakStockCount",
          "label": "连板股数",
          "value": 16,
          "unit": "只",
          "direction": "UP"
        },
        {
          "key": "skyToFloorCount",
          "label": "天地板",
          "value": 1,
          "unit": "只",
          "direction": "DOWN"
        },
        {
          "key": "floorToSkyCount",
          "label": "地天板",
          "value": 2,
          "unit": "只",
          "direction": "UP"
        }
      ],
      "todayDistribution": {
        "tradeDate": "2026-04-28",
        "limitUpSectorDistribution": [
          {
            "sectorCode": "BK1184.DC",
            "sectorName": "人形机器人",
            "sectorType": "CONCEPT",
            "limitUpCount": 6,
            "ratio": 0.102
          },
          {
            "sectorCode": "BK0490.DC",
            "sectorName": "军工",
            "sectorType": "CONCEPT",
            "limitUpCount": 5,
            "ratio": 0.085
          },
          {
            "sectorCode": "BK0428.DC",
            "sectorName": "半导体",
            "sectorType": "CONCEPT",
            "limitUpCount": 4,
            "ratio": 0.068
          },
          {
            "sectorCode": "BK1027.DC",
            "sectorName": "电机",
            "sectorType": "INDUSTRY",
            "limitUpCount": 4,
            "ratio": 0.068
          },
          {
            "sectorCode": "BK0158.DC",
            "sectorName": "广东板块",
            "sectorType": "REGION",
            "limitUpCount": 3,
            "ratio": 0.051
          }
        ],
        "limitDownStructure": [
          {
            "categoryCode": "LIMIT_DOWN",
            "categoryName": "跌停",
            "count": 8,
            "type": "LIMIT_DOWN"
          },
          {
            "categoryCode": "NEAR_LIMIT_DOWN",
            "categoryName": "接近跌停",
            "count": 13,
            "type": "LIMIT_DOWN"
          }
        ],
        "brokenLimitStructure": [
          {
            "categoryCode": "BROKEN_LIMIT",
            "categoryName": "炸板",
            "count": 27,
            "type": "BROKEN_LIMIT"
          },
          {
            "categoryCode": "OPEN_TIMES_GT_2",
            "categoryName": "开板2次以上",
            "count": 9,
            "type": "BROKEN_LIMIT"
          }
        ]
      },
      "previousTradeDayDistribution": {
        "tradeDate": "2026-04-27",
        "limitUpSectorDistribution": [
          {
            "sectorCode": "BK0493.DC",
            "sectorName": "新能源",
            "sectorType": "CONCEPT",
            "limitUpCount": 5,
            "ratio": 0.096
          },
          {
            "sectorCode": "BK0816.DC",
            "sectorName": "机器人执行器",
            "sectorType": "CONCEPT",
            "limitUpCount": 4,
            "ratio": 0.077
          },
          {
            "sectorCode": "BK1012.DC",
            "sectorName": "证券",
            "sectorType": "INDUSTRY",
            "limitUpCount": 3,
            "ratio": 0.058
          }
        ],
        "limitDownStructure": [
          {
            "categoryCode": "LIMIT_DOWN",
            "categoryName": "跌停",
            "count": 6,
            "type": "LIMIT_DOWN"
          }
        ],
        "brokenLimitStructure": [
          {
            "categoryCode": "BROKEN_LIMIT",
            "categoryName": "炸板",
            "count": 23,
            "type": "BROKEN_LIMIT"
          }
        ]
      },
      "historyPoints": [
        {
          "tradeDate": "2026-04-01",
          "limitUpCount": 42,
          "limitDownCount": 11,
          "rangeType": "1m"
        },
        {
          "tradeDate": "2026-04-15",
          "limitUpCount": 51,
          "limitDownCount": 6,
          "rangeType": "1m"
        },
        {
          "tradeDate": "2026-04-28",
          "limitUpCount": 59,
          "limitDownCount": 8,
          "rangeType": "1m"
        }
      ]
    },
    "sectorOverview": {
      "industryRiseTop5": [
        {
          "rank": 1,
          "sectorCode": "BK1027.DC",
          "sectorName": "电机",
          "sectorType": "INDUSTRY",
          "changePct": 4.21,
          "turnoverAmount": 9860000000,
          "netInflowAmount": 1200000000,
          "leadingStockCode": "300660.SZ",
          "leadingStockName": "江苏雷利",
          "leadingStockChangePct": 12.44
        },
        {
          "rank": 2,
          "sectorCode": "BK100.DC",
          "sectorName": "示例行业2",
          "sectorType": "INDUSTRY",
          "changePct": 3.8,
          "turnoverAmount": 7000000000,
          "netInflowAmount": 800000000,
          "leadingStockCode": "000001.SZ",
          "leadingStockName": "示例股",
          "leadingStockChangePct": 5.5
        },
        {
          "rank": 3,
          "sectorCode": "BK101.DC",
          "sectorName": "示例行业3",
          "sectorType": "INDUSTRY",
          "changePct": 3.5999999999999996,
          "turnoverAmount": 6900000000,
          "netInflowAmount": 750000000,
          "leadingStockCode": "000001.SZ",
          "leadingStockName": "示例股",
          "leadingStockChangePct": 4.5
        },
        {
          "rank": 4,
          "sectorCode": "BK102.DC",
          "sectorName": "示例行业4",
          "sectorType": "INDUSTRY",
          "changePct": 3.4,
          "turnoverAmount": 6800000000,
          "netInflowAmount": 700000000,
          "leadingStockCode": "000001.SZ",
          "leadingStockName": "示例股",
          "leadingStockChangePct": 3.5
        },
        {
          "rank": 5,
          "sectorCode": "BK103.DC",
          "sectorName": "示例行业5",
          "sectorType": "INDUSTRY",
          "changePct": 3.1999999999999997,
          "turnoverAmount": 6700000000,
          "netInflowAmount": 650000000,
          "leadingStockCode": "000001.SZ",
          "leadingStockName": "示例股",
          "leadingStockChangePct": 2.5
        }
      ],
      "conceptRiseTop5": [
        {
          "rank": 1,
          "sectorCode": "BK1184.DC",
          "sectorName": "人形机器人",
          "sectorType": "CONCEPT",
          "changePct": 4.37,
          "turnoverAmount": 12860000000,
          "netInflowAmount": 2630000000,
          "leadingStockCode": "002117.SZ",
          "leadingStockName": "东港股份",
          "leadingStockChangePct": 10.02
        },
        {
          "rank": 2,
          "sectorCode": "BK110.DC",
          "sectorName": "示例概念2",
          "sectorType": "CONCEPT",
          "changePct": 4.0,
          "turnoverAmount": 9000000000,
          "netInflowAmount": 700000000,
          "leadingStockCode": "300001.SZ",
          "leadingStockName": "示例股",
          "leadingStockChangePct": 6.2
        },
        {
          "rank": 3,
          "sectorCode": "BK111.DC",
          "sectorName": "示例概念3",
          "sectorType": "CONCEPT",
          "changePct": 3.75,
          "turnoverAmount": 8900000000,
          "netInflowAmount": 660000000,
          "leadingStockCode": "300001.SZ",
          "leadingStockName": "示例股",
          "leadingStockChangePct": 5.2
        },
        {
          "rank": 4,
          "sectorCode": "BK112.DC",
          "sectorName": "示例概念4",
          "sectorType": "CONCEPT",
          "changePct": 3.5,
          "turnoverAmount": 8800000000,
          "netInflowAmount": 620000000,
          "leadingStockCode": "300001.SZ",
          "leadingStockName": "示例股",
          "leadingStockChangePct": 4.2
        },
        {
          "rank": 5,
          "sectorCode": "BK113.DC",
          "sectorName": "示例概念5",
          "sectorType": "CONCEPT",
          "changePct": 3.25,
          "turnoverAmount": 8700000000,
          "netInflowAmount": 580000000,
          "leadingStockCode": "300001.SZ",
          "leadingStockName": "示例股",
          "leadingStockChangePct": 3.2
        }
      ],
      "regionRiseTop5": [
        {
          "rank": 1,
          "sectorCode": "BK0158.DC",
          "sectorName": "广东板块",
          "sectorType": "REGION",
          "changePct": 2.16,
          "turnoverAmount": 9860000000,
          "netInflowAmount": 510000000,
          "leadingStockCode": "000001.SZ",
          "leadingStockName": "平安银行",
          "leadingStockChangePct": 3.12
        },
        {
          "rank": 2,
          "sectorCode": "BK010.DC",
          "sectorName": "示例地域2",
          "sectorType": "REGION",
          "changePct": 2.0,
          "turnoverAmount": 6000000000,
          "netInflowAmount": 300000000,
          "leadingStockCode": "600000.SH",
          "leadingStockName": "示例股",
          "leadingStockChangePct": 3.0
        },
        {
          "rank": 3,
          "sectorCode": "BK011.DC",
          "sectorName": "示例地域3",
          "sectorType": "REGION",
          "changePct": 1.85,
          "turnoverAmount": 5920000000,
          "netInflowAmount": 270000000,
          "leadingStockCode": "600000.SH",
          "leadingStockName": "示例股",
          "leadingStockChangePct": 2.8
        },
        {
          "rank": 4,
          "sectorCode": "BK012.DC",
          "sectorName": "示例地域4",
          "sectorType": "REGION",
          "changePct": 1.7,
          "turnoverAmount": 5840000000,
          "netInflowAmount": 240000000,
          "leadingStockCode": "600000.SH",
          "leadingStockName": "示例股",
          "leadingStockChangePct": 2.6
        },
        {
          "rank": 5,
          "sectorCode": "BK013.DC",
          "sectorName": "示例地域5",
          "sectorType": "REGION",
          "changePct": 1.55,
          "turnoverAmount": 5760000000,
          "netInflowAmount": 210000000,
          "leadingStockCode": "600000.SH",
          "leadingStockName": "示例股",
          "leadingStockChangePct": 2.4
        }
      ],
      "moneyInflowTop5": [
        {
          "rank": 1,
          "sectorCode": "BK20.DC",
          "sectorName": "资金流入板块1",
          "sectorType": "CONCEPT",
          "changePct": 1.8,
          "turnoverAmount": 7000000000,
          "netInflowAmount": 1500000000,
          "leadingStockCode": "002000.SZ",
          "leadingStockName": "示例股",
          "leadingStockChangePct": 4.0
        },
        {
          "rank": 2,
          "sectorCode": "BK21.DC",
          "sectorName": "资金流入板块2",
          "sectorType": "CONCEPT",
          "changePct": 1.7,
          "turnoverAmount": 7000000000,
          "netInflowAmount": 1400000000,
          "leadingStockCode": "002000.SZ",
          "leadingStockName": "示例股",
          "leadingStockChangePct": 3.8
        },
        {
          "rank": 3,
          "sectorCode": "BK22.DC",
          "sectorName": "资金流入板块3",
          "sectorType": "CONCEPT",
          "changePct": 1.6,
          "turnoverAmount": 7000000000,
          "netInflowAmount": 1300000000,
          "leadingStockCode": "002000.SZ",
          "leadingStockName": "示例股",
          "leadingStockChangePct": 3.6
        },
        {
          "rank": 4,
          "sectorCode": "BK23.DC",
          "sectorName": "资金流入板块4",
          "sectorType": "CONCEPT",
          "changePct": 1.5,
          "turnoverAmount": 7000000000,
          "netInflowAmount": 1200000000,
          "leadingStockCode": "002000.SZ",
          "leadingStockName": "示例股",
          "leadingStockChangePct": 3.4
        },
        {
          "rank": 5,
          "sectorCode": "BK24.DC",
          "sectorName": "资金流入板块5",
          "sectorType": "CONCEPT",
          "changePct": 1.4,
          "turnoverAmount": 7000000000,
          "netInflowAmount": 1100000000,
          "leadingStockCode": "002000.SZ",
          "leadingStockName": "示例股",
          "leadingStockChangePct": 3.2
        }
      ],
      "industryFallTop5": [
        {
          "rank": 1,
          "sectorCode": "BK30.DC",
          "sectorName": "行业跌幅1",
          "sectorType": "INDUSTRY",
          "changePct": -1.2,
          "turnoverAmount": 6000000000,
          "netInflowAmount": -200000000,
          "leadingStockCode": "600100.SH",
          "leadingStockName": "示例股",
          "leadingStockChangePct": -2.0
        },
        {
          "rank": 2,
          "sectorCode": "BK31.DC",
          "sectorName": "行业跌幅2",
          "sectorType": "INDUSTRY",
          "changePct": -1.5,
          "turnoverAmount": 6000000000,
          "netInflowAmount": -250000000,
          "leadingStockCode": "600100.SH",
          "leadingStockName": "示例股",
          "leadingStockChangePct": -2.2
        },
        {
          "rank": 3,
          "sectorCode": "BK32.DC",
          "sectorName": "行业跌幅3",
          "sectorType": "INDUSTRY",
          "changePct": -1.7999999999999998,
          "turnoverAmount": 6000000000,
          "netInflowAmount": -300000000,
          "leadingStockCode": "600100.SH",
          "leadingStockName": "示例股",
          "leadingStockChangePct": -2.4
        },
        {
          "rank": 4,
          "sectorCode": "BK33.DC",
          "sectorName": "行业跌幅4",
          "sectorType": "INDUSTRY",
          "changePct": -2.0999999999999996,
          "turnoverAmount": 6000000000,
          "netInflowAmount": -350000000,
          "leadingStockCode": "600100.SH",
          "leadingStockName": "示例股",
          "leadingStockChangePct": -2.6
        },
        {
          "rank": 5,
          "sectorCode": "BK34.DC",
          "sectorName": "行业跌幅5",
          "sectorType": "INDUSTRY",
          "changePct": -2.4,
          "turnoverAmount": 6000000000,
          "netInflowAmount": -400000000,
          "leadingStockCode": "600100.SH",
          "leadingStockName": "示例股",
          "leadingStockChangePct": -2.8
        }
      ],
      "conceptFallTop5": [
        {
          "rank": 1,
          "sectorCode": "BK40.DC",
          "sectorName": "概念跌幅1",
          "sectorType": "CONCEPT",
          "changePct": -1.4,
          "turnoverAmount": 6500000000,
          "netInflowAmount": -230000000,
          "leadingStockCode": "300100.SZ",
          "leadingStockName": "示例股",
          "leadingStockChangePct": -2.5
        },
        {
          "rank": 2,
          "sectorCode": "BK41.DC",
          "sectorName": "概念跌幅2",
          "sectorType": "CONCEPT",
          "changePct": -1.65,
          "turnoverAmount": 6500000000,
          "netInflowAmount": -290000000,
          "leadingStockCode": "300100.SZ",
          "leadingStockName": "示例股",
          "leadingStockChangePct": -2.7
        },
        {
          "rank": 3,
          "sectorCode": "BK42.DC",
          "sectorName": "概念跌幅3",
          "sectorType": "CONCEPT",
          "changePct": -1.9,
          "turnoverAmount": 6500000000,
          "netInflowAmount": -350000000,
          "leadingStockCode": "300100.SZ",
          "leadingStockName": "示例股",
          "leadingStockChangePct": -2.9
        },
        {
          "rank": 4,
          "sectorCode": "BK43.DC",
          "sectorName": "概念跌幅4",
          "sectorType": "CONCEPT",
          "changePct": -2.15,
          "turnoverAmount": 6500000000,
          "netInflowAmount": -410000000,
          "leadingStockCode": "300100.SZ",
          "leadingStockName": "示例股",
          "leadingStockChangePct": -3.1
        },
        {
          "rank": 5,
          "sectorCode": "BK44.DC",
          "sectorName": "概念跌幅5",
          "sectorType": "CONCEPT",
          "changePct": -2.4,
          "turnoverAmount": 6500000000,
          "netInflowAmount": -470000000,
          "leadingStockCode": "300100.SZ",
          "leadingStockName": "示例股",
          "leadingStockChangePct": -3.3
        }
      ],
      "regionFallTop5": [
        {
          "rank": 1,
          "sectorCode": "BK50.DC",
          "sectorName": "地域跌幅1",
          "sectorType": "REGION",
          "changePct": -0.6,
          "turnoverAmount": 5600000000,
          "netInflowAmount": -110000000,
          "leadingStockCode": "000100.SZ",
          "leadingStockName": "示例股",
          "leadingStockChangePct": -1.5
        },
        {
          "rank": 2,
          "sectorCode": "BK51.DC",
          "sectorName": "地域跌幅2",
          "sectorType": "REGION",
          "changePct": -0.8,
          "turnoverAmount": 5600000000,
          "netInflowAmount": -160000000,
          "leadingStockCode": "000100.SZ",
          "leadingStockName": "示例股",
          "leadingStockChangePct": -1.7
        },
        {
          "rank": 3,
          "sectorCode": "BK52.DC",
          "sectorName": "地域跌幅3",
          "sectorType": "REGION",
          "changePct": -1.0,
          "turnoverAmount": 5600000000,
          "netInflowAmount": -210000000,
          "leadingStockCode": "000100.SZ",
          "leadingStockName": "示例股",
          "leadingStockChangePct": -1.9
        },
        {
          "rank": 4,
          "sectorCode": "BK53.DC",
          "sectorName": "地域跌幅4",
          "sectorType": "REGION",
          "changePct": -1.2000000000000002,
          "turnoverAmount": 5600000000,
          "netInflowAmount": -260000000,
          "leadingStockCode": "000100.SZ",
          "leadingStockName": "示例股",
          "leadingStockChangePct": -2.1
        },
        {
          "rank": 5,
          "sectorCode": "BK54.DC",
          "sectorName": "地域跌幅5",
          "sectorType": "REGION",
          "changePct": -1.4,
          "turnoverAmount": 5600000000,
          "netInflowAmount": -310000000,
          "leadingStockCode": "000100.SZ",
          "leadingStockName": "示例股",
          "leadingStockChangePct": -2.3
        }
      ],
      "moneyOutflowTop5": [
        {
          "rank": 1,
          "sectorCode": "BK60.DC",
          "sectorName": "资金流出板块1",
          "sectorType": "CONCEPT",
          "changePct": -0.8,
          "turnoverAmount": 7600000000,
          "netInflowAmount": -1300000000,
          "leadingStockCode": "002100.SZ",
          "leadingStockName": "示例股",
          "leadingStockChangePct": -1.8
        },
        {
          "rank": 2,
          "sectorCode": "BK61.DC",
          "sectorName": "资金流出板块2",
          "sectorType": "CONCEPT",
          "changePct": -1.0,
          "turnoverAmount": 7600000000,
          "netInflowAmount": -1200000000,
          "leadingStockCode": "002100.SZ",
          "leadingStockName": "示例股",
          "leadingStockChangePct": -2.0
        },
        {
          "rank": 3,
          "sectorCode": "BK62.DC",
          "sectorName": "资金流出板块3",
          "sectorType": "CONCEPT",
          "changePct": -1.2000000000000002,
          "turnoverAmount": 7600000000,
          "netInflowAmount": -1100000000,
          "leadingStockCode": "002100.SZ",
          "leadingStockName": "示例股",
          "leadingStockChangePct": -2.2
        },
        {
          "rank": 4,
          "sectorCode": "BK63.DC",
          "sectorName": "资金流出板块4",
          "sectorType": "CONCEPT",
          "changePct": -1.4000000000000001,
          "turnoverAmount": 7600000000,
          "netInflowAmount": -1000000000,
          "leadingStockCode": "002100.SZ",
          "leadingStockName": "示例股",
          "leadingStockChangePct": -2.4000000000000004
        },
        {
          "rank": 5,
          "sectorCode": "BK64.DC",
          "sectorName": "资金流出板块5",
          "sectorType": "CONCEPT",
          "changePct": -1.6,
          "turnoverAmount": 7600000000,
          "netInflowAmount": -900000000,
          "leadingStockCode": "002100.SZ",
          "leadingStockName": "示例股",
          "leadingStockChangePct": -2.6
        }
      ],
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
        },
        {
          "sectorCode": "BK0490.DC",
          "sectorName": "军工",
          "sectorType": "CONCEPT",
          "changePct": 2.35,
          "direction": "UP",
          "turnoverAmount": 7860000000,
          "netInflowAmount": 620000000,
          "riseStockCount": 32,
          "fallStockCount": 465,
          "rowIndex": 0,
          "colIndex": 1
        },
        {
          "sectorCode": "BK0428.DC",
          "sectorName": "半导体",
          "sectorType": "CONCEPT",
          "changePct": 1.88,
          "direction": "UP",
          "turnoverAmount": 16860000000,
          "netInflowAmount": 1080000000,
          "riseStockCount": 58,
          "fallStockCount": 120,
          "rowIndex": 0,
          "colIndex": 2
        },
        {
          "sectorCode": "BK0493.DC",
          "sectorName": "新能源",
          "sectorType": "CONCEPT",
          "changePct": -1.12,
          "direction": "DOWN",
          "turnoverAmount": 8860000000,
          "netInflowAmount": -820000000,
          "riseStockCount": 19,
          "fallStockCount": 184,
          "rowIndex": 0,
          "colIndex": 3
        },
        {
          "sectorCode": "BK1027.DC",
          "sectorName": "电机",
          "sectorType": "INDUSTRY",
          "changePct": 4.21,
          "direction": "UP",
          "turnoverAmount": 9860000000,
          "netInflowAmount": 1200000000,
          "riseStockCount": 26,
          "fallStockCount": 11,
          "rowIndex": 1,
          "colIndex": 0
        },
        {
          "sectorCode": "BK1031.DC",
          "sectorName": "自动化设备",
          "sectorType": "INDUSTRY",
          "changePct": 3.66,
          "direction": "UP",
          "turnoverAmount": 7560000000,
          "netInflowAmount": 850000000,
          "riseStockCount": 40,
          "fallStockCount": 21,
          "rowIndex": 1,
          "colIndex": 1
        },
        {
          "sectorCode": "BK0475.DC",
          "sectorName": "软件开发",
          "sectorType": "INDUSTRY",
          "changePct": 2.74,
          "direction": "UP",
          "turnoverAmount": 13200000000,
          "netInflowAmount": 610000000,
          "riseStockCount": 88,
          "fallStockCount": 76,
          "rowIndex": 1,
          "colIndex": 2
        },
        {
          "sectorCode": "BK0736.DC",
          "sectorName": "消费电子",
          "sectorType": "INDUSTRY",
          "changePct": -0.82,
          "direction": "DOWN",
          "turnoverAmount": 9100000000,
          "netInflowAmount": -360000000,
          "riseStockCount": 35,
          "fallStockCount": 84,
          "rowIndex": 1,
          "colIndex": 3
        },
        {
          "sectorCode": "BK0158.DC",
          "sectorName": "广东板块",
          "sectorType": "REGION",
          "changePct": 2.16,
          "direction": "UP",
          "turnoverAmount": 9860000000,
          "netInflowAmount": 510000000,
          "riseStockCount": 152,
          "fallStockCount": 110,
          "rowIndex": 2,
          "colIndex": 0
        },
        {
          "sectorCode": "BK0160.DC",
          "sectorName": "浙江板块",
          "sectorType": "REGION",
          "changePct": 1.72,
          "direction": "UP",
          "turnoverAmount": 8650000000,
          "netInflowAmount": 330000000,
          "riseStockCount": 142,
          "fallStockCount": 96,
          "rowIndex": 2,
          "colIndex": 1
        },
        {
          "sectorCode": "BK0148.DC",
          "sectorName": "北京板块",
          "sectorType": "REGION",
          "changePct": -0.43,
          "direction": "DOWN",
          "turnoverAmount": 7200000000,
          "netInflowAmount": -120000000,
          "riseStockCount": 81,
          "fallStockCount": 97,
          "rowIndex": 2,
          "colIndex": 2
        },
        {
          "sectorCode": "BK0151.DC",
          "sectorName": "上海板块",
          "sectorType": "REGION",
          "changePct": 0.25,
          "direction": "UP",
          "turnoverAmount": 6800000000,
          "netInflowAmount": 80000000,
          "riseStockCount": 75,
          "fallStockCount": 72,
          "rowIndex": 2,
          "colIndex": 3
        },
        {
          "sectorCode": "BK1186.DC",
          "sectorName": "首发经济",
          "sectorType": "CONCEPT",
          "changePct": -2.18,
          "direction": "DOWN",
          "turnoverAmount": 3660000000,
          "netInflowAmount": -550000000,
          "riseStockCount": 4,
          "fallStockCount": 31,
          "rowIndex": 3,
          "colIndex": 0
        },
        {
          "sectorCode": "BK1185.DC",
          "sectorName": "冰雪经济",
          "sectorType": "CONCEPT",
          "changePct": -1.76,
          "direction": "DOWN",
          "turnoverAmount": 4200000000,
          "netInflowAmount": -280000000,
          "riseStockCount": 2,
          "fallStockCount": 32,
          "rowIndex": 3,
          "colIndex": 1
        },
        {
          "sectorCode": "BK1183.DC",
          "sectorName": "谷子经济",
          "sectorType": "CONCEPT",
          "changePct": 1.36,
          "direction": "UP",
          "turnoverAmount": 5120000000,
          "netInflowAmount": 230000000,
          "riseStockCount": 22,
          "fallStockCount": 55,
          "rowIndex": 3,
          "colIndex": 2
        },
        {
          "sectorCode": "BK0494.DC",
          "sectorName": "节能环保",
          "sectorType": "CONCEPT",
          "changePct": 0.92,
          "direction": "UP",
          "turnoverAmount": 8200000000,
          "netInflowAmount": 150000000,
          "riseStockCount": 32,
          "fallStockCount": 378,
          "rowIndex": 3,
          "colIndex": 3
        },
        {
          "sectorCode": "BK1012.DC",
          "sectorName": "证券",
          "sectorType": "INDUSTRY",
          "changePct": 3.12,
          "direction": "UP",
          "turnoverAmount": 12060000000,
          "netInflowAmount": 1560000000,
          "riseStockCount": 42,
          "fallStockCount": 8,
          "rowIndex": 4,
          "colIndex": 0
        },
        {
          "sectorCode": "BK1018.DC",
          "sectorName": "银行",
          "sectorType": "INDUSTRY",
          "changePct": -0.22,
          "direction": "DOWN",
          "turnoverAmount": 7020000000,
          "netInflowAmount": -260000000,
          "riseStockCount": 14,
          "fallStockCount": 28,
          "rowIndex": 4,
          "colIndex": 1
        },
        {
          "sectorCode": "BK1045.DC",
          "sectorName": "光伏设备",
          "sectorType": "INDUSTRY",
          "changePct": 1.06,
          "direction": "UP",
          "turnoverAmount": 9200000000,
          "netInflowAmount": 420000000,
          "riseStockCount": 38,
          "fallStockCount": 60,
          "rowIndex": 4,
          "colIndex": 2
        },
        {
          "sectorCode": "BK1055.DC",
          "sectorName": "小金属",
          "sectorType": "INDUSTRY",
          "changePct": -1.45,
          "direction": "DOWN",
          "turnoverAmount": 3900000000,
          "netInflowAmount": -310000000,
          "riseStockCount": 15,
          "fallStockCount": 44,
          "rowIndex": 4,
          "colIndex": 3
        }
      ]
    }
  },
  "traceId": "req_20260428_000001",
  "serverTime": "2026-04-28T17:12:00+08:00"
}
```

### 字段说明

| 聚合字段 | 说明 |
|---|---|
| `marketSummary.cards` | 5 个今日市场事实卡片 |
| `marketSummary.textCard` | 说明性文字卡片，不给主观结论 |
| `indices[]` | 10 个指数，支持 2×5 展示 |
| `leaderboards.top10[]` | 榜单 Top10 表格 |
| `limitUp.summaryCards[]` | 涨跌停 8 个统计卡 |
| `limitUp.todayDistribution` | 今日涨停板块分布 + 跌停/炸板结构 |
| `limitUp.previousTradeDayDistribution` | 昨日涨停板块分布 + 跌停/炸板结构 |
| `limitUp.historyPoints[]` | 历史涨跌停组合柱图 |
| `sectorOverview.*Top5` | 8 个 Top5 榜单 |
| `sectorOverview.heatMapItems[]` | 5×4 热力图 20 个格子 |

### 异常状态

| code | 场景 | 前端处理 |
|---:|---|---|
| `400001` | `leaderboardLimit`、`sectorTopLimit`、`heatMapRows/Cols` 非法 | 保留旧数据并提示参数错误 |
| `404001` | 指定交易日无榜单、涨跌停或板块数据 | 对应模块空态 |
| `503001` | 核心行情源不可用 | 模块降级，核心首屏保留旧缓存 |
| `500001` | 聚合服务异常 | 整页异常态 |

### 空数据处理

1. `leaderboards.top10=[]`：显示“暂无榜单数据”。
2. `limitUp.todayDistribution.limitUpSectorDistribution=[]`：显示“暂无涨停板块分布”。
3. `limitUp.previousTradeDayDistribution` 缺失：展示“上一交易日结构暂不可用”。
4. `sectorOverview.heatMapItems.length < 20`：前端可补空格，但需显示数据不足提示。

### 数据更新时间

| 模块 | 更新频率 |
|---|---|
| 榜单 Top10 | `dc_hot` 日内多次；关联 `daily/daily_basic` 日频/按源 |
| 涨跌停 2×2 | `limit_list_d` 按源，盘后固定；实时源接入后 15-60 秒 |
| 板块 Top5 | `dc_index/dc_daily` 日频/按源 |
| 板块资金 Top5 | `moneyflow_ind_dc` 盘后/按源 |
| 热力图 | `dc_index/dc_daily/moneyflow_ind_dc` 按源 |

### 缓存建议

| 模块 | 缓存 |
|---|---|
| 聚合接口 | 盘中 15-60 秒，盘后 1 天 |
| 榜单 Top10 | 5-30 分钟，盘后 1 天 |
| 涨跌停 2×2 | 15-60 秒或按源，盘后 1 天 |
| 板块速览 | 1-5 分钟或按源，盘后 1 天 |
| 热力图 | 1-5 分钟或按源，盘后 1 天 |

### 性能评估

| 项目 | 目标 |
|---|---|
| 聚合接口 P95 | `<500ms` |
| 榜单模块 P95 | `<150ms` |
| 涨跌停模块 P95 | `<220ms` |
| 板块矩阵 + 热力图 P95 | `<220ms` |
| 查询策略 | 必须读取预聚合视图，不允许实时 join 全量原始表 |
| Payload | `heatMapItems` 20 条、Top5 × 8 组、Top10 榜单时，整体建议 `<180KB` |

### 暂缺字段清单

1. `skyToFloorCount`、`floorToSkyCount` 需要天地板/地天板规则确认。
2. 榜单 Top10 若以 `dc_hot` 为主，需要与 `daily/daily_basic` 稳定关联。
3. 热力图排序和行列分配算法需要产品确认。
4. 板块平盘家数需要 `dc_member + daily` 精算。

---

## 4. 模块接口同步说明

### 4.1 GET /api/leaderboard/stock

| 项目 | 内容 |
|---|---|
| 是否需要新增字段 | 是 |
| 新增/确认字段 | `latestPrice`、`turnoverRate`、`volumeRatio`、`volume`、`amount` |
| Top 数量 | 默认 `limit=10` |
| 列顺序 | 排名｜股票｜最新价｜涨跌幅｜换手率｜量比｜成交量｜成交额 |
| 数据来源 | `dc_hot + daily + daily_basic`，或传统榜单由 `daily/daily_basic` 派生 |
| 是否影响其它模块 | 否 |

#### endpoint

```http
GET /api/leaderboard/stock
```

#### request params

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---:|---|---|
| `market` | string | 否 | `CN_A` | P0 A 股 |
| `tradeDate` | string(date) | 否 | 最近交易日 | 交易日 |
| `rankType` | enum | 否 | `POPULAR` | `POPULAR` / `SURGE` / `GAINER` / `LOSER` / `AMOUNT` / `TURNOVER` / `VOLUME_RATIO` |
| `limit` | integer | 否 | `10` | Review v2 固定 Top10 |

#### response JSON

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
  "traceId": "req_xxx",
  "serverTime": "2026-04-28T17:12:00+08:00"
}
```

### 4.2 GET /api/limitup/summary

| 项目 | 内容 |
|---|---|
| 是否需要新增字段 | 是 |
| 新增/确认字段 | `summaryCards`、`todayDistribution`、`previousTradeDayDistribution` |
| 保留字段 | `historyPoints` |
| 展示结构 | 左上 8 卡；右上今日结构；左下历史柱图；右下昨日结构 |
| 数据来源 | `limit_list_d + dc_member/dc_index` |
| 是否影响连板天梯 | 否，本轮不改 `streakLadder` |

#### endpoint

```http
GET /api/limitup/summary
```

#### request params

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---:|---|---|
| `market` | string | 否 | `CN_A` | P0 A 股 |
| `tradeDate` | string(date) | 否 | 最近交易日 | 当前交易日 |
| `includePreviousDistribution` | boolean | 否 | `true` | 是否返回上一交易日结构 |
| `includeHistory` | boolean | 否 | `true` | 是否返回历史柱图 |

#### response JSON

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "tradeDate": "2026-04-28",
    "summaryCards": [
      { "key": "limitUpCount", "label": "涨停家数", "value": 59, "unit": "只", "direction": "UP" },
      { "key": "limitDownCount", "label": "跌停家数", "value": 8, "unit": "只", "direction": "DOWN" }
    ],
    "todayDistribution": {
      "tradeDate": "2026-04-28",
      "limitUpSectorDistribution": [],
      "limitDownStructure": [],
      "brokenLimitStructure": []
    },
    "previousTradeDayDistribution": {
      "tradeDate": "2026-04-27",
      "limitUpSectorDistribution": [],
      "limitDownStructure": [],
      "brokenLimitStructure": []
    },
    "historyPoints": [
      { "tradeDate": "2026-04-28", "limitUpCount": 59, "limitDownCount": 8, "rangeType": "1m" }
    ]
  },
  "traceId": "req_xxx",
  "serverTime": "2026-04-28T17:12:00+08:00"
}
```

### 4.3 GET /api/sector/top

| 项目 | 内容 |
|---|---|
| 是否需要新增字段 | 是 |
| 新增/确认字段 | `sectorOverview` 组合结构、`heatMapItems`、`rowIndex`、`colIndex` |
| Top 数量 | 每组 Top5 |
| 热力图 | 20 条，对应 5×4 |
| 数据来源 | `dc_index`、`dc_daily`、`moneyflow_ind_dc` |
| 是否影响其它模块 | 否 |

#### endpoint

```http
GET /api/sector/top
```

#### request params

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---:|---|---|
| `market` | string | 否 | `CN_A` | P0 A 股 |
| `tradeDate` | string(date) | 否 | 最近交易日 | 交易日 |
| `limit` | integer | 否 | `5` | 每组 Top5 |
| `includeHeatMap` | boolean | 否 | `true` | 是否返回热力图 |
| `heatMapRows` | integer | 否 | `5` | 热力图行 |
| `heatMapCols` | integer | 否 | `4` | 热力图列 |

#### response JSON

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "industryRiseTop5": [],
    "conceptRiseTop5": [],
    "regionRiseTop5": [],
    "moneyInflowTop5": [],
    "industryFallTop5": [],
    "conceptFallTop5": [],
    "regionFallTop5": [],
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
  "traceId": "req_xxx",
  "serverTime": "2026-04-28T17:12:00+08:00"
}
```

---

## 5. 未修改模块说明

以下接口沿用 v0.4，不因 Review v2 主动修改：

1. `GET /api/market/breadth`
2. `GET /api/market/style`
3. `GET /api/market/turnover`
4. `GET /api/moneyflow/market`
5. `GET /api/limitup/streak-ladder`
6. `GET /api/index/summary`
7. `GET /api/settings/quick-entry`

---

## 6. 文档末尾清单

### 6.1 本轮 Review v2 修改摘要

1. `marketSummary` 支持左侧 5 卡 + 说明卡。
2. `indices` 支持主要指数 2×5。
3. `leaderboards.top10` 补齐换手率、量比、成交量、成交额。
4. `limitUp` 支持 2×2 展示结构。
5. `sectorOverview` 支持 8 个 Top5 + 5×4 热力图。

### 6.2 本轮新增字段清单

| 模块 | 新增字段 |
|---|---|
| 今日市场客观总结 | `marketSummary.layout`、`marketSummary.cards`、`marketSummary.textCard` |
| 主要指数 | `indices[].gridRow`、`indices[].gridCol` |
| 榜单 | `latestPrice`、`turnoverRate`、`volumeRatio`、`volume`、`amount` |
| 涨跌停 | `summaryCards`、`todayDistribution`、`previousTradeDayDistribution` |
| 板块 | `sectorOverview.industryRiseTop5`、`conceptRiseTop5`、`regionRiseTop5`、`moneyInflowTop5`、`industryFallTop5`、`conceptFallTop5`、`regionFallTop5`、`moneyOutflowTop5`、`heatMapItems` |
| 热力图 | `rowIndex`、`colIndex`、`riseStockCount`、`fallStockCount` |

### 6.3 本轮修改字段清单

| 字段/对象 | 修改 |
|---|---|
| `StockRankItem.price` | 建议统一为 `latestPrice`，旧字段可短期兼容 |
| `SectorRankItem.sectorId` | 建议统一为 `sectorCode`，旧字段可短期兼容 |
| `LimitUpSummary.distribution` | 本轮拆分为 `todayDistribution` 和 `previousTradeDayDistribution` |

### 6.4 本轮未修改 API 模块清单

1. `breadth`
2. `style`
3. `turnover`
4. `moneyFlow`
5. `streakLadder`
6. `topMarketBar`
7. `breadcrumb`
8. `quickEntries`
9. 路由结构

### 6.5 市场总览页面模块与 API 字段映射表

| 页面模块 | API 字段 |
|---|---|
| 今日市场客观总结 | `marketSummary.cards`、`marketSummary.textCard` |
| 主要指数 | `indices[]` |
| 榜单速览 | `leaderboards.top10[]` |
| 涨跌停统计卡 | `limitUp.summaryCards[]` |
| 今日涨停板块分布 | `limitUp.todayDistribution.limitUpSectorDistribution[]` |
| 今日跌停/炸板结构 | `limitUp.todayDistribution.limitDownStructure[]`、`brokenLimitStructure[]` |
| 昨日涨停板块分布 | `limitUp.previousTradeDayDistribution.limitUpSectorDistribution[]` |
| 昨日跌停/炸板结构 | `limitUp.previousTradeDayDistribution.limitDownStructure[]`、`brokenLimitStructure[]` |
| 历史涨跌停柱状图 | `limitUp.historyPoints[]` |
| 板块矩阵 | `sectorOverview.*Top5[]` |
| 5×4 热力图 | `sectorOverview.heatMapItems[]` |

### 6.6 给 02 HTML Showcase 的 Mock 数据建议

1. 榜单 Top10 必须真实填满 10 行。
2. 每条榜单必须有换手率、量比、成交量、成交额。
3. 涨跌停 8 个统计卡必须齐全。
4. 今日/昨日分布结构必须均有数据。
5. 行业/概念/地域/资金流入/资金流出 Top5 均需 5 条。
6. 热力图必须 20 条，5 行 × 4 列，`rowIndex/colIndex` 完整。

### 6.7 给 03 组件 Props 的字段映射建议

| 组件 | Props |
|---|---|
| `MarketSummaryIndexSplitPanel` | `summary`、`indices` |
| `LeaderboardTop10Table` | `items: StockRankItem[]` |
| `LimitUpTwoByTwoPanel` | `summaryCards`、`todayDistribution`、`previousTradeDayDistribution`、`historyPoints` |
| `SectorOverviewMatrix` | 8 个 Top5 数组 |
| `SectorHeatMapGrid` | `items`、`rows=5`、`cols=4` |

### 6.8 P0 已具备字段

| 能力 | 来源 |
|---|---|
| Top10 基础排名 | `dc_hot` |
| 榜单行情列 | `daily`、`daily_basic` |
| 涨跌停统计 | `limit_list_d` |
| 涨停板块分布 | `limit_list_d + dc_member/dc_index` |
| 板块 Top5 | `dc_index/dc_daily` |
| 板块资金流 Top5 | `moneyflow_ind_dc` |
| 热力图基础 | `dc_index/dc_daily/moneyflow_ind_dc` |

### 6.9 P0 暂缺字段

| 字段 | 说明 |
|---|---|
| `skyToFloorCount` | 天地板规则待确认 |
| `floorToSkyCount` | 地天板规则待确认 |
| 热力图排序算法 | 待确认按涨跌幅、成交额还是资金净流入 |
| 板块平盘数 | 需 `dc_member + daily` 精算 |
| 热榜与传统行情榜并存策略 | 待确认 |

### 6.10 需要数据基座补充的字段/视图

1. `wealth_stock_leaderboard_snapshot`
2. `wealth_limitup_day_distribution_snapshot`
3. `wealth_sector_overview_matrix_snapshot`
4. `wealth_sector_heatmap_5x4_snapshot`
5. 天地板/地天板规则视图

### 6.11 待产品总控确认问题

1. 榜单速览是以 `dc_hot` 为主，还是传统涨跌幅/成交额/换手/量比榜为主？
2. 热力图排序依据是什么？
3. 天地板/地天板是否必须在 v1.2 真实展示？
4. 涨停板块分布是否优先概念板块？
