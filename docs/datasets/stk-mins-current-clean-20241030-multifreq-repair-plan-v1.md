# stk_mins 当前错误 clean 2024-10-30 多频率混入 1min 专项修复方案 v1

状态：待评审
最近更新：2026-05-12
适用范围：当前错误 schema 的 `research/stk_mins_by_date_clean`

## 1. 本文定位

本文只服务第一阶段：

```text
在当前已经存在、但 schema 有问题的 clean 数据集上，把 2024-10-30 多频率混入 1min 的内容清洗流程跑完，并沉淀修复规则。
```

本文不是正式 clean 重建方案。

正式 clean 方案仍以后续 `raw_tushare/stk_mins_by_date -> research/stk_mins_by_date_clean` 重建方案为准。正式 clean 必须保留 `exchange/vwap`，不得写入物理列 `trade_date`。

原正确 schema 口径方案保留在：

```text
docs/datasets/stk-mins-clean-20241030-multifreq-repair-plan-v1.md
```

该文档不再为当前错误 clean 直接执行口径。

## 2. 当前 clean 事实

当前错误 clean 路径：

```text
/Volumes/datasource/goldenshare-tushare-lake/research/stk_mins_by_date_clean
```

当前错误 clean 物理 schema：

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

1. 缺少源业务字段 `exchange/vwap`。
2. 多了物理列 `trade_date`。
3. 因此当前 clean 不能作为最终正式 clean。

但当前阶段仍要继续把它的内容清洗流程跑完，目的是沉淀清洗规则，不是宣布它最终可用。

## 3. 问题背景

`2024-10-30` 这一天，当前错误 clean 中部分北交所股票在 `5/15/30/60` 分钟频率下出现 `bar_count=271`。

这个数量是 `1min` 当日包含盘后交易后的行数，不是 `5/15/30/60` 应有行数。

判断：

```text
2024-10-30 的部分 5/15/30/60 clean 分区混入了 1min 粒度数据。
```

本专项目标：

```text
只替换当前错误 clean 中受影响股票、受影响频率、受影响日期的错误行。
```

不允许覆盖同一分区中其他正常股票。

## 4. 影响范围

影响范围来自当前完备性问题账本：

```text
/Volumes/datasource/goldenshare-tushare-lake/manifest/stk_mins_quality/clean_completeness_issue_ledger.parquet
```

筛选条件：

```sql
trade_date = date '2024-10-30'
and freq in (5, 15, 30, 60)
and actual_value = 'bar_count=271'
```

当前统计：

| freq | 问题记录数 | 受影响股票数 | 修复后目标行数/股票 |
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

执行时必须按 `freq` 各自的问题清单处理，不能用 254 只股票的并集覆盖所有频率。

## 5. 修复边界

本专项只允许处理：

```text
research/stk_mins_by_date_clean/freq=5/trade_date=2024-10-30
research/stk_mins_by_date_clean/freq=15/trade_date=2024-10-30
research/stk_mins_by_date_clean/freq=30/trade_date=2024-10-30
research/stk_mins_by_date_clean/freq=60/trade_date=2024-10-30
```

本专项禁止处理：

```text
raw_tushare/stk_mins_by_date
derived/stk_mins_by_date
research/stk_mins_by_symbol_month
research/stk_mins_indicators_by_date
research/stk_mins_indicators_by_symbol_month
manifest/security_identity_map
其他日期
其他频率
其他数据集
```

## 6. 修复数据来源

第一阶段修复来源使用当前错误 clean 的同日 `1min`：

```text
research/stk_mins_by_date_clean/freq=1/trade_date=2024-10-30
```

已记录核验结果：

| 校验项 | 结果 |
| --- | --- |
| 受影响股票并集数量 | 254 |
| 当前 clean `1min` 每只股票总行数 | 271 |
| 当前 clean `1min` 每只股票常规时段行数 | 241 |
| 当前 clean `1min` 缺失或不足 271 的股票数 | 0 |
| 当前 clean `1min` 常规时段不足 241 的股票数 | 0 |

说明：

1. 当前 clean `1min` 也缺少 `exchange/vwap`，但本阶段不解决 schema。
2. 本阶段修复结果继续保持当前错误 clean 的 10 列 schema。
3. 本阶段不从 raw 构造正式 clean 修复源。

## 7. 时间窗口规则

当前 `1min` 当日包含盘后交易数据：

```text
09:30:00 ~ 11:30:00
13:01:00 ~ 15:00:00
15:01:00 ~ 15:30:00
```

本专项只使用常规日盘：

```text
09:30:00 ~ 11:30:00
13:01:00 ~ 15:00:00
```

不使用盘后交易：

```text
15:01:00 ~ 15:30:00
```

理由：当前 `5/15/30/60` clean 分区目标口径仍是常规日盘，不把盘后交易合入 `5/15/30/60`。

## 8. 输出 schema

本专项输出必须保持当前错误 clean 的物理 schema：

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

这只是第一阶段临时口径。

禁止在本专项里新增：

```text
exchange
vwap
identity_id
source_ts_code
```

说明：

1. `exchange/vwap` 缺失问题放到第二阶段正式 raw -> clean 重建解决。
2. 本专项如果写入 `exchange/vwap`，会导致当前 clean 同一数据集内出现混合 schema，风险更高。
3. `trade_date` 虽然最终不应作为物理列存在，但当前错误 clean 已经这样生成；第一阶段为了完成内容清洗演练，继续保持该 10 列 schema。

## 9. 聚合规则

字段生成规则：

| 字段 | 规则 |
| --- | --- |
| `ts_code` | 沿用当前 clean `1min` 的 `ts_code` |
| `freq` | 目标频率 |
| `trade_time` | 窗口内最后一根 `1min` 的 `trade_time` |
| `open` | 窗口内第一根 `1min` 的 `open` |
| `close` | 窗口内最后一根 `1min` 的 `close` |
| `high` | 窗口内 `high` 最大值 |
| `low` | 窗口内 `low` 最小值 |
| `vol` | 窗口内 `vol` 求和 |
| `amount` | 窗口内 `amount` 求和 |
| `trade_date` | `2024-10-30` |

### 9.1 5min 目标窗口

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

### 9.2 15min 目标窗口

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

### 9.3 30min 目标窗口

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

### 9.4 60min 目标窗口

目标总数：5。

窗口规则：

```text
09:30 单根保留为 09:30
09:31~10:30 聚合为 10:30
10:31~11:30 聚合为 11:30
13:01~14:00 聚合为 14:00
14:01~15:00 聚合为 15:00
```

## 10. 写入策略

本专项必须实现为显式 `dry-run/apply` 两阶段。

建议新增专项命令：

```bash
lake_console/.venv/bin/python -m lake_console.backend.app.cli repair-current-clean-20241030-multifreq --dry-run
lake_console/.venv/bin/python -m lake_console.backend.app.cli repair-current-clean-20241030-multifreq --apply
```

命令必须硬编码本专项边界：

```text
trade_date=2024-10-30
source_freq=1
target_freqs=5,15,30,60
source_layer=research/stk_mins_by_date_clean
target_layer=research/stk_mins_by_date_clean
schema_mode=current_wrong_clean_10_columns
affected_codes_source=clean_completeness_issue_ledger
```

禁止把它泛化成任意日期、任意频率的自由修复工具。

## 11. dry-run 行为

`dry-run` 只读，不写任何正式分区。

必须输出：

1. 每个 `freq` 的受影响股票数。
2. 每个 `freq` 的旧错误行数。
3. 每个 `freq` 的预计重建行数。
4. 每个 `freq` 的预计分区总行数变化。
5. 当前 clean `1min` 源数据是否满足每只股票 `271` 行、常规时段 `241` 行。
6. 当前 clean `1min` 是否存在重复 `(ts_code, freq, trade_time)`。
7. 是否存在无法生成目标窗口的股票。
8. 输出 schema 是否严格等于当前错误 clean 10 列 schema。

预计替换规模：

| freq | 旧错误行数 | 新重建行数 | 预计净减少 |
| --- | ---: | ---: | ---: |
| 5 | 68,563 | 12,397 | 56,166 |
| 15 | 68,834 | 4,318 | 64,516 |
| 30 | 68,834 | 2,286 | 66,548 |
| 60 | 68,834 | 1,270 | 67,564 |

## 12. apply 行为

每个目标频率独立处理：

1. 读取目标分区完整数据。
2. 从目标分区中删除该 `freq` 问题清单内股票的旧行。
3. 从当前 clean `1min` 重建该 `freq` 问题清单内股票的新行。
4. 合并“未受影响股票旧行 + 受影响股票新行”。
5. 以 `(ts_code, freq, trade_time)` 做唯一性校验。
6. 校验输出 schema 严格等于当前错误 clean 10 列 schema。
7. 写入 `_tmp/<run_id>/...`。
8. 校验临时输出文件。
9. 备份旧正式分区到 `_tmp/<run_id>/_backup/...`。
10. 原子替换正式分区。
11. 输出每个频率的写入摘要。

`apply` 过程中任一频率校验失败，必须停止，不能继续处理后续频率。

## 13. 必须通过的门禁

### G1. 问题清单门禁

必须确认问题清单只来自：

```sql
trade_date = date '2024-10-30'
and freq in (5, 15, 30, 60)
and actual_value = 'bar_count=271'
```

不得手工拼接股票清单。

### G2. `1min` 源数据门禁

每只受影响股票必须满足：

```text
freq=1 总行数 = 271
常规时段行数 = 241
无重复 (ts_code, freq, trade_time)
schema 等于当前错误 clean 10 列 schema
```

若任一股票不满足，专项必须停止，不允许部分修。

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

输出 schema 必须等于当前错误 clean 10 列 schema：

```text
ts_code, freq, trade_time, open, close, high, low, vol, amount, trade_date
```

禁止在本专项写入：

```text
exchange
vwap
identity_id
source_ts_code
```

### G6. 回归门禁

专项 apply 后必须执行分区直读校验，确认受影响股票不再是 `bar_count=271`。

旧账本不会因为修复自动消失，所以不能只看旧账本判断修复是否成功。真正确认应使用修复命令的分区直读校验，或重新运行完备性审计后生成新账本。

辅助查看旧账本原始问题清单：

```sql
select freq, latest_ts_code, actual_value
from read_parquet('/Volumes/datasource/goldenshare-tushare-lake/manifest/stk_mins_quality/clean_completeness_issue_ledger.parquet')
where trade_date = date '2024-10-30'
  and freq in (5,15,30,60)
  and actual_value = 'bar_count=271';
```

该 SQL 只能定位旧账本问题，不作为 apply 后成功依据。

## 14. 回滚方案

`apply` 必须把旧分区备份到：

```text
/Volumes/datasource/goldenshare-tushare-lake/_tmp/<run_id>/_backup/research/stk_mins_by_date_clean/freq=<freq>/trade_date=2024-10-30
```

如果 apply 后任一校验失败：

1. 停止后续动作。
2. 不进入 derived/research/indicator 重建。
3. 用备份目录恢复对应频率分区。
4. 重新执行本专项 dry-run。

## 15. 与正式 clean 方案的关系

本专项完成后，只表示：

```text
当前错误 schema clean 的 2024-10-30 多频率混入 1min 内容问题已完成演练式修复。
```

它不表示：

```text
clean schema 已正确
exchange/vwap 已恢复
trade_date 物理列已移除
derived/research/indicator 可以重建
```

正式 clean 仍必须在第二阶段从 raw 重新生成。
