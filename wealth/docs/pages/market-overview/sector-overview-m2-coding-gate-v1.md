# 市场总览｜板块速览 M2 编码前门禁 v1

> 历史状态：仅保留为当前 V1 交付记录；V2 开工门禁见 [sector-overview-m2-coding-gate-v2.md](./sector-overview-m2-coding-gate-v2.md)。
> 用途：在编码前锁定板块速览模块的参数、响应、查询、状态、异常、性能与签字清单。  
> 阶段：M2 开工前。  
> 产物性质：执行门禁清单（不通过不允许编码）。

关联文档：

1. [板块速览标杆需求 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/sector-overview-benchmark-requirement-v1.md)
2. [板块速览技术实施方案 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/sector-overview-implementation-design-v1.md)

---

## 1. 目的

1. 本门禁对应模块：`sectorOverview`
2. 本门禁对应需求文档：`sector-overview-benchmark-requirement-v1.md`
3. 本门禁对应实施方案：`sector-overview-implementation-design-v1.md`

---

## 2. 总门禁清单（全通过才能开工）

1. [ ] `dc_daily + board_moneyflow_dc + dc_index` DC 组合源口径冻结完成
2. [ ] `fundIn/fundOut` 两列使用 `board_moneyflow_dc.net_amount` 的方案冻结完成
3. [ ] 请求参数与默认值冻结完成
4. [ ] 响应对象字段冻结完成（含 debug 结构）
5. [ ] 8 列榜单样例响应通过评审
6. [ ] 20 格热力图样例响应通过评审
7. [ ] 查询草案通过评审
8. [ ] 状态归并样例通过评审
9. [ ] 异常码全部来自异常码注册表，无游离异常码
10. [ ] 性能预算与降级策略明确
11. [ ] 前端真实源加载态门禁冻结（loading/ready/error）
12. [ ] 5 秒超时进入 error 且不展示 mock 回填的行为门禁冻结
13. [ ] 本轮仅 sectors 模块切换到 real，其余模块 source 不变
14. [ ] 通用清单映射矩阵冻结并评审通过
15. [ ] 模块例外白名单冻结并评审通过
16. [ ] 核心测试 case（真实 API + 前端展示）门禁冻结
17. [ ] 签字完成

---

## 3. 请求与响应冻结

### 3.1 请求参数冻结

```ts
interface SectorOverviewRequest {
  market?: "CN_A";    // default: CN_A
  tradeDate?: string; // YYYY-MM-DD
  debug?: 0 | 1;      // default: 0
}
```

参数校验：

1. `market` 非 `CN_A` -> `400001`
2. `tradeDate` 非法格式 -> `400001`
3. `debug` 非 `0/1` -> `400001`
4. 请求不接受 `columnKeys/idxType/sortBy/limit` 等列定义覆盖参数。

### 3.2 响应结构冻结

```ts
interface SectorOverviewResponseData {
  tradingDay: TradingDay;
  pageStatus: PageStatus;
  sectorOverview: SectorOverviewPanel;
  debugInfo?: {
    modules: ModuleStatusItem[];
    exceptions: ModuleExceptionItem[];
  };
}

interface SectorOverviewPanel {
  tradeDate: string;
  status: "READY" | "PARTIAL" | "DELAYED" | "EMPTY" | "ERROR";
  columns: SectorRankColumn[];
  heatMapItems: SectorHeatMapItem[];
}

interface SectorRankColumn {
  columnKey: string;
  title: string;
  tone: "UP" | "DOWN" | "NEUTRAL";
  metricLabel: string;
  rows: SectorRankRow[];
}

interface SectorRankRow {
  rank: number;
  subject: {
    subjectType: "sector";
    subjectCode: string;
    subjectName?: string | null;
    sectorType: "INDUSTRY" | "CONCEPT" | "REGION";
  };
  metric: {
    value?: number | null;
    displayText: string;
    unit?: "%" | null;
    direction: "UP" | "DOWN" | "FLAT" | "UNKNOWN";
  };
  leadingStock?: {
    stockCode?: string | null;
    stockName?: string | null;
    changePct?: number | null;
  } | null;
}

interface SectorHeatMapItem {
  subject: SectorRankRow["subject"];
  changePct?: number | null;
  direction: "UP" | "DOWN" | "FLAT" | "UNKNOWN";
  riseStockCount?: number | null;
  fallStockCount?: number | null;
  leadingStock?: SectorRankRow["leadingStock"];
}
```

---

## 4. 核心样例响应（最小集合）

### 4.1 正常样例

```json
{
  "sectorOverview": {
    "tradeDate": "2026-05-08",
    "status": "READY",
    "columns": [
      {
        "columnKey": "industryTopGainers",
        "title": "行业涨幅前五",
        "tone": "UP",
        "metricLabel": "涨幅",
        "rows": [
          {
            "rank": 1,
            "subject": {
              "subjectType": "sector",
              "subjectCode": "BK0481.DC",
              "subjectName": "有色金属",
              "sectorType": "INDUSTRY"
            },
            "metric": {
              "value": 3.21,
              "displayText": "+3.21%",
              "unit": "%",
              "direction": "UP"
            },
            "leadingStock": {
              "stockCode": "600000.SH",
              "stockName": "示例股票",
              "changePct": 10.01
            }
          }
        ]
      },
      {
        "columnKey": "fundIn",
        "title": "资金流入前五",
        "tone": "UP",
        "metricLabel": "净流入",
        "rows": [
          {
            "rank": 1,
            "subject": {
              "subjectType": "sector",
              "subjectCode": "BK0473.DC",
              "subjectName": "证券",
              "sectorType": "INDUSTRY"
            },
            "metric": {
              "value": 2875528704.0,
              "displayText": "+28.8亿",
              "unit": null,
              "direction": "UP"
            }
          }
        ]
      }
    ],
    "heatMapItems": [
      {
        "subject": {
          "subjectType": "sector",
          "subjectCode": "BK1184.DC",
          "subjectName": "人形机器人",
          "sectorType": "CONCEPT"
        },
        "changePct": 5.6,
        "direction": "UP",
        "riseStockCount": 42,
        "fallStockCount": 8
      }
    ]
  }
}
```

### 4.2 delayed 样例

```json
{
  "sectorOverview": {
    "tradeDate": "2026-05-07",
    "status": "DELAYED",
    "columns": [],
    "heatMapItems": []
  },
  "debugInfo": {
    "modules": [
      {
        "moduleKey": "sectorOverview",
        "expectedTradeDate": "2026-05-08",
        "observedTradeDate": "2026-05-07",
        "lagDays": 1,
        "status": "DELAYED",
        "note": "dc source bundle delayed"
      }
    ],
    "exceptions": [
      {
        "module": "sectorOverview",
        "code": "SO_SOURCE_DELAYED",
        "severity": "warn"
      }
    ]
  }
}
```

### 4.3 empty 样例

```json
{
  "sectorOverview": {
    "tradeDate": "2026-05-08",
    "status": "EMPTY",
    "columns": [],
    "heatMapItems": []
  },
  "debugInfo": {
    "exceptions": [
      {
        "module": "sectorOverview",
        "code": "SO_SOURCE_EMPTY",
        "severity": "warn"
      }
    ]
  }
}
```

### 4.4 error 样例

```json
{
  "sectorOverview": {
    "tradeDate": "2026-05-08",
    "status": "ERROR",
    "columns": [],
    "heatMapItems": []
  },
  "debugInfo": {
    "exceptions": [
      {
        "module": "sectorOverview",
        "code": "SO_QUERY_FAILED",
        "severity": "error"
      }
    ]
  }
}
```

---

## 5. 查询草案（可直接转实现）

### 5.1 观测交易日

默认请求：

```sql
select min(observed_trade_date) as observed_trade_date
from (
  select max(trade_date) as observed_trade_date
  from core_serving.dc_daily
  where trade_date <= :expected_trade_date
  union all
  select max(trade_date) as observed_trade_date
  from core_serving.board_moneyflow_dc
  where trade_date <= :expected_trade_date
  union all
  select max(trade_date) as observed_trade_date
  from core_serving.dc_index
  where trade_date <= :expected_trade_date
) s;
```

显式 `tradeDate`：

```sql
select :trade_date as observed_trade_date;
```

### 5.2 主查询

```sql
select
  ts_code,
  trade_date,
  category,
  close,
  change,
  pct_change,
  turnover_rate,
  amount,
  swing
from core_serving.dc_daily
where trade_date = :observed_trade_date
  and category in ('行业板块', '概念板块', '地域板块')
  and ts_code is not null;
```

### 5.3 结构补充查询

```sql
select
  ts_code,
  trade_date,
  name,
  leading,
  leading_code,
  leading_pct,
  total_mv,
  up_num,
  down_num,
  idx_type,
  level
from core_serving.dc_index
where trade_date = :observed_trade_date
  and idx_type in ('行业板块', '概念板块', '地域板块')
  and ts_code is not null;
```

### 5.4 资金流查询

```sql
select
  trade_date,
  content_type,
  ts_code,
  name,
  pct_change,
  close,
  net_amount,
  net_amount_rate,
  rank
from core_serving.board_moneyflow_dc
where trade_date = :observed_trade_date
  and content_type in ('行业', '概念', '地域')
  and ts_code is not null;
```

### 5.5 列构建规则

```text
industryTopGainers: dc_daily.category='行业板块', pct_change desc nulls last, ts_code asc, limit 5
conceptTopGainers:  dc_daily.category='概念板块', pct_change desc nulls last, ts_code asc, limit 5
regionTopGainers:   dc_daily.category='地域板块', pct_change desc nulls last, ts_code asc, limit 5
fundIn:             board_moneyflow_dc.content_type in ('行业','概念','地域'), net_amount desc nulls last, ts_code asc, limit 5
industryTopLosers:  dc_daily.category='行业板块', pct_change asc nulls last, ts_code asc, limit 5
conceptTopLosers:   dc_daily.category='概念板块', pct_change asc nulls last, ts_code asc, limit 5
regionTopLosers:    dc_daily.category='地域板块', pct_change asc nulls last, ts_code asc, limit 5
fundOut:            board_moneyflow_dc.content_type in ('行业','概念','地域'), net_amount asc nulls last, ts_code asc, limit 5
```

### 5.6 热力图构建规则

```text
all valid dc_daily rows
  -> sort by abs(pct_change) desc nulls last
  -> then pct_change desc nulls last
  -> then ts_code asc
  -> limit 20
```

### 5.7 索引与排序说明

1. 现有索引：
   - `idx_dc_daily_trade_date`
   - `idx_dc_daily_trade_date_category`
   - `idx_board_moneyflow_dc_trade_date`
   - `idx_board_moneyflow_dc_content_type_trade_date`
   - `idx_dc_index_trade_date`
   - `idx_dc_index_idx_type_trade_date`
2. 单日结果集较小，允许在应用层对已取回小集合分组排序。
3. 不允许跨多日拉取后在应用层筛选目标日。

---

## 6. 状态归并样例

| 模块状态组合 | 页面状态 | 备注 |
|---|---|---|
| `READY` | `READY` 或由整页聚合决定 | 板块模块正常 |
| `DELAYED` | `PARTIAL/DELAYED` | 仅 debug 展示模块明细 |
| `PARTIAL` | `PARTIAL` | 行数不足但有可展示内容 |
| `EMPTY` | `PARTIAL/EMPTY` | 由整页聚合决定 |
| `ERROR` | `PARTIAL/ERROR` | 不阻断其他模块 |

---

## 7. 异常码覆盖矩阵

> 异常码必须来自  
> [exception-code-registry.md](/Users/congming/github/goldenshare/wealth/docs/system/exception-code-registry.md)

| code | 覆盖用例 | 触发条件 | 预期行为 |
|---|---|---|---|
| `SO_SOURCE_DELAYED` | 源日期落后 | `observedTradeDate < expectedTradeDate` | 模块 delayed，debug 记录 |
| `SO_SOURCE_EMPTY` | 源数据为空 | 目标/观测日无有效 DC 组合源数据 | 模块 empty |
| `SO_COLUMN_METRIC_UNAVAILABLE` | 列指标不可产出 | 列定义要求 DC 组合源不存在字段 | 模块 error，禁止伪造 |
| `SO_QUERY_FAILED` | 查询失败 | SQL/服务异常 | 模块 error |

---

## 8. 性能门禁

1. P95 预算：`< 300ms`
2. 返回体大小预算：`< 80KB`
3. 最大并发预算：按市场总览模块接口常规并发处理，不新增大查询。
4. 超预算降级策略：
   - 不做应用层大数据拉取；
   - 若单表查询超预算，先检查索引与 SQL，再讨论缓存；
   - 禁止为了过 5 秒阈值做临时 mock fallback。

---

## 9. 测试门禁

1. 单元测试：
   - `category/content_type/idx_type` 映射；
   - 排序与截断；
   - 状态 resolver；
   - 异常 builder。
2. 集成测试：
   - 正常/延迟/empty/error；
   - `debug=0/1`；
   - `tradeDate` 显式与默认路径。
3. 冒烟测试：
   - `SectorOverviewPanel` loading/ready/error；
   - 左 8 列、右 20 格；
   - 点击占位 toast。
4. debug 模式验证：
   - `moduleKey=sectorOverview`；
   - `expectedTradeDate/observedTradeDate/lagDays/status/note` 全字段。

### 9.1 核心测试 case 门禁（必填）

1. 核心字段清单：
   - `columns[].columnKey/title/metricLabel/tone`
   - `rows[].rank/subject/metric`
   - `heatMapItems[].subject/changePct/direction/riseStockCount/fallStockCount`
   - `debugInfo.modules/exceptions`
2. 后端真实 API 集成测试用例列表（禁止 mock service/query）：
   - `test_sector_overview_returns_columns_and_heatmap`
   - `test_sector_overview_uses_dc_source_bundle`
   - `test_sector_overview_debug_status`
   - `test_sector_overview_empty_and_error`
3. 前端真实 API 展示校验用例列表（禁止 mock adapter）：
   - `market-overview-sector-overview-real-api` 展示 8 列和 20 格；
   - loading 期间不展示 mock；
   - 5 秒超时展示 error。
4. 执行命令：
   - `pytest -q tests/web/test_wealth_market_sector_overview_api.py`
   - `cd wealth && npm run test -- market-overview-sector-overview-real-api`
5. 通过标准：
   - 页面可见字段与后端 API 字段一致；
   - 无 mock fallback；
   - 无未登记异常码。

---

## 10. 签字清单

### 10.1 后端负责人

1. [ ] 查询草案可实现
2. [ ] 异常覆盖完整
3. [ ] 状态归并无歧义
4. [ ] DC 组合源边界无漂移

### 10.2 前端负责人

1. [ ] 响应结构可消费
2. [ ] 状态表达可落 UI
3. [ ] 降级策略可实现
4. [ ] 视觉结构不偏离当前页面

### 10.3 架构/产品负责人

1. [ ] 范围未扩散
2. [ ] 语义与业务一致
3. [ ] 资金列口径已拍板
4. [ ] 可进入编码阶段

---

## 11. 跨模块抽象门禁原则映射（必填）

| 原则 | 是否适用 | 落地位置（字段/查询/配置/状态） | 测试落地 | 备注 |
|---|---|---|---|---|
| 事实源单一原则 | 是 | `core_serving.dc_daily/board_moneyflow_dc/dc_index` | API 测试断言字段来源 | 每类字段一个主源 |
| 契约先行与冻结原则 | 是 | `SectorOverviewResponseData` | schema + 前端 adapter 测试 | 先评审再编码 |
| 配置一致性原则 | 是 | 本期固定列定义 | 请求拒绝列覆盖参数 | 暂不接策略中心 |
| 默认行为显式原则 | 是 | 默认/显式 `tradeDate` | 两条日期路径测试 | 无隐式旧日伪装 |
| 排序与筛选确定性原则 | 是 | `category/content_type/idx_type` + 排序链 | 同分排序测试 | `ts_code asc` 稳定 |
| 性能预算前置原则 | 是 | 单表单日查询 | 耗时记录 | P95 `<300ms` |
| 可观测与异常标准化原则 | 是 | `SO_*` + debugInfo | delayed/empty/error 测试 | 注册表唯一 |
| 测试以用户可见结果为中心原则 | 是 | 8 列 + 20 热力格 | 前端真实 API smoke | 不只测 JSON 结构 |

### 11.1 模块例外白名单

| 例外规则 | 生效范围 | 业务语义依据 | 测试要求 |
|---|---|---|---|
| 本期不接策略配置中心 | `sectorOverview` | 当前 UI 列结构固定，三源字段分工已冻结 | 请求不得覆盖列定义 |

### 11.2 模块门禁清单（复盘增强版）

1. [ ] 已核对 `dc_daily`、`board_moneyflow_dc`、`dc_index` 源文档和当前 ORM 字段。
2. [ ] 已确认资金流入/流出列来自 `board_moneyflow_dc.net_amount`，不允许前端伪造。
3. [ ] 已冻结 `category/content_type/idx_type` 中文实值。
4. [ ] 已冻结 8 列与 20 热力格结构。
5. [ ] 已冻结排序主次规则。
6. [ ] 已冻结 loading/ready/error 和 5 秒超时行为。
7. [ ] 已冻结 debug 模块状态字段。
8. [ ] 已冻结真实 API + 前端展示双门禁。

---

## 12. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-13 | 首版：冻结板块速览 M2 编码前门禁 | Codex |
