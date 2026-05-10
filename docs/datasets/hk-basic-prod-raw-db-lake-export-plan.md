# 港股基础信息 Lake prod-raw-db 导出方案

状态：已落地

本文定义 `hk_basic` 数据集从生产 `raw_tushare.hk_basic` 只读导出到本地 Lake Parquet 的方案。该方案只覆盖 `prod-raw-db` 导出模式，不改变现有生产 Tushare 下载链路。

## 1. 目标

把生产库中已经落在 `raw_tushare.hk_basic` 的港股基础信息快照导出到本地 Lake，并同时生成正式 current 文件与本地 security universe manifest。

核心目标：

- 避免本地重复请求 Tushare `hk_basic` 接口。
- 导出的 Parquet 字段必须与 Tushare `hk_basic` 输出参数一致。
- 只访问生产库 `raw_tushare.hk_basic`。
- 禁止 `select *`，必须按字段白名单投影。
- 不把 Goldenshare 系统字段写入 Lake。
- `current_file` 必须保持“全量快照”语义，不能被局部筛选结果覆盖。

## 2. 数据集基本信息

| 项 | 值 |
| --- | --- |
| Lake dataset_key | `hk_basic` |
| 显示名 | 港股基础信息 |
| 前端展示分组 | `reference_data` / 港股基础数据 |
| Tushare api_name | `hk_basic` |
| 源接口文档 | `docs/sources/tushare/港股数据/0191_港股列表.md` |
| 生产定义文件 | `src/foundation/datasets/definitions/reference_master.py` |
| 生产 raw 表 | `raw_tushare.hk_basic` |
| 生产 serving 表 | 无 |
| Lake raw 目标路径 | `raw_tushare/hk_basic/current/part-000.parquet` |
| Lake manifest 路径 | `manifest/security_universe/tushare_hk_basic.parquet` |
| 布局 | `current_file` |
| 写入策略 | `replace_file` |
| 是否双落盘 manifest | 是 |
| 第一阶段写入范围 | 全量 current 快照 + 对应 security universe manifest |

## 3. 字段白名单

导出字段必须严格等于下表，不允许多字段，也不允许少字段。

| 字段 | Tushare 输出类型 | raw 表类型 | Lake 类型 | 是否导出 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `ts_code` | `str` | `varchar(16)` | `string` | 是 | 港股代码 |
| `name` | `str` | `varchar(128)` | `string` | 是 | 股票简称 |
| `fullname` | `str` | `varchar(256)` | `string` | 是 | 公司全称 |
| `enname` | `str` | `varchar(256)` | `string` | 是 | 英文名称 |
| `cn_spell` | `str` | `varchar(128)` | `string` | 是 | 拼音 |
| `market` | `str` | `varchar(64)` | `string` | 是 | 市场类别 |
| `list_status` | `str` | `varchar(8)` | `string` | 是 | 上市状态 |
| `list_date` | `str`，`YYYYMMDD` | `date` | `date` | 是 | 上市日期 |
| `delist_date` | `str`，`YYYYMMDD` | `date` | `date` | 是 | 退市日期 |
| `trade_unit` | `float` | `integer` | `int64` | 是 | 交易单位 |
| `isin` | `str` | `varchar(32)` | `string` | 是 | ISIN代码 |
| `curr_type` | `str` | `varchar(16)` | `string` | 是 | 货币代码 |

明确禁止导出的生产 raw 表字段：

| 字段 | 禁止原因 |
| --- | --- |
| `api_name` | Goldenshare 系统字段，不是 Tushare 输出参数 |
| `fetched_at` | Goldenshare 采集观测字段，不是 Tushare 输出参数 |
| `raw_payload` | Goldenshare 调试/追溯字段，不进入本地 Lake 标准 Parquet |

### 3.1 输入参数对齐

`hk_basic` 源接口支持 `ts_code`、`list_status` 过滤，但第一阶段正式写入只允许全量 current 快照。

| 源站输入参数 | raw 表过滤字段 | 第一阶段是否开放写入 | 说明 |
| --- | --- | --- | --- |
| `ts_code` | `ts_code` | 否 | 仅保留为后续调试能力候选 |
| `list_status` | `list_status` | 否 | 当前远程 raw 现实上仅有 `L`，正式 current 仍只允许全量替换 |

结论：

1. 当前正式写入命令不开放任何筛选参数。
2. `hk_basic` 当前生产事实已经是“当前上市港股池快照”，Lake 首版按生产事实落盘，不额外伪造 `D/P` 状态集合。

## 4. 生产事实源审计

### 4.1 表结构与主键事实

`raw_tushare.hk_basic` 当前主键语义为：

```text
(ts_code)
```

线上真实审计（2026-05-10）：

1. `count(*) = 2732`
2. `count(distinct ts_code) = 2732`
3. `duplicate_rows = 0`
4. `list_status` 当前只有 `L`
5. `list_date` 范围：`1921-01-01 ~ 2026-04-17`
6. 线上额外系统字段仅有：
   - `api_name`
   - `fetched_at`
   - `raw_payload`

### 4.2 raw 与 serving 对比

当前远程生产库不存在：

```text
core_serving_light.hk_basic
```

结论：

1. 当前 Lake 事实源只能选择 `raw_tushare.hk_basic`。
2. 不存在比 raw 更优的远程 serving 事实源。

## 5. 读取方式

### 5.1 读取模式结论

| 评审项 | 结论 | 说明 |
| --- | --- | --- |
| 读取模式 | `full_fetchall` | 线上实库仅 `2732` 行，适合一次性装入内存 |
| SQL 次数估算 | 1 | 一条全量白名单查询 |
| DB 连接次数估算 | 1 | 单连接、只读事务 |
| 最大内存边界 | 低 | 数千行级别 |
| 写入粒度 | 单文件 | `replace_file` |
| 进度输出粒度 | fetched / writing / done | 小快照无需复杂分段进度 |

### 5.2 允许的查询方式

```sql
select
  ts_code,
  name,
  fullname,
  enname,
  cn_spell,
  market,
  list_status,
  list_date,
  delist_date,
  trade_unit,
  isin,
  curr_type
from raw_tushare.hk_basic
order by ts_code;
```

禁止：

```sql
select * from raw_tushare.hk_basic;
```

## 6. 写入策略

必须双落盘，且两份文件来自同一次查询结果：

```text
raw_tushare/hk_basic/current/part-000.parquet
manifest/security_universe/tushare_hk_basic.parquet
```

执行规则：

1. 只支持全量替换正式 current 文件和对应 manifest 文件。
2. 查询返回 `0` 行时，不覆盖已有正式文件，也不覆盖 manifest。
3. manifest 文件与 raw current 文件使用同一份字段白名单和同一份行集，不允许额外裁剪。
4. 写入仍必须走 `_tmp -> validate -> replace`。
5. `manifest/security_universe` 的用途是本地港股池辅助引用，不改变当前生产事实只含 `L` 状态的现实口径。

## 7. 命令设计

第一阶段只保留全量命令：

```bash
lake-console plan-sync hk_basic --from prod-raw-db
lake-console sync-dataset hk_basic --from prod-raw-db
```

该命令完成后应同时更新：

```text
raw_tushare/hk_basic/current/part-000.parquet
manifest/security_universe/tushare_hk_basic.parquet
```

不在第一阶段提供：

```bash
lake-console sync-dataset hk_basic --from prod-raw-db --list-status D
lake-console sync-dataset hk_basic --from prod-raw-db --ts-code 00001.HK
```

原因：这会把“全量 current 快照”错误替换成“局部筛选子集”。

## 8. 配置与权限边界

- 只允许只读连接。
- 只允许访问 `raw_tushare.hk_basic`。
- 禁止访问 `ops`、`core`、`core_serving`、`core_serving_light`、`biz`、`app`、`platform` 等 schema。
- 禁止 `select *`。
- 禁止导出非字段白名单字段。
- 前端不直接连接生产库，只展示命令示例和本地文件事实。

## 9. 验收口径

### 9.1 字段验收

导出 Parquet 必须只包含：

```text
ts_code, name, fullname, enname, cn_spell, market, list_status, list_date, delist_date, trade_unit, isin, curr_type
```

不得包含：

```text
api_name, fetched_at, raw_payload
```

### 9.2 行数验收

Lake current 文件与 manifest 文件行数都应等于生产 raw 表白名单查询行数：

```sql
select count(*)
from raw_tushare.hk_basic;
```

### 9.3 主键验收

导出后必须满足：

```sql
select count(*) = count(distinct ts_code)
from read_parquet('<LAKE_ROOT>/raw_tushare/hk_basic/current/part-000.parquet');
```

### 9.4 DuckDB 验收

```bash
duckdb -c "
describe
select *
from read_parquet('<LAKE_ROOT>/raw_tushare/hk_basic/current/part-000.parquet');
"
```

重点确认：

1. `list_date`、`delist_date` 是 `DATE`。
2. `trade_unit` 是整型。
3. 没有 Goldenshare 系统字段。
4. raw current 与 manifest 文件 schema 一致、行数一致。
