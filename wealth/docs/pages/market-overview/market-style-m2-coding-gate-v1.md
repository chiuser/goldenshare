# 市场总览｜市场风格 M2 编码前门禁 v1

> 用途：在编码前冻结“市场风格”模块的参数、响应、查询、状态、异常与性能。  
> 阶段：M2 开工前。  
> 产物性质：执行门禁清单（不通过不允许编码）。

关联文档：

1. [市场风格标杆需求 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/market-style-benchmark-requirement-v1.md)
2. [市场风格技术实施方案 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/market-style-implementation-design-v1.md)

---

## 1. 目的

1. 本门禁对应模块：`style`
2. 本门禁对应需求文档：`market-style-benchmark-requirement-v1.md`
3. 本门禁对应实施方案：`market-style-implementation-design-v1.md`

---

## 2. 总门禁清单（全通过才能开工）

1. [ ] 三卡来源配置结构冻结
2. [ ] 中位数计算口径冻结（离散中位）
3. [ ] 请求与响应结构冻结
4. [ ] 核心样例响应冻结
5. [ ] 查询草案冻结
6. [ ] 状态归并样例冻结
7. [ ] 异常覆盖矩阵冻结
8. [ ] 性能预算冻结
9. [ ] 签字完成

---

## 3. 请求与响应冻结

### 3.1 请求参数冻结

```ts
interface MarketStyleRequest {
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
interface MarketStyleResponseData {
  tradingDay: TradingDay;
  pageStatus: PageStatus;
  style: {
    definition: {
      definitionKey: string;
      version: string;
      fixedCardCount: 3;
    };
    cards: MarketStyleCard[]; // length always 3
    historyByRange: {
      oneMonth: MarketStyleHistoryPoint[];
      threeMonth: MarketStyleHistoryPoint[];
    };
  };
  debugInfo?: {
    modules: ModuleStatusItem[];
    exceptions: ModuleExceptionItem[];
  };
}
```

---

## 4. 核心样例响应（最小集合）

### 4.1 正常样例

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
  "pageStatus": { "status": "READY", "displayText": "数据已就绪" },
  "style": {
    "definition": {
      "definitionKey": "CN_A_MARKET_STYLE_V1",
      "version": "1.0.0",
      "fixedCardCount": 3
    },
    "cards": [
      { "cardKey": "largeCap", "label": "大盘股平均涨跌幅", "valuePct": 0.72, "sourceText": "沪深300口径", "direction": "UP" },
      { "cardKey": "smallCap", "label": "小盘股平均涨跌幅", "valuePct": 1.48, "sourceText": "中证1000口径", "direction": "UP" },
      { "cardKey": "median", "label": "涨跌中位数", "valuePct": 0.48, "sourceText": "全市场样本", "direction": "UP" }
    ],
    "historyByRange": {
      "oneMonth": [
        { "tradeDate": "2026-04-08", "largePct": -0.23, "smallPct": 0.31, "medianPct": 0.12 },
        { "tradeDate": "2026-04-09", "largePct": 0.14, "smallPct": -0.18, "medianPct": -0.02 }
      ],
      "threeMonth": [
        { "tradeDate": "2026-02-10", "largePct": -0.41, "smallPct": -0.12, "medianPct": -0.19 }
      ]
    }
  }
}
```

### 4.2 delayed 样例

```json
{
  "pageStatus": { "status": "PARTIAL", "displayText": "部分模块数据延迟" },
  "debugInfo": {
    "modules": [
      {
        "moduleKey": "style",
        "expectedTradeDate": "2026-05-08",
        "observedTradeDate": "2026-05-07",
        "lagDays": 1,
        "status": "DELAYED",
        "note": "style source lagged"
      }
    ],
    "exceptions": [
      { "module": "style", "code": "ST_SOURCE_DELAYED", "severity": "warn", "message": "source lagged" }
    ]
  }
}
```

### 4.3 empty 样例

```json
{
  "pageStatus": { "status": "EMPTY", "displayText": "暂无可用数据" },
  "style": {
    "definition": {
      "definitionKey": "CN_A_MARKET_STYLE_V1",
      "version": "1.0.0",
      "fixedCardCount": 3
    },
    "cards": [
      { "cardKey": "largeCap", "label": "大盘股平均涨跌幅", "valuePct": null, "sourceText": "沪深300口径", "direction": "UNKNOWN" },
      { "cardKey": "smallCap", "label": "小盘股平均涨跌幅", "valuePct": null, "sourceText": "中证1000口径", "direction": "UNKNOWN" },
      { "cardKey": "median", "label": "涨跌中位数", "valuePct": null, "sourceText": "全市场样本", "direction": "UNKNOWN" }
    ],
    "historyByRange": { "oneMonth": [], "threeMonth": [] }
  }
}
```

### 4.4 error 样例

```json
{
  "pageStatus": { "status": "ERROR", "displayText": "请求失败，请稍后重试" },
  "debugInfo": {
    "exceptions": [
      { "module": "style", "code": "ST_CONFIG_INVALID", "severity": "error", "message": "style config invalid" }
    ]
  }
}
```

---

## 5. 查询草案（可直接转实现）

1. 当前日大盘/小盘：
   - `index_daily_serving` 按 `trade_date=:d` + `ts_code in (:large,:small)` 取 `pct_chg`
2. 当前日中位数（硬口径）：
   - `select percentile_disc(0.5) within group (order by pct_chg) from equity_daily_bar where trade_date=:d and pct_chg is not null`
3. 历史序列：
   - 交易日列表（22/62）来自 `trade_calendar`
   - 两指数历史来自 `index_daily_serving`
   - 中位数历史来自 `equity_daily_bar` 按 `trade_date` 分组离散中位
4. 索引与排序说明：
   - 历史按 `tradeDate` 升序；
   - 点位唯一键 `tradeDate`。

---

## 6. 状态归并样例

| 模块状态组合 | 页面状态 | 备注 |
|---|---|---|
| `READY` | `READY` | 风格数据完整 |
| `DELAYED` | `PARTIAL` | 源数据落后 |
| `EMPTY` | `EMPTY` | 三卡均缺值且历史为空 |
| `ERROR` | `ERROR` / `PARTIAL` | 视整页其他模块归并 |

---

## 7. 异常码覆盖矩阵

> 异常码必须来自  
> `wealth/docs/system/exception-code-registry.md`

| code | 覆盖用例 | 触发条件 | 预期行为 |
|---|---|---|---|
| `ST_CONFIG_MISSING` | 配置缺失 | 未找到 `marketStyle` 配置 | 模块 ERROR |
| `ST_CONFIG_INVALID` | 配置非法 | 三卡来源结构不合法 | 模块 ERROR |
| `ST_SOURCE_DELAYED` | 数据滞后 | `observed < expected` | 模块 DELAYED |
| `ST_SOURCE_EMPTY` | 空数据 | 三卡全空且历史为空 | 模块 EMPTY |
| `ST_QUERY_FAILED` | 查询失败 | SQL/服务异常 | 模块 ERROR |

---

## 8. 性能门禁

1. P95 预算：`< 220ms`
2. 返回体预算：`< 80KB`
3. 最大并发预算：按 overview 默认并发预算
4. 超预算降级策略：先优化查询批量化与序列化，不引入复杂缓存

---

## 9. 测试门禁

1. 单元测试：
   - 三卡配置校验
   - 离散中位计算校验（非插值）
2. 集成测试：
   - 正常/延迟/空/错误四态
   - `oneMonth/threeMonth` 历史点格式与顺序
3. 冒烟测试：
   - 三卡展示语义不变
   - 三线图数据结构可渲染
4. debug 模式验证：
   - `debug=1` 返回模块级状态和异常；
   - 生产环境禁用 debug 输出。

---

## 10. 签字清单

### 10.1 后端负责人

1. [ ] 三卡来源配置校验可实现
2. [ ] 离散中位查询口径可实现
3. [ ] 状态与异常语义无歧义

### 10.2 前端负责人

1. [ ] 响应结构可消费
2. [ ] 样式交互可零改动接入
3. [ ] 空值降级显示可实现

### 10.3 架构/产品负责人

1. [ ] 范围未扩散
2. [ ] 三卡来源配置化达成
3. [ ] 可进入编码阶段

---

## 11. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-08 | 首版：建立市场风格模块编码门禁（三卡来源配置 + 离散中位） | Codex |
