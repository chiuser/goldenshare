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

关联门禁：  
[money-flow-m2-coding-gate-v1.md](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/money-flow-m2-coding-gate-v1.md)

---

## 2. 代码现状审计（基于真实代码）

1. 现页面基线为：双卡（今日/昨日）+ 单折线 + `1个月/3个月`。
2. 当前前端 `MarketMoneyFlowPanel` 已固定展示“净流入历史主线白色、0 轴居中、Tooltip 正红负绿”。
3. 结论：
   - 先做模块独立接口 `GET /api/v1/wealth/market/money-flow`；
   - 后续再接 overview 聚合，不在本轮扩散。

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
3. 查询编排：
   - 当日净流入
   - 前一交易日净流入
   - 分单结构（超大/大/中/小）
   - 历史净流入序列（22/62 交易日）
4. 状态归并：`money_flow_status_resolver`
5. 异常组装：`money_flow_exception_builder`
6. 响应输出：`schemas.wealth.market.money_flow`

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

---

## 6. 状态与异常落地

1. `pageStatus`：沿用整页归并规则。
2. `moduleStatus`（debug）：
   - `moduleKey=moneyFlow`
   - `expectedTradeDate/observedTradeDate/lagDays/status/note`
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
   - key：`wealth:money-flow:{market}:{tradeDate}`
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

---

## 9. 测试与验证计划

1. 单元测试：
   - 净流入正负语义
   - 分单结构字段映射
2. 集成测试：
   - 正常/延迟/partial/空/错误五态
   - 历史点 `22/62` 范围输出
3. 冒烟验证：
   - 双卡 + 历史图数据结构可消费
   - UI 保持不变
4. 失败回滚与观测：
   - 查询失败仅影响模块，不阻塞整页其他模块。

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

## 12. 已确认清零项

1. 本模块采用单源 `market_moneyflow_dc`，不做跨表兜底。
2. 时间范围固定 `1个月/3个月`。
3. 前端展示保持当前双卡 + 历史图，不改布局交互。
4. 本轮无未决拍板项。

---

## 13. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-08 | 首版：冻结大盘资金流向模块实施口径（双卡 + 历史趋势 + 分单结构） | Codex |
