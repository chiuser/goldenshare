# 同花顺热榜 Lake prod-raw-db 导出方案

状态：已落地（2026-05-08，后端接入完成，最小真实验证通过）

本文定义 `ths_hot` 数据集从生产 `raw_tushare.ths_hot` 只读导出到本地 Lake Parquet 的方案。该方案只覆盖 `prod-raw-db` 导出模式，不改变现有生产同步链路。

## 1. 目标

把生产库中已经落在 `raw_tushare.ths_hot` 的 Tushare 原始同花顺热榜数据，按 Lake Console 的按日分区布局导出成本地 Parquet。

核心目标：

- 导出的 Parquet 字段必须覆盖 Tushare `ths_hot` 输出参数，以及恢复事实所必需的请求派生维度。
- 只访问生产库 `raw_tushare.ths_hot`。
- 禁止 `select *`。
- 不把 `api_name`、`fetched_at`、`raw_payload` 写入 Lake。
- 按交易日生成正式分区。
- `market / is_new` 必须升格为正式事实字段，字段名不带 `query_` 前缀。

## 2. 数据集基本信息

| 项 | 值 |
| --- | --- |
| Lake dataset_key | `ths_hot` |
| 显示名 | 同花顺热榜 |
| Tushare api_name | `ths_hot` |
| 源接口文档 | `docs/sources/tushare/股票数据/打板专题数据/0320_同花顺热榜.md` |
| 生产 raw 表 | `raw_tushare.ths_hot` |
| Lake 目标层 | `raw` |
| Lake 目标路径 | `raw_tushare/ths_hot/trade_date=YYYY-MM-DD/part-000.parquet` |
| 分区字段 | `trade_date` |
| 写入策略 | `replace_partition` |
| 导出来源 | `prod-raw-db` |

## 3. 字段白名单

### 3.1 正式 Lake 字段

| 字段 | 来源 | raw 表类型 | Lake 类型 |
| --- | --- | --- | --- |
| `trade_date` | 源站输出 | `date` | `date` |
| `data_type` | 源站输出 | `varchar` | `string` |
| `ts_code` | 源站输出 | `varchar` | `string` |
| `ts_name` | 源站输出 | `varchar` | `string` |
| `rank` | 源站输出 | `integer` | `int32` |
| `pct_change` | 源站输出 | `numeric` | `double` |
| `current_price` | 源站输出 | `numeric` | `double` |
| `concept` | 源站输出 | `text` | `string` |
| `rank_reason` | 源站输出 | `text` | `string` |
| `hot` | 源站输出 | `numeric` | `double` |
| `rank_time` | 源站输出 | `varchar` | `string` |
| `market` | 请求派生事实维度 | `varchar`（`query_market`） | `string` |
| `is_new` | 请求派生事实维度 | `varchar`（`query_is_new`） | `string` |

禁止导出：

- `api_name`
- `fetched_at`
- `raw_payload`

### 3.2 字段口径说明

当前生产 `DatasetDefinition.source_fields` 只覆盖源站响应字段，不包含：

- `query_market`
- `query_is_new`

但这两个维度在生产 raw 中已真实保存，且源站响应不回显。  
Lake 首版若丢掉它们，会丢失“同一热榜事实属于哪个市场、是否日终榜”的信息。  
因此 `ths_hot` 必须显式保留：

- `query_market -> market`
- `query_is_new -> is_new`

## 4. 生产 raw 表审计

### 4.1 线上真实情况（2026-05-08）

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| 表存在 | 是 | `raw_tushare.ths_hot` |
| schema | `raw_tushare` | 符合边界 |
| 行数 | `54649` | 到 2026-05-07 |
| 日期范围 | `2026-01-05 ~ 2026-05-07` | 当前生产 raw 历史窗口 |
| 开市日覆盖 | `79 / 79` | 当前范围内完整 |
| 非交易日日期数 | `0` | 当前未发现周末/节假日混入 |
| 精确重复组（旧口径） | `0` | 当前未发现事实碰撞 |
| 精确重复组（升级口径） | `0` | 加入 `market / is_new` 后仍为 0 |
| 系统字段 | 有 | `api_name`、`fetched_at`、`raw_payload` |

### 4.2 字段对账

`ths_hot` 当前不存在像 `dc_hot` 那样的事实碰撞，但 `market / is_new` 仍然必须保留为事实维度。  
因此 Lake 首版按以下规则收口：

1. 源站响应字段按原样保留。
2. `query_market -> market`
3. `query_is_new -> is_new`

## 5. 输入参数与导出范围

源站输入参数：

- `trade_date`
- `ts_code`
- `market`
- `is_new`
- `start_date`
- `end_date`
- `limit`
- `offset`

Lake 第一阶段仅支持：

- `--trade-date`
- `--start-date --end-date`

暂不支持：

- `--ts-code`
- `--market`
- `--is-new`

原因：

- Lake 正式分区语义是“某交易日全市场 ths_hot 事实快照”，不允许局部结果覆盖正式分区。

## 6. 读取模式

读取模式结论：`range_streaming_cursor`

理由：

1. 区间导出必须单连接、只读事务、服务端游标流式读取。
2. 最终按 `trade_date` 聚合后逐日写分区。
3. 需要在 SQL 投影阶段完成 `query_* -> 正式事实字段` 的映射。

允许的 SQL：

```sql
select
  trade_date,
  data_type,
  ts_code,
  ts_name,
  rank,
  pct_change,
  current_price,
  concept,
  rank_reason,
  hot,
  rank_time,
  query_market as market,
  query_is_new as is_new
from raw_tushare.ths_hot
where trade_date >= :start_date
  and trade_date <= :end_date
order by trade_date, ts_code, rank_time, query_market, query_is_new;
```

## 7. 分区与空结果策略

正式分区：

```text
raw_tushare/ths_hot/trade_date=YYYY-MM-DD/part-000.parquet
```

规则：

1. 只对本地交易日历中的开市日写正式分区。
2. 某个开市日若查询结果为 0，不写空分区，不覆盖已有分区。
3. 即使未来 raw 混入非交易日记录，也不能生成正式分区。
4. 命令输出要明确 `skipped_replace=true`。

## 8. 命令设计

```bash
lake-console plan-sync ths_hot --from prod-raw-db --trade-date 2026-05-07
lake-console sync-dataset ths_hot --from prod-raw-db --trade-date 2026-05-07

lake-console plan-sync ths_hot --from prod-raw-db --start-date 2026-04-01 --end-date 2026-04-30
lake-console sync-dataset ths_hot --from prod-raw-db --start-date 2026-04-01 --end-date 2026-04-30
```

## 9. 验收口径

1. Parquet 字段必须包含：
   - 源站响应字段
   - `market`
   - `is_new`
2. `trade_date` 必须是 Parquet `date`。
3. 不得包含 `api_name`、`fetched_at`、`raw_payload`。
4. Lake 首版历史起点按当前生产事实 `2026-01-05` 计，不伪造更早分区。
5. 开市日分区行数必须等于白名单 SQL 结果。
