# stk_mins clean 2024-10-30 多频率混入 1min 专项修复方案 v1

## 1. 状态

待评审。

本文只定义修复方案，不表示已经执行修复。

本版已纠正早期草案中的错误 schema 口径：

1. `exchange` / `vwap` 是 `stk_mins` 源站业务字段，clean 层不得丢弃。
2. `trade_date` 只能来自 Hive 分区目录 `trade_date=YYYY-MM-DD`，不得作为 Parquet 物理列写入。
3. 本专项不得把当前错误 clean schema 当成目标 schema。

## 2. 问题背景

`research/stk_mins_by_date_clean` 的 `2024-10-30` 分区中，部分北交所股票在 `5/15/30/60` 分钟频率下出现 `bar_count=271`。

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

后续 derived / research / indicator 必须等 clean 层专项修复和审计通过后，再按独立步骤重建。

## 5. 修复数据来源

修复来源必须是 schema 正确的同日 `1min` 数据。

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

当前已经确认：早期生成的 `research/stk_mins_by_date_clean` 物理 schema 存在缺陷，缺少 `exchange/vwap`，并额外写入了物理列 `trade_date`。因此：

1. 如果本专项在 clean schema 修正后执行，修复来源可以使用同日 schema 正确的 clean `1min`。
2. 如果本专项在 clean schema 修正前执行，不允许只读取当前 10 列 clean `1min` 作为唯一来源；必须从 raw `1min` 读取 `exchange/vwap`，并应用与 clean 一致的身份归一、过滤和去重规则，构造 schema 正确的 `1min` 修复源。
3. 禁止因为当前错误 clean 缺字段，就在修复输出里继续丢弃 `exchange/vwap`。

目标来源路径：

```text
research/stk_mins_by_date_clean/freq=1/trade_date=2024-10-30
```

若该路径仍为错误 schema，则必须回退到：

```text
raw_tushare/stk_mins_by_date/freq=1/trade_date=2024-10-30
```

并先经过 clean 规则转换后，才能作为本专项聚合来源。

当前已核验：

| 校验项 | 结果 |
| --- | --- |
| 受影响股票并集数量 | 254 |
| clean 1min 每只股票总行数 | 271 |
| clean 1min 每只股票常规时段行数 | 241 |
| clean 1min 缺失或不足 271 的股票数 | 0 |
| clean 1min 常规时段不足 241 的股票数 | 0 |

说明：

```text
1min 当日包含 15:01~15:30 盘后交易数据，所以总数为 271。
但当前 clean 高频分区的目标口径仍是常规交易时段，不把盘后交易合入 5/15/30/60。
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

本专项必须实现为显式 `dry-run/apply` 两阶段。

建议新增专项命令：

```bash
lake_console/.venv/bin/python -m lake_console.backend.app.cli repair-stk-mins-clean-20241030-multifreq --dry-run
lake_console/.venv/bin/python -m lake_console.backend.app.cli repair-stk-mins-clean-20241030-multifreq --apply
```

命令必须硬编码本专项边界：

```text
trade_date=2024-10-30
source_freq=1
target_freqs=5,15,30,60
source_layer=schema_correct_1min
target_layer=research/stk_mins_by_date_clean
affected_codes_source=clean_completeness_issue_ledger
```

`source_layer=schema_correct_1min` 的含义：

1. 优先使用 schema 正确的 `research/stk_mins_by_date_clean/freq=1/trade_date=2024-10-30`。
2. 如果当前 clean `1min` 仍缺 `exchange/vwap` 或仍包含物理 `trade_date`，必须使用 raw `1min` 构造修复源。
3. 构造 raw 修复源时，必须应用与 clean 一致的身份归一、退市/上市日前过滤、非法行过滤和去重规则。

禁止把它泛化成任意日期、任意频率的自由修复工具。

### 7.1 dry-run 行为

`dry-run` 只读，不写任何正式分区。

必须输出：

1. 每个 `freq` 的受影响股票数。
2. 每个 `freq` 的旧错误行数。
3. 每个 `freq` 的预计重建行数。
4. 每个 `freq` 的预计分区总行数变化。
5. clean `1min` 源数据是否满足每只股票 `271` 行、常规时段 `241` 行。
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

若当前 clean `1min` 缺少 `exchange/vwap`，不得继续以它作为唯一来源；必须先从 raw `1min` 构造 schema 正确的修复源。

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
research/stk_mins_by_date_clean/freq=<freq>/trade_date=2024-10-30
```

### G6. 回归门禁

修复后至少执行：

```bash
lake_console/.venv/bin/python -m lake_console.backend.app.cli repair-stk-mins-clean-20241030-multifreq --dry-run
```

专项 apply 后必须执行分区直读校验，确认受影响股票不再是 `bar_count=271`。

旧账本不会因为修复自动消失，所以不能只看旧账本判断修复是否成功。真正确认应使用修复命令的分区直读校验，或重新运行完备性审计后生成新账本。

辅助查看旧账本残留可使用：

```sql
select freq, latest_ts_code, actual_value
from read_parquet('/Volumes/datasource/goldenshare-tushare-lake/manifest/stk_mins_quality/clean_completeness_issue_ledger.parquet')
where trade_date = date '2024-10-30'
  and freq in (5,15,30,60)
  and actual_value = 'bar_count=271';
```

这条 SQL 只能用于定位旧账本中原始问题清单，不作为 apply 后成功依据。

## 9. 回滚方案

`apply` 必须把旧分区备份到：

```text
/Volumes/datasource/goldenshare-tushare-lake/_tmp/<run_id>/_backup/research/stk_mins_by_date_clean/freq=<freq>/trade_date=2024-10-30
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

所以本专项必须新增一个边界更窄、门禁更强的 repair 实现。

## 11. 执行顺序

建议分三步：

1. 新增专项 dry-run 命令，只读输出影响范围与预计写入规模。
2. 运行 dry-run，确认所有门禁通过后再申请执行 apply。
3. 执行 apply 后，只做本专项聚焦校验，不顺手重建 derived/research/indicator。

## 12. 下一步

本方案 review 通过后，才进入代码实现。

代码实现完成后，先跑 `dry-run` 并输出结果给 review，再决定是否执行 `apply`。
