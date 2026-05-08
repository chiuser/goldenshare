# 市场总览｜榜单技术实施方案 v1（implementation-design）

> 用途：把榜单需求文档转成可实施技术方案。  
> 阶段：编码前。  
> 产物性质：实现设计基线（不写业务代码）。

---

## 1. 文档目的

1. 对应需求文档：  
   [leaderboard-benchmark-requirement-v1.md](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/leaderboard-benchmark-requirement-v1.md)
2. 本文目标：冻结榜单模块实现落点、查询编排、状态与异常链路。
3. 本文不做：不落业务代码，不实现真实接口，不改前端页面。

关联门禁：  
[leaderboard-m2-coding-gate-v1.md](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/leaderboard-m2-coding-gate-v1.md)

---

## 2. 代码现状审计（必须基于真实代码）

1. 当前路由聚合位于 `src/app/api/v1/router.py`，已承接 `src.biz.api.*`。
2. `src/biz` 已具备 `api/queries/schemas/services` 分层，可承接 wealth 模块化 API。
3. 可复用数据表：`trade_calendar/equity_daily_bar/equity_daily_basic/dc_hot/security_serving`。
4. 现有冲突与技术债：
   - `src/biz` 下历史存在扁平文件组织习惯，需严格按模块分层收敛。
5. 结论：榜单能力落在 `src/biz`，不放入 `src/app`、`src/ops`。

---

## 3. 分层架构与目录落点

### 3.1 接口范围

1. 模块接口路径：`GET /api/v1/wealth/market/leaderboards`。
2. 是否整页聚合接口：否（模块接口）。
3. 返回范围：仅榜单模块对象，不返回整页 overview 聚合包。

### 3.2 代码目录模板（按模块拆分）

```text
src/biz/
  api/
    wealth/
      market/
        leaderboards.py
  queries/
    wealth/
      market/
        leaderboards/
          stock_pool_query.py
          equity_rankings_query.py
          dc_hot_rankings_query.py
          leaderboards_query_service.py
  schemas/
    wealth/
      market/
        leaderboards.py
  services/
    wealth/
      market/
        leaderboards/
          definition_registry.py
          status_resolver.py
          exception_builder.py
```

---

## 4. 数据流与执行链路

1. 请求入口：`api/wealth/market/leaderboards.py`。
2. 参数校验：`market/tradeDate/limit/boardKeys/debug` 统一校验。
3. 查询编排：`leaderboards_query_service.py` 调用 stock pool + equity rankings + dc_hot rankings。
4. 状态归并：`status_resolver.py` 产出 board 状态与 pageStatus。
5. 异常组装：`exception_builder.py` 按注册表产出 `LB_*`。
6. 响应输出：`schemas/.../leaderboards.py` DTO 返回。

---

## 5. 查询编排策略

1. 主查询（主链路）：
   - 行情榜（5 类）：`equity_daily_bar` 主集 + `equity_daily_basic` 补列。
   - 热榜（2 类）：`dc_hot` 主集。
2. 辅助查询（补列/补名）：
   - `security_serving` 名称兜底。
3. 回退查询（可选）：
   - 仅 `dc_hot` 使用 strict/fallback 规则。
4. 去重、排序、截断：
   - 每榜按本榜排序字段排序，截断 `limit`。
5. 空数据与异常处理：
   - 空数据 -> `EMPTY/DELAYED`（视规则）。
   - 查询失败 -> `ERROR + LB_QUERY_FAILED`。

---

## 6. 状态与异常落地

1. `pageStatus` 归并：`READY/PARTIAL/DELAYED/EMPTY/ERROR`。
2. `moduleStatus` 归并：每榜 `expectedTradeDate/observedTradeDate/lagDays/status/note`。
3. debug 输出结构：`debugInfo.modules + debugInfo.exceptions`（仅 `debug=1`）。
4. 异常码映射：只允许使用  
   [exception-code-registry.md](/Users/congming/github/goldenshare/wealth/docs/system/exception-code-registry.md) 中的 `LB_*`。

---

## 7. 性能与缓存策略

1. 性能预算：P95 < 400ms（同机房 DB，默认 limit=10）。
2. 首版策略：先无 Redis，仅 SQL + 索引 + 轻量 CTE。
3. 二期缓存策略：`wealth:leaderboards:{tradeDate}:{limit}:{strict}`（可选）。
4. 失效与一致性：按交易日口径失效；盘后可放宽 TTL。

---

## 8. 安全与权限

1. 鉴权依赖：复用 `quote.read`（或后续独立 wealth 权限点，需拍板）。
2. 权限点：仅已登录且具备行情读取权限用户可访问（按现有 auth 体系）。
3. 防误用策略：
   - 限制 `limit` 范围；
   - 非法 `boardKeys` 拒绝；
   - debug 输出仅开发/受控环境开放（实现时按环境开关）。

---

## 9. 测试与验证计划

1. 单元测试：
   - 定义注册表一致性；
   - 状态归并规则；
   - 异常组装规则。
2. 集成测试：
   - 7 榜单基础返回；
   - strict/fallback 两分支；
   - 空数据/延迟/异常覆盖。
3. 冒烟验证：
   - 调用 `/leaderboards` 返回结构完整；
   - debug=0/1 分支正确。
4. 失败回滚与观测点：
   - 查询失败只影响模块，不阻断整体请求；
   - 记录 `traceId` 与异常码。

---

## 10. 分期里程碑

1. M1（方案冻结）：冻结规则、字段、状态、异常码。
2. M2（后端实现）：通过 coding-gate 后实现 API、查询、状态、异常。
3. M3（前端接入）：按 definitions/schema 驱动渲染。
4. M4（回归发布）：联调、性能回归、上线清单。

---

## 11. 风险与缓解

1. 风险：`dc_hot` 日期落后导致榜单体验不稳定。  
   缓解：strict/fallback 双模式 + delayed 显示。
2. 风险：名称缺失导致前端展示不完整。  
   缓解：后端允许空名，前端降级显示代码。
3. 风险：前端自行拼装规则导致口径漂移。  
   缓解：definitions + columnSchema 驱动。

---

## 12. 待拍板项

1. wealth 模块是否新增独立权限点（替代复用 `quote.read`）。
2. debug 模式在生产环境是否完全禁用（建议禁用）。

---

## 13. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-08 | 按模板重构实施方案结构，冻结模块实现落点 | Codex |
