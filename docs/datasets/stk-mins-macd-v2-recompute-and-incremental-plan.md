# 股票分钟线 MACD v2 重算与增量可靠性方案

- 版本：v1
- 状态：当前参考；clean 基准已切到 `research/stk_mins_by_date_clean_next`
- 更新时间：2026-05-13
- 适用范围：`lake_console` 本地 Parquet Lake
- 指标范围：`MACD(12,26,9)`
- 数据范围：`stk_mins` 的 `1/5/15/30/60/90/120` 分钟线
- 最高优先级：准确 > 性能 > 增量可靠

---

## 0. 当前 clean 基线口径

截至 2026-05-13，正式 clean 基准为：

```text
research/stk_mins_by_date_clean_next
```

已删除的历史错误 clean 路径：

```text
research/stk_mins_by_date_clean
```

本文所有可执行设计都以 `clean_next` 为准。后续 90/120 分钟线、by-month research、MACD 计算都不能直接读取旧错误 clean，也不能绕过 `clean_next` 直接把 raw 当作研究输入。

## 1. 目标

本方案要把当前 MACD 从“能算出一部分结果”收口为“可以长期信任的指标资产”。

目标按优先级排序：

1. 准确第一：代码变更、上市时间、退市过滤、北交所代码切换、源分钟线补数，都不能破坏 MACD 递推连续性。
2. 性能第二：全市场多年全频率重算必须支持并行，不接受单线程长时间无收益等待。
3. 增量可靠第三：只有在全量结果、state、source watermark 都可信后，才允许增量继续递推。

本方案要解决：

1. `300114.SZ -> 302132.SZ` 这类代码变更导致的连续序列断裂。
2. 北交所 `920xxx.BJ` 新代码从特定日期开始出现，不能被错误当成老股票或假新股。
3. 当前旧 MACD by_date / research / state 已经不完整，不能继续基于旧结果补丁式修修补补。
4. 当前全市场 full 计算速度不足，需要并行化，但不能按日期切分破坏递推。
5. 后续每日增量必须能识别“源数据被重写、身份映射变化、历史补数”导致的 state 失效。

---

## 2. 不做什么

1. 不修改 `raw_tushare/stk_mins_by_date` 的原始源站代码字段。
2. 不把旧 MACD 结果当作可信基础继续增量。
3. 不按日期并行计算 MACD。
4. 不在未建立证券连续身份模型前继续做全市场 MACD 正式重算。
5. 不接生产 Ops TaskRun。
6. 不访问远程 `goldenshare-db`。
7. 不做前端页面。
8. 不做 MA / BOLL，本方案只处理 MACD 主链。

---

## 3. 当前问题

### 3.1 原始 `ts_code` 不是研究计算代码

当前分钟线 raw 层按源站 `ts_code` 保存。这对源数据是对的，但对 MACD 不够。

例子：

```text
300114.SZ：中航电测历史代码
302132.SZ：中航成飞新代码
```

如果 MACD 按原始 `ts_code` 计算：

```text
300114.SZ 的 EMA state 到 2025-02-14
302132.SZ 从 2025-02-17 重新初始化
```

这会把同一只股票拆成两条 MACD 线，结果不准确。

正确做法：

```text
300114.SZ 历史分钟线
+ 302132.SZ 新分钟线
= clean 层 ts_code=302132.SZ 的连续输入序列
```

### 3.2 上市时间不能只看当前代码

如果只看 `stock_basic` 当前代码：

```text
302132.SZ 可能看起来像 2025 年才出现
```

但它实际上继承了 `300114.SZ` 的历史，所以 MACD 不能在 2025 年从零初始化。

正确做法：

```text
latest_ts_code 的有效起点 = 该股票所有历史代码在 stock_basic 中的最早 list_date
如果 latest_ts_code 已退市，则整只股票不进入 clean
```

注意：本地分钟线文件中如果出现早于 `stock_basic.list_date` 的行，无论 OHLC 是否为 0，都不进入 clean 层。  
这些行保留在 raw 层，用于追溯源站事实；研究和指标计算只读 clean 层。

### 3.3 当前旧 MACD 结果不完整

当前 Lake 事实显示：

1. `freq=30 / 2026-04` 有一段 by_date + research 结果。
2. `freq=1` 只有到 `2025-02-14`，且历史源数据后续被修复后未重算。
3. `freq=5/15/60/90/120` 没有完整 MACD 输出。
4. `manifest/indicator_recalc_queue/stk_mins_macd.parquet` 存在大量 `pending`。

因此旧结果不能作为后续正式研究基础。

---

## 4. 新模型总览

新 MACD 主链按以下顺序执行：

```text
证券连续身份模型
-> clean by_date 分钟线事实
-> derived 90/120 分钟线
-> clean by_month 研究输入
-> 旧 MACD 产物废弃 / 清理
-> 全量准确重算
-> 完备性审计
-> 并行性能优化
-> 增量可靠更新
```

核心原则：

1. raw 层保存源站事实，不强改源站代码。
2. clean 层负责删除无效行情、过滤未退市股票上市日前数据、整只排除已退市股票，并把旧代码归一到最新代码。
3. derived 90/120 与 by_month research 必须基于 clean 层生成。
4. MACD 只读 clean by_month 输入。
5. MACD 输出只表达 clean 后的最新代码序列，不输出断裂旧代码序列。
6. state 的 key 必须是 clean 后的最新 `ts_code + freq`，不再是源站原始 `ts_code`。

### 4.1 已确认决策

本节记录 2026-05-11 评审确认项，后续实现不得再反复摇摆。

1. 代码变更后的 clean/derived/research/MACD 输出统一使用最新代码。
2. `raw_tushare/stk_mins_by_date` 不做物理改写，继续保存源站原始事实。
3. `manifest/security_identity/security_identity_map.parquet` 只记录 `source_ts_code -> latest_ts_code` 的映射关系、生效区间和审计信息；不把血缘字段重复写入每一行分钟线。
4. `research/stk_mins_by_date_clean_next` 是清洗后的干净分钟线事实层，删除无效行、清理未退市股票上市日前数据、整只排除已退市股票，并把旧代码直接归一为最新代码。
5. clean/derived/research/indicator 行级输出不得保留 `identity_id`、`source_ts_code`、`list_date`、`delist_date`、`identity_version`。
6. `derived` 的 `90/120` 分钟线必须基于 `research/stk_mins_by_date_clean_next` 生成，不再直接基于 raw。
7. `research/stk_mins_by_symbol_month` 必须基于 clean/derived 结果重排，不再直接基于 raw。
8. 对未退市股票，`stock_basic.list_date` 是有效行情起算基准；即使上市日前存在非 0 分钟线，也按无效数据处理，不进入 clean 层。
9. 对已退市股票，clean 层整只剔除，不保留退市前历史分钟线。
10. 旧 MACD 产物允许清理，但必须按 `audit -> dry-run -> apply --confirm-delete-macd-v1` 执行。
11. 并行默认 worker 数为 `4`，CLI 允许临时指定，第一版上限为 `8`。
12. v2 第一阶段先实现映射模型、clean by_date、derived/research 重建、清理旧产物、全量重算、完备性审计；增量入口等 M8 再开放。
13. 清洗和下游生成不得为了解释问题在数据集行级新增任何列。身份、代码变更、退市、审计异常、剔除依据必须记录在独立账本中。
14. `security_identity_map` 是 G1 身份账本，必须覆盖代码变更、北交所映射、退市股票、无法确认映射等 G1 审计情况。
15. G6 完备性审计暴露的问题必须记录到单独的 clean 完备性审计账本。只有账本中明确记录并确认的问题行，才能在后续 clean 修复或重建时被剔除。

### 4.2 raw 与 clean 的持续关系

`raw_tushare/stk_mins_by_date` 是源站原始事实层。每日从 Tushare 更新到最新分钟线时，新数据先写入 raw。

`research/stk_mins_by_date_clean_next` 是清洗后的研究事实层。第一版 clean 先从 raw 完整拷贝初始化，然后通过 clean rebuild 删除脏数据、统一新旧代码、过滤未退市股票上市日前数据，并整只排除已退市股票。

初始化完成后，clean 不是一次性快照。之后每日 raw 有新增分区时，新增 raw 数据必须经过同一套 clean 规则透传进入 clean，且必须保证：

1. 新增 clean 分区不能直接绕过 `security_identity_map`。
2. 新增 clean 分区不能引入无效价格、上市日前数据、已退市股票数据或身份冲突。
3. downstream 的 derived、by_month research、MACD 只能读 clean，不直接读 raw。
4. 如果 clean 增量审计失败，当日不能进入 derived/research/MACD 重建。
5. 如果 clean 增量审计发现需要剔除的问题行，必须先把问题写入 clean 完备性审计账本，再执行剔除或重建；不能直接在数据行上新增解释字段。

### 4.3 为什么不直接改 raw

直觉上，可以把 `300114.SZ` 的历史分钟线直接改成 `302132.SZ`，这样看起来就得到了一条连续序列。但这会把“源站原始事实”和“研究口径事实”混在一起。

本方案不直接改 raw，原因是：

1. raw 层的职责是记录源站当时返回了什么代码。
2. 如果把 raw 中的 `300114.SZ` 改成 `302132.SZ`，就混淆了源站事实和研究事实。
3. 如果映射规则后续发现错误，污染 raw 的恢复成本很高。
4. 源站原始代码只应在 raw 和 identity map 中追溯，不应成为 clean 事实层的行级负担。

所以本方案新增 clean by_date 层：

```text
raw_tushare/stk_mins_by_date
  保存源站原样：300114.SZ / 302132.SZ

research/stk_mins_by_date_clean_next
  保存清洗后事实：删除无效行，统一成 302132.SZ 的连续序列
```

可以把它理解为：

```text
raw 分钟线 = 源站给的原始账本
by_date_clean = 清洗后、统一代码后的干净账本
derived 90/120 = 基于干净账本派生出的周期账本
by_month research = 为长周期查询和指标计算重排后的账本
MACD 输出 = 根据干净账本算出来的结果
```

MACD 只读 clean by_month research，不直接读 raw。

---

## 5. M1：证券连续身份模型

### 5.1 目标

建立一个本地 Lake 的证券连续身份事实表，专门回答：

```text
某个源站 ts_code 应该归一成哪个最新代码？
这个源站 ts_code 的有效区间是什么？
这个最新代码从哪一天开始可以安全进入 clean 层？
```

### 5.2 输入数据

必须读取本地 Lake 文件，不访问远程 DB：

| 输入 | 路径 | 用途 |
|---|---|---|
| stock_basic manifest | `manifest/security_universe/tushare_stock_basic.parquet` | 股票基础信息、上市/退市日期 |
| stock_basic raw | `raw_tushare/stock_basic/current/*.parquet` | 正式数据集副本，辅助审计 |
| namechange | `raw_tushare/namechange/current/*.parquet` | 曾用名、代码变化线索 |
| bse_mapping | `raw_tushare/bse_mapping/current/*.parquet` | 北交所新旧代码映射 |
| stk_mins source | `raw_tushare/stk_mins_by_date/freq=*/trade_date=*/*.parquet` | 本地分钟线实际出现日期、首次有效行情日期、无效占位行审计 |

### 5.3 输出数据

新增：

```text
manifest/security_identity/security_identity_map.parquet
```

这是 G1 身份账本，不是 clean 数据集的一部分。它负责记录所有“为什么某个源代码归属某个最新代码、为什么某只股票不进入 clean”的事实依据。clean/derived/research/indicator 行级数据不得复制这些解释字段。

字段：

| 字段 | 类型 | 含义 |
|---|---|---|
| `latest_ts_code` | string | 当前或最终用于 clean 层和指标输出的最新代码 |
| `source_ts_code` | string | 源分钟线里的原始代码 |
| `valid_from` | date | 该原始代码归属该 identity 的开始日期 |
| `valid_to` | date/null | 该原始代码归属该 identity 的结束日期，当前有效则为空 |
| `effective_list_date` | date | clean 层起算日期，来自该股票历史代码链的最早 `stock_basic.list_date` |
| `effective_delist_date` | date/null | 退市日期，未退市则为空；如果不为空，该 latest_ts_code 整只不进入 clean |
| `source_first_seen_date` | date/null | 本地源文件第一次出现该代码的日期；只用于审计，不等于指标起算日 |
| `source_first_valid_trade_date` | date/null | 本地源文件第一次出现有效行情的日期；只用于审计，不得替代 `stock_basic.list_date` |
| `invalid_before_valid_days` | int | 首次有效行情前的无效占位日期数 |
| `identity_source` | string | `stock_basic` / `namechange` / `bse_mapping` / `manual_rule` |
| `confidence` | string | `confirmed` / `inferred` / `needs_review` |
| `reason` | string | 形成映射的原因说明 |
| `created_at` | timestamp | 生成时间 |

G1 审计必须在该账本中表达以下情况：

| 情况 | 账本表达 | clean 行级是否新增字段 |
|---|---|---|
| 普通股票未改代码 | `source_ts_code == latest_ts_code`，`confidence=confirmed` | 否 |
| 股票代码变更 | 多条 `source_ts_code -> latest_ts_code`，同一最新代码，区间不重叠 | 否 |
| 北交所代码切换 | `identity_source=bse_mapping` 或组合证据，保留来源说明 | 否 |
| 已退市股票 | `effective_delist_date` 非空，该 `latest_ts_code` 整只不进入 clean | 否 |
| 无法确认映射 | `confidence=needs_review`，阻断 clean 生成 | 否 |

### 5.4 关键规则

#### 规则 1：代码变更要归一为最新代码

例如：

```text
source_ts_code=300114.SZ valid_to=2025-02-16
source_ts_code=302132.SZ valid_from=2025-02-17
latest_ts_code=302132.SZ
effective_list_date=2010-08-27
```

#### 规则 2：clean 层只保留未退市股票

本地源文件中有行，不代表这支股票可以参与研究或 MACD。  
如果 `stock_basic.delist_date` 不为空，表示该股票已经退市，clean 层整只剔除，不保留退市前历史分钟线。

未退市股票的 clean 层有效时间边界：

```text
trade_date >= effective_list_date
effective_delist_date 必须为空
```

其中：

```text
effective_list_date  = identity 链上最早 stock_basic.list_date
effective_delist_date = 该股票最终 stock_basic.delist_date；若不为空则整只不进入 clean
```

有效 bar 判定仍然保留，但它只用于删除明显无效行情行，不用于替代上市日期：

```text
trade_time 不为空
open > 0
close > 0
high > 0
low > 0
high >= low
vol >= 0
amount >= 0
```

因此：

```text
source_first_seen_date        = 本地第一次看到源行的日期，只用于审计
source_first_valid_trade_date = 本地第一次看到有效行情的日期，只用于审计
effective_list_date           = stock_basic.list_date 口径，不由源文件出现时间推断
```

记录示例：

```text
identity_source=stock_basic/bse_mapping/namechange/manual_rule
confidence=confirmed 或 needs_review
reason=按 stock_basic 上市日期建立 clean 起点，并剔除已退市股票
```

#### 规则 3：缺失或冲突不能静默通过

如果出现：

1. 源分钟线行情日期早于 `effective_list_date`，但未被 clean 层过滤。
2. 同一个 `source_ts_code + trade_date` 匹配多个 latest code。
3. 同一 source code 的映射区间重叠。
4. 老股票缺少历史代码映射。
5. 某代码存在大量 all-zero 占位行，但没有任何有效行情。
6. `effective_delist_date` 不为空的股票仍进入 clean。

必须进入审计异常，不能直接计算 MACD。

### 5.5 CLI

新增：

```bash
lake-console build-stk-mins-security-identity-map --dry-run
lake-console build-stk-mins-security-identity-map --apply
lake-console audit-security-identity-map
```

`--dry-run` 输出：

1. identity 数量。
2. 代码变更合并数量。
3. 北交所 920 映射数量。
4. 需要人工确认的冲突数量。
5. 示例列表。

`--apply` 只在 dry-run 无 P0 冲突时写入 manifest。

### 5.6 跑数审计方案

M1 开发前必须先做一次只读审计。审计只读本地 Lake，不写任何文件，不访问远程数据库。

#### 5.6.1 审计目标

审计要回答：

1. 当前 Lake 中有哪些源代码存在疑似新旧代码关系。
2. 哪些关系可以由 `bse_mapping` 直接确认。
3. 哪些关系只能由 `namechange`、名称、上市/退市时间、分钟线首末日期综合推断。
4. 哪些源分钟线代码不在 `stock_basic` 中。
5. 哪些源分钟线日期早于 `stock_basic.list_date`，以及哪些源代码对应的最新股票已经退市。
6. 这些早于 `stock_basic.list_date` 的源行到底是有效行情，还是 OHLC 全 0 的无效占位。
7. 每个代码、每个 freq 是否存在有效行情缺失。
8. 哪些候选必须人工确认，不能自动进入 clean 层 identity 规则。

#### 5.6.2 输入事实

审计读取：

```text
manifest/security_universe/tushare_stock_basic.parquet
raw_tushare/stock_basic/current/*.parquet
raw_tushare/namechange/current/*.parquet
raw_tushare/bse_mapping/current/*.parquet
raw_tushare/stk_mins_by_date/freq=1/trade_date=*/*.parquet
```

首轮审计以 `freq=1` 为主，因为 1 分钟线覆盖最细，最容易暴露代码连续性问题。后续实现时要抽样复核其他 freq。

#### 5.6.3 审计步骤

步骤 1：读取本地股票池。

输出：

```text
stock_basic 总数
status 分布
list_date 缺失数
delist_date 非空数量
```

步骤 2：读取 `freq=1` 源分钟线实际代码清单，并做有效性判断。

输出：

```text
每个 ts_code 的 first_trade_date
每个 ts_code 的 first_valid_trade_date
每个 ts_code 的 last_trade_date
每个 ts_code 的 trade_date_count
每个 ts_code 的 invalid_before_valid_days
每个 ts_code 的 all_zero_day_count
```

步骤 3：找“分钟线存在，但 stock_basic 当前无此代码”的源代码。

这类代码通常是：

1. 历史旧代码。
2. 北交所映射旧代码。
3. 源数据异常。

步骤 4：用 `bse_mapping` 建立强确认候选。

例如：

```text
o_code -> n_code
```

如果旧代码或新代码出现在分钟线里，就生成候选关系。

步骤 5：用 `namechange` 建立普通代码变更候选。

`namechange` 不一定直接表达 `old_ts_code -> new_ts_code`，所以只能作为候选依据。需要结合：

1. 名称变化。
2. 新旧代码时间是否无重叠。
3. 旧代码 last_valid_trade_date 与新代码 first_valid_trade_date 是否相邻。
4. 是否存在相同或连续的公司名称。

步骤 6：做时间连续性判断。

对候选关系检查：

```text
old_last_valid_trade_date < new_first_valid_trade_date
gap_days 是否合理
是否存在交易日大断层
是否存在两个代码同一天都有分钟线
是否存在两个代码同一天都有有效行情
```

步骤 7：输出候选分级。

分级：

| 等级 | 含义 | 是否可自动进入 identity map |
|---|---|---|
| `confirmed` | `bse_mapping` 或清晰事实可确认 | 可以 |
| `high_confidence` | namechange + 时间连续 + 名称一致 | 可进入 dry-run，需展示 |
| `needs_review` | 有线索但不充分 | 不自动进入 |
| `rejected` | 时间重叠、事实冲突或源数据异常 | 不进入 |

#### 5.6.4 审计输出

首轮审计输出到终端即可，至少包含：

```text
stock_basic_count
minute_code_count
minute_code_missing_in_stock_basic_count
minute_code_first_seen_before_list_date_count
minute_code_first_valid_before_list_date_count
all_zero_before_list_date_count
bse_mapping_candidate_count
namechange_candidate_count
confirmed_candidate_count
needs_review_count
rejected_count
top_samples
```

若候选较多，再单独落 CSV/Markdown 报告；不在未确认前写入 manifest。

#### 5.6.5 2026-05-11 本地 Lake 初步审计结果

本轮已经对 `freq=1` 首次出现早于 `stock_basic.list_date` 的候选做了跨频率语义审计，报告位置：

```text
reports/stk_mins_effective_start_audit_2026-05-11/report.md
reports/stk_mins_effective_start_audit_2026-05-11/summary_by_code.csv
reports/stk_mins_effective_start_audit_2026-05-11/detail_by_code_freq.csv
```

审计结果：

| 项 | 数量 | 说明 |
|---|---:|---|
| 候选代码 | 237 | `freq=1` 首日早于 `stock_basic.list_date` |
| 上市日前存在非 0 有效行情的代码 | 192 | 按最新口径仍然不进入 clean 层 |
| 上市日前只有无效占位行的代码 | 45 | 典型如 OHLC 全 0 |
| `valid_before_list_date` 明细 | 1012 | code-freq 级别，表示上市日前存在有效行情 |
| `only_invalid_before_list_date` 明细 | 309 | code-freq 级别，表示上市日前只有无效行 |
| `missing_freq` 明细 | 5 | 个别退市股缺少某些频率 |

典型样本：

| ts_code | 现象 | clean 口径 |
|---|---|---|
| `601717.SH` | `2010-07-30` 有 1 分钟行，但 OHLC 为 0；`2010-08-03` 才是 list_date 与首个有效日 | `2010-07-30` 删除，只保留 `2010-08-03` 起 |
| `920003.BJ` | 上市日前多频率只有无效占位行 | 上市日前删除 |
| `920931.BJ` | 上市日前存在非 0 行 | 仍按 `stock_basic.list_date` 删除上市日前数据 |
| `300526.SZ` | 退市股，部分频率缺失 | clean 层整只剔除，不进入研究输入 |

本轮评审已确认：这些候选不再按“首次有效行情日”决定指标起点。未退市股票统一以 `stock_basic.list_date` 为 clean 起点；已退市股票整只剔除，不进入 clean。

---

## 6. M2：clean by_date 分钟线事实层

### 6.1 目标

生成 `research/stk_mins_by_date_clean_next`。

它是基于 raw 源站事实清洗后的分钟线事实层，不是指标结果，也不是专门为 MACD 临时拼出来的输入。它承担三件事：

1. 删除明显无效行情行。
2. 删除 `stock_basic.list_date` 前的数据。
3. 删除已退市股票的全部数据。
4. 把新旧股票代码直接归一到最新代码；源站原始代码只在 raw 和 `security_identity_map` 中追溯，不写入 clean 行。

后续所有研究口径都从这里往下游走：

```text
research/stk_mins_by_date_clean_next
-> derived 90/120 分钟线
-> research/stk_mins_by_symbol_month
-> MACD / 后续 MA / BOLL
```

### 6.2 输入

按 freq 读取：

```text
raw_tushare/stk_mins_by_date/freq=1|5|15|30|60/trade_date=*/part-*.parquet
manifest/security_identity/security_identity_map.parquet
manifest/security_universe/tushare_stock_basic.parquet
```

注意：M2 不读取旧的 `research/stk_mins_by_symbol_month`，也不读取旧 MACD 产物。

### 6.3 输出

新增：

```text
research/stk_mins_by_date_clean_next/
  freq=1/
    trade_date=2025-02-17/
      part-000.parquet
```

字段：

| 字段 | 类型 | 含义 |
|---|---|---|
| `ts_code` | string | 归一化后的最新代码，供研究和指标使用 |
| `freq` | int16 | 周期 |
| `trade_time` | timestamp | 分钟线时间 |
| `open` | double | 清洗后开盘价 |
| `close` | double | 清洗后收盘价，MACD 输入 |
| `high` | double | 清洗后最高价 |
| `low` | double | 清洗后最低价 |
| `vol` | int64 | 成交量 |
| `amount` | double | 成交额 |
| `trade_date` | date | `trade_time` 所属交易日 |

### 6.4 清洗规则

一行 raw 分钟线进入 clean 层必须同时满足：

1. 能通过 `security_identity_map` 匹配唯一 `latest_ts_code`。
2. `trade_time` 不为空。
3. `open/close/high/low` 均大于 0。
4. `high >= low`。
5. `vol >= 0` 且 `amount >= 0`。
6. `trade_date >= effective_list_date`。
7. `effective_delist_date` 必须为空；已退市股票整只不进入 clean。

其中第 6、7 条是本轮新确认的硬口径：

```text
上市日前数据一律不进入 clean 层。
退市股所有数据一律不进入 clean 层。
```

即使上市日前存在非 0 行，也视为源站历史口径污染，只保留在 raw 层，不进入研究事实层。

### 6.5 处理流程

```text
读取 raw by_date 源文件
-> 按 source_ts_code + trade_date 匹配 security_identity_map
-> 执行无效行情过滤
-> 执行 list_date 边界过滤
-> 剔除已退市股票
-> 写入 ts_code=最新代码
-> 按 ts_code + freq + trade_time 去重
-> 按 freq + trade_date 写 clean by_date 分区
```

### 6.6 去重与冲突规则

同一个 `ts_code + freq + trade_time` 如果出现多行：

1. 若行内容完全一致，可去重并计入 `duplicate_same_payload`。
2. 若行内容不一致，必须报错或进入审计异常，不能静默保留任意一行。
3. 不同源站代码映射到同一最新代码后，如果同一时间点行情内容不一致，说明源数据或映射规则存在冲突，必须停下来处理。

### 6.7 过滤原因统计

构建 clean 层时必须输出过滤统计：

| reason | 含义 |
|---|---|
| `invalid_price` | OHLC 非法或全 0 |
| `invalid_volume_amount` | 成交量/成交额非法 |
| `invalid_trade_time` | `trade_time` 为空或无法解析 |
| `before_list_date` | 早于 `stock_basic.list_date` |
| `delisted_security` | 已退市股票，整只不进入 clean |
| `identity_missing` | 找不到唯一身份映射 |
| `identity_conflict` | 匹配多个身份映射 |
| `duplicate_same_payload` | 完全重复行 |
| `duplicate_conflict_payload` | 同键不同内容 |

### 6.8 校验

每个 freq/date 生成后必须校验：

1. `clean_rows = raw_rows - filtered_rows + dedup_adjustment`。
2. 每行 clean 数据只匹配一个 `latest_ts_code`。
3. 同一 `ts_code + freq + trade_time` 不重复。
4. clean 层不存在早于 `security_identity_map.effective_list_date` 的行。
5. clean 层不存在 `security_identity_map.effective_delist_date` 非空的股票。
6. `300114.SZ -> 302132.SZ` 在 clean 层输出为 `302132.SZ`，不保留行级 `source_ts_code`。

### 6.9 CLI

新增：

```bash
lake-console bootstrap-stk-mins-by-date-clean \
  --dry-run \
  --freqs 1,5,15,30,60

lake-console bootstrap-stk-mins-by-date-clean \
  --apply \
  --freqs 1,5,15,30,60

lake-console audit-stk-mins-by-date-clean \
  --freqs 1,5,15,30,60 \
  --start-date 2009-01-01 \
  --end-date 2026-05-07

lake-console rebuild-stk-mins-by-date-clean-range \
  --dry-run \
  --freqs 1,5,15,30,60 \
  --start-date 2009-01-01 \
  --end-date 2026-05-07

lake-console rebuild-stk-mins-by-date-clean-range \
  --apply \
  --freqs 1,5,15,30,60 \
  --start-date 2009-01-01 \
  --end-date 2026-05-07
```

`audit` 只读当前 clean 层并输出违规统计；`rebuild-stk-mins-by-date-clean-range --dry-run` 只基于 raw 计算真正清洗后的保留/过滤统计，不写清洗结果。

`rebuild-stk-mins-by-date-clean-range --apply` 会真实替换 `research/stk_mins_by_date_clean_next` 对应分区。它只读取 raw，只写 clean，不修改 `raw_tushare/stk_mins_by_date`。每个分区写入都必须走：

```text
raw 分区
-> 生成 clean DataFrame
-> 写入 _tmp/{run_id}/research/stk_mins_by_date_clean_next/...
-> 校验 part-000.parquet 行数等于 kept_rows
-> 替换正式 clean 分区
```

如果遇到同一 `ts_code + freq + trade_time` 下内容不一致的重复冲突，命令必须停止，不允许静默保留任意一行。

`bootstrap` 是第一轮初始化动作：把 raw 当前事实完整复制到 clean 目录，建立一份可回退的 clean 初始副本。它不做清洗，不改 raw；如果 clean 分区已存在，默认拒绝覆盖，必须显式传 `--replace-existing`。

### 6.10 clean 完备性审计门禁

clean 重建完成后，不能只看过滤原因为空就进入 derived/research。  
`research/stk_mins_by_date_clean_next` 是后续 derived、research、MACD、MA、BOLL 的共同输入，所以它必须先通过单独的完备性审计门禁。

#### 6.10.1 目标

审计必须回答：

```text
clean schema 是否正确？
clean 是否只保留最新 ts_code？
raw 中应保留的数据是否都进入 clean？
clean 中是否还有非法价格、非法时间、重复 key？
每只股票在 clean 中的交易日覆盖和日内 bar 覆盖是否存在异常？
异常是确定失败，还是需要人工复核？
```

完备性审计的输出不能靠给 clean 行新增字段表达。所有 G6 暴露的问题必须进入独立审计账本，clean 行仍然只保留行情事实字段。

#### 6.10.2 输入

审计读取以下事实输入。默认审计不修改业务数据；当进入“记录问题账本”步骤时，只允许写入审计账本，不允许改 clean/derived/research：

```text
raw_tushare/stk_mins_by_date/freq=1|5|15|30|60/trade_date=*/*.parquet
research/stk_mins_by_date_clean_next/freq=1|5|15|30|60/trade_date=*/*.parquet
manifest/security_identity/security_identity_map.parquet
manifest/security_universe/tushare_stock_basic.parquet
manifest/trading_calendar/tushare_trade_cal.parquet
raw_tushare/suspend_d/trade_date=*/*.parquet
```

不得读取 derived、by_month research、MACD 结果来反推 clean 是否正确。

#### 6.10.2.1 G6 完备性审计账本

新增独立账本：

```text
manifest/stk_mins_quality/clean_completeness_issue_ledger.parquet
```

这个账本只记录 clean 完备性审计暴露的问题和处理依据，不属于分钟线事实层。它的作用是：

1. 记录 G6 发现的缺口、异常 bar、重复冲突、停牌解释、需要复核的问题。
2. 作为后续 clean 修复或剔除问题行的依据。
3. 保持 clean/derived/research/indicator 行级 schema 干净，不为了解释问题新增列。

建议字段：

| 字段 | 类型 | 含义 |
|---|---|---|
| `issue_id` | string | 稳定问题编号，建议由 `gate + ts_code + freq + trade_date + issue_type` 生成 |
| `gate` | string | 固定为 `G6`，或后续扩展为 `G5/G6/G7` |
| `issue_type` | string | `missing_trade_date` / `missing_bar` / `invalid_session_slot` / `duplicate_conflict_payload` / `missing_source_or_calendar_gap` 等 |
| `status` | string | `failed` / `needs_review` / `explained_by_suspend` / `explained_by_lifecycle` / `resolved` |
| `latest_ts_code` | string | clean 口径下的最新代码 |
| `freq` | int | 分钟频度 |
| `trade_date` | date | 问题所属交易日 |
| `trade_time` | timestamp/null | 行级问题的具体时间点；交易日缺口可为空 |
| `expected_value` | string/null | 期望值，例如应有 bar 数、应有交易日 |
| `actual_value` | string/null | 实际值，例如实际 bar 数、实际缺失日期 |
| `evidence_dataset` | string/null | 解释依据，例如 `suspend_d`、`trade_cal`、`raw_tushare.stk_mins` |
| `evidence_ref` | string/null | 证据定位，例如文件路径、分区、样本 key |
| `action` | string | `block` / `exclude_from_clean` / `accept_explained` / `repair_required` |
| `reason` | string | 人可读说明 |
| `created_at` | timestamp | 记录时间 |
| `resolved_at` | timestamp/null | 解决时间 |

硬规则：

1. G6 审计发现的问题默认不能直接修改 clean。
2. 只有问题先写入该账本，并且 `action=exclude_from_clean` 或 `action=repair_required` 等处理动作明确后，后续 clean 修复或重建才允许剔除对应问题行。
3. `explained_by_suspend` 和 `explained_by_lifecycle` 也要计入账本，用于证明“为什么这里没有数据不是错误”。
4. 该账本不得反向污染 clean 行级 schema；clean 中不允许出现 `issue_id`、`issue_type`、`status`、`evidence_ref` 等字段。

#### 6.10.3 审计层级

##### 审计结果枚举

审计项必须使用固定枚举，不允许只输出自然语言。

| 枚举 | 含义 | 是否阻塞下游 |
|---|---|---|
| `pass` | 明确通过 | 不阻塞 |
| `failed` | 确认错误，必须修复 | 阻塞 |
| `needs_review` | 有异常信号，现有规则不能自动判定 | 阻塞，除非后续形成明确豁免 |
| `duplicate_same_payload` | 同 key 完全重复，内容一致，可去重 | 不阻塞，但必须计数 |
| `duplicate_conflict_payload` | 同 key 内容不一致 | 阻塞，等同 `failed` |
| `explained_by_suspend` | 缺失可由 `suspend_d` 停牌记录解释 | 不阻塞，但必须计数 |
| `explained_by_lifecycle` | 缺失发生在未退市股票上市前，或对应股票已退市且应被整只排除 | 不阻塞 |
| `missing_source_or_calendar_gap` | raw、交易日历或停复牌数据不足，无法判断 | 阻塞，归入 `needs_review` |

全局汇总状态由审计项汇总得到：

```text
如果任意项 failed 或 duplicate_conflict_payload -> failed
否则如果任意项 needs_review 或 missing_source_or_calendar_gap -> needs_review
否则 -> success
```

##### A. schema 门禁

clean 分区字段必须严格等于：

```text
ts_code
freq
trade_time
open
close
high
low
vol
amount
trade_date
```

以下字段一旦出现在 clean/derived/research 行级数据中，审计失败：

```text
identity_id
source_ts_code
list_date
delist_date
identity_version
```

原因：这些是映射和审计信息，不是 clean 事实行字段。

##### B. 分区覆盖门禁

以 raw 分区为基准：

```text
raw_tushare/stk_mins_by_date/freq=X/trade_date=YYYY-MM-DD
```

如果该 raw 分区经过 clean 规则后 `kept_rows > 0`，则必须存在对应 clean 分区：

```text
research/stk_mins_by_date_clean_next/freq=X/trade_date=YYYY-MM-DD
```

并且：

```text
clean_row_count == kept_rows
```

如果 raw 分区不存在，审计不能凭空要求 clean 分区存在；该问题应进入“源数据覆盖审计”，不能在 clean 门禁里伪造预期。

##### C. 行级质量门禁

每个 clean 分区必须满足：

```text
ts_code 非空
freq 与路径一致
trade_time 可解析
trade_time.date == trade_date
open/close/high/low > 0
high >= low
vol >= 0
amount >= 0
ts_code + freq + trade_time 唯一
```

任何违反都是 `failed`。

##### D. raw -> clean 归一门禁

审计按分区重新执行 raw -> clean 的只读规则，得到 expected clean 统计：

```text
source_ts_code -> latest_ts_code
invalid_price 过滤
invalid_volume_amount 过滤
invalid_trade_time 过滤
before_list_date 过滤
delisted_security 过滤
duplicate_same_payload 去重
duplicate_conflict_payload 失败
```

然后比对：

```text
expected_rows == actual_clean_rows
expected_ts_code_set == actual_clean_ts_code_set
```

如果 raw 中某行应进入 clean，但 clean 中缺失，`failed`。  
如果 clean 中存在 raw 规则无法解释的额外行，`failed`。

##### E. 股票级交易日连续性审计

这一步不是简单要求“所有股票每天必须有分钟线”。  
原因：停牌、临停、源站历史缺失都会导致某些未退市股票在某些开市日没有分钟线；已退市股票已经在 clean 层整只排除，不再进入连续性审计对象。

审计对象只包含 clean 层中出现的未退市股票。审计按 `ts_code + freq` 统计 clean 中实际出现的交易日序列：

```text
first_clean_trade_date
last_clean_trade_date
actual_trade_dates
```

再用本地交易日历得到该股票在审计窗口内理论上应该覆盖的交易日：

```text
open_trade_dates_between(max(stock_basic.list_date, audit_start_date), audit_end_date)
```

如果某个开市日在 clean 中缺失：

1. raw 中该股票该 freq 该日有应保留数据，但 clean 缺失：`failed`。
2. raw 中该股票该 freq 该日完全没有数据，且 `raw_tushare/suspend_d` 中存在该股票该交易日 `suspend_type='S'` 停牌记录：`explained_by_suspend`。
3. raw 中该股票该 freq 该日完全没有数据，但 `suspend_d` 没有停牌记录：`needs_review`，记录为 `missing_source_or_calendar_gap`。
4. 缺失日期发生在该股票 `stock_basic.list_date` 之前：`explained_by_lifecycle`。
5. 未退市股票在 `max(stock_basic.list_date, audit_start_date) ~ audit_end_date` 内的缺失日期，必须由 raw 缺失、停牌记录或明确审计异常解释，不能因为 clean 当前末日较早就自动放过。

这样可以用已有停复牌数据集解释真实停牌，不需要人工拍脑袋；同时也不会把中间缺口悄悄放过去。

停复牌数据依赖：

```text
dataset_key=suspend_d
路径=raw_tushare/suspend_d/trade_date=YYYY-MM-DD/*.parquet
关键字段=ts_code, trade_date, suspend_type, suspend_timing
停牌判断=suspend_type == 'S'
```

如果审计区间内缺少对应日期的 `suspend_d` 分区，且 clean 又出现疑似缺失，则不能自动解释为停牌，必须输出 `missing_source_or_calendar_gap`。

##### F. 日内 bar 完整性审计

按 `ts_code + freq + trade_date` 统计：

```text
bar_count
first_trade_time
last_trade_time
missing_session_slots
```

第一版先使用 A 股常规分钟线时段规则：

```text
上午：09:30 ~ 11:30
下午：13:00 ~ 15:00
```

各 freq 的参考 bar 数：

| freq | 常规日参考 bar 数 | 说明 |
|---|---:|---|
| 1 | 241 | 含 09:30 |
| 5 | 49 | 含 09:30 |
| 15 | 17 | 含 09:30 |
| 30 | 9 | 含 09:30 |
| 60 | 5 | 含 09:30 |

审计规则：

1. `bar_count == reference_count`：通过。
2. `bar_count == 0`：不应出现在 clean 分区内；若存在则 `failed`。
3. `0 < bar_count < reference_count`：`needs_review`，记录缺失时段。
4. `bar_count > reference_count`：`failed`，通常表示重复或异常时间点。

注意：如果后续确认某些交易日有半日市、特殊交易时段或源站特例，需要先把交易时段日历模型补进 manifest，再调整本审计规则，不能在代码里硬写临时例外。

#### 6.10.4 输出状态

审计输出全局状态：

```text
success
failed
needs_review
```

含义：

| 状态 | 含义 | 是否允许进入 derived/research |
|---|---|---|
| `success` | schema、raw->clean、行级质量、连续性均无异常 | 允许 |
| `failed` | 确认存在数据错误或 clean 与 raw 规则不一致 | 不允许 |
| `needs_review` | 可能是停牌/源站缺失/特殊交易日，必须人工确认 | 默认不允许，除非生成审计豁免清单 |

第一版不设计自动豁免。遇到 `needs_review`，先输出报告，由人工决定是否补数据、接受缺口，还是扩展审计规则。

注意：如果缺失已经被 `suspend_d` 明确解释，审计项状态是 `explained_by_suspend`，它不会把全局状态推到 `needs_review`。只有缺少停复牌依据、raw 缺失或交易日历缺失时，才进入 `needs_review`。

#### 6.10.5 报告内容

审计报告至少包含：

```text
summary.json
schema_violations.csv
partition_count_mismatch.csv
row_count_mismatch.csv
duplicate_keys.csv
invalid_rows.csv
missing_trade_dates.csv
intraday_bar_gaps.csv
suspend_explained_gaps.csv
needs_review_samples.csv
issue_ledger_preview.csv
```

报告目录：

```text
reports/stk_mins_clean_completeness_audit/<run_id>/
```

报告必须记录：

```text
lake_root
freqs
start_date
end_date
raw_partitions
clean_partitions
raw_rows
expected_clean_rows
actual_clean_rows
failed_count
needs_review_count
sample_limit
issue_ledger_new_records
```

#### 6.10.6 CLI

新增：

```bash
lake-console audit-stk-mins-clean-completeness \
  --freqs 1,5,15,30,60 \
  --start-date 2009-01-01 \
  --end-date 2026-05-07 \
  --sample-limit 20
```

默认只读审计，不写 clean，不写 derived，不写 research。  
若后续实现 `--write-ledger` 或独立 `record-stk-mins-clean-audit-ledger` 命令，也只能写 `manifest/stk_mins_quality/clean_completeness_issue_ledger.parquet`，不能修改分钟线事实层。

如果输出 `failed` 或 `needs_review`，后续命令必须停止：

```text
rebuild-stk-mins-derived-from-clean-range
rebuild-stk-mins-research-from-clean-range
compute-stk-mins-indicator-range
```

#### 6.10.7 进入 M3 的门禁

进入 M3 前必须满足：

1. clean schema 正确。
2. clean 不包含行级 `identity_id/source_ts_code/list_date/delist_date/identity_version`。
3. raw -> clean expected rows 与 actual clean rows 一致。
4. clean 无非法价格、非法时间、重复 key。
5. 股票级交易日连续性没有 `failed`。
6. 日内 bar 完整性没有 `failed`。
7. `needs_review` 为 0；或者已形成单独人工确认报告，并在方案文档中明确记录为什么可接受。

在这些条件满足前，不允许重建 derived/research。

2026-05-11 至 2026-05-12 执行状态：

1. 已完成 `bootstrap-stk-mins-by-date-clean --apply --freqs 1,5,15,30,60`，将 raw 完整初始化到 clean：`21045` 个分区、`21637` 个文件、`4576237808` 行。
2. 已完成 `build-stk-mins-security-identity-map --apply --sample-limit 5`，生成 `6089` 条 source code 映射、`5837` 个 identity。
3. 样本审计显示 clean 初始副本并未通过最终审计：`2010-07-30 freq=1` 存在 `invalid_price=241`，因此必须先完成 clean rebuild，再进入 derived/research/MACD。
4. 已完成全量 `rebuild-stk-mins-by-date-clean-range --dry-run --freqs 1,5,15,30,60 --start-date 2009-01-01 --end-date 2026-05-07`，该命令只读 raw 并计算清洗计划，没有写入 clean。
5. 全量 dry-run 结果：
   - raw 行数：`4576237808`
   - 计划保留行数：`4561827979`
   - 计划过滤行数：`14409829`
   - `before_list_date`：`9262364`
   - `invalid_price`：`5147163`
   - `invalid_volume_amount`：`302`
   - `duplicate_reasons`：空，当前没有发现同一清洗主键下的重复冲突。
6. 已完成小窗口 apply 验证：
   - 命令：`rebuild-stk-mins-by-date-clean-range --apply --freqs 1 --start-date 2010-07-30 --end-date 2010-07-30`
   - 结果：raw `455972` 行，clean 写入 `455731` 行，过滤 `invalid_price=241`。
   - 复核：`audit-stk-mins-by-date-clean --freqs 1 --start-date 2010-07-30 --end-date 2010-07-30` 返回 `status=success`，过滤原因为空。
7. 已完成全量受控 clean rebuild apply：
   - 命令：`rebuild-stk-mins-by-date-clean-range --apply --freqs 1,5,15,30,60 --start-date 2009-01-01 --end-date 2026-05-07`
   - `run_id`：`20260511T171742Z-rebuild-stk-mins-clean`
   - 分区数：`21045`
   - raw 行数：`4576237808`
   - clean 写入行数：`4561827979`
   - 过滤行数：`14409829`
   - `before_list_date`：`9262364`
   - `invalid_price`：`5147163`
   - `invalid_volume_amount`：`302`
   - `duplicate_reasons`：空，当前没有发现同一清洗主键下的重复冲突。
   - 耗时：约 `5793.856` 秒。
8. 2026-05-12 口径修正：前述全量 clean rebuild 产物包含行级 `identity_id/source_ts_code/list_date/delist_date/identity_version`，与最新评审口径不一致，已按历史事故处理，不得作为 M3 输入。
9. 2026-05-13 最新结论：正式 `research/stk_mins_by_date_clean_next` 已按最新 schema 重建完成，物理列为 `ts_code,freq,trade_time,open,close,high,low,vol,amount,exchange,vwap`，不包含 `trade_date/identity_id/source_ts_code`。
10. `clean_next` 已通过基础审计与完备性审计：
   - 分区数：`21045`。
   - 频率：`1/5/15/30/60`。
   - 完备性问题账本：`0` 行。
   - 已完成专项：`2024-10-30` 多频率混入 `1min`、`2022` 北交所 `30min bar_count=6`。
11. 最新门禁结论：M3 必须从 `clean_next` 继续；不得读取已删除的 `research/stk_mins_by_date_clean`，不得绕过 clean 直接以 raw 作为研究输入。

---

## 7. M3：基于 clean 层生成 derived 与 by_month research

### 8.1 目标

让下游研究输入全部基于 clean 层，而不是 raw 层。

本阶段包含两个输出：

1. `derived/stk_mins_by_date` 的 `90/120` 分钟线。
2. `research/stk_mins_by_symbol_month` 的全频率按月重排。

### 7.2 derived 90/120 输入输出

输入：

```text
research/stk_mins_by_date_clean_next/freq=30/trade_date=*/*.parquet
research/stk_mins_by_date_clean_next/freq=60/trade_date=*/*.parquet
```

输出：

```text
derived/stk_mins_by_date/freq=90/trade_date=*/*.parquet
derived/stk_mins_by_date/freq=120/trade_date=*/*.parquet
```

derived 输出沿用 clean 层最新代码口径：

```text
ts_code = 最新代码
```

### 7.3 by_month research 输入输出

输入：

```text
research/stk_mins_by_date_clean_next/freq=1|5|15|30|60/trade_date=*/*.parquet
derived/stk_mins_by_date/freq=90|120/trade_date=*/*.parquet
```

输出：

```text
research/stk_mins_by_symbol_month/
  freq=1/
    trade_month=2025-02/
      bucket=07/
        part-000.parquet
```

### 7.4 bucket 规则

bucket 必须基于 clean 后 `ts_code` 稳定 hash，不得基于源站原始代码。

原因：

```text
如果 300114.SZ 和 302132.SZ 按源站原始代码 hash，可能落入不同 bucket。
MACD worker 就读不到完整连续序列。
```

### 7.5 校验

1. by_month 行数必须等于对应 clean/derived 输入行数。
2. 同一 `ts_code + freq + trade_time` 不重复。
3. `300114/302132` 在 by_month 层统一输出为最新代码 `302132.SZ`，可按一个 `ts_code` 连续读取。
4. by_month 不得包含早于 list_date 的数据，也不得包含任何已退市股票的数据。
5. derived 90/120 不得读取 raw 30/60，只能读取 `clean_next` 30/60。
6. derived/research 不得包含行级 `identity_id/source_ts_code/list_date/delist_date/identity_version`。

### 7.6 CLI

新增或调整：

```bash
lake-console rebuild-stk-mins-derived-from-clean-range \
  --target-freqs 90,120 \
  --start-date 2009-01-01 \
  --end-date 2026-05-07

lake-console rebuild-stk-mins-research-from-clean-range \
  --freqs 1,5,15,30,60,90,120 \
  --start-month 2009-01 \
  --end-month 2026-05
```

---

## 8. M4：旧 MACD 产物废弃与清理

### 7.1 目标

旧 MACD 结果不再作为可信事实。

在正式重算前，必须明确清理范围，避免新旧结果混用。

### 8.2 待清理对象

清理前必须 dry-run：

```text
derived/stk_mins_indicators_by_date/indicator=macd/params_key=12_26_9/
research/stk_mins_indicators_by_symbol_month/indicator=macd/params_key=12_26_9/
manifest/indicator_state/stk_mins_macd/params_key=12_26_9/
manifest/indicator_recalc_queue/stk_mins_macd.parquet
```

### 8.3 清理前审计

输出：

1. by_date 分区数量、日期范围、行数。
2. research 分区数量、月份范围、行数。
3. state 行数、freq 分布、最大水位。
4. recalc queue pending 数。
5. 是否存在 `_tmp` 残留。

### 8.4 CLI

新增：

```bash
lake-console audit-stk-mins-macd-assets
lake-console cleanup-stk-mins-macd-assets --dry-run
lake-console cleanup-stk-mins-macd-assets --apply
```

`--apply` 必须二次确认参数：

```bash
--confirm-delete-macd-v1
```

---

## 9. M5：全量准确重算

### 9.1 目标

使用 clean by_month research 作为唯一输入，全量重算 `1/5/15/30/60/90/120` 的 MACD。

### 9.2 输入

只允许读取：

```text
research/stk_mins_by_symbol_month/freq=*/trade_month=*/bucket=*/*.parquet
```

不再允许 full 计算直接读取：

```text
raw_tushare/stk_mins_by_date
research/stk_mins_by_date_clean_next
```

原因：

1. raw/by_date IO 太散。
2. clean by_month research 已经完成身份统一和排序前置校验。
3. 直接读 by_date 会导致 IO 过散，且容易绕过 clean 层边界。

### 9.3 输出

by_date：

```text
derived/stk_mins_indicators_by_date/
  indicator=macd/
    params_key=12_26_9/
      freq=1/
        trade_date=2025-02-17/
          part-000.parquet
```

research：

```text
research/stk_mins_indicators_by_symbol_month/
  indicator=macd/
    params_key=12_26_9/
      freq=1/
        trade_month=2025-02/
          bucket=07/
            part-000.parquet
```

state：

```text
manifest/indicator_state/stk_mins_macd/
  params_key=12_26_9/
    state.parquet
```

### 9.4 输出字段

MACD by_date / research：

| 字段 | 类型 | 含义 |
|---|---|---|
| `ts_code` | string | 输出代码，等于 clean 层最新代码 |
| `freq` | int16 | 周期 |
| `trade_time` | timestamp | 指标时间 |
| `dif` | double | 快慢 EMA 差 |
| `dea` | double | DIF EMA |
| `macd_bar` | double | `2 * (dif - dea)` |
| `params_key` | string | `12_26_9` |
| `indicator_version` | int16 | 算法版本 |

state：

| 字段 | 类型 | 含义 |
|---|---|---|
| `ts_code` | string | clean 层输出代码 |
| `freq` | int16 | 周期 |
| `last_trade_time` | timestamp | 该证券该周期最新 state 时间 |
| `ema_fast` | double | 快 EMA |
| `ema_slow` | double | 慢 EMA |
| `dea` | double | DEA |
| `source_layer` | string | 固定 `clean_research` |
| `source_watermark` | timestamp | 输入源最大时间 |
| `state_version` | int16 | state schema 版本 |
| `updated_at` | timestamp | 更新时间 |

### 9.5 单证券计算规则

对每个 `ts_code + freq`：

```text
读取完整时间序列
按 trade_time 升序
第一条初始化 EMA
逐条递推
写出全部 MACD 行
写最终 state
```

禁止：

1. 每月重新初始化 EMA。
2. 每天重新初始化 EMA。
3. 新代码出现时重新初始化 EMA。
4. 缺历史输入时静默跳过。

---

## 10. M6：并行性能设计

### 10.1 并行单位

并行单位：

```text
freq + bucket
```

例子：

```text
freq=1 bucket=00
freq=1 bucket=01
freq=5 bucket=00
...
```

不能按日期并行。

原因：

```text
MACD 今天依赖昨天，昨天依赖前天。
按日期切开会导致 EMA state 断链。
```

### 10.2 Worker 内部流程

每个 worker：

```text
读取该 freq + bucket 的全部月份
-> 按 ts_code 分组
-> 每个 ts_code 内按 trade_time 排序
-> 顺序计算 MACD
-> 按月份 checkpoint 写 by_date 临时结果
-> 生成该 worker 的 state shard
```

### 10.3 主进程流程

主进程：

```text
生成任务计划
-> 启动 ProcessPool
-> 监控 worker 进度
-> 收集 worker 输出
-> 合并 by_date 分区
-> 合并 state shard
-> 重建 indicator research
-> 跑完备性审计
```

### 10.4 为什么用多进程，不用普通线程

MACD 计算本身是 CPU + Python 循环混合任务。

普通线程会受 GIL 影响，收益有限。

多进程能让多个 bucket 并行使用多核 CPU。

### 10.5 并发配置

新增配置：

```text
LAKE_INDICATOR_WORKER_COUNT=4
LAKE_INDICATOR_MAX_BUCKETS_IN_FLIGHT=4
LAKE_INDICATOR_BATCH_MONTHS=1
```

含义：

| 配置 | 含义 |
|---|---|
| `LAKE_INDICATOR_WORKER_COUNT` | 同时运行的 worker 数 |
| `LAKE_INDICATOR_MAX_BUCKETS_IN_FLIGHT` | 同时处理的 bucket 数上限 |
| `LAKE_INDICATOR_BATCH_MONTHS` | worker 内部 checkpoint 月份跨度，默认 1 |

默认不应把 worker 数设太高。移动硬盘 IO、DuckDB/Parquet 读取、CPU 都可能成为瓶颈。

### 10.6 进度输出

必须输出：

```text
[macd_v2] plan freqs=1,5,15,30,60,90,120 buckets=32 workers=4
[macd_v2] worker_start freq=1 bucket=07 symbols=173 months=209
[macd_v2] worker_progress freq=1 bucket=07 symbol=302132.SZ month=2025-02 rows=...
[macd_v2] worker_checkpoint freq=1 bucket=07 month=2025-02 written=...
[macd_v2] worker_done freq=1 bucket=07 symbols=173 rows=...
[macd_v2] merge_state freq=1 state_rows=...
[macd_v2] audit_done status=success
```

不能长时间无输出。

### 10.7 失败处理

任何 worker 失败：

1. 主进程停止调度新任务。
2. 保留已完成 worker 的临时结果。
3. 不推进最终 state。
4. 不标记整批成功。
5. 输出失败的 `freq/bucket/ts_code/month`。

正式 resume 后续单独设计；第一版可以重新运行失败批次，但不能静默混入半成品。

---

## 11. M7：完备性审计

### 11.1 目标

重算后必须能回答：

```text
源 clean 输入有多少行？
MACD by_date 有多少行？
MACD research 有多少行？
state 水位到哪里？
哪些 freq / 日期 / 股票缺结果？
```

### 11.2 CLI

新增：

```bash
lake-console audit-stk-mins-macd-completeness \
  --freqs 1,5,15,30,60,90,120 \
  --start-date 2009-01-01 \
  --end-date 2026-05-07
```

### 11.3 审计项

| 项 | 规则 |
|---|---|
| source vs by_date 行数 | 同一 freq/date 下，clean source 行数必须等于 MACD 行数 |
| by_date vs research 行数 | 同一 freq/month 下，by_date 行数必须等于 research 行数 |
| state 覆盖 | 每个有源数据的 `ts_code + freq` 必须有 state |
| state 水位 | state 最大时间必须等于该证券该 freq 源数据最大 `trade_time` |
| 旧代码断裂 | clean 后同一真实股票必须统一为最新 `ts_code`，不能再出现旧代码断裂 |
| 重复输出 | `ts_code + freq + trade_time` 不得重复 |
| 缺失日期 | 有源数据的 trade_date 必须有对应 MACD 分区 |

### 11.4 审计结果

输出状态：

```text
success
failed
needs_review
```

`failed` 示例：

```text
freq=1 trade_date=2025-02-17 source_rows=1070000 macd_rows=1069759 missing=241
```

`needs_review` 示例：

```text
source_ts_code=xxx 映射到多个 latest_ts_code，需要人工确认
```

---

## 12. M8：增量可靠更新

### 12.1 进入前置条件

只有满足以下条件，才允许开发和启用增量：

1. security identity map 已生成并审计通过。
2. clean by_date、derived、clean by_month research 已覆盖全量源数据。
3. MACD full 重算已通过完备性审计。
4. state 水位与 source watermark 一致。
5. 旧 queue 已清空或废弃。

### 12.2 增量输入

增量仍然读取 clean by_month research，不直接读取 raw by_date。

当源数据新增或被重写后：

```text
raw 分区变化
-> clean by_date 对应日期重建
-> derived 90/120 对应日期重建
-> clean by_month research 对应月份重建
-> indicator queue 记录受影响 identity/freq/month
-> MACD incremental 从受影响月份前的 state 开始
```

### 12.3 state 失效规则

以下情况必须让旧 state 失效：

1. identity map 版本变化。
2. 某个 identity 历史源数据被补齐或替换。
3. clean by_date、derived 或 clean by_month research 某个分区被替换。
4. MACD 参数变化。
5. MACD 算法版本变化。

### 12.4 增量不能做的事

1. 老股票缺 state 时不能从窗口中途初始化。
2. 代码变更后不能创建新独立 state。
3. source watermark 早于 state watermark 时不能继续。
4. identity map 有冲突时不能继续。

---

## 13. CLI 总览

### 13.1 身份模型

```bash
lake-console build-stk-mins-security-identity-map --dry-run
lake-console build-stk-mins-security-identity-map --apply
lake-console audit-security-identity-map
```

### 13.2 clean 输入与 research 重排

```bash
lake-console bootstrap-stk-mins-by-date-clean \
  --dry-run \
  --freqs 1,5,15,30,60

lake-console bootstrap-stk-mins-by-date-clean \
  --apply \
  --freqs 1,5,15,30,60

lake-console audit-stk-mins-by-date-clean \
  --freqs 1,5,15,30,60 \
  --start-date 2009-01-01 \
  --end-date 2026-05-07

lake-console rebuild-stk-mins-by-date-clean-range \
  --dry-run \
  --freqs 1,5,15,30,60 \
  --start-date 2009-01-01 \
  --end-date 2026-05-07

lake-console rebuild-stk-mins-derived-from-clean-range \
  --target-freqs 90,120 \
  --start-date 2009-01-01 \
  --end-date 2026-05-07

lake-console rebuild-stk-mins-research-from-clean-range \
  --freqs 1,5,15,30,60,90,120 \
  --start-month 2009-01 \
  --end-month 2026-05
```

### 13.3 清理旧 MACD

```bash
lake-console audit-stk-mins-macd-assets
lake-console cleanup-stk-mins-macd-assets --dry-run
lake-console cleanup-stk-mins-macd-assets --apply --confirm-delete-macd-v1
```

### 13.4 全量重算

```bash
lake-console compute-stk-mins-indicator-v2 \
  --indicator macd \
  --mode full \
  --all-market \
  --freqs 1,5,15,30,60,90,120 \
  --start-date 2009-01-01 \
  --end-date 2026-05-07 \
  --workers 4
```

### 13.5 完备性审计

```bash
lake-console audit-stk-mins-macd-completeness \
  --freqs 1,5,15,30,60,90,120 \
  --start-date 2009-01-01 \
  --end-date 2026-05-07
```

### 13.6 增量

```bash
lake-console compute-stk-mins-indicator-v2 \
  --indicator macd \
  --mode incremental \
  --all-market \
  --freqs 1,5,15,30,60,90,120 \
  --start-date 2026-05-08 \
  --end-date 2026-05-08
```

增量入口只有在 M8 完成后才能开放。

---

## 14. 开发里程碑

### M1：证券连续身份模型

目标：

1. 生成 `security_identity_map`。
2. 能识别代码变更、北交所 920、上市/退市时间。
3. 冲突必须可审计。

验收：

1. `300114.SZ -> 302132.SZ` 映射为同一最新代码。
2. `920xxx.BJ` 有合理 `source_first_seen_date`、`source_first_valid_trade_date`，但 clean 起点仍以 `stock_basic.list_date` 为准。
3. 无区间重叠。
4. 无一行源分钟线匹配多个最新代码。

### M2：clean by_date 分钟线事实层

目标：

1. 生成 `research/stk_mins_by_date_clean_next`。
2. 删除无效行、未退市股票上市日前数据，并整只排除已退市股票数据。
3. 所有代码变更后的序列按最新代码连续。

验收：

1. `clean_rows = raw_rows - filtered_rows + dedup_adjustment`。
2. `300114/302132` 在 clean 层输出为最新代码，不保留行级 `source_ts_code`。
3. `ts_code + freq + trade_time` 无重复。
4. clean 层没有早于 list_date 的行，也没有任何已退市股票的行。

### M3：基于 clean 层生成 derived 与 by_month

目标：

1. `derived 90/120` 只读 clean 30/60。
2. `research/stk_mins_by_symbol_month` 只读 clean/derived。

验收：

1. by_month 行数与 clean/derived 输入行数一致。
2. `300114/302132` 在 by_month 层连续。
3. derived 和 by_month 均不含 list_date 前数据，也不含任何已退市股票数据。

### M4：旧 MACD 产物清理

目标：

1. 只清理 MACD v1 产物。
2. 不碰 raw、clean、derived/source 分钟线。

验收：

1. dry-run 清单完整。
2. apply 后旧 by_date、research、state、queue 不再混入新结果。

### M5：准确全量重算

目标：

1. full 只读 clean by_month research。
2. 生成完整 by_date、research、state。

验收：

1. 所有 freq 都有输出。
2. 所有 source 行都有对应 MACD 行。
3. state 水位到源数据最大时间。

### M6：并行计算

目标：

1. 按 `freq + bucket` 并行。
2. worker 内证券时间序列保持连续。
3. 长任务持续输出进度。

验收：

1. 同一输入下，单进程和多进程结果一致。
2. workers=1 与 workers=4 的 row count、sample checksum 一致。
3. 异常 worker 不推进最终 state。

### M7：完备性审计

目标：

1. 一条命令检查 MACD 是否完整。
2. 输出缺失日期、缺失 freq、缺失股票、state 水位。

验收：

1. 审计能发现当前旧 MACD 不完整。
2. 重算后审计通过。
3. 审计结果可直接指导下一步修复。

### M8：增量可靠更新

目标：

1. 每日新增分钟线后可增量刷新 MACD。
2. 源数据重写后能识别并拒绝错误增量。

验收：

1. 正常新增一天数据，增量结果等于 full 到当天的结果。
2. 历史源分区重写后，旧 state 被判定失效。
3. identity map 变化后，旧 state 被判定失效。

---

## 15. 测试门禁

### 15.1 单元测试

必须覆盖：

1. MACD 公式。
2. identity map 生成。
3. 代码变更连续性。
4. 北交所 920 起算日期。
5. clean by_date 与 by_month research 行数一致。
6. state 推进。
7. state 失效。
8. 并行结果一致性。

### 15.2 集成测试

最小 fixture：

```text
A 股票：无代码变更
B 股票：old_code -> new_code
C 股票：920 新代码
D 股票：中途补历史数据
```

验证：

1. full 结果准确。
2. incremental 结果与 full 对齐。
3. 并行结果与单进程对齐。
4. 旧 state 失效时拒绝继续。

### 15.3 真实 Lake 验证

只读或小范围：

1. `300114.SZ -> 302132.SZ`。
2. 若干 `920xxx.BJ`。
3. `freq=30 / 2026-04` 与当前已存在结果抽样对比。

---

## 16. 风险与防护

| 风险 | 防护 |
|---|---|
| 代码变更识别错 | identity map dry-run + conflict 审计 |
| 并行破坏递推 | 只按 `freq + bucket` 并行，不按日期并行 |
| 旧结果混入新结果 | M4 清理旧 MACD 产物 |
| state 被错误推进 | 结果写入成功后才写 state；失败不推进 |
| 源数据补齐后指标未重算 | source watermark + queue + completeness audit |
| worker 失败留下半成品 | 临时目录隔离，最终 merge 前不生效 |
| 性能提升但结果不一致 | workers=1 vs workers=N checksum 门禁 |
| clean 层错误过滤有效数据 | M2 必须输出过滤原因与样本，先 audit 再 rebuild |

---

## 17. 评审待确认

已确认：

1. `300114.SZ -> 302132.SZ` 输出统一使用最新代码。
2. `raw_tushare/stk_mins_by_date` 不修改；新增 `research/stk_mins_by_date_clean_next` 做清洗。
3. clean 层按 `stock_basic.list_date` 与退市状态过滤：未退市股票保留 list_date 起的数据，已退市股票整只不进入 clean。
4. 旧 MACD 产物允许按 M4 的 audit/dry-run/apply 流程清理。
5. 第一版并行 worker 默认值设为 `4`，上限先设为 `8`。

待实现前进一步确认：

1. `security_identity_map` 中 `namechange + bse_mapping + stock_basic` 的冲突优先级。
2. clean 层 `duplicate_conflict_payload` 是直接失败，还是落审计报告后跳过。
3. MACD v2 CLI 是否使用新命令 `compute-stk-mins-indicator-v2`，还是替换现有命令实现。

---

## 18. 建议执行顺序

建议严格按以下顺序推进，不跳步：

```text
M1 identity
-> M2 clean by_date
-> M3 derived/research from clean
-> M4 cleanup old macd
-> M5 full recompute single worker
-> M6 parallel compute
-> M7 completeness audit
-> M8 incremental
```

如果 M1 或 M2 发现身份冲突，不进入 M3。  
如果 M5 单 worker 结果无法审计通过，不进入 M6。  
如果 M7 审计未通过，不进入 M8。
