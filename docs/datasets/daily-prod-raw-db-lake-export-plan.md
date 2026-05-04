# 股票日线 Lake prod-raw-db 导出方案

状态：已实现；`trade_date` Parquet 内部字段统一为 date

本文定义 `daily` 数据集从生产 `raw_tushare.daily` 只读导出到本地 Lake Parquet 的方案。该方案只覆盖 `daily`，不扩展到其他数据集，不改变现有 Tushare API 下载链路。

## 1. 目标

把生产库中已经落在 `raw_tushare.daily` 的 Tushare 原始日线数据，按 Lake Console 的文件布局导出成本地 Parquet。

核心目标：

- 避免本地重复请求 Tushare API。
- 导出的 Parquet 字段必须与 Tushare `daily` 输出参数一致。
- 只访问生产库 `raw_tushare.daily`，禁止访问 Ops、Core、Biz、App 等系统表。
- 禁止 `select *`，必须按字段白名单投影。
- 不把 Goldenshare 系统字段写入 Lake。
- 与现有 `daily` Tushare API 同步链路保持同一 Parquet schema，尤其是 `trade_date` 必须统一为 date 类型。

### 1.1 `trade_date` 统一口径

`daily` 的 Lake 日期模型统一为：

```text
目录分区：trade_date=YYYY-MM-DD
Parquet 字段：trade_date: date
```

执行含义：

1. prod-raw-db 导出时，生产库 `raw_tushare.daily.trade_date` 原本就是 `date`，应直接写入 Parquet date。
2. Tushare API 同步链路也必须同步调整为 Parquet date，不能继续写 string。
3. 同一个 `raw_tushare/daily` 目录下不允许混合 string/date 两种 `trade_date` schema。
4. 如本地已有旧 string 分区，必须通过重跑覆盖或单独 schema migration 收口。

## 2. 数据集基本信息

| 项 | 值 |
| --- | --- |
| Lake dataset_key | `daily` |
| 显示名 | 股票日线 |
| Tushare api_name | `daily` |
| 源接口文档 | `docs/sources/tushare/股票数据/行情数据/0027_A股日线行情.md` |
| 生产 raw 表 | `raw_tushare.daily` |
| Lake 目标层 | `raw` |
| Lake 目标路径 | `raw_tushare/daily/trade_date=YYYY-MM-DD/part-000.parquet` |
| 分区字段 | `trade_date` |
| 写入策略 | `replace_partition` |
| 第一阶段同步粒度 | 单交易日 |
| 第二阶段同步粒度 | 日期区间逐日导出 |

## 3. 字段白名单

导出字段必须严格等于下表，不允许多字段，也不允许少字段。

| 字段 | Tushare 输出类型 | raw 表类型 | Lake 类型 | 是否导出 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `ts_code` | `str` | `varchar(16)` | `string` | 是 | 股票代码 |
| `trade_date` | `str`，`YYYYMMDD` | `date` | `date` | 是 | 交易日期，Parquet 内部字段统一写为 date；目录分区值仍使用 `YYYY-MM-DD` |
| `open` | `float` | `numeric(18,4)` | `double` | 是 | 开盘价 |
| `high` | `float` | `numeric(18,4)` | `double` | 是 | 最高价 |
| `low` | `float` | `numeric(18,4)` | `double` | 是 | 最低价 |
| `close` | `float` | `numeric(18,4)` | `double` | 是 | 收盘价 |
| `pre_close` | `float` | `numeric(18,4)` | `double` | 是 | 昨收价 |
| `change` | `float` | `numeric(18,4)` | `double` | 是 | 涨跌额，保持 Tushare 原始字段名 |
| `pct_chg` | `float` | `numeric(10,4)` | `double` | 是 | 涨跌幅 |
| `vol` | `float` | `numeric(20,4)` | `double` | 是 | 成交量，单位手 |
| `amount` | `float` | `numeric(20,4)` | `double` | 是 | 成交额，单位千元 |

明确禁止导出的生产 raw 表字段：

| 字段 | 禁止原因 |
| --- | --- |
| `api_name` | Goldenshare 系统字段，不是 Tushare 输出参数 |
| `fetched_at` | Goldenshare 采集观测字段，不是 Tushare 输出参数 |
| `raw_payload` | Goldenshare 调试/追溯字段，不进入本地 Lake 标准 Parquet |

## 4. 生产 raw 表差异审计

`raw_tushare.daily` 当前主键为：

```text
(ts_code, trade_date)
```

与 Lake 目标模型相比，存在以下需要显式处理的差异：

| 差异 | 处理方式 |
| --- | --- |
| raw 表 `trade_date` 是 `date`，Tushare 文档是 `YYYYMMDD` 字符串 | Lake Parquet 内部字段统一写为 date；目录分区值仍使用 `YYYY-MM-DD`，便于按日替换和文件扫描 |
| raw 表价格和成交字段是 `numeric` | 导出为 Parquet `double`，与当前 Lake `daily` 定义一致 |
| raw 表存在系统字段 | 严格排除，不进入 Lake |

## 5. 允许的查询方式

### 5.1 单日导出

只允许字段白名单投影：

```sql
select
  ts_code,
  trade_date,
  open,
  high,
  low,
  close,
  pre_close,
  change,
  pct_chg,
  vol,
  amount
from raw_tushare.daily
where trade_date = :trade_date
order by ts_code;
```

禁止：

```sql
select * from raw_tushare.daily;
```

### 5.2 区间导出

区间导出不应一次性把全区间加载进内存，也不应为每个交易日反复创建数据库连接。当前实现采用单连接区间流式读取，再按 `trade_date` 分组写入每日分区：

```text
start_date/end_date
  -> 展开日期列表
  -> 单连接只读事务
  -> 一条区间白名单查询
  -> cursor.fetchmany(...) 分批读取
  -> 按 trade_date 分组
  -> 每个日期独立 replace_partition
```

允许的区间查询仍必须使用字段白名单：

```sql
select
  ts_code,
  trade_date,
  open,
  high,
  low,
  close,
  pre_close,
  change,
  pct_chg,
  vol,
  amount
from raw_tushare.daily
where trade_date >= :start_date
  and trade_date <= :end_date
order by trade_date, ts_code;
```

执行约束：

1. 只能用只读事务。
2. 只能用字段白名单投影。
3. 不能 `fetchall()` 一次性加载全区间。
4. 内存中只缓存当前 `trade_date` 的行。
5. 本地交易日历中没有的日期不写入；生产 raw 没返回的交易日不覆盖已有分区，并记录 `skipped_replace=true`。

## 6. 写入策略

`daily` 写入 Lake 时继续使用当前 by-date 布局：

```text
raw_tushare/daily/
  trade_date=2026-04-24/
    part-000.parquet
```

单日导出成功后，只替换对应 `trade_date` 分区，不影响其他日期。

如果生产 raw 查询返回 0 行：

- 默认不覆盖已有 Lake 分区。
- 命令输出必须明确提示 `fetched=0 written=0 skipped_replace=true`。
- 后续如需要“强制清空分区”，必须单独设计显式参数，本方案不包含。

## 7. 命令设计

现有 Tushare API 同步命令继续保留当前语义。

prod-raw-db 导出建议使用显式来源参数，避免用户误以为仍在请求 Tushare：

```bash
lake-console plan-sync daily --from prod-raw-db --trade-date 2026-04-24
lake-console sync-dataset daily --from prod-raw-db --trade-date 2026-04-24
```

区间导出建议命令：

```bash
lake-console plan-sync daily --from prod-raw-db --start-date 2026-04-01 --end-date 2026-04-30
lake-console sync-dataset daily --from prod-raw-db --start-date 2026-04-01 --end-date 2026-04-30
```

本轮实现同时覆盖单日导出与区间导出。区间导出只负责展开本地交易日历中的开市日，并逐日执行与单日导出相同的只读复制逻辑。

## 8. 配置与权限边界

prod-raw-db 连接配置必须来自本地配置文件或环境变量，不允许写入仓库。

建议配置项：

```text
GOLDENSHARE_PROD_RAW_DB_URL=...
```

本地配置文件也支持同名语义配置：

```toml
prod_raw_db_url = "postgresql://readonly-user:...@host:5432/goldenshare"
```

安全规则：

- 只允许只读连接。
- 只允许访问 `raw_tushare.daily`。
- 禁止访问 `ops`、`core`、`core_serving`、`core_serving_light`、`biz`、`app`、`platform` 等 schema。
- 禁止 `select *`。
- 禁止导出非字段白名单字段。
- 前端不直接连接生产库，只展示命令示例和本地文件事实。

## 9. 验收口径

### 9.1 字段验收

导出 Parquet 必须只包含：

```text
ts_code, trade_date, open, high, low, close, pre_close, change, pct_chg, vol, amount
```

不得包含：

```text
api_name, fetched_at, raw_payload
```

### 9.2 行数验收

单日导出后，Lake 分区行数应等于生产 raw 表白名单查询行数：

```sql
select count(*)
from raw_tushare.daily
where trade_date = :trade_date;
```

### 9.3 样本验收

按 `ts_code` 抽样对比至少 10 条：

- `open`
- `high`
- `low`
- `close`
- `pre_close`
- `change`
- `pct_chg`
- `vol`
- `amount`

### 9.4 DuckDB 验收

示例：

```sql
select count(*)
from read_parquet('raw_tushare/daily/trade_date=2026-04-24/*.parquet');
```

## 10. 测试门禁

实现时至少补齐以下测试：

- SQL 投影测试：确认不会生成 `select *`。
- 表白名单测试：`daily` 只能映射到 `raw_tushare.daily`。
- 字段白名单测试：导出字段与 Lake catalog `daily` 字段一致。
- 系统字段排除测试：`api_name`、`fetched_at`、`raw_payload` 不会进入结果。
- 单日写入测试：只替换目标 `trade_date` 分区。
- 空结果测试：默认不覆盖已有分区。
- docs 检查：`python3 scripts/check_docs_integrity.py`。

## 11. 实施里程碑

### M1：方案评审

- 确认 `daily` 作为第一条 prod-raw-db 导出链路。
- 确认字段白名单和排除字段。
- 确认命令参数使用 `--from prod-raw-db`。

### M2：prod-raw-db 只读基础设施

- 新增本地配置读取。
- 新增 raw 表白名单。
- 新增字段白名单 SQL builder。
- 禁止 `select *`。

### M3：daily 单日导出

- 实现 `daily --from prod-raw-db --trade-date`。
- 写入 by-date 分区。
- 输出 `fetched/written/skipped_replace`。

### M4：daily 区间导出

- 支持 `start_date/end_date`。
- 单连接区间流式读取，按 `trade_date` 分组导出。
- 每日独立写入与进度输出。

### M5：命令示例与前端展示

- 在 Lake command catalog 中补充 prod-raw-db 示例。
- 前端命令示例页展示 prod-raw-db 来源说明。

## 12. 风险

| 风险 | 影响 | 控制方式 |
| --- | --- | --- |
| 误访问生产非 raw 表 | 高 | 表白名单 + schema 白名单 + 测试门禁 |
| `select *` 带出系统字段 | 高 | SQL builder 禁止星号，字段白名单生成投影 |
| 生产 raw 某日数据不完整 | 中 | 导出只能保证复制 raw 事实；命令摘要要展示行数，后续可接审计 |
| 空结果覆盖已有分区 | 中 | 默认不覆盖，除非未来设计显式强制参数 |
| Decimal 转 double 精度差异 | 低 | 与当前 Lake `daily` 类型一致，验收时允许数值等价比较 |

## 13. 本方案不做的事

- 不访问远程 `ops` 状态表。
- 不访问 `core` / `core_serving`。
- 不引入前端直连数据库。
- 不改变现有 Tushare API 下载实现。
- 不新增 `daily` research 层。
- 不把 `api_name`、`fetched_at`、`raw_payload` 写入 Lake。
