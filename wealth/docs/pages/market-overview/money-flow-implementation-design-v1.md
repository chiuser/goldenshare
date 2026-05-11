# 市场总览｜大盘资金流向技术实施方案 v1（implementation-design）

> 用途：把“大盘资金流向”需求文档转成可实施技术方案。  
> 阶段：编码前。  
> 产物性质：实现设计基线（不写业务代码）。

---

## 1. 文档目的

1. 对应需求文档：  
   [money-flow-benchmark-requirement-v1.md](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/money-flow-benchmark-requirement-v1.md)
2. 本文目标：冻结大盘资金流向模块的数据源、查询口径、状态与异常语义。
3. 本文不做：不落业务代码，不改页面样式，不改其他模块。
4. 跨模块抽象门禁原则适配结论：本模块全量适用 8 条原则，落点见 `1.1`。

关联门禁：  
[money-flow-m2-coding-gate-v1.md](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/money-flow-m2-coding-gate-v1.md)

---

## 1.1 跨模块抽象门禁原则适配（必填）

| 原则 | 本模块结论 | 设计落点 | 计划测试 |
|---|---|---|---|
| 事实源单一原则 | 适用；资金流事实单源 | `market_moneyflow_dc` 单源读取 | 集成测试校验字段来源与值 |
| 契约先行与冻结原则 | 适用；先冻结 DTO 再编码 | `money_flow.py` schema 与样例响应 | 契约字段断言测试 |
| 配置一致性原则 | 适用；首期无配置分支 | 固定 `oneMonth/threeMonth` | 请求无配置分支回归 |
| 默认行为显式原则 | 适用；支持显式观测日与系统自动观测日 | `tradeDate` 参数校验 + `trade_calendar` 取值策略 | 显式 `tradeDate` + 默认路径 + 边界态测试 |
| 排序与筛选确定性原则 | 适用；历史点升序、无跨源拼接 | 历史查询输出排序规则 | 排序稳定性测试 |
| 性能预算前置原则 | 适用；P95 预算前置 | 预算 `P95 < 260ms`、payload `< 90KB` | 集成压测与门禁记录 |
| 可观测与异常标准化原则 | 适用；统一异常对象与模块状态 | `status_resolver` + `exception_builder` | delayed/empty/error 分支测试 |
| 测试以用户可见结果为中心原则 | 适用；双卡与历史图为主验收 | 核心字段与页面展示一一映射 | 真实 API + 前端展示 smoke |

---

## 2. 代码现状审计（基于真实代码）

1. 现页面基线为：双卡（今日/昨日）+ 单型资金净流向饼图 + 单折线 + `1个月/3个月`。
2. 当前前端 `MarketMoneyFlowPanel` 已固定展示“单型资金净流向饼图 + 净流入历史主线白色、0 轴居中、Tooltip 正红负绿”。
3. 当前前端仍消费整页 mock ViewModel 字段：`moneyFlowMetrics`、`moneyFlowOrderSizeStructure`、`charts.moneyFlow`。
4. 结论：
   - 先做模块独立接口 `GET /api/v1/wealth/market/money-flow`；
   - 前端本轮必须新增 money-flow 模块 provider/view-model adapter，把模块接口 DTO 转成 `MarketMoneyFlowPanel` 的显式 props；
   - 不允许在页面层临时拼字段，也不允许继续让 money-flow 组件依赖整页 `MarketOverview`；
   - 后续再接 overview 聚合，不在本轮扩散。

### 2.1 真实数据验证结论（2026-05-12）

1. 验证脚本：
   [money-flow-real-data-validation-sql-v1.sql](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/money-flow-real-data-validation-sql-v1.sql)
2. 状态 case 结果：
   - 默认路径（系统自动交易日）-> `READY`
   - 显式 `tradeDate` 路径 -> 与同日查询口径一致
3. 性能基线（`EXPLAIN ANALYZE`）：
   - 双卡查询：`Execution Time ~ 18.8ms`
   - 1个月历史：`Execution Time ~ 19.0ms`
   - 3个月历史：`Execution Time ~ 18.9ms`
4. 结论：在当前数据规模下，性能明显低于模块预算 `P95 < 260ms`。

---

## 3. 分层架构与目录落点

### 3.1 接口范围

1. 模块接口路径：`GET /api/v1/wealth/market/money-flow`
2. 是否整页聚合接口：否（模块接口）
3. 模块接口返回范围：仅 `moneyFlow` 模块对象与必要状态字段

### 3.2 代码目录模板（按模块拆分）

```text
src/biz/
  api/
    wealth/
      market/
        money_flow.py
  queries/
    wealth/
      market/
        money_flow/
          money_flow_query.py
          money_flow_query_service.py
  schemas/
    wealth/
      market/
        money_flow.py
  services/
    wealth/
      market/
        money_flow/
          money_flow_status_resolver.py
          money_flow_exception_builder.py
```

---

## 4. 数据流与执行链路

1. 请求入口：`api.wealth.market.money_flow`
2. 参数校验：`market/tradeDate/debug`
   - `tradeDate` 可选，语义为模块观测交易日。
   - 未传 `tradeDate` 时，后端按交易日历和盘后口径自动推导目标交易日。
   - `tradeDate` 只用于回看、验证和调试，不允许前端把它扩展成用户侧资金流规则配置。
3. 查询编排：
   - 当日净流入
   - 前一交易日净流入
   - 分单结构（超大/大/中/小）
   - 历史净流入序列（22/62 交易日）
4. 状态归并：`money_flow_status_resolver`
5. 异常组装：`money_flow_exception_builder`
6. 响应输出：`schemas.wealth.market.money_flow`

### 4.1 前端接入链路（必须显式落地）

```text
MarketOverviewPage
  -> money-flow provider
  -> MoneyFlowResponseData
  -> MoneyFlowPanelViewModel
  -> MarketMoneyFlowPanel
```

前端落地规则：

1. `MarketMoneyFlowPanel` 不再直接接收整页 `MarketOverview` 对象。
2. money-flow provider 只负责调用 `/api/v1/wealth/market/money-flow`，不得读取其他模块数据。
3. adapter 只做 DTO 到展示 ViewModel 的格式化边界转换，例如金额从元转“亿”、方向字段从正负值派生；不得新增业务事实。
4. 当前 UI 可见字段必须完整覆盖：
   - 双卡：今日大盘资金净流入、昨日大盘资金净流入；
   - 饼图：超大单/大单/中单/小单资金净流向金额、占比、方向；
   - 历史图：`1个月/3个月` 净流入点位；
   - 状态：loading/ready/error/delayed/partial/empty 与 debug 面板。
5. 未返回真实 API 前展示 loading，不允许用 mock 数据冒充 ready；超时按模块 error 处理。

---

## 5. 查询编排策略

### 5.1 主查询（今日/昨日净流入）

1. 来源：`core_serving.market_moneyflow_dc`
2. 当前日：
   - `select net_amount from ... where trade_date=:target_date`
3. 前一交易日：
   - `select net_amount from ... where trade_date=:prev_trade_date`

### 5.2 分单结构查询

1. 来源：`core_serving.market_moneyflow_dc`
2. 字段：
   - `buy_elg_amount`, `buy_elg_amount_rate`
   - `buy_lg_amount`, `buy_lg_amount_rate`
   - `buy_md_amount`, `buy_md_amount_rate`
   - `buy_sm_amount`, `buy_sm_amount_rate`
3. 规则：
   - 与主查询同一 `trade_date`；
   - 缺失字段按 `null` 返回，不做跨表补算。
   - 源表列名为 `buy_*`，本模块按数据源既有口径承接为“单型资金净流向”字段；前端不得根据列名自行改写语义或二次计算买卖差。

### 5.3 历史趋势（1个月/3个月）

1. 交易日序列来源：`core_serving.trade_calendar`
2. 1个月：最近 22 个交易日
3. 3个月：最近 62 个交易日
4. 每个交易日查询：
   - `net_amount` 作为该日净流入
5. 输出：
   - `MoneyFlowHistoryPoint[]`，按 `tradeDate` 升序

### 5.4 空数据与异常处理

1. 当日缺失且前日缺失：模块 `EMPTY`。
2. 当日缺失但观测日落后：模块 `DELAYED`。
3. 双卡可用但历史不足：模块 `PARTIAL`。
4. SQL/服务异常：模块 `ERROR`。

### 5.5 辅助查询（补列/补名）

1. 本模块无“补列补名”跨表查询，所有展示字段来自单源 `market_moneyflow_dc`。
2. 不做名称字典补齐，不做跨源拼接，避免事实漂移。

### 5.6 回退查询（可选）

1. 本模块无回退查询。
2. 当源缺失时，通过 `DELAYED/PARTIAL/EMPTY` 显式状态表达，不做隐式 fallback。

### 5.7 去重、排序、截断规则

1. 历史序列按 `tradeDate` 升序。
2. 不做去重裁剪（由交易日序列与单日一条约束保证唯一性）。
3. 固定区间：
   - `oneMonth` 最多 22 点；
   - `threeMonth` 最多 62 点。

### 5.8 默认行为与边界行为（严格/降级/回退）

1. 接受可选 `tradeDate`；传入时以该交易日作为观测日，未传时统一使用交易日历期望日。
2. `tradeDate` 必须是合法日期格式；是否为交易日由查询服务按交易日历校验并决定是否返回业务错误。
3. 源数据落后：标记 `DELAYED`，不回退旧口径数据掩盖状态。
4. 历史不足：标记 `PARTIAL`，保留可展示点位。
5. 查询失败：标记 `ERROR`，不影响其他模块渲染。

### 5.9 关键筛选枚举与排序规则固定化

1. `market` 仅接受 `CN_A`，不支持其他市场枚举。
2. 排序规则固定为 `tradeDate` 升序；不存在主次排序歧义。

---

## 6. 状态与异常落地

1. `pageStatus`：沿用整页归并规则。
2. `moduleStatus`（debug）：
   - `moduleKey=moneyFlow`
   - `expectedTradeDate/observedTradeDate/lagDays/status/note`
   - 其中 `expectedTradeDate` 表示“本次请求解析后的目标观测交易日”：显式传入 `tradeDate` 时等于该值；未传时等于系统按交易日历和盘后口径推导的交易日。
3. debug 输出：
   - 仅 `debug=1` 返回；
   - 生产环境禁用。
4. 异常码（需登记注册表）：
   - `MF_SOURCE_DELAYED`
   - `MF_SOURCE_EMPTY`
   - `MF_HISTORY_INCOMPLETE`
   - `MF_QUERY_FAILED`

---

## 7. 性能与缓存策略

1. 性能预算：P95 `< 260ms`（模块独立请求）。
2. 首版策略：无 Redis，仅依赖轻量查询与序列化。
3. 二期缓存（可选）：
   - key：`wealth:money-flow:{market}:{targetTradeDate}`
4. 一致性：
   - 以交易日快照为主；
   - 不做跨日补值。

---

## 8. 安全与权限

1. 鉴权依赖：沿用 `quote.read`。
2. 权限点：已登录且具备行情读取权限可访问。
3. 防误用策略：
   - 非法 market/date 直接 `400001`；
   - debug 输出生产禁用。
   - 前端超时阈值默认 5 秒，超时按模块 error 处理，不做静默回退。

---

## 9. 测试与验证计划

1. 单元测试：
   - 净流入正负语义
   - 分单结构字段映射
2. 集成测试：
   - 正常/延迟/partial/空/错误五态
   - 历史点 `22/62` 范围输出
3. 冒烟验证：
   - 双卡 + 单型资金净流向饼图 + 历史图数据结构可消费
   - UI 保持不变
4. 失败回滚与观测：
   - 查询失败仅影响模块，不阻塞整页其他模块。

### 9.1 核心测试 case（必填）

1. 核心字段清单（页面可见要素对应字段）：
   - `moneyFlow.metrics.todayNetAmount`
   - `moneyFlow.metrics.prevNetAmount`
   - `moneyFlow.byOrderSize.elg.amount/rate`
   - `moneyFlow.byOrderSize.lg.amount/rate`
   - `moneyFlow.byOrderSize.md.amount/rate`
   - `moneyFlow.byOrderSize.sm.amount/rate`
   - `moneyFlow.historyByRange.oneMonth[].netAmount`
   - `moneyFlow.historyByRange.threeMonth[].netAmount`
   - `pageStatus.status`
2. 后端真实 API 集成测试设计（非 mock service/query）：
   - 覆盖 `READY/PARTIAL/DELAYED/EMPTY/ERROR`；
   - 覆盖 `tradeDate` 显式输入、默认路径与边界状态；
   - 断言历史点排序与范围长度上限。
3. 前端真实 API 展示校验设计（非 mock adapter）：
   - 双卡数值、涨跌颜色语义、空值降级 `--`；
   - 单型资金净流向饼图的四类字段、占比、方向与后端返回一致；
   - 历史区间切换（1个月/3个月）与点位更新；
   - debug=1 时模块状态与异常列表可见。
4. 执行命令与通过标准：
   - 后端：`pytest -q tests/web/test_wealth_market_money_flow_api.py`
   - 前端：`cd wealth && npm run test -- market-overview-money-flow-real-api`
   - 标准：核心字段断言全通过，无未登记异常码。

### 9.2 参考 case（可复用）

1. “接口成功但模块空数据”：验证 `EMPTY` 归因正确，不误报 `ERROR`。
2. “历史同分/空值混合”：验证折线点位按日期升序、空值点不污染排序。
3. “默认行为不清”：验证显式 `tradeDate` 与系统自动交易日两条路径语义清楚、互不污染。
4. “debug 泄露风险”：验证生产环境 `debug` 输出禁用。

---

## 10. 分期里程碑

1. M1（方案冻结）：双卡口径 + 分单结构 + 历史范围冻结。
2. M2（后端实现）：money-flow 模块接口、查询、状态、异常落地。
3. M3（前端接入）：接真实 money-flow 数据，保持现有 UI 不变。
4. M4（回归发布）：联调、性能回归、灰度验收。

---

## 11. 风险与缓解

1. 风险：`market_moneyflow_dc` 当日无行导致模块长期 delayed。  
   缓解：模块独立 delayed 态 + debug 可追因，不跨源补值。
2. 风险：历史点不足导致趋势图突兀。  
   缓解：模块 `PARTIAL` + `MF_HISTORY_INCOMPLETE`，前端保留可用点位。
3. 风险：金额单位理解偏差。  
   缓解：合同层固定原始单位 `yuan`，前端统一格式化为“亿”展示。

---

## 12. 已确认项（本轮）

1. 本模块采用单源 `market_moneyflow_dc`，不做跨表兜底。
2. 时间范围固定 `1个月/3个月`。
3. 前端展示保持当前双卡 + 单型资金净流向饼图 + 历史图，不改布局交互。
4. 本轮无拍板阻断项。

---

## 13. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-08 | 首版：冻结大盘资金流向模块实施口径（双卡 + 历史趋势 + 分单结构） | Codex |
| v1.1 | 2026-05-12 | 对齐实施方案模板：补齐 8 条原则适配矩阵与核心测试 case 门禁 | Codex |
| v1.2 | 2026-05-12 | 强化实现层编排章节：补齐辅助/回退/排序截断/默认行为与超时阈值约束 | Codex |
| v1.3 | 2026-05-12 | 回写真实数据验证结果与性能基线，收敛为默认路径口径并清理无效分支讨论 | Codex |
| v1.4 | 2026-05-12 | 根据审计结果补齐前端 provider/view-model adapter 方案、可见分单饼图字段与真实测试命令 | Codex |
| v1.5 | 2026-05-12 | 统一市场模块请求口径：恢复 `tradeDate` 可选观测日参数，并补齐默认路径与显式日期双路径门禁 | Codex |
