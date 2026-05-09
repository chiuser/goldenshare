# 市场总览｜成交额总览 M2 编码前门禁 v1

> 用途：在编码前冻结“成交额总览”模块的参数、响应、查询、状态、异常与性能。  
> 阶段：M2 开工前。  
> 产物性质：执行门禁清单（不通过不允许编码）。

关联文档：

1. [成交额总览标杆需求 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/turnover-benchmark-requirement-v1.md)
2. [成交额总览技术实施方案 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/turnover-implementation-design-v1.md)

---

## 1. 目的

1. 本门禁对应模块：`turnover`
2. 本门禁对应需求文档：`turnover-benchmark-requirement-v1.md`
3. 本门禁对应实施方案：`turnover-implementation-design-v1.md`

---

## 2. 总门禁清单（全通过才能开工）

1. [ ] 四卡统计口径冻结
2. [ ] 历史范围口径冻结（22/62）
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
interface TurnoverRequest {
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
interface TurnoverResponseData {
  tradingDay: TradingDay;
  pageStatus: PageStatus;
  turnover: {
    tradeDate: string;
    metrics: {
      todayAmount: number | null;
      prevAmount: number | null;
      amountDelta: number | null;
      amountDeltaPct: number | null;
      avg5dAmount: number | null;
      avg20dAmount: number | null;
      unit: "yuan";
    };
    intradayCumulative: TurnoverIntradayPoint[];
    historyByRange: {
      oneMonth: TurnoverHistoryPoint[];
      threeMonth: TurnoverHistoryPoint[];
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
  "turnover": {
    "tradeDate": "2026-05-08",
    "metrics": {
      "todayAmount": 1052300000000,
      "prevAmount": 982100000000,
      "amountDelta": 70200000000,
      "amountDeltaPct": 7.15,
      "avg5dAmount": 1018000000000,
      "avg20dAmount": 936000000000,
      "unit": "yuan"
    },
    "intradayCumulative": [
      { "time": "09:30", "cumAmount": 0 },
      { "time": "10:30", "cumAmount": 236000000000 },
      { "time": "11:30", "cumAmount": 482000000000 },
      { "time": "14:00", "cumAmount": 812000000000 },
      { "time": "15:00", "cumAmount": 1052300000000 }
    ],
    "historyByRange": {
      "oneMonth": [
        { "tradeDate": "2026-04-08", "amount": 921000000000 },
        { "tradeDate": "2026-04-09", "amount": 938000000000 }
      ],
      "threeMonth": [
        { "tradeDate": "2026-02-10", "amount": 865000000000 }
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
        "moduleKey": "turnover",
        "expectedTradeDate": "2026-05-08",
        "observedTradeDate": "2026-05-07",
        "lagDays": 1,
        "status": "DELAYED",
        "note": "turnover source lagged"
      }
    ],
    "exceptions": [
      { "module": "turnover", "code": "TO_SOURCE_DELAYED", "severity": "warn", "message": "source lagged" }
    ]
  }
}
```

### 4.3 empty 样例

```json
{
  "pageStatus": { "status": "EMPTY", "displayText": "暂无可用数据" },
  "turnover": {
    "tradeDate": "2026-05-08",
    "metrics": {
      "todayAmount": null,
      "prevAmount": null,
      "amountDelta": null,
      "amountDeltaPct": null,
      "avg5dAmount": null,
      "avg20dAmount": null,
      "unit": "yuan"
    },
    "intradayCumulative": [],
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
      { "module": "turnover", "code": "TO_QUERY_FAILED", "severity": "error", "message": "query failed" }
    ]
  }
}
```

---

## 5. 查询草案（可直接转实现）

1. 当日/前日总额：
   - `select trade_date, sum(amount) from core_serving.equity_daily_bar where trade_date in (:d,:prev_d) group by trade_date`
2. 5日/20日窗口：
   - 先取交易日序列，再按 `trade_date` 聚合 `sum(amount)` 后做窗口统计
   - 20日指标固定取均值
3. 历史趋势：
   - 22/62 交易日，逐日 `sum(amount)` 输出
4. 日内累计曲线（固定启用）：
   - `raw_tushare.stk_mins` 按 `freq=30`、`trade_time` 聚合 `sum(amount)` 并累加
   - 固定输出 5 个时间点：`09:30/10:30/11:30/14:00/15:00`
5. 索引与排序说明：
   - 历史按 `tradeDate` 升序；
   - 日内按 `time` 升序。

---

## 6. 状态归并样例

| 模块状态组合 | 页面状态 | 备注 |
|---|---|---|
| `READY` | `READY` | 四卡与曲线完整 |
| `DELAYED` | `PARTIAL` | 主源交易日落后 |
| `PARTIAL` | `PARTIAL` | 四卡可用但日内曲线缺失 |
| `EMPTY` | `EMPTY` | 全部为空 |
| `ERROR` | `ERROR` / `PARTIAL` | 视整页其他模块归并 |

---

## 7. 异常码覆盖矩阵

> 异常码必须来自  
> `wealth/docs/system/exception-code-registry.md`

| code | 覆盖用例 | 触发条件 | 预期行为 |
|---|---|---|---|
| `TO_SOURCE_DELAYED` | 数据滞后 | `observed < expected` | 模块 DELAYED |
| `TO_SOURCE_EMPTY` | 空数据 | 四卡与历史均为空 | 模块 EMPTY |
| `TO_INTRADAY_MISSING` | 日内缺失 | `stk_mins` 当日无可用点 | 模块 PARTIAL |
| `TO_QUERY_FAILED` | 查询失败 | SQL/服务异常 | 模块 ERROR |

---

## 8. 性能门禁

1. P95 预算：`< 280ms`
2. 返回体预算：`< 120KB`
3. 最大并发预算：按 overview 默认并发预算
4. 超预算降级策略：先优化聚合查询与窗口计算，不引入复杂缓存

---

## 9. 测试门禁

1. 单元测试：
   - delta/deltaPct 计算
   - 5日/20日窗口统计
2. 集成测试：
   - 正常/延迟/partial/空/错误五态
   - 历史点位与时间排序
3. 冒烟测试：
   - 四卡 + 两图数据结构可渲染
4. debug 模式验证：
   - `debug=1` 返回模块级状态和异常；
   - 生产环境禁用 debug 输出。

---

## 10. 签字清单

### 10.1 后端负责人

1. [ ] 四卡统计口径可实现
2. [ ] 日内累计策略可实现
3. [ ] 状态与异常语义无歧义

### 10.2 前端负责人

1. [ ] 响应结构可消费
2. [ ] 样式交互可零改动接入
3. [ ] 空值/partial 展示可实现

### 10.3 架构/产品负责人

1. [ ] 范围未扩散
2. [ ] 四卡与两图语义达成
3. [ ] 可进入编码阶段

---

## 11. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-08 | 首版：建立成交额总览模块编码门禁（4卡 + 两图） | Codex |
| v1.1 | 2026-05-08 | 拍板落定：20日均值 + 30min 5点日内累计曲线 | Codex |
