# ST股票列表 Lake prod-raw-db 导出方案

状态：已落地（2026-05-06）

本文定义 `stock_st` 数据集从生产 `raw_tushare.stock_st` 只读导出到本地 Lake Parquet 的方案。该方案只覆盖 `prod-raw-db` 导出模式，不改变现有 Tushare API 下载链路。

## 1. 目标

把生产库中已经落在 `raw_tushare.stock_st` 的 Tushare 原始 ST 股票列表数据，按 Lake Console 的按日分区布局导出成本地 Parquet。

核心目标：

- 导出的 Parquet 字段必须与 Tushare `stock_st` 输出参数一致。
- 只访问生产库 `raw_tushare.stock_st`。
- 禁止 `select *`。
- 不把 `api_name`、`fetched_at`、`raw_payload` 写入 Lake。
- 按交易日生成正式分区。

## 2. 数据集基本信息

| 项 | 值 |
| --- | --- |
| Lake dataset_key | `stock_st` |
| 显示名 | ST股票列表 |
| Tushare api_name | `stock_st` |
| 源接口文档 | `docs/sources/tushare/股票数据/基础数据/0397_ST股票列表.md` |
| 生产 raw 表 | `raw_tushare.stock_st` |
| Lake 目标层 | `raw` |
| Lake 目标路径 | `raw_tushare/stock_st/trade_date=YYYY-MM-DD/part-000.parquet` |
| 分区字段 | `trade_date` |
| 写入策略 | `replace_partition` |
| 导出来源 | `prod-raw-db` |

## 3. 字段白名单

| 字段 | Tushare 输出类型 | raw 表类型 | Lake 类型 |
| --- | --- | --- | --- |
| `ts_code` | `str` | `varchar(16)` | `string` |
| `name` | `str` | `varchar` | `string` |
| `trade_date` | `str` | `date` | `date` |
| `type` | `str` | `varchar` | `string` |
| `type_name` | `str` | `varchar` | `string` |

禁止导出：

- `api_name`
- `fetched_at`
- `raw_payload`

## 4. 生产 raw 表审计

### 4.1 线上真实情况（2026-05-06）

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| 表存在 | 是 | `raw_tushare.stock_st` |
| schema | `raw_tushare` | 符合边界 |
| 行数 | `322817` | 到 2026-04-30 |
| 日期范围 | `2016-08-09 ~ 2026-04-30` | 与当前已修复的库内事实一致 |
| 系统字段 | 有 | `api_name`、`fetched_at`、`raw_payload` |
| 主业务键重复 | `0` | `(ts_code, trade_date, type)` 无重复 |
| `type` 实际值 | `ST` | 当前只有 `ST` 一种类型值 |

说明：

1. 源站文档提示“本接口数据从 20160101 开始，太早历史无法补齐”。
2. 当前生产 raw 表最早日期为 `2016-08-09`，Lake 以当前库内真实事实为准。

### 4.2 字段对账

源站输出字段与生产 raw 字段完全对齐，日期字段统一落为 Parquet `date`，其余保留字符串。

## 5. 输入参数与导出范围

源站输入参数：

- `ts_code`
- `trade_date`
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

- Lake 正式分区语义是某交易日全市场 ST 列表快照，不允许局部标的结果覆盖正式分区。

## 6. 读取模式

读取模式结论：`range_streaming_cursor`

理由：

1. 总行数三十多万，继续沿用 by-date 流式读取模板最稳。
2. `stock_st` 已存在历史缺口修复背景，但 Lake 这里是只读导出，不再重新解释源端行为。
3. 范围流式读取后按 `trade_date` 写分区，符合后续审计与 DuckDB 查询习惯。

允许的 SQL 形态：

```sql
select
  ts_code,
  name,
  trade_date,
  type,
  type_name
from raw_tushare.stock_st
where trade_date >= :start_date
  and trade_date <= :end_date
order by trade_date, ts_code, type;
```

## 7. 分区策略

正式分区：

```text
raw_tushare/stock_st/trade_date=YYYY-MM-DD/part-000.parquet
```

规则：

1. 只对本地交易日历中的开市日写正式分区。
2. 某个开市日查询结果为 0，不写空分区，不覆盖已有分区。
3. `trade_date` 写为 Parquet `date`，目录名仍使用 `YYYY-MM-DD`。

## 8. 验收口径

1. Parquet 字段集合必须与 Tushare 输出参数一致。
2. 不得导出 `api_name`、`fetched_at`、`raw_payload`。
3. `trade_date` 必须是 Parquet `date`。
4. 某交易日 Lake 分区行数必须等于 raw 白名单 SQL 结果。
