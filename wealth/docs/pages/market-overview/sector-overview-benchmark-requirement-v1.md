# 市场总览｜板块速览标杆需求 v1（benchmark-requirement）

> 用途：冻结“板块速览”模块的业务口径、展示边界、数据源与验收规则。  
> 阶段：需求冻结前。  
> 产物性质：业务事实源（不是实现细节文档）。

---

## 1. 目标与定位

1. 模块目标：在市场总览页中，用东方财富板块数据展示当日行业、概念、地域板块的涨跌强弱与热力分布。
2. 用户价值：用户打开首页即可快速看到当天最强、最弱、波动最明显的板块，判断市场主线与风险区域。
3. 业务定位：市场总览页最后一个板块，负责“板块层面的结构性行情概览”，不承担个股榜单、大盘级资金流或连板题材归因。

---

## 2. 范围与边界

### 2.1 本期覆盖

1. 页面布局保持当前 V1.1 原型结构：
   - 左侧 `4 列 x 2 行` Top5 榜单矩阵；
   - 右侧 `5 行 x 4 列` 板块热力图；
   - “进入板块热力图”按钮保留现有交互占位。
2. 数据源使用 DC 板块组合：
   - `core_serving.dc_daily`：板块日线行情，负责涨跌幅、成交额、换手率和热力图主指标；
   - `core_serving.board_moneyflow_dc`：板块资金流，负责资金流入/流出榜；
   - `core_serving.dc_index`：板块列表与结构信息，负责板块名称、类型、上涨/下跌家数、领涨股补充信息。
3. 支持行业、概念、地域三类板块：
   - `dc_daily.category=行业板块/概念板块/地域板块`
   - `dc_index.idx_type=行业板块/概念板块/地域板块`
   - `board_moneyflow_dc.content_type=行业/概念/地域`
4. 支持涨幅前五、跌幅前五、热力图。
5. 支持模块级 debug 信息：
   - `expectedTradeDate`
   - `observedTradeDate`
   - `lagDays`
   - `status`
   - `note`
6. 保持真实 API 接入纪律：
   - API 返回前展示 loading；
   - 超过 5 秒或请求失败展示 error；
   - 禁止用 mock 数据冒充 ready。

### 2.2 本期不覆盖

1. 不接入 THS 板块数据源。
2. 不接入 raw 表实时拼接。
3. 不做板块详情页。
4. 不做板块成分股展开。
5. 不做用户可配置榜单列。
6. 不做 Redis 缓存。
7. 不改变当前页面视觉布局、字号、间距、颜色与交互结构。

### 2.3 与其他模块边界

1. 上游依赖：
   - `core_serving.dc_daily`
   - `core_serving.board_moneyflow_dc`
   - `core_serving.dc_index`
   - 交易日期解析能力（沿用 wealth 市场总览既有盘后静态数据口径）
2. 下游消费者：
   - `SectorOverviewPanel`
   - 页面级 debug 面板
3. 与相邻模块职责分割：
   - 个股排行归 `leaderboards`；
   - 连板题材归 `streakLadder`；
   - 大盘资金流归 `moneyFlow`；
   - 板块速览只展示板块层面的涨跌、热力与板块资金流，不混入大盘资金流或个股资金流事实。

---

## 3. 核心原则（硬约束）

1. 规则归属：后端定义板块榜单的筛选、排序、截断规则；前端只负责展示。
2. 契约归属：本三件套与实现方案是板块速览模块的当前事实源；旧 reference 文档不得作为实现依据。
3. 禁止事项：
   - 禁止前端自行排序、截断或拼装板块事实；
   - 禁止前端跨模块拼装资金流或涨跌排行；
   - 禁止把某个源没有的字段硬造出来；
   - 禁止 silent mock fallback。

### 3.1 跨模块抽象门禁原则（需求层冻结）

1. 事实源单一：板块速览事实字段只来自 DC 板块组合源；每类字段只允许一个主事实源。
2. 契约冻结：`subject/metric/status/debugInfo` 字段在本期冻结。
3. 配置一致性：本期不接策略配置中心；列定义固定在后端模块代码中，后续若配置化必须单独设计。
4. 默认行为显式：未传 `tradeDate` 时按系统盘后口径取目标交易日；显式传入时查询该交易日。
5. 排序筛选确定性：`category/content_type/idx_type` 枚举固定，排序主次规则固定，空值处理固定。
6. 性能预算前置：单次接口 P95 `< 300ms`，payload `< 80KB`。
7. 可观测标准化：异常码统一登记到异常码注册表，模块状态只在 debug 输出。
8. 用户可见结果优先：验收以页面 8 个榜单块和 20 个热力格的可见字段为主。

---

## 4. 业务对象模型（非代码，先语义）

### 4.1 `SectorSubject`

板块主体引用。

| 字段 | 含义 | 单位 | 可空 | 产出方 | 缺失策略 |
|---|---|---|---|---|---|
| `subjectType` | 主体类型，固定 `sector` | - | 否 | 后端 | 不允许缺失 |
| `subjectCode` | 板块代码 | - | 否 | DC 组合源 `ts_code` | 缺失行不入榜 |
| `subjectName` | 板块名称 | - | 是 | `dc_index.name` 或 `board_moneyflow_dc.name` | 缺失时前端只展示代码 |
| `sectorType` | 板块分类：`INDUSTRY/CONCEPT/REGION` | - | 否 | `category/content_type/idx_type` 映射 | 未识别则丢弃并记录 debug |

### 4.2 `SectorRankColumn`

左侧 Top5 榜单列。

| 字段 | 含义 | 单位 | 可空 | 产出方 | 缺失策略 |
|---|---|---|---|---|---|
| `columnKey` | 榜单列 key | - | 否 | 后端 | 不允许缺失 |
| `title` | 榜单标题 | - | 否 | 后端 | 不允许缺失 |
| `tone` | 列颜色语义：`UP/DOWN/NEUTRAL` | - | 否 | 后端 | 不允许缺失 |
| `metricLabel` | 指标标签，如“涨幅/跌幅/换手” | - | 否 | 后端 | 不允许缺失 |
| `rows` | Top5 行 | - | 否 | 后端 | 可为空数组 |

### 4.3 `SectorRankRow`

左侧 Top5 榜单行。

| 字段 | 含义 | 单位 | 可空 | 产出方 | 缺失策略 |
|---|---|---|---|---|---|
| `rank` | 排名 | - | 否 | 后端排序后生成 | 不允许缺失 |
| `subject` | 板块主体 | - | 否 | 后端 | 不允许缺失 |
| `metric.value` | 指标原始值 | `%`、元或数值 | 是 | 后端按列定义读取对应事实源 | 缺失显示 `--` |
| `metric.displayText` | 指标展示文本 | - | 否 | 后端格式化 | 缺失显示 `--` |
| `metric.direction` | 指标方向 | - | 否 | 后端 | 缺失为 `UNKNOWN` |
| `leadingStock` | 领涨股票信息 | - | 是 | `dc_index.leading/leading_code/leading_pct` | 缺失不展示扩展信息 |

### 4.4 `SectorHeatMapItem`

右侧热力图格子。

| 字段 | 含义 | 单位 | 可空 | 产出方 | 缺失策略 |
|---|---|---|---|---|---|
| `subject` | 板块主体 | - | 否 | 后端 | 不允许缺失 |
| `changePct` | 板块涨跌幅 | `%` | 是 | `dc_daily.pct_change` | 缺失显示 `--` |
| `direction` | 红涨绿跌方向 | - | 否 | 后端 | 缺失为 `UNKNOWN` |
| `riseStockCount` | 板块内上涨家数 | 家 | 是 | `dc_index.up_num` | 缺失显示 `--` |
| `fallStockCount` | 板块内下跌家数 | 家 | 是 | `dc_index.down_num` | 缺失显示 `--` |
| `leadingStock` | 领涨股票信息 | - | 是 | `dc_index.leading/leading_code/leading_pct` | 缺失不展示扩展信息 |

---

## 5. 数据来源与映射（事实层）

| 业务字段 | 来源表 | 来源列 | 转换规则 | 备注 |
|---|---|---|---|---|
| `tradeDate` | DC 组合源 | `trade_date` | ISO 日期 | 模块观测交易日 |
| `subject.subjectCode` | `core_serving.dc_daily` / `core_serving.board_moneyflow_dc` | `ts_code` | 原样 | 板块代码 |
| `subject.subjectName` | `core_serving.dc_index` / `core_serving.board_moneyflow_dc` | `name` | 原样 | 缺失展示代码 |
| `subject.sectorType` | `core_serving.dc_daily` / `core_serving.board_moneyflow_dc` | `category` / `content_type` | `行业板块/行业->INDUSTRY`，`概念板块/概念->CONCEPT`，`地域板块/地域->REGION` | 其他值丢弃 |
| `changePct` | `core_serving.dc_daily` | `pct_change` | 百分比数值 | 涨跌榜与热力图主依据 |
| `turnoverRate` | `core_serving.dc_daily` | `turnover_rate` | 百分比数值 | 板块换手补充指标 |
| `amount` | `core_serving.dc_daily` | `amount` | 元 | 本期可作为扩展指标，不直接改 UI |
| `netAmount` | `core_serving.board_moneyflow_dc` | `net_amount` | 元 | 资金流入/流出榜主依据 |
| `netAmountRate` | `core_serving.board_moneyflow_dc` | `net_amount_rate` | 百分比数值 | 资金流辅助指标 |
| `totalMarketValueWan` | `core_serving.dc_index` | `total_mv` | 万元 | 本期不直接展示，保留契约扩展位 |
| `riseStockCount` | `core_serving.dc_index` | `up_num` | 原样 | 热力格辅助信息 |
| `fallStockCount` | `core_serving.dc_index` | `down_num` | 原样 | 热力格辅助信息 |
| `leadingStock.name` | `core_serving.dc_index` | `leading` | 原样 | 扩展信息 |
| `leadingStock.code` | `core_serving.dc_index` | `leading_code` | 原样 | 扩展信息 |
| `leadingStock.changePct` | `core_serving.dc_index` | `leading_pct` | 百分比数值 | 扩展信息 |

补充：

1. 来源优先级：
   - 涨跌榜与热力图：`dc_daily` 为主源，`dc_index` 只补名称与结构信息；
   - 资金流榜：`board_moneyflow_dc` 为主源；
   - 板块名称/上涨下跌家数/领涨股：`dc_index` 为主源。
2. 回退策略：不做跨表替代事实；源数据缺失用模块状态表达。
3. 数据时效语义：盘后静态数据，不是实时行情。

---

## 6. 状态语义

1. 页面级状态：沿用市场总览页状态归并规则。
2. 模块级状态：仅 debug mode 展示。
3. delayed 判定：
   - 默认请求：`observedTradeDate < expectedTradeDate`。
   - 显式 `tradeDate`：目标日无数据时返回 `EMPTY`，不自动伪装成目标日 ready。
4. partial 判定：
   - 目标日有数据，但 8 列或 20 个热力格因源数据不足无法完整填满。
5. ready 判定：
   - 至少有可展示板块数据；
   - 已完成列构建和热力图构建；
   - 无查询错误。

---

## 7. 异常语义

1. 异常对象结构：`module/code/severity/message/details`。
2. 用户可见策略：正式页面不直接展示异常码；模块失败显示 error 样式。
3. debug 可见策略：`debug=1` 时展示结构化异常。

异常码要求：

1. 必须登记到 `wealth/docs/system/exception-code-registry.md`。
2. 本模块异常码前缀：`SO_*`。
3. 未登记异常码禁止进入代码与 API 契约。

---

## 8. API 契约（需求层）

1. 接口路径：`GET /api/v1/wealth/market/sector-overview`
2. 请求参数：
   - `market?: "CN_A"`，默认 `CN_A`
   - `tradeDate?: string`，格式 `YYYY-MM-DD`
   - `debug?: 0 | 1`
3. 响应结构：
   - `tradingDay`
   - `pageStatus`
   - `sectorOverview`
   - `debugInfo?`
4. 字段命名规则：
   - lowerCamelCase；
   - 主体标识使用 `subjectType + subjectCode + subjectName`；
   - 不使用歧义字段 `code/name` 作为顶层业务字段。
5. 向后兼容策略：
   - 本期不保留旧接口；
   - 当前 mock 结构只作为未切换前展示，不作为真实 API 契约。

---

## 9. 验收标准

1. 功能验收：
   - 左侧显示 8 个榜单块；
   - 每个榜单块最多 5 行；
   - 右侧显示 20 个热力格；
   - 点击板块仍触发现有占位 toast。
2. 语义验收：
   - 行业、概念、地域分类只使用 DC 源真实枚举：`dc_daily.category`、`board_moneyflow_dc.content_type`、`dc_index.idx_type`；
   - 红涨绿跌由后端 `direction` 或 `changePct` 结构化字段驱动；
   - 前端不自行排序。
3. 状态验收：
   - loading/ready/error 三态可见；
   - delayed/partial/empty 在 debug 中可追踪。
4. 异常验收：
   - 异常码全部来自注册表；
   - DC 组合源无数据、日期落后、查询失败均有明确表现。

### 9.1 参考 case（可复用）

1. DC 源枚举实值必须按来源区分：`dc_daily.category/dc_index.idx_type` 使用 `行业板块/概念板块/地域板块`，`board_moneyflow_dc.content_type` 使用 `行业/概念/地域`，不能凭英文枚举猜。
2. 若 `pct_change` 同分，必须有稳定次排序，避免页面顺序漂移。
3. 热力图必须固定 20 格，少于 20 格时用模块 `PARTIAL` 表达，不得前端补假数据。
4. 资金流入/流出必须来自 `board_moneyflow_dc.net_amount`，不能由涨跌幅、成交额或换手率替代。

---

## 10. 已确认清零项

1. 已确认：板块速览不是 `dc_index` 单源；本期使用 `dc_daily + board_moneyflow_dc + dc_index` 的 DC 组合源。
2. 已确认：保留原型“资金流入前五 / 资金流出前五”，资金流事实来自 `board_moneyflow_dc.net_amount`。
3. 当前无待拍板项。

---

## 11. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-13 | 首版：冻结板块速览 DC 组合源口径、对象模型与状态语义 | Codex |
