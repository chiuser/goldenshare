# 财势乾坤｜P0 数据字典 v0.8

建议保存路径：`财势乾坤/数据字典与API文档/p0-data-dictionary-v0.8.md`  
负责人：`04_API 契约与数据字典`  
版本：`v0.8`  
状态：`个股详情页 P0 数据字典补充`  
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

## 0. 本轮设计边界

本版在 `p0-data-dictionary-v0.7.md` 基础上补充 **个股详情页 P0** 数据对象。只围绕个股详情 P0 页面所需的基础行情、K 线周期、技术指标、右侧信息栏、资金统计、关联板块和 Mock/真实数据边界建立对象口径，不设计大而全证券 API。

### 0.1 页面边界

1. 个股详情页属于 **乾坤行情**，不是独立一级菜单。
2. 个股详情页是 **A 股个股事实行情终端页**。
3. API 不得返回：
   - `buySuggestion`
   - `sellSuggestion`
   - `positionAdvice`
   - `tradeAction`
   - `tomorrowPrediction`
   - `diagnosticConclusion`
4. 诊股能力 P0 disabled，不进入本轮接口返回。
5. 资料 Tab P0 只显示“暂未开通”，不返回完整股票资料页数据。
6. 固定视口、`100vh`、主内容区高度 `calc(100vh - 顶部固定区域高度)` 都是前端布局约束，不影响 API 返回结构。
7. API 使用财势乾坤业务对象组织，不复刻 Tushare API。
8. 所有行情字段必须支持中国市场红涨绿跌：`UP=红`、`DOWN=绿`、`FLAT=灰`。

### 0.2 支持周期枚举

| period | 展示名称 | 用途 | P0 数据策略 |
|---|---|---|---|
| `time` | 分时 | 分时走势入口 | P0 可 Mock，后续接真实分时 |
| `1m` | 1分 | 分钟 K | P0 可 Mock，后续接 `stk_mins` 或分钟基座 |
| `5m` | 5分 | 分钟 K | P0 可 Mock，后续接 `stk_mins` 或分钟基座 |
| `15m` | 15分 | 分钟 K | P0 可 Mock，后续接 `stk_mins` 或分钟基座 |
| `30m` | 30分 | 分钟 K | P0 可 Mock，后续接 `stk_mins` 或分钟基座 |
| `60m` | 60分 | 分钟 K | P0 可 Mock，后续接 `stk_mins` 或分钟基座 |
| `90m` | 90分 | 扩展分钟 K | P0 可由分钟基座聚合 |
| `120m` | 120分 | 扩展分钟 K | P0 可由分钟基座聚合 |
| `day` | 日K | 默认周期 | P0 可接 `daily` |
| `week` | 周K | 周线 | P0 可由日线聚合或接周线源 |
| `month` | 月K | 月线 | P0 可由日线聚合或接月线源 |

### 0.3 Tushare / PostgreSQL 落库字段参考

| 个股详情能力 | 推荐参考数据集 | 关键源字段 |
|---|---|---|
| 股票基础信息 | `stock_basic` | `ts_code`、`name`、`market`、`exchange`、`industry` |
| 日 K | `daily` | `open`、`high`、`low`、`close`、`pre_close`、`change`、`pct_chg`、`vol`、`amount` |
| 换手率 / 量比 | `daily_basic` | `turnover_rate`、`volume_ratio` |
| 分钟 K | `stk_mins` | `trade_time`、`open`、`close`、`high`、`low`、`vol`、`amount` |
| 周/月 K | `stk_week_month_adj` 或日线聚合 | `freq`、`open`、`high`、`low`、`close`、`vol`、`amount` |
| 个股资金 | `moneyflow_dc` | `net_amount`、`buy_elg_amount`、`buy_lg_amount`、`buy_md_amount`、`buy_sm_amount` |
| 板块关联 | `dc_member`、`dc_index`、`dc_daily` | `ts_code`、`con_code`、`name`、`pct_change` |

---

# 1. StockBasicQuote

**对象定义**：个股详情页基础行情与右侧 StockHeader 状态对象。  
**所属系统**：乾坤行情 / 个股行情服务。  
**使用页面和模块**：StockHeader、BreadcrumbActionBar、盘口 Tab 基础行情。  
**数据来源**：`stock_basic`、`daily`、`daily_basic`、自选/提醒/交易计划服务。  
**更新频率**：P0 日频/Mock；后续接实时行情后 3-15 秒或按源刷新。  
**是否 P0 必需**：是。  
**与红涨绿跌显示的关系**：`latestPrice`、`changeAmount`、`changePct` 按 `direction` 红涨绿跌；行业、状态、按钮中性。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `stockCode` | string | 股票代码 | - | 是 | `603806.SH` | `stock_basic.ts_code` | 低频 | 是 | 无 |
| `stockName` | string | 股票名称 | - | 是 | `福斯特` | `stock_basic.name` | 低频 | 是 | 无 |
| `exchange` | enum | 交易所：`SSE` / `SZSE` / `BSE` | - | 是 | `SSE` | `stock_basic.exchange` | 低频 | 是 | 无 |
| `market` | string | 市场类型 | - | 否 | `主板` | `stock_basic.market` | 低频 | 是 | 无 |
| `industryName` | string | 所属行业 | - | 否 | `光伏设备` | `stock_basic.industry` / 板块映射 | 低频 | 是 | 无 |
| `latestPrice` | number | 最新价 / 收盘价 | 元 | 是 | `18.36` | `daily.close` / 实时源 | 按源 | 是 | 按 direction |
| `prevClose` | number | 昨收价 | 元 | 是 | `18.01` | `daily.pre_close` | 按源 | 是 | 无 |
| `changeAmount` | number | 涨跌额 | 元 | 是 | `0.35` | `daily.change` | 按源 | 是 | 正红负绿 |
| `changePct` | number | 涨跌幅 | % | 是 | `1.94` | `daily.pct_chg` | 按源 | 是 | 正红负绿 |
| `direction` | enum | `UP` / `DOWN` / `FLAT` / `UNKNOWN` | - | 是 | `UP` | `changePct` 派生 | 按源 | 是 | 必须 |
| `tradeStatus` | enum | `TRADING` / `SUSPENDED` / `CLOSED` / `UNKNOWN` | - | 是 | `CLOSED` | 交易日历 + 行情状态 | 分钟/日 | 是 | 状态色 |
| `updateTime` | datetime | 数据更新时间 | - | 是 | `2026-04-28T14:59:56+08:00` | 数据基座 | 按源 | 是 | 无 |
| `dataStatus` | enum | `READY` / `DELAYED` / `PARTIAL` / `EMPTY` / `ERROR` | - | 是 | `READY` | 数据源监控 | 按源 | 是 | 状态色 |
| `isWatched` | boolean | 是否已加入自选 | - | 否 | `true` | 自选服务 | 实时/缓存 | 是 | 无 |
| `hasAlert` | boolean | 是否有提醒 | - | 否 | `false` | 提醒服务 | 实时/缓存 | 是 | 无 |
| `hasTradePlan` | boolean | 是否有关联交易计划 | - | 否 | `true` | 交易计划服务 | 实时/缓存 | 是 | 无 |
| `adjustType` | enum | `none` / `qfq` / `hfq` | - | 是 | `qfq` | 请求/用户偏好 | 请求级 | 是 | 无 |
| `defaultPeriod` | enum | 默认周期，P0 为 `day` | - | 是 | `day` | 页面配置 | 低频 | 是 | 无 |
| `diagnosisEnabled` | boolean | 诊股是否可用，P0 固定 false | - | 是 | `false` | 系统配置 | 固定 | 是 | 无 |
| `profileTabStatus` | enum | 资料 Tab 状态，P0 固定 `NOT_OPEN` | - | 是 | `NOT_OPEN` | 系统配置 | 固定 | 是 | 无 |

---

# 2. StockCandle

**对象定义**：个股 K 线蜡烛图基础数据点，支持分时、分钟、日、周、月周期。  
**所属系统**：K 线服务 / 个股行情服务。  
**使用页面和模块**：K 线主图、十字线 Tooltip、Header Info、指标计算。  
**数据来源**：`daily`、`stk_mins`、后续实时分钟基座；周/月可由日线聚合。  
**更新频率**：日线日频；分钟线按源；P0 可 Mock。  
**是否 P0 必需**：是。  
**与红涨绿跌显示的关系**：K 线实体、涨幅、Tooltip OHLC 对比均需支持红涨绿跌。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `stockCode` | string | 股票代码 | - | 是 | `603806.SH` | 请求参数 | 请求级 | 是 | 无 |
| `period` | enum | `time/1m/5m/15m/30m/60m/90m/120m/day/week/month` | - | 是 | `day` | 请求参数 | 请求级 | 是 | 无 |
| `tradeDate` | string(date) | 交易日期 | - | 是 | `2026-04-28` | `daily.trade_date` / 分钟时间派生 | 按周期 | 是 | 无 |
| `tradeTime` | string(datetime) | 交易时间，分钟周期必填 | - | 否 | `2026-04-28T14:55:00+08:00` | `stk_mins.trade_time` | 按周期 | 是 | 无 |
| `open` | number | 开盘价 | 元 | 是 | `18.10` | `daily.open` / `stk_mins.open` | 按周期 | 是 | 与上一收盘或开盘比较 |
| `high` | number | 最高价 | 元 | 是 | `18.66` | `daily.high` / `stk_mins.high` | 按周期 | 是 | 高于比较基准红 |
| `low` | number | 最低价 | 元 | 是 | `17.98` | `daily.low` / `stk_mins.low` | 按周期 | 是 | 低于比较基准绿 |
| `close` | number | 收盘价 / 当前价 | 元 | 是 | `18.36` | `daily.close` / `stk_mins.close` | 按周期 | 是 | 按涨跌 |
| `prevClose` | number | 上一周期收盘价 | 元 | 否 | `18.01` | `daily.pre_close` / 前一根 K | 按周期 | 是 | 比较基准 |
| `changeAmount` | number | 涨跌额 | 元 | 否 | `0.35` | `daily.change` / 派生 | 按周期 | 是 | 正红负绿 |
| `changePct` | number | 涨跌幅 | % | 否 | `1.94` | `daily.pct_chg` / 派生 | 按周期 | 是 | 正红负绿 |
| `amplitude` | number | 振幅 | % | 否 | `3.82` | 派生 | 按周期 | 是 | 中性 |
| `volume` | number | 成交量 | 源口径，日线通常为手，分钟源按落库口径 | 否 | `128600` | `daily.vol` / `stk_mins.vol` | 按周期 | 是 | 中性 |
| `amount` | number | 成交额 | 源口径，日线通常为千元，分钟源按落库口径 | 否 | `236800` | `daily.amount` / `stk_mins.amount` | 按周期 | 是 | 中性 |
| `turnoverRate` | number | 换手率 | % | 否 | `1.24` | `daily_basic.turnover_rate` / 派生 | 日频/按源 | 是 | 中性 |
| `direction` | enum | 涨跌方向 | - | 是 | `UP` | `changePct` 派生 | 按周期 | 是 | 必须 |

---

# 3. StockIndicatorSet

**对象定义**：指定股票、周期、复权方式下的一组技术指标集合。  
**所属系统**：技术指标服务。  
**使用页面和模块**：K 线主图 MA/BOLL，副图 MACD、成交量、KDJ，Header Info，十字线 Tooltip。  
**数据来源**：由 `StockCandle[]` 计算；P0 可前端 Mock 或前端计算，后续后端返回。  
**更新频率**：与 K 线周期一致。  
**是否 P0 必需**：是。  
**与红涨绿跌显示的关系**：指标本身多为中性色，MACD 柱、成交量柱可按正负或涨跌方向渲染。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `stockCode` | string | 股票代码 | - | 是 | `603806.SH` | 请求参数 | 请求级 | 是 | 无 |
| `period` | enum | 周期 | - | 是 | `day` | 请求参数 | 请求级 | 是 | 无 |
| `adjustType` | enum | `none/qfq/hfq` | - | 是 | `qfq` | 请求参数 | 请求级 | 是 | 无 |
| `ma` | MAIndicator[] | 均线指标 | - | 否 | `[...]` | K 线计算 | 按周期 | 是 | 中性 |
| `boll` | BOLLIndicator[] | BOLL 指标 | - | 否 | `[...]` | K 线计算 | 按周期 | 是 | 中性 |
| `macd` | MACDIndicator[] | MACD 指标 | - | 否 | `[...]` | K 线计算 | 按周期 | 是 | MACD 柱正红负绿 |
| `volume` | VolumeIndicator[] | 成交量指标 | - | 否 | `[...]` | K 线计算 | 按周期 | 是 | 可按 K 线方向 |
| `kdj` | KDJIndicator[] | KDJ 指标 | - | 否 | `[...]` | K 线计算 | 按周期 | 是 | 中性 |

---

# 4. MAIndicator

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `time` | string(datetime/date) | 指标对应时间点 | - | 是 | `2026-04-28` | K 线时间 | 按周期 | 是 | 无 |
| `ma5` | number | 5 周期均线 | 元 | 否 | `19.01` | close 计算 | 按周期 | 是 | 中性 |
| `ma15` | number | 15 周期均线 | 元 | 否 | `18.28` | close 计算 | 按周期 | 是 | 中性 |
| `ma30` | number | 30 周期均线 | 元 | 否 | `18.10` | close 计算 | 按周期 | 是 | 中性 |
| `ma60` | number | 60 周期均线 | 元 | 否 | `18.18` | close 计算 | 按周期 | 是 | 中性 |
| `ma120` | number | 120 周期均线 | 元 | 否 | `16.46` | close 计算 | 按周期 | 是 | 中性 |
| `ma250` | number | 250 周期均线 | 元 | 否 | `15.18` | close 计算 | 按周期 | 是 | 中性 |

# 5. BOLLIndicator

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `time` | string(datetime/date) | 指标对应时间点 | - | 是 | `2026-04-28` | K 线时间 | 按周期 | 是 | 无 |
| `upper` | number | BOLL 上轨 | 元 | 否 | `20.18` | close 计算 | 按周期 | 是 | 中性 |
| `mid` | number | BOLL 中轨 | 元 | 否 | `18.72` | close 计算 | 按周期 | 是 | 中性 |
| `lower` | number | BOLL 下轨 | 元 | 否 | `17.26` | close 计算 | 按周期 | 是 | 中性 |
| `period` | integer | 计算周期 | - | 否 | `20` | 指标参数 | 固定/配置 | 是 | 无 |
| `stdMultiplier` | number | 标准差倍数 | - | 否 | `2` | 指标参数 | 固定/配置 | 是 | 无 |

# 6. MACDIndicator

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `time` | string(datetime/date) | 指标对应时间点 | - | 是 | `2026-04-28` | K 线时间 | 按周期 | 是 | 无 |
| `dif` | number | MACD DIF | - | 否 | `0.18` | close 计算 | 按周期 | 是 | 中性 |
| `dea` | number | MACD DEA | - | 否 | `0.12` | close 计算 | 按周期 | 是 | 中性 |
| `histogram` | number | MACD 柱 | - | 否 | `0.12` | `(dif-dea)*2` | 按周期 | 是 | 正红负绿 |
| `direction` | enum | 柱方向 | - | 否 | `UP` | histogram 派生 | 按周期 | 是 | 必须 |

# 7. VolumeIndicator

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `time` | string(datetime/date) | 指标对应时间点 | - | 是 | `2026-04-28` | K 线时间 | 按周期 | 是 | 无 |
| `volume` | number | 成交量 | 源口径 | 是 | `128600` | StockCandle.volume | 按周期 | 是 | 中性/可随K线 |
| `volumeMa5` | number | 5 周期成交量均线 | 源口径 | 否 | `118200` | 成交量计算 | 按周期 | 是 | 中性 |
| `volumeMa10` | number | 10 周期成交量均线 | 源口径 | 否 | `126800` | 成交量计算 | 按周期 | 是 | 中性 |
| `amount` | number | 成交额 | 源口径 | 否 | `236800` | StockCandle.amount | 按周期 | 是 | 中性 |
| `direction` | enum | 成交量柱方向，可跟随 K 线涨跌 | - | 否 | `UP` | K 线 direction | 按周期 | 是 | 可用 |

# 8. KDJIndicator

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `time` | string(datetime/date) | 指标对应时间点 | - | 是 | `2026-04-28` | K 线时间 | 按周期 | 是 | 无 |
| `k` | number | K 值 | - | 否 | `72.6` | K 线计算 | 按周期 | 是 | 中性 |
| `d` | number | D 值 | - | 否 | `66.1` | K 线计算 | 按周期 | 是 | 中性 |
| `j` | number | J 值 | - | 否 | `85.5` | K 线计算 | 按周期 | 是 | 中性 |

---

# 9. RelatedSectorItem

**对象定义**：个股关联板块表行对象。  
**所属系统**：板块行情服务 / 个股详情服务。  
**使用页面和模块**：右侧信息栏 / 盘口 Tab / 关联板块表。  
**数据来源**：`dc_member`、`dc_index`、`dc_daily`，P0 可 Mock。  
**更新频率**：日频/按源。  
**是否 P0 必需**：是。  
**与红涨绿跌显示的关系**：`changePct` 正红负绿。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `sectorCode` | string | 板块代码 | - | 是 | `BK1184.DC` | `dc_member.ts_code` | 日频 | 是 | 无 |
| `sectorName` | string | 板块名称 | - | 是 | `光伏设备` | `dc_index.name` | 日频 | 是 | 无 |
| `sectorType` | enum | `INDUSTRY/CONCEPT/REGION` | - | 是 | `INDUSTRY` | `dc_index.idx_type` | 日频 | 是 | 无 |
| `changePct` | number | 板块涨幅 | % | 是 | `2.36` | `dc_daily.pct_change` | 日频 | 是 | 正红负绿 |
| `componentStockCount` | integer | 成分股数 | 只 | 是 | `126` | `dc_member` 聚合 | 日频 | 是 | 中性 |
| `rank` | integer | 展示排序 | - | 否 | `1` | 服务端排序 | 请求级 | 否 | 无 |
| `route` | string | 板块详情路由，P0 可预留 | - | 否 | `/market/sectors/BK1184.DC` | 前端路由配置 | 低频 | 否 | 无 |

---

# 10. StockMoneyFlow

**对象定义**：个股资金统计对象，用于右侧盘口 Tab 资金统计环形图和金额柱状图。  
**所属系统**：个股资金流服务。  
**使用页面和模块**：右侧信息栏 / 盘口 Tab / 个股资金统计。  
**数据来源**：`moneyflow_dc`，P0 可 Mock。  
**更新频率**：盘后/按源；实时资金接入后分钟级。  
**是否 P0 必需**：是。  
**与红涨绿跌显示的关系**：净流入正红，净流出负绿；流入/流出标签按组件规则。

| 字段 | 类型 | 字段说明 | 单位 | 必填 | 示例值 | 数据来源 | 更新频率 | P0 必需 | 红涨绿跌关系 |
|---|---|---|---|---|---|---|---|---|---|
| `stockCode` | string | 股票代码 | - | 是 | `603806.SH` | 请求参数 | 请求级 | 是 | 无 |
| `tradeDate` | string(date) | 交易日 | - | 是 | `2026-04-28` | `moneyflow_dc.trade_date` | 日频 | 是 | 无 |
| `mainInflow` | number | 主力流入 | moneyflow_dc 源口径，通常万元 | 是 | `18650.24` | 资金流源 | 按源 | 是 | 红/中性 |
| `mainOutflow` | number | 主力流出 | moneyflow_dc 源口径，通常万元 | 是 | `14220.18` | 资金流源 | 按源 | 是 | 绿/中性 |
| `mainNetInflow` | number | 主力净流入 | moneyflow_dc 源口径，通常万元 | 是 | `4430.06` | `moneyflow_dc.net_amount` | 按源 | 是 | 正红负绿 |
| `superLargeNet` | number | 净特大单 | moneyflow_dc 源口径 | 是 | `1260.00` | `buy_elg_amount` 等 | 按源 | 是 | 正红负绿 |
| `largeNet` | number | 净大单 | moneyflow_dc 源口径 | 是 | `980.00` | `buy_lg_amount` 等 | 按源 | 是 | 正红负绿 |
| `mediumNet` | number | 净中单 | moneyflow_dc 源口径 | 是 | `-520.00` | `buy_md_amount` 等 | 按源 | 是 | 正红负绿 |
| `smallNet` | number | 净小单 | moneyflow_dc 源口径 | 是 | `-1720.00` | `buy_sm_amount` 等 | 按源 | 是 | 正红负绿 |
| `items` | object[] | 环形图/柱状图分项 | - | 是 | `[...]` | 派生 | 按源 | 是 | 按正负 |
| `dataStatus` | enum | 数据状态 | - | 是 | `READY` | 监控服务 | 按源 | 是 | 状态色 |

---

# 11. 个股详情 v0.8 修订清单

## 11.1 本轮新增对象

1. `StockBasicQuote`
2. `StockCandle`
3. `StockIndicatorSet`
4. `MAIndicator`
5. `BOLLIndicator`
6. `MACDIndicator`
7. `VolumeIndicator`
8. `KDJIndicator`
9. `RelatedSectorItem`
10. `StockMoneyFlow`

## 11.2 本轮未修改模块

1. 市场总览相关对象。
2. 市场温度与情绪对象。
3. 榜单、板块、连板天梯对象。
4. 交易建议、诊股、资料页完整数据。

## 11.3 P0 已具备字段

| 能力 | 推荐来源 |
|---|---|
| 股票名称、代码、行业 | `stock_basic` |
| 日 K OHLC、涨跌幅、成交量、成交额 | `daily` |
| 换手率、量比、市值 | `daily_basic` |
| 分钟 K | `stk_mins` 或分钟基座，P0 可 Mock |
| 板块关联 | `dc_member + dc_index + dc_daily`，P0 可 Mock |
| 个股资金 | `moneyflow_dc`，P0 可 Mock |

## 11.4 P0 暂缺字段

| 字段/能力 | 说明 |
|---|---|
| 真实分时 / 多分钟周期全覆盖 | 需要分钟行情基座稳定接入 |
| `90m` / `120m` 周期 | 可由分钟线聚合，需后端聚合服务 |
| 实时资金流 | P0 可 Mock 或盘后数据 |
| 完整股票资料 | P0 资料 Tab 暂未开通 |
| 诊股结论 | P0 disabled，禁止返回 |
| 指标参数设置 | P0 齿轮只 Toast，不开通设置 |

## 11.5 需要数据基座补充的字段/视图

1. `wealth_stock_quote_snapshot`
2. `wealth_stock_candle_snapshot`
3. `wealth_stock_indicator_snapshot`
4. `wealth_stock_related_sector_snapshot`
5. `wealth_stock_moneyflow_snapshot`
6. `wealth_stock_period_config`
7. `wealth_stock_profile_placeholder_config`

## 11.6 待产品总控确认问题

1. 分时 `time` 是否后续使用单独 time-share 对象？
2. `90m` / `120m` 是否由后端统一聚合？
3. P0 资金统计是否允许直接使用 Mock？
4. K 线默认返回根数是否固定为 240？
5. MA250 是否要求 P0 首屏完整显示，还是允许前序为空？
