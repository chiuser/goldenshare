# stk_mins 当前错误 clean 缺失 09:30 bar 专项修复方案 v1

状态：待评审  
最近更新：2026-05-13  
适用范围：当前错误 schema 的 `research/stk_mins_by_date_clean`

## 1. 本文定位

本文只服务第一阶段当前错误 clean 的专项修复：

```text
对“高频 5/15/30/60 缺失 09:30 bar”的问题，
严格按指定 CSV 清单恢复 09:30 行，并且只改命中的股票/频率/日期。
```

本文不是正式 clean 重建方案。

正式 clean 仍以后续 `raw_tushare/stk_mins_by_date -> research/stk_mins_by_date_clean` 重建方案为准；正式 clean 必须保留 `exchange/vwap`，不得写入物理列 `trade_date`。

## 2. 本次唯一输入清单（强约束）

本专项唯一允许的输入清单：

```text
/tmp/stk_mins_clean_missing_0930_with_1min_availability.csv
```

执行时只能使用该文件，不允许改用其他账本/临时 CSV/手工列表。

清单筛选条件固定为：

```text
issue_type = missing_intraday_bar
action = repair_required
freq in (5,15,30,60)
has_clean_1min_0930 = true
```

从该清单得到 `(trade_date, freq, latest_ts_code)` 作为修复目标集合。

## 3. 修复边界

本专项只允许处理：

```text
research/stk_mins_by_date_clean/freq in (5,15,30,60)
且 trade_date / ts_code 必须命中“指定 CSV 清单”
```

本专项禁止处理：

```text
raw_tushare/stk_mins_by_date
research/stk_mins_by_date_clean/freq=1
research/stk_mins_by_date_clean 非清单股票
derived/research/indicator 各层
manifest/security_identity_map
其他数据集
```

## 4. 独立命令（红线）

本专项必须使用独立命令，不得复用或混入其他命令：

```bash
lake_console/.venv/bin/python -m lake_console.backend.app.cli repair-current-clean-missing-0930 --dry-run
lake_console/.venv/bin/python -m lake_console.backend.app.cli repair-current-clean-missing-0930 --apply
```

命令必须硬编码本专项输入 CSV 路径与筛选规则，不提供任意日期/任意频率/任意股票自由参数。

## 5. 源数据与输出口径（当前错误 clean）

### 5.1 源数据

源层固定为当前错误 clean 的同日同股票 `1min` 分区：

```text
research/stk_mins_by_date_clean/freq=1/trade_date=<YYYY-MM-DD>
```

每个目标股票必须在源层存在且只存在一条：

```text
trade_time = <trade_date> 09:30:00
```

### 5.2 目标数据

目标层固定为当前错误 clean 的高频分区：

```text
research/stk_mins_by_date_clean/freq=<5|15|30|60>/trade_date=<YYYY-MM-DD>
```

恢复动作是“补 09:30 一条行”，不是重建整天全部 bar。

### 5.3 输出 schema（保持当前错误 clean 口径）

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

禁止在本专项写入：

```text
exchange
vwap
identity_id
source_ts_code
```

## 6. 恢复规则

对每个清单命中项 `(trade_date, target_freq, ts_code)`：

1. 从 `freq=1` 同日同股票读取 `09:30:00` 源行。
2. 构造目标行：
   - `ts_code`：同源
   - `freq`：写目标频率 `5/15/30/60`
   - `trade_time`：同日 `09:30:00`
   - `open/close/high/low/vol/amount`：直接拷贝源 `1min 09:30` 数值
   - `trade_date`：分区日期
3. 写入前先查目标分区：
   - 若该股票 `09:30` 已存在，则标记 `already_present`，不重复写；
   - 若缺失，则追加该行。

## 7. 校验门禁

### G1. 输入清单门禁

只接受 `/tmp/stk_mins_clean_missing_0930_with_1min_availability.csv`，并且仅处理筛选条件命中的行。

### G2. 源行门禁

每个目标股票必须满足：

```text
freq=1 同日 09:30 行存在且唯一（count=1）
```

不满足则该条失败并终止 apply（fail-fast）。

### G3. 目标唯一键门禁

写入前后分区都必须保持唯一键：

```text
(ts_code, freq, trade_time)
```

### G4. 写入保护门禁

只允许对清单命中股票补 09:30 行，不得影响同分区其他股票既有行。

### G5. 幂等门禁

连续两次执行：

```text
第一次 apply 有实际新增；
第二次 dry-run / apply 应显示 net_change=0（仅 already_present）。
```

## 8. dry-run / apply 输出要求

### dry-run 输出

至少输出：

1. 输入清单总行数、命中修复目标行数。
2. 按频率、按日期的计划修复数量。
3. `source_missing` / `source_duplicate` / `already_present` / `to_insert` 统计。
4. 每个分区写入前后行数变化（预测值）。

### apply 输出

至少输出：

1. run_id；
2. 实际写入分区数；
3. 实际新增行数；
4. 已存在跳过数；
5. 失败样本（若有）。

## 9. 回滚

每个被替换分区必须备份到：

```text
/Volumes/datasource/goldenshare-tushare-lake/_tmp/<run_id>/_backup/research/stk_mins_by_date_clean/freq=<freq>/trade_date=<YYYY-MM-DD>
```

若任一分区写后校验失败：

1. 立即停止后续分区；
2. 使用备份回滚已改分区；
3. 回到 dry-run 检查失败样本后再重试。

## 10. 验收输出

专项完成后至少输出：

1. 清单命中总数、实际修复总数、已存在跳过总数、失败总数；
2. 按 `freq=5/15/30/60` 的修复统计；
3. 修复后“缺 09:30 的高频问题”剩余数量；
4. 抽样分区直读结果；
5. run_id 与备份目录。

## 11. 与第一阶段收口关系

本专项完成仅表示：

```text
当前错误 clean 口径下，“高频缺 09:30 bar”清洗流程闭环完成。
```

不表示：

```text
clean schema 已正确；
exchange/vwap 已恢复；
trade_date 物理列已移除；
正式 clean 可直接用于最终指标生产。
```
