# 市场总览｜今日市场客观总结技术实施方案 v1（implementation-design）

> 用途：把“今日市场客观总结”需求文档转成可实施技术方案。  
> 阶段：编码前。  
> 产物性质：实现设计基线（不写业务代码）。

---

## 1. 文档目的

1. 对应需求文档：  
   [market-summary-benchmark-requirement-v1.md](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/market-summary-benchmark-requirement-v1.md)
2. 本文目标：冻结“后端配置、前端纯展示”的实现落位、查询链路、状态与异常语义。
3. 本文不做：不写业务代码，不改前端页面样式，不扩展其他模块。

关联门禁：  
[market-summary-m2-coding-gate-v1.md](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/market-summary-m2-coding-gate-v1.md)

---

## 2. 代码现状审计（必须基于真实代码）

1. 路由聚合位于 [router.py](/Users/congming/github/goldenshare/src/app/api/v1/router.py)，支持继续挂载 `src.biz.api.wealth.market.*`。
2. 可复用数据表模型已存在：
   - [equity_daily_bar.py](/Users/congming/github/goldenshare/src/foundation/models/core_serving/equity_daily_bar.py)
   - [market_moneyflow_dc.py](/Users/congming/github/goldenshare/src/foundation/models/core/market_moneyflow_dc.py)
   - [limit_list_ths.py](/Users/congming/github/goldenshare/src/foundation/models/core/limit_list_ths.py)
   - [trade_calendar.py](/Users/congming/github/goldenshare/src/foundation/models/core/trade_calendar.py)
3. 现有冲突与技术债：
   - 现有页面基线里“固定 5 卡”表述较多，和“5/6 后端可配”有口径冲突，需以本模块文档为准同步收敛。
   - 现有前端曾存在“真实 API 返回前先渲染 mock summary”的行为，和模块真实态加载语义冲突（本次收敛为 loading/error/ready 三态）。
   - 主要指数首卡历史上输出过“上涨/总数”，已收敛为“上涨:下跌”。
4. 结论：
   - Summary 模块单独落 `src/biz` 模块化目录；
   - Overview 聚合后续只消费该模块 DTO，不自行拼字段。
   - 指数上涨数量由 summary 模块独立查询与计算，不复用主要指数模块内部产物。

---

## 3. 分层架构与目录落点

### 3.1 接口范围

1. 模块接口路径：`GET /api/v1/wealth/market/summary`。
2. 是否整页聚合接口：否（模块接口）。
3. 模块返回范围：只返回 `marketSummary` 及本模块状态，不返回榜单/板块等对象。

### 3.2 代码目录模板（按模块拆分）

```text
src/biz/
  api/
    wealth/
      market/
        summary.py
  queries/
    wealth/
      market/
        summary/
          summary_metrics_query.py
          summary_state_query.py
          summary_query_service.py
  schemas/
    wealth/
      market/
        summary.py
  services/
    wealth/
      market/
        summary/
          config/
            market_summary_text_templates.json
          summary_definition_registry.py
          summary_card_builder.py
          summary_text_renderer.py
          summary_status_resolver.py
          summary_exception_builder.py
```

---

## 4. 数据流与执行链路

1. 请求入口：`api.wealth.market.summary`。
2. 参数校验：`market/tradeDate/debug`。
3. 配置装载：`summary_definition_registry` 读取当前生效配置（`cardCount=5|6`、卡片顺序、文本模板）。
4. 指标查询：`summary_query_service` 汇总卡片所需事实值。
5. 卡片构建：`summary_card_builder` 按配置输出 `cards[]`（不由前端参与）。
6. 文案渲染：`summary_text_renderer` 用后端模板生成 `textCard.content`（盘中/盘后分版本）。
7. 状态归并：`summary_status_resolver` 产出模块状态与页面态映射输入。
8. 异常组装：`summary_exception_builder` 仅使用注册表异常码。
9. 响应输出：`schemas.wealth.market.summary` DTO。
10. 前端渲染态：真实 API 场景下，`MarketSummaryPanel` 只接受真实返回；返回前 `loading`，5 秒超时或请求失败 `error`，成功后 `ready`。

### 4.1 文案模板装载与渲染流程（冻结）

1. 模板文件位置：  
   `src/biz/services/wealth/market/summary/config/market_summary_text_templates.json`
2. 装载策略：`summary_definition_registry` 首次请求懒加载并缓存模板。
3. 选择规则：按 `sessionStatus` 选择模板：
   - `PRE_OPEN/TRADING/BREAK -> objective_intraday_v1`
   - `CLOSED -> objective_close_v1`
4. 变量来源：统一由 `summary_query_service` 计算并传入 renderer。
5. 渲染方式：仅占位符替换（`{var}`），不允许拼接自由文本。
6. 校验与降级：
   - 模板变量缺失 -> `MS_TEXT_RENDER_FAILED` + fallback 文案；
   - 命中禁用词 -> `MS_TEXT_RENDER_FAILED` + fallback 文案；
   - 超长 -> 按门禁策略截断 content。

---

## 5. 查询编排策略

1. 主查询（事实汇总）：
   - `equity_daily_bar`：上涨/下跌/平盘计数 + 成交额汇总；
   - `market_moneyflow_dc`：净流入/流出；
   - `limit_list_ths`：涨停池/跌停池/炸板池数量（按 `ts_code` 去重）。
2. 辅助查询（交易日状态）：
   - `trade_calendar`：`tradeDate/prevTradeDate/isOpen`。
3. 主要指数涨跌比：
   - 由 summary 模块独立查询“10 指数行情”并计算上涨数与下跌数；
   - 对外卡片值固定为 `up:down`（如 `2:8`），副文案固定为“上涨数量:下跌数量”；
   - 不依赖主要指数模块内部数据结构，避免模块内耦合脆弱性。
4. 回退查询：
   - 不做跨日回退补值（避免“旧数据冒充最新”）；只做 delayed 标记。
5. 去重、排序、截断：
   - 本模块不涉及榜单行排序，仅按配置顺序输出卡片。
6. 空数据与异常处理：
   - 单卡源为空：该卡 `value=null` + 模块异常；
   - 全量关键源不可用：模块 `ERROR/EMPTY`。
7. 文案模板策略：
   - 模板按 `sessionStatus` 分版本（盘中/盘后）；
   - 首版不做自动文案生成，仅做模板渲染。

### 5.1 文案模板配置结构（冻结）

```json
{
  "version": "1.0.0",
  "templates": [
    {
      "templateKey": "objective_intraday_v1",
      "sessionStatuses": ["PRE_OPEN", "TRADING", "BREAK"],
      "titleTemplate": "截至当前时点，A 股主要指数{majorIndexTone}。",
      "contentTemplate": "当前上涨家数{upDownTone}下跌家数，成交活跃度较上一交易日同时段{turnoverTone}；涨停{limitUpDownTone}跌停。大盘资金当前为{fundFlowTone}。以下为客观事实快照，不构成交易建议。"
    },
    {
      "templateKey": "objective_close_v1",
      "sessionStatuses": ["CLOSED"],
      "titleTemplate": "截至收盘，A 股主要指数{majorIndexTone}。",
      "contentTemplate": "全市场上涨家数{upDownTone}下跌家数，成交额较上一交易日{turnoverTone}；涨停{limitUpDownTone}跌停。大盘资金今日为{fundFlowTone}，资金分布呈现{flowPatternTone}。本卡片仅描述客观事实，不构成交易建议。"
    }
  ],
  "fallback": {
    "title": "今日市场客观总结",
    "content": "当前可用数据不足，暂仅展示已确认的客观事实。"
  },
  "policy": {
    "forbiddenWords": ["买入", "卖出", "加仓", "减仓", "抄底", "止盈", "止损", "明日", "预测"],
    "maxTitleChars": 36,
    "maxContentChars": 220
  }
}
```

---

## 6. 状态与异常落地

1. `pageStatus` 归并：
   - 模块 `READY` -> 页面可 `READY`；
   - 模块 `DELAYED/EMPTY/ERROR` -> 页面至少 `PARTIAL`。
2. `moduleStatus`（debug）：
   - `moduleKey=marketSummary`；
   - 返回 `expectedTradeDate/observedTradeDate/lagDays/status/note`。
3. debug 输出结构：
   - `debugInfo.modules[]`；
   - `debugInfo.exceptions[]`。
4. 异常码映射（拟定）：
   - `MS_CONFIG_MISSING`
   - `MS_CARD_COUNT_INVALID`
   - `MS_SOURCE_DELAYED`
   - `MS_SOURCE_EMPTY`
   - `MS_TEXT_RENDER_FAILED`

> 上述异常码在编码前必须先登记到异常码注册表。

---

## 7. 性能与缓存策略

1. 性能预算：P95 < 250ms（模块单接口）。
2. 首版策略：无 Redis，先 SQL 聚合 + 最小列读取。
3. 二期缓存策略（可选）：`wealth:summary:{market}:{tradeDate}:{definitionKey}`。
4. 一致性策略：按 `tradeDate` 维度缓存失效，切换交易日自动冷启动。

---

## 8. 安全与权限

1. 鉴权依赖：沿用 wealth 行情读取权限（与市场总览同口径）。
2. 权限点：仅登录且有行情读取权限用户可访问。
3. 防误用策略：
   - `market` 非法值拒绝；
   - `tradeDate` 非法格式拒绝；
   - `debug` 仅受控环境开放明细。

---

## 9. 测试与验证计划

1. 单元测试：
   - `cardCount` 仅允许 5/6；
   - 卡片构建按配置顺序输出；
   - 文本模板渲染不含主观词；
   - 盘中/盘后模板选择正确。
2. 集成测试：
   - 默认 5 卡响应；
   - 6 卡配置响应；
   - delayed/partial/error 样例。
3. 冒烟验证：
   - `/api/v1/wealth/market/summary` 返回结构完整；
   - 前端在 5/6 两种卡片数下布局正确；
   - 前端真实源场景下 “loading -> ready” 与 “5s timeout -> error” 行为正确，不出现 mock summary 回填。
4. 失败回滚与观测点：
   - 配置异常时降级空卡并输出结构化异常；
   - 不影响其他模块接口。

---

## 10. 分期里程碑

1. M1（方案冻结）：冻结对象、字段、状态、异常码草案。
2. M2（后端实现）：模块 API + 查询 + 配置驱动 + 状态异常。
3. M3（前端接入）：前端按 `cards[]` 与 `textCard` 纯渲染，支持 5/6 布局。
4. M4（回归发布）：模块联调、性能回归、debug 验收。

---

## 11. 风险与缓解

1. 风险：配置与数据源口径不一致导致卡片“有定义无数据”。  
   缓解：编码门禁必须冻结“配置键 -> 源字段”映射矩阵。
2. 风险：文本模板混入主观表述。  
   缓解：模板词库白名单 + review gate。
3. 风险：卡片数改为 6 时布局走样。  
   缓解：在门禁中冻结 5/6 两套布局样例并做视觉对比。

---

## 12. 已确认清零项

1. 默认 5 卡，第 6 卡默认关闭。
2. 文案按盘中/盘后分版本。
3. 指数上涨数量由 summary 独立查询，不复用主要指数模块内部产物。
4. 本轮无未决拍板项，可进入编码门禁执行。

---

## 13. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-08 | 首版：冻结 summary 模块后端配置驱动实施方案 | Codex |
