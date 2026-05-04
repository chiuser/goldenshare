# 同花顺板块成分 Lake prod-raw-db 导出方案

状态：待评审

本文定义 `ths_member` 数据集从生产 `raw_tushare.ths_member` 只读导出到本地 Lake Parquet 的方案。该方案只覆盖 `prod-raw-db` 导出模式，不改变现有 Tushare API 下载链路。

## 1. 目标

把生产库中已经落在 `raw_tushare.ths_member` 的同花顺板块成分快照导出到本地 Lake。

核心目标：

- 导出的 Parquet 字段必须与 Tushare `ths_member` 输出参数一致。
- 只访问生产库 `raw_tushare.ths_member`。
- 禁止 `select *`，必须按字段白名单投影。
- 不把 Goldenshare 系统字段写入 Lake。
- `current_file` 必须保持“全量快照”语义，不能被局部筛选结果覆盖。

## 2. 数据集基本信息

| 项 | 值 |
| --- | --- |
| Lake dataset_key | `ths_member` |
| 显示名 | 同花顺板块成分 |
| 前端展示分组 | `board_theme` / 板块 / 题材 |
| Tushare api_name | `ths_member` |
| 源接口文档 | `docs/sources/tushare/股票数据/打板专题数据/0261_同花顺概念板块成分.md` |
| 生产定义文件 | `src/foundation/datasets/definitions/board_hotspot.py` |
| 生产 raw 表 | `raw_tushare.ths_member` |
| Lake raw 目标路径 | `raw_tushare/ths_member/current/part-000.parquet` |
| Lake manifest 路径 | `manifest/board_membership/tushare_ths_member.parquet` |
| 布局 | `current_file` |
| 写入策略 | `replace_file` |
| 是否双落盘 manifest | 是 |
| 第一阶段写入范围 | 全量 current 快照 + 对应 manifest 快照 |

## 3. 字段白名单

| 字段 | Tushare 输出类型 | raw 表类型 | Lake 类型 | 是否导出 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `ts_code` | `str` | `varchar(16)` | `string` | 是 | 板块代码 |
| `con_code` | `str` | `varchar(16)` | `string` | 是 | 股票代码 |
| `con_name` | `str` | `varchar(128)` | `string` | 是 | 股票名称 |
| `weight` | `float` | `numeric(12,6)` | `double` | 是 | 权重 |
| `in_date` | `str`，`YYYYMMDD` | `date` | `date` | 是 | 纳入日期 |
| `out_date` | `str`，`YYYYMMDD` | `date` | `date` | 是 | 剔除日期 |
| `is_new` | `str` | `varchar(8)` | `string` | 是 | 是否最新 |

明确禁止导出的生产 raw 表字段：

| 字段 | 禁止原因 |
| --- | --- |
| `api_name` | Goldenshare 系统字段，不是 Tushare 输出参数 |
| `fetched_at` | Goldenshare 采集观测字段，不是 Tushare 输出参数 |
| `raw_payload` | Goldenshare 调试/追溯字段，不进入本地 Lake 标准 Parquet |

### 3.1 输入参数对齐

`ths_member` 源接口支持 `ts_code`、`con_code`，但第一阶段正式写入只允许全量 current 快照。

| 源站输入参数 | raw 表过滤字段 | 第一阶段是否开放写入 | 说明 |
| --- | --- | --- | --- |
| `ts_code` | `ts_code` | 否 | 仅保留为后续调试能力候选 |
| `con_code` | `con_code` | 否 | 同上 |

结论：

1. 第一阶段不开放筛选写入命令。
2. `ths_member` 是完整板块成分快照，不能被某个板块或某只股票的子集覆盖。

## 4. 生产 raw 表差异审计

`raw_tushare.ths_member` 当前主键为：

```text
(ts_code, con_code)
```

与 Lake 目标模型相比，存在以下需要显式处理的差异：

| 差异 | 处理方式 |
| --- | --- |
| `in_date`、`out_date` 在源站文档中是字符串，在 raw 表中是 `date` | Lake Parquet 内部字段统一写为 `date` |
| `weight` 在 raw 表中是 `numeric(12,6)` | 导出为 Parquet `double` |
| raw 表存在系统字段 | 严格排除，不进入 Lake |

线上真实审计（2026-05-04）：

1. `count(*) = 308810`
2. `api_name <> 'ths_member'` 的异常行数为 `0`
3. `ts_code is null or con_code is null` 的异常行数为 `0`
4. 线上真实列顺序与当前文档白名单一致，额外系统字段仅有：
   - `api_name`
   - `fetched_at`
   - `raw_payload`

## 5. 读取方式

### 5.1 读取模式结论

| 评审项 | 结论 | 说明 |
| --- | --- | --- |
| 读取模式 | `range_streaming_cursor` | 线上实库 `count(*) = 308810`，必须使用流式读取，禁止 `fetchall` |
| SQL 次数估算 | 1 | 一条全量白名单查询 |
| DB 连接次数估算 | 1 | 单连接、只读事务、服务端游标 |
| 最大内存边界 | 中 | 必须按 `fetchmany` 控制批次，不一次性装入全部行 |
| 写入粒度 | 单文件 | `replace_file` |
| 进度输出粒度 | fetched_rows / writing / done | 需要比小快照更明确的读取进度 |

### 5.2 允许的查询方式

```sql
select
  ts_code,
  con_code,
  con_name,
  weight,
  in_date,
  out_date,
  is_new
from raw_tushare.ths_member
order by ts_code, con_code;
```

禁止：

```sql
select * from raw_tushare.ths_member;
```

执行约束：

1. 必须使用只读事务。
2. 必须使用字段白名单投影。
3. 必须使用服务端游标和 `fetchmany`。
4. 不允许对全量快照使用 `fetchall`。

## 6. 写入策略

必须双落盘，且两份文件来自同一次查询结果：

```text
raw_tushare/ths_member/current/part-000.parquet
manifest/board_membership/tushare_ths_member.parquet
```

执行规则：

1. 只支持全量替换正式 current 文件和对应 manifest 文件。
2. 查询返回 0 行时，不覆盖已有正式文件，也不覆盖 manifest。
3. manifest 与 raw current 使用同一份字段白名单与同一份行集。
4. 写入仍必须走 `_tmp -> validate -> replace`。

## 7. 命令设计

```bash
lake-console plan-sync ths_member --from prod-raw-db
lake-console sync-dataset ths_member --from prod-raw-db
```

该命令完成后应同时更新：

```text
raw_tushare/ths_member/current/part-000.parquet
manifest/board_membership/tushare_ths_member.parquet
```

第一阶段不开放 `--ts-code`、`--con-code` 正式写入。

## 8. 配置与权限边界

- 只允许只读连接。
- 只允许访问 `raw_tushare.ths_member`。
- 禁止访问非 `raw_tushare` schema。
- 禁止 `select *`。
- 禁止导出非字段白名单字段。

## 9. 验收口径

### 9.1 字段验收

```text
ts_code, con_code, con_name, weight, in_date, out_date, is_new
```

### 9.2 行数验收

```sql
select count(*)
from raw_tushare.ths_member;
```

raw current 与 manifest 文件都必须匹配该行数。

### 9.3 DuckDB 验收

```bash
duckdb -c "
describe
select *
from read_parquet('<LAKE_ROOT>/raw_tushare/ths_member/current/part-000.parquet');
"
```

重点确认：

1. `in_date`、`out_date` 是 `DATE`。
2. `weight` 是 `DOUBLE`。
3. 没有 Goldenshare 系统字段。
4. raw current 与 manifest 文件 schema 一致、行数一致。
