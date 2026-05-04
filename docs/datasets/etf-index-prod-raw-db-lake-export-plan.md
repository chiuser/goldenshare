# ETF 跟踪指数 Lake prod-raw-db 导出方案

状态：待评审

本文定义 `etf_index` 数据集从生产 `raw_tushare.etf_index` 只读导出到本地 Lake Parquet 的方案。该方案只覆盖 `prod-raw-db` 导出模式，不改变现有 Tushare API 下载链路。

## 1. 目标

把生产库中已经落在 `raw_tushare.etf_index` 的 Tushare 原始 ETF 跟踪指数数据，按 Lake Console 的快照布局导出成本地 Parquet。

核心目标：

- 导出的 Parquet 字段必须与 Tushare `etf_index` 输出参数一致。
- 只访问生产库 `raw_tushare.etf_index`。
- 禁止 `select *`，必须按字段白名单投影。
- 不把 Goldenshare 系统字段写入 Lake。
- `current_file` 必须保持“全量快照”语义，不能被局部筛选结果覆盖。

## 2. 数据集基本信息

| 项 | 值 |
| --- | --- |
| Lake dataset_key | `etf_index` |
| 显示名 | ETF 跟踪指数 |
| 前端展示分组 | `etf_fund` / ETF基金 |
| Tushare api_name | `etf_index` |
| 源接口文档 | `docs/sources/tushare/ETF专题/0386_ETF基准指数列表.md` |
| 生产定义文件 | `src/foundation/datasets/definitions/index_series.py` |
| 生产 raw 表 | `raw_tushare.etf_index` |
| Lake 目标层 | `raw_tushare` |
| Lake raw 目标路径 | `raw_tushare/etf_index/current/part-000.parquet` |
| Lake manifest 路径 | `manifest/etf_reference/tushare_etf_index.parquet` |
| 布局 | `current_file` |
| 写入策略 | `replace_file` |
| 是否双落盘 manifest | 是 |
| 第一阶段写入范围 | 全量 current 快照 + 对应 manifest 快照 |

## 3. 字段白名单

| 字段 | Tushare 输出类型 | raw 表类型 | Lake 类型 | 是否导出 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `ts_code` | `str` | `varchar(16)` | `string` | 是 | 指数代码 |
| `indx_name` | `str` | `varchar(128)` | `string` | 是 | 指数全称 |
| `indx_csname` | `str` | `varchar(128)` | `string` | 是 | 指数简称 |
| `pub_party_name` | `str` | `varchar(128)` | `string` | 是 | 指数发布机构 |
| `pub_date` | `str`，`YYYYMMDD` | `date` | `date` | 是 | 指数发布日期 |
| `base_date` | `str`，`YYYYMMDD` | `date` | `date` | 是 | 指数基日 |
| `bp` | `float` | `numeric(12,6)` | `double` | 是 | 指数基点 |
| `adj_circle` | `str` | `varchar(64)` | `string` | 是 | 调整周期 |

明确禁止导出的生产 raw 表字段：

| 字段 | 禁止原因 |
| --- | --- |
| `api_name` | Goldenshare 系统字段，不是 Tushare 输出参数 |
| `fetched_at` | Goldenshare 采集观测字段，不是 Tushare 输出参数 |
| `raw_payload` | Goldenshare 调试/追溯字段，不进入本地 Lake 标准 Parquet |

### 3.1 输入参数对齐

`etf_index` 源接口输入包括 `ts_code`、`pub_date`、`base_date`，但第一阶段正式写入只允许全量 current 快照。

| 源站输入参数 | raw 表过滤字段 | 第一阶段是否开放写入 | 说明 |
| --- | --- | --- | --- |
| `ts_code` | `ts_code` | 否 | 仅作为后续调试能力候选 |
| `pub_date` | `pub_date` | 否 | 同上 |
| `base_date` | `base_date` | 否 | 同上 |

结论：

1. 第一阶段不开放筛选写入命令。
2. 任何局部导出如需落地，必须使用独立 debug 路径，不能替换正式 current 文件。

## 4. 生产 raw 表差异审计

`raw_tushare.etf_index` 当前主键为：

```text
(ts_code)
```

与 Lake 目标模型相比，存在以下需要显式处理的差异：

| 差异 | 处理方式 |
| --- | --- |
| `pub_date`、`base_date` 在源站文档中是字符串，在 raw 表中是 `date` | Lake Parquet 内部字段统一写为 `date` |
| `bp` 在 raw 表中是 `numeric(12,6)` | 导出为 Parquet `double` |
| raw 表存在系统字段 | 严格排除，不进入 Lake |

线上真实审计（2026-05-04）：

1. `count(*) = 1495`
2. `api_name <> 'etf_index'` 的异常行数为 `0`
3. `ts_code is null` 的异常行数为 `0`
4. 线上真实列顺序与当前文档白名单一致，额外系统字段仅有：
   - `api_name`
   - `fetched_at`
   - `raw_payload`

## 5. 读取方式

### 5.1 读取模式结论

| 评审项 | 结论 | 说明 |
| --- | --- | --- |
| 读取模式 | `full_fetchall` | 线上实库 `count(*) = 1495`，属于小快照 |
| SQL 次数估算 | 1 | 一条全量白名单查询 |
| DB 连接次数估算 | 1 | 单连接、只读事务 |
| 最大内存边界 | 低 | 数千行级别，可直接装入内存 |
| 写入粒度 | 单文件 | `replace_file` |
| 进度输出粒度 | fetched / writing / done | 小快照无需复杂分段进度 |

### 5.2 允许的查询方式

```sql
select
  ts_code,
  indx_name,
  indx_csname,
  pub_party_name,
  pub_date,
  base_date,
  bp,
  adj_circle
from raw_tushare.etf_index
order by ts_code;
```

禁止：

```sql
select * from raw_tushare.etf_index;
```

## 6. 写入策略

必须双落盘，且两份文件来自同一次查询结果：

```text
raw_tushare/etf_index/current/part-000.parquet
manifest/etf_reference/tushare_etf_index.parquet
```

执行规则：

1. 只支持全量替换正式 current 文件和对应 manifest 文件。
2. 查询返回 0 行时，不覆盖已有正式文件，也不覆盖 manifest。
3. manifest 与 raw current 使用同一份字段白名单与同一份行集。
4. 写入仍必须走 `_tmp -> validate -> replace`。

## 7. 命令设计

第一阶段只保留全量命令：

```bash
lake-console plan-sync etf_index --from prod-raw-db
lake-console sync-dataset etf_index --from prod-raw-db
```

该命令完成后应同时更新：

```text
raw_tushare/etf_index/current/part-000.parquet
manifest/etf_reference/tushare_etf_index.parquet
```

不开放 `--ts-code`、`--pub-date`、`--base-date` 写正式 current 文件。

## 8. 配置与权限边界

- 只允许只读连接。
- 只允许访问 `raw_tushare.etf_index`。
- 禁止访问非 `raw_tushare` schema。
- 禁止 `select *`。
- 禁止导出非字段白名单字段。

## 9. 验收口径

### 9.1 字段验收

```text
ts_code, indx_name, indx_csname, pub_party_name, pub_date, base_date, bp, adj_circle
```

### 9.2 行数验收

```sql
select count(*)
from raw_tushare.etf_index;
```

raw current 与 manifest 文件都必须匹配该行数。

### 9.3 DuckDB 验收

```bash
duckdb -c "
describe
select *
from read_parquet('<LAKE_ROOT>/raw_tushare/etf_index/current/part-000.parquet');
"
```

重点确认：

1. `pub_date`、`base_date` 是 `DATE`。
2. `bp` 是 `DOUBLE`。
3. 没有 Goldenshare 系统字段。
4. raw current 与 manifest 文件 schema 一致、行数一致。
