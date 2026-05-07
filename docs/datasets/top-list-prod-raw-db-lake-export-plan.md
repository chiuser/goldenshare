# 龙虎榜 Lake prod-raw-db 导出方案

状态：已落地（2026-05-07，后端接入完成，单日真实验证通过）

本文定义 `top_list` 数据集从生产 `raw_tushare.top_list` 只读导出到本地 Lake Parquet 的方案。该方案只覆盖 `prod-raw-db` 导出模式，不改变现有生产同步链路。

## 1. 目标

把生产库中已经落在 `raw_tushare.top_list` 的 Tushare 原始龙虎榜每日明细数据，按 Lake Console 的按日分区布局导出成本地 Parquet。

核心目标：

- 导出的 Parquet 字段必须与 Tushare `top_list` 输出参数一致。
- 只访问生产库 `raw_tushare.top_list`。
- 禁止 `select *`。
- 不把 `payload_hash`、`reason_hash`、`api_name`、`fetched_at`、`raw_payload` 写入 Lake。
- 按交易日生成正式分区。

## 2. 数据集基本信息

| 项 | 值 |
| --- | --- |
| Lake dataset_key | `top_list` |
| 显示名 | 龙虎榜 |
| Tushare api_name | `top_list` |
| 源接口文档 | `docs/sources/tushare/股票数据/打板专题数据/0106_龙虎榜每日明细.md` |
| 生产 raw 表 | `raw_tushare.top_list` |
| Lake 目标层 | `raw` |
| Lake 目标路径 | `raw_tushare/top_list/trade_date=YYYY-MM-DD/part-000.parquet` |
| 分区字段 | `trade_date` |
| 写入策略 | `replace_partition` |
| 导出来源 | `prod-raw-db` |

## 3. 字段白名单

| 字段 | Tushare 输出类型 | raw 表类型 | Lake 类型 |
| --- | --- | --- | --- |
| `trade_date` | `str` | `date` | `date` |
| `ts_code` | `str` | `varchar(16)` | `string` |
| `name` | `str` | `varchar` | `string` |
| `close` | `float` | `numeric` | `double` |
| `pct_change` | `float` | `numeric` | `double` |
| `turnover_rate` | `float` | `numeric` | `double` |
| `amount` | `float` | `numeric` | `double` |
| `l_sell` | `float` | `numeric` | `double` |
| `l_buy` | `float` | `numeric` | `double` |
| `l_amount` | `float` | `numeric` | `double` |
| `net_amount` | `float` | `numeric` | `double` |
| `net_rate` | `float` | `numeric` | `double` |
| `amount_rate` | `float` | `numeric` | `double` |
| `float_values` | `float` | `numeric` | `double` |
| `reason` | `str` | `text` | `string` |

禁止导出：

- `payload_hash`
- `reason_hash`
- `api_name`
- `fetched_at`
- `raw_payload`

## 4. 生产 raw 表审计

### 4.1 线上真实情况（2026-05-07）

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| 表存在 | 是 | `raw_tushare.top_list` |
| schema | `raw_tushare` | 符合边界 |
| 行数 | `172138` | 到 2026-05-07 |
| 日期范围 | `2016-01-04 ~ 2026-05-07` | 当前生产 raw 历史起点晚于源站文档声称的 2005 年 |
| 交易日覆盖 | `2509 / 2509` | 当前范围内完整 |
| 精确重复组 | `0` | 业务字段组合未发现精确重复 |
| 额外业务字段 | 有 | `payload_hash`、`reason_hash` |
| 系统字段 | 有 | `api_name`、`fetched_at`、`raw_payload` |

### 4.2 字段对账

源站输出字段与生产 raw 业务字段对齐。  
注意：

1. 生产 raw 额外保存了 `payload_hash`、`reason_hash`，用于生产侧去重/审计辅助。
2. 这两个字段不是源站输出字段，只能用于生产侧内部治理，不得进入 Lake raw。
3. Lake 首版按当前生产事实落盘，不额外伪造 `2016-01-04` 之前的历史分区。

## 5. 输入参数与导出范围

源站输入参数：

- `trade_date`（源接口必选）
- `ts_code`
- `limit`
- `offset`

Lake 第一阶段支持：

- `--trade-date`
- `--start-date --end-date`

暂不支持：

- `--ts-code`

说明：

- 源接口原生以单交易日拉取为主。
- Lake `prod-raw-db` 导出第一阶段允许按日期区间导出，是基于生产 raw 已形成连续交易日事实后的本地导出能力，不改变源接口原生请求模型。

## 6. 读取模式

读取模式结论：`range_streaming_cursor`

理由：

1. 历史已超过十七万行，继续沿用区间流式读取更稳。
2. 区间导出必须单连接、只读事务、服务端游标流式读取。
3. 最终按 `trade_date` 聚合后逐日写分区。

允许的 SQL：

```sql
select
  trade_date,
  ts_code,
  name,
  close,
  pct_change,
  turnover_rate,
  amount,
  l_sell,
  l_buy,
  l_amount,
  net_amount,
  net_rate,
  amount_rate,
  float_values,
  reason
from raw_tushare.top_list
where trade_date >= :start_date
  and trade_date <= :end_date
order by trade_date, ts_code, reason;
```

## 7. 分区与空结果策略

正式分区：

```text
raw_tushare/top_list/trade_date=YYYY-MM-DD/part-000.parquet
```

规则：

1. 只对本地交易日历中的开市日写正式分区。
2. 某个开市日若查询结果为 0，不写空分区，不覆盖已有分区。
3. 命令输出要明确 `skipped_replace=true`。

## 8. 命令设计

```bash
lake-console plan-sync top_list --from prod-raw-db --trade-date 2026-05-07
lake-console sync-dataset top_list --from prod-raw-db --trade-date 2026-05-07

lake-console plan-sync top_list --from prod-raw-db --start-date 2026-04-01 --end-date 2026-04-30
lake-console sync-dataset top_list --from prod-raw-db --start-date 2026-04-01 --end-date 2026-04-30
```

## 9. 验收口径

1. Parquet 字段必须与源站输出字段一致。
2. `trade_date` 必须是 Parquet `date`。
3. 不得包含 `payload_hash`、`reason_hash`、`api_name`、`fetched_at`、`raw_payload`。
4. Lake 首版历史起点按当前生产事实 `2016-01-04` 计，不伪造更早分区。
5. 交易日分区行数必须等于白名单 SQL 结果。
