# 股票技术面因子（专业版）Lake prod-raw-db 导出方案

状态：已落地（2026-05-09）

本文定义 `stk_factor_pro` 数据集从生产 `raw_tushare.stk_factor_pro` 只读导出到本地 Lake Parquet 的方案。

## 1. 目标

把生产库中已经落在 `raw_tushare.stk_factor_pro` 的 Tushare 原始股票技术面因子数据，按 Lake Console 的按日分区布局导出成本地 Parquet。

核心目标：

- 导出的 Parquet 字段必须与 Tushare `stk_factor_pro` 输出字段一致。
- 只访问生产库 `raw_tushare.stk_factor_pro`。
- 禁止 `select *`。
- 不把 `api_name`、`fetched_at`、`raw_payload` 写入 Lake。
- 按交易日生成正式分区。

## 2. 数据集基本信息

| 项 | 值 |
| --- | --- |
| Lake dataset_key | `stk_factor_pro` |
| 显示名 | 股票技术面因子（专业版） |
| Tushare api_name | `stk_factor_pro` |
| 源接口文档 | `docs/sources/tushare/股票数据/特色数据/0328_股票技术面因子(专业版).md` |
| 生产 raw 表 | `raw_tushare.stk_factor_pro` |
| Lake 目标层 | `raw` |
| Lake 目标路径 | `raw_tushare/stk_factor_pro/trade_date=YYYY-MM-DD/part-000.parquet` |
| 分区字段 | `trade_date` |
| 写入策略 | `replace_partition` |
| 导出来源 | `prod-raw-db` |

## 3. 字段白名单

Lake 字段白名单采用：

```text
src/foundation/datasets/definitions/market_equity.py
-> stk_factor_pro.source_fields
```

也就是当前生产 `DatasetDefinition` 定义的全量输出字段。  
这是一张超宽表，当前字段数约 `227` 列，包含：

1. 原始价格 / 成交量 / 成交额字段。
2. `hfq/qfq/bfq` 三套价格与技术指标字段。
3. 估值、市值、换手率、量比、复权因子等字段。

规则：

1. SQL 必须显式枚举这全量字段。
2. 禁止 `select *`。
3. 禁止导出：
   - `api_name`
   - `fetched_at`
   - `raw_payload`

## 4. 生产 raw 表审计

### 4.1 线上真实情况（2026-05-09）

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| 表存在 | 是 | `raw_tushare.stk_factor_pro` |
| schema | `raw_tushare` | 符合边界 |
| 行数 | `1796520` | 到 2026-05-08 |
| 日期范围 | `2025-01-02 ~ 2026-05-08` | 当前完整历史起点 |
| 交易日覆盖 | `323 / 323` | 当前范围内完整 |
| distinct `ts_code` | `5798` | 股票覆盖量 |
| 精确重复组 | `0` | `(ts_code, trade_date)` 无重复 |
| 系统字段 | 有 | `api_name`、`fetched_at`、`raw_payload` |

### 4.2 字段对账

远程 raw 表业务字段与当前生产 `DatasetDefinition.source_fields` 对齐。  
当前 Lake 只需要做：

1. 字段白名单显式投影。
2. 数值统一落为 DuckDB 友好的 `double`。
3. `trade_date` 统一落为 Parquet `date`。

## 5. 输入参数与导出范围

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

- 正式 Lake 分区语义是“某交易日全市场技术面因子快照”，不允许局部结果覆盖正式分区。

## 6. 读取模式

读取模式结论：`range_streaming_cursor`

理由：

1. 行数接近 `180` 万，且字段很宽，禁止 `fetchall`。
2. 区间导出必须单连接、只读事务、服务端游标流式读取。
3. 最终按 `trade_date` 聚合后逐日写分区。

允许的 SQL 规则：

1. `select` 必须显式枚举 `source_fields` 的全部列。
2. `where trade_date between :start_date and :end_date`
3. `order by trade_date, ts_code`

## 7. 分区与空结果策略

正式分区：

```text
raw_tushare/stk_factor_pro/trade_date=YYYY-MM-DD/part-000.parquet
```

规则：

1. 只对本地交易日历中的开市日写正式分区。
2. 某个开市日若查询结果为 0，不写空分区，不覆盖已有分区。
3. `trade_date` 必须是 Parquet `date`。

## 8. 命令设计（占位）

```bash
lake-console plan-sync stk_factor_pro --from prod-raw-db --trade-date 2026-05-08
lake-console sync-dataset stk_factor_pro --from prod-raw-db --trade-date 2026-05-08

lake-console plan-sync stk_factor_pro --from prod-raw-db --start-date 2025-01-02 --end-date 2026-05-08
lake-console sync-dataset stk_factor_pro --from prod-raw-db --start-date 2025-01-02 --end-date 2026-05-08
```

## 9. 验收口径

1. Parquet 字段必须与当前 `DatasetDefinition.source_fields` 一致。
2. `trade_date` 必须是 Parquet `date`。
3. 不得包含 `api_name`、`fetched_at`、`raw_payload`。
4. 交易日分区行数必须等于白名单 SQL 结果。
