# stk_mins clean 2024-10-30 多频率混入 1min 专项修复方案 v1

## 1. 状态

已按 `clean_next` 当前现实口径订正，并已执行本专项修复。

本文定义修复方案，并记录 2026-05-13 的实际执行结果。

2026-05-14 收口说明：

1. 本专项修复已经完成，后续不再保留可执行专项命令。
2. 历史 CLI 入口已从 `lake_console` 下线，本文只作为历史方案与执行记录。
3. 未来如需修复 `clean_next`，必须重新走当前标准链路：`raw` 变更 -> affected partition -> `CleanNextRefreshService` -> scoped audit -> gate -> indicator queue，不允许直接写 `clean_next` 分区。

2026-05-13 订正说明：

1. 当前正式 clean candidate 已经从 raw 全量构建到 `research/stk_mins_by_date_clean_next`。
2. `clean_next` 已通过 M4 基础审计，物理 schema 为正式 11 列。
3. M5 完备性账本确认 `2024-10-30` 多频率混入 `1min` 问题仍存在于 `clean_next`。
4. 因此本文执行目标从旧路径 `research/stk_mins_by_date_clean` 订正为 `research/stk_mins_by_date_clean_next`。
5. 本文不服务历史错误 schema clean；相关演练文档已删除，历史摘要见 `stk-mins-clean-cleaning-master-record-v1.md`。

本版已纠正早期草案中的错误 schema 口径：

1. `exchange` / `vwap` 是 `stk_mins` 源站业务字段，clean 层不得丢弃。
2. `trade_date` 只能来自 Hive 分区目录 `trade_date=YYYY-MM-DD`，不得作为 Parquet 物理列写入。
3. 本专项不得把历史错误 clean schema 当成目标 schema。

## 2. 问题背景

`research/stk_mins_by_date_clean_next` 的 `2024-10-30` 分区中，部分北交所股票在 `5/15/30/60` 分钟频率下出现 `bar_count=271`。

这个数量是 `1min` 当日包含盘后交易时段后的行数，不是 `5/15/30/60` 应有的行数。因此判断为：

```text
2024-10-30 的部分高频分区混入了 1min 粒度数据。
```

本专项目标是：

```text
只替换受影响股票、受影响频率、受影响日期的错误行。
```

不允许覆盖同一分区中其他正常股票的数据。

## 3. 真实影响范围

影响范围来自 `clean_next` 当前完备性问题账本：

```text
/Volumes/datasource/goldenshare-tushare-lake/manifest/stk_mins_quality/clean_next_completeness_issue_ledger.parquet
```

筛选条件：

```sql
trade_date = date '2024-10-30'
and freq in (5, 15, 30, 60)
and actual_value = 'bar_count=271'
```

当前统计：

| freq | 问题记录数 | 受影响股票数 | 目标行数/股票 |
| --- | ---: | ---: | ---: |
| 5 | 253 | 253 | 49 |
| 15 | 254 | 254 | 17 |
| 30 | 254 | 254 | 9 |
| 60 | 254 | 254 | 5 |

注意：

```text
freq=5 比其他频率少 1 只股票。
该差异股票为 920122.BJ。
```

所以执行时必须按 `freq` 各自的问题清单处理，不能简单用 254 只股票的并集覆盖所有频率。

## 4. 修复边界

本专项只允许处理：

```text
research/stk_mins_by_date_clean_next/freq=5/trade_date=2024-10-30
research/stk_mins_by_date_clean_next/freq=15/trade_date=2024-10-30
research/stk_mins_by_date_clean_next/freq=30/trade_date=2024-10-30
research/stk_mins_by_date_clean_next/freq=60/trade_date=2024-10-30
```

本专项禁止处理：

```text
raw_tushare/stk_mins_by_date
已删除的历史错误 clean 路径 research/stk_mins_by_date_clean
derived/stk_mins_by_date
research/stk_mins_by_symbol_month
research/stk_mins_indicators_by_date
research/stk_mins_indicators_by_symbol_month
manifest/security_identity_map
其他日期
其他频率
其他数据集
```

后续 derived / research / indicator 必须等 clean 层专项修复和审计通过后，再按独立步骤重建。

## 5. 修复数据来源

修复来源必须是 schema 正确的同日 `clean_next 1min` 数据。

目标字段口径必须与 raw `stk_mins` 源字段一致：

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
exchange
vwap
```

当前已经确认：`research/stk_mins_by_date_clean_next/freq=1/trade_date=2024-10-30` 物理 schema 正确，包含 `exchange/vwap`，且不包含物理列 `trade_date`。因此：

1. 本专项直接使用 `clean_next` 同日 `1min` 作为修复来源。
2. 本专项不得读取历史错误 schema 的 `research/stk_mins_by_date_clean` 作为来源。
3. 本专项不得直接回退读取 raw；如果 `clean_next 1min` 门禁失败，必须停止并先修复 `clean_next 1min`，不能在本专项里临时绕路。
4. 禁止因为历史错误 clean 缺字段，就在修复输出里继续丢弃 `exchange/vwap`。

目标来源路径：

```text
research/stk_mins_by_date_clean_next/freq=1/trade_date=2024-10-30
```

当前已核验：

| 校验项 | 结果 |
| --- | --- |
| `clean_next 1min` 物理字段 | `ts_code,freq,trade_time,open,close,high,low,vol,amount,exchange,vwap` |
| 受影响股票并集数量 | 254 |
| `clean_next 1min` 每只股票总行数 | 271 |
| `clean_next 1min` 每只股票常规时段行数 | 241 |
| `clean_next 1min` 缺失或不足 271 的股票数 | 0 |
| `clean_next 1min` 常规时段不足 241 的股票数 | 0 |

说明：

```text
1min 当日包含 15:01~15:30 盘后交易数据，所以总数为 271。
但当前 `clean_next` 高频分区的目标口径仍是常规交易时段，不把盘后交易合入 `5/15/30/60`。
```

因此本专项只使用：

```text
09:30:00 ~ 11:30:00
13:01:00 ~ 15:00:00
```

不使用：

```text
15:01:00 ~ 15:30:00
```

这是为了与当前 `5/15/30/60` clean 分区的既有口径一致。

## 6. 聚合规则

所有聚合输出必须生成 schema 正确的 clean 字段：

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
exchange
vwap
```

禁止新增行级字段，例如：

```text
identity_id
source_ts_code
trade_date
```

说明：

1. `identity_id` / `source_ts_code` 不进入分钟线事实行；股票身份映射只记录在 `security_identity_map` 账本。
2. `trade_date` 不进入 Parquet 物理列；它只由目录分区 `trade_date=2024-10-30` 表达。
3. `exchange` / `vwap` 必须保留。

字段生成规则：

| 字段 | 规则 |
| --- | --- |
| `ts_code` | 使用 clean 口径下的最新股票代码，不写旧代码 |
| `freq` | 目标频率 |
| `trade_time` | 窗口内最后一根 1min 的 `trade_time` |
| `open` | 窗口内第一根 1min 的 `open` |
| `close` | 窗口内最后一根 1min 的 `close` |
| `high` | 窗口内 `high` 最大值 |
| `low` | 窗口内 `low` 最小值 |
| `vol` | 窗口内 `vol` 求和 |
| `amount` | 窗口内 `amount` 求和 |
| `exchange` | 窗口内非空 `exchange` 必须唯一；若出现多个值，专项失败 |
| `vwap` | 单根窗口沿用源 `vwap`；多根窗口在 `vol > 0` 时按 `amount / vol` 计算；若 `vol = 0`，使用窗口最后一根 1min 的非空 `vwap`，若仍为空则专项失败 |

`vwap` 计算规则必须在 dry-run 中输出统计：

1. 使用源单根 `vwap` 的行数。
2. 使用 `amount / vol` 计算的行数。
3. 使用最后一根 1min `vwap` fallback 的行数。
4. 无法生成 `vwap` 的行数。

若无法生成 `vwap` 的行数大于 0，`apply` 禁止执行。

### 6.1 5min 目标窗口

目标总数：49。

窗口规则：

```text
09:30 单根保留为 09:30
09:31~09:35 聚合为 09:35
09:36~09:40 聚合为 09:40
...
11:26~11:30 聚合为 11:30
13:01~13:05 聚合为 13:05
...
14:56~15:00 聚合为 15:00
```

### 6.2 15min 目标窗口

目标总数：17。

窗口规则：

```text
09:30 单根保留为 09:30
09:31~09:45 聚合为 09:45
09:46~10:00 聚合为 10:00
...
11:16~11:30 聚合为 11:30
13:01~13:15 聚合为 13:15
...
14:46~15:00 聚合为 15:00
```

### 6.3 30min 目标窗口

目标总数：9。

窗口规则：

```text
09:30 单根保留为 09:30
09:31~10:00 聚合为 10:00
10:01~10:30 聚合为 10:30
10:31~11:00 聚合为 11:00
11:01~11:30 聚合为 11:30
13:01~13:30 聚合为 13:30
13:31~14:00 聚合为 14:00
14:01~14:30 聚合为 14:30
14:31~15:00 聚合为 15:00
```

### 6.4 60min 目标窗口

目标总数：5。

窗口规则：

```text
09:30 单根保留为 09:30
09:31~10:30 聚合为 10:30
10:31~11:30 聚合为 11:30
13:01~14:00 聚合为 14:00
14:01~15:00 聚合为 15:00
```

## 7. 写入策略

本专项历史执行时曾使用显式 `dry-run/apply` 两阶段命令。

该命令已在 2026-05-14 下线，本文不再提供可复制的执行入口。

命令必须硬编码本专项边界：

```text
trade_date=2024-10-30
source_freq=1
target_freqs=5,15,30,60
source_layer=research/stk_mins_by_date_clean_next/freq=1/trade_date=2024-10-30
target_layer=research/stk_mins_by_date_clean_next
affected_codes_source=clean_next_completeness_issue_ledger
```

`source_layer=research/stk_mins_by_date_clean_next/freq=1/trade_date=2024-10-30` 的含义：

1. 只使用 `clean_next` 的同日 `1min`。
2. 如果 `clean_next 1min` schema 或行数门禁失败，专项停止。
3. 不允许在本专项内读取旧错误 clean 或 raw 绕过门禁。

禁止把它泛化成任意日期、任意频率的自由修复工具。

### 7.1 dry-run 行为

`dry-run` 只读，不写任何正式分区。

必须输出：

1. 每个 `freq` 的受影响股票数。
2. 每个 `freq` 的旧错误行数。
3. 每个 `freq` 的预计重建行数。
4. 每个 `freq` 的预计分区总行数变化。
5. `clean_next 1min` 源数据是否满足每只股票 `271` 行、常规时段 `241` 行。
6. 修复源是否包含 `exchange/vwap`。
7. 是否存在重复 key。
8. 是否存在无法生成目标窗口的股票。
9. 是否存在无法生成 `exchange/vwap` 的目标行。

预计替换规模：

| freq | 旧错误行数 | 新重建行数 | 预计净减少 |
| --- | ---: | ---: | ---: |
| 5 | 68,563 | 12,397 | 56,166 |
| 15 | 68,834 | 4,318 | 64,516 |
| 30 | 68,834 | 2,286 | 66,548 |
| 60 | 68,834 | 1,270 | 67,564 |

### 7.2 apply 行为

每个目标频率独立处理：

1. 读取目标分区完整数据。
2. 从目标分区中删除该 `freq` 问题清单内股票的旧行。
3. 从 schema 正确的 `1min` 修复源重建该 `freq` 问题清单内股票的新行。
4. 合并“未受影响股票旧行 + 受影响股票新行”。
5. 以 `(ts_code, freq, trade_time)` 做唯一性校验。
6. 写入 `_tmp/<run_id>/...`。
7. 校验临时输出文件。
8. 备份旧正式分区到 `_tmp/<run_id>/_backup/...`。
9. 原子替换正式分区。
10. 输出每个频率的写入摘要。

`apply` 过程中任一频率校验失败，必须停止，不能继续处理后续频率。

## 8. 必须通过的门禁

### G1. 问题清单门禁

必须确认问题清单只来自：

```sql
trade_date = date '2024-10-30'
and freq in (5, 15, 30, 60)
and actual_value = 'bar_count=271'
```

不得手工拼接股票清单。

### G2. 1min 源数据门禁

每只受影响股票必须满足：

```text
freq=1 总行数 = 271
常规时段行数 = 241
无重复 (ts_code, freq, trade_time)
schema 包含 exchange/vwap
```

若任一股票不满足，专项必须停止，不允许部分修。

若 `clean_next 1min` 缺少 `exchange/vwap` 或出现额外物理字段，不得继续执行本专项；必须先修复 `clean_next 1min`。

### G3. 聚合结果门禁

每只受影响股票的重建结果必须满足：

```text
freq=5  -> 49 行
freq=15 -> 17 行
freq=30 -> 9 行
freq=60 -> 5 行
```

注意：`freq=5` 只处理 253 只，`15/30/60` 各处理 254 只。

### G4. 分区保护门禁

写入后必须确认：

```text
未受影响股票行数不变
受影响股票旧行完全删除
受影响股票新行数量正确
分区内无重复 (ts_code, freq, trade_time)
```

### G5. 字段门禁

输出 schema 必须等于 clean schema：

```text
ts_code, freq, trade_time, open, close, high, low, vol, amount, exchange, vwap
```

禁止写入任何额外字段。

特别禁止：

```text
trade_date
identity_id
source_ts_code
```

`trade_date` 只能通过分区目录表达：

```text
research/stk_mins_by_date_clean_next/freq=<freq>/trade_date=2024-10-30
```

### G6. 回归门禁

修复后至少执行 scoped audit：

```bash
lake_console/.venv/bin/python -m lake_console.backend.app.cli audit-stk-mins-clean-next-completeness --freqs 5,15,30,60 --start-date 2024-10-30 --end-date 2024-10-30 --sample-limit 20
lake_console/.venv/bin/python -m lake_console.backend.app.cli audit-stk-mins-by-date-clean-next --freqs 5,15,30,60 --start-date 2024-10-30 --end-date 2024-10-30
```

专项 apply 后必须执行分区直读校验，确认受影响股票不再是 `bar_count=271`。

旧账本不会因为修复自动消失，所以不能只看旧账本判断修复是否成功。真正确认应使用修复命令的分区直读校验，或重新运行完备性审计后生成新账本。

辅助查看旧账本残留可使用：

```sql
select freq, latest_ts_code, actual_value
from read_parquet('/Volumes/datasource/goldenshare-tushare-lake/manifest/stk_mins_quality/clean_next_completeness_issue_ledger.parquet')
where trade_date = date '2024-10-30'
  and freq in (5,15,30,60)
  and actual_value = 'bar_count=271';
```

这条 SQL 只能用于定位旧账本中原始问题清单，不作为 apply 后成功依据。

## 9. 回滚方案

`apply` 必须把旧分区备份到：

```text
/Volumes/datasource/goldenshare-tushare-lake/_tmp/<run_id>/_backup/research/stk_mins_by_date_clean_next/freq=<freq>/trade_date=2024-10-30
```

如果 apply 后任一校验失败：

1. 停止后续动作。
2. 不进入 derived/research/indicator 重建。
3. 用备份目录恢复对应频率分区。
4. 重新执行本专项 dry-run。

## 10. 不复用现有 repair-stk-mins-from-1m 的原因

现有 `repair-stk-mins-from-1m` 是历史源端缺口修复工具，当前不适合直接处理本专项：

1. 它只支持白名单内的历史 `5/15` 源端缺口日期。
2. 它不支持 `2024-10-30`。
3. 它不支持 `30/60`。
4. 它当前会把 `15:01~15:30` 视为非交易时段异常。
5. 它主要面向旧 raw 修补，不是 clean 专项分区替换。
6. 本专项必须额外满足当前文档定义的 clean schema 门禁、`vwap` 生成门禁和受影响股票清单门禁。

所以本专项历史执行时使用了一个边界更窄、门禁更强的 repair 实现。该实现已在专项完成后下线，避免继续绕过当前 `clean_next` 标准发布链路。

## 11. 执行顺序

历史执行顺序分三步：

1. 新增专项 dry-run 命令，只读输出影响范围与预计写入规模。
2. 运行 dry-run，确认所有门禁通过后再申请执行 apply。
3. 执行 apply 后，只做本专项聚焦校验，不顺手重建 derived/research/indicator。

## 12. 执行记录

执行时间：2026-05-13

执行说明：

历史执行时使用过本专项 repair 命令完成 `dry-run -> apply -> scoped audit`。该 repair 命令已下线，本文只保留结果摘要，不再保留可复制命令。

修复前 `dry-run` 结果：

| freq | 受影响股票数 | 旧错误行数 | 新重建行数 | 净减少 | `missing_vwap_rows` |
| --- | ---: | ---: | ---: | ---: | ---: |
| 5 | 253 | 68,563 | 12,397 | 56,166 | 0 |
| 15 | 254 | 68,834 | 4,318 | 64,516 | 0 |
| 30 | 254 | 68,834 | 2,286 | 66,548 | 0 |
| 60 | 254 | 68,834 | 1,270 | 67,564 | 0 |

`apply` 执行结果：

| freq | 替换前分区行数 | 替换后分区行数 | 重建行数 |
| --- | ---: | ---: | ---: |
| 5 | 316,944 | 260,778 | 12,397 |
| 15 | 155,007 | 90,491 | 4,318 |
| 30 | 114,446 | 47,898 | 2,286 |
| 60 | 94,179 | 26,615 | 1,270 |

执行 run_id：

```text
20260513T013935Z-repair-clean-next-20241030-multifreq
```

修复后复核：

1. 重跑专项 `dry-run` 后，四个频率的 `net_reduction` 均为 `0`，说明目标受影响股票已不再是 `bar_count=271` 污染行。
2. `audit-stk-mins-clean-next-completeness --freqs 5,15,30,60 --start-date 2024-10-30 --end-date 2024-10-30` 返回 `issue_count=0`。
3. `audit-stk-mins-by-date-clean-next --freqs 5,15,30,60 --start-date 2024-10-30 --end-date 2024-10-30` 返回 `issue_count=0`，schema 为正式 11 列：

```text
ts_code, freq, trade_time, open, close, high, low, vol, amount, exchange, vwap
```

本专项只修复 `research/stk_mins_by_date_clean_next` 的 `2024-10-30`、`5/15/30/60` 四个分区，未触碰：

```text
raw_tushare/stk_mins_by_date
已删除的历史错误 clean 路径 research/stk_mins_by_date_clean
derived/stk_mins_by_date
research/stk_mins_by_symbol_month
research/stk_mins_indicators_by_date
research/stk_mins_indicators_by_symbol_month
```

## 13. 下一步

继续处理 `clean_next` 完备性账本中剩余的 `missing_intraday_bar` 问题。下一专项是：

```text
2022 北交所 30min 缺失（bar_count=6）
```
