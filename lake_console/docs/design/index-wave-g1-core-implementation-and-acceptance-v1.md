# 通用波浪识别 G1 纯内核实现与验收记录 v1

- 版本：v1
- 状态：G1 已完成；G2 尚未开始
- 更新时间：2026-08-08
- 适用范围：通用、因果、周期无关的波浪识别研究内核
- 依据：[通用波浪识别 G0 冻结合同 v1](./index-wave-g0-generic-contract-v1.md)

## 0. 结论

G1 已经把 G0 的纸面合同实现成一套可执行的 Python 纯领域内核，并完成 F01～F44 金标验收。

它现在可以完成以下工作：

1. 接收经过上游时段和连续性检查的 Canonical Bars。
2. 用固定的 `ATR(14) × 1.5` 因果 ZigZag profile 确认高低拐点。
3. 分开保存极值发生时间 `extreme_at` 和系统首次可知时间 `confirmed_at`。
4. 构造已确认 swing，并把形成中的最后一腿单独标为 provisional。
5. 同时生成标准推动浪、基础锯齿修正浪及其替代场景。
6. 按硬规则决定保留或失效，按软特征和证据覆盖率做确定性排序。
7. 按每根 bar 重放历史判断，保存 scenario key、lineage 和 parent 演化关系。
8. 为通用 `wave_scenario_progression` 模块生成三分类历史标签，并验证概率 simplex、版本和校准门禁。

G1 没有读取 Lake，没有新增 Dagster asset，没有写数据库或 Parquet，没有训练出真实概率，也没有实现四浪专项、API、Wealth 或正式界面。因此，G1 完成表示“算法合同可执行、可测试”，不表示“波浪理论已经被 A 股历史证明有效”。

## 1. 实现边界

### 1.1 本轮新增

代码位于：

```text
lake_console/orchestrator/src/orchestrator/analysis/index_wave/
```

这是独立纯领域包，不 import Dagster，不依赖现有 MACD 服务，也不读取任何具体 Lake 路径。

| 文件 | 责任 |
| --- | --- |
| `bars.py` | Canonical Bar、通用 row adapter、排序/唯一性/OHLC/连续性/as-of 校验 |
| `profiles.py` | detector、degree 和通用 profile 边界 |
| `pivot.py` | Wilder ATR、append-only 因果 Pivot 状态机、稳定 pivot 身份 |
| `swings.py` | Confirmed Swing 与 Forming Leg |
| `grammar.py` | 标准推动浪、基础锯齿修正浪及硬规则三态求值 |
| `scoring.py` | `SCORE_PROFILE_V1`、比例/时间/交替/完整度及证据加权排名 |
| `scenarios.py` | 多起点、多语法场景、排序、剪枝、lineage、parent 和生命周期 |
| `replay.py` | 全量前缀 replay、append-only 增量 replay、流式 replay |
| `progression.py` | 通用下一阶段/失效/未决三分类标签器 |
| `calibration.py` | 概率合同、时间切分防泄漏、Brier/log loss/ECE 展示门禁 |
| `identities.py` | Decimal、时间和哈希的稳定序列化 |

### 1.2 本轮没有新增

- 没有新增数据库表、Parquet、DuckDB 或 ClickHouse schema。
- 没有新增 Dagster asset、check、job、sensor、bootstrap 或 runless event。
- 没有修改指数日线、主要指数分钟线或 MACD 数据合同。
- 没有连接 Wealth、API 或前端。
- 没有加入 `MACD(7,52,7)`、`P0/P1/P2/P3` 或四浪三分类。
- 没有输出买卖、仓位或交易动作字段。

因此，本轮不改变 `foundation/ops/biz/app` 依赖矩阵，也不产生正式数据迁移。

## 2. 数据怎样进入内核

G1 的 adapter 是内存边界，不是新数据源。调用方需要先提供：

```text
ts_code + freq + trade_date + bar_end_at
+ OHLC + 可选 vol/amount
+ source lineage + data_snapshot_id
+ continuity_status + as_of
```

adapter 保留输入顺序，不会偷偷排序、去重或跳过坏 bar。以下情况整次 fail closed：

- bar 重复或乱序；
- `bar_end_at > as_of`；
- OHLC 非有限数、非正数或包络错误；
- 标的、周期或数据快照混用；
- 连续性为 `GAP/UNKNOWN`；
- 时区偏移不符合该历史时点真实的 `Asia/Shanghai` 规则。

最后一项不能简单写死为 UTC+8。上海在部分历史年份存在夏令时，内核按 IANA `Asia/Shanghai` 的历史偏移校验，避免早期日线被错误拒绝。

## 3. Pivot 怎样确认

正式研究 profile 固定为：

```text
CAUSAL_ATR_ZIGZAG_V1
ATR period = 14
ATR seed = 前 14 个 TR 算术平均
ATR smoothing = Wilder RMA
reversal threshold = extreme bar ATR × 1.5
extreme source = high/low
confirmation source = close
equal extreme = 保留更早时点
dual confirmation = 等待无歧义 bar
post confirmation = NEXT_BAR_RESET
```

状态机是 append-only 的：

```text
WARMUP -> UNDEFINED -> UP <-> DOWN
```

确认 bar 只确认上一个极值，同一 bar 的反方向 low/high 不会被偷用为下一候选。这保证了 OHLC 无法证明日内先后时，系统选择保守而可复现的解释。

G1 还提供 `ABSOLUTE_REVERSAL_TEST`，只用于把状态机与 ATR 公式拆开验证。它带 `research_eligible=false`，不能误用于正式研究结果。

## 4. 已确认事实与形成中状态

### 4.1 Confirmed-only

Confirmed Pivot 和 Confirmed Swing 是回测可用事实。每个 pivot 同时保存：

- 极值在哪根 bar 出现；
- 何时第一次满足确认条件；
- 当时使用的阈值；
- 极值 bar、确认 bar 和上游来源身份；
- model、degree、detector 和 data snapshot 版本。

已确认 pivot 的稳定 key 不含 rank、运行号或生成时间。后续 forming extreme 移动，不会改变旧 pivot、旧 swing 或其 key。

### 4.2 Provisional

Forming Leg 只连接最后一个 confirmed pivot 与当前候选 extreme：

- 没有 `to_pivot_key`；
- `uses_provisional=true`；
- 不增加 `confirmed_wave_count`；
- 不作为默认历史事件证据。

Replay 同时返回 confirmed scenario 和附带 forming leg 的 provisional view，二者不会混成一套含糊输出。

## 5. 场景、规则和修正

G1 支持两个 grammar：

1. `IMPULSE_STANDARD_V1`：标准、非斜向、非截短五浪推动。
2. `CORRECTIVE_ZIGZAG_V1`：基础 A-B-C 锯齿修正。

每个已确认 pivot 序列可以同时产生多种解释。场景先做硬规则求值：

- `PASS`：证据足够且规则满足；
- `FAIL`：证据足够且规则违反，场景立即 `INVALIDATED`；
- `NOT_YET_EVALUABLE`：还缺后续 confirmed pivot，不能假装已经通过。

场景身份分成三层：

- `scenario_key`：精确结构身份，结构延长后改变；
- `scenario_lineage_key`：同一起点、方向和 grammar 的演化链身份；
- `parent_scenario_key`：指向延长前的直接父结构。

旧快照是 frozen dataclass。新行情只能产生新快照、子场景或 terminal snapshot，不能覆盖昨天的答案。

### 5.1 G1 补齐的最小阶段语义

G0 定义了 `CANDIDATE/ACTIVE`，但没有给出 active 最小腿数。G1 为了让状态可执行，固定以下 V1 语义：

```text
1 条 confirmed leg -> CANDIDATE
2 条及以上、尚未完整、硬规则未失败 -> ACTIVE
达到完整 grammar -> COMPLETED
任一已可判断硬规则失败 -> INVALIDATED
```

这不是统计参数，不影响 pivot 事实，但属于 grammar 生命周期语义。以后若修改，必须升级 grammar/engine version 并完整重放。

## 6. 启发式分数不是概率

`SCORE_PROFILE_V1` 严格实现 G0 第 11 节：

- Fibonacci 比例贴合；
- 推动浪时间比例；
- 二四浪深度/时长交替代理；
- 结构完整度；
- Channel V1 固定 `NOT_APPLICABLE` 且权重为 0。

证据不足的 component 不填 0，也不填中性 0.5。系统分别输出：

```text
heuristic_score = 已获得证据的平均贴合度
score_coverage  = 完整 profile 中已有多少证据
ranking_score   = 贴合度 × 有效证据质量的保守排序量
```

修改任一权重、比例区间、容差或聚合公式而仍沿用 `SCORE_PROFILE_V1`，构造 profile 时会直接失败。

## 7. Replay 与随行情修正

G1 有两种执行方式：

1. `replay_wave`：保留每个前缀快照，适合测试和小样本审计。
2. `iter_wave_replay`：逐 bar 流式产出快照，适合 G2 长历史，只需把当前结果交给统计器或后续持久化层。

增量引擎每根 bar 只 append 一次。若 confirmed pivots 没变化，硬规则、软特征和稳定身份直接复用，只更新时间可见性；形成中腿仍随当前 bar 更新。这既保持前缀因果性，也避免每根 bar 从头扫描全历史。

人工性能探针使用 10,000 根周期性价格 Canonical Bars、`ATR(14) × 1.5` 和流式 replay：

```text
bar 数：10,000
confirmed pivot 数：500
墙钟时间：约 6.73 秒
最大常驻内存：约 165 MB
```

环境为当前开发机，数据为人工序列，只能说明复杂度已经足够进入 G2 真实数据测量，不是生产 SLA。G2 必须按真实日线和 120 分钟数据分别报告耗时、内存、pivot 密度和场景数。

## 8. Outcome、概率与泄漏门禁

首个通用模块 `wave_scenario_progression` 只研究：20 bars 内是先确认下一阶段、先硬失效，还是期限结束仍未决。

```text
next_phase_confirmed
scenario_invalidated
unresolved
```

- 决策 bar 不进入未来观察窗口。
- 同一 bar 同时推进和失效时固定 `INVALIDATION_FIRST`。
- 未满 20 根未来 bar 时不生成不完整 label。
- 在线 module snapshot 的字段结构和 payload 都禁止 `outcome_key/outcome_at`。
- 同一 event 或 scenario lineage 禁止跨 train/calibration/test 集合。
- 不同 `freq` 禁止混入同一校准评估。

概率只有在版本一致、三类 key 完整、每项位于 `[0,1]`、总和为 1、区间合法并通过样本外门禁时才可标为 `CALIBRATED`。没有 calibrator 时，即使 `heuristic_score=0.82`，概率仍必须为空。

G1 只实现合同和评估 harness，没有用真实历史训练 calibrator。真实概率是否能通过 200/100/每关键类 20、Brier、log loss 和 ECE 门禁，要到 G2 才能回答。

## 9. 测试与验收

测试文件：

```text
lake_console/orchestrator/tests/test_index_wave_g1_golden_contracts.py
```

测试函数逐一命名为 `test_f01...test_f44`，没有调用被测代码生成 expected。参数化反例展开后当前结果为：

```text
69 passed
```

验收覆盖：

- F01～F08：ATR、阈值、双向歧义、平价极值、reset 和输入 fail closed；
- F09～F16：上涨/下跌推动、锯齿、硬失效和多解释；
- F17～F32：forming、前缀不变、全量/增量、lineage、跨周期可见性、标签、概率和静态边界；
- F33～F43：所有字面评分公式、缺失证据和版本门禁；
- F44：同一价格序列包装成 `1d/120min/60min/30min` 后，结构语义一致，身份按周期隔离。

附加静态门禁还验证：

- G1 包没有 Dagster import；
- 核心源码没有四个周期的字面分支；
- Scenario schema 没有交易动作字段；
- 在线模块 schema 没有未来 outcome 字段；
- ATR detector 的 append-only 结果与独立 Wilder 公式一致。

执行命令：

```bash
cd lake_console/orchestrator
ruff check src/orchestrator/analysis/index_wave tests/test_index_wave_g1_golden_contracts.py
PYTHONPATH=src:.venv/lib/python3.13/site-packages \
  /Users/congming/github/goldenshare/.venv/bin/pytest -q \
  tests/test_index_wave_g1_golden_contracts.py
```

## 10. 仍然不能得出的结论

G1 通过后仍不能声称：

- 当前指数处于第几浪；
- `ATR(14) × 1.5` 是中国指数最优 detector；
- heuristic score 是场景成立概率；
- 某个浪型构成买卖信号；
- 30/60 分钟“过滤 `09:30` 竞价行”的专用 adapter 已经实现或通过真实数据验收；
- 四浪反弹或 `MACD(7,52,7)` 结论已经被验证。

## 11. 下一步门禁

G1 到此停止，不自动进入 G2。

若用户批准 G2，第一轮只读运行主要指数日线和 120 分钟：

1. 分别实现并冻结两个真实数据 adapter；
2. 不跨周期默认确认；
3. 不写正式 Lake；
4. 报告 pivot 密度、确认延迟、场景数量、空结果、耗时和内存；
5. 按时间切分生成 progression 标签并审计概率门禁；
6. 发现参数表现差时只报告，不在 `V1` 名义下静默调参。

30/60 分钟竞价行口径已经冻结：直接分析时过滤 `09:30`，不生成独立 Canonical Bar，也不并入第一根常规 K 线。对应 adapter 和真实数据验收尚未实现，因此仍不作为 G2 第一轮日线/120 分钟门禁；后续扩展不得修改 G1 周期无关内核。四浪专项继续保持独立，不进入 G2 通用验收。
