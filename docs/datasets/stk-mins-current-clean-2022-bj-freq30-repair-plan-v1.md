# stk_mins 当前错误 clean 2022 北交所 30min 缺失专项修复方案 v1

状态：待评审  
最近更新：2026-05-13  
适用范围：当前错误 schema 的 `research/stk_mins_by_date_clean`

## 1. 本文定位

本文只服务第一阶段当前错误 clean 的专项修复：

```text
对 2022 年北交所（*.BJ）在 30min 分区中出现 bar_count=6 的记录，
基于同日同股票 clean 15min 重建 30min，并仅替换受影响股票行。
```

本文不是正式 clean 重建方案。

正式 clean 仍以后续 `raw_tushare/stk_mins_by_date -> research/stk_mins_by_date_clean` 重建方案为准；正式 clean 必须保留 `exchange/vwap`，不得写入物理列 `trade_date`。

## 2. 当前问题事实

来自完备性问题账本的已确认问题：

```text
manifest/stk_mins_quality/clean_completeness_issue_ledger.parquet
```

口径（当前已确认）：

```text
trade_date: 2022-07-15 ~ 2022-12-30
latest_ts_code like %.BJ
freq=30
expected_value=bar_count=9
actual_value=bar_count=6
```

该问题表示：当前错误 clean 的 30min 数据在这批股票/日期下日内 bar 数不足，需要重建。

## 3. 修复边界

本专项只允许处理：

```text
research/stk_mins_by_date_clean/freq=30/trade_date=<2022-07-15~2022-12-30>
且仅限账本筛出的 *.BJ 受影响股票
```

本专项禁止处理：

```text
raw_tushare/stk_mins_by_date
research/stk_mins_by_date_clean 其他频率
research/stk_mins_by_date_clean 非账本受影响股票
derived/stk_mins_by_date
research/stk_mins_by_symbol_month
research/stk_mins_indicators_by_date
research/stk_mins_indicators_by_symbol_month
manifest/security_identity_map
其他数据集
```

## 4. 独立命令（红线）

本专项必须使用独立命令，不得复用或混入其他命令：

```bash
lake_console/.venv/bin/python -m lake_console.backend.app.cli repair-current-clean-2022-bj-freq30 --dry-run
lake_console/.venv/bin/python -m lake_console.backend.app.cli repair-current-clean-2022-bj-freq30 --apply
```

命令必须硬编码本专项边界，不提供任意日期/任意频率自由参数。

## 5. 源数据与输出口径（当前错误 clean）

### 5.1 源数据

源层固定为当前错误 clean 的同日同股票 15min：

```text
research/stk_mins_by_date_clean/freq=15/trade_date=<YYYY-MM-DD>
```

### 5.2 输出层

目标层固定为当前错误 clean 的同日同股票 30min：

```text
research/stk_mins_by_date_clean/freq=30/trade_date=<YYYY-MM-DD>
```

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

## 6. 30min 重建规则（从 15min）

### 6.1 15min 源前置期望

每只受影响股票在受影响日期的 `15min` 行数必须为 `17`（当前常规日盘口径）：

```text
09:30 单根
09:45, 10:00, 10:15, 10:30, 10:45, 11:00, 11:15, 11:30
13:15, 13:30, 13:45, 14:00, 14:15, 14:30, 14:45, 15:00
```

### 6.2 30min 目标窗口

每只受影响股票重建后必须为 `9` 行：

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

### 6.3 字段聚合规则

| 字段 | 规则 |
| --- | --- |
| `ts_code` | 沿用源 15min 的 `ts_code` |
| `freq` | 固定写 `30` |
| `trade_time` | 窗口内最后一根 15min 的 `trade_time` |
| `open` | 窗口第一根 15min 的 `open` |
| `close` | 窗口最后一根 15min 的 `close` |
| `high` | 窗口内 `high` 最大值 |
| `low` | 窗口内 `low` 最小值 |
| `vol` | 窗口内 `vol` 求和 |
| `amount` | 窗口内 `amount` 求和 |
| `trade_date` | 分区日期 |

## 7. `dry-run` 要求（只读）

`--dry-run` 必须输出：

1. 受影响交易日数量、受影响股票数量、受影响 `(trade_date, ts_code)` 组合数量。
2. 每个交易日旧 `30min` 受影响行数、预计重建新行数、净变化。
3. 15min 源门禁检查结果：
   - 是否存在缺分区；
   - 是否存在 `bar_count != 17`；
   - 是否存在重复 key `(ts_code, freq, trade_time)`；
   - 是否存在 schema 不一致。
4. 预计写入前后分区总行数变化。
5. 若任一门禁失败，明确列出失败样本并返回失败，不进入 apply。

## 8. `apply` 要求（写入）

`--apply` 必须按交易日逐分区处理，且每个分区遵循：

1. 读取 `freq=30/trade_date=...` 目标分区完整数据。
2. 删除该日受影响股票的旧 30min 行。
3. 基于同日同股票 15min 重建新 30min 行。
4. 合并“未受影响股票旧行 + 受影响股票新行”。
5. 校验：
   - 每只受影响股票重建后 `bar_count=9`；
   - 分区内 key 唯一 `(ts_code, freq, trade_time)`；
   - 输出 schema 严格等于当前错误 clean 10 列。
6. 写 `_tmp/<run_id>/...` 后校验行数，再原子替换正式分区。

任一分区校验失败，必须立即停止，禁止继续后续日期。

## 9. 门禁

### G1. 影响清单门禁

受影响清单必须来自账本筛选，不允许手工股票列表。

### G2. 源数据门禁（15min）

受影响股票在受影响日期必须满足：

```text
bar_count=17
key 唯一
schema 与当前错误 clean 10 列一致
```

### G3. 重建门禁（30min）

受影响股票重建后必须满足：

```text
bar_count=9
key 唯一
schema 与当前错误 clean 10 列一致
```

### G4. 分区保护门禁

```text
未受影响股票行数不变
受影响股票旧行完全删除
受影响股票新行数量正确
```

## 10. 回滚

每个被替换分区必须备份到：

```text
/Volumes/datasource/goldenshare-tushare-lake/_tmp/<run_id>/_backup/research/stk_mins_by_date_clean/freq=30/trade_date=<YYYY-MM-DD>
```

失败时：

1. 立即停止后续日期。
2. 使用备份恢复已替换分区。
3. 回到 `--dry-run` 重新核查失败原因。

## 11. 验收输出

专项完成后至少输出：

1. 受影响交易日数、股票数、组合数。
2. 旧行总数、新行总数、净变化。
3. 修复后 `bar_count=6` 的剩余数量。
4. 分区直读抽样结果。
5. run_id 与备份目录位置。

## 12. 与第一阶段收口关系

本专项完成仅表示：

```text
当前错误 clean 口径下，2022 北交所 30min 缺失（6->9）专项完成。
```

不表示：

```text
clean schema 已正确；
exchange/vwap 已恢复；
trade_date 物理列已移除；
derived/research/indicator 可以重建。
```

正式 clean 仍需第二阶段 raw -> clean 重建。
