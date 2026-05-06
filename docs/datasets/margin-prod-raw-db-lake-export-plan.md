# 融资融券汇总 Lake prod-raw-db 导出方案

状态：已落地（2026-05-06）

本文定义 `margin` 数据集从生产 `raw_tushare.margin` 只读导出到本地 Lake Parquet 的方案。该方案只覆盖 `prod-raw-db` 导出模式，不改变现有 Tushare API 下载链路。

## 1. 目标

把生产库中已经落在 `raw_tushare.margin` 的 Tushare 原始融资融券汇总数据，按 Lake Console 的按日分区布局导出成本地 Parquet。

核心目标：

- 导出的 Parquet 字段必须与 Tushare `margin` 输出参数一致。
- 只访问生产库 `raw_tushare.margin`。
- 禁止 `select *`。
- 不把 `api_name`、`fetched_at`、`raw_payload` 写入 Lake。
- 按交易日生成正式分区。

## 2. 数据集基本信息

| 项 | 值 |
| --- | --- |
| Lake dataset_key | `margin` |
| 显示名 | 融资融券汇总 |
| Tushare api_name | `margin` |
| 源接口文档 | `docs/sources/tushare/股票数据/两融及转融通/0058_融资融券交易汇总.md` |
| 生产 raw 表 | `raw_tushare.margin` |
| Lake 目标层 | `raw` |
| Lake 目标路径 | `raw_tushare/margin/trade_date=YYYY-MM-DD/part-000.parquet` |
| 分区字段 | `trade_date` |
| 写入策略 | `replace_partition` |
| 导出来源 | `prod-raw-db` |

## 3. 字段白名单

| 字段 | Tushare 输出类型 | raw 表类型 | Lake 类型 |
| --- | --- | --- | --- |
| `trade_date` | `str` | `date` | `date` |
| `exchange_id` | `str` | `varchar` | `string` |
| `rzye` | `float` | `numeric` | `double` |
| `rzmre` | `float` | `numeric` | `double` |
| `rzche` | `float` | `numeric` | `double` |
| `rqye` | `float` | `numeric` | `double` |
| `rqmcl` | `float` | `numeric` | `double` |
| `rzrqye` | `float` | `numeric` | `double` |
| `rqyl` | `float` | `numeric` | `double` |

禁止导出：

- `api_name`
- `fetched_at`
- `raw_payload`

## 4. 生产 raw 表审计

### 4.1 线上真实情况（2026-05-06）

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| 表存在 | 是 | `raw_tushare.margin` |
| schema | `raw_tushare` | 符合边界 |
| 行数 | `956` | 到 2026-04-30 |
| 日期范围 | `2025-01-02 ~ 2026-04-30` | 当前库内有效历史范围 |
| 系统字段 | 有 | `api_name`、`fetched_at`、`raw_payload` |
| 主业务键重复 | `0` | `(trade_date, exchange_id)` 无重复 |
| `exchange_id` 实际值 | `BSE,SSE,SZSE` | 当前只有 3 个交易所枚举 |

### 4.2 字段对账

源站输出字段与生产 raw 字段完全对齐，仅数值字段统一落为 Lake `double`，`trade_date` 统一落为 Parquet `date`。

## 5. 输入参数与导出范围

源站输入参数：

- `trade_date`
- `start_date`
- `end_date`
- `exchange_id`
- `limit`
- `offset`

Lake 第一阶段仅支持：

- `--trade-date`
- `--start-date --end-date`

暂不支持：

- `--exchange-id`

原因：

- 正式分区语义是某交易日全交易所融资融券汇总，不允许局部交易所结果覆盖正式分区。

## 6. 读取模式

读取模式结论：`range_streaming_cursor`

理由：

1. 虽然总行数很小，但它仍然是标准日频事实表，继续沿用 by-date 流式模板更稳。
2. 统一单日点查 + 区间流式读取，不为小表再引入第二套执行分支。
3. 每个交易日最多只有少量交易所记录，落盘简单，重跑成本低。

允许的 SQL 形态：

```sql
select
  trade_date,
  exchange_id,
  rzye,
  rzmre,
  rzche,
  rqye,
  rqmcl,
  rzrqye,
  rqyl
from raw_tushare.margin
where trade_date >= :start_date
  and trade_date <= :end_date
order by trade_date, exchange_id;
```

## 7. 分区策略

正式分区：

```text
raw_tushare/margin/trade_date=YYYY-MM-DD/part-000.parquet
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
