# ETF 基础信息 Lake prod-raw-db 导出方案

状态：待评审

本文定义 `etf_basic` 数据集从生产 `raw_tushare.etf_basic` 只读导出到本地 Lake Parquet 的方案。该方案只覆盖 `prod-raw-db` 导出模式，不改变现有 Tushare API 下载链路。

## 1. 目标

把生产库中已经落在 `raw_tushare.etf_basic` 的 Tushare 原始 ETF 基础信息，按 Lake Console 的快照布局导出成本地 Parquet。

核心目标：

- 避免本地重复请求 Tushare API。
- 导出的 Parquet 字段必须与 Tushare `etf_basic` 输出参数一致。
- 只访问生产库 `raw_tushare.etf_basic`，禁止访问 Ops、Core、Biz、App 等系统表。
- 禁止 `select *`，必须按字段白名单投影。
- 不把 Goldenshare 系统字段写入 Lake。
- `current_file` 必须保持“全量快照”语义，不能被局部筛选结果覆盖。

## 2. 数据集基本信息

| 项 | 值 |
| --- | --- |
| Lake dataset_key | `etf_basic` |
| 显示名 | ETF 基础信息 |
| 前端展示分组 | `reference_data` / A股基础数据 |
| Tushare api_name | `etf_basic` |
| 源接口文档 | `docs/sources/tushare/ETF专题/0385_ETF基础信息.md` |
| 生产定义文件 | `src/foundation/datasets/definitions/reference_master.py` |
| 生产 raw 表 | `raw_tushare.etf_basic` |
| Lake 目标层 | `raw_tushare` |
| Lake raw 目标路径 | `raw_tushare/etf_basic/current/part-000.parquet` |
| Lake manifest 路径 | `manifest/etf_universe/tushare_etf_basic.parquet` |
| 布局 | `current_file` |
| 写入策略 | `replace_file` |
| 是否双落盘 manifest | 是 |
| 第一阶段写入范围 | 全量 current 快照 + 对应 manifest 快照 |

## 3. 字段白名单

导出字段必须严格等于下表，不允许多字段，也不允许少字段。

| 字段 | Tushare 输出类型 | raw 表类型 | Lake 类型 | 是否导出 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `ts_code` | `str` | `varchar(16)` | `string` | 是 | 基金交易代码 |
| `csname` | `str` | `varchar(128)` | `string` | 是 | ETF 中文简称 |
| `extname` | `str` | `varchar(256)` | `string` | 是 | ETF 扩位简称 |
| `cname` | `str` | `varchar(256)` | `string` | 是 | 基金中文全称 |
| `index_code` | `str` | `varchar(16)` | `string` | 是 | ETF 基准指数代码 |
| `index_name` | `str` | `varchar(128)` | `string` | 是 | ETF 基准指数中文全称 |
| `setup_date` | `str`，`YYYYMMDD` | `date` | `date` | 是 | 设立日期 |
| `list_date` | `str`，`YYYYMMDD` | `date` | `date` | 是 | 上市日期 |
| `list_status` | `str` | `varchar(8)` | `string` | 是 | 存续状态 |
| `exchange` | `str` | `varchar(16)` | `string` | 是 | 交易所 |
| `mgr_name` | `str` | `varchar(128)` | `string` | 是 | 基金管理人简称 |
| `custod_name` | `str` | `varchar(128)` | `string` | 是 | 基金托管人名称 |
| `mgt_fee` | `float` | `numeric(12,6)` | `double` | 是 | 管理费 |
| `etf_type` | `str` | `varchar(64)` | `string` | 是 | 投资通道类型 |

明确禁止导出的生产 raw 表字段：

| 字段 | 禁止原因 |
| --- | --- |
| `api_name` | Goldenshare 系统字段，不是 Tushare 输出参数 |
| `fetched_at` | Goldenshare 采集观测字段，不是 Tushare 输出参数 |
| `raw_payload` | Goldenshare 调试/追溯字段，不进入本地 Lake 标准 Parquet |

### 3.1 输入参数对齐

`etf_basic` 源接口虽然支持筛选参数，但第一阶段 `prod-raw-db` 正式写入只允许全量 current 快照，不开放筛选子集覆盖正式文件。

| 源站输入参数 | raw 表过滤字段 | 第一阶段是否开放写入 | 说明 |
| --- | --- | --- | --- |
| `ts_code` | `ts_code` | 否 | 仅保留为后续调试能力候选 |
| `index_code` | `index_code` | 否 | 同上 |
| `list_date` | `list_date` | 否 | 同上 |
| `list_status` | `list_status` | 否 | 同上 |
| `exchange` | `exchange` | 否 | 同上 |
| `mgr` | `mgr_name` | 否 | 源站参数名与 raw 输出字段名不同，后续若开放需显式映射 |

结论：

1. 当前正式写入命令不开放任何筛选参数。
2. 如未来需要调试子集导出，必须单独设计 debug 输出路径，不能覆盖 `current/part-000.parquet`。

## 4. 生产 raw 表差异审计

`raw_tushare.etf_basic` 当前主键为：

```text
(ts_code)
```

与 Lake 目标模型相比，存在以下需要显式处理的差异：

| 差异 | 处理方式 |
| --- | --- |
| `setup_date`、`list_date` 在源站文档中是 `YYYYMMDD` 字符串，在 raw 表中是 `date` | Lake Parquet 内部字段统一写为 `date` |
| `mgt_fee` 在 raw 表中是 `numeric(12,6)` | 导出为 Parquet `double` |
| 源站输入参数 `mgr` 对应 raw 输出字段 `mgr_name` | 本阶段不开放筛选写入；后续若开放需做显式映射 |
| raw 表存在系统字段 | 严格排除，不进入 Lake |

线上真实审计（2026-05-04）：

1. `count(*) = 3266`
2. `api_name <> 'etf_basic'` 的异常行数为 `0`
3. `ts_code is null` 的异常行数为 `0`
4. 线上真实列顺序与当前文档白名单一致，额外系统字段仅有：
   - `api_name`
   - `fetched_at`
   - `raw_payload`

## 5. 读取方式

### 5.1 读取模式结论

| 评审项 | 结论 | 说明 |
| --- | --- | --- |
| 读取模式 | `full_fetchall` | 线上实库 `count(*) = 3266`，仍属于小快照，直接一次性装入内存收益更高 |
| SQL 次数估算 | 1 | 一条全量白名单查询 |
| DB 连接次数估算 | 1 | 单连接、只读事务 |
| 最大内存边界 | 低 | 数千行级别，可直接装入内存 |
| 写入粒度 | 单文件 | `replace_file` |
| 进度输出粒度 | fetched / writing / done | 小快照无需复杂分段进度 |

### 5.2 允许的查询方式

只允许字段白名单投影：

```sql
select
  ts_code,
  csname,
  extname,
  cname,
  index_code,
  index_name,
  setup_date,
  list_date,
  list_status,
  exchange,
  mgr_name,
  custod_name,
  mgt_fee,
  etf_type
from raw_tushare.etf_basic
order by ts_code;
```

禁止：

```sql
select * from raw_tushare.etf_basic;
```

## 6. 写入策略

`etf_basic` 写入 Lake 时必须双落盘，且两份文件来自同一次查询结果，不允许不同 run_id 混写：

```text
raw_tushare/etf_basic/current/part-000.parquet
manifest/etf_universe/tushare_etf_basic.parquet
```

执行规则：

1. 只支持全量替换正式 current 文件和对应 manifest 文件。
2. 查询返回 0 行时，不覆盖已有正式文件，也不覆盖 manifest。
3. manifest 文件与 raw current 文件使用同一份字段白名单和同一份行集，不允许做裁剪投影。
4. 写入仍必须走 `_tmp -> validate -> replace`。
5. manifest 仅改变路径与用途说明，不改变数据事实。

## 7. 命令设计

第一阶段只保留全量命令：

```bash
lake-console plan-sync etf_basic --from prod-raw-db
lake-console sync-dataset etf_basic --from prod-raw-db
```

该命令完成后应同时更新：

```text
raw_tushare/etf_basic/current/part-000.parquet
manifest/etf_universe/tushare_etf_basic.parquet
```

不在第一阶段提供：

```bash
lake-console sync-dataset etf_basic --from prod-raw-db --exchange SZ
```

原因：这会把“全量 current 快照”错误替换成“局部筛选子集”。

## 8. 配置与权限边界

- 只允许只读连接。
- 只允许访问 `raw_tushare.etf_basic`。
- 禁止访问 `ops`、`core`、`core_serving`、`core_serving_light`、`biz`、`app`、`platform` 等 schema。
- 禁止 `select *`。
- 禁止导出非字段白名单字段。
- 前端不直接连接生产库，只展示命令示例和本地文件事实。

## 9. 验收口径

### 9.1 字段验收

导出 Parquet 必须只包含：

```text
ts_code, csname, extname, cname, index_code, index_name, setup_date, list_date, list_status, exchange, mgr_name, custod_name, mgt_fee, etf_type
```

不得包含：

```text
api_name, fetched_at, raw_payload
```

### 9.2 行数验收

Lake current 文件与 manifest 文件行数都应等于生产 raw 表白名单查询行数：

```sql
select count(*)
from raw_tushare.etf_basic;
```

### 9.3 DuckDB 验收

```bash
duckdb -c "
describe
select *
from read_parquet('<LAKE_ROOT>/raw_tushare/etf_basic/current/part-000.parquet');
"
```

重点确认：

1. `setup_date`、`list_date` 是 `DATE`。
2. `mgt_fee` 是 `DOUBLE`。
3. 没有 Goldenshare 系统字段。
4. raw current 与 manifest 文件 schema 一致、行数一致。
