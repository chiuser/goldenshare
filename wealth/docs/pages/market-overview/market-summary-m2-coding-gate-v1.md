# 市场总览｜今日市场客观总结 M2 编码前门禁 v1

> 用途：在编码前冻结“配置、响应、查询、状态、异常、性能”口径。  
> 阶段：M2 开工前。  
> 产物性质：执行门禁清单（不通过不允许编码）。

关联文档：

1. [今日市场客观总结标杆需求 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/market-summary-benchmark-requirement-v1.md)
2. [今日市场客观总结技术实施方案 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/market-summary-implementation-design-v1.md)

---

## 1. 目的

1. 本门禁对应模块：`marketSummary`。
2. 本门禁对应需求文档：`market-summary-benchmark-requirement-v1.md`。
3. 本门禁对应实施方案：`market-summary-implementation-design-v1.md`。

---

## 2. 总门禁清单（全通过才能开工）

1. [ ] `cardCount` 仅允许 `5/6` 已冻结
2. [ ] 默认 `cardCount=5`、第 6 卡默认关闭已冻结
3. [ ] 卡片定义（`cardKey` 集合与顺序）已冻结
4. [ ] 文本模板输入字段与输出样例已冻结（盘中/盘后）
5. [ ] 模块响应结构已冻结
6. [ ] 查询草案（含来源映射）已冻结
7. [ ] 状态归并样例已冻结
8. [ ] 异常码已登记并冻结
9. [ ] 性能预算与降级策略已冻结
10. [ ] 前端真实源加载态门禁已冻结（loading/ready/error）
11. [ ] 5 秒超时进入 error 且不展示 mock summary 的行为门禁已冻结
12. [ ] 签字完成

---

## 3. 请求与响应冻结

### 3.1 请求参数冻结

```ts
interface MarketSummaryRequest {
  market?: "CN_A";    // default: CN_A
  tradeDate?: string; // YYYY-MM-DD
  debug?: 0 | 1;      // default: 0
}
```

参数校验规则：

1. `market` 非 `CN_A` -> `400001`
2. `tradeDate` 非法格式 -> `400001`
3. `debug` 非 `0/1` -> `400001`

### 3.2 响应结构冻结

```ts
interface MarketSummaryResponseData {
  tradingDay: TradingDay;
  pageStatus: PageStatus;
  marketSummary: {
    definition: {
      definitionKey: string;
      version: string;
      cardCount: 5 | 6;
      textPosition: "BOTTOM_FIXED";
      layoutVariant: "FIVE_SINGLE_ROW" | "SIX_TWO_ROWS";
    };
    cards: MarketSummaryCard[];
    textCard: {
      title: string;
      content: string;
      templateKey: string;
    };
  };
  debugInfo?: {
    modules: ModuleStatusItem[];
    exceptions: ModuleExceptionItem[];
  };
}
```

说明：

1. `cardCount` 默认值必须是 `5`；
2. `cardCount=6` 只能在后端配置显式开启时生效；
3. 指数上涨数量由 summary 模块独立查询，不依赖主要指数模块内部产物。

---

## 4. 核心样例响应（最小集合）

### 4.1 正常样例（5 卡）

```json
{
  "tradingDay": {
    "tradeDate": "2026-05-08",
    "prevTradeDate": "2026-05-07",
    "market": "CN_A",
    "isTradingDay": true,
    "sessionStatus": "CLOSED",
    "timezone": "Asia/Shanghai"
  },
  "pageStatus": {
    "status": "READY",
    "displayText": "事实聚合已就绪",
    "asOfTime": "2026-05-08T20:07:00+08:00"
  },
  "marketSummary": {
    "definition": {
      "definitionKey": "CN_A_SUMMARY_V1",
      "version": "1.0.0",
      "cardCount": 5,
      "textPosition": "BOTTOM_FIXED",
      "layoutVariant": "FIVE_SINGLE_ROW"
    },
    "cards": [
      { "cardKey": "majorIndexUpCount", "label": "主要指数涨跌比", "value": "8:2", "subText": "上涨数量:下跌数量", "direction": "UP" },
      { "cardKey": "riseFallCount", "label": "上涨 / 下跌", "value": "3421 / 1488", "subText": "平盘 219", "direction": "UP" },
      { "cardKey": "turnoverTotal", "label": "成交总额", "value": "10523亿", "subText": "较昨日：+702亿", "direction": "UP" },
      { "cardKey": "marketNetFlow", "label": "大盘资金", "value": "-52.8亿", "subText": "净流出", "direction": "DOWN" },
      { "cardKey": "limitUpDown", "label": "涨停 / 跌停", "value": "59 / 8", "subText": "炸板 27", "direction": "UP" }
    ],
    "textCard": {
      "title": "截至收盘，A 股主要指数多数上涨。",
      "content": "全市场上涨家数多于下跌家数，成交额较上一交易日放大；涨停家数高于跌停家数。大盘资金今日为净流出，资金分布呈现分化。本卡片仅描述客观事实，不构成交易建议。",
      "templateKey": "objective_close_v1"
    }
  }
}
```

### 4.2 正常样例（6 卡）

```json
{
  "marketSummary": {
    "definition": {
      "definitionKey": "CN_A_SUMMARY_V1",
      "version": "1.1.0",
      "cardCount": 6,
      "textPosition": "BOTTOM_FIXED",
      "layoutVariant": "SIX_TWO_ROWS"
    },
    "cards": [
      { "cardKey": "majorIndexUpCount", "label": "主要指数涨跌比", "value": "8:2", "subText": "上涨数量:下跌数量" },
      { "cardKey": "riseFallCount", "label": "上涨 / 下跌", "value": "3421 / 1488" },
      { "cardKey": "flatCount", "label": "平盘家数", "value": "219" },
      { "cardKey": "turnoverTotal", "label": "成交总额", "value": "10523亿" },
      { "cardKey": "marketNetFlow", "label": "大盘资金", "value": "-52.8亿" },
      { "cardKey": "limitUpDown", "label": "涨停 / 跌停", "value": "59 / 8" }
    ],
    "textCard": {
      "title": "截至收盘，A 股主要指数多数上涨。",
      "content": "......",
      "templateKey": "objective_close_v1"
    }
  }
}
```

### 4.3 正常样例（盘中模板）

```json
{
  "tradingDay": { "sessionStatus": "TRADING" },
  "marketSummary": {
    "textCard": {
      "title": "截至当前时点，A 股主要指数多数上涨。",
      "content": "当前上涨家数多于下跌家数，成交活跃度较上一交易日同时段有所变化。以下为客观事实快照，不构成交易建议。",
      "templateKey": "objective_intraday_v1"
    }
  }
}
```

### 4.4 delayed 样例

```json
{
  "pageStatus": { "status": "PARTIAL", "displayText": "部分模块数据延迟" },
  "debugInfo": {
    "modules": [
      {
        "moduleKey": "marketSummary",
        "expectedTradeDate": "2026-05-08",
        "observedTradeDate": "2026-05-07",
        "lagDays": 1,
        "status": "DELAYED",
        "note": "market_moneyflow_dc date lagged"
      }
    ],
    "exceptions": [
      { "module": "marketSummary", "code": "MS_SOURCE_DELAYED", "severity": "warn", "message": "source lagged" }
    ]
  }
}
```

### 4.5 文案模板冻结表（编码前必须逐项确认）

| templateKey | sessionStatus | titleTemplate | contentTemplate |
|---|---|---|---|
| `objective_intraday_v1` | `PRE_OPEN/TRADING/BREAK` | `截至当前时点，A 股主要指数{majorIndexTone}。` | `当前上涨家数{upDownTone}下跌家数，成交活跃度较上一交易日同时段{turnoverTone}；涨停{limitUpDownTone}跌停。大盘资金当前为{fundFlowTone}。以下为客观事实快照，不构成交易建议。` |
| `objective_close_v1` | `CLOSED` | `截至收盘，A 股主要指数{majorIndexTone}。` | `全市场上涨家数{upDownTone}下跌家数，成交额较上一交易日{turnoverTone}；涨停{limitUpDownTone}跌停。大盘资金今日为{fundFlowTone}，资金分布呈现{flowPatternTone}。本卡片仅描述客观事实，不构成交易建议。` |

变量清单（必须齐全）：

1. `majorIndexTone`
2. `upDownTone`
3. `turnoverTone`
4. `limitUpDownTone`
5. `fundFlowTone`
6. `flowPatternTone`（仅盘后模板必需）

fallback（必须固定）：

1. `title`：`今日市场客观总结`
2. `content`：`当前可用数据不足，暂仅展示已确认的客观事实。`

---

## 5. 查询草案（可直接转实现）

1. 交易日草案：
   - `trade_calendar` 取 `tradeDate/prevTradeDate/is_open`。
2. 宽表聚合草案：
   - `equity_daily_bar` 单次聚合：
     - `up_count = sum(case pct_chg > 0)`
     - `down_count = sum(case pct_chg < 0)`
     - `flat_count = sum(case pct_chg = 0)`
     - `turnover_total = sum(amount)`
3. 资金草案：
   - `market_moneyflow_dc.net_amount` + `net_amount_rate`。
4. 涨跌停草案：
   - `limit_list_ths` 按 `limit_type` 统计涨停池、跌停池、炸板池；
   - 统计口径按 `ts_code` 去重（避免同日多记录重复计数）。
5. 指数上涨草案：
   - 在 summary 模块内独立查询同口径 10 指数集合并计算 `up/total`。

---

## 6. 状态归并样例

| 模块状态 | 页面状态 | 备注 |
|---|---|---|
| `READY` | `READY` | 全部关键源就绪 |
| `DELAYED` | `PARTIAL` | 至少一个关键源滞后 |
| `EMPTY` | `EMPTY` | 关键源全空 |
| `ERROR` | `ERROR` / `PARTIAL` | 按整页其他模块情况归并 |

---

## 7. 异常码覆盖矩阵

> 异常码必须来自  
> [exception-code-registry.md](/Users/congming/github/goldenshare/wealth/docs/system/exception-code-registry.md)

| code | 覆盖用例 | 触发条件 | 预期行为 |
|---|---|---|---|
| `MS_CONFIG_MISSING` | 配置缺失 | definition 未找到 | 模块 ERROR + debug 异常 |
| `MS_CARD_COUNT_INVALID` | 非法卡数 | cardCount 不在 5/6 | 模块 ERROR |
| `MS_SOURCE_DELAYED` | 数据滞后 | observed < expected | 模块 DELAYED |
| `MS_SOURCE_EMPTY` | 空数据 | 关键源无行 | 模块 EMPTY |
| `MS_TEXT_RENDER_FAILED` | 文案渲染失败 | 模板变量缺失/异常 | 模块 PARTIAL，textCard 降级 |

---

## 8. 性能门禁

1. P95 预算：`< 250ms`
2. 返回体预算：`< 20KB`
3. 最大并发预算：按 overview 页面默认并发策略
4. 超预算降级策略：先降 debug 明细，再做查询优化，不先引入复杂缓存

---

## 9. 测试门禁

1. 单元测试：
   - 配置合法性（5/6 卡）；
   - 卡片构建与文案渲染；
   - 状态归并。
2. 集成测试：
   - `/summary` 正常/延迟/空/错误。
3. 冒烟测试：
   - 前端在 5 卡与 6 卡响应下均正确渲染；
   - 真实源请求 pending 时显示 loading（状态基线第一格样式）；
   - 真实源请求超过 5 秒显示 error（状态基线第三格样式）；
   - loading/error 场景均不展示 mock summary 卡片。
4. debug 模式验证：
   - `debug=1` 返回模块状态与异常；
   - `debug=0` 不返回 debugInfo。

---

## 10. 签字清单

### 10.1 后端负责人

1. [ ] 配置与查询映射可实现
2. [ ] 状态归并无歧义
3. [ ] 异常码已登记

### 10.2 前端负责人

1. [ ] 5/6 卡布局都可消费
2. [ ] 文本卡固定位置逻辑清晰
3. [ ] debug 展示策略明确

### 10.3 架构/产品负责人

1. [ ] 范围未扩散
2. [ ] 语义保持客观
3. [ ] 可进入编码阶段

---

## 11. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-08 | 首版：建立 summary 模块 M2 编码前门禁 | Codex |
