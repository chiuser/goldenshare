# 股票周线 Lake prod-raw-db 导出方案

状态：已实现（2026-05-08 已完成 lake_console 接入、测试与最小真实逻辑验证）

本文定义 `stk_period_bar_week` 数据集从生产 `raw_tushare.stk_period_bar` 只读导出到本地 Lake Parquet 的方案。该方案只覆盖 `prod-raw-db` 导出模式，不改变现有生产同步链路。

## 1. 目标

把生产库中已经落在 `raw_tushare.stk_period_bar`、且 `freq='week'` 的 Tushare 股票周线原始事实，按 Lake Console 的按锚点日期分区布局导出成本地 Parquet。

核心目标：

- 导出的 Parquet 字段必须与 Tushare `stk_weekly_monthly` 周线输出参数一致。
- 只访问生产库 `raw_tushare.stk_period_bar`。
- 必须显式过滤 `freq='week'`。
- 禁止 `select *`。
- 不把 `api_name`、`fetched_at`、`raw_payload` 写入 Lake。
- 正式分区锚点遵循 `date_axis=natural_day`、`bucket_rule=week_friday`。
- 不引入任何指数 active pool 或证券池过滤。

## 2. 数据集基本信息

| 项 | 值 |
| --- | --- |
| Lake dataset_key | `stk_period_bar_week` |
| 显示名 | 股票周线行情 |
| Tushare api_name | `stk_weekly_monthly` |
| 源接口文档 | `docs/sources/tushare/股票数据/行情数据/0336_股票周_月线行情(每日更新).md` |
| 生产 raw 表 | `raw_tushare.stk_period_bar` |
| 生产 serving 表 | `core_serving.stk_period_bar` |
| 生产 row_identity_filters | `freq='week'` |
| Lake 目标层 | `raw` |
| Lake 目标路径 | `raw_tushare/stk_period_bar_week/trade_date=YYYY-MM-DD/part-000.parquet` |
| 分区字段 | `trade_date` |
| 写入策略 | `replace_partition` |
| 导出来源 | `prod-raw-db` |

## 3. 生产实现审计结论

### 3.1 当前生产实现（2026-05-08）

已核对：

- `src/foundation/datasets/definitions/market_equity.py`
- `src/foundation/ingestion/request_builders.py`
- `src/foundation/ingestion/unit_planner.py`
- `src/foundation/ingestion/writer.py`

结论：

1. 本数据集不是指数周线，不走 `ops.index_series_active`。
2. `planning.universe_policy = none`，不会按任何 active pool 扇开。
3. 请求参数只依赖：
   - `freq='week'`
   - 可选 `ts_code`
   - `trade_date` / `start_date` / `end_date`
4. 写入路径是 `raw_core_upsert`，不是指数周期专用 writer。
5. 生产 raw / serving 共用表，靠 `freq='week'` 与月线区分。

### 3.2 时间语义

当前唯一口径以 [股票周/月线同步逻辑说明](/Users/congming/github/goldenshare/docs/datasets/equity-weekly-monthly-sync-logic.md) 为准：

1. `trade_date` 字段名沿用源接口，但业务语义不是“最后一个交易日”。
2. 股票周线使用自然周周五作为锚点日期。
3. Lake 不得把本数据集重新解释成 `trade_open_day` 模型。

## 4. 字段白名单

| 字段 | Tushare 输出类型 | raw 表类型 | Lake 类型 |
| --- | --- | --- | --- |
| `ts_code` | `str` | `varchar` | `string` |
| `trade_date` | `str` | `date` | `date` |
| `end_date` | `str` | `date` | `date` |
| `freq` | `str` | `varchar` | `string` |
| `open` | `float` | `numeric` | `double` |
| `high` | `float` | `numeric` | `double` |
| `low` | `float` | `numeric` | `double` |
| `close` | `float` | `numeric` | `double` |
| `pre_close` | `float` | `numeric` | `double` |
| `vol` | `float` | `numeric` | `double` |
| `amount` | `float` | `numeric` | `double` |
| `change` | `float` | `numeric` | `double` |
| `pct_chg` | `float` | `numeric` | `double` |

禁止导出：

- `api_name`
- `fetched_at`
- `raw_payload`

说明：

1. `freq` 必须保留，它是源站输出字段，也是共表事实区分字段。
2. Lake 虽然按 `dataset_key=stk_period_bar_week` 拆目录，但不能把 `freq` 从事实字段里删掉。

## 5. 生产 raw 表审计

### 5.1 线上真实情况（2026-05-08）

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| 表存在 | 是 | `raw_tushare.stk_period_bar` |
| 行数 | `2,778,940` | 仅 `freq='week'` |
| 日期范围 | `2010-01-01 ~ 2026-05-01` | 当前生产周线历史窗口 |
| 锚点日期数 | `836` | 去重后的周锚点数量 |
| 股票数 | `5,556` | `freq='week'` 范围内 distinct `ts_code` |
| 精确重复组 | `0` | 按当前源站业务字段口径核对 |
| 非周五锚点 | `0` | 当前未发现异常周锚点 |
| 系统字段 | 有 | `api_name`、`fetched_at`、`raw_payload` |

### 5.2 字段对账

源站输出字段、生产 raw 业务字段与 Lake 白名单当前一致。  
本数据集不需要额外引入请求派生维度，也不需要 core 字段映射。

## 6. 输入参数与导出范围

源站输入参数：

- `ts_code`
- `trade_date`
- `start_date`
- `end_date`
- `freq`
- `limit`
- `offset`

Lake 第一阶段仅支持：

- `--trade-date`
- `--start-date --end-date`

暂不支持：

- `--ts-code`

原因：

- 正式 Lake 分区语义是“某个周锚点日期的全市场周线快照”，不允许局部结果覆盖正式分区。

## 7. 读取模式

读取模式结论：`range_streaming_cursor`

理由：

1. 数据量已到两百多万行，不适合 `fetchall`。
2. 单连接、只读事务、服务端游标流式读取最稳。
3. 最终按 `trade_date` 聚合后逐日写分区。

允许的 SQL：

```sql
select
  ts_code,
  trade_date,
  end_date,
  freq,
  open,
  high,
  low,
  close,
  pre_close,
  vol,
  amount,
  change,
  pct_chg
from raw_tushare.stk_period_bar
where freq = 'week'
  and trade_date >= :start_date
  and trade_date <= :end_date
order by trade_date, ts_code;
```

## 8. 分区与空结果策略

正式分区：

```text
raw_tushare/stk_period_bar_week/trade_date=YYYY-MM-DD/part-000.parquet
```

规则：

1. 只对符合 `week_friday` 锚点的日期写正式分区。
2. 某个输入日期若不是自然周周五，查询结果为 0，则不写空分区，不覆盖已有分区。
3. Range 导出只写查询结果里真实存在的周锚点日期，不为中间自然日制造空分区。
4. `trade_date` 与 `end_date` 都写 Parquet `date`。

## 9. 命令设计

```bash
lake-console plan-sync stk_period_bar_week --from prod-raw-db --trade-date 2026-05-01
lake-console sync-dataset stk_period_bar_week --from prod-raw-db --trade-date 2026-05-01

lake-console plan-sync stk_period_bar_week --from prod-raw-db --start-date 2026-01-01 --end-date 2026-04-30
lake-console sync-dataset stk_period_bar_week --from prod-raw-db --start-date 2026-01-01 --end-date 2026-04-30
```

## 10. 验收口径

1. Parquet 字段必须与源站周线输出字段一致。
2. 必须包含 `freq='week'` 字段。
3. `trade_date` 和 `end_date` 必须是 Parquet `date`。
4. 不得包含 `api_name`、`fetched_at`、`raw_payload`。
5. 某周锚点分区行数必须等于白名单 SQL 结果。
6. 不得引入 active pool、指数池或证券池额外过滤。
