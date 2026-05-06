# 每日停复牌信息 Lake prod-raw-db 导出方案

状态：已落地（2026-05-06）

本文定义 `suspend_d` 数据集从生产 `raw_tushare.suspend_d` 只读导出到本地 Lake Parquet 的方案。该方案只覆盖 `prod-raw-db` 导出模式，不改变现有 Tushare API 下载链路。

## 1. 目标

把生产库中已经落在 `raw_tushare.suspend_d` 的 Tushare 原始每日停复牌信息数据，按 Lake Console 的按日分区布局导出成本地 Parquet。

核心目标：

- 导出的 Parquet 字段必须与 Tushare `suspend_d` 输出参数一致。
- 只访问生产库 `raw_tushare.suspend_d`。
- 禁止 `select *`。
- 不把 `id`、`row_key_hash`、`api_name`、`fetched_at`、`raw_payload` 写入 Lake。
- 按交易日生成正式分区。

## 2. 数据集基本信息

| 项 | 值 |
| --- | --- |
| Lake dataset_key | `suspend_d` |
| 显示名 | 每日停复牌信息 |
| Tushare api_name | `suspend_d` |
| 源接口文档 | `docs/sources/tushare/股票数据/行情数据/0214_每日停复牌信息.md` |
| 生产 raw 表 | `raw_tushare.suspend_d` |
| Lake 目标层 | `raw` |
| Lake 目标路径 | `raw_tushare/suspend_d/trade_date=YYYY-MM-DD/part-000.parquet` |
| 分区字段 | `trade_date` |
| 写入策略 | `replace_partition` |
| 导出来源 | `prod-raw-db` |

## 3. 字段白名单

| 字段 | Tushare 输出类型 | raw 表类型 | Lake 类型 |
| --- | --- | --- | --- |
| `ts_code` | `str` | `varchar(16)` | `string` |
| `trade_date` | `str` | `date` | `date` |
| `suspend_timing` | `str` | `varchar` | `string` |
| `suspend_type` | `str` | `varchar` | `string` |

禁止导出：

- `id`
- `row_key_hash`
- `api_name`
- `fetched_at`
- `raw_payload`

## 4. 生产 raw 表审计

### 4.1 线上真实情况（2026-05-06）

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| 表存在 | 是 | `raw_tushare.suspend_d` |
| schema | `raw_tushare` | 符合边界 |
| 行数 | `5337` | 到 2026-04-30 |
| 日期范围 | `2025-01-02 ~ 2026-04-30` | 当前库内有效历史范围 |
| 系统字段 | 有 | `id`、`row_key_hash`、`api_name`、`fetched_at`、`raw_payload` |
| 主业务键重复 | `0` | `(ts_code, trade_date, suspend_type, coalesce(suspend_timing,''))` 无重复 |
| `suspend_type` 实际值 | `R,S` | 当前停牌/复牌两类值都存在 |

### 4.2 字段对账

源站输出字段为：

- `ts_code`
- `trade_date`
- `suspend_timing`
- `suspend_type`

生产 raw 额外多出：

- `id`
- `row_key_hash`
- `api_name`
- `fetched_at`
- `raw_payload`

处理策略：

- 上述额外字段全部排除，Lake raw 层只保留源站输出字段。

## 5. 输入参数与导出范围

源站输入参数：

- `ts_code`
- `trade_date`
- `start_date`
- `end_date`
- `suspend_type`
- `limit`
- `offset`

Lake 第一阶段仅支持：

- `--trade-date`
- `--start-date --end-date`

暂不支持：

- `--ts-code`
- `--suspend-type`

原因：

- Lake 正式分区语义是某交易日全市场停复牌快照，不允许局部标的或单一停复牌类型结果覆盖正式分区。

## 6. 读取模式

读取模式结论：`range_streaming_cursor`

理由：

1. 表不大，但仍然是标准日频事实表，继续沿用 by-date 流式模板更稳。
2. `id` 与 `row_key_hash` 只是生产写入辅助字段，不改变 Lake 对外字段契约。
3. 区间读取后按 `trade_date` 写分区，后续审计和 DuckDB 查询最直接。

允许的 SQL 形态：

```sql
select
  ts_code,
  trade_date,
  suspend_timing,
  suspend_type
from raw_tushare.suspend_d
where trade_date >= :start_date
  and trade_date <= :end_date
order by trade_date, ts_code, suspend_type, suspend_timing;
```

## 7. 分区策略

正式分区：

```text
raw_tushare/suspend_d/trade_date=YYYY-MM-DD/part-000.parquet
```

规则：

1. 只对本地交易日历中的开市日写正式分区。
2. 某个开市日查询结果为 0，不写空分区，不覆盖已有分区。
3. `trade_date` 写为 Parquet `date`，目录名仍使用 `YYYY-MM-DD`。

## 8. 验收口径

1. Parquet 字段集合必须与 Tushare 输出参数一致。
2. 不得导出 `id`、`row_key_hash`、`api_name`、`fetched_at`、`raw_payload`。
3. `trade_date` 必须是 Parquet `date`。
4. 某交易日 Lake 分区行数必须等于 raw 白名单 SQL 结果。
