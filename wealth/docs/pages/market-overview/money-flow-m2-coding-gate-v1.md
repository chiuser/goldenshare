# 市场总览｜大盘资金流向 M2 编码前门禁 v1

> 用途：在编码前冻结“大盘资金流向”模块的参数、响应、查询、状态、异常与性能。  
> 阶段：M2 开工前。  
> 产物性质：执行门禁清单（不通过不允许编码）。

关联文档：

1. [大盘资金流向标杆需求 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/money-flow-benchmark-requirement-v1.md)
2. [大盘资金流向技术实施方案 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/money-flow-implementation-design-v1.md)
3. [money-flow 真实数据验证用例 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/money-flow-real-data-validation-cases-v1.md)

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
11. [ ] 核心测试 case（真实 API + 前端展示）门禁冻结
12. [ ] 跨模块抽象门禁原则（8 条）映射完成
13. [ ] `module-delivery-checklist-v1` 映射完成（否决项全过）
14. [ ] 前端 provider/view-model adapter 方案冻结

---

## 3. 请求与响应冻结

### 3.1 请求参数冻结

```ts
interface MoneyFlowRequest {
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
5. `tradeDate` 只作为模块观测日，不允许扩展成用户侧资金流规则配置。

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
   - 源列名为 `buy_*`，契约按数据源口径承接为“单型资金净流向”；禁止前端自行改写语义或二次计算。
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
4. 前端请求超时阈值：`5s`
5. 超预算降级策略：先优化查询，不引入复杂缓存

---

## 9. 测试门禁

1. 单元测试：
   - 今日/昨日净流入映射
   - 分单结构字段映射
2. 集成测试：
   - 正常/延迟/partial/空/错误五态
   - 历史点位与时间排序
3. 冒烟测试：
   - 双卡 + 单型资金净流向饼图 + 历史图数据结构可渲染
4. debug 模式验证：
   - `debug=1` 返回模块级状态和异常；
   - 生产环境禁用 debug 输出。

### 9.1 核心测试 case 门禁（必填）

1. 核心字段清单（页面可见字段）：
   - `moneyFlow.metrics.todayNetAmount`
   - `moneyFlow.metrics.prevNetAmount`
   - `moneyFlow.byOrderSize.elg.amount/rate`
   - `moneyFlow.byOrderSize.lg.amount/rate`
   - `moneyFlow.byOrderSize.md.amount/rate`
   - `moneyFlow.byOrderSize.sm.amount/rate`
   - `moneyFlow.historyByRange.oneMonth[].netAmount`
   - `moneyFlow.historyByRange.threeMonth[].netAmount`
   - `pageStatus.status`
2. 后端真实 API 集成测试用例列表（禁止 mock service/query）：
   - `READY/PARTIAL/DELAYED/EMPTY/ERROR` 五态；
   - `tradeDate` 显式入参与默认路径（系统自动交易日）；
   - 历史点排序与区间上限（22/62）。
3. 前端真实 API 展示校验用例列表（禁止 mock adapter）：
   - 双卡数值与红涨绿跌语义；
   - 单型资金净流向饼图四类金额、占比、方向；
   - 空值降级 `--`；
   - 1个月/3个月切换；
   - debug 信息显示（仅调试态）。
4. 执行命令：
   - `pytest -q tests/web/test_wealth_market_money_flow_api.py`
   - `cd wealth && npm run test -- market-overview-money-flow-real-api`
5. 通过标准：
   - 核心字段断言全通过；
   - 页面关键展示项通过；
   - 无未登记异常码。

### 9.2 本轮真实数据验证结果（2026-05-12）

1. 执行命令：
   - `bash scripts/psql-remote.sh -f /Users/congming/github/goldenshare/wealth/docs/pages/market-overview/money-flow-real-data-validation-sql-v1.sql`
2. 状态验证结果：
   - 默认路径（系统自动交易日）-> `READY`
   - 显式 `tradeDate` 路径需在 API 实现时纳入同一测试套件。
3. 性能基线结果（`EXPLAIN ANALYZE`）：
   - Query-P1：`Execution Time ~ 18.8ms`
   - Query-P2：`Execution Time ~ 19.0ms`
   - Query-P3：`Execution Time ~ 18.9ms`
4. 结论：
   - 查询组合可正确产出双卡、分单、22/62 历史窗口；
   - 性能满足 `P95 < 260ms` 预算；
   - 当前可进入 API 编码阶段（仅限 money-flow 模块范围）。

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

## 11. 跨模块抽象门禁原则映射（必填）

> 要求：每条原则都要明确“是否适用 + 落地位置 + 对应测试”。

| 原则 | 是否适用 | 落地位置（字段/查询/配置/状态） | 测试落地 | 备注 |
|---|---|---|---|---|
| 事实源单一原则 | 是 | `market_moneyflow_dc` 单源读取 | API 集成：字段来源与值断言 | 禁止跨源补值 |
| 契约先行与冻结原则 | 是 | `moneyFlow.metrics/byOrderSize/historyByRange` | API 契约断言 + 前端消费断言 | 字段语义冻结 |
| 配置一致性原则 | 是 | 本模块无策略配置分支 | 无配置分支回归用例 | 固定 1m/3m |
| 默认行为显式原则 | 是 | 显式观测日 + 系统自动交易日逻辑 + delayed/partial 规则 | 显式 `tradeDate`/默认路径/边界态测试 | 禁止隐式 fallback |
| 排序与筛选确定性原则 | 是 | 历史点按 `tradeDate` 升序 | 排序稳定性测试 | 无随机顺序 |
| 性能预算前置原则 | 是 | P95 与 payload 门禁 | 集成耗时与返回体统计 | 超预算先优化查询 |
| 可观测与异常标准化原则 | 是 | `debugInfo.modules/exceptions` | delayed/empty/error 分支断言 | 异常码必须注册 |
| 测试以用户可见结果为中心原则 | 是 | 双卡 + 单型资金净流向饼图 + 历史图 + 状态文案 | 前端 smoke 校验 | 禁止只测中间态 |

### 11.1 参考 case（可复用示例）

1. 目标交易日无数据但接口 200：应返回 `EMPTY/PARTIAL`，不能误报 `READY`。
2. 历史点存在空值：点位可空但排序必须稳定，且页面不崩溃。
3. debug 输出在生产环境禁用：避免异常明细外泄。

### 11.2 模块门禁清单（复盘增强版）

1. [x] 先证据后设计：已完成真实数据探针并冻结单源口径。  
2. [x] 先规则后实现：delayed/partial/empty 规则已文档冻结。  
3. [x] 可判定性优先：状态判定输入字段可直接判定。  
4. [x] 状态分层明确：页面级与模块级（debug）已拆分。  
5. [x] 后端定义事实：净流入与分单字段由后端统一产出。  
6. [x] 三件套强一致：需求/设计/门禁已同步对齐。  
7. [x] 反超前设计：未引入计划外配置与缓存能力。  
8. [x] 字段链路完整：UI -> API -> 表字段映射已可追溯。  

### 11.3 `module-delivery-checklist-v1` 映射（否决项）

| 清单条目 | 结果 | 证据/落点 |
|---|---|---|
| 2.1 三件套先行 | 通过 | 三件套三文档齐备并互链 |
| 2.2 后端事实归一 | 通过 | 单源 `market_moneyflow_dc` |
| 2.3 模块状态机清晰 | 通过 | READY/PARTIAL/DELAYED/EMPTY/ERROR |
| 2.4 显示语义与数据语义绑定 | 通过 | 正负净流入语义固定 |
| 2.5 测试覆盖行为过程 | 通过 | 五态 + debug 分支门禁 |
| 2.6 文档与实现同轮同步 | 通过 | 本轮同步修订三件套 |
| 2.7 模块级渐进替换纪律 | 通过 | 本轮仅 money-flow 模块文档更新 |
| 2.8 契约先行与消费者对齐 | 通过 | 先冻结 DTO，再落实现计划 |
| 2.9 图表坐标与说明约束 | 通过 | 历史图语义固定，文案不新增 |
| 2.10 统计计算与传输边界 | 通过 | 聚合下推 SQL，不在前端拼算 |
| 2.11 配置生效语义 | 不适用 | 本模块首期无配置中心接入 |
| 2.12 通用清单映射矩阵 | 通过 | 本章已逐项映射 |
| 2.13 模块例外白名单与语义断言 | 不适用 | 本模块无例外白名单需求 |
| 2.14 图表参数优先级与语义不可篡改 | 通过 | 历史图坐标语义固定，不改写参数 |
| 2.15 双图并排坐标对齐与标签避让 | 不适用 | 本模块仅单图，不涉及双图并排 |
| 2.16 指标卡片文案长度与单行约束 | 通过 | 双卡结构固定，文案长度受控 |
| 2.17 核心测试 case 覆盖 | 通过 | 9.1 已冻结真实 API + 前端展示门禁 |
| 2.18 跨模块抽象门禁原则 | 通过 | 11 已逐条映射 8 条原则，并补齐测试落点 |

### 11.4 模块 source 切换记录（2.7 追踪项）

1. 目标模块：`moneyFlow`
2. source key：`marketOverview.moduleSources.moneyFlow`
3. 切换前：`mock`
4. 切换后（本轮目标）：`real`
5. 非目标模块：保持当前实际 source 不变，不允许回退或顺手切换。
6. 当前基线：
   - 已为 `real`：`summary`、`majorIndices`、`breadth`、`style`、`turnover`、`leaderboards`、`limitUp`。
   - 仍为 `mock`：`sectors`。
   - 本轮只允许 `moneyFlow: mock -> real`。
7. 回滚步骤：
   - 将 `moneyFlow` source 置回 `mock`；
   - 回退本轮 `money-flow` 模块接口/adapter 改动；
   - 保持其他模块不动。

### 11.5 前端接入门禁（provider / view-model adapter）

1. 必须新增 money-flow 模块 provider，且只调用 `/api/v1/wealth/market/money-flow`。
2. 必须新增或收敛 `MoneyFlowPanelViewModel`，显式承载双卡、分单饼图、历史图、状态与 debug 信息。
3. `MarketMoneyFlowPanel` 不允许继续直接消费整页 `MarketOverview` 对象。
4. adapter 只能做展示边界转换，例如元到亿、正负方向、空值显示，不允许新增事实计算。
5. 页面层不得拼接 `moneyFlowMetrics`、`moneyFlowOrderSizeStructure`、`charts.moneyFlow` 这类旧整页字段。

## 12. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-08 | 首版：建立大盘资金流向模块编码门禁（双卡 + 历史趋势 + 分单结构） | Codex |
| v1.1 | 2026-05-12 | 对齐门禁模板与交付清单：补齐核心测试 case、8 条原则映射与 checklist 否决项映射 | Codex |
| v1.2 | 2026-05-12 | 补齐性能超时门禁与模块 source 切换追踪项（2.7），完善回滚记录口径 | Codex |
| v1.3 | 2026-05-12 | 回写真实数据验证结果，收敛为默认路径口径并移除前端不存在输入分支 | Codex |
| v1.4 | 2026-05-12 | 根据审计结果修正 source 切换基线、补 2.18 映射、修正前端测试命令并新增 provider/view-model adapter 门禁 | Codex |
| v1.5 | 2026-05-12 | 统一市场模块请求口径：恢复 `tradeDate` 可选观测日参数，并补齐显式日期测试门禁 | Codex |
