# 股票详情页 stk_factor_pro 数据覆盖审计 v1

> 目的：审计 `stk_factor_pro` / `core_serving.equity_factor_pro` 能覆盖股票详情页多少数据需求，避免后续真实 API 设计时把它误用成整页万能数据源。  
> 范围：只分析数据覆盖能力，不改代码、不设计最终 API。  
> 页面分区：K线区、指标区、右侧股票信息区。

---

## 1. 审计依据

### 1.1 页面侧依据

1. 股票详情页当前首版仍是 UI + mock：
   - `wealth/src/features/stock-detail/model/stockDetailTypes.ts`
   - `wealth/src/features/stock-detail/api/stockDetailMockAdapter.ts`
2. 股票详情页三件套：
   - `wealth/docs/pages/stock-detail/stock-detail-benchmark-requirement-v1.md`
   - `wealth/docs/pages/stock-detail/stock-detail-implementation-design-v1.md`
   - `wealth/docs/pages/stock-detail/stock-detail-m2-coding-gate-v1.md`

### 1.2 数据集与代码依据

1. Tushare 源文档：
   - `docs/sources/tushare/股票数据/特色数据/0328_股票技术面因子(专业版).md`
2. 数据集事实源：
   - `src/foundation/datasets/definitions/market_equity.py` 中 `stk_factor_pro`
3. ORM 模型：
   - `src/foundation/models/core/equity_factor_pro.py`
4. 现有后端引用：
   - `src/biz/queries/quote_query_service.py` 已使用 `EquityFactorPro` 覆盖日线 MACD/KDJ 指标。

### 1.3 远程库只读核验

只读检查结果：

```text
core_serving.equity_factor_pro
row_count: 1,878,992
min_trade_date: 2025-01-02
max_trade_date: 2026-05-29
```

已确认字段包括：

```text
ts_code, trade_date,
open, high, low, close, pre_close, change, pct_chg,
open_qfq, high_qfq, low_qfq, close_qfq,
vol, amount, turnover_rate, volume_ratio,
ma_bfq_5, ma_bfq_10, ma_bfq_20, ma_bfq_30, ma_bfq_60, ma_bfq_90, ma_bfq_250,
boll_upper_bfq, boll_mid_bfq, boll_lower_bfq,
macd_bfq, macd_dif_bfq, macd_dea_bfq,
kdj_bfq, kdj_k_bfq, kdj_d_bfq
```

样本 `603806.SH / 2026-05-29` 存在完整 OHLC、量额、换手、量比、MA、BOLL、MACD、KDJ 字段。

---

## 2. 总体结论

`stk_factor_pro` 非常适合作为股票详情页“日频行情 + 日频技术因子”的基础数据源，但不能单独支撑整个股票详情页。

它能覆盖：

1. 日K 的 OHLC、成交量、成交额、涨跌额、涨跌幅。
2. 不复权 / 前复权 / 后复权价格字段。
3. 部分均线、BOLL、MACD、KDJ 等日频技术指标。
4. 右侧盘口摘要中的部分日频字段，例如今开、最高、最低、昨收、换手率、量比、成交量、成交额。

它不能覆盖：

1. 分时、1/5/15/30/60/90/120 分钟 K 线。
2. 周K、月K 的专用周月线口径。
3. 股票名称、行业、概念标签、股票资料。
4. 关联板块。
5. 个股资金结构、大单净量、主力资金、融资融券、陆股通等资金类指标。
6. 自选、提醒、交易计划等用户侧状态。

关键限制：

1. `stk_factor_pro` 是交易日日频数据，不是实时行情，也不是分钟线数据。
2. 当前 UI 使用 `MA15`、`MA120`，但 `stk_factor_pro` 直接提供的是 `MA5/10/20/30/60/90/250`，没有 `MA15/MA120`。
3. `KDJ` 字段在表中是 `kdj_*`、`kdj_k_*`、`kdj_d_*`。现有后端代码把 `kdj_*` 当作 `J` 值使用，这与字段命名不完全直观，后续正式 API 设计时应保留这个映射说明。

---

## 3. K线区覆盖审计

### 3.1 当前 K线区需要的数据

来自 `StockCandlePoint` 和页面交互，K线区至少需要：

| 页面需要 | 字段/语义 | `stk_factor_pro` 覆盖情况 | 说明 |
|---|---|---|---|
| 交易日期 | `trade_date` / `fullDate` | 可直接覆盖 | 日频交易日。 |
| 日K 开高低收 | `open/high/low/close` | 可直接覆盖 | 不复权口径。 |
| 前复权日K | `open_qfq/high_qfq/low_qfq/close_qfq` | 可直接覆盖 | 可用于前复权视图。 |
| 后复权日K | `open_hfq/high_hfq/low_hfq/close_hfq` | 可直接覆盖 | 可用于后复权视图。 |
| 昨收 | `pre_close` | 可直接覆盖 | 文档提示该字段为 daily 的 `pre_close`，前复权对比时需谨慎说明。 |
| 涨跌额 | `change` | 可直接覆盖 | 日频。 |
| 涨跌幅 | `pct_chg` | 可直接覆盖 | 日频。 |
| 成交量 | `vol` | 可直接覆盖 | 单位为手。 |
| 成交额 | `amount` | 可直接覆盖 | Tushare 文档单位为千元。前端展示需统一换算。 |
| 分时 | `timeShare` | 不覆盖 | 需要分钟/实时数据。 |
| 1/5/15/30/60/90/120 分钟 | 分钟 K 线 | 不覆盖 | 应来自分钟线数据，例如 `stk_mins`。 |
| 周K/月K | 周月周期 K 线 | 不直接覆盖 | 应使用周月线数据，或后续单独定义由日线聚合的规则。 |
| 右侧最新价浮标 | 当前 candle close | 可由日K close 支撑 | 仅盘后静态日线，不是实时价。 |
| hover tooltip | 日期、开高低收 | 可直接覆盖 | 仅日线周期。 |

### 3.2 K线区结论

1. 如果股票详情页的当前周期是 `日K`，`stk_factor_pro` 可以作为主 K 线数据源。
2. 如果当前周期是 `分时` 或分钟级周期，`stk_factor_pro` 不可用。
3. 如果当前周期是 `周K/月K`，不建议直接用 `stk_factor_pro` 假装覆盖，应走周月线专用数据或明确日线聚合规则。
4. 如果使用前复权/后复权，`stk_factor_pro` 有完整 qfq/hfq 价格字段，比在前端临时计算更稳。

---

## 4. 指标区覆盖审计

### 4.1 当前指标区需要的数据

当前股票详情页指标栏包含：

```text
VOL、成交额、均线、大单净量、MACD、KDJ、主力密码、融资融券、
陆股通资金、陆股通持股、AI机构活跃度、资金抄底、资金仓位、BOLL、更多
```

### 4.2 指标逐项覆盖

| 指标 | 页面含义 | `stk_factor_pro` 覆盖情况 | 可用字段/缺口 |
|---|---|---|---|
| VOL | 成交量柱与量均线 | 部分覆盖 | `vol` 可覆盖柱状成交量；量均线需要从 `vol` 序列计算。 |
| 成交额 | 成交额柱与均线 | 部分覆盖 | `amount` 可覆盖成交额；成交额均线需要计算。 |
| 均线 | MA 覆盖线 | 部分覆盖 | 可直接用 `ma_*_5/10/20/30/60/90/250`；不能直接提供当前 UI 的 `MA15/MA120`。 |
| BOLL | 布林线 | 可直接覆盖 | `boll_upper_*`、`boll_mid_*`、`boll_lower_*`。 |
| MACD | DIF/DEA/MACD | 可直接覆盖 | `macd_dif_*`、`macd_dea_*`、`macd_*`。现有 `quote_query_service.py` 已按复权后缀读取。 |
| KDJ | K/D/J | 可覆盖，但需说明映射 | `kdj_k_*`、`kdj_d_*`、`kdj_*`。现有代码把 `kdj_*` 映射为 `J`。 |
| 大单净量 | 大单资金/成交结构 | 不覆盖 | 需要资金流、逐笔或订单流类数据。 |
| 主力密码 | 自定义主力指标 | 不覆盖 | 需要另行定义算法和数据源。 |
| 融资融券 | 两融数据 | 不覆盖 | 需要 margin 相关数据集。 |
| 陆股通资金 | 北向/陆股通资金 | 不覆盖 | 需要沪深港通或北向资金相关数据源。 |
| 陆股通持股 | 陆股通持股变化 | 不覆盖 | 需要持股明细数据源。 |
| AI机构活跃度 | 自定义活跃度指标 | 不覆盖 | 需要单独模型或算法。 |
| 资金抄底 | 自定义资金信号 | 不覆盖 | 需要资金流与价格行为组合计算。 |
| 资金仓位 | 自定义资金仓位 | 不覆盖 | 需要单独算法和数据源。 |
| 更多 | 扩展指标入口 | 部分覆盖 | `stk_factor_pro` 还含 RSI、WR、OBV、MFI、CCI、ATR 等技术因子，可作为后续扩展来源。 |

### 4.3 指标区关键差异

#### 4.3.1 MA15 / MA120 缺口

当前前端类型与 mock 中存在：

```text
ma5, ma15, ma30, ma60, ma120, ma250
```

`stk_factor_pro` 直接提供：

```text
ma_5, ma_10, ma_20, ma_30, ma_60, ma_90, ma_250
```

因此后续真实 API 有两个选择：

1. 调整页面均线档位，与数据源直接字段对齐，例如 `MA5/MA10/MA20/MA30/MA60/MA250`。
2. 保持页面 `MA15/MA120`，由后端基于日线 close 序列计算，不能从 `stk_factor_pro` 直接读取。

不建议前端自行计算，因为这会让页面拼装事实字段，违背当前 `wealth` 的数据 contract 规则。

#### 4.3.2 KDJ J 值映射

字段命名为：

```text
kdj_*,
kdj_k_*,
kdj_d_*
```

现有 `src/biz/queries/quote_query_service.py` 中：

```text
kdj_k_* -> k
kdj_d_* -> d
kdj_*   -> j
```

后续正式股票详情 API 可以沿用该映射，但文档和 schema 必须写清楚，避免开发者误以为 `kdj_*` 是 KDJ 综合值而不是 J 值。

---

## 5. 右侧股票信息区覆盖审计

### 5.1 当前右侧信息区需要的数据

来自当前 `StockDetailViewModel`：

1. 股票身份：名称、代码、市场、行业/概念标签。
2. 股票头部报价：最新价、涨跌额、涨跌幅。
3. 盘口摘要：今开、昨收、最高、最低、换手率、量比、成交量、成交额。
4. 关联板块：板块名称、涨跌幅、数量、类型。
5. 个股资金统计：不同资金类型的净额、方向、占比。
6. 产品边界说明。
7. 自选、提醒、交易计划等用户侧动作。

### 5.2 右侧信息区逐项覆盖

| 区域 | 页面需要 | `stk_factor_pro` 覆盖情况 | 说明 |
|---|---|---|---|
| 股票代码 | `tsCode` | 可直接覆盖 | `ts_code`。 |
| 股票名称 | `name` | 不覆盖 | 需要股票基础信息或 security serving。 |
| 市场 | `market` | 不覆盖 | 需要基础资料或代码规则映射。 |
| 行业/标签 | `sector/tags` | 不覆盖 | 需要行业、概念、板块成员数据。 |
| 最新价 | `price` | 可用日线 close 覆盖 | 盘后静态口径，不是实时价。 |
| 涨跌额 | `change` | 可直接覆盖 | 日频。 |
| 涨跌幅 | `pct_chg` | 可直接覆盖 | 日频。 |
| 今开 | `open` | 可直接覆盖 | 日频。 |
| 昨收 | `pre_close` | 可直接覆盖 | 注意复权口径说明。 |
| 最高 | `high` | 可直接覆盖 | 日频。 |
| 最低 | `low` | 可直接覆盖 | 日频。 |
| 换手率 | `turnover_rate` | 可直接覆盖 | 也有 `turnover_rate_f`。 |
| 量比 | `volume_ratio` | 可直接覆盖 | 日频。 |
| 成交量 | `vol` | 可直接覆盖 | 单位为手。 |
| 成交额 | `amount` | 可直接覆盖 | 源单位千元，展示需换算。 |
| PE/PB/市值 | 估值类扩展 | 可直接覆盖 | `pe/pe_ttm/pb/ps/total_mv/circ_mv` 等，可用于资料页扩展。 |
| 关联板块 | 板块表格 | 不覆盖 | 需要 `dc_member`、`ths_member`、`dc_daily`、`dc_index` 等。 |
| 个股资金结构 | 资金净流向 | 不覆盖 | 需要个股 moneyflow 类数据。 |
| 产品边界说明 | 静态说明 | 不覆盖 | 应由前端/配置/API 文案提供。 |
| 自选/提醒/交易计划 | 用户状态 | 不覆盖 | 需要用户系统或后续交易计划模块。 |

### 5.3 右侧信息区结论

`stk_factor_pro` 可作为右侧“盘口摘要”的日频事实来源，但不能作为右侧信息栏的完整来源。

后续真实 API 需要组合至少以下来源：

1. `core_serving.equity_factor_pro`：日频行情、换手、量比、估值、技术因子。
2. 股票基础信息 / security serving：名称、上市状态、市场、行业基础信息。
3. 板块成员与板块行情：关联板块。
4. 个股资金流：资金结构。
5. 用户系统：自选、提醒、交易计划。

---

## 6. 与现有后端代码的关系

当前 `src/biz/queries/quote_query_service.py` 已经在日线指标覆盖中使用 `EquityFactorPro`：

1. 根据复权口径选择后缀：
   - `normal -> bfq`
   - `forward -> qfq`
   - `backward -> hfq`
2. 读取：
   - `macd_dif_*`
   - `macd_dea_*`
   - `macd_*`
   - `kdj_k_*`
   - `kdj_d_*`
   - `kdj_*`
3. 覆盖到返回的 K 线 bar：
   - `dif`
   - `dea`
   - `macd`
   - `k`
   - `d`
   - `j`

这说明工程里已经把 `stk_factor_pro` 作为日线技术指标来源之一。后续股票详情真实 API 不应重新发明另一套 KDJ/MACD 映射口径，除非先评审并统一替换。

---

## 7. 推荐后续数据组合方向

### 7.1 日K / 日频指标

推荐主源：

```text
core_serving.equity_factor_pro
```

适用内容：

1. 日K OHLCV。
2. 前复权 / 后复权日K。
3. MA、BOLL、MACD、KDJ、RSI、WR、OBV、MFI 等技术指标。
4. 盘口摘要中的日频字段。

### 7.2 分钟与分时

不应使用 `stk_factor_pro`。

候选来源：

```text
raw_tushare.stk_mins / 对应分钟线服务表
```

需要单独评估：

1. 数据量。
2. 查询性能。
3. 分钟周期聚合。
4. 前端图表加载窗口。

### 7.3 周K/月K

不建议直接用 `stk_factor_pro`。

候选方案：

1. 使用股票周线/月线数据集。
2. 或由日线聚合，但必须先定义聚合规则、复权规则和交易日边界。

### 7.4 右侧栏

推荐拆源组合：

| 右侧模块 | 推荐来源 |
|---|---|
| 股票身份 | security serving / stock_basic |
| 盘口摘要 | `equity_factor_pro` 最新交易日 |
| 关联板块 | `dc_member`、`ths_member`、`dc_daily`、`dc_index` 等 |
| 个股资金统计 | moneyflow / moneyflow_dc 等个股资金流数据 |
| 自选/提醒/交易计划 | 用户系统 |

---

## 8. 风险与待确认项

### 8.1 待确认：MA 档位

当前 UI 使用 `MA15/MA120`，但 `stk_factor_pro` 不直接提供。

需要后续拍板：

1. 页面改为展示源表已有的 `MA10/MA20/MA90` 等；
2. 或后端计算 `MA15/MA120` 后返回。

### 8.2 待确认：KDJ J 值命名

当前代码把 `kdj_*` 作为 `J` 值使用。该口径已有代码事实，但后续 API 文档必须写清楚，否则容易误用。

### 8.3 风险：日线静态数据被误认为实时行情

`stk_factor_pro` 是交易日日频数据。股票详情页如果展示“最新价”，需要明确这是盘后 / 最新交易日静态口径，不是实时 tick。

### 8.4 风险：用单一数据源硬凑整页

如果强行让 `stk_factor_pro` 覆盖关联板块、资金结构、用户动作，会导致字段造假或前端拼装。后续真实 API 必须采用组合源，由后端聚合成稳定 contract。

---

## 9. 分区覆盖结论表

| 页面区域 | 覆盖程度 | 可直接取自 `stk_factor_pro` | 需要补充的数据 |
|---|---:|---|---|
| K线区 | 中高 | 日K OHLCV、复权价格、涨跌额、涨跌幅、成交量、成交额 | 分时、分钟线、周线、月线、周期切换数据 |
| 指标区 | 中 | MA 部分周期、BOLL、MACD、KDJ、RSI/WR/OBV/MFI 等扩展因子 | MA15/MA120、资金类指标、两融、陆股通、自定义信号 |
| 右侧股票信息区 | 中低 | 盘口摘要中的日频行情、换手率、量比、成交量、成交额、估值扩展 | 名称/标签/行业、关联板块、个股资金、用户动作、产品文案 |

---

## 10. 结论

`stk_factor_pro` 应被定位为股票详情页的“日频行情 + 技术因子底座”，而不是整页详情数据源。

最合理的使用方式：

1. 日K 主图和日频指标优先使用 `core_serving.equity_factor_pro`。
2. 分钟线、分时、周月线、资金、板块、用户状态分别接入各自领域数据源。
3. 后端股票详情 API 负责组合这些来源，前端只消费稳定的 `StockDetailViewModel`，不得自行拼装数据事实。

