# 财势乾坤｜个股详情页 API 草案 v0.1

建议保存路径：`财势乾坤/数据字典与API文档/stock-detail-api-v0.1.md`  
负责人：`04_API 契约与数据字典`  
版本：`v0.1`  
状态：`个股详情页 P0 API 草案`  
更新时间：`2026-05-14`

---

## 本轮实际读取的公共区文件

| 序号 | 文件名 | 实际读取到的版本 / 状态 |
|---:|---|---|
| 1 | `财势乾坤行情软件项目总说明_v_0_2.md` | `财势乾坤项目总说明 v0.2`，Review 草案 v0.2 |
| 2 | `个股详情页产品需求文档_v_0_2.md` | `个股详情页产品需求文档 v0.2`，P0 PRD |
| 3 | `p0-data-dictionary-v0.7.md` | `P0 数据字典 v0.7`，Review v9 新闻速览与个股新闻板块修订稿 |
| 4 | `tushare接口文档/README.md` | Tushare 接口说明目录，本地镜像 README |
| 5 | `tushare接口文档/docs_index.csv` | Tushare 文档索引，含 `doc_id/title/api_name/category_path/source_url/local_path` |


---

## 0. 设计边界

### 0.1 页面定位

个股详情页属于 **乾坤行情**，不是独立一级菜单。它是 **A 股个股事实行情终端页**，用于查看个股 K 线、周期、技术指标、成交量、资金结构、关联板块和基础行情信息。

### 0.2 P0 API 边界

本轮只设计个股详情 P0 所需接口，不设计大而全证券 API。

API 不得返回：

```text
buySuggestion
sellSuggestion
positionAdvice
tradeAction
tomorrowPrediction
diagnosticConclusion
```

诊股能力 P0 disabled，不进入本接口返回。资料 Tab P0 只显示“暂未开通”，不返回完整股票资料页数据。

### 0.3 100vh 对 API 无影响

固定视口、`100vh`、`calc(100vh - 顶部固定区域高度)`、禁止 body 级滚动等，均为前端布局约束，不影响 API 返回结构。

---

## 1. 统一响应结构

```json
{
  "code": 0,
  "message": "ok",
  "data": {},
  "traceId": "req_20260514_000001",
  "serverTime": "2026-05-14T15:00:00+08:00"
}
```

## 2. 错误码

| code | 含义 | HTTP 建议 | 前端处理 |
|---:|---|---:|---|
| `0` | 成功 | 200 | 正常渲染 |
| `400001` | 参数错误 | 400 | 提示参数错误 |
| `401001` | 未登录 | 401 | 基础行情游客可看，用户动作引导登录 |
| `403001` | 无权限 | 403 | 展示无权限 |
| `404001` | 股票或数据不存在 | 404 | 展示空状态 |
| `409001` | 状态冲突 | 409 | 如停牌或周期不可用 |
| `429001` | 请求过快 | 429 | 降频重试 |
| `500001` | 服务异常 | 500 | 局部异常态 |
| `503001` | 数据源不可用 | 503 | 模块降级或使用 Mock/缓存 |

---

## 3. 支持周期

| period | 展示名 | 是否 P0 展示 | 数据策略 |
|---|---|---:|---|
| `time` | 分时 | 是 | P0 Mock，后续接真实分时 |
| `1m` | 1分 | 是 | P0 Mock，后续接分钟基座 |
| `5m` | 5分 | 是 | P0 Mock，后续接分钟基座 |
| `15m` | 15分 | 是 | P0 Mock，后续接分钟基座 |
| `30m` | 30分 | 是 | P0 Mock，后续接分钟基座 |
| `60m` | 60分 | 是 | P0 Mock，后续接分钟基座 |
| `90m` | 90分 | 是 | 可由分钟线聚合 |
| `120m` | 120分 | 是 | 可由分钟线聚合 |
| `day` | 日K | 是，默认 | `daily` 或 Mock |
| `week` | 周K | 是 | 日线聚合或周线源 |
| `month` | 月K | 是 | 日线聚合或月线源 |

---

# 4. GET /api/stocks/{stockCode}/detail-overview

## endpoint

```http
GET /api/stocks/{stockCode}/detail-overview
```

## method

`GET`

## 前端使用场景

一次性返回个股详情页右侧 StockHeader、盘口/资料 Tab 基础状态、关联板块表、个股资金统计、默认周期信息、数据更新时间和状态。

不返回 K 线数组和指标数组，K 线与指标由专用接口加载，避免聚合接口过大。

## request params

| 参数 | 位置 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---:|---|---|
| `stockCode` | path | string | 是 | - | 股票代码，如 `603806.SH` |
| `market` | query | string | 否 | `CN_A` | P0 固定 A 股 |
| `tradeDate` | query | string(date) | 否 | 最近交易日 | 指定交易日 |
| `adjustType` | query | enum | 否 | `qfq` | `none/qfq/hfq` |
| `includeMoneyFlow` | query | boolean | 否 | `true` | 是否返回资金统计 |
| `includeSectors` | query | boolean | 否 | `true` | 是否返回关联板块 |
| `mockMode` | query | boolean | 否 | `true` | P0 可先使用 Mock |

## response JSON / Mock 数据示例

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "quote": {
      "stockCode": "603806.SH",
      "stockName": "福斯特",
      "exchange": "SSE",
      "market": "主板",
      "industryName": "光伏设备",
      "latestPrice": 18.36,
      "prevClose": 18.01,
      "changeAmount": 0.35,
      "changePct": 1.94,
      "direction": "UP",
      "tradeStatus": "CLOSED",
      "updateTime": "2026-04-28T14:59:56+08:00",
      "dataStatus": "READY",
      "isWatched": true,
      "hasAlert": false,
      "hasTradePlan": true,
      "adjustType": "qfq",
      "defaultPeriod": "day",
      "diagnosisEnabled": false,
      "profileTabStatus": "NOT_OPEN"
    },
    "availablePeriods": ["time", "1m", "5m", "15m", "30m", "60m", "90m", "120m", "day", "week", "month"],
    "toolbar": {
      "defaultPeriod": "day",
      "enabledPeriods": ["time", "day", "week", "month", "120m", "90m", "60m", "30m", "15m", "5m", "1m"],
      "profileEntry": {
        "enabled": true,
        "status": "PLACEHOLDER",
        "label": "股票资料"
      },
      "diagnosisEntry": {
        "enabled": false,
        "status": "DISABLED",
        "label": "诊股"
      }
    },
    "relatedSectors": [
      {
        "sectorCode": "BK0421.DC",
        "sectorName": "光伏设备",
        "sectorType": "INDUSTRY",
        "changePct": 2.36,
        "componentStockCount": 126,
        "rank": 1,
        "route": "/market/sectors/BK0421.DC"
      },
      {
        "sectorCode": "BK0493.DC",
        "sectorName": "新能源",
        "sectorType": "CONCEPT",
        "changePct": 1.58,
        "componentStockCount": 238,
        "rank": 2,
        "route": "/market/sectors/BK0493.DC"
      }
    ],
    "moneyFlow": {
      "stockCode": "603806.SH",
      "tradeDate": "2026-04-28",
      "mainInflow": 18650.24,
      "mainOutflow": 14220.18,
      "mainNetInflow": 4430.06,
      "superLargeNet": 1260.00,
      "largeNet": 980.00,
      "mediumNet": -520.00,
      "smallNet": -1720.00,
      "items": [
        {
          "key": "superLargeNet",
          "label": "净特大",
          "amount": 1260.0,
          "ratio": 0.28,
          "direction": "UP"
        },
        {
          "key": "largeNet",
          "label": "净大单",
          "amount": 980.0,
          "ratio": 0.22,
          "direction": "UP"
        },
        {
          "key": "mediumNet",
          "label": "净中单",
          "amount": -520.0,
          "ratio": -0.12,
          "direction": "DOWN"
        },
        {
          "key": "smallNet",
          "label": "净小单",
          "amount": -1720.0,
          "ratio": -0.38,
          "direction": "DOWN"
        }
      ],
      "dataStatus": "READY"
    },
    "profileTab": {
      "status": "NOT_OPEN",
      "message": "暂未开通"
    }
  },
  "traceId": "req_stock_detail_000001",
  "serverTime": "2026-05-14T15:00:00+08:00"
}
```

## 字段说明

| 字段 | 说明 |
|---|---|
| `quote` | 个股基础行情，用于 StockHeader |
| `availablePeriods` | 当前页面周期入口，P0 全量展示 |
| `toolbar` | ChartToolbar 状态 |
| `relatedSectors` | 右侧盘口 Tab 关联板块表 |
| `moneyFlow` | 个股资金统计，用于环形图和金额柱 |
| `profileTab` | 资料 Tab P0 占位，不返回完整股票资料 |
| `diagnosisEntry.enabled=false` | 诊股 P0 disabled，不返回诊股结论 |

## 异常状态

| code | 场景 | 前端处理 |
|---:|---|---|
| `400001` | stockCode 格式错误 | 提示股票代码错误 |
| `404001` | 股票不存在 | 显示个股不存在 |
| `409001` | 股票停牌或交易状态冲突 | 显示交易状态，不影响历史 K 线 |
| `503001` | 行情源不可用 | StockHeader 局部异常，允许 K 线 Mock |
| `500001` | 服务异常 | 页面局部异常 |

## 空数据处理

1. `relatedSectors=[]`：显示“暂无关联板块”。
2. `moneyFlow.dataStatus=EMPTY`：显示“资金数据暂不可用”。
3. `profileTab.status=NOT_OPEN`：资料 Tab 显示“暂未开通”。
4. `diagnosisEntry.enabled=false`：诊股入口 disabled。

## 数据更新时间

| 模块 | 更新频率 |
|---|---|
| `quote` | P0 日频/Mock；后续实时 3-15 秒 |
| `relatedSectors` | 日频/按源 |
| `moneyFlow` | 盘后/按源；后续实时资金源接入后分钟级 |
| `toolbar` | 配置低频 |

## 缓存建议

- `quote`：盘中 3-15 秒，P0 Mock 可本地固定。
- `relatedSectors`：盘后 1 天。
- `moneyFlow`：盘后 1 天；实时资金源接入后 1-5 分钟。
- `toolbar`：配置缓存 1 天。

## 性能评估

P95 目标 `<200ms`。右侧信息栏数据应读取聚合快照，不在请求时实时 join 多张原始表。

## 暂缺数据字段清单

1. 实时盘口五档、逐笔成交：P0 不展示。
2. 完整股票资料：P0 资料 Tab 暂未开通。
3. 诊股结论：P0 disabled。
4. 实时资金流：P0 可 Mock 或使用盘后数据。

---

# 5. GET /api/stocks/{stockCode}/candles

## endpoint

```http
GET /api/stocks/{stockCode}/candles
```

## method

`GET`

## 前端使用场景

加载 K 线主图和十字线 Tooltip 所需数据。周期切换时调用该接口局部刷新图表区。

## request params

| 参数 | 位置 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---:|---|---|
| `stockCode` | path | string | 是 | - | 股票代码 |
| `period` | query | enum | 是 | `day` | `time/1m/5m/15m/30m/60m/90m/120m/day/week/month` |
| `adjustType` | query | enum | 否 | `qfq` | `none/qfq/hfq` |
| `startDate` | query | string(date) | 否 | 按 period 推导 | 开始日期 |
| `endDate` | query | string(date) | 否 | 最近交易日 | 结束日期 |
| `limit` | query | integer | 否 | `240` | 返回根数 |
| `mockMode` | query | boolean | 否 | `true` | P0 可先 Mock |

## response JSON / Mock 数据示例

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "stockCode": "603806.SH",
    "period": "day",
    "adjustType": "qfq",
    "items": [
      {
        "stockCode": "603806.SH",
        "period": "day",
        "tradeDate": "2026-04-26",
        "tradeTime": null,
        "open": 17.92,
        "high": 18.30,
        "low": 17.70,
        "close": 18.01,
        "prevClose": 17.88,
        "changeAmount": 0.13,
        "changePct": 0.73,
        "amplitude": 3.36,
        "volume": 112800,
        "amount": 205600,
        "turnoverRate": 0.98,
        "direction": "UP"
      },
      {
        "stockCode": "603806.SH",
        "period": "day",
        "tradeDate": "2026-04-28",
        "tradeTime": null,
        "open": 18.10,
        "high": 18.66,
        "low": 17.98,
        "close": 18.36,
        "prevClose": 18.01,
        "changeAmount": 0.35,
        "changePct": 1.94,
        "amplitude": 3.82,
        "volume": 128600,
        "amount": 236800,
        "turnoverRate": 1.24,
        "direction": "UP"
      }
    ],
    "dataStatus": "READY",
    "asOf": "2026-04-28T15:10:00+08:00"
  },
  "traceId": "req_stock_candles_000001",
  "serverTime": "2026-05-14T15:00:00+08:00"
}
```

## 字段说明

见 `StockCandle` 数据对象。日线字段默认参考 `daily` 和 `daily_basic`；分钟线字段参考 `stk_mins` 或分钟基座。

## 异常状态

| code | 场景 | 前端处理 |
|---:|---|---|
| `400001` | period 不支持 | Toast 或保持当前周期 |
| `404001` | K 线数据为空 | 图表区空态 |
| `409001` | 周期暂未接真实数据 | P0 使用 Mock 或显示暂不可用 |
| `503001` | K 线源不可用 | 图表区局部异常 |
| `500001` | 服务异常 | 图表区局部异常 |

## 空数据处理

`items=[]` 时，图表区展示“暂无 K 线数据”，右侧信息栏仍可展示。

## 数据更新时间

- `day/week/month`：日频/盘后。
- `1m/5m/15m/30m/60m/90m/120m`：P0 Mock；后续按分钟源。
- `time`：P0 Mock；后续按分时/实时源。

## 缓存建议

- 日线/周线/月线：盘后 1 天。
- 分钟线：盘中 15-60 秒或按源。
- P0 Mock：静态文件或前端内置。

## 性能评估

P95 `<220ms`。接口应分页或限制 `limit`，避免一次性返回过长历史。

## 暂缺字段清单

1. 真实分时 `time`。
2. 90m/120m 后端聚合。
3. 盘中实时更新。
4. 完整复权因子校验。

---

# 6. GET /api/stocks/{stockCode}/indicators

## endpoint

```http
GET /api/stocks/{stockCode}/indicators
```

## method

`GET`

## 前端使用场景

加载 K 线主图 MA/BOLL 叠加指标，以及副图 MACD、成交量、KDJ。周期切换或主图指标切换时局部刷新。

## request params

| 参数 | 位置 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---:|---|---|
| `stockCode` | path | string | 是 | - | 股票代码 |
| `period` | query | enum | 是 | `day` | K 线周期 |
| `adjustType` | query | enum | 否 | `qfq` | 复权类型 |
| `indicators` | query | string | 否 | `ma,boll,macd,volume,kdj` | 逗号分隔 |
| `startDate` | query | string(date) | 否 | 与 K 线一致 | 开始日期 |
| `endDate` | query | string(date) | 否 | 最近交易日 | 结束日期 |
| `limit` | query | integer | 否 | `240` | 返回点数 |
| `mockMode` | query | boolean | 否 | `true` | P0 可先 Mock |

## response JSON / Mock 数据示例

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "stockCode": "603806.SH",
    "period": "day",
    "adjustType": "qfq",
    "ma": [
      {
        "time": "2026-04-28",
        "ma5": 19.01,
        "ma15": 18.28,
        "ma30": 18.10,
        "ma60": 18.18,
        "ma120": 16.46,
        "ma250": 15.18
      }
    ],
    "boll": [
      {
        "time": "2026-04-28",
        "upper": 20.18,
        "mid": 18.72,
        "lower": 17.26,
        "period": 20,
        "stdMultiplier": 2
      }
    ],
    "macd": [
      {
        "time": "2026-04-28",
        "dif": 0.18,
        "dea": 0.12,
        "histogram": 0.12,
        "direction": "UP"
      }
    ],
    "volume": [
      {
        "time": "2026-04-28",
        "volume": 128600,
        "volumeMa5": 118200,
        "volumeMa10": 126800,
        "amount": 236800,
        "direction": "UP"
      }
    ],
    "kdj": [
      {
        "time": "2026-04-28",
        "k": 72.6,
        "d": 66.1,
        "j": 85.5
      }
    ],
    "dataStatus": "READY",
    "asOf": "2026-04-28T15:10:00+08:00"
  },
  "traceId": "req_stock_indicators_000001",
  "serverTime": "2026-05-14T15:00:00+08:00"
}
```

## 字段说明

见 `StockIndicatorSet`、`MAIndicator`、`BOLLIndicator`、`MACDIndicator`、`VolumeIndicator`、`KDJIndicator` 数据对象。

## 异常状态

| code | 场景 | 前端处理 |
|---:|---|---|
| `400001` | 指标名不支持 | Toast：该指标暂未支持 |
| `404001` | 指标数据为空 | 对应 panel 空态 |
| `409001` | 指标周期与 K 线周期不匹配 | 保持当前指标状态 |
| `503001` | 指标服务不可用 | 指标 panel 局部异常 |
| `500001` | 服务异常 | 局部异常 |

## 空数据处理

1. 某个指标为空，不影响其它指标。
2. 未支持指标点击后不调用接口，直接 Toast：`该指标暂未支持`。
3. 齿轮设置点击 Toast：`指标设置暂未开通`。

## 数据更新时间

与对应 K 线周期一致。P0 可以前端 Mock 或前端计算；后续可由后端返回。

## 缓存建议

- 与 candles 接口使用相同 cache key：`stockCode + period + adjustType + dateRange`。
- 日线指标盘后 1 天。
- 分钟指标盘中 15-60 秒。
- P0 Mock 静态缓存。

## 性能评估

P95 `<250ms`。指标应预计算或随 K 线批量计算，不建议每次请求重复扫描长历史。

## 暂缺字段清单

1. 指标参数设置。
2. 更多副图指标。
3. 多周期同屏。
4. 主力密码、融资融券、陆股通等非 P0 指标。

---

# 7. 页面模块与接口映射

| 页面模块 | 接口 | 关键对象 |
|---|---|---|
| StockHeader | `GET /api/stocks/{stockCode}/detail-overview` | StockBasicQuote |
| BreadcrumbActionBar | `detail-overview.quote` | StockBasicQuote |
| ChartToolbar | `detail-overview.toolbar` | 周期配置 |
| K 线主图 | `GET /api/stocks/{stockCode}/candles` | StockCandle |
| MA/BOLL 主图叠加 | `GET /api/stocks/{stockCode}/indicators` | MAIndicator / BOLLIndicator |
| MACD 副图 | `GET /api/stocks/{stockCode}/indicators` | MACDIndicator |
| 成交量副图 | `GET /api/stocks/{stockCode}/indicators` | VolumeIndicator |
| KDJ 副图 | `GET /api/stocks/{stockCode}/indicators` | KDJIndicator |
| 十字线 Tooltip | candles + indicators | StockCandle + indicators |
| 关联板块表 | `detail-overview.relatedSectors` | RelatedSectorItem |
| 个股资金统计 | `detail-overview.moneyFlow` | StockMoneyFlow |
| 资料 Tab | `detail-overview.profileTab` | Placeholder |
| 诊股入口 | `detail-overview.toolbar.diagnosisEntry` | disabled |

---

# 8. Mock / 真实数据边界

| 模块 | P0 策略 | 后续真实数据 |
|---|---|---|
| StockHeader | Mock 或 daily/daily_basic | 实时行情 |
| K 线 day/week/month | Mock 或 daily 聚合 | 日/周/月真实行情 |
| K 线分钟周期 | Mock | `stk_mins` 或分钟基座 |
| time 分时 | Mock | 分时/实时源 |
| MA/BOLL/MACD/VOL/KDJ | Mock 或前端计算 | 后端指标服务 |
| 关联板块 | Mock | `dc_member + dc_index + dc_daily` |
| 个股资金 | Mock | `moneyflow_dc` 或实时资金 |
| 股票资料 | 固定“暂未开通” | 独立资料页 |
| 诊股 | disabled | 后续单独能力 |

---

# 9. 给 02 HTML Showcase 的 Mock 数据建议

1. 默认股票使用 `603806.SH 福斯特`，周期默认 `day`。
2. K 线 mock 至少 120 根，保证 MA120 能展示；如要展示 MA250，可提供 260 根或允许前部为空。
3. MACD、成交量、KDJ 与 K 线时间点一一对齐。
4. 资金统计 mock 包含正负值，验证红涨绿跌。
5. 关联板块 mock 至少 4 条。
6. 资料 Tab 固定显示“暂未开通”。
7. 诊股按钮 disabled。
8. 100vh 只在 CSS 实现，不进入 mock 数据。

---

# 10. 给 03 组件 Props 的字段映射建议

| 组件 | Props |
|---|---|
| `StockDetailPage` | `overview`、`candles`、`indicators` |
| `StockHeaderPanel` | `quote: StockBasicQuote` |
| `StockChartToolbar` | `availablePeriods`、`defaultPeriod`、`adjustType` |
| `StockKlinePanel` | `candles: StockCandle[]`、`ma`、`boll` |
| `MacdPanel` | `macd: MACDIndicator[]` |
| `VolumePanel` | `volume: VolumeIndicator[]` |
| `KdjPanel` | `kdj: KDJIndicator[]` |
| `RelatedSectorTable` | `items: RelatedSectorItem[]` |
| `StockMoneyFlowPanel` | `moneyFlow: StockMoneyFlow` |
| `StockProfilePlaceholder` | `profileTab.status/message` |

---

# 11. 给 05 Codex 提示词的 API 约束

1. 不要实现买卖建议、诊股结论、明日预测。
2. 不要请求不存在的完整资料 Tab 数据。
3. `100vh` 是前端布局约束，不要写入 API mock。
4. 周期枚举必须完整：`time/1m/5m/15m/30m/60m/90m/120m/day/week/month`。
5. `candles` 与 `indicators` 时间点必须可对齐。
6. 十字线 Tooltip 从 `StockCandle + indicators` 组合读取。
7. 股票资料点击可进入占位或展示“暂未开通”；诊股 disabled。

---

# 12. 待产品总控确认问题

1. 分时 `time` 是否后续使用单独 time-share 对象？
2. `90m` / `120m` 是否由后端统一聚合？
3. P0 资金统计是否允许直接使用 Mock？
4. K 线默认返回根数是否固定为 240？
5. MA250 是否要求 P0 首屏完整显示，还是允许前序为空？
