# 同花顺板块列表 Lake prod-raw-db 导出方案

状态：待评审

本文定义 `ths_index` 数据集从生产 `raw_tushare.ths_index` 只读导出到本地 Lake Parquet 的方案。该方案只覆盖 `prod-raw-db` 导出模式，不改变现有 Tushare API 下载链路。

## 1. 目标

把生产库中已经落在 `raw_tushare.ths_index` 的同花顺板块列表快照导出到本地 Lake。

核心目标：

- 导出的 Parquet 字段必须与 Tushare `ths_index` 输出参数一致。
- 只访问生产库 `raw_tushare.ths_index`。
- 禁止 `select *`，必须按字段白名单投影。
- 不把 Goldenshare 系统字段写入 Lake。
- `current_file` 必须保持“全量快照”语义，不能被局部筛选结果覆盖。

## 2. 数据集基本信息

| 项 | 值 |
| --- | --- |
| Lake dataset_key | `ths_index` |
| 显示名 | 同花顺板块列表 |
| 前端展示分组 | `board_theme` / 板块 / 题材 |
| Tushare api_name | `ths_index` |
| 源接口文档 | `docs/sources/tushare/股票数据/打板专题数据/0259_同花顺概念和行业指数.md` |
| 生产定义文件 | `src/foundation/datasets/definitions/board_hotspot.py` |
| 生产 raw 表 | `raw_tushare.ths_index` |
| Lake raw 目标路径 | `raw_tushare/ths_index/current/part-000.parquet` |
| Lake manifest 路径 | `manifest/board_universe/tushare_ths_index.parquet` |
| 布局 | `current_file` |
| 写入策略 | `replace_file` |
| 是否双落盘 manifest | 是 |
| 第一阶段写入范围 | 全量 current 快照 + 对应 manifest 快照 |

## 3. 字段白名单

| 字段 | Tushare 输出类型 | raw 表类型 | Lake 类型 | 是否导出 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `ts_code` | `str` | `varchar(16)` | `string` | 是 | 板块代码 |
| `name` | `str` | `varchar(128)` | `string` | 是 | 板块名称 |
| `count` | `int` | `integer` | `int64` | 是 | 成分个数 |
| `exchange` | `str` | `varchar(16)` | `string` | 是 | 市场类型 |
| `list_date` | `str`，`YYYYMMDD` | `date` | `date` | 是 | 上市日期 |
| `type` | `str` | `varchar(32)` | `string` | 是 | 板块类型 |

明确禁止导出的生产 raw 表字段：

| 字段 | 禁止原因 |
| --- | --- |
| `api_name` | Goldenshare 系统字段，不是 Tushare 输出参数 |
| `fetched_at` | Goldenshare 采集观测字段，不是 Tushare 输出参数 |
| `raw_payload` | Goldenshare 调试/追溯字段，不进入本地 Lake 标准 Parquet |

### 3.1 输入参数对齐

`ths_index` 源接口支持 `ts_code`、`exchange`、`type`，但第一阶段正式写入只允许全量 current 快照。

| 源站输入参数 | raw 表过滤字段 | 第一阶段是否开放写入 | 说明 |
| --- | --- | --- | --- |
| `ts_code` | `ts_code` | 否 | 仅保留为后续调试能力候选 |
| `exchange` | `exchange` | 否 | 同上 |
| `type` | `type` | 否 | 同上 |

结论：

1. 第一阶段不开放筛选写入命令。
2. 同花顺板块列表是“完整代码池快照”，不允许局部覆盖正式 current 文件。

## 4. 生产 raw 表差异审计

`raw_tushare.ths_index` 当前主键为：

```text
(ts_code)
```

与 Lake 目标模型相比，存在以下需要显式处理的差异：

| 差异 | 处理方式 |
| --- | --- |
| `list_date` 在源站文档中是字符串，在 raw 表中是 `date` | Lake Parquet 内部字段统一写为 `date` |
| Python 模型属性名是 `type_`，数据库列名是 `type` | SQL 投影必须使用真实列名 `type`，Lake 字段名也保持源站 `type` |
| `count` 在 raw 表中是 `integer` | Lake 统一写为 `int64`，减少 DuckDB 与未来扩展的不确定性 |
| raw 表存在系统字段 | 严格排除，不进入 Lake |

线上真实审计（2026-05-04）：

1. `count(*) = 1724`
2. `api_name <> 'ths_index'` 的异常行数为 `0`
3. `ts_code is null` 的异常行数为 `0`
4. 线上真实列顺序与当前文档白名单一致，额外系统字段仅有：
   - `api_name`
   - `fetched_at`
   - `raw_payload`

## 5. 读取方式

### 5.1 读取模式结论

| 评审项 | 结论 | 说明 |
| --- | --- | --- |
| 读取模式 | `full_fetchall` | 线上实库 `count(*) = 1724`，属于小快照 |
| SQL 次数估算 | 1 | 一条全量白名单查询 |
| DB 连接次数估算 | 1 | 单连接、只读事务 |
| 最大内存边界 | 低 | 当前总量在单次快照级别 |
| 写入粒度 | 单文件 | `replace_file` |
| 进度输出粒度 | fetched / writing / done | 小快照即可 |

### 5.2 允许的查询方式

```sql
select
  ts_code,
  name,
  count,
  exchange,
  list_date,
  type
from raw_tushare.ths_index
order by ts_code;
```

禁止：

```sql
select * from raw_tushare.ths_index;
```

## 6. 写入策略

必须双落盘，且两份文件来自同一次查询结果：

```text
raw_tushare/ths_index/current/part-000.parquet
manifest/board_universe/tushare_ths_index.parquet
```

执行规则：

1. 只支持全量替换正式 current 文件和对应 manifest 文件。
2. 查询返回 0 行时，不覆盖已有正式文件，也不覆盖 manifest。
3. manifest 与 raw current 使用同一份字段白名单与同一份行集。
4. 写入仍必须走 `_tmp -> validate -> replace`。

## 7. 命令设计

```bash
lake-console plan-sync ths_index --from prod-raw-db
lake-console sync-dataset ths_index --from prod-raw-db
```

该命令完成后应同时更新：

```text
raw_tushare/ths_index/current/part-000.parquet
manifest/board_universe/tushare_ths_index.parquet
```

第一阶段不开放 `--exchange`、`--type`、`--ts-code` 正式写入。

## 8. 配置与权限边界

- 只允许只读连接。
- 只允许访问 `raw_tushare.ths_index`。
- 禁止访问非 `raw_tushare` schema。
- 禁止 `select *`。
- 禁止导出非字段白名单字段。

## 9. 验收口径

### 9.1 字段验收

```text
ts_code, name, count, exchange, list_date, type
```

### 9.2 行数验收

```sql
select count(*)
from raw_tushare.ths_index;
```

raw current 与 manifest 文件都必须匹配该行数。

### 9.3 DuckDB 验收

```bash
duckdb -c "
describe
select *
from read_parquet('<LAKE_ROOT>/raw_tushare/ths_index/current/part-000.parquet');
"
```

重点确认：

1. `list_date` 是 `DATE`。
2. `count` 是 `BIGINT` 或等价整型。
3. Lake 字段名是 `type`，不是 `type_`。
4. raw current 与 manifest 文件 schema 一致、行数一致。
