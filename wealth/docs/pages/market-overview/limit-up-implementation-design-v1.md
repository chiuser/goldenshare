# 市场总览｜涨跌停统计与分布技术实施方案 v1（implementation-design）

> 用途：把“涨跌停统计与分布（2×2）”需求转成可实施技术方案。  
> 阶段：编码前。  
> 产物性质：实现设计基线（不写业务代码）。

> 当前状态：`Frozen / 已生效`。  
> 说明：实施口径拍板与门禁签字已完成；本文作为当前实现与后续迭代的实施基线。

---

## 1. 文档目的

1. 对应需求文档：  
   [limit-up-benchmark-requirement-v1.md](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/limit-up-benchmark-requirement-v1.md)
2. 本文目标：冻结本模块的数据链路、查询编排、状态异常、性能预算与实现落位。
3. 本文不做：不落业务代码，不改页面样式，不改连板天梯模块实现。
4. 跨模块抽象门禁原则适配结论：8 条原则全部适用，无免除项。

关联门禁：  
[limit-up-m2-coding-gate-v1.md](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/limit-up-m2-coding-gate-v1.md)

---

## 1.1 跨模块抽象门禁原则适配（必填）

| 原则 | 本模块结论 | 设计落点 | 计划测试 |
|---|---|---|---|
| 事实源单一原则 | 统计事实全部后端产出 | 第 3 节、第 5 节 | 后端 API 字段完整性断言 |
| 契约先行与冻结原则 | DTO 先冻结再编码 | 第 3.1/3.2 节 | 契约快照测试 + 前端类型校验 |
| 配置一致性原则 | 仅允许策略中心配置项接入 | 第 5.2 节、第 8 节 | 配置读取路径测试 |
| 默认行为显式原则 | 未命中文本规则返回 0；缺映射进入 PARTIAL | 第 5.4 节、第 6.2 节 | 异常/降级分支测试 |
| 排序与筛选确定性原则 | Top5/Top3 固定排序与 fallback 范围 | 第 5.2 节 | 排序稳定性测试 |
| 性能预算前置原则 | P95 与 payload 预算冻结 | 第 8 节 | 接口耗时与 payload 预算测试 |
| 可观测与异常标准化原则 | 异常码统一注册，debug 结构化 | 第 7 节 | 异常码覆盖矩阵测试 |
| 测试以用户可见结果为中心原则 | 真实 API + 前端展示双门禁 | 第 10.1 节 | 后端集成 + 前端 smoke |

---

## 2. 代码现状审计（必须基于真实代码）

### 2.1 已有可复用能力

1. 交易日与盘后切换语义：
   - `src/biz/queries/wealth/market/summary/summary_state_query.py`
2. 涨跌停基础统计聚合（仅总数）：
   - `src/biz/queries/wealth/market/summary/summary_metrics_query.py`
3. 核心模型：
   - `src/foundation/models/core/limit_list_ths.py`
   - `src/foundation/models/core/limit_cpt_list.py`
   - `src/foundation/models/core/limit_step.py`
   - `src/foundation/models/core/equity_stock_st.py`
   - `src/foundation/models/core/ths_member.py`

### 2.2 当前缺口

1. 缺少独立 `limit-up` 模块 API、schema、query、service。
2. 缺少 ST 分层卡口径（当前 summary 只算总数，不含 ST 分层）。
3. 缺少封板率“排除 ST”口径。
4. 缺少天地板/地天板文本词典规则实现。
5. 缺少今日/昨日结构（涨停板块分布 + 领涨股涨停表现）独立查询链路。
6. 缺少该模块独立异常码映射和门禁样例。

### 2.3 结论

1. 新增独立模块 `limit_up`，不复用 `summary` 输出结构，避免耦合变脆。
2. 由后端统一产出模块对象，前端不参与统计。
3. 对天地板/地天板采用“文本词典判定 + 未命中即0”的确定性协议。

---

## 3. 分层架构与目录落点

### 3.1 接口范围

1. 模块接口路径：`GET /api/v1/wealth/market/limit-up/summary`
2. 是否整页聚合接口：否（模块接口）
3. 返回范围：仅 `limitUp` 模块对象 + 必要状态与 debug 信息

### 3.2 代码目录模板（按模块拆分）

```text
src/biz/
  api/
    wealth/
      market/
        limit_up.py
  queries/
    wealth/
      market/
        limit_up/
          limit_up_state_query.py
          limit_up_summary_query.py
          limit_up_structure_query.py
          limit_up_history_query.py
          limit_up_query_service.py
  schemas/
    wealth/
      market/
        limit_up.py
  services/
    wealth/
      market/
        limit_up/
          limit_up_status_resolver.py
          limit_up_exception_builder.py
          limit_up_rule_engine.py
```

---

## 4. 数据流与执行链路

1. 请求入口：`api.wealth.market.limit_up`
2. 参数校验：`market/tradeDate/debug`
3. 状态上下文：
   - `limit_up_state_query` 解析 `expectedTradeDate/prevTradeDate/sessionStatus`
4. 核心统计：
   - `limit_up_summary_query` 产出 8 卡核心原始值
5. 结构分布：
   - `limit_up_structure_query` 产出今日结构 + 昨日结构
6. 历史柱图：
   - `limit_up_history_query` 产出 `oneMonth/threeMonth`
7. 规则层：
   - `limit_up_rule_engine` 负责封板率与天地/地天板文本判定
8. 状态归并：
   - `limit_up_status_resolver` 产出模块状态
9. 异常组装：
   - `limit_up_exception_builder`
10. 响应输出：
   - `schemas.wealth.market.limit_up`

---

## 5. 查询编排策略

## 5.1 主查询（8 卡核心统计）

输入：`trade_date`

步骤：

1. 生成三个股票集合：
   - `U`：涨停池
   - `D`：跌停池
   - `B`：炸板池
2. 生成 ST 集合 `ST`（`equity_stock_st` 同交易日）
3. 计算：
   - `|U|, |D|, |B|`
   - `|U∩ST|, |D∩ST|, |B∩ST|`
4. 读取连板（排除 ST）：
   - `streakCount = count(distinct ts_code) where nums::int>=2 and ts_code not in ST`
   - `maxBoard = max(nums::int) where ts_code not in ST`
5. 判定天地板/地天板：
   - 使用 `limit_list_ths.tag/status/lu_desc` 文本词典
   - 命中“天地天板”时双计；未命中返回 0

## 5.2 辅助查询（今日/昨日结构）

对 `trade_date in {today, prev_trade_date}` 分别执行同一逻辑：

1. 涨停板块分布：
   - 直接读取 `limit_cpt_list` 当日数据（同花顺板块口径）
   - 先排除 ST 板块（默认 `885699.TI`，由策略中心配置）
   - 排序：`rank` 升序 + `up_nums` 降序
   - 输出 Top5；若不足 5 个，顺延补齐到 5 个
2. 选中板块：
   - 默认取 Top1 板块，写入 `selectedSectorCode`
3. 领涨股涨停表现：
   - 先基于 Top5 板块，从 `ths_member` 取 `con_code`（板块成分股票）
   - 成分有效性按请求日过滤：`(in_date is null or in_date <= tradeDate)` 且（`out_date is null` 或 `out_date >= tradeDate`）
   - 候选池先排除 ST 股票；
   - 严格候选 = 非ST成分股集合 ∩ 当日 `limit_list_ths(limit_type='涨停池')`
   - 若严格候选不足 3 只，仅在“同板块非ST成分股”内 fallback 补齐，不跨板块
   - 对每个板块独立排序并取 Top3（不是全局 Top3）：
     - 第一优先级：`current_board_count`（当日连板数，来自 `limit_step.nums`）降序
     - 第二优先级：`recent_limit_count_n`（近 N 个交易日涨停次数，来自 `limit_list_ths`）降序
     - 第三优先级：`changePct` 降序
     - 第四优先级：`stockCode` 升序
   - 默认 `N=10`（最近 10 个交易日）
   - 排序结果写入 `leaderStocks[selectedSectorCode]`
   - 允许同一股票出现在多个板块的 Top3（不做跨板块去重）
4. 选中股票：
   - 默认取 Top3 第一只，写入 `selectedStockCode`
5. 输出字段：
   - 板块分布输出 `limitUpCount`（单位：只）
   - 领涨股表现输出 `latestPrice/changePct/streakLabel/recentLimitText/firstLimitTime/openTimes/sealedAmountDisplayText`
6. 柱长规则（前端展示）：
   - 前端按榜内最大值做归一化长度：`barWidth = currentCount / maxCountInCurrentBlock`
   - 今日与昨日独立归一化

字段映射细化：

1. `latestPrice`：`limit_list_ths.price`（缺失回退 `equity_daily_bar.close`）。
2. `changePct`：`limit_list_ths.pct_chg`（缺失回退 `equity_daily_bar.pct_chg`）。
3. `firstLimitTime`：`limit_list_ths.first_lu_time`。
4. `openTimes`：`limit_list_ths.open_num`。
5. `sealedAmountDisplayText`：`limit_list_ths.limit_amount` 经展示层格式化。

## 5.3 历史查询（组合柱图）

1. 交易日窗口：
   - `1个月`：最近 22 个交易日
   - `3个月`：最近 62 个交易日
2. 按交易日统计：
   - `limitUpCount`：涨停总家数（含ST）
   - `limitDownCount`：跌停总家数（含ST）
3. 输出升序点列。

## 5.4 空数据与异常数据处理

1. 当日 `U/D/B` 全空：模块 `EMPTY`，异常 `LU_SOURCE_EMPTY`。
2. 结构映射缺失（板块成分或行情表现无法形成有效 TopN）：模块 `PARTIAL`，异常 `LU_DISTRIBUTION_MAPPING_MISSING`。
3. 历史窗口样本不足：模块 `PARTIAL`，异常 `LU_HISTORY_INCOMPLETE`。
4. `limit_cpt_list` 当日无数据但涨停主集合不为空：`sectors=[]`，模块 `PARTIAL`，异常 `LU_DISTRIBUTION_MAPPING_MISSING`。

---

## 6. 计算实现细节（冻结）

### 6.1 封板率（排除 ST）

1. `nonStLimitUp = limitUpTotal - limitUpSt`
2. `nonStBroken = brokenTotal - brokenSt`
3. `touchCount = nonStLimitUp + nonStBroken`
4. `sealingRate = nonStLimitUp / touchCount`
5. `touchCount=0` -> `sealingRate=null` + `LU_SEAL_RATE_DENOM_ZERO`

### 6.2 天地板 / 地天板

词典判定：

1. 判定字段：`limit_list_ths.tag/status/lu_desc`
2. 天地板命中词：`天地板`、`天地天板`
3. 地天板命中词：`地天板`、`天地天板`
4. 排除词：`昨日地天板`、`前一交易日地天板`、`昨日天地板`、`前一交易日天地板`
5. 双计规则：命中 `天地天板` 时同时计入天地板与地天板
6. 未命中任何词时返回 0（不返回 `null`）

---

## 7. 状态与异常落地

1. `pageStatus`：沿用页面聚合规则。
2. `moduleStatus`（debug）：
   - `moduleKey=limitUp`
   - `expectedTradeDate/observedTradeDate/lagDays/status/note`
3. debug 输出：
   - `debug=1` 返回；
   - 生产环境禁用。
4. 异常码映射（引用注册表）：
   - `LU_SOURCE_DELAYED`
   - `LU_SOURCE_EMPTY`
   - `LU_SEAL_RATE_DENOM_ZERO`
   - `LU_DISTRIBUTION_MAPPING_MISSING`
   - `LU_HISTORY_INCOMPLETE`
   - `LU_QUERY_FAILED`

---

## 8. 性能与耗时预估

### 8.1 单链路耗时预估（P95）

1. 主统计（`limit_list_ths + equity_stock_st + limit_step`）：`85ms ~ 160ms`
2. 今日结构分布 + 领涨股表现：`45ms ~ 110ms`
3. 昨日结构分布 + 领涨股表现：`45ms ~ 110ms`
4. 历史窗口（22/62）：`30ms ~ 70ms`
5. 状态归并 + 序列化：`10ms ~ 20ms`

### 8.2 模块总体预算

1. 模块 P95：`< 380ms`
2. 返回体：`< 180KB`
3. 并发预算：与 overview 模块并发预算一致

### 8.3 二期缓存策略（可选，不在本期实现）

1. key：`wealth:limit-up:{tradeDate}:{market}`
2. 失效：交易日切换或源数据刷新后失效

---

## 9. 安全与权限

1. 鉴权依赖：沿用 `quote.read`
2. 权限点：本期不新增独立权限点
3. 防误用：
   - 非法参数 `400001`
   - debug 生产禁用

---

## 10. 测试与验证计划

1. 单元测试：
   - ST 分层统计
   - 封板率计算
   - 天地/地天文本词典判定（含排除词与双计）
2. 集成测试：
   - 今日结构 + 昨日结构一致性
   - 历史 22/62 窗口输出
   - delayed/partial/empty/error 四态
3. 冒烟：
   - 2×2 全结构渲染
   - 指标卡显示 `总数/ST数`
   - 真实源请求 pending 时展示 loading（不展示 mock 回填）
   - 真实源请求超过 5 秒展示 error（不回填 mock）
4. 失败回滚与观测：
   - 查询失败仅影响模块，不阻塞整页其他模块

---

## 10.1 核心测试 case（必填）

1. 核心字段清单（页面可见要素）：
   - 统计卡：`limitUpCount/limitDownCount/brokenLimitCount/sealingRate/streakCount/maxBoard/skyToFloorCount/floorToSkyCount`
   - 结构块：`sectors[].limitUpCount`、`leaderStocks[].stockCode/stockName/changePct/streakLabel/recentLimitText`
   - 历史：`historyPoints.oneMonth[].limitUpCount/limitDownCount`、`historyPoints.threeMonth[].limitUpCount/limitDownCount`
   - 状态与异常：`pageStatus.status`、`debugInfo.modules[].status`、`debugInfo.exceptions[].code`
2. 后端真实 API 集成测试设计（非 mock service/query）：
   - `tests/web/test_wealth_market_limit_up_api.py`
   - 覆盖正常/partial/delayed/error 及 ST 分层、封板率、Top5/Top3 规则断言
3. 前端真实 API 展示校验设计（非 mock adapter）：
   - `wealth/src/test/market-overview-limit-up-real-api.smoke.test.ts`
   - 覆盖 2×2 渲染、统计卡格式、结构联动、状态与错误提示
4. 执行命令与通过标准：
   - `pytest -q tests/web/test_wealth_market_limit_up_api.py`
   - `cd wealth && npm run test -- src/test/market-overview-limit-up-real-api.smoke.test.ts`
   - 通过标准：字段断言全绿 + 页面关键要素与后端字段一一对应

## 10.2 参考 case（可复用）

1. “接口返回成功但结构块为空”：验证是否命中 `LU_DISTRIBUTION_MAPPING_MISSING`。
2. “同分排序漂移”：验证 Top3 板块内排序主次序是否固定。
3. “字段存在但页面空值”：验证后端契约字段与前端消费字段逐项对齐。
4. “默认行为不清”：验证 strict 与 fallback 路径均有断言。

---

## 11. 分期里程碑

1. M1（方案冻结）：口径、对象、异常、性能冻结
2. M2（后端实现）：API/query/schema/service 完整落地
3. M3（前端接入）：模块 source 切 real，样式不改
4. M4（回归发布）：联调 + 压测 + 灰度验收

---

## 12. 风险与缓解

1. 风险：`limit_list_ths` 文本描述语义变更可能影响天地/地天命中稳定性。  
   缓解：词典规则配置化 + 关键样本回归。
2. 风险：`limit_cpt_list` 当日缺数导致涨停板块分布为空。  
   缓解：模块标记 `PARTIAL`，并返回结构化异常用于 debug 追因。
3. 风险：`ths_member` 板块成分映射缺失导致结构块不完整。  
   缓解：进入 `PARTIAL`，输出异常码并保留其他块。
4. 风险：统计口径被前端二次解释。  
   缓解：后端直接返回结构化字段，前端仅展示。

---

## 13. 本轮已确认口径（已冻结）

1. 涨停/跌停卡同时展示“总数/ST数”，封板率严格排除 ST。
2. 除统计卡外，默认排除 ST 股票（含连板统计、板块领涨候选）。
3. 板块分布排除 ST 板块并顺延补齐 Top5。
4. 候选不足 Top3 时，仅允许同板块非ST fallback，不跨板块。
5. 天地板/地天板按“文本词典 + 排除词 + 天地天双计”执行，未命中返回 0。
6. 今日/昨日结构同算法、同模型输出，且允许同股跨板块重复。

---

## 14. 待拍板项（本轮）

1. 业务口径待拍板项：无（已清零）。
2. 门禁签字与测试门禁已完成，当前无阻塞项。

---

## 15. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-09 | 首版：冻结涨跌停统计与分布模块实施方案（2×2、ST分层、天地/地天降级、结构分布） | Codex |
| v1.1 | 2026-05-10 | 对齐拍板口径：ST默认排除、ST板块过滤并补齐Top5、同板块fallback、天地/地天文本词典与双计、允许跨板块重复股票 | Codex |
| v1.2 | 2026-05-10 | 对齐最新三件套模板：补齐 8 条门禁原则映射、核心测试 case 门禁、待拍板项清零说明 | Codex |
| v1.3 | 2026-05-11 | 收口状态：从 Draft 切换为 Frozen，确认门禁签字完成并生效 | Codex |
