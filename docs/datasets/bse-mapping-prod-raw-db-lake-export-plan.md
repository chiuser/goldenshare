# 北交所新旧代码对照 Lake prod-raw-db 导出方案

状态：已落地

本文定义 `bse_mapping` 数据集从生产 `raw_tushare.bse_mapping` 只读导出到本地 Lake Parquet 的方案。该方案只覆盖 `prod-raw-db` 导出模式，不改变现有生产 Tushare 下载链路。

## 1. 目标

把生产库中已经落在 `raw_tushare.bse_mapping` 的北交所新旧代码对照快照导出到本地 Lake，并同时生成正式 current 文件与本地 reference manifest。

核心目标：

- 避免本地重复请求 Tushare `bse_mapping` 接口。
- 导出的 Parquet 字段必须与 Tushare `bse_mapping` 输出参数一致。
- 只访问生产库 `raw_tushare.bse_mapping`，不访问 `ops`、`core`、`core_serving`、`core_serving_light` 等其他 schema。
- 禁止 `select *`，必须按字段白名单投影。
- 不把 Goldenshare 系统字段写入 Lake。
- `current_file` 必须保持“全量快照”语义，不能被局部筛选结果覆盖。

## 2. 数据集基本信息

| 项 | 值 |
| --- | --- |
| Lake dataset_key | `bse_mapping` |
| 显示名 | 北交所新旧代码对照 |
| 前端展示分组 | `reference_data` / A股基础数据 |
| Tushare api_name | `bse_mapping` |
| 源接口文档 | `docs/sources/tushare/股票数据/基础数据/0375_北交所新旧代码对照表.md` |
| 生产定义文件 | `src/foundation/datasets/definitions/reference_master.py` |
| 生产 raw 表 | `raw_tushare.bse_mapping` |
| 生产 serving 表 | `core_serving_light.bse_mapping` |
| Lake raw 目标路径 | `raw_tushare/bse_mapping/current/part-000.parquet` |
| Lake manifest 路径 | `manifest/security_reference/tushare_bse_mapping.parquet` |
| 布局 | `current_file` |
| 写入策略 | `replace_file` |
| 是否双落盘 manifest | 是 |
| 第一阶段写入范围 | 全量 current 快照 + 对应 reference manifest 快照 |

## 3. 字段白名单

导出字段必须严格等于下表，不允许多字段，也不允许少字段。

| 字段 | Tushare 输出类型 | raw 表类型 | Lake 类型 | 是否导出 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `name` | `str` | `varchar(128)` | `string` | 是 | 股票名称 |
| `o_code` | `str` | `varchar(16)` | `string` | 是 | 旧代码 |
| `n_code` | `str` | `varchar(16)` | `string` | 是 | 新代码 |
| `list_date` | `str`，`YYYYMMDD` | `date` | `date` | 是 | 上市日期 |

明确禁止导出的生产 raw 表字段：

| 字段 | 禁止原因 |
| --- | --- |
| `api_name` | Goldenshare 系统字段，不是 Tushare 输出参数 |
| `fetched_at` | Goldenshare 采集观测字段，不是 Tushare 输出参数 |
| `raw_payload` | Goldenshare 调试/追溯字段，不进入本地 Lake 标准 Parquet |

### 3.1 输入参数对齐

`bse_mapping` 源接口支持 `o_code`、`n_code` 过滤，但第一阶段正式写入只允许全量 current 快照。

| 源站输入参数 | raw 表过滤字段 | 第一阶段是否开放写入 | 说明 |
| --- | --- | --- | --- |
| `o_code` | `o_code` | 否 | 仅保留为后续调试能力候选 |
| `n_code` | `n_code` | 否 | 同上 |

结论：

1. 当前正式写入命令不开放任何筛选参数。
2. `bse_mapping` 是完整代码映射快照，不允许局部结果覆盖正式 current 文件。

## 4. 生产事实源审计

### 4.1 表结构与主键事实

`raw_tushare.bse_mapping` 当前主键语义为：

```text
(o_code, n_code)
```

线上真实审计（2026-05-10）：

1. `raw_tushare.bse_mapping` 存在，`count(*) = 248`
2. `count(distinct (o_code, n_code)) = 248`
3. `duplicate_rows = 0`
4. `list_date` 范围：`2020-07-27 ~ 2024-04-08`
5. 线上额外系统字段仅有：
   - `api_name`
   - `fetched_at`
   - `raw_payload`

### 4.2 raw 与 serving_light 对比

`core_serving_light.bse_mapping` 当前也存在，且线上真实审计结果为：

1. `count(*) = 248`
2. `count(distinct (o_code, n_code)) = 248`
3. `list_date` 范围同样为：`2020-07-27 ~ 2024-04-08`
4. 未发现比 `raw_tushare.bse_mapping` 更高质量的修复收益

结论：

1. 当前 Lake 事实源选择 `raw_tushare.bse_mapping`。
2. `core_serving_light.bse_mapping` 不作为 Lake 第一阶段事实源。

## 5. 读取方式

### 5.1 读取模式结论

| 评审项 | 结论 | 说明 |
| --- | --- | --- |
| 读取模式 | `full_fetchall` | 线上实库仅 `248` 行，适合一次性全量装入内存 |
| SQL 次数估算 | 1 | 一条全量白名单查询 |
| DB 连接次数估算 | 1 | 单连接、只读事务 |
| 最大内存边界 | 极低 | 数百行级别 |
| 写入粒度 | 单文件 | `replace_file` |
| 进度输出粒度 | fetched / writing / done | 小快照无需复杂分段进度 |

### 5.2 允许的查询方式

```sql
select
  name,
  o_code,
  n_code,
  list_date
from raw_tushare.bse_mapping
order by o_code, n_code;
```

禁止：

```sql
select * from raw_tushare.bse_mapping;
```

## 6. 写入策略

必须双落盘，且两份文件来自同一次查询结果：

```text
raw_tushare/bse_mapping/current/part-000.parquet
manifest/security_reference/tushare_bse_mapping.parquet
```

执行规则：

1. 只支持全量替换正式 current 文件和对应 manifest 文件。
2. 查询返回 `0` 行时，不覆盖已有正式文件，也不覆盖 manifest。
3. manifest 文件与 raw current 文件使用同一份字段白名单和同一份行集，不允许额外裁剪。
4. 写入仍必须走 `_tmp -> validate -> replace`。
5. `manifest/security_reference` 的用途是本地代码映射参考，不是执行 universe。

## 7. 命令设计

第一阶段只保留全量命令：

```bash
lake-console plan-sync bse_mapping --from prod-raw-db
lake-console sync-dataset bse_mapping --from prod-raw-db
```

该命令完成后应同时更新：

```text
raw_tushare/bse_mapping/current/part-000.parquet
manifest/security_reference/tushare_bse_mapping.parquet
```

不在第一阶段提供：

```bash
lake-console sync-dataset bse_mapping --from prod-raw-db --o-code 430198.BJ
lake-console sync-dataset bse_mapping --from prod-raw-db --n-code 830198.BJ
```

原因：这会把“全量 current 快照”错误替换成“局部筛选子集”。

## 8. 配置与权限边界

- 只允许只读连接。
- 只允许访问 `raw_tushare.bse_mapping`。
- 禁止访问 `ops`、`core`、`core_serving`、`core_serving_light`、`biz`、`app`、`platform` 等 schema。
- 禁止 `select *`。
- 禁止导出非字段白名单字段。
- 前端不直接连接生产库，只展示命令示例和本地文件事实。

## 9. 验收口径

### 9.1 字段验收

导出 Parquet 必须只包含：

```text
name, o_code, n_code, list_date
```

不得包含：

```text
api_name, fetched_at, raw_payload
```

### 9.2 行数验收

Lake current 文件与 manifest 文件行数都应等于生产 raw 表白名单查询行数：

```sql
select count(*)
from raw_tushare.bse_mapping;
```

### 9.3 主键验收

导出后必须满足：

```sql
select count(*) = count(distinct (o_code, n_code))
from read_parquet('<LAKE_ROOT>/raw_tushare/bse_mapping/current/part-000.parquet');
```

### 9.4 DuckDB 验收

```bash
duckdb -c "
describe
select *
from read_parquet('<LAKE_ROOT>/raw_tushare/bse_mapping/current/part-000.parquet');
"
```

重点确认：

1. `list_date` 是 `DATE`。
2. 没有 Goldenshare 系统字段。
3. raw current 与 manifest 文件 schema 一致、行数一致。
