# 市场总览｜大盘资金流向 M2 编码前门禁 v1

> 用途：在编码前冻结“大盘资金流向”模块的参数、响应、查询、状态、异常与性能。  
> 阶段：M2 开工前。  
> 产物性质：执行门禁清单（不通过不允许编码）。

关联文档：

1. [大盘资金流向标杆需求 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/money-flow-benchmark-requirement-v1.md)
2. [大盘资金流向技术实施方案 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/money-flow-implementation-design-v1.md)

---

## 1. 目的

1. 本门禁对应模块：`moneyFlow`
2. 本门禁对应需求文档：`money-flow-benchmark-requirement-v1.md`
3. 本门禁对应实施方案：`money-flow-implementation-design-v1.md`

---

## 2. 总门禁清单（全通过才能开工）

1. [ ] 双卡统计口径冻结
2. [ ] 分单结构口径冻结
3. [ ] 历史范围口径冻结（22/62）
4. [ ] 请求与响应结构冻结
5. [ ] 核心样例响应冻结
6. [ ] 查询草案冻结
7. [ ] 状态归并样例冻结
8. [ ] 异常覆盖矩阵冻结
9. [ ] 性能预算冻结
10. [ ] 签字完成

---

## 3. 请求与响应冻结

### 3.1 请求参数冻结

```ts
interface MoneyFlowRequest {
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
interface MoneyFlowResponseData {
  tradingDay: TradingDay;
  pageStatus: PageStatus;
  moneyFlow: {
    tradeDate: string;
    metrics: {
      todayNetAmount: number | null;
      prevNetAmount: number | null;
      unit: "yuan";
    };
    byOrderSize: {
      elg: { amount: number | null; rate: number | null };
      lg: { amount: number | null; rate: number | null };
      md: { amount: number | null; rate: number | null };
      sm: { amount: number | null; rate: number | null };
    };
    historyByRange: {
      oneMonth: MoneyFlowHistoryPoint[];
      threeMonth: MoneyFlowHistoryPoint[];
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
  "moneyFlow": {
    "tradeDate": "2026-05-08",
    "metrics": {
      "todayNetAmount": -5280000000,
      "prevNetAmount": 3160000000,
      "unit": "yuan"
    },
    "byOrderSize": {
      "elg": { "amount": -1200000000, "rate": -0.23 },
      "lg": { "amount": -950000000, "rate": -0.18 },
      "md": { "amount": 420000000, "rate": 0.08 },
      "sm": { "amount": 610000000, "rate": 0.12 }
    },
    "historyByRange": {
      "oneMonth": [
        { "tradeDate": "2026-04-08", "netAmount": 1830000000 },
        { "tradeDate": "2026-04-09", "netAmount": -2670000000 }
      ],
      "threeMonth": [
        { "tradeDate": "2026-02-10", "netAmount": 940000000 }
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
        "moduleKey": "moneyFlow",
        "expectedTradeDate": "2026-05-08",
        "observedTradeDate": "2026-05-07",
        "lagDays": 1,
        "status": "DELAYED",
        "note": "moneyflow source lagged"
      }
    ],
    "exceptions": [
      { "module": "moneyFlow", "code": "MF_SOURCE_DELAYED", "severity": "warn", "message": "source lagged" }
    ]
  }
}
```

### 4.3 empty 样例

```json
{
  "pageStatus": { "status": "EMPTY", "displayText": "暂无可用数据" },
  "moneyFlow": {
    "tradeDate": "2026-05-08",
    "metrics": {
      "todayNetAmount": null,
      "prevNetAmount": null,
      "unit": "yuan"
    },
    "byOrderSize": {
      "elg": { "amount": null, "rate": null },
      "lg": { "amount": null, "rate": null },
      "md": { "amount": null, "rate": null },
      "sm": { "amount": null, "rate": null }
    },
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
      { "module": "moneyFlow", "code": "MF_QUERY_FAILED", "severity": "error", "message": "query failed" }
    ]
  }
}
```

---

## 5. 查询草案（可直接转实现）

1. 今日/昨日净流入：
   - `select trade_date, net_amount from core_serving.market_moneyflow_dc where trade_date in (:d,:prev_d)`
2. 分单结构：
   - 与目标交易日同查 `buy_elg_amount/buy_elg_amount_rate/...`
3. 历史趋势：
   - 按 22/62 交易日序列查询 `net_amount`
4. 排序说明：
   - 历史点按 `tradeDate` 升序。

---

## 6. 状态归并样例

| 模块状态组合 | 页面状态 | 备注 |
|---|---|---|
| `READY` | `READY` | 双卡与历史完整 |
| `DELAYED` | `PARTIAL` | 源日期落后 |
| `PARTIAL` | `PARTIAL` | 历史样本不足或分单缺失 |
| `EMPTY` | `EMPTY` | 模块全空 |
| `ERROR` | `ERROR` / `PARTIAL` | 视整页其他模块归并 |

---

## 7. 异常码覆盖矩阵

> 异常码必须来自  
> `wealth/docs/system/exception-code-registry.md`

| code | 覆盖用例 | 触发条件 | 预期行为 |
|---|---|---|---|
| `MF_SOURCE_DELAYED` | 数据滞后 | `observed < expected` | 模块 delayed |
| `MF_SOURCE_EMPTY` | 空数据 | 双卡与历史都为空 | 模块 empty |
| `MF_HISTORY_INCOMPLETE` | 历史不足 | 历史点少于 22（1m）或 62（3m） | 模块 partial |
| `MF_QUERY_FAILED` | 查询失败 | SQL/服务异常 | 模块 error |

---

## 8. 性能门禁

1. P95 预算：`< 260ms`
2. 返回体预算：`< 90KB`
3. 最大并发预算：按 overview 默认并发预算
4. 超预算降级策略：先优化查询，不引入复杂缓存

---

## 9. 测试门禁

1. 单元测试：
   - 今日/昨日净流入映射
   - 分单结构字段映射
2. 集成测试：
   - 正常/延迟/partial/空/错误五态
   - 历史点位与时间排序
3. 冒烟测试：
   - 双卡 + 历史图数据结构可渲染
4. debug 模式验证：
   - `debug=1` 返回模块级状态和异常；
   - 生产环境禁用 debug 输出。

---

## 10. 签字清单

### 10.1 后端负责人

1. [ ] 双卡统计口径可实现
2. [ ] 分单结构字段可实现
3. [ ] 状态与异常语义无歧义

### 10.2 前端负责人

1. [ ] 响应结构可消费
2. [ ] 样式交互可零改动接入
3. [ ] 空值/partial 展示可实现

### 10.3 架构/产品负责人

1. [ ] 范围未扩散
2. [ ] 双卡与历史趋势语义达成
3. [ ] 可进入编码阶段

---

## 11. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-08 | 首版：建立大盘资金流向模块编码门禁（双卡 + 历史趋势 + 分单结构） | Codex |
