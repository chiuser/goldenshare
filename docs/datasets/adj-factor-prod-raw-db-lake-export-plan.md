# 复权因子 Lake prod-raw-db 导出方案

状态：已落地（2026-05-06 首次实跑通过）

本文定义 `adj_factor` 数据集从生产 `raw_tushare.adj_factor` 只读导出到本地 Lake Parquet 的方案。该方案只覆盖 `prod-raw-db` 导出模式，不改变现有 Tushare API 下载链路。

## 1. 目标

把生产库中已经落在 `raw_tushare.adj_factor` 的 Tushare 原始复权因子数据，按 Lake Console 的按日分区布局导出成本地 Parquet。

核心目标：

- 避免本地重复请求 Tushare API。
- 导出的 Parquet 字段必须与 Tushare `adj_factor` 输出参数一致。
- 只访问生产库 `raw_tushare.adj_factor`。
- 禁止 `select *`，必须按字段白名单投影。
- 不把 `api_name`、`fetched_at`、`raw_payload` 写入 Lake。
- 只为本地交易日历中的开市日生成正式分区；非交易日脏行只能忽略，不得生成正式分区。

## 2. 数据集基本信息

| 项 | 值 |
| --- | --- |
| Lake dataset_key | `adj_factor` |
| 显示名 | 复权因子 |
| Tushare api_name | `adj_factor` |
| 源接口文档 | `docs/sources/tushare/股票数据/行情数据/0028_复权因子.md` |
| 生产 raw 表 | `raw_tushare.adj_factor` |
| Lake 目标层 | `raw` |
| Lake 目标路径 | `raw_tushare/adj_factor/trade_date=YYYY-MM-DD/part-000.parquet` |
| 分区字段 | `trade_date` |
| 写入策略 | `replace_partition` |
| 导出来源 | `prod-raw-db` |

## 3. 字段白名单

| 字段 | Tushare 输出类型 | raw 表类型 | Lake 类型 | 是否导出 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `ts_code` | `str` | `varchar(16)` | `string` | 是 | 股票代码 |
| `trade_date` | `str` | `date` | `date` | 是 | 交易日期 |
| `adj_factor` | `float` | `numeric` | `double` | 是 | 复权因子 |

明确禁止导出的系统字段：

- `api_name`
- `fetched_at`
- `raw_payload`

## 4. 生产 raw 表审计

### 4.1 线上真实情况（2026-05-06）

| 检查项 | 结果 | 说明 |
| --- | --- | --- |
| 表存在 | 是 | `raw_tushare.adj_factor` |
| schema | `raw_tushare` | 符合 prod-raw-db 边界 |
| 行数 | `14512019` | 到 2026-04-30 |
| 日期范围 | `2010-01-04 ~ 2026-04-30` | 与股票日频历史相符 |
| 系统字段 | 有 | `api_name`、`fetched_at`、`raw_payload` |
| 非开市日脏行 | `2` | 只出现在非交易日，不能落正式分区 |

### 4.2 字段对账

| 源站字段 | raw 表字段 | raw 类型 | Lake 类型 | 状态 | 处理策略 |
| --- | --- | --- | --- | --- | --- |
| `ts_code` | `ts_code` | `varchar` | `string` | 匹配 | 直接投影 |
| `trade_date` | `trade_date` | `date` | `date` | 匹配 | 直接投影 |
| `adj_factor` | `adj_factor` | `numeric` | `double` | 类型差异 | 写入时转 `double` |

### 4.3 首次实跑结果（2026-05-06）

```bash
lake-console sync-dataset adj_factor --from prod-raw-db --trade-date 2026-04-30
```

结果：

- `fetched_rows = 5518`
- `written_rows = 5518`
- 输出文件：
  - `raw_tushare/adj_factor/trade_date=2026-04-30/part-000.parquet`
- Parquet 校验：
  - `trade_date` 类型为 `date32[day]`
  - 行数为 `5518`

## 5. 输入参数与导出范围

源站输入参数：

- `ts_code`
- `trade_date`
- `start_date`
- `end_date`
- `limit`
- `offset`

本地 Lake 第一阶段只支持：

- `--trade-date`
- `--start-date --end-date`

暂不支持：

- `--ts-code`

原因：

- Lake 目标是按交易日生成全市场分区，不做单证券局部覆盖。

## 6. 读取模式

读取模式结论：`range_streaming_cursor`

理由：

1. 行数已达一千四百多万，禁止 `fetchall`。
2. 区间导出不应拆成“每天一个连接、每天一条 SQL”。
3. 应使用单连接、只读事务、服务端游标、按 `trade_date, ts_code` 排序流式读取。

允许的 SQL：

```sql
select
  ts_code,
  trade_date,
  adj_factor
from raw_tushare.adj_factor
where trade_date >= :start_date
  and trade_date <= :end_date
order by trade_date, ts_code;
```

单日模式：

```sql
select
  ts_code,
  trade_date,
  adj_factor
from raw_tushare.adj_factor
where trade_date = :trade_date
order by ts_code;
```

## 7. 分区与脏数据处理

正式分区仍按：

```text
raw_tushare/adj_factor/trade_date=YYYY-MM-DD/part-000.parquet
```

强规则：

1. 只有本地交易日历中的开市日，才允许写正式分区。
2. `raw_tushare.adj_factor` 中混入的非交易日行，一律忽略。
3. 非交易日脏行不得生成正式目录，也不得影响日期范围统计。
4. 如果某个开市日查询结果为 0：
   - 不写空分区
   - 不覆盖已有分区
   - 在命令结果里明确标记 `skipped_replace=true`

## 8. 命令设计

```bash
lake-console plan-sync adj_factor --from prod-raw-db --trade-date 2026-04-30
lake-console sync-dataset adj_factor --from prod-raw-db --trade-date 2026-04-30

lake-console plan-sync adj_factor --from prod-raw-db --start-date 2026-04-01 --end-date 2026-04-30
lake-console sync-dataset adj_factor --from prod-raw-db --start-date 2026-04-01 --end-date 2026-04-30
```

## 9. 验收口径

1. Parquet 字段必须只有：
   - `ts_code`
   - `trade_date`
   - `adj_factor`
2. `trade_date` 必须是 Parquet `date`。
3. 非交易日脏行不得写入正式目录。
4. 单日或区间导出时，某个交易日的行数必须等于该日白名单 SQL 结果。
5. DuckDB 验证必须通过：

```sql
describe select * from read_parquet('<LAKE_ROOT>/raw_tushare/adj_factor/trade_date=2026-04-30/part-000.parquet');
```
