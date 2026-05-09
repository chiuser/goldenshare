# 市场总览｜主要指数 M2 编码前门禁 v1

> 用途：在编码前冻结主要指数模块的参数、响应、配置、查询、状态与异常。  
> 阶段：M2 开工前。  
> 产物性质：执行门禁清单（不通过不允许编码）。

关联文档：

1. [主要指数标杆需求 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/major-indices-benchmark-requirement-v1.md)
2. [主要指数技术实施方案 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/major-indices-implementation-design-v1.md)

---

## 1. 目的

1. 本门禁对应模块：`majorIndices`
2. 本门禁对应需求文档：`major-indices-benchmark-requirement-v1.md`
3. 本门禁对应实施方案：`major-indices-implementation-design-v1.md`

---

## 2. 总门禁清单（全通过才能开工）

1. [ ] 指数数量固定 10 的规则冻结
2. [ ] 指数名单后端配置结构冻结
3. [ ] 请求与响应结构冻结
4. [ ] 核心样例响应冻结
5. [ ] 查询草案冻结
6. [ ] 状态归并样例冻结
7. [ ] 异常覆盖矩阵冻结
8. [ ] 性能预算冻结
9. [ ] 前端真实源加载态门禁冻结（loading/ready/error）
10. [ ] 5 秒超时进入 error 且不展示 mock 回填的行为门禁冻结
11. [ ] 本轮仅 majorIndices 切换到 real、其余模块 source 不变
12. [ ] 签字完成

---

## 3. 请求与响应冻结

### 3.1 请求参数冻结

```ts
interface MajorIndicesRequest {
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
interface MajorIndicesResponseData {
  tradingDay: TradingDay;
  pageStatus: PageStatus;
  majorIndices: {
    definition: {
      definitionKey: string;
      version: string;
      fixedCount: 10;
    };
    rows: MajorIndexRow[]; // length always 10
  };
  debugInfo?: {
    modules: ModuleStatusItem[];
    exceptions: ModuleExceptionItem[];
  };
}
```

---

## 4. 核心样例响应（最小集合）

### 4.1 正常样例（10 条）

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
    "displayText": "数据已就绪"
  },
  "majorIndices": {
    "definition": {
      "definitionKey": "CN_A_MAJOR_INDICES_V1",
      "version": "1.0.0",
      "fixedCount": 10
    },
    "rows": [
      { "subject": { "subjectType": "index", "subjectCode": "000001.SH", "subjectName": "上证指数" }, "point": 3128.42, "change": 28.66, "changePct": 0.92, "amount": 0, "direction": "UP" },
      { "subject": { "subjectType": "index", "subjectCode": "399001.SZ", "subjectName": "深证成指" }, "point": 9842.15, "change": -34.21, "changePct": -0.35, "amount": 0, "direction": "DOWN" },
      { "subject": { "subjectType": "index", "subjectCode": "399006.SZ", "subjectName": "创业板指" }, "point": 1986.22, "change": 22.03, "changePct": 1.12, "amount": 0, "direction": "UP" },
      { "subject": { "subjectType": "index", "subjectCode": "000688.SH", "subjectName": "科创50" }, "point": 921.56, "change": -1.66, "changePct": -0.18, "amount": 0, "direction": "DOWN" },
      { "subject": { "subjectType": "index", "subjectCode": "000300.SH", "subjectName": "沪深300" }, "point": 3726.84, "change": 26.58, "changePct": 0.72, "amount": 0, "direction": "UP" },
      { "subject": { "subjectType": "index", "subjectCode": "000905.SH", "subjectName": "中证500" }, "point": 5642.33, "change": 58.65, "changePct": 1.05, "amount": 0, "direction": "UP" },
      { "subject": { "subjectType": "index", "subjectCode": "000852.SH", "subjectName": "中证1000" }, "point": 5948.17, "change": 86.70, "changePct": 1.48, "amount": 0, "direction": "UP" },
      { "subject": { "subjectType": "index", "subjectCode": "899050.BJ", "subjectName": "北证50" }, "point": 1196.35, "change": 24.15, "changePct": 2.06, "amount": 0, "direction": "UP" },
      { "subject": { "subjectType": "index", "subjectCode": "000510.SH", "subjectName": "中证A500" }, "point": 4683.91, "change": 38.56, "changePct": 0.83, "amount": 0, "direction": "UP" },
      { "subject": { "subjectType": "index", "subjectCode": "000016.SH", "subjectName": "上证50" }, "point": 2542.08, "change": 10.66, "changePct": 0.42, "amount": 0, "direction": "UP" }
    ]
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
        "moduleKey": "majorIndices",
        "expectedTradeDate": "2026-05-08",
        "observedTradeDate": "2026-05-07",
        "lagDays": 1,
        "status": "DELAYED",
        "note": "index_daily_serving lagged"
      }
    ],
    "exceptions": [
      { "module": "majorIndices", "code": "MI_SOURCE_DELAYED", "severity": "warn", "message": "source lagged" }
    ]
  }
}
```

### 4.3 empty 样例

```json
{
  "pageStatus": { "status": "EMPTY", "displayText": "暂无可用数据" },
  "majorIndices": {
    "definition": { "definitionKey": "CN_A_MAJOR_INDICES_V1", "version": "1.0.0", "fixedCount": 10 },
    "rows": [
      { "subject": { "subjectType": "index", "subjectCode": "000001.SH", "subjectName": null }, "point": null, "change": null, "changePct": null, "amount": null, "direction": "UNKNOWN" },
      { "subject": { "subjectType": "index", "subjectCode": "399001.SZ", "subjectName": null }, "point": null, "change": null, "changePct": null, "amount": null, "direction": "UNKNOWN" },
      { "subject": { "subjectType": "index", "subjectCode": "399006.SZ", "subjectName": null }, "point": null, "change": null, "changePct": null, "amount": null, "direction": "UNKNOWN" },
      { "subject": { "subjectType": "index", "subjectCode": "000688.SH", "subjectName": null }, "point": null, "change": null, "changePct": null, "amount": null, "direction": "UNKNOWN" },
      { "subject": { "subjectType": "index", "subjectCode": "000300.SH", "subjectName": null }, "point": null, "change": null, "changePct": null, "amount": null, "direction": "UNKNOWN" },
      { "subject": { "subjectType": "index", "subjectCode": "000905.SH", "subjectName": null }, "point": null, "change": null, "changePct": null, "amount": null, "direction": "UNKNOWN" },
      { "subject": { "subjectType": "index", "subjectCode": "000852.SH", "subjectName": null }, "point": null, "change": null, "changePct": null, "amount": null, "direction": "UNKNOWN" },
      { "subject": { "subjectType": "index", "subjectCode": "899050.BJ", "subjectName": null }, "point": null, "change": null, "changePct": null, "amount": null, "direction": "UNKNOWN" },
      { "subject": { "subjectType": "index", "subjectCode": "000510.SH", "subjectName": null }, "point": null, "change": null, "changePct": null, "amount": null, "direction": "UNKNOWN" },
      { "subject": { "subjectType": "index", "subjectCode": "000016.SH", "subjectName": null }, "point": null, "change": null, "changePct": null, "amount": null, "direction": "UNKNOWN" }
    ]
  }
}
```

### 4.4 error 样例

```json
{
  "pageStatus": { "status": "ERROR", "displayText": "请求失败，请稍后重试" },
  "debugInfo": {
    "exceptions": [
      { "module": "majorIndices", "code": "MI_QUERY_FAILED", "severity": "error", "message": "query failed" }
    ]
  }
}
```

---

## 5. 查询草案（可直接转实现）

1. 主查询 SQL 草案：
   - `index_daily_serving` 按 `trade_date` + `ts_code in (:index_codes)` 查询。
2. 补列查询草案：
   - `index_basic` 按 `ts_code` 左连接 `name`。
3. 回退查询草案：
   - 不做跨日回退补值；只做 delayed 标记。
4. 索引与排序说明：
   - 结果按配置名单顺序重排（不是按涨跌幅排序）。

---

## 6. 状态归并样例

| 模块状态组合 | 页面状态 | 备注 |
|---|---|---|
| `READY` | `READY` | 模块数据完整 |
| `DELAYED` | `PARTIAL` | 源数据落后 |
| `EMPTY` | `EMPTY` | 无可用行 |
| `ERROR` | `ERROR` / `PARTIAL` | 视整页其他模块归并 |

---

## 7. 异常码覆盖矩阵

> 异常码必须来自  
> `wealth/docs/system/exception-code-registry.md`

| code | 覆盖用例 | 触发条件 | 预期行为 |
|---|---|---|---|
| `MI_CONFIG_MISSING` | 配置缺失 | definition 未找到 | 模块 ERROR |
| `MI_CONFIG_INVALID` | 配置非法 | code 数量 != 10 / 重复 | 模块 ERROR |
| `MI_SOURCE_DELAYED` | 数据滞后 | observed < expected | 模块 DELAYED |
| `MI_SOURCE_EMPTY` | 空数据 | 10 指数全无行 | 模块 EMPTY |
| `MI_QUERY_FAILED` | 查询失败 | SQL/服务异常 | 模块 ERROR |

---

## 8. 性能门禁

1. P95 预算：`< 150ms`
2. 返回体预算：`< 30KB`
3. 最大并发预算：按 overview 默认并发预算
4. 超预算降级策略：先优化查询和序列化，暂不引入复杂缓存

---

## 9. 测试门禁

1. 单元测试：
   - 配置校验（固定 10）
   - 顺序重排
   - 方向字段映射
2. 集成测试：
   - 正常/延迟/空/错误四态
3. 冒烟测试：
   - 前端 2x5 卡片布局无变化
   - 真实源 pending 时显示 loading（不展示 mock 指数数据）
   - 超过 5 秒显示 error
4. debug 模式验证：
   - debug=1 返回明细；
   - 生产环境禁用 debug 输出。
5. 渐进替换约束验证：
   - 仅 `majorIndices` source 发生变化；
   - 非目标模块 source 与行为不变。

---

## 10. 签字清单

### 10.1 后端负责人

1. [ ] 配置结构与校验规则可实现
2. [ ] 查询草案可实现
3. [ ] 状态与异常语义无歧义

### 10.2 前端负责人

1. [ ] 响应结构可消费
2. [ ] 2x5 布局零改动可落地
3. [ ] 缺值降级策略可展示

### 10.3 架构/产品负责人

1. [ ] 范围未扩散
2. [ ] 数量固定 10 与名单可配并存
3. [ ] 可进入编码阶段

---

## 11. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-08 | 首版：建立主要指数模块编码门禁 | Codex |
