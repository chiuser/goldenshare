# 市场总览｜涨跌分布 M2 编码前门禁 v1

> 用途：在编码前冻结涨跌分布模块的参数、响应、查询、状态、异常与性能门禁。  
> 阶段：M2 开工前。  
> 产物性质：执行门禁清单（不通过不允许编码）。

关联文档：

1. [涨跌分布标杆需求 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/breadth-benchmark-requirement-v1.md)
2. [涨跌分布技术实施方案 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/breadth-implementation-design-v1.md)

---

## 1. 目的

1. 本门禁对应模块：`breadth`
2. 本门禁对应需求文档：`breadth-benchmark-requirement-v1.md`
3. 本门禁对应实施方案：`breadth-implementation-design-v1.md`

---

## 2. 总门禁清单（全通过才能开工）

1. [ ] 无配置化能力冻结
2. [ ] 请求与响应结构冻结
3. [ ] 核心样例响应冻结
4. [ ] 查询草案冻结
5. [ ] 状态归并样例冻结
6. [ ] 异常覆盖矩阵冻结
7. [ ] 性能预算冻结
8. [ ] 签字完成

---

## 3. 请求与响应冻结

### 3.1 请求参数冻结

```ts
interface BreadthRequest {
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
interface BreadthResponseData {
  tradingDay: TradingDay;
  pageStatus: PageStatus;
  breadth: {
    tradeDate: string;
    metrics: {
      upCount: number;
      downCount: number;
      flatCount: number;
      redRate: number;
    };
    historyByRange: {
      "1m": BreadthHistoryPoint[]; // 22 points
      "3m": BreadthHistoryPoint[]; // 62 points
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
  "breadth": {
    "tradeDate": "2026-05-08",
    "metrics": {
      "upCount": 3421,
      "downCount": 1488,
      "flatCount": 219,
      "redRate": 66.71
    },
    "historyByRange": {
      "1m": [
        { "tradeDate": "2026-04-10", "upCount": 2892, "downCount": 1983 },
        { "tradeDate": "2026-05-08", "upCount": 3421, "downCount": 1488 }
      ],
      "3m": [
        { "tradeDate": "2026-02-10", "upCount": 2410, "downCount": 2317 },
        { "tradeDate": "2026-05-08", "upCount": 3421, "downCount": 1488 }
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
        "moduleKey": "breadth",
        "expectedTradeDate": "2026-05-08",
        "observedTradeDate": "2026-05-07",
        "lagDays": 1,
        "status": "DELAYED",
        "note": "equity_daily_bar lagged"
      }
    ],
    "exceptions": [
      { "module": "breadth", "code": "BR_SOURCE_DELAYED", "severity": "warn", "message": "source lagged" }
    ]
  }
}
```

### 4.3 empty 样例

```json
{
  "pageStatus": { "status": "EMPTY", "displayText": "暂无可用数据" },
  "breadth": {
    "tradeDate": "2026-05-08",
    "metrics": { "upCount": 0, "downCount": 0, "flatCount": 0, "redRate": 0 },
    "historyByRange": { "1m": [], "3m": [] }
  }
}
```

### 4.4 error 样例

```json
{
  "pageStatus": { "status": "ERROR", "displayText": "请求失败，请稍后重试" },
  "debugInfo": {
    "exceptions": [
      { "module": "breadth", "code": "BR_QUERY_FAILED", "severity": "error", "message": "query failed" }
    ]
  }
}
```

---

## 5. 查询草案（可直接转实现）

1. 当日指标查询草案：
   - `equity_daily_bar` + `trade_date = :target_date`
   - 样本口径：全量样本，不加 ST/停牌特例过滤；
   - 计数样本：仅 `pct_chg is not null`；
   - `sum(case when pct_chg>0 then 1 else 0 end) as up_count`
   - `sum(case when pct_chg<0 then 1 else 0 end) as down_count`
   - `sum(case when pct_chg=0 then 1 else 0 end) as flat_count`
2. 历史趋势查询草案：
   - 先取最近 62 个交易日（`trade_calendar.is_open=true`）；
   - 再按 `trade_date` 聚合 `up/down` 家数；
   - 结果按 `trade_date asc`。
3. 回退查询草案：
   - 不做跨日补值。
4. 索引与排序说明：
   - 按 `trade_date` 升序；
   - `1m`=22 点、`3m`=62 点固定切片。

---

## 6. 状态归并样例

| 模块状态组合 | 页面状态 | 备注 |
|---|---|---|
| `READY` | `READY` | 指标与历史完整 |
| `DELAYED` | `PARTIAL` | 数据日期落后 |
| `EMPTY` | `EMPTY` | 指标与历史均为空 |
| `ERROR` | `ERROR` / `PARTIAL` | 视整页其他模块归并 |

---

## 7. 异常码覆盖矩阵

> 异常码必须来自  
> `wealth/docs/system/exception-code-registry.md`

| code | 覆盖用例 | 触发条件 | 预期行为 |
|---|---|---|---|
| `BR_SOURCE_EMPTY` | 空数据 | 目标日无样本 | 模块 EMPTY |
| `BR_SOURCE_DELAYED` | 数据滞后 | observed < expected | 模块 DELAYED |
| `BR_HISTORY_INCOMPLETE` | 历史不足 | 历史点少于 22/62 | 模块 PARTIAL（debug 提示） |
| `BR_QUERY_FAILED` | 查询失败 | SQL/服务异常 | 模块 ERROR |

---

## 8. 性能门禁

1. P95 预算：`< 200ms`
2. 返回体预算：`< 40KB`
3. 最大并发预算：按 overview 默认并发预算
4. 超预算降级策略：先优化聚合查询与序列化，不引入复杂缓存

---

## 9. 测试门禁

1. 单元测试：
   - 指标计数与 `redRate` 计算
   - `1m/3m` 固定点数切片
   - `pct_chg is null` 样本不计入上/下/平
2. 集成测试：
   - 正常/延迟/空/错误四态
3. 冒烟测试：
   - 前端 `RangeSwitch` 可切 `1个月/3个月`
   - 双趋势线（上涨/下跌）可渲染
4. debug 模式验证：
   - `debug=1` 返回明细；
   - 生产环境禁用 debug 输出。

---

## 10. 签字清单

### 10.1 后端负责人

1. [ ] 查询草案可实现
2. [ ] 状态归并无歧义
3. [ ] 异常覆盖完整

### 10.2 前端负责人

1. [ ] 响应结构可消费
2. [ ] 现有面板无需改样式可接入
3. [ ] 空态/延迟态可表达

### 10.3 架构/产品负责人

1. [ ] 范围未扩散
2. [ ] 语义与当前页面一致
3. [ ] 可进入编码阶段

---

## 11. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-08 | 首版：冻结涨跌分布模块编码门禁 | Codex |
