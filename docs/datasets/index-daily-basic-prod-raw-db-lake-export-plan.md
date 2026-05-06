# 指数每日指标 Lake prod-raw-db 导出方案

状态：已落地（2026-05-06 首次实跑通过）

本文定义 `index_daily_basic` 数据集从生产 `raw_tushare.index_daily_basic` 只读导出到本地 Lake Parquet 的方案。该方案只覆盖 `prod-raw-db` 导出模式，不改变现有 Tushare API 下载链路。

## 1. 目标

把生产库中已经落在 `raw_tushare.index_daily_basic` 的 Tushare 原始指数每日指标数据，按 Lake Console 的按日分区布局导出成本地 Parquet。

核心目标：

- 导出的 Parquet 字段必须与 Tushare `index_dailybasic` 输出参数一致。
- 只访问生产库 `raw_tushare.index_daily_basic`。
- 禁止 `select *`。
- 不把 `api_name`、`fetched_at`、`raw_payload` 写入 Lake。

## 2. 数据集基本信息

| 项 | 值 |
| --- | --- |
| Lake dataset_key | `index_daily_basic` |
| 显示名 | 指数每日指标 |
| Tushare api_name | `index_dailybasic` |
| 源接口文档 | `docs/sources/tushare/指数专题/0128_大盘指数每日指标.md` |
| 生产 raw 表 | `raw_tushare.index_daily_basic` |
| Lake 目标层 | `raw` |
| Lake 目标路径 | `raw_tushare/index_daily_basic/trade_date=YYYY-MM-DD/part-000.parquet` |
| 分区字段 | `trade_date` |
| 写入策略 | `replace_partition` |
| 导出来源 | `prod-raw-db` |

## 3. 字段白名单

| 字段 | Tushare 输出类型 | raw 表类型 | Lake 类型 |
| --- | --- | --- | --- |
| `ts_code` | `str` | `varchar(16)` | `string` |
| `trade_date` | `str` | `date` | `date` |
| `total_mv` | `float` | `numeric` | `double` |
| `float_mv` | `float` | `numeric` | `double` |
| `total_share` | `float` | `numeric` | `double` |
| `float_share` | `float` | `numeric` | `double` |
| `free_share` | `float` | `numeric` | `double` |
| `turnover_rate` | `float` | `numeric` | `double` |
| `turnover_rate_f` | `float` | `numeric` | `double` |
| `pe` | `float` | `numeric` | `double` |
| `pe_ttm` | `float` | `numeric` | `double` |
| `pb` | `float` | `numeric` | `double` |

禁止导出：

- `api_name`
- `fetched_at`
- `raw_payload`

## 4. 生产 raw 表审计

### 4.1 线上真实情况（2026-05-06）

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| 表存在 | 是 | `raw_tushare.index_daily_basic` |
| schema | `raw_tushare` | 符合边界 |
| 行数 | `1785` | 当前仅覆盖少量大盘指数 |
| 日期范围 | `2020-01-02 ~ 2026-04-30` | 与源说明一致 |
| 系统字段 | 有 | `api_name`、`fetched_at`、`raw_payload` |

### 4.2 字段对账

源站输出字段与生产 raw 字段对齐；数值落 Lake `double`，`trade_date` 落 Parquet `date`。

### 4.3 首次实跑结果（2026-05-06）

```bash
lake-console sync-dataset index_daily_basic --from prod-raw-db --trade-date 2026-04-30
```

结果：

- `fetched_rows = 12`
- `written_rows = 12`
- 输出文件：
  - `raw_tushare/index_daily_basic/trade_date=2026-04-30/part-000.parquet`
- Parquet 校验：
  - `trade_date` 类型为 `date32[day]`
  - 行数为 `12`

## 5. 输入参数与导出范围

源站输入参数：

- `trade_date`
- `ts_code`
- `start_date`
- `end_date`
- `limit`
- `offset`

Lake 第一阶段仅支持：

- `--trade-date`
- `--start-date --end-date`

暂不支持：

- `--ts-code`

原因：

- Lake 分区语义是某交易日全市场指数每日指标快照，不允许局部结果覆盖正式分区。

## 6. 读取模式

读取模式结论：`range_streaming_cursor`

虽然行数不大，但为了和 R2 日频分区批保持一致，仍建议统一为单连接区间流式读取，再按 `trade_date` 分组写分区。

允许的 SQL：

```sql
select
  ts_code,
  trade_date,
  total_mv,
  float_mv,
  total_share,
  float_share,
  free_share,
  turnover_rate,
  turnover_rate_f,
  pe,
  pe_ttm,
  pb
from raw_tushare.index_daily_basic
where trade_date >= :start_date
  and trade_date <= :end_date
order by trade_date, ts_code;
```

## 7. 分区策略

```text
raw_tushare/index_daily_basic/trade_date=YYYY-MM-DD/part-000.parquet
```

规则：

1. 只对本地交易日历中的开市日写正式分区。
2. 某个开市日若结果为 0，不写空分区，不覆盖已有分区。

## 8. 命令设计

```bash
lake-console plan-sync index_daily_basic --from prod-raw-db --trade-date 2026-04-30
lake-console sync-dataset index_daily_basic --from prod-raw-db --trade-date 2026-04-30

lake-console plan-sync index_daily_basic --from prod-raw-db --start-date 2026-04-01 --end-date 2026-04-30
lake-console sync-dataset index_daily_basic --from prod-raw-db --start-date 2026-04-01 --end-date 2026-04-30
```

## 9. 验收口径

1. 字段必须与源站输出字段一致。
2. `trade_date` 必须是 Parquet `date`。
3. 不得包含 `api_name`、`fetched_at`、`raw_payload`。
4. 分区行数必须等于白名单 SQL 结果。
