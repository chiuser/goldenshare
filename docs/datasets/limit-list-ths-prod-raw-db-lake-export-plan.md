# 同花顺涨停名单 Lake prod-raw-db 导出方案

状态：已落地（2026-05-07，后端接入完成，单日真实验证通过）

本文定义 `limit_list_ths` 数据集从生产 `raw_tushare.limit_list_ths` 只读导出到本地 Lake Parquet 的方案。该方案只覆盖 `prod-raw-db` 导出模式，不改变现有生产同步链路。

## 1. 目标

把生产库中已经落在 `raw_tushare.limit_list_ths` 的 Tushare 原始同花顺涨跌停榜单数据，按 Lake Console 的按日分区布局导出成本地 Parquet。

核心目标：

- 导出的 Parquet 字段必须与 Tushare `limit_list_ths` 输出参数一致。
- 只访问生产库 `raw_tushare.limit_list_ths`。
- 禁止 `select *`。
- 不把 `query_limit_type`、`query_market`、`api_name`、`fetched_at`、`raw_payload` 写入 Lake。
- 按交易日生成正式分区。

## 2. 数据集基本信息

| 项 | 值 |
| --- | --- |
| Lake dataset_key | `limit_list_ths` |
| 显示名 | 同花顺涨停名单 |
| Tushare api_name | `limit_list_ths` |
| 源接口文档 | `docs/sources/tushare/股票数据/打板专题数据/0355_涨跌停榜单（同花顺）.md` |
| 生产 raw 表 | `raw_tushare.limit_list_ths` |
| Lake 目标层 | `raw` |
| Lake 目标路径 | `raw_tushare/limit_list_ths/trade_date=YYYY-MM-DD/part-000.parquet` |
| 分区字段 | `trade_date` |
| 写入策略 | `replace_partition` |
| 导出来源 | `prod-raw-db` |

## 3. 字段白名单

| 字段 | Tushare 输出类型 | raw 表类型 | Lake 类型 |
| --- | --- | --- | --- |
| `trade_date` | `str` | `date` | `date` |
| `ts_code` | `str` | `varchar(16)` | `string` |
| `name` | `str` | `varchar` | `string` |
| `price` | `float` | `numeric` | `double` |
| `pct_chg` | `float` | `numeric` | `double` |
| `open_num` | `int` | `int4` | `int32` |
| `lu_desc` | `str` | `text` | `string` |
| `limit_type` | `str` | `varchar` | `string` |
| `tag` | `str` | `varchar` | `string` |
| `status` | `str` | `varchar` | `string` |
| `first_lu_time` | `str` | `varchar` | `string` |
| `last_lu_time` | `str` | `varchar` | `string` |
| `first_ld_time` | `str` | `varchar` | `string` |
| `last_ld_time` | `str` | `varchar` | `string` |
| `limit_order` | `float` | `numeric` | `double` |
| `limit_amount` | `float` | `numeric` | `double` |
| `turnover_rate` | `float` | `numeric` | `double` |
| `free_float` | `float` | `numeric` | `double` |
| `lu_limit_order` | `float` | `numeric` | `double` |
| `limit_up_suc_rate` | `float` | `numeric` | `double` |
| `turnover` | `float` | `numeric` | `double` |
| `rise_rate` | `float` | `numeric` | `double` |
| `sum_float` | `float` | `numeric` | `double` |
| `market_type` | `str` | `varchar` | `string` |

禁止导出：

- `query_limit_type`
- `query_market`
- `api_name`
- `fetched_at`
- `raw_payload`

## 4. 生产 raw 表审计

### 4.1 线上真实情况（2026-05-07）

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| 表存在 | 是 | `raw_tushare.limit_list_ths` |
| schema | `raw_tushare` | 符合边界 |
| 行数 | `94172` | 到 2026-04-30 |
| 日期范围 | `2023-11-01 ~ 2026-04-30` | 当前生产 raw 起点已补齐到源站文档声称的首日 |
| 交易日覆盖 | `605 / 605` | 当前范围内完整 |
| 精确重复组 | `0` | 业务字段组合未发现精确重复 |
| 额外上下文字段 | 有 | `query_limit_type`、`query_market` |
| 系统字段 | 有 | `api_name`、`fetched_at`、`raw_payload` |

### 4.2 字段对账

源站输出字段与生产 raw 业务字段对齐。  
注意：

1. 生产 raw 额外保存了查询上下文字段 `query_limit_type`、`query_market`。
2. 这两个字段不是源站输出字段，只能用于生产侧追溯，不得进入 Lake raw。
3. Lake 首版按当前生产事实落盘，不额外伪造 `2023-11-01` 之前的历史分区。

## 5. 输入参数与导出范围

源站输入参数：

- `trade_date`
- `ts_code`
- `limit_type`
- `market`
- `start_date`
- `end_date`
- `limit`
- `offset`

Lake 第一阶段仅支持：

- `--trade-date`
- `--start-date --end-date`

暂不支持：

- `--ts-code`
- `--limit-type`
- `--market`

原因：

- Lake 正式分区语义是“某交易日全市场 limit_list_ths 快照”，不允许局部结果覆盖正式分区。

## 6. 读取模式

读取模式结论：`range_streaming_cursor`

理由：

1. 历史四万多行，继续沿用区间流式读取更稳。
2. 区间导出必须单连接、只读事务、服务端游标流式读取。
3. 最终按 `trade_date` 聚合后逐日写分区。

允许的 SQL：

```sql
select
  trade_date,
  ts_code,
  name,
  price,
  pct_chg,
  open_num,
  lu_desc,
  limit_type,
  tag,
  status,
  first_lu_time,
  last_lu_time,
  first_ld_time,
  last_ld_time,
  limit_order,
  limit_amount,
  turnover_rate,
  free_float,
  lu_limit_order,
  limit_up_suc_rate,
  turnover,
  rise_rate,
  sum_float,
  market_type
from raw_tushare.limit_list_ths
where trade_date >= :start_date
  and trade_date <= :end_date
order by trade_date, ts_code;
```

## 7. 分区与空结果策略

正式分区：

```text
raw_tushare/limit_list_ths/trade_date=YYYY-MM-DD/part-000.parquet
```

规则：

1. 只对本地交易日历中的开市日写正式分区。
2. 某个开市日若查询结果为 0，不写空分区，不覆盖已有分区。
3. 命令输出要明确 `skipped_replace=true`。

## 8. 命令设计

```bash
lake-console plan-sync limit_list_ths --from prod-raw-db --trade-date 2026-04-30
lake-console sync-dataset limit_list_ths --from prod-raw-db --trade-date 2026-04-30

lake-console plan-sync limit_list_ths --from prod-raw-db --start-date 2026-04-01 --end-date 2026-04-30
lake-console sync-dataset limit_list_ths --from prod-raw-db --start-date 2026-04-01 --end-date 2026-04-30
```

## 9. 验收口径

1. Parquet 字段必须与源站输出字段一致。
2. `trade_date` 必须是 Parquet `date`。
3. 不得包含 `query_limit_type`、`query_market`、`api_name`、`fetched_at`、`raw_payload`。
4. Lake 首版历史起点按当前生产事实 `2023-11-01` 计，不伪造更早分区。
5. 交易日分区行数必须等于白名单 SQL 结果。
