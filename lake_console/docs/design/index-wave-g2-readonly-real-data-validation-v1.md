# 通用波浪识别 G2 真实数据只读验证与概率校准记录 v1

- 版本：v1
- 状态：G2 第一轮实现与全量只读验证已完成；日线通过，120 分钟带 1 个引擎失败项；不自动进入 G3
- 更新时间：2026-08-08
- 数据截止：日线 2026-08-07，120 分钟 2026-08-04
- 适用范围：10 个非北交所主要指数，日线与 120 分钟分别运行
- 依据：[G0 冻结合同](./index-wave-g0-generic-contract-v1.md)、[G1 实现与验收记录](./index-wave-g1-core-implementation-and-acceptance-v1.md)

## 0. 结论

G2 已把 G1 纯内核接到真实 Silver 数据，并完成因果逐 bar 回放、标签生成、固定分箱概率校准和样本外门禁。整个过程只读，没有写 Lake、数据库或 Dagster 状态。

第一轮结论分成两部分：

1. 日线 10 个指数全部完成，概率门禁通过。`HEURISTIC_BINNED_DIRICHLET_V1` 在日线样本外同时优于训练先验的 Brier 和 Log Loss，ECE 为 0.0136，因此日线的通用 progression 模块具备第一版“可发布概率”的统计资格。
2. 120 分钟 9 个指数完成，`000016.SH` 因 2025-04-07 巨幅跳空触发 G1 摆动方向矛盾而失败。其余样本的分箱模型虽然样本数和 ECE 达标，但 Brier 与 Log Loss 都差于训练先验，因此 120 分钟概率必须保持关闭。

这不证明“波浪理论有效”，也不表示日线概率可以直接用于交易。它只证明：在当前结果空间、20-bar 观察期、10 指数集合、当前时间切分和当前数据快照下，日线启发式分箱通过了预先冻结的最小校准门禁，而 120 分钟没有通过。

## 1. 范围与禁止项

本轮只做：

1. `silver/index_daily` 到 Canonical Bar 的版本化适配。
2. `silver/quote/major_index_mins/freq=120min` 到 Canonical Bar 的版本化适配。
3. 10 个非北交所指数的逐周期独立回放。
4. Pivot、确认延迟、场景、稳定性、标签、概率和性能审计。
5. 五 bar 因果 Fractal 的解释性对照，只比较 pivot 密度与确认延迟。

本轮没有：

- 写正式 Lake、数据库或 Parquet；
- 新增 Dagster asset、job、sensor、check 或动态分区；
- 接 API、Wealth、前端或正式指数详情页；
- 实现 30/60 分钟 adapter；
- 实现四浪专项或 `MACD(7,52,7)`；
- 搜索 ATR 倍数、修改 `SCORE_PROFILE_V1` 或按结果调参；
- 输出买卖、仓位或交易动作。

## 2. 代码结构与边界

周期无关的 G1 核心仍位于：

```text
lake_console/orchestrator/src/orchestrator/analysis/index_wave/
```

G2 的周期和 Lake 路径相关代码单独位于：

```text
lake_console/orchestrator/src/orchestrator/analysis/index_wave_research/
  source_adapters.py
  research_sources.py
  research_calibration.py
  research_validation.py
```

这样做的原因是：G1 核心禁止出现 `1d/120min/60min/30min` 的周期分支；真实源适配属于上游研究边界，不能污染通用 pivot、swing、scenario 语义。

G2 同时修正了一个 G1 性能缺陷：`iter_wave_replay` 原本虽然逐项 `yield`，内部仍重复保存所有历史快照。现在 `IncrementalWaveReplay` 默认行为不变，但流式入口显式使用 `retain_snapshots=false`；`replay_wave` 仍由调用方保留完整返回快照，外部语义没有改变。

## 3. 数据合同

### 3.1 研究指数池

第一版排除北证 50，固定为：

```text
000001.SH  399001.SZ  399006.SZ  000688.SH  000300.SH
000905.SH  000852.SH  000510.SH  000016.SH  000680.SH
```

指数池在研究包中显式冻结，不复用处于其他开发中的调度合同，也不把 BSE 数据混入概率分母。

### 3.2 日线

源合同版本为 `SILVER_INDEX_DAILY_CANONICAL_V1`：

- `bar_end_at = trade_date 15:00 Asia/Shanghai`；
- 只读取 `bar_end_at <= as_of` 的闭合 bar；
- 按 SSE 开市日历核对从首根到末根的完整日期序列；
- 不排序修复、不去重、不填充 OHLC；
- 每根 bar 保存源分区、合同版本和数据快照身份。

`000688.SH` 在 2019-12-31 有一条 `close=1000`、但 `open/high/low=NULL` 的指数基准点记录。它不是完整 K 线。V1 只允许把“第一根完整 K 线之前、且恰好只缺 open/high/low 的 close-only 基准点”分类为：

```text
LEADING_CLOSE_ONLY_REFERENCE_OBSERVATION
```

这条记录被显式计数后不进入 Canonical Bars，`000688.SH` 日线从 2020-01-02 开始。任何中段 OHLC 缺失、缺 close 或其他前导缺失形态仍然 fail closed，不能套用该例外。

### 3.3 120 分钟

源合同版本为 `SILVER_MAJOR_INDEX_MINS_120M_CANONICAL_V1`：

- `freq` 必须等于 `120min`；
- 每个开市日必须恰好存在 11:30、15:00 两根闭合 bar；
- `trade_time` 统一解释为 `Asia/Shanghai`；
- 不接收 09:30 竞价行，不做 30/60 分钟合并；
- 不允许缺日、缺根、重复、乱序、跨代码或未来 bar。

### 3.4 数据快照

快照 ID 对截至 `as_of` 可见的 Parquet 文件及交易日历文件的相对路径、大小、mtime 和源合同版本做 SHA-256。2026-08-08 本轮使用：

| 周期 | 快照 ID | 文件数（含日历） | 文件大小 |
| --- | --- | ---: | ---: |
| 日线 | `sha256:17959c099c35f82b0e57b6d67afd568adb00fcaa5fd7c8ec45e4087db4a72f2c` | 6,446 | 180,248,121 bytes |
| 120 分钟 | `sha256:6d3f59ca784fd7fbc0ae869f83c69fc6a6c277d549a226aea687923b2b373a40` | 4,272 | 10,329,842 bytes |

它是研究输入清单指纹，不是正式 Lake snapshot 资产，也没有被写回数据湖。

## 4. 回放与标签口径

每个 `ts_code/freq` 独立使用：

```text
detector = CAUSAL_ATR14_1P5_V1
degree   = BASE_ATR14_1P5_V1
```

每个场景 lineage 只在第一次进入 `ACTIVE` 时建立一个 progression 事件，避免把同一场景在连续 bar 上的重复快照当成独立样本。事件从决策 bar 的下一根开始观察：

- 同 lineage 的 `confirmed_wave_count` 增加：`next_phase_confirmed`；
- 同 lineage 进入 `INVALIDATED`：`scenario_invalidated`；
- 观察期耗尽仍无结果：`unresolved`；
- 同一 bar 同时推进和失效：保持 G0 冻结的 `INVALIDATION_FIRST`。

主观察期为 20 bars，同时记录 10/40 bars 敏感性。末端未来 bar 不足时不生成成熟标签。

## 5. 概率校准方法

第一版模型固定为 `HEURISTIC_BINNED_DIRICHLET_V1`，不是把启发式分数乘以 100：

1. 按决策时间的唯一时点做 60%/20%/20% 的 train/calibration/test 切分。
2. 同一决策时点的不同指数不会跨集合。
3. 标签成熟时间跨越下一集合起点的事件执行 embargo。
4. train 集只估计三分类全局先验，使用每类 `alpha=1` 平滑。
5. calibration 集按启发式分数固定分箱：`[0,.2)/[.2,.4)/[.4,.6)/[.6,.8)/[.8,1]`，另设 missing 箱。
6. 每箱结果用强度 3 的 Dirichlet 先验向 train 全局先验收缩。
7. test 集只使用已经冻结的箱后验预测。

日线与 120 分钟完全分别拟合和评估，不共享概率。

发布门禁保持 G0 原值：calibration 至少 200、test 至少 100、两个非 unresolved 类各至少 20，且 Brier/Log Loss 不差于 train-rate baseline、ECE 不超过 0.10。任一失败时只保留启发式和研究报告，不输出概率。

## 6. 全量结果

### 6.1 聚合结果

| 指标 | 日线 | 120 分钟 |
| --- | ---: | ---: |
| 请求序列 | 10 | 10 |
| 成功序列 | 10 | 9 |
| 失败序列 | 0 | 1 |
| 进入回放的 bars | 40,473 | 52,302 |
| 已确认 pivots | 4,952 | 6,513 |
| 五 bar Fractal pivots | 10,091 | 13,411 |
| 首次 ACTIVE 事件 | 4,988 | 6,464 |
| 成熟 20-bar 标签 | 4,966 | 6,444 |
| next phase | 3,054 | 4,122 |
| invalidated | 1,648 | 2,012 |
| unresolved | 264 | 310 |
| 分析耗时合计 | 28.57 s | 53.80 s |
| 进程峰值 RSS | 497,418,240 bytes | 275,578,880 bytes |

日线每指数 pivot 密度为每 100 bars 约 9.91～12.95，120 分钟成功序列为 11.38～12.67。两个周期的 pivot 确认延迟中位数通常为 2 bars。作为对照，五 bar Fractal 的确认延迟固定为 2 bars，但 pivot 密度大约是 ATR detector 的两倍；因此它只作为解释性对照，不能替代 G1 场景输入。

主场景 lineage 的连续稳定率：

- 日线约 92.75%～94.27%；
- 120 分钟约 92.98%～93.94%。

这里的稳定率只表示相邻非空快照的第一名 lineage 是否保持一致，不表示预测准确率。

### 6.2 日线概率门禁

| 项目 | 结果 |
| --- | ---: |
| train | 2,988 |
| calibration | 972 |
| test | 996 |
| train embargo | 2 |
| calibration embargo | 8 |
| Brier | 0.514553 |
| baseline Brier | 0.528672 |
| Log Loss | 0.797521 |
| baseline Log Loss | 0.823440 |
| ECE | 0.013611 |
| test next phase / invalidated | 572 / 392 |
| 结论 | `CALIBRATED`，门禁通过 |

日线结果只授权该模型版本、该 outcome、该 horizon 和该数据快照的研究概率资格。任何换周期、换分箱、换标签或更新数据后都必须重新训练和过门禁。

### 6.3 120 分钟概率门禁

| 项目 | 结果 |
| --- | ---: |
| train | 3,848 |
| calibration | 1,192 |
| test | 1,394 |
| train embargo | 6 |
| calibration embargo | 4 |
| Brier | 0.507163 |
| baseline Brier | 0.506160 |
| Log Loss | 0.869613 |
| baseline Log Loss | 0.832293 |
| ECE | 0.009747 |
| test next phase / invalidated | 878 / 426 |
| 结论 | `NOT_FITTED`，禁止发布概率 |

120 分钟失败不是样本不足，也不是 ECE 过高，而是当前固定分箱模型比“不看启发式分数、只使用训练结果比例”的基线更差。这是直接证据：当前 120 分钟 `heuristic_score` 不能解释为三分类概率。

## 7. 已知失败：000016.SH / 120min

失败原因码：

```text
SWING_PRICE_DIRECTION_CONTRADICTION
```

最小冲突：

```text
前一已确认 LOW：2025-04-03 11:30，2631.4749
后一确认 HIGH：2025-04-07 11:30，2579.5970
```

清明休市后的 2025-04-07 11:30 bar：

```text
open=2555.7102 high=2579.5970 low=2488.4120 close=2521.6118
```

该 bar 整体跳空到前低以下，同时 `high-close` 又超过当时 ATR 反转阈值，导致 append-only detector 确认一个低于前 LOW 的 HIGH。Pivot 类型交替成立，但实际价格方向不成立，所以 `build_confirmed_swings` 正确拒绝了它。

G2 不采用以下伪修复：

- 不删除 4 月 7 日行情；
- 不放宽“UP swing 必须上涨”的规则；
- 不把负振幅的 LOW→HIGH 强行标成上涨；
- 不重写历史已确认 pivot。

正式解决需要单独设计并冻结“跨休市价格跳空的 detector segment reset”或“已确认 pivot 的可审计 supersession/revision”合同，并补人工金标、前缀不变和场景生命周期测试。在该合同完成前，`000016.SH/120min` 不进入 120 分钟校准分母。

## 8. 性能与可持续运行

初次整表 DuckDB glob 扫描会为数千个小 Parquet 文件建立较大的元数据状态。G2 改为：

- 单线程 DuckDB；
- 每批最多 256 个分区文件；
- 每次只读取一个指数、一个周期和必要字段；
- 读取结束即关闭连接；
- 流式 replay 不在引擎内部重复保留快照；
- 每个序列完成后释放 bars 与分析对象。

门禁为单序列 30 秒、进程峰值 RSS 512 MB。最长成功序列的分析耗时约 10.02 秒；两个全量频率运行均未越过门禁。`peak_memory_bytes` 使用进程 `ru_maxrss`，是运行到该序列时的进程峰值，不应误读为该序列独占内存。

## 9. 验收与复现

新增测试覆盖：

- 日线 15:00 闭合时点、来源 lineage、日期完整性、future as-of；
- 120 分钟 11:30/15:00 双 bar、错误周期、错误时点和缺根；
- 缺 OHLC 的稳定 fail-closed 原因码；
- 只允许前导 close-only 基准点分类；
- 五 bar Fractal 的两 bar 因果确认；
- 流式 replay 不重复保留历史快照；
- progression 同 bar 推进/失效事实；
- 时间切分 embargo；
- Dirichlet 概率 simplex；
- 样本不足时概率门禁关闭。

复现命令：

```bash
cd lake_console/orchestrator
PYTHONPATH=src python -m \
  orchestrator.analysis.index_wave_research.research_validation \
  --as-of 2026-08-08T00:00:00+08:00
```

命令只向 stdout 输出 JSON，不创建结果文件、不写 Lake。

## 10. 阶段结论与下一步门禁

G2 第一轮实现和真实数据验证已经执行，但验收结论不是“全绿”：

1. 日线 adapter、回放、标签和第一版概率校准通过。
2. 120 分钟 adapter 和 9 个序列回放通过，但有 1 个真实跳空场景暴露 G1 detector/swing 合同缺口。
3. 120 分钟概率门禁失败，当前不得展示概率。
4. 30/60 分钟 adapter、G3 持久化/版本演化、G4 回测扩展均未获本轮自动授权。

进入下一轮前应先单独评审“价格跳空下的 pivot 修正/分段语义”。在此之前，不应为了让 120 分钟全绿而修改 V1 阈值或吞掉失败样本。
