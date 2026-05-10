# 市场总览｜涨跌停统计与分布技术实施方案 v1（implementation-design）

> 用途：把“涨跌停统计与分布（2×2）”需求转成可实施技术方案。  
> 阶段：编码前。  
> 产物性质：实现设计基线（不写业务代码）。

> 当前状态：`Draft / 待评审`（未冻结）。  
> 说明：本文是候选实施方案，不代表可直接开工；必须等最终拍板后再进入编码。

---

## 1. 文档目的

1. 对应需求文档：  
   [limit-up-benchmark-requirement-v1.md](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/limit-up-benchmark-requirement-v1.md)
2. 本文目标：冻结本模块的数据链路、查询编排、状态异常、性能预算与实现落位。
3. 本文不做：不落业务代码，不改页面样式，不改连板天梯模块实现。

关联门禁：  
[limit-up-m2-coding-gate-v1.md](/Users/congming/github/goldenshare/wealth/docs/pages/market-overview/limit-up-m2-coding-gate-v1.md)

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
   - `src/foundation/models/core/dc_member.py`
   - `src/foundation/models/core/dc_index.py`

### 2.2 当前缺口

1. 缺少独立 `limit-up` 模块 API、schema、query、service。
2. 缺少 ST 分层卡口径（当前 summary 只算总数，不含 ST 分层）。
3. 缺少封板率“排除 ST”口径。
4. 缺少天地板/地天板规则实现与降级语义。
5. 缺少今日/昨日结构（涨停板块分布 + 跌停/炸板结构）独立查询链路。
6. 缺少该模块独立异常码映射和门禁样例。

### 2.3 结论

1. 新增独立模块 `limit_up`，不复用 `summary` 输出结构，避免耦合变脆。
2. 由后端统一产出模块对象，前端不参与统计。
3. 对天地板/地天板采用“可算就算，不可算就降级”的确定性协议。

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
          limit_up_distribution_query.py
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
   - `limit_up_distribution_query` 产出今日结构 + 昨日结构
6. 历史柱图：
   - `limit_up_history_query` 产出 `oneMonth/threeMonth`
7. 规则层：
   - `limit_up_rule_engine` 负责封板率与天地/地天板判定、降级
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
4. 读取连板：
   - `streakCount = count(distinct ts_code) where nums::int>=2`
   - `maxBoard = max(nums::int)`
5. 判定天地板/地天板：
   - 使用 `first_lu_time/last_ld_time/first_ld_time/last_lu_time`
   - 调用 `limit_up_rule_engine`，应用前置条件与降级规则

## 5.2 辅助查询（今日/昨日结构）

对 `trade_date in {today, prev_trade_date}` 分别执行同一逻辑：

1. 涨停板块分布：
   - 直接读取 `limit_cpt_list` 当日数据（同花顺板块口径）
   - 排序：`rank` 升序 + `up_nums` 降序
   - 输出 Top5
2. 跌停结构：
   - `D` 集合优先产出 `ST风险`（`D∩ST`）  
   - 其余按板块聚合，补足 Top2
3. 炸板结构：
   - `B` 集合按板块聚合 Top3
4. 输出字段：
   - 涨停分布输出涨停家数字段（语义名 `upNums`，传输字段可统一为 `count`，单位：只）
   - 跌停/炸板结构输出 `count`（单位：只）
5. 柱长规则（前端展示）：
   - 前端按榜内最大值做归一化长度：`barWidth = currentCount / maxCountInCurrentBlock`
   - 今日与昨日独立归一化

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
2. 结构映射缺失（`dc_member/dc_index` 无法形成有效 TopN）：模块 `PARTIAL`，异常 `LU_DISTRIBUTION_MAPPING_MISSING`。
3. 天地/地天前置条件不足：两卡 `null`，异常 `LU_PATTERN_INPUT_MISSING`。
4. 历史窗口样本不足：模块 `PARTIAL`，异常 `LU_HISTORY_INCOMPLETE`。
5. `limit_cpt_list` 当日无数据但涨停主集合不为空：`limitUpSectorDistribution=[]`，模块 `PARTIAL`，异常 `LU_DISTRIBUTION_MAPPING_MISSING`。

---

## 6. 计算实现细节（冻结）

### 6.1 封板率（排除 ST）

1. `nonStLimitUp = limitUpTotal - limitUpSt`
2. `nonStBroken = brokenTotal - brokenSt`
3. `touchCount = nonStLimitUp + nonStBroken`
4. `sealingRate = nonStLimitUp / touchCount`
5. `touchCount=0` -> `sealingRate=null` + `LU_SEAL_RATE_DENOM_ZERO`

### 6.2 天地板 / 地天板

前置条件：

1. 当日可解析时间字段样本占比 >= 70%
2. 时间值可比较（`HH:mm[:ss]`）

判定：

1. 天地板：`first_lu_time < last_ld_time`
2. 地天板：`first_ld_time < last_lu_time`

冲突：

1. 同一股票同时命中两类时不计入任一类，记录 `LU_PATTERN_CONFLICT`。

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
   - `LU_PATTERN_INPUT_MISSING`
   - `LU_PATTERN_CONFLICT`
   - `LU_DISTRIBUTION_MAPPING_MISSING`
   - `LU_HISTORY_INCOMPLETE`
   - `LU_QUERY_FAILED`

---

## 8. 性能与耗时预估

### 8.1 单链路耗时预估（P95）

1. 主统计（`limit_list_ths + equity_stock_st + limit_step`）：`85ms ~ 160ms`
2. 今日结构分布：`45ms ~ 90ms`
3. 昨日结构分布：`45ms ~ 90ms`
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
   - 天地/地天判定与降级
2. 集成测试：
   - 今日结构 + 昨日结构一致性
   - 历史 22/62 窗口输出
   - delayed/partial/empty/error 四态
3. 冒烟：
   - 2×2 全结构渲染
   - 指标卡显示 `总数/ST数`
4. 失败回滚与观测：
   - 查询失败仅影响模块，不阻塞整页其他模块

---

## 11. 分期里程碑

1. M1（方案冻结）：口径、对象、异常、性能冻结
2. M2（后端实现）：API/query/schema/service 完整落地
3. M3（前端接入）：模块 source 切 real，样式不改
4. M4（回归发布）：联调 + 压测 + 灰度验收

---

## 12. 风险与缓解

1. 风险：`limit_list_ths` 时间字段覆盖不足，天地/地天不可稳算。  
   缓解：明确降级，不输出伪数字。
2. 风险：`limit_cpt_list` 当日缺数导致涨停板块分布为空。  
   缓解：模块标记 `PARTIAL`，并返回结构化异常用于 debug 追因。
3. 风险：`dc_member` 或 `dc_index` 映射缺失导致结构块不完整。  
   缓解：进入 `PARTIAL`，输出异常码并保留其他块。
4. 风险：统计口径被前端二次解释。  
   缓解：后端直接返回结构化字段，前端仅展示。

---

## 13. 待最终确认项（冻结前）

1. 涨停/跌停卡同时展示“总数/ST数”。
2. 封板率严格排除 ST。
3. 天地板/地天板按“前置条件 + 判定规则 + 降级行为”执行。
4. 今日/昨日结构同算法、同模型输出。
5. 本方案尚未冻结，编码阶段不可启动。

---

## 14. 版本记录

| 版本 | 日期 | 变更摘要 | 负责人 |
|---|---|---|---|
| v1 | 2026-05-09 | 首版：冻结涨跌停统计与分布模块实施方案（2×2、ST分层、天地/地天降级、结构分布） | Codex |
