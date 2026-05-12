# 市场总览｜涨跌停统计与分布标杆需求 v1（benchmark-requirement）

> 用途：定义“涨跌停统计与分布（2×2）”模块的业务边界、统计口径与降级语义。  
> 阶段：需求已冻结。  
> 产物性质：业务规则事实源（不是实现细节文档）。

> 当前状态：`Frozen / 已生效`。  
> 说明：口径拍板与门禁签字已完成；本文件作为当前实现与后续迭代的需求事实源。

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
   - 右上：今日“涨停板块分布｜领涨股涨停表现”
   - 左下：历史涨跌停组合柱图（`1个月` / `3个月`）
   - 右下：昨日“涨停板块分布｜领涨股涨停表现”
2. 涨停/跌停卡必须同时展示“总数/ST数”，格式固定为 `总数/ST数`。
3. 封板率口径固定为“不包含 ST 涨停板股票”。
4. 天地板/地天板采用可审计文本词典规则；未命中时返回 `0`，不允许伪造数字。

### 2.2 本期不覆盖

1. 不做盘中实时 tick 级判定。
2. 不做策略预测或交易建议。
3. 不改连板天梯模块（连板天梯单独模块治理）。

### 2.3 与其他模块边界

1. `limitUp` 是独立模块，只维护“涨跌停统计与分布”自身字段真值表。
2. 本模块三件套不维护连板天梯、榜单、板块总览等其它模块字段。
3. 即使与其它模块共享同一来源表（如 `limit_list_ths`、`trade_calendar`），也仅做共享来源说明，不做模块耦合设计。
1. 上游依赖：
   - `core_serving.limit_list_ths`
   - `core_serving.limit_cpt_list`
   - `core_serving.limit_step`
   - `core_serving.equity_stock_st`
   - `core_serving.ths_member`
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
   - 使用 `limit_list_ths.tag/status/lu_desc` 的文本词典判定；
   - 未命中文本时按 `0` 处理，不返回 `null`；
   - 命中“天地天板”时同时计入天地板与地天板（双计）。
5. 分布结构约束：
   - 今日与昨日结构必须使用同一算法；
   - 不允许“今日一个算法、昨日另一个算法”。
6. 默认排除约束：
   - 除“总数/ST数统计卡”外，其它业务计算默认排除 ST 股票；
   - 右侧结构块默认排除 `ST板块`，并顺延补齐 Top5。

禁止事项：

1. 前端自行拼装涨跌停统计字段。
2. 在数据不足时用固定 mock 值冒充真实值。
3. 把 ST 口径混入封板率分母。

### 3.1 跨模块抽象门禁原则（需求层冻结）

1. 事实源单一：本模块事实字段全部由后端产出，前端仅消费。
2. 契约冻结：`summaryCards/todayStructure/yesterdayStructure/historyPoints` 字段语义本期冻结，不允许中途漂移。
3. 配置一致性：仅 `ST 板块排除代码`、`近N日窗口` 可配置，配置键名与生效时机必须由策略中心统一管理。
4. 默认行为显式：未命中天地/地天文本规则时返回 `0`，不是 `null`。
5. 排序筛选确定性：Top5 板块、Top3 领涨股都要固定主次排序和 fallback 范围。
6. 性能预算前置：模块 P95 `< 380ms`、payload `< 180KB`。
7. 可观测标准化：异常统一走 `exception-code-registry`，debug 输出结构化。
8. 用户可见结果优先：验收以页面展示结果为主，不以中间查询结果替代。

---

## 4. 业务对象模型（非代码，先语义）

1. `LimitUpPanel`：模块返回根对象。
2. `LimitSummaryCard`：8 个统计卡对象。
3. `LimitStructureBlock`：今日/昨日结构块（板块 + 领涨股表现联动）。
4. `LimitHistoryPoint`：历史组合柱图点。

字段语义要求：

| 对象 | 字段 | 含义 | 单位 | 可空 | 产出责任 | 缺失降级 |
|---|---|---|---|---|---|---|
| `LimitUpPanel` | `tradeDate` | 模块观测交易日 | - | 否 | 后端 | 缺失即异常 |
| `LimitSummaryCard` | `limitUpPair` | 涨停 `总数/ST数` | 只 | 否 | 后端 | `0/0` |
| `LimitSummaryCard` | `limitDownPair` | 跌停 `总数/ST数` | 只 | 否 | 后端 | `0/0` |
| `LimitSummaryCard` | `brokenLimitPair` | 炸板 `总数/ST数` | 只 | 否 | 后端 | `0/0` |
| `LimitSummaryCard` | `sealingRate` | 封板率（非ST） | % | 是 | 后端 | `null` + 降级说明 |
| `LimitSummaryCard` | `streakCount` | 连板家数（二板及以上，排除ST） | 只 | 否 | 后端 | `0` |
| `LimitSummaryCard` | `maxBoard` | 最高连板（整数板数，排除ST） | 板 | 否 | 后端 | `0` |
| `LimitSummaryCard` | `skyToFloorCount` | 天地板家数 | 只 | 否 | 后端 | `0` |
| `LimitSummaryCard` | `floorToSkyCount` | 地天板家数 | 只 | 否 | 后端 | `0` |
| `LimitStructureBlock` | `selectedSectorCode` | 当前选中板块代码 | - | 否 | 后端 | 回退第一行板块 |
| `LimitStructureBlock` | `selectedStockCode` | 当前选中股票代码 | - | 是 | 后端 | 空字符串 |
| `LimitStructureBlock` | `sectors[]` | 涨停板块分布 TopN（按涨停家数） | 只 | 否 | 后端 | 空数组 |
| `LimitStructureBlock` | `leaderStocks{}` | 板块维度领涨股表现列表 | - | 否 | 后端 | 空对象 |
| `LimitHistoryPoint` | `tradeDate` | 交易日 | - | 否 | 后端 | 异常点丢弃 |
| `LimitHistoryPoint` | `limitUpCount` | 当日涨停总家数（含ST） | 只 | 否 | 后端 | 0 |
| `LimitHistoryPoint` | `limitDownCount` | 当日跌停总家数（含ST） | 只 | 否 | 后端 | 0 |

---

## 5. 数据来源与映射（事实层）

> 口径声明：本章是“涨跌停统计与分布模块字段真值表”，只约束 `limitUp` 模块自身字段；不承担其它模块字段定义。

| 业务字段 | 来源表 | 来源列 | 转换规则 | 备注 |
|---|---|---|---|---|
| 涨停总家数 | `core_serving.limit_list_ths` | `trade_date, ts_code, limit_type` | `count(distinct ts_code) where limit_type='涨停池'` | 当日 |
| 跌停总家数 | `core_serving.limit_list_ths` | 同上 | `count(distinct ts_code) where limit_type='跌停池'` | 当日 |
| 炸板总家数 | `core_serving.limit_list_ths` | 同上 | `count(distinct ts_code) where limit_type='炸板池'` | 当日 |
| ST 涨停/跌停/炸板家数 | `core_serving.equity_stock_st` + `core_serving.limit_list_ths` | `ts_code, trade_date` | 三个集合分别与 ST 集合做交集计数 | 当日 |
| 连板家数 | `core_serving.limit_step` + `core_serving.equity_stock_st` | `nums, ts_code, trade_date` | `count(distinct ts_code) where nums::int>=2 and ts_code not in ST` | 当日 |
| 最高连板 | `core_serving.limit_step` + `core_serving.equity_stock_st` | `nums, ts_code, trade_date` | `max(nums::int) where ts_code not in ST` | 当日 |
| 天地板/地天板 | `core_serving.limit_list_ths` | `tag,status,lu_desc` | 文本词典判定（见第 6 章） | 当日 |
| 涨停板块分布 | `core_serving.limit_cpt_list` | `ts_code,name,up_nums,rank` | 先排除 ST 板块，再按涨停家数排序取 Top5，不足顺延补齐 | 今日/昨日 |
| 板块->成分映射 | `core_serving.limit_cpt_list` + `core_serving.ths_member` | `limit_cpt_list.ts_code -> ths_member.ts_code` + `ths_member.con_code` | 先排除 ST 板块并取 Top5，再映射每个板块成分股代码集合 | 今日/昨日 |
| 领涨股表现（候选池） | `core_serving.limit_cpt_list` + `core_serving.ths_member` | `ts_code,con_code,name` | 在 Top5 板块下生成每板块“非ST”候选池 | 今日/昨日 |
| 领涨股表现（排序字段） | `core_serving.limit_step` + `core_serving.limit_list_ths` + `core_serving.equity_stock_st` | `nums` + `trade_date,ts_code,limit_type` | 先取当日非ST严格候选；不足 Top3 时仅在同板块非ST中 fallback 补齐 | 今日/昨日 |
| 领涨股表现（补充字段） | `core_serving.limit_step` + `core_serving.equity_daily_bar` | `nums` + `close,pct_chg` | 生成 `streakLabel/recentLimitText/latestPrice/changePct` | 今日/昨日 |
| 历史组合柱图 | `core_serving.limit_list_ths` + `core_serving.trade_calendar` | `trade_date,ts_code,limit_type` | 最近 22/62 交易日逐日统计涨停/跌停总数 | 1个月/3个月 |

补充：

1. 主源优先级：`limit_list_ths` 为主源；`limit_step` 提供连板补充；`equity_stock_st` 提供 ST 标签。
2. 回退策略：结构映射缺失时不跨日补值，进入 `PARTIAL` 并输出模块异常。
3. 数据时效语义：盘后快照语义（当前非实时流）。
4. 共享来源说明：若其它模块复用相同表，仅共享数据事实，不共享本模块规则、排序与组装逻辑。

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

数据基础：

1. 使用 `limit_list_ths.tag/status/lu_desc` 文本字段判定。
2. 不依赖 `first_lu_time/last_ld_time/first_ld_time/last_lu_time` 成对时间字段。

判定规则：

1. 天地板：文本命中“天地板”或“天地天板”。
2. 地天板：文本命中“地天板”或“天地天板”。
3. 双计规则：命中“天地天板”时，同时计入天地板与地天板。
4. 排除词：命中“昨日地天板 / 前一交易日地天板 / 昨日天地板 / 前一交易日天地板”仅作为题材描述，不计入当日统计。
5. 未命中任何词时计数为 `0`，不返回 `null`。

### 6.4 结构分布

1. 涨停板块分布：读取 `limit_cpt_list` 当日数据，先排除 ST 板块（默认 `885699.TI`），再按 `rank` 升序（并以 `up_nums` 降序打破并列）取 Top5；若不足 5 个则顺延补齐。
2. 选中板块：默认取首行板块，写入 `selectedSectorCode`。
3. 板块成分来源：使用 `ths_member` 映射 Top5 板块的成分股（`ths_member.con_code`）；有效性判定采用 `(in_date is null or in_date <= tradeDate) and (out_date is null or out_date >= tradeDate)`。
4. 领涨股筛选范围：在每个板块成分股内，筛选“非ST”股票候选；严格候选为“非ST成分股 ∩ 当日涨停池”。
5. 领涨股排序口径（每板块独立排序）：
   - 第一优先级：`current_board_count`（当日连板数）降序；
   - 第二优先级：`recent_limit_count_n`（近 N 天涨停次数）降序；
   - 第三优先级：`changePct` 降序（并列打破）；
   - 第四优先级：`stockCode` 升序（最终稳定排序）。
6. TopN 输出：每个板块输出 Top3 领涨股（不是全局 Top3）；当严格候选不足 3 只时，仅在同板块非ST候选内 fallback 补齐，不跨板块。
7. 选中股票：默认取当前选中板块 Top3 的第一只，写入 `selectedStockCode`。
8. 字段语义：板块主值为涨停家数 `limitUpCount`（单位：只）；不返回“全市场占比”字段。
9. 柱长规则：前端按“榜内最大 `limitUpCount`”做相对长度归一化，仅用于展示。
10. N 天窗口定义：`N=10`（默认），按最近 10 个交易日统计 `limit_type='涨停池'` 的出现次数。
11. 重复股票策略：同一股票允许同时出现在多个板块的领涨股列表中，不做跨板块去重。

字段口径补充：

1. `latestPrice` 首选 `limit_list_ths.price`；若缺失可回退 `equity_daily_bar.close`。
2. `changePct` 首选 `limit_list_ths.pct_chg`；若缺失可回退 `equity_daily_bar.pct_chg`。
3. `firstLimitTime` 对应 `limit_list_ths.first_lu_time`。
4. `openTimes` 对应 `limit_list_ths.open_num`。
5. `sealedAmountDisplayText` 对应 `limit_list_ths.limit_amount` 的展示格式化文本。

---

## 7. 状态语义

1. 页面级状态：`READY/PARTIAL/DELAYED/EMPTY/ERROR`。
2. 模块级状态（debug）：返回 `expectedTradeDate/observedTradeDate/lagDays/status/note`。
3. `DELAYED` 判定：`observedTradeDate < expectedTradeDate`。
4. `PARTIAL` 判定：
   - 统计卡可算，但今日/昨日结构有一块缺失；
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
5. 按文本词典判定天地板/地天板（含排除词与双计）。
6. 计算今日结构（涨停板块分布 + 领涨股涨停表现）。
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
3. 规则验收：天地板/地天板规则按文本词典执行，未命中返回 `0`。
4. 结构验收：今日/昨日结构算法一致。
5. 状态验收：debug 可追因 delayed/partial/empty/error。
6. 异常验收：仅使用注册表异常码。

### 11.1 参考 case（可复用）

1. 筛选值若与真实数据口径不一致，会出现“接口成功但结构块为空”；该场景必须进入验收。
2. 同分排序若未固定主次序，会出现 Top3 漂移；必须在验收中覆盖。
3. 关键展示字段（`limitUpCount/limitDownCount/sealingRate/limitUpPair`）必须逐字段核对。
4. strict/fallback 默认行为必须有明确验收结论，不能留“运行时再看”。

---

## 12. 本轮已确认口径（已冻结）

1. 涨停/跌停卡必须展示 `总数/ST数`，封板率固定排除 ST。
2. 除统计卡外，其它业务计算默认排除 ST 股票。
3. 右侧板块分布排除 ST 板块（默认 `885699.TI`），不足 Top5 顺延补齐。
4. 领涨股候选不足 Top3 时，仅在同板块非ST候选内 fallback 补齐，不跨板块。
5. 天地板/地天板按文本词典判定，命中“天地天板”双计，未命中返回 0。
6. 同一股票允许出现在多个板块的 Top3 中（不跨板块去重）。

---

## 13. 待拍板项（本轮）

1. 业务口径待拍板项：无（已清零）。
2. 门禁签字流程已完成，当前无阻塞项。

---

## 14. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-09 | 首版：冻结涨跌停统计与分布模块业务口径（2×2 + ST分层 + 封板率 + 天地/地天降级） | Codex |
| v1.1 | 2026-05-10 | 对齐拍板口径：ST默认排除、ST板块过滤并补齐Top5、同板块fallback、天地/地天文本词典与双计、允许跨板块重复股票 | Codex |
| v1.2 | 2026-05-10 | 对齐最新三件套模板：补齐跨模块抽象门禁原则、验收参考 case、待拍板项清零说明 | Codex |
| v1.3 | 2026-05-11 | 收口状态：从 Draft 切换为 Frozen，确认门禁签字完成并生效 | Codex |
