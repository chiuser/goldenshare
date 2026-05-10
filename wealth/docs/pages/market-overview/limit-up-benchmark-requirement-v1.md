# 市场总览｜涨跌停统计与分布标杆需求 v1（benchmark-requirement）

> 用途：定义“涨跌停统计与分布（2×2）”模块的业务边界、统计口径与降级语义。  
> 阶段：需求冻结前。  
> 产物性质：业务规则事实源（不是实现细节文档）。

> 当前状态：`Draft / 待评审`（未冻结）。  
> 说明：本方案尚未最终拍板，禁止按本文进入编码实现。

关联文档：

1. [涨跌停统计与分布技术实施方案 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/limit-up-implementation-design-v1.md)
2. [涨跌停统计与分布 M2 编码前门禁 v1](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/limit-up-m2-coding-gate-v1.md)

---

## 1. 目标与定位

1. 模块目标：输出涨跌停客观事实，包括统计卡、今日/昨日结构、历史组合柱图。
2. 用户价值：用户快速识别“封板强弱、结构风险、板块集中度”。
3. 业务定位：市场总览首屏核心事实模块之一，只给事实，不给主观建议。

---

## 2. 范围与边界

### 2.1 本期覆盖

1. 2×2 布局：
   - 左上：8 个统计卡片
   - 右上：今日“涨停板块分布 + 跌停/炸板结构”
   - 左下：历史涨跌停组合柱图（`1个月` / `3个月`）
   - 右下：昨日“涨停板块分布 + 跌停/炸板结构”
2. 涨停/跌停卡必须同时展示“总数/ST数”，格式固定为 `总数/ST数`。
3. 封板率口径固定为“不包含 ST 涨停板股票”。
4. 天地板/地天板采用可审计规则；数据条件不满足时显式降级，不允许伪造数字。

### 2.2 本期不覆盖

1. 不做盘中实时 tick 级判定。
2. 不做策略预测或交易建议。
3. 不改连板天梯模块（连板天梯单独模块治理）。

### 2.3 与其他模块边界

1. 上游依赖：
   - `core_serving.limit_list_ths`
   - `core_serving.limit_cpt_list`
   - `core_serving.limit_step`
   - `core_serving.equity_stock_st`
   - `core_serving.dc_member`
   - `core_serving.dc_index`
   - `core_serving.trade_calendar`
2. 下游消费者：`LimitUpPanel`（页面展示组件）。
3. 职责分割：
   - 本模块负责涨跌停统计与结构；
   - 不负责榜单速览、不负责连板天梯明细卡、不负责板块总览矩阵。

---

## 3. 核心原则（硬约束）

1. 规则归属：后端定义统计规则与分组规则；前端只展示。
2. 契约归属：以本模块三件套文档为单一事实源。
3. ST 口径约束：
   - 涨停/跌停卡必须输出总数与 ST 子集；
   - 封板率必须排除 ST 涨停与 ST 炸板。
4. 天地板/地天板约束：
   - 必须先满足数据前置条件再计算；
   - 不满足条件时必须返回可解释降级（如 `null + reason_code`）。
5. 分布结构约束：
   - 今日与昨日结构必须使用同一算法；
   - 不允许“今日一个算法、昨日另一个算法”。

禁止事项：

1. 前端自行拼装涨跌停统计字段。
2. 在数据不足时用固定 mock 值冒充真实值。
3. 把 ST 口径混入封板率分母。

---

## 4. 业务对象模型（非代码，先语义）

1. `LimitUpPanel`：模块返回根对象。
2. `LimitSummaryCard`：8 个统计卡对象。
3. `LimitDistributionBlock`：今日/昨日结构块。
4. `LimitHistoryPoint`：历史组合柱图点。

字段语义要求：

| 对象 | 字段 | 含义 | 单位 | 可空 | 产出责任 | 缺失降级 |
|---|---|---|---|---|---|---|
| `LimitUpPanel` | `tradeDate` | 模块观测交易日 | - | 否 | 后端 | 缺失即异常 |
| `LimitSummaryCard` | `limitUpPair` | 涨停 `总数/ST数` | 只 | 否 | 后端 | `0/0` |
| `LimitSummaryCard` | `limitDownPair` | 跌停 `总数/ST数` | 只 | 否 | 后端 | `0/0` |
| `LimitSummaryCard` | `brokenLimitPair` | 炸板 `总数/ST数` | 只 | 否 | 后端 | `0/0` |
| `LimitSummaryCard` | `sealingRate` | 封板率（非ST） | % | 是 | 后端 | `null` + 降级说明 |
| `LimitSummaryCard` | `streakCount` | 连板家数（二板及以上） | 只 | 否 | 后端 | `0` |
| `LimitSummaryCard` | `maxBoard` | 最高连板（整数板数） | 板 | 否 | 后端 | `0` |
| `LimitSummaryCard` | `skyToFloorCount` | 天地板家数 | 只 | 是 | 后端 | `null` + 原因 |
| `LimitSummaryCard` | `floorToSkyCount` | 地天板家数 | 只 | 是 | 后端 | `null` + 原因 |
| `LimitDistributionBlock` | `limitUpSectorDistribution[]` | 涨停板块分布 TopN（按涨停家数，字段记作 `upNums/count`） | 只 | 否 | 后端 | 空数组 |
| `LimitDistributionBlock` | `limitDownStructure[]` | 跌停结构 TopN | 只 | 否 | 后端 | 空数组 |
| `LimitDistributionBlock` | `brokenLimitStructure[]` | 炸板结构 TopN | 只 | 否 | 后端 | 空数组 |
| `LimitHistoryPoint` | `tradeDate` | 交易日 | - | 否 | 后端 | 异常点丢弃 |
| `LimitHistoryPoint` | `limitUpCount` | 当日涨停总家数（含ST） | 只 | 否 | 后端 | 0 |
| `LimitHistoryPoint` | `limitDownCount` | 当日跌停总家数（含ST） | 只 | 否 | 后端 | 0 |

---

## 5. 数据来源与映射（事实层）

| 业务字段 | 来源表 | 来源列 | 转换规则 | 备注 |
|---|---|---|---|---|
| 涨停总家数 | `core_serving.limit_list_ths` | `trade_date, ts_code, limit_type` | `count(distinct ts_code) where limit_type='涨停池'` | 当日 |
| 跌停总家数 | `core_serving.limit_list_ths` | 同上 | `count(distinct ts_code) where limit_type='跌停池'` | 当日 |
| 炸板总家数 | `core_serving.limit_list_ths` | 同上 | `count(distinct ts_code) where limit_type='炸板池'` | 当日 |
| ST 涨停/跌停/炸板家数 | `core_serving.equity_stock_st` + `core_serving.limit_list_ths` | `ts_code, trade_date` | 三个集合分别与 ST 集合做交集计数 | 当日 |
| 连板家数 | `core_serving.limit_step` | `nums, ts_code, trade_date` | `count(distinct ts_code) where nums::int>=2` | 当日 |
| 最高连板 | `core_serving.limit_step` | `nums` | `max(nums::int)` | 当日 |
| 天地板/地天板 | `core_serving.limit_list_ths` | `first_lu_time,last_ld_time,first_ld_time,last_lu_time` | 按规则判定（见第 6 章） | 当日 |
| 涨停板块分布 | `core_serving.limit_cpt_list` | `ts_code,name,up_nums,rank` | 按板块统计涨停家数，排序后取 Top5 | 今日/昨日 |
| 跌停/炸板结构 | `core_serving.limit_list_ths` + `core_serving.equity_stock_st` + `core_serving.dc_member` + `core_serving.dc_index` | 同上 | 跌停与炸板分别分组计数 TopN（含 ST 风险行） | 今日/昨日 |
| 历史组合柱图 | `core_serving.limit_list_ths` + `core_serving.trade_calendar` | `trade_date,ts_code,limit_type` | 最近 22/62 交易日逐日统计涨停/跌停总数 | 1个月/3个月 |

补充：

1. 主源优先级：`limit_list_ths` 为主源；`limit_step` 提供连板补充；`equity_stock_st` 提供 ST 标签。
2. 回退策略：结构映射缺失时不跨日补值，进入 `PARTIAL` 并输出模块异常。
3. 数据时效语义：盘后快照语义（当前非实时流）。

---

## 6. 核心计算规则（冻结）

### 6.1 ST 分层计数

1. `limitUpTotal = |U|`，`U = {ts_code | limit_type='涨停池'}`  
2. `limitUpSt = |U ∩ ST|`  
3. `limitDownTotal = |D|`，`D = {ts_code | limit_type='跌停池'}`  
4. `limitDownSt = |D ∩ ST|`  
5. `brokenTotal = |B|`，`B = {ts_code | limit_type='炸板池'}`  
6. `brokenSt = |B ∩ ST|`

### 6.2 封板率（非ST口径）

1. `nonStLimitUp = limitUpTotal - limitUpSt`
2. `nonStBroken = brokenTotal - brokenSt`
3. `touchCount = nonStLimitUp + nonStBroken`
4. `sealingRate = nonStLimitUp / touchCount`
5. 若 `touchCount=0`，则 `sealingRate=null`，并记录异常码 `LU_SEAL_RATE_DENOM_ZERO`。

### 6.3 天地板 / 地天板

前置条件：

1. 同一 `trade_date + ts_code` 必须可获得可比较的时间字段。
2. 时间字段格式必须可解析为 `HH:mm[:ss]`。

判定规则：

1. 天地板：`first_lu_time` 与 `last_ld_time` 均存在，且 `first_lu_time < last_ld_time`。
2. 地天板：`first_ld_time` 与 `last_lu_time` 均存在，且 `first_ld_time < last_lu_time`。

降级规则：

1. 若当日样本中时间字段有效占比低于阈值（默认 70%），两卡返回 `null`，异常 `LU_PATTERN_INPUT_MISSING`。
2. 若同一股票同时命中天地与地天判定，计入冲突样本并排除统计，异常 `LU_PATTERN_CONFLICT`。

### 6.4 结构分布

1. 涨停板块分布：读取 `limit_cpt_list` 当日数据，按 `rank` 升序（并以 `up_nums` 降序打破并列）取 Top5。
2. 跌停结构：以 `D` 为基础集合，输出 Top2（优先展示 `ST风险` 行，其余按板块计数降序）。
3. 炸板结构：以 `B` 为基础集合，输出 Top3（板块计数降序）。
4. 字段语义：涨停板块分布主值为 `upNums`（单位：只），不返回“全市场占比”字段。
5. 柱长规则：前端按“榜内最大 `upNums`”做相对长度归一化（仅展示规则，不是业务统计值）。

---

## 7. 状态语义

1. 页面级状态：`READY/PARTIAL/DELAYED/EMPTY/ERROR`。
2. 模块级状态（debug）：返回 `expectedTradeDate/observedTradeDate/lagDays/status/note`。
3. `DELAYED` 判定：`observedTradeDate < expectedTradeDate`。
4. `PARTIAL` 判定：
   - 统计卡可算，但今日/昨日结构有一块缺失；
   - 或天地板/地天板进入降级；
   - 或历史样本不足。

---

## 8. 异常语义

1. 异常对象结构：`module/code/severity/message/details`。
2. 用户可见策略：正式态不展示异常码。
3. debug 可见策略：`debug=1` 返回模块异常明细（生产禁用）。

异常码要求：

1. 必须登记到 [exception-code-registry.md](/Users/congming/github/goldenshare/wealth/docs/system/exception-code-registry.md)。
2. 未登记异常码禁止进入代码与 API 契约。

---

## 9. API 契约（需求层）

1. 接口路径：`GET /api/v1/wealth/market/limit-up/summary`
2. 请求参数：`market/tradeDate/debug`
3. 响应结构：`tradingDay + pageStatus + limitUp + debugInfo?`
4. 字段命名规则：lowerCamelCase + 语义化字段名
5. 向后兼容策略：只增不改，不改既有字段语义

---

## 10. 实现过程与耗时预估（方案级）

### 10.1 后端执行过程（单次请求）

1. 解析交易日上下文（`expectedTradeDate`、`prevTradeDate`）。
2. 构建当日涨停/跌停/炸板集合与 ST 集合并做交集统计。
3. 计算封板率（非ST）。
4. 读取 `limit_step` 计算连板家数与最高板。
5. 判定天地板/地天板并处理降级。
6. 计算今日结构（涨停板块分布 + 跌停/炸板结构）。
7. 计算昨日结构（同算法，同输出结构）。
8. 计算历史 1个月/3个月 组合柱图。
9. 归并状态与异常，输出响应。

### 10.2 耗时预估（同机房 PostgreSQL，P95）

1. 当日统计 + ST 交集：`60ms ~ 120ms`
2. 连板统计（limit_step）：`10ms ~ 25ms`
3. 天地板/地天板判定：`15ms ~ 40ms`
4. 今日 + 昨日结构分布：`70ms ~ 140ms`
5. 历史组合柱（22/62）：`25ms ~ 60ms`
6. 状态归并 + 序列化：`10ms ~ 20ms`

模块总体预算：

1. P95 `< 380ms`
2. 返回体大小 `< 180KB`

---

## 11. 验收标准

1. 功能验收：完整返回 2×2 四块数据。
2. 口径验收：涨停/跌停卡展示 `总数/ST数`，封板率排除 ST。
3. 规则验收：天地板/地天板规则可解释，降级可追因。
4. 结构验收：今日/昨日结构算法一致。
5. 状态验收：debug 可追因 delayed/partial/empty/error。
6. 异常验收：仅使用注册表异常码。

---

## 12. 待最终确认项（冻结前）

1. 涨停/跌停卡必须展示 `总数/ST数`。
2. 封板率口径固定排除 ST。
3. 天地板/地天板必须有“判定规则 + 数据前置条件 + 降级行为”。
4. 今日与昨日结构必须同算法。
5. 方案整体仍处于评审中，未进入冻结态，禁止开工编码。

---

## 13. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-09 | 首版：冻结涨跌停统计与分布模块业务口径（2×2 + ST分层 + 封板率 + 天地/地天降级） | Codex |
