# stk_mins clean 2022 北交所 30min 缺失专项修复方案 v1

## 1. 状态

已按 `clean_next` 当前现实口径订正，并已执行 `dry-run -> apply -> scoped audit`。

本文既记录修复方案，也记录本次正式 `clean_next` 专项执行结果。

2026-05-13 订正说明：

1. 旧方案 `stk-mins-current-clean-2022-bj-freq30-repair-plan-v1.md` 只服务当前错误 schema 的 `research/stk_mins_by_date_clean`。
2. 当前正式 clean candidate 已经构建到 `research/stk_mins_by_date_clean_next`，物理 schema 为正式 11 列。
3. `clean_next` 完备性账本确认仍存在 `2022-07-15 ~ 2022-12-30` 的北交所 `30min` 缺失问题。
4. 因此本文是面向正式 `clean_next` 的新专项方案，不复用旧错误 clean 的命令与 schema 口径。

本文不是 derived、symbol-month、indicator 重建方案。后续 derived / research / indicator 必须等 clean 层专项修复和审计通过后，再按独立步骤重建。

## 2. 问题背景

`research/stk_mins_by_date_clean_next` 的 `2022-07-15 ~ 2022-12-30` 分区中，北交所股票在 `30min` 频率下出现 `bar_count=6`。

当前 `30min` 常规日盘口径应为：

```text
09:30
10:00
10:30
11:00
11:30
13:30
14:00
14:30
15:00
```

即每只股票每个完整交易日应为 `9` 根 `30min` bar。

`bar_count=6` 表示这批股票/日期的 `30min` 数据缺少部分日内 bar。根据上一阶段排查结论，这个问题应通过同日同股票的 `15min` clean 数据重建完整 `30min`，而不是从 raw 或源站重新拉取。

## 3. 真实影响范围

影响范围来自 `clean_next` 当前完备性问题账本：

```text
/Volumes/datasource/goldenshare-tushare-lake/manifest/stk_mins_quality/clean_next_completeness_issue_ledger.parquet
```

筛选条件：

```sql
trade_date between date '2022-07-15' and date '2022-12-30'
and freq = 30
and latest_ts_code like '%.BJ'
and issue_type = 'missing_intraday_bar'
and expected_value = 'bar_count>=9'
and actual_value = 'bar_count=6'
```

当前账本摘要：

| 问题类型 | freq | 数量 | 日期范围 |
| --- | ---: | ---: | --- |
| `missing_intraday_bar` | 30 | 13,568 | `2022-07-15 ~ 2022-12-30` |

执行时必须以账本筛出的 `(trade_date, latest_ts_code)` 组合为唯一影响清单，不允许手工拼接股票清单。

## 4. 修复边界

本专项只允许处理：

```text
research/stk_mins_by_date_clean_next/freq=30/trade_date=<2022-07-15~2022-12-30>
且仅限账本筛出的北交所受影响股票
```

本专项只允许读取：

```text
research/stk_mins_by_date_clean_next/freq=15/trade_date=<同一交易日>
```

本专项禁止处理：

```text
raw_tushare/stk_mins_by_date
research/stk_mins_by_date_clean
research/stk_mins_by_date_clean_next/freq=1
research/stk_mins_by_date_clean_next/freq=5
research/stk_mins_by_date_clean_next/freq=15 的正式分区写入
research/stk_mins_by_date_clean_next/freq=60
research/stk_mins_by_date_clean_next 非账本受影响股票
derived/stk_mins_by_date
research/stk_mins_by_symbol_month
research/stk_mins_indicators_by_date
research/stk_mins_indicators_by_symbol_month
manifest/security_identity_map
其他数据集
```

说明：

1. `15min` 只作为只读修复来源。
2. `30min` 只替换账本中受影响股票的旧行。
3. 同一 `30min` 分区中未受影响股票必须保持不变。

## 5. 独立命令

建议新增专项命令：

```bash
lake_console/.venv/bin/python -m lake_console.backend.app.cli repair-stk-mins-clean-next-2022-bj-freq30 --dry-run
lake_console/.venv/bin/python -m lake_console.backend.app.cli repair-stk-mins-clean-next-2022-bj-freq30 --apply
```

命令必须硬编码本专项边界：

```text
trade_date_range=2022-07-15~2022-12-30
source_freq=15
target_freq=30
source_layer=research/stk_mins_by_date_clean_next/freq=15
target_layer=research/stk_mins_by_date_clean_next/freq=30
affected_pairs_source=clean_next_completeness_issue_ledger
```

禁止把它泛化成任意日期、任意频率的自由修复工具。

## 6. 源数据与输出口径

### 6.1 源数据

源层固定为 schema 正确的同日同股票 `clean_next 15min`：

```text
research/stk_mins_by_date_clean_next/freq=15/trade_date=<YYYY-MM-DD>
```

源数据必须满足正式 clean schema：

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

如果 `clean_next 15min` schema 或行数门禁失败，专项必须停止，不能回退读取旧错误 clean 或 raw。

### 6.2 输出数据

目标层固定为同日同股票 `clean_next 30min`：

```text
research/stk_mins_by_date_clean_next/freq=30/trade_date=<YYYY-MM-DD>
```

输出 schema 必须严格等于正式 clean 11 列：

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

禁止写入任何额外字段：

```text
trade_date
identity_id
source_ts_code
```

`trade_date` 只能通过目录分区表达：

```text
research/stk_mins_by_date_clean_next/freq=30/trade_date=<YYYY-MM-DD>
```

## 7. 30min 重建规则

### 7.1 15min 源前置期望

每个受影响 `(trade_date, ts_code)` 的 `15min` 源行数必须为 `17`：

```text
09:30
09:45
10:00
10:15
10:30
10:45
11:00
11:15
11:30
13:15
13:30
13:45
14:00
14:15
14:30
14:45
15:00
```

### 7.2 30min 目标窗口

每个受影响 `(trade_date, ts_code)` 重建后必须为 `9` 行：

```text
1)  09:30           -> 单根保留为 09:30
2)  09:45 + 10:00   -> 聚合为 10:00
3)  10:15 + 10:30   -> 聚合为 10:30
4)  10:45 + 11:00   -> 聚合为 11:00
5)  11:15 + 11:30   -> 聚合为 11:30
6)  13:15 + 13:30   -> 聚合为 13:30
7)  13:45 + 14:00   -> 聚合为 14:00
8)  14:15 + 14:30   -> 聚合为 14:30
9)  14:45 + 15:00   -> 聚合为 15:00
```

本专项不使用盘后时段。原因是目标 `30min` clean 分区当前口径为常规交易时段。

### 7.3 字段聚合规则

| 字段 | 规则 |
| --- | --- |
| `ts_code` | 沿用 clean 口径下的最新股票代码 |
| `freq` | 固定写 `30` |
| `trade_time` | 窗口内最后一根 `15min` 的 `trade_time` |
| `open` | 窗口内第一根 `15min` 的 `open` |
| `close` | 窗口内最后一根 `15min` 的 `close` |
| `high` | 窗口内 `high` 最大值 |
| `low` | 窗口内 `low` 最小值 |
| `vol` | 窗口内 `vol` 求和 |
| `amount` | 窗口内 `amount` 求和 |
| `exchange` | 窗口内非空 `exchange` 必须唯一；若出现多个值，专项失败 |
| `vwap` | 单根窗口沿用源 `vwap`；多根窗口在 `vol > 0` 时按 `amount / vol` 计算；若 `vol = 0`，使用窗口最后一根 `15min` 的非空 `vwap`，若仍为空则专项失败 |

`vwap` 计算规则必须在 `dry-run` 中输出统计：

1. 使用源单根 `vwap` 的行数。
2. 使用 `amount / vol` 计算的行数。
3. 使用最后一根 `15min` `vwap` fallback 的行数。
4. 无法生成 `vwap` 的行数。

若无法生成 `vwap` 的行数大于 `0`，`apply` 禁止执行。

## 8. dry-run 行为

`--dry-run` 只读，不写任何正式分区。

必须输出：

1. 受影响交易日数量。
2. 受影响股票数量。
3. 受影响 `(trade_date, ts_code)` 组合数量。
4. 每个交易日旧 `30min` 受影响行数。
5. 每个交易日预计重建新行数。
6. 每个交易日预计分区总行数变化。
7. `clean_next 15min` 源数据是否满足每个组合 `17` 行。
8. `clean_next 15min` 是否存在重复 key。
9. 源和输出 schema 是否严格为正式 11 列。
10. 是否存在无法生成 `exchange/vwap` 的目标行。

若任一门禁失败，必须返回失败并列出样本，不进入 `apply`。

## 9. apply 行为

`--apply` 必须按交易日逐分区处理，且每个目标分区遵循：

1. 读取 `freq=30/trade_date=<YYYY-MM-DD>` 目标分区完整数据。
2. 删除该日受影响股票的旧 `30min` 行。
3. 基于同日同股票 `15min` 重建新 `30min` 行。
4. 合并“未受影响股票旧行 + 受影响股票新行”。
5. 校验：
   - 每个受影响组合重建后 `bar_count=9`；
   - 分区内 key 唯一 `(ts_code, freq, trade_time)`；
   - 输出 schema 严格等于正式 clean 11 列；
   - 不含 `trade_date/identity_id/source_ts_code` 物理列。
6. 写入 `_tmp/<run_id>/...`。
7. 校验临时输出文件。
8. 备份旧正式分区到 `_tmp/<run_id>/_backup/...`。
9. 原子替换正式分区。
10. 写后直读校验目标分区。

任一交易日校验失败，必须立即停止，禁止继续后续日期。

## 10. 门禁

### G1. 影响清单门禁

受影响清单必须来自 `clean_next_completeness_issue_ledger.parquet`，不允许手工股票列表。

### G2. 源数据门禁

受影响组合在 `clean_next 15min` 中必须满足：

```text
bar_count=17
key 唯一
schema 与正式 clean 11 列一致
```

### G3. 重建门禁

受影响组合重建后必须满足：

```text
bar_count=9
key 唯一
schema 与正式 clean 11 列一致
missing_vwap_rows=0
```

### G4. 分区保护门禁

```text
未受影响股票行数不变
受影响股票旧行完全删除
受影响股票新行数量正确
```

### G5. 字段门禁

输出 schema 必须等于：

```text
ts_code, freq, trade_time, open, close, high, low, vol, amount, exchange, vwap
```

特别禁止：

```text
trade_date
identity_id
source_ts_code
```

### G6. 回归门禁

执行前至少执行：

```bash
lake_console/.venv/bin/python -m lake_console.backend.app.cli repair-stk-mins-clean-next-2022-bj-freq30 --dry-run
```

修复后至少执行：

```bash
lake_console/.venv/bin/python -m lake_console.backend.app.cli audit-stk-mins-clean-next-completeness --freqs 30 --start-date 2022-07-15 --end-date 2022-12-30 --sample-limit 20
lake_console/.venv/bin/python -m lake_console.backend.app.cli audit-stk-mins-by-date-clean-next --freqs 30 --start-date 2022-07-15 --end-date 2022-12-30
```

旧账本不会因为修复自动消失，所以不能只看旧账本判断修复是否成功。真正确认应使用修复命令的分区直读校验，或重新运行完备性审计。

说明：

`repair-stk-mins-clean-next-2022-bj-freq30 --dry-run` 是修复前的只读预演命令。`apply` 完成后，目标分区已从 `bar_count=6` 修成 `bar_count=9`，旧账本仍保留历史问题清单，因此再次执行该修复命令的 `dry-run` 会触发“旧行数不是 6”的专项门禁。修复后的成功判定必须以 scoped audit 为准。

## 11. 回滚方案

`apply` 必须把旧分区备份到：

```text
/Volumes/datasource/goldenshare-tushare-lake/_tmp/<run_id>/_backup/research/stk_mins_by_date_clean_next/freq=30/trade_date=<YYYY-MM-DD>
```

如果 apply 后任一校验失败：

1. 停止后续动作。
2. 不进入 derived/research/indicator 重建。
3. 用备份目录恢复对应日期分区。
4. 重新执行本专项 `dry-run`。

## 12. 与旧 current-clean 方案的关系

旧方案：

```text
docs/datasets/stk-mins-current-clean-2022-bj-freq30-repair-plan-v1.md
```

只服务当前错误 schema clean，输出为错误 10 列：

```text
ts_code, freq, trade_time, open, close, high, low, vol, amount, trade_date
```

本文服务正式 `clean_next`，输出必须为正式 11 列：

```text
ts_code, freq, trade_time, open, close, high, low, vol, amount, exchange, vwap
```

两者不能混用。

## 13. 执行记录

### 2026-05-13 dry-run

执行命令：

```bash
lake_console/.venv/bin/python -m lake_console.backend.app.cli repair-stk-mins-clean-next-2022-bj-freq30 --dry-run
```

结果摘要：

```text
mode=dry_run
affected_trade_dates=115
affected_codes_total=13,568
affected_unique_codes=161
old_affected_rows_total=81,408
rebuilt_rows_total=122,112
target_rows_before_total=4,934,172
target_rows_after_total=4,974,876
net_reduction_total=-40,704
source_freq=15
target_freq=30
schema_mode=formal_clean_next_11_columns
missing_vwap_rows=0
write_intent=false
elapsed_seconds=105.737
```

解释：

`net_reduction_total=-40,704` 表示本专项不是删行，而是补行。每个受影响 `(trade_date, ts_code)` 从 6 根 `30min` 修为 9 根 `30min`，所以总行数增加。

### 2026-05-13 apply

执行命令：

```bash
lake_console/.venv/bin/python -m lake_console.backend.app.cli repair-stk-mins-clean-next-2022-bj-freq30 --apply
```

结果摘要：

```text
run_id=20260513T021617Z-repair-clean-next-2022-bj-freq30
mode=apply
affected_trade_dates=115
affected_codes_total=13,568
affected_unique_codes=161
old_affected_rows_total=81,408
rebuilt_rows_total=122,112
target_rows_before_total=4,934,172
target_rows_after_total=4,974,876
net_reduction_total=-40,704
source_freq=15
target_freq=30
schema_mode=formal_clean_next_11_columns
missing_vwap_rows=0
write_intent=true
elapsed_seconds=146.644
```

写入影响：

1. 只替换 `research/stk_mins_by_date_clean_next/freq=30/trade_date=2022-07-15~2022-12-30` 的 115 个交易日分区。
2. 每个分区只替换账本命中的北交所受影响股票行。
3. 未受影响股票行保留。
4. `freq=15` 只读，不写。
5. raw、旧错误 clean、derived、symbol-month、indicator 均未处理。

### 2026-05-13 修复后验证

完备性 scoped audit：

```bash
lake_console/.venv/bin/python -m lake_console.backend.app.cli audit-stk-mins-clean-next-completeness \
  --freqs 30 \
  --start-date 2022-07-15 \
  --end-date 2022-12-30 \
  --sample-limit 20
```

结果：

```text
operation=audit_stk_mins_clean_next_completeness
dataset_layer=research/stk_mins_by_date_clean_next
partitions=115
issue_count=0
issue_type_counts={}
status=success
write_intent=false
```

基础 scoped audit：

```bash
lake_console/.venv/bin/python -m lake_console.backend.app.cli audit-stk-mins-by-date-clean-next \
  --freqs 30 \
  --start-date 2022-07-15 \
  --end-date 2022-12-30
```

结果：

```text
operation=audit_stk_mins_by_date_clean_next
dataset_layer=research/stk_mins_by_date_clean_next
partitions=115
issue_count=0
issue_type_counts={}
schema=[
  ts_code,
  freq,
  trade_time,
  open,
  close,
  high,
  low,
  vol,
  amount,
  exchange,
  vwap
]
status=success
write_intent=false
```

结论：

本专项已完成。`2022-07-15 ~ 2022-12-30` 北交所 `30min bar_count=6` 问题在正式 `clean_next` 中已修复，修复后 scoped audit 未发现残留问题。

## 14. 下一步

回到 `stk_mins` 正式 clean_next 总行动计划，重新运行 M5 或至少运行剩余专项范围的完备性审计，确认是否还有其它未处理问题。
