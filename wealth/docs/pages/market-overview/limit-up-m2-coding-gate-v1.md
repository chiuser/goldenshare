# 市场总览｜涨跌停统计与分布 M2 编码前门禁 v1

> 用途：在编码前冻结“涨跌停统计与分布（2×2）”模块的参数、响应、查询、状态、异常与性能。  
> 阶段：M2 开工前。  
> 产物性质：执行门禁清单（不通过不允许编码）。

> 当前状态：`Draft / 待评审`（未冻结）。  
> 说明：本门禁文档尚未生效，当前仅作为评审草案；未收到最终拍板前禁止开工。

关联文档：

1. [涨跌停统计与分布标杆需求 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/limit-up-benchmark-requirement-v1.md)
2. [涨跌停统计与分布技术实施方案 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/limit-up-implementation-design-v1.md)

---

## 1. 目的

1. 本门禁对应模块：`limitUp`
2. 本门禁对应需求文档：`limit-up-benchmark-requirement-v1.md`
3. 本门禁对应实施方案：`limit-up-implementation-design-v1.md`

---

## 2. 总门禁清单（全通过才能开工）

1. [ ] 文档最终拍板（当前未完成，未完成前不得编码）
2. [ ] 请求与响应结构冻结
3. [ ] 8 卡口径冻结（含 ST 分层）
4. [ ] 封板率排除 ST 口径冻结
5. [ ] 天地板/地天板判定 + 降级冻结
6. [ ] 今日/昨日结构算法冻结
7. [ ] 历史 22/62 口径冻结
8. [ ] 状态归并样例冻结
9. [ ] 异常覆盖矩阵冻结
10. [ ] 性能预算冻结
11. [ ] 签字完成

---

## 3. 请求与响应冻结

### 3.1 请求参数冻结

```ts
interface LimitUpSummaryRequest {
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
interface LimitSummaryCardItem {
  key:
    | "limitUpCount"
    | "limitDownCount"
    | "brokenLimitCount"
    | "sealingRate"
    | "streakCount"
    | "maxBoard"
    | "skyToFloorCount"
    | "floorToSkyCount";
  label: string;
  value: string | number | null;
  unit?: string;
  direction: "UP" | "DOWN" | "FLAT" | "UNKNOWN";
  subText?: string;
}

interface LimitDistributionRow {
  categoryName: string;
  categoryCode?: string;
  count: number; // 涨停分布中语义等价于 upNums
  kind: "up" | "down" | "fail";
}

interface LimitDistributionBlock {
  tradeDate: string;
  limitUpSectorDistribution: LimitDistributionRow[];
  limitDownStructure: LimitDistributionRow[];
  brokenLimitStructure: LimitDistributionRow[];
}

interface LimitHistoryPoint {
  tradeDate: string;
  limitUpCount: number;
  limitDownCount: number;
}

interface LimitUpSummaryResponseData {
  tradingDay: TradingDay;
  pageStatus: PageStatus;
  limitUp: {
    tradeDate: string;
    summaryCards: LimitSummaryCardItem[];
    todayDistribution: LimitDistributionBlock;
    previousTradeDayDistribution: LimitDistributionBlock;
    historyPoints: {
      oneMonth: LimitHistoryPoint[];
      threeMonth: LimitHistoryPoint[];
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
    "tradeDate": "2026-04-28",
    "prevTradeDate": "2026-04-27",
    "market": "CN_A",
    "isTradingDay": true,
    "sessionStatus": "CLOSED",
    "timezone": "Asia/Shanghai"
  },
  "pageStatus": { "status": "READY", "displayText": "数据已就绪" },
  "limitUp": {
    "tradeDate": "2026-04-28",
    "summaryCards": [
      { "key": "limitUpCount", "label": "涨停家数", "value": "99/28", "direction": "UP", "subText": "总涨停家数/ST涨停家数" },
      { "key": "limitDownCount", "label": "跌停家数", "value": "14/4", "direction": "DOWN", "subText": "总跌停家数/ST跌停家数" },
      { "key": "brokenLimitCount", "label": "炸板家数", "value": "31/5", "direction": "FLAT", "subText": "总炸板家数/ST炸板家数" },
      { "key": "sealingRate", "label": "封板率", "value": 69.8, "unit": "%", "direction": "UP", "subText": "非ST口径" },
      { "key": "streakCount", "label": "连板家数", "value": 24, "unit": "只", "direction": "UP", "subText": "二板及以上" },
      { "key": "maxBoard", "label": "最高连板", "value": 7, "unit": "板", "direction": "UP", "subText": "五板及以上合并展示" },
      { "key": "skyToFloorCount", "label": "天地板", "value": 1, "unit": "只", "direction": "DOWN", "subText": "高风险结构" },
      { "key": "floorToSkyCount", "label": "地天板", "value": 2, "unit": "只", "direction": "UP", "subText": "反包结构" }
    ],
    "todayDistribution": {
      "tradeDate": "2026-04-28",
      "limitUpSectorDistribution": [
        { "categoryName": "机器人概念", "categoryCode": "885517.TI", "count": 12, "kind": "up" },
        { "categoryName": "人工智能", "categoryCode": "885728.TI", "count": 9, "kind": "up" }
      ],
      "limitDownStructure": [
        { "categoryName": "ST风险", "count": 4, "kind": "down" },
        { "categoryName": "地产链跌停", "count": 3, "kind": "down" }
      ],
      "brokenLimitStructure": [
        { "categoryName": "炸板·机器人", "count": 8, "kind": "fail" },
        { "categoryName": "炸板·锂电", "count": 6, "kind": "fail" }
      ]
    },
    "previousTradeDayDistribution": {
      "tradeDate": "2026-04-27",
      "limitUpSectorDistribution": [
        { "categoryName": "电子商务", "categoryCode": "885420.TI", "count": 10, "kind": "up" }
      ],
      "limitDownStructure": [
        { "categoryName": "ST风险", "count": 2, "kind": "down" }
      ],
      "brokenLimitStructure": [
        { "categoryName": "炸板·低空", "count": 7, "kind": "fail" }
      ]
    },
    "historyPoints": {
      "oneMonth": [
        { "tradeDate": "2026-04-08", "limitUpCount": 42, "limitDownCount": 11 },
        { "tradeDate": "2026-04-09", "limitUpCount": 51, "limitDownCount": 9 }
      ],
      "threeMonth": [
        { "tradeDate": "2026-02-10", "limitUpCount": 38, "limitDownCount": 7 }
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
        "moduleKey": "limitUp",
        "expectedTradeDate": "2026-04-28",
        "observedTradeDate": "2026-04-27",
        "lagDays": 1,
        "status": "DELAYED",
        "note": "limit list source lagged"
      }
    ],
    "exceptions": [
      { "module": "limitUp", "code": "LU_SOURCE_DELAYED", "severity": "warn", "message": "source lagged" }
    ]
  }
}
```

### 4.3 partial 样例（天地/地天降级）

```json
{
  "pageStatus": { "status": "PARTIAL", "displayText": "部分模块数据不完整" },
  "limitUp": {
    "summaryCards": [
      { "key": "skyToFloorCount", "label": "天地板", "value": null, "direction": "UNKNOWN", "subText": "数据条件不足" },
      { "key": "floorToSkyCount", "label": "地天板", "value": null, "direction": "UNKNOWN", "subText": "数据条件不足" }
    ]
  },
  "debugInfo": {
    "exceptions": [
      { "module": "limitUp", "code": "LU_PATTERN_INPUT_MISSING", "severity": "warn", "message": "time fields coverage too low" }
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
      { "module": "limitUp", "code": "LU_QUERY_FAILED", "severity": "error", "message": "query failed" }
    ]
  }
}
```

---

## 5. 查询草案（可直接转实现）

1. 当日三集合：
   - `U/D/B`：`limit_list_ths` 按 `limit_type` 分组去重 `ts_code`
2. ST 交集：
   - `equity_stock_st` 同交易日，与 `U/D/B` 交集计数
3. 连板统计：
   - `limit_step` 按 `nums::int` 统计 `>=2` 与 `max`
4. 天地/地天：
   - `limit_list_ths` 聚合时间字段后做判定
5. 分布结构：
   - 涨停板块分布：`limit_cpt_list` 直接取 Top5（`rank asc, up_nums desc`）
   - 跌停/炸板结构：`U/D/B` 与 `dc_member + dc_index` 映射后分组计数 TopN
6. 历史点：
   - 最近 22/62 交易日，逐日统计 `limitUpCount/limitDownCount`

---

## 6. 状态归并样例

| 模块状态组合 | 页面状态 | 备注 |
|---|---|---|
| `READY` | `READY` | 2×2 全块完整 |
| `DELAYED` | `PARTIAL` | 源日期落后 |
| `PARTIAL` | `PARTIAL` | 天地/地天降级或结构缺失 |
| `EMPTY` | `EMPTY` | 当日无可用样本 |
| `ERROR` | `ERROR` / `PARTIAL` | 视整页其他模块归并 |

---

## 7. 异常码覆盖矩阵

> 异常码必须来自  
> `wealth/docs/system/exception-code-registry.md`

| code | 覆盖用例 | 触发条件 | 预期行为 |
|---|---|---|---|
| `LU_SOURCE_DELAYED` | 数据滞后 | `observed < expected` | 模块 delayed |
| `LU_SOURCE_EMPTY` | 空数据 | 当日 `U/D/B` 全空 | 模块 empty |
| `LU_SEAL_RATE_DENOM_ZERO` | 封板率不可算 | `nonStLimitUp + nonStBroken = 0` | `sealingRate=null`，模块可 READY/PARTIAL |
| `LU_PATTERN_INPUT_MISSING` | 天地/地天降级 | 时间字段覆盖不足 | 两卡 `null` + 模块 partial |
| `LU_PATTERN_CONFLICT` | 天地地天冲突 | 同股同时命中两规则 | 冲突样本剔除，模块 partial |
| `LU_DISTRIBUTION_MAPPING_MISSING` | 结构映射缺失 | 板块映射不可用 | 模块 partial |
| `LU_HISTORY_INCOMPLETE` | 历史不足 | 22/62 样本不足 | 模块 partial |
| `LU_QUERY_FAILED` | 查询失败 | SQL/服务异常 | 模块 error |

---

## 8. 性能门禁

1. 模块 P95：`< 380ms`
2. 返回体预算：`< 180KB`
3. 最大并发预算：按 overview 默认并发预算
4. 超预算策略：先优化 SQL 聚合与 join 形态，不引入计划外缓存扩散

---

## 9. 测试门禁

1. 单元测试：
   - ST 分层计数
   - 封板率计算
   - 天地/地天判定与降级
2. 集成测试：
   - 今日/昨日结构 TopN 输出
   - 历史 22/62 输出
   - delayed/partial/empty/error 五态
3. 冒烟测试：
   - 8 卡完整渲染
   - `总数/ST数` 格式渲染
   - 涨停板块分布按家数展示，柱长由前端按榜内最大家数归一化（今日/昨日独立）
4. debug 验证：
   - `debug=1` 输出模块状态与异常
   - 生产环境不输出 debug 字段

---

## 10. 签字清单

### 10.1 后端负责人

1. [ ] ST 口径与封板率口径可实现
2. [ ] 天地/地天判定与降级规则可实现
3. [ ] 今日/昨日结构同算法可实现

### 10.2 前端负责人

1. [ ] 2×2 结构字段可直接消费
2. [ ] 8 卡 UI 可无歧义映射
3. [ ] `null + reason` 降级可展示

### 10.3 架构/产品负责人

1. [ ] 范围未扩散
2. [ ] 口径与页面事实一致
3. [ ] 可进入编码阶段

---

## 11. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-09 | 首版：冻结涨跌停统计与分布模块 M2 编码门禁 | Codex |
