# stk_mins 首日早于 stock_basic.list_date 语义审计

- 生成时间：2026-05-11T21:44:41
- Lake root：`/Volumes/datasource/goldenshare-tushare-lake`
- 候选代码数：`237`
- 审计范围：候选代码 x `freq=1/5/15/30/60/90/120`
- 有效 bar 规则：`open/close/high/low > 0` 且 `high >= low`，`vol/amount >= 0`，`trade_time` 非空。

## 结论口径

本报告用于识别 raw 源文件中“早于 `stock_basic.list_date` 的分钟线行”到底是无效占位还是非 0 行。  
经 2026-05-11 评审确认，后续 `research/stk_mins_by_date_clean` 统一以 `stock_basic.list_date / delist_date` 作为清洗边界：

1. `trade_date < list_date` 的分钟线行不进入 clean 层，即使 OHLC 非 0。
2. `trade_date > delist_date` 的分钟线行不进入 clean 层。
3. raw 层继续保留源站事实，不在 raw 中物理删除或改写这些行。

## 汇总

- `has_valid_before_list_date`：192
- `prelist_rows_invalid_only`：45

## 明细分类

- `missing_freq`：5
- `no_prelist_issue_for_freq`：333
- `only_invalid_before_list_date`：309
- `valid_before_list_date`：1012

## 样例

### has_valid_before_list_date

| ts_code | name | list_dt | min_first_seen | min_first_valid | missing_freqs | valid_before_list_freqs | invalid_only_before_list_freqs |
|---|---|---:|---:|---:|---|---|---|
| `002789.SZ` | *ST建艺 | 2016-03-11 | 2016-03-02 | 2016-03-02 |  | 1 |  |
| `002790.SZ` | 瑞尔特 | 2016-03-08 | 2016-02-25 | 2016-02-25 |  | 1 |  |
| `002801.SZ` | 微光股份 | 2016-06-22 | 2016-06-13 | 2016-06-13 |  | 1 |  |
| `002802.SZ` | 洪汇新材 | 2016-06-29 | 2016-06-20 | 2016-06-20 |  | 1 |  |
| `002803.SZ` | 吉宏股份 | 2016-07-12 | 2016-06-30 | 2016-06-30 |  | 1 |  |
| `002805.SZ` | 丰元股份 | 2016-07-07 | 2016-06-27 | 2016-06-27 |  | 1 |  |
| `002806.SZ` | 华锋股份 | 2016-07-26 | 2016-07-14 | 2016-07-14 |  | 1 |  |
| `002807.SZ` | 江阴银行 | 2016-09-02 | 2016-08-24 | 2016-08-24 |  | 1 |  |
| `002808.SZ` | *ST恒久 | 2016-08-12 | 2016-08-03 | 2016-08-03 |  | 1 |  |
| `002809.SZ` | 红墙股份 | 2016-08-23 | 2016-08-11 | 2016-08-11 |  | 1 |  |

### prelist_rows_invalid_only

| ts_code | name | list_dt | min_first_seen | min_first_valid | missing_freqs | valid_before_list_freqs | invalid_only_before_list_freqs |
|---|---|---:|---:|---:|---|---|---|
| `601717.SH` | 中创智领 | 2010-08-03 | 2010-07-30 | 2010-08-03 |  |  | 1 |
| `920002.BJ` | 万达轴承 | 2024-05-30 | 2024-05-21 | 2024-05-30 |  |  | 1,5,15,30,60,90,120 |
| `920003.BJ` | 中诚咨询 | 2025-11-07 | 2025-10-28 | 2025-11-07 |  |  | 1,5,15,30,60,90,120 |
| `920005.BJ` | 鼎佳精密 | 2025-07-31 | 2025-07-22 | 2025-07-31 |  |  | 1,5,15,30,60,90,120 |
| `920007.BJ` | 酉立智能 | 2025-08-08 | 2025-07-29 | 2025-08-08 |  |  | 1,5,15,30,60,90,120 |
| `920008.BJ` | 成电光信 | 2024-08-29 | 2024-08-20 | 2024-08-29 |  |  | 1,5,15,30,60,90,120 |
| `920009.BJ` | 丹娜生物 | 2025-11-03 | 2025-10-22 | 2025-11-03 |  |  | 1,5,15,30,60,90,120 |
| `920015.BJ` | 锦华新材 | 2025-09-25 | 2025-09-16 | 2025-09-25 |  |  | 1,5,15,30,60,90,120 |
| `920016.BJ` | 中草香料 | 2024-09-13 | 2024-09-03 | 2024-09-13 |  |  | 1,5,15,30,60,90,120 |
| `920018.BJ` | 宏远股份 | 2025-08-20 | 2025-08-11 | 2025-08-20 |  |  | 1,5,15,30,60,90,120 |

## 输出文件

- `/Users/congming/github/goldenshare/reports/stk_mins_effective_start_audit_2026-05-11/summary_by_code.csv`
- `/Users/congming/github/goldenshare/reports/stk_mins_effective_start_audit_2026-05-11/detail_by_code_freq.csv`
