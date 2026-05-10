# 市场总览｜成交额总览技术实施方案 v1（implementation-design）

> 用途：把“成交额总览”需求文档转成可实施技术方案。  
> 阶段：编码前。  
> 产物性质：实现设计基线（不写业务代码）。

---

## 1. 文档目的

1. 对应需求文档：  
   [turnover-benchmark-requirement-v1.md](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/turnover-benchmark-requirement-v1.md)
2. 本文目标：冻结成交额总览模块的数据源、聚合口径、状态与异常语义。
3. 本文不做：不落业务代码，不改页面样式，不改其他模块。

关联门禁：  
[turnover-m2-coding-gate-v1.md](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/turnover-m2-coding-gate-v1.md)

补充长期方案：  
[turnover-minute-snapshot-plan-v1.html](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/turnover-minute-snapshot-plan-v1.html)

补充长期方案门禁：  
[turnover-minute-snapshot-m2-coding-gate-v1.md](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/turnover-minute-snapshot-m2-coding-gate-v1.md)

> 说明：当前 v1 实现已验证，直接从 `raw_tushare.stk_mins` 在线探测最新分钟日期与聚合日内累计曲线会造成结构性慢查询。后续分钟曲线长期方案以 `turnover-minute-snapshot-plan-v1.html` 为准，避免继续扩散 raw 在线聚合。
>
> 本文与 `turnover-m2-coding-gate-v1.md` 约束的是“第一版 turnover 真实 API 接入”。若进入分钟线快照长期改造，必须额外以 `turnover-minute-snapshot-plan-v1.html` 与 `turnover-minute-snapshot-m2-coding-gate-v1.md` 为准。

---

## 2. 代码现状审计（必须基于真实代码）

1. 页面基线已冻结成交额总览为“4 卡 + 2 图 + `1个月/3个月`”。
2. 当前 API 文档对成交额总览尚未专项重做，缺乏独立三件套约束。
3. 结论：
   - 先做模块独立接口 `GET /api/v1/wealth/market/turnover`；
   - 后续再接 overview 聚合，不在本轮扩散。

---

## 3. 分层架构与目录落点

### 3.1 接口范围

1. 模块接口路径：`GET /api/v1/wealth/market/turnover`
2. 是否整页聚合接口：否（模块接口）
3. 模块接口返回范围：仅 `turnover` 模块对象与必要状态字段

### 3.2 代码目录模板（按模块拆分）

```text
src/biz/
  api/
    wealth/
      market/
        turnover.py
  queries/
    wealth/
      market/
        turnover/
          turnover_query.py
          turnover_query_service.py
  schemas/
    wealth/
      market/
        turnover.py
  services/
    wealth/
      market/
        turnover/
          turnover_status_resolver.py
          turnover_exception_builder.py
```

---

## 4. 数据流与执行链路

1. 请求入口：`api.wealth.market.turnover`
2. 参数校验：`market/tradeDate/debug`
3. 查询编排：
   - 当日/前日总成交额聚合
   - 5日与20日窗口聚合
   - 历史趋势点聚合（22/62 交易日）
   - 日内累计曲线（固定启用 `wealth_market_turnover_snapshot`）
4. 状态归并：`turnover_status_resolver`
5. 异常组装：`turnover_exception_builder`
6. 响应输出：`schemas.wealth.market.turnover`
7. 前端接入行为门禁（真实源）：
   - 请求 pending：页面该模块显示 `loading`；
   - 请求超过 5 秒：页面该模块显示 `error`；
   - `loading/error` 两种状态都禁止回填 mock 数据。

---

## 5. 查询编排策略

## 5.1 主查询（当日与前日）

1. 来源：`core_serving.equity_daily_bar`
2. 金额单位：`amount` 统一按 `thousand_yuan`（千元）口径输出，与市场客观总结模块保持一致。
3. 当前日：
   - `sum(amount) where trade_date=:target_date`
4. 前一交易日：
   - `sum(amount) where trade_date=:prev_trade_date`
5. 派生：
   - `amountDelta = todayAmount - prevAmount`
   - `amountDeltaPct = amountDelta / prevAmount`

## 5.2 窗口统计（5日/20日）

1. 交易日序列来源：`core_serving.trade_calendar`
2. 5 日：最近 5 个交易日的日总成交额聚合
3. 20 日：最近 20 个交易日的日总成交额均值聚合（固定口径）

## 5.3 历史趋势（1个月/3个月）

1. 1个月：最近 22 个交易日
2. 3个月：最近 62 个交易日
3. 每个交易日聚合：
   - `sum(amount)` 作为该日成交总额
4. 输出：
   - `TurnoverHistoryPoint[]`，按 `tradeDate` 升序

## 5.4 日内累计曲线（固定启用）

1. 来源：`core_serving.wealth_market_turnover_snapshot`
2. 金额单位：快照中的 `total_amount` 与 `points_json[].amount` 均为 `thousand_yuan`（千元），物化时由分钟线源端元口径转换而来。
3. 条件：
   - `type='stock'`
   - `market='CN_A'`
   - `trade_date=目标交易日`
   - `freq=30`
   - `build_status='READY'`
4. 读取与计算：
   - 读取快照单行 `points_json`
   - 依 `tradeTimeTs` 升序累计 `amount`，生成页面所需 `cumAmount`
5. 坐标点（固定 5 点）：
   - `09:30`
   - `10:30`
   - `11:30`
   - `14:00`
   - `15:00`

## 5.5 空数据与异常数据处理

1. 当日缺失：模块 `DELAYED/EMPTY`（按 expected vs observed 判定）。
2. 历史缺口：保留可用点，模块 `PARTIAL`。
3. 日内曲线缺失但四卡可用：模块 `PARTIAL`。

## 5.6 统计计算与数据传输边界

1. `todayAmount/prevAmount/5日均值/20日均值/历史趋势` 全部在 SQL 侧聚合，不允许先拉全量明细到应用层再计算。
2. 日内累计曲线按 `freq=30` 聚合后返回固定 5 点；禁止返回原始分钟明细给前端再累计。
3. 本模块不依赖数据库特有函数（如 `percentile_disc`）；SQL 需兼容当前测试数据库口径。

---

## 6. 状态与异常落地

1. `pageStatus`：沿用整页归并规则。
2. `moduleStatus`（debug）：
   - `moduleKey=turnover`
   - `expectedTradeDate/observedTradeDate/lagDays/status/note`
3. debug 输出：
   - 仅 `debug=1` 返回；
   - 生产环境禁用。
4. 异常码（需登记注册表）：
   - `TO_SOURCE_DELAYED`
   - `TO_SOURCE_EMPTY`
   - `TO_INTRADAY_MISSING`
   - `TO_QUERY_FAILED`

---

## 7. 性能与缓存策略

1. 性能预算：P95 < 280ms（含日内曲线时）。
2. 首版策略：无 Redis，仅依赖聚合查询与轻量序列化。
3. 二期缓存（可选）：
   - key：`wealth:turnover:{market}:{tradeDate}`
4. 一致性：
   - 以交易日快照为主；
   - 日内曲线按目标交易日重算。

---

## 8. 安全与权限

1. 鉴权依赖：沿用 `quote.read`。
2. 权限点：已登录且具备行情读取权限可访问。
3. 防误用策略：
   - 非法 market/date 直接 `400001`
   - debug 输出生产禁用。

---

## 9. 测试与验证计划

1. 单元测试：
   - delta 与 deltaPct 计算
   - 5日/20日窗口聚合
2. 集成测试：
   - 正常/延迟/空/错误四态
   - 历史点 `22/62` 范围输出
3. 冒烟验证：
   - 4 卡 + 2 图数据结构可消费
   - UI 不变
   - 真实源请求 pending 时显示 loading（不展示 mock turnover）
   - 真实源请求超过 5 秒显示 error（不回填 mock turnover）
4. 失败回滚与观测：
   - 查询失败仅影响模块，不阻塞整页其他模块。
5. 性能验证：
   - 模块切 real API 前必须完成端到端耗时实测，并与 5 秒前端超时阈值对齐；
   - 超预算时先优化 SQL 聚合与返回体，不引入计划外缓存扩散。
6. 范围约束验证：
   - 本轮只允许 `turnover` 模块 source 从 `mock` 切到 `real`；
   - 其他模块 source 必须保持原值不变。

## 9.1 图表与说明文案约束（对齐 checklist）

1. 成交额图表纵轴必须从 `0` 起，固定刻度为 `0/10000/20000/30000/40000`，不允许出现负数刻度。
2. 图下“横轴/纵轴解释”等说明文案默认不常驻展示；仅在 benchmark 明确要求时允许展示。
3. “5日均值”卡片副文案（`20日均值 xxx亿`）必须单行展示，采用模块定点样式约束，不允许挤压其他卡片布局。

## 9.2 配置生效语义（本模块）

1. 本模块当前无策略配置中心配置项（无独立 JSON 配置文件、无 moduleKey 注册项）。
2. 若后续引入配置化能力，必须补齐：配置文件路径、注册键（`moduleKey/market`）、生效时机、校验失败行为，并同步更新 coding gate 门禁。

---

## 10. 分期里程碑

1. M1（方案冻结）：4卡口径 + 历史范围 + 日内曲线策略冻结。
2. M2（后端实现）：turnover 模块接口、查询、状态、异常落地。
3. M3（前端接入）：接真实 turnover 数据，保持现有 UI 不变。
4. M4（回归发布）：联调、性能回归、灰度验收。

---

## 11. 风险与缓解

1. 风险：`wealth_market_turnover_snapshot` 缺失或未 READY 导致日内曲线为空。  
   缓解：模块进入 `PARTIAL`，并通过 `TO_INTRADAY_MISSING` 可观测。
2. 风险：快照构建未完成导致模块进入 `PARTIAL/DELAYED`。  
   缓解：手动物化命令先构建 `1/5/15/30/60`，查询链路只读取 `build_status='READY'`。
3. 风险：金额单位口径误解导致前端展示偏差。  
   缓解：响应字段附 `unit` 与格式化规则说明。

---

## 12. 已确认清零项

1. 20 日指标口径固定为 20 日均值。
2. 日内累计曲线固定启用 `wealth_market_turnover_snapshot`。
3. 日内累计曲线固定 `freq=30`，输出 5 个坐标点。
4. 本轮无未决拍板项。

---

## 13. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-08 | 首版：冻结成交额总览模块实施口径（4卡 + 两图） | Codex |
| v1.1 | 2026-05-08 | 拍板落定：20日均值 + 30min 5点日内累计曲线 | Codex |
| v1.2 | 2026-05-10 | 文档纠偏：日内累计来源统一为 `wealth_market_turnover_snapshot`，补充单行副文案约束 | Codex |
