# stk_mins clean 完备性审计排查记录 v1

状态：排查中
最近更新：2026-05-13
适用范围：本地 Lake `research/stk_mins_by_date_clean` 完备性审计结果排查

## 1. 背景

本记录用于沉淀 `stk_mins` clean 层完备性审计中已经确认过的事实、口径修正和专项处理清单，避免后续排查时重复判断或遗忘结论。

本轮只记录审计事实，不代表已经修复数据。

当前问题账本：

```text
/Volumes/datasource/goldenshare-tushare-lake/manifest/stk_mins_quality/clean_completeness_issue_ledger.parquet
```

审计对象：

```text
/Volumes/datasource/goldenshare-tushare-lake/research/stk_mins_by_date_clean
```

## 2. 原始审计结果

初次 clean 完备性审计发现问题总数：

```text
893,422
```

问题类型：

| issue_type | status | 含义 |
| --- | --- | --- |
| `extra_intraday_bar` | `failed` | 某股票某日某频率的 bar 数超过当前预期 |
| `missing_intraday_bar` | `needs_review` | 某股票某日某频率的 bar 数少于当前预期 |

## 3. 已确认口径修正：盘后交易

### 3.1 事实

A 股股票存在盘后交易，交易时间为 `15:00 ~ 15:30`。

因此某些频率的日内 bar 数比常规日盘预期更多，不应直接判定为数据错误。

### 3.2 当前排除规则

| freq | 常规日盘预期 | 盘后额外上限 | 可接受最大值 |
| --- | ---: | ---: | ---: |
| `1` | 241 | 30 | 271 |
| `5` | 49 | 6 | 55 |
| `15` | 17 | 2 | 19 |
| `30` | 9 | 1 | 10 |
| `60` | 5 | 1 | 6 |

### 3.3 排除后结果

```text
原始问题数：893,422
排除盘后交易后：22,111
```

结论：盘后交易解释了绝大多数 `extra_intraday_bar`。

## 4. 已确认专项一：2024-10-30 多频率混入 1min 数据

### 4.1 事实

`2024-10-30` 这一天，部分 `*.BJ` 股票的 `5/15/30/60` 分钟线分区中，实际 bar 数均为 `271`。

这不是盘后交易问题，而是高频率分区中混入了 1 分钟粒度数据。

### 4.2 问题规模

| trade_date | freq | expected_value | actual_value | count |
| --- | ---: | --- | --- | ---: |
| `2024-10-30` | 5 | `bar_count=49` | `bar_count=271` | 253 |
| `2024-10-30` | 15 | `bar_count=17` | `bar_count=271` | 254 |
| `2024-10-30` | 30 | `bar_count=9` | `bar_count=271` | 254 |
| `2024-10-30` | 60 | `bar_count=5` | `bar_count=271` | 254 |

### 4.3 处理口径

单独记录为专项：

```text
2024-10-30 多频率分区混入 1min 数据专项
```

建议后续处理：

1. 删除 clean 中 `2024-10-30` 对应股票的错误 `5/15/30/60` 行。
2. 基于同日 clean 层 `1min` 数据重新生成 `5/15/30/60`。
3. 修复完成后重新跑 clean 完备性审计。

专项清单导出文件：

```text
/tmp/stk_mins_2024-10-30_freq5_15_30_60_actual271_rebuild_from_1min.csv
```

### 4.4 排除后结果

```text
排除盘后交易后：22,111
再排除 2024-10-30 多频率混入 1min 专项后：21,096
```

### 4.5 执行状态（2026-05-13）

该专项已按独立命令执行完成：

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

分区直读复核：

```text
trade_date=2024-10-30
freq=5/15/30/60 下 bar_count=271 股票数均为 0
且每只股票 bar_count 分别为 49/17/9/5
```

## 5. 已确认专项二：2022 年北交所 30min 原始缺失

### 5.1 事实

`2022` 年一批 `*.BJ` 股票的 `30min` 数据存在系统性缺失。

典型表现：

```text
freq=30
expected_value=bar_count=9
actual_value=bar_count=6
```

这批数据被判断为原始 30min 数据本身不完整，需要基于同日 `15min` clean 数据重新生成 30min。

### 5.2 问题规模

| 范围 | 数量 |
| --- | ---: |
| 日期范围 | `2022-07-15 ~ 2022-12-30` |
| 涉及股票数 | 161 |
| 问题记录数 | 13,568 |

### 5.3 处理口径

单独记录为专项：

```text
2022 年北交所 30min 原始数据缺失专项
```

建议后续处理：

1. 不从 Tushare 重新请求这批 30min 数据作为第一选择。
2. 使用同日 `15min` clean 数据合成 30min。
3. 修复完成后重新跑 clean 完备性审计。

专项清单导出文件：

```text
/tmp/stk_mins_2022_bj_freq30_actual6_rebuild_from_15min.csv
```

### 5.4 排除后结果

```text
排除盘后交易：22,111
排除 2024-10-30 多频率混入 1min 专项：21,096
排除 2022 年北交所 30min 原始缺失专项：7,528
```

## 6. 已确认专项三：清洗误删 09:30 OHLC=0 bar

### 6.1 事实

部分股票在 `09:30:00` 的分钟 bar 中，OHLC 为 `0`。这不是无效数据，而是源站给出的集合竞价/开盘时点记录。

另有部分 `1min` 中间时点 bar 不是 OHLC 全 0，而是单个 OHLC 字段为 `0`，同时成交量或成交额不为 `0`。这类也不能直接按非法价格删除。

此前 clean 清洗规则把部分 OHLC 为 `0` 的 `09:30:00` bar 删除，导致高频数据出现缺一根的情况。

用户确认样例：

```text
300464.SZ
2015-06-16 09:30:00
freq=1/5/15/30/60 在 09:30:00 均应存在一条记录
```

只读验证样例：

```text
600988.SH
2011-12-12 09:34:00
raw 存在，clean 缺失
raw: open=9.35 close=9.36 high=9.36 low=0.0 vol=2800 amount=26200
```

结论：此前“任一 OHLC 为 0 就删除”的规则过粗，误删了部分有效 bar。

### 6.2 问题规模

在排除盘后交易、`2024-10-30` 多频率混入 1min、`2022` 年北交所 30min 原始缺失专项后，剩余 `7,528` 条问题。

其中：

| 分类 | 数量 | 处理判断 |
| --- | ---: | --- |
| 高频缺 `09:30:00`，且同日同股票 clean `1min 09:30:00` 存在 | 7,441 | 可用 `1min 09:30:00` 恢复高频 `5/15/30/60` |
| `freq=1` 自身缺 `09:30:00` | 5 | clean `1min` 无法自恢复，需查 raw 或源端 |
| 不缺 `09:30:00`，但 `1min` 当日少一根 | 82 | 不是 09:30 删除问题，需另查具体缺失时间点 |

按频率拆分：

| freq | 缺 `09:30:00` 数量 | clean `1min 09:30:00` 是否可作为恢复来源 |
| ---: | ---: | --- |
| 1 | 5 | 否 |
| 5 | 1,862 | 是 |
| 15 | 1,856 | 是 |
| 30 | 1,862 | 是 |
| 60 | 1,861 | 是 |

### 6.3 处理口径

单独记录为专项：

```text
清洗误删 09:30 OHLC=0 bar 专项
```

建议后续处理：

1. 不修改 raw。
2. 先调整 clean 清洗口径：`09:30:00` OHLC 为 `0` 不能直接判定为非法价格。
3. 对 `1min` 中间时点，若只是部分 OHLC 字段为 `0`，但成交量或成交额不为 `0`，也不能直接判定为非法价格。
4. 只有 OHLC 全 0 且成交量、成交额也无有效信息的记录，才应进入无效候选；具体规则仍需修复方案中明确。
5. 对 `5/15/30/60` 缺 `09:30:00` 且 clean `1min 09:30:00` 存在的记录，用同日同股票 `1min 09:30:00` 恢复对应高频 `09:30:00` bar。
6. `freq=1` 自身缺 `09:30:00` 的 5 条，需要查 raw 或源端，不能从 clean `1min` 自恢复。
7. 修复完成后重新跑 clean 完备性审计。

专项排查 CSV：

```text
/tmp/stk_mins_clean_missing_0930_with_1min_availability.csv
```

## 7. 当前仍未归类问题

排除以下已确认口径和专项后：

1. 盘后交易额外 bar。
2. `2024-10-30` 多频率混入 `1min`。
3. `2022` 年北交所 `30min` 原始缺失。
4. 高频缺 `09:30:00` 且可从 clean `1min 09:30:00` 恢复。

仍未归类的问题剩：

```text
87
```

结构：

| issue_type | status | freq | expected_value | actual_value | has_clean_0930 | count |
| --- | --- | ---: | --- | --- | --- | ---: |
| `missing_intraday_bar` | `needs_review` | 1 | `bar_count=241` | `bar_count=141` | 否 | 5 |
| `missing_intraday_bar` | `needs_review` | 1 | `bar_count=241` | `bar_count=240` | 是 | 82 |

说明：

1. 这 87 条都是 `1min` 问题。
2. 其中 5 条连 clean `1min 09:30:00` 都缺，需要查 raw 或源端。
3. 其中 82 条已有 clean `1min 09:30:00`，但当日仍少一根，需要继续定位缺失的是哪个具体时间点。

未归类问题 CSV：

```text
/tmp/stk_mins_clean_remaining_unresolved_after_known_cases.csv
```

## 8. 最新补查结果：未归类 `1min` 问题

### 8.1 `freq=1 actual=240` 的 82 条

对 `freq=1 actual=240` 的 82 条逐条定位缺失分钟点，并回查 raw `stk_mins_by_date` 后确认：

```text
82 条缺失分钟点在 raw 中均存在。
这 82 条都是 partial_ohlc_zero。
即：OHLC 中有单个字段为 0，但不是全 0，并且 vol/amount 有值。
```

这批属于 clean 误删，应纳入“部分 OHLC 为 0 但有成交量/成交额”的恢复专项。

排查 CSV 已覆盖 raw 字段：

```text
/tmp/stk_mins_clean_remaining_unresolved_after_known_cases.csv
/tmp/stk_mins_clean_remaining_unresolved_after_known_cases_with_raw_1min.csv
```

原始未补 raw 字段版本备份：

```text
/tmp/stk_mins_clean_remaining_unresolved_after_known_cases.original.csv
```

### 8.2 `freq=1 actual=141` 的 5 条

这 5 条展开后共有 `650` 个缺失分钟点。

排查结果：

```text
clean 缺失。
raw 也缺失。
```

因此这批不是 clean 清洗误删，需要从源站重新拉取 raw 或按单独源端缺失专项处理。

### 8.3 `920367.BJ 2023-09-07` 补拉验证

样例：

```text
920367.BJ
2023-09-07
freq=1
```

补拉前，本地 raw 只有：

```text
raw count=141
time range=13:10:00 ~ 15:30:00
```

补拉命令：

```bash
lake_console/.venv/bin/python -m lake_console.backend.app.cli sync-stk-mins-range \
  --ts-code 920367.BJ \
  --freq 1 \
  --start-date 2023-09-07 \
  --end-date 2023-09-07
```

补拉后，本地 raw 已完整：

```text
raw count=271
time range=09:30:00 ~ 15:30:00
日盘 missing_count=0
```

分段：

| session | count | range |
| --- | ---: | --- |
| morning | 121 | `09:30:00 ~ 11:30:00` |
| afternoon_regular | 120 | `13:01:00 ~ 15:00:00` |
| post_market | 30 | `15:01:00 ~ 15:30:00` |

但 clean 仍未更新：

```text
raw   271 rows
clean 141 rows
```

结论：raw 可通过单股票增量补拉修复；clean 需要后续单独从 raw 重建或修复对应分区。

## 9. 2026-05-12 clean `1min` 修复执行记录

本节记录已经执行过的 clean `1min` 修复，避免后续重复操作。

### 9.1 已修复：partial OHLC=0 单点

来源 CSV：

```text
/tmp/stk_mins_clean_remaining_unresolved_after_known_cases_with_raw_1min.csv
```

执行结果：

```text
partial_csv_rows_used=82
partial_rows_missing_after_repair=0
```

含义：82 个 raw 存在但 clean 误删的 `1min` 单点已经补回 clean。

### 9.2 已修复：raw 已补全的批量缺失股票日

以下 `1min` raw 已完整，且已写回 clean：

| ts_code | trade_date | clean 修复后数量 | 时间范围 |
| --- | --- | ---: | --- |
| `920367.BJ` | `2023-09-07` | 271 | `09:30:00 ~ 15:30:00` |
| `920826.BJ` | `2023-11-01` | 271 | `09:30:00 ~ 15:30:00` |
| `920694.BJ` | `2024-05-21` | 271 | `09:30:00 ~ 15:30:00` |
| `920806.BJ` | `2024-08-22` | 271 | `09:30:00 ~ 15:30:00` |

### 9.3 已修复：`920110.BJ 2024-10-17`

`920110.BJ` 在 `2024-10-17` 的 raw 后续已重新补全，并已从 raw 合并修复到 clean。

修复前状态：

```text
raw count=141
raw time range=13:10:00 ~ 15:30:00
clean count=141
clean time range=13:10:00 ~ 15:30:00
```

修复命令来源：

```text
raw 先通过 Tushare 单股票增量补拉完整。
clean 再从 raw 单股票合并修复。
```

修复后状态：

```text
raw count=271
clean count=271
time range=09:30:00 ~ 15:30:00
clean_day_missing_count=0
```

分段：

| session | count | range |
| --- | ---: | --- |
| morning | 121 | `09:30:00 ~ 11:30:00` |
| afternoon_regular | 120 | `13:01:00 ~ 15:00:00` |
| post_market | 30 | `15:01:00 ~ 15:30:00` |

修复摘要：

```text
run_id=20260512T134541Z-clean-single-symbol-repair
old_symbol_rows=141
new_symbol_rows=271
old_partition_rows=1,289,339
new_partition_rows=1,289,469
added_rows=130
```

### 9.4 修复后仍未解决清单状态

修复后重新扫描 `/tmp/stk_mins_clean_remaining_unresolved_after_known_cases_with_raw_1min.csv`，仍未解决：

```text
0 rows
```

最新清单：

```text
/tmp/stk_mins_clean_remaining_unresolved_after_920110_repair.csv
```

最新剩余清单：

```text
/tmp/stk_mins_clean_remaining_unresolved_after_repair.csv
```

本轮修复摘要：

```text
run_id=20260512T132809Z-clean-freq1-repair
partitions_written=25
total_repair_input_rows=1166
total_added_rows=602
partition_summary_csv=/tmp/20260512T132809Z-clean-freq1-repair_partition_summary.csv
```

## 10. 后续排查建议

下一步只建议继续做账本抽样分析，不直接修复：

1. 为 `09:30` 高频恢复设计从 `1min` 生成 `5/15/30/60` 的修复规则。
2. 为 `2022` 年北交所 `30min` 原始缺失专项设计从 `15min` 重建 `30min` 的规则。
3. 在修复规则明确前，不进入 derived/research/indicator 重建。

## 11. 查询与导出命令

### 11.1 查看当前账本总览

```bash
duckdb -c "
select issue_type, status, freq, expected_value, actual_value, count(*) as cnt
from read_parquet('/Volumes/datasource/goldenshare-tushare-lake/manifest/stk_mins_quality/clean_completeness_issue_ledger.parquet')
group by 1,2,3,4,5
order by issue_type, freq, cnt desc;
"
```

### 11.2 打开 09:30 专项排查 CSV

```bash
open /tmp/stk_mins_clean_missing_0930_with_1min_availability.csv
```

### 11.3 打开修复后仍未解决 CSV

```bash
open /tmp/stk_mins_clean_remaining_unresolved_after_920110_repair.csv
```

### 11.4 打开当前仍未归类问题 CSV

```bash
open /tmp/stk_mins_clean_remaining_unresolved_after_known_cases.csv
```

### 11.5 导出排除前三类已确认项后的剩余问题

```bash
duckdb -c "
copy (
  with ledger as (
    select
      *,
      cast(regexp_extract(expected_value, 'bar_count=([0-9]+)', 1) as integer) as expected_count,
      cast(regexp_extract(actual_value, 'bar_count=([0-9]+)', 1) as integer) as actual_count
    from read_parquet('/Volumes/datasource/goldenshare-tushare-lake/manifest/stk_mins_quality/clean_completeness_issue_ledger.parquet')
  ),
  rules as (
    select *
    from (values
      (1, 30),
      (5, 6),
      (15, 2),
      (30, 1),
      (60, 1)
    ) as t(freq, after_hours_extra_bars)
  ),
  marked as (
    select
      l.*,
      r.after_hours_extra_bars,
      case
        when l.issue_type = 'extra_intraday_bar'
         and l.actual_count > l.expected_count
         and l.actual_count <= l.expected_count + r.after_hours_extra_bars
        then true
        else false
      end as is_after_hours_extra,
      case
        when l.trade_date = date '2024-10-30'
         and l.actual_value = 'bar_count=271'
         and l.freq in (5,15,30,60)
        then true
        else false
      end as is_20241030_multifreq_1min_mixed,
      case
        when l.trade_date between date '2022-01-01' and date '2022-12-31'
         and l.latest_ts_code like '%.BJ'
         and l.freq = 30
         and l.expected_value = 'bar_count=9'
         and l.actual_value = 'bar_count=6'
        then true
        else false
      end as is_2022_bj_freq30_from_15min
    from ledger l
    left join rules r using (freq)
  )
  select *
  from marked
  where not is_after_hours_extra
    and not is_20241030_multifreq_1min_mixed
    and not is_2022_bj_freq30_from_15min
  order by issue_type, freq, actual_count desc, trade_date, latest_ts_code
) to '/tmp/stk_mins_clean_remaining_after_known_cases.csv'
with (header, delimiter ',');
"
```

打开：

```bash
open /tmp/stk_mins_clean_remaining_after_known_cases.csv
```
