# 市场总览｜涨跌分布技术实施方案 v1（implementation-design）

> 用途：把“涨跌分布”需求文档转成可实施技术方案。  
> 阶段：编码前。  
> 产物性质：实现设计基线（不写业务代码）。

---

## 1. 文档目的

1. 对应需求文档：  
   [breadth-benchmark-requirement-v1.md](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/breadth-benchmark-requirement-v1.md)
2. 本文目标：冻结涨跌分布模块的查询、状态、异常与返回契约。
3. 本文不做：不落业务代码，不改前端样式，不改其他模块语义。

关联门禁：  
[breadth-m2-coding-gate-v1.md](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/breadth-m2-coding-gate-v1.md)

---

## 2. 代码现状审计（必须基于真实代码）

1. 现有页面已固定涨跌分布交互：
   - [MarketBreadthPanel.tsx](/Users/congming/github/goldenshare/wealth/src/features/market-overview/breadth/MarketBreadthPanel.tsx)
2. 现有前端 mock 口径已固定 `1m/3m` 双范围：
   - [marketOverviewMockAdapter.ts](/Users/congming/github/goldenshare/wealth/src/features/market-overview/api/marketOverviewMockAdapter.ts)
3. 当前冲突与风险：
   - `market-overview-api-model-design-v1.md` 尚未细化 breadth 模块实现落点。
4. 结论：
   - breadth 模块按独立模块接口落 `src/biz` 分层目录；
   - 本模块不接策略配置中心（无配置化能力）。

---

## 3. 分层架构与目录落点

### 3.1 接口范围

1. 模块接口路径：`GET /api/v1/wealth/market/breadth`
2. 是否整页聚合接口：否（模块接口）
3. 模块返回范围：仅 `breadth` 模块对象与必要状态字段

### 3.2 代码目录模板（按模块拆分）

```text
src/biz/
  api/
    wealth/
      market/
        breadth.py
  queries/
    wealth/
      market/
        breadth/
          breadth_metrics_query.py
          breadth_history_query.py
          breadth_query_service.py
  schemas/
    wealth/
      market/
        breadth.py
  services/
    wealth/
      market/
        breadth/
          breadth_status_resolver.py
          breadth_exception_builder.py
```

---

## 4. 数据流与执行链路

1. 请求入口：`api.wealth.market.breadth`
2. 参数校验：`market/tradeDate/debug`
3. 主查询：
   - `breadth_metrics_query`：当日上/下/平家数
   - `breadth_history_query`：最近 62 个交易日上/下家数
4. 结果编排：
   - 从 62 日结果切片得到 `3m`（62）和 `1m`（22）
5. 状态归并：`breadth_status_resolver` 产出模块状态
6. 异常组装：`breadth_exception_builder` 仅使用注册表异常码
7. 响应输出：`schemas.wealth.market.breadth` DTO
8. 前端渲染态（真实源）：
   - 返回前：`loading`
   - 返回成功：`ready`
   - 请求失败或超过 5 秒：`error`
   - 禁止 silent fallback 回填 mock。
9. 前端展示规则（冻结）：
   - 3 个指标卡副文案分别为：`红盘率 x%` / `绿盘率 x%` / `平盘率 x%`；
   - 平盘卡副文案禁止展示“当前日统计”；
   - 折线图纵轴固定 `yMin=0`，固定刻度值 `0/1500/3000/4500/6000`。

---

## 5. 查询编排策略

1. 主查询（当日指标）：
   - `equity_daily_bar` 按 `trade_date = target_date` 聚合；
   - 样本集口径：`equity_daily_bar` 全量样本，不做 ST/停牌特例附加过滤；
   - 仅 `pct_chg is not null` 参与上/下/平计数；
   - `upCount/downCount/flatCount` 由 `pct_chg` 条件计数；
   - `redRate = upCount / (upCount + downCount + flatCount)`。
2. 历史查询（趋势线）：
   - 先取最近 `62` 个开市交易日（trade_calendar）；
   - 再按每个交易日聚合 `upCount/downCount`；
   - 按日期升序输出。
3. 回退查询：
   - 不跨日补值；落后即 delayed。
4. 去重、排序、截断规则：
   - 历史点按 `tradeDate` 升序；
   - `1m` 固定 22 点，`3m` 固定 62 点。
5. 空数据与异常数据处理：
   - 单日无样本：模块 `EMPTY`；
   - 历史为空：返回空数组并标 `EMPTY`。

---

## 6. 状态与异常落地

1. `pageStatus`：沿用整页状态聚合规则。
2. `moduleStatus`（debug）：
   - `moduleKey=breadth`
   - `expectedTradeDate/observedTradeDate/lagDays/status/note`
3. debug 输出：
   - 仅 `debug=1` 返回；
   - 生产环境禁用。
4. 异常码（拟定）：
   - `BR_SOURCE_EMPTY`
   - `BR_SOURCE_DELAYED`
   - `BR_QUERY_FAILED`
   - `BR_HISTORY_INCOMPLETE`

---

## 7. 性能与缓存策略

1. 性能预算：P95 < 200ms（单日聚合 + 62 日历史聚合）。
2. 首版策略：无 Redis；依赖聚合 SQL + 交易日裁剪。
3. 二期缓存（可选）：`wealth:breadth:{market}:{tradeDate}`。
4. 一致性：按交易日失效。

---

## 8. 安全与权限

1. 鉴权依赖：沿用 `quote.read`（本期固定）。
2. 权限点：已登录且具备行情读取权限可访问。
3. 防误用策略：
   - 禁止非法 market；
   - 禁止非法 date 格式；
   - debug 输出生产禁用。

---

## 9. 测试与验证计划

1. 单元测试：
   - `redRate` 计算正确；
   - `1m/3m` 点数固定；
   - 趋势线只包含 up/down。
2. 集成测试：
   - 正常/延迟/空数据/异常场景。
3. 冒烟验证：
   - 返回结构稳定；
   - 面板切换 `1m/3m` 可正常渲染；
   - 真实源请求 pending 时显示 loading（不展示 mock breadth）；
   - 真实源请求超过 5 秒显示 error；
   - 平盘卡副文案显示 `平盘率 x%`；
   - 纵轴刻度固定 `0/1500/3000/4500/6000` 且无负值刻度。
4. 失败回滚与观测：
   - 查询失败只影响本模块，不阻断整页响应。
5. 范围约束验证：
   - 本轮只允许 `breadth` 模块切到 `real`；
   - 其他模块 source 保持原值不变。

---

## 10. 分期里程碑

1. M1（方案冻结）：定义对象、查询、状态、异常冻结。
2. M2（后端实现）：模块接口 + 查询 + 状态异常落地。
3. M3（前端接入）：按现有 `MarketBreadthPanel` 结构接入，不改样式。
4. M4（回归发布）：联调、性能回归、灰度验收。

---

## 11. 风险与缓解

1. 风险：历史点不足导致趋势图断裂。  
   缓解：返回实际点并标记 `BR_HISTORY_INCOMPLETE`（debug）。
2. 风险：交易日口径错误导致“自然日空洞”。  
   缓解：严格以 `trade_calendar(is_open=1)` 作为历史日集。
3. 风险：模块被误接入策略配置中心导致复杂化。  
   缓解：在门禁文档明确“本模块无配置化能力”。

---

## 12. 已确认清零项

1. 本模块无配置能力，不接策略配置中心。
2. 仅支持 `1个月/3个月` 两档范围。
3. UI 样式与交互保持现状，不做变更。
4. 统计口径已拍板：`equity_daily_bar` 全量样本口径，`pct_chg` 为空不计入。
5. 本模块接入真实 API 时，必须遵守 `loading -> ready`、`timeout(5s) -> error`，且 timeout/error 不允许回填 mock 数据。
6. 本轮仅允许 `breadth` 模块 source 从 `mock` 切到 `real`，其余模块 source 必须保持原值不变。
7. 本轮无未决拍板项。
8. 平盘家数卡片副文案统一为 `平盘率 x%`。
9. 纵轴刻度固定为 `0/1500/3000/4500/6000`，纵轴下限为 `0`。

---

## 13. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-08 | 首版：冻结涨跌分布模块实现边界与查询策略 | Codex |
| v1.1 | 2026-05-09 | 对齐模块交付清单：补充真实源 loading/error 行为门禁、5 秒超时语义与单模块 source 切换约束 | Codex |
| v1.2 | 2026-05-09 | 对齐实现修复：补充平盘率副文案与固定纵轴刻度 0/1500/3000/4500/6000 | Codex |
