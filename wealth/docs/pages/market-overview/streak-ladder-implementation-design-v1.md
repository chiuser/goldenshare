# 市场总览｜连板天梯技术实施方案 v1（implementation-design）

> 用途：把“连板天梯”需求文档转成可实施技术方案。
> 阶段：编码前。
> 产物性质：实现设计基线（不写业务代码）。

---

## 1. 文档目的

1. 对应需求文档：
   [streak-ladder-benchmark-requirement-v1.md](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/streak-ladder-benchmark-requirement-v1.md)
2. 本文目标：冻结连板天梯模块的接口路径、目录落点、查询编排、DTO、状态异常与测试计划。
3. 本文不做：不落业务代码，不改页面视觉，不改 `limitUp` 模块，不改其它市场模块。
4. 跨模块抽象门禁原则适配结论：本模块全量适用 8 条原则。

关联门禁：
[streak-ladder-m2-coding-gate-v1.md](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/streak-ladder-m2-coding-gate-v1.md)

---

## 1.1 跨模块抽象门禁原则适配（必填）

| 原则 | 本模块结论 | 设计落点 | 计划测试 |
|---|---|---|---|
| 事实源单一原则 | 适用；连板事实只能来自后端 `streakLadder` DTO | `equity_limit_list` 主查询 + schema | 后端真实 API 断言 `boardCount/bucketKey` |
| 契约先行与冻结原则 | 适用；先冻结 DTO 再编码 | 第 3 节、第 4 节 | 契约字段测试 + 前端类型检查 |
| 配置一致性原则 | 适用；首期无配置中心接入 | 第 7 节 | 断言无配置读取分支 |
| 默认行为显式原则 | 适用；默认观测日、empty、delayed、partial 全部写死 | 第 4 节、第 6 节 | 默认路径 + 显式 `tradeDate` 测试 |
| 排序与筛选确定性原则 | 适用；分桶、梯队内排序固定 | 第 5 节 | 排序稳定性与异常 `limit_times` 测试 |
| 性能预算前置原则 | 适用；P95 与 payload 预算冻结 | 第 7 节 | 接口耗时 + payload 预算记录 |
| 可观测与异常标准化原则 | 适用；统一 `SL_*` 异常码 | 第 6 节 | debug 异常覆盖测试 |
| 测试以用户可见结果为中心原则 | 适用；五梯队与股票卡片为验收核心 | 第 9 节 | 后端真实 API + 前端真实展示 smoke |

---

## 2. 代码现状审计（必须基于真实代码）

### 2.1 当前已有实现

1. 前端当前存在：
   - `wealth/src/features/market-overview/limit-up/StreakLadderPanel.tsx`
   - 该组件当前消费整页 `MarketOverview.ladder` mock 数据。
2. 页面装配当前存在：
   - `wealth/src/pages/market-overview/MarketOverviewPage.tsx`
   - 当前直接渲染 `StreakLadderPanel overview={overview}`。
3. 模块 source 清单当前存在：
   - `wealth/src/features/market-overview/api/moduleSources.ts`
   - 目前没有 `streakLadder` 独立 key。
4. 后端当前没有独立 `streak-ladder` API、schema、query、service。
5. 可复用模型：
   - `src/foundation/models/core/equity_limit_list.py`

### 2.2 当前冲突与技术债

1. 组件目录语义不准：连板天梯当前放在 `limit-up/` 下，但业务上已经确认为独立模块。
2. 数据来源不准：当前前端吃 mock，未接 `equity_limit_list`。
3. 契约不独立：当前没有 `streakLadder` 独立 API 和 provider。
4. 全局模型旧口径存在过时字段：早期文档曾把连板天梯主源写成 `limit_step`，当前应统一到 `equity_limit_list / limit_list_d`。

### 2.3 结论

1. 新增独立后端模块 `streak_ladder`。
2. 新增独立前端模块目录 `streak-ladder/`。
3. 将当前前端组件从“整页 mock 消费”改为“模块 provider + view-model adapter + 显式 props”。
4. 本轮编码时只允许切 `streakLadder`，其它模块保持当前 source 状态不动。

---

## 3. 分层架构与目录落点

### 3.1 接口范围

1. 模块接口路径：`GET /api/v1/wealth/market/streak-ladder`
2. 是否整页聚合接口：否。
3. 模块接口返回范围：仅 `streakLadder` 模块对象、`tradingDay`、`pageStatus`、可选 `debugInfo`。

### 3.2 后端代码目录

```text
src/biz/
  api/
    wealth/
      market/
        streak_ladder.py
  queries/
    wealth/
      market/
        streak_ladder/
          streak_ladder_state_query.py
          streak_ladder_query.py
          streak_ladder_query_service.py
  schemas/
    wealth/
      market/
        streak_ladder.py
  services/
    wealth/
      market/
        streak_ladder/
          streak_ladder_bucket_builder.py
          streak_ladder_status_resolver.py
          streak_ladder_exception_builder.py
```

职责约束：

1. `api` 只做路由、参数校验和依赖注入。
2. `queries` 只做 SQL 查询与轻量数据结构。
3. `services` 负责分桶、状态归并和异常组装。
4. `schemas` 只承载本模块 DTO，不承载整页 DTO。

### 3.3 前端代码目录

```text
wealth/src/features/market-overview/streak-ladder/
  StreakLadderPanel.tsx
  api/
    marketStreakLadderApi.ts
    marketStreakLadderAdapter.ts
    marketStreakLadderTypes.ts
  __tests__/
    marketStreakLadderAdapter.test.ts
```

页面装配改动：

1. `MarketOverviewPage` 只接入 `streak-ladder provider` 输出。
2. `StreakLadderPanel` 不再接收整页 `MarketOverview`。
3. `moduleSources.ts` 新增 `streakLadder` key，初始切换本轮为 `real`；非目标模块不改。

---

## 4. 数据流与执行链路

1. 请求入口：`api.wealth.market.streak_ladder`
2. 参数校验：
   - `market`
   - `tradeDate`
   - `debug`
3. 状态上下文：
   - 复用市场模块交易日解析思路，取 `expectedTradeDate/prevTradeDate/sessionStatus`。
4. 主查询：
   - 查询目标日 `equity_limit_list` 涨停行。
5. 分桶：
   - 解析 `limit_times` 为正整数 `boardCount`。
   - 分入五个固定 bucket。
6. 排序：
   - 每个 bucket 内按固定排序规则输出。
7. 状态归并：
   - `streak_ladder_status_resolver`
8. 异常组装：
   - `streak_ladder_exception_builder`
9. 响应输出：
   - `schemas.wealth.market.streak_ladder`

---

## 5. 查询编排策略

### 5.1 主查询：`equity_limit_list`

输入：`trade_date`

SQL 草案：

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

处理规则：

1. `ts_code` 为空：丢弃。
2. `limit_times` 解析不到正整数：丢弃并记录 `SL_INVALID_BOARD_COUNT`。
3. 同一 `ts_code` 多行：取最大 `boardCount`。
4. `close/pct_chg/open_times/industry` 缺失不丢主行，但记录 `SL_JOIN_METRIC_MISSING`。
5. `limit_list_d` 文档明确“不提供 ST 股票统计”，本模块不额外查询 ST 集合。

### 5.2 字段映射

1. `latestPrice` 使用 `equity_limit_list.close`，缺失为 `null`。
2. `changePct` 使用 `equity_limit_list.pct_chg`，缺失为 `null`。
3. `openTimes` 使用 `equity_limit_list.open_times`，缺失为 `null`。
4. `sectorName` 使用 `equity_limit_list.industry`，缺失为 `null`。
5. `direction` 由 `changePct` 派生：`>0 UP`，`<0 DOWN`，`=0 FLAT`，缺失 `UNKNOWN`。

### 5.3 分桶规则

| boardCount | bucketKey | bucketLabel | minBoardCount | maxBoardCount |
|---|---|---|---|---|
| `1` | `first` | `首板` | 1 | 1 |
| `2` | `second` | `二板` | 2 | 2 |
| `3` | `third` | `三板` | 3 | 3 |
| `4` | `fourth` | `四板` | 4 | 4 |
| `>=5` | `fifthPlus` | `五板及以上` | 5 | `null` |

### 5.4 梯队内排序规则

每个梯队内固定排序：

1. `boardCount` 降序。
2. `openTimes` 升序，`null` 放最后。
3. `changePct` 降序，`null` 放最后。
4. `latestPrice` 降序，`null` 放最后。
5. `subjectCode` 升序。

说明：

1. `first/second/third/fourth` 内 `boardCount` 理论相同，但仍保留统一排序规则。
2. `fifthPlus` 必须先按真实 `boardCount` 排序。
3. 前端不得重新排序。

### 5.5 空数据与异常数据处理

1. `equity_limit_list` 目标日无涨停行：模块 `EMPTY`，异常 `SL_SOURCE_EMPTY`。
2. 过滤后无有效行：模块 `EMPTY`，异常 `SL_SOURCE_EMPTY`。
3. 存在无效 `limit_times` 行：模块 `PARTIAL`，异常 `SL_INVALID_BOARD_COUNT`。
4. 有主行但展示字段缺失：模块 `PARTIAL`，异常 `SL_JOIN_METRIC_MISSING`。
5. SQL/服务异常：模块 `ERROR`，异常 `SL_QUERY_FAILED`。

---

## 6. 状态与异常落地

### 6.1 pageStatus 归并

| 模块状态 | 页面状态建议 | 说明 |
|---|---|---|
| `READY` | `READY` | 连板数据完整 |
| `DELAYED` | `PARTIAL` | 源日期落后 |
| `PARTIAL` | `PARTIAL` | 主数据可展示但有补列或异常行 |
| `EMPTY` | `EMPTY` 或 `PARTIAL` | 视整页其它模块归并 |
| `ERROR` | `ERROR` 或 `PARTIAL` | 视整页其它模块归并 |

### 6.2 moduleStatus

```ts
interface ModuleStatusItem {
  moduleKey: "streakLadder";
  expectedTradeDate: string;
  observedTradeDate: string | null;
  lagDays: number | null;
  status: "READY" | "DELAYED" | "PARTIAL" | "EMPTY" | "ERROR";
  note: string;
}
```

### 6.3 异常码映射

| code | severity | 触发条件 | 前端行为 |
|---|---|---|---|
| `SL_SOURCE_DELAYED` | warn | `observedTradeDate < expectedTradeDate` | debug 标记 delayed |
| `SL_SOURCE_EMPTY` | warn | 目标日无有效主行 | 模块 empty |
| `SL_INVALID_BOARD_COUNT` | warn | `limit_times` 非正整数 | 丢弃异常行，模块 partial |
| `SL_JOIN_METRIC_MISSING` | warn | 展示字段缺失 | 显示 `--`，模块 partial |
| `SL_QUERY_FAILED` | error | 查询/服务异常 | 模块 error |

---

## 7. 性能与缓存策略

1. P95 预算：`< 320ms`。
2. Payload 预算：`< 260KB`。
3. 首版策略：无 Redis，无预聚合新增表。
4. 查询策略：
   - 先按目标日取 `equity_limit_list` 涨停候选。
   - 本模块首期不做跨表补列。
   - 不扫描全市场。
5. 缓存二期可选：
   - key：`wealth:streak-ladder:{market}:{tradeDate}`
   - 当前不开发。

---

## 8. 安全与权限

1. 鉴权依赖：沿用行情读取权限。
2. 权限点：不新增独立权限点。
3. 防误用策略：
   - `market` 只接受 `CN_A`。
   - `tradeDate` 非法返回参数错误。
   - debug 输出生产禁用。

---

## 9. 测试与验证计划

### 9.1 单元测试

1. `limit_times` 解析：
   - `"1"` -> `1`
   - `"5"` -> `5`
   - `"11"` -> `11`
   - `""/null/"abc"` -> invalid
2. 分桶：
   - `1/2/3/4/>=5` 映射正确。
3. 排序：
   - `boardCount/openTimes/changePct/latestPrice/subjectCode` 主次序固定。
4. DTO adapter：
   - 真实 DTO 能转成股票卡片 view model。

### 9.2 后端真实 API 集成测试

建议新增：

```text
tests/web/test_wealth_market_streak_ladder_api.py
```

覆盖：

1. 正常返回五个固定 bucket。
2. 每个返回股票的 `boardCount` 与所属 bucket 一致。
3. `fifthPlus` 保留精确 `boardCount`。
4. `stocks[].subject.subjectCode/subjectName/boardCount` 必填字段齐全。
5. `latestPrice/changePct/openTimes/sectorName` 可空但字段存在。
6. debug 模式返回 `moduleKey=streakLadder`。

### 9.3 前端真实展示校验

建议新增：

```bash
cd wealth && npm run test -- market-overview-streak-ladder-real-api
```

覆盖：

1. loading -> ready。
2. 五个梯队标题均展示。
3. 股票卡片展示名称、代码、主题、价格、涨跌幅、开板次数。
4. 点击股票卡片触发 toast。
5. debug 面板能展示 `streakLadder` 模块状态。

---

## 10. 分期里程碑

1. M1：三件套评审与异常码登记。
2. M2：后端 `streak_ladder` API、query、schema、service 落地。
3. M3：前端 `streak-ladder` provider、adapter、panel 显式 props 改造。
4. M4：source 切换为 `real`，执行后端真实 API + 前端真实展示测试。

---

## 11. 风险与缓解

| 风险 | 触发条件 | 缓解动作 |
|---|---|---|
| `limit_times` 非数字导致分桶错误 | 源数据出现非数字文本 | 统一解析，失败丢弃并记录 `SL_INVALID_BOARD_COUNT` |
| 展示字段缺失造成卡片空洞 | `equity_limit_list.close/pct_chg/open_times/industry` 缺失 | 字段可空 + debug 异常，不阻断主展示 |
| 行业标签缺失 | `equity_limit_list.industry` 缺失 | `sectorName=null`，前端显示 `--` |
| payload 过大 | 极端日期首板数量过多 | 首版先返回全量，若超预算再进入评审，不在实现中临时截断 |

---

## 12. 待拍板项

当前无阻塞拍板项。若评审希望限制每梯队最多展示条数或增加“完整天梯”入口，必须先更新 benchmark 与 coding gate。

---

## 13. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-12 | 初版：冻结连板天梯独立模块实施落点、查询编排与测试计划 | Codex |
