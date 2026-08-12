# 市场总览｜板块速览技术实施方案 v1（implementation-design）

> 历史状态：本文只解释当前 V1 实现；V2 技术方案见 [sector-overview-implementation-design-v2.md](./sector-overview-implementation-design-v2.md)，禁止在 V1 上继续叠加。
> 用途：把“板块速览”需求文档转成可实施技术方案。  
> 阶段：编码前。  
> 产物性质：实现设计基线（不写业务代码）。

---

## 1. 文档目的

1. 对应需求文档：  
   [sector-overview-benchmark-requirement-v1.md](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/sector-overview-benchmark-requirement-v1.md)
2. 本文目标：冻结板块速览模块的接口、查询、状态、异常与前端接入方案。
3. 本文不做：不落业务代码，不修改页面视觉，不接入 THS 或 raw 表实时拼接。
4. 跨模块抽象门禁原则适配结论：本模块全量适用 8 条原则，落点见 `1.1`。

关联门禁：  
[sector-overview-m2-coding-gate-v1.md](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/sector-overview-m2-coding-gate-v1.md)

---

## 1.1 跨模块抽象门禁原则适配（必填）

| 原则 | 本模块结论 | 设计落点 | 计划测试 |
|---|---|---|---|
| 事实源单一原则 | 适用；板块事实来自 DC 组合源，且每类字段只有一个主源 | 查询层只允许 `dc_daily/board_moneyflow_dc/dc_index` | 集成测试断言字段来源 |
| 契约先行与冻结原则 | 适用；先冻结 `SectorOverviewResponse` | `schemas.wealth.market.sector_overview` | 契约字段断言 |
| 配置一致性原则 | 适用；本期无策略配置中心配置 | 固定列定义与热力图规则 | 测试确认请求不能覆盖列定义 |
| 默认行为显式原则 | 适用；默认交易日与显式交易日路径分开 | API 参数与状态 resolver | 默认/显式日期用例 |
| 排序与筛选确定性原则 | 适用；category/content_type/idx_type、排序、空值处理固定 | 查询 SQL + service 排序 | 同分排序与空值剔除测试 |
| 性能预算前置原则 | 适用；结果集小但需 SQL 下推 | 单日查询 + 排序截断 | 端到端耗时记录 |
| 可观测与异常标准化原则 | 适用；`SO_*` 异常码 | exception builder + debugInfo | delayed/empty/error 分支测试 |
| 测试以用户可见结果为中心原则 | 适用；8 列 + 20 热力格为主断言 | 前端真实 API smoke | 页面可见字段校验 |

---

## 2. 代码现状审计（必须基于真实代码）

1. 当前前端模块：
   - [SectorOverviewPanel.tsx](/Users/congming/github/goldenshare/wealth/src/features/market-overview/sectors/SectorOverviewPanel.tsx)
   - 当前仍消费整页 mock `overview.sectors.columns/heatmap`。
2. 当前模块 source：
   - [moduleSources.ts](/Users/congming/github/goldenshare/wealth/src/features/market-overview/api/moduleSources.ts) 中 `sectors: "mock"`。
3. 当前 mock 类型：
   - [marketOverviewTypes.ts](/Users/congming/github/goldenshare/wealth/src/features/market-overview/api/marketOverviewTypes.ts) 中 `SectorRankRow/SectorColumn/HeatCell` 仍是旧 mock 轻量结构。
4. 当前原型事实：
   - [market-overview-v1.1.html](/Users/congming/github/goldenshare/wealth/docs/reference/showcase/market-overview-v1.1.html) 固定左 `4x2`、右 `5x4`。
5. 当前数据源：
   - [dc_daily.py](/Users/congming/github/goldenshare/src/foundation/models/core/dc_daily.py)
   - [board_moneyflow_dc.py](/Users/congming/github/goldenshare/src/foundation/models/core/board_moneyflow_dc.py)
   - [dc_index.py](/Users/congming/github/goldenshare/src/foundation/models/core/dc_index.py)
   - [board_hotspot.py](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/board_hotspot.py)
   - [moneyflow.py](/Users/congming/github/goldenshare/src/foundation/datasets/definitions/moneyflow.py)
   - Tushare 文档：[0382_东财概念板块行情.md](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/打板专题数据/0382_东财概念板块行情.md)
   - Tushare 文档：[0344_东财概念及行业板块资金流向（DC）.md](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/资金流向数据/0344_东财概念及行业板块资金流向（DC）.md)
   - Tushare 文档：[0362_东方财富概念板块.md](/Users/congming/github/goldenshare/docs/sources/tushare/股票数据/打板专题数据/0362_东方财富概念板块.md)
6. 现有冲突与技术债：
   - 当前 UI 有“资金流入/流出前五”，必须由 `board_moneyflow_dc` 承接，不能从 `dc_index` 或 `dc_daily` 伪造。
7. 结论：
   - 板块速览落在 `src/biz/**` 模块化 API；
   - 前端新增 sectors provider/view-model adapter；
   - 当前 `SectorOverviewPanel` 不继续直接吃整页 `MarketOverview`；
   - 三源字段分工必须写死，不允许实现时临场发挥。

---

## 3. 分层架构与目录落点

### 3.1 接口范围

1. 模块接口路径：`GET /api/v1/wealth/market/sector-overview`
2. 是否整页聚合接口：否（模块接口）
3. 模块接口返回范围：仅 `sectorOverview` 模块对象与必要状态字段

### 3.2 代码目录模板（按模块拆分）

```text
src/biz/
  api/
    wealth/
      market/
        sector_overview.py
  queries/
    wealth/
      market/
        sector_overview/
          sector_overview_query.py
          sector_overview_query_service.py
          sector_overview_state_query.py
  schemas/
    wealth/
      market/
        sector_overview.py
  services/
    wealth/
      market/
        sector_overview/
          sector_overview_status_resolver.py
          sector_overview_exception_builder.py
          sector_overview_column_registry.py

wealth/src/features/market-overview/
  sectors/
    SectorOverviewPanel.tsx
    api/
      marketSectorOverviewApi.ts
      marketSectorOverviewAdapter.ts
```

---

## 4. 数据流与执行链路

1. 请求入口：`api.wealth.market.sector_overview`
2. 参数校验：`market/tradeDate/debug`
3. 查询编排：
   - 解析目标交易日；
   - 查询 `dc_daily`、`board_moneyflow_dc`、`dc_index` 目标/观测交易日板块行；
   - 构建左侧榜单列；
   - 构建右侧热力图 20 格。
4. 状态归并：`sector_overview_status_resolver`
5. 异常组装：`sector_overview_exception_builder`
6. 响应输出：`schemas.wealth.market.sector_overview`
7. 前端行为：
   - real API pending -> `loading`
   - 成功 -> `ready`
   - 5 秒超时或请求失败 -> `error`
   - 禁止 mock fallback

### 4.1 前端接入链路（必须显式落地）

```text
MarketOverviewPage
  -> sectors provider
  -> SectorOverviewResponseData
  -> SectorOverviewPanelViewModel
  -> SectorOverviewPanel
```

前端规则：

1. `SectorOverviewPanel` 不再直接接收整页 `MarketOverview`。
2. sectors provider 只请求 `/api/v1/wealth/market/sector-overview`。
3. adapter 只做 DTO 到 ViewModel 的展示格式转换，不做排序、不做业务筛选。
4. 未接真实 API 前展示 loading，不允许用 mock 数据冒充 ready。

---

## 5. 查询编排策略

### 5.1 主查询

主行情来源表：`core_serving.dc_daily`

筛选：

1. `trade_date = :observed_trade_date`
2. `category in ('行业板块', '概念板块', '地域板块')`
3. `ts_code is not null`

字段：

```text
ts_code, trade_date, category, close, change,
pct_change, amount, turnover_rate, swing
```

结构补充来源表：`core_serving.dc_index`

字段：

```text
ts_code, trade_date, name, leading, leading_code,
leading_pct, total_mv, up_num, down_num, idx_type, level
```

资金流来源表：`core_serving.board_moneyflow_dc`

字段：

```text
trade_date, content_type, ts_code, name, pct_change,
close, net_amount, net_amount_rate, rank
```

### 5.2 左侧榜单列

已冻结 8 列：

| columnKey | 标题 | 分类 | 指标 | 排序 |
|---|---|---|---|---|
| `industryTopGainers` | 行业涨幅前五 | 行业板块 | `dc_daily.pct_change` | `pct_change desc nulls last, ts_code asc` |
| `conceptTopGainers` | 概念涨幅前五 | 概念板块 | `dc_daily.pct_change` | `pct_change desc nulls last, ts_code asc` |
| `regionTopGainers` | 地域涨幅前五 | 地域板块 | `dc_daily.pct_change` | `pct_change desc nulls last, ts_code asc` |
| `fundIn` | 资金流入前五 | 行业/概念/地域 | `board_moneyflow_dc.net_amount` | `net_amount desc nulls last, ts_code asc` |
| `industryTopLosers` | 行业跌幅前五 | 行业板块 | `dc_daily.pct_change` | `pct_change asc nulls last, ts_code asc` |
| `conceptTopLosers` | 概念跌幅前五 | 概念板块 | `dc_daily.pct_change` | `pct_change asc nulls last, ts_code asc` |
| `regionTopLosers` | 地域跌幅前五 | 地域板块 | `dc_daily.pct_change` | `pct_change asc nulls last, ts_code asc` |
| `fundOut` | 资金流出前五 | 行业/概念/地域 | `board_moneyflow_dc.net_amount` | `net_amount asc nulls last, ts_code asc` |

字段补充：

1. 涨跌榜主体名称优先从同日 `dc_index` 按 `ts_code + trade_date` 补齐；缺失则只展示代码。
2. 资金流榜主体名称优先使用 `board_moneyflow_dc.name`。
3. `content_type=行业/概念/地域` 映射为 `INDUSTRY/CONCEPT/REGION`。

### 5.3 右侧热力图

规则：

1. 从 `dc_daily` 三类板块全集中选取 `abs(pct_change)` 最大的 20 个板块；
2. 排序：`abs(pct_change) desc nulls last, pct_change desc nulls last, ts_code asc`；
3. 返回 20 个 `SectorHeatMapItem`；
4. 少于 20 个时返回现有数量，并标记模块 `PARTIAL`。

### 5.4 状态查询

1. 默认请求：
   - `expectedTradeDate` 由系统盘后口径推导；
   - `observedTradeDate` 取 `dc_daily`、`board_moneyflow_dc`、`dc_index` 三个必需源在 `expectedTradeDate` 之前的共同可用日期，避免同一模块混用不同交易日事实。
2. 显式 `tradeDate`：
   - 只查询该交易日；
   - 无数据返回 `EMPTY`，不自动回退旧日期。

### 5.5 空数据与异常处理

1. 必需 DC 组合源无任何目标/观测日数据：`EMPTY + SO_SOURCE_EMPTY`。
2. 观测日期落后：`DELAYED + SO_SOURCE_DELAYED`。
3. 列指标不可由已冻结 DC 组合源产出：`ERROR + SO_COLUMN_METRIC_UNAVAILABLE`，不得伪造数据。
4. SQL/服务异常：`ERROR + SO_QUERY_FAILED`。

### 5.6 辅助查询（补列/补名）

1. 本期只允许同一交易日、同一 `ts_code` 下的 DC 组合源内部补充：
   - `dc_daily` 涨跌榜与热力图行可从 `dc_index` 补充 `name/up_num/down_num/leading/leading_code/leading_pct`；
   - `board_moneyflow_dc` 资金流榜优先使用本表 `name`，必要时可从同日 `dc_index` 补充结构信息。
2. 禁止跨到 THS、个股主数据或 raw 表补字段。
3. `name` 最终仍缺失时不继续查其他表，前端展示代码。

### 5.7 回退查询

1. 本期无回退查询。
2. 源缺失通过 `EMPTY/DELAYED/PARTIAL/ERROR` 表达。

---

## 6. 状态与异常落地

1. `pageStatus`：沿用整页归并规则。
2. `moduleStatus`（debug）：
   - `moduleKey=sectorOverview`
   - `expectedTradeDate`
   - `observedTradeDate`
   - `lagDays`
   - `status`
   - `note`
3. debug 输出：
   - 仅 `debug=1` 返回；
   - 生产环境禁用。
4. 异常码：
   - `SO_SOURCE_DELAYED`
   - `SO_SOURCE_EMPTY`
   - `SO_COLUMN_METRIC_UNAVAILABLE`
   - `SO_QUERY_FAILED`

---

## 7. 性能与缓存策略

1. 性能预算：P95 `< 300ms`。
2. 返回体大小预算：`< 80KB`。
3. 首版策略：无 Redis，三张 DC serving 表按同一交易日查询，应用层只做小结果集分组。
4. 二期缓存（可选）：
   - key：`wealth:sector-overview:{market}:{observedTradeDate}`
5. 一致性：按交易日快照失效；盘后数据稳定后可缓存。

---

## 8. 安全与权限

1. 鉴权依赖：沿用 `quote.read`。
2. 权限点：不新增独立权限点。
3. 防误用策略：
   - 非 `CN_A` 直接拒绝；
   - `tradeDate` 非法格式直接拒绝；
   - 请求不接受列定义、排序字段或 `idx_type` 覆盖参数。

---

## 9. 测试与验证计划

1. 单元测试：
   - `category/content_type/idx_type` 映射；
   - 列定义合法性；
   - `pct_change` 与 `net_amount` 排序；
   - 状态 resolver；
   - exception builder。
2. 集成测试：
   - `GET /api/v1/wealth/market/sector-overview` 正常返回；
   - `debug=1` 返回 `sectorOverview` 模块状态；
   - DC 组合源空数据、延迟、查询失败分支。
3. 冒烟验证：
   - 前端 loading/ready/error；
   - 左侧 8 列；
   - 每列最多 5 行；
   - 右侧 20 个热力格；
   - 不展示 mock fallback。
4. 失败回滚与观测点：
   - 本轮只允许 `sectors` 模块 source 从 mock 切 real；
   - 失败时切回 `sectors: "mock"`，不影响其他模块。

### 9.1 核心测试 case（必填）

1. 核心字段清单：
   - `tradeDate`
   - `columns[].columnKey/title/metricLabel/tone`
   - `columns[].rows[].rank`
   - `columns[].rows[].subject.subjectCode/subjectName/sectorType`
   - `columns[].rows[].metric.value/displayText/direction`
   - `heatMapItems[].subject.subjectCode/subjectName/sectorType`
   - `heatMapItems[].changePct/direction`
   - `debugInfo.modules[]`
   - `debugInfo.exceptions[]`
2. 后端真实 API 集成测试：
   - 走真实路由；
   - 禁止 mock service/query；
   - 断言涨跌榜主指标来自 `dc_daily`；
   - 断言资金流榜主指标来自 `board_moneyflow_dc`；
   - 断言结构补充字段来自 `dc_index`。
3. 前端真实 API 展示校验：
   - 禁用 mock adapter；
   - 验证 8 列标题、Top5 行、20 热力格、loading/error。
4. 执行命令与通过标准：
   - 后端：`pytest -q tests/web/test_wealth_market_sector_overview_api.py`
   - 前端：`cd wealth && npm run test -- market-overview-sector-overview-real-api`
   - 通过标准：核心字段与页面可见要素一一对应。

---

## 10. 分期里程碑

1. M1（方案冻结）：三件套评审通过，DC 组合源口径冻结。
2. M2（后端实现）：API、schema、query、status、exception 落地。
3. M3（前端接入）：provider + adapter + panel props 改造，保持视觉不变。
4. M4（回归发布）：真实 API 测试、页面 smoke、性能验证。

---

## 11. 风险与缓解

1. 风险：三源日期不一致导致模块混用不同交易日事实。  
   触发条件：默认请求时各源 latest trade_date 不一致。  
   缓解动作：默认路径以三源共同可用日期作为观测日期，并在 debug 标记 delayed。
2. 风险：`category/content_type/idx_type` 实值写错导致接口成功但全空。  
   触发条件：用英文枚举或历史印象写筛选。  
   缓解动作：使用真实文档和源数据实值，测试覆盖。
3. 风险：同分排序不稳定导致页面快照漂移。  
   触发条件：只按主指标排序。  
   缓解动作：固定 `ts_code asc` 次排序。
4. 风险：前端继续消费整页 mock 结构。  
   触发条件：未拆 provider/adapter。  
   缓解动作：M3 强制 `SectorOverviewPanelViewModel`。

---

## 12. 已确认清零项

1. 已确认：板块速览使用 `dc_daily + board_moneyflow_dc + dc_index` 的 DC 组合源。
2. 已确认：保留原型“资金流入前五 / 资金流出前五”，主指标来自 `board_moneyflow_dc.net_amount`。
3. 当前无待拍板项。

---

## 13. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-13 | 首版：冻结板块速览 DC 组合源实现方案 | Codex |
