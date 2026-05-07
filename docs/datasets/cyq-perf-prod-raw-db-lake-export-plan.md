# 每日筹码及胜率 Lake prod-raw-db 导出方案

状态：已落地（2026-05-07，后端接入完成，单日真实验证通过）

本文定义 `cyq_perf` 数据集从生产 `raw_tushare.cyq_perf` 只读导出到本地 Lake Parquet 的方案。该方案只覆盖 `prod-raw-db` 导出模式，不改变现有生产同步链路。

## 1. 目标

把生产库中已经落在 `raw_tushare.cyq_perf` 的 Tushare 原始每日筹码及胜率数据，按 Lake Console 的按日分区布局导出成本地 Parquet。

核心目标：

- 导出的 Parquet 字段必须与 Tushare `cyq_perf` 输出参数一致。
- 只访问生产库 `raw_tushare.cyq_perf`。
- 禁止 `select *`。
- 不把 `api_name`、`fetched_at`、`raw_payload` 写入 Lake。
- 按交易日生成正式分区。

## 2. 数据集基本信息

| 项 | 值 |
| --- | --- |
| Lake dataset_key | `cyq_perf` |
| 显示名 | 每日筹码及胜率 |
| Tushare api_name | `cyq_perf` |
| 源接口文档 | `docs/sources/tushare/股票数据/特色数据/0293_每日筹码及胜率.md` |
| 生产 raw 表 | `raw_tushare.cyq_perf` |
| Lake 目标层 | `raw` |
| Lake 目标路径 | `raw_tushare/cyq_perf/trade_date=YYYY-MM-DD/part-000.parquet` |
| 分区字段 | `trade_date` |
| 写入策略 | `replace_partition` |
| 导出来源 | `prod-raw-db` |

## 3. 字段白名单

| 字段 | Tushare 输出类型 | raw 表类型 | Lake 类型 |
| --- | --- | --- | --- |
| `ts_code` | `str` | `varchar(16)` | `string` |
| `trade_date` | `str` | `date` | `date` |
| `his_low` | `float` | `numeric` | `double` |
| `his_high` | `float` | `numeric` | `double` |
| `cost_5pct` | `float` | `numeric` | `double` |
| `cost_15pct` | `float` | `numeric` | `double` |
| `cost_50pct` | `float` | `numeric` | `double` |
| `cost_85pct` | `float` | `numeric` | `double` |
| `cost_95pct` | `float` | `numeric` | `double` |
| `weight_avg` | `float` | `numeric` | `double` |
| `winner_rate` | `float` | `numeric` | `double` |

禁止导出：

- `api_name`
- `fetched_at`
- `raw_payload`

## 4. 生产 raw 表审计

### 4.1 线上真实情况（2026-05-07）

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| 表存在 | 是 | `raw_tushare.cyq_perf` |
| schema | `raw_tushare` | 符合边界 |
| 行数 | `9160088` | 到 2026-05-07 |
| 日期范围 | `2018-01-02 ~ 2026-05-07` | 与源站“2018年开始”一致 |
| 交易日覆盖 | `2021 / 2021` | 当前范围内完整 |
| 精确重复组 | `0` | 业务字段组合未发现精确重复 |
| 系统字段 | 有 | `api_name`、`fetched_at`、`raw_payload` |

### 4.2 字段对账

源站输出字段与生产 raw 字段完全对齐，仅数值字段统一落为 Lake `double`，`trade_date` 统一落为 Parquet `date`。

## 5. 输入参数与导出范围

源站输入参数：

- `ts_code`（必选）
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

- Lake 正式分区语义是“某交易日全市场 cyq_perf 快照”，不允许局部结果覆盖正式分区。

## 6. 读取模式

读取模式结论：`range_streaming_cursor`

理由：

1. 行数已超过九百万，禁止 `fetchall`。
2. 区间导出必须单连接、只读事务、服务端游标流式读取。
3. 最终按 `trade_date` 聚合后逐日写分区。

允许的 SQL：

```sql
select
  ts_code,
  trade_date,
  his_low,
  his_high,
  cost_5pct,
  cost_15pct,
  cost_50pct,
  cost_85pct,
  cost_95pct,
  weight_avg,
  winner_rate
from raw_tushare.cyq_perf
where trade_date >= :start_date
  and trade_date <= :end_date
order by trade_date, ts_code;
```

## 7. 分区与空结果策略

正式分区：

```text
raw_tushare/cyq_perf/trade_date=YYYY-MM-DD/part-000.parquet
```

规则：

1. 只对本地交易日历中的开市日写正式分区。
2. 某个开市日若查询结果为 0，不写空分区，不覆盖已有分区。
3. 命令输出要明确 `skipped_replace=true`。

## 8. 命令设计

```bash
lake-console plan-sync cyq_perf --from prod-raw-db --trade-date 2026-05-07
lake-console sync-dataset cyq_perf --from prod-raw-db --trade-date 2026-05-07

lake-console plan-sync cyq_perf --from prod-raw-db --start-date 2026-04-01 --end-date 2026-04-30
lake-console sync-dataset cyq_perf --from prod-raw-db --start-date 2026-04-01 --end-date 2026-04-30
```

## 9. 验收口径

1. Parquet 字段必须与源站输出字段一致。
2. `trade_date` 必须是 Parquet `date`。
3. 不得包含 `api_name`、`fetched_at`、`raw_payload`。
4. 交易日分区行数必须等于白名单 SQL 结果。
