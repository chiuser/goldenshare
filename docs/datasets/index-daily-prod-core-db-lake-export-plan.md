# 指数日线 Lake prod-core-db 导出方案

状态：已落地（2026-05-06 首次实跑通过）

本文定义 `index_daily` 数据集导出到本地 Lake 的特殊方案。  
**本数据集不走 `prod-raw-db`，而是按已拍板要求从生产 `core_serving.index_daily_serving` 读取，再映射回 Tushare `index_daily` 原始字段口径写入 Lake。**

这是 R2 第一批里唯一一个“读生产 core 层”的例外项。

## 1. 为什么它是例外

你已经明确拍板：

```text
index_daily 必须从 core 层读，不允许从 raw 层读。
```

这意味着：

1. 它不能直接复用现有 `prod-raw-db` 规则模板。
2. 它需要单独定义一个 `prod-core-db` 只读导出模式。
3. 进入实现前，Lake 的隔离规则和模板文档都要先补充这一条例外。

## 2. 目标

把生产 `core_serving.index_daily_serving` 中的指数日线数据，按 Lake Console 的按日分区布局导出到本地 Parquet，同时保持 Lake 字段仍然是 Tushare `index_daily` 的原始输出字段口径。

核心目标：

- 读取源是 `core_serving.index_daily_serving`
- Lake 字段仍使用：
  - `ts_code`
  - `trade_date`
  - `open`
  - `high`
  - `low`
  - `close`
  - `pre_close`
  - `change`
  - `pct_chg`
  - `vol`
  - `amount`
- `core_serving` 中的 `change_amount` 必须映射回 Lake 字段 `change`
- 不把 `source`、`created_at`、`updated_at` 导入 Lake

## 3. 数据集基本信息

| 项 | 值 |
| --- | --- |
| Lake dataset_key | `index_daily` |
| 显示名 | 指数日线行情 |
| Tushare api_name | `index_daily` |
| 源接口文档 | `docs/sources/tushare/指数专题/0095_指数日线行情.md` |
| 生产读取表 | `core_serving.index_daily_serving` |
| 原始 raw 表 | `raw_tushare.index_daily` |
| Lake 目标层 | `raw` |
| Lake 目标路径 | `raw_tushare/index_daily/trade_date=YYYY-MM-DD/part-000.parquet` |
| 分区字段 | `trade_date` |
| 写入策略 | `replace_partition` |
| 导出来源 | `prod-core-db` |

## 4. 字段口径

### 4.1 Tushare 原始输出字段

| Lake 字段 | Tushare 含义 |
| --- | --- |
| `ts_code` | TS 指数代码 |
| `trade_date` | 交易日 |
| `open` | 开盘点位 |
| `high` | 最高点位 |
| `low` | 最低点位 |
| `close` | 收盘点位 |
| `pre_close` | 昨日收盘点 |
| `change` | 涨跌点 |
| `pct_chg` | 涨跌幅 |
| `vol` | 成交量（手） |
| `amount` | 成交额（千元） |

### 4.2 core 层真实字段（2026-05-06）

`core_serving.index_daily_serving` 真实列：

- `ts_code`
- `trade_date`
- `open`
- `high`
- `low`
- `close`
- `pre_close`
- `change_amount`
- `pct_chg`
- `vol`
- `amount`
- `source`
- `created_at`
- `updated_at`

关键差异：

| core 字段 | Lake 字段 | 处理 |
| --- | --- | --- |
| `change_amount` | `change` | 重命名映射 |
| `source` | 不导出 | 排除 |
| `created_at` | 不导出 | 排除 |
| `updated_at` | 不导出 | 排除 |

## 5. 线上真实审计

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| core 表存在 | 是 | `core_serving.index_daily_serving` |
| raw 表存在 | 是 | `raw_tushare.index_daily` |
| core 行数 | `1636390` | 到 2026-04-30 |
| raw 行数 | `1636390` | 当前与 core 一致 |
| core 日期范围 | `2020-01-02 ~ 2026-04-30` | 与 raw 一致 |
| `source` 实际取值 | `api` | 当前单一取值 |

结论：

1. 当前 core 行数与 raw 行数一致。
2. 你要求读 core 层，因此本方案以后以 `core_serving.index_daily_serving` 为唯一读取事实源。
3. Lake 输出仍保持 Tushare 原始字段名，不把 core 层字段名直接暴露出去。

## 6. 输入参数与导出范围

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

- 正式 Lake 分区语义是某交易日全市场指数日线快照，不允许局部结果覆盖正式分区。

## 7. 读取模式

读取模式结论：`range_streaming_cursor`

理由：

1. 行数已达一百六十多万，没必要逐日单 SQL。
2. 允许单连接、只读事务、服务端游标流式读取。
3. 最终按 `trade_date` 聚合后逐日写入。

允许的 SQL：

```sql
select
  ts_code,
  trade_date,
  open,
  high,
  low,
  close,
  pre_close,
  change_amount as change,
  pct_chg,
  vol,
  amount
from core_serving.index_daily_serving
where trade_date >= :start_date
  and trade_date <= :end_date
order by trade_date, ts_code;
```

## 8. 分区策略

正式分区：

```text
raw_tushare/index_daily/trade_date=YYYY-MM-DD/part-000.parquet
```

规则：

1. 只对本地交易日历中的开市日写正式分区。
2. 某个开市日查询结果为 0，不写空分区，不覆盖已有分区。
3. 当前读 core 层，不再关心 raw 层是否存在额外脏行。

## 9. 进入实现前的额外门禁

这是本数据集的强门禁：

1. 先补 Lake `prod-core-db` 只读例外规则，不能直接拿 `prod-raw-db` 代码硬改。
2. 先在模板或接入规则文档中写明：
   - 哪些数据集允许从 core 层读
   - 为什么允许
   - 字段映射如何回到源站口径
3. 未完成上述规则收口前，不进入实现。

## 10. 命令设计（占位）

等 `prod-core-db` 只读模式落地后，命令应类似：

```bash
lake-console plan-sync index_daily --from prod-core-db --trade-date 2026-04-30
lake-console sync-dataset index_daily --from prod-core-db --trade-date 2026-04-30
```

## 11. 验收口径

1. Lake Parquet 字段必须仍然叫 `change`，不能泄露 `change_amount`。
2. 不得导出 `source`、`created_at`、`updated_at`。
3. `trade_date` 必须是 Parquet `date`。
4. 某交易日 Lake 分区行数必须等于 core 白名单 SQL 结果。

## 12. 首次实跑结果（2026-05-06）

```bash
lake-console sync-dataset index_daily --from prod-core-db --trade-date 2026-04-30
```

结果：

- `fetched_rows = 1130`
- `written_rows = 1130`
- 输出文件：
  - `raw_tushare/index_daily/trade_date=2026-04-30/part-000.parquet`
- Parquet 校验：
  - `trade_date` 类型为 `date32[day]`
  - 字段名包含 `change`
  - 字段名不包含 `change_amount`
  - 行数为 `1130`
