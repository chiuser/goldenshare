# 市场总览｜涨跌停统计与分布 M2 编码前门禁 v1

> 用途：在编码前冻结“涨跌停统计与分布（2×2）”模块的参数、响应、查询、状态、异常与性能。  
> 阶段：M2 开工前。  
> 产物性质：执行门禁清单（不通过不允许编码）。

> 当前状态：`Frozen / 已生效`。  
> 说明：口径拍板、三方签字与核心门禁测试均已完成；本门禁作为当前生效基线。

关联文档：

1. [涨跌停统计与分布标杆需求 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/limit-up-benchmark-requirement-v1.md)
2. [涨跌停统计与分布技术实施方案 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/limit-up-implementation-design-v1.md)

---

## 1. 目的

1. 本门禁对应模块：`limitUp`
2. 本门禁对应需求文档：`limit-up-benchmark-requirement-v1.md`
3. 本门禁对应实施方案：`limit-up-implementation-design-v1.md`
4. 本门禁只约束 `limitUp` 模块；共享来源不等于跨模块耦合。

---

## 2. 总门禁清单（全通过才能开工）

1. [x] 文档最终拍板（已完成）
2. [x] 请求与响应结构冻结
3. [x] 8 卡口径冻结（含 ST 分层）
4. [x] 封板率排除 ST 口径冻结
5. [x] 天地板/地天板文本判定规则冻结
6. [x] 今日/昨日结构算法冻结
7. [x] 历史 22/62 口径冻结
8. [x] 状态归并样例冻结
9. [x] 异常覆盖矩阵冻结
10. [x] 性能预算冻结
11. [x] 真实源 loading/ready/error 行为冻结
12. [x] 真实源超时门禁冻结（5 秒超时进入 error，不回填 mock）
13. [x] 模块 source 渐进替换门禁冻结（仅目标模块可切 real）
14. [x] 通用清单映射矩阵冻结（2.1~2.18）
15. [x] 模块例外白名单冻结（若有）
16. [x] 核心测试 case（真实 API + 前端展示）门禁冻结
17. [x] 跨模块抽象门禁原则（8 条）映射冻结
18. [x] 签字完成
19. [x] 已确认“只维护 limitUp 字段真值表，不扩展到其它模块”

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

interface LimitSectorItem {
  sectorCode: string;
  sectorName: string;
  sectorType: "CONCEPT" | "INDUSTRY" | "REGION" | "OTHER";
  limitUpCount: number;
}

interface LimitLeaderPerformanceItem {
  stockCode: string;
  stockName: string;
  latestPrice: number;
  changePct: number;
  rank: number;
  streakLabel: string;
  recentLimitText: string;
  firstLimitTime: string;
  openTimes: number;
  sealedAmountDisplayText: string;
}

interface LimitStructureBlock {
  tradeDate: string;
  selectedSectorCode: string;
  selectedStockCode: string;
  sectors: LimitSectorItem[];
  leaderStocks: Record<string, LimitLeaderPerformanceItem[]>;
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
    todayStructure: LimitStructureBlock;
    yesterdayStructure: LimitStructureBlock;
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

### 3.3 状态机与超时门禁冻结

1. 模块状态至少覆盖：`loading / ready / error`，并支持 `delayed / partial / empty` 扩展态。
2. 真实源请求 pending 时，页面必须显示 loading，不允许展示 mock 数据冒充 ready。
3. 超时阈值固定为 5 秒；超过 5 秒进入 error 态，不允许静默回退 mock。
4. 模块 source 切 real 当轮，禁止顺手切换非目标模块 source。

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
    "todayStructure": {
      "tradeDate": "2026-04-28",
      "selectedSectorCode": "BK1031",
      "selectedStockCode": "002085.SZ",
      "sectors": [
        { "sectorCode": "BK1031", "sectorName": "机器人", "sectorType": "CONCEPT", "limitUpCount": 12 },
        { "sectorCode": "BK2014", "sectorName": "固态电池", "sectorType": "CONCEPT", "limitUpCount": 9 }
      ],
      "leaderStocks": {
        "BK1031": [
          {
            "stockCode": "002085.SZ",
            "stockName": "万丰奥威",
            "latestPrice": 18.62,
            "changePct": 10.02,
            "rank": 1,
            "streakLabel": "首板",
            "recentLimitText": "1天1板",
            "firstLimitTime": "09:38:12",
            "openTimes": 0,
            "sealedAmountDisplayText": "5.8亿"
          }
        ]
      }
    },
    "yesterdayStructure": {
      "tradeDate": "2026-04-27",
      "selectedSectorCode": "BK0839",
      "selectedStockCode": "603017.SH",
      "sectors": [
        { "sectorCode": "BK0839", "sectorName": "低空经济", "sectorType": "CONCEPT", "limitUpCount": 10 }
      ],
      "leaderStocks": {
        "BK0839": [
          {
            "stockCode": "603017.SH",
            "stockName": "中衡设计",
            "latestPrice": 12.74,
            "changePct": 10.02,
            "rank": 1,
            "streakLabel": "2连板",
            "recentLimitText": "2天2板",
            "firstLimitTime": "09:41:08",
            "openTimes": 0,
            "sealedAmountDisplayText": "2.9亿"
          }
        ]
      }
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

### 4.3 partial 样例（结构映射缺失）

```json
{
  "pageStatus": { "status": "PARTIAL", "displayText": "部分模块数据不完整" },
  "limitUp": {
    "todayStructure": {
      "tradeDate": "2026-04-28",
      "selectedSectorCode": "",
      "selectedStockCode": "",
      "sectors": [],
      "leaderStocks": {}
    }
  },
  "debugInfo": {
    "exceptions": [
      { "module": "limitUp", "code": "LU_DISTRIBUTION_MAPPING_MISSING", "severity": "warn", "message": "sector/member mapping unavailable" }
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

> 口径声明：本节为 `limitUp` 模块真值表落地门禁，不包含连板天梯等其它模块规则。

1. 当日三集合：
   - `U/D/B`：`limit_list_ths` 按 `limit_type` 分组去重 `ts_code`
2. ST 交集：
   - `equity_stock_st` 同交易日，与 `U/D/B` 交集计数
3. 连板统计：
   - `limit_step` 按 `nums::int` 统计 `>=2` 与 `max`，并排除 ST 股票
4. 天地/地天：
   - `limit_list_ths.tag/status/lu_desc` 文本词典判定
   - 命中“天地天板”时同时计入天地板和地天板
   - 命中“昨日地天板 / 前一交易日地天板 / 昨日天地板 / 前一交易日天地板”时不计入当日
   - 未命中返回 `0`（不返回 `null`）
5. 分布结构：
   - 涨停板块分布：`limit_cpt_list` 先排除 ST 板块（默认 `885699.TI`），再取 Top5；不足 5 个顺延补齐
   - 板块成分映射：Top5 板块通过 `ths_member` 取成分股 `con_code`，并按请求日过滤有效成分（`(in_date is null or in_date <= tradeDate) and (out_date is null or out_date >= tradeDate)`）
   - 领涨股候选：每个板块候选池 = 非ST成分股集合 ∩ 当日 `limit_list_ths(limit_type='涨停池')`
   - 若候选不足 Top3：仅在同板块非ST成分股内 fallback 补齐，不跨板块
   - 领涨股排序（每板块独立）：`current_board_count desc` -> `recent_limit_count_n desc` -> `changePct desc` -> `stockCode asc`
   - 领涨股 TopN：每个板块输出 Top3（不是全局 Top3），默认 `N=10`（最近 10 个交易日）
   - 同一股票允许在多个板块 Top3 中重复出现
   - 结构对象：`selectedSectorCode/selectedStockCode/sectors/leaderStocks`
6. 历史点：
   - 最近 22/62 交易日，逐日统计 `limitUpCount/limitDownCount`

---

## 6. 状态归并样例

| 模块状态组合 | 页面状态 | 备注 |
|---|---|---|
| `READY` | `READY` | 2×2 全块完整 |
| `DELAYED` | `PARTIAL` | 源日期落后 |
| `PARTIAL` | `PARTIAL` | 结构缺失或历史样本不足 |
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
| `LU_DISTRIBUTION_MAPPING_MISSING` | 结构映射缺失 | `limit_cpt_list` 或 `ths_member` 映射不可用 | 模块 partial |
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
   - 天地/地天文本词典判定（含排除词、双计）
2. 集成测试：
   - 今日/昨日结构 TopN 输出（板块 + 领涨股）
   - 历史 22/62 输出
   - delayed/partial/empty/error 五态
3. 冒烟测试：
   - 8 卡完整渲染
   - `总数/ST数` 格式渲染
   - 涨停板块分布按家数展示，柱长由前端按榜内最大家数归一化（今日/昨日独立）
   - 板块 hover 联动领涨股、领涨股 hover 高亮、最多 3 只 + `more` 行渲染
   - 真实源请求 pending 时显示 loading（不展示 mock 回填）
   - 真实源请求超过 5 秒显示 error（不回填 mock）
4. debug 验证：
   - `debug=1` 输出模块状态与异常
   - 生产环境不输出 debug 字段
5. 渐进替换约束验证：
   - 本轮只允许 `limitUp` source 从 `mock -> real`
   - 非目标模块 source 与行为保持不变

---

## 9.1 核心测试 case 门禁（必填）

1. 核心字段清单（页面可见字段）：
   - `summaryCards[].value/unit/direction/subText`
   - `todayStructure.sectors[].limitUpCount`
   - `todayStructure.leaderStocks[].stockCode/stockName/streakLabel/recentLimitText/changePct`
   - `yesterdayStructure.sectors[].limitUpCount`
   - `historyPoints.oneMonth[].limitUpCount/limitDownCount`
   - `historyPoints.threeMonth[].limitUpCount/limitDownCount`
   - `pageStatus.status`、`debugInfo.exceptions[].code`
2. 后端真实 API 集成测试用例列表（禁止 mock service/query）：
   - `tests/web/test_wealth_market_limit_up_api.py::test_limit_up_summary_ready`
   - `tests/web/test_wealth_market_limit_up_api.py::test_limit_up_summary_partial_mapping_missing`
   - `tests/web/test_wealth_market_limit_up_api.py::test_limit_up_summary_delayed`
   - `tests/web/test_wealth_market_limit_up_api.py::test_limit_up_summary_rule_st_exclusion`
3. 前端真实 API 展示校验用例列表（禁止 mock adapter）：
   - `wealth/src/test/market-overview-limit-up-real-api.smoke.test.ts::renders-limit-up-panel`
   - `wealth/src/test/market-overview-limit-up-real-api.smoke.test.ts::shows-partial-and-error-state`
4. 执行命令：
   - `pytest -q tests/web/test_wealth_market_limit_up_api.py`
   - `cd wealth && npm run test -- src/test/market-overview-limit-up-real-api.smoke.test.ts`
5. 通过标准：
   - 后端：核心字段断言、口径断言、状态断言全通过
   - 前端：2×2 结构、`总数/ST数`、结构联动、错误态展示全部通过

---

## 10. 通用清单映射矩阵

| 通用清单条目 | 适用性 | 本模块落地位置 | 当前状态 |
|---|---|---|---|
| 2.1 三件套先行 | 适用 | 本文 + benchmark + implementation | 已落地 |
| 2.2 后端事实归一 | 适用 | 第 3 节契约 + 第 5 节查询草案 | 已落地 |
| 2.3 模块状态机清晰 | 适用 | 第 3.3 节状态机与超时门禁 | 已落地 |
| 2.4 显示语义绑定 | 适用 | 第 3.2 节响应字段与 4.1 样例 | 已落地 |
| 2.5 测试覆盖行为过程 | 适用 | 第 9 节测试门禁 | 已落地 |
| 2.6 文档与实现同轮同步 | 适用 | 本轮三件套同轮修订 | 已落地 |
| 2.7 模块级渐进替换纪律 | 适用 | 第 2 节总门禁 + 第 9 节第 5 条 | 已落地 |
| 2.8 契约先行与消费者对齐 | 适用 | 第 3 节请求/响应冻结 | 已落地 |
| 2.9 图表坐标与说明文案约束 | 适用 | 第 5 节历史组合柱查询口径 + 第 9 节冒烟 | 已落地 |
| 2.10 统计计算与传输边界 | 适用 | 第 5 节查询草案 + 第 8 节性能预算 | 已落地 |
| 2.11 配置生效语义 | 适用 | 第 5 节查询草案（ST板块排除码/N窗口）+ 第 11 节配置一致性原则 | 已落地 |
| 2.12 通用清单映射矩阵 | 适用 | 本节 | 已落地 |
| 2.13 模块例外白名单与语义断言 | 适用 | 第 12 节 | 已落地 |
| 2.14 图表参数优先级 | 适用 | 第 9 节测试门禁（坐标参数语义断言） | 已落地 |
| 2.15 双图并排坐标对齐 | 适用 | 第 9 节测试门禁（今日/昨日结构 + 历史图） | 已落地 |
| 2.16 指标卡片文案单行约束 | 不适用 | 本模块卡片仅事实字段，不包含单行文案强约束需求 | 已登记例外 |
| 2.17 核心测试 case（真实 API + 前端展示）覆盖 | 适用 | 第 9.1 节 | 已落地 |
| 2.18 跨模块抽象门禁原则 | 适用 | 第 11 节 | 已落地 |

---

## 11. 跨模块抽象门禁原则映射（必填）

| 原则 | 是否适用 | 落地位置（字段/查询/配置/状态） | 测试落地 | 备注 |
|---|---|---|---|---|
| 事实源单一原则 | 是 | 第 3.2 节响应结构、第 5 节查询草案 | `test_limit_up_summary_ready` | 前端不拼装事实 |
| 契约先行与冻结原则 | 是 | 第 3 节请求/响应冻结 | `test_limit_up_contract_fields` | 契约变更需同轮更新文档+测试 |
| 配置一致性原则 | 是 | 第 5 节（ST板块排除码、N窗口） | `test_limit_up_config_binding` | 本期仍以固定键读取 |
| 默认行为显式原则 | 是 | 第 5 节、第 6 节状态归并 | `test_limit_up_summary_partial_mapping_missing` | 未命中返回0、映射缺失进PARTIAL |
| 排序与筛选确定性原则 | 是 | 第 5 节分布结构排序链 | `test_limit_up_leader_sort_stability` | 固定主次序 |
| 性能预算前置原则 | 是 | 第 8 节性能门禁 | `test_limit_up_api_latency_budget` | 超预算即不通过 |
| 可观测与异常标准化原则 | 是 | 第 7 节异常矩阵 + debugInfo | `test_limit_up_exception_codes` | 异常码必须注册 |
| 测试以用户可见结果为中心原则 | 是 | 第 9 节、第 9.1 节 | `market-overview-limit-up-real-api.smoke.test.ts` | 校验页面真实展示 |

---

### 11.1 参考 case（可复用示例）

1. 市场筛选值或板块筛选值不一致时，接口可能“成功但结构全空”，必须触发 `LU_DISTRIBUTION_MAPPING_MISSING`。
2. 同分排序未固定会导致 Top3 漂移，必须有主次排序断言。
3. 契约字段存在但页面空值，必须通过真实 API 展示用例阻断。
4. strict/fallback 默认行为必须有明确断言，禁止运行时再决定。

---

## 12. 模块例外白名单（limitUp）

| 例外规则 | 生效范围 | 业务语义依据 | 处理方式 |
|---|---|---|---|
| 2.16 单行卡片文案门禁不适用 | limitUp 全模块 | 统计卡以事实值展示为主，无“指定副文案必须单行”的需求 | 标记 N/A |

---

## 13. 签字清单

### 13.1 后端负责人

1. [x] ST 口径与封板率口径可实现
2. [x] 天地/地天文本词典规则可实现（含排除词、双计）
3. [x] 今日/昨日结构同算法可实现

### 13.2 前端负责人

1. [x] 2×2 结构字段可直接消费
2. [x] 8 卡 UI 可无歧义映射
3. [x] 天地/地天计数按数值渲染（未命中为 0）

### 13.3 架构/产品负责人

1. [x] 范围未扩散
2. [x] 口径与页面事实一致
3. [x] 可进入编码阶段

### 13.4 执行确认项（已完成）

1. [x] 三方签字清单全部勾选完成。
2. [x] `9.1 核心测试 case` 对应的真实 API 与真实展示用例已落库并可执行。
3. [x] 通用清单映射矩阵（2.1~2.18）完成复审，无冲突条目。

---

## 14. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-09 | 首版：冻结涨跌停统计与分布模块 M2 编码门禁 | Codex |
| v1.1 | 2026-05-10 | 对齐通用清单：补齐 2.1~2.16 映射矩阵、模块例外白名单、loading/5秒超时/source 渐进替换门禁 | Codex |
| v1.2 | 2026-05-10 | 对齐拍板口径：ST默认排除、ST板块过滤并补齐Top5、同板块fallback、天地/地天文本词典与双计、未命中返回0 | Codex |
| v1.3 | 2026-05-10 | 对齐最新模板与通用清单：补齐 2.17/2.18 映射、核心测试 case 门禁、8 条跨模块原则映射 | Codex |
| v1.4 | 2026-05-11 | 收口状态：从 Draft 切换为 Frozen，完成三方签字与执行确认项 | Codex |
