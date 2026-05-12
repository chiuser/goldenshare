# 市场总览｜连板天梯标杆需求 v1（benchmark-requirement）

> 用途：定义“连板天梯”模块的业务边界、分层口径、展示字段与状态语义。
> 阶段：需求冻结前。
> 产物性质：业务事实源（不是实现细节文档）。

关联文档：

1. [连板天梯技术实施方案 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/streak-ladder-implementation-design-v1.md)
2. [连板天梯 M2 编码前门禁 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/streak-ladder-m2-coding-gate-v1.md)

---

## 1. 目标与定位

1. 模块目标：按交易日展示 A 股涨停晋级股票的连板层级，固定分为“首板、二板、三板、四板、五板及以上”。
2. 用户价值：用户快速看到市场短线接力结构，识别高标高度、各梯队宽度与代表股票。
3. 业务定位：市场总览中紧跟“涨跌停统计与分布”的独立事实模块，只展示客观结构，不给交易建议。

---

## 2. 范围与边界

### 2.1 本期覆盖

1. 独立模块 `streakLadder`，不再作为 `limitUp` 子对象实现。
2. 固定五个梯队：
   - `first`：首板，`boardCount=1`
   - `second`：二板，`boardCount=2`
   - `third`：三板，`boardCount=3`
   - `fourth`：四板，`boardCount=4`
   - `fifthPlus`：五板及以上，`boardCount>=5`
3. 每个梯队展示股票数量与股票卡片。
4. 股票卡片展示：
   - 股票名称
   - 股票代码
   - 主题/板块标签
   - 最新价
   - 涨跌幅
   - 开板次数
   - 精确板数 `boardCount`
5. 股票卡片点击交互：当前阶段保留 toast 提示“进入详情：{subjectCode}”，不跳转真实详情页。
6. 模块级 debug 状态：仅在页面 debug 模式展示。

### 2.2 本期不覆盖

1. 不做右侧抽屉、全量明细页或个股详情页。
2. 不做连板强度评分、交易建议、晋级概率预测。
3. 不做用户侧自定义梯队、排序、股票池过滤。
4. 不接策略配置中心；本模块首期规则固定在后端实现。
5. 不改“涨跌停统计与分布”模块的统计卡、结构分布和历史柱图。

### 2.3 与其他模块边界

1. 上游依赖：
   - `core_serving.equity_limit_list`
   - `core_serving.trade_calendar`
2. 下游消费者：`StreakLadderPanel`。
3. 与相邻模块的职责分割：
   - `limitUp` 负责涨跌停统计、结构分布与历史组合柱图；
   - `streakLadder` 只负责按连板层级组织股票卡片；
   - `leaderboards` 负责涨幅、跌幅、成交额、换手、量比、人气、飙升等排行榜；
   - `sectorOverview` 负责板块速览，不为本模块补业务事实。

---

## 3. 核心原则（硬约束）

1. 规则归属：梯队划分、排序、字段缺失降级和状态判定全部由后端定义，前端只展示。
2. 契约归属：以本三件套为 `streakLadder` 唯一契约事实源。
3. 数据源归属：主事实源为 `core_serving.equity_limit_list`，对应 Tushare `limit_list_d`。
4. ST 口径：`limit_list_d` 文档明确不提供 ST 股票统计，本模块不再额外叠加 ST 过滤。
5. 板数口径：`boardCount` 必须来自 `equity_limit_list.limit_times` 解析后的整数；`fifthPlus` 中也必须保留每只股票的真实 `boardCount`。
6. 排序口径：每个梯队内部排序必须固定，禁止前端二次排序。
7. 状态口径：真实 API 未返回前展示 loading；失败展示 error；禁止静默回退 mock。

禁止事项：

1. 前端按 `limit_times` 自行分桶。
2. 前端从整页 mock 或 `limitUp` 对象里派生连板天梯。
3. 为了补字段临时调用 ops 后台接口。
4. 把 `equity_limit_list` 中非数字 `limit_times` 行强行展示为未知板数。
5. 让用户侧通过参数改变梯队定义或排序规则。

### 3.1 跨模块抽象门禁原则（需求层冻结）

1. 事实源单一：连板事实字段全部由后端模块接口产出，前端不拼装事实。
2. 契约冻结：`buckets/stocks/boardCount/stockCount/moduleStatus` 字段语义本期冻结。
3. 配置一致性：本模块首期无策略配置；后续如增加配置必须走策略中心，不允许散落文件。
4. 默认行为显式：未传 `tradeDate` 使用系统期望交易日；无数据进入 `EMPTY`；源落后进入 `DELAYED`。
5. 排序筛选确定性：`limit_times` 解析、梯队分桶、梯队内排序均由后端固定。
6. 性能预算前置：模块 P95 `< 320ms`，payload `< 260KB`。
7. 可观测标准化：异常码统一登记到异常码注册表，debug 结构与其它市场模块一致。
8. 用户可见结果优先：验收以页面五个梯队、股票卡片字段、点击反馈和状态展示为准。

---

## 4. 业务对象模型（非代码，先语义）

### 4.1 `StreakLadderPanel`

连板天梯模块根对象。

| 字段 | 含义 | 单位 | 可空 | 产出责任 | 缺失降级 |
|---|---|---|---|---|---|
| `tradeDate` | 模块观测交易日 | - | 否 | 后端 | 缺失即异常 |
| `buckets` | 五个固定梯队 | - | 否 | 后端 | 空数组不允许；无股票也返回五个空梯队 |

### 4.2 `StreakBucket`

单个连板梯队。

| 字段 | 含义 | 单位 | 可空 | 产出责任 | 缺失降级 |
|---|---|---|---|---|---|
| `bucketKey` | 梯队键 | - | 否 | 后端 | 缺失即异常 |
| `bucketLabel` | 梯队中文名 | - | 否 | 后端 | 缺失即异常 |
| `minBoardCount` | 梯队最小板数 | 板 | 否 | 后端 | 缺失即异常 |
| `maxBoardCount` | 梯队最大板数；五板及以上为 `null` | 板 | 是 | 后端 | `fifthPlus` 固定 `null` |
| `stockCount` | 该梯队全量股票数量 | 只 | 否 | 后端 | 无数据返回 `0` |
| `stocks` | 该梯队股票卡片列表 | - | 否 | 后端 | 无数据返回空数组 |

### 4.3 `StreakStockRow`

梯队中的股票卡片。

| 字段 | 含义 | 单位 | 可空 | 产出责任 | 缺失降级 |
|---|---|---|---|---|---|
| `rank` | 梯队内排序名次 | - | 否 | 后端 | 缺失即异常 |
| `subject.subjectType` | 主体类型 | - | 否 | 后端 | 固定 `stock` |
| `subject.subjectCode` | 股票代码 | - | 否 | 后端 | 缺失丢弃该行 |
| `subject.subjectName` | 股票名称 | - | 是 | 后端 | 缺失时前端只显示代码 |
| `boardCount` | 真实连板数 | 板 | 否 | 后端 | 非正整数丢弃该行 |
| `sectorName` | 主题/板块标签 | - | 是 | 后端 | 缺失显示 `--` |
| `latestPrice` | 最新价/收盘价 | 元 | 是 | 后端 | 缺失显示 `--` |
| `changePct` | 当日涨跌幅 | % | 是 | 后端 | 缺失显示 `--` |
| `direction` | 涨跌方向 | - | 否 | 后端 | 缺失按 `UNKNOWN` |
| `openTimes` | 开板次数 | 次 | 是 | 后端 | 缺失显示 `--` |

---

## 5. 数据来源与映射（事实层）

| 业务字段 | 来源表 | 来源列 | 转换规则 | 备注 |
|---|---|---|---|---|
| `tradeDate` | `core_serving.trade_calendar` | `trade_date` | 未传日期时按盘后口径取期望交易日 | 与其它市场模块一致 |
| `subject.subjectCode` | `core_serving.equity_limit_list` | `ts_code` | 原样 | 主源 |
| `subject.subjectName` | `core_serving.equity_limit_list` | `name` | 原样；缺失时前端只展示代码 | 主源 |
| `boardCount` | `core_serving.equity_limit_list` | `limit_times` | 解析正整数；非数字丢弃并记录异常 | 主源 |
| `bucketKey/bucketLabel` | 派生 | `boardCount` | `1/2/3/4/>=5` 固定映射 | 后端派生 |
| `stockCount` | 派生 | `bucketKey` | 每梯队过滤后行数 | 后端派生 |
| `latestPrice` | `core_serving.equity_limit_list` | `close` | 原样；缺失显示 `--` | 主源 |
| `changePct` | `core_serving.equity_limit_list` | `pct_chg` | 原样；缺失显示 `--` | 主源 |
| `direction` | 派生 | `changePct` | `>0 UP`，`<0 DOWN`，`=0 FLAT`，缺失 `UNKNOWN` | 前端只消费 |
| `openTimes` | `core_serving.equity_limit_list` | `open_times` | 原样；缺失显示 `--` | 主源 |
| `sectorName` | `core_serving.equity_limit_list` | `industry` | 原样；缺失显示 `--` | 主源 |

补充：

1. 主源优先级：`equity_limit_list` 是连板天梯唯一主源。
2. 回退策略：本模块首期不跨表补列；缺失展示字段统一可空降级。
3. 数据时效语义：盘后快照语义，非实时流。
4. 源接口依据：Tushare `limit_list_d` 文档位于 `docs/sources/tushare/股票数据/打板专题数据/0298_涨跌停列表（新）.md`，输出字段包含 `open_times` 与 `limit_times`，单次上限 2500 行。

---

## 6. 状态语义

1. 页面级状态：沿用市场总览 `READY/PARTIAL/DELAYED/EMPTY/ERROR`。
2. 模块级状态（debug-only）：
   - `moduleKey=streakLadder`
   - `expectedTradeDate`
   - `observedTradeDate`
   - `lagDays`
   - `status`
   - `note`
3. delayed 判定：`observedTradeDate < expectedTradeDate`。
4. empty 判定：目标交易日没有有效 `equity_limit_list` 涨停行。
5. partial 判定：
   - 有有效连板行，但部分展示补列缺失；
   - 存在非数字 `limit_times` 行被丢弃；
   - `sectorName` 全量缺失但主梯队仍可展示。

---

## 7. 异常语义

1. 异常对象结构：`module/code/severity/message/details`。
2. 用户可见策略：正式态不展示异常码；模块可展示 loading、empty、error 视觉状态。
3. debug 可见策略：`debug=1` 时返回模块状态和异常列表；生产环境禁用 debug 输出。

异常码要求：

1. 必须登记到 [exception-code-registry.md](/Users/congming/github/goldenshare/wealth/docs/system/exception-code-registry.md)。
2. 未登记异常码禁止进入代码与 API 契约。

本模块异常码：

| code | 语义 |
|---|---|
| `SL_SOURCE_DELAYED` | `equity_limit_list` 观测日期落后 |
| `SL_SOURCE_EMPTY` | 目标日期无有效连板数据 |
| `SL_INVALID_BOARD_COUNT` | `equity_limit_list.limit_times` 无法解析为正整数 |
| `SL_JOIN_METRIC_MISSING` | 最新价、涨跌幅、开板次数或行业字段缺失 |
| `SL_QUERY_FAILED` | 查询或服务异常 |

---

## 8. API 契约（需求层）

1. 接口路径：`GET /api/v1/wealth/market/streak-ladder`。
2. 请求参数：
   - `market?: "CN_A"`，默认 `CN_A`
   - `tradeDate?: string`，可选观测交易日，格式 `YYYY-MM-DD`
   - `debug?: 0 | 1`，默认 `0`
3. 响应结构：`tradingDay + pageStatus + streakLadder + debugInfo?`。
4. 字段命名规则：lowerCamelCase。
5. 向后兼容策略：本模块尚未真实接入，不保留旧整页 mock 字段兼容；实现时直接按本契约切换。

---

## 9. 验收标准

1. 功能验收：页面展示五个固定梯队，且顺序为“首板、二板、三板、四板、五板及以上”。
2. 语义验收：每只股票的 `boardCount` 与所属梯队一致，`fifthPlus` 中保留真实板数。
3. 状态验收：真实 API 未返回前展示 loading；超时或失败展示 error；无数据展示 empty。
4. 异常验收：只使用本文件登记的 `SL_*` 异常码。
5. 交互验收：点击股票卡片触发当前页面同款 toast，不跳转真实详情页。

### 9.1 参考 case（可复用）

1. `limit_times="5"`、`limit_times="6"`、`limit_times="11"` 都进入 `fifthPlus`，但 `boardCount` 分别保留 `5/6/11`。
2. `limit_times` 非数字时剔除该行，并在 debug 中返回 `SL_INVALID_BOARD_COUNT`。
3. `equity_limit_list` 主行存在但 `close/pct_chg/open_times/industry` 缺失时，股票仍展示，缺失字段显示 `--`，debug 返回 `SL_JOIN_METRIC_MISSING`。
4. 目标日源日期落后时，正式页面仍展示可用数据，debug 面板标记 `DELAYED`。
5. 目标日期没有 `limit_type='U'` 的有效涨停行时，模块进入 `EMPTY`，不展示 mock 股票。

---

## 10. 已确认项

1. 连板天梯是独立模块，独立完成三件套。
2. 数据源参考并以 `core_serving.equity_limit_list` 为主事实源。
3. 本期不接策略中心，不暴露用户侧配置参数。
4. 本期不做个股详情页真实跳转。

---

## 11. 待拍板项

当前无阻塞拍板项。若评审中要调整是否限制每梯队展示条数、或是否新增“完整天梯”入口，必须先改本三件套，再进入编码。

---

## 12. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-12 | 初版：冻结连板天梯独立模块需求、数据源、字段与状态语义 | Codex |
