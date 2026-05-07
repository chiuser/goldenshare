# 连板天梯 Lake prod-raw-db 导出方案

状态：已落地（2026-05-07，后端接入完成，单日真实验证通过）

本文定义 `limit_step` 数据集从生产 `raw_tushare.limit_step` 只读导出到本地 Lake Parquet 的方案。该方案只覆盖 `prod-raw-db` 导出模式，不改变现有生产同步链路。

## 1. 目标

把生产库中已经落在 `raw_tushare.limit_step` 的 Tushare 原始连板天梯数据，按 Lake Console 的按日分区布局导出成本地 Parquet。

核心目标：

- 导出的 Parquet 字段必须与 Tushare `limit_step` 输出参数一致。
- 只访问生产库 `raw_tushare.limit_step`。
- 禁止 `select *`。
- 不把 `api_name`、`fetched_at`、`raw_payload` 写入 Lake。
- 按交易日生成正式分区。

## 2. 数据集基本信息

| 项 | 值 |
| --- | --- |
| Lake dataset_key | `limit_step` |
| 显示名 | 连板梯队 |
| Tushare api_name | `limit_step` |
| 源接口文档 | `docs/sources/tushare/股票数据/打板专题数据/0356_连板天梯.md` |
| 生产 raw 表 | `raw_tushare.limit_step` |
| Lake 目标层 | `raw` |
| Lake 目标路径 | `raw_tushare/limit_step/trade_date=YYYY-MM-DD/part-000.parquet` |
| 分区字段 | `trade_date` |
| 写入策略 | `replace_partition` |
| 导出来源 | `prod-raw-db` |

## 3. 字段白名单

| 字段 | Tushare 输出类型 | raw 表类型 | Lake 类型 |
| --- | --- | --- | --- |
| `ts_code` | `str` | `varchar(16)` | `string` |
| `name` | `str` | `varchar` | `string` |
| `trade_date` | `str` | `date` | `date` |
| `nums` | `str` | `varchar` | `string` |

禁止导出：

- `api_name`
- `fetched_at`
- `raw_payload`

## 4. 生产 raw 表审计

### 4.1 线上真实情况（2026-05-07）

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| 表存在 | 是 | `raw_tushare.limit_step` |
| schema | `raw_tushare` | 符合边界 |
| 行数 | `1324` | 到 2026-04-30 |
| 日期范围 | `2026-01-05 ~ 2026-04-30` | 当前生产 raw 历史窗口较短 |
| 交易日覆盖 | `77 / 77` | 当前范围内完整 |
| 精确重复组 | `0` | 业务字段组合未发现精确重复 |
| 系统字段 | 有 | `api_name`、`fetched_at`、`raw_payload` |

### 4.2 字段对账

源站输出字段与生产 raw 字段完全对齐。  
Lake 首版按当前生产事实落盘，不额外伪造 `2026-01-05` 之前的历史分区。

## 5. 输入参数与导出范围

源站输入参数：

- `trade_date`
- `ts_code`
- `start_date`
- `end_date`
- `nums`
- `limit`
- `offset`

Lake 第一阶段仅支持：

- `--trade-date`
- `--start-date --end-date`

暂不支持：

- `--ts-code`
- `--nums`

原因：

- Lake 正式分区语义是“某交易日全市场 limit_step 快照”，不允许局部结果覆盖正式分区。

## 6. 读取模式

读取模式结论：`range_streaming_cursor`

理由：

1. 当前表很小，但为了和日频分区主线保持一致，仍统一使用区间流式读取。
2. 这样后续历史补链时无需再改读取模式。
3. 最终按 `trade_date` 聚合后逐日写分区。

允许的 SQL：

```sql
select
  ts_code,
  name,
  trade_date,
  nums
from raw_tushare.limit_step
where trade_date >= :start_date
  and trade_date <= :end_date
order by trade_date, ts_code;
```

## 7. 分区与空结果策略

正式分区：

```text
raw_tushare/limit_step/trade_date=YYYY-MM-DD/part-000.parquet
```

规则：

1. 只对本地交易日历中的开市日写正式分区。
2. 某个开市日若查询结果为 0，不写空分区，不覆盖已有分区。
3. 命令输出要明确 `skipped_replace=true`。

## 8. 命令设计

```bash
lake-console plan-sync limit_step --from prod-raw-db --trade-date 2026-04-30
lake-console sync-dataset limit_step --from prod-raw-db --trade-date 2026-04-30

lake-console plan-sync limit_step --from prod-raw-db --start-date 2026-01-05 --end-date 2026-04-30
lake-console sync-dataset limit_step --from prod-raw-db --start-date 2026-01-05 --end-date 2026-04-30
```

## 9. 验收口径

1. Parquet 字段必须与源站输出字段一致。
2. `trade_date` 必须是 Parquet `date`。
3. 不得包含 `api_name`、`fetched_at`、`raw_payload`。
4. Lake 首版历史起点按当前生产事实 `2026-01-05` 计，不伪造更早分区。
5. 交易日分区行数必须等于白名单 SQL 结果。
