# 同花顺板块指数行情 Lake prod-raw-db 导出方案

状态：已落地（2026-05-08，后端接入完成，最小真实验证通过）

本文定义 `ths_daily` 数据集从生产 `raw_tushare.ths_daily` 只读导出到本地 Lake Parquet 的方案。该方案只覆盖 `prod-raw-db` 导出模式，不改变现有生产同步链路。

## 1. 目标

把生产库中已经落在 `raw_tushare.ths_daily` 的 Tushare 原始同花顺板块指数行情数据，按 Lake Console 的按日分区布局导出成本地 Parquet。

核心目标：

- 导出的 Parquet 字段必须与 Tushare `ths_daily` 输出参数一致。
- 只访问生产库 `raw_tushare.ths_daily`。
- 禁止 `select *`。
- 不把 `api_name`、`fetched_at`、`raw_payload` 写入 Lake。
- 按交易日生成正式分区。
- 即使 raw 表长期混入休市日数据，也不能写成正式 Lake 分区。

## 2. 数据集基本信息

| 项 | 值 |
| --- | --- |
| Lake dataset_key | `ths_daily` |
| 显示名 | 同花顺板块指数行情 |
| Tushare api_name | `ths_daily` |
| 源接口文档 | `docs/sources/tushare/股票数据/打板专题数据/0260_同花顺板块指数行情.md` |
| 生产 raw 表 | `raw_tushare.ths_daily` |
| Lake 目标层 | `raw` |
| Lake 目标路径 | `raw_tushare/ths_daily/trade_date=YYYY-MM-DD/part-000.parquet` |
| 分区字段 | `trade_date` |
| 写入策略 | `replace_partition` |
| 导出来源 | `prod-raw-db` |

## 3. 字段白名单

| 字段 | Tushare 输出类型 | raw 表类型 | Lake 类型 |
| --- | --- | --- | --- |
| `ts_code` | `str` | `varchar` | `string` |
| `trade_date` | `str` | `date` | `date` |
| `close` | `float` | `numeric` | `double` |
| `open` | `float` | `numeric` | `double` |
| `high` | `float` | `numeric` | `double` |
| `low` | `float` | `numeric` | `double` |
| `pre_close` | `float` | `numeric` | `double` |
| `avg_price` | `float` | `numeric` | `double` |
| `change` | `float` | `numeric` | `double` |
| `pct_change` | `float` | `numeric` | `double` |
| `vol` | `float` | `numeric` | `double` |
| `turnover_rate` | `float` | `numeric` | `double` |
| `total_mv` | `float` | `numeric` | `double` |
| `float_mv` | `float` | `numeric` | `double` |

禁止导出：

- `api_name`
- `fetched_at`
- `raw_payload`

## 4. 生产 raw 表审计

### 4.1 线上真实情况（2026-05-08）

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| 表存在 | 是 | `raw_tushare.ths_daily` |
| schema | `raw_tushare` | 符合边界 |
| 行数 | `650421` | 到 2026-05-07 |
| 日期范围 | `2020-01-02 ~ 2026-05-07` | 当前生产 raw 历史窗口 |
| 开市日覆盖 | `1534 / 1534` | 当前范围内完整 |
| 非交易日日期数 | `102` | raw 长期混入休市日记录 |
| 精确重复组 | `0` | 业务字段组合未发现精确重复 |
| 系统字段 | 有 | `api_name`、`fetched_at`、`raw_payload` |

### 4.2 字段对账

源站输出字段与生产 raw 业务字段完全对齐。  
但当前 raw 长期混入休市日记录，Lake 首版必须严格按本地交易日历开市日白名单写分区，不能把这些日期写成正式 Lake 分区。

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

- Lake 正式分区语义是“某交易日全市场 ths_daily 快照”，不允许局部结果覆盖正式分区。

## 6. 读取模式

读取模式结论：`range_streaming_cursor`

理由：

1. 区间导出必须单连接、只读事务、服务端游标流式读取。
2. 最终按 `trade_date` 聚合后逐日写分区。
3. 量级较大，统一按流式导出更稳。

允许的 SQL：

```sql
select
  ts_code,
  trade_date,
  close,
  open,
  high,
  low,
  pre_close,
  avg_price,
  change,
  pct_change,
  vol,
  turnover_rate,
  total_mv,
  float_mv
from raw_tushare.ths_daily
where trade_date >= :start_date
  and trade_date <= :end_date
order by trade_date, ts_code;
```

## 7. 分区与空结果策略

正式分区：

```text
raw_tushare/ths_daily/trade_date=YYYY-MM-DD/part-000.parquet
```

规则：

1. 只对本地交易日历中的开市日写正式分区。
2. 任何非交易日记录即使存在于 raw，也不能生成正式分区。
3. 某个开市日若查询结果为 0，不写空分区，不覆盖已有分区。
4. 命令输出要明确 `skipped_replace=true`。

## 8. 命令设计

```bash
lake-console plan-sync ths_daily --from prod-raw-db --trade-date 2026-05-07
lake-console sync-dataset ths_daily --from prod-raw-db --trade-date 2026-05-07

lake-console plan-sync ths_daily --from prod-raw-db --start-date 2026-04-01 --end-date 2026-04-30
lake-console sync-dataset ths_daily --from prod-raw-db --start-date 2026-04-01 --end-date 2026-04-30
```

## 9. 验收口径

1. Parquet 字段必须与源站输出字段一致。
2. `trade_date` 必须是 Parquet `date`。
3. 不得包含 `api_name`、`fetched_at`、`raw_payload`。
4. Lake 首版历史起点按当前生产事实 `2020-01-02` 计，不伪造更早分区。
5. 非交易日不得出现在正式 Lake 分区中。
6. 开市日分区行数必须等于白名单 SQL 结果。
