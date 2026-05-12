# stk_mins clean 数据清洗总记录 v1

状态：待评审
最近更新：2026-05-13
适用范围：本地 Lake `stk_mins` 当前错误 schema clean 数据集的清洗流程沉淀

## 1. 本文定位

本文记录 `stk_mins` 从 raw 到 clean 相关的已执行动作、已产生产物、当前数据结构、遗留问题和后续清洗顺序。

当前决策分两阶段：

1. 第一阶段：继续把当前这份错误 schema 的 `research/stk_mins_by_date_clean` 按既有清洗记录中的遗留项清理完。该阶段目标不是让它成为最终正式数据，而是把清洗流程跑通，沉淀问题分类、专项修复、复查和记录方法。
2. 第二阶段：第一阶段完成后，再从 `raw_tushare/stk_mins_by_date` 重新生成正式 clean。正式 clean 必须保留 `exchange/vwap`，不得写入物理列 `trade_date`。

本文同时记录已执行修复动作与剩余待执行项，以作为第一阶段清洗总账本。

## 2. 相关文档

| 文档 | 用途 |
| --- | --- |
| [工程风险登记簿](/Users/congming/github/goldenshare/docs/governance/engineering-risk-register.md) | P0 风险与两阶段处理策略 |
| [股票历史分钟行情 Parquet Lake 方案 v1](/Users/congming/github/goldenshare/docs/datasets/stk-mins-parquet-lake-plan-v1.md) | `stk_mins` Lake 总体存储方案 |
| [stk_mins clean / audit 门禁流程图 v1（HTML）](/Users/congming/github/goldenshare/docs/datasets/stk-mins-clean-audit-gates-v1.html) | clean 与审计门禁流程图 |
| [stk_mins clean 完备性审计排查记录 v1](/Users/congming/github/goldenshare/docs/datasets/stk-mins-clean-completeness-investigation-notes-v1.md) | 已发现问题、排查结论、已修复记录 |
| [stk_mins clean 2024-10-30 多频率混入 1min 专项修复方案 v1](/Users/congming/github/goldenshare/docs/datasets/stk-mins-clean-20241030-multifreq-repair-plan-v1.md) | `2024-10-30` 多频率混入 `1min` 专项方案 |
| [股票分钟线 MACD v2 重算与增量可靠性方案](/Users/congming/github/goldenshare/docs/datasets/stk-mins-macd-v2-recompute-and-incremental-plan.md) | 指标依赖 clean 前置条件 |
| [股票历史分钟行情存储瘦身方案 v1](/Users/congming/github/goldenshare/docs/datasets/stk-mins-storage-slimming-plan-v1.md) | 分钟线字段与存储优化背景 |

## 3. 数据位置与文件结构

Lake root：

```text
/Volumes/datasource/goldenshare-tushare-lake
```

当前涉及路径：

| 层 | 路径 | 当前用途 |
| --- | --- | --- |
| raw | `raw_tushare/stk_mins_by_date/freq=<freq>/trade_date=<YYYY-MM-DD>/*.parquet` | 源站分钟线事实，保留 Tushare 字段 |
| clean 当前副本 | `research/stk_mins_by_date_clean/freq=<freq>/trade_date=<YYYY-MM-DD>/*.parquet` | 当前错误 schema clean，第一阶段继续用于清洗流程沉淀 |
| identity map | `manifest/security_identity/security_identity_map.parquet` | 记录旧代码到最新代码的身份映射账本 |
| 完备性问题账本 | `manifest/stk_mins_quality/clean_completeness_issue_ledger.parquet` | G6 完备性审计问题账本 |
| raw 恢复备份 | `_recovery/<run_id>/...` | raw 事故恢复备份与恢复证据 |
| clean 修复临时目录 | `_tmp/<run_id>/...` | clean 专项修复的临时输出与备份位置 |

注意：

1. 第一阶段不修改 raw。
2. 第一阶段不重建 `derived/stk_mins_by_date`。
3. 第一阶段不重建 `research/stk_mins_by_symbol_month`。
4. 第一阶段不重建技术指标。

## 4. 字段结构

### 4.1 raw 物理 schema

当前抽样核验的 raw parquet 物理列：

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

字段含义：

| 字段 | 含义 |
| --- | --- |
| `ts_code` | 股票代码 |
| `freq` | 分钟频率，当前支持 `1/5/15/30/60` |
| `trade_time` | 分钟 bar 时间戳 |
| `open` | 开盘价 |
| `close` | 收盘价 |
| `high` | 最高价 |
| `low` | 最低价 |
| `vol` | 成交量 |
| `amount` | 成交额 |
| `exchange` | 交易所代码 |
| `vwap` | 成交均价 |

### 4.2 当前错误 clean 物理 schema

当前错误 clean 抽样核验的物理列：

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

已确认问题：

1. 缺失源业务字段 `exchange/vwap`。
2. 额外写入物理列 `trade_date`。
3. 该 clean 不能作为最终正式 clean。

### 4.3 第二阶段正式 clean 目标 schema

正式 clean 应使用与 raw 源业务字段一致的物理列：

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

正式 clean 禁止写入以下物理列：

```text
trade_date
identity_id
source_ts_code
```

`trade_date` 只通过目录分区表达：

```text
research/stk_mins_by_date_clean/freq=<freq>/trade_date=<YYYY-MM-DD>
```

## 5. 已执行动作与产物

本节只记录已有文档明确写出的动作和产物。未保留完整命令的动作，不补造命令。

### 5.1 raw 事故恢复与单股票补数安全修复

背景：旧单股票补数路径曾把 raw 全市场分区覆盖成单股票分区。

已记录动作：

1. 新增只读审计命令 `audit-stk-mins-raw-integrity`。
2. 新增恢复命令 `recover-stk-mins-raw-from-research --dry-run/--apply`。
3. 完成 raw 事故恢复：
   - `freq=5`：恢复 `2010-08-27 ~ 2011-08-05` 中 `227` 个严重低行数分区。
   - `freq=1`：恢复 `2010-08-27 ~ 2025-02-14` 中 `3508` 个严重低行数分区。
   - 合计恢复严重低行数分区：`3735`。
4. 后续单股票补数路径已改为 merge 语义：只替换指定 `ts_code` 行，不覆盖同分区其他股票。

相关记录：

```text
docs/governance/engineering-risk-register.md
RISK-2026-05-11-007
```

### 5.2 clean 初始副本与身份映射

已执行 clean bootstrap：

```bash
lake_console/.venv/bin/python -m lake_console.backend.app.cli bootstrap-stk-mins-by-date-clean \
  --apply \
  --freqs 1,5,15,30,60
```

产物：

```text
research/stk_mins_by_date_clean
```

记录结果：

```text
分区数：21045
文件数：21637
行数：4576237808
```

说明：

```text
该动作只是 raw -> clean 的完整副本初始化，不做清洗，不修改 raw。
```

已执行身份映射构建：

```bash
lake_console/.venv/bin/python -m lake_console.backend.app.cli build-stk-mins-security-identity-map \
  --apply \
  --sample-limit 5
```

产物：

```text
manifest/security_identity/security_identity_map.parquet
```

记录结果：

```text
source code 映射：6089 条
identity：5837 个
当前无 identity 冲突
规则覆盖 stock_basic、bse_mapping、可唯一推断的 namechange 映射
```

### 5.3 clean 样本审计与 dry-run

已记录的小窗口验证命令：

```bash
lake_console/.venv/bin/python -m lake_console.backend.app.cli bootstrap-stk-mins-by-date-clean \
  --dry-run \
  --freqs 1 \
  --start-date 2026-04-24 \
  --end-date 2026-04-24

lake_console/.venv/bin/python -m lake_console.backend.app.cli build-stk-mins-security-identity-map \
  --dry-run \
  --sample-limit 5

lake_console/.venv/bin/python -m lake_console.backend.app.cli rebuild-stk-mins-by-date-clean-range \
  --dry-run \
  --freqs 1 \
  --start-date 2026-04-24 \
  --end-date 2026-04-24
```

已记录审计结果：

```text
2010-07-30 freq=1:
  当前 clean 副本审计结果：needs_rebuild
  原因：invalid_price=241
  dry-run rebuild 预计保留：455731 行
  dry-run rebuild 预计过滤：241 行

2026-04-24 freq=1:
  dry-run rebuild 预计保留：1326946 行
  dry-run rebuild 预计过滤：0 行
```

### 5.4 clean 完备性审计与问题账本

问题账本：

```text
manifest/stk_mins_quality/clean_completeness_issue_ledger.parquet
```

当前可复查命令入口：

```bash
lake_console/.venv/bin/python -m lake_console.backend.app.cli audit-stk-mins-clean-completeness \
  --freqs 1,5,15,30,60 \
  --write-ledger
```

初次完备性审计记录：

```text
问题总数：893422
```

问题类型：

| issue_type | status | 含义 |
| --- | --- | --- |
| `extra_intraday_bar` | `failed` | 某股票某日某频率 bar 数超过当前预期 |
| `missing_intraday_bar` | `needs_review` | 某股票某日某频率 bar 数少于当前预期 |

盘后交易口径修正后：

```text
原始问题数：893422
排除盘后交易后：22111
```

### 5.5 已完成的 `1min` 修复

已修复：`partial OHLC=0` 单点。

来源 CSV：

```text
/tmp/stk_mins_clean_remaining_unresolved_after_known_cases_with_raw_1min.csv
```

记录结果：

```text
partial_csv_rows_used=82
partial_rows_missing_after_repair=0
```

已修复：raw 已补全的批量缺失股票日。

| ts_code | trade_date | clean 修复后数量 | 时间范围 |
| --- | --- | ---: | --- |
| `920367.BJ` | `2023-09-07` | 271 | `09:30:00 ~ 15:30:00` |
| `920826.BJ` | `2023-11-01` | 271 | `09:30:00 ~ 15:30:00` |
| `920694.BJ` | `2024-05-21` | 271 | `09:30:00 ~ 15:30:00` |
| `920806.BJ` | `2024-08-22` | 271 | `09:30:00 ~ 15:30:00` |
| `920110.BJ` | `2024-10-17` | 271 | `09:30:00 ~ 15:30:00` |

记录到的修复 run：

```text
run_id=20260512T132809Z-clean-freq1-repair
partitions_written=25
total_repair_input_rows=1166
total_added_rows=602
partition_summary_csv=/tmp/20260512T132809Z-clean-freq1-repair_partition_summary.csv
```

`920110.BJ 2024-10-17` 单独修复记录：

```text
run_id=20260512T134541Z-clean-single-symbol-repair
old_symbol_rows=141
new_symbol_rows=271
old_partition_rows=1289339
new_partition_rows=1289469
added_rows=130
```

修复后未解决清单：

```text
0 rows
```

相关 CSV：

```text
/tmp/stk_mins_clean_remaining_unresolved_after_920110_repair.csv
/tmp/stk_mins_clean_remaining_unresolved_after_repair.csv
```

## 6. 已确认但不需要修复的口径

### 6.1 盘后交易

A 股存在盘后交易，交易时间为：

```text
15:00 ~ 15:30
```

因此某些频率的日内 bar 数比常规日盘预期更多，不直接判定为错误。

| freq | 常规日盘预期 | 盘后额外上限 | 可接受最大值 |
| --- | ---: | ---: | ---: |
| `1` | 241 | 30 | 271 |
| `5` | 49 | 6 | 55 |
| `15` | 17 | 2 | 19 |
| `30` | 9 | 1 | 10 |
| `60` | 5 | 1 | 6 |

### 6.2 `2024-10-30` 多频率混入 `1min` 专项（已执行）

执行命令：

```bash
lake_console/.venv/bin/python -m lake_console.backend.app.cli repair-current-clean-20241030-multifreq --dry-run
lake_console/.venv/bin/python -m lake_console.backend.app.cli repair-current-clean-20241030-multifreq --apply
```

执行结果摘要：

```text
run_id=20260512T161417Z-repair-current-clean-20241030-multifreq
freq=5:  old_affected_rows=68563 -> rebuilt_rows=12397
freq=15: old_affected_rows=68834 -> rebuilt_rows=4318
freq=30: old_affected_rows=68834 -> rebuilt_rows=2286
freq=60: old_affected_rows=68834 -> rebuilt_rows=1270
```

修复后分区直读复核：

```text
trade_date=2024-10-30
freq=5/15/30/60 下 bar_count=271 股票数均为 0
且每只股票 bar_count 分别为 49/17/9/5
```

## 7. 第一阶段剩余清洗项

第一阶段只处理当前错误 schema clean 的内容清洗流程沉淀，不解决最终 schema。

### 7.1 高频缺 `09:30:00` bar

问题规模：

| freq | 数量 | 恢复来源 |
| ---: | ---: | --- |
| 5 | 1862 | 同日同股票 clean `1min 09:30:00` |
| 15 | 1856 | 同日同股票 clean `1min 09:30:00` |
| 30 | 1862 | 同日同股票 clean `1min 09:30:00` |
| 60 | 1861 | 同日同股票 clean `1min 09:30:00` |

处理方向：

1. 不修改 raw。
2. 不处理 `freq=1`。
3. 只恢复高频缺失的 `09:30:00` bar。
4. 修复后重跑 clean 完备性审计。

专项排查 CSV：

```text
/tmp/stk_mins_clean_missing_0930_with_1min_availability.csv
```

### 7.2 `2022` 年北交所 `30min` 原始缺失

问题规模：

| 范围 | 数量 |
| --- | ---: |
| 日期范围 | `2022-07-15 ~ 2022-12-30` |
| 涉及股票数 | 161 |
| 问题记录数 | 13568 |

典型表现：

```text
freq=30
expected_value=bar_count=9
actual_value=bar_count=6
```

处理方向：

1. 不优先重新请求 Tushare `30min`。
2. 使用同日 clean `15min` 合成 `30min`。
3. 只处理问题清单内的北交所股票和日期。
4. 修复后重跑 clean 完备性审计。

专项清单：

```text
/tmp/stk_mins_2022_bj_freq30_actual6_rebuild_from_15min.csv
```

专项方案：

```text
docs/datasets/stk-mins-current-clean-2022-bj-freq30-repair-plan-v1.md
```

## 8. 禁止事项

第一阶段禁止：

1. 修改 raw。
2. 重建 derived。
3. 重建 research by symbol month。
4. 重建技术指标。
5. 把当前错误 schema clean 作为正式 clean 对外宣称。
6. 在未 dry-run 和未获得用户确认前执行 apply。
7. 在文档中把没有记录的历史命令补造成已执行事实。

## 9. 后续执行顺序建议

建议按以下顺序继续：

1. 高频缺 `09:30:00` bar 专项：先出方案或 dry-run 只读统计，再确认是否 apply。
2. `2022` 年北交所 `30min` 原始缺失专项：先出专项方案，再 dry-run。
3. 两个专项完成后，重跑 clean 完备性审计，更新本总记录与排查记录。
4. 用户确认第一阶段收尾后，再进入第二阶段正式 raw -> clean 重建方案评审。

## 10. 当前未解决的问题

1. 当前 clean schema 仍然错误，缺 `exchange/vwap`，多物理 `trade_date`。
2. 当前错误 clean 即使完成内容清洗，也不能作为最终正式 clean。
3. 正式 raw -> clean 重建方案尚未重新评审。
4. derived/research/indicator 必须等待正式 clean 完成后再重建。
