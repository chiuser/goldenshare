# Dagster 90m/120m 分钟线合同修复与历史重建低层设计

更新时间：2026-08-08

状态：P0-P7 已完成；P8 Day-0 启动与即时消费验收已完成。连续至少 3 个实际交易日观察、UI latest 事件顺序处理，以及受影响 120m 研究/回测重跑尚未完成，因此本专项仍处于 P8 观察和收口阶段。

关联文档：

- [股票分钟线 QFQ 检查治理 LLD](./dagster-stk-mins-qfq-validation-governance-low-level-design.md)
- [股票分钟线 QFQ MACD/KDJ 方案](./dagster-stk-mins-qfq-macd-kdj-indicators-plan.md)
- [普通指数分钟线方案](./dagster-index-mins-data-onboarding-plan.md)
- [普通指数分钟线 LLD](./dagster-index-mins-data-onboarding-low-level-design.md)
- [主要指数分钟线方案](./dagster-major-index-mins-data-onboarding-plan.md)
- [主要指数分钟线 LLD](./dagster-major-index-mins-data-onboarding-low-level-design.md)
- [Dagster 数据管道性能规范](./dagster-data-pipeline-performance-governance.md)
- [Asset Schema 合同](./dagster-asset-schema-contract-design.md)

## 1. 目标与非目标

### 1.1 目标

统一修复以下三套正式资产的 90m/120m 派生合同：

1. 股票前复权分钟线：`gold_stk_mins_qfq_90m/120m`。
2. 普通指数分钟线：`silver_index_mins_90m/120m`。
3. 主要指数分钟线：`silver_major_index_mins_90m/120m`。

股票 90m/120m QFQ 改变后，还要从历史基线顺序重建：

```text
gold_stk_mins_qfq_macd_kdj_90m/120m
gold_stk_mins_qfq_macd_kdj_state_90m/120m
```

修复完成后，日常 asset、历史 bootstrap、factor repair、check/readiness 和本地维护入口必须使用同一份窗口合同，不能再出现三套 Dagster 实现与两套旧 backend 实现各自维护窗口的情况。

### 1.2 非目标

本专项不做以下事情：

1. 不修改 1m/5m/15m/30m/60m 原生分钟线。
2. 不修改 QFQ 因子公式、MACD/KDJ 公式、字段 schema、asset key、物理路径或动态分区名称。
3. 不新增 production formula check，不增加 asset check 数量。
4. 不修改 run key、job 名称、sensor 名称或日常 first-not-ready 选择策略。
5. 不删除历史 Dagster run、event、dynamic partition 或 repair/status 账本。
6. P0-P5 不执行正式 Lake 重建；P6 正式 promote 与 P7 runless event 补录必须分别审批、分别验收。

## 2. 冻结业务合同

### 2.1 09:30 行的身份

`09:30` 行是集合竞价 K 线，不是一个完整的 30 分钟或 60 分钟连续竞价区间。第一根上午派生 bar 对它的使用规则固定为：

1. `open` 使用 `09:30.close`。
2. `high/low` 只把 `09:30.close` 当作一个价格锚点，不使用 `09:30.high/low`。
3. `vol/amount` 包含 `09:30` 集合竞价成交量和成交额，且只能加一次。
4. `09:30.open` 不参与 90m/120m 派生。
5. 不允许完全丢弃 `09:30` 行，因为这会漏掉开盘锚点和集合竞价成交量/成交额。
6. `09:30.close`、`vol`、`amount` 缺失、非有限或重复时 fail closed，不生成第一根派生 bar。

### 2.2 90m 窗口

90m 只读取同资产、同代码、同交易日的 30m source：

| 输出时间 | 竞价锚点 | 常规 source 时间 | open | close | high / low | vol / amount |
| --- | --- | --- | --- | --- | --- | --- |
| `11:00` | `09:30.close` | `10:00, 10:30, 11:00` | `09:30.close` | `11:00.close` | `max/min(09:30.close, 三根常规 high/low)` | 竞价行加三根常规行求和 |
| `14:00` | 无 | `11:30, 13:30, 14:00` | `11:30.open` | `14:00.close` | 三根常规行 max/min | 三根常规行求和 |
| `15:00` | 无 | `14:30, 15:00` | `14:30.open` | `15:00.close` | 两根常规行 max/min | 两根常规行求和 |

第三根是已确认保留的尾部 60 分钟 bar。第二根按照有序交易 bar 序列聚合，午休期间没有源行，不把午休自然分钟计入成交数据。

### 2.3 120m 窗口

120m 只读取同资产、同代码、同交易日的 60m source：

| 输出时间 | 竞价锚点 | 常规 source 时间 | open | close | high / low | vol / amount |
| --- | --- | --- | --- | --- | --- | --- |
| `11:30` | `09:30.close` | `10:30, 11:30` | `09:30.close` | `11:30.close` | `max/min(09:30.close, 两根常规 high/low)` | 竞价行加两根常规行求和 |
| `15:00` | 无 | `14:00, 15:00` | `14:00.open` | `15:00.close` | 两根常规行 max/min | 两根常规行求和 |

旧实现输出 `10:30` 和 `14:00`，并漏掉 `15:00`，必须整体废止。

### 2.4 15:30 盘后行

A 股正常交易统一按 `15:00` 收盘。源数据中的 `15:30` 行表示盘后交易时段，可能出现在上交所、深交所或北交所，90m/120m 派生统一按以下规则处理：

1. `15:30` 不属于任何 90m/120m 常规窗口，也不是竞价锚点。
2. `15:30` 的 open/high/low/close/vol/amount 均不参与派生聚合；下午最后一根 bar 的 close 固定来自 `15:00.close`。
3. source-day 严格诊断不得仅因存在 `15:30` 行而失败，且该规则不按 exchange 分支。
4. 除 `15:30` 外的其它非合同时间仍 fail closed；本规则不放宽缺失、重复、跨日、非法 OHLCV 或混合 exchange 门禁。
5. 30m/60m 原生数据继续保留源端 `15:30` 事实，本专项不删除或改写原生行。

### 2.5 其它字段

1. `ts_code`、`trade_date`、`exchange` 和目标 `freq` 沿用当前各资产合同。
2. 目标 `trade_time` 固定为上表输出时间。
3. 普通指数和主要指数派生 `vwap` 继续为 `NULL`。
4. 股票 QFQ 的其它非本次字段继续使用现有字段合同，本专项不顺手增加或删除字段。
5. 不跨代码、跨交易日或混合 exchange 聚合。

## 3. 当前实现审计与根因

### 3.1 修复前的重复窗口定义

P1 前，相同业务语义分散在以下实现中：

| 资产族 | 修复前窗口定义 | 修复前 writer / consumer | 问题 |
| --- | --- | --- | --- |
| 股票 QFQ | `defs/stk_mins_qfq.py::GOLD_STK_MINS_QFQ_DERIVED_WINDOWS` | QFQ asset、history、factor repair、check/readiness | 90m 跳过 09:30；120m 把 09:30 当普通 source 并输出错误时间 |
| 普通指数 | `defs/run_contracts/index_mins.py::INDEX_MINS_DERIVED_WINDOWS` | Silver writer、check/readiness、bootstrap | 与股票复制同一错误窗口 |
| 主要指数 | `defs/run_contracts/major_index_mins.py::_MAJOR_INDEX_MINS_DERIVED_WINDOWS` | Silver writer、quality/readiness、bootstrap | 与前两套复制同一错误窗口；还保留不进入 Silver 的 BSE 派生分支 |
| 旧股票 backend | `backend/app/services/stk_mins_derived_service.py` | CLI、Sync Center、本地旧湖写入 | 90m 直接跳过 09:30，120m 按两根切块 |
| 旧指数 backend | `backend/app/services/index_mins_derived_service.py` | CLI、本地旧湖写入 | `_DERIVED_CHUNK_RANGES` 锁定旧分组 |

根因不是某一条 SQL 写错，而是“集合竞价锚点”没有成为显式合同，并且同一规则被复制到多个模块。测试又直接使用这些窗口常量构造 expected，导致实现和测试一起报绿。

### 3.2 旧行为的具体错误

1. 90m 第一根只聚合 `10:00/10:30/11:00`，所以 `open` 错用 `10:00.open`，竞价 `vol/amount` 被漏掉。
2. 120m 第一根聚合 `09:30/10:30`，所以 `open` 错用 `09:30.open`，输出时间错为 `10:30`，且漏掉 `11:30` 常规 bar。
3. 120m 第二根聚合 `11:30/14:00`，输出时间错为 `14:00`；`15:00` source 被完全丢弃。
4. coverage/check/readiness 复用了同一错误窗口，因此历史 check 全绿不能证明窗口业务语义正确。

## 4. 正式 Lake 只读证据

### 4.1 09:30 open 与 close 不能互换

对 `2026-08-06` 正式 Lake 的 09:30 行做全量只读统计：

| 数据集 | 代码数 | `open != close` | 比例 |
| --- | ---: | ---: | ---: |
| 股票 QFQ | 5,533 | 2,488 | 44.97% |
| 普通指数 | 530 | 308 | 58.11% |

因此不能因为个别样本 `open=close` 就继续使用 `09:30.open`。业务合同必须显式使用 `09:30.close`。

同日 30m 与 60m 的 `09:30.close/vol/amount` 在股票 5,533 个代码、普通指数 530 个代码中完全一致；`2026-08-04` 的主要指数 10 个 Silver 代码也完全一致。因此 90m 可读取自己的 30m source 锚点，120m 可读取自己的 60m source 锚点，不需要为了锚点额外扫描 1m 文件。

### 4.2 90m 是否需要重建

按新合同只读重算第一根 90m，并与正式目标文件比较：

| 数据集 / 日期 | 代码数 | open 变化 | high 变化 | low 变化 | close 变化 | vol 变化 | amount 变化 | 任一字段变化 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 股票 QFQ `2026-08-06` | 5,533 | 3,926 | 155 | 257 | 0 | 5,504 | 5,504 | 5,525 |
| 普通指数 `2026-08-06` | 530 | 530 | 14 | 63 | 0 | 530 | 530 | 530 |
| 主要指数 `2026-08-04` | 10 | 10 | 0 | 0 | 0 | 10 | 10 | 10 |

结论：90m 必须与 120m 一起全历史重建。不能只重建 120m，也不能只修最新日期。即使少数股票当日数值恰好相同，历史文件仍由旧合同生成，不能把偶然相等当作合同合格。

### 4.3 当前重建量级快照

以下为 2026-08-07 只读 Parquet metadata 快照，正式执行前必须重新生成冻结清单：

| 资产 | 文件数 | 行数 | 物理字节 |
| --- | ---: | ---: | ---: |
| 股票 QFQ 90m | 52,880 | 34,787,706 | 1,580,972,479 |
| 股票 QFQ 120m | 52,875 | 23,212,438 | 1,157,462,849 |
| 股票 MACD/KDJ 90m | 52,880 | 34,787,706 | 2,092,707,085 |
| 股票 MACD/KDJ 120m | 52,875 | 23,212,438 | 1,457,996,246 |
| 股票 state 90m | 3,062 | 11,881,180 | 536,122,977 |
| 股票 state 120m | 3,062 | 11,882,383 | 536,175,129 |
| 普通指数 90m | 386 | 612,882 | 26,936,280 |
| 普通指数 120m | 386 | 408,588 | 19,054,806 |
| 主要指数 90m | 4,271 | 91,266 | 11,648,597 |
| 主要指数 120m | 4,271 | 60,844 | 10,233,098 |

总计约 226,948 个目标文件、140,937,431 行、7,429,309,546 字节目标数据。该量级禁止用逐文件 DuckDB connection、逐代码 Python 聚合或 Dagster backfill 重算。

## 5. 上下游影响面

### 5.1 不重建的上游

以下 source 不受影响，只作为重建输入：

```text
gold_stk_mins_qfq_30m
gold_stk_mins_qfq_60m
silver_index_mins_30m
silver_index_mins_60m
silver_major_index_mins_30m
silver_major_index_mins_60m
```

Raw、股票 Silver、adj factor、普通指数 Raw、主要指数 Raw 均不重建。

### 5.2 必须重建的直接目标

```text
gold_stk_mins_qfq_90m
gold_stk_mins_qfq_120m
silver_index_mins_90m
silver_index_mins_120m
silver_major_index_mins_90m
silver_major_index_mins_120m
```

### 5.3 必须重建的股票递推下游

```text
gold_stk_mins_qfq_90m/120m
    -> gold_stk_mins_qfq_macd_kdj_90m/120m
    -> gold_stk_mins_qfq_macd_kdj_state_90m/120m
```

MACD/KDJ 和 KDJ state 都具有历史递推依赖。不能只重算最近日期，也不能保留旧 state 后继续计算。两个频率必须各自从 expected calendar 第一交易日开始，按交易日顺序重建完整 indicator/state 历史。

### 5.4 运行时与消费端

1. `stock_mins_qfq_factor_repair_job` 会重写 90m/120m，必须使用新合同，否则未来 repair 会把旧语义写回。
2. `gold_stk_mins_qfq_macd_kdj_repair_job` 消费 90m/120m QFQ，也必须在合同修复后回归。
3. `silver_index_mins_update_job` 和 `silver_major_index_mins_update_job` 同时生成原生与派生频率，必须在重建期间停止自动提交。
4. 财势乾坤本地分钟接口通过 `src/foundation/clients/local_lake/stock_mins_reader.py` 直接读取 90m/120m QFQ 与指标文件。正式重建完成前，这两个周期仍返回旧语义。
5. 任何基于 `silver_index_mins_120m` 的研究结果都必须标记失效并重新计算，包括波浪/趋势反转回测文档对应的输出；历史研究结论不能继续引用旧 120m bar。

## 6. 目标代码设计

### 6.1 唯一正式窗口合同

新增正式共享合同模块：

```text
lake_console/orchestrator/src/orchestrator/defs/run_contracts/cn_a_derived_minute_bars.py
```

建议结构：

```python
@dataclass(frozen=True, slots=True)
class DerivedMinuteWindow:
    target_freq: int
    target_time: str
    regular_source_times: tuple[str, ...]
    auction_anchor_time: str | None
    expected_regular_source_count: int

CN_A_DERIVED_MINUTE_WINDOWS = {
    90: (...),
    120: (...),
}
```

合同必须把 `auction_anchor_time` 与 `regular_source_times` 分开表达。禁止重新把 09:30 塞回普通 window map，再用 `first(open)` 处理。

原有三个本地窗口常量必须清零：

```text
GOLD_STK_MINS_QFQ_DERIVED_WINDOWS
INDEX_MINS_DERIVED_WINDOWS
_MAJOR_INDEX_MINS_DERIVED_WINDOWS
```

对外 helper 名称可以保留，但必须委托共享合同；不得保留复制的 tuple。

### 6.2 统一 SQL 语义

三个 writer 可保留各自 schema/path 适配，但窗口计算必须复用同一 SQL contract builder：

```text
source_rows
    -> auction_anchor_rows
    -> regular_window_map
    -> regular_window_rows
    -> window_diagnostics
    -> complete_windows
    -> derived_output
```

第一上午窗口：

```sql
open   = anchor.close
close  = arg_max(regular.close, regular.trade_time)
high   = greatest(anchor.close, max(regular.high))
low    = least(anchor.close, min(regular.low))
vol    = anchor.vol + sum(regular.vol)
amount = anchor.amount + sum(regular.amount)
```

其它窗口：

```sql
open   = arg_min(regular.open, regular.trade_time)
close  = arg_max(regular.close, regular.trade_time)
high   = max(regular.high)
low    = min(regular.low)
vol    = sum(regular.vol)
amount = sum(regular.amount)
```

完整性门禁：

1. 每个 code/date 只能有一条 09:30 anchor。
2. 第一 90m 必须有 1 anchor + 3 regular；第一 120m 必须有 1 anchor + 2 regular。
3. 后续窗口 source 时间集合必须精确匹配，不用总行数代替时间身份。
4. 不允许额外 source 行进入窗口。
5. exchange 多值、重复 key、非有限 OHLC、负 `vol/amount` 均 fail closed。

### 6.3 三套正式实现

| 文件 | 代码改动 |
| --- | --- |
| `defs/stk_mins_qfq.py` | derived select、diagnostics、coverage 全部改用共享合同；anchor 单独参与价格与成交聚合 |
| `defs/run_contracts/stk_mins.py` | 只保留目标到 source freq 映射；不再承载窗口副本 |
| `defs/assets/index_mins_silver.py` | native/fallback 不变；90m/120m writer 使用共享合同 |
| `defs/run_contracts/index_mins.py` | 删除本地窗口 tuple；session/fallback 合同保留 |
| `defs/io/major_index_mins_silver_writer.py` | window temp table 改用共享合同；BSE 不进入 Silver 派生 |
| `defs/run_contracts/major_index_mins.py` | 删除重复 CN/BSE 派生窗口；主要指数 Silver 仍排除 `899050.BJ` |
| 三套 quality/readiness/check | 复用同一 identity/diagnostics 语义，不重算一套不同窗口 |
| 三套 bootstrap/apply/event helper | 重建计划、行数和目标时间按新合同生成 |

### 6.4 旧 backend 写入入口

以下入口是会写文件的旧算法生产者，不能只改测试后继续保留第二套口径：

```text
lake_console/backend/app/services/stk_mins_derived_service.py
lake_console/backend/app/services/index_mins_derived_service.py
lake_console/backend/app/cli/commands/stk_mins.py
lake_console/backend/app/cli/commands/sync_dataset.py
lake_console/backend/app/api/sync_center.py
```

实现阶段先用 CodeGraph 再确认消费者，然后按以下顺序收敛：

1. 正式 Lake 的 90m/120m 写入只保留 orchestrator 路径。
2. 删除旧 backend 的派生写命令、API wiring、catalog action 和对应旧算法测试。
3. 如果某个只读 UI 仍需要展示派生结果，改为读取正式 Lake，不允许现场重算或写回。
4. 不增加兼容 wrapper，不复制共享合同到 backend。

## 7. Check、readiness 与事件口径

### 7.1 Check 数量不增加

本专项不新增 check：

| 资产 | 每资产 blocking check 数 | 本次变化 |
| --- | ---: | --- |
| 股票 derived QFQ | 4 | 仅修正 source-window coverage 身份 |
| 股票 MACD/KDJ indicator | 2 | 不改数量和公式职责 |
| 股票 MACD/KDJ state | 2 | 不改数量 |
| 普通指数 Silver | 1 | core check 改用新目标时间/窗口 |
| 主要指数 Silver | 1 | core check 改用新目标时间/窗口 |

公式正确性由独立 literal golden fixture 证明。production check 继续只验证文件、schema、key/value、source-window coverage 和 state/source coverage，不恢复“用同一算法自算自验”的 formula check。

### 7.2 Readiness

1. 最近窗口大小保持当前 10 个 expected dates，不扩大到全历史。
2. 每个 sensor tick 继续使用一次有界 DuckDB batch readiness。
3. 不读取 Dagster event history，不逐日调用单日 helper。
4. 目标文件缺失为 `materialized=False`；文件存在但新合同失败为 `materialized=True, checks_passed=False`，禁止自动覆盖。
5. 历史重建使用独立维护入口，不通过日常 sensor 补全历史。

### 7.3 历史 event 恢复

文件对账通过后才允许恢复 Dagster event：

1. 所有被重建 asset partition 补一条新的 materialization event。
2. blocking check event 只补各自分区集合最近 20 个交易日，并绑定新的 target materialization。
3. 旧 event 不删除；新的 latest materialization/check 覆盖当前状态。
4. repair/status/completion checks 不删除、不重写。
5. dynamic partition 不修改。
6. 普通 runless event 是默认交付方式；如果 Dagster 当前版本因 runless check 唯一键阻止同一 `asset/check/partition` 再写一条 check，必须保留旧有效 check，并通过真实单分区 checks-only run 写入新的 check。禁止伪造 run id，也禁止为绕过唯一键删除旧有效 check。

按当前快照预计：

| 事件 | 预计数量 |
| --- | ---: |
| 全历史 materialization | 27,686 |
| 最近 20 日 blocking checks | 400 |
| 合计目标 materialization/check events | 28,086 |

正式计划必须从冻结日期清单重新计算，不能把以上快照写死为 apply 数量。

## 8. 测试设计

### 8.1 独立 golden fixture

fixture expected 必须写字面量，禁止调用被测窗口 helper 生成 expected。至少覆盖：

1. 09:30 `open != close`，证明输出 open 使用 close。
2. 09:30 high/low 与 close 不同，证明只把 close 当价格锚点。
3. 09:30 vol/amount 非零，证明只加一次。
4. 90m 三个目标时间 `11:00/14:00/15:00`。
5. 120m 两个目标时间 `11:30/15:00`。
6. 第一窗口缺 anchor、anchor 重复、缺任一 regular source 时 fail closed。
7. 午休前后窗口只按固定 source 时间集合聚合。
8. 股票、普通指数、主要指数对同一输入得到相同 OHLCV 语义。

### 8.2 回归范围

至少覆盖：

```text
tests/test_stk_mins_qfq_m11_derived_assets.py
tests/test_stk_mins_qfq_formula_golden_contracts.py
tests/test_stk_mins_lake_readiness.py
tests/test_stk_mins_continuity_performance.py
tests/test_stk_mins_qfq_m11f_derived_history.py
tests/test_stk_mins_qfq_m12_macd_kdj.py
tests/test_stk_mins_qfq_macd_kdj_repair_op_contracts.py
tests/test_index_mins_contracts.py
tests/test_index_mins_silver_writer.py
tests/test_index_mins_lake_readiness.py
tests/test_index_mins_bootstrap_apply.py
tests/test_major_index_mins_contracts.py
tests/test_major_index_mins_silver_writer.py
tests/test_major_index_mins_lake_readiness.py
tests/test_major_index_mins_bootstrap_apply.py
tests/test_run_contract_static_gates.py
```

静态门禁必须证明：

1. 活跃 orchestrator 中只有一份 CN A 股 90m/120m 窗口合同。
2. 不存在 `09:30 -> target 10:30` 或 `11:30 -> target 14:00` 的 120m 旧映射。
3. 第一窗口 SQL 明确读取 `anchor.close`，不读取 `anchor.open/high/low`。
4. 旧 backend 派生写入口已退出，不再能写正式或旧湖 90m/120m。
5. production check 数量没有增加。

## 9. 性能门禁

### 9.1 代码阶段

1. 单日三套 writer 各使用一个 DuckDB connection 和一次 set-based 派生查询。
2. 90m/120m 各自读取 30m/60m 的 09:30 anchor，不额外扫描 1m。
3. check/readiness 只做 identity/coverage 聚合，不重算完整 OHLC expected。
4. 不逐代码、逐行 Python 计算。

### 9.2 重建阶段

1. 正式 staging 必须位于与 Lake 相同文件系统，例如 `<lake_root>/_tmp/<rebuild_id>`，保证 promote 可原子 rename；`/private/tmp` 只保存报告和小样本。
2. 股票 stock-year 文件默认按 `freq/year` 做一次 set-based 扫描；若 P2 最新日期样本已证明单批预算不足，只允许进一步缩小批次，禁止为 benchmark 额外扫描全历史，也禁止重复打开相同 source 集合。
3. 普通指数和主要指数按不超过 20 个交易日的有界批次执行，批内 set-based 读取。
4. MACD/KDJ 必须按频率顺序扫描日期，不能为每个交易日从历史起点重算。
5. 正式重建前计算 staging、rollback backup 和安全余量。按当前 7.43 GB 目标快照，至少预留目标数据两倍以上的额外空间，并以实际压缩率重新计算。
6. 每批记录 source files/rows、output files/rows、DuckDB elapsed、write/readback/promote elapsed、峰值内存和失败样本。
7. 任何全历史 Python 缓存、逐分区 Dagster job/backfill、无界文件 glob、event history 深扫或跨文件系统 promote 都不允许进入正式执行。

### 9.3 P0/P1 已执行结果

P0 只读报告：

```text
/private/tmp/derived_minute_bars_p0_preflight_20260807_105136_v2.json
/private/tmp/derived_minute_bars_p0_manifests_20260807_105136/
```

停机后确认 Dagster 相关进程为 0、active runs 为 0、30m/60m source 结构性异常为 0，`should_stop=false`。冻结分区事实如下：

| 分区集合 | 数量 | 范围 | SHA-256 |
| --- | ---: | --- | --- |
| `cn_a_stock_mins_silver_trade_days` | 3,062 | `2014-01-02..2026-08-06` | `9c27ccff27877eb0caf4db3ee5cde56107518c9d6d1148bffb96a72515697161` |
| `cn_a_index_mins_trade_days` | 387 | `2025-01-02..2026-08-07` | `0168078cdf7428731430ce97033c6cd5b75df0780a355c0f838f8267ed95ea46` |
| `cn_major_index_mins_trade_days` | 4,271 | `2009-01-05..2026-08-04` | `778ea9f612e0727f81243493ea62100b543f99086c0ab77756aa9e2918583b99` |

P1 已完成：

1. 新增 `defs/run_contracts/cn_a_derived_minute_bars.py`，统一 anchor/regular 角色、窗口、目标时间和精确完整性谓词。
2. 股票 QFQ、普通指数和主要指数 writer/diagnostics/coverage/readiness/bootstrap 全部消费共享合同；factor repair 继续复用同一 QFQ derived builder。
3. 删除 backend 股票/指数旧 derived service、CLI、catalog action 和 Sync Center 派生写阶段；正式派生写入只保留 orchestrator。
4. 新增静态门禁，禁止三个旧窗口常量、旧 service、旧 CLI 和旧 Sync Center 阶段回流。
5. QFQ 派生诊断把错误频率、跨日时间、非合同时间、非法 OHLCV 和空 exchange 纳入 source-day 完整性；daily/history writer 发现任一不完整窗口即整体拒绝写入。缺/重复 anchor、缺 regular、跨日、非法数值和非合同时间均有负向样本。
6. 核心 literal fixture 为 46 tests + 11 subtests 全绿；扩大到 factor repair、三类 check/readiness/bootstrap/definitions 和静态门禁后为 285 tests + 11 subtests 全绿。
7. backend Sync Center/clean-next 回归 23 个通过；全仓 command-example 测试另有 `anns_d` 等 4 个无关既有缺口，不属于本专项。
8. `dg check defs` 通过，全部 component YAML 和 definitions 均可加载。

P0/P1 没有修改正式 Parquet、Dagster DB、dynamic partition、event 或 sensor 状态。

## 10. 历史重建执行步骤

### P0：冻结与只读 preflight

1. 停止以下会写相关目标的 sensor，或在 `dg dev` 完全关闭时保持关闭：
   - `stock_mins_qfq_daily_sensor`
   - `stock_mins_qfq_factor_repair_sensor`
   - `gold_stk_mins_qfq_macd_kdj_daily_update_job_sensor`
   - `gold_stk_mins_qfq_macd_kdj_repair_job_sensor`
   - `index_mins_trade_day_sensor`
   - `raw_index_mins_update_job_sensor`
   - `silver_index_mins_update_job_sensor`
   - `major_index_mins_trade_day_sensor`
   - `raw_major_index_mins_update_job_sensor`
   - `silver_major_index_mins_update_job_sensor`
2. 确认没有相关 `QUEUED/STARTING/STARTED/CANCELING` run。
3. 冻结三套 expected/registered 日期、代码范围、source 文件和 target 文件清单及 fingerprint。
4. 只读确认 30m/60m source 全部通过现有结构性合同。

P0 实际恢复基线：前七个 sensor 的持久化状态为 RUNNING；三个主要指数 sensor 为 STOPPED/default。P0 至 P7 期间不启动 Dagster；如确需临时启动，必须先把七个 RUNNING sensor 改为 STOPPED。

### P1：代码修复

1. 新增共享窗口合同和 SQL contract builder。
2. 修改三套正式 writer、diagnostics、coverage、quality、readiness 和 bootstrap helper。
3. 修改 factor repair 的 derived rewrite 路径。
4. 删除旧 backend 派生写入口及消费者。
5. 更新 catalog notes、data card、方案文档和静态门禁。
6. 不写正式 Lake 或 Dagster instance。

### P2：最新日期真实性样本

P2 不做起始日、中间日或全市场真实性重算。每个资产族只验证其冻结分区集合中的最新 source-ready 日期：

| 资产族 | 样本日期 | 代码样本上限 |
| --- | --- | ---: |
| 股票 QFQ | `2026-08-06` | 10 |
| 普通指数 | `2026-08-06` | 10 |
| 主要指数 | `2026-08-04` | 5 |

1. 先跑 literal golden fixture，公式正确性仍由固定输入和固定 expected 独立证明。
2. 在各自最新日期内按确定性规则选择代码：优先覆盖 `09:30.open != close`、anchor close 影响 high/low、不同 exchange；其余按代码排序补足。样本清单和选择原因写入报告，禁止人工挑选只会通过的样本。
3. 只把这些代码的 30m/60m source 抽取到 `/private/tmp` 临时 Lake，分别构建 90m/120m；不复制或扫描该日期的全市场数据。
4. 使用独立审计 SQL 逐根核对目标时间、`09:30.close` anchor、OHLC、vol/amount、schema、PK 和 exchange；竞价成交量与成交额必须且只能计入一次。
5. 输出一份有界真实性报告，记录 source/output 行数、样本代码、逐窗口 expected/actual 和失败原因。P2 不写正式 Lake、Dagster DB 或 event。

P2 实际执行结果（2026-08-07）：

1. 普通指数 `cn_a_index_mins_trade_days` 已注册到 `2026-08-07`，但正式 30m/60m source 文件共同最新日期为 `2026-08-06`；P2 按“最新 source-ready 日期”使用 `2026-08-06`，没有为满足静态日期制造或补猜数据。
2. literal fixture 已通过：`28 passed, 6 subtests passed`。
3. 确定性分层样本：
   - 股票 QFQ：`920045.BJ`、`600032.SH`、`000042.SZ`、`920028.BJ`、`600059.SH`、`000058.SZ`、`920017.BJ`、`600021.SH`、`000066.SZ`、`920029.BJ`；exchange 分布为 BSE 4、SSE 3、SZSE 3。
   - 普通指数：`399811.SZ`、`000858.SH`、`399620.SZ`、`000001.SH`、`399638.SZ`、`000002.SH`、`399388.SZ`、`000004.SH`、`399417.SZ`、`000017.SH`；exchange 分布为 XSHE 5、XSHG 5。
   - 主要指数：`399001.SZ`、`000001.SH`、`399006.SZ`、`000016.SH`、`000300.SH`；exchange 分布为 XSHE 2、XSHG 3。
4. 候选发现保持有界：股票只扫描每个 exchange 前 64 个同时具备 2026 年 30m/60m 文件的候选，共 192 个代码、384 个文件，其中 191 个满足目标日完整时间网格；普通指数和主要指数各只扫描最新日期的两份 source 文件，并只投影候选摘要列。
5. 三个正式 writer 在临时 Lake 生成 90m/120m，共 48 个 Parquet，无 staging 残留。独立 DuckDB SQL 对账结果：
   - 股票 QFQ：90m `90 -> 30` 行，120m `50 -> 20` 行。
   - 普通指数：90m `90 -> 30` 行，120m `50 -> 20` 行。
   - 主要指数：90m `45 -> 15` 行，120m `25 -> 10` 行。
   - 六组结果均为 missing key 0、extra key 0、value mismatch 0、duplicate key 0、schema match；所有第一上午窗口均满足 anchor count=1，且 anchor vol 非零，竞价成交量/成交额只计入一次。
6. 报告：`/private/tmp/derived_minute_bars_p2_latest_sample_20260807_151726.json`；成功临时 Lake：`/private/tmp/derived_minute_bars_p2_lake_20260807_151726`；`should_stop=false`，总耗时约 `967 ms`。
7. P2 正式环境写入计数均为 0：正式 Lake、Dagster DB、Dagster event、sensor 状态均未修改。

### P3：DuckDB 宏观对账与执行预算

P3 不再执行全历史派生 SELECT，也不逐文件做深度数值审计。P0 已完成的 source 结构审计和冻结 manifest 作为正式基线，P3 只做下面的低成本宏观门禁：

1. DuckDB 按有界路径批次读取 Parquet metadata/schema，汇总三条 source/target 链路的文件数、row-group 行数、物理字节、日期范围和 schema fingerprint；禁止逐文件建立 connection。
2. 依赖 P0 的 source 时间网格异常为 0，按合同基数计算预计输出行数：90m 每个完整 stock/index-day 产生 3 行，120m 产生 2 行。预计数量必须与冻结目标布局和后续 staging 计划一致。
3. 对 QFQ stock-year、普通指数 date partition、主要指数 date partition 和 MACD/KDJ history 分别计算待写文件数、预计输入/输出字节、staging/rollback 空间和批次数，不运行全历史指标计算 benchmark。
4. 数值正确性直接复用 P2 最新日期样本结果；P3 不重复读取全历史 OHLCV，不重复审计已经通过 P0 的 source 主键和数值域。
5. 只在以下情况 `should_stop=true`：文件/行数不可解释、schema fingerprint 漂移、日期范围越界、合同基数不可整除、目标路径冲突或磁盘预算不足。
6. 输出 `/private/tmp/derived_minute_bars_p3_macro_audit_<timestamp>.json`。该报告只冻结数量和执行预算，不创建正式目标、不写 event。

P3 实际执行结果（2026-08-07）：

1. 报告：`/private/tmp/derived_minute_bars_p3_macro_audit_20260807_152844.json`；`should_stop=false`，stop reason 为 0，总耗时约 `30.7s`。
2. 运行边界保持冻结：active run 为 0，Dagster daemon/webserver/code-server/user-code 进程为 0；正式 Lake、Dagster DB、Dagster event 和 sensor 状态写入均为 0。
3. 12 组直接 source/target 的文件数、row-group 行数、物理字节与 P0 冻结 manifest 完全一致，manifest SHA-256 也全部匹配。按“每个 stock-year 一份、每 20 个 date partition 一份”的有界规则抽样 996 个文件，schema 全部与合同一致。
4. 股票 QFQ 数量门禁通过：30m/90m 均为 52,880 个 stock-year 文件，60m/120m 均为 52,875 个；90m 目标 34,787,706 行、120m 目标 23,212,438 行，目标行数分别可按 3 行和 2 行合同整除。股票历史允许生命周期边缘存在 partial stock-day，因此 corrected 精确输出行数仍由 P4 staging diagnostics 计算，P3 未用简单除法伪造精确值。
5. 普通指数数量合同精确成立：386 个 source-ready 日期内，30m `1,838,646 / 9 = 204,294` 个完整 code-day，对应 90m `612,882 / 3 = 204,294`；60m `1,021,470 / 5 = 204,294`，对应 120m `408,588 / 2 = 204,294`。
6. 主要指数数量合同精确成立：4,271 个日期内，30m `273,798 / 9 = 30,422` 个完整 code-day，对应 90m `91,266 / 3 = 30,422`；60m `152,110 / 5 = 30,422`，对应 120m `60,844 / 2 = 30,422`。
7. MACD/KDJ 对账通过：90m 和 120m indicator 的文件数与行数分别和同频 QFQ 完全一致；两个 state 资产各有 3,062 个 date-partition 文件，与冻结股票分区数一致。另抽样 336 个 indicator/state 文件，schema 全部匹配。
8. P4-P6 预计处理 226,948 个目标文件；当前目标快照约 `7.43 GB`，staging、rollback 和 25% 安全余量合计需要约 `16.72 GB`，当前可用约 `2.54 TB`，空间余量约 151.9 倍。预定 staging/rollback 路径均不存在，且与正式 Lake 位于同一文件系统。
9. 批次预算为 828 批：QFQ stock-year 26 批、普通指数 date batch 40 批、主要指数 date batch 428 批、MACD/KDJ stock-year 26 批、state date batch 308 批。根据 P2 四个暴露耗时的 date-partition writer 估算并乘以 4 倍安全系数，计划耗时约 `5.66h`；股票 QFQ helper 未单独暴露 writer elapsed，因此该时长只用于容量规划，P4 每批真实 telemetry 才是继续执行的硬门禁。
10. P3 没有执行全历史派生 SELECT、OHLCV 明细扫描或 Dagster event history 查询；数值正确性继续以 P2 最新 source-ready 日期独立审计为依据。

### P4：直接派生资产 staging

顺序固定：

```text
gold_stk_mins_qfq_90m/120m
silver_index_mins_90m/120m
silver_major_index_mins_90m/120m
```

1. 每个资产族全部写入 versioned staging。
2. 完成全量 schema/date/time/key/count/domain/window 对账。
3. 任一异常停止，不能 promote 部分资产族。

首次 P4 执行在股票 QFQ 90m 的 2021 年批次按门禁停止：2014-2020 年 7 个 stock-year staging 批次已经独立对账通过，2021 年 source 中 `15:30` 盘后行被旧严格谓词误判为非合同时间，产生 `8,124` 个 incomplete windows。只读全量归因确认该类行是盘后事实，不应参与 90m/120m；正式目标文件、Dagster DB 和 sensor 状态均未修改。修复第 2.4 节共享合同并通过回归后，P4 从已验收 staging 断点继续，不删除或重算已通过批次。

P4 实际执行结果（2026-08-07）：

1. 最终报告：`/private/tmp/derived_minute_bars_p4_staging_20260807_160522.json`；`should_stop=false`，`final_audit.passed=true`，报告耗时约 `29m41s`。
2. versioned staging 根目录：`/Volumes/datasource/data_lake/_tmp/derived_minute_bars_90_120_contract_v2`；磁盘占用约 `2.8G`。
3. 六组 staging 的最终事实如下：

| 资产族 | 频率 | 文件数 | 行数 | 物理字节 | schema |
| --- | ---: | ---: | ---: | ---: | --- |
| 股票 QFQ | 90m | 52,880 | 34,787,706 | 1,581,430,831 | 全部匹配 |
| 股票 QFQ | 120m | 52,875 | 23,212,438 | 1,159,775,006 | 全部匹配 |
| 普通指数 | 90m | 386 | 612,882 | 26,985,098 | 全部匹配 |
| 普通指数 | 120m | 386 | 408,588 | 18,983,974 | 全部匹配 |
| 主要指数 | 90m | 4,271 | 91,266 | 11,650,402 | 全部匹配 |
| 主要指数 | 120m | 4,271 | 60,844 | 10,240,201 | 全部匹配 |
| 合计 | - | 115,069 | 59,173,724 | 2,809,065,512 | 全部匹配 |

4. 股票 QFQ 共 26 个 stock-year 批次；普通指数共 40 个日期批次；主要指数共 428 个日期批次。所有批次均满足 `expected_window_count == generated_window_count` 且 `incomplete_window_count=0`。
5. 主要指数开工前曾因临时 P4 执行器把频率整数 `90` 传给要求 `"90min"` 的 writer 而 fail closed。该问题只修正 `/private/tmp` 执行适配器，未修改业务合同；续跑复用了已通过对账的股票 QFQ 和普通指数 staging，没有重复覆盖正式数据。
6. 最终 staging 宏观审计确认：临时残留文件为 0、全部 Parquet 都有合同 schema、正式目标 manifest 前后完全一致。另以独立进程把 P0 冻结 manifest 中 115,069 个正式目标路径的 size/mtime 与当前文件逐一复核，差异为 0。
7. P4 写入边界为：versioned staging 写入已发生；正式 Lake target 写入 0、Dagster DB 写入 0、Dagster event 写入 0、sensor 状态修改 0。
8. P4 后独立复核确认 active run 为 0，Dagster daemon/webserver/code-server/user-code 进程为 0。P4 到此收口，不自动进入 P5。

### P5：股票指标与 state staging

1. 只读取 P4 已验收的 corrected QFQ staging 或已经冻结的 corrected source view。
2. 90m、120m 分别从 expected calendar 第一交易日顺序计算。
3. 同时生成 indicator stock-year staging 和 state date-partition staging。
4. 检查每个 QFQ key 都有 indicator key；每个日期都有正确 state frontier。
5. 不复用旧 90m/120m state 作为初始化。

P5 已于 2026-08-07 完成，正式报告为：

```text
/private/tmp/derived_minute_bars_p5_staging_20260807_164959.json
SHA-256: 2551d692be032c7a92fe3f3029e8de5a8d81723ce266bb67e62a3a8e6082c6ba
```

实际执行与验收结果：

1. 写入前只读 preflight 报告为 `/private/tmp/derived_minute_bars_p5_staging_20260807_164916.json`。冻结的 `cn_a_stock_mins_silver_trade_days` 仍为 3,062 个，范围为 `2014-01-02..2026-08-06`，SHA-256 指纹仍为 `9c27ccff27877eb0caf4db3ee5cde56107518c9d6d1148bffb96a72515697161`。
2. P4 corrected QFQ source 重新核对为 105,755 个文件、58,000,144 行，全部文件 schema 与合同一致；P5 开工前四类 indicator/state staging 目标均为 0。
3. P5 按 `90m -> 120m`、每个频率按 `2014 -> 2026` 的顺序完成 26 个 stock-year 批次。只有两个频率各自的 2014 首批使用无 previous state 初始化，其余 24 个批次均承接 staging 中上一 expected state；未读取正式旧 90m/120m state。
4. 每个年度批次均执行 QFQ 与 indicator `(ts_code, freq, trade_date, trade_time)` 双向 `EXCEPT` 对账、indicator/state schema 与唯一键检查、数值及参数合同检查、逐日 state 最新 `last_trade_time` 与当日 indicator frontier 精确对账。26 个批次全部通过，缺 indicator key、额外 indicator key、state frontier 错位和未来 state 时间均为 0。
5. 最终 staging 文件事实如下：

| 资产 | 文件数 | 行数 | 大小（bytes） |
| --- | ---: | ---: | ---: |
| `gold_stk_mins_qfq_macd_kdj_90m` | 52,880 | 34,787,706 | 2,092,728,026 |
| `gold_stk_mins_qfq_macd_kdj_120m` | 52,875 | 23,212,438 | 1,457,984,675 |
| `gold_stk_mins_qfq_macd_kdj_state_90m` | 3,062 | 11,881,180 | 536,123,037 |
| `gold_stk_mins_qfq_macd_kdj_state_120m` | 3,062 | 11,882,383 | 536,175,845 |

6. 四类文件均为单一合同 schema，临时残留文件为 0。P5 总耗时为 `884,506.801ms`，约 14 分 45 秒；P4+P5 versioned staging 当前约 `7.3G`。
7. P5 前后 P4 corrected QFQ source 的 path/size/mtime 快照完全一致；正式 MACD/KDJ indicator/state 的 111,879 个文件 path/size/mtime 快照也完全一致。独立复核 active run 为 0，未发现 Dagster daemon/webserver/code-server/user-code 进程。
8. P5 写入边界为：versioned staging 写入已发生；正式 Lake target 写入 0、Dagster DB 写入 0、Dagster event 写入 0、sensor 状态修改 0。P5 到此收口，不自动进入 P6。

### P6：原子 promote

1. 再次确认相关 writer/sensor 无 active run。
2. 按资产族建立 rollback manifest 和旧文件 backup。
3. 只 promote 已通过全量对账的 staging。
4. 每批完成后立即只读核对 target hash/count；异常时停止并按 manifest 回滚当前批次。
5. 禁止先删除全部旧文件再生成，避免中途留下正式 Lake 空洞。

P6 已于 2026-08-07 完成，正式报告为：

```text
/private/tmp/derived_minute_bars_p6_promote_20260807_191332.json
SHA-256: f70cb7ca28039df4857157e9d77680a3a0cd1b66326d85cdefa46b90c311c122
```

实际执行与验收结果：

1. 正式写入前只读 preflight 报告为 `/private/tmp/derived_minute_bars_p6_promote_20260807_191157.json`，`should_stop=false`。冻结分区、P0/P4/P5 manifest、226,948 个 staging/target 路径、828 个批次及磁盘预算全部通过，rollback 根目录在写入前不存在。
2. promote 顺序严格固定为：股票 QFQ 90m/120m、普通指数 90m/120m、主要指数 90m/120m、股票 MACD/KDJ indicator 90m/120m、state 90m/120m。828 个批次全部成功；每批先创建旧文件 hard-link rollback backup，再以同文件系统 `os.replace(...)` 原子替换，并立即核对新 target 的 path/size/mtime SHA-256。
3. 共替换 226,948 个正式 Parquet 文件；最终正式 Lake 为 140,937,431 行、7,432,077,095 bytes。十组正式资产的文件数、行数、字节数和 schema 均与 P4/P5 已验收 staging 完全一致：

| 资产 | 文件数 | 行数 | 大小（bytes） |
| --- | ---: | ---: | ---: |
| `gold_stk_mins_qfq_90m` | 52,880 | 34,787,706 | 1,581,430,831 |
| `gold_stk_mins_qfq_120m` | 52,875 | 23,212,438 | 1,159,775,006 |
| `silver_index_mins_90m` | 386 | 612,882 | 26,985,098 |
| `silver_index_mins_120m` | 386 | 408,588 | 18,983,974 |
| `silver_major_index_mins_90m` | 4,271 | 91,266 | 11,650,402 |
| `silver_major_index_mins_120m` | 4,271 | 60,844 | 10,240,201 |
| `gold_stk_mins_qfq_macd_kdj_90m` | 52,880 | 34,787,706 | 2,092,728,026 |
| `gold_stk_mins_qfq_macd_kdj_120m` | 52,875 | 23,212,438 | 1,457,984,675 |
| `gold_stk_mins_qfq_macd_kdj_state_90m` | 3,062 | 11,881,180 | 536,123,037 |
| `gold_stk_mins_qfq_macd_kdj_state_120m` | 3,062 | 11,882,383 | 536,175,845 |

4. promote 后 versioned staging 中属于本次 target 的文件数为 0，临时文件数为 0。rollback 根目录完整保留 226,948 个旧文件，共 7,429,309,546 bytes；旧文件集合 fingerprint 为 `e3b44a3fd111eda7e07b1479585a1a2ea9a4ff793a8c5d3895f1751563e3d4b9`。
5. 828 份 rollback manifest 和 828 份通过的 checkpoint 均已保存。执行中没有失败批次，也没有触发批次回滚；P6 总耗时为 `296,514.744ms`，约 4 分 57 秒。
6. P6 后独立复核 active run 为 0，未发现 Dagster daemon/webserver/code-server/user-code 进程。P6 写入边界仅包含正式 Lake target 和 rollback 文件；Dagster DB、materialization/check event、dynamic partition 和 sensor 状态写入均为 0。
7. P6 到此收口，不自动进入 P7。当前 Dagster 中仍保留旧 materialization/check 事实，必须按 P7 单独 dry-run、审批和补录，不能把 P6 的物理文件成功误认为事件恢复已经完成。

### P7：Dagster event 恢复

1. 先 dry-run 事件计划，确认文件审计全部通过。
2. 全历史补 corrected materialization。
3. 仅最近 20 个各自分区日补 corrected blocking check，并绑定 corrected latest materialization。
4. 对照计划数量、partition、target materialization、asset key 和 check name。
5. 不删除旧 event，不修改 repair/status/completion 账本。

P7 已于 2026-08-07 完成。正式计划和最终报告为：

```text
/private/tmp/derived_minute_bars_p7_plan_20260807_193549.json
SHA-256: 0c8e9839a1bc6753ba4b9dbbc39b3919a150179ff2f2b47e3852ec5f8a15f1d8

/private/tmp/derived_minute_bars_p7_hybrid_full_20260807.json
SHA-256: 31cc6804acafd2570e6ae75a1335fe92d7ec727946e478bfb17e2e378a9de542
```

实际执行与验收结果：

1. dry-run 重新读取 P0 冻结分区和 P6 正式 Lake 事实，生成 `27,686` 条全历史 materialization 与 `400` 条最近 20 个物理交易日 blocking check，共 `28,086` 条目标事件。全部最近窗口 check 在写入前以正式 check 语义只读执行并通过。
2. 样本门禁报告为 `/private/tmp/derived_minute_bars_p7_hybrid_sample_20260807.json`，SHA-256 为 `837e6297184c8eee40a4fca0b4d2fb73af42b030d3a912062ad9ba9f67bad642`。十个资产各取最早/最新分区，共 20 条 materialization；每个资产最新分区共 20 条 check，全部正确归属并绑定本轮最新 materialization。
3. Dagster `1.13.8` 的 runless check 固定使用空 `run_id`，数据库唯一键为 `(asset_key, check_name, run_id, partition)`。普通指数有 24 条、主要指数有 40 条目标 check 与既有有效 runless check 冲突。碰撞计划为 `/private/tmp/derived_minute_bars_p7_collision_plan_20260807.json`，SHA-256 为 `3838a31b173d05c234ce4845cebca2d62c8b625165de4abcff1cdb704a4c7645`。
4. 对 64 条碰撞 check 采用受支持的单分区 checks-only run：普通指数 12 个交易日、主要指数 20 个交易日，每个 run 同时执行 90m/120m 两条 core check，共 32 个 run、64 条 check。32 个 run 全部为 `SUCCESS`，且每条 check 的 `partition` 和 `target_materialization_data.storage_id` 均与本轮最新 materialization 精确一致。原有 64 条有效 runless check 完整保留，没有删除或改写。
5. 其余 336 条 check 使用 runless event；27,686 条 materialization 全部使用 runless event。checkpoint 为 `/private/tmp/derived_minute_bars_p7_checkpoint_20260807_194033.sqlite`，最终记录 `materialization=27,686`、`check=400`、`inflight=0`。
6. 首次 runless 碰撞在失败事务前已写入一条未被 `asset_check_executions` 或 `asset_event_tags` 引用的孤立 `event_logs.id=6906889`。该行先完整导出到 `/private/tmp/derived_minute_bars_p7_orphan_event_6906889_backup.json`（SHA-256 `b3d9623f828b8abdeac742b8e420fc9ac32281c6c64c01e4e1e0961e326bd305`），再在 active run 为 0、引用数为 0、事件类型和空 run id 全部精确匹配的单事务中定点删除。删除后孤立行数为 0；这不是删除旧有效历史 check。
7. 最终逐项审计为：materialization verified `27,686`、check verified `400`、runless check `336`、checks-only check `64`，`passed=true`。三个 dynamic partition 集合与 P0 冻结值和 fingerprint 完全一致，active run 为 0，未发现 Dagster daemon/webserver/code-server/user-code 进程。
8. P7 写入边界仅包含 Dagster materialization/check event，以及 32 个 checks-only run 的正常运行记录；正式 Lake、dynamic partition、repair/status/completion check 和 sensor 状态写入均为 0。P7 到此收口，不自动进入 P8。

### P8：恢复自动化与消费验收

1. 只读确认三套最近 10 日 batch readiness 全绿。
2. 确认 90m/120m MACD/KDJ latest state 与 corrected QFQ frontier 一致。
3. 启动 Definitions 后先做只读 UI/API 抽查，再按原状态恢复 sensors。
4. 观察至少 3 个交易日，确认新 daily 与 factor repair 都持续生成新合同。
5. 重新运行受影响的 120m 研究/回测并标记旧报告失效。

#### P8 Day-0 启动记录（2026-08-07）

P8 已开始，但尚未完成连续 3 个交易日验收，也尚未重新运行受影响的研究/回测。

只读进入门禁：

```text
/private/tmp/derived_minute_bars_p8_entry_audit_20260807.json
SHA-256: d9e724de40041e009e5120a0fcb1ed8efe004f69392690dee9ba9b3b0d95596e
```

1. 启动前 active run 为 0；股票 qfq、普通指数、主要指数最近 10 个物理交易日 batch readiness 全绿，`2026-08-06` 的 14 个 MACD/KDJ asset/state readiness 全绿。
2. 本地分钟 API 抽查 `600030.SH` 的 90m、120m 行情及 120m MACD/KDJ，API 均返回 `READY`，返回值与正式 Lake 精确一致。90m 时间为 `11:00/14:00/15:00`，120m 时间为 `11:30/15:00`；第一上午 bar 的 open 为 `09:30.close`。
3. Dagster 于 `2026-08-07 21:56:09 +08:00` 启动，Definitions 和 Asset 页面正常加载。原先持久化 RUNNING 的 7 个相关 sensor 均完成首轮 tick，没有错误或 RPC timeout；3 个主要指数 sensor 继续保持 STOPPED/default，未被本轮启动。
4. 股票 qfq daily/factor repair sensor 因 `cn_a_stock_mins_silver_trade_days` 尚未注册 `2026-08-07` 而 fail closed，没有误触发。MACD/KDJ daily/repair sensor 无新 upstream run，因此正常 skip。
5. `raw_index_mins_update_job_sensor` 只提交 `raw_index_mins_update:2026-08-07`，run `fa0d1980-97bc-47d8-b040-2982edbdeda9` 成功。Raw 五频共 `170,130` 行、530 个代码；单日 lake readiness 复核为 ready，耗时约 `47ms`。
6. `silver_index_mins_update_job_sensor` 在下一次自然 tick 中只提交 `silver_index_mins_update:2026-08-07`，run `eb5d9254-056c-40b4-ba9c-f1b404c7d0d2` 成功。该 tick 批量扫描 Raw 50 个文件约 `458ms`、Silver 126 个文件约 `1,047ms`，总 tick 约 `2.09s`。
7. 新 Silver 分区生成 7 个频率文件：90m 为 `1,590` 行、120m 为 `1,060` 行，两者均覆盖 530 个代码；90m 时间为 `11:00/14:00/15:00`，120m 时间为 `11:30/15:00`。Silver 单日 readiness 全绿，14 个文件、`172,780` 行，耗时约 `318ms`。
8. P8 Day-0 结束时 active run 为 0，7 个相关 RUNNING sensor 均无错误；本轮没有启用主要指数 sensor，也没有手工触发 job。

运行审计：

```text
/private/tmp/derived_minute_bars_p8_day0_runtime_20260807.json
SHA-256: 0d739ce7d5b4c13f2cbcd11f3eb7dc4630bdcfb197565249ed19265a98478f1e
```

UI 抽查同时发现 P7 runless 回填的事件顺序遗留：P7 先写 latest 样本，再补其余历史分区，因此 6 个股票 qfq/指标/state 资产在 Asset 页面暂显示 `2026-08-05`，2 个主要指数资产暂显示 `2026-08-03`；对应物理和分区 readiness frontier 分别已到 `2026-08-06`、`2026-08-04`。这不影响 Lake、按分区 check、readiness 或自动触发；普通指数 90m/120m 已被本轮真实 daily run 自然刷新到 `2026-08-07`。P8 不擅自补写事件，UI latest 顺序修正作为单独待审项保留。

```text
/private/tmp/derived_minute_bars_p8_ui_order_audit_20260807.json
SHA-256: 3ae35aa04f168ed3f5ed93c3dbb1ef180e121693b78a9b06bb6bc99eb508391a
```

P8 后续必须继续完成：至少 3 个实际交易日的 daily/factor repair 观察；确认股票 qfq 与 MACD/KDJ 新分区也持续使用新合同；处理或明确接受上述 UI latest 事件顺序；重新运行受影响的 120m 研究/回测并标记旧报告失效。未完成这些事项前，本专项不得标记为最终完成。

## 11. 失败与回滚

1. 代码测试失败：不进入任何正式写入。
2. staging 审计失败：删除本批 staging，正式目标不动。
3. promote 失败：停止后续批次，按 rollback manifest 恢复本批旧文件。
4. event 写入失败：不回滚已验证 Lake 文件；保留报告，从未完成的 asset partition 续写 event。
5. 最近 20 日 check 失败：停止恢复 sensor，不用手写绿灯 event 绕过文件问题。
6. 任何 source 30m/60m 异常：退出本专项，先修 source，不能在 derived writer 中填补或猜测。

## 12. 验收标准

只有同时满足以下条件，专项才算完成：

1. 三套正式代码只存在一份 CN A 股 90m/120m 窗口合同。
2. 第一上午 bar 的 open、high/low anchor 和 vol/amount 完全符合第 2 节。
3. 90m 目标时间固定为 `11:00/14:00/15:00`，120m 固定为 `11:30/15:00`。
4. 三套直接派生资产全历史重建并通过文件对账。
5. 股票 90m/120m MACD/KDJ 与 state 从基线顺序重建。
6. 全历史 materialization 与最近 20 日 check event 正确归属。
7. dynamic partitions、repair/status checks、原生频率文件不变。
8. 财势乾坤本地分钟 API 的 90m/120m 抽查与 corrected Lake 一致。
9. 日常 sensors 连续至少 3 个交易日没有旧窗口回流、重复写入或 readiness 性能退化。
10. 原方案文档不再把旧 120m `10:30/14:00` 或 90m 丢弃竞价信息描述为有效口径。

## 13. 开发前无待拍板项

本 LLD 已冻结以下用户决定：

1. 第一上午派生 bar 使用 `09:30.close` 作为 open。
2. 竞价 `vol/amount` 必须包含。
3. 90m 和 120m 都重建。
4. 股票指标和递推 state 属于必须重建的下游。
5. 不增加 production check。

进入代码开发前只需要再次确认正式执行窗口和磁盘空间；这属于运行审批，不是业务口径拍板。

## 14. 2026-08-08 主要指数历史零价修复

全历史只读复核发现，Tushare 当前 5/15/30/60min 源在两个已冻结开盘 scope 返回 OHLC
四价全零，但同一行 `vol/amount` 非零，且当前 1min 返回明确集合竞价价：

- `2016-10-10 / 000016.SH / 15min / 09:30`：1 行；
- `2017-11-29 / 五个上交所主要指数 / 5/15/30/60min / 09:30`：20 行。

Raw 继续保存源事实。Silver 按主要指数接入 LLD 第 29.4 节的 cleanup revision v2 精确
替换这 21 行四价，未知零价不得自动修复。2016 行不属于 90/120 source；2017 的 30/60
修复后必须重新生成 90/120，清除第一上午 bar 的 10 行派生污染。窗口合同本身不变：
90min 仍为 `11:00/14:00/15:00`，120min 仍为 `11:30/15:00`，第一上午 bar 仍使用
`09:30.close` 作为 anchor。

本次正式写入边界固定如下：

| 项目 | 数量/口径 |
| --- | --- |
| 交易日 | 2 个：2016-10-10、2017-11-29 |
| 直接修复 Silver 行 | 21 |
| 重新生成派生行 | 10 |
| 目标文件 | 7 个，共 714 行、46,910 bytes（写前快照） |
| Tushare 写入请求 | 0；只使用已冻结并实测的修复合同 |
| staging/rollback | Lake 同文件系统；逐文件 staging，旧文件 hard-link 备份 |
| 停止条件 | active run、源/冻结值漂移、缺文件、校验失败、目标竞争或磁盘不足 |

执行必须复用正式 `silver_major_index_mins_update_job`，分区顺序固定为 2016 后 2017。
正式执行前把 7 个旧目标移入独立 rollback 根；任一 run 或 check 失败时立即按 manifest
恢复对应旧文件。两次 run 都成功后，必须完成 7 个目标文件逐行校验、全历史非正 OHLC
扫描、30->90 与 60->120 精确重算对账、Dagster materialization/check 归属和 active run
复核。修复不新增 asset/job/sensor/check，也不改变依赖矩阵。

### 14.1 正式执行与验收结果

本次修复已于 2026-08-08 按上述边界完成：

1. rollback manifest 和旧文件保存在
   `/Volumes/datasource/data_lake/_rollback/major_index_mins_zero_ohlc_repair_20260808`；
   写前 21 条 Raw/1min 源证据、7 个旧目标的行数、非正 OHLC 数、大小和 SHA-256 全部
   与冻结 preflight 一致。
2. `2016-10-10` 正式 run 为 `62c1b995-a6d8-429f-bf16-0804f78d8f82`，状态
   `SUCCESS`。只有 15min 使用 `staged_atomic_replace`，其它六频均为 `reuse_existing`；
   7 个 blocking check 全部通过。
3. `2017-11-29` 正式 run 为 `433c5ff2-d5e0-4aab-9743-b993730dc48c`，状态
   `SUCCESS`。5/15/30/60/90/120min 使用 `staged_atomic_replace`，1min 为
   `reuse_existing`；7 个 blocking check 全部通过。
4. 独立文件验收确认 7 个目标仍为 714 行，非正 OHLC 为 0；21 行替换价逐行匹配，
   `vol/amount/vwap` 与旧文件一致，未受影响的原生行双向 `EXCEPT ALL` 差异为 0。
5. 30min->90min、60min->120min 独立重算的双向差异均为 0；七个频率的 Silver
   全历史扫描均为 0 条非正 OHLC。
6. 为恢复 UI latest event 顺序，`2026-08-04` 运行
   `a68a0e26-27cb-486e-8b76-64bd1068e7b4` 成功；七频全部
   `reuse_existing`，7 个 blocking check 全部通过，七个资产的 latest materialization
   均回到 `2026-08-04`。
7. `2016-10-10`、`2017-11-29`、`2026-08-04` 三个日期的 Silver batch readiness
   全绿，共扫描 21 个文件；执行结束 active run 为 0。未修改 Raw、Prod、sensor 状态、
   asset/job/check 数量或依赖矩阵。
