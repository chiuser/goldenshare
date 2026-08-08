# 通用波浪识别 G0 冻结合同 v1

- 版本：v1-frozen
- 状态：G0 已完成并保持冻结；G1 已按本合同实现并通过验收；30/60 分钟竞价行过滤口径已补充冻结，adapter 尚未实现
- 更新时间：2026-08-08
- 适用范围：通用、因果、可回放的波浪识别研究内核
- 当前动作边界：用户已授权并完成 G1；尚未授权 G2、Dagster 资产或正式 Lake 读写
- 后续范围澄清：通用内核从 G1 起必须与 K 线周期无关；当前开发线程止于 G4，API、Wealth 与正式界面由其他线程后续集成

关联文档：

- [波浪浪型识别开源源码学习与 Goldenshare 适配审计 v1](/Users/congming/github/goldenshare/lake_console/docs/design/elliott-wave-source-study-and-goldenshare-adaptation-audit-v1.md)
- [通用波浪识别 G1 纯内核实现与验收记录 v1](/Users/congming/github/goldenshare/lake_console/docs/design/index-wave-g1-core-implementation-and-acceptance-v1.md)
- [指数四浪反弹失效与趋势反转量化回测方案 v1（独立专项案例，暂缓实施）](/Users/congming/github/goldenshare/docs/datasets/index-wave4-trend-reversal-backtest-plan-v1.md)
- [Dagster 数据管道性能治理规范](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-data-pipeline-performance-governance.md)
- [Dagster Asset Schema 合同](/Users/congming/github/goldenshare/lake_console/docs/design/dagster-asset-schema-contract-design.md)

---

## 0. 结论先行

G0 不负责“把波浪数出来”，而是先冻结以后所有实现都不能含糊的语言：输入 K 线是什么、一个拐点什么时候才可见、形成中的腿怎样变化、一个浪型场景怎样延长或失效、启发式分数怎样与概率分开，以及历史上某一天的判断怎样被完整重放。

本合同已经把这些概念收敛为六层结构：

```text
Canonical Bar
  -> Detector Profile
  -> Pivot Confirmation
  -> Confirmed Swing / Forming Leg
  -> Wave Scenario Snapshot
  -> Analysis Module / Outcome / Probability
```

其中四项边界已经由前序讨论确认：

1. 通用内核不内置四浪 MACD 案例；`MACD(7,52,7)` 仍是未来专项。
2. 日线、120 分钟、60 分钟、30 分钟及后续受支持周期分别独立运行同一内核；任何周期都不在通用内核里默认确认另一个周期。
3. 系统保留多个候选解释，不伪装成唯一正确数浪。
4. 启发式分数必须通过独立历史结果校准后，才可能成为概率。
5. 主要指数 30/60 分钟直接进入波浪分析时，`09:30` 集合竞价行只在 adapter 中过滤：不生成独立 Canonical Bar，也不并入第一根常规 K 线；该规则不改变上游 Silver 和 90/120 分钟派生合同。

第 15 节的 D01～D10 已全部确认并回写正文。G1 已按本文实现并通过 F01～F44；合同冻结和测试通过仍不代表启发式参数已经被 A 股历史样本验证，也不自动授权 G2 读取真实数据。

---

## 1. G0 的目标、依据、范围与影响面

### 1.1 开发目标

本阶段只交付以下内容：

1. 规范 bar、detector、pivot、swing、forming leg 和 scenario 的领域合同。
2. 冻结无未来函数所需的 `as_of/extreme_at/confirmed_at/visible_through` 语义。
3. 定义基础推动浪和基础锯齿修正浪的硬规则、软特征与三态求值。
4. 定义场景身份、演化链、生命周期和回放规则。
5. 定义分析模块、结果空间、标签、校准和概率展示门禁。
6. 定义 G1 必须落成自动测试的人工金标夹具。

### 1.2 依据

本稿依据以下当前事实：

- 源码学习结论：ta4j 的因果 ZigZag、多场景和 walk-forward 思路值得吸收，但原模型缺少完整 `confirmed_at` 与 Goldenshare 所需的版本身份。
- G0 冻结时的代码审计：仓库内当时尚无正式 pivot、wave、scenario 或概率校准引擎；G1 后已新增独立纯领域包，而不是给旧指标类增加字段。
- 当前输入能力：主要指数日线和已修复的 120 分钟线可作为后续 G2 验证输入，但不在 G0 被读取或重算。
- 当前指标边界：已有 MACD 计算与股票分钟指标链不属于波浪事实源，本轮不修改，也不复用为波浪内核。
- 仓库治理：算法正确性以后由独立金标和性质测试证明；正式资产 check 不应二次重算全量算法来证明公式。

### 1.3 本轮改动范围

本轮只允许修改：

- 本 G0 合同文档；
- 上游源码审计文档中的 G0 状态与链接；
- 文档总索引中的入口。

本轮禁止：

- 新增 `analysis/index_wave` 代码；
- 修改 `major_index_mins`、日线、MACD 或其他现有数据合同；
- 新增 asset、check、job、sensor、API、前端页面或配置项；
- 运行 materialize、backfill、bootstrap、runless event；
- 写入正式 Lake 或生产数据库。

### 1.4 G0 冻结时的代码影响面结论

CodeGraph 与当前代码核验得到的边界是：

| 当前区域 | 与未来波浪能力的关系 | G0 是否修改 |
| --- | --- | --- |
| `major_index_mins` run contract / silver writer / checks | 提供未来 120 分钟规范输入 | 否 |
| 指数日线资产 | 提供未来日线规范输入 | 否 |
| backend MACD calculator | 公式参考或未来专项外围能力 | 否 |
| Dagster catalog/schema/paths | G3 才设计正式资产 | 否 |
| Wealth / Index Detail 前端 | 由其他线程在 G4 结果合同稳定后消费 | 否 |
| pivot/wave/scenario engine | G0 冻结时不存在；G1 后已新增纯领域包 | G0 本轮只定义合同 |

因此，本稿不改变 `foundation/ops/biz/app` 依赖矩阵，也不把 Lake Console 代码引入生产主系统。

---

## 2. 不可违反的总约束

当前线程 G1～G4 以及后续其他线程的消费实现都必须满足下表。

| 编号 | 硬约束 | 违反后的处理 |
| --- | --- | --- |
| C01 | 任何判断只能读取 `bar_end_at <= as_of` 的闭合 bar | 整次计算失败，不产出新快照 |
| C02 | 图上极值时间与系统可知时间分离 | 必须同时保存 `extreme_at` 和 `confirmed_at` |
| C03 | confirmed pivot 不得被后续行情静默移动或删除 | 新模型或修复必须使用新版本/快照身份 |
| C04 | forming leg 永远不能冒充 confirmed swing | 输出必须带 `uses_provisional=true`，且不增加 `confirmed_wave_count` |
| C05 | 同一 `ts_code/freq/degree` 的 confirmed pivots 高低交替 | 输入或状态错误，fail closed |
| C06 | 相同输入快照、模型和参数必须得到相同 key、规则结果和排序 | 确定性测试失败即阻断发布 |
| C07 | 硬规则、软特征和当前不可判断必须分离 | 硬规则只返回 `PASS/FAIL/NOT_YET_EVALUABLE`；软特征只返回 `EVALUATED/NOT_YET_EVALUABLE/NOT_APPLICABLE` |
| C08 | 同一时点允许多个场景 | 不以最高分场景覆盖其他有效解释 |
| C09 | `heuristic_score` 只用于排序和解释 | 禁止改名或展示为胜率、置信概率 |
| C10 | outcome label 只能在回测侧使用未来生成 | 在线内核和场景生成器不得读取标签 |
| C11 | 概率必须绑定模块、结果空间、期限、标签和校准版本 | 任一版本缺失时不得返回概率 |
| C12 | 每个 `ts_code/freq` 都是独立运行实例，核心算法不得硬编码某个周期或每天 bar 数 | 跨周期信息只能由显式模块按可见时点消费；新增周期若要求修改 pivot/swing/scenario 核心则验收失败 |
| C13 | 通用内核不识别 `7,52,7`、`P0/P1/P2/P3` 或四浪专项三分类 | 这些语义只能出现在后续专项模块 |
| C14 | 波浪结果是研究假设，不是交易指令 | 不产出买卖、仓位或自动下单字段 |
| C15 | 未支持的复杂形态必须返回 `UNSUPPORTED` | 禁止套入最相近的已支持标签 |
| C16 | 所有历史修正必须可回放 | 保存模型、规则、数据快照、来源与生成版本 |

---

## 3. 时间与可见性合同

### 3.1 四个时间不能混用

| 字段 | 含义 | 可用于什么 |
| --- | --- | --- |
| `bar_end_at` | 这根 K 线结束的市场时间 | 判断 bar 是否已闭合 |
| `extreme_at` | 某个高点或低点实际发生在哪根 bar | 图上标记、结构定位 |
| `confirmed_at` | 后续价格首次达到确认条件的 bar 结束时间 | 回测最早可使用时点 |
| `created_at` | 系统实际生成文件或记录的墙上时间 | 运维审计，不能参与行情逻辑 |

必须满足：

```text
extreme_at <= confirmed_at <= as_of
bar_visible_through <= as_of
```

### 3.2 `as_of` 的精确定义

`as_of` 是本次判断允许使用的最后一根闭合 bar 的 `bar_end_at`，不是任务开始时间，也不是文件写入时间。

- 对 120 分钟序列，正常交易日可分别在 `11:30` 和 `15:00` 形成快照。
- 对日线序列，adapter 把交易日规范成该市场当日收盘 bar 的结束时点。
- 对 60 分钟、30 分钟及后续周期，adapter 必须按各自已经冻结的上游交易时段合同提供 `bar_end_at` 和连续性；核心算法不得猜测每天 bar 数或自行重采样。
- 上游文件即使在更晚时间才到达，也只能影响何时运行，不能把 `as_of` 改成写文件时间。
- 回测前缀必须用 `bars[bar_end_at <= as_of]` 构造，不能先读取全历史再从最终结果中筛选。

### 3.3 单周期运行

通用内核的一次运行身份是：

```text
ts_code + freq + degree_key + as_of
+ detector_profile_version + grammar_profile_version
+ score_profile_version + engine_version
```

一次运行只允许一个 `freq`。任一周期的结果都不能覆盖、复用或默认引用另一个周期的 pivot、scenario、状态或概率校准器。

### 3.4 跨周期可见性

若未来某个分析模块同时消费多个周期，必须逐输入保存：

```json
{
  "120min": "2026-08-08T15:00:00+08:00",
  "1d": "2026-08-08T15:00:00+08:00"
}
```

模块只能读取在其决策时点前已经闭合且通过上游 readiness 的数据。跨周期模块不允许回写或改变任何单周期 pivot 和 scenario 历史。

---

## 4. Canonical Bar 合同

`Canonical Bar` 是 Bar Adapter 交给纯内核的周期无关内存接口，不是新的行情来源。G1 不为它创建数据库表、Parquet 或 Dagster asset；日线、120 分钟、60 分钟和 30 分钟只有通过各自 adapter 的闭合时点、连续性和来源版本检查后，才转换为同一字段合同。新增周期原则上只能新增或调整 adapter/profile，不得修改 pivot、swing、scenario 核心语义。

### 4.1 字段

| 字段 | 类型建议 | 必填 | 说明 |
| --- | --- | --- | --- |
| `ts_code` | VARCHAR | 是 | 规范化大写证券/指数代码 |
| `freq` | VARCHAR | 是 | 例如 `120min`、`1d`；同一序列必须一致 |
| `trade_date` | DATE | 是 | 所属交易日 |
| `bar_end_at` | TIMESTAMPTZ | 是 | `Asia/Shanghai` 的闭合时间 |
| `open` | DOUBLE | 是 | 开盘价 |
| `high` | DOUBLE | 是 | 最高价 |
| `low` | DOUBLE | 是 | 最低价 |
| `close` | DOUBLE | 是 | 收盘价；用于 ZigZag 反转确认 |
| `vol` | DOUBLE | 否 | 可为 0，不进入首版波浪结构 |
| `amount` | DOUBLE | 否 | 可为 0，不进入首版波浪结构 |
| `source_asset_key` | VARCHAR | 是 | 输入资产身份 |
| `source_partition` | VARCHAR | 是 | 来源分区 |
| `source_contract_version` | VARCHAR | 是 | 上游 K 线语义版本 |
| `data_snapshot_id` | VARCHAR | 是 | 本次可复现输入快照 |

`bar_key` 的规范身份为：

```text
sha256("bar/v1" + ts_code + freq + bar_end_at)
```

价格不进入 `bar_key`；若同一 bar 被数据修复，仍是同一市场 bar，但必须产生新的 `data_snapshot_id`。下游结果通过数据快照区分修复前后，不能静默混用。

### 4.2 排序与唯一性

对每个 `ts_code/freq`：

1. `bar_end_at` 必须严格递增。
2. `(ts_code,freq,bar_end_at)` 必须唯一。
3. adapter 不得静默去重、排序后掩盖源端重复；发现乱序或重复时 fail closed，并输出 reason code。
4. 运行时 `bar_index` 只是该次规范序列中的零基索引，不进入任何稳定 key。

### 4.3 价格质量

每根 bar 必须满足：

```text
open, high, low, close 均为有限数且 > 0
high >= max(open, close)
low  <= min(open, close)
high >= low
vol/amount 若存在，则为有限数且 >= 0
```

违反任一项时，不允许跳过坏 bar 后继续数浪。该 `ts_code/freq/as_of` 返回 `INPUT_INVALID`，不生成新 confirmed 事实或场景快照。

### 4.4 连续性

通用内核不自行猜测交易日历和交易时段。Bar Adapter 必须先根据上游合同给出：

- `continuity_status=COMPLETE`：可运行；
- `continuity_status=KNOWN_SESSION_EXCEPTION`：例如有正式交易日历依据的提前收市，可运行并记录原因；
- `continuity_status=GAP/UNKNOWN`：fail closed。

这避免把“文件存在”误当成完整输入，也避免内核把合法提前收市误判成缺 bar。

### 4.5 主要指数 30/60 分钟竞价行过滤合同

本节只约束“直接使用主要指数 30 分钟或 60 分钟 Silver 数据进行波浪分析”的 Bar Adapter，不修改 Lake 行情事实。

现有 Silver 正常交易日中，30 分钟有 9 行、60 分钟有 5 行，二者都包含 `09:30` 集合竞价行。上游仍必须先按自己的完整性合同验证这些源行；验证通过后，波浪 Bar Adapter 固定执行以下规则：

1. 精确过滤 `Asia/Shanghai` 当日 `09:30:00` 行。
2. 该行不得生成独立 Canonical Bar。
3. 该行不得并入第一根常规 K 线，其 `open/high/low/close/vol/amount` 均不进入任何 30/60 分钟 Canonical Bar。
4. 其余常规 K 线逐行透传，不重采样、不重新聚合，也不改写 OHLC、`vol` 或 `amount`。
5. 30 分钟正常日输出 8 根 Canonical Bars，闭合时间固定为 `10:00/10:30/11:00/11:30/13:30/14:00/14:30/15:00`。
6. 60 分钟正常日输出 4 根 Canonical Bars，闭合时间固定为 `10:30/11:30/14:00/15:00`。
7. 当日第一根可见 bar 分别在 `10:00` 和 `10:30` 闭合；`as_of` 早于闭合时间时不得提前暴露。
8. adapter 的连续性以过滤后的 8/4 根分析序列判定，但不能用过滤动作掩盖上游缺行、重复、乱序或未通过 readiness；上游不完整时仍须 fail closed。
9. 实现时必须使用独立、版本化的 `source_contract_version` 记录本过滤语义，禁止与“保留 `09:30`”或“并入第一根 K 线”的输入快照混用。

边界保持不变：Silver 文件继续保留 `09:30` 源行；90/120 分钟继续按各自已冻结的派生合同使用竞价锚点。本节只冻结 30/60 分钟波浪分析输入语义，不代表 adapter 已实现或已经通过真实数据验收。

---

## 5. Detector Profile 与 ATR 基线

### 5.1 detector 是参数化观察器，不是波浪真理

同一行情用不同摆动阈值会得到不同尺度的 pivots。因此每个结果必须携带完整 detector profile，不能只写“用了 ZigZag”。

| 字段 | 说明 |
| --- | --- |
| `detector_key` | 算法族，例如 `CAUSAL_ATR_ZIGZAG` |
| `detector_version` | 状态机语义版本 |
| `detector_profile_key` | 一组完整参数的稳定名称 |
| `atr_period` | ATR 周期 |
| `atr_seed_method` | ATR 初值算法 |
| `atr_smoothing` | 后续平滑算法 |
| `atr_multiplier` | 反转阈值倍数 |
| `extreme_source` | 固定为 `HIGH_LOW` |
| `confirmation_source` | 固定为 `CLOSE` |
| `threshold_anchor` | 固定为 `EXTREME_BAR` |
| `equal_extreme_policy` | 相等高低点保留哪一个 |
| `dual_confirmation_policy` | 同 bar 双向可确认时怎样处理 |
| `post_confirmation_reset_policy` | 确认 bar 后怎样开始反向候选 |
| `warmup_policy` | ATR 未成熟时怎样处理 |

### 5.2 已确认的第一版 ATR 公式

第一版固定使用经典 Wilder ATR，并把它写成独立金标，不直接继承某个库的初始化差异。

```text
TR(0) = high(0) - low(0)
TR(t) = max(
  high(t) - low(t),
  abs(high(t) - close(t-1)),
  abs(low(t) - close(t-1))
)

ATR(n-1) = mean(TR(0) ... TR(n-1))
ATR(t)   = (ATR(t-1) * (n-1) + TR(t)) / n,  t >= n
```

基线参数固定为：

```text
atr_period = 14
atr_multiplier = 1.5
smoothing = WILDER_RMA
min/max clamp = NONE
threshold_at_extreme = ATR(extreme_bar) * 1.5
```

前 `n-1` 根没有成熟 ATR，不允许确认 pivot。任何无效 TR/ATR 都使当前序列 fail closed，不做“遇到 NaN 后重新开始”的隐式恢复。

### 5.3 反转阈值

高点候选的向下确认：

```text
candidate_high - current_close >= threshold_at_candidate_high
```

低点候选的向上确认：

```text
current_close - candidate_low >= threshold_at_candidate_low
```

阈值必须锚定候选极值 bar。候选极值一旦被更高高点或更低低点替换，阈值随新极值重新锚定；它不能每天跟着当前 ATR 漂移。

### 5.4 状态机

状态只有四种：

```text
WARMUP -> UNDEFINED -> UP <-> DOWN
```

#### WARMUP

- ATR 尚未成熟；只计算公式，不产出候选或 pivot。

#### UNDEFINED

- 从第一根 ATR 成熟 bar 开始，同时维护区间最高点和最低点。
- 高点只在 `high > candidate_high` 时更新；相等时保留更早的 bar。
- 低点只在 `low < candidate_low` 时更新；相等时保留更早的 bar。
- 若收盘只满足“从区间低点向上反转”，确认 LOW，并进入 `UP`。
- 若收盘只满足“从区间高点向下反转”，确认 HIGH，并进入 `DOWN`。
- 若同一根 bar 同时满足两个方向，OHLC 无法提供日内先后顺序；本 bar 不确认任何 pivot，继续等待无歧义 bar。

#### UP

- 只维护新的候选高点。
- 收盘从候选高点回撤达到锚定阈值时，确认 HIGH，并进入 `DOWN`。

#### DOWN

- 只维护新的候选低点。
- 收盘从候选低点反弹达到锚定阈值时，确认 LOW，并进入 `UP`。

### 5.5 确认 bar 后的反向候选

第一版固定使用 `NEXT_BAR_RESET`：确认 bar 只负责确认上一极值，反向候选从下一根 bar 才开始。

理由是单根 OHLC 无法证明确认 bar 内的 high 和 low 谁先发生。若确认 HIGH 后立刻把同一 bar 的 low 当成新低点候选，未来可能产生同一时间的 HIGH/LOW 两个 pivot，形成无法证明的日内顺序。

该选择比直接复用确认 bar 更保守，可能少捕捉一部分急速 V 形反转，因此 G2 仍必须用 same-bar reset 做敏感性对照；对照只评估影响，不反向改写已经冻结的 V1 历史。

### 5.6 test-only detector

G1 的状态机夹具应额外支持 `ABSOLUTE_REVERSAL_TEST`，例如固定 5 点阈值。它只用于把 pivot 逻辑与 ATR 公式分开测试，不得用于正式研究结果或用户展示。

---

## 6. Pivot Candidate 与 Pivot Confirmation

### 6.1 Candidate

Candidate 是内存中的形成中状态，不是历史事实。它至少包含：

```text
pivot_type
extreme_at
extreme_price
threshold_at_extreme
candidate_updated_at
```

它可以被更高高点或更低低点替换，不获得 `pivot_key`，也不写入 confirmed pivot 资产。

### 6.2 Confirmation

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| `model_version` | VARCHAR | 波浪内核版本 |
| `data_snapshot_id` | VARCHAR | 输入数据快照 |
| `ts_code` | VARCHAR | 标的代码 |
| `freq` | VARCHAR | 单一输入周期 |
| `degree_key` | VARCHAR | 尺度合同 |
| `pivot_key` | VARCHAR | confirmed 事件稳定身份 |
| `pivot_type` | VARCHAR | `HIGH/LOW` |
| `extreme_at` | TIMESTAMPTZ | 极值位置 |
| `extreme_trade_date` | DATE | 极值所在交易日 |
| `extreme_price` | DOUBLE | HIGH 取 high，LOW 取 low |
| `confirmed_at` | TIMESTAMPTZ | 最早可用时点 |
| `confirmation_trade_date` | DATE | 确认所在交易日；未来资产按此日期分区 |
| `confirmation_close` | DOUBLE | 触发确认的收盘价 |
| `threshold_at_extreme` | DOUBLE | 极值 bar 锚定阈值 |
| `detector_profile_key` | VARCHAR | 完整 detector 参数身份 |
| `extreme_bar_key` | VARCHAR | 极值所在 bar |
| `confirmation_bar_key` | VARCHAR | 确认所在 bar |
| `source_asset_key` | VARCHAR | 上游资产 |
| `extreme_source_partition` | VARCHAR | 极值所在来源分区 |
| `confirmation_source_partition` | VARCHAR | 确认所在来源分区；可与极值分区不同 |
| `created_at` | TIMESTAMPTZ | 运维生成时间 |

`pivot_key` 推荐使用规范化内容哈希：

```text
sha256(
  "pivot/v1"
  + ts_code + freq + degree_key + detector_profile_key
  + pivot_type + extreme_at + canonical_decimal(extreme_price)
  + confirmed_at + canonical_decimal(threshold_at_extreme)
)
```

`canonical_decimal` 必须规定固定、跨平台一致的十进制序列化；不得直接对二进制 float 或 Python 对象表示做哈希。

### 6.3 不变量

```text
confirmed_at >= extreme_at
HIGH.extreme_price = source_bar.high
LOW.extreme_price  = source_bar.low
confirmation_bar.close 满足对应反转不等式
同一序列 confirmed pivots 的类型严格交替
相邻 confirmed pivots 的 extreme_at 严格递增
相邻 confirmed pivots 的 confirmed_at 严格递增
pivot_key 不依赖 rank、run_id、created_at 或文件路径
```

若上游数据修复导致某个历史 pivot 内容变化，必须以新 `data_snapshot_id/model_version` 重放。旧结果可以归档或标记 superseded，但不能在同一版本下原地伪装成从未发生过。

---

## 7. Confirmed Swing 与 Forming Leg

### 7.1 Confirmed Swing

Swing 只连接两个相邻 confirmed pivots。

| 字段 | 说明 |
| --- | --- |
| `swing_key` | 由两个 pivot key 和 swing contract version 计算 |
| `from_pivot_key/to_pivot_key` | 不复制出一套无法追溯的拐点身份 |
| `direction` | `UP` 或 `DOWN` |
| `start_at/end_at` | 两个极值的 `extreme_at` |
| `available_at` | `to_pivot.confirmed_at` |
| `start_price/end_price` | 两端极值价格 |
| `absolute_change` | `end_price-start_price` |
| `return_ratio` | `end_price/start_price-1` |
| `duration_bars` | 两个 extreme bar 之间的 bar 数 |
| `confirmation_delay_bars` | 终点 extreme 到 confirmed 的 bar 数 |

必须满足：

```text
UP   -> from=LOW,  to=HIGH, end_price > start_price
DOWN -> from=HIGH, to=LOW,  end_price < start_price
available_at = to_pivot.confirmed_at
```

### 7.2 Forming Leg

Forming leg 是最后一个 confirmed pivot 到当前候选极值的临时连线。它至少包含：

```text
from_pivot_key
direction
forming_extreme_at
forming_extreme_price
visible_at
threshold_remaining
uses_provisional=true
```

它的端点可以随新 bar 移动。它没有 `to_pivot_key`，不能进入 confirmed `pivot_keys`，不能增加 `confirmed_wave_count`，也不能作为回测事件的已确认结构证据。

前端未来可以把它画成虚线；默认回测必须使用 `uses_provisional=false` 的场景快照。

---

## 8. Degree 合同

`degree_key` 表示“同一周期内由哪套尺度 profile 生成的结构”，不是文学名称，也不是自动等同于分钟、小时或日线。

每个 degree profile 至少绑定：

```text
degree_key
degree_version
detector_profile_key
grammar_profile_key
max_history_pivots
max_start_candidates
max_scenarios
progression_horizon_bars
```

G1 每个 `freq` 只启用一个基线 degree：

```text
degree_key = BASE_ATR14_1P5_V1
```

该基线可由日线、120 分钟、60 分钟和 30 分钟分别运行，但“使用同一首轮基线”不代表参数或概率可以跨周期共享。G2 及后续周期扩展必须分别报告 pivot 密度、确认延迟、场景稳定性和校准质量；需要不同参数时新增版本化 profile，不在核心代码中按 `freq` 分支。

合同保留多 degree 扩展能力，但第一版不同时搜索多个 ATR 倍数，避免把参数搜索误写成“天然浪级”。多 degree 要在 G2 单独做稳定性和计算量评审后再启用。

---

## 9. 第一版浪型语法

### 9.1 支持边界

第一版只定义两个 grammar profile：

1. `IMPULSE_STANDARD_V1`：标准、非斜向、非截短的五浪推动结构。
2. `CORRECTIVE_ZIGZAG_V1`：基础 A-B-C 锯齿修正结构。

平台、扩散/收敛三角形、联合调整、斜向三角形、截短五浪等全部返回 `UNSUPPORTED`，不得硬塞进上述两类。

### 9.2 规则求值三态

每条规则只能返回：

| 状态 | 含义 | 对场景的影响 |
| --- | --- | --- |
| `PASS` | 当前已具备足够证据且满足 | 保留 |
| `FAIL` | 当前已具备足够证据且违反硬规则 | 立即 `INVALIDATED` |
| `NOT_YET_EVALUABLE` | 还缺后续 confirmed pivot | 保留，但不能当作通过 |

### 9.3 标准推动浪硬规则

以上涨推动为例，六个 confirmed pivots 为 `W0...W5`：

```text
W0 LOW -> W1 HIGH -> W2 LOW -> W3 HIGH -> W4 LOW -> W5 HIGH
```

下跌推动完全镜像。

| 规则 key | 最早可判断 | 上涨推动定义 | 未满足处理 |
| --- | --- | --- | --- |
| `IMPULSE_ALTERNATING_DIRECTION` | 每新增一个 pivot | 高低严格交替 | `FAIL` |
| `WAVE2_NOT_BEYOND_ORIGIN` | W2 | `W2.price > W0.price` | `FAIL` |
| `WAVE3_EXCEEDS_WAVE1` | W3 | `W3.price > W1.price` | `FAIL` |
| `WAVE4_NO_WAVE1_OVERLAP` | W4 | `W4.price > W1.price` | `FAIL`；斜向形态不在 V1 |
| `WAVE5_EXCEEDS_WAVE3` | W5 | `W5.price > W3.price` | `FAIL`；截短五浪不在 V1 |
| `WAVE3_NOT_SHORTEST` | W5 | `len(W3) >= min(len(W1),len(W5))` | W5 前为 `NOT_YET_EVALUABLE`；之后违反为 `FAIL` |

这里的 `len(Wk)` 是该价格腿的绝对点数，不是时间长度。

### 9.4 锯齿修正浪硬规则

以下跌修正为例：

```text
C0 HIGH -> A LOW -> B HIGH -> C LOW
```

上涨修正完全镜像。

| 规则 key | 最早可判断 | 下跌修正定义 | 未满足处理 |
| --- | --- | --- | --- |
| `ZIGZAG_ALTERNATING_DIRECTION` | 每新增一个 pivot | `DOWN/UP/DOWN` | `FAIL` |
| `B_NOT_BEYOND_ORIGIN` | B | `B.price < C0.price` | `FAIL` |
| `C_EXCEEDS_A` | C | `C.price < A.price` | `FAIL`；截短 C 不在 V1 |

第一版不因三段结构存在就断言它一定是更大级别修正浪。若缺少上一级上下文，场景保留 `context_status=LOCAL_STRUCTURE_ONLY`。

### 9.5 软特征

软特征不决定合法性，只用于排序和解释：

| feature key | 说明 | 不足证据时 |
| --- | --- | --- |
| `FIBONACCI_RATIO_FIT` | 回撤/延伸比例与 profile 中参考区间的接近度 | `NOT_YET_EVALUABLE` |
| `TIME_RATIO_FIT` | 各腿持续 bar 数的相对关系 | 推动 W3 前为 `NOT_YET_EVALUABLE`；锯齿 V1 为 `NOT_APPLICABLE` |
| `WAVE2_WAVE4_ALTERNATION` | Wave 2 与 Wave 4 在深度/时长上的差异 | 推动 W4 前为 `NOT_YET_EVALUABLE`；锯齿为 `NOT_APPLICABLE` |
| `CHANNEL_FIT` | 极值与版本化通道的贴合度 | V1 不进入总分，返回 `NOT_APPLICABLE` 和固定 reason code |
| `STRUCTURE_COMPLETENESS` | 已确认阶段占完整 grammar 的比例 | 始终可算 |

所有特征输出：

```text
feature_status
feature_value
feature_score in [0,1]
feature_coverage in [0,1]
feature_reason
feature_profile_version
```

第 11 节冻结 `score_profile_v1`。它是可解释、可回放的工程基线，不是由当前本地数据拟合出的最优参数；G2 必须把“合同已冻结”和“样本外有效”作为两件不同的事验证。

---

## 10. Scenario Snapshot、身份与演化

### 10.1 为什么需要两个身份

如果 `scenario_key` 包含全部有序 pivot，那么新确认一浪后结构内容变化，key 必然变化；如果 key 不包含 pivots，又无法精确复现当时结构。

因此拆成：

1. `scenario_key`：精确结构身份。相同结构跨快照稳定；结构延长后产生新 key。
2. `scenario_lineage_key`：演化链身份。来自同一起点、同一方向、同一 grammar/profile 的延长结构共享 lineage。
3. `parent_scenario_key`：直接指向延长前的结构，形成可审计链。

### 10.2 key 计算

```text
scenario_key = sha256(
  "scenario/v1"
  + ts_code + freq + degree_key
  + grammar_profile_key + scenario_type + direction
  + ordered_pivot_keys
)

scenario_lineage_key = sha256(
  "scenario-lineage/v1"
  + ts_code + freq + degree_key
  + grammar_profile_key + scenario_type + direction
  + start_pivot_key
)
```

rank、分数、forming extreme、as_of、run_id 和 created_at 不进入这两个 key。

### 10.3 生命周期

| 状态 | 严格含义 |
| --- | --- |
| `CANDIDATE` | 已匹配部分 grammar，尚未达到该 profile 的 active 最小阶段 |
| `ACTIVE` | 当前 confirmed pivots 通过全部已可判断硬规则，结构仍可延长 |
| `COMPLETED` | 已达到 grammar 完整阶段且硬规则通过 |
| `INVALIDATED` | 某条已可判断硬规则失败 |
| `SUPERSEDED` | 仍未硬失效，但因新结构证据被同 lineage 或替代解释降级 |

`COMPLETED` 只表示“按该 grammar 结构完整”，不表示市场预测成功，也不表示趋势必然继续。

### 10.4 字段合同

| 字段组 | 关键字段 |
| --- | --- |
| 身份 | `model_version,score_profile_version,data_snapshot_id,ts_code,freq,as_of,degree_key` |
| 结构 | `scenario_key,scenario_lineage_key,parent_scenario_key,scenario_type,direction,ordered_pivot_keys` |
| 阶段 | `current_phase,confirmed_wave_count,scenario_status,status_changed_at,valid_from_as_of` |
| 排名 | `rank,ranking_score,heuristic_score,score_coverage,score_spread` |
| 规则 | `hard_evaluations_json,soft_evaluations_json` |
| forming | `uses_provisional,forming_leg_json` |
| 失效 | `invalidation_price,invalidation_rule_key` |
| 来源 | `detector_profile_key,grammar_profile_key,engine_key,engine_version,bar_visible_through` |

### 10.5 排名

- 每个 `ts_code/freq/degree/as_of` 最多保留 5 个可展示场景。
- 先按硬规则过滤，再按 `ranking_score` 降序。
- `ranking_score` 相同时，依次按 `heuristic_score`、`score_coverage`、`confirmed_wave_count`、`scenario_key` 排序，保证确定性。
- 被剪枝数量和原因必须作为 diagnostics 保存；不能让“只剩一个”看起来像“只有一种解释”。
- `INVALIDATED` 场景至少保存一次终止快照，以解释何时、因何失效。

### 10.6 快照不可覆盖

`ScenarioSnapshot(as_of=t)` 是“当时系统知道什么”的事实。`t+n` 只能：

- 延长为子 scenario；
- 更新 rank/score/forming；
- 产生 invalidated/superseded 终止快照；
- 在新模型或新数据快照下产生另一套显式版本。

不得用今天的最佳解释覆盖昨天的历史快照。

---

## 11. 启发式分数合同

### 11.1 分数不是概率

`heuristic_score` 只回答：在同一个 `as_of` 的有效场景中，哪个更符合当前版本的软特征偏好。

它不回答：

- 后续上涨概率；
- 当前浪型最终成立概率；
- 买入后盈利概率；
- 某个场景相对于全部现实可能性的贝叶斯概率。

### 11.2 `score_profile_v1` 的来源和边界

已确认的 profile key：

```text
score_profile_version = SCORE_PROFILE_V1
source_baseline = TA4J_0_23_0
empirical_status = NOT_FITTED
```

ta4j 0.23.0 提供了 Fibonacci、时长、二四浪交替、通道和结构完整度五类因素及默认权重，适合作为可追溯起点；它不构成中国指数上的统计证据。Goldenshare V1 有两处有意不照搬：

1. ta4j 在部分证据不足、非推动结构或无有效通道时返回中性 `0.5`；本合同返回 `NOT_YET_EVALUABLE/NOT_APPLICABLE`，不得伪造证据。
2. ta4j 的当前通道分数把某个时点的静态上下界用于全部 swing 端点。V1 尚未冻结逐端点、逐时点的因果通道，因此 `CHANNEL_FIT` 先排除出总分。

本节中的区间和权重只是首个透明基线。G2 可以验证它、否定它或提出新 profile，但不得在同一版本下调参。

### 11.3 通用比例接近度函数

所有价格比例都使用 swing 绝对振幅，所有时间比例都使用正整数 `duration_bars`。对目标带 `L <= I <= U` 和绝对比例容差 `T`，定义：

```text
left_edge_score  = 1.0 if I == L else 0.5
right_edge_score = 1.0 if I == U else 0.5

proximity(r; L,I,U,T) =
  0                                                    , r < L-T or r > U+T
  left_edge_score * (r-(L-T)) / T                     , L-T <= r < L
  left_edge_score + (1-left_edge_score)*(r-L)/(I-L)   , L <= r < I
  1                                                    , r == I
  1 - (1-right_edge_score)*(r-I)/(U-I)                , I < r <= U
  right_edge_score * ((U+T)-r) / T                    , U < r <= U+T
```

退化边界处理：当 `I=L` 时不存在 `L <= r < I` 分支；当 `I=U` 时不存在 `I < r <= U` 分支；当 `T=0` 时不存在两个容差分支。最终结果钳制到 `[0,1]`。无效数、负比例、分母 `<=0` 均不返回 0 分，而是该 component `NOT_YET_EVALUABLE` 并记录 reason code。

这个函数保证：理想值为 1，普通有效带边界通常为 0.5，容差外边界为 0，且没有边界跳变。

### 11.4 `FIBONACCI_RATIO_FIT`

| grammar | component | 比例 `r` | `L` | `I` | `U` | `T` | 最早可算 |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| 推动 | `W2_W1` | `amp(W2)/amp(W1)` | 0.382 | 0.618 | 0.786 | 0.05 | W2 |
| 推动 | `W3_W1` | `amp(W3)/amp(W1)` | 1.000 | 1.618 | 2.618 | 0.05 | W3 |
| 推动 | `W4_W3` | `amp(W4)/amp(W3)` | 0.236 | 0.382 | 0.786 | 0.05 | W4 |
| 推动 | `W5_W1` | `amp(W5)/amp(W1)` | 0.618 | 1.000 | 1.618 | 0.05 | W5 |
| 锯齿 | `B_A` | `amp(B)/amp(A)` | 0.382 | 0.618 | 0.886 | 0.05 | B |
| 锯齿 | `C_A` | `amp(C)/amp(A)` | 1.000 | 1.000 | 1.618 | 0.05 | C |

```text
component_score  = proximity(r; L,I,U,T)
feature_score    = mean(当前可计算的 component_score)
feature_coverage = 可计算 component 数 / 该 grammar 的总 component 数
```

推动总 component 数为 4，锯齿总 component 数为 2。尚未形成的未来浪不记 0 分；它只降低 `feature_coverage`。硬规则已经失败的场景先失效，不再靠 Fibonacci 高分“救回”。

### 11.5 `TIME_RATIO_FIT`

V1 只对推动浪定义两个可解释 component；锯齿时长关系没有冻结，返回 `NOT_APPLICABLE`，对应权重为 0。

```text
T3 = min(1, duration(W3) / duration(W1))
T5 = proximity(duration(W5)/duration(W1); 0.5,1.0,1.5,0.5)

feature_score    = mean(当前可计算的 T3/T5)
feature_coverage = 当前可计算 component 数 / 2
```

`T3` 表达“Wave 3 在时间上至少不短于 Wave 1”，`T5` 表达 Wave 1 与 Wave 5 时长相近。W3 前整个特征为 `NOT_YET_EVALUABLE`；W3 后只计算 T3，W5 后才加入 T5。

### 11.6 `WAVE2_WAVE4_ALTERNATION`

V1 只对推动浪、且 W4 已确认时计算一个“深度 + 时长差异代理”，不声称已经识别 sharp/sideways 的完整形态类别：

```text
depth2 = amp(W2) / amp(W1)
depth4 = amp(W4) / amp(W3)

depth_difference = abs(depth2 - depth4)
time_difference  = abs(duration(W2)-duration(W4))
                   / max(duration(W2),duration(W4))

depth_score = min(1, 2 * depth_difference)
time_score  = min(1, time_difference)

feature_score    = (depth_score + time_score) / 2
feature_coverage = 1
```

W4 前为 `NOT_YET_EVALUABLE`；锯齿为 `NOT_APPLICABLE`。任何分母 `<=0` 都不得回填中性分。

### 11.7 `STRUCTURE_COMPLETENESS`

```text
expected_wave_count = 5 for IMPULSE_STANDARD_V1
expected_wave_count = 3 for CORRECTIVE_ZIGZAG_V1

feature_score    = min(1, confirmed_wave_count / expected_wave_count)
feature_coverage = 1
```

完整结构不再额外奖励 `+0.1`，因为 `confirmed_wave_count/expected_wave_count` 已经在完成时等于 1。forming leg 不进入分子。

### 11.8 `CHANNEL_FIT`

V1 固定：

```text
feature_status   = NOT_APPLICABLE
feature_score    = NULL
feature_coverage = 0
feature_reason   = CHANNEL_ALGORITHM_NOT_FROZEN_IN_SCORE_V1
configured_weight = 0
```

这不是判断“通道没有价值”，而是拒绝在没有逐时点边界、阶段化锚点、容差单位和前缀不变性合同前塞入一个看似精确的分数。以后启用通道必须升级 `score_profile_version`，补充独立公式和金标，再全历史重放。

### 11.9 grammar 专属权重

所有正权重在各自 grammar 内合计为 1。

| feature | `IMPULSE_STANDARD_V1` | `CORRECTIVE_ZIGZAG_V1` | 来源说明 |
| --- | ---: | ---: | --- |
| `FIBONACCI_RATIO_FIT` | `7/17`（0.41176471） | `2/3`（0.66666667） | ta4j 0.23.0 原权重去掉 V1 不采用的因素后归一化 |
| `TIME_RATIO_FIT` | `4/17`（0.23529412） | 0 | 锯齿时长合同未冻结 |
| `WAVE2_WAVE4_ALTERNATION` | `3/17`（0.17647059） | 0 | 只适用于推动浪 |
| `CHANNEL_FIT` | 0 | 0 | V1 排除 |
| `STRUCTURE_COMPLETENESS` | `3/17`（0.17647059） | `1/3`（0.33333333） | 保留结构成熟度但不额外奖励完成态 |

推动权重来自 ta4j 默认 `0.35/0.20/0.15/0.15/0.15` 去除 channel 后按 `0.85` 归一化；锯齿权重来自其 pattern-aware profile，去除未真正定义的 time、alternation 和本合同不采用的 channel 后，将 Fibonacci `0.30` 与 completeness `0.15` 归一化。权重来源可追溯，不代表已被 A 股样本验证。

### 11.10 聚合、覆盖率与排名分

component 不足不能填 0 或 0.5。每个 feature 的有效证据权重为：

```text
effective_weight_i = configured_weight_i * feature_coverage_i
evaluated_weight   = sum(effective_weight_i)
weighted_sum       = sum(effective_weight_i * feature_score_i)

heuristic_score = weighted_sum / evaluated_weight
score_coverage  = evaluated_weight / sum(configured_weight_i)
ranking_score   = weighted_sum
```

各 grammar 的配置权重和为 1，因此 `score_coverage=evaluated_weight`。三个字段回答不同问题：

- `heuristic_score`：已获得证据的平均贴合度；
- `score_coverage`：完整 profile 中已有多少证据；
- `ranking_score`：把贴合度和证据覆盖一起考虑后的保守排序值。

缺失项并没有被记录成 0 分；它只不贡献 evidence mass。若 `evaluated_weight=0`，`heuristic_score` 和 `ranking_score` 均为 `NULL`，`score_coverage=0`，排序退回 `confirmed_wave_count` 与稳定 key。

同一个 `ts_code/freq/degree/as_of` 的候选先按第 10.5 节排序。`score_spread` 固定为第一名与第二名的 `ranking_score` 之差；若不足两个可排名场景则为 `NULL`。前端不得只展示总分而隐藏 coverage、分项和 profile version。

权重、目标区间、容差、component 数、缺失策略或聚合公式任一变化，都必须升级 `score_profile_version` 并重新回放；前端不得自行计算。

---

## 12. 分析模块、Outcome 与 Probability

### 12.1 模块只读边界

分析模块可以消费通用 scenario、指标、市场宽度或其他周期上下文，但不得修改通用 pivot、swing、scenario、rank 和 heuristic score。

每个模块必须声明：

```text
analysis_module_key
module_version
eligibility_contract_version
outcome_space_version
horizon_value + horizon_unit
label_version
feature_contract_version
calibration_contract_version
```

在线 module snapshot 不能携带未来 outcome；历史 label 通过 `module_snapshot_id/event_key` 关联。

### 12.2 首个通用模块：`wave_scenario_progression`

该模块不认识四浪，也不读取特殊 MACD。它只研究一个通用问题：当前场景在固定 bar 期限内，是先延长到 grammar 的下一 confirmed 阶段，还是先被硬规则否定。

三类互斥结果：

| outcome key | 定义 |
| --- | --- |
| `next_phase_confirmed` | 决策 bar 之后、期限内，先出现一个使该 scenario lineage 合法延长到下一阶段的 confirmed pivot |
| `scenario_invalidated` | 决策 bar 之后、期限内，先触发当前场景的硬失效条件 |
| `unresolved` | 到期限结束，两者都未发生 |

标签观察从 `as_of` 的下一根 bar 开始，不能把决策 bar 上已经发生的事实当未来结果。

若同一根 OHLC bar 同时可能满足“下一阶段”和“硬失效”且无法知道日内先后，第一版固定保守记为 `scenario_invalidated`，并保存 `tie_policy=INVALIDATION_FIRST`。该选择必须做敏感性报告，不得隐藏。

### 12.3 观察期

观察期只使用 `BAR`，不使用自然日或四浪专项的 60 个交易日。

第一版固定为：

```text
primary_horizon = 20 bars
sensitivity_horizons = 10 / 40 bars
```

不同 `freq` 的 20 bars 是不同时间尺度的模块样本，日线、120 分钟、60 分钟和 30 分钟不得直接混成同一校准器。10/40 bars 只用于各周期自己的敏感性报告，不替代 20 bars 主标签。

### 12.4 Label 合同

| 字段组 | 关键字段 |
| --- | --- |
| 身份 | `event_key,module_snapshot_id,scenario_key,scenario_lineage_key` |
| 决策 | `ts_code,freq,decision_as_of,decision_phase` |
| 结果 | `outcome_key,outcome_at,label_matured_at` |
| 期限 | `horizon_value,horizon_unit,horizon_end_at` |
| 版本 | `outcome_space_version,label_version,scenario_model_version,data_snapshot_id` |
| 审计 | `trigger_rule_key,tie_policy,label_diagnostics_json` |

所有达到期限但没有事件的样本必须保留为 `unresolved`。不得删除未决样本后重新计算“成功率”。

### 12.5 Probability Snapshot

| 字段组 | 关键字段 |
| --- | --- |
| 身份 | `analysis_module_key,module_snapshot_id,scenario_key,scenario_lineage_key,ts_code,freq,as_of` |
| 结果合同 | `outcome_space_version,horizon_value,horizon_unit,label_version` |
| 上游 | `scenario_model_version,scenario_score_profile_version,scenario_data_snapshot_id,feature_contract_version` |
| 校准 | `calibration_model_version,calibration_method,calibration_data_snapshot_id` |
| 输出 | `outcome_probabilities_json,primary_outcome_key` |
| 不确定性 | `outcome_intervals_json,calibration_sample_count` |
| 状态 | `calibration_status,calibration_visible_through`；状态枚举为 `CALIBRATED/NOT_FITTED/INSUFFICIENT_SAMPLE/STALE/VERSION_MISMATCH` |

概率 JSON 必须：

1. 只包含当前 outcome space 的 keys；
2. 每项位于 `[0,1]`；
3. 总和在容差内等于 1；
4. 不因主 outcome 变化而丢掉其他类别；
5. 不允许用 `heuristic_score * 100%` 兜底。

### 12.6 数据切分与泄漏门禁

1. 训练、校准、测试按时间前后切分。
2. 同一 `event_key/scenario_lineage_key` 派生的连续快照必须整体进入同一集合。
3. 校准数据的所有 label 必须在 `calibration_visible_through` 前成熟。
4. 测试集只能在参数、标签和门禁冻结后打开一次。
5. 每个 `freq` 和不同 outcome space 默认使用不同校准器；任何一个周期的概率结果都不得直接复用于另一个周期。

### 12.7 已确认的第一版展示门禁

概率只有同时满足以下条件才标记 `CALIBRATED`：

- 校准集成熟事件数不少于 200；
- 独立样本外事件数不少于 100；
- 每个非 `unresolved` 类在样本外至少 20 个事件；
- 样本外 multiclass Brier score 与 log loss 均不差于训练期基准发生率模型；
- ECE 不高于 0.10；
- 概率区间、样本数、期限和版本可一并展示。

这是保守的首轮工程门禁，不是统计学永恒真值。阈值需要在 G2 根据真实事件密度评审；未通过时保留 heuristic score 和研究报告，但用户界面不显示概率。

---

## 13. Schema 草案

G0 只冻结领域字段，不提前决定 G3 的 asset key、Parquet 分区和 Dagster event 策略。

### 13.1 `pivot_confirmation_v1`

主键候选：

```text
model_version + data_snapshot_id + pivot_key
```

必要字段沿用第 6.2 节；正式 schema 必须保留 `extreme_at/confirmed_at/extreme_bar_key/confirmation_bar_key`。

### 13.2 `wave_scenario_snapshot_v1`

主键候选：

```text
model_version + score_profile_version + data_snapshot_id
+ ts_code + freq + as_of + degree_key + scenario_key
```

必要字段沿用第 10.4 节；`scenario_key/scenario_lineage_key/parent_scenario_key` 不得合并成一个字段。

### 13.3 `analysis_module_snapshot_v1`

主键候选：

```text
analysis_module_key + module_version + module_snapshot_id
```

在线字段不允许出现 `outcome_key/outcome_at`。

### 13.4 `outcome_label_v1`

主键候选：

```text
analysis_module_key + outcome_space_version + label_version + event_key
```

该表属于回测侧，不能成为通用场景生成器的输入。

### 13.5 `probability_snapshot_v1`

主键候选：

```text
module_snapshot_id + calibration_model_version
```

只有 `calibration_status=CALIBRATED` 时 `outcome_probabilities_json` 才允许非空；`NOT_FITTED/INSUFFICIENT_SAMPLE/STALE/VERSION_MISMATCH` 必须返回空概率和明确原因。

---

## 14. G1 人工金标夹具清单

G1 必须把下列条目写成独立、字面 expected 的 fixture。不能调用被测实现生成 expected。

### 14.1 ATR 与 pivot 夹具

| ID | 输入重点 | 预期 |
| --- | --- | --- |
| F01 | 14 根已知 TR + 后续 2 根 | 第 14 根按算术均值产生首个 ATR；后续按 Wilder 递推 |
| F02 | 固定阈值 5；高点 108 后 close 104 | 回撤 4，不确认 HIGH |
| F03 | 固定阈值 5；同一高点后 close 103 | 在当前 bar 确认 HIGH，`extreme_at` 仍指向 108 所在 bar |
| F04 | UNDEFINED 阶段一根大振幅 bar 同时满足上下确认 | 不确认，保持 UNDEFINED |
| F05 | 连续两根相同最高价 | 保留更早 extreme；key 不随相等 bar 移动 |
| F06 | HIGH 在 bar t 确认；t bar 同时有很低的 low | `NEXT_BAR_RESET` 下该 low 不成为反向候选 |
| F07 | 阈值恰好等于 5 | 使用 `>=`，必须确认 |
| F08 | duplicate/乱序/非正 OHLC/包络错误 | 每种输入分别 fail closed，不跳行 |

### 14.2 scenario grammar 夹具

scenario 测试直接输入已确认 pivots，以便把 grammar 与 detector 解耦。

| ID | Pivot 价格序列 | 预期 |
| --- | --- | --- |
| F09 | 上涨推动 `100L,120H,110L,150H,130L,160H` | `IMPULSE_STANDARD_V1 COMPLETED`，全部硬规则 PASS |
| F10 | 下跌推动 `200H,180L,190H,150L,175H,140L` | 镜像推动完成 |
| F11 | `100L,120H,99L` | Wave 2 越过起点，立即 INVALIDATED |
| F12 | `100L,120H,110L,128H,123L,150H` | Wave 3 最短；W5 前 NOT_YET，W5 后 FAIL |
| F13 | `100L,120H,110L,150H,115L` | Wave 4 与 Wave 1 重叠，INVALIDATED |
| F14 | 下跌锯齿 `160H,135L,150H,120L` | `CORRECTIVE_ZIGZAG_V1 COMPLETED` |
| F15 | `160H,135L,165H` | B 越过起点，锯齿 INVALIDATED |
| F16 | `100L,120H,110L,130H` | 同时保留“部分上涨推动”和“上涨锯齿修正”替代解释 |

### 14.3 生命周期、可见性与概率夹具

| ID | 场景 | 预期 |
| --- | --- | --- |
| F17 | forming extreme 连续创新高 | forming 端点变化，confirmed pivot/swing/key 完全不变 |
| F18 | 同一前缀分别用 t 与 t+n 重放 | t 时已确认 pivot 的 key/extreme/confirmed 完全一致 |
| F19 | 全量运行与逐 bar 增量运行 | 所有 confirmation、scenario snapshot 相同 |
| F20 | 相同 scenario 新增一个合法 pivot | 新 `scenario_key`、相同 lineage、parent 指向旧 key |
| F21 | 新证据硬失效主场景但备选仍有效 | 主场景终止快照 INVALIDATED；备选重新排名，不改旧快照 |
| F22 | 日线 as_of 晚于 120 分钟模块决策时点 | 模块不得读取尚未闭合日线 |
| F23 | horizon 内无推进也无失效 | label 必须为 unresolved，不可丢弃 |
| F24 | 同一 bar 同时推进与失效 | 按冻结 tie policy 标记并保留 diagnostics |
| F25 | 概率三项为 `0.2/0.3/0.5` | simplex check 通过 |
| F26 | 概率缺 outcome、总和不为 1、版本不匹配 | 分别 fail closed 或返回非 CALIBRATED 状态 |
| F27 | `heuristic_score=0.82`，但没有合格 calibrator | 概率必须为空，状态为 `NOT_FITTED` 或有事实依据的 `INSUFFICIENT_SAMPLE` |
| F28 | 在线 feature payload 混入 `outcome_key/outcome_at` | 输入合同拒绝，防止结果侧泄漏 |
| F29 | 通用 profile 混入 `MACD_7_52_7` 或 `P0/P1/P2/P3` | 静态边界测试失败 |
| F30 | 通用输出 schema 出现 `buy/sell/position/trade_action` | 合同测试失败 |
| F31 | 输入形态只符合斜向/平台/三角形等未支持 grammar | 返回 `UNSUPPORTED`，不得套成推动或锯齿 |
| F32 | 在 `as_of=t` 的输入后附加 t 之后的 bar | t 快照必须与原前缀完全一致；adapter 若把未来 bar 传入则拒绝 |

### 14.4 score profile 字面夹具

| ID | 输入 | 字面 expected |
| --- | --- | --- |
| F33 | W2/W1 比例依次为 `0.618/0.382/0.332/0.331` | proximity 依次为 `1/0.5/0/0` |
| F34 | C/A 比例依次为 `1.000/1.618/1.668` | proximity 依次为 `1/0.5/0`；验证 `I=L` 退化边界 |
| F35 | `duration(W1)=8,duration(W3)=6` | `T3=0.75` |
| F36 | W5/W1 时长比例依次为 `0.5/1.0/2.0` | `T5` 依次为 `0.5/1/0` |
| F37 | `depth2=0.6,depth4=0.3,duration(W2)=5,duration(W4)=10` | `depth_score=0.6,time_score=0.5,alternation=0.55` |
| F38 | 推动已确认 3 腿；锯齿已确认 2 腿 | completeness 分别为 `0.6` 与 `2/3` |
| F39 | 推动到 W3；两个 Fibonacci component 和 T3 均为 1 | `ranking_score=7.3/17=0.42941176,score_coverage=0.5,heuristic_score=0.85882353` |
| F40 | channel 缺失或有效 | V1 均为 `NOT_APPLICABLE/NULL/coverage=0/weight=0`，不得回填 0.5 |
| F41 | 场景 A `heuristic=1,coverage=0.2`；场景 B `heuristic=0.8,coverage=1` | `ranking_score` 分别为 `0.2/0.8`，B 排在 A 前 |
| F42 | 任一比例分母为 0、NaN 或负数 | component `NOT_YET_EVALUABLE`，不得记 0 分或中性分 |
| F43 | 只修改任一权重、区间、容差或聚合公式 | 必须更换 `score_profile_version`；旧快照不覆盖 |

所有断言比较使用公式计算值；展示层可四舍五入，但排序必须使用未展示舍入前的值。

### 14.5 周期无关性夹具

| ID | 输入 | 字面 expected |
| --- | --- | --- |
| F44 | 将同一规范价格序列分别包装成 `1d/120min/60min/30min` 的闭合 Canonical Bars | 除包含 `freq/bar_end_at` 的稳定身份外，pivot 相对位置、方向、规则状态、场景类型和全量/增量一致性相同；核心不得读取每天 bar 数或跨周期复用状态 |

### 14.6 硬约束到测试的映射

| 硬约束 | 必须覆盖的金标/门禁 |
| --- | --- |
| C01 只读 as-of 前缀 | F18、F22、F32 |
| C02 extreme/confirmed 双时点 | F02、F03、F07 |
| C03 confirmed 事实不静默改写 | F17、F18、F20、F21 |
| C04 forming 隔离 | F06、F17 |
| C05 pivot 高低交替 | F09～F16、F19 |
| C06 确定性 | F05、F18、F19、F20、F33～F44 |
| C07 hard/soft/未知三态 | F12、F13、F23、F40、F42 |
| C08 多场景 | F16、F21 |
| C09 heuristic 不是 probability | F27、F39、F41 |
| C10 outcome 与在线特征隔离 | F28 |
| C11 概率版本和 simplex | F25、F26、F27 |
| C12 周期无关内核、单周期独立、跨周期显式可见 | F22、F44 |
| C13 通用内核不含四浪专项 | F29 |
| C14 不产出交易指令 | F30 |
| C15 未支持形态不误标 | F31 |
| C16 历史修正可回放 | F18、F20、F21、F43 |

---

## 15. G0 决策记录

D01～D09 由用户在 2026-08-08 明确选择推荐项；D10 随后按第 11 节方案确认。确认不是一句摘要：每项都已经回写到正文合同、夹具或门禁。

| 编号 | 决策 | 合同结果 | 状态 | 落点 |
| --- | --- | --- | --- | --- |
| D01 | ATR 初始化 | 第 14 根取前 14 个 TR 均值，之后 Wilder RMA | `CONFIRMED` | §5.2、F01 |
| D02 | 相等极值 | 只在严格更高/更低时更新，平价保留更早极值 | `CONFIRMED` | §5.4、F05 |
| D03 | 确认 bar 后反向候选 | `NEXT_BAR_RESET` | `CONFIRMED` | §5.5、F06 |
| D04 | 首版 grammar | 标准非斜向非截短推动 + 基础锯齿修正 | `CONFIRMED` | §9、F09～F16、F31 |
| D05 | 首版 degree | 每个周期只启用 `BASE_ATR14_1P5_V1` 一个尺度 | `CONFIRMED` | §8 |
| D06 | 场景上限 | 每 as-of/degree 最多展示 5 个，保留剪枝诊断 | `CONFIRMED` | §10.5 |
| D07 | 通用 progression 期限 | 20 bars 为主，10/40 bars 做敏感性 | `CONFIRMED` | §12.3 |
| D08 | 同 bar outcome 冲突 | `INVALIDATION_FIRST` | `CONFIRMED` | §12.2、F24 |
| D09 | 概率展示门禁 | 200 校准 + 100 样本外 + 各关键类 20；优于基准且 ECE<=0.10 | `CONFIRMED` | §12.7 |
| D10 | `score_profile_v1` | 采用 §11 的公式、缺失语义、grammar 权重、channel 排除和 `ranking_score` | `CONFIRMED` | §11、F33～F43 |

D01～D10 共同构成 G0 V1 冻结基线。后续修改任何一项都必须升级对应 contract/profile version，并按新版本完整重放；不得在 `v1-frozen` 名义下静默调参。

---

## 16. G0 验收对账

| 验收问题 | 本稿答案 | 状态 |
| --- | --- | --- |
| 一个字段什么时候可见？ | 第 3、4、6、7 节按 bar/extreme/confirm/as-of 定义 | 已冻结 |
| 违反规则后怎样处理？ | 输入 fail closed；hard rule INVALIDATED；soft rule 只扣分 | 已冻结 |
| 形成中端点怎样变化？ | 只在 forming leg，不能进入 confirmed 事实 | 已冻结 |
| 场景怎样随行情修正？ | snapshot 不覆盖；key + lineage + parent 形成演化链 | 已冻结 |
| 怎样逐时点回放？ | 使用 `bar_end_at<=as_of` 的前缀并保存完整版本 | 已冻结 |
| 怎样避免分数冒充概率？ | 独立 outcome、label、calibrator 和展示门禁 | 已冻结 |
| 日线、120、60、30 分钟及后续周期怎样共存？ | 同一周期无关内核分别运行；单周期状态独立，跨周期只进显式模块 | 已冻结并补充周期无关验收 |
| 四浪案例是否污染通用能力？ | C13 明确禁止 | 已冻结边界 |
| 算法正反例是否明确？ | F01～F44，并逐条映射 C01～C16 | 已落成测试文件并全部通过 |
| 所有数值和公式是否已拍板？ | D01～D10 已确认；`score_profile_v1` 使用 §11 冻结口径 | 已冻结 |

G0 完成条件对账：

1. D01～D10 全部确认：已完成。
2. 本文状态改为 `v1-frozen`：已完成。
3. 上游源码审计文档逐条对账且无相反口径：已完成。
4. G1 独立授权门禁：用户已明确批准，现已完成；实现与验收见 G1 记录。

---

## 17. 下一步

G0 保持冻结，G1 已完成。本次不自动进入 G2。

用户另行批准 G2 后，第一轮只对主要指数日线和 120 分钟数据做真实数据只读对照，不写正式 Lake。60/30 分钟直接过滤 `09:30` 竞价行的合同已经冻结，待专用 adapter 实现和验收后再扩展；API、Wealth、正式界面和四浪专项仍不进入当前阶段。
