# 指数月线 Lake prod-core-db 导出方案

状态：已落地（2026-05-09）

本文定义 `index_monthly` 数据集导出到本地 Lake 的方案。  
**本数据集不走 `prod-raw-db`，而是按当前已确认的“最佳事实优先”口径，从生产 `core_serving.index_monthly_serving` 读取，再映射回 Tushare `index_monthly` 字段口径写入 Lake。**

## 1. 为什么这次不读 raw

这次的选择标准不是“谁更像源站”，而是：

```text
谁是当前可用的最佳事实源。
```

对 `index_monthly` 而言：

1. `raw_tushare.index_monthly_bar` 当前每个月锚点只覆盖约 `560` 个指数代码。
2. `core_serving.index_monthly_serving` 会在 active 池门禁后，对缺失指数用 `index_daily` 做 `derived_daily` 补齐。
3. 最新月锚点上：
   - raw：`560` 个代码
   - serving：`1130` 个代码
   - 来源构成：`api=560`，`derived_daily=570`

因此，本数据集在 Lake 中应以 `core_serving.index_monthly_serving` 作为读取事实源。

## 2. 目标

把生产 `core_serving.index_monthly_serving` 中已经修复过的指数月线数据，按 Lake Console 的月锚点分区布局导出到本地 Parquet，同时保持 Lake 对外字段仍是 Tushare `index_monthly` 的输出字段口径。

核心目标：

- 读取源是 `core_serving.index_monthly_serving`
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
- 不把 `period_start_date`、`source`、`created_at`、`updated_at` 导入 Lake

## 3. 数据集基本信息

| 项 | 值 |
| --- | --- |
| Lake dataset_key | `index_monthly` |
| 显示名 | 指数月线行情 |
| Tushare api_name | `index_monthly` |
| 源接口文档 | `docs/sources/tushare/指数专题/0172_指数月线行情.md` |
| 生产读取表 | `core_serving.index_monthly_serving` |
| 生产 raw 表 | `raw_tushare.index_monthly_bar` |
| Lake 目标层 | `raw` |
| Lake 目标路径 | `raw_tushare/index_monthly/trade_date=YYYY-MM-DD/part-000.parquet` |
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
| `change` | 涨跌点位 |
| `pct_chg` | 涨跌幅 |
| `vol` | 成交量（手） |
| `amount` | 成交额（千元） |

### 4.2 serving 层真实字段（2026-05-09）

`core_serving.index_monthly_serving` 真实列：

- `ts_code`
- `period_start_date`
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

| serving 字段 | Lake 字段 | 处理 |
| --- | --- | --- |
| `change_amount` | `change` | 重命名映射 |
| `period_start_date` | 不导出 | 排除 |
| `source` | 不导出 | 排除 |
| `created_at` | 不导出 | 排除 |
| `updated_at` | 不导出 | 排除 |

## 5. 线上真实审计

### 5.1 serving 表事实（2026-05-09）

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| serving 表存在 | 是 | `core_serving.index_monthly_serving` |
| raw 表存在 | 是 | `raw_tushare.index_monthly_bar` |
| serving 行数 | `80784` | 到 2026-04-30 |
| raw 行数 | `40813` | 到 2026-04-30 |
| serving 日期范围 | `2020-01-23 ~ 2026-04-30` | 月锚点连续 |
| raw 日期范围 | `2020-01-23 ~ 2026-04-30` | 月锚点连续 |
| serving 去重情况 | `0` | `(ts_code, trade_date)` 无重复 |
| raw 去重情况 | `0` | `(ts_code, trade_date)` 无重复 |

### 5.2 最新月锚点对比

最新锚点 `2026-04-30`：

- `raw_tushare.index_monthly_bar`：`560` 个代码
- `core_serving.index_monthly_serving`：`1130` 个代码

来源构成：

- `api`：`560`
- `derived_daily`：`570`

### 5.3 锚点口径

远程真实数据表明：

1. 月线锚点与“月最后开市日”一致。
2. 当前没有额外的月末后脏锚点。

因此，Lake 可直接按 serving 表中的 `trade_date` 作为正式月分区锚点。

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

- 正式 Lake 分区语义是某个月锚点的全市场月线快照，不允许局部结果覆盖正式分区。

## 7. 读取模式

读取模式结论：`range_streaming_cursor`

理由：

1. 行数八万级，不需要 `fetchall`。
2. 允许单连接、只读事务、服务端游标流式读取。
3. 最终按 `trade_date` 聚合后逐月写入。

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
from core_serving.index_monthly_serving
where trade_date >= :start_date
  and trade_date <= :end_date
order by trade_date, ts_code;
```

## 8. 分区策略

正式分区：

```text
raw_tushare/index_monthly/trade_date=YYYY-MM-DD/part-000.parquet
```

规则：

1. 只允许月最后开市日生成正式分区。
2. 某个月锚点若查询结果为 0，不写空分区，不覆盖已有分区。
3. Lake 不再尝试复现 raw 的 `560` 代码子集，而是忠实导出 serving 已修复结果。

## 9. 进入实现前的额外门禁

这是本数据集的强门禁：

1. `prod-core-db` 只读例外范围必须从 `index_daily` 扩展到 `index_monthly`。
2. `lake_console` 的字段白名单、CLI、Planner、Strategy、测试都必须按 serving 事实源扩展。
3. Lake raw 仍不得导出 `period_start_date`、`source`、`created_at`、`updated_at`。

## 10. 命令设计（占位）

```bash
lake-console plan-sync index_monthly --from prod-core-db --trade-date 2026-04-30
lake-console sync-dataset index_monthly --from prod-core-db --trade-date 2026-04-30

lake-console plan-sync index_monthly --from prod-core-db --start-date 2026-01-01 --end-date 2026-04-30
lake-console sync-dataset index_monthly --from prod-core-db --start-date 2026-01-01 --end-date 2026-04-30
```

## 11. 验收口径

1. Lake 行数必须对齐 serving 白名单 SQL，而不是 raw。
2. Parquet 字段必须仍然叫 `change`，不能泄露 `change_amount`。
3. 不得导出 `period_start_date`、`source`、`created_at`、`updated_at`。
4. 月锚点正式分区只允许落在月最后开市日。
