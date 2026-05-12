# 市场总览｜连板天梯 M2 编码前门禁 v1

> 用途：在编码前冻结“连板天梯”模块的参数、响应、查询、状态、异常、性能与测试。
> 阶段：M2 开工前。
> 产物性质：执行门禁清单（不通过不允许编码）。

关联文档：

1. [连板天梯标杆需求 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/streak-ladder-benchmark-requirement-v1.md)
2. [连板天梯技术实施方案 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/streak-ladder-implementation-design-v1.md)

---

## 1. 目的

1. 本门禁对应模块：`streakLadder`
2. 本门禁对应需求文档：`streak-ladder-benchmark-requirement-v1.md`
3. 本门禁对应实施方案：`streak-ladder-implementation-design-v1.md`

---

## 2. 总门禁清单（全通过才能开工）

1. [ ] 请求与响应结构冻结
2. [ ] 五梯队分桶规则冻结
3. [ ] 源数据 ST 口径冻结
4. [ ] `limit_times -> boardCount` 解析规则冻结
5. [ ] 梯队内排序规则冻结
6. [ ] 补列字段可空策略冻结
7. [ ] 核心样例响应冻结
8. [ ] 查询草案冻结
9. [ ] 状态归并样例冻结
10. [ ] 异常码已登记并冻结
11. [ ] 性能预算冻结
12. [ ] 前端 provider/view-model adapter 方案冻结
13. [ ] 模块 source 切换范围冻结
14. [ ] 核心测试 case（真实 API + 前端展示）门禁冻结
15. [ ] 通用清单映射矩阵冻结
16. [ ] 跨模块抽象门禁原则（8 条）映射完成
17. [ ] 签字完成

---

## 3. 请求与响应冻结

### 3.1 请求参数冻结

```ts
interface StreakLadderRequest {
  market?: "CN_A";    // default: CN_A
  tradeDate?: string; // YYYY-MM-DD；可选观测交易日
  debug?: 0 | 1;      // default: 0
}
```

参数校验规则：

1. `market` 非 `CN_A` -> `400001`
2. `tradeDate` 非合法 `YYYY-MM-DD` 日期格式 -> `400001`
3. `debug` 非 `0/1` -> `400001`
4. 未传 `tradeDate` 时，由后端按交易日历和盘后口径推导期望交易日。

### 3.2 响应结构冻结

```ts
interface StreakLadderResponseData {
  tradingDay: TradingDay;
  pageStatus: PageStatus;
  streakLadder: {
    tradeDate: string;
    buckets: StreakBucket[];
  };
  debugInfo?: {
    modules: ModuleStatusItem[];
    exceptions: ModuleExceptionItem[];
  };
}

interface StreakBucket {
  bucketKey: "first" | "second" | "third" | "fourth" | "fifthPlus";
  bucketLabel: "首板" | "二板" | "三板" | "四板" | "五板及以上";
  minBoardCount: number;
  maxBoardCount: number | null;
  stockCount: number;
  stocks: StreakStockRow[];
}

interface StreakStockRow {
  rank: number;
  subject: {
    subjectType: "stock";
    subjectCode: string;
    subjectName: string | null;
  };
  boardCount: number;
  sectorName: string | null;
  latestPrice: number | null;
  changePct: number | null;
  direction: "UP" | "DOWN" | "FLAT" | "UNKNOWN";
  openTimes: number | null;
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
  "streakLadder": {
    "tradeDate": "2026-05-08",
    "buckets": [
      {
        "bucketKey": "first",
        "bucketLabel": "首板",
        "minBoardCount": 1,
        "maxBoardCount": 1,
        "stockCount": 1,
        "stocks": [
          {
            "rank": 1,
            "subject": {
              "subjectType": "stock",
              "subjectCode": "002537.SZ",
              "subjectName": "海联金汇"
            },
            "boardCount": 1,
            "sectorName": "金融科技",
            "latestPrice": 7.88,
            "changePct": 10.06,
            "direction": "UP",
            "openTimes": 0
          }
        ]
      },
      {
        "bucketKey": "second",
        "bucketLabel": "二板",
        "minBoardCount": 2,
        "maxBoardCount": 2,
        "stockCount": 0,
        "stocks": []
      },
      {
        "bucketKey": "third",
        "bucketLabel": "三板",
        "minBoardCount": 3,
        "maxBoardCount": 3,
        "stockCount": 0,
        "stocks": []
      },
      {
        "bucketKey": "fourth",
        "bucketLabel": "四板",
        "minBoardCount": 4,
        "maxBoardCount": 4,
        "stockCount": 0,
        "stocks": []
      },
      {
        "bucketKey": "fifthPlus",
        "bucketLabel": "五板及以上",
        "minBoardCount": 5,
        "maxBoardCount": null,
        "stockCount": 1,
        "stocks": [
          {
            "rank": 1,
            "subject": {
              "subjectType": "stock",
              "subjectCode": "300998.SZ",
              "subjectName": "星辰科技"
            },
            "boardCount": 6,
            "sectorName": "机器人",
            "latestPrice": 28.6,
            "changePct": 20.0,
            "direction": "UP",
            "openTimes": 1
          }
        ]
      }
    ]
  }
}
```

### 4.2 delayed 样例

```json
{
  "pageStatus": { "status": "PARTIAL", "displayText": "部分模块数据延迟" },
  "streakLadder": {
    "tradeDate": "2026-05-07",
    "buckets": [
      { "bucketKey": "first", "bucketLabel": "首板", "minBoardCount": 1, "maxBoardCount": 1, "stockCount": 0, "stocks": [] },
      { "bucketKey": "second", "bucketLabel": "二板", "minBoardCount": 2, "maxBoardCount": 2, "stockCount": 0, "stocks": [] },
      { "bucketKey": "third", "bucketLabel": "三板", "minBoardCount": 3, "maxBoardCount": 3, "stockCount": 0, "stocks": [] },
      { "bucketKey": "fourth", "bucketLabel": "四板", "minBoardCount": 4, "maxBoardCount": 4, "stockCount": 0, "stocks": [] },
      { "bucketKey": "fifthPlus", "bucketLabel": "五板及以上", "minBoardCount": 5, "maxBoardCount": null, "stockCount": 0, "stocks": [] }
    ]
  },
  "debugInfo": {
    "modules": [
      {
        "moduleKey": "streakLadder",
        "expectedTradeDate": "2026-05-08",
        "observedTradeDate": "2026-05-07",
        "lagDays": 1,
        "status": "DELAYED",
        "note": "equity_limit_list source lagged"
      }
    ],
    "exceptions": [
      {
        "module": "streakLadder",
        "code": "SL_SOURCE_DELAYED",
        "severity": "warn",
        "message": "equity_limit_list source lagged"
      }
    ]
  }
}
```

### 4.3 empty 样例

```json
{
  "pageStatus": { "status": "EMPTY", "displayText": "暂无可用数据" },
  "streakLadder": {
    "tradeDate": "2026-05-08",
    "buckets": [
      { "bucketKey": "first", "bucketLabel": "首板", "minBoardCount": 1, "maxBoardCount": 1, "stockCount": 0, "stocks": [] },
      { "bucketKey": "second", "bucketLabel": "二板", "minBoardCount": 2, "maxBoardCount": 2, "stockCount": 0, "stocks": [] },
      { "bucketKey": "third", "bucketLabel": "三板", "minBoardCount": 3, "maxBoardCount": 3, "stockCount": 0, "stocks": [] },
      { "bucketKey": "fourth", "bucketLabel": "四板", "minBoardCount": 4, "maxBoardCount": 4, "stockCount": 0, "stocks": [] },
      { "bucketKey": "fifthPlus", "bucketLabel": "五板及以上", "minBoardCount": 5, "maxBoardCount": null, "stockCount": 0, "stocks": [] }
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
      {
        "module": "streakLadder",
        "code": "SL_QUERY_FAILED",
        "severity": "error",
        "message": "query failed"
      }
    ]
  }
}
```

---

## 5. 查询草案（可直接转实现）

### 5.1 主查询

```sql
select
  ts_code,
  name,
  trade_date,
  industry,
  close,
  pct_chg,
  open_times,
  limit_times
from core_serving.equity_limit_list
where trade_date = :trade_date
  and limit_type = 'U';
```

处理：

1. 解析 `limit_times` 为正整数。
2. 同一 `ts_code` 多行时取最大 `boardCount`。
3. `close/pct_chg/open_times/industry` 缺失不丢主行，但记录 `SL_JOIN_METRIC_MISSING`。
4. `limit_list_d` 文档明确“不提供 ST 股票统计”，本模块不额外查询 ST 集合。

### 5.2 字段映射冻结

| API 字段 | 来源字段 | 缺失策略 |
|---|---|---|
| `subject.subjectCode` | `ts_code` | 缺失丢弃 |
| `subject.subjectName` | `name` | 缺失时前端只展示代码 |
| `boardCount` | `limit_times` | 非正整数丢弃并记录异常 |
| `sectorName` | `industry` | 缺失为 `null` |
| `latestPrice` | `close` | 缺失为 `null` |
| `changePct` | `pct_chg` | 缺失为 `null` |
| `openTimes` | `open_times` | 缺失为 `null` |
| `direction` | `pct_chg` 派生 | 缺失为 `UNKNOWN` |

---

## 6. 状态归并样例

| 模块状态组合 | 页面状态 | 备注 |
|---|---|---|
| `READY` | `READY` | 五梯队正常返回 |
| `DELAYED` | `PARTIAL` | 源日期落后 |
| `PARTIAL` | `PARTIAL` | 无效 `limit_times` 或展示字段缺失 |
| `EMPTY` | `EMPTY` / `PARTIAL` | 视其它模块归并 |
| `ERROR` | `ERROR` / `PARTIAL` | 视其它模块归并 |

---

## 7. 异常码覆盖矩阵

> 异常码必须来自
> `wealth/docs/system/exception-code-registry.md`

| code | 覆盖用例 | 触发条件 | 预期行为 |
|---|---|---|---|
| `SL_SOURCE_DELAYED` | 数据滞后 | `observedTradeDate < expectedTradeDate` | debug 标记 delayed |
| `SL_SOURCE_EMPTY` | 空数据 | 目标日期无有效主行 | 模块 empty |
| `SL_INVALID_BOARD_COUNT` | 异常板数字段 | `limit_times` 无法解析为正整数 | 丢弃行，模块 partial |
| `SL_JOIN_METRIC_MISSING` | 补列缺失 | 价格、涨跌幅、开板次数或主题标签缺失 | 显示 `--`，模块 partial |
| `SL_QUERY_FAILED` | 查询失败 | SQL/服务异常 | 模块 error |

---

## 8. 性能门禁

1. P95 预算：`< 320ms`
2. 返回体大小预算：`< 260KB`
3. 最大并发预算：按市场总览默认并发预算
4. 前端请求超时阈值：`5s`
5. 超预算处理：先优化 SQL 与补列查询，不引入临时缓存或截断逻辑。

---

## 9. 测试门禁

1. 单元测试：
   - `limit_times` 解析
   - 分桶
   - 排序
   - adapter 字段映射
2. 集成测试：
   - 后端真实 API 正常、delayed、empty、partial、error
3. 冒烟测试：
   - 页面五梯队展示
   - 股票卡片字段完整
   - 点击卡片 toast
4. debug 模式验证：
   - `debug=1` 返回 `moduleKey=streakLadder`
   - debug 面板展示模块状态和异常

### 9.1 核心测试 case 门禁（必填）

1. 核心字段清单：
   - `buckets[].bucketKey`
   - `buckets[].bucketLabel`
   - `buckets[].stockCount`
   - `stocks[].subject.subjectCode`
   - `stocks[].subject.subjectName`
   - `stocks[].boardCount`
   - `stocks[].sectorName`
   - `stocks[].latestPrice`
   - `stocks[].changePct`
   - `stocks[].direction`
   - `stocks[].openTimes`
2. 后端真实 API 集成测试：
   - `tests/web/test_wealth_market_streak_ladder_api.py`
   - 禁止 mock service/query。
3. 前端真实 API 展示校验：
   - `cd wealth && npm run test -- market-overview-streak-ladder-real-api`
   - 禁止 mock adapter。
4. 执行命令：
   - `pytest -q tests/web/test_wealth_market_streak_ladder_api.py`
   - `cd wealth && npm run test -- market-overview-streak-ladder-real-api`
   - `cd wealth && npm run typecheck`
5. 通过标准：
   - 五个 bucket 均存在。
   - 至少一个真实样本股票卡片字段可展示。
   - `fifthPlus` 样本保留精确 `boardCount`。
   - 无真实 API 返回前不展示 mock。

---

## 10. 签字清单

### 10.1 后端负责人

1. [ ] 查询草案可实现
2. [ ] 异常覆盖完整
3. [ ] 状态归并无歧义
4. [ ] `equity_limit_list / limit_list_d` 源行为与真实样本已核验

### 10.2 前端负责人

1. [ ] 响应结构可消费
2. [ ] 状态表达可落 UI
3. [ ] 降级策略可实现
4. [ ] 组件不再依赖整页 `MarketOverview`

### 10.3 架构/产品负责人

1. [ ] 范围未扩散
2. [ ] 语义与业务一致
3. [ ] 可进入编码阶段

---

## 11. 跨模块抽象门禁原则映射（必填）

| 原则 | 是否适用 | 落地位置（字段/查询/配置/状态） | 测试落地 | 备注 |
|---|---|---|---|---|
| 事实源单一原则 | 是 | `equity_limit_list` 主源 + `streakLadder` DTO | 后端真实 API 字段断言 | 前端不拼板数 |
| 契约先行与冻结原则 | 是 | `StreakLadderResponseData` | 类型检查 + API 测试 | 字段名不可漂移 |
| 配置一致性原则 | 是 | 首期无配置读取 | 断言不接策略中心 | 后续扩展需单独评审 |
| 默认行为显式原则 | 是 | 默认交易日、empty、delayed | 默认路径与显式 `tradeDate` 测试 | 不静默回退 |
| 排序与筛选确定性原则 | 是 | 源数据 ST 口径、分桶、排序规则 | 排序/分桶单测 | 前端不排序 |
| 性能预算前置原则 | 是 | SQL 草案 + 预算 | API 耗时记录 | 不扫描全市场 |
| 可观测与异常标准化原则 | 是 | `SL_*` 异常码 + debug | debug 模式测试 | 异常码先登记 |
| 测试以用户可见结果为中心原则 | 是 | 五梯队 + 股票卡片字段 | 前端真实 API 展示测试 | 只测 mock 不合格 |

### 11.1 模块门禁清单（复盘增强版）

1. [ ] 先证据后设计：编码前完成 `equity_limit_list` 真实样本探针，记录样本日期、行数、`limit_times` 分布。
2. [ ] 先规则后实现：源数据 ST 口径、分桶、排序、字段缺失规则已冻结。
3. [ ] 可判定性优先：`boardCount` 仅来自 `equity_limit_list.limit_times`，不从其它表猜。
4. [ ] 状态分层明确：正式页面展示状态，debug 面板展示 `SL_*` 细节。
5. [ ] 后端定义事实：梯队与排序由后端统一治理。
6. [ ] 三件套强一致：benchmark、implementation、coding gate 无冲突。
7. [ ] 反超前设计：未引入完整天梯页、抽屉、详情页或用户侧配置。
8. [ ] 字段链路完整：UI -> API -> 数据源 -> 降级路径可追溯。

---

## 12. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-12 | 初版：冻结连板天梯 M2 编码前门禁 | Codex |
